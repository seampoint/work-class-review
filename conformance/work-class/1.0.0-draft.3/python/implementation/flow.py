"""Finite information provenance, exact disclosure and possible-exposure claims."""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar

from .common import PIN, PREFIX, Refusal, canonical, digest, schema_valid, utf8_sorted_unique
from .holdings import valid_instant


_VERIFIED = ContextVar("flow_verified_prefixes", default=None)


@contextmanager
def evaluation_scope():
    if _VERIFIED.get() is not None:
        yield
        return
    token = _VERIFIED.set(set())
    try:
        yield
    finally:
        _VERIFIED.reset(token)


def configuration_digest(configuration):
    return digest("flow-configuration", configuration)


def state_digest(state):
    return digest("flow-state", state) if state is not None else None


def _verified_key(configuration, state):
    return canonical({"configuration": configuration, "state": state})


def _remember(configuration, state):
    _VERIFIED.get().add(_verified_key(configuration, state))


def validate_configuration(configuration):
    if not schema_valid(configuration, "information-flow.schema.json", "configuration"):
        raise Refusal("SCHEMA_INVALID")
    if configuration["specification_pin"] != PIN:
        raise Refusal("VERSION_UNSUPPORTED")
    restrictions = configuration["restrictions"]
    if not utf8_sorted_unique([row["id"] for row in restrictions]):
        raise Refusal("INPUT_INVALID")
    if any(row["releasable"] != (row["release_role"] is not None) for row in restrictions):
        raise Refusal("DEFINITION_INVALID")


def control_subject(configuration, event):
    projected = copy.deepcopy(event)
    for name in ("access_authority", "transfer_authority"):
        projected["payload"].pop(name, None)
    return digest("flow-control-subject", {"configuration_digest": configuration_digest(configuration), "event": projected})


def response_subject(request):
    return digest("flow-response-subject", {"configuration_digest": configuration_digest(request["configuration"]),
        "state_digest": request["state_digest"], "event_id": request["event"]["id"],
        "event_digest": digest("flow-event", {"event": request["event"], "host_evidence": request["host_evidence"]}),
        "protected_channel": request["configuration"]["protected_channel"]})


def _no_budgets(request):
    return (not request["envelope"]["limits"]["shared_budgets"]
        and not request["work_class"].get("shared_budgets", [])
        and all(not row.get("shared_budgets", []) for row in request["work_class"]["steps"]))


def _evaluate(request):
    from . import authority
    if not _no_budgets(request):
        raise Refusal("UNSUPPORTED_RELATION")
    result = authority.evaluate_authority(request, PIN)
    if result["status"] != "READY_FOR_RESERVATION":
        raise Refusal("ACCESS_NOT_ESTABLISHED" if result["code"] == "AUTHORITY_NOT_ESTABLISHED" else result["code"])
    if result["required_budgets"]:
        raise Refusal("UNSUPPORTED_RELATION")
    return result


def _access(configuration, request, subject, operation, actor=None, clock=None, response=False):
    from . import authority as a
    from .human_decisions import ORDERS
    if len(canonical(request)) > 1048576:
        raise Refusal("LIMIT_EXCEEDED")
    result = a.evaluate_authority(request, PIN)
    if result["status"] == "REFUSED" and result["code"] in (*ORDERS[1], *ORDERS[2]):
        raise Refusal(result["code"])
    if request["envelope"].get("flow_requirements") or request.get("flow_bases"):
        raise Refusal("UNSUPPORTED_RELATION")
    if not _no_budgets(request):
        raise Refusal("UNSUPPORTED_RELATION")
    proposal, envelope = request["proposal"], request["envelope"]
    fields, types = proposal["fields"], a._type_map(request["work_class"])
    if (envelope["principal"] != configuration["principal"]
            or proposal["executor"]["principal"] != configuration["principal"]
            or proposal["interface"] != configuration["control_interface"] or proposal["operation"] != operation
            or actor is not None and proposal["executor"]["actor"] != actor
            or response and proposal["executor"]["role"] != configuration["response_role"]
            or clock is not None and request["clock"] != clock
            or request["clock"]["status"] != "AVAILABLE"
            or not valid_instant(request["clock"]["instant"])
            or len(fields) != 1 or fields[0]["name"] != "admission_subject"
            or fields[0]["value"]["value"] != subject):
        raise Refusal("BINDING_MISMATCH")
    ref = fields[0]["value"]["type_ref"]
    if ref not in types:
        raise Refusal("REFERENCE_INVALID")
    if types[ref]["kind"] not in {"STRING", "IDENTITY"}:
        raise Refusal("TYPE_INVALID")
    if result["status"] != "READY_FOR_RESERVATION":
        raise Refusal("ACCESS_NOT_ESTABLISHED" if result["code"] == "AUTHORITY_NOT_ESTABLISHED" else result["code"])
    if result["required_budgets"]:
        raise Refusal("UNSUPPORTED_RELATION")
    return result


def _host(configuration, event, host):
    if host["configuration_digest"] != configuration_digest(configuration) or host["event_subject_digest"] != control_subject(configuration, event):
        raise Refusal("DEPENDENCY_MISMATCH")
    expected = []
    kind, payload = event["kind"], event["payload"]
    if kind == "CREATE_CONTEXT":
        expected = [("INITIAL_INVENTORY", digest("flow-initial-inventory", payload))]
    elif kind == "READ":
        expected = [("SOURCE_CLASSIFICATION", digest("flow-source", payload["source"]))]
    elif kind == "MATERIALIZE":
        expected = [("MATERIALIZED_CONTENT", digest("flow-materialized-content", {key: payload[key] for key in ("types", "fields")}))]
    rows = host["attestations"]
    if [canonical(row) for row in rows] != sorted({canonical(row) for row in rows}):
        raise Refusal("INPUT_INVALID")
    if any((row["kind"], row["subject_digest"]) not in expected
            or (row["provider"], row["source"], row["channel"])
            != (configuration["provider"], configuration["source"], configuration["protected_channel"]) for row in rows):
        raise Refusal("DEPENDENCY_MISMATCH")
    if any(not any((row["kind"], row["subject_digest"]) == item for row in rows) for item in expected):
        raise Refusal("EVIDENCE_UNAVAILABLE")


def _restriction_set(configuration, identifiers, scope):
    if not utf8_sorted_unique(identifiers):
        raise Refusal("INPUT_INVALID")
    catalogue = {row["id"]: row for row in configuration["restrictions"]}
    if set(identifiers) - set(catalogue):
        raise Refusal("REFERENCE_INVALID")
    if any(catalogue[name]["scope"] != scope for name in identifiers):
        raise Refusal("DEPENDENCY_MISMATCH")


def _source(configuration, source, scope, state):
    if source["scope"] != scope:
        raise Refusal("DEPENDENCY_MISMATCH")
    _restriction_set(configuration, source["restrictions"], scope)
    coordinates = ("provider", "source", "record_type", "record_id", "revision", "scope")
    for context in state["core"]["contexts"]:
        for previous in context["origins"]:
            if all(source[name] == previous[name] for name in coordinates) and source != previous:
                raise Refusal("DEPENDENCY_MISMATCH")


def _native(types, fields):
    from . import authority as a
    if not utf8_sorted_unique([row["id"] for row in types]) or not utf8_sorted_unique([row["name"] for row in fields]):
        raise Refusal("INPUT_INVALID")
    table = {row["id"]: row for row in types}
    if any(row["value"]["type_ref"] not in table for row in fields):
        raise Refusal("REFERENCE_INVALID")
    if (any((row["kind"] in {"IDENTITY", "STRING", "BOOLEAN", "INSTANT"} and row["nonnegative"])
            or row["kind"] != "DECIMAL" and row["unit"] is not None for row in types)
            or any(not a._typed_value_valid(row["value"], table) for row in fields)):
        raise Refusal("TYPE_INVALID")
    if not a._finite_limits({"types": types, "fields": fields}, table):
        raise Refusal("LIMIT_EXCEEDED")


def _claim(payload, kind, context, configuration, subject):
    return {"id": payload["claim_id"], "intent_id": payload["intent_id"], "status": "POSSIBLE_EXPOSURE",
        "kind": kind, "context_id": context["id"], "recipient": context["id"], "channel": configuration["control_interface"],
        "purpose": context["purpose"], "subject_digest": subject, "release_act_digest": None}


def _apply(configuration, state, event, host):
    before = state_digest(state)
    revision = state["core"]["revision"] if state else "0"
    if state is None and event["kind"] != "CREATE_CONTEXT":
        raise Refusal("STATE_INVALID")
    if event["expected_revision"] != revision or event["expected_state_digest"] != before:
        raise Refusal("REVISION_CONFLICT")
    clock = event["clock"]
    if (clock["source"] != configuration["clock_source"] or clock["status"] != "AVAILABLE"
            or not valid_instant(clock["instant"]) or state and clock["instant"] < state["core"]["last_clock"]):
        raise Refusal("CLOCK_INVALID")
    _host(configuration, event, host)
    if state and len(state["records"]) >= 128:
        raise Refusal("LIMIT_EXCEEDED")
    core = copy.deepcopy(state["core"]) if state else {"configuration_digest": configuration_digest(configuration),
        "revision": "0", "last_clock": clock["instant"], "contexts": [], "artifacts": [], "claims": [], "consumed_release_acts": []}
    contexts = {row["id"]: row for row in core["contexts"]}
    artifacts = {row["id"]: row for row in core["artifacts"]}
    kind, payload, results = event["kind"], event["payload"], []
    claim = None
    if kind == "CREATE_CONTEXT":
        if payload["context_id"] in contexts:
            raise Refusal("DEFINITION_CONFLICT")
        _restriction_set(configuration, payload["ceiling"], payload["scope"])
        if payload["initial_sources"]:
            raise Refusal("UNSUPPORTED_RELATION")
        core["contexts"].append({"id": payload["context_id"], **{key: payload[key] for key in ("actor", "scope", "purpose", "ceiling")},
            "revision": "1", "restrictions": [], "origins": []})
        decision = "CONTEXT_CREATED"
    elif kind in {"READ", "IMPORT", "MATERIALIZE"}:
        context = contexts.get(payload["receiver_context_id"] if kind == "IMPORT" else payload["context_id"])
        if context is None:
            raise Refusal("DEPENDENCY_MISMATCH")
        if kind in {"READ", "IMPORT"}:
            if any(row["id"] == payload["claim_id"] or row["intent_id"] == payload["intent_id"] for row in core["claims"]):
                raise Refusal("DEPENDENCY_MISMATCH")
            if kind == "READ":
                _source(configuration, payload["source"], context["scope"], state)
                incoming = payload["source"]["restrictions"]
                origins = [payload["source"]]
            else:
                sender, artifact = contexts.get(payload["sender_context_id"]), artifacts.get(payload["artifact_id"])
                if sender is None or artifact is None or artifact["context_id"] != sender["id"] or sender["scope"] != context["scope"]:
                    raise Refusal("DEPENDENCY_MISMATCH")
                incoming = sorted(set(sender["restrictions"]) | set(artifact["restrictions"]), key=str.encode)
                origins = sender["origins"] + artifact["origins"]
            union = sorted(set(context["restrictions"]) | set(incoming), key=str.encode)
            if set(union) - set(context["ceiling"]):
                raise Refusal("ACCESS_NOT_ESTABLISHED")
            subject = control_subject(configuration, event)
            results.append(_access(configuration, payload["access_authority"], subject, configuration["access_operation"], context["actor"], clock))
            if kind == "IMPORT":
                results.append(_access(configuration, payload["transfer_authority"], subject, configuration["transfer_operation"], sender["actor"], clock))
            context["restrictions"] = union
            all_origins = {digest("flow-source", row): row for row in context["origins"] + origins}
            context["origins"] = [copy.deepcopy(all_origins[name]) for name in sorted(all_origins, key=str.encode)]
            context["revision"] = str(int(context["revision"]) + 1)
            claim = _claim(payload, kind, context, configuration, subject)
            decision = "READ_RECORDED" if kind == "READ" else "IMPORT_RECORDED"
        else:
            if payload["artifact_id"] in artifacts:
                raise Refusal("DEPENDENCY_MISMATCH")
            if context["revision"] == "1":
                raise Refusal("ACCESS_NOT_ESTABLISHED")
            _native(payload["types"], payload["fields"])
            core["artifacts"].append({"id": payload["artifact_id"], "context_id": context["id"],
                "context_revision": context["revision"], "context_digest": digest("flow-context", context),
                **{key: copy.deepcopy(payload[key]) for key in ("types", "fields")},
                **{key: copy.deepcopy(context[key]) for key in ("restrictions", "origins")}})
            decision = "ARTIFACT_RECORDED"
    else:
        outgoing = copy.deepcopy(payload["authority_projection"])
        basis = outgoing["flow_bases"][0]
        if (state is None or basis["configuration"] != configuration or basis["state_digest"] != before
                or basis["requirement_id"] != payload["requirement_id"]):
            raise Refusal("DEPENDENCY_MISMATCH")
        if outgoing["clock"] != clock:
            raise Refusal("BINDING_MISMATCH")
        basis["state"] = copy.deepcopy(state)
        results.append(_evaluate(outgoing))
        declaration = next(row for row in requirements(outgoing) if row["id"] == payload["requirement_id"])
        values = disclosure_values(outgoing, declaration, basis)
        release = release_act(outgoing, declaration)
        claim = {"id": declaration["claim_id"], "intent_id": declaration["intent_id"], "status": "POSSIBLE_EXPOSURE",
            "kind": "EXPOSE", "context_id": declaration["context_id"], "recipient": values["recipient"],
            "channel": declaration["channel"], "purpose": declaration["purpose"], "subject_digest": values["subject_digest"],
            "release_act_digest": digest("authority-act", release) if release is not None else None}
        if claim["release_act_digest"] is not None:
            core["consumed_release_acts"].append(claim["release_act_digest"])
        decision = "EXPOSURE_RECORDED"
    if claim is not None:
        core["claims"].append(claim)
    if (len(core["contexts"]) > 16 or len(core["artifacts"]) > 64 or len(core["claims"]) > 128
            or any(len(row["origins"]) > 64 for row in core["contexts"])):
        raise Refusal("LIMIT_EXCEEDED")
    for name in ("contexts", "artifacts", "claims"):
        core[name].sort(key=lambda row: row["id"].encode())
    core["consumed_release_acts"].sort(key=str.encode)
    core.update(revision=str(int(revision) + 1), last_clock=clock["instant"])
    event_digest = digest("flow-event", {"event": event, "host_evidence": host})
    receipt = {"schema": PREFIX + "flow-receipt", "event_id": event["id"], "event_digest": event_digest,
        "state_before_digest": before, "revision": core["revision"], "core_after_digest": digest("flow-core", core),
        "decision": decision, "authority_result_digests": [digest("authority-result", row) for row in results],
        "authority_evidence_digests": [row["evidence_digest"] for row in results], "protected_channel": configuration["protected_channel"]}
    record = {"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(host), "event_digest": event_digest,
        "receipt": receipt, "receipt_digest": digest("flow-receipt", receipt)}
    next_state = {"schema": PREFIX + "flow-state", "specification_pin": PIN, "core": core,
        "records": [*(copy.deepcopy(state["records"]) if state else []), record]}
    if len(canonical(next_state)) > 16777216:
        raise Refusal("LIMIT_EXCEEDED")
    return {"status": "TRANSITION", "receipt": receipt, "receipt_digest": record["receipt_digest"],
        "state": next_state, "state_digest": state_digest(next_state), "replay": False}


def validate_state(configuration, state, supplied_digest):
    with evaluation_scope():
        if state_digest(state) != supplied_digest:
            raise Refusal("DIGEST_MISMATCH")
        if state is None:
            _remember(configuration, state)
            return
        if not schema_valid(state, "information-flow.schema.json", "state"):
            raise Refusal("SCHEMA_INVALID")
        if len(canonical(state)) > 16777216:
            raise Refusal("LIMIT_EXCEEDED")
        if state["specification_pin"] != PIN:
            raise Refusal("VERSION_UNSUPPORTED")
        if state["core"]["configuration_digest"] != configuration_digest(configuration):
            raise Refusal("DEPENDENCY_MISMATCH")
        if _verified_key(configuration, state) in _VERIFIED.get():
            return
        rebuilt, ids = None, set()
        try:
            for record in state["records"]:
                if record["event"]["id"] in ids:
                    raise Refusal("STATE_INVALID")
                ids.add(record["event"]["id"])
                _remember(configuration, rebuilt)
                result = _apply(configuration, rebuilt, record["event"], record["host_evidence"])
                if result["state"]["records"][-1] != record:
                    raise Refusal("STATE_INVALID")
                rebuilt = result["state"]
            if rebuilt != state:
                raise Refusal("STATE_INVALID")
        except (Refusal, KeyError, StopIteration, TypeError, ValueError):
            raise Refusal("STATE_INVALID") from None
        _remember(configuration, state)


def admit_input(request):
    if not schema_valid(request, "information-flow.schema.json", "input"):
        raise Refusal("SCHEMA_INVALID")
    try:
        size = len(canonical(request))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise Refusal("SCHEMA_INVALID") from None
    if size > 16777216:
        raise Refusal("LIMIT_EXCEEDED")


def transition(request):
    try:
        admit_input(request)
    except Refusal as error:
        return {"status": "REFUSED", "code": error.code, "path": ""}
    with evaluation_scope():
        try:
            _access(request["configuration"], request["response_authority"], response_subject(request),
                request["configuration"]["response_operation"], response=True)
        except Refusal as error:
            return {"status": "REFUSED", "code": error.code, "path": ""}
        try:
            if request["specification_pin"] != PIN:
                raise Refusal("VERSION_UNSUPPORTED")
            configuration, state, event, host = (request[name] for name in ("configuration", "state", "event", "host_evidence"))
            validate_configuration(configuration)
            validate_state(configuration, state, request["state_digest"])
            if state:
                previous = next((row for row in state["records"] if row["event"]["id"] == event["id"]), None)
                if previous:
                    if previous["event"] != event or previous["host_evidence"] != host:
                        raise Refusal("REPLAY_CONFLICT")
                    return {"status": "TRANSITION", "receipt": copy.deepcopy(previous["receipt"]),
                        "receipt_digest": previous["receipt_digest"], "state": copy.deepcopy(state),
                        "state_digest": request["state_digest"], "replay": True}
            return _apply(configuration, state, event, host)
        except Refusal as error:
            return {"status": "REFUSED", "code": error.code, "path": "", "state": copy.deepcopy(request["state"]), "state_digest": request["state_digest"]}


def requirements(request):
    return [row for row in request["envelope"].get("flow_requirements", []) if row["step"] == request["proposal"]["step"]]


def declaration_errors(work, envelope):
    from . import authority as a
    errors = set()
    rows = envelope.get("flow_requirements", [])
    if not utf8_sorted_unique([row["id"] for row in rows]):
        errors.add("INPUT_INVALID")
    steps, types = a._step_map(work), a._type_map(work)
    sources = {row["id"]: row for row in envelope.get("source_observation_requirements", [])}
    humans = {row["id"]: row for row in envelope.get("decision_requirements", [])}
    for row in rows:
        step = steps.get(row["step"])
        if step is None or row["step"] not in {item["step"] for item in envelope["operations"]}:
            errors.add("REFERENCE_INVALID")
            continue
        native = a._field_map(step)
        if row["recipient_field"] not in native:
            errors.add("REFERENCE_INVALID")
        elif native[row["recipient_field"]]["type_ref"] in types and types[native[row["recipient_field"]]["type_ref"]]["kind"] not in {"STRING", "IDENTITY"}:
            errors.add("TYPE_INVALID")
        if row["policy"]["configuration_digest"] != row["configuration_digest"]:
            errors.add("DEPENDENCY_MISMATCH")
        for name in ("entitlements", "release_rules"):
            encoded = [canonical(item) for item in row["policy"][name]]
            if encoded != sorted(set(encoded)):
                errors.add("INPUT_INVALID")
        mappings = row["sources"]
        if not utf8_sorted_unique(mappings["blockers"]):
            errors.add("INPUT_INVALID")
        human = humans.get(row["release_decision_requirement_id"])
        if row["release_decision_requirement_id"] is None:
            if mappings["release_selection"] is not None or mappings["release_effectiveness"] is not None:
                errors.add("UNSUPPORTED_RELATION")
        elif human is None:
            errors.add("REFERENCE_INVALID")
        else:
            bindings = [item for item in human["context_bindings"] if item["value"]["kind"] == "FLOW_DISCLOSURE"]
            if (human["step"] != row["step"] or mappings["release_selection"] is None or mappings["release_effectiveness"] is None
                    or len(bindings) != 1 or bindings[0]["value"]["requirement_id"] != row["id"]):
                errors.add("UNSUPPORTED_RELATION")
            if envelope.get("assessment_requirements") and envelope["gate"].get("decision_requirement") == human["id"]:
                errors.add("UNSUPPORTED_RELATION")
        gate = step.get("dispatch_gate", {})
        if gate.get("kind") != "SOURCE_REQUIREMENTS":
            errors.add("UNSUPPORTED_RELATION")
        gate_names = set(gate.get("requirements", []))
        if len(gate_names) + len([item for item in envelope.get("holdings_requirements", []) if item["step"] == row["step"]]) + 1 > 64:
            errors.add("LIMIT_EXCEEDED")
        for name in ("policy", "recipient", "release_selection", "release_effectiveness"):
            mapping = mappings[name]
            if mapping is None:
                continue
            source = sources.get(mapping["requirement_id"])
            if source is None:
                errors.add("REFERENCE_INVALID")
                continue
            declarations = {field["name"]: field["type_ref"] for field in source["fields"]}
            for member, field in mapping.items():
                if member == "requirement_id":
                    continue
                if field not in declarations or declarations[field] not in types:
                    errors.add("REFERENCE_INVALID")
                elif types[declarations[field]]["kind"] not in ({"BOOLEAN"} if member == "effective_field" else {"STRING", "IDENTITY"}):
                    errors.add("TYPE_INVALID")
        names = [mapping["requirement_id"] for name, mapping in mappings.items() if name != "blockers" and mapping is not None] + mappings["blockers"]
        for name in names:
            source = sources.get(name)
            if source is None:
                errors.add("REFERENCE_INVALID")
            elif (source["step"] != row["step"] or name not in gate_names or source["at"] != "CLOCK"
                    or source.get("evaluation_point") != "PROPOSE_AND_DISPATCH" or source["freshness_seconds"] != "0"):
                errors.add("UNSUPPORTED_RELATION")
        if any(source["step"] == row["step"] and (source["id"] not in gate_names or source["at"] != "CLOCK"
                or source.get("evaluation_point") != "PROPOSE_AND_DISPATCH" or source["freshness_seconds"] != "0") for source in sources.values()):
            errors.add("UNSUPPORTED_RELATION")
    return errors


def phase_one(request):
    errors = declaration_errors(request["work_class"], request["envelope"]) & {"TYPE_INVALID", "INPUT_INVALID"}
    if not utf8_sorted_unique([row["requirement_id"] for row in request.get("flow_bases", [])]):
        errors.add("INPUT_INVALID")
    for basis in request.get("flow_bases", []):
        if not utf8_sorted_unique(basis["released_restrictions"]):
            errors.add("INPUT_INVALID")
    return errors


def phase_two(request):
    errors = declaration_errors(request["work_class"], request["envelope"])
    declared = {row["id"]: row for row in requirements(request)}
    bases = {row["requirement_id"]: row for row in request.get("flow_bases", [])}
    if set(bases) - set(declared):
        errors.add("DEPENDENCY_MISMATCH")
    if set(declared) - set(bases):
        errors.add("EVIDENCE_UNAVAILABLE")
    if ("flow_bases" in request or "flow_requirements" in request["envelope"]) and len(canonical(request)) > 1048576:
        errors.add("LIMIT_EXCEEDED")
    for basis in bases.values():
        try:
            validate_configuration(basis["configuration"])
            validate_state(basis["configuration"], basis["state"], basis["state_digest"])
        except Refusal as error:
            errors.add(error.code)
        if not valid_instant(basis["selection"]["at"]):
            errors.add("CLOCK_INVALID")
        declaration = declared.get(basis["requirement_id"])
        if declaration:
            if declaration["configuration_digest"] != configuration_digest(basis["configuration"]):
                errors.add("DEPENDENCY_MISMATCH")
            if bool(basis["released_restrictions"]) != (declaration["release_decision_requirement_id"] is not None):
                errors.add("UNSUPPORTED_RELATION")
            catalogue = {row["id"]: row for row in basis["configuration"]["restrictions"]}
            if any(row["restriction_id"] not in catalogue for name in ("entitlements", "release_rules") for row in declaration["policy"][name]):
                errors.add("REFERENCE_INVALID")
            elif any(row["scope"] != catalogue[row["restriction_id"]]["scope"] for name in ("entitlements", "release_rules") for row in declaration["policy"][name]):
                errors.add("DEPENDENCY_MISMATCH")
    return errors


def _selected(request, declaration, basis):
    context = next(row for row in basis["state"]["core"]["contexts"] if row["id"] == declaration["context_id"])
    artifact = next(row for row in basis["state"]["core"]["artifacts"] if row["id"] == declaration["artifact_id"])
    return context, artifact


def phase_three(request):
    for declaration in requirements(request):
        basis = next(row for row in request["flow_bases"] if row["requirement_id"] == declaration["id"])
        configuration, selection = basis["configuration"], basis["selection"]
        if (declaration["configuration_digest"] != configuration_digest(configuration)
                or selection["configuration_digest"] != configuration_digest(configuration)
                or selection["state_digest"] != basis["state_digest"] or selection["revision"] != basis["state"]["core"]["revision"]
                or (selection["provider"], selection["source"], selection["channel"])
                != (configuration["provider"], configuration["source"], configuration["protected_channel"])):
            return "DEPENDENCY_MISMATCH"
        try:
            context, artifact = _selected(request, declaration, basis)
        except StopIteration:
            return "BINDING_MISMATCH"
        if (configuration["principal"] != request["envelope"]["principal"] or context["scope"] != request["envelope"]["scope"]["id"]
                or context["actor"] != request["proposal"]["executor"]["actor"] or artifact["context_id"] != context["id"]
                or artifact["types"] != request["work_class"]["types"] or artifact["fields"] != request["proposal"]["fields"]):
            return "BINDING_MISMATCH"
        union = set(context["restrictions"]) | set(artifact["restrictions"])
        released = basis["released_restrictions"]
        if set(released) - union:
            return "BINDING_MISMATCH"
    return None


def disclosure_values(request, declaration, basis):
    context, artifact = _selected(request, declaration, basis)
    recipient = next(row["value"]["value"] for row in request["proposal"]["fields"] if row["name"] == declaration["recipient_field"])
    value = {"principal": request["envelope"]["principal"], "configuration_digest": configuration_digest(basis["configuration"]),
        "policy_digest": digest("flow-policy", declaration["policy"]), "context_digest": digest("flow-context", context),
        "artifact_digest": digest("flow-artifact", artifact),
        **{key: request["proposal"][key] for key in ("work_class_digest", "instance", "occurrence", "step", "interface", "operation", "fields")},
        "recipient": recipient, **{key: declaration[key] for key in ("channel", "purpose", "intent_id", "claim_id")},
        "released_restrictions": basis["released_restrictions"]}
    return {**value, "subject_digest": digest("flow-disclosure-subject", value)}


def binding_value(request, selector):
    declaration = next(row for row in requirements(request) if row["id"] == selector["requirement_id"])
    basis = next(row for row in request["flow_bases"] if row["requirement_id"] == declaration["id"])
    return {"type_ref": selector["type_ref"], "value": disclosure_values(request, declaration, basis)["subject_digest"]}


def release_act(request, declaration):
    name = declaration["release_decision_requirement_id"]
    if name is None:
        return None
    evidence = next(row["evidence"] for row in request["decision_bases"] if row["requirement_id"] == name)
    return next(row for row in evidence["authority_input"]["acts"] if digest("authority-act", row) == evidence["decision_act_digest"])


def policy(request, usable, decision_contexts=None):
    reasons, failed, checks, fences = set(), [], [], []
    for declaration in requirements(request):
        basis = next(row for row in request["flow_bases"] if row["requirement_id"] == declaration["id"])
        values = disclosure_values(request, declaration, basis)
        at = request["clock"]["instant"]
        query = {"requirement_id": declaration["id"], **{key: values[key] for key in ("context_digest", "artifact_digest", "intent_id", "claim_id", "recipient", "channel", "purpose")}, "at": at}
        check = {"purpose": "FLOW", "subject_digest": digest("flow-query", query), "requirement_ref": declaration["id"], "at": at}
        own = set()
        selection, core = basis["selection"], basis["state"]["core"]
        if selection["status"] != "AVAILABLE":
            own.add("FLOW_UNAVAILABLE")
        elif selection["at"] != at or at < core["last_clock"]:
            own.add("FLOW_STALE")
        if len(basis["state"]["records"]) >= 128 or len(core["claims"]) >= 128:
            own.add("FLOW_CAPACITY_EXHAUSTED")
        mappings = declaration["sources"]
        def matches(mapping, expected):
            observation = usable.get(mapping["requirement_id"])
            if observation is None:
                return True
            fields = {row["name"]: row["value"]["value"] for row in observation["fields"]}
            return all(fields.get(mapping[key]) == value for key, value in expected.items())
        if (not matches(mappings["policy"], {"digest_field": values["policy_digest"]})
                or not matches(mappings["recipient"], {"recipient_field": values["recipient"], "channel_field": values["channel"], "purpose_field": values["purpose"]})):
            own.add("FLOW_DEPENDENCY_CHANGED")
        if not matches(mappings["recipient"], {"effective_field": True}):
            own.add("FLOW_RECIPIENT_NOT_ENTITLED")
        context, artifact = _selected(request, declaration, basis)
        released = set(basis["released_restrictions"])
        union = set(context["restrictions"]) | set(artifact["restrictions"])
        catalogue = {row["id"]: row for row in basis["configuration"]["restrictions"]}
        target = {"scope": context["scope"], "recipient": values["recipient"], "channel": values["channel"], "purpose": values["purpose"]}
        for restriction in union - released:
            if {"restriction_id": restriction, **target} not in declaration["policy"]["entitlements"]:
                own.add("FLOW_RECIPIENT_NOT_ENTITLED")
        act = release_act(request, declaration)
        act_digest = digest("authority-act", act) if act is not None else None
        if released:
            human = next(row for row in request["envelope"]["decision_requirements"] if row["id"] == declaration["release_decision_requirement_id"])
            for restriction in released:
                rule = {"restriction_id": restriction, **target, "release_role": catalogue[restriction]["release_role"]}
                if (not catalogue[restriction]["releasable"] or rule not in declaration["policy"]["release_rules"]
                        or human["principal"] != basis["configuration"]["principal"] or human["role"] != rule["release_role"]):
                    own.add("FLOW_RELEASE_NOT_ESTABLISHED")
            if (not matches(mappings["release_selection"], {"act_id_field": act["id"], "act_digest_field": act_digest,
                    "subject_digest_field": values["subject_digest"], "claim_id_field": declaration["claim_id"]})
                    or not matches(mappings["release_effectiveness"], {"act_id_field": act["id"], "effective_field": True})):
                own.add("FLOW_RELEASE_NOT_ESTABLISHED")
            if decision_contexts is not None and decision_contexts[human["id"]]["result"]["status"] != "EVIDENCE_VALID":
                own.add("FLOW_RELEASE_NOT_ESTABLISHED")
        if any(row["id"] == declaration["claim_id"] or row["intent_id"] == declaration["intent_id"] for row in core["claims"]) or act_digest in core["consumed_release_acts"]:
            own.add("FLOW_CLAIM_CONSUMED")
        if own:
            reasons.update(own)
            failed.extend({**check, "reason": reason} for reason in sorted(own))
        else:
            checks.append(check)
            fences.append({"requirement_id": declaration["id"], "configuration_digest": values["configuration_digest"],
                "state_digest": basis["state_digest"], "revision": core["revision"],
                **{key: values[key] for key in ("context_digest", "artifact_digest", "policy_digest", "intent_id", "claim_id")}, "release_act_digest": act_digest})
    return {"reasons": reasons, "failed": failed, "checks": checks, "rows": fences}


def fence_rows(request, result):
    from .source_observations import source_query
    usable = {}
    for row in request["envelope"].get("source_observation_requirements", []):
        query = source_query(row, request)
        observations = {canonical(item): item for item in request["observations"] if item["query_digest"] == digest("authority-query", query)}
        if len(observations) == 1:
            usable[row["id"]] = next(iter(observations.values()))
    derived = policy(request, usable)
    if derived["failed"]:
        raise Refusal("BINDING_MISMATCH")
    return sorted(derived["rows"], key=lambda row: row["requirement_id"].encode())
