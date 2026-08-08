"""Tracing: every call is recorded to a `traces/<session>.jsonl` file."""
import json

from types import SimpleNamespace as NS


def test_write_records_to_jsonl(tmp_path):
    from voxgate import tracing
    settings = NS(traces_dir=tmp_path)
    rec = tracing.write(settings, session="abc", category="groq.chat",
                        provider="groq", model="m", ok=True)
    assert rec["session"] == "abc"
    assert rec["category"] == "groq.chat"
    lines = (tmp_path / "abc.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["provider"] == "groq"
    assert data["ok"] is True


def test_traces_dir_created(tmp_path):
    from voxgate import tracing
    d = tmp_path / "traces"
    tracing.traces_dir(NS(traces_dir=d))
    assert d.exists()


def test_write_is_safe_on_errors(tmp_path):
    from voxgate import tracing
    # A settings object missing `traces_dir` must not raise.
    rec = tracing.write(NS(), session="x", category="c")
    assert rec["session"] == "x"


def test_groq_chat_traces_real_key(monkeypatch, tmp_path):
    """A real Groq-backed call path records a trace via _chat_json."""
    import voxgate.groq_brain as g
    from voxgate import tracing

    class R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"value":"y","confidence":0.9}'}}]}

    monkeypatch.setattr(g, "get_settings",
                        lambda: NS(groq_api_key="gsk_test", traces_dir=tmp_path))
    monkeypatch.setattr(g.httpx, "post", lambda *a, **k: R())
    out = g.interpret_answer("nationality", "I am from Germany", session="case-1",
                             settings=NS(groq_api_key="gsk_test", traces_dir=tmp_path))
    assert out["value"] == "y"
    lines = (tmp_path / "case-1.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert any("groq.chat" in l for l in lines)