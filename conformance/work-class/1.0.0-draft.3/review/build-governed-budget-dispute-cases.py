#!/usr/bin/env python3
"""Build governed budget-backed dispute vectors from LIFE-010 and RES-WIRE-003.

Covers a clean, non-disputed dispatch whose settlement is nonetheless disputed by the
registry itself: a matching effect the shared-budget journal fails to corroborate.
"""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock
from lifecycle_budget_fixture import initial_budget_success, permitted_budget_proposal, reserve_for_proposal
from lifecycle_factory import (
    admitted_transition, base_lifecycle, dispatch_event, dispatch_result, governed_effect_event,
    governed_native_evidence, governed_outcome, step_input,
)
from reservation_fixture import effect_record, fixture, host_and_event, native as native_record, registered_state, request as reservation_request, transition as reservation_transition


GROUP = CASES / "governed-budget-disputes"
REGISTRY_CLOCK_INSTANT = "2026-09-10T04:30:00Z"
REGISTRY_CLOCK_REVISION = "1"


def matching_native_record(facts: dict, evidence: dict, reservation_id: str) -> dict:
    """The clean, non-mismatched embedding LIFE-010 constructs for a matching settle."""
    record = native_record(
        facts, "EFFECT", evidence["evidence_id"], reservation_id=reservation_id,
        completion_mismatch=False, mismatch_reason=None, effect_id=evidence["native_operation_id"],
    )
    record["provider"] = evidence["provider"]
    record["source"] = evidence["source"]
    record["evidence_ref"] = evidence["evidence_ref"]
    record["actual_fields"] = copy.deepcopy(evidence["actual_fields"])
    record["collections"] = copy.deepcopy(evidence["collections"])
    record["rules_out_past_and_future_effects"] = evidence["rules_out_past_and_future_effects"]
    record["occurred_at"] = evidence["event_time"]
    return record


def uncorroborated_settle(
    facts: dict, registry_state: dict, reservation_id: str, event_id: str, record: dict,
    blocked_partitions: list[dict],
) -> tuple[dict, dict]:
    """A SETTLE embedding an unchanged initial history that never recorded this effect.

    RES-WIRE-003: "Missing journal corroboration retains EFFECT_DISPUTED rather than claiming
    settlement." Resupplying the untouched initial history (still only its opening entry)
    guarantees the prescribed committed event is absent, since its id is a digest of the
    effect id and mapping and can never coincide with an unrelated entry.
    """
    registry_digest = digest("reservation-registry", registry_state["core"]["configuration"])
    embedded_id = digest(
        "lifecycle-reservation-event",
        {
            "instance_id": facts["authority_a"]["proposal"]["instance"], "lifecycle_event_id": event_id,
            "lifecycle_event_kind": "EFFECT_OBSERVED", "reservation_event_kind": "SETTLE",
            "registry_digest": registry_digest,
        },
    )
    event, host = host_and_event(
        facts, "SETTLE", embedded_id, registry_state["core"]["revision"],
        {"native": record, "histories": [facts["history"]]},
        event_clock=facts["clock"], administration=None,
    )
    core = copy.deepcopy(registry_state["core"])
    for reservation in core["reservations"]:
        if reservation["id"] == reservation_id:
            reservation["status"] = "DISPUTED"
    core["effects"].append(effect_record(record, "DISPUTED", "HISTORY_UNCORROBORATED", blocked_partitions))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    result = reservation_transition(
        registry_state, event, host, core, "EFFECT_DISPUTED",
        reservation_id=reservation_id, reasons=["HISTORY_UNCORROBORATED"],
    )
    budget_input = {
        "registry_digest": registry_digest, "affected_anchors": ["license-spend"],
        "expected_revision": registry_state["core"]["revision"],
        "request": reservation_request(registry_state, event, host),
    }
    budget_output = {"registry_digest": registry_digest, "affected_anchors": ["license-spend"], "result": result}
    return budget_input, budget_output


def matched_history_uncorroborated_case() -> None:
    """D2-230: a matching settle the registry disputes for missing journal corroboration."""
    base, facts, proposal, permitted = initial_budget_success(
        instance_id="case-d2-230", event_id="proposal-d2-230"
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]

    clean_event = dispatch_event(
        base, permitted, event_id="dispatch-d2-230", attempt_status="SENT",
        attempted_at=REGISTRY_CLOCK_INSTANT, clock_revision=REGISTRY_CLOCK_REVISION,
    )
    dispatched = dispatch_result(
        permitted, clean_event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED",
    )
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-230",
        status="EFFECT_ESTABLISHED", observed_at=REGISTRY_CLOCK_INSTANT,
    )
    record = matching_native_record(facts, evidence, reservation_id)
    # RES-WIRE-003: the reservation's own original contribution is always among the blocked
    # partitions once its exposure is disputed, independent of what the effect actually projects.
    reservation_row = next(row for row in registry_state["core"]["reservations"] if row["id"] == reservation_id)
    blocked_partitions = [
        {"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_row["contributions"]
    ]
    budget_input, budget_output = uncorroborated_settle(
        facts, registry_state, reservation_id, "effect-d2-230", record, blocked_partitions
    )
    event = governed_effect_event(
        permitted, dispatched, evidence, event_id="effect-d2-230",
        budget_inputs=[budget_input], clock_revision=REGISTRY_CLOCK_REVISION,
    )
    reason_codes = sorted(
        {"BUDGET_EFFECT_DISPUTED", "HISTORY_UNCORROBORATED"}, key=lambda value: value.encode("utf-8")
    )
    receipt_digest = budget_output["result"]["receipt_digest"]
    outcome = governed_outcome(
        event, dispatched, classification="MATCHED", disputed=True,
        reservation_receipt_digests=[receipt_digest],
    )

    def mutate(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active = next(
            (row for row in next_state["active"] if row["occurrence"]["occurrence_id"] == permitted["permit"]["occurrence"]["occurrence_id"]),
            None,
        )
        if active is not None:
            active["status"] = "BLOCKED_DISPUTE"

    expected = admitted_transition(
        dispatched["state"], event, disposition="DISPUTED", reason_codes=reason_codes,
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output["registry_digest"], "receipt_digest": receipt_digest, "reasons": ["HISTORY_UNCORROBORATED"]},
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence["evidence_id"]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], budget_results=[budget_output], mutate=mutate,
    )
    write_canonical_json(
        GROUP / "D2-230.json",
        exact_case(
            "D2-230", "step", step_input(base, dispatched["state"], event), expected, [],
            "The dispatch exactly matches the permit, so the lifecycle classification is MATCHED with no mismatch of its own: completion_mismatch is false and the embedded native record copies the reservation's exact retained request. RES-WIRE-003 requires all prescribed committed event records in every supplied current journal before a settlement can be claimed. The supplied history is the registry's original opening journal, which never recorded this effect's prescribed event, so journal corroboration fails independently of the clean dispatch. The registry retains disputed exposure with reason HISTORY_UNCORROBORATED rather than settling. LIFE-010's disposition table places this budget-disputed MATCHED classification under the general budget-disputed row, so the lifecycle changes the occurrence to BLOCKED_DISPUTE and does not apply the otherwise matching success route.",
        ),
    )


def add_issue_deadline(definition: dict) -> None:
    """One absolute deadline on the operation step, with its own clock source."""
    definition["profile"] = "DEADLINES"
    definition["deadlines"] = [
        {
            "id": "issue-deadline", "step_id": "issue", "clock_source": "work-clock",
            "due": {"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-10T04:31:00Z"},
            "boundary": "AT_OR_AFTER", "expiry_target": "terminal",
        }
    ]
    definition["relationships"].append(
        {"kind": "EXPIRY", "from": "issue", "to": "terminal", "deadline_ref": "issue-deadline"}
    )
    definition["relationships"].sort(key=canonical_bytes)


def budget_lifecycle_with_clocks(instance_id: str, definition_mutator, initial_clocks: list[dict]) -> tuple[dict, dict]:
    """`lifecycle_budget_fixture.budget_lifecycle`, with `initial_clocks` reaching base_lifecycle.

    The shared fixture does not pass that argument through, and a deadline on the root step needs
    an initial clock for its source at deployment time. Batch-local rather than a fixture change.
    """
    base = base_lifecycle(
        shared_budget=True, instance_id=instance_id,
        definition_mutator=definition_mutator, initial_clocks=initial_clocks,
    )
    facts = fixture()
    facts["authority_a"] = copy.deepcopy(base["authority_input"])
    facts["authority_a_result"] = copy.deepcopy(base["authority_result"])
    completion = next(row for row in base["definition"]["steps"] if row["kind"] == "OPERATION")["completion"]
    facts["budget"]["contributor_classes"] = [base["definition"]["id"]]
    facts["budget"]["reservation_policy"]["settlement"] = {
        "provider": completion["effect_provider"], "source": completion["effect_source"]
    }
    facts["budget"]["reservation_policy"]["no_effect"] = {
        "provider": completion["no_effect_provider"], "source": completion["no_effect_source"]
    }
    budget_digest = digest("budget-definition", facts["budget"])
    authorization = facts["authorizations"][0]
    authorization["budget_digest"] = budget_digest
    authorization["work_class"] = base["definition"]["id"]
    authorization["work_class_digest"] = digest("authority-work-class", base["authority_input"]["work_class"])
    authorization["envelope_digest"] = digest("authority-envelope", base["authority_input"]["envelope"])
    authorization["step"] = base["proposal_event"]["occurrence"]["step_id"]
    authorization["authority_definition"] = {
        "schema": "seampoint.work-class/1.0.0-draft.3/authority-definition",
        **{key: copy.deepcopy(base["authority_input"][key]) for key in ("source", "work_class", "envelope")},
    }
    facts["history"]["budget_digest"] = budget_digest
    return base, facts


def work_state_digest(state: dict) -> str:
    projected = copy.deepcopy(state)
    for replay in projected["replays"]:
        replay.pop("transaction_digest", None)
    return digest("work-state", projected)


def deadline_expiry(base: dict, state: dict, clock: dict, event_id: str) -> tuple[dict, dict]:
    """LIFE-012/LIFE-014: the due clock closes the occurrence EXPIRED along its declared edge."""
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": event_id,
        "kind": "CLOCK", "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"], "expected_state_digest": work_state_digest(state),
        "clock": copy.deepcopy(clock), "activation_clocks": [],
    }
    event_digest = digest("runtime-event", event)
    deadline = next(row for row in state["deadlines"] if row["deadline_id"] == "issue-deadline")
    active = next(row for row in state["active"] if row["occurrence"]["occurrence_id"] == deadline["occurrence_id"])
    relationship = next(row for row in base["definition"]["relationships"] if row["kind"] == "EXPIRY")
    relationship_digest = digest("relationship", relationship)

    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        next_state["active"] = [
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] != active["occurrence"]["occurrence_id"]
        ]
        next_state["completed"].append({
            "occurrence": copy.deepcopy(active["occurrence"]), "disposition": "EXPIRED",
            "evidence_digest": clock["evidence_digest"], "occurred_at": clock["observed_time"],
            "route_label": None, "selected_relationship_digest": relationship_digest, "late": False,
        })
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        target = next(row for row in next_state["deadlines"] if row["deadline_id"] == "issue-deadline")
        target["status"] = "EXPIRED"
        target["expiry_event_digest"] = event_digest
        next_state["status"] = "COMPLETE"

    return event, admitted_transition(
        state, event, disposition="EXPIRED", reason_codes=[],
        details=[
            {"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]},
            {"kind": "DEADLINE", "deadline_ids": ["issue-deadline"], "reasons": []},
            {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []},
        ],
        mutate=mutate,
    )


def late_matched_uncorroborated_case() -> None:
    """D2-235: a matching effect arrives after deadline closure, with an uncorroborated journal."""
    base, facts = budget_lifecycle_with_clocks(
        "case-d2-235", add_issue_deadline, [available_clock("work-clock", "1", "2026-09-10T04:00:00Z")]
    )
    proposal = copy.deepcopy(base["proposal_event"])
    proposal["event_id"] = "proposal-d2-235"
    registry_state = registered_state(facts)
    budget_input, budget_output, _ = reserve_for_proposal(base, facts, registry_state, proposal)
    proposal["budget_inputs"] = [budget_input]
    permitted = permitted_budget_proposal(base, proposal, budget_output)
    reserved_registry = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]

    clean_event = dispatch_event(
        base, permitted, event_id="dispatch-d2-235", attempt_status="SENT",
        attempted_at=REGISTRY_CLOCK_INSTANT, clock_revision=REGISTRY_CLOCK_REVISION,
    )
    dispatched = dispatch_result(
        permitted, clean_event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED",
    )
    _, expired = deadline_expiry(
        base, dispatched["state"], available_clock("work-clock", "2", "2026-09-10T04:31:00Z"), "clock-d2-235"
    )
    closed = {**dispatched, "state": expired["state"], "state_digest": expired["state_digest"]}

    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-235",
        status="EFFECT_ESTABLISHED", observed_at=REGISTRY_CLOCK_INSTANT,
    )
    record = matching_native_record(facts, evidence, reservation_id)
    reservation_row = next(row for row in reserved_registry["core"]["reservations"] if row["id"] == reservation_id)
    blocked_partitions = [
        {"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_row["contributions"]
    ]
    budget_input, budget_output = uncorroborated_settle(
        facts, reserved_registry, reservation_id, "effect-d2-235", record, blocked_partitions
    )
    event = governed_effect_event(
        permitted, closed, evidence, event_id="effect-d2-235",
        budget_inputs=[budget_input], clock_revision=REGISTRY_CLOCK_REVISION,
    )
    receipt_digest = budget_output["result"]["receipt_digest"]
    outcome = governed_outcome(
        event, closed, classification="LATE_MATCHED", disputed=True,
        reservation_receipt_digests=[receipt_digest],
    )

    def mutate(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    reason_codes = sorted(
        {"BUDGET_EFFECT_DISPUTED", "HISTORY_UNCORROBORATED", "LATE_EFFECT"},
        key=lambda value: value.encode("utf-8"),
    )
    expected = admitted_transition(
        closed["state"], event, disposition="DISPUTED", reason_codes=reason_codes,
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output["registry_digest"], "receipt_digest": receipt_digest, "reasons": ["HISTORY_UNCORROBORATED"]},
            {"kind": "EFFECT", "classification": "LATE_MATCHED", "evidence_id": evidence["evidence_id"]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], budget_results=[budget_output], mutate=mutate,
    )
    write_canonical_json(
        GROUP / "D2-235.json",
        exact_case(
            "D2-235", "step", step_input(base, closed["state"], event), expected, [],
            "The due clock committed first: LIFE-014's AT_OR_AFTER predicate is satisfied at equality, the occurrence closed as EXPIRED and the declared expiry route reached terminal. LIFE-012 then fixes the classification of the later evidence: a matching effect that arrives after deadline closure is LATE_MATCHED, and it cannot create a new permission, erase the earlier closure or reopen completed routing. The dispatch matched the permit and was eligible, so the embedded settlement carries completion_mismatch false and copies the reservation's exact retained request. RES-WIRE-003 requires all prescribed committed event records in every supplied current journal before a settlement can be claimed; the supplied history is the registry's original opening journal, which never recorded this effect's prescribed event, so corroboration fails and RES-WIRE-004 assigns the reason HISTORY_UNCORROBORATED. LIFE-006's decision-reason mapping is exhaustive: the LATE_MATCHED row contributes LATE_EFFECT, and the budget-disputed row adds BUDGET_EFFECT_DISPUTED and every reservation receipt reason to that classification-specific reason. LIFE-010's budget-disputed row leaves a closed occurrence and its route unchanged. The reservation becomes DISPUTED with its original contribution partition blocked; no route, completion or release occurs.",
        ),
    )


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    matched_history_uncorroborated_case()
    late_matched_uncorroborated_case()
    print(json.dumps({"case_ids": ["D2-230", "D2-235"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
