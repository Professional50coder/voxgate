# Phase 8 — FastAPI App (REST + WebSocket)

**Status:** 🟡 Built — task review pending (pipeline paused)

> Implementation is complete and the full test suite is green (39/39), but the SDD pipeline was paused by the user on 2026-08-06 before this task's review step ran. Treat the content below as accurate to the current source, but not yet review-approved — no fix rounds, deferred minors, or parked findings exist for this phase yet because review has not happened.

## 1. Purpose

Phase 8 is the platform's HTTP/WebSocket surface — the API layer the design spec's frontend (`/apply`, `/review` — out of scope until a later plan) and the demo script (Phase 9) talk to. It is a thin FastAPI wrapper: essentially every route delegates directly to a `CaseRunner` method or a `CaseStore` read, with the API layer's own job limited to HTTP status-code semantics (404 for unknown packs/cases, 409 for state-conflicting actions) and request/response shaping.

## 2. What was built

| File | Responsibility |
|---|---|
| `src/voxgate/service/app.py` | `create_app(settings, runner) -> FastAPI`, request/response pydantic models, `_postgres_factory(dsn)`, all routes, lazy module-level `app` |
| `tests/test_api.py` | 5 tests: pack listing, full case lifecycle over HTTP, decision-flow 409 conflicts, 404s, WebSocket history-then-live streaming |

## 3. Public interfaces

```python
# src/voxgate/service/app.py
class CreateCase(BaseModel):
    pack_id: str

class FieldsPayload(BaseModel):
    fields: dict
    confidence: dict = {}

class DecisionPayload(BaseModel):
    action: str
    note: str = ""

def _postgres_factory(dsn: str): ...          # PostgresSaver over a psycopg autocommit connection, .setup() run

def create_app(settings: Settings | None = None, runner: CaseRunner | None = None) -> FastAPI: ...

def __getattr__(name):                        # PEP 562 module-level lazy attribute
    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

Routes (all verified against `app.py` and exercised by `tests/test_api.py`):

| Route | Behavior |
|---|---|
| `GET /packs` | `[{pack_id, display_name, gate_role, fields: [...]}]` — `fields` is `list(p.schema_model.model_fields)` |
| `POST /cases` `{"pack_id": str}` | 201 + case dict via `runner.start_case`; 404 if `body.pack_id not in runner.packs` |
| `GET /cases?pack_id=` | `runner.store.list(pack_id)` |
| `GET /cases/{id}` | case dict via `_case_or_404`; 404 if unknown |
| `PATCH /cases/{id}/fields` `{"fields": {...}, "confidence": {...}}` | `runner.patch_fields(...)`, after a 404 check |
| `POST /cases/{id}/interview-result` `{"fields": {...}, "confidence": {...}}` | `runner.resume(...)`; 409 if `case["interrupt"]` is falsy or its `type != "interview"` |
| `POST /cases/{id}/decision` `{"action": "approve"\|"reject"\|"request_info", "note": str}` | `runner.resume(...)`; 409 if `case["interrupt"]` is falsy or its `type != "review"` |
| `WS /cases/{id}/events` | accepts, then loops `asyncio.to_thread(runner.bus.wait, case_id, cursor, 1.0)`, sending each new event as JSON and advancing `cursor`; exits cleanly on `WebSocketDisconnect` |

## 4. Key design decisions & why

- **`create_app(settings=None, runner=None)` accepts a pre-built `runner` for dependency injection.** Every test in `tests/test_api.py` constructs its own `CaseRunner` with `MemorySaver` and passes it directly to `create_app`, so tests never touch the module-level `app` (which loads real packs and, per `Settings`, potentially a real Postgres connection).
- **Module-level `app` is built lazily via a PEP 562 module `__getattr__`, not the brief's literal eager `app = create_app()`.** This is a documented, brief-sanctioned deviation (see §6): eagerly calling `create_app()` at import time would run `load_packs(settings.packs_dir)` and build a full LangGraph graph per pack as a side effect of merely importing `voxgate.service.app` — which happens on every collection of `tests/test_api.py` (it does `from voxgate.service.app import create_app`), even though the tests only ever call `create_app(runner=...)`. `__getattr__` builds `app` only on first attribute access, so `uvicorn voxgate.service.app:app` is unaffected (uvicorn resolves `app` by attribute access, which triggers `__getattr__` and builds the real app exactly as before), while importing the module for testing has zero side effects.
- **Conflict semantics are 409, not 400 or a silent no-op.** `POST /cases/{id}/interview-result` checks `case["interrupt"]["type"] == "interview"` before calling `runner.resume`, and `POST /cases/{id}/decision` checks `case["interrupt"]["type"] == "review"` — submitting an interview result to a case that's actually awaiting review (or vice versa) is a genuine state conflict. `test_decision_flow_and_conflicts` verifies both directions: a decision posted before any review interrupt exists, and a second interview-result posted while a case is `awaiting_review`, both 409 rather than silently corrupting graph state.
- **The checkpointer factory choice — `MemorySaver` vs. Postgres — is made once, inside `create_app`, based on `settings.database_url`.** `factory = (lambda: _postgres_factory(settings.database_url)) if settings.database_url else MemorySaver`, then passed into `CaseRunner`. This is the concrete point where Phase 1's `Settings.database_url is None` "in-memory dev mode" default takes effect for the live service (test fixtures always pass `MemorySaver` explicitly instead).
- **`_postgres_factory(dsn)` constructs a `PostgresSaver` from a raw `psycopg` connection with `autocommit=True` and calls `.setup()`** — `.setup()` creates/migrates LangGraph's checkpoint tables, so the very first Postgres-backed app boot is self-migrating with no separate migration step.
- **The WebSocket handler is a polling loop over the synchronous `EventBus.wait`, bridged via `asyncio.to_thread`** (`await asyncio.to_thread(runner.bus.wait, case_id, cursor, 1.0)` in a `while True` loop, sending each new event as JSON and disconnecting cleanly on `WebSocketDisconnect`). This keeps `EventBus` itself fully synchronous/thread-based (consistent with Phase 7) while still giving FastAPI's async event loop a non-blocking way to wait on it — the 1-second poll timeout bounds how long a slow client keeps a thread-pool worker occupied per iteration.
- **`GET /packs`'s `fields` key is `list(pack.schema_model.model_fields)`** — derived directly from the pack's live pydantic `Schema` class, not a separately maintained field list, so a pack's interview field set can never drift out of sync with what `GET /packs` advertises to a client.
- **Status vocabulary is never hardcoded in `app.py`.** The exact strings (`awaiting_interview`, `processing`, `awaiting_review`, `approved`, `rejected`, `needs_attention`) flow through unchanged from `CaseRunner`/`CaseStore` — the API layer has no place to drift from the vocabulary because it never re-encodes it.

## 5. How to run the API

```sh
uv run uvicorn voxgate.service.app:app --reload
```

Then open **http://127.0.0.1:8000/docs** for the interactive Swagger UI (FastAPI's auto-generated OpenAPI docs), where every route above can be exercised by hand — create a case against the `kyc-uae` pack, submit interview fields, and (for a `RISKY`-shaped payload) submit a reviewer decision. With no `VOXGATE_DATABASE_URL` set, this runs fully in-memory (no Postgres required).

## 6. Test evidence

From `task-8-report.md` — 5/5 in `test_api.py`, 39/39 in the full suite, one known unavoidable warning:

```
tests/test_api.py::test_packs_listing PASSED                             [ 20%]
tests/test_api.py::test_case_lifecycle_over_http PASSED                  [ 40%]
tests/test_api.py::test_decision_flow_and_conflicts PASSED               [ 60%]
tests/test_api.py::test_unknown_pack_and_case_404 PASSED                 [ 80%]
tests/test_api.py::test_ws_streams_history_then_live PASSED              [100%]
5 passed, 1 warning in 2.02s
```

```
uv run pytest -q
39 passed, 1 warning in 2.36s
```
(39 = 34 pre-existing from Tasks 1–7 + 5 new from Task 8.)

- `test_packs_listing` — `GET /packs` returns `kyc-uae` first with `"full_name"` present in its `fields` list.
- `test_case_lifecycle_over_http` — full case lifecycle purely over HTTP: `POST /cases` → `awaiting_interview`; `PATCH .../fields` (live patch); `POST .../interview-result` with `CLEAN` → `approved`; a follow-up `GET` confirms `score.band == "low"`.
- `test_decision_flow_and_conflicts` — a `decision` posted before any review interrupt exists returns 409; submitting `RISKY` parks the case at `awaiting_review`; a second `interview-result` posted while awaiting review also returns 409; the eventual `decision` (`reject`) resolves to `status == "rejected"`.
- `test_unknown_pack_and_case_404` — `POST /cases` with an unknown `pack_id` and `GET /cases/{unknown}` both return 404.
- `test_ws_streams_history_then_live` — connecting to `WS /cases/{id}/events` immediately receives the case's `"state"`-kind history; a subsequent `PATCH .../fields` call produces a live `"fields"`-kind event over the same socket.

**Known, unavoidable warning:** `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` This fires from `fastapi/testclient.py`'s own `from starlette.testclient import TestClient as TestClient` line — i.e., the instant `from fastapi.testclient import TestClient` (the brief's mandated, verbatim first import in `tests/test_api.py`) executes, before any project code runs. It's a property of the pinned dependency versions in this environment (fastapi 0.141.1 / starlette 1.4.1 / httpx 0.28.1) advising a `httpx2` package that is not a project dependency; adding it was judged outside this task's scope (no dependency changes requested, and pulling in a new package solely to silence a library-emitted deprecation notice would be overbuilding). Confirmed intrinsic to using `TestClient` at all with the currently locked versions — not caused by anything in `app.py` or `test_api.py` beyond the brief's own mandated import.

## 7. Review history

**Not yet performed.** Per the ledger (`.superpowers/sdd/2026-08-06-voxgate-core-platform/progress.md`):

> Task 8: implemented DONE (39/39 full suite; lazy module-level app via PEP 562 __getattr__ per brief note; one StarletteDeprecationWarning from fastapi.testclient import itself) — TASK REVIEW PENDING, pipeline paused by user 2026-08-06

Implementation is complete and self-reviewed by the implementer (see the report's "Self-review" section: completeness vs. brief confirmed for all 7 routes; 404/409 semantics confirmed by tests; pristine output modulo the one documented unavoidable warning; no overbuilding — the only deviation from the brief's literal code is the sanctioned lazy-loading guard). No independent review has run yet, so there is no fix round, no deferred-minors list, and no parked findings to report for this phase — those will be added once review resumes.

**One documented deviation from the brief's literal code** (implementer-flagged, brief-sanctioned, pending independent confirmation): the lazy module-level `app` via `__getattr__` in place of the brief's literal `app = create_app()`, described in §4 above. The brief's own implementer note explicitly anticipates and permits this: *"if that's annoying for tests importing the module, guard it with a lazy factory... the tests only require `create_app(runner=...)`."*

## 8. Dependencies

- **Consumes:** Phase 7 (`CaseRunner`, `CaseStore`, `EventBus`), Phase 1 (`Settings`, `get_settings`), Phase 4 (`load_packs`, for the lazily-built module-level `app`).
- **Feeds:** Phase 9 (`scripts/demo_case.py`, not yet built, is planned to drive this HTTP API against a running `uvicorn voxgate.service.app:app` process; the planned Postgres durability integration test is expected to import `_postgres_factory` directly from this module — both currently blocked by the paused pipeline).
