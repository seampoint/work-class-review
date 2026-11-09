"""Source-selected information-flow facts and complete expected records.

Decisions and complete next-state deltas are explicit source judgments. This module
imports review constructors only, never consumers, schemas or observed outputs.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from corpus_common import CONFORMANCE, candidate_pin, canonical_bytes, digest
from authority_fixture import authority_refusal
from assessment_fixture import (base_authority, expected_authority as ordinary_expected, rebind_outer,
    fields, typed, TYPES, native_values, authority as assessment_authority, reliance_subject, local_bodies, human_leaf, current_requirements, APPROVAL)
from equipment_observation_fixture import observation, requirement


SCHEMA = "seampoint.work-class/1.0.0-draft.3/"


def ordered(rows):
    return sorted(copy.deepcopy(rows), key=canonical_bytes)


def configuration(*, principal, registry_id, scope, restriction_id, meaning,
                  releasable=False, release_role=None):
    return {
        "schema": SCHEMA + "flow-configuration",
        "specification_pin": candidate_pin(),
        "id": registry_id,
        "principal": principal,
        "provider": "synthetic-flow-host.invalid",
        "source": "protected-flow-registry",
        "protected_channel": "protected-flow-control",
        "clock_source": "synthetic-flow-clock",
        "control_interface": "synthetic-protected-mediator",
        "access_operation": "admit-exact-input",
        "transfer_operation": "transfer-exact-artifact",
        "response_operation": "read-protected-flow-result",
        "response_role": "protected-flow-reader",
        "restrictions": [{"id": restriction_id, "scope": scope,
            "meaning": meaning, "releasable": releasable,
            "release_role": release_role}],
    }


def source_descriptor(*, provider, source, record_type, record_id, revision,
                      content_digest, scope, restrictions):
    return {
        "provider": provider, "source": source, "record_type": record_type,
        "record_id": record_id, "revision": revision,
        "content_digest": content_digest, "scope": scope,
        "restrictions": sorted(restrictions),
    }


def context(*, context_id, actor, scope, purpose, ceiling, restrictions=(),
            origins=(), revision="1"):
    return {
        "id": context_id, "actor": actor, "scope": scope, "purpose": purpose,
        "revision": revision, "ceiling": sorted(ceiling),
        "restrictions": sorted(restrictions),
        "origins": sorted(copy.deepcopy(origins),
            key=lambda row: digest("flow-source", row).encode()),
    }


def event(config, state, *, kind, event_id, payload, at):
    return {
        "schema": SCHEMA + "flow-event", "id": event_id, "kind": kind,
        "expected_revision": "0" if state is None else state["core"]["revision"],
        "expected_state_digest": None if state is None else digest("flow-state", state),
        "clock": {"source": config["clock_source"], "status": "AVAILABLE", "instant": at},
        "payload": copy.deepcopy(payload),
    }


def control_subject(config, selected_event):
    projection = copy.deepcopy(selected_event)
    projection["payload"].pop("access_authority", None)
    projection["payload"].pop("transfer_authority", None)
    return digest("flow-control-subject", {
        "configuration_digest": digest("flow-configuration", config),
        "event": projection,
    })


def host_evidence(config, selected_event):
    """Construct the exact positive attestations selected in root's proposed companion."""
    payload, kind = selected_event["payload"], selected_event["kind"]
    attestations = []
    selected = {
        "CREATE_CONTEXT": ("INITIAL_INVENTORY", "flow-initial-inventory", payload),
        "READ": ("SOURCE_CLASSIFICATION", "flow-source", payload.get("source")),
        "MATERIALIZE": ("MATERIALIZED_CONTENT", "flow-materialized-content",
            {key: copy.deepcopy(payload[key]) for key in ("types", "fields")}
            if kind == "MATERIALIZE" else None),
    }.get(kind)
    if selected is not None:
        attestation_kind, domain, body = selected
        attestations = [{
            "kind": attestation_kind, "subject_digest": digest(domain, body),
            "provider": config["provider"], "source": config["source"],
            "channel": config["protected_channel"],
            "evidence_ref": "protected-" + selected_event["id"],
        }]
    return {
        "configuration_digest": digest("flow-configuration", config),
        "event_subject_digest": control_subject(config, selected_event),
        "selection_evidence": "protected-current-flow-configuration",
        "attestations": ordered(attestations),
    }


def request(config, state, selected_event, evidence, *, response_at=None):
    supplied = {
        "schema": SCHEMA + "flow-input", "specification_pin": candidate_pin(),
        "configuration": copy.deepcopy(config), "state": copy.deepcopy(state),
        "state_digest": None if state is None else digest("flow-state", state),
        "event": copy.deepcopy(selected_event), "host_evidence": copy.deepcopy(evidence),
    }
    refresh_response(supplied, at=response_at)
    return supplied


def transition(supplied, decision, *, contexts, artifacts, claims,
               consumed_release_acts=(), authority_results=()):
    """Retain an explicit independently chosen complete next core and result list."""
    config, selected_event = supplied["configuration"], supplied["event"]
    prior = supplied["state"]
    core = {
        "configuration_digest": digest("flow-configuration", config),
        "revision": str(1 if prior is None else int(prior["core"]["revision"]) + 1),
        "last_clock": selected_event["clock"]["instant"],
        "contexts": sorted(copy.deepcopy(contexts), key=lambda row: row["id"].encode()),
        "artifacts": sorted(copy.deepcopy(artifacts), key=lambda row: row["id"].encode()),
        "claims": sorted(copy.deepcopy(claims), key=lambda row: row["id"].encode()),
        "consumed_release_acts": sorted(consumed_release_acts),
    }
    event_digest = digest("flow-event", {
        "event": selected_event, "host_evidence": supplied["host_evidence"],
    })
    receipt = {
        "schema": SCHEMA + "flow-receipt", "event_id": selected_event["id"],
        "event_digest": event_digest, "state_before_digest": supplied["state_digest"],
        "revision": core["revision"], "core_after_digest": digest("flow-core", core),
        "decision": decision,
        "authority_result_digests": [digest("authority-result", row) for row in authority_results],
        "authority_evidence_digests": [row["evidence_digest"] for row in authority_results],
        "protected_channel": config["protected_channel"],
    }
    receipt_digest = digest("flow-receipt", receipt)
    record = {
        "event": copy.deepcopy(selected_event),
        "host_evidence": copy.deepcopy(supplied["host_evidence"]),
        "event_digest": event_digest, "receipt": copy.deepcopy(receipt),
        "receipt_digest": receipt_digest,
    }
    state = {
        "schema": SCHEMA + "flow-state", "specification_pin": candidate_pin(),
        "core": core,
        "records": [*copy.deepcopy(prior["records"] if prior else []), record],
    }
    return {
        "status": "TRANSITION", "receipt": receipt,
        "receipt_digest": receipt_digest, "state": state,
        "state_digest": digest("flow-state", state), "replay": False,
    }


def refusal(supplied, code, *, shape=False):
    if shape:
        return {"status": "REFUSED", "code": code, "path": ""}
    return {
        "status": "REFUSED", "code": code, "path": "",
        "state": copy.deepcopy(supplied["state"]), "state_digest": supplied["state_digest"],
    }


def replay(supplied):
    record = next(row for row in supplied["state"]["records"]
        if row["event"]["id"] == supplied["event"]["id"])
    return {
        "status": "TRANSITION", "receipt": copy.deepcopy(record["receipt"]),
        "receipt_digest": record["receipt_digest"],
        "state": copy.deepcopy(supplied["state"]), "state_digest": supplied["state_digest"],
        "replay": True,
    }


def basis(config, state, *, requirement_id, at, released_restrictions=(),
          status="AVAILABLE"):
    config_digest, state_digest = digest("flow-configuration", config), digest("flow-state", state)
    return {
        "requirement_id": requirement_id,
        "configuration": copy.deepcopy(config), "state": copy.deepcopy(state),
        "state_digest": state_digest,
        "selection": {
            "configuration_digest": config_digest, "state_digest": state_digest,
            "revision": state["core"]["revision"], "provider": config["provider"],
            "source": config["source"], "channel": config["protected_channel"],
            "at": at, "status": status,
            "selection_evidence": "protected-latest-flow-registry",
        },
        "released_restrictions": sorted(released_restrictions),
    }


def materialized_artifact(producer, *, artifact_id, types, fields):
    return {
        "id": artifact_id, "context_id": producer["id"],
        "context_revision": producer["revision"],
        "context_digest": digest("flow-context", producer),
        "types": copy.deepcopy(types), "fields": copy.deepcopy(fields),
        "restrictions": copy.deepcopy(producer["restrictions"]),
        "origins": copy.deepcopy(producer["origins"]),
    }


def disclosure_subject(supplied, req, selected_basis, sender, artifact):
    proposal = supplied["proposal"]
    recipient = next(row["value"]["value"] for row in proposal["fields"]
        if row["name"] == req["recipient_field"])
    body = {
        "principal": proposal["executor"]["principal"],
        "configuration_digest": digest("flow-configuration", selected_basis["configuration"]),
        "policy_digest": digest("flow-policy", req["policy"]),
        "context_digest": digest("flow-context", sender),
        "artifact_digest": digest("flow-artifact", artifact),
        **{key: copy.deepcopy(proposal[key]) for key in (
            "work_class_digest", "instance", "occurrence", "step", "interface", "operation", "fields")},
        "recipient": recipient, "channel": req["channel"], "purpose": req["purpose"],
        "intent_id": req["intent_id"], "claim_id": req["claim_id"],
        "released_restrictions": copy.deepcopy(selected_basis["released_restrictions"]),
    }
    return body, digest("flow-disclosure-subject", body)


def flow_check(req, sender, artifact, *, recipient, at, reason=None):
    subject = digest("flow-query", {
        "requirement_id": req["id"], "context_digest": digest("flow-context", sender),
        "artifact_digest": digest("flow-artifact", artifact), "intent_id": req["intent_id"], "claim_id": req["claim_id"],
        "recipient": recipient, "channel": req["channel"], "purpose": req["purpose"], "at": at,
    })
    row = {"purpose": "FLOW", "subject_digest": subject, "requirement_ref": req["id"], "at": at}
    if reason is not None:
        row["reason"] = reason
    return row


def authority_evidence(supplied):
    evidence = {key: copy.deepcopy(supplied[key]) for key in (
        "host_selection", "occupancies", "capacities", "credentials", "acts",
        "returns", "observations", "clock")}
    for key in ("evaluation_point", "decision_bases", "assessment_bases",
                "holdings_bases", "flow_bases"):
        if key in supplied:
            evidence[key] = copy.deepcopy(supplied[key])
    return evidence


def authority_expected(supplied, ordinary_expected, *, req=None, sender=None,
                       artifact=None, recipient=None):
    """Extend an explicitly selected positive ordinary result, without policy inference."""
    result = copy.deepcopy(ordinary_expected)
    if req is not None:
        result["checks"] = ordered([*result["checks"], flow_check(
            req, sender, artifact, recipient=recipient, at=supplied["clock"]["instant"])])
    result["evidence_digest"] = digest("authority-evidence", authority_evidence(supplied))
    return result


def policy_refusal(supplied, ordinary_expected, *, req, sender, artifact,
                   recipient, reasons, other_failed_checks=()):
    """Build the independently chosen exact failed-check union, never choose a denial."""
    failed = [*copy.deepcopy(other_failed_checks), *[
        flow_check(req, sender, artifact, recipient=recipient,
            at=supplied["clock"]["instant"], reason=reason)
        for reason in reasons]]
    failed = sorted({canonical_bytes(row): row for row in failed}.values(), key=canonical_bytes)
    result = authority_refusal(failed)
    if "decision_results" in ordinary_expected:
        result["decision_results"] = copy.deepcopy(ordinary_expected["decision_results"])
    return result


def authority_projection(supplied):
    projection = copy.deepcopy(supplied)
    projection["flow_bases"][0].pop("state")
    return projection


def expanded_projection(projection, state):
    """Construct the chosen complete body; runtime admission is deliberately absent."""
    expanded = copy.deepcopy(projection)
    expanded["flow_bases"][0]["state"] = copy.deepcopy(state)
    return expanded


def claim(*, claim_id, intent_id, kind, context_id, recipient, channel, purpose,
          subject_digest, release_act_digest=None):
    return {
        "id": claim_id, "intent_id": intent_id, "status": "POSSIBLE_EXPOSURE", "kind": kind, "context_id": context_id,
        "recipient": recipient, "channel": channel, "purpose": purpose,
        "subject_digest": subject_digest, "release_act_digest": release_act_digest,
    }


def delivery_claim(supplied, receiver):
    selected_event = supplied["event"]
    return claim(
        claim_id=selected_event["payload"]["claim_id"], intent_id=selected_event["payload"]["intent_id"], kind=selected_event["kind"],
        context_id=receiver["id"], recipient=receiver["id"],
        channel=supplied["configuration"]["control_interface"], purpose=receiver["purpose"],
        subject_digest=control_subject(supplied["configuration"], selected_event),
    )


def access_authority(config, selected_event, selected_context, *, role, source,
                     transfer=False, actor_kind="MACHINE", explicit_empty=False, response=False, subject_override=None, class_id_override=None):
    """Build chosen exact mediator authority from an explicit source policy body.

    The control operation admits one exact transfer/input. It performs no native
    customer send and creates no content release. Its selected source must provide
    the business-role/read remit; the generic registry cannot infer that remit.
    """
    subject = subject_override or control_subject(config, selected_event)
    operation = config["response_operation"] if response else config["transfer_operation"] if transfer else config["access_operation"]
    class_id = class_id_override or "flow-control-" + selected_event["id"] + ("-response" if response else "-transfer" if transfer else "-access")
    values = {"admission_subject": {"type_ref": "IDENTITY", "value": subject}}
    work = {
        "schema": SCHEMA + "authority-work-class", "id": class_id, "revision": "1",
        "types": [{"id": "IDENTITY", "kind": "IDENTITY", "nonnegative": False, "unit": None}],
        "steps": [{
            "id": operation, "interface": config["control_interface"], "operation": operation,
            "executor_role": role, "fields": [{"name": "admission_subject", "type_ref": "IDENTITY"}],
            "scope_fields": {"subjects": ["admission_subject"], "resources": ["admission_subject"]},
            "required_credentials": [], "quantity_mode": "NONE", "exclusive_keys": [],
        }],
    }
    supplied = base_authority(
        work, values, principal=config["principal"], role=role, actor=selected_context["actor"],
        now=selected_event["clock"]["instant"], instance="flow-control-instance-" + selected_context["id"],
        occurrence="flow-control-occurrence-" + selected_event["id"])
    old_credentials = {digest("authority-credential", row) for row in supplied["credentials"]}
    supplied["credentials"] = []
    supplied["observations"] = [row for row in supplied["observations"]
        if row["query"]["subject_digest"] not in old_credentials]
    supplied["source"] = copy.deepcopy(source)
    supplied["envelope"]["source_obligations"] = sorted(row["id"] for row in source["obligations"])
    supplied["envelope"]["gate"] = {
        "materiality": "LOW", "reversibility": "HIGH", "kind": "NONE", "role": None, "criteria": [],
    }
    supplied["envelope"]["clock_source"] = config["clock_source"]
    supplied["clock"]["source"] = config["clock_source"]
    next(row for row in supplied["occupancies"]
        if row["id"] == supplied["proposal"]["executor"]["occupancy"])["kind"] = actor_kind
    if explicit_empty:
        supplied["flow_bases"] = []
        supplied["envelope"]["flow_requirements"] = []
    rebind_outer(supplied)
    result = ordinary_expected(supplied)
    result["evidence_digest"] = digest("authority-evidence", authority_evidence(supplied))
    return supplied, result


def exposure_claim(supplied, req, selected_basis, sender, artifact, *, release_act_digest=None):
    _, subject = disclosure_subject(supplied, req, selected_basis, sender, artifact)
    recipient = next(row["value"]["value"] for row in supplied["proposal"]["fields"]
        if row["name"] == req["recipient_field"])
    return claim(claim_id=req["claim_id"], intent_id=req["intent_id"], kind="EXPOSE", context_id=sender["id"],
        recipient=recipient, channel=req["channel"], purpose=req["purpose"],
        subject_digest=subject, release_act_digest=release_act_digest)


HERE = CONFORMANCE / "review"
BANK_SOURCE = HERE / "fixtures/bank-information-flow-revision2-source.md"
COMPENSATION_SOURCE = HERE / "fixtures/compensation-content-release-revision2-source.md"
BANK_AT = "2026-10-08T10:00:00Z"
COMPENSATION_AT = "2026-10-08T12:05:00Z"
RELEASE_START = "2026-10-08T12:00:00Z"
RELEASE_END = "2026-10-08T13:00:00Z"


def fixture_source(*, compensation=False, control=False):
    path = COMPENSATION_SOURCE if compensation else BANK_SOURCE
    obligations = ([
        "Only the protected host-selected reader may receive exact protected flow results.",
        "The selected exact role, case, purpose and recipient require current ordinary authority before possible exposure.",
        "Every reachable input joins the principal registry before possible delivery; restrictions and origins never shrink.",
    ] if control else [
        "The exact approved midpoint may go only to consultant-01 through the selected benchmarking route under one current attributable Director release.",
        "The source table remains internal. Release neither removes producer restrictions nor authorizes other content, recipients or forwarding.",
        "Ordinary send authority, current consultant designation and Director remit remain independently required. The exact release is used once and expires at 13:00 UTC.",
    ])
    return {"schema": SCHEMA + "authority-source", "id": path.stem + ("-control" if control else "-send"),
        "revision": "revision-2", "obligations": [{"id": "FLOW-OBL-" + str(i).zfill(3), "text": text}
            for i, text in enumerate(obligations, 1)]}


def refresh_response(supplied, *, at=None):
    config, selected_event = supplied["configuration"], supplied["event"]
    event_digest = digest("flow-event", {"event": selected_event, "host_evidence": supplied["host_evidence"]})
    subject = digest("flow-response-subject", {
        "configuration_digest": digest("flow-configuration", config),
        "state_digest": supplied["state_digest"], "event_id": selected_event["id"],
        "event_digest": event_digest, "protected_channel": config["protected_channel"],
    })
    current_event = copy.deepcopy(selected_event)
    if at is not None:
        current_event["clock"]["instant"] = at
    reader = {"id": "protected-result-reader", "actor": "protected-host-reader-01"}
    supplied["response_authority"], _ = access_authority(config, current_event, reader,
        role=config["response_role"], source=fixture_source(control=True),
        response=True, subject_override=subject)
    return supplied


def resign_request(supplied, *, access=False, transfer=False, explicit_empty=False):
    config, selected_event = supplied["configuration"], supplied["event"]
    payload = selected_event["payload"]
    contexts = supplied["state"]["core"]["contexts"] if supplied["state"] else []
    if access:
        receiver_id = payload.get("receiver_context_id", payload.get("context_id"))
        receiver = next(row for row in contexts if row["id"] == receiver_id)
        old = payload["access_authority"]
        payload["access_authority"], _ = access_authority(config, selected_event, receiver,
            role=old["proposal"]["executor"]["role"], source=old["source"], explicit_empty=explicit_empty)
    if transfer:
        sender = next(row for row in contexts if row["id"] == payload["sender_context_id"])
        old = payload["transfer_authority"]
        payload["transfer_authority"], _ = access_authority(config, selected_event, sender,
            role=old["proposal"]["executor"]["role"], source=old["source"], transfer=True)
    supplied["host_evidence"] = host_evidence(config, selected_event)
    return refresh_response(supplied)


def create(config, state=None, *, context_id, actor, scope, purpose, ceiling=(), at=BANK_AT, event_id=None):
    payload = {"context_id": context_id, "actor": actor, "scope": scope,
        "purpose": purpose, "ceiling": sorted(ceiling), "initial_sources": []}
    selected_event = event(config, state, kind="CREATE_CONTEXT", event_id=event_id or "create-" + context_id, payload=payload, at=at)
    supplied = request(config, state, selected_event, host_evidence(config, selected_event))
    receiver = context(context_id=context_id, actor=actor, scope=scope, purpose=purpose, ceiling=ceiling)
    core = state["core"] if state else {"contexts": [], "artifacts": [], "claims": [], "consumed_release_acts": []}
    result = transition(supplied, "CONTEXT_CREATED", contexts=[*core["contexts"], receiver], artifacts=core["artifacts"],
        claims=core["claims"], consumed_release_acts=core["consumed_release_acts"])
    return supplied, result


def read(config, state, source, *, context_id, role, event_id, at=BANK_AT,
         claim_id=None, intent_id=None, explicit_empty=False, compact=False):
    receiver = next(row for row in state["core"]["contexts"] if row["id"] == context_id)
    payload = {"context_id": context_id, "intent_id": intent_id or "intent-" + event_id,
        "claim_id": claim_id or "claim-" + event_id, "source": copy.deepcopy(source)}
    selected_event = event(config, state, kind="READ", event_id=event_id, payload=payload, at=at)
    selected_source = {"schema": SCHEMA + "authority-source", "id": "capacity-policy", "revision": "1",
        "obligations": [{"id": "exact-input", "text": "The protected host may admit this exact independent input."}]} if compact else fixture_source(control=True)
    access, access_result = access_authority(config, selected_event, receiver, role=role,
        source=selected_source, explicit_empty=explicit_empty, class_id_override="c" if compact else None)
    if compact:
        def shorten(value):
            if isinstance(value, dict):
                return {key: "e" if key in {"evidence_ref", "selection_evidence"} else shorten(member) for key, member in value.items()}
            if isinstance(value, list):
                return [shorten(member) for member in value]
            if isinstance(value, str) and not value.startswith("sha256:"):
                return value.replace("component-identity-provider.invalid", "i").replace("authority-revocations", "v").replace("component-authority-return", "r").replace("component-", "c-")
            return value
        access = shorten(access)
        access["clock"]["source"] = config["clock_source"]
        access["envelope"]["clock_source"] = config["clock_source"]
        for act in access["acts"]:
            act["occurred_at"] = at
        for returned in access["returns"]:
            returned["returned_at"] = at
        rebind_outer(access)
        selected_grant = next(row for row in access["acts"] if row["kind"] == "GRANT")
        for act in access["acts"]:
            if act["kind"] == "ORGANISATIONAL_ATTESTATION":
                act["subject_digest"] = digest("authority-act", selected_grant)
        rebind_outer(access)
        refresh_revocations(access)
        access_result = ordinary_expected(access)
    selected_event["payload"]["access_authority"] = access
    supplied = request(config, state, selected_event, host_evidence(config, selected_event))
    advanced = copy.deepcopy(receiver)
    advanced["revision"] = str(int(receiver["revision"]) + 1)
    advanced["restrictions"] = sorted(set(receiver["restrictions"]) | set(source["restrictions"]))
    origins = {digest("flow-source", row): row for row in [*receiver["origins"], source]}
    advanced["origins"] = [copy.deepcopy(origins[key]) for key in sorted(origins)]
    contexts = [advanced if row["id"] == context_id else row for row in state["core"]["contexts"]]
    result = transition(supplied, "READ_RECORDED", contexts=contexts, artifacts=state["core"]["artifacts"],
        claims=[*state["core"]["claims"], delivery_claim(supplied, advanced)],
        consumed_release_acts=state["core"]["consumed_release_acts"], authority_results=[access_result])
    return supplied, result


def materialize(config, state, *, context_id, artifact_id, types, native_fields, at=BANK_AT, event_id=None):
    producer = next(row for row in state["core"]["contexts"] if row["id"] == context_id)
    selected_event = event(config, state, kind="MATERIALIZE", event_id=event_id or "materialize-" + artifact_id,
        payload={"context_id": context_id, "artifact_id": artifact_id, "types": copy.deepcopy(types),
            "fields": copy.deepcopy(native_fields)}, at=at)
    supplied = request(config, state, selected_event, host_evidence(config, selected_event))
    artifact = materialized_artifact(producer, artifact_id=artifact_id, types=types, fields=native_fields)
    result = transition(supplied, "ARTIFACT_RECORDED", contexts=state["core"]["contexts"],
        artifacts=[*state["core"]["artifacts"], artifact], claims=state["core"]["claims"],
        consumed_release_acts=state["core"]["consumed_release_acts"])
    return supplied, result


def import_artifact(config, state, *, sender_id, receiver_id, artifact_id, event_id,
                    receiver_role, sender_role, at=BANK_AT):
    core = state["core"]
    sender = next(row for row in core["contexts"] if row["id"] == sender_id)
    receiver = next(row for row in core["contexts"] if row["id"] == receiver_id)
    artifact = next(row for row in core["artifacts"] if row["id"] == artifact_id)
    payload = {"sender_context_id": sender_id, "receiver_context_id": receiver_id,
        "artifact_id": artifact_id, "intent_id": "intent-" + event_id, "claim_id": "claim-" + event_id}
    selected_event = event(config, state, kind="IMPORT", event_id=event_id, payload=payload, at=at)
    access, access_result = access_authority(config, selected_event, receiver,
        role=receiver_role, source=fixture_source(control=True))
    transfer, transfer_result = access_authority(config, selected_event, sender,
        role=sender_role, source=fixture_source(control=True), transfer=True)
    selected_event["payload"].update(access_authority=access, transfer_authority=transfer)
    supplied = request(config, state, selected_event, host_evidence(config, selected_event))
    advanced = copy.deepcopy(receiver)
    advanced["revision"] = str(int(receiver["revision"]) + 1)
    advanced["restrictions"] = sorted(set(receiver["restrictions"]) | set(sender["restrictions"]) | set(artifact["restrictions"]))
    origins = {digest("flow-source", row): row for row in [*receiver["origins"], *sender["origins"], *artifact["origins"]]}
    advanced["origins"] = [copy.deepcopy(origins[key]) for key in sorted(origins)]
    result = transition(supplied, "IMPORT_RECORDED", contexts=[advanced if row["id"] == receiver_id else row for row in core["contexts"]],
        artifacts=core["artifacts"], claims=[*core["claims"], delivery_claim(supplied, advanced)],
        consumed_release_acts=core["consumed_release_acts"], authority_results=[access_result, transfer_result])
    return supplied, result


def descriptor(record_id, *, scope, restrictions=(), compensation=False, revision="revision-1"):
    return source_descriptor(provider="compensation-records.invalid" if compensation else "transactions.bank.invalid",
        source="approved-compensation-table" if compensation else "independent-transaction-records",
        record_type="COMPENSATION_FACT" if compensation else "CUSTOMER_FACTS", record_id=record_id,
        revision=revision, content_digest="sha256:" + hashlib.sha256((record_id + "/" + revision).encode()).hexdigest(),
        scope=scope, restrictions=restrictions)


def compensation_skeleton(*, now=COMPENSATION_AT):
    values = {"recipient": typed("consultant-01"),
        "destination": typed("https://portal.benchmark-advisor.invalid/engagements/HES-BENCH-026/messages", "STRING"),
        "subject": typed("2026 Platform Engineering midpoint for HES-BENCH-026", "STRING"),
        "body": typed("Harbor Example Services' approved 2026 Platform Engineering salary-band midpoint is USD 150,000.00. Please compare this midpoint with the benchmark scope agreed for engagement HES-BENCH-026.", "STRING"),
        "attachment_count": typed("0", "COUNT"), "message_id": typed("HES-BENCH-MESSAGE-026-01")}
    step = {"id": "send-benchmark-midpoint", "interface": "synthetic-benchmark-portal", "operation": "send-benchmark-midpoint",
        "executor_role": "hr-compensation-analysis-agent", "fields": [{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in fields(values)],
        "scope_fields": {"subjects": ["recipient"], "resources": ["message_id"]}, "required_credentials": [],
        "quantity_mode": "NONE", "exclusive_keys": [], "authority_type_refs": sorted(row["id"] for row in TYPES)}
    work = {"schema": SCHEMA + "authority-work-class", "id": "compensation-benchmark-release", "revision": "revision-2",
        "types": copy.deepcopy(TYPES), "steps": [step]}
    supplied = base_authority(work, values, principal="HES-01", role=step["executor_role"],
        actor="hr-compensation-analysis-agent-01", now=now,
        instance="HES-BENCH-026-instance", occurrence="HES-BENCH-026-occurrence", signed=RELEASE_START)
    old_credentials = {digest("authority-credential", row) for row in supplied["credentials"]}
    supplied["credentials"] = []
    supplied["observations"] = [row for row in supplied["observations"] if row["query"]["subject_digest"] not in old_credentials]
    supplied["source"] = fixture_source(compensation=True)
    supplied["envelope"]["source_obligations"] = sorted(row["id"] for row in supplied["source"]["obligations"])
    next(row for row in supplied["occupancies"] if row["id"] == supplied["proposal"]["executor"]["occupancy"])["kind"] = "MACHINE"
    rebind_outer(supplied)
    return supplied


def flow_requirement(config, supplied, *, context_id, artifact_id, release=False,
                     purpose="REQUEST_TRANSFER_FACTS", entitlement=False):
    recipient = next(row["value"]["value"] for row in supplied["proposal"]["fields"] if row["name"] == "recipient")
    channel = supplied["proposal"]["interface"]
    row = {"restriction_id": config["restrictions"][0]["id"], "scope": config["restrictions"][0]["scope"],
        "recipient": recipient, "channel": channel, "purpose": purpose}
    policy = {"id": "current-flow-policy", "revision": "revision-1", "configuration_digest": digest("flow-configuration", config),
        "entitlements": ordered([row]) if entitlement else [],
        "release_rules": ordered([{**row, "release_role": config["restrictions"][0]["release_role"] or "compensation-director"}]) if release else []}
    return {"id": "exact-outgoing-flow", "step": supplied["proposal"]["step"], "configuration_digest": digest("flow-configuration", config),
        "context_id": context_id, "artifact_id": artifact_id, "intent_id": "intent-exact-disclosure", "claim_id": "claim-exact-disclosure",
        "recipient_field": "recipient", "channel": channel, "purpose": purpose, "policy": policy,
        "release_decision_requirement_id": "exact-compensation-release" if release else None,
        "sources": {"policy": {"requirement_id": "current-flow-policy", "digest_field": "policy_digest"},
            "recipient": {"requirement_id": "current-flow-recipient", "recipient_field": "recipient", "channel_field": "channel",
                "purpose_field": "purpose", "effective_field": "effective"},
            "release_selection": {"requirement_id": "current-release-selection", "act_id_field": "act_id", "act_digest_field": "act_digest",
                "subject_digest_field": "subject_digest", "claim_id_field": "claim_id"} if release else None,
            "release_effectiveness": {"requirement_id": "current-release-effectiveness", "act_id_field": "act_id", "effective_field": "effective"} if release else None,
            "blockers": ["release-withdrawal"] if release else []}}


def add_sources(supplied, selected_rows):
    """Append explicitly chosen source rows and values, retaining complete ordinary bindings."""
    envelope, step = supplied["envelope"], supplied["work_class"]["steps"][0]
    existing = envelope.setdefault("source_observation_requirements", [])
    for row, values in selected_rows:
        existing.append(copy.deepcopy(row))
        supplied["observations"].append(observation(row, supplied, values=values, revision=row["id"] + "-revision-1"))
    existing.sort(key=lambda row: row["id"])
    ids = sorted(row["id"] for row in existing)
    coordinator = next((row for row in existing if row["id"] in {"message-governance-coordinator", "flow-governance-coordinator"}), None)
    if coordinator is None:
        raise ValueError("explicit coordinator row required")
    old_validities = step.get("dispatch_gate", {}).get("validity_requirements", [])
    step["dispatch_gate"] = {"kind": "SOURCE_REQUIREMENTS", "requirements": ids,
        "coordinator_requirement": coordinator["id"], "fence_provider": coordinator["provider"], "fence_source": coordinator["source"],
        "authorization_seconds": "60", "validity_requirements": copy.deepcopy(old_validities)}
    root = supplied["host_selection"]["root"]
    root["providers"] = sorted(set(root["providers"]) | {row["provider"] for row in existing})
    rebind_outer(supplied)
    refresh_revocations(supplied)


def current_source(supplied, req_id, values, *, status="AVAILABLE", relations=(), record_id=None):
    row = requirement(req_id, step=supplied["proposal"]["step"], purpose="AUTHORITY",
        provider="flow-policy-provider.invalid", source="component-" + req_id, record_type="FLOW_AUTHORITY_RECORD",
        subject={"kind": "PROPOSAL_FIELD", "field": "message_id"},
        record_id=record_id if record_id is not None else req_id + "-record" if status == "AVAILABLE" else None,
        expected_status=status, fields=[{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in fields(values)],
        relations=sorted(copy.deepcopy(relations), key=lambda row: row["id"]))
    return row, copy.deepcopy(values)


def attach_bank_flow(config, state, supplied, *, context_id, artifact_id, entitlement=False):
    supplied = copy.deepcopy(supplied)
    req = flow_requirement(config, supplied, context_id=context_id, artifact_id=artifact_id, entitlement=entitlement)
    supplied["envelope"]["flow_requirements"] = [req]
    supplied["flow_bases"] = [basis(config, state, requirement_id=req["id"], at=supplied["clock"]["instant"])]
    rows = [current_source(supplied, "current-flow-policy", {"policy_digest": typed(digest("flow-policy", req["policy"]))}),
        current_source(supplied, "current-flow-recipient", {"recipient": typed("customer-074"), "channel": typed(req["channel"]),
            "purpose": typed(req["purpose"]), "effective": typed(True, "BOOLEAN")})]
    add_sources(supplied, rows)
    # Flow source requirements change the work-class gate before assessment issuance.
    assessment = local_bodies(supplied["work_class"], supplied["proposal"])
    human, _ = human_leaf({row["name"]: row["value"] for row in supplied["proposal"]["fields"]}, assessment)
    assessment_rows, assessment_values, human_requirement = current_requirements(
        {row["name"]: row["value"] for row in supplied["proposal"]["fields"]}, assessment, human)
    supplied["envelope"]["decision_requirements"] = [human_requirement]
    supplied["decision_bases"] = [{"requirement_id": human_requirement["id"], "evidence": human}]
    supplied["assessment_bases"] = [assessment]
    flow_ids = {row[0]["id"] for row in rows}
    supplied["envelope"]["source_observation_requirements"] = [row for row in supplied["envelope"]["source_observation_requirements"] if row["id"] in flow_ids]
    supplied["observations"] = [row for row in supplied["observations"]
        if row["query"]["purpose"] == "REVOCATION" or row["query"].get("requirement_id") in flow_ids]
    add_sources(supplied, [(row, assessment_values[row["id"]]) for row in assessment_rows])
    for row in supplied["observations"]:
        if row["query"].get("requirement_id") == "customer-facts":
            row["revision"] = "revision-1"
        elif row["query"].get("requirement_id") == "immutable-assessment":
            row["revision"] = assessment["assessment"]["revision"]
        elif row["query"].get("requirement_id") == APPROVAL:
            row["provider_record_id"] = assessment["review"]["id"]
    supplied["observations"].sort(key=lambda row: digest("authority-observation", row))
    sender = next(row for row in state["core"]["contexts"] if row["id"] == context_id)
    artifact = next(row for row in state["core"]["artifacts"] if row["id"] == artifact_id)
    return supplied, authority_expected(supplied, ordinary_expected(supplied), req=req, sender=sender, artifact=artifact, recipient="customer-074")


def attach_compensation_flow(config, state, supplied, *, context_id, artifact_id,
        release_id="HES-RELEASE-BENCH-026-01", decision_id="exact-compensation-release",
        source_record_id="HES-COMP-2026-01", release_purpose="HES-BENCH-026",
        release_actor="compensation-director-01", leaf_source=None, released_restrictions=None):
    supplied = copy.deepcopy(supplied)
    principal = config["principal"]
    release_role = config["restrictions"][0]["release_role"] or "compensation-director"
    req = flow_requirement(config, supplied, context_id=context_id, artifact_id=artifact_id,
        release=True, purpose=release_purpose)
    req["release_decision_requirement_id"] = decision_id
    supplied["envelope"]["flow_requirements"] = [req]
    supplied["flow_bases"] = [basis(config, state, requirement_id=req["id"], at=supplied["clock"]["instant"],
        released_restrictions=([config["restrictions"][0]["id"]] if released_restrictions is None else released_restrictions))]
    native = {row["name"]: copy.deepcopy(row["value"]) for row in supplied["proposal"]["fields"]}
    coords = {"provider": "flow-policy-provider.invalid", "source": "component-release-record", "record_type": "FLOW_AUTHORITY_RECORD"}
    identity = canonical_bytes({**coords, "provider_record_id": release_id}).decode()
    values = {**native, "disclosure_subject": typed("placeholder"), "release_identity": typed(identity),
        "effective_from": typed(RELEASE_START, "INSTANT"), "effective_until": typed(RELEASE_END, "INSTANT")}
    def literal(value):
        return {"kind": "LITERAL", "value": copy.deepcopy(value)}
    def equal(req_id, name, right):
        return {"id": name, "kind": "EQUALS", "left": {"kind": "OBSERVATION_FIELD", "requirement_id": req_id, "field": name}, "right": right}
    relations = [{"id": "issue-id", "kind": "EQUALS",
        "left": {"kind": "OBSERVATION_ID", "requirement_id": "release-record", "type_ref": "IDENTITY"},
        "right": {"kind": "DECISION_ACT", "requirement_id": decision_id, "member": "id", "type_ref": "IDENTITY"}}]
    record_values = copy.deepcopy(values)
    for member in ["digest", "actor", "role", "principal", "occurred_at"]:
        name, type_ref = "act-" + member, "INSTANT" if member == "occurred_at" else "IDENTITY"
        record_values[name] = typed(RELEASE_START if type_ref == "INSTANT" else "placeholder", type_ref)
        relations.append(equal("release-record", name,
            {"kind": "DECISION_ACT", "requirement_id": decision_id, "member": member, "type_ref": type_ref}))
    for name in sorted(values):
        relations.append(equal("release-record", name, {"kind": "DECISION_FIELD", "requirement_id": decision_id, "field": name}))
    selected_source = next(row for row in sender_sources(state, context_id) if row["record_id"] == source_record_id)
    source_values = {"source_digest": typed(digest("flow-source", selected_source)), "revision": typed(selected_source["revision"], "REVISION")}
    selected_rows = [
        current_source(supplied, "current-compensation-source", source_values, relations=[
            equal("current-compensation-source", name, literal(value)) for name, value in source_values.items()]),
        current_source(supplied, "current-flow-policy", {"policy_digest": typed(digest("flow-policy", req["policy"]))}),
        current_source(supplied, "current-flow-recipient", {"recipient": native["recipient"], "channel": typed(req["channel"]),
            "purpose": typed(req["purpose"]), "effective": typed(True, "BOOLEAN")}),
        current_source(supplied, "current-release-selection", {"act_id": typed(release_id), "act_digest": typed("placeholder"),
            "subject_digest": typed("placeholder"), "claim_id": typed(req["claim_id"])}),
        current_source(supplied, "current-release-effectiveness", {"act_id": typed(release_id), "effective": typed(True, "BOOLEAN")}),
        current_source(supplied, "release-record", record_values, relations=relations, record_id=release_id),
        current_source(supplied, "release-withdrawal", {}, status="ABSENT"),
        current_source(supplied, "current-director-remit", {"basis_digest": typed("placeholder"), "no_applicable_revocation": typed(True, "BOOLEAN")}, relations=[
            equal("current-director-remit", "basis_digest", {"kind": "DECISION_BASIS", "requirement_id": decision_id, "type_ref": "IDENTITY"}),
            equal("current-director-remit", "no_applicable_revocation", literal(typed(True, "BOOLEAN")))]),
        current_source(supplied, "flow-governance-coordinator", {"complete_writer_coverage": typed(True, "BOOLEAN")}, relations=[
            equal("flow-governance-coordinator", "complete_writer_coverage", literal(typed(True, "BOOLEAN")))]),
    ]
    add_sources(supplied, selected_rows)
    gate = supplied["work_class"]["steps"][0]["dispatch_gate"]
    gate["validity_requirements"] = sorted([*gate["validity_requirements"], {"requirement_id": "release-record", "not_before_field": "effective_from", "not_after_field": "effective_until"}], key=lambda row: row["requirement_id"])
    rebind_outer(supplied)
    sender = next(row for row in state["core"]["contexts"] if row["id"] == context_id)
    artifact = next(row for row in state["core"]["artifacts"] if row["id"] == artifact_id)
    _, subject = disclosure_subject(supplied, req, supplied["flow_bases"][0], sender, artifact)
    values["disclosure_subject"] = typed(subject)
    leaf_step = {"id": "release-exact-midpoint", "interface": "protected-compensation-decisions", "operation": "release-exact-midpoint",
        "executor_role": release_role, "fields": [{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in fields(values)],
        "scope_fields": {"subjects": ["recipient"], "resources": ["message_id"]}, "required_credentials": [],
        "quantity_mode": "NONE", "exclusive_keys": []}
    leaf_work = {"schema": SCHEMA + "authority-work-class", "id": "compensation-director-exact-release", "revision": "revision-2",
        "types": copy.deepcopy(TYPES), "steps": [leaf_step], "authority_profile": "EVIDENCE_ONLY"}
    leaf = base_authority(leaf_work, values, principal=principal, role=release_role, actor=release_actor,
        now=supplied["clock"]["instant"], signed=RELEASE_START, signer_until=RELEASE_END,
        leaf=True, issue=release_id, instance="HES-RELEASE-BENCH-026-instance", occurrence="HES-RELEASE-BENCH-026-occurrence")
    leaf["source"] = copy.deepcopy(leaf_source) if leaf_source is not None else fixture_source(compensation=True)
    leaf["envelope"]["source_obligations"] = sorted(row["id"] for row in leaf["source"]["obligations"])
    leaf["envelope"]["temporal_validity"] = {"valid_from": RELEASE_START, "valid_until": RELEASE_END}
    capacity = next(row for row in leaf["capacities"] if row["id"].endswith("-executor"))
    capacity["reliance"] = {"kind": "CURRENT_ONLY"}
    rebind_outer(leaf)
    refresh_revocations(leaf)
    leaf_result = ordinary_expected(leaf, leaf=True)
    evidence = {"schema": SCHEMA + "human-decision-evidence", "authority_input": leaf,
        "decision_act_digest": leaf_result["decision_act_digest"]}
    bindings = [{"field": name, "value": {"kind": "FLOW_DISCLOSURE", "requirement_id": req["id"], "type_ref": "IDENTITY"}
        if name == "disclosure_subject" else {"kind": "PROPOSAL_FIELD", "field": name} if name in native else literal(value)}
        for name, value in sorted(values.items())]
    supplied["envelope"]["decision_requirements"] = [{"id": decision_id, "step": supplied["proposal"]["step"],
        "principal": principal, "role": release_role, "work_class_digest": digest("authority-work-class", leaf_work),
        "envelope_digest": digest("authority-envelope", leaf["envelope"]), "record_requirement_id": "release-record",
        "identity_field": "release_identity", "validity_fields": {"not_before_field": "effective_from", "not_after_field": "effective_until"},
        "context_bindings": bindings, "distinct_from": [{"kind": "EXECUTOR"}]}]
    supplied["envelope"]["gate"]["role"] = release_role
    supplied["envelope"]["gate"]["decision_requirement"] = decision_id
    supplied["decision_bases"] = [{"requirement_id": decision_id, "evidence": evidence}]
    selected_act = next(row for row in leaf["acts"] if row["kind"] == "INSTANCE_DECISION")
    record_values.update(values)
    for member in ["digest", "actor", "role", "principal", "occurred_at"]:
        record_values["act-" + member] = typed(evidence["decision_act_digest"] if member == "digest" else selected_act[member],
            "INSTANT" if member == "occurred_at" else "IDENTITY")
    replace_values = {"release-record": record_values,
        "current-release-selection": {"act_id": typed(release_id), "act_digest": typed(evidence["decision_act_digest"]),
            "subject_digest": typed(subject), "claim_id": typed(req["claim_id"])},
        "current-director-remit": {"basis_digest": typed(reliance_subject(evidence)), "no_applicable_revocation": typed(True, "BOOLEAN")}}
    supplied["observations"] = [row for row in supplied["observations"] if row["query"].get("requirement_id") not in replace_values]
    for req_id, row_values in replace_values.items():
        row = next(row for row in supplied["envelope"]["source_observation_requirements"] if row["id"] == req_id)
        supplied["observations"].append(observation(row, supplied, values=row_values, revision=req_id + "-revision-1"))
    rebind_outer(supplied)
    result = authority_expected(supplied, ordinary_expected(supplied), req=req, sender=sender,
        artifact=artifact, recipient="consultant-01")
    return supplied, result


def expose(config, state, supplied, authority_result, *, event_id="expose-exact-disclosure"):
    req = supplied["envelope"]["flow_requirements"][0]
    selected_event = event(config, state, kind="EXPOSE", event_id=event_id,
        payload={"requirement_id": req["id"], "authority_projection": authority_projection(supplied)}, at=supplied["clock"]["instant"])
    flow_input = request(config, state, selected_event, host_evidence(config, selected_event))
    sender = next(row for row in state["core"]["contexts"] if row["id"] == req["context_id"])
    artifact = next(row for row in state["core"]["artifacts"] if row["id"] == req["artifact_id"])
    release_digest = (supplied["decision_bases"][0]["evidence"]["decision_act_digest"]
        if req["release_decision_requirement_id"] is not None else None)
    claims = [*state["core"]["claims"], exposure_claim(supplied, req, supplied["flow_bases"][0], sender, artifact,
        release_act_digest=release_digest)]
    consumed = [*state["core"]["consumed_release_acts"], *([release_digest] if release_digest else [])]
    result = transition(flow_input, "EXPOSURE_RECORDED", contexts=state["core"]["contexts"], artifacts=state["core"]["artifacts"],
        claims=claims, consumed_release_acts=consumed, authority_results=[authority_result])
    return flow_input, result


def refresh_revocations(supplied):
    """Issue the complete selected root/capacity/envelope queries after remit construction."""
    now = supplied["clock"]["instant"]
    root = supplied["host_selection"]["root"]
    queries = {}
    def add(subject, at, revocation):
        query = {"purpose": "REVOCATION", "subject_digest": subject, "at": at,
            "provider": revocation["provider"], "source": revocation["source"]}
        queries[canonical_bytes(query)] = query
    for act in supplied["acts"]:
        capacity = next(row for row in supplied["capacities"] if row["id"] == act["capacity"])
        for at in [act["occurred_at"], now]:
            add(digest("authority-root", root), at, root["revocation"])
            add(digest("authority-capacity", capacity), at, capacity["revocation"])
    add(digest("authority-envelope", supplied["envelope"]), now, supplied["envelope"]["revocation"])
    for credential in supplied["credentials"]:
        add(digest("authority-credential", credential), now, credential["revocation"])
    supplied["observations"] = [row for row in supplied["observations"] if row["query"]["purpose"] != "REVOCATION"]
    for index, query in enumerate(sorted(queries.values(), key=canonical_bytes)):
        supplied["observations"].append({"query": query, "query_digest": digest("authority-query", query),
            "status": "AVAILABLE", "as_of": query["at"], "revision": "revocation-snapshot-1", "revoked": False,
            "evidence_ref": "host-revocation-" + str(index)})
    supplied["observations"].sort(key=lambda row: digest("authority-observation", row))
    return supplied


def sender_sources(state, context_id):
    return next(row for row in state["core"]["contexts"] if row["id"] == context_id)["origins"]


def flow_fence(event, result):
    from fixture_factory import add_seconds
    current, permit = event["authority_input"], event["permit"]
    gate = current["work_class"]["steps"][0]["dispatch_gate"]
    sources = []
    for req_id in gate["requirements"]:
        row = next(row for row in current["observations"] if row["query"].get("requirement_id") == req_id)
        query = row["query"]
        sources.append({"requirement_id": req_id, "provider": query["provider"], "source": query["source"],
            "expected_status": query["expected_status"], "record_id": row.get("provider_record_id"), "provider_revision": row["revision"],
            "query_digest": row["query_digest"], "observation_digest": digest("authority-observation", row)})
    req = current["envelope"]["flow_requirements"][0]
    selected = current["flow_bases"][0]
    sender = next(row for row in selected["state"]["core"]["contexts"] if row["id"] == req["context_id"])
    artifact = next(row for row in selected["state"]["core"]["artifacts"] if row["id"] == req["artifact_id"])
    release = next((row["evidence"]["decision_act_digest"] for row in current.get("decision_bases", [])
        if row["requirement_id"] == req["release_decision_requirement_id"]), None)
    flows = [{"requirement_id": req["id"], "configuration_digest": req["configuration_digest"],
        "state_digest": selected["state_digest"], "revision": selected["state"]["core"]["revision"],
        "context_digest": digest("flow-context", sender), "artifact_digest": digest("flow-artifact", artifact),
        "policy_digest": digest("flow-policy", req["policy"]), "intent_id": req["intent_id"], "claim_id": req["claim_id"], "release_act_digest": release}]
    checked = current["clock"]["instant"]
    ends = [permit["expires_at"], add_seconds(checked, gate["authorization_seconds"]), current["envelope"]["temporal_validity"]["valid_until"]]
    for validity in gate["validity_requirements"]:
        row = next(row for row in current["observations"] if row["query"].get("requirement_id") == validity["requirement_id"])
        ends.append(next(value["value"]["value"] for value in row["fields"] if value["name"] == validity["not_after_field"]))
    ends.extend(row["result"]["effective_until"] for row in result.get("decision_results", []))
    expires = min(end for end in ends if end is not None)
    scope = {"instance_id": event["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
        "permit_digest": permit["permit_id"], "native_request": event["native_request"], "connector": event["connector"],
        "dispatch_intent_id": event["dispatch_intent_id"], "checked_at": checked, "expires_at": expires,
        "authority_result_digest": digest("authority-result", result), "sources": sources, "flows": flows}
    coordinator = next(row for row in sources if row["requirement_id"] == gate["coordinator_requirement"])
    return {"kind": "SOURCE_REQUIREMENTS", "provider": gate["fence_provider"], "source": gate["fence_source"],
        "provider_revision": coordinator["provider_revision"], "scope_digest": digest("dispatch-authorization-scope", scope),
        "checked_at": checked, "status": "EFFECTIVE", "sources": sources, "flows": flows}, expires


def lifecycle_trace(facts, *, instance="information-flow-host-instance"):
    """Construct one exact source-selected lifecycle and matching first-exposure body."""
    from fixture_factory import add_seconds, available_clock, deployment, occurrence, readback_paths, structural_step
    from lifecycle_factory import admitted_transition, permitted_proposal, state_digest, step_input
    from assessment_fixture import refreshed, public_result
    old = facts["authority"]
    projected = old["work_class"]["steps"][0]
    step = {**copy.deepcopy(projected), "kind": "OPERATION", "authority_requirements": [old["envelope"]["id"]],
        "shared_budgets": [], "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": "300", "failure_behavior": "STOP",
        "referral_policy": {"authority": [], "completion": []}}
    if "completion" not in step:
        step["completion"] = {"terminal_policy": "LEGACY_NONTERMINAL", "effect_provider": "synthetic-benchmark-provider.invalid",
            "effect_source": "synthetic-benchmark-sink", "effect_record_type": "BENCHMARK_MESSAGE_RESULT", "no_effect_provider": "synthetic-benchmark-provider.invalid",
            "no_effect_source": "synthetic-benchmark-sink", "no_effect_record_type": "BENCHMARK_MESSAGE_NO_EFFECT", "status_field": "status", "status_type_ref": "STRING",
            "success_values": [typed("ACCEPTED", "STRING")], "failure_values": [typed("REJECTED", "STRING")], "route_label_field": None, "route_label_type_ref": None,
            "evidence_bindings": [{"request_field": row["name"], "evidence_field": row["name"]} for row in projected["fields"]]}
    definition = {"schema": SCHEMA + "work-class-definition", "specification_pin": candidate_pin(),
        "id": old["work_class"]["id"], "revision": old["work_class"]["revision"], "profile": "LINEAR", "root": projected["id"],
        "participants": [{"id": old["proposal"]["executor"]["actor"], "role": projected["executor_role"], "kind": "AGENT"}],
        "objects": [], "types": copy.deepcopy(old["work_class"]["types"]), "steps": [step, structural_step("terminal", "TERMINAL")],
        "relationships": [{"kind": "SEQUENCE", "from": projected["id"], "to": "terminal"}], "choices": [],
        "occurrence_limits": [{"step_id": projected["id"], "maximum": "1"}], "loops": [], "deadlines": [], "parallel_blocks": [], "fanouts": [], "shared_budgets": [],
        "limits": {"maximum_proposals": "64", "maximum_activations": "64", "maximum_actuations": "1", "maximum_active_obligations": "64", "maximum_fanout_objects": "64"},
        "source": {"id": old["source"]["id"], "revision": old["source"]["revision"], "obligations": sorted(row["id"] for row in old["source"]["obligations"])}}
    definition_digest = digest("work-class-definition", definition)
    root_occurrence = occurrence(definition_digest, instance, projected["id"])
    compensation = facts["configuration"]["principal"] == "HES-01"
    if compensation:
        skeleton = compensation_skeleton(now=facts["at"])
        skeleton["proposal"].update(instance=instance, occurrence=root_occurrence["occurrence_id"])
        supplied, result = attach_compensation_flow(facts["configuration"], facts["state"], skeleton,
            context_id=facts["context_id"], artifact_id=facts["artifact_id"])
    else:
        skeleton = assessment_authority(instance=instance, occurrence=root_occurrence["occurrence_id"])[0]
        supplied, result = attach_bank_flow(facts["configuration"], facts["state"], skeleton,
            context_id=facts["context_id"], artifact_id=facts["artifact_id"])
    paths, obligations = readback_paths(definition), definition["source"]["obligations"]
    mappings = [{"source_obligation_id": obligation, "provision_paths": paths[i::len(obligations)]} for i, obligation in enumerate(obligations)]
    deploy_input, deployed = deployment(definition, instance_id=instance, organization_id=facts["configuration"]["principal"],
        authorization_time="2026-10-08T11:57:00Z" if compensation else "2026-10-08T09:57:00Z",
        evidence_expires_at="2026-10-09T10:00:00Z", correspondence_mappings=mappings)
    clock = available_clock(supplied["clock"]["source"], "1", facts["at"])
    clock_event = {"schema": SCHEMA + "runtime-event", "event_id": "flow-lifecycle-clock-1", "kind": "CLOCK", "instance_id": instance,
        "expected_state_revision": deployed["state"]["revision"], "expected_state_digest": state_digest(deployed["state"]), "clock": clock, "activation_clocks": []}
    def append_clock(state):
        state["clocks"].append(copy.deepcopy(clock))
    clock_result = admitted_transition(deployed["state"], clock_event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": "1", "status": "AVAILABLE"}], mutate=append_clock)
    executor = supplied["proposal"]["executor"]
    proposal_event = {"schema": SCHEMA + "runtime-event", "kind": "PROPOSE", "event_id": "flow-lifecycle-propose", "instance_id": instance,
        "expected_state_revision": clock_result["state"]["revision"], "expected_state_digest": state_digest(clock_result["state"]), "occurrence": root_occurrence,
        "native_request": {key: copy.deepcopy(supplied["proposal"][key]) for key in ["interface", "operation", "fields"]},
        "executor": {"participant_id": executor["actor"], "role": executor["role"], "binding_digest": digest("executor-binding", executor)},
        "credential_ids": sorted(row["id"] for row in supplied["credentials"]), "authority_input": supplied, "budget_inputs": [], "clock_revision": "1",
        "observation_digests": sorted(digest("authority-observation", row) for row in supplied["observations"])}
    base = {"definition": definition, "definition_digest": definition_digest, "deploy_input": deploy_input, "deploy_result": deployed,
        "clock_event": clock_event, "clock_result": clock_result, "authority_input": supplied, "authority_result": result,
        "proposal_event": proposal_event, "permit_expires_at": add_seconds(facts["at"], "300")}
    permitted = permitted_proposal(base)
    later = add_seconds(facts["at"], "1")
    dispatch_clock = available_clock(supplied["clock"]["source"], "2", later)
    dispatch_clock_event = {"schema": SCHEMA + "runtime-event", "kind": "CLOCK", "event_id": "flow-lifecycle-clock-2", "instance_id": instance,
        "expected_state_revision": permitted["state"]["revision"], "expected_state_digest": state_digest(permitted["state"]), "clock": dispatch_clock, "activation_clocks": []}
    def append_dispatch_clock(state):
        state["clocks"].append(copy.deepcopy(dispatch_clock))
    clock2 = admitted_transition(permitted["state"], dispatch_clock_event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": dispatch_clock["source"], "revision": "2", "status": "AVAILABLE"}], mutate=append_dispatch_clock)
    current = refreshed(supplied, later)
    current["flow_bases"][0]["selection"]["at"] = later
    req = current["envelope"]["flow_requirements"][0]
    sender = next(row for row in facts["state"]["core"]["contexts"] if row["id"] == facts["context_id"])
    artifact = next(row for row in facts["state"]["core"]["artifacts"] if row["id"] == facts["artifact_id"])
    recipient = next(row["value"]["value"] for row in current["proposal"]["fields"] if row["name"] == req["recipient_field"])
    current_result = authority_expected(current, ordinary_expected(current), req=req, sender=sender, artifact=artifact, recipient=recipient)
    connector_body = {"id": "synthetic-flow-connector", "version": "revision-1"}
    connector = {**connector_body, "binding_digest": digest("connector-binding", connector_body)}
    authorization_event = {"schema": SCHEMA + "runtime-event", "kind": "AUTHORIZE_DISPATCH", "event_id": "flow-lifecycle-authorize", "instance_id": instance,
        "expected_state_revision": clock2["state"]["revision"], "expected_state_digest": state_digest(clock2["state"]), "permit": copy.deepcopy(permitted["permit"]),
        "native_request": copy.deepcopy(permitted["permit"]["native_request"]), "connector": connector, "authorization_fence": None,
        "authority_input": current, "dispatch_intent_id": req["intent_id"], "observation_digests": sorted(digest("authority-observation", row) for row in current["observations"]), "clock_revision": "2"}
    authorization_event["authorization_fence"], expires = flow_fence(authorization_event, current_result)
    body = {"event_id": authorization_event["event_id"], "event_digest": digest("runtime-event", authorization_event), "permit_digest": permitted["permit"]["permit_id"],
        "native_request": authorization_event["native_request"], "connector": connector, "authorization_fence": authorization_event["authorization_fence"],
        "observation_digests": authorization_event["observation_digests"], "clock_revision": "2", "dispatch_intent_id": req["intent_id"],
        "authority_input": current, "authority_result": current_result, "authority_result_digest": digest("authority-result", current_result),
        "expires_at": expires, "supersedes_authorization_digest": None}
    record = {"authorization_digest": digest("dispatch-authorization", body), **body}
    evaluation_body = {"event_id": authorization_event["event_id"], "event_digest": digest("runtime-event", authorization_event), "permit_digest": permitted["permit"]["permit_id"],
        "dispatch_intent_id": req["intent_id"], "clock_revision": "2", "authority_input": current, "authority_result": current_result,
        "authority_result_digest": digest("authority-result", current_result), "authorization_digest": record["authorization_digest"], "disposition": "AUTHORIZED"}
    evaluation = {"evaluation_digest": digest("dispatch-authorization-evaluation", evaluation_body), **evaluation_body}
    def retain_authorization(state):
        state["authorizations"].append(copy.deepcopy(record)); state["authorization_evaluations"].append(copy.deepcopy(evaluation))
    authorized = admitted_transition(clock2["state"], authorization_event, disposition="AUTHORIZED", reason_codes=[],
        details=[{"kind": "AUTHORIZATION", "authorization_digest": record["authorization_digest"], "permit_digest": permitted["permit"]["permit_id"],
            "gate_kind": "SOURCE_REQUIREMENTS", "checked_at": later, "expires_at": expires,
            "sources": authorization_event["authorization_fence"]["sources"], "flows": authorization_event["authorization_fence"]["flows"]}],
        receipt_permit_digest=permitted["permit"]["permit_id"], receipt_authority_result_digest=digest("authority-result", current_result),
        receipt_authorization_evaluation_digest=evaluation["evaluation_digest"], mutate=retain_authorization)
    expose_input, expose_result = expose(facts["configuration"], facts["state"], current, current_result, event_id="flow-lifecycle-first-exposure")
    stages = [["deploy", deploy_input, deployed], ["step", step_input(base, deployed["state"], clock_event), public_result(clock_result)],
        ["step", step_input(base, clock_result["state"], proposal_event), public_result(permitted)],
        ["step", step_input(base, permitted["state"], dispatch_clock_event), public_result(clock2)],
        ["step", step_input(base, clock2["state"], authorization_event), public_result(authorized)], ["flow-step", expose_input, expose_result]]
    return {"base": base, "permitted": permitted, "authorization_event": authorization_event, "authorized": authorized,
        "dispatch_authority": current, "dispatch_authority_result": current_result, "flow_expose_input": expose_input,
        "flow_expose_result": expose_result, "connector": connector, "stages": stages}


def event_capacity(facts):
    config, state = facts['configuration'], None
    scope = facts['authority']['envelope']['scope']['id']
    for i in range(16):
        _, result = create(config, state, context_id='capacity-'+str(i).zfill(2), actor=facts['authority']['proposal']['executor']['actor'],
            scope=scope, purpose='REQUEST_TRANSFER_FACTS')
        state=result['state']
    source=descriptor('capacity-independent-request',scope=scope)
    for i in range(48):
        _,result=read(config,state,source,context_id='capacity-00',role='customer-message-agent',event_id='capacity-read-'+str(i).zfill(2),compact=True)
        state=result['state']
    for i in range(64):
        _,result=materialize(config,state,context_id='capacity-00',artifact_id='capacity-artifact-'+str(i).zfill(2),
            types=facts['authority']['work_class']['types'] if i==63 else [{'id':'IDENTITY','kind':'IDENTITY','nonnegative':False,'unit':None}],
            native_fields=facts['authority']['proposal']['fields'] if i==63 else [{'name':'content','value':{'type_ref':'IDENTITY','value':'independent-minimal-artifact'}}])
        state=result['state']
    return state


def origin_capacity(facts):
    config=facts['configuration'];scope=facts['authority']['envelope']['scope']['id']
    _,result=create(config,context_id='origin-receiver',actor='origin-receiver-01',scope=scope,purpose='REQUEST_TRANSFER_FACTS')
    state=result['state']
    for i in range(64):
        source=descriptor('origin-'+str(i).zfill(2),scope=scope)
        _,result=read(config,state,source,context_id='origin-receiver',role='customer-message-agent',event_id='origin-read-'+str(i).zfill(2),compact=True)
        state=result['state']
    _,result=create(config,state,context_id='origin-sender',actor='origin-sender-01',scope=scope,purpose='REQUEST_TRANSFER_FACTS')
    state=result['state']
    source=descriptor('origin-65',scope=scope)
    _,result=read(config,state,source,context_id='origin-sender',role='customer-message-agent',event_id='origin-sender-read',compact=True)
    state=result['state']
    _,result=materialize(config,state,context_id='origin-sender',artifact_id='origin-sender-artifact',
        types=[{'id':'IDENTITY','kind':'IDENTITY','nonnegative':False,'unit':None}],native_fields=[{'name':'content','value':{'type_ref':'IDENTITY','value':'independent-origin-65'}}])
    return result['state']


def generic_combined(*, same_person=False, review_decision="APPROVE"):
    """The separate generic source selects both acts; bank/compensation policy is unchanged."""
    ordinary = assessment_authority(now=COMPENSATION_AT)[0]
    ordinary["source"]["id"] = "generic-assessment-and-release-revision1-source"
    ordinary["source"]["obligations"].append({"id": "GENERIC-EXACT-RELEASE", "text":
        "This synthetic internal review draft additionally needs one current exact supplementary content release. Assessment review remains the outer gate."})
    ordinary["source"]["obligations"].sort(key=lambda row: row["id"])
    ordinary["envelope"]["source_obligations"] = sorted(row["id"] for row in ordinary["source"]["obligations"])
    rebind_outer(ordinary); refresh_revocations(ordinary)
    scope = ordinary["envelope"]["scope"]["id"]
    config = configuration(principal=ordinary["envelope"]["principal"], registry_id="generic-combined-registry", scope=scope,
        restriction_id="GENERIC-INTERNAL-DRAFT", meaning="Synthetic internal review draft, not reporting or compensation data",
        releasable=True, release_role="generic-content-release-officer")
    config["clock_source"] = ordinary["clock"]["source"]
    _, seeded = create(config, context_id="generic-review-context", actor=ordinary["proposal"]["executor"]["actor"], scope=scope,
        purpose="GENERIC_INTERNAL_PREPARATION", ceiling=["GENERIC-INTERNAL-DRAFT"], at=COMPENSATION_AT)
    source = descriptor("GENERIC-INTERNAL-FIXTURE", scope=scope, restrictions=["GENERIC-INTERNAL-DRAFT"])
    source.update(provider="generic-fixture-provider.invalid", source="generic-review-draft", record_type="GENERIC_DRAFT")
    _, delivered = read(config, seeded["state"], source, context_id="generic-review-context", role="customer-message-agent",
        event_id="generic-source-read", at=COMPENSATION_AT)
    _, materialized = materialize(config, delivered["state"], context_id="generic-review-context", artifact_id="generic-reviewed-artifact",
        types=ordinary["work_class"]["types"], native_fields=ordinary["proposal"]["fields"], at=COMPENSATION_AT)
    state = materialized["state"]
    leaf_source = {"schema": SCHEMA + "authority-source", "id": "generic-exact-content-release-source", "revision": "revision-1",
        "obligations": [{"id": "GENERIC-RELEASE", "text": "The exact synthetic reviewed artifact may go to the selected portal recipient once under current Generic Content Release Officer authority."}]}
    supplied, _ = attach_compensation_flow(config, state, ordinary, context_id="generic-review-context", artifact_id="generic-reviewed-artifact",
        release_id="GENERIC-RELEASE-01", decision_id="generic-content-release", source_record_id="GENERIC-INTERNAL-FIXTURE",
        release_purpose="REQUEST_TRANSFER_FACTS", release_actor="customer-reviewer-01" if same_person else "generic-release-officer-01", leaf_source=leaf_source)
    assessment = local_bodies(supplied["work_class"], supplied["proposal"], decision=review_decision)
    human, _ = human_leaf({row["name"]: row["value"] for row in supplied["proposal"]["fields"]}, assessment, now=COMPENSATION_AT)
    assessment_rows, assessment_values, human_requirement = current_requirements(
        {row["name"]: row["value"] for row in supplied["proposal"]["fields"]}, assessment, human)
    release_requirement = supplied["envelope"]["decision_requirements"][0]
    release_basis = supplied["decision_bases"][0]
    supplied["envelope"]["decision_requirements"] = sorted([human_requirement, release_requirement], key=lambda row: row["id"])
    supplied["decision_bases"] = sorted([{"requirement_id": human_requirement["id"], "evidence": human}, release_basis], key=lambda row: row["requirement_id"])
    supplied["envelope"]["gate"].update(role=human_requirement["role"], decision_requirement=human_requirement["id"])
    supplied["assessment_bases"] = [assessment]
    old_ids = {row["id"] for row in assessment_rows}
    supplied["envelope"]["source_observation_requirements"] = [row for row in supplied["envelope"]["source_observation_requirements"] if row["id"] not in old_ids]
    supplied["observations"] = [row for row in supplied["observations"] if row["query"].get("requirement_id") not in old_ids]
    add_sources(supplied, [(row, assessment_values[row["id"]]) for row in assessment_rows])
    for row in supplied["observations"]:
        req_id = row["query"].get("requirement_id")
        if req_id == "customer-facts":
            row["revision"] = "revision-1"
        elif req_id == "immutable-assessment":
            row["revision"] = assessment["assessment"]["revision"]
        elif req_id == APPROVAL:
            row["provider_record_id"] = assessment["review"]["id"]
    supplied["observations"].sort(key=lambda row: digest("authority-observation", row))
    req = supplied["envelope"]["flow_requirements"][0]
    result = authority_expected(supplied, ordinary_expected(supplied), req=req, sender=state["core"]["contexts"][0],
        artifact=state["core"]["artifacts"][0], recipient="customer-074")
    return supplied, result
