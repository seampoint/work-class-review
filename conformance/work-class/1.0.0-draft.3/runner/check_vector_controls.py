#!/usr/bin/env python3
"""Verify frozen digest-vector expectations without evaluating policy."""

from __future__ import annotations

import copy
import base64
import datetime
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "review"))
from corpus_common import canonical_bytes, digest  # noqa: E402


def state_core_digest(state: dict) -> str:
    projected = copy.deepcopy(state)
    projected["receipts"] = []
    projected["replays"] = []
    return digest("work-state-core", projected)


def state_digest(state: dict) -> str:
    projected = copy.deepcopy(state)
    for replay in projected["replays"]:
        replay.pop("transaction_digest", None)
    return digest("work-state", projected)


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def readback_lines(value, path: str = "") -> list[dict[str, str]]:
    if isinstance(value, dict) and value:
        rows = []
        for key, member in value.items():
            rows.extend(readback_lines(member, path + "/" + pointer_token(key)))
        return rows
    if isinstance(value, list) and value:
        rows = []
        for index, member in enumerate(value):
            rows.extend(readback_lines(member, path + "/" + str(index)))
        return rows
    return [{"path": path, "value": canonical_bytes(value).decode("utf-8")}]


def valid_timestamp(value: str, precision: str) -> bool:
    suffix = r"" if precision == "SECOND" else r"\.\d{9}"
    match = re.fullmatch(rf"(\d{{4}})-(\d{{2}})-(\d{{2}})T(\d{{2}}):(\d{{2}}):(\d{{2}}){suffix}Z", value)
    if match is None:
        return False
    year, month, day, hour, minute, second = map(int, match.groups()[:6])
    if hour > 23 or minute > 59 or second > 59:
        return False
    try:
        datetime.date(year, month, day)
    except ValueError:
        return False
    return True


def actual(case: dict) -> dict:
    if case["operation"] == "boundary":
        return {
            "status": "CLOSED_DOCUMENTED_BOUNDARY",
            "boundary_digest": digest("boundary", case["input"]),
            "does_not_establish_external_truth": True,
        }
    kind = case["input"]["kind"]
    if kind == "OCCURRENCE_IDENTITY":
        values = [digest("occurrence", subject) for subject in case["input"]["subjects"]]
        return {"relation": "DISTINCT" if len(set(values)) == len(values) else "EQUAL", "digests": values}
    if kind == "OBLIGATION_IDENTITY":
        return {"digest": digest("obligation", case["input"]["subject"])}
    if kind == "STATE_CORE_MUTATION":
        before = state_core_digest(case["input"]["before"])
        after = state_core_digest(case["input"]["after"])
        return {"relation": "DISTINCT" if before != after else "EQUAL", "before_digest": before, "after_digest": after}
    if kind == "STATE_RECORD_MUTATION":
        before_state = state_digest(case["input"]["before"])
        after_state = state_digest(case["input"]["after"])
        before_core = state_core_digest(case["input"]["before"])
        after_core = state_core_digest(case["input"]["after"])
        return {
            "full_state_relation": "DISTINCT" if before_state != after_state else "EQUAL",
            "state_core_relation": "DISTINCT" if before_core != after_core else "EQUAL",
            "before_state_digest": before_state,
            "after_state_digest": after_state,
            "before_core_digest": before_core,
            "after_core_digest": after_core,
        }
    if kind in {"LIFECYCLE_RESERVATION_INSTANCE", "LIFECYCLE_RESERVATION_EVENT_KIND"}:
        values = [digest("lifecycle-reservation-event", subject) for subject in case["input"]["subjects"]]
        return {"relation": "DISTINCT" if len(set(values)) == len(values) else "EQUAL", "digests": values}
    if kind == "READBACK_POINTER_ORDER":
        return {
            "lines": sorted(
                readback_lines(case["input"]["value"]),
                key=lambda row: row["path"].encode("utf-8"),
            )
        }
    if kind == "UNICODE_NO_NORMALIZATION":
        values = case["input"]["values"]
        digests = [digest("canonicalization-property", value) for value in values]
        return {
            "canonical_bytes_base64": [base64.b64encode(canonical_bytes(value)).decode("ascii") for value in values],
            "digests": digests,
            "relation": "DISTINCT" if len(set(digests)) == len(digests) else "EQUAL",
        }
    if kind == "TIMESTAMP_GRAMMAR":
        accepted = []
        rejected = []
        for value in case["input"]["values"]:
            (accepted if valid_timestamp(value, case["input"]["precision"]) else rejected).append(value)
        return {"accepted": accepted, "rejected": rejected}
    raise ValueError(f"unsupported vector kind {kind}")


def main() -> int:
    failures = []
    files = []
    for path in sorted((ROOT / "cases").rglob("*.json")):
        if path.name == "index.json":
            continue
        case = json.loads(path.read_text())
        if case["operation"] in {"validate vectors", "property", "boundary"}:
            files.append(path)
    for path in files:
        case = json.loads(path.read_text())
        observed = actual(case)
        if canonical_bytes(observed) != canonical_bytes(case["expected"]):
            failures.append({"id": case["id"], "expected": case["expected"], "actual": observed})
    print(json.dumps({"status": "PASS" if not failures else "FAIL", "cases": len(files), "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
