"""Groq LLM brain — tested with a mocked HTTP transport and keyless paths.

No network calls or real keys. Covers: keyless raw fallback, JSON extraction,
and degradation to the raw transcript on a non-2xx / badly-formed response.
"""
from types import SimpleNamespace as NS

import httpx

import voxgate.groq_brain as g

KEY = NS(groq_api_key="gsk_test")


def _resp(status=200, content='{"value": "uae_resident", "confidence": 0.98}'):
    class R:
        def raise_for_status(self):
            if status >= 400:
                raise httpx.HTTPStatusError(
                    str(status), request=httpx.Request("POST", "http://x"),
                    response=httpx.Response(status, request=httpx.Request("POST", "http://x")))

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    return R()


def _patch(monkeypatch, post, settings=KEY):
    monkeypatch.setattr(g, "get_settings", lambda: settings)
    monkeypatch.setattr(g.httpx, "post", post)


def test_disabled_returns_raw(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(AssertionError("no http")),
           settings=NS(groq_api_key=None))
    out = g.interpret_answer("product", "um, spot trading i think")
    assert out == {"value": "um, spot trading i think", "confidence": 0.5, "source": "raw"}
    assert g.is_enabled() is False


def test_disabled_never_calls_http(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call")

    _patch(monkeypatch, boom, settings=NS(groq_api_key=None))
    g.interpret_answer("product", "derive something")
    assert called["n"] == 0


def test_interpret_extracts_value(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["payload"] = json
        return _resp()

    _patch(monkeypatch, fake_post)
    res = g.interpret_answer("residency_status", "I am a UAE resident")
    assert res == {"value": "uae_resident", "confidence": 0.98, "source": "llm"}
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["payload"]["model"] == "openai/gpt-oss-120b"
    assert seen["payload"]["response_format"] == {"type": "json_object"}
    assert "residency_status" in seen["payload"]["messages"][1]["content"]
    assert "I am a UAE resident" in seen["payload"]["messages"][1]["content"]


def test_empty_transcript_skips_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call")

    _patch(monkeypatch, boom)
    res = g.interpret_answer("full_name", "   ")
    assert res == {"value": None, "confidence": 0.5, "source": "raw"}


def test_http_error_falls_back_to_raw(monkeypatch):
    def fuse(url, json=None, headers=None, timeout=None):
        raise httpx.HTTPError("boom")

    _patch(monkeypatch, fuse)
    res = g.interpret_answer("dob", "March fifth 1991")
    assert res["source"] == "raw"
    assert res["value"] == "March fifth 1991"


def test_bad_json_falls_back_to_raw(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: _resp(200, "not json at all"))
    res = g.interpret_answer("full_name", "Priya Raghavan")
    assert res["source"] == "raw"
    assert res["value"] == "Priya Raghavan"


def test_http_error_status_falls_back_to_raw(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: _resp(500, "nope"))
    res = g.interpret_answer("full_name", "Priya Raghavan")
    assert res["source"] == "raw"


def _agent_resp(line):
    return _resp(200, f'{{"line": "{line}"}}')


def test_agent_line_returns_llm_line(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["payload"] = json
        return _agent_resp("Thanks for confirming that. What is the main source of the funds?")

    _patch(monkeypatch, fake_post)
    res = g.agent_line("source_of_funds", "What is the main source of the funds you will use?",
                       last_captured={"field": "residency_status", "value": "uae_resident"})
    assert res == {"line": "Thanks for confirming that. What is the main source of the funds?",
                   "source": "llm"}
    # the just-captured field is included so the agent can acknowledge it
    assert "uae_resident" in seen["payload"]["messages"][1]["content"]


def test_agent_line_clarification_mentions_attempt(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["payload"] = json
        return _agent_resp("I'm sorry, could you spell that for me?")

    _patch(monkeypatch, fake_post)
    res = g.agent_line("full_name", "Could you spell your full name for me, please?",
                       transcript="Priv Ratavan", attempt=2)
    assert res["source"] == "llm"
    assert "Clarification attempt" in seen["payload"]["messages"][1]["content"]


def test_agent_line_falls_back_to_hint_when_disabled(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no http")

    _patch(monkeypatch, boom, settings=NS(groq_api_key=None))
    hint = "What is your date of birth?"
    res = g.agent_line("dob", hint)
    assert res == {"line": hint, "source": "raw"}


def test_agent_line_falls_back_to_hint_on_http_error(monkeypatch):
    def fuse(url, json=None, headers=None, timeout=None):
        raise httpx.HTTPError("boom")

    _patch(monkeypatch, fuse)
    hint = "Which country issued your passport?"
    res = g.agent_line("nationality", hint)
    assert res == {"line": hint, "source": "raw"}


# ----------------------------- time-of-day greeting -------------------------


def test_time_of_day_buckets():
    assert g.time_of_day(2) == "night"
    assert g.time_of_day(8) == "morning"
    assert g.time_of_day(14) == "afternoon"
    assert g.time_of_day(19) == "evening"
    assert g.time_of_day(23) == "night"
    assert g.time_of_day(0) == "night"


def test_greeting_disabled_returns_time_of_day_line(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(AssertionError("no http")),
           settings=NS(groq_api_key=None))
    res = g.greeting(name="Priya", hour=9)
    assert res["source"] == "raw"
    assert res["line"].startswith("Good morning")
    assert "Priya" in res["line"]


def test_greeting_uses_llm(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["payload"] = json
        return _resp(200, '{"line": "Good afternoon, Priya. I am VoxGate and I will run a short verification with you."}')

    _patch(monkeypatch, fake_post)
    res = g.greeting(name="Priya", hour=15)
    assert res["source"] == "llm"
    assert "Good afternoon" in res["line"]
    assert "time of day" in seen["payload"]["messages"][1]["content"]