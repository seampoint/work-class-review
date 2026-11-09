#!/usr/bin/env python3
"""Build the repair-round controls for effect classification and the budget registry.

Each case pins one rule from the gate-2 repair round (derivations sealed 2026-09-13) on a path no earlier
case reached. Inputs extend committed cases or their builders; expected results are derived with the
fixture transition helpers, never taken from a consumer.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_factory import admitted_transition, governed_effect_event, governed_native_evidence, governed_outcome, step_input
from reservation_fixture import effect_record, host_and_event, native as native_record, request as reservation_request, transition as reservation_transition


def _module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GCS = _module("governed_conflicting_settles", "build-governed-conflicting-settle-cases.py")
B2 = _module("budget_effect_b2", "build-budget-effect-b2-cases.py")
BEC = _module("budget_effects", "build-budget-effect-cases.py")
RN = _module("renewal_budget", "build-renewal-budget-cases.py")
GROUP = CASES / "repair-round-effect-controls"
INSTANT = "2026-09-10T04:30:00Z"


def load(relative: str) -> dict:
    return json.loads((CASES / relative).read_text())


def emit(case_id: str, operation: str, input_value: dict, expected: dict, requirements: list[str], derivation: str) -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(GROUP / f"{case_id}.json", exact_case(case_id, operation, input_value, expected, requirements, derivation))


def foreign_record(event: dict, classification: str, conflicts: list[str]) -> dict:
    body = {
        "kind": "FOREIGN", "event_id": event["event_id"], "event_digest": digest("runtime-event", event),
        "permit_digest": None, "dispatch_digest": None, "dispatch_attempt_digest": None,
        "native_evidence": copy.deepcopy(event["native_evidence"]), "classification": classification,
        "affected_budget_anchors": copy.deepcopy(event["affected_budget_anchors"]), "reservation_receipt_digests": [],
        "conflicts_with_evidence_ids": sorted(conflicts, key=lambda value: value.encode("utf-8")), "disputed": True,
    }
    return {"outcome_digest": digest("outcome", body), **body}


def add_conflict(row: dict, evidence_id: str) -> None:
    row["conflicts_with_evidence_ids"] = sorted(set(row["conflicts_with_evidence_ids"]) | {evidence_id}, key=lambda value: value.encode("utf-8"))
    row["disputed"] = True
    row["outcome_digest"] = digest("outcome", {key: value for key, value in row.items() if key != "outcome_digest"})


def host_for(registry_digest: str, selection: str, histories: list[dict], native: dict) -> dict:
    records = [{"kind": "HISTORY", "record_digest": digest("budget-history", row), "provider": row["provider"], "source": row["source"]} for row in histories]
    records.append({"kind": "NATIVE_OUTCOME", "record_digest": digest("reservation-native-outcome", native), "provider": native["provider"], "source": native["source"]})
    return {"registry_digest": registry_digest, "selection_evidence": selection, "administration_bases": [], "authenticated_records": records}


def duplicate_retry_of_duplicate_row() -> None:
    chain = GCS.settle_then_conflict_chain("case-d2-263", "d2-263")
    case = load("governed-conflicting-settles/D2-263.json")
    state = case["expected"]["state"]
    registry = case["expected"]["budget_results"][0]["result"]["state"]
    evidence = copy.deepcopy(case["input"]["event"]["native_evidence"])
    group_record = next(row["native"] for row in registry["core"]["effects"] if row["id"] == chain["evidence2"]["evidence_id"])
    record = copy.deepcopy(group_record)
    record["id"] = evidence["evidence_id"]
    record["evidence_ref"] = evidence["evidence_ref"]
    budget_input, budget_output = GCS.settle(
        chain["facts"], registry, chain["reservation_id"], "effect-c2-duplicate-retry", record, chain["history"],
        decision="EFFECT_DISPUTED", disposition=None, reason="UNEXPECTED_EFFECT", blocked=[],
    )
    after = {**chain["dispatched"], "state": state, "state_digest": case["expected"]["state_digest"]}
    event = governed_effect_event(chain["permitted"], after, evidence, event_id="effect-c2-duplicate-retry", budget_inputs=[budget_input], clock_revision="1")
    expected = admitted_transition(
        state, event, disposition="OUTCOME_RETAINED", reason_codes=["DUPLICATE_EVIDENCE"],
        details=[
            {"kind": "BUDGET", "registry_digest": budget_output["registry_digest"], "receipt_digest": budget_output["result"]["receipt_digest"], "reasons": ["UNEXPECTED_EFFECT"]},
            {"kind": "EFFECT", "classification": "DUPLICATE", "evidence_id": evidence["evidence_id"]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], budget_results=[budget_output],
    )
    emit(
        "C2-duplicate-retry-of-duplicate-row", "step", step_input(chain["base"], state, event), expected, ["LIFE-010", "LIFE-013", "RES-WIRE-003"],
        "The checkpoint is D2-263's result: a settled effect, a CONFLICTING record for the same operation and a DUPLICATE row carrying the conflicting fact under a new identity. The host now re-delivers that DUPLICATE row's own evidence byte for byte. LIFE-013 makes a repeated evidence identity OUTCOME_RETAINED/DUPLICATE, appending no outcome row and committing the idempotent registry receipt. LIFE-010 fixes the embedded record as a copy of the retained same-fact record with only id and evidence_ref changed. The registry keeps one record per fact group, under the first evidence identity of that fact, and never stores a record for a DUPLICATE row, so the copy source is the conflicting fact's record, not a record under the DUPLICATE row's identity. The registry returns the group's established EFFECT_DISPUTED disposition with its retained reason and no new effect record; LIFE-006's DUPLICATE row fixes the reason set to DUPLICATE_EVIDENCE.",
    )


def unknown_after_authorized_release() -> None:
    case = load("budget-effect-disputes/D2-271.json")
    state = case["expected"]["state"]
    registry = case["expected"]["budget_results"][0]["result"]["state"]
    value = copy.deepcopy(case["input"])
    event = value["event"]
    step = next(row for row in value["definition"]["steps"] if row["id"] == case["input"]["state"]["permits"][0]["occurrence"]["step_id"])
    completion = step["completion"]
    event["event_id"] = "effect-c2-unknown-after-release"
    event["expected_state_revision"] = state["revision"]
    event["expected_state_digest"] = case["expected"]["state_digest"]
    evidence = event["native_evidence"]
    evidence.update({
        "status": "OUTCOME_UNKNOWN", "event_time": None, "actual_fields": [], "collections": [], "rules_out_past_and_future_effects": False,
        "provider": completion["effect_provider"], "source": completion["effect_source"], "record_type": completion["effect_record_type"],
        "evidence_id": "evidence-c2-unknown-after-release", "evidence_ref": "evidence-ref-c2-unknown-after-release",
    })
    event["completion_authorization"] = None
    budget_input = event["budget_inputs"][0]
    registry_request = budget_input["request"]
    prior_native = registry_request["event"]["payload"]["native"]
    registry_digest = digest("reservation-registry", registry["core"]["configuration"])
    native = {
        "id": evidence["evidence_id"], "provider": evidence["provider"], "source": evidence["source"], "reservation": prior_native["reservation"],
        "outcome": "UNKNOWN", "request": copy.deepcopy(prior_native["request"]), "effect_id": None, "occurred_at": None,
        "rules_out_past_and_future_effects": False, "evidence_ref": evidence["evidence_ref"], "observed_request": None,
        "actual_fields": [], "collections": [], "completion_mismatch": False, "mismatch_reason": None,
    }
    histories = [copy.deepcopy(row["history"]) for row in registry["core"]["budgets"] if row["definition"]["anchor"] in budget_input["affected_anchors"]]
    histories.sort(key=lambda row: row["budget_digest"].encode("utf-8"))
    reservation_event = {
        "id": digest("lifecycle-reservation-event", {"instance_id": event["instance_id"], "lifecycle_event_id": event["event_id"], "lifecycle_event_kind": "EFFECT_OBSERVED", "reservation_event_kind": "SETTLE", "registry_digest": registry_digest}),
        "expected_revision": registry["core"]["revision"], "kind": "SETTLE", "clock": copy.deepcopy(registry_request["event"]["clock"]),
        "payload": {"native": native, "histories": histories}, "administration": None,
    }
    host = host_for(registry_digest, registry_request["host_evidence"]["selection_evidence"], histories, native)
    budget_input["request"] = reservation_request(registry, reservation_event, host)
    budget_input["expected_revision"] = registry["core"]["revision"]
    value["state"] = copy.deepcopy(state)
    value["state_digest"] = case["expected"]["state_digest"]
    core = copy.deepcopy(registry["core"])
    core["effects"].append(effect_record(native, "UNKNOWN", "UNKNOWN_OUTCOME", []))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    result = reservation_transition(registry, reservation_event, host, core, "UNKNOWN", reservation_id=native["reservation"], reasons=[])
    budget_output = {"registry_digest": registry_digest, "affected_anchors": copy.deepcopy(budget_input["affected_anchors"]), "result": result}
    expected = B2.budget_effect_result(
        None, {"state": state}, event, budget_output, classification="UNKNOWN", disposition="OUTCOME_RETAINED",
        reason_codes=["UNKNOWN_OUTCOME"], occurrence_status=None, disputed=False,
    )
    emit(
        "C2-unknown-after-authorized-release", "step", value, expected, ["LIFE-010", "RES-WIRE-003"],
        "The checkpoint is D2-271's result: an authorized no-effect conclusion released the reservation, completed the occurrence NO_EFFECT and completed the instance. A clean OUTCOME_UNKNOWN record for the same permit and dispatch now arrives, with completion_mismatch false. LIFE-010 retains an unknown record after SETTLED or RELEASED without changing that conclusion, and the prior-state table gives the row SETTLED or RELEASED; later UNKNOWN: receipt UNKNOWN, retain the native evidence and prior terminal state, change no exposure. Only a later EFFECT takes the late-after-release row. The reservation therefore stays RELEASED with a new UNKNOWN effect record, the outcome is not disputed, the completed occurrence and the COMPLETE instance are unchanged, and LIFE-006 gives OUTCOME_RETAINED with UNKNOWN_OUTCOME.",
    )


def duplicate_with_newer_history() -> None:
    case = load("reservation-edges/D2-146.json")
    base = case["input"]
    state = base["state"]
    prior = next(row for row in state["core"]["effects"] if row["id"] == "native-effect")
    native = copy.deepcopy(prior["native"])
    native["id"] = "native-effect-repeat"
    native["evidence_ref"] = "evidence-native-effect-repeat"
    history = copy.deepcopy(state["core"]["budgets"][0]["history"])
    appended = copy.deepcopy(history["journal"][-1])
    appended["sequence"] = str(int(appended["sequence"]) + 1)
    appended["event"]["id"] = "later-committed-event"
    history["journal"].append(appended)
    history["revision"] = appended["sequence"]
    history["as_of"] = base["event"]["clock"]["instant"]
    event = {
        "id": "event-c2-duplicate-newer-history", "expected_revision": state["core"]["revision"], "kind": "SETTLE",
        "clock": copy.deepcopy(base["event"]["clock"]), "payload": {"native": native, "histories": [history]}, "administration": None,
    }
    host = host_for(base["host_evidence"]["registry_digest"], base["host_evidence"]["selection_evidence"], [history], native)
    expected = reservation_transition(state, event, host, state["core"], "SETTLED", reservation_id="reserve-a")
    emit(
        "C2-duplicate-with-newer-history", "aggregate-step", reservation_request(state, event, host), expected, ["RES-WIRE-003"],
        "The registry holds a SETTLED reservation with its matched effect record. A second SETTLE carries the same native fact under a new identity, together with a supplied history that has since gained one later committed journal entry for another event. RESERVATION-RECORDS gives SETTLED; duplicate matching EFFECT: receipt SETTLED, remain SETTLED, add no committed or pending exposure, and a duplicate returns the established disposition without repeating an effect record or charge. LIFECYCLE gives the same result for exact or same-fact duplicates. Duplicate recognition follows the native fact, not the accompanying history. The history-revision rule marks a SETTLED reservation DISPUTED only when newly admitted history revises or retracts a prescribed event, and the added entry does neither. The repair-round ruling of 2026-09-13 recorded in CONTRACT-DECISIONS.md settles the remaining question: a duplicate retry stores none of the newer history, so no registry fact other than the revision and receipt changes.",
    )


def unknown_keeps_blocked_dispute() -> None:
    base, facts, _proposal, permitted = B2.initial_budget_success(instance_id="case-d2-230", event_id="proposal-d2-230")
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    dispatch = B2.dispatch_event(base, permitted, event_id="dispatch-d2-230", attempt_status="SENT", attempted_at=INSTANT, clock_revision="1")
    dispatched = B2.dispatch_result(permitted, dispatch, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")
    case = load("governed-budget-disputes/D2-230.json")
    state = case["expected"]["state"]
    registry = case["expected"]["budget_results"][0]["result"]["state"]
    after = {**dispatched, "state": state, "state_digest": case["expected"]["state_digest"]}
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-c2-unknown-blocked", status="OUTCOME_UNKNOWN", event_time=None, observed_at=INSTANT)
    record = native_record(facts, "UNKNOWN", evidence["evidence_id"], reservation_id=reservation_id, completion_mismatch=False, mismatch_reason=None)
    record["provider"] = evidence["provider"]
    record["source"] = evidence["source"]
    record["evidence_ref"] = evidence["evidence_ref"]
    registry_digest = digest("reservation-registry", registry["core"]["configuration"])
    event_id = "effect-c2-unknown-blocked"
    embedded_id = digest("lifecycle-reservation-event", {"instance_id": state["instance_id"], "lifecycle_event_id": event_id, "lifecycle_event_kind": "EFFECT_OBSERVED", "reservation_event_kind": "SETTLE", "registry_digest": registry_digest})
    history = registry["core"]["budgets"][0]["history"]
    reservation_event, host = host_and_event(facts, "SETTLE", embedded_id, registry["core"]["revision"], {"native": record, "histories": [history]}, event_clock=facts["clock"], administration=None)
    budget_input = {"registry_digest": registry_digest, "affected_anchors": ["license-spend"], "expected_revision": registry["core"]["revision"], "request": reservation_request(registry, reservation_event, host)}
    event = governed_effect_event(permitted, after, evidence, event_id=event_id, budget_inputs=[budget_input], clock_revision="1")
    reservation_row = next(row for row in registry["core"]["reservations"] if row["id"] == reservation_id)
    blocked = [{"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_row["contributions"]]
    core = copy.deepcopy(registry["core"])
    core["effects"].append(effect_record(record, "DISPUTED", "UNKNOWN_OUTCOME", blocked))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    result = reservation_transition(registry, reservation_event, host, core, "EFFECT_DISPUTED", reservation_id=reservation_id, reasons=["UNKNOWN_OUTCOME"])
    budget_output = {"registry_digest": registry_digest, "affected_anchors": ["license-spend"], "result": result}
    outcome = governed_outcome(event, after, classification="UNKNOWN", disputed=True, reservation_receipt_digests=[result["receipt_digest"]])

    def mutate(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    expected = admitted_transition(
        state, event, disposition="DISPUTED",
        reason_codes=["BUDGET_EFFECT_DISPUTED", "UNKNOWN_OUTCOME"],
        details=[
            {"kind": "BUDGET", "registry_digest": registry_digest, "receipt_digest": result["receipt_digest"], "reasons": ["UNKNOWN_OUTCOME"]},
            {"kind": "EFFECT", "classification": "UNKNOWN", "evidence_id": evidence["evidence_id"]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], budget_results=[budget_output], mutate=mutate,
    )
    emit(
        "C2-unknown-keeps-blocked-dispute", "step", step_input(base, state, event), expected, ["LIFE-010", "LIFE-013", "RES-WIRE-003"],
        "The checkpoint is D2-230's result: a conclusive MATCHED effect whose budget reconciliation was disputed, which left the occurrence BLOCKED_DISPUTE and the reservation DISPUTED. A clean OUTCOME_UNKNOWN record for the same permit and dispatch now arrives. LIFE-013 states that an UNKNOWN after a conclusive governed result is retained without changing the earlier conclusion, and that unknown or disputed reconciliation leaves the occurrence BLOCKED_DISPUTE, so the occurrence stays BLOCKED_DISPUTE; it does not fall back to OUTCOME_UNKNOWN. The disputed reservation remains DISPUTED and retains the new fact, blocking its own contribution key. RES-WIRE-004: a record with completion_mismatch false against an already DISPUTED reservation records its own effect reason, here UNKNOWN_OUTCOME, under receipt decision EFFECT_DISPUTED; LIFE-010 gives the outcome disputed true because its receipt decision is EFFECT_DISPUTED.",
    )


def foreign_duplicate_joins_conflict_group() -> None:
    case = load("foreign-effects/C2-foreign-duplicate-evidence-identity.json")
    start = case["input"]["state"]
    prior_id = "evidence-d2-118"
    conflict = copy.deepcopy(case["input"]["event"])
    conflict["event_id"] = "effect-c2-foreign-conflict"
    conflict["native_evidence"]["evidence_id"] = "evidence-c2-foreign-conflict"
    conflict["native_evidence"]["evidence_ref"] = "evidence-ref-c2-foreign-conflict"
    conflict["native_evidence"]["record_digest"] = digest("provider-native-record", {"record": "C2-FOREIGN-CONFLICT"})
    conflict_row = foreign_record(conflict, "CONFLICTING", [prior_id])

    def setup(next_state: dict) -> None:
        for row in next_state["outcomes"]:
            if row["native_evidence"]["evidence_id"] == prior_id:
                add_conflict(row, conflict["native_evidence"]["evidence_id"])
        next_state["outcomes"].append(copy.deepcopy(conflict_row))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    conflicted = admitted_transition(
        start, conflict, disposition="DISPUTED", reason_codes=["CONFLICTING_EFFECT"],
        details=[{"kind": "EFFECT", "classification": "CONFLICTING", "evidence_id": conflict["native_evidence"]["evidence_id"]}], mutate=setup,
    )
    duplicate = copy.deepcopy(case["input"]["event"])
    duplicate["event_id"] = "effect-c2-foreign-duplicate"
    duplicate["native_evidence"]["evidence_id"] = "evidence-c2-foreign-duplicate"
    duplicate["native_evidence"]["evidence_ref"] = "evidence-ref-c2-foreign-duplicate"
    duplicate["expected_state_revision"] = conflicted["state"]["revision"]
    duplicate["expected_state_digest"] = conflicted["state_digest"]
    duplicate_row = foreign_record(duplicate, "DUPLICATE", [conflict["native_evidence"]["evidence_id"]])

    def mutate(next_state: dict) -> None:
        for row in next_state["outcomes"]:
            if row["native_evidence"]["evidence_id"] == conflict["native_evidence"]["evidence_id"]:
                add_conflict(row, duplicate["native_evidence"]["evidence_id"])
        next_state["outcomes"].append(copy.deepcopy(duplicate_row))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    expected = admitted_transition(
        conflicted["state"], duplicate, disposition="OUTCOME_RETAINED", reason_codes=["DUPLICATE_EVIDENCE"],
        details=[{"kind": "EFFECT", "classification": "DUPLICATE", "evidence_id": duplicate["native_evidence"]["evidence_id"]}], mutate=mutate,
    )
    value = copy.deepcopy(case["input"])
    value["state"] = copy.deepcopy(conflicted["state"])
    value["state_digest"] = conflicted["state_digest"]
    value["event"] = duplicate
    emit(
        "C2-foreign-duplicate-joins-conflict-group", "step", value, expected, ["LIFE-010", "LIFE-013"],
        "Setup: a foreign effect is retained, then a foreign record with the same provider-native operation identity and a different record digest is retained as CONFLICTING, so the two facts form two conflict groups that list each other. The case: a third foreign record carries the first fact under a new evidence identity, so it is a DUPLICATE. LIFE-010 fixes the conflict bookkeeping: a DUPLICATE inherits the disputed value and conflict set of the retained same-fact outcome, and when that fact already conflicts with another fact, each member of the other group adds the duplicate evidence identity to its sorted conflict set; a foreign conflict list uses the same symmetric rule. The CONFLICTING row therefore lists both the original and the duplicate, the new DUPLICATE row lists the CONFLICTING record, and LIFE-006 fixes the reason set to DUPLICATE_EVIDENCE.",
    )


def renew_disputed_reservation_withheld() -> None:
    base, facts, _proposal, permitted = B2.initial_budget_success(instance_id="case-c2-renew-disputed", event_id="proposal-c2-renew-disputed")
    registry = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    changed_event = B2.dispatch_event(base, permitted, event_id="dispatch-c2-renew-disputed", attempt_status="SENT", native_request=B2.changed_request(permitted), attempted_at=INSTANT, clock_revision="1")
    changed = B2.dispatch_result(permitted, changed_event, disposition="DISPUTED", reasons=["NATIVE_ARGUMENT_MISMATCH"], occurrence_status="BLOCKED_DISPUTE")
    evidence = B2.governed_native_evidence(base, permitted, changed, evidence_id="evidence-c2-renew-disputed", status="OUTCOME_UNKNOWN", observed_at=INSTANT)
    _dispute_input, dispute_output = B2.effect_budget_input(
        facts, registry, reservation_id, "effect-c2-renew-disputed", evidence_status="OUTCOME_UNKNOWN",
        completion_mismatch=True, mismatch_reason="NATIVE_REQUEST_MISMATCH", evidence=evidence,
    )
    disputed = dispute_output["result"]["state"]
    current = RN.advance_clock(base, permitted, event_id="clock-before-c2-renew-disputed")
    renewal, _authority_input, authority_result = RN.renewal_event(base, current, "C2-renew-disputed")
    renew_input, _ = RN.renew_for_proposal(base, facts, disputed, renewal, authority_result=authority_result)
    request = renew_input["request"]
    core = copy.deepcopy(disputed["core"])
    for budget in core["budgets"]:
        budget["history"] = RN.renewal_history(facts)
    expected = reservation_transition(
        disputed, request["event"], request["host_evidence"], core, "WITHHELD",
        reservation_id=reservation_id, budgets=[], authority_result=authority_result, reasons=["EXPOSURE_DISPUTED"],
    )
    emit(
        "C2-renew-disputed-reservation-withheld", "aggregate-step", request, expected, ["RES-WIRE-004"],
        "Setup: a changed-argument dispatch reports an unknown outcome, so the registry retains the fact as disputed exposure and the reservation becomes DISPUTED. The case: a well-formed RENEW names that reservation with current authority and a complete history. RES-WIRE-004 states that an already DISPUTED reservation cannot be renewed or released and that WITHHELD with EXPOSURE_DISPUTED retains it, so this is an admitted policy decision, not an admission refusal: the receipt is WITHHELD with reason EXPOSURE_DISPUTED and no aggregate judgment, the reservation keeps its DISPUTED status and permit, and the revision advances. The supplied history is current and complete, so it updates the budget journal as for any admitted renewal decision; RESERVATION-RECORDS withholds that update only for stale or unavailable history.",
    )


def foreign_effect_conflicts_no_effect() -> None:
    case = load("failure-no-effect/D2-099.json")
    state = case["expected"]["state"]
    state_digest = case["expected"]["state_digest"]
    no_effect = next(row for row in state["outcomes"] if row["native_evidence"]["status"] == "NO_EFFECT_ESTABLISHED")
    evidence = copy.deepcopy(no_effect["native_evidence"])
    attributed = evidence["attributed_request"]
    evidence.update({
        "evidence_id": "evidence-c2-foreign-no-effect-conflict", "evidence_ref": "evidence-ref-c2-foreign-no-effect-conflict",
        "status": "EFFECT_ESTABLISHED", "record_type": "card-result", "record_digest": digest("provider-native-record", {"record": "C2-FOREIGN-NO-EFFECT"}),
        "event_time": INSTANT, "observed_at": INSTANT, "collections": [], "rules_out_past_and_future_effects": False,
        "actual_fields": sorted(copy.deepcopy(attributed["fields"]) + [{"name": "status", "value": {"type_ref": "STRING", "value": "ISSUED"}}], key=lambda row: row["name"].encode("utf-8")),
    })
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "effect-c2-foreign-no-effect-conflict", "kind": "EFFECT_OBSERVED",
        "instance_id": state["instance_id"], "expected_state_revision": state["revision"], "expected_state_digest": state_digest,
        "permit": None, "dispatch_digest": None, "native_evidence": evidence, "completion_authorization": None,
        "reservation_id": None, "affected_budget_anchors": [], "budget_inputs": [], "clock_revision": None, "activation_clocks": [],
    }
    row = foreign_record(event, "CONFLICTING", [no_effect["native_evidence"]["evidence_id"]])

    def mutate(next_state: dict) -> None:
        for outcome in next_state["outcomes"]:
            if outcome["native_evidence"]["evidence_id"] == no_effect["native_evidence"]["evidence_id"]:
                add_conflict(outcome, evidence["evidence_id"])
        next_state["outcomes"].append(copy.deepcopy(row))
        next_state["outcomes"].sort(key=lambda value: value["outcome_digest"].encode("utf-8"))

    expected = admitted_transition(
        state, event, disposition="DISPUTED", reason_codes=["CONFLICTING_EFFECT"],
        details=[{"kind": "EFFECT", "classification": "CONFLICTING", "evidence_id": evidence["evidence_id"]}], mutate=mutate,
    )
    value = copy.deepcopy(case["input"])
    value["state"] = copy.deepcopy(state)
    value["state_digest"] = state_digest
    value["event"] = event
    emit(
        "C2-foreign-effect-conflicts-no-effect", "step", value, expected, ["LIFE-010", "LIFE-013"],
        "The checkpoint is D2-099's result: a governed NO_EFFECT_ESTABLISHED conclusion for provider-native operation native-operation-1 completed the work. A foreign established effect for that same provider-native operation identity now arrives. LIFE-013 makes a second conclusive record with the same provider-native operation identity and different content conflicting evidence, and a no-effect conclusion is conclusive. LIFE-010 classifies a changed conclusive foreign fact as CONFLICTING and applies the symmetric conflict rule to foreign lists, so the foreign row lists the no-effect evidence, the governed no-effect outcome adds the foreign evidence and becomes disputed, and LIFE-006 fixes the reason set to CONFLICTING_EFFECT. The foreign record changes no current occurrence.",
    )


def collection_keeps_observed_request() -> None:
    base, facts, permitted, dispatched, registry, reservation_id = BEC.dispatched_budget_permit("case-c2-collection", "C2-collection")
    collections = [{"name": "extra_items", "element_type_ref": "IDENTITY", "values": [{"type_ref": "IDENTITY", "value": "x-1"}]}]
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-c2-collection", status="EFFECT_ESTABLISHED", event_time=INSTANT, observed_at=INSTANT, collections=collections)
    record = native_record(facts, "EFFECT", evidence["evidence_id"], reservation_id=reservation_id, completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT", effect_id=evidence["native_operation_id"])
    for key in ("provider", "source", "evidence_ref", "rules_out_past_and_future_effects"):
        record[key] = evidence[key]
    record["actual_fields"] = copy.deepcopy(evidence["actual_fields"])
    record["collections"] = copy.deepcopy(collections)
    record["occurred_at"] = evidence["event_time"]
    reservation_row = next(row for row in registry["core"]["reservations"] if row["id"] == reservation_id)
    blocked = [{"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_row["contributions"]]
    budget_input, budget_output = GCS.settle(
        facts, registry, reservation_id, "effect-c2-collection", record, facts["history"],
        decision="EFFECT_DISPUTED", disposition="DISPUTED", reason="UNEXPECTED_EFFECT", blocked=blocked,
    )
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-c2-collection", budget_inputs=[budget_input], clock_revision=BEC.REGISTRY_CLOCK_REVISION)
    expected = B2.budget_effect_result(
        base, dispatched, event, budget_output, classification="UNEXPECTED", disposition="DISPUTED",
        reason_codes=["BUDGET_EFFECT_DISPUTED", "UNEXPECTED_EFFECT"], occurrence_status="OUTCOME_UNKNOWN", disputed=True,
    )
    emit(
        "C2-collection-keeps-observed-request", "step", step_input(base, dispatched["state"], event), expected, ["LIFE-010", "RES-WIRE-003"],
        "A budget-backed operation step's matching effect carries a collection its completion carrier does not declare, so the record is completion-mismatched and the lifecycle classification is UNEXPECTED. LIFE-010 defines observed_request from the evidence fields alone: it is the dispatch-attributed request when every completion binding maps the actual fields back to that exact request, and null only when a field is missing, extra, inconsistent or unprojectable; RES-WIRE-003 calls it the complete operation-field projection when that projection is possible. The fields here project exactly, so the embedded record keeps the projected request with completion_mismatch true and mismatch_reason UNEXPECTED_EFFECT. The registry retains the fact as disputed exposure, blocking the reservation's original partition, which is also the projected one; the occurrence becomes OUTCOME_UNKNOWN and LIFE-006 adds BUDGET_EFFECT_DISPUTED and the receipt reason to UNEXPECTED_EFFECT.",
    )


def status_outside_lists_keeps_observed_request() -> None:
    base, facts, permitted, dispatched, registry, reservation_id = BEC.dispatched_budget_permit("case-c2-status-outside", "C2-status-outside")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-c2-status-outside", status="EFFECT_ESTABLISHED", event_time=INSTANT, observed_at=INSTANT)
    step = next(row for row in base["definition"]["steps"] if row["id"] == permitted["permit"]["occurrence"]["step_id"])
    completion = step["completion"]
    status_row = next(row for row in evidence["actual_fields"] if row["name"] == completion["status_field"])
    status_row["value"]["value"] = "HELD_FOR_REVIEW"
    assert all(value["value"] != "HELD_FOR_REVIEW" for value in completion["success_values"] + completion["failure_values"])
    record = native_record(facts, "EFFECT", evidence["evidence_id"], reservation_id=reservation_id, completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT", effect_id=evidence["native_operation_id"])
    for key in ("provider", "source", "evidence_ref", "rules_out_past_and_future_effects"):
        record[key] = evidence[key]
    record["actual_fields"] = copy.deepcopy(evidence["actual_fields"])
    record["occurred_at"] = evidence["event_time"]
    assert record["observed_request"] == record["request"]
    reservation_row = next(row for row in registry["core"]["reservations"] if row["id"] == reservation_id)
    blocked = [{"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_row["contributions"]]
    budget_input, budget_output = GCS.settle(
        facts, registry, reservation_id, "effect-c2-status-outside", record, facts["history"],
        decision="EFFECT_DISPUTED", disposition="DISPUTED", reason="UNEXPECTED_EFFECT", blocked=blocked,
    )
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-c2-status-outside", budget_inputs=[budget_input], clock_revision=BEC.REGISTRY_CLOCK_REVISION)
    expected = B2.budget_effect_result(
        base, dispatched, event, budget_output, classification="UNEXPECTED", disposition="DISPUTED",
        reason_codes=["BUDGET_EFFECT_DISPUTED", "UNEXPECTED_EFFECT"], occurrence_status="OUTCOME_UNKNOWN", disputed=True,
    )
    emit(
        "C2-status-outside-lists-keeps-observed-request", "step", step_input(base, dispatched["state"], event), expected, ["LIFE-010", "RES-WIRE-003"],
        "A budget-backed operation step's effect evidence matches the permitted request in every bound field but its status field carries HELD_FOR_REVIEW, which is in neither the success nor the failure values. LIFE-010 makes the classification UNEXPECTED, so the embedded record has completion_mismatch true with UNEXPECTED_EFFECT. observed_request is null only when a field is missing, extra, inconsistent or unprojectable; the status field is declared and typed, and every completion binding maps an actual field back to the exact request, so observed_request is the attributed request. The registry retains the fact as disputed exposure with UNEXPECTED_EFFECT, blocking the reservation's original partition, which is also the projected one; the occurrence becomes OUTCOME_UNKNOWN and LIFE-006 gives DISPUTED with BUDGET_EFFECT_DISPUTED and UNEXPECTED_EFFECT.",
    )

BUILDERS = [
    status_outside_lists_keeps_observed_request,
    duplicate_retry_of_duplicate_row, unknown_after_authorized_release, duplicate_with_newer_history, unknown_keeps_blocked_dispute,
    foreign_duplicate_joins_conflict_group, renew_disputed_reservation_withheld, foreign_effect_conflicts_no_effect, collection_keeps_observed_request,
]


def main() -> None:
    for build in BUILDERS:
        build()
    print(json.dumps({"output": str(GROUP), "case_ids": sorted(path.stem for path in GROUP.glob("*.json"))}, indent=2))


if __name__ == "__main__":
    main()
