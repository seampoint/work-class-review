#!/usr/bin/env python3
"""Build declared-failure and authority-only no-effect lifecycle cases."""

from __future__ import annotations

import json

from corpus_common import CASES, canonical_bytes, exact_case, write_canonical_json
from lifecycle_factory import (
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    effect_result,
    governed_effect_event,
    governed_native_evidence,
    no_effect_completion_authorization,
    permitted_proposal,
    stateful_refusal,
    step_input,
)


GROUP = CASES / "failure-no-effect"


def failure_edge(definition: dict) -> None:
    operation = next(row for row in definition["steps"] if row["kind"] == "OPERATION")
    operation["failure_behavior"] = "FAILURE_EDGE"
    definition["relationships"].append({"kind": "FAILURE", "from": operation["id"], "to": "terminal"})
    definition["relationships"].sort(key=canonical_bytes)


def setup(*, with_failure_edge: bool) -> tuple[dict, dict, dict]:
    base = base_lifecycle(definition_mutator=failure_edge if with_failure_edge else None)
    permitted = permitted_proposal(base)
    event = dispatch_event(base, permitted, event_id="dispatch-failure-no-effect", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, event, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    return base, permitted, dispatched


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def no_effect_event(base: dict, permitted: dict, dispatched: dict, case_id: str, *, authorization: bool) -> dict:
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-" + case_id.lower(),
        status="NO_EFFECT_ESTABLISHED",
    )
    completion = no_effect_completion_authorization(base, permitted, dispatched, evidence) if authorization else None
    return governed_effect_event(
        permitted,
        dispatched,
        evidence,
        event_id="effect-" + case_id.lower(),
        completion_authorization=completion,
    )


def main() -> None:
    base, permitted, dispatched = setup(with_failure_edge=True)
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-d2-029",
        result_value="REJECTED",
    )
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-d2-029")
    expected = effect_result(
        base,
        permitted,
        dispatched,
        event,
        classification="FAILED",
        disposition="FAILED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="FAILED",
        route=True,
        route_relationship_kind="FAILURE",
    )
    emit(
        "D2-029",
        base,
        dispatched["state"],
        event,
        expected,
        "The exact effect carrier supplies the declared failure value. FAILURE_EDGE selects the one FAILURE relationship, records the occurrence as FAILED, and reaches terminal without treating the failure as a success route.",
    )

    for case_id in ["D2-099", "D2-126"]:
        event = no_effect_event(base, permitted, dispatched, case_id, authorization=True)
        expected = effect_result(
            base,
            permitted,
            dispatched,
            event,
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
            case_id,
            base,
            dispatched["state"],
            event,
            expected,
            "The first authority-only no-effect record has null event_time, an exact final-safe dispatch attribution, explicit past-and-future no-effect assertion, and current exact completion authorization. The occurrence closes as NO_EFFECT and follows its declared FAILURE relationship.",
        )

    event = no_effect_event(base, permitted, dispatched, "D2-100", authorization=False)
    emit(
        "D2-100",
        base,
        dispatched["state"],
        event,
        stateful_refusal(dispatched["state"], "EVIDENCE_UNAVAILABLE"),
        "A first no-effect assertion for an unresolved occurrence requires a complete organizational completion authorization. Null authorization is EVIDENCE_UNAVAILABLE and changes no work state.",
    )

    stop_base, stop_permitted, stop_dispatched = setup(with_failure_edge=False)
    evidence = governed_native_evidence(
        stop_base,
        stop_permitted,
        stop_dispatched,
        evidence_id="evidence-d2-184",
        result_value="REJECTED",
    )
    event = governed_effect_event(stop_permitted, stop_dispatched, evidence, event_id="effect-d2-184")
    expected = effect_result(
        stop_base,
        stop_permitted,
        stop_dispatched,
        event,
        classification="FAILED",
        disposition="STOPPED",
        reason_codes=["DECLARED_FAILURE"],
        occurrence_status=None,
        disputed=False,
        complete_disposition="FAILED",
        route=False,
        instance_status="STOPPED",
    )
    emit(
        "D2-184",
        stop_base,
        stop_dispatched["state"],
        event,
        expected,
        "The exact carrier establishes the declared failure, and the operation declares failure_behavior STOP. The effect is retained, the occurrence closes as FAILED, no successor is created, and the instance becomes STOPPED.",
    )

    event = no_effect_event(stop_base, stop_permitted, stop_dispatched, "D2-152", authorization=True)
    expected = effect_result(
        stop_base,
        stop_permitted,
        stop_dispatched,
        event,
        classification="NO_EFFECT_ESTABLISHED",
        disposition="STOPPED",
        reason_codes=["NO_EFFECT_ESTABLISHED"],
        occurrence_status=None,
        disputed=False,
        complete_disposition="NO_EFFECT",
        route=False,
        instance_status="STOPPED",
    )
    emit(
        "D2-152",
        stop_base,
        stop_dispatched["state"],
        event,
        expected,
        "Qualifying affirmative no-effect evidence closes the occurrence as NO_EFFECT. With failure_behavior STOP, the instance stops without selecting a relationship or creating a successor.",
    )

    print(json.dumps({"case_ids": ["D2-029", "D2-099", "D2-100", "D2-126", "D2-152", "D2-184"]}, indent=2))


if __name__ == "__main__":
    main()
