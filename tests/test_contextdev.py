"""Context.dev optional enrichment client — tested with a mocked HTTP transport.

No network calls and no real API key are used anywhere here: the module is a
no-op (returns None) without a key, and every HTTP interaction is replaced via
monkeypatch. See src/voxgate/contextdev.py for the design notes.
"""
import pytest
import httpx
import voxgate.contextdev as cd


class FakeResp:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=httpx.Request("POST", "http://x"),
                response=httpx.Response(self.status_code, request=httpx.Request("POST", "http://x")))

    def json(self):
        return self._payload


def _patch_http(monkeypatch, responses):
    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        resp = responses[idx]
        if callable(resp):
            return resp(url=url, json=json, headers=headers)
        return resp

    monkeypatch.setattr(cd.httpx, "post", fake_post)
    monkeypatch.setattr(cd.time, "sleep", lambda s: None)
    return calls


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("CONTEXT_DEV_API_KEY", raising=False)
    monkeypatch.delenv("CONTEXT_API_KEY", raising=False)
    monkeypatch.setattr(cd, "get_settings", lambda: type("S", (), {"context_dev_api_key": None})())
    assert cd.is_enabled() is False
    assert cd.brand_lookup("example.com") is None
    assert cd.scrape_markdown("https://example.com") is None


def test_brand_lookup_returns_brand(monkeypatch):
    brand = {"domain": "acme.com", "title": "Acme"}
    _patch_http(monkeypatch, [FakeResp(200, {"status": "ok", "brand": brand})])
    key = cd._Client("ctxt_test")
    result = cd.brand_lookup("acme.com", settings=_settings(key))
    assert result == brand


def test_brand_lookup_not_found_returns_none(monkeypatch):
    _patch_http(monkeypatch, [FakeResp(404, {})])
    key = cd._Client("ctxt_test")
    out = cd.brand_lookup("nope.example", settings=_settings(key))
    assert out is None


def test_brand_lookup_401_raises_permission_error(monkeypatch):
    _patch_http(monkeypatch, [FakeResp(401, {})])
    key = cd._Client("bad_key")
    with pytest.raises(PermissionError):
        cd.brand_lookup("acme.com", settings=_settings(key))


def test_retry_on_408_then_success(monkeypatch):
    brand = {"domain": "acme.com", "title": "Acme"}
    _patch_http(monkeypatch, [
        FakeResp(408, {}, {"Retry-After": "0"}),
        FakeResp(200, {"status": "ok", "brand": brand}),
    ])
    key = cd._Client("ctxt_test")
    out = cd.brand_lookup("acme.com", settings=_settings(key))
    assert out == brand


def test_retry_on_429_then_success(monkeypatch):
    brand = {"domain": "acme.com", "title": "Acme"}
    _patch_http(monkeypatch, [
        FakeResp(429, {}, {"Retry-After": "0"}),
        FakeResp(200, {"status": "ok", "brand": brand}),
    ])
    key = cd._Client("ctxt_test")
    out = cd.brand_lookup("acme.com", settings=_settings(key))
    assert out == brand


def test_scrape_markdown(monkeypatch):
    _patch_http(monkeypatch, [FakeResp(200, {"success": True, "markdown": "# Hi"})])
    key = cd._Client("ctxt_test")
    assert cd.scrape_markdown("https://acme.com", settings=_settings(key)) == "# Hi"


def test_domain_from_identity():
    assert cd.domain_from_identity("bob@acme.io") == "acme.io"
    assert cd.domain_from_identity("nope") is None
    assert cd.domain_from_identity(None) is None


def _settings(key):
    return type("S", (), {"context_dev_api_key": key})()