# VoxGate — Roadmap

**Written:** 2026-08-07
**Supersedes:** the "REMAINING" list in `.paul/STATE.md`'s 2026-08-06 wind-down section.
**Backed by:** `docs/research/` — five notes, each verified against live sources. Read
`docs/research/README.md` first.

---

## 1. What VoxGate is

A **pack-driven voice-interview compliance gating platform**. Two things make it interesting
and both are already built:

1. **Durable human-in-the-loop execution.** A LangGraph state machine per case that pauses on
   `interrupt()` for human input — whether that input arrives by voice or by a reviewer's
   click — and survives process restarts via Postgres checkpointing.
2. **Real, explainable ML.** Additive log-odds scorecards where every risk contribution is
   attributable, and an ensemble fuzzy/embedding name matcher built specifically for Arabic
   romanization variants in Gulf compliance screening.

The platform is **scenario-generic**. Each use case is a self-contained *pack* — a directory
under `packs/<pack_id>/` exposing a fixed module contract (schema, checks, scoring, prompt).
Adding a pack is designed to require zero platform-code changes, and
`tests/pack_conformance.py` enforces that claim generically.

**v1 pack:** `kyc-uae` — client onboarding for a Dubai fintech, with sanctions/PEP/adverse-media
screening and a 7-feature AML risk scorecard. All data synthetic and marked as such.

**This is the multi-use-case abstraction the user asked for, and it already exists.** A new
vertical should be a new pack, not new code. The upgrade work is about making the *platform*
production-grade, not about inventing a second abstraction.

---

## 2. Where it actually stands

**Verified 2026-08-07: `uv run pytest -q` → 54 passed, 1 skipped.** The skip is the Postgres
integration test, which needs `VOXGATE_TEST_DB` and `docker compose up`. One known warning
from `fastapi.testclient` importing `starlette.testclient` — a pinned-dependency artifact,
not a defect.

| Layer | State |
|---|---|
| Config, name matching, scorecard | Complete, reviewed |
| Pack contract + loader + conformance suite | Complete, reviewed |
| `kyc-uae` pack | Complete, reviewed |
| LangGraph state machine | Complete, reviewed. Wave 1 extension (audit trail, richer interrupt payloads, RetryPolicy) is **code-green but never independently reviewed** |
| CaseStore / EventBus / CaseRunner | Complete, reviewed. **In-memory — dies on restart, does not work multi-process** |
| FastAPI REST + WebSocket | Complete, reviewed |
| Postgres durability | Complete, integration-tested against real Postgres |
| **Dashboard UI** | **~30 %. CSS design system complete (33 KB), HTML shell exists, `dashboard.js` never written.** `app.py` untouched, so the API is fully intact |
| Voice layer | **Design doc only, no code** — and the design needs revision (§5) |

---

## 3. What changed on 2026-08-07

Five user-directed changes:

1. Frontend moves to **Next.js**.
2. **Pipecat** becomes central, not a later plan.
3. **LangGraph gets a production upgrade** — "looks too simple".
4. **Groq API** added; the zero-paid-keys constraint is relaxed.
5. **Git constraint lifted**; repo live at `github.com/hitanshppc-hash/voxgate`.

---

## 4. Three findings that change the plan

These came out of the research and are easy to miss inside long notes. Each one invalidates
something already written down elsewhere in this repo.

### 4.1 Local STT cannot do word-by-word captions

`WhisperSTTService` and `MoonshineSTTService` both extend `SegmentedSTTService` — they
transcribe *after* the turn ends. **There is no local producer of interim transcripts.**

The dashboard CSS defines `.caption-word.interim` and `.caption-cursor`. The voice design doc
§3.3 assumes "partial transcript while the user is still talking". **Neither can be built as
specified.** Options: accept per-utterance finals (honest, recommended), use Groq's hosted
Whisper, or animate the reveal of a received final (looks streaming, is not — fine for a demo
if labeled honestly).

### 4.2 Half the planned voice plumbing already exists as a framework default

`PipelineWorker(enable_rtvi=True)` is the **default**. RTVI already ships interim/final
transcripts, bot and user speaking state, and audio levels to the browser over a standard
protocol with an official JS/React SDK, plus `onServerMessage` for arbitrary custom payloads.

The voice design doc §3.3 invents a bespoke `caption` event on VoxGate's own WebSocket.
**Delete it.** Let RTVI carry in-call data over the WebRTC data channel; keep
`/cases/{id}/events` for authoritative graph state only.

Also: `PipelineTask`/`PipelineRunner` are **deprecated** (since 1.3.0, removed in 2.0.0). The
design doc's §4 task 6 targets the dead API. Use `PipelineWorker`/`WorkerRunner`.

**Net effect: the voice plan gets smaller, not bigger.** The Piper GPL blocker also
evaporates — Kokoro and PocketTTS are local, keyless, and non-GPL.

### 4.3 Groq's free tier cannot run a live interview

Measured: **8K tokens/minute** on `gpt-oss-120b`, and a single trivial 86-token request
consumed 598 tokens of that budget. That is roughly **13 short reasoning calls per minute,
1,000 per day.** Fine for development, not for a demo with real traffic.

Also measured and genuinely useful: `gpt-oss-120b` at 0.80 s TTFT with an exposed
chain-of-thought trace (an audit asset for a compliance system), hosted Whisper at ~0.5 s
fixed overhead, and `llama-prompt-guard-2-86m` separating injection attempts at 0.9996 versus
0.00036 in 0.39 s.

**And the thing that needs a real decision, not a checkbox:** Groq stores all customer data in
US GCP buckets with no published EU or India residency option. VoxGate handles KYC PII for
UAE/India subjects. Mitigations exist (enable ZDR, redact identifiers before they leave the
process, keep raw audio local) but this should be an explicit recorded decision.

---

## 5. The work, in dependency order

Nine workstreams. The ordering matters — later ones depend on earlier ones, and two of them
are cheap wins that unblock demos.

### Phase 0 — Close out the existing build (small, do first)

| # | Task | Why | Size |
|---|---|---|---|
| 0.1 | **Graph Wave 1 independent review** | Code is green but unreviewed; package is ready at `.superpowers/.../task-wave1-package.md` | S |
| 0.2 | **`POST /cases/{id}/recover` endpoint** | `recover_case` exists and is integration-tested but is not exposed over HTTP, so after a restart `GET /cases/{id}` 404s even though the Postgres checkpoint survived. **This breaks the durability demo over HTTP** | S |
| 0.3 | **Fix `pyproject.toml` pipecat pin** | Currently `pipecat-ai[webrtc,deepgram,cartesia,openai,silero]>=0.0.60` — a floor from the previous framework generation that silently resolved across a major version, and it pulls two **paid-key services**. Should be `[webrtc,websocket,whisper,kokoro,silero,groq]>=1.7,<2` | S |
| 0.4 | **Write a `CLAUDE.md`** | Constraints currently live in `.paul/` and the SDD ledger, where a fresh agent will not automatically see them | S |

### Phase 1 — LangGraph production upgrade

See `docs/research/2026-08-07-langgraph-production-upgrade.md`. The known problems:

- One flat `StateGraph` per pack, with no reusable subgraph — packs will fork the graph as
  they diverge.
- **Synchronous `.invoke()` from a FastAPI request thread.** Works today only because no node
  does real I/O. The moment voice, LLM calls, or external screening APIs land, this blocks a
  worker per case.
- **In-memory `CaseStore`** — dies on restart, and does not work across processes. Already
  flagged in `runner.py:64-73` as a known gap ("the dashboard needs it, once one exists").
- **In-memory `EventBus`** — same problem, and it is what the dashboard's live updates depend
  on.
- No multi-tenancy: no thread-id namespacing, no per-tenant isolation, no auth.

### Phase 2 — Voice layer (Pipecat)

Per `docs/research/2026-08-07-pipecat-integration.md` §7. Module layout is specified there.
Key decisions already made by the research:

- **No LLM in the pipeline.** A custom `FrameProcessor` consumes `TranscriptionFrame` and
  emits `TTSSpeakFrame`; the graph's `reask_fields` are the script. This is the supported
  path and it is what makes the system deterministic and auditable.
- `SmallWebRTCTransport` + `SmallWebRTCRequestHandler`, one `PipelineWorker` per case,
  in-process with FastAPI, models loaded once at module scope.
- Keep the HTTP-only boundary: `voxgate.voice` never imports `voxgate.graph`.
- Add `LocalSmartTurnAnalyzerV3` — bundled, free, ~65 ms, and materially better than raw VAD
  for an interview where people pause mid-answer reciting an ID number.

Build order: `confidence` → `dialog` → `stt` → `bridge` → `processor` → `pipeline`/`webrtc`.
The first three are pure logic with no pipecat import, so they test instantly.

**Start with a throwaway smoke bot, not a module.** No end-to-end pipeline has been run with
live audio yet.

### Phase 3 — Next.js frontend

Port target, not a rewrite from zero. `docs/research/2026-08-07-dashboard-asset-inventory.md`
is a complete map of what exists: every token, every class, every ID, and a gap analysis that
recovers the intended feature surface from the CSS.

**Preserve the design system.** The tokens, status colours, and component specs encode real
product thinking and map cleanly onto Tailwind v4 CSS variables.

**Apply the honest filter** from `docs/research/2026-08-07-frontend-techniques.md` §7. The
short version: this is a dense console where a reviewer makes consequential judgments for
hours, not a marketing site. Specifically —

- **Never ship smooth-scroll hijacking (Lenis).** It breaks Ctrl+F, scroll restoration,
  keyboard paging, and screen readers. Reviewers scan long lists.
- **Ration `backdrop-filter` to 2–3 chrome surfaces.** This is the biggest existing risk in
  the current CSS — 20 glass tiles will drop frames, and text over a variable-luminance
  backdrop has unguaranteeable contrast.
- **No gradient text on any number, label, or status.** In a compliance tool a misread digit
  is a real incident.
- Do ship: the static CSS aurora, tokenized easing with one-time mount stagger, container
  queries, `color-mix()`, and a genuine `prefers-reduced-motion` path (compliance software
  ships into orgs with hard WCAG 2.2 AA procurement requirements).

Voice orb: **Canvas 2D, not WebGL.** Full implementation approach with the audio graph, RMS
envelope, state machine, and render loop is in the frontend note §4.

### Phase 4 — Groq integration

Per `docs/research/2026-08-07-groq-api-survey.md` §8. Recommended split:

- Interview dialogue reasoning → `gpt-oss-120b`, `reasoning_effort="medium"`, streaming.
- Risk-narrative generation for reviewers → `gpt-oss-120b`, `reasoning_effort="high"`,
  offline/batch.
- Field extraction and validation → `gpt-oss-20b` with strict JSON schema.
- **Add `llama-prompt-guard-2-86m` as an injection gate on transcribed speech** — a KYC
  interview is a system where the subject speaks text straight into your prompt context.
  This is absent from the current design and is close to free insurance.
- **STT stays local by default**, with `GroqSTTService` wired behind the same interface as an
  opt-in fallback. Both are `BaseWhisperSTTService` subclasses, so it is a config swap.
- **TTS stays local.** Groq's Orpheus is hard-blocked on org terms acceptance anyway.

### Phase 5 — Second and third packs

The claim that "adding a pack requires zero platform changes" is enforced by a generic
conformance suite but has only ever been exercised by **one** pack. Building `loan-intake` or
`claim-fnol` is the real test of the multi-use-case story, and it should happen *after* the
graph upgrade so the packs are built against the target architecture rather than migrated to
it.

### Phase 6 — Final review and hardening

- Whole-project review + fix wave (never run; was queued as the last gate).
- Security review — the project handles KYC PII and now has a live API key.
- Accessibility audit against WCAG 2.2 AA.
- Live UI pass in a real browser. Worth stating explicitly: a previous project shipped with
  "deploy triggered but unverified", and that should not repeat here.

---

## 6. Open decisions that need a human

These are not research gaps — they are genuine judgment calls that shape the architecture.

1. **Captions.** Accept per-utterance finals, use Groq's hosted Whisper, or fake the
   word-by-word reveal? (§4.1)
2. **PII and data residency.** Does any raw KYC identifier leave the process? If a client
   contractually requires in-region processing, the local-first design is the only compliant
   configuration and that should be recorded as a decision, not discovered later. (§4.3)
3. **Groq tier.** Free tier cannot carry a live interview. Paid tier before any real demo?
4. **Frontend hosting shape.** Does Next.js serve as a separate app calling the FastAPI
   control plane, or does FastAPI keep serving static assets? This decides the deployment
   topology.
5. **Voice UI kit.** Adopt `@pipecat-ai/voice-ui-kit` (Tailwind 4, prebuilt components) or
   hand-roll against the existing design system? The kit saves work but may fight the
   established visual language.

---

## 7. What is deliberately not being done

- Rebuilding the pack abstraction. It already works and is conformance-tested.
- Rewriting the scorecard or name matcher. Both are complete, reviewed, and are the
  interesting ML in the project.
- Adding a chart library. The CSS explicitly says "pure CSS/JS, no libs" and the four charts
  are simple bars and funnels.
- Fullscreen WebGL gradients, Lottie, Rive, magnetic cursors, scroll-reveal. See the frontend
  note §7 for why each would actively hurt a dense ops console.

---

## 8. Deferred minors carried forward

The 2026-08-06 build closed with a list of explicitly-deferred minor findings — none
blocking, all noticed rather than missed. They live in `.paul/STATE.md` under "Deferred
minors" and should be swept during Phase 6 rather than one at a time. Two are worth pulling
forward because the upgrade touches them anyway:

- `CaseStore.get()`/`.list()` return direct references to internal dicts, so a caller
  mutating a returned case corrupts store state. **Phase 1 replaces the store — fix it
  there.**
- `packs/kyc_uae/scoring.py` hardcodes the `sys.modules` qualname string
  `"voxgate_pack_kyc-uae_checks"`, so renaming the pack's `pack_id` would silently break the
  lookup. **Phase 5 adds packs — fix it before that.**
