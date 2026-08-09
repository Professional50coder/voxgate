# Task 7 Report: CaseStore + EventBus + CaseRunner

## Summary

Implemented `CaseStore`, `EventBus`, and `CaseRunner` per the task-7 brief, following TDD strictly
(RED for the module-not-found stage, GREEN at 5 tests, RED again for the isolated needs_attention
test, GREEN at 6 tests). Full suite: 34/34 passing (28 pre-existing + 6 new), no warnings.

## Files changed

- Created `src/voxgate/service/store.py` — `CaseStore` (in-memory, thread-safe via `threading.Lock`)
- Created `src/voxgate/service/events.py` — `EventBus` (thread-safe via `threading.Condition`)
- Created `src/voxgate/service/runner.py` — `CaseRunner`
- Created `tests/test_runner.py` — 6 tests (5 from Step 1 + 1 from Step 5)

## TDD evidence

### RED (Step 2) — module missing

```
uv run pytest tests/test_runner.py -v
...
ModuleNotFoundError: No module named 'voxgate.service.store'
1 error in 0.74s
```
Matches the brief's expected failure mode exactly.

### GREEN (Step 4) — 5 PASS

Implemented `store.py`, `events.py`, and `runner.py` transcribed verbatim from the brief (Step 3
implementation, i.e. **without** the exception-wrapping — that's Step 5's job).

```
uv run pytest tests/test_runner.py -v
tests/test_runner.py::test_full_lifecycle_clean PASSED
tests/test_runner.py::test_gate_lifecycle_and_events PASSED
tests/test_runner.py::test_patch_fields_is_live_only PASSED
tests/test_runner.py::test_list_and_unknown_case PASSED
tests/test_runner.py::test_eventbus_wait_returns_new_events PASSED
5 passed in 2.20s
```

### RED (Step 5, part 1) — needs_attention test fails correctly

Appended `test_node_crash_marks_needs_attention` plus the `_boom` / `_crashing_graph_for` helpers.
Before the runner exception-wrapping change, the `RuntimeError("provider down")` propagated
uncaught out of `runner.resume()` — confirming the graph is not silently swallowing failures and
the runner really is the trust boundary described in the Task 6 review decision:

```
tests\test_runner.py:14: RuntimeError
RuntimeError: provider down
During task with name 'check__boom' and id '...'
1 failed in 0.92s
```

### GREEN (Step 5, part 2) — 6 PASS

Wrapped `.invoke()` calls in `start_case`/`resume` in `try/except Exception`, mapping any failure
to `status="needs_attention"`, `error=str(e)`, publishing a state event, and returning (no
re-raise). No changes made inside the graph itself.

```
uv run pytest tests/test_runner.py -v
tests/test_runner.py::test_full_lifecycle_clean PASSED
tests/test_runner.py::test_gate_lifecycle_and_events PASSED
tests/test_runner.py::test_patch_fields_is_live_only PASSED
tests/test_runner.py::test_list_and_unknown_case PASSED
tests/test_runner.py::test_eventbus_wait_returns_new_events PASSED
tests/test_runner.py::test_node_crash_marks_needs_attention PASSED
6 passed in 0.64s
```

### Full suite

```
uv run pytest -q
34 passed in 0.94s
```
(Also re-ran with `-W error::DeprecationWarning` — still 34 passed, confirming pristine output.)

## Deviations from the brief (recorded, not silent)

1. **`_crashing_graph_for` checkpointer wiring (genuine API-drift fix, test semantics preserved).**
   The brief's helper signature was `_crashing_graph_for(pack)`, building the crashing graph with a
   brand-new `MemorySaver()`. Debugged this against real LangGraph behavior: a fresh `MemorySaver`
   has no checkpoint history for the case's `thread_id`, so `Command(resume=payload)` against it
   does **not** raise — it silently replays from `START` (no prior state to resume), re-hits the
   `interview` interrupt, and never reaches the crashing check node. Confirmed via an isolated
   repro script: `Command(resume=...)` on a disconnected fresh checkpointer returns a normal
   `awaiting_interview` state instead of touching `check__boom`.

   Fix: changed the helper signature to `_crashing_graph_for(pack, checkpointer)` and pass in
   `runner.graphs["kyc-uae"].checkpointer` — the same shared `MemorySaver` instance the runner
   already built with, which holds the case's actual checkpoint state (compiled graphs expose
   `.checkpointer` as the exact instance passed to `build_graph`, confirmed via `is` check). This
   preserves the test's intent (a check that raises should crash the graph mid-resume) while fixing
   the disconnected-state bug in the literal transcription. No graph or runner production code was
   touched to make this pass — purely a test-file wiring fix, and the RED confirmed the crash
   propagates correctly before the runner change was applied.

2. **`_mark_needs_attention` helper (minor, non-semantic).** The brief describes the same
   upsert/publish/return sequence inline in both `start_case`'s and `resume`'s except blocks. I
   factored it into a private `_mark_needs_attention(case_id, pack_id, e)` method to avoid
   duplicating three identical lines twice. Behavior is byte-identical to what the brief specifies
   in each call site; this is a DRY simplification, not a logic change.

## Self-review

- **Completeness vs brief:** All required methods present with the exact signatures specified —
  `CaseStore.upsert/get/list`, `EventBus.publish/history/wait`, `CaseRunner.start_case/resume/
  patch_fields/_sync`. Status vocabulary strings match exactly (`awaiting_interview`, `processing`,
  `awaiting_review`, `approved`, `rejected`, `needs_attention`). Case dict keys match the brief's
  list (`case_id, pack_id, status, fields, live_fields, score, check_results, decision, interrupt,
  seq`) — `live_fields` is populated by `patch_fields`/`start_case`; `_sync` doesn't overwrite it
  since `CaseStore.upsert` merges into existing rather than replacing.
- **No guards added inside the graph** — per the Task 6 review ruling, the trust boundary is the
  runner only. `src/voxgate/graph/build.py` was not modified.
- **Pristine output:** no warnings under `-q` or `-W error::DeprecationWarning`; only threading
  import inside a test function body (as specified in the brief) — no lint issues introduced.
- **No overbuilding:** did not add retry/backoff (explicitly deferred to Plan 2 per the brief), did
  not add persistence beyond in-memory dicts, did not add validation beyond what tests require.

## Concerns

- The checkpointer-wiring fix (deviation #1) is worth a second pair of eyes in review, since it
  diverges from the literal brief text (`MemorySaver()` → `checkpointer` param). The deviation is
  minimal and the test's assertions/behavior are unchanged — only the plumbing to make the crash
  actually reach the check node was corrected.
- No other concerns; all 34 tests green, verbatim implementation otherwise.
