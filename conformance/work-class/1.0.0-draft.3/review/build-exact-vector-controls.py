#!/usr/bin/env python3
"""Create the six digest-only vectors called out by REPORT-3.md.

D2-058 and D2-071 are full step/replay vectors and are intentionally built by
the lifecycle corpus builder. This script never reads an implementation.
"""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, candidate_pin, digest, exact_case, write_canonical_json


PIN = candidate_pin()
ZERO = "sha256:" + "0" * 64


def occurrence_subject(instance_id: str) -> dict:
    return {
        "specification_pin": PIN,
        "work_class_digest": digest("work-class-definition", {"vector": "occurrence"}),
        "instance_id": instance_id,
        "step_id": "issue-card",
        "ordinal": "1",
        "predecessor_occurrence_ids": [],
        "enclosing": [],
        "object_key": None,
    }


def obligation_subject() -> dict:
    return {
        "kind": "PARALLEL_BRANCH",
        "construct_id": "background-checks",
        "pass": "1",
        "source_occurrence_ids": [digest("occurrence", occurrence_subject("instance-A"))],
        "branch_id": "identity-check",
        "object_key": None,
        "join_step_id": "checks-complete",
    }


def minimal_review_evidence() -> tuple[dict, dict, dict]:
    """Schema-valid LIFE-003 review records for a state whose definition is a digest-only stand-in."""
    work_digest = digest("work-class-definition", {"vector": "state"})
    correspondence = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": "correspondence-1",
        "kind": "CORRESPONDENCE",
        "status": "ACCEPTED",
        "subject_digest": work_digest,
        "source_id": "source-A",
        "source_revision": "1",
        "work_class_digest": work_digest,
        "mappings": [],
        "uncovered_source_obligation_ids": [],
        "unsupported_provision_paths": [],
        "residue": [],
        "recorded_at": "2026-09-11T00:00:00Z",
        "provenance_digest": digest("evidence-provenance", {"vector": "correspondence"}),
    }
    correspondence["review"] = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": "correspondence-review-1",
        "kind": "REVIEW",
        "status": "ACCEPTED",
        "subject_digest": digest("correspondence-subject", {key: value for key, value in correspondence.items() if key != "review"}),
        "reviewer_id": "reviewer-A",
        "paragraph_ids": [],
        "case_ids": [],
        "finding_ids": [],
        "recorded_at": "2026-09-11T00:00:00Z",
        "provenance_digest": digest("evidence-provenance", {"vector": "correspondence-review"}),
    }
    source_confirmation = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": "source-confirmation-1",
        "kind": "SOURCE_CONFIRMATION",
        "status": "ACCEPTED",
        "subject_digest": digest("work-class-source", {"id": "source-A", "revision": "1", "obligations": ["obligation-1"]}),
        "actor_id": "confirmer-A",
        "scope_ids": ["obligation-1"],
        "recorded_at": "2026-09-11T00:00:00Z",
        "provenance_digest": digest("evidence-provenance", {"vector": "source-confirmation"}),
    }
    policy_decision = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": "policy-decision-1",
        "kind": "POLICY_DECISION",
        "status": "ACCEPTED",
        "subject_digest": work_digest,
        "decision_maker_id": "policy-owner-A",
        "decision_ids": ["decision-1"],
        "recorded_at": "2026-09-11T00:00:00Z",
        "provenance_digest": digest("evidence-provenance", {"vector": "policy-decision"}),
    }
    return correspondence, source_confirmation, policy_decision


def minimal_state() -> dict:
    review_evidence = minimal_review_evidence()
    deployment_authorization = {
        "schema": "seampoint.work-class/1.0.0-draft.3/deployment-authorization",
        "authorization_id": "authorization-1",
        "specification_pin": PIN,
        "work_class_digest": digest("work-class-definition", {"vector": "state"}),
        "profile": "LINEAR",
        "role": "LINEAR_WORK_RUNTIME",
        "instance_id": "instance-A",
        "organization_id": "organization-A",
        "status": "AUTHORIZED",
        "authorization_evidence_digest": ZERO,
        "correspondence_evidence_digest": digest("evidence", review_evidence[0]),
        "source_confirmation_evidence_digest": digest("evidence", review_evidence[1]),
        "policy_decision_evidence_digest": digest("evidence", review_evidence[2]),
        "authorized_at": "2026-09-11T00:00:00Z",
        "expires_at": None,
    }
    subject_record = dict(deployment_authorization)
    del subject_record["authorization_evidence_digest"]
    subject_digest = digest("deployment-authorization-subject", subject_record)
    evidence = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": "deployment-evidence-1",
        "kind": "ORGANIZATIONAL_AUTHORIZATION",
        "status": "ACCEPTED",
        "subject_digest": subject_digest,
        "organization_id": "organization-A",
        "authorizer_id": "authorizer-A",
        "authorization_scope": sorted(
            [
                PIN,
                deployment_authorization["work_class_digest"],
                "LINEAR",
                "LINEAR_WORK_RUNTIME",
                "instance-A",
            ]
        ),
        "recorded_at": "2026-09-11T00:00:00Z",
        "expires_at": "2026-09-12T00:00:00Z",
        "provenance_digest": digest("evidence-provenance", {"vector": "state"}),
    }
    evidence_digest = digest("evidence", evidence)
    deployment_authorization["authorization_evidence_digest"] = evidence_digest
    occurrence = occurrence_subject("instance-A")
    occurrence_record = {"occurrence_id": digest("occurrence", occurrence), **occurrence}
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/work-state",
        "specification_pin": PIN,
        "work_class_digest": deployment_authorization["work_class_digest"],
        "profile": "LINEAR",
        "role": "LINEAR_WORK_RUNTIME",
        "instance_id": "instance-A",
        "deployment_authorization": deployment_authorization,
        "deployment_authorization_subject_digest": subject_digest,
        "deployment_authorization_digest": digest("deployment-authorization", deployment_authorization),
        "deployment_authorization_evidence": evidence,
        "deployment_authorization_evidence_digest": evidence_digest,
        "deployment_correspondence_evidence": review_evidence[0],
        "deployment_correspondence_evidence_digest": deployment_authorization["correspondence_evidence_digest"],
        "deployment_source_confirmation_evidence": review_evidence[1],
        "deployment_source_confirmation_evidence_digest": deployment_authorization["source_confirmation_evidence_digest"],
        "deployment_policy_decision_evidence": review_evidence[2],
        "deployment_policy_decision_evidence_digest": deployment_authorization["policy_decision_evidence_digest"],
        "deployment_authorization_clock": {
            "source": "deployment-clock",
            "revision": "1",
            "status": "AVAILABLE",
            "observed_time": "2026-09-11T00:00:00Z",
            "evidence_digest": digest("clock-evidence", {"vector": "deployment"}),
        },
        "deployment_organization_id": "organization-A",
        "revision": "0",
        "status": "ACTIVE",
        "total_activations": "1",
        "total_actuations": "0",
        "step_counters": [{"step_id": "issue-card", "activations": "1", "actuations": "0"}],
        "active": [
            {
                "occurrence": occurrence_record,
                "activation_event_digest": digest(
                    "deployment-activation",
                    {
                        "deployment_authorization_digest": digest(
                            "deployment-authorization", deployment_authorization
                        ),
                        "instance_id": "instance-A",
                        "occurrence_id": occurrence_record["occurrence_id"],
                    },
                ),
                "status": "ACTIVE",
                "deadline_ids": [],
            }
        ],
        "completed": [],
        "obligations": [],
        "proposals": [],
        "permits": [],
        "dispatches": [],
        "outcomes": [],
        "clocks": [],
        "deadlines": [],
        "fanout_passes": [],
        "receipts": [],
        "replays": [],
    }


def state_core_digest(state: dict) -> str:
    core = copy.deepcopy(state)
    core["receipts"] = []
    core["replays"] = []
    return digest("work-state-core", core)


def state_digest(state: dict) -> str:
    identity = copy.deepcopy(state)
    for replay in identity["replays"]:
        replay.pop("transaction_digest", None)
    return digest("work-state", identity)


def case_065() -> dict:
    a = occurrence_subject("instance-A")
    b = occurrence_subject("instance-B")
    return exact_case(
        "D2-065",
        "validate vectors",
        {"kind": "OCCURRENCE_IDENTITY", "subjects": [a, b]},
        {
            "relation": "DISTINCT",
            "digests": [digest("occurrence", a), digest("occurrence", b)],
        },
        ["WCS2-002", "LIFE-004"],
        "LIFE-004 includes instance_id in the complete occurrence preimage. The two otherwise equal subjects therefore have the listed distinct digests.",
    )


def case_066() -> dict:
    subject = obligation_subject()
    expected_digest = digest("obligation", subject)
    return exact_case(
        "D2-066",
        "validate vectors",
        {"kind": "OBLIGATION_IDENTITY", "subject": subject},
        {"digest": expected_digest},
        ["WCS2-002", "LIFE-019"],
        "WCS2-002 fixes the obligation preimage to the seven immutable fields supplied here. Both languages must produce this exact digest.",
    )


def case_076() -> dict:
    before = minimal_state()
    after = copy.deepcopy(before)
    after["total_activations"] = "2"
    return exact_case(
        "D2-076",
        "validate vectors",
        {"kind": "STATE_CORE_MUTATION", "before": before, "after": after},
        {
            "relation": "DISTINCT",
            "before_digest": state_core_digest(before),
            "after_digest": state_core_digest(after),
        },
        ["WCS2-002", "LIFE-019"],
        "LIFE-019 includes total_activations in the complete state-core preimage. Changing that field changes the listed digest.",
    )


def case_077() -> dict:
    state = minimal_state()
    event_digest = digest("runtime-event", {"vector": "receipt-mutation"})
    decision = {
        "schema": "seampoint.work-class/1.0.0-draft.3/decision-receipt",
        "decision_id": ZERO,
        "instance_id": "instance-A",
        "sequence": "1",
        "event_id": "event-1",
        "event_digest": event_digest,
        "event_kind": "CLOCK",
        "disposition": "CLOCK_RECORDED",
        "reason_codes": [],
        "details": [],
        "permit_digest": None,
        "authority_result_digest": None,
        "reservation_receipt_digests": [],
        "state_before_digest": state_digest(state),
        "state_after_core_digest": ZERO,
    }
    core_state = copy.deepcopy(state)
    core_state["revision"] = "1"
    core_state["receipts"] = []
    core_state["replays"] = []
    decision["state_after_core_digest"] = state_core_digest(core_state)
    decision_subject = dict(decision)
    del decision_subject["decision_id"]
    decision["decision_id"] = digest("decision-receipt", decision_subject)
    replay = {
        "event_id": "event-1",
        "event_digest": event_digest,
        "decision": copy.deepcopy(decision),
        "decision_receipt_digest": decision["decision_id"],
        "permit": None,
        "budget_results": [],
        "transition_state_digest": decision["state_after_core_digest"],
        "transaction_digest": digest("lifecycle-transaction", {"vector": "receipt-mutation"}),
    }
    before = copy.deepcopy(core_state)
    before["receipts"] = [decision]
    before["replays"] = [replay]
    after = copy.deepcopy(before)
    after["receipts"][0]["reason_codes"] = ["CLOCK_UNAVAILABLE"]
    return exact_case(
        "D2-077",
        "validate vectors",
        {"kind": "STATE_RECORD_MUTATION", "before": before, "after": after},
        {
            "full_state_relation": "DISTINCT",
            "state_core_relation": "EQUAL",
            "before_state_digest": state_digest(before),
            "after_state_digest": state_digest(after),
            "before_core_digest": state_core_digest(before),
            "after_core_digest": state_core_digest(after),
        },
        ["WCS2-002", "LIFE-019"],
        "LIFE-019 excludes receipts and replays from the state-core preimage but includes the receipt in the complete work-state identity projection. The receipt mutation therefore changes only the full-state digest.",
    )


def lifecycle_reservation_subject(instance_id: str, lifecycle_kind: str, reservation_kind: str) -> dict:
    return {
        "instance_id": instance_id,
        "lifecycle_event_id": "event-1",
        "lifecycle_event_kind": lifecycle_kind,
        "reservation_event_kind": reservation_kind,
        "registry_digest": digest("reservation-registry", {"vector": "shared-registry"}),
    }


def case_094() -> dict:
    a = lifecycle_reservation_subject("instance-A", "PROPOSE", "RESERVE")
    b = lifecycle_reservation_subject("instance-B", "PROPOSE", "RESERVE")
    return exact_case(
        "D2-094",
        "validate vectors",
        {"kind": "LIFECYCLE_RESERVATION_INSTANCE", "subjects": [a, b]},
        {
            "relation": "DISTINCT",
            "digests": [digest("lifecycle-reservation-event", a), digest("lifecycle-reservation-event", b)],
        },
        ["WCS2-002", "LIFE-007"],
        "LIFE-007 includes instance_id in the lifecycle-reservation-event preimage. Reusing the local event identifier in another instance yields the listed distinct digest.",
    )


def case_120() -> dict:
    proposal = lifecycle_reservation_subject("instance-A", "PROPOSE", "RESERVE")
    effect = lifecycle_reservation_subject("instance-A", "EFFECT_OBSERVED", "SETTLE")
    return exact_case(
        "D2-120",
        "validate vectors",
        {"kind": "LIFECYCLE_RESERVATION_EVENT_KIND", "subjects": [proposal, effect]},
        {
            "relation": "DISTINCT",
            "digests": [
                digest("lifecycle-reservation-event", proposal),
                digest("lifecycle-reservation-event", effect),
            ],
        },
        ["WCS2-002", "LIFE-007", "LIFE-010"],
        "The lifecycle-reservation-event preimage includes both lifecycle and reservation event kinds. Equal local event identifiers cannot conflate a proposal reservation with effect settlement.",
    )


def main() -> None:
    cases = [case_065(), case_066(), case_076(), case_077(), case_094(), case_120()]
    for case in cases:
        write_canonical_json(CASES / "vector-controls" / f"{case['id']}.json", case)
    summary = {
        "candidate_pin": PIN,
        "case_ids": [case["id"] for case in cases],
        "count": str(len(cases)),
        "source": "Specification.md WCS2-001/WCS2-002 and lifecycle digest preimages only",
        "implementation_output_used": False,
        "remaining_exact_vector_gaps": ["D2-058", "D2-071"],
    }
    write_canonical_json(CASES / "vector-controls" / "index.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
