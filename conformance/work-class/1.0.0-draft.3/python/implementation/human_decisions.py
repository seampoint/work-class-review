"""Nonrecursive human evidence and phase-joined execution authority."""
from __future__ import annotations

import copy

from . import authority as a


ORDERS = {
    1: ("SCHEMA_INVALID", "ARTIFACT_ENCODING_INVALID", "ARTIFACT_NONCANONICAL", "TYPE_INVALID", "INPUT_INVALID"),
    2: ("VERSION_UNSUPPORTED", "DEPENDENCY_MISMATCH", "DEFINITION_INVALID", "DIGEST_MISMATCH", "STATE_INVALID", "CLOCK_INVALID", "EVIDENCE_UNAVAILABLE", "UNSUPPORTED_RELATION", "REFERENCE_INVALID", "LIMIT_EXCEEDED"),
    3: ("BINDING_MISMATCH",),
    4: ("ACT_CONFLICT", "GATE_REQUIRED", "EVIDENCE_UNAVAILABLE", "ACT_NOT_AUTHORIZED", "ACT_NOT_ACCEPTED"),
    5: ("DEPENDENCY_MISMATCH", "EVIDENCE_UNAVAILABLE", "AUTHORITY_NOT_ESTABLISHED"),
}


def _first(phase, errors):
    return next((code for code in ORDERS[phase] if code in errors), None)


def requirements(request):
    return [row for row in request["envelope"].get("decision_requirements", []) if row["step"] == request["proposal"]["step"]]


def declaration_errors(work, envelope):
    from . import assessments
    errors = set()
    declared = envelope.get("decision_requirements", [])
    table = {row["id"]: row for row in declared}
    steps, types = a._step_map(work), a._type_map(work)
    source = {row["id"]: row for row in envelope.get("source_observation_requirements", [])}
    if not a._ordered_unique([row["id"] for row in declared], str.encode):
        errors.add("INPUT_INVALID")
    for row in declared:
        step, record = steps.get(row["step"]), source.get(row["record_requirement_id"])
        if step is None or record is None:
            errors.add("REFERENCE_INVALID")
            continue
        if record["step"] != row["step"] or record["expected_status"] != "AVAILABLE" or record["purpose"] != "AUTHORITY" or record["record_id"] is None and not assessments.identity_exception(work, envelope, row):
            errors.add("UNSUPPORTED_RELATION")
        if not a._ordered_unique([item["field"] for item in row["context_bindings"]], str.encode) or not a._ordered_unique(row["distinct_from"], a.canonical):
            errors.add("INPUT_INVALID")
        fields = a._field_map(step)
        for binding in row["context_bindings"]:
            value = binding["value"]
            if value["kind"] == "PROPOSAL_FIELD":
                if value["field"] not in fields:
                    errors.add("REFERENCE_INVALID")
            elif value["kind"] == "ASSESSMENT":
                target = next((item for item in envelope.get("assessment_requirements", []) if item["id"] == value["requirement_id"]), None)
                if target is None or value["type_ref"] not in types:
                    errors.add("REFERENCE_INVALID")
                elif types[value["type_ref"]]["kind"] not in {"STRING", "IDENTITY"}:
                    errors.add("TYPE_INVALID")
                linked = table.get(target["review_decision_requirement_id"]) if target is not None else None
                if (target is not None and target["step"] in steps and linked is not None and linked["step"] in steps
                        and (target["step"] != row["step"] or linked["id"] != row["id"])):
                    errors.add("UNSUPPORTED_RELATION")
            elif value["kind"] == "FLOW_DISCLOSURE":
                target = next((item for item in envelope.get("flow_requirements", []) if item["id"] == value["requirement_id"]), None)
                if target is None or value["type_ref"] not in types:
                    errors.add("REFERENCE_INVALID")
                elif types[value["type_ref"]]["kind"] not in {"STRING", "IDENTITY"}:
                    errors.add("TYPE_INVALID")
                if target is not None and (target["step"] != row["step"] or target["release_decision_requirement_id"] != row["id"]):
                    errors.add("UNSUPPORTED_RELATION")
            elif value["value"]["type_ref"] not in types:
                errors.add("REFERENCE_INVALID")
        for separation in row["distinct_from"]:
            if separation["kind"] == "DECISION" and (separation["requirement_id"] not in table or separation["requirement_id"] == row["id"] or table[separation["requirement_id"]]["step"] != row["step"]):
                errors.add("REFERENCE_INVALID")
    selected = envelope["gate"].get("decision_requirement")
    if selected is not None:
        if envelope["gate"]["kind"] != "DECIDE":
            errors.add("UNSUPPORTED_RELATION")
        if selected not in table:
            errors.add("REFERENCE_INVALID")
    return errors


def binding_type(work, declaration, field):
    binding = next((row for row in declaration["context_bindings"] if row["field"] == field), None)
    if binding is None:
        raise LookupError(field)
    value = binding["value"]
    if value["kind"] == "PROPOSAL_FIELD":
        return a._field_map(a._step_map(work)[declaration["step"]])[value["field"]]["type_ref"]
    return value["type_ref"] if value["kind"] in {"ASSESSMENT", "FLOW_DISCLOSURE"} else value["value"]["type_ref"]


def reliance_subject(request):
    return a.digest("human-decision-reliance-subjects", {
        "root_digest": a.digest("authority-root", request["host_selection"]["root"]),
        "envelope_digest": a.digest("authority-envelope", request["envelope"]),
        "capacities": [{"id": row["id"], "capacity_digest": a.digest("authority-capacity", row)} for row in sorted(request["capacities"], key=lambda row: row["id"].encode())],
    })


def _bridge(left, right, ref):
    return ref in left and ref in right and left[ref] == right[ref]


def _translate(predicate, bindings):
    if isinstance(predicate, list):
        return [_translate(row, bindings) for row in predicate]
    if not isinstance(predicate, dict):
        return predicate
    if predicate.get("kind") == "FIELD":
        value = bindings[predicate["name"]]
        if value["kind"] in {"ASSESSMENT", "FLOW_DISCLOSURE"}:
            raise ValueError("unsupported assessment predicate")
        return {"kind": "FIELD", "name": value["field"]} if value["kind"] == "PROPOSAL_FIELD" else {"kind": "LITERAL", "value": copy.deepcopy(value["value"])}
    return {key: _translate(value, bindings) for key, value in predicate.items()}


def _coverage(declaration, leaf, record):
    name = declaration["id"]
    covered = set()
    for relation in record["relations"]:
        if relation["kind"] != "EQUALS":
            continue
        for selected, own in ((relation["left"], relation["right"]), (relation["right"], relation["left"])):
            if not isinstance(selected, dict) or selected.get("requirement_id") != name:
                continue
            own_id = isinstance(own, dict) and own.get("kind") == "OBSERVATION_ID" and own.get("requirement_id") == record["id"]
            own_field = isinstance(own, str) or isinstance(own, dict) and own.get("kind") == "OBSERVATION_FIELD" and own.get("requirement_id") == record["id"]
            if selected["kind"] == "DECISION_ACT" and ((selected["member"] == "id" and own_id) or selected["member"] != "id" and own_field):
                covered.add(("act", selected["member"]))
            if selected["kind"] == "DECISION_FIELD" and own_field:
                covered.add(("field", selected["field"]))
    expected = {("act", member) for member in ("id", "digest", "actor", "role", "principal", "occurred_at")}
    expected.update(("field", row["name"]) for row in leaf["proposal"]["fields"])
    return expected <= covered


def _known_bridges(outer, contexts):
    errors = []
    types = a._type_map(outer["work_class"])
    outer_fields = a._field_map(a._step_map(outer["work_class"])[outer["proposal"]["step"]]) if outer["proposal"]["step"] in a._step_map(outer["work_class"]) else {}
    declarations = {row["id"]: row for row in outer["envelope"].get("decision_requirements", [])}
    for name, context in contexts:
        declaration = declarations.get(name)
        if declaration is None:
            continue
        leaf = context["request"]
        leaf_types = a._type_map(leaf["work_class"])
        fields = {row["name"]: row["value"] for row in leaf["proposal"]["fields"]}
        for binding in declaration["context_bindings"]:
            own = fields.get(binding["field"])
            if own is None:
                continue
            value = binding["value"]
            target_ref = outer_fields.get(value["field"], {}).get("type_ref") if value["kind"] == "PROPOSAL_FIELD" else value["type_ref"] if value["kind"] in {"ASSESSMENT", "FLOW_DISCLOSURE"} else value["value"]["type_ref"]
            if own["type_ref"] in leaf_types and target_ref in types and (own["type_ref"] != target_ref or leaf_types[own["type_ref"]] != types[target_ref]):
                errors.append("TYPE_INVALID")
        if outer["envelope"]["gate"].get("decision_requirement") == name:
            for node in a._walk_nodes(leaf["envelope"]["gate"]["criteria"]):
                if isinstance(node, dict) and "type_ref" in node and "value" in node and node["type_ref"] in types and node["type_ref"] in leaf_types and not _bridge(types, leaf_types, node["type_ref"]):
                    errors.append("TYPE_INVALID")
    return errors


def _phase_two(outer, contexts):
    errors = list(declaration_errors(outer["work_class"], outer["envelope"]))
    selected = {row["id"]: row for row in requirements(outer)}
    names = [row["requirement_id"] for row in outer.get("decision_bases", [])]
    if not a._ordered_unique(names, str.encode):
        return ["INPUT_INVALID"]
    if set(names) - set(selected): errors.append("DEPENDENCY_MISMATCH")
    if set(selected) - set(names): errors.append("EVIDENCE_UNAVAILABLE")
    if len(a.canonical(outer)) > 1048576: errors.append("LIMIT_EXCEEDED")
    sources = {row["id"]: row for row in outer["envelope"].get("source_observation_requirements", [])}
    for name, context in contexts.items():
        leaf = context["request"]
        if len(a.canonical(leaf)) > 262144: errors.append("LIMIT_EXCEEDED")
        declaration = selected.get(name)
        if declaration is None: continue
        context["declaration"] = declaration
        if a.digest("authority-work-class", leaf["work_class"]) != declaration["work_class_digest"] or a.digest("authority-envelope", leaf["envelope"]) != declaration["envelope_digest"]:
            errors.append("DEPENDENCY_MISMATCH")
        fields = a._field_map(leaf["work_class"]["steps"][0])
        if set(fields) != {row["field"] for row in declaration["context_bindings"]}: errors.append("REFERENCE_INVALID")
        bindings = {row["field"]: row["value"] for row in declaration["context_bindings"]}
        if outer["envelope"]["gate"].get("decision_requirement") == name and any(isinstance(node, dict) and node.get("kind") == "FIELD" and bindings.get(node["name"], {}).get("kind") in {"ASSESSMENT", "FLOW_DISCLOSURE"} for node in a._walk_nodes(leaf["envelope"]["gate"]["criteria"])):
            errors.append("UNSUPPORTED_RELATION")
        for field in (declaration["identity_field"], *declaration["validity_fields"].values()):
            if field not in fields: errors.append("REFERENCE_INVALID")
        validity = declaration["validity_fields"]
        if validity["not_before_field"] == validity["not_after_field"]: errors.append("UNSUPPORTED_RELATION")
        record = sources.get(declaration["record_requirement_id"])
        if record is not None and not _coverage(declaration, leaf, record): errors.append("UNSUPPORTED_RELATION")
        if record is not None:
            gate = a._step_map(outer["work_class"])[declaration["step"]].get("dispatch_gate")
            if gate and gate.get("kind") == "SOURCE_REQUIREMENTS":
                rows = [row for row in gate["validity_requirements"] if row["requirement_id"] == record["id"]]
                if record["id"] not in gate["requirements"] or len(rows) != 1:
                    errors.append("UNSUPPORTED_RELATION")
                else:
                    for key in ("not_before_field", "not_after_field"):
                        target = {"kind": "DECISION_FIELD", "requirement_id": name, "field": validity[key]}
                        own = {"kind": "OBSERVATION_FIELD", "requirement_id": record["id"], "field": rows[0][key]}
                        if not any(row["kind"] == "EQUALS" and ((row["left"] == target and row["right"] == own) or (row["right"] == target and row["left"] == own)) for row in record["relations"]):
                            errors.append("UNSUPPORTED_RELATION")
    return errors


def _phase_three(outer, contexts):
    from . import assessments, flow
    errors = []
    gate_requirement = outer["envelope"]["gate"].get("decision_requirement")
    if gate_requirement is not None and next(row for row in outer["envelope"]["decision_requirements"] if row["id"] == gate_requirement)["step"] != outer["proposal"]["step"]:
        errors.append("BINDING_MISMATCH")
    fields = {row["name"]: row["value"] for row in outer["proposal"]["fields"]}
    sources = {row["id"]: row for row in outer["envelope"].get("source_observation_requirements", [])}
    for name, context in contexts.items():
        declaration, leaf = context["declaration"], context["request"]
        if leaf["envelope"]["principal"] != declaration["principal"] or leaf["envelope"]["gate"]["role"] != declaration["role"]:
            errors.append("BINDING_MISMATCH")
        if leaf["clock"]["source"] != leaf["envelope"]["clock_source"]:
            errors.append("BINDING_MISMATCH")
        if {key: leaf["clock"][key] for key in ("status", "instant")} != {key: outer["clock"][key] for key in ("status", "instant")}:
            errors.append("BINDING_MISMATCH")
        values = {row["name"]: row["value"] for row in leaf["proposal"]["fields"]}
        for binding in declaration["context_bindings"]:
            selected = binding["value"]
            wanted = fields.get(selected["field"]) if selected["kind"] == "PROPOSAL_FIELD" else assessments.binding_value(outer, selected) if selected["kind"] == "ASSESSMENT" else flow.binding_value(outer, selected) if selected["kind"] == "FLOW_DISCLOSURE" else selected["value"]
            if values.get(binding["field"]) != wanted: errors.append("BINDING_MISMATCH")
        types = a._type_map(leaf["work_class"])
        validity = declaration["validity_fields"]
        for key, endpoint in (("not_before_field", "valid_from"), ("not_after_field", "valid_until")):
            value = values.get(validity[key], {})
            if value.get("type_ref") not in types or types[value["type_ref"]]["kind"] != "INSTANT" or value.get("value") != leaf["envelope"]["temporal_validity"][endpoint] or value.get("value") is None:
                errors.append("BINDING_MISMATCH")
        acts = [row for row in leaf["acts"] if row["kind"] == "INSTANCE_DECISION"]
        if len(acts) == 1:
            decision = acts[0]
            context["decision"] = decision
            if a.digest("authority-act", decision) != context["evidence"]["decision_act_digest"]:
                errors.append("BINDING_MISMATCH")
            if leaf["proposal"]["executor"] != {key: decision[key] for key in ("actor", "role", "principal", "occupancy")}:
                errors.append("BINDING_MISMATCH")
            record = sources[declaration["record_requirement_id"]]
            identity = values[declaration["identity_field"]]
            expected = a.canonical({"provider": record["provider"], "source": record["source"], "record_type": record["record_type"], "provider_record_id": decision["id"]}).decode()
            linked_assessment = next((row for row in assessments.requirements(outer) if row["review_decision_requirement_id"] == name), None)
            linked_id = next((row["review"]["id"] for row in outer.get("assessment_bases", []) if linked_assessment is not None and row["requirement_id"] == linked_assessment["id"]), None)
            if (types[identity["type_ref"]]["kind"] not in {"STRING", "IDENTITY"} or identity["value"] != expected
                    or linked_assessment is None and record["record_id"] != decision["id"]
                    or linked_assessment is not None and (record["record_id"] is not None or linked_id != decision["id"])):
                errors.append("BINDING_MISMATCH")
        if outer["envelope"]["gate"].get("decision_requirement") == name:
            gate = outer["envelope"]["gate"]
            if declaration["step"] != outer["proposal"]["step"] or declaration["principal"] != outer["envelope"]["principal"] or declaration["role"] != gate["role"]:
                errors.append("BINDING_MISMATCH")
            leaf_criteria = [row for row in leaf["envelope"]["gate"]["criteria"] if row["step"] == leaf["proposal"]["step"]]
            outer_criteria = [row for row in gate["criteria"] if row["step"] == outer["proposal"]["step"]]
            bindings = {row["field"]: row["value"] for row in declaration["context_bindings"]}
            translated = [{"id": row["id"], "step": outer["proposal"]["step"], "predicate": _translate(row["predicate"], bindings)} for row in leaf_criteria]
            if translated != outer_criteria: errors.append("BINDING_MISMATCH")
    return errors


def effective_until(context):
    request, selected = context["request"], context["acts"]["selected"]
    now = request["clock"]["instant"]
    root = request["host_selection"]["root"]
    ends = [request["envelope"]["temporal_validity"]["valid_until"]]
    if not root["prior_acts_survive_expiry"]: ends.append(root["validity"]["valid_until"])
    channels = {row["id"]: row for row in root["channels"]}
    for returned in context["acts"]["returns"].values():
        channel = channels[returned["channel"]]
        if not channel["prior_returns_survive_expiry"]: ends.append(channel["validity"]["valid_until"])
    capacities = {row["id"]: row for row in request["capacities"]}
    for act in selected:
        capacity = capacities[act["capacity"]]
        intervals = [capacity["validity"]]
        if capacity["reliance"]["kind"] == "SURVIVE_EXPIRY": intervals.append(capacity["reliance"]["validity"])
        intervals.sort(key=lambda row: row["valid_from"])
        merged = []
        for interval in intervals:
            if merged and (merged[-1]["valid_until"] is None or interval["valid_from"] <= merged[-1]["valid_until"]):
                previous = merged[-1]
                previous["valid_until"] = None if previous["valid_until"] is None or interval["valid_until"] is None else max(previous["valid_until"], interval["valid_until"])
            else: merged.append(copy.deepcopy(interval))
        current = next(row for row in merged if a._inside(row, a._instant(now)))
        ends.append(current["valid_until"])
    return min(row for row in ends if row is not None)


def evaluate(request, selected_pin):
    if not a._valid(request, "input"):
        return a._refusal("SCHEMA_INVALID")
    supplied = [(row["requirement_id"], {"request": row["evidence"]["authority_input"], "evidence": row["evidence"]}) for row in request.get("decision_bases", [])]
    contexts = dict(supplied)
    all_contexts = [{"request": request}, *(context for _, context in supplied)]
    errors = [a._phase_one(context["request"], "input" if index == 0 else "humanDecisionInput")[0] for index, context in enumerate(all_contexts)]
    errors.extend(code for context in all_contexts if (code := a._definition_static({"schema": a.AUTH_PREFIX + "authority-definition", **{key: context["request"][key] for key in ("source", "work_class", "envelope")}})) in {"TYPE_INVALID", "INPUT_INVALID"})
    errors += _known_bridges(request, supplied)
    names = [row["requirement_id"] for row in request.get("decision_bases", [])]
    if not a._ordered_unique(names, str.encode): errors.append("INPUT_INVALID")
    code = _first(1, errors)
    if code: return a._refusal(code)
    errors = []
    for context in all_contexts:
        own = context["request"]
        if own["specification_pin"] != selected_pin: errors.append("DEPENDENCY_MISMATCH")
        code, dependencies = a._phase_two(own, a.digest("authority-source", own["source"]), a.digest("authority-work-class", own["work_class"]), a.digest("authority-envelope", own["envelope"]))
        errors.append(code); context["dependencies"] = dependencies
    errors += _phase_two(request, contexts)
    code = _first(2, errors)
    if code: return a._refusal(code)
    errors = []
    for context in all_contexts:
        own, deps = context["request"], context["dependencies"]
        code, application = a._phase_three(own, own["work_class"], own["envelope"], deps["occupancies"])
        errors.append(code); context["application"] = application
        if application is not None: errors.append(a._select_credentials(own, deps, application["step"]))
    errors += _phase_three(request, contexts)
    code = _first(3, errors) or next((code for code in errors if code), None)
    if code: return a._refusal(code)
    from .authority_acts import evaluate_acts
    errors = []
    for context in all_contexts:
        own = context["request"]
        operation = a.digest("authority-operation", {"envelope_digest": a.digest("authority-envelope", own["envelope"]), "work_class_digest": a.digest("authority-work-class", own["work_class"]), "proposal_digest": a.digest("authority-proposal", own["proposal"])})
        context["acts"] = evaluate_acts(own, own["envelope"], context["dependencies"]["root"], own["proposal"], context["application"]["step"], a._parse_clock(own, own["envelope"]), operation)
        if context["acts"].get("status") == "REFUSED": errors.append(context["acts"]["code"])
        elif context is not all_contexts[0] and a.digest("authority-act", context["decision"]) != context["evidence"]["decision_act_digest"]: errors.append("ACT_NOT_AUTHORIZED")
    code = _first(4, errors)
    if code: return a._refusal(code)
    from . import assessments
    code = assessments.chronology_error(request, contexts)
    if code: return a._refusal(code)
    if a._parse_clock(request, request["envelope"]) is None: return a._refusal("AUTHORITY_NOT_ESTABLISHED", ["CLOCK_UNAVAILABLE"])
    results = []
    for name, context in contexts.items():
        result = a._policy_result(context["request"], selected_pin, context["dependencies"], context["application"], context["acts"], historical_signer=context["request"]["proposal"]["executor"])
        if result["status"] == "READY_FOR_RESERVATION":
            result.update(schema=a.AUTH_PREFIX + "human-decision-result", status="EVIDENCE_VALID", decision_act_digest=context["evidence"]["decision_act_digest"], effective_until=effective_until(context))
        context["result"] = result
        results.append({"requirement_id": name, "result": result, "result_digest": a.digest("authority-result", result)})
    result = a._policy_result(request, selected_pin, all_contexts[0]["dependencies"], all_contexts[0]["application"], all_contexts[0]["acts"], decision_contexts=contexts)
    admission = [row["result"]["code"] for row in results if row["result"].get("code") in {"DEPENDENCY_MISMATCH", "EVIDENCE_UNAVAILABLE"}]
    if result.get("code") in {"DEPENDENCY_MISMATCH", "EVIDENCE_UNAVAILABLE"}: admission.append(result["code"])
    code = _first(5, admission)
    if code:
        refused = a._refusal(code)
        if "decision_bases" in request: refused["decision_results"] = results
        return refused
    reasons, failed, checks = set(result.get("reasons", [])), list(result.get("failed_checks", [])), list(result.get("checks", []))
    for name, context in contexts.items():
        check = {"purpose": "HUMAN_DECISION", "subject_digest": context["evidence"]["decision_act_digest"], "requirement_ref": name, "at": request["clock"]["instant"]}
        if context["result"]["status"] != "EVIDENCE_VALID":
            reasons.add("DECISION_NOT_EFFECTIVE"); failed.append({**check, "reason": "DECISION_NOT_EFFECTIVE"})
        else: checks.append(check)
        for separation in context["declaration"]["distinct_from"]:
            actor = request["proposal"]["executor"]["actor"] if separation["kind"] == "EXECUTOR" else contexts[separation["requirement_id"]]["decision"]["actor"]
            check = {**check, "purpose": "SEPARATION"}
            if actor == context["decision"]["actor"]:
                reasons.add("DECISION_SEPARATION"); failed.append({**check, "reason": "DECISION_SEPARATION"})
            else: checks.append(check)
    if reasons: result = a._refusal("AUTHORITY_NOT_ESTABLISHED", reasons, failed)
    else: result["checks"] = sorted({a.canonical(row): row for row in checks}.values(), key=a.canonical)
    if "decision_bases" in request: result["decision_results"] = results
    return result


def selected_gate_bases(basis, result):
    name = basis["envelope"]["gate"].get("decision_requirement")
    if name is None: return []
    evidence = next(row["evidence"] for row in basis["decision_bases"] if row["requirement_id"] == name)
    checked = next(row["result"] for row in result["decision_results"] if row["requirement_id"] == name)
    if checked["status"] != "EVIDENCE_VALID": return []
    act = next(row for row in evidence["authority_input"]["acts"] if a.digest("authority-act", row) == checked["decision_act_digest"])
    return [{"act_digest": checked["decision_act_digest"], "act": act}]


def permit_actors(permit):
    basis = permit.get("authority_basis", {})
    return {act["actor"] for row in basis.get("decision_bases", []) for act in row["evidence"]["authority_input"]["acts"]}


def permit_act_bases(permit):
    return permit["authority_act_bases"] + selected_gate_bases(permit["authority_basis"], permit["authority_result"]) if "authority_basis" in permit else permit["authority_act_bases"]
