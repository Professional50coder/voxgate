import asyncio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from langgraph.checkpoint.memory import MemorySaver
from voxgate.config import Settings, get_settings
from voxgate.packs.loader import load_packs
from .runner import CaseRunner
from .store import CaseStore
from .events import EventBus
from .dashboard import STATIC_DIR, build_dashboard
from voxgate import groq_brain

class CreateCase(BaseModel):
    pack_id: str

class FieldsPayload(BaseModel):
    fields: dict
    confidence: dict = {}

class DecisionPayload(BaseModel):
    action: str
    note: str = ""

class RecoverBody(BaseModel):
    pack_id: str

class CaptionBody(BaseModel):
    role: str            # "agent" | "applicant"
    text: str
    interim: bool = False

class AnswerBody(BaseModel):
    field: str
    transcript: str

class AgentLineBody(BaseModel):
    field: str
    hint: str = ""
    last_captured: dict | None = None
    transcript: str = ""
    attempt: int = 0

class GreetingBody(BaseModel):
    name: str = ""
    hour: int | None = None

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
                 "fields": list(p.schema_model.model_fields),
                 # Natural-language question prompts per field, so a voice agent
                 # can phrase the interview live (see packs/<id>/schema.py REASK_HINTS).
                 "reask_hints": p.reask_hints,
                 "feature_field_hints": p.feature_field_hints}
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

    @app.post("/cases/{case_id}/captions")
    def publish_caption(case_id: str, body: CaptionBody):
        """Publish a caption event (agent question or applicant answer) to a case's
        live event stream, so the dashboard orb/transcript animate in real time.

        The event bus is transport-agnostic: the browser voice session writes here
        today; a future Pipecat pipeline can publish the same shape.
        """
        _case_or_404(case_id)
        runner.bus.publish(case_id, {"kind": "caption", "role": body.role,
                                     "text": body.text, "interim": body.interim})
        return {"ok": True}

    @app.post("/cases/{case_id}/answer")
    def interpret_answer(case_id: str, body: AnswerBody):
        """Interpret a spoken answer for one interview field into a canonical value.

        Uses the optional Groq brain (``GROQ_API_KEY``); without a key it falls
        back to the raw transcript so the loop still works. The value is NOT
        committed to the case here — the client accumulates fields and submits
        them together via /interview-result (which runs LangGraph validation).
        """
        case = _case_or_404(case_id)
        pack = runner.packs[case["pack_id"]]
        hints = pack.reask_hints.get(body.field)
        return groq_brain.interpret_answer(body.field, body.transcript, hints=hints)

    @app.post("/cases/{case_id}/agent-line")
    def agent_line(case_id: str, body: AgentLineBody):
        """Craft the agent's next spoken line (Pipecat-style conversational turn).

        Groq brain writes one natural sentence that briefly acknowledges the last
        captured field and asks for `body.field` — or asks for clarification when
        a previous answer wasn't understood. Falls back to the pack hint when no
        key / call fails. Purely a conversational-layer helper; it does not mutate
        the case.
        """
        _case_or_404(case_id)
        return groq_brain.agent_line(
            body.field, body.hint, last_captured=body.last_captured,
            transcript=body.transcript, attempt=body.attempt)

    @app.post("/cases/{case_id}/agent-greeting")
    def agent_greeting(case_id: str, body: GreetingBody):
        """Produce the agent's opening line: a time-of-day greeting + interview intro.

        The voice session calls this once when it starts so the agent opens
        naturally (``GROQ_API_KEY`` -> LLM-crafted; otherwise a template line).
        """
        _case_or_404(case_id)
        return groq_brain.greeting(name=body.name, hour=body.hour)

    @app.post("/cases/{case_id}/decision")
    def decision(case_id: str, body: DecisionPayload):
        case = _case_or_404(case_id)
        if not case.get("interrupt") or case["interrupt"]["type"] != "review":
            raise HTTPException(409, "case is not awaiting review")
        return runner.resume(case_id, {"action": body.action, "note": body.note})

    @app.post("/cases/{case_id}/recover")
    def recover(case_id: str, body: RecoverBody):
        # Rehydrate a case that exists only in the checkpointer after a restart (the in-memory store is empty), so unknown case_ids are NOT 404d; only unknown pack_ids 404.
        if body.pack_id not in runner.packs:
            raise HTTPException(404, "unknown pack")
        return runner.recover_case(case_id, body.pack_id)

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

    @app.websocket("/cases/{case_id}/voice")
    async def voice(ws: WebSocket, case_id: str, scenario: str = "kyc-interview"):
        """Realtime voice session (Pipecat): Groq Whisper STT -> Groq LLM ->
        Cartesia Sonic TTS. Select a usecase via `?scenario=`. The agent is
        anchored to this case's LangGraph interview plan (fields in order +
re-asks). Blocks until the client disconnects."""
        from .voice.agent import run_case_voice
        # pipecat's FastAPIWebsocketTransport does not call `accept()` itself;
        # the route must accept the connection up front or uvicorn rejects it.
        await ws.accept()
        case = runner.store.get(case_id)
        fields = None
        if case is not None:
            pack = runner.packs.get(case["pack_id"])
            hints = (pack.reask_hints if pack else {}) or {}
            interrupt = case.get("interrupt") or {}
            if interrupt.get("type") == "interview" and interrupt.get("reask_fields"):
                fields = [{"field": f, "hint": hints.get(f, "")}
                          for f in interrupt["reask_fields"]]
            elif pack is not None:
                fields = [{"field": f, "hint": hints.get(f, "")}
                          for f in list(pack.schema_model.model_fields)]
        await run_case_voice(ws, case_id=case_id, scenario=scenario, fields=fields,
                             publish=lambda role, text, interim: runner.bus.publish(
                                 case_id, {"kind": "caption", "role": role,
                                           "text": text, "interim": interim}))

    @app.get("/voice/scenarios")
    def voice_scenarios():
        from .voice.agent import SCENARIOS
        return [{"id": sid, "display_name": s["display_name"]} for sid, s in SCENARIOS.items()]

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(build_dashboard(runner))

    @app.middleware("http")
    async def _no_cache_assets(request, call_next):
        """Ensure the browser always fetches the latest JS/CSS (the dashboard is
        actively iterated on, so stale cached assets make changes invisible)."""
        response = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path == "/dashboard":
            for k, v in NO_CACHE.items():
                response.headers.setdefault(k, v)
        return response

    return app

NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

# NOTE (Implementer deviation from brief's literal `app = create_app()`):
# Calling create_app() eagerly at import time would load real packs and
# build LangGraph graphs every time this module is imported — including
# every test-collection pass of tests/test_api.py, which only needs
# create_app(runner=...). Per the brief's implementer note, `app` is
# instead built lazily on first attribute access (PEP 562 module
# __getattr__), so `uvicorn voxgate.service.app:app` still works
# unchanged, but importing the module for testing has no side effects.
# The built instance is memoized in `_app_instance` so repeated `app`
# accesses (e.g. two `getattr(module, "app")` calls) return the same
# singleton FastAPI/CaseRunner/CaseStore/EventBus instance rather than
# each rebuilding an independent one with disjoint state.
_app_instance: FastAPI | None = None

def __getattr__(name):
    global _app_instance
    if name == "app":
        if _app_instance is None:
            _app_instance = create_app()
        return _app_instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
