import uuid
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from voxgate.config import get_settings
from voxgate.packs.loader import load_pack
from voxgate.graph.build import build_graph, MAX_REASKS, _latest_checks
from tests.test_pack_kyc_uae import CLEAN, RISKY

@pytest.fixture()
def pack():
    return load_pack(get_settings().packs_dir / "kyc_uae")

def start(graph, pack):
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke({"case_id": cfg["configurable"]["thread_id"],
                  "pack_id": pack.pack_id, "reask_count": 0}, cfg)
    return cfg

def interrupt_payload(graph, cfg):
    return graph.get_state(cfg).tasks[0].interrupts[0].value

def test_check_node_names_match_pack_check_names(pack):
    graph = build_graph(pack, MemorySaver())
    node_names = set(graph.get_graph().nodes.keys())
    assert {"check_sanctions", "check_pep", "check_adverse_media"} <= node_names

def test_pauses_at_interview_then_clean_case_auto_approves(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    assert interrupt_payload(graph, cfg)["type"] == "interview"
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    s = graph.get_state(cfg).values
    assert s["status"] == "approved"
    assert s["decision"]["by"] == "system"
    assert s["score"]["band"] == "low"

def test_risky_case_parks_at_reviewer_gate_and_approve_resumes(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    payload = interrupt_payload(graph, cfg)
    assert payload["type"] == "review" and payload["gate_role"] == "Compliance Officer"
    assert graph.get_state(cfg).values["status"] == "awaiting_review"
    graph.invoke(Command(resume={"action": "reject", "note": "sanctions hit"}), cfg)
    s = graph.get_state(cfg).values
    assert s["status"] == "rejected" and s["decision"]["note"] == "sanctions hit"

def test_invalid_fields_trigger_reask_with_hints(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": {**CLEAN, "dob": "2020-01-01"}, "confidence": {}}), cfg)
    payload = interrupt_payload(graph, cfg)
    assert payload["type"] == "interview"
    assert "dob" in payload["reask_fields"]
    assert payload["reask_hints"]["dob"]
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    assert graph.get_state(cfg).values["status"] == "approved"

def test_reask_cap_forces_reviewer_gate(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    bad = {"fields": {**CLEAN, "dob": "2020-01-01"}, "confidence": {}}
    graph.invoke(Command(resume=bad), cfg)
    for _ in range(MAX_REASKS):
        assert interrupt_payload(graph, cfg)["type"] == "interview"
        graph.invoke(Command(resume=bad), cfg)
    assert interrupt_payload(graph, cfg)["type"] == "review"   # cap exhausted → gate

def test_request_info_from_gate_loops_back_to_interview(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    graph.invoke(Command(resume={"action": "request_info", "note": "verify SoF"}), cfg)
    assert interrupt_payload(graph, cfg)["type"] == "interview"

def test_resume_after_restart_same_checkpointer(pack):
    saver = MemorySaver()
    graph = build_graph(pack, saver)
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    graph2 = build_graph(pack, saver)          # "restarted process"
    assert graph2.get_state(cfg).values["status"] == "awaiting_review"
    graph2.invoke(Command(resume={"action": "approve", "note": "ok"}), cfg)
    assert graph2.get_state(cfg).values["status"] == "approved"

def test_latest_check_results_win_after_reask(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    # RISKY runs checks once and parks at the reviewer gate.
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    # request_info loops back to interview without touching check_results.
    graph.invoke(Command(resume={"action": "request_info", "note": "verify SoF"}), cfg)
    # Supplying CLEAN fields re-runs checks, appending a second result per check_name.
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    s = graph.get_state(cfg).values
    per_check = [c["check_name"] for c in s["check_results"]]
    assert len(per_check) > len(set(per_check))     # duplicates genuinely accumulated
    assert s["score"]["band"] == "low"          # scored on deduped latest (CLEAN) results
    deduped = _latest_checks(s["check_results"])
    assert sorted(c["check_name"] for c in deduped) == sorted(set(per_check))
