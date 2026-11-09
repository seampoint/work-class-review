#!/usr/bin/env python3
"""Build supplementary exact-restart controls after structured creation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

from corpus_common import CASES, exact_case, write_canonical_json
from fixture_factory import available_clock
from lifecycle_factory import admitted_transition, state_digest, step_input


PARALLEL = runpy.run_path(str(Path(__file__).with_name("build-parallel-entry-cases.py")))
FANOUT = runpy.run_path(str(Path(__file__).with_name("build-fanout-cases.py")))


GROUP = CASES / "structured-restart"


def neutral_clock(state: dict, event_id: str) -> dict:
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "CLOCK",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "clock": available_clock("restart-probe", "1", "2026-09-10T04:31:00Z"),
        "activation_clocks": [],
    }


def recorded_clock(state: dict, event: dict) -> dict:
    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(event["clock"]))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    return admitted_transition(
        state,
        event,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[
            {
                "kind": "CLOCK",
                "source": event["clock"]["source"],
                "revision": event["clock"]["revision"],
                "status": event["clock"]["status"],
            }
        ],
        mutate=mutate,
    )


def main() -> None:
    parallel_base, _permitted, parallel_dispatched, parallel_event = PARALLEL["setup"](
        "restart-parallel-created",
        ["branch-a", "branch-b"],
    )
    parallel_entry = PARALLEL["parallel_entry_result"](
        parallel_base,
        parallel_dispatched,
        parallel_event,
        ["branch-a", "branch-b"],
    )
    event = neutral_clock(parallel_entry["state"], "restart-parallel-clock")
    write_canonical_json(
        GROUP / "C2-restart-parallel-created.json",
        exact_case(
            "C2-restart-parallel-created",
            "step",
            step_input(parallel_base, parallel_entry["state"], event),
            recorded_clock(parallel_entry["state"], event),
            ["LIFE-012", "LIFE-019", "PAR-001"],
            "A fresh consumer receives the complete state returned by a two-branch split, including exact active occurrences, open obligations, counters, outcome, receipt, and replay preimages. All restart invariants hold, so an unrelated first clock source is admitted and recorded without changing the structured inventory.",
        ),
    )

    keys = [FANOUT["typed"]("IDENTITY", "card-802"), FANOUT["typed"]("IDENTITY", "card-803")]
    fanout_base, fanout_dispatched, fanout_event = FANOUT["setup"](
        "restart-fanout-created",
        keys,
        empty_behavior="ADVANCE_TO_JOIN",
    )
    fanout_entry = FANOUT["expansion_result"](
        fanout_base,
        fanout_dispatched,
        fanout_event,
        mode="NONEMPTY",
    )
    event = neutral_clock(fanout_entry["state"], "restart-fanout-clock")
    write_canonical_json(
        GROUP / "C2-restart-fanout-created.json",
        exact_case(
            "C2-restart-fanout-created",
            "step",
            step_input(fanout_base, fanout_entry["state"], event),
            recorded_clock(fanout_entry["state"], event),
            ["LIFE-012", "LIFE-019", "FAN-001"],
            "A fresh consumer receives the complete state returned by a two-object expansion, including the source-order frozen pass, exact object occurrences, obligation identities, counters, outcome, receipt, and replay preimages. Restart admission succeeds and the unrelated first clock source is recorded without changing the fan-out inventory.",
        ),
    )

    duplicate_keys = [FANOUT["typed"]("IDENTITY", "card-802"), FANOUT["typed"]("IDENTITY", "card-802")]
    stopped_base, stopped_dispatched, stopped_event = FANOUT["setup"](
        "restart-fanout-duplicate-stopped",
        duplicate_keys,
        empty_behavior="ADVANCE_TO_JOIN",
    )
    stopped = FANOUT["expansion_result"](
        stopped_base,
        stopped_dispatched,
        stopped_event,
        mode="DUPLICATE",
    )
    event = neutral_clock(stopped["state"], "restart-fanout-duplicate-clock")
    write_canonical_json(
        GROUP / "C2-restart-fanout-duplicate-stopped.json",
        exact_case(
            "C2-restart-fanout-duplicate-stopped",
            "step",
            step_input(stopped_base, stopped["state"], event),
            recorded_clock(stopped["state"], event),
            ["LIFE-012", "LIFE-019", "FAN-001"],
            "A fresh consumer receives the complete STOPPED state whose retained fan-out pass records the two equal object keys that caused FANOUT_SET_DUPLICATE. Duplicate keys are required evidence in this policy-stop state, not a definition-like state error. Restart admission succeeds and records an unrelated clock without changing the stopped pass.",
        ),
    )

    print(
        json.dumps(
            {
                "case_ids": [
                    "C2-restart-parallel-created",
                    "C2-restart-fanout-created",
                    "C2-restart-fanout-duplicate-stopped",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
