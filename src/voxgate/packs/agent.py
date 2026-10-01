"""Each pack's voice agent: who it is, how it sounds, and its own house rules.

Declared in an optional ``agent:`` block of ``pack.yaml``. Every field has a
default, so a pack without the block still gets a complete, working agent; a
pack that wants its own personality overrides only what differs.

    agent:
      name: Lucy
      greeting: Hi, I'm Lucy from Acme. This takes about three minutes.
      voice: {primary: <cartesia voice id>, fallback: <cartesia voice id>}
      max_smalltalk: 2
      blocked_topics: [crypto tips, investment advice]
      sensitive_terms: [emirates id]
      process_answers:
        duration: About four minutes, and you can stop at any point.
      knowledge: |
        Facts the page assistant may use when answering questions.

What stays OUT of this block on purpose: the questions. Those remain the
pack's ``REASK_HINTS``, so persona can change how the agent sounds and what it
refuses to discuss, never what a regulated question says.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# Cartesia sonic-3 voices, chosen by ear on 2026-10-01.
LUCY_UK = "2f251ac3-89a9-4a77-a452-704b474ccd01"       # British, reassuring
KAVITA_IN = "56e35e2d-6eb6-4226-ab8b-9776515a7094"     # Indian, customer care

PROCESS_TOPICS = ("duration", "recording", "privacy", "identity", "purpose")


class VoiceProfile(BaseModel):
    provider: str = "cartesia"
    primary: str = LUCY_UK
    fallback: str | None = KAVITA_IN
    language: str = "en"
    #: Cartesia speed control. Slightly under 1.0 reads as calmer on a phone line.
    speed: float = Field(default=1.0, ge=0.6, le=1.5)


class AgentProfile(BaseModel):
    name: str = "Lucy"
    greeting: str | None = None
    voice: VoiceProfile = Field(default_factory=VoiceProfile)
    max_smalltalk: int = Field(default=2, ge=0, le=5)
    #: Phrases that mark a turn as off-topic for THIS agent, matched
    #: deterministically so the rule holds with no model and no network.
    blocked_topics: list[str] = Field(default_factory=list)
    #: Extra things this agent must never collect by voice, on top of the
    #: platform's PINs, passwords and card numbers.
    sensitive_terms: list[str] = Field(default_factory=list)
    process_answers: dict[str, str] = Field(default_factory=dict)
    #: Background facts for the page assistant. Never used in the interview.
    knowledge: str = ""

    @field_validator("process_answers")
    @classmethod
    def _known_topics(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = set(v) - set(PROCESS_TOPICS)
        if unknown:
            raise ValueError(f"unknown process topics {sorted(unknown)}; "
                             f"expected some of {list(PROCESS_TOPICS)}")
        return v

    def _terms(self, terms: list[str]) -> re.Pattern | None:
        cleaned = [re.escape(t.strip()) for t in terms if t.strip()]
        return re.compile(r"\b(" + "|".join(cleaned) + r")\b", re.I) if cleaned else None

    def is_blocked(self, spoken: str) -> bool:
        pattern = self._terms(self.blocked_topics)
        return bool(pattern and pattern.search(spoken or ""))

    def is_sensitive(self, spoken: str) -> bool:
        pattern = self._terms(self.sensitive_terms)
        return bool(pattern and pattern.search(spoken or ""))


DEFAULT_AGENT = AgentProfile()
