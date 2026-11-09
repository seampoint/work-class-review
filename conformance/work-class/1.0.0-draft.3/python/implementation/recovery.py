"""Explicit evidence dispositions and retained exception exposure."""

from __future__ import annotations

import base64
import copy
from decimal import Decimal, localcontext

from .common import PIN, Refusal, canonical, digest, utf8_sorted_unique, valid_instant


PROJECTION = ("status", "active", "completed", "obligations", "deadlines", "total_activations", "total_actuations", "step_counters", "fanout_passes")
GENERATION = ("target", "request", "covered_evidence_digests", "superseded_evidence_digests", "attempts", "conclusion", "native_outcomes", "rules_out_past_and_future_effects")


def empty_registry():
    return {"policies": [], "dispositions": [], "contingent": [], "allowances": []}


def projection(state):
    names = PROJECTION + tuple(name for name in ("event_duties", "deferred_deadlines") if name in state)
    return {name: copy.deepcopy(state[name]) for name in names}


def fact(native):
    value = copy.deepcopy(native)
    for name in ("id", "evidence_id", "evidence_ref", "record_digest", "observed_at"):
        value.pop(name, None)
    return value


def generation(evidence, retained=()):
    value = {name: copy.deepcopy(evidence[name]) for name in GENERATION}
    facts = {canonical(fact(row)): fact(row) for row in evidence["native_outcomes"]}
    value["native_outcomes"] = [facts[key] for key in sorted(facts)]
    for name in ("covered_evidence_digests", "superseded_evidence_digests"):
        value[name] = sorted(set(value[name]), key=str.encode)
    return digest("recovery-generation", value)


def subject(event):
    value = copy.deepcopy(event)
    if "payload" in value:
        value["payload"].pop("controller", None)
        value["payload"].pop("authorization", None)
    else:
        value.pop("controller", None)
    return digest("recovery-subject", value)


def inside(validity, instant):
    return (valid_instant(validity["valid_from"]) and (validity["valid_until"] is None or valid_instant(validity["valid_until"]))
            and validity["valid_from"] <= instant and (validity["valid_until"] is None or instant < validity["valid_until"]))


def _numeric_limits(values):
    if any(len(value.lstrip("-").replace(".", "")) > 128 for value in values):
        raise Refusal("LIMIT_EXCEEDED")


def _authenticated(host, expected):
    actual = {(row["kind"], row["record_digest"], row["provider"], row["source"]) for row in host["authenticated_records"]}
    if not actual.issubset(expected):
        raise Refusal("DEPENDENCY_MISMATCH")
    if not expected.issubset(actual):
        raise Refusal("EVIDENCE_UNAVAILABLE")


def _authorize(configuration, principal, scope, kind, event, authorization, host, clock, excluded=(), release=False):
    if authorization is None:
        raise Refusal("ADMINISTRATION_NOT_ESTABLISHED")
    act, returned = authorization["act"], authorization["returned"]
    bases = [row for row in host["recovery_bases"] if row["id"] == act["basis"]]
    if len(bases) != 1:
        raise Refusal("ADMINISTRATION_NOT_ESTABLISHED")
    basis = bases[0]
    role = configuration["policy_owner_role"] if kind in {"ISSUE_POLICY", "REVOKE_POLICY"} else configuration["controller_role"]
    if (basis["principal"] != principal or basis["scope_digest"] != scope
            or (basis["provider"], basis["source"]) != (configuration["provider"], configuration["source"])
            or basis["at"] != clock or act["actor"] != basis["actor"] or act["principal"] != principal
            or act["role"] != role or act["kind"] != kind or act["occurred_at"] != clock
            or act["subject_digest"] != subject(event)):
        raise Refusal("DEPENDENCY_MISMATCH")
    required = {kind} | ({"RELEASE_DISPUTED_EXPOSURE"} if release else set())
    if (basis["kind"] != "HUMAN" or basis["role"] != role or basis["revoked"] or not inside(basis["validity"], clock)
            or not required.issubset(basis["operations"]) or act["disposition"] != "ACCEPT"
            or basis["actor"] in excluded):
        raise Refusal("ADMINISTRATION_NOT_ESTABLISHED")
    try:
        raw = base64.b64decode(returned["act_bytes_base64"], validate=True)
    except (TypeError, ValueError):
        raise Refusal("INPUT_INVALID") from None
    if (raw != canonical(act) or returned["act_digest"] != digest("recovery-act", act)
            or returned["actor"] != act["actor"] or returned["returned_at"] != clock
            or (returned["provider"], returned["source"]) != (configuration["provider"], configuration["source"])):
        raise Refusal("DEPENDENCY_MISMATCH")
    return ("RECOVERY_RETURN", digest("recovery-return", returned), returned["provider"], returned["source"])


def _scope_valid(scope):
    return all(utf8_sorted_unique(scope[name]) and scope[name] for name in ("budget_anchors", "work_classes", "executors", "connectors"))


def policy_event(core, event, host, api):
    configuration = core["configuration"].get("recovery")
    if configuration is None or host.get("recovery") is None:
        raise Refusal("DEPENDENCY_MISMATCH")
    payload, trusted = event["payload"], host["recovery"]
    policy = payload["policy"]
    if policy is None or policy["family"] != payload["family"] or policy["family"] not in configuration["policy_families"]:
        raise Refusal("INPUT_INVALID")
    policy_digest = digest("recovery-policy", policy)
    if payload["policy_digest"] != policy_digest:
        raise Refusal("DEPENDENCY_MISMATCH")
    _numeric_limits([policy["version"], policy["per_incident_limit"], policy["cumulative_limit"]])
    scope = policy["scope"]
    registry_digest = digest("reservation-registry", core["configuration"])
    if (not _scope_valid(scope) or scope["principal"] != core["configuration"]["principal"]
            or scope["registry_digest"] != registry_digest or scope["profile"] not in configuration["exception_profiles"]
            or scope["unit"] != "USD" or scope["window_seconds"] != "86400"
            or Decimal(policy["per_incident_limit"]) < 0 or Decimal(policy["cumulative_limit"]) < 0
            or policy["validity"]["valid_until"] is None
            or not valid_instant(policy["validity"]["valid_from"]) or not valid_instant(policy["validity"]["valid_until"])
            or policy["validity"]["valid_until"] <= policy["validity"]["valid_from"]):
        raise Refusal("INPUT_INVALID")
    family = [row for row in core["recovery"]["policies"] if row["policy"]["family"] == policy["family"]]
    if any(row["policy"]["id"] == policy["id"] and row["policy"] != policy for row in core["recovery"]["policies"]):
        raise Refusal("DEPENDENCY_MISMATCH")
    previous = max(family, key=lambda row: int(row["policy"]["version"])) if family else None
    if previous is not None and previous["policy"]["scope"] != scope:
        raise Refusal("UNSUPPORTED_RELATION")
    operation = "ISSUE_POLICY" if payload["action"] == "ISSUE" else "REVOKE_POLICY"
    auth = _authorize(configuration, scope["principal"], digest("recovery-policy-scope", scope), operation,
                      event, payload["authorization"], trusted, event["clock"]["instant"])
    _authenticated(trusted, {auth})
    if payload["action"] == "ISSUE":
        if (payload["supersedes"] != (None if previous is None else previous["policy_digest"])
                or previous is not None and int(policy["version"]) <= int(previous["policy"]["version"])
                or any(row["policy_digest"] == policy_digest for row in core["recovery"]["policies"])):
            raise Refusal("REVISION_CONFLICT")
        core["recovery"]["policies"].append({"policy": copy.deepcopy(policy), "policy_digest": policy_digest,
            "revoked": False, "event_digest": digest("reservation-event", event), "authorization": copy.deepcopy(payload["authorization"])})
    else:
        if previous is None or previous["policy_digest"] != payload["policy_digest"] or previous["policy"] != policy or previous["revoked"]:
            raise Refusal("REVISION_CONFLICT")
        previous["revoked"] = True
    core["recovery"]["policies"].sort(key=canonical)
    return "POLICY_RECORDED", None, [], None, []


def _evidence_inventory(evidence, target, request, retained, attempt_ids=None):
    if evidence["target"] != target or evidence["request"] != request:
        raise Refusal("DEPENDENCY_MISMATCH")
    reasons = [] if evidence["complete_attempt_inventory"] and evidence["attempts"] else ["RECOVERY_EVIDENCE_INCOMPLETE"]
    for name in ("covered_evidence_digests", "superseded_evidence_digests"):
        if not utf8_sorted_unique(evidence[name]):
            raise Refusal("INPUT_INVALID")
    covered = {digest("recovery-fact", fact(row)) for row in list(retained) + evidence["native_outcomes"]}
    if set(evidence["covered_evidence_digests"]) != covered or not set(evidence["superseded_evidence_digests"]).issubset(covered):
        raise Refusal("DEPENDENCY_MISMATCH")
    ids = [row["id"] for row in evidence["attempts"]]
    if not utf8_sorted_unique(ids) or (attempt_ids is not None and not set(attempt_ids).issubset(ids)):
        raise Refusal("DEPENDENCY_MISMATCH")
    expected_digest = digest("reservation-native-request", request)
    effect_ids = []
    for row in evidence["attempts"]:
        _numeric_limits([row["maximum_executions"]])
        if (row["request_digest"] != expected_digest or int(row["maximum_executions"]) <= 0
                or not utf8_sorted_unique(row["effect_ids"]) or len(row["effect_ids"]) > int(row["maximum_executions"])
                or row["no_effect"] and row["effect_ids"]):
            raise Refusal("DEPENDENCY_MISMATCH")
        effect_ids.extend(row["effect_ids"])
    if len(effect_ids) != len(set(effect_ids)):
        raise Refusal("DEPENDENCY_MISMATCH")
    return reasons


def _attempt_ownership(evidence, retained):
    owners = {effect: attempt["id"] for attempt in evidence["attempts"] for effect in attempt["effect_ids"]}
    for packet in retained:
        for attempt in packet["attempts"]:
            if any(effect in owners and owners[effect] != attempt["id"] for effect in attempt["effect_ids"]):
                raise Refusal("DEPENDENCY_MISMATCH")


def _incident(core, target, reservation):
    return digest("recovery-incident", {"principal": core["configuration"]["principal"],
        "registry_digest": target["registry_digest"], "reservation": reservation["id"],
        "occurrence": reservation["occurrence_key"], "error_class": "DUPLICATE_SEND_UNCERTAINTY"})


def _disposition(incident, evidence, result, policy_digest, controller, supersedes, event, clock, retained):
    generation_digest = generation(evidence, retained)
    body = {"incident_digest": incident, "generation_digest": generation_digest, "result": result,
            "policy_digest": policy_digest, "controller": copy.deepcopy(controller), "supersedes": supersedes}
    return {"id": digest("recovery-disposition", body), **body, "target": copy.deepcopy(evidence["target"]),
        "acceptance_basis_digest": digest("recovery-acceptance-basis", {"incident_digest": incident,
            "generation_digest": generation_digest, "policy_digest": policy_digest}) if result == "ACCEPT_UNRESOLVED" else None,
        "evidence": copy.deepcopy(evidence), "event_digest": digest("reservation-event" if "payload" in event else "runtime-event", event),
        "accepted_at": clock, "source_event": copy.deepcopy(event)}


def _head(rows, target):
    selected = [row for row in rows if row["target"] == target]
    superseded = {row["supersedes"] for row in selected if row["supersedes"] is not None}
    heads = [row for row in selected if row["id"] not in superseded]
    return heads[-1] if heads else None


def registry_coverage(core, target, row):
    retained = [item["native"] for item in core["effects"] if item["reservation"] == target["reservation"]]
    retained.extend(native for old in core["recovery"]["dispositions"] if old["target"] == target for native in old["evidence"]["native_outcomes"])
    covered = set(row["evidence"]["covered_evidence_digests"])
    return all(digest("recovery-fact", fact(native)) in covered for native in retained)


def registry_effective(core, target, clock=None):
    row = _head(core.get("recovery", {}).get("dispositions", []), target)
    if row is None or row["result"] == "LEAVE_UNRESOLVED" or not registry_coverage(core, target, row):
        return None
    if row["result"] == "ESTABLISH_EFFECT":
        from . import reservation_v2
        reservation = next(item for item in core["reservations"] if item["id"] == target["reservation"])
        histories = [(budget, budget["history"]) for budget in core["budgets"]]
        if actual_accounting(core, reservation, histories, reservation_v2, clock=clock)[0]:
            return None
    if row["result"] == "ACCEPT_UNRESOLVED":
        policies = [item for item in core["recovery"]["policies"] if item["policy_digest"] == row["policy_digest"]]
        if len(policies) != 1:
            return None
        policy = policies[0]
        family = [item for item in core["recovery"]["policies"] if item["policy"]["family"] == policy["policy"]["family"]]
        if policy["revoked"] or max(family, key=lambda item: int(item["policy"]["version"]))["policy_digest"] != row["policy_digest"] or clock is None or not inside(policy["policy"]["validity"], clock):
            return None
    return row


def registry_clears(core, reservation, clock=None):
    target = {"kind": "RESERVATION", "registry_digest": digest("reservation-registry", core["configuration"]), "reservation": reservation}
    row = registry_effective(core, target, clock)
    return row is not None and (row["result"] != "ESTABLISH_EFFECT" or not unresolved_executions(row["evidence"])
        and all(not native["completion_mismatch"] and native["observed_request"] == row["evidence"]["request"] for native in selected_actuals(row["evidence"])))


def selected_registry_natives(evidence):
    superseded = set(evidence["superseded_evidence_digests"])
    return [row for row in evidence["native_outcomes"] if digest("recovery-fact", fact(row)) not in superseded]


def selected_actuals(evidence):
    return [row for row in selected_registry_natives(evidence) if row["outcome"] == "EFFECT"]


def attributed_effect_ids(evidence):
    return {row["effect_id"] for row in selected_actuals(evidence)}


def unresolved_executions(evidence):
    if evidence["target"]["kind"] != "RESERVATION":
        return sum(int(row["maximum_executions"]) - len(row["effect_ids"])
                   for row in evidence["attempts"] if not row["no_effect"])
    actual = attributed_effect_ids(evidence)
    return sum(int(row["maximum_executions"]) - len(actual.intersection(row["effect_ids"]))
               for row in evidence["attempts"] if not row["no_effect"])


def _current_policy(core, policy_digest, clock):
    rows = [row for row in core["recovery"]["policies"] if row["policy_digest"] == policy_digest]
    if len(rows) != 1:
        return None
    row = rows[0]
    family = [item for item in core["recovery"]["policies"] if item["policy"]["family"] == row["policy"]["family"]]
    if row["revoked"] or not inside(row["policy"]["validity"], clock) or max(family, key=lambda item: int(item["policy"]["version"]))["policy_digest"] != policy_digest:
        return None
    return row["policy"]


def _controller_excluded(reservation):
    selected = reservation["authority"]
    executor = selected["proposal"]["executor"]["actor"]
    if selected.get("decision_bases"):
        return {executor, *(row["actor"] for row in selected["acts"]),
                *(act["actor"] for basis in selected["decision_bases"] for act in basis["evidence"]["authority_input"]["acts"])}
    gate = selected["envelope"]["gate"]
    kind = {"NONE": None, "VERIFY": "VERIFY", "DECIDE": "INSTANCE_DECISION"}[gate["kind"]]
    return {executor, *(row["actor"] for row in selected["acts"] if row["kind"] == kind and row["role"] == gate["role"]
                        and digest("authority-act", row) in reservation["authority_result"]["act_digests"])}


def _work_controller_excluded(permit):
    from .human_decisions import permit_actors
    basis = permit.get("authority_basis", {})
    executor = permit["executor"]["participant_id"]
    if basis.get("decision_bases"):
        return {executor, *(row["act"]["actor"] for row in permit["authority_act_bases"]), *permit_actors(permit)}
    if basis:
        return _controller_excluded({"authority": basis, "authority_result": permit["authority_result"]})
    return {executor, *(row["act"]["actor"] for row in permit["authority_act_bases"]
                        if row["act"]["kind"] in {"VERIFY", "INSTANCE_DECISION"}
                        and row["act_digest"] in permit["authority_result"]["act_digests"])}


def _history_selection(core, event, reservation, api):
    # Direct current-history dependencies only; scalar/date/prefix integrity and
    # freshness remain after every recovery/history authentication hook.
    histories = event["payload"]["histories"]
    selected = {row["definition"]["anchor"]: row for row in core["budgets"] if row["definition"]["anchor"] in {item["anchor"] for item in reservation["contributions"]}}
    selected_histories = api._select_history_rows(histories, list(selected.values()))
    api._validate_history_bindings(selected_histories)
    return selected_histories


def _histories(core, event, api, host, selected_histories):
    histories = event["payload"]["histories"]
    api._validate_history_authentication(host, histories, core["configuration"])
    api._validate_histories(selected_histories, event["clock"]["instant"], history_array=histories)
    usable, reasons = [], []
    for budget, history in selected_histories:
        if history["status"] != "AVAILABLE":
            reasons.extend(["RECOVERY_EVIDENCE_INCOMPLETE", {"UNAVAILABLE": "HISTORY_UNAVAILABLE", "INCOMPLETE": "HISTORY_INCOMPLETE", "CONFLICT": "HISTORY_CONFLICT"}[history["status"]]])
        elif not history["complete"]:
            reasons.extend(["RECOVERY_EVIDENCE_INCOMPLETE", "HISTORY_INCOMPLETE"])
        elif not api._history_is_fresh(history, budget, event["clock"]["instant"]):
            reasons.extend(["RECOVERY_EVIDENCE_INCOMPLETE", "HISTORY_STALE"])
        else:
            usable.append((budget, history))
    return usable, reasons


def relevant_actuals(core, reservation, evidence=None):
    """Apply retained packet supersession in admitted revision order, retaining bytes."""
    facts = {canonical(fact(row["native"])): row["native"] for row in core["effects"]
             if row["reservation"] == reservation["id"] and row["reason"] != "UNKNOWN_RESERVATION"}
    packets = [row for row in core.get("recovery", {}).get("dispositions", [])
               if row["target"].get("reservation") == reservation["id"]]
    packets.sort(key=lambda row: int(row["source_event"]["expected_revision"]))
    for packet in [*[row["evidence"] for row in packets], *([evidence] if evidence is not None else [])]:
        superseded = set(packet["superseded_evidence_digests"])
        facts = {key: row for key, row in facts.items() if digest("recovery-fact", fact(row)) not in superseded}
        facts.update({canonical(fact(row)): row for row in selected_actuals(packet)})
    return [row for row in facts.values() if row["outcome"] == "EFFECT"]


def foreign_actual_reasons(core, scope):
    # RES-WIRE: no exact class/envelope binding exists for a foreign effect.
    if any(effect["native"]["outcome"] == "EFFECT" and effect["reason"] == "UNKNOWN_RESERVATION" and
           any(scope.get(part["anchor"]) and (part["key"] is None or canonical(part["key"]) in scope[part["anchor"]])
               for part in effect["blocked_partitions"]) for effect in core["effects"]):
        return ["RECOVERY_EVIDENCE_INCOMPLETE"]
    return []


def actual_accounting(core, reservation, selected_histories, api, evidence=None, clock=None, scope=None):
    reasons, amounts = set(), {}
    actuals = relevant_actuals(core, reservation, evidence)
    anchors = {row["anchor"] for row in reservation["contributions"]}
    if not anchors:
        return [], amounts
    selected = [(budget, history) for budget, history in selected_histories
                if budget["definition"]["anchor"] in anchors]
    if not selected:
        return [], amounts
    counts = {}
    for native in actuals:
        counts[native["effect_id"]] = counts.get(native["effect_id"], 0) + 1
    for native in actuals:
        for budget, history in selected:
            anchor = budget["definition"]["anchor"]
            observed = native["observed_request"]
            try:
                actual = api._native_contributions(budget, observed, reservation) if observed is not None else None
            except api._AdmissionError as error:
                if error.code not in {"REFERENCE_INVALID", "TYPE_INVALID"}:
                    raise
                actual = None
            if actual and scope is not None:
                keys = scope.get(anchor, set())
                if not any(canonical(row["key"]) in keys for row in [*actual, *(
                    row for row in reservation["contributions"] if row["anchor"] == anchor)]):
                    continue
            if counts[native["effect_id"]] > 1:
                reasons.update(["RECOVERY_CONFLICT_UNRESOLVED", "RECOVERY_EVIDENCE_INCOMPLETE"])
                continue
            if not actual:
                reasons.add("RECOVERY_EVIDENCE_INCOMPLETE")
                continue
            if not api._history_is_fresh(history, budget, clock or core["last_clock"]):
                reasons.add("RECOVERY_EVIDENCE_INCOMPLETE")
                continue
            for contribution in actual:
                if not api._history_has_prescribed(history, api._prescribed_event(budget, contribution, native["effect_id"], native["occurred_at"])):
                    reasons.update(["RECOVERY_EVIDENCE_INCOMPLETE", "HISTORY_UNCORROBORATED"])
                else:
                    anchor = budget["definition"]["anchor"]
                    if budget["definition"]["aggregate"]["aggregate"]["reducer"] == "SUM":
                        with localcontext() as exact:
                            exact.prec = 512
                            amounts[anchor] = amounts.get(anchor, Decimal(0)) + Decimal(contribution["value"]["value"])
    return sorted(reasons), amounts


def original_actual_substitution(core, reservation, api):
    target = {"kind": "RESERVATION", "registry_digest": digest("reservation-registry", core["configuration"]), "reservation": reservation["id"]}
    head = _head(core.get("recovery", {}).get("dispositions", []), target)
    if (head is None or not head["evidence"]["complete_attempt_inventory"]
            or unresolved_executions(head["evidence"]) or not registry_coverage(core, target, head)):
        return False
    actuals = relevant_actuals(core, reservation)
    owned = {effect for row in head["evidence"]["attempts"] for effect in row["effect_ids"]}
    if not actuals or {row["effect_id"] for row in actuals} != owned:
        return False
    selected = [(budget, budget["history"]) for budget in core["budgets"]]
    return not actual_accounting(core, reservation, selected, api)[0]


def _contingent(core, reservation, evidence, disposition, api):
    if not reservation["contributions"]:
        return []
    count = unresolved_executions(evidence)
    if max(0, count - (reservation["status"] in {"OPEN", "UNKNOWN", "DISPUTED"})) * len(reservation["contributions"]) + sum(row["reservation"] != reservation["id"] for row in core["recovery"]["contingent"]) > 4096:
        raise Refusal("LIMIT_EXCEEDED")
    actual_ids = attributed_effect_ids(evidence)
    unresolved = [(attempt, index) for attempt in evidence["attempts"] if not attempt["no_effect"]
                  for index in range(len(actual_ids.intersection(attempt["effect_ids"])), int(attempt["maximum_executions"]))]
    registry_digest = digest("reservation-registry", core["configuration"])
    rows = []
    for attempt, index in unresolved[1 if reservation["status"] in {"OPEN", "UNKNOWN", "DISPUTED"} else 0:]:
        for contribution in reservation["contributions"]:
            identity = {"registry_digest": registry_digest, "reservation": reservation["id"], "attempt_id": attempt["id"],
                "execution_index": str(index + 1), "anchor": contribution["anchor"], "mapping": contribution["mapping"], "key": contribution["key"]}
            rows.append({"id": digest("recovery-contingent", identity), "disposition_digest": disposition["id"],
                "reservation": reservation["id"], "attempt_id": attempt["id"], "execution_index": str(index + 1), **copy.deepcopy(contribution)})
    return rows


def dispose_registry(core, event, host, api):
    configuration, payload = core["configuration"].get("recovery"), event["payload"]
    trusted = host.get("recovery")
    if configuration is None or trusted is None:
        raise Refusal("DEPENDENCY_MISMATCH")
    target, evidence = payload["target"], payload["evidence"]
    registry_digest = digest("reservation-registry", core["configuration"])
    if target["kind"] != "RESERVATION" or target["registry_digest"] != registry_digest or host["registry_digest"] != registry_digest:
        raise Refusal("DEPENDENCY_MISMATCH")
    reservation = next((row for row in core["reservations"] if row["id"] == target["reservation"]), None)
    if reservation is None:
        raise Refusal("INPUT_INVALID")
    request = api._proposal_native_request(reservation)
    retained = [row["native"] for row in core["effects"] if row["reservation"] == reservation["id"]]
    retained.extend(native for row in core["recovery"]["dispositions"] if row["target"] == target for native in row["evidence"]["native_outcomes"])
    reasons = _evidence_inventory(evidence, target, request, retained)
    _attempt_ownership(evidence, (row["evidence"] for row in core["recovery"]["dispositions"] if row["target"] == target))
    attempts = {row["id"]: row for row in evidence["attempts"]}
    for old in core["recovery"]["dispositions"]:
        if old["target"] != target:
            continue
        for attempt in old["evidence"]["attempts"]:
            current = attempts.get(attempt["id"])
            if current is None or any(current[name] != attempt[name] for name in ("attempt_digest", "executor", "connector", "request_digest")):
                raise Refusal("DEPENDENCY_MISMATCH")
    no_effect = payload["requested_result"] == "ESTABLISH_NO_EFFECT" or payload["requested_result"] == "LEAVE_UNRESOLVED" and evidence["conclusion"] == "NO_EFFECT_ESTABLISHED"
    if not reservation["contributions"]:
        step = next((row for row in reservation["authority"]["work_class"]["steps"] if row["id"] == reservation["authority"]["proposal"]["step"]), None)
        completion = step.get("completion") if step is not None else None
        if not reservation.get("exclusive_keys") or completion is None:
            raise Refusal("UNSUPPORTED_RELATION")
        prefix = "no_effect" if no_effect else "effect"
        if (evidence["provider"], evidence["source"]) != (completion[prefix + "_provider"], completion[prefix + "_source"]):
            raise Refusal("DEPENDENCY_MISMATCH")
    for budget in core["budgets"]:
        if budget["definition"]["anchor"] in {row["anchor"] for row in reservation["contributions"]}:
            declared = budget["definition"]["reservation_policy"]["no_effect" if no_effect else "settlement"]
            if (evidence["provider"], evidence["source"]) != (declared["provider"], declared["source"]):
                raise Refusal("DEPENDENCY_MISMATCH")
    selected_histories = _history_selection(core, event, reservation, api)
    for native in evidence["native_outcomes"]:
        if "outcome" not in native:
            raise Refusal("DEPENDENCY_MISMATCH")
        checked = copy.deepcopy(native)
        if checked["outcome"] == "NO_EFFECT":
            checked["rules_out_past_and_future_effects"] = True
        api._validate_native(checked)
        if ((native["provider"], native["source"]) != (evidence["provider"], evidence["source"])
                or native["reservation"] != target["reservation"] or native["request"] != request):
            raise Refusal("DEPENDENCY_MISMATCH")
    expected = {("RECOVERY_EVIDENCE", digest("recovery-evidence", evidence), evidence["provider"], evidence["source"])}
    desired = payload["requested_result"]
    if desired in {"ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT"}:
        expected.add(_authorize(configuration, core["configuration"]["principal"], digest("recovery-target", target), desired,
            event, payload["controller"], trusted, event["clock"]["instant"], _controller_excluded(reservation), desired == "ESTABLISH_NO_EFFECT"))
    elif payload["controller"] is not None:
        raise Refusal("INPUT_INVALID")
    _authenticated(trusted, expected)
    if any(row["target"] == target and row["record_digest"] != digest("recovery-evidence", evidence) for row in trusted["pending_evidence"]):
        reasons.append("RECOVERY_PENDING_EVIDENCE")
    incident = _incident(core, target, reservation)
    proposed = _disposition(incident, evidence, desired, payload["policy_digest"], payload["controller"], payload["supersedes"], event, event["clock"]["instant"], retained)
    previous = _head(core["recovery"]["dispositions"], target)
    histories, history_reasons = _histories(core, event, api, host, selected_histories)
    # R-i: an unusable history is not adopted and adds no reason to an explicit LEAVE_UNRESOLVED.
    if desired != "LEAVE_UNRESOLVED":
        reasons.extend(reason for reason in history_reasons if desired != "ACCEPT_UNRESOLVED" or reason != "RECOVERY_EVIDENCE_INCOMPLETE")
    policy = _current_policy(core, payload["policy_digest"], event["clock"]["instant"])
    if (not reasons and previous is not None and desired == previous["result"] == "ACCEPT_UNRESOLVED"
            and proposed["acceptance_basis_digest"] is not None and previous["acceptance_basis_digest"] == proposed["acceptance_basis_digest"]
            and policy is not None and trusted["caller"] in policy["scope"]["executors"]):
        for budget, history in histories:
            api._mark_retracted_matches(core, budget, history)
            budget["history"] = copy.deepcopy(history)
        return "DISPOSITION_REUSED", reservation["id"], [], None, [], previous["id"]
    if previous is not None and payload["supersedes"] != previous["id"]:
        raise Refusal("REVISION_CONFLICT")
    if previous is None and payload["supersedes"] is not None:
        raise Refusal("REVISION_CONFLICT")
    if previous is not None and previous["generation_digest"] == proposed["generation_digest"] and previous["result"] != desired and previous["result"] != "LEAVE_UNRESOLVED" and desired != "LEAVE_UNRESOLVED":
        raise Refusal("INPUT_INVALID")
    # R-m: preflight the declared replacement even for incomplete inventories.
    # Arithmetic precedes enumeration; the original reservation supplies one slot.
    projected_rows = max(0, unresolved_executions(evidence) - (reservation["status"] in {"OPEN", "UNKNOWN", "DISPUTED"})) * len(reservation["contributions"])
    other_rows = sum(row["reservation"] != reservation["id"] for row in core["recovery"]["contingent"])
    if projected_rows + other_rows > 4096:
        raise Refusal("LIMIT_EXCEEDED")
    # REC-004/016 and R-k apply to every requested result, including explicit LEAVE.
    native_effects = selected_actuals(evidence)
    actual_ids = {row["effect_id"] for row in native_effects}
    attempt_ids = {effect for row in evidence["attempts"] for effect in row["effect_ids"]}
    if actual_ids != attempt_ids:
        reasons.append("RECOVERY_EVIDENCE_INCOMPLETE")
    if any(row["outcome"] == "NO_EFFECT" and native_effects or
           row["outcome"] == "EFFECT" and not any(fact(selected) == fact(row) for selected in evidence["native_outcomes"])
           for row in [*retained, *evidence["native_outcomes"]] if digest("recovery-fact", fact(row)) not in evidence["superseded_evidence_digests"]):
        reasons.append("RECOVERY_CONFLICT_UNRESOLVED")
    if any(a["effect_id"] == b["effect_id"] and fact(a) != fact(b) for i, a in enumerate(native_effects) for b in native_effects[i + 1:]):
        reasons.append("RECOVERY_CONFLICT_UNRESOLVED")
    # The retraction marking applies when the history is admitted, before this
    # event's own policy evaluation (RESERVATION-RECORDS, ruling R-a).
    for budget, history in histories or []:
        api._mark_retracted_matches(core, budget, history)
    accounting_reasons, actual_amounts = actual_accounting(core, reservation, selected_histories, api, evidence, event["clock"]["instant"])
    reasons.extend(accounting_reasons)
    other_accounting = []
    if desired == "ACCEPT_UNRESOLVED" and len(histories) == len(selected_histories):
        scope = {budget["definition"]["anchor"]: {canonical(row["key"]) for row in reservation["contributions"]
                 if row["anchor"] == budget["definition"]["anchor"]} for budget, _ in selected_histories}
        other_accounting.extend(foreign_actual_reasons(core, scope))
        for other in core["reservations"]:
            if other["id"] != reservation["id"]:
                other_accounting.extend(actual_accounting(core, other, selected_histories, api, clock=event["clock"]["instant"], scope=scope)[0])
        reasons.extend(other_accounting)
    budget_results = []
    contingent_rows = []
    if desired == "ACCEPT_UNRESOLVED" and evidence["complete_attempt_inventory"] and not accounting_reasons and not other_accounting and len(histories) == len(selected_histories):
        contingent_rows = _contingent(core, reservation, evidence, proposed, api)
        assessed_core = copy.deepcopy(core)
        assessed_core["last_clock"] = event["clock"]["instant"]
        for budget, history in histories:
            next(row for row in assessed_core["budgets"] if row["definition_digest"] == budget["definition_digest"])["history"] = history
        for budget, history in histories or []:
            authorization, projected = api._projection_for(budget["authorizations"], reservation["authority"], budget)
            contributions = [row for row in reservation["contributions"] if row["anchor"] == budget["definition"]["anchor"]]
            # REC-010 constructs the whole anchor inventory before AGG partitions by key.
            # Key prefiltering changes R-n's request-size refusal and is not equivalent.
            anchor = budget["definition"]["anchor"]
            keys = [row["key"] for other in core["reservations"] for row in other["contributions"] if row["anchor"] == anchor]
            keys.extend(row["key"] for row in core["recovery"]["contingent"] if row["anchor"] == anchor)
            pending = api._pending_for(assessed_core, anchor, keys, reservation["id"])
            pending.extend({"reservation": row["id"], **{name: copy.deepcopy(row[name]) for name in ("anchor", "mapping", "key", "value")}, "occurrence": row["id"]} for row in contingent_rows if row["anchor"] == budget["definition"]["anchor"])
            pending.sort(key=lambda row: canonical([row["reservation"], row["mapping"], row["occurrence"], row["key"]]))
            # R-n: the recovery row bound does not enlarge AGG's request bound.
            if len(pending) > 1024:
                raise Refusal("LIMIT_EXCEEDED")
            aggregate_request = api._aggregate_request(budget, reservation["authority"], projected, contributions, history, event["clock"], pending, api.PIN)
            # Keep the originating scope to select the history partitions even
            # when no original pending execution supplies a contribution.
            use_original = reservation["status"] in {"OPEN", "UNKNOWN", "DISPUTED"} and (
                unresolved_executions(evidence) or not relevant_actuals(core, reservation, evidence))
            aggregate_result = api._evaluate_aggregate(aggregate_request, api.PIN, charge_operations=bool(use_original))
            budget_results.append({"anchor": budget["definition"]["anchor"], "result": aggregate_result})
            if aggregate_result["status"] != "SATISFIED":
                reasons.append("BOUND_VIOLATED" if aggregate_result["status"] == "VIOLATED" else "HISTORY_INCOMPLETE")
    if desired == "ESTABLISH_EFFECT":
        # R-j: absence of establishment and an affirmative exclusion are independent.
        if evidence["conclusion"] != "EFFECT_ESTABLISHED":
            reasons.append("RECOVERY_EVIDENCE_INCOMPLETE")
        if evidence["rules_out_past_and_future_effects"]:
            reasons.append("RECOVERY_CONFLICT_UNRESOLVED")
        effects, conflicting_effects = {}, set()
        for native in native_effects:
            old = effects.get(native["effect_id"])
            if old is not None and fact(old) != fact(native):
                reasons.append("RECOVERY_CONFLICT_UNRESOLVED")
                conflicting_effects.add(native["effect_id"])
            effects.setdefault(native["effect_id"], native)
        attempt_effects = {effect for row in evidence["attempts"] for effect in row["effect_ids"]}
        if set(effects) != attempt_effects or not effects:
            reasons.append("RECOVERY_EVIDENCE_INCOMPLETE")
        chosen_facts = {canonical(fact(row)) for row in effects.values()}
        if any(canonical(fact(row)) not in chosen_facts and row["outcome"] in {"EFFECT", "NO_EFFECT"}
               and digest("recovery-fact", fact(row)) not in evidence["superseded_evidence_digests"] for row in retained):
            reasons.append("RECOVERY_CONFLICT_UNRESOLVED")
        for native in effects.values():
            if native["effect_id"] in conflicting_effects:
                continue
            api._validate_native(native)
            for budget, history in histories or []:
                policy = budget["definition"]["reservation_policy"]["settlement"]
                if (evidence["provider"], evidence["source"]) != (policy["provider"], policy["source"]) or (native["provider"], native["source"]) != (policy["provider"], policy["source"]):
                    raise Refusal("DEPENDENCY_MISMATCH")
    elif desired == "ESTABLISH_NO_EFFECT":
        if (evidence["conclusion"] != "NO_EFFECT_ESTABLISHED" or not evidence["rules_out_past_and_future_effects"]
                or any(not row["no_effect"] or row["effect_ids"] for row in evidence["attempts"])):
            reasons.append("RECOVERY_EVIDENCE_INCOMPLETE")
        if any(row["outcome"] == "EFFECT" and digest("recovery-fact", fact(row)) not in evidence["superseded_evidence_digests"] for row in retained):
            reasons.append("RECOVERY_CONFLICT_UNRESOLVED")
        if not evidence["native_outcomes"] or any(row.get("outcome") != "NO_EFFECT" or row["request"] != request or not row["rules_out_past_and_future_effects"] for row in evidence["native_outcomes"]):
            reasons.append("RECOVERY_EVIDENCE_INCOMPLETE")
        for budget, _ in histories or []:
            policy = budget["definition"]["reservation_policy"]["no_effect"]
            if (evidence["provider"], evidence["source"]) != (policy["provider"], policy["source"]):
                raise Refusal("DEPENDENCY_MISMATCH")
    elif desired == "ACCEPT_UNRESOLVED":
        prior_allowances = copy.deepcopy(core["recovery"]["allowances"])
        reasons.extend(_exception(core, reservation, evidence, proposed, trusted, histories, api, not accounting_reasons, actual_amounts))
        if reasons:
            core["recovery"]["allowances"] = prior_allowances
    elif desired != "LEAVE_UNRESOLVED":
        raise Refusal("INPUT_INVALID")
    for budget, history in histories:
        budget["history"] = copy.deepcopy(history)
    if reasons or desired == "LEAVE_UNRESOLVED":
        proposed = _disposition(incident, evidence, "LEAVE_UNRESOLVED", payload["policy_digest"], payload["controller"], payload["supersedes"], event, event["clock"]["instant"], retained)
    else:
        core["recovery"]["contingent"] = [row for row in core["recovery"]["contingent"] if row["reservation"] != reservation["id"]]
        if desired == "ACCEPT_UNRESOLVED":
            core["recovery"]["contingent"].extend(_contingent(core, reservation, evidence, proposed, api))
        elif desired == "ESTABLISH_EFFECT" and unresolved_executions(evidence):
            core["recovery"]["contingent"].extend(_contingent(core, reservation, evidence, proposed, api))
    # R-h: a retained LEAVE_UNRESOLVED, requested or fallen back to, replaces the rows like an acceptance.
    if (desired == "ACCEPT_UNRESOLVED" or proposed["result"] == "LEAVE_UNRESOLVED") and evidence["complete_attempt_inventory"] and evidence["attempts"] and all(
            int(row["maximum_executions"]) > 0 and row["request_digest"] == digest("reservation-native-request", request)
            for row in evidence["attempts"]):
        core["recovery"]["contingent"] = [row for row in core["recovery"]["contingent"] if row["reservation"] != reservation["id"]] + _contingent(core, reservation, evidence, proposed, api)
    core["recovery"]["dispositions"].append(proposed)
    core["recovery"]["dispositions"].sort(key=canonical)
    core["recovery"]["contingent"].sort(key=canonical)
    core["recovery"]["allowances"].sort(key=canonical)
    return "WITHHELD" if reasons else "DISPOSITION_RECORDED", reservation["id"], sorted(budget_results, key=lambda row: row["anchor"]), None, sorted(set(reasons), key=str.encode), proposed["id"]


def _exception(core, reservation, evidence, disposition, host, histories, api, assessed=True, actual_amounts=None):
    with localcontext() as context:
        context.prec = 512
        return _exception_exact(core, reservation, evidence, disposition, host, histories, api, assessed, actual_amounts)


def _exception_exact(core, reservation, evidence, disposition, host, histories, api, assessed=True, actual_amounts=None):
    configuration = core["configuration"]["recovery"]
    reasons = []
    if ("MONETARY_DUPLICATE_SEND" not in configuration["exception_profiles"] or not reservation["contributions"]
            or len(histories) != len({row["anchor"] for row in reservation["contributions"]})):
        reasons.append("RECOVERY_EXCEPTION_INELIGIBLE")
    native_rows = [row["native"] for row in core["effects"] if row["reservation"] == reservation["id"]] + evidence["native_outcomes"]
    native_rows.extend(native for row in core["recovery"]["dispositions"] if row["target"].get("reservation") == reservation["id"] for native in row["evidence"]["native_outcomes"])
    if (not evidence["complete_attempt_inventory"] or evidence["conclusion"] != "UNRESOLVED" or evidence["rules_out_past_and_future_effects"]
            or sum(int(row["maximum_executions"]) for row in evidence["attempts"]) < 2 or any(row["effect_ids"] or row["no_effect"] for row in evidence["attempts"])
            or any(row.get("outcome") in {"EFFECT", "NO_EFFECT"} or row.get("request") != evidence["request"] or row.get("observed_request") not in (None, evidence["request"]) for row in native_rows)):
        reasons.append("RECOVERY_EXCEPTION_INELIGIBLE")
    policies = [row for row in core["recovery"]["policies"] if row["policy_digest"] == disposition["policy_digest"]]
    if len(policies) != 1:
        return [*reasons, "RECOVERY_POLICY_INVALID"]
    record, clock = policies[0], disposition["accepted_at"]
    policy, scope = record["policy"], record["policy"]["scope"]
    family = [row for row in core["recovery"]["policies"] if row["policy"]["family"] == policy["family"]]
    proposal = reservation["authority"]["proposal"]
    if (record["revoked"] or max(family, key=lambda row: int(row["policy"]["version"]))["policy_digest"] != record["policy_digest"] or not inside(policy["validity"], clock)
            or proposal["work_class"] not in scope["work_classes"] or host["caller"] not in scope["executors"]
            or any(row["executor"] not in scope["executors"] or row["connector"] not in scope["connectors"] for row in evidence["attempts"])):
        reasons.append("RECOVERY_POLICY_INVALID")
    if not assessed:
        return reasons
    total_executions = unresolved_executions(evidence)
    amounts = {}
    for contribution in reservation["contributions"]:
        budget = next(row for row in core["budgets"] if row["definition"]["anchor"] == contribution["anchor"])
        aggregate = budget["definition"]["aggregate"]["aggregate"]
        declaration = api._definition_types(budget["definition"])[aggregate["result_type"]]
        if (aggregate["reducer"] != "SUM" or declaration.get("unit") != "USD" or not declaration.get("nonnegative")
                or contribution["anchor"] not in scope["budget_anchors"]):
            reasons.append("RECOVERY_EXCEPTION_INELIGIBLE")
            continue
        amounts[contribution["anchor"]] = amounts.get(contribution["anchor"], Decimal(0)) + Decimal(contribution["value"]["value"]) * total_executions
    for anchor, amount in (actual_amounts or {}).items():
        if anchor in amounts:
            amounts[anchor] += amount
    if any(amount > Decimal(policy["per_incident_limit"]) for amount in amounts.values()):
        reasons.append("RECOVERY_INCIDENT_LIMIT_EXCEEDED")
    rows = []
    for budget, amount in amounts.items():
        for kind, actors in (("BUDGET", {budget}), ("EXECUTOR", {row["executor"] for row in evidence["attempts"]}), ("CONNECTOR", {row["connector"] for row in evidence["attempts"]})):
            for actor in actors:
                previous = sum((Decimal(row["amount"]) for row in core["recovery"]["allowances"] if row["policy_family"] == policy["family"] and row["budget"] == budget and row["actor_kind"] == kind and row["actor"] == actor
                                and 0 <= (api._parse_time(clock) - api._parse_time(row["accepted_at"])).total_seconds() < 86400), Decimal(0))
                if previous + amount > Decimal(policy["cumulative_limit"]):
                    reasons.append("RECOVERY_ALLOWANCE_EXCEEDED")
                rows.append({"acceptance_basis_digest": disposition["acceptance_basis_digest"], "policy_family": policy["family"],
                    "budget": budget, "actor_kind": kind, "actor": actor, "amount": format(amount, "f").rstrip("0").rstrip(".") if "." in format(amount, "f") else format(amount, "f"), "accepted_at": clock})
    if not reasons:
        core["recovery"]["allowances"].extend(rows)
    return reasons


def _work_target(state, target):
    if target["kind"] != "WORK_OUTCOME" or target["instance_id"] != state["instance_id"]:
        raise Refusal("DEPENDENCY_MISMATCH")
    outcome = next((row for row in state["outcomes"] if row["outcome_digest"] == target["outcome_digest"]), None)
    permit = None if outcome is None else next((row for row in state["permits"] if row["permit_id"] == outcome["permit_digest"]), None)
    if permit is None or permit["occurrence"]["occurrence_id"] != target["occurrence_id"]:
        raise Refusal("DEPENDENCY_MISMATCH")
    return outcome, permit


def relevant_work_outcomes(state, permit_id):
    evidence_ids = {row["native_evidence"]["evidence_id"] for row in state["outcomes"] if row["permit_digest"] == permit_id}
    changed = True
    while changed:
        previous = set(evidence_ids)
        for row in state["outcomes"]:
            if row["native_evidence"]["evidence_id"] in evidence_ids or set(row["conflicts_with_evidence_ids"]) & evidence_ids:
                evidence_ids.add(row["native_evidence"]["evidence_id"])
                evidence_ids.update(row["conflicts_with_evidence_ids"])
        changed = evidence_ids != previous
    return [row for row in state["outcomes"] if row["native_evidence"]["evidence_id"] in evidence_ids]


def work_effective(state, outcome):
    candidates = [row["disposition"] for row in state.get("recovery_records", [])
                  if row["disposition"]["target"]["kind"] == "WORK_OUTCOME"
                  and row["disposition"]["target"]["outcome_digest"] == outcome["outcome_digest"]]
    if not candidates:
        return None
    row = _head(candidates, candidates[-1]["target"])
    if row is None or row["result"] != "ESTABLISH_EFFECT" or unresolved_executions(row["evidence"]) or not _current_work_coverage(state, row):
        return None
    retained = [item["native_evidence"] for item in relevant_work_outcomes(state, outcome["permit_digest"])]
    retained.extend(native for item in candidates for native in item["evidence"]["native_outcomes"])
    known = set(row["evidence"]["covered_evidence_digests"]) | {digest("recovery-fact", fact(item)) for item in row["evidence"]["native_outcomes"]}
    if any(digest("recovery-fact", fact(item)) not in known for item in retained):
        return None
    if not any(fact(item) == fact(outcome["native_evidence"]) for item in row["evidence"]["native_outcomes"]):
        return None
    return row


def native_evidence(disposition, completion):
    result = []
    natives = disposition["evidence"]["native_outcomes"] if disposition["target"]["kind"] == "WORK_OUTCOME" else selected_registry_natives(disposition["evidence"])
    for native in natives:
        if disposition["target"]["kind"] == "WORK_OUTCOME":
            result.append(copy.deepcopy(native))
            continue
        no_effect = native["outcome"] == "NO_EFFECT"
        request = native["request"]
        result.append({"evidence_id": native["id"], "native_operation_id": native["effect_id"] or native["id"],
            "provider": native["provider"], "source": native["source"],
            "record_type": completion["no_effect_record_type" if no_effect else "effect_record_type"],
            "record_digest": disposition["evidence"]["record_digest"], "evidence_ref": native["evidence_ref"],
            "attributed_request": copy.deepcopy(request), "native_request_digest": digest("native-request", request),
            "status": "NO_EFFECT_ESTABLISHED" if no_effect else "EFFECT_ESTABLISHED" if native["outcome"] == "EFFECT" else "OUTCOME_UNKNOWN",
            "actual_fields": copy.deepcopy(native["actual_fields"]), "collections": copy.deepcopy(native["collections"]),
            "event_time": native["occurred_at"], "observed_at": disposition["accepted_at"],
            "rules_out_past_and_future_effects": native["rules_out_past_and_future_effects"]})
    return result


def _current_work_coverage(state, disposition):
    target = disposition["target"]
    candidates = [row["disposition"] for row in state.get("recovery_records", []) if row["disposition"]["target"] == target]
    head = _head(candidates, target)
    if head is None or head["id"] != disposition["id"]:
        return False
    if not disposition["evidence"]["complete_attempt_inventory"]:
        return False
    target_outcome = next((row for row in state["outcomes"] if row["outcome_digest"] == target["outcome_digest"]), None)
    if target_outcome is None:
        return False
    target_permit = next((row for row in state["permits"] if row["permit_id"] == target_outcome["permit_digest"]), None)
    if target_permit is None:
        return False
    occurrence_id = target_permit["occurrence"]["occurrence_id"]
    permits = {row["permit_id"] for row in state["permits"] if row["occurrence"]["occurrence_id"] == occurrence_id}
    attempts = {row["attempt_digest"] for row in disposition["evidence"]["attempts"]}
    if not {row["dispatch_attempt_digest"] for row in state["dispatches"] if row["permit_digest"] in permits}.issubset(attempts):
        return False
    retained = [row["native_evidence"] for permit in permits for row in relevant_work_outcomes(state, permit)]
    retained.extend(native for row in candidates for native in row["evidence"]["native_outcomes"])
    covered = set(disposition["evidence"]["covered_evidence_digests"])
    covered.update(digest("recovery-fact", fact(row)) for row in disposition["evidence"]["native_outcomes"])
    return all(digest("recovery-fact", fact(row)) in covered for row in retained)


def derived_outcomes(state, definition, current=False):
    result = {}
    steps = {row["id"]: row for row in definition["steps"]}
    for record in state.get("recovery_records", []):
        disposition = record["disposition"]
        if disposition["result"] != "ESTABLISH_EFFECT" or unresolved_executions(disposition["evidence"]):
            continue
        if current and disposition["target"]["kind"] == "WORK_OUTCOME" and not _current_work_coverage(state, disposition):
            continue
        before_ids = {row["occurrence"]["occurrence_id"] for row in record["before_projection"]["completed"]}
        for completed in record["after_projection"]["completed"]:
            occurrence = completed["occurrence"]
            if occurrence["occurrence_id"] in before_ids or completed["disposition"] != "SUCCEEDED":
                continue
            permits = [row for row in state["permits"] if row["occurrence"]["occurrence_id"] == occurrence["occurrence_id"]]
            if disposition["target"]["kind"] == "RESERVATION":
                permits = [row for row in permits if any(binding["registry_digest"] == disposition["target"]["registry_digest"] and binding["reservation_id"] == disposition["target"]["reservation"] for binding in row["budget_revisions"])]
            for evidence in native_evidence(disposition, steps[occurrence["step_id"]]["completion"]):
                if digest("native-evidence", evidence) == completed["evidence_digest"] and permits:
                    selected = permits[-1]
                    if steps[occurrence["step_id"]]["completion"].get("authorization_revision_bindings"):
                        matched = _recovery_dispatch(state, permits, evidence, disposition)
                        if matched is None:
                            continue
                        selected, _ = matched
                    result[(selected["permit_id"], completed["evidence_digest"])] = {"kind": "GOVERNED", "classification": "MATCHED", "disputed": False,
                        "permit_digest": selected["permit_id"], "native_evidence": evidence}
    return list(result.values())


def factual_outcomes(state, definition, current=False):
    result = list(state["outcomes"])
    identities = {(row["permit_digest"], digest("native-evidence", row["native_evidence"])) for row in result}
    for row in derived_outcomes(state, definition, current):
        if (row["permit_digest"], digest("native-evidence", row["native_evidence"])) not in identities:
            result.append(row)
    return result


def completed_integrity(completed, definition, records):
    step = next(row for row in definition["steps"] if row["id"] == completed["occurrence"]["step_id"])
    for record in records:
        disposition = record["disposition"]
        if completed not in record["after_projection"]["completed"] or completed in record["before_projection"]["completed"]:
            continue
        if disposition["result"] not in {"ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT"}:
            continue
        if any(digest("native-evidence", evidence) == completed["evidence_digest"] for evidence in native_evidence(disposition, step["completion"])):
            return True
    return False


def _work_clock(state, event, permit, api):
    clocks = [row for row in state["clocks"] if row["source"] == permit["clock_source"]]
    if not clocks:
        raise Refusal("CLOCK_INVALID")
    clock = max(clocks, key=lambda row: int(row["revision"]))
    if clock["status"] != "AVAILABLE" or clock["revision"] != event["clock_revision"]:
        raise Refusal("CLOCK_INVALID")
    return clock


def _work_dispose(request):
    from . import lifecycle
    state, event, definition = request["state"], request["event"], request["definition"]
    configuration, host = definition.get("recovery"), request.get("recovery_host")
    if configuration is None or host is None:
        raise Refusal("EVIDENCE_UNAVAILABLE")
    outcome, permit = _work_target(state, event["target"])
    if permit["budget_revisions"]:
        raise Refusal("DEPENDENCY_MISMATCH")
    clock = _work_clock(state, event, permit, lifecycle)
    target, evidence = event["target"], event["evidence"]
    desired = event["requested_result"]
    if desired == "ACCEPT_UNRESOLVED":
        raise Refusal("INPUT_INVALID")
    step = next(row for row in definition["steps"] if row["id"] == permit["occurrence"]["step_id"])
    expected_request = {"work_class": definition["id"], "instance": state["instance_id"], "occurrence": target["occurrence_id"], "step": step["id"], **permit["native_request"]}
    retained = [row["native_evidence"] for row in relevant_work_outcomes(state, permit["permit_id"])]
    retained.extend(native for row in state.get("recovery_records", []) if row["disposition"]["target"] == target for native in row["disposition"]["evidence"]["native_outcomes"])
    occurrence_permits = [row for row in state["permits"] if row["occurrence"]["occurrence_id"] == permit["occurrence"]["occurrence_id"]]
    attempts = [group for item in occurrence_permits for group in lifecycle._dispatch_attempt_groups(state, item["permit_id"])]
    attempt_ids = {group["records"][-1]["attempt"]["attempt_id"] for group in attempts}
    retained_packets = [row["disposition"]["evidence"] for row in state.get("recovery_records", []) if row["disposition"]["target"] == target]
    attempt_ids.update(attempt["id"] for packet in retained_packets for attempt in packet["attempts"])
    reasons = _evidence_inventory(evidence, target, expected_request, retained, attempt_ids)
    _attempt_ownership(evidence, retained_packets)
    retained_attempts = {group["records"][-1]["attempt"]["attempt_id"]: group for group in attempts}
    local_digests = {group["digest"]: attempt_id for attempt_id, group in retained_attempts.items()}
    for attempt in evidence["attempts"]:
        group = retained_attempts.get(attempt["id"])
        if attempt["attempt_digest"] in local_digests and local_digests[attempt["attempt_digest"]] != attempt["id"]:
            raise Refusal("DEPENDENCY_MISMATCH")
        if group is not None:
            dispatch = group["records"][-1]
            if (attempt["attempt_digest"] != group["digest"] or attempt["executor"] != permit["executor"]["participant_id"]
                    or attempt["connector"] != dispatch["connector"]["id"]):
                raise Refusal("DEPENDENCY_MISMATCH")
    supplied_attempts = {row["id"]: row for row in evidence["attempts"]}
    for packet in retained_packets:
        for attempt in packet["attempts"]:
            current = supplied_attempts[attempt["id"]]
            if any(current[name] != attempt[name] for name in ("attempt_digest", "executor", "connector", "request_digest")):
                raise Refusal("DEPENDENCY_MISMATCH")
    principal = state["deployment_organization_id"]
    expected = {("RECOVERY_EVIDENCE", digest("recovery-evidence", evidence), evidence["provider"], evidence["source"])}
    if desired in {"ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT"}:
        expected.add(_authorize(configuration, principal, digest("recovery-target", target), desired, event,
            event["controller"], host, clock["observed_time"], _work_controller_excluded(permit)))
    elif event["controller"] is not None:
        raise Refusal("INPUT_INVALID")
    _authenticated(host, expected)
    provider = step["completion"]
    no_effect = desired == "ESTABLISH_NO_EFFECT" or desired == "LEAVE_UNRESOLVED" and evidence["conclusion"] == "NO_EFFECT_ESTABLISHED"
    pair = (provider["no_effect_provider"], provider["no_effect_source"]) if no_effect else (provider["effect_provider"], provider["effect_source"])
    if (evidence["provider"], evidence["source"]) != pair:
        raise Refusal("DEPENDENCY_MISMATCH")
    for native in evidence["native_outcomes"]:
        record_type = provider["no_effect_record_type"] if native.get("status") == "NO_EFFECT_ESTABLISHED" else provider["effect_record_type"]
        if ("status" not in native or (native["provider"], native["source"]) != pair or native["attributed_request"] != expected_request
                or native["native_request_digest"] != digest("native-request", expected_request) or native["record_type"] != record_type):
            raise Refusal("DEPENDENCY_MISMATCH")
    if any(row["target"] == target and row["record_digest"] != digest("recovery-evidence", evidence) for row in host["pending_evidence"]):
        reasons.append("RECOVERY_PENDING_EVIDENCE")
    selected_facts = {digest("recovery-fact", fact(row)) for row in evidence["native_outcomes"]}
    if any(row["status"] in {"EFFECT_ESTABLISHED", "NO_EFFECT_ESTABLISHED"}
           and digest("recovery-fact", fact(row)) not in selected_facts | set(evidence["superseded_evidence_digests"]) for row in retained):
        reasons.append("RECOVERY_CONFLICT_UNRESOLVED")
    actual_ids = {row["native_operation_id"] for row in evidence["native_outcomes"] if row.get("status") == "EFFECT_ESTABLISHED"}
    attributed_ids = {value for attempt in evidence["attempts"] for value in attempt["effect_ids"]}
    if actual_ids != attributed_ids:
        reasons.append("RECOVERY_EVIDENCE_INCOMPLETE")
    superseded_facts = set(evidence["superseded_evidence_digests"])
    native_facts = {}
    for native in evidence["native_outcomes"]:
        if native["status"] == "OUTCOME_UNKNOWN":
            continue
        operation = native["native_operation_id"]
        normalized = fact(native)
        if digest("recovery-fact", normalized) in superseded_facts:
            continue
        if operation in native_facts and native_facts[operation] != normalized:
            reasons.append("RECOVERY_CONFLICT_UNRESOLVED")
        native_facts.setdefault(operation, normalized)
    if desired == "ESTABLISH_EFFECT":
        if (evidence["conclusion"] != "EFFECT_ESTABLISHED" or not evidence["native_outcomes"]
                or any(row["status"] != "EFFECT_ESTABLISHED" or row["attributed_request"] != expected_request for row in evidence["native_outcomes"])):
            reasons.append("RECOVERY_EVIDENCE_INCOMPLETE")
        if evidence["rules_out_past_and_future_effects"]:
            reasons.append("RECOVERY_CONFLICT_UNRESOLVED")
    elif desired == "ESTABLISH_NO_EFFECT":
        if (evidence["conclusion"] != "NO_EFFECT_ESTABLISHED" or not evidence["rules_out_past_and_future_effects"]
                or any(not row["no_effect"] or row["effect_ids"] for row in evidence["attempts"])
                or not evidence["native_outcomes"] or any(row.get("status") != "NO_EFFECT_ESTABLISHED"
                    or row["attributed_request"] != expected_request or not row["rules_out_past_and_future_effects"] for row in evidence["native_outcomes"])):
            reasons.append("RECOVERY_EVIDENCE_INCOMPLETE")
    incident = digest("recovery-incident", {"principal": principal, "target": target})
    result = "LEAVE_UNRESOLVED" if reasons else desired
    disposition = _disposition(incident, evidence, result, None, event["controller"], event["supersedes"], event, clock["observed_time"], retained)
    previous = _head([row["disposition"] for row in state.get("recovery_records", [])], target)
    if previous is not None and event["supersedes"] != previous["id"]:
        raise Refusal("REVISION_CONFLICT")
    if previous is None and event["supersedes"] is not None:
        raise Refusal("REVISION_CONFLICT")
    return disposition, host, permit, sorted(set(reasons), key=str.encode)


def _registry_selection(selection):
    from . import reservation_v2
    state = selection["state"]
    if (selection["state_digest"] != reservation_v2._state_digest(state)
            or state["specification_pin"] != PIN or not reservation_v2._replay_state(state, PIN)
            or selection["host_evidence"]["registry_digest"] != digest("reservation-registry", state["core"]["configuration"])):
        raise Refusal("STATE_INVALID")
    return state


def _registry_clock(core, instant):
    from .lifecycle import _parse
    if instant is not None and core["last_clock"] is not None and _parse(instant) < _parse(core["last_clock"]):
        raise Refusal("CLOCK_INVALID")


def _apply_registry(request):
    from . import lifecycle
    event, state = request["event"], request["state"]
    if request["definition"].get("recovery") is None:
        raise Refusal("DEPENDENCY_MISMATCH")
    registry = _registry_selection(event["registry"])
    target = event["target"]
    disposition = next((row for row in registry["core"].get("recovery", {}).get("dispositions", []) if row["id"] == event["disposition_digest"]), None)
    if disposition is None or disposition["target"] != target:
        raise Refusal("DEPENDENCY_MISMATCH")
    reservation = next((row for row in registry["core"]["reservations"] if row["id"] == target["reservation"]), None)
    if reservation is None:
        raise Refusal("DEPENDENCY_MISMATCH")
    proposal = reservation["authority"]["proposal"]
    declared = {anchor for step in request["definition"]["steps"] for anchor in step.get("shared_budgets", [])}
    if not {row["anchor"] for row in reservation["contributions"]}.issubset(declared):
        raise Refusal("DEPENDENCY_MISMATCH")
    permits = [row for row in state["permits"] if any(binding["registry_digest"] == target["registry_digest"] and binding["reservation_id"] == target["reservation"] for binding in row["budget_revisions"])]
    permit = next((row for row in permits if row["occurrence"]["occurrence_id"] == proposal["occurrence"] and proposal["instance"] == state["instance_id"]), None)
    if permit is None:
        clocks = [row for row in state["clocks"] if row["source"] == registry["core"]["configuration"]["clock_source"]]
        if not clocks:
            raise Refusal("CLOCK_INVALID")
        clock = max(clocks, key=lambda row: int(row["revision"]))
        if clock["status"] != "AVAILABLE" or clock["revision"] != event["clock_revision"]:
            raise Refusal("CLOCK_INVALID")
    else:
        clock = _work_clock(state, event, permit, lifecycle)
    _registry_clock(registry["core"], clock["observed_time"])
    effective = registry_effective(registry["core"], target, clock["observed_time"])
    if disposition["result"] != "LEAVE_UNRESOLVED" and (effective is None or effective["id"] != disposition["id"]):
        raise Refusal("EVIDENCE_UNAVAILABLE")
    host = request.get("recovery_host") or event["registry"]["host_evidence"].get("recovery")
    if host is None:
        raise Refusal("EVIDENCE_UNAVAILABLE")
    registry_pending = event["registry"]["host_evidence"].get("recovery", {}).get("pending_evidence", [])
    if any(row["target"] == target for row in host["pending_evidence"] + registry_pending):
        raise Refusal("EVIDENCE_UNAVAILABLE")
    return disposition, host, permit, []


def _dispatch_cause_covered(state, occurrence_id):
    permits = [row for row in state["permits"] if row["occurrence"]["occurrence_id"] == occurrence_id]
    permit_ids = {row["permit_id"] for row in permits}
    known_attempts = {row["dispatch_attempt_digest"] for row in state["dispatches"] if row["permit_digest"] in permit_ids}
    retained = [row["native_evidence"] for row in state["outcomes"] if row["permit_digest"] in permit_ids]
    for record in state.get("recovery_records", []):
        disposition = record["disposition"]
        if disposition["result"] != "ESTABLISH_EFFECT" or unresolved_executions(disposition["evidence"]):
            continue
        target = disposition["target"]
        if target["kind"] == "WORK_OUTCOME":
            if target["occurrence_id"] != occurrence_id or not _current_work_coverage(state, disposition):
                continue
        else:
            if not any(any(binding["registry_digest"] == target["registry_digest"] and binding["reservation_id"] == target["reservation"] for binding in permit["budget_revisions"]) for permit in permits):
                continue
            registry = record["event"].get("registry", {}).get("state", {}).get("core")
            if registry is None or registry_effective(registry, target) != disposition:
                continue
        evidence = disposition["evidence"]
        if not evidence["complete_attempt_inventory"] or not known_attempts.issubset({row["attempt_digest"] for row in evidence["attempts"]}):
            continue
        covered = set(evidence["covered_evidence_digests"])
        covered.update(digest("recovery-fact", fact(row)) for row in evidence["native_outcomes"])
        if all(digest("recovery-fact", fact(row)) in covered for row in retained):
            return True
    return False


def _unresolved_roots(state, definition):
    from . import lifecycle

    completed = {row["occurrence"]["occurrence_id"] for row in state["completed"]}
    permits = {row["permit_id"]: row for row in state["permits"]}
    roots = set()
    derived_permits = {row["permit_digest"] for row in derived_outcomes(state, definition, current=True)}
    for outcome in state["outcomes"]:
        if outcome["kind"] != "GOVERNED" or not outcome["disputed"] or outcome["native_evidence"]["status"] not in {"EFFECT_ESTABLISHED", "NO_EFFECT_ESTABLISHED"}:
            continue
        permit = permits[outcome["permit_digest"]]
        occurrence = permit["occurrence"]["occurrence_id"]
        if occurrence not in completed:
            continue
        related = [row for row in state["outcomes"] if row["permit_digest"] == outcome["permit_digest"] and row["classification"] == "MATCHED"]
        if outcome["permit_digest"] not in derived_permits and not any(work_effective(state, row) is not None for row in related):
            roots.add(occurrence)
    for occurrence in lifecycle._all_occurrences(state).values():
        occurrence_id = occurrence["occurrence_id"]
        affected = False
        for permit in (row for row in state["permits"] if row["occurrence"]["occurrence_id"] == occurrence_id):
            step = next(row for row in definition["steps"] if row["id"] == permit["occurrence"]["step_id"])
            for group in lifecycle._dispatch_attempt_view(state, permit["permit_id"]):
                if occurrence_id in completed:
                    affected = affected or lifecycle._completed_dispatch_cause(state, occurrence_id, group)
                else:
                    affected = affected or group["disqualified"] and group["possibly_effective"] or group["disputed"] and (bool(step.get("dispatch_gate")) or not lifecycle._final_safe_attempt_set(state, permit["permit_id"], group["digest"]))
        if affected and not _dispatch_cause_covered(state, occurrence_id):
            roots.add(occurrence_id)
    return roots


def _block_newly_unresolved(before_roots, state, definition):
    from . import lifecycle

    if state["status"] == "COMPLETE":
        return
    newly_unresolved = _unresolved_roots(state, definition) - before_roots
    for occurrence_id in sorted(newly_unresolved, key=str.encode):
        active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == occurrence_id), None)
        if active is not None:
            active["status"] = "BLOCKED_DISPUTE"
        lifecycle._block_dependents(state, occurrence_id)


def _join_restored(request, state):
    from . import lifecycle, work_class
    reasons, route_ids, constructs, other_details = [], set(), set(), []
    while state["status"] == "ACTIVE":
        for obligation in state["obligations"]:
            if obligation["status"] == "DISPUTED" and obligation["waiting_on"] is not None:
                children = [row for row in state["obligations"] if row["obligation_id"] in obligation["waiting_on"]["obligation_ids"]]
                if children and not any(row["status"] == "DISPUTED" for row in children):
                    obligation["status"] = "WAITING"
        ready = None
        for obligation in state["obligations"]:
            if obligation["status"] != "DISCHARGED":
                continue
            outer = lifecycle._obligation_outer(state, obligation)
            siblings = [row for row in state["obligations"] if row["kind"] == obligation["kind"] and row["construct_id"] == obligation["construct_id"] and row["pass"] == obligation["pass"] and lifecycle._obligation_outer(state, row) == outer]
            if siblings and all(row["status"] == "DISCHARGED" for row in siblings):
                ready = obligation
                break
        if ready is None:
            break
        frontier = lifecycle._completion_frontier(state, ready)
        source = lifecycle._occurrence_from_state(state, frontier[-1])
        relation, frontier, joined = lifecycle._advance_join(request, state, ready, source)
        if relation is None:
            break
        owning = None
        while True:
            route_ids.add(digest("relationship", relation)); constructs.add(joined["construct_id"])
            owning = next((row for row in state["obligations"] if row["status"] == "WAITING" and row["waiting_on"] == joined), None)
            target = next(row for row in request["definition"]["steps"] if row["id"] == relation["to"])
            if target["kind"] not in {"PARALLEL_JOIN", "FANOUT_JOIN"}:
                break
            if owning is None:
                raise Refusal("STATE_INVALID")
            owning.update(status="DISCHARGED", waiting_on=None, completion_basis={"kind": "CHILD_PASS", "event_digest": digest("runtime-event", request["event"]), "child_pass": copy.deepcopy(joined)})
            relation, frontier, joined = lifecycle._advance_join(request, state, owning, source)
            if relation is None:
                break
        if relation is None:
            continue
        if target["kind"] == "TERMINAL":
            if not state["active"] and not any(row["status"] in {"OPEN", "BLOCKED", "WAITING", "DISPUTED"} for row in state["obligations"]):
                state["status"] = "COMPLETE"
        elif target["kind"] == "PARALLEL_SPLIT":
            split_source = {**source, "enclosing": copy.deepcopy(joined["outer_enclosing"])}
            stop, details, ids, entered = lifecycle._enter_parallel(request, state, split_source, target, frontier)
            constructs.update(entered); other_details.extend(details)
            if stop:
                state["status"] = "STOPPED"; reasons.extend(stop)
            elif owning is not None:
                block = next(row for row in request["definition"]["parallel_blocks"] if row["split_step_id"] == target["id"])
                owning.update(status="WAITING", expected_occurrence_id=None, required_operation=None,
                    waiting_on={"kind": "PARALLEL", "construct_id": block["id"], "pass": next(row["pass"] for row in state["obligations"] if row["obligation_id"] == ids[0]), "outer_enclosing": copy.deepcopy(split_source["enclosing"]), "obligation_ids": sorted(ids, key=str.encode)})
        elif target["kind"] in work_class.PROPOSAL:
            occurrence, deadlines, stop, limit = lifecycle._activation_preflight(request, state, source, relation, target, frontier, joined["outer_enclosing"])
            if stop:
                state["status"] = "STOPPED"; reasons.extend(stop)
                if limit is not None:
                    other_details.append(limit)
                deadline_reasons = [row for row in stop if row.startswith("DEADLINE_") or row == "ACTIVATION_CLOCK_UNAVAILABLE"]
                if deadline_reasons:
                    other_details.append({"kind": "DEADLINE", "deadline_ids": [row["id"] for row in request["definition"]["deadlines"] if row["step_id"] == target["id"]], "reasons": sorted(deadline_reasons, key=str.encode)})
            else:
                state["active"].append({"occurrence": occurrence, "activation_event_digest": digest("runtime-event", request["event"]), "status": "ACTIVE", "deadline_ids": [row["deadline_id"] for row in deadlines]})
                state["deadlines"].extend(deadlines)
                counter = next(row for row in state["step_counters"] if row["step_id"] == target["id"])
                counter["activations"] = str(int(counter["activations"]) + 1)
                state["total_activations"] = str(int(state["total_activations"]) + 1)
                if owning is not None:
                    owning.update(status="OPEN", expected_occurrence_id=occurrence["occurrence_id"], required_operation=target["operation"], waiting_on=None)
        else:
            raise Refusal("UNSUPPORTED_FEATURE")
    if route_ids or constructs:
        other_details.append({"kind": "ROUTE", "relationship_digests": sorted(route_ids, key=str.encode), "construct_ids": sorted(constructs, key=str.encode)})
    state["active"].sort(key=lambda row: canonical(row["occurrence"]))
    state["deadlines"].sort(key=lambda row: (row["due"], canonical(lifecycle._occurrence_from_state(state, row["occurrence_id"])), row["deadline_id"].encode()))
    return reasons, other_details


def _completion_budget_current(request, permit, no_effect):
    from . import reservation_v2
    selections = {digest("reservation-registry", row["state"]["core"]["configuration"]): row for row in request.get("recovery_registries", [])}
    if request["event"]["kind"] == "APPLY_DISPOSITION":
        selection = request["event"]["registry"]
        selections[digest("reservation-registry", selection["state"]["core"]["configuration"])] = selection
    for binding in permit["budget_revisions"]:
        selected = selections.get(binding["registry_digest"])
        if selected is None:
            return False
        registry = _registry_selection(selected)
        row = next((row for row in registry["core"]["reservations"] if row["id"] == binding["reservation_id"]), None)
        if row is None:
            return False
        target = {"kind": "RESERVATION", "registry_digest": binding["registry_digest"], "reservation": row["id"]}
        if any(item["target"] == target for item in selected["host_evidence"].get("recovery", {}).get("pending_evidence", [])):
            return False
        clocks = [clock for clock in request["state"]["clocks"] if clock["source"] == registry["core"]["configuration"]["clock_source"] and clock["status"] == "AVAILABLE"]
        if not clocks:
            return False
        now = max(clocks, key=lambda clock: int(clock["revision"]))["observed_time"]
        _registry_clock(registry["core"], now)
        if any(not reservation_v2._history_is_fresh(budget["history"], budget, now) for budget in registry["core"]["budgets"] if budget["definition"]["anchor"] in {item["anchor"] for item in row["contributions"]}):
            return False
        if row["status"] == ("RELEASED" if no_effect else "SETTLED"):
            continue
        disposition = registry_effective(registry["core"], target)
        if disposition is None or disposition["result"] != ("ESTABLISH_NO_EFFECT" if no_effect else "ESTABLISH_EFFECT") or unresolved_executions(disposition["evidence"]):
            return False
    return True


def _restore(request, state, disposition, permit):
    from . import lifecycle, timing
    details, reasons = [], []
    if permit is None or state["status"] != "ACTIVE" or disposition["result"] in {"LEAVE_UNRESOLVED", "ACCEPT_UNRESOLVED"}:
        return reasons, details
    if disposition["result"] == "ESTABLISH_EFFECT" and unresolved_executions(disposition["evidence"]):
        return reasons, details
    target = disposition["target"]
    occurrence_id = permit["occurrence"]["occurrence_id"]
    selected_native = None
    if target["kind"] == "WORK_OUTCOME" and disposition["result"] == "ESTABLISH_EFFECT":
        original = next(row for row in state["outcomes"] if row["outcome_digest"] == target["outcome_digest"])
        completed = next((row for row in state["completed"] if row["occurrence"]["occurrence_id"] == occurrence_id), None)
        original_native = original["native_evidence"]
        if completed is not None:
            original_native = next((row["native_evidence"] for row in factual_outcomes(state, request["definition"])
                if row["permit_digest"] == permit["permit_id"] and digest("native-evidence", row["native_evidence"]) == completed["evidence_digest"]), original_native)
        selected_native = next((row for row in disposition["evidence"]["native_outcomes"] if fact(row) == fact(original_native)), None)
        original_retained = selected_native is not None
        if completed and not original_retained:
            state["status"] = "STOPPED"
            return ["RECOVERY_BASIS_CHANGED"], []
        if completed is None and len({row["native_operation_id"] for row in disposition["evidence"]["native_outcomes"]}) > 1:
            if not original_retained or original["classification"] not in {"MATCHED", "FAILED", "LATE_MATCHED"} or original_native["status"] != "EFFECT_ESTABLISHED":
                return reasons, details
    if target["kind"] == "RESERVATION" and disposition["result"] == "ESTABLISH_EFFECT":
        step = next(row for row in request["definition"]["steps"] if row["id"] == permit["occurrence"]["step_id"])
        candidates = native_evidence(disposition, step["completion"])
        completed = next((row for row in state["completed"] if row["occurrence"]["occurrence_id"] == occurrence_id), None)
        if completed is not None:
            original_native = next((row["native_evidence"] for row in factual_outcomes(state, request["definition"])
                if row["permit_digest"] == permit["permit_id"] and digest("native-evidence", row["native_evidence"]) == completed["evidence_digest"]), None)
            selected_native = next((row for row in candidates if original_native is not None and fact(row) == fact(original_native)), None)
            if selected_native is None:
                state["status"] = "STOPPED"
                return ["RECOVERY_BASIS_CHANGED"], []
        elif len({row["native_operation_id"] for row in candidates if row["status"] == "EFFECT_ESTABLISHED"}) > 1:
            original_facts = {canonical(fact(row["native_evidence"])) for row in state["outcomes"] if row["permit_digest"] == permit["permit_id"] and row["classification"] in {"MATCHED", "FAILED", "LATE_MATCHED"} and row["native_evidence"]["status"] == "EFFECT_ESTABLISHED"}
            matches = {canonical(fact(row)): row for row in candidates if canonical(fact(row)) in original_facts}
            if len(matches) != 1:
                return reasons, details
            selected_native = next(iter(matches.values()))
    if disposition["result"] == "ESTABLISH_NO_EFFECT" and any(row["occurrence"]["occurrence_id"] == occurrence_id for row in state["completed"]):
        state["status"] = "STOPPED"
        return ["RECOVERY_BASIS_CHANGED"], []
    roots = _unresolved_roots(state, request["definition"])
    affected = roots | {occurrence["occurrence_id"] for occurrence in lifecycle._all_occurrences(state).values() if roots & lifecycle._predecessor_closure(state, occurrence)}
    for active in list(state["active"]):
        if active["status"] != "BLOCKED_DISPUTE":
            continue
        closure = lifecycle._predecessor_closure(state, active["occurrence"])
        if active["occurrence"]["occurrence_id"] in roots or roots & closure:
            continue
        own_permits = [row for row in state["permits"] if row["occurrence"]["occurrence_id"] == active["occurrence"]["occurrence_id"]]
        own_ids = {row["permit_id"] for row in own_permits}
        own_disputed = [row for row in state["outcomes"] if row["permit_digest"] in own_ids and row["disputed"]]
        selected_own = permit["occurrence"]["occurrence_id"] == active["occurrence"]["occurrence_id"]
        if own_disputed and not selected_own and not all(work_effective(state, row) is not None for row in own_disputed):
            continue
        consumed = any(row["permit_digest"] in own_ids and (row["attempt"]["status"] != "NOT_SENT" or row["acknowledgement"]["status"] == "ACCEPTED") for row in state["dispatches"])
        active["status"] = "OUTCOME_UNKNOWN" if consumed else "PERMITTED" if own_permits else "ACTIVE"
        expired = [row for row in state["deadlines"] if row["occurrence_id"] == active["occurrence"]["occurrence_id"] and row["status"] == "EXPIRED"] + timing.expired_for_occurrence(state, active["occurrence"]["occurrence_id"])
        if expired and not timing.selected(request["definition"]):
            deadline = expired[0]
            clock = deadline["expiry_basis"]["clock"] if "expiry_basis" in deadline else next(row for row in state["clocks"] if row["source"] == deadline["source"] and row["status"] == "AVAILABLE" and lifecycle._due(deadline, row["observed_time"]))
            _, route_reasons, route_details = lifecycle._complete_simple_route(request, state, active, "EXPIRED", clock["evidence_digest"], None, clock["observed_time"], None)
            reasons.extend(route_reasons); details.extend(route_details)
    if timing.selected(request["definition"]):
        request["_timing_rollback_before"] = copy.deepcopy(state)
        restored, _, expiry_reasons, expiry_details = timing.transition(request, state, "DISPOSITION_APPLIED", [], [])
        if restored is not state:
            state.clear()
            state.update(restored)
        reasons.extend(expiry_reasons)
        details.extend(expiry_details)
        request["_timing_expiry_route_prefix"] = len(details)
        if state["status"] != "ACTIVE":
            return reasons, details
    for obligation in state["obligations"]:
        if obligation["status"] == "BLOCKED":
            occurrence = lifecycle._all_occurrences(state).get(obligation["expected_occurrence_id"])
            if occurrence is not None and not roots & lifecycle._predecessor_closure(state, occurrence):
                obligation["status"] = "OPEN"
        elif obligation["status"] == "DISPUTED" and obligation["completion_basis"] is not None:
            candidate = {**obligation, "status": "DISCHARGED"}
            try:
                frontier = lifecycle._completion_frontier(state, candidate)
            except Refusal:
                continue
            if not affected & set(frontier):
                obligation["status"] = "DISCHARGED"
    for active in list(state["active"]):
        if state["status"] != "ACTIVE":
            break
        if active["status"] != "OUTCOME_UNKNOWN" or active["occurrence"]["occurrence_id"] == occurrence_id:
            continue
        own_permits = {row["permit_id"]: row for row in state["permits"] if row["occurrence"]["occurrence_id"] == active["occurrence"]["occurrence_id"]}
        candidates = [row for row in state["outcomes"] if row["permit_digest"] in own_permits and not row["disputed"] and row["classification"] in {"MATCHED", "FAILED", "NO_EFFECT_ESTABLISHED", "LATE_MATCHED"}]
        if not candidates:
            continue
        outcome = candidates[-1]
        own_permit = own_permits[outcome["permit_digest"]]
        if not _completion_budget_current(request, own_permit, outcome["classification"] == "NO_EFFECT_ESTABLISHED"):
            continue
        evidence = outcome["native_evidence"]
        step = next(row for row in request["definition"]["steps"] if row["id"] == own_permit["occurrence"]["step_id"])
        classification, label = outcome["classification"], None
        if classification in {"MATCHED", "LATE_MATCHED"}:
            dispatch = next((row for row in state["dispatches"] if row["dispatch_digest"] == outcome.get("dispatch_digest")), None)
            classification, label, _ = lifecycle._completion_fields(step, own_permit, evidence, {row["id"]: row for row in request["definition"]["types"]}, state=state, dispatch=dispatch)
        if classification in {"MATCHED", "FAILED", "NO_EFFECT_ESTABLISHED"}:
            _, route_reasons, route_details = lifecycle._complete_simple_route(request, state, active, classification,
                digest("native-evidence", evidence), label, evidence["event_time"] or evidence["observed_at"], evidence)
            reasons.extend(route_reasons); details.extend(route_details)
    if target["kind"] == "WORK_OUTCOME":
        active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == occurrence_id), None)
        if active is not None and active["status"] != "BLOCKED_DISPUTE":
            original = next(row for row in state["outcomes"] if row["outcome_digest"] == target["outcome_digest"])
            if original["classification"] in {"UNEXPECTED", "CONFLICTING", "LATE_AFTER_RELEASE"}:
                return reasons, details
            step = next(row for row in request["definition"]["steps"] if row["id"] == permit["occurrence"]["step_id"])
            candidates = native_evidence(disposition, step["completion"])
            evidence = selected_native or next((row for row in candidates if fact(row) == fact(original["native_evidence"])), candidates[0] if candidates else original["native_evidence"])
            if disposition["result"] == "ESTABLISH_NO_EFFECT":
                classification, label, occurred = "NO_EFFECT_ESTABLISHED", None, evidence["observed_at"]
                evidence_digest = digest("native-evidence", evidence)
            else:
                classification, label, _ = _recovered_completion(state, step, permit, evidence, disposition, {row["id"]: row for row in request["definition"]["types"]})
                occurred, evidence_digest = evidence["event_time"], digest("native-evidence", evidence)
            if classification in {"MATCHED", "FAILED", "NO_EFFECT_ESTABLISHED"}:
                _, route_reasons, route_details = lifecycle._complete_simple_route(request, state, active, classification, evidence_digest, label, occurred, evidence)
                reasons.extend(route_reasons); details.extend(route_details)
            else:
                state["status"] = "STOPPED"
                reasons.append("RECOVERY_BASIS_CHANGED")
    if target["kind"] == "RESERVATION" and target["reservation"] in {row["reservation_id"] for row in permit["budget_revisions"]}:
        if disposition["result"] == "ESTABLISH_EFFECT" and unresolved_executions(disposition["evidence"]):
            return reasons, details
        active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == occurrence_id), None)
        if active is not None and active["status"] != "BLOCKED_DISPUTE":
            step = next(row for row in request["definition"]["steps"] if row["id"] == permit["occurrence"]["step_id"])
            candidates = native_evidence(disposition, step["completion"])
            evidence = selected_native or next((row for row in candidates if row["status"] == ("EFFECT_ESTABLISHED" if disposition["result"] == "ESTABLISH_EFFECT" else "NO_EFFECT_ESTABLISHED")), None)
            if evidence is not None:
                if any(row["permit_digest"] == permit["permit_id"] and row["classification"] in {"UNEXPECTED", "CONFLICTING", "LATE_AFTER_RELEASE"}
                       and fact(row["native_evidence"]) == fact(evidence) for row in state["outcomes"]):
                    return reasons, details
                if disposition["result"] == "ESTABLISH_NO_EFFECT":
                    classification, label = "NO_EFFECT_ESTABLISHED", None
                else:
                    classification, label, _ = _recovered_completion(state, step, permit, evidence, disposition, {row["id"]: row for row in request["definition"]["types"]})
                if classification not in {"MATCHED", "FAILED", "NO_EFFECT_ESTABLISHED"}:
                    state["status"] = "STOPPED"
                    reasons.append("RECOVERY_BASIS_CHANGED")
                    return reasons, details
                _, route_reasons, route_details = lifecycle._complete_simple_route(request, state, active, classification,
                    digest("native-evidence", evidence), label, evidence["event_time"] or evidence["observed_at"], evidence)
                reasons.extend(route_reasons); details.extend(route_details)
    join_reasons, join_details = _join_restored(request, state)
    reasons.extend(join_reasons); details.extend(join_details)
    return reasons, details


def _recovery_dispatch(state, permits, evidence, disposition):
    from . import lifecycle
    attempts = [row for row in disposition["evidence"]["attempts"] if evidence["native_operation_id"] in row["effect_ids"]]
    if len(attempts) != 1:
        return None
    attempt = attempts[0]
    matches = []
    for permit in permits:
        for group in lifecycle._dispatch_attempt_groups(state, permit["permit_id"]):
            if group["digest"] != attempt["attempt_digest"] or any(row["attempt"]["attempt_id"] != attempt["id"] for row in group["records"]):
                continue
            bindings = {(row.get("authorization_digest"), canonical(row["native_request"]), canonical(row["connector"])) for row in group["records"]}
            if len(bindings) != 1:
                return None
            matches.append((permit, group["records"][-1]))
    return matches[0] if len(matches) == 1 else None


def _recovered_completion(state, step, permit, evidence, disposition, types):
    from . import lifecycle
    dispatch = None
    if step["completion"].get("authorization_revision_bindings"):
        permits = [row for row in state["permits"] if row["occurrence"] == permit["occurrence"]]
        matched = _recovery_dispatch(state, permits, evidence, disposition)
        if matched is None: return "UNEXPECTED", None, False
        permit, dispatch = matched
    return lifecycle._completion_fields(step, permit, evidence, types, state=state, dispatch=dispatch)


def _merge_details(details):
    merged = {}
    for detail in details:
        kind = detail["kind"]
        if kind not in merged:
            merged[kind] = copy.deepcopy(detail)
        elif kind in {"ROUTE", "DEADLINE"}:
            for name, values in detail.items():
                if name != "kind":
                    merged[kind][name] = sorted(set(merged[kind][name]) | set(values), key=str.encode)
    order = ("AUTHORITY", "AUTHORIZATION", "SEPARATION", "BUDGET", "DISPATCH", "EFFECT", "COMPLETION_CHECK", "CLOCK", "DEADLINE", "ROUTE", "LABEL", "LIMIT")
    return [merged[name] for name in order if name in merged]


def lifecycle_step(request):
    from . import lifecycle, timing
    event = request["event"]
    disposition, host, permit, reasons = _work_dispose(request) if event["kind"] == "DISPOSE" else _apply_registry(request)
    for selection in request.get("recovery_registries", []):
        _registry_selection(selection)
    state = copy.deepcopy(request["state"])
    record = {"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(host), "disposition": copy.deepcopy(disposition),
              "before_projection": projection(state), "after_projection": projection(state)}
    if request.get("recovery_registries"):
        record["registry_selections"] = copy.deepcopy(request["recovery_registries"])
    before_roots = _unresolved_roots(state, request["definition"]) if disposition["result"] == "LEAVE_UNRESOLVED" else set()
    state.setdefault("recovery_records", []).append(record)
    if disposition["result"] == "LEAVE_UNRESOLVED":
        _block_newly_unresolved(before_roots, state, request["definition"])
    route_reasons, details = _restore(request, state, disposition, permit)
    reasons.extend(route_reasons)
    if timing.selected(request["definition"]) and state["status"] == "STOPPED":
        prefix = request.get("_timing_expiry_route_prefix", 0)
        details = [row for index, row in enumerate(details) if index >= prefix or row["kind"] != "ROUTE"]
    record["after_projection"] = projection(state)
    decision = "STOPPED" if record["before_projection"]["status"] == "ACTIVE" and state["status"] == "STOPPED" else "WITHHELD" if reasons and disposition["result"] == "LEAVE_UNRESOLVED" else "DISPOSITION_RECORDED" if event["kind"] == "DISPOSE" else "DISPOSITION_APPLIED"
    if timing.selected(request["definition"]) and decision != "STOPPED" and any(row["kind"] == "DEADLINE" and row["deadline_ids"] for row in details):
        decision = "EXPIRED"
    result = lifecycle._finish(request, state, decision,
        reasons, _merge_details(details), recovery_disposition_digest=disposition["id"])
    return result


def renewal_required(state, permit):
    receipts = {row["event_id"]: int(row["sequence"]) for row in state["receipts"]}
    proposal = next((row for row in state["proposals"] if row["proposal_digest"] == permit["proposal_digest"]), None)
    if proposal is None:
        return False
    sequence = receipts[proposal["event_id"]]
    occurrence = permit["occurrence"]["occurrence_id"]
    for record in state.get("recovery_records", []):
        if receipts.get(record["event"]["event_id"], 0) <= sequence:
            continue
        before = next((row for row in record["before_projection"]["active"] if row["occurrence"]["occurrence_id"] == occurrence), None)
        after = next((row for row in record["after_projection"]["active"] if row["occurrence"]["occurrence_id"] == occurrence), None)
        if before is not None and before["status"] == "BLOCKED_DISPUTE" and after is not None and after["status"] == "PERMITTED":
            return True
    return False


def permission_boundary(request):
    from . import lifecycle, reservation_v2
    state, event = request["state"], request["event"]
    if event["kind"] not in {"PROPOSE", "AUTHORIZE_DISPATCH", "DISPATCH_OBSERVED"}:
        return
    if event["kind"] == "DISPATCH_OBSERVED":
        if renewal_required(state, event["permit"]):
            raise Refusal("PREREQUISITE_MISSING")
        return
    host = request.get("recovery_host")
    occurrence = event.get("occurrence", event.get("permit", {}).get("occurrence"))
    if event["kind"] == "PROPOSE" and occurrence is not None and any(row["occurrence"]["occurrence_id"] == occurrence["occurrence_id"] and row["status"] == "BLOCKED_DISPUTE" for row in state["active"]):
        return
    closure = set() if occurrence is None else lifecycle._predecessor_closure(state, occurrence) | {occurrence["occurrence_id"]}
    if _unresolved_roots(state, request["definition"]) & closure:
        raise Refusal("PREREQUISITE_MISSING")
    if host is not None and any(row["target"]["kind"] == "WORK_OUTCOME" and row["target"]["instance_id"] == state["instance_id"] and row["target"]["occurrence_id"] in closure for row in host["pending_evidence"]):
        raise Refusal("EVIDENCE_UNAVAILABLE")
    if event["kind"] == "AUTHORIZE_DISPATCH" and renewal_required(state, event["permit"]):
        raise Refusal("PREREQUISITE_MISSING")
    selections = {digest("reservation-registry", row["state"]["core"]["configuration"]): row for row in request.get("recovery_registries", [])}
    selections.update({row["registry_digest"]: {"state": row["request"]["state"], "state_digest": row["request"]["state_digest"], "host_evidence": row["request"]["host_evidence"]} for row in event.get("budget_inputs", [])})
    consumed = {row["registry_digest"] for row in event.get("permit", {}).get("budget_revisions", [])}
    consumed.update(row["registry_digest"] for row in event.get("budget_inputs", []))
    for registry_digest in consumed:
        selected = selections.get(registry_digest)
        if selected is None or selected["state"]["core"]["configuration"].get("recovery") is None:
            continue
        registry = _registry_selection(selected)
        clocks = [row for row in state["clocks"] if row["source"] == registry["core"]["configuration"]["clock_source"]]
        latest = max(clocks, key=lambda row: int(row["revision"])) if clocks else None
        _registry_clock(registry["core"], latest["observed_time"] if latest is not None and latest["status"] == "AVAILABLE" else None)
    for record in state.get("recovery_records", []):
        disposition = record["disposition"]
        if disposition["target"]["kind"] != "RESERVATION" or disposition["result"] == "LEAVE_UNRESOLVED":
            continue
        registry_digest = disposition["target"]["registry_digest"]
        bound_occurrences = {row["occurrence"]["occurrence_id"] for row in state["permits"] if any(binding["registry_digest"] == registry_digest and binding["reservation_id"] == disposition["target"]["reservation"] for binding in row["budget_revisions"])}
        relevant = bool(bound_occurrences & closure)
        historical = record["event"].get("registry", {}).get("state", {}).get("core")
        origin = None if historical is None else next((row for row in historical["reservations"] if row["id"] == disposition["target"]["reservation"]), None)
        for row in event.get("budget_inputs", []):
            if relevant or row["registry_digest"] != registry_digest or origin is None:
                continue
            for budget in row["request"]["state"]["core"]["budgets"]:
                try:
                    authorization, projected = reservation_v2._projection_for(budget["authorizations"], event["authority_input"], budget)
                    contributions = reservation_v2._contributions(budget, authorization, projected, event["authority_input"])
                except (KeyError, TypeError, ValueError, reservation_v2._AdmissionError):
                    continue
                relevant = relevant or any(candidate["anchor"] == old["anchor"] and candidate["key"] == old["key"] for candidate in contributions for old in origin["contributions"])
        if not relevant:
            continue
        selected = selections.get(registry_digest)
        if selected is None:
            raise Refusal("EVIDENCE_UNAVAILABLE")
        registry = _registry_selection(selected)
        pending = selected["host_evidence"].get("recovery", {}).get("pending_evidence", [])
        if any(row["target"] == disposition["target"] for row in pending):
            raise Refusal("EVIDENCE_UNAVAILABLE")
        clocks = [row for row in state["clocks"] if row["source"] == registry["core"]["configuration"]["clock_source"]]
        latest = max(clocks, key=lambda row: int(row["revision"])) if clocks else None
        clock = latest["observed_time"] if latest is not None and latest["status"] == "AVAILABLE" else None
        _registry_clock(registry["core"], clock)
        if registry_effective(registry["core"], disposition["target"], clock) is None:
            raise Refusal("EVIDENCE_UNAVAILABLE")


def decision_integrity(receipt, replay, state):
    records = [row for row in state.get("recovery_records", []) if row["event"]["event_id"] == receipt["event_id"]]
    if len(records) != 1:
        return False
    record = records[0]
    expected = "STOPPED" if record["before_projection"]["status"] == "ACTIVE" and record["after_projection"]["status"] == "STOPPED" else "WITHHELD" if receipt["reason_codes"] and record["disposition"]["result"] == "LEAVE_UNRESOLVED" else "DISPOSITION_RECORDED" if receipt["event_kind"] == "DISPOSE" else "DISPOSITION_APPLIED"
    timing_expiry = receipt["disposition"] == "EXPIRED" and expected != "STOPPED" and any(row["kind"] == "DEADLINE" for row in receipt["details"]) and any(name in record["after_projection"] for name in ("event_duties", "deferred_deadlines"))
    return (digest("runtime-event", record["event"]) == receipt["event_digest"]
            and receipt.get("recovery_disposition_digest") == record["disposition"]["id"]
            and (receipt["disposition"] == expected or timing_expiry)
            and receipt["authority_result_digest"] is None and receipt["permit_digest"] is None and not replay["budget_results"])


def checkpoint_before(state, record):
    from . import lifecycle
    receipts = {row["event_id"]: row for row in state["receipts"]}
    sequence = int(receipts[record["event"]["event_id"]]["sequence"])
    before = lambda event_id: int(receipts[event_id]["sequence"]) < sequence
    prior = copy.deepcopy(state)
    prior.update(copy.deepcopy(record["before_projection"]))
    prior["revision"] = str(sequence - 1)
    prior["receipts"] = [row for row in prior["receipts"] if before(row["event_id"])]
    prior["replays"] = [row for row in prior["replays"] if before(row["event_id"])]
    prior["recovery_records"] = [row for row in prior["recovery_records"] if before(row["event"]["event_id"])]
    for name in ("proposals", "dispatches", "outcomes", "authorizations", "authorization_evaluations", "completion_checks", "terminal_records", "referrals"):
        if name in prior:
            prior[name] = [row for row in prior[name] if before(row["event_id"])]
    if "proposal_authority_evaluations" in prior:
        prior["proposal_authority_evaluations"] = [row for row in prior["proposal_authority_evaluations"] if before(row["event"]["event_id"])]
    if "timing_clock_events" in prior:
        prior["timing_clock_events"] = [row for row in prior["timing_clock_events"] if before(row["event_id"])]
    proposal_ids = {row["proposal_digest"] for row in prior["proposals"]}
    prior["permits"] = [row for row in prior["permits"] if row["proposal_digest"] in proposal_ids]
    clock_sequences = {(detail["source"], detail["revision"]): int(row["sequence"]) for row in state["receipts"] for detail in row["details"] if detail["kind"] == "CLOCK"}
    prior["clocks"] = [row for row in prior["clocks"] if clock_sequences.get((row["source"], row["revision"]), 0) < sequence]
    evidence_ids = {row["native_evidence"]["evidence_id"] for row in prior["outcomes"]}
    rebuilt = []
    for outcome in sorted(prior["outcomes"], key=lambda row: int(receipts[row["event_id"]]["sequence"])):
        outcome["conflicts_with_evidence_ids"] = [value for value in outcome["conflicts_with_evidence_ids"] if value in evidence_ids]
        original = receipts[outcome["event_id"]]
        outcome["disputed"] = (outcome["kind"] == "FOREIGN" or bool(outcome["conflicts_with_evidence_ids"])
            or outcome["classification"] in {"UNEXPECTED", "CONFLICTING", "LATE_AFTER_RELEASE"}
            or "BUDGET_EFFECT_DISPUTED" in original["reason_codes"])
        if outcome["classification"] == "DUPLICATE":
            sources = [row for row in rebuilt if row["permit_digest"] == outcome["permit_digest"] and fact(row["native_evidence"]) == fact(outcome["native_evidence"])]
            if sources:
                outcome["disputed"] = outcome["disputed"] or sources[-1]["disputed"]
        lifecycle._rehash_outcome(outcome)
        rebuilt.append(outcome)
    prior["outcomes"].sort(key=lambda row: row["outcome_digest"])
    return prior


def state_integrity(state, definition):
    from . import lifecycle, timing
    if bool(definition.get("recovery")) != ("recovery_records" in state):
        return False
    if [row["event"]["event_id"] for row in state.get("recovery_records", [])] != [row["event_id"] for row in state["receipts"] if row["event_kind"] in {"DISPOSE", "APPLY_DISPOSITION"}]:
        return False
    receipts = {row["event_id"]: row for row in state["receipts"]}
    for record in state.get("recovery_records", []):
        event = record["event"]
        receipt = receipts.get(event["event_id"])
        if receipt is None or receipt["event_digest"] != digest("runtime-event", event):
            return False
        expected_projection = set(PROJECTION) | {name for name in ("event_duties", "deferred_deadlines") if name in state}
        if any(set(record[name]) != expected_projection for name in ("before_projection", "after_projection")):
            return False
        prior = checkpoint_before(state, record)
        if (event["expected_state_revision"] != prior["revision"] or event["expected_state_digest"] != receipt["state_before_digest"]
                or lifecycle.state_digest(prior) != receipt["state_before_digest"]):
            return False
        request = {"specification_pin": PIN, "definition": definition, "definition_digest": state["work_class_digest"],
            "profile": state["profile"], "role": state["role"], "state": prior, "state_digest": receipt["state_before_digest"],
            "event": event, "recovery_host": record["host_evidence"]}
        if record.get("registry_selections"):
            request["recovery_registries"] = copy.deepcopy(record["registry_selections"])
        try:
            if timing.selected(definition):
                result = lifecycle_step(request)
                restored = next(row for row in result["state"]["recovery_records"] if row["event"]["event_id"] == event["event_id"])
                if restored != record or result["decision"] != receipt:
                    return False
                continue
            disposition, host, permit, _ = _work_dispose(request) if event["kind"] == "DISPOSE" else _apply_registry(request)
            if disposition != record["disposition"]:
                return False
            before_roots = _unresolved_roots(prior, definition) if disposition["result"] == "LEAVE_UNRESOLVED" else set()
            prior["recovery_records"].append(copy.deepcopy(record))
            if disposition["result"] == "LEAVE_UNRESOLVED":
                _block_newly_unresolved(before_roots, prior, definition)
            _restore(request, prior, disposition, permit)
            if projection(prior) != record["after_projection"]:
                return False
        except (KeyError, TypeError, ValueError, StopIteration, Refusal):
            return False
    return True
