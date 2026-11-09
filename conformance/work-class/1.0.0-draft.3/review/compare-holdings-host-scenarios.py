#!/usr/bin/env python3
"""Compare source-frozen host projections; execute no consumer or policy code."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ALTERNATIVES = {
    "PENDING_OR_UNCERTAIN": {"PENDING", "UNCERTAIN", "PENDING_OR_UNCERTAIN"},
    "REFUSED_OR_WITHHELD": {"REFUSED", "WITHHELD", "REFUSED_OR_WITHHELD"},
}


def sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def compare(oracle, report):
    expected_rows = {row["id"]: row for row in oracle["rows"]}
    actual_rows = report.get("rows", [])
    ids = [row.get("id") for row in actual_rows]
    checks = [{"name": "candidate pin", "passed": report.get("candidate_pin") == oracle["candidate_pin"]},
              {"name": "input and runtime guards unchanged", "passed": report.get("guard_unchanged") is True},
              {"name": "complete unique scenario inventory", "passed": len(ids) == len(set(ids)) and set(ids) == set(expected_rows)}]
    for row in actual_rows:
        if row.get("id") not in expected_rows:
            continue
        wanted = expected_rows[row["id"]]["expected"]
        observed = row.get("observed")
        checks.append({"name": row["id"] + ":no unexpected error", "passed": row.get("error") is None})
        checks.append({"name": row["id"] + ":observation object", "passed": isinstance(observed, dict)})
        if not isinstance(observed, dict):
            observed = {}
        for field, value in wanted.items():
            if field == "forbidden_details":
                continue
            actual = observed.get(field)
            passed = actual in ALTERNATIVES[value] if isinstance(value, str) and value in ALTERNATIVES else actual == value
            checks.append({"name": row["id"] + ":" + field, "passed": passed,
                           **({} if passed else {"expected": value, "actual": actual})})
        checks.append({"name": row["id"] + ":raw evidence retained", "passed": bool(row.get("raw_evidence"))})
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--typescript", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    oracle = load(args.oracle)
    reports = {"python": args.python, "typescript": args.typescript}
    checks = []
    for language, path in reports.items():
        checks.extend({"language": language, **row} for row in compare(oracle, load(path)))
    failed = sum(not row["passed"] for row in checks)
    report = {"candidate_pin": oracle["candidate_pin"], "status": "PASS" if failed == 0 else "FAIL",
        "qualification": "DEVELOPMENT_RUN_NOT_QUALIFYING", "scope": "SOURCE_SELECTED_HOST_PROJECTIONS_WITH_RETAINED_RAW_CALLS",
        "oracle": {"path": str(args.oracle), "sha256": sha(args.oracle)},
        "actual_reports": [{"language": language, "path": str(path), "sha256": sha(path)} for language, path in reports.items()],
        "checks": len(checks), "passed": len(checks) - failed, "failed": failed, "results": checks,
        "limitations": ["Process-local checkpoint reconstruction does not establish durable recovery.",
            "Rollback substitution exercises an owned root; it does not prove real provider authenticity or latest-state truth.",
            "Synchronous stub commitment covers only demonstrated writer paths.",
            "The protected public-denial helper does not establish complete application information-flow mediation."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ["candidate_pin", "status", "checks", "passed", "failed"]}, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
