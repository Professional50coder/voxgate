"""Who can reach what.

The split under test is not "risky handlers are locked". It is "operator
surfaces are locked, and every route the applicant flow touches is not" —
because an applicant follows an invite link, has no account, and never will.
Locking their path would mean handing the key to every applicant, which is the
same as having no key.

The most load-bearing assertion here is the last group: the applicant can still
complete an interview end to end with no credentials at all. An auth change
that quietly breaks that would take the product down without failing any test
that only checks the locked routes.
"""

import pytest
from fastapi.testclient import TestClient

from voxgate.config import Settings
from voxgate.service.app import create_app
from voxgate.service.auth import key_matches, parse_keys

KEY = "operator-key-aaaaaaaaaaaa"
OTHER = "second-key-bbbbbbbbbbbb"

CLEAN = {
    "full_name": "Priya Raghavan", "dob": "1992-04-15", "nationality": "IN",
    "residency_status": "uae_resident", "source_of_funds": "salary",
    "product": "spot_trading",
}

OPERATOR_ROUTES = [
    ("get", "/cases", None),
    ("post", "/packs/draft", {"description": "A clinic intake for a dental practice."}),
    ("post", "/packs/publish", {"spec": {}}),
]


@pytest.fixture
def secured(tmp_path):
    return TestClient(create_app(settings=Settings(
        database_url=None, api_keys=f"{KEY},{OTHER}")))


@pytest.fixture
def open_app():
    """No keys configured: auth is off by design, so dev and CI keep working."""
    return TestClient(create_app(settings=Settings(database_url=None, api_keys=None)))


# --------------------------------------------------------------------------
# Key handling
# --------------------------------------------------------------------------

def test_keys_parse_and_blanks_are_dropped():
    assert parse_keys(" a , b ,, ") == ["a", "b"]
    assert parse_keys(None) == []
    assert parse_keys("") == []


def test_key_matching_is_exact():
    allowed = parse_keys(f"{KEY},{OTHER}")
    assert key_matches(KEY, allowed)
    assert key_matches(OTHER, allowed)
    assert not key_matches(KEY[:-1], allowed)
    assert not key_matches(KEY + "x", allowed)
    assert not key_matches("", allowed)


# --------------------------------------------------------------------------
# Operator routes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("method,path,body", OPERATOR_ROUTES)
def test_operator_routes_reject_an_anonymous_caller(secured, method, path, body):
    r = getattr(secured, method)(path, **({"json": body} if body else {}))
    assert r.status_code == 401, f"{path} was reachable without a key"
    assert "bearer" in r.headers.get("www-authenticate", "").lower()


@pytest.mark.parametrize("method,path,body", OPERATOR_ROUTES)
def test_operator_routes_reject_a_wrong_key(secured, method, path, body):
    r = getattr(secured, method)(
        path, headers={"X-API-Key": "not-the-key"}, **({"json": body} if body else {})
    )
    assert r.status_code == 403, f"{path} accepted a bad key"


def test_a_valid_key_is_admitted_by_either_header(secured):
    for headers in ({"X-API-Key": KEY}, {"Authorization": f"Bearer {KEY}"}):
        r = secured.get("/cases", headers=headers)
        assert r.status_code == 200, f"{headers} was rejected"


def test_every_configured_key_works_not_just_the_first(secured):
    """Key rotation depends on this: the new key must work before the old one
    is removed, or rotation means downtime."""
    assert secured.get("/cases", headers={"X-API-Key": OTHER}).status_code == 200


def test_a_bearer_scheme_that_is_not_bearer_is_not_accepted(secured):
    assert secured.get(
        "/cases", headers={"Authorization": f"Basic {KEY}"}
    ).status_code == 401


def test_the_reviewer_decision_route_is_protected(secured):
    """It is the one route that changes a compliance outcome."""
    case = secured.post("/cases", json={"pack_id": "kyc-uae"}).json()
    secured.post(f"/cases/{case['case_id']}/interview-result",
                 json={"fields": CLEAN, "confidence": {}})
    r = secured.post(f"/cases/{case['case_id']}/decision",
                     json={"action": "approve", "note": ""})
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------
# The applicant path must stay open
# --------------------------------------------------------------------------

def test_an_applicant_completes_an_interview_with_no_credentials(secured):
    """The load-bearing one.

    An applicant has no key and never will. If any part of this path starts
    requiring one, the product is down for the people it is for — and no test
    that only checks the locked routes would notice.
    """
    assert secured.get("/packs").status_code == 200

    case = secured.post("/cases", json={"pack_id": "kyc-uae"})
    assert case.status_code == 201, "an applicant could not open a case"
    case_id = case.json()["case_id"]

    assert secured.get(f"/cases/{case_id}").status_code == 200
    assert secured.patch(
        f"/cases/{case_id}/fields",
        json={"fields": {"full_name": "Priya R"}, "confidence": {}},
    ).status_code == 200

    done = secured.post(f"/cases/{case_id}/interview-result",
                        json={"fields": CLEAN, "confidence": {}})
    assert done.status_code == 200, "an applicant could not submit an interview"
    assert done.json()["score"] is not None, "and it still ran the graph"


def test_health_endpoints_are_open(secured):
    """A load balancer has no key."""
    assert secured.get("/health").status_code == 200
    assert secured.get("/health/ready").status_code == 200


# --------------------------------------------------------------------------
# Unconfigured
# --------------------------------------------------------------------------

def test_without_keys_everything_is_open_and_readiness_says_so(open_app):
    """Off by default keeps dev and CI working. It must not be quiet about it."""
    assert open_app.get("/cases").status_code == 200
    assert open_app.get("/health/ready").json()["checks"]["auth"] == "disabled"


def test_with_keys_readiness_reports_auth_enabled(secured):
    assert secured.get("/health/ready").json()["checks"]["auth"] == "enabled"


def test_the_startup_warning_names_the_variable(caplog):
    """The warning is the only signal an operator gets that they are exposed,
    so it has to say what to set."""
    with caplog.at_level("WARNING"):
        create_app(settings=Settings(database_url=None, api_keys=None))
    assert any("VOXGATE_API_KEYS" in r.getMessage() for r in caplog.records)
