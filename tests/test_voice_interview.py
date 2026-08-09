"""The voice interview, driven without audio.

This is the payoff for keeping the language model out of the conversation loop.
`InterviewProcessor` is a function of (pack questions, current field,
transcript), so the whole interview — including the paths that only happen when
things go wrong — can be exercised by feeding it TranscriptionFrames. No
microphone, no Whisper, no Kokoro, no network, no LLM.

An LLM-driven agent could not be tested this way at all. You would be asserting
against a model's choice of what to say next, which is exactly the property that
makes it unsuitable for asking regulated questions.
"""

import pytest

# The voice stack is a heavy optional extra (torch, transformers, model
# downloads). Skipping cleanly keeps the default suite installable and fast.
pytest.importorskip("pipecat", reason="install the 'voice' extra to run these")

from pipecat.frames.frames import StartFrame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection

from voxgate.voice import MAX_ATTEMPTS_PER_FIELD, MIN_CONFIDENCE, InterviewProcessor

FIELDS = ["full_name", "nationality", "source_of_funds"]
QUESTIONS = {
    "full_name": "What is your full name?",
    "nationality": "What is your nationality?",
    "source_of_funds": "What is the main source of your funds?",
}


class Recorder:
    """Captures what the applicant would hear.

    The processor pushes TTSSpeakFrames downstream; collecting them is how the
    conversation becomes assertable text.
    """

    def __init__(self):
        self.spoken: list[str] = []
        self.other: list = []

    async def __call__(self, frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, TTSSpeakFrame):
            self.spoken.append(frame.text)
        else:
            self.other.append(frame)


def build(extract, on_complete=None, greeting=None):
    """A processor with its frame plumbing stubbed.

    `push_frame` is replaced rather than running a real pipeline: a Pipeline
    would need a transport, a task and an event loop to assert on three strings.
    """
    completed = {}

    async def default_complete(fields, confidence):
        completed["fields"] = fields
        completed["confidence"] = confidence

    processor = InterviewProcessor(
        field_names=FIELDS,
        questions=QUESTIONS,
        extract=extract,
        on_complete=on_complete or default_complete,
        greeting=greeting,
    )
    recorder = Recorder()
    processor.push_frame = recorder            # type: ignore[method-assign]
    return processor, recorder, completed


def perfect_extractor(value_map):
    async def extract(field, spoken):
        return value_map.get(field, spoken), 0.95
    return extract


async def start(processor):
    await processor._begin()


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_it_asks_the_packs_own_question_first():
    """The wording comes from the pack, not from a model paraphrasing it. For a
    regulated question that is a compliance property, not a style one."""
    processor, rec, _ = build(perfect_extractor({}))
    await start(processor)
    assert rec.spoken == ["What is your full name?"]


@pytest.mark.asyncio
async def test_a_greeting_precedes_the_first_question():
    processor, rec, _ = build(perfect_extractor({}), greeting="Hello there.")
    await start(processor)
    assert rec.spoken == ["Hello there.", "What is your full name?"]


@pytest.mark.asyncio
async def test_a_full_interview_collects_every_field_and_submits():
    answers = {
        "full_name": "Priya Raghavan",
        "nationality": "IN",
        "source_of_funds": "salary",
    }
    processor, rec, completed = build(perfect_extractor(answers))
    await start(processor)

    for spoken in ["Priya Raghavan", "Indian", "my salary"]:
        await processor.process_frame(
            TranscriptionFrame(text=spoken, user_id="u", timestamp="t"),
            FrameDirection.DOWNSTREAM,
        )

    assert processor.state.finished
    assert completed["fields"] == answers
    assert rec.spoken[-1].startswith("That is everything I need")
    # Each question asked exactly once, in the pack's order.
    assert rec.spoken[:3] == [QUESTIONS[f] for f in FIELDS]


# --------------------------------------------------------------------------
# The paths that only happen when something goes wrong
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_low_confidence_answer_is_re_asked_not_accepted():
    """Guessing on a compliance field is the one thing this system exists not
    to do, so a shaky extraction is a re-ask rather than a stored value."""
    async def unsure(field, spoken):
        return "salary", MIN_CONFIDENCE - 0.01

    processor, rec, _ = build(unsure)
    await start(processor)
    await processor.process_frame(
        TranscriptionFrame(text="uhh maybe", user_id="u", timestamp="t"),
        FrameDirection.DOWNSTREAM,
    )

    assert processor.state.answers == {}, "a guess was stored as an answer"
    assert processor.state.current == "full_name", "it moved on anyway"
    # Asserted as a property, not a sentence: the re-ask ladder owns the
    # wording, and pinning the exact string here would make every improvement
    # to how it asks look like a regression.
    assert rec.spoken[-1] != QUESTIONS["full_name"], "it repeated itself verbatim"
    assert QUESTIONS["full_name"] in rec.spoken[-1], "it stopped asking the question"


@pytest.mark.asyncio
async def test_silence_does_not_consume_an_attempt():
    """A dropped packet or a moment of background noise must not burn a retry;
    that would turn a microphone problem into a failed interview."""
    processor, _, _ = build(perfect_extractor({}))
    await start(processor)

    for empty in ["", "   ", "\n"]:
        await processor.process_frame(
            TranscriptionFrame(text=empty, user_id="u", timestamp="t"),
            FrameDirection.DOWNSTREAM,
        )

    assert processor.state.attempts == 0


@pytest.mark.asyncio
async def test_an_unanswerable_field_is_abandoned_rather_than_looping_forever():
    """An accent the extractor cannot place must not trap someone in a loop. The
    field is recorded as unresolved and a human picks it up."""
    async def never(field, spoken):
        return None, 0.0

    processor, rec, completed = build(never)
    await start(processor)

    for _ in range(MAX_ATTEMPTS_PER_FIELD * len(FIELDS)):
        await processor.process_frame(
            TranscriptionFrame(text="something", user_id="u", timestamp="t"),
            FrameDirection.DOWNSTREAM,
        )

    assert processor.state.finished, "the interview never ended"
    assert processor.state.unresolved == FIELDS
    assert completed["fields"] == {}, "an unresolved field must not be invented"
    assert any("member of the team" in s for s in rec.spoken)


@pytest.mark.asyncio
async def test_an_extractor_that_raises_is_a_re_ask_not_a_crash():
    """An operational failure is ours, never the applicant's."""
    calls = {"n": 0}

    async def flaky(field, spoken):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("groq is down")
        return "Priya Raghavan", 0.95

    processor, rec, _ = build(flaky)
    await start(processor)

    await processor.process_frame(
        TranscriptionFrame(text="Priya", user_id="u", timestamp="t"),
        FrameDirection.DOWNSTREAM,
    )
    assert processor.state.answers == {}
    assert rec.spoken[-1] != QUESTIONS["full_name"], "it repeated itself verbatim"
    assert "groq" not in " ".join(rec.spoken).lower(), "an internal error was read aloud"

    await processor.process_frame(
        TranscriptionFrame(text="Priya Raghavan", user_id="u", timestamp="t"),
        FrameDirection.DOWNSTREAM,
    )
    assert processor.state.answers["full_name"] == "Priya Raghavan"


@pytest.mark.asyncio
async def test_a_failed_submission_does_not_reach_the_applicant():
    """They have already been told they are finished, and they are — their
    answers exist. Retrying is our problem, not something to read out."""
    async def explode(fields, confidence):
        raise RuntimeError("connection to 10.0.0.7 refused")

    processor, rec, _ = build(perfect_extractor({}), on_complete=explode)
    await start(processor)
    for spoken in ["a", "b", "c"]:
        await processor.process_frame(
            TranscriptionFrame(text=spoken, user_id="u", timestamp="t"),
            FrameDirection.DOWNSTREAM,
        )

    assert processor.state.finished
    assert "10.0.0.7" not in " ".join(rec.spoken)


@pytest.mark.asyncio
async def test_speech_after_the_interview_ends_is_ignored():
    """A trailing "thanks, bye" must not resubmit the case."""
    submissions = []

    async def record(fields, confidence):
        submissions.append(fields)

    processor, _, _ = build(perfect_extractor({}), on_complete=record)
    await start(processor)
    for spoken in ["a", "b", "c", "thanks, bye"]:
        await processor.process_frame(
            TranscriptionFrame(text=spoken, user_id="u", timestamp="t"),
            FrameDirection.DOWNSTREAM,
        )

    assert len(submissions) == 1


@pytest.mark.asyncio
async def test_the_applicants_words_are_never_echoed_downstream():
    """Downstream is TTS. Forwarding a TranscriptionFrame would have the agent
    read the applicant back to themselves."""
    processor, rec, _ = build(perfect_extractor({}))
    await start(processor)
    await processor.process_frame(
        TranscriptionFrame(text="Priya Raghavan", user_id="u", timestamp="t"),
        FrameDirection.DOWNSTREAM,
    )
    assert not any(isinstance(f, TranscriptionFrame) for f in rec.other)


@pytest.mark.asyncio
async def test_the_start_frame_is_forwarded_before_anything_is_spoken(monkeypatch):
    """Speaking before the downstream TTS and transport have started means the
    greeting goes into a pipeline not yet carrying audio, and the applicant
    hears silence and assumes the line is dead.

    `FrameProcessor.process_frame` is stubbed because a real StartFrame spins up
    pipecat's own task machinery, which needs a linked pipeline. What is under
    test is the ordering *this* class chooses, not pipecat's start-up.
    """
    from pipecat.processors.frame_processor import FrameProcessor

    async def noop(self, frame, direction):
        return None

    monkeypatch.setattr(FrameProcessor, "process_frame", noop)

    processor, _, _ = build(perfect_extractor({}), greeting="Hello there.")

    order: list[str] = []

    async def track(frame, direction=FrameDirection.DOWNSTREAM):
        order.append("speak" if isinstance(frame, TTSSpeakFrame) else type(frame).__name__)

    processor.push_frame = track            # type: ignore[method-assign]
    await processor.process_frame(
        StartFrame(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
        FrameDirection.DOWNSTREAM,
    )

    assert order[0] == "StartFrame", f"spoke before starting the pipeline: {order}"
    assert order[1:] == ["speak", "speak"], "greeting and first question"
