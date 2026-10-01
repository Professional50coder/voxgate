# VoxGate

**Voice interviews for regulated intake. The agent holds the conversation, the questions stay exactly as approved, and a person makes the call with a full record of why.**

- Web app: **https://voxgate-web.vercel.app**
- API: **https://voxgate-api.vercel.app** (`GET /health`, `GET /packs`, `GET /stats`)

### At a glance

- **AI runs the conversation, you own the questions.** Regulated questions are read verbatim from a pack. AI handles everything around them.
- **The output is an outcome, not a transcript.** Each call ends with validated fields, check results and a scored, explained result.
- **People decide.** The workflow pauses for a named reviewer, survives restarts, and records every decision.

### Contents

1. [The problem we solve](#the-problem-we-solve)
2. [Why we built it](#why-we-built-it)
3. [What VoxGate does](#what-voxgate-does)
4. [Use cases](#use-cases)
5. [Product tour](#product-tour)
6. [How it works](#how-it-works)
7. [Architecture](#architecture)
8. [Intelligence and models](#intelligence-and-models)
9. [Design principles](#design-principles)
10. [Feature matrix](#feature-matrix)
11. [Measured performance](#measured-performance)
12. [Trust, data handling and limits](#trust-data-handling-and-limits)
13. [Where VoxGate stands in the market](#where-voxgate-stands-in-the-market)
14. [Tech stack](#tech-stack)
15. [Repository layout](#repository-layout)
16. [Running locally](#running-locally)
17. [Testing](#testing)
18. [Deploying](#deploying)
19. [Roadmap](#roadmap)

---

## The problem we solve

**Who has it.** Compliance, onboarding, intake and screening teams in banking, insurance, healthcare, lending, property and recruiting. Every new customer, claimant, patient, borrower, tenant or candidate has to answer the same set of questions before anyone can act.

**What it costs them today.**

- **Staff time.** Skilled people spend their day reading scripts aloud and typing notes.
- **Inconsistent records.** Two interviewers capture the same answer two different ways.
- **Reconstruction work.** Reviewers re-read or re-listen to calls to rebuild the facts before they can decide.
- **Slow onboarding.** Applicants wait for a slot with a person, and some give up.
- **Audit exposure.** A paraphrased regulated question, or a decision nobody wrote down, is a finding waiting to happen.

**What VoxGate delivers.** Every applicant is interviewed the same compliant way, their answers become checked structured data, the risk comes with its reasons, and only the cases that need judgment reach a person, with a full record of who decided and why.

---

## Why we built it

Regulated intake still runs on scripts and notes. An officer reads the approved questions, types what they hear, and passes the file on. The record is only as good as the person typing it. When the case reaches a reviewer, the reviewer often goes back to the recording to work out what was actually said.

Voice AI looks like the obvious fix, and for customer service it often is. For regulated intake it creates three new problems. A model that rephrases a KYC or medical question is no longer asking the approved question. A transcript is not a decision: someone still has to extract the facts, check them and weigh them. And a call that ends in an automated outcome with no named decision-maker leaves no usable audit trail.

VoxGate splits the work differently. **Let AI handle the conversation**: greetings, small talk, "why do you need this?", corrections, refusing a card number. **Keep the questions verbatim** and **the decision human.** **Make every number explainable**, so a reviewer or an auditor can see exactly why a case scored the way it did.

Every section below ties back to that split, and to the part of the problem it removes.

---

## What VoxGate does

| Capability | What it means | Problem it removes |
|---|---|---|
| **Verbatim questions** | Regulated questions come from the pack and are read word for word. No model writes or rewords them. | Audit exposure from paraphrasing |
| **Natural conversation** | AI handles small talk, process questions, corrections, off-topic answers and refusing card numbers or PINs. | Staff time on scripted calls |
| **Structured capture** | Spoken answers become validated fields as the caller speaks. Extraction is grounded: it can only use words the caller said. | Inconsistent records |
| **Explainable scoring** | An additive log-odds scorecard. Every point is attributed to a field or a check. | Reviewers rebuilding the story |
| **Human decision, recorded** | Clean, low-risk cases auto-approve. Hits and high-risk cases stop for a reviewer, whose name is stored with the decision. | Undocumented decisions |
| **Durable cases** | Checkpointed in Postgres. A restart mid-case resumes at the exact step. | Lost work, broken audit trail |
| **Available on demand** | Applicants start the interview from a link, without waiting for a slot. | Slow onboarding and drop-off |
| **New use case = new pack** | A pack is a folder. Platform code never changes, and a conformance suite enforces this. | Cost of covering each new workflow |

---

## Use cases

Nine packs ship today. Four have a named voice agent with its own persona and voice.

| Pack | Use case | Reviewer | Agent |
|---|---|---|---|
| `kyc-uae` | UAE Fintech KYC Onboarding, with sanctions, PEP and adverse-media screening | Compliance Officer | Lucy |
| `patient-intake` | Clinic Patient Intake | Triage Nurse | Iris |
| `sales-discovery` | B2B Sales Discovery Call | Sales Manager | Skylar |
| `recruit-screen` | Candidate Phone Screen | Hiring Manager | Victoria |
| `claim-fnol` | Insurance First Notice of Loss | Claims Adjuster | |
| `loan-intake` | Consumer Loan Application | Credit Officer | |
| `tenant-screening` | Rental Tenant Screening | Letting Manager | |
| `realestate-lead` | Real Estate Buyer Qualification | Listing Agent | |
| `support-triage` | Customer Support Triage | Support Lead | |

---

## Product tour

Each surface proves one part of the claim.

### `/` Landing: show the outcome, not just the voice

- **Industry agent picker** in the hero. Each card plays the agent's real voice, with a waveform driven by the actual audio.
- **Trust strip** listing only what the product backs today: a person makes every judgment call, full audit trail, factor-by-factor risk score, card numbers and PINs refused, demo on synthetic data.
- **Recorded sample calls.** The transcript follows the audio turn by turn.
- **Interactive reviewer console sample.** A synthetic case the visitor can decide, because a buyer is buying the review step.
- **ROI calculator** that runs on numbers the visitor sets.

### `/how-it-works` The walkthrough, narrated

- **Lucy, the site guide.** Tap to talk, hands-free, interruptible. She can narrate each section. She can only take actions from a fixed list; anything else is dropped.
- **Animated pipeline** of a case from first word to decision.
- **Agent gallery** with each persona and voice.
- **Live rules playground.** Say something off topic or read out a card number, and see which rule fired.

### `/apply` The applicant's interview

*Solves inconsistent records, in front of the applicant.*

- The agent speaks in its own voice and asks the pack's questions.
- A **live capture panel** fills in each field as it is understood.
- A **result card** at the end shows the outcome with factor-by-factor reasons.

### `/console` The reviewer

*Solves reconstruction work and undocumented decisions.*

- A queue of cases waiting for judgment, with fields, check results, score breakdown and transcript, plus approve or reject.

### `/dashboard` Operations

- Per-agent analytics, full-text search across interview transcripts, and the agent store.

### `/agents` Build an agent

*Solves the cost of each new workflow.*

- Describe the agent in plain English. VoxGate drafts a pack spec, a person reviews the questions, then publishes it.

**On motion.** Animations are tied to real events: fields landing, score bars filling, the waveform following real audio. They respect `prefers-reduced-motion`.

---

## How it works

### One answer, end to end

1. The applicant speaks. The browser's speech recognition turns it into text.
2. The page sends the text to `POST /packs/{pack_id}/extract`.
3. **Agent rules** run first: the pack's sensitive terms, blocked topics and process answers.
4. **Platform patterns** run next: small talk, process questions, corrections, card numbers and PINs, off-topic.
5. If the turn is an answer, **grounded extraction** with Groq maps it to the field, and the pack schema validates it. Without a key, keyword matching does this.
6. The API returns the field (or the right non-answer reply) and the next question, worded exactly as the pack defines it.
7. `/tts` streams the agent's line in its Cartesia voice.

### One case, end to end

1. The captured fields are submitted to `POST /cases/{id}/interview-result`.
2. The pack's **checks** run. For `kyc-uae` that is sanctions, PEP and adverse-media name screening.
3. The **scorecard** places the case in a low, medium or high band.
4. Routing:
   - Low band, no hits: **auto-approve**.
   - Medium band: **re-ask** the field behind the largest risk contribution, up to a limit, then send to review.
   - High band, any check hit, or a forced review: **reviewer gate** (`interrupt()`).
5. The reviewer decides via `POST /cases/{id}/decision`. Their named key is recorded with the decision.
6. The transcript session is closed with a summary. A deterministic template is always written; with a key, Groq adds the narrative paragraph. Counts and captured fields never come from the model.

---

## Architecture

```mermaid
flowchart LR
    U["Browser / phone"] --> W["Next.js web app<br/>(Vercel)"]
    W -- "/api/* proxy" --> A["FastAPI API<br/>(Vercel)"]

    subgraph API["API"]
        A --> B["Dialogue brain<br/>rules first, then Groq"]
        A --> G["LangGraph case workflow<br/>human-in-the-loop gate"]
        A --> T["TTS<br/>Cartesia sonic-3"]
        G --> S["Checks + scorecard<br/>(from the pack)"]
    end

    A --> P[("Neon Postgres<br/>cases, checkpoints, transcripts,<br/>agent store, events, quota")]
    G --> P

    V["Voice worker (separate process)<br/>Pipecat: Silero VAD, Whisper STT,<br/>Kokoro or Cartesia TTS"] -- "REST" --> A
    K["packs/*/pack.yaml<br/>questions, persona, thresholds"] --> A
```

### Components

| Component | Role |
|---|---|
| **Web app** (`apps/web`) | Next.js site and applicant interview. Proxies `/api/*` to the API, so the browser sees one origin and there is no CORS setup. |
| **API** (`src/voxgate/service`) | FastAPI: cases, extraction, TTS, assistant, transcripts, analytics, agent store. Rate limiting and quota middleware. |
| **Dialogue brain** (`src/voxgate/dialogue`) | Turn understanding shared by the browser and the voice worker, so a rule holds on both. |
| **Case workflow** (`src/voxgate/graph`) | LangGraph state machine: checks, score, route, re-ask, reviewer gate, finalize. |
| **Packs** (`packs/`) | Questions, persona, thresholds, checks and scoring for each use case. |
| **Voice worker** (`src/voxgate/voice`) | Separate process because it holds speech models in memory. Drives the same REST surface as the browser. |

Web and API deploy automatically from `main`.

### Data model (Postgres)

| Table | Holds |
|---|---|
| `cases` | Case index per tenant: pack, workflow thread, status, payload, timestamps |
| LangGraph checkpoint tables | Workflow state, so a case resumes after a restart |
| `events`, `event_seq` | Durable event stream behind the live view |
| `runs` | Workflow run bookkeeping |
| `transcript_sessions`, `transcript_turns` | Interview transcripts. Turns carry a generated `tsvector` with a GIN index for full-text search. |
| `published_packs` | Agent store: published agents saved as specs and regenerated on every instance |
| `quota_usage` | Daily usage per caller for paid endpoints |

Schema changes are managed with Alembic.

### Main API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /cases`, `GET /cases/{id}` | Open and read a case |
| `POST /cases/{id}/interview-result` | Submit captured fields, which runs checks and scoring |
| `POST /cases/{id}/decision` | Reviewer decision (operator key) |
| `GET /cases/{id}/events` (HTTP and WebSocket) | Live case updates |
| `POST /packs/{pack_id}/extract` | Turn a spoken answer into a field |
| `POST /assistant` | Site voice assistant (closed action set) |
| `GET/POST /tts` | Agent voice audio |
| `POST /cases/{id}/transcripts`, `GET /transcripts/search` | Store transcripts; full-text search (operator) |
| `POST /packs/draft`, `POST /packs/publish`, `GET /store` | Draft and publish agents; list the agent store |
| `GET /analytics` (operator), `GET /stats` (public) | Per-agent analytics; public counts |
| `GET /health`, `GET /health/ready` | Liveness and readiness |

---

## Intelligence and models

The system is hybrid on purpose. Deterministic code handles anything that must not vary. Models handle what needs language understanding, inside fixed limits.

| Job | Model / engine | Why |
|---|---|---|
| Extraction, classification, drafting (strict tier) | Groq `openai/gpt-oss-120b`, `openai/gpt-oss-20b` | Support `json_schema` with `strict: true`, so the provider enforces the output shape. |
| Same jobs (lenient tier) | Groq `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` | Used when every strict model is rate-limited. The schema is then enforced in our code. |
| Key and model fallback | Model-major, key-minor walk | Groq limits apply per key **and** per model, so N keys × M models is the real headroom. Dead keys (401/403) are skipped. Rate-limited keys (429) cool down and move to the back of the line. |
| Latency setting | `reasoning_effort: low` | Short, bounded tasks. Extra reasoning adds delay, not accuracy. |
| Session summaries | Groq, over a deterministic template | The model writes the narrative paragraph only. Counts and fields come from the record. |
| Site assistant ("Lucy") | Groq, with a closed action set; keyword FAQ offline | It can explain and navigate, never act outside the list. |
| Agent voices | Cartesia sonic-3, streamed MP3 | Fast first audio and natural delivery. Lucy (British), Iris (American), Skylar (American), Victoria (British). Kavita (Indian English) is the shared fallback. |
| In-browser speech-to-text | Browser Web Speech API | Nothing for the applicant to install. Note: the browser sends audio to its vendor's speech service. |
| Voice worker | Pipecat with Silero VAD, Whisper (faster-whisper) STT, Kokoro local TTS or Cartesia | Runs fully on your machine when audio must not leave it. |
| Name screening | Ensemble of Jaro-Winkler and token-set similarity (RapidFuzz), optional sentence-transformer embeddings | Tuned for Arabic name romanisation, where one name has many valid spellings. |
| Risk scoring | Additive log-odds scorecard | Every contribution is attributable and shown. |

### Per-agent personas

Personas are data in `pack.yaml`. The same rules apply in the browser and in the voice worker.

```yaml
agent:
  name: Lucy
  greeting: "Hi, I'm Lucy. I'll take you through a short identity check for your new account. It takes about three minutes."
  voice: {primary: <cartesia-voice-id>, fallback: <cartesia-voice-id>, speed: 0.95}
  max_smalltalk: 1
  blocked_topics: [investment advice, crypto tips, stock tips, loan offer]
  sensitive_terms: [iban, account number, emirates id number]
  process_answers:
    purpose: "UAE regulations require us to verify every new customer before an account is opened. A compliance officer reviews your answers."
    privacy: "Your answers go only to our compliance team and are kept as your regulatory record."
```

---

## Design principles

Each principle is a decision, the reason for it, and what it costs.

### 1. Regulated questions are read verbatim

*Solves: audit exposure from paraphrased questions; inconsistent interviews.*

- **Decision.** Question text lives in the pack (`REASK_HINTS` in `schema.py`). No model writes or rewords it at runtime.
- **Why.** The approved wording is the compliance artefact. If the wording can change per call, nothing else in the record can be trusted.
- **Trade-off.** The questions sound slightly less natural than a free-form bot. The conversational layer around them closes most of that gap.

### 2. Two-layer understanding: rules first, model second

*Solves: inconsistent records; the risk of a model inventing an answer.*

- **Decision.** Every caller turn goes through deterministic rules first: the agent's own rules, then shared platform patterns. They run in under 1 ms. A model is used only for turns the rules cannot place, and only to pick from a closed set of labels. Extraction is grounded: it can only use words the caller said, and the schema validates the result.
- **Why.** Sensitive data and off-topic requests must be caught the same way every time, and a caller cannot talk a rule out of being a rule. Grounding turns a bad extraction into a re-ask, never an invented fact.
- **Trade-off.** Rules need maintaining per pack. They live in `pack.yaml`, so that is a data change, not a code change.

### 3. An additive scorecard, not a classifier

*Solves: reviewers rebuilding the story; unexplained outcomes.*

- **Decision.** Risk is an additive log-odds scorecard. Each feature contributes a signed amount, and every contribution is shown.
- **Why.** A reviewer, a regulator or the applicant can follow the arithmetic. A bare score with no reasons would not survive an audit.
- **Trade-off.** Less expressive than a learned model. For intake gating, explainability is worth more than marginal accuracy.

### 4. A durable workflow with a human gate

*Solves: undocumented decisions; lost work.*

- **Decision.** Each case is a LangGraph workflow. When judgment is needed it calls `interrupt()` and waits for a reviewer. State is checkpointed to Postgres, so a restart mid-case resumes at the exact step.
- **Why.** A gate that disappears when a server restarts is not a gate. The decision, the reviewer's name and the inputs they saw are stored together.
- **Trade-off.** Production needs Postgres. Locally the system falls back to in-memory storage.

### 5. A new use case is a new folder

*Solves: the cost of covering each new workflow.*

- **Decision.** A pack is data (`pack.yaml`: questions, thresholds, persona) plus a small generated Python module (schema, checks, scoring). Platform code never imports a pack by name. `tests/pack_conformance.py` checks every pack against the same contract.
- **Why.** "Add a vertical without touching the platform" is only true if a test catches the day it stops being true.
- **Trade-off.** Packs are files, so on a serverless host they need a home. Published agents are stored as specs in Postgres and regenerated on every instance.

### 6. Graceful degradation everywhere

*Solves: an intake channel that goes silent when a dependency fails.*

- **Decision.** Every external dependency has a fallback.
  - No Groq key: offline rules, keyword extraction and a keyword FAQ for the site assistant.
  - Voice: the agent's primary Cartesia voice, then its fallback voice, then the browser's voice (or Kokoro in the voice worker).
  - Database: in-memory locally when `VOXGATE_DATABASE_URL` is unset.
- **Why.** A silent channel loses applicants. Weaker but working beats down.
- **Trade-off.** More code paths. CI exercises them, because CI runs with no keys.

---

## Feature matrix

| Area | What it does |
|---|---|
| **Conversation** | Per-pack personas with greeting and voice; small talk within a budget (`max_smalltalk`); answers to process questions ("why?", "who sees this?"); corrections; off-topic redirect; refusal of card numbers, PINs and pack-specific sensitive terms |
| **Understanding** | Agent rules, then platform patterns, then a model only for what is left; grounded extraction validated against the pack schema; re-ask in the pack's own wording when validation fails |
| **Voice** | Cartesia primary and fallback voice per agent; streamed audio; browser or Kokoro fallback; site-wide assistant that is hands-free and interruptible |
| **Workflow and decisions** | LangGraph state machine; Postgres checkpoints; auto-approve, targeted re-ask or reviewer gate; named reviewer on every decision; live event stream over WebSocket |
| **Data and search** | Transcripts in Postgres with full-text search; session summaries; per-agent analytics; public counts; agent store regenerated on every instance |
| **Operations and security** | Rate limiting, including the paid endpoints (`/tts`, `/assistant`, extraction, drafting); daily quota per caller; named operator keys (`VOXGATE_API_KEYS="name:key,..."`); applicant PII reads are operator-only; secrets stripped of invisible BOMs and whitespace on load; liveness and readiness checks |

---

## Measured performance

| Step | Latency |
|---|---|
| Deterministic understanding (rules) | 0.1 to 0.5 ms per turn |
| Voice, time to first audio (streamed) | ~200 ms |
| Site assistant reply | ~550 ms |
| Model-based extraction | ~0.5 to 1 s |

Measured on a development machine. These are not SLAs.

---

## Trust, data handling and limits

What the code does today:

- Regulated questions come from the pack and are never generated.
- Card numbers, PINs and each pack's `sensitive_terms` are recognised, and the caller is asked not to share them.
- Each scorecard contribution is attributed to a field or a check.
- Hits and high-risk cases stop at a reviewer gate, and decisions record the reviewer's name.
- Operator endpoints and applicant PII reads need an operator key. If `VOXGATE_API_KEYS` is unset they are open, which is only acceptable for a demo.

Where data goes:

- The hosted demo sends the agent's lines to Cartesia to be spoken and the caller's answer text to Groq.
- In-browser speech recognition goes to the browser vendor's speech service.
- The voice worker can run fully local (Whisper and Kokoro) when audio must stay on your machine.

Limits:

- The `kyc-uae` sanctions, PEP and adverse-media lists are synthetic sample data, not a licensed feed.
- Login-based authentication and enforced multi-tenancy are not finished. Reviewers authenticate with named keys today.
- VoxGate holds no compliance certification.

---

## Where VoxGate stands in the market

We reviewed 13 voice-AI products: Vapi, Retell, Bland, ElevenLabs, Synthflow, Sierra, PolyAI, Hume, Cartesia, Deepgram, Decagon, Parloa and Cognigy. Most are general-purpose voice agent platforms, customer-service agents or voice infrastructure. VoxGate is narrower on purpose: structured, auditable intake where the outcome of the call is the product.

| | General voice agent platforms / CX agents | VoxGate |
|---|---|---|
| Main job | Build any voice bot, or answer customer-service calls | Structured intake for regulated workflows |
| Question wording | Usually produced by the model at runtime | Read verbatim from the pack |
| What a call produces | Call, transcript, actions | Validated fields plus a scored, explained result |
| Decision | Automated, or handed off | Human reviewer gate with an audit trail |
| Adding a use case | Prompt and configuration | A pack folder, checked by a conformance suite |
| What the site shows | The conversation | The conversation and its outcome: captured fields, score breakdown, reviewer view |

### What we deliberately don't do

- **No model-written regulated questions.** The pack's wording is the only wording.
- **No automatic rejection where judgment is needed.** Hits and high-risk cases go to a person. Only clean, low-risk cases auto-approve.
- **No certification claims.** We state what the code does, not badges it has not earned.

---

## Tech stack

| Layer | Technology |
|---|---|
| Web | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Motion |
| API | Python 3.12, FastAPI, Pydantic |
| Workflow | LangGraph with Postgres checkpointing |
| Database | Postgres (Neon in production), Alembic migrations, full-text search |
| Language models | Groq (gpt-oss strict tier, Llama lenient tier) |
| Voice | Cartesia sonic-3; Pipecat voice worker with Silero, Whisper and Kokoro |
| Matching and scoring | RapidFuzz, optional sentence-transformers, additive log-odds scorecard |
| Hosting and CI | Vercel (web and API), GitHub Actions |

## Repository layout

```
apps/web/              Next.js site: /, /how-it-works, /apply, /console, /dashboard, /agents
src/voxgate/
  config.py            Settings (VOXGATE_* env vars, repo-relative paths, secret cleaning)
  dialogue/            brain.py (turn understanding), assistant.py (site assistant), phrasing.py
  ml/                  understanding, grounded extraction, name matching, scorecard, summaries,
                       pack authoring, Groq client
  packs/               pack contract, loader, agent personas
  graph/               LangGraph case workflow
  service/             FastAPI app, case store, events, records (transcripts), analytics,
                       auth, rate limiting, quota
  migrations/          Alembic revisions
  voice/               Pipecat voice worker
  tts.py               Cartesia voice with fallbacks
packs/<pack_id>/       pack.yaml, schema.py, checks.py, scoring.py, prompt.md, data/
scripts/               pack generator, sample-call generator, demo case
tests/                 pytest suite; pack_conformance.py is the contract every pack must pass
docs/                  PRODUCT.md, DEPLOYMENT.md, ROADMAP.md, phases/
```

## Running locally

Requires **Python 3.12+** and [uv](https://docs.astral.sh/uv/getting-started/installation/). No API keys are needed.

```sh
git clone <repo-url> voxgate && cd voxgate
uv sync
uv run uvicorn voxgate.service.app:app --port 8000   # API
```

Web app:

```sh
cd apps/web
npm ci
API_ORIGIN=http://localhost:8000 npm run dev
```

Configuration uses `VOXGATE_*` environment variables or a `.env` file (copy `.env.example`):

| Variable | Purpose |
|---|---|
| `VOXGATE_DATABASE_URL` | Postgres DSN. Unset runs in memory, and cases are lost on restart. |
| `VOXGATE_API_KEYS` | Operator and reviewer keys, `name:key,...` |
| `GROQ_API_KEY` / `GROQ_API_KEYS` | Language model features. Without a key, rules and keyword matching take over. |
| `CARTESIA_API_KEY` | Hosted voices. Without it, the browser or local voice is used. |
| `VOXGATE_PACKS_DIR` | Override the packs directory |

Voice worker (heavy; downloads speech models):

```sh
uv sync --extra voice
uv run --extra voice python -m voxgate.voice --pack-id kyc-uae
```

**Dependencies.** `pyproject.toml` declares ranges; `uv.lock` is the tested snapshot. `requirements.txt` is generated with `uv export`, holds API dependencies only (no voice stack), and should not be edited by hand.

### Writing a pack

A pack is a directory under `packs/<pack_id>/`:

- `pack.yaml`: `pack_id`, `display_name`, `gate_role`, `thresholds: {low, high}`, optional `agent:` block
- `schema.py`: Pydantic `Schema` for the interview fields, plus `REASK_HINTS` (the exact question wording)
- `checks.py`: `CHECKS`, functions returning a `CheckResult` (`clear` / `review` / `hit`)
- `scoring.py`: `build_scorecard(low, high)` and `FEATURE_FIELD_HINTS`

`packs/kyc_uae/` is the reference example. `scripts/generate_packs.py` generates packs from declarative specs, the same shape `/agents` drafts.

## Testing

368+ automated tests. CI runs them with no API keys and no database, so a fresh clone or fork gets a green build.

```sh
uv run pytest -q
```

The Postgres integration suite is opt-in and runs against a throwaway database:

```sh
docker compose up -d
export VOXGATE_TEST_DB="postgresql://voxgate:voxgate@localhost:5433/voxgate"   # PowerShell: $env:VOXGATE_TEST_DB = "..."
uv run pytest tests/integration -v
```

## Deploying

Two Vercel projects from one repository: the API at the repo root (`tool.vercel.entrypoint = "app:app"`) and the web app at `apps/web`, with `API_ORIGIN` set to the API URL. Use a pooled Postgres connection string (Neon works). In production, set `VOXGATE_DATABASE_URL` and `VOXGATE_API_KEYS`.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for environment variables, workers, reverse proxy settings and health checks.

## Roadmap

Each item closes a remaining part of the problem.

- **Phone "call me".** The agent calls the applicant, so there is no link to open.
- **Preview database branches.** A Neon branch for each preview deployment.
- **Reviewer logins.** Neon Auth in place of shared operator keys, for a per-person audit trail.
- **Contradiction detection.** Flag answers that conflict with earlier answers in the same interview.
- **Semantic search.** pgvector search across transcripts and cases.
