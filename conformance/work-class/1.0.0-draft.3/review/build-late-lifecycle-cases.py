#!/usr/bin/env python3
"""Build late dispatch, late acknowledgement, and disqualified-effect vectors."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, exact_case, write_canonical_json
from fixture_factory import available_clock
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    effect_result,
    governed_effect_event,
    governed_native_evidence,
    permitted_proposal,
    step_input,
)


GROUP = CASES / "late-lifecycle"


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def advance_clock(permitted: dict, instant: str, revision: str, event_id: str) -> dict:
    selected = available_clock("authority-clock", revision, instant)
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

    result = admitted_transition(
        permitted["state"],
        event,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[{"kind": "CLOCK", "source": selected["source"], "revision": selected["revision"], "status": selected["status"]}],
        mutate=mutate,
    )
    return {**copy.deepcopy(permitted), "state": result["state"], "state_digest": result["state_digest"]}


def changed_request(permitted: dict) -> dict:
    native = copy.deepcopy(permitted["permit"]["native_request"])
    next(row for row in native["fields"] if row["name"] == "card_id")["value"]["value"] = "card-999"
    return native


def main() -> None:
    base = base_lifecycle()
    permitted = permitted_proposal(base)

    not_sent_event = dispatch_event(
        base,
        permitted,
        event_id="dispatch-before-d2-158",
        attempt_status="NOT_SENT",
        acknowledgement_status="NONE",
    )
    not_sent = dispatch_result(
        permitted,
        not_sent_event,
        disposition="DISPATCH_REFUSED",
        reasons=["NATIVE_NOT_SENT"],
        occurrence_status="PERMITTED",
    )
    evidence = governed_native_evidence(base, permitted, not_sent, evidence_id="evidence-d2-158")
    event = governed_effect_event(permitted, not_sent, evidence, event_id="effect-d2-158")
    expected = effect_result(
        base,
        permitted,
        not_sent,
        event,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["UNEXPECTED_EFFECT"],
        occurrence_status="OUTCOME_UNKNOWN",
        disputed=True,
    )
    emit(
        "D2-158",
        base,
        not_sent["state"],
        event,
        expected,
        "The attributed attempt is retained as NOT_SENT with no accepted acknowledgement. It is not a qualifying dispatch for governed completion, so the established effect is retained as UNEXPECTED, the occurrence becomes OUTCOME_UNKNOWN, and no route is selected.",
    )

    sent_event = dispatch_event(base, permitted, event_id="dispatch-before-d2-195", attempt_status="SENT")
    sent = dispatch_result(
        permitted,
        sent_event,
        disposition="DISPATCH_RECORDED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    evidence = governed_native_evidence(
        base,
        permitted,
        sent,
        evidence_id="evidence-d2-195",
        event_time="2026-09-10T04:35:30Z",
        observed_at="2026-09-10T04:36:00Z",
    )
    event = governed_effect_event(permitted, sent, evidence, event_id="effect-d2-195")
    expected = effect_result(
        base,
        permitted,
        sent,
        event,
        classification="MATCHED",
        disposition="COMPLETED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=True,
    )
    emit(
        "D2-195",
        base,
        sent["state"],
        event,
        expected,
        "The exact request was dispatched before the exclusive permit expiry. Later observation of its matching effect remains MATCHED even though the effect and observation occur after permit expiry; the occurrence completes and follows its declared route.",
    )

    after_expiry = advance_clock(permitted, "2026-09-10T04:35:00Z", "2", "clock-before-d2-216")
    expired_event = dispatch_event(
        base,
        after_expiry,
        event_id="dispatch-before-d2-216",
        attempt_status="SENT",
        attempted_at="2026-09-10T04:35:00Z",
        clock_revision="2",
    )
    expired = dispatch_result(
        after_expiry,
        expired_event,
        disposition="DISPUTED",
        reasons=["PERMIT_EXPIRED"],
        occurrence_status="BLOCKED_DISPUTE",
    )
    evidence = governed_native_evidence(
        base,
        permitted,
        expired,
        evidence_id="evidence-d2-216",
        event_time="2026-09-10T04:35:00Z",
        observed_at="2026-09-10T04:36:00Z",
    )
    event = governed_effect_event(permitted, expired, evidence, event_id="effect-d2-216")
    expected = effect_result(
        base,
        permitted,
        expired,
        event,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["DEPENDENCY_DISPUTED", "UNEXPECTED_EFFECT"],
        occurrence_status="BLOCKED_DISPUTE",
        disputed=True,
    )
    emit(
        "D2-216",
        base,
        expired["state"],
        event,
        expected,
        "The retained attempt occurred at the exclusive permit expiry and was therefore disqualified with PERMIT_EXPIRED. Exact success evidence is still retained, but it is UNEXPECTED and cannot complete or route the occurrence.",
    )

    report_clock = advance_clock(permitted, "2026-09-10T04:36:00Z", "2", "clock-before-d2-220")
    late_report_event = dispatch_event(
        base,
        report_clock,
        event_id="dispatch-d2-220",
        attempt_status="SENT",
        attempted_at="2026-09-10T04:34:00Z",
        clock_revision="2",
    )
    late_report = dispatch_result(
        report_clock,
        late_report_event,
        disposition="DISPATCH_RECORDED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    write_canonical_json(
        GROUP / "C2-220-dispatch.json",
        exact_case(
            "C2-220-dispatch",
            "step",
            step_input(base, report_clock["state"], late_report_event),
            late_report,
            ["LIFE-009", "LIFE-012"],
            "The latest retained clock is later than permit expiry, but permit expiry is tested against attempted_at. The exact attempt occurred before the exclusive expiry, so the later report is recorded without PERMIT_EXPIRED.",
        ),
    )
    evidence = governed_native_evidence(
        base,
        permitted,
        late_report,
        evidence_id="evidence-d2-220",
        event_time="2026-09-10T04:34:30Z",
        observed_at="2026-09-10T04:36:00Z",
    )
    event = governed_effect_event(permitted, late_report, evidence, event_id="effect-d2-220")
    expected = effect_result(
        base,
        permitted,
        late_report,
        event,
        classification="MATCHED",
        disposition="COMPLETED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=True,
    )
    emit(
        "D2-220",
        base,
        late_report["state"],
        event,
        expected,
        "The retained dispatch reports an exact attempt made before permit expiry, although the report was evaluated against a later clock. The subsequent exact effect is MATCHED, completes the occurrence, and advances the work graph.",
    )

    first_event = dispatch_event(base, permitted, event_id="dispatch-before-d2-258", attempt_status="SENT")
    first = dispatch_result(
        permitted,
        first_event,
        disposition="DISPATCH_RECORDED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    evidence = governed_native_evidence(base, permitted, first, evidence_id="evidence-before-d2-258")
    effect_event = governed_effect_event(permitted, first, evidence, event_id="effect-before-d2-258")
    completed = effect_result(
        base,
        permitted,
        first,
        effect_event,
        classification="MATCHED",
        disposition="COMPLETED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=True,
    )
    acknowledgement_clock = advance_clock(
        {**copy.deepcopy(completed), "permit": permitted["permit"]},
        "2026-09-10T04:31:00Z",
        "2",
        "clock-before-d2-258",
    )
    update = copy.deepcopy(first_event)
    update["event_id"] = "acknowledge-d2-258"
    update["expected_state_revision"] = acknowledgement_clock["state"]["revision"]
    update["expected_state_digest"] = acknowledgement_clock["state_digest"]
    update["clock_revision"] = "2"
    update["acknowledgement"] = {
        "status": "ACCEPTED",
        "reference": "accepted-acknowledgement-d2-258",
        "observed_at": "2026-09-10T04:31:00Z",
    }
    expected = dispatch_result(
        {"state": acknowledgement_clock["state"], "permit": permitted["permit"]},
        update,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    emit(
        "D2-258",
        base,
        acknowledgement_clock["state"],
        update,
        expected,
        "After a new admitted clock reaches the acknowledgement time, the update repeats the retained permit, native request, connector and attempt bytes, so it reuses the stable attempt digest. It records the first ACCEPTED acknowledgement under a new complete dispatch digest without recreating the completed occurrence or changing its terminal route.",
    )

    changed_event = dispatch_event(
        base,
        permitted,
        event_id="dispatch-before-d2-269",
        attempt_status="SENT",
        native_request=changed_request(permitted),
    )
    changed = dispatch_result(
        permitted,
        changed_event,
        disposition="DISPUTED",
        reasons=["NATIVE_ARGUMENT_MISMATCH"],
        occurrence_status="BLOCKED_DISPUTE",
    )
    evidence = governed_native_evidence(
        base,
        permitted,
        changed,
        evidence_id="evidence-d2-269",
        status="NO_EFFECT_ESTABLISHED",
    )
    event = governed_effect_event(permitted, changed, evidence, event_id="effect-d2-269")
    expected = effect_result(
        base,
        permitted,
        changed,
        event,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["DEPENDENCY_DISPUTED", "UNEXPECTED_EFFECT"],
        occurrence_status="BLOCKED_DISPUTE",
        disputed=True,
    )
    emit(
        "D2-269",
        base,
        changed["state"],
        event,
        expected,
        "The changed-argument dispatch may have reached the connector and remains disqualified. Its first no-effect assertion carries null completion authorization, is retained as UNEXPECTED, and cannot close the occurrence or establish safe release.",
    )

    print(json.dumps({"exact_case_ids": ["D2-158", "D2-195", "D2-216", "D2-220", "D2-258", "D2-269"], "supplementary_cases": 1}, indent=2))


if __name__ == "__main__":
    main()
