#!/usr/bin/env python3
"""Inventory candidate files and optionally require version-control tracking."""

import argparse
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[4]
PATHS = [
    "library/work-class-specification/1.0.0-draft.3",
    "conformance/work-class/1.0.0-draft.3",
    "planning/work-packages/WORK-CLASS-DRAFT3-REQUIREMENTS.md",
    "planning/work-packages/WORK-CLASS-DRAFT3-EQUIPMENT-CONTRACT-PROPOSAL.md",
    "planning/work-packages/WORK-CLASS-DRAFT3-RECOVERY-PROPOSAL.md",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-tracked", action="store_true")
    args = parser.parse_args()
    inventory = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *PATHS],
        cwd=ROOT, capture_output=True, check=True,
    )
    paths = sorted(set(inventory.stdout.decode().strip("\0").split("\0")))
    missing = [path for path in paths if not (ROOT / path).is_file()]
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--", *PATHS],
        cwd=ROOT, capture_output=True, check=True,
    )
    tracked_paths = set(tracked.stdout.decode().strip("\0").split("\0"))
    untracked = [path for path in paths if path not in tracked_paths]
    gate = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", *paths],
        cwd=ROOT, capture_output=True,
    )
    failed = bool(missing) or (args.require_tracked and gate.returncode != 0)
    print(json.dumps({
        "status": "FAIL" if failed else "PASS",
        "scope": "Candidate roots and development planning records; ignored scratch and caches excluded",
        "require_tracked": args.require_tracked,
        "required_paths": paths,
        "required_file_count": len(paths),
        "missing": missing,
        "untracked": untracked,
        "tracked_gate_exit_code": gate.returncode,
        "publication_ready": not missing and gate.returncode == 0,
        "limit": "Tracking does not prove commit contents, a clean tree, adoption or publication authorization.",
    }, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
