"""Pure aggregate, authority, and reservation operation entry points."""

from __future__ import annotations

from . import aggregate_contract, authority, core, lifecycle, reservation_v2
from .common import PIN, Refusal, digest, schema_valid


def aggregate(request):
    if not schema_valid(request, "aggregate.schema.json", "input"):
        return {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""}
    if request["specification_pin"] != PIN:
        return {"status": "REFUSED", "code": "VERSION_UNSUPPORTED", "path": ""}
    if request["definition_digest"] != digest("aggregate-definition", request["definition"]):
        return {"status": "REFUSED", "code": "INPUT_INVALID", "path": ""}
    try:
        aggregate_contract.input(request)
        core.semantic_validate(request)
        result = core.Eval(request).evaluate()
    except (Refusal, core.Refusal) as error:
        return {"status": "REFUSED", "code": error.code, "path": ""}
    result["specification_pin"] = PIN
    if not schema_valid(result, "aggregate.schema.json", "result"):
        raise RuntimeError("aggregate evaluator produced an invalid result")
    return result


def authority_evaluate(request):
    if not schema_valid(request, "authority.schema.json", "input"):
        return {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": "", "reasons": [], "failed_checks": []}
    result = authority.evaluate_authority(request, PIN)
    if not (
        schema_valid(result, "authority.schema.json", "result")
        or schema_valid(result, "authority.schema.json", "refusal")
    ):
        raise RuntimeError("authority evaluator produced an invalid result")
    return result


def reservation_step(request):
    result = reservation_v2.aggregate_step(request, PIN)
    if not (
        schema_valid(result, "reservation.schema.json", "result")
        or schema_valid(result, "reservation.schema.json", "statefulRefusal")
        or schema_valid(result, "reservation.schema.json", "shapeRefusal")
    ):
        raise RuntimeError("reservation evaluator produced an invalid result")
    return result


def lifecycle_deploy(request):
    if not schema_valid(request, "lifecycle.schema.json", "deployInput"):
        return {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""}
    try:
        result = lifecycle.deploy(request)
    except Refusal as error:
        result = {"status": "REFUSED", "profile": request["profile"], "role": request["role"], "code": error.code, "path": ""}
    if not (
        schema_valid(result, "lifecycle.schema.json", "deployResult")
        or schema_valid(result, "lifecycle.schema.json", "deployRefusal")
    ):
        raise RuntimeError("lifecycle deployment produced an invalid result")
    return result


def lifecycle_step(request):
    if isinstance(request,dict) and request.get("profile") in lifecycle.PROFILE_ROLES and request.get("role") != lifecycle.PROFILE_ROLES[request["profile"]]:
        return {"status":"REFUSED","code":"ROLE_UNSUPPORTED","path":""}
    if not schema_valid(request, "lifecycle.schema.json", "stepInput"):
        return {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""}
    try:
        result = lifecycle.step(request)
    except Refusal as error:
        result = lifecycle.refusal(request, error.code)
    if not (
        schema_valid(result, "lifecycle.schema.json", "stepResult")
        or schema_valid(result, "lifecycle.schema.json", "statefulRefusal")
    ):
        raise RuntimeError("lifecycle step produced an invalid result")
    return result
