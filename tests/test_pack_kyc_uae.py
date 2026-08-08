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
