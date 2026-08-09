# Graph Wave 1 — Implementation Report

**Date:** 2026-08-06
**Scope:** proposals (a) audit trail, (b) per-node timing, (c) richer interview/review interrupt payloads, (e) per-check RetryPolicy(max_attempts=2). Proposals (d) and (f) deliberately NOT implemented.
**Spec:** `docs/design/2026-08-06-graph-upgrade-design.md`

## Files changed

- `src/voxgate/graph/state.py` — additive only: `audit: Annotated[list[dict], operator.add]`, `field_errors: dict[str, str]`.
- `src/voxgate/graph/build.py` — added `_summarize()`/`_audited()` helpers, optional `clock=` kwarg on `build_graph`, wrapped every `g.add_node(...)` call (including the dynamic `check_*` loop) with `_audited(...)`, extended `extract_validate`/`interview`/`reviewer_gate` payloads, added `RetryPolicy(max_attempts=2)` to the check-node registration loop.
- `tests/test_graph_wave1.py` — new file, 13 tests (only file touched under tests/; `tests/test_graph.py` untouched).

No other files touched (no `runner.py`, no `pyproject.toml`, no `packs/*`).

## Implementation summary

Followed the design doc's pseudocode closely:

- `_audited(name, fn, clock=None)` wraps a node function: computes `seq = len(state.get("audit", [])) + 1` from the state snapshot the node was invoked with (deterministic, no wall clock), brackets `fn(state)` with `time.perf_counter()` for `duration_ms`, and only adds a `"ts"` key when a `clock` callable is supplied (default `None` → no ts, matching every existing call site's signature untouched).
- Applied to all 11 node registrations, including the per-pack dynamic `check_*` loop, so `seq` is shared across the parallel check fan-out as the design specifies.
- `extract_validate` now captures `{field: pydantic_msg}` into `field_errors` on validation failure, in addition to the unchanged `reask_fields`/`reask_count` shape (`after_validate` routing logic untouched).
- `interview()` payload gains `field_errors`, `attempt`, `max_attempts`, `fields_validated` — all additive alongside the four existing keys.
- `reviewer_gate()` payload gains `score_waterfall` (contributions sorted by `abs(contribution)` desc), `flagged_checks` (non-`clear` checks), `reask_count`, `force_review` — all additive alongside the five existing keys.
- Check-node registration: `g.add_node(name, _audited(...), retry_policy=RetryPolicy(max_attempts=2))`, imported from `langgraph.types` (already a transitive dependency of the repo's langgraph install — no new dependency added).

## RED/GREEN evidence

**RED** — temporarily reverted `state.py`/`build.py` to their pre-Wave-1 content (verbatim ground truth from the task brief) and ran the new test file:
```
uv run pytest tests/test_graph_wave1.py -v
...
FAILED tests/test_graph_wave1.py::test_audit_trail_records_intake_through_approve
FAILED tests/test_graph_wave1.py::test_audit_parallel_checks_share_seq
FAILED tests/test_graph_wave1.py::test_audit_survives_resume_after_restart
FAILED tests/test_graph_wave1.py::test_audit_append_only_across_reask_loop
FAILED tests/test_graph_wave1.py::test_audit_entries_have_nonnegative_duration
FAILED tests/test_graph_wave1.py::test_audit_ts_present_only_when_clock_supplied
FAILED tests/test_graph_wave1.py::test_interview_payload_field_errors_and_attempt
FAILED tests/test_graph_wave1.py::test_interview_payload_reports_progress
FAILED tests/test_graph_wave1.py::test_review_payload_waterfall_sorted_by_magnitude
FAILED tests/test_graph_wave1.py::test_review_payload_flags_sanctions_hit
FAILED tests/test_graph_wave1.py::test_review_payload_carries_reask_and_force_review
FAILED tests/test_graph_wave1.py::test_transient_check_failure_recovers_via_retry
12 failed, 1 passed in 1.54s
```
(The one pass, `test_always_failing_check_still_reaches_terminal_failure`, is the pre-existing crash-propagates-immediately behavior — correctly passes with or without the retry policy, since it proves the *unchanged* trust boundary.)

Restored the implementation, re-ran — **GREEN**:
```
uv run pytest tests/test_graph_wave1.py -v
13 passed in 2.46s
```

### Required verification commands (all three, in order)

**1. `uv run pytest tests/test_graph_wave1.py -v`**
```
13 passed in 2.46s
```
All new tests pass: audit trail (4 tests), timing (2 tests), interview payload (2 tests), review payload (3 tests), retry policy (2 tests).

**2. `uv run pytest tests/test_graph.py -v`**
```
8 passed in 0.90s
```
All 8 ground-truth tests pass unchanged — compatibility contract intact.

**3. `uv run pytest tests/test_runner.py tests/test_api.py -q`**
```
12 passed, 1 warning in 2.32s
```
(6 runner tests + 6 API tests, per the task brief's count.) Service layers unaffected — no runner.py or api.py edits were made, and the interrupt-payload additions flow through `runner._sync`'s existing "store whole payload verbatim" behavior for free, exactly as the design doc claims. The one warning is a pre-existing `httpx`/`starlette.testclient` deprecation notice, unrelated to this change.

## Deviations from the design doc

1. **`RetryPolicy(max_attempts=2)` retry_on default excludes `RuntimeError`.** The design doc's pseudocode uses `RetryPolicy(max_attempts=2)` with no `retry_on=` override, and its test plan describes a "check closure that raises on its first call and succeeds on its second." I initially wrote that stub raising `RuntimeError` (mirroring `test_runner.py`'s `_boom` pattern) and it did **not** retry — LangGraph's `default_retry_on` explicitly excludes `RuntimeError`, `ValueError`, `TypeError`, `OSError`, etc. (treated as deterministic bugs) and only retries things like `ConnectionError` / HTTP 5xx by default. I changed the transient-failure test stub to raise `ConnectionError` instead, so it actually exercises the retry path, and added a comment explaining why. This is a clarification, not a scope change: `RetryPolicy(max_attempts=2)` is implemented exactly as specified, and the existing `_boom`/`RuntimeError`-based `test_node_crash_marks_needs_attention` in `test_runner.py` is unaffected either way (it never retries, by design, since a permanently-down provider raising `RuntimeError` is correctly treated as non-transient) — confirmed still green in verification step 3.
2. **`runner._sync` audit-key line not added.** The design doc (§a, task list step 1) calls for one line in `runner.py`: `"audit": v.get("audit", [])`, so the audit trail flows into the store/API. Per file-ownership rules (`service/*` is owned by another agent working concurrently), I did not touch `runner.py`. The `audit` field is fully present and correct on graph state (verified directly via `graph.get_state(cfg).values["audit"]` in all new tests, matching how `test_graph.py` itself tests state rather than the API layer) but is not yet surfaced through `CaseRunner`/`GET /cases`. This is a one-line, additive, zero-risk follow-up for whoever owns `runner.py` next — flagging it rather than crossing the ownership boundary.
3. Proposal (c)'s design pseudocode suggested extending `test_invalid_fields_trigger_reask_with_hints` in `tests/test_graph.py` directly; per instructions I left that file untouched and instead added equivalent new tests (`test_interview_payload_field_errors_and_attempt`, `test_interview_payload_reports_progress`) in `test_graph_wave1.py` covering the same assertions.

## Concerns

- None blocking. The `runner._sync` line noted above (deviation 2) is the only gap between "Wave 1 fully wired end-to-end" and "Wave 1 correct at the graph layer, pending a one-line pickup by the runner.py owner."
- `RetryPolicy`'s default `initial_interval=0.5s` / `jitter=True` means a genuinely-retried check adds real wall-clock delay (~0.5–1s) to any case that hits a transient failure — acceptable for Wave 1 (sync API, portfolio-scale demo) but worth knowing if retry-heavy test suites grow.

## Test count

Suite is now 40 (ground truth) + 13 (`test_graph_wave1.py`) = 53 tests total across the touched/verified files; all green in the three required commands above.

---

## Follow-up integration (coordinator handoff, same day)

Once the other agent finished with `src/voxgate/service/runner.py`, it became mine for one scoped integration: wire the audit trail through to the store/API, closing deviation #2 above.

### Change

`src/voxgate/service/runner.py`, `CaseRunner._sync`'s case dict — added the single design-doc line, nothing else touched (confirmed `recover_case` and everything else left byte-for-byte as handed off):

```python
case = {"case_id": case_id, "pack_id": pack_id,
        "status": v.get("status", "processing"),
        "fields": v.get("fields", {}),
        "score": v.get("score"), "decision": v.get("decision"),
        "check_results": v.get("check_results", []),
        "audit": v.get("audit", []),          # <-- added
        "interrupt": pending}
```

### New test

Added `test_runner_store_carries_audit_trail_after_clean_lifecycle` to `tests/test_graph_wave1.py` (not `test_runner.py`), using a local `runner` fixture that mirrors `test_runner.py`'s own fixture (`CaseRunner(load_packs(...), MemorySaver, CaseStore(), EventBus())`). It drives a case through `start_case` → `resume` with `CLEAN` fields to `approved`, then asserts:
- `done["audit"]` is a non-empty list,
- the visited-node set includes `intake`, `interview`, `extract_validate`, `score`, `auto_approve`,
- every entry has the full `{seq, node, status_before, status_after, summary, duration_ms}` shape with correct types,
- `runner.store.get(case_id)["audit"]` matches what `resume()` returned (store-level, not just return-value-level).

### Re-verification

```
uv run pytest tests/test_graph_wave1.py -v
14 passed in 1.95s
```
(13 previous + 1 new, all green.)

```
uv run pytest tests/test_runner.py tests/test_api.py tests/test_graph.py -q
20 passed, 1 warning in 2.55s
```
(6 runner + 6 api + 8 graph, all green; same pre-existing httpx/testclient deprecation warning as before, unrelated.)

### Status

Deviation #2 from the original report is now closed — Wave 1 (a, b, c, e) is fully wired end-to-end: graph → `CaseRunner._sync` → `CaseStore` → (by inheritance, since `_sync`'s dict is exactly what `GET /cases`/`GET /cases/{id}` serialize) the API. No remaining concerns.
