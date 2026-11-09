#!/usr/bin/env python3
"""Build exact frozen fan-out expansion vectors."""

from __future__ import annotations

import copy
import json

from composition_fixture import add_authority_operations, proposal_for_occurrence
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import occurrence, structural_step, typed
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    governed_outcome,
    effect_result,
    permitted_proposal,
    stateful_refusal,
    step_input,
)


GROUP = CASES / "fanout-expansion"


def fanout_definition(empty_behavior: str, *, object_limit: str | None = None, failure_edge: bool = False):
    def mutate(definition: dict) -> None:
        definition["profile"] = "PARALLEL_FANOUT"
        expand = next(row for row in definition["steps"] if row["id"] == definition["root"])
        expand["kind"] = "FANOUT_EXPAND"
        definition["steps"].append(structural_step("fanout-join", "FANOUT_JOIN"))
        definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
        definition["relationships"] = [
            {"kind": "SEQUENCE", "from": "object-step", "to": "fanout-join"},
            {"kind": "SEQUENCE", "from": "fanout-join", "to": "terminal"},
        ]
        if failure_edge:
            expand["failure_behavior"] = "FAILURE_EDGE"
            definition["relationships"].append({"kind": "FAILURE", "from": expand["id"], "to": "terminal"})
        definition["fanouts"] = [
            {
                "id": "fanout-1",
                "expand_step_id": expand["id"],
                "region_head_step_id": "object-step",
                "join_step_id": "fanout-join",
                "object_field": "items",
                "object_request_field": "card_id",
                "object_type_ref": "IDENTITY",
                "empty_set_behavior": empty_behavior,
            }
        ]
        next(
            row for row in definition["occurrence_limits"] if row["step_id"] == "object-step"
        )["maximum"] = "2"
        if object_limit is not None:
            definition["limits"]["maximum_fanout_objects"] = object_limit
        definition["occurrence_limits"].sort(key=lambda row: row["step_id"].encode("utf-8"))

    return mutate


def setup(
    case_id: str,
    values: list[dict],
    *,
    empty_behavior: str,
    collection_name: str = "items",
    element_type_ref: str = "IDENTITY",
    object_limit: str | None = None,
    failure_edge: bool = False,
    result_value: str = "ISSUED",
) -> tuple[dict, dict, dict]:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(["object-step"]),
        definition_mutator=fanout_definition(empty_behavior, object_limit=object_limit, failure_edge=failure_edge),
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-before-" + case_id.lower(), acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    collections = [] if result_value == "REJECTED" else [
        {"name": collection_name, "element_type_ref": element_type_ref, "values": copy.deepcopy(values)}
    ]
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-" + case_id.lower(),
        result_value=result_value,
        collections=collections,
    )
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-" + case_id.lower())
    return base, dispatched, event


def object_obligation(base: dict, event: dict, key: dict, occurrence_value: dict) -> dict:
    source_id = event["permit"]["occurrence"]["occurrence_id"]
    subject = {
        "kind": "FANOUT_OBJECT",
        "construct_id": "fanout-1",
        "pass": "1",
        "source_occurrence_ids": [source_id],
        "branch_id": None,
        "object_key": copy.deepcopy(key),
        "join_step_id": "fanout-join",
    }
    operation = next(row["operation"] for row in base["definition"]["steps"] if row["id"] == "object-step")
    return {
        "obligation_id": digest("obligation", subject),
        **subject,
        "creation_event_digest": digest("runtime-event", event),
        "status": "OPEN",
        "expected_occurrence_id": occurrence_value["occurrence_id"],
        "required_operation": operation,
        "waiting_on": None,
        "completion_basis": None,
    }


def expansion_result(base: dict, dispatched: dict, event: dict, *, mode: str) -> dict:
    source = event["permit"]["occurrence"]
    values = event["native_evidence"]["collections"][0]["values"]
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    occurrence_rows: list[dict] = []
    obligation_rows: list[dict] = []
    if mode == "NONEMPTY":
        for index, key in enumerate(values):
            object_occurrence = occurrence(
                base["definition_digest"],
                source["instance_id"],
                "object-step",
                str(index + 1),
                [source["occurrence_id"]],
                [
                    {
                        "kind": "FANOUT",
                        "construct_id": "fanout-1",
                        "pass": "1",
                        "branch_id": None,
                        "object_key": copy.deepcopy(key),
                    }
                ],
                object_key=key,
            )
            occurrence_rows.append(object_occurrence)
            obligation_rows.append(object_obligation(base, event, key, object_occurrence))
    pass_row = {
        "fanout_id": "fanout-1",
        "pass": "1",
        "expand_occurrence_id": source["occurrence_id"],
        "object_keys": copy.deepcopy(values),
        "obligation_ids": [row["obligation_id"] for row in obligation_rows],
        "joined": mode == "EMPTY_ADVANCE",
    }
    join_relationship_digest = None
    if mode == "EMPTY_ADVANCE":
        join_relationship = next(
            row for row in base["definition"]["relationships"]
            if row["kind"] == "SEQUENCE" and row["from"] == "fanout-join"
        )
        join_relationship_digest = digest("relationship", join_relationship)

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [
            row for row in state["active"]
            if row["occurrence"]["occurrence_id"] != source["occurrence_id"]
        ]
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(source),
                "disposition": "SUCCEEDED",
                "evidence_digest": digest("native-evidence", event["native_evidence"]),
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": None,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["fanout_passes"].append(copy.deepcopy(pass_row))
        state["fanout_passes"].sort(
            key=lambda row: (row["fanout_id"].encode("utf-8"), int(row["pass"]), row["expand_occurrence_id"].encode("utf-8"))
        )
        if mode == "NONEMPTY":
            for object_occurrence, obligation in zip(occurrence_rows, obligation_rows):
                state["active"].append(
                    {
                        "occurrence": copy.deepcopy(object_occurrence),
                        "activation_event_digest": digest("runtime-event", event),
                        "status": "ACTIVE",
                        "deadline_ids": [],
                    }
                )
                state["obligations"].append(copy.deepcopy(obligation))
            state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
            state["obligations"].sort(key=lambda row: row["obligation_id"].encode("utf-8"))
            counter = next(row for row in state["step_counters"] if row["step_id"] == "object-step")
            counter["activations"] = str(int(counter["activations"]) + len(occurrence_rows))
            state["total_activations"] = str(int(state["total_activations"]) + len(occurrence_rows))
        elif mode == "EMPTY_ADVANCE":
            state["status"] = "COMPLETE"
        else:
            state["status"] = "STOPPED"

    reasons = []
    disposition = "COMPLETED"
    if mode == "DUPLICATE":
        disposition = "STOPPED"
        reasons = ["FANOUT_SET_DUPLICATE"]
    elif mode == "EMPTY_STOP":
        disposition = "STOPPED"
        reasons = ["FANOUT_EMPTY"]
    elif mode == "LIMIT":
        disposition = "STOPPED"
        reasons = ["LIMIT_EXCEEDED"]
    route_digests = [] if join_relationship_digest is None else [join_relationship_digest]
    details = [
        {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
        {"kind": "ROUTE", "relationship_digests": route_digests, "construct_ids": ["fanout-1"]},
    ]
    if mode == "LIMIT":
        details.append(
            {
                "kind": "LIMIT",
                "limit_kind": "FANOUT_OBJECTS",
                "limit": base["definition"]["limits"]["maximum_fanout_objects"],
                "current": str(len(values)),
                "step_id": "object-step",
                "relationship_digest": None,
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


def emit(case_id: str, base: dict, dispatched: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, dispatched["state"], event), expected, [], derivation),
    )


def main() -> None:
    unique = [typed("IDENTITY", "card-802"), typed("IDENTITY", "card-803")]
    base, dispatched, event = setup("D2-054", unique, empty_behavior="ADVANCE_TO_JOIN")
    emit(
        "D2-054",
        base,
        dispatched,
        event,
        expansion_result(base, dispatched, event, mode="NONEMPTY"),
        "The matching expand effect supplies two unique IDENTITY values in source order. The transition freezes that exact array in fanout pass one and atomically creates two object-bound occurrences and their complete obligation inventory. The pass remains unjoined while both obligations are open.",
    )

    duplicate = [typed("IDENTITY", "card-802"), typed("IDENTITY", "card-802")]
    base, dispatched, event = setup("D2-055", duplicate, empty_behavior="ADVANCE_TO_JOIN")
    emit(
        "D2-055",
        base,
        dispatched,
        event,
        expansion_result(base, dispatched, event, mode="DUPLICATE"),
        "The collection is schema-valid and attributable, but the two canonical typed object keys are equal. The effect and complete source-order key list are retained in fanout pass one; the pass has no obligations, remains unjoined, and the instance stops with FANOUT_SET_DUPLICATE.",
    )

    base, dispatched, event = setup("D2-056", [], empty_behavior="ADVANCE_TO_JOIN")
    emit(
        "D2-056",
        base,
        dispatched,
        event,
        expansion_result(base, dispatched, event, mode="EMPTY_ADVANCE"),
        "The exact empty collection follows the declared ADVANCE_TO_JOIN policy. The transition retains one joined pass with empty key and obligation inventories, traverses the join's sequence relationship to terminal, creates no object occurrence, and completes the instance.",
    )

    base, dispatched, event = setup("D2-057", [], empty_behavior="STOP")
    emit(
        "D2-057",
        base,
        dispatched,
        event,
        expansion_result(base, dispatched, event, mode="EMPTY_STOP"),
        "The exact empty collection follows the declared STOP policy. The effect and one unjoined empty pass are retained, no object occurrence or obligation is created, the join does not fire, and the instance stops with FANOUT_EMPTY.",
    )

    base, dispatched, event = setup("D2-075", unique, empty_behavior="ADVANCE_TO_JOIN", object_limit="1")
    emit(
        "D2-075",
        base,
        dispatched,
        event,
        expansion_result(base, dispatched, event, mode="LIMIT"),
        "The exact two-key expansion exceeds maximum_fanout_objects one only at the second source-order key. The effect and complete key array remain retained in an unjoined pass, but atomic preflight creates no object occurrence or obligation and stops the instance with the exact FANOUT_OBJECTS limit detail.",
    )

    base, dispatched, event = setup(
        "D2-129",
        unique,
        empty_behavior="ADVANCE_TO_JOIN",
        collection_name="other-items",
    )
    expected = effect_result(
        base,
        {"permit": event["permit"]},
        dispatched,
        event,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["UNEXPECTED_EFFECT"],
        occurrence_status="OUTCOME_UNKNOWN",
        disputed=True,
    )
    emit(
        "D2-129",
        base,
        dispatched,
        event,
        expected,
        "The evidence is closed and attributable but supplies other-items rather than the fan-out carrier's exact items collection. The first record is retained as UNEXPECTED and blocks the occurrence. It creates no fan-out pass, object occurrence, or obligation.",
    )

    wrong_type_values = [typed("STRING", "card-802")]
    base, dispatched, event = setup(
        "D2-150",
        wrong_type_values,
        empty_behavior="ADVANCE_TO_JOIN",
        element_type_ref="STRING",
    )
    expected = effect_result(
        base,
        {"permit": event["permit"]},
        dispatched,
        event,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["UNEXPECTED_EFFECT"],
        occurrence_status="OUTCOME_UNKNOWN",
        disputed=True,
    )
    emit(
        "D2-150",
        base,
        dispatched,
        event,
        expected,
        "The named items collection is schema-valid but declares STRING elements while fanout-1 requires IDENTITY. The effect is retained as UNEXPECTED and disputed; no fan-out pass or object occurrence is created.",
    )

    base, dispatched, event = setup(
        "D2-135",
        [],
        empty_behavior="ADVANCE_TO_JOIN",
        failure_edge=True,
        result_value="REJECTED",
    )
    expected = effect_result(
        base,
        {"permit": event["permit"]},
        dispatched,
        event,
        classification="FAILED",
        disposition="FAILED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="FAILED",
        route=True,
        route_relationship_kind="FAILURE",
    )
    emit(
        "D2-135",
        base,
        dispatched,
        event,
        expected,
        "The fan-out expand carrier establishes its declared failure value and supplies no collection. The exact FAILURE relationship reaches terminal, so the occurrence completes as FAILED without attempting fan-out expansion or recording a fan-out pass.",
    )

    base, dispatched, event = setup("D2-198", [], empty_behavior="STOP")
    emit(
        "D2-198",
        base,
        dispatched,
        event,
        expansion_result(base, dispatched, event, mode="EMPTY_STOP"),
        "The FANOUT_EXPAND success carries the exact declared empty collection under STOP. The retained pass has empty object and obligation inventories and joined false; no child or join successor is created and the instance stops with FANOUT_EMPTY.",
    )

    base, dispatched, event = setup("D2-143", [], empty_behavior="ADVANCE_TO_JOIN")
    emit(
        "D2-143",
        base,
        dispatched,
        event,
        expansion_result(base, dispatched, event, mode="EMPTY_ADVANCE"),
        "The exact empty collection follows ADVANCE_TO_JOIN. The retained pass is joined with empty key and obligation inventories, and the join's one declared sequence relationship reaches terminal in the same transition.",
    )

    base, dispatched, event = setup("D2-252-base", unique, empty_behavior="ADVANCE_TO_JOIN")
    expanded = expansion_result(base, dispatched, event, mode="NONEMPTY")
    object_occurrence = next(
        row["occurrence"] for row in expanded["state"]["active"]
        if row["occurrence"]["object_key"] == typed("IDENTITY", "card-802")
    )
    proposal, _authority_result = proposal_for_occurrence(
        base,
        expanded["state"],
        object_occurrence,
        event_id="proposal-d2-252",
    )
    next(row for row in proposal["native_request"]["fields"] if row["name"] == "card_id")["value"] = typed("IDENTITY", "card-803")
    emit(
        "D2-252",
        base,
        {"state": expanded["state"]},
        proposal,
        stateful_refusal(expanded["state"], "BINDING_MISMATCH"),
        "The proposal names the active object occurrence whose retained key is card-802, but the exact object-request field card_id contains card-803. LIFE-007 checks the fan-out occurrence-to-request binding before authority or reservation evaluation and returns BINDING_MISMATCH with state unchanged.",
    )

    print(json.dumps({"case_ids": ["D2-054", "D2-055", "D2-056", "D2-057", "D2-075", "D2-129", "D2-135", "D2-143", "D2-150", "D2-198", "D2-252"]}, indent=2))


if __name__ == "__main__":
    main()
