import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.service.app import create_app
from voxgate.service.runner import CaseRunner
from voxgate.service.store import InMemoryCaseStore
from voxgate.service.events import EventBus
from tests.test_pack_kyc_uae import CLEAN, RISKY

@pytest.fixture()
def client():
    runner = CaseRunner(load_packs(get_settings().packs_dir),
                        MemorySaver, InMemoryCaseStore(), EventBus())
    return TestClient(create_app(runner=runner))

def test_packs_listing(client):
    packs = client.get("/packs").json()
    by_id = {p["pack_id"]: p for p in packs}
    # Look the pack up by id rather than by position. Packs load in directory
    # order, so asserting on packs[0] breaks the moment a pack is added whose
    # directory sorts earlier.
    assert "kyc-uae" in by_id
    kyc = by_id["kyc-uae"]
    assert "full_name" in kyc["fields"]
    # reask_hints are what the applicant-facing interview reads its questions
    # from, so every field must have one.
    assert set(kyc["reask_hints"]) == set(kyc["fields"])

def test_case_lifecycle_over_http(client):
    case = client.post("/cases", json={"pack_id": "kyc-uae"}).json()
    cid = case["case_id"]
    assert case["status"] == "awaiting_interview"
    client.patch(f"/cases/{cid}/fields", json={"fields": {"full_name": "Pri"}, "confidence": {}})
    done = client.post(f"/cases/{cid}/interview-result",
                       json={"fields": CLEAN, "confidence": {}}).json()
    assert done["status"] == "approved"
    assert client.get(f"/cases/{cid}").json()["score"]["band"] == "low"

def test_decision_flow_and_conflicts(client):
    cid = client.post("/cases", json={"pack_id": "kyc-uae"}).json()["case_id"]
    # decision before review is a 409
    assert client.post(f"/cases/{cid}/decision",
                       json={"action": "approve", "note": ""}).status_code == 409
    client.post(f"/cases/{cid}/interview-result", json={"fields": RISKY, "confidence": {}})
    assert client.get(f"/cases/{cid}").json()["status"] == "awaiting_review"
    # second interview-result while awaiting review is a 409
    assert client.post(f"/cases/{cid}/interview-result",
                       json={"fields": RISKY, "confidence": {}}).status_code == 409
    r = client.post(f"/cases/{cid}/decision", json={"action": "reject", "note": "hit"})
    assert r.json()["status"] == "rejected"

def test_unknown_pack_and_case_404(client):
    assert client.post("/cases", json={"pack_id": "nope"}).status_code == 404
    assert client.get("/cases/nope").status_code == 404

def test_ws_streams_history_then_live(client):
    cid = client.post("/cases", json={"pack_id": "kyc-uae"}).json()["case_id"]
    with client.websocket_connect(f"/cases/{cid}/events") as ws:
        first = ws.receive_json()
        assert first["kind"] == "state"
        client.patch(f"/cases/{cid}/fields", json={"fields": {"dob": "1992-04-15"}, "confidence": {}})
        live = ws.receive_json()
        while live["kind"] != "fields":
            live = ws.receive_json()
        assert live["fields"]["dob"] == "1992-04-15"

def test_lazy_module_app_is_memoized_singleton(monkeypatch):
    # Regression test: module-level `app` (used by `uvicorn voxgate.service.app:app`)
    # is built lazily via PEP 562 __getattr__ so importing the module for tests
    # has no side effects. It must still behave like the singleton a bare
    # `app = create_app()` implies: repeated access returns the SAME instance,
    # and create_app() must only run once. Stub create_app so this test never
    # triggers real pack loading/graph building.
    import voxgate.service.app as app_module

    calls = []
    sentinel = object()

    def fake_create_app(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(app_module, "create_app", fake_create_app)
    monkeypatch.setattr(app_module, "_app_instance", None)

    a1 = app_module.app
    a2 = app_module.app

    assert a1 is a2 is sentinel
    assert len(calls) == 1
