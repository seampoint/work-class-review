#!/usr/bin/env python3
"""Build draft-3 dispatch-authorization lifecycle cases from the contract text."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    permitted_proposal,
    stateful_refusal,
    step_input,
)


GROUP = CASES / "dispatch-authorization"


def authorization_scope(event: dict) -> str:
    return digest(
        "dispatch-authorization-scope",
        {
            "instance_id": event["instance_id"],
            "occurrence_id": event["permit"]["occurrence"]["occurrence_id"],
            "permit_id": event["permit"]["permit_id"],
            "native_request": event["native_request"],
            "connector": event["connector"],
        },
    )


def authorization_record(event: dict) -> dict:
    record = {
        "authorization_digest": "",
        "event_id": event["event_id"],
        "event_digest": digest("runtime-event", event),
        "permit_digest": event["permit"]["permit_id"],
        "native_request": copy.deepcopy(event["native_request"]),
        "connector": copy.deepcopy(event["connector"]),
        "authorization_fence": copy.deepcopy(event["authorization_fence"]),
        "observation_digests": copy.deepcopy(event["observation_digests"]),
        "clock_revision": event["clock_revision"],
    }
    record["authorization_digest"] = digest("dispatch-authorization", {key: value for key, value in record.items() if key != "authorization_digest"})
    return record


def authorization_event(base: dict, permitted: dict, *, event_id: str) -> dict:
    state = permitted["state"]
    permit = permitted["permit"]
    connector_subject = {"id": "card-connector", "version": "version-1"}
    connector = {**connector_subject, "binding_digest": digest("connector-binding", connector_subject)}
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "AUTHORIZE_DISPATCH",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": permitted["state_digest"],
        "permit": copy.deepcopy(permit),
        "native_request": copy.deepcopy(permit["native_request"]),
        "connector": connector,
        "authorization_fence": {
            "provider": "maintenance-register",
            "source": "approval-register",
            "approval_id": "approval-ap-091",
            "scope_digest": "",
            "approver_role": "reliability-supervisor",
            "signed_at": "2026-09-10T04:29:00Z",
            "provider_revision": "approval-revision-7",
            "checked_at": "2026-09-10T04:30:00Z",
            "status": "EFFECTIVE",
        },
        "observation_digests": copy.deepcopy(permit["observation_digests"]),
        "clock_revision": "1",
    }
    event["authorization_fence"]["scope_digest"] = authorization_scope(event)
    return event


def authorization_result(base: dict, permitted: dict, event: dict) -> dict:
    record = authorization_record(event)

    def mutate(state: dict) -> None:
        state["authorizations"] = [record]

    return admitted_transition(
        permitted["state"],
        event,
        disposition="AUTHORIZED",
        reason_codes=[],
        details=[
            {
                "kind": "AUTHORIZATION",
                "authorization_digest": record["authorization_digest"],
                "permit_digest": event["permit"]["permit_id"],
                "approval_id": event["authorization_fence"]["approval_id"],
                "provider_revision": event["authorization_fence"]["provider_revision"],
                "checked_at": event["authorization_fence"]["checked_at"],
            }
        ],
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def emit(case_id: str, input_value: dict, expected: dict, derivation: str) -> dict:
    return exact_case(case_id, "step", input_value, expected, ["LIFE-009A"], derivation)


def main() -> None:
    base = base_lifecycle()
    permitted = permitted_proposal(base)
    valid_event = authorization_event(base, permitted, event_id="authorize-valid")
    valid_result = authorization_result(base, permitted, valid_event)
    cases = [
        emit(
            "C3-AUTH-001",
            step_input(base, permitted["state"], valid_event),
            valid_result,
            "An admitted permit, exact native request and connector, current clock, complete source-observation digest set and effective provider fence produce one retained authorization record before dispatch.",
        )
    ]

    withdrawn = copy.deepcopy(valid_event)
    withdrawn["event_id"] = "authorize-withdrawn"
    withdrawn["authorization_fence"]["status"] = "WITHDRAWN"
    cases.append(
        emit(
            "C3-AUTH-002",
            step_input(base, permitted["state"], withdrawn),
            stateful_refusal(permitted["state"], "PREREQUISITE_MISSING"),
            "A withdrawn fence does not create an authorization record or permit connector invocation.",
        )
    )

    wrong_scope = copy.deepcopy(valid_event)
    wrong_scope["event_id"] = "authorize-wrong-scope"
    wrong_scope["authorization_fence"]["scope_digest"] = digest("dispatch-authorization-scope", {"wrong": True})
    cases.append(
        emit(
            "C3-AUTH-003",
            step_input(base, permitted["state"], wrong_scope),
            stateful_refusal(permitted["state"], "BINDING_MISMATCH"),
            "A fence for a different scope cannot authorize the retained permit and native request.",
        )
    )

    dispatch = dispatch_event(
        base,
        {"state": valid_result["state"], "state_digest": valid_result["state_digest"], "permit": permitted["permit"]},
        event_id="dispatch-authorized",
        authorization_digest=valid_result["state"]["authorizations"][0]["authorization_digest"],
    )
    dispatch_expected = dispatch_result(
        {"state": valid_result["state"], "permit": permitted["permit"]},
        dispatch,
        disposition="DISPATCH_RECORDED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    cases.append(
        emit(
            "C3-AUTH-004",
            step_input(base, valid_result["state"], dispatch),
            dispatch_expected,
            "The dispatch observation names the retained authorization digest, so the consumer binds the attempt to the already committed fence.",
        )
    )

    missing_digest = copy.deepcopy(dispatch)
    missing_digest["event_id"] = "dispatch-without-authorization"
    missing_digest.pop("authorization_digest")
    missing_digest["expected_state_revision"] = valid_result["state"]["revision"]
    missing_digest["expected_state_digest"] = valid_result["state_digest"]
    cases.append(
        emit(
            "C3-AUTH-005",
            step_input(base, valid_result["state"], missing_digest),
            stateful_refusal(valid_result["state"], "PREREQUISITE_MISSING"),
            "Once a permit has a retained authorization record, a dispatch that omits its authorization digest cannot bypass that gate.",
        )
    )

    for case in cases:
        write_canonical_json(GROUP / f"{case['id']}.json", case)
    print(json.dumps({"case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
