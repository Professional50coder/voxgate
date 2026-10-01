"""Draft a scenario pack from a plain-English description of a business need.

A business owner describes what they do and what the agent should find out. This
turns that into a **pack spec**: the same declarative shape
`scripts/generate_packs.py` already consumes. That reuse is the point. The LLM
never writes Python and never invents structure; it fills in a shape whose rules
are enforced by a JSON schema, and the deterministic generator does the rest.

The draft is a proposal, not a deployment. Nothing reaches the packs directory
until a human has read the questions and approved them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM = """You design structured interview scripts for a compliance and intake platform.

Given a description of a business and what its agent should find out, produce a
pack spec.

Rules you must follow:
- Between 4 and 8 fields. Fewer is better. Every field must be something a
  person can answer out loud in one sentence.
- Prefer `enum` fields over `text`. Enums are what make an answer scoreable.
  Use `text` only for genuinely open answers like a name or a description.
- Every enum value name is lower_snake_case and self-describing (`under_2k`,
  `mortgage_approved`), never `option_a` or `yes`/`no` where a richer word fits.
- `risk` is 0..1: how much this answer should raise concern for the reviewer.
  A neutral or good answer is near 0. Never make every value high risk.
- Questions are spoken aloud. Write them the way a polite person talks. No
  field names, no jargon, no brackets, one question per field. Every question
  is phrased as a question and ends with a question mark.
- Checks scan one field's answer for phrases that warrant attention. Give each
  a name that reads like what it detects (`affordability_strain`, not `check_1`).
- Never ask for protected characteristics: race, religion, sexual orientation,
  disability, pregnancy, union membership.
- Never ask for a password, full card number, or government ID number.
"""

# Mirrors the generator's spec vocabulary. Kept strict so the model cannot
# invent a field type the generator has no emitter for.
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "display_name": {"type": "string"},
        "gate_role": {
            "type": "string",
            "description": "Job title of the human who reviews escalated cases.",
        },
        "persona": {
            "type": "string",
            "description": "How the agent should behave, and what it must never do.",
        },
        "gate_reason": {
            "type": "string",
            "description": "Which cases should reach a human, in plain language.",
        },
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["enum", "text"]},
                    "question": {"type": "string"},
                    "weight": {
                        "type": "number",
                        "description": "Scorecard weight, 0.5 to 2.0. Enum fields only.",
                    },
                    "values": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "value": {"type": "string"},
                                "risk": {"type": "number"},
                            },
                            "required": ["value", "risk"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "type", "question", "weight", "values"],
                "additionalProperties": False,
            },
        },
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "field": {"type": "string"},
                    "hit_phrases": {"type": "array", "items": {"type": "string"}},
                    "review_phrases": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "field", "hit_phrases", "review_phrases"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "display_name",
        "gate_role",
        "persona",
        "gate_reason",
        "fields",
        "checks",
    ],
    "additionalProperties": False,
}


class DraftError(Exception):
    """Raised when a draft cannot be produced or fails validation."""


class RateLimited(DraftError):
    """Every model in the fallback chain refused on quota.

    Distinguished from a generic DraftError because the caller should respond
    differently: a UI says "try again shortly" rather than "that failed", and a
    test skips rather than fails. Groq's free tier is 30 requests per minute
    PER MODEL, so this only fires once the whole chain is exhausted.
    """


@dataclass
class PackDraft:
    """A proposed pack, before any human has seen it."""

    pack_id: str
    display_name: str
    gate_role: str
    persona: str
    gate_reason: str
    fields: list[dict]
    checks: list[dict]
    warnings: list[str] = field(default_factory=list)

    def to_spec(self) -> dict:
        """Convert to the exact shape scripts/generate_packs.py consumes."""
        spec_fields = []
        for f in self.fields:
            entry: dict[str, Any] = {
                "name": f["name"],
                "type": f["type"],
                "question": f["question"],
            }
            if f["type"] == "enum":
                entry["weight"] = f["weight"]
                entry["values"] = {v["value"]: v["risk"] for v in f["values"]}
            else:
                entry["min_words"] = 1
            spec_fields.append(entry)

        return {
            "pack_id": self.pack_id,
            "display_name": self.display_name,
            "gate_role": self.gate_role,
            "persona": self.persona,
            "gate_reason": self.gate_reason,
            "thresholds": {"low": 0.30, "high": 0.65},
            "bias": -2.5,
            "fields": spec_fields,
            "checks": [
                {
                    "name": c["name"],
                    "field": c["field"],
                    "flags": {
                        "hit": c["hit_phrases"],
                        "review": c["review_phrases"],
                    },
                }
                for c in self.checks
            ],
        }


# Field names the platform reserves or that would collide with graph state.
RESERVED = {"case_id", "pack_id", "status", "score", "decision", "audit"}

BANNED_TOPICS = {
    "race", "ethnicity", "religion", "religious", "sexual", "orientation",
    "disability", "disabled", "pregnan", "union", "political",
    "password", "card_number", "cvv", "ssn", "social_security",
}


def validate_draft(draft: PackDraft) -> list[str]:
    """Structural and policy checks a human should see before approving.

    Returns warnings rather than raising: a draft with a problem is still worth
    showing, because the reviewer may want to fix one field rather than start
    over.
    """
    warnings: list[str] = []
    names = [f["name"] for f in draft.fields]

    if not 3 <= len(draft.fields) <= 10:
        warnings.append(
            f"{len(draft.fields)} questions. Interviews under 4 feel thin and over 8 get abandoned."
        )

    if len(names) != len(set(names)):
        warnings.append("Two fields share a name, which would silently overwrite an answer.")

    for name in names:
        if name in RESERVED:
            warnings.append(f"`{name}` is reserved by the platform and must be renamed.")
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            warnings.append(f"`{name}` is not a valid Python identifier.")
        for banned in BANNED_TOPICS:
            if banned in name.lower():
                warnings.append(
                    f"`{name}` looks like a protected characteristic or a secret. Remove it."
                )
                break

    for f in draft.fields:
        if f["type"] == "enum":
            values = [v["value"] for v in f.get("values", [])]
            if len(values) < 2:
                warnings.append(f"`{f['name']}` is an enum with fewer than two choices.")
            if len(values) != len(set(values)):
                warnings.append(f"`{f['name']}` repeats a value.")
            risks = [v["risk"] for v in f.get("values", [])]
            if risks and min(risks) > 0.5:
                warnings.append(
                    f"`{f['name']}` has no low-risk answer, so every case scores high on it."
                )
        if not f["question"].strip().endswith("?"):
            warnings.append(f"`{f['name']}` question does not read as a question.")

    known = set(names)
    for c in draft.checks:
        if c["field"] not in known:
            warnings.append(
                f"Check `{c['name']}` reads `{c['field']}`, which is not one of the fields."
            )
        if not c["hit_phrases"] and not c["review_phrases"]:
            warnings.append(f"Check `{c['name']}` has no phrases, so it can never fire.")

    return warnings


def slugify(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "-" for ch in text.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:40] or "custom-agent"


_ASKS = re.compile(
    r"^(what|which|how|when|where|who|whose|why|do|does|did|are|is|was|were|can|could|"
    r"would|will|have|has|should|may)\b", re.I)


def as_question(text: str) -> str:
    """Give a spoken question its question mark when the model dropped it.

    Only for sentences that open like a question ("What is your..."); an
    instruction such as "Please describe the damage." is left alone, because
    bolting a "?" on reads worse than the full stop, and validate_draft warns.
    """
    text = (text or "").strip()
    if text and _ASKS.match(text) and not text.endswith("?"):
        text = text.rstrip(".!") + "?"
    return text


def draft_pack(
    description: str,
    *,
    pack_id: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 45.0,
) -> PackDraft:
    """Ask the model for a pack spec, then validate it before returning."""
    if not description.strip():
        raise DraftError("Describe the business and what the agent should find out.")

    from voxgate.config import get_settings

    settings = get_settings()
    if model is None:
        model = settings.groq_model
    # An explicit api_key ("" in tests) overrides the pool entirely.
    pool = [api_key] if api_key is not None else settings.groq_key_pool()
    pool = [k for k in pool if k]

    if not pool:
        raise DraftError("No Groq key configured, so drafting is unavailable.")

    from voxgate.ml.groq_client import GroqError, GroqRateLimited, structured_call

    try:
        result = structured_call(
            api_keys=pool,
            system=SYSTEM,
            user=description.strip(),
            schema=DRAFT_SCHEMA,
            schema_name="pack_draft",
            preferred_model=model,
            temperature=0.4,
            max_tokens=4000,
            timeout=timeout,
        )
    except GroqRateLimited as exc:
        raise RateLimited(str(exc)) from exc
    except GroqError as exc:
        raise DraftError(f"Could not draft a pack: {exc}") from exc

    payload = result.content

    for f in payload["fields"]:
        f["question"] = as_question(f.get("question", ""))

    draft = PackDraft(
        pack_id=pack_id or slugify(payload["display_name"]),
        display_name=payload["display_name"],
        gate_role=payload["gate_role"],
        persona=payload["persona"],
        gate_reason=payload["gate_reason"],
        fields=payload["fields"],
        checks=payload["checks"],
    )
    draft.warnings = validate_draft(draft)
    if result.fell_back:
        draft.warnings.append(
            f"Drafted by {result.model} on key #{result.key_index + 1} after "
            f"{result.attempts - 1} rate-limited attempt(s)."
        )
    return draft
