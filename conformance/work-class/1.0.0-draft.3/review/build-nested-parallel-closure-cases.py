#!/usr/bin/env python3
"""Build exact nested-parallel progression, stop, and dispute vectors."""

from __future__ import annotations

import copy
import json

from composition_fixture import (
    add_authority_operations,
    parallel_entry_result,
    permitted_operation_proposal,
    proposal_for_occurrence,
)
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock, occurrence, structural_step
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


GROUP = CASES / "nested-parallel-closure"
OUTER_BRANCHES = ["outer-a", "outer-b"]
CHILD_BRANCHES = ["child-a", "child-b"]
OPERATIONS = [*OUTER_BRANCHES, *CHILD_BRANCHES, "outer-successor"]


def nested_definition(*, child_to_parent_join: bool = False, obligation_limit: str = "64", deadlines: bool = False):
    def mutate(definition: dict) -> None:
        definition["profile"] = "PARALLEL_FANOUT"
        definition["steps"].extend(
            [
                structural_step("child-join", "PARALLEL_JOIN"),
                structural_step("child-split", "PARALLEL_SPLIT"),
                structural_step("parallel-join", "PARALLEL_JOIN"),
                structural_step("parallel-split", "PARALLEL_SPLIT"),
            ]
        )
        if child_to_parent_join:
            definition["steps"] = [row for row in definition["steps"] if row["id"] != "outer-successor"]
            definition["occurrence_limits"] = [
                row for row in definition["occurrence_limits"] if row["step_id"] != "outer-successor"
            ]
        definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
        child_target = "parallel-join" if child_to_parent_join else "outer-successor"
        definition["relationships"] = [
            {"kind": "SEQUENCE", "from": "issue", "to": "parallel-split"},
            {"kind": "SEQUENCE", "from": "outer-a", "to": "child-split"},
            {"kind": "SEQUENCE", "from": "outer-b", "to": "parallel-join"},
            {"kind": "SEQUENCE", "from": "child-a", "to": "child-join"},
            {"kind": "SEQUENCE", "from": "child-b", "to": "child-join"},
            {"kind": "SEQUENCE", "from": "child-join", "to": child_target},
            *([] if child_to_parent_join else [{"kind": "SEQUENCE", "from": "outer-successor", "to": "parallel-join"}]),
            {"kind": "SEQUENCE", "from": "parallel-join", "to": "terminal"},
        ]
        definition["parallel_blocks"] = [
            {
                "id": "parallel-1",
                "split_step_id": "parallel-split",
                "branches": [
                    {"id": "branch-1", "head_step_id": "outer-a"},
                    {"id": "branch-2", "head_step_id": "outer-b"},
                ],
                "join_step_id": "parallel-join",
            },
            {
                "id": "parallel-2",
                "split_step_id": "child-split",
                "branches": [
                    {"id": "child-branch-1", "head_step_id": "child-a"},
                    {"id": "child-branch-2", "head_step_id": "child-b"},
                ],
                "join_step_id": "child-join",
            },
        ]
        definition["limits"]["maximum_active_obligations"] = obligation_limit
        if deadlines:
            deadline_step_ids = ["child-a", "child-b", "outer-a", "outer-b"]
            definition["deadlines"] = [
                {
                    "id": step_id + "-deadline",
                    "step_id": step_id,
                    "clock_source": "work-clock",
                    "due": {
                        "kind": "ABSOLUTE_INSTANT",
                        "instant": "2026-09-10T05:00:00Z" if step_id == "outer-a" else "2026-09-10T04:31:00Z",
                    },
                    "boundary": "AT_OR_AFTER",
                    "expiry_target": (
                        "child-join"
                        if step_id.startswith("child-")
                        else None
                        if step_id == "outer-a"
                        else "parallel-join"
                    ),
                }
                for step_id in deadline_step_ids
            ]
            definition["relationships"].extend(
                {
                    "kind": "EXPIRY",
                    "from": step_id,
                    "to": (
                        "child-join"
                        if step_id.startswith("child-")
                        else "child-split"
                        if step_id == "outer-a"
                        else "parallel-join"
                    ),
                    "deadline_ref": step_id + "-deadline",
                }
                for step_id in ["child-a", "child-b", "outer-b"]
            )
        definition["relationships"].sort(key=canonical_bytes)
        definition["occurrence_limits"].sort(key=lambda row: row["step_id"].encode("utf-8"))

    return mutate


def setup_outer(case_id: str, *, child_to_parent_join: bool = False, obligation_limit: str = "64", deadlines: bool = False):
    initial_clocks = [available_clock("work-clock", "1", "2026-09-10T04:30:00Z")] if deadlines else None
    base = base_lifecycle(
        authority_mutator=add_authority_operations(OPERATIONS),
        definition_mutator=nested_definition(
            child_to_parent_join=child_to_parent_join,
            obligation_limit=obligation_limit,
            deadlines=deadlines,
        ),
        initial_clocks=initial_clocks,
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(
        base,
        permitted,
        event_id="dispatch-root-" + case_id.lower(),
        acknowledgement_status="ACCEPTED",
    )
    dispatched = dispatch_result(
        permitted,
        dispatch,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-root-" + case_id.lower(),
        native_operation_id="native-root-" + case_id.lower(),
    )
    event = governed_effect_event(
        permitted,
        dispatched,
        evidence,
        event_id="effect-root-" + case_id.lower(),
    )
    if deadlines:
        event["activation_clocks"] = [copy.deepcopy(initial_clocks[0])]
    outer = parallel_entry_result(
        base,
        dispatched,
        event,
        OUTER_BRANCHES,
        install_deadlines=deadlines,
    )
    return base, outer


def execute(base: dict, state: dict, step_id: str, suffix: str):
    active = next(row["occurrence"] for row in state["active"] if row["occurrence"]["step_id"] == step_id)
    proposal, authority_result = proposal_for_occurrence(
        base,
        state,
        active,
        event_id="proposal-" + suffix,
    )
    permitted = permitted_operation_proposal(base, state, proposal, authority_result)
    dispatch = dispatch_event(
        base,
        permitted,
        event_id="dispatch-" + suffix,
        acknowledgement_status="ACCEPTED",
    )
    dispatched = dispatch_result(
        permitted,
        dispatch,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    dispatch_digest = next(
        row["dispatch_digest"]
        for row in dispatched["state"]["dispatches"]
        if row["event_id"] == dispatch["event_id"]
    )
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-" + suffix,
        native_operation_id="native-" + suffix,
        dispatch_digest=dispatch_digest,
    )
    effect = governed_effect_event(
        permitted,
        dispatched,
        evidence,
        event_id="effect-" + suffix,
        dispatch_digest=dispatch_digest,
    )
    return permitted, dispatched, effect


def direct_relationship(base: dict, step_id: str) -> dict:
    return next(
        row
        for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == step_id
    )


def effect_transition(
    base: dict,
    dispatched: dict,
    event: dict,
    *,
    disposition: str,
    reason_codes: list[str],
    relationship_digests: list[str],
    construct_ids: list[str],
    mutate_after,
    limit_detail: dict | None = None,
) -> dict:
    occurrence_value = event["permit"]["occurrence"]
    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    selected = direct_relationship(base, occurrence_value["step_id"])
    selected_digest = digest("relationship", selected)

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [
            row
            for row in state["active"]
            if row["occurrence"]["occurrence_id"] != occurrence_value["occurrence_id"]
        ]
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(occurrence_value),
                "disposition": "SUCCEEDED",
                "evidence_digest": evidence_digest,
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": selected_digest,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        for deadline in state["deadlines"]:
            if deadline["occurrence_id"] == occurrence_value["occurrence_id"] and deadline["status"] == "PENDING":
                deadline["status"] = "DISCHARGED"
        mutate_after(state, occurrence_value, event_digest, evidence_digest)

    details = [
        {
            "kind": "EFFECT",
            "classification": "MATCHED",
            "evidence_id": event["native_evidence"]["evidence_id"],
        },
        {
            "kind": "ROUTE",
            "relationship_digests": sorted(set(relationship_digests), key=lambda value: value.encode("utf-8")),
            "construct_ids": sorted(set(construct_ids), key=lambda value: value.encode("utf-8")),
        },
    ]
    if limit_detail is not None:
        details.append(copy.deepcopy(limit_detail))
    return admitted_transition(
        dispatched["state"],
        event,
        disposition=disposition,
        reason_codes=reason_codes,
        details=details,
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def child_pass_reference(state: dict, outer_enclosing: list[dict]) -> dict:
    obligation_ids = [
        next(
            row["obligation_id"]
            for row in state["obligations"]
            if row["construct_id"] == "parallel-2" and row["branch_id"] == branch_id
        )
        for branch_id in ["child-branch-1", "child-branch-2"]
    ]
    return {
        "kind": "PARALLEL",
        "construct_id": "parallel-2",
        "pass": "1",
        "outer_enclosing": copy.deepcopy(outer_enclosing),
        "obligation_ids": sorted(obligation_ids, key=lambda value: value.encode("utf-8")),
    }


def nested_entry_result(
    base: dict,
    dispatched: dict,
    event: dict,
    *,
    stop_on_limit: bool = False,
    install_deadlines: bool = False,
) -> dict:
    source = event["permit"]["occurrence"]
    selected_digest = digest("relationship", direct_relationship(base, source["step_id"]))
    event_digest = digest("runtime-event", event)
    children: list[tuple[dict, dict]] = []
    for index, step_id in enumerate(CHILD_BRANCHES, 1):
        branch_id = "child-branch-" + str(index)
        enclosing = copy.deepcopy(source["enclosing"]) + [
            {
                "kind": "BRANCH",
                "construct_id": "parallel-2",
                "pass": "1",
                "branch_id": branch_id,
                "object_key": None,
            }
        ]
        child = occurrence(
            base["definition_digest"],
            source["instance_id"],
            step_id,
            "1",
            [source["occurrence_id"]],
            enclosing,
        )
        subject = {
            "kind": "PARALLEL_BRANCH",
            "construct_id": "parallel-2",
            "pass": "1",
            "source_occurrence_ids": [source["occurrence_id"]],
            "branch_id": branch_id,
            "object_key": None,
            "join_step_id": "child-join",
        }
        operation = next(row["operation"] for row in base["definition"]["steps"] if row["id"] == step_id)
        obligation = {
            "obligation_id": digest("obligation", subject),
            **subject,
            "creation_event_digest": event_digest,
            "status": "OPEN",
            "expected_occurrence_id": child["occurrence_id"],
            "required_operation": operation,
            "waiting_on": None,
            "completion_basis": None,
        }
        children.append((child, obligation))

    def mutate_after(state: dict, occurrence_value: dict, triggering_event_digest: str, evidence_digest: str) -> None:
        parent = next(
            row
            for row in state["obligations"]
            if row["expected_occurrence_id"] == occurrence_value["occurrence_id"]
        )
        if stop_on_limit:
            state["status"] = "STOPPED"
            operation = parent["required_operation"]
            parent["status"] = "DISCHARGED"
            parent["expected_occurrence_id"] = None
            parent["required_operation"] = None
            parent["completion_basis"] = {
                "kind": "DIRECT_EVENT",
                "event_digest": triggering_event_digest,
                "occurrence_id": occurrence_value["occurrence_id"],
                "operation": operation,
                "evidence_digest": evidence_digest,
            }
            return
        for child, obligation in children:
            deadline_ids: list[str] = []
            if install_deadlines:
                definition_deadline = next(
                    row for row in base["definition"]["deadlines"] if row["step_id"] == child["step_id"]
                )
                activation_clock = next(
                    row for row in event["activation_clocks"] if row["source"] == definition_deadline["clock_source"]
                )
                activation_subject = {
                    "deadline_id": definition_deadline["id"],
                    "occurrence_id": child["occurrence_id"],
                    "trigger_digest": triggering_event_digest,
                    "source": definition_deadline["clock_source"],
                    "activation_revision": state["revision"],
                    "activation_clock_revision": activation_clock["revision"],
                    "activation_instant": activation_clock["observed_time"],
                    "activation_clock_evidence_digest": activation_clock["evidence_digest"],
                    "due": definition_deadline["due"]["instant"],
                    "boundary": definition_deadline["boundary"],
                }
                state["deadlines"].append(
                    {
                        "activation_digest": digest("deadline-activation", activation_subject),
                        **activation_subject,
                        "status": "PENDING",
                        "expiry_event_digest": None,
                    }
                )
                deadline_ids = [definition_deadline["id"]]
            state["active"].append(
                {
                    "occurrence": copy.deepcopy(child),
                    "activation_event_digest": triggering_event_digest,
                    "status": "ACTIVE",
                    "deadline_ids": deadline_ids,
                }
            )
            state["obligations"].append(copy.deepcopy(obligation))
            counter = next(row for row in state["step_counters"] if row["step_id"] == child["step_id"])
            counter["activations"] = str(int(counter["activations"]) + 1)
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["obligations"].sort(key=lambda row: row["obligation_id"].encode("utf-8"))
        state["deadlines"].sort(
            key=lambda row: (
                row["due"].encode("utf-8"),
                canonical_bytes(next(
                    active["occurrence"]
                    for active in state["active"]
                    if active["occurrence"]["occurrence_id"] == row["occurrence_id"]
                ))
                if any(
                    active["occurrence"]["occurrence_id"] == row["occurrence_id"]
                    for active in state["active"]
                )
                else canonical_bytes(next(
                    completed["occurrence"]
                    for completed in state["completed"]
                    if completed["occurrence"]["occurrence_id"] == row["occurrence_id"]
                )),
                row["deadline_id"].encode("utf-8"),
            )
        )
        state["total_activations"] = str(int(state["total_activations"]) + len(children))
        parent["status"] = "WAITING"
        parent["expected_occurrence_id"] = None
        parent["required_operation"] = None
        parent["waiting_on"] = {
            "kind": "PARALLEL",
            "construct_id": "parallel-2",
            "pass": "1",
            "outer_enclosing": copy.deepcopy(occurrence_value["enclosing"]),
            "obligation_ids": sorted((obligation["obligation_id"] for _child, obligation in children), key=lambda value: value.encode("utf-8")),
        }

    limit_detail = None
    if stop_on_limit:
        limit_detail = {
            "kind": "LIMIT",
            "limit_kind": "ACTIVE_OBLIGATIONS",
            "limit": "3",
            "current": "4",
            "step_id": "child-a",
            "relationship_digest": selected_digest,
        }
    return effect_transition(
        base,
        dispatched,
        event,
        disposition="STOPPED" if stop_on_limit else "COMPLETED",
        reason_codes=["LIMIT_EXCEEDED"] if stop_on_limit else [],
        relationship_digests=[selected_digest],
        construct_ids=["parallel-2"],
        mutate_after=mutate_after,
        limit_detail=limit_detail,
    )


def direct_obligation_completion(base: dict, dispatched: dict, event: dict) -> dict:
    occurrence_value = event["permit"]["occurrence"]
    selected_digest = digest("relationship", direct_relationship(base, occurrence_value["step_id"]))

    def mutate_after(state: dict, completed: dict, event_digest: str, evidence_digest: str) -> None:
        obligation = next(
            row
            for row in state["obligations"]
            if row["expected_occurrence_id"] == completed["occurrence_id"]
        )
        operation = obligation["required_operation"]
        obligation["status"] = "DISCHARGED"
        obligation["expected_occurrence_id"] = None
        obligation["required_operation"] = None
        obligation["completion_basis"] = {
            "kind": "DIRECT_EVENT",
            "event_digest": event_digest,
            "occurrence_id": completed["occurrence_id"],
            "operation": operation,
            "evidence_digest": evidence_digest,
        }

    construct_id = "parallel-2" if occurrence_value["step_id"].startswith("child-") else "parallel-1"
    return effect_transition(
        base,
        dispatched,
        event,
        disposition="COMPLETED",
        reason_codes=[],
        relationship_digests=[selected_digest],
        construct_ids=[construct_id],
        mutate_after=mutate_after,
    )


def final_child_completion(
    base: dict,
    dispatched: dict,
    event: dict,
    *,
    resume_parent: bool,
    join_parent: bool,
) -> dict:
    occurrence_value = event["permit"]["occurrence"]
    selected_digest = digest("relationship", direct_relationship(base, occurrence_value["step_id"]))
    child_join_relationship = direct_relationship(base, "child-join")
    child_join_digest = digest("relationship", child_join_relationship)
    relationship_digests = [selected_digest, child_join_digest]
    construct_ids = ["parallel-2"]
    if join_parent:
        outer_join = direct_relationship(base, "parallel-join")
        relationship_digests.append(digest("relationship", outer_join))
        construct_ids.append("parallel-1")

    def mutate_after(state: dict, completed: dict, event_digest: str, evidence_digest: str) -> None:
        direct = next(
            row
            for row in state["obligations"]
            if row["expected_occurrence_id"] == completed["occurrence_id"]
        )
        operation = direct["required_operation"]
        direct["status"] = "DISCHARGED"
        direct["expected_occurrence_id"] = None
        direct["required_operation"] = None
        direct["completion_basis"] = {
            "kind": "DIRECT_EVENT",
            "event_digest": event_digest,
            "occurrence_id": completed["occurrence_id"],
            "operation": operation,
            "evidence_digest": evidence_digest,
        }
        child_obligations = [row for row in state["obligations"] if row["construct_id"] == "parallel-2"]
        for row in child_obligations:
            row["status"] = "JOINED"
        parent = next(
            row
            for row in state["obligations"]
            if row["status"] == "WAITING"
            and row["waiting_on"] is not None
            and row["waiting_on"]["construct_id"] == "parallel-2"
        )
        child_pass = copy.deepcopy(parent["waiting_on"])
        frontier = sorted(
            [
                row["completion_basis"]["occurrence_id"]
                for row in child_obligations
                if row["completion_basis"]["kind"] == "DIRECT_EVENT"
            ],
            key=lambda value: value.encode("utf-8"),
        )
        parent["waiting_on"] = None
        if resume_parent:
            successor = occurrence(
                base["definition_digest"],
                completed["instance_id"],
                "outer-successor",
                "1",
                frontier,
                child_pass["outer_enclosing"],
            )
            parent["status"] = "OPEN"
            parent["expected_occurrence_id"] = successor["occurrence_id"]
            parent["required_operation"] = next(
                row["operation"]
                for row in base["definition"]["steps"]
                if row["id"] == "outer-successor"
            )
            state["active"].append(
                {
                    "occurrence": successor,
                    "activation_event_digest": event_digest,
                    "status": "ACTIVE",
                    "deadline_ids": [],
                }
            )
            state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
            counter = next(row for row in state["step_counters"] if row["step_id"] == "outer-successor")
            counter["activations"] = str(int(counter["activations"]) + 1)
            state["total_activations"] = str(int(state["total_activations"]) + 1)
        else:
            parent["status"] = "DISCHARGED"
            parent["expected_occurrence_id"] = None
            parent["required_operation"] = None
            parent["completion_basis"] = {
                "kind": "CHILD_PASS",
                "event_digest": event_digest,
                "child_pass": child_pass,
            }
            if join_parent:
                outer_obligations = [row for row in state["obligations"] if row["construct_id"] == "parallel-1"]
                for row in outer_obligations:
                    row["status"] = "JOINED"
                state["status"] = "COMPLETE"

    return effect_transition(
        base,
        dispatched,
        event,
        disposition="COMPLETED",
        reason_codes=[],
        relationship_digests=relationship_digests,
        construct_ids=construct_ids,
        mutate_after=mutate_after,
    )


def nested_resume_sequence(case_id: str):
    base, outer = setup_outer(case_id)
    _parent_permit, parent_dispatched, parent_effect = execute(base, outer["state"], "outer-a", case_id.lower() + "-outer-a")
    nested = nested_entry_result(base, parent_dispatched, parent_effect)
    _first_permit, first_dispatched, first_effect = execute(base, nested["state"], "child-a", case_id.lower() + "-child-a")
    first = direct_obligation_completion(base, first_dispatched, first_effect)
    _final_permit, final_dispatched, final_effect = execute(base, first["state"], "child-b", case_id.lower() + "-child-b")
    final = final_child_completion(base, final_dispatched, final_effect, resume_parent=True, join_parent=False)
    return base, outer, parent_dispatched, parent_effect, nested, first, final_dispatched, final_effect, final


def build_resume_case(case_id: str, derivation: str) -> None:
    base, _outer, _parent_dispatched, _parent_effect, _nested, _first, final_dispatched, final_effect, final = nested_resume_sequence(case_id)
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(
            case_id,
            "step",
            step_input(base, final_dispatched["state"], final_effect),
            final,
            [],
            derivation,
        ),
    )


def conflict_result(base: dict, state: dict, original_permit: dict, original_dispatch_digest: str, event: dict) -> dict:
    old_evidence_id = next(
        row["native_evidence"]["evidence_id"]
        for row in state["outcomes"]
        if row["permit_digest"] == original_permit["permit_id"] and row["classification"] == "MATCHED"
    )
    new_outcome = governed_outcome(
        event,
        {"state": state},
        classification="CONFLICTING",
        disputed=True,
        conflicts=[old_evidence_id],
    )

    def mutate(next_state: dict) -> None:
        for prior in next_state["outcomes"]:
            if prior["native_evidence"]["evidence_id"] != old_evidence_id:
                continue
            prior["disputed"] = True
            prior["conflicts_with_evidence_ids"] = [event["native_evidence"]["evidence_id"]]
            prior["outcome_digest"] = digest(
                "outcome",
                {key: value for key, value in prior.items() if key != "outcome_digest"},
            )
        next_state["outcomes"].append(copy.deepcopy(new_outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        affected_occurrence = original_permit["occurrence"]["occurrence_id"]
        direct = next(
            row
            for row in next_state["obligations"]
            if row["completion_basis"] is not None
            and row["completion_basis"]["kind"] == "DIRECT_EVENT"
            and row["completion_basis"]["occurrence_id"] == affected_occurrence
        )
        direct["status"] = "DISPUTED"
        parent = next(
            row
            for row in next_state["obligations"]
            if row["status"] == "WAITING"
            and direct["obligation_id"] in row["waiting_on"]["obligation_ids"]
        )
        parent["status"] = "DISPUTED"

    return admitted_transition(
        state,
        event,
        disposition="DISPUTED",
        reason_codes=["CONFLICTING_EFFECT"],
        details=[
            {
                "kind": "EFFECT",
                "classification": "CONFLICTING",
                "evidence_id": event["native_evidence"]["evidence_id"],
            }
        ],
        receipt_permit_digest=original_permit["permit_id"],
        mutate=mutate,
    )


def fixed_point_expiry_result(base: dict, state: dict, event: dict) -> dict:
    selected_clock = event["clock"]
    event_digest = digest("runtime-event", event)
    due_rows = sorted(
        [
            (
                deadline,
                next(
                    active["occurrence"]
                    for active in state["active"]
                    if active["occurrence"]["occurrence_id"] == deadline["occurrence_id"]
                ),
            )
            for deadline in state["deadlines"]
            if deadline["status"] == "PENDING"
            and deadline["source"] == selected_clock["source"]
            and deadline["due"] <= selected_clock["observed_time"]
        ],
        key=lambda pair: (
            pair[0]["due"].encode("utf-8"),
            canonical_bytes(pair[1]),
            pair[0]["deadline_id"].encode("utf-8"),
        ),
    )
    expiry_relationships = {
        deadline["deadline_id"]: next(
            row
            for row in base["definition"]["relationships"]
            if row["kind"] == "EXPIRY" and row["deadline_ref"] == deadline["deadline_id"]
        )
        for deadline, _occurrence in due_rows
    }
    child_join = direct_relationship(base, "child-join")
    outer_join = direct_relationship(base, "parallel-join")
    relationship_digests = [
        *(digest("relationship", row) for row in expiry_relationships.values()),
        digest("relationship", child_join),
        digest("relationship", outer_join),
    ]

    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(selected_clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        due_ids = {occurrence_value["occurrence_id"] for _deadline, occurrence_value in due_rows}
        next_state["active"] = [
            row
            for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] not in due_ids
        ]
        for deadline, occurrence_value in due_rows:
            expiry_digest = digest("relationship", expiry_relationships[deadline["deadline_id"]])
            next_state["completed"].append(
                {
                    "occurrence": copy.deepcopy(occurrence_value),
                    "disposition": "EXPIRED",
                    "evidence_digest": selected_clock["evidence_digest"],
                    "occurred_at": selected_clock["observed_time"],
                    "route_label": None,
                    "selected_relationship_digest": expiry_digest,
                    "late": False,
                }
            )
            retained_deadline = next(
                row
                for row in next_state["deadlines"]
                if row["deadline_id"] == deadline["deadline_id"]
                and row["occurrence_id"] == occurrence_value["occurrence_id"]
            )
            retained_deadline["status"] = "EXPIRED"
            retained_deadline["expiry_event_digest"] = event_digest
            obligation = next(
                row
                for row in next_state["obligations"]
                if row["expected_occurrence_id"] == occurrence_value["occurrence_id"]
            )
            operation = obligation["required_operation"]
            obligation["status"] = "DISCHARGED"
            obligation["expected_occurrence_id"] = None
            obligation["required_operation"] = None
            obligation["completion_basis"] = {
                "kind": "DIRECT_EVENT",
                "event_digest": event_digest,
                "occurrence_id": occurrence_value["occurrence_id"],
                "operation": operation,
                "evidence_digest": selected_clock["evidence_digest"],
            }
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        child_obligations = [row for row in next_state["obligations"] if row["construct_id"] == "parallel-2"]
        for row in child_obligations:
            row["status"] = "JOINED"
        parent = next(
            row
            for row in next_state["obligations"]
            if row["status"] == "WAITING"
            and row["waiting_on"] is not None
            and row["waiting_on"]["construct_id"] == "parallel-2"
        )
        child_pass = copy.deepcopy(parent["waiting_on"])
        parent["status"] = "DISCHARGED"
        parent["expected_occurrence_id"] = None
        parent["required_operation"] = None
        parent["waiting_on"] = None
        parent["completion_basis"] = {
            "kind": "CHILD_PASS",
            "event_digest": event_digest,
            "child_pass": child_pass,
        }
        outer_obligations = [row for row in next_state["obligations"] if row["construct_id"] == "parallel-1"]
        for row in outer_obligations:
            row["status"] = "JOINED"
        next_state["status"] = "COMPLETE"

    return admitted_transition(
        state,
        event,
        disposition="EXPIRED",
        reason_codes=[],
        details=[
            {
                "kind": "CLOCK",
                "source": selected_clock["source"],
                "revision": selected_clock["revision"],
                "status": selected_clock["status"],
            },
            {
                "kind": "DEADLINE",
                "deadline_ids": sorted(
                    [deadline["deadline_id"] for deadline, _occurrence in due_rows],
                    key=lambda value: value.encode("utf-8"),
                ),
                "reasons": [],
            },
            {
                "kind": "ROUTE",
                "relationship_digests": sorted(set(relationship_digests), key=lambda value: value.encode("utf-8")),
                "construct_ids": ["parallel-1", "parallel-2"],
            },
        ],
        mutate=mutate,
    )


def build() -> list[str]:
    produced: list[str] = []

    base, outer = setup_outer("D2-243")
    _permit, dispatched, event = execute(base, outer["state"], "outer-a", "d2-243-outer-a")
    expected = nested_entry_result(base, dispatched, event)
    write_canonical_json(
        GROUP / "D2-243.json",
        exact_case(
            "D2-243",
            "step",
            step_input(base, dispatched["state"], event),
            expected,
            [],
            "The matching outer-a effect selects child-split. Complete preflight admits both child branches. The directly owning outer obligation changes from OPEN to WAITING on the exact parallel-2 child-pass reference while both child occurrences and obligations are created atomically; the independent outer-b obligation remains OPEN.",
        ),
    )
    produced.append("D2-243")

    build_resume_case(
        "D2-244",
        "The final child-b effect discharges the remaining parallel-2 obligation. Both child obligations become JOINED. The child join activates outer-successor in the parent branch, whose predecessor set is the exact recursive child frontier and whose enclosing path retains the outer branch while removing both child-branch segments. The parent obligation becomes OPEN on that successor.",
    )
    produced.append("D2-244")

    build_resume_case(
        "D2-200",
        "The final nested child obligation discharges and parallel-2 joins. The resumed outer-successor occurrence retains the exact common outer-branch prefix, removes the joined child-branch ancestry, and names both final child occurrence identities in raw UTF-8 predecessor order.",
    )
    produced.append("D2-200")

    base, outer = setup_outer("D2-245", child_to_parent_join=True)
    _parent_permit, parent_dispatched, parent_effect = execute(base, outer["state"], "outer-a", "d2-245-outer-a")
    nested = nested_entry_result(base, parent_dispatched, parent_effect)
    _child_permit, child_dispatched, child_effect = execute(base, nested["state"], "child-a", "d2-245-child-a")
    child_first = direct_obligation_completion(base, child_dispatched, child_effect)
    _outer_permit, outer_dispatched, outer_effect = execute(base, child_first["state"], "outer-b", "d2-245-outer-b")
    outer_complete = direct_obligation_completion(base, outer_dispatched, outer_effect)
    _final_permit, final_dispatched, final_effect = execute(base, outer_complete["state"], "child-b", "d2-245-child-b")
    final = final_child_completion(base, final_dispatched, final_effect, resume_parent=False, join_parent=True)
    write_canonical_json(
        GROUP / "D2-245.json",
        exact_case(
            "D2-245",
            "step",
            step_input(base, final_dispatched["state"], final_effect),
            final,
            [],
            "The final child-b effect completes the exact parallel-2 inventory. The child obligations become JOINED and the waiting outer obligation becomes DISCHARGED with a CHILD_PASS basis bound to this event. Because outer-b was already DISCHARGED, fixed-point progression joins parallel-1 and follows its join-to-terminal relationship in the same transition.",
        ),
    )
    produced.append("D2-245")

    base, outer = setup_outer("D2-246", obligation_limit="3")
    _permit, dispatched, event = execute(base, outer["state"], "outer-a", "d2-246-outer-a")
    expected = nested_entry_result(base, dispatched, event, stop_on_limit=True)
    write_canonical_json(
        GROUP / "D2-246.json",
        exact_case(
            "D2-246",
            "step",
            step_input(base, dispatched["state"], event),
            expected,
            [],
            "Entering parallel-2 would raise unresolved obligations from two to four against maximum_active_obligations three. The matched effect and selected route are retained, no child inventory is created, the directly owning outer obligation discharges with the effect's DIRECT_EVENT basis, the outer sibling stays OPEN, and the instance stops.",
        ),
    )
    produced.append("D2-246")

    base, outer = setup_outer("D2-249")
    _parent_permit, parent_dispatched, parent_effect = execute(base, outer["state"], "outer-a", "d2-249-outer-a")
    nested = nested_entry_result(base, parent_dispatched, parent_effect)
    first_permit, first_dispatched, first_effect = execute(base, nested["state"], "child-a", "d2-249-child-a")
    first = direct_obligation_completion(base, first_dispatched, first_effect)
    prior_dispatch_digest = first_effect["dispatch_digest"]
    actual_fields = copy.deepcopy(first_effect["native_evidence"]["actual_fields"])
    next(row for row in actual_fields if row["name"] == "card_id")["value"]["value"] = "card-conflict"
    conflict_evidence = governed_native_evidence(
        base,
        first_permit,
        {"state": first["state"]},
        evidence_id="evidence-d2-249-conflict",
        native_operation_id=first_effect["native_evidence"]["native_operation_id"],
        actual_fields=actual_fields,
        record_digest=digest("provider-native-record", {"record": "d2-249-conflict"}),
        dispatch_digest=prior_dispatch_digest,
    )
    conflict_event = governed_effect_event(
        first_permit,
        {"state": first["state"]},
        conflict_evidence,
        event_id="effect-d2-249-conflict",
        dispatch_digest=prior_dispatch_digest,
    )
    conflict = conflict_result(
        base,
        first["state"],
        first_permit["permit"],
        prior_dispatch_digest,
        conflict_event,
    )
    write_canonical_json(
        GROUP / "D2-249.json",
        exact_case(
            "D2-249",
            "step",
            step_input(base, first["state"], conflict_event),
            conflict,
            [],
            "A second conclusive record for child-a uses the same provider-native operation identity but changes the conclusive fact. Both outcomes become disputed. The child-a completion-based obligation becomes DISPUTED, and the outer obligation waiting on the exact parallel-2 pass becomes the waiting form of DISPUTED. Child-b and the independent outer branch remain active, but neither affected pass can join.",
        ),
    )
    produced.append("D2-249")

    base, outer = setup_outer("D2-255", child_to_parent_join=True, deadlines=True)
    _parent_permit, parent_dispatched, parent_effect = execute(base, outer["state"], "outer-a", "d2-255-outer-a")
    work_clock = next(
        row
        for row in parent_dispatched["state"]["clocks"]
        if row["source"] == "work-clock" and row["status"] == "AVAILABLE"
    )
    parent_effect["activation_clocks"] = [copy.deepcopy(work_clock)]
    nested = nested_entry_result(base, parent_dispatched, parent_effect, install_deadlines=True)
    clock = available_clock("work-clock", "2", "2026-09-10T04:31:00Z")
    clock_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-d2-255",
        "kind": "CLOCK",
        "instance_id": nested["state"]["instance_id"],
        "expected_state_revision": nested["state"]["revision"],
        "expected_state_digest": nested["state_digest"],
        "clock": clock,
        "activation_clocks": [],
    }
    fixed = fixed_point_expiry_result(base, nested["state"], clock_event)
    write_canonical_json(
        GROUP / "D2-255.json",
        exact_case(
            "D2-255",
            "step",
            step_input(base, nested["state"], clock_event),
            fixed,
            [],
            "One accepted clock makes outer-b, child-a, and child-b due together. Their direct obligations discharge first. The complete parallel-2 pass then joins at greater depth, discharging its waiting outer obligation with a CHILD_PASS basis; parallel-1 becomes complete and joins in the next fixed-point round. The combined transition reaches terminal with exact expiry, child-join, and outer-join route commitments.",
        ),
    )
    produced.append("D2-255")

    return produced


def main() -> None:
    produced = build()
    print(json.dumps({"case_ids": produced}, indent=2))


if __name__ == "__main__":
    main()
