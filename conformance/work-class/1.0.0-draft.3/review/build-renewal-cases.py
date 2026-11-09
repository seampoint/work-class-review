#!/usr/bin/env python3
"""Build authority-only permit expiry, renewal, and supersession cases."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    permitted_proposal,
    proposal_permit,
    state_digest,
    stateful_refusal,
    step_input,
)


GROUP = CASES / "permit-renewal"


def advance_clock(permitted: dict, *, revision: str = "2", instant: str = "2026-09-10T04:35:00Z", event_id: str) -> dict:
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
        state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    result = admitted_transition(
        permitted["state"],
        event,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[{"kind": "CLOCK", "source": selected["source"], "revision": selected["revision"], "status": selected["status"]}],
        mutate=mutate,
    )
    return {**copy.deepcopy(permitted), "state": result["state"], "state_digest": result["state_digest"]}


def current_authority(base: dict, instant: str) -> tuple[dict, dict]:
    authority_input = copy.deepcopy(base["authority_input"])
    prior_instant = authority_input["clock"]["instant"]
    authority_input["clock"]["status"] = "AVAILABLE"
    authority_input["clock"]["instant"] = instant
    query_replacements = {}
    for observation in authority_input["observations"]:
        if observation["query"]["at"] != prior_instant:
            continue
        prior_digest = observation["query_digest"]
        observation["query"]["at"] = instant
        observation["as_of"] = instant
        observation["query_digest"] = digest("authority-query", observation["query"])
        query_replacements[prior_digest] = observation["query_digest"]
    authority_result = copy.deepcopy(base["authority_result"])
    for check in authority_result["checks"]:
        if check["at"] == prior_instant:
            check["at"] = instant
        if check["requirement_ref"] in query_replacements:
            check["requirement_ref"] = query_replacements[check["requirement_ref"]]
    authority_result["checks"].sort(key=canonical_bytes)
    authority_result["evidence_digest"] = digest(
        "authority-evidence",
        {
            key: authority_input[key]
            for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock"]
        },
    )
    return authority_input, authority_result


def renewal_event(base: dict, current: dict, case_id: str, *, changed_native: bool = False) -> tuple[dict, dict]:
    event = copy.deepcopy(base["proposal_event"])
    event["event_id"] = "renewal-" + case_id.lower()
    event["expected_state_revision"] = current["state"]["revision"]
    event["expected_state_digest"] = current["state_digest"]
    event["clock_revision"] = "2"
    authority_input, authority_result = current_authority(base, "2026-09-10T04:35:00Z")
    event["authority_input"] = authority_input
    event["observation_digests"] = sorted(
        (digest("authority-observation", row) for row in authority_input["observations"]),
        key=lambda value: value.encode("utf-8"),
    )
    if changed_native:
        next(row for row in event["native_request"]["fields"] if row["name"] == "card_id")["value"]["value"] = "card-999"
    return event, authority_result


def renewal_result(base: dict, current: dict, event: dict, authority_result: dict) -> dict:
    prior_permit = current["permit"]
    renewal_base = {**copy.deepcopy(base), "authority_result": copy.deepcopy(authority_result)}
    permit = proposal_permit(renewal_base, event)
    permit["supersedes_permit_digest"] = prior_permit["permit_id"]
    permit["expires_at"] = "2026-09-10T04:40:00Z"
    permit["permit_id"] = digest("permit", {key: value for key, value in permit.items() if key != "permit_id"})
    event_digest = digest("runtime-event", event)
    proposal_digest = digest("proposal", event)

    def mutate(state: dict) -> None:
        state["proposals"].append(
            {
                "event_id": event["event_id"],
                "event_digest": event_digest,
                "proposal_digest": proposal_digest,
                "occurrence_id": event["occurrence"]["occurrence_id"],
                "disposition": "PERMITTED",
                "permit_digest": permit["permit_id"],
                "authority_result_digest": permit["authority_result_digest"],
                "reservation_receipt_digests": [],
                "prior_permit_digest": prior_permit["permit_id"],
            }
        )
        state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
        state["permits"].append(copy.deepcopy(permit))
        state["permits"].sort(key=lambda row: row["permit_id"].encode("utf-8"))

    return admitted_transition(
        current["state"],
        event,
        disposition="PERMITTED",
        reason_codes=[],
        details=[],
        permit=permit,
        mutate=mutate,
    )


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def main() -> None:
    base = base_lifecycle()
    permitted = permitted_proposal(base)
    emit(
        "D2-169",
        base,
        base["clock_result"]["state"],
        base["proposal_event"],
        permitted,
        "The authority-only proposal selects the accepted authority clock at 04:30:00 and the step declares permit_seconds 300. The committed permit expires exclusively at 04:35:00 and contains no budget revision or reservation result.",
    )

    early_event = copy.deepcopy(base["proposal_event"])
    early_event["event_id"] = "renewal-d2-171"
    early_event["expected_state_revision"] = permitted["state"]["revision"]
    early_event["expected_state_digest"] = permitted["state_digest"]
    emit(
        "D2-171",
        base,
        permitted["state"],
        early_event,
        stateful_refusal(permitted["state"], "PREREQUISITE_MISSING"),
        "The retained clock remains 04:30:00, before the prior permit's exclusive 04:35:00 expiry. Renewal eligibility therefore fails before authority evaluation and leaves the prior permit unchanged.",
    )

    expired = advance_clock(permitted, event_id="clock-before-d2-170")
    event, authority_result = renewal_event(base, expired, "D2-170")
    renewed = renewal_result(base, expired, event, authority_result)
    emit(
        "D2-170",
        base,
        expired["state"],
        event,
        renewed,
        "The latest retained authority clock is exactly the prior permit's exclusive expiry. The occurrence is still PERMITTED, no dispatch consumed the permit, the request is byte-identical and current authority succeeds. A new five-minute permit supersedes the prior permit while activation and actuation counts remain unchanged.",
    )

    changed_event, _ = renewal_event(base, expired, "D2-172", changed_native=True)
    emit(
        "D2-172",
        base,
        expired["state"],
        changed_event,
        stateful_refusal(expired["state"], "BINDING_MISMATCH"),
        "Although retained time establishes expiry, the proposed native fields differ from the prior permit's exact native request. Renewal is a continuation of the unchanged request, so binding admission fails without superseding the prior permit.",
    )

    old_dispatch = dispatch_event(
        base,
        renewed,
        event_id="dispatch-d2-175",
        attempt_status="NOT_SENT",
        acknowledgement_status="NONE",
        attempted_at="2026-09-10T04:35:00Z",
        clock_revision="2",
    )
    old_dispatch["permit"] = copy.deepcopy(permitted["permit"])
    old_dispatch["native_request"] = copy.deepcopy(permitted["permit"]["native_request"])
    expected = dispatch_result(
        {"state": renewed["state"], "permit": permitted["permit"]},
        old_dispatch,
        disposition="DISPATCH_REFUSED",
        reasons=["NATIVE_NOT_SENT", "PERMIT_EXPIRED", "PERMIT_SUPERSEDED"],
        occurrence_status="PERMITTED",
    )
    emit(
        "D2-175",
        base,
        renewed["state"],
        old_dispatch,
        expected,
        "The observed permit is the expired predecessor of the current permit. NOT_SENT with no accepted acknowledgement is retained safely, but the dispatch is refused with the table reason plus PERMIT_EXPIRED and PERMIT_SUPERSEDED. The active occurrence and current permit remain unchanged.",
    )

    safe_dispatch_event = dispatch_event(
        base,
        permitted,
        event_id="dispatch-before-d2-190",
        attempt_status="NOT_SENT",
        acknowledgement_status="REJECTED",
    )
    safe_dispatch = dispatch_result(
        permitted,
        safe_dispatch_event,
        disposition="DISPATCH_REFUSED",
        reasons=["NATIVE_NOT_SENT"],
        occurrence_status="PERMITTED",
    )
    safe_expired = advance_clock(
        {**copy.deepcopy(permitted), "state": safe_dispatch["state"], "state_digest": safe_dispatch["state_digest"]},
        event_id="clock-before-d2-190",
    )
    event, authority_result = renewal_event(base, safe_expired, "D2-190")
    expected = renewal_result(base, safe_expired, event, authority_result)
    emit(
        "D2-190",
        base,
        safe_expired["state"],
        event,
        expected,
        "The only earlier attempt is explicitly NOT_SENT. Its REJECTED acknowledgement does not change that attempt status or consume the permit. After expiry, exact renewal with current authority succeeds and supersedes the prior permit.",
    )

    sent_event = dispatch_event(base, permitted, event_id="dispatch-before-d2-191", attempt_status="SENT")
    sent = dispatch_result(
        permitted,
        sent_event,
        disposition="DISPATCH_RECORDED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    sent_expired = advance_clock(
        {**copy.deepcopy(permitted), "state": sent["state"], "state_digest": sent["state_digest"]},
        event_id="clock-before-d2-191",
    )
    event, _ = renewal_event(base, sent_expired, "D2-191")
    emit(
        "D2-191",
        base,
        sent_expired["state"],
        event,
        stateful_refusal(sent_expired["state"], "PREREQUISITE_MISSING"),
        "The earlier SENT attempt consumed the old permit and left the occurrence DISPATCHED. Expiry cannot turn that invocation into an undispatched renewal candidate, so no second permission is created.",
    )

    print(json.dumps({"case_ids": ["D2-169", "D2-170", "D2-171", "D2-172", "D2-175", "D2-190", "D2-191"]}, indent=2))


if __name__ == "__main__":
    main()
