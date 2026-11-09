"""Source-selected holdings facts and complete expected records, without consumers.

This module constructs the chosen synthetic histories. It does not admit arbitrary
inputs or import runtime policy, schemas, adapters, or consumer output.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone

from corpus_common import candidate_pin, canonical_bytes, digest
from authority_fixture import authority_refusal, authority_specimen, canonical_sort
from equipment_observation_fixture import expected_ready, refresh


SCHEMA = "seampoint.work-class/1.0.0-draft.3/"
AT = "2026-09-10T04:30:00Z"
BEFORE = "2026-09-01T04:30:00Z"
AFTER = "2026-09-10T04:31:00Z"


def configuration(*, principal="access-card-owner", registry_id="permission-registry-1",
                  permissions=None, conflicts=None, clock_source="authority-clock"):
    names = permissions if permissions is not None else [
        "AP_PAYMENT_RELEASE", "APPLY_WORK", "REVIEW_WORK", "VENDOR_MASTER_MAINTENANCE"]
    pairs = conflicts if conflicts is not None else [
        {"left": "AP_PAYMENT_RELEASE", "right": "VENDOR_MASTER_MAINTENANCE"}]
    return {"schema": SCHEMA + "holdings-configuration", "specification_pin": candidate_pin(),
        "id": registry_id, "principal": principal, "policy_revision": "policy-revision-1",
        "permissions": sorted(names), "conflicts": canonical_sort(pairs),
        "provider": "permission-provider", "source": "authoritative-permissions",
        "protected_channel": "permission-internal", "clock_source": clock_source,
        "administration_role": "permission-administrator", "actor_namespace": "canonical-actors",
        "identity_provider": "identity-provider", "identity_revision": "identity-revision-1"}


def initial_grant(grant_id, actor, permission, *, start=BEFORE, end=None):
    return {"id": grant_id, "actor": actor, "permission": permission,
            "valid_from": start, "valid_until": end}


def request(config, state=None, *, kind="INITIALIZE", event_id="initialize-1", at=BEFORE,
            grants=None, grant_id="grant-new", actor="employee-042", permission="AP_PAYMENT_RELEASE",
            end=None, administrator="administrator-1"):
    state = copy.deepcopy(state)
    prior_digest = None if state is None else digest("holdings-state", state)
    clock = {"source": config["clock_source"], "status": "AVAILABLE", "instant": at}
    if kind == "INITIALIZE":
        payload = {"grants": sorted(copy.deepcopy(grants or []), key=lambda row: row["id"].encode())}
    else:
        payload = {"grant_id": grant_id, "actor": actor, "permission": permission}
        if kind == "GRANT":
            payload["valid_until"] = end
    event = {"schema": SCHEMA + "holdings-event", "id": event_id, "kind": kind,
        "expected_revision": "0" if state is None else state["core"]["revision"],
        "expected_state_digest": prior_digest, "clock": clock, "administration": None,
        "payload": payload}
    supplied = {"schema": SCHEMA + "holdings-input", "specification_pin": candidate_pin(),
        "configuration": copy.deepcopy(config), "state": state, "state_digest": prior_digest,
        "event": event, "host_evidence": {"configuration_digest": digest("holdings-configuration", config),
        "selection_evidence": "protected-configuration-selection", "authenticated_records": [],
        "seed_inventory": None}}
    resign(supplied, administrator=administrator)
    return supplied


def resign(supplied, *, administrator=None):
    """Authenticate a deliberately selected new event, preserving any chosen admin actor."""
    config, event = supplied["configuration"], supplied["event"]
    old = event.get("administration")
    administrator = administrator or (old["act"]["actor"] if old else "administrator-1")
    config_digest = digest("holdings-configuration", config)
    at = event["clock"]["instant"] or AT
    projection = {key: copy.deepcopy(value) for key, value in event.items() if key != "administration"}
    subject = digest("holdings-administration-subject", {"configuration_digest": config_digest, "event": projection})
    basis = {"id": "admin-basis-" + event["id"], "configuration_digest": config_digest,
        "principal": config["principal"], "role": config["administration_role"], "actor": administrator,
        "actor_kind": "HUMAN", "allowed_operations": ["GRANT", "INITIALIZE", "REVOKE"],
        "provider": config["provider"], "source": config["source"], "observed_at": at,
        "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z",
        "revoked_at": None, "evidence_ref": "protected-human-designation"}
    act = {"id": "admin-act-" + event["id"], "basis_id": basis["id"], "actor": administrator,
        "principal": config["principal"], "role": config["administration_role"], "kind": event["kind"],
        "subject_digest": subject, "occurred_at": at, "status": "ACCEPTED"}
    returned = {"actor": administrator, "provider": config["provider"], "source": config["source"],
        "channel": config["protected_channel"], "observed_at": at,
        "act_digest": digest("holdings-administration-act", act),
        "act_bytes_base64": base64.b64encode(canonical_bytes(act)).decode(),
        "evidence_ref": "protected-human-return",
        "provenance_digest": digest("holdings-return-provenance", {"event": event["id"], "actor": administrator})}
    event["administration"] = {"basis": basis, "act": act, "return": returned}
    supplied["host_evidence"].update(configuration_digest=config_digest,
        authenticated_records=canonical_sort([
            {"kind": "ADMIN_BASIS", "record_digest": digest("holdings-administration-basis", basis),
             "provider": config["provider"], "source": config["source"], "channel": None},
            {"kind": "ADMIN_RETURN", "record_digest": digest("holdings-administration-return", returned),
             "provider": config["provider"], "source": config["source"], "channel": config["protected_channel"]}]),
        seed_inventory=None if event["kind"] != "INITIALIZE" else {
            "inventory_digest": digest("holdings-seed-inventory", event["payload"]["grants"]),
            "evidence_ref": "protected-complete-existing-inventory"})
    return supplied


def transition(supplied, decision, reasons=()):
    """Retain a source-chosen decision and apply only its explicit grant delta."""
    config, event = supplied["configuration"], supplied["event"]
    state = copy.deepcopy(supplied["state"])
    grants = [] if state is None else copy.deepcopy(state["core"]["grants"])
    at, payload = event["clock"]["instant"], event["payload"]
    if decision == "INITIALIZED":
        grants = [{**copy.deepcopy(row), "revoked_at": None} for row in payload["grants"]]
    elif decision == "GRANTED":
        grants.append({"id": payload["grant_id"], "actor": payload["actor"], "permission": payload["permission"],
            "valid_from": at, "valid_until": payload["valid_until"], "revoked_at": None})
    elif decision == "REVOKED":
        next(row for row in grants if row["id"] == payload["grant_id"])["revoked_at"] = at
    grants.sort(key=lambda row: row["id"].encode())
    revision = str(1 if state is None else int(state["core"]["revision"]) + 1)
    core = {"configuration_digest": digest("holdings-configuration", config), "revision": revision,
            "last_clock": at, "grants": grants}
    event_digest = digest("holdings-event", {"event": event, "host_evidence": supplied["host_evidence"]})
    receipt = {"schema": SCHEMA + "holdings-receipt", "event_id": event["id"], "event_digest": event_digest,
        "state_before_digest": supplied["state_digest"], "revision": revision,
        "core_after_digest": digest("holdings-core", core), "decision": decision,
        "reasons": list(reasons), "protected_channel": config["protected_channel"]}
    receipt_digest = digest("holdings-receipt", receipt)
    record = {"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(supplied["host_evidence"]),
        "event_digest": event_digest, "receipt": receipt, "receipt_digest": receipt_digest}
    records = [] if state is None else state["records"]
    state = {"schema": SCHEMA + "holdings-state", "specification_pin": candidate_pin(),
             "core": core, "records": [*records, record]}
    return {"status": "TRANSITION", "receipt": copy.deepcopy(receipt), "receipt_digest": receipt_digest,
            "state": state, "state_digest": digest("holdings-state", state), "replay": False}


def refusal(supplied, code, *, shape=False):
    if shape:
        return {"status": "REFUSED", "code": code, "path": ""}
    return {"status": "REFUSED", "code": code, "path": "",
            "state": copy.deepcopy(supplied["state"]), "state_digest": supplied["state_digest"]}


def replay(supplied):
    record = next(row for row in supplied["state"]["records"] if row["event"]["id"] == supplied["event"]["id"])
    return {"status": "TRANSITION", "receipt": copy.deepcopy(record["receipt"]),
        "receipt_digest": record["receipt_digest"], "state": copy.deepcopy(supplied["state"]),
        "state_digest": supplied["state_digest"], "replay": True}


def basis(config, state, at=AT, *, status="AVAILABLE"):
    state_digest = digest("holdings-state", state)
    return {"configuration": copy.deepcopy(config), "state": copy.deepcopy(state), "state_digest": state_digest,
        "selection": {"configuration_digest": digest("holdings-configuration", config), "state_digest": state_digest,
        "revision": state["core"]["revision"], "provider": config["provider"], "source": config["source"],
        "channel": config["protected_channel"], "at": at, "status": status,
        "selection_evidence": "protected-latest-holdings-selection"}}


def requirement(config, *, requirement_id="executor-current-permission", actor="EXECUTOR", permission="APPLY_WORK", step="issue"):
    return {"id": requirement_id, "step": step, "configuration_digest": digest("holdings-configuration", config),
            "permission": permission, "actor": actor}


def holdings_check(req, actor, at=AT, reason=None):
    row = {"purpose": "HOLDINGS", "subject_digest": digest("holdings-query", {"requirement": req, "actor": actor, "at": at}),
           "requirement_ref": req["id"], "at": at}
    if reason is not None:
        row["reason"] = reason
    return row


def authority(*, config=None, state=None, reqs=None, bases=True, mutator=None):
    config = configuration() if config is None else copy.deepcopy(config)
    if state is None:
        seed = request(config, grants=[initial_grant("executor-grant-1", "card-machine", "APPLY_WORK")])
        state = transition(seed, "INITIALIZED")["state"]
    reqs = [requirement(config)] if reqs is None else copy.deepcopy(reqs)
    def configure(value, original):
        value["envelope"]["holdings_requirements"] = copy.deepcopy(reqs)
        if mutator:
            mutator(value, original)
    supplied, expected = authority_specimen(shared_budget=False, mutator=configure)
    if bases:
        supplied["holdings_bases"] = [basis(config, state, supplied["clock"]["instant"])]
    expected = authority_expected(supplied, expected)
    return supplied, expected


def authority_expected(supplied, previous, *, actors=None):
    expected = expected_ready(supplied, previous)
    expected["checks"] = [row for row in expected["checks"] if row["purpose"] != "HOLDINGS"]
    for req in supplied["envelope"].get("holdings_requirements", []):
        if req["step"] != supplied["proposal"]["step"]:
            continue
        actor = supplied["proposal"]["executor"]["actor"] if req["actor"] == "EXECUTOR" else (actors or {})[req["id"]]
        expected["checks"].append(holdings_check(req, actor, supplied["clock"]["instant"]))
    expected["checks"] = canonical_sort(expected["checks"])
    evidence = {key: copy.deepcopy(supplied[key]) for key in [
        "host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock"]}
    for key in ["evaluation_point", "decision_bases", "holdings_bases"]:
        if key in supplied:
            evidence[key] = copy.deepcopy(supplied[key])
    expected["evidence_digest"] = digest("authority-evidence", evidence)
    return expected


def ordinary_gate_authority(*, holding_actor="person-grantor", gate_kind="DECIDE"):
    """A complete ordinary human decision selects the holder independently of executor."""
    from equipment_correction_fixture import rebind_authority
    config = configuration()
    seed = request(config, grants=[initial_grant("reviewer-grant-1", holding_actor, "REVIEW_WORK")])
    state = transition(seed, "INITIALIZED")["state"]
    supplied, _ = authority_specimen(shared_budget=False)
    supplied["envelope"]["holdings_requirements"] = [requirement(config, actor="GATE_ACTOR", permission="REVIEW_WORK")]
    supplied["envelope"]["limits"]["per_action"] = []
    supplied["work_class"]["steps"][0]["quantity_mode"] = "NONE"
    supplied["envelope"]["gate"] = {"kind": gate_kind, "materiality": "HIGH" if gate_kind == "DECIDE" else "MEDIUM",
        "reversibility": "LOW" if gate_kind == "DECIDE" else "MEDIUM", "role": "access-card-grantor",
        "criteria": [{"id": "reviewed", "step": "issue", "predicate": {"kind": "BOOLEAN", "value": True}}]}
    grant = next(row for row in supplied["acts"] if row["kind"] == "GRANT")
    gate = {**copy.deepcopy(grant), "id": "ordinary-review-decision", "kind": "INSTANCE_DECISION" if gate_kind == "DECIDE" else "VERIFY",
            "occurred_at": "2026-09-09T10:00:00Z", "criteria": ["reviewed"]}
    supplied["acts"].append(gate)
    capacity = next(row for row in supplied["capacities"] if row["id"] == grant["capacity"])
    capacity["act_kinds"] = sorted([*capacity["act_kinds"], gate["kind"]])
    if gate_kind == "DECIDE":
        attester = copy.deepcopy(next(row for row in supplied["acts"] if row["kind"] == "ORGANISATIONAL_ATTESTATION"))
        attester.update(id="ordinary-decision-attestation", occurred_at="2026-09-09T10:01:00Z")
        supplied["acts"].append(attester)
    supplied, expected = rebind_authority(supplied)
    # That older equipment constructor selects its own provider. This generic
    # specimen retains the original identity-provider coordinates instead.
    for observed in supplied["observations"]:
        observed["query"]["provider"] = supplied["envelope"]["revocation"]["provider"]
        observed["query_digest"] = digest("authority-query", observed["query"])
    supplied["holdings_bases"] = [basis(config, state)]
    req = supplied["envelope"]["holdings_requirements"][0]
    return supplied, authority_expected(supplied, expected, actors={req["id"]: "person-grantor"})


def independent_gate_authority(*, holding_actor=None):
    """Add a separate generic permission condition to the pure two-decision apparatus."""
    from cdmo_fixture import cdmo_authority, expected_authority
    from authority_fixture import rewrite
    supplied, _, _ = cdmo_authority()
    selected_id = supplied["envelope"]["gate"]["decision_requirement"]
    selected = next(row["evidence"] for row in supplied["decision_bases"] if row["requirement_id"] == selected_id)
    leaf = selected["authority_input"]
    act = next(row for row in leaf["acts"] if digest("authority-act", row) == selected["decision_act_digest"])
    actor = act["actor"]
    config = configuration(principal=supplied["envelope"]["principal"], clock_source=supplied["clock"]["source"])
    seed = request(config, at="2026-10-06T10:00:00Z", grants=[initial_grant("selected-reviewer-grant", holding_actor or actor,
        "REVIEW_WORK", start="2026-10-06T10:00:00Z")])
    state = transition(seed, "INITIALIZED")["state"]
    replacements = {}
    old_envelope = digest("authority-envelope", supplied["envelope"])
    supplied["envelope"]["holdings_requirements"] = [requirement(config, actor="GATE_ACTOR", permission="REVIEW_WORK",
        step=supplied["proposal"]["step"])]
    replacements[old_envelope] = digest("authority-envelope", supplied["envelope"])
    root = supplied["host_selection"]["root"]
    old_root = digest("authority-root", root)
    root["envelope_digest"] = replacements[old_envelope]
    replacements[old_root] = digest("authority-root", root)
    for capacity in supplied["capacities"]:
        old = digest("authority-capacity", capacity)
        capacity.update(root_digest=replacements[old_root], envelope_digest=replacements[old_envelope])
        replacements[old] = digest("authority-capacity", capacity)
    for kind in ["GRANT", "ORGANISATIONAL_ATTESTATION"]:
        for outer_act in supplied["acts"]:
            if outer_act["kind"] != kind:
                continue
            old = digest("authority-act", outer_act)
            outer_act["subject_digest"] = replacements.get(outer_act["subject_digest"], outer_act["subject_digest"])
            replacements[old] = digest("authority-act", outer_act)
    for returned in supplied["returns"]:
        old = digest("authority-return", returned)
        act_id = json_load_return_id(returned)
        outer_act = next(row for row in supplied["acts"] if row["id"] == act_id)
        returned.update(act_digest=digest("authority-act", outer_act), act_bytes_base64=base64.b64encode(canonical_bytes(outer_act)).decode())
        replacements[old] = digest("authority-return", returned)
    supplied["host_selection"]["authenticated_records"] = canonical_sort(rewrite(supplied["host_selection"]["authenticated_records"], replacements))
    for observed in supplied["observations"]:
        if observed["query"]["purpose"] == "REVOCATION":
            observed["query"]["subject_digest"] = replacements.get(observed["query"]["subject_digest"], observed["query"]["subject_digest"])
            observed["query_digest"] = digest("authority-query", observed["query"])
    supplied["acts"].sort(key=lambda row:digest("authority-act",row))
    supplied["observations"].sort(key=lambda row:digest("authority-observation",row))
    supplied["holdings_bases"] = [basis(config, state, supplied["clock"]["instant"])]
    expected = expected_authority(supplied)
    req = supplied["envelope"]["holdings_requirements"][0]
    expected["checks"].append(holdings_check(req, actor, supplied["clock"]["instant"]))
    expected["checks"] = canonical_sort(expected["checks"])
    evidence = {key: supplied[key] for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock", "decision_bases", "holdings_bases"]}
    expected["evidence_digest"] = digest("authority-evidence", evidence)
    return supplied, expected, actor


def json_load_return_id(returned):
    import json
    return json.loads(base64.b64decode(returned["act_bytes_base64"]))["id"]


def policy_refusal(supplied, reason, *, requirement_id=None, actor=None):
    req = next(row for row in supplied["envelope"]["holdings_requirements"]
               if requirement_id is None or row["id"] == requirement_id)
    selected_actor = supplied["proposal"]["executor"]["actor"] if actor is None else actor
    return authority_refusal([holdings_check(req, selected_actor, supplied["clock"]["instant"], reason)])


def quinn_trace():
    config = configuration(principal="finance-org-01", registry_id="finance-permissions")
    seed = request(config)
    initialized = transition(seed, "INITIALIZED")
    vendor = request(config, initialized["state"], kind="GRANT", event_id="vendor-class-grant",
        at=BEFORE, grant_id="vendor-grant-1", permission="VENDOR_MASTER_MAINTENANCE", administrator="administrator-1")
    vendor_result = transition(vendor, "GRANTED")
    payment = request(config, vendor_result["state"], kind="GRANT", event_id="payment-class-grant",
        at=AT, grant_id="payment-grant-1", permission="AP_PAYMENT_RELEASE", administrator="administrator-2")
    payment_result = transition(payment, "WITHHELD", ["CONFLICTING_HOLDING"])
    revoke = request(config, payment_result["state"], kind="REVOKE", event_id="vendor-class-revoke",
        at=AFTER, grant_id="vendor-grant-1", permission="VENDOR_MASTER_MAINTENANCE")
    revoked = transition(revoke, "REVOKED")
    retry = request(config, revoked["state"], kind="GRANT", event_id="payment-class-after-revoke",
        at=AFTER, grant_id="payment-grant-2", permission="AP_PAYMENT_RELEASE", administrator="administrator-2")
    return [(seed, initialized), (vendor, vendor_result), (payment, payment_result), (revoke, revoked), (retry, transition(retry, "GRANTED"))]


def current_rows(supplied):
    rows = []
    now = supplied["clock"]["instant"]
    for req in supplied["envelope"]["holdings_requirements"]:
        if req["step"] != supplied["proposal"]["step"]:
            continue
        selected = next(row for row in supplied["holdings_bases"]
                        if digest("holdings-configuration", row["configuration"]) == req["configuration_digest"])
        actor = supplied["proposal"]["executor"]["actor"]
        grant = next(row for row in selected["state"]["core"]["grants"]
            if row["actor"] == actor and row["permission"] == req["permission"] and row["valid_from"] <= now
            and (row["valid_until"] is None or now < row["valid_until"])
            and (row["revoked_at"] is None or now < row["revoked_at"]))
        rows.append({"requirement_id": req["id"], "configuration_digest": req["configuration_digest"],
            "state_digest": selected["state_digest"], "revision": selected["state"]["core"]["revision"],
            "actor": actor, "permission": req["permission"], "grant_id": grant["id"], "valid_until": grant["valid_until"]})
    return sorted(rows, key=lambda row: row["requirement_id"].encode())


def lifecycle_base(*, end="2026-09-10T04:30:30Z", requirement_count=1, source_count=5):
    from equipment_observation_fixture import _configure
    from lifecycle_factory import base_lifecycle
    config = configuration()
    seed = request(config, grants=[initial_grant("executor-grant-1", "card-machine", "APPLY_WORK", end=end)])
    state = transition(seed, "INITIALIZED")["state"]
    reqs = [requirement(config, requirement_id="executor-current-permission-" + str(i).zfill(2)) for i in range(requirement_count)]
    def configure(value, _original):
        _configure(value, gated=True, include_session=True)
        source_reqs = value["envelope"]["source_observation_requirements"]
        # The default five sources are complete current session/approval/withdrawals.
        if source_count > len(source_reqs):
            from equipment_observation_fixture import observation
            for i in range(len(source_reqs), source_count):
                extra = copy.deepcopy(source_reqs[0])
                extra["id"] = "additional-source-" + str(i).zfill(2)
                source_reqs.append(extra)
                value["observations"].append(observation(extra, value))
            source_reqs.sort(key=lambda row: row["id"].encode())
        step = next(row for row in value["work_class"]["steps"] if row["id"] == value["proposal"]["step"])
        step["dispatch_gate"] = {"kind": "SOURCE_REQUIREMENTS", "requirements": [row["id"] for row in source_reqs],
            "coordinator_requirement": "approval", "fence_provider": "identity-provider",
            "fence_source": "equipment-synthetic-approvals", "authorization_seconds": "60", "validity_requirements": []}
        value["envelope"]["holdings_requirements"] = copy.deepcopy(reqs)
    base = base_lifecycle(authority_mutator=configure, instance_id="permission-work-instance")
    supplied = base["authority_input"]
    supplied["holdings_bases"] = [basis(config, state)]
    base["authority_result"] = authority_expected(supplied, base["authority_result"])
    base["proposal_event"]["authority_input"] = copy.deepcopy(supplied)
    base["holdings_configuration"], base["holdings_state"] = config, state
    base["holdings_seed_input"], base["holdings_seed_result"] = seed, transition(seed, "INITIALIZED")
    return base


def dispatch_fence(event, result):
    from fixture_factory import add_seconds
    supplied, permit = event["authority_input"], event["permit"]
    step = next(row for row in supplied["work_class"]["steps"] if row["id"] == supplied["proposal"]["step"])
    gate, sources = step["dispatch_gate"], []
    for req_id in gate["requirements"]:
        row = next(row for row in supplied["observations"] if row["query"].get("requirement_id") == req_id)
        query = row["query"]
        sources.append({"requirement_id": req_id, "provider": query["provider"], "source": query["source"],
            "expected_status": query["expected_status"], "record_id": row.get("provider_record_id"),
            "provider_revision": row["revision"], "query_digest": row["query_digest"],
            "observation_digest": digest("authority-observation", row)})
    holdings = current_rows(supplied)
    now = supplied["clock"]["instant"]
    ends = [permit["expires_at"], add_seconds(now, gate["authorization_seconds"])]
    envelope_end = supplied["envelope"]["temporal_validity"]["valid_until"]
    if envelope_end:
        ends.append(envelope_end)
    ends.extend(row["valid_until"] for row in holdings if row["valid_until"] is not None)
    expires = min(ends)
    scope = {"instance_id": event["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
        "permit_digest": permit["permit_id"], "native_request": event["native_request"], "connector": event["connector"],
        "dispatch_intent_id": event["dispatch_intent_id"], "checked_at": now, "expires_at": expires,
        "authority_result_digest": digest("authority-result", result), "sources": sources, "holdings": holdings}
    coordinator = next(row for row in sources if row["requirement_id"] == gate["coordinator_requirement"])
    return {"kind": "SOURCE_REQUIREMENTS", "provider": gate["fence_provider"], "source": gate["fence_source"],
        "provider_revision": coordinator["provider_revision"], "scope_digest": digest("dispatch-authorization-scope", scope),
        "checked_at": now, "status": "EFFECTIVE", "sources": sources, "holdings": holdings}, expires


def dispatch_authorization(base, permitted, *, supplied=None, event_id="permission-authorize-1", failure=None):
    from lifecycle_factory import admitted_transition, state_digest
    state, permit = permitted["state"], permitted["permit"]
    supplied = refresh(permit["authority_basis"], AT) if supplied is None else copy.deepcopy(supplied)
    for row in supplied.get("holdings_bases", []):
        row["selection"]["at"] = supplied["clock"]["instant"]
    result = authority_expected(supplied, base["authority_result"]) if failure is None else copy.deepcopy(failure)
    body = {"id": "permission-native-connector", "version": "revision-1"}
    connector = {**body, "binding_digest": digest("connector-binding", body)}
    event = {"schema": SCHEMA + "runtime-event", "kind": "AUTHORIZE_DISPATCH", "event_id": event_id,
        "instance_id": state["instance_id"], "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state), "permit": copy.deepcopy(permit),
        "native_request": copy.deepcopy(permit["native_request"]), "connector": connector,
        "authorization_fence": None, "authority_input": supplied, "dispatch_intent_id": "permission-intent-1",
        "observation_digests": sorted(digest("authority-observation", row) for row in supplied["observations"]),
        "clock_revision": "1"}
    result_digest, record = digest("authority-result", result), None
    if failure is None:
        fence, expires = dispatch_fence(event, result)
        event["authorization_fence"] = fence
        record_body = {"event_id": event_id, "event_digest": digest("runtime-event", event), "permit_digest": permit["permit_id"],
            "native_request": event["native_request"], "connector": connector, "authorization_fence": fence,
            "observation_digests": event["observation_digests"], "clock_revision": "1", "dispatch_intent_id": event["dispatch_intent_id"],
            "authority_input": supplied, "authority_result": result, "authority_result_digest": result_digest,
            "expires_at": expires, "supersedes_authorization_digest": None}
        record = {"authorization_digest": digest("dispatch-authorization", record_body), **record_body}
        details = [{"kind": "AUTHORIZATION", "authorization_digest": record["authorization_digest"], "permit_digest": permit["permit_id"],
            "gate_kind": "SOURCE_REQUIREMENTS", "checked_at": AT, "expires_at": expires, "sources": fence["sources"], "holdings": fence["holdings"]}]
        disposition, reasons = "AUTHORIZED", []
    else:
        disposition = "WITHHELD"
        reasons = sorted({"AUTHORITY_REQUIRED", failure["code"], *failure["reasons"]})
        details = [{"kind": "AUTHORITY", "authority_result_digest": result_digest, "code": failure["code"],
                    "reasons": failure["reasons"], "failed_checks": failure["failed_checks"]}]
    evaluation_body = {"event_id": event_id, "event_digest": digest("runtime-event", event), "permit_digest": permit["permit_id"],
        "dispatch_intent_id": event["dispatch_intent_id"], "clock_revision": "1", "authority_input": supplied,
        "authority_result": result, "authority_result_digest": result_digest,
        "authorization_digest": None if record is None else record["authorization_digest"], "disposition": disposition}
    evaluation = {"evaluation_digest": digest("dispatch-authorization-evaluation", evaluation_body), **evaluation_body}
    def mutate(next_state):
        if record is not None:
            next_state["authorizations"].append(copy.deepcopy(record))
        next_state["authorization_evaluations"].append(copy.deepcopy(evaluation))
    result = admitted_transition(state, event, disposition=disposition, reason_codes=reasons, details=details,
        receipt_permit_digest=permit["permit_id"], receipt_authority_result_digest=result_digest,
        receipt_authorization_evaluation_digest=evaluation["evaluation_digest"], mutate=mutate)
    return event, result
