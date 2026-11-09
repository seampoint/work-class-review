"""Fixed CDMO source facts and complete normative expectations, without consumers.

This constructor is not an authority evaluator. Its successful inventories apply
the declared positive source facts; negative expectations are chosen explicitly.
"""
from __future__ import annotations

import base64
import copy
import hashlib
from pathlib import Path

from corpus_common import candidate_pin, canonical_bytes, digest
from equipment_observation_fixture import observation, requirement, source_query
from equipment_completion_fixture import lookup_event, lookup_result, terminal_effect_result
from equipment_dispatch_fixture import retained
from equipment_history_fixture import history_state, seed_request, seed_result
from fixture_factory import add_seconds, available_clock, deployment, occurrence, readback_paths, structural_step
from lifecycle_budget_fixture import permitted_budget_proposal
from lifecycle_factory import admitted_transition, dispatch_event, dispatch_result, governed_effect_event, governed_native_evidence, state_digest
from reservation_fixture import effect_record, host_and_event, native, request as reservation_request, reservation_record, transition

SCHEMA = "seampoint.work-class/1.0.0-draft.3/"
PIN = candidate_pin()
HERE = Path(__file__).resolve().parent
SOURCE_PATH = HERE / "fixtures/pharmaceutical-batch-disposition-revision3-source.md"
SOURCE_ID = "pharmaceutical-batch-disposition-revision3-source"
CEDAR = "cedar-vector-manufacturing"
ALDER = "alder-therapy-research"
NOW = "2026-10-06T12:10:00Z"
SIGNED = "2026-10-06T12:00:00Z"
END = "2026-10-07T12:00:00Z"
OCCUPANCY_END = "2026-10-06T12:05:00Z"
VALID = {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-11-01T00:00:00Z"}
PROVIDER = "cedar-inventory-ledger"
EVENT_SOURCE = "batch-transfer-authorizations"
EVENT_TYPE = "batch-transfer-authorization-event"
TYPES = [{"id": name, "kind": kind, "nonnegative": False, "unit": None}
         for name, kind in [("BOOLEAN", "BOOLEAN"), ("IDENTITY", "IDENTITY"),
                            ("INSTANT", "INSTANT"), ("REVISION", "STRING"), ("STATUS", "STRING")]]
TYPE_BY_NAME = {row["id"]: row for row in TYPES}


def typed(value, type_ref="IDENTITY"):
    return {"type_ref": type_ref, "value": value}


def fields(values):
    return [{"name": name, "value": copy.deepcopy(value)} for name, value in sorted(values.items())]


def type_for(name):
    if name in {"effective_from", "effective_until", "signed_at"}:
        return "INSTANT"
    if name.endswith("revision"):
        return "REVISION"
    if name in {"old_status", "new_status"}:
        return "STATUS"
    return "IDENTITY"


def source_obligations():
    import json
    path = HERE.parent / "specimens/pharmaceutical-batch-disposition/normalized-obligations.json"
    record = json.loads(path.read_text())
    return [{"id": row["id"], "text": row["text"]} for row in record["obligations"]]


def dossier_records(revision="7"):
    inventory = []
    for name, record_id, rev, values in [
        ("manufacturing", "CV-MFG-026", "8", {"complete_operations": True, "complete_reviews": True}),
        ("laboratory", "CV-LAB-026", "6", {name: "PASS" for name in
            ["identity", "vector_genome_titer", "potency", "endotoxin", "microbiological_safety"]}),
        ("deviations", "CV-DEV-026", "4", {"complete": True, "all_investigated": True,
            "all_dispositions_authorized": True, "required_followup_complete": True, "unresolved_failure": False}),
        ("holds", "CV-HOLD-026", "9", {"batch_blocked": False, "product_blocked": False, "site_blocked": False}),
        ("specification", "AAV-DS-04-SPEC", "2", {"product_id": "AAV-DS-04", "approved": True}),
    ]:
        body = {"batch_id": "CV-BATCH-026", "record_id": record_id, "revision": rev, "conclusions": values}
        inventory.append({"provider": "cedar-" + name + "-records", "source": name + "-records",
            "record_type": name + "-record", "record_id": record_id, "revision": rev,
            "content_digest": "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest(), "body": body})
    dossier = {"record_id": "CV-DOSSIER-026", "revision": revision, "batch_id": "CV-BATCH-026",
        "site_id": "CV-IN-01", "product_id": "AAV-DS-04", "product_revision": "2", "customer_id": "ATR-US-01",
        "agreement_id": "CV-ATR-07", "agreement_revision": "3",
        "evidence": [{key: row[key] for key in ("provider", "source", "record_type", "record_id", "revision", "content_digest")}
            for row in inventory]}
    return inventory, dossier, "sha256:" + hashlib.sha256(canonical_bytes(dossier)).hexdigest()


def business_fields(*, request_id="CV-TRANSFER-042", dossier_revision="7", cedar_issue="CV-APPROVAL-026-R3",
                    alder_issue="ATR-ASSENT-026-R3"):
    _, _, dossier_digest = dossier_records(dossier_revision)
    values = {"request_id": request_id, "batch_id": "CV-BATCH-026", "site_id": "CV-IN-01", "product_id": "AAV-DS-04",
        "product_revision": "2", "customer_id": "ATR-US-01", "dossier_revision": dossier_revision,
        "dossier_digest": dossier_digest, "agreement_revision": "3", "cedar_approval_identity": identity_text("cedar", cedar_issue),
        "customer_assent_identity": identity_text("alder", alder_issue), "expected_inventory_revision": "11",
        "old_status": "QUARANTINED", "new_status": "APPROVED_FOR_CUSTOMER_TRANSFER"}
    return {name: typed(value, type_for(name)) for name, value in values.items()}


def criterion(step):
    return {"id": "approved-status", "step": step, "predicate": {"kind": "EQUAL",
        "left": {"kind": "FIELD", "name": "new_status"},
        "right": {"kind": "LITERAL", "value": typed("APPROVED_FOR_CUSTOMER_TRANSFER", "STATUS")}}}


def operation_projection(step_id, values, executor_role, *, leaf=False):
    step = {"id": step_id, "operation": step_id, "interface": "cedar-inventory-administration" if not leaf else "human-quality-decisions",
        "executor_role": executor_role, "fields": [{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in fields(values)],
        "scope_fields": {"subjects": ["customer_id"], "resources": ["batch_id", "site_id"]},
        "required_credentials": [] if leaf else ["inventory-authenticated-session"], "quantity_mode": "NONE", "exclusive_keys": []}
    return step


def base_authority(work, values, *, principal, role, actor, now=NOW, leaf=False, issue=None, gate_requirement=None,
                   decision_requirements=None, source_requirements=None, source_values=None, decision_bases=None,
                   instance="cdmo-instance-1", occurrence="cdmo-occurrence-1", signed=SIGNED, signer_until=OCCUPANCY_END, decider=None, capacity_until=None, source_padding=0):
    """Construct exact positive records from an explicit one-way dependency graph."""
    step = work["steps"][0]
    prefix = "alder" if principal == ALDER else "cedar"
    provider = prefix + "-identity-provider"
    source = {"schema": SCHEMA + "authority-source", "id": SOURCE_ID, "revision": "revision-3-CV-TRANSFER-042",
        "obligations": source_obligations()}
    if source_padding:
        source["obligations"][0]["text"] += "x" * source_padding
    bindings = [{"id": name + "-binding", "step": step["id"], "field": name, "type_ref": values[name]["type_ref"]}
                for name in sorted(set(step["scope_fields"]["subjects"] + step["scope_fields"]["resources"]))]
    gate = {"materiality": "HIGH", "reversibility": "LOW", "kind": "DECIDE", "role": decider[1] if decider else role if leaf else "quality-disposition-reviewer",
        "criteria": [criterion(step["id"])]}
    if gate_requirement:
        gate["decision_requirement"] = gate_requirement
    revocation = {"provider": provider, "source": "authority-revocations", "max_age_seconds": "0"}
    envelope = {"schema": SCHEMA + "authority-envelope", "id": work["id"] + "-envelope", "principal": principal,
        "grant_ref": work["id"] + "-grant", "grantor_role": "customer-quality-director" if principal == ALDER else "head-of-quality",
        "attester_role": prefix + "-quality-attester", "executor_role": role, "clock_source": prefix + "-quality-clock",
        "operations": [{name: step[name] for name in ["interface", "operation"]} | {"step": step["id"]}],
        "bindings": bindings, "scope": {"id": work["id"] + "-scope", **{member: [{"kind": "BINDING", "binding": name + "-binding"} for name in step["scope_fields"][member]] for member in ["subjects", "resources"]}},
        "conditions": [], "limits": {"per_action": [], "shared_budgets": []}, "gate": gate,
        "temporal_validity": {"valid_from": signed, "valid_until": END}, "revocation": revocation,
        "enforcement": {"mechanisms": ["AUTHORITY_BEFORE_RESERVATION"] if not step["exclusive_keys"] else
            ["ATOMIC_RESERVATION_TRANSITION", "AUTHORITY_BEFORE_RESERVATION"], "out_of_envelope": "REFUSE", "safe_state": "NO_NEW_DISPATCH"},
        "escalation": {"kind": "DECLARED_NONE"}, "limitations": [],
        "source_obligations": sorted(row["id"] for row in source["obligations"]),
        "source_digest": digest("authority-source", source), "work_class_digest": digest("authority-work-class", work)}
    if decision_requirements is not None:
        envelope["decision_requirements"] = copy.deepcopy(decision_requirements)
    if source_requirements is not None:
        envelope["source_observation_requirements"] = copy.deepcopy(source_requirements)
    proposal = {"schema": SCHEMA + "authority-proposal", "work_class": work["id"],
        "work_class_digest": digest("authority-work-class", work), "instance": instance, "occurrence": occurrence,
        "step": step["id"], "interface": step["interface"], "operation": step["operation"], "fields": fields(values),
        "executor": {"actor": actor, "role": role, "principal": principal, "occupancy": work["id"] + "-occupancy-executor"}}
    envelope_digest = digest("authority-envelope", envelope)
    operation_digest = digest("authority-operation", {"envelope_digest": envelope_digest,
        "work_class_digest": digest("authority-work-class", work), "proposal_digest": digest("authority-proposal", proposal)})
    persons = [("grantor", prefix + "-quality-head-01", envelope["grantor_role"]),
        ("attester", prefix + "-quality-attester-01", envelope["attester_role"]), ("executor", actor, role)]
    if decider:
        persons.append(("decider", decider[0], decider[1]))
    occupancies = [{"id": work["id"] + "-occupancy-" + suffix, "actor": person, "role": selected_role, "principal": principal,
        "kind": "HUMAN" if leaf or suffix != "executor" or actor != "inventory-agent-01" else "MACHINE", "provider": provider,
        "validity": {**VALID, "valid_until": signer_until} if leaf and suffix == "executor" else copy.deepcopy(VALID),
        "evidence_ref": "host-selected-" + work["id"] + "-" + suffix} for suffix, person, selected_role in persons]
    root = {"schema": SCHEMA + "authority-root", "id": work["id"] + "-root", "revision": "1", "designator": prefix + "-quality-director",
        "principal": principal, "source_digest": digest("authority-source", source), "work_class_digest": digest("authority-work-class", work),
        "envelope_digest": envelope_digest, "capacity_ids": sorted(work["id"] + "-capacity-" + suffix for suffix, _, _ in persons if suffix != "executor" or leaf),
        "occupancy_ids": sorted(row["id"] for row in occupancies),
        "providers": sorted({provider} | {row["provider"] for row in source_requirements or []}),
        "channels": [{"id": prefix + "-authority-return", "provider": provider, "validity": copy.deepcopy(VALID), "prior_returns_survive_expiry": True}],
        "validity": copy.deepcopy(VALID), "prior_acts_survive_expiry": True, "revocation": copy.deepcopy(revocation),
        "allow_self_attestation": False, "limitations": []}
    root_digest = digest("authority-root", root)
    capacities = []
    for suffix, person, selected_role in persons:
        if suffix == "executor" and not leaf:
            continue
        capacities.append({"id": work["id"] + "-capacity-" + suffix, "actor": person, "role": selected_role, "principal": principal,
            "occupancy": work["id"] + "-occupancy-" + suffix, "provider": provider, "root_digest": root_digest,
            "envelope_digest": envelope_digest, "act_kinds": [{"grantor": "GRANT", "attester": "ORGANISATIONAL_ATTESTATION", "executor": "INSTANCE_DECISION", "decider": "INSTANCE_DECISION"}[suffix]],
            "validity": {**VALID, "valid_until": signer_until} if suffix == "executor" else {**VALID, "valid_until": capacity_until or VALID["valid_until"]},
            "revocation": copy.deepcopy(revocation), "reliance": {"kind": "SURVIVE_EXPIRY", "validity": {"valid_from": signed, "valid_until": END}}
                if suffix == "executor" else {"kind": "CURRENT_ONLY"},
            "may_self_attest": False, "evidence_ref": "host-selected-capacity-" + suffix})
    def act(act_id, kind, suffix, subject, *, attested=None, criteria=None):
        person = next(row for row in occupancies if row["id"].endswith("-" + suffix))
        return {"id": act_id, "kind": kind, "actor": person["actor"], "role": person["role"], "principal": principal,
            "occupancy": person["id"], "capacity": work["id"] + "-capacity-" + suffix, "recorder": prefix + "-quality-recorder",
            "occurred_at": signed, "disposition": "ACCEPT", "subject_digest": subject, "attested_actor": attested,
            "criteria": criteria or []}
    grant = act(envelope["grant_ref"], "GRANT", "grantor", envelope_digest)
    acts = [grant, act(work["id"] + "-grant-attestation", "ORGANISATIONAL_ATTESTATION", "attester",
        digest("authority-act", grant), attested=grant["actor"])]
    if leaf or decider:
        decision = act(issue, "INSTANCE_DECISION", "executor" if leaf else "decider", operation_digest, criteria=["approved-status"])
        acts += [decision, act(work["id"] + "-decision-attestation", "ORGANISATIONAL_ATTESTATION", "attester",
            digest("authority-act", decision), attested=decision["actor"])]
    returns = [{"id": "return-" + row["id"], "actor": row["actor"], "provider": provider, "channel": root["channels"][0]["id"],
        "act_digest": digest("authority-act", row), "act_bytes_base64": base64.b64encode(canonical_bytes(row)).decode(),
        "returned_at": signed, "evidence_ref": "host-returned-" + row["id"]} for row in acts]
    credentials = [] if leaf else [{"id": "cdmo-executor-session-1", "actor": actor, "occupancy": proposal["executor"]["occupancy"],
        "step": step["id"], "interface": step["interface"], "operation": step["operation"], "kind": "inventory-authenticated-session",
        "validity": copy.deepcopy(VALID), "provider": provider, "revocation": copy.deepcopy(revocation), "evidence_ref": "host-session-1"}]
    observations = []
    query_map = {}
    for row in acts:
        cap = next(cap for cap in capacities if cap["id"] == row["capacity"])
        for subject in [root_digest, digest("authority-capacity", cap)]:
            for at in [row["occurred_at"], now]:
                query = {"purpose": "REVOCATION", "subject_digest": subject, "at": at, "provider": provider, "source": "authority-revocations"}
                query_map[canonical_bytes(query)] = query
    for subject in [envelope_digest] + [digest("authority-credential", row) for row in credentials]:
        query = {"purpose": "REVOCATION", "subject_digest": subject, "at": now, "provider": provider, "source": "authority-revocations"}
        query_map[canonical_bytes(query)] = query
    for index, query in enumerate(sorted(query_map.values(), key=canonical_bytes)):
        observations.append({"query": query, "query_digest": digest("authority-query", query), "status": "AVAILABLE", "as_of": query["at"],
            "revision": "revocation-snapshot-1", "revoked": False, "evidence_ref": "host-revocation-" + str(index)})
    authenticated = [{"kind": kind, "record_digest": digest(domain, row), "provider": row["provider"], "channel": row.get("channel")}
        for collection, kind, domain in [(occupancies, "OCCUPANCY", "authority-occupancy"), (capacities, "CAPACITY", "authority-capacity"),
            (credentials, "CREDENTIAL", "authority-credential"), (returns, "RETURN", "authority-return")] for row in collection]
    supplied = {"schema": SCHEMA + "authority-input", "specification_pin": PIN, "source": source, "work_class": copy.deepcopy(work),
        "envelope": envelope, "proposal": proposal, "clock": {"source": envelope["clock_source"], "status": "AVAILABLE", "instant": now},
        "host_selection": {"root": root, "selection_evidence": "host-root-selection-" + work["id"],
            "authenticated_records": sorted(authenticated, key=canonical_bytes)},
        "occupancies": sorted(occupancies, key=lambda row: row["id"]), "capacities": sorted(capacities, key=lambda row: row["id"]),
        "credentials": credentials, "acts": sorted(acts, key=lambda row: digest("authority-act", row)),
        "returns": sorted(returns, key=lambda row: row["id"]), "observations": observations}
    if decision_bases is not None:
        supplied["decision_bases"] = copy.deepcopy(decision_bases)
    for req in source_requirements or []:
        supplied["observations"].append(observation(req, supplied, values=source_values[req["id"]],
            revision="QG-42" if req["id"] == "current-quality-gate" else req["id"] + "-revision-1"))
    supplied["observations"].sort(key=lambda row: digest("authority-observation", row))
    return supplied


def expected_authority(supplied, *, leaf=False, selected_leaf_results=None):
    """Derive the positive inventory specified by AUTHORITY-CHECKS and AUTH-008/009."""
    now = supplied["clock"]["instant"]
    source, work, envelope, proposal = (supplied[key] for key in ["source", "work_class", "envelope", "proposal"])
    subjects = {key + "_digest": digest("authority-" + key.replace("work_class", "work-class"), value)
                for key, value in [("source", source), ("work_class", work), ("envelope", envelope), ("proposal", proposal)]}
    op = digest("authority-operation", {name: subjects[name] for name in ["envelope_digest", "work_class_digest", "proposal_digest"]})
    values = {row["name"]: row["value"] for row in proposal["fields"]}
    scope = {member: sorted({values[name]["value"] for name in work["steps"][0]["scope_fields"][member]}) for member in ["subjects", "resources"]}
    checks = []
    def add(purpose, subject, requirement_ref, at=now):
        checks.append({"purpose": purpose, "subject_digest": subject, "requirement_ref": requirement_ref, "at": at})
    for purpose, subject, requirement_ref in [
        ("SOURCE_BINDING", subjects["envelope_digest"], source["id"]),
        ("ROOT_BINDING", subjects["envelope_digest"], supplied["host_selection"]["root"]["id"]),
        ("INPUT_SUPPORT", op, proposal["step"]), ("BINDING", op, envelope["scope"]["id"]),
        ("GATE_FLOOR", subjects["envelope_digest"], envelope["id"]),
        ("ENVELOPE_VALIDITY", subjects["envelope_digest"], envelope["id"])]:
        add(purpose, subject, requirement_ref)
    if not leaf:
        add("EXECUTOR_OCCUPANCY", op, proposal["executor"]["occupancy"])
    for row in supplied["credentials"]:
        add("CREDENTIAL", op, row["id"])
    for row in supplied["acts"]:
        subject = digest("authority-act", row)
        add("ACT_CAPACITY", subject, row["capacity"], row["occurred_at"])
        add("ACT_OCCUPANCY", subject, row["occupancy"], row["occurred_at"])
        add("ACT_RELIANCE", subject, row["capacity"])
        add("RETURN", subject, "return-" + row["id"])
        if row["kind"] == "ORGANISATIONAL_ATTESTATION":
            add("SEPARATION", subject, row["capacity"])
        if row["kind"] == "INSTANCE_DECISION":
            for criterion_id in row["criteria"]:
                add("GATE_CRITERION", subject, criterion_id, row["occurred_at"])
    for row in supplied["observations"]:
        if row["query"]["purpose"] == "REVOCATION":
            add("REVOCATION", row["query"]["subject_digest"], row["query_digest"], row["query"]["at"])
        else:
            add("SOURCE_OBSERVATION", subjects["envelope_digest"], row["query"]["requirement_id"], row["query"]["at"])
    decision_results = []
    for row in supplied.get("decision_bases", []):
        result = (selected_leaf_results or {}).get(row["requirement_id"]) or expected_authority(row["evidence"]["authority_input"], leaf=True)
        decision_results.append({"requirement_id": row["requirement_id"], "result": result, "result_digest": digest("authority-result", result)})
        requirement_row = next(r for r in envelope["decision_requirements"] if r["id"] == row["requirement_id"])
        subject = row["evidence"]["decision_act_digest"]
        add("HUMAN_DECISION", subject, row["requirement_id"])
        if requirement_row["distinct_from"]:
            add("SEPARATION", subject, row["requirement_id"])
        if envelope["gate"].get("decision_requirement") == row["requirement_id"]:
            selected = next(a for a in row["evidence"]["authority_input"]["acts"] if a["kind"] == "INSTANCE_DECISION")
            add("GATE_CRITERION", subject, "approved-status", selected["occurred_at"])
    evidence = {key: supplied[key] for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock"]}
    for key in ["evaluation_point", "decision_bases"]:
        if key in supplied:
            evidence[key] = supplied[key]
    result = {"schema": SCHEMA + ("human-decision-result" if leaf else "authority-result"), "specification_pin": PIN,
        "status": "EVIDENCE_VALID" if leaf else "READY_FOR_RESERVATION", **subjects, "operation_digest": op,
        "scope": scope, "actual_scope": copy.deepcopy(scope), "act_digests": sorted(digest("authority-act", row) for row in supplied["acts"]),
        "checks": sorted({canonical_bytes(row): row for row in checks}.values(), key=canonical_bytes), "required_budgets": [],
        "evidence_digest": digest("authority-evidence", evidence)}
    if "decision_bases" in supplied:
        result["decision_results"] = decision_results
    if leaf:
        result["decision_act_digest"] = digest("authority-act", next(row for row in supplied["acts"] if row["kind"] == "INSTANCE_DECISION"))
        result["effective_until"] = leaf_effective_until(supplied)
    keys = work["steps"][0]["exclusive_keys"]
    if keys:
        result["required_exclusive_keys"] = [{"id": row["id"], "slot": row["slot"], "namespace": row["namespace"],
            "key": [copy.deepcopy(p["value"] if "value" in p else values[p["field"]]) for p in row["projection"]], "retention": row["retention"]}
            for row in keys]
    return result


def leaf_effective_until(supplied):
    now = supplied["clock"]["instant"]
    root = supplied["host_selection"]["root"]
    ends = [supplied["envelope"]["temporal_validity"]["valid_until"]]
    if not root["prior_acts_survive_expiry"]:
        ends.append(root["validity"]["valid_until"])
    for channel in root["channels"]:
        if not channel["prior_returns_survive_expiry"]:
            ends.append(channel["validity"]["valid_until"])
    for capacity in supplied["capacities"]:
        validity = capacity["validity"]
        if capacity["reliance"]["kind"] == "CURRENT_ONLY":
            ends.append(validity["valid_until"])
            continue
        intervals = sorted([validity, capacity["reliance"]["validity"]], key=lambda row: row["valid_from"])
        components = []
        for interval in intervals:
            if components and (components[-1][1] is None or interval["valid_from"] <= components[-1][1]):
                components[-1][1] = None if components[-1][1] is None or interval["valid_until"] is None else max(components[-1][1], interval["valid_until"])
            else:
                components.append([interval["valid_from"], interval["valid_until"]])
        ends.append(next(end for start, end in components if start <= now and (end is None or now < end)))
    return min(end for end in ends if end is not None)


def decision_leaf(party, business, *, now=NOW, signed=SIGNED, signer_until=OCCUPANCY_END, revision="3", actor=None, capacity_until=None, source_padding=0):
    import json
    is_cedar = party == "cedar"
    role = "quality-disposition-reviewer" if is_cedar else "customer-quality-representative"
    issue_field = "cedar_approval_identity" if is_cedar else "customer_assent_identity"
    values = {name: copy.deepcopy(value) for name, value in business.items() if name not in ["cedar_approval_identity", "customer_assent_identity"]}
    values.update(dossier_id=typed("CV-DOSSIER-026"), agreement_id=typed("CV-ATR-07"), executor_role=typed("inventory-records-agent"),
        effective_from=typed(signed, "INSTANT"), effective_until=typed(END, "INSTANT"),
        decision_identity=copy.deepcopy(business[issue_field]), decision_revision=typed(revision, "REVISION"))
    step = operation_projection("decide-" + party + "-disposition", values, role, leaf=True)
    work = {"schema": SCHEMA + "authority-work-class", "id": "cdmo-" + party + "-human-decision", "revision": "3",
        "types": copy.deepcopy(TYPES), "steps": [step], "authority_profile": "EVIDENCE_ONLY"}
    supplied = base_authority(work, values, principal=CEDAR if is_cedar else ALDER, role=role,
        actor=actor or ("quality-reviewer-01" if is_cedar else "customer-quality-01"), now=now, leaf=True,
        issue=json.loads(business[issue_field]["value"])["provider_record_id"], signed=signed, signer_until=signer_until, capacity_until=capacity_until, source_padding=source_padding)
    result = expected_authority(supplied, leaf=True)
    return {"schema": SCHEMA + "human-decision-evidence", "authority_input": supplied,
        "decision_act_digest": result["decision_act_digest"]}, result


def basis_digest(evidence):
    supplied = evidence["authority_input"]
    return digest("human-decision-reliance-subjects", {"root_digest": digest("authority-root", supplied["host_selection"]["root"]),
        "envelope_digest": digest("authority-envelope", supplied["envelope"]),
        "capacities": [{"id": row["id"], "capacity_digest": digest("authority-capacity", row)} for row in supplied["capacities"]]})


def decision_coordinates(party):
    return {"provider": party + "-quality-records", "source": "disposition-decisions" if party == "cedar" else "customer-assents",
        "record_type": "batch-disposition" if party == "cedar" else "customer-assent"}


def identity_text(party, issue):
    return canonical_bytes({**decision_coordinates(party), "provider_record_id": issue}).decode()


def outer_requirements(business, leaves):
    requirements, facts, decisions = [], {}, []
    def observed(req, name):
        return {"kind": "OBSERVATION_FIELD", "requirement_id": req, "field": name}
    def equal(req, name, right):
        return {"id": name, "kind": "EQUALS", "left": observed(req, name), "right": right}
    def literal(value):
        return {"kind": "LITERAL", "value": value}
    def add(req_id, values, *, provider="cedar-quality-records", source="quality-prerequisites", record_type="quality-prerequisite",
            record_id=None, relations=None, status="AVAILABLE", purpose="AUTHORITY", key_projection=None):
        req = requirement(req_id, step="authorize-customer-transfer", provider=provider, source=source, record_type=record_type,
            purpose=purpose, subject={"kind": "PROPOSAL_FIELD", "field": "batch_id"}, record_id=record_id or (req_id + "-record") if status == "AVAILABLE" else None,
            expected_status=status, fields=[{"name": name, "type_ref": value["type_ref"]} for name, value in sorted(values.items())],
            relations=sorted(relations if relations is not None else [equal(req_id, name, literal(value)) for name, value in values.items()], key=lambda row: row["id"]))
        if key_projection:
            req["key_projection"] = key_projection
        requirements.append(req)
        facts[req_id] = copy.deepcopy(values)
        return req
    for party in ["alder", "cedar"]:
        evidence, _ = leaves[party]
        supplied = evidence["authority_input"]
        decision = next(row for row in supplied["acts"] if row["kind"] == "INSTANCE_DECISION")
        req_id = party + "-decision-record"
        decision_id = party + "-decision"
        values = {row["name"]: copy.deepcopy(row["value"]) for row in supplied["proposal"]["fields"]}
        bindings = []
        for name, value in values.items():
            outer_name = ("cedar_approval_identity" if party == "cedar" else "customer_assent_identity") if name == "decision_identity" else name
            selector = {"kind": "PROPOSAL_FIELD", "field": outer_name} if outer_name in business else {"kind": "LITERAL", "value": copy.deepcopy(value)}
            bindings.append({"field": name, "value": selector})
        declarations = {"id": decision_id, "step": "authorize-customer-transfer", "principal": supplied["envelope"]["principal"],
            "role": supplied["envelope"]["gate"]["role"], "work_class_digest": digest("authority-work-class", supplied["work_class"]),
            "envelope_digest": digest("authority-envelope", supplied["envelope"]), "record_requirement_id": req_id,
            "identity_field": "decision_identity", "validity_fields": {"not_before_field": "effective_from", "not_after_field": "effective_until"},
            "context_bindings": sorted(bindings, key=lambda row: row["field"]),
            "distinct_from": sorted([{"kind": "EXECUTOR"}, {"kind": "DECISION", "requirement_id": "cedar-decision" if party == "alder" else "alder-decision"}], key=canonical_bytes)}
        decisions.append(declarations)
        rels = [{"id": "issue-id", "kind": "EQUALS", "left": {"kind": "OBSERVATION_ID", "requirement_id": req_id, "type_ref": "IDENTITY"},
            "right": {"kind": "DECISION_ACT", "requirement_id": decision_id, "member": "id", "type_ref": "IDENTITY"}}]
        for member in ["digest", "actor", "role", "principal", "occurred_at"]:
            name = "act-" + member
            values[name] = typed(evidence["decision_act_digest"] if member == "digest" else decision[member], "INSTANT" if member == "occurred_at" else "IDENTITY")
            rels.append(equal(req_id, name, {"kind": "DECISION_ACT", "requirement_id": decision_id, "member": member, "type_ref": values[name]["type_ref"]}))
        for row in supplied["proposal"]["fields"]:
            rels.append(equal(req_id, row["name"], {"kind": "DECISION_FIELD", "requirement_id": decision_id, "field": row["name"]}))
        add(req_id, values, **decision_coordinates(party), record_id=decision["id"], relations=rels)
        basis_id = party + "-authority-scope"
        add(basis_id, {"basis_digest": typed(basis_digest(evidence)), "no_applicable_revocation": typed(True, "BOOLEAN")},
            provider=party + "-quality-authority", source="authority-scope", record_type="authority-scope-record",
            relations=[equal(basis_id, "basis_digest", {"kind": "DECISION_BASIS", "requirement_id": decision_id, "type_ref": "IDENTITY"}),
                equal(basis_id, "no_applicable_revocation", literal(typed(True, "BOOLEAN")))])
        add(party + "-decision-withdrawal", {}, provider=party + "-quality-records", source="decision-withdrawals",
            record_type="withdrawal", status="ABSENT")
    add("current-quality-gate", {"batch_id": business["batch_id"], "site_id": business["site_id"], "complete_writer_coverage": typed(True, "BOOLEAN")},
        provider="cedar-quality-gate-service", source="quality-gate", record_type="quality-gate-snapshot")
    add("prior-attempt-history", {"batch_id": business["batch_id"], "site_id": business["site_id"], "candidate_request_id": business["request_id"],
        "complete": typed(True, "BOOLEAN"), "candidate_registered": typed(True, "BOOLEAN"), "no_other_unresolved_attempt": typed(True, "BOOLEAN")},
        provider="cedar-attempt-coordinator", source="prior-attempt-history", record_type="prior-attempt-history",
        key_projection=[{"field": name, "type_ref": business[name]["type_ref"]} for name in ["batch_id", "request_id", "site_id"]])
    add("inventory-state", {"batch_id": business["batch_id"], "revision": business["expected_inventory_revision"], "status": business["old_status"]},
        provider=PROVIDER, source="batch-inventory", record_type="inventory-record", record_id="CV-INVENTORY-026")
    for name, record_id, revision in [("manufacturing", "CV-MFG-026", "8"), ("laboratory", "CV-LAB-026", "6"),
            ("deviations", "CV-DEV-026", "4"), ("specification", "AAV-DS-04-SPEC", "2")]:
        values = {"batch_id": business["batch_id"], "revision": typed(revision, "REVISION"), "acceptable": typed(True, "BOOLEAN")}
        if name == "laboratory":
            values.update({name: typed("PASS", "STATUS") for name in ["identity", "vector_genome_titer", "potency", "endotoxin", "microbiological_safety"]})
        add(name + "-evidence", values, provider="cedar-" + name + "-records", source=name + "-records", record_type=name + "-record", record_id=record_id)
    add("dossier", {"revision": business["dossier_revision"], "digest": business["dossier_digest"], "immutable": typed(True, "BOOLEAN")}, source="predecision-dossiers", record_type="manufacturing-dossier", record_id="CV-DOSSIER-026")
    add("quality-agreement", {"agreement_id": typed("CV-ATR-07"), "revision": business["agreement_revision"], "applicable": typed(True, "BOOLEAN")},
        provider="cedar-alder-quality-governance", source="quality-agreements", record_type="quality-agreement", record_id="CV-ATR-07")
    for scope in ["batch", "product", "site"]:
        add(scope + "-hold", {}, provider="cedar-quality-holds", source=scope + "-holds", record_type="blocking-hold", status="ABSENT")
    for fact in ["session", "role"]:
        req_id = "executor-current-" + fact
        add(req_id, {"actor": typed("inventory-agent-01"), "current": typed(True, "BOOLEAN")}, provider="cedar-identity-provider",
            source="authenticated-sessions" if fact == "session" else "role-occupancy", record_type=fact,
            purpose="AUTHENTICATED_SESSION" if fact == "session" else "ROLE_ASSIGNMENT")
    return sorted(requirements, key=lambda row: row["id"]), facts, decisions


def exclusive_keys():
    def literal(name, value, type_ref="IDENTITY"):
        return {"key_field": name, "value": typed(value, type_ref)}
    def field(name):
        return {"key_field": name, "field": name, "type_ref": type_for(name)}
    return [{"id": "approved-disposition-key", "slot": "approved-disposition-use", "namespace": "cedar-approved-batch-disposition",
        "retention": "RETAIN_UNTIL_SETTLED_OR_AUTHORIZED_RELEASE", "projection": [literal("provider", PROVIDER), field("batch_id"), field("site_id"), field("cedar_approval_identity"), literal("decision_revision", "3", "REVISION")]},
        {"id": "request-key", "slot": "request-use", "namespace": "cedar-transfer-request", "retention": "RETAIN_UNTIL_SETTLED_OR_AUTHORIZED_RELEASE",
         "projection": [literal("issuer", CEDAR), field("request_id")]}]


def completion_carrier(business, correction_options=None):
    return {"terminal_policy": "STOP_RETAIN", "effect_provider": PROVIDER, "effect_source": EVENT_SOURCE, "effect_record_type": EVENT_TYPE,
        "no_effect_provider": PROVIDER, "no_effect_source": EVENT_SOURCE, "no_effect_record_type": "batch-transfer-no-effect",
        "status_field": "new_status", "status_type_ref": "STATUS", "status_request_field": "new_status",
        "success_values": [copy.deepcopy(business["new_status"])], "failure_values": [], "route_label_field": None, "route_label_type_ref": None,
        "evidence_bindings": [{"request_field": name, "evidence_field": "previous_inventory_revision" if name == "expected_inventory_revision" else name} for name in sorted(business)],
        "provider_record_identity": {"field": "event_id", "type_ref": "IDENTITY"}, "event_time_identity": {"field": "event_time", "type_ref": "INSTANT"},
        "additional_fields": [{"name": "resulting_inventory_revision", "value": typed("12", "REVISION")}],
        "authorization_revision_bindings": [{"evidence_field": "committed_quality_gate_revision", "type_ref": "REVISION", "requirement_id": "current-quality-gate"}],
        "lookup": {"provider": PROVIDER, "source": EVENT_SOURCE, "record_type": EVENT_TYPE, "namespace": "cedar-batch-disposition-lookup",
            "key_projection": [{"field": name, "type_ref": type_for(name)} for name in ["batch_id", "cedar_approval_identity", "request_id", "site_id"]]},
        "correction_policy": correction_policy(**(correction_options or {}))}


def cdmo_authority(*, now=NOW, instance="cdmo-instance-1", occurrence="cdmo-occurrence-1", business=None, leaf_options=None, source_padding=0, correction_options=None):
    business = business_fields() if business is None else copy.deepcopy(business)
    leaves = {party: decision_leaf(party, business, now=now, **(leaf_options or {}).get(party, {})) for party in ["alder", "cedar"]}
    requirements, facts, decisions = outer_requirements(business, leaves)
    step = operation_projection("authorize-customer-transfer", business, "inventory-records-agent")
    step["exclusive_keys"] = exclusive_keys()
    step["authority_type_refs"] = sorted(TYPE_BY_NAME)
    step["completion"] = completion_carrier(business, correction_options)
    step["dispatch_gate"] = {"kind": "SOURCE_REQUIREMENTS", "requirements": sorted(row["id"] for row in requirements if not row["id"].startswith("executor-current-")),
        "coordinator_requirement": "current-quality-gate", "fence_provider": "cedar-quality-gate-service", "fence_source": "quality-gate",
        "authorization_seconds": "60", "validity_requirements": [{"requirement_id": party + "-decision-record",
            "not_before_field": "effective_from", "not_after_field": "effective_until"} for party in ["alder", "cedar"]]}
    work = {"schema": SCHEMA + "authority-work-class", "id": "pharmaceutical-batch-disposition", "revision": "revision-3",
        "types": copy.deepcopy(TYPES), "steps": [step]}
    supplied = base_authority(work, business, principal=CEDAR, role="inventory-records-agent", actor="inventory-agent-01", now=now,
        gate_requirement="cedar-decision", decision_requirements=decisions, source_requirements=requirements, source_values=facts,
        decision_bases=[{"requirement_id": party + "-decision", "evidence": leaves[party][0]} for party in ["alder", "cedar"]],
        instance=instance, occurrence=occurrence, source_padding=source_padding)
    return supplied, expected_authority(supplied), {"business": business, "leaves": leaves, "source_values": facts}


def referral_policy():
    common = {"queue": "cedar-quality-review", "safe_state": "no-new-transfer-authorization"}
    return {"authority": [{"id": "quality-authority-review", "destination_role": "cedar-quality-disposition-authority",
        "purpose": "review-disposition-authority", "via_role": None, "requirement_ids": [], **common}],
        "completion": [{"id": "inventory-completion-review", "destination_role": "inventory-records-custodian",
            "purpose": "reconcile-inventory-evidence", "via_role": None, "requirement_ids": [], **common},
            {"id": "quality-completion-review", "destination_role": "cedar-quality-disposition-authority",
             "purpose": "investigate-native-inventory-event", "via_role": None, "requirement_ids": [], **common}]}


def cdmo_base(*, instance="cdmo-instance-1", business=None, leaf_options=None, correction_options=None):
    supplied, result, facts = cdmo_authority(instance=instance, business=business, leaf_options=leaf_options, correction_options=correction_options)
    authority_step = supplied["work_class"]["steps"][0]
    step = {**copy.deepcopy(authority_step), "kind": "OPERATION", "authority_requirements": [supplied["envelope"]["id"]],
        "shared_budgets": [], "prior_effect_bindings": [], "prior_actor_separations": [],
        "permit_seconds": "300", "failure_behavior": "STOP", "referral_policy": referral_policy()}
    definition = {"schema": SCHEMA + "work-class-definition", "specification_pin": PIN,
        "id": supplied["work_class"]["id"], "revision": "revision-3", "profile": "LINEAR", "root": step["id"],
        "participants": [{"id": "inventory-agent-01", "role": "inventory-records-agent", "kind": "AGENT"}],
        "objects": [], "types": copy.deepcopy(TYPES), "steps": [step, structural_step("terminal", "TERMINAL")],
        "relationships": [{"kind": "SEQUENCE", "from": step["id"], "to": "terminal"}], "choices": [],
        "occurrence_limits": [{"step_id": step["id"], "maximum": "1"}], "loops": [], "deadlines": [],
        "parallel_blocks": [], "fanouts": [], "shared_budgets": [],
        "limits": {"maximum_proposals": "64", "maximum_activations": "64", "maximum_actuations": "1",
            "maximum_active_obligations": "64", "maximum_fanout_objects": "64"},
        "source": {"id": SOURCE_ID, "revision": supplied["source"]["revision"],
            "obligations": sorted(row["id"] for row in supplied["source"]["obligations"])}}
    definition_digest = digest("work-class-definition", definition)
    root_occurrence = occurrence(definition_digest, instance, step["id"])
    supplied, result, facts = cdmo_authority(instance=instance, occurrence=root_occurrence["occurrence_id"], business=facts["business"], leaf_options=leaf_options, correction_options=correction_options)
    paths, obligations = readback_paths(definition), definition["source"]["obligations"]
    # Synthetic admission coverage; the separate source correspondence remains PENDING.
    synthetic_mappings = [{"source_obligation_id": obligation, "provision_paths": paths[index::len(obligations)]}
        for index, obligation in enumerate(obligations)]
    deploy_input, deploy_result = deployment(definition, instance_id=instance, organization_id=CEDAR,
        authorization_time="2026-10-06T11:59:00Z", evidence_expires_at=END, correspondence_mappings=synthetic_mappings)
    clock = available_clock(supplied["clock"]["source"], "1", NOW)
    event = {"schema": SCHEMA + "runtime-event", "event_id": "cdmo-clock-1", "kind": "CLOCK", "instance_id": instance,
        "expected_state_revision": deploy_result["state"]["revision"], "expected_state_digest": deploy_result["state_digest"],
        "clock": clock, "activation_clocks": []}
    def mutate(state):
        state["clocks"].append(copy.deepcopy(clock))
    clock_result = admitted_transition(deploy_result["state"], event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": "1", "status": "AVAILABLE"}], mutate=mutate)
    executor = supplied["proposal"]["executor"]
    proposal = {"schema": SCHEMA + "runtime-event", "kind": "PROPOSE", "event_id": "cdmo-proposal-1", "instance_id": instance,
        "expected_state_revision": clock_result["state"]["revision"], "expected_state_digest": clock_result["state_digest"],
        "occurrence": root_occurrence, "native_request": {name: copy.deepcopy(supplied["proposal"][name]) for name in ["interface", "operation", "fields"]},
        "executor": {"participant_id": executor["actor"], "role": executor["role"], "binding_digest": digest("executor-binding", executor)},
        "credential_ids": sorted(row["id"] for row in supplied["credentials"]), "authority_input": supplied, "budget_inputs": [],
        "clock_revision": "1", "observation_digests": sorted(digest("authority-observation", row) for row in supplied["observations"])}
    return {"definition": definition, "definition_digest": definition_digest, "deploy_input": deploy_input, "deploy_result": deploy_result,
        "clock_event": event, "clock_result": clock_result, "authority_input": supplied, "authority_result": result,
        "proposal_event": proposal, "source_values": facts["source_values"], "business": facts["business"],
        "permit_expires_at": add_seconds(NOW, "300"), "correction_options": correction_options or {}}


def cdmo_registry(base):
    authority = base["authority_input"]
    keys = authority["work_class"]["steps"][0]["exclusive_keys"]
    native_fields = [{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in authority["proposal"]["fields"]]
    completed_fields = [{"name": "previous_inventory_revision" if row["name"] == "expected_inventory_revision" else row["name"],
        "type_ref": row["type_ref"]} for row in native_fields]
    completed_fields += [{"name": name, "type_ref": kind} for name, kind in [("committed_quality_gate_revision", "REVISION"),
        ("event_id", "IDENTITY"), ("event_time", "INSTANT"), ("resulting_inventory_revision", "REVISION")]]
    completed_fields.sort(key=lambda row: row["name"])
    config = {"schema": SCHEMA + "reservation-registry", "id": "cedar-batch-disposition-registry", "principal": CEDAR,
        "clock_source": authority["clock"]["source"], "administration_provider": "cedar-quality-governance",
        "administration_source": "exclusive-disposition-cutover", "administration_role": "cedar-quality-governance-lead",
        "slots": [], "exclusive_slots": []}
    for key in keys:
        projection = [{"key_field": row["key_field"], "kind": "LITERAL", "value": copy.deepcopy(row["value"])} if "value" in row else
            {"key_field": row["key_field"], "kind": "NATIVE_FIELD", "field": row["field"], "type_ref": row["type_ref"]} for row in key["projection"]]
        config["exclusive_slots"].append({"slot": key["slot"], "namespace": key["namespace"], "authorized_classes": [base["definition"]["id"]],
            "retention": key["retention"], "permit_seconds": "300", "key_shape": [{"name": row["key_field"],
                "type_ref": row.get("type_ref", row.get("value", {}).get("type_ref"))} for row in key["projection"]],
            "types": copy.deepcopy(TYPES), "history_record_fields": {"held": native_fields, "consumed": completed_fields},
            "history_projection": projection, "uniqueness": {"kind": "EXCLUSIVE_MEDIATOR_SEEDED", "provider": PROVIDER,
                "source": EVENT_SOURCE, "record_type": "batch-disposition-history", "history_scope": key["slot"] + "-complete-prior-uses",
                "cutover_id": "cedar-disposition-cutover-1", "evidence_ref": "host-all-disposition-writers-mediated"}})
    facts = {"configuration": config, "clock": copy.deepcopy(authority["clock"]), "authority_a": copy.deepcopy(authority),
        "authority_a_result": copy.deepcopy(base["authority_result"])}
    state, seeds = history_state(facts), []
    for key in keys:
        supplied = seed_request(facts, state, key["slot"], [], "cdmo-seed-" + key["slot"])
        supplied["host_evidence"]["administration_bases"][0]["validity"] = copy.deepcopy(VALID)
        output = seed_result(facts, supplied)
        seeds.append([supplied, output])
        state = output["state"]
    return facts, state, seeds


def cdmo_permitted(base):
    facts, registry, seeds = cdmo_registry(base)
    proposal = copy.deepcopy(base["proposal_event"])
    registry_digest = digest("reservation-registry", facts["configuration"])
    reserve_id = digest("lifecycle-reservation-event", {"instance_id": proposal["instance_id"], "lifecycle_event_id": proposal["event_id"],
        "lifecycle_event_kind": "PROPOSE", "reservation_event_kind": "RESERVE", "registry_digest": registry_digest})
    event, host = host_and_event(facts, "RESERVE", reserve_id, registry["core"]["revision"],
        {"authority": facts["authority_a"], "histories": [], "exclusive_keys": base["authority_result"]["required_exclusive_keys"]}, administration=False)
    core = copy.deepcopy(registry["core"])
    record = reservation_record(facts, "authority_a", reserve_id)
    record["permit_until"] = base["permit_expires_at"]
    core["reservations"].append(record)
    owner = {"kind": "WORK_OCCURRENCE", "work_class": base["definition"]["id"], "instance_id": proposal["instance_id"],
        "occurrence_id": proposal["occurrence"]["occurrence_id"]}
    core["exclusive_keys"].extend({**copy.deepcopy(row), "owner": owner, "acquisition_event": reserve_id,
        "status": "HELD", "settlement_evidence": None} for row in record["exclusive_keys"])
    core["exclusive_keys"].sort(key=lambda row: row["key_digest"])
    reserved = transition(registry, event, host, core, "RESERVED", reservation_id=reserve_id, authority_result=base["authority_result"])
    supplied = reservation_request(registry, event, host)
    proposal["budget_inputs"] = [{"registry_digest": registry_digest, "affected_anchors": [], "expected_revision": registry["core"]["revision"], "request": supplied}]
    budget_output = {"registry_digest": registry_digest, "affected_anchors": [], "result": reserved}
    output = permitted_budget_proposal(base, proposal, budget_output)
    base.update(reservation_facts=facts, reservation_result=reserved, key_proposal_event=proposal, registry_seed_trace=seeds, reservation_input=supplied)
    return output


def refreshed(authority, instant):
    current = copy.deepcopy(authority)
    current["clock"]["instant"] = instant
    current["evaluation_point"] = "DISPATCH"
    for basis in current.get("decision_bases", []):
        basis["evidence"]["authority_input"] = refreshed(basis["evidence"]["authority_input"], instant)
    declarations = {row["id"]: row for row in current["envelope"].get("source_observation_requirements", [])}
    rows = []
    for old in current["observations"]:
        query = copy.deepcopy(old["query"])
        if query["purpose"] == "REVOCATION":
            if query["at"] == authority["clock"]["instant"]:
                query["at"] = instant
            row = copy.deepcopy(old)
            row.update(query=query, query_digest=digest("authority-query", query), as_of=query["at"])
        else:
            req = declarations[query["requirement_id"]]
            row = observation(req, current, values={value["name"]: value["value"] for value in old["fields"]},
                revision=old["revision"], record_id=old.get("provider_record_id"), status=old["status"])
        rows.append(row)
    current["observations"] = sorted(rows, key=lambda row: digest("authority-observation", row))
    return current


def cdmo_fence(event, result):
    current, permit = event["authority_input"], event["permit"]
    gate = current["work_class"]["steps"][0]["dispatch_gate"]
    sources = []
    for req_id in gate["requirements"]:
        row = next(row for row in current["observations"] if row["query"].get("requirement_id") == req_id)
        query = row["query"]
        sources.append({"requirement_id": req_id, "provider": query["provider"], "source": query["source"],
            "expected_status": query["expected_status"], "record_id": row.get("provider_record_id"), "provider_revision": row["revision"],
            "query_digest": row["query_digest"], "observation_digest": digest("authority-observation", row)})
    checked = current["clock"]["instant"]
    ends = [permit["expires_at"], add_seconds(checked, gate["authorization_seconds"]), current["envelope"]["temporal_validity"]["valid_until"]]
    for validity in gate["validity_requirements"]:
        row = next(row for row in current["observations"] if row["query"].get("requirement_id") == validity["requirement_id"])
        ends.append(next(value["value"]["value"] for value in row["fields"] if value["name"] == validity["not_after_field"]))
    ends.extend(row["result"]["effective_until"] for row in result["decision_results"])
    expires = min(ends)
    scope = {"instance_id": event["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"], "permit_digest": permit["permit_id"],
        "native_request": event["native_request"], "connector": event["connector"], "dispatch_intent_id": event["dispatch_intent_id"],
        "checked_at": checked, "expires_at": expires, "authority_result_digest": digest("authority-result", result), "sources": sources}
    coordinator = next(row for row in sources if row["requirement_id"] == gate["coordinator_requirement"])
    return {"kind": "SOURCE_REQUIREMENTS", "provider": gate["fence_provider"], "source": gate["fence_source"],
        "provider_revision": coordinator["provider_revision"], "scope_digest": digest("dispatch-authorization-scope", scope),
        "checked_at": checked, "status": "EFFECTIVE", "sources": sources}, expires


def cdmo_authorized(base, prior):
    instant = "2026-10-06T12:11:00Z"
    clock = available_clock(base["authority_input"]["clock"]["source"], "2", instant)
    clock_event = {"schema": SCHEMA + "runtime-event", "kind": "CLOCK", "event_id": "cdmo-clock-2", "instance_id": prior["state"]["instance_id"],
        "expected_state_revision": prior["state"]["revision"], "expected_state_digest": state_digest(prior["state"]), "clock": clock, "activation_clocks": []}
    def record_clock(state):
        state["clocks"].append(copy.deepcopy(clock))
    clock_result = admitted_transition(prior["state"], clock_event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": "2", "status": "AVAILABLE"}], mutate=record_clock)
    base["dispatch_clock_event"], base["dispatch_clock_result"] = clock_event, clock_result
    prior = retained(clock_result, prior["permit"])
    current = refreshed(base["authority_input"], instant)
    result = expected_authority(current)
    body = {"id": "cedar-inventory-connector", "version": "revision-3"}
    connector = {**body, "binding_digest": digest("connector-binding", body)}
    event = {"schema": SCHEMA + "runtime-event", "kind": "AUTHORIZE_DISPATCH", "event_id": "cdmo-authorize-1", "instance_id": prior["state"]["instance_id"],
        "expected_state_revision": prior["state"]["revision"], "expected_state_digest": state_digest(prior["state"]), "permit": copy.deepcopy(prior["permit"]),
        "native_request": copy.deepcopy(prior["permit"]["native_request"]), "connector": connector, "authorization_fence": None, "authority_input": current,
        "dispatch_intent_id": "cdmo-intent-1", "observation_digests": sorted(digest("authority-observation", row) for row in current["observations"]), "clock_revision": "2"}
    event["authorization_fence"], expires = cdmo_fence(event, result)
    result_digest = digest("authority-result", result)
    record_body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": prior["permit"]["permit_id"],
        "native_request": event["native_request"], "connector": connector, "authorization_fence": event["authorization_fence"],
        "observation_digests": event["observation_digests"], "clock_revision": "2", "dispatch_intent_id": event["dispatch_intent_id"],
        "authority_input": current, "authority_result": result, "authority_result_digest": result_digest, "expires_at": expires,
        "supersedes_authorization_digest": None}
    record = {"authorization_digest": digest("dispatch-authorization", record_body), **record_body}
    evaluation_body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": prior["permit"]["permit_id"],
        "dispatch_intent_id": event["dispatch_intent_id"], "clock_revision": "2", "authority_input": current, "authority_result": result,
        "authority_result_digest": result_digest, "authorization_digest": record["authorization_digest"], "disposition": "AUTHORIZED"}
    evaluation = {"evaluation_digest": digest("dispatch-authorization-evaluation", evaluation_body), **evaluation_body}
    def mutate(state):
        state["authorizations"].append(record)
        state["authorization_evaluations"].append(evaluation)
    output = admitted_transition(prior["state"], event, disposition="AUTHORIZED", reason_codes=[],
        details=[{"kind": "AUTHORIZATION", "authorization_digest": record["authorization_digest"], "permit_digest": prior["permit"]["permit_id"],
            "gate_kind": "SOURCE_REQUIREMENTS", "checked_at": instant, "expires_at": expires, "sources": event["authorization_fence"]["sources"]}],
        receipt_permit_digest=prior["permit"]["permit_id"], receipt_authority_result_digest=result_digest,
        receipt_authorization_evaluation_digest=evaluation["evaluation_digest"], mutate=mutate)
    return event, retained(output, prior["permit"])


def cdmo_dispatched(base, prior, *, attempt_status="SENT", acknowledgement_status="NONE"):
    authorization = prior["state"]["authorizations"][-1]
    event = dispatch_event(base, prior, event_id="cdmo-dispatch-1", attempt_status=attempt_status,
        acknowledgement_status=acknowledgement_status, attempted_at="2026-10-06T12:11:00Z", clock_revision="2", authorization_digest=authorization["authorization_digest"])
    event["connector"] = copy.deepcopy(authorization["connector"])
    disposition, reasons, status = "DISPATCH_RECORDED", [], "DISPATCHED"
    if attempt_status == "NOT_SENT":
        disposition, reasons, status = "DISPATCH_REFUSED", ["NATIVE_NOT_SENT"], "PERMITTED"
    elif attempt_status == "REJECTED":
        disposition, reasons, status = "DISPATCH_REFUSED", ["NATIVE_DISPATCH_REJECTED"], "PERMITTED"
    elif acknowledgement_status == "ACCEPTED":
        disposition = "ACKNOWLEDGED"
    elif attempt_status == "UNKNOWN":
        reasons = ["DISPATCH_STATUS_UNKNOWN"]
    return event, retained(dispatch_result(prior, event, disposition=disposition, reasons=reasons, occurrence_status=status), prior["permit"])


def cdmo_native(base, prior, *, actual_fields=None, evidence_id="cdmo-native-evidence-1", provider_record_id="CV-BTA-026-001"):
    authorization = next(row for row in prior["state"]["authorizations"] if row["authorization_digest"] == prior["state"]["dispatches"][-1]["authorization_digest"])
    revision = next(row["provider_revision"] for row in authorization["authorization_fence"]["sources"] if row["requirement_id"] == "current-quality-gate")
    if actual_fields is None:
        actual_fields = [{"name": "previous_inventory_revision" if row["name"] == "expected_inventory_revision" else row["name"],
            "value": copy.deepcopy(row["value"])} for row in prior["permit"]["native_request"]["fields"]]
        actual_fields += [{"name": name, "value": value} for name, value in [("event_id", typed(provider_record_id)),
            ("event_time", typed("2026-10-06T12:11:01Z", "INSTANT")), ("resulting_inventory_revision", typed("12", "REVISION")),
            ("committed_quality_gate_revision", typed(revision, "REVISION"))]]
    record = governed_native_evidence(base, prior, prior, evidence_id=evidence_id, result_value="APPROVED_FOR_CUSTOMER_TRANSFER",
        native_operation_id="cedar-transfer-operation-042", event_time="2026-10-06T12:11:01Z", observed_at="2026-10-06T12:11:01Z", actual_fields=actual_fields)
    record.update(provider=PROVIDER, source=EVENT_SOURCE, record_type=EVENT_TYPE, provider_record_id=provider_record_id, provider_revision="CV-BTA-026-001-R1")
    record["record_digest"] = digest("provider-native-record", {name: record[name] for name in (
        "provider", "source", "record_type", "provider_record_id", "provider_revision", "actual_fields", "event_time")})
    return record


def cdmo_settlement(base, prior, event, *, mismatch=False, registry_state=None):
    facts = base["reservation_facts"]
    state = copy.deepcopy(registry_state or base["reservation_result"]["state"])
    evidence, basis = event["native_evidence"], prior["permit"]["budget_revisions"][0]
    record = native(facts, "EFFECT", evidence["evidence_id"], reservation_id=basis["reservation_id"])
    for name in ["provider", "source", "evidence_ref", "actual_fields", "collections", "rules_out_past_and_future_effects"]:
        record[name] = copy.deepcopy(evidence[name])
    record.update(effect_id=evidence["native_operation_id"], occurred_at=evidence["event_time"], completion_mismatch=mismatch,
        mismatch_reason="UNEXPECTED_EFFECT" if mismatch else None, observed_request=None if mismatch else copy.deepcopy(record["request"]))
    settle_id = digest("lifecycle-reservation-event", {"instance_id": event["instance_id"], "lifecycle_event_id": event["event_id"],
        "lifecycle_event_kind": "EFFECT_OBSERVED", "reservation_event_kind": "SETTLE", "registry_digest": basis["registry_digest"]})
    latest = max((row for row in prior["state"]["clocks"] if row["source"] == prior["permit"]["clock_source"]), key=lambda row: int(row["revision"]))
    settle_clock = {"source": latest["source"], "status": latest["status"], "instant": latest["observed_time"]}
    settle, host = host_and_event(facts, "SETTLE", settle_id, state["core"]["revision"], {"native": record, "histories": []}, event_clock=settle_clock, administration=False)
    supplied = {"registry_digest": basis["registry_digest"], "affected_anchors": [], "expected_revision": state["core"]["revision"],
        "request": reservation_request(state, settle, host)}
    core = copy.deepcopy(state["core"])
    reservation = next(row for row in core["reservations"] if row["id"] == basis["reservation_id"])
    reservation["status"] = "DISPUTED" if mismatch else "SETTLED"
    if not mismatch:
        reservation["matched_effect"] = evidence["native_operation_id"]
        selected = {row["key_digest"] for row in reservation["exclusive_keys"]}
        for row in core["exclusive_keys"]:
            if row["key_digest"] in selected:
                row.update(status="CONSUMED", settlement_evidence=evidence["native_operation_id"])
    core["effects"].append(effect_record(record, "DISPUTED" if mismatch else "MATCHED", "UNEXPECTED_EFFECT" if mismatch else "MATCHED_EFFECT", affected_anchors=[]))
    output = transition(state, settle, host, core, "EFFECT_DISPUTED" if mismatch else "SETTLED", reservation_id=basis["reservation_id"], reasons=["UNEXPECTED_EFFECT"] if mismatch else [])
    return supplied, {"registry_digest": basis["registry_digest"], "affected_anchors": [], "result": output}


def cdmo_completed(base, prior, *, actual_fields=None, mismatch=False, registry_state=None):
    record = cdmo_native(base, prior, actual_fields=actual_fields)
    latest = max((row for row in prior["state"]["clocks"] if row["source"] == prior["permit"]["clock_source"]), key=lambda row: int(row["revision"]))
    event = governed_effect_event(prior, prior, record, event_id="cdmo-effect-1", clock_revision=latest["revision"])
    supplied, registry = cdmo_settlement(base, prior, event, mismatch=mismatch, registry_state=registry_state)
    event["budget_inputs"] = [supplied]
    output = terminal_effect_result(base, prior, event, classification="UNEXPECTED" if mismatch else "MATCHED",
        disposition="DISPUTED" if mismatch else "COMPLETED", reason_codes=["BUDGET_EFFECT_DISPUTED", "UNEXPECTED_EFFECT"] if mismatch else [],
        occurrence_status="BLOCKED_DISPUTE" if mismatch else None, disputed=mismatch,
        complete_disposition=None if mismatch else "SUCCEEDED", route=not mismatch, budget_results=[registry])
    return event, retained(output, prior["permit"]), registry


def cdmo_late_exact(base, prior, *, blocked=False):
    record = cdmo_native(base, prior, evidence_id="cdmo-late-exact-evidence")
    event = governed_effect_event(prior, prior, record, event_id="cdmo-late-exact-event", clock_revision="3")
    supplied, registry = cdmo_settlement(base, prior, event)
    event["budget_inputs"] = [supplied]
    result = terminal_effect_result(base, prior, event, classification="LATE_MATCHED", disposition="OUTCOME_RETAINED",
        reason_codes=["DEPENDENCY_DISPUTED", "LATE_EFFECT"] if blocked else ["LATE_EFFECT"],
        occurrence_status="BLOCKED_DISPUTE" if blocked else None, disputed=False,
        complete_disposition=None if blocked else "SUCCEEDED", budget_results=[registry])
    return event, retained(result, prior["permit"]), registry


def cdmo_completion_clock(base, prior):
    clock = available_clock(base["authority_input"]["clock"]["source"], "3", "2026-10-06T12:11:01Z")
    event = {"schema": SCHEMA + "runtime-event", "kind": "CLOCK", "event_id": "cdmo-clock-3", "instance_id": prior["state"]["instance_id"],
        "expected_state_revision": prior["state"]["revision"], "expected_state_digest": state_digest(prior["state"]), "clock": clock, "activation_clocks": []}
    def mutate(state):
        state["clocks"].append(copy.deepcopy(clock))
    result = admitted_transition(prior["state"], event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": "3", "status": "AVAILABLE"}], mutate=mutate)
    return event, retained(result, prior["permit"])


def cdmo_trace(*, leaf_options=None, correction_options=None):
    base = cdmo_base(leaf_options=leaf_options, correction_options=correction_options)
    permitted = cdmo_permitted(base)
    authorization_event, authorized = cdmo_authorized(base, permitted)
    dispatch, dispatched = cdmo_dispatched(base, authorized)
    completion_clock_event, completion_ready = cdmo_completion_clock(base, dispatched)
    completion_event, completed, registry = cdmo_completed(base, completion_ready)
    return {"base": base, "permitted": permitted, "authorization_event": authorization_event, "authorized": authorized,
        "dispatch_event": dispatch, "dispatched": dispatched, "completion_clock_event": completion_clock_event,
        "completion_ready": completion_ready, "completion_event": completion_event, "completed": completed, "settled_registry": registry}


def correction_context(*, reuse_issue=False, reuse_dossier_revision=False, reuse_dossier_digest=False):
    business = business_fields(dossier_revision="7" if reuse_dossier_revision else "8", cedar_issue="CV-APPROVAL-026-R3" if reuse_issue else "CV-APPROVAL-026-CORR-R4", alder_issue="ATR-ASSENT-026-R3" if reuse_issue else "ATR-ASSENT-026-CORR-R4")
    if reuse_dossier_digest:
        business["dossier_digest"] = business_fields()["dossier_digest"]
    leaves = {party: decision_leaf(party, business, now="2026-10-06T12:30:00Z", signed="2026-10-06T12:20:00Z",
        signer_until="2026-10-06T12:25:00Z", revision="4") for party in ["alder", "cedar"]}
    requirements, facts, decisions = outer_requirements(business, leaves)
    for row in [*requirements, *decisions]:
        row["step"] = "source-correction"
    return business, leaves, requirements, facts, decisions


def correction_policy(**options):
    business, _, _, _, decisions = correction_context(**options)
    return {"kind": "INDEPENDENT_HUMAN_DECISIONS", "custodian_role": "inventory-records-custodian", "issuer_role": "head-of-quality",
        "correction_provider": PROVIDER, "correction_source": "inventory-corrections", "correction_record_type": "linked-inventory-correction",
        "custodian_identity_source": "role-occupancy", "original_id_field": "original_record_identity",
        "original_digest_field": "original_record_digest", "original_revision_field": "original_revision",
        "changes_digest_field": "changes_digest", "result_digest_field": "corrected_result_digest",
        "business_result_fields": sorted(["previous_inventory_revision" if name == "expected_inventory_revision" else name for name in business] + ["resulting_inventory_revision"]),
        "provider_link_bindings": [], "business_decision_requirements": decisions,
        "business_context_bindings": sorted([{"proposal_field": name, "value": {"kind": "CORRECTED_FIELD",
            "field": "previous_inventory_revision" if name == "expected_inventory_revision" else name}} for name in sorted(business)] +
            [{"proposal_field": "correction_principal", "value": {"kind": "LITERAL", "value": typed(CEDAR)}}], key=lambda row: row["proposal_field"]),
        "fresh_result_fields": ["dossier_digest", "dossier_revision"]}


def seal_correction(record):
    record["provenance_digest"] = digest("source-correction-provenance", {key: value for key, value in record.items() if key != "provenance_digest"})
    return record


def cdmo_correction(trace, *, business_change=True):
    base, original_permit, original = trace["base"], trace["permitted"]["permit"], trace["completion_event"]["native_evidence"]
    corrected = {row["name"]: copy.deepcopy(row["value"]) for row in original["actual_fields"]}
    business, leaves, requirements, facts, decisions = correction_context(**base.get("correction_options", {}))
    if business_change:
        for name in ["dossier_digest", "dossier_revision", "cedar_approval_identity", "customer_assent_identity"]:
            corrected[name] = copy.deepcopy(business[name])
    else:
        business = {name: copy.deepcopy(corrected["previous_inventory_revision" if name == "expected_inventory_revision" else name]) for name in business}
        corrected["event_time"] = typed("2026-10-06T12:11:02Z", "INSTANT")
        leaves, requirements, facts, decisions = {}, [], {}, []
    originals = {row["name"]: row["value"] for row in original["actual_fields"]}
    changes = [{"field": name, "old_value": originals[name], "new_value": value} for name, value in sorted(corrected.items()) if value != originals[name]]
    corrected_fields = fields(corrected)
    identity = {name: original[name] for name in ["provider", "source", "record_type", "provider_record_id"]}
    values = {**business, "correction_principal": typed(CEDAR), **{name: typed(value) for name, value in {
        "original_record_identity": canonical_bytes(identity).decode(), "original_record_digest": original["record_digest"],
        "original_revision": original["provider_revision"], "changes_digest": digest("source-correction-changes", changes),
        "corrected_result_digest": digest("source-correction-result", corrected_fields)}.items()}}
    step = operation_projection("source-correction", values, "inventory-records-custodian")
    step["scope_fields"] = {"subjects": ["correction_principal", "customer_id"], "resources": ["batch_id", "original_record_identity", "site_id"]}
    work = {"schema": SCHEMA + "authority-work-class", "id": "cedar-inventory-source-correction", "revision": "revision-3",
        "types": copy.deepcopy(TYPES), "steps": [step]}
    for row in requirements:
        if row["id"].startswith("executor-current-"):
            facts[row["id"]]["actor"] = typed("inventory-custodian-01")
            next(relation for relation in row["relations"] if relation["id"] == "actor")["right"]["value"] = typed("inventory-custodian-01")
    authority = base_authority(work, values, principal=CEDAR, role="inventory-records-custodian", actor="inventory-custodian-01",
        now="2026-10-06T12:30:00Z", signed="2026-10-06T12:29:00Z", decider=("cedar-quality-head-01", "head-of-quality"),
        issue="CV-CORRECTION-AUTH-026-R1", decision_requirements=decisions, source_requirements=requirements, source_values=facts,
        decision_bases=[{"requirement_id": party + "-decision", "evidence": leaves[party][0]} for party in ["alder", "cedar"]] if business_change else [],
        instance="CV-CORRECTION-026", occurrence="CV-CORRECTION-026-occurrence")
    result = expected_authority(authority)
    custodian = copy.deepcopy(authority["proposal"]["executor"])
    occupancy = next(row for row in authority["occupancies"] if row["id"] == custodian["occupancy"])
    returned = {"provider": occupancy["provider"], "source": "role-occupancy", "occupancy_digest": digest("authority-occupancy", occupancy),
        "actor": custodian["actor"], "role": custodian["role"], "at": authority["clock"]["instant"], "evidence_ref": "current-custodian-role-return"}
    returned["provenance_digest"] = digest("source-correction-custodian-provenance", returned)
    decision = next(row for row in authority["acts"] if row["kind"] == "INSTANCE_DECISION")
    correction = seal_correction({"schema": SCHEMA + "source-correction-record", "evidence_id": "CV-CORRECTION-EVENT-026",
        "provider": PROVIDER, "source": "inventory-corrections", "record_type": "linked-inventory-correction",
        "original_provider_record_id": original["provider_record_id"], "original_record_digest": original["record_digest"],
        "expected_revision": original["provider_revision"], "custodian": custodian, "custodian_return": returned,
        "changes": changes, "corrected_fields": corrected_fields, "correction_authority_input": authority,
        "correction_authorization_digest": digest("authority-act", decision), "decision_policy": "INDEPENDENT_HUMAN_DECISIONS",
        "event_time": authority["clock"]["instant"], "observed_at": authority["clock"]["instant"], "evidence_ref": "linked-correction-entry-026"})
    supplied = {"profile": "LINEAR", "role": "REVIEW_EVIDENCE", "specification_pin": PIN, "definition": base["definition"],
        "definition_digest": base["definition_digest"], "original_permit": original_permit, "original_record": original, "correction": correction}
    expected = {"status": "EVIDENCE_VALID", "profile": "LINEAR", "role": "REVIEW_EVIDENCE", "specification_pin": PIN,
        "kind": "SOURCE_CORRECTION", "definition_digest": base["definition_digest"], "original_record_identity": identity,
        "original_record_digest": original["record_digest"], "correction_digest": digest("source-correction", correction),
        "correction_authority_result": result, "correction_authority_result_digest": digest("authority-result", result),
        "decision_policy": "INDEPENDENT_HUMAN_DECISIONS", "changes_digest": digest("source-correction-changes", changes),
        "result_digest": digest("source-correction-result", corrected_fields)}
    return supplied, expected
