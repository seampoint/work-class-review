"""Complete exclusive-slot declarations and attributed cutover history."""

from __future__ import annotations

import copy

from . import authority
from .common import Refusal, canonical, digest, utf8_sorted_unique, valid_instant


def complete(slot):
    return "uniqueness" in slot


def mediated(slot):
    return complete(slot) and slot["uniqueness"]["kind"] == "EXCLUSIVE_MEDIATOR_SEEDED"


def validate_slot(slot):
    if not complete(slot):
        return
    declarations = slot["types"]
    if not utf8_sorted_unique([row["id"] for row in declarations]):
        raise Refusal("INPUT_INVALID")
    if any(row["kind"] not in {"INTEGER", "DECIMAL"} and row["nonnegative"]
           or row["kind"] != "DECIMAL" and row["unit"] is not None for row in declarations):
        raise Refusal("TYPE_INVALID")
    types = {row["id"]: row for row in declarations}
    shape = slot["key_shape"]
    if len({row["name"] for row in shape}) != len(shape):
        raise Refusal("INPUT_INVALID")
    for field in shape:
        if field["type_ref"] not in types:
            raise Refusal("REFERENCE_INVALID")
    inventories = slot["history_record_fields"]
    for fields in inventories.values():
        if not utf8_sorted_unique([row["name"] for row in fields]):
            raise Refusal("INPUT_INVALID")
        if any(row["type_ref"] not in types for row in fields):
            raise Refusal("REFERENCE_INVALID")
    projection = slot["history_projection"]
    if len(projection) != len(shape):
        raise Refusal("INPUT_INVALID")
    for field, selector in zip(shape, projection):
        if selector["key_field"] != field["name"]:
            raise Refusal("INPUT_INVALID")
        kind = selector["kind"]
        selected_type = selector["value"]["type_ref"] if kind == "LITERAL" else selector["type_ref"]
        if selected_type not in types:
            raise Refusal("REFERENCE_INVALID")
        if selected_type != field["type_ref"]:
            raise Refusal("TYPE_INVALID")
        if kind == "NATIVE_FIELD":
            for fields in inventories.values():
                source = next((row for row in fields if row["name"] == selector["field"]), None)
                if source is None:
                    raise Refusal("REFERENCE_INVALID")
                if source["type_ref"] != selected_type:
                    raise Refusal("TYPE_INVALID")
        elif kind in {"SOURCE_REQUEST", "RECORD"}:
            if types[selected_type]["kind"] not in {"IDENTITY", "STRING"}:
                raise Refusal("TYPE_INVALID")
        elif kind == "LITERAL":
            if not authority._typed_value_valid(selector["value"], types):
                raise Refusal("TYPE_INVALID")
        else:
            raise Refusal("UNSUPPORTED_RELATION")
    guarantee = slot["uniqueness"]
    if guarantee["kind"] == "PROVIDER_UNIQUENESS":
        scope = {name: slot[name] for name in ("slot", "namespace", "key_shape")}
        if guarantee["atomic_scope"] != scope:
            raise Refusal("BINDING_MISMATCH")
    elif guarantee["kind"] != "EXCLUSIVE_MEDIATOR_SEEDED":
        raise Refusal("UNSUPPORTED_RELATION")


def validate_binding(slot, key, projected_types, declaration):
    if not complete(slot):
        return
    types = {row["id"]: row for row in slot["types"]}
    for identifier, row in types.items():
        if identifier not in projected_types:
            raise Refusal("REFERENCE_INVALID")
        if row != projected_types[identifier]:
            raise Refusal("TYPE_INVALID")
    if len(key) != len(slot["key_shape"]) or len(declaration["projection"]) != len(key):
        raise Refusal("BINDING_MISMATCH")
    for field, value, projection in zip(slot["key_shape"], key, declaration["projection"]):
        if projection.get("key_field", projection.get("field")) != field["name"]:
            raise Refusal("BINDING_MISMATCH")
        if value["type_ref"] != field["type_ref"]:
            raise Refusal("TYPE_INVALID")
        if not authority._typed_value_valid(value, types):
            raise Refusal("TYPE_INVALID")


def owner(proposal):
    return {"kind": "WORK_OCCURRENCE", "work_class": proposal["work_class"],
        "instance_id": proposal["instance"], "occurrence_id": proposal["occurrence"]}


def owned(row, proposal):
    if "owner" in row:
        return row["owner"] == owner(proposal)
    return (row["owner_instance"], row["owner_occurrence"]) == (proposal["instance"], proposal["occurrence"])


def unavailable(core, keys):
    slots = {row["slot"]: row for row in core["configuration"].get("exclusive_slots", [])}
    snapshots = {row["snapshot"]["slot"]: row["snapshot"] for row in core.get("key_history", [])}
    return any(mediated(slots[key["slot"]]) and key["slot"] not in snapshots for key in keys)


def seed(core, event, host, registry):
    fail = registry._AdmissionError
    payload = event["payload"]
    slot = next((row for row in core["configuration"].get("exclusive_slots", []) if row["slot"] == payload["slot"]), None)
    if slot is None:
        raise fail("REFERENCE_INVALID")
    if not mediated(slot):
        raise fail("UNSUPPORTED_RELATION")
    if event["clock"]["status"] != "AVAILABLE":
        raise fail("CLOCK_INVALID")
    if any(row["snapshot"]["slot"] == slot["slot"] for row in core.get("key_history", [])):
        raise fail("DEFINITION_CONFLICT")
    coverage = payload["coverage"]
    guarantee = slot["uniqueness"]
    if coverage["slot"] != slot["slot"] or any(coverage[name] != guarantee[name] for name in ("provider", "source", "record_type", "history_scope", "cutover_id")) or coverage["as_of"] != event["clock"]["instant"] or not valid_instant(coverage["as_of"]):
        raise fail("BINDING_MISMATCH")
    claims = payload["claims"]
    order = [(row["key_digest"].encode(), canonical(row)) for row in claims]
    if order != sorted(order) or len(order) != len(set(order)):
        raise fail("INPUT_INVALID")
    types = {row["id"]: row for row in slot["types"]}
    authenticated = {("EXCLUSIVE_COVERAGE", digest("exclusive-history-coverage", coverage), coverage["provider"], coverage["source"])}
    registry_digest = digest("reservation-registry", core["configuration"])
    for claim in claims:
        native = claim["native_record"]
        request = claim["source_request"]
        provenance = claim["request_provenance"]
        native_digest = digest("exclusive-native-history", native)
        if claim["record_digest"] != native_digest or provenance["native_record_digest"] != native_digest or provenance["source_request_digest"] != digest("exclusive-source-request", request):
            raise fail("DEPENDENCY_MISMATCH")
        if any(native[name] != guarantee[name] for name in ("provider", "source", "record_type")) or any(provenance[name] != guarantee[name] for name in ("provider", "source")):
            raise fail("BINDING_MISMATCH" if any(native[name] != guarantee[name] for name in ("provider", "source", "record_type")) else "DEPENDENCY_MISMATCH")
        if not valid_instant(native["occurred_at"]) or native["occurred_at"] > coverage["as_of"]:
            raise fail("BINDING_MISMATCH")
        fields = native["native_fields"]
        inventory = slot["history_record_fields"]["held" if native["state"] == "HELD" else "consumed"]
        if [row["name"] for row in fields] != [row["name"] for row in inventory] or any(row["value"]["type_ref"] != field["type_ref"] for row, field in zip(fields, inventory)):
            raise fail("BINDING_MISMATCH")
        if any(not authority._typed_value_valid(row["value"], types) for row in fields):
            raise fail("TYPE_INVALID")
        values = {row["name"]: row["value"] for row in fields}
        key = []
        for selector in slot["history_projection"]:
            if selector["kind"] == "NATIVE_FIELD":
                value = values[selector["field"]]
            elif selector["kind"] == "LITERAL":
                value = selector["value"]
            else:
                source = request if selector["kind"] == "SOURCE_REQUEST" else native
                value = {"type_ref": selector["type_ref"], "value": source[selector["member"]]}
            key.append(copy.deepcopy(value))
        expected_owner = {"kind": "WORK_OCCURRENCE", **native["work_occurrence"]} if native["work_occurrence"] is not None else {"kind": "NATIVE_HISTORY", "provider": native["provider"], "source": native["source"], "record_id": native["record_id"], "record_digest": native_digest}
        if claim["key"] != key or claim["owner"] != expected_owner or claim["slot"] != slot["slot"] or claim["namespace"] != slot["namespace"] or claim["status"] != native["state"] or claim["acquisition_event"] != event["id"] or claim["settlement_evidence"] != (native["record_id"] if native["state"] == "CONSUMED" else None):
            raise fail("BINDING_MISMATCH")
        expected_key = digest("exclusive-key", {"registry": registry_digest, "slot": slot["slot"], "namespace": slot["namespace"], "key": key})
        if claim["key_digest"] != expected_key:
            raise fail("DEPENDENCY_MISMATCH")
        authenticated.add(("EXCLUSIVE_NATIVE_HISTORY", native_digest, native["provider"], native["source"]))
        authenticated.add(("EXCLUSIVE_REQUEST_PROVENANCE", digest("exclusive-request-provenance", provenance), provenance["provider"], provenance["source"]))
    if len({row["key_digest"] for row in claims}) != len(claims):
        raise fail("OCCURRENCE_CONFLICT")
    registry._validate_admin(event, host, core["configuration"], authenticated)
    encoded = [registry.canon(row) for row in host["authenticated_records"]]
    if encoded != sorted(set(encoded)):
        raise fail("INPUT_INVALID")
    if not coverage["complete"] or not coverage["exclusive_writers"]:
        return "WITHHELD", None, [], None, ["EXCLUSIVE_HISTORY_UNAVAILABLE"]
    occupied = {row["key_digest"] for row in core.get("exclusive_keys", [])}
    if occupied & {row["key_digest"] for row in claims}:
        raise fail("OCCURRENCE_CONFLICT")
    if len(core.get("exclusive_keys", [])) + len(claims) > 4096:
        raise fail("LIMIT_EXCEEDED")
    snapshot = {"registry_digest": registry_digest, "event_id": event["id"], "slot": slot["slot"], "coverage": copy.deepcopy(coverage), "claims": copy.deepcopy(claims)}
    core["key_history"].append({"snapshot_digest": digest("exclusive-history-snapshot", snapshot), "snapshot": snapshot})
    core["key_history"].sort(key=lambda row: row["snapshot"]["slot"].encode())
    members = ("key_digest", "slot", "namespace", "key", "owner", "acquisition_event", "status", "settlement_evidence")
    core["exclusive_keys"].extend({name: copy.deepcopy(row[name]) for name in members} for row in claims)
    core["exclusive_keys"].sort(key=lambda row: row["key_digest"].encode())
    return "SEEDED_EXCLUSIVE", None, [], None, []
