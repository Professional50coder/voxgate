# VoxGate Core Platform Implementation Plan (Plan 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the scenario-generic durable-workflow backend — LangGraph case state machine with two human-input interrupts, the ML engines (name-matching ensemble, explainable scorecard), the scenario-pack system with the `kyc-uae` pack, and the FastAPI case API — demoable end-to-end with a CLI-simulated interview and zero paid API keys.

**Architecture:** One FastAPI service owns a per-pack compiled LangGraph (Postgres-checkpointed in production, in-memory in tests). The interview and the reviewer decision are both `interrupt()` pauses resumed through the API. Scenario packs are directories loaded at startup through fixed protocols; platform code never imports pack code by name. Voice (Plan 2) and frontend (Plan 3) later attach to this API without backend changes.

**Tech Stack:** Python 3.12 + uv · LangGraph ≥ 0.4 + langgraph-checkpoint-postgres · FastAPI + Uvicorn · Pydantic v2 · rapidfuzz · numpy · PyYAML · pytest + httpx · Postgres via docker-compose.

## Global Constraints

- **No git in this folder** (user request). Every task ends at green tests — skip any commit habit. Do NOT run `git init` or any `git` command.
- Dev machine is **Windows 11 / PowerShell** — all `Run:` commands are PowerShell-compatible; always invoke tools through `uv run …` from the repo root `C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate`.
- **Zero paid keys** in this plan: no LLM, STT, or TTS calls anywhere. The sync graph is used everywhere (`.invoke`/`.get_state`, never the async variants) so tests need no asyncio plumbing.
- All datasets are **mock/synthetic** and every dataset file carries `"synthetic": true` at its top level.
- Scorecard routing thresholds come from `pack.yaml` (`kyc-uae`: low `0.30`, high `0.65`); never hard-code them in platform code.
- Re-ask loop is capped at **2** (`MAX_REASKS = 2` in `graph/build.py`); after the cap, cases go to the reviewer gate.
- Status vocabulary (exact strings, used by store, API, and tests): `awaiting_interview`, `processing`, `awaiting_review`, `approved`, `rejected`, `needs_attention`.
- Embeddings are optional everywhere: `NameMatcher(embedder=None)` must work (weights renormalize) — sentence-transformers is an optional extra, never imported at module top level.

---

## File Structure

```
voxgate/
├─ pyproject.toml
├─ docker-compose.yml              # Postgres 16
├─ README.md                      # Task 9
├─ .env.example
├─ .paul/                         # PROJECT.md + STATE.md (Task 9)
├─ src/voxgate/
│  ├─ __init__.py
│  ├─ config.py                   # Settings (env + defaults)
│  ├─ ml/
│  │  ├─ __init__.py
│  │  ├─ variants.py              # Arabic transliteration variant table + expand_variants()
│  │  ├─ name_match.py            # NameMatcher, MatchCandidate
│  │  └─ scorecard.py             # Feature, Scorecard, ScoreResult, FeatureContribution
│  ├─ packs/
│  │  ├─ __init__.py
│  │  ├─ base.py                  # CheckResult, Pack, protocols
│  │  └─ loader.py                # load_pack(), load_packs()
│  ├─ graph/
│  │  ├─ __init__.py
│  │  ├─ state.py                 # CaseState TypedDict
│  │  └─ build.py                 # build_graph(pack, checkpointer)
│  └─ service/
│     ├─ __init__.py
│     ├─ store.py                 # CaseStore (in-memory index of cases)
│     ├─ events.py                # EventBus (threading-based, WS-pollable)
│     ├─ runner.py                # CaseRunner: start/resume cases, sync store+events
│     └─ app.py                   # create_app(settings) — all HTTP/WS routes
├─ packs/kyc_uae/
│  ├─ pack.yaml
│  ├─ prompt.md
│  ├─ schema.py                   # Schema (pydantic), REASK_HINTS
│  ├─ checks.py                   # CHECKS list (sanctions, pep, adverse_media)
│  ├─ scoring.py                  # build_scorecard(), FEATURE_FIELD_HINTS
│  └─ data/
│     ├─ sanctions.json           # UN + OFAC + UAE-local mock entries
│     ├─ peps.json
│     ├─ adverse_media.json
│     └─ countries.json           # ISO codes + FATF risk tier
├─ scripts/demo_case.py           # CLI end-to-end demo (Task 9)
└─ tests/
   ├─ conftest.py
   ├─ pack_conformance.py         # shared conformance suite (imported, not collected)
   ├─ test_config.py
   ├─ test_name_match.py
   ├─ test_scorecard.py
   ├─ test_pack_loader.py
   ├─ test_pack_kyc_uae.py
   ├─ test_graph.py
   ├─ test_api.py
   └─ integration/test_postgres_resume.py   # skipped unless VOXGATE_TEST_DB set
```

---

### Task 1: Project scaffold + Settings

**Files:**
- Create: `pyproject.toml`, `.env.example`, `docker-compose.yml`, `src/voxgate/__init__.py`, `src/voxgate/config.py`, `tests/test_config.py`, empty `__init__.py` in `src/voxgate/{ml,packs,graph,service}/`

**Interfaces:**
- Produces: `voxgate.config.Settings` with fields `database_url: str | None` (env `VOXGATE_DATABASE_URL`, default `None` → in-memory mode), `packs_dir: Path` (env `VOXGATE_PACKS_DIR`, default `<repo>/packs`); `get_settings() -> Settings`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "voxgate"
version = "0.1.0"
description = "Voice-driven durable workflow orchestrator (LangGraph + Pipecat)"
requires-python = ">=3.12"
dependencies = [
    "langgraph>=0.4",
    "langgraph-checkpoint-postgres>=2.0",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "pyyaml>=6.0",
    "rapidfuzz>=3.9",
    "numpy>=1.26",
    "psycopg[binary]>=3.1",
]

[project.optional-dependencies]
embeddings = ["sentence-transformers>=3.0"]

[dependency-groups]
dev = ["pytest>=8.2", "httpx>=0.27", "websockets>=12.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/voxgate"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `docker-compose.yml` and `.env.example`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: voxgate
      POSTGRES_PASSWORD: voxgate
      POSTGRES_DB: voxgate
    ports: ["5433:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
volumes:
  pgdata:
```

`.env.example`:

```
# Leave DATABASE_URL unset for in-memory dev mode (no persistence)
VOXGATE_DATABASE_URL=postgresql://voxgate:voxgate@localhost:5433/voxgate
```

- [ ] **Step 3: Write the failing test** — `tests/test_config.py`

```python
from pathlib import Path
from voxgate.config import Settings, get_settings

def test_defaults(monkeypatch):
    monkeypatch.delenv("VOXGATE_DATABASE_URL", raising=False)
    s = Settings()
    assert s.database_url is None
    assert s.packs_dir.name == "packs"

def test_env_override(monkeypatch):
    monkeypatch.setenv("VOXGATE_DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("VOXGATE_PACKS_DIR", str(Path("C:/tmp/pk")))
    s = Settings()
    assert s.database_url == "postgresql://x"
    assert s.packs_dir == Path("C:/tmp/pk")
```

- [ ] **Step 4: Run to verify failure**

Run: `uv sync; uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: voxgate.config`

- [ ] **Step 5: Implement `src/voxgate/config.py`**

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOXGATE_", env_file=".env", extra="ignore")
    database_url: str | None = None
    packs_dir: Path = REPO_ROOT / "packs"

def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 PASS

---

### Task 2: Transliteration variants + name-matching ensemble

**Files:**
- Create: `src/voxgate/ml/variants.py`, `src/voxgate/ml/name_match.py`, `tests/test_name_match.py`

**Interfaces:**
- Produces:
  - `variants.expand_variants(name: str) -> list[str]` — normalized romanization variants incl. the input.
  - `name_match.MatchCandidate` (pydantic): `entry_id: str`, `entry_name: str`, `list_name: str`, `jaro_winkler: float`, `token_set: float`, `embedding_sim: float | None`, `combined: float`, `band: str` (`"clear" | "review" | "strong"`).
  - `name_match.NameMatcher(entries: list[dict], embedder: Callable[[str], "np.ndarray"] | None = None)`; entries carry `id, name, list, dob, nationality, aliases`. Method: `match(name: str, dob: str | None = None, nationality: str | None = None, top_k: int = 5) -> list[MatchCandidate]` sorted by `combined` desc.
  - Bands: `combined >= 0.85` → `strong`; `>= 0.65` → `review`; else `clear`. Ensemble weights `0.35*jw + 0.25*token_set + 0.40*emb`; with `embedder=None` renormalize to `0.58*jw + 0.42*token_set`. DOB exact match boosts `combined` by `+0.07`, nationality match `+0.03` (cap 1.0).

- [ ] **Step 1: Write the failing tests** — `tests/test_name_match.py`

```python
from voxgate.ml.variants import expand_variants
from voxgate.ml.name_match import NameMatcher

ENTRIES = [
    {"id": "UN-001", "name": "Mohammed Al Rashid", "list": "UN Consolidated",
     "dob": "1975-03-02", "nationality": "SY", "aliases": ["Abu Khalid"]},
    {"id": "OFAC-77", "name": "Dmitri Volkov", "list": "OFAC SDN",
     "dob": "1969-11-20", "nationality": "RU", "aliases": []},
]

def test_variants_cover_common_romanizations():
    v = expand_variants("Muhammad Al-Rashid")
    joined = " | ".join(v)
    assert "mohammed al rashid" in joined

def test_transliteration_variant_matches_strongly():
    m = NameMatcher(ENTRIES)
    top = m.match("Muhammad Al-Rashid", dob="1975-03-02", nationality="SY")[0]
    assert top.entry_id == "UN-001"
    assert top.band == "strong"
    assert top.combined > 0.9

def test_different_name_is_clear():
    m = NameMatcher(ENTRIES)
    res = m.match("Priya Raghavan", dob="1990-01-01", nationality="IN")
    assert all(c.band == "clear" for c in res)

def test_alias_is_searched():
    m = NameMatcher(ENTRIES)
    top = m.match("Abu Khalid")[0]
    assert top.entry_id == "UN-001"
    assert top.band != "clear"

def test_embedder_changes_score_and_renormalization_works():
    import numpy as np
    def fake_embedder(text: str):
        vec = np.zeros(4); vec[hash(text) % 4] = 1.0; return vec
    with_emb = NameMatcher(ENTRIES, embedder=fake_embedder).match("Dmitri Volkov")[0]
    without = NameMatcher(ENTRIES).match("Dmitri Volkov")[0]
    assert with_emb.embedding_sim is not None
    assert without.embedding_sim is None
    assert without.band == "strong"   # exact name must still hit without embeddings
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_name_match.py -v`
Expected: FAIL — `ModuleNotFoundError: voxgate.ml.variants`

- [ ] **Step 3: Implement `src/voxgate/ml/variants.py`**

```python
import re

# canonical token -> known romanization variants (curated, extend freely)
_VARIANTS: dict[str, list[str]] = {
    "mohammed": ["muhammad", "mohamed", "mohammad", "mohd", "muhammed"],
    "abdul": ["abdel", "abd al", "abdal", "abdol"],
    "hussein": ["husain", "hussain", "husayn"],
    "rashid": ["rasheed", "rachid"],
    "said": ["saeed", "sayid", "sayyid"],
    "aisha": ["ayesha", "aysha"],
    "khalid": ["khaled", "haled"],
    "jamal": ["gamal", "djamel"],
}
_CANON = {v: k for k, vs in _VARIANTS.items() for v in vs}

def _norm(name: str) -> str:
    name = name.lower().replace("-", " ").replace("'", "")
    name = re.sub(r"\bal[\s-]?", "al ", name)
    return re.sub(r"\s+", " ", name).strip()

def expand_variants(name: str) -> list[str]:
    base = _norm(name)
    tokens = base.split()
    canon_tokens = [_CANON.get(t, t) for t in tokens]
    out = {base, " ".join(canon_tokens)}
    for i, tok in enumerate(canon_tokens):          # one substitution at a time
        for var in _VARIANTS.get(tok, []):
            out.add(" ".join(canon_tokens[:i] + [var] + canon_tokens[i + 1:]))
    return sorted(out)
```

- [ ] **Step 4: Implement `src/voxgate/ml/name_match.py`**

```python
from typing import Callable
import numpy as np
from pydantic import BaseModel
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from .variants import expand_variants, _norm

class MatchCandidate(BaseModel):
    entry_id: str
    entry_name: str
    list_name: str
    jaro_winkler: float
    token_set: float
    embedding_sim: float | None
    combined: float
    band: str

def _band(score: float) -> str:
    return "strong" if score >= 0.85 else "review" if score >= 0.65 else "clear"

class NameMatcher:
    def __init__(self, entries: list[dict], embedder: Callable | None = None):
        self.entries = entries
        self.embedder = embedder

    def _emb_sim(self, a: str, b: str) -> float | None:
        if self.embedder is None:
            return None
        va, vb = self.embedder(a), self.embedder(b)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
        return float(np.dot(va, vb) / denom)

    def match(self, name, dob=None, nationality=None, top_k=5) -> list[MatchCandidate]:
        queries = expand_variants(name)
        out = []
        for e in self.entries:
            targets = [e["name"], *e.get("aliases", [])]
            best = (0.0, 0.0, None)  # jw, ts, emb
            for q in queries:
                for t in targets:
                    tn = _norm(t)
                    jw = JaroWinkler.normalized_similarity(q, tn)
                    ts = fuzz.token_set_ratio(q, tn) / 100.0
                    emb = self._emb_sim(q, tn)
                    score = 0.35 * jw + 0.25 * ts + 0.40 * (emb or 0.0)
                    if score > 0.35 * best[0] + 0.25 * best[1] + 0.40 * (best[2] or 0.0):
                        best = (jw, ts, emb)
            jw, ts, emb = best
            combined = (0.35 * jw + 0.25 * ts + 0.40 * emb) if emb is not None \
                       else (0.58 * jw + 0.42 * ts)
            if dob and e.get("dob") == dob:
                combined = min(1.0, combined + 0.07)
            if nationality and e.get("nationality") == nationality:
                combined = min(1.0, combined + 0.03)
            out.append(MatchCandidate(
                entry_id=e["id"], entry_name=e["name"], list_name=e["list"],
                jaro_winkler=round(jw, 4), token_set=round(ts, 4),
                embedding_sim=None if emb is None else round(emb, 4),
                combined=round(combined, 4), band=_band(combined)))
        return sorted(out, key=lambda c: c.combined, reverse=True)[:top_k]
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_name_match.py -v`
Expected: 5 PASS. If `test_transliteration_variant_matches_strongly` fails on the 0.9 bound, the bug is in `_norm`'s `al-` handling — do not lower the assertion.

---

### Task 3: Explainable scorecard engine

**Files:**
- Create: `src/voxgate/ml/scorecard.py`, `tests/test_scorecard.py`

**Interfaces:**
- Produces (all pydantic except `Feature`/`Scorecard` which are plain classes):
  - `FeatureContribution`: `feature: str`, `value: float`, `weight: float`, `contribution: float` (= value·weight).
  - `ScoreResult`: `probability: float`, `band: str` (`"low"|"medium"|"high"`), `contributions: list[FeatureContribution]`, `bias: float`.
  - `Feature(name: str, weight: float, extractor: Callable[[dict], float])` — extractor maps case fields+check context → x ∈ [0, 1].
  - `Scorecard(features: list[Feature], bias: float, low_threshold: float, high_threshold: float)` with `score(data: dict) -> ScoreResult`; `probability = sigmoid(bias + Σ wᵢ·xᵢ)`; band: `p < low` → low, `p < high` → medium, else high.

- [ ] **Step 1: Write the failing tests** — `tests/test_scorecard.py`

```python
import math
from voxgate.ml.scorecard import Feature, Scorecard

def make_card():
    return Scorecard(
        features=[
            Feature("risk_a", 2.0, lambda d: d["a"]),
            Feature("risk_b", 1.0, lambda d: d["b"]),
        ],
        bias=-2.0, low_threshold=0.30, high_threshold=0.65)

def test_probability_matches_formula_and_is_deterministic():
    card = make_card()
    r1, r2 = card.score({"a": 0.5, "b": 1.0}), card.score({"a": 0.5, "b": 1.0})
    expected = 1 / (1 + math.exp(-(-2.0 + 2.0 * 0.5 + 1.0 * 1.0)))
    assert abs(r1.probability - expected) < 1e-9
    assert r1.probability == r2.probability

def test_contributions_are_attributable():
    r = make_card().score({"a": 0.5, "b": 1.0})
    by = {c.feature: c for c in r.contributions}
    assert by["risk_a"].contribution == 1.0 and by["risk_b"].contribution == 1.0
    assert r.bias == -2.0

def test_monotonic_increasing_risk_never_lowers_probability():
    card = make_card()
    p_low = card.score({"a": 0.0, "b": 0.2}).probability
    p_hi = card.score({"a": 1.0, "b": 0.2}).probability
    assert p_hi > p_low

def test_band_edges():
    card = make_card()
    assert card.score({"a": 0.0, "b": 0.0}).band == "low"      # p≈0.119
    assert card.score({"a": 0.5, "b": 1.0}).band == "medium"   # p=0.5
    assert card.score({"a": 1.0, "b": 1.0}).band == "high"     # p≈0.731
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scorecard.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/voxgate/ml/scorecard.py`**

```python
import math
from typing import Callable
from pydantic import BaseModel

class FeatureContribution(BaseModel):
    feature: str
    value: float
    weight: float
    contribution: float

class ScoreResult(BaseModel):
    probability: float
    band: str
    contributions: list[FeatureContribution]
    bias: float

class Feature:
    def __init__(self, name: str, weight: float, extractor: Callable[[dict], float]):
        self.name, self.weight, self.extractor = name, weight, extractor

class Scorecard:
    def __init__(self, features: list[Feature], bias: float,
                 low_threshold: float, high_threshold: float):
        self.features, self.bias = features, bias
        self.low_threshold, self.high_threshold = low_threshold, high_threshold

    def score(self, data: dict) -> ScoreResult:
        contribs = []
        total = self.bias
        for f in self.features:
            x = float(f.extractor(data))
            c = x * f.weight
            total += c
            contribs.append(FeatureContribution(
                feature=f.name, value=round(x, 4),
                weight=f.weight, contribution=round(c, 4)))
        p = 1.0 / (1.0 + math.exp(-total))
        band = "low" if p < self.low_threshold else \
               "medium" if p < self.high_threshold else "high"
        return ScoreResult(probability=round(p, 6), band=band,
                           contributions=contribs, bias=self.bias)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_scorecard.py -v`
Expected: 4 PASS

---

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

### Task 5: The `kyc-uae` pack + shared conformance suite

**Files:**
- Create: `packs/kyc_uae/pack.yaml`, `packs/kyc_uae/prompt.md`, `packs/kyc_uae/schema.py`, `packs/kyc_uae/checks.py`, `packs/kyc_uae/scoring.py`, `packs/kyc_uae/data/{sanctions.json,peps.json,adverse_media.json,countries.json}`, `tests/pack_conformance.py`, `tests/test_pack_kyc_uae.py`

**Interfaces:**
- Consumes: Task 2 (`NameMatcher`), Task 3 (`Feature`, `Scorecard`), Task 4 (pack module contract).
- Produces: the `kyc-uae` pack (fields: `full_name, dob, nationality, residency_status, source_of_funds, product`) and `tests/pack_conformance.py: run_conformance(pack: Pack) -> None` — raises `AssertionError` on any contract violation; every future pack's test file calls it.

- [ ] **Step 1: Write the mock datasets** (every file top-level `"synthetic": true`)

`packs/kyc_uae/data/sanctions.json` — ≥ 8 entries across the three lists; must include `UN-001 Mohammed Al Rashid` (dob `1975-03-02`, SY, alias `Abu Khalid`), one `OFAC SDN` entry, and ≥ 2 entries with `"list": "UAE Local Terrorist List"`:

```json
{
  "synthetic": true,
  "entries": [
    {"id": "UN-001", "name": "Mohammed Al Rashid", "list": "UN Consolidated",
     "dob": "1975-03-02", "nationality": "SY", "aliases": ["Abu Khalid"]},
    {"id": "UAE-004", "name": "Khalid Bin Mahfouz", "list": "UAE Local Terrorist List",
     "dob": "1981-07-14", "nationality": "YE", "aliases": []}
  ]
}
```

(Extend to ≥ 8 realistic-shaped synthetic entries in the same format.) `peps.json`: same entry shape, `"list": "PEP"` — ≥ 4 entries. `adverse_media.json`: `{"synthetic": true, "entries": [{"name": "...", "headline": "...", "severity": 0.6}]}` — ≥ 3 entries. `countries.json`: `{"synthetic": true, "countries": {"AE": {"name": "United Arab Emirates", "fatf": "clean"}, "IN": {"name": "India", "fatf": "clean"}, "SY": {"name": "Syria", "fatf": "black"}, "YE": {"name": "Yemen", "fatf": "grey"}, "RU": {"name": "Russia", "fatf": "grey"}, "GB": {"name": "United Kingdom", "fatf": "clean"}}}` (≥ 12 countries total, all three FATF tiers).

- [ ] **Step 2: Write `pack.yaml` and `prompt.md`**

```yaml
pack_id: kyc-uae
display_name: UAE Fintech KYC Onboarding
gate_role: Compliance Officer
thresholds: {low: 0.30, high: 0.65}
```

`prompt.md`: the interview system prompt (used by Plan 2's voice bot; content quality matters, ~200 words): agent persona ("compliance onboarding assistant for a Dubai-based virtual-asset platform"), collect exactly the six schema fields one at a time, confirm spellings of names, never give legal advice, call `record_field` after each answer and `complete_interview` when all fields are captured.

- [ ] **Step 3: Write `schema.py`**

```python
from datetime import date
from pydantic import BaseModel, field_validator

VALID_SOF = {"salary", "business_income", "investments", "inheritance", "crypto_trading", "other"}
VALID_PRODUCTS = {"spot_trading", "derivatives", "custody"}
VALID_RESIDENCY = {"uae_resident", "non_resident"}

class Schema(BaseModel):
    full_name: str
    dob: str                      # ISO date string
    nationality: str              # ISO alpha-2
    residency_status: str
    source_of_funds: str
    product: str

    @field_validator("dob")
    @classmethod
    def dob_plausible(cls, v):
        d = date.fromisoformat(v)
        age = (date.today() - d).days / 365.25
        if not 18 <= age <= 100:
            raise ValueError("age must be 18-100")
        return v

    @field_validator("full_name")
    @classmethod
    def name_plausible(cls, v):
        if len(v.split()) < 2:
            raise ValueError("need given and family name")
        return v

    @field_validator("residency_status")
    @classmethod
    def res_valid(cls, v):
        if v not in VALID_RESIDENCY: raise ValueError(f"one of {VALID_RESIDENCY}")
        return v

    @field_validator("source_of_funds")
    @classmethod
    def sof_valid(cls, v):
        if v not in VALID_SOF: raise ValueError(f"one of {VALID_SOF}")
        return v

    @field_validator("product")
    @classmethod
    def product_valid(cls, v):
        if v not in VALID_PRODUCTS: raise ValueError(f"one of {VALID_PRODUCTS}")
        return v

REASK_HINTS = {
    "full_name": "Could you spell your full name for me, please?",
    "dob": "Could you give me your date of birth again — day, month and year?",
    "nationality": "Which country issued your passport?",
    "residency_status": "Are you a UAE resident, or applying from abroad?",
    "source_of_funds": "What is the main source of the funds you will use?",
    "product": "Which product are you applying for — spot trading, derivatives, or custody?",
}
```

Note: `nationality` validity against `countries.json` is checked in `checks.py`-adjacent code, not the schema (schema stays data-file-free).

- [ ] **Step 4: Write `checks.py`** (module loads its own data; nationality check included here)

```python
import json
from pathlib import Path
from rapidfuzz import fuzz
from voxgate.ml.name_match import NameMatcher
from voxgate.packs.base import CheckResult

DATA = Path(__file__).parent / "data"
_sanctions = json.loads((DATA / "sanctions.json").read_text(encoding="utf-8"))["entries"]
_peps = json.loads((DATA / "peps.json").read_text(encoding="utf-8"))["entries"]
_media = json.loads((DATA / "adverse_media.json").read_text(encoding="utf-8"))["entries"]
COUNTRIES = json.loads((DATA / "countries.json").read_text(encoding="utf-8"))["countries"]

_STATUS = {"strong": "hit", "review": "review", "clear": "clear"}

def _screen(name, entries, check_name, fields):
    matcher = NameMatcher(entries)   # embedder wired in Plan 2+ via config; None is valid
    cands = matcher.match(name, dob=fields.get("dob"), nationality=fields.get("nationality"))
    top = cands[0] if cands else None
    return CheckResult(
        check_name=check_name,
        status=_STATUS[top.band] if top else "clear",
        score=top.combined if top else 0.0,
        details={"candidates": [c.model_dump() for c in cands]})

def sanctions_screen(fields: dict) -> CheckResult:
    return _screen(fields["full_name"], _sanctions, "sanctions", fields)

def pep_screen(fields: dict) -> CheckResult:
    return _screen(fields["full_name"], _peps, "pep", fields)

def adverse_media(fields: dict) -> CheckResult:
    hits = [m for m in _media
            if fuzz.token_set_ratio(fields["full_name"].lower(), m["name"].lower()) > 85]
    worst = max((m["severity"] for m in hits), default=0.0)
    return CheckResult(check_name="adverse_media",
                       status="review" if worst >= 0.5 else "clear",
                       score=worst, details={"articles": hits})

CHECKS = [sanctions_screen, pep_screen, adverse_media]
```

- [ ] **Step 5: Write `scoring.py`** — extractors read `{"fields": {...}, "checks": [CheckResult-dicts]}`

```python
from voxgate.ml.scorecard import Feature, Scorecard
from .checks import COUNTRIES   # loader registers modules in sys.modules; use
                                # voxgate_pack_kyc-uae_checks import if relative fails
_FATF_X = {"clean": 0.0, "grey": 0.5, "black": 1.0}
_SOF_X = {"salary": 0.1, "business_income": 0.3, "investments": 0.3,
          "inheritance": 0.4, "crypto_trading": 0.7, "other": 0.9}
_PRODUCT_X = {"spot_trading": 0.3, "custody": 0.2, "derivatives": 0.7}

def _check_score(data, name):
    return max((c["score"] for c in data["checks"] if c["check_name"] == name), default=0.0)

def build_scorecard(low, high):
    return Scorecard(
        features=[
            Feature("fatf_nationality_risk", 2.2,
                    lambda d: _FATF_X.get(COUNTRIES.get(d["fields"]["nationality"], {}).get("fatf", "grey"), 0.5)),
            Feature("pep_similarity", 1.8, lambda d: _check_score(d, "pep")),
            Feature("sanctions_similarity", 3.0, lambda d: _check_score(d, "sanctions")),
            Feature("adverse_media", 1.0, lambda d: _check_score(d, "adverse_media")),
            Feature("source_of_funds_risk", 1.5, lambda d: _SOF_X[d["fields"]["source_of_funds"]]),
            Feature("product_risk", 0.8, lambda d: _PRODUCT_X[d["fields"]["product"]]),
            Feature("non_resident", 0.6,
                    lambda d: 1.0 if d["fields"]["residency_status"] == "non_resident" else 0.0),
        ],
        bias=-3.5, low_threshold=low, high_threshold=high)

FEATURE_FIELD_HINTS = {
    "fatf_nationality_risk": "nationality", "pep_similarity": "full_name",
    "sanctions_similarity": "full_name", "adverse_media": "full_name",
    "source_of_funds_risk": "source_of_funds", "product_risk": "product",
    "non_resident": "residency_status",
}
```

**Import caveat for the implementer:** `from .checks import COUNTRIES` fails because the loader imports pack files as standalone modules, not a package. Use `import sys; COUNTRIES = sys.modules["voxgate_pack_kyc-uae_checks"].COUNTRIES` — and note the loader loads `checks.py` **before** `scoring.py` (adjust `load_pack` ordering if you changed it). Alternatively re-read `countries.json` directly in `scoring.py`; either is acceptable, pick one and leave a one-line comment.

- [ ] **Step 6: Write the shared conformance suite** — `tests/pack_conformance.py`

```python
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
```

- [ ] **Step 7: Write the failing pack tests** — `tests/test_pack_kyc_uae.py`

```python
import pytest
from voxgate.config import get_settings
from voxgate.packs.loader import load_pack
from tests.pack_conformance import run_conformance

CLEAN = {"full_name": "Priya Raghavan", "dob": "1992-04-15", "nationality": "IN",
         "residency_status": "uae_resident", "source_of_funds": "salary",
         "product": "spot_trading"}
RISKY = {"full_name": "Muhammad Al-Rashid", "dob": "1975-03-02", "nationality": "SY",
         "residency_status": "non_resident", "source_of_funds": "crypto_trading",
         "product": "derivatives"}

@pytest.fixture(scope="module")
def pack():
    return load_pack(get_settings().packs_dir / "kyc_uae")

def test_conformance(pack):
    run_conformance(pack, CLEAN)

def test_clean_applicant_scores_low(pack):
    checks = [c(CLEAN).model_dump() for c in pack.checks]
    assert all(c["status"] == "clear" for c in checks)
    assert pack.scorecard.score({"fields": CLEAN, "checks": checks}).band == "low"

def test_sanctioned_lookalike_hits_and_scores_high(pack):
    checks = [c(RISKY).model_dump() for c in pack.checks]
    sanc = next(c for c in checks if c["check_name"] == "sanctions")
    assert sanc["status"] == "hit"
    assert sanc["details"]["candidates"][0]["entry_id"] == "UN-001"
    assert pack.scorecard.score({"fields": RISKY, "checks": checks}).band == "high"

def test_schema_rejects_implausible(pack):
    for bad in [{**CLEAN, "dob": "2020-01-01"}, {**CLEAN, "full_name": "Cher"},
                {**CLEAN, "source_of_funds": "magic"}]:
        with pytest.raises(Exception):
            pack.schema_model(**bad)
```

- [ ] **Step 8: Run — iterate on data/weights until green**

Run: `uv run pytest tests/test_pack_kyc_uae.py -v`
Expected: 4 PASS. If the RISKY case doesn't reach `high`, the fix is dataset/weights (e.g. confirm the DOB/nationality boosts apply), never loosening the test.

---

### Task 6: LangGraph case state machine

**Files:**
- Create: `src/voxgate/graph/state.py`, `src/voxgate/graph/build.py`, `tests/test_graph.py`

**Interfaces:**
- Consumes: `Pack` (Task 4), pack behavior (Task 5).
- Produces:
  - `state.CaseState(TypedDict, total=False)`: `case_id: str`, `pack_id: str`, `status: str`, `fields: dict`, `field_confidence: dict`, `reask_count: int`, `reask_fields: list[str]`, `force_review: bool`, `check_results: Annotated[list[dict], operator.add]`, `score: dict | None`, `decision: dict | None`.
  - `build.MAX_REASKS = 2`.
  - `build.build_graph(pack: Pack, checkpointer) -> CompiledStateGraph`. Interrupt payloads: interview → `{"type": "interview", "reask_fields": [...], "reask_hints": {...}, "fields_so_far": {...}}`, resumed with `{"fields": {...}, "confidence": {...}}`; reviewer gate → `{"type": "review", "gate_role": ..., "score": {...}, "check_results": [...], "fields": {...}}`, resumed with `{"action": "approve"|"reject"|"request_info", "note": str}`.
  - Node names (dashboard shows these): `intake`, `interview`, `extract_validate`, `check_<check_name>` per pack check, `score`, `route`, `auto_approve`, `reviewer_gate`, `finalize`.

- [ ] **Step 1: Write the failing tests** — `tests/test_graph.py` (uses the real kyc-uae pack; `CLEAN`/`RISKY` dicts exactly as in Task 5 Step 7 — import them: `from tests.test_pack_kyc_uae import CLEAN, RISKY`)

```python
import uuid
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from voxgate.config import get_settings
from voxgate.packs.loader import load_pack
from voxgate.graph.build import build_graph, MAX_REASKS
from tests.test_pack_kyc_uae import CLEAN, RISKY

@pytest.fixture()
def pack():
    return load_pack(get_settings().packs_dir / "kyc_uae")

def start(graph, pack):
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke({"case_id": cfg["configurable"]["thread_id"],
                  "pack_id": pack.pack_id, "reask_count": 0}, cfg)
    return cfg

def interrupt_payload(graph, cfg):
    return graph.get_state(cfg).tasks[0].interrupts[0].value

def test_pauses_at_interview_then_clean_case_auto_approves(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    assert interrupt_payload(graph, cfg)["type"] == "interview"
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    s = graph.get_state(cfg).values
    assert s["status"] == "approved"
    assert s["decision"]["by"] == "system"
    assert s["score"]["band"] == "low"

def test_risky_case_parks_at_reviewer_gate_and_approve_resumes(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    payload = interrupt_payload(graph, cfg)
    assert payload["type"] == "review" and payload["gate_role"] == "Compliance Officer"
    assert graph.get_state(cfg).values["status"] == "awaiting_review"
    graph.invoke(Command(resume={"action": "reject", "note": "sanctions hit"}), cfg)
    s = graph.get_state(cfg).values
    assert s["status"] == "rejected" and s["decision"]["note"] == "sanctions hit"

def test_invalid_fields_trigger_reask_with_hints(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": {**CLEAN, "dob": "2020-01-01"}, "confidence": {}}), cfg)
    payload = interrupt_payload(graph, cfg)
    assert payload["type"] == "interview"
    assert "dob" in payload["reask_fields"]
    assert payload["reask_hints"]["dob"]
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    assert graph.get_state(cfg).values["status"] == "approved"

def test_reask_cap_forces_reviewer_gate(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    bad = {"fields": {**CLEAN, "dob": "2020-01-01"}, "confidence": {}}
    graph.invoke(Command(resume=bad), cfg)
    for _ in range(MAX_REASKS):
        assert interrupt_payload(graph, cfg)["type"] == "interview"
        graph.invoke(Command(resume=bad), cfg)
    assert interrupt_payload(graph, cfg)["type"] == "review"   # cap exhausted → gate

def test_request_info_from_gate_loops_back_to_interview(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    graph.invoke(Command(resume={"action": "request_info", "note": "verify SoF"}), cfg)
    assert interrupt_payload(graph, cfg)["type"] == "interview"

def test_resume_after_restart_same_checkpointer(pack):
    saver = MemorySaver()
    graph = build_graph(pack, saver)
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": RISKY, "confidence": {}}), cfg)
    graph2 = build_graph(pack, saver)          # "restarted process"
    assert graph2.get_state(cfg).values["status"] == "awaiting_review"
    graph2.invoke(Command(resume={"action": "approve", "note": "ok"}), cfg)
    assert graph2.get_state(cfg).values["status"] == "approved"

def test_latest_check_results_win_after_reask(pack):
    graph = build_graph(pack, MemorySaver())
    cfg = start(graph, pack)
    graph.invoke(Command(resume={"fields": {**CLEAN, "dob": "2020-01-01"}, "confidence": {}}), cfg)
    graph.invoke(Command(resume={"fields": CLEAN, "confidence": {}}), cfg)
    s = graph.get_state(cfg).values
    per_check = [c["check_name"] for c in s["check_results"]]
    assert s["score"]["band"] == "low"          # scored on deduped latest results
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: voxgate.graph.build`

- [ ] **Step 3: Implement `src/voxgate/graph/state.py`**

```python
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
```

- [ ] **Step 4: Implement `src/voxgate/graph/build.py`**

```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from pydantic import ValidationError
from voxgate.packs.base import Pack
from .state import CaseState

MAX_REASKS = 2

def _latest_checks(results: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for r in results:                      # append-order: later wins
        latest[r["check_name"]] = r
    return list(latest.values())

def build_graph(pack: Pack, checkpointer):
    g = StateGraph(CaseState)

    def intake(state):
        return {"status": "awaiting_interview", "fields": {}, "reask_count": state.get("reask_count", 0)}

    def interview(state):
        payload = interrupt({
            "type": "interview",
            "reask_fields": state.get("reask_fields", []),
            "reask_hints": {f: pack.reask_hints[f] for f in state.get("reask_fields", []) if f in pack.reask_hints},
            "fields_so_far": state.get("fields", {}),
        })
        return {"fields": {**state.get("fields", {}), **payload["fields"]},
                "field_confidence": payload.get("confidence", {}),
                "status": "processing", "reask_fields": []}

    def extract_validate(state):
        try:
            clean = pack.schema_model(**state["fields"]).model_dump()
            return {"fields": clean}
        except ValidationError as e:
            bad = sorted({err["loc"][0] for err in e.errors() if err["loc"]})
            return {"reask_fields": list(bad), "reask_count": state["reask_count"] + 1}

    def after_validate(state):
        if state.get("reask_fields"):
            if state["reask_count"] > MAX_REASKS:
                return "force_gate"
            return "interview"
        return [f"check_{c.__name__}" for c in pack.checks]   # parallel fan-out

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
        top = max((c for c in state["score"]["contributions"]), key=lambda c: c["contribution"])
        field = pack.feature_field_hints.get(top["feature"], "full_name")
        return {"reask_fields": [field], "reask_count": state["reask_count"] + 1}

    def auto_approve(state):
        return {"decision": {"action": "approve", "by": "system", "note": "low risk"},
                "status": "approved"}

    def reviewer_gate(state):
        state_checks = _latest_checks(state.get("check_results", []))
        decision = interrupt({
            "type": "review", "gate_role": pack.gate_role, "score": state["score"],
            "check_results": state_checks, "fields": state["fields"]})
        if decision["action"] == "request_info":
            return {"reask_fields": ["source_of_funds"], "reask_count": 0,
                    "force_review": False, "decision": None, "status": "processing"}
        return {"decision": {**decision, "by": pack.gate_role},
                "status": "approved" if decision["action"] == "approve" else "rejected"}

    def after_gate(state):
        return "interview" if state.get("reask_fields") else "finalize"

    def set_awaiting_review(state):
        return {"status": "awaiting_review"}

    def finalize(state):
        return {}

    g.add_node("intake", intake)
    g.add_node("interview", interview)
    g.add_node("extract_validate", extract_validate)
    for c in pack.checks:
        g.add_node(f"check_{c.__name__}", make_check_node(c))
    g.add_node("force_gate", force_gate)
    g.add_node("score", score)
    g.add_node("medium_reask", medium_reask)
    g.add_node("auto_approve", auto_approve)
    g.add_node("awaiting_review", set_awaiting_review)
    g.add_node("reviewer_gate", reviewer_gate)
    g.add_node("finalize", finalize)

    g.add_edge(START, "intake")
    g.add_edge("intake", "interview")
    g.add_edge("interview", "extract_validate")
    g.add_conditional_edges("extract_validate", after_validate,
        ["interview", "force_gate"] + [f"check_{c.__name__}" for c in pack.checks])
    for c in pack.checks:
        g.add_edge(f"check_{c.__name__}", "score")
    g.add_edge("force_gate", "awaiting_review")
    g.add_conditional_edges("score", route, ["awaiting_review", "medium_reask", "auto_approve"])
    g.add_edge("medium_reask", "interview")
    g.add_edge("awaiting_review", "reviewer_gate")
    g.add_conditional_edges("reviewer_gate", after_gate, ["interview", "finalize"])
    g.add_edge("auto_approve", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
```

**Implementer notes (read before coding):**
- `route` returns node names directly: `"awaiting_review"` (status-setter node that then flows into the `reviewer_gate` interrupt node), `"medium_reask"`, or `"auto_approve"`.
- `score` returning `"check_results": []` is a no-op under the add-reducer; dedup happens in `_latest_checks` (last write wins). The `test_latest_check_results_win_after_reask` test guards this.
- Status `awaiting_interview` is visible when parked at the interview interrupt because `interview`'s state update hasn't run yet; `awaiting_review` is set by the dedicated node *before* the gate interrupt — that ordering is what the store/API tests rely on.

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_graph.py -v`
Expected: 7 PASS

---

### Task 7: CaseStore + EventBus + CaseRunner

**Files:**
- Create: `src/voxgate/service/store.py`, `src/voxgate/service/events.py`, `src/voxgate/service/runner.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: Task 6 graph, Task 4 loader.
- Produces:
  - `store.CaseStore` (in-memory, thread-safe): `upsert(case: dict)`, `get(case_id) -> dict | None`, `list(pack_id: str | None = None) -> list[dict]` (newest first by `created_at` seq). Case dict keys: `case_id, pack_id, status, fields, live_fields, score, check_results, decision, interrupt, seq`.
  - `events.EventBus`: `publish(case_id, event: dict)`, `history(case_id) -> list[dict]`, `wait(case_id, after_index: int, timeout: float) -> list[dict]` (blocking; returns new events or `[]` on timeout). Thread-safe via `threading.Condition`.
  - `runner.CaseRunner(packs: dict[str, Pack], checkpointer_factory: Callable[[], Any], store: CaseStore, bus: EventBus)`:
    - `start_case(pack_id) -> dict` — new uuid case, invoke to first interrupt, sync store, publish `{"kind": "state"}` event, return store dict.
    - `resume(case_id, payload) -> dict` — `Command(resume=payload)`, sync, publish, return store dict. Raises `KeyError` on unknown case.
    - `patch_fields(case_id, fields: dict, confidence: dict) -> dict` — merges into `live_fields` only (graph untouched), publishes `{"kind": "fields"}` event.
    - `_sync(case_id)` — reads `graph.get_state`, maps to the store case dict; `interrupt` key holds the pending interrupt payload or `None`.
  - Graphs are built once per pack at runner init (`self.graphs: dict[str, CompiledStateGraph]`), all sharing one checkpointer from `checkpointer_factory()`.

- [ ] **Step 1: Write the failing tests** — `tests/test_runner.py`

```python
import pytest
from langgraph.checkpoint.memory import MemorySaver
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.service.store import CaseStore
from voxgate.service.events import EventBus
from voxgate.service.runner import CaseRunner
from tests.test_pack_kyc_uae import CLEAN, RISKY

@pytest.fixture()
def runner():
    packs = load_packs(get_settings().packs_dir)
    return CaseRunner(packs, MemorySaver, CaseStore(), EventBus())

def test_full_lifecycle_clean(runner):
    case = runner.start_case("kyc-uae")
    assert case["status"] == "awaiting_interview"
    assert case["interrupt"]["type"] == "interview"
    done = runner.resume(case["case_id"], {"fields": CLEAN, "confidence": {}})
    assert done["status"] == "approved" and done["interrupt"] is None
    assert done["score"]["band"] == "low"

def test_gate_lifecycle_and_events(runner):
    case = runner.start_case("kyc-uae")
    runner.resume(case["case_id"], {"fields": RISKY, "confidence": {}})
    parked = runner.store.get(case["case_id"])
    assert parked["status"] == "awaiting_review"
    assert parked["interrupt"]["type"] == "review"
    runner.resume(case["case_id"], {"action": "approve", "note": "cleared by officer"})
    assert runner.store.get(case["case_id"])["status"] == "approved"
    kinds = [e["kind"] for e in runner.bus.history(case["case_id"])]
    assert kinds.count("state") >= 3

def test_patch_fields_is_live_only(runner):
    case = runner.start_case("kyc-uae")
    runner.patch_fields(case["case_id"], {"full_name": "Pri"}, {"full_name": 0.4})
    c = runner.store.get(case["case_id"])
    assert c["live_fields"] == {"full_name": "Pri"}
    assert c["status"] == "awaiting_interview"          # graph untouched
    assert runner.bus.history(case["case_id"])[-1]["kind"] == "fields"

def test_list_and_unknown_case(runner):
    a = runner.start_case("kyc-uae"); b = runner.start_case("kyc-uae")
    ids = [c["case_id"] for c in runner.store.list()]
    assert ids[0] == b["case_id"]                        # newest first
    with pytest.raises(KeyError):
        runner.resume("nope", {})

def test_eventbus_wait_returns_new_events(runner):
    case = runner.start_case("kyc-uae")
    n = len(runner.bus.history(case["case_id"]))
    import threading
    got = []
    t = threading.Thread(target=lambda: got.extend(
        runner.bus.wait(case["case_id"], after_index=n, timeout=5.0)))
    t.start()
    runner.patch_fields(case["case_id"], {"dob": "1992-04-15"}, {})
    t.join(timeout=6)
    assert got and got[-1]["kind"] == "fields"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: voxgate.service.store`

- [ ] **Step 3: Implement `store.py`, `events.py`, `runner.py`**

`src/voxgate/service/store.py`:

```python
import threading

class CaseStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._cases: dict[str, dict] = {}
        self._seq = 0

    def upsert(self, case: dict):
        with self._lock:
            existing = self._cases.get(case["case_id"])
            if existing:
                case = {**existing, **case}
            else:
                self._seq += 1
                case = {**case, "seq": self._seq}
            self._cases[case["case_id"]] = case

    def get(self, case_id):
        with self._lock:
            return self._cases.get(case_id)

    def list(self, pack_id=None):
        with self._lock:
            cases = [c for c in self._cases.values()
                     if pack_id is None or c["pack_id"] == pack_id]
        return sorted(cases, key=lambda c: c["seq"], reverse=True)
```

`src/voxgate/service/events.py`:

```python
import threading

class EventBus:
    def __init__(self):
        self._cond = threading.Condition()
        self._events: dict[str, list[dict]] = {}

    def publish(self, case_id, event):
        with self._cond:
            self._events.setdefault(case_id, []).append(event)
            self._cond.notify_all()

    def history(self, case_id):
        with self._cond:
            return list(self._events.get(case_id, []))

    def wait(self, case_id, after_index, timeout):
        with self._cond:
            self._cond.wait_for(
                lambda: len(self._events.get(case_id, [])) > after_index, timeout=timeout)
            return list(self._events.get(case_id, [])[after_index:])
```

`src/voxgate/service/runner.py`:

```python
import uuid
from langgraph.types import Command

class CaseRunner:
    def __init__(self, packs, checkpointer_factory, store, bus):
        self.packs, self.store, self.bus = packs, store, bus
        checkpointer = checkpointer_factory()
        from voxgate.graph.build import build_graph
        self.graphs = {pid: build_graph(p, checkpointer) for pid, p in packs.items()}

    def _cfg(self, case_id):
        return {"configurable": {"thread_id": case_id}}

    def _sync(self, case_id, pack_id):
        graph = self.graphs[pack_id]
        snap = graph.get_state(self._cfg(case_id))
        v = snap.values
        pending = None
        for task in snap.tasks:
            if task.interrupts:
                pending = task.interrupts[0].value
        case = {"case_id": case_id, "pack_id": pack_id,
                "status": v.get("status", "processing"),
                "fields": v.get("fields", {}),
                "score": v.get("score"), "decision": v.get("decision"),
                "check_results": v.get("check_results", []),
                "interrupt": pending}
        self.store.upsert(case)
        self.bus.publish(case_id, {"kind": "state", "case": self.store.get(case_id)})
        return self.store.get(case_id)

    def start_case(self, pack_id):
        case_id = str(uuid.uuid4())
        self.store.upsert({"case_id": case_id, "pack_id": pack_id,
                           "status": "awaiting_interview", "live_fields": {}})
        self.graphs[pack_id].invoke(
            {"case_id": case_id, "pack_id": pack_id, "reask_count": 0}, self._cfg(case_id))
        return self._sync(case_id, pack_id)

    def _pack_of(self, case_id):
        case = self.store.get(case_id)
        if case is None:
            raise KeyError(case_id)
        return case["pack_id"]

    def resume(self, case_id, payload):
        pack_id = self._pack_of(case_id)
        self.graphs[pack_id].invoke(Command(resume=payload), self._cfg(case_id))
        return self._sync(case_id, pack_id)

    def patch_fields(self, case_id, fields, confidence):
        pack_id = self._pack_of(case_id)
        case = self.store.get(case_id)
        live = {**case.get("live_fields", {}), **fields}
        self.store.upsert({"case_id": case_id, "pack_id": pack_id, "live_fields": live})
        self.bus.publish(case_id, {"kind": "fields", "fields": live, "confidence": confidence})
        return self.store.get(case_id)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_runner.py -v`
Expected: 5 PASS

- [ ] **Step 5: Add needs_attention coverage** — append to `tests/test_runner.py`, then make it pass

```python
def test_node_crash_marks_needs_attention(runner, monkeypatch):
    case = runner.start_case("kyc-uae")
    pack = runner.packs["kyc-uae"]
    monkeypatch.setitem(
        runner.graphs, "kyc-uae",
        _crashing_graph_for(pack))   # helper: pack with one check raising RuntimeError
    out = runner.resume(case["case_id"], {"fields": CLEAN, "confidence": {}})
    assert out["status"] == "needs_attention"
    assert "error" in out
```

Helper `_crashing_graph_for` (in the test file): copy the pack via `dataclasses.replace(pack, checks=[_boom])` where `_boom` raises `RuntimeError("provider down")`, build with `MemorySaver()`. Implementation change in `runner.resume`/`start_case`: wrap `.invoke` in `try/except Exception as e`, on failure `self.store.upsert({"case_id": ..., "pack_id": ..., "status": "needs_attention", "error": str(e)})`, publish a state event, and return the store dict (do not re-raise). Retry-with-backoff on LLM nodes arrives in Plan 2 where LLM nodes exist; the graph has no flaky-by-design nodes in Plan 1.

Run: `uv run pytest tests/test_runner.py -v`
Expected: 6 PASS

---

### Task 8: FastAPI app — REST + WebSocket

**Files:**
- Create: `src/voxgate/service/app.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: Task 7 (`CaseRunner`, `CaseStore`, `EventBus`), Task 1 (`Settings`).
- Produces: `create_app(settings: Settings | None = None, runner: CaseRunner | None = None) -> FastAPI` (runner injection is what tests use) plus module-level `app = create_app()` for `uvicorn voxgate.service.app:app`. Routes:
  - `GET /packs` → `[{pack_id, display_name, gate_role, fields: [...]}]`
  - `POST /cases` body `{"pack_id": str}` → 201, case dict; 404 unknown pack
  - `GET /cases?pack_id=` → list; `GET /cases/{id}` → case dict or 404
  - `PATCH /cases/{id}/fields` body `{"fields": {...}, "confidence": {...}}` → case dict
  - `POST /cases/{id}/interview-result` body `{"fields": {...}, "confidence": {...}}` → case dict (resumes interview interrupt); 409 if case isn't awaiting an interview
  - `POST /cases/{id}/decision` body `{"action": "approve"|"reject"|"request_info", "note": str}` → case dict; 409 if not `awaiting_review`
  - `WS /cases/{id}/events` → server pushes each event as JSON; sends full history on connect.

- [ ] **Step 1: Write the failing tests** — `tests/test_api.py`

```python
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.service.app import create_app
from voxgate.service.runner import CaseRunner
from voxgate.service.store import CaseStore
from voxgate.service.events import EventBus
from tests.test_pack_kyc_uae import CLEAN, RISKY

@pytest.fixture()
def client():
    runner = CaseRunner(load_packs(get_settings().packs_dir),
                        MemorySaver, CaseStore(), EventBus())
    return TestClient(create_app(runner=runner))

def test_packs_listing(client):
    packs = client.get("/packs").json()
    assert packs[0]["pack_id"] == "kyc-uae"
    assert "full_name" in packs[0]["fields"]

def test_case_lifecycle_over_http(client):
    case = client.post("/cases", json={"pack_id": "kyc-uae"}).json()
    cid = case["case_id"]
    assert case["status"] == "awaiting_interview"
    client.patch(f"/cases/{cid}/fields", json={"fields": {"full_name": "Pri"}, "confidence": {}})
    done = client.post(f"/cases/{cid}/interview-result",
                       json={"fields": CLEAN, "confidence": {}}).json()
    assert done["status"] == "approved"
    assert client.get(f"/cases/{cid}").json()["score"]["band"] == "low"

def test_decision_flow_and_conflicts(client):
    cid = client.post("/cases", json={"pack_id": "kyc-uae"}).json()["case_id"]
    # decision before review is a 409
    assert client.post(f"/cases/{cid}/decision",
                       json={"action": "approve", "note": ""}).status_code == 409
    client.post(f"/cases/{cid}/interview-result", json={"fields": RISKY, "confidence": {}})
    assert client.get(f"/cases/{cid}").json()["status"] == "awaiting_review"
    # second interview-result while awaiting review is a 409
    assert client.post(f"/cases/{cid}/interview-result",
                       json={"fields": RISKY, "confidence": {}}).status_code == 409
    r = client.post(f"/cases/{cid}/decision", json={"action": "reject", "note": "hit"})
    assert r.json()["status"] == "rejected"

def test_unknown_pack_and_case_404(client):
    assert client.post("/cases", json={"pack_id": "nope"}).status_code == 404
    assert client.get("/cases/nope").status_code == 404

def test_ws_streams_history_then_live(client):
    cid = client.post("/cases", json={"pack_id": "kyc-uae"}).json()["case_id"]
    with client.websocket_connect(f"/cases/{cid}/events") as ws:
        first = ws.receive_json()
        assert first["kind"] == "state"
        client.patch(f"/cases/{cid}/fields", json={"fields": {"dob": "1992-04-15"}, "confidence": {}})
        live = ws.receive_json()
        while live["kind"] != "fields":
            live = ws.receive_json()
        assert live["fields"]["dob"] == "1992-04-15"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: voxgate.service.app`

- [ ] **Step 3: Implement `src/voxgate/service/app.py`**

```python
import asyncio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from langgraph.checkpoint.memory import MemorySaver
from voxgate.config import Settings, get_settings
from voxgate.packs.loader import load_packs
from .runner import CaseRunner
from .store import CaseStore
from .events import EventBus

class CreateCase(BaseModel):
    pack_id: str

class FieldsPayload(BaseModel):
    fields: dict
    confidence: dict = {}

class DecisionPayload(BaseModel):
    action: str
    note: str = ""

def _postgres_factory(dsn: str):
    from langgraph.checkpoint.postgres import PostgresSaver
    import psycopg
    conn = psycopg.connect(dsn, autocommit=True)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver

def create_app(settings: Settings | None = None, runner: CaseRunner | None = None) -> FastAPI:
    settings = settings or get_settings()
    if runner is None:
        factory = (lambda: _postgres_factory(settings.database_url)) \
                  if settings.database_url else MemorySaver
        runner = CaseRunner(load_packs(settings.packs_dir), factory, CaseStore(), EventBus())
    app = FastAPI(title="VoxGate")

    def _case_or_404(case_id):
        case = runner.store.get(case_id)
        if case is None:
            raise HTTPException(404, "case not found")
        return case

    @app.get("/packs")
    def packs():
        return [{"pack_id": p.pack_id, "display_name": p.display_name,
                 "gate_role": p.gate_role,
                 "fields": list(p.schema_model.model_fields)}
                for p in runner.packs.values()]

    @app.post("/cases", status_code=201)
    def create_case(body: CreateCase):
        if body.pack_id not in runner.packs:
            raise HTTPException(404, "unknown pack")
        return runner.start_case(body.pack_id)

    @app.get("/cases")
    def list_cases(pack_id: str | None = None):
        return runner.store.list(pack_id)

    @app.get("/cases/{case_id}")
    def get_case(case_id: str):
        return _case_or_404(case_id)

    @app.patch("/cases/{case_id}/fields")
    def patch_fields(case_id: str, body: FieldsPayload):
        _case_or_404(case_id)
        return runner.patch_fields(case_id, body.fields, body.confidence)

    @app.post("/cases/{case_id}/interview-result")
    def interview_result(case_id: str, body: FieldsPayload):
        case = _case_or_404(case_id)
        if not case.get("interrupt") or case["interrupt"]["type"] != "interview":
            raise HTTPException(409, "case is not awaiting an interview")
        return runner.resume(case_id, {"fields": body.fields, "confidence": body.confidence})

    @app.post("/cases/{case_id}/decision")
    def decision(case_id: str, body: DecisionPayload):
        case = _case_or_404(case_id)
        if not case.get("interrupt") or case["interrupt"]["type"] != "review":
            raise HTTPException(409, "case is not awaiting review")
        return runner.resume(case_id, {"action": body.action, "note": body.note})

    @app.websocket("/cases/{case_id}/events")
    async def events(ws: WebSocket, case_id: str):
        await ws.accept()
        cursor = 0
        try:
            while True:
                batch = await asyncio.to_thread(runner.bus.wait, case_id, cursor, 1.0)
                for event in batch:
                    await ws.send_json(event)
                cursor += len(batch)
        except WebSocketDisconnect:
            pass

    return app

app = create_app()
```

**Implementer note:** module-level `app = create_app()` loads real packs at import — if that's annoying for tests importing the module, guard it with a lazy factory or move it to a `__main__`/uvicorn entry; the tests only require `create_app(runner=...)`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: 5 PASS

- [ ] **Step 5: Full suite regression**

Run: `uv run pytest -v`
Expected: all tests from Tasks 1–8 PASS

---

### Task 9: Postgres durability integration test + demo script + docs

**Files:**
- Create: `tests/integration/test_postgres_resume.py`, `scripts/demo_case.py`, `README.md`, `.paul/PROJECT.md`, `.paul/STATE.md`

**Interfaces:**
- Consumes: everything.
- Produces: the "kill the server, come back, approve the case" proof, a runnable demo, and project docs.

- [ ] **Step 1: Write the integration test** — `tests/integration/test_postgres_resume.py` (skipped unless `VOXGATE_TEST_DB` is set; run `docker compose up -d` first and set `VOXGATE_TEST_DB=postgresql://voxgate:voxgate@localhost:5433/voxgate`)

```python
import os
import pytest
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.service.app import _postgres_factory
from voxgate.service.runner import CaseRunner
from voxgate.service.store import CaseStore
from voxgate.service.events import EventBus
from tests.test_pack_kyc_uae import RISKY

DSN = os.environ.get("VOXGATE_TEST_DB")
pytestmark = pytest.mark.skipif(not DSN, reason="VOXGATE_TEST_DB not set")

def _fresh_runner():
    return CaseRunner(load_packs(get_settings().packs_dir),
                      lambda: _postgres_factory(DSN), CaseStore(), EventBus())

def test_case_survives_process_restart():
    r1 = _fresh_runner()
    case = r1.start_case("kyc-uae")
    r1.resume(case["case_id"], {"fields": RISKY, "confidence": {}})
    assert r1.store.get(case["case_id"])["status"] == "awaiting_review"

    r2 = _fresh_runner()                    # brand-new runner = restarted process
    # store is empty in r2 (in-memory index) — recover from the checkpointer:
    recovered = r2.recover_case(case["case_id"], "kyc-uae")
    assert recovered["status"] == "awaiting_review"
    assert recovered["interrupt"]["type"] == "review"
    done = r2.resume(case["case_id"], {"action": "approve", "note": "post-restart"})
    assert done["status"] == "approved"
```

- [ ] **Step 2: Implement `CaseRunner.recover_case`** in `src/voxgate/service/runner.py`

```python
    def recover_case(self, case_id, pack_id):
        """Rehydrate the store entry for a case that exists only in the checkpointer."""
        self.store.upsert({"case_id": case_id, "pack_id": pack_id, "live_fields": {}})
        return self._sync(case_id, pack_id)
```

Also add a `list_known_threads` note: full store rebuild on boot is a Plan 3 concern (the dashboard needs it); for now `recover_case` is the explicit per-case recovery path and the integration test its consumer.

- [ ] **Step 3: Run the integration test**

Run: `docker compose up -d; $env:VOXGATE_TEST_DB="postgresql://voxgate:voxgate@localhost:5433/voxgate"; uv run pytest tests/integration -v`
Expected: 1 PASS (and SKIP when the env var is absent: `uv run pytest tests/integration -v` in a fresh shell)

- [ ] **Step 4: Write `scripts/demo_case.py`** — CLI demo against a running server (`uv run uvicorn voxgate.service.app:app`). Uses httpx; no arguments = clean applicant, `--risky` = sanctions-lookalike applicant. It must: create a case, print the interview interrupt payload, submit the scripted fields as the "interview", pretty-print check results + the score waterfall (feature name, value, weight, contribution, one `#`-bar per 0.1 contribution), and if the case parks at review, prompt `approve/reject/request_info` on stdin and submit the decision. ~80 lines; print every status transition with the case id so a screen recording of this is the Plan-1 demo artifact.

- [ ] **Step 5: Manual end-to-end check**

Run (terminal 1): `uv run uvicorn voxgate.service.app:app --port 8000`
Run (terminal 2): `uv run python scripts/demo_case.py --risky`
Expected: case parks at `awaiting_review` with a printed score waterfall showing `sanctions_similarity` dominating; typing `approve` finishes the case. Then restart terminal 1 mid-review (with `VOXGATE_DATABASE_URL` set) and confirm the decision still lands after restart.

- [ ] **Step 6: Write `README.md`, `.paul/PROJECT.md`, `.paul/STATE.md`**

`README.md`: what VoxGate is (3 sentences), quickstart (uv sync → docker compose up → uvicorn → demo script), test matrix (`uv run pytest` / integration env var), pack-authoring guide (the module contract from Task 4, ~15 lines), and the 4-plan roadmap. `.paul/PROJECT.md`: goal, architecture summary, spec + plan links. `.paul/STATE.md`: Plan 1 complete, Plans 2–4 pending, date 2026-08-06.

- [ ] **Step 7: Final full regression**

Run: `uv run pytest -v`
Expected: all green (integration tests skip without the env var — that's fine)

---

## Self-Review Notes (already applied)

- **Spec coverage:** §2 pack interface → Tasks 4–5; §3.1 graph+API → Tasks 6–8; §4.1 name ensemble → Task 2; §4.2 scorecard → Task 3; §6 error handling → Task 6 (re-ask cap), Task 7 Step 5 (needs_attention), Task 9 (restart durability); §9 conformance suite → Task 5. Deliberately deferred per the plan split: voice/bot + LLM retry policies + telemetry (Plan 2), frontend/WS visualizations (Plan 3), loan-intake + claim-fnol packs (Plan 4), embeddings wiring into checks (config flag, Plan 2+).
- **Known simplifications, stated:** `CaseStore` is an in-memory index over the durable checkpointer (rebuild-on-boot deferred to Plan 3; `recover_case` covers the durability proof). `request_info` from the gate re-asks `source_of_funds` (fixed choice) — pack-configurable later. Adverse-media check is fuzzy-only by design.
- **Type consistency check:** `CheckResult.model_dump()` dicts flow: check node → `check_results` → `_latest_checks` → scorecard `data["checks"]` and gate payload `check_results` — field names (`check_name`, `status`, `score`, `details`) used consistently in Tasks 5, 6, 7 tests.
