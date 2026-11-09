#!/usr/bin/env python3
"""Freeze complete permission-component expectations before consumer execution."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path

from corpus_common import CASES, CONFORMANCE, ROOT, candidate_pin, canonical_bytes, digest, exact_case, write_canonical_json
from authority_fixture import authority_refusal, authority_specimen
from holdings_fixture import (
    AFTER, AT, BEFORE, authority, authority_expected, basis, configuration, dispatch_authorization,
    independent_gate_authority, initial_grant, lifecycle_base, ordinary_gate_authority, policy_refusal, quinn_trace, replay, request, requirement,
    resign, refusal, transition,
)
from lifecycle_factory import dispatch_event, dispatch_result, permitted_proposal, replay_result, stateful_refusal, step_input
from holdings_retained_fixture import retained_checkpoints


HERE = Path(__file__).resolve().parent
GROUP = CASES / "holdings"
SPECIMEN = CONFORMANCE / "specimens/permission-holdings"
SOURCE = HERE / "fixtures/permission-holdings-revision1-source.md"


def sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def authenticated(supplied):
    config, admin = supplied["configuration"], supplied["event"]["administration"]
    returned = admin["return"]
    supplied["host_evidence"]["authenticated_records"] = sorted([
        {"kind": "ADMIN_BASIS", "record_digest": digest("holdings-administration-basis", admin["basis"]),
         "provider": config["provider"], "source": config["source"], "channel": None},
        {"kind": "ADMIN_RETURN", "record_digest": digest("holdings-administration-return", returned),
         "provider": config["provider"], "source": config["source"], "channel": config["protected_channel"]}], key=canonical_bytes)


def returned_act(supplied):
    admin = supplied["event"]["administration"]
    admin["return"]["act_digest"] = digest("holdings-administration-act", admin["act"])
    admin["return"]["act_bytes_base64"] = base64.b64encode(canonical_bytes(admin["act"])).decode()
    authenticated(supplied)


def build():
    rows, labels = [], {}
    def emit(operation, supplied, expected, text, requirements, *, label, case_id=None):
        case_id = case_id or "C3-HOLD-" + str(len(rows) + 1).zfill(3)
        row = exact_case(case_id, operation, supplied, expected, requirements, text)
        rows.append(row)
        labels[label] = case_id
        return row
    def hold(supplied, expected, text, *, label, requirements=None):
        return emit("holdings-step", supplied, expected, text,
                    requirements or ["HOLD-002", "HOLD-003", "HOLD-004", "HOLD-005"], label=label)
    def deny(supplied, code, text, *, label, shape=False, requirements=None):
        return hold(supplied, refusal(supplied, code, shape=shape), text, label=label, requirements=requirements)

    trace = quinn_trace()
    texts = [
        "Protected complete empty inventory and an exact accepted HUMAN administration initialize revision1.",
        "The first work class grants Vendor Master Maintenance to employee-042.",
        "Nine days later another authorized human grants AP Payment Release from another work class. The current same-actor incompatible holding records WITHHELD despite both separate administrations being valid.",
        "Exact authorized revoke removes the first current permission and retains its original grant history.",
        "A fresh immutable grant after revocation records GRANTED. This does not erase the prior withheld attempt."]
    for index, ((supplied, expected), text) in enumerate(zip(trace, texts, strict=True)):
        hold(supplied, expected, text, label="quinn-" + str(index + 1), requirements=["HOLD-001", "HOLD-002", "HOLD-003", "HOLD-004"])
    config, final = trace[-1][0]["configuration"], trace[-1][1]["state"]
    old = copy.deepcopy(trace[1][0]); old.update(state=copy.deepcopy(final), state_digest=digest("holdings-state", final))
    hold(old, replay(old), "Exact replay returns the original grant receipt with the current complete state. It does not restore a revoked permission or require current historical administrator validity.", label="old-replay")
    changed = copy.deepcopy(old); changed["host_evidence"]["selection_evidence"] = "different-protected-selection"
    deny(changed, "REPLAY_CONFLICT", "Changed complete host evidence under an old event identifier is not exact replay, before revision or capacity checks.", label="changed-replay")
    stale = request(config, final, kind="GRANT", event_id="stale-revision", at=AFTER, grant_id="stale-grant")
    stale["event"]["expected_revision"] = "0"; stale["event"]["administration"] = None
    deny(stale, "REVISION_CONFLICT", "Stale expected revision takes precedence over missing human administration.", label="revision-before-admin")
    stale_digest = request(config, final, kind="REVOKE", event_id="wrong-expected-digest", at=AFTER,
        grant_id="payment-grant-2")
    stale_digest["event"]["expected_state_digest"] = "sha256:" + "0" * 64
    deny(stale_digest, "REVISION_CONFLICT", "Fresh event with a changed expected state digest refuses before clock and administration.", label="expected-digest")
    for label, change in [
        ("clock-source", lambda v: v["event"]["clock"].update(source="other-clock")),
        ("clock-unavailable", lambda v: v["event"]["clock"].update(status="UNAVAILABLE", instant=None)),
        ("clock-backward", lambda v: v["event"]["clock"].update(instant=BEFORE)),
        ("clock-calendar", lambda v: v["event"]["clock"].update(instant="2026-02-30T04:30:00Z"))]:
        supplied = request(config, final, kind="GRANT", event_id=label, at=AFTER)
        change(supplied); supplied["event"]["administration"] = None
        deny(supplied, "CLOCK_INVALID", "Invalid or unavailable ordered event clock takes precedence over missing administration: " + label + ".", label=label)
    raw = request(config, final, kind="GRANT", event_id="admin-fault", at=AFTER)
    for label, code, mutate in [
        ("admin-missing", "ADMINISTRATION_NOT_ESTABLISHED", lambda v: v["event"].update(administration=None)),
        ("return-missing", "EVIDENCE_UNAVAILABLE", lambda v: v["event"]["administration"].update({"return": None})),
        ("authentication-missing", "EVIDENCE_UNAVAILABLE", lambda v: v["host_evidence"].update(authenticated_records=[])),
        ("admin-wrong-subject", "DEPENDENCY_MISMATCH", lambda v: v["event"]["administration"]["act"].update(subject_digest="sha256:" + "0" * 64)),
        ("admin-wrong-actor", "DEPENDENCY_MISMATCH", lambda v: v["event"]["administration"]["act"].update(actor="unselected-administrator")),
        ("admin-return-channel", "DEPENDENCY_MISMATCH", lambda v: v["event"]["administration"]["return"].update(channel="public-channel")),
        ("admin-rejected", "ADMINISTRATION_NOT_ESTABLISHED", lambda v: v["event"]["administration"]["act"].update(status="REJECTED")),
        ("admin-expired", "ADMINISTRATION_NOT_ESTABLISHED", lambda v: v["event"]["administration"]["basis"].update(valid_until=AFTER)),
        ("admin-revoked", "ADMINISTRATION_NOT_ESTABLISHED", lambda v: v["event"]["administration"]["basis"].update(revoked_at=AFTER)),
        ("admin-wrong-remit", "ADMINISTRATION_NOT_ESTABLISHED", lambda v: v["event"]["administration"]["basis"].update(allowed_operations=["REVOKE"]))]:
        supplied = copy.deepcopy(raw); mutate(supplied)
        if label != "authentication-missing" and supplied["event"]["administration"] and supplied["event"]["administration"]["return"] is not None:
            returned_act(supplied)
        deny(supplied, code, "Exact administration admission: " + label + ". No permission holder or model assessment supplies this designation.", label=label)
    for label, body, code in [
        ("return-invalid-encoding", b"\xff", "ARTIFACT_ENCODING_INVALID"),
        ("return-duplicate-key", b'{"a":"x","a":"y"}', "ARTIFACT_ENCODING_INVALID"),
        ("return-noncanonical", b' {"a":"x"}', "ARTIFACT_NONCANONICAL")]:
        supplied = copy.deepcopy(raw)
        supplied["event"]["administration"]["return"]["act_bytes_base64"] = base64.b64encode(body).decode()
        authenticated(supplied)
        deny(supplied, code, "Embedded human return decoding/canonical admission: " + label + ".", label=label)
    for label, pair in [
        ("conflict-reversed", {"left":"VENDOR_MASTER_MAINTENANCE","right":"AP_PAYMENT_RELEASE"}),
        ("conflict-self", {"left":"AP_PAYMENT_RELEASE","right":"AP_PAYMENT_RELEASE"}),
        ("conflict-unknown", {"left":"AP_PAYMENT_RELEASE","right":"UNKNOWN_PERMISSION"})]:
        bad_config=configuration(conflicts=[pair]); supplied=request(bad_config)
        deny(supplied,"DEFINITION_INVALID","Conflict pairs must name two catalogue members in exact canonical order: "+label+".",label=label,requirements=["HOLD-001"])
    supplied=request(configuration(conflicts=[config["conflicts"][0],config["conflicts"][0]]))
    deny(supplied,"DEFINITION_INVALID","Duplicate incompatible pairs are not distinct policy declarations.",label="conflict-duplicate",requirements=["HOLD-001"])
    supplied=request(config, final, kind="INITIALIZE", event_id="initialize-again",at=AFTER)
    deny(supplied,"DEFINITION_CONFLICT","A fresh initialization cannot replace an established authoritative history.",label="initialize-again")
    supplied=request(config);supplied["host_evidence"]["seed_inventory"]=None
    deny(supplied,"EVIDENCE_UNAVAILABLE","Initialization cannot infer that an unverified caller inventory is complete.",label="initial-completeness")
    supplied=request(config);supplied["host_evidence"]["seed_inventory"]["inventory_digest"]="sha256:"+"0"*64
    deny(supplied,"DEPENDENCY_MISMATCH","The protected complete-inventory assertion binds the exact seed digest.",label="initial-digest")
    for label, grants in [
        ("initial-conflict",[initial_grant("a","employee-042","AP_PAYMENT_RELEASE"),initial_grant("b","employee-042","VENDOR_MASTER_MAINTENANCE")]),
        ("initial-duplicate-membership",[initial_grant("a","employee-042","AP_PAYMENT_RELEASE"),initial_grant("b","employee-042","AP_PAYMENT_RELEASE")]),
        ("initial-future",[initial_grant("a","employee-042","AP_PAYMENT_RELEASE",start=AFTER)]),
        ("initial-expired",[initial_grant("a","employee-042","AP_PAYMENT_RELEASE",start="2026-08-01T00:00:00Z",end=BEFORE)])]:
        supplied=request(config,grants=grants)
        deny(supplied,"STATE_INVALID","Complete initialization admits only a currently active, nonduplicated, compatible inventory: "+label+".",label=label)
    for label, fields in [
        ("unknown-permission",{"permission":"UNKNOWN_PERMISSION"}),
        ("reused-grant-id",{"grant_id":"vendor-grant-1"}),
        ("nonpositive-grant-end",{"end":AFTER})]:
        supplied=request(config,final,kind="GRANT",event_id=label,at=AFTER,**fields)
        deny(supplied,"CLOCK_INVALID" if label=="nonpositive-grant-end" else "DEPENDENCY_MISMATCH","Immutable grant/interval admission: "+label+".",label=label)
    same=request(config,final,kind="GRANT",event_id="already-held",at=AFTER,grant_id="unused-duplicate",end="2027-01-01T00:00:00Z")
    hold(same,transition(same,"UNCHANGED",["ALREADY_HELD"]),"A duplicate current permission records an attempt but neither adds the proposed identifier nor extends the existing grant.",label="already-held")
    old_revoke=request(config,final,kind="REVOKE",event_id="old-revoke",at=AFTER,grant_id="vendor-grant-1",permission="VENDOR_MASTER_MAINTENANCE")
    hold(old_revoke,transition(old_revoke,"UNCHANGED",["NOT_ACTIVE"]),"Revoking an already revoked old identifier records NOT_ACTIVE and leaves a later distinct grant unchanged.",label="old-revoke")
    for label, grant_id, actor, permission in [
        ("revoke-unknown","unknown-grant","employee-042","AP_PAYMENT_RELEASE"),
        ("revoke-wrong-actor","payment-grant-2","other-employee","AP_PAYMENT_RELEASE"),
        ("revoke-wrong-permission","payment-grant-2","employee-042","VENDOR_MASTER_MAINTENANCE")]:
        supplied=request(config,final,kind="REVOKE",event_id=label,at=AFTER,grant_id=grant_id,actor=actor,permission=permission)
        deny(supplied,"DEPENDENCY_MISMATCH","Revocation binds exact retained grant identifier, actor and permission: "+label+".",label=label)
    for label, mutate, code in [
        ("state-digest",lambda v:v.update(state_digest="sha256:"+"0"*64),"DIGEST_MISMATCH"),
        ("state-core-rehash",lambda v:v["state"]["core"].update(last_clock=BEFORE),"STATE_INVALID"),
        ("state-missing-record",lambda v:v["state"]["records"].pop(1),"STATE_INVALID"),
        ("state-altered-receipt",lambda v:v["state"]["records"][1]["receipt"].update(decision="WITHHELD"),"STATE_INVALID"),
        ("state-historical-administration",lambda v:v["state"]["records"][0]["event"].update(administration=None),"STATE_INVALID")]:
        supplied=request(config,final,kind="REVOKE",event_id=label,at=AFTER,grant_id="payment-grant-2")
        mutate(supplied)
        if label!="state-digest":supplied["state_digest"]=digest("holdings-state",supplied["state"])
        deny(supplied,code,"Reachable complete reconstruction precedes fresh event checks; a recomputed outer state hash does not repair "+label+".",label=label,requirements=["HOLD-003","HOLD-005"])
    # Finite catalogue/pair inventories have exact N-1/N/N+1 shape boundaries.
    for count in [63,64,65]:
        cfg=configuration(permissions=["P"+str(i).zfill(3) for i in range(count)],conflicts=[])
        supplied=request(cfg)
        if count<=64: hold(supplied,transition(supplied,"INITIALIZED"),"Catalogue cardinality "+str(count)+" is supported.",label="permissions-"+str(count))
        else: deny(supplied,"SCHEMA_INVALID","The65th permission exceeds the closed catalogue bound before definition policy.",label="permissions-65",shape=True)
    permissions=["P"+str(i).zfill(3) for i in range(64)]
    pairs=sorted([{"left":a,"right":b} for i,a in enumerate(permissions) for b in permissions[i+1:]],key=canonical_bytes)
    for count in [127,128,129]:
        supplied=request(configuration(permissions=permissions,conflicts=pairs[:count]))
        if count<=128:hold(supplied,transition(supplied,"INITIALIZED"),"Exact incompatible-pair inventory "+str(count)+" is supported.",label="pairs-"+str(count))
        else:deny(supplied,"SCHEMA_INVALID","The129th pair exceeds the closed shape bound.",label="pairs-129",shape=True)
    for count in [255,256,257]:
        grants=[initial_grant("seed-"+str(i).zfill(3),"actor-"+str(i).zfill(3),"APPLY_WORK") for i in range(count)]
        supplied=request(configuration(),grants=grants)
        if count<=256:hold(supplied,transition(supplied,"INITIALIZED"),"Complete active import retains "+str(count)+" distinct grants.",label="grants-"+str(count))
        else:deny(supplied,"SCHEMA_INVALID","An initial257th grant is a closed-shape collection overflow.",label="grants-257",shape=True)
    full_cfg=configuration(); full_seed=request(full_cfg,grants=[initial_grant("seed-"+str(i).zfill(3),"actor-"+str(i).zfill(3),"APPLY_WORK") for i in range(256)])
    full=transition(full_seed,"INITIALIZED")["state"]
    supplied=request(full_cfg,full,kind="GRANT",event_id="grant-capacity",actor="new-actor",permission="APPLY_WORK")
    deny(supplied,"LIMIT_EXCEEDED","A genuine257th retained grant refuses after administration and target checks.",label="projected-grant-capacity")
    supplied=request(full_cfg,full,kind="GRANT",event_id="full-already-held",actor="actor-000",permission="APPLY_WORK")
    hold(supplied,transition(supplied,"UNCHANGED",["ALREADY_HELD"]),"At256 grants a duplicate records because it adds no grant row.",label="full-already-held")
    history=copy.deepcopy(trace[0][1]["state"])
    history_states={1:copy.deepcopy(history)}
    for i in range(2,65):
        supplied=request(config,history,kind="REVOKE" if i>2 else "GRANT",event_id="history-"+str(i).zfill(2),
            at=BEFORE,grant_id="history-grant",permission="APPLY_WORK")
        result=transition(supplied,"GRANTED" if i==2 else "REVOKED" if i==3 else "UNCHANGED",[] if i<=3 else ["NOT_ACTIVE"])
        history=result["state"]; history_states[i]=copy.deepcopy(history)
    supplied=request(config,history_states[63],kind="REVOKE",event_id="event64",at=BEFORE,grant_id="history-grant",permission="APPLY_WORK")
    hold(supplied,transition(supplied,"UNCHANGED",["NOT_ACTIVE"]),"The64th admitted event remains retainable, including a no-op.",label="events-64")
    for label, mutate, code in [
        ("events65","none","LIMIT_EXCEEDED"),
        ("capacity-before-unknown","unknown","LIMIT_EXCEEDED"),
        ("revision-before-capacity","revision","REVISION_CONFLICT"),
        ("admin-before-capacity","admin","ADMINISTRATION_NOT_ESTABLISHED")]:
        supplied=request(config,history,kind="REVOKE",event_id=label,at=BEFORE,grant_id="history-grant",permission="APPLY_WORK")
        if mutate=="unknown":supplied["event"]["payload"]["grant_id"]="unknown-grant";resign(supplied)
        if mutate=="revision":supplied["event"]["expected_revision"]="0"
        if mutate=="admin":supplied["event"]["administration"]=None
        deny(supplied,code,"Selected failure precedence at the64-event ceiling: "+label+".",label=label)
    supplied=copy.deepcopy(trace[0][0]);supplied.update(state=history,state_digest=digest("holdings-state",history))
    hold(supplied,replay(supplied),"At64 events an exact historical initialization replay remains available with current complete state.",label="capacity-replay")
    # Direct current authority cases use synthetic APPLY_WORK; no bank policy is selected.
    supplied,expected=authority()
    emit("evaluate",{"kind":"AUTHORITY","request":supplied},expected,"Complete latest authoritative membership satisfies only the selected executor permission condition.",["HOLD-006"],label="authority-current")
    for label, mutate, reason in [
        ("authority-missing-basis",lambda v:v.pop("holdings_bases"),"HOLDINGS_UNAVAILABLE"),
        ("authority-empty-basis",lambda v:v.update(holdings_bases=[]),"HOLDINGS_UNAVAILABLE"),
        ("authority-unavailable",lambda v:v["holdings_bases"][0]["selection"].update(status="UNAVAILABLE"),"HOLDINGS_UNAVAILABLE"),
        ("authority-conflicting",lambda v:v["holdings_bases"][0]["selection"].update(status="CONFLICTING"),"HOLDINGS_UNAVAILABLE"),
        ("authority-stale-query",lambda v:v["holdings_bases"][0]["selection"].update(at=BEFORE),"HOLDINGS_STALE")]:
        current=copy.deepcopy(supplied);mutate(current)
        emit("evaluate",{"kind":"AUTHORITY","request":current},policy_refusal(current,reason),"Current holdings policy failure: "+label+".",["HOLD-006"],label=label)
    empty_seed=request(configuration());empty_state=transition(empty_seed,"INITIALIZED")["state"]
    current,_=authority(state=empty_state)
    emit("evaluate",{"kind":"AUTHORITY","request":current},policy_refusal(current,"CURRENT_HOLDING_REQUIRED"),"A complete fresh empty registry establishes absence of the required permission.",["HOLD-006"],label="authority-absent")
    for label, end in [("authority-before-end","2026-09-10T04:30:01Z"),("authority-at-end",AT)]:
        seed=request(configuration(),grants=[initial_grant("executor-grant-1","card-machine","APPLY_WORK",end=end)])
        current,ready=authority(state=transition(seed,"INITIALIZED")["state"])
        emit("evaluate",{"kind":"AUTHORITY","request":current},ready if end>AT else policy_refusal(current,"CURRENT_HOLDING_REQUIRED"),"Permission end is exclusive at the exact query instant: "+label+".",["HOLD-004","HOLD-006"],label=label)
    for label, mutate, code in [
        ("authority-duplicate-basis",lambda v:v["holdings_bases"].append(copy.deepcopy(v["holdings_bases"][0])),"BINDING_MISMATCH"),
        ("authority-state-digest",lambda v:v["holdings_bases"][0].update(state_digest="sha256:"+"0"*64),"DIGEST_MISMATCH"),
        ("authority-selection-provider",lambda v:v["holdings_bases"][0]["selection"].update(provider="other-provider"),"DEPENDENCY_MISMATCH"),
        ("authority-state-rehashed",lambda v:v["holdings_bases"][0]["state"]["core"].update(last_clock=AFTER),"STATE_INVALID")]:
        current=copy.deepcopy(supplied);mutate(current)
        if label=="authority-state-rehashed":
            selected=current["holdings_bases"][0];selected["state_digest"]=digest("holdings-state",selected["state"])
            selected["selection"]["state_digest"]=selected["state_digest"]
        emit("evaluate",{"kind":"AUTHORITY","request":current},authority_refusal([],code=code),"Supplied holdings admission is preserved before policy withholding: "+label+".",["HOLD-003","HOLD-006"],label=label)
    # Complete public lifecycle trace binds the exact holdings row into dispatch scope.
    base=lifecycle_base();permitted=permitted_proposal(base)
    emit("deploy",base["deploy_input"],base["deploy_result"],"Deploy the fictional generic permission component using synthetic review carriers; no bank successor gates are selected.",["LIFE-003","HOLD-007"],label="lifecycle-deploy")
    emit("step",step_input(base,base["deploy_result"]["state"],base["clock_event"]),base["clock_result"],"Record the exact proposal and dispatch clock.",["LIFE-014"],label="lifecycle-clock")
    emit("step",step_input(base,base["clock_result"]["state"],base["proposal_event"]),permitted,"Permit after current APPLY_WORK membership and ordinary human authority. Permission alone grants no business authority.",["HOLD-006","LIFE-008"],label="lifecycle-permit")
    auth_event,authorized=dispatch_authorization(base,permitted)
    emit("step",step_input(base,permitted["state"],auth_event),authorized,"Fresh dispatch evaluation retains the complete holdings state and derived row. Authorization expiry is clipped to the permission's04:30:30 exclusive end.",["HOLD-007","LIFE-009B"],label="lifecycle-authorize")
    retained={**authorized,"permit":permitted["permit"]}
    event=dispatch_event(base,retained,event_id="permission-dispatch-1",authorization_digest=authorized["state"]["authorizations"][0]["authorization_digest"])
    event["connector"]=copy.deepcopy(authorized["state"]["authorizations"][0]["connector"])
    dispatched=dispatch_result(retained,event,disposition="DISPATCH_RECORDED",reasons=[],occurrence_status="DISPATCHED")
    emit("step",step_input(base,authorized["state"],event),dispatched,"Retain one exact invocation against the committed permission-bound authorization.",["HOLD-007","LIFE-009"],label="lifecycle-dispatch")
    emit("step",step_input(base,dispatched["state"],event),replay_result(dispatched["state"],event["event_id"]),"Exact dispatch-observation replay retains historical facts and creates no second invocation.",["LIFE-013","HOLD-007"],label="lifecycle-dispatch-replay")
    for label, mutate in [
        ("fence-missing-holdings",lambda v:v["authorization_fence"].pop("holdings")),
        ("fence-wrong-revision",lambda v:v["authorization_fence"]["holdings"][0].update(revision="999")),
        ("fence-wrong-actor",lambda v:v["authorization_fence"]["holdings"][0].update(actor="other-actor")),
        ("fence-wrong-grant",lambda v:v["authorization_fence"]["holdings"][0].update(grant_id="other-grant"))]:
        changed=copy.deepcopy(auth_event);changed["event_id"]=label;mutate(changed)
        emit("step",step_input(base,permitted["state"],changed),stateful_refusal(permitted["state"],"BINDING_MISMATCH"),"Dispatch fence must derive every exact current holdings coordinate: "+label+".",["HOLD-007"],label=label)
    # Keep all original case ids stable when extending the independent tranche.
    for count in [31,32,33]:
        cfg=configuration()
        reqs=[requirement(cfg,requirement_id="permission-requirement-"+str(i).zfill(2)) for i in range(count)]
        current,ready=authority(reqs=reqs)
        emit("evaluate",{"kind":"AUTHORITY","request":current},ready if count<=32 else {"status":"REFUSED","code":"SCHEMA_INVALID","path":""},
            "Exact holdings requirement inventory cardinality "+str(count)+"; the33rd row is closed-schema overflow.",["HOLD-005","HOLD-006"],label="requirements-"+str(count))
    for count in [7,8,9]:
        configs=[configuration(registry_id="generic-registry-"+str(i).zfill(2)) for i in range(count)]
        reqs=[requirement(cfg,requirement_id="registry-requirement-"+str(i).zfill(2)) for i,cfg in enumerate(configs)]
        current,ready=authority(config=configs[0],reqs=reqs)
        selections=[]
        for cfg in configs:
            seeded=request(cfg,grants=[initial_grant("executor-grant-1","card-machine","APPLY_WORK")])
            selections.append(basis(cfg,transition(seeded,"INITIALIZED")["state"]))
        current["holdings_bases"]=sorted(selections,key=lambda row:digest("holdings-configuration",row["configuration"]))
        ready=authority_expected(current,ready)
        emit("evaluate",{"kind":"AUTHORITY","request":current},ready if count<=8 else {"status":"REFUSED","code":"SCHEMA_INVALID","path":""},
            "Generic compound policy names "+str(count)+" distinct complete registry bases. This is not a bypass of the bank's single-registry policy.",["HOLD-005","HOLD-006"],label="bases-"+str(count))
    for label, config_options in [("authority-wrong-principal",{"principal":"other-principal"}),("authority-wrong-clock-source",{"clock_source":"other-clock"})]:
        current,_=authority(config=configuration(**config_options))
        emit("evaluate",{"kind":"AUTHORITY","request":current},authority_refusal([],code="DEPENDENCY_MISMATCH"),
            "A selected internally valid registry must bind the exact authority principal and clock source: "+label+".",["HOLD-006"],label=label)
    current=copy.deepcopy(supplied)
    # Rebuild the direct authority input, since 'supplied' above also names transition inputs.
    current,_=authority();other=configuration(registry_id="unrequested-registry")
    extra=request(other);current["holdings_bases"]=[basis(other,transition(extra,"INITIALIZED")["state"])]
    emit("evaluate",{"kind":"AUTHORITY","request":current},authority_refusal([],code="BINDING_MISMATCH"),
        "An internally valid unrequested configuration is EXTRA even when the requested basis is missing; no replacement intent is inferred.",["HOLD-006"],label="authority-extra-and-missing")
    current,_=authority()
    current["envelope"]["holdings_requirements"][0]["permission"]="UNKNOWN_PERMISSION"
    # This declaration fault is isolated in a freshly constructed envelope with all exact authority dependencies.
    current,_=authority(reqs=[requirement(configuration(),permission="UNKNOWN_PERMISSION")])
    emit("evaluate",{"kind":"AUTHORITY","request":current},authority_refusal([],code="DEPENDENCY_MISMATCH"),
        "The required permission must belong to the selected configuration catalogue before membership policy.",["HOLD-006"],label="authority-unknown-permission")
    for label, mutate in [
        ("selection-state-digest",lambda v:v["holdings_bases"][0]["selection"].update(state_digest="sha256:"+"0"*64)),
        ("selection-revision",lambda v:v["holdings_bases"][0]["selection"].update(revision="999")),
        ("selection-configuration",lambda v:v["holdings_bases"][0]["selection"].update(configuration_digest="sha256:"+"0"*64)),
        ("selection-channel",lambda v:v["holdings_bases"][0]["selection"].update(channel="unprotected-channel"))]:
        current,_=authority();mutate(current)
        emit("evaluate",{"kind":"AUTHORITY","request":current},authority_refusal([],code="DEPENDENCY_MISMATCH"),
            "Exact protected selection must bind its full registry identity: "+label+".",["HOLD-006"],label=label)
    for kind in ["DECIDE","VERIFY"]:
        current,ready=ordinary_gate_authority(gate_kind=kind)
        emit("evaluate",{"kind":"AUTHORITY","request":current},ready,
            "Generic REVIEW_WORK belongs to the exact admitted ordinary "+kind+" actor, independently of executor identity. This selects no bank reviewer policy.",["HOLD-006"],label="gate-actor-"+kind.lower())
        wrong,_=ordinary_gate_authority(holding_actor="card-machine",gate_kind=kind)
        emit("evaluate",{"kind":"AUTHORITY","request":wrong},policy_refusal(wrong,"CURRENT_HOLDING_REQUIRED",actor="person-grantor"),
            "The executor's permission cannot substitute for the exact ordinary "+kind+" gate actor's permission.",["HOLD-006"],label="gate-actor-wrong-"+kind.lower())
    # Build a reachable exhausted current registry with the exact required permission still present.
    cfg=configuration();seed=request(cfg,grants=[initial_grant("executor-grant-1","card-machine","APPLY_WORK")])
    exhausted=transition(seed,"INITIALIZED")["state"]
    for i in range(2,65):
        no_op=request(cfg,exhausted,kind="GRANT",event_id="exhaustion-"+str(i).zfill(2),
            grant_id="unused-grant-"+str(i).zfill(2),actor="card-machine",permission="APPLY_WORK")
        exhausted=transition(no_op,"UNCHANGED",["ALREADY_HELD"])["state"]
    current,_=authority(config=cfg,state=exhausted)
    emit("evaluate",{"kind":"AUTHORITY","request":current},policy_refusal(current,"HOLDINGS_CAPACITY_EXHAUSTED"),
        "At64 events the permission remains present, but new business authority withholds because no future revocation could be retained.",["HOLD-005","HOLD-006"],label="authority-history-exhausted")
    for label, status in [("dispatch-unavailable","UNAVAILABLE"),("dispatch-conflicting","CONFLICTING")]:
        current=copy.deepcopy(auth_event["authority_input"]);current["holdings_bases"][0]["selection"]["status"]=status
        failed=policy_refusal(current,"HOLDINGS_UNAVAILABLE")
        changed,result=dispatch_authorization(base,permitted,supplied=current,event_id=label,failure=failed)
        emit("step",step_input(base,permitted["state"],changed),result,
            "Fresh dispatch holdings selection "+status+" records WITHHELD, despite a valid proposal snapshot.",["HOLD-007"],label=label)
    revoked_input=request(base["holdings_configuration"],base["holdings_state"],kind="REVOKE",event_id="executor-revoke-before-dispatch",
        at=AT,grant_id="executor-grant-1",actor="card-machine",permission="APPLY_WORK")
    revoked_state=transition(revoked_input,"REVOKED")["state"]
    current=copy.deepcopy(auth_event["authority_input"]);current["holdings_bases"]=[basis(base["holdings_configuration"],revoked_state)]
    failed=policy_refusal(current,"CURRENT_HOLDING_REQUIRED")
    changed,result=dispatch_authorization(base,permitted,supplied=current,event_id="dispatch-after-revoke",failure=failed)
    emit("step",step_input(base,permitted["state"],changed),result,
        "A current authorized revoke after proposal prevents fresh dispatch; the historical permit is not a current permission grant.",["HOLD-004","HOLD-007"],label="dispatch-after-revoke")
    current=copy.deepcopy(auth_event["authority_input"]);current["holdings_bases"]=[basis(cfg,exhausted)]
    failed=policy_refusal(current,"HOLDINGS_CAPACITY_EXHAUSTED")
    changed,result=dispatch_authorization(base,permitted,supplied=current,event_id="dispatch-exhausted",failure=failed)
    emit("step",step_input(base,permitted["state"],changed),result,
        "Fresh dispatch stops at exhausted history even though current membership is active.",["HOLD-005","HOLD-007"],label="dispatch-exhausted")
    # Exact bank R1 exclusion component, without a successor bank authority gate.
    bank_cfg=configuration(principal="MRB-US-01",registry_id="bank-permissions",permissions=["SAR_APPROVE","SAR_PREPARE","SAR_SUBMIT"],
        conflicts=[{"left":"SAR_APPROVE","right":"SAR_PREPARE"},{"left":"SAR_APPROVE","right":"SAR_SUBMIT"}])
    for held,wanted,decision,reason in [
        ("SAR_APPROVE","SAR_PREPARE","WITHHELD",["CONFLICTING_HOLDING"]),
        ("SAR_APPROVE","SAR_SUBMIT","WITHHELD",["CONFLICTING_HOLDING"]),
        ("SAR_PREPARE","SAR_SUBMIT","GRANTED",[])]:
        seed=request(bank_cfg,grants=[initial_grant("bank-existing-grant","bank-actor-1",held)])
        seeded=transition(seed,"INITIALIZED")["state"]
        supplied=request(bank_cfg,seeded,kind="GRANT",event_id="bank-"+held+"-"+wanted,actor="bank-actor-1",permission=wanted)
        hold(supplied,transition(supplied,decision,reason),"Existing bank revision1 explicitly selects "+held+" with "+wanted+" for the same actor. No mandatory preparation or current-reviewer gate is inferred.",label="bank-"+held+"-"+wanted,requirements=["HOLD-001","HOLD-004"])
    current,ready,selected_actor=independent_gate_authority()
    emit("evaluate",{"kind":"AUTHORITY","request":current},ready,
        "An added generic REVIEW_WORK condition resolves the exact Cedar decision selected by gate.decision_requirement, preserving both historical human decisions and their current reliance. This is a generic mechanism probe, not a bank policy.",["HOLD-006","AUTH-008"],label="independent-selected-gate-actor")
    wrong,_,selected_actor=independent_gate_authority(holding_actor="alder-quality-reviewer-01")
    # Use the real nonselected leaf's actor rather than a guessed alias.
    unselected=next(row["evidence"] for row in wrong["decision_bases"] if row["requirement_id"]!=wrong["envelope"]["gate"]["decision_requirement"])
    unselected_actor=next(row["actor"] for row in unselected["authority_input"]["acts"] if digest("authority-act",row)==unselected["decision_act_digest"])
    wrong,_,selected_actor=independent_gate_authority(holding_actor=unselected_actor)
    failed=policy_refusal(wrong,"CURRENT_HOLDING_REQUIRED",actor=selected_actor)
    failed["decision_results"]=copy.deepcopy(ready["decision_results"])
    emit("evaluate",{"kind":"AUTHORITY","request":wrong},failed,
        "A different successful independent leaf's current permission cannot substitute for the exactly selected gate decision actor. Preserve both complete underlying decision results.",["HOLD-006","AUTH-008"],label="independent-nongate-holder")
    for label, reqs, code in [
        ("requirements-duplicate",[requirement(configuration()),requirement(configuration())],"INPUT_INVALID"),
        ("requirements-unsorted",[requirement(configuration(),requirement_id="z"),requirement(configuration(),requirement_id="a")],"INPUT_INVALID"),
        ("requirements-unknown-step",[requirement(configuration(),step="unknown-step")],"REFERENCE_INVALID"),
        ("gate-actor-none",[requirement(configuration(),actor="GATE_ACTOR",permission="REVIEW_WORK")],"UNSUPPORTED_RELATION")]:
        def configure(value,_original):value["envelope"].update(holdings_requirements=copy.deepcopy(reqs))
        raw,_=authority_specimen(shared_budget=False,mutator=configure)
        emit("evaluate",{"kind":"AUTHORITY","request":raw},authority_refusal([],code=code),
            "Static holdings declaration admission precedes current permission checks: "+label+".",["HOLD-006"],label=label)
    future_seed=request(configuration(),at=AFTER,grants=[initial_grant("executor-grant-1","card-machine","APPLY_WORK")])
    current,_=authority(state=transition(future_seed,"INITIALIZED")["state"])
    emit("evaluate",{"kind":"AUTHORITY","request":current},policy_refusal(current,"HOLDINGS_STALE"),
        "A current query before the registry's retained last clock is stale even when protected selection.at equals the query.",["HOLD-006"],label="query-before-state-clock")
    for label, with_empty in [("no-holdings-omitted",False),("no-holdings-explicit-empty",True)]:
        current,ready=authority_specimen(shared_budget=False)
        if with_empty:current["holdings_bases"]=[]
        ready=authority_expected(current,ready)
        emit("evaluate",{"kind":"AUTHORITY","request":current},ready,
            "No selected permission condition preserves ordinary readiness; explicit empty evidence remains distinct digest bytes: "+label+".",["HOLD-006"],label=label)
    for source_count,accept in [(32,True),(33,False)]:
        combined=lifecycle_base(requirement_count=32,source_count=source_count)
        result=permitted_proposal(combined) if accept else stateful_refusal(combined["clock_result"]["state"],"LIMIT_EXCEEDED")
        emit("step",step_input(combined,combined["clock_result"]["state"],combined["proposal_event"]),result,
            "The selected source-plus-holdings projection has "+str(source_count+32)+" members. The combined64 ceiling applies before proposal permit issuance.",["HOLD-007"],label="combined-projection-"+str(source_count+32))
    # Natural expiry/regrant retains immutable old identifiers and exact target semantics.
    cfg=configuration();seed=request(cfg,grants=[initial_grant("old-apply-grant","card-machine","APPLY_WORK",end=AT)])
    expired_state=transition(seed,"INITIALIZED")["state"]
    grant=request(cfg,expired_state,kind="GRANT",event_id="regrant-after-natural-expiry",at=AT,
        grant_id="new-apply-grant",actor="card-machine",permission="APPLY_WORK")
    new_grant=transition(grant,"GRANTED")
    hold(grant,new_grant,"At the exact old exclusive end a fresh immutable grant may establish current permission again; it does not alter old grant history.",label="natural-expiry-regrant")
    old_target=request(cfg,new_grant["state"],kind="REVOKE",event_id="revoke-expired-old-identity",at=AT,
        grant_id="old-apply-grant",actor="card-machine",permission="APPLY_WORK")
    hold(old_target,transition(old_target,"UNCHANGED",["NOT_ACTIVE"]),"An old expired revoke cannot remove a new active grant of the same permission for the same actor.",label="old-revoke-new-same-permission")
    current,ready=authority(config=cfg,state=new_grant["state"])
    emit("evaluate",{"kind":"AUTHORITY","request":current},ready,"Fresh current evaluation may use an authorized replacement permission. No approval no-revival policy is inferred.",["HOLD-004","HOLD-006"],label="authority-regrant-current")
    cfg=configuration();seed=request(cfg,grants=[initial_grant("vendor-existing","actor-one","VENDOR_MASTER_MAINTENANCE")])
    seeded=transition(seed,"INITIALIZED")["state"]
    separate=request(cfg,seeded,kind="GRANT",event_id="distinct-actor-compatible",actor="actor-two",permission="AP_PAYMENT_RELEASE")
    hold(separate,transition(separate,"GRANTED"),"A same-actor incompatible pair does not prohibit its two permissions for two distinct canonical actors. Canonical identity resolution remains a host premise.",label="distinct-actors")
    cfg=configuration();grants=[initial_grant("seed-"+str(i).zfill(3),"actor-"+str(i).zfill(3),"VENDOR_MASTER_MAINTENANCE" if i==0 else "APPLY_WORK") for i in range(256)]
    full_seed=request(cfg,grants=grants);full=transition(full_seed,"INITIALIZED")["state"]
    conflict=request(cfg,full,kind="GRANT",event_id="full-conflict-recordable",actor="actor-000",permission="AP_PAYMENT_RELEASE")
    hold(conflict,transition(conflict,"WITHHELD",["CONFLICTING_HOLDING"]),"At256 retained grants a current conflict still records if event room exists, because it adds no grant row.",label="full-conflict")
    exhausted_init=request(configuration(),exhausted,kind="INITIALIZE",event_id="exhausted-new-initialize")
    deny(exhausted_init,"LIMIT_EXCEEDED","At64 retained events event-history capacity precedes the fresh initialized-state target check.",label="exhausted-before-new-initialize")
    # A changed identity namespace/configuration cannot silently reuse an old registry history.
    namespace=request(configuration(),base["holdings_state"],kind="GRANT",event_id="changed-identity-namespace",actor="different-alias",permission="APPLY_WORK")
    namespace["configuration"]["identity_revision"]="identity-revision-2";resign(namespace)
    deny(namespace,"DEPENDENCY_MISMATCH","A changed identity revision changes the immutable configuration digest and cannot reset the established registry's actor inventory.",label="identity-revision-substitution",requirements=["HOLD-001","HOLD-003"])
    # Absent and explicit-empty declarations both preserve old semantics; an unsolicited basis is extra.
    current,ready=authority_specimen(shared_budget=False)
    cfg=configuration();seed=request(cfg)
    current["holdings_bases"]=[basis(cfg,transition(seed,"INITIALIZED")["state"])]
    emit("evaluate",{"kind":"AUTHORITY","request":current},authority_refusal([],code="BINDING_MISMATCH"),
        "A complete but unrequested registry basis is extra even when the envelope declares no holdings condition.",["HOLD-006"],label="basis-without-requirement")
    for label, where in [("basis-config-pin-before-envelope-digest","configuration"),("basis-state-pin-before-envelope-digest","state")]:
        current,_=authority()
        current["host_selection"]["root"]["envelope_digest"]="sha256:"+"0"*64
        current["holdings_bases"][0][where]["specification_pin"]="sha256:"+"1"*64
        emit("evaluate",{"kind":"AUTHORITY","request":current},authority_refusal([],code="VERSION_UNSUPPORTED"),
            "Phase2VERSION_UNSUPPORTED from a supplied holdings "+where+" precedes inherited wrong-envelope DEPENDENCY_MISMATCH.",["HOLD-006","AUTH-006"],label=label)
    current,_=authority();current["holdings_bases"][0]["selection"].update(at="2026-02-30T04:30:00Z",status="UNAVAILABLE")
    emit("evaluate",{"kind":"AUTHORITY","request":current},authority_refusal([],code="CLOCK_INVALID"),
        "A structurally present invalid current selection calendar instant is an admission fault even when selection status is UNAVAILABLE.",["HOLD-006"],label="selection-invalid-calendar-unavailable")
    cfg_a=configuration(registry_id="priority-registry-a");cfg_b=configuration(registry_id="priority-registry-b")
    reqs=[requirement(cfg_a,requirement_id="a"),requirement(cfg_b,requirement_id="b")]
    current,_=authority(config=cfg_a,reqs=reqs)
    seed_b=request(cfg_b,grants=[initial_grant("executor-grant-1","card-machine","APPLY_WORK")])
    basis_a=current["holdings_bases"][0];basis_b=basis(cfg_b,transition(seed_b,"INITIALIZED")["state"])
    basis_a["state_digest"]="sha256:"+"0"*64
    basis_b["selection"]["at"]="2026-02-30T04:30:00Z"
    for label,order in [("multiple-bases-digest-first",[basis_a,basis_b]),("multiple-bases-calendar-first",[basis_b,basis_a])]:
        changed=copy.deepcopy(current);changed["holdings_bases"]=copy.deepcopy(order)
        emit("evaluate",{"kind":"AUTHORITY","request":changed},authority_refusal([],code="DIGEST_MISMATCH"),
            "Phase2collects independently checkable supplied-basis faults; DIGEST_MISMATCH precedes CLOCK_INVALID regardless of array order.",["HOLD-006","AUTH-006"],label=label)
    current,_=authority();selected=current["holdings_bases"][0]
    selected["state"]["core"]["last_clock"]=AFTER
    selected["state_digest"]=digest("holdings-state",selected["state"])
    selected["selection"].update(state_digest=selected["state_digest"],at="2026-02-30T04:30:00Z")
    emit("evaluate",{"kind":"AUTHORITY","request":current},authority_refusal([],code="STATE_INVALID"),
        "Phase2unreachable retained history precedes independently invalid current selection calendar time.",["HOLD-003","HOLD-006"],label="state-before-selection-calendar")
    from lifecycle_factory import base_lifecycle
    for label, legacy_gate in [("holdings-lifecycle-no-gate",False),("holdings-lifecycle-legacy-gate",True)]:
        def configure(value,_original):
            if legacy_gate:
                from equipment_observation_fixture import _configure
                _configure(value,gated=True,include_session=True)
            value["envelope"]["holdings_requirements"]=[requirement(configuration())]
        invalid=base_lifecycle(authority_mutator=configure)
        emit("step",step_input(invalid,invalid["clock_result"]["state"],invalid["proposal_event"]),stateful_refusal(invalid["clock_result"]["state"],"UNSUPPORTED_RELATION"),
            "A lifecycle permission requirement requires SOURCE_REQUIREMENTS before permit creation, including when current permission evidence is also missing.",["HOLD-007"],label=label)
    return rows,labels,{"quinn":trace,"base":base,"permitted":permitted,"authorization_event":auth_event,"authorized":authorized,"dispatch_event":event,"dispatched":dispatched}


def main():
    rows,labels,facts=build()
    write_canonical_json(CONFORMANCE/"typescript/test-data/holdings-retained-checkpoints.json",retained_checkpoints())
    for row in rows:write_canonical_json(GROUP/(row["id"]+".json"),row)
    role=exact_case("C3-HOLD-ROLE-001","holdings-step",facts["quinn"][0][0],{"status":"REFUSED","code":"ROLE_UNSUPPORTED","path":""},["WCS2-011","HOLD-002"],"A capability-limited adapter omits HOLDINGS_TRANSITIONS and refuses before admitting a state.")
    write_canonical_json(GROUP/(role["id"]+".json"),role);rows.append(role)
    SPECIMEN.mkdir(parents=True,exist_ok=True)
    (SPECIMEN/"source-packet.md").write_bytes(SOURCE.read_bytes())
    streams={"quinn-transitions":[row for row in rows if row["id"] in [labels["quinn-"+str(i)] for i in range(1,6)]],
        "valid-dispatch":[row for row in rows if row["id"] in [labels["lifecycle-"+s] for s in ["deploy","clock","permit","authorize","dispatch","dispatch-replay"]]]}
    for name,stream in streams.items():
        target=SPECIMEN/name;target.mkdir(parents=True,exist_ok=True)
        requests=[{"protocol":"seampoint.work-class.adapter/1.0.0-draft.3","request_id":row["id"],"operation":row["operation"],"input":row["input"]} for row in stream]
        (target/"requests.jsonl").write_bytes(b"".join(canonical_bytes(row)+b"\n" for row in requests))
        write_canonical_json(target/"results-derived.json",[row["expected"] for row in stream])
    write_canonical_json(SPECIMEN/"authority-input.json",next(row["input"]["request"] for row in rows if row["id"]==labels["authority-current"]))
    write_canonical_json(SPECIMEN/"authority-result-derived.json",next(row["expected"] for row in rows if row["id"]==labels["authority-current"]))
    inventory={"candidate_pin":candidate_pin(),"source_sha256":sha(SOURCE),"cases":[{"id":row["id"],"path":"../../cases/holdings/"+row["id"]+".json","raw_sha256":sha(GROUP/(row["id"]+".json"))} for row in rows]}
    write_canonical_json(SPECIMEN/"case-inventory.json",inventory)
    clause_norms={"1":["HOLD-001"],"2":["HOLD-002"],"3":["HOLD-002"],"4":["HOLD-004"],"5":["HOLD-003","HOLD-005"],
        "6":["HOLD-005"],"7":["HOLD-005"],"8":["HOLD-006"],"9":["HOLD-006","HOLD-007"],"10":["HOLD-007"],"11":["HOLD-008"],"12":["HOLD-008"]}
    coverage={"candidate_pin":candidate_pin(),"status":"DEVELOPMENT_COMPONENT_NOT_INDUSTRY_ACCEPTANCE","source":str(SOURCE.relative_to(ROOT)),"source_sha256":sha(SOURCE),
        "coverage":[{"requirement":req,"case_ids":[row["id"] for row in rows if req in row["requirements"]]} for req in ["HOLD-00"+str(i) for i in range(1,9)]],
        "source_clauses":[{"selected_component_rule":number,"normative_references":refs,"case_ids":[row["id"] for row in rows if set(refs)&set(row["requirements"])],
            "scope":"HOST_SCENARIOS_AND_EXTERNAL_OBLIGATIONS" if number in ["11","12"] else "COMPLETE_ADAPTER_CASES_WITH_EXPLICIT_HOST_PREMISES"}
            for number,refs in clause_norms.items()],
        "host_judgment_inventory":"runs/2026-10-08-holdings/source/holdings-host-expected-judgments-02.json",
        "byte_boundary_inventory":"runs/2026-10-08-holdings/source/byte-boundary-freeze-01/manifest.json",
        "host_residue":["canonical actor resolution","authenticated complete inventory and latest-state selection","all relevant writer participation","durable custody and recovery","protected reader authorization","actual native provider integration"],
        "deferred":["Quinn prerequisites","approved exceptions","bank mandatory preparation and reviewer permission policy","complete bank filing and customer-communication workflow"]}
    write_canonical_json(SPECIMEN/"source-coverage.json",coverage)
    artifacts=[path for path in SPECIMEN.rglob('*') if path.is_file() and path.name!='artifact-index.json']
    write_canonical_json(SPECIMEN/"artifact-index.json",{"candidate_pin":candidate_pin(),"artifacts":[{"path":str(path.relative_to(SPECIMEN)),"sha256":sha(path)} for path in sorted(artifacts)]})
    print(json.dumps({"candidate_pin":candidate_pin(),"cases":len(rows),"labels":labels},indent=2))


if __name__=="__main__":main()
