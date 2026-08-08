"""Tracing: every outsourced call gets recorded to a `traces/` folder.

Each call (LLM chat, answer interpretation, agent-line, and later Pipecat
STT/LLM/TTS stages) is appended as one JSON line (JSONL) to
``<traces_dir>/<session>.jsonl`` so every interaction can be audited later.

The directory is configurable via ``VOXGATE_TRACES_DIR`` and defaults to the
repo's ``traces/`` folder. Records are skipped silently on write errors —
tracing must never break the interview.
"""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from voxgate.config import Settings, get_settings

_lock = threading.Lock()


def traces_dir(settings: Settings | None = None) -> Path:
    d = (settings or get_settings()).traces_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write(settings: Settings | None = None, *, session: str = "global",
          category: str = "call", **fields):
    """Append one trace line (a JSON object) to ``traces/<session>.jsonl``.

    Safe to call from any thread/handler; failures are swallowed.
    Returns the record dict it wrote (best-effort).
    """
    fields.setdefault("ts", _iso())
    rec = {"session": session or "global", "category": category, **fields}
    try:
        path = traces_dir(settings) / f"{session or 'global'}.jsonl"
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass
    return rec


def timed(settings: Settings | None = None, *, session: str = "", category: str = "", **meta):
    """Context manager that records duration_ms and OK/error around a call."""
    from contextlib import contextmanager

    started = time.perf_counter()

    @contextmanager
    def _cm():
        try:
            yield
            record(settings, session=session, category=category, ok=True,
                   duration_ms=round((time.perf_counter() - started) * 1000, 1), **meta)
        except Exception as exc:  # pragma: no cover - supersat server failure branch
            record(settings, session=session, category=category, ok=False,
                   duration_ms=round((time.perf_counter() - started) * 1000, 1),
                   error=f"{type(exc).__name__}: {exc}", **meta)
            raise
    return _cm()