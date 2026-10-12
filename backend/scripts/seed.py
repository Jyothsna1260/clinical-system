"""Seed a running backend with demo data through the public API (works locally or against Render).

Creates (or logs in) the demo user, uploads the four synthetic protocols (renal x2, hepatic,
cardiac) and creates the ten synthetic patients. With --analyze it runs a representative set of
assessments (including the 69 / eGFR 28 acceptance case) and prints each outcome.

    python -m scripts.seed --api-url http://localhost:8000 [--analyze]

All data is synthetic. Demo credentials are for local demos only.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
DEMO_EMAIL = "demo@example.org"
DEMO_PASSWORD = "demo-password-123"
PROTOCOLS = [("protocol_renal.pdf", "SYN-RENAL-001 (severe renal impairment undefined)"),
             ("protocol_renal_defined.pdf", "SYN-RENAL-001b (severe renal impairment defined as eGFR < 30)"),
             ("protocol_hepatic.pdf", "SYN-HEP-002 (liver safety study, HP-42)"),
             ("protocol_cardio.pdf", "SYN-CARDIO-003 (heart failure study, CV-9)")]
PATIENTS = ["patient_69_egfr28.json", "patient_all_pass.json", "patient_missing_egfr.json",
            "patient_conflicting_egfr.json",
            "patient_hep_eligible.json", "patient_hep_high_alt.json", "patient_hep_stale_labs.json",
            "patient_cardio_eligible.json", "patient_cardio_recent_mi.json", "patient_cardio_incomplete.json"]
# (protocol, patient) pairs assessed with --analyze; the first is the mandatory acceptance case.
ANALYSES = [("protocol_renal.pdf", "patient_69_egfr28.json"),
            ("protocol_renal.pdf", "patient_all_pass.json"),
            ("protocol_renal_defined.pdf", "patient_69_egfr28.json"),
            ("protocol_hepatic.pdf", "patient_hep_eligible.json"),
            ("protocol_hepatic.pdf", "patient_hep_high_alt.json"),
            ("protocol_hepatic.pdf", "patient_hep_stale_labs.json"),
            ("protocol_cardio.pdf", "patient_cardio_eligible.json"),
            ("protocol_cardio.pdf", "patient_cardio_recent_mi.json"),
            ("protocol_cardio.pdf", "patient_cardio_incomplete.json")]


def _token(client: httpx.Client, email: str, password: str) -> str:
    r = client.post("/api/auth/register", json={"email": email, "password": password, "full_name": "Demo Clinician"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def seed(api_url: str, email: str, password: str, analyze: bool) -> int:
    from scripts.make_synthetic_protocol import main as make_pdfs

    if not all((FIXTURES / name).exists() for name, _ in PROTOCOLS):
        make_pdfs()
    with httpx.Client(base_url=api_url, timeout=120) as client:
        client.headers["Authorization"] = f"Bearer {_token(client, email, password)}"
        existing_trials = {t["title"]: t for t in client.get("/api/trials").json()}
        trial_ids = {}
        for name, title in PROTOCOLS:
            if title in existing_trials:
                trial_ids[name] = existing_trials[title]["id"]
                print(f"trial exists: {title}")
                continue
            with open(FIXTURES / name, "rb") as fh:
                r = client.post("/api/trials/upload", files={"file": (name, fh, "application/pdf")},
                                data={"title": title})
            r.raise_for_status()
            trial = r.json()
            trial_ids[name] = trial["id"]
            print(f"uploaded {title}: {len(trial['criteria'])} criteria")

        existing_patients = {p["label"]: p for p in client.get("/api/patients").json()}
        patient_ids = {}
        for name in PATIENTS:
            body = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
            if body["label"] in existing_patients:
                patient_ids[name] = existing_patients[body["label"]]["id"]
                print(f"patient exists: {body['label']}")
                continue
            r = client.post("/api/patients", json={"label": body["label"], "profile": body["profile"]})
            r.raise_for_status()
            patient_ids[name] = r.json()["id"]
            print(f"created patient: {body['label']}")

        if analyze:
            failed = 0
            for protocol, patient in ANALYSES:
                r = client.post("/api/eligibility/analyze", json={
                    "trial_id": trial_ids[protocol], "patient_id": patient_ids[patient]})
                r.raise_for_status()
                run_id = r.json()["run_id"]
                for _ in range(180):
                    status = client.get(f"/api/eligibility/{run_id}/status").json()
                    if status["status"] in {"completed", "failed"}:
                        break
                    time.sleep(1)
                print(f"analysis {protocol} x {patient}: {status['status']} -> {status['overall_status']}")
                failed += status["status"] != "completed"
            if failed:
                return 1
    print(f"\nDemo login: {email} / {password}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--email", default=DEMO_EMAIL)
    parser.add_argument("--password", default=DEMO_PASSWORD)
    parser.add_argument("--analyze", action="store_true", help="also run the 69 / eGFR 28 acceptance analysis")
    args = parser.parse_args()
    sys.exit(seed(args.api_url.rstrip("/"), args.email, args.password, args.analyze))


if __name__ == "__main__":
    main()
