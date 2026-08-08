# VoxGate — Voice-Driven Durable Workflow Orchestrator

**Date:** 2026-08-06
**Status:** Approved design, pending implementation plan
**Owner:** Hitansh Gopani / Pitch Perfekt Collective

## 1. What this is

VoxGate is a portfolio-grade showcase of two things working together:

1. **LangGraph durable execution** — long-lived, Postgres-checkpointed state machines that pause for humans (via `interrupt()`) and survive restarts, with human input arriving either by **voice** or by **dashboard click**.
2. **Real AI/ML engineering** — explainable scoring models, ensemble fuzzy/embedding name matching, confidence-driven agent behavior, and pipeline telemetry, all visualized.

A **Pipecat** voice agent conducts a structured intake interview in the browser (WebRTC); a **LangGraph** backend runs the durable case workflow; a **React dashboard** gives human reviewers a visualization-rich approval surface.

The platform is **scenario-generic**: each use case is a self-contained *scenario pack*. v1 ships three packs; two more are roadmap items that prove extensibility.

**Primary purpose:** portfolio showcase (screen recording + GitHub repo + live demo). All datasets are mock but realistically shaped, clearly labeled synthetic. Target market relevance: Dubai/UAE financial industry.

## 2. Scenarios

### v1 packs

| Pack | Industry story | Checks | Scoring model | Human gate |
|---|---|---|---|---|
| `kyc-uae` | Client onboarding for a Dubai fintech / virtual-asset platform (VARA/DFSA flavor) | Sanctions (UN Consolidated, OFAC SDN, UAE Local Terrorist List — all mocked), PEP, adverse media | AML risk scorecard (additive log-odds) | Compliance officer |
| `loan-intake` | Personal loan application at a UAE bank | Mock credit bureau pull, affordability/DTI checks | Credit scorecard (log-odds points, feature contributions) | Underwriter |
| `claim-fnol` | Insurance first-notice-of-loss by voice | Policy validation, coverage check | Fraud anomaly score (inconsistency + claim-pattern features) | Claims adjuster |

### v2 roadmap packs (defined, not built)

- `realestate-aml` — Dubai DNFBP real-estate party onboarding (reuses kyc-uae screening machinery).
- `patient-intake` — pre-visit intake with triage scoring and nurse gate.

### Scenario pack interface

A pack is a directory under `packs/<pack_id>/` containing:

- `pack.yaml` — display name, industry, routing thresholds, gate role name.
- `schema.py` — Pydantic model of the fields the interview must collect (types, validation rules, per-field re-ask hints).
- `prompt.md` — the voice agent's interview system prompt.
- `checks.py` — the pack's check-node implementations (must conform to the `CheckNode` protocol: `case_state -> CheckResult`).
- `scoring.py` — scorecard definition: feature extractors + weights + threshold bands (must conform to the `Scorecard` protocol, returning per-feature contributions).
- `data/` — mock datasets (sanctions lists, bureau records, policies…).

The graph, API, bot runner, and dashboard consume packs only through these interfaces. Adding a pack requires **zero changes** to platform code — that claim is tested (see §9).

## 3. Architecture

Three deployables + Postgres (the only shared infrastructure). Approach: **interview as a paused graph node** — the voice layer is just another human-input source, architecturally identical to the reviewer's approve button.

```
Browser /apply ⇄ WebRTC ⇄ Bot runner (Pipecat: STT → Grok → TTS)
                               │  PATCH field updates (live)
                               │  POST interview-result (resume graph)
                               ▼
Browser /review  ⇄ REST+WS ⇄ Backend (FastAPI + LangGraph + PostgresSaver) ⇄ Postgres
```

### 3.1 Backend — FastAPI + LangGraph

Owns the graph, checkpointing, business data, and pack registry.

Graph topology (one thread per case; `⏸` = `interrupt()`):

```
intake → interview ⏸ → extract_validate → [pack check nodes, parallel fan-out]
       → score → route ─(low)──────→ auto_approve → finalize
                       ─(needs info)→ interview (re-ask loop, max 2)
                       ─(high/hits)─→ reviewer_gate ⏸ → decision → finalize
```

API surface:

- `GET /packs` — available scenario packs.
- `POST /cases` `{pack_id}` — create case; graph runs to the interview interrupt; returns case id + WebRTC room info.
- `PATCH /cases/{id}/fields` — bot streams field extractions during the call (live dashboard).
- `POST /cases/{id}/interview-result` — bot submits final payload; resumes graph.
- `POST /cases/{id}/decision` `{approve|reject|request_info, note}` — reviewer resumes gate.
- `GET /cases`, `GET /cases/{id}` — queue and full case state (score breakdown, match candidates, graph position, history).
- `WS /cases/{id}/events` — live state/telemetry stream for the dashboard.

Checkpointing: `PostgresSaver`. LLM-touching nodes get a retry policy (exponential backoff, 3 attempts); terminal failure parks the case in `needs_attention`, visible in the queue.

### 3.2 Bot runner — Pipecat

One process; one pipeline per call: **SmallWebRTC transport → STT → Grok (interview prompt + function tools) → TTS**.

- LLM: xAI Grok via its OpenAI-compatible API (also used by backend graph nodes).
- STT: Deepgram (free credits) → fallback **local faster-whisper (CPU/int8)**.
- TTS: Cartesia (free tier) → fallback **local Piper/Kokoro**.
- Provider selection by config with automatic fallback when a key is missing or a provider errors mid-session; the serving tier is logged and surfaced in telemetry.
- Function tools: one `record_field(name, value, confidence)`-style tool generated from the pack's schema, plus `complete_interview()`. Low-confidence fields cause the agent to re-ask in the same call.
- Telemetry per turn: STT latency, LLM time-to-first-token, end-to-end turn latency — posted to the backend with field updates.

### 3.3 Frontend — React + Vite

Two routes, one build:

- **`/apply`** — pack picker, then Pipecat React client: mic UI, live transcript, and a "fields captured" panel that fills as the applicant speaks.
- **`/review`** — reviewer surface (role label comes from the pack: officer / underwriter / adjuster): case queue (risk badges, pack filter, `needs_attention` flag); case detail with:
  - **risk waterfall** — per-feature scorecard contributions;
  - **match-candidate bars** — per-list-entry ensemble score breakdown (kyc-uae);
  - **live graph-state diagram** — which node the case is at, interrupts highlighted;
  - **turn-latency chart** + serving-tier indicator;
  - Approve / Reject / Request-more-info actions.

Charts follow the `dataviz` skill's system. Language: English (Arabic voice via Deepgram/Cartesia multilingual is a stretch goal, not v1).

## 4. AI/ML formulations

1. **Name screening ensemble (kyc-uae).** Arabic-name romanization variants (Mohammed/Muhammad/Mohamed/Mohd) are why naive matching fails in Gulf compliance. Query name → transliteration-variant expansion (curated variant table) → per-list-entry score = weighted combination of **Jaro-Winkler + token-set ratio + embedding cosine** (local sentence-transformers model, no API), corroborated by DOB/nationality. Output: ranked candidates with per-component scores and band (clear / review / strong match).

2. **Explainable scorecards (all packs).** Additive log-odds: `score = σ(Σ wᵢ·xᵢ)` with pack-defined feature extractors and weights. Deterministic, monotonic, and fully attributable — the reviewer sees *why* the score is 0.74. Thresholds define the three routing bands. kyc-uae features: FATF nationality risk, PEP flag, max sanctions similarity, source-of-funds category, product risk, residency. loan-intake: DTI, income stability, bureau signals. claim-fnol: report-delay, claim/premium ratio, narrative-inconsistency flags from extraction.

3. **Extraction confidence loop.** Per-field confidence from the LLM's function calls; below-threshold fields trigger an in-call re-ask. Validation node checks plausibility (DOB ranges, ISO country codes); implausible data routes back to interview with targeted re-ask instructions, capped at 2 loops before forced reviewer review.

4. **Voice pipeline telemetry.** Latency metrics per turn, per provider tier, charted on the dashboard; provider fallback events are first-class data.

## 5. Data flow (one case, happy-ish path)

1. Applicant picks a pack, clicks Start → `POST /cases` → graph parks at `interview`.
2. Bot runner joins the WebRTC room, interviews; fields stream in live (`PATCH`).
3. Bot calls `complete_interview` → `POST interview-result` → graph resumes: validation → parallel checks → scorecard → route.
4. Low risk → auto-approve. Otherwise the case parks at `reviewer_gate` — minutes or days, surviving restarts.
5. Reviewer inspects the visualizations, decides; graph resumes to `finalize`. Full history + every score breakdown retained as the audit trail.

## 6. Error handling

- **Dropped call mid-interview:** graph never left the interrupt; new call resumes with prior fields pre-loaded into agent context.
- **Cloud voice provider fails mid-session:** pipeline reconnects on the local fallback tier; the switch is telemetry, i.e. a demo feature.
- **Grok/API failure in graph nodes:** retry ×3 with backoff → `needs_attention` state; never a silently lost case.
- **Backend restart:** checkpointer resumes all cases exactly where they were (deliberately demoed: kill server on camera, restart, approve the case).
- **Bad/adversarial input:** plausibility validation + capped re-ask loop → forced reviewer review.

## 7. Configuration

Single `.env` + `config.yaml`: provider keys (all optional — absent key = local tier), Postgres DSN, pack directory. Everything runs with **zero paid keys** (Grok free tier + local STT/TTS) at reduced voice quality.

## 8. Repo & deployment

- Location: `PPC_Tech/voxgate` — plain folder for now, no git repo (per user request; can be initialized/pushed to the Pitchperfektcollective org later). Python backend/bot (uv), pnpm/npm frontend, `docker-compose.yml` for Postgres (+ optional full-stack compose).
- Deploy target: existing PPC VPS. Not in v1 scope beyond compose files.
- `.paul/PROJECT.md` + `.paul/STATE.md` maintained per PPC convention.

## 9. Testing

- **Graph tests (bulk of the suite):** pytest, in-memory checkpointer, no audio/network. Every route: auto-approve, hit → gate → approve/reject, re-ask loop cap, needs_attention, resume-after-restart.
- **ML tests:** name-matcher golden cases (variant names must match; similar-but-different must not), scorecard determinism + monotonicity (adding a risk factor never lowers risk), threshold edges.
- **Pack conformance tests:** a generic suite every pack must pass (schema round-trip, checks protocol, scorecard protocol) — this is what enforces "adding a pack touches no platform code".
- **Bot tests:** extraction tools driven by scripted text transcripts (no audio); manual end-to-end voice smoke checklist.
- **API tests:** FastAPI TestClient over the case lifecycle.

## 10. Out of scope (v1)

- Real KYC/bureau/insurance provider integrations (mocked by design).
- Telephony (Twilio) — browser WebRTC only.
- Arabic-language voice (stretch), auth/multi-tenancy, production hardening, `realestate-aml` and `patient-intake` packs (v2 roadmap).
