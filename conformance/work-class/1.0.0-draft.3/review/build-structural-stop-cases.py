#!/usr/bin/env python3
"""Build exact effect-driven successor preflight stop vectors."""

from __future__ import annotations

import copy
import json

from composition_fixture import add_authority_operations
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    governed_outcome,
    permitted_proposal,
    step_input,
)


GROUP = CASES / "structural-stops"


def linear_successor(definition: dict) -> None:
    definition["relationships"] = [
        {"kind": "SEQUENCE", "from": definition["root"], "to": "successor"},
        {"kind": "SEQUENCE", "from": "successor", "to": "terminal"},
    ]


def limit_definition(definition: dict) -> None:
    linear_successor(definition)
    definition["limits"]["maximum_activations"] = "1"


def deadline_definition(definition: dict) -> None:
    linear_successor(definition)
    definition["profile"] = "DEADLINES"
    definition["deadlines"] = [
        {
            "id": "successor-deadline",
            "step_id": "successor",
            "clock_source": "deadline-clock",
            "due": {"kind": "ELAPSED_DURATION", "value": "60", "unit": "SECOND"},
            "boundary": "AT_OR_AFTER",
            "expiry_target": "terminal",
        }
    ]
    definition["relationships"].append(
        {"kind": "EXPIRY", "from": "successor", "to": "terminal", "deadline_ref": "successor-deadline"}
    )


def setup(definition_mutator) -> tuple[dict, dict, dict]:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(["successor"]),
        definition_mutator=definition_mutator,
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-before-structural-stop", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-structural-stop")
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-structural-stop")
    return base, dispatched, event


def stop_result(
    base: dict,
    dispatched: dict,
    event: dict,
    *,
    reason: str,
    limit_kind: str = "ACTIVATIONS",
) -> dict:
    source = event["permit"]["occurrence"]
    relationship = next(
        row for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == source["step_id"]
    )
    relationship_digest = digest("relationship", relationship)
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)

    def mutate(state: dict) -> None:
        state["status"] = "STOPPED"
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active_index = next(
            index for index, row in enumerate(state["active"])
            if row["occurrence"]["occurrence_id"] == source["occurrence_id"]
        )
        state["active"].pop(active_index)
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(source),
                "disposition": "SUCCEEDED",
                "evidence_digest": digest("native-evidence", event["native_evidence"]),
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": relationship_digest,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))

    details = [{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]}]
    if reason == "ACTIVATION_CLOCK_UNAVAILABLE":
        details.append(
            {
                "kind": "DEADLINE",
                "deadline_ids": ["successor-deadline"],
                "reasons": ["ACTIVATION_CLOCK_UNAVAILABLE"],
            }
        )
    details.append({"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []})
    if reason == "LIMIT_EXCEEDED":
        if limit_kind == "STEP_OCCURRENCES":
            limit = "0"
            current = "1"
        else:
            limit = "1"
            current = "2"
        details.append(
            {
                "kind": "LIMIT",
                "limit_kind": limit_kind,
                "limit": limit,
                "current": current,
                "step_id": "successor",
                "relationship_digest": relationship_digest,
            }
        )
    return admitted_transition(
        dispatched["state"],
        event,
        disposition="STOPPED",
        reason_codes=[reason],
        details=details,
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def emit(case_id: str, base: dict, dispatched: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, dispatched["state"], event), expected, [], derivation),
    )


def main() -> None:
    base, dispatched, event = setup(deadline_definition)
    event["event_id"] = "effect-d2-108"
    event["native_evidence"]["evidence_id"] = "evidence-d2-108"
    emit(
        "D2-108",
        base,
        dispatched,
        event,
        stop_result(base, dispatched, event, reason="ACTIVATION_CLOCK_UNAVAILABLE"),
        "The first exact matching effect selects the ordinary sequence relationship to successor. That step has an elapsed deadline on deadline-clock, but the state retains no available sample for that source and the event cannot supply one. The transition retains the effect, closes the source occurrence, records the selected route and deadline reason, creates no successor, and stops the instance.",
    )

    base, dispatched, event = setup(limit_definition)
    event["event_id"] = "effect-d2-122"
    event["native_evidence"]["evidence_id"] = "evidence-d2-122"
    emit(
        "D2-122",
        base,
        dispatched,
        event,
        stop_result(base, dispatched, event, reason="LIMIT_EXCEEDED"),
        "The matching effect selects the ordinary unlabeled sequence relationship to successor. The root already accounts for one activation, so creating successor would raise total activations to two against maximum one. The transition retains the effect and route, closes the source occurrence, creates no successor, and records EFFECT, ROUTE, and LIMIT details in fixed order.",
    )

    print(json.dumps({"case_ids": ["D2-108", "D2-122"]}, indent=2))


if __name__ == "__main__":
    main()
