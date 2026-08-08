"""VoxGate CLI demo — drives one kyc-uae case end-to-end against a running server.

Terminal 1: uv run uvicorn voxgate.service.app:app --port 8000
Terminal 2: uv run python scripts/demo_case.py            # clean applicant, auto-approves
            uv run python scripts/demo_case.py --risky     # sanctions-lookalike, parks for review

This is the Plan-1 demo artifact: run it while screen-recording to show a case
being created, interviewed, scored, and (for --risky) reviewed by a human.
"""
import argparse
import httpx

BASE = "http://127.0.0.1:8000"

CLEAN = {"full_name": "Priya Raghavan", "dob": "1992-04-15", "nationality": "IN",
         "residency_status": "uae_resident", "source_of_funds": "salary",
         "product": "spot_trading"}
RISKY = {"full_name": "Muhammad Al-Rashid", "dob": "1975-03-02", "nationality": "SY",
         "residency_status": "non_resident", "source_of_funds": "crypto_trading",
         "product": "derivatives"}


def transition(case):
    print(f"[{case['case_id']}] status={case['status']}")


def print_waterfall(score):
    print(f"  probability={score['probability']:.4f}  band={score['band']}")
    for c in sorted(score["contributions"], key=lambda c: -abs(c["contribution"])):
        bars = "#" * round(abs(c["contribution"]) / 0.1)
        print(f"  {c['feature']:<24} value={c['value']:<7} weight={c['weight']:<5} "
              f"contribution={c['contribution']:+.4f} {bars}")


def print_checks(check_results):
    for c in check_results:
        print(f"  check={c['check_name']:<14} status={c['status']:<7} score={c['score']:.3f}")


def main():
    parser = argparse.ArgumentParser(description="VoxGate demo CLI")
    parser.add_argument("--risky", action="store_true", help="use the sanctions-lookalike applicant")
    args = parser.parse_args()
    fields = RISKY if args.risky else CLEAN

    client = httpx.Client(base_url=BASE, timeout=10.0)

    case = client.post("/cases", json={"pack_id": "kyc-uae"}).json()
    transition(case)
    print("interview interrupt payload:")
    print(f"  reask_fields={case['interrupt']['reask_fields']}  fields_so_far={case['interrupt']['fields_so_far']}")

    print(f"[{case['case_id']}] submitting interview fields ({'RISKY' if args.risky else 'CLEAN'})")
    case = client.post(f"/cases/{case['case_id']}/interview-result",
                       json={"fields": fields, "confidence": {}}).json()
    transition(case)

    if case.get("check_results"):
        print("check results:")
        print_checks(case["check_results"])
    if case.get("score"):
        print("score waterfall:")
        print_waterfall(case["score"])

    if case["status"] == "awaiting_review":
        print(f"[{case['case_id']}] parked for human review - gate_role={case['interrupt']['gate_role']}")
        action = ""
        while action not in {"approve", "reject", "request_info"}:
            action = input("decision (approve/reject/request_info): ").strip().lower()
        note = input("note (optional): ").strip()
        case = client.post(f"/cases/{case['case_id']}/decision",
                           json={"action": action, "note": note}).json()
        transition(case)

        if case["status"] == "processing":  # request_info re-opened the interview
            print(f"[{case['case_id']}] re-interview requested — resubmitting fields")
            case = client.post(f"/cases/{case['case_id']}/interview-result",
                               json={"fields": fields, "confidence": {}}).json()
            transition(case)

    print(f"[{case['case_id']}] final status: {case['status']}")


if __name__ == "__main__":
    main()
