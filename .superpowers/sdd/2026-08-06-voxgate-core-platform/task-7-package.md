# Task 7 review package - full contents of created/changed files

=== FILE: src/voxgate/service/store.py ===
import threading

class CaseStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._cases: dict[str, dict] = {}
        self._seq = 0

    def upsert(self, case: dict):
        with self._lock:
            existing = self._cases.get(case["case_id"])
            if existing:
                case = {**existing, **case}
            else:
                self._seq += 1
                case = {**case, "seq": self._seq}
            self._cases[case["case_id"]] = case

    def get(self, case_id):
        with self._lock:
            return self._cases.get(case_id)

    def list(self, pack_id=None):
        with self._lock:
            cases = [c for c in self._cases.values()
                     if pack_id is None or c["pack_id"] == pack_id]
        return sorted(cases, key=lambda c: c["seq"], reverse=True)


=== FILE: src/voxgate/service/events.py ===
import threading

class EventBus:
    def __init__(self):
        self._cond = threading.Condition()
        self._events: dict[str, list[dict]] = {}

    def publish(self, case_id, event):
        with self._cond:
            self._events.setdefault(case_id, []).append(event)
            self._cond.notify_all()

    def history(self, case_id):
        with self._cond:
            return list(self._events.get(case_id, []))

    def wait(self, case_id, after_index, timeout):
        with self._cond:
            self._cond.wait_for(
                lambda: len(self._events.get(case_id, [])) > after_index, timeout=timeout)
            return list(self._events.get(case_id, [])[after_index:])


=== FILE: src/voxgate/service/runner.py ===
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

    def patch_fields(self, case_id, fields, confidence):
        pack_id = self._pack_of(case_id)
        case = self.store.get(case_id)
        live = {**case.get("live_fields", {}), **fields}
        self.store.upsert({"case_id": case_id, "pack_id": pack_id, "live_fields": live})
        self.bus.publish(case_id, {"kind": "fields", "fields": live, "confidence": confidence})
        return self.store.get(case_id)


=== FILE: src/voxgate/service/__init__.py ===


=== FILE: tests/test_runner.py ===
import dataclasses
import pytest
from langgraph.checkpoint.memory import MemorySaver
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.graph.build import build_graph
from voxgate.service.store import CaseStore
from voxgate.service.events import EventBus
from voxgate.service.runner import CaseRunner
from tests.test_pack_kyc_uae import CLEAN, RISKY


def _boom(fields):
    raise RuntimeError("provider down")


def _crashing_graph_for(pack, checkpointer):
    # NOTE: must reuse the runner's existing checkpointer (a MemorySaver
    # instance), not a fresh MemorySaver() — a brand-new checkpointer has no
    # history for the case's thread_id, so Command(resume=...) silently
    # replays from START instead of resuming into the crashing check node.
    crashing_pack = dataclasses.replace(pack, checks=[_boom])
    return build_graph(crashing_pack, checkpointer)

@pytest.fixture()
def runner():
    packs = load_packs(get_settings().packs_dir)
    return CaseRunner(packs, MemorySaver, CaseStore(), EventBus())

def test_full_lifecycle_clean(runner):
    case = runner.start_case("kyc-uae")
    assert case["status"] == "awaiting_interview"
    assert case["interrupt"]["type"] == "interview"
    done = runner.resume(case["case_id"], {"fields": CLEAN, "confidence": {}})
    assert done["status"] == "approved" and done["interrupt"] is None
    assert done["score"]["band"] == "low"

def test_gate_lifecycle_and_events(runner):
    case = runner.start_case("kyc-uae")
    runner.resume(case["case_id"], {"fields": RISKY, "confidence": {}})
    parked = runner.store.get(case["case_id"])
    assert parked["status"] == "awaiting_review"
    assert parked["interrupt"]["type"] == "review"
    runner.resume(case["case_id"], {"action": "approve", "note": "cleared by officer"})
    assert runner.store.get(case["case_id"])["status"] == "approved"
    kinds = [e["kind"] for e in runner.bus.history(case["case_id"])]
    assert kinds.count("state") >= 3

def test_patch_fields_is_live_only(runner):
    case = runner.start_case("kyc-uae")
    runner.patch_fields(case["case_id"], {"full_name": "Pri"}, {"full_name": 0.4})
    c = runner.store.get(case["case_id"])
    assert c["live_fields"] == {"full_name": "Pri"}
    assert c["status"] == "awaiting_interview"          # graph untouched
    assert runner.bus.history(case["case_id"])[-1]["kind"] == "fields"

def test_list_and_unknown_case(runner):
    a = runner.start_case("kyc-uae"); b = runner.start_case("kyc-uae")
    ids = [c["case_id"] for c in runner.store.list()]
    assert ids[0] == b["case_id"]                        # newest first
    with pytest.raises(KeyError):
        runner.resume("nope", {})

def test_eventbus_wait_returns_new_events(runner):
    case = runner.start_case("kyc-uae")
    n = len(runner.bus.history(case["case_id"]))
    import threading
    got = []
    t = threading.Thread(target=lambda: got.extend(
        runner.bus.wait(case["case_id"], after_index=n, timeout=5.0)))
    t.start()
    runner.patch_fields(case["case_id"], {"dob": "1992-04-15"}, {})
    t.join(timeout=6)
    assert got and got[-1]["kind"] == "fields"

def test_node_crash_marks_needs_attention(runner, monkeypatch):
    case = runner.start_case("kyc-uae")
    pack = runner.packs["kyc-uae"]
    monkeypatch.setitem(
        runner.graphs, "kyc-uae",
        _crashing_graph_for(pack, runner.graphs["kyc-uae"].checkpointer))
    out = runner.resume(case["case_id"], {"fields": CLEAN, "confidence": {}})
    assert out["status"] == "needs_attention"
    assert "error" in out

