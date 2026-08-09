"""Fallback chain: discovery, tiering, and lenient validation.

All offline except the two marked live. Discovery and tiering are pure
functions over the API's own metadata, so they are testable without a network.
"""

import pytest

from voxgate.config import get_settings
from voxgate.ml.groq_client import (
    EXCLUDED,
    MIN_CONTEXT,
    _matches,
    _useful,
    discover_models,
)


def model(**overrides):
    base = {
        "id": "openai/gpt-oss-120b",
        "active": True,
        "context_window": 131072,
        "max_completion_tokens": 65536,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "supported_features": ["tools", "json_mode", "structured_outputs"],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# Which models are worth calling
# --------------------------------------------------------------------------

def test_a_text_model_with_json_mode_is_useful():
    assert _useful(model())


def test_inactive_models_are_skipped():
    assert not _useful(model(active=False))


def test_audio_models_are_skipped():
    """Whisper: audio in, text out. Not a generator."""
    assert not _useful(model(id="whisper-large-v3-turbo",
                             input_modalities=["audio"],
                             output_modalities=["text"]))


def test_tts_models_are_skipped():
    """Orpheus: text in, audio out."""
    assert not _useful(model(id="canopylabs/orpheus-v1-english",
                             output_modalities=["audio"]))


def test_classifiers_are_skipped_by_context_not_by_name():
    """prompt-guard caps at 512. Filtering on context rather than a name list
    means a future classifier is excluded automatically."""
    assert not _useful(model(id="meta-llama/llama-prompt-guard-2-86m",
                             context_window=512,
                             supported_features=[]))
    assert not _useful(model(context_window=MIN_CONTEXT - 1))


def test_models_without_json_mode_are_skipped():
    """Without json_mode there is no way to get parseable structured output."""
    assert not _useful(model(supported_features=["tools"]))


def test_explicitly_excluded_models_are_skipped():
    """Agentic models measured at 9.2s TTFT. Capable, but not in a request path."""
    for excluded_id in EXCLUDED:
        assert not _useful(model(id=excluded_id))


# --------------------------------------------------------------------------
# Lenient-tier validation
# --------------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": "string", "enum": ["a", "b"]},
        "score": {"type": "number"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["value"],
}


def test_valid_payload_matches():
    assert _matches({"value": "a", "score": 0.5, "tags": ["x"]}, SCHEMA)


def test_missing_required_key_fails():
    assert not _matches({"score": 1}, SCHEMA)


def test_value_outside_the_enum_fails():
    """The whole point of the lenient tier: catch what the provider did not."""
    assert not _matches({"value": "z"}, SCHEMA)


def test_wrong_type_fails():
    assert not _matches({"value": "a", "score": "high"}, SCHEMA)


def test_booleans_are_not_numbers():
    """True == 1 in Python, so a naive isinstance check would let it through."""
    assert not _matches({"value": "a", "score": True}, SCHEMA)


def test_array_item_types_are_checked():
    assert not _matches({"value": "a", "tags": [1, 2]}, SCHEMA)


def test_non_dict_fails_an_object_schema():
    assert not _matches(["a"], SCHEMA)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def test_discovery_falls_back_when_it_cannot_reach_the_api():
    """Discovery is an optimisation. A bad key must degrade, never raise."""
    strict, lenient = discover_models("gsk_not_a_real_key", force=True)
    assert strict and lenient


REQUIRES_GROQ = pytest.mark.skipif(
    not get_settings().groq_api_key, reason="no Groq key configured"
)


@REQUIRES_GROQ
def test_live_discovery_tiers_by_reported_capability():
    strict, lenient = discover_models(get_settings().groq_key_pool()[0], force=True)
    assert strict, "expected at least one strict-capable model"
    # Tiers must not overlap: a model is either schema-enforced or it is not.
    assert not (set(strict) & set(lenient))
    # Nothing excluded should survive discovery.
    assert not (set(strict) | set(lenient)) & set(EXCLUDED)


@REQUIRES_GROQ
def test_live_discovery_excludes_audio_and_classifier_models():
    strict, lenient = discover_models(get_settings().groq_key_pool()[0], force=True)
    found = set(strict) | set(lenient)
    for unusable in ("whisper-large-v3", "whisper-large-v3-turbo",
                     "meta-llama/llama-prompt-guard-2-86m",
                     "canopylabs/orpheus-v1-english"):
        assert unusable not in found, unusable
