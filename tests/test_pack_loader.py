import textwrap
from pathlib import Path
import pytest
from voxgate.packs.loader import load_pack, load_packs, PackLoadError

def make_min_pack(root: Path, pack_id="toy") -> Path:
    d = root / pack_id
    d.mkdir(parents=True)
    (d / "pack.yaml").write_text(textwrap.dedent(f"""
        pack_id: {pack_id}
        display_name: Toy Pack
        gate_role: Reviewer
        thresholds: {{low: 0.30, high: 0.65}}
    """), encoding="utf-8")
    (d / "prompt.md").write_text("You interview people.", encoding="utf-8")
    (d / "schema.py").write_text(textwrap.dedent("""
        from pydantic import BaseModel
        class Schema(BaseModel):
            full_name: str
            amount: float
        REASK_HINTS = {"full_name": "Please spell your full name."}
    """), encoding="utf-8")
    (d / "checks.py").write_text(textwrap.dedent("""
        from voxgate.packs.base import CheckResult
        def always_clear(fields):
            return CheckResult(check_name="noop", status="clear", score=0.0, details={})
        CHECKS = [always_clear]
    """), encoding="utf-8")
    (d / "scoring.py").write_text(textwrap.dedent("""
        from voxgate.ml.scorecard import Feature, Scorecard
        def build_scorecard(low, high):
            return Scorecard([Feature("amount_risk", 2.0,
                lambda d: min(d["fields"]["amount"] / 100000, 1.0))], -2.0, low, high)
        FEATURE_FIELD_HINTS = {"amount_risk": "amount"}
    """), encoding="utf-8")
    return d

def test_load_pack_wires_everything(tmp_path):
    pack = load_pack(make_min_pack(tmp_path))
    assert pack.pack_id == "toy" and pack.gate_role == "Reviewer"
    assert pack.low_threshold == 0.30 and pack.high_threshold == 0.65
    assert pack.schema_model(full_name="A B", amount=5.0).amount == 5.0
    assert pack.checks[0]({"x": 1}).status == "clear"
    r = pack.scorecard.score({"fields": {"amount": 200000}, "checks": []})
    assert r.band in {"low", "medium", "high"} and r.contributions
    assert pack.feature_field_hints["amount_risk"] == "amount"
    assert pack.prompt.startswith("You interview")

def test_load_packs_skips_junk(tmp_path):
    make_min_pack(tmp_path, "toy")
    (tmp_path / "not_a_pack").mkdir()
    (tmp_path / "readme.txt").write_text("hi", encoding="utf-8")
    packs = load_packs(tmp_path)
    assert list(packs) == ["toy"]

def test_load_packs_detects_duplicate_pack_id(tmp_path):
    """Two pack directories with the same pack_id should raise ValueError."""
    make_min_pack(tmp_path, "pack1")
    # Create a second pack with the same pack_id
    d2 = tmp_path / "pack2"
    d2.mkdir(parents=True)
    (d2 / "pack.yaml").write_text(textwrap.dedent("""
        pack_id: pack1
        display_name: Duplicate Pack
        gate_role: Reviewer
        thresholds: {low: 0.30, high: 0.65}
    """), encoding="utf-8")
    (d2 / "prompt.md").write_text("Duplicate pack.", encoding="utf-8")
    (d2 / "schema.py").write_text(textwrap.dedent("""
        from pydantic import BaseModel
        class Schema(BaseModel):
            name: str
        REASK_HINTS = {}
    """), encoding="utf-8")
    (d2 / "checks.py").write_text(textwrap.dedent("""
        from voxgate.packs.base import CheckResult
        CHECKS = []
    """), encoding="utf-8")
    (d2 / "scoring.py").write_text(textwrap.dedent("""
        from voxgate.ml.scorecard import Scorecard
        def build_scorecard(low, high):
            return Scorecard([], 0.0, low, high)
        FEATURE_FIELD_HINTS = {}
    """), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        load_packs(tmp_path)
    assert "Duplicate pack_id 'pack1'" in str(excinfo.value)
    assert "pack1" in str(excinfo.value) and "pack2" in str(excinfo.value)

def test_load_pack_missing_thresholds_raises_pack_load_error(tmp_path):
    """Missing 'thresholds' key in pack.yaml should raise PackLoadError with pack context."""
    d = tmp_path / "broken"
    d.mkdir(parents=True)
    (d / "pack.yaml").write_text(textwrap.dedent("""
        pack_id: broken
        display_name: Broken Pack
        gate_role: Reviewer
    """), encoding="utf-8")
    (d / "prompt.md").write_text("Prompt", encoding="utf-8")
    (d / "schema.py").write_text("class Schema: pass\nREASK_HINTS = {}", encoding="utf-8")
    (d / "checks.py").write_text("CHECKS = []", encoding="utf-8")
    (d / "scoring.py").write_text("def build_scorecard(low, high): pass\nFEATURE_FIELD_HINTS = {}", encoding="utf-8")

    with pytest.raises(PackLoadError) as excinfo:
        load_pack(d)
    assert str(d) in str(excinfo.value)
    assert excinfo.value.__cause__ is not None

def test_load_pack_missing_scoring_py_raises_pack_load_error(tmp_path):
    """Missing 'scoring.py' file should raise PackLoadError with pack context."""
    d = tmp_path / "missing_scoring"
    d.mkdir(parents=True)
    (d / "pack.yaml").write_text(textwrap.dedent("""
        pack_id: missing_scoring
        display_name: Missing Scoring
        gate_role: Reviewer
        thresholds: {low: 0.30, high: 0.65}
    """), encoding="utf-8")
    (d / "prompt.md").write_text("Prompt", encoding="utf-8")
    (d / "schema.py").write_text("from pydantic import BaseModel\nclass Schema(BaseModel): pass\nREASK_HINTS = {}", encoding="utf-8")
    (d / "checks.py").write_text("CHECKS = []", encoding="utf-8")
    # Intentionally not creating scoring.py

    with pytest.raises(PackLoadError) as excinfo:
        load_pack(d)
    assert str(d) in str(excinfo.value)
    assert excinfo.value.__cause__ is not None

def test_one_broken_pack_does_not_stop_the_others_loading(tmp_path, caplog):
    """Regression: a single unloadable pack used to make the process refuse to
    boot.

    `load_packs` raised, `create_app` raised, and the service stayed down until
    someone deleted the directory by hand — an outage that survived restarts and
    that any failed publish could cause. A broken pack is now skipped loudly.
    """
    make_min_pack(tmp_path, "good")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "pack.yaml").write_text("pack_id: broken\n", encoding="utf-8")

    packs = load_packs(tmp_path)

    assert list(packs) == ["good"], "the healthy pack must still serve"
    assert any("broken" in r.getMessage() for r in caplog.records), (
        "skipping must be logged, not silent"
    )


def test_strict_still_raises_on_a_broken_pack(tmp_path):
    """The CLI generator and conformance runs want the failure, not the skip."""
    make_min_pack(tmp_path, "good")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "pack.yaml").write_text("pack_id: broken\n", encoding="utf-8")

    with pytest.raises(PackLoadError):
        load_packs(tmp_path, strict=True)


def test_in_flight_publish_staging_dirs_are_invisible(tmp_path):
    """publish_pack stages into a sibling `.staging-*` directory before renaming
    into place. A concurrent load must never see that half-written pack."""
    make_min_pack(tmp_path, "good")
    make_min_pack(tmp_path, ".staging-abc123")
    make_min_pack(tmp_path, "good.replacing")

    assert list(load_packs(tmp_path)) == ["good"]
