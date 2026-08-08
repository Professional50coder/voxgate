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
