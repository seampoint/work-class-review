#!/usr/bin/env python3
"""Build exact proposal and actuation ceiling vectors."""

from __future__ import annotations

import copy
import json

from authority_fixture import authority_refusal, authority_specimen, envelope_validity_check
from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_budget_fixture import budget_lifecycle, reserve_for_proposal
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    effect_result,
    governed_effect_event,
    governed_native_evidence,
    permitted_proposal,
    stateful_refusal,
    step_input,
    withheld_proposal,
)
from reservation_fixture import registered_state


GROUP = CASES / "proposal-limits"


def set_limit(name: str, value: str):
    def mutate(definition: dict) -> None:
        definition["limits"][name] = value
    return mutate


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def stop_on_actuation(base: dict, event: dict) -> dict:
    authority_digest = digest("authority-result", base["authority_result"])

    def mutate(state: dict) -> None:
        state["status"] = "STOPPED"

    return admitted_transition(
        base["clock_result"]["state"],
        event,
        disposition="STOPPED",
        reason_codes=["LIMIT_EXCEEDED"],
        details=[
            {
                "kind": "LIMIT",
                "limit_kind": "ACTUATIONS",
                "limit": "0",
                "current": "1",
                "step_id": event["occurrence"]["step_id"],
                "relationship_digest": None,
            }
        ],
        receipt_authority_result_digest=authority_digest,
        mutate=mutate,
    )


def expired_authority_event(base: dict, *, event_id: str) -> tuple[dict, dict]:
    occurrence = base["clock_result"]["state"]["active"][0]["occurrence"]

    def expire(request: dict, _original: dict) -> None:
        request["envelope"]["temporal_validity"]["valid_until"] = "2026-09-10T04:30:00Z"

    authority_input, _ = authority_specimen(
        shared_budget=False,
        instance_id=base["clock_result"]["state"]["instance_id"],
        occurrence_id=occurrence["occurrence_id"],
        mutator=expire,
    )
    event = copy.deepcopy(base["proposal_event"])
    event["event_id"] = event_id
    event["authority_input"] = authority_input
    event["observation_digests"] = sorted(
        (digest("authority-observation", row) for row in authority_input["observations"]),
        key=lambda value: value.encode("utf-8"),
    )
    refusal = authority_refusal([envelope_validity_check(authority_input)])
    return event, refusal


def main() -> None:
    base = base_lifecycle(definition_mutator=set_limit("maximum_actuations", "0"))
    event = copy.deepcopy(base["proposal_event"])
    event["event_id"] = "proposal-actuation-limit"
    emit(
        "D2-095",
        base,
        base["clock_result"]["state"],
        event,
        stop_on_actuation(base, event),
        "Current authority is READY_FOR_RESERVATION, but the initial permit would raise total actuations from zero to one against maximum_actuations zero. Proposal preflight records STOPPED with the retained authority-result digest and ACTUATIONS limit detail; it creates no proposal record, permit or reservation.",
    )

    max_one = base_lifecycle(definition_mutator=set_limit("maximum_proposals", "1"))
    event = copy.deepcopy(max_one["proposal_event"])
    event["event_id"] = "proposal-at-ceiling"
    permitted = permitted_proposal(max_one, event)
    emit(
        "D2-123",
        max_one,
        max_one["clock_result"]["state"],
        event,
        permitted,
        "No retained PROPOSE receipt exists before this event. Its admitted PERMITTED decision raises the retained PROPOSE count from zero to the declared maximum one, which is allowed, and creates the ordinary authority-only permit.",
    )

    dispatch = dispatch_event(max_one, permitted, event_id="dispatch-after-proposal-ceiling", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(max_one, permitted, dispatched, evidence_id="evidence-d2-131")
    effect_event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-d2-131")
    completed = effect_result(
        max_one,
        permitted,
        dispatched,
        effect_event,
        classification="MATCHED",
        disposition="COMPLETED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=True,
    )
    emit(
        "D2-131",
        max_one,
        dispatched["state"],
        effect_event,
        completed,
        "The retained proposal count already equals maximum_proposals, but this event is EFFECT_OBSERVED. The proposal ceiling cannot strand existing work. The exact first matching effect remains admissible, completes the occurrence, follows its sequence edge and completes the instance.",
    )

    withholding_base = base_lifecycle(definition_mutator=set_limit("maximum_proposals", "1"))
    first_event, first_refusal = expired_authority_event(withholding_base, event_id="proposal-first-withheld")
    first_withheld = withheld_proposal(withholding_base, first_event, first_refusal)
    second = copy.deepcopy(withholding_base["proposal_event"])
    second["event_id"] = "proposal-after-ceiling"
    second["expected_state_revision"] = first_withheld["state"]["revision"]
    second["expected_state_digest"] = first_withheld["state_digest"]
    emit(
        "D2-124",
        withholding_base,
        first_withheld["state"],
        second,
        stateful_refusal(first_withheld["state"], "LIMIT_EXCEEDED"),
        "The first authority withholding is an admitted PROPOSE decision, so the retained proposal count equals maximum_proposals one while the occurrence remains ACTIVE. This new, otherwise bound proposal is not a replay. The ceiling returns LIMIT_EXCEEDED before current authority and leaves state unchanged.",
    )

    invalid_second, _ = expired_authority_event(withholding_base, event_id="proposal-invalid-after-ceiling")
    invalid_second["expected_state_revision"] = first_withheld["state"]["revision"]
    invalid_second["expected_state_digest"] = first_withheld["state_digest"]
    emit(
        "D2-176",
        withholding_base,
        first_withheld["state"],
        invalid_second,
        stateful_refusal(first_withheld["state"], "LIMIT_EXCEEDED"),
        "The prior withholding has filled the one-proposal ceiling. Although this new authority input would independently be withheld for envelope expiry, LIFE-006 evaluates the retained proposal count first and returns admission refusal LIMIT_EXCEEDED without another receipt.",
    )

    budget_base, budget_facts = budget_lifecycle(definition_mutator=set_limit("maximum_actuations", "0"))
    registry_state = registered_state(budget_facts)
    budget_event = copy.deepcopy(budget_base["proposal_event"])
    budget_event["event_id"] = "proposal-actuation-before-stale-budget"
    budget_input, _budget_output, _reservation = reserve_for_proposal(
        budget_base,
        budget_facts,
        registry_state,
        budget_event,
    )
    budget_input["expected_revision"] = "0"
    budget_input["request"]["event"]["expected_revision"] = "0"
    budget_event["budget_inputs"] = [budget_input]
    expected = stop_on_actuation(budget_base, budget_event)
    emit(
        "D2-267",
        budget_base,
        budget_base["clock_result"]["state"],
        budget_event,
        expected,
        "The required registry request is closed and digest-bound but selects expected revision zero while its supplied state is revision one. Current authority nevertheless succeeds, and the initial actuation ceiling is checked before cloning or evaluating that registry transition. The work instance records the stop and the supplied registry remains unchanged.",
    )

    print(json.dumps({"case_ids": ["D2-095", "D2-123", "D2-124", "D2-131", "D2-176", "D2-267"]}, indent=2))


if __name__ == "__main__":
    main()
