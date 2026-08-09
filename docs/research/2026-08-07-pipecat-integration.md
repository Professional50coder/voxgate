# Pipecat Integration Research

> ## ⚠️ VERIFIED AGAINST THE CLONED REPO — read this before §2
>
> The upstream repo was cloned and read directly on 2026-08-07 (HEAD
> `f82cd106`, 2026-08-06). This section supersedes anything below it that
> conflicts, and it **resolves the open disagreement** flagged in §2.
>
> ### 1. `TransportParams` has NO `vad_analyzer` and NO `turn_analyzer`
>
> Settled. `grep -n "vad_analyzer\|turn_analyzer" src/pipecat/transports/base_transport.py`
> returns **nothing**. Every tutorial that writes
> `TransportParams(vad_analyzer=SileroVADAnalyzer())` is describing a dead API.
>
> ### 2. Where VAD actually goes — and it differs for us
>
> The canonical example `examples/getting-started/06a-voice-agent-local.py` puts
> it in the **LLM aggregator**:
>
> ```python
> user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
>     context,
>     user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
> )
> ```
>
> **VoxGate has no LLM in the pipeline, so that path is unavailable to us.**
> This was the gap in the original research: it never asked where VAD goes
> without an aggregator. The answer is two standalone processors:
>
> - **`VADProcessor`** (`pipecat.processors.audio.vad_processor`)
>   `VADProcessor(vad_analyzer=SileroVADAnalyzer(), speech_activity_period=0.2,
>   audio_idle_timeout=1.0)`. Emits `VADUserStartedSpeakingFrame`,
>   `VADUserStoppedSpeakingFrame` and periodic `UserSpeakingFrame`. The
>   `UserSpeakingFrame` stream is what a voice orb should read for amplitude.
> - **`UserTurnProcessor`** (`pipecat.turns.user_turn_processor`) with strategies
>   from `pipecat.turns.user_turn_strategies`. Event handlers:
>   `on_user_turn_started`, `on_user_turn_stopped`,
>   `on_user_turn_inference_triggered`, `on_user_turn_stop_timeout`,
>   `on_user_turn_idle`.
>
> **The corrected LLM-free pipeline for VoxGate:**
>
> ```
> transport.input()
>   → VADProcessor(vad_analyzer=SileroVADAnalyzer())
>   → UserTurnProcessor(...)            # strategies decide when a turn ends
>   → ConfidenceWhisperSTTService
>   → GraphDialogProcessor              # ours: reask_fields in, TTSSpeakFrame out
>   → tts
>   → transport.output()
> ```
>
> `on_user_turn_idle` is a free win nobody planned for: an applicant who goes
> quiet mid-interview can be prompted rather than left hanging.
>
> ### 3. Confirmed unchanged
>
> - `PipelineTask` is deprecated verbatim: *"deprecated:: 1.3.0 … use
>   `PipelineWorker`. Will be removed in 2.0.0."*
> - `WorkerRunner` lives at `src/pipecat/workers/runner.py`.
> - **Every service `__init__.py` is 0 bytes** — measured for `whisper`, `piper`,
>   `kokoro`, `groq`. Always import from the leaf module.
> - The `settings=Service.Settings(...)` constructor pattern is what the current
>   examples use.
>
> ### 4. Note on the canonical example
>
> `06a-voice-agent-local.py` is "local" only in its **transport**
> (`LocalAudioTransport`). Its STT, TTS and LLM are Deepgram, Cartesia and
> OpenAI — all paid. There is no fully-local example in the repo, so our
> zero-key pipeline has no upstream reference implementation to copy. Budget
> for that: the smoke bot is genuinely first-of-its-kind work, not a port.

**Date:** 2026-08-07
**Method:** Direct reading of the pipecat 1.7.0 source installed in `voxgate/.venv`, plus a
live import smoke-test in that venv, plus Context7 (`/websites/pipecat_ai`,
`/pipecat-ai/docs`, `/pipecat-ai/pipecat-client-web`), plus WebFetch on docs.pipecat.ai,
PyPI, and the GitHub releases API. Where these disagree — and they do — the installed
source wins and the disagreement is called out.

---

## 1. Version and date check

| Package | Latest | Released | Installed in VoxGate |
|---|---|---|---|
| `pipecat-ai` | **1.7.0** | **2026-08-01** (6 days before this note) | 1.7.0 — already current |
| `langgraph` | 1.2.10 | 2026-07-28 | 1.2.10 — already current |

Release line: 0.0.108 (2026-03-28) → **1.0.0 (2026-04-14)** → 1.1.0 (04-27) → 1.2.0 (05-14)
→ 1.2.1 (05-15) → 1.3.0 (05-29) → 1.4.0 (06-17) → 1.5.0 (07-04) → 1.6.0 (07-21) → 1.7.0
(08-01). Cadence is roughly two weeks.

The `0.0.x` → `1.0.0` jump was four months ago. **Any tutorial, blog post, or answer older
than 2026-04-14 describes a different framework generation.** This is the single biggest
source of wrong information about Pipecat right now.

Python requirement: **≥3.11, ≥3.12 recommended**. VoxGate runs 3.12.10.

### Environment smoke test (Windows, Python 3.12.10) — all passed

```
OK  pipecat.pipeline.worker.PipelineWorker
OK  pipecat.workers.runner.WorkerRunner
OK  pipecat.audio.vad.silero.SileroVADAnalyzer
OK  pipecat.audio.turn.smart_turn.local_smart_turn_v3.LocalSmartTurnAnalyzerV3
OK  pipecat.transports.smallwebrtc.transport.SmallWebRTCTransport
OK  pipecat.processors.frameworks.rtvi.observer.RTVIObserver
OK  pipecat.frames.frames.TTSSpeakFrame
```

**There are no Windows blockers.** The historical onnxruntime-on-3.12 wheel gap is long
closed (1.24.4 installed and working); aiortc 1.15.0 has Windows wheels.

---

## 2. Architecture in 1.7.0

### The headline: `PipelineTask` and `PipelineRunner` are deprecated

From `.venv/Lib/site-packages/pipecat/pipeline/task.py`, lines 7–13, verbatim:

```
"""Deprecated module.

.. deprecated:: 1.3.0
    Import from :mod:`pipecat.pipeline.worker` instead. Constructing
    :class:`PipelineTask` directly is also deprecated; use
    :class:`PipelineWorker`. Will be removed in 2.0.0.
"""
```

`pipeline/runner.py` carries the same notice: `PipelineRunner` → **`WorkerRunner`** in
`pipecat.workers.runner`, removed in 2.0.0.

Nearly every Pipecat tutorial online — **including Pipecat's own runner guide page** —
still shows the deprecated pair. They work today through re-export shims, but they are on
a removal clock. Write `PipelineWorker` / `WorkerRunner` from the first line of VoxGate
voice code.

### Core model

A `Pipeline` is an ordered list of `FrameProcessor`s. `Frame`s flow `DOWNSTREAM` and
`UPSTREAM` in three lanes with different ordering guarantees:

- **`SystemFrame`** — high priority, jumps queues. `InputAudioRawFrame`,
  `UserStartedSpeakingFrame`, `InterruptionFrame`.
- **`DataFrame`** — ordered. `TextFrame`, `TranscriptionFrame`, `TTSSpeakFrame`.
- **`ControlFrame`** — ordered. `StartFrame`, `EndFrame`, `TTSStartedFrame`.

### The `FrameProcessor` contract — strict and unforgiving

```python
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

class MyProcessor(FrameProcessor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)                      # required

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)   # required, and FIRST
        ...
        await self.push_frame(frame, direction)         # required — never swallow a frame
```

Dropping a frame instead of forwarding it deadlocks the pipeline. This is the most common
beginner failure.

### `PipelineWorker` — the constructor arguments that matter

Read from `pipeline/worker.py:227-254`. Full set: `active`, `app_resources`, `bridged`,
`cancel_on_idle_timeout`, `cancel_runner_on_idle_timeout`, `cancel_timeout_secs`,
`check_dangling_tasks`, `clock`, `conversation_id`, `enable_tracing`,
`enable_turn_tracking`, `enable_rtvi=True`, `exclude_frames`, `idle_timeout_frames`,
`idle_timeout_secs`, `name`, `observers`, `params`, `rtvi_processor`,
`rtvi_observer_params`, `task_manager`, `tool_resources`.

Methods: `queue_frame()`, `queue_frames()`, `stop_when_done()`, `cancel()`,
`flush_pipeline()`, `add_observer()`. Properties: `.rtvi`, `.turn_tracking_observer`,
`.app_resources`.

Two of these are gifts for VoxGate:

- **`app_resources: Any`** — an arbitrary pass-by-reference bag, exposed as
  `worker.app_resources` and injected into tool handlers. This is the intended way to hand
  a per-case bridge object into the pipeline. Pipecat never inspects it.
- **`conversation_id`** — set it to VoxGate's `case_id` and every trace, metric, and log
  line correlates for free.

### Minimal current-API bot

```python
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker, PipelineParams   # NOT pipeline.task
from pipecat.workers.runner import WorkerRunner                      # NOT pipeline.runner

pipeline = Pipeline([transport.input(), stt, dialog, tts, transport.output()])

worker = PipelineWorker(
    pipeline,
    params=PipelineParams(enable_metrics=True),
    enable_rtvi=True,            # default — RTVI is auto-wired
    app_resources=bridge,        # your per-case bag
    conversation_id=case_id,
    idle_timeout_secs=300.0,
)
await WorkerRunner().run(worker)
```

### Breaking change that will silently bite: VAD moved out of the transport

`transports/base_transport.py:25` — **`TransportParams` in 1.7.0 has no `vad_analyzer` and
no `turn_analyzer` field.** Every older tutorial writes
`TransportParams(vad_analyzer=SileroVADAnalyzer())`. That is dead code now.

Turn-taking became a first-class subsystem under `pipecat/turns/`, configured through
`LLMUserAggregatorParams` and `UserTurnStrategies`
(`turns/user_turn_strategies.py`):

- **start strategies**: `VADUserTurnStartStrategy`, `MinWordsUserTurnStartStrategy`,
  `WakePhraseUserTurnStartStrategy`, `ExternalUserTurnStartStrategy`
- **stop strategies**: `TurnAnalyzerUserTurnStopStrategy` (wraps smart-turn),
  `DeferredUserTurnStopStrategy`, `ExternalUserTurnStopStrategy`
- **mute strategies**: `MuteUntilFirstBotCompleteUserMuteStrategy`,
  `FunctionCallUserMuteStrategy`, `AlwaysUserMuteStrategy`

The `External*` strategies let VoxGate's own FSM declare turn boundaries rather than
inferring them from silence. For a scripted interview where the system knows exactly when
it is expecting an answer, that is a much tighter fit than VAD guessing.

> **Note on a source disagreement.** Two research passes read `TransportParams` and reached
> different conclusions about whether `vad_analyzer` is still accepted there. Treat this as
> **unverified** and confirm against `transports/base_transport.py` before writing pipeline
> assembly code. The `pipecat/turns/` subsystem definitely exists either way.

---

## 3. Local, zero-key services — all first-class, all verified

Extras verified from `pipecat_ai-1.7.0.dist-info/METADATA` `Requires-Dist` lines; class
names and import paths read from module source.

| Layer | Class | Import path | Extra | Notes |
|---|---|---|---|---|
| VAD | `SileroVADAnalyzer` | `pipecat.audio.vad.silero` | `silero` | Model **bundled**: `audio/vad/data/silero_vad.onnx`, 2,327,524 B. Zero download. |
| Turn | `LocalSmartTurnAnalyzerV3` | `pipecat.audio.turn.smart_turn.local_smart_turn_v3` | **none** | Model **bundled**: `smart-turn-v3.2-cpu.onnx`, 8,679,182 B. Source imports `onnxruntime` only. ~65 ms inference. |
| STT | `WhisperSTTService`, `WhisperSTTServiceMLX` | `pipecat.services.whisper.stt` | `whisper` → `faster-whisper~=1.2.1` | Segmented, not streaming. |
| STT | `MoonshineSTTService` | `pipecat.services.moonshine.stt` | `moonshine` → `moonshine-voice` | ONNX, CPU. Default `Model.SMALL_STREAMING`. Notably faster than Whisper on CPU. |
| TTS | `PiperTTSService`, `PiperHttpTTSService` | `pipecat.services.piper.tts` | `piper` → `piper-tts>=1.3.0` | **GPL-3.0.** |
| TTS | `KokoroTTSService` | `pipecat.services.kokoro.tts` | `kokoro` → `kokoro-onnx` | Best local voice quality. Non-GPL. |
| TTS | `PocketTTSService` | `pipecat.services.pocket_tts.tts` | `pocket-tts` | **New in 1.7.0.** Streaming, CPU-only, `quantize` flag, voice cloning from an audio prompt. |
| LLM | `OLLamaLLMService` | `pipecat.services.ollama.llm` | `ollama` | Subclasses `OpenAILLMService`; `base_url="http://localhost:11434/v1"`, `api_key="ollama"` hardcoded. |
| Transport | `SmallWebRTCTransport` | `pipecat.transports.smallwebrtc.transport` | `webrtc` → `aiortc>=1.14`, `opencv-python-headless` | |
| Transport | `FastAPIWebsocketTransport` | `pipecat.transports.websocket.fastapi` | `websocket` | |

### Import-path gotcha — matters, and the docs are wrong

**Every `pipecat/services/*/__init__.py` is empty.** You must import from the leaf module:

```python
from pipecat.services.piper.tts import PiperTTSService     # correct
from pipecat.services.piper import PiperTTSService          # ImportError — but this is
                                                            # what docs.pipecat.ai shows
```

Same for the transport: the official runner guide still shows
`pipecat.transports.network.small_webrtc`, a 0.0.x path. The real path is
`pipecat.transports.smallwebrtc.transport`.

**Trust the installed source over the docs site.**

### Turn detection is a free win that predates no existing VoxGate doc

`LocalSmartTurnAnalyzerV3` is a *semantic* end-of-turn classifier. Silero VAD only hears
silence; smart-turn understands that "my date of birth is… uh…" is not a finished turn.
For a form-filling interview where people pause mid-answer reciting a passport number,
this measurably cuts false interruptions. It costs nothing: bundled model, no extra, runs
on the onnxruntime already installed.

**Do not install the `[local-smart-turn]` extra.** It pulls `torch`, `torchaudio`,
`transformers`, and `coremltools` — multiple gigabytes — and exists only for the V2/CoreML
path. V3 needs none of it.

### Whisper still discards confidence — but the fix got much smaller

`services/whisper/stt.py:343-390` — `run_stt` uses `segment.no_speech_prob` purely as an
internal accept/reject filter and yields a bare frame:

```python
yield TranscriptionFrame(text, self._user_id, time_now_iso8601(), language)
```

`avg_logprob` and per-word probabilities are dropped. **However**, `TranscriptionFrame`
gained a `result: Any | None = None` field (`frames/frames.py:446-465`), documented as
"Raw result from the STT service" — the intended hook for exactly this. So instead of the
custom frame class and class hierarchy the existing design doc plans, this becomes a
~15-line subclass that overrides `run_stt` and populates the standard `result` field. No
divergence from framework convention.

### Model download budget

Bundled, zero download: Silero (2.3 MB) + smart-turn (8.7 MB).
Downloaded on first use: Whisper `small` ≈500 MB, `medium` ≈1.5 GB, `distil-large-v2`
≈1.5 GB, `large-v3` ≈3 GB. Kokoro fetches `kokoro-v1.0.onnx` + `voices-v1.0.bin` (~350 MB)
to `~/.cache/pipecat/kokoro-onnx/`. Piper voices auto-download. Moonshine is the smallest.

**`large-v3` on CPU/int8 is too slow for conversational turn-taking** — seconds per
utterance. Default to `DISTIL_LARGE_V2` or `MEDIUM`, keep `large-v3` as a config knob, and
seriously evaluate Moonshine, which is designed for exactly this shape of workload (short
utterances, CPU, streaming).

---

## 4. Driving dialogue from our own logic, not an LLM

**This is the most important answer for VoxGate, and the framework supports it cleanly.**

An LLM is not a required pipeline element. `TTSSpeakFrame` (`frames/frames.py:790`) is a
`DataFrame` that makes the TTS service speak arbitrary text with no LLM, no context
aggregators, and no function calling anywhere in the pipeline:

```
transport.input() → stt → GraphDialogProcessor → tts → transport.output()
```

```python
from pipecat.frames.frames import TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

class GraphDialogProcessor(FrameProcessor):
    """Consumes final transcripts; drives questions from LangGraph's reask_fields."""

    def __init__(self, pack, bridge, case_id, **kwargs):
        super().__init__(**kwargs)
        self._fsm = DialogFSM(pack)
        self._bridge = bridge
        self._case_id = case_id

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            field = self._fsm.current_field
            conf = confidence_from(frame.result)      # populated by our STT subclass
            await self._bridge.patch_fields(self._case_id, {field: frame.text}, {field: conf})

            if conf < CONFIDENCE_FLOOR:
                await self.push_frame(TTSSpeakFrame(self._fsm.reask_text(field)))
            else:
                self._fsm.record(field, frame.text)
                if self._fsm.is_complete():
                    case = await self._bridge.interview_result(self._case_id, ...)
                    self._fsm.reload(case.get("interrupt"))   # graph hands back new reask_fields
                nxt = self._fsm.next_question()
                if nxt:
                    await self.push_frame(TTSSpeakFrame(nxt))

        await self.push_frame(frame, direction)
```

Because the FSM re-seeds from the graph's `interrupt` payload on every round trip, **the
graph drives the questions** — which is the stated requirement. The pack's
`schema_model.model_fields` and `reask_hints` are the script.

Two other injection routes exist:

- `worker.queue_frame(TTSSpeakFrame(...))` — speak from outside the pipeline, e.g. from a
  FastAPI handler.
- `BusTTSSpeakMessage` (`bus/messages.py:106-117`) — "Asks a `PipelineWorker` to speak the
  given text via its TTS service… Pipelines without a TTS service let the frame flow
  through harmlessly." This is how a *separate process* can make a running bot talk, which
  matters if the bot runner is ever split out from the API.

If an LLM is ever wanted, `OLLamaLLMService(base_url="http://localhost:11434/v1")` is
keyless and swappable for llama.cpp or vLLM by changing one URL.

---

## 5. Real-time transcripts and speaking state — RTVI gives this away free

**`PipelineWorker(enable_rtvi=True)` is the default.** RTVI is auto-wired; nothing to add.

`RTVIObserver` (`processors/frameworks/rtvi/observer.py`) translates pipeline frames into a
standard client protocol with an official JS/React SDK. `RTVIObserverParams` flags read
from source: `bot_output_enabled`, `bot_llm_enabled`, `bot_tts_enabled`,
`bot_speaking_enabled`, `bot_audio_level_enabled`, `user_llm_enabled`,
`user_speaking_enabled`, `vad_user_speaking_enabled`, `user_transcription_enabled`,
`user_audio_level_enabled`, `metrics_enabled`, `system_logs_enabled`, `ignored_sources`,
`skip_aggregator_types`, `bot_output_transforms`.

Mapping directly onto the dashboard's stated needs:

| UI need | RTVI client event | Server frame |
|---|---|---|
| Live captions (interim) | `onUserTranscript({text, final: false, …})` | `InterimTranscriptionFrame` |
| Live captions (final) | `onUserTranscript({text, final: true, …})` | `TranscriptionFrame` |
| Bot's spoken text | `onBotOutput({text, spoken_status})` | `AggregatedTextFrame` |
| **Orb: user talking** | `onUserStartedSpeaking` / `onUserStoppedSpeaking` | `UserStartedSpeakingFrame` / `UserStoppedSpeakingFrame` |
| **Orb: bot talking** | `onBotStartedSpeaking` / `onBotStoppedSpeaking` | `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame` |
| **Orb: amplitude** | `onLocalAudioLevel(level)` / `onRemoteAudioLevel(level, p)` | audio-level messages, `audio_level_period_secs` default 0.15 s |
| VoxGate-specific payloads | `onServerMessage(data)` | `RTVIServerMessageFrame(data={...})` |

`vad_user_speaking_enabled` gives raw VAD ungated by turn logic — that is the responsive
signal for an orb, as opposed to the semantically-debounced turn events.

```python
await self.push_frame(RTVIServerMessageFrame(data={
    "type": "voxgate.fields", "case_id": case_id,
    "fields": live_fields, "confidence": conf, "current_field": field,
}))
```

`bot_output_transforms` is directly relevant to a KYC bot: it redacts PII in the text sent
to the client while the bot still *speaks* it correctly. The documented example is
credit-card masking; passport and Emirates ID numbers are the VoxGate equivalent.

### Consequence: delete the planned custom caption channel

`docs/design/2026-08-06-voice-agent-plan2-design.md` §3.3 invents a `caption` event kind on
VoxGate's own `EventBus`. That is reinventing RTVI, badly, and it forces in-call data to
round-trip through the backend instead of riding the WebRTC data channel already open.

**Recommended split:** RTVI carries everything in-call (transcripts, speaking state, audio
levels, field progress). VoxGate's existing `/cases/{id}/events` WebSocket carries
authoritative graph state (`kind: "state"`, `"fields"`) only. One protocol per concern.

### The caveat that changes the caption UI design

Both `WhisperSTTService` and `MoonshineSTTService` extend `SegmentedSTTService` — they
transcribe *after* the turn ends. **Local STT emits no true interim transcripts.** The
`InterimTranscriptionFrame` row in the table above is real in the protocol but has no local
producer.

So the dashboard's specified "word-by-word captions" **cannot be built as described**
against local Whisper. Options:

1. Accept per-utterance final captions, and render a "listening…" affordance from
   `UserStartedSpeaking` + audio level during the gap. Honest and cheap.
2. Use a Moonshine streaming model variant and re-verify whether it emits interims.
3. Fake word-by-word by animating the reveal of a received final transcript. Looks like
   streaming, is not. Acceptable for a demo if labeled honestly internally.

Option 1 is recommended; option 3 is the pragmatic demo choice.

---

## 6. Transport and browser client

`SmallWebRTCTransport` is the right choice: peer-to-peer via `aiortc`, **no account, no
paid service, no signaling SaaS**. Google's public STUN
(`stun:stun.l.google.com:19302`) is free and sufficient for LAN; localhost needs neither
STUN nor TURN; cross-NAT production needs a TURN server (self-hosted coturn, free).

The signaling contract is one plain route: `POST /api/offer` taking `{sdp, type, pc_id?}`
and returning `{sdp, type, pc_id}`.

```python
@app.post("/api/offer")
async def offer(request: dict, background_tasks: BackgroundTasks):
    conn = SmallWebRTCConnection(ice_servers)
    await conn.initialize(sdp=request["sdp"], type=request["type"])

    @conn.event_handler("closed")
    async def on_closed(c):
        pcs_map.pop(c.pc_id, None)

    background_tasks.add_task(run_bot, conn)
    return conn.get_answer()
```

**Better: use `SmallWebRTCRequestHandler`** (`transports/smallwebrtc/request_handler.py:86-262`)
rather than hand-rolling. `handle_web_request(request, webrtc_connection_callback)` handles
`pc_id` reuse, renegotiation, ICE restart, ESP32 SDP munging, and single-vs-multiple
`ConnectionMode` constraints, and raises `HTTPException` directly — it is built for FastAPI.
`handle_patch_request()` covers trickle ICE; `update_ice_servers()` covers rotation.

### Browser SDK

```bash
npm i @pipecat-ai/client-js @pipecat-ai/small-webrtc-transport
# optional: @pipecat-ai/client-react
```

```ts
import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";

const client = new PipecatClient({ transport: new SmallWebRTCTransport(), enableMic: true });
await client.connect({ webrtcUrl: "http://localhost:7860/api/offer" });
```

**Package-scope gotcha:** Context7's mirror of the `pipecat-client-web` README shows
`@pipecat/client-js`. The docs show `@pipecat-ai/client-js`. **`@pipecat-ai/*` is the
correct published scope** — verify with `npm view` before writing frontend code.

`@pipecat-ai/client-react` exposes `PipecatClientProvider`, `PipecatClientAudio`, and hooks
like `usePipecatClientMediaDevices`. There is also **`@pipecat-ai/voice-ui-kit`** (Tailwind
4, prebuilt voice components, debug console) — worth evaluating before hand-rolling an orb
and transcript view, though see the frontend research note on why VoxGate's existing design
system may make it a poor fit.

Other transports present: `daily` (paid SaaS — skip), `livekit`, `moq`, `whatsapp`,
`heygen`, `tavus`, `vonage`, `lemonslice`, `local` (needs PyAudio — not needed, since audio
arrives over WebRTC rather than a local device).

---

## 7. Integration pattern with FastAPI and LangGraph

**Recommended: one `PipelineWorker` per call, in-process with FastAPI, spawned from
`/api/offer` via `BackgroundTasks`.** Not a separate OS process per case.

Rationale: `WorkerRunner` manages multiple workers; a `PipelineWorker` is a cheap asyncio
object; and **models are the expensive part**. Load Whisper, TTS, Silero, and smart-turn
once at module scope and share the underlying models across workers. A process per case
would reload gigabytes per call.

Flow:

1. Browser `POST /api/offer?case_id=…` with the SDP offer.
2. `SmallWebRTCRequestHandler.handle_web_request(req, callback)`.
3. Callback builds the pipeline with a per-case `GraphDialogProcessor(pack, bridge, case_id)`
   and `conversation_id=case_id`; `background_tasks.add_task(runner.run, worker)`.
4. Bot reads `GET /cases/{case_id}` for `interrupt.reask_fields` / `reask_hints` /
   `fields_so_far` and seeds the FSM.
5. Per answer: `PATCH /cases/{id}/fields` — cheap, does not touch the graph.
6. On completion: `POST /cases/{id}/interview-result` with `{fields, confidence}`.
7. Inspect the returned `interrupt`. If it is `interview` again with fresh `reask_fields`,
   **keep the same worker and WebRTC connection alive** and continue talking. Otherwise
   speak a closing line and `await worker.stop_when_done()`.

Step 7 matters: keeping the worker alive across a graph round-trip avoids tearing down
WebRTC mid-call, which the existing design doc's flow would have done.

### Keep the HTTP-only boundary

The existing design doc's best decision is that `voxgate.voice` talks to VoxGate **only
over the HTTP/WS API** and never imports `voxgate.graph` or `CaseRunner`. Keep this even
when co-located. It keeps the voice layer independently testable against
`create_app(runner=fake)` — which `tests/test_api.py` already demonstrates — and it means
splitting the bot into its own service later is a base-URL change, not a refactor.

### Suggested module layout

```
src/voxgate/voice/
├─ __init__.py
├─ config.py        # VoiceSettings: stt_model, tts_engine, confidence_floor, ice_servers
├─ models.py        # module-scope singletons: Whisper, TTS, Silero, SmartTurnV3.
│                   #   Loaded ONCE at import, shared across all per-case workers.
├─ stt.py           # ConfidenceWhisperSTTService(WhisperSTTService):
│                   #   override run_stt, populate TranscriptionFrame.result
├─ confidence.py    # pure functions: segment_confidence, field_confidence
├─ dialog.py        # DialogFSM: pure. No pipecat import, no httpx import.
│                   #   Drives off pack.schema_model.model_fields + pack.reask_hints.
│                   #   reload(interrupt_payload) re-seeds from the graph.
├─ processor.py     # GraphDialogProcessor(FrameProcessor) — the only pipecat-aware file
├─ bridge.py        # httpx client — the only HTTP-aware file
├─ pipeline.py      # build_worker(case_id, pack, connection) -> PipelineWorker
└─ webrtc.py        # SmallWebRTCRequestHandler wiring for /api/offer

tests/voice/
├─ test_confidence.py   # pure, no audio
├─ test_dialog.py       # pure FSM over scripted tuples, no pipecat
├─ test_processor.py    # frames in → frames out, no audio, no network
└─ test_bridge.py       # against create_app(runner=fake)
```

The layering is the point: `dialog.py` and `confidence.py` import neither pipecat nor
httpx, so they test instantly. Only `processor.py` knows about frames. Only `bridge.py`
knows about HTTP.

Build order: `confidence` → `dialog` → `stt` → `bridge` → `processor` → `pipeline`/`webrtc`
→ manual smoke test.

Changes to `src/voxgate/service/app.py`: **add `POST /api/offer` and `PATCH /api/offer`
only.** Everything else untouched.

---

## 8. Gotchas, consolidated

1. **`PipelineTask`/`PipelineRunner` removed in 2.0.0** — never write them.
2. **`TransportParams` VAD field** — see the flagged disagreement in §2. Verify before use.
3. **Docs contain stale import paths** — service `__init__.py` files are empty; transport
   path changed. Trust installed source.
4. **`pyproject.toml` is misconfigured.** It currently pins
   `pipecat-ai[webrtc,deepgram,cartesia,openai,silero]>=0.0.60`. That floor is from the
   previous framework generation and silently resolved across a major version to 1.7.0.
   Worse, `deepgram` and `cartesia` are **paid-key services** that the project's zero-key
   constraint explicitly rules out, and the pin is missing `whisper`, a TTS extra, and
   `websocket`. Suggested: `pipecat-ai[webrtc,websocket,whisper,kokoro,silero,ollama]>=1.7,<2`.
   **Pin `<2`** because of the deprecation removals.
5. **Do not install `[local-smart-turn]`** — ~2 GB of torch for a feature already bundled.
6. **Do not install `[local]`** — pulls PyAudio/PortAudio, unnecessary with WebRTC.
7. **Piper is GPL-3.0.** Real, and previously treated as a blocking decision. It is now
   avoidable entirely: Kokoro (`kokoro-onnx`) or `PocketTTSService`. Recommend benchmarking
   Kokoro and Pocket first; the licensing question may simply evaporate.
8. **Local STT is segmented** — no interim transcripts. See §5.
9. **Whisper `large-v3` on CPU is too slow** for turn-taking.
10. **CPU is the real scaling constraint** for concurrency, not memory or network.

---

## 9. Verdict on `docs/design/2026-08-06-voice-agent-plan2-design.md`

It is a genuinely good document with real source-reading discipline, and most of it holds.
But it was written against a mental model that 1.7.0 has moved past.

**Still correct and worth keeping:**

- Rule-based FSM over the pack instead of an LLM (§1.3, §5) — correct, and better supported
  than the doc knew.
- `WhisperSTTService` discards `avg_logprob` (§2) — re-verified true in 1.7.0.
- Silero VAD bundled and zero-config (§2).
- `SmallWebRTCTransport` needs no paid account (§2).
- The HTTP-API-only boundary for `voxgate/voice` (§3.1) — the document's best decision.
- Two-tier re-ask design (§3.2), dropped-call durability reasoning (§3.6), the confidence
  scorer (§3.4), the error/retry table, and the `large-v3` latency pushback.

**Now wrong or superseded — six points:**

| # | Issue | Correction |
|---|---|---|
| 1 | §3.3 invents a custom `caption` WS event | RTVI already standardizes this and is on by default. **Delete §3.3's custom kind.** Biggest single change. |
| 2 | §4 task 6 targets `PipelineTask`/`PipelineRunner` | Deprecated since 1.3.0, gone in 2.0.0. Code written from it is born dead. |
| 3 | §3.3 assumes interim transcripts exist | Local STT is segmented — **finals only**. Re-plan the captions UI. |
| 4 | §2 treats Piper GPL as an unavoidable decision | Kokoro and PocketTTS are local, keyless, non-GPL. Risk 1 likely evaporates. |
| 5 | §2 omits turn detection entirely | `LocalSmartTurnAnalyzerV3` is bundled, free, ~65 ms, materially better than VAD alone for form-filling. Biggest missed opportunity. |
| 6 | §4 task 2 plans a custom STT class hierarchy | `TranscriptionFrame.result` reduces it to a short subclass. |

Also: §2/§5.9 undersells `SmallWebRTCRequestHandler`, which removes most of the signaling
work the doc budgets for.

**Net effect: the plan gets smaller, not bigger.** The licensing blocker likely disappears,
the captions plumbing is replaced by a framework default, and the STT task shrinks to a
subclass. Effort should land under the doc's "~2–3 weeks" estimate.

---

## 10. Honest limits of this research

Class names, import paths, constructor signatures, extras, bundled model files, and
importability were all verified by reading installed source and running imports in the
project venv. **No end-to-end pipeline was run with live audio.** The code shapes above are
assembled from verified pieces plus current docs, not from an executed bot. The first
implementation step should be a throwaway smoke bot, not a module.

The `TransportParams` VAD question (§2) is explicitly unresolved between two research
passes and must be checked against source before pipeline assembly.

---

## Sources

- [pipecat GitHub](https://github.com/pipecat-ai/pipecat) · [releases](https://github.com/pipecat-ai/pipecat/releases) · [PyPI](https://pypi.org/project/pipecat-ai/)
- [Pipeline & frame processing](https://docs.pipecat.ai/pipecat/learn/pipeline)
- [Custom FrameProcessor](https://docs.pipecat.ai/pipecat/fundamentals/custom-frame-processor)
- [RTVI observer](https://docs.pipecat.ai/api-reference/server/rtvi/rtvi-observer) · [RTVI client standard](https://docs.pipecat.ai/client/rtvi-standard)
- [SmallWebRTC server](https://docs.pipecat.ai/api-reference/server/services/transport/small-webrtc) · [SmallWebRTC JS client](https://docs.pipecat.ai/api-reference/client/js/transports/small-webrtc)
- [Runner guide](https://docs.pipecat.ai/api-reference/server/utilities/runner/guide) · [Observer pattern](https://docs.pipecat.ai/api-reference/server/utilities/observers/observer-pattern)
- [Smart turn overview](https://docs.pipecat.ai/api-reference/server/utilities/turn-detection/smart-turn-overview) · [smart-turn model repo](https://github.com/pipecat-ai/smart-turn) · [LocalSmartTurnAnalyzerV3 API](https://reference-server.pipecat.ai/en/stable/api/pipecat.audio.turn.smart_turn.local_smart_turn_v3.html)
- [Supported services](https://docs.pipecat.ai/server/services/supported-services) · [Whisper](https://docs.pipecat.ai/server/services/stt/whisper) · [Piper](https://docs.pipecat.ai/server/services/tts/piper) · [Kokoro](https://docs.pipecat.ai/server/services/tts/kokoro) · [Ollama](https://docs.pipecat.ai/api-reference/server/services/llm/ollama)
- [pipecat-client-web](https://github.com/pipecat-ai/pipecat-client-web) · [voice-ui-kit](https://github.com/pipecat-ai/voice-ui-kit)
- [Local voice agent example](https://github.com/pipecat-ai/pipecat/blob/main/examples/getting-started/06a-voice-agent-local.py)
- Installed source: `voxgate/.venv/Lib/site-packages/pipecat/{pipeline/task.py, pipeline/worker.py, pipeline/runner.py, workers/runner.py, bus/messages.py, frames/frames.py, services/whisper/stt.py, audio/turn/smart_turn/local_smart_turn_v3.py, transports/smallwebrtc/request_handler.py, transports/base_transport.py, turns/user_turn_strategies.py, processors/frameworks/rtvi/observer.py}` and `pipecat_ai-1.7.0.dist-info/METADATA`
