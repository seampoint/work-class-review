#!/usr/bin/env python3
"""Build the repair-round controls for structural closure, join stops and loop-entry region heads.

Each case pins one COMPOSITION or LIFECYCLE rule from the gate-2 repair round (derivations sealed
2026-09-13) on a shape no committed case reached. Expected results are derived with batch-local
constructors over the fixture helpers, never taken from a consumer.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from composition_fixture import add_authority_operations, parallel_definition, parallel_entry_result
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


SIBLINGS = _module("stopped_siblings", "build-stopped-sibling-cases.py")
LATE = _module("stopped_fanout_late", "build-stopped-fanout-late-case.py")
PREFIX = _module("fanout_outer_prefix", "build-fanout-outer-prefix-case.py")
RESTART = _module("restart_admission_controls", "build-restart-admission-controls.py")
GROUP = CASES / "repair-round-composition-controls"
LOOP_ID = "head-loop"


def utf8_sorted(values) -> list[str]:
    return sorted(values, key=lambda value: value.encode("utf-8"))


def emit(case_id: str, input_value: dict, expected: dict, requirements: list[str], derivation: str) -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(GROUP / f"{case_id}.json", exact_case(case_id, "step", input_value, expected, requirements, derivation))


def relationship(base: dict, source: str, **match) -> str:
    rows = [row for row in base["definition"]["relationships"] if row["from"] == source and all(row.get(key) == value for key, value in match.items())]
    assert len(rows) == 1, (source, match)
    return digest("relationship", rows[0])


def block(block_id: str, split: str, heads: list[str], join: str, branch_prefix: str) -> dict:
    return {
        "id": block_id, "split_step_id": split, "join_step_id": join,
        "branches": [{"id": f"{branch_prefix}-{index}", "head_step_id": head} for index, head in enumerate(heads, 1)],
    }


def blocks_definition(heads: list[str], sequences: list[tuple[str, str]], blocks: list[dict], structural: list[tuple[str, str]]):
    def mutate(definition: dict) -> None:
        parallel_definition(heads)(definition)
        definition["steps"].extend(structural_step(step_id, kind) for step_id, kind in structural)
        definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
        definition["relationships"] = [{"kind": "SEQUENCE", "from": source, "to": target} for source, target in sequences]
        definition["relationships"].sort(key=canonical_bytes)
        definition["parallel_blocks"].extend(blocks)
        definition["parallel_blocks"].sort(key=lambda row: row["id"].encode("utf-8"))

    return mutate


def enter_root(base: dict, tag: str) -> tuple[dict, dict]:
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-root-" + tag, acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-root-" + tag, native_operation_id="native-root-" + tag)
    return dispatched, governed_effect_event(permitted, dispatched, evidence, event_id="effect-root-" + tag)


def run_operation(base: dict, state: dict, step_id: str, tag: str, *, label: str | None = None, collections: list[dict] | None = None) -> tuple[dict, dict]:
    occurrence_value = SIBLINGS.occurrence_for(state, step_id)
    _proposal, permitted, dispatched = SIBLINGS.propose_and_dispatch(base, state, occurrence_value, suffix=tag)
    dispatch_digest = SIBLINGS.dispatch_digest(dispatched, "dispatch-" + tag)
    options: dict = {}
    if label is not None:
        row = next(row for row in dispatched["state"]["dispatches"] if row["dispatch_digest"] == dispatch_digest)
        fields = copy.deepcopy(row["native_request"]["fields"]) + [
            {"name": "route", "value": typed("STRING", label)}, {"name": "status", "value": typed("STRING", "ISSUED")},
        ]
        options["actual_fields"] = sorted(fields, key=lambda value: value["name"].encode("utf-8"))
    if collections is not None:
        options["collections"] = collections
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-" + tag, native_operation_id="native-" + tag, dispatch_digest=dispatch_digest, **options,
    )
    return dispatched, governed_effect_event(permitted, dispatched, evidence, event_id="effect-" + tag, dispatch_digest=dispatch_digest)


def step_transition(
    base: dict, dispatched: dict, event: dict, *, selected: str | None, relationship_digests: list[str], construct_ids: list[str],
    mutate_after, route_label: dict | None = None, disposition: str = "COMPLETED", reasons: list[str] | None = None, extra_details: list[dict] | None = None,
) -> dict:
    """A matched effect completes its occurrence; `mutate_after` applies the structural closure."""
    occurrence_value = event["permit"]["occurrence"]
    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [row for row in state["active"] if row["occurrence"]["occurrence_id"] != occurrence_value["occurrence_id"]]
        state["completed"].append({
            "occurrence": copy.deepcopy(occurrence_value), "disposition": "SUCCEEDED", "evidence_digest": evidence_digest,
            "occurred_at": event["native_evidence"]["event_time"], "route_label": copy.deepcopy(route_label),
            "selected_relationship_digest": selected, "late": False,
        })
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        mutate_after(state, occurrence_value, event_digest, evidence_digest)

    details = [
        {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
        {"kind": "ROUTE", "relationship_digests": utf8_sorted(set(relationship_digests)), "construct_ids": utf8_sorted(set(construct_ids))},
        *(extra_details or []),
    ]
    return admitted_transition(
        dispatched["state"], event, disposition=disposition, reason_codes=reasons or [], details=details,
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


def next_ordinal(state: dict, step_id: str) -> str:
    return str(1 + max((int(row["occurrence"]["ordinal"]) for row in state["active"] + state["completed"] if row["occurrence"]["step_id"] == step_id), default=0))


def loop_segments(base: dict, step_id: str) -> list[dict]:
    # COMPOSITION: every operation occurrence in a loop carries one LOOP segment after its branch and
    # fan-out segments, and entry from outside allocates pass 1.
    loop = next((row for row in base["definition"]["loops"] if step_id in row["member_step_ids"]), None)
    return [] if loop is None else [{"kind": "LOOP", "construct_id": loop["id"], "pass": "1", "branch_id": None, "object_key": None}]


def discharge(state: dict, completed: dict, event_digest: str, evidence_digest: str) -> dict:
    row = next(row for row in state["obligations"] if row["expected_occurrence_id"] == completed["occurrence_id"])
    row["completion_basis"] = {
        "kind": "DIRECT_EVENT", "event_digest": event_digest, "occurrence_id": completed["occurrence_id"],
        "operation": row["required_operation"], "evidence_digest": evidence_digest,
    }
    row.update(status="DISCHARGED", expected_occurrence_id=None, required_operation=None)
    return row


def join_pass(state: dict, construct_id: str) -> list[str]:
    rows = [row for row in state["obligations"] if row["construct_id"] == construct_id]
    assert rows and all(row["status"] == "DISCHARGED" for row in rows)
    for row in rows:
        row["status"] = "JOINED"
    return utf8_sorted({row["completion_basis"]["occurrence_id"] for row in rows})


def branch_rows(base: dict, state: dict, block_id: str, outer: list[dict], frontier: list[str], event_digest: str) -> list[tuple[dict, dict]]:
    definition = base["definition"]
    block_row = next(row for row in definition["parallel_blocks"] if row["id"] == block_id)
    operations = {row["id"]: row["operation"] for row in definition["steps"]}
    rows = []
    for branch in block_row["branches"]:
        head = branch["head_step_id"]
        enclosing = copy.deepcopy(outer) + [{"kind": "BRANCH", "construct_id": block_id, "pass": "1", "branch_id": branch["id"], "object_key": None}] + loop_segments(base, head)
        child = occurrence(base["definition_digest"], state["instance_id"], head, next_ordinal(state, head), list(frontier), enclosing)
        subject = {
            "kind": "PARALLEL_BRANCH", "construct_id": block_id, "pass": "1", "source_occurrence_ids": list(frontier),
            "branch_id": branch["id"], "object_key": None, "join_step_id": block_row["join_step_id"],
        }
        rows.append((child, {
            "obligation_id": digest("obligation", subject), **subject, "creation_event_digest": event_digest, "status": "OPEN",
            "expected_occurrence_id": child["occurrence_id"], "required_operation": operations[head], "waiting_on": None, "completion_basis": None,
        }))
    return rows


def install(state: dict, rows: list[tuple[dict, dict]], event_digest: str) -> None:
    for child, obligation in rows:
        state["active"].append({"occurrence": copy.deepcopy(child), "activation_event_digest": event_digest, "status": "ACTIVE", "deadline_ids": []})
        state["obligations"].append(copy.deepcopy(obligation))
        counter = next(row for row in state["step_counters"] if row["step_id"] == child["step_id"])
        counter["activations"] = str(int(counter["activations"]) + 1)
    state["total_activations"] = str(int(state["total_activations"]) + len(rows))
    state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
    state["obligations"].sort(key=lambda row: row["obligation_id"].encode("utf-8"))


def branch_completion(base: dict, dispatched: dict, event: dict, construct_id: str) -> dict:
    selected = relationship(base, event["permit"]["occurrence"]["step_id"])
    return step_transition(base, dispatched, event, selected=selected, relationship_digests=[selected], construct_ids=[construct_id], mutate_after=discharge)


def split_entry(base: dict, dispatched: dict, event: dict, block_id: str, *, parent_waits: bool) -> dict:
    selected = relationship(base, event["permit"]["occurrence"]["step_id"])

    def mutate_after(state: dict, completed: dict, event_digest: str, _evidence_digest: str) -> None:
        parent = next((row for row in state["obligations"] if row["expected_occurrence_id"] == completed["occurrence_id"]), None)
        assert (parent is not None) == parent_waits
        rows = branch_rows(base, state, block_id, completed["enclosing"], [completed["occurrence_id"]], event_digest)
        install(state, rows, event_digest)
        if parent is not None:
            parent.update(status="WAITING", expected_occurrence_id=None, required_operation=None, waiting_on={
                "kind": "PARALLEL", "construct_id": block_id, "pass": "1", "outer_enclosing": copy.deepcopy(completed["enclosing"]),
                "obligation_ids": utf8_sorted(obligation["obligation_id"] for _child, obligation in rows),
            })

    return step_transition(base, dispatched, event, selected=selected, relationship_digests=[selected], construct_ids=[block_id], mutate_after=mutate_after)


def join_into_child_split() -> None:
    tag = "c2-join-split"
    heads = ["outer-a", "outer-b"]
    base = base_lifecycle(
        authority_mutator=add_authority_operations(heads + ["child-a", "child-b"]),
        definition_mutator=blocks_definition(
            heads,
            [("issue", "parallel-split"), ("outer-a", "parallel-join"), ("outer-b", "parallel-join"), ("parallel-join", "child-split"),
             ("child-a", "child-join"), ("child-b", "child-join"), ("child-join", "terminal")],
            [block("parallel-2", "child-split", ["child-a", "child-b"], "child-join", "child-branch")],
            [("child-join", "PARALLEL_JOIN"), ("child-split", "PARALLEL_SPLIT")],
        ),
    )
    root_dispatched, root_event = enter_root(base, tag)
    entered = parallel_entry_result(base, root_dispatched, root_event, heads)
    first_dispatched, first_event = run_operation(base, entered["state"], "outer-a", tag + "-outer-a")
    first = branch_completion(base, first_dispatched, first_event, "parallel-1")
    dispatched, event = run_operation(base, first["state"], "outer-b", tag + "-outer-b")

    def mutate_after(state: dict, completed: dict, event_digest: str, evidence_digest: str) -> None:
        discharge(state, completed, event_digest, evidence_digest)
        frontier = join_pass(state, "parallel-1")
        install(state, branch_rows(base, state, "parallel-2", [], frontier, event_digest), event_digest)

    to_join = relationship(base, "outer-b")
    expected = step_transition(
        base, dispatched, event, selected=to_join, relationship_digests=[to_join, relationship(base, "parallel-join")],
        construct_ids=["parallel-1", "parallel-2"], mutate_after=mutate_after,
    )
    emit(
        "C2-join-into-child-split", step_input(base, dispatched["state"], event), expected, ["LIFE-015", "LIFE-017", "PAR-001"],
        "A top-level two-branch block's join routes directly to a second block's split. outer-a has completed and discharged its branch obligation, and outer-b's matching effect now arrives. PAR-001 discharges outer-b's obligation with its direct basis; the pass is then complete, so the join fires in the same transition and both obligations become JOINED. LIFE-015: when the pass joins, the successor removes the joined BRANCH segment and every region-local segment after it, retains the common outer prefix, here empty, and appends only segments the continuing closure introduces, so each second-block branch occurrence carries exactly its own BRANCH segment at pass 1. Their predecessor lists and the new obligations' source lists are the raw UTF-8 sorted completion frontier of the joined pass, the two direct final occurrences. The ROUTE detail names outer-b's relationship to the join and the join's outgoing relationship, and both blocks, because the closure traverses the first block's join and the second block's split.",
    )


def child_join_into_sibling_split() -> None:
    tag = "c2-child-join-split"
    heads = ["outer-a", "outer-b"]
    base = base_lifecycle(
        authority_mutator=add_authority_operations(heads + ["child-a", "child-b", "third-a", "third-b"]),
        definition_mutator=blocks_definition(
            heads,
            [("issue", "parallel-split"), ("outer-a", "child-split"), ("outer-b", "parallel-join"), ("child-a", "child-join"), ("child-b", "child-join"),
             ("child-join", "third-split"), ("third-a", "third-join"), ("third-b", "third-join"), ("third-join", "parallel-join"), ("parallel-join", "terminal")],
            [block("parallel-2", "child-split", ["child-a", "child-b"], "child-join", "child-branch"),
             block("parallel-3", "third-split", ["third-a", "third-b"], "third-join", "third-branch")],
            [("child-join", "PARALLEL_JOIN"), ("child-split", "PARALLEL_SPLIT"), ("third-join", "PARALLEL_JOIN"), ("third-split", "PARALLEL_SPLIT")],
        ),
    )
    root_dispatched, root_event = enter_root(base, tag)
    entered = parallel_entry_result(base, root_dispatched, root_event, heads)
    outer_dispatched, outer_event = run_operation(base, entered["state"], "outer-a", tag + "-outer-a")
    nested = split_entry(base, outer_dispatched, outer_event, "parallel-2", parent_waits=True)
    first_dispatched, first_event = run_operation(base, nested["state"], "child-a", tag + "-child-a")
    first = branch_completion(base, first_dispatched, first_event, "parallel-2")
    dispatched, event = run_operation(base, first["state"], "child-b", tag + "-child-b")

    def mutate_after(state: dict, completed: dict, event_digest: str, evidence_digest: str) -> None:
        discharge(state, completed, event_digest, evidence_digest)
        frontier = join_pass(state, "parallel-2")
        parent = next(row for row in state["obligations"] if row["status"] == "WAITING" and row["waiting_on"]["construct_id"] == "parallel-2")
        outer = copy.deepcopy(parent["waiting_on"]["outer_enclosing"])
        rows = branch_rows(base, state, "parallel-3", outer, frontier, event_digest)
        install(state, rows, event_digest)
        parent["waiting_on"] = {
            "kind": "PARALLEL", "construct_id": "parallel-3", "pass": "1", "outer_enclosing": outer,
            "obligation_ids": utf8_sorted(obligation["obligation_id"] for _child, obligation in rows),
        }

    to_join = relationship(base, "child-b")
    expected = step_transition(
        base, dispatched, event, selected=to_join, relationship_digests=[to_join, relationship(base, "child-join")],
        construct_ids=["parallel-2", "parallel-3"], mutate_after=mutate_after,
    )
    emit(
        "C2-child-join-into-sibling-split", step_input(base, dispatched["state"], event), expected, ["LIFE-015", "PAR-001"],
        "Inside branch-1 of the outer block, outer-a entered a child block whose join routes directly to a third block's split, and the third block's join returns to the outer join. child-a has completed, and child-b's matching effect now arrives. Its direct discharge completes the child pass, which joins. COMPOSITION: when a child join's closure immediately enters another child split, the transition replaces the parent obligation's waiting reference with the new exact child-pass reference, whose outer_enclosing is the complete enclosing prefix before the new construct's branch segment. LIFE-015 removes the joined child BRANCH segment from the continuation and retains the common outer prefix, so each third-block occurrence carries the outer branch segment and then its own third-block branch segment at pass 1, with the sorted child completion frontier as predecessors and sources. The parent stays WAITING, its outer_enclosing is the outer branch prefix, and its obligation identifiers are in raw UTF-8 order. The ROUTE detail names child-b's relationship to the child join, the child join's outgoing relationship, and the child and third blocks.",
    )


def empty_fanout_advance_into_parent_join() -> None:
    tag = "c2-empty-advance"
    base = base_lifecycle(authority_mutator=add_authority_operations(LATE.BRANCHES + [LATE.OBJECT]), definition_mutator=LATE.definition_mutator)
    root_dispatched, root_event = enter_root(base, tag)
    entered = parallel_entry_result(base, root_dispatched, root_event, LATE.BRANCHES)
    dispatched, event = run_operation(
        base, entered["state"], "expand-b", tag + "-expand-b", collections=[{"name": "items", "element_type_ref": "IDENTITY", "values": []}],
    )

    def mutate_after(state: dict, completed: dict, event_digest: str, evidence_digest: str) -> None:
        state["fanout_passes"].append({
            "fanout_id": LATE.FANOUT_ID, "pass": "1", "expand_occurrence_id": completed["occurrence_id"], "object_keys": [], "obligation_ids": [], "joined": True,
        })
        state["fanout_passes"].sort(key=lambda row: (row["fanout_id"].encode("utf-8"), int(row["pass"]), row["expand_occurrence_id"].encode("utf-8")))
        discharge(state, completed, event_digest, evidence_digest)

    expected = step_transition(
        base, dispatched, event, selected=None, relationship_digests=[relationship(base, "fanout-b-join")],
        construct_ids=[LATE.FANOUT_ID, "parallel-1"], mutate_after=mutate_after,
    )
    assert expected["state"]["status"] == "ACTIVE"
    emit(
        "C2-empty-fanout-advance-into-parent-join", step_input(base, dispatched["state"], event), expected, ["LIFE-015", "LIFE-018", "PAR-001", "FAN-001"],
        "The outer block's branch-2 head is a FANOUT_EXPAND step whose fan-out join routes to the outer parallel join, and branch-1 is still OPEN. The expand step's matching effect carries the exact empty collection under ADVANCE_TO_JOIN. LIFE-018 retains one joined pass with empty key and obligation inventories and records the completed expand occurrence with a null selected relationship. COMPOSITION: empty fan-out advance creates no child obligations and uses the expand occurrence as the structural frontier; when the closure reaches the region's own join, the directly owning branch obligation becomes DISCHARGED with a DIRECT_EVENT basis on that occurrence. The outer join does not fire because branch-1 is OPEN, so no occurrence is created and the instance stays ACTIVE. LIFE-015 names the fan-out join's outgoing relationship, the fan-out whose expansion and join the closure traverses, and the outer block whose join it reaches.",
    )


def join_continuation_limit_stop() -> None:
    tag = "c2-join-limit"
    heads = ["outer-a", "outer-b"]
    definition_mutator = blocks_definition(
        heads, [("issue", "parallel-split"), ("outer-a", "parallel-join"), ("outer-b", "parallel-join"), ("parallel-join", "after"), ("after", "terminal")], [], [],
    )

    def mutate(definition: dict) -> None:
        definition_mutator(definition)
        definition["limits"]["maximum_activations"] = "3"

    base = base_lifecycle(authority_mutator=add_authority_operations(heads + ["after"]), definition_mutator=mutate)
    root_dispatched, root_event = enter_root(base, tag)
    entered = parallel_entry_result(base, root_dispatched, root_event, heads)
    first_dispatched, first_event = run_operation(base, entered["state"], "outer-a", tag + "-outer-a")
    first = branch_completion(base, first_dispatched, first_event, "parallel-1")
    dispatched, event = run_operation(base, first["state"], "outer-b", tag + "-outer-b")
    assert dispatched["state"]["total_activations"] == "3"

    def mutate_after(state: dict, completed: dict, event_digest: str, evidence_digest: str) -> None:
        discharge(state, completed, event_digest, evidence_digest)
        state["status"] = "STOPPED"

    to_join, join_out = relationship(base, "outer-b"), relationship(base, "parallel-join")
    expected = step_transition(
        base, dispatched, event, selected=to_join, relationship_digests=[to_join, join_out], construct_ids=["parallel-1"], mutate_after=mutate_after,
        disposition="STOPPED", reasons=["LIMIT_EXCEEDED"],
        extra_details=[{"kind": "LIMIT", "limit_kind": "ACTIVATIONS", "limit": "3", "current": "4", "step_id": "after", "relationship_digest": join_out}],
    )
    emit(
        "C2-join-continuation-limit-stop", step_input(base, dispatched["state"], event), expected, ["LIFE-017", "PAR-001"],
        "A two-branch block's join routes to one more operation, and the work class allows three activations: the root and the two branch heads. outer-a has completed and discharged its obligation. outer-b's matching effect now arrives and completes the pass, so the join's continuation would create a fourth activation. COMPOSITION requires the consumer to preflight the complete fixed-point result before creating any successor, replacement wait or ancestor discharge; a stop anywhere in that preflight retains the direct event results, creates none of the proposed continuation, and discharges only the directly triggering obligation with its direct basis. The decision is STOPPED with LIMIT_EXCEEDED and the ACTIVATIONS limit detail naming the successor step and the join's outgoing relationship. Both branch obligations stay DISCHARGED and neither becomes JOINED, no successor exists, and the instance is STOPPED. The ROUTE detail names the closure traversed in preflight: outer-b's relationship to the join, the join's outgoing relationship, and the block.",
    )
    restart_event = RESTART.clock_event(expected["state"], "clock-c2-join-limit-restart")
    emit(
        "C2-restart-after-join-continuation-stop", step_input(base, expected["state"], restart_event), RESTART.clock_recorded(expected["state"], restart_event), ["LIFE-019", "PAR-001"],
        "The checkpoint is the result of C2-join-continuation-limit-stop: a STOPPED instance whose one pass has every obligation DISCHARGED and none JOINED. A fresh available CLOCK sample asks the consumer to restart. LIFE-019 admits an all-DISCHARGED, not-JOINED pass in a STOPPED state when the retained stop decision and the direct completion bases prove the join was suppressed by fixed-point preflight failure; the retained LIMIT_EXCEEDED decision on the event that discharged the last obligation, with both direct bases, proves it. The CLOCK sample is recorded with no other change.",
    )


def branch_loop_definition(definition: dict) -> None:
    blocks_definition(["loop-head", "outer-b"], [("issue", "parallel-split"), ("loop-head", "loop-tail"), ("outer-b", "parallel-join"), ("parallel-join", "terminal")], [], [])(definition)
    definition["relationships"].extend([
        {"kind": "LABEL", "from": "loop-tail", "to": "loop-head", "label": typed("STRING", "CONTINUE")},
        {"kind": "LABEL", "from": "loop-tail", "to": "parallel-join", "label": typed("STRING", "EXIT")},
    ])
    definition["relationships"].sort(key=canonical_bytes)
    loop_choice(definition, "loop-tail")


def loop_choice(definition: dict, tail_id: str) -> None:
    tail = next(row for row in definition["steps"] if row["id"] == tail_id)
    tail["completion"]["route_label_field"] = "route"
    tail["completion"]["route_label_type_ref"] = "STRING"
    definition["choices"] = [{"step_id": tail_id, "label_type_ref": "STRING", "label_values": [typed("STRING", "CONTINUE"), typed("STRING", "EXIT")]}]
    definition["loops"] = [{"id": LOOP_ID, "entry_step_id": "loop-head", "member_step_ids": ["loop-head", "loop-tail"], "back_edge_from_step_id": tail_id, "maximum_passes": "3"}]
    for row in definition["occurrence_limits"]:
        if row["step_id"] in {"loop-head", "loop-tail"}:
            row["maximum"] = "3"


def region_advance(base: dict, dispatched: dict, event: dict, *, successor: str, selected: str, route_label: dict | None, loop_pass: str) -> dict:
    """An eligible direct route inside one branch replaces the owning obligation's expectation."""
    source = event["permit"]["occurrence"]
    operation = next(row["operation"] for row in base["definition"]["steps"] if row["id"] == successor)

    def mutate_after(state: dict, completed: dict, event_digest: str, _evidence_digest: str) -> None:
        enclosing = copy.deepcopy(completed["enclosing"])
        next(row for row in enclosing if row["kind"] == "LOOP")["pass"] = loop_pass
        child = occurrence(base["definition_digest"], state["instance_id"], successor, next_ordinal(state, successor), [completed["occurrence_id"]], enclosing)
        state["active"].append({"occurrence": child, "activation_event_digest": event_digest, "status": "ACTIVE", "deadline_ids": []})
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        counter = next(row for row in state["step_counters"] if row["step_id"] == successor)
        counter["activations"] = str(int(counter["activations"]) + 1)
        state["total_activations"] = str(int(state["total_activations"]) + 1)
        owner = next(row for row in state["obligations"] if row["expected_occurrence_id"] == completed["occurrence_id"])
        owner.update(expected_occurrence_id=child["occurrence_id"], required_operation=operation)

    label_details = [] if route_label is None else [{"kind": "LABEL", "step_id": source["step_id"], "observed_value": copy.deepcopy(route_label)}]
    return step_transition(
        base, dispatched, event, selected=selected, relationship_digests=[selected], construct_ids=[], mutate_after=mutate_after,
        route_label=route_label, extra_details=label_details,
    )


def branch_head_loop_entry() -> None:
    tag = "c2-branch-loop"
    base = base_lifecycle(authority_mutator=add_authority_operations(["loop-head", "loop-tail", "outer-b"]), definition_mutator=branch_loop_definition)
    root_dispatched, root_event = enter_root(base, tag)
    entered = split_entry(base, root_dispatched, root_event, "parallel-1", parent_waits=False)
    emit(
        "C2-branch-head-loop-entry", step_input(base, root_dispatched["state"], root_event), entered, ["LIFE-016", "LIFE-017", "PAR-001"],
        "A two-branch block's branch-1 head is the entry of a loop wholly inside that branch: loop-head routes to loop-tail, which chooses CONTINUE back to loop-head or EXIT to the block join. COMPOSITION admits a parallel branch head whose only incoming edge other than the block's implicit edge is an admitted back edge wholly inside that branch, and admits a cycle contained wholly inside one branch. The root's matching effect enters the split. LIFE-017 creates both branch obligations and occurrences atomically. COMPOSITION's loop rule gives every operation occurrence in the loop one LOOP segment, with branch segments in their outer-to-inner positions, and entry from outside allocates pass 1. The loop-head occurrence's enclosing path is therefore its BRANCH segment followed by the LOOP segment at pass 1; outer-b carries only its BRANCH segment. The ROUTE detail names the root's relationship to the split and the block.",
    )
    head_dispatched, head_event = run_operation(base, entered["state"], "loop-head", tag + "-head-1")
    advanced = region_advance(base, head_dispatched, head_event, successor="loop-tail", selected=relationship(base, "loop-head"), route_label=None, loop_pass="1")
    tail_dispatched, tail_event = run_operation(base, advanced["state"], "loop-tail", tag + "-tail-1", label="CONTINUE")
    label = typed("STRING", "CONTINUE")
    expected = region_advance(
        base, tail_dispatched, tail_event, successor="loop-head", selected=relationship(base, "loop-tail", label=label), route_label=label, loop_pass="2",
    )
    emit(
        "C2-branch-loop-back-edge-keeps-branch", step_input(base, tail_dispatched["state"], tail_event), expected, ["LIFE-016", "PAR-001"],
        "Continuing C2-branch-head-loop-entry: loop-head has completed and routed to loop-tail inside the branch and the loop, and the branch obligation names loop-tail. loop-tail's matching effect carries the CONTINUE label, which selects the declared back edge to the branch head. COMPOSITION: selecting the one back edge allocates the current pass plus one, branch segments keep their outer-to-inner positions, and a loop inside one branch retains branch ancestry. PAR-001: an eligible direct route within the same branch replaces the obligation's expected occurrence and required operation atomically. The new loop-head occurrence has ordinal 2, loop-tail as its only predecessor, and its BRANCH segment followed by the LOOP segment at pass 2; the branch obligation names it. The decision carries the ROUTE detail for the selected label relationship and the LABEL detail.",
    )


def fanout_loop_definition(definition: dict) -> None:
    definition["profile"] = "PARALLEL_FANOUT"
    next(row for row in definition["steps"] if row["id"] == definition["root"])["kind"] = "FANOUT_EXPAND"
    definition["steps"].append(structural_step("fanout-join", "FANOUT_JOIN"))
    definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
    definition["relationships"] = [
        {"kind": "SEQUENCE", "from": "loop-head", "to": "loop-tail"},
        {"kind": "LABEL", "from": "loop-tail", "to": "loop-head", "label": typed("STRING", "CONTINUE")},
        {"kind": "LABEL", "from": "loop-tail", "to": "fanout-join", "label": typed("STRING", "EXIT")},
        {"kind": "SEQUENCE", "from": "fanout-join", "to": "terminal"},
    ]
    definition["relationships"].sort(key=canonical_bytes)
    loop_choice(definition, "loop-tail")
    definition["fanouts"] = [{
        "id": "fanout-1", "expand_step_id": definition["root"], "region_head_step_id": "loop-head", "join_step_id": "fanout-join",
        "object_field": "items", "object_request_field": "card_id", "object_type_ref": "IDENTITY", "empty_set_behavior": "ADVANCE_TO_JOIN",
    }]


def fanout_head_loop_entry() -> None:
    tag = "c2-fanout-loop"
    base = base_lifecycle(authority_mutator=add_authority_operations(["loop-head", "loop-tail"]), definition_mutator=fanout_loop_definition)
    keys = [typed("IDENTITY", "object-1")]
    _permitted, dispatched, event = PREFIX.execute_expand_multi(base, base["clock_result"]["state"], base["proposal_event"]["occurrence"], tag, "items", keys)
    fanout = base["definition"]["fanouts"][0]
    head = fanout["region_head_step_id"]
    operation = next(row["operation"] for row in base["definition"]["steps"] if row["id"] == head)

    def mutate_after(state: dict, completed: dict, event_digest: str, _evidence_digest: str) -> None:
        existing = int(next_ordinal(state, head)) - 1
        rows = []
        for index, key in enumerate(keys, start=existing + 1):
            enclosing = copy.deepcopy(completed["enclosing"]) + [
                {"kind": "FANOUT", "construct_id": fanout["id"], "pass": "1", "branch_id": None, "object_key": copy.deepcopy(key)},
            ] + loop_segments(base, head)
            child = occurrence(base["definition_digest"], state["instance_id"], head, str(index), [completed["occurrence_id"]], enclosing, object_key=key)
            subject = {
                "kind": "FANOUT_OBJECT", "construct_id": fanout["id"], "pass": "1", "source_occurrence_ids": [completed["occurrence_id"]],
                "branch_id": None, "object_key": copy.deepcopy(key), "join_step_id": fanout["join_step_id"],
            }
            rows.append((child, {
                "obligation_id": digest("obligation", subject), **subject, "creation_event_digest": event_digest, "status": "OPEN",
                "expected_occurrence_id": child["occurrence_id"], "required_operation": operation, "waiting_on": None, "completion_basis": None,
            }))
        install(state, rows, event_digest)
        state["fanout_passes"].append({
            "fanout_id": fanout["id"], "pass": "1", "expand_occurrence_id": completed["occurrence_id"], "object_keys": copy.deepcopy(keys),
            "obligation_ids": [obligation["obligation_id"] for _child, obligation in rows], "joined": False,
        })
        state["fanout_passes"].sort(key=lambda row: (row["fanout_id"].encode("utf-8"), int(row["pass"]), row["expand_occurrence_id"].encode("utf-8")))

    expected = step_transition(base, dispatched, event, selected=None, relationship_digests=[], construct_ids=[fanout["id"]], mutate_after=mutate_after)
    emit(
        "C2-fanout-head-loop-entry", step_input(base, dispatched["state"], event), expected, ["LIFE-016", "LIFE-018", "FAN-001"],
        "The root is a FANOUT_EXPAND step whose region head is the entry of a loop wholly inside the object region: loop-head routes to loop-tail, which chooses CONTINUE back to loop-head or EXIT to the fan-out join. COMPOSITION admits a fan-out region head whose only incoming edge other than the fan-out's implicit edge is an admitted back edge wholly inside that object region. The root's matching effect carries one object. LIFE-018 freezes the set and creates the object obligation and occurrence atomically. COMPOSITION's loop rule gives every operation occurrence in the loop one LOOP segment, with fan-out segments in their outer-to-inner positions, and entry from outside allocates pass 1. The loop-head occurrence's enclosing path is therefore the object's FANOUT segment followed by the LOOP segment at pass 1. The completed expand occurrence records a null selected relationship, and the ROUTE detail names only the fan-out.",
    )


def fanout_join_into_operation() -> None:
    tag = "c2-object-join-operation"

    def mutate(definition: dict) -> None:
        definition["profile"] = "PARALLEL_FANOUT"
        root = next(row for row in definition["steps"] if row["id"] == definition["root"])
        root["kind"] = "FANOUT_EXPAND"
        definition["steps"].append(structural_step("fanout-join", "FANOUT_JOIN"))
        definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
        definition["relationships"] = [
            {"kind": "SEQUENCE", "from": "object-step", "to": "fanout-join"},
            {"kind": "SEQUENCE", "from": "fanout-join", "to": "after"},
            {"kind": "SEQUENCE", "from": "after", "to": "terminal"},
        ]
        definition["relationships"].sort(key=canonical_bytes)
        definition["fanouts"] = [{
            "id": "fanout-1", "expand_step_id": root["id"], "region_head_step_id": "object-step", "join_step_id": "fanout-join",
            "object_field": "items", "object_request_field": "card_id", "object_type_ref": "IDENTITY", "empty_set_behavior": "ADVANCE_TO_JOIN",
        }]

    base = base_lifecycle(authority_mutator=add_authority_operations(["object-step", "after"]), definition_mutator=mutate)
    keys = [typed("IDENTITY", "object-1")]
    _permitted, expand_dispatched, expand_event = PREFIX.execute_expand_multi(
        base, base["clock_result"]["state"], base["proposal_event"]["occurrence"], tag, "items", keys,
    )
    expanded = PREFIX.multi_expansion(base, expand_dispatched, expand_event, "fanout-1", keys)
    dispatched, event = run_operation(base, expanded["state"], "object-step", tag + "-object")

    def mutate_after(state: dict, completed: dict, event_digest: str, evidence_digest: str) -> None:
        discharge(state, completed, event_digest, evidence_digest)
        frontier = join_pass(state, "fanout-1")
        next(row for row in state["fanout_passes"] if row["fanout_id"] == "fanout-1")["joined"] = True
        successor = occurrence(base["definition_digest"], state["instance_id"], "after", next_ordinal(state, "after"), frontier, [])
        state["active"].append({"occurrence": successor, "activation_event_digest": event_digest, "status": "ACTIVE", "deadline_ids": []})
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        counter = next(row for row in state["step_counters"] if row["step_id"] == "after")
        counter["activations"] = str(int(counter["activations"]) + 1)
        state["total_activations"] = str(int(state["total_activations"]) + 1)

    to_join = relationship(base, "object-step")
    expected = step_transition(
        base, dispatched, event, selected=to_join, relationship_digests=[to_join, relationship(base, "fanout-join")],
        construct_ids=["fanout-1"], mutate_after=mutate_after,
    )
    assert next(row["occurrence"] for row in expected["state"]["active"] if row["occurrence"]["step_id"] == "after")["object_key"] is None
    emit(
        "C2-object-join-into-operation", step_input(base, dispatched["state"], event), expected, ["LIFE-001", "LIFE-015", "FAN-001"],
        "A top-level fan-out has one frozen object; its region head routes to the fan-out join, and the join routes to an ordinary operation. The object's matching effect discharges its obligation, which completes the pass, so the join fires in the same transition: the object obligation becomes JOINED and the pass row is marked joined. LIFE-015 removes the joined FANOUT segment from the successor, retains the common outer prefix, here empty, and makes the successor's predecessor list the pass's completion frontier, the object occurrence. LIFE-001 gives an occurrence the innermost fan-out segment's key only when its enclosing path contains a fan-out segment; otherwise its object_key is null. The successor therefore has an empty enclosing path and a null object key, whatever the completed object's key was. No parent obligation exists, the instance stays ACTIVE, and the ROUTE detail names the object's relationship to the join, the join's outgoing relationship, and the fan-out.",
    )


BUILDERS = [
    join_into_child_split, child_join_into_sibling_split, empty_fanout_advance_into_parent_join, join_continuation_limit_stop,
    branch_head_loop_entry, fanout_head_loop_entry, fanout_join_into_operation,
]


def main() -> None:
    for build in BUILDERS:
        build()
    print(json.dumps({"output": str(GROUP), "case_ids": sorted(path.stem for path in GROUP.glob("*.json"))}, indent=2))


if __name__ == "__main__":
    main()
