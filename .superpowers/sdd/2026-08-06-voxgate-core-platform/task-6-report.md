# Task 6 Report: LangGraph case state machine

## What I implemented

- `src/voxgate/graph/state.py` — `CaseState(TypedDict, total=False)` with fields `case_id`, `pack_id`, `status`, `fields`, `field_confidence`, `reask_count`, `reask_fields`, `force_review`, `check_results` (Annotated with `operator.add` reducer), `score`, `decision`. Transcribed verbatim from the brief's Step 3.
- `src/voxgate/graph/build.py` — `MAX_REASKS = 2` and `build_graph(pack, checkpointer) -> CompiledStateGraph`, implementing the full case workflow: `intake` → `interview` (interrupt) → `extract_validate` → parallel `check_<name>` fan-out → `score` → `route` (auto_approve / medium_reask / awaiting_review) → `reviewer_gate` (interrupt) → `finalize`, with reask-cap escape to `force_gate` and request_info loop-back to `interview`. Transcribed verbatim from the brief's Step 4.
- `tests/test_graph.py` already existed in the repo with content identical to the brief's Step 1 — verified it matched exactly, character for character, no edits needed.

## TDD evidence

**RED** — `uv run pytest tests/test_graph.py -v`:
```
ERROR collecting tests/test_graph.py
tests\test_graph.py:7: in <module>
    from voxgate.graph.build import build_graph, MAX_REASKS
E   ModuleNotFoundError: No module named 'voxgate.graph.build'
1 error in 0.89s
```
Matches the brief's expected failure exactly.

**GREEN** — `uv run pytest tests/test_graph.py -v`:
```
tests/test_graph.py::test_pauses_at_interview_then_clean_case_auto_approves PASSED
tests/test_graph.py::test_risky_case_parks_at_reviewer_gate_and_approve_resumes PASSED
tests/test_graph.py::test_invalid_fields_trigger_reask_with_hints PASSED
tests/test_graph.py::test_reask_cap_forces_reviewer_gate PASSED
tests/test_graph.py::test_request_info_from_gate_loops_back_to_interview PASSED
tests/test_graph.py::test_resume_after_restart_same_checkpointer PASSED
tests/test_graph.py::test_latest_check_results_win_after_reask PASSED
7 passed in 1.52s
```

**Full suite** — `uv run pytest -q`:
```
...........................
27 passed in 0.97s
```
27 = 20 pre-existing (Tasks 1-5) + 7 new (Task 6). All stayed green.

**Warnings check** — ran both the new test file and the full suite with `-W error` (promotes all warnings, including DeprecationWarning, to errors): both passed cleanly with zero warnings raised. LangGraph 1.2.10 (the installed version — no version drift/pin issues encountered) emits nothing under the brief's usage pattern.

## Files changed

- Created: `src/voxgate/graph/state.py`
- Created: `src/voxgate/graph/build.py`
- No changes needed to `tests/test_graph.py` (pre-existed, already brief-exact) or `src/voxgate/graph/__init__.py` (pre-existing empty file, sufficient as package marker).

## Deviations

None. The brief's code ran as-is against the installed langgraph 1.2.10 — no API incompatibilities encountered, no fixes needed to routing/status-ordering logic, no test weakening.

## Self-review

- **Completeness vs brief**: state.py and build.py are byte-for-byte transcriptions of the brief's Step 3/Step 4 code blocks. Verified node names (`intake`, `interview`, `extract_validate`, `check_sanctions_screen`, `check_pep_screen`, `check_adverse_media`, `score`, `route` via conditional edges, `auto_approve`, `reviewer_gate`, `finalize`, plus helper nodes `force_gate`, `medium_reask`, `awaiting_review`) all wire up correctly against the real kyc_uae pack (3 checks: `sanctions_screen`, `pep_screen`, `adverse_media`; `gate_role = "Compliance Officer"`).
- **Clean code**: no dead code, no extra abstractions beyond the brief. Did not add docstrings/comments/refactors beyond what the brief specified — task explicitly calls for verbatim transcription.
- **No overbuilding**: nothing added beyond the two files and confirming the pre-existing test file matched.
- **Pristine test output**: confirmed via `-W error` runs on both the new suite and the full suite — zero warnings, not just zero failures.

## Concerns

None. Implementation is a direct, unmodified transcription of the brief and all tests pass without any weakening, workarounds, or version-compatibility shims.

---

## Fix report (post-review)

Review returned two Important findings (a third — resume-payload guards — was parked by the human; Task 7's runner owns that boundary, and per instruction nothing was added for it here).

### Finding 1: check node names must be `check_<check_name>`, not `check_<function __name__>`

**Root cause**: `build.py` derived node names as `f"check_{c.__name__}"`, so kyc_uae's checks registered as `check_sanctions_screen`, `check_pep_screen`, `check_adverse_media` — mismatched against the reported `check_name` values (`sanctions`, `pep`, `adverse_media`) each `CheckResult` actually carries.

**Fix**:
- `packs/kyc_uae/checks.py`: added one-line attribute assignments right after each check function definition — `sanctions_screen.check_name = "sanctions"`, `pep_screen.check_name = "pep"`, `adverse_media.check_name = "adverse_media"`. This is an explicit per-pack opt-in; the `Pack`/loader contract is unchanged.
- `src/voxgate/graph/build.py`: added a shared helper `_node_name(check) -> f"check_{getattr(check, 'check_name', check.__name__)}"` (falls back to `__name__` for any check that doesn't opt in) and replaced all four `f"check_{c.__name__}"` call sites (the `after_validate` fan-out list, `add_node` registration loop, the conditional-edge target list, and the `add_edge(..., "score")` loop) with calls to `_node_name(c)`.
- `tests/test_graph.py`: added `test_check_node_names_match_pack_check_names`, which builds the graph for the real kyc_uae pack and asserts `{"check_sanctions", "check_pep", "check_adverse_media"} <= set(graph.get_graph().nodes.keys())`. Confirmed `graph.get_graph().nodes` is the correct, clean introspection point on langgraph 1.2.10 (verified interactively — it returns the compiled graph's node names including `__start__`/`__end__`; `graph.builder.nodes` also works and returns the same set minus the start/end sentinels).

### Finding 2: `test_latest_check_results_win_after_reask` never exercised the dedup path

**Root cause**: the original test submitted an invalid-dob payload first (which fails schema validation before any check node runs), so `check_results` only ever accumulated one entry per check_name — the `_latest_checks` last-write-wins behavior was never actually triggered, and the `per_check` variable it computed was unused (no duplicate-count assertion).

**Fix**: rewrote the test body (same test name, kept) to use the reliable duplicate-producing path this graph provides: submit RISKY (runs checks once, parks at reviewer gate) → resume `{"action": "request_info", ...}` (loops back to interview without touching `check_results`) → resume with CLEAN fields (re-validates and re-runs all three checks, appending a second result per check_name via the `operator.add` reducer). Added:
- `assert len(per_check) > len(set(per_check))` — proves raw `check_results` genuinely contains duplicates.
- `assert s["score"]["band"] == "low"` — proves the score reflects the LATEST (CLEAN) results, not the RISKY ones from the first run (last-write-wins).
- `deduped = _latest_checks(s["check_results"])` plus `assert sorted(c["check_name"] for c in deduped) == sorted(set(per_check))` — directly exercises `_latest_checks` and confirms exactly one entry per check_name survives dedup.
- Imported `_latest_checks` from `voxgate.graph.build` and `RISKY` (already imported) in `tests/test_graph.py`.

### Covering test runs

`uv run pytest tests/test_graph.py -v`:
```
tests/test_graph.py::test_check_node_names_match_pack_check_names PASSED
tests/test_graph.py::test_pauses_at_interview_then_clean_case_auto_approves PASSED
tests/test_graph.py::test_risky_case_parks_at_reviewer_gate_and_approve_resumes PASSED
tests/test_graph.py::test_invalid_fields_trigger_reask_with_hints PASSED
tests/test_graph.py::test_reask_cap_forces_reviewer_gate PASSED
tests/test_graph.py::test_request_info_from_gate_loops_back_to_interview PASSED
tests/test_graph.py::test_resume_after_restart_same_checkpointer PASSED
tests/test_graph.py::test_latest_check_results_win_after_reask PASSED
8 passed in 1.54s
```

`uv run pytest -q` (full suite):
```
............................
28 passed in 1.14s
```
28 = 27 previous + 1 new (`test_check_node_names_match_pack_check_names`). Re-ran full suite with `-W error` as well — 28 passed, zero warnings.

Also grepped the repo for any other coupling to the old `check_<function __name__>` convention (`pack_conformance.py`, service layer, other packs) — found none; only `build.py`'s new `_node_name` helper and the three new `checks.py` attribute assignments reference `check_name`.

### Files changed (this fix pass)

- `packs/kyc_uae/checks.py` — added `check_name` attributes on the three check functions.
- `src/voxgate/graph/build.py` — added `_node_name` helper; replaced 4 call sites.
- `tests/test_graph.py` — added `test_check_node_names_match_pack_check_names`; rewrote `test_latest_check_results_win_after_reask`; added `_latest_checks` to the import line.

No changes made regarding resume-payload guards, per the human's parked ruling — that boundary stays with Task 7's runner.
