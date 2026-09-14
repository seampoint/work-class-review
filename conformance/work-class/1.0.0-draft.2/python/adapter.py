#!/usr/bin/env python3
"""Restricted JSON-lines adapter for the independent draft-2 consumer."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
for dependency in (ROOT, ROOT / "vendor"):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

from implementation import artifacts, evidence, operations  # noqa: E402
from implementation.common import (  # noqa: E402
    IDENTIFIER_PATTERN,
    PIN,
    PROTOCOL,
    Refusal,
    artifact_bytes,
    canonical,
    parse_json,
    schema_valid,
)


ALL_OPERATIONS = (
    "aggregate-step",
    "capabilities",
    "check-evidence",
    "deploy",
    "evaluate",
    "readback",
    "step",
    "validate",
)
ALL_ROLES = (
    "AGGREGATE_EVALUATOR",
    "AUTHORITY_EVALUATOR",
    "CHOICE_LOOP_RUNTIME",
    "DEADLINE_RUNTIME",
    "LINEAR_WORK_RUNTIME",
    "PARALLEL_FANOUT_RUNTIME",
    "REFERENCE_SINGLE_PROCESS_CONTENTION",
    "REVIEW_EVIDENCE",
    "SHARED_BUDGET_TRANSITIONS",
)
ACTIVE_ROLES = tuple(sorted(filter(None,os.environ.get("WORK_CLASS_ADAPTER_ROLES",",".join(ALL_ROLES)).split(",")),key=str.encode))
IMPLEMENTED_OPERATIONS = ALL_OPERATIONS if "SHARED_BUDGET_TRANSITIONS" in ACTIVE_ROLES else tuple(operation for operation in ALL_OPERATIONS if operation!="aggregate-step")
LIMITS = {
    "max_definitions": "64",
    "max_operations": "256",
    "max_collection_members": "1024",
    "max_numeric_digits": "128",
    "max_expression_depth": "64",
    "max_expression_nodes": "4096",
}


def refusal(code: str):
    return {"status": "REFUSED", "code": code, "path": ""}


def _echo_identifier(value):
    return value if isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value) else None


def _response(request_id, operation, result):
    return {
        "protocol": PROTOCOL,
        "request_id": request_id,
        "operation": operation,
        "result": result,
    }


def _protocol_error(request):
    if not isinstance(request, dict):
        return _response(None, None, refusal("PROTOCOL_INVALID"))
    return _response(
        _echo_identifier(request.get("request_id")),
        _echo_identifier(request.get("operation")),
        refusal("PROTOCOL_INVALID"),
    )


def _dispatch(operation: str, value):
    if operation == "capabilities":
        if value != {}:
            return refusal("SCHEMA_INVALID")
        return {
            "status": "CAPABILITIES",
            "protocol": PROTOCOL,
            "specification_pin": PIN,
            "roles": list(ACTIVE_ROLES),
            "operations": list(IMPLEMENTED_OPERATIONS),
            "tzdb": "2025a",
            "limits": LIMITS,
        }
    if operation in ("validate", "readback"):
        if not schema_valid(value, "protocol.schema.json", "artifactInput"):
            return refusal("SCHEMA_INVALID")
        if value["specification_pin"] != PIN:
            return refusal("VERSION_UNSUPPORTED")
        try:
            artifact = artifact_bytes(value["artifact_bytes_base64"])
            if operation == "validate":
                return {"status": "ACCEPTED", "digest": artifacts.admit(value["kind"], artifact)}
            return artifacts.readback(value["kind"], artifact)
        except Refusal as error:
            return refusal(error.code)
    if operation == "evaluate":
        if not schema_valid(value, "protocol.schema.json", "evaluateInput"):
            return refusal("SCHEMA_INVALID")
        if value["kind"] == "AGGREGATE":
            return operations.aggregate(value["request"])
        return operations.authority_evaluate(value["request"])
    if operation == "aggregate-step":
        return operations.reservation_step(value) if "SHARED_BUDGET_TRANSITIONS" in ACTIVE_ROLES else refusal("ROLE_UNSUPPORTED")
    if operation == "check-evidence":
        return evidence.check(value)
    if operation == "deploy":
        return operations.lifecycle_deploy(value)
    if operation == "step":
        return operations.lifecycle_step(value)
    raise RuntimeError("unreachable operation")


def handle(request):
    if (
        type(request) is not dict
        or set(request) != {"protocol", "request_id", "operation", "input"}
        or request.get("protocol") != PROTOCOL
        or _echo_identifier(request.get("request_id")) is None
        or _echo_identifier(request.get("operation")) is None
        or request["operation"] not in ALL_OPERATIONS
        or type(request.get("input")) is not dict
    ):
        return _protocol_error(request)
    result = _dispatch(request["operation"], request["input"])
    response = _response(request["request_id"], request["operation"], result)
    if not schema_valid(response, "protocol.schema.json", "response"):
        raise RuntimeError("operation produced an invalid protocol response")
    return response


def main():
    if sys.argv[1:]:
        raise SystemExit("usage: adapter.py")
    for raw in sys.stdin.buffer:
        if not raw.endswith(b"\n"):
            print("unterminated request", file=sys.stderr)
            raise SystemExit(2)
        try:
            request = parse_json(raw[:-1])
            response = handle(request)
        except Exception as error:
            print(f"transport or execution failure: {error}", file=sys.stderr)
            raise SystemExit(2) from error
        sys.stdout.buffer.write(canonical(response) + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
