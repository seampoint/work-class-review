#!/usr/bin/env python3
"""Build restart-admission controls for state that conforming transitions produce.

Each control pins one LIFE-019 admission rule that no committed vector discriminated: a checkpoint a
conforming implementation emits must be admitted on restart, and the minimal violation of the rule
must be refused. Restart is exercised with a fresh available CLOCK sample, which admits the state and
changes nothing else.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from corpus_common import CASES, digest, exact_case, write_canonical_json
from fixture_factory import add_seconds, available_clock, typed
from checkpoint_reseal import reseal_last_transition
from lifecycle_factory import admitted_transition, base_lifecycle, state_digest, stateful_refusal, step_input


def _module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFIX = _module("fanout_outer_prefix", "build-fanout-outer-prefix-case.py")
GROUP = CASES / "restart-admission-controls"
SOURCE = "authority-clock"


def load(relative: str) -> dict:
    return json.loads((CASES / relative).read_text())


def next_clock(state: dict) -> dict:
    rows = [row for row in state["clocks"] if row["source"] == SOURCE]
    latest = max(rows, key=lambda row: int(row["revision"]))
    return available_clock(SOURCE, str(int(latest["revision"]) + 1), add_seconds(latest["observed_time"], "60"))


def clock_event(state: dict, event_id: str) -> dict:
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "CLOCK",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "clock": next_clock(state),
        "activation_clocks": [],
    }


def clock_recorded(state: dict, event: dict) -> dict:
    clock = event["clock"]

    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    return admitted_transition(
        state, event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]}],
        mutate=mutate,
    )


def restart_input(case: dict, state: dict, event: dict) -> dict:
    value = copy.deepcopy(case["input"])
    value["state"] = copy.deepcopy(state)
    value["state_digest"] = state_digest(state)
    value["event"] = event
    return value


def emit(case_id: str, input_value: dict, expected: dict, requirements: list[str], derivation: str) -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(GROUP / f"{case_id}.json", exact_case(case_id, "step", input_value, expected, requirements, derivation))


def restart_after_outer_prefix() -> None:
    case = load("fanout-outer-prefix/D2-115.json")
    state = case["expected"]["state"]
    event = clock_event(state, "clock-restart-outer-prefix")
    emit(
        "C2-restart-fanout-outer-prefix", restart_input(case, state, event), clock_recorded(state, event),
        ["LIFE-019", "FAN-001"],
        "The checkpoint is D2-115's resulting state: the same inner fan-out holds two pass-1 rows under two different outer objects, and each outer object's obligation waits on its own child pass. LIFE-019 requires a WAITING obligation to name one existing unique child pass with the exact kind, construct, pass, common outer enclosing prefix and complete obligation inventory, and COMPOSITION states that outer_enclosing distinguishes passes whose numerical pass values restart in different contexts. Fan-out passes are keyed by fan-out identifier, pass and expand occurrence, so admission must select each reference's pass by its outer prefix rather than by construct and pass number alone. Both references resolve, so the checkpoint is admitted, and the available CLOCK sample is retained with an empty reason set and no other change.",
    )


def restart_after_disputed_frontier() -> None:
    case = load("branch-routes/D2-256.json")
    state = case["expected"]["state"]
    event = clock_event(state, "clock-restart-disputed-frontier")
    emit(
        "C2-restart-disputed-completion-frontier", restart_input(case, state, event), clock_recorded(state, event),
        ["LIFE-013", "LIFE-019"],
        "The checkpoint is D2-256's resulting state: in one branch operation A routed to B, B discharged the branch obligation, and a later conflicting record disputed A, so the obligation became DISPUTED while retaining its completion basis. That basis's frontier is B alone, not A. LIFE-019 admits a completion-based DISPUTED obligation whose former discharge frontier intersects the dependency-affected set of a retained completed occurrence with disputed conclusive evidence, and restart recomputes that set from predecessor lists under LIFE-013, which defines it as the disputed occurrence and every transitive active or completed descendant. B descends from A, so the intersection is nonempty and the checkpoint is admitted. The available CLOCK sample is retained with an empty reason set and no other change.",
    )


def refuse_branch_head_source_mismatch() -> None:
    case = load("waiting-parent-proposal/D2-247.json")
    state = copy.deepcopy(case["input"]["state"])
    occurrences = {
        row["occurrence"]["step_id"] + "#" + row["occurrence"]["ordinal"]: row["occurrence"]["occurrence_id"]
        for row in state["active"] + state["completed"]
    }
    for obligation in state["obligations"]:
        if obligation["construct_id"] == "parallel-1" and obligation["branch_id"] == "branch-2":
            obligation["source_occurrence_ids"] = [occurrences["outer-a#1"]]
            identity = {key: obligation[key] for key in ("kind", "construct_id", "pass", "source_occurrence_ids", "branch_id", "object_key", "join_step_id")}
            obligation["obligation_id"] = digest("obligation", identity)
    state["obligations"].sort(key=lambda row: row["obligation_id"].encode("utf-8"))
    reseal_last_transition(state)
    event = clock_event(state, "clock-refuse-branch-source")
    emit(
        "C2-refuse-branch-head-source-mismatch", restart_input(case, state, event), stateful_refusal(state, "STATE_INVALID"),
        ["LIFE-019", "PAR-001"],
        "This is D2-247's admitted checkpoint with one change: the outer block's second branch obligation records source_occurrence_ids naming the completed first-branch head rather than the issue occurrence, with its identifier recomputed and the last receipt and replay recommitted to the changed state so that no stale history commitment is the fault. Its expected occurrence is still that branch's head, whose predecessors name the issue occurrence, and the sibling branch obligation still names the issue occurrence. COMPOSITION requires every new branch occurrence to copy the current structural frontier into its predecessors and each obligation's source_occurrence_ids to equal that same frontier, both immutable, and LIFE-019 makes a retained obligation set or occurrence path that disagrees STATE_INVALID on restart. An onward route moves only the obligation's expected occurrence, so the equality is judged against the region head. The checkpoint is refused before the CLOCK event is considered, returning the exact supplied state.",
    )


def unsorted_inner_keys(base: dict, source: dict) -> list[dict]:
    """Two object keys in a source order that differs from their obligation identifiers' raw order."""
    keys = [typed("IDENTITY", "inner-card-a"), typed("IDENTITY", "inner-card-b")]

    def obligation_id(key: dict) -> str:
        return digest("obligation", {
            "kind": "FANOUT_OBJECT", "construct_id": "fanout-inner", "pass": "1",
            "source_occurrence_ids": [source["occurrence_id"]], "branch_id": None,
            "object_key": key, "join_step_id": "inner-join",
        })

    ids = [obligation_id(key) for key in keys]
    return keys if ids != sorted(ids, key=lambda value: value.encode("utf-8")) else list(reversed(keys))


def waiting_order_cases() -> None:
    base = base_lifecycle(
        authority_mutator=PREFIX.add_authority_operations(["outer-expand", "inner-operation"]),
        definition_mutator=PREFIX.definition_mutator,
    )
    outer_keys = [typed("IDENTITY", "outer-card-1")]
    _p, outer_dispatched, outer_event = PREFIX.execute_expand_multi(
        base, base["clock_result"]["state"], base["proposal_event"]["occurrence"], "order-outer", "outer_items", outer_keys,
    )
    outer = PREFIX.multi_expansion(base, outer_dispatched, outer_event, "fanout-outer", outer_keys)
    head = next(row["occurrence"] for row in outer["state"]["active"] if row["occurrence"]["step_id"] == "outer-expand")
    parent = next(row["obligation_id"] for row in outer["state"]["obligations"] if row["expected_occurrence_id"] == head["occurrence_id"])
    _p, inner_dispatched, inner_event = PREFIX.execute_expand_multi(
        base, outer["state"], head, "order-inner", "inner_items", unsorted_inner_keys(base, head),
    )
    expected = PREFIX.multi_expansion(base, inner_dispatched, inner_event, "fanout-inner", unsorted_inner_keys(base, head), parent_obligation_id=parent)
    emit(
        "C2-waiting-child-pass-order", step_input(base, inner_dispatched["state"], inner_event), expected,
        ["LIFE-019", "FAN-001"],
        "The inner expansion's source collection lists two objects in an order that is not the raw UTF-8 order of their obligation identifiers. Two different sentences govern the two lists that result. COMPOSITION states that each fan-out pass retains source order in object_keys and obligation_ids, so the pass row keeps the collection's order. LIFE-019 states that child-pass obligation IDs use raw UTF-8 order, and the parent obligation's waiting reference is exactly a child-pass reference, so its obligation_ids are the same two identifiers sorted. Everything else follows FAN-001 for a successful nonempty expansion: one object occurrence and obligation per key in source order, the parent moved to WAITING on the exact reference in the same transition, and a MATCHED effect with an empty reason set whose ROUTE names only the inner fan-out.",
    )

    state = copy.deepcopy(expected["state"])
    pass_row = next(row for row in state["fanout_passes"] if row["fanout_id"] == "fanout-inner")
    waiting = next(row for row in state["obligations"] if row["status"] == "WAITING")
    assert waiting["waiting_on"]["obligation_ids"] != pass_row["obligation_ids"]
    waiting["waiting_on"]["obligation_ids"] = copy.deepcopy(pass_row["obligation_ids"])
    reseal_last_transition(state)
    event = clock_event(state, "clock-refuse-waiting-order")
    emit(
        "C2-refuse-waiting-child-pass-source-order", step_input(base, state, event), stateful_refusal(state, "STATE_INVALID"),
        ["LIFE-019"],
        "This is C2-waiting-child-pass-order's resulting checkpoint with one change: the parent's waiting reference lists its two child obligation identifiers in the pass row's source order instead of raw UTF-8 order, with the last receipt and replay recommitted to the changed state so that no stale history commitment is the fault. The identities are the same set, so the reference still names the right pass. LIFE-019 fixes the order of child-pass obligation IDs as raw UTF-8 and states that the consumer refuses any noncanonical ordering as STATE_INVALID before applying the next event, so the checkpoint is refused before the CLOCK event is considered and the exact supplied state is returned.",
    )


def main() -> None:
    restart_after_outer_prefix()
    restart_after_disputed_frontier()
    refuse_branch_head_source_mismatch()
    waiting_order_cases()
    print(json.dumps({"output": str(GROUP), "case_ids": sorted(path.stem for path in GROUP.glob("*.json"))}, indent=2))


if __name__ == "__main__":
    main()
