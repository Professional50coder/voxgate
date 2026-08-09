# Graph Wave 1 review package - full contents of created/changed files (runner.py change is the single audit line in _sync)

=== FILE: src/voxgate/graph/state.py ===
import operator
from typing import Annotated, TypedDict

class CaseState(TypedDict, total=False):
    case_id: str
    pack_id: str
    status: str
    fields: dict
    field_confidence: dict
    reask_count: int
    reask_fields: list[str]
    force_review: bool
    check_results: Annotated[list[dict], operator.add]
    score: dict | None
    decision: dict | None
    # Wave 1 additions (additive-only; see docs/design/2026-08-06-graph-upgrade-design.md)
    audit: Annotated[list[dict], operator.add]
    field_errors: dict[str, str]


=== FILE: src/voxgate/graph/build.py ===
import time
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, RetryPolicy
from pydantic import ValidationError
from voxgate.packs.base import Pack
from .state import CaseState

MAX_REASKS = 2

def _node_name(check) -> str:
    return f"check_{getattr(check, 'check_name', check.__name__)}"

def _latest_checks(results: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for r in results:                      # append-order: later wins
        latest[r["check_name"]] = r
    return list(latest.values())

def _summarize(name, state, result):
    # Deterministic, state-derived summary — no wall-clock, no randomness.
    bits = [name]
    if result.get("reask_fields"):
        bits.append(f"reask={result['reask_fields']}")
    if result.get("decision") is not None:
        bits.append(f"decision={result['decision'].get('action')}")
    status_after = result.get("status", state.get("status"))
    if status_after != state.get("status"):
        bits.append(f"status={state.get('status')}->{status_after}")
    return " ".join(bits)

def _audited(name, fn, clock=None):
    """Wrap a node function so every invocation appends one audit entry.

    seq is a pure function of the audit list already present in the state the
    node was invoked with (design doc §a) — deterministic, no wall clock.
    duration_ms uses a monotonic clock only for the *difference* of two calls,
    never as an identity/ordering key, so it introduces no non-determinism
    that any test could reasonably assert an exact value of.
    """
    def wrapper(state):
        t0 = time.perf_counter()
        result = fn(state) or {}
        entry = {
            "seq": len(state.get("audit", [])) + 1,
            "node": name,
            "status_before": state.get("status"),
            "status_after": result.get("status", state.get("status")),
            "summary": _summarize(name, state, result),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
        if clock is not None:
            entry["ts"] = clock()
        return {**result, "audit": [entry]}
    return wrapper

def build_graph(pack: Pack, checkpointer, clock=None):
    g = StateGraph(CaseState)

    def intake(state):
        return {"status": "awaiting_interview", "fields": {}, "reask_count": state.get("reask_count", 0)}

    def interview(state):
        reask_fields = state.get("reask_fields", [])
        schema_fields = list(pack.schema_model.model_fields)
        payload = interrupt({
            "type": "interview",
            "reask_fields": reask_fields,
            "reask_hints": {f: pack.reask_hints[f] for f in reask_fields if f in pack.reask_hints},
            "fields_so_far": state.get("fields", {}),
            # additive (proposal c): explain *why* + progress/attempt visibility
            "field_errors": {f: state.get("field_errors", {}).get(f) for f in reask_fields},
            "attempt": state.get("reask_count", 0),
            "max_attempts": MAX_REASKS,
            "fields_validated": [f for f in schema_fields
                                  if f not in reask_fields and f in state.get("fields", {})],
        })
        return {"fields": {**state.get("fields", {}), **payload["fields"]},
                "field_confidence": payload.get("confidence", {}),
                "status": "processing", "reask_fields": []}

    def extract_validate(state):
        try:
            clean = pack.schema_model(**state["fields"]).model_dump()
            return {"fields": clean}
        except ValidationError as e:
            errs = {err["loc"][0]: err["msg"] for err in e.errors() if err["loc"]}
            return {"reask_fields": sorted(errs), "reask_count": state["reask_count"] + 1,
                    "field_errors": errs}

    def after_validate(state):
        if state.get("reask_fields"):
            if state["reask_count"] > MAX_REASKS:
                return "force_gate"
            return "interview"
        return [_node_name(c) for c in pack.checks]   # parallel fan-out

    def force_gate(state):
        return {"force_review": True, "score": {"probability": None, "band": "high",
                "contributions": [], "bias": None}, "check_results": []}

    def make_check_node(check):
        def node(state):
            return {"check_results": [check(state["fields"]).model_dump()]}
        return node

    def score(state):
        checks = _latest_checks(state.get("check_results", []))
        result = pack.scorecard.score({"fields": state["fields"], "checks": checks})
        return {"score": result.model_dump(), "check_results": []}  # add-reducer: no-op append

    def route(state):
        checks = _latest_checks(state.get("check_results", []))
        band = state["score"]["band"]
        any_hit = any(c["status"] == "hit" for c in checks)
        if state.get("force_review") or any_hit or band == "high":
            return "awaiting_review"
        if band == "medium":
            if state["reask_count"] >= MAX_REASKS:
                return "awaiting_review"
            return "medium_reask"
        return "auto_approve"

    def medium_reask(state):
        top = max((c for c in state["score"]["contributions"]), key=lambda c: c["contribution"])
        field = pack.feature_field_hints.get(top["feature"], "full_name")
        return {"reask_fields": [field], "reask_count": state["reask_count"] + 1}

    def auto_approve(state):
        return {"decision": {"action": "approve", "by": "system", "note": "low risk"},
                "status": "approved"}

    def reviewer_gate(state):
        state_checks = _latest_checks(state.get("check_results", []))
        contributions = state["score"].get("contributions", [])
        waterfall = sorted(contributions, key=lambda c: abs(c["contribution"]), reverse=True)
        flagged = [c for c in state_checks if c["status"] != "clear"]
        decision = interrupt({
            "type": "review", "gate_role": pack.gate_role, "score": state["score"],
            "check_results": state_checks, "fields": state["fields"],
            # additive (proposal c): pre-assembled waterfall/flags + why-here signals
            "score_waterfall": waterfall,
            "flagged_checks": flagged,
            "reask_count": state.get("reask_count", 0),
            "force_review": state.get("force_review", False),
        })
        if decision["action"] == "request_info":
            return {"reask_fields": ["source_of_funds"], "reask_count": 0,
                    "force_review": False, "decision": None, "status": "processing"}
        return {"decision": {**decision, "by": pack.gate_role},
                "status": "approved" if decision["action"] == "approve" else "rejected"}

    def after_gate(state):
        return "interview" if state.get("reask_fields") else "finalize"

    def set_awaiting_review(state):
        return {"status": "awaiting_review"}

    def finalize(state):
        return {}

    g.add_node("intake", _audited("intake", intake, clock))
    g.add_node("interview", _audited("interview", interview, clock))
    g.add_node("extract_validate", _audited("extract_validate", extract_validate, clock))
    for c in pack.checks:
        name = _node_name(c)
        g.add_node(name, _audited(name, make_check_node(c), clock),
                   retry_policy=RetryPolicy(max_attempts=2))
    g.add_node("force_gate", _audited("force_gate", force_gate, clock))
    g.add_node("score", _audited("score", score, clock))
    g.add_node("medium_reask", _audited("medium_reask", medium_reask, clock))
    g.add_node("auto_approve", _audited("auto_approve", auto_approve, clock))
    g.add_node("awaiting_review", _audited("awaiting_review", set_awaiting_review, clock))
    g.add_node("reviewer_gate", _audited("reviewer_gate", reviewer_gate, clock))
    g.add_node("finalize", _audited("finalize", finalize, clock))

    g.add_edge(START, "intake")
    g.add_edge("intake", "interview")
    g.add_edge("interview", "extract_validate")
    g.add_conditional_edges("extract_validate", after_validate,
        ["interview", "force_gate"] + [_node_name(c) for c in pack.checks])
    for c in pack.checks:
        g.add_edge(_node_name(c), "score")
    g.add_edge("force_gate", "awaiting_review")
    g.add_conditional_edges("score", route, ["awaiting_review", "medium_reask", "auto_approve"])
    g.add_edge("medium_reask", "interview")
    g.add_edge("awaiting_review", "reviewer_gate")
    g.add_conditional_edges("reviewer_gate", after_gate, ["interview", "finalize"])
    g.add_edge("auto_approve", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


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


=== FILE: tests/test_graph_wave1.py ===
"""Graph Wave 1 tests: audit trail (a), per-node timing (b), richer interrupt
payloads (c), per-check retry policy (e).

Mirrors tests/test_graph.py's own local-helper style (no shared fixtures
across files) and drives the graph directly via build_graph/invoke/get_state,
exactly like test_graph.py — most of (c)'s new interrupt-payload keys and
(a)'s new audit key are visible on graph state/interrupt payloads without any
service-layer change. One integration test at the bottom (added once
runner.py's owner wired `"audit": v.get("audit", [])` into CaseRunner._sync)
additionally drives a case through CaseRunner, mirroring test_runner.py's
fixture pattern, to prove the audit trail reaches the store too.
"""
import dataclasses
import uuid
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from voxgate.config import get_settings
from voxgate.packs.loader import load_pack, load_packs
from voxgate.packs.base import CheckResult
from voxgate.graph.build import build_graph, MAX_REASKS
from voxgate.service.store import CaseStore
from voxgate.service.events import EventBus
from voxgate.service.runner import CaseRunner
from tests.test_pack_kyc_uae import CLEAN, RISKY


@pytest.fixture()
def pack():
    return load_pack(get_settings().packs_dir / "kyc_uae")


@pytest.fixture()
def runner():
    packs = load_packs(get_settings().packs_dir)
    return CaseRunner(packs, MemorySaver, CaseStore(), EventBus())


def start(graph, pack):
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke({"case_id": cfg["configurable"]["thread_id"],
                  "pack_id": pack.pack_id, "reask_count": 0}, cfg)
    return cfg


def interrupt_payload(graph, cfg):
    return graph.get_state(cfg).tasks[0].interrupts[0].value


# ---------------------------------------------------------------------------
# (a) Audit trail
# ---------------------------------------------------------------------------

def test_audit_trail_records_intake_through_approve(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    s = graph.get_state(cfg).values
    audit = s["audit"]
    assert audit
    assert audit[0]["node"] == "intake"
    visited = {e["node"] for e in audit}
    expected = {"intake", "interview", "extract_validate", "check_sanctions",
                "check_pep", "check_adverse_media", "score", "auto_approve", "finalize"}
    assert expected <= visited
    for e in audit:
        assert set(e) >= {"seq", "node", "status_before", "status_after", "summary", "duration_ms"}
        assert isinstance(e["seq"], int) and e["seq"] >= 1


def test_audit_parallel_checks_share_seq(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    audit = graph.get_state(cfg).values["audit"]
    check_entries = [e for e in audit if e["node"].startswith("check_")]
    assert len(check_entries) == 3
    seqs = {e["seq"] for e in check_entries}
    assert len(seqs) == 1                       # all three share one seq
    names = {e["node"] for e in check_entries}
    assert names == {"check_sanctions", "check_pep", "check_adverse_media"}


def test_audit_survives_resume_after_restart(pack):
    saver = MemorySaver()
    graph = build_graph(pack, saver)
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    audit_before = graph.get_state(cfg).values["audit"]
    assert audit_before

    graph2 = build_graph(pack, saver)            # "restarted process"
    audit_rehydrated = graph2.get_state(cfg).values["audit"]
    assert audit_rehydrated == audit_before       # nothing lost, nothing reset

    graph2.invoke(Command(resume={"action": "approve", "note": "ok"}), cfg)
    audit_after = graph2.get_state(cfg).values["audit"]
    assert len(audit_after) > len(audit_before)


def test_audit_append_only_across_reask_loop(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    bad = {"fields": {**CLEAN, "dob": "2020-01-01"}, "confidence": {}}
    graph.invoke(Command(resume=bad), cfg)
    lengths = [len(graph.get_state(cfg).values["audit"])]
    for _ in range(MAX_REASKS):
        assert interrupt_payload(graph, cfg)["type"] == "interview"
        graph.invoke(Command(resume=bad), cfg)
        lengths.append(len(graph.get_state(cfg).values["audit"]))
    assert lengths == sorted(lengths)
    assert len(set(lengths)) == len(lengths)      # strictly increasing, never shrinks


# ---------------------------------------------------------------------------
# (b) Per-node timing
# ---------------------------------------------------------------------------

def test_audit_entries_have_nonnegative_duration(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    audit = graph.get_state(cfg).values["audit"]
    assert audit
    for e in audit:
        assert isinstance(e["duration_ms"], float)
        assert e["duration_ms"] >= 0.0


def test_audit_ts_present_only_when_clock_supplied(pack):
    graph_no_clock = build_graph(pack, MemorySaver())
    cfg = start(graph_no_clock, pack)
    graph_no_clock.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    audit_no_clock = graph_no_clock.get_state(cfg).values["audit"]
    assert audit_no_clock
    assert all("ts" not in e for e in audit_no_clock)   # default: no clock, no ts

    tick = {"n": 0.0}
    def fake_clock():
        tick["n"] += 1.0
        return tick["n"]

    graph_clock = build_graph(pack, MemorySaver(), clock=fake_clock)
    cfg2 = start(graph_clock, pack)
    graph_clock.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg2)
    audit_clock = graph_clock.get_state(cfg2).values["audit"]
    assert audit_clock
    assert all("ts" in e and isinstance(e["ts"], float) for e in audit_clock)


# ---------------------------------------------------------------------------
# (c) Richer interview payload
# ---------------------------------------------------------------------------

def test_interview_payload_field_errors_and_attempt(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": {**CLEAN, "dob": "2020-01-01"}, "confidence": {}}), cfg)
    payload = interrupt_payload(graph, cfg)
    assert payload["type"] == "interview"
    assert "dob" in payload["reask_fields"]
    assert payload["field_errors"]["dob"]                 # non-empty Pydantic message
    assert isinstance(payload["field_errors"]["dob"], str)
    assert payload["attempt"] == 1
    assert payload["max_attempts"] == MAX_REASKS


def test_interview_payload_reports_progress(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": {**CLEAN, "dob": "2020-01-01"}, "confidence": {}}), cfg)
    payload = interrupt_payload(graph, cfg)
    assert "dob" not in payload["fields_validated"]
    for good in ("full_name", "nationality", "residency_status", "source_of_funds", "product"):
        assert good in payload["fields_validated"]


# ---------------------------------------------------------------------------
# (c) Richer review payload
# ---------------------------------------------------------------------------

def test_review_payload_waterfall_sorted_by_magnitude(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    payload = interrupt_payload(graph, cfg)
    assert payload["type"] == "review"
    waterfall = payload["score_waterfall"]
    assert waterfall
    mags = [abs(c["contribution"]) for c in waterfall]
    assert mags == sorted(mags, reverse=True)


def test_review_payload_flags_sanctions_hit(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    payload = interrupt_payload(graph, cfg)
    flagged_names = {c["check_name"] for c in payload["flagged_checks"]}
    assert "sanctions" in flagged_names
    sanc = next(c for c in payload["flagged_checks"] if c["check_name"] == "sanctions")
    assert sanc["status"] == "hit"
    assert all(c["status"] != "clear" for c in payload["flagged_checks"])


def test_review_payload_carries_reask_and_force_review(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    payload = interrupt_payload(graph, cfg)
    assert payload["reask_count"] == 0
    assert payload["force_review"] is False


# ---------------------------------------------------------------------------
# (e) Per-check retry policy
# ---------------------------------------------------------------------------

def _make_flaky_check():
    # LangGraph's RetryPolicy default retry_on excludes RuntimeError/ValueError/etc.
    # (treated as deterministic bugs, not transient) and only retries things like
    # ConnectionError/HTTP 5xx by default — see langgraph.types.default_retry_on.
    # Use ConnectionError here so this test actually exercises the retry path;
    # test_always_failing_check_still_reaches_terminal_failure below (and the
    # existing test_node_crash_marks_needs_attention in test_runner.py, which
    # this file must not touch) intentionally keep RuntimeError to prove a
    # non-transient failure still fails fast with no wasted retry.
    calls = {"n": 0}
    def flaky(fields):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("transient check failure")
        return CheckResult(check_name="flaky", status="clear", score=0.0, details={})
    return flaky


def test_transient_check_failure_recovers_via_retry(pack):
    flaky_pack = dataclasses.replace(pack, checks=[_make_flaky_check()])
    graph = build_graph(flaky_pack, MemorySaver())
    cfg = start(graph, flaky_pack)
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    s = graph.get_state(cfg).values
    assert s["status"] != "needs_attention"
    assert s["status"] in ("approved", "awaiting_review")


def test_always_failing_check_still_reaches_terminal_failure(pack):
    def _boom(fields):
        raise RuntimeError("provider down")
    boom_pack = dataclasses.replace(pack, checks=[_boom])
    graph = build_graph(boom_pack, MemorySaver())
    cfg = start(graph, boom_pack)
    with pytest.raises(RuntimeError):
        graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)


# ---------------------------------------------------------------------------
# (a) Audit trail reaches the store/API via CaseRunner._sync
# ---------------------------------------------------------------------------

def test_runner_store_carries_audit_trail_after_clean_lifecycle(runner):
    case = runner.start_case("kyc-uae")
    assert case["interrupt"]["type"] == "interview"
    done = runner.resume(case["case_id"], {"fields": CLEAN, "confidence": {}})
    assert done["status"] == "approved"

    audit = done["audit"]
    assert isinstance(audit, list) and audit
    node_names = {e["node"] for e in audit}
    assert {"intake", "interview", "extract_validate", "score", "auto_approve"} <= node_names
    for e in audit:
        assert set(e) >= {"seq", "node", "status_before", "status_after", "summary", "duration_ms"}
        assert isinstance(e["seq"], int) and e["seq"] >= 1
        assert isinstance(e["duration_ms"], float) and e["duration_ms"] >= 0.0

    # also present via runner.store directly, not just the returned dict
    stored = runner.store.get(case["case_id"])
    assert stored["audit"] == audit

