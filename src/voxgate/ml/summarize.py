"""Session summaries for the transcript vault.

The deterministic template is always produced, so an instance with no Groq key
still writes a complete artifact. When a key is configured, a model writes the
narrative paragraph and risk notes instead; the counts and captured fields are
never taken from the model.

Plugs into ``TranscriptRecorder.finalize(summarizer=...)``.
"""
from __future__ import annotations

import logging

from voxgate.config import Settings, get_settings

log = logging.getLogger(__name__)

_SYSTEM = (
    "You summarize a structured voice-interview transcript for a {purpose} case "
    "file. Write ONE factual paragraph of at most 90 words: which fields the "
    "applicant provided, anything a reviewer should notice (refusals, confusion, "
    "corrections, contradictions, off-topic or sensitive remarks) and how the "
    "session ended. Neutral tone, no marketing language, and never state a fact "
    "that is not in the transcript. risk_notes are short reviewer-facing flags; "
    "leave the list empty when there is nothing to flag."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "risk_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["narrative", "risk_notes"],
    "additionalProperties": False,
}


class SessionSummarizer:
    def __init__(self, settings: Settings | None = None, purpose: str = "compliance"):
        self.settings = settings or get_settings()
        self.purpose = purpose

    def summarize(self, *, case_id: str, session_id: str, entries: list[dict],
                  fields_collected: dict | None = None, outcome: str = "completed",
                  duration_ms: float = 0, guardrail_stats: dict | None = None) -> dict:
        fields = dict(fields_collected or {})
        guard = dict(guardrail_stats or {})
        applicant = [e for e in entries if e.get("role") == "applicant"]
        summary = {
            "turns_applicant": len(applicant),
            "narrative": _template(case_id, session_id, outcome, len(applicant), fields, guard),
            "risk_notes": [f"{k}:{v}" for k, v in guard.items() if v],
            "source": "template",
        }
        keys = self.settings.groq_key_pool()
        if not keys or not applicant:
            return summary
        from voxgate.ml.groq_client import GroqError, structured_call
        transcript = "\n".join(f"[{e.get('offset_ms', 0) // 1000}s] {e['role']}: {e['text']}"
                               for e in entries)
        try:
            result = structured_call(
                api_keys=keys, schema=SCHEMA, schema_name="session_summary",
                preferred_model=self.settings.groq_model, max_tokens=600,
                system=_SYSTEM.format(purpose=self.purpose),
                user=(f"Outcome: {outcome}\nFields captured: {fields}\n"
                      f"Guardrail counts: {guard}\n\nTRANSCRIPT:\n{transcript}"))
        except GroqError as exc:
            log.warning("summary fell back to template: %s", exc)
            return summary
        summary["narrative"] = result.content["narrative"].strip()
        summary["risk_notes"] = [str(n)[:200] for n in result.content["risk_notes"]][:8]
        summary["source"] = "llm"
        return summary


def _template(case_id, session_id, outcome, turns, fields, guard) -> str:
    shown = ", ".join(f"{k}={str(v)[:40]}" for k, v in fields.items())
    flagged = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in guard.items() if v)
    return (f"Interview session '{session_id}' on case {case_id} ended as '{outcome}' "
            f"after {turns} applicant turn(s). "
            + (f"Fields provided: {shown}. " if shown else "No fields were captured. ")
            + (f"Guardrail handled: {flagged}." if flagged else "No guardrail events."))
