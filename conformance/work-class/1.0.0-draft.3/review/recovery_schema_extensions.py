"""Closed draft 3 carriers for explicit evidence disposition and retained exposure."""

from __future__ import annotations

from copy import deepcopy


BASE = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/"
VERSION = "seampoint.work-class/1.0.0-draft.3/"
ID = {"$ref": BASE + "aggregate.schema.json#/$defs/id"}
DIGEST = {"$ref": BASE + "aggregate.schema.json#/$defs/digest"}
NATURAL = {"$ref": BASE + "aggregate.schema.json#/$defs/natural"}
VALUE = {"$ref": BASE + "aggregate.schema.json#/$defs/value"}
INSTANT = {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}
DECIMAL = {"type": "string", "pattern": r"^(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$"}
RESULTS = ["ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT", "ACCEPT_UNRESOLVED", "LEAVE_UNRESOLVED"]
OPERATIONS = ["ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT", "RELEASE_DISPUTED_EXPOSURE", "ISSUE_POLICY", "REVOKE_POLICY"]


def ref(name: str) -> dict:
    return {"$ref": "#/$defs/" + name}


def reservation_ref(name: str) -> dict:
    return {"$ref": BASE + "reservation.schema.json#/$defs/" + name}


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required if required is not None else list(properties), "additionalProperties": False}


def arr(item: dict, minimum: int = 0, maximum: int | None = None, unique: bool = False) -> dict:
    result = {"type": "array", "items": item, "minItems": minimum}
    if maximum is not None:
        result["maxItems"] = maximum
    if unique:
        result["uniqueItems"] = True
    return result


def nullable(value: dict) -> dict:
    return {"oneOf": [value, {"type": "null"}]}


def extend_recovery_schemas(work: dict, lifecycle: dict, reservation: dict) -> None:
    defs = reservation["$defs"]
    defs["recoveryReservationTarget"] = obj({"kind": {"const": "RESERVATION"}, "registry_digest": DIGEST, "reservation": ID})
    defs["recoveryWorkTarget"] = obj({"kind": {"const": "WORK_OUTCOME"}, "instance_id": ID, "occurrence_id": DIGEST, "outcome_digest": DIGEST})
    defs["recoveryTarget"] = {"oneOf": [ref("recoveryReservationTarget"), ref("recoveryWorkTarget")]}
    defs["recoveryConfiguration"] = obj({
        "provider": ID, "source": ID, "controller_role": ID, "policy_owner_role": ID,
        "policy_families": arr(ID, 0, 64, True), "negative_prerequisite_behavior": {"const": "STOP"},
        "exception_profiles": arr({"const": "MONETARY_DUPLICATE_SEND"}, 0, 1, True),
    })
    defs["configuration"]["properties"]["recovery"] = ref("recoveryConfiguration")
    work["$defs"]["definition"]["properties"]["recovery"] = reservation_ref("recoveryConfiguration")
    defs["recoveryBasis"] = obj({
        "id": ID, "actor": ID, "principal": ID, "role": ID, "kind": {"const": "HUMAN"}, "scope_digest": DIGEST,
        "operations": arr({"enum": OPERATIONS}, 1, 5, True),
        "validity": {"$ref": BASE + "authority.schema.json#/$defs/interval"}, "at": INSTANT, "revoked": {"type": "boolean"},
        "provider": ID, "source": ID, "evidence_ref": ID,
    })
    defs["recoveryAct"] = deepcopy(defs["adminAct"])
    defs["recoveryAct"]["properties"]["kind"] = {"enum": OPERATIONS}
    defs["recoveryReturn"] = deepcopy(defs["adminReturn"])
    defs["recoveryAuthorization"] = obj({"act": ref("recoveryAct"), "returned": ref("recoveryReturn")})
    defs["recoveryAuthenticated"] = obj({
        "kind": {"enum": ["RECOVERY_EVIDENCE", "RECOVERY_RETURN"]}, "record_digest": DIGEST, "provider": ID, "source": ID,
    })
    defs["recoveryPendingEvidence"] = obj({"target": ref("recoveryTarget"), "record_digest": DIGEST})
    defs["recoveryHost"] = obj({
        "caller": ID, "recovery_bases": arr(ref("recoveryBasis"), 0, 64),
        "authenticated_records": arr(ref("recoveryAuthenticated"), 0, 4096),
        "pending_evidence": arr(ref("recoveryPendingEvidence"), 0, 4096),
    })
    defs["host"]["properties"]["recovery"] = ref("recoveryHost")
    defs["recoveryAttempt"] = obj({
        "id": ID, "attempt_digest": DIGEST, "executor": ID, "connector": ID, "request_digest": DIGEST,
        "maximum_executions": {"type": "string", "pattern": r"^[1-9][0-9]*$"},
        "effect_ids": arr(ID, 0, 4096, True), "no_effect": {"type": "boolean"},
    })
    defs["recoveryEvidence"] = obj({
        "id": ID, "provider": ID, "source": ID, "record_type": {"const": "RECOVERY_ADJUDICATION"},
        "record_digest": DIGEST, "evidence_ref": ID, "provider_revision": NATURAL,
        "target": ref("recoveryTarget"), "request": ref("nativeRequest"),
        "covered_evidence_digests": arr(DIGEST, 0, 4096, True), "superseded_evidence_digests": arr(DIGEST, 0, 4096, True),
        "attempts": arr(ref("recoveryAttempt"), 1, 4096),
        "conclusion": {"enum": ["EFFECT_ESTABLISHED", "NO_EFFECT_ESTABLISHED", "UNRESOLVED"]},
        "native_outcomes": arr({"oneOf": [ref("native"), {"$ref": BASE + "lifecycle.schema.json#/$defs/nativeEvidence"}]}, 0, 4096),
        "rules_out_past_and_future_effects": {"type": "boolean"}, "complete_attempt_inventory": {"type": "boolean"},
    })
    defs["recoveryPolicyScope"] = obj({
        "principal": ID, "registry_digest": DIGEST, "budget_anchors": arr(ID, 1, 64, True),
        "work_classes": arr(ID, 1, 64, True), "executors": arr(ID, 1, 64, True), "connectors": arr(ID, 1, 64, True),
        "unit": {"const": "USD"}, "profile": {"const": "MONETARY_DUPLICATE_SEND"}, "window_seconds": {"const": "86400"},
    })
    defs["recoveryPolicy"] = obj({
        "id": ID, "family": ID, "version": NATURAL, "scope": ref("recoveryPolicyScope"),
        "per_incident_limit": DECIMAL, "cumulative_limit": DECIMAL,
        "validity": obj({"valid_from": INSTANT, "valid_until": INSTANT}),
    })
    defs["recoveryPolicyPayload"] = obj({
        "action": {"enum": ["ISSUE", "REVOKE"]}, "family": ID, "policy": nullable(ref("recoveryPolicy")),
        "policy_digest": nullable(DIGEST), "supersedes": nullable(DIGEST), "authorization": ref("recoveryAuthorization"),
    })
    defs["recoveryDisposePayload"] = obj({
        "target": ref("recoveryReservationTarget"), "requested_result": {"enum": RESULTS}, "evidence": ref("recoveryEvidence"),
        "controller": nullable(ref("recoveryAuthorization")), "policy_digest": nullable(DIGEST), "supersedes": nullable(DIGEST),
        "histories": arr(ref("history"), 0, 64),
    })
    for name, kind, payload in [("recoveryPolicyEvent", "RECOVERY_POLICY", "recoveryPolicyPayload"), ("recoveryDisposeEvent", "DISPOSE", "recoveryDisposePayload")]:
        defs[name] = obj({
            "id": ID, "expected_revision": NATURAL, "kind": {"const": kind},
            "clock": {"$ref": BASE + "authority.schema.json#/$defs/clock"}, "payload": ref(payload), "administration": {"type": "null"},
        })
        if ref(name) not in defs["event"]["oneOf"]:
            defs["event"]["oneOf"].append(ref(name))
    defs["recoveryPolicyRecord"] = obj({
        "policy": ref("recoveryPolicy"), "policy_digest": DIGEST, "revoked": {"type": "boolean"}, "event_digest": DIGEST,
        "authorization": ref("recoveryAuthorization"),
    })
    defs["recoveryDisposition"] = obj({
        "id": DIGEST, "incident_digest": DIGEST, "generation_digest": DIGEST, "acceptance_basis_digest": nullable(DIGEST),
        "target": ref("recoveryTarget"), "result": {"enum": RESULTS}, "evidence": ref("recoveryEvidence"),
        "policy_digest": nullable(DIGEST), "controller": nullable(ref("recoveryAuthorization")), "supersedes": nullable(DIGEST),
        "event_digest": DIGEST, "accepted_at": INSTANT,
        "source_event": {"oneOf": [ref("recoveryDisposeEvent"), {"$ref": BASE + "lifecycle.schema.json#/$defs/recoveryDisposeEvent"}]},
    })
    defs["recoveryContingent"] = obj({
        "id": DIGEST, "disposition_digest": DIGEST, "reservation": ID, "attempt_id": ID, "execution_index": NATURAL,
        "anchor": ID, "mapping": ID, "occurrence": ID, "key": arr(VALUE, 1, 64), "value": VALUE,
    })
    defs["recoveryAllowance"] = obj({
        "acceptance_basis_digest": DIGEST, "policy_family": ID, "budget": ID,
        "actor_kind": {"enum": ["BUDGET", "EXECUTOR", "CONNECTOR"]}, "actor": ID, "amount": DECIMAL, "accepted_at": INSTANT,
    })
    defs["recoveryState"] = obj({
        "policies": arr(ref("recoveryPolicyRecord")), "dispositions": arr(ref("recoveryDisposition")),
        "contingent": arr(ref("recoveryContingent"), 0, 4096), "allowances": arr(ref("recoveryAllowance")),
    })
    defs["core"]["properties"]["recovery"] = ref("recoveryState")
    decisions = defs["receipt"]["properties"]["decision"]["enum"]
    for decision in ["POLICY_RECORDED", "DISPOSITION_RECORDED", "DISPOSITION_REUSED"]:
        if decision not in decisions:
            decisions.append(decision)
    defs["receipt"]["properties"]["recovery_disposition_digest"] = DIGEST

    life = lifecycle["$defs"]
    life["recoveryRegistrySelection"] = obj({"state": reservation_ref("state"), "state_digest": DIGEST, "host_evidence": reservation_ref("host")})
    common = {
        "schema": {"const": VERSION + "runtime-event"}, "event_id": ID, "instance_id": ID,
        "expected_state_revision": NATURAL, "expected_state_digest": DIGEST,
    }
    clocks = {"clock_revision": ref("natural"), "activation_clocks": arr(ref("clockAvailable"), 0, 256)}
    life["recoveryDisposeEvent"] = obj(common | {
        "kind": {"const": "DISPOSE"}, "target": reservation_ref("recoveryWorkTarget"),
        "requested_result": {"enum": ["ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT", "LEAVE_UNRESOLVED"]},
        "evidence": reservation_ref("recoveryEvidence"), "controller": nullable(reservation_ref("recoveryAuthorization")),
        "policy_digest": {"type": "null"}, "supersedes": nullable(DIGEST),
    } | clocks)
    life["recoveryApplyEvent"] = obj(common | {
        "kind": {"const": "APPLY_DISPOSITION"}, "target": reservation_ref("recoveryReservationTarget"),
        "disposition_digest": DIGEST, "registry": ref("recoveryRegistrySelection"),
    } | clocks)
    for name in ["recoveryDisposeEvent", "recoveryApplyEvent"]:
        if ref(name) not in life["event"]["oneOf"]:
            life["event"]["oneOf"].append(ref(name))
    projection_keys = ["status", "active", "completed", "obligations", "deadlines", "total_activations", "total_actuations", "step_counters", "fanout_passes"]
    life["recoveryProjection"] = obj({key: deepcopy(life["state"]["properties"][key]) for key in projection_keys})
    life["recoveryApplication"] = obj({
        "event": {"oneOf": [ref("recoveryDisposeEvent"), ref("recoveryApplyEvent")]},
        "host_evidence": reservation_ref("recoveryHost"), "disposition": reservation_ref("recoveryDisposition"),
        "before_projection": ref("recoveryProjection"), "after_projection": ref("recoveryProjection"),
    })
    life["recoveryApplication"]["properties"]["registry_selections"] = arr(ref("recoveryRegistrySelection"), 1, 1)
    life["state"]["properties"]["recovery_records"] = arr(ref("recoveryApplication"))
    life["stepInput"]["properties"]["recovery_host"] = reservation_ref("recoveryHost")
    life["stepInput"]["properties"]["recovery_registries"] = arr(ref("recoveryRegistrySelection"), 0, 1)
    receipt = life["decisionReceipt"]["properties"]
    for kind in ["DISPOSE", "APPLY_DISPOSITION"]:
        if kind not in receipt["event_kind"]["enum"]:
            receipt["event_kind"]["enum"].append(kind)
    for result in ["DISPOSITION_RECORDED", "DISPOSITION_APPLIED"]:
        if result not in receipt["disposition"]["enum"]:
            receipt["disposition"]["enum"].append(result)
    receipt["recovery_disposition_digest"] = DIGEST
