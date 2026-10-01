"""The site's voice assistant: one brain, a persona per page.

Unlike the interview, this IS a model writing the reply, and that is safe for
the same reason the interview keeps a model out: what it may talk about is
closed. It answers questions about VoxGate from a fixed knowledge sheet, it
never sees an applicant's case unless an operator's page hands it one, and the
only thing it can *do* is pick one action from a fixed list, which the page
then carries out. A reply that names an action outside the list is dropped.

Latency is the product here, so the call is small: a short system prompt, the
last few turns only, a low token cap, and the fastest strict model first. With
no key the assistant still answers, from keyword matching on the same sheet.
"""
from __future__ import annotations

import re

from voxgate.config import Settings, get_settings

KNOWLEDGE = """\
VoxGate runs structured voice interviews that collect answers, check them, and
hand the decision to a person. Positioning: structured interviews that run
themselves, with the judgment left to your people and the paper trail handled.

How it works, in order:
1. A business picks or publishes a pack: the questions, the checks, the scoring
   and the agent's persona. Nine ship today: UAE KYC onboarding, insurance first
   notice of loss, loan intake, patient intake, real-estate leads, recruiting
   screens, sales discovery, support triage and tenant screening.
2. The applicant gets a link and talks to the agent in the browser or on a call.
   The agent reads the pack's questions word for word, so a regulated question
   is never reworded.
3. Every answer is understood in two layers. First, deterministic rules: the
   pack agent's own rules, then shared patterns for "I don't know", refusals,
   corrections, small talk, process questions and sensitive data. These take
   well under a millisecond. Only what they cannot place goes to a fast model,
   which maps the answer onto the pack's allowed values and is validated
   against them.
4. Checks and an explainable scorecard run (for KYC: sanctions, PEP and adverse
   media screening with name matching built for Arabic romanisation). Every risk
   contribution is attributable, so a regulator can read why.
5. Low risk is approved automatically; anything else pauses for a human
   reviewer in the console, with the transcript, an AI summary and the score
   breakdown. The workflow survives restarts and resumes exactly where it was.

Each agent has its own persona in its pack: name, voice, greeting, topics it
refuses, extra sensitive terms and its own answers to process questions. The
voice is Cartesia sonic-3 (a British voice by default, an Indian voice as
automatic fallback, and a local voice if both are unreachable).

Privacy: the agent refuses PINs, passwords, card numbers and one-time codes and
does not record them. Only the reviewing team sees answers. Transcripts are
kept with the application.

The site has a landing page, a how-it-works page, an applicant interview at
/apply, a reviewer console at /console and an agent builder at /agents where a
business describes an agent in plain English and publishes it.
"""

PAGES = {
    "home": "You greet visitors on the VoxGate landing page. Be brief and curious "
            "about what they want to automate.",
    "how-it-works": "You are the guide on the How it works page. Explain the "
                    "pipeline step by step, one step per reply unless asked for "
                    "more, and offer to show the next step.",
    "apply": "You help an applicant before their interview starts. Reassure them, "
             "explain what will happen, and never ask for their details yourself.",
    "console": "You assist a compliance reviewer. When case context is provided, "
               "summarise it and point at what needs a human decision. Never make "
               "the decision yourself.",
    "agents": "You help a business design a new voice agent: suggest questions, "
              "checks and persona rules for their use case.",
}

ACTIONS = ["none", "start_interview", "open_console", "open_agent_builder",
           "show_pipeline", "show_packs", "next_step"]

SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "action": {"type": "string", "enum": ACTIONS},
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reply", "action", "suggestions"],
    "additionalProperties": False,
}

_RULES = (
    "You are {name}, VoxGate's voice assistant. Your reply is spoken aloud, so "
    "write the way a warm, sharp person talks: plain sentences, no lists, no "
    "markdown, no emoji, at most three sentences. Only discuss VoxGate, using "
    "the facts below; if asked something you cannot answer from them, say so "
    "and offer what you can do. Never ask for personal data, PINs or card "
    "numbers. Pick action only when the user asked for it or clearly wants it, "
    "otherwise none. suggestions are two or three short follow-up questions the "
    "user might ask next.\n\nPage: {page}\n\nFACTS:\n{facts}"
)

# Keyword fallback for keyless and offline runs, matched against the message.
_FAQ = [
    (r"\b(how|work|pipeline|steps?)\b",
     "An applicant talks to the agent, every answer is understood and checked, "
     "an explainable score is calculated, and anything risky pauses for a person "
     "to decide.", "show_pipeline"),
    (r"\b(pack|use ?case|industr|kyc|loan|patient|insurance)\b",
     "Each use case is a pack. Nine ship today, from UAE KYC to patient intake, "
     "and a new one needs no platform code.", "show_packs"),
    (r"\b(start|apply|try|demo|interview)\b",
     "Happy to. I will start a demo interview for you now.", "start_interview"),
    (r"\b(fast|latency|speed|quick)\b",
     "The rules layer answers in well under a millisecond, and only answers it "
     "cannot place go to a fast model.", "none"),
    (r"\b(privacy|data|secure|safe|record)\b",
     "Only the reviewing team sees answers, and the agent refuses PINs, "
     "passwords and card numbers outright.", "none"),
    (r"\b(build|create|own agent|custom)\b",
     "You can describe your own agent in plain English in the agent builder and "
     "publish it.", "open_agent_builder"),
]


def answer(message: str, *, page: str = "home", history: list[dict] | None = None,
           context: str | None = None, name: str = "Lucy",
           settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    page = page if page in PAGES else "home"
    keys = settings.groq_key_pool()
    if keys:
        from voxgate.ml.groq_client import GroqError, structured_call
        turns = "\n".join(f"{t.get('role', 'user')}: {str(t.get('text', ''))[:400]}"
                          for t in (history or [])[-6:])
        user = ((f"On-screen context:\n{context[:3000]}\n\n" if context else "")
                + (f"Conversation so far:\n{turns}\n\n" if turns else "")
                + f"User: {message[:1000]}")
        try:
            result = structured_call(
                api_keys=keys, user=user, schema=SCHEMA, schema_name="assistant_reply",
                preferred_model=settings.groq_model, max_tokens=700, timeout=12.0,
                temperature=0.4,
                system=_RULES.format(name=name, page=PAGES[page], facts=KNOWLEDGE))
            content = result.content
            action = content["action"] if content["action"] in ACTIONS else "none"
            return {"reply": content["reply"].strip(), "action": action,
                    "suggestions": [str(s)[:80] for s in content["suggestions"]][:3],
                    "source": "llm"}
        except GroqError:
            pass
    return _offline(message)


def _offline(message: str) -> dict:
    for pattern, reply, action in _FAQ:
        if re.search(pattern, message or "", re.I):
            break
    else:
        reply, action = ("I can explain how VoxGate works, show the use cases, or "
                         "start a demo interview. Which would help?"), "none"
    return {"reply": reply, "action": action,
            "suggestions": ["How does it work?", "Is my data safe?", "Start a demo"],
            "source": "offline"}
