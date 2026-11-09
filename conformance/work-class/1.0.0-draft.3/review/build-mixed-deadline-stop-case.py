#!/usr/bin/env python3
"""Build a simultaneous deadline stop with a second activation failure."""

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


GROUP = CASES / "mixed-deadline-stop"
BRANCHES = ["branch-a", "branch-b"]


def definition(definition_value: dict) -> None:
    parallel_definition(BRANCHES)(definition_value)
    definition_value["deadlines"] = [
        {
            "id": "branch-a-deadline",
            "step_id": "branch-a",
            "clock_source": "work-clock",
            "due": {"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-10T04:31:00Z"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": None,
        },
        {
            "id": "branch-b-deadline",
            "step_id": "branch-b",
            "clock_source": "work-clock",
            "due": {"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-10T04:31:00Z"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "branch-b-successor",
        },
        {
            "id": "branch-b-successor-deadline",
            "step_id": "branch-b-successor",
            "clock_source": "missing-clock",
            "due": {"kind": "ELAPSED_DURATION", "value": "60", "unit": "SECOND"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "parallel-join",
        },
    ]
    definition_value["relationships"].extend(
        [
            {
                "kind": "EXPIRY",
                "from": "branch-b",
                "to": "branch-b-successor",
                "deadline_ref": "branch-b-deadline",
            },
            {"kind": "SEQUENCE", "from": "branch-b-successor", "to": "parallel-join"},
            {
                "kind": "EXPIRY",
                "from": "branch-b-successor",
                "to": "parallel-join",
                "deadline_ref": "branch-b-successor-deadline",
            },
        ]
    )
    definition_value["relationships"].sort(key=canonical_bytes)


def setup() -> tuple[dict, dict]:
    base = base_lifecycle(
        authority_mutator=add_authority_operations([*BRANCHES, "branch-b-successor"]),
        definition_mutator=definition,
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(
        base,
        permitted,
        event_id="dispatch-before-d2-199",
        acknowledgement_status="ACCEPTED",
    )
    dispatched = dispatch_result(
        permitted,
        dispatch,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    activation_clock = available_clock("work-clock", "1", "2026-09-10T04:30:00Z")
    clock_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-before-d2-199",
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
            {
                "kind": "CLOCK",
                "source": activation_clock["source"],
                "revision": activation_clock["revision"],
                "status": activation_clock["status"],
            }
        ],
        mutate=retain_clock,
    )
    evidence = governed_native_evidence(
        base,
        permitted,
        clocked,
        evidence_id="evidence-entry-d2-199",
        native_operation_id="native-operation-entry-d2-199",
    )
    effect = governed_effect_event(
        permitted,
        clocked,
        evidence,
        event_id="effect-entry-d2-199",
    )
    effect["activation_clocks"] = [copy.deepcopy(activation_clock)]
    return base, parallel_entry_result(base, clocked, effect, BRANCHES, install_deadlines=True)


def expected(base: dict, state: dict, event: dict) -> dict:
    selected_clock = event["clock"]
    event_digest = digest("runtime-event", event)
    due = sorted(
        [
            next(row["occurrence"] for row in state["active"] if row["occurrence"]["step_id"] == step_id)
            for step_id in BRANCHES
        ],
        key=canonical_bytes,
    )
    routed_expiry = next(
        row
        for row in base["definition"]["relationships"]
        if row["kind"] == "EXPIRY" and row["from"] == "branch-b"
    )
    routed_expiry_digest = digest("relationship", routed_expiry)

    def mutate(next_state: dict) -> None:
        next_state["status"] = "STOPPED"
        next_state["clocks"].append(copy.deepcopy(selected_clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        due_ids = {row["occurrence_id"] for row in due}
        next_state["active"] = [
            row
            for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] not in due_ids
        ]
        for occurrence_value in due:
            next_state["completed"].append(
                {
                    "occurrence": copy.deepcopy(occurrence_value),
                    "disposition": "EXPIRED",
                    "evidence_digest": selected_clock["evidence_digest"],
                    "occurred_at": selected_clock["observed_time"],
                    "route_label": None,
                    "selected_relationship_digest": (
                        routed_expiry_digest if occurrence_value["step_id"] == "branch-b" else None
                    ),
                    "late": False,
                }
            )
            deadline = next(
                row
                for row in next_state["deadlines"]
                if row["occurrence_id"] == occurrence_value["occurrence_id"]
            )
            deadline["status"] = "EXPIRED"
            deadline["expiry_event_digest"] = event_digest
            obligation = next(
                row
                for row in next_state["obligations"]
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
        reason_codes=["ACTIVATION_CLOCK_UNAVAILABLE", "EXPIRY_STOP"],
        details=[
            {
                "kind": "CLOCK",
                "source": selected_clock["source"],
                "revision": selected_clock["revision"],
                "status": selected_clock["status"],
            },
            {
                "kind": "DEADLINE",
                "deadline_ids": [
                    "branch-a-deadline",
                    "branch-b-deadline",
                    "branch-b-successor-deadline",
                ],
                "reasons": ["ACTIVATION_CLOCK_UNAVAILABLE", "EXPIRY_STOP"],
            },
        ],
        mutate=mutate,
    )


def main() -> None:
    base, entered = setup()
    selected_clock = available_clock("work-clock", "2", "2026-09-10T04:31:00Z")
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-d2-199",
        "kind": "CLOCK",
        "instance_id": entered["state"]["instance_id"],
        "expected_state_revision": entered["state"]["revision"],
        "expected_state_digest": entered["state_digest"],
        "clock": selected_clock,
        "activation_clocks": [],
    }
    write_canonical_json(
        GROUP / "D2-199.json",
        exact_case(
            "D2-199",
            "step",
            step_input(base, entered["state"], event),
            expected(base, entered["state"], event),
            [],
            "The accepted work-clock sample makes both sibling deadlines due. Branch-a declares expiry stop. Branch-b selects branch-b-successor, whose elapsed deadline requires missing-clock, for which no retained available sample exists. Union preflight retains both reasons, closes and discharges both due occurrences, records branch-b's directly selected expiry relationship, creates no successor or join, and stops the instance.",
        ),
    )
    print(json.dumps({"case_ids": ["D2-199"]}, indent=2))


if __name__ == "__main__":
    main()
