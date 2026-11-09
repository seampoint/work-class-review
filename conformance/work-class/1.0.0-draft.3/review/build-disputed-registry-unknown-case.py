#!/usr/bin/env python3
"""Build D2-232: a clean governed UNKNOWN against an already-disputed shared-budget reservation.

LIFE-010, RES-WIRE-003 and RES-WIRE-004. The reservation is disputed first by a foreign effect naming
it, which a host can record without disturbing the clean dispatch or its occurrence. An earlier
construction disputed it with a changed first attempt and then hand-wrote a second clean SENT attempt
that both implementations refuse, so that history could not occur.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_budget_fixture import initial_budget_success
from lifecycle_factory import (
    admitted_transition, dispatch_event, dispatch_result, governed_effect_event,
    governed_native_evidence, governed_outcome, step_input,
)
from reservation_fixture import effect_record, host_and_event, native as native_record, request as reservation_request, transition as reservation_transition


GROUP = CASES / "governed-budget-disputes"
REGISTRY_CLOCK_INSTANT = "2026-09-10T04:30:00Z"
REGISTRY_CLOCK_REVISION = "1"


def changed_request(permitted: dict) -> dict:
    native = copy.deepcopy(permitted["permit"]["native_request"])
    next(row for row in native["fields"] if row["name"] == "card_id")["value"]["value"] = "card-999"
    return native


def bare_native_record(facts: dict, evidence: dict, reservation_id: str, *, completion_mismatch: bool, mismatch_reason: str | None) -> dict:
    record = native_record(
        facts, "UNKNOWN", evidence["evidence_id"], reservation_id=reservation_id,
        completion_mismatch=completion_mismatch, mismatch_reason=mismatch_reason,
    )
    record["provider"] = evidence["provider"]
    record["source"] = evidence["source"]
    record["evidence_ref"] = evidence["evidence_ref"]
    record["rules_out_past_and_future_effects"] = evidence["rules_out_past_and_future_effects"]
    return record


def settle_unknown(
    facts: dict, registry_state: dict, reservation_id: str, event_id: str, record: dict,
    *, reservation_status: str | None, reason: str, blocked: list[dict],
) -> tuple[dict, dict]:
    registry_digest = digest("reservation-registry", registry_state["core"]["configuration"])
    embedded_id = digest(
        "lifecycle-reservation-event",
        {
            "instance_id": facts["authority_a"]["proposal"]["instance"], "lifecycle_event_id": event_id,
            "lifecycle_event_kind": "EFFECT_OBSERVED", "reservation_event_kind": "SETTLE",
            "registry_digest": registry_digest,
        },
    )
    event, host = host_and_event(
        facts, "SETTLE", embedded_id, registry_state["core"]["revision"],
        {"native": record, "histories": [facts["history"]]},
        event_clock=facts["clock"], administration=None,
    )
    core = copy.deepcopy(registry_state["core"])
    if reservation_status is not None:
        for reservation in core["reservations"]:
            if reservation["id"] == reservation_id:
                reservation["status"] = reservation_status
    core["effects"].append(effect_record(record, "DISPUTED" if reservation_status == "DISPUTED" else "UNKNOWN", reason, blocked))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    decision = "EFFECT_DISPUTED" if reservation_status == "DISPUTED" else "UNKNOWN"
    result = reservation_transition(
        registry_state, event, host, core, decision,
        reservation_id=reservation_id, reasons=[reason] if decision == "EFFECT_DISPUTED" else [],
    )
    budget_input = {
        "registry_digest": registry_digest, "affected_anchors": ["license-spend"],
        "expected_revision": registry_state["core"]["revision"],
        "request": reservation_request(registry_state, event, host),
    }
    budget_output = {"registry_digest": registry_digest, "affected_anchors": ["license-spend"], "result": result}
    return budget_input, budget_output


def _module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FOREIGN = _module("foreign_budget_effects", "build-foreign-budget-effect-cases.py")


def fixture() -> dict:
    """A reachable history: a clean dispatch, then a foreign effect that disputes the same reservation.

    A foreign effect against the occurrence's own known reservation disputes the registry and leaves
    current occurrences unchanged (LIFE-006), so the clean dispatch and its DISPATCHED occurrence
    survive intact for the governed UNKNOWN that the case submits.
    """
    base, facts, _proposal, permitted = initial_budget_success(instance_id="case-d2-232", event_id="proposal-d2-232")
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    permit = permitted["permit"]

    dispatch = dispatch_event(
        base, permitted, event_id="dispatch-a", attempt_status="SENT",
        attempted_at=REGISTRY_CLOCK_INSTANT, clock_revision=REGISTRY_CLOCK_REVISION,
    )
    dispatched = dispatch_result(permitted, dispatch, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")
    digest_a = next(row["dispatch_digest"] for row in dispatched["state"]["dispatches"] if row["event_id"] == dispatch["event_id"])

    reservation_row = next(row for row in registry_state["core"]["reservations"] if row["id"] == reservation_id)
    attributed = FOREIGN.attributed_request(base, permit)
    foreign_evidence = FOREIGN.foreign_evidence("D2-232-foreign", attributed, permit)
    foreign_input, foreign_output = FOREIGN.foreign_settle_transition(
        facts, registry_state, reservation_id, "effect-d2-232-foreign",
        attributed=attributed, evidence=foreign_evidence,
        retained_request=FOREIGN.retained_native_request(reservation_row),
        reservation_status="DISPUTED", reason="UNEXPECTED_EFFECT",
    )
    foreign_event = FOREIGN.foreign_event(dispatched["state"], permit, foreign_evidence, reservation_id, foreign_input)
    foreign = FOREIGN.foreign_budget_result(dispatched["state"], foreign_event, foreign_evidence, foreign_output, reason="UNEXPECTED_EFFECT")
    after_foreign = {**dispatched, "state": foreign["state"], "state_digest": foreign["state_digest"]}
    registry_disputed = foreign_output["result"]["state"]

    # The case: the clean dispatch's own OUTCOME_UNKNOWN record, with no mismatch of its own.
    evidence = governed_native_evidence(
        base, permitted, after_foreign, evidence_id="evidence-d2-232", status="OUTCOME_UNKNOWN",
        observed_at=REGISTRY_CLOCK_INSTANT, dispatch_digest=digest_a,
    )
    record = bare_native_record(facts, evidence, reservation_id, completion_mismatch=False, mismatch_reason=None)
    # A clean UNKNOWN projects no actual key; the reservation's own original contribution key is what
    # remains blocked.
    reservation_after = next(row for row in registry_disputed["core"]["reservations"] if row["id"] == reservation_id)
    blocked_partitions = [{"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_after["contributions"]]
    budget_input, budget_output = settle_unknown(
        facts, registry_disputed, reservation_id, "effect-d2-232", record,
        reservation_status="DISPUTED", reason="UNKNOWN_OUTCOME", blocked=blocked_partitions,
    )
    event = governed_effect_event(
        permitted, after_foreign, evidence, event_id="effect-d2-232",
        budget_inputs=[budget_input], clock_revision=REGISTRY_CLOCK_REVISION, dispatch_digest=digest_a,
    )
    outcome = governed_outcome(
        event, after_foreign, classification="UNKNOWN", disputed=True,
        reservation_receipt_digests=[budget_output["result"]["receipt_digest"]],
    )

    def mutate(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active = next(row for row in next_state["active"] if row["occurrence"]["occurrence_id"] == permit["occurrence"]["occurrence_id"])
        if active["status"] != "BLOCKED_DISPUTE":
            active["status"] = "OUTCOME_UNKNOWN"

    expected = admitted_transition(
        after_foreign["state"], event, disposition="DISPUTED",
        reason_codes=["BUDGET_EFFECT_DISPUTED", "UNKNOWN_OUTCOME"],
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output["registry_digest"], "receipt_digest": budget_output["result"]["receipt_digest"], "reasons": ["UNKNOWN_OUTCOME"]},
            {"kind": "EFFECT", "classification": "UNKNOWN", "evidence_id": evidence["evidence_id"]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], budget_results=[budget_output], mutate=mutate,
    )
    return {
        "base": base, "permitted": permitted, "dispatch": dispatch, "dispatched": dispatched,
        "foreign_event": foreign_event, "foreign": foreign, "after_foreign": after_foreign,
        "event": event, "expected": expected,
    }


def disputed_registry_unknown_case() -> None:
    parts = fixture()
    write_canonical_json(
        GROUP / "D2-232.json",
        exact_case(
            "D2-232", "step", step_input(parts["base"], parts["after_foreign"]["state"], parts["event"]), parts["expected"], [],
            "Setup, by transitions a host can record: the permitted occurrence's native request is dispatched cleanly and recorded as SENT, so the occurrence is DISPATCHED. A foreign effect then names the occurrence's own known reservation; LIFE-010 retains it as disputed exposure and the registry moves the reservation to DISPUTED, while LIFE-006 leaves current occurrences unchanged for a DISPUTED foreign effect, so the occurrence and its clean dispatch are untouched. The case: that clean dispatch's own OUTCOME_UNKNOWN record carries no mismatch of its own (completion_mismatch false), so its classification is UNKNOWN. RES-WIRE-003's reconciliation table is explicit that a DISPUTED reservation performs no automatic resolution: any new attributable fact returns EFFECT_DISPUTED and the reservation remains DISPUTED regardless of whether the new fact itself matches. RES-WIRE-004 assigns the receipt's reason from the native record's own mismatch_reason when completion-mismatched, or HISTORY_UNCORROBORATED for missing corroboration; neither applies to a clean UNKNOWN, and the registry's EFFECT_DISPUTED reason falls back to UNEXPECTED_EFFECT, a recorded open question. LIFE-006 adds BUDGET_EFFECT_DISPUTED and the receipt reason to the classification's UNKNOWN_OUTCOME. The occurrence becomes OUTCOME_UNKNOWN, the existing disputed exposure remains charged, and no route is selected. The retained outcome's disputed flag follows the current convention pending an open specification question.",
        ),
    )


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    disputed_registry_unknown_case()
    print(json.dumps({"case_ids": ["D2-232"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
