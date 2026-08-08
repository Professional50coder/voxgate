"""Groq free-tier LLM "brain" for interpreting spoken answers.

The browser voice session captures raw transcripts (e.g. "it's the twelfth of
march, nineteen ninety two"). Raw STT text can't be stored into an interview
field like an enum or an ISO date, so this module asks Groq (an
OpenAI-compatible endpoint) to extract the *canonical* value for the field
currently being asked, plus a confidence.

It is **optional** in VoxGate, exactly like ``contextdev.py``:
- No key configured -> ``interpret_answer`` returns the raw transcript trimmed,
  so callers still get a usable value.
- Everything is a small RFC7686-style no-op otherwise; no VoxGate core imports
  this module, and no code path requires it.
"""
import json
import os
import time
from datetime import datetime

import httpx

from voxgate.config import Settings, get_settings
from voxgate import tracing

GROQ_BASE = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"

_FIELD_FORMAT = {
    "full_name": "given name(s) then family name, spelled normally",
    "dob": "ISO date as YYYY-MM-DD",
    "nationality": "ISO 3166-1 alpha-2 country code (e.g. IN, GB, SY)",
    "residency_status": "one of: uae_resident | non_resident",
    "source_of_funds": "one of: salary | business_income | investments | inheritance | crypto_trading | other",
    "product": "one of: spot_trading | derivatives | custody",
}

_SYSTEM = (
    "You extract a single canonical value from a KYC voice-interview answer. "
    "Reply with ONLY a JSON object of the form "
    '{"value": <extracted value or null>, "confidence": <0.0 to 1.0>}. '
    "If the speaker's answer does not let you determine the value, value must be null. "
    "Do not invent values."
)

_AGENT_SYSTEM = (
    "You are VoxGate, a warm and efficient voice assistant running a one-question-at-a-time "
    "KYC compliance interview. You speak in a SINGLE short sentence that is easy to synthesize "
    "(no markdown, emojis, bullets, or numbering). You briefly acknowledge what the applicant "
    "just said, then ask exactly one field's question. You do not invent facts or repeat the "
    "applicant's answers at length. Reply with ONLY a JSON object: {\"line\": \"<one sentence>\"}."
)

_GREET_SYSTEM = (
    "You are VoxGate, a warm, professional voice assistant opening a short KYC identity-"
    "verification interview. The applicant can only hear you, so speak in ONE short, natural "
    "sentence (no markdown, emojis, bullets, or numbering). Greet them according to the current "
    "time of day, introduce yourself as VoxGate, and tell them the interview takes only a couple "
    "of minutes. Reply with ONLY a JSON object: {\"line\": \"<one sentence>\"}."
)

_GREET_FALLBACK = {
    "morning": "Good morning",
    "afternoon": "Good afternoon",
    "evening": "Good evening",
    "night": "Good evening",
}


def time_of_day(hour: int | None = None) -> str:
    """Return a friendly time-of-day bucket for the local hour (24h clock)."""
    h = datetime.now().hour if hour is None else (hour % 24)
    if h < 5 or h >= 22:
        return "night"
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    return "evening"


def greeting(*, name=None, hour=None, settings: Settings | None = None, model=None, session=""):
    """Produce the agent's opening spoken line: a time-of-day greeting + intro.

    Uses Groq when available (``source`` = "llm"); otherwise returns a natural
    template-based line (``source`` = "raw") so the session always has a greeting.
    ``hour`` may be supplied (e.g. the applicant's local time); defaults to server time.
    """
    pod = time_of_day(hour)
    base = _GREET_FALLBACK[pod]
    fallback = (
        f"{base}{', ' + name if name else ''}. I'm VoxGate. I'll run a short "
        "identity verification with you — I'll ask a few quick questions, so just "
        "answer naturally whenever you're ready."
    )
    if not _key(settings):
        return {"line": fallback, "source": "raw"}
    user = (
        f"Current local time of day: {pod}. Applicant name: {name or 'unknown'}.\n"
        "Say a warm one-sentence greeting, introduce yourself as VoxGate, and mention "
        "that this is a short identity-verification interview."
    )
    data = _chat_json(user, _GREET_SYSTEM, settings=settings, model=model, session=session or "")
    try:
        line = (data or {}).get("line")
    except AttributeError:
        line = None
    if line:
        return {"line": line, "source": "llm"}
    return {"line": fallback, "source": "raw"}


def _chat_json(user, system, *, settings=None, model=None, session=""):
    """Call Groq and parse a JSON response, or return None on any failure."""
    api_key = _key(settings)
    if not api_key:
        return None
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t0 = time.perf_counter()
    data = None
    error = None
    status = None
    try:
        r = httpx.post(f"{GROQ_BASE}/chat/completions", json=payload, headers=headers, timeout=30.0)
        status = getattr(r, "status_code", None)
        r.raise_for_status()
        data = json.loads(r.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
        error = f"{type(e).__name__}: {e}"
        data = None
    tracing.write(settings, session=session, category="groq.chat", provider="groq",
                  model=payload["model"], ok=data is not None, http_status=status,
                  error=error or None, duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                  system=system, user=user)
    return data


def _key(settings: Settings | None = None) -> str | None:
    if settings is None:
        settings = get_settings()
    if settings.groq_api_key:
        return settings.groq_api_key
    return os.environ.get("GROQ_API_KEY")


def is_enabled(settings: Settings | None = None) -> bool:
    return bool(_key(settings))


def _field_format(field: str) -> str:
    return _FIELD_FORMAT.get(field, "plain text")


def interpret_answer(field, transcript, *, hints=None, settings: Settings | None = None, model=None,
                     session=""):
    """Interpret a spoken answer for `field`. Returns {value, confidence, source}.

    ``source`` is ``"llm"`` when Groq answered, else ``"raw"`` for the fallback.
    """
    text = (transcript or "").strip()
    api_key = _key(settings)
    if not api_key or not text:
        return {"value": text or None, "confidence": 0.5, "source": "raw"}

    user = (
        f"Field: {field}\n"
        f"Required format: {_field_format(field)}\n"
        f"Hints: {hints or 'none'}\n"
        f"Spoken answer: \"{text}\""
    )
    data = _chat_json(user, _SYSTEM, settings=settings, model=model, session=session or "")
    if data is None:
        return {"value": text or None, "confidence": 0.5, "source": "raw"}
    return {
        "value": data.get("value"),
        "confidence": float(data.get("confidence") or 0.5),
        "source": "llm",
    }


def agent_line(field, hint, *, last_captured=None, transcript=None, attempt=0,
               settings: Settings | None = None, model=None, session=""):
    """Craft the agent's NEXT spoken line for the interview.

    Pipecat-style conversational turn: briefly acknowledge the last captured
    field, then ask the one question for `field` — or ask for clarification when
    a previous answer wasn't understood (attempt >= 1). Returns:
    {line, source} where source is "llm" or "raw" (the hint fallback).
    """
    bits = [f"Field you must ask about: {field}", f"Expected format: {_field_format(field)}"]
    if hint:
        bits.append(f"A natural phrasing you may use: \"{hint}\"")
    if last_captured and last_captured.get("value") not in (None, ""):
        bits.append(
            f"The applicant just told you: {last_captured.get('field')} = {last_captured.get('value')}. "
            "Acknowledge this in at most a few words, then ask the field above."
        )
    elif transcript:
        bits.append(f"The applicant last said (may be unclear): \"{transcript}\"")
    if attempt >= 1:
        bits.append(
            f"Clarification attempt #{attempt}: the applicant's answer was not understood. "
            "Ask again more clearly, or ask them to spell it or choose from the options if the field has a set."
        )
    else:
        bits.append("Ask this field as a single, natural question.")
    data = _chat_json("\n".join(bits), _AGENT_SYSTEM, settings=settings, model=model,
                      session=session or "")
    try:
        line = (data or {}).get("line")
    except AttributeError:
        line = None
    if line:
        return {"line": line, "source": "llm"}
    return {"line": hint or f"Could you tell me your {field.replace('_', ' ')}?", "source": "raw"}