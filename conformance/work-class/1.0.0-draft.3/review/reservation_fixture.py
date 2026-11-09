"""Rule-derived shared-budget fixtures for the draft-2 corpus.

The records are built from the frozen contract and the independently derived
authority specimen. Neither draft-2 implementation is imported or executed.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any

from authority_fixture import authority_specimen
from corpus_common import ROOT, canonical_bytes, digest
from fixture_factory import PIN


V = "seampoint.work-class/1.0.0-draft.3"
HISTORICAL_AGGREGATE = ROOT / "library/work-class-specification/1.0.0-draft.1/examples/aggregate-sum-boundary.json"


def canonical_sort(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=canonical_bytes)


def clock(instant: str = "2026-09-10T04:30:00Z") -> dict[str, Any]:
    return {"source": "authority-clock", "status": "AVAILABLE", "instant": instant}


def fixture(*, exclusive_keys: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    authority_a, result_a = authority_specimen(
        shared_budget=exclusive_keys is None,
        exclusive_keys=exclusive_keys,
        instance_id="instance-1",
        occurrence_id="issue:1",
    )
    authority_b, result_b = authority_specimen(
        shared_budget=exclusive_keys is None,
        exclusive_keys=exclusive_keys,
        instance_id="instance-2",
        occurrence_id="issue:2",
    )
    current_clock = clock()
    for request in (authority_a, authority_b):
        request["clock"] = copy.deepcopy(current_clock)

    configuration = {
        "schema": V + "/reservation-registry",
        "id": "license-registry",
        "principal": authority_a["envelope"]["principal"],
        "clock_source": current_clock["source"],
        "administration_provider": "organization-provider",
        "administration_source": "budget-administration",
        "administration_role": "budget-administrator",
        "slots": [{"anchor": "license-spend", "exposure_domain": "issuer-global-usd"}],
    }
    if exclusive_keys is not None:
        configuration["exclusive_slots"] = [
            {
                "slot": row["slot"],
                "namespace": row["namespace"],
                "authorized_classes": [authority_a["work_class"]["id"]],
                "retention": row["retention"],
                "permit_seconds": "300",
            }
            for row in exclusive_keys
        ]
    aggregate = json.loads(HISTORICAL_AGGREGATE.read_text())["definition"]
    aggregate["schema"] = V + "/aggregate-definition"
    aggregate["aggregate"]["time"]["clock_source"] = current_clock["source"]
    aggregate["aggregate"]["mappings"][0]["step_ids"] = ["issue"]
    aggregate["aggregate"]["committed_source"]["qualifier"] = {"kind": "BOOLEAN", "value": True}
    budget = {
        "schema": V + "/budget-definition",
        "anchor": "license-spend",
        "exposure_domain": "issuer-global-usd",
        "principal": configuration["principal"],
        "aggregate": aggregate,
        "contributor_classes": [authority_a["work_class"]["id"]],
        "reservation_policy": {
            "permit_seconds": "300",
            "pending_across_windows": True,
            "unexpected_effect": "BLOCK_AFFECTED_PARTITIONS",
            "unprojectable_effect": "BLOCK_ANCHOR",
            "settlement": {"provider": "native-provider", "source": "card-ledger"},
            "no_effect": {"provider": "native-provider", "source": "card-no-effect"},
        },
    }
    budget_digest = digest("budget-definition", budget)
    authorization = {
        "id": "license-class-authorization",
        "budget_digest": budget_digest,
        "work_class": authority_a["work_class"]["id"],
        "work_class_digest": digest("authority-work-class", authority_a["work_class"]),
        "envelope_digest": digest("authority-envelope", authority_a["envelope"]),
        "principal": configuration["principal"],
        "step": "issue",
        "authority_definition": {
            "schema": V + "/authority-definition",
            **{key: copy.deepcopy(authority_a[key]) for key in ("source", "work_class", "envelope")},
        },
        "projection": [
            {"native_field": "amount", "native_type": "amount", "budget_field": "amount", "budget_type": "amount"},
            {"native_field": "beneficiary", "native_type": "IDENTITY", "budget_field": "beneficiary", "budget_type": "beneficiary"},
        ],
    }
    history = {
        "budget_digest": budget_digest,
        "provider": aggregate["aggregate"]["committed_source"]["provider"],
        "source": aggregate["aggregate"]["committed_source"]["source"],
        "status": "AVAILABLE",
        "as_of": current_clock["instant"],
        "complete": True,
        "revision": "1",
        "journal": [
            {
                "sequence": "1",
                "event": {
                    "id": "opening-800",
                    "state": "ACTIVE",
                    "occurred_at": "2026-09-10T04:00:00Z",
                    "fields": [
                        {"name": "amount", "value": {"type_ref": "amount", "value": "800"}},
                        {"name": "beneficiary", "value": {"type_ref": "beneficiary", "value": "employee-7"}},
                    ],
                },
            }
        ],
        "evidence_ref": "complete-opening-history",
    }
    return {
        "configuration": configuration,
        "clock": current_clock,
        "budget": budget,
        "authorizations": [authorization],
        "history": history,
        "authority_a": authority_a,
        "authority_a_result": result_a,
        "authority_b": authority_b,
        "authority_b_result": result_b,
    }


def zero_state(facts: dict[str, Any]) -> dict[str, Any]:
    core = {
        "configuration": copy.deepcopy(facts["configuration"]),
        "revision": "0",
        "last_clock": None,
        "budgets": [],
        "reservations": [],
        "effects": [],
    }
    if facts["configuration"].get("exclusive_slots"):
        core["exclusive_keys"] = []
    return {
        "schema": V + "/reservation-state",
        "specification_pin": PIN,
        "core": core,
        "receipts": [],
    }


def host_and_event(
    facts: dict[str, Any],
    kind: str,
    event_id: str,
    revision: str,
    payload: dict[str, Any],
    *,
    event_clock: dict[str, Any] | None = None,
    administration: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected_clock = copy.deepcopy(event_clock or facts["clock"])
    configuration = facts["configuration"]
    event = {
        "id": event_id,
        "expected_revision": revision,
        "kind": kind,
        "clock": selected_clock,
        "payload": copy.deepcopy(payload),
        "administration": None,
    }
    registry_digest = digest("reservation-registry", configuration)
    host = {
        "registry_digest": registry_digest,
        "selection_evidence": "selected-license-registry",
        "administration_bases": [],
        "authenticated_records": [],
    }
    histories = [payload["history"]] if kind == "REGISTER" else payload.get("histories", [])
    for history in histories:
        host["authenticated_records"].append(
            {
                "kind": "HISTORY",
                "record_digest": digest("budget-history", history),
                "provider": history["provider"],
                "source": history["source"],
            }
        )
    if "native" in payload:
        native = payload["native"]
        host["authenticated_records"].append(
            {
                "kind": "NATIVE_OUTCOME",
                "record_digest": digest("reservation-native-outcome", native),
                "provider": native["provider"],
                "source": native["source"],
            }
        )
    if administration is None:
        administration = kind in ("REGISTER", "RELEASE")
    if administration:
        basis = {
            "id": "admin-basis",
            "registry_digest": registry_digest,
            "actor": "budget-owner-human",
            "principal": configuration["principal"],
            "role": configuration["administration_role"],
            "kind": "HUMAN",
            "operations": ["REGISTER", "RELEASE"],
            "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
            "at": selected_clock["instant"],
            "revoked": False,
            "provider": configuration["administration_provider"],
            "source": configuration["administration_source"],
            "evidence_ref": "selected-administration-basis",
        }
        subject = {
            "registry_digest": registry_digest,
            "event_id": event_id,
            "expected_revision": revision,
            "kind": kind,
            "clock": selected_clock,
            "payload": payload,
        }
        act = {
            "id": "admin-act-" + event_id,
            "basis": basis["id"],
            "actor": basis["actor"],
            "principal": basis["principal"],
            "role": basis["role"],
            "kind": kind,
            "subject_digest": digest("reservation-administration-subject", subject),
            "occurred_at": selected_clock["instant"],
            "disposition": "ACCEPT",
        }
        returned = {
            "id": "admin-return-" + event_id,
            "act_digest": digest("reservation-administration-act", act),
            "act_bytes_base64": base64.b64encode(canonical_bytes(act)).decode("ascii"),
            "actor": act["actor"],
            "provider": configuration["administration_provider"],
            "source": configuration["administration_source"],
            "returned_at": selected_clock["instant"],
            "evidence_ref": "authenticated-admin-return-" + event_id,
        }
        event["administration"] = {"act": act, "returned": returned}
        host["administration_bases"] = [basis]
        host["authenticated_records"].append(
            {
                "kind": "ADMIN_RETURN",
                "record_digest": digest("reservation-administration-return", returned),
                "provider": returned["provider"],
                "source": returned["source"],
            }
        )
    host["authenticated_records"] = canonical_sort(host["authenticated_records"])
    return event, host


def request(state: dict[str, Any], event: dict[str, Any], host: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": V + "/reservation-input",
        "specification_pin": PIN,
        "state": copy.deepcopy(state),
        "state_digest": digest("reservation-state", state),
        "event": copy.deepcopy(event),
        "host_evidence": copy.deepcopy(host),
    }


def transition(
    state: dict[str, Any],
    event: dict[str, Any],
    host: dict[str, Any],
    core: dict[str, Any],
    decision: str,
    *,
    reservation_id: str | None = None,
    budgets: list[dict[str, Any]] | None = None,
    authority_result: dict[str, Any] | None = None,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    next_core = copy.deepcopy(core)
    next_core["revision"] = str(int(state["core"]["revision"]) + 1)
    if event["clock"]["status"] == "AVAILABLE":
        next_core["last_clock"] = event["clock"]["instant"]
    receipt = {
        "event_digest": digest("reservation-event", event),
        "prior_state_digest": digest("reservation-state", state),
        "revision": next_core["revision"],
        "next_core_digest": digest("reservation-core", next_core),
        "decision": decision,
        "reservation": reservation_id,
        "budgets": copy.deepcopy(budgets or []),
        "authority_result": copy.deepcopy(authority_result),
        "reasons": sorted(set(reasons or []), key=lambda value: value.encode("utf-8")),
    }
    next_state = {
        "schema": V + "/reservation-state",
        "specification_pin": PIN,
        "core": next_core,
        "receipts": copy.deepcopy(state["receipts"]) + [{"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(host), "receipt": receipt}],
    }
    return {
        "status": "TRANSITION",
        "receipt": receipt,
        "receipt_digest": digest("reservation-receipt", receipt),
        "state": next_state,
        "state_digest": digest("reservation-state", next_state),
        "replay": False,
    }


def refusal(state: dict[str, Any], code: str) -> dict[str, Any]:
    return {"status": "REFUSED", "code": code, "path": "", "state": copy.deepcopy(state), "state_digest": digest("reservation-state", state)}


def budget_result(facts: dict[str, Any], total: str, status: str = "SATISFIED") -> list[dict[str, Any]]:
    reasons = [] if status == "SATISFIED" else ["BOUND_VIOLATED"]
    return [
        {
            "anchor": facts["budget"]["anchor"],
            "result": {
                "schema": V + "/aggregate-result",
                "specification_pin": PIN,
                "definition_digest": digest("aggregate-definition", facts["budget"]["aggregate"]),
                "status": status,
                "partitions": [
                    {
                        "occurrence": None,
                        "key": [{"type_ref": "beneficiary", "value": "employee-7"}],
                        "accumulator": {"kind": "SCALAR", "value": total},
                        "result": total,
                        "status": status,
                        "reasons": reasons,
                    }
                ],
                "reasons": reasons,
            },
        }
    ]


def reservation_record(facts: dict[str, Any], authority_key: str, reservation_id: str) -> dict[str, Any]:
    authority = facts[authority_key]
    authority_result = facts[authority_key + "_result"]
    proposal = authority["proposal"]
    occurrence_key = digest(
        "reservation-occurrence",
        {"work_class": proposal["work_class"], "instance": proposal["instance"], "occurrence": proposal["occurrence"]},
    )
    record = {
        "id": reservation_id,
        "occurrence_key": occurrence_key,
        "proposal_digest": digest("authority-proposal", proposal),
        "envelope_digest": digest("authority-envelope", authority["envelope"]),
        "authority": copy.deepcopy(authority),
        "authority_result": copy.deepcopy(authority_result),
        "contributions": [
            {
                "anchor": "license-spend",
                "mapping": "pay",
                "occurrence": occurrence_key,
                "key": [{"type_ref": "beneficiary", "value": "employee-7"}],
                "value": {"type_ref": "amount", "value": "150"},
            }
        ],
        "created_at": facts["clock"]["instant"],
        "permit_until": "2026-09-10T04:35:00Z",
        "status": "OPEN",
        "matched_effect": None,
    }
    if facts["configuration"].get("exclusive_slots"):
        record["contributions"] = []
        record["exclusive_keys"] = [
            {
                "key_digest": digest(
                    "exclusive-key",
                    {
                        "registry": digest("reservation-registry", facts["configuration"]),
                        "slot": row["slot"],
                        "namespace": row["namespace"],
                        "key": row["key"],
                    },
                ),
                "slot": row["slot"],
                "namespace": row["namespace"],
                "key": copy.deepcopy(row["key"]),
            }
            for row in facts["authority_a_result"].get("required_exclusive_keys", [])
        ]
    return record


def native(
    facts: dict[str, Any],
    outcome: str,
    native_id: str,
    *,
    reservation_id: str = "reserve-a",
    request_record: dict[str, Any] | None = None,
    observed_request: dict[str, Any] | None | object = ..., 
    effect_id: str = "effect-1",
    completion_mismatch: bool = False,
    mismatch_reason: str | None = None,
) -> dict[str, Any]:
    proposal = facts["authority_a"]["proposal"]
    attributed = request_record or {key: copy.deepcopy(proposal[key]) for key in ["work_class", "instance", "occurrence", "step", "operation", "interface", "fields"]}
    if outcome == "EFFECT":
        observed = copy.deepcopy(attributed) if observed_request is ... else copy.deepcopy(observed_request)
        actual_fields = copy.deepcopy(observed["fields"]) if observed is not None else []
        source = "card-ledger"
    else:
        observed = None
        actual_fields = []
        source = "card-no-effect" if outcome == "NO_EFFECT" else "card-ledger"
    return {
        "id": native_id,
        "provider": "native-provider",
        "source": source,
        "reservation": reservation_id,
        "outcome": outcome,
        "request": copy.deepcopy(attributed),
        "effect_id": effect_id if outcome == "EFFECT" else None,
        "occurred_at": facts["clock"]["instant"] if outcome == "EFFECT" else None,
        "rules_out_past_and_future_effects": outcome == "NO_EFFECT",
        "evidence_ref": "evidence-" + native_id,
        "observed_request": observed,
        "actual_fields": actual_fields,
        "collections": [],
        "completion_mismatch": completion_mismatch,
        "mismatch_reason": mismatch_reason,
    }


def effect_record(
    native_record: dict[str, Any],
    disposition: str,
    reason: str,
    blocked: list[dict[str, Any]] | None = None,
    affected_anchors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": native_record["id"],
        "native": copy.deepcopy(native_record),
        "native_digest": digest("reservation-native-outcome", native_record),
        "reservation": native_record["reservation"],
        "disposition": disposition,
        "affected_anchors": ["license-spend"] if affected_anchors is None else copy.deepcopy(affected_anchors),
        "blocked_partitions": copy.deepcopy(blocked or []),
        "reason": reason,
    }


def registered_state(facts: dict[str, Any]) -> dict[str, Any]:
    state = zero_state(facts)
    event, host = host_and_event(
        facts,
        "REGISTER",
        "register-license-budget",
        "0",
        {"definition": facts["budget"], "authorizations": facts["authorizations"], "history": facts["history"]},
    )
    core = copy.deepcopy(state["core"])
    core["budgets"] = [
        {
            "definition": copy.deepcopy(facts["budget"]),
            "definition_digest": digest("budget-definition", facts["budget"]),
            "authorizations": copy.deepcopy(facts["authorizations"]),
            "history": copy.deepcopy(facts["history"]),
        }
    ]
    return transition(state, event, host, core, "REGISTERED")["state"]


def open_state(facts: dict[str, Any]) -> dict[str, Any]:
    state = registered_state(facts)
    event, host = host_and_event(
        facts,
        "RESERVE",
        "reserve-a",
        "1",
        {"authority": facts["authority_a"], "histories": [facts["history"]]},
        administration=False,
    )
    core = copy.deepcopy(state["core"])
    core["reservations"] = [reservation_record(facts, "authority_a", "reserve-a")]
    return transition(
        state,
        event,
        host,
        core,
        "RESERVED",
        reservation_id="reserve-a",
        budgets=budget_result(facts, "950"),
        authority_result=facts["authority_a_result"],
    )["state"]


def matching_history(facts: dict[str, Any], native_record: dict[str, Any]) -> dict[str, Any]:
    history = copy.deepcopy(facts["history"])
    history["revision"] = "2"
    history["journal"].append(
        {
            "sequence": "2",
            "event": {
                "id": digest(
                    "reservation-committed-event",
                    {"budget_digest": history["budget_digest"], "effect_id": native_record["effect_id"], "mapping": "pay"},
                ),
                "state": "ACTIVE",
                "occurred_at": native_record["occurred_at"],
                "fields": [
                    {"name": "amount", "value": {"type_ref": "amount", "value": "150"}},
                    {"name": "beneficiary", "value": {"type_ref": "beneficiary", "value": "employee-7"}},
                ],
            },
        }
    )
    return history


def settled_state(facts: dict[str, Any]) -> dict[str, Any]:
    state = open_state(facts)
    native_record = native(facts, "EFFECT", "native-effect")
    history = matching_history(facts, native_record)
    event, host = host_and_event(
        facts,
        "SETTLE",
        "settle-a",
        "2",
        {"native": native_record, "histories": [history]},
        administration=False,
    )
    core = copy.deepcopy(state["core"])
    core["budgets"][0]["history"] = history
    core["reservations"][0].update(status="SETTLED", matched_effect="effect-1")
    core["effects"] = [effect_record(native_record, "MATCHED", "MATCHED_EFFECT")]
    return transition(state, event, host, core, "SETTLED", reservation_id="reserve-a")["state"]


def released_state(facts: dict[str, Any]) -> dict[str, Any]:
    state = open_state(facts)
    native_record = native(facts, "NO_EFFECT", "native-no-effect")
    event, host = host_and_event(
        facts,
        "RELEASE",
        "release-a",
        "2",
        {"native": native_record},
        administration=True,
    )
    core = copy.deepcopy(state["core"])
    core["reservations"][0]["status"] = "RELEASED"
    core["effects"] = [effect_record(native_record, "RELEASED", "AFFIRMATIVE_NO_EFFECT")]
    return transition(state, event, host, core, "RELEASED", reservation_id="reserve-a")["state"]
