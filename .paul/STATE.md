# VoxGate — State

**As of:** 2026-08-07 (production-hardening pass)
**Ledger:** `.superpowers/sdd/2026-08-06-voxgate-core-platform/progress.md`

---

## Current state — production hardening, 2026-08-07

**Suite: 232 passed with Postgres (`VOXGATE_TEST_DB` set), 197 passed / 35 skipped offline.**
Branch `feat/production-spine`. Frontend (`apps/web`) builds clean on Next.js 16.3.

A full production review was run against the whole codebase and its findings fixed.
The two that mattered:

1. **Remote code execution in `POST /packs/publish` — proven, then closed.** `bias`,
   `weight`, `min_words` and enum risk values were interpolated into generated Python
   as bare f-string values, so a spec containing
   `"bias": "__import__('os').system('...') or -2.0"` executed on import, reachable
   unauthenticated from a browser. Closed at two independent layers: `publish._number()`
   validates, and `emit._num()` refuses to render a non-number even if called directly.
   Regression tests include an end-to-end one that publishes the exploit and asserts the
   file it would have written does not exist.
2. **Boot denial of service.** Publishing wrote straight into the packs directory, and
   `load_packs` aborted on any unloadable pack — so one malformed request left a partial
   pack behind and the service refused to start until a human deleted it, across
   restarts. Publishing now stages into a sibling temp dir and renames into place, with
   backup-and-restore on overwrite; `load_packs` skips a broken pack with a warning
   (`strict=True` still raises, for the CLI and conformance runs).

Also fixed in this pass:

- **WebSocket streams no longer die silently.** The cursor was a list position, so once
  the ring buffer evicted anything, `len(queue) > after_index` went permanently false.
  Events now carry a monotonic `seq` and the cursor filters on it.
- **Multi-worker correctness.** The in-memory `EventBus` and the per-process pack
  registry both broke under `--workers N` with no error at either end. There is now a
  `PgEventBus` (polling, not LISTEN/NOTIFY — LISTEN does not survive a transaction
  pooler, which the pool is configured for), and the runner rescans the packs directory
  on a miss so a pack published on one worker becomes runnable on the others.
  `tests/integration/test_multi_worker.py` asserts both, including a test that pins the
  in-memory bus's *failure* so swapping it back in cannot pass silently.
- **The event stream silently dropped ~1.2% of events under concurrent writers —
  a bug I introduced with the Postgres bus and then caught.** `events.seq` was a
  global `bigserial`, and a sequence hands out its value *before* the transaction
  commits. Writer A takes seq=10, writer B takes seq=11 and commits first; a
  poller reading at that instant advances its cursor past 11 and never asks for
  10 again. Every row was in the table and the viewer simply never received some
  of them — invisible to any single-threaded test, which is why the whole
  contract suite passed throughout. Found by running three workers end to end and
  noticing 6 of 8 events arrive. Fixed by allocating a per-case seq from a
  counter row bumped in the *same transaction* as the insert, so the row lock is
  held until the event is visible: seq N+1 cannot be allocated until N is
  committed. A `MAX(seq)+1` retry loop was tried first and was much worse — 264
  of 320 publishes exhausted their retries. `tests/integration/test_event_ordering.py`
  pins it; verified separately with two independent server processes on one
  database, four trials, zero loss.
- **Per-case concurrency control.** A double-submitted review form could have two resumes
  race the same interrupt, the second overwriting the first. `CaseRunner._case_lock` takes
  a per-case `threading.Lock` plus a Postgres advisory lock. **The first version of this
  fix was worse than the bug** — it held a store-pool connection for the whole graph
  invocation while the work under it needed a second, deadlocking at five concurrent
  resumes against a five-connection pool. Confirmed with a standalone reproduction, then
  fixed with a dedicated lock pool; `tests/integration/test_case_locking.py` pins it.
- **Exception messages no longer reach clients.** `runner` stored `str(e)` in the case and
  returned it; a psycopg failure carries host, port and user. Now the type only, with the
  traceback logged. `RequestContextMiddleware` does the same for unhandled 500s and
  attaches an `X-Request-ID`.
- **Rate limiting** on the endpoints that spend an LLM call or write generated Python
  (per process — see the docstring for why that trade is deliberate).
- **CORS `*` no longer combines with credentials** (Starlette echoes the request Origin in
  that configuration, which is worse than a wildcard).
- **Graceful shutdown** closes both pools and the checkpointer's own connection.
- Request-body bound on `PublishPayload.spec`; Groq key fragment removed from
  `docs/research/`; stray `image.png` removed from the repo root.

**Known and deliberate:** auth is not built (deferred by the user), so `/packs/publish`
must not be publicly exposed as-is. Schema management is still
`CREATE TABLE IF NOT EXISTS` rather than migrations. The Pipecat voice layer has no code
yet.

---

## ⚠️ DIRECTION CHANGE — 2026-08-07

**The project scope changed. Everything below the "Status summary" heading describes the
completed 2026-08-06 backend build and remains accurate as history — but the "REMAINING"
list in the old wind-down section is superseded.**

Five changes, all from the user directly:

1. **Frontend moves to Next.js.** The half-built vanilla-JS dashboard becomes a *port
   target*, not a completion target. Its CSS design system is complete and worth preserving.
2. **Pipecat becomes a central integration**, not a later plan.
3. **The LangGraph layer gets a production upgrade** — the flat per-pack graph, the
   synchronous `.invoke()` from a request thread, and the in-memory `CaseStore`/`EventBus`
   are all targets.
4. **Groq API added.** Key lives in `.env` (gitignored). The previous **zero-paid-keys
   constraint is relaxed** — though local-first still matters for PII, see below.
5. **The "no git in this folder" constraint is LIFTED.** The repo is live at
   `https://github.com/hitanshppc-hash/voxgate` (private).

**Read `docs/research/README.md` before doing anything.** Five research notes were written
on 2026-08-07, each verified against live sources. Three of their findings invalidate
assumptions baked into the older design docs. The acting plan is `docs/ROADMAP.md`.

**The single most load-bearing finding:** local STT is *segmented*, not streaming — it emits
no interim transcripts. The dashboard spec's "word-by-word captions" **cannot be built as
designed**.

**Baseline re-verified 2026-08-07:** `uv run pytest -q` → **54 passed, 1 skipped**.

---

**Session wound down by user 2026-08-06 (evening).** All 9 planned tasks are COMPLETE and review-approved. An extension wave (graph Wave 1 + dashboard + design docs) ran after the plan; its exact state is in "Wind-down state" below. **Final verified suite at wind-down: `uv run pytest -q` → 54 passed, 1 skipped (Postgres integration without env var), 1 known warning.**

## Wind-down state (what is DONE vs REMAINING)

**DONE beyond the 9-task plan:**
- **Task 8**: review completed after the pause — 1 Important finding (non-memoized lazy `app`) fixed in fix round 1 (`_app_instance` cache + regression test), re-review clean. COMPLETE.
- **Graph Wave 1** (`docs/design/2026-08-06-graph-upgrade-design.md`): IMPLEMENTED + integrated — audit trail (`audit` reducer w/ seq + duration_ms per node), richer interview payloads (field_errors, attempt, max_attempts, fields_validated), richer review payloads (score_waterfall, flagged_checks), RetryPolicy(max_attempts=2) on check nodes, audit surfaced through `runner._sync` to the store/API. 14 tests in `tests/test_graph_wave1.py`, all green; the original 8 graph tests untouched and green. **Its independent review was interrupted by the wind-down — code is green but not yet independently reviewed.** Known deviation: langgraph's default RetryPolicy does not retry RuntimeError (only connection/5xx-style errors) — retry test adapted accordingly.
- **Voice agent design (Plan 2)**: `docs/design/2026-08-06-voice-agent-plan2-design.md` — verified fully-local zero-key pipeline (faster-whisper + Silero VAD + Piper TTS + pipecat 1.7), 8-task implementation plan under `src/voxgate/voice/*`. Design only; no code.
- **Demo kit**: `docs/demo/DEMO-RUNBOOK.md` (10-min live demo script) + `docs/demo/ONE-PAGER.md` (product brief).
- **Cross-platform README.md** (auto-paths, per-OS setup, dependency policy) + per-phase docs `docs/phases/` + this `.paul/` set.

**REMAINING (in priority order for the next session):**
1. **Dashboard UI — partial, ~30% built, NOT functional.** The build agent was stopped mid-write. Exists: `src/voxgate/service/static/index.html` (shell) + `static/dashboard.css` (complete Siri-style design system, ~33KB). Missing: the main JS application file, `src/voxgate/service/dashboard.py` (router — never created), the `app.py` include wiring, `tests/test_dashboard.py`, and the demo-seed endpoint. `app.py` was never touched, so the API is fully intact. Full spec for the dashboard (Siri aesthetic, voice orb + word-by-word captions, live pipeline SVG graph, KPI tiles, analytics, monitoring strip, demo seed) lives in the coordinator conversation and can be re-derived from the two static files' structure.
2. **Graph Wave 1 independent review** — code green but unreviewed; package ready at `.superpowers/sdd/2026-08-06-voxgate-core-platform/task-wave1-package.md`.
3. **`POST /cases/{id}/recover` REST endpoint** — `CaseRunner.recover_case` exists and is integration-tested, but is not exposed over HTTP: after a server restart `GET /cases/{id}` 404s even though the Postgres checkpoint survived. Small task (endpoint + test); makes the durability demo work live over HTTP.
4. **Final whole-project review + fix wave** — never run; was queued as the last gate.
5. Voice agent implementation (Plan 2) per its design doc, when desired.

## Status summary

| Task | Phase name | Status |
|---|---|---|
| 1 | Project scaffold + Settings | ✅ Complete, review clean |
| 2 | Transliteration variants + name-matching ensemble | ✅ Complete, review clean |
| 3 | Explainable scorecard engine | ✅ Complete, review clean |
| 4 | Pack protocols + loader | ✅ Complete — fix round 1 applied (2 findings fixed), review clean |
| 5 | The `kyc-uae` pack + shared conformance suite | ✅ Complete, review clean |
| 6 | LangGraph case state machine | ✅ Complete — fix round 1 applied (2 findings fixed, 1 parked), review clean |
| 7 | CaseStore + EventBus + CaseRunner | ✅ Complete, review clean (deviations approved) |
| 8 | FastAPI app — REST + WebSocket | ✅ Complete — fix round 1 applied (lazy `app` memoized), review clean |
| 9 | Postgres durability integration test + demo script + docs | ✅ Complete — `recover_case` added, integration test passes against real Postgres (1 passed), skips cleanly without `VOXGATE_TEST_DB`; `scripts/demo_case.py` verified end-to-end (clean auto-approve + risky review path); full suite green (41 passed with `VOXGATE_TEST_DB` set, 40 passed/1 skipped without) |

**Test suite state:** per `task-8-report.md`, `uv run pytest -q` → **39 passed, 1 warning** (34 from Tasks 1–7 + 5 from Task 8). The one warning (`StarletteDeprecationWarning`, from `fastapi.testclient`'s own import of `starlette.testclient`) is a pinned-dependency-version artifact, not a defect — see `docs/phases/phase-8-fastapi-service.md` §6 for detail. Tasks 1–7 additionally verified clean under `-W error` (zero warnings) as of the Task 7 fix-round rerun.

## Deferred minors (from the ledger, `progress.md`)

Copied verbatim from `.superpowers/sdd/2026-08-06-voxgate-core-platform/progress.md`:

- **Task 1:** `get_settings()` untested (named interface, test is import-only).
- **Task 2:** best-pair selection in `NameMatcher.match()` uses embed-weighted scoring even without an embedder (selection formula vs. reported `combined` formula diverge when `embedder=None`, though the winning pair doesn't change since `emb=0` for all candidates); `_norm` is imported from `variants.py` as a private (underscore-prefixed) name; no test asserts the DOB/nationality boost cap at `1.0`.
- **Task 3:** `contribution` is rounded from the unrounded `x`, so `emitted_value * weight` (recomputed from the already-rounded `value`) may differ from the emitted `contribution` at the 4th decimal place. Cosmetic only — doesn't affect probability, band, or routing.
- **Task 4:** a colliding pack's `schema`/`checks`/`scoring` submodules land in `sys.modules` before the duplicate-`pack_id` `ValueError` fires (stale `sys.modules` state after the error); the duplicate-pack test's `"pack1" in str(excinfo.value)` assertion is trivially satisfied because the error message quotes the `pack_id` directly (the accompanying `"pack2"` assertion is the meaningful check).
- **Task 5:** `adverse_media.json` (3 entries) and the UAE Local Terrorist List slice of `sanctions.json` (2 entries) sit at the brief's exact stated minimums; `NameMatcher` is rebuilt fresh on every single check call rather than cached; no test exercises the `adverse_media` check's actual `"review"`-status hit path; `scoring.py` hardcodes the `sys.modules` qualname string `"voxgate_pack_kyc-uae_checks"` — renaming the pack's `pack_id` in `pack.yaml` would silently break this lookup.
- **Task 6:** `test_check_node_names_match_pack_check_names` uses a subset check (`<=`) rather than an exact node-set match; the test relies on `graph.get_graph().nodes` for introspection, an API surface that could shift across LangGraph versions; `medium_reask`'s `max(...)` over `state["score"]["contributions"]` is unguarded against an empty list; `force_gate`'s `check_results: []` combined with the add-reducer can leave stale check results visible from an earlier interview cycle when a case is force-gated.
- **Task 7:** `CaseStore.get()`/`.list()` return direct references to the dicts held internally, not copies — a caller mutating a returned case dict in place would corrupt store state without going through `upsert`; `start_case` on an unknown `pack_id` isn't guarded upfront, so it surfaces as a phantom `needs_attention` case (caught by the existing `try/except` around `.invoke()`) rather than a clean error before any case record is created — Phase 8's `create_app` compensates for this at the HTTP layer by checking `pack_id not in runner.packs` before calling `start_case`, but the runner itself doesn't enforce it.

None of these are blocking; all were explicitly deferred by review rather than left unnoticed.

## Parked findings (deliberate architectural rulings, not deferred minors)

- **Task 6:** resume-payload guards (protecting against a malformed/missing-key `Command(resume=...)` payload raising a bare `KeyError` inside a graph node) were raised in review and explicitly parked. Ruling: Task 7's `CaseRunner` already owns this trust boundary — its brief wraps `.invoke()` in `try/except Exception` to produce the `needs_attention` status — so graph-level guards would duplicate rather than strengthen it. The graph stays a thin, trusting state machine; Task 7 is responsible for containing malformed input/crashes. **Task 7 implements this boundary** — confirmed in review: `start_case`/`resume` wrap `.invoke()` in `try/except Exception`, mapping any failure (including a crashing check node) to `status="needs_attention"` with an `error` field, via a shared `_mark_needs_attention` helper. No guards were added inside `src/voxgate/graph/build.py`.
- **Task 7:** pre-invoke case skeleton (`start_case`'s initial `store.upsert` before `graph.invoke()` runs) omits the `fields`/`score`/`check_results`/`decision`/`interrupt` keys `_sync` would otherwise populate — this is the brief's own Step-3 code, not an implementation oversight. Ruling: because `graph.invoke()` runs synchronously and completes in sub-millisecond time in Plan 1 (no LLM/network-calling nodes exist yet), the window where a caller could observe this incomplete skeleton is effectively unexercisable today. Parked, to be revisited in Plan 2 once nodes gain real latency.

## Fixes applied (not deferred)

- **Task 4, fix round 1/5** (per ledger: "2 addressed, 0 open"): `PackLoadError` now wraps every exception raised while loading a single pack, preserving pack path + original exception as `__cause__`; `load_packs()` now raises `ValueError` on a duplicate `pack_id` across two directories instead of silently overwriting the first pack's entry.
- **Task 6, fix round 1/5** (per ledger: "2 addressed, 0 open"): check-node names now derive from an explicit `check_name` attribute set on each `kyc-uae` check function (`sanctions_screen.check_name = "sanctions"`, etc.) via a shared `_node_name()` helper in `build.py`, instead of the Python function's `__name__` — closing the mismatch where graph node names (`check_sanctions_screen`) didn't match each check's reported `CheckResult.check_name` (`"sanctions"`). `test_latest_check_results_win_after_reask` was also rewritten: the original version's invalid-dob-first payload never reached any check node, so the last-write-wins dedup logic went unexercised despite the test's name; the rewrite drives RISKY → `request_info` → CLEAN to force a genuine duplicate-then-dedup cycle and asserts on it directly.

## Deviations approved (Task 7)

- **Shared checkpointer in the crash test**, not a fresh `MemorySaver()` as the brief's literal helper signature suggested. Empirically verified: a brand-new `MemorySaver` has no checkpoint history for the case's `thread_id`, so `Command(resume=payload)` against it silently replays from `START` instead of raising — it never reaches the crashing check node. The test helper (`_crashing_graph_for(pack, checkpointer)`) was changed to reuse the runner's actual `MemorySaver` instance, confirmed via an isolated repro before the fix was accepted. No production code changed to make the test pass — pure test-wiring correction.
- **`_mark_needs_attention` DRY helper** — factors the brief's duplicated inline upsert/publish/return sequence (present in both `start_case`'s and `resume`'s except blocks) into one private method. Behavior-identical at each call site; non-semantic simplification.

## Task 8 (implemented, review pending)

- **Task 8: implemented DONE** (per ledger): 39/39 full suite passing; module-level `app` built lazily via a PEP 562 `__getattr__` instead of the brief's literal eager `app = create_app()` — explicitly sanctioned by the brief's own implementer note, since eager construction would load real packs and build LangGraph graphs as a side effect of merely importing the module (including on every `tests/test_api.py` collection); one `StarletteDeprecationWarning` fires from `fastapi.testclient`'s own import of `starlette.testclient`, intrinsic to the pinned dependency versions and not caused by project code. **Task review has not run — the pipeline was paused by the user immediately after this implementation landed.** No fix rounds, deferred minors, or parked findings exist for Task 8 yet.

## Notable non-brief change

- `pyproject.toml` gained `pythonpath = ["."]` under `[tool.pytest.ini_options]` during Task 5 — needed because the brief's own `tests/test_pack_kyc_uae.py` does `from tests.pack_conformance import run_conformance`, which requires the repo root on `sys.path` under `uv run pytest` (no `tests/__init__.py`/`conftest.py` otherwise adds it). Confirmed necessary by review; outside Task 5's stated file list but additive and minimal.

## Next steps

Superseded — see "Wind-down state" at the top of this file for the authoritative DONE vs REMAINING list (dashboard completion is item 1).

## Reference docs

- Per-phase detail: [`docs/phases/README.md`](../docs/phases/README.md) (index of `docs/phases/phase-1-*.md` … `phase-9-*.md`)
- Project overview: [`.paul/PROJECT.md`](PROJECT.md)
- Design spec: `docs/superpowers/specs/2026-08-06-voxgate-design.md`
- SDD ledger: `.superpowers/sdd/2026-08-06-voxgate-core-platform/progress.md`
