# Phase 7 — CaseStore + EventBus + CaseRunner

**Status:** ✅ Built & review-approved

## 1. Purpose

Phase 6 produces a compiled LangGraph state machine per pack, but something has to own instantiating it, exposing a case's current status without callers needing to know LangGraph's checkpoint API, and fanning out state changes to live listeners (the WebSocket dashboard, per design spec §3.3). Phase 7 builds that owning layer: an in-memory case index (`CaseStore`), a thread-safe pub/sub mechanism for live updates (`EventBus`), and the orchestrator that drives the graph and keeps both in sync (`CaseRunner`). It sits directly beneath Phase 8's FastAPI layer — the API is a thin HTTP/WS wrapper over `CaseRunner`.

Phase 7 also carries architectural weight assigned to it by Phase 6's review: the Task 6 ruling explicitly parked resume-payload guards out of the graph, on the basis that "Task 7 runner owns the trust boundary." This phase is where that boundary is actually implemented.

## 2. What was built

| File | Responsibility |
|---|---|
| `src/voxgate/service/store.py` | `CaseStore` — thread-safe in-memory case index |
| `src/voxgate/service/events.py` | `EventBus` — thread-safe pub/sub with blocking `wait()` |
| `src/voxgate/service/runner.py` | `CaseRunner` — owns compiled graphs, drives `start_case`/`resume`/`patch_fields`, syncs store + bus, contains node-crash exceptions |
| `tests/test_runner.py` | 6 tests: full clean lifecycle, gate lifecycle + event count, live-only field patching, list-ordering + unknown-case error, blocking event wait, node-crash → `needs_attention` |

## 3. Public interfaces

```python
# src/voxgate/service/store.py
class CaseStore:
    def __init__(self): ...                                        # threading.Lock-backed
    def upsert(self, case: dict): ...                               # merges into existing, assigns seq on first insert
    def get(self, case_id): ...                                     # -> dict | None
    def list(self, pack_id=None): ...                                # -> list[dict], newest first by seq

# src/voxgate/service/events.py
class EventBus:
    def __init__(self): ...                                        # threading.Condition-backed
    def publish(self, case_id, event): ...
    def history(self, case_id): ...                                 # -> list[dict]
    def wait(self, case_id, after_index, timeout): ...               # blocking; -> list[dict], [] on timeout

# src/voxgate/service/runner.py
class CaseRunner:
    def __init__(self, packs, checkpointer_factory, store, bus):
        # checkpointer_factory() called exactly once; one compiled graph per pack, all sharing it
        ...
    def _cfg(self, case_id): ...                                     # {"configurable": {"thread_id": case_id}}
    def _sync(self, case_id, pack_id): ...                            # StateSnapshot -> store dict, publishes {"kind": "state"}
    def _mark_needs_attention(self, case_id, pack_id, e): ...         # DRY helper, upserts status="needs_attention", error=str(e)
    def start_case(self, pack_id): ...                                # -> dict
    def _pack_of(self, case_id): ...                                  # raises KeyError on unknown case_id
    def resume(self, case_id, payload): ...                           # -> dict; raises KeyError on unknown case
    def patch_fields(self, case_id, fields, confidence): ...          # -> dict, live_fields only
```

Case dict keys (verified against `_sync`/`_mark_needs_attention`/`patch_fields`): `case_id, pack_id, status, fields, live_fields, score, check_results, decision, interrupt, seq`, plus `error` when `status == "needs_attention"`.

## 4. Key design decisions & why

- **`CaseStore` and `EventBus` are both `threading`-primitive-backed (`threading.Lock` / `threading.Condition`), not asyncio-native.** Matches the global constraint that the sync LangGraph API (`.invoke`/`.get_state`) is used everywhere — the whole service layer stays synchronous internally; Phase 8's FastAPI async WebSocket handler bridges in via `asyncio.to_thread` around the blocking `EventBus.wait()`, keeping the threading/asyncio boundary at the API edge rather than smearing it through the store/runner.
- **`EventBus.wait(case_id, after_index, timeout)` is index-based, not timestamp-based**, and returns `[]` on timeout rather than raising — `self._cond.wait_for(lambda: len(self._events.get(case_id, [])) > after_index, timeout=timeout)` then slices `[after_index:]`. A WebSocket handler polls in a loop advancing its own cursor, so a plain "how many events have I already seen" index is sufficient and avoids clock-skew/ordering ambiguity that timestamps would introduce.
- **`patch_fields` writes only to `live_fields`, never touches the graph.** `live = {**case.get("live_fields", {}), **fields}` then upserts just `live_fields` — the graph's authoritative `fields` state is only ever updated via `resume`'s `Command(resume=payload)`. This is the mechanism behind the design spec's "PATCH field updates (live)" during an in-progress voice interview: the bot streams partial/low-confidence field extractions to the dashboard in real time without those partial values ever reaching the case's real state. `test_patch_fields_is_live_only` asserts `status` stays `"awaiting_interview"` after a patch.
- **One compiled graph per pack, built once at `CaseRunner.__init__` time, all sharing a single checkpointer instance** — `checkpointer = checkpointer_factory()` is called exactly once, then `self.graphs = {pid: build_graph(p, checkpointer) for pid, p in packs.items()}`. Every pack's cases persist to the same checkpoint store (in-memory `MemorySaver` in tests, Postgres in production per Phase 1's `Settings.database_url`); one `thread_id` per case, keyed by `case_id`, is enough to disambiguate across packs since case IDs are UUIDs.
- **`_sync(case_id, pack_id)` is the single translation point between LangGraph's `StateSnapshot` and the store's plain-dict case shape.** It reads `graph.get_state(cfg).values` plus any pending interrupt off `snap.tasks[*].interrupts` (looping over tasks and taking the last one with interrupts — in practice there is at most one), upserts into `CaseStore`, and publishes `{"kind": "state", "case": ...}` to `EventBus`. Both `start_case` and `resume` end by calling `_sync` on success, so the store and the graph's checkpointed state can never drift while the runner is the only writer.
- **`resume(case_id, payload)` raises a bare `KeyError` on an unknown case_id**, via `_pack_of`, which looks the case up in the store and raises if `None`. Phase 8 translates this into an HTTP 404 — keeping the runner's error vocabulary framework-agnostic (`KeyError`, not an HTTP-flavored exception) so it isn't coupled to FastAPI.
- **Node-crash resilience (`needs_attention`) is an explicit `try/except Exception` wrap around `.invoke()` in both `start_case` and `resume`, not left to propagate.** Per the design spec §6 ("Grok/API failure in graph nodes: retry ×3 with backoff → `needs_attention` state; never a silently lost case") — Phase 7 lays the groundwork (single-attempt catch, no retry, since Plan 1 has no flaky/LLM-touching nodes) via the shared `_mark_needs_attention(case_id, pack_id, e)` helper: upserts `status: "needs_attention"` with `error: str(e)`, publishes a state event, and returns the store dict rather than re-raising. **This is the concrete implementation of the trust boundary Task 6's review assigned here**: no guards were added inside `src/voxgate/graph/build.py`; a check node raising `RuntimeError` propagates all the way up through `graph.invoke()` and is caught only at this layer.
- **`_mark_needs_attention` is a DRY refactor over the brief's literal code** (approved deviation, see §6) — the brief describes the same upsert/publish/return sequence inline in both `start_case`'s and `resume`'s except blocks; factoring it into one private method avoids duplicating three identical lines twice, with byte-identical behavior at each call site.

## 5. Test evidence

From `task-7-report.md` — 6/6 in `test_runner.py`, 34/34 in the full suite, no warnings (also re-verified under `-W error::DeprecationWarning`):

```
tests/test_runner.py::test_full_lifecycle_clean PASSED
tests/test_runner.py::test_gate_lifecycle_and_events PASSED
tests/test_runner.py::test_patch_fields_is_live_only PASSED
tests/test_runner.py::test_list_and_unknown_case PASSED
tests/test_runner.py::test_eventbus_wait_returns_new_events PASSED
tests/test_runner.py::test_node_crash_marks_needs_attention PASSED
6 passed in 0.64s
```

```
uv run pytest -q
34 passed in 0.94s
```
(34 = 28 pre-existing from Tasks 1–6 + 6 new from Task 7.)

- `test_full_lifecycle_clean` — `start_case("kyc-uae")` returns `status == "awaiting_interview"` with an `"interview"`-type interrupt; resuming with `CLEAN` fields yields `status == "approved"`, `interrupt is None`, `score.band == "low"`.
- `test_gate_lifecycle_and_events` — resuming with `RISKY` fields parks the case at `status == "awaiting_review"` with a `"review"`-type interrupt; an `"approve"` decision resolves to `status == "approved"`; the event bus history for the case shows at least 3 `"state"`-kind events across the lifecycle.
- `test_patch_fields_is_live_only` — `patch_fields` sets `live_fields == {"full_name": "Pri"}` while `status` remains `"awaiting_interview"` (graph untouched), and the last published event is `{"kind": "fields", ...}`.
- `test_list_and_unknown_case` — two cases started in sequence list newest-first by `seq`; `resume("nope", {})` raises `KeyError`.
- `test_eventbus_wait_returns_new_events` — a background thread blocked in `bus.wait(case_id, after_index=n, timeout=5.0)` unblocks and returns the new `{"kind": "fields"}` event once `patch_fields` publishes it from the main thread — proves `EventBus`'s condition-variable wakeup actually works across threads, not just in-thread.
- `test_node_crash_marks_needs_attention` — swaps in a graph built from `dataclasses.replace(pack, checks=[_boom])` (a check that raises `RuntimeError("provider down")`), resumes a case into it, and asserts the runner returns `status == "needs_attention"` with an `"error"` key rather than raising — the crash-containment proof.

## 6. Review history

Per the ledger (`.superpowers/sdd/2026-08-06-voxgate-core-platform/progress.md`):

> Task 7: parked — pre-invoke case skeleton omits fields/score/check_results/decision/interrupt keys (plan-mandated, brief's own Step-3 code) — ruling: window is synchronous+sub-ms today, unexercisable; revisit in Plan 2 when nodes gain real latency
> Task 7: minor (deferred): store get()/list() return direct dict references not copies; start_case catches unknown pack_id into a phantom needs_attention case instead of erroring
> Task 7: complete (no-git mode, review clean; deviations approved — shared checkpointer in crash test [verified: fresh MemorySaver silently replays], _mark_needs_attention DRY helper)

**One parked finding, plan-mandated (not a bug to fix here):** `start_case`'s pre-invoke store write (`self.store.upsert({"case_id": ..., "pack_id": ..., "status": "awaiting_interview", "live_fields": {}})`, written before `graph.invoke(...)` runs) creates a case-dict skeleton missing the `fields`, `score`, `check_results`, `decision`, and `interrupt` keys that `_sync` would otherwise populate. This is literally the brief's own Step-3 code, not an oversight introduced during implementation. Ruling: because `graph.invoke()` in Plan 1 runs synchronously and completes in sub-millisecond time (no LLM/network calls in this ledger's nodes), the window where a caller could observe this incomplete skeleton is effectively unexercisable today — a `GET /cases/{id}` between the pre-invoke upsert and the post-invoke `_sync` essentially cannot happen in practice. Explicitly deferred to Plan 2, "when nodes gain real latency" (i.e., once LLM-touching nodes exist and that window becomes observable).

**Two deferred minors:**
1. `CaseStore.get()`/`.list()` return the actual dict objects held in `self._cases`, not copies — a caller mutating a returned case dict in place would corrupt the store's internal state without going through `upsert`. No test currently exercises this.
2. `start_case` on an unknown `pack_id` isn't guarded — since `pack_id not in self.packs`/`self.graphs` isn't checked before use, an unknown pack_id passed to `start_case` would raise inside the runner's own `.invoke()` call (a `KeyError` on `self.graphs[pack_id]`), which the existing `try/except Exception` around `.invoke()` catches and converts into a real, stored `needs_attention` case — i.e., a phantom case record for a pack that was never valid, rather than a clean upfront error before any case is created. (Phase 8's `create_app` currently guards this at the HTTP layer by checking `body.pack_id not in runner.packs` before calling `start_case` — but the runner itself doesn't enforce it, so any other caller of `CaseRunner.start_case` directly would hit this.)

**Two approved deviations from the brief's literal code, both reviewed and accepted:**
1. **Shared checkpointer in `test_node_crash_marks_needs_attention`'s helper**, instead of the brief's literal `_crashing_graph_for(pack)` signature building a fresh `MemorySaver()`. Debugging against real LangGraph behavior showed a brand-new `MemorySaver` has no checkpoint history for the case's `thread_id`, so `Command(resume=payload)` against it does not raise — it silently replays from `START` and never reaches the crashing check node, since there's no prior state to actually resume into. The test helper was changed to `_crashing_graph_for(pack, checkpointer)`, passed the runner's own existing `MemorySaver` instance (`runner.graphs["kyc-uae"].checkpointer`) so the crashing graph shares the case's real checkpoint state. This was empirically verified via an isolated repro (a fresh, disconnected checkpointer's resume returns a normal `awaiting_interview` state instead of touching the crashing node) before the fix was accepted — no graph or runner production code was touched to make the test pass, purely a test-file wiring correction, and the RED state (uncaught `RuntimeError` propagating out of `runner.resume()`) was confirmed before the runner's exception-wrapping was even added, proving the crash was real and the graph wasn't silently swallowing it.
2. **`_mark_needs_attention` DRY helper**, replacing the brief's inline duplicated upsert/publish/return sequence in both `start_case`'s and `resume`'s except blocks — a non-semantic simplification, behavior-identical at each call site.

## 7. Dependencies

- **Consumes:** Phase 6 (`build_graph`, the compiled graph, and the resume-payload trust boundary this phase implements per Task 6's ruling), Phase 4 (`load_packs`, `Pack`).
- **Feeds:** Phase 8 (FastAPI routes are thin wrappers over `CaseRunner`'s methods plus `CaseStore.list`/`.get`; Phase 8's `create_app` also compensates for this phase's deferred unknown-`pack_id` minor by checking `body.pack_id not in runner.packs` before calling `start_case`), Phase 9 (`CaseRunner.recover_case`, planned for Phase 9, extends this class for post-restart recovery).
