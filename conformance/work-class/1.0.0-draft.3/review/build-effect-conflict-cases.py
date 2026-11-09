#!/usr/bin/env python3
"""Build governed evidence identity, conflict and additional-effect cases."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_factory import (
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    effect_result,
    governed_effect_event,
    governed_native_evidence,
    permitted_proposal,
    stateful_refusal,
    step_input,
)


GROUP = CASES / "effect-conflicts"


def setup() -> tuple[dict, dict, dict, dict]:
    base = base_lifecycle()
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-effect-conflict", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-first-matched")
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-first-matched")
    matched = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="MATCHED",
        disposition="COMPLETED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=True,
    )
    return base, permitted, dispatched, matched


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def changed_same_operation(
    base: dict,
    permitted: dict,
    matched: dict,
    case_id: str,
) -> tuple[dict, dict]:
    first = matched["state"]["outcomes"][0]["native_evidence"]
    changed = copy.deepcopy(first)
    changed["evidence_id"] = "evidence-" + case_id.lower()
    changed["evidence_ref"] = "evidence-ref-" + case_id.lower()
    changed["record_digest"] = digest("provider-native-record", {"record": case_id, "conclusion": "changed"})
    event = governed_effect_event(
        permitted,
        {"state": matched["state"]},
        changed,
        event_id="effect-" + case_id.lower(),
    )
    expected = effect_result(
        base,
        permitted,
        {"state": matched["state"]},
        event,
        classification="CONFLICTING",
        disposition="DISPUTED",
        reason_codes=["CONFLICTING_EFFECT"],
        occurrence_status=None,
        disputed=True,
        conflicts=[first["evidence_id"]],
        update_conflicting_outcomes=True,
    )
    return event, expected


def no_effect_conflict(
    base: dict,
    permitted: dict,
    matched: dict,
    case_id: str,
    *,
    native_operation_id: str,
) -> tuple[dict, dict]:
    evidence = governed_native_evidence(
        base,
        permitted,
        {"state": matched["state"]},
        evidence_id="evidence-" + case_id.lower(),
        status="NO_EFFECT_ESTABLISHED",
        native_operation_id=native_operation_id,
        observed_at="2026-09-10T04:31:00Z",
    )
    event = governed_effect_event(
        permitted,
        {"state": matched["state"]},
        evidence,
        event_id="effect-" + case_id.lower(),
        completion_authorization=None,
    )
    first_id = matched["state"]["outcomes"][0]["native_evidence"]["evidence_id"]
    expected = effect_result(
        base,
        permitted,
        {"state": matched["state"]},
        event,
        classification="CONFLICTING",
        disposition="DISPUTED",
        reason_codes=["CONFLICTING_EFFECT"],
        occurrence_status=None,
        disputed=True,
        conflicts=[first_id],
        update_conflicting_outcomes=True,
    )
    return event, expected


def main() -> None:
    base, permitted, dispatched, matched = setup()

    first = matched["state"]["outcomes"][0]["native_evidence"]
    changed_id = copy.deepcopy(first)
    changed_id["record_digest"] = digest("provider-native-record", {"record": "changed-under-existing-evidence-id"})
    event = governed_effect_event(
        permitted,
        {"state": matched["state"]},
        changed_id,
        event_id="effect-d2-103",
    )
    emit(
        "D2-103",
        base,
        matched["state"],
        event,
        stateful_refusal(matched["state"], "INPUT_INVALID"),
        "The evidence identifier already exists, but the complete native-evidence bytes change through record_digest. Evidence-identity admission refuses INPUT_INVALID and preserves the prior conclusion exactly.",
    )

    for case_id in ["D2-039", "D2-072"]:
        event, expected = changed_same_operation(base, permitted, matched, case_id)
        emit(
            case_id,
            base,
            matched["state"],
            event,
            expected,
            "The new conclusive record keeps the same provider-native operation identity but changes its complete fact beyond evidence identity and reference. It is CONFLICTING, both conclusion records receive symmetric conflict identities and disputed status, and the completed route remains unchanged.",
        )

    for case_id in ["D2-107", "D2-161"]:
        event, expected = no_effect_conflict(
            base,
            permitted,
            matched,
            case_id,
            native_operation_id="native-operation-1",
        )
        emit(
            case_id,
            base,
            matched["state"],
            event,
            expected,
            "A distinct first no-effect conclusion contradicts the retained matched effect for the same permit and physical dispatch attempt. Because the occurrence is already closed, completion authorization is null; both outcomes become symmetrically disputed and routing is not rewound.",
        )

    event, expected = no_effect_conflict(
        base,
        permitted,
        matched,
        "D2-229",
        native_operation_id="different-native-operation",
    )
    emit(
        "D2-229",
        base,
        matched["state"],
        event,
        expected,
        "The no-effect record names a different provider-native operation identity, but it binds the same governed permit and stable dispatch attempt as the earlier effect. That physical-attempt scope fixes CONFLICTING and symmetric dispute retention.",
    )

    evidence = governed_native_evidence(
        base,
        permitted,
        {"state": matched["state"]},
        evidence_id="evidence-d2-196",
        native_operation_id="second-native-operation",
        observed_at="2026-09-10T04:31:00Z",
    )
    event = governed_effect_event(permitted, {"state": matched["state"]}, evidence, event_id="effect-d2-196")
    expected = effect_result(
        base,
        permitted,
        {"state": matched["state"]},
        event,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["UNEXPECTED_EFFECT"],
        occurrence_status=None,
        disputed=True,
    )
    emit(
        "D2-196",
        base,
        matched["state"],
        event,
        expected,
        "After one conclusive effect for the stable dispatch attempt, another established effect with a distinct provider-native operation identity is additional execution. It is retained as UNEXPECTED without changing the prior completion.",
    )

    conflict_event, conflict_result = changed_same_operation(base, permitted, matched, "D2-238-conflict-prerequisite")
    first_fact = copy.deepcopy(matched["state"]["outcomes"][0]["native_evidence"])
    first_fact["evidence_id"] = "evidence-d2-238"
    first_fact["evidence_ref"] = "evidence-ref-d2-238"
    duplicate_event = governed_effect_event(
        permitted,
        {"state": conflict_result["state"]},
        first_fact,
        event_id="effect-d2-238",
    )
    conflicting_evidence_id = conflict_event["native_evidence"]["evidence_id"]
    expected = effect_result(
        base,
        permitted,
        {"state": conflict_result["state"]},
        duplicate_event,
        classification="DUPLICATE",
        disposition="OUTCOME_RETAINED",
        reason_codes=["DUPLICATE_EVIDENCE"],
        occurrence_status=None,
        disputed=True,
        conflicts=[conflicting_evidence_id],
        update_conflicting_outcomes=True,
    )
    emit(
        "D2-238",
        base,
        conflict_result["state"],
        duplicate_event,
        expected,
        "The new evidence identity repeats the first fact after that fact already conflicts with another conclusive group. The duplicate inherits disputed status and the opposing conflict identity; the opposing outcome adds the duplicate identity, with no repeated completion.",
    )

    print(json.dumps({"case_ids": ["D2-039", "D2-072", "D2-103", "D2-107", "D2-161", "D2-196", "D2-229", "D2-238"]}, indent=2))


if __name__ == "__main__":
    main()
