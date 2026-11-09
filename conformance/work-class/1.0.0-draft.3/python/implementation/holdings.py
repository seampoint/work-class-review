"""Complete permission registry transitions and current authority reliance."""
from __future__ import annotations

import copy

from .common import PIN, PREFIX, Refusal, artifact_bytes, canonical, digest, schema_valid, utf8_sorted_unique, valid_instant


def configuration_digest(configuration):
    return digest("holdings-configuration", configuration)


def state_digest(state):
    return digest("holdings-state", state)


def validate_configuration(configuration):
    if not schema_valid(configuration, "holdings.schema.json", "configuration"):
        raise Refusal("SCHEMA_INVALID")
    if configuration["specification_pin"] != PIN:
        raise Refusal("VERSION_UNSUPPORTED")
    permissions, conflicts = configuration["permissions"], configuration["conflicts"]
    pairs = [canonical(row) for row in conflicts]
    if (not utf8_sorted_unique(permissions) or pairs != sorted(set(pairs))
            or any(row["left"] not in permissions or row["right"] not in permissions
                   or row["left"].encode() >= row["right"].encode() for row in conflicts)):
        raise Refusal("DEFINITION_INVALID")


def active(grant, at):
    return (grant["valid_from"] <= at and (grant["valid_until"] is None or at < grant["valid_until"])
            and (grant.get("revoked_at") is None or at < grant["revoked_at"]))


def _administration(configuration, event, host):
    config_digest = configuration_digest(configuration)
    if host["configuration_digest"] != config_digest:
        raise Refusal("DEPENDENCY_MISMATCH")
    administration = event["administration"]
    if administration is None:
        raise Refusal("ADMINISTRATION_NOT_ESTABLISHED")
    basis, act, returned = (administration[name] for name in ("basis", "act", "return"))
    at = event["clock"]["instant"]
    subject = digest("holdings-administration-subject", {"configuration_digest": config_digest,
        "event": {key: value for key, value in event.items() if key != "administration"}})
    if (basis["configuration_digest"] != config_digest or basis["principal"] != configuration["principal"]
            or basis["actor"] != act["actor"] or act["basis_id"] != basis["id"]
            or act["principal"] != basis["principal"] or act["role"] != basis["role"]
            or act["kind"] != event["kind"] or act["subject_digest"] != subject
            or basis["observed_at"] != at or act["occurred_at"] != at
            or (basis["provider"], basis["source"]) != (configuration["provider"], configuration["source"])
            or not utf8_sorted_unique(basis["allowed_operations"])):
        raise Refusal("DEPENDENCY_MISMATCH")
    if returned is None:
        raise Refusal("EVIDENCE_UNAVAILABLE")
    decoded = artifact_bytes(returned["act_bytes_base64"])
    if (decoded != act or returned["act_digest"] != digest("holdings-administration-act", act)
            or returned["actor"] != act["actor"] or returned["observed_at"] != at
            or (returned["provider"], returned["source"], returned["channel"])
            != (configuration["provider"], configuration["source"], configuration["protected_channel"])):
        raise Refusal("DEPENDENCY_MISMATCH")
    expected = [{"kind": kind, "record_digest": digest("holdings-administration-" + name, record),
        "provider": configuration["provider"], "source": configuration["source"], "channel": channel}
        for kind, name, record, channel in (("ADMIN_BASIS", "basis", basis, None),
            ("ADMIN_RETURN", "return", returned, configuration["protected_channel"]))]
    actual = host["authenticated_records"]
    actual_bytes = [canonical(row) for row in actual]
    if actual_bytes != sorted(set(actual_bytes)) or any(row not in expected for row in actual):
        raise Refusal("DEPENDENCY_MISMATCH")
    if any(row not in actual for row in expected):
        raise Refusal("EVIDENCE_UNAVAILABLE")
    instants = [basis[name] for name in ("observed_at", "valid_from", "valid_until", "revoked_at")] + [act["occurred_at"], returned["observed_at"]]
    if any(value is not None and not valid_instant(value) for value in instants):
        raise Refusal("CLOCK_INVALID")
    if (basis["role"] != configuration["administration_role"] or event["kind"] not in basis["allowed_operations"]
            or not active(basis, at) or act["status"] != "ACCEPTED"):
        raise Refusal("ADMINISTRATION_NOT_ESTABLISHED")


def _apply(configuration, state, event, host):
    before = state_digest(state) if state is not None else None
    revision = state["core"]["revision"] if state is not None else "0"
    if event["expected_revision"] != revision or event["expected_state_digest"] != before:
        raise Refusal("REVISION_CONFLICT")
    clock = event["clock"]
    if (clock["source"] != configuration["clock_source"] or clock["status"] != "AVAILABLE"
            or not valid_instant(clock["instant"])
            or state is not None and clock["instant"] < state["core"]["last_clock"]):
        raise Refusal("CLOCK_INVALID")
    _administration(configuration, event, host)
    if state is not None and len(state["records"]) >= 64:
        raise Refusal("LIMIT_EXCEEDED")
    at, payload = clock["instant"], event["payload"]
    grants = copy.deepcopy(state["core"]["grants"]) if state is not None else []
    reasons = []
    if event["kind"] == "INITIALIZE":
        if state is not None:
            raise Refusal("DEFINITION_CONFLICT")
        seed = host["seed_inventory"]
        if seed is None:
            raise Refusal("EVIDENCE_UNAVAILABLE")
        if seed["inventory_digest"] != digest("holdings-seed-inventory", payload["grants"]):
            raise Refusal("DEPENDENCY_MISMATCH")
        identifiers = [row["id"] for row in payload["grants"]]
        if not utf8_sorted_unique(identifiers):
            raise Refusal("STATE_INVALID")
        grants = [{**copy.deepcopy(row), "revoked_at": None} for row in payload["grants"]]
        if any(row["permission"] not in configuration["permissions"]
                or not valid_instant(row["valid_from"])
                or row["valid_until"] is not None and not valid_instant(row["valid_until"])
                or not active(row, at) for row in grants):
            raise Refusal("STATE_INVALID")
        pairs = [(row["actor"], row["permission"]) for row in grants]
        if len(pairs) != len(set(pairs)) or any(
            (actor, conflict["left"]) in pairs and (actor, conflict["right"]) in pairs
            for actor, _ in pairs for conflict in configuration["conflicts"]):
            raise Refusal("STATE_INVALID")
        decision = "INITIALIZED"
    elif state is None:
        raise Refusal("STATE_INVALID")
    elif event["kind"] == "GRANT":
        if payload["permission"] not in configuration["permissions"] or any(row["id"] == payload["grant_id"] for row in grants):
            raise Refusal("DEPENDENCY_MISMATCH")
        end = payload["valid_until"]
        if end is not None and (not valid_instant(end) or end <= at):
            raise Refusal("CLOCK_INVALID")
        held = {row["permission"] for row in grants if row["actor"] == payload["actor"] and active(row, at)}
        if payload["permission"] in held:
            decision, reasons = "UNCHANGED", ["ALREADY_HELD"]
        elif any(payload["permission"] == row["left"] and row["right"] in held
                 or payload["permission"] == row["right"] and row["left"] in held for row in configuration["conflicts"]):
            decision, reasons = "WITHHELD", ["CONFLICTING_HOLDING"]
        else:
            if len(grants) >= 256:
                raise Refusal("LIMIT_EXCEEDED")
            grants.append({"id": payload["grant_id"], "actor": payload["actor"], "permission": payload["permission"],
                "valid_from": at, "valid_until": end, "revoked_at": None})
            decision = "GRANTED"
    else:
        target = next((row for row in grants if row["id"] == payload["grant_id"]), None)
        if target is None or (target["actor"], target["permission"]) != (payload["actor"], payload["permission"]):
            raise Refusal("DEPENDENCY_MISMATCH")
        if not active(target, at):
            decision, reasons = "UNCHANGED", ["NOT_ACTIVE"]
        else:
            target["revoked_at"] = at
            decision = "REVOKED"
    core = {"configuration_digest": configuration_digest(configuration), "revision": str(int(revision) + 1),
        "last_clock": at, "grants": sorted(grants, key=lambda row: row["id"].encode())}
    event_digest = digest("holdings-event", {"event": event, "host_evidence": host})
    receipt = {"schema": PREFIX + "holdings-receipt", "event_id": event["id"], "event_digest": event_digest,
        "state_before_digest": before, "revision": core["revision"], "core_after_digest": digest("holdings-core", core),
        "decision": decision, "reasons": reasons, "protected_channel": configuration["protected_channel"]}
    receipt_digest = digest("holdings-receipt", receipt)
    record = {"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(host), "event_digest": event_digest,
        "receipt": receipt, "receipt_digest": receipt_digest}
    next_state = {"schema": PREFIX + "holdings-state", "specification_pin": PIN, "core": core,
        "records": [*(copy.deepcopy(state["records"]) if state is not None else []), record]}
    return {"status": "TRANSITION", "receipt": receipt, "receipt_digest": receipt_digest,
        "state": next_state, "state_digest": state_digest(next_state), "replay": False}


def validate_state(configuration, state, supplied_digest):
    if state is None:
        if supplied_digest is not None:
            raise Refusal("DIGEST_MISMATCH")
        return
    if not schema_valid(state, "holdings.schema.json", "state"):
        raise Refusal("SCHEMA_INVALID")
    if state_digest(state) != supplied_digest:
        raise Refusal("DIGEST_MISMATCH")
    if state["specification_pin"] != PIN:
        raise Refusal("VERSION_UNSUPPORTED")
    if state["core"]["configuration_digest"] != configuration_digest(configuration):
        raise Refusal("DEPENDENCY_MISMATCH")
    rebuilt, ids = None, set()
    try:
        for record in state["records"]:
            if record["event"]["id"] in ids:
                raise Refusal("STATE_INVALID")
            ids.add(record["event"]["id"])
            result = _apply(configuration, rebuilt, record["event"], record["host_evidence"])
            if result["state"]["records"][-1] != record:
                raise Refusal("STATE_INVALID")
            rebuilt = result["state"]
        if rebuilt != state:
            raise Refusal("STATE_INVALID")
    except Refusal:
        raise Refusal("STATE_INVALID") from None


def transition(request):
    if not schema_valid(request, "holdings.schema.json", "input"):
        return {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""}
    try:
        if len(canonical(request)) > 16777216:
            raise Refusal("LIMIT_EXCEEDED")
        if request["specification_pin"] != PIN:
            raise Refusal("VERSION_UNSUPPORTED")
        configuration, state, event, host = (request[name] for name in ("configuration", "state", "event", "host_evidence"))
        validate_configuration(configuration)
        validate_state(configuration, state, request["state_digest"])
        if state is not None:
            previous = next((row for row in state["records"] if row["event"]["id"] == event["id"]), None)
            if previous is not None:
                if previous["event"] != event or previous["host_evidence"] != host:
                    raise Refusal("REPLAY_CONFLICT")
                return {"status": "TRANSITION", "receipt": copy.deepcopy(previous["receipt"]),
                    "receipt_digest": previous["receipt_digest"], "state": copy.deepcopy(state),
                    "state_digest": request["state_digest"], "replay": True}
        return _apply(configuration, state, event, host)
    except Refusal as error:
        return {"status": "REFUSED", "code": error.code, "path": "", "state": copy.deepcopy(request["state"]),
            "state_digest": request["state_digest"]}


def requirements(request):
    return [row for row in request["envelope"].get("holdings_requirements", []) if row["step"] == request["proposal"]["step"]]


def declaration_error(work, envelope):
    declared = envelope.get("holdings_requirements", [])
    if not utf8_sorted_unique([row["id"] for row in declared]):
        return "INPUT_INVALID"
    if any(row["step"] not in {step["id"] for step in work["steps"]} for row in declared):
        return "REFERENCE_INVALID"
    if envelope["gate"]["kind"] == "NONE" and any(row["actor"] == "GATE_ACTOR" for row in declared):
        return "UNSUPPORTED_RELATION"
    for step in work["steps"]:
        gate = step.get("dispatch_gate")
        selected = [row for row in declared if row["step"] == step["id"]]
        if selected and gate is not None:
            if gate.get("kind") != "SOURCE_REQUIREMENTS":
                return "UNSUPPORTED_RELATION"
            if len(gate["requirements"]) + len(selected) > 64:
                return "LIMIT_EXCEEDED"
    return None


def phase_two(request):
    errors = set()
    for basis in request.get("holdings_bases", []):
        configuration = basis["configuration"]
        if configuration["specification_pin"] != PIN or basis["state"]["specification_pin"] != PIN:
            errors.add("VERSION_UNSUPPORTED")
        for admit in (lambda: validate_configuration(configuration), lambda: validate_state(configuration, basis["state"], basis["state_digest"])):
            try:
                admit()
            except Refusal as error:
                errors.add(error.code)
        selection = basis["selection"]
        if not valid_instant(selection["at"]):
            errors.add("CLOCK_INVALID")
    if errors:
        raise Refusal(next(code for code in ("VERSION_UNSUPPORTED", "DEPENDENCY_MISMATCH", "DEFINITION_INVALID", "DIGEST_MISMATCH", "STATE_INVALID", "CLOCK_INVALID",
            "EVIDENCE_UNAVAILABLE", "UNSUPPORTED_RELATION", "REFERENCE_INVALID", "LIMIT_EXCEEDED") if code in errors))


def phase_three(request):
    supplied = [configuration_digest(row["configuration"]) for row in request.get("holdings_bases", [])]
    selected = requirements(request)
    needed = {row["configuration_digest"] for row in selected}
    if len(supplied) != len(set(supplied)) or set(supplied) - needed:
        return "BINDING_MISMATCH"
    for basis in request.get("holdings_bases", []):
        configuration, selection = basis["configuration"], basis["selection"]
        config_digest = configuration_digest(configuration)
        if (configuration["principal"] != request["envelope"]["principal"]
                or configuration["clock_source"] != request["envelope"]["clock_source"]
                or selection["configuration_digest"] != config_digest
                or selection["state_digest"] != basis["state_digest"] or selection["revision"] != basis["state"]["core"]["revision"]
                or (selection["provider"], selection["source"], selection["channel"])
                != (configuration["provider"], configuration["source"], configuration["protected_channel"])
                or any(row["permission"] not in configuration["permissions"] for row in selected if row["configuration_digest"] == config_digest)):
            return "DEPENDENCY_MISMATCH"
    return None


def actor_for(request, requirement, selected_acts, decision_contexts=None):
    if requirement["actor"] == "EXECUTOR":
        return request["proposal"]["executor"]["actor"]
    gate = request["envelope"]["gate"]
    if "decision_requirement" in gate:
        context = (decision_contexts or {}).get(gate["decision_requirement"])
        if context is None:
            raise Refusal("BINDING_MISMATCH")
        return context["decision"]["actor"]
    kind = {"DECIDE": "INSTANCE_DECISION", "VERIFY": "VERIFY"}.get(gate["kind"])
    acts = [row for row in selected_acts if row["kind"] == kind and row["role"] == gate["role"]]
    if len(acts) != 1:
        raise Refusal("BINDING_MISMATCH")
    return acts[0]["actor"]


def policy(request, selected_acts, decision_contexts=None):
    checks, failed, rows = [], [], []
    bases = {configuration_digest(row["configuration"]): row for row in request.get("holdings_bases", [])}
    at = request["clock"]["instant"]
    for requirement in requirements(request):
        actor = actor_for(request, requirement, selected_acts, decision_contexts)
        check = {"purpose": "HOLDINGS", "subject_digest": digest("holdings-query", {"requirement": requirement, "actor": actor, "at": at}),
            "requirement_ref": requirement["id"], "at": at}
        basis = bases.get(requirement["configuration_digest"])
        reason = None
        if basis is None or basis["selection"]["status"] != "AVAILABLE":
            reason = "HOLDINGS_UNAVAILABLE"
        elif basis["selection"]["at"] != at or at < basis["state"]["core"]["last_clock"]:
            reason = "HOLDINGS_STALE"
        elif len(basis["state"]["records"]) >= 64:
            reason = "HOLDINGS_CAPACITY_EXHAUSTED"
        else:
            grants = [row for row in basis["state"]["core"]["grants"] if row["actor"] == actor
                and row["permission"] == requirement["permission"] and active(row, at)]
            if len(grants) != 1:
                reason = "CURRENT_HOLDING_REQUIRED"
            else:
                grant = grants[0]
                rows.append({"requirement_id": requirement["id"], "configuration_digest": requirement["configuration_digest"],
                    "state_digest": basis["state_digest"], "revision": basis["state"]["core"]["revision"], "actor": actor,
                    "permission": requirement["permission"], "grant_id": grant["id"], "valid_until": grant["valid_until"]})
        if reason:
            failed.append({**check, "reason": reason})
        else:
            checks.append(check)
    return {"checks": checks, "failed": failed, "reasons": {row["reason"] for row in failed}, "rows": rows}


def fence_rows(request, result):
    from . import human_decisions
    selected = [row for row in request["acts"] if digest("authority-act", row) in result["act_digests"]]
    contexts = {}
    for row in human_decisions.selected_gate_bases(request, result):
        contexts[request["envelope"]["gate"]["decision_requirement"]] = {"decision": row["act"]}
    checked = policy(request, selected, contexts)
    if checked["failed"]:
        raise Refusal("BINDING_MISMATCH")
    return sorted(checked["rows"], key=lambda row: row["requirement_id"].encode())
