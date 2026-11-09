#!/usr/bin/env python3
"""Build budget-backed permit renewal vectors from LIFE-007, LIFE-008, LIFE-019 and RES-006.

The renewal forms differ from the initial-proposal forms in three ways the shared
fixtures do not cover: the proposal record carries the prior permit digest rather than
null, a renewal increments neither the activation nor the actuation counter, and the
embedded reservation event kind is RENEW rather than RESERVE. These constructors are
local rather than added to the shared fixtures so that existing case bytes are unchanged.
"""

from __future__ import annotations

import copy
import json

from authority_fixture import authority_refusal, revocation_check
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock
from lifecycle_factory import admitted_transition, proposal_permit, step_input
from lifecycle_budget_fixture import initial_budget_success
from reservation_fixture import (
    budget_result,
    clock as reservation_clock,
    host_and_event,
    request as reservation_request,
    transition as reservation_transition,
)


GROUP = CASES / "permit-renewal-budget"
RENEWAL_INSTANT = "2026-09-10T04:35:00Z"
RENEWAL_CLOCK_REVISION = "2"
RENEWAL_EXPIRY = "2026-09-10T04:40:00Z"


def advance_clock(base: dict, permitted: dict, *, event_id: str) -> dict:
    """Record an available clock at the prior permit's exclusive expiry."""
    selected = available_clock("authority-clock", RENEWAL_CLOCK_REVISION, RENEWAL_INSTANT)
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "CLOCK",
        "instance_id": permitted["state"]["instance_id"],
        "expected_state_revision": permitted["state"]["revision"],
        "expected_state_digest": permitted["state_digest"],
        "clock": selected,
        "activation_clocks": [],
    }

    def mutate(state: dict) -> None:
        state["clocks"].append(copy.deepcopy(selected))
        state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    result = admitted_transition(
        permitted["state"],
        event,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[{"kind": "CLOCK", "source": selected["source"], "revision": selected["revision"], "status": selected["status"]}],
        mutate=mutate,
    )
    return {"state": result["state"], "state_digest": result["state_digest"], "permit": copy.deepcopy(permitted["permit"])}


def current_authority(base: dict, instant: str, *, clock_status: str = "AVAILABLE", revoke: bool = False) -> tuple[dict, dict]:
    """Rebind the authority input and result to the current instant."""
    authority_input = copy.deepcopy(base["authority_input"])
    prior_instant = authority_input["clock"]["instant"]
    authority_input["clock"]["status"] = clock_status
    if clock_status == "AVAILABLE":
        authority_input["clock"]["instant"] = instant
    else:
        authority_input["clock"]["instant"] = None
    replacements = {}
    for observation in authority_input["observations"]:
        if observation["query"]["at"] != prior_instant:
            continue
        prior_digest = observation["query_digest"]
        observation["query"]["at"] = instant
        observation["as_of"] = instant
        observation["query_digest"] = digest("authority-query", observation["query"])
        if revoke:
            observation["revoked"] = True
        replacements[prior_digest] = observation["query_digest"]
    authority_result = copy.deepcopy(base["authority_result"])
    for check in authority_result["checks"]:
        if check["at"] == prior_instant:
            check["at"] = instant
        if check["requirement_ref"] in replacements:
            check["requirement_ref"] = replacements[check["requirement_ref"]]
    authority_result["checks"].sort(key=canonical_bytes)
    authority_result["evidence_digest"] = digest(
        "authority-evidence",
        {
            key: authority_input[key]
            for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock"]
        },
    )
    return authority_input, authority_result


def revoked_refusal(authority_input: dict) -> dict:
    """AUTHORITY-CHECKS: one REVOCATION failed check per revoked current query."""
    return authority_refusal([
        revocation_check(authority_input, row["query"]["subject_digest"], row["query"]["at"])
        for row in authority_input["observations"] if row["revoked"]
    ])


def renewal_history(facts: dict, interim_amount: str | None = None) -> dict:
    """RES-006 requires complete current histories for a renewal.

    RES-004 fixes the revision to the number of journal entries and requires the prior
    journal to remain an exact prefix, so only as_of advances. RESERVATION-RECORDS
    forbids as_of exceeding the current event clock, so it equals the renewal instant.
    """
    history = copy.deepcopy(facts["history"])
    history["as_of"] = RENEWAL_INSTANT
    if interim_amount is not None:
        # RES-004 keeps the prior journal an exact prefix and ties the natural revision
        # to the journal length, so committed exposure grows by appending one entry.
        history["journal"].append({
            "sequence": str(len(history["journal"]) + 1),
            "event": {
                "id": f"interim-{interim_amount}",
                "state": "ACTIVE",
                "occurred_at": "2026-09-10T04:33:00Z",
                "fields": [
                    {"name": "amount", "value": {"type_ref": "amount", "value": interim_amount}},
                    {"name": "beneficiary", "value": {"type_ref": "beneficiary", "value": "employee-7"}},
                ],
            },
        })
        history["revision"] = str(len(history["journal"]))
    assert history["revision"] == str(len(history["journal"])), "RES-004 revision must equal journal length"
    return history


def renew_for_proposal(
    base: dict,
    facts: dict,
    registry_state: dict,
    proposal: dict,
    *,
    decision: str = "RENEWED",
    total: str = "950",
    authority_result: dict | None = None,
    interim_amount: str | None = None,
) -> tuple[dict, dict]:
    """Embed one RENEW reservation event, preserving the existing reservation row."""
    registry_digest = digest("reservation-registry", registry_state["core"]["configuration"])
    reservation_event_id = digest(
        "lifecycle-reservation-event",
        {
            "instance_id": proposal["instance_id"],
            "lifecycle_event_id": proposal["event_id"],
            "lifecycle_event_kind": "PROPOSE",
            "reservation_event_kind": "RENEW",
            "registry_digest": registry_digest,
        },
    )
    # RES-006 and renewPayload: RENEW names the existing reservation and keeps its
    # id, occurrence and contributions unchanged.
    core = copy.deepcopy(registry_state["core"])
    existing = core["reservations"][0]["id"] if core["reservations"] else None
    event, host = host_and_event(
        facts,
        "RENEW",
        reservation_event_id,
        registry_state["core"]["revision"],
        {
            "reservation": existing,
            "authority": proposal["authority_input"],
            "histories": [renewal_history(facts, interim_amount)],
        },
        # LIFE-007: the embedded event clock is the exact accepted lifecycle clock
        # selected by clock_revision and used by the authority input.
        event_clock=reservation_clock(RENEWAL_INSTANT),
        administration=False,
    )
    violated = decision == "WITHHELD"
    # RES-003 commits affected budget histories with the decision, including a withheld one.
    history = renewal_history(facts, interim_amount)
    for budget in core["budgets"]:
        budget["history"] = copy.deepcopy(history)
    if not violated:
        # RES-006: replace current authority evidence and permit expiry, keeping id,
        # occurrence and contributions unchanged.
        for reservation in core["reservations"]:
            if reservation["id"] != existing:
                continue
            reservation["authority"] = copy.deepcopy(proposal["authority_input"])
            if authority_result is not None:
                reservation["authority_result"] = copy.deepcopy(authority_result)
            reservation["permit_until"] = RENEWAL_EXPIRY
    result = reservation_transition(
        registry_state,
        event,
        host,
        core,
        decision,
        reservation_id=existing,
        budgets=budget_result(facts, total, "VIOLATED" if violated else "SATISFIED"),
        authority_result=authority_result if authority_result is not None else base["authority_result"],
        reasons=["BOUND_VIOLATED"] if violated else [],
    )
    budget_input = {
        "registry_digest": registry_digest,
        "affected_anchors": ["license-spend"],
        "expected_revision": registry_state["core"]["revision"],
        "request": reservation_request(registry_state, event, host),
    }
    budget_output = {
        "registry_digest": registry_digest,
        "affected_anchors": ["license-spend"],
        "result": result,
    }
    return budget_input, budget_output


def renewal_event(
    base: dict,
    current: dict,
    case_id: str,
    *,
    clock_status: str = "AVAILABLE",
    revoke: bool = False,
) -> tuple[dict, dict, dict]:
    event = copy.deepcopy(base["proposal_event"])
    event["event_id"] = "renewal-" + case_id.lower()
    event["expected_state_revision"] = current["state"]["revision"]
    event["expected_state_digest"] = current["state_digest"]
    authority_input, authority_result = current_authority(
        base, RENEWAL_INSTANT, clock_status=clock_status, revoke=revoke
    )
    # LIFE-007: a null lifecycle clock revision is representable only on an
    # authority-withheld proposal whose selected clock is unavailable.
    event["clock_revision"] = None if clock_status != "AVAILABLE" else RENEWAL_CLOCK_REVISION
    event["authority_input"] = authority_input
    event["observation_digests"] = sorted(
        (digest("authority-observation", row) for row in authority_input["observations"]),
        key=lambda value: value.encode("utf-8"),
    )
    return event, authority_input, authority_result


def renewal_permit(base: dict, proposal: dict, budget_output: dict, prior_permit: dict, authority_result: dict) -> dict:
    renewal_base = {**copy.deepcopy(base), "authority_result": copy.deepcopy(authority_result)}
    permit = proposal_permit(renewal_base, proposal)
    result = budget_output["result"]
    without_id = {key: copy.deepcopy(value) for key, value in permit.items() if key != "permit_id"}
    without_id["budget_revisions"] = [
        {
            "registry_digest": budget_output["registry_digest"],
            "affected_anchors": copy.deepcopy(budget_output["affected_anchors"]),
            "revision": result["state"]["core"]["revision"],
            "reservation_id": result["receipt"]["reservation"],
            "receipt_digest": result["receipt_digest"],
        }
    ]
    without_id["supersedes_permit_digest"] = prior_permit["permit_id"]
    without_id["expires_at"] = RENEWAL_EXPIRY
    return {"permit_id": digest("permit", without_id), **without_id}


def permitted_renewal(base: dict, current: dict, proposal: dict, budget_output: dict, prior_permit: dict, authority_result: dict) -> dict:
    permit = renewal_permit(base, proposal, budget_output, prior_permit, authority_result)
    result = budget_output["result"]
    event_digest = digest("runtime-event", proposal)
    proposal_digest = digest("proposal", proposal)

    def mutate(state: dict) -> None:
        # LIFE-007 and LIFE-019: a renewal increments neither counter.
        state["proposals"].append(
            {
                "event_id": proposal["event_id"],
                "event_digest": event_digest,
                "proposal_digest": proposal_digest,
                "occurrence_id": proposal["occurrence"]["occurrence_id"],
                "disposition": "PERMITTED",
                "permit_digest": permit["permit_id"],
                "authority_result_digest": permit["authority_result_digest"],
                "reservation_receipt_digests": [result["receipt_digest"]],
                "prior_permit_digest": prior_permit["permit_id"],
            }
        )
        state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
        state["permits"].append(copy.deepcopy(permit))
        state["permits"].sort(key=lambda row: row["permit_id"].encode("utf-8"))

    return admitted_transition(
        current["state"],
        proposal,
        disposition="PERMITTED",
        reason_codes=[],
        details=[],
        permit=permit,
        budget_results=[budget_output],
        mutate=mutate,
    )


def authority_withheld_renewal(current: dict, event: dict, refusal: dict, prior_permit: dict) -> dict:
    """LIFE-007: empty reservation-receipt array, null permit, prior permit digest, registry unchanged."""
    event_digest = digest("runtime-event", event)
    proposal_digest = digest("proposal", event)
    authority_result_digest = digest("authority-result", refusal)
    reason_codes = sorted(
        set(["AUTHORITY_REQUIRED", refusal["code"], *refusal["reasons"]]),
        key=lambda value: value.encode("utf-8"),
    )

    def mutate(state: dict) -> None:
        state["proposals"].append(
            {
                "event_id": event["event_id"],
                "event_digest": event_digest,
                "proposal_digest": proposal_digest,
                "occurrence_id": event["occurrence"]["occurrence_id"],
                "disposition": "WITHHELD",
                "permit_digest": None,
                "authority_result_digest": authority_result_digest,
                "reservation_receipt_digests": [],
                "prior_permit_digest": prior_permit["permit_id"],
            }
        )
        state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))

    return admitted_transition(
        current["state"],
        event,
        disposition="WITHHELD",
        reason_codes=reason_codes,
        details=[
            {
                "kind": "AUTHORITY",
                "authority_result_digest": authority_result_digest,
                "code": refusal["code"],
                "reasons": copy.deepcopy(refusal["reasons"]),
                "failed_checks": copy.deepcopy(refusal["failed_checks"]),
            }
        ],
        receipt_authority_result_digest=authority_result_digest,
        mutate=mutate,
    )


def budget_withheld_renewal(current: dict, proposal: dict, budget_output: dict, prior_permit: dict, authority_result: dict) -> dict:
    """LIFE-007: successful authority digest, one receipt digest, prior permit digest, no new reservation."""
    result = budget_output["result"]
    event_digest = digest("runtime-event", proposal)
    proposal_digest = digest("proposal", proposal)
    authority_result_digest = digest("authority-result", authority_result)
    reasons = sorted(
        set(["BUDGET_WITHHELD", *result["receipt"]["reasons"]]),
        key=lambda value: value.encode("utf-8"),
    )

    def mutate(state: dict) -> None:
        state["proposals"].append(
            {
                "event_id": proposal["event_id"],
                "event_digest": event_digest,
                "proposal_digest": proposal_digest,
                "occurrence_id": proposal["occurrence"]["occurrence_id"],
                "disposition": "WITHHELD",
                "permit_digest": None,
                "authority_result_digest": authority_result_digest,
                "reservation_receipt_digests": [result["receipt_digest"]],
                "prior_permit_digest": prior_permit["permit_id"],
            }
        )
        state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))

    return admitted_transition(
        current["state"],
        proposal,
        disposition="WITHHELD",
        reason_codes=reasons,
        details=[
            {
                "kind": "BUDGET",
                "registry_digest": budget_output["registry_digest"],
                "receipt_digest": result["receipt_digest"],
                "reasons": copy.deepcopy(result["receipt"]["reasons"]),
            }
        ],
        receipt_authority_result_digest=authority_result_digest,
        budget_results=[budget_output],
        mutate=mutate,
    )


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def setup(instance_id: str, case_id: str):
    """Initial budget-backed permit, then a retained clock at its exclusive expiry."""
    base, facts, proposal, permitted = initial_budget_success(
        instance_id=instance_id, event_id=f"proposal-{case_id.lower()}"
    )
    current = advance_clock(base, permitted, event_id=f"clock-before-{case_id.lower()}")
    registry_after = permitted["budget_results"][0]["result"]["state"]
    return base, facts, permitted["permit"], current, registry_after


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    produced = []

    # D2-173 -- successful budget-backed renewal.
    base, facts, prior_permit, current, registry = setup("case-d2-173", "D2-173")
    event, _, authority_result = renewal_event(base, current, "D2-173")
    budget_input, budget_output = renew_for_proposal(base, facts, registry, event, authority_result=authority_result)
    event["budget_inputs"] = [budget_input]
    expected = permitted_renewal(base, current, event, budget_output, prior_permit, authority_result)
    emit(
        "D2-173", base, current["state"], event, expected,
        "LIFE-007 classifies this as a renewal because the occurrence is PERMITTED with the latest permit, the native request is unchanged and no dispatch consumed it. The latest retained available clock is at the prior permit's exclusive expiry, so eligibility holds. Current authority succeeds and RES-006 removes only this reservation's own unsettled contribution before evaluating the same contribution once, so the registry returns RENEWED. LIFE-008 records the superseded permit, and LIFE-019 leaves both counters unchanged because a renewal is not an initial proposal becoming PERMITTED.",
    )
    produced.append("D2-173")

    # D2-174 -- current authority revoked at renewal.
    base, facts, prior_permit, current, registry = setup("case-d2-174", "D2-174")
    event, _, _ = renewal_event(base, current, "D2-174", revoke=True)
    refusal = revoked_refusal(event["authority_input"])
    budget_input, _ = renew_for_proposal(base, facts, registry, event)
    event["budget_inputs"] = [budget_input]
    expected = authority_withheld_renewal(current, event, refusal, prior_permit)
    emit(
        "D2-174", base, current["state"], event, expected,
        "Renewal eligibility holds, so evaluation reaches current authority. AUTH-005 requires current revocation checks for every selected act, and a revoked observation cannot establish permission, so the evaluator returns AUTHORITY_NOT_ESTABLISHED with sole reason REVOKED. LIFE-007 maps that to an admitted policy withholding whose sorted reason codes are the union of AUTHORITY_REQUIRED, the refusal code and every refusal reason. The authority withholding records an empty reservation-receipt array, a null permit digest and the prior permit digest, and the reservation transition is never reached, so the registry is unchanged and the prior permit is not superseded.",
    )
    produced.append("D2-174")

    # D2-208 -- retained expiry established, current authority clock unavailable.
    base, facts, prior_permit, current, registry = setup("case-d2-208", "D2-208")
    from timing_fixture import clock_event, clock_result
    outage_event = clock_event(current["state"], "3", status="UNAVAILABLE", event_id="outage-before-d2-208")
    outage = clock_result(current["state"], outage_event)
    current.update(state=outage["state"], state_digest=outage["state_digest"])
    event, _, _ = renewal_event(base, current, "D2-208", clock_status="UNAVAILABLE")
    refusal = authority_refusal([], reasons=["CLOCK_UNAVAILABLE"])
    budget_input, _ = renew_for_proposal(base, facts, registry, event)
    event["budget_inputs"] = [budget_input]
    expected = authority_withheld_renewal(current, event, refusal, prior_permit)
    emit(
        "D2-208", base, current["state"], event, expected,
        "LIFE-007 separates the two clocks. Renewal eligibility uses the latest retained available lifecycle clock for the permit source, which is at the prior permit's exclusive expiry, so the result is not PREREQUISITE_MISSING. TIME-006 requires the submitted unavailable status to be consistent with retained time. An explicit later UNAVAILABLE lifecycle clock is retained after the available sample established renewal eligibility, so the new unavailable authority input produces ordinary admitted withholding without contradicting the latest sample. AUTH-005 cannot establish permission without a current clock. The lifecycle clock revision is null, which LIFE-007 permits only on an authority-withheld proposal whose selected clock is unavailable. The prior permit and reservation remain unextended and unsuperseded.",
    )
    produced.append("D2-208")

    # D2-215 -- authority succeeds, budget bound violated.
    base, facts, prior_permit, current, registry = setup("case-d2-215", "D2-215")
    event, _, authority_result = renewal_event(base, current, "D2-215")
    budget_input, budget_output = renew_for_proposal(
        base, facts, registry, event, decision="WITHHELD", total="1050",
        authority_result=authority_result, interim_amount="100"
    )
    event["budget_inputs"] = [budget_input]
    expected = budget_withheld_renewal(current, event, budget_output, prior_permit, authority_result)
    emit(
        "D2-215", base, current["state"], event, expected,
        "Renewal eligibility holds and current authority succeeds, so evaluation reaches the single reservation transition. RES-006 tests the same contribution against the current committed window plus all still-unsettled exposure and the bound is violated, so the registry returns WITHHELD with reason BOUND_VIOLATED. LIFE-007 commits the registry withholding receipt and next revision together with one WITHHELD proposal record carrying the successful authority-result digest, the one receipt digest, a null permit digest and the exact prior-permit digest. Its lifecycle reason codes are the sorted union of the receipt reasons and BUDGET_WITHHELD. No new or extended reservation is created and the prior permit is not superseded.",
    )
    produced.append("D2-215")

    # D2-189 -- successful renewal after an earlier withheld proposal.
    base, facts, prior_permit, current, registry = setup("case-d2-189", "D2-189")
    withheld_event, _, _ = renewal_event(base, current, "D2-189-withheld", revoke=True)
    withheld_refusal = revoked_refusal(withheld_event["authority_input"])
    withheld_input, _ = renew_for_proposal(base, facts, registry, withheld_event)
    withheld_event["budget_inputs"] = [withheld_input]
    after_withheld = authority_withheld_renewal(current, withheld_event, withheld_refusal, prior_permit)
    carried = {"state": after_withheld["state"], "state_digest": after_withheld["state_digest"]}

    event, _, authority_result = renewal_event(base, carried, "D2-189")
    budget_input, budget_output = renew_for_proposal(base, facts, registry, event, authority_result=authority_result)
    event["budget_inputs"] = [budget_input]
    expected = permitted_renewal(base, carried, event, budget_output, prior_permit, authority_result)
    emit(
        "D2-189", base, carried["state"], event, expected,
        "An earlier renewal was withheld and appended one proposal record with disposition WITHHELD under LIFE-007, leaving the prior permit unsuperseded. The current renewal is eligible and every check succeeds, so it appends one PERMITTED proposal record and creates one permit. LIFE-019 states that a permit renewal increments neither the activation nor the actuation counter and that actuations increment only when an occurrence's initial proposal becomes PERMITTED, so per-step and total counters are unchanged and consumption against maximum_actuations does not move. The decision receipt sequence advances by one because every admitted transition appends exactly one receipt.",
    )
    produced.append("D2-189")

    print(json.dumps({"case_ids": produced, "count": len(produced), "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
