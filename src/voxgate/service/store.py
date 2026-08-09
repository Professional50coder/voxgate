"""The case index.

A **projection** of graph state, never a second source of truth. `_sync()`
rewrites rows from `graph.get_state()`; the checkpointer stays authoritative.
That is what makes two implementations safe: neither owns truth, so they cannot
disagree about it, only about query semantics. A shared contract suite pins
those down (`tests/contracts/test_case_store.py`).

Both implementations return **copies**. The original in-memory store handed out
live references to its internal dicts, so a caller mutating a returned case
silently corrupted store state without going through `upsert`. That was a
deferred finding from the first build; returning copies closes it.
"""

from __future__ import annotations

import copy
import json
import threading
from typing import Protocol, runtime_checkable

# Columns promoted out of the payload because the board queries on them.
# Everything else (fields, score, audit, interrupt, live_fields) rides in jsonb,
# so adding a case attribute never needs a migration.
_COLUMNS = ("tenant_id", "case_id", "pack_id", "status", "seq")


@runtime_checkable
class CaseStore(Protocol):
    def upsert(self, tenant_id: str, case: dict) -> dict: ...
    def get(self, tenant_id: str, case_id: str) -> dict | None: ...
    def list(self, tenant_id: str, pack_id: str | None = None) -> list[dict]: ...


class InMemoryCaseStore:
    """Dev and test implementation. Behaviour pinned by the contract suite."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cases: dict[tuple[str, str], dict] = {}
        self._seq = 0

    def upsert(self, tenant_id: str, case: dict) -> dict:
        key = (tenant_id, case["case_id"])
        with self._lock:
            existing = self._cases.get(key)
            if existing:
                merged = {**existing, **case}
            else:
                self._seq += 1
                merged = {**case, "seq": self._seq}
            merged["tenant_id"] = tenant_id
            self._cases[key] = merged
            return copy.deepcopy(merged)

    def get(self, tenant_id: str, case_id: str) -> dict | None:
        with self._lock:
            found = self._cases.get((tenant_id, case_id))
            return copy.deepcopy(found) if found is not None else None

    def list(self, tenant_id: str, pack_id: str | None = None) -> list[dict]:
        with self._lock:
            rows = [
                c
                for (t, _), c in self._cases.items()
                if t == tenant_id and (pack_id is None or c.get("pack_id") == pack_id)
            ]
            rows.sort(key=lambda c: c["seq"], reverse=True)
            return [copy.deepcopy(c) for c in rows]


class PgCaseStore:
    """Durable index. Survives restarts, and is visible across processes."""

    def __init__(self, pool) -> None:
        self._pool = pool

    @staticmethod
    def _to_case(row: dict) -> dict:
        case = dict(row["payload"] or {})
        for column in _COLUMNS:
            case[column] = row[column]
        return case

    def upsert(self, tenant_id: str, case: dict) -> dict:
        # Read-modify-write so a partial upsert merges rather than replaces,
        # matching the in-memory store. `patch_fields` relies on this: it sends
        # only live_fields and must not wipe score or audit.
        existing = self.get(tenant_id, case["case_id"]) or {}
        merged = {**existing, **case}
        payload = {k: v for k, v in merged.items() if k not in _COLUMNS and k != "thread_id"}

        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO cases (tenant_id, case_id, pack_id, thread_id, status, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, case_id) DO UPDATE
                   SET pack_id    = EXCLUDED.pack_id,
                       status     = EXCLUDED.status,
                       payload    = EXCLUDED.payload,
                       updated_at = now()
                RETURNING *
                """,
                (
                    tenant_id,
                    merged["case_id"],
                    merged.get("pack_id", existing.get("pack_id", "")),
                    f"{tenant_id}:{merged['case_id']}",
                    merged.get("status", existing.get("status", "processing")),
                    json.dumps(payload, default=str),
                ),
            ).fetchone()
        return self._to_case(row)

    def get(self, tenant_id: str, case_id: str) -> dict | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM cases WHERE tenant_id = %s AND case_id = %s",
                (tenant_id, case_id),
            ).fetchone()
        return self._to_case(row) if row else None

    def list(self, tenant_id: str, pack_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM cases WHERE tenant_id = %s"
        args: list = [tenant_id]
        if pack_id is not None:
            sql += " AND pack_id = %s"
            args.append(pack_id)
        sql += " ORDER BY seq DESC"
        with self._pool.connection() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [self._to_case(r) for r in rows]
