#!/usr/bin/env python3
"""Build the draft-2 access-card specimen from the frozen normative rules.

This fixture constructor is deliberately independent of the draft-2 TypeScript
and Python consumers. It contains fixed specimen data and the digest projections
stated in the contract. It is not a general work-class evaluator.
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
INSTANCE = "access-card-instance-1"
NOW = "2026-09-10T12:00:00Z"
DEPLOYMENT_AUTHORIZED_AT = "2026-09-10T11:50:00Z"
EXPIRY = "2026-09-10T12:05:00Z"


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
        return "[" + ",".join(canonical_text(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            canonical_text(key) + ":" + canonical_text(value[key])
            for key in sorted(value, key=key_order)
        ) + "}"
    raise TypeError(f"restricted JSON excludes {type(value).__name__}")


def canonical_bytes(value) -> bytes:
    return canonical_text(value).encode("utf-8")


def digest(kind: str, value) -> str:
    return "sha256:" + hashlib.sha256(PREFIX + kind.encode() + b"\n" + canonical_bytes(value)).hexdigest()


def raw_sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def omit(value: dict, *keys: str) -> dict:
    result = copy.deepcopy(value)
    for key in keys:
        result.pop(key, None)
    return result


def sorted_utf8(values):
    return sorted(values, key=lambda item: canonical_bytes(item) if not isinstance(item, str) else item.encode("utf-8"))


def write(name: str, value) -> None:
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def typed(type_ref: str, value):
    return {"type_ref": type_ref, "value": value}


def field(name: str, type_ref: str, value):
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


def work_state_digest(state):
    projected = copy.deepcopy(state)
    for replay in projected["replays"]:
        replay.pop("transaction_digest")
    return digest("work-state", projected)


def work_transition(before, event, *, disposition, reason_codes, details, permit, budget_results,
                    authority_result_digest=None, reservation_receipt_digests=None, mutate=None):
    event_digest = digest("runtime-event", event)
    after = copy.deepcopy(before)
    after["revision"] = str(int(before["revision"]) + 1)
    if mutate:
        mutate(after, event_digest)
    core = copy.deepcopy(after)
    core["receipts"] = []
    core["replays"] = []
    core_digest = digest("work-state-core", core)
    receipt = {
        "schema": SCHEMA + "decision-receipt",
        "decision_id": "sha256:" + "0" * 64,
        "instance_id": INSTANCE,
        "sequence": after["revision"],
        "event_id": event["event_id"],
        "event_digest": event_digest,
        "event_kind": event["kind"],
        "disposition": disposition,
        "reason_codes": reason_codes,
        "details": details,
        "permit_digest": permit["permit_id"] if permit else (event.get("permit") or {}).get("permit_id"),
        "authority_result_digest": authority_result_digest,
        "reservation_receipt_digests": reservation_receipt_digests or [],
        "state_before_digest": work_state_digest(before),
        "state_after_core_digest": core_digest,
    }
    receipt["decision_id"] = digest("decision-receipt", omit(receipt, "decision_id"))
    budget_results = budget_results or []
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


def reservation_state_digest(state):
    return digest("reservation-state", state)


def reservation_transition(before, event, host, *, decision, reservation_id, budgets,
                           authority_result, mutate):
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
        "reasons": [],
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


def main():
    source_policy = {
        "artifact_kind": "NON_NORMATIVE_SYNTHETIC_SOURCE_POLICY",
        "candidate_pin": PIN,
        "id": "access-card-issuance-policy",
        "revision": "r1",
        "obligations": [
            {"id": "cap-issued-cards", "text": "Count committed and unsettled card issuances by beneficiary in the last 24 hours and do not exceed two."},
            {"id": "issue-exact-card", "text": "Issue the exact card identifier to the exact named beneficiary and treat only matching attributable native effect evidence as completion."},
            {"id": "require-current-authority", "text": "Require a current reusable grant, separate organizational attestation, current executor credential and current revocation evidence before reserving capacity."},
        ],
    }
    source_ids = [row["id"] for row in source_policy["obligations"]]
    types = [
        {"id": "t.identity", "kind": "IDENTITY", "nonnegative": False, "unit": None},
        {"id": "t.status", "kind": "STRING", "nonnegative": False, "unit": None},
    ]
    op_fields = [{"name": "beneficiary", "type_ref": "t.identity"}, {"name": "card_id", "type_ref": "t.identity"}]
    completion = {
        "effect_provider": "card-provider",
        "effect_source": "card-ledger",
        "effect_record_type": "card-issuance",
        "no_effect_provider": "card-provider",
        "no_effect_source": "card-ledger",
        "no_effect_record_type": "card-no-effect",
        "status_field": "status",
        "status_type_ref": "t.status",
        "success_values": [typed("t.status", "ISSUED")],
        "failure_values": [typed("t.status", "FAILED")],
        "route_label_field": None,
        "route_label_type_ref": None,
        "evidence_bindings": [
            {"request_field": "beneficiary", "evidence_field": "beneficiary"},
            {"request_field": "card_id", "evidence_field": "card_id"},
        ],
    }
    work_class = {
        "schema": SCHEMA + "work-class-definition",
        "specification_pin": PIN,
        "id": "access-card-issuance",
        "revision": "r1",
        "profile": PROFILE,
        "root": "issue-card",
        "participants": [
            {"id": "card-issuer-machine", "role": "card-issuer", "kind": "AGENT"},
            {"id": "unapproved-machine", "role": "card-auditor", "kind": "AGENT"},
        ],
        "objects": [],
        "types": types,
        "steps": [
            {
                "id": "complete",
                "kind": "TERMINAL",
                "executor_role": None,
                "interface": None,
                "operation": None,
                "fields": [],
                "scope_fields": None,
                "required_credentials": [],
                "authority_requirements": [],
                "shared_budgets": [],
                "prior_effect_bindings": [],
                "prior_actor_separations": [],
                "permit_seconds": None,
                "failure_behavior": None,
                "completion": None,
            },
            {
                "id": "issue-card",
                "kind": "OPERATION",
                "executor_role": "card-issuer",
                "interface": "card-system",
                "operation": "issue-access-card",
                "fields": op_fields,
                "scope_fields": {"subjects": ["beneficiary"], "resources": ["card_id"]},
                "required_credentials": ["card-issuer-credential"],
                "authority_requirements": ["access-card-authority"],
                "shared_budgets": ["cards-per-beneficiary"],
                "prior_effect_bindings": [],
                "prior_actor_separations": [],
                "permit_seconds": "300",
                "failure_behavior": "STOP",
                "completion": completion,
            },
        ],
        "relationships": [{"kind": "SEQUENCE", "from": "issue-card", "to": "complete"}],
        "choices": [],
        "occurrence_limits": [{"step_id": "issue-card", "maximum": "1"}],
        "loops": [],
        "deadlines": [],
        "parallel_blocks": [],
        "fanouts": [],
        "shared_budgets": ["cards-per-beneficiary"],
        "limits": {
            "maximum_proposals": "16",
            "maximum_activations": "1",
            "maximum_actuations": "1",
            "maximum_active_obligations": "0",
            "maximum_fanout_objects": "0",
        },
        "source": {"id": source_policy["id"], "revision": source_policy["revision"], "obligations": source_ids},
    }
    definition_digest = digest("work-class-definition", work_class)

    authority_source = {
        "schema": SCHEMA + "authority-source",
        "id": source_policy["id"],
        "revision": source_policy["revision"],
        "obligations": [{"id": row["id"], "text": row["text"]} for row in source_policy["obligations"]],
    }
    authority_work_class = {
        "schema": SCHEMA + "authority-work-class",
        "id": work_class["id"],
        "revision": work_class["revision"],
        "types": [types[0]],
        "steps": [{
            "id": "issue-card",
            "operation": "issue-access-card",
            "interface": "card-system",
            "executor_role": "card-issuer",
            "fields": op_fields,
            "scope_fields": {"subjects": ["beneficiary"], "resources": ["card_id"]},
            "required_credentials": ["card-issuer-credential"],
        }],
    }
    source_digest = digest("authority-source", authority_source)
    authority_work_class_digest = digest("authority-work-class", authority_work_class)
    envelope = {
        "schema": SCHEMA + "authority-envelope",
        "id": "access-card-authority",
        "source_digest": source_digest,
        "work_class_digest": authority_work_class_digest,
        "source_obligations": source_ids,
        "principal": "sample-organization",
        "grantor_role": "card-policy-owner",
        "executor_role": "card-issuer",
        "attester_role": "card-policy-attester",
        "grant_ref": "grant-card-issuance",
        "clock_source": "governance-clock",
        "bindings": [
            {"id": "beneficiary-binding", "step": "issue-card", "field": "beneficiary", "type_ref": "t.identity"},
            {"id": "card-binding", "step": "issue-card", "field": "card_id", "type_ref": "t.identity"},
        ],
        "scope": {
            "id": "access-card-scope",
            "subjects": [{"kind": "BINDING", "binding": "beneficiary-binding"}],
            "resources": [{"kind": "BINDING", "binding": "card-binding"}],
        },
        "operations": [{"step": "issue-card", "operation": "issue-access-card", "interface": "card-system"}],
        "limits": {"per_action": [], "shared_budgets": ["cards-per-beneficiary"]},
        "conditions": [{"id": "issuance-enabled", "step": "issue-card", "predicate": {"kind": "BOOLEAN", "value": True}}],
        "enforcement": {"mechanisms": ["ATOMIC_SHARED_RESERVATION", "AUTHORITY_BEFORE_RESERVATION"], "safe_state": "NO_NEW_DISPATCH", "out_of_envelope": "REFUSE"},
        "escalation": {"kind": "DECLARED_NONE"},
        "revocation": {"provider": "identity-provider", "source": "authority-revocations", "max_age_seconds": "3600"},
        "temporal_validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
        "gate": {"materiality": "LOW", "reversibility": "HIGH", "kind": "NONE", "role": None, "criteria": []},
        "limitations": [],
    }
    envelope_digest = digest("authority-envelope", envelope)
    authority_definition = {"schema": SCHEMA + "authority-definition", "source": authority_source, "work_class": authority_work_class, "envelope": envelope}

    occurrence_subject = {
        "specification_pin": PIN,
        "work_class_digest": definition_digest,
        "instance_id": INSTANCE,
        "step_id": "issue-card",
        "ordinal": "1",
        "predecessor_occurrence_ids": [],
        "enclosing": [],
        "object_key": None,
    }
    occurrence = {"occurrence_id": digest("occurrence", occurrence_subject), **occurrence_subject}
    proposal_fields = [field("beneficiary", "t.identity", "employee-7"), field("card_id", "t.identity", "card-802")]
    authority_executor = {"actor": "card-issuer-machine", "role": "card-issuer", "principal": "sample-organization", "occupancy": "occupancy-card-machine"}
    authority_proposal = {
        "schema": SCHEMA + "authority-proposal",
        "work_class_digest": authority_work_class_digest,
        "work_class": work_class["id"],
        "instance": INSTANCE,
        "occurrence": occurrence["occurrence_id"],
        "step": "issue-card",
        "operation": "issue-access-card",
        "interface": "card-system",
        "executor": authority_executor,
        "fields": proposal_fields,
    }
    authority_proposal_digest = digest("authority-proposal", authority_proposal)
    operation_digest = digest("authority-operation", {"envelope_digest": envelope_digest, "work_class_digest": authority_work_class_digest, "proposal_digest": authority_proposal_digest})

    root_stub = {
        "schema": SCHEMA + "authority-root", "id": "root-card-authority", "revision": "1",
        "designator": "sample-authority-office", "principal": "sample-organization",
        "source_digest": source_digest, "work_class_digest": authority_work_class_digest, "envelope_digest": envelope_digest,
        "capacity_ids": ["capacity-card-attester", "capacity-card-grantor"],
        "occupancy_ids": ["occupancy-card-attester", "occupancy-card-grantor", "occupancy-card-machine"],
        "providers": ["identity-provider"],
        "channels": [{"id": "authority-return-channel", "provider": "identity-provider", "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, "prior_returns_survive_expiry": False}],
        "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
        "revocation": {"provider": "identity-provider", "source": "authority-revocations", "max_age_seconds": "3600"},
        "prior_acts_survive_expiry": False, "allow_self_attestation": False, "limitations": [],
    }
    root_digest = digest("authority-root", root_stub)
    occupancies = [
        {"id": "occupancy-card-attester", "actor": "person-card-attester", "role": "card-policy-attester", "principal": "sample-organization", "kind": "HUMAN", "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, "provider": "identity-provider", "evidence_ref": "occupancy-attester-evidence"},
        {"id": "occupancy-card-grantor", "actor": "person-card-grantor", "role": "card-policy-owner", "principal": "sample-organization", "kind": "HUMAN", "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, "provider": "identity-provider", "evidence_ref": "occupancy-grantor-evidence"},
        {"id": "occupancy-card-machine", "actor": "card-issuer-machine", "role": "card-issuer", "principal": "sample-organization", "kind": "MACHINE", "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, "provider": "identity-provider", "evidence_ref": "occupancy-machine-evidence"},
    ]
    capacities = [
        {"id": "capacity-card-attester", "root_digest": root_digest, "envelope_digest": envelope_digest, "actor": "person-card-attester", "role": "card-policy-attester", "principal": "sample-organization", "occupancy": "occupancy-card-attester", "act_kinds": ["ORGANISATIONAL_ATTESTATION"], "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, "revocation": {"provider": "identity-provider", "source": "authority-revocations", "max_age_seconds": "3600"}, "reliance": {"kind": "CURRENT_ONLY"}, "may_self_attest": False, "provider": "identity-provider", "evidence_ref": "capacity-attester-evidence"},
        {"id": "capacity-card-grantor", "root_digest": root_digest, "envelope_digest": envelope_digest, "actor": "person-card-grantor", "role": "card-policy-owner", "principal": "sample-organization", "occupancy": "occupancy-card-grantor", "act_kinds": ["GRANT"], "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, "revocation": {"provider": "identity-provider", "source": "authority-revocations", "max_age_seconds": "3600"}, "reliance": {"kind": "CURRENT_ONLY"}, "may_self_attest": False, "provider": "identity-provider", "evidence_ref": "capacity-grantor-evidence"},
    ]
    credential = {"id": "credential-card-machine", "actor": "card-issuer-machine", "occupancy": "occupancy-card-machine", "kind": "card-issuer-credential", "step": "issue-card", "operation": "issue-access-card", "interface": "card-system", "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, "revocation": {"provider": "identity-provider", "source": "authority-revocations", "max_age_seconds": "3600"}, "provider": "identity-provider", "evidence_ref": "credential-card-machine-evidence"}
    grant = {"id": "grant-card-issuance", "kind": "GRANT", "actor": "person-card-grantor", "role": "card-policy-owner", "principal": "sample-organization", "occupancy": "occupancy-card-grantor", "capacity": "capacity-card-grantor", "recorder": "authority-recorder", "occurred_at": "2026-09-08T10:00:00Z", "disposition": "ACCEPT", "subject_digest": envelope_digest, "attested_actor": None, "criteria": []}
    grant_digest = digest("authority-act", grant)
    attestation = {"id": "attest-card-grant", "kind": "ORGANISATIONAL_ATTESTATION", "actor": "person-card-attester", "role": "card-policy-attester", "principal": "sample-organization", "occupancy": "occupancy-card-attester", "capacity": "capacity-card-attester", "recorder": "authority-recorder", "occurred_at": "2026-09-08T10:01:00Z", "disposition": "ACCEPT", "subject_digest": grant_digest, "attested_actor": "person-card-grantor", "criteria": []}
    acts = sorted([grant, attestation], key=lambda row: digest("authority-act", row).encode("utf-8"))
    returns = []
    for act, return_id in [(grant, "return-card-grant"), (attestation, "return-card-attestation")]:
        returns.append({"id": return_id, "actor": act["actor"], "provider": "identity-provider", "channel": "authority-return-channel", "act_digest": digest("authority-act", act), "act_bytes_base64": base64.b64encode(canonical_bytes(act)).decode(), "returned_at": act["occurred_at"], "evidence_ref": return_id + "-evidence"})
    returns.sort(key=lambda row: row["id"].encode())

    queries = []
    def add_query(subject_digest, at):
        query = {"purpose": "REVOCATION", "subject_digest": subject_digest, "at": at, "provider": "identity-provider", "source": "authority-revocations"}
        queries.append(query)
    for at in [grant["occurred_at"], attestation["occurred_at"], NOW]: add_query(root_digest, at)
    for at in [attestation["occurred_at"], NOW]: add_query(digest("authority-capacity", capacities[0]), at)
    for at in [grant["occurred_at"], NOW]: add_query(digest("authority-capacity", capacities[1]), at)
    add_query(envelope_digest, NOW)
    add_query(digest("authority-credential", credential), NOW)
    observations = []
    for index, query in enumerate(queries, 1):
        observations.append({"query": query, "query_digest": digest("authority-query", query), "status": "AVAILABLE", "as_of": query["at"], "revision": f"rev-{index}", "revoked": False, "evidence_ref": f"revocation-evidence-{index}"})

    authenticated_records = []
    for row in occupancies:
        authenticated_records.append({"kind": "OCCUPANCY", "record_digest": digest("authority-occupancy", row), "provider": row["provider"], "channel": None})
    for row in capacities:
        authenticated_records.append({"kind": "CAPACITY", "record_digest": digest("authority-capacity", row), "provider": row["provider"], "channel": None})
    authenticated_records.append({"kind": "CREDENTIAL", "record_digest": digest("authority-credential", credential), "provider": credential["provider"], "channel": None})
    for row in returns:
        authenticated_records.append({"kind": "RETURN", "record_digest": digest("authority-return", row), "provider": row["provider"], "channel": row["channel"]})
    authenticated_records = sorted_utf8(authenticated_records)
    host_selection = {"root": root_stub, "selection_evidence": "root-selection-evidence", "authenticated_records": authenticated_records}
    authority_input = {
        "schema": SCHEMA + "authority-input", "specification_pin": PIN, "source": authority_source,
        "work_class": authority_work_class, "envelope": envelope, "proposal": authority_proposal,
        "clock": {"source": "governance-clock", "status": "AVAILABLE", "instant": NOW},
        "host_selection": host_selection, "occupancies": occupancies, "capacities": capacities,
        "credentials": [credential], "acts": acts, "returns": returns, "observations": observations,
    }

    check_rows = [
        {"purpose": "SOURCE_BINDING", "subject_digest": envelope_digest, "requirement_ref": authority_source["id"], "at": NOW},
        {"purpose": "ROOT_BINDING", "subject_digest": envelope_digest, "requirement_ref": root_stub["id"], "at": NOW},
        {"purpose": "INPUT_SUPPORT", "subject_digest": operation_digest, "requirement_ref": "issue-card", "at": NOW},
        {"purpose": "BINDING", "subject_digest": operation_digest, "requirement_ref": "access-card-scope", "at": NOW},
        {"purpose": "GATE_FLOOR", "subject_digest": envelope_digest, "requirement_ref": envelope["id"], "at": NOW},
        {"purpose": "ENVELOPE_VALIDITY", "subject_digest": envelope_digest, "requirement_ref": envelope["id"], "at": NOW},
        {"purpose": "EXECUTOR_OCCUPANCY", "subject_digest": operation_digest, "requirement_ref": authority_executor["occupancy"], "at": NOW},
        {"purpose": "CONDITION", "subject_digest": operation_digest, "requirement_ref": "issuance-enabled", "at": NOW},
        {"purpose": "CREDENTIAL", "subject_digest": operation_digest, "requirement_ref": credential["id"], "at": NOW},
    ]
    return_by_act = {row["act_digest"]: row for row in returns}
    for act in acts:
        act_digest = digest("authority-act", act)
        check_rows.extend([
            {"purpose": "ACT_CAPACITY", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": act["occurred_at"]},
            {"purpose": "ACT_OCCUPANCY", "subject_digest": act_digest, "requirement_ref": act["occupancy"], "at": act["occurred_at"]},
            {"purpose": "ACT_RELIANCE", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": NOW},
            {"purpose": "RETURN", "subject_digest": act_digest, "requirement_ref": return_by_act[act_digest]["id"], "at": NOW},
        ])
        if act["kind"] == "ORGANISATIONAL_ATTESTATION":
            check_rows.append({"purpose": "SEPARATION", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": NOW})
    for query in queries:
        check_rows.append({"purpose": "REVOCATION", "subject_digest": query["subject_digest"], "requirement_ref": digest("authority-query", query), "at": query["at"]})
    check_rows = sorted_utf8(check_rows)
    authority_evidence_subject = {"host_selection": host_selection, "occupancies": occupancies, "capacities": capacities, "credentials": [credential], "acts": acts, "returns": returns, "observations": observations, "clock": authority_input["clock"]}
    authority_result = {
        "schema": SCHEMA + "authority-result", "specification_pin": PIN, "status": "READY_FOR_RESERVATION",
        "source_digest": source_digest, "work_class_digest": authority_work_class_digest,
        "envelope_digest": envelope_digest, "proposal_digest": authority_proposal_digest,
        "operation_digest": operation_digest,
        "scope": {"subjects": ["employee-7"], "resources": ["card-802"]},
        "actual_scope": {"subjects": ["employee-7"], "resources": ["card-802"]},
        "act_digests": sorted([digest("authority-act", row) for row in acts]),
        "checks": check_rows, "required_budgets": ["cards-per-beneficiary"],
        "evidence_digest": digest("authority-evidence", authority_evidence_subject),
    }
    authority_result_digest = digest("authority-result", authority_result)

    aggregate_definition = {
        "schema": SCHEMA + "aggregate-definition",
        "types": [
            {"id": "b.boolean", "kind": "BOOLEAN", "unit": None, "nonnegative": False},
            {"id": "b.count", "kind": "INTEGER", "unit": None, "nonnegative": True},
            {"id": "b.identity", "kind": "IDENTITY", "unit": None, "nonnegative": False},
        ],
        "aggregate": {
            "id": "cards-per-beneficiary-count", "reducer": "COUNT", "result_type": "b.count", "element_type": None,
            "key_types": ["b.identity"],
            "mappings": [{"id": "issue-card-count", "step_ids": ["issue-card"], "qualifier": {"kind": "BOOLEAN", "value": True}, "key_fields": ["beneficiary"], "contribution": {"kind": "COUNT"}}],
            "time": {"clock_source": "governance-clock", "precision": "SECOND"},
            "window": {"kind": "ROLLING", "duration_seconds": "86400", "start_inclusive": False, "end_inclusive": True},
            "committed_source": {"provider": "card-provider", "source": "card-ledger", "freshness": {"kind": "NONE"}, "key_fields": ["beneficiary"], "qualifier": {"kind": "BOOLEAN", "value": True}, "contribution": {"kind": "COUNT"}},
            "pending_policy": "INCLUDE_ALL_RESERVED", "operator": "LTE", "bound": typed("b.count", "2"),
        },
    }
    aggregate_definition_digest = digest("aggregate-definition", aggregate_definition)
    budget_definition = {
        "schema": SCHEMA + "budget-definition", "anchor": "cards-per-beneficiary", "exposure_domain": "access-card-issuance",
        "principal": "sample-organization", "aggregate": aggregate_definition, "contributor_classes": [work_class["id"]],
        "reservation_policy": {"permit_seconds": "300", "pending_across_windows": True, "unexpected_effect": "BLOCK_AFFECTED_PARTITIONS", "unprojectable_effect": "BLOCK_ANCHOR", "settlement": {"provider": "card-provider", "source": "card-ledger"}, "no_effect": {"provider": "card-provider", "source": "card-ledger"}},
    }
    budget_definition_digest = digest("budget-definition", budget_definition)
    budget_authorization = {
        "id": "access-card-budget-authorization", "budget_digest": budget_definition_digest,
        "work_class": work_class["id"], "work_class_digest": authority_work_class_digest,
        "envelope_digest": envelope_digest, "principal": "sample-organization", "step": "issue-card",
        "authority_definition": authority_definition,
        "projection": [{"native_field": "beneficiary", "native_type": "t.identity", "budget_field": "beneficiary", "budget_type": "b.identity"}],
    }
    initial_history = {"budget_digest": budget_definition_digest, "provider": "card-provider", "source": "card-ledger", "status": "AVAILABLE", "as_of": NOW, "complete": True, "revision": "0", "journal": [], "evidence_ref": "card-history-empty"}
    registry_configuration = {
        "schema": SCHEMA + "reservation-registry", "id": "access-card-registry", "principal": "sample-organization",
        "clock_source": "governance-clock", "administration_provider": "governance-provider", "administration_source": "budget-administration",
        "administration_role": "budget-administrator", "slots": [{"anchor": "cards-per-beneficiary", "exposure_domain": "access-card-issuance"}],
    }
    registry_digest = digest("reservation-registry", registry_configuration)
    reservation_initial = {"schema": SCHEMA + "reservation-state", "specification_pin": PIN, "core": {"configuration": registry_configuration, "revision": "0", "last_clock": None, "budgets": [], "reservations": [], "effects": []}, "receipts": []}
    register_payload = {"definition": budget_definition, "authorizations": [budget_authorization], "history": initial_history}
    register_event_without_admin = {"id": "register-access-card-budget", "expected_revision": "0", "kind": "REGISTER", "clock": {"source": "governance-clock", "status": "AVAILABLE", "instant": NOW}, "payload": register_payload}
    admin_subject = digest("reservation-administration-subject", {
        "registry_digest": registry_digest,
        "event_id": register_event_without_admin["id"],
        "expected_revision": register_event_without_admin["expected_revision"],
        "kind": register_event_without_admin["kind"],
        "clock": register_event_without_admin["clock"],
        "payload": register_event_without_admin["payload"],
    })
    admin_basis = {"id": "budget-admin-basis", "registry_digest": registry_digest, "actor": "person-budget-admin", "principal": "sample-organization", "role": "budget-administrator", "kind": "HUMAN", "operations": ["REGISTER", "RELEASE"], "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, "at": NOW, "revoked": False, "provider": "governance-provider", "source": "budget-administration", "evidence_ref": "budget-admin-basis-evidence"}
    admin_act = {"id": "register-access-card-budget-act", "basis": admin_basis["id"], "actor": admin_basis["actor"], "principal": admin_basis["principal"], "role": admin_basis["role"], "kind": "REGISTER", "subject_digest": admin_subject, "occurred_at": NOW, "disposition": "ACCEPT"}
    admin_return = {"id": "register-access-card-budget-return", "act_digest": digest("reservation-administration-act", admin_act), "act_bytes_base64": base64.b64encode(canonical_bytes(admin_act)).decode(), "actor": admin_act["actor"], "provider": "governance-provider", "source": "budget-administration", "returned_at": NOW, "evidence_ref": "register-return-evidence"}
    register_event = {**register_event_without_admin, "administration": {"act": admin_act, "returned": admin_return}}
    register_host = {"registry_digest": registry_digest, "selection_evidence": "registry-selection-evidence", "administration_bases": [admin_basis], "authenticated_records": sorted_utf8([
        {"kind": "HISTORY", "record_digest": digest("budget-history", initial_history), "provider": initial_history["provider"], "source": initial_history["source"]},
        {"kind": "ADMIN_RETURN", "record_digest": digest("reservation-administration-return", admin_return), "provider": admin_return["provider"], "source": admin_return["source"]},
    ])}
    def apply_register(state):
        state["core"]["budgets"] = [{"definition": budget_definition, "definition_digest": budget_definition_digest, "authorizations": [budget_authorization], "history": initial_history}]
    registry_registered, register_result = reservation_transition(reservation_initial, register_event, register_host, decision="REGISTERED", reservation_id=None, budgets=[], authority_result=None, mutate=apply_register)
    register_input = {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": reservation_initial, "state_digest": reservation_state_digest(reservation_initial), "event": register_event, "host_evidence": register_host}

    lines = readback(work_class)
    readback_result = {"status": "READBACK", "digest": definition_digest, "lines": lines}
    path_set = [line["path"] for line in lines]
    supported_paths = {
        "cap-issued-cards": {
            "/shared_budgets/0",
            "/source/obligations/0",
            "/steps/1/shared_budgets/0",
        },
        "issue-exact-card": {
            "/relationships/0/from",
            "/relationships/0/kind",
            "/relationships/0/to",
            "/root",
            "/source/obligations/1",
            "/steps/0/id",
            "/steps/0/kind",
            "/steps/1/completion/effect_provider",
            "/steps/1/completion/effect_record_type",
            "/steps/1/completion/effect_source",
            "/steps/1/completion/evidence_bindings/0/evidence_field",
            "/steps/1/completion/evidence_bindings/0/request_field",
            "/steps/1/completion/evidence_bindings/1/evidence_field",
            "/steps/1/completion/evidence_bindings/1/request_field",
            "/steps/1/completion/status_field",
            "/steps/1/completion/status_type_ref",
            "/steps/1/completion/success_values/0/type_ref",
            "/steps/1/completion/success_values/0/value",
            "/steps/1/fields/0/name",
            "/steps/1/fields/0/type_ref",
            "/steps/1/fields/1/name",
            "/steps/1/fields/1/type_ref",
            "/steps/1/id",
            "/steps/1/interface",
            "/steps/1/kind",
            "/steps/1/operation",
            "/steps/1/scope_fields/resources/0",
            "/steps/1/scope_fields/subjects/0",
            "/types/0/id",
            "/types/0/kind",
            "/types/1/id",
            "/types/1/kind",
        },
        "require-current-authority": {
            "/source/obligations/2",
            "/steps/1/authority_requirements/0",
            "/steps/1/executor_role",
            "/steps/1/required_credentials/0",
        },
    }
    mappings = [
        {
            "source_obligation_id": obligation,
            "provision_paths": sorted(supported_paths[obligation], key=lambda value: value.encode("utf-8")),
        }
        for obligation in source_ids
    ]
    mapped_paths = set().union(*supported_paths.values())
    unknown_mapped_paths = mapped_paths - set(path_set)
    if unknown_mapped_paths:
        raise ValueError(f"correspondence names absent readback paths: {sorted(unknown_mapped_paths)}")
    unsupported_paths = sorted(set(path_set) - mapped_paths, key=lambda value: value.encode("utf-8"))
    residue = [
        {
            "kind": "ARTIFACT_PROVISION",
            "subject": path,
            "disposition": "UNSUPPORTED",
            "explanation": "The synthetic source policy does not state this representation or execution detail.",
        }
        for path in unsupported_paths
    ]
    correspondence_base = {"schema": SCHEMA + "evidence-record", "evidence_id": "access-card-correspondence", "kind": "CORRESPONDENCE", "status": "ACCEPTED", "subject_digest": definition_digest, "source_id": work_class["source"]["id"], "source_revision": work_class["source"]["revision"], "work_class_digest": definition_digest, "mappings": mappings, "uncovered_source_obligation_ids": [], "unsupported_provision_paths": unsupported_paths, "residue": residue, "recorded_at": DEPLOYMENT_AUTHORIZED_AT, "provenance_digest": digest("specimen-provenance", {"id": "access-card-correspondence"})}
    correspondence_subject = digest("correspondence-subject", correspondence_base)
    correspondence_review = {"schema": SCHEMA + "evidence-record", "evidence_id": "access-card-correspondence-review", "kind": "REVIEW", "status": "ACCEPTED", "subject_digest": correspondence_subject, "reviewer_id": "synthetic:specimen-proxy-reviewer:20260913", "paragraph_ids": [], "case_ids": ["access-card-correspondence"], "finding_ids": [], "recorded_at": DEPLOYMENT_AUTHORIZED_AT, "provenance_digest": digest("specimen-provenance", {"id": "access-card-correspondence-review"})}
    correspondence = {**correspondence_base, "review": correspondence_review}
    correspondence_input = {"profile": PROFILE, "role": "REVIEW_EVIDENCE", "specification_pin": PIN, "subject": {"kind": "WORK_CLASS", "subject_id": work_class["id"], "subject_digest": definition_digest, "candidate_identity": "seampoint.work-class/1.0.0-draft.2", "specification_pin": PIN}, "work_class": work_class, "work_class_digest": definition_digest, "evidence": correspondence}
    # LIFE-003 review acts for deployment. The correspondence review above, the source confirmation and the
    # policy decision are labelled synthetic proxy acts; no person has performed them, and the README says so.
    # The 2026-09-11 independent specimen review bound an earlier correspondence subject (blocker AC-REV-001).
    source_confirmation = {"schema": SCHEMA + "evidence-record", "evidence_id": "access-card-source-confirmation", "kind": "SOURCE_CONFIRMATION", "status": "ACCEPTED", "subject_digest": digest("work-class-source", work_class["source"]), "actor_id": "synthetic:specimen-proxy-source-confirmer:20260913", "scope_ids": list(work_class["source"]["obligations"]), "recorded_at": DEPLOYMENT_AUTHORIZED_AT, "provenance_digest": digest("specimen-provenance", {"id": "access-card-source-confirmation"})}
    policy_decision = {"schema": SCHEMA + "evidence-record", "evidence_id": "access-card-policy-decision", "kind": "POLICY_DECISION", "status": "ACCEPTED", "subject_digest": definition_digest, "decision_maker_id": "synthetic:specimen-proxy-policy-owner:20260913", "decision_ids": ["access-card-policy-decision-1"], "recorded_at": DEPLOYMENT_AUTHORIZED_AT, "provenance_digest": digest("specimen-provenance", {"id": "access-card-policy-decision"})}
    correspondence_digest = digest("evidence", correspondence)
    source_confirmation_digest = digest("evidence", source_confirmation)
    policy_decision_digest = digest("evidence", policy_decision)

    authorization_clock = {"source": "deployment-clock", "revision": "1", "status": "AVAILABLE", "observed_time": "2026-09-10T11:55:00Z", "evidence_digest": digest("specimen-clock-evidence", {"source": "deployment-clock", "revision": "1", "time": "2026-09-10T11:55:00Z"})}
    deployment_authorization_partial = {"schema": SCHEMA + "deployment-authorization", "authorization_id": "authorize-access-card-instance", "specification_pin": PIN, "work_class_digest": definition_digest, "profile": PROFILE, "role": ROLE, "instance_id": INSTANCE, "organization_id": "sample-organization", "status": "AUTHORIZED", "authorized_at": DEPLOYMENT_AUTHORIZED_AT, "expires_at": "2026-09-11T00:00:00Z", "correspondence_evidence_digest": correspondence_digest, "source_confirmation_evidence_digest": source_confirmation_digest, "policy_decision_evidence_digest": policy_decision_digest}
    deployment_subject_digest = digest("deployment-authorization-subject", deployment_authorization_partial)
    deployment_evidence = {"schema": SCHEMA + "evidence-record", "evidence_id": "deployment-authorization-evidence", "kind": "ORGANIZATIONAL_AUTHORIZATION", "status": "ACCEPTED", "subject_digest": deployment_subject_digest, "organization_id": "sample-organization", "authorizer_id": "person-deployment-authorizer", "authorization_scope": sorted([PIN, definition_digest, PROFILE, ROLE, INSTANCE]), "recorded_at": "2026-09-10T11:50:00Z", "expires_at": "2026-09-11T00:00:00Z", "provenance_digest": digest("specimen-provenance", {"id": "deployment-authorization-evidence"})}
    deployment_evidence_digest = digest("evidence", deployment_evidence)
    deployment_authorization = {**deployment_authorization_partial, "authorization_evidence_digest": deployment_evidence_digest}
    deployment_authorization_digest = digest("deployment-authorization", deployment_authorization)
    activation_digest = digest("deployment-activation", {"deployment_authorization_digest": deployment_authorization_digest, "instance_id": INSTANCE, "occurrence_id": occurrence["occurrence_id"]})
    work_state_initial = {
        "schema": SCHEMA + "work-state", "specification_pin": PIN, "work_class_digest": definition_digest, "profile": PROFILE, "role": ROLE, "instance_id": INSTANCE,
        "deployment_authorization": deployment_authorization, "deployment_authorization_subject_digest": deployment_subject_digest,
        "deployment_authorization_digest": deployment_authorization_digest, "deployment_authorization_evidence": deployment_evidence,
        "deployment_authorization_evidence_digest": deployment_evidence_digest,
        "deployment_correspondence_evidence": correspondence, "deployment_correspondence_evidence_digest": correspondence_digest,
        "deployment_source_confirmation_evidence": source_confirmation, "deployment_source_confirmation_evidence_digest": source_confirmation_digest,
        "deployment_policy_decision_evidence": policy_decision, "deployment_policy_decision_evidence_digest": policy_decision_digest,
        "deployment_authorization_clock": authorization_clock,
        "deployment_organization_id": "sample-organization", "revision": "0", "status": "ACTIVE", "total_activations": "1", "total_actuations": "0",
        "step_counters": [{"step_id": "issue-card", "activations": "1", "actuations": "0"}],
        "active": [{"occurrence": occurrence, "activation_event_digest": activation_digest, "status": "ACTIVE", "deadline_ids": []}],
        "completed": [], "obligations": [], "proposals": [], "permits": [], "dispatches": [], "outcomes": [], "clocks": [], "deadlines": [], "fanout_passes": [], "receipts": [], "replays": [],
    }
    deploy_input = {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest, "instance_id": INSTANCE, "deployment_authorization": deployment_authorization, "authorization_evidence": deployment_evidence, "correspondence_evidence": correspondence, "source_confirmation_evidence": source_confirmation, "policy_decision_evidence": policy_decision, "authorization_clock": authorization_clock, "initial_clocks": []}
    deploy_result = {"status": "DEPLOYED", "profile": PROFILE, "role": ROLE, "instance_id": INSTANCE, "work_class_digest": definition_digest, "deployment_authorization_digest": deployment_authorization_digest, "state": work_state_initial, "state_digest": work_state_digest(work_state_initial)}

    lifecycle_clock = {"source": "governance-clock", "revision": "1", "status": "AVAILABLE", "observed_time": NOW, "evidence_digest": digest("specimen-clock-evidence", {"source": "governance-clock", "revision": "1", "time": NOW})}
    clock_event = {"schema": SCHEMA + "runtime-event", "event_id": "clock-governance-1", "kind": "CLOCK", "instance_id": INSTANCE, "expected_state_revision": "0", "expected_state_digest": deploy_result["state_digest"], "clock": lifecycle_clock, "activation_clocks": []}
    def apply_clock(state, _event_digest): state["clocks"].append(lifecycle_clock)
    work_state_clocked, clock_result = work_transition(work_state_initial, clock_event, disposition="CLOCK_RECORDED", reason_codes=[], details=[{"kind": "CLOCK", "source": "governance-clock", "revision": "1", "status": "AVAILABLE"}], permit=None, budget_results=[], mutate=apply_clock)

    native_request = {"interface": "card-system", "operation": "issue-access-card", "fields": proposal_fields}
    reservation_request = {"work_class": work_class["id"], "instance": INSTANCE, "occurrence": occurrence["occurrence_id"], "step": "issue-card", "operation": native_request["operation"], "interface": native_request["interface"], "fields": native_request["fields"]}
    lifecycle_executor = {"participant_id": "card-issuer-machine", "role": "card-issuer", "binding_digest": digest("executor-binding", authority_executor)}
    observation_digests = sorted([digest("authority-observation", row) for row in observations])
    propose_event_id = "propose-access-card-1"
    reserve_event_id = digest("lifecycle-reservation-event", {"instance_id": INSTANCE, "lifecycle_event_id": propose_event_id, "lifecycle_event_kind": "PROPOSE", "reservation_event_kind": "RESERVE", "registry_digest": registry_digest})
    reserve_event = {"id": reserve_event_id, "expected_revision": "1", "kind": "RESERVE", "clock": authority_input["clock"], "payload": {"authority": authority_input, "histories": [initial_history]}, "administration": None}
    reserve_host = {"registry_digest": registry_digest, "selection_evidence": "registry-selection-evidence", "administration_bases": [], "authenticated_records": [{"kind": "HISTORY", "record_digest": digest("budget-history", initial_history), "provider": initial_history["provider"], "source": initial_history["source"]}]}
    reserve_input = {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": registry_registered, "state_digest": reservation_state_digest(registry_registered), "event": reserve_event, "host_evidence": reserve_host}
    aggregate_result = {"schema": SCHEMA + "aggregate-result", "specification_pin": PIN, "definition_digest": aggregate_definition_digest, "status": "SATISFIED", "partitions": [{"occurrence": None, "key": [typed("b.identity", "employee-7")], "status": "SATISFIED", "accumulator": {"kind": "SCALAR", "value": "1"}, "result": "1", "reasons": []}], "reasons": []}
    occurrence_key = digest("reservation-occurrence", {"work_class": work_class["id"], "instance": INSTANCE, "occurrence": occurrence["occurrence_id"]})
    reservation_row = {"id": reserve_event_id, "occurrence_key": occurrence_key, "proposal_digest": authority_proposal_digest, "envelope_digest": envelope_digest, "authority": authority_input, "authority_result": authority_result, "contributions": [{"anchor": "cards-per-beneficiary", "mapping": "issue-card-count", "occurrence": occurrence_key, "key": [typed("b.identity", "employee-7")], "value": typed("b.count", "1")}], "created_at": NOW, "permit_until": EXPIRY, "status": "OPEN", "matched_effect": None}
    budget_results = [{"anchor": "cards-per-beneficiary", "result": aggregate_result}]
    def apply_reserve(state): state["core"]["reservations"] = [reservation_row]
    registry_reserved, reserve_result = reservation_transition(registry_registered, reserve_event, reserve_host, decision="RESERVED", reservation_id=reserve_event_id, budgets=budget_results, authority_result=authority_result, mutate=apply_reserve)
    budget_transition = {"registry_digest": registry_digest, "affected_anchors": ["cards-per-beneficiary"], "result": reserve_result}
    proposal_event = {"schema": SCHEMA + "runtime-event", "event_id": propose_event_id, "kind": "PROPOSE", "instance_id": INSTANCE, "expected_state_revision": "1", "expected_state_digest": work_state_digest(work_state_clocked), "occurrence": occurrence, "native_request": native_request, "executor": lifecycle_executor, "credential_ids": [credential["id"]], "authority_input": authority_input, "budget_inputs": [{"registry_digest": registry_digest, "affected_anchors": ["cards-per-beneficiary"], "expected_revision": "1", "request": reserve_input}], "clock_revision": "1", "observation_digests": observation_digests}
    proposal_digest = digest("proposal", proposal_event)
    authority_act_bases = sorted([
        {"act_digest": digest("authority-act", act), "act": act}
        for act in acts
    ], key=lambda row: row["act_digest"].encode("utf-8"))
    permit = {"schema": SCHEMA + "permit", "permit_id": "sha256:" + "0" * 64, "instance_id": INSTANCE, "work_class_digest": definition_digest, "profile": PROFILE, "role": ROLE, "occurrence": occurrence, "proposal_digest": proposal_digest, "native_request": native_request, "executor": lifecycle_executor, "credential_ids": [credential["id"]], "authority_result": authority_result, "authority_result_digest": authority_result_digest, "authority_evidence_digest": authority_result["evidence_digest"], "authority_act_bases": authority_act_bases, "prior_effect_bases": [], "separation_bases": [], "observation_digests": observation_digests, "supersedes_permit_digest": None, "budget_revisions": [{"registry_digest": registry_digest, "affected_anchors": ["cards-per-beneficiary"], "revision": "2", "reservation_id": reserve_event_id, "receipt_digest": reserve_result["receipt_digest"]}], "clock_source": "governance-clock", "clock_revision": "1", "expires_at": EXPIRY}
    permit["permit_id"] = digest("permit", omit(permit, "permit_id"))
    def apply_proposal(state, event_digest):
        state["total_actuations"] = "1"; state["step_counters"][0]["actuations"] = "1"; state["active"][0]["status"] = "PERMITTED"
        state["proposals"].append({"event_id": proposal_event["event_id"], "event_digest": event_digest, "proposal_digest": proposal_digest, "occurrence_id": occurrence["occurrence_id"], "disposition": "PERMITTED", "permit_digest": permit["permit_id"], "authority_result_digest": authority_result_digest, "reservation_receipt_digests": [reserve_result["receipt_digest"]], "prior_permit_digest": None})
        state["permits"].append(permit)
    work_state_permitted, proposal_result = work_transition(work_state_clocked, proposal_event, disposition="PERMITTED", reason_codes=[], details=[], permit=permit, budget_results=[budget_transition], authority_result_digest=authority_result_digest, reservation_receipt_digests=[reserve_result["receipt_digest"]], mutate=apply_proposal)

    connector = {"id": "card-connector", "version": "v1", "binding_digest": "sha256:" + "0" * 64}
    connector["binding_digest"] = digest("connector-binding", omit(connector, "binding_digest"))
    attempt = {"attempt_id": "card-attempt-1", "status": "SENT", "request_digest": digest("dispatch-native-request", {"instance_id": INSTANCE, "occurrence_id": occurrence["occurrence_id"], "interface": native_request["interface"], "operation": native_request["operation"], "fields": native_request["fields"]}), "attempted_at": NOW}
    acknowledgement = {"status": "ACCEPTED", "reference": "card-ack-1", "observed_at": NOW}
    dispatch_event = {"schema": SCHEMA + "runtime-event", "event_id": "dispatch-access-card-1", "kind": "DISPATCH_OBSERVED", "instance_id": INSTANCE, "expected_state_revision": "2", "expected_state_digest": work_state_digest(work_state_permitted), "permit": permit, "native_request": native_request, "connector": connector, "attempt": attempt, "acknowledgement": acknowledgement, "clock_revision": "1"}
    dispatch_event_digest = digest("runtime-event", dispatch_event)
    dispatch_attempt_digest = digest("dispatch-attempt", {"permit_id": permit["permit_id"], "native_request": native_request, "connector": connector, "attempt": attempt})
    dispatch_record = {"dispatch_digest": "sha256:" + "0" * 64, "dispatch_attempt_digest": dispatch_attempt_digest, "event_id": dispatch_event["event_id"], "event_digest": dispatch_event_digest, "permit_digest": permit["permit_id"], "native_request": native_request, "connector": connector, "attempt": attempt, "acknowledgement": acknowledgement, "clock_revision": "1"}
    dispatch_record["dispatch_digest"] = digest("dispatch", omit(dispatch_record, "dispatch_digest"))
    def apply_dispatch(state, _event_digest):
        state["active"][0]["status"] = "DISPATCHED"; state["dispatches"].append(dispatch_record)
    work_state_dispatched, dispatch_result = work_transition(work_state_permitted, dispatch_event, disposition="ACKNOWLEDGED", reason_codes=[], details=[{"kind": "DISPATCH", "attempt_id": attempt["attempt_id"], "reasons": []}], permit=None, budget_results=[], mutate=apply_dispatch)

    attributed_request = {"work_class": work_class["id"], "instance": INSTANCE, "occurrence": occurrence["occurrence_id"], "step": "issue-card", "operation": native_request["operation"], "interface": native_request["interface"], "fields": native_request["fields"]}
    actual_fields = [field("beneficiary", "t.identity", "employee-7"), field("card_id", "t.identity", "card-802"), field("status", "t.status", "ISSUED")]
    native_evidence = {"evidence_id": "card-effect-evidence-1", "native_operation_id": "card-provider-operation-1", "provider": "card-provider", "source": "card-ledger", "record_type": "card-issuance", "record_digest": digest("specimen-native-record", {"native_operation_id": "card-provider-operation-1", "actual_fields": actual_fields}), "evidence_ref": "card-effect-record-1", "attributed_request": attributed_request, "native_request_digest": digest("native-request", attributed_request), "status": "EFFECT_ESTABLISHED", "actual_fields": actual_fields, "collections": [], "event_time": NOW, "observed_at": NOW, "rules_out_past_and_future_effects": False}
    committed_event = {"id": digest("reservation-committed-event", {"budget_digest": budget_definition_digest, "effect_id": native_evidence["native_operation_id"], "mapping": "issue-card-count"}), "state": "ACTIVE", "occurred_at": NOW, "fields": [field("beneficiary", "b.identity", "employee-7")]}
    settled_history = {**initial_history, "revision": "1", "journal": [{"sequence": "1", "event": committed_event}], "evidence_ref": "card-history-settled"}
    reservation_native = {"id": native_evidence["evidence_id"], "provider": native_evidence["provider"], "source": native_evidence["source"], "reservation": reserve_event_id, "outcome": "EFFECT", "request": attributed_request, "effect_id": native_evidence["native_operation_id"], "occurred_at": NOW, "rules_out_past_and_future_effects": False, "evidence_ref": native_evidence["evidence_ref"], "observed_request": attributed_request, "actual_fields": actual_fields, "collections": [], "completion_mismatch": False, "mismatch_reason": None}
    settle_event_id = digest("lifecycle-reservation-event", {"instance_id": INSTANCE, "lifecycle_event_id": "effect-access-card-1", "lifecycle_event_kind": "EFFECT_OBSERVED", "reservation_event_kind": "SETTLE", "registry_digest": registry_digest})
    settle_event = {"id": settle_event_id, "expected_revision": "2", "kind": "SETTLE", "clock": authority_input["clock"], "payload": {"native": reservation_native, "histories": [settled_history]}, "administration": None}
    settle_host = {"registry_digest": registry_digest, "selection_evidence": "registry-selection-evidence", "administration_bases": [], "authenticated_records": sorted_utf8([
        {"kind": "HISTORY", "record_digest": digest("budget-history", settled_history), "provider": settled_history["provider"], "source": settled_history["source"]},
        {"kind": "NATIVE_OUTCOME", "record_digest": digest("reservation-native-outcome", reservation_native), "provider": reservation_native["provider"], "source": reservation_native["source"]},
    ])}
    settle_input = {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": registry_reserved, "state_digest": reservation_state_digest(registry_reserved), "event": settle_event, "host_evidence": settle_host}
    def apply_settle(state):
        state["core"]["budgets"][0]["history"] = settled_history
        state["core"]["reservations"][0]["status"] = "SETTLED"
        state["core"]["reservations"][0]["matched_effect"] = native_evidence["native_operation_id"]
        state["core"]["effects"] = [{"id": reservation_native["id"], "native": reservation_native, "native_digest": digest("reservation-native-outcome", reservation_native), "reservation": reserve_event_id, "disposition": "MATCHED", "affected_anchors": ["cards-per-beneficiary"], "blocked_partitions": [], "reason": "MATCHED_EFFECT"}]
    registry_settled, settle_result = reservation_transition(registry_reserved, settle_event, settle_host, decision="SETTLED", reservation_id=reserve_event_id, budgets=[], authority_result=None, mutate=apply_settle)
    effect_budget_transition = {"registry_digest": registry_digest, "affected_anchors": ["cards-per-beneficiary"], "result": settle_result}
    effect_event = {"schema": SCHEMA + "runtime-event", "event_id": "effect-access-card-1", "kind": "EFFECT_OBSERVED", "instance_id": INSTANCE, "expected_state_revision": "3", "expected_state_digest": work_state_digest(work_state_dispatched), "permit": permit, "dispatch_digest": dispatch_record["dispatch_digest"], "native_evidence": native_evidence, "completion_authorization": None, "budget_inputs": [{"registry_digest": registry_digest, "affected_anchors": ["cards-per-beneficiary"], "expected_revision": "2", "request": settle_input}], "clock_revision": "1", "activation_clocks": []}
    effect_event_digest = digest("runtime-event", effect_event)
    native_evidence_digest = digest("native-evidence", native_evidence)
    relationship_digest = digest("relationship", work_class["relationships"][0])
    outcome_record = {"kind": "GOVERNED", "outcome_digest": "sha256:" + "0" * 64, "event_id": effect_event["event_id"], "event_digest": effect_event_digest, "permit_digest": permit["permit_id"], "dispatch_digest": dispatch_record["dispatch_digest"], "dispatch_attempt_digest": dispatch_attempt_digest, "native_evidence": native_evidence, "classification": "MATCHED", "reservation_receipt_digests": [settle_result["receipt_digest"]], "conflicts_with_evidence_ids": [], "disputed": False}
    outcome_record["outcome_digest"] = digest("outcome", omit(outcome_record, "outcome_digest"))
    completed = {"occurrence": occurrence, "disposition": "SUCCEEDED", "evidence_digest": native_evidence_digest, "occurred_at": NOW, "route_label": None, "selected_relationship_digest": relationship_digest, "late": False}
    def apply_effect(state, _event_digest):
        state["status"] = "COMPLETE"; state["active"] = []; state["completed"] = [completed]; state["outcomes"] = [outcome_record]
    work_state_completed, effect_result = work_transition(work_state_dispatched, effect_event, disposition="COMPLETED", reason_codes=[], details=[{"kind": "BUDGET", "registry_digest": registry_digest, "receipt_digest": settle_result["receipt_digest"], "reasons": settle_result["receipt"]["reasons"]}, {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": native_evidence["evidence_id"]}, {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []}], permit=None, budget_results=[effect_budget_transition], reservation_receipt_digests=[settle_result["receipt_digest"]], mutate=apply_effect)

    protocol_requests = [
        {"protocol": PROTOCOL, "request_id": "access-card-deploy", "operation": "deploy", "input": deploy_input},
        {"protocol": PROTOCOL, "request_id": "access-card-clock", "operation": "step", "input": {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest, "state": work_state_initial, "state_digest": work_state_digest(work_state_initial), "event": clock_event}},
        {"protocol": PROTOCOL, "request_id": "access-card-propose", "operation": "step", "input": {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest, "state": work_state_clocked, "state_digest": work_state_digest(work_state_clocked), "event": proposal_event}},
        {"protocol": PROTOCOL, "request_id": "access-card-dispatch", "operation": "step", "input": {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest, "state": work_state_permitted, "state_digest": work_state_digest(work_state_permitted), "event": dispatch_event}},
        {"protocol": PROTOCOL, "request_id": "access-card-effect", "operation": "step", "input": {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest, "state": work_state_dispatched, "state_digest": work_state_digest(work_state_dispatched), "event": effect_event}},
    ]
    protocol_results = [
        {"protocol": PROTOCOL, "request_id": "access-card-deploy", "operation": "deploy", "result": deploy_result},
        {"protocol": PROTOCOL, "request_id": "access-card-clock", "operation": "step", "result": clock_result},
        {"protocol": PROTOCOL, "request_id": "access-card-propose", "operation": "step", "result": proposal_result},
        {"protocol": PROTOCOL, "request_id": "access-card-dispatch", "operation": "step", "result": dispatch_result},
        {"protocol": PROTOCOL, "request_id": "access-card-effect", "operation": "step", "result": effect_result},
    ]

    missing_authority = copy.deepcopy(protocol_requests[2])
    missing_authority["request_id"] = "access-card-missing-authority"
    missing_authority_input = missing_authority["input"]["event"]["authority_input"]
    missing_authority_input["observations"] = missing_authority_input["observations"][:-1]
    missing_authority["input"]["event"]["observation_digests"] = sorted(
        digest("authority-observation", row) for row in missing_authority_input["observations"]
    )
    missing_authority["input"]["event"]["budget_inputs"][0]["request"]["event"]["payload"]["authority"] = copy.deepcopy(missing_authority_input)

    wrong_executor = copy.deepcopy(protocol_requests[2])
    wrong_executor["request_id"] = "access-card-wrong-executor"
    wrong_executor["input"]["event"]["executor"]["participant_id"] = "unapproved-machine"

    changed_card = copy.deepcopy(protocol_requests[2])
    changed_card["request_id"] = "access-card-changed-card-identity"
    # The valid request reuses the authority operation's field array. Break that
    # construction-time alias so this scenario changes only the proposed request.
    changed_card["input"]["event"]["native_request"] = copy.deepcopy(changed_card["input"]["event"]["native_request"])
    changed_card["input"]["event"]["native_request"]["fields"][1]["value"]["value"] = "card-999"

    foreign_native_evidence = copy.deepcopy(native_evidence)
    foreign_native_evidence["evidence_id"] = "card-foreign-effect-evidence-1"
    foreign_native_evidence["native_operation_id"] = "card-provider-operation-foreign-1"
    foreign_native_evidence["actual_fields"] = [
        copy.deepcopy(row) for row in foreign_native_evidence["actual_fields"] if row["name"] != "status"
    ]
    foreign_native_evidence["record_digest"] = digest("specimen-native-record", {
        "native_operation_id": foreign_native_evidence["native_operation_id"],
        "actual_fields": foreign_native_evidence["actual_fields"],
    })
    foreign_native_evidence["evidence_ref"] = "card-foreign-effect-record-1"
    foreign_attributed_request = copy.deepcopy(attributed_request)
    foreign_attributed_request["occurrence"] = "foreign-card-occurrence-1"
    foreign_native_evidence["attributed_request"] = foreign_attributed_request
    foreign_native_evidence["native_request_digest"] = digest("native-request", foreign_attributed_request)
    foreign_native = copy.deepcopy(reservation_native)
    foreign_native["id"] = foreign_native_evidence["evidence_id"]
    foreign_native["effect_id"] = foreign_native_evidence["native_operation_id"]
    foreign_native["evidence_ref"] = foreign_native_evidence["evidence_ref"]
    foreign_native["actual_fields"] = copy.deepcopy(foreign_native_evidence["actual_fields"])
    foreign_observed_request = copy.deepcopy(foreign_attributed_request)
    foreign_observed_request["fields"] = copy.deepcopy(foreign_native_evidence["actual_fields"])
    foreign_native["observed_request"] = foreign_observed_request
    foreign_native["completion_mismatch"] = True
    foreign_native["mismatch_reason"] = "UNEXPECTED_EFFECT"
    foreign_committed_event = {
        "id": digest("reservation-committed-event", {
            "budget_digest": budget_definition_digest,
            "effect_id": foreign_native_evidence["native_operation_id"],
            "mapping": "issue-card-count",
        }),
        "state": "ACTIVE",
        "occurred_at": NOW,
        "fields": [field("beneficiary", "b.identity", "employee-7")],
    }
    foreign_history = {
        **initial_history,
        "revision": "1",
        "journal": [{"sequence": "1", "event": foreign_committed_event}],
        "evidence_ref": "card-history-foreign-effect",
    }
    foreign_lifecycle_event_id = "access-card-foreign-completion"
    foreign_settle_event = {
        "id": digest("lifecycle-reservation-event", {
            "instance_id": INSTANCE,
            "lifecycle_event_id": foreign_lifecycle_event_id,
            "lifecycle_event_kind": "EFFECT_OBSERVED",
            "reservation_event_kind": "SETTLE",
            "registry_digest": registry_digest,
        }),
        "expected_revision": "2",
        "kind": "SETTLE",
        "clock": authority_input["clock"],
        "payload": {"native": foreign_native, "histories": [foreign_history]},
        "administration": None,
    }
    foreign_settle_host = {
        "registry_digest": registry_digest,
        "selection_evidence": "registry-selection-evidence",
        "administration_bases": [],
        "authenticated_records": sorted_utf8([
            {"kind": "HISTORY", "record_digest": digest("budget-history", foreign_history), "provider": foreign_history["provider"], "source": foreign_history["source"]},
            {"kind": "NATIVE_OUTCOME", "record_digest": digest("reservation-native-outcome", foreign_native), "provider": foreign_native["provider"], "source": foreign_native["source"]},
        ]),
    }
    foreign_settle_input = {
        "schema": SCHEMA + "reservation-input",
        "specification_pin": PIN,
        "state": registry_reserved,
        "state_digest": reservation_state_digest(registry_reserved),
        "event": foreign_settle_event,
        "host_evidence": foreign_settle_host,
    }
    foreign_completion = {
        "protocol": PROTOCOL,
        "request_id": foreign_lifecycle_event_id,
        "operation": "step",
        "input": {
            "profile": PROFILE,
            "role": ROLE,
            "specification_pin": PIN,
            "definition": work_class,
            "definition_digest": definition_digest,
            "state": work_state_dispatched,
            "state_digest": work_state_digest(work_state_dispatched),
            "event": {
                "schema": SCHEMA + "runtime-event",
                "event_id": foreign_lifecycle_event_id,
                "kind": "EFFECT_OBSERVED",
                "instance_id": INSTANCE,
                "expected_state_revision": "3",
                "expected_state_digest": work_state_digest(work_state_dispatched),
                "permit": None,
                "dispatch_digest": None,
                "native_evidence": foreign_native_evidence,
                "completion_authorization": None,
                "reservation_id": reserve_event_id,
                "affected_budget_anchors": ["cards-per-beneficiary"],
                "budget_inputs": [{
                    "registry_digest": registry_digest,
                    "affected_anchors": ["cards-per-beneficiary"],
                    "expected_revision": "2",
                    "request": foreign_settle_input,
                }],
                "clock_revision": "1",
                "activation_clocks": [],
            },
        },
    }

    exact_replay = copy.deepcopy(protocol_requests[4])
    exact_replay["request_id"] = "access-card-exact-effect-replay"
    exact_replay["input"]["state"] = work_state_completed
    exact_replay["input"]["state_digest"] = work_state_digest(work_state_completed)

    aggregate_coverage = {
        "start": "2026-09-09T12:00:00Z",
        "end": NOW,
        "start_inclusive": False,
        "end_inclusive": True,
    }
    aggregate_key = [typed("b.identity", "employee-7")]
    aggregate_query = {
        "definition_digest": aggregate_definition_digest,
        "interval": aggregate_coverage,
        "keys": [aggregate_key],
    }
    aggregate_observation = {
        "kind": "EVENT_SNAPSHOT",
        "provider": "card-provider",
        "source": "card-ledger",
        "request_digest": digest("aggregate-query", aggregate_query),
        "status": "AVAILABLE",
        "as_of": NOW,
        "revision": "card-history-r1",
        "coverage": aggregate_coverage,
        "events": [{
            "id": "previous-card-issuance",
            "state": "ACTIVE",
            "occurred_at": "2026-09-10T11:00:00Z",
            "fields": [field("beneficiary", "b.identity", "employee-7")],
        }],
        "evidence_ref": "access-card-cap-history",
    }
    aggregate_operation = {
        "step": "issue-card",
        "occurrence": occurrence["occurrence_id"],
        "fields": [field("beneficiary", "b.identity", "employee-7")],
    }
    aggregate_request = {
        "schema": SCHEMA + "aggregate-input",
        "specification_pin": PIN,
        "definition": aggregate_definition,
        "definition_digest": aggregate_definition_digest,
        "clock": {"source": "governance-clock", "status": "AVAILABLE", "instant": NOW},
        "operations": [aggregate_operation],
        "observations": [aggregate_observation],
        "pending": [],
    }
    cap_boundary = {
        "protocol": PROTOCOL,
        "request_id": "access-card-cap-boundary",
        "operation": "evaluate",
        "input": {"kind": "AGGREGATE", "request": aggregate_request},
    }
    combined_exposure = copy.deepcopy(cap_boundary)
    combined_exposure["request_id"] = "access-card-combined-exposure"
    combined_exposure["input"]["request"]["pending"] = [{
        "reservation": "prior-open-card-reservation",
        "mapping": "issue-card-count",
        "occurrence": "prior-card-occurrence",
        "key": aggregate_key,
        "contribution": typed("b.count", "1"),
    }]

    scenario_requests = [missing_authority, wrong_executor, changed_card, foreign_completion, exact_replay, cap_boundary, combined_exposure]
    scenario_expectations = {
        "candidate_pin": PIN,
        "status": "DERIVED_PENDING_INDEPENDENT_REVIEW",
        "method": "Each judgment was derived from the cited normative rule before either draft-2 implementation or its output was inspected.",
        "scenarios": [
            {
                "id": "access-card-valid-issuance",
                "input": {"trace": "valid-trace/requests.jsonl"},
                "expected_judgment": "DEPLOYED, CLOCK_RECORDED, PERMITTED with one atomic reservation, ACKNOWLEDGED, then COMPLETED with a SETTLED reservation",
                "state_and_budget_consequence": "The instance is COMPLETE, the exact occurrence is SUCCEEDED, and the beneficiary partition replaces one pending issuance with one committed issuance.",
                "normative_references": ["LIFE-003", "LIFE-007", "LIFE-009", "LIFE-010", "RES-005", "RES-007"],
            },
            {
                "id": "access-card-missing-authority",
                "input": {"request_id": "access-card-missing-authority"},
                "expected_judgment": "STEP/WITHHELD with AUTHORITY_REQUIRED and EVIDENCE_UNAVAILABLE",
                "state_and_budget_consequence": "A withholding proposal and decision are retained; no permit or reservation is created, and the supplied registry is unchanged.",
                "normative_references": ["AUTH-005", "LIFE-006", "LIFE-007"],
            },
            {
                "id": "access-card-wrong-executor",
                "input": {"request_id": "access-card-wrong-executor"},
                "expected_judgment": "REFUSED/BINDING_MISMATCH",
                "state_and_budget_consequence": "Work and budget states are returned unchanged; authority and reservation are not evaluated.",
                "normative_references": ["LIFE-006", "LIFE-007"],
            },
            {
                "id": "access-card-changed-card-identity",
                "input": {"request_id": "access-card-changed-card-identity"},
                "expected_judgment": "REFUSED/BINDING_MISMATCH",
                "state_and_budget_consequence": "The native request differs from the exact authority subject. Work and budget states are returned unchanged.",
                "normative_references": ["AUTH-002", "LIFE-007"],
            },
            {
                "id": "access-card-foreign-completion",
                "input": {"request_id": foreign_lifecycle_event_id},
                "expected_judgment": "STEP/DISPUTED/BUDGET_EFFECT_DISPUTED+FOREIGN_EFFECT+UNEXPECTED_EFFECT with EFFECT/FOREIGN and reservation EFFECT_DISPUTED/UNEXPECTED_EFFECT",
                "state_and_budget_consequence": "The foreign fact is retained as disputed exposure, the affected beneficiary partition is blocked, and the governed occurrence does not complete or route.",
                "normative_references": ["LIFE-010", "LIFE-011", "RES-007", "RES-WIRE-003"],
            },
            {
                "id": "access-card-exact-replay",
                "input": {"request_id": "access-card-exact-effect-replay"},
                "expected_judgment": "STEP with replay true and the original COMPLETED transition",
                "state_and_budget_consequence": "The original decision, budget result, transition-state digest and transaction digest are returned with the current complete state; no revision changes.",
                "normative_references": ["LIFE-013", "LIFE-019"],
            },
            {
                "id": "access-card-cap-boundary",
                "input": {"request_id": "access-card-cap-boundary"},
                "expected_judgment": "SATISFIED with exact COUNT accumulator 2",
                "state_and_budget_consequence": "One committed issuance and the proposed issuance reach, but do not exceed, the inclusive cap of two for the beneficiary.",
                "normative_references": ["AGG-002", "AGG-003", "AGG-004", "AGG-008"],
            },
            {
                "id": "access-card-combined-exposure",
                "input": {"request_id": "access-card-combined-exposure"},
                "expected_judgment": "VIOLATED with exact COUNT accumulator 3 and BOUND_VIOLATED",
                "state_and_budget_consequence": "One committed issuance, one distinct unsettled reservation and the proposed issuance exceed the same cap; an enclosing reservation transition must withhold the proposal.",
                "normative_references": ["AGG-002", "AGG-003", "AGG-004", "RES-005"],
            },
        ],
    }
    exact_assertions = {
        "access-card-valid-issuance": {
            "response_dispositions": ["DEPLOYED", "CLOCK_RECORDED", "PERMITTED", "ACKNOWLEDGED", "COMPLETED"],
            "final_work_status": "COMPLETE", "final_work_revision": "4", "final_budget_revision": "3",
            "final_reservation_status": "SETTLED", "committed_count": "1", "pending_count": "0",
        },
        "access-card-missing-authority": {
            "status": "STEP", "disposition": "WITHHELD",
            "reason_codes": ["AUTHORITY_REQUIRED", "EVIDENCE_UNAVAILABLE"],
            "authority_status": "REFUSED", "authority_code": "EVIDENCE_UNAVAILABLE",
            "permit": None, "budget_results": [],
        },
        "access-card-wrong-executor": {
            "status": "REFUSED", "code": "BINDING_MISMATCH", "state_unchanged": True, "budget_unchanged": True,
        },
        "access-card-changed-card-identity": {
            "status": "REFUSED", "code": "BINDING_MISMATCH", "state_unchanged": True, "budget_unchanged": True,
        },
        "access-card-foreign-completion": {
            "status": "STEP", "disposition": "DISPUTED",
            "reason_codes": ["BUDGET_EFFECT_DISPUTED", "FOREIGN_EFFECT", "UNEXPECTED_EFFECT"],
            "classification": "FOREIGN", "budget_decision": "EFFECT_DISPUTED",
            "budget_reasons": ["UNEXPECTED_EFFECT"], "reservation_status": "DISPUTED",
            "blocked_partitions": [{"anchor": "cards-per-beneficiary", "key": [typed("b.identity", "employee-7")]}],
        },
        "access-card-exact-replay": {
            "status": "STEP", "disposition": "COMPLETED", "replay": True,
            "work_status": "COMPLETE", "work_revision": "4", "budget_revision_unchanged": True,
            "decision_digest_equals_original": True, "transaction_digest_equals_original": True,
        },
        "access-card-cap-boundary": {
            "status": "SATISFIED", "accumulator": "2", "partition_status": "SATISFIED", "reasons": [],
        },
        "access-card-combined-exposure": {
            "status": "VIOLATED", "accumulator": "3", "partition_status": "VIOLATED", "reasons": ["BOUND_VIOLATED"],
        },
    }
    for scenario in scenario_expectations["scenarios"]:
        scenario["expected_assertions"] = exact_assertions[scenario["id"]]


    write("source-policy.json", source_policy)
    write("work-class.json", work_class)
    write("authority-definition.json", authority_definition)
    write("authority-input.json", authority_input)
    write("authority-result-derived.json", authority_result)
    write("shared-budget-definition.json", budget_definition)
    write("shared-budget-register-input.json", register_input)
    write("shared-budget-register-result-derived.json", register_result)
    write("deployment-input.json", deploy_input)
    write("deployment-result-derived.json", deploy_result)
    write("valid-trace/requests.json", protocol_requests)
    write("valid-trace/results-derived.json", protocol_results)
    write("valid-trace/final-work-state.json", work_state_completed)
    write("valid-trace/final-budget-state.json", registry_settled)
    write("readback-derived.json", readback_result)
    write("correspondence-input.json", correspondence_input)
    write("correspondence-record.json", correspondence)
    write("scenarios/requests.json", scenario_requests)
    write("scenarios/expectations.json", scenario_expectations)

    (HERE / "valid-trace" / "requests.jsonl").write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in protocol_requests))
    (HERE / "valid-trace" / "results-derived.jsonl").write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in protocol_results))
    (HERE / "scenarios" / "requests.jsonl").write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in scenario_requests))

    index = {
        "candidate_pin": PIN,
        "construction": "INDEPENDENT_FROM_DRAFT2_IMPLEMENTATIONS",
        "status": "CONTRACT_DERIVED_CROSS_LANGUAGE_VERIFIED_NON_NORMATIVE",
        "files": [],
    }
    for path in sorted(HERE.rglob("*.json")) + sorted(HERE.rglob("*.jsonl")):
        if path.name == "artifact-index.json":
            continue
        index["files"].append({"path": path.relative_to(HERE).as_posix(), "sha256": raw_sha(path.read_bytes())})
    write("artifact-index.json", index)


if __name__ == "__main__":
    main()
