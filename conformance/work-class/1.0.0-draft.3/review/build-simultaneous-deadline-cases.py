#!/usr/bin/env python3
"""Build simultaneous parallel-deadline expiry vectors."""

from __future__ import annotations

import copy
import json

from composition_fixture import add_authority_operations, parallel_definition, parallel_entry_result
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    permitted_proposal,
    step_input,
)


GROUP = CASES / "simultaneous-deadlines"


def deadline_parallel(
    branches: list[str],
    *,
    stop_branch: str | None = None,
    later_branch: str | None = None,
):
    parallel = parallel_definition(branches)

    def mutate(definition: dict) -> None:
        parallel(definition)
        definition["profile"] = "PARALLEL_FANOUT"
        definition["deadlines"] = [
            {
                "id": step_id + "-deadline",
                "step_id": step_id,
                "clock_source": "work-clock",
                "due": {
                    "kind": "ABSOLUTE_INSTANT",
                    "instant": "2026-09-10T04:32:00Z" if step_id == later_branch else "2026-09-10T04:31:00Z",
                },
                "boundary": "AT_OR_AFTER",
                "expiry_target": None if step_id == stop_branch else "parallel-join",
            }
            for step_id in branches
        ]
        definition["relationships"].extend(
            {
                "kind": "EXPIRY",
                "from": step_id,
                "to": "parallel-join",
                "deadline_ref": step_id + "-deadline",
            }
            for step_id in branches
            if step_id != stop_branch
        )
        definition["relationships"].sort(key=canonical_bytes)

    return mutate


def setup(
    branches: list[str],
    suffix: str,
    *,
    stop_branch: str | None = None,
    later_branch: str | None = None,
) -> tuple[dict, dict]:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(branches),
        definition_mutator=deadline_parallel(branches, stop_branch=stop_branch, later_branch=later_branch),
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-before-" + suffix, acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    activation_clock = available_clock("work-clock", "1", "2026-09-10T04:30:00Z")
    clock_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-before-" + suffix,
        "kind": "CLOCK",
        "instance_id": dispatched["state"]["instance_id"],
        "expected_state_revision": dispatched["state"]["revision"],
        "expected_state_digest": dispatched["state_digest"],
        "clock": activation_clock,
        "activation_clocks": [],
    }

    def retain_clock(state: dict) -> None:
        state["clocks"].append(copy.deepcopy(activation_clock))
        state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    clocked = admitted_transition(
        dispatched["state"],
        clock_event,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[
            {"kind": "CLOCK", "source": activation_clock["source"], "revision": activation_clock["revision"], "status": activation_clock["status"]}
        ],
        mutate=retain_clock,
    )
    evidence = governed_native_evidence(
        base,
        permitted,
        clocked,
        evidence_id="evidence-entry-" + suffix,
        native_operation_id="native-operation-entry-" + suffix,
    )
    effect = governed_effect_event(permitted, clocked, evidence, event_id="effect-entry-" + suffix)
    effect["activation_clocks"] = [copy.deepcopy(activation_clock)]
    return base, parallel_entry_result(base, clocked, effect, branches, install_deadlines=True)


def expiry_result(base: dict, state: dict, event: dict, branches: list[str]) -> dict:
    selected_clock = event["clock"]
    event_digest = digest("runtime-event", event)
    due_rows = sorted(
        [
            (
                next(row for row in state["active"] if row["occurrence"]["step_id"] == step_id)["occurrence"],
                next(row for row in base["definition"]["relationships"] if row["kind"] == "EXPIRY" and row["from"] == step_id),
            )
            for step_id in branches
        ],
        key=lambda pair: canonical_bytes(pair[0]),
    )
    relationship_digests = [digest("relationship", relationship) for _occurrence, relationship in due_rows]
    join_relationship = next(
        row for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == "parallel-join"
    )
    relationship_digests.append(digest("relationship", join_relationship))
    relationship_digests.sort(key=lambda value: value.encode("utf-8"))

    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(selected_clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        due_ids = {occurrence["occurrence_id"] for occurrence, _relationship in due_rows}
        next_state["active"] = [
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] not in due_ids
        ]
        for occurrence_value, relationship in due_rows:
            evidence_digest = selected_clock["evidence_digest"]
            next_state["completed"].append(
                {
                    "occurrence": copy.deepcopy(occurrence_value),
                    "disposition": "EXPIRED",
                    "evidence_digest": evidence_digest,
                    "occurred_at": selected_clock["observed_time"],
                    "route_label": None,
                    "selected_relationship_digest": digest("relationship", relationship),
                    "late": False,
                }
            )
            deadline = next(
                row for row in next_state["deadlines"]
                if row["occurrence_id"] == occurrence_value["occurrence_id"]
            )
            deadline["status"] = "EXPIRED"
            deadline["expiry_event_digest"] = event_digest
            obligation = next(
                row for row in next_state["obligations"]
                if row["expected_occurrence_id"] == occurrence_value["occurrence_id"]
            )
            operation = obligation["required_operation"]
            obligation["status"] = "DISCHARGED"
            obligation["expected_occurrence_id"] = None
            obligation["required_operation"] = None
            obligation["completion_basis"] = {
                "kind": "DIRECT_EVENT",
                "event_digest": event_digest,
                "occurrence_id": occurrence_value["occurrence_id"],
                "operation": operation,
                "evidence_digest": evidence_digest,
            }
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        for obligation in next_state["obligations"]:
            if obligation["construct_id"] == "parallel-1" and obligation["pass"] == "1":
                obligation["status"] = "JOINED"
        next_state["status"] = "COMPLETE"

    return admitted_transition(
        state,
        event,
        disposition="EXPIRED",
        reason_codes=[],
        details=[
            {"kind": "CLOCK", "source": selected_clock["source"], "revision": selected_clock["revision"], "status": selected_clock["status"]},
            {"kind": "DEADLINE", "deadline_ids": sorted((step + "-deadline" for step in branches), key=lambda value: value.encode("utf-8")), "reasons": []},
            {"kind": "ROUTE", "relationship_digests": relationship_digests, "construct_ids": ["parallel-1"]},
        ],
        mutate=mutate,
    )


def stopped_expiry_result(base: dict, state: dict, event: dict, due_branches: list[str]) -> dict:
    selected_clock = event["clock"]
    event_digest = digest("runtime-event", event)
    due_occurrences = sorted(
        [
            next(row["occurrence"] for row in state["active"] if row["occurrence"]["step_id"] == step_id)
            for step_id in due_branches
        ],
        key=canonical_bytes,
    )

    def mutate(next_state: dict) -> None:
        next_state["status"] = "STOPPED"
        next_state["clocks"].append(copy.deepcopy(selected_clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        due_ids = {row["occurrence_id"] for row in due_occurrences}
        next_state["active"] = [
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] not in due_ids
        ]
        for occurrence_value in due_occurrences:
            expiry_relationship = next(
                (
                    row
                    for row in base["definition"]["relationships"]
                    if row["kind"] == "EXPIRY" and row["from"] == occurrence_value["step_id"]
                ),
                None,
            )
            next_state["completed"].append(
                {
                    "occurrence": copy.deepcopy(occurrence_value),
                    "disposition": "EXPIRED",
                    "evidence_digest": selected_clock["evidence_digest"],
                    "occurred_at": selected_clock["observed_time"],
                    "route_label": None,
                    "selected_relationship_digest": (
                        digest("relationship", expiry_relationship)
                        if expiry_relationship is not None
                        else None
                    ),
                    "late": False,
                }
            )
            deadline = next(
                row for row in next_state["deadlines"]
                if row["occurrence_id"] == occurrence_value["occurrence_id"]
            )
            deadline["status"] = "EXPIRED"
            deadline["expiry_event_digest"] = event_digest
            obligation = next(
                row for row in next_state["obligations"]
                if row["expected_occurrence_id"] == occurrence_value["occurrence_id"]
            )
            operation = obligation["required_operation"]
            obligation["status"] = "DISCHARGED"
            obligation["expected_occurrence_id"] = None
            obligation["required_operation"] = None
            obligation["completion_basis"] = {
                "kind": "DIRECT_EVENT",
                "event_digest": event_digest,
                "occurrence_id": occurrence_value["occurrence_id"],
                "operation": operation,
                "evidence_digest": selected_clock["evidence_digest"],
            }
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))

    return admitted_transition(
        state,
        event,
        disposition="STOPPED",
        reason_codes=["EXPIRY_STOP"],
        details=[
            {"kind": "CLOCK", "source": selected_clock["source"], "revision": selected_clock["revision"], "status": selected_clock["status"]},
            {
                "kind": "DEADLINE",
                "deadline_ids": sorted((step + "-deadline" for step in due_branches), key=lambda value: value.encode("utf-8")),
                "reasons": ["EXPIRY_STOP"],
            },
        ],
        mutate=mutate,
    )


def build_case(case_id: str, branches: list[str], derivation: str) -> None:
    base, entered = setup(branches, case_id.lower())
    clock = available_clock("work-clock", "2", "2026-09-10T04:31:00Z")
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-" + case_id.lower(),
        "kind": "CLOCK",
        "instance_id": entered["state"]["instance_id"],
        "expected_state_revision": entered["state"]["revision"],
        "expected_state_digest": entered["state_digest"],
        "clock": clock,
        "activation_clocks": [],
    }
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(
            case_id,
            "step",
            step_input(base, entered["state"], event),
            expiry_result(base, entered["state"], event, branches),
            [],
            derivation,
        ),
    )


def build_stop_case(
    case_id: str,
    branches: list[str],
    due_branches: list[str],
    derivation: str,
    *,
    later_branch: str | None = None,
) -> None:
    base, entered = setup(
        branches,
        case_id.lower(),
        stop_branch=due_branches[0],
        later_branch=later_branch,
    )
    clock = available_clock("work-clock", "2", "2026-09-10T04:31:00Z")
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-" + case_id.lower(),
        "kind": "CLOCK",
        "instance_id": entered["state"]["instance_id"],
        "expected_state_revision": entered["state"]["revision"],
        "expected_state_digest": entered["state_digest"],
        "clock": clock,
        "activation_clocks": [],
    }
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(
            case_id,
            "step",
            step_input(base, entered["state"], event),
            stopped_expiry_result(base, entered["state"], event, due_branches),
            [],
            derivation,
        ),
    )


def main() -> None:
    build_case(
        "D2-073",
        ["branch-a", "branch-b", "branch-c"],
        "One accepted work-clock sample satisfies the equal due instant of three active branch occurrences. The due set is ordered by canonical occurrence bytes. All three exact expiry relationships reach the parallel join; the transition marks all deadlines EXPIRED, discharges all three obligations, joins the pass, follows the join-to-terminal relationship, and completes the instance atomically.",
    )
    build_case(
        "D2-144",
        ["branch-a", "branch-b"],
        "One accepted work-clock sample satisfies both parallel branch deadlines at equality. Each occurrence closes as EXPIRED through its declared expiry relationship, both direct obligations discharge, the complete pass joins, and the join-to-terminal relationship completes the instance in the same transition.",
    )
    build_case(
        "D2-109",
        ["branch-a", "branch-b"],
        "Both active branch deadlines become due on the same accepted clock sample and both expiry relationships select the same parallel join. Union preflight succeeds, so one transition closes both occurrences, discharges both obligations, joins the complete pass and reaches terminal without an order-dependent intermediate state.",
    )
    build_stop_case(
        "D2-110",
        ["branch-a", "branch-b"],
        ["branch-a", "branch-b"],
        "The accepted clock makes both sibling deadlines due, and branch-a declares an explicit expiry stop. The transition retains the complete ordered due set, closes and discharges both eligible branch occurrences, creates no expiry successor, does not fire the join, and stops the instance with EXPIRY_STOP.",
    )
    build_stop_case(
        "D2-209",
        ["branch-a", "branch-b", "branch-c"],
        ["branch-a", "branch-b"],
        "The accepted clock makes branch-a and branch-b due while branch-c remains pending. Branch-a's explicit expiry stop causes union preflight to retain and close both due occurrences without applying either structural closure. Their obligations discharge, branch-c and its obligation remain active and open, no join fires, and the instance stops.",
        later_branch="branch-c",
    )
    print(json.dumps({"case_ids": ["D2-073", "D2-109", "D2-110", "D2-144", "D2-209"]}, indent=2))


if __name__ == "__main__":
    main()
