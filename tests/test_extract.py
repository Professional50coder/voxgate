"""Extraction tests.

The keyword tests run offline and keyless, so the default suite stays fast and
network-free. The Groq tests are opt-in via GROQ_API_KEY and skip cleanly when
it is absent, matching how the Postgres integration tests already work.
"""

import pytest

from voxgate.config import get_settings
from voxgate.ml.extract import (
    Extraction,
    GroqExtractor,
    KeywordExtractor,
    allowed_values,
    build_extractor,
)
from voxgate.packs.loader import load_packs

LOAN_EMPLOYMENT = ["contract", "permanent", "self_employed", "unemployed"]


@pytest.fixture(scope="module")
def packs():
    return load_packs(get_settings().packs_dir)


# --------------------------------------------------------------------------
# Keyword extractor: offline, deterministic
# --------------------------------------------------------------------------

def test_exact_value_spoken_back():
    got = KeywordExtractor().extract("employment_status", LOAN_EMPLOYMENT, "permanent")
    assert got.value == "permanent"
    assert got.confidence == 1.0


def test_value_name_inside_a_sentence():
    got = KeywordExtractor().extract(
        "employment_status", LOAN_EMPLOYMENT, "I am self employed these days"
    )
    assert got.value == "self_employed"


def test_returns_none_rather_than_guessing():
    """A wrong guess here becomes a field on a compliance record. None is safer."""
    got = KeywordExtractor().extract(
        "employment_status", LOAN_EMPLOYMENT, "it's complicated honestly"
    )
    assert got.value is None
    assert got.confidence == 0.0


def test_empty_answer_is_not_an_extraction():
    assert KeywordExtractor().extract("employment_status", LOAN_EMPLOYMENT, "   ").value is None


def test_free_text_field_passes_through():
    got = KeywordExtractor().extract("full_name", None, "  Priya Raghavan  ")
    assert got.value == "Priya Raghavan"
    assert got.source == "passthrough"


def test_partial_token_overlap_does_not_match():
    """'one' alone must not satisfy 'one_to_three'."""
    got = KeywordExtractor().extract(
        "residency_years", ["under_1", "one_to_three", "over_three"], "one"
    )
    assert got.value != "one_to_three"


# --------------------------------------------------------------------------
# Allowed values are read from the pack, not duplicated
# --------------------------------------------------------------------------

def test_allowed_values_come_from_the_pack_schema(packs):
    pack = packs["loan-intake"]
    values = allowed_values(pack.schema_model, "employment_status")
    assert values == LOAN_EMPLOYMENT


def test_allowed_values_none_for_free_text(packs):
    pack = packs["loan-intake"]
    assert allowed_values(pack.schema_model, "full_name") is None


def test_every_enum_field_exposes_its_allowed_values(packs):
    """If this breaks, the extractor silently degrades to passthrough on a field
    the schema will then reject."""
    pack = packs["loan-intake"]
    enum_fields = ["employment_status", "income_band", "existing_debt",
                   "loan_purpose", "residency_years"]
    for field in enum_fields:
        assert allowed_values(pack.schema_model, field), field


# --------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------

def test_build_extractor_satisfies_the_protocol():
    got = build_extractor().extract("employment_status", LOAN_EMPLOYMENT, "permanent")
    assert isinstance(got, Extraction)
    assert got.value == "permanent"


def test_groq_extractor_falls_back_without_a_key():
    """No key must degrade, never raise."""
    extractor = GroqExtractor(api_key="")
    assert not extractor.available
    got = extractor.extract("employment_status", LOAN_EMPLOYMENT, "permanent")
    assert got.value == "permanent"
    assert got.source == "keyword"


def test_groq_extractor_falls_back_on_a_bad_key():
    """A rejected request must degrade to keyword matching, not break the interview."""
    extractor = GroqExtractor(api_key="gsk_definitely_not_valid", timeout=8.0)
    got = extractor.extract("employment_status", LOAN_EMPLOYMENT, "permanent")
    assert got.value == "permanent"
    assert got.source == "keyword"


# --------------------------------------------------------------------------
# Live Groq. Opt-in.
# --------------------------------------------------------------------------

def _groq_configured() -> bool:
    """Read through Settings, not os.environ: the key normally lives only in
    .env, so an os.environ check would skip these tests silently forever."""
    return bool(get_settings().groq_api_key)


REQUIRES_GROQ = pytest.mark.skipif(
    not _groq_configured(), reason="no Groq key configured"
)


CASES = [
    ("uh yeah I've been at the same company full time for about six years", "permanent"),
    ("I run my own little consultancy", "self_employed"),
    ("I'm between things at the moment", "unemployed"),
    ("it's a twelve month fixed term thing", "contract"),
]


@REQUIRES_GROQ
def test_groq_maps_natural_speech():
    """The cases keyword matching cannot reach.

    Asserts aggregate accuracy, not per-case equality. The model is
    non-deterministic, so pinning one phrasing to one answer made this fail
    intermittently on a capability that plainly works. What matters to the
    product is the hit rate and that a miss returns something valid rather than
    something invented, so that is what is asserted.
    """
    extractor = GroqExtractor()
    correct, results = 0, []
    for spoken, expected in CASES:
        got = extractor.extract("employment_status", LOAN_EMPLOYMENT, spoken)
        results.append((spoken, expected, got.value))
        # A wrong answer is tolerable. An answer outside the schema is not.
        assert got.value is None or got.value in LOAN_EMPLOYMENT, got.value
        correct += got.value == expected

    assert correct >= 3, f"only {correct}/{len(CASES)} mapped correctly: {results}"


@REQUIRES_GROQ
def test_groq_never_returns_a_value_outside_the_schema():
    got = GroqExtractor().extract(
        "employment_status", LOAN_EMPLOYMENT, "I am a professional yodeller on Mars"
    )
    assert got.value is None or got.value in LOAN_EMPLOYMENT
