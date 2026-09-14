"""Ordered semantic admission for aggregate definitions and inputs."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
import re

from .common import Refusal, canonical, utf8_sorted_unique


INTEGER = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")


def _fail(code):
    raise Refusal(code)


def _number(value, integer=False):
    pattern = INTEGER if integer else DECIMAL
    return isinstance(value, str) and pattern.fullmatch(value) is not None and value != "-0"


def _value(value, types, expected=None):
    if type(value) is not dict or set(value) != {"type_ref", "value"}:
        _fail("TYPE_INVALID")
    type_ref = value["type_ref"]
    if type_ref not in types or (expected is not None and type_ref != expected):
        _fail("TYPE_INVALID")
    declaration = types[type_ref]
    raw = value["value"]
    kind = declaration["kind"]
    valid = (
        (kind == "STRING" and isinstance(raw, str))
        or (kind == "IDENTITY" and isinstance(raw, str) and bool(raw))
        or (kind == "BOOLEAN" and type(raw) is bool)
        or (kind == "INTEGER" and _number(raw, integer=True))
        or (kind == "DECIMAL" and _number(raw))
    )
    if not valid or (kind in ("INTEGER", "DECIMAL") and declaration["nonnegative"] and raw.startswith("-")):
        _fail("TYPE_INVALID")
    return type_ref


def _predicate(predicate, types, fields=None):
    kind = predicate["kind"]
    if kind == "BOOLEAN":
        return
    if kind in ("ALL", "ANY"):
        for child in predicate["operands"]:
            _predicate(child, types, fields)
        return
    if kind == "NOT":
        _predicate(predicate["operand"], types, fields)
        return

    def operand(row):
        if row["kind"] == "LITERAL":
            return _value(row["value"], types)
        if fields is None:
            return None
        if row["name"] not in fields:
            _fail("INPUT_INVALID")
        return fields[row["name"]]["type_ref"]

    if kind == "MEMBER":
        selected = operand(predicate["value"])
        members = predicate["members"]
        member_bytes = [canonical(member) for member in members]
        if len(member_bytes) != len(set(member_bytes)) or member_bytes != sorted(member_bytes):
            _fail("TYPE_INVALID")
        member_types = [_value(member, types) for member in members]
        if len(set(member_types + ([selected] if selected is not None else []))) > 1:
            _fail("TYPE_INVALID")
        return
    left = operand(predicate["left"])
    right = operand(predicate["right"])
    if left is not None and right is not None and left != right:
        _fail("TYPE_INVALID")
    selected = left if left is not None else right
    if kind == "COMPARE" and selected is not None and types[selected]["kind"] not in ("INTEGER", "DECIMAL"):
        _fail("TYPE_INVALID")


def _predicate_size(predicate):
    kind = predicate["kind"]
    if kind in ("ALL", "ANY"):
        children = [_predicate_size(child) for child in predicate["operands"]]
    elif kind == "NOT":
        children = [_predicate_size(predicate["operand"])]
    else:
        children = []
    return 1 + sum(nodes for nodes, _ in children), 1 + max((depth for _, depth in children), default=0)


def _instant(value, precision):
    pattern = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
    if precision == "NANOSECOND":
        pattern = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{9})?Z$"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        _fail("INPUT_INVALID")
    try:
        dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail("INPUT_INVALID")


def definition(definition):
    types_list = definition["types"]
    if not utf8_sorted_unique([row["id"] for row in types_list]):
        _fail("REFERENCE_INVALID")
    aggregate = definition["aggregate"]
    mappings = aggregate["mappings"]
    if not utf8_sorted_unique([row["id"] for row in mappings]):
        _fail("REFERENCE_INVALID")
    if any(not utf8_sorted_unique(row["step_ids"]) for row in mappings):
        _fail("REFERENCE_INVALID")
    types = {row["id"]: row for row in types_list}
    references = aggregate["key_types"] + [aggregate["result_type"]]
    if aggregate["element_type"] is not None:
        references.append(aggregate["element_type"])
    if any(reference not in types for reference in references):
        _fail("REFERENCE_INVALID")

    for declaration in types_list:
        kind = declaration["kind"]
        if kind not in ("INTEGER", "DECIMAL") and declaration["nonnegative"]:
            _fail("TYPE_INVALID")
        if kind != "DECIMAL" and declaration["unit"] is not None:
            _fail("TYPE_INVALID")
    reducer = aggregate["reducer"]
    result_type = types[aggregate["result_type"]]
    if reducer in ("COUNT", "CARDINALITY"):
        if result_type["kind"] != "INTEGER" or not result_type["nonnegative"] or result_type["unit"] is not None:
            _fail("TYPE_INVALID")
    elif result_type["kind"] != "DECIMAL" or not result_type["nonnegative"] or result_type["unit"] is None:
        _fail("TYPE_INVALID")
    if (reducer == "CARDINALITY") != (aggregate["element_type"] is not None):
        _fail("TYPE_INVALID")
    _value(aggregate["bound"], types, aggregate["result_type"])
    if aggregate["bound"]["value"].startswith("-"):
        _fail("TYPE_INVALID")
    for mapping in mappings:
        if mapping["contribution"]["kind"] != reducer:
            _fail("TYPE_INVALID")
        _predicate(mapping["qualifier"], types)
    source = aggregate["committed_source"]
    if source is not None:
        if source["contribution"]["kind"] != reducer:
            _fail("TYPE_INVALID")
        _predicate(source["qualifier"], types)
    window = aggregate["window"]
    if window["kind"] == "PER_ACTION":
        if source is not None or aggregate["pending_policy"] != "EXCLUDE_RESERVED":
            _fail("INPUT_INVALID")
    elif source is None:
        _fail("INPUT_INVALID")
    if window["kind"] == "ROLLING":
        duration = window["duration_seconds"]
        if Decimal(duration) <= 0 or (aggregate["time"]["precision"] == "SECOND" and "." in duration) or ("." in duration and len(duration.split(".")[1]) > 9):
            _fail("INPUT_INVALID")
    predicates = [row["qualifier"] for row in mappings]
    if source is not None:
        predicates.append(source["qualifier"])
    nodes_depths = [_predicate_size(item) for item in predicates]
    if len(types_list) > 64 or len(mappings) > 64 or sum(row[0] for row in nodes_depths) > 4096 or max((row[1] for row in nodes_depths), default=0) > 64:
        _fail("LIMIT_EXCEEDED")
    return types


def input(request):
    types = definition(request["definition"])
    aggregate = request["definition"]["aggregate"]
    operations = request["operations"]
    if not utf8_sorted_unique([row["occurrence"] for row in operations]):
        _fail("INPUT_INVALID")
    operation_occurrences = {row["occurrence"] for row in operations}
    mappings = {row["id"]: row for row in aggregate["mappings"]}
    for operation in operations:
        if not utf8_sorted_unique([row["name"] for row in operation["fields"]]):
            _fail("INPUT_INVALID")
        fields = {row["name"]: row["value"] for row in operation["fields"]}
        for value in fields.values():
            _value(value, types)
        for mapping in mappings.values():
            if operation["step"] not in mapping["step_ids"]:
                continue
            _predicate(mapping["qualifier"], types, fields)
            if any(name not in fields for name in mapping["key_fields"]):
                _fail("INPUT_INVALID")
            if [fields[name]["type_ref"] for name in mapping["key_fields"]] != aggregate["key_types"]:
                _fail("TYPE_INVALID")
            contribution = mapping["contribution"]
            if contribution["kind"] != "COUNT":
                if contribution["field"] not in fields:
                    _fail("INPUT_INVALID")
                expected = aggregate["element_type"] if contribution["kind"] == "CARDINALITY" else aggregate["result_type"]
                _value(fields[contribution["field"]], types, expected)
    pending = request["pending"]
    pending_keys = [canonical([row["reservation"], row["mapping"], row["occurrence"], row["key"]]) for row in pending]
    if len(pending_keys) != len(set(pending_keys)) or pending_keys != sorted(pending_keys):
        _fail("INPUT_INVALID")
    if pending and aggregate["pending_policy"] != "INCLUDE_ALL_RESERVED":
        _fail("INPUT_INVALID")
    for row in pending:
        if row["mapping"] not in mappings:
            _fail("INPUT_INVALID")
        if row["occurrence"] in operation_occurrences:
            _fail("INPUT_INVALID")
        if len(row["key"]) != len(aggregate["key_types"]):
            _fail("TYPE_INVALID")
        for value, expected in zip(row["key"], aggregate["key_types"]):
            _value(value, types, expected)
        mapping = mappings[row["mapping"]]
        expected = aggregate["element_type"] if mapping["contribution"]["kind"] == "CARDINALITY" else aggregate["result_type"]
        _value(row["contribution"], types, expected)
    if not operations and request["observations"]:
        _fail("INPUT_INVALID")
    clock = request["clock"]
    if clock["source"] != aggregate["time"]["clock_source"]:
        _fail("INPUT_INVALID")
    if clock["status"] == "AVAILABLE":
        _instant(clock["instant"], aggregate["time"]["precision"])
    if aggregate["window"]["kind"] == "PER_ACTION" and request["observations"]:
        _fail("INPUT_INVALID")
    if len(operations) > 256:
        _fail("LIMIT_EXCEEDED")
    for node in [request["definition"], operations, pending, request["observations"]]:
        stack = [node]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                if set(current) == {"type_ref", "value"} and current.get("type_ref") in types:
                    declaration = types[current["type_ref"]]
                    if declaration["kind"] in ("INTEGER", "DECIMAL") and len(current["value"].lstrip("-").replace(".", "")) > 128:
                        _fail("LIMIT_EXCEEDED")
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)

