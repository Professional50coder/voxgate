"""SessionSummarizer: template always, model narrative when a key works. Offline."""
from voxgate.config import Settings
from voxgate.ml import groq_client
from voxgate.ml.summarize import SessionSummarizer
from voxgate.transcripts import TranscriptRecorder

ENTRIES = [
    {"role": "agent", "text": "What is your full name?", "offset_ms": 0, "ts": "t0", "final": True},
    {"role": "applicant", "text": "Fatima Al Mansoori", "offset_ms": 2100, "ts": "t1", "final": True},
]


def _settings(tmp_path, key=None):
    return Settings(groq_api_key=key, groq_api_keys=None, transcripts_dir=tmp_path)


def test_template_without_a_key(tmp_path):
    s = SessionSummarizer(_settings(tmp_path)).summarize(
        case_id="c1", session_id="s1", entries=ENTRIES,
        fields_collected={"full_name": "Fatima Al Mansoori"},
        guardrail_stats={"off_topic": 1, "sensitive": 0})
    assert s["source"] == "template"
    assert "full_name=Fatima Al Mansoori" in s["narrative"]
    assert s["risk_notes"] == ["off_topic:1"]


def test_model_narrative_when_a_key_works(tmp_path, monkeypatch):
    monkeypatch.setattr(groq_client, "structured_call", lambda **kw: groq_client.GroqResult(
        content={"narrative": "Applicant gave their name.", "risk_notes": []},
        model="m", attempts=1, fell_back=False))
    s = SessionSummarizer(_settings(tmp_path, "k")).summarize(
        case_id="c1", session_id="s1", entries=ENTRIES)
    assert (s["source"], s["narrative"]) == ("llm", "Applicant gave their name.")


def test_a_failing_model_keeps_the_template(tmp_path, monkeypatch):
    def boom(**kw):
        raise groq_client.GroqRateLimited("all limited")
    monkeypatch.setattr(groq_client, "structured_call", boom)
    s = SessionSummarizer(_settings(tmp_path, "k")).summarize(
        case_id="c1", session_id="s1", entries=ENTRIES)
    assert s["source"] == "template"


def test_plugs_into_the_transcript_vault(tmp_path):
    settings = _settings(tmp_path)
    rec = TranscriptRecorder("case-9", settings)
    rec.add("agent", "What is your full name?")
    rec.add("applicant", "Fatima Al Mansoori")
    out = rec.finalize(summarizer=SessionSummarizer(settings),
                       fields_collected={"full_name": "Fatima Al Mansoori"})
    assert out["source"] == "template" and "Fatima" in out["narrative"]
    assert list((tmp_path / "case-9").glob("*.md"))
