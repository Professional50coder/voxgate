import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langgraph.checkpoint.memory import MemorySaver
from voxgate import transcripts
from voxgate.config import Settings, get_settings
from voxgate.packs.loader import load_packs
from .runner import CaseRunner
from .store import InMemoryCaseStore, PgCaseStore
from .events import InMemoryEventBus, PgEventBus
from .auth import build_admin_guard, parse_keys
from .middleware import RateLimitMiddleware, RequestContextMiddleware
from .quota import PgQuota

logger = logging.getLogger(__name__)

# Endpoints that spend an LLM call or write generated Python. See
# RateLimitMiddleware for why the cap is per process.
COSTLY_PATHS = ("/packs/draft", "/packs/publish")
COSTLY_LIMIT = 30
COSTLY_WINDOW = 60.0

class CreateCase(BaseModel):
    pack_id: str

class FieldsPayload(BaseModel):
    fields: dict
    confidence: dict = {}

class DecisionPayload(BaseModel):
    action: str
    note: str = ""

# Bounds on anything a client supplies that reaches an LLM or the filesystem.
# Without them a large body is billed to us, can exceed the model's context, and
# gives an anonymous caller a cheap way to burn the whole daily quota.
class ExtractPayload(BaseModel):
    field: str = Field(max_length=128)
    spoken: str = Field(max_length=4_000)
    # How many attempts on this field have already failed. Drives which rung of
    # the re-ask ladder comes back, so the browser flow gets the same escalation
    # the voice flow does without reimplementing it in TypeScript.
    attempt: int = Field(default=0, ge=0, le=10)
    # Conversation budgets, echoed back by the browser each turn so the API
    # stays stateless (serverless instances share no memory).
    smalltalk_used: int = Field(default=0, ge=0, le=50)
    off_topic_strikes: int = Field(default=0, ge=0, le=50)

class TTSPayload(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    # Speak in this pack agent's voice; omitted means the default agent.
    pack_id: str | None = Field(default=None, max_length=64)

class AssistantTurn(BaseModel):
    role: str = Field(max_length=16)
    text: str = Field(max_length=1_000)

class AssistantPayload(BaseModel):
    message: str = Field(min_length=1, max_length=1_000)
    page: str = Field(default="home", max_length=32)
    history: list[AssistantTurn] = Field(default_factory=list, max_length=12)
    # What the page is showing, e.g. a case on the console. Plain text, capped.
    context: str | None = Field(default=None, max_length=3_000)

class DraftPayload(BaseModel):
    description: str = Field(min_length=20, max_length=4_000)
    pack_id: str | None = Field(default=None, max_length=64)

class PublishPayload(BaseModel):
    # A spec is a small object: a dozen fields, a dozen checks, some prose. The
    # emitters walk it and write a file per key, so an unbounded body is a disk
    # fill and a CPU burn with no auth in front of it. 64 KiB is roughly 20x the
    # largest spec the drafter produces.
    spec: dict = Field(max_length=64 * 1024)
    overwrite: bool = False

def _postgres_factory(dsn: str):
    # Delegates to db.make_checkpointer_sync rather than duplicating it. The
    # duplicate here omitted prepare_threshold=0, which db.py documents as
    # required: behind pgbouncer or a Neon pooled endpoint the checkpointer
    # would break while the case store kept working.
    from .db import make_checkpointer_sync

    return make_checkpointer_sync(dsn)

def create_app(settings: Settings | None = None, runner: CaseRunner | None = None) -> FastAPI:
    settings = settings or get_settings()
    # A caller-supplied runner brings its own storage, so there is nothing here
    # to build a shared counter against.
    quota = None
    if runner is None:
        factory = (lambda: _postgres_factory(settings.database_url)) \
                  if settings.database_url else MemorySaver
        # Durable when a database is configured, in-memory otherwise. The
        # contract suite runs against both, so behaviour cannot diverge.
        if settings.database_url:
            from .db import ensure_schema_sync, open_pool_sync

            pool = open_pool_sync(settings.database_url)
            ensure_schema_sync(pool)
            store = PgCaseStore(pool)
            # Both must be durable together. A Postgres store behind an
            # in-memory bus is the worst of both: the board is correct after a
            # restart, but the live stream a second worker publishes to is
            # invisible, so the UI looks frozen until the user reloads.
            bus = PgEventBus(pool, tenant_id=CaseRunner.DEFAULT_TENANT)
            # Separate from `pool` on purpose: see CaseRunner._case_lock. A
            # connection here is held for a whole graph invocation, and the work
            # under it borrows from `pool`, so sharing one pool deadlocks.
            lock_pool = open_pool_sync(settings.database_url, min_size=0, max_size=10)
            quota = PgQuota(pool, limit=settings.quota_daily_limit)
        else:
            store = InMemoryCaseStore()
            bus = InMemoryEventBus()
            lock_pool = None
            # No database, no shared counter. The burst window is the right
            # amount of machinery for a single-process dev run.
            quota = None
        runner = CaseRunner(
            load_packs(settings.packs_dir), factory, store, bus,
            packs_dir=settings.packs_dir, lock_pool=lock_pool,
        )
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Warm the Groq model list in the background, so the first applicant's
        # first answer does not also pay for model discovery. Fire and forget:
        # startup never waits on, or fails because of, a hosted API.
        keys = settings.groq_key_pool()
        if keys:
            from voxgate.ml.groq_client import discover_models
            asyncio.get_running_loop().run_in_executor(None, discover_models, keys[0])
        yield
        # Graceful shutdown. Without this, SIGTERM tore the process down with
        # connections still checked out: Postgres logged a wall of unexpected
        # EOFs on every deploy, and the checkpointer's own connection was never
        # closed at all.
        for name, pool in (("store", getattr(runner.store, "_pool", None)),
                           ("lock", runner.lock_pool)):
            if pool is None:
                continue
            try:
                pool.close()
            except Exception:
                logger.warning("error closing the %s connection pool", name, exc_info=True)
        conn = getattr(runner.checkpointer, "conn", None)
        if conn is not None and hasattr(conn, "close"):
            try:
                conn.close()
            except Exception:
                logger.warning("error closing the checkpointer connection", exc_info=True)

    # One dependency, built from THESE settings rather than global ones, so an
    # app constructed with explicit settings authenticates against them.
    operator = Depends(build_admin_guard(settings))

    app = FastAPI(title="VoxGate", lifespan=lifespan)
    # The standard FastAPI seam for per-app singletons. Routes close over
    # `runner` directly; this is for anything holding the app rather than a
    # request â€” shutdown, operational tooling, and tests.
    app.state.runner = runner

    # ORDER MATTERS AND IS COUNTERINTUITIVE. `add_middleware` inserts at the
    # front of the stack, so the LAST one added ends up OUTERMOST. Rate limit
    # added first and request context second means RequestContextMiddleware
    # wraps everything, which is what makes a 429 carry an X-Request-ID and
    # appear in the access log. Added the other way round -- as this was, with a
    # comment claiming the opposite -- the rate limiter short-circuits before
    # the context layer is entered, so exactly the abuse traffic you want
    # correlated is the traffic that gets no id and no log line.
    app.add_middleware(
        RateLimitMiddleware,
        # /tts and /assistant are public and each spends a paid call.
        paths=COSTLY_PATHS + ("/packs/", "/tts", "/assistant"),
        limit=COSTLY_LIMIT,
        window=COSTLY_WINDOW,
        quota=quota,
    )
    app.add_middleware(RequestContextMiddleware)

    # The dashboard is served from a different origin (Next.js dev server, and a
    # separate deploy in production), so the browser preflights every request.
    # Without this the API answers curl normally but the browser blocks it.
    # "*" with allow_credentials is not a wildcard, it is worse: Starlette
    # echoes back whatever Origin the request carried, so every site on the
    # internet becomes an allowed origin *with cookies*. If an operator sets
    # "*", credentials are dropped and it behaves like the public API it is.
    allow_any_origin = "*" in settings.cors_origins
    if allow_any_origin:
        logger.warning(
            "CORS is set to '*'; disabling credentialed cross-origin requests. "
            "Set VOXGATE_CORS_ORIGINS to your real frontend origins."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=not allow_any_origin,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    def _case_or_404(case_id):
        # Scoped by tenant even though auth is stubbed, so enabling real
        # tenancy later is a change to how the tenant is resolved, not a sweep
        # through every handler.
        case = runner.store.get(runner.tenant, case_id)
        if case is None:
            raise HTTPException(404, "case not found")
        return case

    @app.get("/health")
    def health():
        """Liveness. Cheap and dependency-free on purpose: if this fails the
        process is wedged, and a restart is the right response."""
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        """Readiness. Reports whether the process can actually serve traffic.

        Deliberately separate from liveness: a process that is up but cannot
        reach Postgres should be pulled out of rotation, not restarted.
        """
        checks: dict[str, object] = {"packs": len(runner.packs)}
        checks["auth"] = "enabled" if parse_keys(settings.api_keys) else "disabled"
        ok = bool(runner.packs)

        if settings.database_url:
            try:
                store = runner.store
                pool = getattr(store, "_pool", None)
                if pool is not None:
                    with pool.connection() as conn:
                        conn.execute("SELECT 1", prepare=False)
                    checks["database"] = "ok"
                else:
                    checks["database"] = "not pooled"
            except Exception as exc:
                # Type only, never the message: a connection error string can
                # carry the host, port and user.
                checks["database"] = f"error: {type(exc).__name__}"
                ok = False
        else:
            checks["database"] = "in-memory"

        if not ok:
            raise HTTPException(503, {"status": "not ready", "checks": checks})
        return {"status": "ready", "checks": checks}

    @app.get("/agents/status", dependencies=[operator])
    def agents_status():
        """What the intelligence layer is running on. Operator-only; key
        health is reported by position, never by value or fingerprint."""
        from voxgate.ml import groq_client
        keys = settings.groq_key_pool()
        status: dict[str, object] = {"llm": "enabled" if keys else "disabled",
                                     "keys": groq_client.key_health(keys)}
        if keys:
            strict, lenient = groq_client.discover_models(keys[0])
            status["models"] = {"preferred": settings.groq_model,
                                "strict": strict, "lenient": lenient}
        return status

    @app.get("/packs")
    def packs():
        # The catalogue must show packs published by other workers, not just
        # this process's start-up snapshot. Throttled inside the runner.
        runner.refresh_packs()
        # reask_hints are the pack's own question phrasings. The applicant-facing
        # interview surface reads them from here so the pack stays the single
        # source of truth for what gets asked, rather than the questions being
        # duplicated in frontend code.
        from voxgate.ml.extract import allowed_values

        def values_for(pack):
            """The permitted values per field, where the pack constrains them.

            Exposed so a client can offer them rather than guess. The voice
            interview uses this to read the options aloud when an applicant says
            they do not know â€” which is the difference between a re-ask that
            helps and one that repeats the same sentence. The system always had
            this list; it simply never left the server.
            """
            out = {}
            for name in pack.schema_model.model_fields:
                allowed = allowed_values(pack.schema_model, name)
                if allowed:
                    out[name] = allowed
            return out

        return [{"pack_id": p.pack_id, "display_name": p.display_name,
                 "gate_role": p.gate_role,
                 "fields": list(p.schema_model.model_fields),
                 "reask_hints": p.reask_hints,
                 "field_values": values_for(p),
                 # The pack's voice agent: persona, voice and house rules. All
                 # of it is applicant-facing already, so nothing here is secret.
                 "agent": p.agent.model_dump()}
                for p in runner.packs.values()]

    @app.post("/packs/{pack_id}/extract")
    def extract_field(pack_id: str, body: ExtractPayload):
        """Map a spoken answer onto the value this pack's schema requires.

        The applicant interview calls this instead of guessing client-side. The
        allowed values come from the pack itself, so the extractor and the
        validator can never disagree about what is acceptable.
        """
        if not runner.has_pack(pack_id):
            raise HTTPException(404, "unknown pack")
        pack = runner.packs[pack_id]
        if body.field not in pack.schema_model.model_fields:
            raise HTTPException(404, "unknown field")

        from voxgate.ml.extract import allowed_values, build_extractor
        from voxgate.ml.understanding import Intent
        from voxgate.dialogue import brain, phrasing

        t0 = time.perf_counter()
        allowed = allowed_values(pack.schema_model, body.field)
        question = pack.reask_hints.get(body.field, "")

        # What the person DID, before what it maps to. An utterance that is not
        # an attempt to answer must not be extracted: that is what let "I don't
        # know" become a stored value on a free-text field. The pack's own
        # agent rules are applied first.
        u = brain.understand(body.spoken, pack.agent)
        intent = u.intent
        t1 = time.perf_counter()
        if intent is not Intent.ANSWER:
            result = None
        else:
            result = build_extractor().extract(body.field, allowed, body.spoken)
        t2 = time.perf_counter()

        counters = brain.Counters(body.smalltalk_used, body.off_topic_strikes)
        conversational = brain.non_answer_reply(u, question, counters, pack.agent)

        # The next thing to say, decided here rather than in the browser. Both
        # surfaces asking the same way is the point: a second implementation in
        # TypeScript would drift, and the one that drifted would be the one
        # applicants actually use.
        if conversational is not None:
            prompt = conversational
        elif intent is Intent.REPEAT:
            prompt = question
        elif intent is Intent.QUESTION:
            prompt = phrasing.explain(body.field, question, allowed=allowed)
        elif intent is Intent.REFUSAL:
            prompt = phrasing.acknowledge_refusal(question, attempt=body.attempt)
        elif result is None or result.value is None:
            prompt = phrasing.reask(
                question=question, attempt=body.attempt, allowed=allowed
            )
        else:
            prompt = None

        return {
            "field": body.field,
            "value": result.value if result else None,
            "confidence": result.confidence if result else 0.0,
            "source": result.source if result else "non-answer",
            "allowed": allowed,
            "intent": intent.value,
            "is_answer": intent is Intent.ANSWER,
            # Which layer decided: a rule from this pack's agent block, or the
            # platform's shared patterns.
            "rule": u.rule,
            # None when the answer landed; otherwise what to show the applicant.
            "prompt": prompt,
            "counters": {"smalltalk_used": counters.smalltalk,
                         "off_topic_strikes": counters.off_topic},
            # Server-side cost of this turn, so latency is measured, not claimed.
            "timing_ms": {"understand": round((t1 - t0) * 1000, 2),
                          "extract": round((t2 - t1) * 1000, 2),
                          "total": round((time.perf_counter() - t0) * 1000, 2)},
        }

    @app.get("/tts")
    def tts_get(text: str = Query(min_length=1, max_length=600),
                pack_id: str | None = Query(default=None, max_length=64)):
        """Same as POST, as a URL an <audio> element can stream directly, so
        playback starts on the first chunk with no client-side buffering."""
        return tts(TTSPayload(text=text, pack_id=pack_id))

    @app.post("/tts")
    def tts(body: TTSPayload):
        """Speak a line in an agent's voice: its primary, then its fallback.

        503 means neither voice is reachable (or no key is set), and the page
        should use the browser's own voice. The key never leaves the server.
        """
        from fastapi.responses import StreamingResponse
        from voxgate.packs.agent import DEFAULT_AGENT
        from voxgate.tts import TTSUnavailable, stream

        agent = DEFAULT_AGENT
        if body.pack_id:
            if not runner.has_pack(body.pack_id):
                raise HTTPException(404, "unknown pack")
            agent = runner.packs[body.pack_id].agent
        try:
            tier, _, first_ms, chunks = stream(body.text, agent.voice, settings)
        except TTSUnavailable as exc:
            raise HTTPException(503, f"voice unavailable: {exc}") from exc
        # Streamed: the page starts playing on the first chunk instead of
        # waiting for the whole sentence to be generated.
        return StreamingResponse(chunks, media_type="audio/mpeg", headers={
            "X-Voice-Tier": tier, "X-TTS-First-Byte-Ms": str(first_ms),
            "X-Agent-Name": agent.name, "Cache-Control": "no-store"})

    @app.post("/assistant")
    def assistant(body: AssistantPayload):
        """The page voice assistant. Answers about VoxGate, and may ask the page
        to perform one action from a fixed list."""
        from voxgate.dialogue.assistant import answer
        return answer(body.message, page=body.page, context=body.context,
                      history=[t.model_dump() for t in body.history],
                      settings=settings)

    @app.post("/packs/draft", dependencies=[operator])
    def draft_new_pack(body: DraftPayload):
        """Draft a scenario pack from a plain-English business description.

        Returns a proposal for a human to review, never a deployed pack. The
        warnings list is the part a reviewer must actually read.
        """
        from voxgate.ml.authoring import DraftError, draft_pack

        try:
            draft = draft_pack(body.description, pack_id=body.pack_id)
        except DraftError as exc:
            # 422: the request was well formed, we could not produce a draft.
            raise HTTPException(422, str(exc)) from exc

        return {
            "pack_id": draft.pack_id,
            "display_name": draft.display_name,
            "gate_role": draft.gate_role,
            "persona": draft.persona,
            "gate_reason": draft.gate_reason,
            "fields": draft.fields,
            "checks": draft.checks,
            "warnings": draft.warnings,
            "spec": draft.to_spec(),
        }

    @app.post("/packs/publish", status_code=201, dependencies=[operator])
    def publish(body: PublishPayload):
        """Write a drafted spec to disk and compile it into a live graph.

        After this returns, the pack appears in GET /packs and POST /cases can
        run it. The pack is byte-identical to one produced by the CLI generator.

        Operator-only. This writes generated Python to the server and imports
        it. Every value that reaches generated source is type-checked or escaped
        by `emit._str`/`emit._num`, with regression tests for the two injections
        that were possible before â€” but defence in depth means it is also behind
        the operator key, and it refuses to overwrite an existing pack unless
        told to. If VOXGATE_API_KEYS is unset the guard is a no-op; readiness
        reports that as `auth: disabled`.
        """
        from voxgate.packs.publish import PublishError, publish_pack, register

        try:
            pack = publish_pack(
                body.spec, settings.packs_dir, overwrite=body.overwrite
            )
        except PublishError as exc:
            raise HTTPException(422, str(exc)) from exc

        register(runner, pack, runner.checkpointer)
        return {
            "pack_id": pack.pack_id,
            "display_name": pack.display_name,
            "gate_role": pack.gate_role,
            "fields": list(pack.schema_model.model_fields),
            "reask_hints": pack.reask_hints,
            "live": pack.pack_id in runner.graphs,
        }

    @app.post("/cases", status_code=201)
    def create_case(body: CreateCase):
        # has_pack, not `in runner.packs`: a pack published through another
        # worker is on disk and in the catalogue but not yet compiled here.
        if not runner.has_pack(body.pack_id):
            raise HTTPException(404, "unknown pack")
        return runner.start_case(body.pack_id)

    @app.get("/cases", dependencies=[operator])
    def list_cases(pack_id: str | None = None):
        return runner.store.list(runner.tenant, pack_id)

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
        try:
            return runner.resume(case_id, {"fields": body.fields,
                                           "confidence": body.confidence})
        except KeyError as exc:
            raise HTTPException(409, "case is not awaiting an interview") from exc

    @app.post("/cases/{case_id}/decision", dependencies=[operator])
    def decision(case_id: str, body: DecisionPayload):
        case = _case_or_404(case_id)
        if not case.get("interrupt") or case["interrupt"]["type"] != "review":
            raise HTTPException(409, "case is not awaiting review")
        try:
            return runner.resume(case_id, {"action": body.action, "note": body.note})
        except KeyError as exc:
            raise HTTPException(409, "case is not awaiting review") from exc

    @app.get("/cases/{case_id}/events")
    def poll_events(case_id: str, after: int = 0, wait: float = 0.0):
        """Long-poll fallback for hosts with no WebSocket support (Vercel).

        Same seq-based cursor as the WebSocket: pass back `cursor` as `after`.
        """
        _case_or_404(case_id)
        batch = runner.bus.wait(case_id, after, max(0.0, min(wait, 10.0)))
        cursor = max((e.get("seq", after) for e in batch), default=after)
        return {"events": batch, "cursor": cursor}

    # Transcripts carry applicant PII, so both reads are operator-only.
    @app.get("/cases/{case_id}/transcripts", dependencies=[operator])
    def case_transcripts(case_id: str):
        _case_or_404(case_id)
        return {"case_id": case_id,
                "sessions": transcripts.list_sessions(case_id, settings)}

    @app.get("/cases/{case_id}/transcripts/{session_id}", dependencies=[operator])
    def case_transcript(case_id: str, session_id: str):
        _case_or_404(case_id)
        session = transcripts.load_session(case_id, session_id, settings)
        if session is None:
            raise HTTPException(404, "unknown transcript session")
        return session

    @app.websocket("/cases/{case_id}/events")
    async def events(ws: WebSocket, case_id: str):
        await ws.accept()
        # Track the last sequence number seen, not how many events arrived.
        # A positional cursor breaks permanently once the bus evicts anything.
        cursor = 0
        try:
            while True:
                batch = await asyncio.to_thread(runner.bus.wait, case_id, cursor, 1.0)
                for event in batch:
                    await ws.send_json(event)
                    cursor = max(cursor, event.get("seq", cursor))
        except WebSocketDisconnect:
            pass

    return app

# NOTE (Implementer deviation from brief's literal `app = create_app()`):
# Calling create_app() eagerly at import time would load real packs and
# build LangGraph graphs every time this module is imported â€” including
# every test-collection pass of tests/test_api.py, which only needs
# create_app(runner=...). Per the brief's implementer note, `app` is
# instead built lazily on first attribute access (PEP 562 module
# __getattr__), so `uvicorn voxgate.service.app:app` still works
# unchanged, but importing the module for testing has no side effects.
# The built instance is memoized in `_app_instance` so repeated `app`
# accesses (e.g. two `getattr(module, "app")` calls) return the same
# singleton FastAPI/CaseRunner/store/EventBus instance rather than
# each rebuilding an independent one with disjoint state.
_app_instance: FastAPI | None = None

def __getattr__(name):
    global _app_instance
    if name == "app":
        if _app_instance is None:
            _app_instance = create_app()
        return _app_instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
