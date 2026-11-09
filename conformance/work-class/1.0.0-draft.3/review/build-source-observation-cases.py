#!/usr/bin/env python3
"""Build draft-3 source-observation authority cases from the access-card base."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT / "conformance/work-class/1.0.0-draft.3/specimens/access-card"
CASES = ROOT / "conformance/work-class/1.0.0-draft.3/cases/source-observations"
PREFIX = b"seampoint.work-class/1.0.0-draft.3/"
NOW = "2026-09-10T12:00:00Z"


def canonical(value) -> bytes:
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(canonical(item) for item in value) + b"]"
    if isinstance(value, dict):
        return b"{" + b",".join(
            canonical(key) + b":" + canonical(value[key])
            for key in sorted(value, key=lambda key: key.encode("utf-16-be"))
        ) + b"}"
    raise TypeError(type(value).__name__)


def digest(kind: str, value) -> str:
    return "sha256:" + hashlib.sha256(PREFIX + kind.encode() + b"\n" + canonical(value)).hexdigest()


def typed_field(name: str, type_ref: str, value: str) -> dict:
    return {"name": name, "value": {"type_ref": type_ref, "value": value}}


def source_query(requirement: dict) -> dict:
    return {
        "requirement_id": requirement["id"],
        "step": requirement["step"],
        "at": requirement["at"],
        "provider": requirement["provider"],
        "source": requirement["source"],
        "record_type": requirement["record_type"],
        "subject": requirement["subject"],
        "record_id": requirement["record_id"],
        "purpose": requirement["purpose"],
        "freshness_seconds": requirement["freshness_seconds"],
        "expected_status": requirement["expected_status"],
        "fields": requirement["fields"],
        "relations": requirement["relations"],
    }


def source_observation(requirement: dict, *, status: str = "AVAILABLE", as_of: str | None = NOW,
                       record_id: str = "session-1", query: dict | None = None) -> dict:
    query = copy.deepcopy(query or source_query(requirement))
    query_digest = digest("authority-query", query)
    available = status == "AVAILABLE"
    complete = status in {"AVAILABLE", "ABSENT"}
    observation = {
        "query": query,
        "query_digest": query_digest,
        "status": status,
        "as_of": as_of if complete else None,
        "revision": "session-revision-1" if complete else None,
        "fields": [typed_field(field["name"], field["type_ref"], "employee-7") for field in requirement["fields"]] if available else [],
        "relations": [],
        "evidence_ref": "session-observation-evidence",
        "provenance_digest": digest("source-observation-provenance", {
            "query_digest": query_digest,
            "provider_record_id": record_id,
        }),
    }
    if status == "ABSENT":
        observation["coverage"] = "COMPLETE"
    if available:
        observation["provider_record_id"] = record_id
    return observation


def replace_digests(value, replacements):
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [replace_digests(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: replace_digests(item, replacements) for key, item in value.items()}
    return value


def prepare_base() -> tuple[dict, dict, dict]:
    request = json.loads((BASE / "authority-input.json").read_text())
    base_result = json.loads((BASE / "authority-result-derived.json").read_text())
    requirement = {
        "id": "session-observation",
        "step": "issue-card",
        "purpose": "AUTHENTICATED_SESSION",
        "provider": "identity-provider",
        "source": "authenticated-sessions",
        "record_type": "authenticated-session",
        "subject": "card-issuer-machine",
        "record_id": "session-1",
        "at": NOW,
        "freshness_seconds": "60",
        "expected_status": "AVAILABLE",
        "fields": [{"name": "session_actor", "type_ref": "t.identity"}],
        "relations": [],
    }
    request["envelope"] = copy.deepcopy(request["envelope"])
    request["envelope"]["source_observation_requirements"] = [requirement]

    old_envelope_digest = digest("authority-envelope", json.loads((BASE / "authority-input.json").read_text())["envelope"])
    old_root = request["host_selection"]["root"]
    old_root_digest = digest("authority-root", old_root)
    old_capacity_digests = {row["id"]: digest("authority-capacity", row) for row in request["capacities"]}
    old_act_digests = {row["id"]: digest("authority-act", row) for row in request["acts"]}

    new_envelope_digest = digest("authority-envelope", request["envelope"])
    old_root["envelope_digest"] = new_envelope_digest
    new_root_digest = digest("authority-root", old_root)
    for capacity in request["capacities"]:
        capacity["root_digest"] = new_root_digest
        capacity["envelope_digest"] = new_envelope_digest

    acts_by_id = {row["id"]: row for row in request["acts"]}
    acts_by_id["grant-card-issuance"]["subject_digest"] = new_envelope_digest
    grant_digest = digest("authority-act", acts_by_id["grant-card-issuance"])
    acts_by_id["attest-card-grant"]["subject_digest"] = grant_digest
    request["acts"] = sorted(acts_by_id.values(), key=lambda row: digest("authority-act", row).encode("utf-8"))
    new_act_digests = {row["id"]: digest("authority-act", row) for row in request["acts"]}

    returns_by_id = {row["id"]: row for row in request["returns"]}
    for act in request["acts"]:
        returned = next(row for row in returns_by_id.values() if row["act_digest"] == old_act_digests[act["id"]])
        returned["act_digest"] = new_act_digests[act["id"]]
        returned["act_bytes_base64"] = base64.b64encode(canonical(act)).decode("ascii")

    replacements = {
        old_envelope_digest: new_envelope_digest,
        old_root_digest: new_root_digest,
        **{old_capacity_digests[key]: digest("authority-capacity", next(row for row in request["capacities"] if row["id"] == key)) for key in old_capacity_digests},
    }
    for observation in request["observations"]:
        query = observation["query"]
        if query["purpose"] == "REVOCATION":
            old_query_digest = observation["query_digest"]
            query["subject_digest"] = replacements.get(query["subject_digest"], query["subject_digest"])
            observation["query_digest"] = digest("authority-query", query)
            replacements[old_query_digest] = observation["query_digest"]

    authenticated = []
    for occupancy in request["occupancies"]:
        authenticated.append({"kind": "OCCUPANCY", "record_digest": digest("authority-occupancy", occupancy), "provider": occupancy["provider"], "channel": None})
    for capacity in request["capacities"]:
        authenticated.append({"kind": "CAPACITY", "record_digest": digest("authority-capacity", capacity), "provider": capacity["provider"], "channel": None})
    for credential in request["credentials"]:
        authenticated.append({"kind": "CREDENTIAL", "record_digest": digest("authority-credential", credential), "provider": credential["provider"], "channel": None})
    for returned in request["returns"]:
        authenticated.append({"kind": "RETURN", "record_digest": digest("authority-return", returned), "provider": returned["provider"], "channel": returned["channel"]})
    request["host_selection"]["authenticated_records"] = sorted(authenticated, key=canonical)

    replacements.update(old_act_digests)
    replacements.update({old_act_digests[key]: new_act_digests[key] for key in old_act_digests})
    return request, base_result, {
        "envelope": new_envelope_digest,
        "root": new_root_digest,
        "capacity": {row["id"]: digest("authority-capacity", row) for row in request["capacities"]},
        "act": new_act_digests,
        "old_envelope": old_envelope_digest,
        "old_root": old_root_digest,
        "old_capacity": old_capacity_digests,
        "old_act": old_act_digests,
        "replacements": replacements,
    }


def expected_ready(request: dict, base_result: dict, identities: dict, requirement: dict) -> dict:
    old_operation = base_result["operation_digest"]
    proposal_digest = base_result["proposal_digest"]
    work_class_digest = base_result["work_class_digest"]
    new_operation = digest("authority-operation", {
        "envelope_digest": identities["envelope"],
        "work_class_digest": work_class_digest,
        "proposal_digest": proposal_digest,
    })
    replacements = dict(identities["replacements"])
    replacements[old_operation] = new_operation
    result = replace_digests(base_result, replacements)
    result["envelope_digest"] = identities["envelope"]
    result["operation_digest"] = new_operation
    result["act_digests"] = sorted(identities["act"].values(), key=lambda value: value.encode("utf-8"))
    result["checks"].append({
        "purpose": "SOURCE_OBSERVATION",
        "subject_digest": identities["envelope"],
        "requirement_ref": requirement["id"],
        "at": requirement["at"],
    })
    result["checks"] = sorted({canonical(row): row for row in result["checks"]}.values(), key=canonical)
    evidence = {key: request[key] for key in ("host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock")}
    result["evidence_digest"] = digest("authority-evidence", evidence)
    return result


def refused(code: str, identities: dict, requirement: dict, reason: str | None = None) -> dict:
    failed = []
    reasons = []
    if reason:
        reasons = [reason]
        failed = [{
            "purpose": "SOURCE_OBSERVATION",
            "subject_digest": identities["envelope"],
            "requirement_ref": requirement["id"],
            "at": requirement["at"],
            "reason": reason,
        }]
    return {"status": "REFUSED", "code": code, "path": "", "reasons": reasons, "failed_checks": sorted(failed, key=canonical)}


def make_case(case_id: str, request: dict, expected: dict, derivation: str) -> dict:
    return {
        "id": case_id,
        "operation": "evaluate",
        "input": {"kind": "AUTHORITY", "request": request},
        "expected": expected,
        "requirements": ["AUTH-007"],
        "derivation": derivation,
    }


def main() -> None:
    request, base_result, identities = prepare_base()
    requirement = request["envelope"]["source_observation_requirements"][0]
    valid = source_observation(requirement)

    variants = {
        "C3-001": ([valid], expected_ready({**request, "observations": request["observations"] + [valid]}, base_result, identities, requirement), "The exact declared source query has one fresh available record with the required typed field and no relations. Authority is ready, and the source observation appears in the successful checks and evidence digest."),
        "C3-002": ([source_observation(requirement, status="ABSENT")], refused("AUTHORITY_NOT_ESTABLISHED", identities, requirement, "SOURCE_OBSERVATION_BINDING"), "The provider answered the exact query with ABSENT. The evaluator retains that distinct status and withholds authority."),
        "C3-003": ([source_observation(requirement, status="UNAVAILABLE")], refused("AUTHORITY_NOT_ESTABLISHED", identities, requirement, "SOURCE_OBSERVATION_UNAVAILABLE"), "The provider did not make a usable answer available. UNAVAILABLE is not treated as ABSENT or as a satisfied observation."),
        "C3-004": ([], refused("EVIDENCE_UNAVAILABLE", identities, requirement), "The declared query has no observation. Missing source evidence is an admission failure before policy evaluation produces a result."),
        "C3-005": ([source_observation(requirement, as_of="2026-09-10T11:58:00Z")], refused("AUTHORITY_NOT_ESTABLISHED", identities, requirement, "SOURCE_OBSERVATION_STALE"), "The available record is older than the declared 60-second freshness bound at the exact evaluation instant."),
        "C3-006": ([source_observation(requirement, query={**source_query(requirement), "record_id": "other-session"})], refused("DEPENDENCY_MISMATCH", identities, requirement), "A record for a substituted query is rejected as a dependency mismatch, even though its provider and shape are otherwise valid."),
        "C3-007": ([valid, source_observation(requirement, record_id="session-record-2")], refused("AUTHORITY_NOT_ESTABLISHED", identities, requirement, "SOURCE_OBSERVATION_CONFLICT"), "Two distinct available records answer the same declared query. The evaluator retains the conflict and withholds authority."),
    }
    for case_id, (source_rows, expected, derivation) in variants.items():
        case_request = copy.deepcopy(request)
        case_request["observations"] = copy.deepcopy(request["observations"]) + copy.deepcopy(source_rows)
        if case_id == "C3-001":
            expected = expected_ready(case_request, base_result, identities, requirement)
        path = CASES / f"{case_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical(make_case(case_id, case_request, expected, derivation)) + b"\n")
    print(json.dumps({"cases": len(variants), "path": str(CASES)}, indent=2))


if __name__ == "__main__":
    main()
