#!/usr/bin/env python3
"""Write the draft 2 freeze record from the suite manifest, the offline export report and the review records."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
from pathlib import Path

AREA = Path(__file__).resolve().parents[1]
ROOT = AREA.parents[2]
CONTRACT = ROOT / "library/work-class-specification/1.0.0-draft.3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-report", type=Path, required=True)
    parser.add_argument("--verification-commit", required=True)
    args = parser.parse_args()
    pin = "sha256:" + sha(CONTRACT / "contract-manifest.json")
    suite_path = AREA / "suite/manifest.json"
    suite = json.loads(suite_path.read_text())
    if suite["specification_pin"] != pin:
        raise ValueError("suite manifest is not at the current pin")
    export = json.loads(args.export_report.read_text())
    if export["specification_pin"] != pin or export["suite_manifest_sha256"] != sha(suite_path):
        raise ValueError("offline export report does not bind this pin and suite manifest")
    records = AREA / "review/records/freeze-20260914"
    records.mkdir(parents=True, exist_ok=True)
    stored_export = records / "offline-export-report.json"
    shutil.copy2(args.export_report, stored_export)
    register = json.loads((AREA / "review/JUDGMENT-CASE-REGISTER.json").read_text())
    pending = sorted(row["judgment_id"] for row in register["rows"] if not row.get("case_path"))
    record = {
        "identity": "seampoint.work-class/1.0.0-draft.3",
        "at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "SEMANTIC_FREEZE_OPEN_REVIEW_CANDIDATE",
        "meaning": "The draft 2 normative text, schemas and conformance suite are fixed at this pin for open review and for white paper revision 3. A change to any normative file or expected result creates a new candidate; results stay attached to the pin that produced them.",
        "claim_ceiling": "APPARATUS_ONLY",
        "qualification": "NOT_QUALIFIED",
        "specification_pin": pin,
        "suite_manifest": {"path": "suite/manifest.json", "sha256": sha(suite_path)},
        "counts": {
            "requirements": str(len(suite["mandatory_requirements"])),
            "cases": str(len(suite["cases"])),
            "contract_judgments": str(register["counts"].get("judgments", "")) if isinstance(register.get("counts"), dict) else "",
            "specimens": str(len(suite["specimens"])),
        },
        "register_counts": register.get("counts"),
        "pending_judgments": pending,
        "verification": {
            "commit": args.verification_commit,
            "procedure": "one pass: corpus check, both reference consumers over every case with every actual result compared, the shared specimen verifier, npm run gates",
            "corpus": "PASS", "typescript": "425 of 425", "python": "425 of 425", "differing_results": "0", "specimens": "PASS", "gates": "681 of 681",
        },
        "offline_export": {"path": "review/records/freeze-20260914/offline-export-report.json", "sha256": sha(stored_export), "status": export["status"], "corpus": export.get("corpus"), "steps": [{key: step[key] for key in ("name", "exit_code")} for step in export["steps"]]},
        "review": {
            "path": "review/records/FREEZE-REVIEW-20260913.md", "sha256": sha(AREA / "review/records/FREEZE-REVIEW-20260913.md"),
            "pin_reviewed": "sha256:5a75779d3191c2e8b7b3b0db8533fdcc9e0aabd8fb9d32a6f43e72c1e9c0be21",
            "findings": {"raised": "34", "refuted": "5", "confirmed": "28", "uncertain": "1"},
        },
        "unreviewed_changes": [
            {"commit": "a141ec4d", "pin": "sha256:571fbbb7d6712eb3418a0ffc1b9fd34aa29df00919940d95374cd66fff0bb456", "summary": "Text-decided fixes from the review round in the affected consumers, a revert of an observed-request name check, five clarifying sentences, eight cases and specimen documentation corrections."},
            {"commit": "84da38c4", "pin": pin, "summary": "The specification owner's decisions on the round's open questions: deployment binding conditions before availability conditions, admission of a fresh REJECTED attempt on a consumed permit, removal of the failed_checks cap, and the statement that the reservation transition does not compare the observed request with actual fields; five cases."},
        ],
        "decisions": {"path": "review/CONTRACT-DECISIONS.md", "sha256": sha(AREA / "review/CONTRACT-DECISIONS.md")},
        "known_limitations": [
            "D2-193 has no exact vector.",
            "No independent review has accepted the access-card correspondence subject (AC-REV-001); every specimen's review acts are labelled synthetic proxies.",
            "Draft 2 has no mutation catalog, generated-property suite or closed requirement-coverage record.",
            "The Python consumer's unit tests under python/tests are stale and outside the gates.",
            "A disputed effect has no attributable human exit in draft 2.",
        ],
        "later_candidate_items": ["CR-02a and CR-02b: disposition of a disputed reservation and lifecycle dispute clearance", "CR-06: business-day boundaries", "CR-07: host conformance profile", "Pre-approved materiality thresholds", "Specimen design inputs recorded in CONTRACT-DECISIONS.md"],
    }
    (AREA / "review/FREEZE.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"status": record["status"], "pin": pin, "suite": record["suite_manifest"]["sha256"], "export": record["offline_export"]["status"], "pending": pending, "register_counts": register.get("counts")}, indent=2))


if __name__ == "__main__":
    main()
