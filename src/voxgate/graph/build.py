import time
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, RetryPolicy
from pydantic import ValidationError
from voxgate.packs.base import Pack
from .state import CaseState

MAX_REASKS = 2

def _node_name(check) -> str:
    return f"check_{getattr(check, 'check_name', check.__name__)}"

def _latest_checks(results: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for r in results:                      # append-order: later wins
        latest[r["check_name"]] = r
    return list(latest.values())

def _summarize(name, state, result):
    # Deterministic, state-derived summary — no wall-clock, no randomness.
    bits = [name]
    if result.get("reask_fields"):
        bits.append(f"reask={result['reask_fields']}")
    if result.get("decision") is not None:
        bits.append(f"decision={result['decision'].get('action')}")
    status_after = result.get("status", state.get("status"))
    if status_after != state.get("status"):
        bits.append(f"status={state.get('status')}->{status_after}")
    return " ".join(bits)

def _audited(name, fn, clock=None):
    """Wrap a node function so every invocation appends one audit entry.

    seq is a pure function of the audit list already present in the state the
    node was invoked with (design doc §a) — deterministic, no wall clock.
    duration_ms uses a monotonic clock only for the *difference* of two calls,
    never as an identity/ordering key, so it introduces no non-determinism
    that any test could reasonably assert an exact value of.
    """
    def wrapper(state):
        t0 = time.perf_counter()
        result = fn(state) or {}
        entry = {
            "seq": len(state.get("audit", [])) + 1,
            "node": name,
            "status_before": state.get("status"),
            "status_after": result.get("status", state.get("status")),
            "summary": _summarize(name, state, result),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
        if clock is not None:
            entry["ts"] = clock()
        return {**result, "audit": [entry]}
    return wrapper

def build_graph(pack: Pack, checkpointer, clock=None):
    g = StateGraph(CaseState)

    def intake(state):
        return {"status": "awaiting_interview", "fields": {}, "reask_count": state.get("reask_count", 0)}

    def interview(state):
        reask_fields = state.get("reask_fields", [])
        schema_fields = list(pack.schema_model.model_fields)
        payload = interrupt({
            "type": "interview",
            "reask_fields": reask_fields,
            "reask_hints": {f: pack.reask_hints[f] for f in reask_fields if f in pack.reask_hints},
            "fields_so_far": state.get("fields", {}),
            # additive (proposal c): explain *why* + progress/attempt visibility
            "field_errors": {f: state.get("field_errors", {}).get(f) for f in reask_fields},
            "attempt": state.get("reask_count", 0),
            "max_attempts": MAX_REASKS,
            "fields_validated": [f for f in schema_fields
                                  if f not in reask_fields and f in state.get("fields", {})],
        })
        return {"fields": {**state.get("fields", {}), **payload["fields"]},
                "field_confidence": payload.get("confidence", {}),
                "status": "processing", "reask_fields": []}

    def extract_validate(state):
        try:
            clean = pack.schema_model(**state["fields"]).model_dump()
            return {"fields": clean}
        except ValidationError as e:
            errs = {err["loc"][0]: err["msg"] for err in e.errors() if err["loc"]}
            # Back to the applicant. If the re-ask cap is exhausted the router
            # sends it to the reviewer gate instead, which sets its own status.
            return {"reask_fields": sorted(errs), "reask_count": state["reask_count"] + 1,
                    "field_errors": errs, "status": "awaiting_interview"}

    def after_validate(state):
        if state.get("reask_fields"):
            if state["reask_count"] > MAX_REASKS:
                return "force_gate"
            return "interview"
        return [_node_name(c) for c in pack.checks]   # parallel fan-out

    def force_gate(state):
        return {"force_review": True, "score": {"probability": None, "band": "high",
                "contributions": [], "bias": None}, "check_results": []}

    def make_check_node(check):
        def node(state):
            return {"check_results": [check(state["fields"]).model_dump()]}
        return node

    def score(state):
        checks = _latest_checks(state.get("check_results", []))
        result = pack.scorecard.score({"fields": state["fields"], "checks": checks})
        return {"score": result.model_dump(), "check_results": []}  # add-reducer: no-op append

    def route(state):
        checks = _latest_checks(state.get("check_results", []))
        band = state["score"]["band"]
        any_hit = any(c["status"] == "hit" for c in checks)
        if state.get("force_review") or any_hit or band == "high":
            return "awaiting_review"
        if band == "medium":
            if state["reask_count"] >= MAX_REASKS:
                return "awaiting_review"
            return "medium_reask"
        return "auto_approve"

    def medium_reask(state):
        contributions = state["score"].get("contributions") or []
        top = max(contributions, key=lambda c: c["contribution"], default=None)
        field = pack.feature_field_hints.get(top["feature"], "full_name") \
            if top is not None else "full_name"
        # Back to the interview, so say so: left at "processing", a case
        # waiting on the applicant looked like one still being screened.
        return {"reask_fields": [field], "reask_count": state["reask_count"] + 1,
                "status": "awaiting_interview"}

    def auto_approve(state):
        return {"decision": {"action": "approve", "by": "system", "note": "low risk"},
                "status": "approved"}

    def reviewer_gate(state):
        state_checks = _latest_checks(state.get("check_results", []))
        contributions = state["score"].get("contributions", [])
        waterfall = sorted(contributions, key=lambda c: abs(c["contribution"]), reverse=True)
        flagged = [c for c in state_checks if c["status"] != "clear"]
        decision = interrupt({
            "type": "review", "gate_role": pack.gate_role, "score": state["score"],
            "check_results": state_checks, "fields": state["fields"],
            # additive (proposal c): pre-assembled waterfall/flags + why-here signals
            "score_waterfall": waterfall,
            "flagged_checks": flagged,
            "reask_count": state.get("reask_count", 0),
            "force_review": state.get("force_review", False),
        })
        if decision["action"] == "request_info":
            return {"reask_fields": ["source_of_funds"], "reask_count": 0,
                    "force_review": False, "decision": None, "status": "awaiting_interview"}
        # `by` stays the role (what the pack requires); `reviewer` is the named
        # person whose key made the call, when keys are named.
        return {"decision": {**decision, "by": pack.gate_role},
                "status": "approved" if decision["action"] == "approve" else "rejected"}

    def after_gate(state):
        return "interview" if state.get("reask_fields") else "finalize"

    def set_awaiting_review(state):
        return {"status": "awaiting_review"}

    def finalize(state):
        return {}

    g.add_node("intake", _audited("intake", intake, clock))
    g.add_node("interview", _audited("interview", interview, clock))
    g.add_node("extract_validate", _audited("extract_validate", extract_validate, clock))
    for c in pack.checks:
        name = _node_name(c)
        g.add_node(name, _audited(name, make_check_node(c), clock),
                   retry_policy=RetryPolicy(max_attempts=2))
    g.add_node("force_gate", _audited("force_gate", force_gate, clock))
    g.add_node("score", _audited("score", score, clock))
    g.add_node("medium_reask", _audited("medium_reask", medium_reask, clock))
    g.add_node("auto_approve", _audited("auto_approve", auto_approve, clock))
    g.add_node("awaiting_review", _audited("awaiting_review", set_awaiting_review, clock))
    g.add_node("reviewer_gate", _audited("reviewer_gate", reviewer_gate, clock))
    g.add_node("finalize", _audited("finalize", finalize, clock))

    g.add_edge(START, "intake")
    g.add_edge("intake", "interview")
    g.add_edge("interview", "extract_validate")
    g.add_conditional_edges("extract_validate", after_validate,
        ["interview", "force_gate"] + [_node_name(c) for c in pack.checks])
    for c in pack.checks:
        g.add_edge(_node_name(c), "score")
    g.add_edge("force_gate", "awaiting_review")
    g.add_conditional_edges("score", route, ["awaiting_review", "medium_reask", "auto_approve"])
    g.add_edge("medium_reask", "interview")
    g.add_edge("awaiting_review", "reviewer_gate")
    g.add_conditional_edges("reviewer_gate", after_gate, ["interview", "finalize"])
    g.add_edge("auto_approve", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
