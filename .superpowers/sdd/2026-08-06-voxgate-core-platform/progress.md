# SDD ledger — plan: docs/superpowers/plans/2026-08-06-voxgate-core-platform.md
Task 1: minor (deferred): get_settings() untested (named interface, test is import-only)
Task 1: complete (no-git mode, review clean)
Task 2: minor (deferred): best-pair selection uses embed-weights even without embedder; _norm private import; no boost-cap test
Task 2: complete (no-git mode, review clean)
Task 3: minor (deferred): contribution rounded from unrounded x, so emitted value*weight may differ at 4th decimal
Task 3: complete (no-git mode, review clean)
Task 4: fix round 1/5 (2 addressed, 0 open — PackLoadError wrapping; duplicate pack_id ValueError)
Task 4: minor (deferred): colliding pack's submodules land in sys.modules before the duplicate-id ValueError fires; duplicate-pack test's "pack1" assertion trivially satisfied by the quoted id
Task 4: complete (no-git mode, review clean)
Task 5: minor (deferred): adverse_media/UAE-list data at exact brief minimum; NameMatcher rebuilt per check call; no adverse_media hit-path test; scoring.py hardcodes qualname "voxgate_pack_kyc-uae_checks" (renaming pack_id silently breaks it)
Task 5: complete (no-git mode, review clean; pythonpath=["."] added to pyproject — reviewer confirmed necessary)
Task 6: fix round 1/5 (2 addressed, 0 open — check nodes renamed check_<check_name> via function attr; dedup test now drives request_info loop and asserts last-write-wins)
Task 6: parked — resume-payload guards (KeyError on malformed resume) — ruling: human ruled Task 7 runner owns the trust boundary (its brief wraps .invoke in try/except → needs_attention); graph-level guards would duplicate it
Task 6: minor (deferred): node-set test uses subset (<=) not exact match; test relies on graph.get_graph().nodes introspection API (langgraph version-fragility surface); medium_reask max() unguarded for empty contributions; stale check_results shown at force_gate after earlier check cycle
Task 6: complete (no-git mode, review clean after fix round 1)
Task 7: parked — pre-invoke case skeleton omits fields/score/check_results/decision/interrupt keys (plan-mandated, brief's own Step-3 code) — ruling: window is synchronous+sub-ms today, unexercisable; revisit in Plan 2 when nodes gain real latency
Task 7: minor (deferred): store get()/list() return direct dict references not copies; start_case catches unknown pack_id into a phantom needs_attention case instead of erroring
Task 7: complete (no-git mode, review clean; deviations approved — shared checkpointer in crash test [verified: fresh MemorySaver silently replays], _mark_needs_attention DRY helper)
Task 8: implemented DONE (39/39 full suite; lazy module-level app via PEP 562 __getattr__ per brief note; one StarletteDeprecationWarning from fastapi.testclient import itself)
Task 8: fix round 1/5 (1 addressed, 0 open — lazy app memoized via _app_instance cache + regression test; 40/40)
Task 8: minor (deferred): __getattr__ memoization not lock-protected for concurrent first access (unreachable via uvicorn's single-threaded import); WS handler catches only WebSocketDisconnect (brief-inherited)
Task 8: complete (no-git mode, review clean after fix round 1)
--- Extension wave (user-requested, beyond plan): Task 9 + graph Wave 1 (docs/design/2026-08-06-graph-upgrade-design.md) + dashboard UI, running as parallel implementers with disjoint file ownership ---
Task 9: minor (deferred): demo waterfall bars use abs(contribution) — ambiguous if a future pack has negative contributions; request_info path in demo script manually verified only
Task 9: complete (no-git mode, review clean; Postgres integration test passed against real Docker Postgres; recover_case verbatim; docs kept light per user)
Wave 1: implemented + integrated (14 new tests green; audit surfaced via runner._sync) — REVIEW INTERRUPTED by wind-down; package at task-wave1-package.md
Dashboard: PARTIAL (~30%) — static/index.html + dashboard.css only; no JS, no dashboard.py router, app.py untouched, no tests; build agent stopped mid-write by user wind-down
SESSION WIND-DOWN 2026-08-06: final verified state 54 passed / 1 skipped / 1 known warning; authoritative DONE-vs-REMAINING list in .paul/STATE.md "Wind-down state"
