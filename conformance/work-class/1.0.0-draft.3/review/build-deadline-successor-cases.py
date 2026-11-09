#!/usr/bin/env python3
"""Build expiry closures that activate deadline-bearing successors."""

from __future__ import annotations

import copy
import json

from composition_fixture import add_authority_operations
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock, occurrence
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    governed_outcome,
    permitted_proposal,
    step_input,
)


GROUP = CASES / "deadline-successors"


def definition(definition_value: dict) -> None:
    definition_value["profile"] = "DEADLINES"
    definition_value["relationships"] = [
        {"kind": "SEQUENCE", "from": "issue", "to": "terminal"},
        {"kind": "SEQUENCE", "from": "successor", "to": "terminal"},
        {"kind": "EXPIRY", "from": "issue", "to": "successor", "deadline_ref": "issue-deadline"},
        {"kind": "EXPIRY", "from": "successor", "to": "terminal", "deadline_ref": "successor-deadline"},
    ]
    definition_value["relationships"].sort(key=canonical_bytes)
    definition_value["deadlines"] = [
        {
            "id": "issue-deadline",
            "step_id": "issue",
            "clock_source": "work-clock",
            "due": {"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-10T04:31:00Z"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "successor",
        },
        {
            "id": "successor-deadline",
            "step_id": "successor",
            "clock_source": "work-clock",
            "due": {"kind": "ELAPSED_DURATION", "value": "60", "unit": "SECOND"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "terminal",
        },
    ]


def overflow_definition(definition_value: dict) -> None:
    definition_value["profile"] = "DEADLINES"
    definition_value["relationships"] = [
        {"kind": "SEQUENCE", "from": "issue", "to": "successor"},
        {"kind": "SEQUENCE", "from": "successor", "to": "terminal"},
        {"kind": "EXPIRY", "from": "successor", "to": "terminal", "deadline_ref": "successor-deadline"},
    ]
    definition_value["relationships"].sort(key=canonical_bytes)
    definition_value["deadlines"] = [
        {
            "id": "successor-deadline",
            "step_id": "successor",
            "clock_source": "deadline-clock",
            "due": {"kind": "ELAPSED_DURATION", "value": "1", "unit": "SECOND"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "terminal",
        }
    ]


def overflow_expected(base: dict, state: dict, event: dict) -> dict:
    root = event["permit"]["occurrence"]
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, {"state": state}, classification="MATCHED", disputed=False)
    relationship = next(
        row for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == root["step_id"]
    )
    relationship_digest = digest("relationship", relationship)

    def mutate(next_state: dict) -> None:
        next_state["status"] = "STOPPED"
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        next_state["active"] = [
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] != root["occurrence_id"]
        ]
        next_state["completed"].append(
            {
                "occurrence": copy.deepcopy(root),
                "disposition": "SUCCEEDED",
                "evidence_digest": evidence_digest,
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": relationship_digest,
                "late": False,
            }
        )
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))

    return admitted_transition(
        state,
        event,
        disposition="STOPPED",
        reason_codes=["DEADLINE_TIME_OVERFLOW"],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
            {"kind": "DEADLINE", "deadline_ids": ["successor-deadline"], "reasons": ["DEADLINE_TIME_OVERFLOW"]},
            {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []},
        ],
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def expected(base: dict, state: dict, event: dict) -> dict:
    selected_clock = event["clock"]
    event_digest = digest("runtime-event", event)
    root = next(row["occurrence"] for row in state["active"] if row["occurrence"]["step_id"] == "issue")
    expiry = next(
        row for row in base["definition"]["relationships"]
        if row["kind"] == "EXPIRY" and row["from"] == "issue"
    )
    expiry_digest = digest("relationship", expiry)
    successor = occurrence(
        base["definition_digest"],
        state["instance_id"],
        "successor",
        "1",
        [root["occurrence_id"]],
        [],
    )

    def mutate(next_state: dict) -> None:
        next_revision = str(int(state["revision"]) + 1)
        next_state["clocks"].append(copy.deepcopy(selected_clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        next_state["active"] = [
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] != root["occurrence_id"]
        ]
        next_state["completed"].append(
            {
                "occurrence": copy.deepcopy(root),
                "disposition": "EXPIRED",
                "evidence_digest": selected_clock["evidence_digest"],
                "occurred_at": selected_clock["observed_time"],
                "route_label": None,
                "selected_relationship_digest": expiry_digest,
                "late": False,
            }
        )
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        root_deadline = next(row for row in next_state["deadlines"] if row["deadline_id"] == "issue-deadline")
        root_deadline["status"] = "EXPIRED"
        root_deadline["expiry_event_digest"] = event_digest
        activation_subject = {
            "deadline_id": "successor-deadline",
            "occurrence_id": successor["occurrence_id"],
            "trigger_digest": event_digest,
            "source": selected_clock["source"],
            "activation_revision": next_revision,
            "activation_clock_revision": selected_clock["revision"],
            "activation_instant": selected_clock["observed_time"],
            "activation_clock_evidence_digest": selected_clock["evidence_digest"],
            "due": "2026-09-10T04:32:00Z",
            "boundary": "AT_OR_AFTER",
        }
        next_state["deadlines"].append(
            {
                "activation_digest": digest("deadline-activation", activation_subject),
                **activation_subject,
                "status": "PENDING",
                "expiry_event_digest": None,
            }
        )
        next_state["deadlines"].sort(
            key=lambda row: (
                row["due"].encode("utf-8"),
                canonical_bytes(root if row["occurrence_id"] == root["occurrence_id"] else successor),
                row["deadline_id"].encode("utf-8"),
            )
        )
        next_state["active"].append(
            {
                "occurrence": copy.deepcopy(successor),
                "activation_event_digest": event_digest,
                "status": "ACTIVE",
                "deadline_ids": ["successor-deadline"],
            }
        )
        next_state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        counter = next(row for row in next_state["step_counters"] if row["step_id"] == "successor")
        counter["activations"] = str(int(counter["activations"]) + 1)
        next_state["total_activations"] = str(int(next_state["total_activations"]) + 1)

    return admitted_transition(
        state,
        event,
        disposition="EXPIRED",
        reason_codes=[],
        details=[
            {"kind": "CLOCK", "source": selected_clock["source"], "revision": selected_clock["revision"], "status": selected_clock["status"]},
            {"kind": "DEADLINE", "deadline_ids": ["issue-deadline"], "reasons": []},
            {"kind": "ROUTE", "relationship_digests": [expiry_digest], "construct_ids": []},
        ],
        mutate=mutate,
    )


def main() -> None:
    initial_clock = available_clock("work-clock", "1", "2026-09-10T04:30:00Z")
    base = base_lifecycle(
        authority_mutator=add_authority_operations(["successor"]),
        definition_mutator=definition,
        initial_clocks=[initial_clock],
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-before-d2-139", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    next_clock = available_clock("work-clock", "2", "2026-09-10T04:31:00Z")
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-d2-139",
        "kind": "CLOCK",
        "instance_id": dispatched["state"]["instance_id"],
        "expected_state_revision": dispatched["state"]["revision"],
        "expected_state_digest": dispatched["state_digest"],
        "clock": next_clock,
        "activation_clocks": [copy.deepcopy(next_clock)],
    }
    write_canonical_json(
        GROUP / "D2-139.json",
        exact_case(
            "D2-139",
            "step",
            step_input(base, dispatched["state"], event),
            expected(base, dispatched["state"], event),
            [],
            "The accepted work-clock sample reaches the root deadline at its AT_OR_AFTER boundary. Its expiry relationship activates successor. Because successor has an elapsed deadline on the same source, activation_clocks contains the just accepted sample. The transition closes the root as EXPIRED, creates successor once, and persists successor-deadline due 60 seconds after that accepted clock.",
        ),
    )

    overflow = base_lifecycle(
        authority_mutator=add_authority_operations(["successor"]),
        definition_mutator=overflow_definition,
    )
    permitted = permitted_proposal(overflow)
    dispatch = dispatch_event(overflow, permitted, event_id="dispatch-before-d2-157", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    activation_clock = available_clock("deadline-clock", "1", "9999-12-31T23:59:59Z")
    clock_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-before-d2-157",
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
        overflow,
        permitted,
        clocked,
        evidence_id="evidence-d2-157",
        native_operation_id="native-operation-d2-157",
    )
    effect = governed_effect_event(permitted, clocked, evidence, event_id="effect-d2-157")
    effect["activation_clocks"] = [copy.deepcopy(activation_clock)]
    write_canonical_json(
        GROUP / "D2-157.json",
        exact_case(
            "D2-157",
            "step",
            step_input(overflow, clocked["state"], effect),
            overflow_expected(overflow, clocked["state"], effect),
            [],
            "The matching root effect selects successor, whose elapsed one-second deadline must use the latest retained deadline-clock sample at 9999-12-31T23:59:59Z. Adding the declared duration would exceed year 9999. The effect and selected route are retained, the root closes, no successor or deadline state is created, and the instance stops with DEADLINE_TIME_OVERFLOW.",
        ),
    )
    print(json.dumps({"case_ids": ["D2-139", "D2-157"]}, indent=2))


if __name__ == "__main__":
    main()
