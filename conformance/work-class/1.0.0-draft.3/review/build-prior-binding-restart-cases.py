#!/usr/bin/env python3
"""Build exact prior-effect and actor-separation restart vectors."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

from corpus_common import CASES, exact_case, write_canonical_json


SUPPLIER = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "specimens" / "supplier-payment" / "build-specimen.py")
)

GROUP = CASES / "prior-binding-restart"
SCHEMA = SUPPLIER["SCHEMA"]
PIN = SUPPLIER["PIN"]
PROFILE = SUPPLIER["PROFILE"]
ROLE = SUPPLIER["ROLE"]
NOW = SUPPLIER["NOW"]
PERMIT_EXPIRY = SUPPLIER["PERMIT_EXPIRY"]
build_authority = SUPPLIER["build_authority"]
build_deployment = SUPPLIER["build_deployment"]
build_static_contract = SUPPLIER["build_static_contract"]
canonical_bytes = SUPPLIER["canonical_bytes"]
digest = SUPPLIER["digest"]
field = SUPPLIER["field"]
omit = SUPPLIER["omit"]
sorted_utf8 = SUPPLIER["sorted_utf8"]
typed = SUPPLIER["typed"]
work_state_digest = SUPPLIER["work_state_digest"]
work_transition = SUPPLIER["work_transition"]


def lifecycle_input(definition: dict, definition_digest: str, state: dict, event: dict) -> dict:
    return {
        "profile": PROFILE,
        "role": ROLE,
        "specification_pin": PIN,
        "definition": copy.deepcopy(definition),
        "definition_digest": definition_digest,
        "state": copy.deepcopy(state),
        "state_digest": work_state_digest(state),
        "event": copy.deepcopy(event),
    }


def refusal(state: dict, code: str) -> dict:
    return {
        "status": "REFUSED",
        "profile": PROFILE,
        "role": ROLE,
        "code": code,
        "path": "",
        "state": copy.deepcopy(state),
        "state_digest": work_state_digest(state),
        "budget_states": [],
    }


def clock_event(state: dict, event_id: str, *, source: str, revision: str, observed_time: str) -> dict:
    clock = {
        "source": source,
        "revision": revision,
        "status": "AVAILABLE",
        "observed_time": observed_time,
        "evidence_digest": digest(
            "specimen-clock-evidence",
            {"source": source, "revision": revision, "time": observed_time},
        ),
    }
    return {
        "schema": SCHEMA + "runtime-event",
        "event_id": event_id,
        "kind": "CLOCK",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": work_state_digest(state),
        "clock": clock,
        "activation_clocks": [],
    }


def accepted_clock(state: dict, event: dict) -> tuple[dict, dict]:
    def mutate(next_state: dict, _event_digest: str) -> None:
        next_state["clocks"].append(copy.deepcopy(event["clock"]))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    return work_transition(
        state,
        event,
        disposition="CLOCK_RECORDED",
        reasons=[],
        details=[
            {
                "kind": "CLOCK",
                "source": event["clock"]["source"],
                "revision": event["clock"]["revision"],
                "status": event["clock"]["status"],
            }
        ],
        permit=None,
        budget_results=[],
        authority_result_digest=None,
        reservation_receipt_digests=[],
        mutate=mutate,
    )


def lifecycle_executor(authority: dict) -> dict:
    return {
        "participant_id": authority["executor"]["actor"],
        "role": authority["executor"]["role"],
        "binding_digest": digest("executor-binding", authority["executor"]),
    }


def proposal_event(
    state: dict,
    occurrence: dict,
    authority: dict,
    fields: list[dict],
    *,
    event_id: str,
) -> dict:
    step = authority["input"]["proposal"]
    return {
        "schema": SCHEMA + "runtime-event",
        "event_id": event_id,
        "kind": "PROPOSE",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": work_state_digest(state),
        "occurrence": copy.deepcopy(occurrence),
        "native_request": {
            "interface": step["interface"],
            "operation": step["operation"],
            "fields": copy.deepcopy(fields),
        },
        "executor": lifecycle_executor(authority),
        "credential_ids": [authority["credential"]["id"]],
        "authority_input": copy.deepcopy(authority["input"]),
        "budget_inputs": [],
        "clock_revision": "1",
        "observation_digests": sorted_utf8(
            [digest("authority-observation", row) for row in authority["input"]["observations"]]
        ),
    }


def authority_act_bases(authority: dict) -> list[dict]:
    return sorted(
        [
            {"act_digest": digest("authority-act", row), "act": copy.deepcopy(row)}
            for row in authority["acts"]
        ],
        key=lambda row: row["act_digest"].encode("utf-8"),
    )


def permit(
    definition_digest: str,
    event: dict,
    authority: dict,
    *,
    prior_effect_bases: list[dict] | None = None,
    separation_bases: list[dict] | None = None,
) -> dict:
    without_id = {
        "schema": SCHEMA + "permit",
        "instance_id": event["instance_id"],
        "work_class_digest": definition_digest,
        "profile": PROFILE,
        "role": ROLE,
        "occurrence": copy.deepcopy(event["occurrence"]),
        "proposal_digest": digest("proposal", event),
        "native_request": copy.deepcopy(event["native_request"]),
        "executor": copy.deepcopy(event["executor"]),
        "credential_ids": copy.deepcopy(event["credential_ids"]),
        "authority_result": copy.deepcopy(authority["result"]),
        "authority_result_digest": authority["result_digest"],
        "authority_evidence_digest": authority["result"]["evidence_digest"],
        "authority_act_bases": authority_act_bases(authority),
        "prior_effect_bases": copy.deepcopy(prior_effect_bases or []),
        "separation_bases": copy.deepcopy(separation_bases or []),
        "observation_digests": copy.deepcopy(event["observation_digests"]),
        "supersedes_permit_digest": None,
        "budget_revisions": [],
        "clock_source": authority["input"]["clock"]["source"],
        "clock_revision": event["clock_revision"],
        "expires_at": PERMIT_EXPIRY,
    }
    return {"permit_id": digest("permit", without_id), **without_id}


def permitted_result(state: dict, event: dict, permit_value: dict, authority: dict) -> tuple[dict, dict]:
    event_digest = digest("runtime-event", event)

    def mutate(next_state: dict, _event_digest: str) -> None:
        next_state["total_actuations"] = str(int(next_state["total_actuations"]) + 1)
        next(
            row for row in next_state["step_counters"] if row["step_id"] == event["occurrence"]["step_id"]
        )["actuations"] = str(
            int(next(row for row in state["step_counters"] if row["step_id"] == event["occurrence"]["step_id"])["actuations"]) + 1
        )
        active = next(
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] == event["occurrence"]["occurrence_id"]
        )
        active["status"] = "PERMITTED"
        next_state["proposals"].append(
            {
                "event_id": event["event_id"],
                "event_digest": event_digest,
                "proposal_digest": digest("proposal", event),
                "occurrence_id": event["occurrence"]["occurrence_id"],
                "disposition": "PERMITTED",
                "permit_digest": permit_value["permit_id"],
                "authority_result_digest": authority["result_digest"],
                "reservation_receipt_digests": [],
                "prior_permit_digest": None,
            }
        )
        next_state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
        next_state["permits"].append(copy.deepcopy(permit_value))
        next_state["permits"].sort(key=lambda row: row["permit_id"].encode("utf-8"))

    return work_transition(
        state,
        event,
        disposition="PERMITTED",
        reasons=[],
        details=[],
        permit=permit_value,
        budget_results=[],
        authority_result_digest=authority["result_digest"],
        reservation_receipt_digests=[],
        mutate=mutate,
    )


def dispatch_result(state: dict, event: dict, permit_value: dict) -> tuple[dict, dict, dict]:
    native_request = copy.deepcopy(permit_value["native_request"])
    connector_subject = {"id": event + "-connector", "version": "v1"}
    connector = {**connector_subject, "binding_digest": digest("connector-binding", connector_subject)}
    attempt = {
        "attempt_id": event + "-attempt",
        "status": "SENT",
        "request_digest": digest(
            "dispatch-native-request",
            {
                "instance_id": state["instance_id"],
                "occurrence_id": permit_value["occurrence"]["occurrence_id"],
                "interface": native_request["interface"],
                "operation": native_request["operation"],
                "fields": native_request["fields"],
            },
        ),
        "attempted_at": NOW,
    }
    acknowledgement = {"status": "ACCEPTED", "reference": event + "-ack", "observed_at": NOW}
    dispatch_event = {
        "schema": SCHEMA + "runtime-event",
        "event_id": event,
        "kind": "DISPATCH_OBSERVED",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": work_state_digest(state),
        "permit": copy.deepcopy(permit_value),
        "native_request": native_request,
        "connector": connector,
        "attempt": attempt,
        "acknowledgement": acknowledgement,
        "clock_revision": "1",
    }
    event_digest = digest("runtime-event", dispatch_event)
    attempt_digest = digest(
        "dispatch-attempt",
        {
            "permit_id": permit_value["permit_id"],
            "native_request": native_request,
            "connector": connector,
            "attempt": attempt,
        },
    )
    without_digest = {
        "dispatch_attempt_digest": attempt_digest,
        "event_id": event,
        "event_digest": event_digest,
        "permit_digest": permit_value["permit_id"],
        "native_request": native_request,
        "connector": connector,
        "attempt": attempt,
        "acknowledgement": acknowledgement,
        "clock_revision": "1",
    }
    record = {"dispatch_digest": digest("dispatch", without_digest), **without_digest}

    def mutate(next_state: dict, _event_digest: str) -> None:
        next(
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] == permit_value["occurrence"]["occurrence_id"]
        )["status"] = "DISPATCHED"
        next_state["dispatches"].append(copy.deepcopy(record))
        next_state["dispatches"].sort(key=lambda row: row["dispatch_digest"].encode("utf-8"))

    after, result = work_transition(
        state,
        dispatch_event,
        disposition="ACKNOWLEDGED",
        reasons=[],
        details=[{"kind": "DISPATCH", "attempt_id": attempt["attempt_id"], "reasons": []}],
        permit=None,
        budget_results=[],
        authority_result_digest=None,
        reservation_receipt_digests=[],
        mutate=mutate,
    )
    return after, result, record


def change_effect_result(
    definition: dict,
    definition_digest: str,
    state: dict,
    change_occurrence: dict,
    change_permit: dict,
    dispatch: dict,
    fields: list[dict],
) -> tuple[dict, dict, dict, dict]:
    attributed = {
        "work_class": definition["id"],
        "instance": state["instance_id"],
        "occurrence": change_occurrence["occurrence_id"],
        "step": change_occurrence["step_id"],
        "operation": change_permit["native_request"]["operation"],
        "interface": change_permit["native_request"]["interface"],
        "fields": copy.deepcopy(fields),
    }
    actual_fields = copy.deepcopy(fields) + [field("status", "t.status", "SUCCEEDED")]
    actual_fields.sort(key=lambda row: row["name"].encode("utf-8"))
    evidence = {
        "evidence_id": "change-effect",
        "native_operation_id": "supplier-master-native-1",
        "provider": "supplier-master-provider",
        "source": "supplier-master-ledger",
        "record_type": "supplier-master-change",
        "record_digest": digest("specimen-native-record", {"actual_fields": actual_fields}),
        "evidence_ref": "change-effect-record",
        "attributed_request": attributed,
        "native_request_digest": digest("native-request", attributed),
        "status": "EFFECT_ESTABLISHED",
        "actual_fields": actual_fields,
        "collections": [],
        "event_time": NOW,
        "observed_at": NOW,
        "rules_out_past_and_future_effects": False,
    }
    event = {
        "schema": SCHEMA + "runtime-event",
        "event_id": "effect-change",
        "kind": "EFFECT_OBSERVED",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": work_state_digest(state),
        "permit": copy.deepcopy(change_permit),
        "dispatch_digest": dispatch["dispatch_digest"],
        "native_evidence": evidence,
        "completion_authorization": None,
        "budget_inputs": [],
        "clock_revision": None,
        "activation_clocks": [],
    }
    event_digest = digest("runtime-event", event)
    relationship = next(
        row for row in definition["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == change_occurrence["step_id"]
    )
    relationship_digest = digest("relationship", relationship)
    payment_occurrence = SUPPLIER["occurrence"](
        definition_digest,
        state["instance_id"],
        "pay-invoice",
        "1",
        [change_occurrence["occurrence_id"]],
    )
    without_outcome_digest = {
        "kind": "GOVERNED",
        "event_id": event["event_id"],
        "event_digest": event_digest,
        "permit_digest": change_permit["permit_id"],
        "dispatch_digest": dispatch["dispatch_digest"],
        "dispatch_attempt_digest": dispatch["dispatch_attempt_digest"],
        "native_evidence": evidence,
        "classification": "MATCHED",
        "reservation_receipt_digests": [],
        "conflicts_with_evidence_ids": [],
        "disputed": False,
    }
    outcome = {"outcome_digest": digest("outcome", without_outcome_digest), **without_outcome_digest}

    def mutate(next_state: dict, _event_digest: str) -> None:
        next_state["total_activations"] = str(int(next_state["total_activations"]) + 1)
        next(row for row in next_state["step_counters"] if row["step_id"] == "pay-invoice")["activations"] = "1"
        next_state["active"] = [
            {
                "occurrence": copy.deepcopy(payment_occurrence),
                "activation_event_digest": event_digest,
                "status": "ACTIVE",
                "deadline_ids": [],
            }
        ]
        next_state["completed"].append(
            {
                "occurrence": copy.deepcopy(change_occurrence),
                "disposition": "SUCCEEDED",
                "evidence_digest": digest("native-evidence", evidence),
                "occurred_at": NOW,
                "route_label": None,
                "selected_relationship_digest": relationship_digest,
                "late": False,
            }
        )
        next_state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    after, result = work_transition(
        state,
        event,
        disposition="COMPLETED",
        reasons=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []},
        ],
        permit=None,
        budget_results=[],
        authority_result_digest=None,
        reservation_receipt_digests=[],
        mutate=mutate,
    )
    return after, result, payment_occurrence, evidence


def prior_effect_bases(change_occurrence: dict, change_permit: dict, evidence: dict) -> list[dict]:
    evidence_digest = digest("native-evidence", evidence)
    rows = [
        {
            "binding_id": "payment-account-from-master",
            "source_occurrence_id": change_occurrence["occurrence_id"],
            "source_permit_digest": change_permit["permit_id"],
            "source_native_evidence_digest": evidence_digest,
            "source_field": "destination_account",
            "target_field": "destination_account",
            "value": typed("t.identity", "acct-new"),
        },
        {
            "binding_id": "payment-supplier-from-master",
            "source_occurrence_id": change_occurrence["occurrence_id"],
            "source_permit_digest": change_permit["permit_id"],
            "source_native_evidence_digest": evidence_digest,
            "source_field": "supplier_id",
            "target_field": "supplier_id",
            "value": typed("t.identity", "supplier-17"),
        },
    ]
    rows.sort(key=lambda row: row["binding_id"].encode("utf-8"))
    return rows


def separation_basis(
    change_occurrence: dict,
    payment_occurrence: dict,
    change_authority: dict,
    payment_authority: dict,
) -> dict:
    prior_act = next(row for row in change_authority["acts"] if row["kind"] == "VERIFY")
    current_act = next(row for row in payment_authority["acts"] if row["kind"] == "INSTANCE_DECISION")
    return {
        "requirement_id": "confirmer-differs-from-payment-releaser",
        "relation": "DISTINCT_ACTOR",
        "prior_occurrence_id": change_occurrence["occurrence_id"],
        "current_occurrence_id": payment_occurrence["occurrence_id"],
        "prior_act": {"act_digest": digest("authority-act", prior_act), "act": copy.deepcopy(prior_act)},
        "current_act": {"act_digest": digest("authority-act", current_act), "act": copy.deepcopy(current_act)},
    }


def withheld_separation_result(state: dict, event: dict, authority: dict, basis: dict) -> tuple[dict, dict]:
    event_digest = digest("runtime-event", event)

    def mutate(next_state: dict, _event_digest: str) -> None:
        next_state["proposals"].append(
            {
                "event_id": event["event_id"],
                "event_digest": event_digest,
                "proposal_digest": digest("proposal", event),
                "occurrence_id": event["occurrence"]["occurrence_id"],
                "disposition": "WITHHELD",
                "permit_digest": None,
                "authority_result_digest": authority["result_digest"],
                "reservation_receipt_digests": [],
                "prior_permit_digest": None,
            }
        )
        next_state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))

    return work_transition(
        state,
        event,
        disposition="WITHHELD",
        reasons=["SEPARATION_VIOLATED"],
        details=[
            {
                "kind": "SEPARATION",
                "authority_result": copy.deepcopy(authority["result"]),
                "basis": copy.deepcopy(basis),
            }
        ],
        permit=None,
        budget_results=[],
        authority_result_digest=authority["result_digest"],
        reservation_receipt_digests=[],
        mutate=mutate,
    )


def replay_result(state: dict, event_id: str) -> dict:
    retained = next(row for row in state["replays"] if row["event_id"] == event_id)
    return {
        "status": "STEP",
        "profile": PROFILE,
        "role": ROLE,
        "decision": copy.deepcopy(retained["decision"]),
        "decision_digest": retained["decision_receipt_digest"],
        "permit": copy.deepcopy(retained["permit"]),
        "budget_results": copy.deepcopy(retained["budget_results"]),
        "state": copy.deepcopy(state),
        "state_digest": work_state_digest(state),
        "transition_state_digest": retained["transition_state_digest"],
        "transaction_digest": retained["transaction_digest"],
        "replay": True,
    }


def tamper_separation_decision(state: dict, event_id: str) -> dict:
    changed = copy.deepcopy(state)
    receipt = next(row for row in changed["receipts"] if row["event_id"] == event_id)
    replay = next(row for row in changed["replays"] if row["event_id"] == event_id)
    detail = next(row for row in receipt["details"] if row["kind"] == "SEPARATION")
    detail["basis"]["current_act"]["act"]["actor"] = "tampered-payment-releaser"
    replacement_id = digest("decision-receipt", omit(receipt, "decision_id"))
    receipt["decision_id"] = replacement_id
    replay["decision"] = copy.deepcopy(receipt)
    replay["decision_receipt_digest"] = replacement_id
    replay["transaction_digest"] = digest(
        "lifecycle-transaction",
        {
            "state_before_digest": receipt["state_before_digest"],
            "event_digest": receipt["event_digest"],
            "decision_receipt_digest": replacement_id,
            "state_after_core_digest": receipt["state_after_core_digest"],
            "budget_results": replay["budget_results"],
        },
    )
    return changed


from checkpoint_reseal import reseal_last_transition


def build() -> list[str]:
    source, definition, authority_source, authority_work_class = build_static_contract()
    payment_step = next(row for row in definition["steps"] if row["id"] == "pay-invoice")
    payment_step["shared_budgets"] = []
    payment_step["fields"].append({"name": "request_count", "type_ref": "t.count"})
    payment_step["fields"].sort(key=lambda row: row["name"].encode("utf-8"))
    payment_step["completion"]["evidence_bindings"] = [
        {"request_field": row["name"], "evidence_field": row["name"]}
        for row in payment_step["fields"]
    ]
    payment_step["completion"]["evidence_bindings"].sort(key=lambda row: row["request_field"].encode("utf-8"))
    definition["shared_budgets"] = []
    authority_payment_step = next(row for row in authority_work_class["steps"] if row["id"] == "pay-invoice")
    authority_payment_step["fields"] = copy.deepcopy(payment_step["fields"])
    definition_digest = digest("work-class-definition", definition)
    _deploy_input, _deploy_result, state0, change_occurrence = build_deployment(definition, "prior-binding-instance")

    initial_clock = clock_event(
        state0,
        "clock-prior-binding-1",
        source="governance-clock",
        revision="1",
        observed_time=NOW,
    )
    state1, _clock_result = accepted_clock(state0, initial_clock)
    change_fields = [
        field("destination_account", "t.identity", "acct-new"),
        field("request_count", "t.count", "1"),
        field("supplier_id", "t.identity", "supplier-17"),
    ]
    change_authority = build_authority(
        authority_source,
        authority_work_class,
        instance_id=state1["instance_id"],
        occurrence_row=change_occurrence,
        step_id="change-supplier-destination",
        envelope_id="supplier-change-authority",
        executor_id="supplier-master-agent-1",
        executor_role="supplier-master-agent",
        credential_kind="supplier-master-credential",
        gate_kind="VERIFY",
        gate_actor="destination-confirmer-person",
        gate_role="destination-confirmer",
        subject_fields=["supplier_id"],
        resource_fields=["destination_account"],
        proposal_fields=change_fields,
        required_budgets=[],
    )
    change_proposal = proposal_event(
        state1,
        change_occurrence,
        change_authority,
        change_fields,
        event_id="proposal-change-prior-binding",
    )
    change_permit = permit(definition_digest, change_proposal, change_authority)
    state2, _change_proposal_result = permitted_result(state1, change_proposal, change_permit, change_authority)
    state3, _change_dispatch_result, change_dispatch = dispatch_result(
        state2,
        "dispatch-change-prior-binding",
        change_permit,
    )
    state4, _change_effect_result, payment_occurrence, change_evidence = change_effect_result(
        definition,
        definition_digest,
        state3,
        change_occurrence,
        change_permit,
        change_dispatch,
        change_fields,
    )

    payment_fields = [
        field("amount", "t.money", "150"),
        field("destination_account", "t.identity", "acct-new"),
        field("invoice_id", "t.identity", "invoice-44"),
        field("request_count", "t.count", "1"),
        field("supplier_id", "t.identity", "supplier-17"),
    ]
    payment_authority = build_authority(
        authority_source,
        authority_work_class,
        instance_id=state4["instance_id"],
        occurrence_row=payment_occurrence,
        step_id="pay-invoice",
        envelope_id="invoice-payment-authority",
        executor_id="payment-agent-1",
        executor_role="payment-agent",
        credential_kind="payment-credential",
        gate_kind="DECIDE",
        gate_actor="payment-releaser-person",
        gate_role="payment-releaser",
        subject_fields=["supplier_id"],
        resource_fields=["destination_account", "invoice_id"],
        proposal_fields=payment_fields,
        required_budgets=[],
    )
    payment_proposal = proposal_event(
        state4,
        payment_occurrence,
        payment_authority,
        payment_fields,
        event_id="proposal-payment-prior-binding",
    )
    prior_bases = prior_effect_bases(change_occurrence, change_permit, change_evidence)
    distinct_basis = separation_basis(
        change_occurrence,
        payment_occurrence,
        change_authority,
        payment_authority,
    )
    payment_permit = permit(
        definition_digest,
        payment_proposal,
        payment_authority,
        prior_effect_bases=prior_bases,
        separation_bases=[distinct_basis],
    )
    state5, payment_result = permitted_result(
        state4,
        payment_proposal,
        payment_permit,
        payment_authority,
    )

    next_clock = clock_event(
        state5,
        "clock-d2-288",
        source="governance-clock",
        revision="2",
        observed_time="2026-09-11T12:01:00Z",
    )
    _state6, clock_result = accepted_clock(state5, next_clock)
    write_canonical_json(
        GROUP / "D2-288.json",
        exact_case(
            "D2-288",
            "step",
            lifecycle_input(definition, definition_digest, state5, next_clock),
            clock_result,
            [],
            "The supplied restart checkpoint retains the exact prior-effect bases, complete authority-act preimages, and satisfied DISTINCT_ACTOR basis committed by the payment permit. Restart recomputes those bindings from the state alone. The greater governance-clock revision is therefore evaluated and recorded, advancing work state exactly once while leaving the permit and empty budget inventory unchanged.",
        ),
    )

    damaged_permit_state = copy.deepcopy(state5)
    retained_permit = next(row for row in damaged_permit_state["permits"] if row["permit_id"] == payment_permit["permit_id"])
    retained_permit["prior_effect_bases"] = retained_permit["prior_effect_bases"][1:]
    replay_permit = next(row for row in damaged_permit_state["replays"] if row["event_id"] == payment_proposal["event_id"])["permit"]
    replay_permit["prior_effect_bases"] = replay_permit["prior_effect_bases"][1:]
    # Recompute the permit identity, every record naming it and the last receipt, so the incomplete
    # basis set is the only fault rather than one of two.
    old_permit_id = retained_permit["permit_id"]
    new_permit_id = digest("permit", {key: value for key, value in retained_permit.items() if key != "permit_id"})
    retained_permit["permit_id"] = new_permit_id
    replay_permit["permit_id"] = new_permit_id
    for row in damaged_permit_state["proposals"]:
        if row["permit_digest"] == old_permit_id:
            row["permit_digest"] = new_permit_id
    assert damaged_permit_state["receipts"][-1]["permit_digest"] == old_permit_id
    damaged_permit_state["receipts"][-1]["permit_digest"] = new_permit_id
    damaged_permit_state["permits"].sort(key=lambda row: row["permit_id"].encode("utf-8"))
    reseal_last_transition(damaged_permit_state)
    invalid_permit_clock = clock_event(
        damaged_permit_state,
        "clock-d2-289",
        source="restart-probe",
        revision="1",
        observed_time="2026-09-11T12:01:00Z",
    )
    write_canonical_json(
        GROUP / "D2-289.json",
        exact_case(
            "D2-289",
            "step",
            lifecycle_input(definition, definition_digest, damaged_permit_state, invalid_permit_clock),
            refusal(damaged_permit_state, "STATE_INVALID"),
            [],
            "The restarted payment permit and its replay copy omit the first of the two prior-effect bases required by pay-invoice. The permit identifier, the proposal record and receipt that name it, and the last receipt and replay are all recomputed over the changed bytes, so every commitment in the checkpoint is internally consistent and the incomplete required basis set is the only defect. LIFE-008 makes the prior-effect basis a retained binding, and LIFE-019 requires each permit to carry exactly the prior-effect bases its active step required at proposal time and recomputes that on restart. The consumer returns STATE_INVALID before evaluating the clock event.",
        ),
    )

    write_canonical_json(
        GROUP / "D2-291.json",
        exact_case(
            "D2-291",
            "step",
            lifecycle_input(definition, definition_digest, state5, payment_proposal),
            replay_result(state5, payment_proposal["event_id"]),
            [],
            "The original payment proposal event is byte-identical to the retained replay preimage after restart. Replay identity is established before its stale expected-state revision is considered. The consumer returns the original decision, permit, prior-effect bases, separation basis, transition commitment, and transaction commitment with replay true and makes no state or budget change.",
        ),
    )

    same_actor_authority = build_authority(
        authority_source,
        authority_work_class,
        instance_id=state4["instance_id"],
        occurrence_row=payment_occurrence,
        step_id="pay-invoice",
        envelope_id="invoice-payment-authority",
        executor_id="payment-agent-1",
        executor_role="payment-agent",
        credential_kind="payment-credential",
        gate_kind="DECIDE",
        gate_actor="destination-confirmer-person",
        gate_role="payment-releaser",
        subject_fields=["supplier_id"],
        resource_fields=["destination_account", "invoice_id"],
        proposal_fields=payment_fields,
        required_budgets=[],
    )
    same_actor_proposal = proposal_event(
        state4,
        payment_occurrence,
        same_actor_authority,
        payment_fields,
        event_id="proposal-payment-same-actor",
    )
    equal_basis = separation_basis(
        change_occurrence,
        payment_occurrence,
        change_authority,
        same_actor_authority,
    )
    withheld_state, _withheld_result = withheld_separation_result(
        state4,
        same_actor_proposal,
        same_actor_authority,
        equal_basis,
    )
    tampered = tamper_separation_decision(withheld_state, same_actor_proposal["event_id"])
    invalid_separation_clock = clock_event(
        tampered,
        "clock-d2-295",
        source="restart-probe",
        revision="1",
        observed_time="2026-09-11T12:01:00Z",
    )
    write_canonical_json(
        GROUP / "D2-295.json",
        exact_case(
            "D2-295",
            "step",
            lifecycle_input(definition, definition_digest, tampered, invalid_separation_clock),
            refusal(tampered, "STATE_INVALID"),
            [],
            "The restarted WITHHELD decision retains an accepted current authority result and a DISTINCT_ACTOR failure basis. Its complete current INSTANCE_DECISION act has been changed to a different actor while the nested act_digest and authority-result commitment remain those of the original act. Receipt and replay envelope digests are recomputed so the decisive defect is the self-verifying act basis. LIFE-019 returns STATE_INVALID before evaluating the clock event.",
        ),
    )
    return ["D2-288", "D2-289", "D2-291", "D2-295"]


def main() -> None:
    print(json.dumps({"case_ids": build()}, indent=2))


if __name__ == "__main__":
    main()
