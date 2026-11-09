"""Rule-derived composite lifecycle and reservation fixtures for draft 2."""

from __future__ import annotations

import copy
from typing import Any, Callable

from corpus_common import digest
from lifecycle_factory import admitted_transition, base_lifecycle, proposal_permit
from reservation_fixture import (
    budget_result,
    fixture,
    host_and_event,
    registered_state,
    request as reservation_request,
    reservation_record,
    transition as reservation_transition,
)


def budget_lifecycle(
    *,
    instance_id: str = "case-1",
    definition_mutator: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base = base_lifecycle(
        shared_budget=True,
        instance_id=instance_id,
        definition_mutator=definition_mutator,
    )
    facts = fixture()
    facts["authority_a"] = copy.deepcopy(base["authority_input"])
    facts["authority_a_result"] = copy.deepcopy(base["authority_result"])

    completion = next(row for row in base["definition"]["steps"] if row["kind"] == "OPERATION")["completion"]
    facts["budget"]["contributor_classes"] = [base["definition"]["id"]]
    facts["budget"]["reservation_policy"]["settlement"] = {
        "provider": completion["effect_provider"],
        "source": completion["effect_source"],
    }
    facts["budget"]["reservation_policy"]["no_effect"] = {
        "provider": completion["no_effect_provider"],
        "source": completion["no_effect_source"],
    }
    budget_digest = digest("budget-definition", facts["budget"])
    authorization = facts["authorizations"][0]
    authorization["budget_digest"] = budget_digest
    authorization["work_class"] = base["definition"]["id"]
    authorization["work_class_digest"] = digest("authority-work-class", base["authority_input"]["work_class"])
    authorization["envelope_digest"] = digest("authority-envelope", base["authority_input"]["envelope"])
    authorization["step"] = base["proposal_event"]["occurrence"]["step_id"]
    authorization["authority_definition"] = {
        "schema": "seampoint.work-class/1.0.0-draft.3/authority-definition",
        **{
            key: copy.deepcopy(base["authority_input"][key])
            for key in ("source", "work_class", "envelope")
        },
    }
    facts["history"]["budget_digest"] = budget_digest
    return base, facts


def reserve_for_proposal(
    base: dict[str, Any],
    facts: dict[str, Any],
    registry_state: dict[str, Any],
    proposal: dict[str, Any],
    *,
    total: str = "950",
    decision: str = "RESERVED",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    registry_digest = digest("reservation-registry", registry_state["core"]["configuration"])
    reservation_event_id = digest(
        "lifecycle-reservation-event",
        {
            "instance_id": proposal["instance_id"],
            "lifecycle_event_id": proposal["event_id"],
            "lifecycle_event_kind": "PROPOSE",
            "reservation_event_kind": "RESERVE",
            "registry_digest": registry_digest,
        },
    )
    event, host = host_and_event(
        facts,
        "RESERVE",
        reservation_event_id,
        registry_state["core"]["revision"],
        {"authority": proposal["authority_input"], "histories": [facts["history"]]},
        event_clock=facts["clock"],
        administration=False,
    )
    core = copy.deepcopy(registry_state["core"])
    reservation = reservation_record(facts, "authority_a", reservation_event_id)
    if decision == "RESERVED":
        core["reservations"].append(reservation)
        core["reservations"].sort(key=lambda row: row["id"].encode("utf-8"))
    violated = decision == "WITHHELD"
    result = reservation_transition(
        registry_state,
        event,
        host,
        core,
        decision,
        reservation_id=reservation_event_id if decision == "RESERVED" else None,
        budgets=budget_result(facts, total, "VIOLATED" if violated else "SATISFIED"),
        authority_result=base["authority_result"],
        reasons=["BOUND_VIOLATED"] if violated else [],
    )
    request_value = reservation_request(registry_state, event, host)
    budget_input = {
        "registry_digest": registry_digest,
        "affected_anchors": ["license-spend"],
        "expected_revision": registry_state["core"]["revision"],
        "request": request_value,
    }
    budget_output = {
        "registry_digest": registry_digest,
        "affected_anchors": ["license-spend"],
        "result": result,
    }
    return budget_input, budget_output, reservation


def permitted_budget_proposal(
    base: dict[str, Any],
    proposal: dict[str, Any],
    budget_output: dict[str, Any],
) -> dict[str, Any]:
    before = base["clock_result"]["state"]
    reservation_result = budget_output["result"]
    permit = proposal_permit(base, proposal)
    permit_without_id = {key: copy.deepcopy(value) for key, value in permit.items() if key != "permit_id"}
    permit_without_id["budget_revisions"] = [
        {
            "registry_digest": budget_output["registry_digest"],
            "affected_anchors": copy.deepcopy(budget_output["affected_anchors"]),
            "revision": reservation_result["state"]["core"]["revision"],
            "reservation_id": reservation_result["receipt"]["reservation"],
            "receipt_digest": reservation_result["receipt_digest"],
        }
    ]
    permit = {"permit_id": digest("permit", permit_without_id), **permit_without_id}
    event_digest = digest("runtime-event", proposal)
    proposal_digest = digest("proposal", proposal)
    authority_result_digest = permit["authority_result_digest"]

    def mutate(next_state: dict[str, Any]) -> None:
        active = next(
            row
            for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] == proposal["occurrence"]["occurrence_id"]
        )
        active["status"] = "PERMITTED"
        next_state["total_actuations"] = str(int(next_state["total_actuations"]) + 1)
        counter = next(
            row for row in next_state["step_counters"]
            if row["step_id"] == proposal["occurrence"]["step_id"]
        )
        counter["actuations"] = str(int(counter["actuations"]) + 1)
        next_state["proposals"].append(
            {
                "event_id": proposal["event_id"],
                "event_digest": event_digest,
                "proposal_digest": proposal_digest,
                "occurrence_id": proposal["occurrence"]["occurrence_id"],
                "disposition": "PERMITTED",
                "permit_digest": permit["permit_id"],
                "authority_result_digest": authority_result_digest,
                "reservation_receipt_digests": [reservation_result["receipt_digest"]],
                "prior_permit_digest": None,
            }
        )
        next_state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
        next_state["permits"].append(copy.deepcopy(permit))
        next_state["permits"].sort(key=lambda row: row["permit_id"].encode("utf-8"))

    return admitted_transition(
        before,
        proposal,
        disposition="PERMITTED",
        reason_codes=[],
        details=[],
        permit=permit,
        budget_results=[budget_output],
        mutate=mutate,
    )


def withheld_budget_proposal(
    base: dict[str, Any],
    proposal: dict[str, Any],
    budget_output: dict[str, Any],
) -> dict[str, Any]:
    before = base["clock_result"]["state"]
    reservation_result = budget_output["result"]
    event_digest = digest("runtime-event", proposal)
    proposal_digest = digest("proposal", proposal)
    authority_result_digest = digest("authority-result", base["authority_result"])
    reasons = sorted(
        set(["BUDGET_WITHHELD", *reservation_result["receipt"]["reasons"]]),
        key=lambda value: value.encode("utf-8"),
    )

    def mutate(next_state: dict[str, Any]) -> None:
        next_state["proposals"].append(
            {
                "event_id": proposal["event_id"],
                "event_digest": event_digest,
                "proposal_digest": proposal_digest,
                "occurrence_id": proposal["occurrence"]["occurrence_id"],
                "disposition": "WITHHELD",
                "permit_digest": None,
                "authority_result_digest": authority_result_digest,
                "reservation_receipt_digests": [reservation_result["receipt_digest"]],
                "prior_permit_digest": None,
            }
        )
        next_state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))

    return admitted_transition(
        before,
        proposal,
        disposition="WITHHELD",
        reason_codes=reasons,
        details=[
            {
                "kind": "BUDGET",
                "registry_digest": budget_output["registry_digest"],
                "receipt_digest": reservation_result["receipt_digest"],
                "reasons": copy.deepcopy(reservation_result["receipt"]["reasons"]),
            }
        ],
        receipt_authority_result_digest=authority_result_digest,
        budget_results=[budget_output],
        mutate=mutate,
    )


def initial_budget_success(
    *,
    instance_id: str = "case-1",
    event_id: str = "proposal-1",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    base, facts = budget_lifecycle(instance_id=instance_id)
    proposal = copy.deepcopy(base["proposal_event"])
    proposal["event_id"] = event_id
    registry_state = registered_state(facts)
    budget_input, budget_output, _ = reserve_for_proposal(base, facts, registry_state, proposal)
    proposal["budget_inputs"] = [budget_input]
    expected = permitted_budget_proposal(base, proposal, budget_output)
    return base, facts, proposal, expected
