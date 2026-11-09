#!/usr/bin/env python3
"""Build exact deployment vectors from LIFE-003."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from fixture_factory import PIN, available_clock, deploy_refusal, deployment, deployment_evidence, readback_paths, work_class


def rebind_authorization(input_value: dict) -> None:
    authorization = input_value["deployment_authorization"]
    evidence = input_value["authorization_evidence"]
    subject = copy.deepcopy(authorization)
    del subject["authorization_evidence_digest"]
    subject_digest = digest("deployment-authorization-subject", subject)
    evidence["subject_digest"] = subject_digest
    evidence_digest = digest("evidence", evidence)
    authorization["authorization_evidence_digest"] = evidence_digest


def rebind_review_evidence(input_value: dict) -> None:
    """Recompute the three LIFE-003 review-record digests into the authorization, then the organizational binding."""
    authorization = input_value["deployment_authorization"]
    authorization["correspondence_evidence_digest"] = digest("evidence", input_value["correspondence_evidence"])
    authorization["source_confirmation_evidence_digest"] = digest("evidence", input_value["source_confirmation_evidence"])
    authorization["policy_decision_evidence_digest"] = digest("evidence", input_value["policy_decision_evidence"])
    rebind_authorization(input_value)


def rebind_correspondence_review(correspondence: dict) -> None:
    subject = {key: value for key, value in correspondence.items() if key != "review"}
    correspondence["review"]["subject_digest"] = digest("correspondence-subject", subject)


def review_evidence_cases(valid_input: dict) -> list[dict]:
    """CR-01: deployment refuses without accepted, exactly bound correspondence, source-confirmation and policy-decision evidence."""
    profile, role = valid_input["profile"], valid_input["role"]
    cases = []

    substituted = copy.deepcopy(valid_input)
    other_definition = work_class("LINEAR")
    substituted["correspondence_evidence"] = deployment_evidence(other_definition, recorded_at=valid_input["deployment_authorization"]["authorized_at"], id_prefix="other")[0]
    rebind_review_evidence(substituted)
    cases.append(exact_case(
        "C2-deploy-substituted-definition", "deploy", substituted, deploy_refusal(profile, role, "BINDING_MISMATCH"), ["LIFE-003", "WCS2-005"],
        "The supplied correspondence record is the accepted record of another definition: its work-class digest and subject digest are that definition's, and the deployment authorization names this record's digest, so the digest binding holds and the organizational authorization passes its own checks. LIFE-003 requires the correspondence record to meet the correspondence form of check-evidence for the deployed definition, whose work-class digest equality fails. The refusal is BINDING_MISMATCH and no state is created: an accepted review of one translation cannot deploy another.",
    ))

    pending_residue = copy.deepcopy(valid_input)
    correspondence = pending_residue["correspondence_evidence"]
    moved = correspondence["mappings"][0]["provision_paths"].pop()
    for mapping in correspondence["mappings"][1:]:
        mapping["provision_paths"].remove(moved)
    correspondence["unsupported_provision_paths"] = [moved]
    correspondence["residue"] = [{"kind": "ARTIFACT_PROVISION", "subject": moved, "disposition": "PENDING", "explanation": "Awaiting the reviewer's disposition of this provision."}]
    rebind_correspondence_review(correspondence)
    rebind_review_evidence(pending_residue)
    cases.append(exact_case(
        "C2-deploy-pending-residue", "deploy", pending_residue, deploy_refusal(profile, role, "EVIDENCE_UNAVAILABLE"), ["LIFE-003", "WCS2-005"],
        "One provision path is unsupported with a residue row whose disposition is PENDING; the partition, coverage and nested review are exact and every digest is rebound. LIFE-003 admits UNSUPPORTED and EXCLUDED residue rows but refuses a PENDING row as EVIDENCE_UNAVAILABLE, because a pending disposition means nobody has yet signed that silence. No state is created.",
    ))

    pending_review = copy.deepcopy(valid_input)
    pending_review["correspondence_evidence"]["review"]["status"] = "PENDING"
    rebind_review_evidence(pending_review)
    cases.append(exact_case(
        "C2-deploy-pending-nested-review", "deploy", pending_review, deploy_refusal(profile, role, "EVIDENCE_UNAVAILABLE"), ["LIFE-003", "WCS2-005"],
        "The correspondence record's own status is ACCEPTED but its nested review is PENDING; the review subject digest and every deployment digest are exact. LIFE-003 requires the nested review to be ACCEPTED, so the refusal is EVIDENCE_UNAVAILABLE and no state is created.",
    ))

    shared_identifier = copy.deepcopy(valid_input)
    shared_identifier["policy_decision_evidence"]["evidence_id"] = shared_identifier["source_confirmation_evidence"]["evidence_id"]
    rebind_review_evidence(shared_identifier)
    cases.append(exact_case(
        "C2-deploy-one-record-two-kinds", "deploy", shared_identifier, deploy_refusal(profile, role, "BINDING_MISMATCH"), ["LIFE-003"],
        "The policy-decision record carries the source-confirmation record's evidence identifier; both records are otherwise accepted and exactly bound. LIFE-003 requires the four deployment evidence records to have four distinct identifiers, because one record cannot serve two kinds even when one person holds both remits. The refusal is BINDING_MISMATCH and no state is created.",
    ))

    rejected_policy = copy.deepcopy(valid_input)
    rejected_policy["policy_decision_evidence"]["status"] = "REJECTED"
    rebind_review_evidence(rejected_policy)
    cases.append(exact_case(
        "C2-deploy-rejected-policy-decision", "deploy", rejected_policy, deploy_refusal(profile, role, "EVIDENCE_UNAVAILABLE"), ["LIFE-003"],
        "The policy-decision record has status REJECTED and its digest is rebound into the authorization. LIFE-003 requires an ACCEPTED policy decision; a pending, rejected or deferred record is EVIDENCE_UNAVAILABLE. No state is created.",
    ))

    two_faults = copy.deepcopy(valid_input)
    two_faults["source_confirmation_evidence"]["subject_digest"] = "sha256:" + "2" * 64
    two_faults["policy_decision_evidence"]["status"] = "PENDING"
    rebind_review_evidence(two_faults)
    cases.append(exact_case(
        "C2-deploy-source-subject-mismatch-and-pending-policy", "deploy", two_faults, deploy_refusal(profile, role, "BINDING_MISMATCH"), ["LIFE-003"],
        "The source-confirmation record names a subject digest other than digest(work-class-source, source), and the policy-decision record has status PENDING; both digests are rebound into the authorization. LIFE-003: within the review-evidence checks every BINDING_MISMATCH condition of the three records precedes every EVIDENCE_UNAVAILABLE condition, so the refusal is BINDING_MISMATCH and no state is created.",
    ))

    pending_mismatch = copy.deepcopy(valid_input)
    pending_mismatch["correspondence_evidence"]["status"] = "PENDING"
    pending_mismatch["correspondence_evidence"]["subject_digest"] = "sha256:" + "3" * 64
    rebind_correspondence_review(pending_mismatch["correspondence_evidence"])
    rebind_review_evidence(pending_mismatch)
    cases.append(exact_case(
        "C2-deploy-pending-correspondence-subject-mismatch", "deploy", pending_mismatch, deploy_refusal(profile, role, "BINDING_MISMATCH"), ["LIFE-003"],
        "The correspondence record has status PENDING and names a subject digest other than the definition digest; its nested review is rebound to the changed record and every dependent digest is rebound. LIFE-003: every BINDING_MISMATCH condition of the three review records precedes every EVIDENCE_UNAVAILABLE condition, so the refusal is BINDING_MISMATCH and no state is created.",
    ))
    return cases


def build() -> list[dict]:
    deadline_definition = work_class(
        "DEADLINES", deadline_due={"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-11T01:00:00Z"}
    )
    root_clock = available_clock("work-clock", "1", "2026-09-11T00:00:00Z")
    valid_input, valid_result = deployment(deadline_definition, initial_clocks=[root_clock])
    cases = [
        exact_case(
            "D2-008",
            "deploy",
            valid_input,
            valid_result,
            ["LIFE-003"],
            "LIFE-003 accepts the exact profile-role pair, definition digest, instance-bound authorization, accepted organizational evidence, available authorization clock, and the one required root deadline clock. The expected state and all digests follow the stated deployment construction order.",
        )
    ]

    wrong_instance = copy.deepcopy(valid_input)
    wrong_instance["deployment_authorization"]["instance_id"] = "access-instance-2"
    rebind_authorization(wrong_instance)
    cases.append(
        exact_case(
            "D2-009",
            "deploy",
            wrong_instance,
            deploy_refusal("DEADLINES", "DEADLINE_RUNTIME", "DEPENDENCY_MISMATCH"),
            ["LIFE-003"],
            "All authorization records and their digests are internally consistent, but the authorization names another instance. LIFE-003 assigns DEPENDENCY_MISMATCH.",
        )
    )

    pending = copy.deepcopy(valid_input)
    pending["authorization_evidence"]["status"] = "PENDING"
    rebind_authorization(pending)
    cases.append(
        exact_case(
            "D2-010",
            "deploy",
            pending,
            deploy_refusal("DEADLINES", "DEADLINE_RUNTIME", "EVIDENCE_UNAVAILABLE"),
            ["LIFE-003"],
            "The deployment authorization and evidence digests are recomputed over a structurally admitted PENDING organizational act. LIFE-003 forbids pending evidence from establishing deployment authority.",
        )
    )

    missing_clock = copy.deepcopy(valid_input)
    missing_clock["initial_clocks"] = []
    cases.append(
        exact_case(
            "D2-011",
            "deploy",
            missing_clock,
            deploy_refusal("DEADLINES", "DEADLINE_RUNTIME", "EVIDENCE_UNAVAILABLE"),
            ["LIFE-003", "DEAD-001"],
            "The admitted root deadline requires work-clock, but initial_clocks omits it. LIFE-003 assigns EVIDENCE_UNAVAILABLE and creates no state.",
        )
    )

    due_clock = available_clock("work-clock", "1", "2026-09-11T01:00:00Z")
    already_due, _ = deployment(deadline_definition, initial_clocks=[due_clock])
    cases.append(
        exact_case(
            "D2-091",
            "deploy",
            already_due,
            deploy_refusal("DEADLINES", "DEADLINE_RUNTIME", "CLOCK_INVALID"),
            ["LIFE-003", "LIFE-014"],
            "The AT_OR_AFTER root deadline is satisfied at equality by its exact initial clock. LIFE-003 refuses deployment rather than admitting an already expired root.",
        )
    )

    elapsed_definition = work_class(
        "DEADLINES", deadline_due={"kind": "ELAPSED_DURATION", "value": "1", "unit": "HOUR"}
    )
    elapsed_input, elapsed_result = deployment(elapsed_definition, initial_clocks=[root_clock])
    cases.append(
        exact_case(
            "D2-138",
            "deploy",
            elapsed_input,
            elapsed_result,
            ["LIFE-003", "LIFE-014"],
            "The elapsed root deadline uses the admitted initial clock and produces due time 01:00:00Z. Deployment revision and activation_revision are both zero as LIFE-003 and LIFE-014 require.",
        )
    )

    linear_definition = work_class("LINEAR")
    unsupported_input, _ = deployment(linear_definition)
    unsupported_input["role"] = "DEADLINE_RUNTIME"
    cases.append(
        exact_case(
            "D2-165",
            "deploy",
            unsupported_input,
            deploy_refusal("LINEAR", "DEADLINE_RUNTIME", "ROLE_UNSUPPORTED"),
            ["LIFE-002", "WCS2-011"],
            "LINEAR and DEADLINE_RUNTIME are separately admitted enum values but are not one of the four exact profile-role pairs. Role selection precedes definition and authorization checks.",
        )
    )

    unavailable_input, _ = deployment(linear_definition)
    unavailable_input["deployment_authorization"]["authorized_at"] = "2026-09-11T00:00:01Z"
    rebind_authorization(unavailable_input)
    cases.append(
        exact_case(
            "D2-186",
            "deploy",
            unavailable_input,
            deploy_refusal("LINEAR", "LINEAR_WORK_RUNTIME", "EVIDENCE_UNAVAILABLE"),
            ["LIFE-003", "WCS2-012"],
            "The closed authorization exists, but its authorized_at time is later than the required authorization clock. LIFE-003 treats the authorization as unavailable while retaining the admitted profile and role in the refusal.",
        )
    )

    choice_definition = work_class("CHOICE_LOOPS")
    profile_mismatch, _ = deployment(choice_definition)
    profile_mismatch["profile"] = "LINEAR"
    profile_mismatch["role"] = "LINEAR_WORK_RUNTIME"
    profile_mismatch["deployment_authorization"]["profile"] = "LINEAR"
    profile_mismatch["deployment_authorization"]["role"] = "LINEAR_WORK_RUNTIME"
    rebind_authorization(profile_mismatch)
    cases.append(
        exact_case(
            "D2-222",
            "deploy",
            profile_mismatch,
            deploy_refusal("LINEAR", "LINEAR_WORK_RUNTIME", "BINDING_MISMATCH"),
            ["LIFE-002", "WCS2-012"],
            "The request and authorization consistently select the admitted LINEAR pair, but the supplied definition declares CHOICE_LOOPS. The exact profile equality rule assigns BINDING_MISMATCH.",
        )
    )

    expired_input, _ = deployment(
        linear_definition,
        authorization_expires_at="2026-09-11T00:00:00Z",
    )
    cases.append(
        exact_case(
            "D2-231",
            "deploy",
            expired_input,
            deploy_refusal("LINEAR", "LINEAR_WORK_RUNTIME", "EVIDENCE_UNAVAILABLE"),
            ["LIFE-003"],
            "The nonnull deployment-authorization expiry equals the authorization clock. The expiry is exclusive, so LIFE-003 returns EVIDENCE_UNAVAILABLE.",
        )
    )
    cases.extend(review_evidence_cases(valid_input))
    return cases


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "deployment" / f"{case['id']}.json", case)
    print(json.dumps({"candidate_pin": PIN, "case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
