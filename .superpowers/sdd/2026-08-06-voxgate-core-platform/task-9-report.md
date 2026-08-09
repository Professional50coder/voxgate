# Task 9 report — Postgres durability integration test + demo script + docs

**Date:** 2026-08-06

## Implementation

1. **`tests/integration/test_postgres_resume.py`** (new) — written verbatim per brief Step 1: skips unless `VOXGATE_TEST_DB` is set; starts a runner, drives a `kyc-uae` case to `awaiting_review` with `RISKY` fields, builds a brand-new `CaseRunner` (simulating a process restart, in-memory `CaseStore` empty), calls `recover_case` to rehydrate from the Postgres checkpointer, asserts the recovered state, then resumes with `approve` and asserts `approved`.

2. **`src/voxgate/service/runner.py`** — added `CaseRunner.recover_case(case_id, pack_id)` exactly per brief Step 2 (upserts a bare store skeleton, then calls the existing `_sync` to rehydrate from the graph/checkpointer). Added the `list_known_threads` note as a docstring on `recover_case` explaining that a full store rebuild on boot is a Plan 3 (dashboard) concern; `recover_case` is the explicit per-case recovery path, and this integration test is its consumer. No other part of `runner.py` was touched.

3. **`scripts/demo_case.py`** (new, ~85 lines) — httpx CLI against a running server (`BASE = "http://127.0.0.1:8000"`). No args = `CLEAN` applicant; `--risky` = sanctions-lookalike `RISKY` applicant (both dicts inlined, mirroring `tests/test_pack_kyc_uae.py`, so the script has no cross-package import fragility when run as `python scripts/demo_case.py`). Creates a case, prints the interview interrupt payload, submits the scripted fields, prints check results and a score waterfall (feature, value, weight, signed contribution, `#`-bar per 0.1 of `|contribution|`), and — if the case parks at `awaiting_review` — prompts `approve/reject/request_info` on stdin, submits the decision, and (if `request_info` reopens the interview) resubmits the same fields. Every status transition is printed with the case id, e.g. `[<uuid>] status=awaiting_review`.

4. **`README.md`** — appended two short sections at the end (nothing else rewritten, per the docs-light instruction):
   - **"Pack authoring"** (~12 lines): the module contract from the loader — `pack.yaml` keys, `schema.py`'s `Schema` + `REASK_HINTS`, `checks.py`'s `CHECKS` returning `CheckResult`, `scoring.py`'s `build_scorecard` + `FEATURE_FIELD_HINTS`.
   - **"Roadmap"** (4-plan stub): Plan 1 (this repo, complete) / Plan 2 (voice bot) / Plan 3 (dashboard + `CaseStore` rebuild-on-boot) / Plan 4 (hardening + v2 packs).

5. **`.paul/STATE.md`** — one line: Task 9's row in the status table changed from "⏸ Not started" to "✅ Complete", with a short summary of the verified evidence (integration test result, demo verification, suite counts).

`.paul/PROJECT.md` was left untouched (already current, no Task 9 content required there beyond what's already in its phase table).

## Test evidence

**Integration test — skip path** (no `VOXGATE_TEST_DB`):
```
uv run pytest tests/integration -v
tests/integration/test_postgres_resume.py::test_case_survives_process_restart SKIPPED [100%]
1 skipped in 0.61s
```

**Integration test — real Postgres run:**
- `docker --version` → 29.6.2; `docker compose version` → v5.3.1 (both available).
- `docker compose up -d` pulled `postgres:16-alpine` and started `voxgate-postgres-1` on port 5433 successfully.
- `pg_isready -U voxgate -d voxgate` → ready on first poll.
- With `VOXGATE_TEST_DB=postgresql://voxgate:voxgate@localhost:5433/voxgate`:
```
uv run pytest tests/integration -v
tests/integration/test_postgres_resume.py::test_case_survives_process_restart PASSED [100%]
1 passed in 10.87s
```
  This is a genuine restart proof: `r1` parks a RISKY case at `awaiting_review` against real Postgres, `r2` is a fresh `CaseRunner` (fresh in-memory `CaseStore`, same DSN) that has never seen the case, `recover_case` rehydrates it correctly (`status=awaiting_review`, `interrupt.type=review`), and `resume(...approve...)` lands `approved` — durable across a simulated process boundary.
- `docker compose down` — container/network/volume torn down cleanly afterward.

**Demo script — end-to-end manual verification:**
- Started `uv run uvicorn voxgate.service.app:app --port 8000` in the background; confirmed `GET /packs` responded before proceeding.
- Clean case (`uv run python scripts/demo_case.py`, no stdin needed):
```
[6b409970-2234-4670-a202-8b1febe8214b] status=awaiting_interview
interview interrupt payload:
  reask_fields=[]  fields_so_far={}
[6b409970-2234-4670-a202-8b1febe8214b] submitting interview fields (CLEAN)
[6b409970-2234-4670-a202-8b1febe8214b] status=approved
check results:
  check=adverse_media  status=clear   score=0.000
  check=pep            status=clear   score=0.395
  check=sanctions      status=clear   score=0.481
score waterfall:
  probability=0.2774  band=low
  sanctions_similarity     value=0.4806  weight=3.0   contribution=+1.4418 ##############
  pep_similarity           value=0.3948  weight=1.8   contribution=+0.7106 #######
  product_risk             value=0.3     weight=0.8   contribution=+0.2400 ##
  source_of_funds_risk     value=0.1     weight=1.5   contribution=+0.1500 #
  fatf_nationality_risk    value=0.0     weight=2.2   contribution=+0.0000
  adverse_media            value=0.0     weight=1.0   contribution=+0.0000
  non_resident             value=0.0     weight=0.6   contribution=+0.0000
[6b409970-2234-4670-a202-8b1febe8214b] final status: approved
```
  Auto-approved with no stdin prompt, as expected for a `low`-band case.

- Risky case (`echo`-piped `approve` decision, `uv run python scripts/demo_case.py --risky`):
```
[b4508c19-59ae-4917-8e34-b9710331d525] status=awaiting_interview
interview interrupt payload:
  reask_fields=[]  fields_so_far={}
[b4508c19-59ae-4917-8e34-b9710331d525] submitting interview fields (RISKY)
[b4508c19-59ae-4917-8e34-b9710331d525] status=awaiting_review
check results:
  check=adverse_media  status=clear   score=0.000
  check=pep            status=clear   score=0.561
  check=sanctions      status=hit     score=1.000
score waterfall:
  probability=0.9928  band=high
  sanctions_similarity     value=1.0     weight=3.0   contribution=+3.0000 ##############################
  fatf_nationality_risk    value=1.0     weight=2.2   contribution=+2.2000 ######################
  source_of_funds_risk     value=0.7     weight=1.5   contribution=+1.0500 ##########
  pep_similarity           value=0.5609  weight=1.8   contribution=+1.0096 ##########
  non_resident              value=1.0     weight=0.6   contribution=+0.6000 ######
  product_risk             value=0.7     weight=0.8   contribution=+0.5600 ######
  adverse_media            value=0.0     weight=1.0   contribution=+0.0000
[b4508c19-59ae-4917-8e34-b9710331d525] parked for human review - gate_role=Compliance Officer
decision (approve/reject/request_info): note (optional): [b4508c19-59ae-4917-8e34-b9710331d525] status=approved
[b4508c19-59ae-4917-8e34-b9710331d525] final status: approved
```
  Parked at `awaiting_review` with `sanctions_similarity` dominating the waterfall (largest bar count, 30 `#`), matching the brief's Step 5 expectation. A second run piping `reject` was also verified and correctly finished `rejected`.
- Killed the server afterward (`taskkill` on the PID bound to port 8000, verified `curl` to `/packs` then failed to connect).

## Regression

- `uv run pytest -q` (no `VOXGATE_TEST_DB`, after Postgres torn down): **40 passed, 1 skipped, 1 warning** — the pre-existing `StarletteDeprecationWarning` only. All Task 1–8 tests plus the two new Task 9 tests (`recover_case`'s consumer, skipped; the suite count matches "39 + Task 9's new test(s), possibly +1 from Task 8's concurrent fix").
- `uv run pytest -q` with `VOXGATE_TEST_DB` set and Postgres up: **41 passed, 1 warning** — the integration test ran for real and passed as part of the full suite, not just in isolation.

## Deviations from the brief

- **Demo script inlines `CLEAN`/`RISKY`** instead of importing from `tests.test_pack_kyc_uae`. When invoked as `python scripts/demo_case.py`, the script's own directory (not the repo root) lands on `sys.path[0]`, so `tests.*` imports are not reliably resolvable outside `pytest`'s `pythonpath = ["."]` config. Inlining keeps the demo self-contained and independent of test-suite plumbing — appropriate for a standalone CLI meant to be screen-recorded.
- **Em dash removed** from one demo print statement (`"parked for human review - gate_role=..."` uses a plain hyphen, not `—`) after observing it render as `�` under the default Windows console codepage during manual verification — a legibility fix for the screen-recording use case, no functional change.
- **Docs stayed light per the user's explicit deviation**: `README.md` got only the two appended sections (Pack authoring + Roadmap); `.paul/PROJECT.md` was not touched (already current); `.paul/STATE.md` got the one status-table line plus its evidence summary — no rewrite of either file.

## Concerns

- **Full untargeted `uv run pytest -q` currently shows 1 failure**, but it is **not caused by anything in this task**: `tests/test_graph_wave1.py::test_transient_check_failure_recovers_via_retry` fails deterministically (reran twice, same failure both times). This file did not exist when this task started (confirmed by directory listing at task start: only `test_config.py`, `test_name_match.py`, `test_scorecard.py`, `test_pack_loader.py`, `pack_conformance.py`, `test_pack_kyc_uae.py`, `test_graph.py`, `test_runner.py`, `test_api.py`). Filesystem timestamps show `tests/test_graph_wave1.py` (19:08:49) and `src/voxgate/graph/build.py` (19:09:38) were both modified concurrently *during* this task's work session — after `tests/integration/test_postgres_resume.py` was written (19:03:45). `src/voxgate/graph/build.py` is on this task's explicit do-not-edit list, and `test_graph_wave1.py` is not one of this task's files, so no action was taken on either. **Isolating the scope confirms this**: `uv run pytest -q --ignore=tests/test_graph_wave1.py` → **40 passed, 1 skipped**, fully green. The brief anticipated only "a small concurrent fix... to `tests/test_api.py`" bringing the count to 40–41; a new file plus a `graph/build.py` change implementing check-node retry logic is a materially larger concurrent change than that, and it is currently landing in a broken intermediate state. This should be flagged to whoever owns that concurrent work — it is unrelated to and not fixable from within Task 9's scope.
- Per the ledger's already-known deferred items (Tasks 1–8), nothing new was found in the files this task touched.

## Files touched

- `C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate\tests\integration\test_postgres_resume.py` (new)
- `C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate\src\voxgate\service\runner.py` (added `recover_case`)
- `C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate\scripts\demo_case.py` (new)
- `C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate\README.md` (appended two sections)
- `C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate\.paul\STATE.md` (one status-table line updated)
