#!/usr/bin/env python3
"""Build the vectors where later evidence disputes the source effect a descendant permit rests on.

LIFE-008 makes a permit's prior-effect basis a retained binding rather than a live recomputation,
so LIFE-013's dependency blocking does not rewrite earlier permission. This reuses the
supplier-payment prior-binding fixture, which is the only one in the corpus whose permits carry
prior_effect_bases.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from corpus_common import CASES, exact_case, write_canonical_json
from dependency_dispute_common import apply_dependency_block


def _prior_binding_module():
    path = Path(__file__).resolve().parent / "build-prior-binding-restart-cases.py"
    spec = importlib.util.spec_from_file_location("prior_binding_restart", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PBR = _prior_binding_module()
GROUP = CASES / "disputed-permit-basis"


def permitted_descendant_state():
    """Replay the prior-binding sequence to the point the case needs.

    The source occurrence has completed with a retained effect, and the descendant is PERMITTED
    with a prior-effect basis citing that effect.
    """
    source, definition, authority_source, authority_work_class = PBR.build_static_contract()
    payment_step = next(row for row in definition["steps"] if row["id"] == "pay-invoice")
    payment_step["shared_budgets"] = []
    payment_step["fields"].append({"name": "request_count", "type_ref": "t.count"})
    payment_step["fields"].sort(key=lambda row: row["name"].encode("utf-8"))
    payment_step["completion"]["evidence_bindings"] = [
        {"request_field": row["name"], "evidence_field": row["name"]} for row in payment_step["fields"]
    ]
    payment_step["completion"]["evidence_bindings"].sort(key=lambda row: row["request_field"].encode("utf-8"))
    definition["shared_budgets"] = []
    authority_payment_step = next(row for row in authority_work_class["steps"] if row["id"] == "pay-invoice")
    authority_payment_step["fields"] = copy.deepcopy(payment_step["fields"])
    definition_digest = PBR.digest("work-class-definition", definition)
    _deploy_input, _deploy_result, state0, change_occurrence = PBR.build_deployment(
        definition, "prior-binding-d2-290"
    )

    clock = PBR.clock_event(state0, "clock-d2-290", source="governance-clock", revision="1", observed_time=PBR.NOW)
    state1, _ = PBR.accepted_clock(state0, clock)
    change_fields = [
        PBR.field("destination_account", "t.identity", "acct-new"),
        PBR.field("request_count", "t.count", "1"),
        PBR.field("supplier_id", "t.identity", "supplier-17"),
    ]
    change_authority = PBR.build_authority(
        authority_source, authority_work_class, instance_id=state1["instance_id"],
        occurrence_row=change_occurrence, step_id="change-supplier-destination",
        envelope_id="supplier-change-authority", executor_id="supplier-master-agent-1",
        executor_role="supplier-master-agent", credential_kind="supplier-master-credential",
        gate_kind="VERIFY", gate_actor="destination-confirmer-person", gate_role="destination-confirmer",
        subject_fields=["supplier_id"], resource_fields=["destination_account"],
        proposal_fields=change_fields, required_budgets=[],
    )
    change_proposal = PBR.proposal_event(
        state1, change_occurrence, change_authority, change_fields, event_id="proposal-change-d2-290"
    )
    change_permit = PBR.permit(definition_digest, change_proposal, change_authority)
    state2, _ = PBR.permitted_result(state1, change_proposal, change_permit, change_authority)
    state3, _, change_dispatch = PBR.dispatch_result(state2, "dispatch-change-d2-290", change_permit)
    state4, _, payment_occurrence, change_evidence = PBR.change_effect_result(
        definition, definition_digest, state3, change_occurrence, change_permit, change_dispatch, change_fields
    )

    payment_fields = [
        PBR.field("amount", "t.money", "150"),
        PBR.field("destination_account", "t.identity", "acct-new"),
        PBR.field("invoice_id", "t.identity", "invoice-44"),
        PBR.field("request_count", "t.count", "1"),
        PBR.field("supplier_id", "t.identity", "supplier-17"),
    ]
    payment_authority = PBR.build_authority(
        authority_source, authority_work_class, instance_id=state4["instance_id"],
        occurrence_row=payment_occurrence, step_id="pay-invoice",
        envelope_id="invoice-payment-authority", executor_id="payment-agent-1",
        executor_role="payment-agent", credential_kind="payment-credential",
        gate_kind="DECIDE", gate_actor="payment-releaser-person", gate_role="payment-releaser",
        subject_fields=["supplier_id"], resource_fields=["destination_account", "invoice_id"],
        proposal_fields=payment_fields, required_budgets=[],
    )
    payment_proposal = PBR.proposal_event(
        state4, payment_occurrence, payment_authority, payment_fields, event_id="proposal-payment-d2-290"
    )
    payment_permit = PBR.permit(
        definition_digest, payment_proposal, payment_authority,
        prior_effect_bases=PBR.prior_effect_bases(change_occurrence, change_permit, change_evidence),
        separation_bases=[
            PBR.separation_basis(change_occurrence, payment_occurrence, change_authority, payment_authority)
        ],
    )
    state5, _ = PBR.permitted_result(state4, payment_proposal, payment_permit, payment_authority)
    return definition, definition_digest, state5, change_occurrence, change_permit, change_evidence


def source_dispute_case(case_id: str, *, native_operation_id: str | None, derivation: str) -> None:
    """One later conclusive record against the completed source effect the descendant permit cites.

    `native_operation_id` None keeps the source effect's identity, which LIFE-010 classifies
    CONFLICTING; a different identity is UNEXPECTED additional execution under the same paragraph.
    """
    definition, definition_digest, state, change_occurrence, change_permit, change_evidence = (
        permitted_descendant_state()
    )
    slug = case_id.lower()
    evidence = copy.deepcopy(change_evidence)
    evidence["evidence_id"] = "evidence-" + slug
    evidence["evidence_ref"] = "evidence-ref-" + slug
    evidence["record_digest"] = PBR.digest("provider-native-record", {"record": case_id})
    if native_operation_id is not None:
        evidence["native_operation_id"] = native_operation_id
    conflicting = native_operation_id is None
    dispatch = next(row for row in state["dispatches"] if row["permit_digest"] == change_permit["permit_id"])
    event = {
        "schema": PBR.SCHEMA + "runtime-event", "event_id": "effect-" + slug, "kind": "EFFECT_OBSERVED",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": PBR.work_state_digest(state),
        "permit": copy.deepcopy(change_permit), "dispatch_digest": dispatch["dispatch_digest"],
        "native_evidence": evidence, "completion_authorization": None,
        "budget_inputs": [], "clock_revision": None, "activation_clocks": [],
    }
    event_digest = PBR.digest("runtime-event", event)
    without_digest = {
        "kind": "GOVERNED", "event_id": event["event_id"], "event_digest": event_digest,
        "permit_digest": change_permit["permit_id"], "dispatch_digest": dispatch["dispatch_digest"],
        "dispatch_attempt_digest": dispatch["dispatch_attempt_digest"],
        "native_evidence": copy.deepcopy(evidence),
        "classification": "CONFLICTING" if conflicting else "UNEXPECTED",
        "reservation_receipt_digests": [],
        # LIFE-010: UNEXPECTED has an empty conflict list until another conclusive record
        # conflicts with it, and the symmetric update belongs to CONFLICTING alone.
        "conflicts_with_evidence_ids": [change_evidence["evidence_id"]] if conflicting else [],
        "disputed": True,
    }
    outcome = {"outcome_digest": PBR.digest("outcome", without_digest), **without_digest}

    def mutate(next_state: dict, _event_digest: str) -> None:
        if conflicting:
            for prior in next_state["outcomes"]:
                if prior["native_evidence"]["evidence_id"] != change_evidence["evidence_id"]:
                    continue
                prior["disputed"] = True
                prior["conflicts_with_evidence_ids"] = [evidence["evidence_id"]]
                prior["outcome_digest"] = PBR.digest(
                    "outcome", {key: value for key, value in prior.items() if key != "outcome_digest"}
                )
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        apply_dependency_block(next_state, change_occurrence["occurrence_id"])

    classification = "CONFLICTING" if conflicting else "UNEXPECTED"
    reason = "CONFLICTING_EFFECT" if conflicting else "UNEXPECTED_EFFECT"
    _after, expected = PBR.work_transition(
        state, event, disposition="DISPUTED", reasons=[reason],
        details=[{"kind": "EFFECT", "classification": classification, "evidence_id": evidence["evidence_id"]}],
        permit=None, budget_results=[], authority_result_digest=None, reservation_receipt_digests=[],
        mutate=mutate,
    )
    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(
            case_id, "step",
            PBR.lifecycle_input(definition, definition_digest, state, event),
            expected,
            [] if case_id.startswith("D2-") else ["LIFE-006", "LIFE-010", "LIFE-013"],
            derivation,
        ),
    )


def build() -> None:
    source_dispute_case(
        "D2-290", native_operation_id=None,
        derivation="The descendant permit rests on a prior-effect basis citing the source occurrence's effect, and the descendant is permitted but not yet dispatched. A second conclusive record for that source effect's provider-native operation identity differs in content, so LIFE-010 classifies it CONFLICTING and LIFE-006 fixes the reason set to CONFLICTING_EFFECT. The source occurrence is completed, so LIFE-013's dependency rule runs: the affected set is that occurrence and every transitive descendant, which includes the permitted descendant through its predecessor list, so the descendant's active occurrence becomes BLOCKED_DISPUTE. LIFE-008 makes the prior-effect basis a retained binding rather than a live recomputation, so the descendant's permit and its recorded bases stay exactly as issued: LIFE-013 does not rewrite earlier permission or completed routing, and the completed source row and its selected route are unchanged. LIFE-019 keeps the event log and checkpoint bindings intact across the transition. This candidate has no dispute-resolution transition, so nothing here clears the block.",
    )
    source_dispute_case(
        "C2-dependent-block-unexpected-completed", native_operation_id="supplier-master-native-2",
        derivation="This is D2-290's fixture with one change: the later record carries a different provider-native operation identity. LIFE-010 therefore classifies it UNEXPECTED additional execution rather than CONFLICTING, gives it disputed true with an empty conflict list until another conclusive record conflicts with it, and applies no symmetric update to the earlier outcome. The point of the case is what does not change. LIFE-006's consequence table lists 'dependent descendants are blocked' as its own clause of the DISPUTED governed effect row, parallel to and independent of the clause deciding this occurrence's own status, and LIFE-010 states for the completed case that 'when any of these disputes concerns an already completed occurrence, the completed row and its route stay unchanged; the occurrence is not recreated, but dependent active descendants and obligations become blocked'. The antecedent of 'any of these disputes' is the whole preceding enumeration, inherently disputed and budget-disputed alike. So LIFE-013's dependency-affected set is computed here exactly as for CONFLICTING, and the permitted descendant becomes BLOCKED_DISPUTE through its predecessor list. LIFE-006 fixes the reason set to UNEXPECTED_EFFECT alone, since no budget is involved and no stop condition applies. LIFE-008 keeps the descendant's retained prior-effect basis and permit as issued.",
    )


def main() -> None:
    build()
    print(json.dumps({"case_ids": ["D2-290", "C2-dependent-block-unexpected-completed"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
