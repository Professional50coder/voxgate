# Groq API — live empirical survey

**Date:** 2026-08-07
**Method:** Live calls against `https://api.groq.com/openai/v1/...` with the project key
(read from `GROQ_API_KEY` in `.env`, which is gitignored and never quoted here). Every latency number below is **measured**,
not quoted. Test scripts were kept in the session scratchpad, not in this repo.

> **Gotcha worth knowing before you debug anything:** `urllib.request` gets a bare **403
> Forbidden** from `api.groq.com` — the default Python user-agent is blocked at the edge.
> `httpx` and the official `groq` SDK work fine. Do not waste an hour on a phantom auth
> failure.

---

## 1. The live model list — 15 models, all `active: true`

| id | ctx | max_out | owner | modalities | features |
|---|---|---|---|---|---|
| `openai/gpt-oss-120b` | 131072 | 65536 | OpenAI | text→text | tools, json_mode, **structured_outputs**, **reasoning** |
| `openai/gpt-oss-20b` | 131072 | 65536 | OpenAI | text→text | tools, json_mode, structured_outputs, reasoning |
| `openai/gpt-oss-safeguard-20b` | 131072 | 65536 | OpenAI | text→text | tools, json_mode, structured_outputs, reasoning |
| `qwen/qwen3.6-27b` | 131072 | 16384 | Alibaba | **text+image**→text | tools, json_mode, reasoning |
| `llama-3.3-70b-versatile` | 131072 | 32768 | Meta | text→text | tools, json_mode |
| `llama-3.1-8b-instant` | 131072 | 131072 | Meta | text→text | tools, json_mode |
| `groq/compound` | 131072 | 8192 | Groq | text→text | agentic, built-in web search + code exec |
| `groq/compound-mini` | 131072 | 8192 | Groq | text→text | agentic |
| `allam-2-7b` | 4096 | 4096 | SDAIA | text→text | json_mode (Arabic) |
| `meta-llama/llama-prompt-guard-2-86m` | 512 | 512 | Meta | text→text | classifier |
| `meta-llama/llama-prompt-guard-2-22m` | 512 | 512 | Meta | text→text | classifier |
| `whisper-large-v3` | 448 | 448 | OpenAI | **audio→transcription** | + translation |
| `whisper-large-v3-turbo` | 448 | 448 | OpenAI | audio→transcription | |
| `canopylabs/orpheus-v1-english` | 4000 | 50000 | Canopy Labs | **text→speech** | TTS |
| `canopylabs/orpheus-arabic-saudi` | 4000 | 50000 | Canopy Labs | text→speech | TTS |

**The endpoint returns no `preview` or `deprecated` flag** — everything is `active: true`.
Deprecation is only discoverable by calling: `playai-tts` returns
`400 … has been decommissioned` pointing at
[console.groq.com/docs/deprecations](https://console.groq.com/docs/deprecations). So treat
this list as "what currently works", not "what is stable".

**Categories:** chat (llama ×2, allam, compound ×2) · reasoning (gpt-oss ×3, qwen3.6) ·
**vision (`qwen/qwen3.6-27b` only** — the sole model with `"image"` in `input_modalities`) ·
STT (whisper ×2) · TTS (orpheus ×2) · guard/moderation (prompt-guard ×2,
gpt-oss-safeguard-20b).

---

## 2. Measured chat performance

Identical prompt, `stream=True`, `temperature=1`, `max_completion_tokens=512`. 9 of 10
succeeded.

| model | TTFT | total | tok/s (wall) | streams |
|---|---|---|---|---|
| `allam-2-7b` | **0.365 s** | 0.455 s | 285 | yes (129 chunks) |
| `llama-3.1-8b-instant` | 0.393 s | 0.591 s | 169 | yes (99) |
| `openai/gpt-oss-20b` | 0.641 s | 0.730 s | 375 | yes (82) |
| `llama-3.3-70b-versatile` | 0.472 s | 0.815 s | 163 | yes (132) |
| `openai/gpt-oss-safeguard-20b` | 0.756 s | 0.850 s | 550 | yes (86) |
| **`openai/gpt-oss-120b`** | **0.798 s** | **1.066 s** | 162 | yes (129) |
| `groq/compound-mini` | 1.092 s | 1.301 s | 198 | yes (99) |
| `qwen/qwen3.6-27b` | 0.380 s | 1.347 s | 380 | yes (513) |
| `groq/compound` | **9.167 s** | 9.367 s | 74 | yes (98) |
| `meta-llama/llama-prompt-guard-2-86m` | — | — | — | **400: classification models do not support streaming** |

Three findings that change decisions:

- **`groq/compound` is unusable for real-time voice.** 9.2 s TTFT, because it silently runs
  built-in tools first — 4,884 prompt tokens for a 50-token question. `compound-mini` is 8×
  faster but still the slowest non-agentic option.
- **`qwen/qwen3.6-27b` leaks `<think>` into `content`** by default. Its raw stream began
  `" <think> Here's a thinking process:"` and it burned the full 512-token cap without
  finishing. Needs `reasoning_effort="none"` or `reasoning_format="hidden"` to be usable.
- **`prompt-guard` is genuinely useful** non-streaming: it returns a bare float jailbreak
  probability in `message.content` — `0.00036` for "What is my account balance?" versus
  **`0.9996`** for "Ignore all previous instructions…", in ~0.39 s. The 22m and 86m variants
  agree closely.

---

## 3. `reasoning_effort` — what it actually does

The user-supplied snippet (`gpt-oss-120b`, `reasoning_effort="medium"`, `stream=True`,
`temperature=1`, `max_completion_tokens=2048`) **works verbatim**: TTFT 0.765 s, total
0.906 s, 64 content chunks.

Measured, not documented — it is a **reasoning-token budget dial**, and it **exposes
traces**:

| effort | latency | completion_tokens | **reasoning_tokens** |
|---|---|---|---|
| `low` | 1.01 s | 123 | **14** |
| `medium` | 0.89 s | 137 | **55** |
| `high` | 1.34 s | 295 | **199** |

Streaming emits a **separate `delta.reasoning` field** — 357 characters of genuine
chain-of-thought in the test run: *"The date 31 February is invalid because February never
has 31 days; also 1990 was not a leap year…"*. Non-streaming puts it in `message.reasoning`.
Through LangChain it lands in `additional_kwargs["reasoning_content"]` and
`usage_metadata.output_token_details.reasoning`.

**Support matrix (empirically probed — accepted values differ per model):**

- `openai/gpt-oss-120b` / `-20b` / `-safeguard-20b` → **`low` | `medium` | `high`** only.
  `none` and `default` return 400.
- `qwen/qwen3.6-27b` → **`none` | `default`** only. `medium` / `high` return 400.
- `llama-3.3-70b-versatile`, `groq/compound` → `400 "reasoning_effort is not supported with
  this model"`.

`reasoning_format` on gpt-oss-120b: `parsed` works (separate field), `hidden` works
(suppressed), **`raw` returns 400**. The [reasoning docs](https://console.groq.com/docs/reasoning)
say GPT-OSS wants `include_reasoning` instead.

**Structured outputs work**: `response_format` with a strict JSON schema returned clean
`{"field":"date_of_birth","valid":false,"reason":"February does not have 31 days"}` in 0.93 s.

---

## 4. Groq Whisper STT — the headline finding

Test audio: SAPI-synthesized KYC utterance (name, DOB, address, PAN), 16 kHz mono WAV.

| audio | model | latency | realtime factor |
|---|---|---|---|
| 18.0 s | `whisper-large-v3-turbo` | **0.63 s** | **28.7×** |
| 18.0 s | `whisper-large-v3` | 0.69 s | 25.9× |
| 359.8 s | `whisper-large-v3-turbo` | **3.26 s** | **110×** |
| 359.8 s | `whisper-large-v3` | 3.83 s | 94× |

Latency is very stable — three repeats on the short clip: 0.619 / 0.618 / 0.604 s.

Quality on KYC-shaped content was excellent: it transcribed a spelled-out PAN as
**"ABCDE1234F"** correctly, and normalized "the fourteenth of March, nineteen ninety two" →
"14 March, 1992". `verbose_json` returns `duration`, `language`, `segments` (3 on the short
clip, 61 on the long) and an `x_groq.id` request id. `/audio/translations` also works on
`whisper-large-v3`.

**Fixed overhead is ~0.5 s** (0.63 s for 18 s of audio versus 3.26 s for 360 s). *That* is
the number that matters for a turn-based voice loop — not the 110× throughput figure.

**Groq TTS is currently blocked.** `canopylabs/orpheus-v1-english` returns
`400 "requires terms acceptance. Please have the org admin accept the terms at
console.groq.com/playground?model=canopylabs%2Forpheus-v1-english"`. `playai-tts` is
decommissioned. **Action required if Groq TTS is ever wanted: an org admin must accept the
Orpheus terms in the console.**

---

## 5. Rate limits — observed versus published

Published free tier ([docs/rate-limits](https://console.groq.com/docs/rate-limits)),
confirmed against real response headers:

| model | RPM | RPD | TPM | TPD |
|---|---|---|---|---|
| `gpt-oss-120b` / `-20b` / `-safeguard-20b`, `qwen3.6-27b` | 30 | 1K | **8K** | 200K |
| `llama-3.3-70b-versatile` | 30 | 1K | 12K | 100K |
| `llama-3.1-8b-instant` | 30 | 14.4K | 6K | 500K |
| `groq/compound` / `-mini` | 30 | 250 | 70K | — |
| `whisper-large-v3` / `-turbo` | 20 | 2K | — | ASH 7.2K / ASD 28.8K |
| `prompt-guard-2-22m` / `-86m` | 30 | 14.4K | 15K | 500K |
| `canopylabs/orpheus-*` | 10 | 100 | 1.2K | 3.6K |

**The response headers are misleading and were decoded empirically:**
`x-ratelimit-limit-requests` reports the **daily (RPD)** quota, not RPM.
`x-ratelimit-limit-tokens` reports the **per-minute (TPM)** quota.

Observed exactly: gpt-oss-120b `1000`/`8000`; llama-3.3-70b `1000`/`12000`; llama-3.1-8b
`14400`/`6000`; compound `250`/`70000`; whisper `2000`.

It is a **leaky bucket over 24 h**: `x-ratelimit-reset-requests` was `1m26.4s` for the
1000/day models (86400/1000 = 86.4 s), `43.2s` for whisper's 2000/day, `6s` for
llama-3.1-8b's 14400/day, `5m45.6s` for compound's 250/day. Every value checks out.

Undocumented bonus: **`allam-2-7b` returned 7000 RPD / 6000 TPM** and is not in the
published table at all.

### The binding constraint

**8K TPM on gpt-oss-120b.** A single trivial 86-token request consumed 598 tokens of the
minute budget. That is roughly **13 short reasoning calls per minute, 1,000 per day**.

**The free tier cannot carry a live interview.** Budget for the paid tier before any demo
with real traffic.

### Paid tier

A "Developer" tier exists ([billing FAQs](https://console.groq.com/docs/billing-faqs)) — add
a card, no commitment, progressive billing at $1/$10/$100/$500/$1K lifetime thresholds.
Unlocks higher limits plus Flex and Batch service tiers. **Groq publishes no actual
Developer-tier numbers** — the docs tab is prose only.

Per-model pricing (in/out per M tokens): gpt-oss-120b $0.15/$0.60 · gpt-oss-20b $0.075/$0.30
· llama-3.1-8b $0.05/$0.08 · llama-3.3-70b $0.59/$0.79 · qwen3.6-27b $0.60/$3.00.
**Whisper: `large-v3` $0.111/hr, `large-v3-turbo` $0.04/hr.** `groq/compound` pricing is
unpublished (its model doc page 404s) — treat its cost as unknown.

---

## 6. Pipecat 1.7.0 has full Groq coverage, already installed

`.venv/Lib/site-packages/pipecat/services/groq/` contains `llm.py`, `stt.py`, `tts.py`. All
three import cleanly. `__init__.py` is empty, so import from the submodules:

```python
from pipecat.services.groq.llm import GroqLLMService   # extends OpenAILLMService
from pipecat.services.groq.stt import GroqSTTService   # extends BaseWhisperSTTService
from pipecat.services.groq.tts import GroqTTSService   # extends TTSService
```

Extra: **`pipecat-ai[groq]`** → `groq>=0.23.0,<2`.

Defaults: LLM `llama-3.3-70b-versatile`; STT `whisper-large-v3-turbo` + `Language.EN`; TTS
`canopylabs/orpheus-v1-english` voice `autumn`, **fixed 48 kHz** (it warns otherwise),
formats `flac|mp3|mulaw|ogg|wav`, with a source comment noting only `speed=1.0` is supported
as of 2026-02-25. All three take the modern `settings=Service.Settings(...)` API — passing
`model=` / `voice_id=` directly has been deprecated since 0.0.105, removal in 2.0.0.

**Pipecat ships a published benchmark constant for Groq STT:
`GROQ_TTFS_P99 = 1.54` seconds** (speech-end → final transcript, p99) in
`pipecat/services/stt_latency.py`. That is the honest end-to-end voice number — not the
0.63 s single-shot measurement above.

`pyproject.toml` currently declares
`pipecat-ai[webrtc,deepgram,cartesia,openai,silero]>=0.0.60` — **`groq` is not in the extras
list** and would need adding.

---

## 7. langchain-groq — verified end to end

**`langchain-groq` 1.1.3** (released 2026-06-10), requires `langchain-core>=1.4.0,<2.0.0` —
compatible with the installed `langchain-core 1.5.3` and `langgraph 1.2.10`. Installed and
run live:

- `ChatGroq(model="openai/gpt-oss-120b")` plain invoke: **0.63 s**, usage metadata includes
  `output_token_details.reasoning: 35`.
- `.with_structured_output(PydanticModel)`: **0.64 s** →
  `field_name='date_of_birth' valid=False reason='Invalid date: February has at most 29 days'`.
- **Tool calling through `create_react_agent`: 0.81 s for a full 4-message loop**
  (Human → AI tool_call → ToolMessage → AI summary). Worked first try.
- Streaming via `.stream()`: TTFT 0.477 s, 28 chunks.

One deprecation: `from langgraph.prebuilt import create_react_agent` warns
`LangGraphDeprecatedSinceV10`. The new path is **`from langchain.agents import create_agent`**.

---

## 8. Recommendation for VoxGate

Context: `src/` today makes **zero LLM calls** — the scorecard, name matching, and checks are
all deterministic. The voice pipeline is design-only and specifies a fully-local, zero-key
stack. So this is a clean, unconstrained insertion point.

### Move to Groq

- **Interview dialogue reasoning → `openai/gpt-oss-120b`, `reasoning_effort="medium"`,
  streaming.** 0.80 s TTFT sits inside a natural turn budget, and the `reasoning` field is a
  genuine asset here: for a compliance system, a persisted machine-readable rationale per
  turn is exactly what an auditor wants. Drop to `reasoning_effort="low"` (14 reasoning
  tokens versus 55) for latency-critical turns.
- **Risk-narrative generation → `openai/gpt-oss-120b`, `reasoning_effort="high"`.** Offline
  and batch, not in the voice loop, so 1.34 s does not matter and the 199-token trace is
  worth keeping.
- **Field extraction and validation → `openai/gpt-oss-20b` with strict `response_format`
  JSON schema.** Half the latency, half the price, structured outputs verified working.
  Reserve 120b for genuinely ambiguous fields.
- **Add `meta-llama/llama-prompt-guard-2-86m` as a prompt-injection gate on transcribed
  speech.** 0.39 s, and a 0.9996-versus-0.00036 separation. A KYC interview is a system where
  the subject *speaks text straight into your prompt context* — this is close to free
  insurance, and it is absent from the current design.

### Keep local

- **TTS stays local (Piper/Kokoro/Pocket).** Groq's Orpheus is hard-blocked on org terms
  acceptance, and its free tier is 10 RPM / 100 RPD / 3.6K TPD — not a production voice path.
- **`groq/compound` — avoid.** 9.2 s TTFT and unpublished pricing.

### STT is genuinely contested — recommend hybrid, not migration

Groq Whisper is fast (~0.5 s fixed overhead) and cheap ($0.04/hr on turbo), and Pipecat's own
p99 of 1.54 s is competitive. Against that: (a) it is the **single highest-volume PII
channel** — every raw utterance, including the PAN the test transcribed perfectly; (b) the
free-tier **ASH of 7,200 s = 2 hours of audio per wall-clock hour**, which caps you at
roughly two concurrent live interviews; (c) `faster-whisper` is already a declared
dependency.

**Recommendation: keep local faster-whisper as the default for the live loop, and wire
`GroqSTTService` behind the same interface as an opt-in fallback** for burst load or
low-spec deployments. Pipecat makes this nearly free — both are `BaseWhisperSTTService`
subclasses, so it is a config swap.

---

## 9. The compliance concern, named plainly

VoxGate handles KYC PII, and the `kyc-uae` pack means non-US subjects.

Groq's contractual posture is actually good: the Services Agreement §4.2 forbids training on
inputs/outputs, §8.1 leaves you owning the data, default retention is **none** (30-day cap on
troubleshooting logs), Zero Data Retention is a console toggle under Data Controls, EU SCCs
are in the DPA, and a HIPAA BAA exists.

**But all customer data is stored in GCP buckets in the United States, and there is no
published EU or India data-residency option.** For a UAE/India KYC workload that is a real,
unresolved data-residency question — not a checkbox.

Concrete mitigation path:

1. **Enable ZDR before any real PII touches the API.**
2. **Redact identifiers before they leave the process** — send field *shapes* and validation
   verdicts to Groq, not raw PAN / passport / Emirates ID values. The current deterministic
   check architecture already makes this easy.
3. **Keep raw audio local**, since STT is where unredacted PII is unavoidable.

If a client contractually requires in-region processing, the local-first design is the only
compliant configuration, and that decision should be recorded as such.

---

## 10. What failed or stayed unverified

- **Groq TTS** — org terms not accepted, untestable.
- **`playai-tts`** — decommissioned.
- **`prompt-guard` streaming** — unsupported by design.
- **Developer-tier limit numbers** — Groq publishes none.
- **`groq/compound` pricing** — model doc page 404s.
- **`trust.groq.com` SOC 2 / ISO 27001 status** — JS-rendered, unfetchable; corroborated only
  by Groq's own 2024 announcement.
- **ZDR eligibility wording conflicts** between the docs ("all customers") and the Services
  Agreement ("Eligible Customers") — confirm in the actual console before relying on it.
