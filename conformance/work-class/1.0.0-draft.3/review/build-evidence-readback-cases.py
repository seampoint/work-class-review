#!/usr/bin/env python3
"""Build evidence and readback vectors from WCS2-005 and PROTOCOL.md."""

from __future__ import annotations

import base64
import copy
import json
from typing import Any

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import PIN, deployment, work_class


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def readback_lines(value: Any, path: str = "") -> list[dict[str, str]]:
    if isinstance(value, dict) and value:
        rows = []
        for key, member in value.items():
            rows.extend(readback_lines(member, path + "/" + pointer_token(key)))
        return rows
    if isinstance(value, list) and value:
        rows = []
        for index, member in enumerate(value):
            rows.extend(readback_lines(member, path + "/" + str(index)))
        return rows
    return [{"path": path, "value": canonical_bytes(value).decode("utf-8")}]


def sorted_readback(value: Any) -> list[dict[str, str]]:
    return sorted(readback_lines(value), key=lambda row: row["path"].encode("utf-8"))


def artifact_input(kind: str, value: Any) -> dict[str, str]:
    return {
        "kind": kind,
        "specification_pin": PIN,
        "artifact_bytes_base64": base64.b64encode(canonical_bytes(value)).decode("ascii"),
    }


def evidence_result(profile: str, subject_digest: str, evidence: dict) -> dict[str, str]:
    return {
        "status": "EVIDENCE_VALID",
        "profile": profile,
        "role": "REVIEW_EVIDENCE",
        "subject_digest": subject_digest,
        "evidence_digest": digest("evidence", evidence),
        "specification_pin": PIN,
    }


def evidence_refusal(profile: str, code: str) -> dict[str, str]:
    return {
        "status": "EVIDENCE_INVALID",
        "profile": profile,
        "role": "REVIEW_EVIDENCE",
        "code": code,
        "path": "",
        "specification_pin": PIN,
    }


def review_record(subject_digest: str, status: str = "ACCEPTED", evidence_id: str = "review-1") -> dict:
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": evidence_id,
        "kind": "REVIEW",
        "status": status,
        "subject_digest": subject_digest,
        "reviewer_id": "reviewer-1",
        "paragraph_ids": [],
        "case_ids": [],
        "finding_ids": [],
        "recorded_at": "2026-09-11T00:00:00Z",
        "provenance_digest": digest("evidence-provenance", {"evidence_id": evidence_id}),
    }


def basic_input(profile: str, subject_kind: str, subject_id: str, subject_digest: str, evidence: dict) -> dict:
    return {
        "profile": profile,
        "role": "REVIEW_EVIDENCE",
        "specification_pin": PIN,
        "subject": {
            "kind": subject_kind,
            "subject_id": subject_id,
            "subject_digest": subject_digest,
            "candidate_identity": "seampoint.work-class/1.0.0-draft.3",
            "specification_pin": PIN,
        },
        "evidence": evidence,
    }


def correspondence_input() -> dict:
    definition = work_class("LINEAR")
    definition["shared_budgets"] = ["card-issuance-budget"]
    definition["steps"][0]["shared_budgets"] = ["card-issuance-budget"]
    work_class_digest = digest("work-class-definition", definition)
    paths = [row["path"] for row in sorted_readback(definition)]
    correspondence = {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": "correspondence-1",
        "kind": "CORRESPONDENCE",
        "status": "ACCEPTED",
        "subject_digest": work_class_digest,
        "source_id": definition["source"]["id"],
        "source_revision": definition["source"]["revision"],
        "work_class_digest": work_class_digest,
        "mappings": [
            {
                "source_obligation_id": definition["source"]["obligations"][0],
                "provision_paths": paths,
            }
        ],
        "uncovered_source_obligation_ids": [],
        "unsupported_provision_paths": [],
        "residue": [],
        "review": review_record("sha256:" + "0" * 64, evidence_id="correspondence-review-1"),
        "recorded_at": "2026-09-11T00:00:00Z",
        "provenance_digest": digest("evidence-provenance", {"evidence_id": "correspondence-1"}),
    }
    review_subject = copy.deepcopy(correspondence)
    del review_subject["review"]
    correspondence["review"]["subject_digest"] = digest("correspondence-subject", review_subject)
    return {
        "profile": definition["profile"],
        "role": "REVIEW_EVIDENCE",
        "specification_pin": PIN,
        "subject": {
            "kind": "WORK_CLASS",
            "subject_id": definition["id"],
            "subject_digest": work_class_digest,
            "candidate_identity": "seampoint.work-class/1.0.0-draft.3",
            "specification_pin": PIN,
        },
        "work_class": definition,
        "work_class_digest": work_class_digest,
        "evidence": correspondence,
    }


def rebind_correspondence_review(input_value: dict) -> None:
    subject = copy.deepcopy(input_value["evidence"])
    del subject["review"]
    input_value["evidence"]["review"]["subject_digest"] = digest("correspondence-subject", subject)


def build() -> list[dict]:
    definition = work_class("LINEAR")
    deploy_input, _ = deployment(definition)
    authorization = deploy_input["deployment_authorization"]
    authorization_subject = copy.deepcopy(authorization)
    del authorization_subject["authorization_evidence_digest"]
    authorization_subject_digest = digest("deployment-authorization-subject", authorization_subject)
    accepted_auth = basic_input(
        "LINEAR",
        "AUTHORIZATION",
        authorization["authorization_id"],
        authorization_subject_digest,
        deploy_input["authorization_evidence"],
    )
    cases = [
        exact_case(
            "D2-061",
            "check-evidence",
            accepted_auth,
            evidence_result("LINEAR", authorization_subject_digest, deploy_input["authorization_evidence"]),
            ["WCS2-005", "LIFE-003"],
            "The basic subject and accepted organizational evidence carry the same deployment-authorization-subject digest. The evidence result binds the complete evidence bytes under the evidence domain.",
        )
    ]

    external_subject = digest("review-subject", {"record": "external-1"})
    pending_review = review_record(external_subject, status="PENDING", evidence_id="pending-review-1")
    pending_input = basic_input("LINEAR", "REVIEW", "external-1", external_subject, pending_review)
    cases.append(
        exact_case(
            "D2-062",
            "check-evidence",
            pending_input,
            evidence_refusal("LINEAR", "EVIDENCE_NOT_ACCEPTED"),
            ["WCS2-005"],
            "The review record is structurally admitted and exactly bound, but its status is PENDING. Pending review cannot count as acceptance.",
        )
    )

    boundary = {
        "schema": "seampoint.work-class/1.0.0-draft.3/boundary-record",
        "id": "identity-authentication",
        "candidate_identity": "seampoint.work-class/1.0.0-draft.3",
        "specification_pin": PIN,
        "paragraph_ids": ["WCS2-006:p001"],
        "requirement_ids": ["WCS2-006"],
        "external_fact_or_capability": "The host authenticates asserted actor identities.",
        "responsible_party": {"kind": "DEPLOYER", "party_id": "deployment-owner"},
        "required_control_or_integration": "Bind authenticated identity-provider assertions to submitted records.",
        "evidence_format": "A deployment record naming the identity provider, assertion digest, and verification result.",
        "failure_behavior": "Refuse the dependent operation when authenticated identity evidence is unavailable.",
        "deployment_verification": "Exercise accepted, expired, revoked, and mismatched identity assertions.",
        "establishes": "The boundary and expected host evidence are explicit.",
        "does_not_establish": "The reference consumer has authenticated a real actor.",
        "residual_limitation": "Deployment assurance depends on the selected identity provider and host control.",
    }
    missing_failure = copy.deepcopy(boundary)
    del missing_failure["failure_behavior"]
    cases.append(
        exact_case(
            "D2-063",
            "validate",
            artifact_input("BOUNDARY_RECORD", missing_failure),
            {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
            ["WCS2-007"],
            "The otherwise complete closed boundary record omits its required failure_behavior. The artifact is rejected structurally.",
        )
    )

    readback_definition = correspondence_input()["work_class"]
    cases.append(
        exact_case(
            "D2-064",
            "readback",
            artifact_input("WORK_CLASS", readback_definition),
            {
                "status": "READBACK",
                "digest": digest("work-class-definition", readback_definition),
                "lines": sorted_readback(readback_definition),
            },
            ["WCS2-005", "AGG-009", "LIFE-015"],
            "WCS2-005 emits every scalar and empty collection, sorts complete escaped pointers by raw UTF-8 bytes, and binds the complete work-class definition digest.",
        )
    )

    accepted_review = review_record(external_subject, evidence_id="accepted-review-1")
    malformed = basic_input("LINEAR", "REVIEW", "external-1", external_subject, accepted_review)
    del malformed["specification_pin"]
    cases.append(
        exact_case(
            "D2-117",
            "check-evidence",
            malformed,
            {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
            ["WCS2-012"],
            "The outer check-evidence input omits the required specification_pin, so the generic schema refusal applies before any subject or evidence judgment.",
        )
    )

    correspondence = correspondence_input()
    cases.append(
        exact_case(
            "D2-201",
            "check-evidence",
            correspondence,
            evidence_result("LINEAR", correspondence["work_class_digest"], correspondence["evidence"]),
            ["WCS2-005", "EVD-001"],
            "The one declared source obligation maps to the complete deterministic readback path universe, both residue inventories are empty, and the nested accepted review binds the correspondence-without-review projection.",
        )
    )

    omitted = copy.deepcopy(correspondence)
    omitted["evidence"]["mappings"][0]["provision_paths"] = omitted["evidence"]["mappings"][0]["provision_paths"][:-1]
    rebind_correspondence_review(omitted)
    cases.append(
        exact_case(
            "D2-202",
            "check-evidence",
            omitted,
            evidence_refusal("LINEAR", "BINDING_MISMATCH"),
            ["WCS2-005", "EVD-001"],
            "One exact readback path is removed from both mapped and unsupported inventories while every digest binding is recomputed. The provision universe is incomplete.",
        )
    )

    accepted_basic = basic_input("LINEAR", "REVIEW", "external-1", external_subject, accepted_review)
    cases.append(
        exact_case(
            "D2-203",
            "check-evidence",
            accepted_basic,
            evidence_result("LINEAR", external_subject, accepted_review),
            ["WCS2-005", "EVD-001"],
            "The basic form checks exact subject equality and accepted status. It intentionally supplies no expected scope universe and makes no scope-sufficiency claim.",
        )
    )

    cases.append(
        exact_case(
            "D2-204",
            "readback",
            artifact_input("EVIDENCE_RECORD", accepted_review),
            {
                "status": "READBACK",
                "digest": digest("evidence", accepted_review),
                "lines": sorted_readback(accepted_review),
            },
            ["WCS2-005", "EVD-001"],
            "The accepted review is a closed evidence record. Generic readback emits every operative scalar and empty collection in exact pointer order.",
        )
    )

    overlap = copy.deepcopy(correspondence)
    overlap_path = overlap["evidence"]["mappings"][0]["provision_paths"][0]
    overlap["evidence"]["unsupported_provision_paths"] = [overlap_path]
    overlap["evidence"]["residue"] = [
        {
            "kind": "ARTIFACT_PROVISION",
            "subject": overlap_path,
            "disposition": "UNSUPPORTED",
            "explanation": "The vector deliberately lists this already mapped path as unsupported.",
        }
    ]
    rebind_correspondence_review(overlap)
    cases.append(
        exact_case(
            "D2-211",
            "check-evidence",
            overlap,
            evidence_refusal("LINEAR", "BINDING_MISMATCH"),
            ["WCS2-005", "EVD-001"],
            "The unsupported path has its required residue row and every digest is rebound, but the same path remains in the source mapping. WCS2-005 forbids mapped and unsupported overlap.",
        )
    )

    subject_pin = copy.deepcopy(correspondence)
    subject_pin["subject"]["specification_pin"] = "sha256:" + "1" * 64
    cases.append(
        exact_case(
            "D2-212",
            "check-evidence",
            subject_pin,
            evidence_refusal("LINEAR", "BINDING_MISMATCH"),
            ["WCS2-005", "WCS2-012"],
            "The top-level input, work class, and correspondence still select the candidate, but the exact subject wrapper carries another pin. Subject binding fails.",
        )
    )

    top_pin = copy.deepcopy(correspondence)
    top_pin["specification_pin"] = "sha256:" + "1" * 64
    cases.append(
        exact_case(
            "D2-213",
            "check-evidence",
            top_pin,
            {"status": "REFUSED", "code": "VERSION_UNSUPPORTED", "path": ""},
            ["WCS2-002", "WCS2-013"],
            "Candidate selection precedes correspondence binding. A top-level input pin other than the selected manifest returns the generic VERSION_UNSUPPORTED refusal.",
        )
    )

    pointer_value = {
        "a/b": {"~key": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]},
        "é": True,
    }
    cases.append(
        exact_case(
            "D2-217",
            "property",
            {"kind": "READBACK_POINTER_ORDER", "value": pointer_value},
            {"lines": sorted_readback(pointer_value)},
            ["WCS2-001", "WCS2-005"],
            "This runner-only generic JSON control applies the WCS2-005 readback algorithm directly. It escapes slash as ~1 and tilde as ~0, retains the non-ASCII key, and sorts complete pointer bytes so array position 10 precedes position 2 lexically.",
        )
    )

    profile_mismatch = copy.deepcopy(correspondence)
    profile_mismatch["profile"] = "CHOICE_LOOPS"
    cases.append(
        exact_case(
            "D2-224",
            "check-evidence",
            profile_mismatch,
            evidence_refusal("CHOICE_LOOPS", "BINDING_MISMATCH"),
            ["WCS2-005", "WCS2-012"],
            "CHOICE_LOOPS is admitted, but it differs from the exact LINEAR work-class profile. The correspondence form returns an admitted evidence binding failure.",
        )
    )
    identity_boundary = {
        "schema": "seampoint.work-class/1.0.0-draft.3/boundary-record",
        "id": "actor-identity-authentication",
        "candidate_identity": "seampoint.work-class/1.0.0-draft.3",
        "specification_pin": PIN,
        "paragraph_ids": ["LIFE-007:p-separation-boundary"],
        "requirement_ids": ["HOST-001", "WCS2-006"],
        "external_fact_or_capability": "Distinct actor identifiers supplied to the semantic consumer identify distinct authenticated actors in the deployment domain.",
        "responsible_party": {"kind": "IDENTITY_PROVIDER", "party_id": "deployment-identity-provider"},
        "required_control_or_integration": "Authenticate each actor identifier and prevent two credentials for one actor from satisfying a distinct-actor rule through aliases.",
        "evidence_format": "A deployment identity-assurance record binding each semantic actor identifier to one authenticated principal and recording alias collision checks.",
        "failure_behavior": "Withhold the governed proposal when the host cannot establish distinct authenticated principals for the selected actor identifiers.",
        "deployment_verification": "Test same-principal aliases, distinct principals, expired identity assertions, and identity-provider unavailability.",
        "establishes": "The semantic consumer compares exact actor identifiers and the deployment boundary names the authentication fact needed to rely on that comparison.",
        "does_not_establish": "Different actor identifier strings represent different real people or systems.",
        "residual_limitation": "The strength of separation assurance depends on the deployment's identity proofing, alias controls, and credential lifecycle.",
    }
    cases.append(
        exact_case(
            "D2-292",
            "boundary",
            identity_boundary,
            {
                "status": "CLOSED_DOCUMENTED_BOUNDARY",
                "boundary_digest": digest("boundary", identity_boundary),
                "does_not_establish_external_truth": True,
            },
            ["HOST-001", "WCS2-006"],
            "The closed boundary record assigns identity authentication and alias control to the deployment identity provider, fixes failure behavior and evidence, and expressly withholds any claim that distinct strings prove distinct real actors.",
        )
    )
    return cases


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "evidence-readback" / f"{case['id']}.json", case)
    print(json.dumps({"candidate_pin": PIN, "case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
