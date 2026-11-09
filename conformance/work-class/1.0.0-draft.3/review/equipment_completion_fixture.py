"""Author-derived completion, lookup and terminal constructors without consumer calls."""

from __future__ import annotations

import copy

from corpus_common import canonical_bytes, digest
from equipment_dispatch_fixture import authorization_event, authorization_result, retained
from equipment_observation_fixture import authority_mutator as gated_authority_mutator
from fixture_factory import typed
from lifecycle_budget_fixture import permitted_budget_proposal
from lifecycle_factory import (admitted_transition, base_lifecycle, canonical_occurrence_key,
    dispatch_event, dispatch_result, governed_native_evidence, governed_outcome,
    permit_dispatch, permitted_proposal, state_digest)
from reservation_fixture import (effect_record, fixture, host_and_event, native,
    request as reservation_request, reservation_record, transition, zero_state)


KEYS = [{"id": "card-identity-key", "slot": "card-identity", "namespace": "access-card",
    "projection": [{"field": "card_id", "type_ref": "IDENTITY"}],
    "retention": "RETAIN_UNTIL_SETTLED_OR_AUTHORIZED_RELEASE"}]


def provider_link(provider="identity-provider", source="equipment-synthetic-approvals",
        record_type="approval", provider_record_id="grant-1"):
    return typed("PROVIDER_LINK", canonical_bytes({"provider": provider, "source": source,
        "record_type": record_type, "provider_record_id": provider_record_id}).decode("utf-8"))


def completion_carrier():
    return {"effect_provider": "card-provider", "effect_source": "card-system",
        "effect_record_type": "card-result", "no_effect_provider": "card-provider",
        "no_effect_source": "card-system", "no_effect_record_type": "card-no-effect",
        "status_field": "status", "status_type_ref": "STRING",
        "success_values": [typed("STRING", "ISSUED")], "failure_values": [typed("STRING", "REJECTED")],
        "route_label_field": None, "route_label_type_ref": None,
        "evidence_bindings": [{"request_field": name, "evidence_field": name}
            for name in ("amount", "beneficiary", "card_id")],
        "terminal_policy": "STOP_RETAIN", "provider_record_identity": {"field": "provider_event_id", "type_ref": "IDENTITY"},
        "event_time_identity": {"field": "event_timestamp", "type_ref": "INSTANT"},
        "additional_fields": [
            {"name": "action_kind", "value": typed("STRING", "ISSUE_CARD")},
            {"name": "approval_link", "value": provider_link()},
            {"name": "inspection_id", "value": typed("IDENTITY", "inspection-01")},
            {"name": "operator_id", "value": typed("IDENTITY", "operator-01")},
            {"name": "work_order_id", "value": typed("IDENTITY", "work-order-01")},
        ],
        "lookup": {"provider": "card-provider", "source": "card-system", "record_type": "card-result",
            "namespace": "synthetic-card-completion", "key_projection": [
                {"field": "card_id", "type_ref": "IDENTITY"},
                {"key_field": "inspection_id", "value": typed("IDENTITY", "inspection-01")},
                {"key_field": "approval_link", "value": provider_link()},
                {"key_field": "work_order_id", "value": typed("IDENTITY", "work-order-01")},
            ]}}


def referral_policy():
    return {"authority": [], "completion": [
        {"id": "completion-operations", "destination_role": "operations-control-room-lead",
            "queue": "operations-completion-review", "purpose": "review-unproven-completion",
            "safe_state": "retain-current-state", "via_role": None, "requirement_ids": []},
        {"id": "completion-reliability", "destination_role": "reliability-supervisor",
            "queue": "reliability-completion-review", "purpose": "review-unproven-completion",
            "safe_state": "retain-current-state", "via_role": None, "requirement_ids": []},
    ]}


def completion_authority_mutator(authority_input, original, *, exclusive_keys=False):
    gated_authority_mutator(authority_input, original)
    step = next(row for row in authority_input["work_class"]["steps"] if row["id"] == authority_input["proposal"]["step"])
    for type_id, kind in (("PROVIDER_LINK", "IDENTITY"), ("STRING", "STRING")):
        if not any(row["id"] == type_id for row in authority_input["work_class"]["types"]):
            authority_input["work_class"]["types"].append({"id": type_id, "kind": kind, "nonnegative": False, "unit": None})
    authority_input["work_class"]["types"].sort(key=lambda row: row["id"].encode())
    step["authority_type_refs"] = ["BOOLEAN", "INSTANT", "PROVIDER_LINK", "STRING"]
    step["completion"] = completion_carrier()
    if exclusive_keys:
        step["quantity_mode"] = "NONE"
        step["exclusive_keys"] = copy.deepcopy(KEYS)
        authority_input["envelope"]["limits"]["per_action"] = []
        authority_input["envelope"]["enforcement"]["mechanisms"] = ["ATOMIC_RESERVATION_TRANSITION", "AUTHORITY_BEFORE_RESERVATION"]


def completion_definition_mutator(definition):
    for step in definition["steps"]:
        if step["kind"] == "OPERATION":
            step["completion"] = completion_carrier()
            step["referral_policy"] = referral_policy()


def completion_base(*, exclusive_keys=False):
    return base_lifecycle(definition_mutator=completion_definition_mutator,
        authority_mutator=lambda supplied, original: completion_authority_mutator(supplied, original, exclusive_keys=exclusive_keys))


def completion_key_proposal(base):
    facts = fixture(exclusive_keys=KEYS)
    facts["configuration"]["slots"] = []
    facts["authority_a"] = copy.deepcopy(base["authority_input"])
    facts["authority_a_result"] = copy.deepcopy(base["authority_result"])
    proposal = copy.deepcopy(base["proposal_event"])
    registry = zero_state(facts)
    registry_digest = digest("reservation-registry", facts["configuration"])
    reserve_id = digest("lifecycle-reservation-event", {"instance_id": proposal["instance_id"],
        "lifecycle_event_id": proposal["event_id"], "lifecycle_event_kind": "PROPOSE",
        "reservation_event_kind": "RESERVE", "registry_digest": registry_digest})
    event, host = host_and_event(facts, "RESERVE", reserve_id, "0", {"authority": facts["authority_a"],
        "histories": [], "exclusive_keys": copy.deepcopy(facts["authority_a_result"]["required_exclusive_keys"])}, administration=False)
    core = copy.deepcopy(registry["core"])
    core["reservations"] = [reservation_record(facts, "authority_a", reserve_id)]
    core["exclusive_keys"] = [{"key_digest": digest("exclusive-key", {"registry": registry_digest,
        "slot": row["slot"], "namespace": row["namespace"], "key": row["key"]}),
        "slot": row["slot"], "namespace": row["namespace"], "key": copy.deepcopy(row["key"]),
        "owner_instance": facts["authority_a"]["proposal"]["instance"],
        "owner_occurrence": facts["authority_a"]["proposal"]["occurrence"], "acquisition_event": reserve_id,
        "status": "HELD", "settlement_evidence": None}
        for row in facts["authority_a_result"]["required_exclusive_keys"]]
    reserved = transition(registry, event, host, core, "RESERVED", reservation_id=reserve_id,
        authority_result=facts["authority_a_result"])
    proposal["budget_inputs"] = [{"registry_digest": registry_digest, "affected_anchors": [],
        "expected_revision": "0", "request": reservation_request(registry, event, host)}]
    output = {"registry_digest": registry_digest, "affected_anchors": [], "result": reserved}
    base["reservation_facts"] = facts
    base["reservation_result"] = reserved
    base["key_proposal_event"] = proposal
    return permitted_budget_proposal(base, proposal, output)


def completion_dispatch(attempt_status="SENT", *, acknowledgement_status="NONE", exclusive_keys=False):
    base = completion_base(exclusive_keys=exclusive_keys)
    permitted = completion_key_proposal(base) if exclusive_keys else permitted_proposal(base)
    authorize = authorization_event(base, permitted)
    authorized = authorization_result(base, permitted, authorize)
    current = retained(authorized, permitted["permit"])
    authorization_digest = authorized["state"]["authorizations"][0]["authorization_digest"]
    event = dispatch_event(base, current, event_id="completion-dispatch-1", attempt_status=attempt_status,
        acknowledgement_status=acknowledgement_status, authorization_digest=authorization_digest)
    status, reasons, occurrence_status = "DISPATCH_RECORDED", [], "DISPATCHED"
    if attempt_status in {"NOT_SENT", "REJECTED"} and acknowledgement_status == "ACCEPTED":
        status, reasons, occurrence_status = "DISPUTED", ["DISPATCH_EVIDENCE_CONFLICT"], "BLOCKED_DISPUTE"
    elif attempt_status == "NOT_SENT":
        status, reasons, occurrence_status = "DISPATCH_REFUSED", ["NATIVE_NOT_SENT"], "PERMITTED"
    elif attempt_status == "REJECTED":
        status, reasons, occurrence_status = "DISPATCH_REFUSED", ["NATIVE_DISPATCH_REJECTED"], "PERMITTED"
    elif acknowledgement_status == "ACCEPTED":
        status = "ACKNOWLEDGED"
    elif attempt_status == "UNKNOWN":
        reasons = ["DISPATCH_STATUS_UNKNOWN"]
    elif acknowledgement_status == "REJECTED":
        reasons = ["ACKNOWLEDGEMENT_REJECTED"]
    elif acknowledgement_status == "UNKNOWN":
        reasons = ["DISPATCH_STATUS_UNKNOWN"]
    dispatched = retained(dispatch_result(current, event, disposition=status, reasons=reasons,
        occurrence_status=occurrence_status), permitted["permit"])
    return base, permitted, dispatched


def completion_query(base, prior):
    permit = prior["permit"]
    dispatch = permit_dispatch(prior["state"], permit)
    step = next(row for row in base["definition"]["steps"] if row["id"] == permit["occurrence"]["step_id"])
    declaration = step["completion"]["lookup"]
    fields = {row["name"]: row["value"] for row in permit["native_request"]["fields"]}
    key = [{"name": row.get("key_field", row.get("field")),
        "value": copy.deepcopy(row["value"] if "value" in row else fields[row["field"]])}
        for row in declaration["key_projection"]]
    key.sort(key=lambda row: row["name"].encode())
    clock = max((row for row in prior["state"]["clocks"] if row["source"] == permit["clock_source"]), key=lambda row: int(row["revision"]))
    return {"instance_id": prior["state"]["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
        "permit_digest": permit["permit_id"], "dispatch_digest": dispatch["dispatch_digest"],
        "authorization_digest": dispatch.get("authorization_digest"),
        **{name: declaration[name] for name in ("provider", "source", "record_type", "namespace")},
        "key": key, "at": clock["observed_time"]}


def seal_lookup(lookup):
    lookup["query_digest"] = digest("completion-query", lookup["query"])
    lookup["provenance_digest"] = digest("completion-lookup-provenance", {key: value for key, value in lookup.items() if key != "provenance_digest"})
    return lookup


def lookup_event(base, prior, *, status="NOT_FOUND", coverage="COMPLETE", as_of=None, event_id="completion-check-1"):
    query = completion_query(base, prior)
    count = {"NOT_FOUND": 0, "UNAVAILABLE": 0, "AMBIGUOUS": 2, "OVERFLOW": 64}[status]
    candidates = [{"provider": query["provider"], "source": query["source"], "record_type": query["record_type"],
        "provider_record_id": "provider-event-" + str(number).zfill(3),
        "record_digest": digest("provider-native-record", {"synthetic_event": str(number)})}
        for number in range(1, count + 1)]
    lookup = seal_lookup({"query": query, "status": status, "observed_at": query["at"],
        "as_of": None if status == "UNAVAILABLE" else (as_of or query["at"]),
        "provider_revision": None if status == "UNAVAILABLE" else "provider-revision-1",
        "coverage": "UNAVAILABLE" if status == "UNAVAILABLE" else coverage, "candidates": candidates,
        "truncated": status == "OVERFLOW", "evidence_ref": "synthetic-completion-lookup"})
    clock = max((row for row in prior["state"]["clocks"] if row["source"] == prior["permit"]["clock_source"]), key=lambda row: int(row["revision"]))
    return {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "kind": "COMPLETION_CHECKED",
        "event_id": event_id, "instance_id": prior["state"]["instance_id"],
        "expected_state_revision": prior["state"]["revision"], "expected_state_digest": state_digest(prior["state"]),
        "permit": copy.deepcopy(prior["permit"]), "authorization_digest": query["authorization_digest"],
        "dispatch_digest": query["dispatch_digest"], "lookup": lookup, "clock_revision": clock["revision"]}


def decision_basis(state, event, disposition, reasons, permit_id, authority_result_digest=None,
        outcome_digest=None, completion_check_digest=None):
    return {"instance_id": state["instance_id"], "event_id": event["event_id"],
        "event_digest": digest("runtime-event", event), "disposition": disposition,
        "reason_codes": sorted(set(reasons)), "permit_digest": permit_id,
        "authority_result_digest": authority_result_digest, "outcome_digest": outcome_digest,
        "completion_check_digest": completion_check_digest}


def terminal_record(prior, event, basis, *, cause, occurrence_status, evidence_digests):
    permit = event["permit"]
    dispatch = next(row for row in prior["state"]["dispatches"] if row["dispatch_digest"] == event["dispatch_digest"])
    body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event),
        "instance_id": prior["state"]["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
        "permit_digest": permit["permit_id"], "authorization_digest": dispatch.get("authorization_digest"),
        "dispatch_digest": dispatch["dispatch_digest"], "decision_basis_digest": digest("decision-basis", basis),
        "cause": cause, "occurrence_status": occurrence_status, "evidence_digests": sorted(set(evidence_digests)),
        "retained_reservation_bases": copy.deepcopy(permit["budget_revisions"])}
    return {"terminal_digest": digest("terminal-record", body), **body}


def completion_referrals(base, prior, event, basis, terminal, cause_digest, evidence_digests):
    step = next(row for row in base["definition"]["steps"] if row["id"] == event["permit"]["occurrence"]["step_id"])
    rows = []
    for route in step["referral_policy"]["completion"]:
        body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event),
            "instance_id": prior["state"]["instance_id"], "occurrence_id": event["permit"]["occurrence"]["occurrence_id"],
            "decision_basis_digest": digest("decision-basis", basis), "terminal_digest": terminal["terminal_digest"],
            "cause_digest": cause_digest, **{name: route[name] for name in ("destination_role", "queue", "purpose", "safe_state", "via_role")},
            "evidence_digests": sorted(set(evidence_digests))}
        rows.append({"referral_digest": digest("referral-intent", body), **body})
    return sorted(rows, key=lambda row: row["referral_digest"])


def lookup_result(base, prior, event):
    lookup = event["lookup"]
    reason = {"NOT_FOUND": "UNKNOWN_OUTCOME", "UNAVAILABLE": "UNKNOWN_OUTCOME",
        "AMBIGUOUS": "COMPLETION_AMBIGUOUS", "OVERFLOW": "COMPLETION_OVERFLOW"}[lookup["status"]]
    reasons = [reason]
    if lookup["coverage"] == "INCOMPLETE":
        reasons.append("LOOKUP_INCOMPLETE")
    if lookup["as_of"] is not None and lookup["as_of"] < lookup["query"]["at"]:
        reasons.append("LOOKUP_STALE")
    reasons.sort()
    was_blocked = any(row["occurrence"] == event["permit"]["occurrence"] and row["status"] == "BLOCKED_DISPUTE"
        for row in prior["state"]["active"])
    occurrence_status = "BLOCKED_DISPUTE" if was_blocked or lookup["status"] in {"AMBIGUOUS", "OVERFLOW"} else "OUTCOME_UNKNOWN"
    body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event),
        "permit_digest": event["permit"]["permit_id"], "authorization_digest": event["authorization_digest"],
        "dispatch_digest": event["dispatch_digest"], "lookup": copy.deepcopy(lookup),
        "disposition": "COMPLETION_FAILED", "reason_codes": reasons}
    check = {"check_digest": digest("completion-check", body), **body}
    basis = decision_basis(prior["state"], event, "COMPLETION_FAILED", reasons, event["permit"]["permit_id"], completion_check_digest=check["check_digest"])
    terminal = terminal_record(prior, event, basis, cause="COMPLETION_LOOKUP_FAILED",
        occurrence_status=occurrence_status, evidence_digests=[check["check_digest"]])
    referrals = completion_referrals(base, prior, event, basis, terminal, check["check_digest"], [check["check_digest"]])
    initial_stop = not any(row["occurrence_id"] == terminal["occurrence_id"] for row in prior["state"]["terminal_records"])
    def mutate(state):
        state["status"] = "STOPPED"
        next(row for row in state["active"] if row["occurrence"] == event["permit"]["occurrence"])["status"] = occurrence_status
        state["completion_checks"].append(check)
        state["completion_checks"].sort(key=lambda row: row["event_id"])
        if initial_stop:
            state["terminal_records"].append(terminal)
            state["terminal_records"].sort(key=lambda row: row["terminal_digest"])
            state["referrals"].extend(referrals)
            state["referrals"].sort(key=lambda row: row["referral_digest"])
    return admitted_transition(prior["state"], event, disposition="COMPLETION_FAILED", reason_codes=reasons,
        details=[{"kind": "COMPLETION_CHECK", "check_digest": check["check_digest"], "status": lookup["status"], "reasons": reasons}],
        receipt_permit_digest=event["permit"]["permit_id"], receipt_completion_check_digest=check["check_digest"],
        receipt_decision_basis_digest=digest("decision-basis", basis) if initial_stop else None,
        receipt_terminal_digest=terminal["terminal_digest"] if initial_stop else None, mutate=mutate)


def completion_native(base, prior, *, evidence_id="completion-evidence-1", status="EFFECT_ESTABLISHED",
        result_value="ISSUED", provider_record_id="provider-event-1", provider_revision="provider-revision-1",
        event_time="2026-09-10T04:30:00Z", observed_at="2026-09-10T04:30:00Z", actual_fields=None,
        native_operation_id="native-operation-1", record_digest=None):
    carrier = next(row for row in base["definition"]["steps"] if row["id"] == prior["permit"]["occurrence"]["step_id"])["completion"]
    if actual_fields is None and status == "EFFECT_ESTABLISHED":
        actual_fields = copy.deepcopy(prior["permit"]["native_request"]["fields"] + carrier["additional_fields"])
        actual_fields += [{"name": carrier["status_field"], "value": typed(carrier["status_type_ref"], result_value)},
            {"name": carrier["provider_record_identity"]["field"], "value": typed(carrier["provider_record_identity"]["type_ref"], provider_record_id)},
            {"name": carrier["event_time_identity"]["field"], "value": typed(carrier["event_time_identity"]["type_ref"], event_time)}]
    evidence = governed_native_evidence(base, prior, prior, evidence_id=evidence_id, status=status,
        result_value=result_value, event_time=event_time, observed_at=observed_at, actual_fields=actual_fields,
        native_operation_id=native_operation_id)
    evidence["provider_record_id"] = provider_record_id if status == "EFFECT_ESTABLISHED" else None
    evidence["provider_revision"] = provider_revision if status == "EFFECT_ESTABLISHED" else None
    provider_body = {key: evidence[key] for key in ("provider", "source", "record_type", "provider_record_id",
        "provider_revision", "native_operation_id", "actual_fields", "collections", "event_time", "status")}
    evidence["record_digest"] = record_digest or digest("provider-native-record", provider_body)
    return evidence


def terminal_effect_result(base, prior, event, *, classification, disposition, reason_codes,
        occurrence_status, disputed, conflicts=None, complete_disposition=None, route=False,
        budget_results=None, update_conflicting_outcomes=False):
    receipts = [row["result"]["receipt_digest"] for row in (budget_results or [])]
    outcome = governed_outcome(event, prior, classification=classification, disputed=disputed,
        conflicts=conflicts, reservation_receipt_digests=receipts)
    late = prior["state"]["status"] != "ACTIVE"
    terminal = None
    referrals = []
    basis = None
    if classification not in {"MATCHED", "LATE_MATCHED", "DUPLICATE"} and not any(row["occurrence_id"] == event["permit"]["occurrence"]["occurrence_id"] for row in prior["state"]["terminal_records"]):
        cause = {"UNKNOWN": "UNKNOWN_COMPLETION", "UNEXPECTED": "UNEXPECTED_COMPLETION",
            "CONFLICTING": "CONFLICTING_COMPLETION", "FAILED": "DECLARED_COMPLETION_FAILURE",
            "NO_EFFECT_ESTABLISHED": "NO_EFFECT_COMPLETION"}[classification]
        basis = decision_basis(prior["state"], event, disposition, reason_codes, event["permit"]["permit_id"], outcome_digest=outcome["outcome_digest"])
        evidence_digests = [digest("native-evidence", event["native_evidence"])]
        evidence_digests.extend(digest("native-evidence", row["native_evidence"]) for row in prior["state"]["outcomes"]
            if row["native_evidence"]["evidence_id"] in (conflicts or []))
        terminal = terminal_record(prior, event, basis, cause=cause, occurrence_status=occurrence_status,
            evidence_digests=evidence_digests)
        referrals = completion_referrals(base, prior, event, basis, terminal, outcome["outcome_digest"], evidence_digests)
    relationship = next(row for row in base["definition"]["relationships"] if row["kind"] == "SEQUENCE") if route and not late else None
    relationship_digest = digest("relationship", relationship) if relationship else None
    def mutate(state):
        if update_conflicting_outcomes:
            for previous in state["outcomes"]:
                if previous["native_evidence"]["evidence_id"] in (conflicts or []):
                    previous["disputed"] = True
                    previous["conflicts_with_evidence_ids"] = sorted(set(previous["conflicts_with_evidence_ids"] + [event["native_evidence"]["evidence_id"]]))
                    previous["outcome_digest"] = digest("outcome", {key: value for key, value in previous.items() if key != "outcome_digest"})
        state["outcomes"].append(outcome)
        state["outcomes"].sort(key=lambda row: row["outcome_digest"])
        index = next((index for index, row in enumerate(state["active"]) if row["occurrence"] == event["permit"]["occurrence"]), None)
        if complete_disposition is not None and index is not None:
            active = state["active"].pop(index)
            state["completed"].append({"occurrence": copy.deepcopy(active["occurrence"]),
                "disposition": complete_disposition, "evidence_digest": digest("native-evidence", event["native_evidence"]),
                "occurred_at": event["native_evidence"]["event_time"] or event["native_evidence"]["observed_at"],
                "route_label": None, "selected_relationship_digest": relationship_digest, "late": late})
            state["completed"].sort(key=lambda row: canonical_occurrence_key(row["occurrence"]))
            if not late:
                state["status"] = "COMPLETE"
        elif occurrence_status is not None and index is not None:
            state["active"][index]["status"] = occurrence_status
        if terminal is not None:
            state["status"] = "STOPPED"
            state["terminal_records"].append(terminal)
            state["terminal_records"].sort(key=lambda row: row["terminal_digest"])
            state["referrals"].extend(referrals)
            state["referrals"].sort(key=lambda row: row["referral_digest"])
    details = [{"kind": "EFFECT", "classification": classification, "evidence_id": event["native_evidence"]["evidence_id"]}]
    if budget_results:
        details.insert(0, {"kind": "BUDGET", "registry_digest": budget_results[0]["registry_digest"],
            "receipt_digest": budget_results[0]["result"]["receipt_digest"],
            "reasons": budget_results[0]["result"]["receipt"]["reasons"]})
    if relationship:
        details.append({"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []})
    return admitted_transition(prior["state"], event, disposition=disposition, reason_codes=reason_codes,
        details=details, receipt_permit_digest=event["permit"]["permit_id"], budget_results=budget_results,
        receipt_decision_basis_digest=digest("decision-basis", basis) if basis else None,
        receipt_terminal_digest=terminal["terminal_digest"] if terminal else None, mutate=mutate)


def completion_key_settlement(base, prior, event, registry_state=None):
    facts = base["reservation_facts"]
    state = copy.deepcopy(registry_state or base["reservation_result"]["state"])
    evidence = event["native_evidence"]
    basis = prior["permit"]["budget_revisions"][0]
    record = native(facts, "EFFECT", evidence["evidence_id"], reservation_id=basis["reservation_id"])
    for name in ("provider", "source", "evidence_ref", "actual_fields", "collections", "rules_out_past_and_future_effects"):
        record[name] = copy.deepcopy(evidence[name])
    record["effect_id"] = evidence["native_operation_id"]
    record["occurred_at"] = evidence["event_time"]
    settlement_id = digest("lifecycle-reservation-event", {"instance_id": event["instance_id"],
        "lifecycle_event_id": event["event_id"], "lifecycle_event_kind": "EFFECT_OBSERVED",
        "reservation_event_kind": "SETTLE", "registry_digest": basis["registry_digest"]})
    settle, host = host_and_event(facts, "SETTLE", settlement_id, state["core"]["revision"],
        {"native": record, "histories": []}, administration=False)
    supplied = {"registry_digest": basis["registry_digest"], "affected_anchors": [],
        "expected_revision": state["core"]["revision"], "request": reservation_request(state, settle, host)}
    core = copy.deepcopy(state["core"])
    next(row for row in core["reservations"] if row["id"] == basis["reservation_id"]).update(status="SETTLED", matched_effect=evidence["native_operation_id"])
    for row in core["exclusive_keys"]:
        row.update(status="CONSUMED", settlement_evidence=evidence["native_operation_id"])
    core["effects"].append(effect_record(record, "MATCHED", "MATCHED_EFFECT", affected_anchors=[]))
    expected = transition(state, settle, host, core, "SETTLED", reservation_id=basis["reservation_id"])
    return supplied, {"registry_digest": basis["registry_digest"], "affected_anchors": [], "result": expected}
