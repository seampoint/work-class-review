#!/usr/bin/env python3
"""Build exact parallel sibling behavior after a declared stop."""

from __future__ import annotations

import copy
import json

from composition_fixture import (
    add_authority_operations,
    parallel_definition,
    parallel_entry_result,
    permitted_operation_proposal,
    proposal_for_occurrence,
)
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    governed_outcome,
    permitted_proposal,
    stateful_refusal,
    step_input,
)


GROUP = CASES / "stopped-siblings"
BRANCHES = ["branch-a", "branch-b"]


def setup_parallel(*, deadlines: bool = False) -> tuple[dict, dict]:
    parallel = parallel_definition(BRANCHES)

    def definition_mutator(definition: dict) -> None:
        parallel(definition)
        if not deadlines:
            return
        definition["profile"] = "PARALLEL_FANOUT"
        definition["deadlines"] = [
            {
                "id": step_id + "-deadline",
                "step_id": step_id,
                "clock_source": "work-clock",
                "due": {"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-10T04:31:00Z"},
                "boundary": "AT_OR_AFTER",
                "expiry_target": "parallel-join",
            }
            for step_id in BRANCHES
        ]
        definition["relationships"].extend(
            {
                "kind": "EXPIRY",
                "from": step_id,
                "to": "parallel-join",
                "deadline_ref": step_id + "-deadline",
            }
            for step_id in BRANCHES
        )
        definition["relationships"].sort(key=canonical_bytes)

    base = base_lifecycle(
        authority_mutator=add_authority_operations(BRANCHES),
        definition_mutator=definition_mutator,
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(
        base,
        permitted,
        event_id="dispatch-before-stopped-sibling-entry",
        acknowledgement_status="ACCEPTED",
    )
    dispatched = dispatch_result(
        permitted,
        dispatch,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    transition = dispatched
    activation_clock = None
    if deadlines:
        activation_clock = available_clock("work-clock", "1", "2026-09-10T04:30:00Z")
        clock_event = {
            "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
            "event_id": "clock-before-stopped-sibling-entry",
            "kind": "CLOCK",
            "instance_id": dispatched["state"]["instance_id"],
            "expected_state_revision": dispatched["state"]["revision"],
            "expected_state_digest": dispatched["state_digest"],
            "clock": copy.deepcopy(activation_clock),
            "activation_clocks": [],
        }

        def retain_clock(state: dict) -> None:
            state["clocks"].append(copy.deepcopy(activation_clock))
            state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

        transition = admitted_transition(
            dispatched["state"],
            clock_event,
            disposition="CLOCK_RECORDED",
            reason_codes=[],
            details=[
                {
                    "kind": "CLOCK",
                    "source": activation_clock["source"],
                    "revision": activation_clock["revision"],
                    "status": activation_clock["status"],
                }
            ],
            mutate=retain_clock,
        )
    evidence = governed_native_evidence(
        base,
        permitted,
        transition,
        evidence_id="evidence-stopped-sibling-entry",
        native_operation_id="native-operation-stopped-sibling-entry",
    )
    effect = governed_effect_event(
        permitted,
        transition,
        evidence,
        event_id="effect-stopped-sibling-entry",
    )
    if activation_clock is not None:
        effect["activation_clocks"] = [copy.deepcopy(activation_clock)]
    return base, parallel_entry_result(base, transition, effect, BRANCHES, install_deadlines=deadlines)


def propose_and_dispatch(
    base: dict,
    state: dict,
    occurrence_value: dict,
    *,
    suffix: str,
) -> tuple[dict, dict, dict]:
    proposal, authority_result = proposal_for_occurrence(
        base,
        state,
        occurrence_value,
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
    return proposal, permitted, dispatched


def dispatch_digest(dispatched: dict, event_id: str) -> str:
    return next(
        row["dispatch_digest"]
        for row in dispatched["state"]["dispatches"]
        if row["event_id"] == event_id
    )


def branch_failure_event(
    base: dict,
    permitted: dict,
    dispatched: dict,
    *,
    suffix: str,
) -> dict:
    selected_dispatch_digest = dispatch_digest(dispatched, "dispatch-" + suffix)
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-" + suffix,
        native_operation_id="native-operation-" + suffix,
        result_value="REJECTED",
        dispatch_digest=selected_dispatch_digest,
    )
    return governed_effect_event(
        permitted,
        dispatched,
        evidence,
        event_id="effect-" + suffix,
        dispatch_digest=selected_dispatch_digest,
    )


def branch_failure_stop_result(base: dict, dispatched: dict, event: dict) -> dict:
    occurrence_value = event["permit"]["occurrence"]
    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, dispatched, classification="FAILED", disputed=False)

    def mutate(state: dict) -> None:
        state["status"] = "STOPPED"
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
                "disposition": "FAILED",
                "evidence_digest": evidence_digest,
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": None,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        for deadline in state["deadlines"]:
            if deadline["occurrence_id"] == occurrence_value["occurrence_id"] and deadline["status"] == "PENDING":
                deadline["status"] = "DISCHARGED"
        obligation = next(
            row
            for row in state["obligations"]
            if row["expected_occurrence_id"] == occurrence_value["occurrence_id"]
        )
        obligation["status"] = "DISCHARGED"
        obligation["expected_occurrence_id"] = None
        obligation["required_operation"] = None
        obligation["completion_basis"] = {
            "kind": "DIRECT_EVENT",
            "event_digest": event_digest,
            "occurrence_id": occurrence_value["occurrence_id"],
            "operation": event["permit"]["native_request"]["operation"],
            "evidence_digest": evidence_digest,
        }

    return admitted_transition(
        dispatched["state"],
        event,
        disposition="STOPPED",
        reason_codes=["DECLARED_FAILURE"],
        details=[
            {
                "kind": "EFFECT",
                "classification": "FAILED",
                "evidence_id": event["native_evidence"]["evidence_id"],
            }
        ],
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def late_sibling_result(base: dict, stopped: dict, event: dict) -> dict:
    occurrence_value = event["permit"]["occurrence"]
    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, stopped, classification="LATE_MATCHED", disputed=False)

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
                "selected_relationship_digest": None,
                "late": True,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        obligation = next(
            row
            for row in state["obligations"]
            if row["expected_occurrence_id"] == occurrence_value["occurrence_id"]
        )
        obligation["status"] = "DISCHARGED"
        obligation["expected_occurrence_id"] = None
        obligation["required_operation"] = None
        obligation["completion_basis"] = {
            "kind": "DIRECT_EVENT",
            "event_digest": event_digest,
            "occurrence_id": occurrence_value["occurrence_id"],
            "operation": event["permit"]["native_request"]["operation"],
            "evidence_digest": evidence_digest,
        }

    return admitted_transition(
        stopped["state"],
        event,
        disposition="OUTCOME_RETAINED",
        reason_codes=["LATE_EFFECT"],
        details=[
            {
                "kind": "EFFECT",
                "classification": "LATE_MATCHED",
                "evidence_id": event["native_evidence"]["evidence_id"],
            }
        ],
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def occurrence_for(state: dict, step_id: str) -> dict:
    return next(
        row["occurrence"]
        for row in state["active"]
        if row["occurrence"]["step_id"] == step_id
    )


def stopped_sibling_expiry(stopped: dict, event: dict, occurrence_value: dict) -> dict:
    clock = event["clock"]
    event_digest = digest("runtime-event", event)

    def mutate(state: dict) -> None:
        state["clocks"].append(copy.deepcopy(clock))
        state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        state["active"] = [
            row for row in state["active"]
            if row["occurrence"]["occurrence_id"] != occurrence_value["occurrence_id"]
        ]
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(occurrence_value),
                "disposition": "EXPIRED",
                "evidence_digest": clock["evidence_digest"],
                "occurred_at": clock["observed_time"],
                "route_label": None,
                "selected_relationship_digest": None,
                "late": True,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        deadline = next(
            row for row in state["deadlines"]
            if row["occurrence_id"] == occurrence_value["occurrence_id"]
        )
        deadline["status"] = "EXPIRED"
        deadline["expiry_event_digest"] = event_digest
        obligation = next(
            row for row in state["obligations"]
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
            "evidence_digest": clock["evidence_digest"],
        }

    return admitted_transition(
        stopped["state"],
        event,
        disposition="EXPIRED",
        reason_codes=[],
        details=[
            {"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]},
            {"kind": "DEADLINE", "deadline_ids": ["branch-b-deadline"], "reasons": []},
        ],
        mutate=mutate,
    )


def main() -> None:
    base, entry = setup_parallel()
    branch_a = occurrence_for(entry["state"], "branch-a")
    _proposal, permitted_a, dispatched_a = propose_and_dispatch(
        base,
        entry["state"],
        branch_a,
        suffix="d2-148-stop-a",
    )
    failure = branch_failure_event(
        base,
        permitted_a,
        dispatched_a,
        suffix="d2-148-stop-a",
    )
    stopped = branch_failure_stop_result(base, dispatched_a, failure)
    branch_b = occurrence_for(stopped["state"], "branch-b")
    proposal_b, _authority_result = proposal_for_occurrence(
        base,
        stopped["state"],
        branch_b,
        event_id="proposal-d2-148-after-stop",
    )
    write_canonical_json(
        GROUP / "D2-148.json",
        exact_case(
            "D2-148",
            "step",
            step_input(base, stopped["state"], proposal_b),
            stateful_refusal(stopped["state"], "INSTANCE_NOT_ACTIVE"),
            [],
            "Branch-a's declared failure has stopped the instance while branch-b remains an exact active sibling. A new proposal cannot create permission in a STOPPED instance, so instance-status admission returns INSTANCE_NOT_ACTIVE before current authority evaluation and leaves the sibling and obligations unchanged.",
        ),
    )

    base, entry = setup_parallel()
    branch_b = occurrence_for(entry["state"], "branch-b")
    _proposal_b, permitted_b, dispatched_b = propose_and_dispatch(
        base,
        entry["state"],
        branch_b,
        suffix="d2-149-sibling-b",
    )
    branch_a = occurrence_for(dispatched_b["state"], "branch-a")
    _proposal_a, permitted_a, dispatched_a = propose_and_dispatch(
        base,
        dispatched_b["state"],
        branch_a,
        suffix="d2-149-stop-a",
    )
    failure = branch_failure_event(
        base,
        permitted_a,
        dispatched_a,
        suffix="d2-149-stop-a",
    )
    stopped = branch_failure_stop_result(base, dispatched_a, failure)
    sibling_dispatch_digest = dispatch_digest(stopped, "dispatch-d2-149-sibling-b")
    evidence = governed_native_evidence(
        base,
        permitted_b,
        stopped,
        evidence_id="evidence-d2-149-sibling-b",
        native_operation_id="native-operation-d2-149-sibling-b",
        dispatch_digest=sibling_dispatch_digest,
    )
    event = governed_effect_event(
        permitted_b,
        stopped,
        evidence,
        event_id="effect-d2-149-sibling-b",
        dispatch_digest=sibling_dispatch_digest,
    )
    expected = late_sibling_result(base, stopped, event)
    write_canonical_json(
        GROUP / "D2-149.json",
        exact_case(
            "D2-149",
            "step",
            step_input(base, stopped["state"], event),
            expected,
            [],
            "Branch-b's exact request was permitted and dispatched before branch-a stopped the instance. Its first matching effect remains attributable and closes branch-b as a late success, discharging only that obligation. The transition retains LATE_MATCHED without firing the now-stopped join or changing the instance status.",
        ),
    )

    base, entry = setup_parallel(deadlines=True)
    branch_a = occurrence_for(entry["state"], "branch-a")
    _proposal_a, permitted_a, dispatched_a = propose_and_dispatch(
        base,
        entry["state"],
        branch_a,
        suffix="d2-159-stop-a",
    )
    failure = branch_failure_event(base, permitted_a, dispatched_a, suffix="d2-159-stop-a")
    stopped = branch_failure_stop_result(base, dispatched_a, failure)
    branch_b = occurrence_for(stopped["state"], "branch-b")
    expiry_clock = available_clock("work-clock", "2", "2026-09-10T04:31:00Z")
    clock_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-d2-159",
        "kind": "CLOCK",
        "instance_id": stopped["state"]["instance_id"],
        "expected_state_revision": stopped["state"]["revision"],
        "expected_state_digest": stopped["state_digest"],
        "clock": expiry_clock,
        "activation_clocks": [],
    }
    write_canonical_json(
        GROUP / "D2-159.json",
        exact_case(
            "D2-159",
            "step",
            step_input(base, stopped["state"], clock_event),
            stopped_sibling_expiry(stopped, clock_event, branch_b),
            [],
            "Branch-a's declared failure has already stopped the instance, while branch-b remains active with a pending AT_OR_AFTER deadline. The accepted work-clock sample reaches that due instant. It retains the clock, marks branch-b's deadline expired, closes branch-b late, and discharges only its directly owning obligation. It does not apply the declared expiry route or fire the parallel join, and the instance remains STOPPED.",
        ),
    )

    print(json.dumps({"case_ids": ["D2-148", "D2-149", "D2-159"]}, indent=2))


if __name__ == "__main__":
    main()
