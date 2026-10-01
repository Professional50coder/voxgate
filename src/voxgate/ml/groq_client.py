"""Groq calls with automatic model and key fallback.

Groq's rate limits are **per key AND per model**. A 429 on `gpt-oss-120b` with
key A therefore says nothing about `gpt-oss-120b` with key B, nor about
`gpt-oss-20b` with key A. Walking both dimensions is a genuine recovery rather
than a retry into the same wall, and the effective headroom is keys x models.

Two tiers, because `json_mode` and `json_schema` are different guarantees and
conflating them would quietly weaken the contract:

  STRICT   models supporting `json_schema` + `strict: true`. The provider
           enforces the schema, so the response cannot be the wrong shape.
  LENIENT  models supporting only `json_mode`. The provider guarantees valid
           JSON and nothing more, so the schema is embedded in the prompt and
           the response is validated here. A response failing validation is
           discarded and the walk continues.

Strict models are always tried first. A lenient model is reached only once
every strict model on every key is rate limited, which is exactly the situation
where "validated locally" beats "no answer at all".

Free-tier limits measured 2026-08-07, per key per model:
  gpt-oss-120b / -20b / -safeguard-20b   30 RPM, 8K TPM, 1K RPD
  llama-3.3-70b-versatile                30 RPM, 12K TPM, 1K RPD
  llama-3.1-8b-instant                   30 RPM, 6K TPM, 14.4K RPD
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MODELS_URL = "https://api.groq.com/openai/v1/models"

# Fallback used only when discovery fails (offline, bad key). Verified working
# 2026-08-07, but discovery is authoritative: a hardcoded list goes stale the
# moment Groq ships or retires a model.
_SEED_STRICT = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
_SEED_LENIENT = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

# Models excluded regardless of capability, with the reason. Each is a real
# measurement, not a guess.
EXCLUDED = {
    "groq/compound": "agentic, 9.2s TTFT measured, unusable in a request path",
    "groq/compound-mini": "agentic, 1.3s TTFT and still the slowest non-agentic option",
}

# A generator needs room to think. Classifiers like llama-prompt-guard cap at
# 512 and are excluded by this rather than by name.
MIN_CONTEXT = 8192

STRICT_MODELS: list[str] = list(_SEED_STRICT)
LENIENT_MODELS: list[str] = list(_SEED_LENIENT)
FALLBACK_CHAIN: list[str] = STRICT_MODELS + LENIENT_MODELS

_discovery_cache: dict[str, Any] = {"at": 0.0, "strict": None, "lenient": None}
_DISCOVERY_TTL = 900.0  # seconds

# Per-process health marks, so a revoked key or a retired model costs one
# failed request rather than one per call for the life of the process.
_dead_keys: set[str] = set()                # 401/403: Groq rejected the key
_key_cooldown: dict[str, float] = {}        # 429: monotonic time it may lead again
_demoted_models: dict[str, float] = {}      # 404: monotonic time to retry it
_COOLDOWN_SECS = 60.0

_client = None  # pooled httpx.Client, created on first call
try:
    import httpx as _httpx
    _REAL_POST = _httpx.post
except ImportError:  # pragma: no cover - httpx is a core dependency
    _REAL_POST = None


def reset_health() -> None:
    """Forget every health mark. For tests, and after rotating keys."""
    _dead_keys.clear()
    _key_cooldown.clear()
    _demoted_models.clear()


def key_health(keys: list[str]) -> list[dict[str, Any]]:
    """Per-key status for an operator view. Never includes the key itself."""
    now = time.monotonic()
    return [{"index": i,
             "status": "dead" if k in _dead_keys
             else "cooling" if _key_cooldown.get(k, 0.0) > now else "ok"}
            for i, k in enumerate(keys)]


def _useful(model: dict[str, Any]) -> bool:
    """Is this model usable for structured text generation?

    Filters on what the API actually reports rather than on names, so a model
    Groq adds tomorrow is picked up without a code change.
    """
    if not model.get("active"):
        return False
    if model.get("id") in EXCLUDED:
        return False
    if "text" not in (model.get("input_modalities") or []):
        return False
    if "text" not in (model.get("output_modalities") or []):
        return False
    if (model.get("context_window") or 0) < MIN_CONTEXT:
        return False
    # json_mode is the floor: without it there is no way to get parseable
    # structured output at all.
    return "json_mode" in (model.get("supported_features") or [])


def discover_models(api_key: str, *, force: bool = False) -> tuple[list[str], list[str]]:
    """Return (strict, lenient) model ids, discovered from the API.

    Tiering is read from `supported_features`, so a model is only trusted with
    strict schema enforcement when Groq says it supports it. Results are cached
    briefly: the catalogue changes on the order of weeks, not requests.
    """
    import time

    now = time.time()
    if (
        not force
        and _discovery_cache["strict"] is not None
        and now - _discovery_cache["at"] < _DISCOVERY_TTL
    ):
        return _discovery_cache["strict"], _discovery_cache["lenient"]

    try:
        import httpx

        response = httpx.get(
            MODELS_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=15.0
        )
        response.raise_for_status()
        models = [m for m in response.json().get("data", []) if _useful(m)]
    except Exception:
        # Discovery is an optimisation, never a hard dependency.
        return list(_SEED_STRICT), list(_SEED_LENIENT)

    # Larger output capacity first within each tier: drafting a whole pack is
    # the most output-hungry call this client makes.
    models.sort(key=lambda m: -(m.get("max_completion_tokens") or 0))

    strict, lenient = [], []
    for m in models:
        features = m.get("supported_features") or []
        (strict if "structured_outputs" in features else lenient).append(m["id"])

    if not strict and not lenient:
        return list(_SEED_STRICT), list(_SEED_LENIENT)

    _discovery_cache.update(at=now, strict=strict, lenient=lenient)
    return strict, lenient


def _matches(value: Any, schema: dict[str, Any]) -> bool:
    """Structural check for lenient-mode responses.

    Not a full JSON Schema implementation, deliberately. It covers the shapes
    this codebase actually sends (typed objects, required keys, string enums,
    arrays of objects) and returns False for anything it cannot confirm.
    Rejecting an unrecognised shape is the safe direction.
    """
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            return False
        for key in schema.get("required", []):
            if key not in value:
                return False
        for key, sub in (schema.get("properties") or {}).items():
            if key in value and not _matches(value[key], sub):
                return False
        return True
    if expected == "array":
        items = schema.get("items")
        return isinstance(value, list) and (
            items is None or all(_matches(v, items) for v in value)
        )
    if expected == "string":
        if not isinstance(value, str):
            return False
        allowed = schema.get("enum")
        return value in allowed if allowed else True
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


class GroqError(Exception):
    """A Groq call failed for a reason other than quota."""


class GroqRateLimited(GroqError):
    """Every (model, key) pair returned 429.

    Distinguished from a generic failure because the caller should respond
    differently: a UI says "try again shortly", a test skips rather than fails.
    """


@dataclass(frozen=True)
class GroqResult:
    content: dict
    model: str           # which model actually answered
    attempts: int        # how many (model, key) pairs were tried
    fell_back: bool      # True when the first pair was not the one that answered
    key_index: int = 0   # which key in the pool answered
    strict: bool = True  # False when the schema was enforced here, not by Groq


def structured_call(
    *,
    api_key: str | None = None,
    api_keys: list[str] | None = None,
    system: str,
    user: str,
    schema: dict[str, Any],
    schema_name: str,
    preferred_model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 2000,
    timeout: float = 45.0,
    reasoning_effort: str = "low",
) -> GroqResult:
    """Call Groq for structured JSON, walking models then keys on rate limits.

    Order is **model-major, key-minor**: every key is tried on the best model
    before degrading to a weaker one. Quota is per key AND per model, so the
    effective headroom is keys x models, and this ordering spends it in the
    order that keeps answer quality highest.

    Raises GroqRateLimited only when every (model, key) pair is exhausted. A
    non-429 error advances to the next pair, because a model-specific rejection
    should not fail the whole request.
    """
    import httpx

    # Keep-alive across calls: a fresh TLS handshake costs ~100-300 ms, which
    # is a real share of a conversational turn. Tests that patch httpx.post
    # get it called directly, so they keep working unchanged.
    global _client
    if _client is None:
        _client = httpx.Client(limits=httpx.Limits(max_keepalive_connections=8))
    _pooled = _client if httpx.post is _REAL_POST else None

    keys = [k for k in (api_keys or []) if k]
    if api_key and api_key not in keys:
        keys.insert(0, api_key)
    if not keys:
        raise GroqError("No Groq key supplied")

    strict_models, lenient_models = discover_models(keys[0])

    chain: list[str] = []
    if preferred_model:
        chain.append(preferred_model)
    # Strict tier exhausted before any lenient model is tried, so schema
    # enforcement is only given up when there is no alternative.
    for model in strict_models + lenient_models:
        if model not in chain:
            chain.append(model)

    # Model-major, key-minor: exhaust every key on the best model before
    # degrading. Built explicitly so the order is inspectable, not implied by
    # loop nesting.
    # Skip keys Groq has rejected and models it no longer serves, but never
    # filter down to nothing: a stale mark must not turn into a hard outage.
    now = time.monotonic()
    usable_keys = [k for k in keys if k not in _dead_keys] or keys
    usable_models = [m for m in chain if _demoted_models.get(m, 0.0) <= now] or chain
    # Keys on a 429 cooldown go to the back of each model's turn, not out.
    usable_keys.sort(key=lambda k: _key_cooldown.get(k, 0.0) > now)
    pairs = [(model, keys.index(key), key)
             for model in usable_models
             for key in usable_keys]

    last_error: Exception | None = None
    rate_limited_all = True

    for attempt, (model, key_index, key) in enumerate(pairs, start=1):
        try:
            is_strict = model in strict_models
            if is_strict:
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                }
                system_prompt = system
            else:
                # json_mode guarantees parseable JSON, not the right shape, so
                # the schema goes in the prompt and is verified below.
                response_format = {"type": "json_object"}
                system_prompt = (
                    system
                    + "\n\nRespond with JSON matching exactly this schema, "
                    "and nothing else:\n"
                    + json.dumps(schema)
                )

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
                "response_format": response_format,
            }
            if model.startswith("openai/gpt-oss"):
                # Every call here is a mapping or a short reply, not a puzzle.
                # Default reasoning roughly doubles latency for no gain.
                payload["reasoning_effort"] = reasoning_effort
            response = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
                timeout=timeout,
            ) if _pooled is None else _pooled.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
                timeout=timeout,
            )
            if response.status_code == 429:
                # Quota is per key AND per model, so the next pair is a genuine
                # retry rather than the same wall. No sleep: we are not retrying
                # the same pair.
                last_error = GroqRateLimited(f"{model} key#{key_index + 1} rate limited")
                _key_cooldown[key] = time.monotonic() + _COOLDOWN_SECS
                continue
            if response.status_code in (401, 403):
                _dead_keys.add(key)
            elif response.status_code == 404:
                _demoted_models[model] = time.monotonic() + _DISCOVERY_TTL

            response.raise_for_status()
            content = json.loads(response.json()["choices"][0]["message"]["content"])

            if not is_strict and not _matches(content, schema):
                # Valid JSON, wrong shape. Discard and keep walking rather than
                # hand the caller a value its own schema would reject.
                rate_limited_all = False
                last_error = GroqError(f"{model} returned JSON not matching the schema")
                continue

            return GroqResult(
                content=content,
                model=model,
                strict=is_strict,
                attempts=attempt,
                fell_back=attempt > 1,
                key_index=key_index,
            )

        except httpx.HTTPStatusError as exc:
            rate_limited_all = False
            last_error = GroqError(f"{model} returned {exc.response.status_code}")
            continue
        except Exception as exc:  # network, timeout, malformed JSON
            rate_limited_all = False
            last_error = GroqError(f"{model} failed: {exc}")
            continue

    if rate_limited_all:
        raise GroqRateLimited(
            f"All {len(chain)} models across {len(keys)} key(s) are rate limited. "
            "Free tier is 30 requests per minute per key per model; try again shortly."
        )
    raise GroqError(str(last_error) if last_error else "No model produced a result")
