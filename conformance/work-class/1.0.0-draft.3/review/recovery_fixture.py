"""Construct recovery records and expected transitions from the written contract.

No consumer implementation or implementation output is imported here.
"""

from __future__ import annotations

import base64
import copy
from decimal import Decimal

from authority_fixture import authority_specimen
from corpus_common import canonical_bytes, digest
from reservation_fixture import (
    budget_result, effect_record, fixture, host_and_event, native, request,
    reservation_record, transition, zero_state,
)


def configuration() -> dict:
    return {
        "provider": "organization-provider", "source": "payment-recovery-governance",
        "controller_role": "payment-recovery-controller",
        "policy_owner_role": "payment-recovery-policy-owner",
        "policy_families": ["small-duplicate-payments"],
        "negative_prerequisite_behavior": "STOP",
        "exception_profiles": ["MONETARY_DUPLICATE_SEND"],
    }


def empty_recovery() -> dict:
    return {"policies": [], "dispositions": [], "contingent": [], "allowances": []}


def number(value: Decimal) -> str:
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def facts_for(amount: str = "150", *, instance: str = "instance-1") -> dict:
    facts = fixture()
    facts["configuration"]["recovery"] = configuration()

    def amount_mutator(supplied, _original):
        next(x for x in supplied["proposal"]["fields"] if x["name"] == "amount")["value"]["value"] = amount

    authority, result = authority_specimen(instance_id=instance, occurrence_id="issue:1", mutator=amount_mutator)
    authority["clock"] = copy.deepcopy(facts["clock"])
    facts["authority_a"], facts["authority_a_result"] = authority, result
    facts["amount"] = amount
    return facts


def registered(facts: dict) -> dict:
    before = zero_state(facts)
    before["core"]["recovery"] = empty_recovery()
    event, host = host_and_event(facts, "REGISTER", "register-recovery-budget", "0", {
        "definition": facts["budget"], "authorizations": facts["authorizations"], "history": facts["history"],
    })
    core = copy.deepcopy(before["core"])
    core["budgets"] = [{"definition": copy.deepcopy(facts["budget"]),
        "definition_digest": digest("budget-definition", facts["budget"]),
        "authorizations": copy.deepcopy(facts["authorizations"]), "history": copy.deepcopy(facts["history"])}]
    return transition(before, event, host, core, "REGISTERED")["state"]


def reserve(facts: dict, before: dict, *, event_id: str = "reserve-a") -> tuple[dict, dict]:
    event, host = host_and_event(facts, "RESERVE", event_id, before["core"]["revision"], {
        "authority": facts["authority_a"], "histories": [facts["history"]],
    }, administration=False)
    core = copy.deepcopy(before["core"])
    row = reservation_record(facts, "authority_a", event_id)
    row["contributions"][0]["value"]["value"] = facts["amount"]
    core["reservations"].append(row)
    core["reservations"].sort(key=lambda x: x["id"].encode())
    committed = sum((Decimal(next(f["value"]["value"] for f in row["event"]["fields"] if f["name"] == "amount"))
        for row in facts["history"]["journal"] if row["event"]["state"] == "ACTIVE"), Decimal(0))
    total = number(committed + Decimal(facts["amount"]))
    result = transition(before, event, host, core, "RESERVED", reservation_id=event_id,
        budgets=budget_result(facts, total), authority_result=facts["authority_a_result"])
    return request(before, event, host), result


def disputed(facts: dict, *, result_kind: str = "UNKNOWN") -> dict:
    _, reserved = reserve(facts, registered(facts))
    before = reserved["state"]
    record = native(facts, result_kind, "native-disputed", completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT")
    event, host = host_and_event(facts, "SETTLE", "retain-disputed-outcome", before["core"]["revision"], {
        "native": record, "histories": [facts["history"]],
    }, administration=False)
    core = copy.deepcopy(before["core"])
    core["reservations"][0]["status"] = "DISPUTED"
    key = core["reservations"][0]["contributions"][0]["key"] if result_kind == "EFFECT" else None
    core["effects"].append(effect_record(record, "DISPUTED", "UNEXPECTED_EFFECT", [{"anchor": "license-spend", "key": key}]))
    return transition(before, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["UNEXPECTED_EFFECT"])["state"]


def target_for(state: dict) -> dict:
    return {"kind": "RESERVATION", "registry_digest": digest("reservation-registry", state["core"]["configuration"]), "reservation": state["core"]["reservations"][0]["id"]}


def native_request(state: dict) -> dict:
    p = state["core"]["reservations"][0]["authority"]["proposal"]
    return {key: copy.deepcopy(p[key]) for key in ("work_class", "instance", "occurrence", "step", "operation", "interface", "fields")}


def evidence_for(facts: dict, state: dict, *, conclusion: str = "UNRESOLVED", attempts: int = 2) -> dict:
    target = target_for(state)
    req = native_request(state)
    rows = [{"id": "attempt-" + str(i + 1),
        "attempt_digest": digest("recovery-attempt-evidence", {"request": req, "attempt": str(i + 1)}),
        "executor": facts["authority_a"]["proposal"]["executor"]["actor"], "connector": "payment-connector",
        "request_digest": digest("reservation-native-request", req), "maximum_executions": "1",
        "effect_ids": ["effect-1"] if conclusion == "EFFECT_ESTABLISHED" and i == 0 else [],
        "no_effect": conclusion == "NO_EFFECT_ESTABLISHED"} for i in range(attempts)]
    outcomes = []
    selected = facts["budget"]["reservation_policy"]["no_effect" if conclusion == "NO_EFFECT_ESTABLISHED" else "settlement"]
    if conclusion != "UNRESOLVED":
        outcome = native(facts, "EFFECT" if conclusion == "EFFECT_ESTABLISHED" else "NO_EFFECT", "native-recovery-established",
            reservation_id=target["reservation"], request_record=req)
        outcome.update(provider=selected["provider"], source=selected["source"])
        outcomes = [outcome]
    retained = [x["native"] for x in state["core"]["effects"] if x["reservation"] == target["reservation"]]
    retained += [x for d in state["core"]["recovery"]["dispositions"] if d["target"] == target for x in d["evidence"]["native_outcomes"]]
    retained_facts = {digest("recovery-fact", normalize_native(x)) for x in retained}
    return {
        "id": "provider-adjudication-1", **copy.deepcopy(selected),
        "record_type": "RECOVERY_ADJUDICATION", "record_digest": digest("provider-recovery-record", {"target": target, "conclusion": conclusion}),
        "evidence_ref": "authenticated-provider-complete-attempt-inventory", "provider_revision": "2",
        "target": target, "request": req,
        "covered_evidence_digests": sorted(retained_facts | {digest("recovery-fact", normalize_native(x)) for x in outcomes}),
        "superseded_evidence_digests": sorted(retained_facts),
        "attempts": rows, "conclusion": conclusion, "native_outcomes": outcomes,
        "rules_out_past_and_future_effects": conclusion == "NO_EFFECT_ESTABLISHED", "complete_attempt_inventory": True,
    }


def policy_for(facts: dict, state: dict, *, version: str = "1") -> dict:
    return {"id": "small-duplicate-payments-v" + version, "family": "small-duplicate-payments", "version": version,
        "scope": {"principal": facts["configuration"]["principal"], "registry_digest": digest("reservation-registry", state["core"]["configuration"]),
            "budget_anchors": [facts["budget"]["anchor"]], "work_classes": [facts["authority_a"]["proposal"]["work_class"]],
            "executors": [facts["authority_a"]["proposal"]["executor"]["actor"]], "connectors": ["payment-connector"],
            "unit": "USD", "profile": "MONETARY_DUPLICATE_SEND", "window_seconds": "86400"},
        "per_incident_limit": "5", "cumulative_limit": "10",
        "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}}


def authorize(facts: dict, event: dict, host: dict, *, operation: str, scope_digest: str,
              policy_owner: bool = False, actor: str | None = None) -> None:
    cfg = facts["configuration"]["recovery"]
    lifecycle = "event_id" in event
    event_id = event["event_id"] if lifecycle else event["id"]
    now = facts["clock"]["instant"] if lifecycle else event["clock"]["instant"]
    host_recovery = host if lifecycle else host["recovery"]
    actor = actor or ("recovery-policy-owner-human" if policy_owner else "independent-recovery-controller-human")
    operations = [operation]
    if operation == "ESTABLISH_NO_EFFECT":
        operations.append("RELEASE_DISPUTED_EXPOSURE")
    role = cfg["policy_owner_role"] if policy_owner else cfg["controller_role"]
    basis = {"id": "recovery-basis-" + event_id, "actor": actor, "principal": facts["configuration"]["principal"],
        "role": role, "kind": "HUMAN", "scope_digest": scope_digest, "operations": sorted(operations),
        "validity": {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"},
        "at": now, "revoked": False,
        "provider": cfg["provider"], "source": cfg["source"], "evidence_ref": "selected-independent-recovery-remit"}
    subject = copy.deepcopy(event)
    if lifecycle:
        subject.pop("controller", None)
    else:
        subject["payload"].pop("controller", None)
        subject["payload"].pop("authorization", None)
    act = {"id": "recovery-act-" + event_id, "basis": basis["id"], "actor": actor,
        "principal": basis["principal"], "role": role, "kind": operation,
        "subject_digest": digest("recovery-subject", subject), "occurred_at": now, "disposition": "ACCEPT"}
    returned = {"id": "recovery-return-" + event_id, "act_digest": digest("recovery-act", act),
        "act_bytes_base64": base64.b64encode(canonical_bytes(act)).decode(), "actor": actor,
        "provider": cfg["provider"], "source": cfg["source"], "returned_at": now,
        "evidence_ref": "authenticated-human-recovery-return"}
    (event if lifecycle else event["payload"])["authorization" if policy_owner else "controller"] = {"act": act, "returned": returned}
    host_recovery["recovery_bases"] = [basis]
    host_recovery["authenticated_records"].append({"kind": "RECOVERY_RETURN",
        "record_digest": digest("recovery-return", returned), "provider": cfg["provider"], "source": cfg["source"]})
    host_recovery["authenticated_records"].sort(key=canonical_bytes)


def recovery_event(facts: dict, state: dict, kind: str, event_id: str, payload: dict) -> tuple[dict, dict]:
    event, host = host_and_event(facts, kind, event_id, state["core"]["revision"], payload, administration=False)
    host["recovery"] = {"caller": facts["authority_a"]["proposal"]["executor"]["actor"],
        "recovery_bases": [], "authenticated_records": [], "pending_evidence": []}
    if payload.get("evidence"):
        record = payload["evidence"]
        host["recovery"]["authenticated_records"].append({"kind": "RECOVERY_EVIDENCE",
            "record_digest": digest("recovery-evidence", record), "provider": record["provider"], "source": record["source"]})
    return event, host


def policy_issue(facts: dict, state: dict, *, version: str = "1", supersedes: str | None = None,
                 action: str = "ISSUE", policy: dict | None = None) -> tuple[dict, dict]:
    policy = copy.deepcopy(policy or policy_for(facts, state, version=version))
    pd = digest("recovery-policy", policy)
    event, host = recovery_event(facts, state, "RECOVERY_POLICY", "policy-" + action.lower() + "-" + version, {
        "action": action, "family": policy["family"], "policy": policy,
        "policy_digest": pd, "supersedes": supersedes, "authorization": None,
    })
    authorize(facts, event, host, operation="ISSUE_POLICY" if action == "ISSUE" else "REVOKE_POLICY",
        scope_digest=digest("recovery-policy-scope", policy["scope"]), policy_owner=True)
    core = copy.deepcopy(state["core"])
    if action == "ISSUE":
        core["recovery"]["policies"].append({"policy": policy, "policy_digest": pd, "revoked": False,
            "event_digest": digest("reservation-event", event), "authorization": copy.deepcopy(event["payload"]["authorization"])})
    else:
        next(x for x in core["recovery"]["policies"] if x["policy_digest"] == pd)["revoked"] = True
    core["recovery"]["policies"].sort(key=canonical_bytes)
    return request(state, event, host), transition(state, event, host, core, "POLICY_RECORDED")


def dispose_request(facts: dict, state: dict, result: str, *, event_id: str = "dispose-case",
                    evidence: dict | None = None, policy_digest: str | None = None,
                    supersedes: str | None = None, histories: list | None = None) -> dict:
    conclusion = {"ESTABLISH_EFFECT": "EFFECT_ESTABLISHED", "ESTABLISH_NO_EFFECT": "NO_EFFECT_ESTABLISHED"}.get(result, "UNRESOLVED")
    evidence = copy.deepcopy(evidence or evidence_for(facts, state, conclusion=conclusion,
        attempts=2 if result == "ACCEPT_UNRESOLVED" else 1))
    event, host = recovery_event(facts, state, "DISPOSE", event_id, {"target": target_for(state),
        "requested_result": result, "evidence": evidence, "controller": None, "policy_digest": policy_digest,
        "supersedes": supersedes, "histories": copy.deepcopy(histories if histories is not None else [facts["history"]])})
    if result in ("ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT"):
        authorize(facts, event, host, operation=result, scope_digest=digest("recovery-target", target_for(state)))
    return request(state, event, host)


def normalize_native(record: dict) -> dict:
    return {key: copy.deepcopy(value) for key, value in record.items()
        if key not in ("id", "evidence_id", "evidence_ref", "record_digest", "observed_at")}


def generation(packet: dict) -> str:
    projection = {key: copy.deepcopy(packet[key]) for key in ("target", "request", "covered_evidence_digests",
        "superseded_evidence_digests", "attempts", "conclusion", "native_outcomes", "rules_out_past_and_future_effects")}
    unique = {canonical_bytes(normalize_native(row)): normalize_native(row) for row in packet["native_outcomes"]}
    projection["native_outcomes"] = [unique[key] for key in sorted(unique)]
    return digest("recovery-generation", projection)


def disposition_record(supplied: dict, *, result: str | None = None) -> dict:
    event, state = supplied["event"], supplied["state"]
    p = event["payload"]
    reservation = next(x for x in state["core"]["reservations"] if x["id"] == p["target"]["reservation"])
    incident = digest("recovery-incident", {"principal": state["core"]["configuration"]["principal"],
        "registry_digest": p["target"]["registry_digest"], "reservation": reservation["id"],
        "occurrence": reservation["occurrence_key"], "error_class": "DUPLICATE_SEND_UNCERTAINTY"})
    gd = generation(p["evidence"])
    result = result or p["requested_result"]
    basis = digest("recovery-acceptance-basis", {"incident_digest": incident,
        "generation_digest": gd, "policy_digest": p["policy_digest"]}) if result == "ACCEPT_UNRESOLVED" else None
    identity = {"incident_digest": incident, "generation_digest": gd, "result": result,
        "policy_digest": p["policy_digest"], "controller": p["controller"], "supersedes": p["supersedes"]}
    return {"id": digest("recovery-disposition", identity), **identity,
        "acceptance_basis_digest": basis, "target": copy.deepcopy(p["target"]), "evidence": copy.deepcopy(p["evidence"]),
        "event_digest": digest("reservation-event", event), "accepted_at": event["clock"]["instant"], "source_event": copy.deepcopy(event)}


def disposition_expected(supplied: dict, *, reasons: list[str] | None = None, effective_result: str | None = None,
                         reused: dict | None = None) -> dict:
    before, event, host = supplied["state"], supplied["event"], supplied["host_evidence"]
    core = copy.deepcopy(before["core"])
    p = event["payload"]
    record = reused or disposition_record(supplied, result=effective_result)
    recovery = core["recovery"]
    if reused is None:
        recovery["dispositions"].append(copy.deepcopy(record))
        recovery["dispositions"].sort(key=canonical_bytes)
        rid = p["target"]["reservation"]
        if p["requested_result"] == "ACCEPT_UNRESOLVED" or record["result"] in ("ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT"):
            recovery["contingent"] = [x for x in recovery["contingent"] if x["reservation"] != rid]
        reservation = next(x for x in core["reservations"] if x["id"] == rid)
        if p["requested_result"] == "ACCEPT_UNRESOLVED":
            pending = [(a, i) for a in p["evidence"]["attempts"] if not a["no_effect"]
                for i in range(len(a["effect_ids"]) + 1, int(a["maximum_executions"]) + 1)]
            for attempt, index in pending[1:]:
                for contribution in reservation["contributions"]:
                    identity = {"registry_digest": p["target"]["registry_digest"], "reservation": rid,
                        "attempt_id": attempt["id"], "execution_index": str(index),
                        **{key: copy.deepcopy(contribution[key]) for key in ("anchor", "mapping", "key")}}
                    recovery["contingent"].append({"id": digest("recovery-contingent", identity),
                        "disposition_digest": record["id"], "reservation": rid, "attempt_id": attempt["id"], "execution_index": str(index),
                        **copy.deepcopy(contribution)})
            recovery["contingent"].sort(key=canonical_bytes)
            if record["result"] == "ACCEPT_UNRESOLVED":
                policy = next(x["policy"] for x in recovery["policies"] if x["policy_digest"] == p["policy_digest"])
                for anchor in sorted({x["anchor"] for x in reservation["contributions"]}):
                    amount = sum((Decimal(x["value"]["value"]) for x in reservation["contributions"] if x["anchor"] == anchor), Decimal(0)) * len(pending)
                    attributions = [("BUDGET", anchor)]
                    attributions += [("EXECUTOR", actor) for actor in sorted({a["executor"] for a in p["evidence"]["attempts"]})]
                    attributions += [("CONNECTOR", actor) for actor in sorted({a["connector"] for a in p["evidence"]["attempts"]})]
                    for actor_kind, actor in attributions:
                        recovery["allowances"].append({"acceptance_basis_digest": record["acceptance_basis_digest"],
                            "policy_family": policy["family"], "budget": anchor, "actor_kind": actor_kind,
                            "actor": actor, "amount": number(amount), "accepted_at": record["accepted_at"]})
                recovery["allowances"].sort(key=canonical_bytes)
        for history in p["histories"]:
            if history["status"] == "AVAILABLE":
                next(x for x in core["budgets"] if x["definition_digest"] == history["budget_digest"])["history"] = copy.deepcopy(history)
    decision = "DISPOSITION_REUSED" if reused else "WITHHELD" if reasons else "DISPOSITION_RECORDED"
    evaluations = []
    if reused is None and p["requested_result"] == "ACCEPT_UNRESOLVED":
        definition = core["budgets"][0]["definition"]
        history = core["budgets"][0]["history"]
        committed = sum((Decimal(next(f["value"]["value"] for f in x["event"]["fields"] if f["name"] == "amount"))
            for x in history["journal"] if x["event"]["state"] == "ACTIVE"), Decimal(0))
        pending_amount = sum((Decimal(x["value"]["value"]) for row in core["reservations"] for x in row["contributions"]), Decimal(0))
        pending_amount += sum((Decimal(x["value"]["value"]) for x in core["recovery"]["contingent"]), Decimal(0))
        total = committed + pending_amount
        evaluations = budget_result({"budget": definition}, number(total), "SATISFIED" if total <= Decimal("1000") else "VIOLATED")
        evaluations[0]["result"]["partitions"][0]["key"] = copy.deepcopy(core["reservations"][0]["contributions"][0]["key"])
    result = transition(before, event, host, core, decision, reservation_id=p["target"]["reservation"], reasons=reasons, budgets=evaluations)
    result["receipt"]["recovery_disposition_digest"] = record["id"]
    result["receipt_digest"] = digest("reservation-receipt", result["receipt"])
    result["state"]["receipts"][-1]["receipt"] = copy.deepcopy(result["receipt"])
    result["state_digest"] = digest("reservation-state", result["state"])
    return result


def refresh_authentication(facts: dict, supplied: dict) -> None:
    event, host = supplied["event"], supplied["host_evidence"]
    recovery = host["recovery"]
    recovery["authenticated_records"] = []
    packet = event["payload"].get("evidence")
    if packet:
        recovery["authenticated_records"].append({"kind": "RECOVERY_EVIDENCE",
            "record_digest": digest("recovery-evidence", packet), "provider": packet["provider"], "source": packet["source"]})
    if event["kind"] == "DISPOSE" and event["payload"]["requested_result"] in ("ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT"):
        authorize(facts, event, host, operation=event["payload"]["requested_result"],
            scope_digest=digest("recovery-target", event["payload"]["target"]))
    elif event["kind"] == "RECOVERY_POLICY":
        policy = event["payload"]["policy"]
        authorize(facts, event, host, operation="ISSUE_POLICY" if event["payload"]["action"] == "ISSUE" else "REVOKE_POLICY",
            scope_digest=digest("recovery-policy-scope", policy["scope"]), policy_owner=True)


def established_history(facts: dict, record: dict) -> dict:
    history = copy.deepcopy(facts["history"])
    history["revision"] = "2"
    history["journal"].append({"sequence": "2", "event": {
        "id": digest("reservation-committed-event", {"budget_digest": history["budget_digest"], "effect_id": record["effect_id"], "mapping": "pay"}),
        "state": "ACTIVE", "occurred_at": record["occurred_at"],
        "fields": [{"name": "amount", "value": {"type_ref": "amount", "value": facts["amount"]}},
            {"name": "beneficiary", "value": {"type_ref": "beneficiary", "value": "employee-7"}}]}})
    return history
