"""Fixed source-selected assessment facts and complete expected records, without consumers.

The positive inventory applies chosen source facts. Refusal judgments are explicit.
Canonical bytes/digests come only from review-side corpus_common. No evaluator,
consumer schema, adapter or observed output is imported.
"""
from __future__ import annotations
import base64
import copy
import hashlib
import re
from pathlib import Path
from corpus_common import candidate_pin, canonical_bytes, digest
from equipment_observation_fixture import observation, requirement, source_query
from equipment_completion_fixture import terminal_effect_result
from equipment_dispatch_fixture import retained
from fixture_factory import add_seconds, available_clock, deployment, occurrence, readback_paths, structural_step
from lifecycle_factory import admitted_transition, dispatch_event, dispatch_result, governed_effect_event, governed_native_evidence, permitted_proposal, replay_result, state_digest, stateful_refusal, step_input
from authority_fixture import authority_refusal
from checkpoint_reseal import reseal_last_transition

SCHEMA = "seampoint.work-class/1.0.0-draft.3/"
PIN = candidate_pin()
HERE = Path(__file__).resolve().parent
SOURCE_PATH = HERE / "fixtures/factual-customer-message-review-revision1-source.md"
SOURCE_ID = "factual-customer-message-review-revision1-source"
PRINCIPAL = "MRB-US-01"
NOW = "2026-10-08T10:00:00Z"
SIGNED = "2026-10-08T09:59:00Z"
ASSESSED = "2026-10-08T09:58:00Z"
END = "2026-10-09T10:00:00Z"
OCCUPANCY_END = "2026-10-08T09:59:30Z"
VALID = {"valid_from":"2026-09-01T00:00:00Z","valid_until":"2026-11-01T00:00:00Z"}
STEP = "send-customer-message"
DECISION = "customer-message-review"
ASSESSMENT = "customer-message-assessment"
APPROVAL = "human-approval"
REVIEW_ID = "CM-REVIEW-074-01"
EVALUATOR = {"provider":"assessment-provider.invalid","model":"synthetic-content-review-model","version":"revision-1"}
TYPES = [{"id":name,"kind":kind,"nonnegative":nonnegative,"unit":unit} for name,kind,nonnegative,unit in [
 ("AMOUNT","DECIMAL",True,"USD"),("BOOLEAN","BOOLEAN",False,None),("COUNT","DECIMAL",True,"count"),
 ("DATE","STRING",False,None),("IDENTITY","IDENTITY",False,None),("INSTANT","INSTANT",False,None),
 ("REVISION","STRING",False,None),("STRING","STRING",False,None)]]
CRITERIA = ["grounded-factual-request","neutral-tone","no-invented-account-restriction","no-prosecution-threat","no-sar-implication"]

def typed(value, type_ref="IDENTITY"):
    return {"type_ref":type_ref,"value":value}

def fields(values):
    return [{"name":name,"value":copy.deepcopy(value)} for name,value in sorted(values.items())]

def normalized_obligations():
    paragraphs=[]; heading="preface"; current=[]
    def emit():
        if current:
            text=" ".join(current); paragraphs.append({"heading":heading,"text":text});current.clear()
    for line in SOURCE_PATH.read_text().splitlines():
        if line.startswith("#"):
            emit();heading=line.lstrip("# ")
        elif not line.strip(): emit()
        elif line.startswith("|"):
            emit()
            cells=[c.strip() for c in line.strip().strip("|").split("|")]
            if cells[0] in {"Criterion","Writer class"} or all(set(c)<=set("-: ") for c in cells):continue
            paragraphs.append({"heading":heading,"text":" | ".join(cells),"criterion":cells[0].strip("`") if cells[0].strip("`") in CRITERIA else None})
        else:current.append(line)
    emit()
    rows=[]
    for i,row in enumerate(paragraphs,1):
        record={"id":"CM-OBL-"+str(i).zfill(3),"text":row["text"],"heading":row["heading"]}
        if row.get("criterion"):record["criterion"]=row["criterion"]
        rows.append(record)
    return {"source_id":SOURCE_ID,"source_revision":"revision-1","source_raw_sha256":"sha256:"+hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest(),"obligations":rows}

def source_obligations():
    return [{"id":r["id"],"text":r["text"]} for r in normalized_obligations()["obligations"]]

def native_values():
    return {"recipient":typed("customer-074"),"destination":typed("https://portal.maple-research.invalid/customers/customer-074/messages","STRING"),
      "subject":typed("Request for transfer information","STRING"),
      "body":typed("Please provide invoices and explain the business purpose of the three outgoing USD transfers dated September 8, September 10, and September 12, 2026, totaling USD 84,000.00.","STRING"),
      "attachment_count":typed("0","COUNT"),"message_id":typed("MRB-MESSAGE-074-01")}

def fact_values():
    v={"bank_id":typed(PRINCIPAL),"customer_id":typed("customer-074"),"direction":typed("OUTGOING","STRING"),
       "currency":typed("USD","STRING"),"aggregate_usd_amount":typed("84000","AMOUNT")}
    for i,(rid,date) in enumerate([("MRB-TXN-081","2026-09-08"),("MRB-TXN-082","2026-09-10"),("MRB-TXN-083","2026-09-12")],1):
        v.update({f"transfer_{i}_id":typed(rid),f"transfer_{i}_revision":typed("1","REVISION"),f"transfer_{i}_date":typed(date,"DATE")})
    return v

def criterion(step):
    return {"id":"zero-attachments","step":step,"predicate":{"kind":"EQUAL","left":{"kind":"FIELD","name":"attachment_count"},"right":{"kind":"LITERAL","value":typed("0","COUNT")}}}

def operation_projection(values, *, leaf=False):
    return {"id":"review-customer-message" if leaf else STEP,"operation":"review-customer-message" if leaf else STEP,
      "interface":"human-message-decisions" if leaf else "synthetic-customer-portal","executor_role":"customer-communication-reviewer" if leaf else "customer-message-agent",
      "fields":[{"name":r["name"],"type_ref":r["value"]["type_ref"]} for r in fields(values)],
      "scope_fields":{"subjects":["recipient"],"resources":["message_id"]},"required_credentials":[] if leaf else ["message-authenticated-session"],
      "quantity_mode":"NONE","exclusive_keys":[]}

def base_authority(work, values, *, principal, role, actor, now=NOW, leaf=False, issue=None, gate_requirement=None,
                   decision_requirements=None, source_requirements=None, source_values=None, decision_bases=None,
                   instance="cdmo-instance-1", occurrence="cdmo-occurrence-1", signed=SIGNED, signer_until=OCCUPANCY_END, decider=None, capacity_until=None, source_padding=0):
    """Construct exact positive records from an explicit one-way dependency graph."""
    step = work["steps"][0]
    prefix = "component"
    provider = prefix + "-identity-provider.invalid"
    source = {"schema": SCHEMA + "authority-source", "id": SOURCE_ID, "revision": "revision-1",
        "obligations": source_obligations()}
    if source_padding:
        source["obligations"][0]["text"] += "x" * source_padding
    bindings = [{"id": name + "-binding", "step": step["id"], "field": name, "type_ref": values[name]["type_ref"]}
                for name in sorted(set(step["scope_fields"]["subjects"] + step["scope_fields"]["resources"]))]
    gate = {"materiality": "HIGH", "reversibility": "LOW", "kind": "DECIDE", "role": decider[1] if decider else role if leaf else "customer-communication-reviewer",
        "criteria": [criterion(step["id"])]}
    if gate_requirement:
        gate["decision_requirement"] = gate_requirement
    revocation = {"provider": provider, "source": "authority-revocations", "max_age_seconds": "0"}
    envelope = {"schema": SCHEMA + "authority-envelope", "id": work["id"] + "-envelope", "principal": principal,
        "grant_ref": work["id"] + "-grant", "grantor_role": "component-policy-owner",
        "attester_role": prefix + "-quality-attester", "executor_role": role, "clock_source": prefix + "-component-clock",
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
    persons = [("grantor", prefix + "-policy-owner-01", envelope["grantor_role"]),
        ("attester", prefix + "-policy-attester-01", envelope["attester_role"]), ("executor", actor, role)]
    if decider:
        persons.append(("decider", decider[0], decider[1]))
    occupancies = [{"id": work["id"] + "-occupancy-" + suffix, "actor": person, "role": selected_role, "principal": principal,
        "kind": "HUMAN" if leaf or suffix != "executor" or actor != "customer-message-agent-01" else "MACHINE", "provider": provider,
        "validity": {**VALID, "valid_until": signer_until} if leaf and suffix == "executor" else copy.deepcopy(VALID),
        "evidence_ref": "host-selected-" + work["id"] + "-" + suffix} for suffix, person, selected_role in persons]
    root = {"schema": SCHEMA + "authority-root", "id": work["id"] + "-root", "revision": "1", "designator": prefix + "-policy-designator",
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
            "occupancy": person["id"], "capacity": work["id"] + "-capacity-" + suffix, "recorder": prefix + "-policy-recorder",
            "occurred_at": signed, "disposition": "ACCEPT", "subject_digest": subject, "attested_actor": attested,
            "criteria": criteria or []}
    grant = act(envelope["grant_ref"], "GRANT", "grantor", envelope_digest)
    acts = [grant, act(work["id"] + "-grant-attestation", "ORGANISATIONAL_ATTESTATION", "attester",
        digest("authority-act", grant), attested=grant["actor"])]
    if leaf or decider:
        decision = act(issue, "INSTANCE_DECISION", "executor" if leaf else "decider", operation_digest, criteria=["zero-attachments"])
        acts += [decision, act(work["id"] + "-decision-attestation", "ORGANISATIONAL_ATTESTATION", "attester",
            digest("authority-act", decision), attested=decision["actor"])]
    returns = [{"id": "return-" + row["id"], "actor": row["actor"], "provider": provider, "channel": root["channels"][0]["id"],
        "act_digest": digest("authority-act", row), "act_bytes_base64": base64.b64encode(canonical_bytes(row)).decode(),
        "returned_at": signed, "evidence_ref": "host-returned-" + row["id"]} for row in acts]
    credentials = [] if leaf else [{"id": "component-executor-session-1", "actor": actor, "occupancy": proposal["executor"]["occupancy"],
        "step": step["id"], "interface": step["interface"], "operation": step["operation"], "kind": "message-authenticated-session",
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
            revision=req["id"] + "-revision-1"))
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
            add("GATE_CRITERION", subject, "zero-attachments", selected["occurred_at"])
    for row in supplied.get("assessment_bases", []):
        add("ASSESSMENT", digest("content-assessment", row["assessment"]), row["requirement_id"])
    evidence = {key: supplied[key] for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock"]}
    for key in ["evaluation_point", "decision_bases", "assessment_bases"]:
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


def rubric():
    selected = [r for r in normalized_obligations()["obligations"] if "criterion" in r]
    return {"id": "CM-MESSAGE-RULES-01", "revision": "revision-1",
        "obligations": sorted([{"id": r["id"], "text": r["text"]} for r in selected], key=lambda r: r["id"]),
        "criteria": sorted([{"id": r["criterion"], "obligation_ids": [r["id"]],
            "citation_policy": "CONTEXT" if r["criterion"] == "grounded-factual-request" else "PROPOSAL"}
            for r in selected], key=lambda r: r["id"])}


def declaration():
    return {"id": ASSESSMENT, "step": STEP, "review_decision_requirement_id": DECISION,
        "rubric": rubric(), "evaluator": copy.deepcopy(EVALUATOR), "sources": {
            "content": "current-message-content", "context": ["customer-facts"],
            "context_selection": {"requirement_id": "current-context", "digest_field": "context_digest"},
            "rubric": {"requirement_id": "current-rubric", "digest_field": "rubric_digest"},
            "evaluator": {"requirement_id": "current-evaluator", "provider_field": "provider", "model_field": "model", "version_field": "version"},
            "assessment": {"requirement_id": "immutable-assessment", "digest_field": "assessment_digest"},
            "selection": {"requirement_id": "current-assessment-selection", "identity_field": "assessment_identity", "digest_field": "assessment_digest"},
            "effectiveness": {"requirement_id": "assessment-effectiveness", "identity_field": "assessment_identity", "effective_field": "effective"},
            "blockers": ["approval-withdrawal", "contact-authority", "current-human-authority", "message-governance-coordinator"]}}


def source_coordinates(req_id):
    if req_id == "customer-facts":
        return {"provider": "customer-facts-provider.invalid", "source": "component-customer-facts", "record_type": "CUSTOMER_FACTS"}
    if req_id == APPROVAL:
        return {"provider": "human-review-provider.invalid", "source": "component-human-approval", "record_type": "CUSTOMER_MESSAGE_APPROVAL"}
    if req_id == "immutable-assessment":
        return {"provider": EVALUATOR["provider"], "source": "component-assessments", "record_type": "CONTENT_ASSESSMENT"}
    if req_id == "contact-authority":
        return {"provider": "customer-directory-provider.invalid", "source": "component-contact-authority", "record_type": "CONTACT_AUTHORITY"}
    return {"provider": "message-governance-provider.invalid", "source": "component-" + req_id, "record_type": "GOVERNANCE_RECORD"}


def issuance_identity(coords, record_id):
    return canonical_bytes({**coords, "provider_record_id": record_id}).decode()


def local_bodies(work, proposal, *, model=None, human=None, escalated=None,
                 decision="APPROVE", assessment_id="CM-ASSESSMENT-074-01", review_id=REVIEW_ID,
                 assessed_at=ASSESSED, explanations=None):
    snapshot = {"requirement_id": "customer-facts", "provider_record_id": "CM-FACTS-074-01",
        "provider_revision": "revision-1", "fields": fields(fact_values())}
    context_body = {"types": copy.deepcopy(work["types"]), "records": [{
        "requirement_id": "customer-facts", **source_coordinates("customer-facts"),
        **{k: copy.deepcopy(snapshot[k]) for k in ["provider_record_id", "provider_revision", "fields"]}}]}
    context_digest = digest("content-assessment-context", context_body)
    rubric_digest = digest("content-assessment-rubric", rubric())
    subject_body = {"principal": proposal["executor"]["principal"],
        **{k: copy.deepcopy(proposal[k]) for k in ["work_class_digest", "instance", "occurrence", "step", "interface", "operation", "fields"]},
        "context_digest": context_digest, "rubric_digest": rubric_digest, "evaluator": copy.deepcopy(EVALUATOR)}
    model, human, escalated = model or {}, human or {}, set(escalated or [])
    criteria, dispositions = [], []
    for name in CRITERIA:
        verdict, conclusion = model.get(name, "PASS"), human.get(name, "SATISFIED")
        citations = [{"kind": "CONTEXT_FIELD", "requirement_id": "customer-facts", "field": f} for f in [
            "aggregate_usd_amount", "transfer_1_date", "transfer_2_date", "transfer_3_date"]] if name == "grounded-factual-request" else [{"kind": "PROPOSAL_FIELD", "field": "body"}]
        criteria.append({"id": name, "verdict": verdict, "explanation": (explanations or {}).get(name, "Synthetic criterion judgment against the exact selected content and evidence."),
            "escalation": {"required": name in escalated, "reason": "Review this criterion explicitly." if name in escalated else None},
            "citations": sorted(citations, key=canonical_bytes)})
        adverse = verdict != "PASS" or name in escalated or conclusion != "SATISFIED"
        dispositions.append({"id": name, "disposition": conclusion,
            "reason": "The reviewer evaluated this exact criterion and records the stated conclusion without a waiver." if adverse else None,
            "citations": []})
    assessment = {**source_coordinates("immutable-assessment"), "id": assessment_id, "revision": "revision-1",
        "subject_digest": digest("content-assessment-subject", subject_body), "context_digest": context_digest,
        "rubric_digest": rubric_digest, "evaluator": copy.deepcopy(EVALUATOR), "assessed_at": assessed_at, "criteria": criteria}
    review = {"id": review_id, "assessment_digest": digest("content-assessment", assessment), "decision": decision, "criteria": dispositions}
    return {"requirement_id": ASSESSMENT, "supporting_context": [snapshot], "assessment": assessment, "review": review}


def human_leaf(native, basis, *, now=NOW, signed=SIGNED):
    values = copy.deepcopy(native)
    values.update(subject_digest=typed(basis["assessment"]["subject_digest"]),
        assessment_digest=typed(digest("content-assessment", basis["assessment"])),
        review_digest=typed(digest("content-assessment-review", basis["review"])),
        review_identity=typed(issuance_identity(source_coordinates(APPROVAL), basis["review"]["id"])),
        effective_from=typed(signed, "INSTANT"), effective_until=typed(END, "INSTANT"))
    work = {"schema": SCHEMA + "authority-work-class", "id": "component-human-message-review", "revision": "revision-1",
        "types": copy.deepcopy(TYPES), "steps": [operation_projection(values, leaf=True)], "authority_profile": "EVIDENCE_ONLY"}
    supplied = base_authority(work, values, principal=PRINCIPAL, role="customer-communication-reviewer", actor="customer-reviewer-01",
        leaf=True, issue=basis["review"]["id"], signed=signed, now=now)
    result = expected_authority(supplied, leaf=True)
    return {"schema": SCHEMA + "human-decision-evidence", "authority_input": supplied,
        "decision_act_digest": result["decision_act_digest"]}, result


def reliance_subject(evidence):
    supplied = evidence["authority_input"]
    return digest("human-decision-reliance-subjects", {"root_digest": digest("authority-root", supplied["host_selection"]["root"]),
        "envelope_digest": digest("authority-envelope", supplied["envelope"]),
        "capacities": [{"id": r["id"], "capacity_digest": digest("authority-capacity", r)} for r in supplied["capacities"]]})


def current_requirements(native, basis, human):
    declarations, values = [], {}
    def obs(req_id, field):
        return {"kind": "OBSERVATION_FIELD", "requirement_id": req_id, "field": field}
    def eq(req_id, field, right):
        return {"id": field, "kind": "EQUALS", "left": obs(req_id, field), "right": right}
    def literal(value):
        return {"kind": "LITERAL", "value": value}
    def add(req_id, data, *, relations=None, status="AVAILABLE", record_id="AUTO"):
        req = requirement(req_id, step=STEP, purpose="AUTHORITY", **source_coordinates(req_id),
            subject={"kind": "PROPOSAL_FIELD", "field": "message_id"},
            record_id=(req_id + "-record" if record_id == "AUTO" else record_id) if status == "AVAILABLE" else None,
            expected_status=status, fields=[{"name": r["name"], "type_ref": r["value"]["type_ref"]} for r in fields(data)],
            relations=sorted(relations or [], key=lambda r: r["id"]))
        declarations.append(req); values[req_id] = copy.deepcopy(data)
        return req
    add("current-message-content", native, relations=[eq("current-message-content", name, {"kind": "PROPOSAL_FIELD", "field": name}) for name in native])
    add("customer-facts", fact_values(), record_id="CM-FACTS-074-01")
    add("current-context", {"context_digest": typed(basis["assessment"]["context_digest"])})
    add("current-rubric", {"rubric_digest": typed(basis["assessment"]["rubric_digest"])})
    add("current-evaluator", {k: typed(v) for k, v in EVALUATOR.items()})
    assess_digest = digest("content-assessment", basis["assessment"])
    identity = issuance_identity(source_coordinates("immutable-assessment"), basis["assessment"]["id"])
    derived = {"kind": "DECISION_FIELD", "requirement_id": DECISION, "field": "assessment_digest"}
    add("immutable-assessment", {"assessment_digest": typed(assess_digest)},
        relations=[eq("immutable-assessment", "assessment_digest", derived)], record_id=basis["assessment"]["id"])
    add("current-assessment-selection", {"assessment_digest": typed(assess_digest), "assessment_identity": typed(identity)},
        relations=[eq("current-assessment-selection", "assessment_digest", derived)])
    add("assessment-effectiveness", {"assessment_identity": typed(identity), "effective": typed(True, "BOOLEAN")})
    leaf = human["authority_input"]
    decision_act = next(r for r in leaf["acts"] if r["kind"] == "INSTANCE_DECISION")
    approval_values = {r["name"]: copy.deepcopy(r["value"]) for r in leaf["proposal"]["fields"]}
    relations = [{"id": "issue-id", "kind": "EQUALS", "left": {"kind": "OBSERVATION_ID", "requirement_id": APPROVAL, "type_ref": "IDENTITY"},
        "right": {"kind": "DECISION_ACT", "requirement_id": DECISION, "member": "id", "type_ref": "IDENTITY"}}]
    for member in ["digest", "actor", "role", "principal", "occurred_at"]:
        name = "act-" + member
        approval_values[name] = typed(human["decision_act_digest"] if member == "digest" else decision_act[member], "INSTANT" if member == "occurred_at" else "IDENTITY")
        relations.append(eq(APPROVAL, name, {"kind": "DECISION_ACT", "requirement_id": DECISION, "member": member, "type_ref": approval_values[name]["type_ref"]}))
    for name in sorted(r["name"] for r in leaf["proposal"]["fields"]):
        relations.append(eq(APPROVAL, name, {"kind": "DECISION_FIELD", "requirement_id": DECISION, "field": name}))
    add(APPROVAL, approval_values, relations=relations, record_id=None)
    add("approval-withdrawal", {}, status="ABSENT")
    add("contact-authority", {"principal": typed(PRINCIPAL), "recipient": native["recipient"], "destination": native["destination"],
        "purpose": typed("REQUEST_TRANSFER_FACTS"), "authorized": typed(True, "BOOLEAN")}, relations=[
            eq("contact-authority", name, {"kind": "PROPOSAL_FIELD", "field": name}) for name in ["recipient", "destination"]] + [
            eq("contact-authority", "principal", literal(typed(PRINCIPAL))),
            eq("contact-authority", "purpose", literal(typed("REQUEST_TRANSFER_FACTS"))),
            eq("contact-authority", "authorized", literal(typed(True, "BOOLEAN")))])
    add("current-human-authority", {"basis_digest": typed(reliance_subject(human)), "no_applicable_revocation": typed(True, "BOOLEAN")}, relations=[
        eq("current-human-authority", "basis_digest", {"kind": "DECISION_BASIS", "requirement_id": DECISION, "type_ref": "IDENTITY"}),
        eq("current-human-authority", "no_applicable_revocation", literal(typed(True, "BOOLEAN")))])
    add("message-governance-coordinator", {"complete_writer_coverage": typed(True, "BOOLEAN")}, relations=[
        eq("message-governance-coordinator", "complete_writer_coverage", literal(typed(True, "BOOLEAN")))])
    bindings = []
    derived_members = {"subject_digest": "SUBJECT_DIGEST", "assessment_digest": "ASSESSMENT_DIGEST", "review_digest": "REVIEW_DIGEST", "review_identity": "REVIEW_IDENTITY"}
    for row in leaf["proposal"]["fields"]:
        name = row["name"]
        value = {"kind": "ASSESSMENT", "requirement_id": ASSESSMENT, "member": derived_members[name], "type_ref": "IDENTITY"} if name in derived_members else (
            {"kind": "PROPOSAL_FIELD", "field": name} if name in native else {"kind": "LITERAL", "value": copy.deepcopy(row["value"])})
        bindings.append({"field": name, "value": value})
    human_requirement = {"id": DECISION, "step": STEP, "principal": PRINCIPAL, "role": "customer-communication-reviewer",
        "work_class_digest": digest("authority-work-class", leaf["work_class"]), "envelope_digest": digest("authority-envelope", leaf["envelope"]),
        "record_requirement_id": APPROVAL, "identity_field": "review_identity",
        "validity_fields": {"not_before_field": "effective_from", "not_after_field": "effective_until"},
        "context_bindings": sorted(bindings, key=lambda r: r["field"]), "distinct_from": [{"kind": "EXECUTOR"}]}
    return sorted(declarations, key=lambda r: r["id"]), values, human_requirement


def completion_carrier(native):
    return {"terminal_policy": "STOP_RETAIN", "effect_provider": "synthetic-portal-provider.invalid", "effect_source": "component-message-sink",
        "effect_record_type": "CUSTOMER_MESSAGE_ACCEPTANCE", "no_effect_provider": "synthetic-portal-provider.invalid", "no_effect_source": "component-message-sink",
        "no_effect_record_type": "CUSTOMER_MESSAGE_NO_EFFECT", "status_field": "status", "status_type_ref": "STRING",
        "success_values": [typed("ACCEPTED", "STRING")], "failure_values": [], "route_label_field": None, "route_label_type_ref": None,
        "evidence_bindings": [{"request_field": name, "evidence_field": name} for name in sorted(native)],
        "provider_record_identity": {"field": "provider_event_id", "type_ref": "IDENTITY"},
        "event_time_identity": {"field": "provider_event_time", "type_ref": "INSTANT"}, "additional_fields": [],
        "lookup": {"provider": "synthetic-portal-provider.invalid", "source": "component-message-sink", "record_type": "CUSTOMER_MESSAGE_ACCEPTANCE",
            "namespace": "synthetic-message-acceptance", "key_projection": [{"field": "message_id", "type_ref": "IDENTITY"}]}}


def authority(*, now=NOW, instance="component-message-instance-1", occurrence="component-message-occurrence-1", native=None, **body_options):
    native = native_values() if native is None else copy.deepcopy(native)
    step = operation_projection(native)
    step["authority_type_refs"] = sorted(r["id"] for r in TYPES)
    step["completion"] = completion_carrier(native)
    source_ids = sorted(["current-message-content", "customer-facts", "current-context", "current-rubric", "current-evaluator", "immutable-assessment",
        "current-assessment-selection", "assessment-effectiveness", APPROVAL, "approval-withdrawal", "contact-authority", "current-human-authority", "message-governance-coordinator"])
    coordinator = source_coordinates("message-governance-coordinator")
    step["dispatch_gate"] = {"kind": "SOURCE_REQUIREMENTS", "requirements": source_ids, "coordinator_requirement": "message-governance-coordinator",
        "fence_provider": coordinator["provider"], "fence_source": coordinator["source"], "authorization_seconds": "60",
        "validity_requirements": [{"requirement_id": APPROVAL, "not_before_field": "effective_from", "not_after_field": "effective_until"}]}
    work = {"schema": SCHEMA + "authority-work-class", "id": "factual-customer-message-review", "revision": "revision-1", "types": copy.deepcopy(TYPES), "steps": [step]}
    proposal = {"executor": {"principal": PRINCIPAL}, "work_class_digest": digest("authority-work-class", work),
        "instance": instance, "occurrence": occurrence, "step": STEP, "interface": step["interface"], "operation": step["operation"], "fields": fields(native)}
    basis = local_bodies(work, proposal, **body_options)
    human, human_result = human_leaf(native, basis, now=now)
    requirements, source_values, human_requirement = current_requirements(native, basis, human)
    supplied = base_authority(work, native, principal=PRINCIPAL, role="customer-message-agent", actor="customer-message-agent-01", now=now,
        gate_requirement=DECISION, decision_requirements=[human_requirement], source_requirements=requirements, source_values=source_values,
        decision_bases=[{"requirement_id": DECISION, "evidence": human}], instance=instance, occurrence=occurrence)
    supplied["envelope"]["assessment_requirements"] = [declaration()]
    supplied["assessment_bases"] = [basis]
    # The new declaration changes envelope/root/act commitments, never the earlier work subject.
    rebind_outer(supplied)
    for row in supplied["observations"]:
        if row["query"].get("requirement_id") == "customer-facts":
            row["revision"] = "revision-1"
        if row["query"].get("requirement_id") == "immutable-assessment":
            row["revision"] = basis["assessment"]["revision"]
        if row["query"].get("requirement_id") == APPROVAL:
            row["provider_record_id"] = basis["review"]["id"]
    supplied["observations"].sort(key=lambda r: digest("authority-observation", r))
    return supplied, expected_authority(supplied), {"native": native, "basis": basis, "human": human, "source_values": source_values}


def rebind_outer(supplied):
    """Reissue chosen outer authorization after declaration mutations, without policy evaluation."""
    envelope, work, source, proposal = (supplied[k] for k in ["envelope", "work_class", "source", "proposal"])
    old_env = digest("authority-envelope", envelope)
    envelope["source_digest"] = digest("authority-source", source)
    envelope["work_class_digest"] = digest("authority-work-class", work)
    proposal["work_class_digest"] = envelope["work_class_digest"]
    env_digest = digest("authority-envelope", envelope)
    root = supplied["host_selection"]["root"]
    old_root = digest("authority-root", root)
    root.update(source_digest=envelope["source_digest"], work_class_digest=envelope["work_class_digest"], envelope_digest=env_digest)
    root_digest = digest("authority-root", root)
    caps = {r["id"]: digest("authority-capacity", r) for r in supplied["capacities"]}
    for row in supplied["capacities"]:
        row.update(root_digest=root_digest, envelope_digest=env_digest)
    replacements = {old_root: root_digest, **{caps[r["id"]]: digest("authority-capacity", r) for r in supplied["capacities"]}}
    for row in supplied["acts"]:
        if row["kind"] == "GRANT":
            previous = digest("authority-act", row); row["subject_digest"] = env_digest
            replacements[previous] = digest("authority-act", row)
        elif row["kind"] == "INSTANCE_DECISION":
            previous = digest("authority-act", row)
            row["subject_digest"] = digest("authority-operation", {"envelope_digest": env_digest,
                "work_class_digest": envelope["work_class_digest"], "proposal_digest": digest("authority-proposal", proposal)})
            replacements[previous] = digest("authority-act", row)
    for row in supplied["acts"]:
        if row["kind"] == "ORGANISATIONAL_ATTESTATION" and row["subject_digest"] in replacements:
            row["subject_digest"] = replacements[row["subject_digest"]]
    for returned in supplied["returns"]:
        act = next(r for r in supplied["acts"] if returned["id"] == "return-" + r["id"])
        returned.update(act_digest=digest("authority-act", act), act_bytes_base64=base64.b64encode(canonical_bytes(act)).decode())
    replacements[old_env] = env_digest
    # The old root retains the previous envelope digest even when declaration mutation preceded this helper.
    for row in supplied["observations"]:
        if row["query"]["purpose"] == "REVOCATION":
            query = row["query"]
            if query["subject_digest"] in replacements:
                query["subject_digest"] = replacements[query["subject_digest"]]
            row["query_digest"] = digest("authority-query", query)
    env_queries = [r for r in supplied["observations"] if r["query"]["purpose"] == "REVOCATION" and r["query"]["at"] == supplied["clock"]["instant"]
        and r["query"]["subject_digest"] not in {root_digest, *[digest("authority-capacity", c) for c in supplied["capacities"]], *[digest("authority-credential", c) for c in supplied["credentials"]]}]
    for row in env_queries:
        row["query"]["subject_digest"] = env_digest; row["query_digest"] = digest("authority-query", row["query"])
    authenticated = []
    for collection, kind, domain in [(supplied["occupancies"], "OCCUPANCY", "authority-occupancy"), (supplied["capacities"], "CAPACITY", "authority-capacity"),
            (supplied["credentials"], "CREDENTIAL", "authority-credential"), (supplied["returns"], "RETURN", "authority-return")]:
        authenticated.extend({"kind": kind, "record_digest": digest(domain, row), "provider": row["provider"], "channel": row.get("channel")} for row in collection)
    supplied["host_selection"]["authenticated_records"] = sorted(authenticated, key=canonical_bytes)
    supplied["acts"].sort(key=lambda r: digest("authority-act", r))
    supplied["observations"].sort(key=lambda r: digest("authority-observation", r))


def policy_refusal(supplied, failures):
    """Build the explicit source-selected failed checks, without evaluating inputs."""
    failed = []
    for purpose, requirement_id, reason in failures:
        subject = digest("content-assessment", supplied["assessment_bases"][0]["assessment"]) if purpose == "ASSESSMENT" else digest("authority-envelope", supplied["envelope"])
        failed.append({"purpose": purpose, "subject_digest": subject, "requirement_ref": requirement_id, "at": supplied["clock"]["instant"], "reason": reason})
    result = authority_refusal(sorted(failed, key=canonical_bytes))
    if "decision_bases" in supplied:
        result["decision_results"] = expected_authority(supplied)["decision_results"]
    return result



def lifecycle_base(*, instance="component-message-instance-1", **body_options):
    supplied, result, facts = authority(instance=instance, **body_options)
    projected = supplied["work_class"]["steps"][0]
    step = {**copy.deepcopy(projected), "kind":"OPERATION", "authority_requirements":[supplied["envelope"]["id"]],
      "shared_budgets":[],"prior_effect_bindings":[],"prior_actor_separations":[],"permit_seconds":"300","failure_behavior":"STOP",
      "referral_policy":{"authority":[],"completion":[]}}
    definition={"schema":SCHEMA+"work-class-definition","specification_pin":PIN,"id":supplied["work_class"]["id"],"revision":"revision-1",
      "profile":"LINEAR","root":STEP,"participants":[{"id":"customer-message-agent-01","role":"customer-message-agent","kind":"AGENT"}],
      "objects":[],"types":copy.deepcopy(TYPES),"steps":[step,structural_step("terminal","TERMINAL")],
      "relationships":[{"kind":"SEQUENCE","from":STEP,"to":"terminal"}],"choices":[],"occurrence_limits":[{"step_id":STEP,"maximum":"1"}],
      "loops":[],"deadlines":[],"parallel_blocks":[],"fanouts":[],"shared_budgets":[],
      "limits":{"maximum_proposals":"64","maximum_activations":"64","maximum_actuations":"1","maximum_active_obligations":"64","maximum_fanout_objects":"64"},
      "source":{"id":SOURCE_ID,"revision":"revision-1","obligations":sorted(r["id"] for r in source_obligations())}}
    definition_digest=digest("work-class-definition",definition)
    root_occurrence=occurrence(definition_digest,instance,STEP)
    supplied,result,facts=authority(instance=instance,occurrence=root_occurrence["occurrence_id"],**body_options)
    paths,obligations=readback_paths(definition),definition["source"]["obligations"]
    synthetic_mappings=[{"source_obligation_id":obligation,"provision_paths":paths[i::len(obligations)]} for i,obligation in enumerate(obligations)]
    deploy_input,deploy_result=deployment(definition,instance_id=instance,organization_id=PRINCIPAL,
      authorization_time="2026-10-08T09:57:00Z",evidence_expires_at=END,correspondence_mappings=synthetic_mappings)
    clock=available_clock(supplied["clock"]["source"],"1",NOW)
    event={"schema":SCHEMA+"runtime-event","event_id":"assessment-clock-1","kind":"CLOCK","instance_id":instance,
      "expected_state_revision":deploy_result["state"]["revision"],"expected_state_digest":deploy_result["state_digest"],"clock":clock,"activation_clocks":[]}
    def record_clock(state):state["clocks"].append(copy.deepcopy(clock))
    clock_result=admitted_transition(deploy_result["state"],event,disposition="CLOCK_RECORDED",reason_codes=[],
      details=[{"kind":"CLOCK","source":clock["source"],"revision":"1","status":"AVAILABLE"}],mutate=record_clock)
    executor=supplied["proposal"]["executor"]
    proposal={"schema":SCHEMA+"runtime-event","kind":"PROPOSE","event_id":"assessment-propose-1","instance_id":instance,
      "expected_state_revision":clock_result["state"]["revision"],"expected_state_digest":clock_result["state_digest"],"occurrence":root_occurrence,
      "native_request":{k:copy.deepcopy(supplied["proposal"][k]) for k in ["interface","operation","fields"]},
      "executor":{"participant_id":executor["actor"],"role":executor["role"],"binding_digest":digest("executor-binding",executor)},
      "credential_ids":sorted(r["id"] for r in supplied["credentials"]),"authority_input":supplied,"budget_inputs":[],"clock_revision":"1",
      "observation_digests":sorted(digest("authority-observation",r) for r in supplied["observations"])}
    return {"definition":definition,"definition_digest":definition_digest,"deploy_input":deploy_input,"deploy_result":deploy_result,
      "clock_event":event,"clock_result":clock_result,"authority_input":supplied,"authority_result":result,"proposal_event":proposal,
      "native":facts["native"],"source_values":facts["source_values"],"permit_expires_at":add_seconds(NOW,"300")}


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


def source_fence(event, result):
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


def authorized(base, prior):
    instant = "2026-10-08T10:00:01Z"
    clock = available_clock(base["authority_input"]["clock"]["source"], "2", instant)
    clock_event = {"schema": SCHEMA + "runtime-event", "kind": "CLOCK", "event_id": "assessment-clock-2", "instance_id": prior["state"]["instance_id"],
        "expected_state_revision": prior["state"]["revision"], "expected_state_digest": state_digest(prior["state"]), "clock": clock, "activation_clocks": []}
    def record_clock(state):
        state["clocks"].append(copy.deepcopy(clock))
    clock_result = admitted_transition(prior["state"], clock_event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": "2", "status": "AVAILABLE"}], mutate=record_clock)
    base["dispatch_clock_event"], base["dispatch_clock_result"] = clock_event, clock_result
    prior = retained(clock_result, prior["permit"])
    current = refreshed(base["authority_input"], instant)
    result = expected_authority(current)
    body = {"id": "synthetic-message-connector", "version": "revision-1"}
    connector = {**body, "binding_digest": digest("connector-binding", body)}
    event = {"schema": SCHEMA + "runtime-event", "kind": "AUTHORIZE_DISPATCH", "event_id": "assessment-authorize-1", "instance_id": prior["state"]["instance_id"],
        "expected_state_revision": prior["state"]["revision"], "expected_state_digest": state_digest(prior["state"]), "permit": copy.deepcopy(prior["permit"]),
        "native_request": copy.deepcopy(prior["permit"]["native_request"]), "connector": connector, "authorization_fence": None, "authority_input": current,
        "dispatch_intent_id": "assessment-intent-1", "observation_digests": sorted(digest("authority-observation", row) for row in current["observations"]), "clock_revision": "2"}
    event["authorization_fence"], expires = source_fence(event, result)
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


def dispatched(base, prior, *, attempt_status="SENT", acknowledgement_status="NONE"):
    authorization = prior["state"]["authorizations"][-1]
    event = dispatch_event(base, prior, event_id="assessment-dispatch-1", attempt_status=attempt_status,
        acknowledgement_status=acknowledgement_status, attempted_at="2026-10-08T10:00:01Z", clock_revision="2", authorization_digest=authorization["authorization_digest"])
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




def completion_clock(base, prior):
    clock=available_clock(base["authority_input"]["clock"]["source"],"3","2026-10-08T10:00:02Z")
    event={"schema":SCHEMA+"runtime-event","kind":"CLOCK","event_id":"assessment-clock-3","instance_id":prior["state"]["instance_id"],
      "expected_state_revision":prior["state"]["revision"],"expected_state_digest":prior["state_digest"],"clock":clock,"activation_clocks":[]}
    def change(state):state["clocks"].append(copy.deepcopy(clock))
    result=admitted_transition(prior["state"],event,disposition="CLOCK_RECORDED",reason_codes=[],
      details=[{"kind":"CLOCK","source":clock["source"],"revision":"3","status":"AVAILABLE"}],mutate=change)
    return event,retained(result,prior["permit"])


def completed(base, prior):
    at="2026-10-08T10:00:02Z"
    provider_id="CM-SINK-EVENT-074-01"
    actual=copy.deepcopy(prior["permit"]["native_request"]["fields"])+fields({
      "provider_event_id":typed(provider_id),"provider_event_time":typed(at,"INSTANT"),"status":typed("ACCEPTED","STRING")})
    actual.sort(key=lambda r:r["name"])
    record=governed_native_evidence(base,prior,prior,evidence_id="assessment-sink-evidence-1",result_value="ACCEPTED",
      native_operation_id="synthetic-message-operation-1",event_time=at,observed_at=at,actual_fields=actual)
    record.update(provider="synthetic-portal-provider.invalid",source="component-message-sink",record_type="CUSTOMER_MESSAGE_ACCEPTANCE",
      provider_record_id=provider_id,provider_revision="revision-1")
    record["record_digest"]=digest("provider-native-record",{k:record[k] for k in ["provider","source","record_type","provider_record_id","provider_revision","actual_fields","event_time"]})
    event=governed_effect_event(prior,prior,record,event_id="assessment-effect-1",clock_revision=None)
    result=terminal_effect_result(base,prior,event,classification="MATCHED",disposition="COMPLETED",reason_codes=[],
      occurrence_status=None,disputed=False,complete_disposition="SUCCEEDED",route=True)
    return event,retained(result,prior["permit"])


def public_result(carrier):
    result=copy.deepcopy(carrier)
    if result.get("status")=="STEP" and result["decision"]["event_kind"]!="PROPOSE":result["permit"]=None
    return result


def trace():
    base=lifecycle_base()
    permit=permitted_proposal(base)
    authorization_event,authorization=authorized(base,permit)
    dispatch,dispatch_result=dispatched(base,authorization)
    clock3,completion_ready=completion_clock(base,dispatch_result)
    completion,completion_result=completed(base,completion_ready)
    stages=[("deploy",base["deploy_input"],base["deploy_result"]),
      ("step",step_input(base,base["deploy_result"]["state"],base["clock_event"]),base["clock_result"]),
      ("step",step_input(base,base["clock_result"]["state"],base["proposal_event"]),permit),
      ("step",step_input(base,permit["state"],base["dispatch_clock_event"]),base["dispatch_clock_result"]),
      ("step",step_input(base,base["dispatch_clock_result"]["state"],authorization_event),authorization),
      ("step",step_input(base,authorization["state"],dispatch),dispatch_result),
      ("step",step_input(base,dispatch_result["state"],clock3),completion_ready),
      ("step",step_input(base,completion_ready["state"],completion),completion_result)]
    return {"base":base,"permitted":permit,"authorization_event":authorization_event,"authorized":authorization,
      "dispatch_event":dispatch,"dispatched":dispatch_result,"completion_clock_event":clock3,"completion_ready":completion_ready,
      "completion_event":completion,"completed":completion_result,"stages":[[op,i,public_result(o)] for op,i,o in stages]}
