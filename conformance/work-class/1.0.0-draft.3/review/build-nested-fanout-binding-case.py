#!/usr/bin/env python3
"""Build the exact nested-fan-out proposal-binding vector D2-253."""

from __future__ import annotations

import copy
import json

from authority_fixture import authority_specimen
from composition_fixture import add_authority_operations, authority_projection, permitted_operation_proposal
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
    permitted_proposal,
    state_digest,
    step_input,
)


GROUP = CASES / "nested-fanout-binding"


def nested_fanout_definition(definition: dict) -> None:
    definition["profile"] = "PARALLEL_FANOUT"
    root = next(row for row in definition["steps"] if row["id"] == definition["root"])
    root["kind"] = "FANOUT_EXPAND"
    outer = next(row for row in definition["steps"] if row["id"] == "outer-expand")
    outer["kind"] = "FANOUT_EXPAND"
    for step in [outer, next(row for row in definition["steps"] if row["id"] == "inner-operation")]:
        existing = {row["name"] for row in step["fields"]}
        for name in ["outer_card_id", "inner_card_id"]:
            if name == "inner_card_id" and step["id"] != "inner-operation":
                continue
            if name not in existing:
                step["fields"].append({"name": name, "type_ref": "IDENTITY"})
        step["fields"].sort(key=lambda row: row["name"].encode("utf-8"))
        step["completion"]["evidence_bindings"] = [
            {"request_field": row["name"], "evidence_field": row["name"]}
            for row in step["fields"]
        ]
        step["completion"]["evidence_bindings"].sort(key=lambda row: row["request_field"].encode("utf-8"))
    definition["steps"].extend(
        [
            structural_step("inner-join", "FANOUT_JOIN"),
            structural_step("outer-join", "FANOUT_JOIN"),
        ]
    )
    definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
    definition["relationships"] = [
        {"kind": "SEQUENCE", "from": "inner-operation", "to": "inner-join"},
        {"kind": "SEQUENCE", "from": "inner-join", "to": "outer-join"},
        {"kind": "SEQUENCE", "from": "outer-join", "to": "terminal"},
    ]
    definition["relationships"].sort(key=canonical_bytes)
    definition["fanouts"] = [
        {
            "id": "fanout-inner",
            "expand_step_id": "outer-expand",
            "region_head_step_id": "inner-operation",
            "join_step_id": "inner-join",
            "object_field": "inner_items",
            "object_request_field": "inner_card_id",
            "object_type_ref": "IDENTITY",
            "empty_set_behavior": "ADVANCE_TO_JOIN",
        },
        {
            "id": "fanout-outer",
            "expand_step_id": "issue",
            "region_head_step_id": "outer-expand",
            "join_step_id": "outer-join",
            "object_field": "outer_items",
            "object_request_field": "outer_card_id",
            "object_type_ref": "IDENTITY",
            "empty_set_behavior": "ADVANCE_TO_JOIN",
        },
    ]
    definition["fanouts"].sort(key=lambda row: row["id"].encode("utf-8"))
    definition["occurrence_limits"].sort(key=lambda row: row["step_id"].encode("utf-8"))


def authority_for_nested_occurrence(base: dict, occurrence_value: dict) -> tuple[dict, dict]:
    step = next(row for row in base["definition"]["steps"] if row["id"] == occurrence_value["step_id"])
    key_by_construct = {
        segment["construct_id"]: segment["object_key"]
        for segment in occurrence_value["enclosing"]
        if segment["kind"] == "FANOUT"
    }

    def mutate(request: dict, _original: dict) -> None:
        request["work_class"] = authority_projection(base["definition"])
        request["envelope"]["id"] = "authority-" + step["id"]
        request["envelope"]["operations"] = [
            {"interface": step["interface"], "operation": step["operation"], "step": step["id"]}
        ]
        for binding in request["envelope"]["bindings"]:
            binding["step"] = step["id"]
        for condition in request["envelope"]["conditions"]:
            condition["step"] = step["id"]
        request["envelope"]["limits"]["per_action"] = [
            {
                "id": "authority-only-amount-limit",
                "step": step["id"],
                "field": "amount",
                "operator": "LTE",
                "bound": {"type_ref": "amount", "value": "1000000"},
            }
        ]
        current_fields = {row["name"]: copy.deepcopy(row["value"]) for row in request["proposal"]["fields"]}
        current_fields["outer_card_id"] = copy.deepcopy(key_by_construct["fanout-outer"])
        if "fanout-inner" in key_by_construct:
            current_fields["inner_card_id"] = copy.deepcopy(key_by_construct["fanout-inner"])
        request["proposal"].update(
            {
                "step": step["id"],
                "operation": step["operation"],
                "interface": step["interface"],
                "occurrence": occurrence_value["occurrence_id"],
                "instance": occurrence_value["instance_id"],
                "fields": [
                    {"name": field["name"], "value": copy.deepcopy(current_fields[field["name"]])}
                    for field in step["fields"]
                ],
            }
        )
        request["proposal"]["fields"].sort(key=lambda row: row["name"].encode("utf-8"))
        credential = request["credentials"][0]
        credential.update({"step": step["id"], "operation": step["operation"], "interface": step["interface"]})

    return authority_specimen(
        shared_budget=False,
        instance_id=occurrence_value["instance_id"],
        occurrence_id=occurrence_value["occurrence_id"],
        mutator=mutate,
    )


def proposal_for_nested_occurrence(base: dict, state: dict, occurrence_value: dict, event_id: str):
    authority_input, authority_result = authority_for_nested_occurrence(base, occurrence_value)
    step = next(row for row in base["definition"]["steps"] if row["id"] == occurrence_value["step_id"])
    executor = authority_input["proposal"]["executor"]
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "PROPOSE",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "occurrence": copy.deepcopy(occurrence_value),
        "native_request": {
            "interface": step["interface"],
            "operation": step["operation"],
            "fields": copy.deepcopy(authority_input["proposal"]["fields"]),
        },
        "executor": {
            "participant_id": executor["actor"],
            "role": executor["role"],
            "binding_digest": digest(
                "executor-binding",
                {key: executor[key] for key in ["actor", "role", "principal", "occupancy"]},
            ),
        },
        "credential_ids": sorted(
            (row["id"] for row in authority_input["credentials"]),
            key=lambda value: value.encode("utf-8"),
        ),
        "authority_input": authority_input,
        "budget_inputs": [],
        "clock_revision": "1",
        "observation_digests": sorted(
            (digest("authority-observation", row) for row in authority_input["observations"]),
            key=lambda value: value.encode("utf-8"),
        ),
    }
    return event, authority_result


def object_occurrence(base: dict, source: dict, fanout: dict, key: dict) -> dict:
    enclosing = copy.deepcopy(source["enclosing"]) + [
        {
            "kind": "FANOUT",
            "construct_id": fanout["id"],
            "pass": "1",
            "branch_id": None,
            "object_key": copy.deepcopy(key),
        }
    ]
    return occurrence(
        base["definition_digest"],
        source["instance_id"],
        fanout["region_head_step_id"],
        "1",
        [source["occurrence_id"]],
        enclosing,
        object_key=key,
    )


def object_obligation(base: dict, event: dict, fanout: dict, key: dict, child: dict) -> dict:
    subject = {
        "kind": "FANOUT_OBJECT",
        "construct_id": fanout["id"],
        "pass": "1",
        "source_occurrence_ids": [event["permit"]["occurrence"]["occurrence_id"]],
        "branch_id": None,
        "object_key": copy.deepcopy(key),
        "join_step_id": fanout["join_step_id"],
    }
    operation = next(
        row["operation"] for row in base["definition"]["steps"] if row["id"] == fanout["region_head_step_id"]
    )
    return {
        "obligation_id": digest("obligation", subject),
        **subject,
        "creation_event_digest": digest("runtime-event", event),
        "status": "OPEN",
        "expected_occurrence_id": child["occurrence_id"],
        "required_operation": operation,
        "waiting_on": None,
        "completion_basis": None,
    }


def expansion_result(base: dict, dispatched: dict, event: dict, fanout_id: str, key: dict, parent_obligation_id=None):
    fanout = next(row for row in base["definition"]["fanouts"] if row["id"] == fanout_id)
    source = event["permit"]["occurrence"]
    child = object_occurrence(base, source, fanout, key)
    child_obligation = object_obligation(base, event, fanout, key, child)
    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    pass_row = {
        "fanout_id": fanout_id,
        "pass": "1",
        "expand_occurrence_id": source["occurrence_id"],
        "object_keys": [copy.deepcopy(key)],
        "obligation_ids": [child_obligation["obligation_id"]],
        "joined": False,
    }

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [
            row for row in state["active"] if row["occurrence"]["occurrence_id"] != source["occurrence_id"]
        ]
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(source),
                "disposition": "SUCCEEDED",
                "evidence_digest": evidence_digest,
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": None,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["active"].append(
            {
                "occurrence": copy.deepcopy(child),
                "activation_event_digest": event_digest,
                "status": "ACTIVE",
                "deadline_ids": [],
            }
        )
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["obligations"].append(copy.deepcopy(child_obligation))
        if parent_obligation_id is not None:
            parent = next(row for row in state["obligations"] if row["obligation_id"] == parent_obligation_id)
            parent["status"] = "WAITING"
            parent["expected_occurrence_id"] = None
            parent["required_operation"] = None
            parent["waiting_on"] = {
                "kind": "FANOUT",
                "construct_id": fanout_id,
                "pass": "1",
                "outer_enclosing": copy.deepcopy(source["enclosing"]),
                "obligation_ids": [child_obligation["obligation_id"]],
            }
        state["obligations"].sort(key=lambda row: row["obligation_id"].encode("utf-8"))
        state["fanout_passes"].append(copy.deepcopy(pass_row))
        state["fanout_passes"].sort(
            key=lambda row: (row["fanout_id"].encode("utf-8"), int(row["pass"]), row["expand_occurrence_id"].encode("utf-8"))
        )
        counter = next(row for row in state["step_counters"] if row["step_id"] == child["step_id"])
        counter["activations"] = str(int(counter["activations"]) + 1)
        state["total_activations"] = str(int(state["total_activations"]) + 1)

    return admitted_transition(
        dispatched["state"],
        event,
        disposition="COMPLETED",
        reason_codes=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [], "construct_ids": [fanout_id]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def execute_expand(base: dict, state: dict, occurrence_value: dict, event_id: str, collection_name: str, key: dict):
    if occurrence_value["step_id"] == base["definition"]["root"]:
        permitted = permitted_proposal(base)
    else:
        proposal, authority_result = proposal_for_nested_occurrence(base, state, occurrence_value, "proposal-" + event_id)
        permitted = permitted_operation_proposal(base, state, proposal, authority_result)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-" + event_id, acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    dispatch_digest = next(row["dispatch_digest"] for row in dispatched["state"]["dispatches"] if row["event_id"] == dispatch["event_id"])
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-" + event_id,
        native_operation_id="native-" + event_id,
        collections=[{"name": collection_name, "element_type_ref": "IDENTITY", "values": [copy.deepcopy(key)]}],
        dispatch_digest=dispatch_digest,
    )
    effect = governed_effect_event(
        permitted,
        dispatched,
        evidence,
        event_id="effect-" + event_id,
        dispatch_digest=dispatch_digest,
    )
    return permitted, dispatched, effect


def main() -> None:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(["outer-expand", "inner-operation"]),
        definition_mutator=nested_fanout_definition,
    )
    outer_key = typed("IDENTITY", "outer-card-1")
    _permitted, outer_dispatched, outer_event = execute_expand(
        base,
        base["clock_result"]["state"],
        base["proposal_event"]["occurrence"],
        "d2-253-outer",
        "outer_items",
        outer_key,
    )
    outer = expansion_result(base, outer_dispatched, outer_event, "fanout-outer", outer_key)
    outer_occurrence = next(row["occurrence"] for row in outer["state"]["active"] if row["occurrence"]["step_id"] == "outer-expand")
    outer_obligation = next(row["obligation_id"] for row in outer["state"]["obligations"] if row["expected_occurrence_id"] == outer_occurrence["occurrence_id"])
    inner_key = typed("IDENTITY", "inner-card-1")
    _permitted, inner_dispatched, inner_event = execute_expand(
        base,
        outer["state"],
        outer_occurrence,
        "d2-253-inner",
        "inner_items",
        inner_key,
    )
    nested = expansion_result(
        base,
        inner_dispatched,
        inner_event,
        "fanout-inner",
        inner_key,
        parent_obligation_id=outer_obligation,
    )
    inner_occurrence = next(row["occurrence"] for row in nested["state"]["active"] if row["occurrence"]["step_id"] == "inner-operation")
    proposal, authority_result = proposal_for_nested_occurrence(base, nested["state"], inner_occurrence, "proposal-d2-253")
    expected = permitted_operation_proposal(base, nested["state"], proposal, authority_result)
    write_canonical_json(
        GROUP / "D2-253.json",
        exact_case(
            "D2-253",
            "step",
            step_input(base, nested["state"], proposal),
            expected,
            [],
            "The active inner occurrence retains outer-card-1 in its fanout-outer segment and inner-card-1 in its fanout-inner segment. The request carries those values in the distinct declared fields outer_card_id and inner_card_id. Both occurrence-to-object checks succeed before current authority establishes the exact inner operation; no shared budget input is required, so one permit is created atomically with the work-state advance.",
        ),
    )
    print(json.dumps({"case_ids": ["D2-253"]}, indent=2))


if __name__ == "__main__":
    main()
