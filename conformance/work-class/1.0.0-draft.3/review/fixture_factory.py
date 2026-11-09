"""Normative fixture constructors for draft-2 corpus authoring.

The constructors choose explicit synthetic facts, then apply only digest and
record-construction rules stated by the contract. They do not consult either
draft-2 implementation.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import Any

from corpus_common import candidate_pin, digest


PIN = candidate_pin()


def typed(type_ref: str, value: str) -> dict[str, str]:
    return {"type_ref": type_ref, "value": value}


def operation_step(
    step_id: str = "issue-card",
    authority_requirement: str = "access-card-authority",
    shared_budgets: list[str] | None = None,
    quantity_mode: str | None = None,
    exclusive_keys: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    step = {
        "id": step_id,
        "kind": "OPERATION",
        "executor_role": "access-operator",
        "interface": "access-control",
        "operation": step_id,
        "fields": [
            {"name": "card-id", "type_ref": "identity"},
            {"name": "employee-id", "type_ref": "identity"},
        ],
        "scope_fields": {"subjects": ["employee-id"], "resources": ["card-id"]},
        "required_credentials": ["access-operator-credential"],
        "authority_requirements": [authority_requirement],
        "shared_budgets": [] if shared_budgets is None else list(shared_budgets),
        "prior_effect_bindings": [],
        "prior_actor_separations": [],
        "permit_seconds": "300",
        "failure_behavior": "STOP",
        "completion": {
            "terminal_policy": "LEGACY_NONTERMINAL", "effect_provider": "access-provider",
            "effect_source": "access-control",
            "effect_record_type": "card-result",
            "no_effect_provider": "access-provider",
            "no_effect_source": "access-control",
            "no_effect_record_type": "card-no-effect",
            "status_field": "status",
            "status_type_ref": "status",
            "success_values": [typed("status", "ISSUED")],
            "failure_values": [typed("status", "REJECTED")],
            "route_label_field": None,
            "route_label_type_ref": None,
            "evidence_bindings": [
                {"request_field": "card-id", "evidence_field": "card-id"},
                {"request_field": "employee-id", "evidence_field": "employee-id"},
            ],
        },
    }
    step["quantity_mode"] = "BOUNDED" if quantity_mode is None else quantity_mode
    step["exclusive_keys"] = copy.deepcopy(exclusive_keys or [])
    return step


def structural_step(step_id: str, kind: str) -> dict[str, Any]:
    return {
        "id": step_id,
        "kind": kind,
        "executor_role": None,
        "interface": None,
        "operation": None,
        "fields": [],
        "scope_fields": None,
        "required_credentials": [],
        "authority_requirements": [],
        "shared_budgets": [],
        "exclusive_keys": [],
        "prior_effect_bindings": [],
        "prior_actor_separations": [],
        "permit_seconds": None,
        "failure_behavior": None,
        "completion": None,
    }


def work_class(
    profile: str = "LINEAR",
    *,
    deadline_due: dict[str, str] | None = None,
    deadline_boundary: str = "AT_OR_AFTER",
    instance_limits: dict[str, str] | None = None,
    quantity_mode: str | None = None,
) -> dict[str, Any]:
    deadline = []
    relationships: list[dict[str, Any]] = [{"kind": "SEQUENCE", "from": "issue-card", "to": "terminal"}]
    if deadline_due is not None:
        deadline = [
            {
                "id": "issue-card-deadline",
                "step_id": "issue-card",
                "clock_source": "work-clock",
                "due": deadline_due,
                "boundary": deadline_boundary,
                "expiry_target": "terminal",
            }
        ]
        relationships.append(
            {
                "kind": "EXPIRY",
                "from": "issue-card",
                "to": "terminal",
                "deadline_ref": "issue-card-deadline",
            }
        )
    limits = {
        "maximum_proposals": "64",
        "maximum_activations": "64",
        "maximum_actuations": "64",
        "maximum_active_obligations": "64",
        "maximum_fanout_objects": "64",
    }
    if instance_limits:
        limits.update(instance_limits)
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/work-class-definition",
        "specification_pin": PIN,
        "id": "access-card",
        "revision": "revision-1",
        "profile": profile,
        "root": "issue-card",
        "participants": [{"id": "operator-1", "role": "access-operator", "kind": "AGENT"}],
        "objects": [],
        "types": [
            {"id": "identity", "kind": "IDENTITY", "nonnegative": False, "unit": None},
            {"id": "status", "kind": "STRING", "nonnegative": False, "unit": None},
        ],
        "steps": [operation_step(quantity_mode=quantity_mode), structural_step("terminal", "TERMINAL")],
        "relationships": relationships,
        "choices": [],
        "occurrence_limits": [{"step_id": "issue-card", "maximum": "1"}],
        "loops": [],
        "deadlines": deadline,
        "parallel_blocks": [],
        "fanouts": [],
        "shared_budgets": [],
        "limits": limits,
        "source": {
            "id": "access-policy",
            "revision": "revision-1",
            "obligations": ["authorize-card-issuance"],
        },
    }


def available_clock(source: str, revision: str, observed_time: str) -> dict[str, str]:
    return {
        "source": source,
        "revision": revision,
        "status": "AVAILABLE",
        "observed_time": observed_time,
        "evidence_digest": digest(
            "clock-evidence",
            {"source": source, "revision": revision, "observed_time": observed_time},
        ),
    }


def occurrence(
    definition_digest: str,
    instance_id: str,
    step_id: str,
    ordinal: str = "1",
    predecessors: list[str] | None = None,
    enclosing: list[dict[str, Any]] | None = None,
    object_key: dict[str, str] | None = None,
) -> dict[str, Any]:
    subject = {
        "specification_pin": PIN,
        "work_class_digest": definition_digest,
        "instance_id": instance_id,
        "step_id": step_id,
        "ordinal": ordinal,
        "predecessor_occurrence_ids": [] if predecessors is None else list(predecessors),
        "enclosing": [] if enclosing is None else copy.deepcopy(enclosing),
        "object_key": copy.deepcopy(object_key),
    }
    return {"occurrence_id": digest("occurrence", subject), **subject}


def add_seconds(instant: str, seconds: str) -> str:
    value = dt.datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return (value + dt.timedelta(seconds=int(seconds))).strftime("%Y-%m-%dT%H:%M:%SZ")


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def readback_paths(value: Any, path: str = "") -> list[str]:
    """WCS2-005 readback provision paths: scalar leaves and empty collections, raw UTF-8 sorted."""
    if isinstance(value, dict) and value:
        rows: list[str] = []
        for key, member in value.items():
            rows.extend(readback_paths(member, path + "/" + pointer_token(key)))
    elif isinstance(value, list) and value:
        rows = []
        for index, member in enumerate(value):
            rows.extend(readback_paths(member, path + "/" + str(index)))
    else:
        rows = [path]
    return sorted(rows, key=lambda row: row.encode("utf-8")) if path == "" else rows


def deployment_evidence(
    definition: dict[str, Any],
    *,
    recorded_at: str,
    id_prefix: str = "deployment",
    correspondence_status: str = "ACCEPTED",
    review_status: str = "ACCEPTED",
    source_confirmation_status: str = "ACCEPTED",
    policy_decision_status: str = "ACCEPTED",
    correspondence_mappings: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """LIFE-003 deployment evidence: an accepted correspondence for the exact definition, using supplied
    mappings or mapping every source obligation to the complete path set by default, a source confirmation over
    digest("work-class-source", source) naming the complete obligation list, and a policy decision over the
    definition digest."""
    work_digest = digest("work-class-definition", definition)
    paths = readback_paths(definition)
    obligations = list(definition["source"]["obligations"])
    correspondence = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": id_prefix + "-correspondence",
        "kind": "CORRESPONDENCE",
        "status": correspondence_status,
        "subject_digest": work_digest,
        "source_id": definition["source"]["id"],
        "source_revision": definition["source"]["revision"],
        "work_class_digest": work_digest,
        "mappings": copy.deepcopy(correspondence_mappings) if correspondence_mappings is not None else [
            {"source_obligation_id": obligation, "provision_paths": list(paths)} for obligation in obligations],
        "uncovered_source_obligation_ids": [],
        "unsupported_provision_paths": [],
        "residue": [],
        "recorded_at": recorded_at,
        "provenance_digest": digest("evidence-provenance", {"evidence_id": id_prefix + "-correspondence"}),
    }
    review_subject = digest("correspondence-subject", correspondence)
    correspondence["review"] = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": id_prefix + "-correspondence-review",
        "kind": "REVIEW",
        "status": review_status,
        "subject_digest": review_subject,
        "reviewer_id": "reviewer-1",
        "paragraph_ids": [],
        "case_ids": [],
        "finding_ids": [],
        "recorded_at": recorded_at,
        "provenance_digest": digest("evidence-provenance", {"evidence_id": id_prefix + "-correspondence-review"}),
    }
    source_confirmation = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": id_prefix + "-source-confirmation",
        "kind": "SOURCE_CONFIRMATION",
        "status": source_confirmation_status,
        "subject_digest": digest("work-class-source", definition["source"]),
        "actor_id": "source-confirmer-1",
        "scope_ids": obligations,
        "recorded_at": recorded_at,
        "provenance_digest": digest("evidence-provenance", {"evidence_id": id_prefix + "-source-confirmation"}),
    }
    policy_decision = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": id_prefix + "-policy-decision",
        "kind": "POLICY_DECISION",
        "status": policy_decision_status,
        "subject_digest": work_digest,
        "decision_maker_id": "policy-owner-1",
        "decision_ids": [id_prefix + "-policy-decision-1"],
        "recorded_at": recorded_at,
        "provenance_digest": digest("evidence-provenance", {"evidence_id": id_prefix + "-policy-decision"}),
    }
    return correspondence, source_confirmation, policy_decision


def deployment(
    definition: dict[str, Any],
    *,
    instance_id: str = "access-instance-1",
    organization_id: str = "organization-1",
    authorization_time: str = "2026-09-11T00:00:00Z",
    authorization_expires_at: str | None = None,
    evidence_status: str = "ACCEPTED",
    evidence_expires_at: str = "2026-09-12T00:00:00Z",
    initial_clocks: list[dict[str, str]] | None = None,
    correspondence_mappings: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    definition_digest = digest("work-class-definition", definition)
    profile = definition["profile"]
    role = {
        "LINEAR": "LINEAR_WORK_RUNTIME",
        "CHOICE_LOOPS": "CHOICE_LOOP_RUNTIME",
        "DEADLINES": "DEADLINE_RUNTIME",
        "PARALLEL_FANOUT": "PARALLEL_FANOUT_RUNTIME",
    }[profile]
    evidence_placeholder = "sha256:" + "0" * 64
    correspondence, source_confirmation, policy_decision = deployment_evidence(
        definition, recorded_at=authorization_time, correspondence_mappings=correspondence_mappings)
    correspondence_digest = digest("evidence", correspondence)
    source_confirmation_digest = digest("evidence", source_confirmation)
    policy_decision_digest = digest("evidence", policy_decision)
    authorization = {
        "schema": "seampoint.work-class/1.0.0-draft.3/deployment-authorization",
        "authorization_id": "deployment-authorization-1",
        "specification_pin": PIN,
        "work_class_digest": definition_digest,
        "profile": profile,
        "role": role,
        "instance_id": instance_id,
        "organization_id": organization_id,
        "status": "AUTHORIZED",
        "authorization_evidence_digest": evidence_placeholder,
        "correspondence_evidence_digest": correspondence_digest,
        "source_confirmation_evidence_digest": source_confirmation_digest,
        "policy_decision_evidence_digest": policy_decision_digest,
        "authorized_at": authorization_time,
        "expires_at": authorization_expires_at,
    }
    subject = dict(authorization)
    del subject["authorization_evidence_digest"]
    subject_digest = digest("deployment-authorization-subject", subject)
    scope = sorted([PIN, definition_digest, profile, role, instance_id], key=lambda value: value.encode("utf-8"))
    evidence = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": "deployment-evidence-1",
        "kind": "ORGANIZATIONAL_AUTHORIZATION",
        "status": evidence_status,
        "subject_digest": subject_digest,
        "organization_id": organization_id,
        "authorizer_id": "authorizer-1",
        "authorization_scope": scope,
        "recorded_at": authorization_time,
        "expires_at": evidence_expires_at,
        "provenance_digest": digest(
            "evidence-provenance", {"evidence_id": "deployment-evidence-1", "organization_id": organization_id}
        ),
    }
    evidence_digest = digest("evidence", evidence)
    authorization["authorization_evidence_digest"] = evidence_digest
    authorization_digest = digest("deployment-authorization", authorization)
    authorization_clock = available_clock("deployment-clock", "1", authorization_time)
    clocks = [] if initial_clocks is None else copy.deepcopy(initial_clocks)
    deploy_input = {
        "profile": profile,
        "role": role,
        "specification_pin": PIN,
        "definition": copy.deepcopy(definition),
        "definition_digest": definition_digest,
        "instance_id": instance_id,
        "deployment_authorization": authorization,
        "authorization_evidence": evidence,
        "correspondence_evidence": correspondence,
        "source_confirmation_evidence": source_confirmation,
        "policy_decision_evidence": policy_decision,
        "authorization_clock": authorization_clock,
        "initial_clocks": clocks,
    }
    root_loop = next((row for row in definition["loops"] if row["entry_step_id"] == definition["root"]), None)
    root_enclosing = (
        []
        if root_loop is None
        else [
            {
                "kind": "LOOP",
                "construct_id": root_loop["id"],
                "pass": "1",
                "branch_id": None,
                "object_key": None,
            }
        ]
    )
    root = occurrence(definition_digest, instance_id, definition["root"], enclosing=root_enclosing)
    activation_digest = digest(
        "deployment-activation",
        {
            "deployment_authorization_digest": authorization_digest,
            "instance_id": instance_id,
            "occurrence_id": root["occurrence_id"],
        },
    )
    root_deadline_ids = [row["id"] for row in definition["deadlines"] if row["step_id"] == definition["root"]]
    deadline_states = []
    for deadline in definition["deadlines"]:
        if deadline["step_id"] != definition["root"] or deadline["due"]["kind"] in {"ELAPSED_FROM_FIRST_WITHHELD", "ELAPSED_FROM_FIRST_DISPATCH"}:
            continue
        clock = next(row for row in clocks if row["source"] == deadline["clock_source"])
        due = deadline["due"]["instant"] if deadline["due"]["kind"] == "ABSOLUTE_INSTANT" else add_seconds(
            clock["observed_time"],
            str(int(deadline["due"]["value"]) * {"SECOND": 1, "MINUTE": 60, "HOUR": 3600, "DAY": 86400}[deadline["due"]["unit"]]),
        )
        activation_subject = {
            "deadline_id": deadline["id"],
            "occurrence_id": root["occurrence_id"],
            "trigger_digest": activation_digest,
            "source": deadline["clock_source"],
            "activation_revision": "0",
            "activation_clock_revision": clock["revision"],
            "activation_instant": clock["observed_time"],
            "activation_clock_evidence_digest": clock["evidence_digest"],
            "due": due,
            "boundary": deadline["boundary"],
        }
        deadline_states.append(
            {
                "deadline_id": deadline["id"],
                "occurrence_id": root["occurrence_id"],
                "source": deadline["clock_source"],
                "activation_revision": "0",
                "activation_digest": digest("deadline-activation", activation_subject),
                "trigger_digest": activation_digest,
                "activation_clock_revision": clock["revision"],
                "activation_instant": clock["observed_time"],
                "activation_clock_evidence_digest": clock["evidence_digest"],
                "due": due,
                "boundary": deadline["boundary"],
                "status": "PENDING",
                "expiry_event_digest": None,
            }
        )
    proposal_steps = [step for step in definition["steps"] if step["kind"] in {"OPERATION", "FANOUT_EXPAND"}]
    state = {
        "schema": "seampoint.work-class/1.0.0-draft.3/work-state",
        "specification_pin": PIN,
        "work_class_digest": definition_digest,
        "profile": profile,
        "role": role,
        "instance_id": instance_id,
        "deployment_authorization": copy.deepcopy(authorization),
        "deployment_authorization_subject_digest": subject_digest,
        "deployment_authorization_digest": authorization_digest,
        "deployment_authorization_evidence": copy.deepcopy(evidence),
        "deployment_authorization_evidence_digest": evidence_digest,
        "deployment_correspondence_evidence": copy.deepcopy(correspondence),
        "deployment_correspondence_evidence_digest": correspondence_digest,
        "deployment_source_confirmation_evidence": copy.deepcopy(source_confirmation),
        "deployment_source_confirmation_evidence_digest": source_confirmation_digest,
        "deployment_policy_decision_evidence": copy.deepcopy(policy_decision),
        "deployment_policy_decision_evidence_digest": policy_decision_digest,
        "deployment_authorization_clock": authorization_clock,
        "deployment_organization_id": organization_id,
        "revision": "0",
        "status": "ACTIVE",
        "total_activations": "1",
        "total_actuations": "0",
        "step_counters": [
            {
                "step_id": step["id"],
                "activations": "1" if step["id"] == definition["root"] else "0",
                "actuations": "0",
            }
            for step in sorted(proposal_steps, key=lambda row: row["id"].encode("utf-8"))
        ],
        "active": [
            {
                "occurrence": root,
                "activation_event_digest": activation_digest,
                "status": "ACTIVE",
                "deadline_ids": root_deadline_ids,
            }
        ],
        "completed": [],
        "obligations": [],
        "proposals": [],
        "permits": [],
        "dispatches": [],
        "outcomes": [],
        "clocks": clocks,
        "deadlines": deadline_states,
        "fanout_passes": [],
        "receipts": [],
        "replays": [],
    }
    if any(step.get("dispatch_gate") for step in definition["steps"]):
        state["authorizations"] = []
        state["authorization_evaluations"] = []
    if definition.get("recovery"):
        state["recovery_records"] = []
    if any((step.get("completion") or {}).get("terminal_policy") == "STOP_RETAIN" for step in definition["steps"]):
        state["completion_checks"] = []
        state["terminal_records"] = []
        state["referrals"] = []
    elif any(step.get("referral_policy") for step in definition["steps"]):
        state["referrals"] = []
    if any((step.get("referral_policy") or {}).get("authority") for step in definition["steps"]):
        state["proposal_authority_evaluations"] = []
    state_digest = digest("work-state", state)
    result = {
        "status": "DEPLOYED",
        "profile": profile,
        "role": role,
        "instance_id": instance_id,
        "work_class_digest": definition_digest,
        "deployment_authorization_digest": authorization_digest,
        "state": state,
        "state_digest": state_digest,
    }
    return deploy_input, result


def deploy_refusal(profile: str, role: str, code: str) -> dict[str, str]:
    return {"status": "REFUSED", "profile": profile, "role": role, "code": code, "path": ""}
