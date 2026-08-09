# Task 8 review package - full contents of created/changed files

=== FILE: src/voxgate/service/app.py ===
import asyncio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from langgraph.checkpoint.memory import MemorySaver
from voxgate.config import Settings, get_settings
from voxgate.packs.loader import load_packs
from .runner import CaseRunner
from .store import CaseStore
from .events import EventBus

class CreateCase(BaseModel):
    pack_id: str

class FieldsPayload(BaseModel):
    fields: dict
    confidence: dict = {}

class DecisionPayload(BaseModel):
    action: str
    note: str = ""

def _postgres_factory(dsn: str):
    from langgraph.checkpoint.postgres import PostgresSaver
    import psycopg
    conn = psycopg.connect(dsn, autocommit=True)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver

def create_app(settings: Settings | None = None, runner: CaseRunner | None = None) -> FastAPI:
    settings = settings or get_settings()
    if runner is None:
        factory = (lambda: _postgres_factory(settings.database_url)) \
                  if settings.database_url else MemorySaver
        runner = CaseRunner(load_packs(settings.packs_dir), factory, CaseStore(), EventBus())
    app = FastAPI(title="VoxGate")

    def _case_or_404(case_id):
        case = runner.store.get(case_id)
        if case is None:
            raise HTTPException(404, "case not found")
        return case

    @app.get("/packs")
    def packs():
        return [{"pack_id": p.pack_id, "display_name": p.display_name,
                 "gate_role": p.gate_role,
                 "fields": list(p.schema_model.model_fields)}
                for p in runner.packs.values()]

    @app.post("/cases", status_code=201)
    def create_case(body: CreateCase):
        if body.pack_id not in runner.packs:
            raise HTTPException(404, "unknown pack")
        return runner.start_case(body.pack_id)

    @app.get("/cases")
    def list_cases(pack_id: str | None = None):
        return runner.store.list(pack_id)

    @app.get("/cases/{case_id}")
    def get_case(case_id: str):
        return _case_or_404(case_id)

    @app.patch("/cases/{case_id}/fields")
    def patch_fields(case_id: str, body: FieldsPayload):
        _case_or_404(case_id)
        return runner.patch_fields(case_id, body.fields, body.confidence)

    @app.post("/cases/{case_id}/interview-result")
    def interview_result(case_id: str, body: FieldsPayload):
        case = _case_or_404(case_id)
        if not case.get("interrupt") or case["interrupt"]["type"] != "interview":
            raise HTTPException(409, "case is not awaiting an interview")
        return runner.resume(case_id, {"fields": body.fields, "confidence": body.confidence})

    @app.post("/cases/{case_id}/decision")
    def decision(case_id: str, body: DecisionPayload):
        case = _case_or_404(case_id)
        if not case.get("interrupt") or case["interrupt"]["type"] != "review":
            raise HTTPException(409, "case is not awaiting review")
        return runner.resume(case_id, {"action": body.action, "note": body.note})

    @app.websocket("/cases/{case_id}/events")
    async def events(ws: WebSocket, case_id: str):
        await ws.accept()
        cursor = 0
        try:
            while True:
                batch = await asyncio.to_thread(runner.bus.wait, case_id, cursor, 1.0)
                for event in batch:
                    await ws.send_json(event)
                cursor += len(batch)
        except WebSocketDisconnect:
            pass

    return app

# NOTE (Implementer deviation from brief's literal `app = create_app()`):
# Calling create_app() eagerly at import time would load real packs and
# build LangGraph graphs every time this module is imported — including
# every test-collection pass of tests/test_api.py, which only needs
# create_app(runner=...). Per the brief's implementer note, `app` is
# instead built lazily on first attribute access (PEP 562 module
# __getattr__), so `uvicorn voxgate.service.app:app` still works
# unchanged, but importing the module for testing has no side effects.
def __getattr__(name):
    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


=== FILE: tests/test_api.py ===
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

def test_packs_listing(client):
    packs = client.get("/packs").json()
    assert packs[0]["pack_id"] == "kyc-uae"
    assert "full_name" in packs[0]["fields"]

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

