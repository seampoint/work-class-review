#!/usr/bin/env python3
"""Construct finite-snapshot vectors from normative rules after retained diagnostics."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import runpy

from authority_fixture import authority_refusal, canonical_sort
from assessment_fixture import authority as assessment_authority, rebind_outer
from corpus_common import CASES, ROOT, digest, exact_case, write_canonical_json
from equipment_completion_fixture import completion_native, lookup_event, lookup_result, terminal_effect_result
from fixture_factory import deploy_refusal, typed
from lifecycle_factory import (base_lifecycle, dispatch_event, dispatch_result, governed_effect_event,
    permitted_proposal, state_digest, stateful_refusal, step_input)


HERE = Path(__file__).resolve().parent
GROUP = CASES / "snapshot-eligibility"
SOURCE_PATH = HERE / "fixtures/source-approved-finite-snapshot-revision1-source.md"
PREDECESSOR_PIN = "sha256:120242f6e3a9cc67348932386460144ace5924d9b02852b878093b74a7af82a3"
DEPLOYMENT = runpy.run_path(str(HERE / "build-deployment-cases.py"))
AUTHORIZATION = runpy.run_path(str(HERE / "build-dispatch-authorization-cases.py"))


def snapshot_authority(supplied, original):
    supplied["work_class"].update(id="finite-card-issuance-snapshot", revision="revision-1")
    supplied["proposal"]["work_class"] = supplied["work_class"]["id"]
    supplied["source"].update(id="finite-card-snapshot-policy", revision="revision-1",
        obligations=[{"id": "issue-card", "text": SOURCE_PATH.read_text()}])
    supplied["work_class"]["types"].extend([
        {"id": "INSTANT", "kind": "INSTANT", "nonnegative": False, "unit": None},
        {"id": "STRING", "kind": "STRING", "nonnegative": False, "unit": None},
    ])
    supplied["work_class"]["types"].sort(key=lambda row: row["id"].encode())
    step = supplied["work_class"]["steps"][0]
    step["authority_type_refs"] = ["INSTANT", "STRING"]
    step["completion"] = {
        "terminal_policy": "STOP_RETAIN", "effect_provider": "card-provider", "effect_source": "card-system",
        "effect_record_type": "card-result", "no_effect_provider": "card-provider", "no_effect_source": "card-system",
        "no_effect_record_type": "card-no-effect", "status_field": "status", "status_type_ref": "STRING",
        "success_values": [typed("STRING", "ISSUED")], "failure_values": [typed("STRING", "REJECTED")],
        "route_label_field": None, "route_label_type_ref": None,
        "evidence_bindings": [{"request_field": name, "evidence_field": name} for name in ("amount", "beneficiary", "card_id")],
        "provider_record_identity": {"field": "provider_event_id", "type_ref": "IDENTITY"},
        "event_time_identity": {"field": "event_timestamp", "type_ref": "INSTANT"}, "additional_fields": [],
        "lookup": {"provider": "card-provider", "source": "card-system", "record_type": "card-result",
            "namespace": "finite-card-snapshot-completion", "key_projection": [{"field": "card_id", "type_ref": "IDENTITY"}]},
    }


def retained(result, permit):
    return {**copy.deepcopy(result), "permit": copy.deepcopy(permit)}


def snapshot_definition(definition):
    next(row for row in definition["steps"] if row["kind"] == "OPERATION")["referral_policy"] = {
        "authority": [], "completion": [],
    }


def bind_event(event, state):
    event = copy.deepcopy(event)
    event.update(expected_state_revision=state["revision"], expected_state_digest=state_digest(state))
    return event


def rechain_deployment(state):
    authorization = state["deployment_authorization"]
    for name in ("correspondence", "source_confirmation", "policy_decision"):
        evidence_digest = digest("evidence", state[f"deployment_{name}_evidence"])
        state[f"deployment_{name}_evidence_digest"] = evidence_digest
        authorization[name + "_evidence_digest"] = evidence_digest
    subject = {key: value for key, value in authorization.items() if key != "authorization_evidence_digest"}
    subject_digest = digest("deployment-authorization-subject", subject)
    state["deployment_authorization_subject_digest"] = subject_digest
    state["deployment_authorization_evidence"]["subject_digest"] = subject_digest
    evidence_digest = digest("evidence", state["deployment_authorization_evidence"])
    state["deployment_authorization_evidence_digest"] = evidence_digest
    authorization["authorization_evidence_digest"] = evidence_digest
    authorization_digest = digest("deployment-authorization", authorization)
    state["deployment_authorization_digest"] = authorization_digest
    state["active"][0]["activation_event_digest"] = digest("deployment-activation", {
        "deployment_authorization_digest": authorization_digest, "instance_id": state["instance_id"],
        "occurrence_id": state["active"][0]["occurrence"]["occurrence_id"],
    })


def build():
    base = base_lifecycle(authority_mutator=snapshot_authority, definition_mutator=snapshot_definition,
        instance_id="new-snapshot-instance")
    for check in base["authority_result"]["checks"]:
        if check["purpose"] == "SOURCE_BINDING":
            check["requirement_ref"] = base["authority_input"]["source"]["id"]
    base["authority_result"]["checks"] = canonical_sort(base["authority_result"]["checks"])
    permitted = permitted_proposal(base)
    rows = []

    def emit(operation, supplied, expected, refs, text):
        case_id = "C3-SNAPSHOT-" + str(len(rows) + 1).zfill(3)
        rows.append(exact_case(case_id, operation, supplied, expected, refs,
            text + " The source and acceptance records are fictional apparatus inputs; expectations derive from the contract before executing this fixture revision. Earlier diagnostic results and corrections are retained separately."))

    emit("deploy", base["deploy_input"], base["deploy_result"], ["LIFE-003", "LIFE-008", "LIFE-009A"],
        "A newly authored definition explicitly omits dispatch_gate and its source approves finite proposal authority. All four accepted deployment evidence records bind that exact definition and source.")
    for member in ("correspondence_evidence", "source_confirmation_evidence", "policy_decision_evidence", "authorization_evidence"):
        supplied = copy.deepcopy(base["deploy_input"])
        del supplied[member]
        emit("deploy", supplied, {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""}, ["LIFE-003"],
            "Omitting " + member + " violates the complete deployment input, independently of the source-approved snapshot choice.")
        supplied = copy.deepcopy(base["deploy_input"])
        supplied[member]["status"] = "PENDING"
        if member == "correspondence_evidence":
            DEPLOYMENT["rebind_correspondence_review"](supplied[member])
        DEPLOYMENT["rebind_review_evidence"](supplied)
        emit("deploy", supplied, deploy_refusal("LINEAR", "LINEAR_WORK_RUNTIME", "EVIDENCE_UNAVAILABLE"), ["LIFE-003"],
            "The " + member + " is pending with every dependent digest rebound. Ungated eligibility does not manufacture its acceptance.")

    for mismatch in ("source-subject", "shared-record-identifier"):
        supplied = copy.deepcopy(base["deploy_input"])
        if mismatch == "source-subject":
            supplied["source_confirmation_evidence"]["subject_digest"] = "sha256:" + "1" * 64
        else:
            supplied["policy_decision_evidence"]["evidence_id"] = supplied["source_confirmation_evidence"]["evidence_id"]
        DEPLOYMENT["rebind_review_evidence"](supplied)
        emit("deploy", supplied, deploy_refusal("LINEAR", "LINEAR_WORK_RUNTIME", "BINDING_MISMATCH"), ["LIFE-003"],
            "The deployment has " + mismatch + " with all authorization commitments recomputed. Accepted status cannot waive exact source binding or four distinct record identifiers.")

    for violation in ("pending-source", "mismatched-policy"):
        state = copy.deepcopy(base["deploy_result"]["state"])
        if violation == "pending-source":
            state["deployment_source_confirmation_evidence"]["status"] = "PENDING"
        else:
            state["deployment_policy_decision_evidence"]["subject_digest"] = "sha256:" + "1" * 64
        rechain_deployment(state)
        event = bind_event(base["clock_event"], state)
        event["event_id"] = "restart-" + violation
        emit("step", step_input(base, state, event), stateful_refusal(state, "STATE_INVALID"), ["LIFE-003", "LIFE-019"],
            "A revision-zero restart carries " + violation + ". Every evidence, authorization subject, authorization and root activation commitment is recomputed before the new clock event; there are no receipts to leave stale. State admission still refuses the deployment violation.")

    emit("step", step_input(base, base["deploy_result"]["state"], base["clock_event"]), base["clock_result"], ["LIFE-003", "LIFE-014"],
        "The accepted new snapshot deployment admits the available proposal clock.")
    emit("step", step_input(base, base["clock_result"]["state"], base["proposal_event"]), permitted, ["LIFE-008", "LIFE-009A"],
        "Proposal authority produces a finite permit retaining its complete STOP_RETAIN authority basis without inventing a dispatch gate.")
    event = dispatch_event(base, permitted, event_id="new-snapshot-send")
    dispatched = retained(dispatch_result(permitted, event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED"), permitted["permit"])
    emit("step", step_input(base, permitted["state"], event), {**dispatched, "permit": None}, ["LIFE-009", "LIFE-009A"],
        "Direct timely dispatch of the exact request is recorded without an authorization digest.")

    safe_event = dispatch_event(base, permitted, event_id="new-snapshot-not-sent", attempt_status="NOT_SENT")
    safe = retained(dispatch_result(permitted, safe_event, disposition="DISPATCH_REFUSED", reasons=["NATIVE_NOT_SENT"], occurrence_status="PERMITTED"), permitted["permit"])
    emit("step", step_input(base, permitted["state"], safe_event), {**safe, "permit": None}, ["LIFE-009"],
        "Reliable NOT_SENT with no acknowledgement leaves the still-valid finite permit available.")
    after_safe = dispatch_event(base, safe, event_id="new-snapshot-send-after-not-sent")
    after_safe["attempt"]["attempt_id"] = "confirmed-send-after-not-sent"
    emit("step", step_input(base, safe["state"], after_safe), dispatch_result(safe, after_safe, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED"), ["LIFE-009"],
        "A distinct send within the same permit lifetime follows confirmed NOT_SENT. The safe first attempt did not consume authority.")

    expiry_helpers = runpy.run_path(str(HERE / "build-dispatch-cases.py"))
    expired = expiry_helpers["later_clock"](base, permitted)
    for status, disposition, reasons, occurrence_status in (
        ("NOT_SENT", "DISPATCH_REFUSED", ["NATIVE_NOT_SENT", "PERMIT_EXPIRED"], "PERMITTED"),
        ("SENT", "DISPUTED", ["PERMIT_EXPIRED"], "BLOCKED_DISPUTE"),
    ):
        event = dispatch_event(base, expired, event_id="snapshot-expired-" + status.lower(), attempt_status=status,
            attempted_at="2026-09-10T04:35:00Z", clock_revision="2")
        emit("step", step_input(base, expired["state"], event), dispatch_result(expired, event, disposition=disposition, reasons=reasons, occurrence_status=occurrence_status), ["LIFE-008", "LIFE-009"],
            "At the exclusive finite-permit expiry, " + status + " is disqualified. A reported send remains factual disputed evidence.")

    native = completion_native(base, dispatched, status="OUTCOME_UNKNOWN")
    event = governed_effect_event(permitted, dispatched, native, event_id="new-snapshot-unknown")
    stopped = retained(terminal_effect_result(base, dispatched, event, classification="UNKNOWN", disposition="OUTCOME_RETAINED",
        reason_codes=["UNKNOWN_OUTCOME"], occurrence_status="OUTCOME_UNKNOWN", disputed=False), permitted["permit"])
    emit("step", step_input(base, dispatched["state"], event), {**stopped, "permit": None}, ["LIFE-006A", "LIFE-010"],
        "Unknown completion stops the new ungated operation with null authorization digest in its retained outcome and terminal record.")
    proposal = bind_event(base["proposal_event"], stopped["state"])
    proposal["event_id"] = "new-snapshot-reproposal-after-unknown"
    emit("step", step_input(base, stopped["state"], proposal), stateful_refusal(stopped["state"], "INSTANCE_NOT_ACTIVE"), ["LIFE-005", "LIFE-008", "LIFE-010"],
        "LIFE-005 refuses a new proposal on a STOPPED instance before occurrence eligibility. The stopped uncertain occurrence cannot obtain a new permit by proposing the same request again.")
    for status in ("NOT_SENT", "SENT"):
        event = dispatch_event(base, stopped, event_id="new-snapshot-after-unknown-" + status.lower(), attempt_status=status)
        event["attempt"]["attempt_id"] = "after-unknown-" + status.lower()
        expected = stateful_refusal(stopped["state"], "PREREQUISITE_MISSING") if status == "NOT_SENT" else dispatch_result(
            stopped, event, disposition="DISPUTED", reasons=["LATE_OR_PROHIBITED_DISPATCH"], occurrence_status="BLOCKED_DISPUTE")
        emit("step", step_input(base, stopped["state"], event), expected, ["LIFE-009", "LIFE-010"],
            "After unknown completion, a fresh " + status + " attempt cannot obtain execution authority. A reported prohibited send is retained as disputed evidence, not silently discarded.")
    event = lookup_event(base, dispatched)
    emit("step", step_input(base, dispatched["state"], event), lookup_result(base, dispatched, event), ["LIFE-006A", "LIFE-010"],
        "Completion lookup binds the exact permit and dispatch with null authorization throughout query, check and terminal record.")
    native = completion_native(base, dispatched)
    event = governed_effect_event(permitted, dispatched, native, event_id="new-snapshot-exact-completion")
    emit("step", step_input(base, dispatched["state"], event), terminal_effect_result(base, dispatched, event, classification="MATCHED",
        disposition="COMPLETED", reason_codes=[], occurrence_status=None, disputed=False, complete_disposition="SUCCEEDED", route=True), ["LIFE-006A", "LIFE-010"],
        "A complete exact provider record completes the newly authored ungated operation normally.")

    event = AUTHORIZATION["authorization_event"](base, permitted, event_id="new-snapshot-optional-authorization")
    event["authorization_fence"].update(provider="snapshot-approval-provider", source="snapshot-approval-register",
        approval_id="snapshot-approval-1", approver_role="card-grantor")
    missing_fence = copy.deepcopy(event)
    missing_fence["event_id"] = "new-snapshot-null-fence"
    missing_fence["authorization_fence"] = None
    emit("step", step_input(base, permitted["state"], missing_fence), stateful_refusal(permitted["state"], "INPUT_INVALID"), ["LIFE-009A"],
        "An ungated definition electing AUTHORIZE_DISPATCH still requires a nonnull fence.")
    authorized = AUTHORIZATION["authorization_result"](base, permitted, event)
    emit("step", step_input(base, permitted["state"], event), authorized, ["LIFE-009A"],
        "The optional effective fence produces a retained authorization for the exact finite permit, request and connector.")
    current = retained(authorized, permitted["permit"])
    authorization_digest = authorized["state"]["authorizations"][0]["authorization_digest"]
    event = dispatch_event(base, current, event_id="new-snapshot-bound-authorization", authorization_digest=authorization_digest)
    emit("step", step_input(base, authorized["state"], event), dispatch_result(current, event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED"), ["LIFE-009A"],
        "Dispatch names the optional authorization that was retained for this permit.")
    missing_digest = copy.deepcopy(event)
    missing_digest["event_id"] = "new-snapshot-missing-retained-digest"
    del missing_digest["authorization_digest"]
    emit("step", step_input(base, authorized["state"], missing_digest), stateful_refusal(authorized["state"], "PREREQUISITE_MISSING"), ["LIFE-009A"],
        "After an optional authorization was retained, the ungated definition cannot omit its dispatch digest.")

    supplied = step_input(base, permitted["state"], dispatch_event(base, permitted, event_id="predecessor-request-pin"))
    supplied["specification_pin"] = PREDECESSOR_PIN
    emit("step", supplied, stateful_refusal(permitted["state"], "VERSION_UNSUPPORTED"), ["WCS2-001", "LIFE-019"],
        "The successor consumer refuses a predecessor-pin request without migrating its authority.")
    state = copy.deepcopy(permitted["state"])
    state["specification_pin"] = PREDECESSOR_PIN
    current = {"state": state, "state_digest": state_digest(state), "permit": permitted["permit"]}
    emit("step", step_input(base, state, dispatch_event(base, current, event_id="predecessor-retained-state-pin")), stateful_refusal(state, "STATE_INVALID"), ["WCS2-001", "LIFE-019"],
        "LIFE-019 requires candidate-pin agreement throughout retained state and refuses disagreement as STATE_INVALID before the next event. Rehashing the outer state does not migrate that state.")

    flow_builders = runpy.run_path(str(HERE / "build-information-flow-cases.py"))
    flow = flow_builders["source_trace"](compensation=True)["authority"]
    flow["work_class"]["steps"][0].pop("dispatch_gate")
    rebind_outer(flow)
    emit("evaluate", {"kind": "AUTHORITY", "request": flow}, authority_refusal([], code="UNSUPPORTED_RELATION"), ["FLOW-006", "FLOW-007"],
        "The selected compensation information-flow declaration remains present with its source requirements and evidence. Removing its mandatory SOURCE_REQUIREMENTS gate cannot select snapshot fallback; outer authorization commitments are rebound.")
    assessment = assessment_authority()[0]
    assessment["work_class"]["steps"][0].pop("dispatch_gate")
    rebind_outer(assessment)
    emit("evaluate", {"kind": "AUTHORITY", "request": assessment}, authority_refusal([], code="UNSUPPORTED_RELATION"), ["ASSESS-001", "ASSESS-002"],
        "The selected content assessment and approval declarations remain present. Removing their mandatory SOURCE_REQUIREMENTS gate cannot select snapshot fallback; outer authorization commitments are rebound.")
    return rows


def main():
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    files = [Path(__file__).resolve(), SOURCE_PATH, *(GROUP / (row["id"] + ".json") for row in rows)]
    inventory = {
        "status": "EXPECTATIONS_NOT_EXECUTED", "consumer_execution_for_derivation": False,
        "consumer_execution_for_derivation_scope": "Normative constructors derive the current inputs and expected results; retained diagnostic execution preceded these corrections.",
        "diagnostic_consumer_execution_preceded_this_fixture_revision": True,
        "expected_results_copied_from_consumer": False,
        "runtime_admission_investigated": True,
        "candidate_pin": rows[0]["input"]["specification_pin"], "case_count": str(len(rows)),
        "files": [{"path": str(path.relative_to(CASES.parents[3])), "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()} for path in files],
    }
    generation_root = Path(os.environ.get("WORK_CLASS_GENERATION_ROOT", str(ROOT / "runs/2026-10-09-snapshot-successor/generation")))
    write_canonical_json(generation_root / "snapshot/EXPECTATION-INVENTORY.json", inventory)
    print(json.dumps({"cases": len(rows), "candidate_pin": inventory["candidate_pin"],
        "consumer_execution_for_derivation": False,
        "diagnostic_consumer_execution_preceded_this_fixture_revision": True,
        "expected_results_copied_from_consumer": False, "runtime_admission_investigated": True}))


if __name__ == "__main__":
    main()
