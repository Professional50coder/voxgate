"""Assemble the voice pipeline.

    transport.input  ->  STT  ->  InterviewProcessor  ->  TTS  ->  transport.output

Notably absent: an LLM service. Most Pipecat pipelines put one between STT and
TTS to decide what to say. `InterviewProcessor` replaces it, because the pack
already knows what to ask â€” see that module for why a model choosing the
questions is the wrong shape for regulated intake.

Everything here is local by default. Whisper transcribes on this machine and
Kokoro speaks on it, so an applicant's voice â€” which is biometric data, and in
an identity interview is attached to their name and date of birth â€” does not
leave the box unless an operator opts into a hosted service.

Imports of `pipecat` are deferred into the functions. The voice stack is a
heavy optional extra (torch, transformers, model downloads), and importing this
module must stay cheap for the service, the tests and anything that only wants
`InterviewProcessor`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Whisper's smallest useful multilingual model. Chosen for latency, not
# accuracy: transcription sits directly in the applicant's turnaround, and the
# extractor behind it is validating against a fixed set of allowed values, so it
# recovers from a wrong word far better than the applicant recovers from waiting.
DEFAULT_WHISPER_MODEL = "base"


@dataclass
class VoiceConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    whisper_model: str = DEFAULT_WHISPER_MODEL
    voice_id: str = "af_heart"
    greeting: str | None = (
        "Hello. I have a few questions to get your application started. "
        "Please answer whenever you are ready."
    )


def build_vad():
    """Silero VAD.

    Voice activity detection is what makes this feel like a conversation rather
    than a walkie-talkie: it marks where an utterance ends so Whisper is handed
    a complete one. Whisper is segmented and produces nothing until an utterance
    closes, so without VAD there is no signal for when to transcribe at all.
    """
    from pipecat.audio.vad.silero import SileroVADAnalyzer

    return SileroVADAnalyzer()


def build_stt(model: str = DEFAULT_WHISPER_MODEL):
    from pipecat.services.whisper.stt import WhisperSTTService

    return WhisperSTTService(model=model)


def build_tts(voice_id: str = "af_heart", agent_voice=None):
    """Cartesia in the agent's voice when it is reachable, Kokoro otherwise.

    The agent's primary voice is probed first, then its fallback; whichever
    answers is used for the whole call. With no key, no network or both voices
    down, the call still happens in Kokoro's local voice.
    """
    from voxgate.config import get_settings
    from voxgate.packs.agent import VoiceProfile
    from voxgate.tts import pick_voice

    settings = get_settings()
    picked = pick_voice(agent_voice or VoiceProfile(), settings) \
        if settings.cartesia_api_key else None
    if picked is not None:
        tier, cartesia_voice = picked
        try:
            from pipecat.services.cartesia.tts import CartesiaTTSService

            logger.info("speaking with Cartesia %s voice %s", tier, cartesia_voice)
            return CartesiaTTSService(api_key=settings.cartesia_api_key,
                                      voice_id=cartesia_voice,
                                      model=settings.cartesia_model)
        except ImportError:
            logger.warning("pipecat cartesia extra not installed; using Kokoro")
    from pipecat.services.kokoro.tts import KokoroTTSService

    return KokoroTTSService(voice_id=voice_id)


def build_pipeline(*, transport, interview, config: VoiceConfig | None = None):
    """The four stages, in order.

    `interview` is an `InterviewProcessor`. It is constructed by the caller
    rather than here because it needs a case, an extractor and a completion
    callback â€” all of which belong to the service layer, which this module
    deliberately does not import.
    """
    from pipecat.pipeline.pipeline import Pipeline

    config = config or VoiceConfig()
    return Pipeline([
        transport.input(),
        build_stt(config.whisper_model),
        interview,
        build_tts(config.voice_id, getattr(getattr(interview, "agent", None), "voice", None)),
        transport.output(),
    ])


def build_transport(config: VoiceConfig):
    """A WebSocket transport carrying raw audio.

    WebSocket rather than WebRTC for the first cut: it needs no signalling
    server, no STUN and no TURN, which makes it something you can actually run
    behind the same reverse proxy as the API. WebRTC is the better answer for
    poor networks and `SmallWebRTCTransport` is available for that, but it adds
    infrastructure this does not yet need.
    """
    from pipecat.transports.websocket.server import (
        WebsocketServerParams,
        WebsocketServerTransport,
    )

    return WebsocketServerTransport(
        host=config.host,
        port=config.port,
        params=WebsocketServerParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=build_vad(),
            # The transport tells the pipeline when the applicant starts and
            # stops speaking, which is what lets the agent stop talking when
            # interrupted instead of finishing its sentence over them.
            vad_audio_passthrough=True,
        ),
    )


async def run_interview(*, transport, interview, config: VoiceConfig | None = None):
    """Run one interview to completion.

    `allow_interruptions` is on: someone answering a question they have already
    heard should not have to wait for the agent to finish reading it. In an
    intake interview the applicant is the one with the information, so the
    system yields to them.
    """
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask

    task = PipelineTask(
        build_pipeline(transport=transport, interview=interview, config=config),
        params=PipelineParams(allow_interruptions=True),
    )
    await PipelineRunner().run(task)
