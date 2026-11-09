#!/usr/bin/env python3
"""Build budget-backed disputed-effect vectors from LIFE-010, LIFE-011, RES-008 and RES-WIRE-003.

`lifecycle_factory.effect_result` was written for authority-only effects and does not pass
`budget_results` to `admitted_transition`, so it cannot express a budget-backed effect.
`budget_effect_result` below mirrors its mutate logic and adds the budget row. It is local
to this batch so existing case bytes are unchanged.
"""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from lifecycle_factory import (
    canonical_occurrence_key,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    governed_outcome,
    admitted_transition,
    no_effect_completion_authorization,
    step_input,
)
from lifecycle_budget_fixture import (
    budget_lifecycle,
    initial_budget_success,
    permitted_budget_proposal,
    reserve_for_proposal,
)
from reservation_fixture import (
    effect_record,
    host_and_event,
    native as native_record,
    registered_state,
    request as reservation_request,
    transition as reservation_transition,
)


GROUP = CASES / "budget-effect-disputes"
REGISTRY_CLOCK_REVISION = "1"
REGISTRY_CLOCK_INSTANT = "2026-09-10T04:30:00Z"


def changed_request(permitted: dict) -> dict:
    """A native request that differs from the committed permit."""
    native = copy.deepcopy(permitted["permit"]["native_request"])
    next(row for row in native["fields"] if row["name"] == "card_id")["value"]["value"] = "card-999"
    return native


def reservation_event_kind_for(status: str) -> str:
    """LIFE-010: EFFECT_ESTABLISHED and OUTCOME_UNKNOWN map to SETTLE, NO_EFFECT to RELEASE."""
    return "RELEASE" if status == "NO_EFFECT_ESTABLISHED" else "SETTLE"


def native_outcome_for(status: str) -> str:
    return {"EFFECT_ESTABLISHED": "EFFECT", "OUTCOME_UNKNOWN": "UNKNOWN", "NO_EFFECT_ESTABLISHED": "NO_EFFECT"}[status]


def embedded_native_record(
    facts: dict,
    reservation_id: str,
    evidence: dict,
    *,
    outcome: str,
    completion_mismatch: bool,
    mismatch_reason: str | None,
) -> dict:
    """LIFE-010 constructs the embedded reservation native record exactly.

    `id`, `provider`, `source`, `evidence_ref`, `actual_fields` and `collections` copy the
    native evidence; `request` is the original permitted and reserved request projection;
    `observed_request` is null for `OUTCOME_UNKNOWN` and `NO_EFFECT_ESTABLISHED`; `effect_id`
    and `occurred_at` are set only for `EFFECT`.
    """
    record = native_record(
        facts,
        outcome,
        evidence["evidence_id"],
        reservation_id=reservation_id,
        completion_mismatch=completion_mismatch,
        mismatch_reason=mismatch_reason,
    )
    record["provider"] = evidence["provider"]
    record["source"] = evidence["source"]
    record["evidence_ref"] = evidence["evidence_ref"]
    record["actual_fields"] = copy.deepcopy(evidence["actual_fields"])
    record["collections"] = copy.deepcopy(evidence["collections"])
    record["rules_out_past_and_future_effects"] = evidence["rules_out_past_and_future_effects"]
    if outcome == "EFFECT":
        record["effect_id"] = evidence["native_operation_id"]
        record["occurred_at"] = evidence["event_time"]
    else:
        record["effect_id"] = None
        record["occurred_at"] = None
        record["observed_request"] = None
    return record


def embed_reservation_event(
    facts: dict,
    registry_state: dict,
    reservation_id: str,
    effect_event_id: str,
    record: dict,
    *,
    kind: str,
    decision: str,
    reservation_status: str,
    effect_disposition: str,
    effect_reason: str,
    blocked: list[dict],
    reasons: list[str],
    administration: bool,
) -> tuple[dict, dict]:
    """Embed one reservation event for a governed effect and its expected transition."""
    registry_digest = digest("reservation-registry", registry_state["core"]["configuration"])
    reservation_event_id = digest(
        "lifecycle-reservation-event",
        {
            "instance_id": facts["authority_a"]["proposal"]["instance"],
            "lifecycle_event_id": effect_event_id,
            "lifecycle_event_kind": "EFFECT_OBSERVED",
            "reservation_event_kind": kind,
            "registry_digest": registry_digest,
        },
    )
    # releasePayload carries only the native record; settlePayload also carries histories.
    payload = {"native": record}
    if kind == "SETTLE":
        payload["histories"] = [facts["history"]]
    event, host = host_and_event(
        facts,
        kind,
        reservation_event_id,
        registry_state["core"]["revision"],
        payload,
        event_clock=facts["clock"],
        administration=administration,
    )
    core = copy.deepcopy(registry_state["core"])
    for reservation in core["reservations"]:
        if reservation["id"] == reservation_id:
            reservation["status"] = reservation_status
    core["effects"].append(effect_record(record, effect_disposition, effect_reason, blocked))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    result = reservation_transition(
        registry_state, event, host, core, decision,
        reservation_id=reservation_id,
        reasons=reasons,
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


def effect_budget_input(
    facts: dict,
    registry_state: dict,
    reservation_id: str,
    effect_event_id: str,
    *,
    evidence_status: str,
    completion_mismatch: bool,
    mismatch_reason: str | None,
    evidence: dict,
) -> tuple[dict, dict]:
    """A disputed embedded reservation event, with the exact mismatch flags."""
    record = embedded_native_record(
        facts, reservation_id, evidence,
        outcome=native_outcome_for(evidence_status),
        completion_mismatch=completion_mismatch,
        mismatch_reason=mismatch_reason,
    )
    reason = mismatch_reason or "UNEXPECTED_EFFECT"
    # RESERVATION-RECORDS: a disputed effect sets the reservation DISPUTED, appends the
    # effect record and copies the retained native reason into the receipt reasons. The
    # derivation requires the affected anchors to be blocked while exposure is disputed.
    return embed_reservation_event(
        facts, registry_state, reservation_id, effect_event_id, record,
        kind=reservation_event_kind_for(evidence_status),
        decision="EFFECT_DISPUTED",
        reservation_status="DISPUTED",
        effect_disposition="DISPUTED",
        effect_reason=reason,
        blocked=[{"anchor": anchor, "key": None} for anchor in ["license-spend"]],
        reasons=[reason],
        administration=False,
    )


def release_budget_input(
    facts: dict,
    registry_state: dict,
    reservation_id: str,
    effect_event_id: str,
    *,
    evidence: dict,
) -> tuple[dict, dict]:
    """A clean RELEASE for an authorized no-effect completion over a final safe attempt set.

    RES-008 permits release only when `completion_mismatch` is false and `mismatch_reason`
    null. The release is administered, so the event carries an administration basis.
    """
    record = embedded_native_record(
        facts, reservation_id, evidence,
        outcome="NO_EFFECT",
        completion_mismatch=False,
        mismatch_reason=None,
    )
    return embed_reservation_event(
        facts, registry_state, reservation_id, effect_event_id, record,
        kind="RELEASE",
        decision="RELEASED",
        reservation_status="RELEASED",
        effect_disposition="RELEASED",
        effect_reason="AFFIRMATIVE_NO_EFFECT",
        blocked=[],
        reasons=[],
        administration=True,
    )


def budget_effect_result(
    base: dict,
    dispatched: dict,
    event: dict,
    budget_output: dict,
    *,
    classification: str,
    disposition: str,
    reason_codes: list[str],
    occurrence_status: str | None,
    disputed: bool,
    conflicts: list[str] | None = None,
    complete_disposition: str | None = None,
    route: bool = False,
    route_relationship_kind: str = "FAILURE_EDGE",
) -> dict:
    """Mirror of lifecycle_factory.effect_result that carries the budget row."""
    # A budget-backed outcome records the reservation receipt that reconciled it.
    outcome = governed_outcome(
        event, dispatched, classification=classification, disputed=disputed, conflicts=conflicts,
        reservation_receipt_digests=[budget_output["result"]["receipt_digest"]],
    )
    relationship = None
    if route:
        relationship = next(
            row for row in base["definition"]["relationships"] if row["kind"] == route_relationship_kind
        )
    relationship_digest = digest("relationship", relationship) if relationship is not None else None

    def mutate(next_state: dict) -> None:
        # LIFE-010: a conflicting record marks every prior outcome it conflicts with as
        # disputed and records the new evidence identity on it, which recomputes its digest.
        if classification in {"CONFLICTING", "LATE_AFTER_RELEASE"}:
            for prior in next_state["outcomes"]:
                if prior["native_evidence"]["evidence_id"] not in (conflicts or []):
                    continue
                prior["disputed"] = True
                prior["conflicts_with_evidence_ids"] = sorted(
                    set(prior["conflicts_with_evidence_ids"]) | {event["native_evidence"]["evidence_id"]},
                    key=lambda value: value.encode("utf-8"),
                )
                prior["outcome_digest"] = digest(
                    "outcome", {key: value for key, value in prior.items() if key != "outcome_digest"}
                )
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active_index = next(
            (
                index
                for index, row in enumerate(next_state["active"])
                if row["occurrence"]["occurrence_id"] == event["permit"]["occurrence"]["occurrence_id"]
            ),
            None,
        )
        if complete_disposition is not None and active_index is not None:
            active = next_state["active"].pop(active_index)
            next_state["completed"].append(
                {
                    "occurrence": copy.deepcopy(active["occurrence"]),
                    "disposition": complete_disposition,
                    "evidence_digest": digest("native-evidence", event["native_evidence"]),
                    "occurred_at": event["native_evidence"]["event_time"] or event["native_evidence"]["observed_at"],
                    "route_label": None,
                    "selected_relationship_digest": relationship_digest,
                    "late": False,
                }
            )
            next_state["completed"].sort(key=lambda row: canonical_occurrence_key(row["occurrence"]))
            for deadline in next_state["deadlines"]:
                if deadline["occurrence_id"] == active["occurrence"]["occurrence_id"] and deadline["status"] == "PENDING":
                    deadline["status"] = "DISCHARGED"
            # Routing over the declared edge reaches the TERMINAL step, which completes the
            # instance. lifecycle_factory.effect_result does the same.
            if route:
                next_state["status"] = "COMPLETE"
        elif occurrence_status is not None and active_index is not None:
            next_state["active"][active_index]["status"] = occurrence_status

    result = budget_output["result"]
    details = [
        {
            "kind": "BUDGET",
            "reasons": copy.deepcopy(result["receipt"]["reasons"]),
            "receipt_digest": result["receipt_digest"],
            "registry_digest": budget_output["registry_digest"],
        },
        {"kind": "EFFECT", "classification": classification, "evidence_id": event["native_evidence"]["evidence_id"]},
    ]
    if route:
        details.append({"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []})

    return admitted_transition(
        dispatched["state"],
        event,
        disposition=disposition,
        reason_codes=reason_codes,
        details=details,
        receipt_permit_digest=event["permit"]["permit_id"],
        budget_results=[budget_output],
        mutate=mutate,
    )


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def changed_dispatch_case(
    case_id: str,
    *,
    evidence_status: str,
    classification: str,
    classification_reason: str,
    occurrence_status: str,
    derivation: str,
) -> None:
    """A budget-backed effect attributed to a dispatch request that differed from the permit."""
    lower = case_id.lower()
    base, facts, proposal, permitted = initial_budget_success(
        instance_id=f"case-{lower}", event_id=f"proposal-{lower}"
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    changed_event = dispatch_event(
        base,
        permitted,
        event_id=f"dispatch-{lower}",
        attempt_status="SENT",
        native_request=changed_request(permitted),
        attempted_at=REGISTRY_CLOCK_INSTANT,
        clock_revision=REGISTRY_CLOCK_REVISION,
    )
    changed = dispatch_result(
        permitted,
        changed_event,
        disposition="DISPUTED",
        reasons=["NATIVE_ARGUMENT_MISMATCH"],
        occurrence_status="BLOCKED_DISPUTE",
    )
    evidence = governed_native_evidence(
        base, permitted, changed, evidence_id=f"evidence-{lower}", status=evidence_status,
        observed_at=REGISTRY_CLOCK_INSTANT,
    )
    event_id = f"effect-{lower}"
    budget_input, budget_output = effect_budget_input(
        facts, registry_state, reservation_id, event_id,
        evidence_status=evidence_status,
        completion_mismatch=True,
        mismatch_reason="NATIVE_REQUEST_MISMATCH",
        evidence=evidence,
    )
    event = governed_effect_event(
        permitted, changed, evidence, event_id=event_id,
        budget_inputs=[budget_input], clock_revision=REGISTRY_CLOCK_REVISION,
    )
    reason_codes = sorted(
        {"BUDGET_EFFECT_DISPUTED", "NATIVE_REQUEST_MISMATCH", classification_reason},
        key=lambda value: value.encode("utf-8"),
    )
    expected = budget_effect_result(
        base, changed, event, budget_output,
        classification=classification,
        disposition="DISPUTED",
        reason_codes=reason_codes,
        occurrence_status=occurrence_status,
        disputed=True,
    )
    emit(case_id, base, changed["state"], event, expected, derivation)


def failure_edge(definition: dict) -> None:
    operation = next(row for row in definition["steps"] if row["kind"] == "OPERATION")
    operation["failure_behavior"] = "FAILURE_EDGE"
    definition["relationships"].append({"kind": "FAILURE", "from": operation["id"], "to": "terminal"})
    definition["relationships"].sort(key=canonical_bytes)


def budget_success_with_failure_edge(instance_id: str, event_id: str) -> tuple[dict, dict, dict, dict]:
    """initial_budget_success with a declared failure edge on the operation step."""
    base, facts = budget_lifecycle(instance_id=instance_id, definition_mutator=failure_edge)
    proposal = copy.deepcopy(base["proposal_event"])
    proposal["event_id"] = event_id
    registry_state = registered_state(facts)
    budget_input, budget_output, _ = reserve_for_proposal(base, facts, registry_state, proposal)
    proposal["budget_inputs"] = [budget_input]
    return base, facts, proposal, permitted_budget_proposal(base, proposal, budget_output)


def two_attempt_fixture(instance_id: str, event_id: str, *, first_status: str) -> tuple:
    """A budget-backed permit with two distinct dispatch attempts, recorded in order.

    The receipt sequence that first retained each stable dispatch_attempt_digest orders the
    set A then B, which is what the final-safe-attempt rule reads.
    """
    base, facts, proposal, permitted = budget_success_with_failure_edge(instance_id, event_id)
    refused = first_status == "NOT_SENT"
    event_a = dispatch_event(
        base, permitted, event_id="dispatch-attempt-a", attempt_status=first_status,
        attempted_at=REGISTRY_CLOCK_INSTANT, clock_revision=REGISTRY_CLOCK_REVISION,
    )
    a = dispatch_result(
        permitted, event_a,
        disposition="DISPATCH_REFUSED" if refused else "DISPATCH_RECORDED",
        reasons=["NATIVE_NOT_SENT"] if refused else [],
        occurrence_status="PERMITTED" if refused else "DISPATCHED",
    )
    after_a = {**permitted, "state": a["state"], "state_digest": a["state_digest"]}
    event_b = dispatch_event(
        base, after_a, event_id="dispatch-attempt-b", attempt_status="SENT",
        attempted_at=REGISTRY_CLOCK_INSTANT, clock_revision=REGISTRY_CLOCK_REVISION,
    )
    event_b["attempt"]["attempt_id"] = "attempt-2"
    b = dispatch_result(
        after_a, event_b, disposition="DISPATCH_RECORDED",
        reasons=[], occurrence_status="DISPATCHED",
    )
    digests = {
        "a": next(row["dispatch_digest"] for row in b["state"]["dispatches"] if row["event_id"] == event_a["event_id"]),
        "b": next(row["dispatch_digest"] for row in b["state"]["dispatches"] if row["event_id"] == event_b["event_id"]),
    }
    return base, facts, permitted, b, digests


def attempt_set_not_final_case() -> None:
    """D2-270: a valid authorization over an attempt that is eligible but not the last one.

    Both attempts are SENT so the bound attempt A carries no dispatch-disqualifying fact.
    That isolates the attempt-set rule: the only reason the assertion is not an authorized
    release is that A is not the last distinct attempt.
    """
    base, facts, permitted, dispatched, digests = two_attempt_fixture(
        "case-d2-270", "proposal-d2-270", first_status="NOT_SENT"
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-270",
        status="NO_EFFECT_ESTABLISHED", observed_at=REGISTRY_CLOCK_INSTANT,
        dispatch_digest=digests["a"],
    )
    # The request did not change and no dispatch-disqualifying fact applies to A, so the
    # mismatch comes only from the attempt set and its reason is UNEXPECTED_EFFECT.
    budget_input, budget_output = effect_budget_input(
        facts, registry_state, reservation_id, "effect-d2-270",
        evidence_status="NO_EFFECT_ESTABLISHED",
        completion_mismatch=True,
        mismatch_reason="UNEXPECTED_EFFECT",
        evidence=evidence,
    )
    event = governed_effect_event(
        permitted, dispatched, evidence, event_id="effect-d2-270",
        completion_authorization=no_effect_completion_authorization(
            base, permitted, dispatched, evidence, dispatch_digest=digests["a"]
        ),
        budget_inputs=[budget_input], clock_revision=REGISTRY_CLOCK_REVISION,
        dispatch_digest=digests["a"],
    )
    expected = budget_effect_result(
        base, dispatched, event, budget_output,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["BUDGET_EFFECT_DISPUTED", "UNEXPECTED_EFFECT"],
        occurrence_status="OUTCOME_UNKNOWN",
        disputed=True,
    )
    emit(
        "D2-270", base, dispatched["state"], event, expected,
        "Distinct attempts are ordered by the decision-receipt sequence that first retained each stable dispatch_attempt_digest, so the order is A then B. The assertion binds A, which is not the last value in that order, so the attempt set is not final and safe. Both attempts are SENT with the permitted request, so A carries no dispatch-disqualifying fact and the authorization is valid. LIFE-010 covers this case directly: an assertion whose authorization is valid but whose attempt set is not final and safe is retained as UNEXPECTED, and the authorization cannot close the occurrence or release exposure. completion_mismatch is true because a no-effect assertion lacks a final safe attempt set, and since no dispatch-disqualifying fact caused it the mismatch_reason is UNEXPECTED_EFFECT rather than NATIVE_REQUEST_MISMATCH. That reason collapses with the classification reason, which is why this judgment carries two reason codes where D2-242 carries three. LIFE-010 places UNEXPECTED in the disposition row above the budget-disputed row, so the occurrence stays OUTCOME_UNKNOWN. Attempt B remains possibly effective, the reservation becomes DISPUTED, pending exposure stays charged, and no completion, route or release occurs.",
    )


def final_safe_release_case() -> None:
    """D2-271: the last distinct attempt, with every earlier attempt NOT_SENT and unacknowledged."""
    base, facts, permitted, dispatched, digests = two_attempt_fixture(
        "case-d2-271", "proposal-d2-271", first_status="NOT_SENT"
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-271",
        status="NO_EFFECT_ESTABLISHED", observed_at=REGISTRY_CLOCK_INSTANT,
        dispatch_digest=digests["b"],
    )
    release_input, release_output = release_budget_input(
        facts, registry_state, reservation_id, "effect-d2-271", evidence=evidence,
    )
    event = governed_effect_event(
        permitted, dispatched, evidence, event_id="effect-d2-271",
        completion_authorization=no_effect_completion_authorization(
            base, permitted, dispatched, evidence, dispatch_digest=digests["b"]
        ),
        budget_inputs=[release_input], clock_revision=REGISTRY_CLOCK_REVISION,
        dispatch_digest=digests["b"],
    )
    expected = budget_effect_result(
        base, dispatched, event, release_output,
        classification="NO_EFFECT_ESTABLISHED",
        disposition="FAILED",
        reason_codes=["NO_EFFECT_ESTABLISHED"],
        occurrence_status=None,
        disputed=False,
        complete_disposition="NO_EFFECT",
        route=True,
        route_relationship_kind="FAILURE",
    )
    emit(
        "D2-271", base, dispatched["state"], event, expected,
        "B is the last distinct attempt in the receipt-sequence order, and the only other distinct attempt, A, has status NOT_SENT with no retained ACCEPTED acknowledgement. Both conditions of the final-safe-attempt-set rule hold. The LIFE-010 outcome table then gives the admitted row: NO_EFFECT_ESTABLISHED with exact affirmative evidence, completion authorization for the unresolved occurrence, and a final safe attempt set produces one RELEASE transition with native outcome NO_EFFECT, closes the unresolved occurrence as NO_EFFECT, and follows its failure behavior. completion_mismatch is false and mismatch_reason null, which RES-008 requires before capacity can be released, and the administered release act supplies the release administration. LIFE-011 fixes the work-side result: a step with FAILURE_EDGE records FAILED with reason NO_EFFECT_ESTABLISHED, completes the occurrence as NO_EFFECT, and follows that exact edge. Release does not make the operation successful.",
    )


def late_after_release_case() -> None:
    """D2-197: an established effect follows an authorized no-effect release for the same attempt."""
    base, facts, permitted, dispatched, digests = two_attempt_fixture(
        "case-d2-197", "proposal-d2-197", first_status="NOT_SENT"
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]

    # Setup, not the case: the authorized release that closes the occurrence as NO_EFFECT.
    no_effect = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-197-release",
        status="NO_EFFECT_ESTABLISHED", observed_at=REGISTRY_CLOCK_INSTANT, dispatch_digest=digests["b"],
    )
    release_input, release_output = release_budget_input(
        facts, registry_state, reservation_id, "effect-d2-197-release", evidence=no_effect,
    )
    release_event = governed_effect_event(
        permitted, dispatched, no_effect, event_id="effect-d2-197-release",
        completion_authorization=no_effect_completion_authorization(
            base, permitted, dispatched, no_effect, dispatch_digest=digests["b"]
        ),
        budget_inputs=[release_input], clock_revision=REGISTRY_CLOCK_REVISION, dispatch_digest=digests["b"],
    )
    released = budget_effect_result(
        base, dispatched, release_event, release_output,
        classification="NO_EFFECT_ESTABLISHED", disposition="FAILED",
        reason_codes=["NO_EFFECT_ESTABLISHED"], occurrence_status=None, disputed=False,
        complete_disposition="NO_EFFECT", route=True, route_relationship_kind="FAILURE",
    )
    after_release = {**dispatched, "state": released["state"], "state_digest": released["state_digest"]}
    released_registry = release_output["result"]["state"]

    # The case: a matching established effect for the same provider-native operation identity,
    # governed permit and stable dispatch attempt.
    effect = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-197", status="EFFECT_ESTABLISHED",
        observed_at=REGISTRY_CLOCK_INSTANT, native_operation_id=no_effect["native_operation_id"],
        dispatch_digest=digests["b"],
    )
    record = embedded_native_record(
        facts, reservation_id, effect, outcome="EFFECT", completion_mismatch=False, mismatch_reason=None,
    )
    # RES-WIRE-003: a projectable EFFECT blocks the reservation's own contribution key; the
    # release record itself blocked nothing, so no null-key entry subsumes it.
    reservation_row = next(row for row in released_registry["core"]["reservations"] if row["id"] == reservation_id)
    blocked = [{"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_row["contributions"]]
    budget_input, budget_output = embed_reservation_event(
        facts, released_registry, reservation_id, "effect-d2-197", record,
        kind="SETTLE", decision="EFFECT_DISPUTED", reservation_status="DISPUTED",
        effect_disposition="DISPUTED", effect_reason="LATE_EFFECT_AFTER_RELEASE",
        blocked=blocked, reasons=["LATE_EFFECT_AFTER_RELEASE"], administration=False,
    )
    event = governed_effect_event(
        permitted, after_release, effect, event_id="effect-d2-197",
        budget_inputs=[budget_input], clock_revision=REGISTRY_CLOCK_REVISION, dispatch_digest=digests["b"],
    )
    expected = budget_effect_result(
        base, after_release, event, budget_output,
        classification="LATE_AFTER_RELEASE", disposition="DISPUTED",
        reason_codes=sorted({"BUDGET_EFFECT_DISPUTED", "LATE_EFFECT_AFTER_RELEASE"}, key=lambda v: v.encode("utf-8")),
        occurrence_status=None, disputed=True, conflicts=[no_effect["evidence_id"]],
    )
    emit(
        "D2-197", base, after_release["state"], event, expected,
        "LIFE-010 names this the directional special case: LATE_AFTER_RELEASE is established effect evidence following an authorized no-effect release for the same provider-native operation identity, permit and stable dispatch-attempt digest. All three hold here, so the classification is LATE_AFTER_RELEASE rather than CONFLICTING. The record carries no mismatch of its own: the request matched the permit, the attempt was eligible, and LATE_AFTER_RELEASE is not among the classifications that force completion_mismatch true. RES-WIRE-003's reconciliation table gives a RELEASED reservation receiving a later EFFECT the EFFECT_DISPUTED decision: it becomes DISPUTED, restores the unresolved pending charge, retains the actual effect and blocks the affected partition. RES-WIRE-004 makes LATE_EFFECT_AFTER_RELEASE take precedence over the native record's mismatch reason. LIFE-006's mapping contributes LATE_EFFECT_AFTER_RELEASE for the classification and adds BUDGET_EFFECT_DISPUTED with the receipt reason, which coincide, so the sorted set has two members. LIFE-013 makes the two outcomes name one another in symmetric conflict lists. LIFE-012 bars the late evidence from erasing the earlier closure or reopening completed routing, so the NO_EFFECT completed row and the selected failure route are unchanged.",
    )


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    produced = []

    changed_dispatch_case(
        "D2-241",
        evidence_status="OUTCOME_UNKNOWN",
        classification="UNKNOWN",
        classification_reason="UNKNOWN_OUTCOME",
        occurrence_status="BLOCKED_DISPUTE",
        derivation="LIFE-010 maps OUTCOME_UNKNOWN to a SETTLE reservation event with native outcome UNKNOWN. The dispatch-attributed request differs from the committed permit, which makes completion_mismatch true with mismatch_reason NATIVE_REQUEST_MISMATCH because changed native arguments caused it. The reservation transition treats completion_mismatch true as disputed exposure even though the provider attributes the effect to the changed request. LIFE-011 keeps the occurrence unresolved with its unsettled reservation charged once and no advance along a success route, so the affected anchors stay blocked and nothing routes or completes.",
    )
    produced.append("D2-241")

    changed_dispatch_case(
        "D2-242",
        evidence_status="NO_EFFECT_ESTABLISHED",
        classification="UNEXPECTED",
        classification_reason="UNEXPECTED_EFFECT",
        occurrence_status="BLOCKED_DISPUTE",
        derivation="The changed-argument dispatch already blocked the active source. The no-effect assertion attributed to that dispatch is UNEXPECTED and reconciles exposure through a completion-mismatched RELEASE, which cannot free the reservation. LIFE-006 preserves BLOCKED_DISPUTE. The disputed budget result supplies BUDGET_EFFECT_DISPUTED and its own reasons, so DEPENDENCY_DISPUTED is not added. No completion, route or release occurs.",
    )
    produced.append("D2-242")

    # D2-270 binds the no-effect assertion to a NOT_SENT attempt that a later SENT attempt follows.
    # LIFE-010 (D2): the NOT_SENT attempt is not dispatch-disqualifying, so the authorization is
    # admitted; the attempt set is not final and safe, so the assertion is UNEXPECTED.
    attempt_set_not_final_case()
    final_safe_release_case()
    late_after_release_case()
    produced.extend(["D2-270", "D2-197", "D2-271"])

    print(json.dumps({"case_ids": produced, "count": len(produced), "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
