"""Exact content, immutable assessments, and attributable review bindings."""
from __future__ import annotations

from . import authority as a


MEMBERS = {"SUBJECT_DIGEST", "ASSESSMENT_DIGEST", "REVIEW_DIGEST", "REVIEW_IDENTITY"}
SINGULAR_ROLES = ("context_selection", "rubric", "evaluator", "assessment", "selection", "effectiveness")


def requirements(request):
    return [row for row in request["envelope"].get("assessment_requirements", []) if row["step"] == request["proposal"]["step"]]


def identity_exception(work, envelope, decision):
    rows = envelope.get("assessment_requirements", [])
    known = {row["id"]: row for row in rows}
    humans, steps = {row["id"]: row for row in envelope.get("decision_requirements", [])}, a._step_map(work)
    for binding in decision["context_bindings"]:
        if binding["value"]["kind"] != "ASSESSMENT":
            continue
        target = known.get(binding["value"]["requirement_id"])
        linked = humans.get(target["review_decision_requirement_id"]) if target is not None else None
        if target is None or target["step"] not in steps or linked is None or linked["step"] not in steps:
            return True
    if len(rows) != 1:
        return False
    row = rows[0]
    return (row["review_decision_requirement_id"] == decision["id"] == envelope["gate"].get("decision_requirement")
            and row["step"] == decision["step"])


def _ordered(values, key=str.encode):
    return a._ordered_unique(values, key)


def _equality(requirement, left, right):
    return any(row["kind"] == "EQUALS" and ((row["left"] == left and row["right"] == right)
               or (row["right"] == left and row["left"] == right)) for row in requirement["relations"])


def declaration_errors(work, envelope, source):
    errors = set()
    declared = envelope.get("assessment_requirements", [])
    types, steps = a._type_map(work), a._step_map(work)
    sources = {row["id"]: row for row in envelope.get("source_observation_requirements", [])}
    decisions = {row["id"]: row for row in envelope.get("decision_requirements", [])}
    obligations = {row["id"]: row for row in source["obligations"]}
    if not _ordered([row["id"] for row in declared]):
        errors.add("INPUT_INVALID")
    for row in declared:
        rubric, roles = row["rubric"], row["sources"]
        if (not _ordered([item["id"] for item in rubric["obligations"]])
                or not _ordered([item["id"] for item in rubric["criteria"]])
                or not _ordered(roles["context"]) or not _ordered(roles["blockers"])):
            errors.add("INPUT_INVALID")
        selected_obligations = {item["id"] for item in rubric["obligations"]}
        if any(item["id"] not in obligations for item in rubric["obligations"]):
            errors.add("REFERENCE_INVALID")
        if any(item["id"] in obligations and item != obligations[item["id"]] for item in rubric["obligations"]):
            errors.add("DEPENDENCY_MISMATCH")
        covered = set()
        for criterion in rubric["criteria"]:
            if not _ordered(criterion["obligation_ids"]):
                errors.add("INPUT_INVALID")
            if set(criterion["obligation_ids"]) - selected_obligations:
                errors.add("REFERENCE_INVALID")
            covered.update(criterion["obligation_ids"])
        if covered != selected_obligations:
            errors.add("REFERENCE_INVALID")
        step = steps.get(row["step"])
        human = decisions.get(row["review_decision_requirement_id"])
        if step is None or row["step"] not in {item["step"] for item in envelope["operations"]} or human is None:
            errors.add("REFERENCE_INVALID")
            continue
        if human["step"] != row["step"] or envelope["gate"]["kind"] != "DECIDE" or envelope["gate"].get("decision_requirement") != human["id"]:
            errors.add("UNSUPPORTED_RELATION")
        bindings = [item for item in human["context_bindings"] if item["value"]["kind"] == "ASSESSMENT"]
        known_targets = {item["id"] for item in declared}
        if not any(item["value"]["requirement_id"] not in known_targets for item in bindings):
            identities = [item["field"] for item in bindings if item["value"]["member"] == "REVIEW_IDENTITY"]
            if (len(bindings) != 4 or {item["value"]["member"] for item in bindings} != MEMBERS
                    or any(item["value"]["requirement_id"] != row["id"] for item in bindings)
                    or identities != [human["identity_field"]]):
                errors.add("UNSUPPORTED_RELATION")
        approval = sources.get(human["record_requirement_id"])
        if approval is None:
            errors.add("REFERENCE_INVALID")
        elif approval["record_id"] is not None:
            errors.add("UNSUPPORTED_RELATION")
        names = [roles["content"], *(roles[name]["requirement_id"] for name in SINGULAR_ROLES), *roles["context"], human["record_requirement_id"]]
        if len(names) != len(set(names)) or set(names) & set(roles["blockers"]):
            errors.add("UNSUPPORTED_RELATION")
        gate = step.get("dispatch_gate", {})
        if gate.get("kind") != "SOURCE_REQUIREMENTS":
            errors.add("UNSUPPORTED_RELATION")
        gate_names = set(gate.get("requirements", []))
        same_step = {item["id"] for item in sources.values() if item["step"] == row["step"]}
        if not same_step <= gate_names:
            errors.add("UNSUPPORTED_RELATION")
        for name in names + roles["blockers"]:
            requirement = sources.get(name)
            if requirement is None:
                errors.add("REFERENCE_INVALID")
                continue
            if (requirement["step"] != row["step"] or name not in gate_names or requirement["at"] != "CLOCK"
                    or requirement.get("evaluation_point") != "PROPOSE_AND_DISPATCH" or requirement["freshness_seconds"] != "0"
                    or name not in roles["blockers"] and requirement["expected_status"] != "AVAILABLE"):
                errors.add("UNSUPPORTED_RELATION")
        native = a._field_map(step)
        content = sources.get(roles["content"])
        if content is not None:
            fields = {item["name"]: item for item in content["fields"]}
            if set(fields) != set(native):
                errors.add("REFERENCE_INVALID")
            for name in set(fields) & set(native):
                if fields[name]["type_ref"] in types and native[name]["type_ref"] in types and fields[name]["type_ref"] != native[name]["type_ref"]:
                    errors.add("TYPE_INVALID")
                own = {"kind": "OBSERVATION_FIELD", "requirement_id": content["id"], "field": name}
                if not _equality(content, own, {"kind": "PROPOSAL_FIELD", "field": name}):
                    errors.add("UNSUPPORTED_RELATION")
        for name in [roles["content"], *roles["context"]]:
            requirement = sources.get(name)
            if requirement is None:
                continue
            allowed = set(roles["context"]) | ({name} if name == roles["content"] else set())
            for relation in requirement["relations"]:
                for operand in (relation["left"], relation["right"]):
                    if isinstance(operand, dict) and (operand["kind"] in {"ACT", "DECISION_ACT", "DECISION_FIELD", "DECISION_BASIS"}
                            or operand["kind"] in {"OBSERVATION_FIELD", "OBSERVATION_ID"} and operand["requirement_id"] not in allowed):
                        errors.add("UNSUPPORTED_RELATION")
        for name in SINGULAR_ROLES:
            mapping = roles[name]
            requirement = sources.get(mapping["requirement_id"])
            if requirement is None:
                continue
            fields = {item["name"]: item["type_ref"] for item in requirement["fields"]}
            for member, field in mapping.items():
                if member == "requirement_id":
                    continue
                if field not in fields or fields[field] not in types:
                    errors.add("REFERENCE_INVALID")
                elif types[fields[field]]["kind"] not in ({"BOOLEAN"} if member == "effective_field" else {"STRING", "IDENTITY"}):
                    errors.add("TYPE_INVALID")
            mapped = [value for key, value in mapping.items() if key != "requirement_id"]
            if name in {"evaluator", "selection", "effectiveness"} and len(mapped) != len(set(mapped)):
                errors.add("UNSUPPORTED_RELATION")
        digest_bindings = [item for item in human["context_bindings"] if item["value"]["kind"] == "ASSESSMENT" and item["value"]["member"] == "ASSESSMENT_DIGEST"]
        if len(digest_bindings) == 1:
            target = {"kind": "DECISION_FIELD", "requirement_id": human["id"], "field": digest_bindings[0]["field"]}
            for role in ("assessment", "selection"):
                mapping = roles[role]
                requirement = sources.get(mapping["requirement_id"])
                own = {"kind": "OBSERVATION_FIELD", "requirement_id": mapping["requirement_id"], "field": mapping["digest_field"]}
                if requirement is not None and not _equality(requirement, own, target):
                    errors.add("UNSUPPORTED_RELATION")
    return errors


def phase_one(request):
    errors = set()
    types = a._type_map(request["work_class"])
    sources = {row["id"]: row for row in request["envelope"].get("source_observation_requirements", [])}
    errors.update(declaration_errors(request["work_class"], request["envelope"], request["source"]) & {"TYPE_INVALID", "INPUT_INVALID"})
    bases = request.get("assessment_bases", [])
    if not _ordered([row["requirement_id"] for row in bases]):
        errors.add("INPUT_INVALID")
    for basis in bases:
        snapshots = basis["supporting_context"]
        if not _ordered([row["requirement_id"] for row in snapshots]):
            errors.add("INPUT_INVALID")
        for snapshot in snapshots:
            if not _ordered([row["name"] for row in snapshot["fields"]]):
                errors.add("INPUT_INVALID")
            declarations = {row["name"]: row["type_ref"] for row in sources.get(snapshot["requirement_id"], {}).get("fields", [])}
            for field in snapshot["fields"]:
                own, expected = field["value"]["type_ref"], declarations.get(field["name"])
                if own in types and expected in types and own != expected:
                    errors.add("TYPE_INVALID")
                if not a._typed_value_valid(field["value"], types):
                    errors.add("TYPE_INVALID")
        try:
            a._instant(basis["assessment"]["assessed_at"])
        except ValueError:
            errors.add("INPUT_INVALID")
        for key in ("assessment", "review"):
            if not _ordered([row["id"] for row in basis[key]["criteria"]]):
                errors.add("INPUT_INVALID")
            for criterion in basis[key]["criteria"]:
                if not _ordered(criterion["citations"], a.canonical):
                    errors.add("INPUT_INVALID")
                if key == "assessment" and criterion["escalation"]["required"] != (criterion["escalation"]["reason"] is not None):
                    errors.add("INPUT_INVALID")
    return errors


def phase_two(request):
    errors = set(declaration_errors(request["work_class"], request["envelope"], request["source"]))
    selected = {row["id"]: row for row in requirements(request)}
    bases = {row["requirement_id"]: row for row in request.get("assessment_bases", [])}
    if set(bases) - set(selected):
        errors.add("DEPENDENCY_MISMATCH")
    if set(selected) - set(bases):
        errors.add("EVIDENCE_UNAVAILABLE")
    sources = {row["id"]: row for row in request["envelope"].get("source_observation_requirements", [])}
    types = a._type_map(request["work_class"])
    proposal_fields = {row["name"] for row in request["proposal"]["fields"]}
    for name in set(selected) & set(bases):
        declaration, basis = selected[name], bases[name]
        snapshots = {row["requirement_id"]: row for row in basis["supporting_context"]}
        expected = set(declaration["sources"]["context"])
        if expected - set(snapshots): errors.add("EVIDENCE_UNAVAILABLE")
        if set(snapshots) - expected: errors.add("DEPENDENCY_MISMATCH")
        for snapshot in snapshots.values():
            requirement = sources.get(snapshot["requirement_id"])
            if requirement is None:
                continue
            fields = {row["name"] for row in snapshot["fields"]}
            expected_fields = {row["name"] for row in requirement["fields"]}
            if expected_fields - fields: errors.add("EVIDENCE_UNAVAILABLE")
            if fields - expected_fields: errors.add("REFERENCE_INVALID")
            if any(row["value"]["type_ref"] not in types for row in snapshot["fields"]): errors.add("REFERENCE_INVALID")
        criteria = {row["id"] for row in declaration["rubric"]["criteria"]}
        for key in ("assessment", "review"):
            supplied = {row["id"] for row in basis[key]["criteria"]}
            if criteria - supplied: errors.add("EVIDENCE_UNAVAILABLE")
            if supplied - criteria: errors.add("REFERENCE_INVALID")
            for criterion in basis[key]["criteria"]:
                for citation in criterion["citations"]:
                    if citation["kind"] == "PROPOSAL_FIELD":
                        if citation["field"] not in proposal_fields: errors.add("REFERENCE_INVALID")
                    else:
                        target = snapshots.get(citation["requirement_id"])
                        if citation["requirement_id"] not in expected or target is None or citation["field"] not in {row["name"] for row in target["fields"]}:
                            errors.add("REFERENCE_INVALID")
    if ("assessment_bases" in request or "assessment_requirements" in request["envelope"]) and len(a.canonical(request)) > 1048576:
        errors.add("LIMIT_EXCEEDED")
    return errors


def values(request, declaration, basis):
    source = {row["id"]: row for row in request["envelope"]["source_observation_requirements"]}
    records = [{"requirement_id": row["requirement_id"], **{key: source[row["requirement_id"]][key] for key in ("provider", "source", "record_type")},
                **{key: row[key] for key in ("provider_record_id", "provider_revision", "fields")}} for row in basis["supporting_context"]]
    context = a.digest("content-assessment-context", {"types": request["work_class"]["types"], "records": records})
    rubric = a.digest("content-assessment-rubric", declaration["rubric"])
    proposal = request["proposal"]
    subject = a.digest("content-assessment-subject", {"principal": proposal["executor"]["principal"],
        **{key: proposal[key] for key in ("work_class_digest", "instance", "occurrence", "step", "interface", "operation", "fields")},
        "context_digest": context, "rubric_digest": rubric, "evaluator": declaration["evaluator"]})
    human = next(row for row in request["envelope"]["decision_requirements"] if row["id"] == declaration["review_decision_requirement_id"])
    approval = source[human["record_requirement_id"]]
    identity = a.canonical({**{key: approval[key] for key in ("provider", "source", "record_type")}, "provider_record_id": basis["review"]["id"]}).decode()
    return {"context_digest": context, "rubric_digest": rubric, "SUBJECT_DIGEST": subject,
            "ASSESSMENT_DIGEST": a.digest("content-assessment", basis["assessment"]),
            "REVIEW_DIGEST": a.digest("content-assessment-review", basis["review"]), "REVIEW_IDENTITY": identity}


def binding_value(request, selector):
    declaration = next(row for row in requirements(request) if row["id"] == selector["requirement_id"])
    basis = next(row for row in request["assessment_bases"] if row["requirement_id"] == declaration["id"])
    return {"type_ref": selector["type_ref"], "value": values(request, declaration, basis)[selector["member"]]}


def phase_three(request):
    for declaration in requirements(request):
        basis = next(row for row in request["assessment_bases"] if row["requirement_id"] == declaration["id"])
        computed, assessment = values(request, declaration, basis), basis["assessment"]
        source = next(row for row in request["envelope"]["source_observation_requirements"] if row["id"] == declaration["sources"]["assessment"]["requirement_id"])
        if (assessment["subject_digest"] != computed["SUBJECT_DIGEST"] or assessment["context_digest"] != computed["context_digest"]
                or assessment["rubric_digest"] != computed["rubric_digest"] or assessment["evaluator"] != declaration["evaluator"]
                or any(assessment[key] != source[key] for key in ("provider", "source", "record_type"))
                or basis["review"]["assessment_digest"] != computed["ASSESSMENT_DIGEST"]):
            return "BINDING_MISMATCH"
        policies = {row["id"]: row["citation_policy"] for row in declaration["rubric"]["criteria"]}
        reviews = {row["id"]: row for row in basis["review"]["criteria"]}
        for criterion in assessment["criteria"]:
            review = reviews[criterion["id"]]
            if (criterion["verdict"] != "PASS" or criterion["escalation"]["required"] or review["disposition"] != "SATISFIED") and review["reason"] is None:
                return "BINDING_MISMATCH"
            allowed = {"CONTEXT_FIELD"} if policies[criterion["id"]] == "CONTEXT" else {"PROPOSAL_FIELD"} if policies[criterion["id"]] == "PROPOSAL" else {"CONTEXT_FIELD", "PROPOSAL_FIELD"}
            if any(row["kind"] not in allowed for row in criterion["citations"]):
                return "BINDING_MISMATCH"
    return None


def chronology_error(request, contexts):
    for declaration in requirements(request):
        basis = next(row for row in request["assessment_bases"] if row["requirement_id"] == declaration["id"])
        decision = contexts[declaration["review_decision_requirement_id"]]["decision"]
        if a._instant(basis["assessment"]["assessed_at"]) > a._instant(decision["occurred_at"]):
            return "BINDING_MISMATCH"
    return None


def policy(request, usable):
    reasons, failed, checks = set(), [], []
    for declaration in requirements(request):
        basis = next(row for row in request["assessment_bases"] if row["requirement_id"] == declaration["id"])
        computed, roles = values(request, declaration, basis), declaration["sources"]
        check = {"purpose": "ASSESSMENT", "subject_digest": computed["ASSESSMENT_DIGEST"], "requirement_ref": declaration["id"], "at": request["clock"]["instant"]}
        changed = False
        def matches(name, expected, metadata=None):
            observation = usable.get(name)
            if observation is None:
                return True
            fields = {row["name"]: row["value"]["value"] for row in observation["fields"]}
            return all(fields[field] == value for field, value in expected.items()) and (metadata is None or all(observation[key] == value for key, value in metadata.items()))
        for snapshot in basis["supporting_context"]:
            observation = usable.get(snapshot["requirement_id"])
            if observation is not None and (observation["provider_record_id"] != snapshot["provider_record_id"] or observation["revision"] != snapshot["provider_revision"]
                    or {row["name"]: row["value"] for row in observation["fields"]} != {row["name"]: row["value"] for row in snapshot["fields"]}):
                changed = True
        content = usable.get(roles["content"])
        if content is not None and {row["name"]: row["value"] for row in content["fields"]} != {row["name"]: row["value"] for row in request["proposal"]["fields"]}:
            changed = True
        for role, value in (("context_selection", computed["context_digest"]), ("rubric", computed["rubric_digest"]), ("assessment", computed["ASSESSMENT_DIGEST"])):
            mapping = roles[role]
            metadata = {"provider_record_id": basis["assessment"]["id"], "revision": basis["assessment"]["revision"]} if role == "assessment" else None
            changed |= not matches(mapping["requirement_id"], {mapping["digest_field"]: value}, metadata)
        mapping = roles["evaluator"]
        changed |= not matches(mapping["requirement_id"], {mapping[key + "_field"]: value for key, value in declaration["evaluator"].items()})
        identity = a.canonical({**{key: basis["assessment"][key] for key in ("provider", "source", "record_type")}, "provider_record_id": basis["assessment"]["id"]}).decode()
        mapping = roles["selection"]
        changed |= not matches(mapping["requirement_id"], {mapping["identity_field"]: identity, mapping["digest_field"]: computed["ASSESSMENT_DIGEST"]})
        mapping = roles["effectiveness"]
        changed |= not matches(mapping["requirement_id"], {mapping["identity_field"]: identity, mapping["effective_field"]: True})
        own_reasons = []
        if changed: own_reasons.append("ASSESSMENT_DEPENDENCY_CHANGED")
        if basis["review"]["decision"] != "APPROVE" or any(row["disposition"] != "SATISFIED" for row in basis["review"]["criteria"]):
            own_reasons.append("ASSESSMENT_NOT_SATISFIED")
        reasons.update(own_reasons)
        failed.extend({**check, "reason": reason} for reason in own_reasons)
        if not own_reasons: checks.append(check)
    return {"reasons": reasons, "failed": failed, "checks": checks}
