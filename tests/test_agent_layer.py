"""Per-pack agents, the shared brain, and the voice/assistant endpoints. Offline."""
import time

import pytest
from fastapi.testclient import TestClient

from voxgate.config import Settings
from voxgate.dialogue import brain, phrasing
from voxgate.dialogue.assistant import ACTIONS, answer
from voxgate.ml.understanding import Intent, classify
from voxgate.packs.agent import AgentProfile
from voxgate.service.app import create_app

KYC_AGENT = AgentProfile(
    name="Lucy", blocked_topics=["crypto tips"], sensitive_terms=["iban"],
    process_answers={"duration": "About three minutes."})


def _offline_settings(**kw):
    return Settings(groq_api_key=None, groq_api_keys=None, cartesia_api_key=None, **kw)


# ----------------------------------------------------------------- understanding

@pytest.mark.parametrize("spoken,intent", [
    ("my card number is 4111 1111 1111 1111", Intent.SENSITIVE),
    ("the OTP is 4421", Intent.SENSITIVE),
    ("hello there", Intent.SMALLTALK),
    ("thank you so much", Intent.SMALLTALK),
    ("how long will this take?", Intent.PROCESS),
    ("is this call being recorded", Intent.PROCESS),
    ("are you a real person?", Intent.PROCESS),
    ("thanks, it's Fatima Al Mansoori", Intent.ANSWER),
    ("I don't know", Intent.DONT_KNOW),
])
def test_platform_intents(spoken, intent):
    assert classify(spoken) is intent


def test_agent_rules_run_before_platform_rules():
    assert brain.understand("my IBAN is AE07...", KYC_AGENT) == \
        brain.Understanding(Intent.SENSITIVE, rule="agent")
    assert brain.understand("any crypto tips for me?", KYC_AGENT).intent is Intent.OFF_TOPIC
    # A different agent has no such rule, so the same words are just an answer.
    assert brain.understand("any crypto tips for me?").intent is Intent.ANSWER


def test_agent_wording_overrides_process_answers():
    c = brain.Counters()
    u = brain.understand("how long does this take", KYC_AGENT)
    assert brain.non_answer_reply(u, "Your name?", c, KYC_AGENT) == "About three minutes. Your name?"


def test_smalltalk_budget_then_nudge():
    agent, c = AgentProfile(max_smalltalk=1), brain.Counters()
    u = brain.understand("hello")
    first = brain.non_answer_reply(u, "Q?", c, agent)
    second = brain.non_answer_reply(u, "Q?", c, agent)
    assert first.endswith("Q?") and "keep going" not in first
    assert "keep going" in second


def test_off_topic_gets_plainer():
    c = brain.Counters()
    u = brain.Understanding(Intent.OFF_TOPIC)
    assert brain.non_answer_reply(u, "Q?", c) != brain.non_answer_reply(u, "Q?", c)


def test_sensitive_reply_never_echoes_the_number():
    reply = phrasing.refuse_sensitive("What is your name?")
    assert "4111" not in reply and "not recorded" in reply


def test_unknown_process_topic_in_a_pack_is_rejected():
    with pytest.raises(ValueError):
        AgentProfile(process_answers={"weather": "sunny"})


def test_rules_layer_is_sub_millisecond():
    lines = ["hello", "how long will this take", "my pin is 1234", "Fatima Al Mansoori",
             "I'd rather not say", "any crypto tips?"] * 200
    t0 = time.perf_counter()
    for line in lines:
        brain.understand(line, KYC_AGENT)
    per_turn_ms = (time.perf_counter() - t0) * 1000 / len(lines)
    assert per_turn_ms < 1.0, f"{per_turn_ms:.3f} ms per turn"


# --------------------------------------------------------------------- service

@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(_offline_settings()))


def test_every_pack_exposes_its_agent(client):
    packs = {p["pack_id"]: p for p in client.get("/packs").json()}
    assert packs["kyc-uae"]["agent"]["name"] == "Lucy"
    assert packs["patient-intake"]["agent"]["name"] == "Iris"
    assert all(p["agent"]["voice"]["fallback"] for p in packs.values())


def test_extract_applies_the_pack_agent_rules_and_reports_timing(client):
    r = client.post("/packs/kyc-uae/extract", json={
        "field": "full_name", "spoken": "my IBAN is AE070331234567890123456"}).json()
    assert (r["intent"], r["rule"], r["value"]) == ("sensitive", "agent", None)
    assert "not recorded" in r["prompt"]
    assert r["timing_ms"]["understand"] < 5


def test_extract_round_trips_conversation_counters(client):
    r = client.post("/packs/kyc-uae/extract", json={
        "field": "full_name", "spoken": "hello", "smalltalk_used": 0}).json()
    assert r["intent"] == "smalltalk" and r["counters"]["smalltalk_used"] == 1
    r = client.post("/packs/kyc-uae/extract", json={
        "field": "full_name", "spoken": "hi", "smalltalk_used": 1}).json()
    assert "keep going" in r["prompt"]  # kyc-uae allows one pleasantry


def test_tts_without_a_key_tells_the_page_to_use_its_own_voice(client):
    assert client.post("/tts", json={"text": "Hello"}).status_code == 503
    assert client.post("/tts", json={"text": "Hi", "pack_id": "nope"}).status_code == 404


def test_assistant_answers_offline_with_an_allowed_action(client):
    r = client.post("/assistant", json={"message": "how does it work?",
                                        "page": "how-it-works"}).json()
    assert r["source"] == "offline" and r["action"] in ACTIONS and r["reply"]


def test_assistant_drops_unknown_pages_to_home():
    r = answer("start a demo", page="nonsense", settings=_offline_settings())
    assert r["action"] == "start_interview"
