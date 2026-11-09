"""Proposed completion/referral schema extension; importing leaves the pin unchanged."""

from __future__ import annotations

import copy

from equipment_schema_extensions import AGG, BASE, DIGEST, FIELD, ID, INSTANT, VALUE, arr, key_projection, nullable, obj, optional


def extend_completion_schemas(work_class_schema, lifecycle_schema, authority_schema=None):
    work = work_class_schema["$defs"]
    lifecycle = lifecycle_schema["$defs"]
    local = lambda name: {"$ref": "#/$defs/" + name}
    unique_ids = lambda maximum: {**arr(ID, maximum), "uniqueItems": True}
    unique_digests = lambda maximum: {**arr(DIGEST, maximum), "uniqueItems": True}

    carrier = copy.deepcopy(work["completionCarrier"])
    legacy = copy.deepcopy(carrier)
    legacy["properties"]["terminal_policy"] = {"const": "LEGACY_NONTERMINAL"}
    legacy["required"].append("terminal_policy")
    terminal = copy.deepcopy(carrier)
    terminal["properties"].update({
        "terminal_policy": {"const": "STOP_RETAIN"},
        "provider_record_identity": obj({"field": ID, "type_ref": ID}),
        "event_time_identity": obj({"field": ID, "type_ref": ID}),
        "additional_fields": arr(FIELD, 64),
        "lookup": obj({"provider": ID, "source": ID, "record_type": ID,
            "namespace": ID, "key_projection": arr(key_projection(), 64, 1)}),
    })
    terminal["required"] = list(terminal["properties"])
    optional(terminal, "generated_fields", arr(obj({"name": ID, "type_ref": ID}), 64))
    work["completionCarrier"] = {"oneOf": [legacy, terminal]}
    if authority_schema is not None:
        authority_schema["$defs"]["completionCarrier"] = {"$ref": BASE + "work-class.schema.json#/$defs/completionCarrier"}
    route = obj({"id": ID, "destination_role": ID, "queue": ID, "purpose": ID,
        "safe_state": ID, "via_role": nullable(ID), "requirement_ids": unique_ids(64)})
    optional(work["step"], "referral_policy", obj({"authority": arr(route, 16), "completion": arr(route, 16)}))
    optional(work["definition"], "boundary_exits", arr(obj({"id": ID,
        "scope": {"enum": ["PHYSICAL_CONTROL", "MIXED_CONTROL"]}, "owner_role": ID,
        "queue": ID, "purpose": ID, "safe_state": ID, "reentry_requirements": unique_ids(64)}), 16))

    optional(lifecycle["nativeEvidence"], "provider_record_id", nullable(ID))
    optional(lifecycle["nativeEvidence"], "provider_revision", nullable(ID))
    optional(lifecycle["governedOutcomeRecord"], "source_event", local("governedEffectObserved"))
    lifecycle["completionQuery"] = obj({"instance_id": ID, "occurrence_id": ID,
        "permit_digest": DIGEST, "dispatch_digest": DIGEST, "authorization_digest": nullable(DIGEST),
        "provider": ID, "source": ID, "record_type": ID, "namespace": ID,
        "key": arr(FIELD, 64, 1), "at": INSTANT})
    lifecycle["completionCandidate"] = obj({"provider": ID, "source": ID,
        "record_type": ID, "provider_record_id": ID, "record_digest": DIGEST})
    lookup_common = {"query": local("completionQuery"), "query_digest": DIGEST,
        "observed_at": INSTANT, "evidence_ref": ID, "provenance_digest": DIGEST}
    usable = {"as_of": INSTANT, "provider_revision": ID,
        "coverage": {"enum": ["COMPLETE", "INCOMPLETE"]}}
    variants = []
    for status, minimum, maximum, truncated in (("NOT_FOUND", 0, 0, False),
            ("AMBIGUOUS", 2, 64, False), ("OVERFLOW", 64, 64, True)):
        variants.append(obj({**copy.deepcopy(lookup_common), **copy.deepcopy(usable),
            "status": {"const": status}, "candidates": arr(local("completionCandidate"), maximum, minimum),
            "truncated": {"const": truncated}}))
    variants.append(obj({**copy.deepcopy(lookup_common), "status": {"const": "UNAVAILABLE"},
        "as_of": {"type": "null"}, "provider_revision": {"type": "null"},
        "coverage": {"const": "UNAVAILABLE"}, "candidates": arr(local("completionCandidate"), 0),
        "truncated": {"const": False}}))
    lifecycle["completionLookup"] = {"oneOf": variants}
    lifecycle["completionChecked"] = obj({
        "schema": {"const": "seampoint.work-class/1.0.0-draft.3/runtime-event"},
        "event_id": ID, "kind": {"const": "COMPLETION_CHECKED"}, "instance_id": ID,
        "expected_state_revision": {"$ref": AGG + "natural"}, "expected_state_digest": DIGEST,
        "permit": local("permit"), "authorization_digest": nullable(DIGEST), "dispatch_digest": DIGEST,
        "lookup": local("completionLookup"), "clock_revision": {"$ref": AGG + "natural"},
    })
    lifecycle["event"]["oneOf"].append(local("completionChecked"))
    lifecycle["completionCheck"] = obj({"check_digest": DIGEST, "event_id": ID,
        "event_digest": DIGEST, "permit_digest": DIGEST, "authorization_digest": nullable(DIGEST),
        "dispatch_digest": DIGEST, "lookup": local("completionLookup"),
        "disposition": {"const": "COMPLETION_FAILED"}, "reason_codes": unique_ids(64)})
    lifecycle["decisionBasis"] = obj({"instance_id": ID, "event_id": ID,
        "event_digest": DIGEST, "disposition": ID, "reason_codes": unique_ids(64),
        **{name: nullable(DIGEST) for name in ("permit_digest", "authority_result_digest",
            "outcome_digest", "completion_check_digest")}})
    lifecycle["terminalRecord"] = obj({"terminal_digest": DIGEST, "event_id": ID,
        "event_digest": DIGEST, "instance_id": ID, "occurrence_id": ID, "permit_digest": DIGEST,
        "authorization_digest": nullable(DIGEST), "dispatch_digest": DIGEST, "decision_basis_digest": DIGEST,
        "cause": {"enum": ["UNKNOWN_COMPLETION", "UNEXPECTED_COMPLETION", "CONFLICTING_COMPLETION",
            "DECLARED_COMPLETION_FAILURE", "COMPLETION_LOOKUP_FAILED", "NO_EFFECT_COMPLETION"]},
        "occurrence_status": {"enum": ["OUTCOME_UNKNOWN", "BLOCKED_DISPUTE"]},
        "evidence_digests": unique_digests(256),
        "retained_reservation_bases": copy.deepcopy(lifecycle["permit"]["properties"]["budget_revisions"]),
    })
    lifecycle["referralIntent"] = obj({"referral_digest": DIGEST, "event_id": ID,
        "event_digest": DIGEST, "instance_id": ID, "occurrence_id": ID, "decision_basis_digest": DIGEST,
        "terminal_digest": nullable(DIGEST), "cause_digest": DIGEST, "destination_role": ID,
        "queue": ID, "purpose": ID, "safe_state": ID, "via_role": nullable(ID),
        "evidence_digests": unique_digests(256)})
    lifecycle["boundaryReferral"] = obj({"referral_digest": DIGEST, "definition_digest": DIGEST,
        "exit_id": ID, "request_digest": DIGEST, "scope": {"enum": ["PHYSICAL_CONTROL", "MIXED_CONTROL"]},
        "owner_role": ID, "queue": ID, "purpose": ID, "safe_state": ID,
        "evidence_ref": ID, "provenance_digest": DIGEST})
    for name, item, maximum in (("completion_checks", "completionCheck", 128),
            ("terminal_records", "terminalRecord", 128), ("referrals", "referralIntent", 4096)):
        optional(lifecycle["state"], name, arr(local(item), maximum))
    lifecycle["proposalAuthorityEvaluation"] = obj({"evaluation_digest": DIGEST,
        "event": local("propose"), "authority_result": {"$ref": BASE + "authority.schema.json#/$defs/refusal"},
        "authority_result_digest": DIGEST})
    optional(lifecycle["state"], "proposal_authority_evaluations", arr(local("proposalAuthorityEvaluation"), 128))
    for name in ("completion_check_digest", "decision_basis_digest", "terminal_digest"):
        optional(lifecycle["decisionReceipt"], name, DIGEST)
    optional(lifecycle["decisionReceipt"], "proposal_authority_evaluation_digest", DIGEST)
    lifecycle["decisionReceipt"]["properties"]["event_kind"]["enum"].append("COMPLETION_CHECKED")
    lifecycle["decisionReceipt"]["properties"]["disposition"]["enum"].append("COMPLETION_FAILED")
    lifecycle["decisionDetailCompletionCheck"] = obj({"kind": {"const": "COMPLETION_CHECK"},
        "check_digest": DIGEST, "status": {"enum": ["NOT_FOUND", "UNAVAILABLE", "AMBIGUOUS", "OVERFLOW"]},
        "reasons": unique_ids(64)})
    lifecycle["decisionDetail"]["oneOf"].insert(6, local("decisionDetailCompletionCheck"))
