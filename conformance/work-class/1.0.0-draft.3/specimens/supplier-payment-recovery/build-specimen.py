#!/usr/bin/env python3
"""Construct source revision 2 and financial recovery traces without a consumer."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REVIEW = HERE.parents[1] / "review"
sys.path.insert(0, str(REVIEW))
from corpus_common import canonical_bytes, digest
from lifecycle_factory import admitted_transition, replay_result, stateful_refusal
from recovery_fixture import configuration, disposition_expected, dispose_request, generation, normalize_native, policy_issue, target_for
from recovery_lifecycle_fixture import PROJECTION_KEYS, dispute_prerequisite, work_dispose_request
from reservation_fixture import effect_record, host_and_event, request as registry_request, transition as registry_transition


def load_base():
    path = HERE.parent / "supplier-payment/build-specimen.py"
    spec = importlib.util.spec_from_file_location("supplier_payment_revision2_base", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = HERE
    original = module.build_static_contract

    def selected_contract():
        source, work, authority_source, authority_class = original()
        source.update(revision="r2", status="CONSTRUCTED_PENDING_VERIFICATION",
            recovery_source="../../review/fixtures/supplier-payment-recovery-revision2-source.md")
        source["recovery_sections"] = [
            {"section": "02", "requirements": ["REC-003", "REC-004", "REC-005", "REC-016"]},
            {"section": "03", "requirements": ["REC-006", "REC-012", "REC-013"]},
            {"section": "04", "requirements": ["REC-007", "REC-012", "REC-013"]},
            {"section": "05", "requirements": ["REC-002", "REC-005", "REC-008", "REC-009", "REC-010"]},
            {"section": "06", "requirements": ["REC-011", "REC-016"]},
            {"section": "07", "requirements": ["REC-012", "REC-013", "REC-014"]},
            {"section": "08", "requirements": ["REC-002", "REC-015", "REC-016"]},
        ]
        work.update(revision="r2", recovery=configuration())
        work["source"]["revision"] = "r2"
        authority_source["revision"] = authority_class["revision"] = "r2"
        return source, work, authority_source, authority_class

    module.build_static_contract = selected_contract
    return module


def read(name):
    return json.loads((HERE / name).read_text())


def write(name, value):
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def request_row(base, name, operation, supplied):
    return base.protocol_request(name, operation, supplied)


def result_row(base, request, result):
    return {"protocol": base.PROTOCOL, "request_id": request["request_id"], "operation": request["operation"], "result": result}


def lifecycle_input(definition, state, event, **extra):
    return {"profile": definition["profile"], "role": "LINEAR_WORK_RUNTIME", "specification_pin": definition["specification_pin"],
        "definition": definition, "definition_digest": digest("work-class-definition", definition),
        "state": state, "state_digest": work_digest(state), "event": event, **extra}


def work_digest(state):
    value = copy.deepcopy(state)
    for replay in value["replays"]:
        replay.pop("transaction_digest", None)
    return digest("work-state", value)


def disputed_payment(base, supplied):
    """Derive the existing unexpected-151 result from LIFE-010 and RES-007."""
    event = supplied["event"]
    registry_request = event["budget_inputs"][0]["request"]
    registry_before = registry_request["state"]
    native = registry_request["event"]["payload"]["native"]
    core = copy.deepcopy(registry_before["core"])
    core["reservations"][0]["status"] = "DISPUTED"
    core["effects"].append(effect_record(native, "DISPUTED", "UNEXPECTED_EFFECT",
        [{"anchor": "supplier-payment-cap", "key": None}],
        affected_anchors=["supplier-payment-cap"]))
    core["budgets"][0]["history"] = copy.deepcopy(registry_request["event"]["payload"]["histories"][0])
    registry_result = registry_transition(registry_before, registry_request["event"], registry_request["host_evidence"],
        core, "EFFECT_DISPUTED", reservation_id=native["reservation"], reasons=["UNEXPECTED_EFFECT"])
    budget = {"registry_digest": registry_request["host_evidence"]["registry_digest"],
        "affected_anchors": ["supplier-payment-cap"], "result": registry_result}
    dispatch = next(row for row in supplied["state"]["dispatches"] if row["dispatch_digest"] == event["dispatch_digest"])
    row = {"kind": "GOVERNED", "event_id": event["event_id"], "event_digest": digest("runtime-event", event),
        "permit_digest": event["permit"]["permit_id"], "dispatch_digest": event["dispatch_digest"],
        "dispatch_attempt_digest": dispatch["dispatch_attempt_digest"], "native_evidence": copy.deepcopy(event["native_evidence"]),
        "classification": "UNEXPECTED", "reservation_receipt_digests": [registry_result["receipt_digest"]],
        "conflicts_with_evidence_ids": [], "disputed": True}
    row["outcome_digest"] = digest("outcome", row)

    def mutate(state):
        state["active"][0]["status"] = "OUTCOME_UNKNOWN"
        state["outcomes"].append(copy.deepcopy(row))
        state["outcomes"].sort(key=lambda x: x["outcome_digest"].encode())

    result = admitted_transition(supplied["state"], event, disposition="DISPUTED", reason_codes=["BUDGET_EFFECT_DISPUTED", "UNEXPECTED_EFFECT"],
        details=[{"kind": "BUDGET", "registry_digest": budget["registry_digest"], "receipt_digest": registry_result["receipt_digest"], "reasons": ["UNEXPECTED_EFFECT"]},
            {"kind": "EFFECT", "classification": "UNEXPECTED", "evidence_id": event["native_evidence"]["evidence_id"]}],
        receipt_permit_digest=event["permit"]["permit_id"], budget_results=[budget], mutate=mutate)
    return result, registry_result


def packet_for(base, state, work_state, native, conclusion, *, attempts=1):
    target = target_for(state)
    reservation = state["core"]["reservations"][0]
    permit = next(row for row in work_state["permits"] if any(x["reservation_id"] == target["reservation"] for x in row["budget_revisions"]))
    dispatch = next(row for row in work_state["dispatches"] if row["permit_digest"] == permit["permit_id"])
    request = {key: copy.deepcopy(reservation["authority"]["proposal"][key])
        for key in ("work_class", "instance", "occurrence", "step", "operation", "interface", "fields")}
    retained = [row["native"] for row in state["core"]["effects"] if row["reservation"] == target["reservation"]]
    retained += [row for d in state["core"]["recovery"]["dispositions"] if d["target"] == target for row in d["evidence"]["native_outcomes"]]
    facts = {digest("recovery-fact", normalize_native(row)) for row in retained}
    outcomes = [native] if native else []
    rows = []
    for index in range(attempts):
        rows.append({"id": dispatch["attempt"]["attempt_id"] if index == 0 else "provider-confirmed-second-possibly-sent-attempt",
            "attempt_digest": dispatch["dispatch_attempt_digest"] if index == 0 else digest("provider-attempt", {"request": request, "ordinal": str(index + 1)}),
            "executor": permit["executor"]["participant_id"], "connector": dispatch["connector"]["id"],
            "request_digest": digest("reservation-native-request", request), "maximum_executions": "1",
            "effect_ids": [native["effect_id"]] if native and native["outcome"] == "EFFECT" and index == 0 else [],
            "no_effect": conclusion == "NO_EFFECT_ESTABLISHED"})
    rows.sort(key=lambda row: row["id"].encode())
    packet = {"id": "supplier-payment-" + conclusion.lower(), "provider": "payment-provider", "source": "payment-ledger",
        "record_type": "RECOVERY_ADJUDICATION", "record_digest": digest("provider-recovery-record", {"target": target, "conclusion": conclusion}),
        "evidence_ref": "synthetic-provider-complete-invocation-and-writer-inventory", "provider_revision": "3", "target": target,
        "request": request, "covered_evidence_digests": sorted(facts | {digest("recovery-fact", normalize_native(row)) for row in outcomes}),
        "superseded_evidence_digests": sorted(facts), "attempts": rows, "conclusion": conclusion,
        "native_outcomes": outcomes, "rules_out_past_and_future_effects": conclusion == "NO_EFFECT_ESTABLISHED", "complete_attempt_inventory": True}
    return packet


def lifecycle_native(definition, disposition):
    native = disposition["evidence"]["native_outcomes"][0]
    step = next(row for row in definition["steps"] if row["id"] == native["request"]["step"])
    effect = native["outcome"] == "EFFECT"
    return {"evidence_id": native["id"], "native_operation_id": native["effect_id"] if effect else native["id"],
        "provider": native["provider"], "source": native["source"],
        "record_type": step["completion"]["effect_record_type" if effect else "no_effect_record_type"],
        "record_digest": disposition["evidence"]["record_digest"], "evidence_ref": native["evidence_ref"],
        "attributed_request": copy.deepcopy(native["request"]), "native_request_digest": digest("native-request", native["request"]),
        "status": "EFFECT_ESTABLISHED" if effect else "NO_EFFECT_ESTABLISHED", "actual_fields": copy.deepcopy(native["actual_fields"]),
        "collections": copy.deepcopy(native["collections"]), "event_time": native["occurred_at"], "observed_at": disposition["accepted_at"],
        "rules_out_past_and_future_effects": native["rules_out_past_and_future_effects"]}


def apply_request(base, definition, before, registry, disposition, event_id):
    selected = {"state": registry, "state_digest": digest("reservation-state", registry), "host_evidence": {
        "registry_digest": digest("reservation-registry", registry["core"]["configuration"]),
        "selection_evidence": "synthetic-current-authoritative-registry-selection", "administration_bases": [], "authenticated_records": []}}
    event = {"schema": base.SCHEMA + "runtime-event", "event_id": event_id, "kind": "APPLY_DISPOSITION", "instance_id": before["instance_id"],
        "expected_state_revision": before["revision"], "expected_state_digest": work_digest(before), "target": copy.deepcopy(disposition["target"]),
        "disposition_digest": disposition["id"], "registry": selected, "clock_revision": "1", "activation_clocks": []}
    host = {"caller": "payment-agent-1", "recovery_bases": [], "authenticated_records": [], "pending_evidence": []}
    return lifecycle_input(definition, before, event, recovery_host=host)


def apply_expected(supplied, disposition, *, own=True):
    before, event = supplied["state"], supplied["event"]
    prior = {key: copy.deepcopy(before[key]) for key in PROJECTION_KEYS}
    result = disposition["result"]
    reasons, details = [], []
    stops = own and before["status"] == "ACTIVE" and result == "ESTABLISH_NO_EFFECT"
    if stops:
        reasons = ["NO_EFFECT_ESTABLISHED"]
    if own and before["status"] == "ACTIVE" and result == "ESTABLISH_EFFECT":
        relation = next(row for row in supplied["definition"]["relationships"] if row["from"] == "pay-invoice")
        details = [{"kind": "ROUTE", "relationship_digests": [digest("relationship", relation)], "construct_ids": []}]

    def mutate(state):
        if own and state["status"] == "ACTIVE" and result in ("ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT"):
            active = next(row for row in state["active"] if row["occurrence"]["step_id"] == "pay-invoice")
            evidence = lifecycle_native(supplied["definition"], disposition)
            state["active"].remove(active)
            state["completed"].append({"occurrence": copy.deepcopy(active["occurrence"]), "disposition": "NO_EFFECT" if stops else "SUCCEEDED",
                "evidence_digest": digest("native-evidence", evidence), "occurred_at": evidence["event_time"] or evidence["observed_at"],
                "route_label": None, "selected_relationship_digest": details[0]["relationship_digests"][0] if details else None, "late": False})
            state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
            state["status"] = "STOPPED" if stops else "COMPLETE"
        after = {key: copy.deepcopy(state[key]) for key in PROJECTION_KEYS}
        state["recovery_records"].append({"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(supplied["recovery_host"]),
            "disposition": copy.deepcopy(disposition), "before_projection": prior, "after_projection": after})

    return admitted_transition(before, event, disposition="STOPPED" if stops else "DISPOSITION_APPLIED", reason_codes=reasons,
        details=details, receipt_recovery_disposition_digest=disposition["id"], mutate=mutate)


def financial_descendant(base, definition):
    """Resolve master evidence after the dispatched payment settles while blocked."""
    dispatched = read("restart/after-payment-dispatch-work-state.json")
    original = next(row for row in dispatched["outcomes"] if row["native_evidence"]["attributed_request"]["step"] == "change-supplier-destination")
    master_permit = next(row for row in dispatched["permits"] if row["permit_id"] == original["permit_digest"])
    master_dispatch = next(row for row in dispatched["dispatches"] if row["dispatch_digest"] == original["dispatch_digest"])
    chain = {"definition": definition, "definition_digest": digest("work-class-definition", definition), "before_dispute": dispatched,
        "change_evidence": original["native_evidence"], "change_permit": master_permit,
        "change_dispatch": master_dispatch, "change_occurrence": master_permit["occurrence"]}
    conflict_input, conflict_result = dispute_prerequisite(chain)
    payment_input = copy.deepcopy(read("valid-trace/requests.json")[-1]["input"])
    event = payment_input["event"]
    event.update(event_id="retain-financial-result-while-master-blocked", expected_state_revision=conflict_result["state"]["revision"],
        expected_state_digest=conflict_result["state_digest"])
    payment_input["state"], payment_input["state_digest"] = conflict_result["state"], conflict_result["state_digest"]
    budget = event["budget_inputs"][0]
    selected = budget["request"]
    registry_before = read("restart/after-payment-dispatch-budget-state.json")
    selected["state"], selected["state_digest"] = registry_before, digest("reservation-state", registry_before)
    selected["event"]["id"] = digest("lifecycle-reservation-event", {"instance_id": event["instance_id"], "lifecycle_event_id": event["event_id"],
        "lifecycle_event_kind": "EFFECT_OBSERVED", "reservation_event_kind": "SETTLE", "registry_digest": budget["registry_digest"]})
    selected["event"]["expected_revision"] = budget["expected_revision"] = registry_before["core"]["revision"]
    native = selected["event"]["payload"]["native"]
    core = copy.deepcopy(registry_before["core"])
    core["budgets"][0]["history"] = copy.deepcopy(selected["event"]["payload"]["histories"][0])
    core["reservations"][0].update(status="SETTLED", matched_effect=native["effect_id"])
    core["effects"].append(effect_record(native, "MATCHED", "MATCHED_EFFECT", affected_anchors=["supplier-payment-cap"]))
    settled = registry_transition(registry_before, selected["event"], selected["host_evidence"], core, "SETTLED", reservation_id=native["reservation"])
    budget_result = {"registry_digest": budget["registry_digest"], "affected_anchors": budget["affected_anchors"], "result": settled}
    dispatch = next(row for row in dispatched["dispatches"] if row["dispatch_digest"] == event["dispatch_digest"])
    outcome = {"kind": "GOVERNED", "event_id": event["event_id"], "event_digest": digest("runtime-event", event),
        "permit_digest": event["permit"]["permit_id"], "dispatch_digest": event["dispatch_digest"],
        "dispatch_attempt_digest": dispatch["dispatch_attempt_digest"], "native_evidence": copy.deepcopy(event["native_evidence"]),
        "classification": "MATCHED", "reservation_receipt_digests": [settled["receipt_digest"]], "conflicts_with_evidence_ids": [], "disputed": False}
    outcome["outcome_digest"] = digest("outcome", outcome)

    def retain(state):
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode())

    retained = admitted_transition(payment_input["state"], event, disposition="OUTCOME_RETAINED", reason_codes=["DEPENDENCY_DISPUTED"],
        details=[{"kind": "BUDGET", "registry_digest": budget["registry_digest"], "receipt_digest": settled["receipt_digest"], "reasons": []},
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]}],
        receipt_permit_digest=event["permit"]["permit_id"], budget_results=[budget_result], mutate=retain)
    recovery = work_dispose_request(chain, retained["state"], event_id="restore-master-and-complete-retained-payment")
    recovery["recovery_registries"] = [{"state": settled["state"], "state_digest": settled["state_digest"], "host_evidence": {
        "registry_digest": budget["registry_digest"], "selection_evidence": "synthetic-current-settled-payment-selection",
        "administration_bases": [], "authenticated_records": []}}]
    before, recovery_event = recovery["state"], recovery["event"]
    identity = {"incident_digest": digest("recovery-incident", {"principal": before["deployment_organization_id"], "target": recovery_event["target"]}),
        "generation_digest": generation(recovery_event["evidence"]), "result": "ESTABLISH_EFFECT", "policy_digest": None,
        "controller": recovery_event["controller"], "supersedes": None}
    disposition = {"id": digest("recovery-disposition", identity), **identity, "acceptance_basis_digest": None,
        "target": copy.deepcopy(recovery_event["target"]), "evidence": copy.deepcopy(recovery_event["evidence"]),
        "event_digest": digest("runtime-event", recovery_event), "accepted_at": base.NOW, "source_event": copy.deepcopy(recovery_event)}
    relation = next(row for row in definition["relationships"] if row["from"] == "pay-invoice")
    relation_digest = digest("relationship", relation)

    def complete(state):
        prior = {key: copy.deepcopy(before[key]) for key in PROJECTION_KEYS}
        active = next(row for row in state["active"] if row["occurrence"]["step_id"] == "pay-invoice")
        evidence = event["native_evidence"]
        state["completed"].append({"occurrence": copy.deepcopy(active["occurrence"]), "disposition": "SUCCEEDED",
            "evidence_digest": digest("native-evidence", evidence), "occurred_at": evidence["event_time"], "route_label": None,
            "selected_relationship_digest": relation_digest, "late": False})
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["active"].remove(active)
        state["status"] = "COMPLETE"
        state["recovery_records"].append({"event": copy.deepcopy(recovery_event), "host_evidence": copy.deepcopy(recovery["recovery_host"]),
            "disposition": disposition, "before_projection": prior, "after_projection": {key: copy.deepcopy(state[key]) for key in PROJECTION_KEYS},
            "registry_selections": copy.deepcopy(recovery["recovery_registries"])})

    restored = admitted_transition(before, recovery_event, disposition="DISPOSITION_RECORDED", reason_codes=[],
        details=[{"kind": "ROUTE", "relationship_digests": [relation_digest], "construct_ids": []}],
        receipt_recovery_disposition_digest=disposition["id"], mutate=complete)
    replay = copy.deepcopy(recovery)
    replay.update(state=copy.deepcopy(restored["state"]), state_digest=restored["state_digest"])
    replayed = replay_result(restored["state"], recovery_event["event_id"])
    omitted = copy.deepcopy(replay)
    omitted["state"]["recovery_records"][0].pop("registry_selections")
    omitted["state_digest"] = work_digest(omitted["state"])
    return [conflict_input, payment_input, recovery, replay, omitted], [conflict_result, retained, restored, replayed, stateful_refusal(omitted["state"], "STATE_INVALID")]


def main():
    base = load_base()
    base.main(configuration())
    definition = read("work-class.json")
    rows = read("scenarios/requests.json")
    unexpected = next(row for row in rows if row["request_id"] == "effect-payment-unexpected-a-1")
    disputed_work, disputed_registry = disputed_payment(base, unexpected["input"])
    initial_history = read("shared-budget-register-input.json")["event"]["payload"]["history"]
    registry = disputed_registry["state"]
    facts = {"configuration": registry["core"]["configuration"], "clock": unexpected["input"]["event"]["budget_inputs"][0]["request"]["event"]["clock"],
        "budget": registry["core"]["budgets"][0]["definition"], "history": initial_history,
        "authority_a": registry["core"]["reservations"][0]["authority"]}
    traces, expectations = {}, []

    def record(name, requests, results, text, refs):
        write("recovery/" + name + "/requests.json", requests)
        write("recovery/" + name + "/results-derived.json", [result_row(base, req, result) for req, result in zip(requests, results, strict=True)])
        traces[name] = {"requests": requests, "results": results}
        expectations.append({"id": name, "requests": "recovery/" + name + "/requests.json", "derivation": text, "normative_references": refs})

    for result in ("ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT", "LEAVE_UNRESOLVED"):
        history = copy.deepcopy(registry["core"]["budgets"][0]["history"])
        native = None
        if result != "LEAVE_UNRESOLVED":
            native = copy.deepcopy(registry["core"]["effects"][0]["native"])
            native.update(id="payment-authoritative-" + result.lower(), completion_mismatch=False, mismatch_reason=None,
                evidence_ref="synthetic-authoritative-payment-correction", observed_request=copy.deepcopy(native["request"]))
            corrected = copy.deepcopy(history["journal"][-1]["event"])
            if result == "ESTABLISH_EFFECT":
                next(row for row in native["actual_fields"] if row["name"] == "amount")["value"]["value"] = "150"
                next(row for row in corrected["fields"] if row["name"] == "amount")["value"]["value"] = "150"
            else:
                native.update(outcome="NO_EFFECT", effect_id=None, occurred_at=None, observed_request=None,
                    actual_fields=[], collections=[], rules_out_past_and_future_effects=True)
                corrected = {"id": corrected["id"], "state": "RETRACTED"}
            history.update(revision="3", evidence_ref="synthetic-complete-corrected-payment-history")
            history["journal"].append({"sequence": "3", "event": corrected})
        packet = packet_for(base, registry, disputed_work["state"], native,
            "EFFECT_ESTABLISHED" if result == "ESTABLISH_EFFECT" else "NO_EFFECT_ESTABLISHED" if result == "ESTABLISH_NO_EFFECT" else "UNRESOLVED")
        supplied = dispose_request(facts, registry, result, event_id="financial-" + result.lower(), evidence=packet, histories=[history])
        disposed = disposition_expected(supplied)
        disposition = disposed["state"]["core"]["recovery"]["dispositions"][0]
        applied_input = apply_request(base, definition, disputed_work["state"], disposed["state"], disposition, "apply-financial-" + result.lower())
        applied = apply_expected(applied_input, disposition)
        requests = [unexpected, request_row(base, supplied["event"]["id"], "aggregate-step", supplied),
            request_row(base, applied_input["event"]["event_id"], "step", applied_input)]
        record(result.lower(), requests, [disputed_work, disposed, applied],
            "Retain the original unexpected 151 USD conclusion and its journal prefix. The protected authoritative packet either corrects that same execution to the authorized 150 USD, disproves past/future execution with a journal reversal, or leaves it unresolved. Registry accounting commits before local application. The completed basis uses the selected packet-native conversion, never the superseded 151 USD outcome.",
            ["REC-003", "REC-004", "REC-006", "REC-007", "REC-013", "REC-015"])
        if result == "ESTABLISH_NO_EFFECT":
            no_effect_state = disposed["state"]
        if result == "ESTABLISH_EFFECT":
            restored_registry, restored_disposition = disposed["state"], disposition

    unknown_work = read("restart/after-payment-unknown-work-state.json")
    unknown_registry = read("restart/after-payment-unknown-budget-state.json")
    unknown_facts = {**facts, "configuration": unknown_registry["core"]["configuration"]}
    duplicate_native = copy.deepcopy(unknown_registry["core"]["effects"][0]["native"])
    duplicate_native.update(id="provider-duplicate-send-uncertainty", evidence_ref="synthetic-attributable-duplicate-send-uncertainty",
        completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT")
    duplicate_event, duplicate_host = host_and_event(unknown_facts, "SETTLE", "retain-duplicate-send-uncertainty", unknown_registry["core"]["revision"],
        {"native": duplicate_native, "histories": [initial_history]}, administration=False)
    duplicate_core = copy.deepcopy(unknown_registry["core"])
    duplicate_core["reservations"][0]["status"] = "DISPUTED"
    duplicate_core["effects"].append(effect_record(duplicate_native, "DISPUTED", "UNEXPECTED_EFFECT",
        [{"anchor": "supplier-payment-cap", "key": None}], affected_anchors=["supplier-payment-cap"]))
    duplicate_core["effects"].sort(key=lambda row: row["id"].encode())
    duplicate_input = registry_request(unknown_registry, duplicate_event, duplicate_host)
    duplicate_result = registry_transition(unknown_registry, duplicate_event, duplicate_host, duplicate_core, "EFFECT_DISPUTED",
        reservation_id=duplicate_native["reservation"], reasons=["UNEXPECTED_EFFECT"])
    issue, issued = policy_issue(unknown_facts, duplicate_result["state"])
    policy_digest = issue["event"]["payload"]["policy_digest"]
    packet = packet_for(base, issued["state"], unknown_work, None, "UNRESOLVED", attempts=2)
    bounded = dispose_request(unknown_facts, issued["state"], "ACCEPT_UNRESOLVED", event_id="financial-150-plus-150",
        evidence=packet, policy_digest=policy_digest)
    rejected = disposition_expected(bounded, reasons=["BOUND_VIOLATED", "RECOVERY_ALLOWANCE_EXCEEDED", "RECOVERY_INCIDENT_LIMIT_EXCEEDED"], effective_result="LEAVE_UNRESOLVED")
    record("bounded-uncertainty-rejected", [request_row(base, duplicate_event["id"], "aggregate-step", duplicate_input),
        request_row(base, issue["event"]["id"], "aggregate-step", issue), request_row(base, bounded["event"]["id"], "aggregate-step", bounded)],
        [duplicate_result, issued, rejected],
        "An attributable duplicate-send report establishes an operational dispute beyond the ordinary unknown result. Two independently bounded possible executions of the unchanged 150 USD request retain 300 USD uncertainty. The whole case exceeds both the 5 USD incident and 10 USD rolling allowance limits, and 800 + 300 exceeds the ordinary 1000 USD ceiling. Withhold clearance, retain the extra 150 USD contingent row, and consume no exception allowance.",
        ["REC-008", "REC-009", "REC-010", "AGG-008"])

    # Instance B has a separate completed supplier-change prerequisite and no payment invocation.
    other = read("instances/b/payment-active-state.json")
    other_apply = apply_request(base, definition, other, restored_registry, restored_disposition, "apply-shared-disposition-instance-b")
    other_expected = apply_expected(other_apply, restored_disposition, own=False)
    record("shared-instance-propagation", [request_row(base, other_apply["event"]["event_id"], "step", other_apply)], [other_expected],
        "The same authoritative registry disposition is applied against instance B's own revision. It records the selection and application without completing B's different payment occurrence, changing its supplier-master fact, or repeating registry accounting.", ["REC-013", "REC-015"])

    fresh = copy.deepcopy(next(row for row in rows if row["request_id"] == "propose-payment-b-1"))
    nested = fresh["input"]["event"]["budget_inputs"][0]
    nested["expected_revision"] = no_effect_state["core"]["revision"]
    nested["request"]["state"], nested["request"]["state_digest"] = no_effect_state, digest("reservation-state", no_effect_state)
    nested["request"]["event"]["expected_revision"] = no_effect_state["core"]["revision"]
    nested["request"]["event"]["payload"]["histories"] = [no_effect_state["core"]["budgets"][0]["history"]]
    nested["request"]["host_evidence"]["authenticated_records"] = [{"kind": "HISTORY", "record_digest": digest("budget-history", no_effect_state["core"]["budgets"][0]["history"]), "provider": "payment-provider", "source": "payment-ledger"}]
    write("recovery/fresh-work-after-no-effect/request.json", fresh)
    expectations.append({"id": "fresh-work-after-no-effect", "requests": "recovery/fresh-work-after-no-effect/request.json",
        "expected": {"status": "STEP", "disposition": "PERMITTED", "instance_id": "supplier-payment-instance-b", "budget_decision": "RESERVED", "ordinary_total": "950"},
        "derivation": "The stopped invocation in A is affirmatively excluded from future execution. B supplies its separately deployed instance, independent occurrence, exact supplier-master evidence and current payment authority. Its fresh 150 USD reservation fits 800 committed exposure. The source permits no resend in A.", "normative_references": ["REC-007", "REC-013", "LIFE-007", "RES-005"]})

    descendant_requests, descendant_results = financial_descendant(base, definition)
    record("retained-financial-descendant", [request_row(base, "financial-descendant-" + str(index + 1), "step", supplied)
        for index, supplied in enumerate(descendant_requests)], descendant_results,
        "The supplier-master prerequisite becomes disputed after payment dispatch. Exact matching payment evidence settles the registry while local completion remains blocked. Work-only adjudication establishes the original master fact and uses the complete current registry selection to apply the retained payment once. Its application retains registry_selections; fresh replay reconstructs the same completion and a rehashed checkpoint omitting that selection is refused.",
        ["REC-012", "REC-013", "REC-014", "REC-015", "LIFE-010"])

    write("recovery/expectations.json", {"candidate_pin": base.PIN, "status": "DERIVED_BEFORE_CONSUMER_EXECUTION", "scenarios": expectations})
    write("source-coverage.json", {"status": "SYNTHETIC_MAPPING_PENDING_EXTERNAL_REVIEW", "candidate_pin": base.PIN,
        "original_source_obligations": read("source-policy.json")["obligations"],
        "original_work_correspondence": "correspondence-record.json", "recovery_source_sections": read("source-policy.json")["recovery_sections"],
        "recovery_configuration": "work-class.json#/recovery", "shared_registry_configuration": "shared-budget-register-input.json#/state/core/configuration/recovery",
        "external_policy_carrier": "recovery/bounded-uncertainty-rejected/requests.json", "recovery_traces": "recovery/expectations.json",
        "limits": ["The typed work-source correspondence covers the seven original obligations and labels recovery representation paths unsupported.",
            "This supplemental record maps source2 recovery requirements across normative profiles, registry policy and lifecycle evidence; it is not a human-approved correspondence act.",
            "Governance designations, provider records and complete-writer assertions are synthetic fixtures, not deployment proof."]})
    index = {"candidate_pin": base.PIN, "construction": "SOURCE_AND_CONTRACT_DERIVED_WITHOUT_CONSUMER_OUTPUT", "status": "CONSTRUCTED_PENDING_VERIFICATION", "files": []}
    for path in sorted(HERE.rglob("*.json")) + sorted(HERE.rglob("*.jsonl")):
        if path.name == "artifact-index.json":
            continue
        index["files"].append({"path": path.relative_to(HERE).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    write("artifact-index.json", index)
    print(json.dumps({"specimen": str(HERE), "financial_recovery_scenarios": str(len(expectations)), "consumer_execution": False}))


if __name__ == "__main__":
    main()
