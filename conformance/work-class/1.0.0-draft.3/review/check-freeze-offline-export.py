#!/usr/bin/env python3
"""Build the flattened draft 2 reviewer export and rerun the conformance evidence inside it.

The export holds the specification, the complete draft 2 conformance area (cases, suite manifest, both reference
consumers, runner, four specimens and review records) and the installed dependencies of the runner and of the TypeScript consumer, with no symlinks. Every command
runs from inside the export. Large development run reports are left out and regenerated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

AREA = Path(__file__).resolve().parents[1]
ROOT = AREA.parents[2]
ROLES = "AGGREGATE_EVALUATOR,AUTHORITY_EVALUATOR,CHOICE_LOOP_RUNTIME,DEADLINE_RUNTIME,LINEAR_WORK_RUNTIME,PARALLEL_FANOUT_RUNTIME,REFERENCE_SINGLE_PROCESS_CONTENTION,REVIEW_EVIDENCE"
IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", "ts-morning-final.json", "py-morning-final.json")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name: str, command: list[str], cwd: Path, log: Path) -> dict:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with log.open("w") as handle:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, timeout=7200)
    return {"name": name, "command": command, "exit_code": result.returncode, "log": str(log)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.export_root.exists() or args.report.exists() or not str(args.export_root.resolve()).startswith("/Volumes/ssd/"):
        raise ValueError("new SSD export and report required")
    export = args.export_root
    export.mkdir(parents=True)
    shutil.copytree(ROOT / "library/work-class-specification/1.0.0-draft.3", export / "library/work-class-specification/1.0.0-draft.3", symlinks=False)
    area = export / "conformance/work-class/1.0.0-draft.3"
    shutil.copytree(AREA, area, symlinks=False, ignore=IGNORED)
    shutil.copytree(ROOT / "node_modules", export / "node_modules", symlinks=False)
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(ROOT / name, export / name)
    symlinks = [str(path.relative_to(export)) for path in export.rglob("*") if path.is_symlink()]
    source_references = []
    # Archived reviewer probes under review/records are retained provenance and never run here; only executed code is scanned.
    for path in area.rglob("*"):
        if "records" in path.relative_to(area).parts:
            continue
        if path.is_file() and path.suffix in {".py", ".ts", ".mjs", ".sh"}:
            if str(ROOT) in path.read_text(errors="ignore"):
                source_references.append(str(path.relative_to(export)))

    scratch = export / "scratch"
    scratch.mkdir()
    logs = scratch / "logs"
    logs.mkdir()
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    python = sys.executable
    steps = [run("check-corpus", [node, str(area / "runner/check-corpus.mjs")], export, logs / "check-corpus.log")]
    reports = {}
    for language, adapter, host in (
        ("typescript", f"{node} {area}/typescript/adapter.ts", f"{node} {area}/typescript/host.ts"),
        ("python", f"{python} {area}/python/adapter.py", f"{python} {area}/python/host_adapter.py"),
    ):
        reports[language] = scratch / f"{language}-run.json"
        without_budget = f"env WORK_CLASS_ADAPTER_ROLES={ROLES} {adapter}"
        steps.append(run(f"corpus-{language}", [
            python, str(area / "runner/run-development.py"), "--adapter-command", adapter, "--adapter-without-shared-budget-command", without_budget,
            "--host-command", host, "--scratch-root", str(scratch / f"{language}-scratch"), "--report", str(reports[language]),
        ], export, logs / f"corpus-{language}.log"))
    steps.append(run("specimens-shared-verifier", [python, str(area / "review/verify-cross-language-specimens.py"), "--report", str(scratch / "specimen-verification.json")], area / "review", logs / "specimens.log"))
    steps.append(run("specimen-roe-engagement", [python, str(area / "specimens/roe-engagement/verify-specimen.py")], area / "specimens/roe-engagement", logs / "roe.log"))
    steps.append(run("specimen-sepsis-surveillance", [python, str(area / "specimens/sepsis-surveillance/compare-consumers.py"), "--fresh"], area / "specimens/sepsis-surveillance", logs / "sepsis.log"))

    comparison = {}
    if all(path.exists() for path in reports.values()):
        results = {name: {row["id"]: row for row in json.loads(path.read_text())["case_results"]} for name, path in reports.items()}
        ids = sorted(set(results["typescript"]) | set(results["python"]))
        comparison = {
            name: {"total": len(rows), "passed": sum(row.get("status") == "PASS" for row in rows.values())} for name, rows in results.items()
        }
        comparison["differing_actual"] = [case_id for case_id in ids if results["typescript"].get(case_id, {}).get("actual") != results["python"].get(case_id, {}).get("actual")]

    suite = json.loads((area / "suite/manifest.json").read_text())
    passed = (
        not symlinks and not source_references and all(step["exit_code"] == 0 for step in steps)
        and comparison and not comparison["differing_actual"]
        and all(comparison[name]["passed"] == comparison[name]["total"] == len(suite["cases"]) for name in ("typescript", "python"))
    )
    report = {
        "candidate": "seampoint.work-class/1.0.0-draft.3",
        "export_root": str(export),
        "specification_pin": "sha256:" + sha(export / "library/work-class-specification/1.0.0-draft.3/contract-manifest.json"),
        "suite_manifest_sha256": sha(area / "suite/manifest.json"),
        "external_symlinks": symlinks,
        "files_naming_the_source_checkout": source_references,
        "steps": steps,
        "corpus": comparison,
        "status": "PASS" if passed else "FAIL",
        "limitations": "The export shows that the draft 2 evidence reproduces from a self-contained copy on this host. It does not qualify a production deployment, the host obligations the specification lists, or either consumer beyond the frozen cases and specimens.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "corpus", "external_symlinks", "files_naming_the_source_checkout")}, indent=2))
    print(json.dumps([{key: step[key] for key in ("name", "exit_code")} for step in steps]))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
