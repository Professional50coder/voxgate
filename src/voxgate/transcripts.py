"""Transcript vault: timestamped per-session transcripts + auto-summaries.

Every voice/text agent session writes a deployable compliance artifact set
under ``transcripts/<case_id>/`` (configurable via ``VOXGATE_TRANSCRIPTS_DIR``):

    <session_id>.jsonl         one JSON line per final utterance:
                               {ts, offset_ms, role, text, final}
    <session_id>.summary.json  machine-readable summary (LLM narrative when a
                               key/model is live, deterministic template else)
    <session_id>.md            human-readable transcript + summary for reviewers

Writes are crash-safe (append-per-line, flushed) and best-effort: a failing
disk must never break an interview.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from voxgate.config import Settings, get_settings

_lock = threading.Lock()

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(name: str) -> str:
    return _SAFE.sub("_", name or "")[:120] or "unknown"


def sessions_dir(case_id: str, settings: Settings | None = None) -> Path:
    d = Path((settings or get_settings()).transcripts_dir) / _safe(case_id)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 - read-only FS: recorder degrades to memory
        pass
    return d


def new_session_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TranscriptRecorder:
    """Records one session's utterances with timestamps; finalize() persists the
    summary + markdown artifacts."""

    def __init__(self, case_id: str, settings: Settings | None = None,
                 session_id: str | None = None):
        self.case_id = case_id
        self.settings = settings or get_settings()
        self.session_id = session_id or new_session_id()
        self.started_monotonic = time.monotonic()
        self.entries: list[dict] = []
        self.closed = False
        self._path = sessions_dir(case_id, self.settings) / f"{_safe(self.session_id)}.jsonl"
        self._guardrail = {"off_topic": 0, "sensitive": 0, "smalltalk": 0,
                           "process_question": 0}

    # ------------------------------------------------------------- recording

    def add(self, role: str, text: str, *, interim: bool = False) -> dict | None:
        """Append one utterance. Interims update stats only — finals persist."""
        if self.closed or not (text or "").strip():
            return None
        entry = {
            "ts": _iso(),
            "offset_ms": round((time.monotonic() - self.started_monotonic) * 1000),
            "role": role,
            "text": text.strip(),
            "final": not interim,
        }
        if interim:
            return entry
        self.entries.append(entry)
        try:
            with _lock:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - tracing must never break the session
            pass
        return entry

    def note_guardrail(self, label: str) -> None:
        if label in self._guardrail:
            self._guardrail[label] += 1

    @property
    def duration_ms(self) -> float:
        return (time.monotonic() - self.started_monotonic) * 1000.0

    def guardrail_stats(self) -> dict:
        return dict(self._guardrail)

    # -------------------------------------------------------------- finalize

    def finalize(self, *, outcome: str = "completed",
                 summarizer=None, fields_collected: dict | None = None,
                 extra: dict | None = None) -> dict | None:
        """Write ``<session>.summary.json`` and ``<session>.md``; returns summary."""
        if self.closed:
            return None
        self.closed = True
        summary = {
            "case_id": self.case_id,
            "session_id": self.session_id,
            "outcome": outcome,
            "duration_ms": round(self.duration_ms),
            "turns_applicant": sum(1 for e in self.entries if e["role"] == "applicant"),
            "turns_agent": sum(1 for e in self.entries if e["role"] == "agent"),
            "fields_captured": dict(fields_collected or {}),
            "guardrail": self.guardrail_stats(),
            "first_seen": self.entries[0]["ts"] if self.entries else None,
            "last_seen": self.entries[-1]["ts"] if self.entries else None,
            "source": "template",
        }
        if summarizer is not None:
            try:
                llm_summary = summarizer.summarize(
                    case_id=self.case_id, session_id=self.session_id,
                    entries=self.entries, fields_collected=fields_collected or {},
                    outcome=outcome, duration_ms=self.duration_ms,
                    guardrail_stats=self.guardrail_stats())
                for k in ("narrative", "risk_notes", "source"):
                    if k in llm_summary:
                        summary[k] = llm_summary[k]
                if summary.get("source") == "llm":
                    summary["turns_applicant"] = max(summary["turns_applicant"],
                                                     llm_summary.get("turns_applicant", 0))
            except Exception:  # noqa: BLE001 - template fallback already present
                pass
        if extra:
            summary.update(extra)
        base = self._path.with_suffix("")
        try:
            with _lock:
                with open(base.with_name(base.name + ".summary.json"), "w",
                          encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass
        try:
            with _lock:
                with open(base.with_name(base.name + ".md"), "w",
                          encoding="utf-8") as f:
                    f.write(render_markdown(summary, self.entries))
        except Exception:  # noqa: BLE001
            pass
        return summary


# ------------------------------------------------------------------ reading

def list_sessions(case_id: str, settings: Settings | None = None) -> list[dict]:
    d = sessions_dir(case_id, settings)
    out = []
    try:
        for p in sorted(d.glob("*.summary.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            sid = p.name[: -len(".summary.json")]
            out.append({
                "session_id": sid,
                "outcome": data.get("outcome"),
                "duration_ms": data.get("duration_ms"),
                "turns_applicant": data.get("turns_applicant"),
                "fields_captured_count": len(data.get("fields_captured") or {}),
                "has_transcript": (d / f"{sid}.jsonl").exists(),
                "first_seen": data.get("first_seen"),
                "last_seen": data.get("last_seen"),
                "source": data.get("source"),
            })
    except OSError:
        return []
    return out


def load_session(case_id: str, session_id: str,
                 settings: Settings | None = None) -> dict | None:
    d = sessions_dir(case_id, settings)
    entries = []
    try:
        lines = (d / f"{_safe(session_id)}.jsonl").read_text(encoding="utf-8")
        entries = [json.loads(ln) for ln in lines.splitlines() if ln.strip()]
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 - partial artifacts still readable
        entries = []
    try:
        summary = json.loads(
            (d / f"{_safe(session_id)}.summary.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        summary = None
    if not entries and summary is None:
        return None
    return {"case_id": case_id, "session_id": session_id,
            "entries": entries, "summary": summary}


def render_markdown(summary: dict, entries: list[dict]) -> str:
    def mmss(off_ms: int) -> str:
        s = int(off_ms // 1000)
        return f"{s // 60:02d}:{s % 60:02d}"

    lines = [
        f"# Interview transcript — case `{summary.get('case_id')}`",
        "",
        f"- **Session:** {summary.get('session_id')}",
        f"- **Outcome:** {summary.get('outcome')}",
        f"- **Duration:** {round((summary.get('duration_ms') or 0) / 1000)}s · "
        f"agent turns {summary.get('turns_agent', 0)} · "
        f"applicant turns {summary.get('turns_applicant', 0)}",
        f"- **Window:** {summary.get('first_seen')} → {summary.get('last_seen')}",
        f"- **Summary source:** {summary.get('source')}",
        "",
        "## Summary",
        "",
        str(summary.get("narrative", "")).strip() or "_No narrative generated._",
    ]
    notes = summary.get("risk_notes") or []
    if notes:
        lines += ["", "**Risk notes:**"]
        lines += [f"- {n}" for n in notes]
    captured = summary.get("fields_captured") or {}
    if captured:
        lines += ["", "**Fields captured:**"]
        lines += [f"- `{k}`: {v}" for k, v in captured.items()]
    lines += ["", "## Transcript", ""]
    if not entries:
        lines.append("_No finalized utterances were recorded._")
    for e in entries:
        who = "Agent" if e.get("role") == "agent" else "Applicant"
        mark = "" if e.get("final") else " *(interim)*"
        lines.append(f"`[{mmss(e.get('offset_ms', 0))}]` **{who}**{mark}: "
                     f"{e.get('text', '')}")
    lines.append("")
    return "\n".join(lines)
