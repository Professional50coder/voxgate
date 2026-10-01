"""Transcripts, the agent store, analytics and named reviewers, over HTTP. Offline.

The Postgres implementations run the same behaviour in
tests/integration/test_records_pg.py.
"""
import shutil

import pytest
from fastapi.testclient import TestClient

from voxgate.config import Settings
from voxgate.packs.loader import load_packs
from voxgate.service.app import create_app
from voxgate.service.records import InMemoryPackStore
from voxgate.service.runner import CaseRunner
from voxgate.service.store import InMemoryCaseStore
from voxgate.service.events import InMemoryEventBus
from langgraph.checkpoint.memory import MemorySaver

from tests.test_publish import spec
from tests.test_pack_kyc_uae import RISKY

KEYS = "priya:key-priya,omar:key-omar"
PRIYA = {"X-API-Key": "key-priya"}


def _settings(tmp_path, **kw):
    packs = tmp_path / "packs"
    shutil.copytree(Settings().packs_dir, packs)
    return Settings(database_url=None, packs_dir=packs, groq_api_key=None, groq_api_keys=None,
                    cartesia_api_key=None, api_keys=KEYS, **kw)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(_settings(tmp_path)))


def _case(client, pack="kyc-uae"):
    return client.post("/cases", json={"pack_id": pack}).json()["case_id"]


# ------------------------------------------------------------------ transcripts

def test_a_web_interview_transcript_round_trips(client):
    cid = _case(client)
    r = client.post(f"/cases/{cid}/transcripts", json={"turns": [
        {"role": "agent", "text": "What is your full name?", "offset_ms": 0},
        {"role": "applicant", "text": "Fatima Al Mansoori", "offset_ms": 2100}]})
    sid = r.json()["session_id"]
    assert r.json()["turns"] == 2
    client.post(f"/cases/{cid}/transcripts", json={"session_id": sid, "turns": [
        {"role": "agent", "text": "Thank you. And your date of birth?", "offset_ms": 4000}]})
    summary = client.post(f"/cases/{cid}/transcripts/{sid}/finish", json={}).json()
    assert summary["turns"] == 3 and summary["source"] == "template"

    sessions = client.get(f"/cases/{cid}/transcripts", headers=PRIYA).json()["sessions"]
    assert [s["session_id"] for s in sessions] == [sid]
    full = client.get(f"/cases/{cid}/transcripts/{sid}", headers=PRIYA).json()
    assert [e["turn_no"] for e in full["entries"]] == [0, 1, 2]
    assert full["summary"]["outcome"] == "completed"


def test_transcript_reads_and_search_are_operator_only(client):
    cid = _case(client)
    assert client.get(f"/cases/{cid}/transcripts").status_code == 401
    assert client.get("/transcripts/search", params={"q": "passport"}).status_code == 401


def test_transcripts_are_searchable(client):
    cid = _case(client)
    client.post(f"/cases/{cid}/transcripts", json={"turns": [
        {"role": "applicant", "text": "My brother handles the source of funds"}]})
    hits = client.get("/transcripts/search", params={"q": "source funds"}, headers=PRIYA).json()["hits"]
    assert hits and hits[0]["case_id"] == cid


def test_transcript_writes_are_validated(client):
    cid = _case(client)
    assert client.post("/cases/nope/transcripts", json={
        "turns": [{"role": "agent", "text": "hi"}]}).status_code == 404
    assert client.post(f"/cases/{cid}/transcripts", json={
        "session_id": "../etc", "turns": [{"role": "agent", "text": "hi"}]}).status_code == 422
    assert client.post(f"/cases/{cid}/transcripts", json={
        "turns": [{"role": "system", "text": "hi"}]}).status_code == 422


# ------------------------------------------------------------------ agent store

def test_published_agents_show_in_the_store_with_who_published(client):
    store = {p["pack_id"]: p for p in client.get("/store").json()}
    assert store["kyc-uae"]["source"] == "built-in"
    r = client.post("/packs/publish", json={"spec": spec()}, headers=PRIYA)
    assert r.status_code == 201
    store = {p["pack_id"]: p for p in client.get("/store").json()}
    assert store["test-clinic"]["source"] == "published"
    assert store["test-clinic"]["published_by"] == "priya"


def test_another_instance_regenerates_a_published_agent_from_the_store(tmp_path):
    shared = InMemoryPackStore()
    shared.save("default", spec(), "omar")
    packs = load_packs(Settings().packs_dir)
    runner = CaseRunner(packs, MemorySaver, InMemoryCaseStore(), InMemoryEventBus(),
                        packs_dir=Settings().packs_dir, published_dir=tmp_path / "published",
                        pack_store=shared)
    assert runner.has_pack("test-clinic")
    assert (tmp_path / "published" / "test_clinic" / "pack.yaml").exists()


# ------------------------------------------------------------ named reviewers

def test_the_decision_records_which_reviewer_made_it(client):
    cid = _case(client)
    client.post(f"/cases/{cid}/interview-result", json={"fields": RISKY})
    r = client.post(f"/cases/{cid}/decision", json={"action": "reject", "note": "hit"},
                    headers={"X-API-Key": "key-omar"})
    assert r.status_code == 200
    assert r.json()["decision"]["reviewer"] == "omar"
    assert r.json()["decision"]["by"] == "Compliance Officer"


def test_named_keys_parse_and_bare_keys_still_work():
    from voxgate.service.auth import identify, parse_named_keys
    keys = parse_named_keys("priya:k1, k2 ,omar:k3")
    assert keys == [("priya", "k1"), ("operator", "k2"), ("omar", "k3")]
    assert identify("k3", keys) == "omar" and identify("nope", keys) is None


# ------------------------------------------------------------------ analytics

def test_analytics_and_public_stats(client):
    risky = _case(client)
    client.post(f"/cases/{risky}/interview-result", json={"fields": RISKY})
    _case(client)  # started, never answered
    a = client.get("/analytics", headers=PRIYA).json()
    kyc = next(x for x in a["agents"] if x["pack_id"] == "kyc-uae")
    assert kyc["cases"] == 2 and kyc["completed_interviews"] == 1
    assert a["totals"]["awaiting_review"] == 1
    assert client.get("/analytics").status_code == 401

    s = client.get("/stats").json()
    assert s == {"interviews_started": 2, "cases_screened": 1, "agents_live": s["agents_live"]}
    assert s["agents_live"] >= 9
