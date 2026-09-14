#!/usr/bin/env python3
"""Build the supplier-payment specimen from the draft-2 normative contract.

This is a fixed specimen constructor, not a general evaluator. It was written
without consulting either draft-2 implementation or implementation output.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
PIN = "sha256:" + hashlib.sha256(
    (HERE.parents[4] / "library/work-class-specification/1.0.0-draft.2/contract-manifest.json").read_bytes()
).hexdigest()
PREFIX = b"seampoint.work-class/1.0.0-draft.2/"
SCHEMA = "seampoint.work-class/1.0.0-draft.2/"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.2"
PROFILE = "LINEAR"
ROLE = "LINEAR_WORK_RUNTIME"
ORG = "sample-buying-organization"
NOW = "2026-09-11T12:00:00Z"
DEPLOYMENT_AUTHORIZED_AT = "2026-09-11T11:50:00Z"
PERMIT_EXPIRY = "2026-09-11T12:05:00Z"
HISTORY_TIME = "2026-09-11T10:00:00Z"


def key_order(value: str) -> bytes:
    return value.encode("utf-16-be")


def canonical_text(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(canonical_text(row) for row in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            canonical_text(key) + ":" + canonical_text(value[key])
            for key in sorted(value, key=key_order)
        ) + "}"
    raise TypeError(type(value).__name__)


def canonical_bytes(value) -> bytes:
    return canonical_text(value).encode("utf-8")


def digest(kind: str, value) -> str:
    return "sha256:" + hashlib.sha256(PREFIX + kind.encode() + b"\n" + canonical_bytes(value)).hexdigest()


def raw_sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def omit(value: dict, *keys: str) -> dict:
    answer = copy.deepcopy(value)
    for key in keys:
        answer.pop(key, None)
    return answer


def sorted_utf8(values):
    return sorted(values, key=lambda row: row.encode("utf-8") if isinstance(row, str) else canonical_bytes(row))


def write(relative: str, value) -> None:
    path = HERE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def typed(type_ref: str, value: str) -> dict:
    return {"type_ref": type_ref, "value": value}


def field(name: str, type_ref: str, value: str) -> dict:
    return {"name": name, "value": typed(type_ref, value)}


def readback(value):
    lines = []

    def token(text: str) -> str:
        return text.replace("~", "~0").replace("/", "~1")

    def walk(node, pointer: str):
        if isinstance(node, dict):
            if not node:
                lines.append({"path": pointer, "value": canonical_text(node)})
            else:
                for key, child in node.items():
                    walk(child, pointer + "/" + token(key))
        elif isinstance(node, list):
            if not node:
                lines.append({"path": pointer, "value": canonical_text(node)})
            else:
                for index, child in enumerate(node):
                    walk(child, pointer + "/" + str(index))
        else:
            lines.append({"path": pointer, "value": canonical_text(node)})

    walk(value, "")
    return sorted(lines, key=lambda line: line["path"].encode("utf-8"))


def work_state_digest(state: dict) -> str:
    projection = copy.deepcopy(state)
    for replay in projection["replays"]:
        replay.pop("transaction_digest")
    return digest("work-state", projection)


def work_transition(before: dict, event: dict, *, disposition: str, reasons: list[str], details: list[dict],
                    permit: dict | None, budget_results: list[dict], authority_result_digest: str | None,
                    reservation_receipt_digests: list[str], mutate) -> tuple[dict, dict]:
    event_digest = digest("runtime-event", event)
    after = copy.deepcopy(before)
    after["revision"] = str(int(before["revision"]) + 1)
    mutate(after, event_digest)
    core = copy.deepcopy(after)
    core["receipts"] = []
    core["replays"] = []
    core_digest = digest("work-state-core", core)
    receipt = {
        "schema": SCHEMA + "decision-receipt",
        "decision_id": "sha256:" + "0" * 64,
        "instance_id": event["instance_id"],
        "sequence": after["revision"],
        "event_id": event["event_id"],
        "event_digest": event_digest,
        "event_kind": event["kind"],
        "disposition": disposition,
        "reason_codes": sorted_utf8(reasons),
        "details": details,
        "permit_digest": permit["permit_id"] if permit else (event.get("permit") or {}).get("permit_id"),
        "authority_result_digest": authority_result_digest,
        "reservation_receipt_digests": reservation_receipt_digests,
        "state_before_digest": work_state_digest(before),
        "state_after_core_digest": core_digest,
    }
    receipt["decision_id"] = digest("decision-receipt", omit(receipt, "decision_id"))
    transaction_digest = digest("lifecycle-transaction", {
        "state_before_digest": receipt["state_before_digest"],
        "event_digest": event_digest,
        "decision_receipt_digest": receipt["decision_id"],
        "state_after_core_digest": core_digest,
        "budget_results": budget_results,
    })
    replay = {
        "event_id": event["event_id"],
        "event_digest": event_digest,
        "decision": receipt,
        "decision_receipt_digest": receipt["decision_id"],
        "permit": permit,
        "budget_results": budget_results,
        "transition_state_digest": core_digest,
        "transaction_digest": transaction_digest,
    }
    after["receipts"].append(receipt)
    after["replays"].append(replay)
    after["replays"].sort(key=lambda row: row["event_id"].encode("utf-8"))
    state_digest = work_state_digest(after)
    return after, {
        "status": "STEP",
        "profile": PROFILE,
        "role": ROLE,
        "decision": receipt,
        "decision_digest": receipt["decision_id"],
        "permit": permit,
        "budget_results": budget_results,
        "state": after,
        "state_digest": state_digest,
        "transition_state_digest": core_digest,
        "transaction_digest": transaction_digest,
        "replay": False,
    }


def reservation_state_digest(state: dict) -> str:
    return digest("reservation-state", state)


def reservation_transition(before: dict, event: dict, host: dict, *, decision: str,
                           reservation_id: str | None, budgets: list[dict], authority_result,
                           reasons: list[str], mutate) -> tuple[dict, dict]:
    event_digest = digest("reservation-event", event)
    after = copy.deepcopy(before)
    after["core"]["revision"] = str(int(before["core"]["revision"]) + 1)
    if event["clock"]["status"] == "AVAILABLE":
        after["core"]["last_clock"] = event["clock"]["instant"]
    mutate(after)
    core_digest = digest("reservation-core", after["core"])
    receipt = {
        "event_digest": event_digest,
        "prior_state_digest": reservation_state_digest(before),
        "revision": after["core"]["revision"],
        "next_core_digest": core_digest,
        "decision": decision,
        "reservation": reservation_id,
        "budgets": budgets,
        "authority_result": authority_result,
        "reasons": sorted_utf8(reasons),
    }
    after["receipts"].append({"event": event, "host_evidence": host, "receipt": receipt})
    result = {
        "status": "TRANSITION",
        "receipt": receipt,
        "receipt_digest": digest("reservation-receipt", receipt),
        "state": after,
        "state_digest": reservation_state_digest(after),
        "replay": False,
    }
    return after, result


def occurrence(definition_digest: str, instance_id: str, step_id: str, ordinal: str,
               predecessors: list[str]) -> dict:
    subject = {
        "specification_pin": PIN,
        "work_class_digest": definition_digest,
        "instance_id": instance_id,
        "step_id": step_id,
        "ordinal": ordinal,
        "predecessor_occurrence_ids": sorted_utf8(predecessors),
        "enclosing": [],
        "object_key": None,
    }
    return {"occurrence_id": digest("occurrence", subject), **subject}


def build_authority(authority_source: dict, authority_work_class: dict, *, instance_id: str,
                    occurrence_row: dict, step_id: str, envelope_id: str, executor_id: str,
                    executor_role: str, credential_kind: str, gate_kind: str, gate_actor: str,
                    gate_role: str, subject_fields: list[str], resource_fields: list[str],
                    proposal_fields: list[dict], required_budgets: list[str], revoked: bool = False,
                    expired: bool = False) -> dict:
    step = next(row for row in authority_work_class["steps"] if row["id"] == step_id)
    source_digest = digest("authority-source", authority_source)
    work_class_digest = digest("authority-work-class", authority_work_class)
    bindings = []
    subject_selectors = []
    resource_selectors = []
    for name in subject_fields + resource_fields:
        declaration = next(row for row in step["fields"] if row["name"] == name)
        binding_id = f"{step_id}-{name}-binding"
        bindings.append({"id": binding_id, "step": step_id, "field": name, "type_ref": declaration["type_ref"]})
        selector = {"kind": "BINDING", "binding": binding_id}
        (subject_selectors if name in subject_fields else resource_selectors).append(selector)
    bindings.sort(key=lambda row: row["id"].encode())
    subject_selectors = sorted_utf8(subject_selectors)
    resource_selectors = sorted_utf8(resource_selectors)
    criterion_id = f"{step_id}-criterion"
    per_action = []
    if not required_budgets:
        per_action = [{
            "id": f"{step_id}-one-action",
            "step": step_id,
            "field": "request_count",
            "operator": "LTE",
            "bound": typed("t.count", "1"),
        }]
    envelope = {
        "schema": SCHEMA + "authority-envelope",
        "id": envelope_id,
        "source_digest": source_digest,
        "work_class_digest": work_class_digest,
        "source_obligations": [row["id"] for row in authority_source["obligations"]],
        "principal": ORG,
        "grantor_role": f"{step_id}-policy-owner",
        "executor_role": executor_role,
        "attester_role": "organizational-attester",
        "grant_ref": f"{step_id}-grant",
        "clock_source": "governance-clock",
        "bindings": bindings,
        "scope": {"id": f"{step_id}-scope", "subjects": subject_selectors, "resources": resource_selectors},
        "operations": [{"step": step_id, "operation": step["operation"], "interface": step["interface"]}],
        "limits": {"per_action": per_action, "shared_budgets": required_budgets},
        "conditions": [{"id": f"{step_id}-enabled", "step": step_id, "predicate": {"kind": "BOOLEAN", "value": True}}],
        "enforcement": {
            "mechanisms": ["AUTHORITY_BEFORE_RESERVATION"] if not required_budgets else ["ATOMIC_SHARED_RESERVATION", "AUTHORITY_BEFORE_RESERVATION"],
            "safe_state": "NO_NEW_DISPATCH",
            "out_of_envelope": "REFUSE",
        },
        "escalation": {"kind": "DECLARED_NONE"},
        "revocation": {"provider": "identity-provider", "source": "authority-revocations", "max_age_seconds": "3600"},
        "temporal_validity": {
            "valid_from": "2026-09-01T00:00:00Z",
            "valid_until": "2026-09-11T11:00:00Z" if expired else "2026-10-01T00:00:00Z",
        },
        "gate": {
            "materiality": "MEDIUM" if gate_kind == "VERIFY" else "HIGH",
            "reversibility": "MEDIUM" if gate_kind == "VERIFY" else "NONE",
            "kind": gate_kind,
            "role": gate_role,
            "criteria": [{"id": criterion_id, "step": step_id, "predicate": {"kind": "BOOLEAN", "value": True}}],
        },
        "limitations": [],
    }
    envelope_digest = digest("authority-envelope", envelope)
    executor_occupancy = f"{step_id}-executor-occupancy"
    grantor = f"{step_id}-grantor"
    grantor_occupancy = f"{step_id}-grantor-occupancy"
    gate_occupancy = f"{step_id}-gate-occupancy"
    attester = "organizational-attester-person"
    attester_occupancy = f"{step_id}-attester-occupancy"
    occupancy_specs = [
        (attester_occupancy, attester, "organizational-attester", "HUMAN"),
        (executor_occupancy, executor_id, executor_role, "MACHINE"),
        (gate_occupancy, gate_actor, gate_role, "HUMAN"),
        (grantor_occupancy, grantor, f"{step_id}-policy-owner", "HUMAN"),
    ]
    occupancies = [{
        "id": oid,
        "actor": actor,
        "role": role,
        "principal": ORG,
        "kind": kind,
        "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
        "provider": "identity-provider",
        "evidence_ref": oid + "-evidence",
    } for oid, actor, role, kind in occupancy_specs]
    occupancies.sort(key=lambda row: row["id"].encode())
    capacity_specs = [
        (f"{step_id}-attester-capacity", attester, "organizational-attester", attester_occupancy, ["ORGANISATIONAL_ATTESTATION"]),
        (f"{step_id}-gate-capacity", gate_actor, gate_role, gate_occupancy, ["VERIFY" if gate_kind == "VERIFY" else "INSTANCE_DECISION"]),
        (f"{step_id}-grantor-capacity", grantor, f"{step_id}-policy-owner", grantor_occupancy, ["GRANT"]),
    ]
    root = {
        "schema": SCHEMA + "authority-root",
        "id": f"{step_id}-authority-root",
        "revision": "r1",
        "designator": "sample-authority-office",
        "principal": ORG,
        "source_digest": source_digest,
        "work_class_digest": work_class_digest,
        "envelope_digest": envelope_digest,
        "capacity_ids": sorted_utf8([row[0] for row in capacity_specs]),
        "occupancy_ids": sorted_utf8([row[0] for row in occupancy_specs]),
        "providers": ["identity-provider"],
        "channels": [{
            "id": "authority-return-channel",
            "provider": "identity-provider",
            "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
            "prior_returns_survive_expiry": False,
        }],
        "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
        "revocation": {"provider": "identity-provider", "source": "authority-revocations", "max_age_seconds": "3600"},
        "prior_acts_survive_expiry": False,
        "allow_self_attestation": False,
        "limitations": [],
    }
    root_digest = digest("authority-root", root)
    capacities = [{
        "id": cid,
        "root_digest": root_digest,
        "envelope_digest": envelope_digest,
        "actor": actor,
        "role": role,
        "principal": ORG,
        "occupancy": occupancy_id,
        "act_kinds": act_kinds,
        "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
        "revocation": {"provider": "identity-provider", "source": "authority-revocations", "max_age_seconds": "3600"},
        "reliance": {"kind": "CURRENT_ONLY"},
        "may_self_attest": False,
        "provider": "identity-provider",
        "evidence_ref": cid + "-evidence",
    } for cid, actor, role, occupancy_id, act_kinds in capacity_specs]
    capacities.sort(key=lambda row: row["id"].encode())
    credential = {
        "id": f"{step_id}-executor-credential",
        "actor": executor_id,
        "occupancy": executor_occupancy,
        "kind": credential_kind,
        "step": step_id,
        "operation": step["operation"],
        "interface": step["interface"],
        "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
        "revocation": {"provider": "identity-provider", "source": "authority-revocations", "max_age_seconds": "3600"},
        "provider": "identity-provider",
        "evidence_ref": f"{step_id}-credential-evidence",
    }
    executor = {"actor": executor_id, "role": executor_role, "principal": ORG, "occupancy": executor_occupancy}
    authority_proposal = {
        "schema": SCHEMA + "authority-proposal",
        "work_class_digest": work_class_digest,
        "work_class": authority_work_class["id"],
        "instance": instance_id,
        "occurrence": occurrence_row["occurrence_id"],
        "step": step_id,
        "operation": step["operation"],
        "interface": step["interface"],
        "executor": executor,
        "fields": proposal_fields,
    }
    proposal_digest = digest("authority-proposal", authority_proposal)
    operation_digest = digest("authority-operation", {
        "envelope_digest": envelope_digest,
        "work_class_digest": work_class_digest,
        "proposal_digest": proposal_digest,
    })
    capacity_by_kind = {kind: row for row in capacities for kind in row["act_kinds"]}
    grant = {
        "id": f"{step_id}-grant",
        "kind": "GRANT",
        "actor": grantor,
        "role": f"{step_id}-policy-owner",
        "principal": ORG,
        "occupancy": grantor_occupancy,
        "capacity": capacity_by_kind["GRANT"]["id"],
        "recorder": "authority-recorder",
        "occurred_at": "2026-09-10T09:00:00Z",
        "disposition": "ACCEPT",
        "subject_digest": envelope_digest,
        "attested_actor": None,
        "criteria": [],
    }
    grant_digest = digest("authority-act", grant)
    grant_attestation = {
        "id": f"{step_id}-grant-attestation",
        "kind": "ORGANISATIONAL_ATTESTATION",
        "actor": attester,
        "role": "organizational-attester",
        "principal": ORG,
        "occupancy": attester_occupancy,
        "capacity": capacity_by_kind["ORGANISATIONAL_ATTESTATION"]["id"],
        "recorder": "authority-recorder",
        "occurred_at": "2026-09-10T09:01:00Z",
        "disposition": "ACCEPT",
        "subject_digest": grant_digest,
        "attested_actor": grantor,
        "criteria": [],
    }
    gate_act_kind = "VERIFY" if gate_kind == "VERIFY" else "INSTANCE_DECISION"
    gate_act = {
        "id": f"{step_id}-{gate_act_kind.lower()}-act",
        "kind": gate_act_kind,
        "actor": gate_actor,
        "role": gate_role,
        "principal": ORG,
        "occupancy": gate_occupancy,
        "capacity": capacity_by_kind[gate_act_kind]["id"],
        "recorder": "authority-recorder",
        "occurred_at": "2026-09-11T11:55:00Z",
        "disposition": "ACCEPT",
        "subject_digest": operation_digest,
        "attested_actor": None,
        "criteria": [criterion_id],
    }
    acts = [grant, grant_attestation, gate_act]
    if gate_kind == "DECIDE":
        gate_digest = digest("authority-act", gate_act)
        decision_attestation = {
            "id": f"{step_id}-decision-attestation",
            "kind": "ORGANISATIONAL_ATTESTATION",
            "actor": attester,
            "role": "organizational-attester",
            "principal": ORG,
            "occupancy": attester_occupancy,
            "capacity": capacity_by_kind["ORGANISATIONAL_ATTESTATION"]["id"],
            "recorder": "authority-recorder",
            "occurred_at": "2026-09-11T11:56:00Z",
            "disposition": "ACCEPT",
            "subject_digest": gate_digest,
            "attested_actor": gate_actor,
            "criteria": [],
        }
        acts.append(decision_attestation)
    acts.sort(key=lambda row: digest("authority-act", row).encode())
    returns = []
    for act in acts:
        returns.append({
            "id": f"return-{act['id']}",
            "actor": act["actor"],
            "provider": "identity-provider",
            "channel": "authority-return-channel",
            "act_digest": digest("authority-act", act),
            "act_bytes_base64": base64.b64encode(canonical_bytes(act)).decode(),
            "returned_at": act["occurred_at"],
            "evidence_ref": f"return-{act['id']}-evidence",
        })
    returns.sort(key=lambda row: row["id"].encode())
    query_rows = {}
    for act in acts:
        for subject in [root_digest, digest("authority-capacity", next(row for row in capacities if row["id"] == act["capacity"]))]:
            for at in [act["occurred_at"], NOW]:
                query = {"purpose": "REVOCATION", "subject_digest": subject, "at": at, "provider": "identity-provider", "source": "authority-revocations"}
                query_rows[canonical_text(query)] = query
    for subject in [envelope_digest, digest("authority-credential", credential)]:
        query = {"purpose": "REVOCATION", "subject_digest": subject, "at": NOW, "provider": "identity-provider", "source": "authority-revocations"}
        query_rows[canonical_text(query)] = query
    queries = list(query_rows.values())
    observations = []
    for index, query in enumerate(queries, 1):
        observations.append({
            "query": query,
            "query_digest": digest("authority-query", query),
            "status": "AVAILABLE",
            "as_of": query["at"],
            "revision": f"rev-{index}",
            "revoked": revoked and query["subject_digest"] == envelope_digest and query["at"] == NOW,
            "evidence_ref": f"revocation-evidence-{step_id}-{index}",
        })
    authenticated = []
    for row in occupancies:
        authenticated.append({"kind": "OCCUPANCY", "record_digest": digest("authority-occupancy", row), "provider": row["provider"], "channel": None})
    for row in capacities:
        authenticated.append({"kind": "CAPACITY", "record_digest": digest("authority-capacity", row), "provider": row["provider"], "channel": None})
    authenticated.append({"kind": "CREDENTIAL", "record_digest": digest("authority-credential", credential), "provider": credential["provider"], "channel": None})
    for row in returns:
        authenticated.append({"kind": "RETURN", "record_digest": digest("authority-return", row), "provider": row["provider"], "channel": row["channel"]})
    authenticated = sorted_utf8(authenticated)
    host_selection = {"root": root, "selection_evidence": f"{step_id}-root-selection", "authenticated_records": authenticated}
    authority_input = {
        "schema": SCHEMA + "authority-input",
        "specification_pin": PIN,
        "source": authority_source,
        "work_class": authority_work_class,
        "envelope": envelope,
        "proposal": authority_proposal,
        "clock": {"source": "governance-clock", "status": "AVAILABLE", "instant": NOW},
        "host_selection": host_selection,
        "occupancies": occupancies,
        "capacities": capacities,
        "credentials": [credential],
        "acts": acts,
        "returns": returns,
        "observations": observations,
    }
    actual = {row["name"]: row["value"]["value"] for row in proposal_fields}
    resolved_scope = {
        "subjects": sorted_utf8([actual[name] for name in subject_fields]),
        "resources": sorted_utf8([actual[name] for name in resource_fields]),
    }
    check_rows = [
        {"purpose": "SOURCE_BINDING", "subject_digest": envelope_digest, "requirement_ref": authority_source["id"], "at": NOW},
        {"purpose": "ROOT_BINDING", "subject_digest": envelope_digest, "requirement_ref": root["id"], "at": NOW},
        {"purpose": "INPUT_SUPPORT", "subject_digest": operation_digest, "requirement_ref": step_id, "at": NOW},
        {"purpose": "BINDING", "subject_digest": operation_digest, "requirement_ref": envelope["scope"]["id"], "at": NOW},
        {"purpose": "GATE_FLOOR", "subject_digest": envelope_digest, "requirement_ref": envelope_id, "at": NOW},
        {"purpose": "ENVELOPE_VALIDITY", "subject_digest": envelope_digest, "requirement_ref": envelope_id, "at": NOW},
        {"purpose": "EXECUTOR_OCCUPANCY", "subject_digest": operation_digest, "requirement_ref": executor_occupancy, "at": NOW},
        {"purpose": "CONDITION", "subject_digest": operation_digest, "requirement_ref": f"{step_id}-enabled", "at": NOW},
        {"purpose": "CREDENTIAL", "subject_digest": operation_digest, "requirement_ref": credential["id"], "at": NOW},
    ]
    if per_action:
        check_rows.append({"purpose": "PER_ACTION_LIMIT", "subject_digest": operation_digest, "requirement_ref": per_action[0]["id"], "at": NOW})
    return_by_digest = {row["act_digest"]: row for row in returns}
    for act in acts:
        act_digest = digest("authority-act", act)
        check_rows.extend([
            {"purpose": "ACT_CAPACITY", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": act["occurred_at"]},
            {"purpose": "ACT_OCCUPANCY", "subject_digest": act_digest, "requirement_ref": act["occupancy"], "at": act["occurred_at"]},
            {"purpose": "ACT_RELIANCE", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": NOW},
            {"purpose": "RETURN", "subject_digest": act_digest, "requirement_ref": return_by_digest[act_digest]["id"], "at": NOW},
        ])
        if act["kind"] == "ORGANISATIONAL_ATTESTATION":
            check_rows.append({"purpose": "SEPARATION", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": NOW})
        if act["kind"] in {"VERIFY", "INSTANCE_DECISION"}:
            check_rows.append({"purpose": "GATE_CRITERION", "subject_digest": act_digest, "requirement_ref": criterion_id, "at": act["occurred_at"]})
    for query in queries:
        check_rows.append({"purpose": "REVOCATION", "subject_digest": query["subject_digest"], "requirement_ref": digest("authority-query", query), "at": query["at"]})
    check_rows = sorted_utf8(check_rows)
    evidence_subject = {
        "host_selection": host_selection,
        "occupancies": occupancies,
        "capacities": capacities,
        "credentials": [credential],
        "acts": acts,
        "returns": returns,
        "observations": observations,
        "clock": authority_input["clock"],
    }
    authority_result = {
        "schema": SCHEMA + "authority-result",
        "specification_pin": PIN,
        "status": "READY_FOR_RESERVATION",
        "source_digest": source_digest,
        "work_class_digest": work_class_digest,
        "envelope_digest": envelope_digest,
        "proposal_digest": proposal_digest,
        "operation_digest": operation_digest,
        "scope": resolved_scope,
        "actual_scope": resolved_scope,
        "act_digests": sorted_utf8([digest("authority-act", row) for row in acts]),
        "checks": check_rows,
        "required_budgets": required_budgets,
        "evidence_digest": digest("authority-evidence", evidence_subject),
    }
    definition = {"schema": SCHEMA + "authority-definition", "source": authority_source, "work_class": authority_work_class, "envelope": envelope}
    return {
        "definition": definition,
        "input": authority_input,
        "result": authority_result,
        "result_digest": digest("authority-result", authority_result),
        "envelope_digest": envelope_digest,
        "proposal_digest": proposal_digest,
        "credential": credential,
        "executor": executor,
        "gate_act": gate_act,
        "acts": acts,
    }


def build_static_contract() -> tuple[dict, dict, dict, dict]:
    source = {
        "artifact_kind": "NON_NORMATIVE_SYNTHETIC_SOURCE_POLICY",
        "candidate_pin": PIN,
        "id": "supplier-bank-change-and-invoice-payment",
        "revision": "r1",
        "status": "READY_FOR_INDEPENDENT_SPECIMEN_REVIEW",
        "obligations": [
            {"id": "bind-payment-authority", "text": "Payment authority must bind the exact supplier, destination account, invoice, amount and payment occurrence."},
            {"id": "cap-cumulative-payments", "text": "Committed payments and unsettled payment reservations for this supplier must not exceed 1000 USD in the rolling window; the initial complete history contains 800 USD of committed exposure."},
            {"id": "change-exact-supplier-destination", "text": "The supplier master record may be changed only for the exact supplier and destination account covered by accepted confirmation and current business authority."},
            {"id": "confirm-new-destination-independently", "text": "A person independent of the person who releases payment must confirm the exact supplier and proposed destination account before the supplier master record is changed."},
            {"id": "require-established-master-data-effect", "text": "Payment may be proposed only after attributable native evidence establishes that the supplier master record was changed to the same destination account named by the payment proposal."},
            {"id": "retain-uncertain-effects", "text": "An acknowledgement does not establish payment. Unknown, late, unexpected and conflicting effects remain attributable evidence and retain or conservatively restore exposure as the contract requires."},
            {"id": "separate-confirmation-and-release", "text": "The actor whose accepted authority act confirms the new destination must differ from the actor whose accepted authority act releases payment."},
        ],
        "required_scenarios": [
            "successful bank change and payment", "two concurrent 150 payment proposals against 200 remaining capacity",
            "stale retry followed by policy withholding", "revoked authority", "expired authority",
            "invoice approval bound to the old destination", "changed dispatch arguments", "commit failure before dispatch",
            "acknowledgement without settlement", "unknown outcome retaining the reservation", "late matching settlement",
            "unexpected effect retained as disputed exposure", "restart after deployment, proposal, permit, dispatch, unknown outcome and settlement",
        ],
    }
    types = [
        {"id": "t.count", "kind": "INTEGER", "nonnegative": True, "unit": None},
        {"id": "t.identity", "kind": "IDENTITY", "nonnegative": False, "unit": None},
        {"id": "t.money", "kind": "DECIMAL", "nonnegative": True, "unit": "USD"},
        {"id": "t.status", "kind": "STRING", "nonnegative": False, "unit": None},
    ]
    change_fields = [
        {"name": "destination_account", "type_ref": "t.identity"},
        {"name": "request_count", "type_ref": "t.count"},
        {"name": "supplier_id", "type_ref": "t.identity"},
    ]
    payment_fields = [
        {"name": "amount", "type_ref": "t.money"},
        {"name": "destination_account", "type_ref": "t.identity"},
        {"name": "invoice_id", "type_ref": "t.identity"},
        {"name": "supplier_id", "type_ref": "t.identity"},
    ]
    def completion(provider: str, source_name: str, record: str, fields: list[dict]) -> dict:
        return {
            "effect_provider": provider,
            "effect_source": source_name,
            "effect_record_type": record,
            "no_effect_provider": provider,
            "no_effect_source": source_name,
            "no_effect_record_type": record + "-no-effect",
            "status_field": "status",
            "status_type_ref": "t.status",
            "success_values": [typed("t.status", "SUCCEEDED")],
            "failure_values": [typed("t.status", "FAILED")],
            "route_label_field": None,
            "route_label_type_ref": None,
            "evidence_bindings": [{"request_field": row["name"], "evidence_field": row["name"]} for row in fields],
        }
    change_step = {
        "id": "change-supplier-destination", "kind": "OPERATION", "executor_role": "supplier-master-agent",
        "interface": "supplier-master-system", "operation": "change-supplier-destination", "fields": change_fields,
        "scope_fields": {"subjects": ["supplier_id"], "resources": ["destination_account"]},
        "required_credentials": ["supplier-master-credential"], "authority_requirements": ["supplier-change-authority"],
        "shared_budgets": [], "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": "300",
        "failure_behavior": "STOP", "completion": completion("supplier-master-provider", "supplier-master-ledger", "supplier-master-change", change_fields),
    }
    terminal = {
        "id": "complete", "kind": "TERMINAL", "executor_role": None, "interface": None, "operation": None,
        "fields": [], "scope_fields": None, "required_credentials": [], "authority_requirements": [], "shared_budgets": [],
        "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": None, "failure_behavior": None, "completion": None,
    }
    payment_step = {
        "id": "pay-invoice", "kind": "OPERATION", "executor_role": "payment-agent", "interface": "payment-system",
        "operation": "pay-invoice", "fields": payment_fields,
        "scope_fields": {"subjects": ["supplier_id"], "resources": ["destination_account", "invoice_id"]},
        "required_credentials": ["payment-credential"], "authority_requirements": ["invoice-payment-authority"],
        "shared_budgets": ["supplier-payment-cap"],
        "prior_effect_bindings": [
            {"id": "payment-account-from-master", "selection": "UNIQUE_COMPLETED_ANCESTOR", "source_step_id": "change-supplier-destination", "source_evidence_field": "destination_account", "target_request_field": "destination_account"},
            {"id": "payment-supplier-from-master", "selection": "UNIQUE_COMPLETED_ANCESTOR", "source_step_id": "change-supplier-destination", "source_evidence_field": "supplier_id", "target_request_field": "supplier_id"},
        ],
        "prior_actor_separations": [{
            "id": "confirmer-differs-from-payment-releaser", "relation": "DISTINCT_ACTOR",
            "selection": "UNIQUE_COMPLETED_ANCESTOR", "prior_step_id": "change-supplier-destination",
            "prior_act_kind": "VERIFY", "current_act_kind": "INSTANCE_DECISION",
        }],
        "permit_seconds": "300", "failure_behavior": "STOP",
        "completion": completion("payment-provider", "payment-ledger", "invoice-payment", payment_fields),
    }
    work_class = {
        "schema": SCHEMA + "work-class-definition", "specification_pin": PIN,
        "id": "supplier-bank-change-and-invoice-payment", "revision": "r1", "profile": PROFILE,
        "root": change_step["id"],
        "participants": [
            {"id": "payment-agent-1", "role": "payment-agent", "kind": "AGENT"},
            {"id": "supplier-master-agent-1", "role": "supplier-master-agent", "kind": "AGENT"},
        ],
        "objects": [], "types": types, "steps": [change_step, terminal, payment_step],
        "relationships": [
            {"kind": "SEQUENCE", "from": "change-supplier-destination", "to": "pay-invoice"},
            {"kind": "SEQUENCE", "from": "pay-invoice", "to": "complete"},
        ],
        "choices": [],
        "occurrence_limits": [
            {"step_id": "change-supplier-destination", "maximum": "1"},
            {"step_id": "pay-invoice", "maximum": "1"},
        ],
        "loops": [], "deadlines": [], "parallel_blocks": [], "fanouts": [],
        "shared_budgets": ["supplier-payment-cap"],
        "limits": {"maximum_proposals": "16", "maximum_activations": "2", "maximum_actuations": "2", "maximum_active_obligations": "0", "maximum_fanout_objects": "0"},
        "source": {"id": source["id"], "revision": source["revision"], "obligations": [row["id"] for row in source["obligations"]]},
    }
    authority_source = {"schema": SCHEMA + "authority-source", "id": source["id"], "revision": source["revision"], "obligations": [{"id": row["id"], "text": row["text"]} for row in source["obligations"]]}
    authority_work_class = {
        "schema": SCHEMA + "authority-work-class", "id": work_class["id"], "revision": work_class["revision"],
        "types": [row for row in types if row["id"] != "t.status"],
        "steps": [{
            "id": row["id"], "operation": row["operation"], "interface": row["interface"],
            "executor_role": row["executor_role"], "fields": row["fields"], "scope_fields": row["scope_fields"],
            "required_credentials": row["required_credentials"],
        } for row in [change_step, payment_step]],
    }
    return source, work_class, authority_source, authority_work_class


def build_review_evidence(work_class: dict) -> tuple[dict, dict, dict, tuple[dict, dict, dict]]:
    """Readback, the correspondence record and input, and the three LIFE-003 review records for the definition."""
    definition_digest = digest("work-class-definition", work_class)
    readback_lines = readback(work_class)
    readback_result = {"status": "READBACK", "digest": definition_digest, "lines": readback_lines}
    supported_paths = {
        "bind-payment-authority": {
            "/source/obligations/0",
            "/steps/2/authority_requirements/0",
            "/steps/2/fields/0/name", "/steps/2/fields/0/type_ref",
            "/steps/2/fields/1/name", "/steps/2/fields/1/type_ref",
            "/steps/2/fields/2/name", "/steps/2/fields/2/type_ref",
            "/steps/2/fields/3/name", "/steps/2/fields/3/type_ref",
            "/steps/2/id", "/steps/2/operation",
            "/steps/2/scope_fields/resources/0", "/steps/2/scope_fields/resources/1",
            "/steps/2/scope_fields/subjects/0",
            "/types/1/id", "/types/1/kind",
            "/types/2/id", "/types/2/kind", "/types/2/nonnegative", "/types/2/unit",
        },
        "cap-cumulative-payments": {
            "/shared_budgets/0",
            "/source/obligations/1",
            "/steps/2/shared_budgets/0",
        },
        "change-exact-supplier-destination": {
            "/source/obligations/2",
            "/steps/0/authority_requirements/0",
            "/steps/0/completion/effect_provider", "/steps/0/completion/effect_record_type", "/steps/0/completion/effect_source",
            "/steps/0/completion/evidence_bindings/0/evidence_field", "/steps/0/completion/evidence_bindings/0/request_field",
            "/steps/0/completion/evidence_bindings/2/evidence_field", "/steps/0/completion/evidence_bindings/2/request_field",
            "/steps/0/completion/status_field", "/steps/0/completion/status_type_ref",
            "/steps/0/completion/success_values/0/type_ref", "/steps/0/completion/success_values/0/value",
            "/steps/0/fields/0/name", "/steps/0/fields/0/type_ref",
            "/steps/0/fields/2/name", "/steps/0/fields/2/type_ref",
            "/steps/0/id", "/steps/0/interface", "/steps/0/kind", "/steps/0/operation",
            "/steps/0/scope_fields/resources/0", "/steps/0/scope_fields/subjects/0",
            "/types/1/id", "/types/1/kind",
            "/types/3/id", "/types/3/kind",
        },
        "confirm-new-destination-independently": {
            "/source/obligations/3",
            "/steps/0/authority_requirements/0",
            "/steps/2/prior_actor_separations/0/id",
            "/steps/2/prior_actor_separations/0/prior_act_kind",
            "/steps/2/prior_actor_separations/0/prior_step_id",
            "/steps/2/prior_actor_separations/0/relation",
            "/steps/2/prior_actor_separations/0/selection",
        },
        "require-established-master-data-effect": {
            "/relationships/0/from", "/relationships/0/kind", "/relationships/0/to",
            "/source/obligations/4",
            "/steps/0/completion/effect_provider", "/steps/0/completion/effect_record_type", "/steps/0/completion/effect_source",
            "/steps/0/completion/status_field", "/steps/0/completion/status_type_ref",
            "/steps/0/completion/success_values/0/type_ref", "/steps/0/completion/success_values/0/value",
            "/steps/2/prior_effect_bindings/0/id", "/steps/2/prior_effect_bindings/0/selection",
            "/steps/2/prior_effect_bindings/0/source_evidence_field", "/steps/2/prior_effect_bindings/0/source_step_id", "/steps/2/prior_effect_bindings/0/target_request_field",
            "/steps/2/prior_effect_bindings/1/id", "/steps/2/prior_effect_bindings/1/selection",
            "/steps/2/prior_effect_bindings/1/source_evidence_field", "/steps/2/prior_effect_bindings/1/source_step_id", "/steps/2/prior_effect_bindings/1/target_request_field",
        },
        "retain-uncertain-effects": {
            "/source/obligations/5",
            "/steps/2/completion/effect_provider", "/steps/2/completion/effect_record_type", "/steps/2/completion/effect_source",
            "/steps/2/completion/failure_values/0/type_ref", "/steps/2/completion/failure_values/0/value",
            "/steps/2/completion/no_effect_provider", "/steps/2/completion/no_effect_record_type", "/steps/2/completion/no_effect_source",
            "/steps/2/completion/status_field", "/steps/2/completion/status_type_ref",
            "/steps/2/completion/success_values/0/type_ref", "/steps/2/completion/success_values/0/value",
            "/steps/2/failure_behavior",
        },
        "separate-confirmation-and-release": {
            "/source/obligations/6",
            "/steps/2/prior_actor_separations/0/current_act_kind",
            "/steps/2/prior_actor_separations/0/id",
            "/steps/2/prior_actor_separations/0/prior_act_kind",
            "/steps/2/prior_actor_separations/0/prior_step_id",
            "/steps/2/prior_actor_separations/0/relation",
            "/steps/2/prior_actor_separations/0/selection",
        },
    }
    correspondence_mappings = [
        {"source_obligation_id": obligation_id, "provision_paths": sorted_utf8(supported_paths[obligation_id])}
        for obligation_id in work_class["source"]["obligations"]
    ]
    path_set = {line["path"] for line in readback_lines}
    mapped_paths = set().union(*supported_paths.values())
    unknown_mapped_paths = mapped_paths - path_set
    if unknown_mapped_paths:
        raise ValueError(f"correspondence names absent readback paths: {sorted_utf8(unknown_mapped_paths)}")
    unsupported_paths = sorted_utf8(path_set - mapped_paths)
    residue = [
        {
            "kind": "ARTIFACT_PROVISION",
            "subject": path,
            "disposition": "UNSUPPORTED",
            "explanation": "The synthetic source policy does not state this representation or execution detail.",
        }
        for path in unsupported_paths
    ]
    correspondence_base = {
        "schema": SCHEMA + "evidence-record", "evidence_id": "supplier-payment-correspondence", "kind": "CORRESPONDENCE",
        "status": "ACCEPTED", "subject_digest": definition_digest, "source_id": work_class["source"]["id"], "source_revision": work_class["source"]["revision"],
        "work_class_digest": definition_digest, "mappings": correspondence_mappings, "uncovered_source_obligation_ids": [],
        "unsupported_provision_paths": unsupported_paths, "residue": residue, "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
        "provenance_digest": digest("specimen-provenance", {"id": "supplier-payment-correspondence"}),
    }
    correspondence_subject = digest("correspondence-subject", correspondence_base)
    correspondence_review = {
        "schema": SCHEMA + "evidence-record", "evidence_id": "supplier-payment-correspondence-review", "kind": "REVIEW",
        "status": "ACCEPTED", "subject_digest": correspondence_subject, "reviewer_id": "synthetic:specimen-proxy-reviewer:20260913",
        "paragraph_ids": [], "case_ids": ["supplier-payment-correspondence"], "finding_ids": [], "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
        "provenance_digest": digest("specimen-provenance", {"id": "supplier-payment-correspondence-review"}),
    }
    correspondence_record = {**correspondence_base, "review": correspondence_review}
    correspondence_input = {
        "profile": PROFILE, "role": "REVIEW_EVIDENCE", "specification_pin": PIN,
        "subject": {"kind": "WORK_CLASS", "subject_id": work_class["id"], "subject_digest": definition_digest,
                    "candidate_identity": "seampoint.work-class/1.0.0-draft.2", "specification_pin": PIN},
        "work_class": work_class, "work_class_digest": definition_digest, "evidence": correspondence_record,
    }
    # LIFE-003 review acts for deployment. No person has reviewed this specimen's correspondence; the nested
    # review, the source confirmation and the policy decision are labelled synthetic proxy acts, and the
    # README says so.
    source_confirmation = {
        "schema": SCHEMA + "evidence-record", "evidence_id": "supplier-payment-source-confirmation", "kind": "SOURCE_CONFIRMATION",
        "status": "ACCEPTED", "subject_digest": digest("work-class-source", work_class["source"]),
        "actor_id": "synthetic:specimen-proxy-source-confirmer:20260913", "scope_ids": list(work_class["source"]["obligations"]),
        "recorded_at": DEPLOYMENT_AUTHORIZED_AT, "provenance_digest": digest("specimen-provenance", {"id": "supplier-payment-source-confirmation"}),
    }
    policy_decision = {
        "schema": SCHEMA + "evidence-record", "evidence_id": "supplier-payment-policy-decision", "kind": "POLICY_DECISION",
        "status": "ACCEPTED", "subject_digest": definition_digest, "decision_maker_id": "synthetic:specimen-proxy-policy-owner:20260913",
        "decision_ids": ["supplier-payment-policy-decision-1"], "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
        "provenance_digest": digest("specimen-provenance", {"id": "supplier-payment-policy-decision"}),
    }
    review_evidence = (correspondence_record, source_confirmation, policy_decision)
    return readback_result, correspondence_record, correspondence_input, review_evidence



def generic_review_evidence(work_class: dict) -> tuple[dict, dict, dict]:
    """LIFE-003 review records for a definition without a hand-mapped correspondence: every source obligation
    maps to the complete readback path set with empty residue. Labelled synthetic proxy acts."""
    definition_digest = digest("work-class-definition", work_class)
    paths = sorted_utf8([line["path"] for line in readback(work_class)])
    obligations = list(work_class["source"]["obligations"])
    base = {
        "schema": SCHEMA + "evidence-record", "evidence_id": f"{work_class['id']}-correspondence", "kind": "CORRESPONDENCE",
        "status": "ACCEPTED", "subject_digest": definition_digest, "source_id": work_class["source"]["id"], "source_revision": work_class["source"]["revision"],
        "work_class_digest": definition_digest, "mappings": [{"source_obligation_id": obligation_id, "provision_paths": list(paths)} for obligation_id in obligations],
        "uncovered_source_obligation_ids": [], "unsupported_provision_paths": [], "residue": [], "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
        "provenance_digest": digest("specimen-provenance", {"id": f"{work_class['id']}-correspondence"}),
    }
    review = {
        "schema": SCHEMA + "evidence-record", "evidence_id": f"{work_class['id']}-correspondence-review", "kind": "REVIEW",
        "status": "ACCEPTED", "subject_digest": digest("correspondence-subject", base), "reviewer_id": "synthetic:specimen-proxy-reviewer:20260913",
        "paragraph_ids": [], "case_ids": [f"{work_class['id']}-correspondence"], "finding_ids": [], "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
        "provenance_digest": digest("specimen-provenance", {"id": f"{work_class['id']}-correspondence-review"}),
    }
    source_confirmation = {
        "schema": SCHEMA + "evidence-record", "evidence_id": f"{work_class['id']}-source-confirmation", "kind": "SOURCE_CONFIRMATION",
        "status": "ACCEPTED", "subject_digest": digest("work-class-source", work_class["source"]),
        "actor_id": "synthetic:specimen-proxy-source-confirmer:20260913", "scope_ids": obligations,
        "recorded_at": DEPLOYMENT_AUTHORIZED_AT, "provenance_digest": digest("specimen-provenance", {"id": f"{work_class['id']}-source-confirmation"}),
    }
    policy_decision = {
        "schema": SCHEMA + "evidence-record", "evidence_id": f"{work_class['id']}-policy-decision", "kind": "POLICY_DECISION",
        "status": "ACCEPTED", "subject_digest": definition_digest, "decision_maker_id": "synthetic:specimen-proxy-policy-owner:20260913",
        "decision_ids": [f"{work_class['id']}-policy-decision-1"], "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
        "provenance_digest": digest("specimen-provenance", {"id": f"{work_class['id']}-policy-decision"}),
    }
    return {**base, "review": review}, source_confirmation, policy_decision


def build_deployment(work_class: dict, instance_id: str, review_evidence: tuple[dict, dict, dict] | None = None) -> tuple[dict, dict, dict, dict]:
    definition_digest = digest("work-class-definition", work_class)
    if review_evidence is None:
        review_evidence = generic_review_evidence(work_class)
    correspondence, source_confirmation, policy_decision = review_evidence
    correspondence_digest, source_confirmation_digest, policy_decision_digest = (digest("evidence", row) for row in review_evidence)
    root_occurrence = occurrence(definition_digest, instance_id, work_class["root"], "1", [])
    auth_partial = {
        "schema": SCHEMA + "deployment-authorization", "authorization_id": f"deploy-{instance_id}",
        "specification_pin": PIN, "work_class_digest": definition_digest, "profile": PROFILE, "role": ROLE,
        "instance_id": instance_id, "organization_id": ORG, "status": "AUTHORIZED",
        "authorized_at": DEPLOYMENT_AUTHORIZED_AT, "expires_at": "2026-09-12T00:00:00Z",
        "correspondence_evidence_digest": correspondence_digest, "source_confirmation_evidence_digest": source_confirmation_digest,
        "policy_decision_evidence_digest": policy_decision_digest,
    }
    subject_digest = digest("deployment-authorization-subject", auth_partial)
    evidence = {
        "schema": SCHEMA + "evidence-record", "evidence_id": f"deployment-evidence-{instance_id}",
        "kind": "ORGANIZATIONAL_AUTHORIZATION", "status": "ACCEPTED", "subject_digest": subject_digest,
        "organization_id": ORG, "authorizer_id": "deployment-authorizer",
        "authorization_scope": sorted_utf8([PIN, definition_digest, PROFILE, ROLE, instance_id]),
        "recorded_at": "2026-09-11T11:50:00Z", "expires_at": "2026-09-12T00:00:00Z",
        "provenance_digest": digest("specimen-provenance", {"id": f"deployment-evidence-{instance_id}"}),
    }
    evidence_digest = digest("evidence", evidence)
    authorization = {**auth_partial, "authorization_evidence_digest": evidence_digest}
    authorization_digest = digest("deployment-authorization", authorization)
    authorization_clock = {
        "source": "deployment-clock", "revision": "1", "status": "AVAILABLE",
        "observed_time": "2026-09-11T11:55:00Z",
        "evidence_digest": digest("specimen-clock-evidence", {"source": "deployment-clock", "revision": "1", "time": "2026-09-11T11:55:00Z"}),
    }
    activation_digest = digest("deployment-activation", {"deployment_authorization_digest": authorization_digest, "instance_id": instance_id, "occurrence_id": root_occurrence["occurrence_id"]})
    proposal_steps = [row for row in work_class["steps"] if row["kind"] == "OPERATION"]
    state = {
        "schema": SCHEMA + "work-state", "specification_pin": PIN, "work_class_digest": definition_digest,
        "profile": PROFILE, "role": ROLE, "instance_id": instance_id,
        "deployment_authorization": authorization, "deployment_authorization_subject_digest": subject_digest,
        "deployment_authorization_digest": authorization_digest, "deployment_authorization_evidence": evidence,
        "deployment_authorization_evidence_digest": evidence_digest,
        "deployment_correspondence_evidence": correspondence, "deployment_correspondence_evidence_digest": correspondence_digest,
        "deployment_source_confirmation_evidence": source_confirmation, "deployment_source_confirmation_evidence_digest": source_confirmation_digest,
        "deployment_policy_decision_evidence": policy_decision, "deployment_policy_decision_evidence_digest": policy_decision_digest,
        "deployment_authorization_clock": authorization_clock,
        "deployment_organization_id": ORG, "revision": "0", "status": "ACTIVE",
        "total_activations": "1", "total_actuations": "0",
        "step_counters": [{"step_id": row["id"], "activations": "1" if row["id"] == work_class["root"] else "0", "actuations": "0"} for row in proposal_steps],
        "active": [{"occurrence": root_occurrence, "activation_event_digest": activation_digest, "status": "ACTIVE", "deadline_ids": []}],
        "completed": [], "obligations": [], "proposals": [], "permits": [], "dispatches": [], "outcomes": [],
        "clocks": [], "deadlines": [], "fanout_passes": [], "receipts": [], "replays": [],
    }
    deploy_input = {
        "profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class,
        "definition_digest": definition_digest, "instance_id": instance_id, "deployment_authorization": authorization,
        "authorization_evidence": evidence, "correspondence_evidence": correspondence, "source_confirmation_evidence": source_confirmation,
        "policy_decision_evidence": policy_decision, "authorization_clock": authorization_clock, "initial_clocks": [],
    }
    deploy_result = {
        "status": "DEPLOYED", "profile": PROFILE, "role": ROLE, "instance_id": instance_id,
        "work_class_digest": definition_digest, "deployment_authorization_digest": authorization_digest,
        "state": state, "state_digest": work_state_digest(state),
    }
    return deploy_input, deploy_result, state, root_occurrence


def protocol_request(request_id: str, operation: str, input_value: dict) -> dict:
    return {"protocol": PROTOCOL, "request_id": request_id, "operation": operation, "input": input_value}


def main() -> None:
    source, work_class, authority_source, authority_work_class = build_static_contract()
    definition_digest = digest("work-class-definition", work_class)

    aggregate_definition = {
        "schema": SCHEMA + "aggregate-definition",
        "types": [
            {"id": "b.identity", "kind": "IDENTITY", "unit": None, "nonnegative": False},
            {"id": "b.money", "kind": "DECIMAL", "unit": "USD", "nonnegative": True},
        ],
        "aggregate": {
            "id": "supplier-payment-sum", "reducer": "SUM", "result_type": "b.money", "element_type": None,
            "key_types": ["b.identity"],
            "mappings": [{"id": "invoice-payment-amount", "step_ids": ["pay-invoice"], "qualifier": {"kind": "BOOLEAN", "value": True}, "key_fields": ["supplier_id"], "contribution": {"kind": "SUM", "field": "amount"}}],
            "time": {"clock_source": "governance-clock", "precision": "SECOND"},
            "window": {"kind": "ROLLING", "duration_seconds": "86400", "start_inclusive": False, "end_inclusive": True},
            "committed_source": {"provider": "payment-provider", "source": "payment-ledger", "freshness": {"kind": "NONE"}, "key_fields": ["supplier_id"], "qualifier": {"kind": "BOOLEAN", "value": True}, "contribution": {"kind": "SUM", "field": "amount"}},
            "pending_policy": "INCLUDE_ALL_RESERVED", "operator": "LTE", "bound": typed("b.money", "1000"),
        },
    }
    aggregate_digest = digest("aggregate-definition", aggregate_definition)
    budget_definition = {
        "schema": SCHEMA + "budget-definition", "anchor": "supplier-payment-cap", "exposure_domain": "supplier-payment",
        "principal": ORG, "aggregate": aggregate_definition, "contributor_classes": [work_class["id"]],
        "reservation_policy": {"permit_seconds": "300", "pending_across_windows": True,
                               "unexpected_effect": "BLOCK_AFFECTED_PARTITIONS", "unprojectable_effect": "BLOCK_ANCHOR",
                               "settlement": {"provider": "payment-provider", "source": "payment-ledger"},
                               "no_effect": {"provider": "payment-provider", "source": "payment-ledger"}},
    }
    budget_digest = digest("budget-definition", budget_definition)
    history_event_800 = {
        "id": "committed-payment-800", "state": "ACTIVE", "occurred_at": HISTORY_TIME,
        "fields": [field("amount", "b.money", "800"), field("supplier_id", "b.identity", "supplier-17")],
    }
    initial_history = {
        "budget_digest": budget_digest, "provider": "payment-provider", "source": "payment-ledger",
        "status": "AVAILABLE", "as_of": NOW, "complete": True, "revision": "1",
        "journal": [{"sequence": "1", "event": history_event_800}], "evidence_ref": "payment-history-800",
    }
    registry_config = {
        "schema": SCHEMA + "reservation-registry", "id": "supplier-payment-registry", "principal": ORG,
        "clock_source": "governance-clock", "administration_provider": "governance-provider",
        "administration_source": "budget-administration", "administration_role": "budget-administrator",
        "slots": [{"anchor": "supplier-payment-cap", "exposure_domain": "supplier-payment"}],
    }
    registry_digest = digest("reservation-registry", registry_config)
    registry_empty = {"schema": SCHEMA + "reservation-state", "specification_pin": PIN,
                      "core": {"configuration": registry_config, "revision": "0", "last_clock": None, "budgets": [], "reservations": [], "effects": []}, "receipts": []}

    payment_authority_placeholder = build_authority(
        authority_source, authority_work_class, instance_id="supplier-payment-instance-a",
        occurrence_row=occurrence(definition_digest, "supplier-payment-instance-a", "pay-invoice", "1", []),
        step_id="pay-invoice", envelope_id="invoice-payment-authority", executor_id="payment-agent-1",
        executor_role="payment-agent", credential_kind="payment-credential", gate_kind="DECIDE",
        gate_actor="payment-releaser-person", gate_role="payment-releaser", subject_fields=["supplier_id"],
        resource_fields=["destination_account", "invoice_id"],
        proposal_fields=[field("amount", "t.money", "150"), field("destination_account", "t.identity", "acct-new"), field("invoice_id", "t.identity", "invoice-44"), field("supplier_id", "t.identity", "supplier-17")],
        required_budgets=["supplier-payment-cap"],
    )
    class_authorization = {
        "id": "supplier-payment-budget-authorization", "budget_digest": budget_digest,
        "work_class": work_class["id"], "work_class_digest": digest("authority-work-class", authority_work_class),
        "envelope_digest": payment_authority_placeholder["envelope_digest"], "principal": ORG, "step": "pay-invoice",
        "authority_definition": payment_authority_placeholder["definition"],
        "projection": [
            {"native_field": "amount", "native_type": "t.money", "budget_field": "amount", "budget_type": "b.money"},
            {"native_field": "supplier_id", "native_type": "t.identity", "budget_field": "supplier_id", "budget_type": "b.identity"},
        ],
    }
    register_payload = {"definition": budget_definition, "authorizations": [class_authorization], "history": initial_history}
    register_without_admin = {"id": "register-supplier-payment-budget", "expected_revision": "0", "kind": "REGISTER",
                              "clock": {"source": "governance-clock", "status": "AVAILABLE", "instant": NOW}, "payload": register_payload}
    admin_subject = digest("reservation-administration-subject", {"registry_digest": registry_digest, "event_id": register_without_admin["id"],
                                                                  "expected_revision": "0", "kind": "REGISTER", "clock": register_without_admin["clock"], "payload": register_payload})
    admin_basis = {"id": "supplier-payment-admin-basis", "registry_digest": registry_digest, "actor": "budget-admin-person", "principal": ORG,
                   "role": "budget-administrator", "kind": "HUMAN", "operations": ["REGISTER", "RELEASE"],
                   "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
                   "at": NOW, "revoked": False, "provider": "governance-provider", "source": "budget-administration", "evidence_ref": "supplier-payment-admin-evidence"}
    admin_act = {"id": "register-supplier-payment-budget-act", "basis": admin_basis["id"], "actor": admin_basis["actor"], "principal": ORG,
                 "role": admin_basis["role"], "kind": "REGISTER", "subject_digest": admin_subject, "occurred_at": NOW, "disposition": "ACCEPT"}
    admin_return = {"id": "register-supplier-payment-budget-return", "act_digest": digest("reservation-administration-act", admin_act),
                    "act_bytes_base64": base64.b64encode(canonical_bytes(admin_act)).decode(), "actor": admin_act["actor"],
                    "provider": "governance-provider", "source": "budget-administration", "returned_at": NOW, "evidence_ref": "supplier-payment-admin-return-evidence"}
    register_event = {**register_without_admin, "administration": {"act": admin_act, "returned": admin_return}}
    register_host = {"registry_digest": registry_digest, "selection_evidence": "supplier-payment-registry-selection", "administration_bases": [admin_basis],
                     "authenticated_records": sorted_utf8([
                         {"kind": "HISTORY", "record_digest": digest("budget-history", initial_history), "provider": "payment-provider", "source": "payment-ledger"},
                         {"kind": "ADMIN_RETURN", "record_digest": digest("reservation-administration-return", admin_return), "provider": "governance-provider", "source": "budget-administration"},
                     ])}
    def apply_register(state):
        state["core"]["budgets"] = [{"definition": budget_definition, "definition_digest": budget_digest,
                                       "authorizations": [class_authorization], "history": initial_history}]
    registry_registered, register_result = reservation_transition(registry_empty, register_event, register_host, decision="REGISTERED",
                                                                  reservation_id=None, budgets=[], authority_result=None, reasons=[], mutate=apply_register)
    register_input = {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": registry_empty,
                      "state_digest": reservation_state_digest(registry_empty), "event": register_event, "host_evidence": register_host}

    write("source-policy.json", source)
    write("work-class.json", work_class)
    write("shared-budget-definition.json", budget_definition)
    write("shared-budget-register-input.json", register_input)
    write("shared-budget-register-result-derived.json", register_result)

    readback_result, correspondence_record, correspondence_input, review_evidence = build_review_evidence(work_class)

    # Build two complete independent instances through successful master-data change.
    instance_material = {}
    for suffix in ["a", "b"]:
        instance_id = f"supplier-payment-instance-{suffix}"
        deploy_input, deploy_result, state0, change_occ = build_deployment(work_class, instance_id, review_evidence)
        clock = {"source": "governance-clock", "revision": "1", "status": "AVAILABLE", "observed_time": NOW,
                 "evidence_digest": digest("specimen-clock-evidence", {"source": "governance-clock", "revision": "1", "time": NOW})}
        clock_event = {"schema": SCHEMA + "runtime-event", "event_id": f"clock-{instance_id}-1", "kind": "CLOCK", "instance_id": instance_id,
                       "expected_state_revision": "0", "expected_state_digest": work_state_digest(state0), "clock": clock, "activation_clocks": []}
        def apply_clock(state, _): state["clocks"] = [clock]
        state1, clock_result = work_transition(state0, clock_event, disposition="CLOCK_RECORDED", reasons=[],
                                               details=[{"kind": "CLOCK", "source": "governance-clock", "revision": "1", "status": "AVAILABLE"}],
                                               permit=None, budget_results=[], authority_result_digest=None, reservation_receipt_digests=[], mutate=apply_clock)
        change_fields = [field("destination_account", "t.identity", "acct-new"), field("request_count", "t.count", "1"), field("supplier_id", "t.identity", "supplier-17")]
        change_auth = build_authority(authority_source, authority_work_class, instance_id=instance_id, occurrence_row=change_occ,
                                      step_id="change-supplier-destination", envelope_id="supplier-change-authority",
                                      executor_id="supplier-master-agent-1", executor_role="supplier-master-agent",
                                      credential_kind="supplier-master-credential", gate_kind="VERIFY",
                                      gate_actor="destination-confirmer-person", gate_role="destination-confirmer",
                                      subject_fields=["supplier_id"], resource_fields=["destination_account"],
                                      proposal_fields=change_fields, required_budgets=[])
        change_native_request = {"interface": "supplier-master-system", "operation": "change-supplier-destination", "fields": change_fields}
        change_executor = {"participant_id": "supplier-master-agent-1", "role": "supplier-master-agent",
                           "binding_digest": digest("executor-binding", change_auth["executor"])}
        observation_digests = sorted_utf8([digest("authority-observation", row) for row in change_auth["input"]["observations"]])
        change_event = {"schema": SCHEMA + "runtime-event", "event_id": f"propose-change-{suffix}", "kind": "PROPOSE", "instance_id": instance_id,
                        "expected_state_revision": "1", "expected_state_digest": work_state_digest(state1), "occurrence": change_occ,
                        "native_request": change_native_request, "executor": change_executor,
                        "credential_ids": [change_auth["credential"]["id"]], "authority_input": change_auth["input"],
                        "budget_inputs": [], "clock_revision": "1", "observation_digests": observation_digests}
        proposal_digest = digest("proposal", change_event)
        change_permit = {"schema": SCHEMA + "permit", "permit_id": "sha256:" + "0" * 64, "instance_id": instance_id,
                         "work_class_digest": definition_digest, "profile": PROFILE, "role": ROLE, "occurrence": change_occ,
                         "proposal_digest": proposal_digest, "native_request": change_native_request, "executor": change_executor,
                         "credential_ids": [change_auth["credential"]["id"]], "authority_result": change_auth["result"],
                         "authority_result_digest": change_auth["result_digest"], "authority_evidence_digest": change_auth["result"]["evidence_digest"],
                         "authority_act_bases": sorted([{"act_digest": digest("authority-act", row), "act": row} for row in change_auth["acts"]], key=lambda row: row["act_digest"].encode("utf-8")),
                         "prior_effect_bases": [], "separation_bases": [], "observation_digests": observation_digests,
                         "supersedes_permit_digest": None, "budget_revisions": [], "clock_source": "governance-clock", "clock_revision": "1", "expires_at": PERMIT_EXPIRY}
        change_permit["permit_id"] = digest("permit", omit(change_permit, "permit_id"))
        def apply_change_proposal(state, event_digest):
            state["total_actuations"] = "1"
            next(row for row in state["step_counters"] if row["step_id"] == "change-supplier-destination")["actuations"] = "1"
            state["active"][0]["status"] = "PERMITTED"
            state["proposals"].append({"event_id": change_event["event_id"], "event_digest": event_digest, "proposal_digest": proposal_digest,
                                        "occurrence_id": change_occ["occurrence_id"], "disposition": "PERMITTED", "permit_digest": change_permit["permit_id"],
                                        "authority_result_digest": change_auth["result_digest"], "reservation_receipt_digests": [], "prior_permit_digest": None})
            state["permits"].append(change_permit)
        state2, change_proposal_result = work_transition(state1, change_event, disposition="PERMITTED", reasons=[], details=[], permit=change_permit,
                                                         budget_results=[], authority_result_digest=change_auth["result_digest"], reservation_receipt_digests=[], mutate=apply_change_proposal)
        connector = {"id": "supplier-master-connector", "version": "v1", "binding_digest": "sha256:" + "0" * 64}
        connector["binding_digest"] = digest("connector-binding", omit(connector, "binding_digest"))
        attempt = {"attempt_id": f"change-attempt-{suffix}", "status": "SENT",
                   "request_digest": digest("dispatch-native-request", {"instance_id": instance_id, "occurrence_id": change_occ["occurrence_id"],
                                                                         "interface": change_native_request["interface"], "operation": change_native_request["operation"], "fields": change_native_request["fields"]}),
                   "attempted_at": NOW}
        acknowledgement = {"status": "ACCEPTED", "reference": f"change-ack-{suffix}", "observed_at": NOW}
        dispatch_event = {"schema": SCHEMA + "runtime-event", "event_id": f"dispatch-change-{suffix}", "kind": "DISPATCH_OBSERVED", "instance_id": instance_id,
                          "expected_state_revision": "2", "expected_state_digest": work_state_digest(state2), "permit": change_permit,
                          "native_request": change_native_request, "connector": connector, "attempt": attempt, "acknowledgement": acknowledgement, "clock_revision": "1"}
        dispatch_event_digest = digest("runtime-event", dispatch_event)
        dispatch_attempt_digest = digest("dispatch-attempt", {"permit_id": change_permit["permit_id"], "native_request": change_native_request, "connector": connector, "attempt": attempt})
        dispatch_record = {"dispatch_digest": "sha256:" + "0" * 64, "dispatch_attempt_digest": dispatch_attempt_digest,
                           "event_id": dispatch_event["event_id"], "event_digest": dispatch_event_digest, "permit_digest": change_permit["permit_id"],
                           "native_request": change_native_request, "connector": connector, "attempt": attempt, "acknowledgement": acknowledgement, "clock_revision": "1"}
        dispatch_record["dispatch_digest"] = digest("dispatch", omit(dispatch_record, "dispatch_digest"))
        def apply_change_dispatch(state, _):
            state["active"][0]["status"] = "DISPATCHED"; state["dispatches"].append(dispatch_record)
        state3, change_dispatch_result = work_transition(state2, dispatch_event, disposition="ACKNOWLEDGED", reasons=[],
                                                         details=[{"kind": "DISPATCH", "attempt_id": attempt["attempt_id"], "reasons": []}], permit=None,
                                                         budget_results=[], authority_result_digest=None, reservation_receipt_digests=[], mutate=apply_change_dispatch)
        attributed = {"work_class": work_class["id"], "instance": instance_id, "occurrence": change_occ["occurrence_id"],
                      "step": "change-supplier-destination", "operation": change_native_request["operation"], "interface": change_native_request["interface"], "fields": change_fields}
        actual_fields = change_fields + [field("status", "t.status", "SUCCEEDED")]
        actual_fields.sort(key=lambda row: row["name"].encode())
        native_evidence = {"evidence_id": f"change-effect-{suffix}", "native_operation_id": f"supplier-master-native-{suffix}",
                           "provider": "supplier-master-provider", "source": "supplier-master-ledger", "record_type": "supplier-master-change",
                           "record_digest": digest("specimen-native-record", {"instance": instance_id, "actual_fields": actual_fields}),
                           "evidence_ref": f"supplier-master-effect-record-{suffix}", "attributed_request": attributed,
                           "native_request_digest": digest("native-request", attributed), "status": "EFFECT_ESTABLISHED",
                           "actual_fields": actual_fields, "collections": [], "event_time": NOW, "observed_at": NOW,
                           "rules_out_past_and_future_effects": False}
        effect_event = {"schema": SCHEMA + "runtime-event", "event_id": f"effect-change-{suffix}", "kind": "EFFECT_OBSERVED", "instance_id": instance_id,
                        "expected_state_revision": "3", "expected_state_digest": work_state_digest(state3), "permit": change_permit,
                        "dispatch_digest": dispatch_record["dispatch_digest"], "native_evidence": native_evidence,
                        "completion_authorization": None, "budget_inputs": [], "clock_revision": None, "activation_clocks": []}
        effect_event_digest = digest("runtime-event", effect_event)
        relation_digest = digest("relationship", work_class["relationships"][0])
        payment_occ = occurrence(definition_digest, instance_id, "pay-invoice", "1", [change_occ["occurrence_id"]])
        outcome = {"kind": "GOVERNED", "outcome_digest": "sha256:" + "0" * 64, "event_id": effect_event["event_id"],
                   "event_digest": effect_event_digest, "permit_digest": change_permit["permit_id"], "dispatch_digest": dispatch_record["dispatch_digest"],
                   "dispatch_attempt_digest": dispatch_attempt_digest, "native_evidence": native_evidence, "classification": "MATCHED",
                   "reservation_receipt_digests": [], "conflicts_with_evidence_ids": [], "disputed": False}
        outcome["outcome_digest"] = digest("outcome", omit(outcome, "outcome_digest"))
        completed_change = {"occurrence": change_occ, "disposition": "SUCCEEDED", "evidence_digest": digest("native-evidence", native_evidence),
                            "occurred_at": NOW, "route_label": None, "selected_relationship_digest": relation_digest, "late": False}
        def apply_change_effect(state, _):
            state["total_activations"] = "2"
            next(row for row in state["step_counters"] if row["step_id"] == "pay-invoice")["activations"] = "1"
            state["active"] = [{"occurrence": payment_occ, "activation_event_digest": effect_event_digest, "status": "ACTIVE", "deadline_ids": []}]
            state["completed"] = [completed_change]
            state["outcomes"] = [outcome]
        state4, change_effect_result = work_transition(state3, effect_event, disposition="COMPLETED", reasons=[],
                                                       details=[{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": native_evidence["evidence_id"]},
                                                                {"kind": "ROUTE", "relationship_digests": [relation_digest], "construct_ids": []}],
                                                       permit=None, budget_results=[], authority_result_digest=None, reservation_receipt_digests=[], mutate=apply_change_effect)
        requests = [
            protocol_request(f"deploy-{suffix}", "deploy", deploy_input),
            protocol_request(f"clock-{suffix}", "step", {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest, "state": state0, "state_digest": work_state_digest(state0), "event": clock_event}),
            protocol_request(f"propose-change-{suffix}", "step", {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest, "state": state1, "state_digest": work_state_digest(state1), "event": change_event}),
            protocol_request(f"dispatch-change-{suffix}", "step", {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest, "state": state2, "state_digest": work_state_digest(state2), "event": dispatch_event}),
            protocol_request(f"effect-change-{suffix}", "step", {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest, "state": state3, "state_digest": work_state_digest(state3), "event": effect_event}),
        ]
        results = [deploy_result, clock_result, change_proposal_result, change_dispatch_result, change_effect_result]
        instance_material[suffix] = {"instance_id": instance_id, "payment_occ": payment_occ, "state_payment_active": state4,
                                     "change_auth": change_auth, "change_permit": change_permit, "change_evidence": native_evidence,
                                     "requests": requests, "results": results}
        write(f"instances/{suffix}/authority-change-definition.json", change_auth["definition"])
        write(f"instances/{suffix}/authority-change-input.json", change_auth["input"])
        write(f"instances/{suffix}/authority-change-result-derived.json", change_auth["result"])
        write(f"instances/{suffix}/deployment-input.json", deploy_input)
        write(f"instances/{suffix}/deployment-result-derived.json", deploy_result)
        write(f"instances/{suffix}/through-master-change-requests.json", requests)
        write(f"instances/{suffix}/through-master-change-results-derived.json", results)
        write(f"instances/{suffix}/payment-active-state.json", state4)

    # Create the two competing payment proposals against the same revision-1 registry.
    payment_proposals = {}
    for suffix, invoice in [("a", "invoice-44"), ("b", "invoice-45")]:
        material = instance_material[suffix]
        instance_id = material["instance_id"]
        payment_occ = material["payment_occ"]
        payment_fields = [field("amount", "t.money", "150"), field("destination_account", "t.identity", "acct-new"),
                          field("invoice_id", "t.identity", invoice), field("supplier_id", "t.identity", "supplier-17")]
        payment_auth = build_authority(authority_source, authority_work_class, instance_id=instance_id, occurrence_row=payment_occ,
                                       step_id="pay-invoice", envelope_id="invoice-payment-authority", executor_id="payment-agent-1",
                                       executor_role="payment-agent", credential_kind="payment-credential", gate_kind="DECIDE",
                                       gate_actor="payment-releaser-person", gate_role="payment-releaser", subject_fields=["supplier_id"],
                                       resource_fields=["destination_account", "invoice_id"], proposal_fields=payment_fields,
                                       required_budgets=["supplier-payment-cap"])
        native_request = {"interface": "payment-system", "operation": "pay-invoice", "fields": payment_fields}
        lifecycle_executor = {"participant_id": "payment-agent-1", "role": "payment-agent", "binding_digest": digest("executor-binding", payment_auth["executor"])}
        obs_digests = sorted_utf8([digest("authority-observation", row) for row in payment_auth["input"]["observations"]])
        event_id = f"propose-payment-{suffix}-1"
        reservation_event_id = digest("lifecycle-reservation-event", {"instance_id": instance_id, "lifecycle_event_id": event_id,
                                                                      "lifecycle_event_kind": "PROPOSE", "reservation_event_kind": "RESERVE",
                                                                      "registry_digest": registry_digest})
        reserve_event = {"id": reservation_event_id, "expected_revision": "1", "kind": "RESERVE",
                         "clock": payment_auth["input"]["clock"], "payload": {"authority": payment_auth["input"], "histories": [initial_history]},
                         "administration": None}
        reserve_host = {"registry_digest": registry_digest, "selection_evidence": "supplier-payment-registry-selection", "administration_bases": [],
                        "authenticated_records": [{"kind": "HISTORY", "record_digest": digest("budget-history", initial_history),
                                                   "provider": "payment-provider", "source": "payment-ledger"}]}
        reserve_input = {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": registry_registered,
                         "state_digest": reservation_state_digest(registry_registered), "event": reserve_event, "host_evidence": reserve_host}
        event = {"schema": SCHEMA + "runtime-event", "event_id": event_id, "kind": "PROPOSE", "instance_id": instance_id,
                 "expected_state_revision": "4", "expected_state_digest": work_state_digest(material["state_payment_active"]),
                 "occurrence": payment_occ, "native_request": native_request, "executor": lifecycle_executor,
                 "credential_ids": [payment_auth["credential"]["id"]], "authority_input": payment_auth["input"],
                 "budget_inputs": [{"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "expected_revision": "1", "request": reserve_input}],
                 "clock_revision": "1", "observation_digests": obs_digests}
        request = protocol_request(event_id, "step", {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class,
                                                       "definition_digest": definition_digest, "state": material["state_payment_active"],
                                                       "state_digest": work_state_digest(material["state_payment_active"]), "event": event})
        payment_proposals[suffix] = {"authority": payment_auth, "fields": payment_fields, "native_request": native_request,
                                     "executor": lifecycle_executor, "event": event, "request": request,
                                     "reserve_input": reserve_input, "reservation_event_id": reservation_event_id,
                                     "obs_digests": obs_digests}
        write(f"instances/{suffix}/authority-payment-definition.json", payment_auth["definition"])
        write(f"instances/{suffix}/authority-payment-input.json", payment_auth["input"])
        write(f"instances/{suffix}/authority-payment-result-derived.json", payment_auth["result"])

    first = payment_proposals["a"]
    first_occurrence_key = digest("reservation-occurrence", {"work_class": work_class["id"], "instance": instance_material["a"]["instance_id"],
                                                              "occurrence": instance_material["a"]["payment_occ"]["occurrence_id"]})
    first_reservation = {"id": first["reservation_event_id"], "occurrence_key": first_occurrence_key,
                         "proposal_digest": first["authority"]["proposal_digest"], "envelope_digest": first["authority"]["envelope_digest"],
                         "authority": first["authority"]["input"], "authority_result": first["authority"]["result"],
                         "contributions": [{"anchor": "supplier-payment-cap", "mapping": "invoice-payment-amount", "occurrence": first_occurrence_key,
                                            "key": [typed("b.identity", "supplier-17")], "value": typed("b.money", "150")}],
                         "created_at": NOW, "permit_until": PERMIT_EXPIRY, "status": "OPEN", "matched_effect": None}
    aggregate_950 = {"schema": SCHEMA + "aggregate-result", "specification_pin": PIN, "definition_digest": aggregate_digest,
                     "status": "SATISFIED", "partitions": [{"occurrence": None, "key": [typed("b.identity", "supplier-17")],
                                                              "status": "SATISFIED", "accumulator": {"kind": "SCALAR", "value": "950"},
                                                              "result": "950", "reasons": []}], "reasons": []}
    def apply_first_reserve(state): state["core"]["reservations"] = [first_reservation]
    registry_after_first, first_reserve_result = reservation_transition(registry_registered, first["reserve_input"]["event"], first["reserve_input"]["host_evidence"],
                                                                        decision="RESERVED", reservation_id=first["reservation_event_id"],
                                                                        budgets=[{"anchor": "supplier-payment-cap", "result": aggregate_950}],
                                                                        authority_result=first["authority"]["result"], reasons=[], mutate=apply_first_reserve)
    first_budget_result = {"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "result": first_reserve_result}
    change_source = instance_material["a"]
    change_gate = change_source["change_auth"]["gate_act"]
    current_gate = first["authority"]["gate_act"]
    prior_bases = [
        {"binding_id": "payment-account-from-master", "source_occurrence_id": change_source["payment_occ"]["predecessor_occurrence_ids"][0],
         "source_permit_digest": change_source["change_permit"]["permit_id"],
         "source_native_evidence_digest": digest("native-evidence", change_source["change_evidence"]),
         "source_field": "destination_account", "target_field": "destination_account", "value": typed("t.identity", "acct-new")},
        {"binding_id": "payment-supplier-from-master", "source_occurrence_id": change_source["payment_occ"]["predecessor_occurrence_ids"][0],
         "source_permit_digest": change_source["change_permit"]["permit_id"],
         "source_native_evidence_digest": digest("native-evidence", change_source["change_evidence"]),
         "source_field": "supplier_id", "target_field": "supplier_id", "value": typed("t.identity", "supplier-17")},
    ]
    separation_basis = {"requirement_id": "confirmer-differs-from-payment-releaser", "relation": "DISTINCT_ACTOR",
                        "prior_occurrence_id": change_source["payment_occ"]["predecessor_occurrence_ids"][0],
                        "current_occurrence_id": change_source["payment_occ"]["occurrence_id"],
                        "prior_act": {"act_digest": digest("authority-act", change_gate), "act": change_gate},
                        "current_act": {"act_digest": digest("authority-act", current_gate), "act": current_gate}}
    first_proposal_digest = digest("proposal", first["event"])
    first_permit = {"schema": SCHEMA + "permit", "permit_id": "sha256:" + "0" * 64, "instance_id": instance_material["a"]["instance_id"],
                    "work_class_digest": definition_digest, "profile": PROFILE, "role": ROLE, "occurrence": change_source["payment_occ"],
                    "proposal_digest": first_proposal_digest, "native_request": first["native_request"], "executor": first["executor"],
                    "credential_ids": [first["authority"]["credential"]["id"]], "authority_result": first["authority"]["result"],
                    "authority_result_digest": first["authority"]["result_digest"], "authority_evidence_digest": first["authority"]["result"]["evidence_digest"],
                    "authority_act_bases": sorted([{"act_digest": digest("authority-act", row), "act": row} for row in first["authority"]["acts"]], key=lambda row: row["act_digest"].encode("utf-8")),
                    "prior_effect_bases": prior_bases, "separation_bases": [separation_basis], "observation_digests": first["obs_digests"],
                    "supersedes_permit_digest": None,
                    "budget_revisions": [{"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "revision": "2",
                                          "reservation_id": first["reservation_event_id"], "receipt_digest": first_reserve_result["receipt_digest"]}],
                    "clock_source": "governance-clock", "clock_revision": "1", "expires_at": PERMIT_EXPIRY}
    first_permit["permit_id"] = digest("permit", omit(first_permit, "permit_id"))
    def apply_first_proposal(state, event_digest):
        state["total_actuations"] = "2"
        next(row for row in state["step_counters"] if row["step_id"] == "pay-invoice")["actuations"] = "1"
        state["active"][0]["status"] = "PERMITTED"
        state["proposals"].append({"event_id": first["event"]["event_id"], "event_digest": event_digest, "proposal_digest": first_proposal_digest,
                                    "occurrence_id": change_source["payment_occ"]["occurrence_id"], "disposition": "PERMITTED", "permit_digest": first_permit["permit_id"],
                                    "authority_result_digest": first["authority"]["result_digest"], "reservation_receipt_digests": [first_reserve_result["receipt_digest"]],
                                    "prior_permit_digest": None})
        state["proposals"].sort(key=lambda row: row["event_id"].encode())
        state["permits"].append(first_permit); state["permits"].sort(key=lambda row: row["permit_id"].encode())
    state_payment_permitted, payment_proposal_result = work_transition(change_source["state_payment_active"], first["event"], disposition="PERMITTED", reasons=[], details=[],
                                                                       permit=first_permit, budget_results=[first_budget_result],
                                                                       authority_result_digest=first["authority"]["result_digest"],
                                                                       reservation_receipt_digests=[first_reserve_result["receipt_digest"]], mutate=apply_first_proposal)

    # Payment dispatch, unknown outcome, and later matching settlement.
    payment_connector = {"id": "payment-connector", "version": "v1", "binding_digest": "sha256:" + "0" * 64}
    payment_connector["binding_digest"] = digest("connector-binding", omit(payment_connector, "binding_digest"))
    payment_attempt = {"attempt_id": "payment-attempt-a-1", "status": "SENT",
                       "request_digest": digest("dispatch-native-request", {"instance_id": instance_material["a"]["instance_id"],
                                                                             "occurrence_id": change_source["payment_occ"]["occurrence_id"],
                                                                             "interface": "payment-system", "operation": "pay-invoice", "fields": first["fields"]}),
                       "attempted_at": NOW}
    payment_ack = {"status": "ACCEPTED", "reference": "payment-ack-a-1", "observed_at": NOW}
    payment_dispatch_event = {"schema": SCHEMA + "runtime-event", "event_id": "dispatch-payment-a-1", "kind": "DISPATCH_OBSERVED",
                              "instance_id": instance_material["a"]["instance_id"], "expected_state_revision": "5",
                              "expected_state_digest": work_state_digest(state_payment_permitted), "permit": first_permit,
                              "native_request": first["native_request"], "connector": payment_connector, "attempt": payment_attempt,
                              "acknowledgement": payment_ack, "clock_revision": "1"}
    dispatch_event_digest = digest("runtime-event", payment_dispatch_event)
    payment_attempt_digest = digest("dispatch-attempt", {"permit_id": first_permit["permit_id"], "native_request": first["native_request"],
                                                          "connector": payment_connector, "attempt": payment_attempt})
    payment_dispatch_record = {"dispatch_digest": "sha256:" + "0" * 64, "dispatch_attempt_digest": payment_attempt_digest,
                               "event_id": payment_dispatch_event["event_id"], "event_digest": dispatch_event_digest,
                               "permit_digest": first_permit["permit_id"], "native_request": first["native_request"], "connector": payment_connector,
                               "attempt": payment_attempt, "acknowledgement": payment_ack, "clock_revision": "1"}
    payment_dispatch_record["dispatch_digest"] = digest("dispatch", omit(payment_dispatch_record, "dispatch_digest"))
    def apply_payment_dispatch(state, _):
        state["active"][0]["status"] = "DISPATCHED"; state["dispatches"].append(payment_dispatch_record); state["dispatches"].sort(key=lambda row: row["dispatch_digest"].encode())
    state_payment_dispatched, payment_dispatch_result = work_transition(state_payment_permitted, payment_dispatch_event, disposition="ACKNOWLEDGED", reasons=[],
                                                                         details=[{"kind": "DISPATCH", "attempt_id": payment_attempt["attempt_id"], "reasons": []}],
                                                                         permit=None, budget_results=[], authority_result_digest=None,
                                                                         reservation_receipt_digests=[], mutate=apply_payment_dispatch)
    payment_attributed = {"work_class": work_class["id"], "instance": instance_material["a"]["instance_id"],
                          "occurrence": change_source["payment_occ"]["occurrence_id"], "step": "pay-invoice",
                          "operation": "pay-invoice", "interface": "payment-system", "fields": first["fields"]}
    unknown_evidence = {"evidence_id": "payment-unknown-a-1", "native_operation_id": "payment-native-a-1", "provider": "payment-provider",
                        "source": "payment-ledger", "record_type": "invoice-payment", "record_digest": digest("specimen-native-record", {"id": "payment-unknown-a-1"}),
                        "evidence_ref": "payment-unknown-record-a-1", "attributed_request": payment_attributed,
                        "native_request_digest": digest("native-request", payment_attributed), "status": "OUTCOME_UNKNOWN", "actual_fields": [],
                        "collections": [], "event_time": None, "observed_at": NOW, "rules_out_past_and_future_effects": False}
    unknown_native = {"id": unknown_evidence["evidence_id"], "provider": "payment-provider", "source": "payment-ledger",
                      "reservation": first["reservation_event_id"], "outcome": "UNKNOWN", "request": payment_attributed,
                      "effect_id": None, "occurred_at": None, "rules_out_past_and_future_effects": False,
                      "evidence_ref": unknown_evidence["evidence_ref"], "observed_request": None, "actual_fields": [], "collections": [],
                      "completion_mismatch": False, "mismatch_reason": None}
    unknown_lifecycle_id = "effect-payment-unknown-a-1"
    unknown_registry_event = {"id": digest("lifecycle-reservation-event", {"instance_id": instance_material["a"]["instance_id"],
                                                                            "lifecycle_event_id": unknown_lifecycle_id, "lifecycle_event_kind": "EFFECT_OBSERVED",
                                                                            "reservation_event_kind": "SETTLE", "registry_digest": registry_digest}),
                              "expected_revision": "2", "kind": "SETTLE", "clock": first["authority"]["input"]["clock"],
                              "payload": {"native": unknown_native, "histories": [initial_history]}, "administration": None}
    unknown_host = {"registry_digest": registry_digest, "selection_evidence": "supplier-payment-registry-selection", "administration_bases": [],
                    "authenticated_records": sorted_utf8([
                        {"kind": "HISTORY", "record_digest": digest("budget-history", initial_history), "provider": "payment-provider", "source": "payment-ledger"},
                        {"kind": "NATIVE_OUTCOME", "record_digest": digest("reservation-native-outcome", unknown_native), "provider": "payment-provider", "source": "payment-ledger"},
                    ])}
    unknown_input = {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": registry_after_first,
                     "state_digest": reservation_state_digest(registry_after_first), "event": unknown_registry_event, "host_evidence": unknown_host}
    def apply_unknown(state):
        state["core"]["reservations"][0]["status"] = "UNKNOWN"
        state["core"]["effects"] = [{"id": unknown_native["id"], "native": unknown_native,
                                      "native_digest": digest("reservation-native-outcome", unknown_native),
                                      "reservation": first["reservation_event_id"], "disposition": "UNKNOWN",
                                      "affected_anchors": ["supplier-payment-cap"], "blocked_partitions": [], "reason": "UNKNOWN_OUTCOME"}]
    registry_unknown, unknown_result = reservation_transition(registry_after_first, unknown_registry_event, unknown_host,
                                                              decision="UNKNOWN", reservation_id=first["reservation_event_id"], budgets=[],
                                                              authority_result=None, reasons=[], mutate=apply_unknown)
    unknown_budget = {"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "result": unknown_result}
    unknown_event = {"schema": SCHEMA + "runtime-event", "event_id": unknown_lifecycle_id, "kind": "EFFECT_OBSERVED",
                     "instance_id": instance_material["a"]["instance_id"], "expected_state_revision": "6",
                     "expected_state_digest": work_state_digest(state_payment_dispatched), "permit": first_permit,
                     "dispatch_digest": payment_dispatch_record["dispatch_digest"], "native_evidence": unknown_evidence,
                     "completion_authorization": None,
                     "budget_inputs": [{"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "expected_revision": "2", "request": unknown_input}],
                     "clock_revision": "1", "activation_clocks": []}
    unknown_event_digest = digest("runtime-event", unknown_event)
    unknown_outcome = {"kind": "GOVERNED", "outcome_digest": "sha256:" + "0" * 64, "event_id": unknown_lifecycle_id,
                       "event_digest": unknown_event_digest, "permit_digest": first_permit["permit_id"],
                       "dispatch_digest": payment_dispatch_record["dispatch_digest"], "dispatch_attempt_digest": payment_attempt_digest,
                       "native_evidence": unknown_evidence, "classification": "UNKNOWN", "reservation_receipt_digests": [unknown_result["receipt_digest"]],
                       "conflicts_with_evidence_ids": [], "disputed": False}
    unknown_outcome["outcome_digest"] = digest("outcome", omit(unknown_outcome, "outcome_digest"))
    def apply_unknown_work(state, _):
        state["active"][0]["status"] = "OUTCOME_UNKNOWN"; state["outcomes"].append(unknown_outcome); state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode())
    state_unknown, unknown_work_result = work_transition(state_payment_dispatched, unknown_event, disposition="OUTCOME_RETAINED", reasons=["UNKNOWN_OUTCOME"],
                                                         details=[{"kind": "BUDGET", "registry_digest": registry_digest, "receipt_digest": unknown_result["receipt_digest"], "reasons": unknown_result["receipt"]["reasons"]}, {"kind": "EFFECT", "classification": "UNKNOWN", "evidence_id": unknown_evidence["evidence_id"]}],
                                                         permit=None, budget_results=[unknown_budget], authority_result_digest=None,
                                                         reservation_receipt_digests=[unknown_result["receipt_digest"]], mutate=apply_unknown_work)
    payment_actual = first["fields"] + [field("status", "t.status", "SUCCEEDED")]
    payment_actual.sort(key=lambda row: row["name"].encode())
    settled_evidence = {"evidence_id": "payment-settled-a-1", "native_operation_id": "payment-native-a-1", "provider": "payment-provider",
                        "source": "payment-ledger", "record_type": "invoice-payment",
                        "record_digest": digest("specimen-native-record", {"id": "payment-settled-a-1", "actual_fields": payment_actual}),
                        "evidence_ref": "payment-settled-record-a-1", "attributed_request": payment_attributed,
                        "native_request_digest": digest("native-request", payment_attributed), "status": "EFFECT_ESTABLISHED",
                        "actual_fields": payment_actual, "collections": [], "event_time": NOW, "observed_at": NOW,
                        "rules_out_past_and_future_effects": False}
    payment_committed_event = {"id": digest("reservation-committed-event", {"budget_digest": budget_digest, "effect_id": settled_evidence["native_operation_id"], "mapping": "invoice-payment-amount"}), "state": "ACTIVE", "occurred_at": NOW,
                               "fields": [field("amount", "b.money", "150"), field("supplier_id", "b.identity", "supplier-17")]}
    settled_history = {**initial_history, "revision": "2", "journal": [initial_history["journal"][0], {"sequence": "2", "event": payment_committed_event}],
                       "evidence_ref": "payment-history-950"}
    settled_native = {"id": settled_evidence["evidence_id"], "provider": "payment-provider", "source": "payment-ledger",
                      "reservation": first["reservation_event_id"], "outcome": "EFFECT", "request": payment_attributed,
                      "effect_id": settled_evidence["native_operation_id"], "occurred_at": NOW, "rules_out_past_and_future_effects": False,
                      "evidence_ref": settled_evidence["evidence_ref"], "observed_request": payment_attributed,
                      "actual_fields": payment_actual, "collections": [], "completion_mismatch": False, "mismatch_reason": None}
    settled_lifecycle_id = "effect-payment-settled-a-1"
    settled_registry_event = {"id": digest("lifecycle-reservation-event", {"instance_id": instance_material["a"]["instance_id"],
                                                                            "lifecycle_event_id": settled_lifecycle_id, "lifecycle_event_kind": "EFFECT_OBSERVED",
                                                                            "reservation_event_kind": "SETTLE", "registry_digest": registry_digest}),
                              "expected_revision": "3", "kind": "SETTLE", "clock": first["authority"]["input"]["clock"],
                              "payload": {"native": settled_native, "histories": [settled_history]}, "administration": None}
    settled_host = {"registry_digest": registry_digest, "selection_evidence": "supplier-payment-registry-selection", "administration_bases": [],
                    "authenticated_records": sorted_utf8([
                        {"kind": "HISTORY", "record_digest": digest("budget-history", settled_history), "provider": "payment-provider", "source": "payment-ledger"},
                        {"kind": "NATIVE_OUTCOME", "record_digest": digest("reservation-native-outcome", settled_native), "provider": "payment-provider", "source": "payment-ledger"},
                    ])}
    settled_input = {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": registry_unknown,
                     "state_digest": reservation_state_digest(registry_unknown), "event": settled_registry_event, "host_evidence": settled_host}
    def apply_settled(state):
        state["core"]["budgets"][0]["history"] = settled_history
        state["core"]["reservations"][0]["status"] = "SETTLED"; state["core"]["reservations"][0]["matched_effect"] = "payment-native-a-1"
        state["core"]["effects"].append({"id": settled_native["id"], "native": settled_native,
                                          "native_digest": digest("reservation-native-outcome", settled_native),
                                          "reservation": first["reservation_event_id"], "disposition": "MATCHED",
                                          "affected_anchors": ["supplier-payment-cap"], "blocked_partitions": [], "reason": "MATCHED_EFFECT"})
        state["core"]["effects"].sort(key=lambda row: row["id"].encode())
    registry_settled, settled_result = reservation_transition(registry_unknown, settled_registry_event, settled_host,
                                                              decision="SETTLED", reservation_id=first["reservation_event_id"], budgets=[],
                                                              authority_result=None, reasons=[], mutate=apply_settled)
    settled_budget = {"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "result": settled_result}
    settled_event = {"schema": SCHEMA + "runtime-event", "event_id": settled_lifecycle_id, "kind": "EFFECT_OBSERVED",
                     "instance_id": instance_material["a"]["instance_id"], "expected_state_revision": "7",
                     "expected_state_digest": work_state_digest(state_unknown), "permit": first_permit,
                     "dispatch_digest": payment_dispatch_record["dispatch_digest"], "native_evidence": settled_evidence,
                     "completion_authorization": None,
                     "budget_inputs": [{"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "expected_revision": "3", "request": settled_input}],
                     "clock_revision": "1", "activation_clocks": []}
    settled_event_digest = digest("runtime-event", settled_event)
    settled_outcome = {"kind": "GOVERNED", "outcome_digest": "sha256:" + "0" * 64, "event_id": settled_lifecycle_id,
                       "event_digest": settled_event_digest, "permit_digest": first_permit["permit_id"],
                       "dispatch_digest": payment_dispatch_record["dispatch_digest"], "dispatch_attempt_digest": payment_attempt_digest,
                       "native_evidence": settled_evidence, "classification": "MATCHED", "reservation_receipt_digests": [settled_result["receipt_digest"]],
                       "conflicts_with_evidence_ids": [], "disputed": False}
    settled_outcome["outcome_digest"] = digest("outcome", omit(settled_outcome, "outcome_digest"))
    payment_relation_digest = digest("relationship", work_class["relationships"][1])
    completed_payment = {"occurrence": change_source["payment_occ"], "disposition": "SUCCEEDED", "evidence_digest": digest("native-evidence", settled_evidence),
                         "occurred_at": NOW, "route_label": None, "selected_relationship_digest": payment_relation_digest, "late": False}
    def apply_settled_work(state, _):
        state["status"] = "COMPLETE"; state["active"] = []; state["completed"].append(completed_payment)
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["outcomes"].append(settled_outcome); state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode())
    state_complete, settled_work_result = work_transition(state_unknown, settled_event, disposition="COMPLETED", reasons=[],
                                                           details=[{"kind": "BUDGET", "registry_digest": registry_digest, "receipt_digest": settled_result["receipt_digest"], "reasons": settled_result["receipt"]["reasons"]}, {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": settled_evidence["evidence_id"]},
                                                                    {"kind": "ROUTE", "relationship_digests": [payment_relation_digest], "construct_ids": []}],
                                                           permit=None, budget_results=[settled_budget], authority_result_digest=None,
                                                           reservation_receipt_digests=[settled_result["receipt_digest"]], mutate=apply_settled_work)

    valid_requests = instance_material["a"]["requests"] + [
        first["request"],
        protocol_request("dispatch-payment-a-1", "step", {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class,
                                                           "definition_digest": definition_digest, "state": state_payment_permitted,
                                                           "state_digest": work_state_digest(state_payment_permitted), "event": payment_dispatch_event}),
        protocol_request(unknown_lifecycle_id, "step", {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class,
                                                        "definition_digest": definition_digest, "state": state_payment_dispatched,
                                                        "state_digest": work_state_digest(state_payment_dispatched), "event": unknown_event}),
        protocol_request(settled_lifecycle_id, "step", {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class,
                                                        "definition_digest": definition_digest, "state": state_unknown,
                                                        "state_digest": work_state_digest(state_unknown), "event": settled_event}),
    ]
    valid_results = [{"protocol": PROTOCOL, "request_id": row["request_id"], "operation": row["operation"], "result": result}
                     for row, result in zip(valid_requests, instance_material["a"]["results"] + [payment_proposal_result, payment_dispatch_result, unknown_work_result, settled_work_result])]

    # Scenario-only exact requests. Each starts from an admitted checkpoint named in the request itself.
    stale_second = copy.deepcopy(payment_proposals["b"]["request"])
    stale_second["request_id"] = "supplier-payment-second-stale"
    stale_second["input"]["event"]["budget_inputs"][0]["request"]["state"] = registry_registered
    stale_second["input"]["event"]["budget_inputs"][0]["request"]["state_digest"] = reservation_state_digest(registry_registered)
    retry_second = copy.deepcopy(payment_proposals["b"]["request"])
    retry_second["request_id"] = "supplier-payment-second-retry-withheld"
    retry_event = retry_second["input"]["event"]
    retry_event["event_id"] = "propose-payment-b-2"
    retry_reserve = retry_event["budget_inputs"][0]["request"]
    retry_reserve["state"] = registry_after_first; retry_reserve["state_digest"] = reservation_state_digest(registry_after_first)
    retry_reserve["event"]["id"] = digest("lifecycle-reservation-event", {"instance_id": instance_material["b"]["instance_id"],
                                                                          "lifecycle_event_id": retry_event["event_id"], "lifecycle_event_kind": "PROPOSE",
                                                                          "reservation_event_kind": "RESERVE", "registry_digest": registry_digest})
    retry_reserve["event"]["expected_revision"] = "2"
    retry_event["budget_inputs"][0]["expected_revision"] = "2"
    retry_event["budget_inputs"][0]["request"]["event"]["payload"]["histories"] = [initial_history]

    revoked = copy.deepcopy(first["request"])
    revoked["request_id"] = "supplier-payment-revoked-authority"
    revoked_auth = build_authority(authority_source, authority_work_class, instance_id=instance_material["a"]["instance_id"], occurrence_row=change_source["payment_occ"],
                                   step_id="pay-invoice", envelope_id="invoice-payment-authority", executor_id="payment-agent-1", executor_role="payment-agent",
                                   credential_kind="payment-credential", gate_kind="DECIDE", gate_actor="payment-releaser-person", gate_role="payment-releaser",
                                   subject_fields=["supplier_id"], resource_fields=["destination_account", "invoice_id"], proposal_fields=first["fields"],
                                   required_budgets=["supplier-payment-cap"], revoked=True)
    revoked["input"]["event"]["authority_input"] = revoked_auth["input"]
    revoked["input"]["event"]["observation_digests"] = sorted_utf8([digest("authority-observation", row) for row in revoked_auth["input"]["observations"]])
    revoked["input"]["event"]["budget_inputs"][0]["request"]["event"]["payload"]["authority"] = revoked_auth["input"]

    expired = copy.deepcopy(first["request"])
    expired["request_id"] = "supplier-payment-expired-authority"
    expired_auth = build_authority(authority_source, authority_work_class, instance_id=instance_material["a"]["instance_id"], occurrence_row=change_source["payment_occ"],
                                   step_id="pay-invoice", envelope_id="invoice-payment-authority", executor_id="payment-agent-1", executor_role="payment-agent",
                                   credential_kind="payment-credential", gate_kind="DECIDE", gate_actor="payment-releaser-person", gate_role="payment-releaser",
                                   subject_fields=["supplier_id"], resource_fields=["destination_account", "invoice_id"], proposal_fields=first["fields"],
                                   required_budgets=["supplier-payment-cap"], expired=True)
    expired["input"]["event"]["authority_input"] = expired_auth["input"]
    expired["input"]["event"]["observation_digests"] = sorted_utf8([digest("authority-observation", row) for row in expired_auth["input"]["observations"]])
    expired["input"]["event"]["budget_inputs"][0]["request"]["event"]["payload"]["authority"] = expired_auth["input"]

    # AUTHORITY-CHECKS failed_checks: the revoked current envelope query and the expired envelope validity check.
    revoked_query = {"purpose": "REVOCATION", "subject_digest": revoked_auth["envelope_digest"], "at": NOW, "provider": "identity-provider", "source": "authority-revocations"}
    revoked_failed_checks = [{"purpose": "REVOCATION", "subject_digest": revoked_auth["envelope_digest"], "requirement_ref": digest("authority-query", revoked_query), "at": NOW, "reason": "REVOKED"}]
    expired_failed_checks = [{"purpose": "ENVELOPE_VALIDITY", "subject_digest": expired_auth["envelope_digest"], "requirement_ref": "invoice-payment-authority", "at": NOW, "reason": "ENVELOPE_EXPIRED"}]

    old_destination = copy.deepcopy(first["request"])
    old_destination["request_id"] = "supplier-payment-old-destination"
    for row in old_destination["input"]["event"]["native_request"]["fields"]:
        if row["name"] == "destination_account": row["value"]["value"] = "acct-old"
    old_destination_fields = copy.deepcopy(first["fields"])
    next(row for row in old_destination_fields if row["name"] == "destination_account")["value"]["value"] = "acct-old"
    old_destination_auth = build_authority(
        authority_source, authority_work_class, instance_id=instance_material["a"]["instance_id"],
        occurrence_row=change_source["payment_occ"], step_id="pay-invoice", envelope_id="invoice-payment-authority",
        executor_id="payment-agent-1", executor_role="payment-agent", credential_kind="payment-credential",
        gate_kind="DECIDE", gate_actor="payment-releaser-person", gate_role="payment-releaser",
        subject_fields=["supplier_id"], resource_fields=["destination_account", "invoice_id"],
        proposal_fields=old_destination_fields, required_budgets=["supplier-payment-cap"],
    )
    old_destination["input"]["event"]["authority_input"] = old_destination_auth["input"]
    old_destination["input"]["event"]["observation_digests"] = sorted_utf8(
        [digest("authority-observation", row) for row in old_destination_auth["input"]["observations"]]
    )
    old_destination["input"]["event"]["budget_inputs"][0]["request"]["event"]["payload"]["authority"] = old_destination_auth["input"]

    same_actor = copy.deepcopy(first["request"])
    same_actor["request_id"] = "supplier-payment-same-confirmation-and-release-actor"
    same_actor_auth = build_authority(
        authority_source, authority_work_class, instance_id=instance_material["a"]["instance_id"],
        occurrence_row=change_source["payment_occ"], step_id="pay-invoice", envelope_id="invoice-payment-authority",
        executor_id="payment-agent-1", executor_role="payment-agent", credential_kind="payment-credential",
        gate_kind="DECIDE", gate_actor="destination-confirmer-person", gate_role="payment-releaser",
        subject_fields=["supplier_id"], resource_fields=["destination_account", "invoice_id"],
        proposal_fields=first["fields"], required_budgets=["supplier-payment-cap"],
    )
    same_actor["input"]["event"]["authority_input"] = same_actor_auth["input"]
    same_actor["input"]["event"]["observation_digests"] = sorted_utf8(
        [digest("authority-observation", row) for row in same_actor_auth["input"]["observations"]]
    )
    same_actor["input"]["event"]["budget_inputs"][0]["request"]["event"]["payload"]["authority"] = same_actor_auth["input"]

    changed_dispatch = copy.deepcopy(valid_requests[6])
    changed_dispatch["request_id"] = "supplier-payment-changed-dispatch"
    # The valid request intentionally reuses its permit's native-request object.
    # Break that construction-time alias before changing only the observed dispatch request.
    changed_dispatch["input"]["event"]["native_request"] = copy.deepcopy(changed_dispatch["input"]["event"]["native_request"])
    for row in changed_dispatch["input"]["event"]["native_request"]["fields"]:
        if row["name"] == "amount": row["value"]["value"] = "151"
    changed_dispatch["input"]["event"]["attempt"]["status"] = "NOT_SENT"
    changed_dispatch["input"]["event"]["attempt"]["request_digest"] = digest("dispatch-native-request", {
        "instance_id": instance_material["a"]["instance_id"], "occurrence_id": change_source["payment_occ"]["occurrence_id"],
        "interface": "payment-system", "operation": "pay-invoice", "fields": changed_dispatch["input"]["event"]["native_request"]["fields"]})
    changed_dispatch["input"]["event"]["acknowledgement"] = {"status": "NONE", "reference": None, "observed_at": None}

    exact_replay = copy.deepcopy(valid_requests[-1])
    exact_replay["request_id"] = "supplier-payment-settlement-replay"
    exact_replay["input"]["state"] = state_complete; exact_replay["input"]["state_digest"] = work_state_digest(state_complete)

    unexpected_fields = copy.deepcopy(first["fields"])
    next(row for row in unexpected_fields if row["name"] == "amount")["value"]["value"] = "151"
    unexpected_actual = unexpected_fields + [field("status", "t.status", "SUCCEEDED")]
    unexpected_actual.sort(key=lambda row: row["name"].encode())
    unexpected_evidence = {
        "evidence_id": "payment-unexpected-a-1",
        "native_operation_id": "payment-native-unexpected-a-1",
        "provider": "payment-provider",
        "source": "payment-ledger",
        "record_type": "invoice-payment",
        "record_digest": digest("specimen-native-record", {"id": "payment-unexpected-a-1", "actual_fields": unexpected_actual}),
        "evidence_ref": "payment-unexpected-record-a-1",
        "attributed_request": payment_attributed,
        "native_request_digest": digest("native-request", payment_attributed),
        "status": "EFFECT_ESTABLISHED",
        "actual_fields": unexpected_actual,
        "collections": [],
        "event_time": NOW,
        "observed_at": NOW,
        "rules_out_past_and_future_effects": False,
    }
    unexpected_observed_request = None
    unexpected_native = {
        "id": unexpected_evidence["evidence_id"],
        "provider": "payment-provider",
        "source": "payment-ledger",
        "reservation": first["reservation_event_id"],
        "outcome": "EFFECT",
        "request": payment_attributed,
        "effect_id": unexpected_evidence["native_operation_id"],
        "occurred_at": NOW,
        "rules_out_past_and_future_effects": False,
        "evidence_ref": unexpected_evidence["evidence_ref"],
        "observed_request": unexpected_observed_request,
        "actual_fields": unexpected_actual,
        "collections": [],
        "completion_mismatch": True,
        "mismatch_reason": "UNEXPECTED_EFFECT",
    }
    unexpected_committed_event = {
        "id": digest("reservation-committed-event", {"budget_digest": budget_digest, "effect_id": unexpected_evidence["native_operation_id"], "mapping": "invoice-payment-amount"}),
        "state": "ACTIVE",
        "occurred_at": NOW,
        "fields": [field("amount", "b.money", "151"), field("supplier_id", "b.identity", "supplier-17")],
    }
    unexpected_history = {
        **initial_history,
        "revision": "2",
        "journal": [initial_history["journal"][0], {"sequence": "2", "event": unexpected_committed_event}],
        "evidence_ref": "payment-history-unexpected-951",
    }
    unexpected_lifecycle_id = "effect-payment-unexpected-a-1"
    unexpected_registry_event = {
        "id": digest("lifecycle-reservation-event", {
            "instance_id": instance_material["a"]["instance_id"],
            "lifecycle_event_id": unexpected_lifecycle_id,
            "lifecycle_event_kind": "EFFECT_OBSERVED",
            "reservation_event_kind": "SETTLE",
            "registry_digest": registry_digest,
        }),
        "expected_revision": "2",
        "kind": "SETTLE",
        "clock": first["authority"]["input"]["clock"],
        "payload": {"native": unexpected_native, "histories": [unexpected_history]},
        "administration": None,
    }
    unexpected_host = {
        "registry_digest": registry_digest,
        "selection_evidence": "supplier-payment-registry-selection",
        "administration_bases": [],
        "authenticated_records": sorted_utf8([
            {"kind": "HISTORY", "record_digest": digest("budget-history", unexpected_history), "provider": "payment-provider", "source": "payment-ledger"},
            {"kind": "NATIVE_OUTCOME", "record_digest": digest("reservation-native-outcome", unexpected_native), "provider": "payment-provider", "source": "payment-ledger"},
        ]),
    }
    unexpected_reservation_input = {
        "schema": SCHEMA + "reservation-input",
        "specification_pin": PIN,
        "state": registry_after_first,
        "state_digest": reservation_state_digest(registry_after_first),
        "event": unexpected_registry_event,
        "host_evidence": unexpected_host,
    }
    unexpected_event = {
        "schema": SCHEMA + "runtime-event",
        "event_id": unexpected_lifecycle_id,
        "kind": "EFFECT_OBSERVED",
        "instance_id": instance_material["a"]["instance_id"],
        "expected_state_revision": "6",
        "expected_state_digest": work_state_digest(state_payment_dispatched),
        "permit": first_permit,
        "dispatch_digest": payment_dispatch_record["dispatch_digest"],
        "native_evidence": unexpected_evidence,
        "completion_authorization": None,
        "budget_inputs": [{
            "registry_digest": registry_digest,
            "affected_anchors": ["supplier-payment-cap"],
            "expected_revision": "2",
            "request": unexpected_reservation_input,
        }],
        "clock_revision": "1",
        "activation_clocks": [],
    }
    unexpected_request = protocol_request(unexpected_lifecycle_id, "step", {
        "profile": PROFILE,
        "role": ROLE,
        "specification_pin": PIN,
        "definition": work_class,
        "definition_digest": definition_digest,
        "state": state_payment_dispatched,
        "state_digest": work_state_digest(state_payment_dispatched),
        "event": unexpected_event,
    })

    commit_failure_case = {
        "candidate_pin": PIN,
        "id": "supplier-payment-commit-failure",
        "kind": "HOST_HARNESS_CASE",
        "input": {
            "kind": "COMMIT",
            "transaction_digest": payment_proposal_result["transaction_digest"],
            "authoritative_state_digest": work_state_digest(change_source["state_payment_active"]),
            "authoritative_budgets": [{"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "state_digest": reservation_state_digest(registry_registered)}],
            "calculated_state_digest": work_state_digest(state_payment_permitted),
            "calculated_budgets": [{"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "state_digest": reservation_state_digest(registry_after_first)}],
            "inject_failure": True,
            "failure_reference": "supplier-payment-injected-before-root-swap",
        },
        "expected": {
            "status": "HOST_COMMIT",
            "disposition": "COMMIT_FAILED",
            "transaction_digest": payment_proposal_result["transaction_digest"],
            "state_before_digest": work_state_digest(change_source["state_payment_active"]),
            "authoritative_state_digest": work_state_digest(change_source["state_payment_active"]),
            "budget_before": [{"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "state_digest": reservation_state_digest(registry_registered)}],
            "authoritative_budgets": [{"registry_digest": registry_digest, "affected_anchors": ["supplier-payment-cap"], "state_digest": reservation_state_digest(registry_registered)}],
            "failure_reference": "supplier-payment-injected-before-root-swap",
            "dispatch_performed": False,
        },
        "derivation": "The injected failure occurs before the host's one authoritative-root swap. The prior work and registry roots remain authoritative, the failed transaction is not installed, and dispatch is prohibited.",
        "normative_references": ["LIFE-005", "LIFE-008", "LIFE-020"],
    }

    scenario_requests = [payment_proposals["a"]["request"], payment_proposals["b"]["request"], stale_second, retry_second,
                         revoked, expired, old_destination, same_actor, changed_dispatch, valid_requests[6], valid_requests[7], valid_requests[8],
                         unexpected_request, exact_replay]
    expectations = {
        "candidate_pin": PIN,
        "status": "DERIVED_PENDING_INDEPENDENT_REVIEW",
        "method": "Every judgment was derived from the cited normative contract before either draft-2 implementation or its output was inspected.",
        "scenarios": [
            {"id": "supplier-payment-valid", "input": {"trace": "valid-trace/requests.jsonl"},
             "expected_judgment": "The master change and payment are each permitted and dispatched; matching master evidence activates payment; unknown payment evidence retains exposure; later matching evidence settles and completes.",
             "state_and_budget_consequence": "The final instance is COMPLETE and the supplier partition contains 950 USD committed with no pending charge.",
             "normative_references": ["LIFE-007", "LIFE-010", "COMP-BIND-001", "RES-005", "RES-007"]},
            {"id": "supplier-payment-prior-effect-and-distinct-actors", "input": {"request_id": "propose-payment-a-1"},
             "expected_judgment": "STEP/PERMITTED with two prior-effect bases and one satisfied DISTINCT_ACTOR basis",
             "state_and_budget_consequence": "The permit binds supplier-17 and acct-new to the unique completed master-change effect and compares destination-confirmer-person with payment-releaser-person before reserving 150 USD.",
             "normative_references": ["COMP-BIND-001", "LIFE-007", "LIFE-008"]},
            {"id": "supplier-payment-two-concurrent-proposals", "input": {"request_ids": ["propose-payment-a-1", "propose-payment-b-1"]},
             "expected_judgment": "Each proposal is individually admissible against registry revision 1, but the serialized host commits only one",
             "state_and_budget_consequence": "One 150 USD reservation advances the registry to revision 2; the other client's stale registry root cannot commit.",
             "normative_references": ["RES-005", "RES-009", "LIFE-020"]},
            {"id": "supplier-payment-stale-second", "input": {"request_id": "supplier-payment-second-stale"},
             "expected_judgment": "REFUSED/REVISION_CONFLICT at the serialized host boundary",
             "state_and_budget_consequence": "Instance B and the authoritative revision-2 registry remain unchanged.",
             "normative_references": ["LIFE-005", "LIFE-020", "RES-WIRE-004"]},
            {"id": "supplier-payment-retry-withheld", "input": {"request_id": "supplier-payment-second-retry-withheld"},
             "expected_judgment": "STEP/WITHHELD with BUDGET_WITHHELD and BOUND_VIOLATED",
             "state_and_budget_consequence": "The registry records a withholding receipt at revision 3, but only the first 150 USD remains pending; 800 + 150 + 150 would be 1100.",
             "normative_references": ["AGG-008", "RES-005", "LIFE-007"]},
            {"id": "supplier-payment-revoked-authority", "input": {"request_id": "supplier-payment-revoked-authority"},
             "expected_judgment": "STEP/WITHHELD with AUTHORITY_REQUIRED, AUTHORITY_NOT_ESTABLISHED and REVOKED",
             "state_and_budget_consequence": "No permit or reservation is created.", "normative_references": ["AUTH-005", "AUTH-006", "LIFE-007"]},
            {"id": "supplier-payment-expired-authority", "input": {"request_id": "supplier-payment-expired-authority"},
             "expected_judgment": "STEP/WITHHELD with AUTHORITY_REQUIRED, AUTHORITY_NOT_ESTABLISHED and ENVELOPE_EXPIRED",
             "state_and_budget_consequence": "No permit or reservation is created.", "normative_references": ["AUTH-005", "AUTH-006", "LIFE-007"]},
            {"id": "supplier-payment-old-destination", "input": {"request_id": "supplier-payment-old-destination"},
             "expected_judgment": "REFUSED/BINDING_MISMATCH before authority",
             "state_and_budget_consequence": "The prior master effect established acct-new while the payment request names acct-old; work and budget remain unchanged.",
             "normative_references": ["COMP-BIND-001", "LIFE-006", "LIFE-007"]},
            {"id": "supplier-payment-same-confirmation-and-release-actor", "input": {"request_id": "supplier-payment-same-confirmation-and-release-actor"},
             "expected_judgment": "STEP/WITHHELD with SEPARATION_VIOLATED after authority succeeds and before budget evaluation",
             "state_and_budget_consequence": "The payment release act names the same person as the retained destination confirmation act. The work state records withholding, creates no permit, and leaves the registry unchanged.",
             "normative_references": ["COMP-BIND-001", "LIFE-006", "LIFE-007"]},
            {"id": "supplier-payment-changed-dispatch", "input": {"request_id": "supplier-payment-changed-dispatch"},
             "expected_judgment": "STEP/DISPATCH_REFUSED with NATIVE_ARGUMENT_MISMATCH and NATIVE_NOT_SENT",
             "state_and_budget_consequence": "The exact committed permit remains the only authority. The safe NOT_SENT observation is retained, and no connector invocation or effect is claimed.",
             "normative_references": ["LIFE-008", "LIFE-009"]},
            {"id": "supplier-payment-commit-failure", "input": {"case": "host/commit-failure-case.json"},
             "expected_judgment": "HOST_COMMIT/COMMIT_FAILED with dispatch_performed false",
             "state_and_budget_consequence": "The authoritative pre-proposal work and registry roots remain installed and no native dispatch occurs.",
             "normative_references": ["LIFE-005", "LIFE-008", "LIFE-020"]},
            {"id": "supplier-payment-acknowledgement-only", "input": {"request_id": "dispatch-payment-a-1"},
             "expected_judgment": "STEP/ACKNOWLEDGED",
             "state_and_budget_consequence": "The occurrence becomes DISPATCHED and the 150 USD reservation remains OPEN; acknowledgement is not settlement.",
             "normative_references": ["LIFE-001", "LIFE-009"]},
            {"id": "supplier-payment-unknown", "input": {"request_id": unknown_lifecycle_id},
             "expected_judgment": "STEP/OUTCOME_RETAINED with UNKNOWN and reservation UNKNOWN",
             "state_and_budget_consequence": "The occurrence becomes OUTCOME_UNKNOWN and the 150 USD pending charge remains counted.",
             "normative_references": ["LIFE-010", "RES-007"]},
            {"id": "supplier-payment-late-matching-settlement", "input": {"request_id": settled_lifecycle_id},
             "expected_judgment": "STEP/COMPLETED with MATCHED and reservation SETTLED",
             "state_and_budget_consequence": "The later matching fact replaces pending exposure with the 150 USD committed event exactly once and completes the instance.",
             "normative_references": ["LIFE-010", "LIFE-012", "RES-007"]},
            {"id": "supplier-payment-unexpected-effect", "input": {"request_id": unexpected_lifecycle_id},
             "expected_judgment": "STEP/DISPUTED with reservation EFFECT_DISPUTED/UNEXPECTED_EFFECT",
             "state_and_budget_consequence": "The effect is retained, pending exposure remains or is restored, the supplier partition is blocked, and no normal route occurs.",
             "normative_references": ["LIFE-010", "LIFE-013", "RES-007"]},
            {"id": "supplier-payment-restart-every-stage", "input": {"states": ["deployment", "proposal", "permit", "dispatch", "unknown", "settlement"]},
             "expected_judgment": "Every next request admits the complete supplied work and registry checkpoint without process-local history",
             "state_and_budget_consequence": "Each stage continues from the exact prior returned state; exact settlement replay changes no revision.",
             "normative_references": ["LIFE-013", "LIFE-019", "RES-WIRE-003"]},
        ],
    }

    exact_assertions = {
        "supplier-payment-valid": {
            "response_dispositions": ["DEPLOYED", "CLOCK_RECORDED", "PERMITTED", "ACKNOWLEDGED", "COMPLETED", "PERMITTED", "ACKNOWLEDGED", "OUTCOME_RETAINED", "COMPLETED"],
            "final_work_status": "COMPLETE",
            "final_work_revision": "8",
            "final_budget_revision": "4",
            "final_reservation_status": "SETTLED",
            "final_committed_accumulator": "950",
        },
        "supplier-payment-prior-effect-and-distinct-actors": {
            "status": "STEP", "disposition": "PERMITTED", "reason_codes": [],
            "prior_effect_binding_ids": ["payment-account-from-master", "payment-supplier-from-master"],
            "prior_actor_separation_ids": ["confirmer-differs-from-payment-releaser"],
            "prior_actor": "destination-confirmer-person", "current_actor": "payment-releaser-person",
            "budget_decisions": ["RESERVED"],
        },
        "supplier-payment-two-concurrent-proposals": {
            "both_calculated_from_registry_revision": "1", "individually_calculated_disposition": "PERMITTED",
            "maximum_commits": "1", "committed_registry_revision": "2",
        },
        "supplier-payment-stale-second": {
            "status": "REFUSED", "code": "REVISION_CONFLICT", "state_unchanged": True,
            "authoritative_registry_revision": "2", "dispatch_performed": False,
        },
        "supplier-payment-retry-withheld": {
            "status": "STEP", "disposition": "WITHHELD", "reason_codes": ["BOUND_VIOLATED", "BUDGET_WITHHELD"],
            "budget_decision": "WITHHELD", "budget_reasons": ["BOUND_VIOLATED"],
            "candidate_accumulator": "1100", "next_registry_revision": "3",
        },
        "supplier-payment-revoked-authority": {
            "status": "STEP", "disposition": "WITHHELD", "reason_codes": ["AUTHORITY_NOT_ESTABLISHED", "AUTHORITY_REQUIRED", "REVOKED"],
            "authority_status": "REFUSED", "authority_code": "AUTHORITY_NOT_ESTABLISHED",
            "authority_reasons": ["REVOKED"], "authority_failed_checks": revoked_failed_checks, "permit": None, "budget_results": [],
        },
        "supplier-payment-expired-authority": {
            "status": "STEP", "disposition": "WITHHELD", "reason_codes": ["AUTHORITY_NOT_ESTABLISHED", "AUTHORITY_REQUIRED", "ENVELOPE_EXPIRED"],
            "authority_status": "REFUSED", "authority_code": "AUTHORITY_NOT_ESTABLISHED",
            "authority_reasons": ["ENVELOPE_EXPIRED"], "authority_failed_checks": expired_failed_checks, "permit": None, "budget_results": [],
        },
        "supplier-payment-old-destination": {
            "status": "REFUSED", "code": "BINDING_MISMATCH", "state_unchanged": True, "budget_unchanged": True,
        },
        "supplier-payment-same-confirmation-and-release-actor": {
            "status": "STEP", "disposition": "WITHHELD", "reason_codes": ["SEPARATION_VIOLATED"],
            "separation_requirement_id": "confirmer-differs-from-payment-releaser",
            "prior_actor": "destination-confirmer-person", "current_actor": "destination-confirmer-person",
            "permit": None, "budget_results": [], "budget_unchanged": True,
        },
        "supplier-payment-changed-dispatch": {
            "status": "STEP", "disposition": "DISPATCH_REFUSED",
            "reason_codes": ["NATIVE_ARGUMENT_MISMATCH", "NATIVE_NOT_SENT"], "dispatch_record_added": True,
        },
        "supplier-payment-commit-failure": commit_failure_case["expected"],
        "supplier-payment-acknowledgement-only": {
            "status": "STEP", "disposition": "ACKNOWLEDGED", "occurrence_status": "DISPATCHED",
            "reservation_status": "OPEN", "work_revision": "6", "budget_revision": "2",
        },
        "supplier-payment-unknown": {
            "status": "STEP", "disposition": "OUTCOME_RETAINED", "reason_codes": ["UNKNOWN_OUTCOME"],
            "classification": "UNKNOWN", "occurrence_status": "OUTCOME_UNKNOWN", "budget_decision": "UNKNOWN",
            "reservation_status": "UNKNOWN", "pending_contribution": "150",
        },
        "supplier-payment-late-matching-settlement": {
            "status": "STEP", "disposition": "COMPLETED", "reason_codes": [], "classification": "MATCHED",
            "work_status": "COMPLETE", "budget_decision": "SETTLED", "reservation_status": "SETTLED",
            "committed_accumulator": "950", "pending_contribution": "0",
        },
        "supplier-payment-unexpected-effect": {
            "status": "STEP", "disposition": "DISPUTED", "reason_codes": ["BUDGET_EFFECT_DISPUTED", "UNEXPECTED_EFFECT"],
            "classification": "UNEXPECTED", "occurrence_status": "OUTCOME_UNKNOWN", "budget_decision": "EFFECT_DISPUTED",
            "budget_reasons": ["UNEXPECTED_EFFECT"], "reservation_status": "DISPUTED",
            "blocked_partitions": [{"anchor": "supplier-payment-cap", "key": None}],
        },
        "supplier-payment-restart-every-stage": {
            "checkpoint_index": "restart/checkpoints.json", "requires_process_local_history": False,
            "exact_replay": True, "replay_changes_work_revision": False, "replay_changes_budget_revision": False,
        },
    }
    for scenario in expectations["scenarios"]:
        scenario["expected_assertions"] = exact_assertions[scenario["id"]]

    restart_artifacts = {
        "restart/after-deployment-work-state.json": instance_material["a"]["results"][0]["state"],
        "restart/after-master-change-work-state.json": change_source["state_payment_active"],
        "restart/after-payment-permit-work-state.json": state_payment_permitted,
        "restart/after-payment-permit-budget-state.json": registry_after_first,
        "restart/after-payment-dispatch-work-state.json": state_payment_dispatched,
        "restart/after-payment-dispatch-budget-state.json": registry_after_first,
        "restart/after-payment-unknown-work-state.json": state_unknown,
        "restart/after-payment-unknown-budget-state.json": registry_unknown,
        "restart/after-payment-settlement-work-state.json": state_complete,
        "restart/after-payment-settlement-budget-state.json": registry_settled,
    }
    restart_checkpoints = {
        "candidate_pin": PIN,
        "note": "Proposal admission, permit creation and reservation commit form one transition, so the proposal and permit checkpoint is the same exact state.",
        "checkpoints": [],
    }
    for path, state in restart_artifacts.items():
        digest_kind = "reservation-state" if "budget-state" in path else "work-state"
        state_digest = reservation_state_digest(state) if digest_kind == "reservation-state" else work_state_digest(state)
        restart_checkpoints["checkpoints"].append({"path": path, "digest_kind": digest_kind, "state_digest": state_digest})
    restart_checkpoints["checkpoints"].sort(key=lambda row: row["path"].encode())


    write("valid-trace/requests.json", valid_requests)
    write("valid-trace/results-derived.json", valid_results)
    write("valid-trace/final-work-state.json", state_complete)
    write("valid-trace/final-budget-state.json", registry_settled)
    write("contention/requests.json", [payment_proposals["a"]["request"], payment_proposals["b"]["request"], stale_second, retry_second])
    write("host/commit-failure-case.json", commit_failure_case)
    write("scenarios/requests.json", scenario_requests)
    write("scenarios/expectations.json", expectations)
    write("readback-derived.json", readback_result)
    write("correspondence-record.json", correspondence_record)
    write("correspondence-input.json", correspondence_input)
    for path, state in restart_artifacts.items():
        write(path, state)
    write("restart/checkpoints.json", restart_checkpoints)
    (HERE / "valid-trace" / "requests.jsonl").write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in valid_requests))
    (HERE / "valid-trace" / "results-derived.jsonl").write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in valid_results))
    (HERE / "scenarios" / "requests.jsonl").write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in scenario_requests))

    index = {"candidate_pin": PIN, "construction": "INDEPENDENT_FROM_DRAFT2_IMPLEMENTATIONS", "status": "CONTRACT_DERIVED_CROSS_LANGUAGE_VERIFIED_NON_NORMATIVE", "files": []}
    for path in sorted(HERE.rglob("*.json")) + sorted(HERE.rglob("*.jsonl")):
        if path.name == "artifact-index.json":
            continue
        index["files"].append({"path": path.relative_to(HERE).as_posix(), "sha256": raw_sha(path.read_bytes())})
    write("artifact-index.json", index)


if __name__ == "__main__":
    main()
