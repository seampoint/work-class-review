#!/usr/bin/env python3
"""Build branch onward-route vectors: a branch whose head routes to a second operation.

PAR-001: "When an eligible direct route within the same branch or object region activates one
operation successor, the obligation replaces its expected occurrence and required operation
atomically." These two cases fix that replacement and what a later ancestor dispute does to the
obligation once the branch has discharged through its second operation.
"""

from __future__ import annotations

import copy
import json

from composition_fixture import (
    add_authority_operations, parallel_definition, parallel_entry_result,
    permitted_operation_proposal, proposal_for_occurrence,
)
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from dependency_dispute_common import dependency_dispute_result
from lifecycle_factory import (
    admitted_transition, base_lifecycle, dispatch_event, dispatch_result, governed_effect_event,
    governed_native_evidence, governed_outcome, permitted_proposal, step_input,
)


GROUP = CASES / "branch-routes"
HEADS = ["branch-a", "branch-b"]
SECOND = "branch-a-next"
OPERATIONS = HEADS + [SECOND]


def two_step_branch(definition: dict) -> None:
    """The parallel block, with the first branch routing through a second operation."""
    parallel_definition(HEADS)(definition)
    definition["relationships"] = [
        row for row in definition["relationships"]
        if not (row["kind"] == "SEQUENCE" and row["from"] == "branch-a" and row["to"] == "parallel-join")
    ]
    definition["relationships"].extend([
        {"kind": "SEQUENCE", "from": "branch-a", "to": SECOND},
        {"kind": "SEQUENCE", "from": SECOND, "to": "parallel-join"},
    ])


def dispatch_digest_of(dispatched: dict, event: dict) -> str:
    """The retained dispatch for this event; the list is digest-sorted, so [-1] is not it."""
    return next(
        row["dispatch_digest"] for row in dispatched["state"]["dispatches"]
        if row["event_id"] == event["event_id"]
    )


def branch_entry(instance_id: str) -> tuple[dict, dict, dict, dict]:
    base = base_lifecycle(
        instance_id=instance_id,
        authority_mutator=add_authority_operations(OPERATIONS),
        definition_mutator=two_step_branch,
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-entry", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-entry")
    effect = governed_effect_event(permitted, dispatched, evidence, event_id="effect-entry")
    entry = parallel_entry_result(base, dispatched, effect, HEADS)
    return base, permitted, dispatched, entry


def run_operation(base: dict, carrier: dict, state_holder: dict, step_id: str, suffix: str) -> tuple[dict, dict, dict, str]:
    """Propose, permit and dispatch the active occurrence at `step_id`."""
    occurrence_value = next(
        row["occurrence"] for row in state_holder["state"]["active"] if row["occurrence"]["step_id"] == step_id
    )
    proposal, authority_result = proposal_for_occurrence(
        base, state_holder["state"], occurrence_value, event_id=f"propose-{suffix}"
    )
    permitted = permitted_operation_proposal(base, state_holder["state"], proposal, authority_result)
    dispatch = dispatch_event(base, permitted, event_id=f"dispatch-{suffix}", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(
        permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED"
    )
    return permitted, dispatched, dispatch, dispatch_digest_of(dispatched, dispatch)


def routed_completion(
    base: dict, permitted: dict, dispatched: dict, event: dict, evidence: dict, *, successor_step: str,
) -> dict:
    """The head occurrence completes and routes onward, replacing the obligation's expectation."""
    occurrence_value = permitted["permit"]["occurrence"]
    occurrence_id = occurrence_value["occurrence_id"]
    step_id = occurrence_value["step_id"]
    relationship = next(
        row for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == step_id
    )
    relationship_digest = digest("relationship", relationship)
    successor = _successor_occurrence(base, occurrence_value, successor_step)
    successor_operation = next(row for row in base["definition"]["steps"] if row["id"] == successor_step)["operation"]
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)

    def mutate(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        index = next(
            i for i, row in enumerate(next_state["active"])
            if row["occurrence"]["occurrence_id"] == occurrence_id
        )
        active = next_state["active"].pop(index)
        next_state["completed"].append({
            "occurrence": copy.deepcopy(active["occurrence"]), "disposition": "SUCCEEDED",
            "evidence_digest": digest("native-evidence", evidence),
            "occurred_at": evidence["event_time"], "route_label": None,
            "selected_relationship_digest": relationship_digest, "late": False,
        })
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        next_state["active"].append({
            "occurrence": copy.deepcopy(successor), "status": "ACTIVE",
            "activation_event_digest": digest("runtime-event", event), "deadline_ids": [],
        })
        next_state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        counter = next(row for row in next_state["step_counters"] if row["step_id"] == successor_step)
        counter["activations"] = str(int(counter["activations"]) + 1)
        next_state["total_activations"] = str(int(next_state["total_activations"]) + 1)
        # PAR-001: the obligation replaces its expected occurrence and required operation
        # atomically; it does not discharge on an onward route within the branch.
        for obligation in next_state["obligations"]:
            if obligation.get("expected_occurrence_id") != occurrence_id:
                continue
            obligation["expected_occurrence_id"] = successor["occurrence_id"]
            obligation["required_operation"] = successor_operation

    return admitted_transition(
        dispatched["state"], event, disposition="COMPLETED", reason_codes=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


def _successor_occurrence(base: dict, source: dict, step_id: str) -> dict:
    from fixture_factory import occurrence as make_occurrence
    return make_occurrence(
        base["definition_digest"], source["instance_id"], step_id, "1",
        [source["occurrence_id"]], copy.deepcopy(source["enclosing"]),
    )


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def branch_onward_route_case() -> None:
    """D2-114: the branch head routes to a second operation before reaching its join."""
    base, permitted, dispatched, entry = branch_entry("case-d2-114")
    permitted_a, dispatched_a, _, digest_a = run_operation(base, dispatched, entry, "branch-a", "d2-114")
    evidence = governed_native_evidence(
        base, permitted_a, dispatched_a, evidence_id="evidence-d2-114",
        native_operation_id="native-operation-a", dispatch_digest=digest_a,
    )
    event = governed_effect_event(
        permitted_a, dispatched_a, evidence, event_id="effect-d2-114", dispatch_digest=digest_a
    )
    expected = routed_completion(base, permitted_a, dispatched_a, event, evidence, successor_step=SECOND)
    emit(
        "D2-114", base, dispatched_a["state"], event, expected,
        "The branch head's declared SEQUENCE relationship reaches another operation rather than the join, so the eligible direct route activates one operation successor inside the same branch. PAR-001 fixes the consequence: the obligation replaces its expected occurrence and required operation atomically. It therefore stays OPEN with no completion basis, now expecting the successor occurrence and its operation, and the join cannot fire while the obligation is unsatisfied. The completed head occurrence records the selected relationship, and the successor occurrence inherits the branch enclosing segment with the head as its predecessor. LIFE-006 gives a MATCHED effect with no stop condition and no disputed budget an empty reason set, and the decision carries EFFECT and ROUTE details.",
    )


def disputed_branch_ancestor_case() -> None:
    """D2-256: an ancestor inside a discharged branch is disputed after the branch completed."""
    base, permitted, dispatched, entry = branch_entry("case-d2-256")
    permitted_a, dispatched_a, _, digest_a = run_operation(base, dispatched, entry, "branch-a", "d2-256-head")
    head_evidence = governed_native_evidence(
        base, permitted_a, dispatched_a, evidence_id="evidence-d2-256-head",
        native_operation_id="native-operation-a", dispatch_digest=digest_a,
    )
    head_event = governed_effect_event(
        permitted_a, dispatched_a, head_evidence, event_id="effect-d2-256-head", dispatch_digest=digest_a
    )
    routed = routed_completion(base, permitted_a, dispatched_a, head_event, head_evidence, successor_step=SECOND)
    routed_view = {**dispatched_a, "state": routed["state"], "state_digest": routed["state_digest"]}

    permitted_2, dispatched_2, _, digest_2 = run_operation(base, dispatched_a, routed_view, SECOND, "d2-256-second")
    second_evidence = governed_native_evidence(
        base, permitted_2, dispatched_2, evidence_id="evidence-d2-256-second",
        native_operation_id="native-operation-a-next", dispatch_digest=digest_2,
    )
    second_event = governed_effect_event(
        permitted_2, dispatched_2, second_evidence, event_id="effect-d2-256-second", dispatch_digest=digest_2
    )
    discharged = branch_discharge(base, permitted_2, dispatched_2, second_event, second_evidence)
    carrier = {**dispatched_a, "state": discharged["state"], "state_digest": discharged["state_digest"]}

    evidence = governed_native_evidence(
        base, permitted_a, dispatched_a, evidence_id="evidence-d2-256",
        native_operation_id="native-operation-a",
        record_digest=digest("provider-native-record", {"record": "D2-256"}), dispatch_digest=digest_a,
    )
    event = governed_effect_event(
        permitted_a, carrier, evidence, event_id="effect-d2-256", dispatch_digest=digest_a
    )
    expected = dependency_dispute_result(
        base, carrier, event, conflicts=[head_evidence["evidence_id"]],
        source_occurrence_id=permitted_a["permit"]["occurrence"]["occurrence_id"],
    )
    emit(
        "D2-256", base, carrier["state"], event, expected,
        "Operation A completed and routed to B inside one unjoined branch, B completed and discharged the branch obligation, and the sibling obligation remained open. The later record shares A's provider-native operation identity and differs in content, so LIFE-010 classifies it CONFLICTING and LIFE-006 fixes the reason set to CONFLICTING_EFFECT. A is completed, so LIFE-013's dependency rule runs and the affected set is A together with every transitive descendant, which here is the completed B. The discharged obligation's completion frontier is B, which is in that set, so the obligation becomes DISPUTED and the pass can never join in this candidate. Both completed rows and their selected routes remain historical; LIFE-013 does not rewrite earlier permission or completed routing. The open sibling obligation is untouched.",
    )


def branch_discharge(base: dict, permitted: dict, dispatched: dict, event: dict, evidence: dict) -> dict:
    """The last operation in a branch completes, discharging the branch obligation."""
    occurrence_value = permitted["permit"]["occurrence"]
    occurrence_id = occurrence_value["occurrence_id"]
    step_id = occurrence_value["step_id"]
    operation = next(row for row in base["definition"]["steps"] if row["id"] == step_id)["operation"]
    relationship = next(
        row for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == step_id
    )
    relationship_digest = digest("relationship", relationship)
    basis = {
        "event_digest": digest("runtime-event", event),
        "evidence_digest": digest("native-evidence", evidence),
        "kind": "DIRECT_EVENT", "occurrence_id": occurrence_id, "operation": operation,
    }
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)

    def mutate(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        index = next(
            i for i, row in enumerate(next_state["active"])
            if row["occurrence"]["occurrence_id"] == occurrence_id
        )
        active = next_state["active"].pop(index)
        next_state["completed"].append({
            "occurrence": copy.deepcopy(active["occurrence"]), "disposition": "SUCCEEDED",
            "evidence_digest": digest("native-evidence", evidence),
            "occurred_at": evidence["event_time"], "route_label": None,
            "selected_relationship_digest": relationship_digest, "late": False,
        })
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        for obligation in next_state["obligations"]:
            if obligation.get("expected_occurrence_id") != occurrence_id:
                continue
            obligation["status"] = "DISCHARGED"
            obligation["completion_basis"] = copy.deepcopy(basis)
            obligation["expected_occurrence_id"] = None
            obligation["required_operation"] = None

    return admitted_transition(
        dispatched["state"], event, disposition="COMPLETED", reason_codes=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": ["parallel-1"]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    branch_onward_route_case()
    disputed_branch_ancestor_case()
    print(json.dumps({"case_ids": ["D2-114", "D2-256"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
