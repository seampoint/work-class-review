"""Pure direct-grant authority evaluator for the draft profile."""
from __future__ import annotations

import base64
import datetime as datetime
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "input/authority.schema.json").read_text())
AGG_URI = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/aggregate.schema.json"
REGISTRY = {
    SCHEMA["$id"]: SCHEMA,
    AGG_URI: json.loads((ROOT / "input/aggregate.schema.json").read_text()),
}
for schema_path in (ROOT / "input").glob("*.schema.json"):
    bundled = json.loads(schema_path.read_text())
    REGISTRY[bundled["$id"]] = bundled
RESOLVER = RefResolver(SCHEMA["$id"], SCHEMA, store=REGISTRY)
AUTH_PREFIX = "seampoint.work-class/1.0.0-draft.3/"
STAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
NATURAL = re.compile(r"^(0|[1-9][0-9]*)$")
DECIMAL = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$")


def canonical(value):
    """Return WCS2-001 canonical JSON bytes."""
    if isinstance(value, dict):
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        return b"{" + b",".join(canonical(key) + b":" + canonical(value[key]) for key in keys) + b"}"
    if isinstance(value, list):
        return b"[" + b",".join(canonical(item) for item in value) + b"]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(kind, value):
    return "sha256:" + hashlib.sha256((AUTH_PREFIX + kind + "\n").encode() + canonical(value)).hexdigest()


def _refusal(code, reasons=(), failed_checks=()):
    return {"status": "REFUSED", "code": code, "path": "", "reasons": sorted(set(reasons)), "failed_checks": sorted({canonical(row): row for row in failed_checks}.values(), key=canonical)}


def _valid(value, name):
    try:
        validator = Draft202012Validator({"$ref": f"{SCHEMA['$id']}#/$defs/{name}"}, resolver=RESOLVER)
        return not list(validator.iter_errors(value))
    except Exception:
        return False


def _instant(value):
    if not isinstance(value, str) or not STAMP.fullmatch(value):
        raise ValueError
    return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def _inside(interval, instant):
    return _instant(interval["valid_from"]) <= instant and (interval["valid_until"] is None or instant < _instant(interval["valid_until"]))


def _records(records):
    return {record["id"]: record for record in records}


def _utf8(value):
    return value.encode("utf-8")


def _ordered_unique(values, key=lambda value: value):
    keys = [key(value) for value in values]
    return len(keys) == len(set(keys)) and keys == sorted(keys)


def _predicate_member_sets_ordered(predicate):
    kind = predicate["kind"]
    ordered_members = (kind != "MEMBER" or
                       _ordered_unique([canonical(member) for member in predicate["members"]]))
    if kind in ("ALL", "ANY"):
        return ordered_members and all(_predicate_member_sets_ordered(child) for child in predicate["operands"])
    if kind == "NOT":
        return ordered_members and _predicate_member_sets_ordered(predicate["operand"])
    return ordered_members


def _type_map(work_class):
    return {item["id"]: item for item in work_class["types"]}


def _step_map(work_class):
    return {item["id"]: item for item in work_class["steps"]}


def _field_map(step):
    return {item["name"]: item for item in step["fields"]}


def _typed_value_valid(value, types):
    """Validate a value when its nominal type is declared."""
    if not isinstance(value, dict) or value.get("type_ref") not in types:
        return True
    declaration = types[value["type_ref"]]
    payload = value.get("value")
    kind = declaration["kind"]
    if kind in ("IDENTITY", "STRING") and not isinstance(payload, str):
        return False
    if kind == "IDENTITY" and payload == "":
        return False
    if kind == "INSTANT":
        try:
            _instant(payload)
        except (TypeError, ValueError):
            return False
    if kind == "BOOLEAN" and type(payload) is not bool:
        return False
    if kind == "INTEGER" and (not isinstance(payload, str) or not NATURAL.fullmatch(payload)):
        return False
    if kind == "DECIMAL" and (not isinstance(payload, str) or not DECIMAL.fullmatch(payload)):
        return False
    if kind not in ("INTEGER", "DECIMAL") and declaration["nonnegative"]:
        return False
    return True


def _all_typed_values(value, types):
    if isinstance(value, dict):
        if "type_ref" in value and "value" in value and not _typed_value_valid(value, types):
            return False
        return all(_all_typed_values(child, types) for child in value.values())
    if isinstance(value, list):
        return all(_all_typed_values(child, types) for child in value)
    return True


def _operand_type(operand, fields, types, faults):
    """Resolve an operand's nominal type, recording faults instead of raising.

    Returns the operand's known nominal type, or None when that type cannot be
    known (an undeclared FIELD or an unknown type reference). A FIELD naming a
    field the row's step does not declare is REFERENCE_INVALID.
    """
    if operand["kind"] == "FIELD":
        declaration = fields.get(operand["name"])
        if declaration is None:
            faults.add("REFERENCE_INVALID")
            return None
        type_ref = declaration["type_ref"]
        if type_ref not in types:
            faults.add("REFERENCE_INVALID")
            return None
        return type_ref
    type_ref = operand["value"]["type_ref"]
    if type_ref not in types:
        faults.add("REFERENCE_INVALID")
        return None
    if not _typed_value_valid(operand["value"], types):
        faults.add("TYPE_INVALID")
    return type_ref


def _predicate_type_faults(predicate, fields, types, faults):
    """Collect every branch's and operand's static faults (AUTH-001).

    No branch short-circuits another: each operand is checked even when another
    branch decides the predicate. A known type that alone violates its
    operator's rule is TYPE_INVALID; a violation that depends on an unknown
    type is left to that operand's REFERENCE_INVALID.
    """
    kind = predicate["kind"]
    if kind == "BOOLEAN":
        return
    if kind in ("EQUAL", "COMPARE"):
        left = _operand_type(predicate["left"], fields, types, faults)
        right = _operand_type(predicate["right"], fields, types, faults)
        if kind == "COMPARE":
            for known in (left, right):
                if known is not None and types[known]["kind"] not in ("INTEGER", "DECIMAL"):
                    faults.add("TYPE_INVALID")
        if left is not None and right is not None and left != right:
            faults.add("TYPE_INVALID")
        return
    if kind == "MEMBER":
        value_type = _operand_type(predicate["value"], fields, types, faults)
        # MEMBER places no kind restriction on its value type, so a known value
        # type alone never violates it. A member literal of unknown type is
        # REFERENCE_INVALID; its mismatch with the value depends on that type.
        for member in predicate["members"]:
            if member["type_ref"] not in types:
                faults.add("REFERENCE_INVALID")
                continue
            if not _typed_value_valid(member, types):
                faults.add("TYPE_INVALID")
            if value_type is not None and member["type_ref"] != value_type:
                faults.add("TYPE_INVALID")
        return
    if kind in ("ALL", "ANY"):
        for child in predicate["operands"]:
            _predicate_type_faults(child, fields, types, faults)
        return
    if kind == "NOT":
        _predicate_type_faults(predicate["operand"], fields, types, faults)
        return
    faults.add("TYPE_INVALID")


def _predicate_value(operand, fields):
    value = fields[operand["name"]]["value"] if operand["kind"] == "FIELD" else operand["value"]
    return value["type_ref"], value["value"]


def _pred(predicate, fields, types=None):
    """Evaluate a statically type-checked predicate without string coercion."""
    types = types or {}
    kind = predicate["kind"]
    if kind == "BOOLEAN":
        return predicate["value"]
    if kind in ("EQUAL", "COMPARE"):
        left_type, left = _predicate_value(predicate["left"], fields)
        right_type, right = _predicate_value(predicate["right"], fields)
        if left_type != right_type:
            return False
        if kind == "EQUAL":
            return left == right
        if types and types[left_type]["kind"] not in ("INTEGER", "DECIMAL"):
            return False
        left, right = Decimal(left), Decimal(right)
        return {"LT": left < right, "LTE": left <= right, "GT": left > right, "GTE": left >= right}[predicate["operator"]]
    if kind == "MEMBER":
        value_type, value = _predicate_value(predicate["value"], fields)
        return any(member["type_ref"] == value_type and member["value"] == value for member in predicate["members"])
    if kind == "ALL":
        return all(_pred(child, fields, types) for child in predicate["operands"])
    if kind == "ANY":
        return any(_pred(child, fields, types) for child in predicate["operands"])
    return not _pred(predicate["operand"], fields, types)


def _date_admission(value):
    invalid = False

    def walk(node):
        nonlocal invalid
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {"valid_from", "valid_until", "occurred_at", "returned_at", "at", "as_of", "instant"} and child is not None and not (key == "at" and child == "CLOCK"):
                    try:
                        _instant(child)
                    except (TypeError, ValueError):
                        invalid = True
                walk(child)
            if node.get("status") == "AVAILABLE" and isinstance(node.get("query"), dict) and node.get("as_of") is not None and "requirement_id" not in node["query"]:
                try:
                    if _instant(node["as_of"]) > _instant(node["query"]["at"]):
                        invalid = True
                except (KeyError, TypeError, ValueError):
                    invalid = True
            if "valid_from" in node and "valid_until" in node:
                try:
                    if node["valid_until"] is not None and _instant(node["valid_from"]) >= _instant(node["valid_until"]):
                        invalid = True
                except (TypeError, ValueError):
                    invalid = True
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return not invalid


def _inventory_admission(request):
    """Validate all specified uniqueness and canonical order constraints."""
    checks = []

    def ids(items, field="id"):
        return _ordered_unique([item[field] for item in items], _utf8)

    checks.extend([
        ids(request["source"]["obligations"]), ids(request["work_class"]["types"]), ids(request["work_class"]["steps"]),
        ids(request["envelope"]["bindings"]), ids(request["envelope"]["conditions"]), ids(request["envelope"]["limits"]["per_action"]),
        ids(request["host_selection"]["root"]["channels"]), ids(request["occupancies"]), ids(request["capacities"]),
        ids(request["credentials"]), ids(request["returns"]), _ordered_unique([digest("authority-act", act) for act in request["acts"]]),
        _ordered_unique([canonical(record) for record in request["host_selection"]["authenticated_records"]]),
        all(_ordered_unique(act["criteria"], _utf8) for act in request["acts"]),
    ])
    for step in request["work_class"]["steps"]:
        checks.extend([_ordered_unique([field["name"] for field in step["fields"]], _utf8), _ordered_unique(step["scope_fields"]["subjects"], _utf8), _ordered_unique(step["scope_fields"]["resources"], _utf8), _ordered_unique(step["required_credentials"], _utf8), _ordered_unique([key["id"] for key in step.get("exclusive_keys", [])], _utf8)])
        checks.extend(len({projection.get("key_field", projection.get("field")) for projection in key["projection"]}) == len(key["projection"]) for key in step.get("exclusive_keys", []))
    envelope = request["envelope"]
    steps = {step["id"]: step for step in request["work_class"]["steps"]}
    types = {type_row["id"]: type_row for type_row in request["work_class"]["types"]}
    checks.append(_ordered_unique([row["id"] for row in envelope.get("source_observation_requirements", [])], _utf8))
    for requirement in envelope.get("source_observation_requirements", []):
        checks.extend([_ordered_unique([row["name"] for row in requirement["fields"]], _utf8),
                       _ordered_unique([row["id"] for row in requirement["relations"]], _utf8)])
    checks.extend([
        _ordered_unique([item["step"] for item in envelope["operations"]], _utf8),
        _ordered_unique([canonical(item) for item in envelope["scope"]["subjects"]]), _ordered_unique([canonical(item) for item in envelope["scope"]["resources"]]),
        _ordered_unique(envelope["limits"]["shared_budgets"], _utf8), _ordered_unique(envelope["enforcement"]["mechanisms"], _utf8),
        _ordered_unique(envelope["gate"]["criteria"], lambda item: _utf8(item["id"])),
        _ordered_unique(request["host_selection"]["root"]["capacity_ids"], _utf8), _ordered_unique(request["host_selection"]["root"]["occupancy_ids"], _utf8),
        _ordered_unique(request["host_selection"]["root"]["providers"], _utf8), _ordered_unique(request["proposal"]["fields"], lambda item: _utf8(item["name"])),
        _ordered_unique(request["host_selection"]["root"]["limitations"], _utf8), _ordered_unique(envelope["limitations"], _utf8),
    ])
    checks.append(all(_predicate_member_sets_ordered(row["predicate"])
                      for row in envelope["conditions"] + envelope["gate"]["criteria"]))
    checks.extend(_ordered_unique(capacity["act_kinds"], _utf8) for capacity in request["capacities"])
    return all(checks)


def _definition_inventory(definition):
    source, work_class, envelope = definition["source"], definition["work_class"], definition["envelope"]
    checks = [
        _ordered_unique([item["id"] for item in source["obligations"]], _utf8),
        _ordered_unique([item["id"] for item in work_class["types"]], _utf8),
        _ordered_unique([item["id"] for item in work_class["steps"]], _utf8),
        _ordered_unique([item["id"] for item in envelope["bindings"]], _utf8),
        _ordered_unique([item["step"] for item in envelope["operations"]], _utf8),
        _ordered_unique([item["id"] for item in envelope["conditions"]], _utf8),
        _ordered_unique([item["id"] for item in envelope["limits"]["per_action"]], _utf8),
        _ordered_unique(envelope["limits"]["shared_budgets"], _utf8),
        _ordered_unique(envelope["enforcement"]["mechanisms"], _utf8),
        _ordered_unique([item["id"] for item in envelope["gate"]["criteria"]], _utf8),
        _ordered_unique([canonical(item) for item in envelope["scope"]["subjects"]]),
        _ordered_unique([canonical(item) for item in envelope["scope"]["resources"]]),
        _ordered_unique([item["id"] for item in envelope.get("source_observation_requirements", [])], _utf8),
    ]
    for step in work_class["steps"]:
        checks.extend([
            _ordered_unique([field["name"] for field in step["fields"]], _utf8),
            _ordered_unique(step["scope_fields"]["subjects"], _utf8),
            _ordered_unique(step["scope_fields"]["resources"], _utf8),
            _ordered_unique(step["required_credentials"], _utf8),
            _ordered_unique([key["id"] for key in step.get("exclusive_keys", [])], _utf8),
        ])
        checks.extend(len({projection.get("key_field", projection.get("field")) for projection in key["projection"]}) == len(key["projection"]) for key in step.get("exclusive_keys", []))
    for requirement in envelope.get("source_observation_requirements", []):
        checks.extend([
            _ordered_unique([field["name"] for field in requirement["fields"]], _utf8),
            _ordered_unique([relation["id"] for relation in requirement["relations"]], _utf8),
        ])
    checks.append(all(_predicate_member_sets_ordered(row["predicate"])
                      for row in envelope["conditions"] + envelope["gate"]["criteria"]))
    return all(checks)


def _predicate_admission(definition, request=None):
    """Accumulate predicate faults over every row, branch and operand.

    TYPE_INVALID is a phase-1 code and REFERENCE_INVALID a phase-2 code, so the
    phase decides between them; row or loop order never does.
    """
    types = _type_map(definition["work_class"])
    steps = _step_map(definition["work_class"])
    envelope = definition["envelope"]
    faults = set()
    for condition in envelope["conditions"] + envelope["gate"]["criteria"]:
        step = steps.get(condition["step"])
        if step is None:
            faults.add("REFERENCE_INVALID")
            continue
        _predicate_type_faults(condition["predicate"], _field_map(step), types, faults)
    if request is not None:
        fields = {field["name"]: {"type_ref": field["value"]["type_ref"], "value": field["value"]} for field in request["proposal"]["fields"]}
        for condition in envelope["conditions"] + envelope["gate"]["criteria"]:
            if condition["step"] == request["proposal"]["step"]:
                _predicate_type_faults(condition["predicate"], fields, types, faults)
    for code in ("TYPE_INVALID", "REFERENCE_INVALID"):
        if code in faults:
            return code
    return None


def _limit_admission(definition):
    types = _type_map(definition["work_class"])
    steps = _step_map(definition["work_class"])
    envelope = definition["envelope"]
    try:
        permitted_steps = {row["step"] for row in envelope["operations"]}
        for step_id in permitted_steps:
            step = steps[step_id]
            bounds = [bound for bound in envelope["limits"]["per_action"] if bound["step"] == step["id"]]
            mode = step["quantity_mode"]
            if mode == "NONE" and (bounds or envelope["limits"]["shared_budgets"]):
                return "BINDING_MISMATCH"
            if mode == "BOUNDED" and not bounds and not envelope["limits"]["shared_budgets"]:
                return "BINDING_MISMATCH"
            for bound in bounds:
                field = next(field for field in step["fields"] if field["name"] == bound["field"])
                declared, bound_type = types[field["type_ref"]], types[bound["bound"]["type_ref"]]
                if field["type_ref"] != bound["bound"]["type_ref"] or declared["kind"] not in ("INTEGER", "DECIMAL") or not declared["nonnegative"] or declared["unit"] != bound_type["unit"]:
                    return "TYPE_INVALID"
        return None
    except (KeyError, StopIteration):
        return "REFERENCE_INVALID"


def _finite_limits(value, types=None):
    """Apply the WCS2-004 finite collection, expression, and number bounds."""
    types = types or {}
    arrays = 0
    maximum_depth = 0
    predicate_nodes = 0
    predicate_depth = 0

    def walk(node, depth=0):
        nonlocal arrays, maximum_depth
        maximum_depth = max(maximum_depth, depth)
        if isinstance(node, list):
            arrays += 1
            if len(node) > 1024:
                return False
            return all(walk(child, depth + 1) for child in node)
        if isinstance(node, dict):
            return all(walk(child, depth + 1) for child in node.values())
        return True

    if not walk(value) or arrays > 1024 or maximum_depth > 64:
        return False
    if isinstance(value, dict) and "work_class" in value:
        work_class = value["work_class"]
        if len(work_class["types"]) > 64 or len(work_class["steps"]) > 1024:
            return False
        envelope = value["envelope"]
        if len(envelope["operations"]) > 256:
            return False
        predicates = envelope["conditions"] + envelope["gate"]["criteria"]

        def count_predicate(predicate, depth=1):
            nonlocal predicate_nodes, predicate_depth
            predicate_nodes += 1
            predicate_depth = max(predicate_depth, depth)
            if predicate["kind"] in ("ALL", "ANY"):
                return all(count_predicate(child, depth + 1) for child in predicate["operands"])
            if predicate["kind"] == "NOT":
                return count_predicate(predicate["operand"], depth + 1)
            return True

        if not all(count_predicate(item["predicate"]) for item in predicates) or predicate_nodes > 4096 or predicate_depth > 64:
            return False
    for node in _walk_nodes(value):
        if isinstance(node, dict) and "type_ref" in node and "value" in node and node["type_ref"] in types:
            declaration = types[node["type_ref"]]
            if declaration["kind"] in ("INTEGER", "DECIMAL") and len(node["value"].replace(".", "")) > 128:
                return False
        if isinstance(node, dict) and "max_age_seconds" in node and len(node["max_age_seconds"]) > 128:
            return False
    return True


def _walk_nodes(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_nodes(child)


def _definition_static(definition):
    if not _valid(definition, "definition"):
        return "SCHEMA_INVALID"
    if definition["schema"] != AUTH_PREFIX + "authority-definition":
        return "VERSION_UNSUPPORTED"
    source, work_class, envelope = definition["source"], definition["work_class"], definition["envelope"]
    from . import completion
    from .common import Refusal
    try:
        for step in work_class["steps"]:
            completion.validate_step(step, _type_map(work_class))
    except Refusal as error:
        return "INPUT_INVALID" if error.code == "DEFINITION_INVALID" else error.code
    types, steps = _type_map(work_class), _step_map(work_class)
    type_error = any((item["kind"] in ("IDENTITY", "STRING", "BOOLEAN", "INSTANT") and item["nonnegative"]) or (item["kind"] != "DECIMAL" and item["unit"] is not None) for item in types.values())
    predicate_error = _predicate_admission(definition)
    if type_error or predicate_error == "TYPE_INVALID":
        return "TYPE_INVALID"
    if not _date_admission(definition):
        return "INPUT_INVALID"
    if not _definition_inventory(definition):
        return "INPUT_INVALID"
    from .source_observations import declaration_admission
    source_error = declaration_admission(work_class, envelope)
    from . import assessments, flow
    assessment_errors = assessments.declaration_errors(work_class, envelope, source)
    assessment_errors.update(flow.declaration_errors(work_class, envelope))
    static_error = next((code for code in ("TYPE_INVALID", "INPUT_INVALID", "DEPENDENCY_MISMATCH", "UNSUPPORTED_RELATION", "REFERENCE_INVALID", "LIMIT_EXCEEDED", "BINDING_MISMATCH") if code == source_error or code in assessment_errors), None)
    if static_error:
        return static_error
    from .holdings import declaration_error
    holdings_error = declaration_error(work_class, envelope)
    if holdings_error:
        return holdings_error
    if not _finite_limits(definition, types):
        return "LIMIT_EXCEEDED"
    if envelope["source_digest"] != digest("authority-source", source) or envelope["work_class_digest"] != digest("authority-work-class", work_class):
        return "DEPENDENCY_MISMATCH"
    if any(item not in {obligation["id"] for obligation in source["obligations"]} for item in envelope["source_obligations"]):
        return "REFERENCE_INVALID"
    for requirement in envelope.get("source_observation_requirements", []):
        if requirement["step"] not in steps:
            return "REFERENCE_INVALID"
        if any(field["type_ref"] not in types for field in requirement["fields"]):
            return "REFERENCE_INVALID"
    if any(row["step"] not in steps for row in envelope["operations"] + envelope["conditions"] + envelope["limits"]["per_action"] + envelope["gate"]["criteria"]):
        return "REFERENCE_INVALID"
    for row in envelope["operations"]:
        step = steps[row["step"]]
        if (row["operation"], row["interface"]) != (step["operation"], step["interface"]):
            return "REFERENCE_INVALID"
    for step in work_class["steps"]:
        fields = _field_map(step)
        if any(field["type_ref"] not in types for field in step["fields"]):
            return "REFERENCE_INVALID"
        if any(name not in fields for name in step["scope_fields"]["subjects"] + step["scope_fields"]["resources"]):
            return "REFERENCE_INVALID"
        if any(types[fields[name]["type_ref"]]["kind"] not in ("IDENTITY", "STRING") for name in step["scope_fields"]["subjects"] + step["scope_fields"]["resources"]):
            return "TYPE_INVALID"
        for key in step.get("exclusive_keys", []):
            for projection in key["projection"]:
                if "value" in projection:
                    if projection["value"]["type_ref"] not in types: return "REFERENCE_INVALID"
                    if not _typed_value_valid(projection["value"], types): return "TYPE_INVALID"
                    continue
                field = fields.get(projection["field"])
                if field is None or field["type_ref"] != projection["type_ref"] or projection["type_ref"] not in types:
                    return "REFERENCE_INVALID"
    bindings = {item["id"]: item for item in envelope["bindings"]}
    if bindings and len(envelope["operations"]) != 1:
        return "UNSUPPORTED_RELATION"
    for binding in envelope["bindings"]:
        step, field = steps.get(binding["step"]), None
        if step:
            field = _field_map(step).get(binding["field"])
        if not step or not field or any(row["step"] != binding["step"] for row in envelope["operations"]):
            return "REFERENCE_INVALID"
        if binding["type_ref"] != field["type_ref"] or types[binding["type_ref"]]["kind"] not in ("IDENTITY", "STRING"):
            return "TYPE_INVALID"
    if any(selector["kind"] == "BINDING" and selector["binding"] not in bindings for selector in envelope["scope"]["subjects"] + envelope["scope"]["resources"]):
        return "REFERENCE_INVALID"
    if predicate_error:
        return predicate_error
    limit_error = _limit_admission(definition)
    if limit_error:
        return limit_error
    has_exclusive_keys = any(step.get("exclusive_keys") for step in work_class["steps"])
    expected_mechanisms = ["ATOMIC_RESERVATION_TRANSITION", "AUTHORITY_BEFORE_RESERVATION"] if has_exclusive_keys else ["ATOMIC_SHARED_RESERVATION", "AUTHORITY_BEFORE_RESERVATION"] if envelope["limits"]["shared_budgets"] else ["AUTHORITY_BEFORE_RESERVATION"]
    if envelope["enforcement"]["mechanisms"] != expected_mechanisms:
        return "BINDING_MISMATCH"
    if envelope["limitations"]:
        return "UNSUPPORTED_RELATION"
    gate = envelope["gate"]
    required = "DECIDE" if gate["materiality"] == "HIGH" or gate["reversibility"] in ("LOW", "NONE") else "VERIFY" if gate["materiality"] == "MEDIUM" or gate["reversibility"] == "MEDIUM" else "NONE"
    if ["NONE", "VERIFY", "DECIDE"].index(gate["kind"]) < ["NONE", "VERIFY", "DECIDE"].index(required):
        return "BINDING_MISMATCH"
    if gate["kind"] == "NONE" and (gate["role"] is not None or gate["criteria"]):
        return "BINDING_MISMATCH"
    if gate["kind"] != "NONE" and (gate["role"] is None or not gate["criteria"]):
        return "BINDING_MISMATCH"
    if gate["kind"] != "NONE" and any(not any(criteria["step"] == row["step"] for criteria in gate["criteria"]) for row in envelope["operations"]):
        return "BINDING_MISMATCH"
    return None


def validate_definition(definition):
    error = _definition_static(definition)
    if error:
        return _refusal(error)
    return {"status": "ACCEPTED", "schema": definition["schema"], "digest": digest("authority-definition", definition), "source": definition["source"], "work_class": definition["work_class"], "envelope": definition["envelope"]}


def _decode_returns(request):
    """Admit every embedded act and accumulate independent phase-one failures."""
    decoded = {}
    errors = []

    def unique_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_number(_value):
        raise ValueError("JSON number token")

    for returned in request["returns"]:
        try:
            raw = base64.b64decode(returned["act_bytes_base64"], validate=True)
            if base64.b64encode(raw).decode("ascii") != returned["act_bytes_base64"]:
                errors.append("ARTIFACT_ENCODING_INVALID")
                continue
        except (ValueError, TypeError):
            errors.append("ARTIFACT_ENCODING_INVALID")
            continue

        try:
            text = raw.decode("utf-8")
            decoded_json = json.loads(
                text,
                object_pairs_hook=unique_pairs,
                parse_int=reject_number,
                parse_float=reject_number,
                parse_constant=reject_number,
            )
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            errors.append("ARTIFACT_ENCODING_INVALID")
            continue

        if not _valid(decoded_json, "act"):
            errors.append("SCHEMA_INVALID")
        if raw != canonical(decoded_json):
            errors.append("ARTIFACT_NONCANONICAL")
        decoded[returned["id"]] = (decoded_json, raw)
    return decoded, errors


def _phase_one(request, schema_name="input"):
    if not _valid(request, schema_name):
        return "SCHEMA_INVALID", None
    errors = []
    if not _date_admission({key: value for key, value in request.items() if key not in {"holdings_bases", "flow_bases"}}):
        errors.append("INPUT_INVALID")
    if not _inventory_admission(request):
        errors.append("INPUT_INVALID")
    decoded, return_errors = _decode_returns(request)
    errors.extend(return_errors)
    types = _type_map(request["work_class"])
    if any((item["kind"] in ("IDENTITY", "STRING", "BOOLEAN", "INSTANT") and item["nonnegative"]) or (item["kind"] != "DECIMAL" and item["unit"] is not None) for item in types.values()):
        errors.append("TYPE_INVALID")
    if any(not _all_typed_values(value, types) for value in (request["work_class"], request["proposal"], request["envelope"], request["observations"])):
        errors.append("TYPE_INVALID")
    predicate_error = _predicate_admission({"work_class": request["work_class"], "envelope": request["envelope"]})
    if predicate_error == "TYPE_INVALID":
        errors.append("TYPE_INVALID")
    from .source_observations import declaration_admission
    source_error = declaration_admission(request["work_class"], request["envelope"])
    if source_error in {"TYPE_INVALID", "INPUT_INVALID"}:
        errors.append(source_error)
    from .holdings import declaration_error
    if declaration_error(request["work_class"], request["envelope"]) == "INPUT_INVALID":
        errors.append("INPUT_INVALID")
    from . import assessments, flow
    errors.extend(assessments.phase_one(request))
    errors.extend(flow.phase_one(request))
    if errors:
        precedence = ("SCHEMA_INVALID", "ARTIFACT_ENCODING_INVALID", "ARTIFACT_NONCANONICAL", "TYPE_INVALID", "INPUT_INVALID")
        return next(code for code in precedence if code in errors), None
    return None, decoded


def _phase_two(request, source_digest, work_class_digest, envelope_digest):
    source, work_class, envelope = request["source"], request["work_class"], request["envelope"]
    root = request["host_selection"]["root"]
    from .common import PIN
    if any(basis["configuration"]["specification_pin"] != PIN or basis["state"]["specification_pin"] != PIN for basis in request.get("holdings_bases", [])):
        return "VERSION_UNSUPPORTED", None
    if envelope["source_digest"] != source_digest or envelope["work_class_digest"] != work_class_digest or request["proposal"]["work_class_digest"] != work_class_digest or request["proposal"]["work_class"] != work_class["id"]:
        return "DEPENDENCY_MISMATCH", None
    if any(row["query_digest"] != digest("authority-query", row["query"]) for row in request["observations"]):
        return "DEPENDENCY_MISMATCH", None
    root_digest = digest("authority-root", root)
    if root["source_digest"] != source_digest or root["work_class_digest"] != work_class_digest or root["envelope_digest"] != envelope_digest or root["principal"] != envelope["principal"]:
        return "DEPENDENCY_MISMATCH", None
    definition_error = _definition_static({"schema": AUTH_PREFIX + "authority-definition", "source": source, "work_class": work_class, "envelope": envelope})
    if definition_error in {"INPUT_INVALID", "TYPE_INVALID"}:
        return definition_error, None
    errors = [definition_error] if definition_error in {"DEPENDENCY_MISMATCH", "UNSUPPORTED_RELATION", "REFERENCE_INVALID", "LIMIT_EXCEEDED"} else []
    if not _finite_limits({key: value for key, value in request.items() if key not in {"decision_bases", "holdings_bases", "flow_bases"}}, _type_map(work_class)):
        errors.append("LIMIT_EXCEEDED")
    if ("holdings_bases" in request or "holdings_requirements" in envelope) and len(canonical(request)) > 1048576:
        errors.append("LIMIT_EXCEEDED")
    from . import holdings
    try:
        holdings.phase_two(request)
    except holdings.Refusal as error:
        errors.append(error.code)
    from . import assessments, flow
    errors.extend(assessments.phase_two(request))
    errors.extend(flow.phase_two(request))
    type_ids = set(_type_map(work_class))
    for field in request["proposal"]["fields"]:
        if field["value"]["type_ref"] not in type_ids:
            errors.append("REFERENCE_INVALID")
    capacities, occupancies = _records(request["capacities"]), _records(request["occupancies"])
    if set(capacities) != set(root["capacity_ids"]) or set(occupancies) != set(root["occupancy_ids"]):
        missing = set(root["capacity_ids"]) - set(capacities) or set(root["occupancy_ids"]) - set(occupancies)
        errors.append("EVIDENCE_UNAVAILABLE" if missing else "DEPENDENCY_MISMATCH")
    all_records = request["occupancies"] + request["capacities"] + request["credentials"] + request["returns"]
    if any(row["provider"] not in root["providers"] for row in envelope.get("source_observation_requirements", [])):
        errors.append("DEPENDENCY_MISMATCH")
    if any(record["provider"] not in root["providers"] for record in all_records) or any(channel["provider"] not in root["providers"] for channel in root["channels"]):
        errors.append("DEPENDENCY_MISMATCH")
    if any(returned["channel"] not in {channel["id"] for channel in root["channels"]} for returned in request["returns"]):
        errors.append("DEPENDENCY_MISMATCH")
    if any(capacity["occupancy"] not in occupancies for capacity in capacities.values()):
        errors.append("DEPENDENCY_MISMATCH")
    if any(credential["occupancy"] not in occupancies for credential in request["credentials"]):
        errors.append("DEPENDENCY_MISMATCH")
    supplied = set()
    for kind, records in (("OCCUPANCY", request["occupancies"]), ("CAPACITY", request["capacities"]), ("CREDENTIAL", request["credentials"]), ("RETURN", request["returns"])):
        for record in records:
            supplied.add((kind, digest("authority-" + kind.lower(), record), record.get("provider"), record.get("channel")))
    authenticated = {(record["kind"], record["record_digest"], record["provider"], record["channel"]) for record in request["host_selection"]["authenticated_records"]}
    if authenticated - supplied:
        errors.append("DEPENDENCY_MISMATCH")
    if supplied - authenticated:
        errors.append("EVIDENCE_UNAVAILABLE")
    if envelope["limitations"] or root["limitations"]:
        errors.append("UNSUPPORTED_RELATION")
    if errors:
        return next(code for code in ("VERSION_UNSUPPORTED", "DEPENDENCY_MISMATCH", "DEFINITION_INVALID", "DIGEST_MISMATCH", "STATE_INVALID", "CLOCK_INVALID", "EVIDENCE_UNAVAILABLE", "UNSUPPORTED_RELATION", "REFERENCE_INVALID", "LIMIT_EXCEEDED") if code in errors), None
    return None, {"root": root, "root_digest": root_digest, "capacities": capacities, "occupancies": occupancies, "credentials": request["credentials"]}


def _phase_three(request, work_class, envelope, occupancies=None):
    from .holdings import phase_three
    holdings_error = phase_three(request)
    if holdings_error:
        return holdings_error, None
    proposal = request["proposal"]
    steps = _step_map(work_class)
    step = steps.get(proposal["step"])
    if not step or (proposal["operation"], proposal["interface"]) != (step["operation"], step["interface"]):
        return "BINDING_MISMATCH", None
    if (proposal["step"], proposal["operation"], proposal["interface"]) not in {(row["step"], row["operation"], row["interface"]) for row in envelope["operations"]}:
        return "BINDING_MISMATCH", None
    declarations, fields = _field_map(step), {field["name"]: field for field in proposal["fields"]}
    if set(fields) != set(declarations) or any(fields[name]["value"]["type_ref"] != declaration["type_ref"] for name, declaration in declarations.items()):
        return "BINDING_MISMATCH", None
    executor = proposal["executor"]
    occupancy = (occupancies or {}).get(executor["occupancy"])
    if (not occupancy or executor["actor"] != occupancy["actor"] or executor["role"] != occupancy["role"] or
            executor["principal"] != occupancy["principal"] or executor["role"] != step["executor_role"] or
            executor["principal"] != envelope["principal"]):
        return "BINDING_MISMATCH", None
    actual = {kind: sorted({fields[name]["value"]["value"] for name in step["scope_fields"][kind]}, key=_utf8) for kind in ("subjects", "resources")}
    bindings = {item["id"]: item for item in envelope["bindings"]}
    scope = {}
    for kind in ("subjects", "resources"):
        resolved = []
        for selector in envelope["scope"][kind]:
            resolved.append(selector["value"] if selector["kind"] == "CONSTANT" else fields[bindings[selector["binding"]]["field"]]["value"]["value"])
        scope[kind] = sorted(set(resolved), key=_utf8)
        if not set(actual[kind]).issubset(scope[kind]):
            return "BINDING_MISMATCH", None
    gate = envelope["gate"]
    required = "DECIDE" if gate["materiality"] == "HIGH" or gate["reversibility"] in ("LOW", "NONE") else "VERIFY" if gate["materiality"] == "MEDIUM" or gate["reversibility"] == "MEDIUM" else "NONE"
    if ["NONE", "VERIFY", "DECIDE"].index(gate["kind"]) < ["NONE", "VERIFY", "DECIDE"].index(required):
        return "BINDING_MISMATCH", None
    predicate_error = _predicate_admission({"work_class": work_class, "envelope": envelope}, request)
    if predicate_error:
        return predicate_error, None
    limit_error = _limit_admission({"work_class": work_class, "envelope": envelope})
    if limit_error:
        return limit_error, None
    from . import assessments, flow
    assessment_error = assessments.phase_three(request)
    if assessment_error:
        return assessment_error, None
    flow_error = flow.phase_three(request)
    if flow_error:
        return flow_error, None
    return None, {"step": step, "fields": fields, "scope": scope, "actual_scope": actual}


def _select_credentials(request, dependencies, step):
    proposal = request["proposal"]
    required = step["required_credentials"]
    matching = [credential for credential in dependencies["credentials"] if (credential["step"], credential["operation"], credential["interface"]) == (proposal["step"], proposal["operation"], proposal["interface"])]
    if len(matching) != len(dependencies["credentials"]):
        return "DEPENDENCY_MISMATCH"
    if any(credential["actor"] != proposal["executor"]["actor"] for credential in matching):
        return "DEPENDENCY_MISMATCH"
    if {credential["kind"] for credential in matching} != set(required) or len(matching) != len(required):
        return "EVIDENCE_UNAVAILABLE"
    if any(credential["occupancy"] != proposal["executor"]["occupancy"] for credential in matching):
        return "DEPENDENCY_MISMATCH"
    dependencies["credentials"] = matching
    return None


def _parse_clock(request, envelope):
    clock = request["clock"]
    if clock["source"] != envelope["clock_source"] or clock["status"] != "AVAILABLE":
        return None
    try:
        return _instant(clock["instant"])
    except (TypeError, ValueError):
        return None


def evaluate_authority(request, selected_pin):
    from .flow import evaluation_scope
    with evaluation_scope():
        return _evaluate_authority(request, selected_pin)


def _evaluate_authority(request, selected_pin):
    envelope = request.get("envelope") if isinstance(request, dict) else None
    if isinstance(envelope, dict) and ("decision_bases" in request or "decision_requirements" in envelope or "assessment_bases" in request or "assessment_requirements" in envelope or isinstance(envelope.get("gate"), dict) and "decision_requirement" in envelope["gate"]):
        from .human_decisions import evaluate
        return evaluate(request, selected_pin)
    phase_error, _ = _phase_one(request)
    if phase_error:
        return _refusal(phase_error)
    if request["schema"] != AUTH_PREFIX + "authority-input":
        return _refusal("VERSION_UNSUPPORTED")
    if request["specification_pin"] != selected_pin:
        return _refusal("DEPENDENCY_MISMATCH")
    source, work_class, envelope, proposal = request["source"], request["work_class"], request["envelope"], request["proposal"]
    source_digest, work_class_digest = digest("authority-source", source), digest("authority-work-class", work_class)
    envelope_digest, proposal_digest = digest("authority-envelope", envelope), digest("authority-proposal", proposal)
    operation_digest = digest("authority-operation", {"envelope_digest": envelope_digest, "work_class_digest": work_class_digest, "proposal_digest": proposal_digest})
    phase_error, dependencies = _phase_two(request, source_digest, work_class_digest, envelope_digest)
    if phase_error:
        return _refusal(phase_error)
    phase_error, application = _phase_three(request, work_class, envelope, dependencies["occupancies"])
    if phase_error:
        return _refusal(phase_error)
    phase_error = _select_credentials(request, dependencies, application["step"])
    if phase_error:
        return _refusal(phase_error)
    try:
        from .authority_acts import evaluate_acts
    except ImportError:
        from authority_acts import evaluate_acts
    acts_phase = evaluate_acts(request, envelope, dependencies["root"], proposal, application["step"], _parse_clock(request, envelope), operation_digest)
    if acts_phase.get("status") == "REFUSED":
        return acts_phase
    now = _parse_clock(request, envelope)
    if now is None:
        return _refusal("AUTHORITY_NOT_ESTABLISHED", ["CLOCK_UNAVAILABLE"])
    return _policy_result(request, selected_pin, dependencies, application, acts_phase)


def _policy_result(request, selected_pin, dependencies, application, acts_phase, *, historical_signer=None, decision_contexts=None):
    source, work_class, envelope, proposal = (request[key] for key in ("source", "work_class", "envelope", "proposal"))
    source_digest, work_class_digest = digest("authority-source", source), digest("authority-work-class", work_class)
    envelope_digest, proposal_digest = digest("authority-envelope", envelope), digest("authority-proposal", proposal)
    operation_digest = digest("authority-operation", {"envelope_digest": envelope_digest, "work_class_digest": work_class_digest, "proposal_digest": proposal_digest})
    from .authority_observations import observe_revocation
    from .source_observations import observe_source
    observation_phase = observe_revocation(request, acts_phase["selected"], dependencies["root"], dependencies["capacities"], dependencies["credentials"], envelope, operation_digest, historical_signer=historical_signer)
    source_phase = observe_source(request, envelope, acts_phase["selected"], decision_contexts=decision_contexts)
    refusals = [row for row in (observation_phase, source_phase) if row.get("status") == "REFUSED"]
    if refusals:
        return next((row for row in refusals if row["code"] == "DEPENDENCY_MISMATCH"), refusals[0])
    reasons = set(observation_phase["reasons"]) | set(source_phase["reasons"])
    failed = list(observation_phase["failed"]) + list(source_phase["failed"])
    stamp, checks = request["clock"]["instant"], []
    from .holdings import policy
    holdings_phase = policy(request, acts_phase["selected"], decision_contexts)
    reasons.update(holdings_phase["reasons"])
    failed.extend(holdings_phase["failed"])
    checks.extend(holdings_phase["checks"])
    from . import assessments
    assessment_phase = assessments.policy(request, source_phase.get("assessment_values", {}))
    reasons.update(assessment_phase["reasons"])
    failed.extend(assessment_phase["failed"])
    checks.extend(assessment_phase["checks"])
    from . import flow
    flow_phase = flow.policy(request, source_phase.get("flow_values", {}), decision_contexts)
    reasons.update(flow_phase["reasons"])
    failed.extend(flow_phase["failed"])
    checks.extend(flow_phase["checks"])
    fields, types = application["fields"], _type_map(work_class)
    for condition in envelope["conditions"]:
        if condition["step"] == proposal["step"] and not _pred(condition["predicate"], fields, types):
            reasons.add("CONDITION_VIOLATED")
            failed.append({"purpose": "CONDITION", "subject_digest": operation_digest, "requirement_ref": condition["id"], "at": stamp, "reason": "CONDITION_VIOLATED"})
    for limit in envelope["limits"]["per_action"]:
        if limit["step"] == proposal["step"]:
            actual = Decimal(fields[limit["field"]]["value"]["value"])
            bound = Decimal(limit["bound"]["value"])
            if not (actual < bound if limit["operator"] == "LT" else actual <= bound):
                reasons.add("PER_ACTION_LIMIT_VIOLATED")
                failed.append({"purpose": "PER_ACTION_LIMIT", "subject_digest": operation_digest, "requirement_ref": limit["id"], "at": stamp, "reason": "PER_ACTION_LIMIT_VIOLATED"})
    criterion_map = {criteria["id"]: criteria for criteria in envelope["gate"]["criteria"]}
    criterion_acts = list(acts_phase["selected"])
    selected_decision = envelope["gate"].get("decision_requirement")
    if selected_decision is not None:
        criterion_acts.append(decision_contexts[selected_decision]["decision"])
    for act in criterion_acts:
        if act["kind"] in ("VERIFY", "INSTANCE_DECISION"):
            for criterion_id in act["criteria"]:
                if not _pred(criterion_map[criterion_id]["predicate"], fields, types):
                    reasons.add("GATE_CRITERION_VIOLATED")
                    failed.append({"purpose": "GATE_CRITERION", "subject_digest": digest("authority-act", act), "requirement_ref": criterion_id, "at": act["occurred_at"], "reason": "GATE_CRITERION_VIOLATED"})
    if reasons:
        return _refusal("AUTHORITY_NOT_ESTABLISHED", reasons, failed)
    fixed = (("SOURCE_BINDING", envelope_digest, source["id"]), ("ROOT_BINDING", envelope_digest, dependencies["root"]["id"]), ("INPUT_SUPPORT", operation_digest, proposal["step"]), ("BINDING", operation_digest, envelope["scope"]["id"]), ("GATE_FLOOR", envelope_digest, envelope["id"]), ("ENVELOPE_VALIDITY", envelope_digest, envelope["id"]), ("EXECUTOR_OCCUPANCY", operation_digest, proposal["executor"]["occupancy"]))
    checks.extend({"purpose": purpose, "subject_digest": subject, "requirement_ref": reference, "at": stamp} for purpose, subject, reference in fixed if not (purpose == "EXECUTOR_OCCUPANCY" and historical_signer is not None))
    for act in acts_phase["selected"]:
        act_digest = digest("authority-act", act)
        returned = acts_phase["returns"][act_digest]
        checks.extend({"purpose": purpose, "subject_digest": act_digest, "requirement_ref": reference, "at": act["occurred_at"] if purpose in ("ACT_CAPACITY", "ACT_OCCUPANCY") else stamp} for purpose, reference in (("ACT_CAPACITY", act["capacity"]), ("ACT_OCCUPANCY", act["occupancy"]), ("ACT_RELIANCE", act["capacity"]), ("RETURN", returned["id"])))
        if act["kind"] == "ORGANISATIONAL_ATTESTATION":
            checks.append({"purpose": "SEPARATION", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": stamp})
        if act["kind"] in ("VERIFY", "INSTANCE_DECISION"):
            checks.extend({"purpose": "GATE_CRITERION", "subject_digest": act_digest, "requirement_ref": criterion, "at": act["occurred_at"]} for criterion in act["criteria"])
    checks.extend({"purpose": "CONDITION", "subject_digest": operation_digest, "requirement_ref": condition["id"], "at": stamp} for condition in envelope["conditions"] if condition["step"] == proposal["step"])
    checks.extend({"purpose": "PER_ACTION_LIMIT", "subject_digest": operation_digest, "requirement_ref": limit["id"], "at": stamp} for limit in envelope["limits"]["per_action"] if limit["step"] == proposal["step"])
    checks.extend({"purpose": "REVOCATION", "subject_digest": query["subject_digest"], "requirement_ref": digest("authority-query", query), "at": query["at"]} for query in observation_phase["queries"])
    checks.extend(source_phase["checks"])
    if selected_decision is not None:
        act = decision_contexts[selected_decision]["decision"]
        checks.extend({"purpose": "GATE_CRITERION", "subject_digest": digest("authority-act", act), "requirement_ref": criterion, "at": act["occurred_at"]} for criterion in act["criteria"])
    checks.extend({"purpose": "CREDENTIAL", "subject_digest": operation_digest, "requirement_ref": credential["id"], "at": stamp} for credential in dependencies["credentials"])
    checks = sorted({canonical(check): check for check in checks}.values(), key=canonical)
    evidence = {key: request[key] for key in ("host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock")}
    if "evaluation_point" in request:
        evidence["evaluation_point"] = request["evaluation_point"]
    if "decision_bases" in request:
        evidence["decision_bases"] = request["decision_bases"]
    if "holdings_bases" in request:
        evidence["holdings_bases"] = request["holdings_bases"]
    if "assessment_bases" in request:
        evidence["assessment_bases"] = request["assessment_bases"]
    if "flow_bases" in request:
        evidence["flow_bases"] = request["flow_bases"]
    result = {"schema": AUTH_PREFIX + "authority-result", "specification_pin": selected_pin, "status": "READY_FOR_RESERVATION", "source_digest": source_digest, "work_class_digest": work_class_digest, "envelope_digest": envelope_digest, "proposal_digest": proposal_digest, "operation_digest": operation_digest, "scope": application["scope"], "actual_scope": application["actual_scope"], "act_digests": sorted(digest("authority-act", act) for act in acts_phase["selected"]), "checks": checks, "required_budgets": envelope["limits"]["shared_budgets"], "evidence_digest": digest("authority-evidence", evidence)}
    exclusive_keys = application["step"].get("exclusive_keys", [])
    if exclusive_keys:
        result["required_exclusive_keys"] = [{"id": key["id"], "slot": key["slot"], "namespace": key["namespace"], "key": [row["value"] if "value" in row else fields[row["field"]]["value"] for row in key["projection"]], "retention": key["retention"]} for key in exclusive_keys]
    return result
