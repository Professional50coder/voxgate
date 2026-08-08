"""Pipecat voice agent, closely aligned with `pipecat-ai/pipecat` examples.

Mirrors the canonical FastAPI websocket pipeline shape from the upstream repo:
``transport.input() -> STT -> LLMContextAggregator.user() -> LLM -> TTS ->
transport.output() -> LLMContextAggregator.assistant()``, run with a
`PipelineWorker`/`WorkerRunner` and a `FastAPIWebsocketTransport`.

The LLM stage is a real Groq service, so the agent converses naturally and in
real time (time-of-day aware greeting, brief acknowledgment, one question at a
time). Scenarios select which persona/instruction set to use — multiple
usecases from the same transport.
"""
from __future__ import annotations

from typing import Callable

from fastapi import WebSocket

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import Frame, LLMRunFrame, LLMTextFrame, TextFrame, TranscriptionFrame
from pipecat.observers.base_observer import BaseObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor, Frame
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.groq.stt import GroqSTTService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

from voxgate.config import Settings, get_settings
from voxgate import groq_brain, tracing

# Cartesia Sonic natural female voice id (from pipecat examples).
DEFAULT_CARTESIA_VOICE = "32b3f3c5-7171-46aa-abe7-b598964aa793"

# A single natural Sonic voice produces a natural, non-robotic sound — the
# reason we route the voice through Cartesia rather than the browser TTS.

# Multiple usecases: pick a persona per session. The `system` prompt teaches
# the LLM how to speak to the client correctly in real time.


def _greet_preamble(pod: str, hint: str) -> str:
    return (
        "You speak in warm, short, natural sentences that are easy to speak aloud "
        "(no markdown, emojis, bullets, or numbering). You converse fluidly, "
        "acknowledging what the applicant says before responding. "
        f"It is currently {pod}. Begin by greeting the applicant appropriately "
        "for the time of day, introduce yourself as VoxGate, and set up the "
        f"conversation: {hint}"
    )


SCENARIOS: dict[str, dict] = {
    "kyc-interview": {
        "display_name": "KYC identity-verification interview",
        # Warm, compliance-savvy interviewing tone.
        "system": (
            "You are VoxGate, a warm and efficient voice assistant running a KYC "
            "identity-verification interview, one question at a time. Ask about the "
            "applicant's details (full legal name, date of birth, nationality, "
            "residency status, source of funds) clearly and patiently. If an answer "
            "is unclear, ask once more, calmly and briefly. Keep every reply to one "
            "or two short sentences so it can be spoken aloud. Avoid repeating the "
            "applicant's personal data in full."
        ),
    },
    "onboarding": {
        "display_name": "New-customer onboarding welcome",
        "system": (
            "You are VoxGate, a friendly product assistant welcoming a new customer. "
            "Explain in a few short, spoken sentences who we are, what the "
            "onboarding involves, and ask them how best we can help today."
        ),
        "hint": "tell them VoxGate offers fast, transparent verification and ask how you can help.",
    },
    "support": {
        "display_name": "Customer support assistant",
        "system": (
            "You are VoxGate's support assistant. Listen to the customer's issue, "
            "paraphrase it in one line, then offer the single most helpful next step. "
            "Keep answers to one or two short, calm sentences that can be spoken aloud."
        ),
        "hint": "help with setting up their account or verifying an identity.",
    },
    "kyc-crypto": {
        "display_name": "Crypto onboarding interview",
        "system": (
            "You are VoxGate running a cryptocurrency onboarding interview. Ask about "
            "the customer's legal name, date of birth, residency, trading experience, "
            "and primary source of funds. Reassure them that this is a standard "
            "compliance step. One or two short, calm sentences per reply."
        ),
        "hint": "start the crypto onboarding compliance interview.",
    },
    "risk-review": {
        "display_name": "Enhanced risk review",
        "system": (
            "You are VoxGate conducting an enhanced due-diligence risk review. "
            "Ask one clarifying question about any flagged transaction or unusual "
            "activity. Be professional and non-accusatory, and keep each reply to "
            "one short, spoken sentence."
        ),
        "hint": "ask the customer to clarify the flagged activity.",
    },
    "general": {
        "display_name": "General assistant",
        "system": (
            "You are VoxGate, a helpful, concise voice assistant. Answer the user's "
            "questions helpfully in one or two short sentences that can be spoken "
            "aloud. Do not use formatting or bullets."
        ),
        "hint": "ask how you can help.",
    },
    "followup": {
        "display_name": "Outbound follow-up call",
        "system": (
            "You are VoxGate making a brief outbound follow-up call. Confirm who you "
            "are and the reason for the call, ask one specific confirmation question, "
            "then thank the customer. Thread cautious and polite, one short sentence at a time."
        ),
        "hint": "confirm a recent document or action with the customer.",
    },
    "multilang": {
        "display_name": "Spanish-speaking assistant",
        "system": (
            "Eres VoxGate, un asistente de voz cálido y conciso. Responde al cliente "
            "en español, en una o dos frases cortas fáciles de pronunciar, sin "
            "formato ni viñetas. (You are VoxGate, a warm voice assistant. Answer the "
            "customer in Spanish, briefly.)"
        ),
        "hint": "saluda y pregunta cómo puedes ayudar.",
    },
}


def scenario_system(scenario: str) -> str:
    spec = SCENARIOS.get(scenario, SCENARIOS["kyc-interview"])
    hint = spec.get("hint") or "ask the first question to begin the interview."
    return f"{spec['system']}\n\n{_greet_preamble(groq_brain.time_of_day(), hint)}"


def _interview_plan(fields: list[dict] | None) -> str:
    """Render the LangGraph field list as spoken instructions for the LLM."""
    if not fields:
        return ""
    lines = []
    for i, f in enumerate(fields, 1):
        hint = (f.get("hint") or "").strip()
        lines.append(f'{i}. "{f.get("field")}"'
                     + (f' — ask naturally, e.g.: "{hint}"' if hint else ""))
    return ("Collect these fields IN ORDER, one question at a time; "
            "acknowledge each answer briefly and, if unclear, ask again once: "
            + "; ".join(lines) + ".")


class _TextBridge(FrameProcessor):
    """Turn typed user input (browser ``Frame.text``) into an LLM turn.

    The STT stage only consumes audio, so a raw ``TextFrame`` would otherwise
    die in the pipeline. This bridge (placed right after ``transport.input()``)
    instead appends the typed line to the LLM context as a user message and
    re-triggers the model, so a user can type answers/questions mid-session.
    """

    def __init__(self, context: LLMContext):
        super().__init__()
        self._context = context

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, TextFrame) and frame.text:
            self._context.add_message({"role": "user", "content": frame.text})
            await self.push_frame(LLMRunFrame(), direction)
            return
        await self.push_frame(frame, direction)


class _CaptionObserver(BaseObserver):
    """Publish each spoken line to the case's event stream.

    The observer sits on the pipeline and forwards every user transcription and
    every assistant text frame to ``publish(role, text, interim)`` so the
    dashboard render real-time captions + orb activity without any extra round
    trip from the browser client.
    """

    def __init__(self, publish: Callable[[str, str, bool], None]):
        super().__init__()
        self._publish = publish

    async def on_process_frame(self, data):
        frame = data.frame
        if isinstance(frame, TranscriptionFrame) and frame.text:
            self._publish("applicant", frame.text, bool(frame.finalized))
        elif isinstance(frame, (LLMTextFrame, TextFrame)) and getattr(frame, "text", None):
            self._publish("agent", frame.text, False)


async def run_case_voice(websocket: WebSocket, *, case_id: str,
                         scenario: str = "kyc-interview",
                         fields: list[dict] | None = None,
                         publish: Callable[[str, str, bool], None] | None = None,
                         settings: Settings | None = None) -> None:
    """Accept a connected websocket and run a Pipecat voice session for the case.

    ``fields`` is the LangGraph interview plan: an ordered list of
    ``{"field": ..., "hint": ...}`` the agent must collect. Passing it keeps the
    spoken conversation aligned with the workflow's required fields and re-asks.

    ``publish`` receives every spoken line as ``(role, text, interim)``
    (``role`` is ``"agent"`` or ``"applicant"``) and is expected to push a
    caption event into the case's live event stream so the dashboard orb and
    captions animate (the same shape as ``POST /cases/{id}/captions``).

    Blocks (awaits the runner) until the client disconnects, at which point the
    pipeline is cancelled and the session's trace entry is closed out.
    """
    settings = settings or get_settings()
    spec = SCENARIOS.get(scenario, SCENARIOS["kyc-interview"])
    tracing.write(settings, session=case_id, category="voice.session", scenario=scenario,
                  display=spec["display_name"], fields=[f.get("field") for f in (fields or [])],
                  ok=True)

    # The browser client speaks pipecat's protobuf wire format (see
    # `voice/protobuf.py` + the client in dashboard.js). Without a serializer the
    # transport drops every inbound message (`if not self._params.serializer`),
    # so audio would never reach the STT — the serializer is mandatory here.
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            serializer=ProtobufFrameSerializer(),
        ),
    )

    # LLM context + aggregator so the agent can hold a real, multi-turn chat.
    context = LLMContext()
    plan = _interview_plan(fields)
    context.add_message({"role": "developer",
                         "content": scenario_system(scenario) + ("\n\n" + plan if plan else "")})

    user_aggr, assistant_aggr = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            filter_incomplete_user_turns=True,
        ),
    )

    groq_key = settings.groq_api_key
    stt = GroqSTTService(api_key=groq_key)
    llm = GroqLLMService(api_key=groq_key)
    voice_id = getattr(settings, "cartesia_voice", None) or DEFAULT_CARTESIA_VOICE
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        settings=CartesiaTTSService.Settings(voice=voice_id),
    )

    pipeline = Pipeline(
        [
            transport.input(),     # Audio from the browser
            _TextBridge(context),  # Typed user input -> an LLM user turn
            stt,                   # Speech -> text (Groq Whisper)
            user_aggr,             # Accumulate the user's spoken turns
            llm,                   # Conversational answer (Groq)
            tts,                   # Text -> natural audio (Cartesia Sonic)
            transport.output(),    # Audio back to the browser
            assistant_aggr,        # Assistant responses for the running context
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(),
        observers=[_CaptionObserver(publish)] if publish else [],
    )
    runner = WorkerRunner()

    @transport.event_handler("on_client_connected")
    async def _connected(*args):
        tracing.write(settings, session=case_id, category="voice.connect", ok=True)
        # Trigger the opening utterance (greeting -> first question).
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _disconnected(*args):
        tracing.write(settings, session=case_id, category="voice.end", ok=True)
        await worker.cancel()

    await runner.add_workers(worker)
    await runner.run()


__all__ = ["SCENARIOS", "scenario_system", "run_case_voice", "DEFAULT_CARTESIA_VOICE"]