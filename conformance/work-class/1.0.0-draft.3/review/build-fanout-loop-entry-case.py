#!/usr/bin/env python3
"""Build D2-113: the same loop entered for the first time under a second frozen fan-out object.

COMP-002 allocates loop passes on the pair (loop_id, exact outer enclosing prefix) and only when
the back edge is selected. Entry from outside allocates pass 1 unconditionally, and a new object
context begins at one. LIFE-016 fixes the resulting occurrence's enclosing path: the loop segment
follows the fan-out segment in outer-to-inner order.

The fixture is a one-fan-out region whose head routes by SEQUENCE into a self-looping operation.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from composition_fixture import add_authority_operations, permitted_operation_proposal
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import occurrence, structural_step, typed
from lifecycle_factory import (
    admitted_transition, base_lifecycle, dispatch_event, dispatch_result, governed_effect_event,
    governed_native_evidence, governed_outcome, permitted_proposal, step_input,
)


def _module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NESTED = _module("nested_fanout_binding", "build-nested-fanout-binding-case.py")
PREFIX = _module("fanout_outer_prefix", "build-fanout-outer-prefix-case.py")
GROUP = CASES / "fanout-loop-entry"
LOOP_ID = "retry-loop"
FANOUT_ID = "fanout-outer"
HEAD = "outer-expand"
LOOP_STEP = "inner-operation"


def loop_in_fanout_definition(definition: dict) -> None:
    definition["profile"] = "PARALLEL_FANOUT"
    root = next(row for row in definition["steps"] if row["id"] == definition["root"])
    root["kind"] = "FANOUT_EXPAND"
    for step_id in (HEAD, LOOP_STEP):
        step = next(row for row in definition["steps"] if row["id"] == step_id)
        if not any(row["name"] == "outer_card_id" for row in step["fields"]):
            step["fields"].append({"name": "outer_card_id", "type_ref": "IDENTITY"})
        step["fields"].sort(key=lambda row: row["name"].encode("utf-8"))
        step["completion"]["evidence_bindings"] = [
            {"request_field": row["name"], "evidence_field": row["name"]} for row in step["fields"]
        ]
        step["completion"]["evidence_bindings"].sort(key=lambda row: row["request_field"].encode("utf-8"))
    loop_step = next(row for row in definition["steps"] if row["id"] == LOOP_STEP)
    loop_step["completion"]["route_label_field"] = "route"
    loop_step["completion"]["route_label_type_ref"] = "STRING"
    definition["steps"].append(structural_step("outer-join", "FANOUT_JOIN"))
    definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
    definition["relationships"] = [
        {"kind": "SEQUENCE", "from": HEAD, "to": LOOP_STEP},
        {"kind": "LABEL", "from": LOOP_STEP, "to": LOOP_STEP, "label": typed("STRING", "CONTINUE")},
        {"kind": "LABEL", "from": LOOP_STEP, "to": "outer-join", "label": typed("STRING", "EXIT")},
        {"kind": "SEQUENCE", "from": "outer-join", "to": "terminal"},
    ]
    definition["relationships"].sort(key=canonical_bytes)
    definition["choices"] = [{
        "step_id": LOOP_STEP, "label_type_ref": "STRING",
        "label_values": [typed("STRING", "CONTINUE"), typed("STRING", "EXIT")],
    }]
    definition["loops"] = [{
        "id": LOOP_ID, "entry_step_id": LOOP_STEP, "member_step_ids": [LOOP_STEP],
        "back_edge_from_step_id": LOOP_STEP, "maximum_passes": "2",
    }]
    definition["fanouts"] = [{
        "id": FANOUT_ID, "expand_step_id": definition["root"], "region_head_step_id": HEAD,
        "join_step_id": "outer-join", "object_field": "outer_items",
        "object_request_field": "outer_card_id", "object_type_ref": "IDENTITY",
        "empty_set_behavior": "ADVANCE_TO_JOIN",
    }]
    definition["occurrence_limits"] = [
        {"step_id": definition["root"], "maximum": "1"},
        {"step_id": HEAD, "maximum": "2"},
        {"step_id": LOOP_STEP, "maximum": "4"},
    ]
    definition["occurrence_limits"].sort(key=lambda row: row["step_id"].encode("utf-8"))
    definition["limits"]["maximum_fanout_objects"] = "2"


def next_ordinal(state: dict, step_id: str) -> str:
    retained = [
        int(row["occurrence"]["ordinal"])
        for row in state["active"] + state["completed"]
        if row["occurrence"]["step_id"] == step_id
    ]
    return str(max(retained, default=0) + 1)


def run_operation(base: dict, state: dict, occurrence_value: dict, tag: str, *, route_label: str | None = None):
    proposal, authority_result = NESTED.proposal_for_nested_occurrence(
        base, state, occurrence_value, "proposal-" + tag
    )
    permitted = permitted_operation_proposal(base, state, proposal, authority_result)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-" + tag, acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(
        permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED"
    )
    row = next(r for r in dispatched["state"]["dispatches"] if r["event_id"] == dispatch["event_id"])
    fields = None
    if route_label is not None:
        fields = copy.deepcopy(row["native_request"]["fields"]) + [
            {"name": "route", "value": typed("STRING", route_label)},
            {"name": "status", "value": typed("STRING", "ISSUED")},
        ]
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-" + tag, native_operation_id="native-" + tag,
        actual_fields=fields, dispatch_digest=row["dispatch_digest"],
    )
    event = governed_effect_event(
        permitted, dispatched, evidence, event_id="effect-" + tag, dispatch_digest=row["dispatch_digest"]
    )
    return dispatched, evidence, event


def relationship_digest(base: dict, **match) -> str:
    row = next(
        r for r in base["definition"]["relationships"]
        if all(r.get(key) == value for key, value in match.items())
    )
    return digest("relationship", row)


def advance_within_region(
    base: dict, dispatched: dict, evidence: dict, event: dict, *,
    successor_step: str, enclosing: list[dict], route_label: dict | None, selected: str, details_extra: list[dict],
) -> dict:
    """One eligible direct route inside an object region, replacing the obligation's expectation."""
    source = event["permit"]["occurrence"]
    successor_operation = next(
        row["operation"] for row in base["definition"]["steps"] if row["id"] == successor_step
    )
    successor = occurrence(
        base["definition_digest"], source["instance_id"], successor_step,
        next_ordinal(dispatched["state"], successor_step), [source["occurrence_id"]], enclosing,
        # LIFE-001: with a fan-out segment present the top-level object key is the innermost one.
        object_key=next(
            (seg["object_key"] for seg in reversed(enclosing) if seg["kind"] == "FANOUT"), None
        ),
    )
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [
            row for row in state["active"] if row["occurrence"]["occurrence_id"] != source["occurrence_id"]
        ]
        state["completed"].append({
            "occurrence": copy.deepcopy(source), "disposition": "SUCCEEDED",
            "evidence_digest": digest("native-evidence", evidence), "occurred_at": evidence["event_time"],
            "route_label": copy.deepcopy(route_label), "selected_relationship_digest": selected, "late": False,
        })
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["active"].append({
            "occurrence": copy.deepcopy(successor), "activation_event_digest": digest("runtime-event", event),
            "status": "ACTIVE", "deadline_ids": [],
        })
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        counter = next(row for row in state["step_counters"] if row["step_id"] == successor_step)
        counter["activations"] = str(int(counter["activations"]) + 1)
        state["total_activations"] = str(int(state["total_activations"]) + 1)
        # PAR-001 and FAN-001: an onward route inside the region retracks the owning obligation
        # rather than discharging it; the join stays pending.
        for obligation in state["obligations"]:
            if obligation.get("expected_occurrence_id") == source["occurrence_id"]:
                obligation["expected_occurrence_id"] = successor["occurrence_id"]
                obligation["required_operation"] = successor_operation

    return admitted_transition(
        dispatched["state"], event, disposition="COMPLETED", reason_codes=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [selected], "construct_ids": []},
        ] + details_extra,
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


def loop_entry(base: dict, dispatched: dict, evidence: dict, event: dict) -> dict:
    """The region head routes into the loop entry, which is entry from outside at pass 1."""
    source = event["permit"]["occurrence"]
    enclosing = copy.deepcopy(source["enclosing"]) + [
        {"kind": "LOOP", "construct_id": LOOP_ID, "pass": "1", "branch_id": None, "object_key": None}
    ]
    return advance_within_region(
        base, dispatched, evidence, event, successor_step=LOOP_STEP, enclosing=enclosing,
        route_label=None, selected=relationship_digest(base, kind="SEQUENCE", **{"from": HEAD}),
        details_extra=[],
    )


def loop_back_edge(base: dict, dispatched: dict, evidence: dict, event: dict) -> dict:
    """Selecting the declared back edge allocates current pass plus one in the same context."""
    source = event["permit"]["occurrence"]
    enclosing = copy.deepcopy(source["enclosing"])
    segment = next(row for row in reversed(enclosing) if row["kind"] == "LOOP")
    segment["pass"] = str(int(segment["pass"]) + 1)
    return advance_within_region(
        base, dispatched, evidence, event, successor_step=LOOP_STEP, enclosing=enclosing,
        route_label=typed("STRING", "CONTINUE"),
        selected=relationship_digest(base, kind="LABEL", label=typed("STRING", "CONTINUE")),
        details_extra=[{"kind": "LABEL", "step_id": LOOP_STEP, "observed_value": typed("STRING", "CONTINUE")}],
    )


def build() -> None:
    base = base_lifecycle(
        authority_mutator=add_authority_operations([HEAD, LOOP_STEP]),
        definition_mutator=loop_in_fanout_definition,
    )
    keys = [typed("IDENTITY", "outer-card-1"), typed("IDENTITY", "outer-card-2")]
    _p, expand_dispatched, expand_event = PREFIX.execute_expand_multi(
        base, base["clock_result"]["state"], base["proposal_event"]["occurrence"],
        "d2-113-expand", "outer_items", keys,
    )
    expanded = PREFIX.multi_expansion(base, expand_dispatched, expand_event, FANOUT_ID, keys)

    def object_head(state, ordinal):
        return next(
            row["occurrence"] for row in state["active"]
            if row["occurrence"]["step_id"] == HEAD and row["occurrence"]["ordinal"] == ordinal
        )

    # Setup: the first object enters the loop and then takes the back edge, retaining pass 2 for
    # the pair of this loop and the first object's prefix.
    first_dispatched, first_evidence, first_event = run_operation(
        base, expanded["state"], object_head(expanded["state"], "1"), "d2-113-head-a"
    )
    first_entry = loop_entry(base, first_dispatched, first_evidence, first_event)
    loop_one = next(
        row["occurrence"] for row in first_entry["state"]["active"] if row["occurrence"]["step_id"] == LOOP_STEP
    )
    back_dispatched, back_evidence, back_event = run_operation(
        base, first_entry["state"], loop_one, "d2-113-loop-a", route_label="CONTINUE"
    )
    retained = loop_back_edge(base, back_dispatched, back_evidence, back_event)

    # The case: the second object's region head completes and enters the same loop for the first
    # time in its own context.
    case_dispatched, case_evidence, case_event = run_operation(
        base, retained["state"], object_head(retained["state"], "2"), "d2-113"
    )
    expected = loop_entry(base, case_dispatched, case_evidence, case_event)

    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(
        GROUP / "D2-113.json",
        exact_case(
            "D2-113", "step", step_input(base, case_dispatched["state"], case_event), expected, [],
            "The first frozen object has already entered this loop and taken its declared back edge, so the state retains pass 2 for the pair of this loop and that object's enclosing prefix, which is the declared maximum. The second object's region head now completes and its declared SEQUENCE relationship reaches the loop entry. COMP-002 makes two things decisive. Pass one begins when the entry is first activated from outside the loop, and only taking the declared back edge increments a pass; entry from outside allocates pass 1 outright. The retained pass is also keyed on the pair of loop identifier and exact outer enclosing prefix, and a new object context begins at one, so the first object's pass 2 is not in scope for this allocation at all. The new occurrence therefore carries pass 1 and no loop bound is approached, let alone crossed. LIFE-016 fixes its shape: one LOOP segment with the loop identifier and current pass, with the fan-out segment retained ahead of it in outer-to-inner order, and the top-level object key equal to the innermost fan-out segment's key. FAN-001 and PAR-001 fix the obligation consequence: an eligible direct route inside the object region replaces the obligation's expected occurrence and required operation atomically rather than discharging it, so the all-done join stays pending. LIFE-006 gives a MATCHED effect with no stop condition and no disputed budget an empty reason set, and the decision carries EFFECT and ROUTE details, the ROUTE naming the one selected relationship and no construct because the closure traverses no split, expansion or join.",
        ),
    )


def main() -> None:
    build()
    print(json.dumps({"case_ids": ["D2-113"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
