#!/usr/bin/env python3
"""Build foundational governed-effect cases from the frozen lifecycle rules."""

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


GROUP = CASES / "effect-foundation"


def setup() -> tuple[dict, dict, dict]:
    base = base_lifecycle()
    permitted = permitted_proposal(base)
    event = dispatch_event(base, permitted, event_id="dispatch-effect-foundation", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(
        permitted,
        event,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    return base, permitted, dispatched


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    case = exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation)
    write_canonical_json(GROUP / f"{case_id}.json", case)


def standard_event(
    base: dict,
    permitted: dict,
    state_result: dict,
    case_id: str,
    **evidence_options,
) -> tuple[dict, dict]:
    evidence = governed_native_evidence(
        base,
        permitted,
        state_result,
        evidence_id="evidence-" + case_id.lower(),
        **evidence_options,
    )
    event = governed_effect_event(
        permitted,
        state_result,
        evidence,
        event_id="effect-" + case_id.lower(),
    )
    return evidence, event


def main() -> None:
    base, permitted, dispatched = setup()

    evidence, event = standard_event(base, permitted, dispatched, "D2-026")
    expected = effect_result(
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
    emit(
        "D2-026",
        base,
        dispatched["state"],
        event,
        expected,
        "The first established effect has the exact completion-provider triple, request bindings, success status, dispatch attempt and event timeline. It records MATCHED, completes the occurrence as SUCCEEDED, follows the one sequence relationship to terminal, and completes the instance.",
    )
    matched = expected

    absent = copy.deepcopy(event)
    absent["event_id"] = "effect-d2-027"
    absent["permit"]["expires_at"] = "2026-09-10T04:36:00Z"
    permit_without_id = {key: value for key, value in absent["permit"].items() if key != "permit_id"}
    absent["permit"]["permit_id"] = digest("permit", permit_without_id)
    absent["native_evidence"]["evidence_id"] = "evidence-d2-027"
    absent["native_evidence"]["evidence_ref"] = "evidence-ref-d2-027"
    absent["native_evidence"]["record_digest"] = digest("provider-native-record", {"record": "evidence-d2-027"})
    emit(
        "D2-027",
        base,
        dispatched["state"],
        absent,
        stateful_refusal(dispatched["state"], "PREREQUISITE_MISSING"),
        "The supplied permit is internally self-identifying but its digest is absent from the admitted state's permit inventory. Permit presence is the effect prerequisite and fails before dispatch or carrier interpretation.",
    )

    changed_fields = copy.deepcopy(dispatched["state"]["dispatches"][-1]["native_request"]["fields"])
    next(row for row in changed_fields if row["name"] == "card_id")["value"]["value"] = "card-999"
    changed_fields.append({"name": "status", "value": {"type_ref": "STRING", "value": "ISSUED"}})
    evidence, event = standard_event(base, permitted, dispatched, "D2-030", actual_fields=changed_fields)
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["UNEXPECTED_EFFECT"],
        occurrence_status="OUTCOME_UNKNOWN",
        disputed=True,
    )
    emit(
        "D2-030",
        base,
        dispatched["state"],
        event,
        expected,
        "The attributable first effect changes the request-bound card identity. Lifecycle carrier comparison classifies it as UNEXPECTED, retains it as disputed evidence, leaves the occurrence unresolved as OUTCOME_UNKNOWN, and does not route.",
    )

    evidence, event = standard_event(base, permitted, dispatched, "D2-032", status="OUTCOME_UNKNOWN")
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="UNKNOWN",
        disposition="OUTCOME_RETAINED",
        reason_codes=["UNKNOWN_OUTCOME"],
        occurrence_status="OUTCOME_UNKNOWN",
        disputed=False,
    )
    emit(
        "D2-032",
        base,
        dispatched["state"],
        event,
        expected,
        "The native record expressly reports OUTCOME_UNKNOWN with no event time, fields or collections. The evidence is retained, the occurrence becomes OUTCOME_UNKNOWN, and the graph does not advance.",
    )
    unknown = expected

    evidence, event = standard_event(
        base,
        permitted,
        dispatched,
        "D2-033",
        status="OUTCOME_UNKNOWN",
        observed_at="2026-09-10T04:31:00Z",
    )
    evidence["evidence_ref"] = "connector-timeout-without-terminal-fact"
    event["native_evidence"] = evidence
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="UNKNOWN",
        disposition="OUTCOME_RETAINED",
        reason_codes=["UNKNOWN_OUTCOME"],
        occurrence_status="OUTCOME_UNKNOWN",
        disputed=False,
    )
    emit(
        "D2-033",
        base,
        dispatched["state"],
        event,
        expected,
        "A timeout supplies only an OUTCOME_UNKNOWN assertion. It neither establishes no effect nor authorizes release, so the occurrence and any exposure remain unresolved.",
    )

    evidence, event = standard_event(base, permitted, dispatched, "D2-098")
    event["native_evidence"]["event_time"] = None
    emit(
        "D2-098",
        base,
        dispatched["state"],
        event,
        stateful_refusal(dispatched["state"], "INPUT_INVALID"),
        "EFFECT_ESTABLISHED semantically requires a nonnull event_time. The closed shape permits the nullable field so the semantic INPUT_INVALID rule can refuse it while preserving state.",
    )

    first_native = matched["state"]["outcomes"][0]["native_evidence"]
    repeated_event = governed_effect_event(
        permitted,
        {"state": matched["state"]},
        copy.deepcopy(first_native),
        event_id="effect-d2-102",
    )
    expected = effect_result(
        base,
        permitted,
        {"state": matched["state"]},
        repeated_event,
        classification="DUPLICATE",
        disposition="OUTCOME_RETAINED",
        reason_codes=["DUPLICATE_EVIDENCE"],
        occurrence_status=None,
        disputed=False,
        append_outcome=False,
    )
    emit(
        "D2-102",
        base,
        matched["state"],
        repeated_event,
        expected,
        "The new lifecycle event repeats an existing evidence_id and byte-identical native evidence. It records a duplicate decision without adding another outcome, completion or route.",
    )

    changed_identity = copy.deepcopy(first_native)
    changed_identity["evidence_id"] = "evidence-d2-104"
    changed_identity["evidence_ref"] = "evidence-ref-d2-104"
    duplicate_event = governed_effect_event(
        permitted,
        {"state": matched["state"]},
        changed_identity,
        event_id="effect-d2-104",
    )
    expected = effect_result(
        base,
        permitted,
        {"state": matched["state"]},
        duplicate_event,
        classification="DUPLICATE",
        disposition="OUTCOME_RETAINED",
        reason_codes=["DUPLICATE_EVIDENCE"],
        occurrence_status=None,
        disputed=False,
    )
    emit(
        "D2-104",
        base,
        matched["state"],
        duplicate_event,
        expected,
        "Omitting only evidence_id and evidence_ref leaves the same complete native-evidence-fact digest. The new evidence identity is retained as DUPLICATE while completion and routing remain unchanged.",
    )

    later_unknown = governed_native_evidence(
        base,
        permitted,
        {"state": matched["state"]},
        evidence_id="evidence-d2-105",
        status="OUTCOME_UNKNOWN",
        native_operation_id="native-operation-1",
        observed_at="2026-09-10T04:31:00Z",
    )
    later_unknown_event = governed_effect_event(
        permitted,
        {"state": matched["state"]},
        later_unknown,
        event_id="effect-d2-105",
    )
    expected = effect_result(
        base,
        permitted,
        {"state": matched["state"]},
        later_unknown_event,
        classification="UNKNOWN",
        disposition="OUTCOME_RETAINED",
        reason_codes=["UNKNOWN_OUTCOME"],
        occurrence_status=None,
        disputed=False,
    )
    emit(
        "D2-105",
        base,
        matched["state"],
        later_unknown_event,
        expected,
        "A later unknown assertion is retained after conclusive MATCHED evidence, but it does not change the completed occurrence, terminal route or instance status.",
    )

    matching_after_unknown = governed_native_evidence(
        base,
        permitted,
        {"state": unknown["state"]},
        evidence_id="evidence-d2-106",
        status="EFFECT_ESTABLISHED",
        native_operation_id="native-operation-1",
        observed_at="2026-09-10T04:31:00Z",
    )
    match_event = governed_effect_event(
        permitted,
        {"state": unknown["state"]},
        matching_after_unknown,
        event_id="effect-d2-106",
    )
    expected = effect_result(
        base,
        permitted,
        {"state": unknown["state"]},
        match_event,
        classification="MATCHED",
        disposition="COMPLETED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=True,
    )
    emit(
        "D2-106",
        base,
        unknown["state"],
        match_event,
        expected,
        "UNKNOWN is not conclusive. The first later exact established effect for the same dispatch is MATCHED, completes the still-active occurrence, and follows the declared sequence to terminal.",
    )

    evidence, event = standard_event(base, permitted, dispatched, "D2-178")
    event["clock_revision"] = "1"
    emit(
        "D2-178",
        base,
        dispatched["state"],
        event,
        stateful_refusal(dispatched["state"], "CLOCK_INVALID"),
        "An authority-only effect has no registry input and therefore requires clock_revision null. Supplying a revision is CLOCK_INVALID and leaves the work state unchanged.",
    )

    evidence, event = standard_event(base, permitted, dispatched, "D2-179")
    event["native_evidence"]["provider"] = "other-provider"
    emit(
        "D2-179",
        base,
        dispatched["state"],
        event,
        stateful_refusal(dispatched["state"], "BINDING_MISMATCH"),
        "The effect provider no longer equals the operation's exact completion-carrier provider. Carrier binding fails before result-field interpretation.",
    )

    evidence, event = standard_event(
        base,
        permitted,
        dispatched,
        "D2-225",
        event_time="2026-09-10T04:29:59Z",
        observed_at="2026-09-10T04:30:00Z",
    )
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["UNEXPECTED_EFFECT"],
        occurrence_status="OUTCOME_UNKNOWN",
        disputed=True,
    )
    emit(
        "D2-225",
        base,
        dispatched["state"],
        event,
        expected,
        "The established event time precedes the retained dispatch attempt. The record remains attributable evidence, but timeline classification makes it UNEXPECTED and prevents routing.",
    )

    evidence, event = standard_event(
        base,
        permitted,
        dispatched,
        "D2-226",
        event_time="2026-09-10T04:30:01Z",
        observed_at="2026-09-10T04:30:00Z",
    )
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="UNEXPECTED",
        disposition="DISPUTED",
        reason_codes=["UNEXPECTED_EFFECT"],
        occurrence_status="OUTCOME_UNKNOWN",
        disputed=True,
    )
    emit(
        "D2-226",
        base,
        dispatched["state"],
        event,
        expected,
        "The established event time is later than the record's own observation time. The schema-valid evidence is retained as UNEXPECTED and does not route.",
    )

    evidence, event = standard_event(base, permitted, dispatched, "D2-207", status="NO_EFFECT_ESTABLISHED")
    event["native_evidence"]["record_type"] = "card-result"
    emit(
        "D2-207",
        base,
        dispatched["state"],
        event,
        stateful_refusal(dispatched["state"], "BINDING_MISMATCH"),
        "NO_EFFECT_ESTABLISHED must use the separately declared no-effect provider, source and record-type triple. Supplying the effect record type is a carrier binding mismatch.",
    )

    print(
        json.dumps(
            {
                "case_ids": [
                    "D2-026",
                    "D2-027",
                    "D2-030",
                    "D2-032",
                    "D2-033",
                    "D2-098",
                    "D2-102",
                    "D2-104",
                    "D2-105",
                    "D2-106",
                    "D2-178",
                    "D2-179",
                    "D2-207",
                    "D2-225",
                    "D2-226",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
