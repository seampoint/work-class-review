#!/usr/bin/env python3
"""Build exact parallel obligation discharge and join vectors."""

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
    state_digest,
    step_input,
)


GROUP = CASES / "parallel-completion"
BRANCHES = ["branch-a", "branch-b"]


def definition_mutator(definition: dict) -> None:
    parallel_definition(BRANCHES)(definition)
    definition["deadlines"] = [
        {
            "id": "deadline-a",
            "step_id": "branch-a",
            "clock_source": "authority-clock",
            "due": {"kind": "ELAPSED_DURATION", "value": "1", "unit": "MINUTE"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "parallel-join",
        },
        {
            "id": "deadline-b",
            "step_id": "branch-b",
            "clock_source": "authority-clock",
            "due": {"kind": "ELAPSED_DURATION", "value": "2", "unit": "MINUTE"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "parallel-join",
        },
    ]
    definition["relationships"].extend(
        [
            {"kind": "EXPIRY", "from": "branch-a", "to": "parallel-join", "deadline_ref": "deadline-a"},
            {"kind": "EXPIRY", "from": "branch-b", "to": "parallel-join", "deadline_ref": "deadline-b"},
        ]
    )


def setup() -> tuple[dict, dict]:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(BRANCHES),
        definition_mutator=definition_mutator,
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-before-parallel", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-parallel-entry")
    effect = governed_effect_event(permitted, dispatched, evidence, event_id="effect-parallel-entry")
    effect["activation_clocks"] = [copy.deepcopy(base["clock_result"]["state"]["clocks"][0])]
    entry = parallel_entry_result(base, dispatched, effect, BRANCHES, install_deadlines=True)
    return base, entry


def clock_event(state: dict, *, event_id: str, revision: str, observed_time: str) -> dict:
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "CLOCK",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "clock": available_clock("authority-clock", revision, observed_time),
        "activation_clocks": [],
    }


def expiration_result(base: dict, state: dict, event: dict, *, deadline_id: str, final_join: bool) -> dict:
    deadline = next(row for row in state["deadlines"] if row["deadline_id"] == deadline_id)
    active = next(row for row in state["active"] if row["occurrence"]["occurrence_id"] == deadline["occurrence_id"])
    occurrence = active["occurrence"]
    expiry_relationship = next(
        row for row in base["definition"]["relationships"]
        if row["kind"] == "EXPIRY" and row["deadline_ref"] == deadline_id
    )
    expiry_digest = digest("relationship", expiry_relationship)
    relationship_digests = [expiry_digest]
    if final_join:
        join_relationship = next(
            row for row in base["definition"]["relationships"]
            if row["kind"] == "SEQUENCE" and row["from"] == "parallel-join"
        )
        relationship_digests.append(digest("relationship", join_relationship))
    relationship_digests.sort(key=lambda value: value.encode("utf-8"))
    event_digest = digest("runtime-event", event)

    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(event["clock"]))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        next_state["active"] = [
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] != occurrence["occurrence_id"]
        ]
        next_state["completed"].append(
            {
                "occurrence": copy.deepcopy(occurrence),
                "disposition": "EXPIRED",
                "evidence_digest": event["clock"]["evidence_digest"],
                "occurred_at": event["clock"]["observed_time"],
                "route_label": None,
                "selected_relationship_digest": expiry_digest,
                "late": False,
            }
        )
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        target_deadline = next(row for row in next_state["deadlines"] if row["deadline_id"] == deadline_id)
        target_deadline["status"] = "EXPIRED"
        target_deadline["expiry_event_digest"] = event_digest
        obligation = next(
            row for row in next_state["obligations"]
            if row["expected_occurrence_id"] == occurrence["occurrence_id"]
        )
        obligation["status"] = "DISCHARGED"
        obligation["expected_occurrence_id"] = None
        obligation["required_operation"] = None
        obligation["completion_basis"] = {
            "kind": "DIRECT_EVENT",
            "event_digest": event_digest,
            "occurrence_id": occurrence["occurrence_id"],
            "operation": next(
                row["operation"] for row in base["definition"]["steps"]
                if row["id"] == occurrence["step_id"]
            ),
            "evidence_digest": event["clock"]["evidence_digest"],
        }
        if final_join:
            for row in next_state["obligations"]:
                row["status"] = "JOINED"
            next_state["status"] = "COMPLETE"

    return admitted_transition(
        state,
        event,
        disposition="EXPIRED",
        reason_codes=[],
        details=[
            {
                "kind": "CLOCK",
                "source": event["clock"]["source"],
                "revision": event["clock"]["revision"],
                "status": event["clock"]["status"],
            },
            {"kind": "DEADLINE", "deadline_ids": [deadline_id], "reasons": []},
            {"kind": "ROUTE", "relationship_digests": relationship_digests, "construct_ids": ["parallel-1"]},
        ],
        mutate=mutate,
    )


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def main() -> None:
    base, entry = setup()
    first_clock = clock_event(
        entry["state"],
        event_id="clock-d2-052",
        revision="2",
        observed_time="2026-09-10T04:31:00Z",
    )
    first_expiry = expiration_result(base, entry["state"], first_clock, deadline_id="deadline-a", final_join=False)
    emit(
        "D2-052",
        base,
        entry["state"],
        first_clock,
        first_expiry,
        "The accepted clock reaches deadline-a but not deadline-b. The transition closes branch-a as expired and changes its exact obligation to DISCHARGED with a direct clock-event basis. Branch-b and its obligation remain active and open, so parallel-1 cannot join and the instance remains active.",
    )

    second_clock = clock_event(
        first_expiry["state"],
        event_id="clock-d2-053",
        revision="3",
        observed_time="2026-09-10T04:32:00Z",
    )
    final_expiry = expiration_result(base, first_expiry["state"], second_clock, deadline_id="deadline-b", final_join=True)
    emit(
        "D2-053",
        base,
        first_expiry["state"],
        second_clock,
        final_expiry,
        "The later accepted clock reaches deadline-b after branch-a's exact obligation is already discharged. This transition discharges branch-b, observes that the complete immutable obligation inventory is now discharged, marks both obligations JOINED, traverses the join-to-terminal relationship and completes the instance.",
    )

    print(json.dumps({"case_ids": ["D2-052", "D2-053"]}, indent=2))


if __name__ == "__main__":
    main()
