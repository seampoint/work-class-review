#!/usr/bin/env python3
"""Check that every accepted review binds committed bytes at the current candidate pin."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
REVIEW = CANDIDATE / "review"
ROOT = CANDIDATE.parents[2]
sys.path.insert(0, str(REVIEW))
from corpus_common import candidate_pin, digest, raw_sha256  # noqa: E402


ACCEPTED_STATUSES = {"ACCEPTED", "PASS"}
# A record that declares itself accepted under a longer spelling must still be checked.
# Skipping it would give a self-declared acceptance no binding guarantee at all.
ACCEPTED_PREFIX = "ACCEPTED"
PENDING_STATUSES = {
    "AWAITING_INDEPENDENT_REVIEW",
    "AUTHOR_CONSTRUCTED_PENDING_INDEPENDENT_REVIEW",
    "AUTHOR_REVISION_PENDING_INDEPENDENT_REVIEW",
    "DERIVED_EXPECTATIONS_PENDING_INDEPENDENT_REVIEW",
    "PENDING_INDEPENDENT_DERIVATION",
    "PENDING_INDEPENDENT_REVIEW",
    "READY_FOR_INDEPENDENT_REVIEW",
    "READY_FOR_INDEPENDENT_REVIEW_WITH_INTEGRATION_RERUN_PENDING",
}
REJECTED_STATUSES = {"BLOCKED", "CHANGES_REQUIRED", "REJECTED"}
NON_REVIEW_STATUSES = {
    "DEVELOPMENT_CHECKPOINT",
    "DEVELOPMENT_NOT_QUALIFYING",
    "REVIEWED_INPUT_DISPOSITION",
}

PIN_FIELDS = ("candidate_pin", "specification_pin", "contract_manifest_pin")
ROW_KEYS = ("case_reviews", "rows", "vectors")
CASE_HASH_KEYS = ("case_sha256", "raw_sha256")
INPUT_DIGEST_KEYS = ("input_canonical_sha256", "input_digest")
EXPECTED_DIGEST_KEYS = (
    "expected_canonical_sha256",
    "expected_digest",
    "expected_digest_compared_after_derivation",
    "expected_result_sha256",
)


def first(mapping: dict, keys: tuple) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def is_accepted(status: str) -> bool:
    upper = status.upper()
    return upper in ACCEPTED_STATUSES or upper.startswith(ACCEPTED_PREFIX)


def status_of(record: dict) -> str | None:
    value = record.get("status") or record.get("overall_status")
    return str(value) if value is not None else None


def case_index() -> dict:
    index = {}
    for path in sorted(CANDIDATE.glob("cases/**/*.json")):
        if path.name == "index.json":
            continue
        try:
            index[json.loads(path.read_text())["id"]] = path
        except (KeyError, ValueError):
            continue
    return index


def committed_blob(commit: str, path: Path) -> bytes | None:
    relative = path.relative_to(ROOT)
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{relative}"],
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def commit_exists(commit: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"],
        capture_output=True,
    )
    return result.returncode == 0


def check_review(path: Path, cases: dict, pin: str, failures: list) -> dict:
    record = json.loads(path.read_text())
    name = path.name
    status = status_of(record)
    counters = {"rows": 0, "reconciled": 0}

    if status is None:
        failures.append({"review": name, "requirement": "STATUS_PRESENT", "detail": "no status or overall_status member"})
        return counters
    if not is_accepted(status):
        return counters

    declared_pin = first(record, PIN_FIELDS)
    if declared_pin is None:
        failures.append({"review": name, "requirement": "PIN_DECLARED", "detail": "no candidate pin member"})
    elif declared_pin != pin:
        failures.append({"review": name, "requirement": "PIN_CURRENT", "detail": f"binds {declared_pin}, current is {pin}"})

    commit = record.get("reviewed_commit")
    if commit is None:
        failures.append({"review": name, "requirement": "COMMIT_DECLARED", "detail": "no reviewed_commit member"})
    elif not commit_exists(str(commit)):
        failures.append({"review": name, "requirement": "COMMIT_RESOLVABLE", "detail": f"{commit} is not a commit in this repository"})
        commit = None

    rows = next((record[key] for key in ROW_KEYS if isinstance(record.get(key), list)), [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        case_id = row.get("case_id") or row.get("id")
        if case_id is None:
            continue
        counters["rows"] += 1
        case_path = cases.get(case_id)
        if case_path is None:
            failures.append({"review": name, "case_id": case_id, "requirement": "CASE_PRESENT", "detail": "no case with this id"})
            continue

        declared_hash = first(row, CASE_HASH_KEYS)
        if declared_hash is None:
            failures.append({"review": name, "case_id": case_id, "requirement": "CASE_HASH_DECLARED", "detail": "no case hash member"})
            continue
        if declared_hash != raw_sha256(case_path):
            failures.append({"review": name, "case_id": case_id, "requirement": "CASE_HASH_CURRENT", "detail": "declared hash differs from the current case file"})
            continue

        if commit is not None:
            blob = committed_blob(str(commit), case_path)
            if blob is None:
                failures.append({"review": name, "case_id": case_id, "requirement": "CASE_COMMITTED", "detail": f"case absent from {commit}"})
                continue
            if hashlib.sha256(blob).hexdigest() != declared_hash:
                failures.append({"review": name, "case_id": case_id, "requirement": "CASE_HASH_COMMITTED", "detail": f"declared hash differs from the bytes in {commit}"})
                continue

        case = json.loads(case_path.read_text())
        declared_input = first(row, INPUT_DIGEST_KEYS)
        declared_expected = first(row, EXPECTED_DIGEST_KEYS)
        if declared_input is None or declared_expected is None:
            failures.append({"review": name, "case_id": case_id, "requirement": "DIGESTS_DECLARED", "detail": "no canonical input or expected digest member"})
            continue

        domain = row.get("digest_domain")
        if domain is None:
            failures.append({"review": name, "case_id": case_id, "requirement": "DIGEST_DOMAIN_DECLARED", "detail": "no digest_domain member naming the input and expected domains"})
            continue
        input_domain = domain.get("input")
        expected_domain = domain.get("expected")
        if not input_domain or not expected_domain:
            failures.append({"review": name, "case_id": case_id, "requirement": "DIGEST_DOMAIN_COMPLETE", "detail": "digest_domain lacks an input or expected label"})
            continue
        if digest(input_domain, case["input"]) != declared_input:
            failures.append({"review": name, "case_id": case_id, "requirement": "INPUT_DIGEST_REPRODUCES", "detail": f"declared input digest does not reproduce under domain {input_domain}"})
            continue
        if digest(expected_domain, case["expected"]) != declared_expected:
            failures.append({"review": name, "case_id": case_id, "requirement": "EXPECTED_DIGEST_REPRODUCES", "detail": f"declared expected digest does not reproduce under domain {expected_domain}"})
            continue

        counters["reconciled"] += 1

    return counters


def main() -> int:
    pin = candidate_pin()
    cases = case_index()
    failures: list = []
    unclassified: list = []
    accepted = rows_total = rows_reconciled = 0

    for path in sorted(REVIEW.glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        status = status_of(record)
        if status is None:
            continue
        upper = status.upper()
        known = ACCEPTED_STATUSES | PENDING_STATUSES | REJECTED_STATUSES | NON_REVIEW_STATUSES
        if upper not in known:
            unclassified.append({"review": path.name, "status": status})
            # An unrecognised status is a defect, not a reason to skip the record. The
            # control cannot decide what an undeclared status means.
            failures.append({
                "review": path.name,
                "requirement": "STATUS_CLASSIFIED",
                "detail": f"status {status} is outside the known vocabulary",
            })
        if not is_accepted(status):
            continue
        accepted += 1
        counters = check_review(path, cases, pin, failures)
        rows_total += counters["rows"]
        rows_reconciled += counters["reconciled"]

    result = {
        "status": "PASS" if not failures else "FAIL",
        "identity": "seampoint.work-class.review-binding-control/1.0.0-draft.2",
        "candidate_pin": pin,
        "accepted_reviews": str(accepted),
        "rows_declared": str(rows_total),
        "rows_reconciled": str(rows_reconciled),
        "rows_returned_to_pending": str(rows_total - rows_reconciled),
        "unclassified_statuses": unclassified,
        "failures": failures,
    }
    print(json.dumps(result, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
