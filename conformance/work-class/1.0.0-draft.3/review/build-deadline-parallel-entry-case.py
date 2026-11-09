#!/usr/bin/env python3
"""Build a deadline expiry that enters structured parallel work."""

from __future__ import annotations

import copy
import json

from composition_fixture import add_authority_operations, parallel_definition
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock, occurrence
from lifecycle_factory import admitted_transition, base_lifecycle, dispatch_event, dispatch_result, permitted_proposal, step_input


GROUP = CASES / "deadline-parallel-entry"
BRANCHES = ["branch-a", "branch-b"]


def definition(definition_value: dict) -> None:
    parallel_definition(BRANCHES)(definition_value)
    definition_value["relationships"] = [
        row for row in definition_value["relationships"]
        if not (row["kind"] == "SEQUENCE" and row["from"] == "issue" and row["to"] == "parallel-split")
    ]
    definition_value["relationships"].extend(
        [
            {"kind": "SEQUENCE", "from": "issue", "to": "terminal"},
            {"kind": "EXPIRY", "from": "issue", "to": "parallel-split", "deadline_ref": "issue-deadline"},
        ]
    )
    definition_value["relationships"].sort(key=canonical_bytes)
    definition_value["deadlines"] = [
        {
            "id": "issue-deadline",
            "step_id": "issue",
            "clock_source": "work-clock",
            "due": {"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-10T04:31:00Z"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "parallel-split",
        }
    ]


def branch_rows(base: dict, source: dict, event: dict) -> list[tuple[dict, dict]]:
    rows = []
    event_digest = digest("runtime-event", event)
    for index, step_id in enumerate(BRANCHES):
        branch_id = "branch-" + str(index + 1)
        occurrence_value = occurrence(
            base["definition_digest"],
            source["instance_id"],
            step_id,
            "1",
            [source["occurrence_id"]],
            [
                {
                    "kind": "BRANCH",
                    "construct_id": "parallel-1",
                    "pass": "1",
                    "branch_id": branch_id,
                    "object_key": None,
                }
            ],
        )
        subject = {
            "kind": "PARALLEL_BRANCH",
            "construct_id": "parallel-1",
            "pass": "1",
            "source_occurrence_ids": [source["occurrence_id"]],
            "branch_id": branch_id,
            "object_key": None,
            "join_step_id": "parallel-join",
        }
        operation = next(row["operation"] for row in base["definition"]["steps"] if row["id"] == step_id)
        obligation = {
            "obligation_id": digest("obligation", subject),
            **subject,
            "creation_event_digest": event_digest,
            "status": "OPEN",
            "expected_occurrence_id": occurrence_value["occurrence_id"],
            "required_operation": operation,
            "waiting_on": None,
            "completion_basis": None,
        }
        rows.append((occurrence_value, obligation))
    return rows


def expected(base: dict, state: dict, event: dict) -> dict:
    selected_clock = event["clock"]
    event_digest = digest("runtime-event", event)
    source = next(row["occurrence"] for row in state["active"] if row["occurrence"]["step_id"] == "issue")
    expiry = next(row for row in base["definition"]["relationships"] if row["kind"] == "EXPIRY")
    expiry_digest = digest("relationship", expiry)
    children = branch_rows(base, source, event)

    def mutate(next_state: dict) -> None:
        next_state["clocks"].append(copy.deepcopy(selected_clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
        next_state["active"] = [
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] != source["occurrence_id"]
        ]
        next_state["completed"].append(
            {
                "occurrence": copy.deepcopy(source),
                "disposition": "EXPIRED",
                "evidence_digest": selected_clock["evidence_digest"],
                "occurred_at": selected_clock["observed_time"],
                "route_label": None,
                "selected_relationship_digest": expiry_digest,
                "late": False,
            }
        )
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        deadline = next(row for row in next_state["deadlines"] if row["deadline_id"] == "issue-deadline")
        deadline["status"] = "EXPIRED"
        deadline["expiry_event_digest"] = event_digest
        for occurrence_value, obligation in children:
            next_state["active"].append(
                {
                    "occurrence": copy.deepcopy(occurrence_value),
                    "activation_event_digest": event_digest,
                    "status": "ACTIVE",
                    "deadline_ids": [],
                }
            )
            next_state["obligations"].append(copy.deepcopy(obligation))
            counter = next(row for row in next_state["step_counters"] if row["step_id"] == occurrence_value["step_id"])
            counter["activations"] = str(int(counter["activations"]) + 1)
        next_state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        next_state["obligations"].sort(key=lambda row: row["obligation_id"].encode("utf-8"))
        next_state["total_activations"] = str(int(next_state["total_activations"]) + len(children))

    return admitted_transition(
        state,
        event,
        disposition="EXPIRED",
        reason_codes=[],
        details=[
            {"kind": "CLOCK", "source": selected_clock["source"], "revision": selected_clock["revision"], "status": selected_clock["status"]},
            {"kind": "DEADLINE", "deadline_ids": ["issue-deadline"], "reasons": []},
            {"kind": "ROUTE", "relationship_digests": [expiry_digest], "construct_ids": ["parallel-1"]},
        ],
        mutate=mutate,
    )


def main() -> None:
    initial_clock = available_clock("work-clock", "1", "2026-09-10T04:30:00Z")
    base = base_lifecycle(
        authority_mutator=add_authority_operations(BRANCHES),
        definition_mutator=definition,
        initial_clocks=[initial_clock],
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-before-d2-239", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    clock = available_clock("work-clock", "2", "2026-09-10T04:31:00Z")
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-d2-239",
        "kind": "CLOCK",
        "instance_id": dispatched["state"]["instance_id"],
        "expected_state_revision": dispatched["state"]["revision"],
        "expected_state_digest": dispatched["state_digest"],
        "clock": clock,
        "activation_clocks": [],
    }
    write_canonical_json(
        GROUP / "D2-239.json",
        exact_case(
            "D2-239",
            "step",
            step_input(base, dispatched["state"], event),
            expected(base, dispatched["state"], event),
            [],
            "The accepted work-clock sample satisfies the root AT_OR_AFTER deadline and selects its exact EXPIRY relationship into parallel-split. Complete structural preflight succeeds. The clock transition closes the root as EXPIRED and atomically creates the two source-ordered branch occurrences and their complete OPEN obligation inventory, each bound to the expired root and the CLOCK event digest.",
        ),
    )
    print(json.dumps({"case_ids": ["D2-239"]}, indent=2))


if __name__ == "__main__":
    main()
