# VoxGate — Phase Documentation Index

VoxGate is a pack-driven voice-interview compliance gating platform. This directory documents the 9-phase build described in `.superpowers/sdd/2026-08-06-voxgate-core-platform/` (the "core platform" SDD ledger): config → name matching → scorecard → pack loader → the `kyc-uae` pack → LangGraph case state machine → case store/API service → operational polish.

As of this writing (2026-08-06), Tasks 1–7 are **built and review-approved**; Task 8 is **implemented (39/39 tests passing) but its review is pending**; Task 9 is **not started**. The user paused the SDD build pipeline on 2026-08-06 right after Task 8's implementation landed, before Task 8's review or Task 9's work began.

| Phase | Name | Status | Files touched | Summary |
|---|---|---|---|---|
| 1 | [Project Scaffold + Settings](phase-1-config.md) | ✅ Built & review-approved | `pyproject.toml`, `docker-compose.yml`, `.env.example`, `src/voxgate/config.py`, `src/voxgate/{ml,packs,graph,service}/__init__.py`, `tests/test_config.py` | Package scaffold + `Settings`/`get_settings()` — the in-memory-vs-Postgres switch and `packs_dir` every later phase reads. |
| 2 | [Transliteration Variants + Name-Matching Ensemble](phase-2-name-matching.md) | ✅ Built & review-approved | `src/voxgate/ml/variants.py`, `src/voxgate/ml/name_match.py`, `tests/test_name_match.py` | `NameMatcher` ensemble (Jaro-Winkler + token-set + optional embedding) with Arabic-name romanization variant expansion and DOB/nationality corroboration boosts. |
| 3 | [Explainable Scorecard Engine](phase-3-scorecard.md) | ✅ Built & review-approved | `src/voxgate/ml/scorecard.py`, `tests/test_scorecard.py` | Pack-agnostic additive log-odds scorecard: `Feature`/`Scorecard` → `ScoreResult` with per-feature attributable contributions and low/medium/high banding. |
| 4 | [Pack Protocols + Loader](phase-4-pack-loader.md) | ✅ Built & review-approved | `src/voxgate/packs/base.py`, `src/voxgate/packs/loader.py`, `tests/test_pack_loader.py` | `Pack`/`CheckResult` platform contract; `load_pack`/`load_packs` dynamically wire a `packs/<id>/` directory into a `Pack`, with `PackLoadError` wrapping and duplicate-`pack_id` detection. |
| 5 | [The `kyc-uae` Pack + Shared Conformance Suite](phase-5-kyc-uae-pack.md) | ✅ Built & review-approved | `packs/kyc_uae/**`, `tests/pack_conformance.py`, `tests/test_pack_kyc_uae.py` | First real scenario pack (UAE fintech KYC): sanctions/PEP/adverse-media screening, 7-feature scorecard, mock synthetic datasets, plus the generic `run_conformance()` every future pack must pass. |
| 6 | [LangGraph Case State Machine](phase-6-langgraph-case-state-machine.md) | ✅ Built & review-approved | `src/voxgate/graph/state.py`, `src/voxgate/graph/build.py`, `tests/test_graph.py`, `packs/kyc_uae/checks.py` (check_name attrs) | `CaseState` + `build_graph()`: intake → interview (interrupt) → validate → parallel `check_<check_name>` fan-out → score → route → auto-approve or reviewer gate (interrupt), with a capped re-ask loop; resume-payload trust boundary deliberately parked to Task 7. |
| 7 | [CaseStore + EventBus + CaseRunner](phase-7-case-store-eventbus-runner.md) | ✅ Built & review-approved | `src/voxgate/service/store.py`, `src/voxgate/service/events.py`, `src/voxgate/service/runner.py`, `tests/test_runner.py` | In-memory case index, thread-safe pub/sub for live dashboard events, and the orchestrator that drives the compiled graph and keeps both in sync; implements the `needs_attention` crash-containment trust boundary parked to it by Task 6. |
| 8 | [FastAPI App — REST + WebSocket](phase-8-fastapi-service.md) | 🟡 Built — task review pending (pipeline paused) | `src/voxgate/service/app.py`, `tests/test_api.py` | `create_app()`: thin REST/WS wrapper over `CaseRunner` — pack listing, case lifecycle, field patching, interview/decision resume with 404/409 semantics, live WebSocket event stream. Implemented and passing (39/39); independent review has not run yet. |
| 9 | [Postgres Durability Integration Test + Demo Script + Docs](phase-9-postgres-durability-and-demo.md) | ⏸ Not started — pipeline paused | `tests/integration/test_postgres_resume.py`, `scripts/demo_case.py`, `README.md`, `.paul/PROJECT.md`, `.paul/STATE.md` | Proves the "kill the server, restart, resume the case" durability claim against real Postgres; ships the CLI demo script (the portfolio screen-recording artifact) and top-level docs. Blocked behind Task 8's review. |

## How to read this

Each phase doc follows the same structure: Purpose, What was/will be built, Public interfaces, Key design decisions & why, Test evidence, Review history, Dependencies. For Phases 1–8, interfaces and test evidence are quoted directly from the built source (`src/voxgate/**`, `packs/kyc_uae/**`, `tests/**`) and the SDD reports (`.superpowers/sdd/2026-08-06-voxgate-core-platform/task-N-report.md`). Phases 1–7 additionally carry completed review history; Phase 8's review has not run yet (pipeline paused), so its doc has no fix rounds/deferred minors/parked findings section populated. Phase 9 is drawn entirely from its brief (`task-9-brief.md`) describing the plan — no Task 9 code exists yet.

## Sources

- SDD ledger: `.superpowers/sdd/2026-08-06-voxgate-core-platform/progress.md`
- Global constraints: `.superpowers/sdd/2026-08-06-voxgate-core-platform/global-constraints.md`
- Per-phase briefs: `.superpowers/sdd/2026-08-06-voxgate-core-platform/task-{1..9}-brief.md`
- Per-phase reports (Phases 1–8 only): `.superpowers/sdd/2026-08-06-voxgate-core-platform/task-{1..8}-report.md` (Task 4's and Task 6's reports each include an appended fix-round report)
- Design spec: `docs/superpowers/specs/2026-08-06-voxgate-design.md`
- Source: `src/voxgate/**`, `packs/kyc_uae/**`, `tests/**`

See also: [`.paul/PROJECT.md`](../../.paul/PROJECT.md), [`.paul/STATE.md`](../../.paul/STATE.md).
