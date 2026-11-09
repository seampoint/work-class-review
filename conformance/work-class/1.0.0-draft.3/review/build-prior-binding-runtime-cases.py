#!/usr/bin/env python3
"""Build exact prior-effect and actor-separation runtime vectors."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

from composition_fixture import (
    add_authority_operations,
    parallel_definition,
    parallel_entry_result,
    permitted_operation_proposal,
    proposal_for_occurrence,
)
from authority_fixture import authority_refusal, envelope_validity_check
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import occurrence
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    governed_outcome,
    permitted_proposal,
    state_digest,
    step_input,
)


REVIEW = Path(__file__).resolve().parent
PB = runpy.run_path(str(REVIEW / "build-prior-binding-restart-cases.py"))
FANOUT = runpy.run_path(str(REVIEW / "build-fanout-cases.py"))
FANOUT_COMPLETION = runpy.run_path(str(REVIEW / "build-fanout-completion-cases.py"))
SUPPLIER = PB["SUPPLIER"]
GROUP = CASES / "prior-binding-runtime"
RESTART_GROUP = CASES / "prior-binding-restart"
SCHEMA = SUPPLIER["SCHEMA"]
PIN = SUPPLIER["PIN"]
PROFILE = SUPPLIER["PROFILE"]
ROLE = SUPPLIER["ROLE"]
NOW = SUPPLIER["NOW"]


def lifecycle_input(definition: dict, definition_digest: str, state: dict, event: dict) -> dict:
    return {
        "profile": state["profile"],
        "role": state["role"],
        "specification_pin": PIN,
        "definition": copy.deepcopy(definition),
        "definition_digest": definition_digest,
        "state": copy.deepcopy(state),
        "state_digest": PB["work_state_digest"](state),
        "event": copy.deepcopy(event),
    }


def refusal(state: dict, code: str, budget_states: list[dict] | None = None) -> dict:
    return {
        "status": "REFUSED",
        "profile": state["profile"],
        "role": state["role"],
        "code": code,
        "path": "",
        "state": copy.deepcopy(state),
        "state_digest": PB["work_state_digest"](state),
        "budget_states": copy.deepcopy(budget_states or []),
    }


def emit(
    case_id: str,
    definition: dict,
    definition_digest: str,
    state: dict,
    event: dict,
    expected: dict,
    requirements: list[str],
    derivation: str,
    *,
    group: Path = GROUP,
) -> None:
    write_canonical_json(
        group / f"{case_id}.json",
        exact_case(
            case_id,
            "step",
            lifecycle_input(definition, definition_digest, state, event),
            expected,
            requirements,
            derivation,
        ),
    )


def supplier_context(
    case_id: str,
    *,
    prior_mode: str,
    separation_rows: list[dict],
    payment_destination: str = "acct-new",
    payment_actor: str = "payment-releaser-person",
    expired_authority: bool = False,
) -> dict:
    source, definition, authority_source, authority_work_class = SUPPLIER["build_static_contract"]()
    payment_step = next(row for row in definition["steps"] if row["id"] == "pay-invoice")
    definition["shared_budgets"] = []
    payment_step["shared_budgets"] = []
    if not any(row["name"] == "request_count" for row in payment_step["fields"]):
        payment_step["fields"].append({"name": "request_count", "type_ref": "t.count"})
    payment_step["fields"].sort(key=lambda row: row["name"].encode("utf-8"))
    payment_step["completion"]["evidence_bindings"] = [
        {"request_field": row["name"], "evidence_field": row["name"]}
        for row in payment_step["fields"]
    ]
    payment_step["completion"]["evidence_bindings"].sort(
        key=lambda row: row["request_field"].encode("utf-8")
    )
    if prior_mode == "none":
        payment_step["prior_effect_bindings"] = []
    elif prior_mode == "destination":
        payment_step["prior_effect_bindings"] = [
            next(
                copy.deepcopy(row)
                for row in payment_step["prior_effect_bindings"]
                if row["target_request_field"] == "destination_account"
            )
        ]
    elif prior_mode == "future":
        template = copy.deepcopy(
            next(row for row in definition["steps"] if row["id"] == "change-supplier-destination")
        )
        template["id"] = "future-destination-source"
        template["operation"] = "future-destination-source"
        template["authority_requirements"] = ["future-destination-authority"]
        definition["steps"].append(template)
        definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
        definition["relationships"] = [
            {
                "kind": "SEQUENCE",
                "from": "change-supplier-destination",
                "to": "pay-invoice",
            },
            {"kind": "SEQUENCE", "from": "pay-invoice", "to": "future-destination-source"},
            {"kind": "SEQUENCE", "from": "future-destination-source", "to": "complete"},
        ]
        definition["occurrence_limits"].append(
            {"step_id": "future-destination-source", "maximum": "1"}
        )
        definition["occurrence_limits"].sort(key=lambda row: row["step_id"].encode("utf-8"))
        authority_template = copy.deepcopy(
            next(
                row
                for row in authority_work_class["steps"]
                if row["id"] == "change-supplier-destination"
            )
        )
        authority_template["id"] = "future-destination-source"
        authority_template["operation"] = "future-destination-source"
        authority_work_class["steps"].append(authority_template)
        authority_work_class["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
        payment_step["prior_effect_bindings"] = [
            {
                "id": "payment-account-from-future-source",
                "selection": "UNIQUE_COMPLETED_ANCESTOR",
                "source_step_id": "future-destination-source",
                "source_evidence_field": "destination_account",
                "target_request_field": "destination_account",
            }
        ]
    elif prior_mode != "all":
        raise ValueError(prior_mode)
    payment_step["prior_actor_separations"] = copy.deepcopy(separation_rows)
    payment_step["prior_actor_separations"].sort(key=lambda row: row["id"].encode("utf-8"))

    authority_payment_step = next(
        row for row in authority_work_class["steps"] if row["id"] == "pay-invoice"
    )
    authority_payment_step["fields"] = copy.deepcopy(payment_step["fields"])
    definition_digest = PB["digest"]("work-class-definition", definition)
    _deploy_input, _deploy_result, state0, change_occurrence = SUPPLIER["build_deployment"](
        definition, f"prior-binding-{case_id.lower()}"
    )
    clock = PB["clock_event"](
        state0,
        f"clock-{case_id.lower()}",
        source="governance-clock",
        revision="1",
        observed_time=NOW,
    )
    state1, _clock_result = PB["accepted_clock"](state0, clock)
    change_fields = [
        PB["field"]("destination_account", "t.identity", "acct-new"),
        PB["field"]("request_count", "t.count", "1"),
        PB["field"]("supplier_id", "t.identity", "supplier-17"),
    ]
    change_authority = SUPPLIER["build_authority"](
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
    change_proposal = PB["proposal_event"](
        state1,
        change_occurrence,
        change_authority,
        change_fields,
        event_id=f"proposal-change-{case_id.lower()}",
    )
    change_permit = PB["permit"](definition_digest, change_proposal, change_authority)
    state2, _change_proposal_result = PB["permitted_result"](
        state1, change_proposal, change_permit, change_authority
    )
    state3, _change_dispatch_result, change_dispatch = PB["dispatch_result"](
        state2, f"dispatch-change-{case_id.lower()}", change_permit
    )
    state4, _change_effect_result, payment_occurrence, change_evidence = PB[
        "change_effect_result"
    ](
        definition,
        definition_digest,
        state3,
        change_occurrence,
        change_permit,
        change_dispatch,
        change_fields,
    )
    payment_fields = [
        PB["field"]("amount", "t.money", "150"),
        PB["field"]("destination_account", "t.identity", payment_destination),
        PB["field"]("invoice_id", "t.identity", "invoice-44"),
        PB["field"]("request_count", "t.count", "1"),
        PB["field"]("supplier_id", "t.identity", "supplier-17"),
    ]
    payment_authority = SUPPLIER["build_authority"](
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
        gate_actor=payment_actor,
        gate_role="payment-releaser",
        subject_fields=["supplier_id"],
        resource_fields=["destination_account", "invoice_id"],
        proposal_fields=payment_fields,
        required_budgets=[],
        expired=expired_authority,
    )
    payment_event = PB["proposal_event"](
        state4,
        payment_occurrence,
        payment_authority,
        payment_fields,
        event_id=f"proposal-{case_id.lower()}",
    )
    return {
        "source": source,
        "definition": definition,
        "definition_digest": definition_digest,
        "state": state4,
        "change_occurrence": change_occurrence,
        "change_permit": change_permit,
        "change_evidence": change_evidence,
        "change_authority": change_authority,
        "payment_occurrence": payment_occurrence,
        "payment_authority": payment_authority,
        "payment_event": payment_event,
    }


def separation_basis(context: dict, requirement_id: str) -> dict:
    prior_act = next(
        row for row in context["change_authority"]["acts"] if row["kind"] == "VERIFY"
    )
    current_act = next(
        row
        for row in context["payment_authority"]["acts"]
        if row["kind"] == "INSTANCE_DECISION"
    )
    return {
        "requirement_id": requirement_id,
        "relation": "DISTINCT_ACTOR",
        "prior_occurrence_id": context["change_occurrence"]["occurrence_id"],
        "current_occurrence_id": context["payment_occurrence"]["occurrence_id"],
        "prior_act": {
            "act_digest": PB["digest"]("authority-act", prior_act),
            "act": copy.deepcopy(prior_act),
        },
        "current_act": {
            "act_digest": PB["digest"]("authority-act", current_act),
            "act": copy.deepcopy(current_act),
        },
    }


def authority_withheld_result(
    state: dict, event: dict, authority_refusal: dict
) -> tuple[dict, dict]:
    event_digest = PB["digest"]("runtime-event", event)
    refusal_digest = PB["digest"]("authority-result", authority_refusal)
    reason_codes = sorted(
        {"AUTHORITY_REQUIRED", authority_refusal["code"], *authority_refusal["reasons"]},
        key=lambda value: value.encode("utf-8"),
    )

    def mutate(next_state: dict, _event_digest: str) -> None:
        next_state["proposals"].append(
            {
                "event_id": event["event_id"],
                "event_digest": event_digest,
                "proposal_digest": PB["digest"]("proposal", event),
                "occurrence_id": event["occurrence"]["occurrence_id"],
                "disposition": "WITHHELD",
                "permit_digest": None,
                "authority_result_digest": refusal_digest,
                "reservation_receipt_digests": [],
                "prior_permit_digest": None,
            }
        )
        next_state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))

    return PB["work_transition"](
        state,
        event,
        disposition="WITHHELD",
        reasons=reason_codes,
        details=[
            {
                "kind": "AUTHORITY",
                "authority_result_digest": refusal_digest,
                "code": authority_refusal["code"],
                "reasons": copy.deepcopy(authority_refusal["reasons"]),
                "failed_checks": copy.deepcopy(authority_refusal["failed_checks"]),
            }
        ],
        permit=None,
        budget_results=[],
        authority_result_digest=refusal_digest,
        reservation_receipt_digests=[],
        mutate=mutate,
    )


def fanout_definition_with_target(definition: dict) -> None:
    FANOUT["fanout_definition"]("ADVANCE_TO_JOIN")(definition)
    target = next(row for row in definition["steps"] if row["id"] == "target-step")
    target["prior_effect_bindings"] = [
        {
            "id": "object-beneficiary",
            "selection": "UNIQUE_COMPLETED_ANCESTOR",
            "source_step_id": "object-step",
            "source_evidence_field": "beneficiary",
            "target_request_field": "beneficiary",
        }
    ]
    definition["relationships"] = [
        {"kind": "SEQUENCE", "from": "object-step", "to": "fanout-join"},
        {"kind": "SEQUENCE", "from": "fanout-join", "to": "target-step"},
        {"kind": "SEQUENCE", "from": "target-step", "to": "terminal"},
    ]
    next(
        row for row in definition["occurrence_limits"] if row["step_id"] == "target-step"
    )["maximum"] = "1"
    definition["occurrence_limits"].sort(key=lambda row: row["step_id"].encode("utf-8"))


def fanout_final_to_target_result(base: dict, dispatched: dict, event: dict) -> dict:
    source = event["permit"]["occurrence"]
    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    object_relationship = next(
        row
        for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == "object-step"
    )
    join_relationship = next(
        row
        for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == "fanout-join"
    )
    relationship_digests = sorted(
        [digest("relationship", object_relationship), digest("relationship", join_relationship)],
        key=lambda value: value.encode("utf-8"),
    )
    prior_object_ids = sorted(
        [
            row["occurrence"]["occurrence_id"]
            for row in dispatched["state"]["completed"]
            if row["occurrence"]["step_id"] == "object-step"
        ]
        + [source["occurrence_id"]],
        key=lambda value: value.encode("utf-8"),
    )
    target_occurrence = occurrence(
        base["definition_digest"],
        source["instance_id"],
        "target-step",
        "1",
        prior_object_ids,
        [],
    )

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [
            row
            for row in state["active"]
            if row["occurrence"]["occurrence_id"] != source["occurrence_id"]
        ]
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(source),
                "disposition": "SUCCEEDED",
                "evidence_digest": evidence_digest,
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": digest("relationship", object_relationship),
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        obligation = next(
            row
            for row in state["obligations"]
            if row["expected_occurrence_id"] == source["occurrence_id"]
        )
        obligation["status"] = "DISCHARGED"
        obligation["expected_occurrence_id"] = None
        obligation["required_operation"] = None
        obligation["completion_basis"] = {
            "kind": "DIRECT_EVENT",
            "event_digest": event_digest,
            "occurrence_id": source["occurrence_id"],
            "operation": event["permit"]["native_request"]["operation"],
            "evidence_digest": evidence_digest,
        }
        pass_row = next(row for row in state["fanout_passes"] if row["fanout_id"] == "fanout-1")
        pass_row["joined"] = True
        obligation_ids = set(pass_row["obligation_ids"])
        for row in state["obligations"]:
            if row["obligation_id"] in obligation_ids:
                row["status"] = "JOINED"
        state["active"].append(
            {
                "occurrence": copy.deepcopy(target_occurrence),
                "activation_event_digest": event_digest,
                "status": "ACTIVE",
                "deadline_ids": [],
            }
        )
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        target_counter = next(
            row for row in state["step_counters"] if row["step_id"] == "target-step"
        )
        target_counter["activations"] = str(int(target_counter["activations"]) + 1)
        state["total_activations"] = str(int(state["total_activations"]) + 1)

    return admitted_transition(
        dispatched["state"],
        event,
        disposition="COMPLETED",
        reason_codes=[],
        details=[
            {
                "kind": "EFFECT",
                "classification": "MATCHED",
                "evidence_id": event["native_evidence"]["evidence_id"],
            },
            {
                "kind": "ROUTE",
                "relationship_digests": relationship_digests,
                "construct_ids": ["fanout-1"],
            },
        ],
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def two_ancestor_case() -> tuple[dict, dict, dict]:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(["object-step", "target-step"]),
        definition_mutator=fanout_definition_with_target,
        instance_id="prior-binding-d2-278",
    )
    root_permitted = permitted_proposal(base)
    root_dispatch = dispatch_event(
        base,
        root_permitted,
        event_id="dispatch-expand-d2-278",
        acknowledgement_status="ACCEPTED",
    )
    root_dispatched = dispatch_result(
        root_permitted,
        root_dispatch,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    keys = [FANOUT["typed"]("IDENTITY", "card-802"), FANOUT["typed"]("IDENTITY", "card-803")]
    root_evidence = governed_native_evidence(
        base,
        root_permitted,
        root_dispatched,
        evidence_id="evidence-expand-d2-278",
        collections=[{"name": "items", "element_type_ref": "IDENTITY", "values": keys}],
    )
    root_effect = governed_effect_event(
        root_permitted,
        root_dispatched,
        root_evidence,
        event_id="effect-expand-d2-278",
    )
    expanded = FANOUT["expansion_result"](base, root_dispatched, root_effect, mode="NONEMPTY")
    object_occurrences = sorted(
        (row["occurrence"] for row in expanded["state"]["active"]),
        key=lambda row: int(row["ordinal"]),
    )
    _p1, _a1, _d1, _da1, _e1, first_completed = FANOUT_COMPLETION["execute_object"](
        base,
        expanded["state"],
        object_occurrences[0],
        suffix="d2-278-object-1",
        final_join=False,
    )
    proposal2, authority2 = proposal_for_occurrence(
        base,
        first_completed["state"],
        object_occurrences[1],
        event_id="proposal-d2-278-object-2",
    )
    permitted2 = permitted_operation_proposal(
        base, first_completed["state"], proposal2, authority2
    )
    dispatch2 = dispatch_event(
        base,
        permitted2,
        event_id="dispatch-d2-278-object-2",
        acknowledgement_status="ACCEPTED",
    )
    dispatched2 = dispatch_result(
        permitted2,
        dispatch2,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    dispatch2_digest = next(
        row["dispatch_digest"]
        for row in dispatched2["state"]["dispatches"]
        if row["event_id"] == dispatch2["event_id"]
    )
    evidence2 = governed_native_evidence(
        base,
        permitted2,
        dispatched2,
        evidence_id="evidence-d2-278-object-2",
        native_operation_id="native-d2-278-object-2",
        dispatch_digest=dispatch2_digest,
    )
    effect2 = governed_effect_event(
        permitted2,
        dispatched2,
        evidence2,
        event_id="effect-d2-278-object-2",
        dispatch_digest=dispatch2_digest,
    )
    joined = fanout_final_to_target_result(base, dispatched2, effect2)
    target_occurrence = next(
        row["occurrence"]
        for row in joined["state"]["active"]
        if row["occurrence"]["step_id"] == "target-step"
    )
    target_event, _target_authority = proposal_for_occurrence(
        base,
        joined["state"],
        target_occurrence,
        event_id="proposal-d2-278",
    )
    return base, joined["state"], target_event


def parallel_definition_with_binding(definition: dict) -> None:
    parallel_definition(["source-branch", "target-branch"])(definition)
    target = next(row for row in definition["steps"] if row["id"] == "target-branch")
    target["prior_effect_bindings"] = [
        {
            "id": "sibling-beneficiary",
            "selection": "UNIQUE_COMPLETED_ANCESTOR",
            "source_step_id": "source-branch",
            "source_evidence_field": "beneficiary",
            "target_request_field": "beneficiary",
        }
    ]


def sibling_completion_result(base: dict, dispatched: dict, event: dict) -> dict:
    source = event["permit"]["occurrence"]
    event_digest = digest("runtime-event", event)
    evidence_digest = digest("native-evidence", event["native_evidence"])
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    relationship = next(
        row
        for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == source["step_id"]
    )
    relationship_digest = digest("relationship", relationship)

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [
            row
            for row in state["active"]
            if row["occurrence"]["occurrence_id"] != source["occurrence_id"]
        ]
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(source),
                "disposition": "SUCCEEDED",
                "evidence_digest": evidence_digest,
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": relationship_digest,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        obligation = next(
            row
            for row in state["obligations"]
            if row["expected_occurrence_id"] == source["occurrence_id"]
        )
        obligation["status"] = "DISCHARGED"
        obligation["expected_occurrence_id"] = None
        obligation["required_operation"] = None
        obligation["completion_basis"] = {
            "kind": "DIRECT_EVENT",
            "event_digest": event_digest,
            "occurrence_id": source["occurrence_id"],
            "operation": event["permit"]["native_request"]["operation"],
            "evidence_digest": evidence_digest,
        }

    return admitted_transition(
        dispatched["state"],
        event,
        disposition="COMPLETED",
        reason_codes=[],
        details=[
            {
                "kind": "EFFECT",
                "classification": "MATCHED",
                "evidence_id": event["native_evidence"]["evidence_id"],
            },
            {
                "kind": "ROUTE",
                "relationship_digests": [relationship_digest],
                "construct_ids": ["parallel-1"],
            },
        ],
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def sibling_non_predecessor_case() -> tuple[dict, dict, dict]:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(["source-branch", "target-branch"]),
        definition_mutator=parallel_definition_with_binding,
        instance_id="prior-binding-d2-281",
    )
    root_permitted = permitted_proposal(base)
    root_dispatch = dispatch_event(
        base,
        root_permitted,
        event_id="dispatch-parallel-d2-281",
        acknowledgement_status="ACCEPTED",
    )
    root_dispatched = dispatch_result(
        root_permitted,
        root_dispatch,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    root_evidence = governed_native_evidence(
        base,
        root_permitted,
        root_dispatched,
        evidence_id="evidence-parallel-d2-281",
    )
    root_effect = governed_effect_event(
        root_permitted,
        root_dispatched,
        root_evidence,
        event_id="effect-parallel-d2-281",
    )
    entered = parallel_entry_result(
        base, root_dispatched, root_effect, ["source-branch", "target-branch"]
    )
    source_occurrence = next(
        row["occurrence"]
        for row in entered["state"]["active"]
        if row["occurrence"]["step_id"] == "source-branch"
    )
    source_event, source_authority = proposal_for_occurrence(
        base,
        entered["state"],
        source_occurrence,
        event_id="proposal-source-d2-281",
    )
    source_permitted = permitted_operation_proposal(
        base, entered["state"], source_event, source_authority
    )
    source_dispatch = dispatch_event(
        base,
        source_permitted,
        event_id="dispatch-source-d2-281",
        acknowledgement_status="ACCEPTED",
    )
    source_dispatched = dispatch_result(
        source_permitted,
        source_dispatch,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    source_dispatch_digest = next(
        row["dispatch_digest"]
        for row in source_dispatched["state"]["dispatches"]
        if row["event_id"] == source_dispatch["event_id"]
    )
    source_evidence = governed_native_evidence(
        base,
        source_permitted,
        source_dispatched,
        evidence_id="evidence-source-d2-281",
        dispatch_digest=source_dispatch_digest,
    )
    source_effect = governed_effect_event(
        source_permitted,
        source_dispatched,
        source_evidence,
        event_id="effect-source-d2-281",
        dispatch_digest=source_dispatch_digest,
    )
    source_completed = sibling_completion_result(base, source_dispatched, source_effect)
    target_occurrence = next(
        row["occurrence"]
        for row in source_completed["state"]["active"]
        if row["occurrence"]["step_id"] == "target-branch"
    )
    target_event, _target_authority = proposal_for_occurrence(
        base,
        source_completed["state"],
        target_occurrence,
        event_id="proposal-d2-281",
    )
    return base, source_completed["state"], target_event


def duplicate_current_act_state(context: dict, permitted_result: dict) -> dict:
    state = copy.deepcopy(permitted_result["state"])
    old_id = permitted_result["permit"]["permit_id"]
    retained = next(row for row in state["permits"] if row["permit_id"] == old_id)
    duplicate = copy.deepcopy(
        next(
            row
            for row in retained["authority_act_bases"]
            if row["act"]["kind"] == "INSTANCE_DECISION"
        )
    )
    duplicate["act"]["id"] = "pay-invoice-instance-decision-act-injected"
    duplicate["act_digest"] = digest("authority-act", duplicate["act"])
    retained["authority_act_bases"].append(duplicate)
    retained["authority_act_bases"].sort(key=lambda row: row["act_digest"].encode("utf-8"))
    new_id = digest("permit", {key: value for key, value in retained.items() if key != "permit_id"})
    retained["permit_id"] = new_id
    state["permits"].sort(key=lambda row: row["permit_id"].encode("utf-8"))
    proposal = next(row for row in state["proposals"] if row["permit_digest"] == old_id)
    proposal["permit_digest"] = new_id
    receipt = next(
        row for row in state["receipts"] if row["event_id"] == context["payment_event"]["event_id"]
    )
    replay = next(
        row for row in state["replays"] if row["event_id"] == context["payment_event"]["event_id"]
    )
    replay["permit"] = copy.deepcopy(retained)
    receipt["permit_digest"] = new_id
    core = copy.deepcopy(state)
    core["receipts"] = []
    core["replays"] = []
    receipt["state_after_core_digest"] = digest("work-state-core", core)
    receipt_without_id = {key: value for key, value in receipt.items() if key != "decision_id"}
    receipt["decision_id"] = digest("decision-receipt", receipt_without_id)
    replay["decision"] = copy.deepcopy(receipt)
    replay["decision_receipt_digest"] = receipt["decision_id"]
    replay["transition_state_digest"] = receipt["state_after_core_digest"]
    replay["transaction_digest"] = digest(
        "lifecycle-transaction",
        {
            "state_before_digest": receipt["state_before_digest"],
            "event_digest": receipt["event_digest"],
            "decision_receipt_digest": receipt["decision_id"],
            "state_after_core_digest": receipt["state_after_core_digest"],
            "budget_results": replay["budget_results"],
        },
    )
    return state


def supplier_budget_precedence_case() -> tuple[dict, dict, dict, dict, dict]:
    path = (
        REVIEW.parent
        / "specimens"
        / "supplier-payment"
        / "scenarios"
        / "requests.json"
    )
    requests = json.loads(path.read_text(encoding="utf-8"))
    request = copy.deepcopy(
        next(
            row
            for row in requests
            if row["request_id"] == "supplier-payment-same-confirmation-and-release-actor"
        )["input"]
    )
    event = request["event"]
    event["event_id"] = "proposal-d2-287"
    budget_input = event["budget_inputs"][0]
    budget_input["expected_revision"] = "0"
    budget_input["request"]["event"]["expected_revision"] = "0"
    reservation_event = budget_input["request"]["event"]
    reservation_event["id"] = SUPPLIER["digest"](
        "lifecycle-reservation-event",
        {
            "instance_id": event["instance_id"],
            "lifecycle_event_id": event["event_id"],
            "lifecycle_event_kind": "PROPOSE",
            "reservation_event_kind": "RESERVE",
            "registry_digest": budget_input["registry_digest"],
        },
    )
    authority_input = event["authority_input"]
    authority_input["specification_pin"] = PIN
    authority = SUPPLIER["build_authority"](
        authority_input["source"],
        authority_input["work_class"],
        instance_id=event["instance_id"],
        occurrence_row=event["occurrence"],
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
        proposal_fields=event["native_request"]["fields"],
        required_budgets=["supplier-payment-cap"],
    )
    if authority["input"] != authority_input:
        raise AssertionError("supplier authority reconstruction changed")
    definition = request["definition"]
    requirement = next(
        row
        for row in next(
            step for step in definition["steps"] if step["id"] == "pay-invoice"
        )["prior_actor_separations"]
        if row["id"] == "confirmer-differs-from-payment-releaser"
    )
    completed = next(
        row
        for row in request["state"]["completed"]
        if row["occurrence"]["step_id"] == requirement["prior_step_id"]
    )
    source_permit = next(
        row
        for row in request["state"]["permits"]
        if row["occurrence"]["occurrence_id"] == completed["occurrence"]["occurrence_id"]
    )
    prior_basis = next(
        copy.deepcopy(row)
        for row in source_permit["authority_act_bases"]
        if row["act"]["kind"] == requirement["prior_act_kind"]
    )
    current_act = next(
        row for row in authority["acts"] if row["kind"] == requirement["current_act_kind"]
    )
    basis = {
        "requirement_id": requirement["id"],
        "relation": requirement["relation"],
        "prior_occurrence_id": completed["occurrence"]["occurrence_id"],
        "current_occurrence_id": event["occurrence"]["occurrence_id"],
        "prior_act": prior_basis,
        "current_act": {
            "act_digest": digest("authority-act", current_act),
            "act": copy.deepcopy(current_act),
        },
    }
    _after, expected = PB["withheld_separation_result"](
        request["state"], event, authority, basis
    )
    return definition, request["definition_digest"], request["state"], event, expected


def main() -> None:
    standard_separation = [
        {
            "id": "confirmer-differs-from-payment-releaser",
            "relation": "DISTINCT_ACTOR",
            "selection": "UNIQUE_COMPLETED_ANCESTOR",
            "prior_step_id": "change-supplier-destination",
            "prior_act_kind": "VERIFY",
            "current_act_kind": "INSTANCE_DECISION",
        }
    ]

    context = supplier_context(
        "D2-277", prior_mode="future", separation_rows=[]
    )
    emit(
        "D2-277",
        context["definition"],
        context["definition_digest"],
        context["state"],
        context["payment_event"],
        refusal(context["state"], "PREREQUISITE_MISSING"),
        ["LIFE-006", "LIFE-007", "COMP-BIND-001"],
        "The payment step's only prior-effect binding names future-destination-source, a valid proposal-capable downstream step with no completed occurrence in the current payment occurrence's recursive predecessor closure. Prior-effect selection therefore returns PREREQUISITE_MISSING before current authority or budget evaluation and changes no state.",
    )

    fanout_base, fanout_state, fanout_event = two_ancestor_case()
    emit(
        "D2-278",
        fanout_base["definition"],
        fanout_base["definition_digest"],
        fanout_state,
        fanout_event,
        refusal(fanout_state, "BINDING_MISMATCH"),
        ["LIFE-006", "LIFE-007", "COMP-BIND-001"],
        "The completed two-object fan-out supplies two governed, matched, undisputed object-step occurrences in target-step's recursive predecessor closure. Both satisfy the one UNIQUE_COMPLETED_ANCESTOR binding. The consumer returns BINDING_MISMATCH without choosing by ordinal, object order, time or graph distance.",
    )

    context = supplier_context(
        "D2-279",
        prior_mode="all",
        separation_rows=[],
        payment_destination="acct-old",
    )
    emit(
        "D2-279",
        context["definition"],
        context["definition_digest"],
        context["state"],
        context["payment_event"],
        refusal(context["state"], "BINDING_MISMATCH"),
        ["LIFE-006", "LIFE-007", "COMP-BIND-001"],
        "The unique completed master-change occurrence established destination_account acct-new. The current native request and its otherwise exact authority subject name acct-old. The first prior-effect binding fails exact canonical value equality, so authority and reservation are not evaluated and both states remain unchanged.",
    )

    context = supplier_context("D2-280", prior_mode="all", separation_rows=[])
    prior_bases = PB["prior_effect_bases"](
        context["change_occurrence"], context["change_permit"], context["change_evidence"]
    )
    payment_permit = PB["permit"](
        context["definition_digest"],
        context["payment_event"],
        context["payment_authority"],
        prior_effect_bases=prior_bases,
    )
    _after, expected = PB["permitted_result"](
        context["state"],
        context["payment_event"],
        payment_permit,
        context["payment_authority"],
    )
    emit(
        "D2-280",
        context["definition"],
        context["definition_digest"],
        context["state"],
        context["payment_event"],
        expected,
        ["LIFE-007", "LIFE-008", "COMP-BIND-001"],
        "The unique completed master-change occurrence has one exact governed MATCHED outcome. Its destination_account and supplier_id evidence fields have the same nominal types and canonical values as the current request. The permit retains both prior-effect bases and no budget transition is required.",
    )

    sibling_base, sibling_state, sibling_event = sibling_non_predecessor_case()
    emit(
        "D2-281",
        sibling_base["definition"],
        sibling_base["definition_digest"],
        sibling_state,
        sibling_event,
        refusal(sibling_state, "PREREQUISITE_MISSING"),
        ["LIFE-004", "LIFE-007", "COMP-BIND-001"],
        "The source-branch has a governed, matched, undisputed completion with the same beneficiary value, but it is a sibling of target-branch. It is outside the target occurrence's recursive predecessor closure and is therefore ineligible. Zero eligible occurrences returns PREREQUISITE_MISSING without changing work state.",
    )

    context = supplier_context(
        "D2-282", prior_mode="none", separation_rows=standard_separation
    )
    basis = separation_basis(context, standard_separation[0]["id"])
    payment_permit = PB["permit"](
        context["definition_digest"],
        context["payment_event"],
        context["payment_authority"],
        separation_bases=[basis],
    )
    _after, expected = PB["permitted_result"](
        context["state"],
        context["payment_event"],
        payment_permit,
        context["payment_authority"],
    )
    emit(
        "D2-282",
        context["definition"],
        context["definition_digest"],
        context["state"],
        context["payment_event"],
        expected,
        ["LIFE-007", "LIFE-008", "COMP-BIND-001"],
        "The unique completed master-change permit selects destination-confirmer-person through VERIFY. Current authority selects payment-releaser-person through INSTANCE_DECISION. Their exact identifiers differ, so the permit retains the complete authority-act projection and one satisfied separation basis.",
    )

    context = supplier_context(
        "D2-283",
        prior_mode="none",
        separation_rows=standard_separation,
        payment_actor="destination-confirmer-person",
    )
    basis = separation_basis(context, standard_separation[0]["id"])
    _after, expected = PB["withheld_separation_result"](
        context["state"],
        context["payment_event"],
        context["payment_authority"],
        basis,
    )
    emit(
        "D2-283",
        context["definition"],
        context["definition_digest"],
        context["state"],
        context["payment_event"],
        expected,
        ["LIFE-006", "LIFE-007", "COMP-BIND-001"],
        "The prior VERIFY and current INSTANCE_DECISION use destination-confirmer-person under different roles, occupancies and capacities. DISTINCT_ACTOR compares the exact actor identifiers, records the complete first failing basis and withholds without creating a permit or reservation.",
    )

    missing_prior_act = [copy.deepcopy(standard_separation[0])]
    missing_prior_act[0]["prior_act_kind"] = "INSTANCE_DECISION"
    context = supplier_context(
        "D2-284", prior_mode="none", separation_rows=missing_prior_act
    )
    emit(
        "D2-284",
        context["definition"],
        context["definition_digest"],
        context["state"],
        context["payment_event"],
        refusal(context["state"], "PREREQUISITE_MISSING"),
        ["LIFE-006", "LIFE-007", "COMP-BIND-001"],
        "The unique completed master-change occurrence and establishing permit are otherwise eligible, but that permit selected VERIFY and contains no INSTANCE_DECISION authority-act basis. Actor-separation selection returns PREREQUISITE_MISSING without changing work state.",
    )

    context = supplier_context(
        "D2-285", prior_mode="none", separation_rows=standard_separation
    )
    basis = separation_basis(context, standard_separation[0]["id"])
    payment_permit = PB["permit"](
        context["definition_digest"],
        context["payment_event"],
        context["payment_authority"],
        separation_bases=[basis],
    )
    _state5, permitted = PB["permitted_result"](
        context["state"],
        context["payment_event"],
        payment_permit,
        context["payment_authority"],
    )
    damaged = duplicate_current_act_state(context, permitted)
    probe = PB["clock_event"](
        damaged,
        "clock-d2-285-restart-probe",
        source="restart-probe",
        revision="2",
        observed_time="2026-09-11T12:01:00Z",
    )
    emit(
        "D2-285",
        context["definition"],
        context["definition_digest"],
        damaged,
        probe,
        refusal(damaged, "STATE_INVALID"),
        ["AUTH-004", "LIFE-008", "LIFE-019"],
        "The supplied restart checkpoint has a matching outer state digest and internally recomputed permit, receipt, replay and transaction envelopes. Its current payment permit injects a second distinct INSTANCE_DECISION authority-act basis that is absent from the retained successful authority result. LIFE-019 rejects the impossible selected-act projection as STATE_INVALID before evaluating the clock event.",
        group=RESTART_GROUP,
    )

    context = supplier_context(
        "D2-286",
        prior_mode="none",
        separation_rows=standard_separation,
        payment_actor="destination-confirmer-person",
        expired_authority=True,
    )
    payment_refusal = authority_refusal([envelope_validity_check(context["payment_authority"]["input"])])
    _after, expected = authority_withheld_result(
        context["state"], context["payment_event"], payment_refusal
    )
    emit(
        "D2-286",
        context["definition"],
        context["definition_digest"],
        context["state"],
        context["payment_event"],
        expected,
        ["LIFE-006", "LIFE-007"],
        "The current payment envelope expired before the selected current clock, so authority returns AUTHORITY_NOT_ESTABLISHED with ENVELOPE_EXPIRED. The unexecuted separation would compare equal actor identifiers. Authority withholding has precedence, records only AUTHORITY detail and creates no separation basis, permit or reservation.",
    )

    definition, definition_digest, state, event, expected = supplier_budget_precedence_case()
    emit(
        "D2-287",
        definition,
        definition_digest,
        state,
        event,
        expected,
        ["LIFE-006", "LIFE-007", "RES-WIRE-004"],
        "Current authority succeeds, then the prior VERIFY and current INSTANCE_DECISION compare equal destination-confirmer-person identifiers. The supplied required registry event also selects revision zero against state revision one, but separation precedes budget admission. The work state records only SEPARATION_VIOLATED, and the supplied registry remains unchanged.",
    )

    two_separations = [
        {
            "id": "a-equal-actors",
            "relation": "DISTINCT_ACTOR",
            "selection": "UNIQUE_COMPLETED_ANCESTOR",
            "prior_step_id": "change-supplier-destination",
            "prior_act_kind": "VERIFY",
            "current_act_kind": "INSTANCE_DECISION",
        },
        {
            "id": "z-missing-prior-act",
            "relation": "DISTINCT_ACTOR",
            "selection": "UNIQUE_COMPLETED_ANCESTOR",
            "prior_step_id": "change-supplier-destination",
            "prior_act_kind": "INSTANCE_DECISION",
            "current_act_kind": "INSTANCE_DECISION",
        },
    ]
    context = supplier_context(
        "D2-293",
        prior_mode="none",
        separation_rows=two_separations,
        payment_actor="destination-confirmer-person",
    )
    basis = separation_basis(context, "a-equal-actors")
    _after, expected = PB["withheld_separation_result"](
        context["state"],
        context["payment_event"],
        context["payment_authority"],
        basis,
    )
    emit(
        "D2-293",
        context["definition"],
        context["definition_digest"],
        context["state"],
        context["payment_event"],
        expected,
        ["LIFE-006", "LIFE-007", "COMP-BIND-001"],
        "The two separation requirements are sorted by identifier. a-equal-actors resolves first and compares equal destination-confirmer-person identifiers. The consumer records only that complete failing basis and does not evaluate z-missing-prior-act, whose prior INSTANCE_DECISION basis is absent.",
    )

    case_ids = [f"D2-{value}" for value in range(277, 288)] + ["D2-293"]
    print(
        json.dumps(
            {
                "candidate_pin": PIN,
                "case_ids": case_ids,
                "d2_285_judgment": "REFUSED/STATE_INVALID",
                "global_indexes_updated": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
