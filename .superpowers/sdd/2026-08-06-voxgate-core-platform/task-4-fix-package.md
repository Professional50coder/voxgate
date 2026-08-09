# Task 4 FIX review package — current files after fix round 1

=== FILE: src/voxgate/packs/loader.py ===
import importlib.util
import sys
from pathlib import Path
import yaml
from .base import Pack

class PackLoadError(Exception):
    """Exception raised when a pack fails to load, wrapping the underlying error with pack context."""
    pass

def _load_module(path: Path, qualname: str):
    spec = importlib.util.spec_from_file_location(qualname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod          # so pack modules can import each other
    spec.loader.exec_module(mod)
    return mod

def load_pack(path: Path) -> Pack:
    try:
        meta = yaml.safe_load((path / "pack.yaml").read_text(encoding="utf-8"))
        pid = meta["pack_id"]
        schema = _load_module(path / "schema.py", f"voxgate_pack_{pid}_schema")
        checks = _load_module(path / "checks.py", f"voxgate_pack_{pid}_checks")
        scoring = _load_module(path / "scoring.py", f"voxgate_pack_{pid}_scoring")
        low, high = meta["thresholds"]["low"], meta["thresholds"]["high"]
        return Pack(
            pack_id=pid, display_name=meta["display_name"], gate_role=meta["gate_role"],
            low_threshold=low, high_threshold=high,
            schema_model=schema.Schema, reask_hints=schema.REASK_HINTS,
            prompt=(path / "prompt.md").read_text(encoding="utf-8"),
            checks=checks.CHECKS, scorecard=scoring.build_scorecard(low, high),
            feature_field_hints=scoring.FEATURE_FIELD_HINTS, path=path)
    except Exception as e:
        raise PackLoadError(f"Failed to load pack from {path}: {e}") from e

def load_packs(packs_dir: Path) -> dict[str, Pack]:
    out: dict[str, Pack] = {}
    pack_paths: dict[str, Path] = {}  # track pack_id -> directory for collision detection
    for child in sorted(packs_dir.iterdir()):
        if child.is_dir() and (child / "pack.yaml").exists():
            pack = load_pack(child)
            if pack.pack_id in out:
                raise ValueError(
                    f"Duplicate pack_id '{pack.pack_id}' found in {pack_paths[pack.pack_id]} and {child}"
                )
            out[pack.pack_id] = pack
            pack_paths[pack.pack_id] = child
    return out

=== FILE: tests/test_pack_loader.py ===
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
