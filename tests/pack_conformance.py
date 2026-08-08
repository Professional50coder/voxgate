"""Shared pack conformance suite. Every pack's test file imports and calls
run_conformance(pack). Not collected directly by pytest (no test_ prefix)."""
from pydantic import BaseModel
from voxgate.packs.base import CheckResult, Pack

def run_conformance(pack: Pack, valid_fields: dict) -> None:
    # pack.yaml essentials
    assert pack.pack_id and pack.display_name and pack.gate_role
    assert 0 < pack.low_threshold < pack.high_threshold < 1
    # schema round-trip + reask hints cover every field
    assert issubclass(pack.schema_model, BaseModel)
    parsed = pack.schema_model(**valid_fields)
    assert set(pack.reask_hints) == set(parsed.model_dump())
    # checks conform
    for check in pack.checks:
        r = check(valid_fields)
        assert isinstance(r, CheckResult) and r.status in {"clear", "review", "hit"}
        assert 0.0 <= r.score <= 1.0
    # scorecard conforms and attributes fully
    checks = [check(valid_fields).model_dump() for check in pack.checks]
    result = pack.scorecard.score({"fields": valid_fields, "checks": checks})
    assert 0.0 <= result.probability <= 1.0
    assert result.band in {"low", "medium", "high"}
    assert len(result.contributions) >= 3
    # every scorecard feature maps to a re-askable field
    feats = {c.feature for c in result.contributions}
    assert feats == set(pack.feature_field_hints)
    assert set(pack.feature_field_hints.values()) <= set(parsed.model_dump())
    # prompt is real
    assert len(pack.prompt) > 100
