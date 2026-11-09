#!/usr/bin/env python3
"""Build a governed conflicting-after-settle vector from LIFE-010, LIFE-013 and RES-WIRE-003.

A clean settlement completes an occurrence; a second conclusive record for the same
provider-native operation identity, differing only in evidence identity and content such as
`record_digest`, disputes the retained settlement rather than being read as a harmless
duplicate.
"""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_budget_fixture import initial_budget_success
from lifecycle_factory import (
    admitted_transition, dispatch_event, dispatch_result, governed_effect_event,
    governed_native_evidence, governed_outcome, step_input,
)
from reservation_fixture import host_and_event, native as native_record, request as reservation_request, transition as reservation_transition


GROUP = CASES / "governed-conflicting-settles"
REGISTRY_CLOCK_INSTANT = "2026-09-10T04:30:00Z"
REGISTRY_CLOCK_REVISION = "1"


def clean_record(facts: dict, evidence: dict, reservation_id: str) -> dict:
    record = native_record(
        facts, "EFFECT", evidence["evidence_id"], reservation_id=reservation_id,
        completion_mismatch=False, mismatch_reason=None, effect_id=evidence["native_operation_id"],
    )
    record["provider"] = evidence["provider"]
    record["source"] = evidence["source"]
    record["evidence_ref"] = evidence["evidence_ref"]
    record["actual_fields"] = copy.deepcopy(evidence["actual_fields"])
    record["collections"] = copy.deepcopy(evidence["collections"])
    record["rules_out_past_and_future_effects"] = evidence["rules_out_past_and_future_effects"]
    record["occurred_at"] = evidence["event_time"]
    return record


def prescribed_event(budget: dict, contribution: dict, effect_id: str, occurred_at: str) -> dict:
    """RES-WIRE-003's committed-event id: a digest of the budget, effect id and mapping."""
    mapping = next(row for row in budget["definition"]["aggregate"]["aggregate"]["mappings"] if row["id"] == contribution["mapping"])
    fields = dict(zip(mapping["key_fields"], contribution["key"]))
    fields[mapping["contribution"]["field"]] = contribution["value"]
    return {
        "id": digest("reservation-committed-event", {"budget_digest": budget["definition_digest"], "effect_id": effect_id, "mapping": contribution["mapping"]}),
        "state": "ACTIVE", "occurred_at": occurred_at,
        "fields": [{"name": name, "value": fields[name]} for name in sorted(fields)],
    }


def corroborating_history(facts: dict, budget: dict, contribution: dict, effect_id: str, occurred_at: str) -> dict:
    history = copy.deepcopy(facts["history"])
    history["journal"].append({"sequence": "2", "event": prescribed_event(budget, contribution, effect_id, occurred_at)})
    history["revision"] = "2"
    history["as_of"] = REGISTRY_CLOCK_INSTANT
    return history


def settle(
    facts: dict, registry_state: dict, reservation_id: str, event_id: str, record: dict,
    history: dict, *, decision: str, disposition: str, reason: str, blocked: list[dict],
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
        {"native": record, "histories": [history]},
        event_clock=facts["clock"], administration=None,
    )
    core = copy.deepcopy(registry_state["core"])
    for reservation in core["reservations"]:
        if reservation["id"] != reservation_id:
            continue
        if disposition == "DISPUTED":
            reservation["status"] = "DISPUTED"
        elif disposition == "MATCHED":
            reservation["status"] = "SETTLED"
            reservation["matched_effect"] = record["effect_id"]
    if history["status"] == "AVAILABLE":
        for budget in core["budgets"]:
            if budget["definition"]["anchor"] == "license-spend":
                budget["history"] = copy.deepcopy(history)
    # A duplicate returns the established disposition and appends no effect record; disposition
    # None marks that case.
    if disposition is not None:
        core["effects"].append({
            "id": record["id"], "native": copy.deepcopy(record), "native_digest": digest("reservation-native-outcome", record),
            "reservation": reservation_id, "disposition": disposition, "affected_anchors": ["license-spend"],
            "blocked_partitions": blocked, "reason": reason,
        })
        core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    result = reservation_transition(
        registry_state, event, host, core, decision, reservation_id=reservation_id,
        reasons=[reason] if decision == "EFFECT_DISPUTED" else [],
    )
    budget_input = {
        "registry_digest": registry_digest, "affected_anchors": ["license-spend"],
        "expected_revision": registry_state["core"]["revision"], "request": reservation_request(registry_state, event, host),
    }
    budget_output = {"registry_digest": registry_digest, "affected_anchors": ["license-spend"], "result": result}
    return budget_input, budget_output


def settle_then_conflict_chain(instance_id: str, event_id_prefix: str) -> dict:
    """The shared setup: a clean settlement completes the occurrence, then a conflicting record.

    Returns every artifact the conflicting step produced, so a duplicate of that conflicting
    record can be built on the state it leaves behind.
    """
    base, facts, proposal, permitted = initial_budget_success(
        instance_id=instance_id, event_id=f"proposal-{event_id_prefix}"
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    reservation_row = next(row for row in registry_state["core"]["reservations"] if row["id"] == reservation_id)
    budget_row = registry_state["core"]["budgets"][0]
    contribution = reservation_row["contributions"][0]

    clean_event = dispatch_event(
        base, permitted, event_id=f"dispatch-{event_id_prefix}", attempt_status="SENT",
        attempted_at=REGISTRY_CLOCK_INSTANT, clock_revision=REGISTRY_CLOCK_REVISION,
    )
    dispatched = dispatch_result(
        permitted, clean_event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED",
    )
    evidence1 = governed_native_evidence(
        base, permitted, dispatched, evidence_id=f"evidence-{event_id_prefix}-first",
        status="EFFECT_ESTABLISHED", observed_at=REGISTRY_CLOCK_INSTANT,
    )
    record1 = clean_record(facts, evidence1, reservation_id)
    history = corroborating_history(facts, budget_row, contribution, evidence1["native_operation_id"], evidence1["event_time"])
    budget_input1, budget_output1 = settle(
        facts, registry_state, reservation_id, f"effect-{event_id_prefix}-first", record1, history,
        decision="SETTLED", disposition="MATCHED", reason="MATCHED_EFFECT", blocked=[],
    )
    event1 = governed_effect_event(
        permitted, dispatched, evidence1, event_id=f"effect-{event_id_prefix}-first",
        budget_inputs=[budget_input1], clock_revision=REGISTRY_CLOCK_REVISION,
    )
    outcome1 = governed_outcome(
        event1, dispatched, classification="MATCHED", disputed=False,
        reservation_receipt_digests=[budget_output1["result"]["receipt_digest"]],
    )
    relationship = next(row for row in base["definition"]["relationships"] if row["kind"] == "SEQUENCE")

    def mutate1(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(outcome1))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active_index = next(
            i for i, row in enumerate(next_state["active"])
            if row["occurrence"]["occurrence_id"] == permitted["permit"]["occurrence"]["occurrence_id"]
        )
        active = next_state["active"].pop(active_index)
        next_state["completed"].append({
            "occurrence": copy.deepcopy(active["occurrence"]), "disposition": "SUCCEEDED",
            "evidence_digest": digest("native-evidence", evidence1), "occurred_at": evidence1["event_time"],
            "route_label": None, "selected_relationship_digest": digest("relationship", relationship), "late": False,
        })
        # Routing over the declared edge reaches the TERMINAL step, which completes the instance.
        next_state["status"] = "COMPLETE"

    step1 = admitted_transition(
        dispatched["state"], event1, disposition="COMPLETED", reason_codes=[],
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output1["registry_digest"], "receipt_digest": budget_output1["result"]["receipt_digest"], "reasons": []},
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence1["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [digest("relationship", relationship)], "construct_ids": []},
        ],
        receipt_permit_digest=event1["permit"]["permit_id"], budget_results=[budget_output1], mutate=mutate1,
    )
    after1 = {**dispatched, "state": step1["state"], "state_digest": step1["state_digest"]}
    registry_after1 = budget_output1["result"]["state"]

    evidence2 = governed_native_evidence(
        base, permitted, dispatched, evidence_id=f"evidence-{event_id_prefix}", status="EFFECT_ESTABLISHED",
        observed_at=REGISTRY_CLOCK_INSTANT, native_operation_id=evidence1["native_operation_id"],
        record_digest=digest("provider-native-record", {"record": event_id_prefix.upper()}),
    )
    record2 = native_record(
        facts, "EFFECT", evidence2["evidence_id"], reservation_id=reservation_id,
        completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT", effect_id=evidence2["native_operation_id"],
    )
    record2["provider"] = evidence2["provider"]; record2["source"] = evidence2["source"]
    record2["evidence_ref"] = evidence2["evidence_ref"]
    record2["actual_fields"] = copy.deepcopy(evidence2["actual_fields"])
    record2["collections"] = copy.deepcopy(evidence2["collections"])
    record2["rules_out_past_and_future_effects"] = evidence2["rules_out_past_and_future_effects"]
    record2["occurred_at"] = evidence2["event_time"]
    blocked = [{"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_row["contributions"]]
    budget_input2, budget_output2 = settle(
        facts, registry_after1, reservation_id, f"effect-{event_id_prefix}", record2, history,
        decision="EFFECT_DISPUTED", disposition="DISPUTED", reason="UNEXPECTED_EFFECT", blocked=blocked,
    )
    event2 = governed_effect_event(
        permitted, after1, evidence2, event_id=f"effect-{event_id_prefix}",
        budget_inputs=[budget_input2], clock_revision=REGISTRY_CLOCK_REVISION,
    )
    outcome2 = governed_outcome(
        event2, after1, classification="CONFLICTING", disputed=True,
        conflicts=[evidence1["evidence_id"]],
        reservation_receipt_digests=[budget_output2["result"]["receipt_digest"]],
    )

    def mutate2(next_state: dict) -> None:
        for prior in next_state["outcomes"]:
            if prior["native_evidence"]["evidence_id"] == evidence1["evidence_id"]:
                prior["disputed"] = True
                prior["conflicts_with_evidence_ids"] = [evidence2["evidence_id"]]
                prior["outcome_digest"] = digest("outcome", {k: v for k, v in prior.items() if k != "outcome_digest"})
        next_state["outcomes"].append(copy.deepcopy(outcome2))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    step2 = admitted_transition(
        after1["state"], event2, disposition="DISPUTED",
        reason_codes=sorted({"BUDGET_EFFECT_DISPUTED", "CONFLICTING_EFFECT", "UNEXPECTED_EFFECT"}, key=lambda v: v.encode("utf-8")),
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output2["registry_digest"], "receipt_digest": budget_output2["result"]["receipt_digest"], "reasons": ["UNEXPECTED_EFFECT"]},
            {"kind": "EFFECT", "classification": "CONFLICTING", "evidence_id": evidence2["evidence_id"]},
        ],
        receipt_permit_digest=event2["permit"]["permit_id"], budget_results=[budget_output2], mutate=mutate2,
    )
    return {
        "base": base, "facts": facts, "permitted": permitted, "dispatched": dispatched,
        "reservation_id": reservation_id, "history": history,
        "evidence1": evidence1, "evidence2": evidence2, "record2": record2,
        "after1": after1, "event2": event2, "step2": step2,
        "registry_after2": budget_output2["result"]["state"],
        "outcome2": outcome2, "blocked": blocked,
    }


def duplicate_of_conflicting_case() -> None:
    """D2-263: a third record carries the conflicting record's exact fact under a new identity."""
    chain = settle_then_conflict_chain("case-d2-263", "d2-263")
    base, facts = chain["base"], chain["facts"]
    permitted, dispatched = chain["permitted"], chain["dispatched"]
    reservation_id, registry = chain["reservation_id"], chain["registry_after2"]
    conflicting_evidence, conflicting_record = chain["evidence2"], chain["record2"]
    after2 = {**dispatched, "state": chain["step2"]["state"], "state_digest": chain["step2"]["state_digest"]}

    # RES-WIRE-003: the same complete fact after omitting only evidence identity and reference.
    # nativeFactDigest covers record_digest, so the duplicate carries the conflicting record's.
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-263-duplicate", status="EFFECT_ESTABLISHED",
        observed_at=REGISTRY_CLOCK_INSTANT, native_operation_id=conflicting_evidence["native_operation_id"],
        record_digest=conflicting_evidence["record_digest"], evidence_ref="evidence-ref-d2-263-duplicate",
    )
    # LIFE-010: "For a lifecycle DUPLICATE, the consumer copies the retained same-fact outcome's
    # complete embedded reservation-native record and changes only id and evidence_ref."
    retained_native = next(
        row["native"] for row in registry["core"]["effects"] if row["id"] == conflicting_evidence["evidence_id"]
    )
    record = copy.deepcopy(retained_native)
    record["id"] = evidence["evidence_id"]
    record["evidence_ref"] = evidence["evidence_ref"]
    # A duplicate returns the established disposition and appends no effect record or exposure,
    # so the core is unchanged apart from the revision the receipt advances.
    budget_input, budget_output = settle(
        facts, registry, reservation_id, "effect-d2-263-duplicate", record, chain["history"],
        decision="EFFECT_DISPUTED", disposition=None, reason="UNEXPECTED_EFFECT", blocked=[],
    )
    event = governed_effect_event(
        permitted, after2, evidence, event_id="effect-d2-263-duplicate",
        budget_inputs=[budget_input], clock_revision=REGISTRY_CLOCK_REVISION,
    )
    outcome = governed_outcome(
        event, after2, classification="DUPLICATE", disputed=True,
        conflicts=copy.deepcopy(chain["outcome2"]["conflicts_with_evidence_ids"]),
        reservation_receipt_digests=[budget_output["result"]["receipt_digest"]],
    )

    def mutate(next_state: dict) -> None:
        # LIFE-010: the duplicate lists every evidence identity in the other fact group, and each
        # member of that group adds the duplicate evidence identity to its sorted conflict set.
        for prior in next_state["outcomes"]:
            if prior["native_evidence"]["evidence_id"] not in outcome["conflicts_with_evidence_ids"]:
                continue
            prior["conflicts_with_evidence_ids"] = sorted(
                set(prior["conflicts_with_evidence_ids"]) | {evidence["evidence_id"]},
                key=lambda value: value.encode("utf-8"),
            )
            prior["outcome_digest"] = digest(
                "outcome", {key: value for key, value in prior.items() if key != "outcome_digest"}
            )
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    expected = admitted_transition(
        after2["state"], event, disposition="OUTCOME_RETAINED", reason_codes=["DUPLICATE_EVIDENCE"],
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output["registry_digest"], "receipt_digest": budget_output["result"]["receipt_digest"], "reasons": ["UNEXPECTED_EFFECT"]},
            {"kind": "EFFECT", "classification": "DUPLICATE", "evidence_id": evidence["evidence_id"]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], budget_results=[budget_output], mutate=mutate,
    )
    write_canonical_json(
        GROUP / "D2-263.json",
        exact_case(
            "D2-263", "step", step_input(base, after2["state"], event), expected, [],
            "Setup, not the case: a clean settlement completed the occurrence, then a second conclusive record for the same provider-native operation identity with a changed record_digest was retained as CONFLICTING and disputed the settled reservation. The case: a third record whose complete fact equals the conflicting record's after omitting only evidence identity and reference, which RES-WIRE-003 defines as a duplicate. LIFE-010 makes the embedding mechanical: for a lifecycle DUPLICATE the consumer copies the retained same-fact outcome's complete embedded reservation-native record and changes only id and evidence_ref to the new evidence values, so completion_mismatch:true and its mismatch_reason carry over unchanged; a duplicate of UNEXPECTED or CONFLICTING remains completion-mismatched and the reservation transition recognizes it as the same fact rather than inventing a second conclusion. LIFE-010 adds that exact or same-fact duplicates return the established reservation disposition without adding exposure, and RES-WIRE-004 still advances the registry revision by one for the admitted event, so a receipt is produced with no new effect record and no new charge. LIFE-010 also fixes the outcome: a DUPLICATE outcome inherits the disputed value and conflict set of the retained same-fact outcome. LIFE-006's DUPLICATE row takes precedence and fixes the complete reason set to DUPLICATE_EVIDENCE, including when its idempotent reservation receipt reports an already retained dispute. The completed route and the blocked dependencies are unchanged.",
        ),
    )


def conflicting_after_settle_case() -> None:
    base, facts, proposal, permitted = initial_budget_success(
        instance_id="case-d2-234", event_id="proposal-d2-234"
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    reservation_row = next(row for row in registry_state["core"]["reservations"] if row["id"] == reservation_id)
    budget_row = registry_state["core"]["budgets"][0]
    contribution = reservation_row["contributions"][0]

    clean_event = dispatch_event(
        base, permitted, event_id="dispatch-d2-234", attempt_status="SENT",
        attempted_at=REGISTRY_CLOCK_INSTANT, clock_revision=REGISTRY_CLOCK_REVISION,
    )
    dispatched = dispatch_result(
        permitted, clean_event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED",
    )

    # Step 1: a clean settlement, corroborated so the occurrence completes normally.
    evidence1 = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-234-first",
        status="EFFECT_ESTABLISHED", observed_at=REGISTRY_CLOCK_INSTANT,
    )
    record1 = clean_record(facts, evidence1, reservation_id)
    history1 = corroborating_history(facts, budget_row, contribution, evidence1["native_operation_id"], evidence1["event_time"])
    budget_input1, budget_output1 = settle(
        facts, registry_state, reservation_id, "effect-d2-234-first", record1, history1,
        decision="SETTLED", disposition="MATCHED", reason="MATCHED_EFFECT", blocked=[],
    )
    event1 = governed_effect_event(
        permitted, dispatched, evidence1, event_id="effect-d2-234-first",
        budget_inputs=[budget_input1], clock_revision=REGISTRY_CLOCK_REVISION,
    )
    outcome1 = governed_outcome(
        event1, dispatched, classification="MATCHED", disputed=False,
        reservation_receipt_digests=[budget_output1["result"]["receipt_digest"]],
    )
    relationship = next(row for row in base["definition"]["relationships"] if row["kind"] == "SEQUENCE")

    def mutate1(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(outcome1))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active_index = next(
            i for i, row in enumerate(next_state["active"]) if row["occurrence"]["occurrence_id"] == permitted["permit"]["occurrence"]["occurrence_id"]
        )
        active = next_state["active"].pop(active_index)
        next_state["completed"].append({
            "occurrence": copy.deepcopy(active["occurrence"]), "disposition": "SUCCEEDED",
            "evidence_digest": digest("native-evidence", evidence1), "occurred_at": evidence1["event_time"],
            "route_label": None, "selected_relationship_digest": digest("relationship", relationship), "late": False,
        })
        # Routing over the declared edge reaches the TERMINAL step, which completes the instance.
        next_state["status"] = "COMPLETE"

    step1_expected = admitted_transition(
        dispatched["state"], event1, disposition="COMPLETED", reason_codes=[],
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output1["registry_digest"], "receipt_digest": budget_output1["result"]["receipt_digest"], "reasons": []},
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence1["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [digest("relationship", relationship)], "construct_ids": []},
        ],
        receipt_permit_digest=event1["permit"]["permit_id"], budget_results=[budget_output1], mutate=mutate1,
    )
    after1 = {**dispatched, "state": step1_expected["state"], "state_digest": step1_expected["state_digest"]}
    registry_after1 = budget_output1["result"]["state"]

    # Step 2 (the case): a second conclusive EFFECT_ESTABLISHED record, same provider-native
    # operation identity, changed record_digest, forcing completion_mismatch true and CONFLICTING.
    evidence2 = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-d2-234", status="EFFECT_ESTABLISHED",
        observed_at=REGISTRY_CLOCK_INSTANT, native_operation_id=evidence1["native_operation_id"],
        record_digest=digest("provider-native-record", {"record": "D2-234"}),
    )
    record2 = native_record(
        facts, "EFFECT", evidence2["evidence_id"], reservation_id=reservation_id,
        completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT", effect_id=evidence2["native_operation_id"],
    )
    record2["provider"] = evidence2["provider"]; record2["source"] = evidence2["source"]
    record2["evidence_ref"] = evidence2["evidence_ref"]
    record2["actual_fields"] = copy.deepcopy(evidence2["actual_fields"])
    record2["collections"] = copy.deepcopy(evidence2["collections"])
    record2["rules_out_past_and_future_effects"] = evidence2["rules_out_past_and_future_effects"]
    record2["occurred_at"] = evidence2["event_time"]
    blocked = [{"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_row["contributions"]]
    budget_input2, budget_output2 = settle(
        facts, registry_after1, reservation_id, "effect-d2-234", record2, history1,
        decision="EFFECT_DISPUTED", disposition="DISPUTED", reason="UNEXPECTED_EFFECT", blocked=blocked,
    )
    event2 = governed_effect_event(
        permitted, after1, evidence2, event_id="effect-d2-234",
        budget_inputs=[budget_input2], clock_revision=REGISTRY_CLOCK_REVISION,
    )
    outcome2 = governed_outcome(
        event2, after1, classification="CONFLICTING", disputed=True,
        conflicts=[evidence1["evidence_id"]],
        reservation_receipt_digests=[budget_output2["result"]["receipt_digest"]],
    )

    def mutate2(next_state: dict) -> None:
        for prior in next_state["outcomes"]:
            if prior["native_evidence"]["evidence_id"] == evidence1["evidence_id"]:
                prior["disputed"] = True
                prior["conflicts_with_evidence_ids"] = [evidence2["evidence_id"]]
                prior["outcome_digest"] = digest("outcome", {key: value for key, value in prior.items() if key != "outcome_digest"})
        next_state["outcomes"].append(copy.deepcopy(outcome2))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    reason_codes = sorted(
        {"BUDGET_EFFECT_DISPUTED", "CONFLICTING_EFFECT", "UNEXPECTED_EFFECT"}, key=lambda value: value.encode("utf-8")
    )
    expected = admitted_transition(
        after1["state"], event2, disposition="DISPUTED", reason_codes=reason_codes,
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output2["registry_digest"], "receipt_digest": budget_output2["result"]["receipt_digest"], "reasons": ["UNEXPECTED_EFFECT"]},
            {"kind": "EFFECT", "classification": "CONFLICTING", "evidence_id": evidence2["evidence_id"]},
        ],
        receipt_permit_digest=event2["permit"]["permit_id"], budget_results=[budget_output2], mutate=mutate2,
    )
    write_canonical_json(
        GROUP / "D2-234.json",
        exact_case(
            "D2-234", "step", step_input(base, after1["state"], event2), expected, [],
            "The first record settled cleanly and completed the occurrence. The second record shares its provider-native operation identity but differs in record_digest and evidence identity, so nativeFactDigest differs from the first outcome: this is a conclusive conflict, not a duplicate. LIFE-010 classifies it CONFLICTING because the prior effect was EFFECT_ESTABLISHED, not NO_EFFECT_ESTABLISHED. A CONFLICTING classification forces completion_mismatch true with mismatch_reason UNEXPECTED_EFFECT in the embedded settlement, overriding what the dispatch's own eligibility would otherwise permit. RES-WIRE-003's table gives a SETTLED reservation receiving a nonduplicate EFFECT the EFFECT_DISPUTED decision: it becomes DISPUTED, retains all conclusions, restores the unresolved pending charge and blocks the reservation's original contribution. The earlier completed row and its route are unchanged; the prior outcome is marked disputed and records the new conflict.",
        ),
    )


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    conflicting_after_settle_case()
    duplicate_of_conflicting_case()
    print(json.dumps({"case_ids": ["D2-234", "D2-263"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
