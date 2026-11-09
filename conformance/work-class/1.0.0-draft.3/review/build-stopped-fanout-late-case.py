#!/usr/bin/env python3
"""Build D2-250: a late matching effect for the one object of a fan-out in a stopped instance.

LIFE-012 closes the still-active, non-BLOCKED_DISPUTE object as a late success and discharges its
directly owning obligation without firing the join. The fan-out pass is left all-DISCHARGED and not
JOINED, which LIFE-019 admits only in a STOPPED checkpoint whose retained stop decision and direct
completion basis prove the join was suppressed.

The stop has to come from outside the object region, since every fan-out stop mode creates zero
objects. This is D2-149's stopped-sibling shape with the surviving branch replaced by a one-object
fan-out: branch-a declares failure and stops the instance while branch-b's object is dispatched.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from composition_fixture import add_authority_operations, parallel_definition, parallel_entry_result
from corpus_common import CASES, exact_case, write_canonical_json
from fixture_factory import structural_step, typed
from lifecycle_factory import (
    base_lifecycle, dispatch_event, dispatch_result, governed_effect_event, governed_native_evidence,
    permitted_proposal, step_input,
)


def _module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SIBLINGS = _module("stopped_siblings", "build-stopped-sibling-cases.py")
PREFIX = _module("fanout_outer_prefix", "build-fanout-outer-prefix-case.py")
GROUP = CASES / "stopped-fanout-late"
BRANCHES = ["branch-a", "expand-b"]
OBJECT = "object-b"
FANOUT_ID = "fanout-b"


def definition_mutator(definition: dict) -> None:
    parallel_definition(BRANCHES)(definition)
    next(row for row in definition["steps"] if row["id"] == "expand-b")["kind"] = "FANOUT_EXPAND"
    definition["steps"].append(structural_step("fanout-b-join", "FANOUT_JOIN"))
    definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
    definition["relationships"] = [
        row for row in definition["relationships"] if row.get("from") != "expand-b"
    ]
    definition["relationships"][-1:-1] = [
        {"kind": "SEQUENCE", "from": OBJECT, "to": "fanout-b-join"},
        {"kind": "SEQUENCE", "from": "fanout-b-join", "to": "parallel-join"},
    ]
    definition["fanouts"] = [{
        "id": FANOUT_ID, "expand_step_id": "expand-b", "region_head_step_id": OBJECT,
        "join_step_id": "fanout-b-join", "object_field": "items", "object_request_field": "card_id",
        "object_type_ref": "IDENTITY", "empty_set_behavior": "ADVANCE_TO_JOIN",
    }]
    definition["occurrence_limits"].sort(key=lambda row: row["step_id"].encode("utf-8"))


def object_dispatched_fixture() -> tuple[dict, dict, dict]:
    """The ACTIVE parallel block with branch-b's single fan-out object permitted and dispatched."""
    base = base_lifecycle(
        authority_mutator=add_authority_operations(BRANCHES + [OBJECT]),
        definition_mutator=definition_mutator,
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-d2-250-entry", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-250-entry", native_operation_id="native-d2-250-entry"
    )
    entry = parallel_entry_result(
        base, dispatched, governed_effect_event(permitted, dispatched, evidence, event_id="effect-d2-250-entry"), BRANCHES
    )

    # Branch-b expands to exactly one object; its branch obligation waits on the child pass.
    expand = SIBLINGS.occurrence_for(entry["state"], "expand-b")
    _p, permitted_x, dispatched_x = SIBLINGS.propose_and_dispatch(base, entry["state"], expand, suffix="d2-250-expand-b")
    key = typed("IDENTITY", "card-d2-250")
    x_dispatch = SIBLINGS.dispatch_digest(dispatched_x, "dispatch-d2-250-expand-b")
    x_evidence = governed_native_evidence(
        base, permitted_x, dispatched_x, evidence_id="evidence-d2-250-expand-b",
        native_operation_id="native-d2-250-expand-b",
        collections=[{"name": "items", "element_type_ref": "IDENTITY", "values": [copy.deepcopy(key)]}],
        dispatch_digest=x_dispatch,
    )
    x_event = governed_effect_event(permitted_x, dispatched_x, x_evidence, event_id="effect-d2-250-expand-b", dispatch_digest=x_dispatch)
    branch_2 = next(
        row["obligation_id"] for row in dispatched_x["state"]["obligations"]
        if row.get("expected_occurrence_id") == expand["occurrence_id"]
    )
    expanded = PREFIX.multi_expansion(base, dispatched_x, x_event, FANOUT_ID, [key], parent_obligation_id=branch_2)

    object_occurrence = SIBLINGS.occurrence_for(expanded["state"], OBJECT)
    _p, permitted_o, dispatched_o = SIBLINGS.propose_and_dispatch(base, expanded["state"], object_occurrence, suffix="d2-250-object-b")
    return base, permitted_o, dispatched_o


def build() -> None:
    # The object is permitted and dispatched before the sibling stops the instance.
    base, permitted_o, dispatched_o = object_dispatched_fixture()
    branch_a = SIBLINGS.occurrence_for(dispatched_o["state"], "branch-a")
    _p, permitted_a, dispatched_a = SIBLINGS.propose_and_dispatch(base, dispatched_o["state"], branch_a, suffix="d2-250-stop-a")
    failure = SIBLINGS.branch_failure_event(base, permitted_a, dispatched_a, suffix="d2-250-stop-a")
    stopped = SIBLINGS.branch_failure_stop_result(base, dispatched_a, failure)

    o_dispatch = SIBLINGS.dispatch_digest(stopped, "dispatch-d2-250-object-b")
    o_evidence = governed_native_evidence(
        base, permitted_o, stopped, evidence_id="evidence-d2-250", native_operation_id="native-d2-250-object-b",
        dispatch_digest=o_dispatch,
    )
    event = governed_effect_event(permitted_o, stopped, o_evidence, event_id="effect-d2-250", dispatch_digest=o_dispatch)
    expected = SIBLINGS.late_sibling_result(base, stopped, event)

    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(
        GROUP / "D2-250.json",
        exact_case(
            "D2-250", "step", step_input(base, stopped["state"], event), expected, [],
            "Branch-b expanded a frozen fan-out to exactly one object, whose occurrence was permitted and dispatched, and branch-b's obligation waits on that child pass. Branch-a then declared failure under failure_behavior STOP, which stopped the instance while the object occurrence remained active and was never BLOCKED_DISPUTE. No shared budget is declared. The object's first matching effect now arrives. LIFE-012 classifies a matching effect after instance stop as LATE_MATCHED and fixes the consequence for a still-active, non-blocked occurrence in a stopped instance: it moves to completed with late true, null route fields and the LIFE-010 evidence-derived disposition SUCCEEDED, and its directly owning obligation discharges with a DIRECT_EVENT basis without firing the join. The directly owning obligation is the fan-out object obligation, the innermost region; branch-b's parent obligation stays WAITING, because stopped-instance late evidence that prevents the child join does not manufacture parent completion. The fan-out pass is therefore all-DISCHARGED and not JOINED. LIFE-019 forbids that in an ACTIVE checkpoint but admits it in a STOPPED one exactly when the retained stop decision and the direct completion basis prove the join was suppressed by stopped-instance late evidence, which this state supplies. LIFE-006 maps EFFECT_OBSERVED/LATE_MATCHED to LATE_EFFECT, with no budget row to add. The instance stays STOPPED. FAN-001 fixes the object's region identity and its single object pass.",
        ),
    )


def main() -> None:
    build()
    print(json.dumps({"case_ids": ["D2-250"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
