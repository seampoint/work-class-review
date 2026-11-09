"""Typed source declarations, resolved queries, and actual relation checks."""

from __future__ import annotations

import copy

from .authority import NATURAL, _instant, _ordered_unique, _refusal, _typed_value_valid, canonical, digest


def selected_requirements(request):
    return [row for row in request["envelope"].get("source_observation_requirements", [])
            if row["step"] == request["proposal"]["step"]
            and (request.get("evaluation_point", "PROPOSE") == "PROPOSE"
                 or row.get("evaluation_point", "PROPOSE") == "PROPOSE_AND_DISPATCH")]


def source_query(requirement, request):
    query = {"requirement_id": requirement["id"], **{key: copy.deepcopy(requirement[key]) for key in
             ("step", "at", "provider", "source", "record_type", "subject", "record_id", "purpose", "freshness_seconds", "expected_status", "fields", "relations")}}
    fields = {row["name"]: row["value"] for row in request["proposal"]["fields"]}
    if query["at"] == "CLOCK":
        query["at"] = request["clock"]["instant"]
    subject = query["subject"]
    if isinstance(subject, dict):
        query["subject"] = fields[subject["field"]]["value"] if subject["kind"] == "PROPOSAL_FIELD" else request["proposal"]["executor"][subject["member"]]
    if not isinstance(query["subject"], str) or not query["subject"]:
        raise ValueError("subject")
    if "evaluation_point" in requirement:
        query["evaluation_point"] = requirement["evaluation_point"]
    if "key_projection" in requirement:
        query["key"] = sorted([{"name": row.get("key_field", row["field"]), "value": copy.deepcopy(fields[row["field"]])}
                               for row in requirement["key_projection"]], key=lambda row: row["name"].encode("utf-8"))
    return query


def declaration_admission(work_class, envelope):
    from . import human_decisions
    types = {row["id"]: row for row in work_class["types"]}
    steps = {row["id"]: row for row in work_class["steps"]}
    requirements = {row["id"]: row for row in envelope.get("source_observation_requirements", [])}
    edges = {name: set() for name in requirements}
    errors = set()
    errors.update(human_decisions.declaration_errors(work_class, envelope))
    decisions = {row["id"]: row for row in envelope.get("decision_requirements", [])}

    def error(code):
        errors.add(code)

    def explicit_type(type_ref, kinds):
        if type_ref not in types:
            error("REFERENCE_INVALID")
            return None
        if kinds is not None and types[type_ref]["kind"] not in kinds:
            error("TYPE_INVALID")
        return type_ref

    def field_type(fields, name):
        if name not in fields:
            error("REFERENCE_INVALID")
            return None
        return explicit_type(fields[name]["type_ref"], None)

    def operand_type(operand, requirement, fields):
        local = {row["name"]: row for row in requirement["fields"]}
        if isinstance(operand, str):
            return field_type(local, operand)
        kind = operand["kind"]
        if kind == "PROPOSAL_FIELD":
            return field_type(fields, operand["field"])
        if kind in {"EXECUTOR", "ACT", "CLOCK"}:
            kinds = {"INSTANT"} if kind == "CLOCK" or operand.get("member") == "occurred_at" else {"IDENTITY", "STRING"}
            return explicit_type(operand["type_ref"], kinds)
        if kind == "LITERAL":
            type_ref = explicit_type(operand["value"]["type_ref"], None)
            if not _typed_value_valid(operand["value"], types):
                error("TYPE_INVALID")
            return type_ref
        if kind in {"DECISION_ACT", "DECISION_FIELD", "DECISION_BASIS"}:
            target = decisions.get(operand["requirement_id"])
            if target is None or target["step"] != requirement["step"]:
                error("REFERENCE_INVALID")
                return None
            if kind == "DECISION_FIELD":
                try:
                    return explicit_type(human_decisions.binding_type(work_class, target, operand["field"]), None)
                except (KeyError, LookupError):
                    error("REFERENCE_INVALID")
                    return None
            return explicit_type(operand["type_ref"], {"INSTANT"} if operand.get("member") == "occurred_at" else {"IDENTITY", "STRING"})
        target = requirements.get(operand["requirement_id"])
        if target is None:
            error("REFERENCE_INVALID")
            return None
        if target["id"] != requirement["id"]:
            edges[requirement["id"]].add(target["id"])
        if (target["step"] != requirement["step"] or target["expected_status"] != "AVAILABLE"
                or requirement.get("evaluation_point", "PROPOSE") == "PROPOSE_AND_DISPATCH"
                and target.get("evaluation_point", "PROPOSE") != "PROPOSE_AND_DISPATCH"):
            error("UNSUPPORTED_RELATION")
        if kind == "OBSERVATION_ID":
            return explicit_type(operand["type_ref"], {"IDENTITY", "STRING"})
        return field_type({row["name"]: row for row in target["fields"]}, operand["field"])

    for step in steps.values():
        refs = step.get("authority_type_refs", [])
        if not _ordered_unique(refs, str.encode):
            error("INPUT_INVALID")
        for ref in refs:
            explicit_type(ref, None)
    counts = {}
    for requirement in requirements.values():
        step = steps.get(requirement["step"])
        if step is None:
            error("REFERENCE_INVALID")
            continue
        fields = {row["name"]: row for row in step["fields"]}
        counts[step["id"]] = counts.get(step["id"], 0) + len(requirement["relations"])
        if requirement["expected_status"] == "ABSENT":
            if requirement["fields"]:
                error("INPUT_INVALID")
            if requirement["relations"]:
                error("UNSUPPORTED_RELATION")
        for row in requirement["fields"]:
            explicit_type(row["type_ref"], None)
        subject = requirement["subject"]
        if isinstance(subject, dict):
            ref = field_type(fields, subject["field"]) if subject["kind"] == "PROPOSAL_FIELD" else explicit_type(subject["type_ref"], {"IDENTITY", "STRING"})
            if ref in types and types[ref]["kind"] not in {"IDENTITY", "STRING"}:
                error("TYPE_INVALID")
        projections = requirement.get("key_projection", [])
        if not _ordered_unique([row.get("key_field", row["field"]) for row in projections], str.encode):
            error("INPUT_INVALID")
        for row in projections:
            ref = field_type(fields, row["field"])
            explicit_type(row["type_ref"], None)
            if ref is not None and ref != row["type_ref"]:
                error("TYPE_INVALID")
        for relation in requirement["relations"]:
            left, right = (operand_type(relation[key], requirement, fields) for key in ("left", "right"))
            if relation["kind"] == "ELAPSED_LTE":
                maximum = relation.get("maximum_seconds")
                if not isinstance(maximum, str) or not NATURAL.fullmatch(maximum):
                    error("INPUT_INVALID")
                elif len(maximum) > 128:
                    error("LIMIT_EXCEEDED")
            if relation["kind"] == "INCLUDES":
                error("UNSUPPORTED_RELATION")
            elif left is not None and right is not None:
                if left != right or relation["kind"] not in {"EQUALS", "NOT_EQUALS"} and types[left]["kind"] != "INSTANT":
                    error("TYPE_INVALID")
    if any(value > 256 for value in counts.values()):
        error("LIMIT_EXCEEDED")
    visiting, visited = set(), set()
    def visit(name):
        if name in visiting:
            return False
        if name in visited:
            return True
        visiting.add(name)
        result = all(visit(target) for target in edges[name])
        visiting.remove(name)
        visited.add(name)
        return result
    if not all(visit(name) for name in edges):
        error("INPUT_INVALID")
    for step in steps.values():
        gate = step.get("dispatch_gate")
        if gate is None:
            continue
        vector = gate.get("kind") == "SOURCE_REQUIREMENTS"
        policies = gate["requirements"] if vector else gate["policy_withdrawal_requirements"]
        names = policies if vector else [gate["approval_requirement"], gate["withdrawal_requirement"], *policies]
        if not _ordered_unique(policies, str.encode) or len(names) != len(set(names)):
            error("INPUT_INVALID")
        if len(names) > 64:
            error("LIMIT_EXCEEDED")
        for name in names:
            requirement = requirements.get(name)
            if requirement is None:
                error("REFERENCE_INVALID")
                continue
            if (requirement["step"] != step["id"] or requirement["at"] != "CLOCK"
                    or requirement.get("evaluation_point") != "PROPOSE_AND_DISPATCH"
                    or requirement["freshness_seconds"] != "0"
                    or not vector and name == gate["approval_requirement"] and (requirement["purpose"] != "AUTHORITY" or requirement["expected_status"] != "AVAILABLE" or requirement["record_id"] is None)
                    or not vector and name != gate["approval_requirement"] and requirement["expected_status"] != "ABSENT"):
                error("UNSUPPORTED_RELATION")
        for binding in (step.get("completion") or {}).get("authorization_revision_bindings", []):
            target = requirements.get(binding["requirement_id"])
            if target is None:
                error("REFERENCE_INVALID")
            elif target["step"] != step["id"] or target["expected_status"] != "AVAILABLE":
                error("UNSUPPORTED_RELATION")
        if vector:
            coordinator = requirements.get(gate["coordinator_requirement"])
            if coordinator is None:
                error("REFERENCE_INVALID")
            elif coordinator["id"] not in names or coordinator["expected_status"] != "AVAILABLE" or (coordinator["provider"], coordinator["source"]) != (gate["fence_provider"], gate["fence_source"]):
                error("UNSUPPORTED_RELATION")
            if not _ordered_unique([row["requirement_id"] for row in gate["validity_requirements"]], str.encode):
                error("INPUT_INVALID")
            for row in gate["validity_requirements"]:
                target = requirements.get(row["requirement_id"])
                if target is None:
                    error("REFERENCE_INVALID")
                    continue
                if target["id"] not in names or target["expected_status"] != "AVAILABLE" or row["not_before_field"] == row["not_after_field"]:
                    error("UNSUPPORTED_RELATION")
                fields = {field["name"]: field for field in target["fields"]}
                for key in ("not_before_field", "not_after_field"):
                    ref = field_type(fields, row[key])
                    if ref is not None and types[ref]["kind"] != "INSTANT": error("TYPE_INVALID")
    return next((code for code in ("TYPE_INVALID", "INPUT_INVALID", "UNSUPPORTED_RELATION", "REFERENCE_INVALID", "LIMIT_EXCEEDED", "BINDING_MISMATCH") if code in errors), None)


def observe_source(request, envelope, selected_acts, *, decision_contexts=None):
    try:
        expected = {digest("authority-query", query): (requirement, query)
                    for requirement in selected_requirements(request) for query in [source_query(requirement, request)]}
    except (KeyError, ValueError):
        return _refusal("BINDING_MISMATCH")
    groups = {}
    for observation in request["observations"]:
        query = observation["query"]
        if "requirement_id" not in query:
            continue
        query_digest = observation["query_digest"]
        if query_digest != digest("authority-query", query) or query_digest not in expected:
            return _refusal("DEPENDENCY_MISMATCH")
        groups.setdefault(query_digest, {})[canonical(observation)] = observation
    if set(expected) - set(groups):
        return _refusal("EVIDENCE_UNAVAILABLE")
    reasons, failed, checks = set(), [], []
    usable = {}
    subject_digest = digest("authority-envelope", envelope)

    def fail(reason, requirement, query):
        reasons.add(reason)
        failed.append({"purpose": "SOURCE_OBSERVATION", "subject_digest": subject_digest,
                       "requirement_ref": requirement["id"], "at": query["at"], "reason": reason})

    for query_digest, (requirement, query) in expected.items():
        rows = list(groups[query_digest].values())
        if len(rows) != 1:
            fail("SOURCE_OBSERVATION_CONFLICT", requirement, query)
            continue
        observation = rows[0]
        if observation["status"] not in {"AVAILABLE", "ABSENT"}:
            fail("SOURCE_OBSERVATION_" + observation["status"], requirement, query)
            continue
        if (observation["status"] != requirement["expected_status"]
                or observation["status"] == "AVAILABLE" and requirement["record_id"] is not None and observation["provider_record_id"] != requirement["record_id"]):
            fail("SOURCE_OBSERVATION_BINDING", requirement, query)
        as_of, at, now = (_instant(value) for value in (observation["as_of"], query["at"], request["clock"]["instant"]))
        if not as_of <= at <= now:
            fail("SOURCE_OBSERVATION_TIME", requirement, query)
        if (at - as_of).total_seconds() > int(requirement["freshness_seconds"]):
            fail("SOURCE_OBSERVATION_STALE", requirement, query)
        fields = {row["name"]: row["value"] for row in observation["fields"]}
        declared = {row["name"]: row["type_ref"] for row in requirement["fields"]}
        if observation["status"] == "AVAILABLE":
            if len(fields) != len(observation["fields"]) or set(fields) != set(declared) or any(fields[name]["type_ref"] != ref for name, ref in declared.items() if name in fields):
                fail("SOURCE_OBSERVATION_FIELDS", requirement, query)
            if observation["relations"] != requirement["relations"]:
                fail("SOURCE_OBSERVATION_RELATIONS", requirement, query)
        if not any(row["requirement_ref"] == requirement["id"] for row in failed):
            usable[requirement["id"]] = observation

    assessment_values = dict(usable)
    proposal_fields = {row["name"]: row["value"] for row in request["proposal"]["fields"]}
    def operand_value(operand, requirement, observation):
        if isinstance(operand, str):
            return next(row["value"] for row in observation["fields"] if row["name"] == operand)
        kind = operand["kind"]
        if kind == "LITERAL":
            return operand["value"]
        if kind == "PROPOSAL_FIELD":
            return proposal_fields[operand["field"]]
        if kind == "EXECUTOR":
            value = request["proposal"]["executor"][operand["member"]]
        elif kind == "ACT":
            acts = [row for row in selected_acts if row["kind"] == operand["act_kind"]]
            if len(acts) != 1:
                raise ValueError("selected act")
            value = acts[0][operand["member"]]
        elif kind == "CLOCK":
            value = request["clock"]["instant"]
        elif kind in {"DECISION_ACT", "DECISION_FIELD", "DECISION_BASIS"}:
            target = decision_contexts[operand["requirement_id"]]
            if kind == "DECISION_FIELD":
                return next(row["value"] for row in target["request"]["proposal"]["fields"] if row["name"] == operand["field"])
            if kind == "DECISION_BASIS":
                from .human_decisions import reliance_subject
                value = reliance_subject(target["request"])
            else:
                value = digest("authority-act", target["decision"]) if operand["member"] == "digest" else target["decision"][operand["member"]]
        else:
            target = observation if operand["requirement_id"] == requirement["id"] else usable[operand["requirement_id"]]
            if target["status"] != "AVAILABLE":
                raise ValueError("unusable dependency")
            if kind == "OBSERVATION_FIELD":
                return next(row["value"] for row in target["fields"] if row["name"] == operand["field"])
            value = target["provider_record_id"]
        return {"type_ref": operand["type_ref"], "value": value}

    requirements = {requirement["id"]: (query_digest, requirement, query)
                    for query_digest, (requirement, query) in expected.items()}
    evaluated = set()

    def evaluate_relations(name):
        if name in evaluated:
            return
        query_digest, requirement, query = requirements[name]
        for relation in requirement["relations"]:
            for key in ("left", "right"):
                operand = relation[key]
                if isinstance(operand, dict) and operand["kind"] in {"OBSERVATION_FIELD", "OBSERVATION_ID"} and operand["requirement_id"] != name:
                    evaluate_relations(operand["requirement_id"])
        evaluated.add(name)
        rows = list(groups[query_digest].values())
        if len(rows) != 1 or rows[0]["status"] != "AVAILABLE":
            return
        observation = rows[0]
        step = next(row for row in request["work_class"]["steps"] if row["id"] == request["proposal"]["step"])
        gate = step.get("dispatch_gate", {})
        if gate.get("kind") == "SOURCE_REQUIREMENTS":
            for validity in gate["validity_requirements"]:
                if validity["requirement_id"] != name: continue
                try:
                    fields = {row["name"]: row["value"] for row in observation["fields"]}
                    begin = _instant(fields[validity["not_before_field"]]["value"])
                    end = _instant(fields[validity["not_after_field"]]["value"])
                    if not begin <= _instant(request["clock"]["instant"]) < end:
                        fail("SOURCE_OBSERVATION_TIME", requirement, query)
                        assessment_values.pop(name, None)
                except (KeyError, TypeError, ValueError):
                    fail("SOURCE_OBSERVATION_TIME", requirement, query)
                    assessment_values.pop(name, None)
        for relation in requirement["relations"]:
            try:
                left = operand_value(relation["left"], requirement, observation)
                right = operand_value(relation["right"], requirement, observation)
                valid = left["type_ref"] == right["type_ref"]
                kind = relation["kind"]
                if kind == "EQUALS":
                    valid = valid and canonical(left["value"]) == canonical(right["value"])
                elif kind == "NOT_EQUALS":
                    valid = valid and canonical(left["value"]) != canonical(right["value"])
                else:
                    a, b = _instant(left["value"]), _instant(right["value"])
                    if kind == "ELAPSED_LTE":
                        elapsed = b - a
                        seconds = elapsed.days * 86400 + elapsed.seconds
                        valid = valid and 0 <= seconds <= int(relation["maximum_seconds"])
                    else:
                        valid = valid and {"BEFORE": a < b, "AFTER": a > b, "AT_OR_BEFORE": a <= b, "AT_OR_AFTER": a >= b}.get(kind, False)
            except (KeyError, StopIteration, TypeError, ValueError):
                valid = False
            if not valid:
                fail("SOURCE_OBSERVATION_RELATIONS", requirement, query)
        if not any(row["requirement_ref"] == requirement["id"] for row in failed):
            checks.append({"purpose": "SOURCE_OBSERVATION", "subject_digest": subject_digest, "requirement_ref": requirement["id"], "at": query["at"]})
        else:
            usable.pop(requirement["id"], None)

    for name in requirements:
        evaluate_relations(name)
    for requirement, query in expected.values():
        if requirement["expected_status"] == "ABSENT" and not any(row["requirement_ref"] == requirement["id"] for row in failed):
            checks.append({"purpose": "SOURCE_OBSERVATION", "subject_digest": subject_digest, "requirement_ref": requirement["id"], "at": query["at"]})
    result = {"status": "OBSERVATIONS_DERIVED", "queries": [query for requirement, query in expected.values()], "reasons": reasons, "failed": failed, "checks": checks}
    if envelope.get("assessment_requirements"):
        result["assessment_values"] = assessment_values
    if envelope.get("flow_requirements"):
        result["flow_values"] = assessment_values
    return result
