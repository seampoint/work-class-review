#!/usr/bin/env python3
"""Freeze author-derived bank vectors before any bank consumer comparison."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

from corpus_common import CASES, CONFORMANCE, ROOT, canonical_bytes, digest, exact_case, write_canonical_json
from authority_fixture import authority_refusal
from lifecycle_factory import step_input, stateful_refusal, governed_effect_event
import assessment_fixture as customer
import bank_fixture as bank
import flow_fixture as flow
import holdings_fixture as holdings

GROUP = CASES / "bank-source"
SPECIMEN = CONFORMANCE / "specimens/bank-sar-filing"
GENERATION_ROOT = Path(os.environ.get("WORK_CLASS_GENERATION_ROOT", str(ROOT / "runs/2026-10-08-overnight"))).resolve()
RUN = GENERATION_ROOT / "bank"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.3"


def build():
    rows, labels, streams = [], {}, {}
    def emit(operation, supplied, expected, text, label, refs):
        case_id = "C3-BANK-" + str(len(rows) + 1).zfill(3)
        row = exact_case(case_id, operation, supplied, expected, refs, text + " Author-derived judgment from the provisional fictional source and public contract, selected before runtime comparison.")
        rows.append(row); labels[label] = case_id
        return row
    def evaluate(supplied, expected, text, label, refs): return emit("evaluate", {"kind": "AUTHORITY", "request": supplied}, expected, text, label, refs)
    def policy_denial(supplied, check):
        result = authority_refusal([check])
        if supplied.get("decision_bases") is not None: result["decision_results"] = bank.complete_expected(supplied)["decision_results"]
        return result
    config, initialization, initialized = bank.remit_registry(); holdings_state = initialized["state"]
    emit("holdings-step", initialization, initialized, "The bank seeds three distinct actors and current mutually exclusive reporting permissions.", "initialize-remit", ["HOLD-001", "HOLD-002", "HOLD-003"])
    preparation, preparation_result = bank.prepare_authority(config, holdings_state)
    evaluate(preparation, preparation_result, "Governed preparation requires current SAR_PREPARE and binds the complete native package and supporting manifest.", "preparation-current", ["HOLD-004", "HOLD-005"])
    preparation_revoke = holdings.request(config, holdings_state, kind="REVOKE", event_id="revoke-mrb-prepare", at=bank.NOW, grant_id="mrb-prepare-01", actor="sar-preparation-agent-01", permission="SAR_PREPARE")
    revoked_preparation = holdings.transition(preparation_revoke, "REVOKED")
    missing_prepare = copy.deepcopy(preparation); missing_prepare["holdings_bases"] = [holdings.basis(config, revoked_preparation["state"], bank.NOW)]
    req = missing_prepare["envelope"]["holdings_requirements"][0]
    evaluate(missing_prepare, policy_denial(missing_prepare, holdings.holdings_check(req, "sar-preparation-agent-01", bank.NOW, "CURRENT_HOLDING_REQUIRED")), "Preparation permission absent at the governed preparation commitment cannot be supplied by later filing authority.", "preparation-revoked", ["HOLD-004", "HOLD-005"])
    supplied, expected, facts = bank.authority(config, holdings_state)
    evaluate(supplied, expected, "The exact initial SAR combines complete native XML, all nine retained support records, model assessment, historical human approval, current selected reviewer and submission holdings, and nonreleasable reporting flow.", "exact-initial-filing", ["ASSESS-001", "ASSESS-002", "AUTH-008", "HOLD-004", "FLOW-004", "FLOW-005"])
    reviewer_revoke = holdings.request(config, holdings_state, kind="REVOKE", event_id="revoke-mrb-reviewer", at=bank.NOW, grant_id="mrb-approve-01", actor="sar-review-officer-01", permission="SAR_APPROVE")
    revoked = holdings.transition(reviewer_revoke, "REVOKED")
    emit("holdings-step", reviewer_revoke, revoked, "Revocation changes current permission without modifying the retained signed approval.", "reviewer-revocation", ["HOLD-001", "HOLD-003"])
    denied = copy.deepcopy(supplied); denied["holdings_bases"] = [holdings.basis(config, revoked["state"], bank.NOW)]
    req = denied["envelope"]["holdings_requirements"][0]
    evaluate(denied, policy_denial(denied, holdings.holdings_check(req, "sar-review-officer-01", bank.NOW, "CURRENT_HOLDING_REQUIRED")), "The selected reviewer's absent current permission blocks reliance; the exact historical human approval remains valid evidence.", "reviewer-revoked-filing", ["HOLD-004", "HOLD-005", "AUTH-008"])
    regrant = holdings.request(config, revoked["state"], kind="GRANT", event_id="regrant-mrb-reviewer", at=bank.NOW, grant_id="mrb-approve-02", actor="sar-review-officer-01", permission="SAR_APPROVE")
    restored_registry = holdings.transition(regrant, "GRANTED")
    emit("holdings-step", regrant, restored_registry, "A valid regrant records a new current permission and preserves the revoked earlier grant.", "reviewer-regrant", ["HOLD-001", "HOLD-003"])
    restored = copy.deepcopy(supplied); restored["holdings_bases"] = [holdings.basis(config, restored_registry["state"], bank.NOW)]
    evaluate(restored, bank.complete_expected(restored), "Regrant restores reliance on the unchanged exact, unwithdrawn and unexpired approval; no live historical reviewer session is required.", "reviewer-regrant-filing", ["HOLD-004", "HOLD-005", "AUTH-008"])
    conflict = holdings.request(config, holdings_state, kind="GRANT", event_id="conflicting-mrb-grant", at=bank.NOW, grant_id="mrb-submit-reviewer", actor="sar-review-officer-01", permission="SAR_SUBMIT")
    emit("holdings-step", conflict, holdings.transition(conflict, "WITHHELD", ["CONFLICTING_HOLDING"]), "The reviewer cannot concurrently obtain SAR_SUBMIT; this source selects no exception.", "incompatible-permission", ["HOLD-001", "HOLD-003"])
    for n, (request, result) in enumerate(zip(facts["flow_requests"], facts["flow_results"]), 1):
        emit("flow-step", request, result, "The bank preparation and submission contexts retain exact whole origins and reporting restrictions through step " + str(n) + ".", "protected-flow-" + str(n), ["FLOW-001", "FLOW-002", "FLOW-003"])
    changed = copy.deepcopy(supplied); next(row for row in changed["proposal"]["fields"] if row["name"] == "native_payload_utf8")["value"]["value"] += " "
    evaluate(changed, authority_refusal([], code="BINDING_MISMATCH"), "Even a one-byte XML change after review disagrees with the immutable materialized artifact and requires a new package and review.", "changed-xml-after-review", ["FLOW-004", "ASSESS-001", "AUTH-008"])
    base = bank.lifecycle_base(config, holdings_state); permission = bank.permitted(base)
    authorization_event, authorized, exposure = bank.authorized(base, permission)
    dispatch_event, dispatched = bank.dispatched(base, authorized)
    completion_event, completed = bank.completed(base, dispatched)
    lifecycle = [emit("deploy", base["deploy_input"], base["deploy_result"], "The exact filing workflow installs with explicit provisional source evidence; mechanical deployment mappings make no full source correspondence claim.", "filing-deploy", ["LIFE-003"]),
        emit("step", step_input(base, base["deploy_result"]["state"], base["clock_event"]), bank.public_result(base["clock_result"]), "The bank records the current attributable clock before proposal.", "filing-clock", ["LIFE-001"]),
        emit("step", step_input(base, base["clock_result"]["state"], base["proposal_event"]), bank.public_result(permission), "The filing permit retains complete holdings, assessment, human and flow evidence.", "filing-permit", ["HOLD-006", "FLOW-007", "ASSESS-004"]),
        emit("step", step_input(base, permission["state"], authorization_event), bank.public_result(authorized), "Current exact filing authorization retains both selected reviewer/executor holdings and the whole disclosure fence.", "filing-authorization", ["HOLD-006", "FLOW-007"]),
        emit("flow-step", exposure[0], exposure[1], "Disclosure records the stable filing intent and attempt claim before any gateway custody exposure.", "filing-exposure", ["FLOW-003", "FLOW-007"]),
        emit("step", step_input(base, authorized["state"], dispatch_event), bank.public_result(dispatched), "Transport dispatch records one attempted transmission and establishes no accepted filing.", "filing-dispatch", ["LIFE-001", "LIFE-009B"]),
        emit("step", step_input(base, dispatched["state"], completion_event), bank.public_result(completed), "The portable controlled-provider completion matches the exact request, generated receipt identity/time, declared accepted status and fixed stage. Complete raw receipt and variable facts remain in a separately protected sidecar; this carrier does not qualify a real acknowledgement.", "filing-completion", ["LIFE-009", "LIFE-009B"])]
    warning_event, warning_result = bank.completed(base, dispatched, warnings=[{"code": "SYNTHETIC-WARNING-17", "field": "unknown-counterparty", "text": "Review this declared unresolved value."}, {"code": "SYNTHETIC-WARNING-29", "field": "narrative", "text": "A second variable warning remains retained."}])
    emit("step", step_input(base, dispatched["state"], warning_event), bank.public_result(warning_result), "Accepted filing with warnings remains a historical filing. The separately protected receipt sidecar retains the complete warning inventory and correction-duty requirement; portable completion does not inspect those sidecar semantics.", "accepted-with-warnings", ["LIFE-009", "LIFE-009B"])
    customer_authority, _, _ = customer.authority()
    scope = customer_authority["envelope"]["scope"]["id"]; flow_config = facts["flow_configuration"]; customer_state = exposure[1]["state"]
    customer_stages = []
    pair = flow.create(flow_config, customer_state, context_id="mrb-independent-customer-context", actor="customer-message-agent-01", scope=scope, purpose="REQUEST_TRANSFER_FACTS", ceiling=[], at=customer.NOW)
    customer_stages.append(pair); customer_state = pair[1]["state"]
    source_body = {"facts": customer.fact_values(), "contact_authority": {"recipient": "customer-074", "purpose": "REQUEST_TRANSFER_FACTS"}, "reporting_information": "EXCLUDED"}
    descriptor = flow.source_descriptor(provider="customer-facts-provider.invalid", source="independent-customer-facts", record_type="CUSTOMER_FACTS", record_id="MRB-CUSTOMER-FACTS-074", revision="revision-1", content_digest="sha256:" + hashlib.sha256(canonical_bytes(source_body)).hexdigest(), scope=scope, restrictions=[])
    pair = flow.read(flow_config, customer_state, descriptor, context_id="mrb-independent-customer-context", role="customer-message-agent", event_id="read-mrb-independent-customer-facts", at=customer.NOW)
    customer_stages.append(pair); customer_state = pair[1]["state"]
    pair = flow.materialize(flow_config, customer_state, context_id="mrb-independent-customer-context", artifact_id="mrb-independent-customer-message", types=customer_authority["work_class"]["types"], native_fields=customer_authority["proposal"]["fields"], at=customer.NOW)
    customer_stages.append(pair); customer_state = pair[1]["state"]
    customer_authority, customer_result = flow.attach_bank_flow(flow_config, customer_state, customer_authority, context_id="mrb-independent-customer-context", artifact_id="mrb-independent-customer-message")
    for n, pair in enumerate(customer_stages, 1): emit("flow-step", pair[0], pair[1], "A separate customer context reads only independently authorized underlying facts, without receiving the SAR workflow's retained origins, step " + str(n) + ".", "independent-customer-" + str(n), ["FLOW-001", "FLOW-002", "FLOW-003"])
    evaluate(customer_authority, customer_result, "The independently reviewed factual customer request has its own authority and fresh clean context while the global protected history remains retained.", "independent-customer-authority", ["FLOW-004", "FLOW-005", "ASSESS-001", "AUTH-008"])
    customer_trace = flow.lifecycle_trace({"authority": customer_authority, "configuration": flow_config, "state": customer_state, "at": customer.NOW, "context_id": "mrb-independent-customer-context", "artifact_id": "mrb-independent-customer-message"}, instance="bank-independent-customer-instance-074")
    customer_lifecycle = []
    for n, (operation, request, result) in enumerate(customer_trace["stages"], 1):
        customer_lifecycle.append(emit(operation, request, result, "The separate customer workflow has its own exact authority, current recipient and disclosure commitment without a filing-completion prerequisite, stage " + str(n) + ".", "customer-workflow-" + str(n), ["LIFE-001", "FLOW-004", "FLOW-007", "ASSESS-004"]))
    cb, ca = customer_trace["base"], bank.retained(customer_trace["authorized"], customer_trace["permitted"]["permit"])
    customer_dispatch, customer_dispatched = customer.dispatched(cb, ca)
    customer_clock, customer_clocked = customer.completion_clock(cb, customer_dispatched)
    customer_completion, customer_completed = customer.completed(cb, customer_clocked)
    for label, request, before, result in [("customer-dispatch", customer_dispatch, ca, customer_dispatched), ("customer-completion-clock", customer_clock, customer_dispatched, customer_clocked), ("customer-completion", customer_completion, customer_clocked, customer_completed)]:
        customer_lifecycle.append(emit("step", step_input(cb, before["state"], request), bank.public_result(result), "The customer message retains its own transport and declared portal-acceptance evidence. No customer reading or reporting-status disclosure is inferred.", label, ["LIFE-001", "LIFE-009", "FLOW-007"]))
    delayed_grants = [holdings.initial_grant("mrb-prepare-01", "sar-preparation-agent-01", "SAR_PREPARE", start="2026-09-01T00:00:00Z"), holdings.initial_grant("mrb-approve-delayed", "sar-review-officer-01", "SAR_APPROVE", start="2026-10-06T15:05:00Z"), holdings.initial_grant("mrb-submit-01", "sar-submission-agent-01", "SAR_SUBMIT", start="2026-09-01T00:00:00Z")]
    delayed_input = holdings.request(config, grants=delayed_grants, at="2026-10-06T15:06:00Z", event_id="initialize-delayed-mrb-remit")
    delayed_state = holdings.transition(delayed_input, "INITIALIZED")["state"]
    before_remit, _, _ = bank.authority(config, delayed_state, signing_state=delayed_state)
    leaf = before_remit["decision_bases"][0]["evidence"]["authority_input"]
    leaf_denial = authority_refusal([{"purpose": "SOURCE_OBSERVATION", "subject_digest": digest("authority-envelope", leaf["envelope"]), "requirement_ref": "signing-time-sar-approve", "at": bank.NOW, "reason": "SOURCE_OBSERVATION_RELATIONS"}])
    before_remit_expected = authority_refusal([{"purpose": "HUMAN_DECISION", "subject_digest": before_remit["decision_bases"][0]["evidence"]["decision_act_digest"], "requirement_ref": bank.DECISION, "at": bank.NOW, "reason": "DECISION_NOT_EFFECTIVE"}])
    before_remit_expected["decision_results"] = [{"requirement_id": bank.DECISION, "result": leaf_denial, "result_digest": digest("authority-result", leaf_denial)}]
    evaluate(before_remit, before_remit_expected, "A reviewer who first obtains SAR_APPROVE after signing cannot supply the required signing-time permission. A current filing-time holding does not repair the original ineligible act.", "approval-before-first-permission", ["AUTH-008", "HOLD-004"])
    amend_preparation, amend_preparation_result = bank.prepare_authority(config, holdings_state, amended=True)
    evaluate(amend_preparation, amend_preparation_result, "A full corrected/amended package requires its own current preparation permission and distinct exact XML review subject.", "amendment-preparation", ["HOLD-004", "ASSESS-001"])
    amendment = bank.lifecycle_base(config, holdings_state, instance="bank-amendment-instance-074", amended=True, prior_flow_state=exposure[1]["state"], prior_filing=completion_event["native_evidence"])
    evaluate(amendment["authority_input"], amendment["authority_result"], "The separately authorized amendment binds the complete accepted initial filing source, generated prior BSA Identifier, fresh assessment/approval, full corrected XML and new submission token.", "amendment-authority", ["AUTH-008", "ASSESS-001", "FLOW-004", "LIFE-009B"])
    for n, pair in enumerate(zip(amendment["facts"]["flow_requests"], amendment["facts"]["flow_results"]), 1): emit("flow-step", pair[0], pair[1], "The amendment retains the original protected registry history and admits a separate current restricted preparation/submission context, stage " + str(n) + ".", "amendment-flow-" + str(n), ["FLOW-001", "FLOW-002", "FLOW-003"])
    amend_permit = bank.permitted(amendment)
    amend_authorization_event, amend_authorized, amend_exposure = bank.authorized(amendment, amend_permit)
    amend_dispatch_event, amend_dispatched = bank.dispatched(amendment, amend_authorized)
    amend_completion_event, amend_completed = bank.completed(amendment, amend_dispatched)
    amendment_lifecycle = [emit("deploy", amendment["deploy_input"], amendment["deploy_result"], "The amendment installs as a separate authorized work instance and preserves the initial filing.", "amendment-deploy", ["LIFE-003"]),
        emit("step", step_input(amendment, amendment["deploy_result"]["state"], amendment["clock_event"]), bank.public_result(amendment["clock_result"]), "The amendment uses its later independent clock.", "amendment-clock", ["LIFE-001"]),
        emit("step", step_input(amendment, amendment["clock_result"]["state"], amendment["proposal_event"]), bank.public_result(amend_permit), "Fresh amended content, prior filing source and human approval form the new permit.", "amendment-permit", ["AUTH-008", "ASSESS-004", "FLOW-007"]),
        emit("step", step_input(amendment, amend_permit["state"], amend_authorization_event), bank.public_result(amend_authorized), "Current reviewer/executor permissions and exact protected first-custody conditions authorize the new token.", "amendment-authorization", ["HOLD-006", "FLOW-007"]),
        emit("flow-step", amend_exposure[0], amend_exposure[1], "The amendment consumes its own new disclosure intent and attempt claim while retaining the initial claim.", "amendment-exposure", ["FLOW-003", "FLOW-007"]),
        emit("step", step_input(amendment, amend_authorized["state"], amend_dispatch_event), bank.public_result(amend_dispatched), "The new exact amendment request has a distinct transport attempt.", "amendment-dispatch", ["LIFE-001", "LIFE-009B"]),
        emit("step", step_input(amendment, amend_dispatched["state"], amend_completion_event), bank.public_result(amend_completed), "The amended filing establishes its own simulated accepted result, native submission, receipt and new BSA Identifier31000000000002.", "amendment-completion", ["LIFE-009", "LIFE-009B"])]
    reused_ack = governed_effect_event(amend_dispatched, amend_dispatched, completion_event["native_evidence"], event_id="reuse-initial-ack-for-amendment", clock_revision=None)
    emit("step", step_input(amendment, amend_dispatched["state"], reused_ack), stateful_refusal(amend_dispatched["state"], "BINDING_MISMATCH"), "The original initial-filing acknowledgement names another exact request and cannot establish this amendment's effect.", "amendment-reused-initial-ack", ["LIFE-009", "LIFE-009B"])
    for row in rows: write_canonical_json(GROUP / (row["id"] + ".json"), row)
    write_canonical_json(SPECIMEN / "normalized-obligations.json", bank.normalized_obligations())
    for name, value in [("holdings-configuration.json", config), ("holdings-initialize-input.json", initialization), ("holdings-initialize-result-derived.json", initialized), ("preparation-authority-input.json", preparation), ("preparation-authority-result-derived.json", preparation_result), ("filing-authority-input.json", base["authority_input"]), ("filing-authority-result-derived.json", base["authority_result"]), ("definition.json", base["definition"]), ("flow-pre-exposure-state.json", base["facts"]["flow_state"]), ("flow-source-record.json", base["facts"]["flow_source"]), ("native-package.json", bank.native_package()), ("amendment-native-package.json", bank.native_package(amended=True)), ("retained-support-records.json", bank.supporting_records()[0]), ("ordered-support-manifest.json", bank.supporting_records()[1]), ("customer-authority-input.json", customer_authority), ("customer-authority-result-derived.json", customer_result)]: write_canonical_json(SPECIMEN / name, value)
    (SPECIMEN / "native-initial-payload.xml").write_bytes(bank.native_package()["payload"].encode())
    (SPECIMEN / "native-amendment-payload.xml").write_bytes(bank.native_package(amended=True)["payload"].encode())
    write_canonical_json(SPECIMEN / "initial-receipt-sidecar.json", bank.receipt_sidecar(base, dispatched, completion_event))
    write_canonical_json(SPECIMEN / "warning-receipt-sidecar.json", bank.receipt_sidecar(base, dispatched, warning_event, warnings=[{"code": "SYNTHETIC-WARNING-17", "field": "unknown-counterparty", "text": "Review this declared unresolved value."}, {"code": "SYNTHETIC-WARNING-29", "field": "narrative", "text": "A second variable warning remains retained."}]))
    (SPECIMEN / "customer-requests.jsonl").write_bytes(b"".join(canonical_bytes({"protocol": PROTOCOL, "request_id": row["id"], "operation": row["operation"], "input": row["input"]}) + b"\n" for row in customer_lifecycle))
    write_canonical_json(SPECIMEN / "customer-results-derived.json", [{"case_id": row["id"], "expected": row["expected"]} for row in customer_lifecycle])
    (SPECIMEN / "amendment-requests.jsonl").write_bytes(b"".join(canonical_bytes({"protocol": PROTOCOL, "request_id": row["id"], "operation": row["operation"], "input": row["input"]}) + b"\n" for row in amendment_lifecycle))
    write_canonical_json(SPECIMEN / "amendment-results-derived.json", [{"case_id": row["id"], "expected": row["expected"]} for row in amendment_lifecycle])
    write_canonical_json(SPECIMEN / "amendment-authority-input.json", amendment["authority_input"])
    write_canonical_json(SPECIMEN / "amendment-receipt-sidecar.json", bank.receipt_sidecar(amendment, amend_dispatched, amend_completion_event))
    (SPECIMEN / "requests.jsonl").write_bytes(b"".join(canonical_bytes({"protocol": PROTOCOL, "request_id": row["id"], "operation": row["operation"], "input": row["input"]}) + b"\n" for row in lifecycle))
    write_canonical_json(SPECIMEN / "results-derived.json", [{"case_id": row["id"], "expected": row["expected"]} for row in lifecycle])
    freeze = {"candidate_pin": bank.PIN, "source": str(bank.SOURCE.relative_to(ROOT)), "source_sha256": "sha256:" + hashlib.sha256(bank.SOURCE.read_bytes()).hexdigest(), "author_independence": "Author-derived; the author also implemented the TypeScript flow consumer. Separate source review pending.", "cases": [{"id": row["id"], "raw_sha256": "sha256:" + hashlib.sha256((GROUP / (row["id"] + ".json")).read_bytes()).hexdigest()} for row in rows], "labels": labels, "retention": "Freeze before bank runtime comparison. Preserve each successor and all observed failures."}
    write_canonical_json(RUN / "BANK-CASE-FREEZE-06.json", freeze)
    # Bind the public specimen metadata to this newly derived successor, rather
    # than leaving the previous pin and case hashes beside the new traces.
    # Keep the original historical seal at its retained location unchanged.
    seal_name = "source-expectation-seal.json"
    write_canonical_json(SPECIMEN / seal_name, freeze)
    inventory = json.loads((SPECIMEN / "case-inventory.json").read_text())
    assert {row["id"] for row in inventory["cases"]} == {row["id"] for row in rows}
    inventory["candidate_pin"] = bank.PIN
    inventory["source_freeze"] = seal_name
    inventory["source_freeze_sha256"] = "sha256:" + hashlib.sha256((SPECIMEN / seal_name).read_bytes()).hexdigest()
    inventory["source_freeze_scope"] = "Source-derived successor; no transferred historical independent acceptance"
    for item in inventory["cases"]:
        item["raw_sha256"] = "sha256:" + hashlib.sha256((CONFORMANCE / item["candidate_path"]).read_bytes()).hexdigest()
    write_canonical_json(SPECIMEN / "case-inventory.json", inventory)
    coverage = json.loads((SPECIMEN / "source-coverage.json").read_text())
    coverage["candidate_pin"] = bank.PIN
    write_canonical_json(SPECIMEN / "source-coverage.json", coverage)
    artifact_index = json.loads((SPECIMEN / "artifact-index.json").read_text())
    artifact_paths = sorted({item["path"] for item in artifact_index["artifacts"]} | {seal_name})
    artifact_index["candidate_pin"] = bank.PIN
    artifact_index["artifacts"] = [{"path": path, "raw_sha256": "sha256:" + hashlib.sha256((SPECIMEN / path).read_bytes()).hexdigest()} for path in artifact_paths]
    write_canonical_json(SPECIMEN / "artifact-index.json", artifact_index)
    print(json.dumps({"cases": len(rows), "source_paragraphs": len(bank.normalized_obligations()["obligations"]), "candidate_pin": bank.PIN, "source_review": "PENDING"}))


if __name__ == "__main__": build()
