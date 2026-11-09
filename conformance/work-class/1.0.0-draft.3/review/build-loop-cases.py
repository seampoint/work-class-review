#!/usr/bin/env python3
"""Build exact bounded-loop activation and bound-stop cases."""

from __future__ import annotations

import copy
import json

from authority_fixture import authority_specimen
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import occurrence, typed
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


GROUP = CASES / "bounded-loops"


def loop_definition(definition: dict) -> None:
    definition["profile"] = "CHOICE_LOOPS"
    operation = next(row for row in definition["steps"] if row["kind"] == "OPERATION")
    operation["completion"]["route_label_field"] = "route"
    operation["completion"]["route_label_type_ref"] = "STRING"
    definition["relationships"] = [
        {"kind": "LABEL", "from": operation["id"], "to": operation["id"], "label": typed("STRING", "CONTINUE")},
        {"kind": "LABEL", "from": operation["id"], "to": "terminal", "label": typed("STRING", "EXIT")},
    ]
    definition["choices"] = [
        {
            "step_id": operation["id"],
            "label_type_ref": "STRING",
            "label_values": [typed("STRING", "CONTINUE"), typed("STRING", "EXIT")],
        }
    ]
    definition["occurrence_limits"] = [{"step_id": operation["id"], "maximum": "2"}]
    definition["loops"] = [
        {
            "id": "retry-loop",
            "entry_step_id": operation["id"],
            "member_step_ids": [operation["id"]],
            "back_edge_from_step_id": operation["id"],
            "maximum_passes": "2",
        }
    ]


def competing_limit_loop_definition(definition: dict) -> None:
    loop_definition(definition)
    definition["loops"][0]["maximum_passes"] = "3"
    definition["limits"]["maximum_activations"] = "2"


def event_for_occurrence(base: dict, state: dict, occurrence_value: dict, case_id: str) -> tuple[dict, dict]:
    authority_input, authority_result = authority_specimen(
        shared_budget=False,
        instance_id=state["instance_id"],
        occurrence_id=occurrence_value["occurrence_id"],
    )
    authority_executor = authority_input["proposal"]["executor"]
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "proposal-before-" + case_id.lower(),
        "kind": "PROPOSE",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": digest_state(state),
        "occurrence": copy.deepcopy(occurrence_value),
        "native_request": {
            "interface": authority_input["proposal"]["interface"],
            "operation": authority_input["proposal"]["operation"],
            "fields": copy.deepcopy(authority_input["proposal"]["fields"]),
        },
        "executor": {
            "participant_id": authority_executor["actor"],
            "role": authority_executor["role"],
            "binding_digest": digest(
                "executor-binding",
                {key: authority_executor[key] for key in ["actor", "role", "principal", "occupancy"]},
            ),
        },
        "credential_ids": sorted((row["id"] for row in authority_input["credentials"]), key=lambda value: value.encode("utf-8")),
        "authority_input": authority_input,
        "budget_inputs": [],
        "clock_revision": "1",
        "observation_digests": sorted(
            (digest("authority-observation", row) for row in authority_input["observations"]),
            key=lambda value: value.encode("utf-8"),
        ),
    }
    return event, authority_result


def digest_state(state: dict) -> str:
    projected = copy.deepcopy(state)
    for replay in projected["replays"]:
        replay.pop("transaction_digest", None)
    return digest("work-state", projected)


def loop_effect(
    base: dict,
    permitted: dict,
    dispatched: dict,
    event: dict,
    *,
    activate: bool,
    stop_reason: str = "LOOP_BOUND_REACHED",
) -> dict:
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    back_edge = next(
        row
        for row in base["definition"]["relationships"]
        if row["kind"] == "LABEL" and row["label"] == typed("STRING", "CONTINUE")
    )
    relationship_digest = digest("relationship", back_edge)
    current_occurrence = event["permit"]["occurrence"]
    next_occurrence = occurrence(
        base["definition_digest"],
        current_occurrence["instance_id"],
        current_occurrence["step_id"],
        str(int(current_occurrence["ordinal"]) + 1),
        [current_occurrence["occurrence_id"]],
        [
            {
                "kind": "LOOP",
                "construct_id": "retry-loop",
                "pass": str(int(current_occurrence["enclosing"][0]["pass"]) + 1),
                "branch_id": None,
                "object_key": None,
            }
        ],
    )

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active = next(row for row in state["active"] if row["occurrence"]["occurrence_id"] == current_occurrence["occurrence_id"])
        state["active"].remove(active)
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(current_occurrence),
                "disposition": "SUCCEEDED",
                "evidence_digest": digest("native-evidence", event["native_evidence"]),
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": typed("STRING", "CONTINUE"),
                "selected_relationship_digest": relationship_digest,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        if activate:
            state["active"].append(
                {
                    "occurrence": next_occurrence,
                    "activation_event_digest": digest("runtime-event", event),
                    "status": "ACTIVE",
                    "deadline_ids": [],
                }
            )
            state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
            state["total_activations"] = str(int(state["total_activations"]) + 1)
            counter = next(row for row in state["step_counters"] if row["step_id"] == current_occurrence["step_id"])
            counter["activations"] = str(int(counter["activations"]) + 1)
        else:
            state["status"] = "STOPPED"

    details = [
        {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
        {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []},
        {"kind": "LABEL", "step_id": current_occurrence["step_id"], "observed_value": typed("STRING", "CONTINUE")},
    ]
    reasons = []
    disposition = "COMPLETED"
    if not activate:
        disposition = "STOPPED"
        reasons = [stop_reason]
        if stop_reason == "LIMIT_EXCEEDED":
            limit_kind = "STEP_OCCURRENCES"
            limit = "2"
        else:
            limit_kind = "LOOP_PASSES"
            limit = "2"
        details.append(
            {
                "kind": "LIMIT",
                "limit_kind": limit_kind,
                "limit": limit,
                "current": "3",
                "step_id": current_occurrence["step_id"],
                "relationship_digest": relationship_digest,
            }
        )
    return admitted_transition(
        dispatched["state"],
        event,
        disposition=disposition,
        reason_codes=reasons,
        details=details,
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def effect_event(base: dict, permitted: dict, dispatched: dict, case_id: str) -> dict:
    dispatch_id = "dispatch-before-" + case_id.lower()
    dispatch_digest = next(
        row["dispatch_digest"]
        for row in dispatched["state"]["dispatches"]
        if row["event_id"] == dispatch_id
    )
    fields = copy.deepcopy(dispatched["state"]["dispatches"][-1]["native_request"]["fields"])
    fields.extend(
        [
            {"name": "route", "value": typed("STRING", "CONTINUE")},
            {"name": "status", "value": typed("STRING", "ISSUED")},
        ]
    )
    fields.sort(key=lambda row: row["name"].encode("utf-8"))
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-" + case_id.lower(),
        native_operation_id=(
            "native-operation-" + case_id.lower()
            if case_id in {"D2-049", "D2-087"}
            else "native-operation-1"
        ),
        actual_fields=fields,
        dispatch_digest=dispatch_digest,
    )
    return governed_effect_event(
        permitted,
        dispatched,
        evidence,
        event_id="effect-" + case_id.lower(),
        dispatch_digest=dispatch_digest,
    )


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def main() -> None:
    base = base_lifecycle(definition_mutator=loop_definition)
    first_permitted = permitted_proposal(base)
    first_dispatch_event = dispatch_event(base, first_permitted, event_id="dispatch-before-d2-048", acknowledgement_status="ACCEPTED")
    first_dispatched = dispatch_result(
        first_permitted,
        first_dispatch_event,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    first_effect_event = effect_event(base, first_permitted, first_dispatched, "D2-048")
    first_effect = loop_effect(base, first_permitted, first_dispatched, first_effect_event, activate=True)
    emit(
        "D2-048",
        base,
        first_dispatched["state"],
        first_effect_event,
        first_effect,
        "The first root occurrence is loop pass 1. Selecting the declared back edge allocates pass 2, exactly the maximum, and ordinal 2. The matching effect, completed occurrence and new active occurrence commit together with a fresh occurrence identity.",
    )

    second_occurrence = first_effect["state"]["active"][0]["occurrence"]
    proposal_event, authority_result = event_for_occurrence(base, first_effect["state"], second_occurrence, "D2-049")
    second_base = copy.deepcopy(base)
    second_base["proposal_event"] = proposal_event
    second_base["authority_input"] = proposal_event["authority_input"]
    second_base["authority_result"] = authority_result
    second_base["clock_result"] = {"state": first_effect["state"], "state_digest": first_effect["state_digest"], "role": first_effect["role"]}
    second_permitted = permitted_proposal(second_base, proposal_event)
    second_dispatch_event = dispatch_event(base, second_permitted, event_id="dispatch-before-d2-049", acknowledgement_status="ACCEPTED")
    second_dispatched = dispatch_result(
        second_permitted,
        second_dispatch_event,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    second_effect_event = effect_event(base, second_permitted, second_dispatched, "D2-049")
    second_effect = loop_effect(
        base,
        second_permitted,
        second_dispatched,
        second_effect_event,
        activate=False,
        stop_reason="LIMIT_EXCEEDED",
    )
    emit(
        "D2-049",
        base,
        second_dispatched["state"],
        second_effect_event,
        second_effect,
        "The current occurrence is loop pass 2 and the step already has two occurrences. Taking the back edge would allocate pass and occurrence 3, exceeding both maximum_passes two and the step occurrence maximum two. Canonical limit precedence selects STEP_OCCURRENCES, so the effect and route remain retained, the instance stops with LIMIT_EXCEEDED, and no successor is created.",
    )

    competing = base_lifecycle(definition_mutator=competing_limit_loop_definition)
    first_permitted = permitted_proposal(competing)
    first_dispatch_event = dispatch_event(
        competing,
        first_permitted,
        event_id="dispatch-before-d2-087-pass-1",
        acknowledgement_status="ACCEPTED",
    )
    first_dispatched = dispatch_result(
        first_permitted,
        first_dispatch_event,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    first_effect_event = effect_event(competing, first_permitted, first_dispatched, "D2-087-pass-1")
    first_effect = loop_effect(competing, first_permitted, first_dispatched, first_effect_event, activate=True)
    second_occurrence = first_effect["state"]["active"][0]["occurrence"]
    proposal_event, authority_result = event_for_occurrence(
        competing,
        first_effect["state"],
        second_occurrence,
        "D2-087",
    )
    second_base = copy.deepcopy(competing)
    second_base["proposal_event"] = proposal_event
    second_base["authority_input"] = proposal_event["authority_input"]
    second_base["authority_result"] = authority_result
    second_base["clock_result"] = {
        "state": first_effect["state"],
        "state_digest": first_effect["state_digest"],
        "role": first_effect["role"],
    }
    second_permitted = permitted_proposal(second_base, proposal_event)
    second_dispatch_event = dispatch_event(
        competing,
        second_permitted,
        event_id="dispatch-before-d2-087",
        acknowledgement_status="ACCEPTED",
    )
    second_dispatched = dispatch_result(
        second_permitted,
        second_dispatch_event,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    second_effect_event = effect_event(competing, second_permitted, second_dispatched, "D2-087")
    second_effect = loop_effect(
        competing,
        second_permitted,
        second_dispatched,
        second_effect_event,
        activate=False,
        stop_reason="LIMIT_EXCEEDED",
    )
    emit(
        "D2-087",
        competing,
        second_dispatched["state"],
        second_effect_event,
        second_effect,
        "The matching pass-2 effect selects the declared back edge. Allocating pass 3 would violate both the step occurrence maximum two and maximum_activations two. Canonical dynamic-limit precedence selects STEP_OCCURRENCES, so the transition retains the effect and route, completes pass 2, stops the instance, and creates no pass-3 occurrence.",
    )

    print(json.dumps({"case_ids": ["D2-048", "D2-049", "D2-087"]}, indent=2))


if __name__ == "__main__":
    main()
