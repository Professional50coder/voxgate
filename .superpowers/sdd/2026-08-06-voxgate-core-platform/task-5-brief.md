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

