#!/usr/bin/env python3
"""Check ordering, canonical bytes, and digest constructions in closure batch 1."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
REVIEW = CANDIDATE / "review"
sys.path.insert(0, str(REVIEW))
from corpus_common import canonical_bytes, candidate_pin, digest, raw_sha256  # noqa: E402


INDEX = HERE / "exact-vector-closure-batch-1.json"
WORK_STATE_SCHEMA = "seampoint.work-class/1.0.0-draft.2/work-state"


def state_identity(state: dict) -> dict:
    projected = copy.deepcopy(state)
    for replay in projected["replays"]:
        replay.pop("transaction_digest", None)
    return projected


def state_digest(state: dict) -> str:
    return digest("work-state", state_identity(state))


def state_core_digest(state: dict) -> str:
    projected = copy.deepcopy(state)
    projected["receipts"] = []
    projected["replays"] = []
    return digest("work-state-core", projected)


def occurrence_for(state: dict, occurrence_id: str) -> dict:
    return next(
        row["occurrence"]
        for row in state["active"] + state["completed"]
        if row["occurrence"]["occurrence_id"] == occurrence_id
    )


def ordered_state(state: dict) -> list[str]:
    failures = []
    checks = [
        ("active", lambda row: canonical_bytes(row["occurrence"])),
        ("completed", lambda row: canonical_bytes(row["occurrence"])),
        ("obligations", lambda row: row["obligation_id"].encode("utf-8")),
        ("proposals", lambda row: row["event_id"].encode("utf-8")),
        ("permits", lambda row: row["permit_id"].encode("utf-8")),
        ("dispatches", lambda row: row["dispatch_digest"].encode("utf-8")),
        ("outcomes", lambda row: row["outcome_digest"].encode("utf-8")),
        ("clocks", lambda row: (row["source"].encode("utf-8"), int(row["revision"]))),
        (
            "deadlines",
            lambda row: (
                row["due"].encode("utf-8"),
                canonical_bytes(occurrence_for(state, row["occurrence_id"])),
                row["deadline_id"].encode("utf-8"),
            ),
        ),
        (
            "fanout_passes",
            lambda row: (
                row["fanout_id"].encode("utf-8"),
                int(row["pass"]),
                row["expand_occurrence_id"].encode("utf-8"),
            ),
        ),
        ("receipts", lambda row: int(row["sequence"])),
        ("replays", lambda row: row["event_id"].encode("utf-8")),
    ]
    for name, key in checks:
        if state[name] != sorted(state[name], key=key):
            failures.append(name)
    return failures


def walk(value, visit) -> None:
    if isinstance(value, dict):
        visit(value)
        for member in value.values():
            walk(member, visit)
    elif isinstance(value, list):
        for member in value:
            walk(member, visit)


def check_success(case_id: str, case: dict, failures: list[str]) -> None:
    request = case["input"]
    expected = case["expected"]
    before = request["state"]
    after = expected["state"]
    event = request["event"]
    replay = expected["replay"]
    expected_revision = int(before["revision"]) if replay else int(before["revision"]) + 1
    if int(after["revision"]) != expected_revision:
        failures.append(f"{case_id}: result revision")
    if expected["state_digest"] != state_digest(after):
        failures.append(f"{case_id}: result state digest")
    decision = expected["decision"]
    decision_subject = {key: value for key, value in decision.items() if key != "decision_id"}
    if expected["decision_digest"] != digest("decision-receipt", decision_subject):
        failures.append(f"{case_id}: result decision digest")
    if decision["event_digest"] != digest("runtime-event", event):
        failures.append(f"{case_id}: decision event digest")
    if not replay:
        if decision["state_before_digest"] != state_digest(before):
            failures.append(f"{case_id}: decision state-before digest")
        if decision["state_after_core_digest"] != state_core_digest(after):
            failures.append(f"{case_id}: decision next-core digest")
        if expected["transition_state_digest"] != state_core_digest(after):
            failures.append(f"{case_id}: transition-state digest")
        transaction_subject = {
            "state_before_digest": decision["state_before_digest"],
            "event_digest": decision["event_digest"],
            "decision_receipt_digest": decision["decision_id"],
            "state_after_core_digest": decision["state_after_core_digest"],
            "budget_results": expected["budget_results"],
        }
        if expected["transaction_digest"] != digest("lifecycle-transaction", transaction_subject):
            failures.append(f"{case_id}: transaction digest")
    if expected["permit"] is not None:
        permit_subject = {key: value for key, value in expected["permit"].items() if key != "permit_id"}
        if expected["permit"]["permit_id"] != digest("permit", permit_subject):
            failures.append(f"{case_id}: result permit digest")


def main() -> int:
    metadata = json.loads(INDEX.read_text())
    failures: list[str] = []
    states_checked = 0
    if metadata["candidate_pin"] != candidate_pin():
        failures.append("runner metadata candidate pin")
    for row in metadata["cases"]:
        path = CANDIDATE / row["path"]
        raw = path.read_bytes()
        case = json.loads(raw)
        if raw != canonical_bytes(case) + b"\n":
            failures.append(f"{case['id']}: noncanonical case bytes")
        if row["sha256"] != raw_sha256(path):
            failures.append(f"{case['id']}: runner metadata case hash")
        if case["id"] != row["id"]:
            failures.append(f"{row['id']}: case identity")
        request = case["input"]
        expected = case["expected"]
        if request["specification_pin"] != candidate_pin():
            failures.append(f"{case['id']}: request candidate pin")
        if request["definition_digest"] != digest("work-class-definition", request["definition"]):
            failures.append(f"{case['id']}: definition digest")
        if request["state_digest"] != state_digest(request["state"]):
            failures.append(f"{case['id']}: request state digest")
        if not expected.get("replay", False) and request["event"]["expected_state_digest"] != request["state_digest"]:
            failures.append(f"{case['id']}: event expected-state digest")
        if request["event"]["instance_id"] != request["state"]["instance_id"]:
            failures.append(f"{case['id']}: event instance binding")

        def visit(value: dict) -> None:
            nonlocal states_checked
            if "specification_pin" in value and value["specification_pin"] != candidate_pin():
                failures.append(f"{case['id']}: nested candidate pin")
            if value.get("schema") == WORK_STATE_SCHEMA:
                states_checked += 1
                for collection in ordered_state(value):
                    failures.append(f"{case['id']}: unsorted work-state {collection}")

        walk(case, visit)
        if expected["status"] == "REFUSED":
            if expected["state"] != request["state"]:
                failures.append(f"{case['id']}: refusal changed state")
            if expected["state_digest"] != request["state_digest"]:
                failures.append(f"{case['id']}: refusal state digest")
            if expected["budget_states"]:
                failures.append(f"{case['id']}: unexpected refusal budget state")
        else:
            check_success(case["id"], case, failures)
    result = {
        "status": "PASS" if not failures else "FAIL",
        "cases": metadata["count"],
        "work_states_checked": str(states_checked),
        "failures": failures,
    }
    print(json.dumps(result, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
