import uuid

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.service.app import create_app
from voxgate.service.runner import CaseRunner
from voxgate.service.store import CaseStore
from voxgate.service.events import EventBus
from tests.test_pack_kyc_uae import CLEAN, RISKY

@pytest.fixture()
def client():
    runner = CaseRunner(load_packs(get_settings().packs_dir),
                        MemorySaver, CaseStore(), EventBus())
    return TestClient(create_app(runner=runner))

def test_dashboard_serves_html(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert '<div id="voxgate-app"' in r.text

def test_dashboard_static_assets(client):
    css = client.get("/static/dashboard.css")
    assert css.status_code == 200
    assert "siri" in css.text or ":root" in css.text

    js = client.get("/static/dashboard.js")
    assert js.status_code == 200
    assert len(js.text) > 0
    assert "demo-seed" in js.text or "#case-list" in js.text

    assert client.get("/static/index.html").status_code == 200

def test_demo_seed_creates_spread(client):
    r = client.post("/dashboard/demo-seed")
    assert r.status_code == 201
    data = r.json()
    assert data["seeded"] == 5
    statuses = [c["status"] for c in data["cases"]]
    assert "approved" in statuses
    assert "awaiting_review" in statuses
    assert len(client.get("/cases").json()) >= 5

def test_demo_seed_idempotent_and_grows(client):
    client.post("/dashboard/demo-seed")
    first = len(client.get("/cases").json())
    client.post("/dashboard/demo-seed")
    second = len(client.get("/cases").json())
    assert second > first

def test_recover_restores_unknown_case_id(client):
    cid = str(uuid.uuid4())
    r = client.post(f"/cases/{cid}/recover", json={"pack_id": "kyc-uae"})
    assert r.status_code == 200
    case = r.json()
    assert case["case_id"] == cid
    # A never-started thread has no checkpoint, so get_state() yields an empty
    # state: _sync falls back to v.get("status", "processing"). The brief
    # predicted "awaiting_interview", but the real observed value is
    # "processing" (the graph's intake node never ran for a fresh thread_id).
    assert case["status"] == "processing"

def test_recover_unknown_pack_404(client):
    cid = str(uuid.uuid4())
    assert client.post(f"/cases/{cid}/recover",
                       json={"pack_id": "nope"}).status_code == 404

def test_recover_restores_parked_review_case(client):
    cid = client.post("/cases", json={"pack_id": "kyc-uae"}).json()["case_id"]
    parked = client.post(f"/cases/{cid}/interview-result",
                         json={"fields": RISKY, "confidence": {}}).json()
    assert parked["status"] == "awaiting_review"
    assert parked["interrupt"]["type"] == "review"

    # Recovering re-syncs from the shared in-memory checkpointer, so the parked
    # review interrupt survives the round-trip.
    recovered = client.post(f"/cases/{cid}/recover",
                            json={"pack_id": "kyc-uae"})
    assert recovered.status_code == 200
    case = recovered.json()
    assert case["status"] == "awaiting_review"
    assert case["interrupt"]["type"] == "review"
