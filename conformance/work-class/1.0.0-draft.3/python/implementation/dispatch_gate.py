"""Fresh gated authorizations and retained evidence integrity."""

from __future__ import annotations

import copy

from . import authority, recovery
from .common import PIN, PREFIX, Refusal, canonical, digest
from .source_observations import source_query


ADMISSION_CODES = {"SCHEMA_INVALID", "ARTIFACT_ENCODING_INVALID", "ARTIFACT_NONCANONICAL", "TYPE_INVALID", "INPUT_INVALID", "LIMIT_EXCEEDED", "VERSION_UNSUPPORTED", "DEPENDENCY_MISMATCH", "UNSUPPORTED_RELATION", "REFERENCE_INVALID", "BINDING_MISMATCH", "DEFINITION_INVALID", "STATE_INVALID", "DIGEST_MISMATCH", "CLOCK_INVALID"}
IMMUTABLE = ("schema", "specification_pin", "source", "work_class", "envelope", "proposal", "host_selection", "occupancies", "capacities", "credentials", "acts", "returns")


def step_definition(definition, permit):
    return next(row for row in definition["steps"] if row["id"] == permit["occurrence"]["step_id"])


def observation_digests(value):
    return sorted({digest("authority-observation", row) for row in value["observations"]}, key=str.encode)


def immutable_binding(basis, fresh):
    def projection(value):
        body = copy.deepcopy(value)
        for key in ("clock", "observations", "evaluation_point", "holdings_bases"):
            body.pop(key, None)
        for row in body.get("flow_bases", []):
            for key in ("state", "state_digest", "selection"):
                row.pop(key, None)
        for row in body.get("decision_bases", []):
            row["evidence"]["authority_input"] = projection(row["evidence"]["authority_input"])
        return body
    return canonical(projection(basis)) == canonical(projection(fresh))


def head(state, permit_id):
    rows = [row for row in state.get("authorizations", []) if row["permit_digest"] == permit_id and "dispatch_intent_id" in row]
    successors = {row["supersedes_authorization_digest"] for row in rows if row["supersedes_authorization_digest"] is not None}
    heads = [row for row in rows if row["authorization_digest"] not in successors]
    if len(heads) > 1:
        raise Refusal("STATE_INVALID")
    return heads[0] if heads else None


def consumed(state, permit_id):
    return (any(row["permit_digest"] == permit_id and (row["attempt"]["status"] != "NOT_SENT" or row["acknowledgement"]["status"] == "ACCEPTED") for row in state["dispatches"])
            or any(row.get("permit_digest") == permit_id and row["native_evidence"]["status"] in {"EFFECT_ESTABLISHED", "NO_EFFECT_ESTABLISHED"} for row in state["outcomes"])
            or any(row["permit_digest"] == permit_id for row in state.get("completion_checks", [])))


def eligible(state, permit):
    active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == permit["occurrence"]["occurrence_id"]), None)
    return (state["status"] == "ACTIVE" and active is not None and active["status"] == "PERMITTED"
            and any(row["permit_id"] == permit["permit_id"] for row in state["permits"])
            and not consumed(state, permit["permit_id"])
            and not recovery.renewal_required(state, permit)
            and not any(row["supersedes_permit_digest"] == permit["permit_id"] for row in state["permits"]))


def accepted_clock(state, source, before_sequence, available_only=False):
    clock_sequences = {(detail["source"], detail["revision"]): int(receipt["sequence"])
                       for receipt in state["receipts"] for detail in receipt["details"] if detail["kind"] == "CLOCK"}
    rows = [row for row in state["clocks"] if row["source"] == source
            and (not available_only or row["status"] == "AVAILABLE")
            and clock_sequences.get((row["source"], row["revision"]), 0) < before_sequence]
    return max(rows, key=lambda row: int(row["revision"])) if rows else None


def latest_evaluation(state, permit_id):
    sequences = {row["event_id"]: int(row["sequence"]) for row in state["receipts"]}
    rows = [row for row in state.get("authorization_evaluations", []) if row["permit_digest"] == permit_id]
    return max(rows, key=lambda row: sequences[row["event_id"]]) if rows else None


def attempt_history(state, permit_id, attempt_id, before_sequence=None):
    sequences = {row["event_id"]: int(row["sequence"]) for row in state["receipts"]}
    return sorted([row for row in state["dispatches"] if row["permit_digest"] == permit_id
                   and row["attempt"]["attempt_id"] == attempt_id
                   and (before_sequence is None or sequences[row["event_id"]] < before_sequence)],
                  key=lambda row: sequences[row["event_id"]])


def historical_authorization(state, permit, authorization, native_request, connector, attempted_at, before_sequence):
    from . import lifecycle
    if (authorization is None or "dispatch_intent_id" not in authorization
            or authorization["permit_digest"] != permit["permit_id"]
            or canonical(authorization["native_request"]) != canonical(native_request)
            or canonical(authorization["connector"]) != canonical(connector)
            or not lifecycle._parse(authorization["authorization_fence"]["checked_at"]) <= lifecycle._parse(attempted_at) < lifecycle._parse(authorization["expires_at"])):
        return False
    sequences = {row["event_id"]: int(row["sequence"]) for row in state["receipts"]}
    selected_sequence = sequences[authorization["event_id"]]
    if selected_sequence >= before_sequence:
        return False
    for evaluation in state.get("authorization_evaluations", []):
        if evaluation["permit_digest"] != permit["permit_id"] or not selected_sequence < sequences[evaluation["event_id"]] < before_sequence:
            continue
        clock = evaluation["authority_input"]["clock"]
        if clock["status"] == "AVAILABLE" and lifecycle._parse(attempted_at) >= lifecycle._parse(clock["instant"]):
            return False
    return not any(row.get("authorization_digest") == authorization["authorization_digest"]
                   and sequences[row["event_id"]] < before_sequence for row in state["dispatches"])


def dispatch_integrity(state, definition, dispatch):
    try:
        return _dispatch_integrity(state, definition, dispatch)
    except (KeyError, StopIteration, TypeError, ValueError, OverflowError, Refusal):
        return False


def _dispatch_integrity(state, definition, dispatch):
    from . import completion, lifecycle, timing
    permit = next(row for row in state["permits"] if row["permit_id"] == dispatch["permit_digest"])
    receipts = {row["event_id"]: row for row in state["receipts"]}
    receipt = receipts[dispatch["event_id"]]
    sequence = int(receipt["sequence"])
    event = {"schema": PREFIX + "runtime-event", "kind": "DISPATCH_OBSERVED", "event_id": dispatch["event_id"],
             "instance_id": state["instance_id"], "expected_state_revision": str(sequence - 1),
             "expected_state_digest": receipt["state_before_digest"], "permit": permit,
             **{key: dispatch[key] for key in ("native_request", "connector", "attempt", "acknowledgement", "clock_revision")}}
    if "authorization_digest" in dispatch:
        event["authorization_digest"] = dispatch["authorization_digest"]
    if digest("runtime-event", event) != dispatch["event_digest"]:
        return False
    prior = completion._prior_evidence(state, sequence, definition)
    request = {
        "specification_pin": PIN, "definition": definition, "definition_digest": state["work_class_digest"],
        "profile": state["profile"], "role": state["role"], "state": prior,
        "state_digest": receipt["state_before_digest"], "event": event,
    }
    next_state, disposition, reasons, details, _ = lifecycle._prepare_dispatch(request)
    next_state, disposition, reasons, details = timing.transition(request, next_state, disposition, reasons, details)
    timing.validate_activation_clocks(request, next_state)
    return (disposition == receipt["disposition"]
            and sorted(set(reasons), key=str.encode) == receipt["reason_codes"]
            and details == receipt["details"])


def expiry(permit, fresh, gate, checked_at):
    from .lifecycle import _add_seconds
    try:
        end = _add_seconds(checked_at, int(gate["authorization_seconds"]))
    except (ValueError, OverflowError):
        raise Refusal("LIMIT_EXCEEDED") from None
    limits = [permit["expires_at"], end]
    fixed_end = fresh["envelope"]["temporal_validity"]["valid_until"]
    if fixed_end is not None:
        limits.append(fixed_end)
    if gate.get("kind") == "SOURCE_REQUIREMENTS":
        requirements = {row["id"]: row for row in fresh["envelope"].get("source_observation_requirements", [])}
        for validity in gate["validity_requirements"]:
            query = source_query(requirements[validity["requirement_id"]], fresh)
            rows = {canonical(row): row for row in fresh["observations"] if row["query_digest"] == digest("authority-query", query)}
            if len(rows) != 1: raise Refusal("BINDING_MISMATCH")
            observation = next(iter(rows.values()))
            limits.append(next(row["value"]["value"] for row in observation["fields"] if row["name"] == validity["not_after_field"]))
    if fresh.get("decision_bases"):
        result = authority.evaluate_authority(fresh, PIN)
        if result.get("status") != "READY_FOR_RESERVATION": raise Refusal("BINDING_MISMATCH")
        limits.extend(row["result"]["effective_until"] for row in result.get("decision_results", []))
    from . import holdings
    if holdings.requirements(fresh):
        result = authority.evaluate_authority(fresh, PIN)
        if result.get("status") != "READY_FOR_RESERVATION": raise Refusal("BINDING_MISMATCH")
        limits.extend(row["valid_until"] for row in holdings.fence_rows(fresh, result) if row["valid_until"] is not None)
    return min(limits)


def fence(event, result, gate, checked_at, expires_at):
    fresh = event["authority_input"]
    requirements = {row["id"]: row for row in fresh["envelope"].get("source_observation_requirements", [])}
    sources = []
    vector = gate.get("kind") == "SOURCE_REQUIREMENTS"
    names = gate["requirements"] if vector else [gate["approval_requirement"], gate["withdrawal_requirement"], *gate["policy_withdrawal_requirements"]]
    for name in sorted(names, key=str.encode):
        requirement = requirements[name]
        query = source_query(requirement, fresh)
        rows = {canonical(row): row for row in fresh["observations"] if row["query_digest"] == digest("authority-query", query)}
        if len(rows) != 1:
            raise Refusal("BINDING_MISMATCH")
        observation = next(iter(rows.values()))
        sources.append({"requirement_id": name, "provider": requirement["provider"], "source": requirement["source"],
                        "expected_status": requirement["expected_status"], "record_id": observation.get("provider_record_id"),
                        "provider_revision": observation["revision"], "query_digest": observation["query_digest"],
                        "observation_digest": digest("authority-observation", observation)})
    scope = {"instance_id": event["instance_id"], "occurrence_id": event["permit"]["occurrence"]["occurrence_id"],
             "permit_digest": event["permit"]["permit_id"], "native_request": event["native_request"], "connector": event["connector"],
             "dispatch_intent_id": event["dispatch_intent_id"], "checked_at": checked_at, "expires_at": expires_at,
             "authority_result_digest": digest("authority-result", result), "sources": sources}
    from . import holdings, flow
    selected_holdings = holdings.requirements(fresh)
    selected_flows = flow.requirements(fresh)
    if (selected_holdings or selected_flows) and not vector:
        raise Refusal("BINDING_MISMATCH")
    if len(sources) + len(selected_holdings) + len(selected_flows) > 64:
        raise Refusal("LIMIT_EXCEEDED")
    holding_rows = holdings.fence_rows(fresh, result) if selected_holdings else None
    if holding_rows is not None:
        scope["holdings"] = holding_rows
    flow_rows = flow.fence_rows(fresh, result) if selected_flows else None
    if flow_rows is not None:
        scope["flows"] = flow_rows
    if vector:
        coordinator = next(row for row in sources if row["requirement_id"] == gate["coordinator_requirement"])
        derived = {"kind": "SOURCE_REQUIREMENTS", "provider": gate["fence_provider"], "source": gate["fence_source"], "provider_revision": coordinator["provider_revision"], "scope_digest": digest("dispatch-authorization-scope", scope), "checked_at": checked_at, "status": "EFFECTIVE", "sources": sources}
        if holding_rows is not None:
            derived["holdings"] = holding_rows
        if flow_rows is not None:
            derived["flows"] = flow_rows
        return derived
    approval = next(row for row in sources if row["requirement_id"] == gate["approval_requirement"])
    grants = [row for row in fresh["acts"] if row["kind"] == "GRANT" and digest("authority-act", row) in result["act_digests"]]
    if len(grants) != 1:
        raise Refusal("BINDING_MISMATCH")
    return {"approval_id": approval["record_id"], "approver_role": grants[0]["role"], "signed_at": grants[0]["occurred_at"],
            "provider": gate["fence_provider"], "source": gate["fence_source"], "provider_revision": approval["provider_revision"],
            "status": "EFFECTIVE", "scope_digest": digest("dispatch-authorization-scope", scope), "checked_at": checked_at, "sources": sources}


def authorize(request):
    from . import lifecycle
    event, original, definition = request["event"], request["state"], request["definition"]
    state, permit = copy.deepcopy(original), event["permit"]
    step = step_definition(definition, permit)
    gate = step["dispatch_gate"]
    if event.get("authority_input") is None:
        raise Refusal("EVIDENCE_UNAVAILABLE")
    if event.get("dispatch_intent_id") is None:
        raise Refusal("INPUT_INVALID")
    fresh = event["authority_input"]
    basis = permit.get("authority_basis")
    if basis is None:
        raise Refusal("STATE_INVALID")
    if fresh.get("evaluation_point") != "DISPATCH":
        raise Refusal("INPUT_INVALID")
    if (not immutable_binding(basis, fresh)
            or canonical(event["native_request"]) != canonical(permit["native_request"])
            or event["connector"]["binding_digest"] != digest("connector-binding", {"id": event["connector"]["id"], "version": event["connector"]["version"]})):
        raise Refusal("BINDING_MISMATCH")
    evaluations = state.setdefault("authorization_evaluations", [])
    if any(row["dispatch_intent_id"] == event["dispatch_intent_id"] for row in evaluations) or any(row.get("dispatch_intent_id") == event["dispatch_intent_id"] for row in state.get("authorizations", [])):
        raise Refusal("BINDING_MISMATCH")
    if len(evaluations) >= 128:
        raise Refusal("LIMIT_EXCEEDED")
    if not eligible(state, permit):
        raise Refusal("PREREQUISITE_MISSING")
    clocks = [row for row in state["clocks"] if row["source"] == permit["clock_source"]]
    if not clocks:
        raise Refusal("CLOCK_INVALID")
    current = max(clocks, key=lambda row: int(row["revision"]))
    if current["status"] == "CONFLICTING" or event["clock_revision"] != current["revision"] or fresh["clock"] != {"source": current["source"], "status": current["status"], "instant": current["observed_time"]}:
        raise Refusal("CLOCK_INVALID")
    issued = next(row for row in clocks if row["revision"] == permit["clock_revision"])
    if current["status"] == "AVAILABLE" and lifecycle._parse(current["observed_time"]) < lifecycle._parse(issued["observed_time"]):
        raise Refusal("CLOCK_INVALID")
    if current["status"] == "AVAILABLE" and lifecycle._parse(current["observed_time"]) >= lifecycle._parse(permit["expires_at"]):
        raise Refusal("PREREQUISITE_MISSING")
    if event["observation_digests"] != observation_digests(fresh):
        raise Refusal("BINDING_MISMATCH")
    result = authority.evaluate_authority(fresh, PIN)
    result_digest = digest("authority-result", result)
    if result["status"] == "REFUSED" and result["code"] in ADMISSION_CODES:
        raise Refusal(result["code"])
    authorization = None
    disposition, reasons, details = "WITHHELD", [], []
    if result["status"] == "REFUSED":
        reasons = sorted(set(["AUTHORITY_REQUIRED", result["code"], *result["reasons"]]), key=str.encode)
        details = [{"kind": "AUTHORITY", "authority_result_digest": result_digest, "code": result["code"], "reasons": copy.deepcopy(result["reasons"]), "failed_checks": copy.deepcopy(result["failed_checks"])}]
    else:
        checked_at = current["observed_time"]
        expires_at = expiry(permit, fresh, gate, checked_at)
        derived = fence(event, result, gate, checked_at, expires_at)
        if canonical(event["authorization_fence"]) != canonical(derived):
            raise Refusal("BINDING_MISMATCH")
        predecessor = head(state, permit["permit_id"])
        authorization = {"authorization_digest": "", "event_id": event["event_id"], "event_digest": digest("runtime-event", event),
                         "permit_digest": permit["permit_id"], "native_request": copy.deepcopy(event["native_request"]),
                         "connector": copy.deepcopy(event["connector"]), "authorization_fence": derived,
                         "observation_digests": copy.deepcopy(event["observation_digests"]), "clock_revision": event["clock_revision"],
                         "dispatch_intent_id": event["dispatch_intent_id"], "authority_input": copy.deepcopy(fresh),
                         "authority_result": result, "authority_result_digest": result_digest, "expires_at": expires_at,
                         "supersedes_authorization_digest": None if predecessor is None else predecessor["authorization_digest"]}
        authorization["authorization_digest"] = lifecycle._authorization_digest(authorization)
        state.setdefault("authorizations", []).append(authorization)
        state["authorizations"].sort(key=lambda row: row["authorization_digest"].encode("utf-8"))
        disposition = "AUTHORIZED"
        details = [{"kind": "AUTHORIZATION", "authorization_digest": authorization["authorization_digest"], "permit_digest": permit["permit_id"], "checked_at": checked_at, "expires_at": expires_at, "sources": copy.deepcopy(derived["sources"])}]
        if "holdings" in derived:
            details[0]["holdings"] = copy.deepcopy(derived["holdings"])
        if "flows" in derived:
            details[0]["flows"] = copy.deepcopy(derived["flows"])
        details[0].update({"gate_kind": "SOURCE_REQUIREMENTS"} if gate.get("kind") == "SOURCE_REQUIREMENTS" else {"approval_id": derived["approval_id"]})
    evaluation = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": permit["permit_id"],
                  "dispatch_intent_id": event["dispatch_intent_id"], "clock_revision": event["clock_revision"], "authority_input": copy.deepcopy(fresh),
                  "authority_result": result, "authority_result_digest": result_digest,
                  "authorization_digest": None if authorization is None else authorization["authorization_digest"], "disposition": disposition}
    evaluation["evaluation_digest"] = digest("dispatch-authorization-evaluation", evaluation)
    evaluations.append(evaluation)
    evaluations.sort(key=lambda row: row["event_id"].encode("utf-8"))
    return lifecycle._finish(request, state, disposition, reasons, details, authority_result_digest=result_digest,
                             permit_digest=permit["permit_id"], authorization_evaluation_digest=evaluation["evaluation_digest"])


def basis_integrity(state, definition, permit):
    try:
        return _basis_integrity(state, definition, permit)
    except (KeyError, StopIteration, TypeError, ValueError, OverflowError, Refusal):
        return False


def _basis_integrity(state, definition, permit):
    from . import lifecycle
    step = step_definition(definition, permit)
    basis = permit.get("authority_basis")
    if basis is None or basis.get("evaluation_point", "PROPOSE") != "PROPOSE":
        return False
    from . import holdings, flow
    if (holdings.requirements(basis) or flow.requirements(basis)) and step.get("dispatch_gate", {}).get("kind") != "SOURCE_REQUIREMENTS":
        return False
    proposal = basis["proposal"]
    if (basis["work_class"] != lifecycle._authority_projection(definition)
            or basis["source"]["id"] != definition["source"]["id"] or basis["source"]["revision"] != definition["source"]["revision"]
            or [row["id"] for row in basis["source"]["obligations"]] != definition["source"]["obligations"]
            or basis["envelope"]["id"] != step["authority_requirements"][0]
            or proposal["work_class"] != definition["id"] or proposal["instance"] != state["instance_id"]
            or proposal["occurrence"] != permit["occurrence"]["occurrence_id"] or proposal["step"] != step["id"]
            or any(proposal[key] != permit["native_request"][key] for key in ("operation", "interface", "fields"))
            or permit["executor"]["binding_digest"] != digest("executor-binding", proposal["executor"])
            or permit["executor"]["participant_id"] != proposal["executor"]["actor"]
            or permit["executor"]["role"] != proposal["executor"]["role"]
            or permit["credential_ids"] != sorted([row["id"] for row in basis["credentials"]], key=str.encode)
            or permit["observation_digests"] != observation_digests(basis)):
        return False
    clocks = [row for row in state["clocks"] if row["source"] == permit["clock_source"] and row["revision"] == permit["clock_revision"]]
    if len(clocks) != 1 or basis["clock"] != {"source": clocks[0]["source"], "status": "AVAILABLE", "instant": clocks[0]["observed_time"]}:
        return False
    result = authority.evaluate_authority(basis, PIN)
    if result != permit["authority_result"] or result["status"] != "READY_FOR_RESERVATION":
        return False
    if [row["act_digest"] for row in permit["authority_act_bases"]] != result["act_digests"] or any(row["act"] not in basis["acts"] for row in permit["authority_act_bases"]):
        return False
    end = lifecycle._add_seconds(clocks[0]["observed_time"], int(step["permit_seconds"]))
    fixed = basis["envelope"]["temporal_validity"]["valid_until"]
    if fixed is not None:
        end = min(end, fixed)
    replay = next(row for row in state["replays"] if row["permit"] is not None and row["permit"]["permit_id"] == permit["permit_id"])
    for wrapped in replay["budget_results"]:
        receipt = wrapped["result"]["receipt"]
        reservation = next(row for row in wrapped["result"]["state"]["core"]["reservations"] if row["id"] == receipt["reservation"])
        if reservation["authority"] != basis:
            return False
        end = min(end, reservation["permit_until"])
    return permit["expires_at"] == end


def state_integrity(state, definition):
    try:
        return _state_integrity(state, definition)
    except (KeyError, StopIteration, TypeError, ValueError, OverflowError, Refusal):
        return False


def _state_integrity(state, definition):
    from . import completion, lifecycle
    evaluations = state.get("authorization_evaluations", [])
    if len(evaluations) > 128 or [row["event_id"] for row in evaluations] != sorted({row["event_id"] for row in evaluations}, key=str.encode):
        return False
    if len({row["dispatch_intent_id"] for row in evaluations}) != len(evaluations):
        return False
    permits = {row["permit_id"]: row for row in state["permits"]}
    receipts = {row["event_id"]: row for row in state["receipts"]}
    authorizations = {row["authorization_digest"]: row for row in state.get("authorizations", [])}
    previous = {}
    checkpoint = completion._prior_evidence(state, 1, definition) if evaluations else None
    for evaluation in sorted(evaluations, key=lambda row: int(receipts[row["event_id"]]["sequence"]) if row["event_id"] in receipts else -1):
        permit = permits.get(evaluation["permit_digest"])
        receipt = receipts.get(evaluation["event_id"])
        if permit is None or receipt is None or not step_definition(definition, permit).get("dispatch_gate"):
            return False
        gate = step_definition(definition, permit)["dispatch_gate"]
        fresh = evaluation["authority_input"]
        body = copy.deepcopy(evaluation); body.pop("evaluation_digest")
        if (digest("dispatch-authorization-evaluation", body) != evaluation["evaluation_digest"]
                or fresh.get("evaluation_point") != "DISPATCH" or not immutable_binding(permit["authority_basis"], fresh)
                or receipt["event_kind"] != "AUTHORIZE_DISPATCH" or receipt["event_digest"] != evaluation["event_digest"]
                or receipt["permit_digest"] != permit["permit_id"] or receipt["disposition"] != evaluation["disposition"]
                or receipt.get("authorization_evaluation_digest") != evaluation["evaluation_digest"]
                or receipt["authority_result_digest"] != evaluation["authority_result_digest"]
                or digest("authority-result", evaluation["authority_result"]) != evaluation["authority_result_digest"]
                or authority.evaluate_authority(fresh, PIN) != evaluation["authority_result"]):
            return False
        sequence = int(receipt["sequence"])
        prior_state = completion._advance_evidence(checkpoint, state, definition, sequence)
        if prior_state is None:
            prior_state = completion._prior_evidence(state, sequence, definition)
        if lifecycle.state_digest(prior_state) != receipt["state_before_digest"] or not eligible(prior_state, permit):
            return False
        checkpoint = prior_state
        current = accepted_clock(state, permit["clock_source"], sequence)
        issued = next((row for row in state["clocks"] if row["source"] == permit["clock_source"] and row["revision"] == permit["clock_revision"]), None)
        if (current is None or issued is None or current["revision"] != evaluation["clock_revision"]
                or current["status"] == "CONFLICTING"
                or fresh["clock"] != {"source": current["source"], "status": current["status"], "instant": current["observed_time"]}):
            return False
        if current["status"] == "AVAILABLE" and not lifecycle._parse(issued["observed_time"]) <= lifecycle._parse(current["observed_time"]) < lifecycle._parse(permit["expires_at"]):
            return False
        prior = lambda row: row["event_id"] in receipts and int(receipts[row["event_id"]]["sequence"]) < sequence
        if (any(prior(row) and row["permit_digest"] == permit["permit_id"] and (row["attempt"]["status"] != "NOT_SENT" or row["acknowledgement"]["status"] == "ACCEPTED") for row in state["dispatches"])
                or any(prior(row) and row.get("permit_digest") == permit["permit_id"] and row["native_evidence"]["status"] in {"EFFECT_ESTABLISHED", "NO_EFFECT_ESTABLISHED"} for row in state["outcomes"])):
            return False
        authorization = authorizations.get(evaluation["authorization_digest"])
        if evaluation["disposition"] == "WITHHELD":
            if evaluation["authorization_digest"] is not None or evaluation["authority_result"]["status"] != "REFUSED" or evaluation["authority_result"]["code"] in ADMISSION_CODES or any(row["event_id"] == evaluation["event_id"] for row in authorizations.values()):
                return False
        else:
            if authorization is None or evaluation["authority_result"]["status"] != "READY_FOR_RESERVATION":
                return False
            for key in ("event_id", "event_digest", "permit_digest", "dispatch_intent_id", "clock_revision", "authority_input", "authority_result", "authority_result_digest"):
                if authorization.get(key) != evaluation[key]:
                    return False
            if authorization.get("supersedes_authorization_digest") != previous.get(permit["permit_id"]):
                return False
            end = expiry(permit, fresh, gate, current["observed_time"])
            synthetic_event = {"instance_id": state["instance_id"], "permit": permit, **authorization}
            if (authorization["expires_at"] != end or authorization["observation_digests"] != observation_digests(fresh)
                    or authorization["native_request"] != permit["native_request"]
                    or authorization["connector"]["binding_digest"] != digest("connector-binding", {key: authorization["connector"][key] for key in ("id", "version")})
                    or canonical(authorization["authorization_fence"]) != canonical(fence(synthetic_event, evaluation["authority_result"], gate, current["observed_time"], end))):
                return False
            event = {"schema": PREFIX + "runtime-event", "kind": "AUTHORIZE_DISPATCH", "event_id": evaluation["event_id"],
                     "instance_id": state["instance_id"], "expected_state_revision": str(sequence - 1),
                     "expected_state_digest": receipt["state_before_digest"], "permit": permit,
                     **{key: authorization[key] for key in ("native_request", "connector", "authorization_fence", "observation_digests", "clock_revision", "authority_input", "dispatch_intent_id")}}
            if digest("runtime-event", event) != evaluation["event_digest"]:
                return False
            previous[permit["permit_id"]] = authorization["authorization_digest"]
    gated = [row for row in authorizations.values() if step_definition(definition, permits[row["permit_digest"]]).get("dispatch_gate")]
    if any(not any(evaluation["authorization_digest"] == row["authorization_digest"] for evaluation in evaluations) for row in gated):
        return False
    return True
