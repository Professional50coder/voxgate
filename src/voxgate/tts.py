"""Human-sounding speech: Cartesia, main voice first, fallback second.

Pure httpx, no pipecat, so the API can serve speech to the browser from a
serverless function and the voice worker can probe a voice before a call.

The order is the pack agent's: ``voice.primary`` then ``voice.fallback``. When
both fail, or no key is configured, callers drop to their local voice (Kokoro
in the worker, the browser's own voice on the web), so speech degrades and
never stops.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from voxgate.config import Settings, get_settings
from voxgate.packs.agent import VoiceProfile

CARTESIA_TTS_URL = "https://api.cartesia.ai/tts/bytes"
CARTESIA_VERSION = "2025-04-16"

# A spoken prompt is a sentence or three. Anything longer is a misuse of a
# public endpoint, and capping it caps the cost of one request.
MAX_CHARS = 600


class TTSUnavailable(Exception):
    """No configured voice could speak. The caller uses its local voice."""


@dataclass(frozen=True)
class Speech:
    audio: bytes
    media_type: str
    voice_id: str
    #: "primary" or "fallback": which of the agent's voices actually spoke.
    tier: str
    ms: float


def synthesize(text: str, voice: VoiceProfile, settings: Settings | None = None,
               *, timeout: float = 8.0) -> Speech:
    import httpx

    settings = settings or get_settings()
    if not settings.cartesia_api_key:
        raise TTSUnavailable("no CARTESIA_API_KEY configured")
    text = (text or "").strip()[:MAX_CHARS]
    if not text:
        raise TTSUnavailable("nothing to say")

    tiers = [("primary", voice.primary)]
    if voice.fallback and voice.fallback != voice.primary:
        tiers.append(("fallback", voice.fallback))

    last = "no voice tried"
    for tier, voice_id in tiers:
        t0 = time.perf_counter()
        try:
            response = httpx.post(
                CARTESIA_TTS_URL,
                headers={"X-API-Key": settings.cartesia_api_key,
                         "Cartesia-Version": CARTESIA_VERSION},
                json={
                    "model_id": settings.cartesia_model,
                    "transcript": text,
                    "language": voice.language,
                    "voice": {"mode": "id", "id": voice_id},
                    "generation_config": {"speed": voice.speed},
                    "output_format": {"container": "mp3", "sample_rate": 44100,
                                      "bit_rate": 128000},
                },
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            last = f"{tier}: {type(exc).__name__}"
            continue
        if response.status_code == 200 and response.content:
            return Speech(response.content, "audio/mpeg", voice_id, tier,
                          round((time.perf_counter() - t0) * 1000, 1))
        last = f"{tier}: HTTP {response.status_code}"
    raise TTSUnavailable(last)


def pick_voice(voice: VoiceProfile, settings: Settings | None = None) -> tuple[str, str] | None:
    """The first of the agent's voices that speaks right now, as (tier, id).

    Called once before a phone call starts, so a dead primary costs one short
    probe instead of a silent call. None means use the local voice.
    """
    try:
        speech = synthesize("Hello.", voice, settings, timeout=4.0)
    except TTSUnavailable:
        return None
    return speech.tier, speech.voice_id
