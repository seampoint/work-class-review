#!/usr/bin/env python3
"""Build conflict cases across acknowledgement updates for one stable attempt."""

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
    no_effect_completion_authorization,
    permitted_proposal,
    step_input,
)


GROUP = CASES / "acknowledgement-conflicts"


def acknowledgement_update(permitted: dict, prior_event: dict, state_result: dict, case_id: str) -> tuple[dict, dict]:
    selected_clock = available_clock("authority-clock", "2", "2026-09-10T04:31:00Z")
    clock_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-before-" + case_id.lower(),
        "kind": "CLOCK",
        "instance_id": state_result["state"]["instance_id"],
        "expected_state_revision": state_result["state"]["revision"],
        "expected_state_digest": state_result["state_digest"],
        "clock": selected_clock,
        "activation_clocks": [],
    }

    def retain_clock(state: dict) -> None:
        state["clocks"].append(copy.deepcopy(selected_clock))
        state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    clock_result = admitted_transition(
        state_result["state"],
        clock_event,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[{"kind": "CLOCK", "source": selected_clock["source"], "revision": selected_clock["revision"], "status": selected_clock["status"]}],
        mutate=retain_clock,
    )
    update = copy.deepcopy(prior_event)
    update["event_id"] = "acknowledge-before-" + case_id.lower()
    update["expected_state_revision"] = clock_result["state"]["revision"]
    update["expected_state_digest"] = clock_result["state_digest"]
    update["clock_revision"] = "2"
    update["acknowledgement"] = {
        "status": "ACCEPTED",
        "reference": "accepted-before-" + case_id.lower(),
        "observed_at": "2026-09-10T04:31:00Z",
    }
    result = dispatch_result(
        {"state": clock_result["state"], "permit": permitted["permit"]},
        update,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    new_dispatch = next(row for row in result["state"]["dispatches"] if row["event_id"] == update["event_id"])
    return update, {**result, "selected_dispatch_digest": new_dispatch["dispatch_digest"]}


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def main() -> None:
    base = base_lifecycle()
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-before-d2-261", attempt_status="SENT")
    sent = dispatch_result(permitted, dispatch, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")
    first_evidence = governed_native_evidence(base, permitted, sent, evidence_id="effect-before-d2-261")
    first_event = governed_effect_event(permitted, sent, first_evidence, event_id="complete-before-d2-261")
    first = effect_result(
        base,
        permitted,
        sent,
        first_event,
        classification="MATCHED",
        disposition="COMPLETED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=True,
    )
    _, updated = acknowledgement_update(permitted, dispatch, first, "D2-261")
    second_evidence = governed_native_evidence(
        base,
        permitted,
        updated,
        evidence_id="evidence-d2-261",
        status="NO_EFFECT_ESTABLISHED",
        native_operation_id="native-operation-2",
        observed_at="2026-09-10T04:32:00Z",
        dispatch_digest=updated["selected_dispatch_digest"],
    )
    second_event = governed_effect_event(
        permitted,
        updated,
        second_evidence,
        event_id="effect-d2-261",
        dispatch_digest=updated["selected_dispatch_digest"],
    )
    expected = effect_result(
        base,
        permitted,
        updated,
        second_event,
        classification="CONFLICTING",
        disposition="DISPUTED",
        reason_codes=["CONFLICTING_EFFECT"],
        occurrence_status=None,
        disputed=True,
        conflicts=[first_evidence["evidence_id"]],
        update_conflicting_outcomes=True,
    )
    emit(
        "D2-261",
        base,
        updated["state"],
        second_event,
        expected,
        "The later acknowledgement changes the complete dispatch digest but preserves the stable dispatch-attempt digest. A distinct no-effect conclusion therefore conflicts with the retained matched effect for the same permit and physical attempt. Both outcomes become disputed, while the completed route remains unchanged.",
    )

    base = base_lifecycle()
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-before-d2-262", attempt_status="SENT")
    sent = dispatch_result(permitted, dispatch, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")
    first_evidence = governed_native_evidence(
        base,
        permitted,
        sent,
        evidence_id="no-effect-before-d2-262",
        status="NO_EFFECT_ESTABLISHED",
    )
    authorization = no_effect_completion_authorization(base, permitted, sent, first_evidence)
    first_event = governed_effect_event(
        permitted,
        sent,
        first_evidence,
        event_id="close-before-d2-262",
        completion_authorization=authorization,
    )
    first = effect_result(
        base,
        permitted,
        sent,
        first_event,
        classification="NO_EFFECT_ESTABLISHED",
        disposition="STOPPED",
        reason_codes=["NO_EFFECT_ESTABLISHED"],
        occurrence_status=None,
        disputed=False,
        complete_disposition="NO_EFFECT",
        route=False,
        instance_status="STOPPED",
    )
    _, updated = acknowledgement_update(permitted, dispatch, first, "D2-262")
    second_evidence = governed_native_evidence(
        base,
        permitted,
        updated,
        evidence_id="evidence-d2-262",
        native_operation_id="native-operation-2",
        event_time="2026-09-10T04:30:30Z",
        observed_at="2026-09-10T04:32:00Z",
        dispatch_digest=updated["selected_dispatch_digest"],
    )
    second_event = governed_effect_event(
        permitted,
        updated,
        second_evidence,
        event_id="effect-d2-262",
        dispatch_digest=updated["selected_dispatch_digest"],
    )
    expected = effect_result(
        base,
        permitted,
        updated,
        second_event,
        classification="CONFLICTING",
        disposition="DISPUTED",
        reason_codes=["CONFLICTING_EFFECT"],
        occurrence_status=None,
        disputed=True,
        conflicts=[first_evidence["evidence_id"]],
        update_conflicting_outcomes=True,
    )
    emit(
        "D2-262",
        base,
        updated["state"],
        second_event,
        expected,
        "The updated dispatch record preserves the earlier attempt digest. Established effect evidence for that same physical attempt conflicts with its retained authorized no-effect conclusion even though the complete dispatch digest and provider-native operation identity changed. The earlier stop remains historical and both outcomes become disputed.",
    )

    print(json.dumps({"case_ids": ["D2-261", "D2-262"]}, indent=2))


if __name__ == "__main__":
    main()
