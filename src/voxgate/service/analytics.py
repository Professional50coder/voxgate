"""Per-agent performance, computed from case records and transcripts.

Plain Python over the case projection rather than SQL, so the in-memory and
Postgres deployments report identical numbers and the logic is testable without
a database. At the volumes a reviewer board handles this is a few thousand rows.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

DONE = {"approved", "rejected"}
WAITING_ON_APPLICANT = {"awaiting_interview"}


def _ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    v = sorted(values)
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


def compute(cases: list[dict], sessions: list[dict], names: dict[str, str]) -> dict:
    by_pack: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        by_pack[c.get("pack_id", "unknown")].append(c)
    sessions_by_case: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        sessions_by_case[s["case_id"]].append(s)

    agents = []
    for pack_id, rows in sorted(by_pack.items()):
        status = Counter(r.get("status", "unknown") for r in rows)
        bands = Counter((r.get("score") or {}).get("band") for r in rows if r.get("score"))
        interviewed = [r for r in rows if r.get("status") not in WAITING_ON_APPLICANT
                       or r.get("score")]
        auto = sum(1 for r in rows if (r.get("decision") or {}).get("by") == "system")
        decided = [r for r in rows if r.get("status") in DONE]
        reviewed = [r for r in decided if (r.get("decision") or {}).get("by") != "system"]

        # Which question people get stuck on: fields the graph had to re-ask.
        stuck = Counter()
        for r in rows:
            for f in ((r.get("interrupt") or {}).get("reask_fields") or []):
                stuck[f] += 1

        # Interview length and guardrail activity, from finished transcripts.
        durations, guard = [], Counter()
        for r in rows:
            for s in sessions_by_case.get(r["case_id"], []):
                summary = s.get("summary") or {}
                if summary.get("duration_ms"):
                    durations.append(summary["duration_ms"] / 1000)
                guard.update({k: v for k, v in (summary.get("guardrail") or {}).items() if v})

        agents.append({
            "pack_id": pack_id,
            "name": names.get(pack_id, pack_id),
            "cases": len(rows),
            "completed_interviews": len(interviewed),
            "completion_rate": round(len(interviewed) / len(rows), 3) if rows else 0,
            "status": dict(status),
            "risk_bands": {k: v for k, v in bands.items() if k},
            "auto_approved": auto,
            "human_reviewed": len(reviewed),
            "automation_rate": round(auto / len(decided), 3) if decided else None,
            "most_reasked": stuck.most_common(3),
            "median_interview_seconds": _median(durations),
            "guardrail": dict(guard),
        })

    return {
        "totals": {
            "cases": len(cases),
            "awaiting_review": sum(1 for c in cases if c.get("status") == "awaiting_review"),
            "decided": sum(1 for c in cases if c.get("status") in DONE),
            "transcripts": len(sessions),
        },
        "agents": agents,
    }


def public(cases: list[dict], agent_count: int) -> dict:
    """Counts only. No names, fields, scores or anything about an applicant."""
    screened = sum(1 for c in cases if c.get("score"))
    return {"interviews_started": len(cases), "cases_screened": screened,
            "agents_live": agent_count}
