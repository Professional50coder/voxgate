"""How the interview behaves when the applicant is not a well-formed form.

The complaint that produced this file: answer "I don't know" to every question
and the interview accepted it and submitted. Two separate failures behind that —
free-text fields stored the transcript verbatim, and every re-ask repeated the
same sentence, so nothing about the second attempt was more likely to succeed
than the first.

What is asserted here is the conversation, not the plumbing: what a person
actually hears, and whether it changes when the first attempt did not land.
"""

import pytest

pytest.importorskip("pipecat", reason="install the 'voice' extra to run these")

from pipecat.frames.frames import TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection

from voxgate.ml.understanding import Intent
from voxgate.voice import MAX_ATTEMPTS_PER_FIELD, InterviewProcessor
from voxgate.voice.interview import MAX_REFUSALS_PER_FIELD

FIELDS = ["full_name", "residency_status", "source_of_funds"]
QUESTIONS = {
    "full_name": "What is your full name?",
    "residency_status": "What is your residency status?",
    "source_of_funds": "What is the main source of your funds?",
}
OPTIONS = {
    "residency_status": ["uae_resident", "non_resident"],
    "source_of_funds": ["salary", "business_income", "investments"],
}


class Recorder:
    def __init__(self):
        self.spoken: list[str] = []

    async def __call__(self, frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, TTSSpeakFrame):
            self.spoken.append(frame.text)


def build(extract=None, classify_model=None, options=OPTIONS):
    completed = {}

    async def default_extract(field, spoken):
        return None, 0.0

    async def on_complete(fields, confidence):
        completed["fields"] = fields

    processor = InterviewProcessor(
        field_names=FIELDS,
        questions=QUESTIONS,
        extract=extract or default_extract,
        on_complete=on_complete,
        options=options,
        classify_model=classify_model,
    )
    rec = Recorder()
    processor.push_frame = rec            # type: ignore[method-assign]
    return processor, rec, completed


async def say(processor, text):
    await processor.process_frame(
        TranscriptionFrame(text=text, user_id="u", timestamp="t"),
        FrameDirection.DOWNSTREAM,
    )


# --------------------------------------------------------------------------
# The reported bug
# --------------------------------------------------------------------------

async def test_answering_i_dont_know_to_everything_stores_nothing():
    """The regression, stated as the user reported it.

    Previously "I don't know" was stored as the applicant's legal name, because
    a free-text field took the transcript at confidence 0.6 and the interview
    accepted anything at or above 0.55. The case then reached a reviewer looking
    complete rather than empty, which is the dangerous part: a gap you can see
    is a task, a gap filled with junk is a wrong decision waiting to happen.
    """
    processor, _, completed = build()
    await processor._begin()

    for _ in range(MAX_ATTEMPTS_PER_FIELD * len(FIELDS) + 3):
        await say(processor, "I don't know")

    assert processor.state.finished
    assert completed["fields"] == {}, "a non-answer was stored as a value"
    assert processor.state.unresolved == FIELDS


async def test_a_non_answer_never_becomes_a_free_text_value():
    """The specific hole: enum fields were always safe, text fields were not."""
    async def passthrough(field, spoken):
        # What the old free-text path did: hand back whatever was said.
        return spoken, 0.6

    processor, _, completed = build(extract=passthrough)
    await processor._begin()
    for _ in range(MAX_ATTEMPTS_PER_FIELD):
        await say(processor, "no idea")

    assert "full_name" not in processor.state.answers
    assert processor.state.answers.get("full_name") != "no idea"


# --------------------------------------------------------------------------
# The ladder
# --------------------------------------------------------------------------

async def test_the_second_ask_reads_the_options_instead_of_repeating():
    """The single biggest win available, and it needs no model: the pack
    already holds the list of acceptable answers and it was never used."""
    processor, rec, _ = build()
    await processor._begin()
    processor.state.index = 1                # residency_status, an enum field
    processor.state.attempts = 0
    rec.spoken.clear()

    await say(processor, "I don't know")

    latest = rec.spoken[-1]
    assert latest != QUESTIONS["residency_status"], "it just repeated itself"
    assert "UAE resident" in latest and "non resident" in latest


async def test_the_third_ask_offers_an_example_and_permission_to_not_know():
    """An applicant who believes an answer is compulsory will invent one, and an
    invented answer on a compliance record is worse than an admitted gap."""
    processor, rec, _ = build()
    await processor._begin()
    processor.state.index = 1
    processor.state.attempts = 0
    rec.spoken.clear()

    await say(processor, "I don't know")
    await say(processor, "still no idea")

    latest = rec.spoken[-1]
    assert "colleague" in latest.lower()
    assert "most people answer" in latest.lower()


async def test_every_reask_for_one_field_is_different():
    """The property the ladder exists for. Three identical sentences is what
    the interview used to produce."""
    processor, rec, _ = build()
    await processor._begin()
    rec.spoken.clear()

    for _ in range(MAX_ATTEMPTS_PER_FIELD):
        await say(processor, "I don't know")

    prompts = [s for s in rec.spoken if s]
    assert len(set(prompts)) == len(prompts), f"repeated itself: {prompts}"


# --------------------------------------------------------------------------
# Letting the applicant talk back
# --------------------------------------------------------------------------

async def test_asking_what_a_question_means_is_answered_not_penalised():
    """Someone asking what a question means is cooperating. Charging them an
    attempt pushes the most engaged applicants to the give-up path fastest."""
    processor, rec, _ = build()
    await processor._begin()
    processor.state.index = 2                 # source_of_funds
    processor.state.attempts = 0
    rec.spoken.clear()

    await say(processor, "what do you mean by that?")

    assert processor.state.attempts == 0, "a question back cost an attempt"
    assert "salary" in rec.spoken[-1], "it did not explain or offer the options"


async def test_asking_to_repeat_repeats_verbatim_and_costs_nothing():
    processor, rec, _ = build()
    await processor._begin()
    rec.spoken.clear()

    await say(processor, "sorry, can you say that again")

    assert rec.spoken[-1] == QUESTIONS["full_name"]
    assert processor.state.attempts == 0


async def test_a_refusal_is_acknowledged_rather_than_re_asked_identically():
    processor, rec, _ = build()
    await processor._begin()
    rec.spoken.clear()

    await say(processor, "I'd rather not say")

    assert processor.state.attempts == 1, "a refusal is a decision, and counts"
    assert "your choice" in rec.spoken[-1].lower()


async def test_a_declined_field_is_recorded_apart_from_one_that_was_not_known():
    """A reviewer treats "would not say" and "did not know" very differently,
    and collapsing them loses the more interesting of the two."""
    processor, _, _ = build()
    await processor._begin()

    for _ in range(MAX_REFUSALS_PER_FIELD):
        await say(processor, "I'd rather not say")

    assert processor.state.declined == ["full_name"]
    assert processor.state.unresolved == []


async def test_a_correction_reopens_the_previous_field_and_clears_it():
    """Refusing to go back would leave a value on the record that the applicant
    has explicitly disowned."""
    async def good(field, spoken):
        return "Priya Raghavan", 0.95

    processor, rec, _ = build(extract=good)
    await processor._begin()
    await say(processor, "Priya Raghavan")
    assert processor.state.answers["full_name"] == "Priya Raghavan"
    rec.spoken.clear()

    await say(processor, "actually I meant something else")

    assert "full_name" not in processor.state.answers, "the disowned value survived"
    assert processor.state.current == "full_name"
    assert QUESTIONS["full_name"] in rec.spoken[-1]


# --------------------------------------------------------------------------
# The model-backed second opinion
# --------------------------------------------------------------------------

async def test_an_unrecognised_non_answer_is_understood_by_the_model():
    """"my brother handles all that" is a dont_know that no pattern will catch.
    Answering it with "sorry, I did not catch that" is the behaviour being
    complained about."""
    calls = []

    async def classifier(spoken, question):
        calls.append(spoken)
        return Intent.DONT_KNOW

    processor, rec, _ = build(classify_model=classifier)
    await processor._begin()
    processor.state.index = 1
    processor.state.attempts = 0
    rec.spoken.clear()

    await say(processor, "erm, my brother handles all that paperwork")

    assert calls, "the model was never consulted"
    assert "UAE resident" in rec.spoken[-1], "it fell back to a generic re-ask"


async def test_the_model_is_only_consulted_once_extraction_has_failed():
    """It costs a round trip, so it must not sit on the path where things are
    going well."""
    calls = []

    async def classifier(spoken, question):
        calls.append(spoken)
        return Intent.ANSWER

    async def good(field, spoken):
        return "Priya Raghavan", 0.95

    processor, _, _ = build(extract=good, classify_model=classifier)
    await processor._begin()
    await say(processor, "Priya Raghavan")

    assert calls == [], "a successful answer still cost a classification call"


async def test_a_failing_classifier_never_breaks_the_interview():
    async def broken(spoken, question):
        raise RuntimeError("groq is down")

    processor, rec, _ = build(classify_model=broken)
    await processor._begin()
    rec.spoken.clear()

    await say(processor, "something unparseable")

    assert rec.spoken, "the interview went silent"
    assert "groq" not in " ".join(rec.spoken).lower()


async def test_the_interview_works_with_no_classifier_at_all():
    """The deterministic layer is the product; the model is polish. With no key
    and no network the interview must still run."""
    processor, rec, _ = build(classify_model=None)
    await processor._begin()
    rec.spoken.clear()

    await say(processor, "I don't know")

    assert rec.spoken, "no classifier meant no response"
    assert processor.state.attempts == 1


async def test_a_repeated_refusal_is_not_answered_with_the_same_speech():
    """The first version replied to two identical refusals with two identical
    paragraphs — the exact pestering the ladder exists to avoid."""
    processor, rec, _ = build()
    await processor._begin()
    rec.spoken.clear()

    await say(processor, "I'd rather not say")
    first = rec.spoken[-1]
    await say(processor, "I'd rather not say")

    assert rec.spoken[-1] != first, "it repeated itself at a refusal"
    assert processor.state.declined == ["full_name"], "and it kept asking"


# --------------------------------------------------------------------------
# Answers volunteered before they were asked for
# --------------------------------------------------------------------------

def multi_extractor(mapping):
    """Answers whatever it can find in the sentence, for any field."""
    async def extract(field, spoken):
        for needle, (name, value) in mapping.items():
            if name == field and needle.lower() in spoken.lower():
                return value, 0.95
        return None, 0.0
    return extract


async def test_several_answers_in_one_breath_are_all_kept():
    """People do not answer one question at a time. Throwing two answers away
    to ask for them again a moment later is the most robotic thing an interview
    can do."""
    processor, rec, completed = build(extract=multi_extractor({
        "priya": ("full_name", "Priya Raghavan"),
        "resident": ("residency_status", "uae_resident"),
        "salary": ("source_of_funds", "salary"),
    }))
    await processor._begin()

    await say(processor, "I'm Priya, a UAE resident, and I live on my salary")

    assert processor.state.finished, "it kept asking for what it had been told"
    assert completed["fields"] == {
        "full_name": "Priya Raghavan",
        "residency_status": "uae_resident",
        "source_of_funds": "salary",
    }


async def test_volunteered_answers_are_read_back_so_they_can_be_corrected():
    """Silence would be wrong: a value the applicant never heard recorded is
    one they cannot correct."""
    processor, rec, _ = build(extract=multi_extractor({
        "priya": ("full_name", "Priya Raghavan"),
        "resident": ("residency_status", "uae_resident"),
    }))
    await processor._begin()
    rec.spoken.clear()

    await say(processor, "I'm Priya and I am a UAE resident living here")

    spoken = " ".join(rec.spoken)
    assert "UAE resident" in spoken, "a stored value was never said aloud"
    assert QUESTIONS["residency_status"] not in spoken, "it asked anyway"


async def test_a_volunteered_answer_must_clear_a_higher_bar():
    """A value picked out of an answer to a DIFFERENT question is a weaker
    signal than one given in reply to its own. "I work in sales" mentions sales
    without being an answer about source of funds."""
    async def middling(field, spoken):
        if field == "full_name":
            return "Priya Raghavan", 0.95
        return "salary", 0.7        # above MIN_CONFIDENCE, below volunteered

    processor, _, _ = build(extract=middling)
    await processor._begin()

    await say(processor, "I am Priya Raghavan and I work in sales somewhere")

    assert "source_of_funds" not in processor.state.answers
    assert "source_of_funds" not in processor.state.pending
    assert processor.state.current == "residency_status", "it did not move on"


async def test_a_short_answer_is_not_scanned_for_other_fields():
    """Below a few words the utterance is answering one question, so scanning
    is a round trip per field for nothing."""
    scanned = []

    async def counting(field, spoken):
        scanned.append(field)
        return ("Priya Raghavan", 0.95) if field == "full_name" else (None, 0.0)

    processor, _, _ = build(extract=counting)
    await processor._begin()
    await say(processor, "Priya Raghavan")

    assert scanned == ["full_name"], f"scanned other fields needlessly: {scanned}"


async def test_a_failed_opportunistic_scan_never_disturbs_the_interview():
    """It is a shortcut. An applicant must never see an error for the system's
    attempt to save them a question."""
    async def flaky(field, spoken):
        if field == "full_name":
            return "Priya Raghavan", 0.95
        raise RuntimeError("groq is down")

    processor, rec, _ = build(extract=flaky)
    await processor._begin()
    rec.spoken.clear()

    await say(processor, "I am Priya Raghavan and I live here in Dubai")

    assert processor.state.answers["full_name"] == "Priya Raghavan"
    assert QUESTIONS["residency_status"] in rec.spoken[-1], "it did not carry on"
    assert "groq" not in " ".join(rec.spoken).lower()


async def test_a_volunteered_answer_can_still_be_corrected():
    """The read-back is what makes silent acceptance safe, and it is only safe
    if the correction path actually reaches the volunteered field."""
    processor, rec, _ = build(extract=multi_extractor({
        "priya": ("full_name", "Priya Raghavan"),
        "resident": ("residency_status", "uae_resident"),
    }))
    await processor._begin()
    await say(processor, "I'm Priya and I am a UAE resident living here")
    assert processor.state.answers["residency_status"] == "uae_resident"

    await say(processor, "actually I meant something else")

    assert "residency_status" not in processor.state.answers, "the disowned value survived"
