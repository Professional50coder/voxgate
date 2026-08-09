"""HTTP surface for the extraction and drafting endpoints.

Extraction is tested offline: with no Groq key the endpoint must still answer
using the deterministic keyword extractor, because the applicant interview
depends on it and cannot be allowed to fail closed.
"""

import pytest
from fastapi.testclient import TestClient

from voxgate.config import get_settings
from voxgate.service.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


# --------------------------------------------------------------------------
# POST /packs/{pack_id}/extract
# --------------------------------------------------------------------------

def test_extract_maps_a_plain_answer(client):
    r = client.post(
        "/packs/loan-intake/extract",
        json={"field": "employment_status", "spoken": "permanent"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == "permanent"
    assert body["field"] == "employment_status"
    assert "permanent" in body["allowed"]


def test_extract_exposes_the_allowed_values(client):
    """The interview UI needs these to render a correction control when the
    extraction is unclear."""
    r = client.post(
        "/packs/loan-intake/extract",
        json={"field": "loan_purpose", "spoken": "unintelligible mumbling"},
    )
    assert r.status_code == 200
    assert set(r.json()["allowed"]) >= {"vehicle", "education", "other"}


def test_extract_reports_its_source(client):
    """A reviewer should be able to tell whether a value came from a model or
    from deterministic matching."""
    r = client.post(
        "/packs/loan-intake/extract",
        json={"field": "employment_status", "spoken": "permanent"},
    )
    assert r.json()["source"] in {"keyword", "groq", "passthrough"}


def test_extract_free_text_field_passes_through(client):
    r = client.post(
        "/packs/loan-intake/extract",
        json={"field": "full_name", "spoken": "Priya Raghavan"},
    )
    assert r.json()["value"] == "Priya Raghavan"
    assert r.json()["allowed"] is None


def test_extract_unknown_pack_is_404(client):
    r = client.post(
        "/packs/not-a-pack/extract", json={"field": "x", "spoken": "y"}
    )
    assert r.status_code == 404


def test_extract_unknown_field_is_404(client):
    """A typo'd field name must fail loudly, not silently pass through as free
    text and then be rejected by the schema later."""
    r = client.post(
        "/packs/loan-intake/extract",
        json={"field": "not_a_field", "spoken": "anything"},
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------
# POST /packs/draft
# --------------------------------------------------------------------------

def test_draft_empty_description_is_422(client):
    r = client.post("/packs/draft", json={"description": "   "})
    assert r.status_code == 422


@pytest.mark.skipif(
    not get_settings().groq_api_key, reason="no Groq key configured"
)
def test_draft_returns_a_reviewable_proposal(client):
    r = client.post(
        "/packs/draft",
        json={
            "description": (
                "A driving school taking enquiries. We need to know if they already "
                "hold a provisional licence, how much experience they have, when they "
                "want to start, and how they heard about us."
            )
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fields"] and body["gate_role"]
    assert "warnings" in body
    # The spec must be directly consumable by scripts/generate_packs.py.
    assert body["spec"]["pack_id"] and body["spec"]["thresholds"]["low"] < 1
    assert all(f["question"].endswith("?") for f in body["fields"])
