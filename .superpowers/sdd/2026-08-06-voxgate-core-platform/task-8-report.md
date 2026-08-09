# Task 8 Report: FastAPI app — REST + WebSocket

## What was implemented

- `tests/test_api.py` — transcribed verbatim from the brief (5 tests: packs listing,
  case lifecycle over HTTP, decision flow + 409 conflicts, unknown pack/case 404,
  WS history-then-live streaming).
- `src/voxgate/service/app.py` — `create_app(settings=None, runner=None) -> FastAPI`
  plus all six routes (`GET /packs`, `POST /cases`, `GET /cases`, `GET /cases/{id}`,
  `PATCH /cases/{id}/fields`, `POST /cases/{id}/interview-result`,
  `POST /cases/{id}/decision`, `WS /cases/{id}/events`), implemented essentially
  verbatim from the brief's Step 3 code block.

## TDD evidence

**RED** (`uv run pytest tests/test_api.py -v`, before `app.py` existed):
```
ERROR collecting tests/test_api.py
ModuleNotFoundError: No module named 'voxgate.service.app'
```
Matches the brief's expected failure exactly.

**GREEN** (`uv run pytest tests/test_api.py -v`, after implementation):
```
tests/test_api.py::test_packs_listing PASSED                             [ 20%]
tests/test_api.py::test_case_lifecycle_over_http PASSED                  [ 40%]
tests/test_api.py::test_decision_flow_and_conflicts PASSED               [ 60%]
tests/test_api.py::test_unknown_pack_and_case_404 PASSED                 [ 80%]
tests/test_api.py::test_ws_streams_history_then_live PASSED              [100%]
5 passed, 1 warning in 2.02s
```

**Full suite regression** (`uv run pytest -q`):
```
.......................................                                  [100%]
39 passed, 1 warning in 2.36s
```
34 prior tests + 5 new = 39, all green, no failures.

## Files changed

- Created: `src/voxgate/service/app.py`
- Created: `tests/test_api.py`
- No other files touched.

## Deviations from the brief's literal code

1. **Lazy module-level `app` (per the brief's own Implementer note).**
   The brief's literal Step-3 code ends with a bare `app = create_app()` at
   module scope. Calling `create_app()` eagerly at import time invokes
   `load_packs(settings.packs_dir)` and builds a full LangGraph graph per pack
   as a side effect of merely `import`ing `voxgate.service.app` — which
   happens on every collection of `tests/test_api.py` (that module does
   `from voxgate.service.app import create_app`), even though the tests only
   ever call `create_app(runner=...)` with an injected runner. The brief
   explicitly sanctions guarding this: *"if that's annoying for tests
   importing the module, guard it with a lazy factory... the tests only
   require `create_app(runner=...)`."*

   Implementation: replaced the eager `app = create_app()` line with a
   PEP 562 module-level `__getattr__` that builds `app` lazily on first
   attribute access:
   ```python
   def __getattr__(name):
       if name == "app":
           return create_app()
       raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
   ```
   `uvicorn voxgate.service.app:app` is unaffected — uvicorn resolves `app`
   by attribute access on the imported module, which triggers `__getattr__`
   and builds the real app with real packs exactly as before. Only the
   *timing* changed (first access vs. import time); the *tests* import the
   module and only ever call `create_app(runner=...)` directly, so they never
   trigger the lazy path and never pay the real-pack-loading cost.

   Everything else in `app.py` — route bodies, status codes, interrupt-type
   checks, WS loop — is unchanged from the brief's code block.

2. **Unavoidable warning.** The single warning present in both the isolated
   run and the full-suite run:
   ```
   fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with
   `starlette.testclient` is deprecated; install `httpx2` instead.
   ```
   This fires from `fastapi/testclient.py`'s own `from starlette.testclient
   import TestClient as TestClient` line — i.e. it fires the instant
   `from fastapi.testclient import TestClient` (the brief's mandated,
   verbatim first import in `tests/test_api.py`) is executed, before any of
   my code runs. It is a property of the pinned dependency versions in this
   environment (fastapi 0.141.1 / starlette 1.4.1 / httpx 0.28.1) advising a
   `httpx2` package that is not a project dependency and not something this
   task's scope authorizes adding (no dependency changes were requested, and
   pulling in a new package to silence a library-emitted deprecation notice
   is outside "no overbuilding"). Confirmed no code in `app.py` or
   `test_api.py` beyond the brief's own import triggers it — it is intrinsic
   to using `TestClient` at all with the currently locked versions. Flagging
   as a known, unavoidable warning per the task's "note them if unavoidable"
   instruction rather than silently swallowing it.

## Self-review

- **Completeness vs brief:** all 7 routes implemented exactly as specified;
  status vocabulary strings (`awaiting_interview`, `processing`,
  `awaiting_review`, `approved`, `rejected`, `needs_attention`) are never
  hardcoded in `app.py` — they flow through unchanged from `CaseRunner`/
  `CaseStore`, so there's no place for the API layer to drift from the
  vocabulary. 404 for unknown pack (`POST /cases`) and unknown case (all
  case-scoped routes via `_case_or_404`) confirmed by
  `test_unknown_pack_and_case_404`. 409 semantics (decision before review;
  second interview-result while `awaiting_review`) confirmed by
  `test_decision_flow_and_conflicts`.
- **Pristine output:** full suite is 39/39 green with exactly one
  library-level deprecation warning, documented above as unavoidable given
  the brief's mandated import and the environment's pinned versions.
- **No overbuilding:** implementation is the brief's code verbatim except
  for the one sanctioned lazy-loading guard on the module-level `app`
  symbol; no extra endpoints, no extra validation, no speculative
  abstractions were added.
- **Sync/async boundary respected:** all graph work stays on `CaseRunner`'s
  synchronous API; the only `async def` is the WebSocket handler itself
  (a FastAPI/Starlette requirement), and it offloads the blocking
  `EventBus.wait` call to a thread via `asyncio.to_thread` rather than
  making any graph code async.

## Concerns

None blocking. The one open item is the intrinsic `StarletteDeprecationWarning`
documented above — it is a dependency-version artifact of using
`fastapi.testclient.TestClient` as the brief mandates, not a defect in the
implementation, and resolving it would require a dependency change outside
this task's scope.

---

## Fix (post-review): memoize the lazy module-level `app`

**Finding (Important, from task review):** the PEP 562 `__getattr__("app")`
in `src/voxgate/service/app.py` was not memoized. Each attribute access
called `create_app()` fresh, so two `getattr(module, "app")` calls (or two
imports treating `app` as a stable singleton) produced two independent
FastAPI apps each with its own `CaseRunner`/`CaseStore`/`EventBus`/graph set
and disjoint state. `uvicorn voxgate.service.app:app` only ever worked by
accident because uvicorn does a single `getattr`.

**What changed** — `src/voxgate/service/app.py`:
- Added a module-level `_app_instance: FastAPI | None = None` cache.
- `__getattr__` now checks `_app_instance`, builds it via `create_app()`
  only on the first `app` access, caches it, and returns the same cached
  object on every subsequent access:
  ```python
  _app_instance: FastAPI | None = None

  def __getattr__(name):
      global _app_instance
      if name == "app":
          if _app_instance is None:
              _app_instance = create_app()
          return _app_instance
      raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
  ```
  This restores the singleton semantics a bare `app = create_app()` implies,
  while keeping the import-time-side-effect-free behavior the brief's
  Implementer note sanctioned.

**Test added** — `tests/test_api.py::test_lazy_module_app_is_memoized_singleton`:
monkeypatches `voxgate.service.app.create_app` with a call-counting stub
(returning a sentinel object) and resets `_app_instance` to `None`, so the
test never triggers real pack loading/graph building. It then accesses
`app_module.app` twice and asserts `a1 is a2 is sentinel` and that
`create_app` was called exactly once — directly proving the memoization
without adding cost to the suite (packs stay unloaded for this test, kept
deliberately fast per the review's guidance).

**Covering-test run** (`uv run pytest tests/test_api.py -v`):
```
tests/test_api.py::test_packs_listing PASSED                             [ 16%]
tests/test_api.py::test_case_lifecycle_over_http PASSED                  [ 33%]
tests/test_api.py::test_decision_flow_and_conflicts PASSED               [ 50%]
tests/test_api.py::test_unknown_pack_and_case_404 PASSED                 [ 66%]
tests/test_api.py::test_ws_streams_history_then_live PASSED              [ 83%]
tests/test_api.py::test_lazy_module_app_is_memoized_singleton PASSED     [100%]
6 passed, 1 warning in 2.15s
```

**Full suite regression** (`uv run pytest -q`):
```
........................................                                 [100%]
40 passed, 1 warning in 2.36s
```
34 pre-existing tests + 6 in `test_api.py` (5 original + 1 new regression
test) = 40, all green. The one warning is the same pre-existing, unavoidable
`StarletteDeprecationWarning` documented above — unchanged by this fix.

The review's Minor finding (WS handler catching only `WebSocketDisconnect`)
is inherited verbatim from the brief's own Step-3 code and was left as-is
per the coordinator's instruction.
