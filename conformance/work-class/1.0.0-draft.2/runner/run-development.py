#!/usr/bin/env python3
"""Execute the development case index and compare exact canonical results."""

from __future__ import annotations

import argparse
import datetime
import json
import shlex
import sys
from pathlib import Path

from check_vector_controls import actual as local_control_result
from transport import canonical, invoke, invoke_raw


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent


def load(path: Path):
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-index", type=Path, default=CANDIDATE / "cases" / "index.json")
    parser.add_argument("--adapter-command")
    parser.add_argument("--adapter-without-shared-budget-command")
    parser.add_argument("--host-command")
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--maximum-output", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args()
    # Seampoint machines keep all work on the SSD volume; elsewhere any scratch root is accepted.
    if Path("/Volumes/ssd").is_dir() and not str(args.scratch_root.resolve()).startswith("/Volumes/ssd/"):
        parser.error("scratch root must be under /Volumes/ssd")
    if args.report.exists():
        parser.error("report already exists")
    adapter = shlex.split(args.adapter_command) if args.adapter_command else None
    adapter_without_shared_budget = (
        shlex.split(args.adapter_without_shared_budget_command)
        if args.adapter_without_shared_budget_command
        else None
    )
    host = shlex.split(args.host_command) if args.host_command else None
    index = load(args.case_index)
    rows = []
    args.scratch_root.mkdir(parents=True, exist_ok=True)
    for entry in index["cases"]:
        case = load(CANDIDATE / entry["path"])
        row = {"id": case["id"], "execution_target": entry["execution_target"], "status": "FAIL"}
        try:
            if entry["execution_target"] == "LOCAL_CONTROL":
                observed = local_control_result(case)
            elif entry["execution_target"] == "ADAPTER":
                if adapter is None:
                    raise RuntimeError("ADAPTER_COMMAND_NOT_SUPPLIED")
                observed = invoke(adapter, case["id"], case["operation"], case["input"], args.timeout, args.maximum_output, str(args.scratch_root))
            elif entry["execution_target"] == "ADAPTER_WITHOUT_SHARED_BUDGET_TRANSITIONS":
                if adapter_without_shared_budget is None:
                    raise RuntimeError("ADAPTER_WITHOUT_SHARED_BUDGET_COMMAND_NOT_SUPPLIED")
                observed = invoke(
                    adapter_without_shared_budget,
                    case["id"],
                    case["operation"],
                    case["input"],
                    args.timeout,
                    args.maximum_output,
                    str(args.scratch_root),
                )
            elif entry["execution_target"] == "REFERENCE_HOST":
                if host is None:
                    raise RuntimeError("HOST_COMMAND_NOT_SUPPLIED")
                observed = invoke(host, case["id"], "host-harness", case["input"], args.timeout, args.maximum_output, str(args.scratch_root))
            elif entry["execution_target"] == "RAW_TRANSPORT":
                if adapter is None:
                    raise RuntimeError("ADAPTER_COMMAND_NOT_SUPPLIED")
                observed = invoke_raw(
                    adapter,
                    case["input"]["bytes_base64"],
                    args.timeout,
                    args.maximum_output,
                    str(args.scratch_root),
                )
            else:
                raise RuntimeError(f"UNSUPPORTED_EXECUTION_TARGET_{entry['execution_target']}")
            row["actual"] = observed
            if canonical(observed) == canonical(case["expected"]):
                row["status"] = "PASS"
            else:
                row["expected"] = case["expected"]
        except Exception as error:
            row["execution_failure"] = str(error)
        rows.append(row)
    passed = sum(row["status"] == "PASS" for row in rows)
    report = {
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "PASS" if passed == len(rows) else "FAIL",
        "qualification": "DEVELOPMENT_RUN_NOT_QUALIFYING",
        "candidate_pin": index["candidate_pin"],
        "case_index": str(args.case_index.relative_to(CANDIDATE)),
        "total_cases": str(len(rows)),
        "passed_cases": str(passed),
        "failed_cases": str(len(rows) - passed),
        "case_results": rows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ["status", "qualification", "total_cases", "passed_cases", "failed_cases"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
