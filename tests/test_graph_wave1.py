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
