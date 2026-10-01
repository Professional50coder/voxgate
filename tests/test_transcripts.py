"""Transcript vault — timestamped session transcripts, summaries, artifacts.

Offline only: tmp-path storage, template summaries (no LLM)."""
import json

from voxgate.config import Settings
from voxgate.transcripts import (
    TranscriptRecorder,
    list_sessions,
    load_session,
    render_markdown,
)


def _settings(tmp_path):
    return Settings(groq_api_key=None, transcripts_dir=tmp_path / "vault")


def test_recorder_persists_timestamped_finals_only(tmp_path):
    s = _settings(tmp_path)
    r = TranscriptRecorder("case-1", s)
    r.add("agent", "What is your full legal name?", interim=False)
    r.add("applicant", "Priya Raghavan", interim=True)     # interims never persist
    r.add("applicant", "Priya Raghavan", interim=False)
    vault = tmp_path / "vault" / "case-1"
    lines = [json.loads(ln) for ln in
             (vault / f"{r.session_id}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert all(e["final"] for e in lines)
    assert {e["role"] for e in lines} == {"agent", "applicant"}
    assert lines[0]["offset_ms"] <= lines[1]["offset_ms"]


def test_finalize_writes_summary_and_markdown(tmp_path):
    s = _settings(tmp_path)
    r = TranscriptRecorder("case-1", s)
    r.add("agent", "Good morning. What is your full legal name?")
    r.add("applicant", "Priya Raghavan")
    r.note_guardrail("smalltalk")
    summary = r.finalize(outcome="completed", fields_collected={"full_name": "Priya"})
    base = tmp_path / "vault" / "case-1" / r.session_id
    saved = json.loads((base.with_name(base.name + ".summary.json"))
                       .read_text(encoding="utf-8"))
    assert saved["outcome"] == "completed"
    assert saved["fields_captured"] == {"full_name": "Priya"}
    assert saved["guardrail"]["smalltalk"] == 1

    md = (base.with_name(base.name + ".md")).read_text(encoding="utf-8")
    assert "## Summary" in md and "## Transcript" in md
    assert "Priya Raghavan" in md
    assert "[00:00]" in md or "[00:0" in md            # mm:ss timestamps rendered
    assert summary == saved


def test_list_and_load_sessions_roundtrip(tmp_path):
    s = _settings(tmp_path)
    r1 = TranscriptRecorder("case-9", s)
    r1.add("applicant", "hello")
    r1.finalize(outcome="interrupted")
    sessions = list_sessions("case-9", s)
    assert len(sessions) == 1
    assert sessions[0]["outcome"] == "interrupted"

    loaded = load_session("case-9", r1.session_id, s)
    assert loaded["summary"]["session_id"] == r1.session_id
    assert loaded["entries"][0]["text"] == "hello"
    assert load_session("case-9", "missing-session", s) is None


def test_render_markdown_handles_empty_and_interim(tmp_path):
    md = render_markdown({"case_id": "c", "session_id": "x", "outcome": "completed",
                          "duration_ms": 1500, "turns_applicant": 0,
                          "turns_agent": 0}, [])
    assert "_No finalized utterances were recorded._" in md
