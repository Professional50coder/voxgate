# Phase 9 — Postgres Durability Integration Test + Demo Script + Docs

**Status:** ⏸ Not started — pipeline paused

> This document describes the PLAN from `task-9-brief.md`. Phases 6, 7, and 8 are now built (6 and 7 review-approved; 8 implemented with 39/39 tests passing but review pending — see their respective phase docs), so Phase 9's dependencies are closer to ready than when this document was first written. However, the user paused the SDD build pipeline on 2026-08-06 immediately after Task 8's implementation, before Task 8's review or Task 9's implementation began. As of this writing, `scripts/` and `tests/integration/` still do not exist, and `CaseRunner.recover_case` has not been added to `src/voxgate/service/runner.py`. Nothing in the "what was built" sense below reflects Task-9 code that has actually been written — it remains the plan from the brief only. (Note: a top-level `README.md` does already exist at the repo root — it was written as a separate, out-of-band documentation deliverable, not as part of Task 9's own implementation, so it does not by itself indicate Task 9 has started.)

## 1. Purpose

Phase 9 is the closing phase of the "Plan 1" core-platform build: it doesn't add new platform capability so much as *prove* the capability already built actually survives the scenario the whole architecture was designed around — a process restart mid-case (design spec §6: "Backend restart: checkpointer resumes all cases exactly where they were (deliberately demoed: kill server on camera, restart, approve the case)"). It also produces the runnable CLI demo intended as the literal screen-recording artifact for the portfolio showcase, and the top-level docs a visitor or teammate needs to get oriented.

## 2. What will be built

| File | Responsibility |
|---|---|
| `tests/integration/test_postgres_resume.py` | Skipped unless `VOXGATE_TEST_DB` is set; proves a case parked at `awaiting_review` survives a brand-new `CaseRunner`/process and can still be resumed to `approved` |
| `scripts/demo_case.py` | ~80-line CLI demo against a running server; clean or `--risky` applicant; prints every status transition, the score waterfall, and prompts a reviewer decision on stdin when parked at review |
| `README.md` | What VoxGate is, quickstart, test matrix, pack-authoring guide, roadmap (a top-level `README.md` already exists at the repo root as of this writing, written as a separate out-of-band deliverable — see the note above; whether Task 9's implementer keeps, extends, or supersedes it is not yet decided) |
| `.paul/PROJECT.md` | Goal, architecture summary, spec + plan links (per-project Paul-convention doc — see note below) |
| `.paul/STATE.md` | Build status snapshot (per-project Paul-convention doc — see note below) |

An addition to `src/voxgate/service/runner.py` is also planned as part of this phase: `CaseRunner.recover_case(case_id, pack_id)`.

> **Note on `.paul/` overlap:** this same brief asks the Phase 9 implementer to write `.paul/PROJECT.md`/`.paul/STATE.md`. Those two files are also part of *this documentation task's own deliverables* (per the current task's instructions) and have already been written as part of this pass — see `.paul/PROJECT.md` and `.paul/STATE.md` at the repo root, reflecting the actual current state (Tasks 1–5 built and review-approved, Tasks 6–9 in flight) rather than the brief's forward-looking "Plan 1 complete" framing, since that milestone has not yet been reached.

## 3. Public interfaces (from the brief)

```python
# tests/integration/test_postgres_resume.py
DSN = os.environ.get("VOXGATE_TEST_DB")
pytestmark = pytest.mark.skipif(not DSN, reason="VOXGATE_TEST_DB not set")

def test_case_survives_process_restart(): ...

# src/voxgate/service/runner.py (addition)
class CaseRunner:
    def recover_case(self, case_id, pack_id):
        """Rehydrate the store entry for a case that exists only in the checkpointer."""
        ...
```

`scripts/demo_case.py` CLI contract (per the brief): no arguments = clean applicant, `--risky` = sanctions-lookalike applicant; creates a case, prints the interview interrupt payload, submits the scripted fields as the "interview" result, pretty-prints check results plus a score waterfall (feature name / value / weight / contribution, one `#` per 0.1 of contribution), and — if the case parks at review — prompts `approve`/`reject`/`request_info` on stdin and submits the decision.

## 4. Key design decisions (planned) & why

- **`recover_case` exists because the in-memory `CaseStore` index is *not* durable, even when the checkpointer is Postgres.** A restarted process has an empty `CaseStore` but a fully intact LangGraph checkpoint history in Postgres — `recover_case(case_id, pack_id)` is the planned bridge: it seeds a bare store entry (`live_fields: {}`) and then calls the existing `_sync(case_id, pack_id)` (from Phase 7) to rehydrate the real status/fields/interrupt from the checkpointer. The brief is explicit that this is deliberately a *per-case* recovery path, not a store-rebuild-on-boot: "full store rebuild on boot is a Plan 3 concern (the dashboard needs it); for now `recover_case` is the explicit per-case recovery path and the integration test its consumer." In other words, Phase 9 proves durability is real without yet building the convenience feature (auto-listing all recoverable cases) a dashboard would need — that's explicitly deferred to a later plan.
- **The integration test is opt-in via an environment variable (`VOXGATE_TEST_DB`), not run by default.** Consistent with the global constraint that regular `uv run pytest` needs zero paid keys and no external services — this is the one test in the whole suite that genuinely requires a running Postgres (`docker compose up -d`), so it's gated to skip cleanly (not fail) when that's unavailable, keeping the fast default test loop dependency-free while still providing a real, runnable durability proof when the operator opts in.
- **The test simulates "process restart" by constructing a brand-new `CaseRunner` instance sharing only the DSN, not any Python object.** `_fresh_runner()` builds a fully independent `CaseRunner` each time (`r1`, then `r2`) — the only thing surviving between them is what's actually in Postgres, which is the whole point: if `r2.recover_case(...)` produces the correct `awaiting_review` status and a `"review"`-type interrupt purely from checkpointer state, that's genuine proof the process could die and come back, not an artifact of shared in-memory state.
- **The demo script is designed to *be* the portfolio artifact, not just a smoke test.** Per the brief: "print every status transition with the case id so a screen recording of this is the Plan-1 demo artifact" — its outputs (interrupt payloads, the score waterfall with `#`-bar visualization, the final decision prompt) are deliberately human-readable/presentable rather than machine-parseable, since its purpose is a recorded demo, not CI.
- **The demo script talks to a *running* `uvicorn` server over HTTP (via `httpx`), not to an in-process `CaseRunner`.** This is the same distinction Phase 9's manual end-to-end check leans on: Step 5 of the brief explicitly has the operator restart the `uvicorn` process mid-review (with `VOXGATE_DATABASE_URL` set) and confirm the decision still lands — proving durability through the *real* deployment shape (separate server process, HTTP boundary), not just through the Python-level integration test.
- **README/`.paul` docs are scoped narrowly per the brief**: README covers what-is/quickstart/test-matrix/pack-authoring/roadmap; `.paul/PROJECT.md` covers goal/architecture/links; `.paul/STATE.md` is meant as a snapshot ("Plan 1 complete, Plans 2–4 pending, date 2026-08-06" per the brief's literal text) — though as noted above, since Plan 1 (Tasks 1–9) is not actually complete as of this writing, the `.paul/STATE.md` produced for the current documentation task reflects the true state (5/9 tasks done) rather than the brief's aspirational text.

## 5. Test evidence

Not yet available. Phase 9's own dependencies (Phases 6, 7, 8) are now built — see their respective phase docs — but Task 9 itself has not been implemented; the pipeline was paused right after Task 8's implementation landed. The brief specifies: the integration test should show 1 PASS when `docker compose up -d` + `VOXGATE_TEST_DB` is set, and SKIP in a fresh shell without it; Step 7 calls for a final full regression (`uv run pytest -v`, "all green (integration tests skip without the env var — that's fine)"). Not recorded.

## 6. Review history

Not yet applicable — Phase 9 has not been started; not recorded in the SDD ledger. Task 8, the immediate prerequisite, is itself implemented but still awaiting its own review (see `docs/phases/phase-8-fastapi-service.md`) — Task 9 cannot begin until the pipeline resumes.

## 7. Dependencies

- **Consumes:** everything — Phase 1 (`Settings`), Phase 4 (`load_packs`), Phase 5 (`RISKY` fixture from `tests.test_pack_kyc_uae`), Phase 6 (the compiled graph, indirectly), Phase 7 (`CaseRunner`, `CaseStore`, `EventBus`, plus the new `recover_case` addition), Phase 8 (`_postgres_factory`, and the running HTTP API the demo script targets).
- **Feeds:** nothing further within Plan 1 — this is the terminal phase of the core-platform build described by this ledger. The design spec's roadmap (§8, "4-plan roadmap" referenced in the brief's README instructions) implies later plans (voice bot, frontend dashboard, deployment hardening) build on top of this phase's output, but those are out of scope for `.superpowers/sdd/2026-08-06-voxgate-core-platform/`.
