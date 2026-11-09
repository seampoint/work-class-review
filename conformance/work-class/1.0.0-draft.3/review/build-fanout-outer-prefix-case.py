#!/usr/bin/env python3
"""Build D2-115: the same fan-out entered first under a different outer enclosing prefix.

COMP-002 keys the pass counter on the pair (construct_id, exact outer enclosing prefix), so the
same inner fan-out entered under a second outer object is a first entry in that context and
receives pass 1 rather than pass 2. LIFE-018 and FAN-001 state the same rule from the other side
and make clear this is not the excluded repeat-expansion case.

The nested fan-out fixture in `build-nested-fanout-binding-case.py` expands one object per
expansion; the multi-object expansion below is the generalisation this case needs.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from composition_fixture import add_authority_operations, permitted_operation_proposal
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import occurrence, typed
from lifecycle_factory import (
    admitted_transition, base_lifecycle, dispatch_event, dispatch_result, governed_effect_event,
    governed_native_evidence, governed_outcome, permitted_proposal, step_input,
)


def _nested_module():
    path = Path(__file__).resolve().parent / "build-nested-fanout-binding-case.py"
    spec = importlib.util.spec_from_file_location("nested_fanout_binding", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NESTED = _nested_module()
GROUP = CASES / "fanout-outer-prefix"
MAX_OBJECTS = "2"


def definition_mutator(definition: dict) -> None:
    NESTED.nested_fanout_definition(definition)
    # The per-expansion object maximum is the fan-out bound. The per-step occurrence limit is a
    # separate instance-wide bound and must not be the binding constraint for this case, so it
    # allows the first expansion's object plus this expansion's two.
    definition["limits"]["maximum_fanout_objects"] = MAX_OBJECTS
    for row in definition["occurrence_limits"]:
        if row["step_id"] == "outer-expand":
            row["maximum"] = "2"
        elif row["step_id"] == "inner-operation":
            row["maximum"] = "3"


def execute_expand_multi(base: dict, state: dict, occurrence_value: dict, event_id: str, collection_name: str, keys: list[dict]):
    """`execute_expand`, with a collection carrying every object key rather than one."""
    if occurrence_value["step_id"] == base["definition"]["root"]:
        permitted = permitted_proposal(base)
    else:
        proposal, authority_result = NESTED.proposal_for_nested_occurrence(
            base, state, occurrence_value, "proposal-" + event_id
        )
        permitted = permitted_operation_proposal(base, state, proposal, authority_result)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-" + event_id, acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(
        permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED"
    )
    dispatch_digest = next(
        row["dispatch_digest"] for row in dispatched["state"]["dispatches"] if row["event_id"] == dispatch["event_id"]
    )
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-" + event_id,
        native_operation_id="native-" + event_id,
        collections=[{
            "name": collection_name, "element_type_ref": "IDENTITY",
            "values": [copy.deepcopy(key) for key in keys],
        }],
        dispatch_digest=dispatch_digest,
    )
    effect = governed_effect_event(
        permitted, dispatched, evidence, event_id="effect-" + event_id, dispatch_digest=dispatch_digest
    )
    return permitted, dispatched, effect


def multi_expansion(base: dict, dispatched: dict, event: dict, fanout_id: str, keys: list[dict], parent_obligation_id=None, pass_value: str = "1"):
    """One nonempty expansion allocating an object occurrence and obligation per key."""
    fanout = next(row for row in base["definition"]["fanouts"] if row["id"] == fanout_id)
    source = event["permit"]["occurrence"]
    head = fanout["region_head_step_id"]
    # FAN-001: the pass retains the source-ordered object key list and the allocation rule derives
    # occurrence ordinals in that order. Ordinals continue per step across the instance.
    existing = sum(
        1 for row in dispatched["state"]["active"] + dispatched["state"]["completed"]
        if row["occurrence"]["step_id"] == head
    )
    operation = next(row["operation"] for row in base["definition"]["steps"] if row["id"] == head)
    rows, obligations = [], []
    for index, key in enumerate(keys, start=existing):
        enclosing = copy.deepcopy(source["enclosing"]) + [{
            "kind": "FANOUT", "construct_id": fanout["id"], "pass": pass_value,
            "branch_id": None, "object_key": copy.deepcopy(key),
        }]
        child = occurrence(
            base["definition_digest"], source["instance_id"], head, str(index + 1),
            [source["occurrence_id"]], enclosing, object_key=key,
        )
        rows.append(child)
        subject = {
            "kind": "FANOUT_OBJECT", "construct_id": fanout["id"], "pass": pass_value,
            "source_occurrence_ids": [source["occurrence_id"]], "branch_id": None,
            "object_key": copy.deepcopy(key), "join_step_id": fanout["join_step_id"],
        }
        obligations.append({
            "obligation_id": digest("obligation", subject), **subject,
            "creation_event_digest": digest("runtime-event", event), "status": "OPEN",
            "expected_occurrence_id": child["occurrence_id"], "required_operation": operation,
            "waiting_on": None, "completion_basis": None,
        })

    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    pass_row = {
        "fanout_id": fanout_id, "pass": pass_value, "expand_occurrence_id": source["occurrence_id"],
        "object_keys": [copy.deepcopy(key) for key in keys],
        "obligation_ids": [row["obligation_id"] for row in obligations], "joined": False,
    }

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [
            row for row in state["active"] if row["occurrence"]["occurrence_id"] != source["occurrence_id"]
        ]
        state["completed"].append({
            "occurrence": copy.deepcopy(source), "disposition": "SUCCEEDED",
            "evidence_digest": evidence_digest, "occurred_at": event["native_evidence"]["event_time"],
            "route_label": None, "selected_relationship_digest": None, "late": False,
        })
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        for child in rows:
            state["active"].append({
                "occurrence": copy.deepcopy(child), "activation_event_digest": event_digest,
                "status": "ACTIVE", "deadline_ids": [],
            })
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["obligations"].extend(copy.deepcopy(row) for row in obligations)
        if parent_obligation_id is not None:
            # FAN-001: a successful nonempty expansion of an expand occurrence directly owned by an
            # outer obligation moves that obligation to WAITING on the exact child-pass reference.
            parent = next(row for row in state["obligations"] if row["obligation_id"] == parent_obligation_id)
            parent["status"] = "WAITING"
            parent["expected_occurrence_id"] = None
            parent["required_operation"] = None
            parent["waiting_on"] = {
                "kind": "FANOUT", "construct_id": fanout_id, "pass": pass_value,
                "outer_enclosing": copy.deepcopy(source["enclosing"]),
                # LIFE-019: "child-pass obligation IDs" use raw UTF-8 order; the pass row keeps
                # source order.
                "obligation_ids": sorted((row["obligation_id"] for row in obligations), key=lambda value: value.encode("utf-8")),
            }
        state["obligations"].sort(key=lambda row: row["obligation_id"].encode("utf-8"))
        state["fanout_passes"].append(copy.deepcopy(pass_row))
        state["fanout_passes"].sort(key=lambda row: (
            row["fanout_id"].encode("utf-8"), int(row["pass"]), row["expand_occurrence_id"].encode("utf-8")
        ))
        counter = next(row for row in state["step_counters"] if row["step_id"] == head)
        counter["activations"] = str(int(counter["activations"]) + len(rows))
        state["total_activations"] = str(int(state["total_activations"]) + len(rows))

    return admitted_transition(
        dispatched["state"], event, disposition="COMPLETED", reason_codes=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [], "construct_ids": [fanout_id]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


def build() -> None:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(["outer-expand", "inner-operation"]),
        definition_mutator=definition_mutator,
    )
    outer_keys = [typed("IDENTITY", "outer-card-1"), typed("IDENTITY", "outer-card-2")]
    _permitted, outer_dispatched, outer_event = execute_expand_multi(
        base, base["clock_result"]["state"], base["proposal_event"]["occurrence"],
        "d2-115-outer", "outer_items", outer_keys,
    )
    outer = multi_expansion(base, outer_dispatched, outer_event, "fanout-outer", outer_keys)

    def outer_object(state, ordinal):
        return next(
            row["occurrence"] for row in state["active"]
            if row["occurrence"]["step_id"] == "outer-expand" and row["occurrence"]["ordinal"] == ordinal
        )

    def obligation_for(state, occurrence_id):
        return next(
            row["obligation_id"] for row in state["obligations"]
            if row.get("expected_occurrence_id") == occurrence_id
        )

    # Setup: the inner fan-out expands under the first outer object, retaining pass 1 for that pair.
    first_outer = outer_object(outer["state"], "1")
    first_keys = [typed("IDENTITY", "inner-card-1a")]
    _p, first_dispatched, first_event = execute_expand_multi(
        base, outer["state"], first_outer, "d2-115-inner-first", "inner_items", first_keys
    )
    first_inner = multi_expansion(
        base, first_dispatched, first_event, "fanout-inner", first_keys,
        parent_obligation_id=obligation_for(outer["state"], first_outer["occurrence_id"]),
    )

    # The case: the same inner fan-out under the second outer object, a different outer prefix,
    # with the set at the per-expansion object maximum.
    second_outer = outer_object(first_inner["state"], "2")
    second_keys = [typed("IDENTITY", "inner-card-2a"), typed("IDENTITY", "inner-card-2b")]
    _p2, second_dispatched, second_event = execute_expand_multi(
        base, first_inner["state"], second_outer, "d2-115", "inner_items", second_keys
    )
    expected = multi_expansion(
        base, second_dispatched, second_event, "fanout-inner", second_keys,
        parent_obligation_id=obligation_for(first_inner["state"], second_outer["occurrence_id"]),
    )

    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(
        GROUP / "D2-115.json",
        exact_case(
            "D2-115", "step", step_input(base, second_dispatched["state"], second_event), expected, [],
            "The inner fan-out has already expanded under the first outer object, retaining pass 1 for the pair of that construct and that outer enclosing prefix. COMP-002 keys the counter on exactly that pair: pass numbers are one plus the largest retained pass for the pair, or one on first entry in that context. This expansion is under the second outer object, a different exact outer prefix, so it is a first entry in its own context and allocates pass 1 rather than pass 2. LIFE-018 and FAN-001 state the same rule from the other side and make clear this is not the excluded repeat-expansion case, which is re-entry under the same outer prefix. The supplied set is at the per-expansion object maximum, which is the largest admissible set rather than a refusal; the separate instance-wide occurrence and active-obligation limits still apply and are not crossed. FAN-001 fixes the resulting rows: the pass retains the source-ordered object key list, occurrence ordinals follow that order, each object occurrence carries the fan-out pass identity, object key and complete enclosing ancestry including the outer object key, and because the expand occurrence is directly owned by an outer obligation that obligation moves to WAITING on the exact child-pass reference in the same transition.",
        ),
    )


def main() -> None:
    build()
    print(json.dumps({"case_ids": ["D2-115"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
