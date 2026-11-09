#!/usr/bin/env python3
"""Verify emitted draft 3 review materials through the explicit public evidence view."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
AREA = "conformance/work-class/1.0.0-draft.3"
CONTRACT = "library/work-class-specification/1.0.0-draft.3"
IGNORED_PARTS = {"runs", "node_modules", "__pycache__"}
ROLES = "AGGREGATE_EVALUATOR,AUTHORITY_EVALUATOR,CHOICE_LOOP_RUNTIME,DEADLINE_RUNTIME,FLOW_TRANSITIONS,HOLDINGS_TRANSITIONS,LINEAR_WORK_RUNTIME,PARALLEL_FANOUT_RUNTIME,REFERENCE_SINGLE_PROCESS_CONTENTION,REVIEW_EVIDENCE,RESERVATION_TRANSITIONS"


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def compare_results(index: dict, reports: dict, indexed_count, selected_index: Path) -> dict:
    selected_ids = {row["id"] for row in index["cases"]}
    expected = {row["id"]: load(AREA + "/" + row["path"])["expected"] for row in index["cases"]}
    results, errors = {}, {}
    for consumer in ("typescript", "python"):
        report = reports.get(consumer)
        if report is None:
            errors[consumer] = "MISSING_REPORT"
            continue
        rows = report.get("case_results", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows):
            errors[consumer] = "INVALID_CASE_RESULT_ROWS"
            continue
        ids = [row.get("id") for row in rows]
        try:
            counts_match = all(type(report.get(key)) in (str, int) for key in ("total_cases", "passed_cases", "failed_cases")) and int(report["total_cases"]) == len(selected_ids) and int(report["passed_cases"]) == len(selected_ids) and int(report["failed_cases"]) == 0
            recorded_index = Path(report["case_index"])
            recorded_index = recorded_index if recorded_index.is_absolute() else ROOT / AREA / recorded_index
            identity_matches = report.get("candidate_pin") == index["candidate_pin"] and recorded_index.resolve() == selected_index.resolve()
        except (KeyError, ValueError, TypeError):
            counts_match = False
            identity_matches = False
        if len(ids) != len(selected_ids) or len(set(ids)) != len(ids) or set(ids) != selected_ids:
            errors[consumer] = "SELECTED_CASE_COVERAGE_MISMATCH"
        elif not counts_match:
            errors[consumer] = "SELECTED_CASE_COUNT_MISMATCH"
        elif not identity_matches:
            errors[consumer] = "SELECTED_CASE_IDENTITY_MISMATCH"
        elif report.get("status") != "PASS" or any(row.get("status") != "PASS" or not isinstance(row.get("actual"), dict) or "execution_failure" in row for row in rows):
            errors[consumer] = "INCOMPLETE_OR_FAILED_CASE_RESULT"
        elif any(canonical(row["actual"]) != canonical(expected[row["id"]]) for row in rows):
            errors[consumer] = "EXPECTED_COMPLETE_RESULT_MISMATCH"
        else:
            results[consumer] = {row["id"]: row["actual"] for row in rows}
    differing = [] if errors else [case_id for case_id in sorted(selected_ids) if canonical(results["typescript"][case_id]) != canonical(results["python"][case_id])]
    return {"status": "FAIL" if errors or differing else "PASS", "indexed_case_count": indexed_count, "requested_cases_per_consumer": len(selected_ids), "reported_cases_per_consumer": {name: report.get("total_cases") for name, report in reports.items()}, "execution_strategy": "Fresh transport per adapter, reference-host or raw request; local controls run in the runner", "selected_local_control_cases": sum(row["execution_target"] == "LOCAL_CONTROL" for row in index["cases"]), "different_complete_results": differing, "report_validation_errors": errors}


def execute_phase(argv: list[str], cwd: Path, stdout, stderr, timeout: int) -> dict:
    process = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=os.name == "posix")
    try:
        return {"exit_code": process.wait(timeout=timeout), "timed_out": False}
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()
        return {"exit_code": 124, "timed_out": True}


def inventory() -> dict:
    actual = {}
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if IGNORED_PARTS.intersection(relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError("symlink in package: " + str(relative))
        if path.is_file() and str(relative) != "REVIEW-PACKAGE.json":
            actual[str(relative)] = sha256(path.read_bytes())
        elif not path.is_dir() and str(relative) != "REVIEW-PACKAGE.json":
            raise ValueError("special file in package: " + str(relative))
    package = load("REVIEW-PACKAGE.json")
    if actual != package["emitted_file_sha256"]:
        raise ValueError("emitted inventory, source hash or file count differs from REVIEW-PACKAGE.json")
    for path, expected in package["source_hashes"].items():
        if actual.get(path) != expected:
            raise ValueError("emitted source differs from original source: " + path)
    contract_path = CONTRACT + "/contract-manifest.json"
    pin = "sha256:" + actual[contract_path]
    if package["candidate_pin"] != pin:
        raise ValueError("package candidate pin mismatch")
    contract = load(contract_path)
    for row in contract["files"]:
        if actual.get(CONTRACT + "/" + row["path"]) != row["sha256"]:
            raise ValueError("contract hash mismatch: " + row["path"])
    for consumer in ("python", "typescript"):
        for name in ["contract-manifest.json", *[row["path"] for row in contract["files"]]]:
            if actual.get(f"{AREA}/{consumer}/input/{name}") != actual[CONTRACT + "/" + name]:
                raise ValueError("consumer mirror mismatch: " + consumer + "/" + name)
    suite_path = AREA + "/suite/manifest.json"
    suite = load(suite_path)
    index_path = AREA + "/cases/index.json"
    index = load(index_path)
    index_count = int(index["count"])
    if suite["specification_pin"] != pin or index["candidate_pin"] != pin or index_count != len(index["cases"]) or index["cases"] != suite["cases"]:
        raise ValueError("suite/case inventory mismatch")
    case_paths = {AREA + "/" + row["path"] for row in index["cases"]}
    emitted_cases = {path for path in actual if path.startswith(AREA + "/cases/") and path.endswith(".json") and Path(path).name != "index.json"}
    if case_paths != emitted_cases or len(case_paths) != index_count or len({row["id"] for row in index["cases"]}) != index_count:
        raise ValueError("case inventory missing, extra or duplicate")
    for row in index["cases"]:
        if actual[AREA + "/" + row["path"]] != row["sha256"]:
            raise ValueError("case hash mismatch: " + row["id"])
    for row in suite["specimens"]:
        path = AREA + "/" + row["artifact_index"]
        if actual[path] != row["artifact_index_sha256"]:
            raise ValueError("specimen index hash mismatch: " + path)
        specimen = load(path)
        if specimen["candidate_pin"] != pin:
            raise ValueError("specimen pin mismatch: " + path)
        for item in specimen.get("files", specimen.get("artifacts", [])):
            target = str(Path(path).parent / item["path"])
            expected = item.get("sha256", item.get("raw_sha256", "")).removeprefix("sha256:")
            if actual.get(target) != expected:
                raise ValueError("specimen artifact hash mismatch: " + target)
    overlay = load(package["reviewer_evidence_overlay"])
    if overlay["candidate_pin"] != pin or overlay["canonical_suite_path"] != suite_path or overlay["canonical_suite_sha256"] != actual[suite_path] or package["source_suite_sha256"] != actual[suite_path] or overlay["case_index_sha256"] != actual[index_path]:
        raise ValueError("public evidence overlay is not bound to the canonical suite and case index")
    original_evidence = {row["path"]: row["sha256"] for row in suite["evidence"]}
    included = {row["path"]: row["sha256"] for row in overlay["included_evidence"]}
    omitted = {row["path"]: row["sha256"] for row in overlay["omitted_internal_evidence"]}
    if included.keys() & omitted.keys() or {**included, **omitted} != original_evidence or len(included) + len(omitted) != len(suite["evidence"]):
        raise ValueError("evidence overlay does not account exactly for canonical evidence")
    if overlay["omitted_internal_evidence"] != package["omitted_private_evidence"]:
        raise ValueError("evidence omissions differ from package inventory")
    for path, expected in included.items():
        if actual.get(AREA + "/" + path) != expected:
            raise ValueError("included evidence hash mismatch: " + path)
    for path in omitted:
        if AREA + "/" + path in actual:
            raise ValueError("an explicitly omitted internal record was emitted: " + path)
    return {"candidate_pin": pin, "emitted_files_excluding_manifest": len(actual), "cases": index["count"], "included_evidence": len(included), "omitted_internal_evidence": len(omitted), "manifest_sha256": sha256((ROOT / "REVIEW-PACKAGE.json").read_bytes()), "emitted_inventory_sha256": sha256(canonical(actual))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--scope", choices=("inventory", "support", "corpus", "specimens", "all"), default="inventory")
    parser.add_argument("--case-id", action="append", default=[])
    args = parser.parse_args()
    output = args.out.resolve()
    artifact_root = Path(os.environ.get("WORK_CLASS_ARTIFACT_ROOT", "/Volumes/agents/agent-work")).expanduser().resolve()
    repository_runs = (ROOT / "runs").resolve()
    if output.exists() or not any(output.is_relative_to(root) for root in (artifact_root, repository_runs)):
        parser.error(f"use a fresh run directory under {artifact_root} or {repository_runs}")
    if args.case_id and args.scope not in ("corpus", "all"):
        parser.error("--case-id requires corpus or all scope")
    output.mkdir(parents=True)
    commands = []
    try:
        before = inventory()
    except (OSError, ValueError, KeyError) as error:
        report = {"status": "FAIL", "scope": args.scope, "failure": str(error), "commands": commands, "consumer_processes_started": False}
        (output / "REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return 1
    (output / "inventory-before.json").write_text(json.dumps(before, indent=2) + "\n")

    def run(name: str, argv: list[str], cwd: Path = ROOT, timeout: int = 1200) -> bool:
        with (output / (name + ".stdout.log")).open("wb") as stdout, (output / (name + ".stderr.log")).open("wb") as stderr:
            result = execute_phase(argv, cwd, stdout, stderr, timeout)
        exit_code = result["exit_code"]
        commands.append({"name": name, "argv": argv, "cwd": str(cwd), "timeout_seconds": timeout, "timeout_termination": "PROCESS_GROUP" if os.name == "posix" else "DIRECT_CHILD_ONLY", **result})
        (output / "COMMANDS.json").write_text(json.dumps(commands, indent=2) + "\n")
        print(("PASS " if exit_code == 0 else "FAIL ") + name, flush=True)
        return exit_code == 0

    if args.scope in ("support", "all"):
        run("contract-schemas", ["node", AREA + "/review/check-contract-schemas.mjs"])
        run("corpus-construction", ["node", AREA + "/runner/check-corpus.mjs"])
        run("typescript-typecheck", ["./node_modules/.bin/tsc", "--noEmit"], ROOT / AREA / "typescript")
        run("typescript-units", ["npm", "test", "--silent"], ROOT / AREA / "typescript")
        run("python-units", [sys.executable, "-B", "-m", "unittest", "discover", "-s", AREA + "/python/tests", "-v"], timeout=3600)
        recovery = Path("tests/draft3_work_recovery")
        if (ROOT / recovery).is_dir():
            run("work-recovery-guards", [
                sys.executable, "-B", str(recovery / "verify_cases.py"),
                str(recovery / "SEALED-CASES.json"), str(output / "work-recovery-guards"),
            ])
    if args.scope in ("corpus", "all"):
        index = load(AREA + "/cases/index.json")
        selected_ids = set(args.case_id)
        if selected_ids:
            index["cases"] = [row for row in index["cases"] if row["id"] in selected_ids]
            if {row["id"] for row in index["cases"]} != selected_ids:
                raise ValueError("requested case ID is not indexed")
            index["count"] = len(index["cases"])
        selected_index = output / "selected-case-index.json"
        selected_index.write_text(json.dumps(index, indent=2) + "\n")
        for consumer in ("typescript", "python"):
            transport = ["node", str(ROOT / AREA / "typescript/adapter.ts")] if consumer == "typescript" else [sys.executable, "-B", str(ROOT / AREA / "python/adapter.py")]
            host = ["node", str(ROOT / AREA / "typescript/host.ts")] if consumer == "typescript" else [sys.executable, "-B", str(ROOT / AREA / "python/host_adapter.py")]
            argv = [sys.executable, "-B", AREA + "/runner/run-development.py", "--case-index", str(selected_index), "--adapter-command", shlex.join(transport), "--host-command", shlex.join(host), "--scratch-root", str(output / (consumer + "-scratch")), "--report", str(output / (consumer + ".json")), "--timeout", "600", "--maximum-output", "33554432"]
            for role, option in (("RESERVATION_TRANSITIONS", "reservation"), ("HOLDINGS_TRANSITIONS", "holdings"), ("FLOW_TRANSITIONS", "flow")):
                reduced = ",".join(value for value in ROLES.split(",") if value != role)
                argv.extend(["--adapter-without-" + option + "-command", shlex.join(["env", "WORK_CLASS_ADAPTER_ROLES=" + reduced, *transport])])
            run("corpus-" + consumer, argv, timeout=21600)
        reports = {name: json.loads((output / (name + ".json")).read_text()) for name in ("typescript", "python") if (output / (name + ".json")).is_file()}
        comparison = compare_results(index, reports, before["cases"], selected_index)
        (output / "complete-result-comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
        commands.append({"name": "complete-result-comparison", "exit_code": 0 if comparison["status"] == "PASS" else 1})
        (output / "COMMANDS.json").write_text(json.dumps(commands, indent=2) + "\n")
    if args.scope in ("specimens", "all"):
        run("specimens", [sys.executable, "-B", AREA + "/review/verify-cross-language-specimens.py", "--report", str(output / "specimens.json")], timeout=7200)
        run("information-flow", [sys.executable, "-B", AREA + "/review/verify-information-flow.py", "--conformance-root", AREA, "--report-directory", str(output / "information-flow")], timeout=1200)
    guard_failure = None
    try:
        unchanged = before == inventory()
    except (OSError, ValueError, KeyError) as error:
        unchanged = False
        guard_failure = str(error)
    report = {"status": "PASS" if unchanged and all(row["exit_code"] == 0 for row in commands) else "FAIL", "scope": args.scope, "qualification": "DEVELOPMENT_REPRODUCTION_NOT_QUALIFICATION", "source_inventory_unchanged": unchanged, "guard_failure": guard_failure, "inventory": before, "commands": commands}
    (output / "REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "commands"}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
