"""Telling an answer from everything else an applicant might say.

The defect this exists for: free-text fields took the transcript as the value at
confidence 0.6, and the interview accepted anything at or above 0.55. So an
applicant who replied "I don't know" to every question had that recorded as
their legal name and their source of funds, and the case reached a reviewer
looking complete rather than empty. Enum fields were never exposed, because the
value has to be in the allowed set.

The ordering assertions are the interesting ones. "I don't know what you mean"
is a QUESTION, not a DONT_KNOW — the applicant is reporting that the question
failed, not that the information is unavailable — and getting that backwards
sends the most cooperative people round a loop of the same words.
"""

import pytest

from voxgate.ml.understanding import Intent, classify, is_non_answer


@pytest.mark.parametrize("spoken", [
    "I don't know",
    "I dont know",
    "no idea",
    "not sure",
    "I'm not certain",
    "can't remember",
    "dunno",
    "idk",
    "n/a",
    "none",
    "unknown",
    "haven't got a clue",
])
def test_a_missing_answer_is_recognised(spoken):
    assert classify(spoken) is Intent.DONT_KNOW, spoken
    assert is_non_answer(spoken), spoken


@pytest.mark.parametrize("spoken", [
    "what do you mean by that?",
    "what does that mean",
    "why do you need that?",
    "can you explain",
    "what counts as source of funds",
    "what are the options",
])
def test_a_question_back_is_recognised(spoken):
    assert classify(spoken) is Intent.QUESTION, spoken


def test_i_dont_know_what_you_mean_is_a_question_not_a_missing_answer():
    """The ordering case, and the one most likely to be got wrong.

    It contains "don't know", so a naive matcher calls it DONT_KNOW and burns an
    attempt re-asking. The applicant is telling you the WORDING failed; the
    useful response is to explain, which costs them nothing.
    """
    assert classify("I don't know what you mean") is Intent.QUESTION
    assert classify("not sure what you mean by that") is Intent.QUESTION


@pytest.mark.parametrize("spoken", [
    "I'd rather not say",
    "I prefer not to answer",
    "not telling you that",
    "none of your business",
    "skip",
    "pass",
    "decline to answer",
])
def test_a_refusal_is_recognised(spoken):
    assert classify(spoken) is Intent.REFUSAL, spoken


@pytest.mark.parametrize("spoken", [
    "say that again",
    "can you repeat that",
    "come again",
    "pardon",
    "sorry?",
    "what?",
])
def test_a_request_to_repeat_is_recognised(spoken):
    assert classify(spoken) is Intent.REPEAT, spoken


@pytest.mark.parametrize("spoken", [
    "actually I meant Priya",
    "sorry, I meant something else",
    "let me start over",
    "scratch that",
    "I made a mistake",
])
def test_a_correction_is_recognised(spoken):
    assert classify(spoken) is Intent.CORRECTION, spoken


@pytest.mark.parametrize("spoken", [
    "Priya Raghavan",
    "salary",
    "my monthly salary from a logistics company",
    "about two and a half years now",
    "I am a resident of the UAE",
    "spot trading",
    "fifteenth of April nineteen ninety two",
])
def test_a_real_answer_is_left_alone(spoken):
    """False positives here are worse than false negatives: wrongly calling a
    genuine answer a non-answer refuses information the applicant gave."""
    assert classify(spoken) is Intent.ANSWER, spoken
    assert not is_non_answer(spoken), spoken


def test_an_answer_containing_a_trigger_word_is_still_an_answer():
    """"I know it's a salary" contains "know"; "passport" contains "pass". The
    patterns are anchored to avoid exactly this."""
    assert classify("I know it is my salary") is Intent.ANSWER
    assert classify("my passport says Priya Raghavan") is Intent.ANSWER
    assert classify("I work in sales") is Intent.ANSWER


def test_empty_and_stray_transcripts_are_non_answers():
    """Whisper emits stray punctuation and single characters on noise. Storing
    one as a legal name is exactly the failure this guards."""
    for spoken in ["", "   ", "?", "-", "a", "."]:
        assert is_non_answer(spoken), repr(spoken)


def test_unrecognised_input_falls_through_to_answer():
    """The safe default. An unrecognised utterance goes to the extractor, which
    validates it against the pack's allowed values, so the worst case is the
    behaviour that existed before this function did."""
    assert classify("purple monkey dishwasher") is Intent.ANSWER
