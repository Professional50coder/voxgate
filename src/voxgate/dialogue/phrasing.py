"""How to ask again when the first attempt did not land.

Repeating the identical sentence is what the interview used to do, and it is
the least useful thing available: if someone did not understand the words the
first time, the same words are not going to help. Worse, it wastes the one thing
the system already knows and never used — for an enum field the pack holds the
complete list of acceptable answers, so "I don't know" can be answered by
reading the options rather than by asking again and hoping.

A LADDER, not a repetition. Each rung changes the *kind* of help offered:

    1  the pack's own question, unchanged
    2  the question plus the options, or a narrowed prompt for free text
    3  a worked example, and permission to not know
    4  concede, record it unresolved, move on

Only rung 1 is the pack's wording. That distinction is the point and it is the
line this module is careful not to cross: what gets asked is the pack's
decision, because a model rewording a regulated question is a compliance
problem. How to help someone answer it is conversation, and being rigid there
buys nothing.

Everything here is deterministic string assembly. No model is involved in
deciding what to say, so every rung is assertable and none of it can be talked
into saying something else.
"""

from __future__ import annotations


def humanize(value: str) -> str:
    """`uae_resident` -> "UAE resident". Enum values are identifiers because
    they are Python; nobody should have to hear one read aloud."""
    words = value.replace("_", " ").split()
    return " ".join(w.upper() if len(w) <= 3 and w.isalpha() and w.islower()
                    and w in {"uae", "kyc", "pep", "id", "usa", "uk", "eu"}
                    else w for w in words)


def spoken_options(allowed: list[str], limit: int = 6) -> str:
    """The allowed values as something a person can hear.

    Capped, because reading twelve options aloud is worse than reading none —
    by the eighth the applicant has forgotten the first. Past the cap it offers
    a few and invites them to say what fits, which the extractor can still map.
    """
    values = [humanize(v) for v in allowed]
    if not values:
        return ""
    if len(values) > limit:
        head = ", ".join(values[:limit])
        return f"{head}, or something else close to those"
    if len(values) == 1:
        return values[0]
    return ", ".join(values[:-1]) + f", or {values[-1]}"


def reask(
    *,
    question: str,
    attempt: int,
    allowed: list[str] | None = None,
    reason: str | None = None,
) -> str:
    """The next thing to say, given how many attempts have already failed.

    `attempt` is the number of attempts ALREADY made on this field, so 1 means
    one has failed and this is the second ask.

    `reason` is the pack's explanation of why the field is needed, used at the
    point an applicant is most likely to be wondering.
    """
    if attempt <= 1:
        if allowed:
            return (
                f"{question} You can say {spoken_options(allowed)}."
            )
        return f"Let me put that another way. {question}"

    # Second failure. Offer an example and make it explicitly acceptable not to
    # know, because an applicant who thinks a wrong answer is required will
    # invent one -- and an invented answer on a compliance record is far worse
    # than a gap a human fills in.
    if allowed:
        example = humanize(allowed[0])
        return (
            f"No problem. Most people answer something like \"{example}\". "
            f"{question} If none of those fit, just say so and I will pass it "
            f"to a colleague."
        )
    hint = f" {reason}" if reason else ""
    return (
        f"That is alright.{hint} {question} "
        f"If you are not sure, say so and I will leave it for a colleague."
    )


def explain(field: str, question: str, allowed: list[str] | None = None,
            reason: str | None = None) -> str:
    """Answer "what do you mean?" without treating it as a failed attempt.

    An applicant asking what a question means is engaged and trying to answer
    correctly. Scoring that as a failure — which is what happens when every
    utterance is fed to the extractor — pushes the most cooperative people
    towards the give-up path fastest.
    """
    label = humanize(field)
    body = reason or f"I need this to complete the {label.lower()} part of your application."
    if allowed:
        return f"{body} You can say {spoken_options(allowed)}. {question}"
    return f"{body} {question}"


def acknowledge_refusal(question: str, attempt: int = 0) -> str:
    """A refusal is not a misunderstanding, and treating it as one is insulting.

    They heard the question and are declining. Say what happens next, once, and
    let them decide.

    The first version of this returned the same paragraph every time, which
    produced an agent that answered "I'd rather not say" with an identical
    speech twice in a row — the exact pestering this file exists to avoid. A
    refusal repeated is a decision restated, so the second reply is short and
    the interview moves on rather than asking a third time.
    """
    if attempt <= 1:
        return (
            "That is your choice. I have to record that it was not provided, and "
            f"someone from the team may follow up. {question} "
            "Or say \"skip\" and I will move on."
        )
    return "Understood, I will not ask again."


def concede(field: str) -> str:
    """Give up on one field without giving up on the interview.

    The case still reaches a reviewer with everything else collected, and the
    gap is recorded as a gap rather than filled with a guess.
    """
    return (
        f"That is fine, I will leave {humanize(field).lower()} for a member of "
        "the team to confirm with you."
    )


def confirm_volunteered(taken: dict[str, str]) -> str:
    """Read back answers the applicant gave before being asked for them.

    One sentence for all of them, not a yes/no turn each. Silence would be
    wrong — a value someone never heard recorded is one they cannot correct —
    but confirming each in turn costs more time than skipping the questions
    saved, which defeats the point. Saying them aloud is enough, because
    "actually, I meant..." reopens a field and clears it.
    """
    parts = [f"{humanize(name).lower()} as {humanize(value)}" for name, value in taken.items()]
    if len(parts) == 1:
        body = parts[0]
    else:
        body = ", ".join(parts[:-1]) + f", and {parts[-1]}"
    return f"Thank you. I have your {body}."
