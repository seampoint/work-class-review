"""Rule-derived supplier prerequisite recovery and complete retained projections."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path

from corpus_common import canonical_bytes, digest
from dependency_dispute_common import apply_dependency_block
from lifecycle_factory import admitted_transition
from recovery_fixture import authorize, configuration, generation, normalize_native


PBR = runpy.run_path(str(Path(__file__).with_name("build-prior-binding-restart-cases.py")))
PROJECTION_KEYS = ("status", "active", "completed", "obligations", "deadlines", "total_activations", "total_actuations", "step_counters", "fanout_passes")


def supplier_chain(*, permitted_payment: bool = False) -> dict:
    source, definition, authority_source, authority_work_class = PBR["build_static_contract"]()
    definition["recovery"] = configuration()
    # This bounded prerequisite trace does not propose a monetary payment. The full
    # recovery specimen separately binds its shared payment registry and policy.
    payment_step = next(x for x in definition["steps"] if x["id"] == "pay-invoice")
    payment_step["shared_budgets"] = []
    payment_step["fields"].append({"name": "request_count", "type_ref": "t.count"})
    payment_step["fields"].sort(key=lambda x: x["name"].encode())
    payment_step["completion"]["evidence_bindings"] = [{"request_field": x["name"], "evidence_field": x["name"]} for x in payment_step["fields"]]
    definition["shared_budgets"] = []
    next(x for x in authority_work_class["steps"] if x["id"] == "pay-invoice")["fields"] = copy.deepcopy(payment_step["fields"])
    dd = digest("work-class-definition", definition)
    deploy_input, deploy_result, state0, change_occurrence = PBR["build_deployment"](definition, "supplier-recovery-prerequisite")
    clock_event = PBR["clock_event"](state0, "recovery-clock", source="governance-clock", revision="1", observed_time=PBR["NOW"])
    state1, clock_result = PBR["accepted_clock"](state0, clock_event)
    fields = [PBR["field"]("destination_account", "t.identity", "acct-new"), PBR["field"]("request_count", "t.count", "1"), PBR["field"]("supplier_id", "t.identity", "supplier-17")]
    authority = PBR["build_authority"](authority_source, authority_work_class, instance_id=state1["instance_id"],
        occurrence_row=change_occurrence, step_id="change-supplier-destination", envelope_id="supplier-change-authority",
        executor_id="supplier-master-agent-1", executor_role="supplier-master-agent", credential_kind="supplier-master-credential",
        gate_kind="VERIFY", gate_actor="destination-confirmer-person", gate_role="destination-confirmer",
        subject_fields=["supplier_id"], resource_fields=["destination_account"], proposal_fields=fields, required_budgets=[])
    proposal = PBR["proposal_event"](state1, change_occurrence, authority, fields, event_id="recovery-change-proposal")
    permit = PBR["permit"](dd, proposal, authority)
    state2, permitted = PBR["permitted_result"](state1, proposal, permit, authority)
    state3, dispatched, dispatch = PBR["dispatch_result"](state2, "recovery-change-dispatch", permit)
    state4, completed, payment_occurrence, established = PBR["change_effect_result"](definition, dd, state3, change_occurrence, permit, dispatch, fields)
    chain = {"source": source, "definition": definition, "definition_digest": dd, "authority_source": authority_source,
        "authority_work_class": authority_work_class, "change_occurrence": change_occurrence,
        "change_permit": permit, "change_evidence": established, "change_dispatch": dispatch, "change_authority": authority,
        "payment_occurrence": payment_occurrence, "before_dispute": state4,
        "requests": [("deploy", deploy_input), ("step", PBR["lifecycle_input"](definition, dd, state0, clock_event)),
            ("step", PBR["lifecycle_input"](definition, dd, state1, proposal)),
            ("step", PBR["lifecycle_input"](definition, dd, state2, {k: v for k, v in dispatch_event_from_record(state2, permit, dispatch).items()})),
            ("step", PBR["lifecycle_input"](definition, dd, state3, completed_event(completed, permit, dispatch, established, state3)))],
        "results": [deploy_result, clock_result, permitted, dispatched, completed]}
    if permitted_payment:
        payment_fields = [PBR["field"]("amount", "t.money", "150"), PBR["field"]("destination_account", "t.identity", "acct-new"),
            PBR["field"]("invoice_id", "t.identity", "invoice-44"), PBR["field"]("request_count", "t.count", "1"), PBR["field"]("supplier_id", "t.identity", "supplier-17")]
        payment_authority = PBR["build_authority"](authority_source, authority_work_class, instance_id=state4["instance_id"],
            occurrence_row=payment_occurrence, step_id="pay-invoice", envelope_id="invoice-payment-authority", executor_id="payment-agent-1",
            executor_role="payment-agent", credential_kind="payment-credential", gate_kind="DECIDE", gate_actor="payment-releaser-person",
            gate_role="payment-releaser", subject_fields=["supplier_id"], resource_fields=["destination_account", "invoice_id"],
            proposal_fields=payment_fields, required_budgets=[])
        payment_proposal = PBR["proposal_event"](state4, payment_occurrence, payment_authority, payment_fields, event_id="recovery-payment-proposal")
        payment_permit = PBR["permit"](dd, payment_proposal, payment_authority,
            prior_effect_bases=PBR["prior_effect_bases"](change_occurrence, permit, established),
            separation_bases=[PBR["separation_basis"](change_occurrence, payment_occurrence, authority, payment_authority)])
        state5, permitted_result = PBR["permitted_result"](state4, payment_proposal, payment_permit, payment_authority)
        chain["before_dispute"] = state5
        chain["payment_permit"] = payment_permit
        chain["requests"].append(("step", PBR["lifecycle_input"](definition, dd, state4, payment_proposal)))
        chain["results"].append(permitted_result)
    return chain


def dispatch_event_from_record(before: dict, permit: dict, record: dict) -> dict:
    return {"schema": PBR["SCHEMA"] + "runtime-event", "event_id": record["event_id"], "kind": "DISPATCH_OBSERVED",
        "instance_id": before["instance_id"], "expected_state_revision": before["revision"], "expected_state_digest": PBR["work_state_digest"](before),
        "permit": copy.deepcopy(permit), **{k: copy.deepcopy(record[k]) for k in ("native_request", "connector", "attempt", "acknowledgement", "clock_revision")}}


def completed_event(result: dict, permit: dict, dispatch: dict, evidence: dict, before: dict) -> dict:
    return {"schema": PBR["SCHEMA"] + "runtime-event", "event_id": result["decision"]["event_id"], "kind": "EFFECT_OBSERVED",
        "instance_id": before["instance_id"], "expected_state_revision": before["revision"], "expected_state_digest": PBR["work_state_digest"](before),
        "permit": copy.deepcopy(permit), "dispatch_digest": dispatch["dispatch_digest"], "native_evidence": copy.deepcopy(evidence),
        "completion_authorization": None, "budget_inputs": [], "clock_revision": None, "activation_clocks": []}


def dispute_prerequisite(chain: dict) -> tuple[dict, dict]:
    before = chain["before_dispute"]
    evidence = copy.deepcopy(chain["change_evidence"])
    evidence.update(evidence_id="supplier-master-conflicting-report", evidence_ref="supplier-master-conflicting-report-ref",
        record_digest=digest("provider-native-record", {"record": "conflicting-master-report"}), event_time="2026-09-11T11:59:59Z")
    event = completed_event({"decision": {"event_id": "retain-master-conflict"}}, chain["change_permit"], chain["change_dispatch"], evidence, before)
    ed = digest("runtime-event", event)
    original_id = chain["change_evidence"]["evidence_id"]
    row = {"kind": "GOVERNED", "event_id": event["event_id"], "event_digest": ed,
        "permit_digest": chain["change_permit"]["permit_id"], "dispatch_digest": chain["change_dispatch"]["dispatch_digest"],
        "dispatch_attempt_digest": chain["change_dispatch"]["dispatch_attempt_digest"], "native_evidence": evidence,
        "classification": "CONFLICTING", "reservation_receipt_digests": [], "conflicts_with_evidence_ids": [original_id], "disputed": True}
    row["outcome_digest"] = digest("outcome", row)

    def mutate(state, _event_digest):
        old = next(x for x in state["outcomes"] if x["native_evidence"]["evidence_id"] == original_id)
        old.update(disputed=True, conflicts_with_evidence_ids=[evidence["evidence_id"]])
        old["outcome_digest"] = digest("outcome", {k: v for k, v in old.items() if k != "outcome_digest"})
        state["outcomes"].append(copy.deepcopy(row))
        state["outcomes"].sort(key=lambda x: x["outcome_digest"].encode())
        apply_dependency_block(state, chain["change_occurrence"]["occurrence_id"])

    _, result = PBR["work_transition"](before, event, disposition="DISPUTED", reasons=["CONFLICTING_EFFECT"],
        details=[{"kind": "EFFECT", "classification": "CONFLICTING", "evidence_id": evidence["evidence_id"]}],
        permit=None, budget_results=[], authority_result_digest=None, reservation_receipt_digests=[], mutate=mutate)
    return PBR["lifecycle_input"](chain["definition"], chain["definition_digest"], before, event), result


def work_dispose_request(chain: dict, before: dict, *, result: str = "ESTABLISH_EFFECT", event_id: str = "resolve-master-conflict") -> dict:
    original = next(x for x in before["outcomes"] if x["native_evidence"]["evidence_id"] == chain["change_evidence"]["evidence_id"])
    target = {"kind": "WORK_OUTCOME", "instance_id": before["instance_id"],
        "occurrence_id": chain["change_occurrence"]["occurrence_id"], "outcome_digest": original["outcome_digest"]}
    permit, dispatch = chain["change_permit"], chain["change_dispatch"]
    nr = {"work_class": chain["definition"]["id"], "instance": before["instance_id"], "occurrence": target["occurrence_id"],
        "step": chain["change_occurrence"]["step_id"], **copy.deepcopy(permit["native_request"])}
    effect = result == "ESTABLISH_EFFECT"
    noeffect = result == "ESTABLISH_NO_EFFECT"
    native = copy.deepcopy(chain["change_evidence"])
    if noeffect:
        native.update(status="NO_EFFECT_ESTABLISHED", event_time=None, actual_fields=[],
            rules_out_past_and_future_effects=True)
        step = next(x for x in chain["definition"]["steps"] if x["id"] == chain["change_occurrence"]["step_id"])
        native["record_type"] = step["completion"]["no_effect_record_type"]
    retained = [x["native_evidence"] for x in before["outcomes"] if x["permit_digest"] == permit["permit_id"]]
    retained += [native for row in before["recovery_records"] if row["disposition"]["target"] == target
        for native in row["disposition"]["evidence"]["native_outcomes"]]
    facts = sorted({digest("recovery-fact", normalize_native(x)) for x in retained})
    packet = {"id": "supplier-master-adjudication", "provider": native["provider"], "source": native["source"],
        "record_type": "RECOVERY_ADJUDICATION", "record_digest": digest("provider-recovery-record", {"target": target, "result": result}),
        "evidence_ref": "authenticated-master-adjudication", "provider_revision": "3", "target": target, "request": nr,
        "covered_evidence_digests": sorted(set(facts) | ({digest("recovery-fact", normalize_native(native))} if effect or noeffect else set())), "superseded_evidence_digests": facts,
        "attempts": [{"id": dispatch["attempt"]["attempt_id"], "attempt_digest": dispatch["dispatch_attempt_digest"],
            "executor": permit["executor"]["participant_id"], "connector": dispatch["connector"]["id"],
            "request_digest": digest("reservation-native-request", nr), "maximum_executions": "1",
            "effect_ids": [native["native_operation_id"]] if effect else [], "no_effect": noeffect}],
        "conclusion": "EFFECT_ESTABLISHED" if effect else "NO_EFFECT_ESTABLISHED" if noeffect else "UNRESOLVED",
        "native_outcomes": [native] if effect or noeffect else [], "rules_out_past_and_future_effects": noeffect, "complete_attempt_inventory": True}
    event = {"schema": PBR["SCHEMA"] + "runtime-event", "event_id": event_id, "kind": "DISPOSE", "instance_id": before["instance_id"],
        "expected_state_revision": before["revision"], "expected_state_digest": PBR["work_state_digest"](before),
        "target": target, "requested_result": result, "evidence": packet, "controller": None, "policy_digest": None,
        "supersedes": None, "clock_revision": "1", "activation_clocks": []}
    host = {"caller": "supplier-master-agent-1", "recovery_bases": [], "authenticated_records": [{"kind": "RECOVERY_EVIDENCE",
        "record_digest": digest("recovery-evidence", packet), "provider": packet["provider"], "source": packet["source"]}], "pending_evidence": []}
    if effect or noeffect:
        authority_facts = {"configuration": {"principal": before["deployment_organization_id"], "recovery": chain["definition"]["recovery"]},
            "clock": {"instant": PBR["NOW"]}}
        authorize(authority_facts, event, host, operation=result, scope_digest=digest("recovery-target", target))
    supplied = PBR["lifecycle_input"](chain["definition"], chain["definition_digest"], before, event)
    supplied["recovery_host"] = host
    return supplied


def work_dispose_expected(supplied: dict, *, restored_status: str = "ACTIVE") -> dict:
    event, before = supplied["event"], supplied["state"]
    incident = digest("recovery-incident", {"principal": before["deployment_organization_id"], "target": event["target"]})
    identity = {"incident_digest": incident, "generation_digest": generation(event["evidence"]), "result": event["requested_result"],
        "policy_digest": None, "controller": event["controller"], "supersedes": event["supersedes"]}
    record = {"id": digest("recovery-disposition", identity), **identity, "acceptance_basis_digest": None,
        "target": copy.deepcopy(event["target"]), "evidence": copy.deepcopy(event["evidence"]),
        "event_digest": digest("runtime-event", event), "accepted_at": PBR["NOW"], "source_event": copy.deepcopy(event)}
    prior_projection = {key: copy.deepcopy(before[key]) for key in PROJECTION_KEYS}

    def mutate(state):
        if state["status"] == "ACTIVE":
            if event["requested_result"] == "ESTABLISH_NO_EFFECT":
                state["status"] = "STOPPED"
            elif event["requested_result"] == "ESTABLISH_EFFECT":
                for active in state["active"]:
                    if active["status"] == "BLOCKED_DISPUTE":
                        active["status"] = restored_status
        if state["status"] in ("ACTIVE", "STOPPED") and event["requested_result"] == "LEAVE_UNRESOLVED" and any(
            row["disposition"]["id"] == event["supersedes"]
            and row["disposition"]["target"] == event["target"]
            and row["disposition"]["result"] == "ESTABLISH_EFFECT"
            for row in state["recovery_records"]
        ):
            apply_dependency_block(state, event["target"]["occurrence_id"])
        after_projection = {key: copy.deepcopy(state[key]) for key in PROJECTION_KEYS}
        state["recovery_records"].append({"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(supplied["recovery_host"]),
            "disposition": record, "before_projection": prior_projection, "after_projection": after_projection})

    stops = before["status"] == "ACTIVE" and event["requested_result"] == "ESTABLISH_NO_EFFECT"
    return admitted_transition(before, event, disposition="STOPPED" if stops else "DISPOSITION_RECORDED",
        reason_codes=["RECOVERY_BASIS_CHANGED"] if stops else [], details=[],
        receipt_recovery_disposition_digest=record["id"], mutate=mutate)
