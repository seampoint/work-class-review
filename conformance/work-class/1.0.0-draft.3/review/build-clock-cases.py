#!/usr/bin/env python3
"""Build clock watermark and evidence-retention lifecycle cases."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_factory import admitted_transition, base_lifecycle, state_digest, stateful_refusal, step_input


GROUP = CASES / "clocks"


def clock(source: str, revision: str, status: str, observed_time: str | None) -> dict:
    return {
        "source": source,
        "revision": revision,
        "status": status,
        "observed_time": observed_time,
        "evidence_digest": digest(
            "clock-evidence",
            {"source": source, "revision": revision, "status": status, "observed_time": observed_time},
        ),
    }


def event(state: dict, selected_clock: dict, event_id: str) -> dict:
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "CLOCK",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "clock": copy.deepcopy(selected_clock),
        "activation_clocks": [],
    }


def accepted(state: dict, event_value: dict) -> dict:
    selected = event_value["clock"]

    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(selected))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    reasons = ["CLOCK_UNAVAILABLE"] if selected["status"] != "AVAILABLE" else []
    return admitted_transition(
        state,
        event_value,
        disposition="CLOCK_RECORDED",
        reason_codes=reasons,
        details=[{"kind": "CLOCK", "source": selected["source"], "revision": selected["revision"], "status": selected["status"]}],
        mutate=mutate,
    )


def write(case_id: str, base: dict, state: dict, event_value: dict, expected: dict, derivation: str, *, requirements: list[str] | None = None) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event_value), expected, requirements or ["LIFE-006", "LIFE-014"], derivation),
    )


def main() -> None:
    base = base_lifecycle()
    state = base["clock_result"]["state"]

    next_clock = clock("authority-clock", "2", "AVAILABLE", "2026-09-10T04:31:00Z")
    next_event = event(state, next_clock, "clock-d2-040")
    write(
        "D2-040",
        base,
        state,
        next_event,
        accepted(state, next_event),
        "The available sample advances authority-clock from revision 1 to 2 and moves time forward. No deadline is due, so the decision is CLOCK_RECORDED with an empty reason set.",
    )

    backwards = clock("authority-clock", "2", "AVAILABLE", "2026-09-10T04:29:59Z")
    backwards_event = event(state, backwards, "clock-d2-041")
    write(
        "D2-041",
        base,
        state,
        backwards_event,
        stateful_refusal(state, "CLOCK_INVALID"),
        "The new sample has a greater revision but an earlier available time than the retained source watermark. CLOCK_INVALID leaves the exact work state unchanged.",
    )

    unavailable = clock("deadline-clock", "1", "UNAVAILABLE", None)
    unavailable_event = event(state, unavailable, "clock-d2-042")
    write(
        "D2-042",
        base,
        state,
        unavailable_event,
        accepted(state, unavailable_event),
        "An unavailable clock sample has no observed time and therefore cannot satisfy or expire a deadline. It is retained as CLOCK_RECORDED with CLOCK_UNAVAILABLE and no expiry transition.",
    )

    first = clock("source-s", "5", "UNAVAILABLE", None)
    first_event = event(state, first, "clock-d2-268-unavailable")
    first_result = accepted(state, first_event)
    write(
        "C2-268-unavailable",
        base,
        state,
        first_event,
        first_result,
        "The first sample for source-s may establish revision 5 even though its time is unavailable. It advances the all-status revision watermark and records CLOCK_UNAVAILABLE.",
        requirements=["LIFE-014"],
    )

    reused = clock("source-s", "5", "AVAILABLE", "2026-09-10T04:32:00Z")
    reused_event = event(first_result["state"], reused, "clock-d2-268-reused")
    write(
        "C2-268-reused",
        base,
        first_result["state"],
        reused_event,
        stateful_refusal(first_result["state"], "CLOCK_INVALID"),
        "The available sample reuses the all-status revision watermark 5. CLOCK_INVALID preserves the unavailable sample and does not establish a time baseline.",
        requirements=["LIFE-014"],
    )

    recovered = clock("source-s", "6", "AVAILABLE", "2026-09-10T04:32:00Z")
    recovered_event = event(first_result["state"], recovered, "clock-d2-268-recovered")
    recovered_result = accepted(first_result["state"], recovered_event)
    write(
        "D2-268",
        base,
        first_result["state"],
        recovered_event,
        recovered_result,
        "After the intervening revision-5 reuse was refused and left no state change, revision 6 advances the all-status watermark. Because the earlier sample had no time, this available observation establishes the source's first valid time baseline and records CLOCK_RECORDED.",
    )

    print(json.dumps({"exact_case_ids": ["D2-040", "D2-041", "D2-042", "D2-268"], "supplementary_cases": 2}, indent=2))


if __name__ == "__main__":
    main()
