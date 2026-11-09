"""Proposed exclusive-history schema extension; importing does not change the pin."""

from __future__ import annotations

import copy
from typing import Any


AGG = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/aggregate.schema.json#/$defs/"
AUTH = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/authority.schema.json#/$defs/"


def extend_reservation_schema(schema: dict[str, Any]) -> None:
    defs = schema["$defs"]
    def ref(name: str) -> dict[str, str]:
        return {"$ref": "#/$defs/" + name}
    def agg(name: str) -> dict[str, str]:
        return {"$ref": AGG + name}
    def closed(properties: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    def rows(item: dict[str, Any], maximum: int, minimum: int = 0) -> dict[str, Any]:
        return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}
    identity = agg("id")
    hashed = agg("digest")
    instant = {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}
    null = {"type": "null"}
    fields = rows(closed({"name": identity, "type_ref": identity}), 64)
    defs["historyProjection"] = {"oneOf": [
        closed({"key_field": identity, "kind": {"const": "NATIVE_FIELD"}, "field": identity, "type_ref": identity}),
        closed({"key_field": identity, "kind": {"const": "SOURCE_REQUEST"}, "member": {"enum": ["issuer", "provider", "source", "request_id"]}, "type_ref": identity}),
        closed({"key_field": identity, "kind": {"const": "RECORD"}, "member": {"enum": ["provider", "source", "record_id"]}, "type_ref": identity}),
        closed({"key_field": identity, "kind": {"const": "LITERAL"}, "value": agg("value")}),
    ]}
    defs["exclusiveUniqueness"] = {"oneOf": [
        closed({"kind": {"const": "PROVIDER_UNIQUENESS"}, "provider": identity, "source": identity,
            "atomic_scope": closed({"slot": identity, "namespace": identity, "key_shape": rows(closed({"name": identity, "type_ref": identity}), 64, 1)}),
            "evidence_ref": identity}),
        closed({"kind": {"const": "EXCLUSIVE_MEDIATOR_SEEDED"}, "provider": identity, "source": identity,
            "record_type": identity, "history_scope": identity, "cutover_id": identity, "evidence_ref": identity}),
    ]}
    inherited_slot = copy.deepcopy(defs["exclusiveSlot"])
    profile_properties = copy.deepcopy(inherited_slot["properties"])
    profile_properties.update({"history_record_fields": closed({"held": fields, "consumed": fields}),
        "history_projection": rows(ref("historyProjection"), 64, 1), "uniqueness": ref("exclusiveUniqueness")})
    defs["exclusiveSlot"] = {"oneOf": [inherited_slot, closed(profile_properties)]}
    work_owner = closed({"kind": {"const": "WORK_OCCURRENCE"}, "work_class": identity, "instance_id": identity, "occurrence_id": identity})
    defs["exclusiveOwner"] = {"oneOf": [work_owner, closed({"kind": {"const": "NATIVE_HISTORY"},
        "provider": identity, "source": identity, "record_id": identity, "record_digest": hashed})]}
    work_occurrence = closed({"work_class": identity, "instance_id": identity, "occurrence_id": identity})
    defs["exclusiveNativeHistory"] = closed({"provider": identity, "source": identity, "record_type": identity,
        "record_id": identity, "revision": identity, "occurred_at": instant,
        "state": {"enum": ["HELD", "CONSUMED"]}, "native_fields": rows(agg("field"), 64),
        "work_occurrence": {"oneOf": [work_occurrence, null]}, "evidence_ref": identity})
    defs["exclusiveSourceRequest"] = closed({member: identity for member in ("issuer", "provider", "source", "request_id")})
    defs["exclusiveRequestProvenance"] = closed({"provider": identity, "source": identity,
        "native_record_digest": hashed, "source_request_digest": hashed, "evidence_ref": identity, "provenance_digest": hashed})
    live_properties = {"key_digest": hashed, "slot": identity, "namespace": identity,
        "key": rows(agg("value"), 64, 1), "owner": ref("exclusiveOwner"), "acquisition_event": identity,
        "status": {"enum": ["HELD", "CONSUMED"]}, "settlement_evidence": {"oneOf": [identity, null]}}
    defs["exclusiveSeedClaim"] = closed({**live_properties, "native_record": ref("exclusiveNativeHistory"),
        "record_digest": hashed, "source_request": ref("exclusiveSourceRequest"), "request_provenance": ref("exclusiveRequestProvenance")})
    inherited_state = copy.deepcopy(defs["exclusiveState"].get("oneOf", [defs["exclusiveState"]])[0])
    defs["exclusiveState"] = {"oneOf": [inherited_state, closed(live_properties)]}
    defs["exclusiveCoverage"] = closed({"slot": identity, "provider": identity, "source": identity,
        "record_type": identity, "history_scope": identity, "cutover_id": identity, "as_of": instant,
        "revision": identity, "complete": {"type": "boolean"}, "exclusive_writers": {"type": "boolean"},
        "evidence_ref": identity, "provenance_digest": hashed})
    defs["seedExclusivePayload"] = closed({"slot": identity, "coverage": ref("exclusiveCoverage"),
        "claims": rows(ref("exclusiveSeedClaim"), 256)})
    defs["exclusiveHistorySnapshot"] = closed({"registry_digest": hashed, "event_id": identity,
        **copy.deepcopy(defs["seedExclusivePayload"]["properties"])})
    defs["exclusiveHistoryRecord"] = closed({"snapshot_digest": hashed, "snapshot": ref("exclusiveHistorySnapshot")})
    defs["core"]["properties"]["key_history"] = rows(ref("exclusiveHistoryRecord"), 64)
    defs["configuration"]["properties"]["exclusive_slots"]["maxItems"] = 64
    defs["core"]["properties"]["exclusive_keys"]["maxItems"] = 4096
    defs["event"]["oneOf"] = [row for row in defs["event"]["oneOf"] if row.get("properties", {}).get("kind", {}).get("const") != "SEED_EXCLUSIVE"]
    defs["event"]["oneOf"].append(closed({"id": identity, "expected_revision": agg("natural"),
        "kind": {"const": "SEED_EXCLUSIVE"}, "clock": {"$ref": AUTH + "clock"},
        "payload": ref("seedExclusivePayload"), "administration": ref("administration")}))
    for name, field in (("adminBasis", "operations"), ("adminAct", "kind")):
        selected = defs[name]["properties"][field]
        values = selected["items"]["enum"] if field == "operations" else selected["enum"]
        if "SEED_EXCLUSIVE" not in values:
            values.append("SEED_EXCLUSIVE")
    for kind in ["EXCLUSIVE_COVERAGE", "EXCLUSIVE_NATIVE_HISTORY", "EXCLUSIVE_REQUEST_PROVENANCE"]:
        kinds = defs["authenticated"]["properties"]["kind"]["enum"]
        if kind not in kinds:
            kinds.append(kind)
    decisions = defs["receipt"]["properties"]["decision"]["enum"]
    if "SEEDED_EXCLUSIVE" not in decisions:
        decisions.append("SEEDED_EXCLUSIVE")
