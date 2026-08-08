import operator
from typing import Annotated, TypedDict

class CaseState(TypedDict, total=False):
    case_id: str
    pack_id: str
    status: str
    fields: dict
    field_confidence: dict
    reask_count: int
    reask_fields: list[str]
    force_review: bool
    check_results: Annotated[list[dict], operator.add]
    score: dict | None
    decision: dict | None
    # Wave 1 additions (additive-only; see docs/design/2026-08-06-graph-upgrade-design.md)
    audit: Annotated[list[dict], operator.add]
    field_errors: dict[str, str]
