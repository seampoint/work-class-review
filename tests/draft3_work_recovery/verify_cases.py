"""Compare complete native responses with the sealed REC-016 work-only controls."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "conformance/work-class/1.0.0-draft.3"
sys.path.insert(0, str(AREA / "review"))
sys.path.insert(0, str(AREA / "runner"))

from corpus_common import canonical_bytes
from transport import PROTOCOL, run_captured

SEAL = "7059f391633fb65aae13c818bca36476b56a21097225f6d05fcacff5a69a9dcc"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sealed_cases", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.sealed_cases.read_bytes()
    if sha256(raw).hexdigest() != SEAL:
        parser.error("input differs from preexecution seal")
    cases = json.loads(raw)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ["WORK_CLASS_CHILD_CAPTURE_DIR"] = str(output / "raw")
    node = os.environ.get("WORK_CLASS_NODE") or shutil.which("node")
    if not node:
        parser.error("Node.js is required on PATH or through WORK_CLASS_NODE")
    commands = {
        "typescript": [node, str(AREA / "typescript/adapter.ts")],
        "python": [sys.executable, "-B", str(AREA / "python/adapter.py")],
    }
    rows = []
    for case in cases:
        request = {"protocol": PROTOCOL, "request_id": case["id"], "operation": "step", "input": case["input"]}
        expected = canonical_bytes({
            "protocol": PROTOCOL, "request_id": case["id"], "operation": "step", "result": case["expected"],
        }) + b"\n"
        for consumer, command in commands.items():
            result = run_captured(command, canonical_bytes(request) + b"\n", cwd=str(AREA), timeout=120)
            passed = result.returncode == 0 and not result.stderr and result.stdout == expected
            response = json.loads(result.stdout)["result"] if result.returncode == 0 else {}
            rows.append({
                "case": case["id"], "consumer": consumer, "passed": passed, "exit_code": result.returncode,
                "actual_sha256": sha256(result.stdout).hexdigest(), "expected_sha256": sha256(expected).hexdigest(),
                "disposition": response.get("decision", {}).get("disposition"),
                "reasons": response.get("decision", {}).get("reason_codes"),
                "failure_code": response.get("refusal", {}).get("code") if response.get("refusal") else response.get("code"),
            })
    summary = {"sealed_input_sha256": SEAL, "rows": rows, "passed": sum(row["passed"] for row in rows), "total": len(rows)}
    with (output / "REPORT.json").open("x") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}), flush=True)
    return int(summary["passed"] != summary["total"])


if __name__ == "__main__":
    sys.exit(main())
