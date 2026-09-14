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
AGG_URI = "https://schemas.seampoint.com/work-class/1.0.0-draft.2/aggregate.schema.json"
REGISTRY = {SCHEMA["$id"]: SCHEMA, AGG_URI: json.loads((ROOT / "input/aggregate.schema.json").read_text())}
RESOLVER = RefResolver(SCHEMA["$id"], SCHEMA, store=REGISTRY)
AUTH_PREFIX = "seampoint.work-class/1.0.0-draft.2/"
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


def _operand_type(operand, fields, types):
    if operand["kind"] == "FIELD":
        declaration = fields.get(operand["name"])
        if declaration is None:
            raise LookupError("field")
        return declaration["type_ref"]
    type_ref = operand["value"]["type_ref"]
    if type_ref not in types:
        raise LookupError("type")
    if not _typed_value_valid(operand["value"], types):
        raise ValueError("literal")
    return type_ref


def _validate_predicate_types(predicate, fields, types):
    """Validate every predicate branch and nominal operand compatibility."""
    kind = predicate["kind"]
    if kind == "BOOLEAN":
        return "BOOLEAN"
    if kind in ("EQUAL", "COMPARE"):
        left = _operand_type(predicate["left"], fields, types)
        right = _operand_type(predicate["right"], fields, types)
        if left != right:
            raise ValueError("nominal type")
        if kind == "COMPARE" and types[left]["kind"] not in ("INTEGER", "DECIMAL"):
            raise ValueError("numeric comparison")
        return "BOOLEAN"
    if kind == "MEMBER":
        value_type = _operand_type(predicate["value"], fields, types)
        for member in predicate["members"]:
            if member["type_ref"] != value_type or not _typed_value_valid(member, types):
                raise ValueError("member type")
        return "BOOLEAN"
    if kind in ("ALL", "ANY"):
        for child in predicate["operands"]:
            if _validate_predicate_types(child, fields, types) != "BOOLEAN":
                raise ValueError("predicate")
        return "BOOLEAN"
    if kind == "NOT":
        if _validate_predicate_types(predicate["operand"], fields, types) != "BOOLEAN":
            raise ValueError("predicate")
        return "BOOLEAN"
    raise ValueError("predicate")


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
                if key in {"valid_from", "valid_until", "occurred_at", "returned_at", "at", "as_of", "instant"} and child is not None:
                    try:
                        _instant(child)
                    except (TypeError, ValueError):
                        invalid = True
                walk(child)
            if node.get("status") == "AVAILABLE" and isinstance(node.get("query"), dict) and node.get("as_of") is not None:
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
        _ordered_unique([criterion for act in request["acts"] for criterion in act["criteria"]], _utf8),
    ])
    for step in request["work_class"]["steps"]:
        checks.extend([_ordered_unique([field["name"] for field in step["fields"]], _utf8), _ordered_unique(step["scope_fields"]["subjects"], _utf8), _ordered_unique(step["scope_fields"]["resources"], _utf8), _ordered_unique(step["required_credentials"], _utf8)])
    envelope = request["envelope"]
    checks.extend([
        _ordered_unique([item["step"] for item in envelope["operations"]], _utf8),
        _ordered_unique([canonical(item) for item in envelope["scope"]["subjects"]]), _ordered_unique([canonical(item) for item in envelope["scope"]["resources"]]),
        _ordered_unique(envelope["limits"]["shared_budgets"], _utf8), _ordered_unique(envelope["enforcement"]["mechanisms"], _utf8),
        _ordered_unique(envelope["gate"]["criteria"], lambda item: _utf8(item["id"])),
        _ordered_unique(request["host_selection"]["root"]["capacity_ids"], _utf8), _ordered_unique(request["host_selection"]["root"]["occupancy_ids"], _utf8),
        _ordered_unique(request["host_selection"]["root"]["providers"], _utf8), _ordered_unique(request["proposal"]["fields"], lambda item: _utf8(item["name"])),
        _ordered_unique(request["host_selection"]["root"]["limitations"], _utf8), _ordered_unique(envelope["limitations"], _utf8),
    ])
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
    ]
    for step in work_class["steps"]:
        checks.extend([
            _ordered_unique([field["name"] for field in step["fields"]], _utf8),
            _ordered_unique(step["scope_fields"]["subjects"], _utf8),
            _ordered_unique(step["scope_fields"]["resources"], _utf8),
            _ordered_unique(step["required_credentials"], _utf8),
        ])
    return all(checks)


def _predicate_admission(definition, request=None):
    types = _type_map(definition["work_class"])
    steps = _step_map(definition["work_class"])
    envelope = definition["envelope"]
    try:
        for condition in envelope["conditions"] + envelope["gate"]["criteria"]:
            _validate_predicate_types(condition["predicate"], _field_map(steps[condition["step"]]), types)
        if request is not None:
            fields = {field["name"]: {"type_ref": field["value"]["type_ref"], "value": field["value"]} for field in request["proposal"]["fields"]}
            for condition in envelope["conditions"] + envelope["gate"]["criteria"]:
                if condition["step"] == request["proposal"]["step"]:
                    _validate_predicate_types(condition["predicate"], fields, types)
    except LookupError:
        return "REFERENCE_INVALID"
    except (TypeError, ValueError, KeyError):
        return "TYPE_INVALID"
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
            if not bounds and not envelope["limits"]["shared_budgets"]:
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
    if not _date_admission(definition):
        return "INPUT_INVALID"
    if not _definition_inventory(definition):
        return "INPUT_INVALID"
    types, steps = _type_map(work_class), _step_map(work_class)
    if any((item["kind"] in ("IDENTITY", "STRING", "BOOLEAN") and item["nonnegative"]) or (item["kind"] != "DECIMAL" and item["unit"] is not None) for item in types.values()):
        return "TYPE_INVALID"
    if not _finite_limits(definition, types):
        return "LIMIT_EXCEEDED"
    if envelope["source_digest"] != digest("authority-source", source) or envelope["work_class_digest"] != digest("authority-work-class", work_class):
        return "DEPENDENCY_MISMATCH"
    if any(item not in {obligation["id"] for obligation in source["obligations"]} for item in envelope["source_obligations"]):
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
    bindings = {item["id"]: item for item in envelope["bindings"]}
    for binding in envelope["bindings"]:
        step, field = steps.get(binding["step"]), None
        if step:
            field = _field_map(step).get(binding["field"])
        if not step or not field:
            return "REFERENCE_INVALID"
        if binding["type_ref"] != field["type_ref"] or types[binding["type_ref"]]["kind"] not in ("IDENTITY", "STRING"):
            return "TYPE_INVALID"
    if any(selector["kind"] == "BINDING" and selector["binding"] not in bindings for selector in envelope["scope"]["subjects"] + envelope["scope"]["resources"]):
        return "REFERENCE_INVALID"
    predicate_error = _predicate_admission(definition)
    if predicate_error:
        return predicate_error
    limit_error = _limit_admission(definition)
    if limit_error:
        return limit_error
    expected_mechanisms = ["ATOMIC_SHARED_RESERVATION", "AUTHORITY_BEFORE_RESERVATION"] if envelope["limits"]["shared_budgets"] else ["AUTHORITY_BEFORE_RESERVATION"]
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


def _phase_one(request):
    if not _valid(request, "input"):
        return "SCHEMA_INVALID", None
    errors = []
    if not _date_admission(request):
        errors.append("INPUT_INVALID")
    if not _inventory_admission(request):
        errors.append("INPUT_INVALID")
    decoded, return_errors = _decode_returns(request)
    errors.extend(return_errors)
    types = _type_map(request["work_class"])
    if any(not _all_typed_values(value, types) for value in (request["work_class"], request["proposal"], request["envelope"])):
        errors.append("TYPE_INVALID")
    predicate_error = _predicate_admission({"work_class": request["work_class"], "envelope": request["envelope"]})
    if predicate_error == "TYPE_INVALID":
        errors.append("TYPE_INVALID")
    if errors:
        precedence = ("SCHEMA_INVALID", "ARTIFACT_ENCODING_INVALID", "ARTIFACT_NONCANONICAL", "TYPE_INVALID", "INPUT_INVALID")
        return next(code for code in precedence if code in errors), None
    return None, decoded


def _phase_two(request, source_digest, work_class_digest, envelope_digest):
    source, work_class, envelope = request["source"], request["work_class"], request["envelope"]
    root = request["host_selection"]["root"]
    if envelope["source_digest"] != source_digest or envelope["work_class_digest"] != work_class_digest or request["proposal"]["work_class_digest"] != work_class_digest or request["proposal"]["work_class"] != work_class["id"]:
        return "DEPENDENCY_MISMATCH", None
    root_digest = digest("authority-root", root)
    if root["source_digest"] != source_digest or root["work_class_digest"] != work_class_digest or root["envelope_digest"] != envelope_digest or root["principal"] != envelope["principal"]:
        return "DEPENDENCY_MISMATCH", None
    definition_error = _definition_static({"schema": AUTH_PREFIX + "authority-definition", "source": source, "work_class": work_class, "envelope": envelope})
    if definition_error in {"UNSUPPORTED_RELATION", "REFERENCE_INVALID", "LIMIT_EXCEEDED", "INPUT_INVALID", "TYPE_INVALID"}:
        return definition_error, None
    if not _finite_limits(request, _type_map(work_class)):
        return "LIMIT_EXCEEDED", None
    type_ids = set(_type_map(work_class))
    for field in request["proposal"]["fields"]:
        if field["value"]["type_ref"] not in type_ids:
            return "REFERENCE_INVALID", None
    capacities, occupancies = _records(request["capacities"]), _records(request["occupancies"])
    if set(capacities) != set(root["capacity_ids"]) or set(occupancies) != set(root["occupancy_ids"]):
        missing = set(root["capacity_ids"]) - set(capacities) or set(root["occupancy_ids"]) - set(occupancies)
        return ("EVIDENCE_UNAVAILABLE" if missing else "DEPENDENCY_MISMATCH"), None
    all_records = request["occupancies"] + request["capacities"] + request["credentials"]
    if any(record["provider"] not in root["providers"] for record in all_records) or any(channel["provider"] not in root["providers"] for channel in root["channels"]):
        return "DEPENDENCY_MISMATCH", None
    if any(capacity["occupancy"] not in occupancies for capacity in capacities.values()):
        return "DEPENDENCY_MISMATCH", None
    if any(credential["occupancy"] not in occupancies for credential in request["credentials"]):
        return "DEPENDENCY_MISMATCH", None
    supplied = set()
    for kind, records in (("OCCUPANCY", request["occupancies"]), ("CAPACITY", request["capacities"]), ("CREDENTIAL", request["credentials"]), ("RETURN", request["returns"])):
        for record in records:
            supplied.add((kind, digest("authority-" + kind.lower(), record), record.get("provider"), record.get("channel")))
    authenticated = {(record["kind"], record["record_digest"], record["provider"], record["channel"]) for record in request["host_selection"]["authenticated_records"]}
    if authenticated - supplied:
        return "DEPENDENCY_MISMATCH", None
    if supplied - authenticated:
        return "EVIDENCE_UNAVAILABLE", None
    if envelope["limitations"] or root["limitations"]:
        return "UNSUPPORTED_RELATION", None
    return None, {"root": root, "root_digest": root_digest, "capacities": capacities, "occupancies": occupancies, "credentials": request["credentials"]}


def _phase_three(request, work_class, envelope, occupancies=None):
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
    try:
        from .authority_observations import observe_revocation
    except ImportError:
        from authority_observations import observe_revocation
    observation_phase = observe_revocation(request, acts_phase["selected"], dependencies["root"], dependencies["capacities"], dependencies["credentials"], envelope, operation_digest)
    if observation_phase.get("status") == "REFUSED":
        return observation_phase
    now = _parse_clock(request, envelope)
    if now is None:
        return _refusal("AUTHORITY_NOT_ESTABLISHED", ["CLOCK_UNAVAILABLE"])
    reasons, failed = set(observation_phase["reasons"]), list(observation_phase["failed"])
    stamp, checks = request["clock"]["instant"], []
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
    for act in acts_phase["selected"]:
        if act["kind"] in ("VERIFY", "INSTANCE_DECISION"):
            for criterion_id in act["criteria"]:
                if not _pred(criterion_map[criterion_id]["predicate"], fields, types):
                    reasons.add("GATE_CRITERION_VIOLATED")
                    failed.append({"purpose": "GATE_CRITERION", "subject_digest": digest("authority-act", act), "requirement_ref": criterion_id, "at": act["occurred_at"], "reason": "GATE_CRITERION_VIOLATED"})
    if reasons:
        return _refusal("AUTHORITY_NOT_ESTABLISHED", reasons, failed)
    fixed = (("SOURCE_BINDING", envelope_digest, source["id"]), ("ROOT_BINDING", envelope_digest, dependencies["root"]["id"]), ("INPUT_SUPPORT", operation_digest, proposal["step"]), ("BINDING", operation_digest, envelope["scope"]["id"]), ("GATE_FLOOR", envelope_digest, envelope["id"]), ("ENVELOPE_VALIDITY", envelope_digest, envelope["id"]), ("EXECUTOR_OCCUPANCY", operation_digest, proposal["executor"]["occupancy"]))
    checks.extend({"purpose": purpose, "subject_digest": subject, "requirement_ref": reference, "at": stamp} for purpose, subject, reference in fixed)
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
    checks.extend({"purpose": "CREDENTIAL", "subject_digest": operation_digest, "requirement_ref": credential["id"], "at": stamp} for credential in dependencies["credentials"])
    checks = sorted({canonical(check): check for check in checks}.values(), key=canonical)
    evidence = {key: request[key] for key in ("host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock")}
    return {"schema": AUTH_PREFIX + "authority-result", "specification_pin": selected_pin, "status": "READY_FOR_RESERVATION", "source_digest": source_digest, "work_class_digest": work_class_digest, "envelope_digest": envelope_digest, "proposal_digest": proposal_digest, "operation_digest": operation_digest, "scope": application["scope"], "actual_scope": application["actual_scope"], "act_digests": sorted(digest("authority-act", act) for act in acts_phase["selected"]), "checks": checks, "required_budgets": envelope["limits"]["shared_budgets"], "evidence_digest": digest("authority-evidence", evidence)}
