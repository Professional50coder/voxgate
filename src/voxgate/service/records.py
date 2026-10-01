"""Durable records beside the case: transcripts and the agent store.

Same shape as store.py: a Postgres implementation for real deployments and an
in-memory one for a single process and the test suite, behind one interface,
so the API never asks which one it has.
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Protocol

from psycopg.types.json import Jsonb

# Bounds on what one request may write. A transcript turn is a sentence or two;
# a session is a few minutes of conversation.
MAX_TURN_CHARS = 2_000
MAX_TURNS_PER_SESSION = 400

_SID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def new_session_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def valid_session_id(session_id: str) -> bool:
    return bool(_SID.match(session_id or ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TranscriptStore(Protocol):
    def append(self, tenant: str, case_id: str, session_id: str, turns: list[dict],
               channel: str = "web") -> int: ...
    def finish(self, tenant: str, case_id: str, session_id: str, summary: dict) -> None: ...
    def sessions(self, tenant: str, case_id: str) -> list[dict]: ...
    def load(self, tenant: str, case_id: str, session_id: str) -> dict | None: ...
    def search(self, tenant: str, query: str, limit: int = 20) -> list[dict]: ...
    def all_sessions(self, tenant: str) -> list[dict]: ...


class InMemoryTranscriptStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (tenant, case, session) -> {"channel", "started_at", "finished_at", "summary", "turns"}
        self._s: dict[tuple[str, str, str], dict] = {}

    def append(self, tenant, case_id, session_id, turns, channel="web"):
        with self._lock:
            s = self._s.setdefault((tenant, case_id, session_id), {
                "channel": channel, "started_at": _now(), "finished_at": None,
                "summary": None, "turns": []})
            room = MAX_TURNS_PER_SESSION - len(s["turns"])
            for t in turns[:max(room, 0)]:
                s["turns"].append({"turn_no": len(s["turns"]), "ts": _now(),
                                   "offset_ms": int(t.get("offset_ms") or 0),
                                   "role": t["role"], "text": t["text"][:MAX_TURN_CHARS]})
            return len(s["turns"])

    def finish(self, tenant, case_id, session_id, summary):
        with self._lock:
            s = self._s.setdefault((tenant, case_id, session_id), {
                "channel": "web", "started_at": _now(), "turns": []})
            s["finished_at"], s["summary"] = _now(), summary

    def sessions(self, tenant, case_id):
        return [_session_row(cid, sid, s) for (t, cid, sid), s in sorted(self._s.items())
                if t == tenant and cid == case_id]

    def load(self, tenant, case_id, session_id):
        s = self._s.get((tenant, case_id, session_id))
        if s is None:
            return None
        return {"case_id": case_id, "session_id": session_id,
                "entries": list(s["turns"]), "summary": s.get("summary")}

    def search(self, tenant, query, limit=20):
        words = [w for w in re.findall(r"\w+", (query or "").lower()) if w]
        if not words:
            return []
        hits = []
        for (t, cid, sid), s in self._s.items():
            if t != tenant:
                continue
            for turn in s["turns"]:
                low = turn["text"].lower()
                if all(w in low for w in words):
                    hits.append({"case_id": cid, "session_id": sid, "turn_no": turn["turn_no"],
                                 "role": turn["role"], "text": turn["text"], "ts": turn["ts"]})
        return hits[:limit]

    def all_sessions(self, tenant):
        return [_session_row(cid, sid, s) for (t, cid, sid), s in self._s.items() if t == tenant]


def _session_row(case_id, session_id, s) -> dict:
    turns = s.get("turns", [])
    return {"case_id": case_id, "session_id": session_id, "channel": s.get("channel", "web"),
            "started_at": s.get("started_at"), "finished_at": s.get("finished_at"),
            "turns": len(turns), "summary": s.get("summary")}


class PgTranscriptStore:
    def __init__(self, pool) -> None:
        self._pool = pool

    def append(self, tenant, case_id, session_id, turns, channel="web"):
        with self._pool.connection() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO transcript_sessions (tenant_id, case_id, session_id, channel) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (tenant, case_id, session_id, channel), prepare=False)
            # Serialise numbering per session without a sequence: the session
            # row is the lock, so two appends cannot take the same turn_no.
            conn.execute(
                "SELECT 1 FROM transcript_sessions WHERE tenant_id=%s AND case_id=%s "
                "AND session_id=%s FOR UPDATE", (tenant, case_id, session_id), prepare=False)
            row = conn.execute(
                "SELECT COALESCE(MAX(turn_no) + 1, 0) AS n FROM transcript_turns "
                "WHERE tenant_id=%s AND case_id=%s AND session_id=%s",
                (tenant, case_id, session_id), prepare=False).fetchone()
            n = row["n"]
            for t in turns[:max(MAX_TURNS_PER_SESSION - n, 0)]:
                conn.execute(
                    "INSERT INTO transcript_turns (tenant_id, case_id, session_id, turn_no, "
                    "offset_ms, role, text) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (tenant, case_id, session_id, n, int(t.get("offset_ms") or 0),
                     t["role"], t["text"][:MAX_TURN_CHARS]), prepare=False)
                n += 1
            return n

    def finish(self, tenant, case_id, session_id, summary):
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO transcript_sessions (tenant_id, case_id, session_id, finished_at, "
                "summary) VALUES (%s, %s, %s, now(), %s) ON CONFLICT (tenant_id, case_id, "
                "session_id) DO UPDATE SET finished_at = now(), summary = EXCLUDED.summary",
                (tenant, case_id, session_id, Jsonb(summary)), prepare=False)

    _SESSIONS = (
        "SELECT s.case_id, s.session_id, s.channel, s.started_at, s.finished_at, s.summary, "
        "(SELECT count(*) FROM transcript_turns t WHERE t.tenant_id=s.tenant_id AND "
        " t.case_id=s.case_id AND t.session_id=s.session_id) AS turns "
        "FROM transcript_sessions s WHERE s.tenant_id=%s")

    def sessions(self, tenant, case_id):
        with self._pool.connection() as conn:
            rows = conn.execute(self._SESSIONS + " AND s.case_id=%s ORDER BY s.started_at",
                                (tenant, case_id), prepare=False).fetchall()
        return [_iso(r) for r in rows]

    def load(self, tenant, case_id, session_id):
        with self._pool.connection() as conn:
            head = conn.execute(
                "SELECT summary FROM transcript_sessions WHERE tenant_id=%s AND case_id=%s "
                "AND session_id=%s", (tenant, case_id, session_id), prepare=False).fetchone()
            if head is None:
                return None
            turns = conn.execute(
                "SELECT turn_no, ts, offset_ms, role, text FROM transcript_turns WHERE "
                "tenant_id=%s AND case_id=%s AND session_id=%s ORDER BY turn_no",
                (tenant, case_id, session_id), prepare=False).fetchall()
        return {"case_id": case_id, "session_id": session_id,
                "entries": [_iso(t) for t in turns], "summary": head["summary"]}

    def search(self, tenant, query, limit=20):
        if not (query or "").strip():
            return []
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT case_id, session_id, turn_no, role, text, ts, "
                "ts_rank(tsv, q) AS rank FROM transcript_turns, "
                "websearch_to_tsquery('simple', %s) q WHERE tenant_id=%s AND tsv @@ q "
                "ORDER BY rank DESC, ts DESC LIMIT %s",
                (query, tenant, min(int(limit), 100)), prepare=False).fetchall()
        return [_iso(r) for r in rows]

    def all_sessions(self, tenant):
        with self._pool.connection() as conn:
            rows = conn.execute(self._SESSIONS, (tenant,), prepare=False).fetchall()
        return [_iso(r) for r in rows]


def _iso(row: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}


# --------------------------------------------------------------------------
# The agent store
# --------------------------------------------------------------------------

class PackStore(Protocol):
    def save(self, tenant: str, spec: dict, created_by: str | None) -> None: ...
    def specs(self, tenant: str) -> list[dict]: ...
    def listing(self, tenant: str) -> list[dict]: ...


class InMemoryPackStore:
    """Single-process stand-in. Publishing still writes the pack to disk; this
    only remembers who published what, for the store listing."""

    def __init__(self) -> None:
        self._p: dict[tuple[str, str], dict] = {}

    def save(self, tenant, spec, created_by):
        prev = self._p.get((tenant, spec["pack_id"]))
        self._p[(tenant, spec["pack_id"])] = {
            "pack_id": spec["pack_id"], "display_name": spec.get("display_name", spec["pack_id"]),
            "spec": spec, "created_by": created_by,
            "created_at": prev["created_at"] if prev else _now(), "updated_at": _now()}

    def specs(self, tenant):
        return [v["spec"] for (t, _), v in self._p.items() if t == tenant]

    def listing(self, tenant):
        return [{k: v for k, v in row.items() if k != "spec"}
                for (t, _), row in self._p.items() if t == tenant]


class PgPackStore:
    def __init__(self, pool) -> None:
        self._pool = pool

    def save(self, tenant, spec, created_by):
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO published_packs (tenant_id, pack_id, display_name, spec, created_by) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (tenant_id, pack_id) DO UPDATE SET "
                "display_name = EXCLUDED.display_name, spec = EXCLUDED.spec, "
                "created_by = EXCLUDED.created_by, updated_at = now()",
                (tenant, spec["pack_id"], spec.get("display_name", spec["pack_id"]),
                 Jsonb(spec), created_by), prepare=False)

    def specs(self, tenant):
        with self._pool.connection() as conn:
            rows = conn.execute("SELECT spec FROM published_packs WHERE tenant_id=%s",
                                (tenant,), prepare=False).fetchall()
        return [r["spec"] for r in rows]

    def listing(self, tenant):
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT pack_id, display_name, created_by, created_at, updated_at FROM "
                "published_packs WHERE tenant_id=%s ORDER BY updated_at DESC",
                (tenant,), prepare=False).fetchall()
        return [_iso(r) for r in rows]
