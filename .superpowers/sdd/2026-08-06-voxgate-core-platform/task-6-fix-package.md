# Task 6 FIX review package - current files after fix round 1

=== FILE: src/voxgate/graph/build.py ===
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
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

def build_graph(pack: Pack, checkpointer):
    g = StateGraph(CaseState)

    def intake(state):
        return {"status": "awaiting_interview", "fields": {}, "reask_count": state.get("reask_count", 0)}

    def interview(state):
        payload = interrupt({
            "type": "interview",
            "reask_fields": state.get("reask_fields", []),
            "reask_hints": {f: pack.reask_hints[f] for f in state.get("reask_fields", []) if f in pack.reask_hints},
            "fields_so_far": state.get("fields", {}),
        })
        return {"fields": {**state.get("fields", {}), **payload["fields"]},
                "field_confidence": payload.get("confidence", {}),
                "status": "processing", "reask_fields": []}

    def extract_validate(state):
        try:
            clean = pack.schema_model(**state["fields"]).model_dump()
            return {"fields": clean}
        except ValidationError as e:
            bad = sorted({err["loc"][0] for err in e.errors() if err["loc"]})
            return {"reask_fields": list(bad), "reask_count": state["reask_count"] + 1}

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
        decision = interrupt({
            "type": "review", "gate_role": pack.gate_role, "score": state["score"],
            "check_results": state_checks, "fields": state["fields"]})
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

    g.add_node("intake", intake)
    g.add_node("interview", interview)
    g.add_node("extract_validate", extract_validate)
    for c in pack.checks:
        g.add_node(_node_name(c), make_check_node(c))
    g.add_node("force_gate", force_gate)
    g.add_node("score", score)
    g.add_node("medium_reask", medium_reask)
    g.add_node("auto_approve", auto_approve)
    g.add_node("awaiting_review", set_awaiting_review)
    g.add_node("reviewer_gate", reviewer_gate)
    g.add_node("finalize", finalize)

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


=== FILE: tests/test_graph.py ===
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


=== FILE: packs/kyc_uae/checks.py ===
import json
from pathlib import Path
from rapidfuzz import fuzz
from voxgate.ml.name_match import NameMatcher
from voxgate.packs.base import CheckResult

DATA = Path(__file__).parent / "data"
_sanctions = json.loads((DATA / "sanctions.json").read_text(encoding="utf-8"))["entries"]
_peps = json.loads((DATA / "peps.json").read_text(encoding="utf-8"))["entries"]
_media = json.loads((DATA / "adverse_media.json").read_text(encoding="utf-8"))["entries"]
COUNTRIES = json.loads((DATA / "countries.json").read_text(encoding="utf-8"))["countries"]

_STATUS = {"strong": "hit", "review": "review", "clear": "clear"}

def _screen(name, entries, check_name, fields):
    matcher = NameMatcher(entries)   # embedder wired in Plan 2+ via config; None is valid
    cands = matcher.match(name, dob=fields.get("dob"), nationality=fields.get("nationality"))
    top = cands[0] if cands else None
    return CheckResult(
        check_name=check_name,
        status=_STATUS[top.band] if top else "clear",
        score=top.combined if top else 0.0,
        details={"candidates": [c.model_dump() for c in cands]})

def sanctions_screen(fields: dict) -> CheckResult:
    return _screen(fields["full_name"], _sanctions, "sanctions", fields)
sanctions_screen.check_name = "sanctions"

def pep_screen(fields: dict) -> CheckResult:
    return _screen(fields["full_name"], _peps, "pep", fields)
pep_screen.check_name = "pep"

def adverse_media(fields: dict) -> CheckResult:
    hits = [m for m in _media
            if fuzz.token_set_ratio(fields["full_name"].lower(), m["name"].lower()) > 85]
    worst = max((m["severity"] for m in hits), default=0.0)
    return CheckResult(check_name="adverse_media",
                       status="review" if worst >= 0.5 else "clear",
                       score=worst, details={"articles": hits})
adverse_media.check_name = "adverse_media"

CHECKS = [sanctions_screen, pep_screen, adverse_media]

