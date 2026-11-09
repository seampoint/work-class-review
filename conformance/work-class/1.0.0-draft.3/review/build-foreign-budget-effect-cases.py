#!/usr/bin/env python3
"""Build budget-backed foreign-effect vectors from LIFE-010, RES-007 and RES-WIRE-003.

A foreign effect has no permit or dispatch binding, so when its step is budget-bearing the
consumer reconstructs the embedded SETTLE transition entirely from the reservation and the
native evidence rather than from an admitted dispatch record. `build-foreign-effect-cases.py`
covers the authority-only branch only (empty shared_budgets); this batch covers the
budget-bearing branch.
"""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_budget_fixture import initial_budget_success
from lifecycle_factory import admitted_transition, state_digest, step_input, stateful_refusal
from reservation_fixture import effect_record, host_and_event, request as reservation_request, transition as reservation_transition


GROUP = CASES / "foreign-budget-effects"
REGISTRY_CLOCK_INSTANT = "2026-09-10T04:30:00Z"
REGISTRY_CLOCK_REVISION = "1"


def attributed_request(base: dict, permit: dict) -> dict:
    return {
        "work_class": base["definition"]["id"],
        "instance": permit["instance_id"],
        "occurrence": permit["occurrence"]["occurrence_id"],
        "step": permit["occurrence"]["step_id"],
        "operation": permit["native_request"]["operation"],
        "interface": permit["native_request"]["interface"],
        "fields": copy.deepcopy(permit["native_request"]["fields"]),
    }


def foreign_evidence(case_id: str, attributed: dict, permit: dict) -> dict:
    lower = case_id.lower()
    actual_fields = sorted(
        copy.deepcopy(permit["native_request"]["fields"])
        + [{"name": "status", "value": {"type_ref": "STRING", "value": "ISSUED"}}],
        key=lambda row: row["name"].encode("utf-8"),
    )
    return {
        "evidence_id": f"evidence-{lower}",
        "native_operation_id": f"foreign-native-operation-{lower}",
        "provider": "card-provider",
        "source": "card-system",
        "record_type": "card-result",
        "record_digest": digest("provider-native-record", {"record": case_id}),
        "evidence_ref": f"evidence-ref-{lower}",
        "attributed_request": attributed,
        "native_request_digest": digest("native-request", attributed),
        "status": "EFFECT_ESTABLISHED",
        "actual_fields": actual_fields,
        "collections": [],
        "event_time": REGISTRY_CLOCK_INSTANT,
        "observed_at": REGISTRY_CLOCK_INSTANT,
        "rules_out_past_and_future_effects": False,
    }


def retained_native_request(reservation_row: dict) -> dict:
    """The reservation's exact retained native request: its authority proposal, projected."""
    request = copy.deepcopy(reservation_row["authority"]["proposal"])
    for key in ("schema", "work_class_digest", "executor"):
        request.pop(key, None)
    return request


def foreign_event(state: dict, permit: dict, evidence: dict, reservation_id: str | None, budget_input: dict | None) -> dict:
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": evidence["evidence_id"].replace("evidence-", "effect-"),
        "kind": "EFFECT_OBSERVED",
        "instance_id": permit["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "permit": None,
        "dispatch_digest": None,
        "native_evidence": evidence,
        "completion_authorization": None,
        "reservation_id": reservation_id,
        "affected_budget_anchors": ["license-spend"] if budget_input is not None else [],
        "budget_inputs": [budget_input] if budget_input is not None else [],
        "clock_revision": REGISTRY_CLOCK_REVISION if budget_input is not None else None,
        "activation_clocks": [],
    }


def foreign_settle_transition(
    facts: dict, registry_state: dict, reservation_id: str, event_id: str,
    *, attributed: dict, evidence: dict, retained_request: dict, reservation_status: str | None,
    reason: str,
) -> tuple[dict, dict]:
    """LIFE-010's foreign-branch embedding: exactly one SETTLE/EFFECT transition.

    `request` is the reservation's exact retained native request for a known reservation, or
    the event's attributed request for an unknown one. `observed_request` is the attributed
    request's identity fields with the evidence's actual fields, because the record is
    temporally consistent. `completion_mismatch` is always true with `UNEXPECTED_EFFECT`,
    which prevents a foreign record from ever being read as an authorized settlement.
    """
    registry_digest = digest("reservation-registry", registry_state["core"]["configuration"])
    embedded_id = digest(
        "lifecycle-reservation-event",
        {
            "instance_id": attributed["instance"], "lifecycle_event_id": event_id,
            "lifecycle_event_kind": "EFFECT_OBSERVED", "reservation_event_kind": "SETTLE",
            "registry_digest": registry_digest,
        },
    )
    # LIFE-010 (D4): the observed request takes its fields through the step's completion bindings, which
    # bind each request field to the evidence field of the same name here; the declared status field is
    # ignored. Every bound field is present and well typed, so the record is projectable.
    bound_fields = {row["name"] for row in attributed["fields"]}
    observed_request = {
        "work_class": attributed["work_class"], "instance": attributed["instance"],
        "occurrence": attributed["occurrence"], "step": attributed["step"],
        "operation": attributed["operation"], "interface": attributed["interface"],
        "fields": [copy.deepcopy(row) for row in evidence["actual_fields"] if row["name"] in bound_fields],
    }
    native = {
        "id": evidence["evidence_id"], "provider": evidence["provider"], "source": evidence["source"],
        "reservation": reservation_id, "outcome": "EFFECT", "request": retained_request,
        "effect_id": evidence["native_operation_id"], "occurred_at": evidence["event_time"],
        "rules_out_past_and_future_effects": False, "evidence_ref": evidence["evidence_ref"],
        "observed_request": observed_request, "actual_fields": copy.deepcopy(evidence["actual_fields"]),
        "collections": [], "completion_mismatch": True, "mismatch_reason": "UNEXPECTED_EFFECT",
    }
    event, host = host_and_event(
        facts, "SETTLE", embedded_id, registry_state["core"]["revision"],
        {"native": native, "histories": [facts["history"]]},
        event_clock=facts["clock"], administration=None,
    )
    # RES-WIRE-003 (D4): a known reservation's projectable unexpected EFFECT blocks the sorted unique
    # union of its original reserved keys and the projected keys; the projected fields equal the
    # reserved request here, so the union is the reservation's own contribution keys. An unknown
    # reservation has no retained binding to project through and blocks the anchor with one null key.
    core = copy.deepcopy(registry_state["core"])
    blocked = [{"anchor": "license-spend", "key": None}]
    if reservation_status is not None:
        for reservation in core["reservations"]:
            if reservation["id"] == reservation_id:
                reservation["status"] = reservation_status
                blocked = [{"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation["contributions"]]
    core["effects"].append(effect_record(native, "DISPUTED", reason, blocked))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    result = reservation_transition(
        registry_state, event, host, core, "EFFECT_DISPUTED",
        reservation_id=reservation_id, reasons=[reason],
    )
    budget_input = {
        "registry_digest": registry_digest,
        "affected_anchors": ["license-spend"],
        "expected_revision": registry_state["core"]["revision"],
        "request": reservation_request(registry_state, event, host),
    }
    budget_output = {"registry_digest": registry_digest, "affected_anchors": ["license-spend"], "result": result}
    return budget_input, budget_output


def foreign_budget_result(state: dict, event: dict, evidence: dict, budget_output: dict, *, reason: str) -> dict:
    receipt_digest = budget_output["result"]["receipt_digest"]
    outcome = {
        "kind": "FOREIGN", "event_id": event["event_id"], "event_digest": digest("runtime-event", event),
        "permit_digest": None, "dispatch_digest": None, "dispatch_attempt_digest": None,
        "native_evidence": copy.deepcopy(evidence), "classification": "FOREIGN",
        "affected_budget_anchors": ["license-spend"], "reservation_receipt_digests": [receipt_digest],
        "conflicts_with_evidence_ids": [], "disputed": True,
    }
    outcome = {"outcome_digest": digest("outcome", outcome), **outcome}

    def mutate(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    # LIFE-006: the budget-disputed row adds BUDGET_EFFECT_DISPUTED and every reservation receipt
    # reason to "any non-DUPLICATE effect classification", and reason_codes is the union required by
    # the included details. This decision carries a BUDGET detail whose receipt decision is
    # EFFECT_DISPUTED, so FOREIGN_EFFECT alone is not the complete set.
    reason_codes = sorted({"BUDGET_EFFECT_DISPUTED", "FOREIGN_EFFECT", reason}, key=lambda value: value.encode("utf-8"))
    return admitted_transition(
        state, event, disposition="DISPUTED", reason_codes=reason_codes,
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output["registry_digest"], "receipt_digest": receipt_digest, "reasons": [reason]},
            {"kind": "EFFECT", "classification": "FOREIGN", "evidence_id": evidence["evidence_id"]},
        ],
        receipt_permit_digest=None, budget_results=[budget_output], mutate=mutate,
    )


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def known_reservation_case() -> None:
    """D2-180: a known reservation, exact retained anchor set, deterministic embedded SETTLE."""
    base, facts, proposal, permitted = initial_budget_success(
        instance_id="case-d2-180", event_id="proposal-d2-180"
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    permit = permitted["permit"]
    reservation_row = next(row for row in registry_state["core"]["reservations"] if row["id"] == reservation_id)
    attributed = attributed_request(base, permit)
    evidence = foreign_evidence("D2-180", attributed, permit)
    budget_input, budget_output = foreign_settle_transition(
        facts, registry_state, reservation_id, "effect-d2-180",
        attributed=attributed, evidence=evidence,
        retained_request=retained_native_request(reservation_row),
        reservation_status="DISPUTED", reason="UNEXPECTED_EFFECT",
    )
    event = foreign_event(permitted["state"], permit, evidence, reservation_id, budget_input)
    expected = foreign_budget_result(permitted["state"], event, evidence, budget_output, reason="UNEXPECTED_EFFECT")
    emit(
        "D2-180", base, permitted["state"], event, expected,
        "The foreign branch supplies null permit, dispatch and completion authorization for a well-formed attributable effect. The resolved step's declared shared_budgets is nonempty and the reservation is known, so the event carries that reservation's identity, the declared anchor set and one registry input. The consumer constructs exactly one embedded SETTLE/EFFECT transition: the native record copies the reservation's exact retained native request rather than the attributed request, sets completion_mismatch true with mismatch_reason UNEXPECTED_EFFECT unconditionally, and the temporally consistent record gets a projected observed_request. The registry classifies this as an attributable EFFECT that is unexpected for an OPEN reservation, which is EFFECT_DISPUTED, blocking the retained contribution anchor. Work retains the FOREIGN outcome and exact receipt without completing an occurrence.",
    )


def unknown_reservation_case() -> None:
    """D2-181: a stable unknown reservation, exact nonempty history and anchor set."""
    base, facts, proposal, permitted = initial_budget_success(
        instance_id="case-d2-181", event_id="proposal-d2-181"
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    permit = permitted["permit"]
    unknown_reservation = "reservation-does-not-exist-d2-181"
    attributed = attributed_request(base, permit)
    evidence = foreign_evidence("D2-181", attributed, permit)
    budget_input, budget_output = foreign_settle_transition(
        facts, registry_state, unknown_reservation, "effect-d2-181",
        attributed=attributed, evidence=evidence, retained_request=copy.deepcopy(attributed),
        reservation_status=None, reason="UNKNOWN_RESERVATION",
    )
    event = foreign_event(permitted["state"], permit, evidence, unknown_reservation, budget_input)
    expected = foreign_budget_result(permitted["state"], event, evidence, budget_output, reason="UNKNOWN_RESERVATION")
    emit(
        "D2-181", base, permitted["state"], event, expected,
        "The event names a stable reservation identity that is not retained in the supplied registry. LIFE-010: when the reservation is unknown, the declared step set supplies the complete anchor inventory and the implementation never asks the caller to guess which anchors apply, so the event still carries the step's declared anchor set and one registry input citing a real registered budget through its history. Because the reservation is unknown, the embedded native record's request is the event's attributed request rather than a retained one. RES-WIRE-003: an unknown reservation is retained as disputed exposure on every supplied anchor, not admitted as a known reservation, and has no projectable affected key, so the registry blocks the entire anchor with a null key rather than any specific partition. The registry returns EFFECT_DISPUTED with reason UNKNOWN_RESERVATION; work retains the foreign outcome and the exact receipt.",
    )


def missing_anchor_case() -> None:
    """D2-188: a known reservation whose wrapper affected-anchor set is missing entirely."""
    base, facts, proposal, permitted = initial_budget_success(
        instance_id="case-d2-188", event_id="proposal-d2-188"
    )
    permit = permitted["permit"]
    attributed = attributed_request(base, permit)
    evidence = foreign_evidence("D2-188", attributed, permit)
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    event = foreign_event(permitted["state"], permit, evidence, reservation_id, None)
    emit(
        "D2-188", base, permitted["state"], event, stateful_refusal(permitted["state"], "BINDING_MISMATCH"),
        "The resolved step's declared shared_budgets set is nonempty and the event names a known reservation, but its wrapper affected_budget_anchors and budget_inputs are empty rather than equal to that declared set. LIFE-010: null reservation identity or a missing, extra or partial anchor set is BINDING_MISMATCH, and it cannot turn a budget-bearing operation into an authority-only effect. Admission fails before any evidence is retained; work and registry state remain unchanged.",
    )


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    known_reservation_case()
    unknown_reservation_case()
    missing_anchor_case()
    print(json.dumps({"case_ids": ["D2-180", "D2-181", "D2-188"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
