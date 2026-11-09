#!/usr/bin/env python3
"""Build D2-251: an ACTIVE checkpoint holding a pass whose complete inventory is DISCHARGED, unjoined.

The vector is decisive only if nothing else is wrong with the state. It starts from a reachable ACTIVE
state: branch-b's single fan-out object completes, the child pass joins, and branch-b's parent
obligation discharges with a CHILD_PASS basis while branch-a stays OPEN. The checkpoint reverses
exactly the join markers (object obligation DISCHARGED, pass not joined, parent WAITING on the pass).
The joined state is admitted on restart; the reversed one is refused.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from checkpoint_reseal import reseal_last_transition
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from lifecycle_factory import admitted_transition, governed_effect_event, governed_native_evidence, governed_outcome, stateful_refusal, step_input


def _module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LATE = _module("stopped_fanout_late", "build-stopped-fanout-late-case.py")
CONTROLS = _module("restart_admission_controls", "build-restart-admission-controls.py")
GROUP = CASES / "unjoined-pass-checkpoint"


def object_join_result(base: dict, dispatched: dict, event: dict) -> dict:
    """The object's matching effect discharges its obligation, joins the child pass and discharges the parent."""
    occurrence_value = event["permit"]["occurrence"]
    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    relationships = base["definition"]["relationships"]
    to_join = digest("relationship", next(row for row in relationships if row["kind"] == "SEQUENCE" and row["from"] == LATE.OBJECT))
    join_out = digest("relationship", next(row for row in relationships if row["kind"] == "SEQUENCE" and row["from"] == "fanout-b-join"))

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [row for row in state["active"] if row["occurrence"]["occurrence_id"] != occurrence_value["occurrence_id"]]
        state["completed"].append({
            "occurrence": copy.deepcopy(occurrence_value), "disposition": "SUCCEEDED", "evidence_digest": evidence_digest,
            "occurred_at": event["native_evidence"]["event_time"], "route_label": None,
            "selected_relationship_digest": to_join, "late": False,
        })
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        child = next(row for row in state["obligations"] if row["expected_occurrence_id"] == occurrence_value["occurrence_id"])
        child.update({
            "status": "JOINED", "expected_occurrence_id": None, "required_operation": None,
            "completion_basis": {
                "kind": "DIRECT_EVENT", "event_digest": event_digest, "occurrence_id": occurrence_value["occurrence_id"],
                "operation": event["permit"]["native_request"]["operation"], "evidence_digest": evidence_digest,
            },
        })
        next(row for row in state["fanout_passes"] if row["fanout_id"] == LATE.FANOUT_ID)["joined"] = True
        parent = next(row for row in state["obligations"] if row["status"] == "WAITING" and row["waiting_on"]["construct_id"] == LATE.FANOUT_ID)
        parent.update({
            "status": "DISCHARGED", "waiting_on": None,
            "completion_basis": {"kind": "CHILD_PASS", "event_digest": event_digest, "child_pass": copy.deepcopy(parent["waiting_on"])},
        })

    return admitted_transition(
        dispatched["state"], event, disposition="COMPLETED", reason_codes=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
            # LIFECYCLE.md:289 names every construct whose join the closure traverses. The fan-out join's
            # outgoing edge reaches the enclosing parallel join, which does not fire because branch-a
            # is OPEN; a direct branch arrival at that same unfired join names the block too.
            {"kind": "ROUTE", "relationship_digests": sorted([to_join, join_out], key=lambda value: value.encode("utf-8")), "construct_ids": sorted([LATE.FANOUT_ID, "parallel-1"], key=lambda value: value.encode("utf-8"))},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


def unjoin(state: dict) -> dict:
    """Reverse only the join markers of the child pass."""
    reversed_state = copy.deepcopy(state)
    for row in reversed_state["obligations"]:
        if row["kind"] == "FANOUT_OBJECT" and row["construct_id"] == LATE.FANOUT_ID:
            row["status"] = "DISCHARGED"
        elif row["status"] == "DISCHARGED" and (row["completion_basis"] or {}).get("kind") == "CHILD_PASS":
            row["waiting_on"] = copy.deepcopy(row["completion_basis"]["child_pass"])
            row["status"] = "WAITING"
            row["completion_basis"] = None
    next(row for row in reversed_state["fanout_passes"] if row["fanout_id"] == LATE.FANOUT_ID)["joined"] = False
    reseal_last_transition(reversed_state)
    return reversed_state


def fixture() -> dict:
    base, permitted, dispatched = LATE.object_dispatched_fixture()
    selected = LATE.SIBLINGS.dispatch_digest(dispatched, "dispatch-d2-250-object-b")
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-251", native_operation_id="native-d2-251-object-b",
        dispatch_digest=selected,
    )
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-d2-251-object-b", dispatch_digest=selected)
    joined = object_join_result(base, dispatched, event)
    return {"base": base, "before": dispatched, "event": event, "joined": joined, "unjoined": unjoin(joined["state"])}


def build() -> None:
    parts = fixture()
    state = parts["unjoined"]
    probe = CONTROLS.clock_event(state, "clock-d2-251")
    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(
        GROUP / "D2-251.json",
        exact_case(
            "D2-251", "step", step_input(parts["base"], state, probe), stateful_refusal(state, "STATE_INVALID"), [],
            "A parallel block has two branches; branch-b expanded a frozen fan-out to one object, so branch-b's obligation waits on that child pass, and branch-a is still OPEN, which keeps the instance ACTIVE. The object's governed effect has completed it and its obligation is DISCHARGED with a direct basis, but the child pass is not joined and the parent still waits on it. In the reachable state that one effect produces, the child pass joins in the same transition: the object obligation is JOINED, the pass is joined, and the parent discharges with a CHILD_PASS basis. This checkpoint reverses exactly those markers and nothing else, with the last receipt and replay recommitted to the reversed state so that no stale history commitment is the fault. LIFE-019 states that if an ACTIVE state contains a pass whose complete obligation inventory is DISCHARGED, the checkpoint is invalid because the eligible join should have fired atomically, and PAR-001 fixes that atomicity: when every obligation in the exact child-pass reference is DISCHARGED during an eligible transition, the child join marks them JOINED and resumes the parent. The STOPPED exception does not apply to an ACTIVE instance with no stop decision. The checkpoint is refused before the CLOCK event is considered, returning the exact supplied state and creating no receipt.",
        ),
    )


def main() -> None:
    build()
    print(json.dumps({"case_ids": ["D2-251"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
