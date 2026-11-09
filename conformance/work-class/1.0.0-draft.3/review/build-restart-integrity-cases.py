#!/usr/bin/env python3
"""Build restart admission cases for internally inconsistent retained state."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock
from lifecycle_factory import (
    base_lifecycle,
    permitted_proposal,
    state_digest,
    stateful_refusal,
    step_input,
)


RENEWAL = runpy.run_path(str(Path(__file__).with_name("build-renewal-cases.py")))
advance_clock = RENEWAL["advance_clock"]
renewal_event = RENEWAL["renewal_event"]
renewal_result = RENEWAL["renewal_result"]


GROUP = CASES / "restart-integrity"


def add_deadline(definition: dict) -> None:
    definition["profile"] = "DEADLINES"
    definition["deadlines"] = [
        {
            "id": "issue-deadline",
            "step_id": "issue",
            "clock_source": "work-clock",
            "due": {"kind": "ELAPSED_DURATION", "value": "1", "unit": "HOUR"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "terminal",
        }
    ]
    definition["relationships"].append(
        {"kind": "EXPIRY", "from": "issue", "to": "terminal", "deadline_ref": "issue-deadline"}
    )
    definition["relationships"].sort(key=canonical_bytes)


def neutral_clock_event(state: dict, event_id: str, revision: str = "1") -> dict:
    selected = available_clock("restart-probe", revision, "2026-09-10T04:36:00Z")
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "CLOCK",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "clock": selected,
        "activation_clocks": [],
    }


def emit(case_id: str, base: dict, state: dict, event: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(
            case_id,
            "step",
            step_input(base, state, event),
            stateful_refusal(state, "STATE_INVALID"),
            [],
            derivation,
        ),
    )


from checkpoint_reseal import reseal_last_transition


def main() -> None:
    initial = available_clock("work-clock", "1", "2026-09-10T04:00:00Z")
    deadline_base = base_lifecycle(definition_mutator=add_deadline, initial_clocks=[initial])
    damaged_deadline = copy.deepcopy(deadline_base["clock_result"]["state"])
    damaged_deadline["deadlines"][0]["activation_instant"] = "2026-09-10T04:00:01Z"
    reseal_last_transition(damaged_deadline)
    event = neutral_clock_event(damaged_deadline, "restart-d2-125")
    emit(
        "D2-125",
        deadline_base,
        damaged_deadline,
        event,
        "The persisted activation instant was changed without changing the activation digest or the copied activation-clock evidence. The last receipt and replay are recommitted to the changed state, so no stale commitment is the fault. Restart recomputation rejects the internally inconsistent deadline state before applying the otherwise valid clock event.",
    )

    base = base_lifecycle()
    first = permitted_proposal(base)
    expired = advance_clock(first, event_id="clock-before-fork")
    renewal, authority_result = renewal_event(base, expired, "fork-base")
    renewed = renewal_result(base, expired, renewal, authority_result)
    # A second renewal recorded as admitted against the same prior permit, built by the same transition
    # as the first, so every proposal, permit, receipt, replay and transaction commitment is consistent
    # and the forked chain is the only defect.
    second_holder = {**expired, "state": renewed["state"], "state_digest": renewed["state_digest"]}
    second, second_authority = renewal_event(base, second_holder, "fork-second")
    forked = renewal_result(base, second_holder, second, second_authority)
    assert forked["permit"]["permit_id"] != renewed["permit"]["permit_id"]
    assert forked["permit"]["supersedes_permit_digest"] == first["permit"]["permit_id"]
    forked_state = forked["state"]
    event = neutral_clock_event(forked_state, "restart-d2-187")
    emit(
        "D2-187",
        base,
        forked_state,
        event,
        "The retained history records two admitted renewals of the same permitted occurrence, and both new permits name the same prior permit as superseded. Each renewal carries its own proposal record, receipt, replay and transaction commitment, all consistent, so the only defect is the chain itself: LIFE-019 requires one finite linear permit chain per occurrence in which every permit has at most one immediate successor and exactly one unsuperseded head exists while the occurrence is PERMITTED, and names a fork or several heads STATE_INVALID. Restart returns STATE_INVALID before applying the event.",
    )

    print(json.dumps({"case_ids": ["D2-125", "D2-187"]}, indent=2))


if __name__ == "__main__":
    main()
