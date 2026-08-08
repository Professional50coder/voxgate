"""Pipecat voice agent — structure, scenarios, and LangGraph anchoring.

Pure offline checks (no live audio): the module imports, the scenario registry
is populated, the interview-plan renderer works, and the app registers the
websocket + scenarios routes.
"""
from fastapi.testclient import TestClient

from voxgate.service.app import create_app
from voxgate.service.voice.agent import (
    SCENARIOS,
    _interview_plan,
    run_case_voice,
    scenario_system,
)


def test_scenario_registry_multiple_usecases():
    assert {"kyc-interview", "onboarding", "support", "kyc-crypto",
            "risk-review", "general", "followup", "multilang"} <= set(SCENARIOS)
    for sid, spec in SCENARIOS.items():
        assert spec["display_name"]
        assert spec["system"]


def test_scenario_system_includes_time_of_day():
    text = scenario_system("kyc-interview")
    assert "greet" in text.lower() or "greeting" in text.lower()
    assert any(pod in text for pod in ("morning", "afternoon", "evening", "night"))


def test_unknown_scenario_falls_back_to_kyc():
    text = scenario_system("does-not-exist")
    assert "KYC" in text


def test_interview_plan_orders_fields():
    plan = _interview_plan([
        {"field": "full_name", "hint": "What is your full legal name?"},
        {"field": "dob"},
    ])
    assert plan.startswith("Collect these fields IN ORDER")
    assert plan.index("full_name") < plan.index("dob")


def test_interview_plan_empty_when_no_fields():
    assert _interview_plan(None) == ""
    assert _interview_plan([]) == ""


def test_voice_routes_registered():
    app = create_app()
    paths = [getattr(r, "path", (r.paths[0] if getattr(r, "paths", ()) else str(r)))
             for r in app.routes]
    assert "/cases/{case_id}/voice" in paths
    assert "/voice/scenarios" in paths


def test_scenarios_endpoint_lists_usecases():
    app = create_app()
    client = TestClient(app)
    r = client.get("/voice/scenarios")
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()}
    assert "kyc-interview" in ids and "support" in ids
