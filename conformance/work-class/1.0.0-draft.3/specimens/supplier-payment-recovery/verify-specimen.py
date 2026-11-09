#!/usr/bin/env python3
"""Freeze source-derived specimen assertions before executing either adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[2]
REVIEW = BASE / "review"
sys.path.insert(0, str(REVIEW))
from corpus_common import candidate_pin, canonical_bytes
from verification_output import output_directory, fresh_output_file
sys.path.insert(0, str(BASE / "runner"))
from transport import run_captured  # noqa: E402


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(path, *, report=True):
    path = fresh_output_file(path, ROOT)
    freeze_path = fresh_output_file(path.with_suffix(".freeze.json"), ROOT)
    cases = []
    requests = load(HERE / "valid-trace/requests.json")
    results = load(HERE / "valid-trace/results-derived.json")
    for request, result in zip(requests, results, strict=True):
        cases.append({"group": "ordinary-source2", "request": request, "expected": result})
    for scenario in load(HERE / "recovery/expectations.json")["scenarios"]:
        source = HERE / scenario["requests"]
        if "expected" in scenario:
            cases.append({"group": scenario["id"], "request": load(source), "expected_subset": scenario["expected"]})
        else:
            for request, result in zip(load(source), load(source.with_name("results-derived.json")), strict=True):
                cases.append({"group": scenario["id"], "request": request, "expected": result})
    authority_cases = [BASE / "cases/recovery-authority" / ("C3-RCTRL-" + str(index).zfill(3) + ".json") for index in range(1, 25)]
    for source in authority_cases:
        case = load(source)
        request = {"protocol": "seampoint.work-class.adapter/1.0.0-draft.3", "request_id": case["id"],
                   "operation": case["operation"], "input": case["input"]}
        expected = {name: request[name] for name in ("protocol", "request_id", "operation")}
        expected["result"] = case["expected"]
        cases.append({"group": "recovery-controller-separation", "request": request, "expected": expected})
    value = {"candidate_pin": candidate_pin(), "status": "FROZEN_BEFORE_SPECIMEN_CONSUMER_EXECUTION",
        "implementation_outputs_consulted_for_expectations": False, "cases": cases,
        "limits": ["All organizational and provider records are synthetic", "No production provider authenticity or complete-writer proof",
            "No durable host commitment or process-restart verification", "Six financial branches do not cover every recovery requirement"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical_bytes(value) + b"\n")
    dependencies = [Path(__file__), HERE / "build-specimen.py", HERE.parent / "supplier-payment/build-specimen.py",
        REVIEW / "recovery_fixture.py", REVIEW / "reservation_fixture.py", REVIEW / "lifecycle_factory.py",
        REVIEW / "corpus_common.py", REVIEW / "fixtures/supplier-payment-recovery-revision2-source.md", HERE / "README.md", path]
    dependencies.extend(authority_cases)
    dependencies.append(REVIEW / "build-recovery-authority-cases.py")
    dependencies.extend(sorted(HERE.rglob("*.json")))
    dependencies.extend(sorted(HERE.rglob("*.jsonl")))
    freeze = {"candidate_pin": candidate_pin(), "status": value["status"], "files": [
        {"path": str(item.relative_to(ROOT)) if item.is_relative_to(ROOT) else str(item), "sha256": sha(item)} for item in dependencies]}
    with freeze_path.open("x") as stream:
        stream.write(json.dumps(freeze, indent=2) + "\n")
    if report:
        print(json.dumps({"fixture": str(path), "sha256": sha(path), "cases": str(len(cases)), "consumer_execution": False}))


def difference(actual, expected, pointer=""):
    if type(actual) is not type(expected):
        return {"path": pointer, "actual": actual, "expected": expected}
    if isinstance(expected, dict):
        if set(actual) != set(expected):
            return {"path": pointer, "actual_keys": sorted(actual), "expected_keys": sorted(expected)}
        for key in sorted(expected):
            found = difference(actual[key], expected[key], pointer + "/" + key)
            if found:
                return found
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            return {"path": pointer, "actual_length": str(len(actual)), "expected_length": str(len(expected))}
        for index, (a, e) in enumerate(zip(actual, expected, strict=True)):
            found = difference(a, e, pointer + "/" + str(index))
            if found:
                return found
    elif actual != expected:
        return {"path": pointer, "actual": actual, "expected": expected}
    return None


def subset(result):
    budget = result.get("budget_results", [{}])[0].get("result", {})
    evaluation = budget.get("receipt", {}).get("budgets", [{}])[0].get("result", {})
    return {"status": result.get("status"), "disposition": result.get("decision", {}).get("disposition"),
        "instance_id": result.get("state", {}).get("instance_id"), "budget_decision": budget.get("receipt", {}).get("decision"),
        "ordinary_total": evaluation.get("partitions", [{}])[0].get("result")}


def run(path, node):
    path = output_directory(path, ROOT)
    output_paths = {name: fresh_output_file(path.with_name(path.stem + "." + name + ".actual.jsonl"), ROOT)
                    for name in ("python", "typescript")}
    report_path = fresh_output_file(path.with_suffix(".results.json"), ROOT)
    value = load(path)
    frozen = load(path.with_suffix(".freeze.json"))
    assert value["candidate_pin"] == candidate_pin(), "Candidate changed after fixture freeze"
    for row in frozen["files"]:
        assert sha(ROOT / row["path"]) == row["sha256"], "Frozen specimen input changed: " + row["path"]
    payload = b"".join(canonical_bytes(row["request"]) + b"\n" for row in value["cases"])
    checks, outputs = [], {}
    commands = {"python": [sys.executable, str(BASE / "python/adapter.py")], "typescript": [node, str(BASE / "typescript/adapter.ts")]}
    for name, command in commands.items():
        completed = run_captured(command, payload, cwd=ROOT)
        with output_paths[name].open("xb") as stream:
            stream.write(completed.stdout)
        checks.append({"consumer": name, "group": "adapter-process", "passed": completed.returncode == 0,
            **({"exit_code": str(completed.returncode), "stderr": completed.stderr.decode(errors="replace")} if completed.returncode else {})})
        lines = completed.stdout.splitlines(keepends=True)
        actual = [json.loads(row) for row in lines]
        outputs[name] = completed.stdout
        checks.append({"consumer": name, "group": "response-count", "passed": len(actual) == len(value["cases"]),
            "expected": str(len(value["cases"])), "actual": str(len(actual))})
        for case, response, line in zip(value["cases"], actual, lines):
            # Exact bytes, not parsed JSON. A full expectation fixes the whole line; a
            # subset expectation still requires the line to be the canonical form of itself.
            wanted_line = canonical_bytes(case["expected"] if "expected" in case else response) + b"\n"
            observed, expected = (response, case["expected"]) if "expected" in case else (subset(response["result"]), case["expected_subset"])
            mismatch = difference(observed, expected)
            if mismatch is None and line != wanted_line:
                mismatch = {"path": "", "error": "NONCANONICAL_OUTPUT"}
            checks.append({"consumer": name, "group": case["group"], "request_id": case["request"]["request_id"],
                "passed": mismatch is None, **({"difference": mismatch} if mismatch else {})})
    checks.append({"group": "cross-language", "passed": outputs["python"] == outputs["typescript"]})
    passed = all(row["passed"] for row in checks)
    report = {"candidate_pin": value["candidate_pin"], "status": "PASS" if passed else "FAIL", "cases_per_consumer": str(len(value["cases"])),
        "fixture_sha256": sha(path), "freeze_sha256": sha(path.with_suffix(".freeze.json")), "checks": checks, "limits": value["limits"]}
    with report_path.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "cases_per_consumer": report["cases_per_consumer"], "failed": [row for row in checks if not row["passed"]], "report": str(report_path)}))
    if not passed:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--run", action="store_true")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "runs/2026-10-07-recovery-implementation/supplier-payment-recovery-fixtures.json")
    parser.add_argument("--node", default="node")
    parser.add_argument("--report-directory", type=Path)
    args = parser.parse_args()
    if not args.prepare and not args.run:
        try:
            run_root = output_directory(args.report_directory or ROOT / "runs/2026-10-07-recovery-implementation" / ("source2-verification-" + uuid.uuid4().hex), ROOT)
        except ValueError as error:
            parser.error(str(error))
        run_root.mkdir(parents=True, exist_ok=False)
        (run_root / "retention-reason.txt").write_text("Retain the independently frozen inputs and consumer outputs as evidence for the cross-language specimen verification run.\n")
        fixtures = run_root / "fixtures.json"
        prepare(fixtures, report=False)
        run(fixtures, args.node)
    elif args.prepare:
        try:
            destination = fresh_output_file(args.fixtures, ROOT)
            fresh_output_file(destination.with_suffix(".freeze.json"), ROOT)
        except ValueError as error:
            parser.error(str(error))
        prepare(destination)
    else:
        try:
            fixture = output_directory(args.fixtures, ROOT)
        except ValueError as error:
            parser.error(str(error))
        run(fixture, args.node)


if __name__ == "__main__":
    main()
