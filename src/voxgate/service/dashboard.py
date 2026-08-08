"""VoxGate reviewer dashboard.

A small FastAPI router layered on top of ``create_app``'s existing runner that
serves the static SPA (index.html + dashboard.css + dashboard.js) and a demo
seed endpoint that instantiates a realistic spread of cases for the board to
render. The dashboard is a thin viewer/controller over the same REST + WebSocket
surface the CLI demo and the (future) voice bot use; it introduces no new
case-graph behaviour.
"""
import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Synthetic applicant payloads identical to the ones used by scripts/demo_case.py
# and the kyc-uae pack tests — kept here so the seed endpoint needs no dependency
# on the tests package.
CLEAN = {"full_name": "Priya Raghavan", "dob": "1992-04-15", "nationality": "IN",
         "residency_status": "uae_resident", "source_of_funds": "salary",
         "product": "spot_trading"}
RISKY = {"full_name": "Muhammad Al-Rashid", "dob": "1975-03-02", "nationality": "SY",
         "residency_status": "non_resident", "source_of_funds": "crypto_trading",
         "product": "derivatives"}


def build_dashboard(runner):
    """Return the dashboard APIRouter, closing over the app's CaseRunner.

    The endpoint closures need the runner so demo-seed can drive real cases
    through the graph exactly the way the CLI demo does.
    """
    router = APIRouter()

    @router.get("/dashboard", include_in_schema=False)
    def dashboard_page():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @router.post("/dashboard/demo-seed", status_code=201)
    def demo_seed():
        """Create a realistic spread of kyc-uae cases for the board to render.

        Two clean applicants auto-approve, two risky applicants park at the
        reviewer gate (a live demo beat), and one case awaits an interview.
        """
        cases = []
        for _ in range(2):
            c = runner.start_case("kyc-uae")
            cases.append(runner.resume(c["case_id"], {"fields": CLEAN, "confidence": {}}))
        for _ in range(2):
            c = runner.start_case("kyc-uae")
            cases.append(runner.resume(c["case_id"], {"fields": RISKY, "confidence": {}}))
        cases.append(runner.start_case("kyc-uae"))
        return {"seeded": len(cases), "cases": cases}

    return router