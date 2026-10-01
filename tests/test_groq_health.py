"""Key and model health marks in structured_call. Offline: httpx.post is stubbed."""
import json

import httpx
import pytest

from voxgate.ml import groq_client as gc

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}


class _Resp:
    def __init__(self, status, model):
        self.status_code = status
        self._model = model

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", gc.GROQ_URL)
            raise httpx.HTTPStatusError("err", request=req,
                                        response=httpx.Response(self.status_code, request=req))

    def json(self):
        return {"choices": [{"message": {"content": json.dumps({"ok": True})}}]}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    gc.reset_health()
    monkeypatch.setattr(gc, "discover_models", lambda key, force=False: (["m1", "m2"], []))
    yield
    gc.reset_health()


def _stub(monkeypatch, status_for):
    calls = []

    def post(url, headers, json, timeout):
        key = headers["Authorization"].split()[1]
        calls.append((json["model"], key))
        return _Resp(status_for(json["model"], key), json["model"])

    monkeypatch.setattr(httpx, "post", post)
    return calls


def _call():
    return gc.structured_call(api_keys=["kA", "kB"], system="s", user="u",
                              schema=SCHEMA, schema_name="t")


def test_a_rejected_key_is_skipped_on_the_next_call(monkeypatch):
    calls = _stub(monkeypatch, lambda m, k: 401 if k == "kA" else 200)
    assert _call().key_index == 1
    calls.clear()
    _call()
    assert all(k == "kB" for _, k in calls)
    assert gc.key_health(["kA", "kB"]) == [{"index": 0, "status": "dead"},
                                           {"index": 1, "status": "ok"}]


def test_a_rate_limited_key_goes_to_the_back_not_out(monkeypatch):
    calls = _stub(monkeypatch, lambda m, k: 429 if k == "kA" else 200)
    _call()
    calls.clear()
    _call()
    assert calls[0][1] == "kB"
    assert gc.key_health(["kA"])[0]["status"] == "cooling"


def test_a_retired_model_is_demoted(monkeypatch):
    calls = _stub(monkeypatch, lambda m, k: 404 if m == "m1" else 200)
    assert _call().model == "m2"
    calls.clear()
    _call()
    assert calls[0][0] == "m2"


def test_marks_never_filter_down_to_nothing(monkeypatch):
    _stub(monkeypatch, lambda m, k: 401)
    with pytest.raises(gc.GroqError):
        _call()
    calls = _stub(monkeypatch, lambda m, k: 200)
    _call()
    assert calls, "every key dead must still attempt a call, not refuse outright"
