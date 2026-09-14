#!/usr/bin/env python3
"""Compare both draft-2 adapters against the derived roe-engagement expectations.

Sends every valid-trace and scenario request, the standalone authority
evaluation, the registry registration, the definition readback and the
correspondence check to the Python and TypeScript adapters through
runner/transport.py (one fresh process per request), compares canonical
response bytes to the derived files and to each other, and checks that every
derived AUTHORITY detail names its failed checks consistently. Prints one JSON
report; exits nonzero on any difference. Never writes into the expected files.
"""

from __future__ import annotations

import hashlib
import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT / "conformance/work-class/1.0.0-draft.2"
sys.path.insert(0, str(BASE / "runner"))
import transport  # noqa: E402

CONSUMERS = {"python": ["python3", "python/adapter.py"], "typescript": ["node", "typescript/adapter.ts"]}
PROTOCOL = transport.PROTOCOL


def first_difference(actual, expected, path: str = "") -> str | None:
    if type(actual) is not type(expected):
        return f"{path or '/'}: type {type(actual).__name__} vs {type(expected).__name__}"
    if isinstance(actual, dict):
        for key in sorted(set(actual) | set(expected)):
            if key not in actual:
                return f"{path}/{key}: missing in actual"
            if key not in expected:
                return f"{path}/{key}: unexpected in actual"
            found = first_difference(actual[key], expected[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path}: length {len(actual)} vs {len(expected)}"
        for index, (left, right) in enumerate(zip(actual, expected)):
            found = first_difference(left, right, f"{path}/{index}")
            if found:
                return found
        return None
    if actual != expected:
        return f"{path}: {json.dumps(actual)[:200]} vs {json.dumps(expected)[:200]}"
    return None


def summary(result: dict) -> dict:
    decision = result.get("decision") or {}
    return {"status": result.get("status"), "code": result.get("code"), "disposition": decision.get("disposition"), "reason_codes": decision.get("reason_codes")}


def compare(group: str, request: dict, expected_response: dict, rows: list[dict]) -> None:
    expected_bytes = transport.canonical(expected_response)
    outputs = {}
    for language, command in CONSUMERS.items():
        row = {"group": group, "consumer": language}
        try:
            result = transport.invoke(command, request["request_id"], request["operation"], request["input"], 120.0, 64_000_000, str(BASE))
        except RuntimeError as error:
            rows.append({**row, "passed": False, "error": str(error)})
            continue
        actual = {"protocol": PROTOCOL, "request_id": request["request_id"], "operation": request["operation"], "result": result}
        outputs[language] = transport.canonical(actual)
        row["passed"] = outputs[language] == expected_bytes
        if not row["passed"]:
            row["first_difference"] = first_difference(actual, expected_response)
            row["actual_summary"] = summary(result)
            row["expected_summary"] = summary(expected_response["result"])
        rows.append(row)
    rows.append({"group": f"{group}:cross-language", "consumer": "both", "passed": len(outputs) == 2 and outputs["python"] == outputs["typescript"]})


def compare_stream(name: str, requests_path: Path, expected_path: Path, rows: list[dict]) -> None:
    requests = [transport.read_json(line) for line in requests_path.read_text().splitlines()]
    expected = [transport.read_json(line) for line in expected_path.read_text().splitlines()]
    if len(requests) != len(expected):
        rows.append({"group": f"{name}:line-count", "consumer": "derived", "passed": False})
        return
    for request, expected_response in zip(requests, expected):
        compare(f"{name}:{request['request_id']}", request, expected_response, rows)


def check_derived_failed_checks(rows: list[dict]) -> None:
    """AUTHORITY-CHECKS and LIFE-007 invariants over the derived files, independent of either consumer."""
    problems = []
    named_conditions = []
    for path in (HERE / "valid-trace/results-derived.jsonl", HERE / "scenarios/results-derived.jsonl"):
        for line in path.read_text().splitlines():
            response = transport.read_json(line)
            for detail in (response["result"].get("decision") or {}).get("details", []):
                if detail["kind"] != "AUTHORITY":
                    continue
                checks = detail["failed_checks"]
                if sorted({row["reason"] for row in checks}) != sorted(detail["reasons"]) or not checks:
                    problems.append(f"{response['request_id']}: failed_checks reasons differ from reasons")
                if [transport.canonical(row) for row in checks] != sorted({transport.canonical(row) for row in checks}, key=lambda text: text.encode()):
                    problems.append(f"{response['request_id']}: failed_checks not sorted unique")
                named_conditions += [row["requirement_ref"] for row in checks if row["purpose"] == "CONDITION"]
    if len(named_conditions) != 3 or len(set(named_conditions)) != 3:
        problems.append(f"condition withholdings do not name three distinct conditions: {named_conditions}")
    rows.append({"group": "derived:authority-failed-checks", "consumer": "derived", "passed": not problems, **({"problems": problems} if problems else {})})


def main() -> int:
    rows: list[dict] = []
    load = lambda name: json.loads((HERE / name).read_text())
    check_derived_failed_checks(rows)
    compare_stream("valid", HERE / "valid-trace/requests.jsonl", HERE / "valid-trace/results-derived.jsonl", rows)
    compare_stream("scenario", HERE / "scenarios/requests.jsonl", HERE / "scenarios/results-derived.jsonl", rows)

    def single(group: str, request_id: str, operation: str, input_value: dict, expected_result: dict) -> None:
        request = {"protocol": PROTOCOL, "request_id": request_id, "operation": operation, "input": input_value}
        compare(group, request, {"protocol": PROTOCOL, "request_id": request_id, "operation": operation, "result": expected_result}, rows)

    single("authority-evaluate", "authority-a", "evaluate", {"kind": "AUTHORITY", "request": load("authority-input.json")}, load("authority-result-derived.json"))
    single("registry-register", "register", "aggregate-step", load("shared-budget-register-input.json"), load("shared-budget-register-result-derived.json"))
    work_class_bytes = (HERE / "work-class.json").read_bytes().rstrip(b"\n")
    pin = load("work-class.json")["specification_pin"]
    single("work-class-readback", "readback", "readback",
           {"kind": "WORK_CLASS", "specification_pin": pin, "artifact_bytes_base64": base64.b64encode(work_class_bytes).decode()}, load("readback-derived.json"))
    correspondence_input = load("correspondence-input.json")
    prefix = b"seampoint.work-class/1.0.0-draft.2/evidence\n"
    evidence_digest = "sha256:" + hashlib.sha256(prefix + transport.canonical(correspondence_input["evidence"]).encode()).hexdigest()
    single("correspondence-check", "correspondence", "check-evidence", correspondence_input,
           {"status": "EVIDENCE_VALID", "profile": correspondence_input["profile"], "role": "REVIEW_EVIDENCE",
            "subject_digest": correspondence_input["work_class_digest"], "evidence_digest": evidence_digest, "specification_pin": pin})

    passed = sum(row["passed"] for row in rows)
    report = {"status": "PASS" if passed == len(rows) else "FAIL", "checks": len(rows), "passed": passed,
              "failed": [row for row in rows if not row["passed"]],
              "hashes": {"artifact_index": hashlib.sha256((HERE / "artifact-index.json").read_bytes()).hexdigest(),
                         "derivations": hashlib.sha256((HERE / "DERIVATIONS.md").read_bytes()).hexdigest()}}
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
