# VoxGate — Project

## What this is

VoxGate is a **pack-driven voice-interview compliance gating platform** — a portfolio-grade showcase (per the design spec's stated purpose) combining:

1. **LangGraph durable execution** — long-lived, checkpointed case state machines that pause for human input (`interrupt()`), whether that input arrives by voice or by dashboard click, and survive process restarts.
2. **Real AI/ML engineering** — explainable additive log-odds scorecards, ensemble fuzzy/embedding name matching (built for Gulf-compliance Arabic-name romanization variants), and a confidence-driven extraction/re-ask loop.

The platform is **scenario-generic**: each compliance/onboarding use case is a self-contained *scenario pack* — a directory under `packs/<pack_id>/` exposing a fixed module contract (schema, checks, scoring, prompt). Adding a pack is designed to require zero changes to platform code; a generic conformance test suite (`tests/pack_conformance.py`) enforces that claim.

**v1 pack:** `kyc-uae` — client onboarding for a Dubai fintech / virtual-asset platform (VARA/DFSA-flavored), with sanctions/PEP/adverse-media screening and a 7-feature AML risk scorecard. Two more v1 packs (`loan-intake`, `claim-fnol`) and two v2-roadmap packs (`realestate-aml`, `patient-intake`) are defined in the design spec but not yet built as of this documentation pass.

All data is **mock/synthetic**, explicitly marked (`"synthetic": true` at the top level of every dataset file). Zero paid API keys are required to run the test suite.

Full design spec: [`docs/superpowers/specs/2026-08-06-voxgate-design.md`](../docs/superpowers/specs/2026-08-06-voxgate-design.md).

## Architecture overview

Three deployables + Postgres (the only shared infrastructure), per the design spec:

```
Browser /apply ⇄ WebRTC ⇄ Bot runner (Pipecat: STT → Grok → TTS)      [not yet built]
                               │  PATCH field updates (live)
                               │  POST interview-result (resume graph)
                               ▼
Browser /review  ⇄ REST+WS ⇄ Backend (FastAPI + LangGraph + PostgresSaver) ⇄ Postgres
```

This SDD ledger (`2026-08-06-voxgate-core-platform`) covers the **backend core** only: the pack system, the LangGraph case state machine, and the FastAPI service. The voice bot (Pipecat) and the React dashboard are separate, later plans (per the design spec's "4-plan roadmap") and are out of scope here.

Graph topology (one thread per case; `⏸` = `interrupt()`):

```
intake → interview ⏸ → extract_validate → [pack check nodes, parallel fan-out]
       → score → route ─(low)──────→ auto_approve → finalize
                       ─(needs info)→ interview (re-ask loop, max 2)
                       ─(high/hits)─→ reviewer_gate ⏸ → decision → finalize
```

## How phases map to modules

| Phase | Module(s) | Role |
|---|---|---|
| 1 | `src/voxgate/config.py` | `Settings` — DB DSN, packs dir |
| 2 | `src/voxgate/ml/variants.py`, `name_match.py` | Name screening ensemble |
| 3 | `src/voxgate/ml/scorecard.py` | Explainable additive log-odds scoring |
| 4 | `src/voxgate/packs/base.py`, `loader.py` | Pack contract + dynamic loader |
| 5 | `packs/kyc_uae/**` | First real scenario pack |
| 6 | `src/voxgate/graph/state.py`, `build.py` | LangGraph case state machine |
| 7 | `src/voxgate/service/store.py`, `events.py`, `runner.py` | Case index, pub/sub, orchestrator |
| 8 | `src/voxgate/service/app.py` | FastAPI REST + WebSocket surface |
| 9 | `tests/integration/`, `scripts/demo_case.py` | Postgres durability proof + demo |

Detailed per-phase documentation, including real quoted signatures, design rationale, test evidence, and review history, lives in [`docs/phases/`](../docs/phases/README.md) — one file per phase, indexed there.

## How to run tests

```
uv sync
uv run pytest              # fast suite — no external services, zero paid keys
```

Postgres-dependent integration tests (Phase 9, once built) are opt-in:

```
docker compose up -d
$env:VOXGATE_TEST_DB = "postgresql://voxgate:voxgate@localhost:5433/voxgate"
uv run pytest tests/integration -v
```

Without `VOXGATE_TEST_DB` set, integration tests skip cleanly rather than failing.

## Constraints (binding across the whole ledger)

From `.superpowers/sdd/2026-08-06-voxgate-core-platform/global-constraints.md`:

- **No git in this folder** (user request) — no commits, no `git init`.
- Dev machine is **Windows 11 / PowerShell**; always invoke tools through `uv run …` from the repo root.
- **Zero paid keys**: no LLM/STT/TTS calls anywhere in this ledger's scope. The sync LangGraph API (`.invoke`/`.get_state`) is used everywhere — no asyncio plumbing needed in tests.
- All datasets are **mock/synthetic**, every dataset file carries `"synthetic": true` at its top level.
- Scorecard routing thresholds come from `pack.yaml` (`kyc-uae`: low `0.30`, high `0.65`) — **never hard-coded** in platform code.
- Re-ask loop is capped at **2** (`MAX_REASKS = 2` in `graph/build.py`); after the cap, cases go to the reviewer gate.
- Status vocabulary (exact strings, used by store, API, and tests): `awaiting_interview`, `processing`, `awaiting_review`, `approved`, `rejected`, `needs_attention`.
- Embeddings are optional everywhere: `NameMatcher(embedder=None)` must work (weights renormalize); `sentence-transformers` is an optional extra, never imported at module top level.

## Repo location

`PPC_Tech/voxgate` — plain folder, no git repo in this SDD build session (per the constraint above; may be initialized/pushed to the Pitchperfektcollective GitHub org later per the design spec §8).
