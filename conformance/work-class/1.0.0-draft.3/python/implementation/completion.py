"""Complete native completion, bounded lookup, and retained referral intents."""

from __future__ import annotations

import copy

from .common import PIN, PREFIX, Refusal, canonical, digest, utf8_sorted_unique, valid_instant


def terminal(step):
    return step.get("completion") is not None and step["completion"]["terminal_policy"] == "STOP_RETAIN"


def inventory(step):
    carrier = step["completion"]
    declared = {row["name"]: row["type_ref"] for row in step["fields"]}
    result = {row["evidence_field"]: declared[row["request_field"]] for row in carrier["evidence_bindings"]}
    result[carrier["status_field"]] = carrier["status_type_ref"]
    if carrier["route_label_field"] is not None:
        result[carrier["route_label_field"]] = carrier["route_label_type_ref"]
    if terminal(step):
        for member in ("provider_record_identity", "event_time_identity"):
            result[carrier[member]["field"]] = carrier[member]["type_ref"]
        result.update({row["name"]: row["value"]["type_ref"] for row in carrier["additional_fields"]})
        result.update({row["name"]: row["type_ref"] for row in carrier.get("generated_fields", [])})
        result.update({row["evidence_field"]: row["type_ref"] for row in carrier.get("authorization_revision_bindings", [])})
    return result


def type_refs(carrier):
    result = {carrier["status_type_ref"]}
    if carrier["route_label_type_ref"] is not None:
        result.add(carrier["route_label_type_ref"])
    if carrier["terminal_policy"] == "STOP_RETAIN":
        result.update(carrier[name]["type_ref"] for name in ("provider_record_identity", "event_time_identity"))
        result.update(row["value"]["type_ref"] for row in carrier["additional_fields"])
        result.update(row["type_ref"] for row in carrier.get("generated_fields", []))
        result.update(row["type_ref"] for row in carrier.get("authorization_revision_bindings", []))
        result.update(row["value"]["type_ref"] if "value" in row else row["type_ref"] for row in carrier["lookup"]["key_projection"])
    return result


def validate_step(step, types):
    from . import work_class

    for identifier in step.get("authority_type_refs", []):
        if identifier not in types:
            raise Refusal("REFERENCE_INVALID")
    if "authority_type_refs" in step and not utf8_sorted_unique(step["authority_type_refs"]):
        raise Refusal("DEFINITION_INVALID")
    routes = step.get("referral_policy", {})
    for category, rows in routes.items():
        if not utf8_sorted_unique([row["id"] for row in rows]):
            raise Refusal("DEFINITION_INVALID")
        if any(not utf8_sorted_unique(row["requirement_ids"]) or category == "completion" and row["requirement_ids"] for row in rows):
            raise Refusal("DEFINITION_INVALID")
    if not terminal(step):
        return
    carrier = step["completion"]
    if not type_refs(carrier) <= set(types):
        raise Refusal("REFERENCE_INVALID")
    if types[carrier["provider_record_identity"]["type_ref"]]["kind"] not in {"STRING", "IDENTITY"} or types[carrier["event_time_identity"]["type_ref"]]["kind"] != "INSTANT":
        raise Refusal("TYPE_INVALID")
    additional = carrier["additional_fields"]
    if not utf8_sorted_unique([row["name"] for row in additional]):
        raise Refusal("DEFINITION_INVALID")
    if any(not work_class._typed(row["value"], types) for row in additional):
        raise Refusal("TYPE_INVALID")
    generated = carrier.get("generated_fields", [])
    if not utf8_sorted_unique([row["name"] for row in generated]):
        raise Refusal("DEFINITION_INVALID")
    if len(generated) > 64:
        raise Refusal("LIMIT_EXCEEDED")
    names = [carrier["status_field"], carrier["provider_record_identity"]["field"], carrier["event_time_identity"]["field"]]
    names += [row["evidence_field"] for row in carrier["evidence_bindings"]] + [row["name"] for row in additional] + [row["name"] for row in generated]
    dynamic = carrier.get("authorization_revision_bindings", [])
    if not utf8_sorted_unique([row["evidence_field"] for row in dynamic]):
        raise Refusal("DEFINITION_INVALID")
    gate = step.get("dispatch_gate", {})
    gate_ids = gate.get("requirements", []) if gate.get("kind") == "SOURCE_REQUIREMENTS" else [gate.get("approval_requirement"), gate.get("withdrawal_requirement"), *gate.get("policy_withdrawal_requirements", [])]
    for binding in dynamic:
        if binding["requirement_id"] not in gate_ids: raise Refusal("REFERENCE_INVALID")
        if types[binding["type_ref"]]["kind"] not in {"STRING", "IDENTITY"}: raise Refusal("TYPE_INVALID")
    names += [row["evidence_field"] for row in dynamic]
    overlap = carrier.get("status_request_field")
    if overlap is not None:
        bound = [row for row in carrier["evidence_bindings"] if row["request_field"] == overlap and row["evidence_field"] == carrier["status_field"]]
        declared = {row["name"]: row for row in step["fields"]}
        if len(bound) != 1 or overlap not in declared or declared[overlap]["type_ref"] != carrier["status_type_ref"]:
            raise Refusal("DEFINITION_INVALID")
        names.remove(carrier["status_field"])
    if carrier["route_label_field"] is not None:
        names.append(carrier["route_label_field"])
    if len(names) > 66:
        raise Refusal("LIMIT_EXCEEDED")
    if len(names) != len(set(names)):
        raise Refusal("DEFINITION_INVALID")
    fields = {row["name"]: row for row in step["fields"]}
    key_names = []
    for projection in carrier["lookup"]["key_projection"]:
        key_names.append(projection.get("key_field", projection.get("field")))
        if "value" in projection:
            if not work_class._typed(projection["value"], types):
                raise Refusal("TYPE_INVALID")
        else:
            if projection["field"] not in fields:
                raise Refusal("REFERENCE_INVALID")
            if fields[projection["field"]]["type_ref"] != projection["type_ref"]:
                raise Refusal("TYPE_INVALID")
    if len(key_names) != len(set(key_names)):
        raise Refusal("DEFINITION_INVALID")
    from . import source_corrections
    source_corrections.validate_policy(step, types)


def validate_definition(definition):
    types = {row["id"]: row for row in definition["types"]}
    for step in definition["steps"]:
        validate_step(step, types)
    exits = definition.get("boundary_exits", [])
    if not utf8_sorted_unique([row["id"] for row in exits]) or any(not utf8_sorted_unique(row["reentry_requirements"]) for row in exits):
        raise Refusal("DEFINITION_INVALID")


def authorization_for_dispatch(state, permit, dispatch):
    rows = [row for row in state.get("authorizations", []) if row["authorization_digest"] == dispatch.get("authorization_digest")]
    if len(rows) != 1:
        raise Refusal("STATE_INVALID")
    authorization = rows[0]
    if authorization["permit_digest"] != permit["permit_id"] or dispatch["permit_digest"] != permit["permit_id"] or authorization["native_request"] != dispatch["native_request"] or authorization["native_request"] != permit["native_request"] or authorization["connector"] != dispatch["connector"]:
        raise Refusal("STATE_INVALID")
    return authorization


def fields(step, permit, evidence, types, authorization=None):
    from . import work_class

    carrier = step["completion"]
    actual = evidence["actual_fields"]
    values = {row["name"]: row["value"] for row in actual}
    if len(values) != len(actual) or any(not work_class._typed(row["value"], types) for row in actual):
        return "UNEXPECTED", None, False
    request = {row["name"]: row["value"] for row in permit["native_request"]["fields"]}
    expected = {row["evidence_field"]: request[row["request_field"]] for row in carrier["evidence_bindings"]}
    expected.update({row["name"]: row["value"] for row in carrier["additional_fields"]})
    for generated in carrier.get("generated_fields", []):
        value = values.get(generated["name"])
        if value is None or value["type_ref"] != generated["type_ref"]:
            return "UNEXPECTED", None, False
        expected[generated["name"]] = value
    for binding in carrier.get("authorization_revision_bindings", []):
        if authorization is None: raise Refusal("STATE_INVALID")
        sources = [row for row in authorization["authorization_fence"]["sources"] if row["requirement_id"] == binding["requirement_id"] and row["expected_status"] == "AVAILABLE"]
        if len(sources) != 1: raise Refusal("STATE_INVALID")
        expected[binding["evidence_field"]] = {"type_ref": binding["type_ref"], "value": sources[0]["provider_revision"]}
    identity = carrier["provider_record_identity"]
    event_time = carrier["event_time_identity"]
    if not evidence.get("provider_record_id") or not evidence.get("provider_revision"):
        return "UNEXPECTED", None, False
    expected[identity["field"]] = {"type_ref": identity["type_ref"], "value": evidence["provider_record_id"]}
    expected[event_time["field"]] = {"type_ref": event_time["type_ref"], "value": evidence["event_time"]}
    status = values.get(carrier["status_field"])
    if status is None or status["type_ref"] != carrier["status_type_ref"]:
        return "UNEXPECTED", None, False
    success = status in carrier["success_values"]
    failure = status in carrier["failure_values"]
    if "status_request_field" not in carrier:
        expected[carrier["status_field"]] = status
    label = None
    if success and carrier["route_label_field"] is not None:
        label = values.get(carrier["route_label_field"])
        if label is None or label["type_ref"] != carrier["route_label_type_ref"]:
            return "UNEXPECTED", None, False
        expected[carrier["route_label_field"]] = label
    if values != expected or not (success or failure):
        return "UNEXPECTED", None, False
    if evidence["collections"] and (step["kind"] != "FANOUT_EXPAND" or not success):
        return "UNEXPECTED", None, False
    return ("MATCHED" if success else "FAILED"), copy.deepcopy(label), True


def provider_identity(evidence):
    identifier = evidence.get("provider_record_id")
    if not identifier:
        return None
    return tuple(evidence[name] for name in ("provider", "source", "record_type")) + (identifier,)


def native_fact(evidence):
    return digest("native-evidence-fact", {name: value for name, value in evidence.items() if name not in {"evidence_id", "evidence_ref", "observed_at"}})


def query(state, step, permit, dispatch, clock):
    declaration = step["completion"]["lookup"]
    values = {row["name"]: row["value"] for row in permit["native_request"]["fields"]}
    key = [{"name": row.get("key_field", row.get("field")), "value": copy.deepcopy(row["value"] if "value" in row else values[row["field"]])} for row in declaration["key_projection"]]
    key.sort(key=lambda row: row["name"].encode())
    return {"instance_id": state["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"], "permit_digest": permit["permit_id"], "dispatch_digest": dispatch["dispatch_digest"], "authorization_digest": dispatch.get("authorization_digest"), **{name: declaration[name] for name in ("provider", "source", "record_type", "namespace")}, "key": key, "at": clock["observed_time"]}


def claim_only_allowed(state, definition, permit, dispatch):
    from . import dispatch_gate, lifecycle

    if not dispatch_gate.step_definition(definition, permit).get("dispatch_gate"):
        return False
    group = next(row for row in lifecycle._dispatch_attempt_groups(state, permit["permit_id"])
        if row["digest"] == dispatch["dispatch_attempt_digest"])
    first = group["records"][0]
    receipt = next(row for row in state["receipts"] if row["event_id"] == first["event_id"])
    if "LATE_OR_PROHIBITED_DISPATCH" not in receipt["reason_codes"]:
        return False
    authorization = next((row for row in state.get("authorizations", [])
        if row["authorization_digest"] == first.get("authorization_digest")), None)
    return not dispatch_gate.historical_authorization(state, permit, authorization,
        first["native_request"], first["connector"], first["attempt"]["attempted_at"], int(receipt["sequence"]))


def lookup_policy(state, definition, event, before_sequence=None):
    from . import dispatch_gate

    permit = next((row for row in state["permits"] if row["permit_id"] == event["permit"]["permit_id"]), None)
    if permit is None:
        raise Refusal("PREREQUISITE_MISSING")
    if permit != event["permit"]:
        raise Refusal("BINDING_MISMATCH")
    step = next(row for row in definition["steps"] if row["id"] == permit["occurrence"]["step_id"])
    if not terminal(step):
        raise Refusal("PREREQUISITE_MISSING")
    dispatch = next((row for row in state["dispatches"] if row["dispatch_digest"] == event["dispatch_digest"]), None)
    if dispatch is None:
        raise Refusal("BINDING_MISMATCH" if any(row["permit_digest"] == permit["permit_id"] for row in state["dispatches"]) else "PREREQUISITE_MISSING")
    if dispatch["permit_digest"] != permit["permit_id"] or dispatch.get("authorization_digest") != event["authorization_digest"] or dispatch["native_request"] != permit["native_request"]:
        raise Refusal("BINDING_MISMATCH")
    authorization = next((row for row in state.get("authorizations", []) if row["authorization_digest"] == event["authorization_digest"]), None)
    if step.get("dispatch_gate"):
        if not claim_only_allowed(state, definition, permit, dispatch) and (authorization is None or authorization["permit_digest"] != permit["permit_id"] or authorization["native_request"] != dispatch["native_request"] or authorization["connector"] != dispatch["connector"]):
            raise Refusal("BINDING_MISMATCH")
    elif "authorization_digest" in dispatch:
        if authorization is None or authorization["permit_digest"] != permit["permit_id"] or authorization["native_request"] != dispatch["native_request"] or authorization["connector"] != dispatch["connector"]:
            raise Refusal("BINDING_MISMATCH")
    elif event["authorization_digest"] is not None:
        raise Refusal("BINDING_MISMATCH")
    sequence = int(state["revision"]) + 1 if before_sequence is None else before_sequence
    receipts = {row["event_id"]: row for row in state["receipts"]}
    if int(receipts[dispatch["event_id"]]["sequence"]) >= sequence:
        raise Refusal("PREREQUISITE_MISSING")
    prior = lambda row: int(receipts[row["event_id"]]["sequence"]) < sequence
    occurrence_id = permit["occurrence"]["occurrence_id"]
    permits = {row["permit_id"]: row for row in state["permits"]}
    if dispatch["attempt"]["status"] == "NOT_SENT" and dispatch["acknowledgement"]["status"] != "ACCEPTED" or any(prior(row) and permits[row["permit_digest"]]["occurrence"]["occurrence_id"] == occurrence_id for row in state.get("completion_checks", [])) or any(row["permit_digest"] in permits and prior(row) and permits[row["permit_digest"]]["occurrence"]["occurrence_id"] == occurrence_id and row["native_evidence"]["status"] in {"EFFECT_ESTABLISHED", "NO_EFFECT_ESTABLISHED"} for row in state["outcomes"]):
        raise Refusal("PREREQUISITE_MISSING")
    clock = dispatch_gate.accepted_clock(state, permit["clock_source"], sequence, available_only=True)
    if clock is None or event["clock_revision"] != clock["revision"]:
        raise Refusal("CLOCK_INVALID")
    expected = query(state, step, permit, dispatch, clock)
    lookup = event["lookup"]
    if lookup["query"] != expected or lookup["query_digest"] != digest("completion-query", expected) or lookup["observed_at"] != expected["at"] or lookup["provenance_digest"] != digest("completion-lookup-provenance", {name: value for name, value in lookup.items() if name != "provenance_digest"}):
        raise Refusal("BINDING_MISMATCH")
    rows = lookup["candidates"]
    encoded = [canonical(row) for row in rows]
    identities = [provider_identity(row) for row in rows]
    if encoded != sorted(set(encoded)) or len(identities) != len(set(identities)) or any(any(row[name] != expected[name] for name in ("provider", "source", "record_type")) for row in rows):
        raise Refusal("BINDING_MISMATCH")
    if lookup["status"] != "UNAVAILABLE" and (not valid_instant(lookup["as_of"]) or lookup["as_of"] > expected["at"] or not lookup["provider_revision"]):
        raise Refusal("BINDING_MISMATCH")
    reason = {"NOT_FOUND": "UNKNOWN_OUTCOME", "UNAVAILABLE": "UNKNOWN_OUTCOME", "AMBIGUOUS": "COMPLETION_AMBIGUOUS", "OVERFLOW": "COMPLETION_OVERFLOW"}[lookup["status"]]
    reasons = [reason]
    if lookup["coverage"] == "INCOMPLETE":
        reasons.append("LOOKUP_INCOMPLETE")
    if lookup["as_of"] is not None and lookup["as_of"] < expected["at"]:
        reasons.append("LOOKUP_STALE")
    return permit, dispatch, step, sorted(reasons, key=str.encode), ("OUTCOME_UNKNOWN" if reason == "UNKNOWN_OUTCOME" else "BLOCKED_DISPUTE")


def checked(request):
    from . import lifecycle

    state = copy.deepcopy(request["state"])
    event = request["event"]
    permit, dispatch, step, reasons, occurrence_status = lookup_policy(state, request["definition"], event)
    if len(state["completion_checks"]) >= 128:
        raise Refusal("LIMIT_EXCEEDED")
    body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": permit["permit_id"], "authorization_digest": event["authorization_digest"], "dispatch_digest": dispatch["dispatch_digest"], "lookup": copy.deepcopy(event["lookup"]), "disposition": "COMPLETION_FAILED", "reason_codes": reasons}
    record = {"check_digest": digest("completion-check", body), **body}
    state["completion_checks"].append(record)
    state["completion_checks"].sort(key=lambda row: row["event_id"].encode())
    active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == permit["occurrence"]["occurrence_id"]), None)
    if active is not None and active["status"] != "BLOCKED_DISPUTE":
        active["status"] = occurrence_status
    state["status"] = "STOPPED"
    detail = {"kind": "COMPLETION_CHECK", "check_digest": record["check_digest"], "status": event["lookup"]["status"], "reasons": reasons}
    return lifecycle._finish(request, state, "COMPLETION_FAILED", reasons, [detail], permit_digest=permit["permit_id"], completion_check_digest=record["check_digest"])


def decision_basis(receipt, outcome=None, check=None):
    return {"instance_id": receipt["instance_id"], "event_id": receipt["event_id"], "event_digest": receipt["event_digest"], "disposition": receipt["disposition"], "reason_codes": copy.deepcopy(receipt["reason_codes"]), "permit_digest": receipt["permit_digest"], "authority_result_digest": receipt["authority_result_digest"], "outcome_digest": None if outcome is None else outcome["outcome_digest"], "completion_check_digest": None if check is None else check["check_digest"]}


def terminal_record(state, receipt, permit, dispatch, basis_digest, cause, occurrence_status, evidence):
    body = {"event_id": receipt["event_id"], "event_digest": receipt["event_digest"], "instance_id": state["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"], "permit_digest": permit["permit_id"], "authorization_digest": dispatch.get("authorization_digest"), "dispatch_digest": dispatch["dispatch_digest"], "decision_basis_digest": basis_digest, "cause": cause, "occurrence_status": occurrence_status, "evidence_digests": sorted(set(evidence), key=str.encode), "retained_reservation_bases": copy.deepcopy(permit["budget_revisions"])}
    return {"terminal_digest": digest("terminal-record", body), **body}


def referral_records(state, receipt, occurrence_id, routes, basis_digest, terminal_digest, cause_digest, evidence):
    result = []
    for route in routes:
        body = {"event_id": receipt["event_id"], "event_digest": receipt["event_digest"], "instance_id": state["instance_id"], "occurrence_id": occurrence_id, "decision_basis_digest": basis_digest, "terminal_digest": terminal_digest, "cause_digest": cause_digest, **{name: route[name] for name in ("destination_role", "queue", "purpose", "safe_state", "via_role")}, "evidence_digests": sorted(set(evidence), key=str.encode)}
        result.append({"referral_digest": digest("referral-intent", body), **body})
    return sorted({row["referral_digest"]: row for row in result}.values(), key=lambda row: row["referral_digest"].encode())


def failure_cause(outcome):
    return {"UNKNOWN": ("UNKNOWN_COMPLETION", "OUTCOME_UNKNOWN"), "UNEXPECTED": ("UNEXPECTED_COMPLETION", "BLOCKED_DISPUTE"), "CONFLICTING": ("CONFLICTING_COMPLETION", "BLOCKED_DISPUTE"), "FAILED": ("DECLARED_COMPLETION_FAILURE", "BLOCKED_DISPUTE"), "NO_EFFECT_ESTABLISHED": ("NO_EFFECT_COMPLETION", "BLOCKED_DISPUTE"), "LATE_AFTER_RELEASE": ("CONFLICTING_COMPLETION", "BLOCKED_DISPUTE")}.get(outcome["classification"])


def cause_evidence(state, outcome, check):
    if check is not None:
        return [check["check_digest"]]
    return [digest("native-evidence", outcome["native_evidence"])] + [digest("native-evidence", row["native_evidence"]) for row in state["outcomes"] if row["native_evidence"]["evidence_id"] in outcome["conflicts_with_evidence_ids"]]


def retain_decision(request, state, receipt):
    from . import timing
    event = request["event"]
    outcome = next((row for row in state["outcomes"] if row["event_id"] == event["event_id"]), None)
    check = next((row for row in state.get("completion_checks", []) if row["event_id"] == event["event_id"]), None)
    permit = next((row for row in state["permits"] if row["permit_id"] == receipt["permit_digest"]), None)
    if event["kind"] == "PROPOSE":
        occurrence_id = event["occurrence"]["occurrence_id"]
        occurrence = next(row["occurrence"] for row in state["active"] + state["completed"] if row["occurrence"]["occurrence_id"] == occurrence_id)
        step = next(row for row in request["definition"]["steps"] if row["id"] == occurrence["step_id"])
    elif permit is not None:
        occurrence_id = permit["occurrence"]["occurrence_id"]
        step = next(row for row in request["definition"]["steps"] if row["id"] == permit["occurrence"]["step_id"])
    else:
        return {}
    basis = decision_basis(receipt, outcome, check)
    basis_digest = digest("decision-basis", basis)
    extras = {}
    new_terminal = None
    routes = []
    evidence = []
    cause_digest = None
    authority_withheld = receipt["disposition"] == "WITHHELD" or receipt["disposition"] == "STOPPED" and "DEADLINE_TIME_OVERFLOW" in receipt["reason_codes"]
    if event["kind"] in {"PROPOSE", "AUTHORIZE_DISPATCH"} and authority_withheld and any(row["kind"] == "AUTHORITY" for row in receipt["details"]):
        result = event["authority_input"] if "authority_input" in event else None
        if event["kind"] == "PROPOSE":
            from . import authority
            result = authority.evaluate_authority(event["authority_input"], PIN)
            if timing.retain_evaluation(request["definition"], step["id"]):
                evaluations = state["proposal_authority_evaluations"]
                if len(evaluations) >= 128:
                    raise Refusal("LIMIT_EXCEEDED")
                evaluation = {"event": copy.deepcopy(event), "authority_result": copy.deepcopy(result), "authority_result_digest": digest("authority-result", result)}
                evaluation["evaluation_digest"] = digest("proposal-authority-evaluation", evaluation)
                evaluations.append(evaluation)
                evaluations.sort(key=lambda row: row["event"]["event_id"].encode())
                extras["proposal_authority_evaluation_digest"] = evaluation["evaluation_digest"]
                evidence.append(evaluation["evaluation_digest"])
        else:
            evaluation = next(row for row in state["authorization_evaluations"] if row["event_id"] == event["event_id"])
            result = evaluation["authority_result"]
            evidence.append(evaluation["evaluation_digest"])
        failed = {row["requirement_ref"] for row in result["failed_checks"] if row["purpose"] == "SOURCE_OBSERVATION"}
        routes = [row for row in step.get("referral_policy", {}).get("authority", []) if not row["requirement_ids"] or failed & set(row["requirement_ids"])]
        cause_digest = receipt["authority_result_digest"]
        evidence.append(cause_digest)
    elif permit is not None and terminal(step) and (check is not None or outcome is not None and failure_cause(outcome) is not None):
        if any(row["occurrence_id"] == occurrence_id for row in state["terminal_records"]):
            return {}
        cause, occurrence_status = ("COMPLETION_LOOKUP_FAILED", "OUTCOME_UNKNOWN" if "UNKNOWN_OUTCOME" in check["reason_codes"] else "BLOCKED_DISPUTE") if check is not None else failure_cause(outcome)
        current = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == occurrence_id), None)
        if current is not None and current["status"] == "BLOCKED_DISPUTE":
            occurrence_status = "BLOCKED_DISPUTE"
        dispatch = next(row for row in state["dispatches"] if row["dispatch_digest"] == (check or outcome)["dispatch_digest"])
        evidence = cause_evidence(state, outcome, check)
        new_terminal = terminal_record(state, receipt, permit, dispatch, basis_digest, cause, occurrence_status, evidence)
        routes = step.get("referral_policy", {}).get("completion", [])
        cause_digest = (check or outcome)["check_digest" if check is not None else "outcome_digest"]
    if new_terminal is None and not routes:
        return extras
    referrals = referral_records(state, receipt, occurrence_id, routes, basis_digest, None if new_terminal is None else new_terminal["terminal_digest"], cause_digest, evidence)
    if len(state.get("referrals", [])) + len(referrals) > 4096 or new_terminal is not None and len(state["terminal_records"]) >= 128:
        raise Refusal("LIMIT_EXCEEDED")
    extras["decision_basis_digest"] = basis_digest
    if new_terminal is not None:
        state["terminal_records"].append(new_terminal)
        state["terminal_records"].sort(key=lambda row: row["terminal_digest"].encode())
        extras["terminal_digest"] = new_terminal["terminal_digest"]
    if referrals:
        state["referrals"].extend(referrals)
        state["referrals"].sort(key=lambda row: row["referral_digest"].encode())
    return extras


def _native_integrity(state, definition, receipts, replays):
    from . import timing
    from . import lifecycle

    permits = {row["permit_id"]: row for row in state["permits"]}
    dispatches = {row["dispatch_digest"]: row for row in state["dispatches"]}
    steps = {row["id"]: row for row in definition["steps"]}
    rebuilt = []
    created = {}
    checkpoint = _prior_evidence(state, 1, definition)
    for retained in sorted(state["outcomes"], key=lambda row: int(receipts[row["event_id"]]["sequence"])):
        permit = permits.get(retained["permit_digest"])
        if permit is None or not terminal(steps[permit["occurrence"]["step_id"]]) and not timing.selected(definition):
            if "source_event" in retained:
                return None
            rebuilt.append(copy.deepcopy(retained))
            created[retained["event_id"]] = copy.deepcopy(retained)
            continue
        event = retained.get("source_event")
        receipt = receipts[retained["event_id"]]
        sequence = int(receipt["sequence"])
        evidence = retained["native_evidence"]
        dispatch = dispatches[retained["dispatch_digest"]]
        if (event is None or event["event_id"] != retained["event_id"] or event["instance_id"] != state["instance_id"]
                or event["expected_state_revision"] != str(sequence - 1) or event["expected_state_digest"] != receipt["state_before_digest"]
                or digest("runtime-event", event) != retained["event_digest"] or event["permit"] != permit
                or event["dispatch_digest"] != dispatch["dispatch_digest"] or event["native_evidence"] != evidence
                or int(receipts[dispatch["event_id"]]["sequence"]) >= sequence
                or not valid_instant(evidence["observed_at"]) or evidence["event_time"] is not None and not valid_instant(evidence["event_time"])):
            return None
        prior = _advance_evidence(checkpoint, state, definition, sequence) if checkpoint is not None else None
        if prior is None:
            prior = _prior_evidence(state, sequence, definition)
        prior["outcomes"] = sorted(copy.deepcopy(rebuilt), key=lambda row: row["outcome_digest"])
        if lifecycle.state_digest(prior) != receipt["state_before_digest"]:
            return None
        request = {"specification_pin": PIN, "definition": definition, "definition_digest": state["work_class_digest"], "profile": state["profile"], "role": state["role"], "state": prior, "state_digest": receipt["state_before_digest"], "event": event}
        result = lifecycle._effect_step(request)
        if result["decision"] != receipt or result["budget_results"] != replays[retained["event_id"]]["budget_results"]:
            return None
        rebuilt = copy.deepcopy(result["state"]["outcomes"])
        checkpoint = copy.deepcopy(result["state"])
        created[retained["event_id"]] = copy.deepcopy(next(row for row in rebuilt if row["event_id"] == retained["event_id"]))
    if sorted(rebuilt, key=lambda row: row["outcome_digest"]) != state["outcomes"]:
        return None
    return created


def _advance_evidence(checkpoint, state, definition, sequence):
    from . import lifecycle, timing

    prior = copy.deepcopy(checkpoint)
    replays = {row["event_id"]: row for row in state["replays"]}
    for receipt in state["receipts"]:
        index = int(receipt["sequence"])
        if not int(checkpoint["revision"]) < index < sequence:
            continue
        if lifecycle.state_digest(prior) != receipt["state_before_digest"]:
            return None
        event_id, kind = receipt["event_id"], receipt["event_kind"]
        if timing.selected(definition) and kind == "PROPOSE":
            evaluation = next((row for row in state.get("proposal_authority_evaluations", []) if row["event"]["event_id"] == event_id), None)
            if evaluation is not None:
                result = lifecycle._proposal_step(_replay_request(prior, definition, receipt, evaluation["event"]))
                if result["decision"] != receipt or result["budget_results"] != replays[event_id]["budget_results"]:
                    return None
                prior = result["state"]
                continue
        if kind == "DISPATCH_OBSERVED":
            dispatch = next(row for row in state["dispatches"] if row["event_id"] == event_id)
            permit = next(row for row in prior["permits"] if row["permit_id"] == dispatch["permit_digest"])
            event = {"schema": PREFIX + "runtime-event", "event_id": event_id, "kind": kind, "instance_id": state["instance_id"], "expected_state_revision": str(index - 1), "expected_state_digest": receipt["state_before_digest"], "permit": permit,
                     **{name: copy.deepcopy(dispatch[name]) for name in ("native_request", "connector", "attempt", "acknowledgement", "clock_revision")}}
            if "authorization_digest" in dispatch:
                event["authorization_digest"] = dispatch["authorization_digest"]
            if digest("runtime-event", event) != receipt["event_digest"]:
                return None
            result = lifecycle._dispatch_step(_replay_request(prior, definition, receipt, event))
            if result["decision"] != receipt or result["budget_results"] != replays[event_id]["budget_results"]:
                return None
            prior = result["state"]
            continue
        if kind == "CLOCK":
            detail = next(row for row in receipt["details"] if row["kind"] == "CLOCK")
            clock = next(row for row in state["clocks"] if row["source"] == detail["source"] and row["revision"] == detail["revision"])
            event = copy.deepcopy(next(row for row in state["timing_clock_events"] if row["event_id"] == event_id)) if timing.selected(definition) else _retained_event(state, receipt, definition)
            event["clock"] = copy.deepcopy(clock)
            if digest("runtime-event", event) != receipt["event_digest"]:
                return None
            result = lifecycle._clock_step(_replay_request(prior, definition, receipt, event))
            if result["decision"] != receipt or result["budget_results"] != replays[event_id]["budget_results"]:
                return None
            prior = result["state"]
            continue
        elif kind in {"DISPOSE", "APPLY_DISPOSITION"}:
            from . import recovery
            record = next(row for row in state.get("recovery_records", []) if row["event"]["event_id"] == event_id)
            request = _replay_request(prior, definition, receipt, record["event"])
            request["recovery_host"] = record["host_evidence"]
            if record.get("registry_selections"):
                request["recovery_registries"] = record["registry_selections"]
            result = recovery.lifecycle_step(request)
            if result["decision"] != receipt or result["budget_results"] != replays[event_id]["budget_results"]:
                return None
            prior = result["state"]
            continue
        elif kind == "PROPOSE":
            proposal = next(row for row in state["proposals"] if row["event_id"] == event_id)
            prior["proposals"].append(copy.deepcopy(proposal))
            prior["proposals"].sort(key=lambda row: row["event_id"].encode())
            if receipt["disposition"] == "PERMITTED":
                permit = replays[event_id]["permit"]
                prior["permits"].append(copy.deepcopy(permit))
                prior["permits"].sort(key=lambda row: row["permit_id"])
                active = next(row for row in prior["active"] if row["occurrence"]["occurrence_id"] == proposal["occurrence_id"])
                active["status"] = "PERMITTED"
                if proposal["prior_permit_digest"] is None:
                    counter = next(row for row in prior["step_counters"] if row["step_id"] == permit["occurrence"]["step_id"])
                    counter["actuations"] = str(int(counter["actuations"]) + 1)
                    prior["total_actuations"] = str(int(prior["total_actuations"]) + 1)
            elif receipt["disposition"] == "STOPPED":
                prior["status"] = "STOPPED"
            if "proposal_authority_evaluations" in prior:
                prior["proposal_authority_evaluations"].extend(copy.deepcopy([row for row in state["proposal_authority_evaluations"] if row["event"]["event_id"] == event_id]))
                prior["proposal_authority_evaluations"].sort(key=lambda row: row["event"]["event_id"].encode())
        elif kind == "AUTHORIZE_DISPATCH":
            for name, key in (("authorizations", "authorization_digest"), ("authorization_evaluations", "event_id")):
                prior[name].extend(copy.deepcopy([row for row in state[name] if row["event_id"] == event_id]))
                prior[name].sort(key=lambda row: row[key])
        elif kind == "COMPLETION_CHECKED":
            check = next(row for row in state["completion_checks"] if row["event_id"] == event_id)
            permit = next(row for row in state["permits"] if row["permit_id"] == check["permit_digest"])
            from . import dispatch_gate
            clock = dispatch_gate.accepted_clock(prior, permit["clock_source"], index, available_only=True)
            event = {"schema": PREFIX + "runtime-event", "event_id": event_id, "kind": kind, "instance_id": state["instance_id"], "expected_state_revision": str(index - 1), "expected_state_digest": receipt["state_before_digest"], "permit": permit, "authorization_digest": check["authorization_digest"], "dispatch_digest": check["dispatch_digest"], "lookup": check["lookup"], "clock_revision": clock["revision"]}
            if digest("runtime-event", event) != receipt["event_digest"]:
                return None
            result = checked(_replay_request(prior, definition, receipt, event))
            if result["decision"] != receipt or result["budget_results"] != replays[event_id]["budget_results"]:
                return None
            prior = result["state"]
            continue
        elif kind == "EFFECT_OBSERVED":
            outcome = next((row for row in state["outcomes"] if row["event_id"] == event_id), None)
            if outcome is None:
                detail = next(row for row in receipt["details"] if row["kind"] == "EFFECT")
                if detail["classification"] != "DUPLICATE" or not any(row["native_evidence"]["evidence_id"] == detail["evidence_id"] and row["permit_digest"] == receipt["permit_digest"] for row in prior["outcomes"]):
                    return None
                # Re-observing an existing evidence ID retains no new outcome or structural mutation.
                prior["revision"] = receipt["sequence"]
                core = copy.deepcopy(prior)
                core["receipts"] = []
                core["replays"] = []
                if digest("work-state-core", core) != receipt["state_after_core_digest"]:
                    return None
                prior["receipts"].append(copy.deepcopy(receipt))
                prior["replays"].append(copy.deepcopy(replays[event_id]))
                prior["replays"].sort(key=lambda row: row["event_id"].encode())
                continue
            event = outcome.get("source_event")
            if event is None:
                event = _retained_event(state, receipt, definition)
                permit = next((row for row in state["permits"] if row["permit_id"] == outcome["permit_digest"]), None)
                event.update(permit=permit, dispatch_digest=outcome["dispatch_digest"], native_evidence=outcome["native_evidence"], completion_authorization=None, budget_inputs=[], clock_revision=None)
            if digest("runtime-event", event) != receipt["event_digest"]:
                return None
            result = lifecycle._effect_step(_replay_request(prior, definition, receipt, event))
            if result["decision"] != receipt or result["budget_results"] != replays[event_id]["budget_results"]:
                return None
            prior = result["state"]
            continue
        else:
            return None
        if "referrals" in prior:
            prior["referrals"].extend(copy.deepcopy([row for row in state["referrals"] if row["event_id"] == event_id]))
            prior["referrals"].sort(key=lambda row: row["referral_digest"])
        prior["revision"] = receipt["sequence"]
        core = copy.deepcopy(prior)
        core["receipts"] = []
        core["replays"] = []
        if digest("work-state-core", core) != receipt["state_after_core_digest"]:
            return None
        prior["receipts"].append(copy.deepcopy(receipt))
        prior["replays"].append(copy.deepcopy(replays[event_id]))
        prior["replays"].sort(key=lambda row: row["event_id"].encode())
    return prior


def _retained_event(state, receipt, definition):
    activated = [row for row in state["deadlines"] if row["activation_revision"] == receipt["sequence"]]
    clocks = {(row["source"], row["activation_clock_revision"]) for row in activated}
    return {"schema": PREFIX + "runtime-event", "event_id": receipt["event_id"], "kind": receipt["event_kind"], "instance_id": state["instance_id"], "expected_state_revision": str(int(receipt["sequence"]) - 1), "expected_state_digest": receipt["state_before_digest"], "activation_clocks": sorted([copy.deepcopy(row) for row in state["clocks"] if (row["source"], row["revision"]) in clocks], key=lambda row: row["source"].encode())}


def _replay_request(state, definition, receipt, event):
    return {"specification_pin": PIN, "definition": definition, "definition_digest": state["work_class_digest"], "profile": state["profile"], "role": state["role"], "state": state, "state_digest": receipt["state_before_digest"], "event": event}


def _prior_evidence(state, sequence, definition):
    from . import dispatch_gate, lifecycle, recovery, timing

    if timing.selected(definition):
        initial = timing.initial_checkpoint(state, definition)
        if sequence == 1:
            return initial
        prior = _advance_evidence(initial, state, definition, sequence)
        if prior is None:
            raise Refusal("STATE_INVALID")
        return prior

    if state.get("recovery_records"):
        receipts = {row["event_id"]: row for row in state["receipts"]}
        target_recovery = next((row for row in state["recovery_records"]
                                if int(receipts[row["event"]["event_id"]]["sequence"]) == sequence), None)
        if target_recovery is not None:
            receipt = receipts[target_recovery["event"]["event_id"]]
            prior = recovery.checkpoint_before(state, target_recovery)
            if lifecycle.state_digest(prior) != receipt["state_before_digest"]:
                raise Refusal("STATE_INVALID")
            return prior

        earlier_recoveries = [row for row in state["recovery_records"]
                              if int(receipts[row["event"]["event_id"]]["sequence"]) < sequence]
        if earlier_recoveries:
            record = max(earlier_recoveries,
                         key=lambda row: int(receipts[row["event"]["event_id"]]["sequence"]))
            receipt = receipts[record["event"]["event_id"]]
            prior = recovery.checkpoint_before(state, record)
            if lifecycle.state_digest(prior) != receipt["state_before_digest"]:
                raise Refusal("STATE_INVALID")
            request = _replay_request(prior, definition, receipt, record["event"])
            request["recovery_host"] = record["host_evidence"]
            if record.get("registry_selections"):
                request["recovery_registries"] = record["registry_selections"]
            result = recovery.lifecycle_step(request)
            replay = next(row for row in state["replays"] if row["event_id"] == receipt["event_id"])
            reproduced = next((row for row in result["state"]["recovery_records"]
                               if row["event"]["event_id"] == receipt["event_id"]), None)
            if (result["decision"] != receipt or result["budget_results"] != replay["budget_results"]
                    or reproduced != record):
                raise Refusal("STATE_INVALID")
            prior = _advance_evidence(result["state"], state, definition, sequence)
            target = next((row for row in state["receipts"] if int(row["sequence"]) == sequence), None)
            if prior is None or target is not None and lifecycle.state_digest(prior) != target["state_before_digest"]:
                raise Refusal("STATE_INVALID")
            return prior

        if sequence > 1:
            prior = _advance_evidence(_prior_evidence(state, 1, definition), state, definition, sequence)
            if prior is not None:
                return prior
        state = copy.deepcopy(state)
        names = recovery.PROJECTION + tuple(name for name in ("event_duties", "deferred_deadlines") if name in state)
        for record in reversed(state["recovery_records"]):
            if int(receipts[record["event"]["event_id"]]["sequence"]) >= sequence:
                for name in names:
                    state[name] = copy.deepcopy(record["before_projection"][name])

    if sequence > 1 and not state.get("recovery_records"):
        disqualifying = {"NATIVE_ARGUMENT_MISMATCH", "PERMIT_EXPIRED", "PERMIT_SUPERSEDED", "LATE_OR_PROHIBITED_DISPATCH"}
        ordered_dispatch = any(row["event_kind"] == "DISPATCH_OBSERVED" and
            (row["disposition"] == "DISPUTED" or disqualifying & set(row["reason_codes"])) for row in state["receipts"])
        if ordered_dispatch:
            advanced = _advance_evidence(_prior_evidence(state, 1, definition), state, definition, sequence)
            if advanced is None:
                raise Refusal("STATE_INVALID")
            return advanced

    prior = copy.deepcopy(state)
    receipts = {row["event_id"]: row for row in state["receipts"]}
    before = lambda event_id: int(receipts[event_id]["sequence"]) < sequence
    prior["revision"] = str(sequence - 1)
    prior["receipts"] = [row for row in prior["receipts"] if before(row["event_id"])]
    prior["replays"] = [row for row in prior["replays"] if before(row["event_id"])]
    for name in ("proposals", "dispatches", "outcomes", "authorizations", "authorization_evaluations", "completion_checks", "terminal_records", "referrals"):
        if name in prior:
            prior[name] = [row for row in prior[name] if before(row["event_id"])]
    if "recovery_records" in prior:
        prior["recovery_records"] = [row for row in prior["recovery_records"] if before(row["event"]["event_id"])]
    if "proposal_authority_evaluations" in prior:
        prior["proposal_authority_evaluations"] = [row for row in prior["proposal_authority_evaluations"] if before(row["event"]["event_id"])]
    proposal_ids = {row["proposal_digest"] for row in prior["proposals"]}
    prior["permits"] = [row for row in prior["permits"] if row["proposal_digest"] in proposal_ids]
    clock_sequences = {(detail["source"], detail["revision"]): int(row["sequence"]) for row in state["receipts"] for detail in row["details"] if detail["kind"] == "CLOCK"}
    prior["clocks"] = [row for row in state["clocks"] if clock_sequences.get((row["source"], row["revision"]), 0) < sequence]
    native_digests = {digest("native-evidence", row["native_evidence"]) for row in prior["outcomes"]}
    clock_digests = {row["evidence_digest"] for row in prior["clocks"]}
    prior["completed"] = [row for row in prior["completed"] if row["evidence_digest"] in native_digests | clock_digests]
    completed_ids = {row["occurrence"]["occurrence_id"] for row in prior["completed"]}
    existing_active = {row["occurrence"]["occurrence_id"]: row for row in state["active"]}
    all_completed = {row["occurrence"]["occurrence_id"]: row for row in state["completed"]}
    digest_sequences = {row["event_digest"]: int(row["sequence"]) for row in state["receipts"]}
    prior["obligations"] = [row for row in prior["obligations"] if digest_sequences[row["creation_event_digest"]] < sequence]
    prior["fanout_passes"] = [row for row in prior["fanout_passes"] if any(outcome["permit_digest"] is not None and outcome["native_evidence"]["attributed_request"]["occurrence"] == row["expand_occurrence_id"] for outcome in prior["outcomes"])]
    active = []
    for occurrence in [row["occurrence"] for row in state["active"] + state["completed"]]:
        occurrence_id = occurrence["occurrence_id"]
        if occurrence_id in completed_ids:
            continue
        current = existing_active.get(occurrence_id)
        activation = current["activation_event_digest"] if current else None
        if not occurrence["predecessor_occurrence_ids"]:
            activation = digest("deployment-activation", {"deployment_authorization_digest": state["deployment_authorization_digest"], "instance_id": state["instance_id"], "occurrence_id": occurrence_id})
        elif activation is None:
            predecessors = [all_completed[value] for value in occurrence["predecessor_occurrence_ids"]]
            triggering = [row for row in state["outcomes"] if digest("native-evidence", row["native_evidence"]) in {row["evidence_digest"] for row in predecessors}]
            if triggering:
                activation = max(triggering, key=lambda row: int(receipts[row["event_id"]]["sequence"]))["event_digest"]
        if activation is None or digest_sequences.get(activation, 0) >= sequence:
            continue
        status = "ACTIVE"
        permits = [row for row in prior["permits"] if row["occurrence"]["occurrence_id"] == occurrence_id]
        if permits:
            status = "PERMITTED"
            permit_ids = {row["permit_id"] for row in permits}
            sent = [row for row in prior["dispatches"] if row["permit_digest"] in permit_ids and (row["attempt"]["status"] != "NOT_SENT" or row["acknowledgement"]["status"] == "ACCEPTED")]
            if sent:
                status = "DISPATCHED"
            unknown = [row for row in prior["outcomes"] if row["permit_digest"] in permit_ids]
            if unknown:
                status = "BLOCKED_DISPUTE" if any(row["classification"] in {"UNEXPECTED", "CONFLICTING", "FAILED", "LATE_AFTER_RELEASE"} for row in unknown) else "OUTCOME_UNKNOWN"
            terminal = next((row for row in prior.get("terminal_records", []) if row["occurrence_id"] == occurrence_id), None)
            if terminal is not None:
                status = terminal["occurrence_status"]
        active.append({"occurrence": copy.deepcopy(occurrence), "activation_event_digest": activation, "status": status, "deadline_ids": sorted(row["id"] for row in definition["deadlines"] if row["step_id"] == occurrence["step_id"])})
    prior["active"] = sorted(active, key=lambda row: canonical(row["occurrence"]))
    available_ids = completed_ids | {row["occurrence"]["occurrence_id"] for row in active}
    prior["deadlines"] = [row for row in prior["deadlines"] if row["occurrence_id"] in available_ids and int(row["activation_revision"]) < sequence]
    for deadline in prior["deadlines"]:
        if deadline["occurrence_id"] not in completed_ids:
            deadline["status"] = "PENDING"
            deadline["expiry_event_digest"] = None
    for counter in prior["step_counters"]:
        ids = {row["occurrence"]["occurrence_id"] for row in prior["active"] + prior["completed"] if row["occurrence"]["step_id"] == counter["step_id"]}
        counter["activations"] = str(len(ids))
        counter["actuations"] = str(sum(row["occurrence_id"] in ids and row["disposition"] == "PERMITTED" and row["prior_permit_digest"] is None for row in prior["proposals"]))
    prior["total_activations"] = str(sum(int(row["activations"]) for row in prior["step_counters"]))
    prior["total_actuations"] = str(sum(int(row["actuations"]) for row in prior["step_counters"]))
    prior["status"] = "STOPPED" if prior.get("terminal_records") or any(row["disposition"] == "STOPPED" for row in prior["receipts"]) else "ACTIVE" if active else "COMPLETE"
    if state.get("recovery_records"):
        receipt = next((row for row in state["receipts"] if int(row["sequence"]) == sequence), None)
        if receipt is not None:
            from . import lifecycle
            if lifecycle.state_digest(prior) != receipt["state_before_digest"]:
                raise Refusal("STATE_INVALID")
    return prior


def _proposal_integrity(state, definition, receipts):
    from . import authority, lifecycle, timing

    declared = timing.evaluation_carrier(definition)
    if declared != ("proposal_authority_evaluations" in state):
        return False
    rows = state.get("proposal_authority_evaluations", [])
    if not utf8_sorted_unique([row["event"]["event_id"] for row in rows]):
        return False
    proposal_steps = {row["event_id"]: next(value["occurrence"]["step_id"] for value in state["active"] + state["completed"] if value["occurrence"]["occurrence_id"] == row["occurrence_id"]) for row in state["proposals"]}
    expected_ids = {row["event_id"] for row in receipts.values() if row["event_kind"] == "PROPOSE" and timing.retain_evaluation(definition, proposal_steps[row["event_id"]]) and (row["disposition"] == "WITHHELD" or row["disposition"] == "STOPPED" and "DEADLINE_TIME_OVERFLOW" in row["reason_codes"]) and any(detail["kind"] == "AUTHORITY" for detail in row["details"])}
    if expected_ids != {row["event"]["event_id"] for row in rows}:
        return False
    occurrences = {row["occurrence"]["occurrence_id"]: row["occurrence"] for row in state["active"] + state["completed"]}
    proposals = {row["event_id"]: row for row in state["proposals"]}
    for row in rows:
        event = row["event"]
        receipt = receipts[event["event_id"]]
        sequence = int(receipt["sequence"])
        if (row["evaluation_digest"] != digest("proposal-authority-evaluation", {name: value for name, value in row.items() if name != "evaluation_digest"})
                or row["authority_result_digest"] != digest("authority-result", row["authority_result"])
                or row["authority_result_digest"] != receipt["authority_result_digest"] or row["evaluation_digest"] != receipt.get("proposal_authority_evaluation_digest")
                or event["instance_id"] != state["instance_id"] or event["expected_state_revision"] != str(sequence - 1) or event["expected_state_digest"] != receipt["state_before_digest"]
                or digest("runtime-event", event) != receipt["event_digest"] or digest("proposal", event) != proposals[event["event_id"]]["proposal_digest"]
                or event["occurrence"] != occurrences[proposals[event["event_id"]]["occurrence_id"]]):
            return False
        if authority.evaluate_authority(event["authority_input"], PIN) != row["authority_result"]:
            return False
        prior = _advance_evidence(_prior_evidence(state, 1, definition), state, definition, sequence)
        if prior is None:
            prior = _prior_evidence(state, sequence, definition)
        if lifecycle.state_digest(prior) != receipt["state_before_digest"]:
            return False
        clock = event["authority_input"]["clock"]
        if clock["status"] == "AVAILABLE" and not any(value["source"] == clock["source"] and value["status"] == "AVAILABLE" and value["revision"] == event["clock_revision"] and value["observed_time"] == clock["instant"] for value in prior["clocks"]):
            return False
        result = lifecycle._proposal_step({"definition": definition, "definition_digest": state["work_class_digest"], "profile": state["profile"], "role": state["role"], "state": prior, "state_digest": receipt["state_before_digest"], "event": event})
        evaluation = next(value for value in result["state"]["proposal_authority_evaluations"] if value["event"]["event_id"] == event["event_id"])
        if evaluation != row or any(result["decision"][name] != receipt[name] for name in ("disposition", "reason_codes", "details", "authority_result_digest")):
            return False
    return all((receipt["event_id"] in expected_ids) == ("proposal_authority_evaluation_digest" in receipt) for receipt in receipts.values())


def state_integrity(state, definition):
    try:
        return _state_integrity(state, definition)
    except (Refusal, KeyError, TypeError, ValueError, StopIteration, OverflowError, RuntimeError):
        return False


def _state_integrity(state, definition):
    from . import timing
    stopped_profile = any(terminal(row) for row in definition["steps"])
    referrals_profile = stopped_profile or any("referral_policy" in row for row in definition["steps"])
    required = ["completion_checks", "terminal_records"] if stopped_profile else []
    if referrals_profile:
        required.append("referrals")
    if any(name not in state for name in required):
        return False
    if not required and not any(state.get(name) for name in ("completion_checks", "terminal_records", "referrals")):
        if timing.selected(definition):
            receipts = {row["event_id"]: row for row in state["receipts"]}
            return _proposal_integrity(state, definition, receipts) and _native_integrity(state, definition, receipts, {row["event_id"]: row for row in state["replays"]}) is not None
        return "proposal_authority_evaluations" not in state and not any("source_event" in row for row in state["outcomes"])
    for name, key in (("completion_checks", "event_id"), ("terminal_records", "terminal_digest"), ("referrals", "referral_digest")):
        values = [row[key] for row in state.get(name, [])]
        if not utf8_sorted_unique(values):
            return False
    receipts = {row["event_id"]: row for row in state["receipts"]}
    if not _proposal_integrity(state, definition, receipts):
        return False
    replays = {row["event_id"]: row for row in state["replays"]}
    permits = {row["permit_id"]: row for row in state["permits"]}
    dispatches = {row["dispatch_digest"]: row for row in state["dispatches"]}
    checks = {row["event_id"]: row for row in state.get("completion_checks", [])}
    from . import dispatch_gate

    for check in checks.values():
        receipt = receipts[check["event_id"]]
        sequence = int(receipt["sequence"])
        permit = permits[check["permit_digest"]]
        clock = dispatch_gate.accepted_clock(state, permit["clock_source"], sequence, available_only=True)
        event = {"schema": PREFIX + "runtime-event", "event_id": check["event_id"], "kind": "COMPLETION_CHECKED", "instance_id": state["instance_id"], "expected_state_revision": str(sequence - 1), "expected_state_digest": receipt["state_before_digest"], "permit": permit, "authorization_digest": check["authorization_digest"], "dispatch_digest": check["dispatch_digest"], "lookup": check["lookup"], "clock_revision": clock["revision"]}
        _, _, _, reasons, _ = lookup_policy(state, definition, event, sequence)
        if check["check_digest"] != digest("completion-check", {name: value for name, value in check.items() if name != "check_digest"}) or check["event_digest"] != digest("runtime-event", event) or check["reason_codes"] != reasons or check["disposition"] != "COMPLETION_FAILED" or receipt.get("completion_check_digest") != check["check_digest"]:
            return False
    created = _native_integrity(state, definition, receipts, replays)
    if created is None:
        return False
    expected_terminals = []
    expected_referrals = []
    steps = {row["id"]: row for row in definition["steps"]}
    occurrences = {row["occurrence"]["occurrence_id"]: row["occurrence"] for row in state["active"] + state["completed"]}
    proposals = {row["event_id"]: row for row in state["proposals"]}
    for receipt in state["receipts"]:
        event_id = receipt["event_id"]
        outcome = created.get(event_id)
        check = checks.get(event_id)
        permit = permits.get(receipt["permit_digest"])
        basis_digest = digest("decision-basis", decision_basis(receipt, outcome, check))
        routes = []
        evidence = []
        cause_digest = None
        new_terminal = None
        authority_withheld = receipt["disposition"] == "WITHHELD" or receipt["disposition"] == "STOPPED" and "DEADLINE_TIME_OVERFLOW" in receipt["reason_codes"]
        if receipt["event_kind"] in {"PROPOSE", "AUTHORIZE_DISPATCH"} and authority_withheld and any(row["kind"] == "AUTHORITY" for row in receipt["details"]):
            occurrence_id = proposals[event_id]["occurrence_id"] if receipt["event_kind"] == "PROPOSE" else permit["occurrence"]["occurrence_id"]
            step = steps[occurrences[occurrence_id]["step_id"]]
            detail = next(row for row in receipt["details"] if row["kind"] == "AUTHORITY")
            failed = {row["requirement_ref"] for row in detail["failed_checks"] if row["purpose"] == "SOURCE_OBSERVATION"}
            routes = [row for row in step.get("referral_policy", {}).get("authority", []) if not row["requirement_ids"] or failed & set(row["requirement_ids"])]
            cause_digest = receipt["authority_result_digest"]
            evidence = [cause_digest]
            if receipt["event_kind"] == "PROPOSE" and "proposal_authority_evaluation_digest" in receipt:
                evidence.append(receipt["proposal_authority_evaluation_digest"])
            if receipt["event_kind"] == "AUTHORIZE_DISPATCH":
                evidence.append(receipt["authorization_evaluation_digest"])
        elif permit is not None and terminal(steps[permit["occurrence"]["step_id"]]) and (check is not None or outcome is not None and failure_cause(outcome) is not None):
            occurrence_id = permit["occurrence"]["occurrence_id"]
            step = steps[permit["occurrence"]["step_id"]]
            if not any(row["occurrence_id"] == occurrence_id for row in expected_terminals):
                cause, occurrence_status = ("COMPLETION_LOOKUP_FAILED", "OUTCOME_UNKNOWN" if "UNKNOWN_OUTCOME" in check["reason_codes"] else "BLOCKED_DISPUTE") if check is not None else failure_cause(outcome)
                prior = _prior_evidence(state, int(receipt["sequence"]), definition)
                if any(row["occurrence"]["occurrence_id"] == occurrence_id and row["status"] == "BLOCKED_DISPUTE" for row in prior["active"]):
                    occurrence_status = "BLOCKED_DISPUTE"
                dispatch = dispatches[(check or outcome)["dispatch_digest"]]
                evidence = cause_evidence(state, outcome, check)
                new_terminal = terminal_record(state, receipt, permit, dispatch, basis_digest, cause, occurrence_status, evidence)
                expected_terminals.append(new_terminal)
                routes = step.get("referral_policy", {}).get("completion", [])
                cause_digest = (check or outcome)["check_digest" if check is not None else "outcome_digest"]
        extras = new_terminal is not None or bool(routes)
        if (receipt.get("decision_basis_digest") != basis_digest if extras else "decision_basis_digest" in receipt) or (receipt.get("terminal_digest") != new_terminal["terminal_digest"] if new_terminal is not None else "terminal_digest" in receipt):
            return False
        if extras:
            expected_referrals.extend(referral_records(state, receipt, occurrence_id, routes, basis_digest, None if new_terminal is None else new_terminal["terminal_digest"], cause_digest, evidence))
        if check is None and "completion_check_digest" in receipt:
            return False
    if sorted(expected_terminals, key=lambda row: row["terminal_digest"]) != state.get("terminal_records", []) or sorted(expected_referrals, key=lambda row: row["referral_digest"]) != state.get("referrals", []):
        return False
    if expected_terminals:
        if state["status"] != "STOPPED":
            return False
        first_stop = min(int(receipts[row["event_id"]]["sequence"]) for row in expected_terminals)
        if any(int(receipts[row["event_id"]]["sequence"]) > first_stop for row in state["proposals"]):
            return False
        for record in expected_terminals:
            active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == record["occurrence_id"]), None)
            completed = next((row for row in state["completed"] if row["occurrence"]["occurrence_id"] == record["occurrence_id"]), None)
            if active is None and completed is None:
                return False
            if active is not None:
                if active["status"] not in {"OUTCOME_UNKNOWN", "BLOCKED_DISPUTE"} or record["occurrence_status"] == "BLOCKED_DISPUTE" and active["status"] != "BLOCKED_DISPUTE":
                    return False
            if completed is not None and completed["late"] and (completed["selected_relationship_digest"] is not None or completed["disposition"] != "SUCCEEDED"):
                return False
    return True
