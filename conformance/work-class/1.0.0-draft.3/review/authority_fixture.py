"""Upgrade the independently frozen draft-1 authority specimen to draft 2.

The historical specimen supplies synthetic organizational facts. This module
rebinds those facts to the draft-2 candidate and rederives every digest from
the normative preimages. It does not inspect either draft-2 implementation.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from corpus_common import ROOT, canonical_bytes, digest
from fixture_factory import PIN


SOURCE = ROOT / "conformance/work-class/1.0.0-draft.1/cases-authority-initial/positive-access-card.json"
OLD_PREFIX = b"seampoint.work-class/1.0.0-draft.1/"


def old_digest(kind: str, value: Any) -> str:
    return "sha256:" + hashlib.sha256(OLD_PREFIX + kind.encode("utf-8") + b"\n" + canonical_bytes(value)).hexdigest()


def rewrite(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [rewrite(member, replacements) for member in value]
    if isinstance(value, dict):
        return {key: rewrite(member, replacements) for key, member in value.items()}
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        return value.replace("seampoint.work-class/1.0.0-draft.1/", "seampoint.work-class/1.0.0-draft.3/")
    return value


def canonical_sort(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=canonical_bytes)


def authority_specimen(
    *,
    shared_budget: bool = True,
    shared_budgets: list[str] | None = None,
    exclusive_keys: list[dict[str, Any]] | None = None,
    instance_id: str | None = None,
    occurrence_id: str | None = None,
    mutator: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_case = json.loads(SOURCE.read_text())
    original = source_case["input"]["request"]
    request = rewrite(copy.deepcopy(original), {original["specification_pin"]: PIN})
    for step in request["work_class"]["steps"]:
        step["quantity_mode"] = "BOUNDED"
        step["exclusive_keys"] = []
    referenced_types = {field["type_ref"] for step in request["work_class"]["steps"] for field in step["fields"]}
    request["work_class"]["types"] = [row for row in request["work_class"]["types"] if row["id"] in referenced_types]
    if shared_budgets is not None:
        request["envelope"]["limits"]["shared_budgets"] = copy.deepcopy(shared_budgets)
    elif not shared_budget:
        request["envelope"]["limits"]["shared_budgets"] = []
        request["envelope"]["limits"]["per_action"] = [
            {
                "id": "authority-only-amount-limit",
                "step": "issue",
                "field": "amount",
                "operator": "LTE",
                "bound": {"type_ref": "amount", "value": "1000000"},
            }
        ]
        request["envelope"]["enforcement"]["mechanisms"] = ["AUTHORITY_BEFORE_RESERVATION"]
    if exclusive_keys is not None:
        step = next(row for row in request["work_class"]["steps"] if row["id"] == request["proposal"]["step"])
        step["quantity_mode"] = "NONE" if not request["envelope"]["limits"]["shared_budgets"] else "BOUNDED"
        step["exclusive_keys"] = copy.deepcopy(exclusive_keys)
        step["completion"] = {
            "terminal_policy": "LEGACY_NONTERMINAL",
            "effect_provider": "card-provider",
            "effect_source": "card-system",
            "effect_record_type": "card-result",
            "no_effect_provider": "card-provider",
            "no_effect_source": "card-system",
            "no_effect_record_type": "card-no-effect",
            "status_field": "status",
            "status_type_ref": "IDENTITY",
            "success_values": [{"type_ref": "IDENTITY", "value": "ISSUED"}],
            "failure_values": [{"type_ref": "IDENTITY", "value": "REJECTED"}],
            "evidence_bindings": [
                {"evidence_field": "amount", "request_field": "amount"},
                {"evidence_field": "beneficiary", "request_field": "beneficiary"},
                {"evidence_field": "card_id", "request_field": "card_id"},
            ],
            "route_label_field": None,
            "route_label_type_ref": None,
        }
        request["envelope"]["limits"]["per_action"] = []
        request["envelope"]["enforcement"]["mechanisms"] = [
            "ATOMIC_RESERVATION_TRANSITION",
            "AUTHORITY_BEFORE_RESERVATION",
        ]
    if instance_id is not None:
        request["proposal"]["instance"] = instance_id
    if occurrence_id is not None:
        request["proposal"]["occurrence"] = occurrence_id
    if mutator is not None:
        mutator(request, original)
    replacements: dict[str, str] = {original["specification_pin"]: PIN}

    def bind(kind: str, original_record: dict, new_record: dict) -> None:
        old = old_digest(kind, original_record)
        replacements[old] = digest(kind, rewrite(new_record, replacements))

    bind("authority-source", original["source"], request["source"])
    request = rewrite(request, replacements)
    bind("authority-work-class", original["work_class"], request["work_class"])
    request = rewrite(request, replacements)
    bind("authority-envelope", original["envelope"], request["envelope"])
    request = rewrite(request, replacements)
    bind("authority-proposal", original["proposal"], request["proposal"])
    request = rewrite(request, replacements)
    old_operation = {
        "envelope_digest": old_digest("authority-envelope", original["envelope"]),
        "work_class_digest": old_digest("authority-work-class", original["work_class"]),
        "proposal_digest": old_digest("authority-proposal", original["proposal"]),
    }
    new_operation = rewrite(old_operation, replacements)
    replacements[old_digest("authority-operation", old_operation)] = digest("authority-operation", new_operation)

    original_root = original["host_selection"]["root"]
    request = rewrite(request, replacements)
    bind("authority-root", original_root, request["host_selection"]["root"])
    request = rewrite(request, replacements)

    for collection, kind in [
        ("occupancies", "authority-occupancy"),
        ("capacities", "authority-capacity"),
        ("credentials", "authority-credential"),
    ]:
        for original_record in original[collection]:
            new_record = next(row for row in request[collection] if row["id"] == original_record["id"])
            bind(kind, original_record, new_record)
        request = rewrite(request, replacements)

    remaining_acts = {row["id"]: row for row in original["acts"]}
    for act_id in ["grant-1", "attest-1"]:
        original_record = remaining_acts[act_id]
        new_record = next(row for row in request["acts"] if row["id"] == act_id)
        bind("authority-act", original_record, new_record)
        request = rewrite(request, replacements)

    for original_return in original["returns"]:
        returned = next(row for row in request["returns"] if row["id"] == original_return["id"])
        act = next(row for row in request["acts"] if row["actor"] == returned["actor"])
        returned["act_digest"] = digest("authority-act", act)
        returned["act_bytes_base64"] = base64.b64encode(canonical_bytes(act)).decode("ascii")
        replacements[old_digest("authority-return", original_return)] = digest("authority-return", returned)
    request = rewrite(request, replacements)

    for original_observation in original["observations"]:
        observation = next(row for row in request["observations"] if row["evidence_ref"] == original_observation["evidence_ref"])
        observation["query"] = rewrite(observation["query"], replacements)
        replacements[original_observation["query_digest"]] = digest("authority-query", observation["query"])
        observation["query_digest"] = digest("authority-query", observation["query"])
    request = rewrite(request, replacements)
    request["acts"] = sorted(request["acts"], key=lambda act: digest("authority-act", act).encode("utf-8"))
    request["host_selection"]["authenticated_records"] = canonical_sort(request["host_selection"]["authenticated_records"])

    expected = rewrite(copy.deepcopy(source_case["expected"]), replacements)
    expected["specification_pin"] = PIN
    expected["schema"] = "seampoint.work-class/1.0.0-draft.3/authority-result"
    expected["source_digest"] = digest("authority-source", request["source"])
    expected["work_class_digest"] = digest("authority-work-class", request["work_class"])
    expected["envelope_digest"] = digest("authority-envelope", request["envelope"])
    expected["proposal_digest"] = digest("authority-proposal", request["proposal"])
    expected["operation_digest"] = digest(
        "authority-operation",
        {
            "envelope_digest": expected["envelope_digest"],
            "work_class_digest": expected["work_class_digest"],
            "proposal_digest": expected["proposal_digest"],
        },
    )
    expected["act_digests"] = sorted((digest("authority-act", act) for act in request["acts"]), key=lambda item: item.encode("utf-8"))
    expected_checks = rewrite(expected["checks"], replacements)
    for check in expected_checks:
        if check["purpose"] == "INPUT_SUPPORT":
            check["requirement_ref"] = request["proposal"]["step"]
        elif check["purpose"] in {"ENVELOPE_VALIDITY", "GATE_FLOOR"}:
            check["requirement_ref"] = request["envelope"]["id"]
    for limit in request["envelope"]["limits"]["per_action"]:
        expected_checks.append(
            {
                "at": request["clock"]["instant"],
                "purpose": "PER_ACTION_LIMIT",
                "requirement_ref": limit["id"],
                "subject_digest": expected["operation_digest"],
            }
        )
    for requirement in request["envelope"].get("source_observation_requirements", []):
        if requirement["step"] != request["proposal"]["step"]:
            continue
        if request.get("evaluation_point", "PROPOSE") == "DISPATCH" and requirement.get("evaluation_point", "PROPOSE") != "PROPOSE_AND_DISPATCH":
            continue
        expected_checks.append({"purpose": "SOURCE_OBSERVATION", "subject_digest": expected["envelope_digest"], "requirement_ref": requirement["id"], "at": request["clock"]["instant"] if requirement["at"] == "CLOCK" else requirement["at"]})
    expected["checks"] = canonical_sort(expected_checks)
    expected["evidence_digest"] = digest(
        "authority-evidence",
        {key: request[key] for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock"]},
    )
    if "evaluation_point" in request:
        evidence = {key: request[key] for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock", "evaluation_point"]}
        expected["evidence_digest"] = digest("authority-evidence", evidence)
    if shared_budgets is not None:
        expected["required_budgets"] = copy.deepcopy(shared_budgets)
    else:
        expected["required_budgets"] = ["license-spend"] if shared_budget else []
    declared_keys = next(row for row in request["work_class"]["steps"] if row["id"] == request["proposal"]["step"]).get("exclusive_keys", [])
    if declared_keys:
        fields = {field["name"]: field["value"] for field in request["proposal"]["fields"]}
        expected["required_exclusive_keys"] = [
            {
                "id": row["id"],
                "slot": row["slot"],
                "namespace": row["namespace"],
                "key": [copy.deepcopy(projection["value"] if "value" in projection else fields[projection["field"]]) for projection in row["projection"]],
                "retention": row["retention"],
            }
            for row in declared_keys
        ]
    return request, expected


def envelope_digest(request: dict[str, Any]) -> str:
    return digest("authority-envelope", request["envelope"])


def operation_digest(request: dict[str, Any]) -> str:
    return digest(
        "authority-operation",
        {
            "envelope_digest": envelope_digest(request),
            "work_class_digest": digest("authority-work-class", request["work_class"]),
            "proposal_digest": digest("authority-proposal", request["proposal"]),
        },
    )


def envelope_validity_check(request: dict[str, Any], reason: str = "ENVELOPE_EXPIRED") -> dict[str, str]:
    """AUTHORITY-CHECKS check construction: ENVELOPE_VALIDITY | E | envelope.id | now."""
    return {
        "purpose": "ENVELOPE_VALIDITY", "subject_digest": envelope_digest(request),
        "requirement_ref": request["envelope"]["id"], "at": request["clock"]["instant"], "reason": reason,
    }


def credential_check(request: dict[str, Any], credential_id: str, reason: str = "CREDENTIAL_EXPIRED") -> dict[str, str]:
    """AUTHORITY-CHECKS check construction: CREDENTIAL | O | credential.id | now."""
    return {
        "purpose": "CREDENTIAL", "subject_digest": operation_digest(request),
        "requirement_ref": credential_id, "at": request["clock"]["instant"], "reason": reason,
    }


def revocation_check(request: dict[str, Any], subject_digest: str, at: str, reason: str = "REVOKED") -> dict[str, str]:
    """AUTHORITY-CHECKS check construction: REVOCATION | queried digest | query digest | query.at."""
    query = next(
        row["query"] for row in request["observations"]
        if row["query"]["subject_digest"] == subject_digest and row["query"]["at"] == at
    )
    return {
        "purpose": "REVOCATION", "subject_digest": subject_digest,
        "requirement_ref": digest("authority-query", query), "at": at, "reason": reason,
    }


def authority_refusal(
    failed_checks: list[dict[str, str]],
    *,
    code: str = "AUTHORITY_NOT_ESTABLISHED",
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    """A refusal whose failed_checks sort by canonical bytes and whose reasons default to the rows' reason set."""
    rows = sorted({canonical_bytes(row): copy.deepcopy(row) for row in failed_checks}.values(), key=canonical_bytes)
    selected = {row["reason"] for row in rows} if reasons is None else set(reasons)
    return {
        "status": "REFUSED", "code": code, "path": "",
        "reasons": sorted(selected, key=lambda value: value.encode("utf-8")),
        "failed_checks": rows,
    }
