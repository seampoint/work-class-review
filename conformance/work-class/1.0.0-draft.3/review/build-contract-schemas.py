#!/usr/bin/env python3
"""Build the draft-3 schemas whose public objects must be closed."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from equipment_schema_extensions import extend_authority, extend_common, extend_lifecycle, extend_reservation, extend_work
from equipment_history_schema import extend_reservation_schema
from equipment_completion_schema import extend_completion_schemas
from equipment_boundary_schema import extend_boundary_evidence
from equipment_correction_schema import extend_correction_schemas
from recovery_schema_extensions import extend_recovery_schemas
from timing_schema_extensions import extend_timing_schemas
from cdmo_schema_extensions import extend_cdmo_schemas
from holdings_schema_extensions import extend_holdings_schemas, holdings_schema
from assessment_schema_extensions import extend_assessment_schemas
from information_flow_schema_extensions import extend_information_flow_schemas, information_flow_schema


ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "library/work-class-specification/1.0.0-draft.3"
BASE = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/"
VERSION = "seampoint.work-class/1.0.0-draft.3/"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.3"


def ref(value: str) -> dict:
    return {"$ref": value}


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


def arr(items: dict, minimum: int = 0, maximum: int | None = None, unique: bool = False) -> dict:
    result = {"type": "array", "items": items, "minItems": minimum}
    if maximum is not None:
        result["maxItems"] = maximum
    if unique:
        result["uniqueItems"] = True
    return result


def nullable(schema: dict) -> dict:
    return {"oneOf": [schema, {"type": "null"}]}


ID = {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9._:/-]{0,127}$"}
DIGEST = {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"}
NATURAL = {"type": "string", "pattern": r"^(0|[1-9][0-9]*)$"}
INSTANT = {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}
PROFILE = {"enum": ["LINEAR", "CHOICE_LOOPS", "DEADLINES", "PARALLEL_FANOUT"]}
RUNTIME_ROLE = {"enum": ["LINEAR_WORK_RUNTIME", "CHOICE_LOOP_RUNTIME", "DEADLINE_RUNTIME", "PARALLEL_FANOUT_RUNTIME"]}
REFUSAL_CODES = [
    "ADMINISTRATION_NOT_ESTABLISHED",
    "ARTIFACT_ENCODING_INVALID",
    "ARTIFACT_NONCANONICAL",
    "BINDING_MISMATCH",
    "CLOCK_INVALID",
    "DEFINITION_INVALID",
    "DEFINITION_CONFLICT",
    "DEPENDENCY_MISMATCH",
    "DIGEST_MISMATCH",
    "EVIDENCE_UNAVAILABLE",
    "INPUT_INVALID",
    "LIMIT_EXCEEDED",
    "INSTANCE_NOT_ACTIVE",
    "OCCURRENCE_NOT_ACTIVE",
    "OCCURRENCE_CONFLICT",
    "PREREQUISITE_MISSING",
    "PROTOCOL_INVALID",
    "REFERENCE_INVALID",
    "RESERVATION_NOT_FOUND",
    "REPLAY_CONFLICT",
    "REVISION_CONFLICT",
    "ROLE_UNSUPPORTED",
    "SCHEMA_INVALID",
    "STATE_INVALID",
    "TYPE_INVALID",
    "UNSUPPORTED_FEATURE",
    "UNSUPPORTED_RELATION",
    "VERSION_UNSUPPORTED",
]


def write(name: str, value: dict) -> None:
    (LIB / name).write_text(json.dumps(value, indent=2, sort_keys=False) + "\n")


typed_value = ref(BASE + "aggregate.schema.json#/$defs/value")
field_value = ref(BASE + "aggregate.schema.json#/$defs/field")


work_defs: dict[str, dict] = {
    "id": ID,
    "digest": DIGEST,
    "natural": NATURAL,
    "profile": PROFILE,
    "runtimeRole": RUNTIME_ROLE,
    "type": obj(
        {
            "id": ref("#/$defs/id"),
            "kind": {"enum": ["IDENTITY", "STRING", "BOOLEAN", "INTEGER", "DECIMAL", "INSTANT"]},
            "nonnegative": {"type": "boolean"},
            "unit": nullable({"type": "string", "minLength": 1}),
        }
    ),
    "fieldDeclaration": obj({"name": ref("#/$defs/id"), "type_ref": ref("#/$defs/id")}),
    "scopeFields": obj(
        {
            "subjects": arr(ref("#/$defs/id"), 1, 64, True),
            "resources": arr(ref("#/$defs/id"), 1, 64, True),
        }
    ),
    "exclusiveKey": obj(
        {
            "id": ref("#/$defs/id"),
            "slot": ref("#/$defs/id"),
            "namespace": ref("#/$defs/id"),
            "projection": arr(
                obj(
                    {
                        "field": ref("#/$defs/id"),
                        "type_ref": ref("#/$defs/id"),
                    }
                ),
                1,
                64,
            ),
            "retention": {"const": "RETAIN_UNTIL_SETTLED_OR_AUTHORIZED_RELEASE"},
        }
    ),
    "participant": obj(
        {
            "id": ref("#/$defs/id"),
            "role": ref("#/$defs/id"),
            "kind": {"enum": ["PERSON", "ORGANIZATION", "AGENT", "SYSTEM", "CONNECTOR"]},
        }
    ),
    "objectDeclaration": obj({"id": ref("#/$defs/id"), "type_ref": ref("#/$defs/id")}),
    "evidenceBinding": obj(
        {
            "request_field": ref("#/$defs/id"),
            "evidence_field": ref("#/$defs/id"),
        }
    ),
    "completionCarrier": obj(
        {
            "effect_provider": ref("#/$defs/id"),
            "effect_source": ref("#/$defs/id"),
            "effect_record_type": ref("#/$defs/id"),
            "no_effect_provider": ref("#/$defs/id"),
            "no_effect_source": ref("#/$defs/id"),
            "no_effect_record_type": ref("#/$defs/id"),
            "status_field": ref("#/$defs/id"),
            "status_type_ref": ref("#/$defs/id"),
            "success_values": arr(typed_value, 1, 64, True),
            "failure_values": arr(typed_value, 0, 64, True),
            "route_label_field": nullable(ref("#/$defs/id")),
            "route_label_type_ref": nullable(ref("#/$defs/id")),
            "evidence_bindings": arr(ref("#/$defs/evidenceBinding"), 0, 64),
        }
    ),
    "priorEffectBinding": obj(
        {
            "id": ref("#/$defs/id"),
            "selection": {"const": "UNIQUE_COMPLETED_ANCESTOR"},
            "source_step_id": ref("#/$defs/id"),
            "source_evidence_field": ref("#/$defs/id"),
            "target_request_field": ref("#/$defs/id"),
        }
    ),
    "priorActorSeparation": obj(
        {
            "id": ref("#/$defs/id"),
            "relation": {"const": "DISTINCT_ACTOR"},
            "selection": {"const": "UNIQUE_COMPLETED_ANCESTOR"},
            "prior_step_id": ref("#/$defs/id"),
            "prior_act_kind": {"enum": ["VERIFY", "INSTANCE_DECISION"]},
            "current_act_kind": {"enum": ["VERIFY", "INSTANCE_DECISION"]},
        }
    ),
    "step": obj(
        {
            "id": ref("#/$defs/id"),
            "kind": {"enum": ["OPERATION", "PARALLEL_SPLIT", "PARALLEL_JOIN", "FANOUT_EXPAND", "FANOUT_JOIN", "TERMINAL"]},
            "executor_role": nullable(ref("#/$defs/id")),
            "interface": nullable(ref("#/$defs/id")),
            "operation": nullable(ref("#/$defs/id")),
            "fields": arr(ref("#/$defs/fieldDeclaration"), 0, 64),
            "scope_fields": nullable(ref("#/$defs/scopeFields")),
            "required_credentials": arr(ref("#/$defs/id"), 0, 64, True),
            "authority_requirements": arr(ref("#/$defs/id"), 0, 1, True),
            "shared_budgets": arr(ref("#/$defs/id"), 0, 64, True),
            "exclusive_keys": arr(ref("#/$defs/exclusiveKey"), 0, 32),
            "quantity_mode": {"enum": ["BOUNDED", "NONE"]},
            "prior_effect_bindings": arr(ref("#/$defs/priorEffectBinding"), 0, 64),
            "prior_actor_separations": arr(ref("#/$defs/priorActorSeparation"), 0, 64),
            "permit_seconds": nullable({"type": "string", "pattern": r"^[1-9][0-9]*$"}),
            "failure_behavior": nullable({"enum": ["FAILURE_EDGE", "STOP"]}),
            "completion": nullable(ref("#/$defs/completionCarrier")),
        }
    ),
    "sequenceEdge": obj(
        {"kind": {"const": "SEQUENCE"}, "from": ref("#/$defs/id"), "to": ref("#/$defs/id")}
    ),
    "failureEdge": obj(
        {"kind": {"const": "FAILURE"}, "from": ref("#/$defs/id"), "to": ref("#/$defs/id")}
    ),
    "labelEdge": obj(
        {
            "kind": {"const": "LABEL"},
            "from": ref("#/$defs/id"),
            "to": ref("#/$defs/id"),
            "label": typed_value,
        }
    ),
    "expiryEdge": obj(
        {
            "kind": {"const": "EXPIRY"},
            "from": ref("#/$defs/id"),
            "to": ref("#/$defs/id"),
            "deadline_ref": ref("#/$defs/id"),
        }
    ),
    "relationship": {
        "oneOf": [ref("#/$defs/sequenceEdge"), ref("#/$defs/failureEdge"), ref("#/$defs/labelEdge"), ref("#/$defs/expiryEdge")]
    },
    "choice": obj(
        {
            "step_id": ref("#/$defs/id"),
            "label_type_ref": ref("#/$defs/id"),
            "label_values": arr(typed_value, 1, 64, True),
        }
    ),
    "occurrenceLimit": obj(
        {
            "step_id": ref("#/$defs/id"),
            "maximum": NATURAL,
        }
    ),
    "loop": obj(
        {
            "id": ref("#/$defs/id"),
            "entry_step_id": ref("#/$defs/id"),
            "member_step_ids": arr(ref("#/$defs/id"), 1, 256, True),
            "back_edge_from_step_id": ref("#/$defs/id"),
            "maximum_passes": {"type": "string", "pattern": r"^[1-9][0-9]*$"},
        }
    ),
    "absoluteDue": obj({"kind": {"const": "ABSOLUTE_INSTANT"}, "instant": INSTANT}),
    "elapsedDue": obj(
        {
            "kind": {"const": "ELAPSED_DURATION"},
            "value": {"type": "string", "pattern": r"^[1-9][0-9]*$"},
            "unit": {"enum": ["SECOND", "MINUTE", "HOUR", "DAY"]},
        }
    ),
    "ancestorDue": obj(
        {
            "kind": {"const": "ELAPSED_FROM_ANCESTOR"},
            "value": {"type": "string", "pattern": r"^[1-9][0-9]*$"},
            "unit": {"enum": ["SECOND", "MINUTE", "HOUR", "DAY"]},
            "anchor_step_id": ref("#/$defs/id"),
        }
    ),
    "deadline": obj(
        {
            "id": ref("#/$defs/id"),
            "step_id": ref("#/$defs/id"),
            "clock_source": ref("#/$defs/id"),
            "due": {"oneOf": [ref("#/$defs/absoluteDue"), ref("#/$defs/elapsedDue"), ref("#/$defs/ancestorDue")]},
            "boundary": {"enum": ["AT_OR_AFTER", "AFTER"]},
            "expiry_target": nullable(ref("#/$defs/id")),
        }
    ),
    "parallelBranch": obj({"id": ref("#/$defs/id"), "head_step_id": ref("#/$defs/id")}),
    "parallelBlock": obj(
        {
            "id": ref("#/$defs/id"),
            "split_step_id": ref("#/$defs/id"),
            "branches": arr(ref("#/$defs/parallelBranch"), 2, 64),
            "join_step_id": ref("#/$defs/id"),
        }
    ),
    "fanout": obj(
        {
            "id": ref("#/$defs/id"),
            "expand_step_id": ref("#/$defs/id"),
            "region_head_step_id": ref("#/$defs/id"),
            "join_step_id": ref("#/$defs/id"),
            "object_field": ref("#/$defs/id"),
            "object_request_field": ref("#/$defs/id"),
            "object_type_ref": ref("#/$defs/id"),
            "empty_set_behavior": {"enum": ["ADVANCE_TO_JOIN", "STOP"]},
        }
    ),
    "source": obj(
        {
            "id": ref("#/$defs/id"),
            "revision": ref("#/$defs/id"),
            "obligations": arr(ref("#/$defs/id"), 1, 1024, True),
        }
    ),
    "limits": obj(
        {
            "maximum_proposals": ref("#/$defs/natural"),
            "maximum_activations": {"type": "string", "pattern": r"^[1-9][0-9]*$"},
            "maximum_actuations": ref("#/$defs/natural"),
            "maximum_active_obligations": ref("#/$defs/natural"),
            "maximum_fanout_objects": ref("#/$defs/natural"),
        }
    ),
}
work_defs["step"]["required"].remove("quantity_mode")
work_defs["step"]["allOf"] = [{
    "if": {"properties": {"kind": {"enum": ["OPERATION", "FANOUT_EXPAND"]}}, "required": ["kind"]},
    "then": {"properties": {"quantity_mode": {"enum": ["BOUNDED", "NONE"]}}, "required": ["quantity_mode"]},
}]
work_defs["definition"] = obj(
    {
        "schema": {"const": VERSION + "work-class-definition"},
        "specification_pin": ref("#/$defs/digest"),
        "id": ref("#/$defs/id"),
        "revision": ref("#/$defs/id"),
        "profile": ref("#/$defs/profile"),
        "root": ref("#/$defs/id"),
        "participants": arr(ref("#/$defs/participant"), 1, 256),
        "objects": arr(ref("#/$defs/objectDeclaration"), 0, 256),
        "types": arr(ref("#/$defs/type"), 1, 64),
        "steps": arr(ref("#/$defs/step"), 1, 256),
        "relationships": arr(ref("#/$defs/relationship"), 0, 1024),
        "choices": arr(ref("#/$defs/choice"), 0, 64),
        "occurrence_limits": arr(ref("#/$defs/occurrenceLimit"), 0, 256),
        "loops": arr(ref("#/$defs/loop"), 0, 64),
        "deadlines": arr(ref("#/$defs/deadline"), 0, 256),
        "parallel_blocks": arr(ref("#/$defs/parallelBlock"), 0, 64),
        "fanouts": arr(ref("#/$defs/fanout"), 0, 64),
        "shared_budgets": arr(ref("#/$defs/id"), 0, 64, True),
        "limits": ref("#/$defs/limits"),
        "source": ref("#/$defs/source"),
    }
)
extend_work(work_defs)
write(
    "work-class.schema.json",
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "work-class.schema.json",
        "$comment": "DRAFT_NOT_ADOPTED; APPARATUS_ONLY. Shape admission does not establish authority or host assurance.",
        "$defs": work_defs,
        "$ref": "#/$defs/definition",
    },
)


life_defs: dict[str, dict] = {
    "id": ID,
    "digest": DIGEST,
    "natural": NATURAL,
    "instant": INSTANT,
    "profile": PROFILE,
    "runtimeRole": RUNTIME_ROLE,
    "typedValue": typed_value,
    "field": field_value,
    "loopSegment": obj(
        {
            "kind": {"const": "LOOP"},
            "construct_id": ref("#/$defs/id"),
            "pass": ref("#/$defs/natural"),
            "branch_id": {"type": "null"},
            "object_key": {"type": "null"},
        }
    ),
    "branchSegment": obj(
        {
            "kind": {"const": "BRANCH"},
            "construct_id": ref("#/$defs/id"),
            "pass": ref("#/$defs/natural"),
            "branch_id": ref("#/$defs/id"),
            "object_key": {"type": "null"},
        }
    ),
    "fanoutSegment": obj(
        {
            "kind": {"const": "FANOUT"},
            "construct_id": ref("#/$defs/id"),
            "pass": ref("#/$defs/natural"),
            "branch_id": {"type": "null"},
            "object_key": ref("#/$defs/typedValue"),
        }
    ),
    "enclosingSegment": {
        "oneOf": [
            ref("#/$defs/loopSegment"),
            ref("#/$defs/branchSegment"),
            ref("#/$defs/fanoutSegment"),
        ]
    },
    "occurrence": obj(
        {
            "occurrence_id": ref("#/$defs/digest"),
            "specification_pin": ref("#/$defs/digest"),
            "work_class_digest": ref("#/$defs/digest"),
            "instance_id": ref("#/$defs/id"),
            "step_id": ref("#/$defs/id"),
            "ordinal": ref("#/$defs/natural"),
            "predecessor_occurrence_ids": arr(ref("#/$defs/digest"), 0, 4096, True),
            "enclosing": arr(ref("#/$defs/enclosingSegment"), 0, 64),
            "object_key": nullable(ref("#/$defs/typedValue")),
        }
    ),
    "deploymentAuthorization": obj(
        {
            "schema": {"const": VERSION + "deployment-authorization"},
            "authorization_id": ref("#/$defs/id"),
            "specification_pin": ref("#/$defs/digest"),
            "work_class_digest": ref("#/$defs/digest"),
            "profile": ref("#/$defs/profile"),
            "role": ref("#/$defs/runtimeRole"),
            "instance_id": ref("#/$defs/id"),
            "organization_id": ref("#/$defs/id"),
            "status": {"const": "AUTHORIZED"},
            "authorization_evidence_digest": ref("#/$defs/digest"),
            "correspondence_evidence_digest": ref("#/$defs/digest"),
            "source_confirmation_evidence_digest": ref("#/$defs/digest"),
            "policy_decision_evidence_digest": ref("#/$defs/digest"),
            "authorized_at": ref("#/$defs/instant"),
            "expires_at": nullable(ref("#/$defs/instant")),
        }
    ),
    "clockAvailable": obj(
        {
            "source": ref("#/$defs/id"),
            "revision": ref("#/$defs/natural"),
            "status": {"const": "AVAILABLE"},
            "observed_time": ref("#/$defs/instant"),
            "evidence_digest": ref("#/$defs/digest"),
        }
    ),
    "clockUnavailable": obj(
        {
            "source": ref("#/$defs/id"),
            "revision": ref("#/$defs/natural"),
            "status": {"enum": ["UNAVAILABLE", "CONFLICTING"]},
            "observed_time": {"type": "null"},
            "evidence_digest": ref("#/$defs/digest"),
        }
    ),
    "clock": {"oneOf": [ref("#/$defs/clockAvailable"), ref("#/$defs/clockUnavailable")]},
    "budgetInput": obj(
        {
            "registry_digest": ref("#/$defs/digest"),
            "affected_anchors": arr(ref("#/$defs/id"), 0, 64, True),
            "expected_revision": ref("#/$defs/natural"),
            "request": ref(BASE + "reservation.schema.json#/$defs/input"),
        }
    ),
    "executor": obj(
        {
            "participant_id": ref("#/$defs/id"),
            "role": ref("#/$defs/id"),
            "binding_digest": ref("#/$defs/digest"),
        }
    ),
    "nativeRequest": obj(
        {
            "interface": ref("#/$defs/id"),
            "operation": ref("#/$defs/id"),
            "fields": arr(ref("#/$defs/field"), 0, 64),
        }
    ),
    "propose": obj(
        {
            "schema": {"const": VERSION + "runtime-event"},
            "event_id": ref("#/$defs/id"),
            "kind": {"const": "PROPOSE"},
            "instance_id": ref("#/$defs/id"),
            "expected_state_revision": ref("#/$defs/natural"),
            "expected_state_digest": ref("#/$defs/digest"),
            "occurrence": ref("#/$defs/occurrence"),
            "native_request": ref("#/$defs/nativeRequest"),
            "executor": ref("#/$defs/executor"),
            "credential_ids": arr(ref("#/$defs/id"), 0, 64, True),
            "authority_input": ref(BASE + "authority.schema.json#/$defs/input"),
            "budget_inputs": arr(ref("#/$defs/budgetInput"), 0, 1),
            "clock_revision": nullable(ref("#/$defs/natural")),
            "observation_digests": arr(ref("#/$defs/digest"), 0, 256, True),
        }
    ),
    "connector": obj(
        {"id": ref("#/$defs/id"), "version": ref("#/$defs/id"), "binding_digest": ref("#/$defs/digest")}
    ),
    "authorizationFence": obj(
        {
            "provider": ref("#/$defs/id"),
            "source": ref("#/$defs/id"),
            "approval_id": ref("#/$defs/id"),
            "scope_digest": ref("#/$defs/digest"),
            "approver_role": ref("#/$defs/id"),
            "signed_at": ref("#/$defs/instant"),
            "provider_revision": ref("#/$defs/id"),
            "checked_at": ref("#/$defs/instant"),
            "status": {"enum": ["EFFECTIVE", "WITHDRAWN", "EXPIRED", "MISMATCHED"]},
        }
    ),
    "authorizationRecord": obj(
        {
            "authorization_digest": ref("#/$defs/digest"),
            "event_id": ref("#/$defs/id"),
            "event_digest": ref("#/$defs/digest"),
            "permit_digest": ref("#/$defs/digest"),
            "native_request": ref("#/$defs/nativeRequest"),
            "connector": ref("#/$defs/connector"),
            "authorization_fence": ref("#/$defs/authorizationFence"),
            "observation_digests": arr(ref("#/$defs/digest"), 0, 256, True),
            "clock_revision": ref("#/$defs/natural"),
        }
    ),
    "attempt": obj(
        {
            "attempt_id": ref("#/$defs/id"),
            "status": {"enum": ["NOT_SENT", "SENT", "REJECTED", "UNKNOWN"]},
            "request_digest": ref("#/$defs/digest"),
            "attempted_at": ref("#/$defs/instant"),
        }
    ),
    "acknowledgementNone": obj(
        {
            "status": {"const": "NONE"},
            "reference": {"type": "null"},
            "observed_at": {"type": "null"},
        }
    ),
    "acknowledgementRecorded": obj(
        {
            "status": {"enum": ["ACCEPTED", "REJECTED", "UNKNOWN"]},
            "reference": ref("#/$defs/id"),
            "observed_at": ref("#/$defs/instant"),
        }
    ),
    "acknowledgement": {"oneOf": [ref("#/$defs/acknowledgementNone"), ref("#/$defs/acknowledgementRecorded")]},
    "dispatchObserved": obj(
        {
            "schema": {"const": VERSION + "runtime-event"},
            "event_id": ref("#/$defs/id"),
            "kind": {"const": "DISPATCH_OBSERVED"},
            "instance_id": ref("#/$defs/id"),
            "expected_state_revision": ref("#/$defs/natural"),
            "expected_state_digest": ref("#/$defs/digest"),
            "permit": ref("#/$defs/permit"),
            "native_request": ref("#/$defs/nativeRequest"),
            "connector": ref("#/$defs/connector"),
            "authorization_digest": ref("#/$defs/digest"),
            "attempt": ref("#/$defs/attempt"),
            "acknowledgement": ref("#/$defs/acknowledgement"),
            "clock_revision": ref("#/$defs/natural"),
        },
        required=[
            "schema", "event_id", "kind", "instance_id", "expected_state_revision",
            "expected_state_digest", "permit", "native_request", "connector", "attempt",
            "acknowledgement", "clock_revision",
        ],
    ),
    "authorizeDispatch": obj(
        {
            "schema": {"const": VERSION + "runtime-event"},
            "event_id": ref("#/$defs/id"),
            "kind": {"const": "AUTHORIZE_DISPATCH"},
            "instance_id": ref("#/$defs/id"),
            "expected_state_revision": ref("#/$defs/natural"),
            "expected_state_digest": ref("#/$defs/digest"),
            "permit": ref("#/$defs/permit"),
            "native_request": ref("#/$defs/nativeRequest"),
            "connector": ref("#/$defs/connector"),
            "authorization_fence": ref("#/$defs/authorizationFence"),
            "observation_digests": arr(ref("#/$defs/digest"), 0, 256, True),
            "clock_revision": ref("#/$defs/natural"),
        }
    ),
        "nativeEvidence": obj(
        {
            "evidence_id": ref("#/$defs/id"),
            "native_operation_id": ref("#/$defs/id"),
            "provider": ref("#/$defs/id"),
            "source": ref("#/$defs/id"),
            "record_type": ref("#/$defs/id"),
            "record_digest": ref("#/$defs/digest"),
            "evidence_ref": ref("#/$defs/id"),
            "attributed_request": ref(BASE + "reservation.schema.json#/$defs/nativeRequest"),
            "native_request_digest": ref("#/$defs/digest"),
            "status": {"enum": ["EFFECT_ESTABLISHED", "OUTCOME_UNKNOWN", "NO_EFFECT_ESTABLISHED"]},
            "actual_fields": arr(ref("#/$defs/field"), 0, 66),
            "collections": arr(ref("#/$defs/nativeCollection"), 0, 64),
            "event_time": nullable(ref("#/$defs/instant")),
            "observed_at": ref("#/$defs/instant"),
            "rules_out_past_and_future_effects": {"type": "boolean"},
        }
    ),
    "nativeCollection": obj(
        {
            "name": ref("#/$defs/id"),
            "element_type_ref": ref("#/$defs/id"),
            "values": arr(ref("#/$defs/typedValue"), 0, 1024),
        }
    ),
    "governedEffectObserved": obj(
        {
            "schema": {"const": VERSION + "runtime-event"},
            "event_id": ref("#/$defs/id"),
            "kind": {"const": "EFFECT_OBSERVED"},
            "instance_id": ref("#/$defs/id"),
            "expected_state_revision": ref("#/$defs/natural"),
            "expected_state_digest": ref("#/$defs/digest"),
            "permit": ref("#/$defs/permit"),
            "dispatch_digest": ref("#/$defs/digest"),
            "native_evidence": ref("#/$defs/nativeEvidence"),
            "completion_authorization": nullable(
                ref(BASE + "evidence.schema.json#/$defs/organizationalAuthorization")
            ),
            "budget_inputs": arr(ref("#/$defs/budgetInput"), 0, 1),
            "clock_revision": nullable(ref("#/$defs/natural")),
            "activation_clocks": arr(ref("#/$defs/clockAvailable"), 0, 256),
        }
    ),
    "foreignEffectObserved": obj(
        {
            "schema": {"const": VERSION + "runtime-event"},
            "event_id": ref("#/$defs/id"),
            "kind": {"const": "EFFECT_OBSERVED"},
            "instance_id": ref("#/$defs/id"),
            "expected_state_revision": ref("#/$defs/natural"),
            "expected_state_digest": ref("#/$defs/digest"),
            "permit": {"type": "null"},
            "dispatch_digest": {"type": "null"},
            "native_evidence": ref("#/$defs/nativeEvidence"),
            "completion_authorization": {"type": "null"},
            "reservation_id": nullable(ref("#/$defs/id")),
            "affected_budget_anchors": arr(ref("#/$defs/id"), 0, 64, True),
            "budget_inputs": arr(ref("#/$defs/budgetInput"), 0, 1),
            "clock_revision": nullable(ref("#/$defs/natural")),
            "activation_clocks": arr(ref("#/$defs/clockAvailable"), 0, 256),
        }
    ),
    "effectObserved": {"oneOf": [ref("#/$defs/governedEffectObserved"), ref("#/$defs/foreignEffectObserved")]},
    "clockEvent": obj(
        {
            "schema": {"const": VERSION + "runtime-event"},
            "event_id": ref("#/$defs/id"),
            "kind": {"const": "CLOCK"},
            "instance_id": ref("#/$defs/id"),
            "expected_state_revision": ref("#/$defs/natural"),
            "expected_state_digest": ref("#/$defs/digest"),
            "clock": ref("#/$defs/clock"),
            "activation_clocks": arr(ref("#/$defs/clockAvailable"), 0, 256),
        }
    ),
}
life_defs["event"] = {
    "oneOf": [ref("#/$defs/propose"), ref("#/$defs/authorizeDispatch"), ref("#/$defs/dispatchObserved"), ref("#/$defs/effectObserved"), ref("#/$defs/clockEvent")]
}
obligation_common = {
    "obligation_id": ref("#/$defs/digest"),
    "kind": {"enum": ["PARALLEL_BRANCH", "FANOUT_OBJECT"]},
    "construct_id": ref("#/$defs/id"),
    "pass": ref("#/$defs/natural"),
    "source_occurrence_ids": arr(ref("#/$defs/digest"), 1, 4096, True),
    "branch_id": nullable(ref("#/$defs/id")),
    "object_key": nullable(ref("#/$defs/typedValue")),
    "join_step_id": ref("#/$defs/id"),
    "creation_event_digest": ref("#/$defs/digest"),
}
life_defs.update(
    {
        "activeOccurrence": obj(
            {
                "occurrence": ref("#/$defs/occurrence"),
                "activation_event_digest": ref("#/$defs/digest"),
                "status": {"enum": ["ACTIVE", "PERMITTED", "DISPATCHED", "OUTCOME_UNKNOWN", "BLOCKED_DISPUTE"]},
                "deadline_ids": arr(ref("#/$defs/id"), 0, 1, True),
            }
        ),
        "completedOccurrence": obj(
            {
                "occurrence": ref("#/$defs/occurrence"),
                "disposition": {"enum": ["SUCCEEDED", "FAILED", "NO_EFFECT", "EXPIRED"]},
                "evidence_digest": nullable(ref("#/$defs/digest")),
                "occurred_at": ref("#/$defs/instant"),
                "route_label": nullable(ref("#/$defs/typedValue")),
                "selected_relationship_digest": nullable(ref("#/$defs/digest")),
                "late": {"type": "boolean"},
            }
        ),
        "stepCounter": obj(
            {
                "step_id": ref("#/$defs/id"),
                "activations": ref("#/$defs/natural"),
                "actuations": ref("#/$defs/natural"),
            }
        ),
        "childPass": obj(
            {
                "kind": {"enum": ["PARALLEL", "FANOUT"]},
                "construct_id": ref("#/$defs/id"),
                "pass": ref("#/$defs/natural"),
                "outer_enclosing": arr(ref("#/$defs/enclosingSegment"), 0, 63),
                "obligation_ids": arr(ref("#/$defs/digest"), 1, 1024, True),
            }
        ),
        "obligationCompletionDirect": obj(
            {
                "kind": {"const": "DIRECT_EVENT"},
                "event_digest": ref("#/$defs/digest"),
                "occurrence_id": ref("#/$defs/digest"),
                "operation": ref("#/$defs/id"),
                "evidence_digest": ref("#/$defs/digest"),
            }
        ),
        "obligationCompletionChild": obj(
            {
                "kind": {"const": "CHILD_PASS"},
                "event_digest": ref("#/$defs/digest"),
                "child_pass": ref("#/$defs/childPass"),
            }
        ),
        "obligationCompletion": {
            "oneOf": [
                ref("#/$defs/obligationCompletionDirect"),
                ref("#/$defs/obligationCompletionChild"),
            ]
        },
        "obligationExpecting": obj(
            obligation_common
            | {
                "status": {"enum": ["OPEN", "BLOCKED"]},
                "expected_occurrence_id": ref("#/$defs/digest"),
                "required_operation": ref("#/$defs/id"),
                "waiting_on": {"type": "null"},
                "completion_basis": {"type": "null"},
            }
        ),
        "obligationWaiting": obj(
            obligation_common
            | {
                "status": {"const": "WAITING"},
                "expected_occurrence_id": {"type": "null"},
                "required_operation": {"type": "null"},
                "waiting_on": ref("#/$defs/childPass"),
                "completion_basis": {"type": "null"},
            }
        ),
        "obligationTerminal": obj(
            obligation_common
            | {
                "status": {"enum": ["DISCHARGED", "JOINED"]},
                "expected_occurrence_id": {"type": "null"},
                "required_operation": {"type": "null"},
                "waiting_on": {"type": "null"},
                "completion_basis": ref("#/$defs/obligationCompletion"),
            }
        ),
        "obligationDisputedCompletion": obj(
            obligation_common
            | {
                "status": {"const": "DISPUTED"},
                "expected_occurrence_id": {"type": "null"},
                "required_operation": {"type": "null"},
                "waiting_on": {"type": "null"},
                "completion_basis": ref("#/$defs/obligationCompletion"),
            }
        ),
        "obligationDisputedWaiting": obj(
            obligation_common
            | {
                "status": {"const": "DISPUTED"},
                "expected_occurrence_id": {"type": "null"},
                "required_operation": {"type": "null"},
                "waiting_on": ref("#/$defs/childPass"),
                "completion_basis": {"type": "null"},
            }
        ),
        "obligation": {
            "oneOf": [
                ref("#/$defs/obligationExpecting"),
                ref("#/$defs/obligationWaiting"),
                ref("#/$defs/obligationTerminal"),
                ref("#/$defs/obligationDisputedCompletion"),
                ref("#/$defs/obligationDisputedWaiting"),
            ]
        },
        "proposalRecord": obj(
            {
                "event_id": ref("#/$defs/id"),
                "event_digest": ref("#/$defs/digest"),
                "proposal_digest": ref("#/$defs/digest"),
                "occurrence_id": ref("#/$defs/digest"),
                "disposition": {"enum": ["WITHHELD", "PERMITTED"]},
                "permit_digest": nullable(ref("#/$defs/digest")),
                "authority_result_digest": nullable(ref("#/$defs/digest")),
                "reservation_receipt_digests": arr(ref("#/$defs/digest"), 0, 1, True),
                "prior_permit_digest": nullable(ref("#/$defs/digest")),
            }
        ),
        "authorityActBasis": obj(
            {
                "act_digest": ref("#/$defs/digest"),
                "act": ref(BASE + "authority.schema.json#/$defs/act"),
            }
        ),
        "priorEffectBasis": obj(
            {
                "binding_id": ref("#/$defs/id"),
                "source_occurrence_id": ref("#/$defs/digest"),
                "source_permit_digest": ref("#/$defs/digest"),
                "source_native_evidence_digest": ref("#/$defs/digest"),
                "source_field": ref("#/$defs/id"),
                "target_field": ref("#/$defs/id"),
                "value": ref("#/$defs/typedValue"),
            }
        ),
        "actorSeparationBasis": obj(
            {
                "requirement_id": ref("#/$defs/id"),
                "relation": {"const": "DISTINCT_ACTOR"},
                "prior_occurrence_id": ref("#/$defs/digest"),
                "current_occurrence_id": ref("#/$defs/digest"),
                "prior_act": ref("#/$defs/authorityActBasis"),
                "current_act": ref("#/$defs/authorityActBasis"),
            }
        ),
        "permit": obj(
            {
                "schema": {"const": VERSION + "permit"},
                "permit_id": ref("#/$defs/digest"),
                "instance_id": ref("#/$defs/id"),
                "work_class_digest": ref("#/$defs/digest"),
                "profile": ref("#/$defs/profile"),
                "role": ref("#/$defs/runtimeRole"),
                "occurrence": ref("#/$defs/occurrence"),
                "proposal_digest": ref("#/$defs/digest"),
                "native_request": ref("#/$defs/nativeRequest"),
                "executor": ref("#/$defs/executor"),
                "credential_ids": arr(ref("#/$defs/id"), 0, 64, True),
                "authority_result": ref(BASE + "authority.schema.json#/$defs/result"),
                "authority_result_digest": ref("#/$defs/digest"),
                "authority_evidence_digest": ref("#/$defs/digest"),
                "authority_act_bases": arr(ref("#/$defs/authorityActBasis"), 1, 1024),
                "prior_effect_bases": arr(ref("#/$defs/priorEffectBasis"), 0, 64),
                "separation_bases": arr(ref("#/$defs/actorSeparationBasis"), 0, 64),
                "observation_digests": arr(ref("#/$defs/digest"), 0, 256, True),
                "supersedes_permit_digest": nullable(ref("#/$defs/digest")),
                "budget_revisions": arr(
                    obj(
                        {
                            "registry_digest": ref("#/$defs/digest"),
                            "affected_anchors": arr(ref("#/$defs/id"), 0, 64, True),
                            "revision": ref("#/$defs/natural"),
                            "reservation_id": ref("#/$defs/id"),
                            "receipt_digest": ref("#/$defs/digest"),
                        }
                    ),
                    0,
                    1,
                ),
                "clock_source": ref("#/$defs/id"),
                "clock_revision": ref("#/$defs/natural"),
                "expires_at": ref("#/$defs/instant"),
            }
        ),
        "dispatchRecord": obj(
            {
                "dispatch_digest": ref("#/$defs/digest"),
                "dispatch_attempt_digest": ref("#/$defs/digest"),
                "event_id": ref("#/$defs/id"),
                "event_digest": ref("#/$defs/digest"),
                "permit_digest": ref("#/$defs/digest"),
                "native_request": ref("#/$defs/nativeRequest"),
                "connector": ref("#/$defs/connector"),
                "authorization_digest": ref("#/$defs/digest"),
                "attempt": ref("#/$defs/attempt"),
                "acknowledgement": ref("#/$defs/acknowledgement"),
                "clock_revision": ref("#/$defs/natural"),
            },
            required=[
                "dispatch_digest", "dispatch_attempt_digest", "event_id", "event_digest",
                "permit_digest", "native_request", "connector", "attempt", "acknowledgement",
                "clock_revision",
            ],
        ),
        "governedOutcomeRecord": obj(
            {
                "kind": {"const": "GOVERNED"},
                "outcome_digest": ref("#/$defs/digest"),
                "event_id": ref("#/$defs/id"),
                "event_digest": ref("#/$defs/digest"),
                "permit_digest": ref("#/$defs/digest"),
                "dispatch_digest": ref("#/$defs/digest"),
                "dispatch_attempt_digest": ref("#/$defs/digest"),
                "native_evidence": ref("#/$defs/nativeEvidence"),
                "classification": {"enum": ["MATCHED", "FAILED", "UNKNOWN", "NO_EFFECT_ESTABLISHED", "UNEXPECTED", "CONFLICTING", "LATE_MATCHED", "LATE_AFTER_RELEASE", "DUPLICATE"]},
                "reservation_receipt_digests": arr(ref("#/$defs/digest"), 0, 1, True),
                "conflicts_with_evidence_ids": arr(ref("#/$defs/id"), 0, None, True),
                "disputed": {"type": "boolean"},
            }
        ),
        "foreignOutcomeRecord": obj(
            {
                "kind": {"const": "FOREIGN"},
                "outcome_digest": ref("#/$defs/digest"),
                "event_id": ref("#/$defs/id"),
                "event_digest": ref("#/$defs/digest"),
                "permit_digest": {"type": "null"},
                "dispatch_digest": {"type": "null"},
                "dispatch_attempt_digest": {"type": "null"},
                "native_evidence": ref("#/$defs/nativeEvidence"),
                "classification": {"enum": ["FOREIGN", "DUPLICATE", "CONFLICTING"]},
                "affected_budget_anchors": arr(ref("#/$defs/id"), 0, 64, True),
                "reservation_receipt_digests": arr(ref("#/$defs/digest"), 0, 1, True),
                "conflicts_with_evidence_ids": arr(ref("#/$defs/id"), 0, None, True),
                "disputed": {"const": True},
            }
        ),
        "outcomeRecord": {"oneOf": [ref("#/$defs/governedOutcomeRecord"), ref("#/$defs/foreignOutcomeRecord")]},
        "deadlineState": obj(
            {
                "deadline_id": ref("#/$defs/id"),
                "occurrence_id": ref("#/$defs/digest"),
                "source": ref("#/$defs/id"),
                "activation_revision": ref("#/$defs/natural"),
                "activation_digest": ref("#/$defs/digest"),
                "trigger_digest": ref("#/$defs/digest"),
                "activation_clock_revision": ref("#/$defs/natural"),
            "activation_instant": ref("#/$defs/instant"),
            "activation_clock_evidence_digest": ref("#/$defs/digest"),
            "due": ref("#/$defs/instant"),
                "boundary": {"enum": ["AT_OR_AFTER", "AFTER"]},
                "status": {"enum": ["PENDING", "DISCHARGED", "EXPIRED"]},
                "expiry_event_digest": nullable(ref("#/$defs/digest")),
            }
        ),
        "fanoutPass": obj(
            {
                "fanout_id": ref("#/$defs/id"),
                "pass": ref("#/$defs/natural"),
                "expand_occurrence_id": ref("#/$defs/digest"),
                "object_keys": arr(ref("#/$defs/typedValue"), 0, 1024),
                "obligation_ids": arr(ref("#/$defs/digest"), 0, 1024, True),
                "joined": {"type": "boolean"},
            }
        ),
        "decisionDetailAuthority": obj(
            {
                "kind": {"const": "AUTHORITY"},
                "authority_result_digest": ref("#/$defs/digest"),
                "code": ref("#/$defs/id"),
                "reasons": arr(ref("#/$defs/id"), 0, 64, True),
                "failed_checks": arr(ref(BASE + "authority.schema.json#/$defs/failedCheck"), 0, None, True),
            }
        ),
        "decisionDetailSeparation": obj(
            {
                "kind": {"const": "SEPARATION"},
                "authority_result": ref(BASE + "authority.schema.json#/$defs/result"),
                "basis": ref("#/$defs/actorSeparationBasis"),
            }
        ),
        "decisionDetailBudget": obj(
            {
                "kind": {"const": "BUDGET"},
                "registry_digest": ref("#/$defs/digest"),
                "receipt_digest": ref("#/$defs/digest"),
                "reasons": arr(ref("#/$defs/id"), 0, 64, True),
            }
        ),
        "decisionDetailDispatch": obj(
            {
                "kind": {"const": "DISPATCH"},
                "attempt_id": ref("#/$defs/id"),
                "reasons": arr(
                    {
                        "enum": [
                        "NATIVE_ARGUMENT_MISMATCH",
                        "NATIVE_NOT_SENT",
                        "NATIVE_DISPATCH_REJECTED",
                        "ACKNOWLEDGEMENT_REJECTED",
                        "DISPATCH_STATUS_UNKNOWN",
                        "DISPATCH_EVIDENCE_CONFLICT",
                        "LATE_OR_PROHIBITED_DISPATCH",
                        "PERMIT_EXPIRED",
                        "PERMIT_SUPERSEDED",
                        ]
                    },
                    0,
                    9,
                    True,
                ),
            }
        ),
        "decisionDetailAuthorization": obj(
            {
                "kind": {"const": "AUTHORIZATION"},
                "authorization_digest": ref("#/$defs/digest"),
                "permit_digest": ref("#/$defs/digest"),
                "approval_id": ref("#/$defs/id"),
                "provider_revision": ref("#/$defs/id"),
                "checked_at": ref("#/$defs/instant"),
            }
        ),
        "decisionDetailEffect": obj(
            {
                "kind": {"const": "EFFECT"},
                "classification": {
                    "enum": [
                        "MATCHED",
                        "FAILED",
                        "UNKNOWN",
                        "NO_EFFECT_ESTABLISHED",
                        "UNEXPECTED",
                        "CONFLICTING",
                        "FOREIGN",
                        "LATE_MATCHED",
                        "LATE_AFTER_RELEASE",
                        "DUPLICATE",
                    ]
                },
                "evidence_id": ref("#/$defs/id"),
            }
        ),
        "decisionDetailRoute": obj(
            {
                "kind": {"const": "ROUTE"},
                "relationship_digests": arr(ref("#/$defs/digest"), 0, 1024, True),
                "construct_ids": arr(ref("#/$defs/id"), 0, 128, True),
            }
        ),
        "decisionDetailLabel": obj(
            {
                "kind": {"const": "LABEL"},
                "step_id": ref("#/$defs/id"),
                "observed_value": nullable(ref("#/$defs/typedValue")),
            }
        ),
        "decisionDetailLimit": obj(
            {
                "kind": {"const": "LIMIT"},
                "limit_kind": {
                    "enum": [
                        "ACTIVATIONS",
                        "ACTUATIONS",
                        "STEP_OCCURRENCES",
                        "LOOP_PASSES",
                        "ACTIVE_OBLIGATIONS",
                        "FANOUT_OBJECTS",
                    ]
                },
                "limit": ref("#/$defs/natural"),
                "current": ref("#/$defs/natural"),
                "step_id": nullable(ref("#/$defs/id")),
                "relationship_digest": nullable(ref("#/$defs/digest")),
            }
        ),
        "decisionDetailDeadline": obj(
            {
                "kind": {"const": "DEADLINE"},
                "deadline_ids": arr(ref("#/$defs/id"), 1, 256, True),
                "reasons": arr(
                    {"enum": ["ACTIVATION_CLOCK_UNAVAILABLE", "DEADLINE_ALREADY_DUE", "DEADLINE_TIME_OVERFLOW", "EXPIRY_STOP"]},
                    0,
                    4,
                    True,
                ),
            }
        ),
        "decisionDetailClock": obj(
            {
                "kind": {"const": "CLOCK"},
                "source": ref("#/$defs/id"),
                "revision": ref("#/$defs/natural"),
                "status": {"enum": ["AVAILABLE", "UNAVAILABLE", "CONFLICTING"]},
            }
        ),
        "decisionDetail": {
            "oneOf": [
                ref("#/$defs/decisionDetailAuthority"),
                ref("#/$defs/decisionDetailSeparation"),
                ref("#/$defs/decisionDetailBudget"),
                ref("#/$defs/decisionDetailDispatch"),
                ref("#/$defs/decisionDetailAuthorization"),
                ref("#/$defs/decisionDetailEffect"),
                ref("#/$defs/decisionDetailClock"),
                ref("#/$defs/decisionDetailRoute"),
                ref("#/$defs/decisionDetailLabel"),
                ref("#/$defs/decisionDetailLimit"),
                ref("#/$defs/decisionDetailDeadline"),
            ]
        },
        "decisionReceipt": obj(
            {
                "schema": {"const": VERSION + "decision-receipt"},
                "decision_id": ref("#/$defs/digest"),
                "instance_id": ref("#/$defs/id"),
                "sequence": ref("#/$defs/natural"),
                "event_id": ref("#/$defs/id"),
                "event_digest": ref("#/$defs/digest"),
                "event_kind": {"enum": ["PROPOSE", "AUTHORIZE_DISPATCH", "DISPATCH_OBSERVED", "EFFECT_OBSERVED", "CLOCK"]},
                "disposition": {"enum": ["WITHHELD", "PERMITTED", "AUTHORIZED", "DISPATCH_RECORDED", "DISPATCH_REFUSED", "ACKNOWLEDGED", "OUTCOME_RETAINED", "COMPLETED", "FAILED", "EXPIRED", "STOPPED", "DISPUTED", "CLOCK_RECORDED"]},
                "reason_codes": arr(ref("#/$defs/id"), 0, 64, True),
                "details": arr(ref("#/$defs/decisionDetail"), 0, 10, True),
                "permit_digest": nullable(ref("#/$defs/digest")),
                "authority_result_digest": nullable(ref("#/$defs/digest")),
                "reservation_receipt_digests": arr(ref("#/$defs/digest"), 0, 1, True),
                "state_before_digest": ref("#/$defs/digest"),
                "state_after_core_digest": ref("#/$defs/digest"),
            }
        ),
        "replayRecord": obj(
            {
                "event_id": ref("#/$defs/id"),
                "event_digest": ref("#/$defs/digest"),
                "decision": ref("#/$defs/decisionReceipt"),
                "decision_receipt_digest": ref("#/$defs/digest"),
                "permit": nullable(ref("#/$defs/permit")),
                "budget_results": arr(ref("#/$defs/budgetTransitionResult"), 0, 1),
                "transition_state_digest": ref("#/$defs/digest"),
                "transaction_digest": ref("#/$defs/digest"),
            }
        ),
    }
)
life_defs["state"] = obj(
    {
        "schema": {"const": VERSION + "work-state"},
        "specification_pin": ref("#/$defs/digest"),
        "work_class_digest": ref("#/$defs/digest"),
        "profile": ref("#/$defs/profile"),
        "role": ref("#/$defs/runtimeRole"),
        "instance_id": ref("#/$defs/id"),
        "deployment_authorization": ref("#/$defs/deploymentAuthorization"),
        "deployment_authorization_subject_digest": ref("#/$defs/digest"),
        "deployment_authorization_digest": ref("#/$defs/digest"),
        "deployment_authorization_evidence": ref(BASE + "evidence.schema.json#/$defs/organizationalAuthorization"),
        "deployment_authorization_evidence_digest": ref("#/$defs/digest"),
        "deployment_correspondence_evidence": ref(BASE + "evidence.schema.json#/$defs/correspondence"),
        "deployment_correspondence_evidence_digest": ref("#/$defs/digest"),
        "deployment_source_confirmation_evidence": ref(BASE + "evidence.schema.json#/$defs/sourceConfirmation"),
        "deployment_source_confirmation_evidence_digest": ref("#/$defs/digest"),
        "deployment_policy_decision_evidence": ref(BASE + "evidence.schema.json#/$defs/policyDecision"),
        "deployment_policy_decision_evidence_digest": ref("#/$defs/digest"),
        "deployment_authorization_clock": ref("#/$defs/clockAvailable"),
        "deployment_organization_id": ref("#/$defs/id"),
        "revision": ref("#/$defs/natural"),
        "status": {"enum": ["ACTIVE", "COMPLETE", "STOPPED"]},
        "total_activations": ref("#/$defs/natural"),
        "total_actuations": ref("#/$defs/natural"),
        "step_counters": arr(ref("#/$defs/stepCounter"), 1, 256),
        "active": arr(ref("#/$defs/activeOccurrence"), 0, 4096),
        "completed": arr(ref("#/$defs/completedOccurrence"), 0, 4096),
        "obligations": arr(ref("#/$defs/obligation"), 0, 4096),
        "proposals": arr(ref("#/$defs/proposalRecord"), 0, 4096),
        "permits": arr(ref("#/$defs/permit"), 0, 4096),
        "dispatches": arr(ref("#/$defs/dispatchRecord"), 0),
        "authorizations": arr(ref("#/$defs/authorizationRecord"), 0),
        "outcomes": arr(ref("#/$defs/outcomeRecord"), 0),
        "clocks": arr(ref("#/$defs/clock"), 0),
        "deadlines": arr(ref("#/$defs/deadlineState"), 0, 4096),
        "fanout_passes": arr(ref("#/$defs/fanoutPass"), 0, 4096),
        "receipts": arr(ref("#/$defs/decisionReceipt"), 0),
        "replays": arr(ref("#/$defs/replayRecord"), 0),
    }
)
life_defs["state"]["required"].remove("authorizations")
for declaration in life_defs.values():
    affected = declaration.get("properties", {}).get("affected_anchors")
    if affected:
        affected["minItems"] = 0
life_defs["permit"]["properties"]["budget_revisions"]["items"]["properties"]["affected_anchors"]["minItems"] = 0
life_defs["budgetTransitionResult"] = obj(
    {
        "registry_digest": ref("#/$defs/digest"),
        "affected_anchors": arr(ref("#/$defs/id"), 0, 64, True),
        "result": ref(BASE + "reservation.schema.json#/$defs/result"),
    }
)
life_defs["deployInput"] = obj(
    {
        "profile": ref("#/$defs/profile"),
        "role": ref("#/$defs/runtimeRole"),
        "specification_pin": ref("#/$defs/digest"),
        "definition": ref(BASE + "work-class.schema.json#/$defs/definition"),
        "definition_digest": ref("#/$defs/digest"),
        "instance_id": ref("#/$defs/id"),
        "deployment_authorization": ref("#/$defs/deploymentAuthorization"),
        "authorization_evidence": ref(BASE + "evidence.schema.json#/$defs/organizationalAuthorization"),
        "correspondence_evidence": ref(BASE + "evidence.schema.json#/$defs/correspondence"),
        "source_confirmation_evidence": ref(BASE + "evidence.schema.json#/$defs/sourceConfirmation"),
        "policy_decision_evidence": ref(BASE + "evidence.schema.json#/$defs/policyDecision"),
        "authorization_clock": ref("#/$defs/clockAvailable"),
        "initial_clocks": arr(ref("#/$defs/clockAvailable"), 0, 256),
    }
)
life_defs["deployResult"] = obj(
    {
        "status": {"const": "DEPLOYED"},
        "profile": ref("#/$defs/profile"),
        "role": ref("#/$defs/runtimeRole"),
        "instance_id": ref("#/$defs/id"),
        "work_class_digest": ref("#/$defs/digest"),
        "deployment_authorization_digest": ref("#/$defs/digest"),
        "state": ref("#/$defs/state"),
        "state_digest": ref("#/$defs/digest"),
    }
)
life_defs["deployRefusal"] = obj(
    {
        "status": {"const": "REFUSED"},
        "profile": ref("#/$defs/profile"),
        "role": ref("#/$defs/runtimeRole"),
        "code": {"enum": REFUSAL_CODES},
        "path": {"const": ""},
    }
)
life_defs["stepInput"] = obj(
    {
        "profile": ref("#/$defs/profile"),
        "role": ref("#/$defs/runtimeRole"),
        "specification_pin": ref("#/$defs/digest"),
        "definition": ref(BASE + "work-class.schema.json#/$defs/definition"),
        "definition_digest": ref("#/$defs/digest"),
        "state": ref("#/$defs/state"),
        "state_digest": ref("#/$defs/digest"),
        "event": ref("#/$defs/event"),
    }
)
life_defs["stepResult"] = obj(
    {
        "status": {"const": "STEP"},
        "profile": ref("#/$defs/profile"),
        "role": ref("#/$defs/runtimeRole"),
        "decision": ref("#/$defs/decisionReceipt"),
        "decision_digest": ref("#/$defs/digest"),
        "permit": nullable(ref("#/$defs/permit")),
        "budget_results": arr(ref("#/$defs/budgetTransitionResult"), 0, 1),
        "state": ref("#/$defs/state"),
        "state_digest": ref("#/$defs/digest"),
        "transition_state_digest": ref("#/$defs/digest"),
        "transaction_digest": ref("#/$defs/digest"),
        "replay": {"type": "boolean"},
    }
)
life_defs["statefulRefusal"] = obj(
    {
        "status": {"const": "REFUSED"},
        "profile": ref("#/$defs/profile"),
        "role": ref("#/$defs/runtimeRole"),
        "code": {"enum": REFUSAL_CODES},
        "path": {"const": ""},
        "state": ref("#/$defs/state"),
        "state_digest": ref("#/$defs/digest"),
        "budget_states": arr(
            obj(
                {
                    "registry_digest": ref("#/$defs/digest"),
                    "affected_anchors": arr(ref("#/$defs/id"), 0, 64, True),
                    "state": ref(BASE + "reservation.schema.json#/$defs/state"),
                    "state_digest": ref("#/$defs/digest"),
                }
            ),
            0,
            1,
        ),
    }
)
life_defs["hostBudgetDigest"] = obj(
    {
        "registry_digest": ref("#/$defs/digest"),
        "affected_anchors": arr(ref("#/$defs/id"), 0, 64, True),
        "state_digest": ref("#/$defs/digest"),
    }
)
life_defs["hostCommitSuccess"] = obj(
    {
        "status": {"const": "HOST_COMMIT"},
        "disposition": {"const": "COMMITTED"},
        "transaction_digest": ref("#/$defs/digest"),
        "state_before_digest": ref("#/$defs/digest"),
        "state_after_digest": ref("#/$defs/digest"),
        "budget_before": arr(ref("#/$defs/hostBudgetDigest"), 0, 1),
        "budget_after": arr(ref("#/$defs/hostBudgetDigest"), 0, 1),
        "dispatch_performed": {"const": False},
    }
)
life_defs["hostCommitFailure"] = obj(
    {
        "status": {"const": "HOST_COMMIT"},
        "disposition": {"const": "COMMIT_FAILED"},
        "transaction_digest": ref("#/$defs/digest"),
        "state_before_digest": ref("#/$defs/digest"),
        "authoritative_state_digest": ref("#/$defs/digest"),
        "budget_before": arr(ref("#/$defs/hostBudgetDigest"), 0, 1),
        "authoritative_budgets": arr(ref("#/$defs/hostBudgetDigest"), 0, 1),
        "failure_reference": ref("#/$defs/id"),
        "dispatch_performed": {"const": False},
    }
)
life_defs["hostCommitResult"] = {"oneOf": [ref("#/$defs/hostCommitSuccess"), ref("#/$defs/hostCommitFailure")]}
life_defs["hostDeploymentInstalled"] = obj(
    {
        "status": {"const": "HOST_DEPLOY"},
        "disposition": {"const": "INSTALLED"},
        "organization": ref("#/$defs/id"),
        "instance_id": ref("#/$defs/id"),
        "state_digest": ref("#/$defs/digest"),
        "replay": {"type": "boolean"},
        "dispatch_performed": {"const": False},
    }
)
life_defs["hostDeploymentOccupied"] = obj(
    {
        "status": {"const": "HOST_DEPLOY"},
        "disposition": {"const": "INSTANCE_OCCUPIED"},
        "organization": ref("#/$defs/id"),
        "instance_id": ref("#/$defs/id"),
        "authoritative_state_digest": ref("#/$defs/digest"),
        "proposed_state_digest": ref("#/$defs/digest"),
        "replay": {"const": False},
        "dispatch_performed": {"const": False},
    }
)
life_defs["hostDeploymentResult"] = {
    "oneOf": [ref("#/$defs/hostDeploymentInstalled"), ref("#/$defs/hostDeploymentOccupied")]
}
extend_lifecycle(life_defs)
write(
    "lifecycle.schema.json",
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "lifecycle.schema.json",
        "$comment": "DRAFT_NOT_ADOPTED; APPARATUS_ONLY. All lifecycle records are closed protocol objects.",
        "$defs": life_defs,
        "oneOf": [ref("#/$defs/deploymentAuthorization"), ref("#/$defs/event"), ref("#/$defs/state"), ref("#/$defs/permit"), ref("#/$defs/decisionReceipt"), ref("#/$defs/hostDeploymentResult"), ref("#/$defs/hostCommitResult")],
    },
)


evidence_defs: dict[str, dict] = {
    "id": ID,
    "digest": DIGEST,
    "instant": INSTANT,
    "subject": obj(
        {
            "kind": {"enum": ["SOURCE", "POLICY_DECISION", "WORK_CLASS", "AUTHORIZATION", "REVIEW", "BOUNDARY", "IMPLEMENTATION", "SUITE"]},
            "subject_id": ref("#/$defs/id"),
            "subject_digest": ref("#/$defs/digest"),
            "candidate_identity": {"const": "seampoint.work-class/1.0.0-draft.3"},
            "specification_pin": ref("#/$defs/digest"),
        }
    ),
    "sourceConfirmation": obj(
        {
            "schema": {"const": VERSION + "evidence-record"},
            "evidence_id": ref("#/$defs/id"),
            "kind": {"const": "SOURCE_CONFIRMATION"},
            "status": {"enum": ["ACCEPTED", "REJECTED", "PENDING", "DEFERRED"]},
            "subject_digest": ref("#/$defs/digest"),
            "actor_id": ref("#/$defs/id"),
            "scope_ids": arr(ref("#/$defs/id"), 1, 1024, True),
            "recorded_at": ref("#/$defs/instant"),
            "provenance_digest": ref("#/$defs/digest"),
        }
    ),
    "policyDecision": obj(
        {
            "schema": {"const": VERSION + "evidence-record"},
            "evidence_id": ref("#/$defs/id"),
            "kind": {"const": "POLICY_DECISION"},
            "status": {"enum": ["ACCEPTED", "REJECTED", "PENDING", "DEFERRED"]},
            "subject_digest": ref("#/$defs/digest"),
            "decision_maker_id": ref("#/$defs/id"),
            "decision_ids": arr(ref("#/$defs/id"), 1, 1024, True),
            "recorded_at": ref("#/$defs/instant"),
            "provenance_digest": ref("#/$defs/digest"),
        }
    ),
    "organizationalAuthorization": obj(
        {
            "schema": {"const": VERSION + "evidence-record"},
            "evidence_id": ref("#/$defs/id"),
            "kind": {"const": "ORGANIZATIONAL_AUTHORIZATION"},
            "status": {"enum": ["ACCEPTED", "REJECTED", "PENDING", "DEFERRED"]},
            "subject_digest": ref("#/$defs/digest"),
            "organization_id": ref("#/$defs/id"),
            "authorizer_id": ref("#/$defs/id"),
            "authorization_scope": arr(ref("#/$defs/id"), 1, 1024, True),
            "recorded_at": ref("#/$defs/instant"),
            "expires_at": nullable(ref("#/$defs/instant")),
            "provenance_digest": ref("#/$defs/digest"),
        }
    ),
    "review": obj(
        {
            "schema": {"const": VERSION + "evidence-record"},
            "evidence_id": ref("#/$defs/id"),
            "kind": {"const": "REVIEW"},
            "status": {"enum": ["ACCEPTED", "REJECTED", "PENDING", "DEFERRED"]},
            "subject_digest": ref("#/$defs/digest"),
            "reviewer_id": ref("#/$defs/id"),
            "paragraph_ids": arr(ref("#/$defs/id"), 0, 4096, True),
            "case_ids": arr(ref("#/$defs/id"), 0, 4096, True),
            "finding_ids": arr(ref("#/$defs/id"), 0, 4096, True),
            "recorded_at": ref("#/$defs/instant"),
            "provenance_digest": ref("#/$defs/digest"),
        }
    ),
    "correspondenceMapping": obj(
        {
            "source_obligation_id": ref("#/$defs/id"),
            "provision_paths": arr({"type": "string", "minLength": 1}, 1, 1507469, True),
        }
    ),
    "residue": obj(
        {
            "kind": {"enum": ["SOURCE_OBLIGATION", "ARTIFACT_PROVISION"]},
            "subject": {"type": "string", "minLength": 1},
            "disposition": {"enum": ["UNSUPPORTED", "EXCLUDED", "PENDING"]},
            "explanation": {"type": "string", "minLength": 1},
        }
    ),
}
evidence_defs["correspondence"] = obj(
    {
        "schema": {"const": VERSION + "evidence-record"},
        "evidence_id": ref("#/$defs/id"),
        "kind": {"const": "CORRESPONDENCE"},
        "status": {"enum": ["ACCEPTED", "REJECTED", "PENDING", "DEFERRED"]},
        "subject_digest": ref("#/$defs/digest"),
        "source_id": ref("#/$defs/id"),
        "source_revision": ref("#/$defs/id"),
        "work_class_digest": ref("#/$defs/digest"),
        "mappings": arr(ref("#/$defs/correspondenceMapping"), 0, 1024),
        "uncovered_source_obligation_ids": arr(ref("#/$defs/id"), 0, 1024, True),
        "unsupported_provision_paths": arr({"type": "string", "minLength": 1}, 0, 1507469, True),
        "residue": arr(ref("#/$defs/residue"), 0, 1508493),
        "review": ref("#/$defs/review"),
        "recorded_at": ref("#/$defs/instant"),
        "provenance_digest": ref("#/$defs/digest"),
    }
)
evidence_defs["record"] = {
    "oneOf": [ref("#/$defs/sourceConfirmation"), ref("#/$defs/policyDecision"), ref("#/$defs/organizationalAuthorization"), ref("#/$defs/review"), ref("#/$defs/correspondence")]
}
evidence_defs["basicRecord"] = {
    "oneOf": [ref("#/$defs/sourceConfirmation"), ref("#/$defs/policyDecision"), ref("#/$defs/organizationalAuthorization"), ref("#/$defs/review")]
}
evidence_defs["basicInput"] = obj(
    {
        "profile": PROFILE,
        "role": {"const": "REVIEW_EVIDENCE"},
        "specification_pin": ref("#/$defs/digest"),
        "subject": ref("#/$defs/subject"),
        "evidence": ref("#/$defs/basicRecord"),
    }
)
evidence_defs["correspondenceInput"] = obj(
    {
        "profile": PROFILE,
        "role": {"const": "REVIEW_EVIDENCE"},
        "specification_pin": ref("#/$defs/digest"),
        "subject": ref("#/$defs/subject"),
        "work_class": ref(BASE + "work-class.schema.json#/$defs/definition"),
        "work_class_digest": ref("#/$defs/digest"),
        "evidence": ref("#/$defs/correspondence"),
    }
)
evidence_defs["input"] = {"oneOf": [ref("#/$defs/basicInput"), ref("#/$defs/correspondenceInput")]}
evidence_defs["result"] = obj(
    {
        "status": {"const": "EVIDENCE_VALID"},
        "profile": PROFILE,
        "role": {"const": "REVIEW_EVIDENCE"},
        "subject_digest": ref("#/$defs/digest"),
        "evidence_digest": ref("#/$defs/digest"),
        "specification_pin": ref("#/$defs/digest"),
    }
)
evidence_defs["refusal"] = obj(
    {
        "status": {"const": "EVIDENCE_INVALID"},
        "profile": PROFILE,
        "role": {"const": "REVIEW_EVIDENCE"},
        "code": {"enum": ["BINDING_MISMATCH", "EVIDENCE_NOT_ACCEPTED", "EVIDENCE_UNAVAILABLE", "SCHEMA_INVALID"]},
        "path": {"const": ""},
        "specification_pin": ref("#/$defs/digest"),
    }
)
write(
    "evidence.schema.json",
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "evidence.schema.json",
        "$comment": "DRAFT_NOT_ADOPTED; APPARATUS_ONLY. Mechanical binding does not authenticate the people or organizations named by a record.",
        "$defs": evidence_defs,
        "oneOf": [ref("#/$defs/subject"), ref("#/$defs/record"), ref("#/$defs/input"), ref("#/$defs/result"), ref("#/$defs/refusal")],
    },
)


boundary_defs = {
    "id": ID,
    "digest": DIGEST,
    "owner": obj(
        {
            "kind": {"enum": ["POLICY_OWNER", "IDENTITY_PROVIDER", "OBSERVATION_PROVIDER", "CLOCK_PROVIDER", "HOST_OPERATOR", "CONNECTOR_OPERATOR", "DEPLOYER"]},
            "party_id": ref("#/$defs/id"),
        }
    ),
    "record": obj(
        {
            "schema": {"const": VERSION + "boundary-record"},
            "id": ref("#/$defs/id"),
            "candidate_identity": {"const": "seampoint.work-class/1.0.0-draft.3"},
            "specification_pin": ref("#/$defs/digest"),
            "paragraph_ids": arr(ref("#/$defs/id"), 1, 4096, True),
            "requirement_ids": arr(ref("#/$defs/id"), 1, 1024, True),
            "external_fact_or_capability": {"type": "string", "minLength": 1},
            "responsible_party": ref("#/$defs/owner"),
            "required_control_or_integration": {"type": "string", "minLength": 1},
            "evidence_format": {"type": "string", "minLength": 1},
            "failure_behavior": {"type": "string", "minLength": 1},
            "deployment_verification": {"type": "string", "minLength": 1},
            "establishes": {"type": "string", "minLength": 1},
            "does_not_establish": {"type": "string", "minLength": 1},
            "residual_limitation": {"type": "string", "minLength": 1},
        }
    ),
}
write(
    "boundary.schema.json",
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "boundary.schema.json",
        "$comment": "DRAFT_NOT_ADOPTED; APPARATUS_ONLY. A boundary record closes the specification of an external dependency; it does not establish the external fact.",
        "$defs": boundary_defs,
        "$ref": "#/$defs/record",
    },
)


refusal_codes = REFUSAL_CODES

protocol_defs: dict[str, dict] = {
    "digest": DIGEST,
    "profile": PROFILE,
    "runtimeRole": RUNTIME_ROLE,
    "limits": obj(
        {
            "max_definitions": {"const": "64"},
            "max_operations": {"const": "256"},
            "max_collection_members": {"const": "1024"},
            "max_numeric_digits": {"const": "128"},
            "max_expression_depth": {"const": "64"},
            "max_expression_nodes": {"const": "4096"},
        }
    ),
    "capabilitiesInput": obj({}),
    "capabilitiesResult": obj(
        {
            "status": {"const": "CAPABILITIES"},
            "protocol": {"const": PROTOCOL},
            "specification_pin": ref("#/$defs/digest"),
            "roles": arr(
                {
                    "enum": [
                        "AGGREGATE_EVALUATOR",
                        "AUTHORITY_EVALUATOR",
                        "CHOICE_LOOP_RUNTIME",
                        "DEADLINE_RUNTIME",
                        "LINEAR_WORK_RUNTIME",
                        "PARALLEL_FANOUT_RUNTIME",
                        "REFERENCE_SINGLE_PROCESS_CONTENTION",
                        "REVIEW_EVIDENCE",
                        "RESERVATION_TRANSITIONS",
                    ]
                },
                0,
                10,
                True,
            ),
            "operations": arr({"enum": ["aggregate-step", "capabilities", "check-evidence", "deploy", "evaluate", "readback", "step", "validate"]}, 0, 8, True),
            "tzdb": nullable({"const": "2025a"}),
            "limits": ref("#/$defs/limits"),
        }
    ),
    "evaluateInput": {
        "oneOf": [
            obj({"kind": {"const": "AGGREGATE"}, "request": ref(BASE + "aggregate.schema.json#/$defs/input")}),
            obj({"kind": {"const": "AUTHORITY"}, "request": ref(BASE + "authority.schema.json#/$defs/input")}),
        ]
    },
    "artifactInput": obj(
        {
            "kind": {"enum": ["AGGREGATE_DEFINITION", "AUTHORITY_DEFINITION", "WORK_CLASS", "BOUNDARY_RECORD", "EVIDENCE_RECORD"]},
            "specification_pin": ref("#/$defs/digest"),
            "artifact_bytes_base64": {"type": "string"},
        }
    ),
    "validateResult": obj({"status": {"const": "ACCEPTED"}, "digest": ref("#/$defs/digest")}),
    "readbackLine": obj({"path": {"type": "string"}, "value": {"type": "string"}}),
    "readbackResult": obj(
        {"status": {"const": "READBACK"}, "digest": ref("#/$defs/digest"), "lines": arr(ref("#/$defs/readbackLine"), 0)}
    ),
    "shapeRefusal": obj(
        {
            "status": {"const": "REFUSED"},
            "code": {"enum": [code for code in refusal_codes if code != "PROTOCOL_INVALID"]},
            "path": {"const": ""},
        }
    ),
    "deployInput": ref(BASE + "lifecycle.schema.json#/$defs/deployInput"),
    "deployResult": ref(BASE + "lifecycle.schema.json#/$defs/deployResult"),
    "stepInput": ref(BASE + "lifecycle.schema.json#/$defs/stepInput"),
    "stepResult": ref(BASE + "lifecycle.schema.json#/$defs/stepResult"),
    "stepRefusal": ref(BASE + "lifecycle.schema.json#/$defs/statefulRefusal"),
    "hostCommitResult": ref(BASE + "lifecycle.schema.json#/$defs/hostCommitResult"),
    "evidenceInput": ref(BASE + "evidence.schema.json#/$defs/input"),
    "evidenceResult": ref(BASE + "evidence.schema.json#/$defs/result"),
    "evidenceRefusal": ref(BASE + "evidence.schema.json#/$defs/refusal"),
}
def protocol_request(operation: str, input_schema: dict) -> dict:
    return obj(
        {
            "protocol": {"const": PROTOCOL},
            "request_id": ID,
            "operation": {"const": operation},
            "input": input_schema,
        }
    )


def protocol_response(operation: str, result_schema: dict) -> dict:
    return obj(
        {
            "protocol": {"const": PROTOCOL},
            "request_id": ID,
            "operation": {"const": operation},
            "result": result_schema,
        }
    )


protocol_defs["request"] = {
    "oneOf": [
        protocol_request("capabilities", ref("#/$defs/capabilitiesInput")),
        protocol_request("validate", ref("#/$defs/artifactInput")),
        protocol_request("evaluate", ref("#/$defs/evaluateInput")),
        protocol_request("aggregate-step", ref(BASE + "reservation.schema.json#/$defs/input")),
        protocol_request("deploy", ref("#/$defs/deployInput")),
        protocol_request("step", ref("#/$defs/stepInput")),
        protocol_request("readback", ref("#/$defs/artifactInput")),
        protocol_request("check-evidence", ref("#/$defs/evidenceInput")),
    ]
}
protocol_defs["response"] = {
    "oneOf": [
        protocol_response("capabilities", {"anyOf": [ref("#/$defs/capabilitiesResult"), ref("#/$defs/shapeRefusal")]}),
        protocol_response("validate", {"anyOf": [ref("#/$defs/validateResult"), ref("#/$defs/shapeRefusal")]}),
        protocol_response("evaluate", {"anyOf": [ref(BASE + "aggregate.schema.json#/$defs/result"), ref(BASE + "aggregate.schema.json#/$defs/refusal"), ref(BASE + "authority.schema.json#/$defs/result"), ref(BASE + "authority.schema.json#/$defs/refusal"), ref("#/$defs/shapeRefusal")]}),
        protocol_response("aggregate-step", {"anyOf": [ref(BASE + "reservation.schema.json#/$defs/result"), ref(BASE + "reservation.schema.json#/$defs/statefulRefusal"), ref(BASE + "reservation.schema.json#/$defs/shapeRefusal"), ref("#/$defs/shapeRefusal")]}),
        protocol_response("deploy", {"anyOf": [ref("#/$defs/deployResult"), ref(BASE + "lifecycle.schema.json#/$defs/deployRefusal"), ref("#/$defs/shapeRefusal")]}),
        protocol_response("step", {"anyOf": [ref("#/$defs/stepResult"), ref("#/$defs/stepRefusal"), ref("#/$defs/shapeRefusal")]}),
        protocol_response("readback", {"anyOf": [ref("#/$defs/readbackResult"), ref("#/$defs/shapeRefusal")]}),
        protocol_response("check-evidence", {"anyOf": [ref("#/$defs/evidenceResult"), ref("#/$defs/evidenceRefusal"), ref("#/$defs/shapeRefusal")]}),
        obj(
            {
                "protocol": {"const": PROTOCOL},
                "request_id": nullable(ID),
                "operation": nullable(ID),
                "result": obj({"status": {"const": "REFUSED"}, "code": {"const": "PROTOCOL_INVALID"}, "path": {"const": ""}}),
            }
        ),
    ]
}
write(
    "protocol.schema.json",
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "protocol.schema.json",
        "$comment": "DRAFT_NOT_ADOPTED; APPARATUS_ONLY. The adapter uses this closed bundled schema graph.",
        "$defs": protocol_defs,
        "oneOf": [ref("#/$defs/request"), ref("#/$defs/response")],
    },
)


for existing_name, root_variants in {
    "aggregate.schema.json": ["input", "result", "refusal"],
    "authority.schema.json": ["input", "result", "refusal"],
    "reservation.schema.json": ["input", "result", "statefulRefusal", "shapeRefusal"],
}.items():
    existing_path = LIB / existing_name
    existing_schema = json.loads(existing_path.read_text())
    if existing_name == "authority.schema.json":
        existing_schema["$defs"]["step"]["properties"]["quantity_mode"] = {
            "enum": ["BOUNDED", "NONE"]
        }
    if existing_name == "aggregate.schema.json":
        extend_common(existing_schema)
    elif existing_name == "authority.schema.json":
        extend_authority(existing_schema)
    elif existing_name == "reservation.schema.json":
        extend_reservation(existing_schema)
        extend_reservation_schema(existing_schema)
    existing_schema["$comment"] = (
        "DRAFT_NOT_ADOPTED; APPARATUS_ONLY. Shape admission does not establish authority, "
        "observation truth or host assurance."
    )
    for refusal_name in ["refusal", "statefulRefusal", "shapeRefusal"]:
        refusal = existing_schema.get("$defs", {}).get(refusal_name)
        if refusal and "path" in refusal.get("properties", {}):
            refusal["properties"]["path"] = {"const": ""}
    if existing_name == "reservation.schema.json":
        existing_schema["$defs"]["configuration"]["properties"]["slots"]["minItems"] = 0
        existing_schema["$defs"]["configuration"]["anyOf"] = [
            {"properties": {"slots": {"type": "array", "minItems": 1}}},
            {"required": ["exclusive_slots"], "properties": {"exclusive_slots": {"type": "array", "minItems": 1}}},
        ]
        existing_schema["$defs"]["nativeCollection"] = obj(
            {
                "name": ref(BASE + "aggregate.schema.json#/$defs/id"),
                "element_type_ref": ref(BASE + "aggregate.schema.json#/$defs/id"),
                "values": arr(ref(BASE + "aggregate.schema.json#/$defs/value"), 0, 1024),
            }
        )
        native = existing_schema["$defs"]["native"]
        native["properties"]["observed_request"] = nullable(ref("#/$defs/nativeRequest"))
        native["properties"]["actual_fields"] = arr(
            ref(BASE + "aggregate.schema.json#/$defs/field"), 0, 66
        )
        native["properties"]["collections"] = arr(ref("#/$defs/nativeCollection"), 0, 64)
        native["properties"]["completion_mismatch"] = {"type": "boolean"}
        native["properties"]["mismatch_reason"] = nullable(
            {"enum": ["NATIVE_REQUEST_MISMATCH", "UNEXPECTED_EFFECT"]}
        )
        for required_name in [
            "observed_request",
            "actual_fields",
            "collections",
            "completion_mismatch",
            "mismatch_reason",
        ]:
            if required_name not in native["required"]:
                native["required"].append(required_name)
        for event_variant in existing_schema["$defs"]["event"]["oneOf"]:
            if event_variant.get("properties", {}).get("kind", {}).get("const") == "RELEASE":
                event_variant["properties"]["administration"] = nullable(ref("#/$defs/administration"))
    existing_schema["oneOf"] = [ref(f"#/$defs/{variant}") for variant in root_variants]
    write(existing_name, existing_schema)


work_schema = json.loads((LIB / "work-class.schema.json").read_text())
lifecycle_schema = json.loads((LIB / "lifecycle.schema.json").read_text())
authority_schema = json.loads((LIB / "authority.schema.json").read_text())
evidence_schema = json.loads((LIB / "evidence.schema.json").read_text())
reservation_schema = json.loads((LIB / "reservation.schema.json").read_text())
extend_completion_schemas(work_schema, lifecycle_schema, authority_schema)
extend_boundary_evidence(evidence_schema)
extend_correction_schemas(work_schema, authority_schema, evidence_schema)
extend_recovery_schemas(work_schema, lifecycle_schema, reservation_schema)
extend_timing_schemas(work_schema, lifecycle_schema, authority_schema)
# Evidence-only leaves must remain nonrecursive when rebuilding an extended candidate.
authority_schema["$defs"]["envelope"]["properties"].pop("holdings_requirements", None)
authority_schema["$defs"]["input"]["properties"].pop("holdings_bases", None)
authority_schema["$defs"]["envelope"]["properties"].pop("assessment_requirements", None)
authority_schema["$defs"]["input"]["properties"].pop("assessment_bases", None)
authority_schema["$defs"]["envelope"]["properties"].pop("flow_requirements", None)
authority_schema["$defs"]["input"]["properties"].pop("flow_bases", None)
authority_schema["$defs"]["refusal"]["properties"]["code"]["enum"] = [value for value in authority_schema["$defs"]["refusal"]["properties"]["code"]["enum"] if value not in {"DEFINITION_INVALID", "STATE_INVALID", "DIGEST_MISMATCH", "CLOCK_INVALID"}]
for name in ("check", "failedCheck"):
    values = authority_schema["$defs"][name]["properties"]["purpose"]["enum"]
    authority_schema["$defs"][name]["properties"]["purpose"]["enum"] = [value for value in values if value not in {"HOLDINGS", "ASSESSMENT", "FLOW"}]
for name, prop in (("refusal", "reasons"), ("failedCheck", "reason")):
    target = authority_schema["$defs"][name]["properties"][prop]
    if prop == "reasons":
        target = target["items"]
    target["enum"] = [value for value in target["enum"] if value not in {"CURRENT_HOLDING_REQUIRED", "HOLDINGS_UNAVAILABLE", "HOLDINGS_STALE", "HOLDINGS_CAPACITY_EXHAUSTED", "ASSESSMENT_NOT_SATISFIED", "ASSESSMENT_DEPENDENCY_CHANGED", "FLOW_UNAVAILABLE", "FLOW_STALE", "FLOW_CAPACITY_EXHAUSTED", "FLOW_DEPENDENCY_CHANGED", "FLOW_RECIPIENT_NOT_ENTITLED", "FLOW_RELEASE_NOT_ESTABLISHED", "FLOW_CLAIM_CONSUMED"}]
extend_cdmo_schemas(work_schema, lifecycle_schema, authority_schema, evidence_schema)
protocol_schema = json.loads((LIB / "protocol.schema.json").read_text())
extend_holdings_schemas(authority_schema, lifecycle_schema, protocol_schema)
extend_assessment_schemas(authority_schema, evidence_schema)
extend_information_flow_schemas(authority_schema, lifecycle_schema, protocol_schema)
write("work-class.schema.json", work_schema)
write("lifecycle.schema.json", lifecycle_schema)
write("authority.schema.json", authority_schema)
write("evidence.schema.json", evidence_schema)
write("reservation.schema.json", reservation_schema)
write("protocol.schema.json", protocol_schema)
write("holdings.schema.json", holdings_schema())
write("information-flow.schema.json", information_flow_schema(authority_schema))

schema_names = [
    "aggregate.schema.json",
    "authority.schema.json",
    "boundary.schema.json",
    "evidence.schema.json",
    "holdings.schema.json",
    "information-flow.schema.json",
    "lifecycle.schema.json",
    "protocol.schema.json",
    "reservation.schema.json",
    "work-class.schema.json",
]
registry = {
    "identity": "seampoint.work-class.schema-bundle/1.0.0-draft.3",
    "status": "DRAFT_NOT_ADOPTED",
    "resolution": "Map each exact URI to the listed candidate-relative file. Any other URI is unresolved. No network or undeclared filesystem access is permitted.",
    "schemas": [
        {"uri": BASE + name, "path": name, "sha256": hashlib.sha256((LIB / name).read_bytes()).hexdigest()}
        for name in schema_names
    ],
}
write("schema-bundle.json", registry)
print(json.dumps({"written": ["work-class.schema.json", "lifecycle.schema.json", "evidence.schema.json", "boundary.schema.json", "protocol.schema.json", "schema-bundle.json"]}, indent=2))
