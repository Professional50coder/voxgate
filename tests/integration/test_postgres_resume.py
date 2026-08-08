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
