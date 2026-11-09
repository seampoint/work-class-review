"""Independent source-derived equipment correction evidence constructors."""

from __future__ import annotations

import base64
import copy
from pathlib import Path
import runpy

from authority_fixture import canonical_sort
from corpus_common import ROOT, canonical_bytes, digest
from fixture_factory import PIN, available_clock, deployment, occurrence, structural_step, typed
from lifecycle_factory import state_digest


SCHEMA = "seampoint.work-class/1.0.0-draft.3/"
PRINCIPAL = "NPO-7"
ORIGINAL_AT = "2026-09-12T14:30:00Z"
CORRECTION_AT = "2026-09-12T15:00:00Z"
IDENTITY_PROVIDER = "workforce-identity-and-access-service"
ISSUER_ROLE = "reliability-supervisor"
CUSTODIAN_ROLE = "maintenance-records-custodian"
SOURCE_PATH = Path(__file__).with_name("fixtures") / "equipment-return-to-service-revision3-source.txt"
SUPPLIER = runpy.run_path(str(ROOT / "conformance/work-class/1.0.0-draft.3/specimens/supplier-payment/build-specimen.py"))


def original_identity(record):
    return {name: record[name] for name in ("provider", "source", "record_type", "provider_record_id")}


def identity_text(record):
    return canonical_bytes(original_identity(record)).decode("utf-8")


def correction_policy():
    return {"custodian_role": CUSTODIAN_ROLE, "issuer_role": ISSUER_ROLE,
        "correction_provider": "maintenance-register", "correction_source": "correction-events",
        "correction_record_type": "source-correction", "custodian_identity_source": "active-role-assignment",
        "original_id_field": "original_record_identity", "original_digest_field": "original_record_digest",
        "original_revision_field": "original_revision", "changes_digest_field": "changes_digest",
        "result_digest_field": "corrected_result_digest", "business_result_fields": [
            "approval", "asset", "effective_time", "inspection", "resulting_status", "work_order"],
        "provider_link_bindings": [{"field": "approval_register_link", "provider": "maintenance-register",
            "source": "approval-register", "record_type": "approval", "record_id_field": "approval"}]}


def equipment_native_fields():
    return [{"name": name, "value": typed(type_ref, value)} for name, type_ref, value in (
        ("approval", "APPROVAL_ID", "AP-091"), ("asset", "ASSET_ID", "EQ-204"),
        ("effective_time", "INSTANT", ORIGINAL_AT), ("inspection", "INSPECTION_ID", "IN-552"),
        ("performer_role", "ROLE_ID", "maintenance-records-clerk"),
        ("reason", "REASON", "RTS-AUTH-INSPECTED"), ("work_order", "WORK_ORDER_ID", "WO-7304"))]


def equipment_types():
    kinds = {"APPROVAL_ID": "IDENTITY", "ASSET_ID": "IDENTITY", "EVENT_ID": "IDENTITY",
        "INSTANT": "INSTANT", "INSPECTION_ID": "IDENTITY",
        "PROVIDER_LINK": "IDENTITY", "REASON": "STRING", "ROLE_ID": "IDENTITY",
        "STATUS": "STRING", "WORK_ORDER_ID": "IDENTITY"}
    return [{"id": name, "kind": kinds[name], "nonnegative": False, "unit": None} for name in sorted(kinds)]


def equipment_completion_carrier():
    link = typed("PROVIDER_LINK", canonical_bytes({"provider": "maintenance-register", "source": "approval-register",
        "record_type": "approval", "provider_record_id": "AP-091"}).decode("utf-8"))
    return {"effect_provider": "maintenance-register", "effect_source": "return-to-service-events",
        "effect_record_type": "return-to-service-event", "no_effect_provider": "maintenance-register",
        "no_effect_source": "return-to-service-events", "no_effect_record_type": "return-to-service-no-effect",
        "status_field": "resulting_status", "status_type_ref": "STATUS",
        "success_values": [typed("STATUS", "Return to Service")], "failure_values": [typed("STATUS", "Rejected")],
        "route_label_field": None, "route_label_type_ref": None,
        "evidence_bindings": [{"request_field": row["name"], "evidence_field": row["name"]} for row in equipment_native_fields()],
        "terminal_policy": "STOP_RETAIN", "provider_record_identity": {"field": "event_id", "type_ref": "EVENT_ID"},
        "event_time_identity": {"field": "event_timestamp", "type_ref": "INSTANT"},
        "additional_fields": [{"name": "approval_register_link", "value": link}],
        "lookup": {"provider": "maintenance-register", "source": "return-to-service-events",
            "record_type": "return-to-service-event", "namespace": "equipment-return-to-service",
            "key_projection": [{"field": name, "type_ref": next(row["value"]["type_ref"] for row in equipment_native_fields() if row["name"] == name)}
                for name in ("asset", "work_order", "inspection", "approval")]},
        "correction_policy": correction_policy()}


def _replace_strings(value, replacements):
    if isinstance(value, list):
        return [_replace_strings(row, replacements) for row in value]
    if isinstance(value, dict):
        return {key: _replace_strings(row, replacements) for key, row in value.items()}
    return replacements.get(value, value) if isinstance(value, str) else value


def rebind_authority(request):
    """Rebuild the fixed fixture's dependencies and successful check inventory."""
    request = copy.deepcopy(request)
    source, work, envelope, proposal = (request[name] for name in ("source", "work_class", "envelope", "proposal"))
    source_digest, work_digest = digest("authority-source", source), digest("authority-work-class", work)
    envelope.update(source_digest=source_digest, work_class_digest=work_digest)
    envelope_digest = digest("authority-envelope", envelope)
    proposal.update(work_class=work["id"], work_class_digest=work_digest)
    proposal_digest = digest("authority-proposal", proposal)
    operation_digest = digest("authority-operation", {"envelope_digest": envelope_digest,
        "work_class_digest": work_digest, "proposal_digest": proposal_digest})
    root = request["host_selection"]["root"]
    root.update(source_digest=source_digest, work_class_digest=work_digest, envelope_digest=envelope_digest)
    root_digest = digest("authority-root", root)
    for capacity in request["capacities"]:
        capacity.update(root_digest=root_digest, envelope_digest=envelope_digest)
    grant = next(row for row in request["acts"] if row["kind"] == "GRANT")
    gate = next(row for row in request["acts"] if row["kind"] in {"VERIFY", "INSTANCE_DECISION"})
    grant["subject_digest"] = envelope_digest
    gate["subject_digest"] = operation_digest
    for act in request["acts"]:
        if act["kind"] == "ORGANISATIONAL_ATTESTATION":
            selected = gate if "decision-attestation" in act["id"] else grant
            act.update(subject_digest=digest("authority-act", selected), attested_actor=selected["actor"])
    request["acts"].sort(key=lambda row: digest("authority-act", row))
    channel = root["channels"][0]
    request["returns"] = sorted([{"id": "return-" + row["id"], "actor": row["actor"],
        "provider": channel["provider"], "channel": channel["id"], "act_digest": digest("authority-act", row),
        "act_bytes_base64": base64.b64encode(canonical_bytes(row)).decode("ascii"),
        "returned_at": row["occurred_at"], "evidence_ref": "return-" + row["id"] + "-evidence"}
        for row in request["acts"]], key=lambda row: row["id"])
    now = request["clock"]["instant"]
    queries = {}
    capacities = {row["id"]: row for row in request["capacities"]}
    for act in request["acts"]:
        for subject in (root_digest, digest("authority-capacity", capacities[act["capacity"]])):
            for at in (act["occurred_at"], now):
                query = {"purpose": "REVOCATION", "subject_digest": subject, "at": at,
                    "provider": IDENTITY_PROVIDER, "source": "authority-revocations"}
                queries[canonical_bytes(query)] = query
    for subject in [envelope_digest] + [digest("authority-credential", row) for row in request["credentials"]]:
        query = {"purpose": "REVOCATION", "subject_digest": subject, "at": now,
            "provider": IDENTITY_PROVIDER, "source": "authority-revocations"}
        queries[canonical_bytes(query)] = query
    request["observations"] = [{"query": query, "query_digest": digest("authority-query", query),
        "status": "AVAILABLE", "as_of": query["at"], "revision": "current-revision-1", "revoked": False,
        "evidence_ref": "revocation-" + str(index)} for index, query in enumerate(sorted(queries.values(), key=canonical_bytes), 1)]
    authenticated = []
    for collection, kind, domain in (("occupancies", "OCCUPANCY", "authority-occupancy"),
            ("capacities", "CAPACITY", "authority-capacity"), ("credentials", "CREDENTIAL", "authority-credential"),
            ("returns", "RETURN", "authority-return")):
        for row in request[collection]:
            authenticated.append({"kind": kind, "record_digest": digest(domain, row),
                "provider": row["provider"], "channel": row.get("channel")})
    request["host_selection"]["authenticated_records"] = canonical_sort(authenticated)
    fields = {row["name"]: row["value"]["value"] for row in proposal["fields"]}
    step = next(row for row in work["steps"] if row["id"] == proposal["step"])
    actual_scope = {member: sorted({fields[name] for name in step["scope_fields"][member]}) for member in ("subjects", "resources")}
    scope = copy.deepcopy(actual_scope)
    for member in scope:
        scope[member] = sorted(set(scope[member]) | {row["value"] for row in envelope["scope"][member] if row["kind"] == "CONSTANT"})
    checks = [{"purpose": purpose, "subject_digest": subject, "requirement_ref": requirement, "at": now}
        for purpose, subject, requirement in (
            ("SOURCE_BINDING", envelope_digest, source["id"]), ("ROOT_BINDING", envelope_digest, root["id"]),
            ("INPUT_SUPPORT", operation_digest, step["id"]), ("BINDING", operation_digest, envelope["scope"]["id"]),
            ("GATE_FLOOR", envelope_digest, envelope["id"]), ("ENVELOPE_VALIDITY", envelope_digest, envelope["id"]),
            ("EXECUTOR_OCCUPANCY", operation_digest, proposal["executor"]["occupancy"]))]
    checks.extend({"purpose": "CONDITION", "subject_digest": operation_digest, "requirement_ref": row["id"], "at": now} for row in envelope["conditions"])
    checks.extend({"purpose": "CREDENTIAL", "subject_digest": operation_digest, "requirement_ref": row["id"], "at": now} for row in request["credentials"])
    returned = {row["act_digest"]: row for row in request["returns"]}
    for act in request["acts"]:
        act_digest = digest("authority-act", act)
        checks.extend({"purpose": purpose, "subject_digest": act_digest, "requirement_ref": requirement, "at": at}
            for purpose, requirement, at in (("ACT_CAPACITY", act["capacity"], act["occurred_at"]),
                ("ACT_OCCUPANCY", act["occupancy"], act["occurred_at"]), ("ACT_RELIANCE", act["capacity"], now),
                ("RETURN", returned[act_digest]["id"], now)))
        if act["kind"] == "ORGANISATIONAL_ATTESTATION":
            checks.append({"purpose": "SEPARATION", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": now})
        if act["kind"] in {"VERIFY", "INSTANCE_DECISION"}:
            checks.extend({"purpose": "GATE_CRITERION", "subject_digest": act_digest, "requirement_ref": criterion,
                "at": act["occurred_at"]} for criterion in act["criteria"])
    checks.extend({"purpose": "REVOCATION", "subject_digest": row["subject_digest"],
        "requirement_ref": digest("authority-query", row), "at": row["at"]} for row in queries.values())
    evidence = {name: request[name] for name in ("host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock")}
    if "evaluation_point" in request:
        evidence["evaluation_point"] = request["evaluation_point"]
    result = {"schema": SCHEMA + "authority-result", "specification_pin": PIN, "status": "READY_FOR_RESERVATION",
        "source_digest": source_digest, "work_class_digest": work_digest, "envelope_digest": envelope_digest,
        "proposal_digest": proposal_digest, "operation_digest": operation_digest, "scope": scope,
        "actual_scope": actual_scope, "act_digests": sorted(digest("authority-act", row) for row in request["acts"]),
        "checks": canonical_sort(checks), "required_budgets": [], "evidence_digest": digest("authority-evidence", evidence)}
    return request, result


def build_equipment_authority(*, step_id, fields, executor_actor, executor_role, gate_kind,
        gate_actor, gate_role, at, grant_id, source_text, occurrence_id="external-correction-occurrence", instance_id="external-correction-instance"):
    types = equipment_types() if step_id == "return-to-service" else [{"id": "IDENTITY", "kind": "IDENTITY", "nonnegative": False, "unit": None}]
    subject_fields = ["performer_role"] if step_id == "return-to-service" else ["principal"]
    resource_fields = ["approval", "asset", "inspection", "work_order"] if step_id == "return-to-service" else ["original_record_identity"]
    step = {"id": step_id, "executor_role": executor_role, "operation": step_id,
        "interface": "maintenance-register", "fields": [{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in fields],
        "scope_fields": {"subjects": subject_fields, "resources": resource_fields},
        "required_credentials": [step_id + "-authenticated-session"], "quantity_mode": "NONE", "exclusive_keys": []}
    if step_id == "return-to-service":
        step["authority_type_refs"] = ["EVENT_ID", "PROVIDER_LINK", "STATUS"]
        step["completion"] = equipment_completion_carrier()
    source = {"schema": SCHEMA + "authority-source", "id": "equipment-" + step_id + "-source",
        "revision": "MCS-12-r4-DR-08-r2", "obligations": [{"id": step_id + "-authority", "text": source_text}]}
    work = {"schema": SCHEMA + "authority-work-class", "id": "equipment-" + step_id,
        "revision": "revision-3", "types": types, "steps": [step]}
    constructor = SUPPLIER["build_authority"]
    constructor.__globals__.update(ORG=PRINCIPAL, NOW=at, PIN=PIN)
    bundle = constructor(source, work, instance_id=instance_id, occurrence_row={"occurrence_id": occurrence_id},
        step_id=step_id, envelope_id=step_id + "-envelope", executor_id=executor_actor,
        executor_role=executor_role, credential_kind=step_id + "-authenticated-session", gate_kind=gate_kind,
        gate_actor=gate_actor, gate_role=gate_role, subject_fields=subject_fields, resource_fields=resource_fields,
        proposal_fields=copy.deepcopy(fields), required_budgets=[])
    request = _replace_strings(bundle["input"], {"identity-provider": IDENTITY_PROVIDER,
        step_id + "-policy-owner": ISSUER_ROLE, "organizational-attester": "maintenance-governance-lead",
        step_id + "-grantor": "reliability-supervisor-4", "organizational-attester-person": "maintenance-governance-lead-2",
        step_id + "-grant": grant_id})
    request["envelope"]["limits"]["per_action"] = []
    request["envelope"]["gate"]["materiality"] = "MEDIUM" if gate_kind == "VERIFY" else "HIGH"
    request["envelope"]["gate"]["reversibility"] = "MEDIUM" if gate_kind == "VERIFY" else "NONE"
    for row in request["occupancies"]:
        row["kind"] = "HUMAN"
    if step_id == "return-to-service":
        request["envelope"]["temporal_validity"] = {"valid_from": "2026-09-12T14:00:00Z", "valid_until": "2026-09-12T23:59:00Z"}
        request["envelope"]["scope"]["subjects"].append({"kind": "CONSTANT", "value": PRINCIPAL})
        request["envelope"]["scope"]["subjects"] = canonical_sort(request["envelope"]["scope"]["subjects"])
    times = {"GRANT": "2026-09-12T14:00:00Z" if step_id == "return-to-service" else "2026-09-12T14:57:00Z",
        "VERIFY": "2026-09-12T14:29:00Z" if step_id == "return-to-service" else "2026-09-12T14:59:00Z",
        "INSTANCE_DECISION": "2026-09-12T14:59:00Z"}
    for act in request["acts"]:
        act["occurred_at"] = ("2026-09-12T14:59:30Z" if "decision-attestation" in act["id"] else
            "2026-09-12T14:01:00Z" if step_id == "return-to-service" else "2026-09-12T14:58:00Z") if act["kind"] == "ORGANISATIONAL_ATTESTATION" else times[act["kind"]]
    return rebind_authority(request)


def equipment_original_fixture():
    fields = equipment_native_fields()
    authority, result = build_equipment_authority(step_id="return-to-service", fields=fields,
        executor_actor="maintenance-records-clerk-17", executor_role="maintenance-records-clerk",
        gate_kind="VERIFY", gate_actor="maintenance-records-clerk-17", gate_role="maintenance-records-clerk",
        at=ORIGINAL_AT, grant_id="AP-091", source_text="One Maintenance Register return-to-service entry for EQ-204, WO-7304, IN-552 and AP-091 requires Reliability Supervisor authority and the clerk's factual gate.",
        instance_id="RTS-REQ-417")
    authority_step = authority["work_class"]["steps"][0]
    step = {**copy.deepcopy(authority_step), "kind": "OPERATION", "authority_requirements": [authority["envelope"]["id"]],
        "shared_budgets": [], "prior_effect_bindings": [], "prior_actor_separations": [],
        "permit_seconds": "300", "failure_behavior": "STOP", "completion": equipment_completion_carrier()}
    definition = {"schema": SCHEMA + "work-class-definition", "specification_pin": PIN,
        "id": authority["work_class"]["id"], "revision": "revision-3", "profile": "LINEAR", "root": step["id"],
        "participants": [{"id": authority["proposal"]["executor"]["actor"], "role": step["executor_role"], "kind": "PERSON"}],
        "objects": [], "types": equipment_types(), "steps": [step, structural_step("terminal", "TERMINAL")],
        "relationships": [{"kind": "SEQUENCE", "from": step["id"], "to": "terminal"}], "choices": [],
        "occurrence_limits": [{"step_id": step["id"], "maximum": "1"}], "loops": [], "deadlines": [],
        "parallel_blocks": [], "fanouts": [], "shared_budgets": [],
        "limits": {name: "64" for name in ("maximum_proposals", "maximum_activations", "maximum_actuations", "maximum_active_obligations", "maximum_fanout_objects")},
        "source": {"id": authority["source"]["id"], "revision": authority["source"]["revision"], "obligations": [authority["source"]["obligations"][0]["id"]]}}
    definition_digest = digest("work-class-definition", definition)
    selected_occurrence = occurrence(definition_digest, "RTS-REQ-417", step["id"])
    authority["proposal"]["occurrence"] = selected_occurrence["occurrence_id"]
    authority, result = rebind_authority(authority)
    executor = authority["proposal"]["executor"]
    native_request = {"interface": step["interface"], "operation": step["operation"], "fields": fields}
    runtime_executor = {"participant_id": executor["actor"], "role": executor["role"],
        "binding_digest": digest("executor-binding", executor)}
    credential_ids = sorted(row["id"] for row in authority["credentials"])
    observation_digests = sorted(digest("authority-observation", row) for row in authority["observations"])
    _, deployed = deployment(definition, instance_id="RTS-REQ-417", organization_id=PRINCIPAL,
        authorization_time="2026-09-12T14:00:00Z", evidence_expires_at="2026-09-13T00:00:00Z",
        initial_clocks=[available_clock(authority["clock"]["source"], "1", ORIGINAL_AT)])
    proposal_event = {"schema": SCHEMA + "runtime-event", "event_id": "original-return-to-service-proposal",
        "kind": "PROPOSE", "instance_id": "RTS-REQ-417", "expected_state_revision": deployed["state"]["revision"],
        "expected_state_digest": state_digest(deployed["state"]), "occurrence": selected_occurrence,
        "native_request": native_request, "executor": runtime_executor, "credential_ids": credential_ids,
        "authority_input": authority, "budget_inputs": [], "clock_revision": "1", "observation_digests": observation_digests}
    body = {"schema": SCHEMA + "permit", "instance_id": "RTS-REQ-417", "work_class_digest": definition_digest,
        "profile": "LINEAR", "role": "LINEAR_WORK_RUNTIME", "occurrence": selected_occurrence,
        "proposal_digest": digest("proposal", proposal_event), "native_request": native_request,
        "executor": runtime_executor, "credential_ids": credential_ids, "authority_result": result,
        "authority_result_digest": digest("authority-result", result), "authority_evidence_digest": result["evidence_digest"],
        "authority_act_bases": [{"act_digest": digest("authority-act", act), "act": copy.deepcopy(act)} for act in authority["acts"]],
        "prior_effect_bases": [], "separation_bases": [], "observation_digests": observation_digests,
        "supersedes_permit_digest": None, "budget_revisions": [], "clock_source": authority["clock"]["source"],
        "clock_revision": "1", "expires_at": "2026-09-12T14:35:00Z", "authority_basis": authority}
    permit = {"permit_id": digest("permit", body), **body}
    attributed = {"work_class": definition["id"], "instance": "RTS-REQ-417", "occurrence": selected_occurrence["occurrence_id"],
        "step": step["id"], "operation": step["operation"], "interface": step["interface"], "fields": copy.deepcopy(fields)}
    completion = step["completion"]
    actual = copy.deepcopy(fields + completion["additional_fields"]) + [
        {"name": "event_id", "value": typed("EVENT_ID", "RTS-EVT-901")},
        {"name": "event_timestamp", "value": typed("INSTANT", ORIGINAL_AT)},
        {"name": "resulting_status", "value": typed("STATUS", "Return to Service")}]
    actual.sort(key=lambda row: row["name"])
    record_body = {"provider": "maintenance-register", "source": "return-to-service-events", "record_type": "return-to-service-event",
        "provider_record_id": "RTS-EVT-901", "provider_revision": "maintenance-register-r17", "actual_fields": actual, "event_time": ORIGINAL_AT}
    record = {"evidence_id": "original-return-to-service-evidence", "native_operation_id": "maintenance-register-operation-901",
        **record_body, "record_digest": digest("provider-native-record", record_body), "evidence_ref": "original-maintenance-register-event",
        "attributed_request": attributed, "native_request_digest": digest("native-request", attributed),
        "status": "EFFECT_ESTABLISHED", "collections": [], "observed_at": "2026-09-12T14:31:00Z", "rules_out_past_and_future_effects": False}
    return {"definition": definition, "definition_digest": definition_digest, "authority_input": authority,
        "authority_result": result, "original_permit": permit, "original_record": record,
        "original_proposal_event": proposal_event}


def seal_custodian_return(returned):
    returned["provenance_digest"] = digest("source-correction-custodian-provenance", {key: value for key, value in returned.items() if key != "provenance_digest"})
    return returned


def seal_correction(record):
    record["provenance_digest"] = digest("source-correction-provenance", {key: value for key, value in record.items() if key != "provenance_digest"})
    return record


def correction_fixture(*, changes=None, original_record=None):
    original = equipment_original_fixture()
    if original_record is not None:
        original["original_record"] = copy.deepcopy(original_record)
    record = original["original_record"]
    by_name = {row["name"]: copy.deepcopy(row["value"]) for row in record["actual_fields"]}
    if changes is None:
        changes = [{"field": "reason", "old_value": copy.deepcopy(by_name["reason"]), "new_value": typed("REASON", "RTS-AUTH-INSPECTED-CORRECTED")}]
    changes = sorted(copy.deepcopy(changes), key=lambda row: row["field"])
    for row in changes:
        if row["new_value"] is None:
            by_name.pop(row["field"], None)
        else:
            by_name[row["field"]] = copy.deepcopy(row["new_value"])
    corrected = [{"name": name, "value": by_name[name]} for name in sorted(by_name)]
    changes_digest, result_digest = digest("source-correction-changes", changes), digest("source-correction-result", corrected)
    fields = [{"name": name, "value": typed("IDENTITY", value)} for name, value in sorted({
        "original_record_identity": identity_text(record), "original_record_digest": record["record_digest"],
        "original_revision": record["provider_revision"], "changes_digest": changes_digest, "principal": PRINCIPAL}.items())]
    authority, authority_result = build_equipment_authority(step_id="source-correction", fields=fields,
        executor_actor="maintenance-records-custodian-12", executor_role=CUSTODIAN_ROLE,
        gate_kind="DECIDE", gate_actor="reliability-supervisor-4", gate_role=ISSUER_ROLE,
        at=CORRECTION_AT, grant_id="CORR-GRANT-019", source_text="A correction requires a Correction Authorization issued by the Reliability Supervisor and a linked correction event entered by the Maintenance Records Custodian.")
    custodian = copy.deepcopy(authority["proposal"]["executor"])
    occupancy = next(row for row in authority["occupancies"] if row["id"] == custodian["occupancy"])
    returned = seal_custodian_return({"provider": occupancy["provider"], "source": correction_policy()["custodian_identity_source"],
        "occupancy_digest": digest("authority-occupancy", occupancy), "actor": custodian["actor"], "role": custodian["role"],
        "at": CORRECTION_AT, "evidence_ref": "current-custodian-role-return"})
    new_basis, new_result = None, None
    if any(row["field"] in correction_policy()["business_result_fields"] for row in changes):
        approval_fields = [{"name": name, "value": typed("IDENTITY", value)} for name, value in sorted({
            "original_record_identity": identity_text(record), "principal": PRINCIPAL, "corrected_result_digest": result_digest}.items())]
        new_basis, new_result = build_equipment_authority(step_id="correction-approval", fields=approval_fields,
            executor_actor=custodian["actor"], executor_role=CUSTODIAN_ROLE, gate_kind="VERIFY", gate_actor=custodian["actor"],
            gate_role=CUSTODIAN_ROLE, at=CORRECTION_AT, grant_id="AP-092",
            source_text="A change to asset, work order, inspection, approval, effective time or resulting status requires a new approval basis.")
    decision = next(row for row in authority["acts"] if row["kind"] == "INSTANCE_DECISION")
    correction = seal_correction({"schema": SCHEMA + "source-correction-record", "evidence_id": "correction-event-019",
        "provider": "maintenance-register", "source": "correction-events", "record_type": "source-correction",
        "original_provider_record_id": record["provider_record_id"], "original_record_digest": record["record_digest"],
        "expected_revision": record["provider_revision"], "custodian": custodian, "custodian_return": returned,
        "changes": changes, "corrected_fields": corrected, "correction_authority_input": authority,
        "correction_authorization_digest": digest("authority-act", decision), "new_approval_basis": new_basis,
        "event_time": CORRECTION_AT, "observed_at": CORRECTION_AT, "evidence_ref": "linked-correction-entry-019"})
    supplied = {"profile": "LINEAR", "role": "REVIEW_EVIDENCE", "specification_pin": PIN,
        "definition": original["definition"], "definition_digest": original["definition_digest"],
        "original_permit": original["original_permit"], "original_record": record, "correction": correction}
    expected = correction_result(supplied, authority_result, new_result)
    return supplied, expected


def correction_result(supplied, authority_result, new_approval_result=None):
    correction = supplied["correction"]
    return {"status": "EVIDENCE_VALID", "profile": "LINEAR", "role": "REVIEW_EVIDENCE", "specification_pin": PIN,
        "kind": "SOURCE_CORRECTION", "definition_digest": supplied["definition_digest"],
        "original_record_identity": original_identity(supplied["original_record"]), "original_record_digest": supplied["original_record"]["record_digest"],
        "correction_digest": digest("source-correction", correction), "correction_authority_result": copy.deepcopy(authority_result),
        "correction_authority_result_digest": digest("authority-result", authority_result), "new_approval_result": copy.deepcopy(new_approval_result),
        "new_approval_result_digest": digest("authority-result", new_approval_result) if new_approval_result is not None else None,
        "changes_digest": digest("source-correction-changes", correction["changes"]),
        "result_digest": digest("source-correction-result", correction["corrected_fields"])}


def correction_refusal(code):
    return {"status": "EVIDENCE_INVALID", "profile": "LINEAR", "role": "REVIEW_EVIDENCE",
        "specification_pin": PIN, "code": code, "path": ""}
