#!/usr/bin/env python3
"""Build exact frozen fan-out object completion and join vectors."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

from composition_fixture import permitted_operation_proposal, proposal_for_occurrence
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from lifecycle_factory import (
    admitted_transition,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    governed_outcome,
    step_input,
)


FANOUT = runpy.run_path(str(Path(__file__).with_name("build-fanout-cases.py")))
GROUP = CASES / "fanout-completion"


def object_completion_result(
    base: dict,
    dispatched: dict,
    event: dict,
    *,
    final_join: bool,
) -> dict:
    occurrence_value = event["permit"]["occurrence"]
    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    object_relationship = next(
        row
        for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == occurrence_value["step_id"]
    )
    object_relationship_digest = digest("relationship", object_relationship)
    relationship_digests = [object_relationship_digest]
    if final_join:
        join_relationship = next(
            row
            for row in base["definition"]["relationships"]
            if row["kind"] == "SEQUENCE" and row["from"] == "fanout-join"
        )
        relationship_digests.append(digest("relationship", join_relationship))
    relationship_digests.sort(key=lambda value: value.encode("utf-8"))

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [
            row
            for row in state["active"]
            if row["occurrence"]["occurrence_id"] != occurrence_value["occurrence_id"]
        ]
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(occurrence_value),
                "disposition": "SUCCEEDED",
                "evidence_digest": evidence_digest,
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": object_relationship_digest,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        obligation = next(
            row
            for row in state["obligations"]
            if row["expected_occurrence_id"] == occurrence_value["occurrence_id"]
        )
        obligation["status"] = "DISCHARGED"
        obligation["expected_occurrence_id"] = None
        obligation["required_operation"] = None
        obligation["completion_basis"] = {
            "kind": "DIRECT_EVENT",
            "event_digest": event_digest,
            "occurrence_id": occurrence_value["occurrence_id"],
            "operation": event["permit"]["native_request"]["operation"],
            "evidence_digest": evidence_digest,
        }
        if final_join:
            pass_row = next(
                row
                for row in state["fanout_passes"]
                if row["fanout_id"] == "fanout-1" and row["pass"] == "1"
            )
            pass_row["joined"] = True
            obligation_ids = set(pass_row["obligation_ids"])
            for row in state["obligations"]:
                if row["obligation_id"] in obligation_ids:
                    row["status"] = "JOINED"
            state["status"] = "COMPLETE"

    return admitted_transition(
        dispatched["state"],
        event,
        disposition="COMPLETED",
        reason_codes=[],
        details=[
            {
                "kind": "EFFECT",
                "classification": "MATCHED",
                "evidence_id": event["native_evidence"]["evidence_id"],
            },
            {
                "kind": "ROUTE",
                "relationship_digests": relationship_digests,
                "construct_ids": ["fanout-1"],
            },
        ],
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def execute_object(
    base: dict,
    state: dict,
    occurrence_value: dict,
    *,
    suffix: str,
    final_join: bool,
) -> tuple[dict, dict, dict, dict, dict, dict]:
    proposal, authority_result = proposal_for_occurrence(
        base,
        state,
        occurrence_value,
        event_id="proposal-" + suffix,
    )
    permitted = permitted_operation_proposal(base, state, proposal, authority_result)
    dispatch = dispatch_event(
        base,
        permitted,
        event_id="dispatch-" + suffix,
        acknowledgement_status="ACCEPTED",
    )
    dispatched = dispatch_result(
        permitted,
        dispatch,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    dispatch_digest = next(
        row["dispatch_digest"]
        for row in dispatched["state"]["dispatches"]
        if row["event_id"] == dispatch["event_id"]
    )
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-" + suffix,
        native_operation_id="native-operation-" + suffix,
        dispatch_digest=dispatch_digest,
    )
    effect = governed_effect_event(
        permitted,
        dispatched,
        evidence,
        event_id="effect-" + suffix,
        dispatch_digest=dispatch_digest,
    )
    completed = object_completion_result(base, dispatched, effect, final_join=final_join)
    return proposal, permitted, dispatch, dispatched, effect, completed


def main() -> None:
    keys = [FANOUT["typed"]("IDENTITY", "card-802"), FANOUT["typed"]("IDENTITY", "card-803")]
    base, expand_dispatched, expand_event = FANOUT["setup"](
        "fanout-completion-sequence",
        keys,
        empty_behavior="ADVANCE_TO_JOIN",
    )
    expanded = FANOUT["expansion_result"](base, expand_dispatched, expand_event, mode="NONEMPTY")
    occurrences = sorted(
        (row["occurrence"] for row in expanded["state"]["active"]),
        key=lambda row: int(row["ordinal"]),
    )

    first_proposal, first_permitted, first_dispatch, first_dispatched, first_event, first_completed = execute_object(
        base,
        expanded["state"],
        occurrences[0],
        suffix="fanout-object-1",
        final_join=False,
    )
    write_canonical_json(
        GROUP / "C2-fanout-first-object-completion.json",
        exact_case(
            "C2-fanout-first-object-completion",
            "step",
            step_input(base, first_dispatched["state"], first_event),
            first_completed,
            ["LIFE-015", "PAR-001", "FAN-001"],
            "The first object's matching effect completes only that occurrence and discharges only its exact FANOUT_OBJECT obligation with a direct event basis. The second object and obligation remain active and open, so fanout-1 remains unjoined and the instance remains active.",
        ),
    )

    second_proposal, second_permitted, second_dispatch, second_dispatched, final_event, final_completed = execute_object(
        base,
        first_completed["state"],
        occurrences[1],
        suffix="fanout-object-2",
        final_join=True,
    )
    write_canonical_json(
        GROUP / "D2-142.json",
        exact_case(
            "D2-142",
            "step",
            step_input(base, second_dispatched["state"], final_event),
            final_completed,
            [],
            "The final object's matching effect discharges the last open obligation. The exact pass inventory is now wholly discharged, so the same transition marks both obligations JOINED, marks fanout-1 joined, traverses the join-to-terminal relationship, and completes the instance. ROUTE contains both explicit relationship digests and the fan-out identifier.",
        ),
    )

    print(
        json.dumps(
            {
                "case_ids": ["C2-fanout-first-object-completion", "D2-142"],
                "supporting_events": [
                    first_proposal["event_id"],
                    first_dispatch["event_id"],
                    second_proposal["event_id"],
                    second_dispatch["event_id"],
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
