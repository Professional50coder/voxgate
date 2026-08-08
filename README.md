# VoxGate

**A voice-interview compliance gating platform you can add a use case to without touching the code — a durable LangGraph case state machine, explainable AML scoring, and a real-time voice agent on one API**

Hitansh Gopani · 8 August 2026

[Design spec](docs/superpowers/specs/2026-08-06-voxgate-design.md) · [System design](docs/ARCHITECTURE.md) · [Per-phase build docs](docs/phases/README.md) · [Project notes](.paul/PROJECT.md) · [Live demo runbook](docs/demo/DEMO-RUNBOOK.md)

`voxgate` · Python 3.12 · `uv` · 109 test cases

---

**One sentence:** every compliance/onboarding workflow is a checklist that pauses for human input in the middle — VoxGate renders that as a checkpointed state machine an LLM drives conversationally, scores with math you can read, and lets you add the *next* regulation by dropping in a folder.

The thing I built is generic and the first pack is real: **`kyc-uae`** — client onboarding for a Dubai fintech / virtual-asset platform, with sanctions / PEP / adverse-media screening and a 7-feature AML risk scorecard.

---

## SECTION 01 · THE PROBLEM

> Compliance onboarding is the most expensive conversation a fintech has — and it is built like it's 2010.

Every regulated account starts with an interview, a screening, and a decision. In practice that means:

| Pain | Why it hurts |
|---|---|
| **The interview is a loose script.** | Approval depends on fields being asked *in order* and re-asked when the answer is unusable. Rules live in the interviewer's head. |
| **The screening is a black box.** | A sanctions-lookalike name flags "high risk" and nobody can say *why*. |
| **The decision is either instant or a ticket.** | Low risk can auto-approve; medium needs one more question; high needs a human. Routing is hardcoded. |
| **The next regulation is another rewrite.** | AML applies one compliance policy, KYC applies another, a loan-intake a third. Rewiring platform code per policy is why these systems rot. |

## SECTION 02 · THE SYSTEM

A scenario pack is a self-contained folder. The platform never imports a pack by name.

![VoxGate flow](docs/figures/fig-flow.png)

![VoxGate architecture](docs/figures/fig1-architecture.png)

```
Browser /apply ⇄ WebSocket(protobuf) ⇄ Voice agent (Pipecat: Groq STT → LLM → Cartesia TTS)
                                   │   PATCH field updates (live)
                                   │   POST interview-result (resume graph)
                                   ▼
Browser /review ⇄ REST + WebSocket ⇄ Backend (FastAPI + LangGraph) ⇄ Postgres (optional)
```

The three parts:

| Layer | What it does |
|---|---|
| **Scenario packs** | a directory exposing a fixed contract — schema, checks, scoring, prompt. Zero platform-code changes to add one. |
| **LangGraph case state machine** | long-lived, checkpointed workflows that pause (`interrupt()`) for voice or a dashboard click, and survive restarts. |
| **The ML core** | explainable additive log-odds scorecard + a name-screening ensemble built for Gulf-compliance Arabic-name romanization variants. |

## SECTION 03 · THE CASE PIPELINE — a durable state machine

One graph thread per case, pausable at the two interrupt points a real operation needs:

```
   intake ─▶ interview ⏸ ─▶ extract_validate ─▶ ┌─ checks × N (parallel)
                                                 ├─ score ─▶ route
                                                 │   ├─ low        → auto_approve → finalize
                                                 │   ├─ medium     → re-ask the one feature field (max 2)
                                                 │   └─ high / hit → reviewer_gate ⏸ → decision → finalize
```

| Property | Implementation |
|---|---|
| **Human-in-the-loop** | two `interrupt()`s — the interview (fields + confidence) and the review gate (decision). |
| **Re-ask, not brick-wall** | schema validation failures and medium-band risk re-ask only the offending field (`REASK_HINTS`), capped at 2 then forced to review. |
| **Checkpointed by design** | `MemorySaver` in dev, `PostgresSaver` in prod. A case that survived a server restart is rehydrated via `POST /cases/{id}/recover` instead of 404ing. |
| **Audit trail** | every node append-writes `{seq, node, status_before→after, summary, duration_ms}` — a deterministic, replayable log. |
| **Resilience** | each check node runs under `RetryPolicy(max_attempts=2)`; any crash maps to `needs_attention` rather than a hang. |

Status vocabulary (stable across store, API, tests): `awaiting_interview` · `processing` · `awaiting_review` · `approved` · `rejected` · `needs_attention`.

## SECTION 04 · the brains — ML that explains itself

Two cooperating primitives, both **explainable by construction** — every number they emit can be read back as a contribution.

### Name screening — for the romanization problem the Gulf actually has

`sanctions "Muhammad Al-Rashid"` should catch `Mohammed Al Rasheed`. The matcher:

1. **Transliteration variants** — expands a name across the romanization spellings legitimately used in the UAE register,
2. **ensemble scoring** — exact, fuzzy (`rapidfuzz`), and optional embedding similarity (`sentence-transformers`, off by default / no extra install needed) fused into one score.

The scorecard and weighting renormalize when embeddings are absent — the pipeline runs with zero model downloads.

### The additive log-odds scorecard

Each feature gets a weight, each case a score, each contribution a number:

```text
feature             value          weight    contribution
source_of_funds    crypto_trading   1.90    +0.428
flag: sanctions    hit              2.64    +0.351
nationality        SY               0.58    +0.119
product            derivatives      0.42    +0.074
```

- **Bands come from the pack, not the code** — `pack.yaml` declares `thresholds: {low: 0.30, high: 0.65}` — the score's `band` routes the medium re-ask and the high gate.
- **The re-ask picks its question from the scorecard.** the medium-band re-ask targets the *field whose feature contributed most* (`FEATURE_FIELD_HINTS`) — explainability drives UX, not just the audit.
- every round-trip yields a `score_waterfall` + `flagged_checks` handed to the reviewer, so a human never decides "high risk" without the why.

## SECTION 05 · the voice agent — the interview you already run on the phone

A Pipecat pipeline over a browser WebSocket:

```
browser(protobuf) → Groq Whisper STT → LLM(user context) → Groq LLM → Cartesia Sonic TTS → browser
```

| Piece | Role |
|---|---|
| `_TextBridge` | typed input → LLM turn, so a candidate who can't speak is still routed. |
| `LLMContextAggregatorPair` | holds the running conversation, filters incomplete VAD turns. |
| Scenarios | `kyc-interview`, `onboarding`, `support`, `kyc-crypto`, `risk-review`, `general`, `followup`, `multilang` — one transport, many personas. |
| Captions | every spoken line publishes to the case WebSocket stream — the dashboard orb animates live, word by word. |

The interview prompts come from the live pack — `REASK_HINTS` per field — so the *voice* stays in sync with the LangGraph plan even when a field is re-asked. The agent reads just two keys: `GROQ_API_KEY` for the brain, `CARTESIA_API_KEY` for the voice; without a key it falls back to raw transcript/template lines, so the loop always works.

## SECTION 06 · the surfaces — one API, many ways to touch it

```
uv run uvicorn voxgate.service.app:app --port 8000
```

| Endpoint | What it's for |
|---|---|
| `GET /packs` | what gates exist, their fields, and the natural-language prompts. |
| `GET /cases` · `POST /cases` | list / create a case. |
| `PATCH /cases/{id}/fields` | a partially-captured field update (live voice typing). |
| `POST /cases/{id}/interview-result` | resume the LangGraph check after an interview. |
| `POST /cases/{id}/answer` · `/agent-line` · `/agent-greeting` | conversational helpers — interpret a spoken answer, craft the next line. |
| `POST /cases/{id}/decision` | resume the reviewer gate. |
| `POST /cases/{id}/recover` | rehydrate a persistent case after a server restart. |
| `WS /cases/{id}/events` | live state/caption streaming for the dashboard. |
| `WS /cases/{id}/voice?scenario=…` | the realtime voice session (Pipecat). |
| `GET /dashboard` | the reviewer SPA — live case queue, risk waterfall, KPI tiles, WS updates. |

The **reviewer dashboard** is a thin viewer over the same REST+WS surface (implementation: `src/voxgate/service/dashboard.py` + the static `index.html`/`dashboard.js`).

Demo it without any UI — two applicants, one that auto-approves, one that parks for review:

```bash
uv run python scripts/demo_case.py            # clean applicant → auto-approved
uv run python scripts/demo_case.py --risky     # sanctions-lookalike → awaiting_review
```

## SECTION 07 · the KYC-UAE pack — the v1 proof that packs work

`packs/kyc_uae/` is a real, working example of the contract: `pack.yaml` (id, gate_role `Compliance Officer`, thresholds) · `schema.py` (Pydantic fields + extension/`reask_hints`) · `checks.py` (`CHECKS` with clear/review/hit elicitation) · `scoring.py` (7-feature scorecard + re-ask hints) · `prompt.md` (the agent's interview prompt) · `data/` (mock: sanctions, PEP, adverse media — all `"synthetic": true`).

A dedicated conformance suite (`tests/pack_conformance.py`) runs against **every** pack, enforcing the "zero platform-code changes" claim — which is exactly how a second pack (e.g. `loan-intake` or `realestate-aml`) gets added by dropping in a folder.

## SECTION 08 · evidence — what actually runs today

| Claim | Evidence |
|---|---|
| Full fast suite passes | `uv run pytest -q` → **109 passed, 1 skipped** (the Postgres-gated integration one), run in 45 s, **zero paid API keys required**. |
| Durable across restart | `recover_case` integration test passes against a real Postgres (`docker compose up -d`); skips cleanly without `VOXGATE_TEST_DB`. |
| Voice round-trip | browser-driven Pipecat session over WS: Groq STT→LLM→Cartesia TTS, captions live-toggling to the dashboard. |
| Pack contract enforced | conformance suite rejects any pack that violates the `Pack/CheckResult` contract. |

Run it yourself:

```sh
uv sync                        # installs exactly uv.lock's pinned versions
uv run pytest -q               # 109 passed, 1 skipped — no keys, no network
```

Persistent storage (optional):

```sh
docker compose up -d
# PowerShell
$env:VOXGATE_TEST_DB = "postgresql://voxgate:voxgate@localhost:5433/voxgate"
uv run pytest tests/integration -v
```

## SECTION 09 · Repository

```
src/voxgate/
  config.py            Settings — DB DSN, packs dir (repo-root-relative, no hardcoded paths)
  ml/                  explainable core: scorecard.py, name_match.py, variants.py
  packs/               Pack/CheckResult contract (base.py), dynamic loader (loader.py)
  graph/               LangGraph case state machine (state.py, build.py)
  service/             FastAPI surface: app.py · store.py · runner.py · events.py · dashboard.py
  service/voice/       Pipecat voice agent (agent.py) + protobuf wire format
packs/kyc_uae/         the v1 scenario pack — schema, checks, scoring, prompt, data
docs/phases/           one detailed doc per build phase; README.md indexes them
scripts/demo_case.py   CLI walk-through of the two decision paths
```

Dependency policy: `pyproject.toml` declares ranges; `uv.lock` + autogenerated `requirements.txt` are the tested, pinned snapshot. `requirements.txt` is regenerated via `uv export` — never hand-edit it.

## SECTION 10 · what I'd do next

1. **A second pack in the same session** — `realestate-aml` (~5 files) to prove the conformance suite is the contract, not the optimism.
2. **Multi-tenant auth + HTTPS** at the API layer before anyone touches real applicant data.
3. **TURN/egress hardening + call recording** for the voice agent (the transcript is already a compliance artifact).
4. **Latency budget** on the voice path (STT→LLM→TTS p95) measured against a `model`-based SLO — the same treatment T3N got.

---

**Hitansh Gopani** · hitansh.gopani@somaiya.edu · [gopanihitansh5](github.com/gopanihitansh5-collab)

All datasets are mock/synthetic and marked `"synthetic": true`. No real personal information is stored; the voice agent is a demonstration stack (Groq/Cartesia) to be swapped for a self-hosted pipeline in a regulated deployment.