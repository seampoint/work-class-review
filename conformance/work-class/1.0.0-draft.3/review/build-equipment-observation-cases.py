"""Derive exact direct-authority observation vectors before running either consumer."""

from __future__ import annotations

import copy
from typing import Any

from authority_fixture import authority_refusal
from corpus_common import CASES, digest, exact_case, write_canonical_json
from equipment_observation_fixture import (
    expected_ready, observation, relation, requirement, source_check,
    source_fixture, source_refusal, typed,
)


GROUP = CASES / "equipment-observations"


def source_rows(request: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in request["observations"] if row["query"]["purpose"] != "REVOCATION"]


def source_row(request: dict[str, Any], requirement_id: str = "current-session") -> dict[str, Any]:
    return next(row for row in source_rows(request) if row["query"]["requirement_id"] == requirement_id)


def rebuild_sources(request: dict[str, Any], values: dict[str, dict[str, Any]] | None = None) -> None:
    request["observations"] = [row for row in request["observations"] if row["query"]["purpose"] == "REVOCATION"]
    request["observations"].extend(observation(req, request, values=(values or {}).get(req["id"]))
        for req in request["envelope"]["source_observation_requirements"])


def rich_mutator(request: dict[str, Any], _original: dict[str, Any]) -> None:
    req = next(row for row in request["envelope"]["source_observation_requirements"] if row["id"] == "current-session")
    executor = request["proposal"]["executor"]
    grant = next(row for row in request["acts"] if row["kind"] == "GRANT")
    fields = {"beneficiary": "IDENTITY", "clock_at": "INSTANT", "enabled": "BOOLEAN", "linked_approval": "IDENTITY"}
    values = {"beneficiary": "employee-7", "clock_at": request["clock"]["instant"], "enabled": True, "linked_approval": "grant-1"}
    relations = [
        relation("approval-id", "EQUALS", "linked_approval", {"kind": "OBSERVATION_ID", "requirement_id": "approval", "type_ref": "IDENTITY"}),
        relation("beneficiary", "EQUALS", "beneficiary", {"kind": "PROPOSAL_FIELD", "field": "beneficiary"}),
        relation("beneficiary-distinct", "NOT_EQUALS", "beneficiary", {"kind": "EXECUTOR", "member": "actor", "type_ref": "IDENTITY"}),
        relation("clock", "EQUALS", "clock_at", {"kind": "CLOCK", "type_ref": "INSTANT"}),
        relation("enabled", "EQUALS", "enabled", {"kind": "LITERAL", "value": typed("BOOLEAN", True)}),
    ]
    for member in ("actor", "occupancy", "principal", "role"):
        field = "executor_" + member
        fields[field] = "IDENTITY"
        values[field] = executor[member]
        relations.append(relation(field, "EQUALS", field, {"kind": "EXECUTOR", "member": member, "type_ref": "IDENTITY"}))
    for member in ("actor", "id", "occurred_at", "principal", "role"):
        field = "grant_" + member
        type_ref = "INSTANT" if member == "occurred_at" else "IDENTITY"
        fields[field] = type_ref
        values[field] = grant[member]
        relations.append(relation(field, "EQUALS", field, {"kind": "ACT", "act_kind": "GRANT", "member": member, "type_ref": type_ref}))
    approval_time = {"kind": "OBSERVATION_FIELD", "requirement_id": "approval", "field": "signed_at"}
    relations.extend([
        relation("grant-after", "AFTER", "clock_at", "grant_occurred_at"),
        relation("grant-before", "BEFORE", "grant_occurred_at", "clock_at"),
        relation("inclusive-lower", "AT_OR_AFTER", "grant_occurred_at", approval_time),
        relation("inclusive-upper", "AT_OR_BEFORE", "grant_occurred_at", approval_time),
    ])
    req["fields"] = [{"name": name, "type_ref": fields[name]} for name in sorted(fields)]
    req["relations"] = sorted(relations, key=lambda row: row["id"].encode("utf-8"))
    req["key_projection"] = [
        {"field": "card_id", "type_ref": "IDENTITY", "key_field": "asset_id"},
        {"field": "beneficiary", "type_ref": "IDENTITY", "key_field": "owner_id"},
    ]
    approval = next(row for row in request["envelope"]["source_observation_requirements"] if row["id"] == "approval")
    approval["subject"] = {"kind": "PROPOSAL_FIELD", "field": "beneficiary"}
    rebuild_sources(request, {"current-session": values})


def point_mutator(request: dict[str, Any], _original: dict[str, Any]) -> None:
    historical = requirement("proposal-only", at="2026-09-08T10:00:00Z", subject="person-grantor", record_id="historical-session")
    historical.pop("evaluation_point")
    request["envelope"]["source_observation_requirements"].append(historical)
    request["envelope"]["source_observation_requirements"].sort(key=lambda row: row["id"].encode("utf-8"))
    rebuild_sources(request)


def derived_cases() -> list[dict[str, Any]]:
    cases = []

    def add(number: int, request: dict[str, Any], expected: dict[str, Any], derivation: str) -> None:
        cases.append(exact_case(f"C3-EO-{number:03d}", "evaluate", {"kind": "AUTHORITY", "request": request},
            expected, ["AUTH-007", "AUTH-006"], derivation))

    request, expected = source_fixture(gated=True, mutator=rich_mutator)
    add(1, request, expected, "All declared selectors resolve actual values: every executor identity, selected GRANT id/actor/role/principal/time, proposal beneficiary, available observation identity and field, current CLOCK and typed literal. Strict temporal relations and inclusive equal boundaries succeed. Query subject resolves a proposal field, while the session subject resolves the executor. Named query-key fields are asset_id then owner_id; no synthetic field enters the native proposal.")

    def legacy_subject(request: dict[str, Any], _original: dict[str, Any]) -> None:
        req = request["envelope"]["source_observation_requirements"][0]
        req["subject"] = "card-machine"
        req.pop("evaluation_point")
        rebuild_sources(request)
    request, expected = source_fixture(mutator=legacy_subject)
    add(2, request, expected, "Omitted input and requirement evaluation points mean PROPOSE. A fixed subject retains its exact string, and no default evaluation_point property is inserted into the resolved query or evidence preimage.")

    request, expected = source_fixture(evaluation_point="PROPOSE")
    add(3, request, expected, "Explicit PROPOSE selects the source requirement and adds only the explicitly present evaluation_point member to the eight-member authority-evidence preimage.")

    request, expected = source_fixture(gated=True)
    add(4, request, expected, "The selected approval is AVAILABLE at its exact grant-1 record identity. Approval and both policy withdrawal queries are complete ABSENT with current time, provider revisions, COMPLETE coverage and empty values. Readiness alone still grants no send.")

    request, _ = source_fixture()
    source_row(request)["provider_record_id"] = "different-session"
    add(5, request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_BINDING"), "An otherwise usable source response answers the exact query but names the wrong requested provider record. Only the binding check fails.")

    request, _ = source_fixture()
    req = request["envelope"]["source_observation_requirements"][0]
    request["observations"].remove(source_row(request))
    request["observations"].append(observation(req, request, status="ABSENT"))
    add(6, request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_BINDING"), "A complete ABSENT answer with time, revision and coverage cannot satisfy an AVAILABLE requirement. Status mismatch uses SOURCE_OBSERVATION_BINDING, without treating absence as unavailable evidence.")

    request, _ = source_fixture(gated=True)
    req = next(row for row in request["envelope"]["source_observation_requirements"] if row["id"] == "approval-withdrawal")
    request["observations"].remove(source_row(request, req["id"]))
    request["observations"].append(observation(req, request, status="AVAILABLE", record_id="withdrawal-record"))
    add(7, request, source_refusal(request, req["id"], "SOURCE_OBSERVATION_BINDING"), "An existing withdrawal record answers an expected ABSENT query. Its shape is usable and its empty field declaration matches; the expected-status binding fails.")

    def inclusive(request: dict[str, Any], _original: dict[str, Any]) -> None:
        req = request["envelope"]["source_observation_requirements"][0]
        req["fields"] = [{"name": "boundary", "type_ref": "INSTANT"}]
        req["relations"] = [relation("inclusive-boundary", "AT_OR_AFTER", "boundary", {"kind": "CLOCK", "type_ref": "INSTANT"})]
        rebuild_sources(request, {req["id"]: {"boundary": "2026-09-10T04:29:59Z"}})
    request, _ = source_fixture(mutator=inclusive)
    add(8, request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_RELATIONS"), "The typed boundary is one second before CLOCK, so AT_OR_AFTER is false. The source observation itself is current and usable; its copied relation declaration is not proof.")

    request, _ = source_fixture()
    source_row(request)["relations"] = []
    add(9, request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_RELATIONS"), "The actual Boolean value is true but the response omits the required copied relation declaration. Declaration mismatch fails relations independently of the value.")

    def invalid_instant(request: dict[str, Any], _original: dict[str, Any]) -> None:
        req = request["envelope"]["source_observation_requirements"][0]
        req["fields"] = [{"name": "boundary", "type_ref": "INSTANT"}]
        req["relations"] = []
        rebuild_sources(request, {req["id"]: {"boundary": "2026-02-30T00:00:00Z"}})
    request, _ = source_fixture(mutator=invalid_instant)
    add(10, request, authority_refusal([], code="TYPE_INVALID"), "A known nominal INSTANT value has an impossible calendar date. Typed scalar admission refuses before source-policy evaluation.")

    request, expected = source_fixture(mutator=point_mutator, evaluation_point="DISPATCH")
    add(11, request, expected, "DISPATCH selects the current PROPOSE_AND_DISPATCH requirement and excludes the fixed historical requirement whose point was omitted. Ordinary current and historical revocation checks still run, and the retained evidence includes the explicit DISPATCH member.")

    request, _ = source_fixture(mutator=point_mutator, evaluation_point="DISPATCH")
    req = next(row for row in request["envelope"]["source_observation_requirements"] if row["id"] == "proposal-only")
    request["observations"].append(observation(req, request))
    add(12, request, authority_refusal([], code="DEPENDENCY_MISMATCH"), "A PROPOSE-only source observation is unrequested at DISPATCH. Keeping it from an earlier proposal is an extra-query dependency fault.")

    def cross_phase(request: dict[str, Any], original: dict[str, Any]) -> None:
        point_mutator(request, original)
        req = next(row for row in request["envelope"]["source_observation_requirements"] if row["id"] == "current-session")
        req["relations"] = [relation("cross-phase", "EQUALS", "enabled", {"kind": "OBSERVATION_FIELD", "requirement_id": "proposal-only", "field": "enabled"})]
        rebuild_sources(request)
    request, _ = source_fixture(mutator=cross_phase)
    add(13, request, authority_refusal([], code="UNSUPPORTED_RELATION"), "A requirement selected at DISPATCH depends on a PROPOSE-only observation. Static admission rejects the phase dependency even while evaluating a proposal with both rows present.")

    def cyclic(request: dict[str, Any], _original: dict[str, Any]) -> None:
        first = request["envelope"]["source_observation_requirements"][0]
        second = requirement("second-session", record_id="session-2")
        first["relations"] = [relation("edge-second", "EQUALS", "enabled", {"kind": "OBSERVATION_FIELD", "requirement_id": second["id"], "field": "enabled"})]
        second["relations"] = [relation("edge-first", "EQUALS", "enabled", {"kind": "OBSERVATION_FIELD", "requirement_id": first["id"], "field": "enabled"})]
        request["envelope"]["source_observation_requirements"].append(second)
        rebuild_sources(request)
    request, _ = source_fixture(mutator=cyclic)
    add(14, request, authority_refusal([], code="INPUT_INVALID"), "Two otherwise typed same-step AVAILABLE requirements form a dependency cycle. Cycle admission refuses before policy comparisons.")

    def unknown_field(request: dict[str, Any], _original: dict[str, Any]) -> None:
        req = request["envelope"]["source_observation_requirements"][0]
        req["relations"][0]["left"] = "undeclared-field"
        rebuild_sources(request)
    request, _ = source_fixture(mutator=unknown_field)
    add(15, request, authority_refusal([], code="REFERENCE_INVALID"), "An inherited local-field operand names no declared source field. Exact dependency digests were rebound before deriving this static reference refusal.")

    def incompatible_type(request: dict[str, Any], _original: dict[str, Any]) -> None:
        req = request["envelope"]["source_observation_requirements"][0]
        req["relations"][0]["right"] = {"kind": "LITERAL", "value": typed("IDENTITY", "true")}
        rebuild_sources(request)
    request, _ = source_fixture(mutator=incompatible_type)
    add(16, request, authority_refusal([], code="TYPE_INVALID"), "The Boolean source field and valid IDENTITY literal have different nominal types. EQUALS rejects their static operand compatibility; spelling true does not coerce an identity into a Boolean.")

    request, _ = source_fixture()
    request["observations"].remove(source_row(request))
    add(17, request, authority_refusal([], code="EVIDENCE_UNAVAILABLE"), "The source query has no response, while every ordinary revocation query remains supplied. Missing source evidence is an admission refusal.")

    request, _ = source_fixture()
    source_row(request)["query"]["record_id"] = "substituted-query"
    source_row(request)["query_digest"] = digest("authority-query", source_row(request)["query"])
    add(18, request, authority_refusal([], code="DEPENDENCY_MISMATCH"), "A substituted but internally rehashed query leaves the required query missing and supplies an extra query. DEPENDENCY_MISMATCH precedes EVIDENCE_UNAVAILABLE.")

    request, _ = source_fixture()
    contradictory = copy.deepcopy(source_row(request))
    contradictory["revision"] = "second-opaque-revision"
    contradictory["evidence_ref"] = "independent-source-answer"
    request["observations"].append(contradictory)
    add(19, request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_CONFLICT"), "Two distinct rows answer the same exact query and each independently has matching record, values and time. The group contributes only a conflict check; opaque revision spelling selects no winner.")

    request, base_expected = source_fixture()
    request["observations"].append(copy.deepcopy(source_row(request)))
    add(20, request, expected_ready(request, base_expected), "An exact canonical duplicate source row collapses for policy and check construction. The complete supplied observation array remains committed by the authority-evidence preimage.")

    for number, status, reason in (
        (21, "UNAVAILABLE", "SOURCE_OBSERVATION_UNAVAILABLE"),
        (22, "INCOMPLETE", "SOURCE_OBSERVATION_INCOMPLETE"),
        (24, "ROLLED_BACK", "SOURCE_OBSERVATION_ROLLED_BACK"),
    ):
        request, _ = source_fixture()
        req = request["envelope"]["source_observation_requirements"][0]
        request["observations"].remove(source_row(request))
        request["observations"].append(observation(req, request, status=status))
        add(number, request, source_refusal(request, req["id"], reason), f"An attributable {status} response has null time/revision and no usable values. Its exact status withholds the declared source fact; it cannot establish complete absence.")

    request, _ = source_fixture()
    source_row(request)["as_of"] = "2026-09-10T04:29:59Z"
    add(23, request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_STALE"), "The response is one second old under the zero-second freshness requirement. Time ordering remains valid, so only staleness contributes a failed check.")

    request, _ = source_fixture(gated=True, mutator=rich_mutator)
    req = next(row for row in request["envelope"]["source_observation_requirements"] if row["id"] == "approval")
    request["observations"].remove(source_row(request, "approval"))
    request["observations"].append(observation(req, request, status="UNAVAILABLE"))
    add(25, request, authority_refusal([
        source_check(request, "approval", "SOURCE_OBSERVATION_UNAVAILABLE"),
        source_check(request, "current-session", "SOURCE_OBSERVATION_RELATIONS"),
    ]), "The required approval row is present but unusable. Its own unavailability and the dependent session's unprovable observation identity/field relations both appear, canonically sorted and deduplicated; the dependency supplies no default value.")

    request, _ = source_fixture()
    source_row(request)["fields"].append({"name": "undeclared-extra", "value": typed("IDENTITY", "extra")})
    add(26, request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_FIELDS"), "An extra valid typed field changes the required actual field inventory. The declared enabled field and its copied/actual relation remain true, so only the field-inventory check fails.")

    request, _ = source_fixture()
    source_row(request)["as_of"] = "2026-09-10T04:30:01Z"
    add(27, request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_TIME"), "The source response is one second later than its exact query instant. The raw calendar is valid; the policy time relation fails without producing staleness.")

    request, _ = source_fixture()
    source_row(request)["query_digest"] = "sha256:" + "0" * 64
    add(28, request, authority_refusal([], code="DEPENDENCY_MISMATCH"), "The exact query body remains declared but its supplied digest is forged. Query digest admission refuses before the otherwise true source Boolean can be interpreted.")

    def unsupported_includes(request: dict[str, Any], _original: dict[str, Any]) -> None:
        req = request["envelope"]["source_observation_requirements"][0]
        req["relations"][0]["kind"] = "INCLUDES"
        rebuild_sources(request)
    request, _ = source_fixture(mutator=unsupported_includes)
    add(29, request, authority_refusal([], code="UNSUPPORTED_RELATION"), "INCLUDES remains a transport-admissible relation spelling but has no supported collection operand in this slice. Static admission refuses before policy.")

    request, _ = source_fixture()
    request["clock"]["status"] = "UNAVAILABLE"
    request["clock"]["instant"] = None
    request["observations"] = []
    add(30, request, authority_refusal([], reasons=["CLOCK_UNAVAILABLE"]), "The admitted current clock is unavailable and no observations are supplied. After directly checkable admission, CLOCK_UNAVAILABLE precedes unresolved CLOCK queries and missing evidence; failed_checks stays empty.")

    return sorted(cases, key=lambda row: row["id"].encode("utf-8"))


def main() -> None:
    cases = derived_cases()
    for case in cases:
        write_canonical_json(GROUP / (case["id"] + ".json"), case)
    print(f"Derived {len(cases)} exact observation cases in {GROUP}")


if __name__ == "__main__":
    main()
