#!/usr/bin/env python3
"""Build exact choice routing, invalid-label, and failure-path cases."""

from __future__ import annotations

import copy
import json

from composition_fixture import add_authority_operations
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import occurrence, typed
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    effect_result,
    governed_effect_event,
    governed_native_evidence,
    governed_outcome,
    permitted_proposal,
    step_input,
)


GROUP = CASES / "choice-routing"
CHOICE_TARGETS = ["choice-approve", "choice-reject"]


def choice_definition(definition: dict) -> None:
    definition["profile"] = "CHOICE_LOOPS"
    operation = next(row for row in definition["steps"] if row["id"] == definition["root"])
    operation["completion"]["route_label_field"] = "route"
    operation["completion"]["route_label_type_ref"] = "STRING"
    definition["relationships"] = [
        {"kind": "LABEL", "from": operation["id"], "to": "choice-approve", "label": typed("STRING", "APPROVE")},
        {"kind": "LABEL", "from": operation["id"], "to": "choice-reject", "label": typed("STRING", "REJECT")},
        {"kind": "SEQUENCE", "from": "choice-approve", "to": "terminal"},
        {"kind": "SEQUENCE", "from": "choice-reject", "to": "terminal"},
    ]
    definition["choices"] = [
        {
            "step_id": operation["id"],
            "label_type_ref": "STRING",
            "label_values": [typed("STRING", "APPROVE"), typed("STRING", "REJECT")],
        }
    ]


def failure_choice_definition(definition: dict) -> None:
    choice_definition(definition)
    operation = next(row for row in definition["steps"] if row["id"] == definition["root"])
    operation["failure_behavior"] = "FAILURE_EDGE"
    definition["relationships"].append({"kind": "FAILURE", "from": operation["id"], "to": "terminal"})


def setup(*, failure_edge: bool = False) -> tuple[dict, dict, dict]:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(CHOICE_TARGETS),
        definition_mutator=failure_choice_definition if failure_edge else choice_definition,
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-choice", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    return base, permitted, dispatched


def actual_fields(dispatched: dict, *, result: str, label: dict | None, include_label: bool = True) -> list[dict]:
    fields = copy.deepcopy(dispatched["state"]["dispatches"][-1]["native_request"]["fields"])
    fields.append({"name": "status", "value": typed("STRING", result)})
    if include_label:
        fields.append({"name": "route", "value": copy.deepcopy(label)})
    return sorted(fields, key=lambda row: row["name"].encode("utf-8"))


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def runtime_choice(case_id: str, label: dict | None, *, include_label: bool = True) -> tuple[dict, dict, dict, dict]:
    base, permitted, dispatched = setup()
    fields = actual_fields(dispatched, result="ISSUED", label=label, include_label=include_label)
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-" + case_id.lower(), actual_fields=fields)
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-" + case_id.lower())
    return base, permitted, dispatched, event


def successful_choice_result(base: dict, dispatched: dict, event: dict, relationship: dict, label: dict) -> dict:
    source = event["permit"]["occurrence"]
    target_step = relationship["to"]
    target = occurrence(
        base["definition_digest"],
        source["instance_id"],
        target_step,
        "1",
        [source["occurrence_id"]],
    )
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    relationship_digest = digest("relationship", relationship)

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active_index = next(
            index
            for index, row in enumerate(state["active"])
            if row["occurrence"]["occurrence_id"] == source["occurrence_id"]
        )
        state["active"].pop(active_index)
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(source),
                "disposition": "SUCCEEDED",
                "evidence_digest": digest("native-evidence", event["native_evidence"]),
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": copy.deepcopy(label),
                "selected_relationship_digest": relationship_digest,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["active"].append(
            {
                "occurrence": target,
                "activation_event_digest": digest("runtime-event", event),
                "status": "ACTIVE",
                "deadline_ids": [],
            }
        )
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["total_activations"] = str(int(state["total_activations"]) + 1)
        counter = next(row for row in state["step_counters"] if row["step_id"] == target_step)
        counter["activations"] = str(int(counter["activations"]) + 1)

    return admitted_transition(
        dispatched["state"],
        event,
        disposition="COMPLETED",
        reason_codes=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []},
            {"kind": "LABEL", "step_id": source["step_id"], "observed_value": copy.deepcopy(label)},
        ],
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def main() -> None:
    label = typed("STRING", "APPROVE")
    base, permitted, dispatched, event = runtime_choice("D2-045", label)
    relationship = next(row for row in base["definition"]["relationships"] if row["kind"] == "LABEL" and row["label"] == label)
    expected = successful_choice_result(base, dispatched, event, relationship, label)
    emit(
        "D2-045",
        base,
        dispatched["state"],
        event,
        expected,
        "The exact native effect supplies the declared STRING label APPROVE. That value occurs once in the closed choice domain and maps to choice-approve. The transition retains the route, completes the source occurrence, activates only the exact mapped target and leaves choice-reject inactive.",
    )

    invalid = typed("STRING", "ESCALATE")
    base, permitted, dispatched, event = runtime_choice("D2-046", invalid)
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="MATCHED",
        disposition="STOPPED",
        reason_codes=["LABEL_INVALID"],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=False,
        route_label=invalid,
        include_label_detail=True,
        instance_status="STOPPED",
    )
    emit(
        "D2-046",
        base,
        dispatched["state"],
        event,
        expected,
        "The matching effect supplies a well-typed label outside the declared finite choice domain. The consumer retains the effect and observed label, closes the occurrence, stops the instance with LABEL_INVALID, and invents no route.",
    )

    base, permitted, dispatched, event = runtime_choice("D2-132", None, include_label=False)
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="MATCHED",
        disposition="STOPPED",
        reason_codes=["LABEL_INVALID"],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=False,
        route_label=None,
        include_label_detail=True,
        instance_status="STOPPED",
    )
    emit(
        "D2-132",
        base,
        dispatched["state"],
        event,
        expected,
        "All request-bound fields and the success status match, but the declared route-label field is absent. This is a retained LABEL_INVALID policy stop rather than an unexpected request-field mismatch, and no target is selected.",
    )

    wrong_type = typed("amount", "1")
    base, permitted, dispatched, event = runtime_choice("D2-133", wrong_type)
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="MATCHED",
        disposition="STOPPED",
        reason_codes=["LABEL_INVALID"],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=False,
        route_label=wrong_type,
        include_label_detail=True,
        instance_status="STOPPED",
    )
    emit(
        "D2-133",
        base,
        dispatched["state"],
        event,
        expected,
        "The route field exists once but uses the declared amount type instead of the choice's STRING label type. The effect remains attributable and is retained; LABEL_INVALID stops the instance without selecting a target.",
    )

    base, permitted, dispatched = setup(failure_edge=True)
    fields = actual_fields(dispatched, result="REJECTED", label=None, include_label=False)
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-d2-134", actual_fields=fields)
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-d2-134")
    failure_relationship = next(row for row in base["definition"]["relationships"] if row["kind"] == "FAILURE")
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="FAILED",
        disposition="FAILED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="FAILED",
        route=True,
        route_relationship=failure_relationship,
    )
    emit(
        "D2-134",
        base,
        dispatched["state"],
        event,
        expected,
        "The exact carrier establishes the declared failure value. Failure routing uses the one FAILURE relationship and does not require or interpret the success-only label field.",
    )

    print(json.dumps({"case_ids": ["D2-045", "D2-046", "D2-132", "D2-133", "D2-134"]}, indent=2))


if __name__ == "__main__":
    main()
