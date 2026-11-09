"""Closed authoritative holdings profile and its authority carriers."""
from __future__ import annotations

import copy

BASE = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/"
PREFIX = "seampoint.work-class/1.0.0-draft.3/"
ID = {"$ref": BASE + "aggregate.schema.json#/$defs/id"}
DIGEST = {"$ref": BASE + "aggregate.schema.json#/$defs/digest"}
NATURAL = {"$ref": BASE + "aggregate.schema.json#/$defs/natural"}
INSTANT = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}


def obj(properties, optional=()):
    return {"type": "object", "properties": properties,
            "required": [name for name in properties if name not in optional], "additionalProperties": False}


def arr(items, maximum, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def ref(name):
    return {"$ref": "#/$defs/" + name}


def nullable(schema):
    return {"oneOf": [schema, {"type": "null"}]}


def holdings_schema():
    d = {}
    d["configuration"] = obj({
        "schema": {"const": PREFIX + "holdings-configuration"}, "specification_pin": DIGEST,
        "id": ID, "principal": ID, "policy_revision": ID, "provider": ID, "source": ID,
        "protected_channel": ID, "clock_source": ID, "administration_role": ID,
        "actor_namespace": ID, "identity_provider": ID, "identity_revision": ID,
        "permissions": arr(ID, 64, 1), "conflicts": arr(obj({"left": ID, "right": ID}), 128),
    })
    d["initialGrant"] = obj({"id": ID, "actor": ID, "permission": ID,
        "valid_from": INSTANT, "valid_until": nullable(INSTANT)})
    d["grant"] = copy.deepcopy(d["initialGrant"])
    d["grant"]["properties"]["revoked_at"] = nullable(INSTANT)
    d["grant"]["required"].append("revoked_at")
    d["adminBasis"] = obj({
        "id": ID, "configuration_digest": DIGEST, "principal": ID, "role": ID, "actor": ID,
        "actor_kind": {"const": "HUMAN"}, "allowed_operations": arr({"enum": ["INITIALIZE", "GRANT", "REVOKE"]}, 3, 1),
        "provider": ID, "source": ID, "observed_at": INSTANT, "valid_from": INSTANT,
        "valid_until": nullable(INSTANT), "revoked_at": nullable(INSTANT), "evidence_ref": ID,
    })
    d["adminAct"] = obj({"id": ID, "basis_id": ID, "actor": ID, "principal": ID, "role": ID,
        "kind": {"enum": ["INITIALIZE", "GRANT", "REVOKE"]}, "subject_digest": DIGEST,
        "occurred_at": INSTANT, "status": {"enum": ["ACCEPTED", "REJECTED"]}})
    d["adminReturn"] = obj({"actor": ID, "provider": ID, "source": ID, "channel": ID,
        "observed_at": INSTANT, "act_digest": DIGEST,
        "act_bytes_base64": {"type": "string", "maxLength": 349528, "pattern": "^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"},
        "evidence_ref": ID, "provenance_digest": DIGEST})
    d["administration"] = obj({"basis": ref("adminBasis"), "act": ref("adminAct"), "return": nullable(ref("adminReturn"))})
    d["hostEvidence"] = obj({"configuration_digest": DIGEST, "selection_evidence": ID,
        "authenticated_records": arr(obj({"kind": {"enum": ["ADMIN_BASIS", "ADMIN_RETURN"]},
            "record_digest": DIGEST, "provider": ID, "source": ID, "channel": nullable(ID)}), 2),
        "seed_inventory": nullable(obj({"inventory_digest": DIGEST, "evidence_ref": ID}))})
    clock = {"$ref": BASE + "authority.schema.json#/$defs/clock"}
    common = {"schema": {"const": PREFIX + "holdings-event"}, "id": ID, "expected_revision": NATURAL,
        "expected_state_digest": nullable(DIGEST), "clock": clock, "administration": nullable(ref("administration"))}
    variants = []
    for kind, payload in (("INITIALIZE", obj({"grants": arr(ref("initialGrant"), 256)})),
            ("GRANT", obj({"grant_id": ID, "actor": ID, "permission": ID, "valid_until": nullable(INSTANT)})),
            ("REVOKE", obj({"grant_id": ID, "actor": ID, "permission": ID}))):
        variants.append(obj({**copy.deepcopy(common), "kind": {"const": kind}, "payload": payload}))
    d["event"] = {"oneOf": variants}
    d["core"] = obj({"configuration_digest": DIGEST, "revision": NATURAL,
        "last_clock": INSTANT, "grants": arr(ref("grant"), 256)})
    d["receipt"] = obj({"schema": {"const": PREFIX + "holdings-receipt"}, "event_id": ID,
        "event_digest": DIGEST, "state_before_digest": nullable(DIGEST), "revision": NATURAL,
        "core_after_digest": DIGEST, "decision": {"enum": ["INITIALIZED", "GRANTED", "REVOKED", "UNCHANGED", "WITHHELD"]},
        "reasons": arr({"enum": ["ALREADY_HELD", "CONFLICTING_HOLDING", "NOT_ACTIVE"]}, 1),
        "protected_channel": ID})
    d["record"] = obj({"event": ref("event"), "host_evidence": ref("hostEvidence"),
        "event_digest": DIGEST, "receipt": ref("receipt"), "receipt_digest": DIGEST})
    d["state"] = obj({"schema": {"const": PREFIX + "holdings-state"}, "specification_pin": DIGEST,
        "core": ref("core"), "records": arr(ref("record"), 64, 1)})
    d["input"] = obj({"schema": {"const": PREFIX + "holdings-input"}, "specification_pin": DIGEST,
        "configuration": ref("configuration"), "state": nullable(ref("state")), "state_digest": nullable(DIGEST),
        "event": ref("event"), "host_evidence": ref("hostEvidence")})
    d["result"] = obj({"status": {"const": "TRANSITION"}, "receipt": ref("receipt"),
        "receipt_digest": DIGEST, "state": ref("state"), "state_digest": DIGEST, "replay": {"type": "boolean"}})
    codes = ["ADMINISTRATION_NOT_ESTABLISHED", "ARTIFACT_ENCODING_INVALID", "ARTIFACT_NONCANONICAL",
        "BINDING_MISMATCH", "CLOCK_INVALID", "DEFINITION_CONFLICT", "DEFINITION_INVALID", "DEPENDENCY_MISMATCH",
        "DIGEST_MISMATCH", "EVIDENCE_UNAVAILABLE", "LIMIT_EXCEEDED", "REPLAY_CONFLICT", "REVISION_CONFLICT",
        "SCHEMA_INVALID", "STATE_INVALID", "VERSION_UNSUPPORTED"]
    d["refusal"] = obj({"status": {"const": "REFUSED"}, "code": {"enum": codes}, "path": {"const": ""},
        "state": nullable(ref("state")), "state_digest": nullable(DIGEST)})
    d["selection"] = obj({"configuration_digest": DIGEST, "state_digest": DIGEST, "revision": NATURAL,
        "provider": ID, "source": ID, "channel": ID, "at": INSTANT,
        "status": {"enum": ["AVAILABLE", "UNAVAILABLE", "CONFLICTING"]}, "selection_evidence": ID})
    d["authorityBasis"] = obj({"configuration": ref("configuration"), "state": ref("state"),
        "state_digest": DIGEST, "selection": ref("selection")})
    d["requirement"] = obj({"id": ID, "step": ID, "configuration_digest": DIGEST,
        "permission": ID, "actor": {"enum": ["EXECUTOR", "GATE_ACTOR"]}})
    d["fenceHolding"] = obj({"requirement_id": ID, "configuration_digest": DIGEST, "state_digest": DIGEST,
        "revision": NATURAL, "actor": ID, "permission": ID, "grant_id": ID, "valid_until": nullable(INSTANT)})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": BASE + "holdings.schema.json",
        "$comment": "DRAFT_NOT_ADOPTED; APPARATUS_ONLY. Host authentication and latest-state selection remain external obligations.",
        "$defs": d, "oneOf": [ref(name) for name in ("input", "result", "refusal")]}


def extend_holdings_schemas(authority, lifecycle, protocol):
    a, l, p = (value["$defs"] for value in (authority, lifecycle, protocol))
    a["envelope"]["properties"]["holdings_requirements"] = arr({"$ref": BASE + "holdings.schema.json#/$defs/requirement"}, 32)
    a["input"]["properties"]["holdings_bases"] = arr({"$ref": BASE + "holdings.schema.json#/$defs/authorityBasis"}, 8)
    for code in ("DEFINITION_INVALID", "STATE_INVALID", "DIGEST_MISMATCH", "CLOCK_INVALID"):
        if code not in a["refusal"]["properties"]["code"]["enum"]:
            a["refusal"]["properties"]["code"]["enum"].append(code)
    for name in ("check", "failedCheck"):
        if "HOLDINGS" not in a[name]["properties"]["purpose"]["enum"]:
            a[name]["properties"]["purpose"]["enum"].append("HOLDINGS")
    reasons = ["CURRENT_HOLDING_REQUIRED", "HOLDINGS_UNAVAILABLE", "HOLDINGS_STALE", "HOLDINGS_CAPACITY_EXHAUSTED"]
    for name, prop in (("refusal", "reasons"), ("failedCheck", "reason")):
        target = a[name]["properties"][prop]
        if prop == "reasons":
            target = target["items"]
        for reason in reasons:
            if reason not in target["enum"]:
                target["enum"].append(reason)
    for variant in l["authorizationFence"]["oneOf"]:
        if variant["properties"].get("kind", {}).get("const") == "SOURCE_REQUIREMENTS":
            variant["properties"]["holdings"] = arr({"$ref": BASE + "holdings.schema.json#/$defs/fenceHolding"}, 32, 1)
    for variant in l["decisionDetailAuthorization"]["oneOf"]:
        if variant["properties"].get("gate_kind", {}).get("const") == "SOURCE_REQUIREMENTS":
            variant["properties"]["holdings"] = arr({"$ref": BASE + "holdings.schema.json#/$defs/fenceHolding"}, 32, 1)
    roles = p["capabilitiesResult"]["properties"]["roles"]
    if "HOLDINGS_TRANSITIONS" not in roles["items"]["enum"]:
        roles["items"]["enum"].append("HOLDINGS_TRANSITIONS")
        roles["items"]["enum"].sort()
    operations = p["capabilitiesResult"]["properties"]["operations"]
    if "holdings-step" not in operations["items"]["enum"]:
        operations["items"]["enum"].append("holdings-step")
        operations["items"]["enum"].sort()
    operations["maxItems"] = 9
    for name, body in (("request", "input"), ("response", "result")):
        p[name]["oneOf"] = [v for v in p[name]["oneOf"] if v["properties"]["operation"].get("const") != "holdings-step"]
        properties = {"protocol": {"const": "seampoint.work-class.adapter/1.0.0-draft.3"},
            "request_id": ID, "operation": {"const": "holdings-step"}}
        properties[body] = {"$ref": BASE + "holdings.schema.json#/$defs/input"} if body == "input" else {
            "anyOf": [{"$ref": BASE + "holdings.schema.json#/$defs/result"},
                {"$ref": BASE + "holdings.schema.json#/$defs/refusal"}, {"$ref": "#/$defs/shapeRefusal"}]}
        p[name]["oneOf"].append(obj(properties))
