"""Closed equipment observation and dispatch schema extensions."""

from __future__ import annotations

import copy


BASE = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/"
AGG = BASE + "aggregate.schema.json#/$defs/"
ID = {"$ref": AGG + "id"}
DIGEST = {"$ref": AGG + "digest"}
VALUE = {"$ref": AGG + "value"}
FIELD = {"$ref": AGG + "field"}
INSTANT = {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}


def obj(properties, required=None):
    return {"type": "object", "properties": properties, "required": list(properties) if required is None else required, "additionalProperties": False}


def arr(items, maximum, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def optional(schema, name, value):
    schema["properties"][name] = value


def nullable(schema):
    return {"oneOf": [schema, {"type": "null"}]}


def key_projection():
    return {"oneOf": [
        obj({"field": ID, "type_ref": ID}),
        obj({"field": ID, "type_ref": ID, "key_field": ID}),
        obj({"key_field": ID, "value": VALUE}),
    ]}


def dispatch_gate():
    return obj({
        "approval_requirement": ID,
        "withdrawal_requirement": ID,
        "policy_withdrawal_requirements": arr(ID, 64),
        "fence_provider": ID,
        "fence_source": ID,
        "authorization_seconds": {"type": "string", "pattern": "^[1-9][0-9]*$", "maxLength": 128},
    })


def extend_work(defs):
    defs["exclusiveKey"]["properties"]["projection"] = arr(key_projection(), 64, 1)
    optional(defs["step"], "dispatch_gate", dispatch_gate())
    optional(defs["step"], "authority_type_refs", arr(ID, 64))


def extend_authority(schema):
    defs = schema["$defs"]
    defs["exclusiveKey"]["properties"]["projection"] = arr(key_projection(), 64, 1)
    optional(defs["step"], "quantity_mode", {"enum": ["BOUNDED", "NONE"]})
    for name in ("quantity_mode", "exclusive_keys"):
        if name not in defs["step"]["required"]:
            defs["step"]["required"].append(name)
    optional(defs["step"], "dispatch_gate", dispatch_gate())
    optional(defs["step"], "authority_type_refs", arr(ID, 64))
    optional(defs["input"], "evaluation_point", {"enum": ["PROPOSE", "DISPATCH"]})
    selector = {"oneOf": [
        ID,
        obj({"kind": {"const": "PROPOSAL_FIELD"}, "field": ID}),
        obj({"kind": {"const": "EXECUTOR"}, "member": {"enum": ["actor", "role", "principal", "occupancy"]}, "type_ref": ID}),
        obj({"kind": {"const": "ACT"}, "act_kind": {"enum": ["GRANT", "VERIFY", "INSTANCE_DECISION"]}, "member": {"enum": ["id", "actor", "role", "principal", "occurred_at"]}, "type_ref": ID}),
        obj({"kind": {"const": "OBSERVATION_FIELD"}, "requirement_id": ID, "field": ID}),
        obj({"kind": {"const": "OBSERVATION_ID"}, "requirement_id": ID, "type_ref": ID}),
        obj({"kind": {"const": "CLOCK"}, "type_ref": ID}),
        obj({"kind": {"const": "LITERAL"}, "value": VALUE}),
    ]}
    defs["sourceObservationSelector"] = selector
    relation = defs["sourceObservationRelation"]
    if "oneOf" in relation:
        relation = relation["oneOf"][0]
    relation["properties"]["kind"]["enum"] = ["EQUALS", "NOT_EQUALS", "BEFORE", "AFTER", "AT_OR_BEFORE", "AT_OR_AFTER", "INCLUDES"]
    relation["properties"]["left"] = {"$ref": "#/$defs/sourceObservationSelector"}
    relation["properties"]["right"] = {"$ref": "#/$defs/sourceObservationSelector"}
    requirement = defs["sourceObservationRequirement"]
    requirement["properties"]["at"] = {"oneOf": [INSTANT, {"const": "CLOCK"}]}
    requirement["properties"]["subject"] = {"oneOf": [
        ID,
        obj({"kind": {"const": "PROPOSAL_FIELD"}, "field": ID}),
        obj({"kind": {"const": "EXECUTOR"}, "member": {"enum": ["actor", "role", "principal", "occupancy"]}, "type_ref": ID}),
    ]}
    for name in ("sourceObservationRequirement", "sourceObservationQuery"):
        defs[name]["properties"]["expected_status"] = {"enum": ["AVAILABLE", "ABSENT"]}
        optional(defs[name], "evaluation_point", {"enum": ["PROPOSE", "PROPOSE_AND_DISPATCH"]})
    query_projection = key_projection()
    query_projection["oneOf"] = query_projection["oneOf"][:2]
    optional(requirement, "key_projection", arr(query_projection, 64, 1))
    optional(defs["sourceObservationQuery"], "key", arr(FIELD, 64, 1))
    absent = copy.deepcopy(defs["sourceObservationUnavailable"])
    absent["properties"]["status"] = {"const": "ABSENT"}
    absent["properties"]["as_of"] = INSTANT
    absent["properties"]["revision"] = ID
    absent["properties"]["coverage"] = {"const": "COMPLETE"}
    absent["required"].append("coverage")
    defs["sourceObservationAbsent"] = absent
    defs["sourceObservationUnavailable"]["properties"]["status"]["enum"] = ["UNAVAILABLE", "INCOMPLETE", "CONFLICT", "ROLLED_BACK"]
    defs["sourceObservation"]["oneOf"] = [row for row in defs["sourceObservation"]["oneOf"] if row.get("$ref") != "#/$defs/sourceObservationAbsent"] + [{"$ref": "#/$defs/sourceObservationAbsent"}]


def extend_lifecycle(defs):
    for definition in defs.values():
        properties = definition.get("properties", {})
        if "affected_anchors" in properties:
            properties["affected_anchors"]["minItems"] = 0
    for row in defs["permit"]["properties"]["budget_revisions"]["items"]["properties"].values():
        if row.get("type") == "array":
            row["minItems"] = 0
    optional(defs["permit"], "authority_basis", {"$ref": BASE + "authority.schema.json#/$defs/input"})
    optional(defs["authorizeDispatch"], "authority_input", {"$ref": BASE + "authority.schema.json#/$defs/input"})
    optional(defs["authorizeDispatch"], "dispatch_intent_id", ID)
    defs["authorizeDispatch"]["properties"]["authorization_fence"] = nullable({"$ref": "#/$defs/authorizationFence"})
    defs["fenceSource"] = obj({
        "requirement_id": ID, "provider": ID, "source": ID,
        "expected_status": {"enum": ["AVAILABLE", "ABSENT"]},
        "record_id": nullable(ID), "provider_revision": ID,
        "query_digest": DIGEST, "observation_digest": DIGEST,
    })
    optional(defs["authorizationFence"], "sources", arr({"$ref": "#/$defs/fenceSource"}, 64, 1))
    defs["authorizationEvaluation"] = obj({
        "evaluation_digest": DIGEST,
        "event_id": ID, "event_digest": DIGEST, "permit_digest": DIGEST,
        "dispatch_intent_id": ID, "clock_revision": {"$ref": AGG + "natural"},
        "authority_input": {"$ref": BASE + "authority.schema.json#/$defs/input"},
        "authority_result": {"oneOf": [
            {"$ref": BASE + "authority.schema.json#/$defs/result"},
            {"$ref": BASE + "authority.schema.json#/$defs/refusal"},
        ]},
        "authority_result_digest": DIGEST,
        "authorization_digest": nullable(DIGEST),
        "disposition": {"enum": ["AUTHORIZED", "WITHHELD"]},
    })
    optional(defs["state"], "authorization_evaluations", arr({"$ref": "#/$defs/authorizationEvaluation"}, 128))
    optional(defs["decisionReceipt"], "authorization_evaluation_digest", DIGEST)
    legacy_detail = copy.deepcopy(defs["decisionDetailAuthorization"])
    defs["decisionDetailAuthorization"] = {"oneOf": [legacy_detail, obj({
        "kind": {"const": "AUTHORIZATION"}, "authorization_digest": DIGEST,
        "permit_digest": DIGEST, "approval_id": ID, "checked_at": INSTANT,
        "expires_at": INSTANT, "sources": arr({"$ref": "#/$defs/fenceSource"}, 64, 1),
    })]}
    record = defs["authorizationRecord"]
    for name, value in {
        "dispatch_intent_id": ID,
        "authority_input": {"$ref": BASE + "authority.schema.json#/$defs/input"},
        "authority_result": {"$ref": BASE + "authority.schema.json#/$defs/result"},
        "authority_result_digest": DIGEST,
        "expires_at": INSTANT,
        "supersedes_authorization_digest": nullable(DIGEST),
    }.items():
        optional(record, name, value)


def extend_common(schema):
    kinds = schema["$defs"]["type"]["properties"]["kind"]["enum"]
    if "INSTANT" not in kinds:
        kinds.append("INSTANT")


def extend_reservation(schema):
    slot = schema["$defs"]["exclusiveSlot"]
    if "oneOf" in slot:
        slot = slot["oneOf"][0]
        schema["$defs"]["exclusiveSlot"] = slot
    optional(slot, "key_shape", arr(obj({"name": ID, "type_ref": ID}), 64, 1))
    optional(slot, "types", arr({"$ref": AGG + "type"}, 64, 1))
