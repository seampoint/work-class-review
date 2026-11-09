"""Compare frozen author vectors with the independent in-process Python consumer."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from consumer import Consumer
from implementation import lifecycle, reservation_v2
from implementation.common import PIN, canonical, digest


def reservation_readmission(result, configuration):
    state = result["state"]
    before = canonical(state)
    try:
        valid = (
            state["core"]["configuration"] == configuration
            and reservation_v2._configuration_valid(configuration)
            and reservation_v2._state_digest(state) == result["state_digest"]
            and reservation_v2._replay_state(state, PIN)
        )
    except (KeyError, TypeError, ValueError, RuntimeError):
        valid = False
    return valid and canonical(state) == before


def returned_reservations(operation, request, result):
    checks = []
    if operation == "aggregate-step" and result.get("status") == "TRANSITION":
        checks.append({"path": "state", "valid": reservation_readmission(result, request["state"]["core"]["configuration"])})
    if result.get("status") == "STEP":
        inputs = request["event"].get("budget_inputs", [])
        for index, wrapped in enumerate(result["budget_results"]):
            selected = [row for row in inputs if row["registry_digest"] == wrapped["registry_digest"]]
            valid = False
            if len(selected) == 1:
                configuration = selected[0]["request"]["state"]["core"]["configuration"]
                valid = wrapped["registry_digest"] == digest("reservation-registry", configuration) and reservation_readmission(wrapped["result"], configuration)
            checks.append({"path": f"budget_results[{index}].result.state", "valid": valid})
    return checks


def first_differences(actual, expected, path="$", rows=None):
    rows = [] if rows is None else rows
    if len(rows) >= 8 or actual == expected:
        return rows
    if isinstance(actual, dict) and isinstance(expected, dict):
        for key in sorted(set(actual) | set(expected)):
            if key not in actual or key not in expected:
                rows.append({"path": path + "." + key, "actual_present": key in actual, "expected_present": key in expected})
            else:
                first_differences(actual[key], expected[key], path + "." + key, rows)
            if len(rows) >= 8:
                break
    elif isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            rows.append({"path": path, "actual_length": len(actual), "expected_length": len(expected)})
        for index, (left, right) in enumerate(zip(actual, expected)):
            first_differences(left, right, path + f"[{index}]", rows)
            if len(rows) >= 8:
                break
    else:
        rows.append({"path": path, "actual": actual, "expected": expected})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--group", action="append", default=[])
    parser.add_argument("--exclude-group", action="append", default=[])
    args = parser.parse_args()
    index_path = ROOT.parent / "cases/index.json"
    index_bytes = index_path.read_bytes()
    index = json.loads(index_bytes)
    consumer = Consumer()
    rows = []
    started = time.monotonic()
    for entry in index["cases"]:
        group = Path(entry["path"]).parent.name
        if entry["execution_target"] != "ADAPTER" or (args.group and group not in args.group) or group in args.exclude_group:
            continue
        case = json.loads((ROOT.parent / entry["path"]).read_text())
        result = consumer.call(case["operation"], case["input"])
        exact = canonical(result) == canonical(case["expected"])
        integrity = None
        if result.get("status") in {"STEP", "DEPLOYED"}:
            integrity = lifecycle._validate_state_integrity(result["state"], case["input"]["definition"])
        reservations = returned_reservations(case["operation"], case["input"], result)
        row = {"id": case["id"], "group": group, "exact": exact, "output_state_integrity": integrity, "output_reservation_state_integrity": reservations, "actual_sha256": hashlib.sha256(canonical(result)).hexdigest(), "expected_sha256": hashlib.sha256(canonical(case["expected"])).hexdigest()}
        if not exact or integrity is False or any(not check["valid"] for check in reservations):
            row["differences"] = first_differences(result, case["expected"])
            print(json.dumps({key: row[key] for key in ("id", "group", "exact", "output_state_integrity", "output_reservation_state_integrity")}), flush=True)
        rows.append(row)
        if len(rows) % 50 == 0:
            print(f"Compared {len(rows)} vectors in {time.monotonic() - started:.1f}s", flush=True)
    failed = sum(not row["exact"] or row["output_state_integrity"] is False or any(not check["valid"] for check in row["output_reservation_state_integrity"]) for row in rows)
    work_checks = [row["output_state_integrity"] for row in rows if row["output_state_integrity"] is not None]
    reservation_checks = [check["valid"] for row in rows for check in row["output_reservation_state_integrity"]]
    report = {"candidate_pin": index["candidate_pin"], "index_sha256": hashlib.sha256(index_bytes).hexdigest(), "command": sys.argv, "elapsed_seconds": round(time.monotonic() - started, 3), "total": len(rows), "passed": len(rows) - failed, "failed": failed, "work_state_readmissions": len(work_checks), "work_state_readmission_failures": work_checks.count(False), "reservation_state_readmissions": len(reservation_checks), "reservation_state_readmission_failures": reservation_checks.count(False), "groups": dict(sorted(Counter(row["group"] for row in rows).items())), "results": rows}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in {"command", "results", "groups"}}), flush=True)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
