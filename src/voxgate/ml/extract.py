"""Map a spoken answer onto the exact value a pack's schema requires.

People do not answer like forms. "about two and a half years now" has to become
`one_to_three`, and "we only moved in back in spring" has to become `under_1`.
Keyword matching cannot do this: neither sentence contains a keyword worth
matching on.

Two implementations behind one protocol:

  KeywordExtractor  deterministic, offline, no key. Used by the test suite and
                    as the fallback whenever Groq is unavailable or unsure.
  GroqExtractor     an LLM constrained by a JSON schema whose enum is the pack's
                    own allowed values, so it is structurally incapable of
                    returning a value the schema would reject.

The division of labour matters and is deliberate: the LLM decides *what the
person said*. It never decides what happens next. Routing, scoring and the
approve/reject decision stay in the graph, which is what keeps the audit trail
meaningful.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from voxgate.ml.understanding import is_non_answer

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM = (
    "You map a spoken answer onto one allowed value. Choose the single closest "
    "value. Never invent a value outside the list. confidence is 0..1 for how "
    "certain the mapping is; use a low value when the answer is ambiguous or "
    "does not address the question."
)


@dataclass(frozen=True)
class Extraction:
    """One mapped answer.

    `value` is None when nothing could be mapped, which the caller should treat
    as a re-ask rather than as a failure.
    """

    value: str | None
    confidence: float
    source: str  # "keyword" | "groq" | "passthrough"


@runtime_checkable
class FieldExtractor(Protocol):
    def extract(self, field: str, allowed: list[str] | None, spoken: str) -> Extraction:
        ...


# Spoken lead-ins that are never part of the value: "erm, it's Fatima" is
# Fatima. Repeated, because people stack them ("um, well, my name is...").
_LEAD_IN = re.compile(
    r"^\s*(?:(?:u+m+|e+r+m*|u+h+|a+h+|well|so|okay|ok|yeah|yes|sure|right)[\s,.]+"
    r"|(?:it'?s|it\s+is|that'?s|that\s+is|i'?m|i\s+am|this\s+is|call\s+me"
    r"|my\s+(?:full\s+|legal\s+)?(?:name|answer)\s+is|the\s+answer\s+is)\s+)+",
    re.I)


def strip_lead_in(spoken: str) -> str:
    """Drop spoken filler and "my name is"-style lead-ins from a free-text answer."""
    return _LEAD_IN.sub("", spoken.strip()).strip(" .,!") or spoken.strip()


_FREE_SYSTEM = (
    "You pull the answer to one interview question out of what a person said. "
    "Return the value exactly as they gave it, without filler or lead-ins "
    "(\"erm, it's Fatima Al Mansoori\" -> \"Fatima Al Mansoori\"). Normalise dates "
    "to YYYY-MM-DD. If what they said does not actually contain the answer "
    "(they deflected, guessed someone else would know, or talked about something "
    "else) set found to false. Never invent or complete a value."
)

_FREE_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "value": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["found", "value", "confidence"],
    "additionalProperties": False,
}


def grounded(value: str, spoken: str) -> bool:
    """True when every word of the value was actually said.

    The guard against a model completing a name or inventing a detail. Values
    with digits are exempt, because normalising "fifth of March 1990" to
    1990-03-05 is the point and cannot pass a word check.
    """
    if re.search(r"\d", value):
        return True
    said = set(re.findall(r"[a-z']+", spoken.lower()))
    words = [w for w in re.findall(r"[a-z']+", value.lower()) if len(w) > 1]
    return bool(words) and all(w in said for w in words)


class KeywordExtractor:
    """Offline fallback. Substring and token overlap against the value names.

    Deliberately conservative: it would rather return None and trigger a re-ask
    than guess. That is the correct failure mode for an interview whose answers
    feed a compliance decision.
    """

    def extract(self, field: str, allowed: list[str] | None, spoken: str) -> Extraction:
        text = spoken.strip().lower()
        if not text:
            return Extraction(None, 0.0, "keyword")

        if allowed is None:
            # A free-text field takes the transcript as the value, so it is the
            # ONLY place a non-answer can be stored verbatim. It used to be:
            # an applicant who said "I don't know" to every question had that
            # recorded as their legal name and their source of funds, and the
            # case reached a reviewer looking complete. An enum field was never
            # exposed this way, because the value has to be in the allowed set.
            if is_non_answer(spoken):
                return Extraction(None, 0.0, "non-answer")
            cleaned = strip_lead_in(spoken)
            if is_non_answer(cleaned):
                return Extraction(None, 0.0, "non-answer")
            return Extraction(cleaned, 0.6, "passthrough")

        # Exact value spoken back, e.g. an operator typing the literal.
        for value in allowed:
            if value.lower() == text:
                return Extraction(value, 1.0, "keyword")

        # Whole value name appearing in the sentence, longest first so
        # "mortgage_approved" wins over "mortgage_pending" on a shared prefix.
        for value in sorted(allowed, key=len, reverse=True):
            if value.replace("_", " ").lower() in text:
                return Extraction(value, 0.8, "keyword")

        # Token overlap. Requires every token of the value to be present, which
        # keeps "one" from matching "one_to_three" on its own.
        best: tuple[str, float] | None = None
        for value in allowed:
            tokens = [t for t in re.split(r"[_\s]+", value.lower()) if t.isalpha()]
            if not tokens:
                continue
            present = sum(1 for t in tokens if t in text)
            if present == len(tokens):
                score = 0.55 + 0.05 * len(tokens)
                if best is None or score > best[1]:
                    best = (value, score)
        if best:
            return Extraction(best[0], best[1], "keyword")

        return Extraction(None, 0.0, "keyword")


class GroqExtractor:
    """Groq-backed extraction, constrained by the pack's own allowed values.

    Falls back to KeywordExtractor on any failure: no key, network error, rate
    limit, or a confidence below `floor`. An interview must never break because
    a hosted API had a bad minute.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        floor: float = 0.55,
        timeout: float = 12.0,
    ):
        from voxgate.config import get_settings

        settings = get_settings()
        self.model = model or settings.groq_model
        # An explicit api_key (including "" in tests) overrides the pool.
        self.keys = [api_key] if api_key is not None else settings.groq_key_pool()
        self.keys = [k for k in self.keys if k]
        self.floor = floor
        self.timeout = timeout
        self._fallback = KeywordExtractor()

    @property
    def api_key(self) -> str | None:
        return self.keys[0] if self.keys else None

    @property
    def available(self) -> bool:
        return bool(self.keys)

    def extract(self, field: str, allowed: list[str] | None, spoken: str) -> Extraction:
        if not spoken.strip():
            return Extraction(None, 0.0, "groq")
        if not self.available:
            return self._fallback.extract(field, allowed, spoken)
        if allowed is None:
            return self._extract_free(field, spoken)

        # Extraction is the highest-volume LLM path in the product: once per
        # interview question, per applicant. It needs the model+key fallback
        # MORE than drafting does, not less. Routing it through the shared
        # client was missed the first time, and the symptom was extraction
        # silently degrading to keyword matching under load, which reads as
        # "the model got worse" rather than "we ran out of quota".
        from voxgate.ml.groq_client import GroqError, structured_call

        schema = {
            "type": "object",
            "properties": {
                "value": {"type": "string", "enum": list(allowed)},
                "confidence": {"type": "number"},
            },
            "required": ["value", "confidence"],
            "additionalProperties": False,
        }

        try:
            result = structured_call(
                api_keys=self.keys,
                system=SYSTEM,
                user=f"Field: {field}\nSpoken answer: {spoken!r}",
                schema=schema,
                schema_name="extraction",
                preferred_model=self.model,
                temperature=0,
                max_tokens=200,
                timeout=self.timeout,
            )
        except GroqError:
            # Covers rate limiting and every other provider failure. An
            # interview must never break because a hosted API had a bad minute.
            return self._fallback.extract(field, allowed, spoken)

        value = result.content.get("value")
        confidence = float(result.content.get("confidence", 0.0))

        # The schema enum makes an out-of-range value impossible on the strict
        # tier, and the client validates the lenient tier. Checked anyway: this
        # value lands on a compliance record.
        if value not in allowed or confidence < self.floor:
            fallback = self._fallback.extract(field, allowed, spoken)
            return fallback if fallback.value else Extraction(None, confidence, "groq")

        return Extraction(value, confidence, "groq")

    def _extract_free(self, field: str, spoken: str) -> Extraction:
        """A free-text field: the value inside the sentence, or nothing.

        Without this a free-text field stored the whole transcript, so "erm my
        brother handles all that" became someone's legal name.
        """
        fallback = self._fallback.extract(field, None, spoken)
        if fallback.value is None:
            return fallback  # the patterns already know it is not an answer
        from voxgate.ml.groq_client import GroqError, structured_call
        try:
            result = structured_call(
                api_keys=self.keys, system=_FREE_SYSTEM,
                user=f"Field: {field.replace('_', ' ')}\nThey said: {spoken!r}",
                schema=_FREE_SCHEMA, schema_name="free_extraction",
                preferred_model=self.model, temperature=0, max_tokens=200,
                timeout=self.timeout)
        except GroqError:
            return fallback
        content = result.content
        value = str(content.get("value", "")).strip()
        confidence = float(content.get("confidence", 0.0))
        if not content.get("found") or not value:
            return Extraction(None, confidence, "groq")
        if not grounded(value, spoken):
            # The model produced words that were never said. Keep the cleaned
            # transcript, at the lower passthrough confidence, rather than them.
            return fallback
        return Extraction(value, max(min(confidence, 1.0), 0.0), "groq")


def allowed_values(schema_model, field: str) -> list[str] | None:
    """Read a field's permitted values out of the pack schema.

    Packs declare these as a module-level `VALID_<FIELD>` set next to the
    validator that enforces them, so the extractor and the validator can never
    disagree about what is acceptable.
    """
    module = getattr(schema_model, "__module__", None)
    import sys

    mod = sys.modules.get(module) if module else None
    if mod is None:
        return None
    values = getattr(mod, f"VALID_{field.upper()}", None)
    return sorted(values) if values else None


def build_extractor() -> FieldExtractor:
    """Groq when a key is present, deterministic keyword matching otherwise.

    This is what keeps the test suite offline and keyless by default.
    """
    groq = GroqExtractor()
    return groq if groq.available else KeywordExtractor()
