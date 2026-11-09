#!/usr/bin/env python3
"""Build the complete dispatch table and decisive dispatch admission vectors."""

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
    permitted_proposal,
    stateful_refusal,
    step_input,
)


TABLE = {
    ("NOT_SENT", "NONE"): ("DISPATCH_REFUSED", ["NATIVE_NOT_SENT"], "PERMITTED"),
    ("NOT_SENT", "ACCEPTED"): ("DISPUTED", ["DISPATCH_EVIDENCE_CONFLICT"], "OUTCOME_UNKNOWN"),
    ("NOT_SENT", "REJECTED"): ("DISPATCH_REFUSED", ["NATIVE_NOT_SENT"], "PERMITTED"),
    ("NOT_SENT", "UNKNOWN"): ("DISPATCH_REFUSED", ["NATIVE_NOT_SENT"], "PERMITTED"),
    ("SENT", "NONE"): ("DISPATCH_RECORDED", [], "DISPATCHED"),
    ("SENT", "ACCEPTED"): ("ACKNOWLEDGED", [], "DISPATCHED"),
    ("SENT", "REJECTED"): ("DISPATCH_RECORDED", ["ACKNOWLEDGEMENT_REJECTED"], "DISPATCHED"),
    ("SENT", "UNKNOWN"): ("DISPATCH_RECORDED", ["DISPATCH_STATUS_UNKNOWN"], "DISPATCHED"),
    ("REJECTED", "NONE"): ("DISPATCH_REFUSED", ["NATIVE_DISPATCH_REJECTED"], "PERMITTED"),
    ("REJECTED", "ACCEPTED"): ("DISPUTED", ["DISPATCH_EVIDENCE_CONFLICT"], "OUTCOME_UNKNOWN"),
    ("REJECTED", "REJECTED"): ("DISPATCH_REFUSED", ["NATIVE_DISPATCH_REJECTED"], "PERMITTED"),
    ("REJECTED", "UNKNOWN"): ("DISPATCH_REFUSED", ["NATIVE_DISPATCH_REJECTED"], "PERMITTED"),
    ("UNKNOWN", "NONE"): ("DISPATCH_RECORDED", ["DISPATCH_STATUS_UNKNOWN"], "DISPATCHED"),
    ("UNKNOWN", "ACCEPTED"): ("ACKNOWLEDGED", [], "DISPATCHED"),
    ("UNKNOWN", "REJECTED"): ("DISPATCH_RECORDED", ["DISPATCH_STATUS_UNKNOWN"], "DISPATCHED"),
    ("UNKNOWN", "UNKNOWN"): ("DISPATCH_RECORDED", ["DISPATCH_STATUS_UNKNOWN"], "DISPATCHED"),
}


def later_clock(base: dict, permitted: dict) -> dict:
    clock = available_clock("authority-clock", "2", "2026-09-10T04:35:00Z")
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-2",
        "kind": "CLOCK",
        "instance_id": permitted["state"]["instance_id"],
        "expected_state_revision": permitted["state"]["revision"],
        "expected_state_digest": permitted["state_digest"],
        "clock": clock,
        "activation_clocks": [],
    }

    def mutate(state: dict) -> None:
        state["clocks"].append(copy.deepcopy(clock))

    result = admitted_transition(
        permitted["state"],
        event,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]}],
        mutate=mutate,
    )
    return {**copy.deepcopy(permitted), "state": result["state"], "state_digest": result["state_digest"]}


def changed_request(permitted: dict) -> dict:
    native = copy.deepcopy(permitted["permit"]["native_request"])
    native["fields"][0]["value"]["value"] = "200"
    return native


def build() -> list[dict]:
    base = base_lifecycle()
    permitted = permitted_proposal(base)
    cases = []
    for attempt_status, acknowledgement_status in TABLE:
        disposition, reasons, occurrence_status = TABLE[(attempt_status, acknowledgement_status)]
        identifier = f"DM2-{attempt_status.lower()}-{acknowledgement_status.lower()}"
        event = dispatch_event(
            base,
            permitted,
            event_id=identifier,
            attempt_status=attempt_status,
            acknowledgement_status=acknowledgement_status,
        )
        cases.append(
            exact_case(
                identifier,
                "step",
                step_input(base, permitted["state"], event),
                dispatch_result(permitted, event, disposition=disposition, reasons=reasons, occurrence_status=occurrence_status),
                ["LIFE-009"],
                f"This is the exact timely matching-request dispatch-table cell for attempt {attempt_status} and acknowledgement {acknowledgement_status}.",
            )
        )

    direct = [
        ("D2-022", "SENT", "NONE", None, "DISPATCH_RECORDED", [], "DISPATCHED"),
        ("D2-023", "NOT_SENT", "NONE", changed_request(permitted), "DISPATCH_REFUSED", ["NATIVE_ARGUMENT_MISMATCH", "NATIVE_NOT_SENT"], "PERMITTED"),
        ("D2-025", "SENT", "ACCEPTED", None, "ACKNOWLEDGED", [], "DISPATCHED"),
        ("D2-153", "NOT_SENT", "NONE", changed_request(permitted), "DISPATCH_REFUSED", ["NATIVE_ARGUMENT_MISMATCH", "NATIVE_NOT_SENT"], "PERMITTED"),
        ("D2-154", "SENT", "NONE", changed_request(permitted), "DISPUTED", ["NATIVE_ARGUMENT_MISMATCH"], "BLOCKED_DISPUTE"),
        ("D2-183", "REJECTED", "NONE", changed_request(permitted), "DISPUTED", ["NATIVE_ARGUMENT_MISMATCH", "NATIVE_DISPATCH_REJECTED"], "BLOCKED_DISPUTE"),
    ]
    for case_id, attempt_status, acknowledgement_status, native, disposition, reasons, occurrence_status in direct:
        event = dispatch_event(
            base,
            permitted,
            event_id=f"dispatch-{case_id.lower()}",
            attempt_status=attempt_status,
            acknowledgement_status=acknowledgement_status,
            native_request=native,
        )
        cases.append(
            exact_case(
                case_id,
                "step",
                step_input(base, permitted["state"], event),
                dispatch_result(permitted, event, disposition=disposition, reasons=reasons, occurrence_status=occurrence_status),
                ["LIFE-009"],
                "The exact dispatch table is applied after adding the native-request match result. The complete attempt is retained under its stable attempt digest.",
            )
        )

    absent = dispatch_event(base, permitted, event_id="dispatch-absent-permit")
    absent["expected_state_revision"] = base["clock_result"]["state"]["revision"]
    absent["expected_state_digest"] = base["clock_result"]["state_digest"]
    cases.append(
        exact_case(
            "D2-024",
            "step",
            step_input(base, base["clock_result"]["state"], absent),
            stateful_refusal(base["clock_result"]["state"], "PREREQUISITE_MISSING"),
            ["LIFE-009"],
            "The supplied permit is internally complete but absent from the admitted work state. Dispatch prerequisite admission fails without retaining an attempt.",
        )
    )

    bad_attempt_digest = dispatch_event(base, permitted, event_id="dispatch-bad-request-digest", request_digest="sha256:" + "f" * 64)
    cases.append(
        exact_case(
            "D2-097",
            "step",
            step_input(base, permitted["state"], bad_attempt_digest),
            stateful_refusal(permitted["state"], "BINDING_MISMATCH"),
            ["LIFE-009"],
            "The supplied attempt request_digest differs from the digest of its exact instance, occurrence, interface, operation, and fields projection.",
        )
    )

    bad_connector = dispatch_event(base, permitted, event_id="dispatch-bad-connector", connector_digest="sha256:" + "f" * 64)
    cases.append(
        exact_case(
            "D2-166",
            "step",
            step_input(base, permitted["state"], bad_connector),
            stateful_refusal(permitted["state"], "BINDING_MISMATCH"),
            ["LIFE-009"],
            "The connector binding digest does not equal the domain-separated digest of its exact id and version.",
        )
    )

    at_expiry = later_clock(base, permitted)
    expired_not_sent = dispatch_event(base, at_expiry, event_id="dispatch-at-expiry-not-sent", attempt_status="NOT_SENT", attempted_at="2026-09-10T04:35:00Z", clock_revision="2")
    cases.append(
        exact_case(
            "D2-096",
            "step",
            step_input(base, at_expiry["state"], expired_not_sent),
            dispatch_result(at_expiry, expired_not_sent, disposition="DISPATCH_REFUSED", reasons=["NATIVE_NOT_SENT", "PERMIT_EXPIRED"], occurrence_status="PERMITTED"),
            ["LIFE-008", "LIFE-009"],
            "The attempt occurs at the permit's exclusive expiry. NOT_SENT remains safe, but dispatch is refused with both the table reason and expiry reason.",
        )
    )
    expired_sent = dispatch_event(base, at_expiry, event_id="dispatch-at-expiry-sent", attempt_status="SENT", attempted_at="2026-09-10T04:35:00Z", clock_revision="2")
    cases.append(
        exact_case(
            "D2-168",
            "step",
            step_input(base, at_expiry["state"], expired_sent),
            dispatch_result(at_expiry, expired_sent, disposition="DISPUTED", reasons=["PERMIT_EXPIRED"], occurrence_status="BLOCKED_DISPUTE"),
            ["LIFE-009", "LIFE-014"],
            "The exact request may have reached the connector at the exclusive expiry. The disqualified attempt is retained, blocks the active source and consumes the permit.",
        )
    )
    stale_clock = dispatch_event(base, permitted, event_id="dispatch-later-than-selected-clock", attempted_at="2026-09-10T04:35:00Z", clock_revision="1")
    cases.append(
        exact_case(
            "D2-218",
            "step",
            step_input(base, permitted["state"], stale_clock),
            stateful_refusal(permitted["state"], "CLOCK_INVALID"),
            ["LIFE-009", "LIFE-014"],
            "The selected retained clock is 04:30, while attempted_at claims 04:35. Timeline admission fails before the dispatch table.",
        )
    )
    before_issue = dispatch_event(base, permitted, event_id="dispatch-before-permit-clock", attempted_at="2026-09-10T04:29:59Z")
    cases.append(
        exact_case(
            "D2-221",
            "step",
            step_input(base, permitted["state"], before_issue),
            stateful_refusal(permitted["state"], "CLOCK_INVALID"),
            ["LIFE-009", "LIFE-014"],
            "The attempt predates the retained clock that issued the permit and therefore cannot be admitted as its dispatch.",
        )
    )

    null_clock = dispatch_event(base, permitted, event_id="dispatch-null-clock")
    null_clock["clock_revision"] = None
    cases.append(
        exact_case(
            "D2-210",
            "step",
            step_input(base, permitted["state"], null_clock),
            {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
            ["LIFE-009", "WCS2-012"],
            "DISPATCH_OBSERVED requires a natural clock revision. Null fails the closed event schema before state admission.",
        )
    )
    malformed_ack = dispatch_event(base, permitted, event_id="dispatch-malformed-ack", acknowledgement_status="ACCEPTED")
    malformed_ack["acknowledgement"]["reference"] = None
    malformed_ack["acknowledgement"]["observed_at"] = None
    cases.append(
        exact_case(
            "D2-219",
            "step",
            step_input(base, permitted["state"], malformed_ack),
            {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
            ["LIFE-009", "WCS2-012"],
            "A recorded ACCEPTED acknowledgement requires both a nonnull reference and whole-second observed_at. The event fails closed shape admission.",
        )
    )
    return cases


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "dispatch" / f"{case['id']}.json", case)
    print(json.dumps({"count": len(cases), "case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
