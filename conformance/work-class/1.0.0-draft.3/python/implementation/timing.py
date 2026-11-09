"""Immutable event anchors and same-occurrence elapsed duties."""

from __future__ import annotations

import copy

from .common import PIN, Refusal, canonical, digest, utf8_sorted_unique, valid_instant


EVENT = "ELAPSED_FROM_EVENT_ANCHOR"
WITHHELD = "ELAPSED_FROM_FIRST_WITHHELD"
DISPATCH = "ELAPSED_FROM_FIRST_DISPATCH"
KINDS = {EVENT, WITHHELD, DISPATCH}


def selected(definition):
    return bool(definition.get("event_anchors")) or any(row["due"]["kind"] in KINDS for row in definition["deadlines"])


def inherited(row):
    return row["due"]["kind"] not in KINDS


def withheld_step(definition, step_id):
    return any(row["step_id"] == step_id and row["due"]["kind"] == WITHHELD for row in definition["deadlines"])


def evaluation_carrier(definition):
    return any(row.get("referral_policy", {}).get("authority") for row in definition["steps"]) or any(row["due"]["kind"] == WITHHELD for row in definition["deadlines"])


def retain_evaluation(definition, step_id):
    return any(row.get("referral_policy", {}).get("authority") for row in definition["steps"]) or withheld_step(definition, step_id)


def validate_definition(definition, steps, types, limits, graph, regions):
    from . import work_class

    anchors = definition.get("event_anchors", [])
    if anchors and not utf8_sorted_unique([row["id"] for row in anchors]):
        raise Refusal("DEFINITION_INVALID")
    if len(anchors) > 64 or len(definition["deadlines"]) > 256:
        raise Refusal("LIMIT_EXCEEDED")
    by_id = {row["id"]: row for row in anchors}
    for anchor in anchors:
        fields = anchor["fields"]
        names = [row["name"] for row in fields]
        if not fields or not utf8_sorted_unique(names) or not utf8_sorted_unique(anchor["subject_fields"]):
            raise Refusal("DEFINITION_INVALID")
        field_types = {row["name"]: row["type_ref"] for row in fields}
        if any(value not in types for value in field_types.values()) or not set(anchor["subject_fields"]) <= set(names):
            raise Refusal("REFERENCE_INVALID")
        if any(types[value]["kind"] not in {"IDENTITY", "STRING", "BOOLEAN", "INTEGER", "DECIMAL", "INSTANT"} for value in field_types.values()):
            raise Refusal("DEFINITION_INVALID")
        time = anchor["time"]
        time_type = time.get("type_ref") if time["kind"] == "EVENT_TIME" else field_types.get(time["field_ref"])
        if time_type not in types:
            raise Refusal("REFERENCE_INVALID")
        if types[time_type]["kind"] != "INSTANT":
            raise Refusal("DEFINITION_INVALID")
        bindings = anchor["request_bindings"]
        keys = [(row["step_id"].encode(), row["target_request_field"].encode()) for row in bindings]
        if not bindings or keys != sorted(set(keys)):
            raise Refusal("DEFINITION_INVALID")
        for row in bindings:
            target = steps.get(row["step_id"])
            declaration = None if target is None else next((field for field in target.get("fields", []) if field["name"] == row["target_request_field"]), None)
            if target is None or row["subject_field"] not in anchor["subject_fields"] or declaration is None:
                raise Refusal("REFERENCE_INVALID")
            if target["kind"] not in work_class.PROPOSAL or declaration["type_ref"] != field_types[row["subject_field"]]:
                raise Refusal("DEFINITION_INVALID")
        targets = {definition["root"]} | {row["step_id"] for row in definition["deadlines"] if row["due"]["kind"] == EVENT and row["due"]["anchor_ref"] == anchor["id"]}
        if any(not any(row["step_id"] == target and row["subject_field"] == field for row in bindings) for target in targets for field in anchor["subject_fields"]):
            raise Refusal("DEFINITION_INVALID")
    for deadline in definition["deadlines"]:
        due = deadline["due"]
        if due["kind"] not in KINDS:
            continue
        if int(due["value"]) <= 0:
            raise Refusal("DEFINITION_INVALID")
        if due["kind"] == WITHHELD:
            if int(definition["limits"]["maximum_proposals"]) > 128:
                raise Refusal("LIMIT_EXCEEDED")
            checks = due["failed_checks"]
            keys = [canonical(row) for row in checks]
            if not keys or keys != sorted(set(keys)) or len(keys) > 64:
                raise Refusal("DEFINITION_INVALID")
        if due["kind"] != EVENT:
            continue
        if due["anchor_ref"] not in by_id:
            raise Refusal("REFERENCE_INVALID")
        target = deadline["step_id"]
        if target == definition["root"] or target not in limits or int(limits[target]["maximum"]) != 1:
            raise Refusal("DEFINITION_INVALID")
        if any(target in row["member_step_ids"] for row in definition["loops"]) or any(kind == "FANOUT" and target in region for kind, _, region in regions):
            raise Refusal("DEFINITION_INVALID")
        joins = {}
        for block in definition["parallel_blocks"]:
            heads = [row["head_step_id"] for row in block["branches"]]
            joins[block["join_step_id"]] = [work_class._region(graph, head, block["join_step_id"], heads) for head in heads]
        reached = {definition["root"]}
        changed = True
        while changed:
            changed = False
            for node in steps:
                if node == target or node in reached:
                    continue
                predecessors = {source for source, targets in graph.items() if node in targets}
                available = predecessors & reached
                if available and (node not in joins or all(available & region for region in joins[node])):
                    reached.add(node)
                    changed = True
        if any(steps[node]["kind"] == "TERMINAL" for node in reached):
            raise Refusal("DEFINITION_INVALID")


def anchor_time(declaration, wrapper):
    selection = declaration["time"]
    if selection["kind"] == "EVENT_TIME":
        return wrapper["record"]["event_time"]
    return next(row["value"]["value"] for row in wrapper["record"]["fields"] if row["name"] == selection["field_ref"])


def admit_anchors(definition, wrappers, authorization, work_digest, instance_id, clock):
    from . import lifecycle, work_class

    declarations = definition.get("event_anchors", [])
    expected = [row["id"] for row in declarations]
    supplied = [row["anchor_ref"] for row in wrappers]
    if not utf8_sorted_unique(supplied):
        raise Refusal("INPUT_INVALID")
    if supplied != expected:
        raise Refusal("EVIDENCE_UNAVAILABLE" if set(supplied) < set(expected) else "DEPENDENCY_MISMATCH")
    types = {row["id"]: row for row in definition["types"]}
    vector = []
    for declaration, wrapper in zip(declarations, wrappers):
        record = wrapper["record"]
        if wrapper["specification_pin"] != PIN or wrapper["work_class_digest"] != work_digest:
            raise Refusal("DEPENDENCY_MISMATCH")
        if wrapper["organization_id"] != authorization["organization_id"] or wrapper["instance_id"] != instance_id:
            raise Refusal("BINDING_MISMATCH")
        if any(record[name] != declaration[name] for name in ("provider", "source", "record_type")):
            raise Refusal("BINDING_MISMATCH")
        if wrapper["record_digest"] != digest("event-anchor-record", record):
            raise Refusal("DIGEST_MISMATCH")
        fields = record["fields"]
        if [row["name"] for row in fields] != [row["name"] for row in declaration["fields"]]:
            raise Refusal("BINDING_MISMATCH")
        if any(row["value"]["type_ref"] != field["type_ref"] or not work_class._typed(row["value"], types) for row, field in zip(fields, declaration["fields"])):
            raise Refusal("TYPE_INVALID")
        times = (record["event_time"], record["observed_at"], anchor_time(declaration, wrapper))
        if not all(valid_instant(value) for value in times):
            raise Refusal("TYPE_INVALID")
        event, observed, selected_time = map(lifecycle._parse, times)
        if event > observed or selected_time > observed or observed > lifecycle._parse(clock["observed_time"]):
            raise Refusal("CLOCK_INVALID")
        vector.append({"anchor_ref": declaration["id"], "anchor_digest": digest("initial-event-anchor", wrapper)})
    if vector != authorization.get("event_anchor_digests", []):
        raise Refusal("BINDING_MISMATCH")
    if not declarations and (wrappers or "event_anchor_digests" in authorization):
        raise Refusal("DEPENDENCY_MISMATCH")
    return vector


def request_bindings(definition, state, step_id, native):
    values = {row["name"]: row["value"] for row in native["fields"]}
    wrappers = {row["anchor_ref"]: row for row in state.get("initial_event_anchors", [])}
    for declaration in definition.get("event_anchors", []):
        fields = {row["name"]: row["value"] for row in wrappers[declaration["id"]]["record"]["fields"]}
        for row in declaration["request_bindings"]:
            if row["step_id"] == step_id and canonical(values.get(row["target_request_field"])) != canonical(fields[row["subject_field"]]):
                raise Refusal("BINDING_MISMATCH")


def authority_bindings(definition, event):
    declaration = next((row for row in definition["deadlines"] if row["step_id"] == event["occurrence"]["step_id"] and row["due"]["kind"] in {WITHHELD, DISPATCH}), None)
    if declaration is None:
        return
    authority_input = event["authority_input"]
    if authority_input["clock"]["source"] != declaration["clock_source"]:
        raise Refusal("BINDING_MISMATCH")
    if declaration["due"]["kind"] == WITHHELD:
        selected_requirements = {row["id"] for row in authority_input["envelope"].get("source_observation_requirements", []) if row["step"] == declaration["step_id"]}
        if any(row["requirement_ref"] not in selected_requirements for row in declaration["due"]["failed_checks"]):
            raise Refusal("REFERENCE_INVALID")


def duration(rule):
    return int(rule["value"]) * {"SECOND": 1, "MINUTE": 60, "HOUR": 3600, "DAY": 86400}[rule["unit"]]


def record_limit(definition, state, targets):
    if not selected(definition):
        return None
    current = len(state["deadlines"]) + len(state.get("event_duties", [])) + len(state.get("deferred_deadlines", []))
    for step_id, relationship_digest in targets:
        current += sum(row["step_id"] == step_id and row["due"]["kind"] != EVENT for row in definition["deadlines"])
        if current > 4096:
            return {"kind": "LIMIT", "limit_kind": "DEADLINE_RECORDS", "limit": "4096", "current": str(current), "step_id": step_id, "relationship_digest": relationship_digest}
    return None


def activation_clocks(request, sources, supplied):
    if not selected(request["definition"]):
        return supplied
    request.setdefault("_timing_activation_sources", set()).update(sources)
    return [row for row in supplied if row["source"] in sources]


def validate_activation_clocks(request, state):
    if not selected(request["definition"]):
        return
    sources = sorted(request.get("_timing_activation_sources", set()), key=str.encode)
    supplied = request["event"].get("activation_clocks", [])
    supplied_sources = [row["source"] for row in supplied]
    if set(supplied_sources) - set(sources) or supplied_sources != sorted(set(supplied_sources), key=str.encode):
        raise Refusal("DEPENDENCY_MISMATCH")
    for row in supplied:
        available = [clock for clock in state["clocks"] if clock["source"] == row["source"] and clock["status"] == "AVAILABLE"]
        if not available or canonical(row) != canonical(max(available, key=lambda clock: int(clock["revision"]))):
            raise Refusal("DEPENDENCY_MISMATCH")


def initial_duties(definition, state):
    from . import lifecycle

    declarations = {row["id"]: row for row in definition.get("event_anchors", [])}
    wrappers = {row["anchor_ref"]: row for row in state.get("initial_event_anchors", [])}
    rows = []
    for deadline in definition["deadlines"]:
        if deadline["due"]["kind"] != EVENT:
            continue
        anchor_ref = deadline["due"]["anchor_ref"]
        anchor_digest = digest("initial-event-anchor", wrappers[anchor_ref])
        due = lifecycle._add_seconds(anchor_time(declarations[anchor_ref], wrappers[anchor_ref]), duration(deadline["due"]))
        body = {"specification_pin": PIN, "work_class_digest": state["work_class_digest"], "instance_id": state["instance_id"], "deadline_id": deadline["id"], "anchor_digest": anchor_digest, "due": due, "boundary": deadline["boundary"], "source": deadline["clock_source"]}
        row = {"deadline_id": deadline["id"], "target_step_id": deadline["step_id"], "source": deadline["clock_source"], "boundary": deadline["boundary"], "anchor_ref": anchor_ref, "anchor_digest": anchor_digest, "due": due, "creation_digest": digest("initial-event-duty", body), "status": "PENDING", "occurrence_id": None, "binding_event_digest": None}
        clock = next((value for value in state["clocks"] if value["source"] == row["source"]), None)
        if clock is not None and clock["status"] == "AVAILABLE" and lifecycle._due(row, clock["observed_time"]):
            row.update(status="EXPIRED", expiry_basis={"kind": "DEPLOYMENT", "deployment_authorization_digest": state["deployment_authorization_digest"], "clock": copy.deepcopy(clock)})
        rows.append(row)
    return sorted(rows, key=lambda row: row["deadline_id"].encode())


def initialize(definition, state, wrappers):
    if selected(definition):
        state["timing_clock_events"] = []
    if definition.get("event_anchors"):
        state["initial_event_anchors"] = copy.deepcopy(wrappers)
    if any(row["due"]["kind"] == EVENT for row in definition["deadlines"]):
        state["event_duties"] = initial_duties(definition, state)
    if any(row["due"]["kind"] in {WITHHELD, DISPATCH} for row in definition["deadlines"]):
        state["deferred_deadlines"] = []
    synchronize(definition, state)


def synchronize(definition, state):
    from . import lifecycle

    deferred = state.get("deferred_deadlines", [])
    if len(state["deadlines"]) + len(state.get("event_duties", [])) + len(deferred) > 4096:
        raise Refusal("LIMIT_EXCEEDED")
    for active in state["active"]:
        occurrence = active["occurrence"]
        declarations = [row for row in definition["deadlines"] if row["step_id"] == occurrence["step_id"]]
        active["deadline_ids"] = [row["id"] for row in declarations]
        for declaration in declarations:
            kind = declaration["due"]["kind"]
            if kind == EVENT:
                row = next(value for value in state["event_duties"] if value["deadline_id"] == declaration["id"])
                if row["occurrence_id"] is None:
                    row["occurrence_id"] = occurrence["occurrence_id"]
                    row["binding_event_digest"] = active["activation_event_digest"]
                elif row["occurrence_id"] != occurrence["occurrence_id"]:
                    raise Refusal("STATE_INVALID")
            elif kind in {WITHHELD, DISPATCH} and not any(row["deadline_id"] == declaration["id"] and row["occurrence_id"] == occurrence["occurrence_id"] for row in deferred):
                if len(state["deadlines"]) + len(state.get("event_duties", [])) + len(deferred) >= 4096:
                    raise Refusal("LIMIT_EXCEEDED")
                body = {"specification_pin": PIN, "work_class_digest": state["work_class_digest"], "instance_id": state["instance_id"], "deadline_id": declaration["id"], "occurrence_id": occurrence["occurrence_id"], "activation_event_digest": active["activation_event_digest"]}
                deferred.append({"deadline_id": declaration["id"], "occurrence_id": occurrence["occurrence_id"], "source": declaration["clock_source"], "boundary": declaration["boundary"], "activation_event_digest": active["activation_event_digest"], "creation_digest": digest("deferred-deadline", body), "status": "WAITING"})
    deferred.sort(key=lambda row: (canonical(lifecycle._occurrence_from_state(state, row["occurrence_id"])), row["deadline_id"].encode()))


def discharge(request, state, active, classification, evidence_digest):
    if classification == "EXPIRED":
        return
    occurrence_id = active["occurrence"]["occurrence_id"]
    basis = {"kind": "COMPLETION", "event_digest": digest("runtime-event", request["event"]), "occurrence_id": occurrence_id, "evidence_digest": evidence_digest}
    for row in state.get("event_duties", []) + state.get("deferred_deadlines", []):
        if row.get("occurrence_id") == occurrence_id and row["status"] in {"WAITING", "PENDING"}:
            row.update(status="DISCHARGED", discharge_basis=copy.deepcopy(basis))


def _withholding_trigger(definition, state, event, authority_result, sequence):
    from . import dispatch_gate

    if authority_result["status"] != "REFUSED" or event["authority_input"]["clock"]["status"] != "AVAILABLE":
        return None
    declaration = next((row for row in definition["deadlines"] if row["step_id"] == event["occurrence"]["step_id"] and row["due"]["kind"] == WITHHELD), None)
    if declaration is None:
        return None
    failed = authority_result["failed_checks"]
    requirements = event["authority_input"]["envelope"].get("source_observation_requirements", [])
    selected_requirements = {row["id"] for row in requirements if row["step"] == declaration["step_id"]}
    if any(row["requirement_ref"] not in selected_requirements for row in declaration["due"]["failed_checks"]):
        raise Refusal("REFERENCE_INVALID")
    if not any(all(check.get(name) == selector[name] for name in ("purpose", "requirement_ref", "reason")) for check in failed for selector in declaration["due"]["failed_checks"]):
        return None
    source = event["authority_input"]["clock"]["source"]
    if source != declaration["clock_source"]:
        raise Refusal("BINDING_MISMATCH")
    clock = dispatch_gate.accepted_clock(state, source, sequence)
    if clock is None or clock["status"] != "AVAILABLE" or clock["revision"] != event["clock_revision"] or clock["observed_time"] != event["authority_input"]["clock"]["instant"]:
        raise Refusal("CLOCK_INVALID")
    evaluation = {"event": copy.deepcopy(event), "authority_result": copy.deepcopy(authority_result), "authority_result_digest": digest("authority-result", authority_result)}
    trigger = {"kind": "FIRST_WITHHELD", "evaluation_digest": digest("proposal-authority-evaluation", evaluation), "sequence": str(sequence), "clock": copy.deepcopy(clock)}
    return declaration, trigger, clock["observed_time"]


def _dispatch_trigger(definition, state, event, sequence):
    from . import dispatch_gate

    permit = event["permit"]
    declaration = next((row for row in definition["deadlines"] if row["step_id"] == permit["occurrence"]["step_id"] and row["due"]["kind"] == DISPATCH), None)
    if declaration is None or event["attempt"]["status"] not in {"SENT", "UNKNOWN"} and event["acknowledgement"]["status"] != "ACCEPTED":
        return None
    if permit["clock_source"] != declaration["clock_source"]:
        raise Refusal("BINDING_MISMATCH")
    clock = dispatch_gate.accepted_clock(state, permit["clock_source"], sequence, available_only=True)
    record = next(row for row in state["dispatches"] if row["event_id"] == event["event_id"])
    trigger = {"kind": "FIRST_DISPATCH", "event_digest": record["event_digest"], "sequence": str(sequence), "dispatch_digest": record["dispatch_digest"], "dispatch_attempt_digest": record["dispatch_attempt_digest"], "clock": copy.deepcopy(clock)}
    return declaration, trigger, record["attempt"]["attempted_at"]


def _clock_basis(state, clock):
    receipt = next((row for row in state["receipts"] if any(detail["kind"] == "CLOCK" and detail["source"] == clock["source"] and detail["revision"] == clock["revision"] for detail in row["details"])), None)
    if receipt is None:
        return {"kind": "DEPLOYMENT", "deployment_authorization_digest": state["deployment_authorization_digest"], "clock": copy.deepcopy(clock)}
    return {"kind": "CLOCK", "event_digest": receipt["event_digest"], "clock": copy.deepcopy(clock)}


def _expire_bound(request, state):
    from . import dispatch_gate, lifecycle

    changed = []
    sequence = int(request["state"]["revision"]) + 1
    for row in state.get("event_duties", []):
        if row["status"] != "PENDING" or row["occurrence_id"] is None:
            continue
        clock = dispatch_gate.accepted_clock(state, row["source"], sequence)
        if clock is None or clock["status"] != "AVAILABLE" or not lifecycle._due(row, clock["observed_time"]):
            continue
        event = request["event"]
        basis = {"kind": "CLOCK", "event_digest": digest("runtime-event", event), "clock": copy.deepcopy(clock)} if event["kind"] == "CLOCK" and event["clock"] == clock else _clock_basis(state, clock)
        row.update(status="EXPIRED", expiry_basis=basis)
        changed.append(row)
    return changed


def expired_for_occurrence(state, occurrence_id):
    return [row for row in state.get("event_duties", []) + state.get("deferred_deadlines", []) if row.get("occurrence_id") == occurrence_id and row["status"] == "EXPIRED"]


def completed_expiry(state, completed):
    for row in expired_for_occurrence(state, completed["occurrence"]["occurrence_id"]):
        clock = row["expiry_basis"]["clock"]
        if completed["evidence_digest"] == clock["evidence_digest"] and completed["occurred_at"] == clock["observed_time"]:
            return True
    return False


def base_decision(receipt, replay, state):
    from . import lifecycle

    relevant = [row for row in state.get("deferred_deadlines", []) if row.get("trigger", {}).get("sequence") == receipt["sequence"]]
    bound = [row for row in state.get("event_duties", []) if row["binding_event_digest"] == receipt["event_digest"] and row["status"] == "EXPIRED"]
    if receipt["event_kind"] == "EFFECT_OBSERVED":
        ids = {value for detail in receipt["details"] if detail["kind"] == "DEADLINE" for value in detail["deadline_ids"]}
        bound.extend(row for row in state.get("event_duties", []) if row["deadline_id"] in ids and row["status"] == "EXPIRED")
    if not bound and (not relevant or not any(row["status"] in {"EXPIRED", "TRIGGER_OVERFLOW"} for row in relevant)):
        return None, None
    base = copy.deepcopy(receipt)
    base["details"] = [row for row in base["details"] if row["kind"] not in {"DEADLINE", "ROUTE", "LIMIT"}]
    if receipt["event_kind"] == "PROPOSE":
        detail = next((row for row in base["details"] if row["kind"] == "AUTHORITY"), None)
        if detail is None:
            return None, None
        base["disposition"] = "WITHHELD"
        base["reason_codes"] = sorted({"AUTHORITY_REQUIRED", detail["code"], *detail["reasons"]}, key=str.encode)
    elif receipt["event_kind"] == "DISPATCH_OBSERVED":
        dispatch = next((row for row in state["dispatches"] if row["event_id"] == receipt["event_id"]), None)
        detail = next((row for row in base["details"] if row["kind"] == "DISPATCH"), None)
        if dispatch is None or detail is None:
            return None, None
        disposition, _ = lifecycle._dispatch_base(dispatch["attempt"], dispatch["acknowledgement"])
        disqualifiers = {"NATIVE_ARGUMENT_MISMATCH", "PERMIT_EXPIRED", "PERMIT_SUPERSEDED", "LATE_OR_PROHIBITED_DISPATCH"}
        if set(detail["reasons"]) & disqualifiers:
            permit = next(row for row in state["permits"] if row["permit_id"] == dispatch["permit_digest"])
            matching = dispatch["native_request"] == permit["native_request"]
            refused = dispatch["acknowledgement"]["status"] != "ACCEPTED" and (dispatch["attempt"]["status"] == "NOT_SENT" or dispatch["attempt"]["status"] == "REJECTED" and matching)
            disposition = "DISPATCH_REFUSED" if refused else "DISPUTED"
        base["disposition"], base["reason_codes"] = disposition, detail["reasons"]
    else:
        effect = next((row for row in base["details"] if row["kind"] == "EFFECT"), None)
        if effect is None:
            return None, None
        classification = effect["classification"]
        base["disposition"] = {"MATCHED": "COMPLETED", "FAILED": "FAILED", "NO_EFFECT_ESTABLISHED": "FAILED", "UNKNOWN": "OUTCOME_RETAINED", "LATE_MATCHED": "OUTCOME_RETAINED", "DUPLICATE": "OUTCOME_RETAINED"}.get(classification, "DISPUTED")
        expiry_reasons = {"EXPIRY_STOP", "ACTIVATION_CLOCK_UNAVAILABLE", "DEADLINE_ALREADY_DUE", "DEADLINE_TIME_OVERFLOW", "LIMIT_EXCEEDED"}
        base["reason_codes"] = [reason for reason in receipt["reason_codes"] if reason not in expiry_reasons]
    copied = copy.deepcopy(replay)
    copied["decision"] = copy.deepcopy(base)
    return base, copied


def _order(state, row):
    from . import lifecycle

    occurrence_id = row.get("occurrence_id")
    if occurrence_id is None:
        return row["due"], 1, row["target_step_id"].encode(), row["deadline_id"].encode()
    return row["due"], 0, canonical(lifecycle._occurrence_from_state(state, occurrence_id)), row["deadline_id"].encode()


def _merge_details(details, extras):
    result = []
    for extra in [*details, *extras]:
        existing = next((row for row in result if row["kind"] == extra["kind"]), None)
        if existing is None:
            result.append(copy.deepcopy(extra))
        elif extra["kind"] in {"DEADLINE", "ROUTE"}:
            for name in ("deadline_ids", "reasons") if extra["kind"] == "DEADLINE" else ("relationship_digests", "construct_ids"):
                existing[name] = sorted(set(existing[name]) | set(extra[name]), key=str.encode)
    order = ["AUTHORITY", "AUTHORIZATION", "SEPARATION", "BUDGET", "DISPATCH", "EFFECT", "COMPLETION_CHECK", "CLOCK", "DEADLINE", "ROUTE", "LABEL", "LIMIT"]
    result.sort(key=lambda row: order.index(row["kind"]))
    return result


def transition(request, state, disposition, reasons, details):
    from . import authority, dispatch_gate, lifecycle

    definition, event = request["definition"], request["event"]
    if not selected(definition):
        return state, disposition, reasons, details
    details = _merge_details(details, [])
    if event["kind"] == "CLOCK" and not any(row["event_id"] == event["event_id"] for row in state["timing_clock_events"]):
        state["timing_clock_events"].append(copy.deepcopy(event))
        state["timing_clock_events"].sort(key=lambda row: row["event_id"].encode())
    synchronize(definition, state)
    if event["kind"] == "CLOCK" and event["clock"]["status"] != "AVAILABLE":
        return state, disposition, reasons, details
    sequence = int(request["state"]["revision"]) + 1
    event_digest = digest("runtime-event", event)
    triggered = None
    if event["kind"] == "PROPOSE" and disposition == "WITHHELD" and any(row["kind"] == "AUTHORITY" for row in details):
        triggered = _withholding_trigger(definition, state, event, authority.evaluate_authority(event["authority_input"], PIN), sequence)
    elif event["kind"] == "DISPATCH_OBSERVED":
        triggered = _dispatch_trigger(definition, state, event, sequence)
    newly_armed = None
    if triggered is not None:
        declaration, trigger, instant = triggered
        occurrence_id = event["occurrence"]["occurrence_id"] if event["kind"] == "PROPOSE" else event["permit"]["occurrence"]["occurrence_id"]
        timer = next(row for row in state["deferred_deadlines"] if row["deadline_id"] == declaration["id"] and row["occurrence_id"] == occurrence_id)
        if timer["status"] == "WAITING":
            try:
                due = lifecycle._add_seconds(instant, duration(declaration["due"]))
            except Refusal as error:
                if error.code != "LIMIT_EXCEEDED":
                    raise
                timer.update(status="TRIGGER_OVERFLOW", trigger=trigger, reason="DEADLINE_TIME_OVERFLOW")
                state["status"] = "STOPPED"
                return state, "STOPPED", sorted(set(reasons) | {"DEADLINE_TIME_OVERFLOW"}, key=str.encode), _merge_details(details, [{"kind": "DEADLINE", "deadline_ids": [timer["deadline_id"]], "reasons": ["DEADLINE_TIME_OVERFLOW"]}])
            timer.update(status="PENDING", trigger=trigger, due=due)
            newly_armed = timer
    changed = []
    if event["kind"] == "CLOCK" and event["clock"]["status"] == "AVAILABLE":
        clock = event["clock"]
        for row in state["deadlines"] + state.get("event_duties", []) + state.get("deferred_deadlines", []):
            if row["status"] == "PENDING" and row["source"] == clock["source"] and lifecycle._due(row, clock["observed_time"]):
                row["status"] = "EXPIRED"
                if "activation_revision" in row:
                    row["expiry_event_digest"] = event_digest
                else:
                    row["expiry_basis"] = {"kind": "CLOCK", "event_digest": event_digest, "clock": copy.deepcopy(clock)}
                changed.append(row)
    changed.extend(_expire_bound(request, state))
    if newly_armed is not None and event["kind"] == "DISPATCH_OBSERVED" and lifecycle._due(newly_armed, newly_armed["trigger"]["clock"]["observed_time"]):
        newly_armed.update(status="EXPIRED", expiry_basis={"kind": "DISPATCH", "event_digest": event_digest, "clock": copy.deepcopy(newly_armed["trigger"]["clock"])})
        changed.append(newly_armed)
    return _expire(request, state, disposition, reasons, details, changed)


def _expire(request, state, disposition, reasons, details, changed):
    from . import lifecycle

    definition = request["definition"]
    base = copy.deepcopy(state)
    simulated = copy.deepcopy(state)
    expired_ids = {row["deadline_id"] for row in changed}
    applied = []
    route_details = []
    stop_reasons = []
    base_stopped = disposition == "STOPPED" and "_timing_rollback_before" in request
    processed = set()
    while True:
        synchronize(definition, simulated)
        for row in _expire_bound(request, simulated):
            expired_ids.add(row["deadline_id"])
        candidates = []
        for row in simulated["deadlines"] + simulated.get("event_duties", []) + simulated.get("deferred_deadlines", []):
            occurrence_id = row.get("occurrence_id")
            active = next((item for item in simulated["active"] if item["occurrence"]["occurrence_id"] == occurrence_id), None)
            if row["status"] != "EXPIRED" or active is None or active["status"] == "BLOCKED_DISPUTE" or occurrence_id in processed:
                continue
            if "activation_revision" in row and request["event"]["kind"] not in {"DISPOSE", "APPLY_DISPOSITION"} and not any(item["deadline_id"] == row["deadline_id"] and item["occurrence_id"] == occurrence_id for item in changed):
                continue
            candidates.append(row)
        if not candidates:
            break
        row = min(candidates, key=lambda item: _order(simulated, item))
        occurrence_id = row["occurrence_id"]
        active = next(item for item in simulated["active"] if item["occurrence"]["occurrence_id"] == occurrence_id)
        processed.add(occurrence_id)
        expired_ids.add(row["deadline_id"])
        if "expiry_basis" in row:
            clock = row["expiry_basis"]["clock"]
        else:
            if request["event"]["kind"] == "CLOCK":
                clock = request["event"]["clock"]
            else:
                receipt = next(item for item in simulated["receipts"] if item["event_digest"] == row["expiry_event_digest"])
                detail = next(item for item in receipt["details"] if item["kind"] == "CLOCK")
                clock = next(item for item in simulated["clocks"] if item["source"] == detail["source"] and item["revision"] == detail["revision"])
        applied.append((copy.deepcopy(active), copy.deepcopy(row), copy.deepcopy(clock)))
        if request["state"]["status"] != "ACTIVE" or base["status"] == "STOPPED":
            lifecycle._complete_late_occurrence(request, simulated, active, "EXPIRED", clock["evidence_digest"], clock["observed_time"])
            continue
        simulated["status"] = "ACTIVE"
        result, item_reasons, item_details = lifecycle._complete_simple_route(request, simulated, active, "EXPIRED", clock["evidence_digest"], None, clock["observed_time"], None)
        route_details = _merge_details(route_details, item_details)
        if result == "STOPPED":
            stop_reasons.extend(item_reasons)
            simulated["status"] = "ACTIVE"
    if not expired_ids:
        if base_stopped:
            _rollback_successors(request, state)
        if state["status"] == "COMPLETE" and unresolved(state):
            raise Refusal("STATE_INVALID")
        return state, disposition, reasons, details
    if stop_reasons or base_stopped:
        # Roll back every projected successor and join while retaining the expired heads.
        for row in simulated.get("event_duties", []):
            if row["status"] == "EXPIRED":
                retained = next(item for item in base["event_duties"] if item["deadline_id"] == row["deadline_id"])
                retained["status"] = "EXPIRED"
                retained["expiry_basis"] = copy.deepcopy(row["expiry_basis"])
        _rollback_successors(request, base)
        for active, row, clock in applied:
            occurrence_id = active["occurrence"]["occurrence_id"]
            if not any(item["occurrence"]["occurrence_id"] == occurrence_id for item in base["active"]):
                continue
            declaration = next(item for item in definition["deadlines"] if item["id"] == row["deadline_id"])
            relation = next((item for item in definition["relationships"] if item["kind"] == "EXPIRY" and item["deadline_ref"] == declaration["id"]), None)
            base["active"] = [item for item in base["active"] if item["occurrence"]["occurrence_id"] != occurrence_id]
            base["completed"].append({"occurrence": copy.deepcopy(active["occurrence"]), "disposition": "EXPIRED", "evidence_digest": clock["evidence_digest"], "occurred_at": clock["observed_time"], "route_label": None, "selected_relationship_digest": None if relation is None else digest("relationship", relation), "late": False})
            lifecycle._discharge_obligation(request, base, active, clock["evidence_digest"])
        base["completed"].sort(key=lambda item: canonical(item["occurrence"]))
        base["status"] = "STOPPED"
        simulated = base
        route_details = [row for row in route_details if row["kind"] in {"DEADLINE", "LIMIT"}]
    elif request["state"]["status"] == "ACTIVE" and base["status"] != "STOPPED":
        if simulated["active"] or any(row["status"] in {"OPEN", "BLOCKED", "WAITING", "DISPUTED"} for row in simulated["obligations"]):
            simulated["status"] = "ACTIVE"
        elif unresolved(simulated):
            raise Refusal("STATE_INVALID")
        else:
            simulated["status"] = "COMPLETE"
    deadline_reasons = sorted({reason for reason in stop_reasons if reason != "LIMIT_EXCEEDED"}, key=str.encode)
    extra = [{"kind": "DEADLINE", "deadline_ids": sorted(expired_ids, key=str.encode), "reasons": deadline_reasons}]
    extra = _merge_details(extra, route_details)
    return simulated, "STOPPED" if stop_reasons or base_stopped else "EXPIRED", sorted(set(reasons) | set(stop_reasons), key=str.encode), _merge_details(details, extra)


def _rollback_successors(request, state):
    from . import lifecycle

    before = request.get("_timing_rollback_before", request["state"])
    original_ids = {row["occurrence"]["occurrence_id"] for row in before["active"] + before["completed"]}
    created_ids = {row["occurrence"]["occurrence_id"] for row in state["active"] + state["completed"]} - original_ids
    state["active"] = [row for row in state["active"] if row["occurrence"]["occurrence_id"] in original_ids]
    state["completed"] = [row for row in state["completed"] if row["occurrence"]["occurrence_id"] in original_ids]
    state["obligations"] = copy.deepcopy(before["obligations"])
    state["fanout_passes"] = copy.deepcopy(before["fanout_passes"])
    completed = {row["occurrence"]["occurrence_id"]: row for row in state["completed"]}
    for active in before["active"]:
        row = completed.get(active["occurrence"]["occurrence_id"])
        if row is not None:
            lifecycle._discharge_obligation(request, state, active, row["evidence_digest"])
    state["deadlines"] = [row for row in state["deadlines"] if row["occurrence_id"] not in created_ids]
    if "deferred_deadlines" in state:
        state["deferred_deadlines"] = [row for row in state["deferred_deadlines"] if row["occurrence_id"] not in created_ids]
    for row in state.get("event_duties", []):
        if row["occurrence_id"] in created_ids:
            row["occurrence_id"] = None
            row["binding_event_digest"] = None
    for row in state["step_counters"]:
        row["activations"] = str(sum(item["occurrence"]["step_id"] == row["step_id"] for item in state["active"] + state["completed"]))
    state["total_activations"] = str(sum(int(row["activations"]) for row in state["step_counters"]))


def unresolved(state):
    return any(row["status"] == "PENDING" or row["status"] == "EXPIRED" and row["occurrence_id"] is None for row in state.get("event_duties", []))


def clock_step(request):
    from . import lifecycle

    state = copy.deepcopy(request["state"])
    clock = request["event"]["clock"]
    prior = [row for row in state["clocks"] if row["source"] == clock["source"]]
    if prior and int(clock["revision"]) <= max(int(row["revision"]) for row in prior):
        raise Refusal("CLOCK_INVALID")
    if clock["status"] == "AVAILABLE":
        if not valid_instant(clock["observed_time"]) or any(row["status"] == "AVAILABLE" and lifecycle._parse(clock["observed_time"]) < lifecycle._parse(row["observed_time"]) for row in prior):
            raise Refusal("CLOCK_INVALID")
    state["clocks"].append(copy.deepcopy(clock))
    state["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))
    detail = {"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]}
    return lifecycle._finish(request, state, "CLOCK_RECORDED", [] if clock["status"] == "AVAILABLE" else ["CLOCK_UNAVAILABLE"], [detail])


def initial_checkpoint(state, definition):
    from . import lifecycle

    prior = copy.deepcopy(state)
    clock_keys = {(detail["source"], detail["revision"]) for receipt in state["receipts"] for detail in receipt["details"] if detail["kind"] == "CLOCK"}
    prior["clocks"] = [row for row in state["clocks"] if (row["source"], row["revision"]) not in clock_keys]
    occurrence = lifecycle._initial_root_occurrence(definition, state["work_class_digest"], state["instance_id"])
    activation = digest("deployment-activation", {"deployment_authorization_digest": state["deployment_authorization_digest"], "instance_id": state["instance_id"], "occurrence_id": occurrence["occurrence_id"]})
    prior.update(revision="0", status="ACTIVE", total_activations="1", total_actuations="0")
    prior["active"] = [{"occurrence": occurrence, "activation_event_digest": activation, "status": "ACTIVE", "deadline_ids": [row["id"] for row in definition["deadlines"] if row["step_id"] == definition["root"]]}]
    prior["step_counters"] = [{"step_id": row["step_id"], "activations": "1" if row["step_id"] == definition["root"] else "0", "actuations": "0"} for row in state["step_counters"]]
    for name in ("completed", "obligations", "proposals", "permits", "dispatches", "outcomes", "fanout_passes", "receipts", "replays", "proposal_authority_evaluations", "recovery_records", "authorizations", "authorization_evaluations", "completion_checks", "terminal_records", "referrals"):
        if name in prior:
            prior[name] = []
    clocks = {row["source"]: row for row in prior["clocks"]}
    prior["deadlines"] = [lifecycle._deadline(definition, row, occurrence, activation, "0", clocks[row["clock_source"]]) for row in definition["deadlines"] if row["step_id"] == definition["root"] and inherited(row)]
    initialize(definition, prior, state.get("initial_event_anchors", []))
    return prior


def state_integrity(state, definition):
    from . import completion, lifecycle

    if not selected(definition):
        return not any(name in state for name in ("initial_event_anchors", "event_duties", "deferred_deadlines", "timing_clock_events"))
    try:
        events = state["timing_clock_events"]
        if not utf8_sorted_unique([row["event_id"] for row in events]):
            return False
        receipts = {row["event_id"]: row for row in state["receipts"] if row["event_kind"] == "CLOCK"}
        if set(receipts) != {row["event_id"] for row in events}:
            return False
        for event in events:
            receipt = receipts[event["event_id"]]
            if event["kind"] != "CLOCK" or event["instance_id"] != state["instance_id"] or event["expected_state_revision"] != str(int(receipt["sequence"]) - 1) or event["expected_state_digest"] != receipt["state_before_digest"] or digest("runtime-event", event) != receipt["event_digest"]:
                return False
        if bool(definition.get("event_anchors")) != ("initial_event_anchors" in state):
            return False
        if any(row["due"]["kind"] == EVENT for row in definition["deadlines"]) != ("event_duties" in state):
            return False
        if any(row["due"]["kind"] in {WITHHELD, DISPATCH} for row in definition["deadlines"]) != ("deferred_deadlines" in state):
            return False
        admit_anchors(definition, state.get("initial_event_anchors", []), state["deployment_authorization"], state["work_class_digest"], state["instance_id"], state["deployment_authorization_clock"])
        if len(state["deadlines"]) + len(state.get("event_duties", [])) + len(state.get("deferred_deadlines", [])) > 4096:
            return False
        for permit in state["permits"]:
            request_bindings(definition, state, permit["occurrence"]["step_id"], permit["native_request"])
        for row in state.get("proposal_authority_evaluations", []):
            request_bindings(definition, state, row["event"]["occurrence"]["step_id"], row["event"]["native_request"])
        if state["status"] == "COMPLETE" and unresolved(state):
            return False
        initial = initial_checkpoint(state, definition)
        expected_sources = sorted({row["clock_source"] for row in definition["deadlines"] if row["due"]["kind"] == EVENT or row["step_id"] == definition["root"] and inherited(row)}, key=str.encode)
        if [row["source"] for row in initial["clocks"]] != expected_sources:
            return False
        if any(clocks["status"] != "AVAILABLE" for clocks in initial["clocks"] if any(row["step_id"] == definition["root"] and inherited(row) and row["clock_source"] == clocks["source"] for row in definition["deadlines"])):
            return False
        reconstructed = completion._advance_evidence(initial, state, definition, int(state["revision"]) + 1)
        return reconstructed is not None and lifecycle.state_digest(reconstructed) == lifecycle.state_digest(state)
    except (Refusal, KeyError, TypeError, ValueError, StopIteration, OverflowError, RuntimeError):
        return False
