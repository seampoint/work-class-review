#!/usr/bin/env python3
"""Build the repair-round controls for restart admission.

Each refusal pins one LIFE-019 rule from the gate-2 repair round (derivations sealed 2026-09-13) with a
checkpoint that violates only that rule; each admitted control restarts from the committed checkpoint the
rule must keep admitting. Expected results are derived with the fixture helpers, never taken from a consumer.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from checkpoint_reseal import reseal_last_transition
from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_factory import stateful_refusal


def _module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESTART = _module("restart_admission_controls", "build-restart-admission-controls.py")
GROUP = CASES / "repair-round-restart-controls"


def load(relative: str) -> dict:
    return json.loads((CASES / relative).read_text())


def emit(case_id: str, input_value: dict, expected: dict, requirements: list[str], derivation: str) -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(GROUP / f"{case_id}.json", exact_case(case_id, "step", input_value, expected, requirements, derivation))


def refuse_stale_last_receipt() -> None:
    case = load("branch-routes/D2-114.json")
    state = copy.deepcopy(case["expected"]["state"])
    assert [row["source"] for row in state["clocks"]] == ["authority-clock"]
    state["clocks"][0]["evidence_digest"] = digest("provider-native-record", {"record": "C2-STALE-LAST-RECEIPT"})
    event = RESTART.clock_event(state, "clock-c2-stale-last-receipt")
    emit(
        "C2-refuse-stale-last-receipt", RESTART.restart_input(case, state, event), stateful_refusal(state, "STATE_INVALID"), ["LIFE-019"],
        "The checkpoint is D2-114's result with the evidence digest of its one retained authority-clock sample changed and the last transition not recommitted, so the last receipt's state_after_core_digest no longer hashes the supplied core. No other record in the state binds that evidence digest: the clock event preimage is host-retained and the state carries only its event digest, and the deployment authorization clock is a separate record. A fresh available CLOCK sample asks the consumer to restart from the checkpoint. LIFE-019 has the consumer hash the resulting core as state_after_core_digest before appending the receipt, and refuse any changed digest, missing record or broken binding as STATE_INVALID before applying the next event. The refusal returns the exact supplied state.",
    )


def restart_routed_branch_occurrence() -> None:
    case = load("branch-routes/D2-114.json")
    state = case["expected"]["state"]
    definition = case["input"]["definition"]
    heads = {branch["id"]: branch["head_step_id"] for block in definition["parallel_blocks"] for branch in block["branches"]}
    steps = {row["occurrence"]["occurrence_id"]: row["occurrence"]["step_id"] for row in state["active"]}
    assert any(row["status"] == "OPEN" and steps[row["expected_occurrence_id"]] != heads[row["branch_id"]] for row in state["obligations"])
    event = RESTART.clock_event(state, "clock-c2-restart-routed-branch")
    emit(
        "C2-restart-routed-branch-occurrence", RESTART.restart_input(case, state, event), RESTART.clock_recorded(state, event), ["LIFE-019", "PAR-001"],
        "The checkpoint is D2-114's result: a branch head routed onward to another operation inside the same branch, so that branch's OPEN obligation names an occurrence that is not the branch head. A fresh available CLOCK sample asks the consumer to restart from the checkpoint. PAR-001 lets an eligible direct route within the same branch replace the expected occurrence and required operation atomically, and the routed occurrence's innermost branch segment is the obligation's own, so the direct ownership rule holds and LIFE-019 admits the checkpoint. The CLOCK sample is recorded with no other change.",
    )


def refuse_outer_obligation_naming_child_occurrence() -> None:
    case = load("nested-parallel-closure/D2-243.json")
    state = copy.deepcopy(case["expected"]["state"])
    steps = {row["id"]: row for row in case["input"]["definition"]["steps"]}
    child = next(row["occurrence"] for row in state["active"] if row["occurrence"]["step_id"] == "child-a")
    outer = next(row for row in state["obligations"] if row["construct_id"] == "parallel-1" and row["status"] == "WAITING")
    outer.update(status="OPEN", expected_occurrence_id=child["occurrence_id"], required_operation=steps["child-a"]["operation"], waiting_on=None)
    reseal_last_transition(state)
    event = RESTART.clock_event(state, "clock-c2-outer-names-child")
    emit(
        "C2-refuse-outer-obligation-naming-child-occurrence", RESTART.restart_input(case, state, event), stateful_refusal(state, "STATE_INVALID"), ["LIFE-019", "PAR-001"],
        "The checkpoint is D2-243's result, in which the outer block's branch obligation waits on the exact inner child pass and the inner branch child-a is active. The outer obligation is rewritten as OPEN naming the child-a occurrence and its operation, with no waiting reference, and the last transition is recommitted to the rewritten core, so the receipt binding holds and only the ownership rule is violated. A fresh available CLOCK sample asks the consumer to restart. COMPOSITION gives ownership of an occurrence to the innermost branch or object region only; an enclosing parent obligation is WAITING on the exact child pass and does not also name the inner occurrence. LIFE-019 admits an OPEN obligation only when the occurrence it names belongs directly to its branch or object region. The child-a occurrence's innermost branch segment belongs to the inner block, so the consumer refuses the checkpoint as STATE_INVALID and returns the exact supplied state.",
    )


def restart_nested_child_branch() -> None:
    case = load("nested-parallel-closure/D2-243.json")
    state = case["expected"]["state"]
    assert any(row["construct_id"] == "parallel-1" and row["status"] == "WAITING" for row in state["obligations"])
    event = RESTART.clock_event(state, "clock-c2-restart-nested-child")
    emit(
        "C2-restart-nested-child-branch", RESTART.restart_input(case, state, event), RESTART.clock_recorded(state, event), ["LIFE-019", "PAR-001"],
        "The checkpoint is D2-243's result: the outer block's branch obligation waits on the exact inner child pass, and each inner branch obligation names an active occurrence whose innermost branch segment is its own while the outer branch segment stays in the enclosing prefix. A fresh available CLOCK sample asks the consumer to restart. The direct ownership rule holds for every OPEN obligation, so LIFE-019 admits the checkpoint and the CLOCK sample is recorded with no other change.",
    )


BUILDERS = [refuse_stale_last_receipt, restart_routed_branch_occurrence, refuse_outer_obligation_naming_child_occurrence, restart_nested_child_branch]


def main() -> None:
    for build in BUILDERS:
        build()
    print(json.dumps({"output": str(GROUP), "case_ids": sorted(path.stem for path in GROUP.glob("*.json"))}, indent=2))


if __name__ == "__main__":
    main()
