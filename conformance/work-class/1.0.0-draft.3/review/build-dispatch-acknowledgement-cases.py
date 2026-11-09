#!/usr/bin/env python3
"""Build exact acknowledgement-update cases from lifecycle dispatch rules."""

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
    step_input,
)


GROUP = CASES / "dispatch-acknowledgement"


def scenario(case_id: str, prior_acknowledgement: str) -> dict:
    base = base_lifecycle()
    permitted = permitted_proposal(base)
    first_event = dispatch_event(
        base,
        permitted,
        event_id="dispatch-before-" + case_id.lower(),
        attempt_status="SENT",
        acknowledgement_status=prior_acknowledgement,
    )
    first_result = dispatch_result(
        permitted,
        first_event,
        disposition="DISPATCH_RECORDED",
        reasons=[] if prior_acknowledgement == "NONE" else ["DISPATCH_STATUS_UNKNOWN"],
        occurrence_status="DISPATCHED",
    )
    selected_clock = available_clock("authority-clock", "2", "2026-09-10T04:30:01Z")
    clock_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-before-" + case_id.lower(),
        "kind": "CLOCK",
        "instance_id": first_result["state"]["instance_id"],
        "expected_state_revision": first_result["state"]["revision"],
        "expected_state_digest": first_result["state_digest"],
        "clock": selected_clock,
        "activation_clocks": [],
    }

    def retain_clock(state: dict) -> None:
        state["clocks"].append(copy.deepcopy(selected_clock))
        state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    clock_result = admitted_transition(
        first_result["state"],
        clock_event,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[{"kind": "CLOCK", "source": selected_clock["source"], "revision": selected_clock["revision"], "status": selected_clock["status"]}],
        mutate=retain_clock,
    )
    update = copy.deepcopy(first_event)
    update["event_id"] = "acknowledge-" + case_id.lower()
    update["expected_state_revision"] = clock_result["state"]["revision"]
    update["expected_state_digest"] = clock_result["state_digest"]
    update["clock_revision"] = "2"
    update["acknowledgement"] = {
        "status": "ACCEPTED",
        "reference": "accepted-acknowledgement-" + case_id.lower(),
        "observed_at": "2026-09-10T04:30:01Z",
    }
    expected = dispatch_result(
        {"state": clock_result["state"], "permit": permitted["permit"]},
        update,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    return exact_case(
        case_id,
        "step",
        step_input(base, clock_result["state"], update),
        expected,
        [],
        (
            "The new event retains the exact permit, native request, connector and attempt fields, so its dispatch-attempt digest equals the earlier record. "
            f"An admitted clock at the acknowledgement time supplies the selected revision. The update changes the retained {prior_acknowledgement} acknowledgement to the first timely ACCEPTED acknowledgement under a new complete dispatch digest, leaves the occurrence DISPATCHED, and records ACKNOWLEDGED."
        ),
    )


def main() -> None:
    cases = [scenario("D2-127", "UNKNOWN"), scenario("D2-257", "NONE")]
    for case in cases:
        write_canonical_json(GROUP / f"{case['id']}.json", case)
    print(json.dumps({"case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
