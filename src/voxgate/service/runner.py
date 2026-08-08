import uuid
from langgraph.types import Command

class CaseRunner:
    def __init__(self, packs, checkpointer_factory, store, bus):
        self.packs, self.store, self.bus = packs, store, bus
        checkpointer = checkpointer_factory()
        from voxgate.graph.build import build_graph
        self.graphs = {pid: build_graph(p, checkpointer) for pid, p in packs.items()}

    def _cfg(self, case_id):
        return {"configurable": {"thread_id": case_id}}

    def _sync(self, case_id, pack_id):
        graph = self.graphs[pack_id]
        snap = graph.get_state(self._cfg(case_id))
        v = snap.values
        pending = None
        for task in snap.tasks:
            if task.interrupts:
                pending = task.interrupts[0].value
        case = {"case_id": case_id, "pack_id": pack_id,
                "status": v.get("status", "processing"),
                "fields": v.get("fields", {}),
                "score": v.get("score"), "decision": v.get("decision"),
                "check_results": v.get("check_results", []),
                "audit": v.get("audit", []),
                "interrupt": pending}
        self.store.upsert(case)
        self.bus.publish(case_id, {"kind": "state", "case": self.store.get(case_id)})
        return self.store.get(case_id)

    def _mark_needs_attention(self, case_id, pack_id, e):
        self.store.upsert({"case_id": case_id, "pack_id": pack_id,
                           "status": "needs_attention", "error": str(e)})
        self.bus.publish(case_id, {"kind": "state", "case": self.store.get(case_id)})
        return self.store.get(case_id)

    def start_case(self, pack_id):
        case_id = str(uuid.uuid4())
        self.store.upsert({"case_id": case_id, "pack_id": pack_id,
                           "status": "awaiting_interview", "live_fields": {}})
        try:
            self.graphs[pack_id].invoke(
                {"case_id": case_id, "pack_id": pack_id, "reask_count": 0}, self._cfg(case_id))
        except Exception as e:
            return self._mark_needs_attention(case_id, pack_id, e)
        return self._sync(case_id, pack_id)

    def _pack_of(self, case_id):
        case = self.store.get(case_id)
        if case is None:
            raise KeyError(case_id)
        return case["pack_id"]

    def resume(self, case_id, payload):
        pack_id = self._pack_of(case_id)
        try:
            self.graphs[pack_id].invoke(Command(resume=payload), self._cfg(case_id))
        except Exception as e:
            return self._mark_needs_attention(case_id, pack_id, e)
        return self._sync(case_id, pack_id)

    def recover_case(self, case_id, pack_id):
        """Rehydrate the store entry for a case that exists only in the checkpointer.

        NOTE (list_known_threads): a full store rebuild on boot — enumerating every
        thread_id known to the checkpointer and re-syncing each one — is a Plan 3
        concern (the dashboard needs it, once one exists). For now `recover_case`
        is the explicit per-case recovery path: the caller already knows the
        case_id and pack_id (e.g. from a URL or an external record), and this
        integration test is its consumer.
        """
        self.store.upsert({"case_id": case_id, "pack_id": pack_id, "live_fields": {}})
        return self._sync(case_id, pack_id)

    def patch_fields(self, case_id, fields, confidence):
        pack_id = self._pack_of(case_id)
        case = self.store.get(case_id)
        live = {**case.get("live_fields", {}), **fields}
        self.store.upsert({"case_id": case_id, "pack_id": pack_id, "live_fields": live})
        self.bus.publish(case_id, {"kind": "fields", "fields": live, "confidence": confidence})
        return self.store.get(case_id)
