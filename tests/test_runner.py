import dataclasses
import pytest
from langgraph.checkpoint.memory import MemorySaver
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.graph.build import build_graph
from voxgate.service.store import InMemoryCaseStore
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
    return CaseRunner(packs, MemorySaver, InMemoryCaseStore(), EventBus())

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
    parked = runner.store.get(runner.tenant, case["case_id"])
    assert parked["status"] == "awaiting_review"
    assert parked["interrupt"]["type"] == "review"
    runner.resume(case["case_id"], {"action": "approve", "note": "cleared by officer"})
    assert runner.store.get(runner.tenant, case["case_id"])["status"] == "approved"
    kinds = [e["kind"] for e in runner.bus.history(case["case_id"])]
    assert kinds.count("state") >= 3

def test_patch_fields_is_live_only(runner):
    case = runner.start_case("kyc-uae")
    runner.patch_fields(case["case_id"], {"full_name": "Pri"}, {"full_name": 0.4})
    c = runner.store.get(runner.tenant, case["case_id"])
    assert c["live_fields"] == {"full_name": "Pri"}
    assert c["status"] == "awaiting_interview"          # graph untouched
    assert runner.bus.history(case["case_id"])[-1]["kind"] == "fields"

def test_list_and_unknown_case(runner):
    a = runner.start_case("kyc-uae"); b = runner.start_case("kyc-uae")
    ids = [c["case_id"] for c in runner.store.list(runner.tenant)]
    assert ids[0] == b["case_id"]                        # newest first
    with pytest.raises(KeyError):
        runner.resume("nope", {})

def test_eventbus_wait_returns_new_events(runner):
    case = runner.start_case("kyc-uae")
    n = runner.bus.latest_seq(case["case_id"])
    import threading
    got = []
    t = threading.Thread(target=lambda: got.extend(
        runner.bus.wait(case["case_id"], after_seq=n, timeout=5.0)))
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
