"""Independent key-history scaffold; this is not the complete equipment specimen."""

from __future__ import annotations

import copy
import base64
from typing import Any

from corpus_common import canonical_bytes, digest
from reservation_fixture import fixture, host_and_event, request, reservation_record, transition, zero_state


ISSUER = "NPO-7"
PROVIDER = "card-provider"
SOURCE = "card-system"
CONSTANTS = {"provider": PROVIDER, "source": SOURCE, "issuer": ISSUER,
    "request_id": "RTS-REQ-417", "work_order": "WO-7304", "inspection": "IN-552", "approval": "AP-091"}
SHAPES = {
    "approval-use": ["provider", "source", "approval"],
    "inspection-use": ["issuer", "asset", "inspection"],
    "request-use": ["issuer", "request_id"],
    "tuple-use": ["provider", "source", "asset", "work_order", "inspection", "approval"],
    "work-order-use": ["issuer", "asset", "work_order"],
}


def value(raw: Any, type_ref: str = "IDENTITY") -> dict[str, Any]:
    return {"type_ref": type_ref, "value": raw}


def history_fixture() -> dict[str, Any]:
    keys = []
    for slot, shape in SHAPES.items():
        projection = [{"field": "card_id", "type_ref": "IDENTITY", "key_field": name}
            if name == "asset" else {"key_field": name, "value": value(CONSTANTS[name])} for name in shape]
        keys.append({"id": slot + "-key", "slot": slot, "namespace": "equipment-history-scaffold",
            "projection": projection, "retention": "RETAIN_UNTIL_SETTLED_OR_AUTHORIZED_RELEASE"})
    facts = fixture(exclusive_keys=keys)
    facts["configuration"]["slots"] = []
    fields = [{"name": name, "type_ref": "amount" if name == "amount" else "IDENTITY"}
        for name in sorted(["amount", "approval", "asset", "beneficiary", "card_id", "inspection", "work_order"])]
    for slot in facts["configuration"]["exclusive_slots"]:
        shape = SHAPES[slot["slot"]]
        slot.update({
            "key_shape": [{"name": name, "type_ref": "IDENTITY"} for name in shape],
            "types": copy.deepcopy(facts["authority_a"]["work_class"]["types"]),
            "history_record_fields": {"held": copy.deepcopy(fields), "consumed": copy.deepcopy(fields)},
            "history_projection": [{"key_field": name,
                "kind": "RECORD" if name in {"provider", "source"} else "SOURCE_REQUEST" if name in {"issuer", "request_id"} else "NATIVE_FIELD",
                **({"member": name} if name in {"provider", "source", "issuer", "request_id"} else {"field": name}),
                "type_ref": "IDENTITY"} for name in shape],
            "uniqueness": {"kind": "EXCLUSIVE_MEDIATOR_SEEDED", "provider": PROVIDER, "source": SOURCE,
                "record_type": "synthetic-card-history", "history_scope": slot["slot"] + "-complete-uses",
                "cutover_id": "cutover-1", "evidence_ref": "synthetic-all-writer-premise"},
        })
    return facts


def history_state(facts: dict[str, Any]) -> dict[str, Any]:
    state = zero_state(facts)
    state["core"]["key_history"] = []
    return state


def selected_slot(facts: dict[str, Any], slot: str) -> dict[str, Any]:
    return next(row for row in facts["configuration"]["exclusive_slots"] if row["slot"] == slot)


def project_history(slot: dict[str, Any], native_record: dict[str, Any], source_request: dict[str, Any]) -> list[dict[str, Any]]:
    fields = {row["name"]: row["value"] for row in native_record["native_fields"]}
    projected = []
    for row in slot["history_projection"]:
        if row["kind"] == "NATIVE_FIELD":
            projected.append(copy.deepcopy(fields[row["field"]]))
        elif row["kind"] == "SOURCE_REQUEST":
            projected.append(value(source_request[row["member"]], row["type_ref"]))
        elif row["kind"] == "RECORD":
            projected.append(value(native_record[row["member"]], row["type_ref"]))
        else:
            projected.append(copy.deepcopy(row["value"]))
    return projected


def historical_claim(
    facts: dict[str, Any], slot: str, event_id: str, *, status: str = "CONSUMED",
    asset: str = "older-asset", approval: str = "AP-090", work_order: str = "WO-7303",
    inspection: str = "IN-551", request_id: str = "RTS-REQ-416",
    work_occurrence: dict[str, str] | None = None,
) -> dict[str, Any]:
    configured = selected_slot(facts, slot)
    fields = {"amount": value("150", "amount"), "approval": value(approval), "asset": value(asset),
        "beneficiary": value("employee-7"), "card_id": value(asset), "inspection": value(inspection), "work_order": value(work_order)}
    native_record = {"provider": PROVIDER, "source": SOURCE, "record_type": "synthetic-card-history",
        "record_id": "native-" + request_id, "revision": "native-revision-1", "occurred_at": "2026-09-09T04:00:00Z",
        "state": status, "native_fields": [{"name": name, "value": fields[name]} for name in sorted(fields)],
        "work_occurrence": copy.deepcopy(work_occurrence), "evidence_ref": "native-history-" + request_id}
    record_digest = digest("exclusive-native-history", native_record)
    source_request = {"issuer": ISSUER, "provider": "request-provider", "source": "maintenance-requests", "request_id": request_id}
    provenance = {"provider": PROVIDER, "source": SOURCE, "native_record_digest": record_digest,
        "source_request_digest": digest("exclusive-source-request", source_request),
        "evidence_ref": "linked-original-request-" + request_id,
        "provenance_digest": digest("source-observation-provenance", {"native_record_digest": record_digest, "source_request": source_request})}
    owner = {"kind": "WORK_OCCURRENCE", **copy.deepcopy(work_occurrence)} if work_occurrence is not None else {
        "kind": "NATIVE_HISTORY", "provider": PROVIDER, "source": SOURCE,
        "record_id": native_record["record_id"], "record_digest": record_digest}
    key = project_history(configured, native_record, source_request)
    return {"slot": slot, "namespace": configured["namespace"], "key": key,
        "key_digest": digest("exclusive-key", {"registry": digest("reservation-registry", facts["configuration"]),
            "slot": slot, "namespace": configured["namespace"], "key": key}),
        "owner": owner, "acquisition_event": event_id, "status": status,
        "settlement_evidence": native_record["record_id"] if status == "CONSUMED" else None,
        "native_record": native_record, "record_digest": record_digest,
        "source_request": source_request, "request_provenance": provenance}


def seed_request(facts: dict[str, Any], state: dict[str, Any], slot: str, claims: list[dict[str, Any]], event_id: str) -> dict[str, Any]:
    configured = selected_slot(facts, slot)
    uniqueness = configured["uniqueness"]
    coverage = {key: copy.deepcopy(uniqueness[key]) for key in ("provider", "source", "record_type", "history_scope", "cutover_id")}
    coverage.update({"slot": slot, "as_of": facts["clock"]["instant"], "revision": "coverage-revision-1",
        "complete": True, "exclusive_writers": True, "evidence_ref": "complete-cutover-history-" + slot,
        "provenance_digest": digest("source-observation-provenance", {"slot": slot, "cutover_id": uniqueness["cutover_id"]})})
    payload = {"slot": slot, "coverage": coverage, "claims": copy.deepcopy(claims)}
    for claim in payload["claims"]:
        claim["acquisition_event"] = event_id
    payload["claims"].sort(key=lambda row: (row["key_digest"].encode("utf-8"), canonical_bytes(row)))
    event, host = host_and_event(facts, "SEED_EXCLUSIVE", event_id, state["core"]["revision"], payload, administration=True)
    host["administration_bases"][0]["operations"].append("SEED_EXCLUSIVE")
    host["authenticated_records"].append({"kind": "EXCLUSIVE_COVERAGE", "record_digest": digest("exclusive-history-coverage", coverage),
        "provider": coverage["provider"], "source": coverage["source"]})
    for claim in payload["claims"]:
        for name, kind, domain in (("native_record", "EXCLUSIVE_NATIVE_HISTORY", "exclusive-native-history"),
            ("request_provenance", "EXCLUSIVE_REQUEST_PROVENANCE", "exclusive-request-provenance")):
            body = claim[name]
            host["authenticated_records"].append({"kind": kind, "record_digest": digest(domain, body),
                "provider": body["provider"], "source": body["source"]})
    host["authenticated_records"] = sorted({canonical_bytes(row): row for row in host["authenticated_records"]}.values(), key=canonical_bytes)
    return request(state, event, host)


def snapshot(facts: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {"registry_digest": digest("reservation-registry", facts["configuration"]),
        "event_id": event["id"], **copy.deepcopy(event["payload"])}


def rebind_seed(facts: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    """Bind administrative and host evidence to a deliberately changed full payload."""
    event = supplied["event"]
    rebound = seed_request(facts, supplied["state"], event["payload"]["slot"], event["payload"]["claims"], event["id"])
    rebound["event"]["payload"]["coverage"] = copy.deepcopy(event["payload"]["coverage"])
    act = rebound["event"]["administration"]["act"]
    subject = {"registry_digest": digest("reservation-registry", facts["configuration"]), "event_id": event["id"],
        "expected_revision": event["expected_revision"], "kind": "SEED_EXCLUSIVE", "clock": event["clock"],
        "payload": rebound["event"]["payload"]}
    act["subject_digest"] = digest("reservation-administration-subject", subject)
    returned = rebound["event"]["administration"]["returned"]
    returned["act_digest"] = digest("reservation-administration-act", act)
    returned["act_bytes_base64"] = base64.b64encode(canonical_bytes(act)).decode("ascii")
    for row in rebound["host_evidence"]["authenticated_records"]:
        if row["kind"] == "ADMIN_RETURN":
            row["record_digest"] = digest("reservation-administration-return", returned)
        elif row["kind"] == "EXCLUSIVE_COVERAGE":
            row["record_digest"] = digest("exclusive-history-coverage", event["payload"]["coverage"])
    rebound["host_evidence"]["authenticated_records"].sort(key=canonical_bytes)
    return rebound


def seed_result(facts: dict[str, Any], supplied: dict[str, Any], *, usable: bool = True) -> dict[str, Any]:
    state, event, host = (supplied[key] for key in ("state", "event", "host_evidence"))
    core = copy.deepcopy(state["core"])
    if usable:
        body = snapshot(facts, event)
        core["key_history"].append({"snapshot_digest": digest("exclusive-history-snapshot", body), "snapshot": body})
        core["key_history"].sort(key=lambda row: row["snapshot"]["slot"].encode("utf-8"))
        core["exclusive_keys"].extend({key: copy.deepcopy(claim[key]) for key in (
            "key_digest", "slot", "namespace", "key", "owner", "acquisition_event", "status", "settlement_evidence",
        )} for claim in event["payload"]["claims"])
        core["exclusive_keys"].sort(key=lambda row: row["key_digest"].encode("utf-8"))
    return transition(state, event, host, core, "SEEDED_EXCLUSIVE" if usable else "WITHHELD",
        reasons=[] if usable else ["EXCLUSIVE_HISTORY_UNAVAILABLE"])


def seeded_all(facts: dict[str, Any], *, historical: bool = False) -> dict[str, Any]:
    state = history_state(facts)
    for slot in SHAPES:
        event_id = "seed-" + slot
        claims = [historical_claim(facts, slot, event_id)] if historical else []
        supplied = seed_request(facts, state, slot, claims, event_id)
        state = seed_result(facts, supplied)["state"]
    return state


def reserve_request(facts: dict[str, Any], state: dict[str, Any], event_id: str) -> dict[str, Any]:
    event, host = host_and_event(facts, "RESERVE", event_id, state["core"]["revision"], {
        "authority": facts["authority_a"], "histories": [],
        "exclusive_keys": copy.deepcopy(facts["authority_a_result"]["required_exclusive_keys"]),
    }, administration=False)
    return request(state, event, host)


def reserve_result(facts: dict[str, Any], supplied: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    state, event, host = (supplied[key] for key in ("state", "event", "host_evidence"))
    core = copy.deepcopy(state["core"])
    if reason is None:
        record = reservation_record(facts, "authority_a", event["id"])
        core["reservations"].append(record)
        proposal = facts["authority_a"]["proposal"]
        owner = {"kind": "WORK_OCCURRENCE", "work_class": proposal["work_class"],
            "instance_id": proposal["instance"], "occurrence_id": proposal["occurrence"]}
        for claim in record["exclusive_keys"]:
            core["exclusive_keys"].append({**copy.deepcopy(claim), "owner": owner,
                "acquisition_event": event["id"], "status": "HELD", "settlement_evidence": None})
        core["exclusive_keys"].sort(key=lambda row: row["key_digest"].encode("utf-8"))
    return transition(state, event, host, core, "RESERVED" if reason is None else "WITHHELD",
        reservation_id=event["id"] if reason is None else None,
        authority_result=facts["authority_a_result"], reasons=[] if reason is None else [reason])
