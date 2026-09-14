"""Deterministic 1.0 work-class composition and evidence reference consumer."""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import re


PREFIX = "seampoint.work-class/1.0.0-draft.2/"
PROFILES = {"LINEAR", "CHOICE_LOOPS", "DEADLINES", "PARALLEL_FANOUT"}
PROFILE_ROLES = {
    "LINEAR": "LINEAR_WORK_RUNTIME",
    "CHOICE_LOOPS": "CHOICE_LOOP_RUNTIME",
    "DEADLINES": "DEADLINE_RUNTIME",
    "PARALLEL_FANOUT": "PARALLEL_FANOUT_RUNTIME",
}
ID = re.compile(r"^[A-Za-z][A-Za-z0-9._:/-]{0,127}$")
STAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


class Refusal(Exception):
    def __init__(self, code: str, path: str = ""):
        self.code = code
        self.path = path


def canon(value):
    if isinstance(value, dict):
        return b"{" + b",".join(canon(k) + b":" + canon(value[k]) for k in sorted(value, key=lambda k: k.encode("utf-16-be"))) + b"}"
    if isinstance(value, list):
        return b"[" + b",".join(canon(x) for x in value) + b"]"
    if value is None or type(value) is bool or type(value) is str:
        if isinstance(value, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("lone surrogate")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    raise ValueError("JSON number is not admitted")


def digest(kind, value):
    return "sha256:" + hashlib.sha256((PREFIX + kind + "\n").encode() + canon(value)).hexdigest()


def _id(value):
    return isinstance(value, str) and bool(ID.fullmatch(value))


def _stamp(value):
    if not isinstance(value, str) or not STAMP.fullmatch(value):
        raise Refusal("INPUT_INVALID")
    try:
        return _dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
    except ValueError as exc:
        raise Refusal("INPUT_INVALID") from exc


def _natural(value):
    return isinstance(value, str) and bool(re.fullmatch(r"(?:0|[1-9][0-9]*)", value))


def validate_definition(definition):
    if not isinstance(definition, dict) or definition.get("schema") != PREFIX + "work-class-definition":
        raise Refusal("VERSION_UNSUPPORTED")
    required = {"schema", "id", "revision", "profile", "root", "types", "steps", "authority_requirements", "limits", "source"}
    if set(definition) != required or not _id(definition["id"]) or not _id(definition["revision"]):
        raise Refusal("SCHEMA_INVALID")
    profile = definition["profile"]
    if profile not in PROFILES:
        raise Refusal("UNSUPPORTED_RELATION", "/profile")
    steps = definition["steps"]
    if not isinstance(steps, list) or not steps or len(steps) > 256:
        raise Refusal("LIMIT_EXCEEDED", "/steps")
    ids = [row.get("id") for row in steps if isinstance(row, dict)]
    if len(ids) != len(steps) or any(not _id(x) for x in ids) or len(set(ids)) != len(ids) or ids != sorted(ids, key=lambda x: x.encode()):
        raise Refusal("REFERENCE_INVALID", "/steps")
    if definition["root"] not in ids:
        raise Refusal("REFERENCE_INVALID", "/root")
    step_ids = set(ids)
    type_rows = definition["types"]
    if not isinstance(type_rows, list) or not type_rows or len(type_rows) > 64:
        raise Refusal("LIMIT_EXCEEDED", "/types")
    type_ids = [row.get("id") for row in type_rows if isinstance(row, dict)]
    if len(type_ids) != len(type_rows) or any(not _id(x) for x in type_ids) or len(set(type_ids)) != len(type_ids) or type_ids != sorted(type_ids, key=lambda x: x.encode()):
        raise Refusal("REFERENCE_INVALID", "/types")
    type_set = set(type_ids)
    step_required = {"id", "kind", "executor_role", "interface", "operation", "fields", "required_credentials", "next", "labels", "failure_target", "max_occurrences", "deadline", "branches", "object_field", "fanout_target", "empty_result"}
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise Refusal("SCHEMA_INVALID", f"/steps/{i}")
        if set(step) != step_required:
            raise Refusal("SCHEMA_INVALID", f"/steps/{i}")
        kind = step.get("kind")
        if kind not in {"TASK", "CHOICE", "LOOP", "DEADLINE", "PARALLEL_SPLIT", "PARALLEL_JOIN", "FANOUT_EXPAND", "FANOUT_JOIN", "TERMINAL"}:
            raise Refusal("SCHEMA_INVALID", f"/steps/{i}/kind")
        for field in ("next", "failure_target", "fanout_target"):
            target = step.get(field)
            if target is not None and target not in step_ids:
                raise Refusal("REFERENCE_INVALID", f"/steps/{i}/{field}")
        for target in step.get("labels", {}).values():
            if target not in step_ids:
                raise Refusal("REFERENCE_INVALID", f"/steps/{i}/labels")
        for target in step.get("branches", []):
            if target not in step_ids:
                raise Refusal("REFERENCE_INVALID", f"/steps/{i}/branches")
        fields = step.get("fields")
        if not isinstance(fields, list) or len(fields) > 64 or len({row.get("name") for row in fields if isinstance(row, dict)}) != len(fields):
            raise Refusal("INPUT_INVALID", f"/steps/{i}/fields")
        field_names = []
        for field in fields:
            if not isinstance(field, dict) or set(field) != {"name", "type_ref"} or not _id(field.get("name")) or field.get("type_ref") not in type_set:
                raise Refusal("REFERENCE_INVALID", f"/steps/{i}/fields")
            field_names.append(field["name"])
        if field_names != sorted(field_names, key=lambda x: x.encode()):
            raise Refusal("INPUT_INVALID", f"/steps/{i}/fields")
        credentials = step.get("required_credentials")
        if not isinstance(credentials, list) or len(credentials) > 64 or len(set(credentials)) != len(credentials) or any(not _id(x) for x in credentials):
            raise Refusal("SCHEMA_INVALID", f"/steps/{i}/required_credentials")
        if kind == "CHOICE":
            labels = step.get("labels")
            if not isinstance(labels, dict) or not labels or len(labels) != len(set(labels)):
                raise Refusal("REFERENCE_INVALID", f"/steps/{i}/labels")
            if any(not isinstance(label, str) or not label for label in labels):
                raise Refusal("TYPE_INVALID", f"/steps/{i}/labels")
        if kind == "LOOP":
            if not _natural(step.get("max_occurrences")) or step["max_occurrences"] == "0":
                raise Refusal("LIMIT_EXCEEDED", f"/steps/{i}/max_occurrences")
        if kind == "PARALLEL_SPLIT" and len(step.get("branches", [])) < 2:
            raise Refusal("REFERENCE_INVALID", f"/steps/{i}/branches")
        if kind == "FANOUT_EXPAND" and not step.get("object_field"):
            raise Refusal("SCHEMA_INVALID", f"/steps/{i}/object_field")
        if kind in {"DEADLINE", "TASK", "LOOP"} and step.get("deadline") is not None:
            deadline = step["deadline"]
            if not isinstance(deadline, dict) or set(deadline) != {"kind", "due", "clock_source", "failure_target"} or deadline["kind"] not in {"AT_OR_AFTER", "AFTER"} or not _id(deadline["clock_source"]):
                raise Refusal("SCHEMA_INVALID", f"/steps/{i}/deadline")
            _stamp(deadline["due"])
            if deadline["failure_target"] not in step_ids:
                raise Refusal("REFERENCE_INVALID", f"/steps/{i}/deadline/failure_target")
        if kind == "FANOUT_JOIN" and step.get("next") == definition["root"]:
            raise Refusal("UNSUPPORTED_RELATION", f"/steps/{i}/next")
    # Every declared node must participate in the admitted graph. Detecting
    # this at admission prevents a hidden branch from becoming an unbounded
    # or unaudited execution path.
    edges = {row["id"]: set() for row in steps}
    for row in steps:
        for key in ("next", "failure_target", "fanout_target"):
            if row.get(key): edges[row["id"]].add(row[key])
        edges[row["id"]].update(row.get("labels", {}).values())
        edges[row["id"]].update(row.get("branches", []))
        if row.get("deadline"): edges[row["id"]].add(row["deadline"]["failure_target"])
    reachable = set(); stack = [definition["root"]]
    while stack:
        node = stack.pop()
        if node in reachable: continue
        reachable.add(node); stack.extend(edges[node])
    if reachable != step_ids:
        raise Refusal("REFERENCE_INVALID", "/steps")
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        cycle = any(visit(target) for target in edges[node])
        visiting.remove(node); visited.add(node)
        return cycle
    if visit(definition["root"]):
        cycle_nodes = {node for node in step_ids if node in visiting}
        if not any(row.get("kind") == "LOOP" and row.get("max_occurrences") for row in steps):
            raise Refusal("UNSUPPORTED_RELATION", "/steps")
    # Every declared branch must remain inside structured work until it
    # reaches a join. A terminal or an unstructured edge would otherwise
    # discharge the block without creating the join's complete obligation
    # record.
    by_id = {row["id"]: row for row in steps}
    for split in steps:
        if split.get("kind") != "PARALLEL_SPLIT":
            continue
        for branch in split.get("branches", []):
            pending, seen_branch, joined = [branch], set(), False
            while pending:
                node = pending.pop()
                if node in seen_branch:
                    continue
                seen_branch.add(node)
                row = by_id[node]
                if row.get("kind") == "PARALLEL_JOIN":
                    joined = True
                    continue
                if row.get("kind") == "TERMINAL":
                    raise Refusal("UNSUPPORTED_RELATION", f"/steps/{node}")
                pending.extend(edges[node])
            if not joined:
                raise Refusal("UNSUPPORTED_RELATION", f"/steps/{branch}")
    if profile == "CHOICE_LOOPS" and any(row.get("kind") == "CHOICE" and not row.get("labels") for row in steps):
        raise Refusal("REFERENCE_INVALID", "/steps")
    if profile == "DEADLINES" and not any(row.get("deadline") for row in steps):
        raise Refusal("REFERENCE_INVALID", "/steps")
    if profile == "PARALLEL_FANOUT" and not any(row.get("kind") in {"PARALLEL_SPLIT", "FANOUT_EXPAND"} for row in steps):
        raise Refusal("REFERENCE_INVALID", "/steps")
    limits = definition["limits"]
    if not isinstance(limits, dict) or set(limits) != {"max_activations", "max_dispatches"} or not all(_natural(limits.get(k)) for k in limits):
        raise Refusal("SCHEMA_INVALID", "/limits")
    if definition.get("profile") == "LINEAR" and any(row.get("kind") not in {"TASK", "TERMINAL"} for row in steps):
        raise Refusal("UNSUPPORTED_RELATION", "/profile")
    if definition.get("profile") == "CHOICE_LOOPS" and any(row.get("kind") in {"DEADLINE", "PARALLEL_SPLIT", "PARALLEL_JOIN", "FANOUT_EXPAND", "FANOUT_JOIN"} for row in steps):
        raise Refusal("UNSUPPORTED_RELATION", "/profile")
    if definition.get("profile") == "DEADLINES" and any(row.get("kind") in {"CHOICE", "LOOP", "PARALLEL_SPLIT", "PARALLEL_JOIN", "FANOUT_EXPAND", "FANOUT_JOIN"} for row in steps):
        raise Refusal("UNSUPPORTED_RELATION", "/profile")
    return digest("work-class-definition", definition)


def validate_boundary(record):
    required = {"schema", "id", "paragraph_ids", "requirement_ids", "external_fact", "responsible_party", "control", "evidence_format", "failure_behavior", "verification_method", "residual_limitation"}
    if not isinstance(record, dict) or set(record) != required or record.get("schema") != PREFIX + "boundary-record" or not _id(record.get("id")):
        raise Refusal("SCHEMA_INVALID")
    for key in ("paragraph_ids", "requirement_ids"):
        if not isinstance(record[key], list) or not record[key] or len(set(record[key])) != len(record[key]) or not all(_id(x) for x in record[key]):
            raise Refusal("SCHEMA_INVALID", f"/{key}")
    for key in required - {"schema", "id", "paragraph_ids", "requirement_ids"}:
        if not isinstance(record[key], str) or not record[key].strip():
            raise Refusal("SCHEMA_INVALID", f"/{key}")
    return digest("boundary-record", record)


def _state_digest(state):
    value = {k: v for k, v in state.items() if k != "receipts"}
    return digest("work-state", value)


def _initial(definition, pin, instance):
    root = next(row for row in definition["steps"] if row["id"] == definition["root"])
    active = [{"step": root["id"], "occurrence": "root:1", "ancestry": [], "object": None, "status": "ACTIVE"}]
    return {"schema": PREFIX + "work-state", "specification_pin": pin, "definition_digest": digest("work-class-definition", definition), "instance": instance, "revision": "0", "active": active, "completed": [], "obligations": [], "dispatches": [], "clock": None, "receipts": []}


def deploy(request, pin):
    if not isinstance(request, dict):
        raise Refusal("SCHEMA_INVALID")
    required = {"profile", "role", "specification_pin", "definition", "definition_digest", "instance", "authority"}
    if set(request) != required:
        raise Refusal("SCHEMA_INVALID")
    if request["specification_pin"] != pin:
        raise Refusal("VERSION_UNSUPPORTED", "/specification_pin")
    if request["role"] != PROFILE_ROLES.get(request["profile"]):
        raise Refusal("ROLE_UNSUPPORTED", "/role")
    identity = validate_definition(request["definition"])
    if identity != request["definition_digest"]:
        raise Refusal("INPUT_INVALID", "/definition_digest")
    if not _id(request["instance"]):
        raise Refusal("SCHEMA_INVALID", "/instance")
    authority = request["authority"]
    if not isinstance(authority, dict) or authority.get("status") != "ACCEPTED" or not isinstance(authority.get("subject_digest"), str):
        raise Refusal("AUTHORITY_REQUIRED", "/authority")
    state = _initial(request["definition"], pin, request["instance"])
    state_digest = _state_digest(state)
    return {"status": "DEPLOYED", "profile": request["profile"], "role": request["role"], "instance": request["instance"], "definition_digest": identity, "state": state, "state_digest": state_digest}


def _step_map(definition):
    return {row["id"]: row for row in definition["steps"]}


def _reasons_result(state, event, decision, reasons, pin, replay=False, next_state=None):
    prior = _state_digest(state)
    next_state = copy.deepcopy(state) if next_state is None else next_state
    next_state["revision"] = str(int(state["revision"]) + 1)
    receipt = {"event_id": event.get("id"), "event_digest": digest("work-event", event), "prior_state_digest": prior, "revision": next_state["revision"], "decision": decision, "reasons": sorted(set(reasons))}
    next_state["receipts"] = list(state.get("receipts", [])) + [receipt]
    sd = _state_digest(next_state)
    receipt["next_state_digest"] = sd
    return {"status": "STEP", "decision": decision, "reasons": sorted(set(reasons)), "receipt": receipt, "receipt_digest": digest("work-receipt", receipt), "state": next_state, "state_digest": sd, "replay": replay}


def _activate(state, definition, step_id, parent, object_value=None):
    steps = _step_map(definition)
    step = steps[step_id]
    active = state["active"]
    count = sum(1 for row in state["completed"] + active if row.get("step") == step_id)
    maximum = step.get("max_occurrences")
    if maximum is not None and count >= int(maximum):
        raise Refusal("LOOP_BOUND_REACHED", "/event")
    total = len(state["completed"]) + len(active)
    if total >= int(definition["limits"]["max_activations"]):
        raise Refusal("LIMIT_EXCEEDED", "/event")
    suffix = str(len([row for row in active + state["completed"] if row.get("step") == step_id]) + 1)
    ancestry = list(parent.get("ancestry", [])) + [parent["occurrence"]]
    occurrence = step_id + ":" + suffix
    if object_value is not None:
        occurrence += "/" + str(object_value)
    active.append({"step": step_id, "occurrence": occurrence, "ancestry": ancestry, "object": object_value, "status": "ACTIVE"})


def step(request, pin):
    required = {"profile", "role", "specification_pin", "definition", "definition_digest", "state", "state_digest", "event"}
    if not isinstance(request, dict) or set(request) != required:
        raise Refusal("SCHEMA_INVALID")
    if request["specification_pin"] != pin:
        raise Refusal("VERSION_UNSUPPORTED", "/specification_pin")
    if request["role"] != PROFILE_ROLES.get(request["profile"]):
        raise Refusal("ROLE_UNSUPPORTED", "/role")
    definition_digest = validate_definition(request["definition"])
    if definition_digest != request["definition_digest"]:
        raise Refusal("INPUT_INVALID", "/definition_digest")
    state = request["state"]
    if not isinstance(state, dict) or state.get("specification_pin") != pin or state.get("definition_digest") != definition_digest or request["state_digest"] != _state_digest(state):
        raise Refusal("DEPENDENCY_MISMATCH", "/state_digest")
    event = request["event"]
    if not isinstance(event, dict) or not _id(event.get("id")) or event.get("kind") not in {"COMPLETE", "CLOCK"}:
        raise Refusal("SCHEMA_INVALID", "/event")
    for receipt in reversed(state.get("receipts", [])):
        if event.get("id") == receipt.get("event_id"):
            if digest("work-event", event) == receipt.get("event_digest"):
                return {"status": "STEP", "decision": receipt["decision"], "reasons": receipt["reasons"], "receipt": receipt, "receipt_digest": digest("work-receipt", receipt), "state": state, "state_digest": request["state_digest"], "replay": True}
            raise Refusal("EVENT_CONFLICT", "/event/id")
    steps = _step_map(request["definition"])
    if event["kind"] == "CLOCK":
        clock = event.get("clock")
        if not isinstance(clock, dict) or set(clock) != {"source", "status", "instant", "revision"} or clock["source"] not in {row.get("deadline", {}).get("clock_source") for row in steps.values() if row.get("deadline")}:
            raise Refusal("DEPENDENCY_MISMATCH", "/event/clock/source")
        if clock["status"] == "UNAVAILABLE":
            return _reasons_result(state, event, "HOLD", ["CLOCK_UNAVAILABLE"], pin)
        if clock["status"] != "AVAILABLE" or not _natural(clock["revision"]):
            raise Refusal("INPUT_INVALID", "/event/clock")
        current = state.get("clock")
        if current is not None and int(clock["revision"]) <= int(current["revision"]):
            raise Refusal("CLOCK_INVALID", "/event/clock/revision")
        instant = _stamp(clock["instant"])
        next_state = copy.deepcopy(state)
        next_state["clock"] = clock
        decision = "CLOCK_ACCEPTED"
        reasons = []
        for active in list(next_state["active"]):
            deadline = steps[active["step"]].get("deadline")
            if not deadline or active.get("expired"):
                continue
            due = _stamp(deadline["due"])
            passed = instant >= due if deadline["kind"] == "AT_OR_AFTER" else instant > due
            if passed:
                next_state["active"].remove(active)
                expired = dict(active); expired.update({"status": "EXPIRED", "expired": True, "expired_at": clock["instant"]})
                next_state["completed"].append(expired)
                try: _activate(next_state, request["definition"], deadline["failure_target"], active)
                except Refusal: reasons.append("LOOP_BOUND_REACHED")
                decision = "EXPIRED"
        return _reasons_result(state, event, decision, reasons, pin, next_state=next_state)
    occurrence = event.get("occurrence")
    active = next((row for row in state["active"] if row.get("occurrence") == occurrence), None)
    if active is None:
        expired = next((row for row in state.get("completed", []) if row.get("occurrence") == occurrence and row.get("status") == "EXPIRED"), None)
        if expired is not None:
            next_state = copy.deepcopy(state)
            for row in next_state["completed"]:
                if row.get("occurrence") == occurrence:
                    row.setdefault("late_events", []).append(copy.deepcopy(event))
            return _reasons_result(state, event, "LATE_EFFECT_RETAINED", ["LATE_COMPLETION"], pin, next_state=next_state)
        raise Refusal("OCCURRENCE_NOT_ACTIVE", "/event/occurrence")
    step_def = steps[active["step"]]
    next_state = copy.deepcopy(state)
    next_state["active"] = [row for row in next_state["active"] if row.get("occurrence") != occurrence]
    completed = dict(active); completed.update({"status": "COMPLETED", "outcome": event.get("outcome", "SUCCESS")})
    next_state["completed"].append(completed)
    if len(next_state["dispatches"]) >= int(request["definition"]["limits"]["max_dispatches"]):
        return _reasons_result(state, event, "WITHHELD", ["DISPATCH_LIMIT_REACHED"], pin, next_state=next_state)
    next_state["dispatches"].append({"occurrence": occurrence, "step": active["step"], "event_id": event["id"]})
    for obligation in next_state["obligations"]:
        if obligation.get("parent") in active.get("ancestry", []) and obligation.get("step") == active.get("step") and obligation.get("status") == "OPEN":
            obligation["status"] = "DONE"
    decision = "COMPLETED"
    reasons = []
    target = None
    if step_def["kind"] == "CHOICE":
        if event.get("outcome", "SUCCESS") not in {"SUCCESS", "SUCCEEDED"}:
            target = step_def.get("failure_target")
            if target is None: decision, reasons = "STOPPED", ["CHOICE_FAILURE"]
        else:
            label = event.get("label")
            if not isinstance(label, str) or label not in step_def.get("labels", {}):
                raise Refusal("ROUTE_INVALID", "/event/label")
            target = step_def["labels"][label]
    elif step_def["kind"] == "PARALLEL_SPLIT":
        obligations = [{"parent": occurrence, "step": branch, "status": "OPEN"} for branch in step_def["branches"]]
        next_state["obligations"].extend(obligations)
        for branch in step_def["branches"]: _activate(next_state, request["definition"], branch, active)
    elif step_def["kind"] == "FANOUT_EXPAND":
        objects = event.get("objects")
        if not isinstance(objects, list) or len(objects) != len(set(map(str, objects))) or objects != sorted(objects, key=lambda x: str(x).encode()):
            raise Refusal("INPUT_INVALID", "/event/objects")
        if not objects:
            if step_def.get("empty_result") == "STOP": decision, reasons = "STOPPED", ["EMPTY_FANOUT"]
            elif step_def.get("empty_result") == "ADVANCE": target = step_def.get("next")
            else: raise Refusal("INPUT_INVALID", "/event/objects")
        else:
            for obj in objects: _activate(next_state, request["definition"], step_def["fanout_target"], active, obj)
    else:
        target = step_def.get("next")
    # A branch or frozen object occurrence whose declared successor is a join
    # discharges its obligation first. The join is activated only after every
    # obligation for that exact split or expansion is complete.
    if target and steps[target]["kind"] in {"PARALLEL_JOIN", "FANOUT_JOIN"}:
        parent = active.get("ancestry", [])[-1] if active.get("ancestry") else None
        obligations = [row for row in next_state["obligations"] if row.get("parent") == parent]
        if obligations and all(row.get("status") == "DONE" for row in obligations):
            for row in obligations: row["status"] = "JOINED"
        else:
            target = None
    if target:
        try: _activate(next_state, request["definition"], target, active)
        except Refusal as exc:
            if exc.code == "LOOP_BOUND_REACHED": decision, reasons = "WITHHELD", ["LOOP_BOUND_REACHED"]
            else: raise
    return _reasons_result(state, event, decision, reasons, pin, next_state=next_state)


def check_evidence(request, pin):
    required = {"profile", "role", "specification_pin", "subject", "evidence"}
    if not isinstance(request, dict) or set(request) != required:
        raise Refusal("SCHEMA_INVALID")
    if request["specification_pin"] != pin or request["role"] != "REVIEW_EVIDENCE":
        raise Refusal("ROLE_UNSUPPORTED")
    subject, evidence = request["subject"], request["evidence"]
    if not isinstance(subject, dict) or not isinstance(evidence, dict): raise Refusal("SCHEMA_INVALID")
    subject_digest = digest("evidence-subject", subject)
    if evidence.get("subject_digest") != subject_digest: raise Refusal("BINDING_MISMATCH", "/evidence/subject_digest")
    if evidence.get("status") in {"PENDING", "REJECTED", "DEFERRED"}: raise Refusal("EVIDENCE_UNAVAILABLE", "/evidence/status")
    return {"status": "EVIDENCE_VALID", "subject_digest": subject_digest, "evidence_digest": digest("evidence", evidence), "specification_pin": pin}
