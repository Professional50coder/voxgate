### Task 4: Pack protocols + loader

**Files:**
- Create: `src/voxgate/packs/base.py`, `src/voxgate/packs/loader.py`, `tests/test_pack_loader.py`

**Interfaces:**
- Consumes: `Scorecard` from Task 3.
- Produces:
  - `base.CheckResult` (pydantic): `check_name: str`, `status: str` (`"clear"|"review"|"hit"`), `score: float`, `details: dict`.
  - `base.Pack` (dataclass): `pack_id: str`, `display_name: str`, `gate_role: str`, `low_threshold: float`, `high_threshold: float`, `schema_model: type[BaseModel]`, `reask_hints: dict[str, str]`, `prompt: str`, `checks: list[Callable[[dict], CheckResult]]`, `scorecard: Scorecard`, `feature_field_hints: dict[str, str]`, `path: Path`.
  - `loader.load_pack(path: Path) -> Pack`; `loader.load_packs(dir: Path) -> dict[str, Pack]` (skips non-dirs and dirs without `pack.yaml`).
  - **Pack module contract** (what each pack dir must expose): `schema.py` → `Schema` (pydantic BaseModel) and `REASK_HINTS: dict[str, str]`; `checks.py` → `CHECKS: list[Callable[[dict], CheckResult]]`; `scoring.py` → `build_scorecard(low: float, high: float) -> Scorecard` and `FEATURE_FIELD_HINTS: dict[str, str]` (feature name → field to re-ask).

- [ ] **Step 1: Write the failing tests** — `tests/test_pack_loader.py` (builds a minimal throwaway pack in `tmp_path`)

```python
import textwrap
from pathlib import Path
from voxgate.packs.loader import load_pack, load_packs

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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pack_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: voxgate.packs.loader`

- [ ] **Step 3: Implement `src/voxgate/packs/base.py`**

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from pydantic import BaseModel
from voxgate.ml.scorecard import Scorecard

class CheckResult(BaseModel):
    check_name: str
    status: str            # "clear" | "review" | "hit"
    score: float
    details: dict

@dataclass
class Pack:
    pack_id: str
    display_name: str
    gate_role: str
    low_threshold: float
    high_threshold: float
    schema_model: type[BaseModel]
    reask_hints: dict[str, str]
    prompt: str
    checks: list[Callable[[dict], CheckResult]]
    scorecard: Scorecard
    feature_field_hints: dict[str, str]
    path: Path
```

- [ ] **Step 4: Implement `src/voxgate/packs/loader.py`**

```python
import importlib.util
import sys
from pathlib import Path
import yaml
from .base import Pack

def _load_module(path: Path, qualname: str):
    spec = importlib.util.spec_from_file_location(qualname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod          # so pack modules can import each other
    spec.loader.exec_module(mod)
    return mod

def load_pack(path: Path) -> Pack:
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

def load_packs(packs_dir: Path) -> dict[str, Pack]:
    out: dict[str, Pack] = {}
    for child in sorted(packs_dir.iterdir()):
        if child.is_dir() and (child / "pack.yaml").exists():
            pack = load_pack(child)
            out[pack.pack_id] = pack
    return out
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_pack_loader.py -v`
Expected: 2 PASS

---

