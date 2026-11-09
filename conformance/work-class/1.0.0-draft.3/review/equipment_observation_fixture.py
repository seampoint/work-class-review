"""Synthetic observation facts and normative digest constructors, without a consumer."""

from __future__ import annotations

import copy
from typing import Any, Callable

from authority_fixture import authority_refusal, authority_specimen, canonical_sort
from corpus_common import digest


QUERY_MEMBERS = (
    "step", "at", "provider", "source", "record_type", "subject", "record_id",
    "purpose", "freshness_seconds", "expected_status", "fields", "relations",
)
EVIDENCE_MEMBERS = (
    "host_selection", "occupancies", "capacities", "credentials", "acts",
    "returns", "observations", "clock",
)
GATE_IDS = ("approval", "approval-withdrawal", "policy-dr-withdrawal", "policy-mcs-withdrawal")


def typed(type_ref: str, value: Any) -> dict[str, Any]:
    return {"type_ref": type_ref, "value": value}


def relation(relation_id: str, kind: str, left: Any, right: Any) -> dict[str, Any]:
    return {"id": relation_id, "kind": kind, "left": left, "right": right}


def requirement(requirement_id: str = "current-session", **overrides: Any) -> dict[str, Any]:
    result = {
        "id": requirement_id,
        "step": "issue",
        "purpose": "AUTHENTICATED_SESSION",
        "provider": "identity-provider",
        "source": "equipment-synthetic-sessions",
        "record_type": "authenticated-session",
        "subject": {"kind": "EXECUTOR", "member": "actor", "type_ref": "IDENTITY"},
        "record_id": "session-1",
        "at": "CLOCK",
        "freshness_seconds": "0",
        "expected_status": "AVAILABLE",
        "fields": [{"name": "enabled", "type_ref": "BOOLEAN"}],
        "relations": [relation("session-enabled", "EQUALS", "enabled", {
            "kind": "LITERAL", "value": typed("BOOLEAN", True),
        })],
        "evaluation_point": "PROPOSE_AND_DISPATCH",
    }
    result.update(copy.deepcopy(overrides))
    return result


def source_query(req: dict[str, Any], authority_input: dict[str, Any]) -> dict[str, Any]:
    query = {"requirement_id": req["id"], **{key: copy.deepcopy(req[key]) for key in QUERY_MEMBERS}}
    if req["at"] == "CLOCK":
        query["at"] = authority_input["clock"]["instant"]
    subject = req["subject"]
    if isinstance(subject, dict):
        if subject["kind"] == "PROPOSAL_FIELD":
            query["subject"] = next(row["value"]["value"] for row in authority_input["proposal"]["fields"] if row["name"] == subject["field"])
        else:
            query["subject"] = authority_input["proposal"]["executor"][subject["member"]]
    if "evaluation_point" in req:
        query["evaluation_point"] = req["evaluation_point"]
    if "key_projection" in req:
        fields = {row["name"]: row["value"] for row in authority_input["proposal"]["fields"]}
        query["key"] = sorted([
            {"name": row.get("key_field", row["field"]), "value": copy.deepcopy(fields[row["field"]])}
            for row in req["key_projection"]
        ], key=lambda row: row["name"].encode("utf-8"))
    return query


def selected_requirements(authority_input: dict[str, Any]) -> list[dict[str, Any]]:
    point = authority_input.get("evaluation_point", "PROPOSE")
    return [
        row for row in authority_input["envelope"].get("source_observation_requirements", [])
        if row["step"] == authority_input["proposal"]["step"]
        and (point == "PROPOSE" or row.get("evaluation_point", "PROPOSE") == "PROPOSE_AND_DISPATCH")
    ]


def observation(
    req: dict[str, Any],
    authority_input: dict[str, Any],
    *,
    values: dict[str, Any] | None = None,
    status: str | None = None,
    record_id: str | None = None,
    as_of: str | None = None,
    revision: str | None = None,
    relations: list[dict[str, Any]] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exact_query = copy.deepcopy(query if query is not None else source_query(req, authority_input))
    selected_status = status if status is not None else req["expected_status"]
    usable = selected_status in {"AVAILABLE", "ABSENT"}
    selected_revision = (revision or req["id"] + "-revision-1") if usable else None
    selected_id = record_id if record_id is not None else req["record_id"] or req["id"] + "-record-1"
    grant = next(row for row in authority_input["acts"] if row["kind"] == "GRANT")
    defaults = {
        "enabled": True,
        "approval_actor": grant["actor"],
        "approval_id": grant["id"],
        "approval_role": grant["role"],
        "signed_at": grant["occurred_at"],
    }
    defaults.update(values or {})
    field_rows = []
    if selected_status == "AVAILABLE":
        for field in req["fields"]:
            value = defaults[field["name"]]
            field_rows.append({"name": field["name"], "value": copy.deepcopy(value if isinstance(value, dict) else typed(field["type_ref"], value))})
    query_digest = digest("authority-query", exact_query)
    result = {
        "query": exact_query,
        "query_digest": query_digest,
        "status": selected_status,
        "as_of": (as_of if as_of is not None else exact_query["at"]) if usable else None,
        "revision": selected_revision,
        "fields": field_rows,
        "relations": copy.deepcopy(req["relations"] if relations is None else relations) if selected_status == "AVAILABLE" else [],
        "evidence_ref": "synthetic-observation-" + req["id"],
        "provenance_digest": digest("source-observation-provenance", {
            "query_digest": query_digest, "status": selected_status,
            "record_id": selected_id if selected_status == "AVAILABLE" else None,
            "revision": selected_revision,
        }),
    }
    if selected_status == "AVAILABLE":
        result["provider_record_id"] = selected_id
    elif selected_status == "ABSENT":
        result["coverage"] = "COMPLETE"
    return result


def _configure(authority_input: dict[str, Any], *, gated: bool, include_session: bool) -> None:
    step = next(row for row in authority_input["work_class"]["steps"] if row["id"] == authority_input["proposal"]["step"])
    step["authority_type_refs"] = ["BOOLEAN", "INSTANT"]
    types = authority_input["work_class"]["types"]
    for type_id, kind in (("BOOLEAN", "BOOLEAN"), ("INSTANT", "INSTANT")):
        if not any(row["id"] == type_id for row in types):
            types.append({"id": type_id, "kind": kind, "nonnegative": False, "unit": None})
    types.sort(key=lambda row: row["id"].encode("utf-8"))
    requirements = [requirement()] if include_session else []
    if gated:
        step["dispatch_gate"] = {
            "approval_requirement": "approval",
            "withdrawal_requirement": "approval-withdrawal",
            "policy_withdrawal_requirements": ["policy-dr-withdrawal", "policy-mcs-withdrawal"],
            "fence_provider": "identity-provider",
            "fence_source": "equipment-synthetic-conditional-write",
            "authorization_seconds": "60",
        }
        fields = [{"name": name, "type_ref": type_ref} for name, type_ref in (
            ("approval_actor", "IDENTITY"), ("approval_id", "IDENTITY"),
            ("approval_role", "IDENTITY"), ("signed_at", "INSTANT"),
        )]
        relations = [relation("grant-" + member, "EQUALS", field, {
            "kind": "ACT", "act_kind": "GRANT", "member": member, "type_ref": type_ref,
        }) for field, member, type_ref in (
            ("approval_actor", "actor", "IDENTITY"), ("approval_id", "id", "IDENTITY"),
            ("approval_role", "role", "IDENTITY"), ("signed_at", "occurred_at", "INSTANT"),
        )]
        requirements.append(requirement("approval", purpose="AUTHORITY", source="equipment-synthetic-approvals",
            record_type="approval", subject="access-card-owner", record_id="grant-1", fields=fields,
            relations=sorted(relations, key=lambda row: row["id"].encode("utf-8"))))
        for requirement_id in GATE_IDS[1:]:
            requirements.append(requirement(requirement_id, purpose="AUTHORITY", source="equipment-synthetic-" + requirement_id,
                record_type="withdrawal", subject="access-card-owner", record_id=None,
                expected_status="ABSENT", fields=[], relations=[]))
    authority_input["envelope"]["source_observation_requirements"] = sorted(requirements, key=lambda row: row["id"].encode("utf-8"))
    authority_input["observations"].extend(observation(row, authority_input) for row in requirements)


def authority_mutator(authority_input: dict[str, Any], _original: dict[str, Any], *, include_session: bool = True) -> None:
    """Install the synthetic dispatch gate before authority_specimen rebinds dependencies."""
    _configure(authority_input, gated=True, include_session=include_session)


def source_fixture(
    gated: bool = False,
    *,
    mutator: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    evaluation_point: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    def configure(authority_input: dict[str, Any], original: dict[str, Any]) -> None:
        _configure(authority_input, gated=gated, include_session=True)
        if mutator is not None:
            mutator(authority_input, original)
        if evaluation_point is not None:
            authority_input["evaluation_point"] = evaluation_point
        selected = {row["id"] for row in selected_requirements(authority_input)}
        authority_input["observations"] = [row for row in authority_input["observations"]
            if row["query"]["purpose"] == "REVOCATION" or row["query"]["requirement_id"] in selected]
    supplied, base_expected = authority_specimen(shared_budget=False, mutator=configure)
    return supplied, expected_ready(supplied, base_expected)


def expected_ready(authority_input: dict[str, Any], base_expected: dict[str, Any]) -> dict[str, Any]:
    """Extend the frozen successful check inventory; do not evaluate evidence policy."""
    result = copy.deepcopy(base_expected)
    for name, kind in (("source", "authority-source"), ("work_class", "authority-work-class"),
                       ("envelope", "authority-envelope"), ("proposal", "authority-proposal")):
        result[name + "_digest"] = digest(kind, authority_input[name])
    result["operation_digest"] = digest("authority-operation", {name: result[name] for name in (
        "envelope_digest", "work_class_digest", "proposal_digest",
    )})
    result["act_digests"] = sorted((digest("authority-act", row) for row in authority_input["acts"]), key=lambda value: value.encode("utf-8"))
    result["checks"] = [row for row in result["checks"] if row["purpose"] != "SOURCE_OBSERVATION"]
    historical_times = {row["occurred_at"] for row in authority_input["acts"]}
    for check in result["checks"]:
        if check["purpose"] == "REVOCATION":
            if check["at"] not in historical_times:
                check["at"] = authority_input["clock"]["instant"]
            exact_query = next(row["query"] for row in authority_input["observations"]
                if row["query"]["purpose"] == "REVOCATION"
                and row["query"]["subject_digest"] == check["subject_digest"]
                and row["query"]["at"] == check["at"])
            check["requirement_ref"] = digest("authority-query", exact_query)
        elif check["purpose"] not in {"ACT_CAPACITY", "ACT_OCCUPANCY", "GATE_CRITERION"}:
            check["at"] = authority_input["clock"]["instant"]
    result["checks"].extend({"purpose": "SOURCE_OBSERVATION", "subject_digest": result["envelope_digest"],
        "requirement_ref": req["id"], "at": source_query(req, authority_input)["at"]}
        for req in selected_requirements(authority_input))
    result["checks"] = canonical_sort(result["checks"])
    evidence = {key: authority_input[key] for key in EVIDENCE_MEMBERS}
    if "evaluation_point" in authority_input:
        evidence["evaluation_point"] = authority_input["evaluation_point"]
    result["evidence_digest"] = digest("authority-evidence", evidence)
    return result


def source_check(authority_input: dict[str, Any], requirement_id: str, reason: str) -> dict[str, str]:
    req = next(row for row in authority_input["envelope"]["source_observation_requirements"] if row["id"] == requirement_id)
    return {"purpose": "SOURCE_OBSERVATION", "subject_digest": digest("authority-envelope", authority_input["envelope"]),
        "requirement_ref": requirement_id, "at": source_query(req, authority_input)["at"], "reason": reason}


def source_refusal(authority_input: dict[str, Any], requirement_id: str, *reasons: str) -> dict[str, Any]:
    return authority_refusal([source_check(authority_input, requirement_id, reason) for reason in reasons])


def refresh(authority_input: dict[str, Any], instant: str, *, evaluation_point: str = "DISPATCH") -> dict[str, Any]:
    refreshed = copy.deepcopy(authority_input)
    old_instant = refreshed["clock"]["instant"]
    refreshed["clock"]["instant"] = instant
    refreshed["evaluation_point"] = evaluation_point
    requirements = {row["id"]: row for row in selected_requirements(refreshed)}
    rows = []
    for row in refreshed["observations"]:
        query = row["query"]
        if query["purpose"] == "REVOCATION":
            if query["at"] == old_instant:
                query["at"] = instant
                row["query_digest"] = digest("authority-query", query)
                if row["status"] == "AVAILABLE":
                    row["as_of"] = instant
            rows.append(row)
        elif query["requirement_id"] in requirements:
            req = requirements[query["requirement_id"]]
            row["query"] = source_query(req, refreshed)
            row["query_digest"] = digest("authority-query", row["query"])
            if row["status"] in {"AVAILABLE", "ABSENT"}:
                row["as_of"] = row["query"]["at"]
            rows.append(row)
    refreshed["observations"] = rows
    return refreshed
