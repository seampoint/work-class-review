"""Author-derived fictional bank inputs and expected records, without consumers.

The author also implemented the TypeScript flow consumer. These expectations are
derived from the source and public contract, frozen before runtime comparison,
and require a separate source review. No consumer or observed result is imported.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from corpus_common import candidate_pin, canonical_bytes, digest
from assessment_fixture import (base_authority, expected_authority, rebind_outer,
    fields, typed, TYPES, reliance_subject)
from equipment_observation_fixture import requirement, observation
import holdings_fixture as holdings
import flow_fixture as flow
from bank_native_fixture import package as native_package
from fixture_factory import available_clock, deployment, occurrence as occurrence_record, readback_paths, structural_step
from lifecycle_factory import (admitted_transition, permitted_proposal, step_input,
    dispatch_event, dispatch_result, governed_native_evidence, governed_effect_event, state_digest)
from equipment_dispatch_fixture import retained
from equipment_completion_fixture import terminal_effect_result

SCHEMA = "seampoint.work-class/1.0.0-draft.3/"
PIN = candidate_pin()
HERE = Path(__file__).resolve().parent
SOURCE = HERE / "fixtures/bank-sar-filing-and-customer-communication-revision2-source.md"
SOURCE_ID = "bank-sar-filing-and-customer-communication-revision2-source"
PRINCIPAL = "MRB-US-01"
STEP = "submit-initial-sar"
DECISION = "exact-sar-package-approval"
ASSESSMENT = "sar-content-assessment"
APPROVAL = "current-sar-approval-record"
NOW = "2026-10-06T15:10:00Z"
SIGNED = "2026-10-06T15:00:00Z"
ASSESSED = "2026-10-06T14:59:00Z"
END = "2026-10-07T15:00:00Z"
EVALUATOR = {"provider": "bank-assessment-provider.invalid", "model": "synthetic-sar-content-review", "version": "revision-1"}
CRITERIA = ["complete-native-correspondence", "evidence-grounded-narrative", "explicit-unresolved-facts", "neutral-language", "no-invented-guilt-or-intent"]


def filing_times(native):
    if native["filing_type"]["value"] == "CORRECT_AMEND":
        return {"now": "2026-10-06T15:20:00Z", "signed": "2026-10-06T15:19:00Z", "assessed": "2026-10-06T15:18:00Z", "end": "2026-10-07T15:19:00Z", "signer_until": "2026-10-06T15:19:30Z"}
    return {"now": NOW, "signed": SIGNED, "assessed": ASSESSED, "end": END, "signer_until": "2026-10-06T15:05:00Z"}


def normalized_obligations():
    rows, paragraph, heading = [], [], ""
    def emit():
        if paragraph:
            text = " ".join(paragraph)
            if not text.startswith("Source revision 2,"):
                rows.append({"id": "BANK-OBL-" + str(len(rows) + 1).zfill(3), "heading": heading, "text": text})
            paragraph.clear()
    for line in [*SOURCE.read_text().splitlines(), ""]:
        if line.startswith("#"):
            emit(); heading = line.lstrip("# ")
        elif not line.strip(): emit()
        else: paragraph.append(line)
    return {"source_id": SOURCE_ID, "source_revision": "revision-2", "source_raw_sha256": "sha256:" + hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "obligations": rows}


def source():
    return {"schema": SCHEMA + "authority-source", "id": SOURCE_ID, "revision": "revision-2",
        "obligations": [{"id": row["id"], "text": row["text"]} for row in normalized_obligations()["obligations"]]}


def supporting_records():
    selected = [
        ("bank-institution-provider.invalid", "MRB-INSTITUTION-01", "1", {"bank_id": PRINCIPAL, "name": "Maple Research Bank", "address": "100 Example Plaza, Boston, MA 02110", "country": "US", "ein": "123456789", "rssd": "1234567", "transmitter_control": "TBSATEST"}),
        ("bank-contact-provider.invalid", "MRB-CONTACT-01", "1", {"contact": "Example Filing Contact", "office": "MRB Reporting Office", "phone": "2025550100"}),
        ("customer-diligence-provider.invalid", "MRB-CDD-074", "4", {"customer_id": "customer-074", "name": "Maple Example Trading LLC", "account": "account-074", "address": "200 Example Avenue, Chicago, IL 60601", "ein": "987654321", "identification_document": "UNKNOWN"}),
        ("transaction-provider.invalid", "MRB-TXN-081", "1", {"date": "2026-09-08", "direction": "OUTGOING", "currency": "USD", "amount": "NOT_SUPPLIED", "counterparty": "NOT_SUPPLIED", "account": "account-074", "status": "COMPLETED"}),
        ("transaction-provider.invalid", "MRB-TXN-082", "1", {"date": "2026-09-10", "direction": "OUTGOING", "currency": "USD", "amount": "NOT_SUPPLIED", "counterparty": "NOT_SUPPLIED", "account": "account-074", "status": "COMPLETED"}),
        ("transaction-provider.invalid", "MRB-TXN-083", "1", {"date": "2026-09-12", "direction": "OUTGOING", "currency": "USD", "amount": "NOT_SUPPLIED", "counterparty": "NOT_SUPPLIED", "account": "account-074", "status": "COMPLETED"}),
        ("investigation-provider.invalid", "MRB-INVESTIGATION-074", "6", {"case_id": "MRB-CASE-074", "transaction_records": ["MRB-TXN-081", "MRB-TXN-082", "MRB-TXN-083"], "total_currency": "USD", "total_amount": "84000", "business_purpose": "UNRESOLVED", "guilt": "NOT_ESTABLISHED", "intent": "NOT_ESTABLISHED"}),
        ("detection-provider.invalid", "MRB-DETECTION-074", "1", {"initial_detection_date": "2026-09-14", "suspect_identified": True, "owner": "investigation-owner-01"}),
        ("reporting-decision-provider.invalid", "MRB-DECISION-074", "1", {"decision": "FILE_INITIAL_SAR", "bank_id": PRINCIPAL, "case_id": "MRB-CASE-074", "immediate_attention": False, "officer": "bsa-officer-01"}),
    ]
    records = [{"provider": provider, "source": "bank-retained-support", "record_type": "SUPPORTING_RECORD", "record_id": record_id, "revision": revision,
        "content_digest": "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest(), "body": body} for provider, record_id, revision, body in selected]
    records.sort(key=lambda row: canonical_bytes({k: row[k] for k in ["provider", "record_id", "revision"]}))
    manifest = [{k: row[k] for k in ["provider", "source", "record_type", "record_id", "revision", "content_digest"]} for row in records]
    return records, manifest


def native_values(*, amended=False):
    package, (_, manifest) = native_package(amended=amended), supporting_records()
    values = {"bank_id": typed(PRINCIPAL), "case_id": typed("MRB-CASE-074"), "recipient": typed("MRB-GOVERNED-FILING-GATEWAY"),
        "destination": typed("FINCEN-BSA-EFILING", "STRING"), "gateway_endpoint": typed("https://filing.maple-research.invalid", "STRING"), "package_id": typed("MRB-SAR-074-AMEND-01" if amended else "MRB-SAR-074"),
        "package_revision": typed("1", "REVISION"), "filing_type": typed(package["kind"]), "format_revision": typed("FinCEN-SAR-XML-2.0-guide-1.7-April-2026", "STRING"),
        "serializer": typed(package["serializer"], "STRING"), "native_payload_utf8": typed(package["payload"], "STRING"),
        "native_payload_digest": typed("sha256:" + package["payload_sha256"]), "supporting_manifest": typed(canonical_bytes(manifest).decode(), "STRING"),
        "native_correspondence_digest": typed(digest("bank-native-correspondence", {key: package[key] for key in ["field_correspondence", "conditional_correspondence", "source", "serializer"]})),
        "supporting_manifest_digest": typed(digest("bank-supporting-manifest", manifest)), "attachment_count": typed("0", "COUNT"),
        "submission_token": typed("MRB-SUBMIT-074-AMEND-01" if amended else "MRB-SUBMIT-074-01")}
    if amended: values["prior_bsa_identifier"] = typed("31000000000001")
    return values


def projection(values, *, leaf=False, prepare=False):
    step_id = "approve-exact-sar-package" if leaf else "prepare-sar-package" if prepare else "submit-corrected-amended-sar" if values["filing_type"]["value"] == "CORRECT_AMEND" else STEP
    return {"id": step_id, "interface": "bank-human-reporting-decisions" if leaf else "bank-governed-preparation" if prepare else "synthetic-sar-filing-gateway",
        "operation": step_id, "executor_role": "sar-review-officer" if leaf else "sar-preparation-agent" if prepare else "sar-submission-agent",
        "fields": [{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in fields(values)],
        "scope_fields": {"subjects": ["bank_id", "case_id"], "resources": ["package_id"]}, "required_credentials": [] if leaf else ["message-authenticated-session"], "quantity_mode": "NONE", "exclusive_keys": []}


def bank_base(work, values, **options):
    times = filing_times(values)
    supplied = base_authority(work, values, principal=PRINCIPAL, signed=times["signed"], now=times["now"], **options)
    supplied["source"] = source(); supplied["envelope"]["source_obligations"] = sorted(row["id"] for row in supplied["source"]["obligations"])
    supplied["envelope"]["temporal_validity"]["valid_until"] = times["end"]
    if options.get("gate_requirement") == DECISION: supplied["envelope"]["gate"]["role"] = "sar-review-officer"
    rebind_outer(supplied)
    return supplied


def remit_registry():
    config = holdings.configuration(principal=PRINCIPAL, registry_id="MRB-REMIT", permissions=["SAR_APPROVE", "SAR_PREPARE", "SAR_SUBMIT"],
        conflicts=[{"left": "SAR_APPROVE", "right": "SAR_PREPARE"}, {"left": "SAR_APPROVE", "right": "SAR_SUBMIT"}], clock_source="component-component-clock")
    config["policy_revision"] = "revision-3"
    grants = [holdings.initial_grant("mrb-prepare-01", "sar-preparation-agent-01", "SAR_PREPARE", start="2026-09-01T00:00:00Z"),
        holdings.initial_grant("mrb-approve-01", "sar-review-officer-01", "SAR_APPROVE", start="2026-09-01T00:00:00Z"),
        holdings.initial_grant("mrb-submit-01", "sar-submission-agent-01", "SAR_SUBMIT", start="2026-09-01T00:00:00Z")]
    supplied = holdings.request(config, grants=grants, at="2026-10-06T14:00:00Z", event_id="initialize-mrb-remit")
    result = holdings.transition(supplied, "INITIALIZED")
    return config, supplied, result


def prepare_authority(config, state, *, amended=False):
    values = native_values(amended=amended); operation = projection(values, prepare=True)
    work = {"schema": SCHEMA + "authority-work-class", "id": "bank-sar-preparation", "revision": "revision-2", "types": copy.deepcopy(TYPES), "steps": [operation]}
    supplied = bank_base(work, values, role=operation["executor_role"], actor="sar-preparation-agent-01", instance="bank-preparation-074", occurrence="bank-preparation-074-occurrence")
    supplied["envelope"]["gate"] = {"kind": "NONE", "role": None, "criteria": [], "materiality": "LOW", "reversibility": "HIGH"}
    supplied["envelope"]["holdings_requirements"] = [holdings.requirement(config, requirement_id="current-sar-prepare", permission="SAR_PREPARE", step=operation["id"])]
    supplied["holdings_bases"] = [holdings.basis(config, state, filing_times(values)["now"])]; rebind_outer(supplied)
    return supplied, complete_expected(supplied)


def rubric():
    obligations = source()["obligations"]
    selected = [obligations[i - 1] for i in [13, 14, 15, 16, 17, 18, 19]]
    return {"id": "MRB-NARRATIVE-RULES", "revision": "revision-2", "obligations": selected,
        "criteria": [{"id": name, "obligation_ids": [row["id"] for row in selected], "citation_policy": "CONTEXT" if name == "evidence-grounded-narrative" else "PROPOSAL"} for name in CRITERIA]}


def assessment_body(work, proposal):
    native = {row["name"]: row["value"] for row in proposal["fields"]}; times = filing_times(native); amended = native["filing_type"]["value"] == "CORRECT_AMEND"
    records, manifest = supporting_records()
    values = {"bank_id": typed(PRINCIPAL), "case_id": typed("MRB-CASE-074"), "supporting_manifest": typed(canonical_bytes(manifest).decode(), "STRING"),
        "retained_records": typed(canonical_bytes(records).decode(), "STRING")}
    package = native_package(amended=amended)
    values["native_correspondence"] = typed(canonical_bytes({key: package[key] for key in ["field_correspondence", "conditional_correspondence", "source", "serializer"]}).decode(), "STRING")
    values["native_correspondence_digest"] = copy.deepcopy(native["native_correspondence_digest"])
    snapshot = {"requirement_id": "bank-investigation-context", "provider_record_id": "MRB-CONTEXT-074-AMEND-01" if amended else "MRB-CONTEXT-074", "provider_revision": "revision-1", "fields": fields(values)}
    coordinates = {"provider": "bank-investigation-provider.invalid", "source": "bank-retained-context", "record_type": "INVESTIGATION_CONTEXT"}
    context_body = {"types": copy.deepcopy(work["types"]), "records": [{"requirement_id": snapshot["requirement_id"], **coordinates, **{k: copy.deepcopy(snapshot[k]) for k in ["provider_record_id", "provider_revision", "fields"]}}]}
    context_digest, rubric_digest = digest("content-assessment-context", context_body), digest("content-assessment-rubric", rubric())
    subject = {"principal": PRINCIPAL, **{k: copy.deepcopy(proposal[k]) for k in ["work_class_digest", "instance", "occurrence", "step", "interface", "operation", "fields"]}, "context_digest": context_digest, "rubric_digest": rubric_digest, "evaluator": copy.deepcopy(EVALUATOR)}
    assessment = {"id": "MRB-SAR-ASSESSMENT-074-AMEND-01" if amended else "MRB-SAR-ASSESSMENT-074-01", "revision": "revision-1", "provider": EVALUATOR["provider"], "source": "bank-content-assessments", "record_type": "SAR_CONTENT_ASSESSMENT",
        "subject_digest": digest("content-assessment-subject", subject), "context_digest": context_digest, "rubric_digest": rubric_digest, "evaluator": copy.deepcopy(EVALUATOR), "assessed_at": times["assessed"],
        "criteria": [{"id": name, "verdict": "PASS", "explanation": "Synthetic judgment against the complete decoded XML, selected instructions and retained supporting records.", "escalation": {"required": False, "reason": None},
            "citations": [{"kind": "CONTEXT_FIELD", "requirement_id": "bank-investigation-context", "field": "retained_records"}] if name == "evidence-grounded-narrative" else [{"kind": "PROPOSAL_FIELD", "field": "native_payload_utf8"}]} for name in CRITERIA]}
    review = {"id": "MRB-SAR-APPROVAL-074-AMEND-01" if amended else "MRB-SAR-APPROVAL-074-01", "assessment_digest": digest("content-assessment", assessment), "decision": "APPROVE", "criteria": [{"id": name, "disposition": "SATISFIED", "reason": None, "citations": []} for name in CRITERIA]}
    return {"requirement_id": ASSESSMENT, "supporting_context": [snapshot], "assessment": assessment, "review": review}, coordinates, values


def human_leaf(native, assessment, config, signing_state):
    times = filing_times(native); signed = times["signed"]
    coordinates = {"provider": "bank-human-review-provider.invalid", "source": "bank-sar-approvals", "record_type": "SAR_PACKAGE_APPROVAL"}
    values = copy.deepcopy(native); values.update(subject_digest=typed(assessment["assessment"]["subject_digest"]), assessment_digest=typed(digest("content-assessment", assessment["assessment"])),
        review_digest=typed(digest("content-assessment-review", assessment["review"])), review_identity=typed(canonical_bytes({**coordinates, "provider_record_id": assessment["review"]["id"]}).decode()),
        effective_from=typed(signed, "INSTANT"), effective_until=typed(times["end"], "INSTANT"))
    witness = {"configuration": copy.deepcopy(config), "retained_registry_state": copy.deepcopy(signing_state), "state_digest": digest("holdings-state", signing_state), "signing_instant": signed, "policy": "Authenticate the retained registry and evaluate membership at signing; this is a provider historical assertion, not a nested current holdings query."}
    values["signing_holdings_witness"] = typed(canonical_bytes(witness).decode(), "STRING")
    work = {"schema": SCHEMA + "authority-work-class", "id": "bank-human-sar-package-review", "revision": "revision-2", "types": copy.deepcopy(TYPES), "steps": [projection(values, leaf=True)], "authority_profile": "EVIDENCE_ONLY"}
    eligible = any(row["actor"] == "sar-review-officer-01" and row["permission"] == "SAR_APPROVE" and row["valid_from"] <= signed and (row["valid_until"] is None or signed < row["valid_until"]) and (row["revoked_at"] is None or signed < row["revoked_at"]) for row in signing_state["core"]["grants"])
    permission_values = {"actor": typed("sar-review-officer-01"), "permission": typed("SAR_APPROVE"), "signing_at": typed(signed, "INSTANT"), "state_digest": typed(witness["state_digest"]), "eligible": typed(eligible, "BOOLEAN")}
    selected = requirement("signing-time-sar-approve", step=work["steps"][0]["id"], purpose="AUTHORITY", provider="bank-historical-holdings-provider.invalid", source="bank-signing-permission-witnesses", record_type="HISTORICAL_SIGNING_PERMISSION", subject={"kind": "PROPOSAL_FIELD", "field": "package_id"}, record_id="MRB-SIGNING-REMIT-074-01", expected_status="AVAILABLE", fields=[{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in fields(permission_values)], relations=[{"id": name, "kind": "EQUALS", "left": {"kind": "OBSERVATION_FIELD", "requirement_id": "signing-time-sar-approve", "field": name}, "right": {"kind": "LITERAL", "value": typed(True, "BOOLEAN") if name == "eligible" else copy.deepcopy(value)}} for name, value in sorted(permission_values.items())])
    supplied = bank_base(work, values, role="sar-review-officer", actor="sar-review-officer-01", leaf=True, issue=assessment["review"]["id"], signer_until=times["signer_until"], source_requirements=[selected], source_values={selected["id"]: permission_values})
    result = expected_authority(supplied, leaf=True)
    return {"schema": SCHEMA + "human-decision-evidence", "authority_input": supplied, "decision_act_digest": result["decision_act_digest"]}, coordinates


def complete_expected(supplied):
    result = expected_authority(supplied)
    for req in supplied["envelope"].get("holdings_requirements", []):
        actor = supplied["proposal"]["executor"]["actor"] if req["actor"] == "EXECUTOR" else "sar-review-officer-01"
        result["checks"].append(holdings.holdings_check(req, actor, supplied["clock"]["instant"]))
    for req in supplied["envelope"].get("flow_requirements", []):
        selected = supplied["flow_bases"][0]; sender = next(row for row in selected["state"]["core"]["contexts"] if row["id"] == req["context_id"]); artifact = next(row for row in selected["state"]["core"]["artifacts"] if row["id"] == req["artifact_id"])
        result["checks"].append(flow.flow_check(req, sender, artifact, recipient="MRB-GOVERNED-FILING-GATEWAY", at=supplied["clock"]["instant"]))
    result["checks"] = flow.ordered(result["checks"]); result["evidence_digest"] = digest("authority-evidence", flow.authority_evidence(supplied))
    return result


def current_requirements(native, assessment, human, context_coordinates, context_values, flow_requirement, *, prior_filing=None):
    step = projection(native)["id"]; amended = native["filing_type"]["value"] == "CORRECT_AMEND"
    rows, selected_values = [], {}
    def obs(req_id, field): return {"kind": "OBSERVATION_FIELD", "requirement_id": req_id, "field": field}
    def eq(req_id, field, right): return {"id": field, "kind": "EQUALS", "left": obs(req_id, field), "right": right}
    def literal(value): return {"kind": "LITERAL", "value": value}
    def add(req_id, values, *, coordinates=None, record_id="AUTO", status="AVAILABLE", relations=()):
        coordinates = coordinates or {"provider": "bank-governance-provider.invalid", "source": "bank-" + req_id, "record_type": "BANK_GOVERNANCE_RECORD"}
        selected = requirement(req_id, step=step, purpose="AUTHORITY", **coordinates, subject={"kind": "PROPOSAL_FIELD", "field": "package_id"},
            record_id=(req_id + ("-amendment-record" if amended else "-record") if record_id == "AUTO" else record_id) if status == "AVAILABLE" else None,
            expected_status=status, fields=[{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in fields(values)], relations=sorted(relations, key=lambda row: row["id"]))
        rows.append(selected); selected_values[req_id] = copy.deepcopy(values)
    add("current-package-content", native, relations=[eq("current-package-content", name, {"kind": "PROPOSAL_FIELD", "field": name}) for name in sorted(native)])
    add("bank-investigation-context", context_values, coordinates=context_coordinates, record_id="MRB-CONTEXT-074-AMEND-01" if amended else "MRB-CONTEXT-074", relations=[eq("bank-investigation-context", "native_correspondence_digest", {"kind": "PROPOSAL_FIELD", "field": "native_correspondence_digest"})])
    add("current-assessment-context", {"context_digest": typed(assessment["assessment"]["context_digest"])})
    add("current-narrative-rules", {"rubric_digest": typed(assessment["assessment"]["rubric_digest"])})
    add("current-evaluator", {name: typed(value) for name, value in EVALUATOR.items()})
    assess_digest = digest("content-assessment", assessment["assessment"])
    assess_coordinates = {key: assessment["assessment"][key] for key in ["provider", "source", "record_type"]}
    assess_identity = canonical_bytes({**assess_coordinates, "provider_record_id": assessment["assessment"]["id"]}).decode()
    derived = {"kind": "DECISION_FIELD", "requirement_id": DECISION, "field": "assessment_digest"}
    add("immutable-sar-assessment", {"assessment_digest": typed(assess_digest)}, coordinates=assess_coordinates, record_id=assessment["assessment"]["id"], relations=[eq("immutable-sar-assessment", "assessment_digest", derived)])
    add("current-assessment-selection", {"assessment_digest": typed(assess_digest), "assessment_identity": typed(assess_identity)}, relations=[eq("current-assessment-selection", "assessment_digest", derived)])
    add("assessment-effectiveness", {"assessment_identity": typed(assess_identity), "effective": typed(True, "BOOLEAN")})
    leaf = human["authority_input"]; decision_act = next(row for row in leaf["acts"] if row["kind"] == "INSTANCE_DECISION")
    approval_values = {row["name"]: copy.deepcopy(row["value"]) for row in leaf["proposal"]["fields"]}
    approval_relations = [{"id": "issue-id", "kind": "EQUALS", "left": {"kind": "OBSERVATION_ID", "requirement_id": APPROVAL, "type_ref": "IDENTITY"}, "right": {"kind": "DECISION_ACT", "requirement_id": DECISION, "member": "id", "type_ref": "IDENTITY"}}]
    for member in ["digest", "actor", "role", "principal", "occurred_at"]:
        name = "act-" + member; approval_values[name] = typed(human["decision_act_digest"] if member == "digest" else decision_act[member], "INSTANT" if member == "occurred_at" else "IDENTITY")
        approval_relations.append(eq(APPROVAL, name, {"kind": "DECISION_ACT", "requirement_id": DECISION, "member": member, "type_ref": approval_values[name]["type_ref"]}))
    for name in sorted(row["name"] for row in leaf["proposal"]["fields"]): approval_relations.append(eq(APPROVAL, name, {"kind": "DECISION_FIELD", "requirement_id": DECISION, "field": name}))
    add(APPROVAL, approval_values, coordinates={"provider": "bank-human-review-provider.invalid", "source": "bank-sar-approvals", "record_type": "SAR_PACKAGE_APPROVAL"}, record_id=None, relations=approval_relations)
    add("sar-approval-withdrawal", {}, status="ABSENT")
    if amended:
        if prior_filing is None: raise ValueError("Amendment requires the complete retained prior native filing record")
        prior_values = {row["name"]: row["value"] for row in prior_filing["actual_fields"]}
        add("prior-initial-filing", {"bsa_identifier": prior_values["bsa_identifier"], "status": prior_values["status"], "package_id": prior_values["package_id"], "submission_token": prior_values["submission_token"], "native_submission_id": prior_values["native_submission_id"], "record_digest": typed(prior_filing["record_digest"]), "full_native_record": typed(canonical_bytes(prior_filing).decode(), "STRING")}, coordinates={key: prior_filing[key] for key in ["provider", "source", "record_type"]}, record_id=prior_filing["provider_record_id"], relations=[eq("prior-initial-filing", "bsa_identifier", {"kind": "PROPOSAL_FIELD", "field": "prior_bsa_identifier"}), eq("prior-initial-filing", "status", literal(typed("ACCEPTED_FILING", "STRING"))), eq("prior-initial-filing", "record_digest", literal(typed(prior_filing["record_digest"])))])
    else: add("prior-initial-filing", {}, status="ABSENT")
    reporting_decision = "FILE_CORRECTED_AMENDED_SAR" if amended else "FILE_INITIAL_SAR"
    add("current-reporting-decision", {"decision": typed(reporting_decision), "bank_id": native["bank_id"], "case_id": native["case_id"], "effective": typed(True, "BOOLEAN")}, relations=[
        eq("current-reporting-decision", "decision", literal(typed(reporting_decision))), eq("current-reporting-decision", "effective", literal(typed(True, "BOOLEAN"))),
        *[eq("current-reporting-decision", name, {"kind": "PROPOSAL_FIELD", "field": name}) for name in ["bank_id", "case_id"]]])
    add("current-reviewer-remit", {"basis_digest": typed(reliance_subject(human)), "no_applicable_revocation": typed(True, "BOOLEAN")}, relations=[eq("current-reviewer-remit", "basis_digest", {"kind": "DECISION_BASIS", "requirement_id": DECISION, "type_ref": "IDENTITY"}), eq("current-reviewer-remit", "no_applicable_revocation", literal(typed(True, "BOOLEAN")))])
    add("bank-filing-coordinator", {"complete_writer_coverage": typed(True, "BOOLEAN")}, relations=[eq("bank-filing-coordinator", "complete_writer_coverage", literal(typed(True, "BOOLEAN")))])
    add("current-flow-policy", {"policy_digest": typed(digest("flow-policy", flow_requirement["policy"]))})
    add("current-filing-recipient", {"recipient": native["recipient"], "channel": typed(flow_requirement["channel"]), "purpose": typed(flow_requirement["purpose"]), "effective": typed(True, "BOOLEAN")})
    members = {"subject_digest": "SUBJECT_DIGEST", "assessment_digest": "ASSESSMENT_DIGEST", "review_digest": "REVIEW_DIGEST", "review_identity": "REVIEW_IDENTITY"}
    bindings = [{"field": row["name"], "value": {"kind": "ASSESSMENT", "requirement_id": ASSESSMENT, "member": members[row["name"]], "type_ref": "IDENTITY"} if row["name"] in members else {"kind": "PROPOSAL_FIELD", "field": row["name"]} if row["name"] in native else literal(copy.deepcopy(row["value"]))} for row in leaf["proposal"]["fields"]]
    decision = {"id": DECISION, "step": step, "principal": PRINCIPAL, "role": "sar-review-officer", "work_class_digest": digest("authority-work-class", leaf["work_class"]), "envelope_digest": digest("authority-envelope", leaf["envelope"]),
        "record_requirement_id": APPROVAL, "identity_field": "review_identity", "validity_fields": {"not_before_field": "effective_from", "not_after_field": "effective_until"}, "context_bindings": bindings, "distinct_from": [{"kind": "EXECUTOR"}]}
    declaration = {"id": ASSESSMENT, "step": step, "review_decision_requirement_id": DECISION, "rubric": rubric(), "evaluator": copy.deepcopy(EVALUATOR), "sources": {
        "content": "current-package-content", "context": ["bank-investigation-context"], "context_selection": {"requirement_id": "current-assessment-context", "digest_field": "context_digest"},
        "rubric": {"requirement_id": "current-narrative-rules", "digest_field": "rubric_digest"}, "evaluator": {"requirement_id": "current-evaluator", "provider_field": "provider", "model_field": "model", "version_field": "version"},
        "assessment": {"requirement_id": "immutable-sar-assessment", "digest_field": "assessment_digest"}, "selection": {"requirement_id": "current-assessment-selection", "identity_field": "assessment_identity", "digest_field": "assessment_digest"},
        "effectiveness": {"requirement_id": "assessment-effectiveness", "identity_field": "assessment_identity", "effective_field": "effective"}, "blockers": ["bank-filing-coordinator", "current-reporting-decision", "current-reviewer-remit", "prior-initial-filing", "sar-approval-withdrawal"]}}
    return sorted(rows, key=lambda row: row["id"]), selected_values, decision, declaration


def flow_history(native, *, prior_state=None):
    times = filing_times(native); amended = native["filing_type"]["value"] == "CORRECT_AMEND"
    prefix = "mrb-amendment" if amended else "mrb"
    scope = "bank-sar-filing-scope"
    config = flow.configuration(principal=PRINCIPAL, registry_id="MRB-PROTECTED-REPORTING", scope=scope, restriction_id="SAR_CONFIDENTIAL", meaning="Reporting decision, draft, approval, assessment, filing status and report existence remain in the protected reporting channel.")
    config["clock_source"] = "component-component-clock"
    requests, results = [], []
    def append(pair):
        supplied, selected = seal_flow_pair(pair, signed=times["signed"], until=times["end"])
        requests.append(supplied); results.append(selected)
        return selected["state"]
    state = append(flow.create(config, prior_state, context_id=prefix + "-preparation-context", actor="sar-preparation-agent-01", scope=scope, purpose="SAR_REPORTING", ceiling=["SAR_CONFIDENTIAL"], at=times["now"]))
    content = {"native": native, "supporting_records": supporting_records()[0], "reporting_decision": "MRB-DECISION-074-AMEND-01/revision-1" if amended else "MRB-DECISION-074/revision-1"}
    descriptor = flow.source_descriptor(provider="bank-package-provider.invalid", source="bank-protected-reporting", record_type="SAR_PREPARATION_INPUT", record_id=native["package_id"]["value"], revision="revision-1", content_digest="sha256:" + hashlib.sha256(canonical_bytes(content)).hexdigest(), scope=scope, restrictions=["SAR_CONFIDENTIAL"])
    state = append(flow.read(config, state, descriptor, context_id=prefix + "-preparation-context", role="sar-preparation-agent", event_id="read-" + prefix + "-protected-case", at=times["now"]))
    state = append(flow.materialize(config, state, context_id=prefix + "-preparation-context", artifact_id=prefix + "-reviewed-draft", types=TYPES, native_fields=fields(native), at=times["now"]))
    state = append(flow.create(config, state, context_id=prefix + "-submission-context", actor="sar-submission-agent-01", scope=scope, purpose="SAR_REPORTING", ceiling=["SAR_CONFIDENTIAL"], at=times["now"]))
    state = append(flow.import_artifact(config, state, sender_id=prefix + "-preparation-context", receiver_id=prefix + "-submission-context", artifact_id=prefix + "-reviewed-draft", event_id="import-" + prefix + "-exact-draft", receiver_role="sar-submission-agent", sender_role="sar-preparation-agent", at=times["now"]))
    state = append(flow.materialize(config, state, context_id=prefix + "-submission-context", artifact_id=prefix + "-filing-payload", types=TYPES, native_fields=fields(native), at=times["now"]))
    return config, state, requests, results, {"descriptor": descriptor, "content": content}


def seal_control_authority(supplied, *, signed=SIGNED, until=END):
    supplied["envelope"]["temporal_validity"] = {"valid_from": "2026-10-06T14:00:00Z", "valid_until": until}
    for act in supplied["acts"]: act["occurred_at"] = signed
    for returned in supplied["returns"]: returned["returned_at"] = signed
    rebind_outer(supplied)
    grant = next(row for row in supplied["acts"] if row["kind"] == "GRANT")
    for act in supplied["acts"]:
        if act["kind"] == "ORGANISATIONAL_ATTESTATION": act["subject_digest"] = digest("authority-act", grant)
    rebind_outer(supplied); flow.refresh_revocations(supplied)
    return supplied


def seal_flow_pair(pair, *, signed=SIGNED, until=END):
    supplied, selected = copy.deepcopy(pair)
    authorities = []
    for name in ["access_authority", "transfer_authority"]:
        if name in supplied["event"]["payload"]:
            proof = seal_control_authority(supplied["event"]["payload"][name], signed=signed, until=until); authorities.append(expected_authority(proof))
    supplied["host_evidence"] = flow.host_evidence(supplied["configuration"], supplied["event"])
    flow.refresh_response(supplied); seal_control_authority(supplied["response_authority"], signed=signed, until=until)
    if supplied["event"]["kind"] == "EXPOSE":
        authorities = [complete_expected(flow.expanded_projection(supplied["event"]["payload"]["authority_projection"], supplied["state"]))]
    core = selected["state"]["core"]
    result = flow.transition(supplied, selected["receipt"]["decision"], contexts=core["contexts"], artifacts=core["artifacts"], claims=core["claims"], consumed_release_acts=core["consumed_release_acts"], authority_results=authorities)
    return supplied, result


def authority(config, holdings_state, *, instance="bank-filing-instance-074", occurrence="bank-filing-occurrence-074", signing_state=None, amended=False, prior_flow_state=None, prior_filing=None):
    native = native_values(amended=amended); times = filing_times(native); prefix = "mrb-amendment" if amended else "mrb"
    flow_config, flow_state, flow_requests, flow_results, flow_source = flow_history(native, prior_state=prior_flow_state)
    operation = projection(native); operation["authority_type_refs"] = sorted(row["id"] for row in TYPES); operation["completion"] = completion_carrier(native)
    step = operation["id"]
    source_ids = sorted(["current-package-content", "bank-investigation-context", "current-assessment-context", "current-narrative-rules", "current-evaluator", "immutable-sar-assessment", "current-assessment-selection", "assessment-effectiveness", APPROVAL, "sar-approval-withdrawal", "prior-initial-filing", "current-reporting-decision", "current-reviewer-remit", "bank-filing-coordinator", "current-flow-policy", "current-filing-recipient"])
    operation["dispatch_gate"] = {"kind": "SOURCE_REQUIREMENTS", "requirements": source_ids, "coordinator_requirement": "bank-filing-coordinator", "fence_provider": "bank-governance-provider.invalid", "fence_source": "bank-bank-filing-coordinator", "authorization_seconds": "60", "validity_requirements": [{"requirement_id": APPROVAL, "not_before_field": "effective_from", "not_after_field": "effective_until"}]}
    work = {"schema": SCHEMA + "authority-work-class", "id": "bank-sar-amendment" if amended else "bank-sar-filing", "revision": "revision-2", "types": copy.deepcopy(TYPES), "steps": [operation]}
    proposal = {"executor": {"principal": PRINCIPAL}, "work_class_digest": digest("authority-work-class", work), "instance": instance, "occurrence": occurrence, "step": step, "interface": operation["interface"], "operation": step, "fields": fields(native)}
    assessment, context_coordinates, context_values = assessment_body(work, proposal); human, _ = human_leaf(native, assessment, config, signing_state or holdings_state)
    policy = {"id": "MRB-SAR-DISCLOSURE", "revision": "revision-1", "configuration_digest": digest("flow-configuration", flow_config), "entitlements": [{"restriction_id": "SAR_CONFIDENTIAL", "scope": "bank-sar-filing-scope", "recipient": "MRB-GOVERNED-FILING-GATEWAY", "channel": "bank-protected-filing-custody", "purpose": "SAR_REPORTING"}], "release_rules": []}
    flow_requirement = {"id": "exact-sar-filing-disclosure", "step": step, "configuration_digest": policy["configuration_digest"], "context_id": prefix + "-submission-context", "artifact_id": prefix + "-filing-payload", "intent_id": native["submission_token"]["value"], "claim_id": prefix + "-filing-exposure-074-01", "recipient_field": "recipient", "channel": "bank-protected-filing-custody", "purpose": "SAR_REPORTING", "policy": policy, "release_decision_requirement_id": None, "sources": {
        "policy": {"requirement_id": "current-flow-policy", "digest_field": "policy_digest"}, "recipient": {"requirement_id": "current-filing-recipient", "recipient_field": "recipient", "channel_field": "channel", "purpose_field": "purpose", "effective_field": "effective"}, "release_selection": None, "release_effectiveness": None, "blockers": []}}
    requirements, values, decision, declaration = current_requirements(native, assessment, human, context_coordinates, context_values, flow_requirement, prior_filing=prior_filing)
    supplied = bank_base(work, native, role="sar-submission-agent", actor="sar-submission-agent-01", gate_requirement=DECISION, decision_requirements=[decision], source_requirements=requirements, source_values=values, decision_bases=[{"requirement_id": DECISION, "evidence": human}], instance=instance, occurrence=occurrence)
    supplied["envelope"]["scope"]["id"] = "bank-sar-filing-scope"
    supplied["envelope"]["assessment_requirements"] = [declaration]; supplied["assessment_bases"] = [assessment]
    supplied["envelope"]["holdings_requirements"] = [holdings.requirement(config, requirement_id="current-sar-reviewer-approve", actor="GATE_ACTOR", permission="SAR_APPROVE", step=step), holdings.requirement(config, requirement_id="current-sar-submitter-submit", permission="SAR_SUBMIT", step=step)]
    supplied["holdings_bases"] = [holdings.basis(config, holdings_state, times["now"])]; supplied["envelope"]["flow_requirements"] = [flow_requirement]
    supplied["flow_bases"] = [flow.basis(flow_config, flow_state, requirement_id=flow_requirement["id"], at=times["now"])]
    rebind_outer(supplied); flow.refresh_revocations(supplied)
    for row in supplied["observations"]:
        req_id = row["query"].get("requirement_id")
        if req_id in ["bank-investigation-context", "immutable-sar-assessment"]: row["revision"] = "revision-1"
        if req_id == APPROVAL: row["provider_record_id"] = assessment["review"]["id"]
    supplied["observations"].sort(key=lambda row: digest("authority-observation", row))
    return supplied, complete_expected(supplied), {"native": native, "flow_configuration": flow_config, "flow_state": flow_state, "flow_requests": flow_requests, "flow_results": flow_results, "flow_source": flow_source, "source_values": values}


def completion_carrier(native):
    return {"terminal_policy": "STOP_RETAIN", "effect_provider": "bank-synthetic-filing-provider.invalid", "effect_source": "bank-controlled-filing-receipts", "effect_record_type": "ACCEPTED_SAR_FILING",
        "no_effect_provider": "bank-synthetic-filing-provider.invalid", "no_effect_source": "bank-controlled-filing-receipts", "no_effect_record_type": "QUALIFIED_NO_FILING",
        "status_field": "status", "status_type_ref": "STRING", "success_values": [typed("ACCEPTED_FILING", "STRING")], "failure_values": [], "route_label_field": None, "route_label_type_ref": None,
        "evidence_bindings": [{"request_field": name, "evidence_field": name} for name in sorted(native)],
        "provider_record_identity": {"field": "provider_event_id", "type_ref": "IDENTITY"}, "event_time_identity": {"field": "provider_event_time", "type_ref": "INSTANT"},
        "additional_fields": [{"name": "processing_stage", "value": typed("REPORT_DISPOSITION", "STRING")}],
        "generated_fields": [{"name": name, "type_ref": kind} for name, kind in [("bsa_identifier", "IDENTITY"), ("native_submission_id", "IDENTITY"), ("provider_disposition", "STRING"), ("warning_error_inventory", "STRING")]],
        "lookup": {"provider": "bank-synthetic-filing-provider.invalid", "source": "bank-controlled-filing-receipts", "record_type": "ACCEPTED_SAR_FILING", "namespace": "synthetic-bank-filing-acceptance", "key_projection": [{"field": "submission_token", "type_ref": "IDENTITY"}]}}


def lifecycle_base(config, holdings_state, *, instance="bank-filing-instance-074", amended=False, prior_flow_state=None, prior_filing=None):
    supplied, result, facts = authority(config, holdings_state, instance=instance, amended=amended, prior_flow_state=prior_flow_state, prior_filing=prior_filing)
    step = supplied["work_class"]["steps"][0]["id"]; times = filing_times(facts["native"])
    operation = {**copy.deepcopy(supplied["work_class"]["steps"][0]), "kind": "OPERATION", "authority_requirements": [supplied["envelope"]["id"]], "shared_budgets": [], "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": "300", "failure_behavior": "STOP", "referral_policy": {"authority": [], "completion": []}}
    definition = {"schema": SCHEMA + "work-class-definition", "specification_pin": PIN, "id": supplied["work_class"]["id"], "revision": "revision-2", "profile": "LINEAR", "root": step,
        "participants": [{"id": "sar-submission-agent-01", "role": "sar-submission-agent", "kind": "AGENT"}], "objects": [], "types": copy.deepcopy(TYPES), "steps": [operation, structural_step("terminal", "TERMINAL")],
        "relationships": [{"kind": "SEQUENCE", "from": step, "to": "terminal"}], "choices": [], "occurrence_limits": [{"step_id": step, "maximum": "1"}], "loops": [], "deadlines": [], "parallel_blocks": [], "fanouts": [], "shared_budgets": [],
        "limits": {"maximum_proposals": "64", "maximum_activations": "64", "maximum_actuations": "1", "maximum_active_obligations": "64", "maximum_fanout_objects": "64"},
        "source": {"id": SOURCE_ID, "revision": "revision-2", "obligations": sorted(row["id"] for row in source()["obligations"])}}
    definition_digest = digest("work-class-definition", definition); root_occurrence = occurrence_record(definition_digest, instance, step)
    supplied, result, facts = authority(config, holdings_state, instance=instance, occurrence=root_occurrence["occurrence_id"], amended=amended, prior_flow_state=prior_flow_state, prior_filing=prior_filing)
    # These mechanical deployment mappings establish exact evidence bindings only.
    # BANK-SOURCE-COVERAGE records substantive correspondence and visible gaps.
    paths, obligations = readback_paths(definition), definition["source"]["obligations"]
    mappings = [{"source_obligation_id": value, "provision_paths": paths[i::len(obligations)]} for i, value in enumerate(obligations)]
    deploy_input, deploy_result = deployment(definition, instance_id=instance, organization_id=PRINCIPAL, authorization_time=times["assessed"], evidence_expires_at=times["end"], correspondence_mappings=mappings)
    clock = available_clock(supplied["clock"]["source"], "1", times["now"])
    event = {"schema": SCHEMA + "runtime-event", "kind": "CLOCK", "event_id": "bank-clock-1", "instance_id": instance, "expected_state_revision": deploy_result["state"]["revision"], "expected_state_digest": deploy_result["state_digest"], "clock": clock, "activation_clocks": []}
    def record_clock(state): state["clocks"].append(copy.deepcopy(clock))
    clock_result = admitted_transition(deploy_result["state"], event, disposition="CLOCK_RECORDED", reason_codes=[], details=[{"kind": "CLOCK", "source": clock["source"], "revision": "1", "status": "AVAILABLE"}], mutate=record_clock)
    executor = supplied["proposal"]["executor"]
    proposal = {"schema": SCHEMA + "runtime-event", "kind": "PROPOSE", "event_id": "bank-propose-1", "instance_id": instance, "expected_state_revision": clock_result["state"]["revision"], "expected_state_digest": clock_result["state_digest"], "occurrence": root_occurrence,
        "native_request": {key: copy.deepcopy(supplied["proposal"][key]) for key in ["interface", "operation", "fields"]}, "executor": {"participant_id": executor["actor"], "role": executor["role"], "binding_digest": digest("executor-binding", executor)},
        "credential_ids": sorted(row["id"] for row in supplied["credentials"]), "authority_input": supplied, "budget_inputs": [], "clock_revision": "1", "observation_digests": sorted(digest("authority-observation", row) for row in supplied["observations"])}
    return {"definition": definition, "definition_digest": definition_digest, "deploy_input": deploy_input, "deploy_result": deploy_result, "clock_event": event, "clock_result": clock_result,
        "authority_input": supplied, "authority_result": result, "proposal_event": proposal, "native": facts["native"], "source_values": facts["source_values"], "permit_expires_at": "2026-10-06T15:25:00Z" if amended else "2026-10-06T15:15:00Z", "facts": facts}


def permitted(base):
    return permitted_proposal(base)


def authorized(base, prior):
    times = filing_times(base["native"]); now = times["now"]
    current = copy.deepcopy(base["authority_input"]); current["evaluation_point"] = "DISPATCH"
    result = complete_expected(current); body = {"id": "bank-synthetic-filing-connector", "version": "revision-1"}
    connector = {**body, "binding_digest": digest("connector-binding", body)}
    event = {"schema": SCHEMA + "runtime-event", "kind": "AUTHORIZE_DISPATCH", "event_id": "bank-authorize-1", "instance_id": prior["state"]["instance_id"], "expected_state_revision": prior["state"]["revision"], "expected_state_digest": prior["state_digest"], "permit": copy.deepcopy(prior["permit"]),
        "native_request": copy.deepcopy(prior["permit"]["native_request"]), "connector": connector, "authorization_fence": None, "authority_input": current, "dispatch_intent_id": base["native"]["submission_token"]["value"], "observation_digests": sorted(digest("authority-observation", row) for row in current["observations"]), "clock_revision": "1"}
    fence, expires = flow.flow_fence(event, result)
    holding_rows = []
    selected = current["holdings_bases"][0]
    for req in current["envelope"]["holdings_requirements"]:
        actor = current["proposal"]["executor"]["actor"] if req["actor"] == "EXECUTOR" else "sar-review-officer-01"
        grant = next(row for row in selected["state"]["core"]["grants"] if row["actor"] == actor and row["permission"] == req["permission"] and row["revoked_at"] is None)
        holding_rows.append({"requirement_id": req["id"], "configuration_digest": req["configuration_digest"], "state_digest": selected["state_digest"], "revision": selected["state"]["core"]["revision"], "actor": actor, "permission": req["permission"], "grant_id": grant["id"], "valid_until": grant["valid_until"]})
    fence["holdings"] = holding_rows
    scope = {"instance_id": event["instance_id"], "occurrence_id": event["permit"]["occurrence"]["occurrence_id"], "permit_digest": event["permit"]["permit_id"], "native_request": event["native_request"], "connector": connector, "dispatch_intent_id": event["dispatch_intent_id"], "checked_at": now, "expires_at": expires, "authority_result_digest": digest("authority-result", result), "sources": fence["sources"], "holdings": holding_rows, "flows": fence["flows"]}
    fence["scope_digest"] = digest("dispatch-authorization-scope", scope); event["authorization_fence"] = fence
    record_body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": event["permit"]["permit_id"], "native_request": event["native_request"], "connector": connector, "authorization_fence": fence, "observation_digests": event["observation_digests"], "clock_revision": "1", "dispatch_intent_id": event["dispatch_intent_id"], "authority_input": current, "authority_result": result, "authority_result_digest": digest("authority-result", result), "expires_at": expires, "supersedes_authorization_digest": None}
    record = {"authorization_digest": digest("dispatch-authorization", record_body), **record_body}
    evaluation_body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": event["permit"]["permit_id"], "dispatch_intent_id": event["dispatch_intent_id"], "clock_revision": "1", "authority_input": current, "authority_result": result, "authority_result_digest": digest("authority-result", result), "authorization_digest": record["authorization_digest"], "disposition": "AUTHORIZED"}
    evaluation = {"evaluation_digest": digest("dispatch-authorization-evaluation", evaluation_body), **evaluation_body}
    def mutate(state): state["authorizations"].append(record); state["authorization_evaluations"].append(evaluation)
    output = admitted_transition(prior["state"], event, disposition="AUTHORIZED", reason_codes=[], details=[{"kind": "AUTHORIZATION", "authorization_digest": record["authorization_digest"], "permit_digest": event["permit"]["permit_id"], "gate_kind": "SOURCE_REQUIREMENTS", "checked_at": now, "expires_at": expires, "sources": fence["sources"], "holdings": holding_rows, "flows": fence["flows"]}], receipt_permit_digest=event["permit"]["permit_id"], receipt_authority_result_digest=digest("authority-result", result), receipt_authorization_evaluation_digest=evaluation["evaluation_digest"], mutate=mutate)
    exposure_id = "bank-first-amendment-exposure" if base["native"]["filing_type"]["value"] == "CORRECT_AMEND" else "bank-first-filing-exposure"
    exposure = seal_flow_pair(flow.expose(base["facts"]["flow_configuration"], base["facts"]["flow_state"], current, result, event_id=exposure_id), signed=times["signed"], until=times["end"])
    return event, retained(output, prior["permit"]), exposure


def dispatched(base, prior):
    authorization = prior["state"]["authorizations"][-1]
    event = dispatch_event(base, prior, event_id="bank-dispatch-1", attempt_status="SENT", acknowledgement_status="NONE", attempted_at=filing_times(base["native"])["now"], clock_revision="1", authorization_digest=authorization["authorization_digest"])
    event["connector"] = copy.deepcopy(authorization["connector"])
    return event, retained(dispatch_result(prior, event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED"), prior["permit"])


def provider_receipt(base, prior, *, warnings=()):
    amended = base["native"]["filing_type"]["value"] == "CORRECT_AMEND"
    return {"provider": "bank-synthetic-filing-provider.invalid", "native_submission_id": "MRB-NATIVE-SUBMISSION-074-AMEND-01" if amended else "MRB-NATIVE-SUBMISSION-074-01", "submission_token": base["native"]["submission_token"]["value"], "processing_stage": "REPORT_DISPOSITION", "disposition": "ACCEPTED_WITH_WARNINGS" if warnings else "ACCEPTED", "bsa_identifier": "31000000000002" if amended else "31000000000001", "warnings_errors": copy.deepcopy(list(warnings))}


def completed(base, prior, *, warnings=()):
    now = filing_times(base["native"])["now"]; amended = base["native"]["filing_type"]["value"] == "CORRECT_AMEND"
    provider_id = "MRB-FILING-RECEIPT-074-AMEND-01" if amended else "MRB-FILING-RECEIPT-074-01"
    receipt = provider_receipt(base, prior, warnings=warnings)
    values = {"provider_event_id": typed(provider_id), "provider_event_time": typed(now, "INSTANT"), "status": typed("ACCEPTED_FILING", "STRING"), "processing_stage": typed(receipt["processing_stage"], "STRING"), "bsa_identifier": typed(receipt["bsa_identifier"]), "native_submission_id": typed(receipt["native_submission_id"]), "provider_disposition": typed(receipt["disposition"], "STRING"), "warning_error_inventory": typed(canonical_bytes(receipt["warnings_errors"]).decode(), "STRING")}
    actual = sorted(copy.deepcopy(prior["permit"]["native_request"]["fields"]) + fields(values), key=lambda row: row["name"])
    native = governed_native_evidence(base, prior, prior, evidence_id="bank-accepted-filing-evidence-1", result_value="ACCEPTED_FILING", native_operation_id=receipt["native_submission_id"], event_time=now, observed_at=now, actual_fields=actual)
    native.update(provider="bank-synthetic-filing-provider.invalid", source="bank-controlled-filing-receipts", record_type="ACCEPTED_SAR_FILING", provider_record_id=provider_id, provider_revision="revision-1")
    native["record_digest"] = digest("provider-native-record", {key: native[key] for key in ["provider", "source", "record_type", "provider_record_id", "provider_revision", "actual_fields", "event_time"]})
    event = governed_effect_event(prior, prior, native, event_id="bank-accepted-filing-1", clock_revision=None)
    output = terminal_effect_result(base, prior, event, classification="MATCHED", disposition="COMPLETED", reason_codes=[], occurrence_status=None, disputed=False, complete_disposition="SUCCEEDED", route=True)
    return event, retained(output, prior["permit"])


def receipt_sidecar(base, prior, event, *, warnings=()):
    receipt = provider_receipt(base, prior, warnings=warnings)
    return {"profile": "FICTIONAL_CONTROLLED_PROVIDER_RECEIPT", "recipient": "MRB-GOVERNED-FILING-GATEWAY", "terminal_synthetic_sink": True, "onward_invocations": "0",
        "raw_receipt_utf8": canonical_bytes(receipt).decode(), "normalized_receipt": receipt,
        "native_record_identity": {key: copy.deepcopy(event["native_evidence"][key]) for key in ["provider", "source", "record_type", "provider_record_id", "provider_revision", "record_digest"]},
        "native_operation_id": event["native_evidence"]["native_operation_id"], "permit_digest": prior["permit"]["permit_id"], "dispatch_digest": event["dispatch_digest"],
        "request": copy.deepcopy(prior["permit"]["native_request"]), "normalized_disposition": "ACCEPTED_FILING", "correction_duty_required": bool(warnings),
        "protected_reader_requirement": "Current independently authenticated reporting-reader authority; this file is protected specimen evidence.",
        "portable_boundary": "STOP_RETAIN matches the declared request, generated receipt identity/time, status and fixed stage, and requires exact nominal types and valid scalars for generated BSA/native identity/disposition/warnings fields. It does not qualify a real acknowledgement, validate this sidecar or create the correction duty."}


def public_result(value):
    result = copy.deepcopy(value)
    if result.get("status") == "STEP" and result["decision"]["event_kind"] != "PROPOSE": result["permit"] = None
    return result
