# Task 5 review package - full contents of created/changed files

=== FILE: packs/kyc_uae/pack.yaml ===
pack_id: kyc-uae
display_name: UAE Fintech KYC Onboarding
gate_role: Compliance Officer
thresholds: {low: 0.30, high: 0.65}


=== FILE: packs/kyc_uae/prompt.md ===
You are a compliance onboarding assistant for a Dubai-based virtual-asset platform. Your job is to conduct a short, professional voice interview to collect the information required to open an account, then hand off to a human compliance officer for review.

Collect exactly six fields, one at a time, in this order: full legal name, date of birth, nationality, UAE residency status, source of funds, and the product the applicant wants to use (spot trading, derivatives, or custody). Ask a single clear question for each field and wait for the answer before moving on.

When the applicant states their full name, repeat it back and ask them to confirm or spell it, since accurate spelling matters for identity screening. Be equally careful with dates of birth â€” read the date back in full.

Stay warm, patient, and neutral. Never offer legal, tax, or investment advice, and never comment on whether the applicant will pass or fail screening â€” that decision belongs to the compliance team. If asked, explain only that the information is used for standard regulatory checks.

After the applicant answers each question, call `record_field` with the field name and their answer. Once all six fields have been recorded, call `complete_interview` and thank the applicant for their time, letting them know a compliance officer will follow up if anything further is needed.


=== FILE: packs/kyc_uae/schema.py ===
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
    "dob": "Could you give me your date of birth again â€” day, month and year?",
    "nationality": "Which country issued your passport?",
    "residency_status": "Are you a UAE resident, or applying from abroad?",
    "source_of_funds": "What is the main source of the funds you will use?",
    "product": "Which product are you applying for â€” spot trading, derivatives, or custody?",
}


=== FILE: packs/kyc_uae/checks.py ===
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


=== FILE: packs/kyc_uae/scoring.py ===
import sys
from voxgate.ml.scorecard import Feature, Scorecard

# The loader (voxgate.packs.loader) execs each pack file as a standalone module via
# importlib, not as a package, so `from .checks import COUNTRIES` fails (no parent
# package). It loads checks.py before scoring.py and registers it in sys.modules
# under this qualname, so we pull COUNTRIES from there instead.
COUNTRIES = sys.modules["voxgate_pack_kyc-uae_checks"].COUNTRIES

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


=== FILE: packs/kyc_uae/data/sanctions.json ===
{
  "synthetic": true,
  "entries": [
    {"id": "UN-001", "name": "Mohammed Al Rashid", "list": "UN Consolidated",
     "dob": "1975-03-02", "nationality": "SY", "aliases": ["Abu Khalid"]},
    {"id": "UAE-004", "name": "Khalid Bin Mahfouz", "list": "UAE Local Terrorist List",
     "dob": "1981-07-14", "nationality": "YE", "aliases": []},
    {"id": "UAE-009", "name": "Numan Aziz", "list": "UAE Local Terrorist List",
     "dob": "1988-02-20", "nationality": "YE", "aliases": ["Abu Numan"]},
    {"id": "OFAC-77", "name": "Dmitri Volkov", "list": "OFAC SDN",
     "dob": "1969-11-20", "nationality": "RU", "aliases": []},
    {"id": "OFAC-12", "name": "Wojciech Kowalski", "list": "OFAC SDN",
     "dob": "1965-09-01", "nationality": "RU", "aliases": []},
    {"id": "UN-002", "name": "Nnamdi Okeke", "list": "UN Consolidated",
     "dob": "1970-06-10", "nationality": "SO", "aliases": ["Chief Okeke"]},
    {"id": "UN-003", "name": "Jozef Nowak", "list": "UN Consolidated",
     "dob": "1978-12-05", "nationality": "PK", "aliases": []},
    {"id": "UN-005", "name": "Aliyu Bello", "list": "UN Consolidated",
     "dob": "1972-08-15", "nationality": "KP", "aliases": []},
    {"id": "OFAC-20", "name": "Magnus Fjeld", "list": "OFAC SDN",
     "dob": "1980-01-22", "nationality": "IR", "aliases": ["M. Fjeld"]}
  ]
}


=== FILE: packs/kyc_uae/data/peps.json ===
{
  "synthetic": true,
  "entries": [
    {"id": "PEP-001", "name": "Sipho Zulu", "list": "PEP",
     "dob": "1965-05-11", "nationality": "AE", "aliases": []},
    {"id": "PEP-002", "name": "Karim Osei", "list": "PEP",
     "dob": "1958-03-22", "nationality": "RU", "aliases": []},
    {"id": "PEP-003", "name": "Idris Junaid", "list": "PEP",
     "dob": "1972-09-30", "nationality": "SG", "aliases": []},
    {"id": "PEP-004", "name": "Zubair Hafeez", "list": "PEP",
     "dob": "1968-11-02", "nationality": "PK", "aliases": []},
    {"id": "PEP-005", "name": "Karam Nassif", "list": "PEP",
     "dob": "1975-07-19", "nationality": "RU", "aliases": []}
  ]
}


=== FILE: packs/kyc_uae/data/adverse_media.json ===
{
  "synthetic": true,
  "entries": [
    {"name": "Mohammed Al Rashid", "headline": "Businessman named in leaked offshore-finance records", "severity": 0.65},
    {"name": "Dmitri Volkov", "headline": "Executive linked to shell company fraud investigation", "severity": 0.55},
    {"name": "Anwar Siddiqui", "headline": "Trader fined by regulator for disclosure breach", "severity": 0.4}
  ]
}


=== FILE: packs/kyc_uae/data/countries.json ===
{
  "synthetic": true,
  "countries": {
    "AE": {"name": "United Arab Emirates", "fatf": "clean"},
    "IN": {"name": "India", "fatf": "clean"},
    "GB": {"name": "United Kingdom", "fatf": "clean"},
    "US": {"name": "United States", "fatf": "clean"},
    "SG": {"name": "Singapore", "fatf": "clean"},
    "DE": {"name": "Germany", "fatf": "clean"},
    "YE": {"name": "Yemen", "fatf": "grey"},
    "RU": {"name": "Russia", "fatf": "grey"},
    "PK": {"name": "Pakistan", "fatf": "grey"},
    "SO": {"name": "Somalia", "fatf": "grey"},
    "SY": {"name": "Syria", "fatf": "black"},
    "KP": {"name": "North Korea", "fatf": "black"},
    "IR": {"name": "Iran", "fatf": "black"}
  }
}


=== FILE: tests/pack_conformance.py ===
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


=== FILE: tests/test_pack_kyc_uae.py ===
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


=== FILE: pyproject.toml ===
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
voice = [
    "pipecat-ai[webrtc,deepgram,cartesia,openai,silero]>=0.0.60",
    "faster-whisper>=1.0",
]

[dependency-groups]
dev = ["pytest>=8.2", "httpx>=0.27", "websockets>=12.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/voxgate"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

