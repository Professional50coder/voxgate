"""One turn of understanding, shared by the voice worker and the browser.

Two layers, in latency order:

  1. deterministic   the agent's own rules, then the platform patterns.
                     Microseconds, no network, cannot be talked out of a rule.
  2. model           only for what layer 1 could not place, and only to pick a
                     label from a closed set. Never writes the question.

Both surfaces call `understand` and `non_answer_reply`, so a rule added to a
pack's ``agent:`` block holds on the phone and in the browser alike.
"""
from __future__ import annotations

from dataclasses import dataclass

from voxgate.dialogue import phrasing
from voxgate.ml.understanding import Intent, classify, process_topic
from voxgate.packs.agent import AgentProfile, DEFAULT_AGENT


@dataclass(frozen=True)
class Understanding:
    intent: Intent
    #: For PROCESS, which question about the interview it was.
    topic: str | None = None
    #: "agent" when a pack rule decided, "platform" for the shared patterns.
    rule: str = "platform"


def understand(spoken: str, agent: AgentProfile = DEFAULT_AGENT) -> Understanding:
    # The agent's own sensitive terms outrank everything, same as the platform's.
    if agent.is_sensitive(spoken):
        return Understanding(Intent.SENSITIVE, rule="agent")
    intent = classify(spoken)
    if intent is Intent.ANSWER and agent.is_blocked(spoken):
        return Understanding(Intent.OFF_TOPIC, rule="agent")
    topic = process_topic(spoken) if intent is Intent.PROCESS else None
    return Understanding(intent, topic)


@dataclass
class Counters:
    """Per-conversation budgets. Plain data so the browser can round-trip it."""
    smalltalk: int = 0
    off_topic: int = 0


def non_answer_reply(u: Understanding, question: str, counters: Counters,
                     agent: AgentProfile = DEFAULT_AGENT) -> str | None:
    """What to say for the intents this layer owns, or None to defer.

    REPEAT, QUESTION, REFUSAL, DONT_KNOW and CORRECTION keep their existing
    handling at each surface; this covers the conversational intents.
    """
    if u.intent is Intent.SENSITIVE:
        return phrasing.refuse_sensitive(question)
    if u.intent is Intent.PROCESS:
        return phrasing.process_answer(u.topic, question, agent.process_answers)
    if u.intent is Intent.SMALLTALK:
        reply = phrasing.smalltalk(question, counters.smalltalk, agent.max_smalltalk)
        counters.smalltalk += 1
        return reply
    if u.intent is Intent.OFF_TOPIC:
        counters.off_topic += 1
        return phrasing.redirect(question, counters.off_topic)
    return None
