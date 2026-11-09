#!/usr/bin/env python3
"""Build exact effect-versus-expiry ordering cases for one activity deadline."""

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
    effect_result,
    governed_effect_event,
    governed_native_evidence,
    permitted_proposal,
    step_input,
)


GROUP = CASES / "deadline-order"


def add_deadline(definition: dict) -> None:
    definition["profile"] = "DEADLINES"
    definition["deadlines"] = [
        {
            "id": "issue-deadline",
            "step_id": "issue",
            "clock_source": "work-clock",
            "due": {"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-10T04:31:00Z"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "terminal",
        }
    ]
    definition["relationships"].append(
        {"kind": "EXPIRY", "from": "issue", "to": "terminal", "deadline_ref": "issue-deadline"}
    )
    definition["relationships"].sort(key=canonical_bytes)


def setup() -> tuple[dict, dict, dict]:
    initial = available_clock("work-clock", "1", "2026-09-10T04:00:00Z")
    base = base_lifecycle(definition_mutator=add_deadline, initial_clocks=[initial])
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-deadline", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    return base, permitted, dispatched


def clock_event(state: dict, event_id: str) -> dict:
    selected = available_clock("work-clock", "2", "2026-09-10T04:31:00Z")
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "CLOCK",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": digest_state(state),
        "clock": selected,
        "activation_clocks": [],
    }


def digest_state(state: dict) -> str:
    projected = copy.deepcopy(state)
    for replay in projected["replays"]:
        replay.pop("transaction_digest", None)
    return digest("work-state", projected)


def expire(base: dict, state: dict, event: dict) -> dict:
    selected = event["clock"]
    event_digest = digest("runtime-event", event)
    deadline = next(row for row in state["deadlines"] if row["deadline_id"] == "issue-deadline")
    active = next(row for row in state["active"] if row["occurrence"]["occurrence_id"] == deadline["occurrence_id"])
    relationship = next(row for row in base["definition"]["relationships"] if row["kind"] == "EXPIRY")
    relationship_digest = digest("relationship", relationship)

    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(selected))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        next_state["active"] = [
            row for row in next_state["active"] if row["occurrence"]["occurrence_id"] != active["occurrence"]["occurrence_id"]
        ]
        next_state["completed"].append(
            {
                "occurrence": copy.deepcopy(active["occurrence"]),
                "disposition": "EXPIRED",
                "evidence_digest": selected["evidence_digest"],
                "occurred_at": selected["observed_time"],
                "route_label": None,
                "selected_relationship_digest": relationship_digest,
                "late": False,
            }
        )
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        target = next(row for row in next_state["deadlines"] if row["deadline_id"] == "issue-deadline")
        target["status"] = "EXPIRED"
        target["expiry_event_digest"] = event_digest
        next_state["status"] = "COMPLETE"

    return admitted_transition(
        state,
        event,
        disposition="EXPIRED",
        reason_codes=[],
        details=[
            {"kind": "CLOCK", "source": selected["source"], "revision": selected["revision"], "status": selected["status"]},
            {"kind": "DEADLINE", "deadline_ids": ["issue-deadline"], "reasons": []},
            {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []},
        ],
        mutate=mutate,
    )


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def late_effect(base: dict, permitted: dict, expired: dict, case_id: str) -> tuple[dict, dict]:
    evidence = governed_native_evidence(
        base,
        permitted,
        expired,
        evidence_id="evidence-" + case_id.lower(),
        event_time="2026-09-10T04:30:30Z",
        observed_at="2026-09-10T04:31:01Z",
    )
    event = governed_effect_event(permitted, expired, evidence, event_id="effect-" + case_id.lower())
    expected = effect_result(
        base,
        permitted,
        expired,
        event,
        classification="LATE_MATCHED",
        disposition="OUTCOME_RETAINED",
        reason_codes=["LATE_EFFECT"],
        occurrence_status=None,
        disputed=False,
    )
    return event, expected


def main() -> None:
    base, permitted, dispatched = setup()

    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-before-d2-043",
        event_time="2026-09-10T04:30:59Z",
        observed_at="2026-09-10T04:30:59Z",
    )
    effect_event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-before-d2-043")
    completed = effect_result(
        base,
        permitted,
        dispatched,
        effect_event,
        classification="MATCHED",
        disposition="COMPLETED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=True,
    )
    write_canonical_json(
        GROUP / "C2-043-effect.json",
        exact_case(
            "C2-043-effect",
            "step",
            step_input(base, dispatched["state"], effect_event),
            completed,
            ["LIFE-014", "LIFE-015"],
            "The matching effect commits one second before the AT_OR_AFTER due instant. Completion discharges the occurrence's pending deadline and reaches terminal.",
        ),
    )
    after_completion_clock = clock_event(completed["state"], "clock-d2-043")

    def retain_clock(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(after_completion_clock["clock"]))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    expected = admitted_transition(
        completed["state"],
        after_completion_clock,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[
            {
                "kind": "CLOCK",
                "source": after_completion_clock["clock"]["source"],
                "revision": after_completion_clock["clock"]["revision"],
                "status": after_completion_clock["clock"]["status"],
            }
        ],
        mutate=retain_clock,
    )
    emit(
        "D2-043",
        base,
        completed["state"],
        after_completion_clock,
        expected,
        "The preceding effect already completed the occurrence and discharged its deadline. The equal-to-due clock is retained as CLOCK_RECORDED and cannot expire or reroute completed work.",
    )

    expiry_event = clock_event(dispatched["state"], "clock-before-d2-044")
    expired = expire(base, dispatched["state"], expiry_event)
    write_canonical_json(
        GROUP / "C2-044-expiry.json",
        exact_case(
            "C2-044-expiry",
            "step",
            step_input(base, dispatched["state"], expiry_event),
            expired,
            ["LIFE-012", "LIFE-014"],
            "The AT_OR_AFTER predicate is satisfied at equality. The clock and expiry commit, the occurrence closes as EXPIRED, and the declared expiry route reaches terminal.",
        ),
    )
    event, expected = late_effect(base, permitted, expired, "D2-044")
    emit(
        "D2-044",
        base,
        expired["state"],
        event,
        expected,
        "The due clock committed first. Later exact evidence is retained as LATE_MATCHED with LATE_EFFECT, while the completed EXPIRED occurrence, discharged route and terminal instance remain unchanged.",
    )

    second_expiry_event = clock_event(dispatched["state"], "clock-before-d2-035")
    second_expired = expire(base, dispatched["state"], second_expiry_event)
    event, expected = late_effect(base, permitted, second_expired, "D2-035")
    emit(
        "D2-035",
        base,
        second_expired["state"],
        event,
        expected,
        "The exact effect follows a retained deadline expiry. It is kept as LATE_MATCHED and does not reopen the expired occurrence, alter the expiry route, or create a new permission.",
    )

    print(json.dumps({"exact_case_ids": ["D2-035", "D2-043", "D2-044"], "supplementary_cases": 2}, indent=2))


if __name__ == "__main__":
    main()
