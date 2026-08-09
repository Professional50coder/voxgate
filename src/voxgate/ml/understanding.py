"""What did the applicant actually just do?

Extraction answers "which allowed value does this map to". It cannot answer the
prior question — is this an answer at all? — and that omission was a real
defect, not a missing nicety: free-text fields took whatever was said at
confidence 0.6, so an applicant who replied "I don't know" to every question had
"I don't know" recorded as their legal name and their source of funds, and the
case reached a reviewer looking complete.

So every utterance is classified before it is extracted. The classification is
deliberately **deterministic** — ordered patterns, no model. Three reasons:

  it is on the hot path      once per answer per applicant, ahead of an
                             extraction call that already costs a round trip
  it must not be persuadable an applicant who says "ignore your instructions"
                             is matched against a regex, not reasoned with
  it has to be testable      every branch below is asserted, which is not
                             something you can say about a model's judgement

Patterns are the wrong tool for open-ended meaning and the right tool for this,
because the set being detected is small, closed and phrased in a handful of
conventional ways. Anything that is not recognisably one of them falls through
to ANSWER and the extractor decides — so the failure mode is "treated as an
answer and validated", which is what used to happen to everything anyway.
"""

from __future__ import annotations

import re
from enum import Enum


class Intent(str, Enum):
    """What the utterance is doing, not what it contains."""

    ANSWER = "answer"
    #: "I don't know", "no idea". Genuinely does not have the information.
    DONT_KNOW = "dont_know"
    #: "What do you mean by that?" — needs the question explained, not repeated.
    QUESTION = "question"
    #: "I'd rather not say." Has the information and is declining to give it.
    REFUSAL = "refusal"
    #: "Sorry, what?" — heard nothing. Repeat verbatim; not a failed attempt.
    REPEAT = "repeat"
    #: "Actually, I meant..." — replacing an answer already given.
    CORRECTION = "correction"


# Ordered, and the order is load-bearing. "I don't know what you mean" is a
# QUESTION, not a DONT_KNOW: the applicant is telling you the question failed,
# not that the information is unavailable. Matching DONT_KNOW first would send
# them round a loop of the same words. QUESTION is therefore tested first, and
# its patterns are anchored on the interrogative rather than on "know".
_PATTERNS: list[tuple[Intent, re.Pattern]] = [
    (Intent.REPEAT, re.compile(
        r"\b(say|repeat)\s+(that|it|the\s+question)?\s*(again|one\s+more\s+time)?\b"
        r"|\bcome\s+again\b|\bpardon\b|^\s*(sorry|what)\s*[?.]?\s*$",
        re.I)),
    (Intent.QUESTION, re.compile(
        r"\bwhat\s+do\s+you\s+mean\b|\bwhat'?s?\s+(that|this)\s+mean\b"
        r"|\bwhat\s+does\s+(that|this|it)\s+mean\b"
        r"|\bwhy\s+(do\s+you|are\s+you|is\s+that)\b"
        r"|\bwhat\s+(counts|qualifies|do\s+you\s+need)\b"
        r"|\bcan\s+you\s+explain\b|\bnot\s+sure\s+what\s+you\s+mean\b"
        r"|\bdon'?t\s+know\s+what\s+you\s+mean\b|\bwhat\s+are\s+the\s+options\b",
        re.I)),
    (Intent.CORRECTION, re.compile(
        r"\b(actually|sorry|no)\b[,\s]+(i\s+)?(meant|mean|it'?s|that'?s)\b"
        r"|\blet\s+me\s+(start\s+)?(over|again)\b|\bi\s+made\s+a\s+mistake\b"
        r"|\bcan\s+i\s+change\b|\bscratch\s+that\b",
        re.I)),
    (Intent.REFUSAL, re.compile(
        r"\b(i'?d\s+)?(rather|prefer)\s+not\b|\bnot\s+(telling|saying|answering)\b"
        r"|\bi\s+won'?t\s+(say|answer|tell)\b|\bnone\s+of\s+your\s+business\b"
        r"|\b(skip|pass|next)\s*(this|that|it|question)?\s*[.!]?\s*$"
        r"|\bdecline\s+to\s+answer\b|\bwhy\s+should\s+i\s+tell\b",
        re.I)),
    (Intent.DONT_KNOW, re.compile(
        r"\b(i\s+)?(don'?t|do\s+not)\s+know\b|\bno\s+idea\b|\bnot\s+sure\b"
        r"|\bcan'?t\s+remember\b|\bdon'?t\s+remember\b|\bunsure\b"
        r"|\bi'?m\s+not\s+certain\b|\bhaven'?t\s+got\s+a\s+clue\b"
        r"|^\s*(dunno|idk)\s*[.!]?\s*$|\bnot\s+off\s+the\s+top\b",
        re.I)),
]

# Bare tokens that are only ever non-answers. Matched on the WHOLE utterance,
# because "salary" is a fine answer while "n/a" never is.
#
# "skip" and "pass" are deliberately NOT here. They are refusals -- a decision
# to move on, not an absence of information -- and the distinction reaches the
# reviewer, who treats "would not say" and "did not know" very differently.
_BARE_NON_ANSWERS = {
    "", "n/a", "na", "none", "nothing", "no comment", "unknown", "unsure",
    "dunno", "idk", "?", "-", "--", "null", "nil", "blank",
    "no idea", "not applicable", "prefer not to say", "decline",
}


def classify(spoken: str) -> Intent:
    """What the applicant just did. Falls through to ANSWER when unrecognised.

    Falling through is the safe default: an unrecognised utterance is handed to
    the extractor, which validates it against the pack's allowed values. The
    worst case is the behaviour that existed before this function did.
    """
    text = (spoken or "").strip()
    if not text:
        return Intent.DONT_KNOW

    if text.lower().strip(" .!?") in _BARE_NON_ANSWERS:
        return Intent.DONT_KNOW

    for intent, pattern in _PATTERNS:
        if pattern.search(text):
            return intent

    return Intent.ANSWER


def is_non_answer(spoken: str) -> bool:
    """True when this must never be stored as a field value.

    The direct guard for the free-text hole. Enum fields were always safe
    because the value has to be in the allowed set; text fields accepted the
    transcript verbatim, so this is what stands between "I don't know" and a
    compliance record that says the applicant's name is "I don't know".

    Deliberately broader than `classify(...) is ANSWER`: a REFUSAL and a
    QUESTION are also not values, and so is anything under two characters,
    which is a transcription artefact rather than a name.
    """
    text = (spoken or "").strip()
    if len(text.strip(" .!?,")) < 2:
        return True
    return classify(text) is not Intent.ANSWER


# --------------------------------------------------------------------------
# The model-backed second opinion
# --------------------------------------------------------------------------

_INTENT_SYSTEM = (
    "You classify what a person just DID in an interview, not what they said. "
    "Return exactly one label. "
    "answer: they attempted to answer the question, even partially or vaguely. "
    "dont_know: they do not have the information. "
    "question: they asked you something, or said the question was unclear. "
    "refusal: they have the information and are declining to give it. "
    "repeat: they did not hear you. "
    "correction: they are changing an answer they already gave."
)


def classify_with_model(
    spoken: str,
    question: str | None = None,
    api_keys: list[str] | None = None,
    timeout: float = 8.0,
) -> Intent | None:
    """A second opinion for utterances the patterns did not recognise.

    Returns None on any failure, so the caller keeps whatever the deterministic
    layer decided. This is an enhancement, never a dependency: the interview
    works with no key, no network and no model, and gets better with them.

    **Where this is allowed to sit.** It classifies; it does not compose. The
    model never writes a question, never decides what to ask next and never sees
    the case — it answers one closed question with one of six labels, and an
    answer outside that set is discarded. So the worst a hostile or confused
    utterance can achieve is a wrong branch in a conversation, not a reworded
    regulated question and not a decision.

    Called only after the patterns fell through AND extraction failed, so it
    costs nothing on the path where things are going well. That ordering is the
    reason it can be a model call at all: it happens once per genuinely stuck
    field, not once per answer.
    """
    text = (spoken or "").strip()
    if not text:
        return None

    from voxgate.config import get_settings

    keys = api_keys if api_keys is not None else get_settings().groq_key_pool()
    if not keys:
        return None

    from voxgate.ml.groq_client import GroqError, structured_call

    schema = {
        "type": "object",
        "properties": {"intent": {"type": "string", "enum": [i.value for i in Intent]}},
        "required": ["intent"],
        "additionalProperties": False,
    }
    asked = f"Question asked: {question!r}\n" if question else ""
    try:
        result = structured_call(
            api_keys=keys,
            system=_INTENT_SYSTEM,
            user=f"{asked}What they said: {text!r}",
            schema=schema,
            schema_name="intent",
            temperature=0,
            max_tokens=32,
            timeout=timeout,
        )
    except GroqError:
        return None
    except Exception:  # noqa: BLE001 - a classifier must never break an interview
        return None

    try:
        return Intent(result.content.get("intent"))
    except ValueError:
        # Outside the enum. The schema should prevent it; checked anyway,
        # because this value steers what a person hears next.
        return None
