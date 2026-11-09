"""Closed independent-decision and source-vector contract extensions."""
from __future__ import annotations

import copy
from equipment_schema_extensions import BASE, DIGEST, ID, INSTANT, VALUE, arr, obj


def local(name):
    return {"$ref": "#/$defs/" + name}


def replace_refs(value, mapping):
    if isinstance(value, dict):
        return {key: mapping.get(child, child) if key == "$ref" else replace_refs(child, mapping) for key, child in value.items()}
    if isinstance(value, list):
        return [replace_refs(child, mapping) for child in value]
    return value


def extend_cdmo_schemas(work, lifecycle, authority, evidence):
    a, w, l, e = (schema["$defs"] for schema in (authority, work, lifecycle, evidence))
    # Remove previous generated additions before cloning the nonrecursive profile.
    for name, member in (("input", "decision_bases"), ("envelope", "decision_requirements"),
            ("gate", "decision_requirement"), ("result", "decision_results"), ("refusal", "decision_results")):
        a[name]["properties"].pop(member, None)
    while "oneOf" in a["definition"]:
        a["definition"] = copy.deepcopy(a["definition"]["oneOf"][0])
    for name in ("check", "failedCheck"):
        a[name]["properties"]["purpose"]["enum"] = [v for v in a[name]["properties"]["purpose"]["enum"] if v != "HUMAN_DECISION"]
    for name, member in (("refusal", "reasons"), ("failedCheck", "reason")):
        target = a[name]["properties"][member]
        if member == "reasons":
            target = target["items"]
        target["enum"] = [v for v in target["enum"] if v not in {"DECISION_NOT_EFFECTIVE", "DECISION_SEPARATION"}]
    # Freeze the nonrecursive profile before extending ordinary authority.
    leaf_refs = {"#/$defs/" + name: "#/$defs/humanDecision" + name[0].upper() + name[1:] for name in
        ("envelope", "workClass", "step", "gate", "sourceObservationRequirement", "sourceObservationRelation", "sourceObservationSelector")}
    for name in ("envelope", "workClass", "step", "gate", "sourceObservationRequirement", "sourceObservationRelation", "sourceObservationSelector"):
        a["humanDecision" + name[0].upper() + name[1:]] = replace_refs(copy.deepcopy(a[name]), leaf_refs)
    step = a["humanDecisionStep"]
    for name in ("dispatch_gate", "completion"):
        step["properties"].pop(name, None)
    step["properties"]["quantity_mode"] = {"const": "NONE"}
    for name in ("required_credentials", "exclusive_keys"):
        step["properties"][name]["maxItems"] = 0
    a["humanDecisionWorkClass"]["properties"]["steps"]["maxItems"] = 1
    a["humanDecisionWorkClass"]["properties"]["authority_profile"] = {"const": "EVIDENCE_ONLY"}
    a["humanDecisionWorkClass"]["required"].append("authority_profile")
    a["humanDecisionLimits"] = copy.deepcopy(a["limits"])
    for name in ("per_action", "shared_budgets"):
        a["humanDecisionLimits"]["properties"][name]["maxItems"] = 0
    a["humanDecisionEnvelope"]["properties"]["limits"] = local("humanDecisionLimits")
    a["humanDecisionGate"]["properties"]["kind"] = {"const": "DECIDE"}
    leaf = replace_refs(copy.deepcopy(a["input"]), leaf_refs)
    leaf["properties"]["credentials"]["maxItems"] = 0
    a["humanDecisionInput"] = leaf
    human_definition = replace_refs(copy.deepcopy(a["definition"]), leaf_refs)
    a["humanDecisionDefinition"] = human_definition
    a["definition"] = {"oneOf": [copy.deepcopy(a["definition"]), local("humanDecisionDefinition")]}
    a["humanDecisionEvidence"] = obj({
        "schema": {"const": "seampoint.work-class/1.0.0-draft.3/human-decision-evidence"},
        "authority_input": local("humanDecisionInput"), "decision_act_digest": DIGEST,
    })
    a["humanDecisionRequirement"] = obj({
        "id": ID, "step": ID, "principal": ID, "role": ID,
        "work_class_digest": DIGEST, "envelope_digest": DIGEST, "record_requirement_id": ID, "identity_field": ID,
        "validity_fields": obj({"not_before_field": ID, "not_after_field": ID}),
        "context_bindings": arr(obj({"field": ID, "value": {"oneOf": [
            obj({"kind": {"const": "PROPOSAL_FIELD"}, "field": ID}),
            obj({"kind": {"const": "LITERAL"}, "value": VALUE}),
        ]}}), 64),
        "distinct_from": arr({"oneOf": [obj({"kind": {"const": "EXECUTOR"}}),
            obj({"kind": {"const": "DECISION"}, "requirement_id": ID})]}, 17),
    })
    a["input"]["properties"]["decision_bases"] = arr(obj({
        "requirement_id": ID, "evidence": local("humanDecisionEvidence"),
    }), 16)
    a["envelope"]["properties"]["decision_requirements"] = arr(local("humanDecisionRequirement"), 16)
    a["gate"]["properties"]["decision_requirement"] = ID
    result = copy.deepcopy(a["result"])
    result["properties"]["schema"] = {"const": "seampoint.work-class/1.0.0-draft.3/human-decision-result"}
    result["properties"]["status"] = {"const": "EVIDENCE_VALID"}
    result["properties"]["decision_act_digest"] = DIGEST
    result["properties"]["effective_until"] = INSTANT
    result["required"].extend(["decision_act_digest", "effective_until"])
    result["properties"]["required_budgets"]["maxItems"] = 0
    result["properties"]["required_exclusive_keys"]["maxItems"] = 0
    a["humanDecisionResult"] = result
    a["humanDecisionRefusal"] = copy.deepcopy(a["refusal"])
    a["decisionResult"] = obj({"requirement_id": ID,
        "result": {"oneOf": [local("humanDecisionResult"), local("humanDecisionRefusal")]},
        "result_digest": DIGEST})
    for name in ("result", "refusal"):
        a[name]["properties"]["decision_results"] = arr(local("decisionResult"), 16)
    for name in ("check", "failedCheck"):
        a[name]["properties"]["purpose"]["enum"].append("HUMAN_DECISION")
    for name, property_name in (("refusal", "reasons"), ("failedCheck", "reason")):
        target = a[name]["properties"][property_name]
        if property_name == "reasons":
            target = target["items"]
        target["enum"].extend(["DECISION_NOT_EFFECTIVE", "DECISION_SEPARATION"])
    # The leaf check/refusal enums remain the ordinary nonrecursive profile.
    a["sourceObservationSelector"]["oneOf"].extend([
        obj({"kind": {"const": "DECISION_ACT"}, "requirement_id": ID,
             "member": {"enum": ["digest", "id", "actor", "role", "principal", "occurred_at"]}, "type_ref": ID}),
        obj({"kind": {"const": "DECISION_FIELD"}, "requirement_id": ID, "field": ID}),
        obj({"kind": {"const": "DECISION_BASIS"}, "requirement_id": ID, "type_ref": ID}),
    ])
    gate = obj({"kind": {"const": "SOURCE_REQUIREMENTS"}, "requirements": arr(ID, 64, 1),
        "coordinator_requirement": ID, "fence_provider": ID, "fence_source": ID,
        "authorization_seconds": {"type": "string", "pattern": "^[1-9][0-9]*$", "maxLength": 128},
        "validity_requirements": arr(obj({"requirement_id": ID, "not_before_field": ID, "not_after_field": ID}), 64)})
    for defs in (w, a):
        legacy = copy.deepcopy(defs["step"]["properties"]["dispatch_gate"])
        defs["step"]["properties"]["dispatch_gate"] = {"oneOf": [legacy, copy.deepcopy(gate)]}
    l["authorizationFence"] = {"oneOf": [copy.deepcopy(l["authorizationFence"]), obj({
        "kind": {"const": "SOURCE_REQUIREMENTS"}, "provider": ID, "source": ID,
        "provider_revision": ID, "scope_digest": DIGEST, "checked_at": INSTANT,
        "status": {"enum": ["EFFECTIVE", "WITHDRAWN", "UNKNOWN"]},
        "sources": arr(local("fenceSource"), 64, 1),
    })]}
    l["decisionDetailAuthorization"]["oneOf"].append(obj({
        "kind": {"const": "AUTHORIZATION"}, "authorization_digest": DIGEST,
        "permit_digest": DIGEST, "gate_kind": {"const": "SOURCE_REQUIREMENTS"},
        "checked_at": INSTANT, "expires_at": INSTANT, "sources": arr(local("fenceSource"), 64, 1),
    }))
    l["decisionDetailSeparation"]["properties"]["authority_basis"] = {"$ref": BASE + "authority.schema.json#/$defs/input"}
    for variant in w["completionCarrier"]["oneOf"]:
        if variant["properties"].get("terminal_policy", {}).get("const") != "STOP_RETAIN":
            continue
        variant["properties"]["authorization_revision_bindings"] = arr(obj({
            "evidence_field": ID, "type_ref": ID, "requirement_id": ID}), 64)
        variant["properties"]["status_request_field"] = ID
        old_policy = variant["properties"]["correction_policy"]
        policy = copy.deepcopy(old_policy)
        policy["properties"].update({"kind": {"const": "INDEPENDENT_HUMAN_DECISIONS"},
            "business_decision_requirements": arr({"$ref": BASE + "authority.schema.json#/$defs/humanDecisionRequirement"}, 16, 1),
            "business_context_bindings": arr(obj({"proposal_field": ID, "value": {"oneOf": [
                obj({"kind": {"const": "CORRECTED_FIELD"}, "field": ID}),
                obj({"kind": {"const": "LITERAL"}, "value": VALUE}),
            ]}}), 64, 1),
            "fresh_result_fields": arr(ID, 64, 1)})
        policy["required"] = list(policy["properties"])
        variant["properties"]["correction_policy"] = {"oneOf": [old_policy, policy]}
    old_record = copy.deepcopy(e["sourceCorrectionRecord"])
    record = copy.deepcopy(old_record)
    record["properties"].pop("new_approval_basis")
    record["required"].remove("new_approval_basis")
    record["properties"]["decision_policy"] = {"const": "INDEPENDENT_HUMAN_DECISIONS"}
    record["required"].append("decision_policy")
    e["sourceCorrectionRecord"] = {"oneOf": [old_record, record]}
    old_result = copy.deepcopy(e["sourceCorrectionResult"])
    result = copy.deepcopy(old_result)
    for name in ("new_approval_result", "new_approval_result_digest"):
        result["properties"].pop(name)
        result["required"].remove(name)
    result["properties"]["decision_policy"] = {"const": "INDEPENDENT_HUMAN_DECISIONS"}
    result["required"].append("decision_policy")
    e["sourceCorrectionResult"] = {"oneOf": [old_result, result]}
