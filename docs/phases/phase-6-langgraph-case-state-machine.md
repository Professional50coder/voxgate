# Phase 6 — LangGraph Case State Machine

**Status:** ✅ Built & review-approved

## 1. Purpose

Phase 6 is where VoxGate's core architectural claim — "interview as a paused graph node" (design spec §3) — becomes real. It builds the LangGraph `StateGraph` that drives one case from intake through interview, validation, parallel pack checks, scoring, routing, and either auto-approval or a human reviewer gate, using `interrupt()`/`Command(resume=...)` for both the voice interview and the reviewer decision — architecturally identical pause points. It consumes a loaded `Pack` (Phase 4) and the real `kyc-uae` pack's behavior (Phase 5) and produces the compiled graph that Phase 7's `CaseRunner` drives.

## 2. What was built

| File | Responsibility |
|---|---|
| `src/voxgate/graph/state.py` | `CaseState` — the `TypedDict` schema threading through every graph node |
| `src/voxgate/graph/build.py` | `MAX_REASKS`, `_node_name`, `_latest_checks`, `build_graph(pack, checkpointer) -> CompiledStateGraph` — the full node/edge topology |
| `tests/test_graph.py` | 8 tests: node-naming contract, the happy path, the reviewer-gate path, the re-ask loop (including its cap), request-info looping, checkpoint-resume-after-restart, and check-result deduplication |
| `packs/kyc_uae/checks.py` (touched, fix round) | `sanctions_screen.check_name`, `pep_screen.check_name`, `adverse_media.check_name` attributes added so graph node names match each check's actual `CheckResult.check_name` |

## 3. Public interfaces

```python
# src/voxgate/graph/state.py
class CaseState(TypedDict, total=False):
    case_id: str
    pack_id: str
    status: str
    fields: dict
    field_confidence: dict
    reask_count: int
    reask_fields: list[str]
    force_review: bool
    check_results: Annotated[list[dict], operator.add]   # add-reducer
    score: dict | None
    decision: dict | None

# src/voxgate/graph/build.py
MAX_REASKS = 2

def _node_name(check) -> str:
    return f"check_{getattr(check, 'check_name', check.__name__)}"

def _latest_checks(results: list[dict]) -> list[dict]:
    """Last-write-wins dedup by check_name, preserving append order for the winner."""
    ...

def build_graph(pack: Pack, checkpointer): ...   # -> CompiledStateGraph
```

Interrupt payload shapes (implemented exactly as specified):

- **interview** interrupt (`interview` node): `{"type": "interview", "reask_fields": [...], "reask_hints": {...}, "fields_so_far": {...}}`, resumed with `{"fields": {...}, "confidence": {...}}`.
- **reviewer_gate** interrupt (`reviewer_gate` node): `{"type": "review", "gate_role": ..., "score": {...}, "check_results": [...], "fields": {...}}`, resumed with `{"action": "approve"|"reject"|"request_info", "note": str}`.

Node names (verified against the real `kyc-uae` pack in `test_check_node_names_match_pack_check_names`): `intake`, `interview`, `extract_validate`, `check_sanctions`, `check_pep`, `check_adverse_media`, `force_gate`, `score`, `medium_reask`, `auto_approve`, `awaiting_review` (status-setter), `reviewer_gate`, `finalize`.

## 4. Key design decisions & why

- **`MAX_REASKS = 2` is a module constant in `build.py`**, matching the global constraint ("Re-ask loop is capped at 2"). `after_validate` routes to `force_gate` once `state["reask_count"] > MAX_REASKS`, forcing the case to the reviewer gate with a synthetic `band: "high"` score rather than looping the interview indefinitely.
- **Check node names are `check_<check_name>`, derived from an explicit `check_name` attribute on each check function, not `check_<function.__name__>`.** This was the first fix-round finding: the original implementation used `f"check_{c.__name__}"`, which produced `check_sanctions_screen`/`check_pep_screen`/`check_adverse_media` — mismatched against the `check_name` values (`"sanctions"`, `"pep"`, `"adverse_media"`) each check's own `CheckResult` actually carries. The fix adds a shared `_node_name(check)` helper (`f"check_{getattr(check, 'check_name', check.__name__)}"`, falling back to `__name__` for any check that doesn't opt in) used at all four call sites that need a check's node name (the `after_validate` fan-out list, `add_node` registration, the conditional-edge target list, and the `add_edge(..., "score")` loop), and `packs/kyc_uae/checks.py` now sets `sanctions_screen.check_name = "sanctions"` etc. right after each function definition. This is an explicit per-pack opt-in — the `Pack`/loader contract itself is unchanged.
- **`check_results: Annotated[list[dict], operator.add]` uses LangGraph's add-reducer, with "latest wins" deduplication done by `_latest_checks()` at read time, not the state schema.** Because parallel check nodes each append their own `CheckResult` to the same list (fan-out), and a re-ask loop causes checks to re-run and append *again*, the raw `check_results` list can contain stale entries from a prior interview attempt. `score()` calls `_latest_checks()` to collapse the list by `check_name` (last-write-wins) immediately before scoring, then itself returns `{"check_results": []}` — a deliberate no-op append under the reducer, relying entirely on `_latest_checks` for the actual dedup rather than trying to prune the list in place.
- **`route` is a conditional-edge function that returns node names directly** (`"awaiting_review"`, `"medium_reask"`, `"auto_approve"`), and `"awaiting_review"` is its own tiny status-setter node (`set_awaiting_review`) that runs *before* flowing into the `reviewer_gate` interrupt node — so `status == "awaiting_review"` is observable in state even while the graph is still executing, before the interrupt actually pauses execution. This ordering is what Phase 7's store/API rely on.
- **Thresholds are never hard-coded in the graph** — `route` reads `state["score"]["band"]`, computed by `pack.scorecard.score(...)` using the pack's own `low_threshold`/`high_threshold` (from `pack.yaml`), consistent with the same global constraint honored in Phase 3.
- **A `"medium"` band re-asks the single most-contributing field first** (`medium_reask`, using `pack.feature_field_hints` to map the top-contributing scorecard feature back to a schema field), up to the same `MAX_REASKS` cap, before falling back to `awaiting_review` — treating a middling risk score as potentially a data-quality problem worth one clarifying question rather than an automatic escalation.
- **`extract_validate` catches `pydantic.ValidationError` and turns it into `reask_fields`**, incrementing `reask_count`, rather than crashing the case — implausible/malformed voice-extracted data loops back to a targeted re-ask instead of failing the whole case.
- **`force_gate`** sets `force_review: True` and a synthetic `score` dict (`band: "high"`, no real contributions) — ensures a case that ran out of re-ask attempts always lands at the reviewer gate regardless of what its (incomplete/invalid) data would otherwise score.
- **Checkpointing is fully delegated to the `checkpointer` argument** (`build_graph(pack, checkpointer)`), not chosen inside `build.py` — Phase 7/8 decide `MemorySaver` vs. Postgres based on `Settings.database_url`, keeping the graph itself checkpointer-agnostic. `test_resume_after_restart_same_checkpointer` proves this: a *second* `build_graph` call sharing the same `MemorySaver` instance resumes exactly where the first left off.
- **Resume-payload trust boundary deliberately lives outside the graph.** A third review finding — malformed/missing keys in a `Command(resume=...)` payload could raise a bare `KeyError` deep inside a node — was raised and explicitly **parked**, not fixed. Ruling (per the ledger): Task 7's `CaseRunner` already wraps `.invoke()` in `try/except Exception` to produce the `needs_attention` status (design spec §6's node-crash handling), so adding resume-payload guards inside `build.py` as well would duplicate that trust boundary rather than strengthen it. The graph stays a thin, trusting state machine; input validation/crash containment is Phase 7's job.

## 5. Test evidence

From `task-6-report.md` (initial implementation) and its appended fix report — final: 8/8 in `test_graph.py`, 28/28 in the full suite, zero warnings under `-W error`:

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

```
uv run pytest -q
28 passed in 1.14s
```
(28 = 20 pre-existing from Tasks 1–5 + 8 from Task 6.) The report notes the full suite was also re-run with `-W error` — every warning class, including `DeprecationWarning`, promoted to a hard failure — and passed cleanly with zero warnings raised, against the installed `langgraph 1.2.10`.

- `test_check_node_names_match_pack_check_names` (added in the fix round) — builds the graph for the real `kyc-uae` pack and asserts `{"check_sanctions", "check_pep", "check_adverse_media"} <= set(graph.get_graph().nodes.keys())`, directly guarding the Finding 1 fix.
- `test_pauses_at_interview_then_clean_case_auto_approves` — the graph pauses at an `"interview"`-type interrupt on the first `invoke`; resuming with `CLEAN` fields drives the case to `status == "approved"`, `decision.by == "system"`, `score.band == "low"`.
- `test_risky_case_parks_at_reviewer_gate_and_approve_resumes` — resuming with `RISKY` fields parks the case at a `"review"`-type interrupt with `gate_role == "Compliance Officer"` and `status == "awaiting_review"`; resuming the gate with a `"reject"` decision sets `status == "rejected"` and carries the note through.
- `test_invalid_fields_trigger_reask_with_hints` — a payload with an implausible `dob` produces a second `"interview"` interrupt whose `reask_fields` includes `"dob"` with a non-empty hint; resuming with valid fields then reaches `"approved"`.
- `test_reask_cap_forces_reviewer_gate` — repeatedly resuming with the same invalid payload for `MAX_REASKS` iterations eventually flips the interrupt type from `"interview"` to `"review"` — the cap-exhausted escape to the gate.
- `test_request_info_from_gate_loops_back_to_interview` — a `"request_info"` decision at the reviewer gate produces a fresh `"interview"`-type interrupt rather than terminating the case.
- `test_resume_after_restart_same_checkpointer` — a second `build_graph` call sharing the same `MemorySaver` instance recovers `status == "awaiting_review"` with no further input, and can still be resumed to `"approved"`.
- `test_latest_check_results_win_after_reask` (rewritten in the fix round) — drives RISKY → `request_info` → CLEAN through the graph so `check_results` genuinely accumulates duplicate `check_name` entries (`len(per_check) > len(set(per_check))`), asserts the final `score.band == "low"` (proving the score reflects the LATEST/CLEAN results, not the earlier RISKY ones), and directly calls `_latest_checks()` to confirm exactly one entry per `check_name` survives dedup.

Re-verified as part of this documentation pass is not repeated here since the report's own `-W error` full-suite run already supersedes a plain re-run; the reported 28/28 count is taken as current.

## 6. Review history

Per the ledger (`.superpowers/sdd/2026-08-06-voxgate-core-platform/progress.md`):

> Task 6: fix round 1/5 (2 addressed, 0 open — check nodes renamed check_<check_name> via function attr; dedup test now drives request_info loop and asserts last-write-wins)
> Task 6: parked — resume-payload guards (KeyError on malformed resume) — ruling: human ruled Task 7 runner owns the trust boundary (its brief wraps .invoke in try/except → needs_attention); graph-level guards would duplicate it
> Task 6: minor (deferred): node-set test uses subset (<=) not exact match; test relies on graph.get_graph().nodes introspection API (langgraph version-fragility surface); medium_reask max() unguarded for empty contributions; stale check_results shown at force_gate after earlier check cycle
> Task 6: complete (no-git mode, review clean after fix round 1)

**Fix round 1/5 — both findings addressed, none left open:**
1. Check node names now derive from a `check_name` function attribute (`check_sanctions`/`check_pep`/`check_adverse_media`), not the Python function's `__name__` — see §4 above.
2. `test_latest_check_results_win_after_reask` was rewritten to actually exercise the dedup path: the original version submitted an invalid-dob payload first, which fails schema validation before any check node runs, so `check_results` never accumulated more than one entry per `check_name` and the dedup logic went untested despite the test's name. The rewrite drives RISKY → `request_info` → CLEAN specifically to force a genuine duplicate-then-dedup cycle.

**One parked finding, with an explicit ruling** (not a deferred minor — a deliberate architectural boundary decision): resume-payload guards against malformed/missing keys (which could otherwise raise a bare `KeyError` inside a node) are intentionally *not* added at the graph level. The human reviewer ruled that Task 7's `CaseRunner` already owns this trust boundary via its planned `try/except Exception` wrap around `.invoke()` (feeding the `needs_attention` status), so graph-level guards would be duplicative rather than complementary.

**Four deferred minors** (post-fix-round, review clean):
1. `test_check_node_names_match_pack_check_names` uses a subset check (`<=`) rather than asserting the exact node set — a stricter test would also assert no *unexpected* `check_*` nodes exist.
2. The test relies on `graph.get_graph().nodes` for introspection, an API surface that could shift across LangGraph versions (the report separately confirms `graph.builder.nodes` returns an equivalent set minus the `__start__`/`__end__` sentinels, as a fallback if needed).
3. `medium_reask`'s `max((c for c in state["score"]["contributions"]), key=lambda c: c["contribution"])` is unguarded against an empty `contributions` list — would raise `ValueError` if the scorecard ever produced zero contributions while still landing in the `"medium"` band.
4. After an earlier check cycle, `force_gate`'s emitted `check_results: []` combined with the add-reducer means a case that already had check results from a prior (now-superseded) interview attempt can still show those stale results at the point it's forced to the gate, rather than a clean/empty check history reflecting the state that actually triggered the force-gate path.

## 7. Dependencies

- **Consumes:** Phase 4 (`Pack`), Phase 5 (the real `kyc-uae` pack — its tests import `CLEAN`/`RISKY` fixtures directly from `tests.test_pack_kyc_uae`; its `checks.py` now also carries the `check_name` attributes this phase's node-naming depends on).
- **Feeds:** Phase 7 (`CaseRunner` builds one compiled graph per pack via `build_graph`, and owns the resume-payload trust boundary this phase deliberately left to it), Phase 9 (the Postgres durability integration test and demo script exercise the compiled graph indirectly through the runner/API).
