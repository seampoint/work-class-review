#!/usr/bin/env python3
"""Build LIFE-013 dependency-dispute vectors over a parallel block.

When a completed occurrence becomes disputed, the dependency-affected set is that occurrence and
every transitive active or completed descendant through the predecessor lists. Active members
become `BLOCKED_DISPUTE`, their owning `OPEN` obligations become `BLOCKED`, and a `DISCHARGED`
obligation whose completion frontier intersects the set becomes `DISPUTED`. These cases exercise
what later events do against that blocked state; this candidate has no dispute-resolution
transition, so nothing here clears it.
"""

from __future__ import annotations

import copy
import json

from composition_fixture import (
    add_authority_operations, parallel_definition, parallel_entry_result,
    permitted_operation_proposal, proposal_for_occurrence,
)
from fixture_factory import available_clock
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from dependency_dispute_common import apply_dependency_block, dependency_dispute_result
from lifecycle_factory import (
    permit_dispatch,
    admitted_transition, base_lifecycle, dispatch_event, dispatch_result, effect_result,
    governed_effect_event, governed_native_evidence, governed_outcome, permitted_proposal,
    state_digest, stateful_refusal, step_input,
)


GROUP = CASES / "dependency-disputes"
BRANCHES = ["branch-a", "branch-b"]


def parallel_base(instance_id: str) -> tuple[dict, dict, dict, dict]:
    """One parallel split: the entry occurrence completes and opens two branch obligations."""
    base = base_lifecycle(
        instance_id=instance_id,
        authority_mutator=add_authority_operations(BRANCHES),
        definition_mutator=parallel_definition(BRANCHES),
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-entry", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-entry")
    effect = governed_effect_event(permitted, dispatched, evidence, event_id="effect-entry")
    entry = parallel_entry_result(base, dispatched, effect, BRANCHES)
    return base, permitted, dispatched, entry


def permit_branch(base: dict, entry: dict, step_id: str, event_id: str) -> dict:
    occurrence_value = next(
        row["occurrence"] for row in entry["state"]["active"] if row["occurrence"]["step_id"] == step_id
    )
    event, authority_result = proposal_for_occurrence(base, entry["state"], occurrence_value, event_id=event_id)
    return permitted_operation_proposal(base, entry["state"], event, authority_result)


def ancestor_dispute(
    base: dict, permitted: dict, dispatched: dict, carrier: dict, *, evidence_id: str, event_id: str, record: str,
) -> tuple[dict, dict]:
    """A second conclusive record for the entry occurrence's operation identity disputes it."""
    entry_dispatch = permit_dispatch(dispatched["state"], permitted["permit"])["dispatch_digest"]
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id=evidence_id,
        record_digest=digest("provider-native-record", {"record": record}),
    )
    event = governed_effect_event(
        permitted, carrier, evidence, event_id=event_id, dispatch_digest=entry_dispatch
    )
    return event, evidence


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def blocked_after_dispute(base: dict, permitted: dict, dispatched: dict, carrier: dict, entry_evidence_id: str, suffix: str) -> dict:
    """Apply the ancestor dispute and return the resulting blocked state as a carrier view."""
    event, evidence = ancestor_dispute(
        base, permitted, dispatched, carrier,
        evidence_id=f"evidence-ancestor-{suffix}", event_id=f"effect-ancestor-{suffix}", record=f"ancestor-{suffix}",
    )
    result = dependency_dispute_result(
        base, carrier, event, conflicts=[entry_evidence_id],
        source_occurrence_id=permitted["permit"]["occurrence"]["occurrence_id"],
    )
    return {**carrier, "state": result["state"], "state_digest": result["state_digest"]}


def branch_completion(base: dict, permitted: dict, dispatched: dict, event: dict, evidence: dict) -> dict:
    """A branch occurrence completes and discharges its own PARALLEL_BRANCH obligation.

    `lifecycle_factory.effect_result` completes the occurrence but does not discharge a branch
    obligation, which is parallel-specific, so the discharge is applied here.
    """
    occurrence_id = permitted["permit"]["occurrence"]["occurrence_id"]
    step_id = permitted["permit"]["occurrence"]["step_id"]
    operation = next(row for row in base["definition"]["steps"] if row["id"] == step_id)["operation"]
    basis = {
        "event_digest": digest("runtime-event", event),
        "evidence_digest": digest("native-evidence", evidence),
        "kind": "DIRECT_EVENT",
        "occurrence_id": occurrence_id,
        "operation": operation,
    }
    relationship = next(
        row for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == step_id
    )
    relationship_digest = digest("relationship", relationship)
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
        # The branch obligation discharges on its own occurrence's completion; the instance stays
        # ACTIVE because the sibling branch is still open and the join has not fired.
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


def retained_matched_case() -> None:
    """D2-233: matching evidence for a descendant dispatched before the ancestor was disputed."""
    base, permitted, dispatched, entry = parallel_base("case-d2-233")
    permitted_a = permit_branch(base, entry, "branch-a", "propose-d2-233")
    dispatch = dispatch_event(base, permitted_a, event_id="dispatch-d2-233", acknowledgement_status="ACCEPTED")
    dispatched_a = dispatch_result(
        permitted_a, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED"
    )
    blocked = blocked_after_dispute(base, permitted, dispatched, dispatched_a, "evidence-entry", "d2-233")

    evidence = governed_native_evidence(
        base, permitted_a, dispatched_a, evidence_id="evidence-d2-233", native_operation_id="native-operation-a"
    )
    event = governed_effect_event(
        permitted_a, blocked, evidence, event_id="effect-d2-233",
        dispatch_digest=permit_dispatch(dispatched_a["state"], permitted_a["permit"])["dispatch_digest"],
    )
    expected = effect_result(
        base, permitted_a, blocked, event, classification="MATCHED", disposition="OUTCOME_RETAINED",
        reason_codes=["DEPENDENCY_DISPUTED"], occurrence_status=None, disputed=False,
    )
    emit(
        "D2-233", base, blocked["state"], event, expected,
        "The descendant was dispatched before its completed ancestor became disputed, so LIFE-013's dependency-affected set left it BLOCKED_DISPUTE with its owning obligation BLOCKED. The evidence matches the permit, the completion carrier and the stable attempt, so the classification is MATCHED. LIFE-010's disposition table gives a conclusive MATCHED classification for an occurrence already BLOCKED_DISPUTE, with no shared budget, the OUTCOME_RETAINED row: retain the evidence-derived result but leave the occurrence BLOCKED_DISPUTE and its directly owning obligation BLOCKED while the ancestor dispute remains unresolved, and do not route, fire a join or create a successor. That row precedes every ordinary or stopped-instance late-evidence row. LIFE-006's mapping adds DEPENDENCY_DISPUTED to the classification-specific reasons for a conclusive classification on an already-blocked occurrence with no disputed budget result, and the MATCHED row with no stop condition contributes nothing, so the complete set is DEPENDENCY_DISPUTED. This candidate has no dispute-resolution transition, so the conclusive result cannot clear the ancestor dispute.",
    )


def prohibited_dispatch_case() -> None:
    """D2-236: a possibly-sent attempt against a permit whose occurrence is now blocked."""
    base, permitted, dispatched, entry = parallel_base("case-d2-236")
    permitted_a = permit_branch(base, entry, "branch-a", "propose-d2-236")
    blocked = blocked_after_dispute(base, permitted, dispatched, permitted_a, "evidence-entry", "d2-236")

    event = dispatch_event(base, permitted_a, event_id="dispatch-d2-236", attempt_status="SENT", acknowledgement_status="NONE")
    event["expected_state_revision"] = blocked["state"]["revision"]
    event["expected_state_digest"] = blocked["state_digest"]
    expected = dispatch_result(
        blocked, event, disposition="DISPUTED", reasons=["LATE_OR_PROHIBITED_DISPATCH"],
        occurrence_status="BLOCKED_DISPUTE",
    )
    emit(
        "D2-236", base, blocked["state"], event, expected,
        "The descendant was permitted but never dispatched when its completed ancestor became disputed, so LIFE-013 left it BLOCKED_DISPUTE with its owning obligation BLOCKED. LIFE-009 decides the attempt: a terminal instance, closed occurrence or occurrence status other than PERMITTED adds LATE_OR_PROHIBITED_DISPATCH, and the occurrence is BLOCKED_DISPUTE. A SENT attempt is possibly sent, and a possibly sent attempt produces DISPUTED with LATE_OR_PROHIBITED_DISPATCH and never reopens its route. The request matches the permit and the permit is neither expired nor superseded, so no other reason joins; LIFE-006 fixes a DISPATCH_OBSERVED decision's reason codes to exactly the DISPATCH detail's reasons. The attempt consumes the permit and is retained for reconciliation, but LIFE-013 leaves the occurrence BLOCKED_DISPUTE and its obligation BLOCKED, and dispatchability is not restored.",
    )


def disputed_discharged_obligation_case() -> None:
    """D2-248: conflicting evidence disputes the completed occurrence in a discharged branch."""
    base, permitted, dispatched, entry = parallel_base("case-d2-248")
    permitted_a = permit_branch(base, entry, "branch-a", "propose-d2-248")
    dispatch = dispatch_event(base, permitted_a, event_id="dispatch-d2-248", acknowledgement_status="ACCEPTED")
    dispatched_a = dispatch_result(
        permitted_a, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED"
    )
    completion_evidence = governed_native_evidence(
        base, permitted_a, dispatched_a, evidence_id="evidence-d2-248-first", native_operation_id="native-operation-a"
    )
    completion_event = governed_effect_event(permitted_a, dispatched_a, completion_evidence, event_id="effect-d2-248-first")
    completed = branch_completion(base, permitted_a, dispatched_a, completion_event, completion_evidence)
    carrier = {**dispatched_a, "state": completed["state"], "state_digest": completed["state_digest"]}

    evidence = governed_native_evidence(
        base, permitted_a, dispatched_a, evidence_id="evidence-d2-248", native_operation_id="native-operation-a",
        record_digest=digest("provider-native-record", {"record": "D2-248"}),
    )
    event = governed_effect_event(
        permitted_a, carrier, evidence, event_id="effect-d2-248",
        dispatch_digest=permit_dispatch(dispatched_a["state"], permitted_a["permit"])["dispatch_digest"],
    )
    expected = dependency_dispute_result(
        base, carrier, event, conflicts=[completion_evidence["evidence_id"]],
        source_occurrence_id=permitted_a["permit"]["occurrence"]["occurrence_id"],
    )
    emit(
        "D2-248", base, carrier["state"], event, expected,
        "One branch occurrence completed and discharged its obligation while the sibling obligation remained OPEN. The later record shares that occurrence's provider-native operation identity and differs in content, so LIFE-010 classifies it CONFLICTING and LIFE-006 fixes the reason set to CONFLICTING_EFFECT. The disputed occurrence is completed, so LIFE-013's dependency rule runs: the affected set is that occurrence and its transitive descendants, of which it has none, so no active occurrence changes and the open sibling obligation is untouched. The discharged branch obligation's completion frontier is exactly that occurrence, so it becomes DISPUTED while retaining its completion basis. Under LIFE-017 a DISPUTED obligation does not satisfy a join, so the pass can never join in this candidate even after the sibling discharges. The completed row and its selected route remain historical; LIFE-013 does not rewrite earlier permission or completed routing.",
    )


def branch_deadline_definition(definition: dict) -> None:
    """The parallel block, plus one elapsed-duration deadline on the first branch."""
    parallel_definition(BRANCHES)(definition)
    # Both branches carry a deadline so the parallel entry installs them uniformly; only the
    # first branch's deadline comes due in this case.
    definition["deadlines"] = [
        {
            "id": "deadline-a", "step_id": "branch-a", "clock_source": "authority-clock",
            "due": {"kind": "ELAPSED_DURATION", "value": "1", "unit": "MINUTE"},
            "boundary": "AT_OR_AFTER", "expiry_target": "parallel-join",
        },
        {
            "id": "deadline-b", "step_id": "branch-b", "clock_source": "authority-clock",
            "due": {"kind": "ELAPSED_DURATION", "value": "10", "unit": "MINUTE"},
            "boundary": "AT_OR_AFTER", "expiry_target": "parallel-join",
        },
    ]
    definition["relationships"].extend([
        {"kind": "EXPIRY", "from": "branch-a", "to": "parallel-join", "deadline_ref": "deadline-a"},
        {"kind": "EXPIRY", "from": "branch-b", "to": "parallel-join", "deadline_ref": "deadline-b"},
    ])


def blocked_deadline_expiry_case() -> None:
    """D2-237: the due clock satisfies a deadline whose occurrence is dependency-blocked."""
    base = base_lifecycle(
        instance_id="case-d2-237",
        authority_mutator=add_authority_operations(BRANCHES),
        definition_mutator=branch_deadline_definition,
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-entry", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-entry")
    effect = governed_effect_event(permitted, dispatched, evidence, event_id="effect-entry")
    effect["activation_clocks"] = [copy.deepcopy(base["clock_result"]["state"]["clocks"][0])]
    entry = parallel_entry_result(base, dispatched, effect, BRANCHES, install_deadlines=True)
    carrier = {**dispatched, "state": entry["state"], "state_digest": entry["state_digest"]}
    blocked = blocked_after_dispute(base, permitted, dispatched, carrier, "evidence-entry", "d2-237")

    clock = available_clock("authority-clock", "2", "2026-09-10T04:31:00Z")
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "clock-d2-237",
        "kind": "CLOCK", "instance_id": blocked["state"]["instance_id"],
        "expected_state_revision": blocked["state"]["revision"],
        "expected_state_digest": blocked["state_digest"],
        "clock": copy.deepcopy(clock), "activation_clocks": [],
    }
    event_digest = digest("runtime-event", event)

    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        # LIFE-014: evidence only. The deadline records its expiry; the occurrence stays in active
        # work at BLOCKED_DISPUTE and no route, join or successor follows.
        target = next(row for row in next_state["deadlines"] if row["deadline_id"] == "deadline-a")
        target["status"] = "EXPIRED"
        target["expiry_event_digest"] = event_digest

    expected = admitted_transition(
        blocked["state"], event, disposition="EXPIRED", reason_codes=[],
        details=[
            {"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]},
            {"kind": "DEADLINE", "deadline_ids": ["deadline-a"], "reasons": []},
        ],
        mutate=mutate,
    )
    emit(
        "D2-237", base, blocked["state"], event, expected,
        "The branch occurrence's completed ancestor was disputed, so LIFE-013 left the occurrence BLOCKED_DISPUTE and its owning obligation BLOCKED. The available clock satisfies the AT_OR_AFTER predicate at equality with the elapsed due instant. LIFE-014 decides the rest directly: a due deadline whose occurrence is BLOCKED_DISPUTE is evidence-only, so the occurrence remains BLOCKED_DISPUTE, its directly owning obligation remains BLOCKED, and it contributes no expiry route, join or successor while the ancestor dispute remains unresolved. That is the explicit contrast with the following sentence, which governs an eligible non-BLOCKED_DISPUTE occurrence and does remove it from dispatchable active work and follow the declared expiry relationship. LIFE-006 gives a normal CLOCK/EXPIRED decision an empty reason set, and the decision carries CLOCK and DEADLINE details with no ROUTE detail because no route is selected. The deadline row records EXPIRED as evidence and the instance status is unchanged.",
    )


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    retained_matched_case()
    prohibited_dispatch_case()
    disputed_discharged_obligation_case()
    blocked_deadline_expiry_case()
    # D2-251 moved to build-unjoined-pass-checkpoint-case.py, which starts from a reachable joined state.
    print(json.dumps({"case_ids": ["D2-233", "D2-236", "D2-237", "D2-248"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
