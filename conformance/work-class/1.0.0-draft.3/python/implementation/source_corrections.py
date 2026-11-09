"""Independent admission of linked provider correction evidence."""
from __future__ import annotations

from . import authority, completion, lifecycle, work_class
from .common import PIN, Refusal, canonical, digest, utf8_sorted_unique, valid_instant


def inventory(step):
    return completion.inventory(step)


def validate_policy(step, types):
    policy = step["completion"].get("correction_policy")
    if policy is None:
        return
    fields = inventory(step)
    if not utf8_sorted_unique(policy["business_result_fields"]) or not utf8_sorted_unique([row["field"] for row in policy["provider_link_bindings"]]):
        raise Refusal("DEFINITION_INVALID")
    if any(name not in fields for name in policy["business_result_fields"]):
        raise Refusal("REFERENCE_INVALID")
    for row in policy["provider_link_bindings"]:
        if row["field"] not in fields or row["record_id_field"] not in fields:
            raise Refusal("REFERENCE_INVALID")
        if any(types[fields[name]]["kind"] not in {"IDENTITY", "STRING"} for name in (row["field"], row["record_id_field"])):
            raise Refusal("TYPE_INVALID")
    if policy.get("kind") == "INDEPENDENT_HUMAN_DECISIONS":
        if any(binding["value"]["kind"] in {"ASSESSMENT", "FLOW_DISCLOSURE"} for declaration in policy["business_decision_requirements"] for binding in declaration["context_bindings"]):
            raise Refusal("UNSUPPORTED_RELATION")
        if not utf8_sorted_unique([row["id"] for row in policy["business_decision_requirements"]]) or not utf8_sorted_unique([row["proposal_field"] for row in policy["business_context_bindings"]]) or not utf8_sorted_unique(policy["fresh_result_fields"]):
            raise Refusal("DEFINITION_INVALID")
        request_bound = {row["evidence_field"] for row in step["completion"]["evidence_bindings"]}
        if any(name not in request_bound for name in policy["fresh_result_fields"]): raise Refusal("REFERENCE_INVALID")
        for row in policy["business_context_bindings"]:
            value = row["value"]
            if value["kind"] == "CORRECTED_FIELD" and value["field"] not in fields: raise Refusal("REFERENCE_INVALID")
            if value["kind"] == "LITERAL" and not work_class._typed(value["value"], types): raise Refusal("TYPE_INVALID")


def _original(request):
    definition, permit = request["definition"], request["original_permit"]
    try:
        if work_class.validate(definition) != request["definition_digest"]:
            raise Refusal("DEPENDENCY_MISMATCH")
    except Refusal:
        raise Refusal("DEPENDENCY_MISMATCH") from None
    if (permit["permit_id"] != digest("permit", {name: value for name, value in permit.items() if name != "permit_id"})
            or permit["work_class_digest"] != request["definition_digest"] or definition["profile"] != permit["profile"]
            or permit["profile"] != "LINEAR"
            or permit["role"] != "LINEAR_WORK_RUNTIME"):
        raise Refusal("DEPENDENCY_MISMATCH")
    step = next((row for row in definition["steps"] if row["id"] == permit["occurrence"]["step_id"]), None)
    if step is None or not completion.terminal(step) or "correction_policy" not in step["completion"]:
        raise Refusal("DEPENDENCY_MISMATCH")
    basis = permit.get("authority_basis")
    if basis is None or basis.get("evaluation_point", "PROPOSE") != "PROPOSE":
        raise Refusal("DEPENDENCY_MISMATCH")
    proposal, native = basis["proposal"], permit["native_request"]
    executor = proposal["executor"]
    if (basis["work_class"] != lifecycle._authority_projection(definition)
            or basis["source"]["id"] != definition["source"]["id"] or basis["source"]["revision"] != definition["source"]["revision"]
            or [row["id"] for row in basis["source"]["obligations"]] != definition["source"]["obligations"]
            or basis["envelope"]["id"] != step["authority_requirements"][0]
            or proposal["work_class"] != definition["id"] or proposal["instance"] != permit["instance_id"]
            or proposal["occurrence"] != permit["occurrence"]["occurrence_id"] or proposal["step"] != step["id"]
            or any(proposal[name] != native[name] for name in ("operation", "interface", "fields"))
            or native["operation"] != step["operation"] or native["interface"] != step["interface"]
            or [row["name"] for row in native["fields"]] != [row["name"] for row in step["fields"]]
            or any(row["value"]["type_ref"] != declaration["type_ref"] for row, declaration in zip(native["fields"], step["fields"]))
            or permit["executor"] != {"participant_id": executor["actor"], "role": executor["role"], "binding_digest": digest("executor-binding", executor)}
            or executor["role"] != step["executor_role"] or not any(row["id"] == executor["actor"] and row["role"] == executor["role"] for row in definition["participants"])
            or permit["credential_ids"] != sorted(row["id"] for row in basis["credentials"])
            or permit["observation_digests"] != lifecycle.dispatch_gate.observation_digests(basis)
            or basis["clock"]["status"] != "AVAILABLE" or basis["clock"]["source"] != permit["clock_source"]):
        raise Refusal("DEPENDENCY_MISMATCH")
    occurrence = permit["occurrence"]
    if occurrence != lifecycle._occurrence(PIN, request["definition_digest"], permit["instance_id"], step["id"], occurrence["ordinal"], occurrence["predecessor_occurrence_ids"], occurrence["enclosing"], occurrence["object_key"]):
        raise Refusal("DEPENDENCY_MISMATCH")
    result = authority.evaluate_authority(basis, PIN)
    if (result["status"] != "READY_FOR_RESERVATION" or result != permit["authority_result"]
            or permit["authority_result_digest"] != digest("authority-result", result)
            or permit["authority_evidence_digest"] != result["evidence_digest"]
            or permit["authority_act_bases"] != sorted([{"act_digest": digest("authority-act", row), "act": row} for row in basis["acts"] if digest("authority-act", row) in result["act_digests"]], key=lambda row: row["act_digest"])):
        raise Refusal("DEPENDENCY_MISMATCH")
    end = lifecycle._add_seconds(basis["clock"]["instant"], int(step["permit_seconds"]))
    fixed = basis["envelope"]["temporal_validity"]["valid_until"]
    if fixed is not None:
        end = min(end, fixed)
    if permit["expires_at"] > end or permit["expires_at"] <= basis["clock"]["instant"] or not permit["budget_revisions"] and permit["expires_at"] != end:
        raise Refusal("DEPENDENCY_MISMATCH")
    return step, basis


def _proposal_value(basis, name, value):
    step = next((row for row in basis["work_class"]["steps"] if row["id"] == basis["proposal"]["step"]), None)
    types = {row["id"]: row for row in basis["work_class"]["types"]}
    declaration = next((row for row in step["fields"] if row["name"] == name), None) if step else None
    field = next((row for row in basis["proposal"]["fields"] if row["name"] == name), None)
    if declaration is None or field is None or types[declaration["type_ref"]]["kind"] not in {"STRING", "IDENTITY"} or field["value"] != {"type_ref": declaration["type_ref"], "value": value}:
        raise Refusal("BINDING_MISMATCH")


def _scope(result, identity, principal):
    if any(identity not in result[name]["resources"] or principal not in result[name]["subjects"] for name in ("scope", "actual_scope")):
        raise Refusal("EVIDENCE_UNAVAILABLE")


def check(request):
    original, correction = request["original_record"], request["correction"]
    current = correction["correction_authority_input"]
    if (current.get("assessment_bases") or current["envelope"].get("assessment_requirements")
            or any(binding["value"]["kind"] == "ASSESSMENT" for declaration in current["envelope"].get("decision_requirements", []) for binding in declaration["context_bindings"])):
        raise Refusal("UNSUPPORTED_RELATION")
    dates = [original["event_time"], original["observed_at"], correction["event_time"], correction["observed_at"], correction["custodian_return"]["at"]]
    if any(not valid_instant(at) for at in dates):
        raise Refusal("SCHEMA_INVALID")
    step, original_basis = _original(request)
    carrier, policy = step["completion"], step["completion"]["correction_policy"]
    independent = policy.get("kind") == "INDEPENDENT_HUMAN_DECISIONS"
    if (correction.get("decision_policy") == "INDEPENDENT_HUMAN_DECISIONS") != independent:
        raise Refusal("BINDING_MISMATCH")
    identity = {name: original.get(name) for name in ("provider", "source", "record_type", "provider_record_id")}
    identity_text = canonical(identity).decode("utf-8")
    principal = original_basis["envelope"]["principal"]
    attributed = {"work_class": request["definition"]["id"], "instance": request["original_permit"]["instance_id"], "occurrence": request["original_permit"]["occurrence"]["occurrence_id"], "step": step["id"], **request["original_permit"]["native_request"]}
    commitment = {name: original.get(name) for name in ("provider", "source", "record_type", "provider_record_id", "provider_revision", "actual_fields", "event_time")}
    if (original["status"] != "EFFECT_ESTABLISHED" or not original.get("provider_record_id") or not original.get("provider_revision")
            or any(original[name] != carrier["effect_" + name] for name in ("provider", "source", "record_type"))
            or original["record_digest"] != digest("provider-native-record", commitment)
            or original["attributed_request"] != attributed or original["native_request_digest"] != digest("native-request", attributed)
            or original["event_time"] > original["observed_at"] or original["rules_out_past_and_future_effects"] or original["collections"]
            or any(correction[name] != policy["correction_" + name] for name in ("provider", "source", "record_type"))
            or correction["original_provider_record_id"] != original["provider_record_id"] or correction["original_record_digest"] != original["record_digest"]
            or correction["expected_revision"] != original["provider_revision"]
            or not original["event_time"] <= correction["event_time"] <= correction["observed_at"]):
        raise Refusal("BINDING_MISMATCH")
    rows = original["actual_fields"]
    if not utf8_sorted_unique([row["name"] for row in rows]) or not utf8_sorted_unique([row["field"] for row in correction["changes"]]):
        raise Refusal("BINDING_MISMATCH")
    fields = {row["name"]: row["value"] for row in rows}
    declared = inventory(step)
    types = {row["id"]: row for row in request["definition"]["types"]}
    for change in correction["changes"]:
        name, old, new = change["field"], change["old_value"], change["new_value"]
        if name in {row["evidence_field"] for row in carrier.get("authorization_revision_bindings", [])}:
            raise Refusal("BINDING_MISMATCH")
        if old != fields.get(name) or old == new:
            raise Refusal("BINDING_MISMATCH")
        if name in declared:
            if new is None:
                raise Refusal("BINDING_MISMATCH")
            if new["type_ref"] != declared[name] or not work_class._typed(new, types):
                raise Refusal("TYPE_INVALID")
            fields[name] = new
        elif name not in fields or new is not None:
            raise Refusal("BINDING_MISMATCH")
        else:
            del fields[name]
    corrected = [{"name": name, "value": fields[name]} for name in sorted(fields, key=str.encode)]
    if correction["corrected_fields"] != corrected or set(fields) != set(declared):
        raise Refusal("BINDING_MISMATCH")
    if any(value["type_ref"] != declared[name] or not work_class._typed(value, types) for name, value in fields.items()):
        raise Refusal("TYPE_INVALID")
    for link in policy["provider_link_bindings"]:
        expected = {name: link[name] for name in ("provider", "source", "record_type")}
        expected["provider_record_id"] = fields[link["record_id_field"]]["value"]
        if fields[link["field"]]["value"] != canonical(expected).decode("utf-8"):
            raise Refusal("BINDING_MISMATCH")
    changes_digest = digest("source-correction-changes", correction["changes"])
    result_digest = digest("source-correction-result", corrected)
    current, custodian, returned = correction["correction_authority_input"], correction["custodian"], correction["custodian_return"]
    business = any(row["field"] in policy["business_result_fields"] for row in correction["changes"])
    if independent:
        _proposal_value(current, policy["result_digest_field"], result_digest)
        _business_context(request, step, fields, original_basis, current, business)
    occupancy = next((row for row in current["occupancies"] if row["id"] == custodian["occupancy"]), None)
    if (custodian["role"] != policy["custodian_role"] or custodian["principal"] != principal or occupancy is None
            or returned["provider"] != occupancy["provider"] or returned["source"] != policy["custodian_identity_source"]
            or returned["occupancy_digest"] != digest("authority-occupancy", occupancy) or returned["actor"] != custodian["actor"]
            or returned["role"] != custodian["role"] or returned["at"] != correction["event_time"]):
        raise Refusal("BINDING_MISMATCH")
    if (current.get("evaluation_point", "PROPOSE") != "PROPOSE" or current["clock"] != {"source": current["clock"]["source"], "status": "AVAILABLE", "instant": correction["event_time"]}
            or current["proposal"]["executor"] != custodian or current["envelope"]["principal"] != principal
            or current["envelope"]["executor_role"] != policy["custodian_role"] or current["envelope"]["gate"]["kind"] != "DECIDE"):
        raise Refusal("EVIDENCE_UNAVAILABLE")
    result = authority.evaluate_authority(current, PIN)
    if result["status"] != "READY_FOR_RESERVATION":
        raise Refusal("EVIDENCE_UNAVAILABLE")
    decisions = [row for row in current["acts"] if row["kind"] == "INSTANCE_DECISION" and digest("authority-act", row) in result["act_digests"]]
    if len(decisions) != 1 or decisions[0]["role"] != policy["issuer_role"] or decisions[0]["occurred_at"] > correction["event_time"] or correction["correction_authorization_digest"] != digest("authority-act", decisions[0]):
        raise Refusal("BINDING_MISMATCH")
    for name, value in (("original_id_field", identity_text), ("original_digest_field", original["record_digest"]), ("original_revision_field", original["provider_revision"]), ("changes_digest_field", changes_digest)):
        _proposal_value(current, policy[name], value)
    _scope(result, identity_text, principal)
    fresh = correction.get("new_approval_basis")
    new_result = None
    if not independent and (not business and fresh is not None or business and fresh is None):
        raise Refusal("BINDING_MISMATCH")
    if business and not independent:
        if fresh.get("evaluation_point", "PROPOSE") != "PROPOSE" or fresh["clock"]["status"] != "AVAILABLE" or fresh["clock"]["instant"] != correction["event_time"] or fresh["envelope"]["principal"] != principal:
            raise Refusal("EVIDENCE_UNAVAILABLE")
        new_result = authority.evaluate_authority(fresh, PIN)
        if new_result["status"] != "READY_FOR_RESERVATION":
            raise Refusal("EVIDENCE_UNAVAILABLE")
        grants = [row for row in fresh["acts"] if row["kind"] == "GRANT" and digest("authority-act", row) in new_result["act_digests"]]
        old_ids = {original["provider_record_id"], *(row["id"] for row in original_basis["acts"] if row["kind"] == "GRANT")}
        approval_fields = {row["record_id_field"] for row in policy["provider_link_bindings"]}
        old_ids.update(row["value"]["value"] for row in original["actual_fields"]
                       if row["name"] in approval_fields and isinstance(row["value"]["value"], str))
        approval_request_fields = {row["request_field"] for row in carrier["evidence_bindings"] if row["evidence_field"] in approval_fields}
        old_ids.update(row["value"]["value"] for row in request["original_permit"]["native_request"]["fields"]
                       if row["name"] in approval_request_fields)
        if len(grants) != 1 or grants[0]["id"] in old_ids or grants[0]["role"] != policy["issuer_role"] or grants[0]["occurred_at"] > correction["event_time"]:
            raise Refusal("BINDING_MISMATCH")
        _proposal_value(fresh, policy["result_digest_field"], result_digest)
        _scope(new_result, identity_text, principal)
    if returned["provenance_digest"] != digest("source-correction-custodian-provenance", {name: value for name, value in returned.items() if name != "provenance_digest"}) or correction["provenance_digest"] != digest("source-correction-provenance", {name: value for name, value in correction.items() if name != "provenance_digest"}):
        raise Refusal("BINDING_MISMATCH")
    output = {"status": "EVIDENCE_VALID", "profile": "LINEAR", "role": "REVIEW_EVIDENCE", "specification_pin": PIN, "kind": "SOURCE_CORRECTION", "definition_digest": request["definition_digest"], "original_record_identity": identity, "original_record_digest": original["record_digest"], "correction_digest": digest("source-correction", correction), "correction_authority_result": result, "correction_authority_result_digest": digest("authority-result", result), "changes_digest": changes_digest, "result_digest": result_digest}
    output.update({"decision_policy": "INDEPENDENT_HUMAN_DECISIONS"} if independent else {"new_approval_result": new_result, "new_approval_result_digest": None if new_result is None else digest("authority-result", new_result)})
    return output


def _business_context(request, step, fields, original_basis, current, business):
    policy = step["completion"]["correction_policy"]
    declarations = current["envelope"].get("decision_requirements", [])
    bases = current.get("decision_bases", [])
    if not business:
        if declarations or bases: raise Refusal("BINDING_MISMATCH")
    elif declarations != policy["business_decision_requirements"]:
        raise Refusal("BINDING_MISMATCH")
    controls = {policy[name] for name in ("original_id_field", "original_digest_field", "original_revision_field", "changes_digest_field", "result_digest_field")}
    proposal = {row["name"]: row["value"] for row in current["proposal"]["fields"]}
    bindings = {row["proposal_field"]: row["value"] for row in policy["business_context_bindings"]}
    if set(bindings) != set(proposal) - controls: raise Refusal("BINDING_MISMATCH")
    if any(binding["value"]["kind"] == "PROPOSAL_FIELD" and
           (binding["value"]["field"] not in bindings or binding["value"]["field"] in controls)
           for declaration in declarations for binding in declaration["context_bindings"]):
        raise Refusal("BINDING_MISMATCH")
    original_types = {row["id"]: row for row in request["definition"]["types"]}
    current_types = {row["id"]: row for row in current["work_class"]["types"]}
    for name, binding in bindings.items():
        value = fields[binding["field"]] if binding["kind"] == "CORRECTED_FIELD" else binding["value"]
        ref = value["type_ref"]
        if ref not in original_types or ref not in current_types or original_types[ref] != current_types[ref] or not work_class._typed(value, original_types) or not work_class._typed(value, current_types):
            raise Refusal("TYPE_INVALID")
        if proposal[name] != value: raise Refusal("BINDING_MISMATCH")
    if not business: return
    original = {row["name"]: row["value"] for row in request["original_record"]["actual_fields"]}
    requested = {row["name"]: row["value"] for row in request["original_permit"]["native_request"]["fields"]}
    bound = {row["evidence_field"]: row["request_field"] for row in step["completion"]["evidence_bindings"]}
    for name in policy["fresh_result_fields"]:
        if fields[name] == requested[bound[name]] or fields[name] == original.get(name): raise Refusal("BINDING_MISMATCH")
    old_declarations = {row["id"]: row for row in original_basis["envelope"].get("decision_requirements", [])}
    old_bases = {row["requirement_id"]: row["evidence"] for row in original_basis.get("decision_bases", [])}
    new_bases = {row["requirement_id"]: row["evidence"] for row in bases}
    required = {row["id"] for row in declarations}
    if required - set(new_bases): raise Refusal("EVIDENCE_UNAVAILABLE")
    if set(new_bases) - required: raise Refusal("BINDING_MISMATCH")
    old_act_ids, old_act_digests, old_identities = set(), set(), set()
    for name, evidence in old_bases.items():
        acts = [row for row in evidence["authority_input"]["acts"] if digest("authority-act", row) == evidence["decision_act_digest"]]
        if name not in old_declarations or len(acts) != 1: raise Refusal("BINDING_MISMATCH")
        old_act_ids.add(acts[0]["id"])
        old_act_digests.add(evidence["decision_act_digest"])
        identity_field = old_declarations[name]["identity_field"]
        old_identities.update(row["value"]["value"] for row in evidence["authority_input"]["proposal"]["fields"] if row["name"] == identity_field)
    identities, act_ids, act_digests = set(), set(), set()
    for declaration in declarations:
        name = declaration["id"]
        if name not in old_declarations or name not in old_bases or any(declaration[key] != old_declarations[name][key] for key in ("principal", "role")):
            raise Refusal("BINDING_MISMATCH")
        fresh = new_bases[name]
        new_act = next((row for row in fresh["authority_input"]["acts"] if digest("authority-act", row) == fresh["decision_act_digest"]), None)
        if (new_act is None or new_act["id"] in old_act_ids | act_ids
                or fresh["decision_act_digest"] in old_act_digests | act_digests):
            raise Refusal("BINDING_MISMATCH")
        act_ids.add(new_act["id"])
        act_digests.add(fresh["decision_act_digest"])
        context = next((row["value"] for row in declaration["context_bindings"] if row["field"] == declaration["identity_field"]), None)
        if context is None or context["kind"] != "PROPOSAL_FIELD": raise Refusal("BINDING_MISMATCH")
        target = bindings.get(context["field"])
        if target is None or target["kind"] != "CORRECTED_FIELD" or target["field"] not in bound: raise Refusal("BINDING_MISMATCH")
        field = target["field"]
        if fields[field] == requested[bound[field]] or fields[field] == original.get(field): raise Refusal("BINDING_MISMATCH")
        identity = fields[field]["value"]
        if identity in old_identities | identities: raise Refusal("BINDING_MISMATCH")
        identities.add(identity)
