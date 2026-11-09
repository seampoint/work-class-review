#!/usr/bin/env python3
"""Publish source-derived assessment cases and complete oracles without consumers."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import runpy
from pathlib import Path

from corpus_common import CASES, CONFORMANCE, ROOT, candidate_pin, canonical_bytes, digest, exact_case, write_canonical_json
from authority_fixture import authority_refusal, authority_specimen
from fixture_factory import add_seconds, available_clock, readback_paths
from lifecycle_factory import admitted_transition, replay_result, state_digest, stateful_refusal, step_input
from assessment_fixture import (
    APPROVAL, ASSESSMENT, CRITERIA, DECISION, NOW, PIN, SOURCE_PATH, STEP,
    authority, expected_authority, fields, normalized_obligations, policy_refusal,
    authorized, completed, completion_clock, current_requirements, dispatched, human_leaf, lifecycle_base, source_coordinates,
    public_result, rebind_outer, trace, typed,
)
from checkpoint_reseal import reseal_last_transition
from equipment_observation_fixture import observation
from lifecycle_factory import base_lifecycle, permitted_proposal, proposal_permit

HERE = Path(__file__).resolve().parent
GROUP = CASES / "assessment-source"
SPECIMEN = CONFORMANCE / "specimens/factual-customer-message-review"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.3"


def sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def sort_observations(value):
    value["observations"].sort(key=lambda row: digest("authority-observation", row))


def selected_observation(value, requirement_id):
    return next(row for row in value["observations"] if row["query"].get("requirement_id") == requirement_id)


def selected_field(observation, name):
    return next(row["value"] for row in observation["fields"] if row["name"] == name)


def replace_human(supplied):
    human = supplied["decision_bases"][0]["evidence"]
    human["decision_act_digest"] = expected_authority(human["authority_input"], leaf=True)["decision_act_digest"]
    native = {row["name"]: row["value"] for row in supplied["proposal"]["fields"]}
    basis = supplied["assessment_bases"][0]
    requirements, values, declaration = current_requirements(native, basis, human)
    supplied["envelope"]["decision_requirements"] = [declaration]
    supplied["envelope"]["source_observation_requirements"] = requirements
    supplied["observations"] = [row for row in supplied["observations"] if row["query"]["purpose"] == "REVOCATION"]
    for req in requirements:
        revision = "revision-1" if req["id"] in ["customer-facts", "immutable-assessment"] else req["id"] + "-revision-1"
        supplied["observations"].append(observation(req, supplied, values=values[req["id"]], revision=revision,
            record_id=basis["review"]["id"] if req["id"] == APPROVAL else None))
    rebind_outer(supplied)


def readback(definition):
    rows = []
    for path in readback_paths(definition):
        value = definition
        for token in path[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
        rows.append({"path": path, "value": canonical_bytes(value).decode()})
    return {"status": "READBACK", "digest": digest("work-class-definition", definition), "lines": rows}


def clock_checkpoint(base, state, event_id):
    latest = state["clocks"][-1]
    clock = available_clock(base["authority_input"]["clock"]["source"], str(int(latest["revision"]) + 1), add_seconds(latest["observed_time"], "1"))
    event = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "kind": "CLOCK", "event_id": event_id,
        "instance_id": state["instance_id"], "expected_state_revision": state["revision"], "expected_state_digest": state_digest(state),
        "clock": clock, "activation_clocks": []}
    def change(next_state):
        next_state["clocks"].append(copy.deepcopy(clock))
    expected = admitted_transition(state, event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": "AVAILABLE"}], mutate=change)
    return step_input(base, state, event), public_result(expected)


def forged_permitted_checkpoint(facts, mutation):
    """Reseal every last-proposal commitment around a deliberately invalid basis."""
    state = copy.deepcopy(facts["permitted"]["state"])
    permit = state["permits"][-1]
    mutation(permit["authority_basis"])
    supplied = permit["authority_basis"]
    claimed = expected_authority(supplied)
    permit.update(authority_result=claimed, authority_result_digest=digest("authority-result", claimed), authority_evidence_digest=claimed["evidence_digest"])
    event = copy.deepcopy(facts["base"]["proposal_event"])
    event["authority_input"] = copy.deepcopy(supplied)
    event["observation_digests"] = sorted(digest("authority-observation", row) for row in supplied["observations"])
    proposal_digest = digest("proposal", event)
    event_digest = digest("runtime-event", event)
    permit["proposal_digest"] = proposal_digest
    permit["permit_id"] = digest("permit", {key: value for key, value in permit.items() if key != "permit_id"})
    record = state["proposals"][-1]
    record.update(event_digest=event_digest, proposal_digest=proposal_digest, permit_digest=permit["permit_id"], authority_result_digest=permit["authority_result_digest"])
    receipt = state["receipts"][-1]
    receipt.update(event_digest=event_digest, permit_digest=permit["permit_id"], authority_result_digest=permit["authority_result_digest"])
    replay = next(row for row in state["replays"] if row["event_id"] == event["event_id"])
    replay.update(event_digest=event_digest, permit=copy.deepcopy(permit))
    reseal_last_transition(state)
    return state


def digest_vectors():
    base, _, _ = authority()
    basis = base["assessment_bases"][0]
    declaration = base["envelope"]["assessment_requirements"][0]
    context = {"types": copy.deepcopy(base["work_class"]["types"]), "records": [{"requirement_id": "customer-facts",
        **{key: next(row for row in base["envelope"]["source_observation_requirements"] if row["id"] == "customer-facts")[key]
           for key in ["provider", "source", "record_type"]},
        **{key: copy.deepcopy(basis["supporting_context"][0][key]) for key in ["provider_record_id", "provider_revision", "fields"]}}]}
    subject = {"principal": base["proposal"]["executor"]["principal"],
        **{key: copy.deepcopy(base["proposal"][key]) for key in ["work_class_digest", "instance", "occurrence", "step", "interface", "operation", "fields"]},
        "context_digest": digest("content-assessment-context", context), "rubric_digest": digest("content-assessment-rubric", declaration["rubric"]),
        "evaluator": declaration["evaluator"]}
    bodies = {"content-assessment-context": context, "content-assessment-rubric": declaration["rubric"],
        "content-assessment-subject": subject, "content-assessment": basis["assessment"], "content-assessment-review": basis["review"]}
    rows = []
    for domain, body in bodies.items():
        rows.append({"id": domain + "-component", "domain": domain, "body": body,
            "canonical_utf8_hex": canonical_bytes(body).hex(), "expected_digest": digest(domain, body)})
        for name, text in [("unicode", "caf\u00e9 \u03bb \U0001f642"), ("crlf", "first\r\nsecond\nthird"), ("escaping", 'quote" backslash\\ tab\t')]:
            vector = {"exact": text, "empty": [], "null": None}
            rows.append({"id": domain + "-" + name, "domain": domain, "body": vector,
                "canonical_utf8_hex": canonical_bytes(vector).hex(), "expected_digest": digest(domain, vector)})
        for name, vector in [("omitted", {"exact": "fixed"}), ("explicit-empty", {"exact": "fixed", "optional": []})]:
            rows.append({"id": domain + "-" + name, "domain": domain, "body": vector,
                "canonical_utf8_hex": canonical_bytes(vector).hex(), "expected_digest": digest(domain, vector)})
    return {"candidate_pin": PIN, "derivation": "Review-side canonical JSON and domain-separated SHA256 only; no consumer imports or outputs.", "vectors": rows}


def ordinary_trace(explicit_empty, *, declaration_empty=None, basis_empty=None, instance=None):
    """Ordinary optional-member control, separate from the selected business policy."""
    declaration_empty = explicit_empty if declaration_empty is None else declaration_empty
    basis_empty = explicit_empty if basis_empty is None else basis_empty
    base = lifecycle_base(instance=instance or ("ordinary-empty-assessment" if explicit_empty else "ordinary-omitted-assessment"))
    supplied = base["authority_input"]
    if declaration_empty:
        supplied["envelope"]["assessment_requirements"] = []
    else:
        supplied["envelope"].pop("assessment_requirements")
    if basis_empty:
        supplied["assessment_bases"] = []
    else:
        supplied.pop("assessment_bases")
    leaf_fields = {row["name"]: row["value"] for row in supplied["decision_bases"][0]["evidence"]["authority_input"]["proposal"]["fields"]}
    for row in supplied["envelope"]["decision_requirements"][0]["context_bindings"]:
        if row["value"]["kind"] == "ASSESSMENT": row["value"] = {"kind": "LITERAL", "value": copy.deepcopy(leaf_fields[row["field"]])}
    approval = next(row for row in supplied["envelope"]["source_observation_requirements"] if row["id"] == APPROVAL)
    approval["record_id"] = "CM-REVIEW-074-01"
    observed = selected_observation(supplied, APPROVAL)
    observed["query"]["record_id"] = approval["record_id"]
    observed["query_digest"] = digest("authority-query", observed["query"])
    rebind_outer(supplied)
    base["authority_result"] = expected_authority(supplied)
    base["proposal_event"]["authority_input"] = supplied
    base["proposal_event"]["observation_digests"] = sorted(digest("authority-observation", row) for row in supplied["observations"])
    permit = permitted_proposal(base)
    authorization_event, authorization = authorized(base, permit)
    dispatch, dispatch_result = dispatched(base, authorization)
    clock3, ready = completion_clock(base, dispatch_result)
    completion, result = completed(base, ready)
    stages = [["deploy", base["deploy_input"], base["deploy_result"]],
        ["step", step_input(base, base["deploy_result"]["state"], base["clock_event"]), base["clock_result"]],
        ["step", step_input(base, base["clock_result"]["state"], base["proposal_event"]), permit],
        ["step", step_input(base, permit["state"], base["dispatch_clock_event"]), base["dispatch_clock_result"]],
        ["step", step_input(base, base["dispatch_clock_result"]["state"], authorization_event), authorization],
        ["step", step_input(base, authorization["state"], dispatch), dispatch_result],
        ["step", step_input(base, dispatch_result["state"], clock3), ready],
        ["step", step_input(base, ready["state"], completion), result]]
    return {"base": base, "permitted": permit, "authorized": authorization, "authorization_event": authorization_event,
        "completed": result, "completion_event": completion, "stages": [[op, value, public_result(expected)] for op, value, expected in stages]}


def maximum_inventory_control():
    supplied, _, _ = authority()
    basis = supplied["assessment_bases"][0]
    rubric = supplied["envelope"]["assessment_requirements"][0]["rubric"]
    rubric["obligations"] = copy.deepcopy(supplied["source"]["obligations"][:32])
    rubric["criteria"] = [{"id": "criterion-" + str(i).zfill(2), "obligation_ids": [row["id"]], "citation_policy": "CONTEXT"}
        for i, row in enumerate(rubric["obligations"], 1)]
    snapshot = basis["supporting_context"][0]
    snapshot["fields"] += [{"name": "synthetic_marker_" + str(i).zfill(2), "value": typed("synthetic-context-" + str(i))} for i in range(1, 19)]
    snapshot["fields"].sort(key=lambda row: row["name"])
    citations = sorted([{"kind": "CONTEXT_FIELD", "requirement_id": "customer-facts", "field": row["name"]} for row in snapshot["fields"]], key=canonical_bytes)
    context = {"types": supplied["work_class"]["types"], "records": [{"requirement_id": "customer-facts", **source_coordinates("customer-facts"),
        **{key: snapshot[key] for key in ["provider_record_id", "provider_revision", "fields"]}}]}
    assessment = basis["assessment"]
    assessment["context_digest"] = digest("content-assessment-context", context)
    assessment["rubric_digest"] = digest("content-assessment-rubric", rubric)
    subject = {"principal": supplied["proposal"]["executor"]["principal"],
        **{key: supplied["proposal"][key] for key in ["work_class_digest", "instance", "occurrence", "step", "interface", "operation", "fields"]},
        "context_digest": assessment["context_digest"], "rubric_digest": assessment["rubric_digest"], "evaluator": assessment["evaluator"]}
    assessment["subject_digest"] = digest("content-assessment-subject", subject)
    assessment["criteria"] = [{"id": row["id"], "verdict": "PASS", "explanation": "Synthetic finite-inventory contract control.",
        "escalation": {"required": False, "reason": None}, "citations": copy.deepcopy(citations)} for row in rubric["criteria"]]
    basis["review"]["criteria"] = [{"id": row["id"], "disposition": "SATISFIED", "reason": None, "citations": copy.deepcopy(citations)} for row in rubric["criteria"]]
    basis["review"]["assessment_digest"] = digest("content-assessment", assessment)
    native = {row["name"]: row["value"] for row in supplied["proposal"]["fields"]}
    human, _ = human_leaf(native, basis)
    supplied["decision_bases"][0]["evidence"] = human
    replace_human(supplied)
    req = next(row for row in supplied["envelope"]["source_observation_requirements"] if row["id"] == "customer-facts")
    req["fields"] = [{"name": row["name"], "type_ref": row["value"]["type_ref"]} for row in snapshot["fields"]]
    observed = selected_observation(supplied, "customer-facts")
    observed["query"]["fields"] = copy.deepcopy(req["fields"])
    observed["query_digest"] = digest("authority-query", observed["query"])
    observed["fields"] = copy.deepcopy(snapshot["fields"])
    rebind_outer(supplied)
    return supplied


def empty_separation_control():
    constructors = runpy.run_path(str(HERE / "build-prior-binding-runtime-cases.py"))
    separation = [{"id": "confirmer-differs-from-payment-releaser", "relation": "DISTINCT_ACTOR", "selection": "UNIQUE_COMPLETED_ANCESTOR",
        "prior_step_id": "change-supplier-destination", "prior_act_kind": "VERIFY", "current_act_kind": "INSTANCE_DECISION"}]
    context = constructors["supplier_context"]("assessment-empty-separation", prior_mode="none", separation_rows=separation,
        payment_actor="destination-confirmer-person")
    authority = context["payment_authority"]
    authority["input"]["assessment_bases"] = []
    evidence = {key: authority["input"][key] for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock", "assessment_bases"]}
    authority["result"]["evidence_digest"] = digest("authority-evidence", evidence)
    authority["result_digest"] = digest("authority-result", authority["result"])
    event = context["payment_event"]
    event["authority_input"] = copy.deepcopy(authority["input"])
    basis = constructors["separation_basis"](context, separation[0]["id"])
    def change(state):
        state["proposals"].append({"event_id": event["event_id"], "event_digest": digest("runtime-event", event),
            "proposal_digest": digest("proposal", event), "occurrence_id": event["occurrence"]["occurrence_id"], "disposition": "WITHHELD",
            "permit_digest": None, "authority_result_digest": authority["result_digest"], "reservation_receipt_digests": [], "prior_permit_digest": None})
        state["proposals"].sort(key=lambda row: row["event_id"])
    result = admitted_transition(context["state"], event, disposition="WITHHELD", reason_codes=["SEPARATION_VIOLATED"],
        details=[{"kind": "SEPARATION", "authority_result": copy.deepcopy(authority["result"]), "basis": basis,
            "authority_basis": copy.deepcopy(authority["input"])}], receipt_authority_result_digest=authority["result_digest"], mutate=change)
    base = {"definition": context["definition"], "definition_digest": context["definition_digest"], "deploy_input": {"profile": "LINEAR", "role": context["state"]["role"]},
        "authority_input": authority["input"]}
    return base, context["state"], event, result


def assessment_operation_scope_control(*, criterion_on_operation=False):
    supplied, _, _ = authority()
    original = supplied["work_class"]["steps"][0]
    other = copy.deepcopy(original)
    other["id"] = "zz-known-review-step"
    original.pop("dispatch_gate")
    supplied["work_class"]["steps"].append(other)
    supplied["envelope"]["assessment_requirements"][0]["step"] = other["id"]
    supplied["envelope"]["decision_requirements"][0]["step"] = other["id"]
    for row in supplied["envelope"]["source_observation_requirements"]:
        row["step"] = other["id"]
    if not criterion_on_operation:
        supplied["envelope"]["gate"]["criteria"][0]["step"] = other["id"]
    supplied.pop("assessment_bases")
    supplied.pop("decision_bases")
    supplied["observations"] = [row for row in supplied["observations"] if row["query"]["purpose"] == "REVOCATION"]
    rebind_outer(supplied)
    return supplied


def content_reissuance_control():
    supplied, _, _ = authority()
    content = selected_observation(supplied, "current-message-content")
    content["revision"] = "current-message-content-revision-2"
    sort_observations(supplied)
    return supplied


def build():
    rows, labels = [], {}
    def emit(operation, supplied, expected, text, label, requirements=None):
        case_id = "C3-ASMT-" + str(len(rows) + 1).zfill(3)
        rows.append(exact_case(case_id, operation, supplied, expected, requirements or ["ASSESS-001", "ASSESS-002", "ASSESS-003", "ASSESS-004", "ASSESS-005", "ASSESS-006"], text))
        labels[label] = case_id
    def evaluate(supplied, expected, text, label):
        emit("evaluate", {"kind": "AUTHORITY", "request": supplied}, expected, text, label)
    def deny(supplied, code, text, label, shape=False):
        evaluate(supplied, {"status": "REFUSED", "code": code, "path": ""} if shape else authority_refusal([], code=code), text, label)
    baseline, positive, _ = authority()
    evaluate(baseline, positive, "Exact six native fields, fourteen facts, five model conclusions and complete mandatory human approval establish recorded authority. This does not establish semantic truth.", "authority-positive")
    for verdict in ["FAIL", "UNCERTAIN"]:
        supplied, expected, _ = authority(model={"grounded-factual-request": verdict})
        evaluate(supplied, expected, "A model " + verdict + " does not grant or permanently prohibit authority. An authenticated human records SATISFIED with the required criterion reason.", "model-" + verdict.lower())
    supplied, expected, _ = authority(escalated=["neutral-tone"])
    evaluate(supplied, expected, "A flagged PASS still requires the explicit human criterion reason. This profile always requires the human decision.", "escalated-pass")
    supplied, expected, _ = authority(explanations={"neutral-tone": "x" * 8192})
    evaluate(supplied, expected, "An exact 8192-codepoint explanation is within the selected finite schema limit and is bound by the assessment/review chain.", "explanation-8192")
    supplied = maximum_inventory_control()
    evaluate(supplied, expected_authority(supplied), "Separately labeled generic contract control admits32 rubric obligations,32 model/human criteria and32 valid citations per criterion. Its18 synthetic context markers are not bank facts or an expansion of the fixed five-criterion business source.", "generic-max32")
    for target in ["model-citations", "human-citations", "rubric-obligations"]:
        value = copy.deepcopy(supplied)
        if target == "rubric-obligations": value["envelope"]["assessment_requirements"][0]["rubric"]["obligations"].append(copy.deepcopy(value["source"]["obligations"][32]))
        else:
            collection = value["assessment_bases"][0]["assessment" if target == "model-citations" else "review"]["criteria"][0]["citations"]
            collection.append(copy.deepcopy(collection[-1]))
        deny(value, "SCHEMA_INVALID", "Generic finite-inventory control exceeds the closed32-member " + target + " schema ceiling.", "generic-max33-" + target, shape=True)
    for disposition in ["NOT_SATISFIED", "UNRESOLVED"]:
        supplied, _, _ = authority(human={"neutral-tone": disposition})
        evaluate(supplied, policy_refusal(supplied, [("ASSESSMENT", ASSESSMENT, "ASSESSMENT_NOT_SATISFIED")]), "A human " + disposition + " conclusion withholds despite authenticated ACCEPT signing and all model PASS results.", "human-" + disposition.lower())
    supplied, _, _ = authority(decision="REJECT")
    evaluate(supplied, policy_refusal(supplied, [("ASSESSMENT", ASSESSMENT, "ASSESSMENT_NOT_SATISFIED")]), "An authenticated ACCEPT act attesting to a business REJECT body does not permit the message.", "review-reject")
    for label, change, code in [
        ("basis-omitted", lambda v: v.pop("assessment_bases"), "EVIDENCE_UNAVAILABLE"),
        ("basis-empty", lambda v: v.update(assessment_bases=[]), "EVIDENCE_UNAVAILABLE"),
        ("basis-wrong-id", lambda v: v["assessment_bases"][0].update(requirement_id="unrequested-assessment"), "DEPENDENCY_MISMATCH"),
        ("human-omitted", lambda v: v.pop("decision_bases"), "EVIDENCE_UNAVAILABLE"),
        ("snapshot-missing", lambda v: v["assessment_bases"][0].update(supporting_context=[]), "EVIDENCE_UNAVAILABLE"),
        ("snapshot-extra", lambda v: v["assessment_bases"][0]["supporting_context"].append({**copy.deepcopy(v["assessment_bases"][0]["supporting_context"][0]), "requirement_id": "unrequested-context"}), "DEPENDENCY_MISMATCH"),
        ("snapshot-field-missing", lambda v: v["assessment_bases"][0]["supporting_context"][0]["fields"].pop(), "EVIDENCE_UNAVAILABLE"),
        ("snapshot-field-extra", lambda v: v["assessment_bases"][0]["supporting_context"][0]["fields"].append({"name": "zz-extra", "value": typed("unrequested")}), "REFERENCE_INVALID"),
        ("snapshot-known-nominal", lambda v: v["assessment_bases"][0]["supporting_context"][0]["fields"][0]["value"].update(type_ref="COUNT"), "TYPE_INVALID"),
        ("snapshot-unknown-nominal", lambda v: v["assessment_bases"][0]["supporting_context"][0]["fields"][0]["value"].update(type_ref="UNKNOWN"), "REFERENCE_INVALID"),
        ("snapshot-field-order", lambda v: v["assessment_bases"][0]["supporting_context"][0]["fields"].reverse(), "INPUT_INVALID"),
        ("model-criterion-missing", lambda v: v["assessment_bases"][0]["assessment"]["criteria"].pop(), "EVIDENCE_UNAVAILABLE"),
        ("human-criterion-missing", lambda v: v["assessment_bases"][0]["review"]["criteria"].pop(), "EVIDENCE_UNAVAILABLE"),
        ("model-criterion-unknown", lambda v: v["assessment_bases"][0]["assessment"]["criteria"].append({**copy.deepcopy(v["assessment_bases"][0]["assessment"]["criteria"][-1]), "id": "zz-unknown"}), "REFERENCE_INVALID"),
        ("human-criterion-unknown", lambda v: v["assessment_bases"][0]["review"]["criteria"].append({**copy.deepcopy(v["assessment_bases"][0]["review"]["criteria"][-1]), "id": "zz-unknown"}), "REFERENCE_INVALID"),
        ("model-criterion-order", lambda v: v["assessment_bases"][0]["assessment"]["criteria"].reverse(), "INPUT_INVALID"),
        ("human-criterion-duplicate", lambda v: v["assessment_bases"][0]["review"]["criteria"].append(copy.deepcopy(v["assessment_bases"][0]["review"]["criteria"][-1])), "INPUT_INVALID"),
        ("model-citation-reference", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][1].update(citations=[{"kind": "PROPOSAL_FIELD", "field": "unknown"}]), "REFERENCE_INVALID"),
        ("human-citation-reference", lambda v: v["assessment_bases"][0]["review"]["criteria"][0].update(citations=[{"kind": "CONTEXT_FIELD", "requirement_id": "customer-facts", "field": "unknown"}]), "REFERENCE_INVALID"),
        ("model-citation-duplicate", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][1]["citations"].append(copy.deepcopy(v["assessment_bases"][0]["assessment"]["criteria"][1]["citations"][0])), "INPUT_INVALID"),
        ("model-citation-policy", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][0].update(citations=[{"kind": "PROPOSAL_FIELD", "field": "body"}]), "BINDING_MISMATCH"),
        ("escalation-missing-reason", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][0]["escalation"].update(required=True), "INPUT_INVALID"),
        ("escalation-unrequested-reason", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][0]["escalation"].update(reason="Not flagged."), "INPUT_INVALID"),
        ("assessed-invalid-calendar", lambda v: v["assessment_bases"][0]["assessment"].update(assessed_at="2026-02-30T09:58:00Z"), "INPUT_INVALID"),
    ]:
        supplied = copy.deepcopy(baseline); change(supplied)
        deny(supplied, code, "Exact admission or local binding refusal: " + label + ".", label)
    for label, change in [
        ("verdict-waiver", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][0].update(verdict="WAIVED")),
        ("human-waiver", lambda v: v["assessment_bases"][0]["review"]["criteria"][0].update(disposition="WAIVED")),
        ("model-citations-zero", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][0].update(citations=[])),
        ("model-citations-33", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][0].update(citations=[{"kind": "PROPOSAL_FIELD", "field": "body"}] * 33)),
        ("model-explanation-empty", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][0].update(explanation="")),
        ("model-explanation-8193", lambda v: v["assessment_bases"][0]["assessment"]["criteria"][0].update(explanation="x" * 8193)),
        ("basis-two", lambda v: v["assessment_bases"].append(copy.deepcopy(v["assessment_bases"][0]))),
        ("model-criteria-33", lambda v: v["assessment_bases"][0]["assessment"].update(criteria=[copy.deepcopy(v["assessment_bases"][0]["assessment"]["criteria"][0])] * 33)),
        ("human-criteria-33", lambda v: v["assessment_bases"][0]["review"].update(criteria=[copy.deepcopy(v["assessment_bases"][0]["review"]["criteria"][0])] * 33)),
        ("context-65", lambda v: v["assessment_bases"][0].update(supporting_context=[copy.deepcopy(v["assessment_bases"][0]["supporting_context"][0])] * 65)),
        ("assessment-extra-property", lambda v: v["assessment_bases"][0]["assessment"].update(confidence="0.99")),
    ]:
        supplied = copy.deepcopy(baseline); change(supplied)
        deny(supplied, "SCHEMA_INVALID", "The closed evaluate input refuses before authority admission: " + label + ".", label, shape=True)
    for label, source, key in [
        ("subject-digest", "assessment", "subject_digest"), ("context-digest", "assessment", "context_digest"),
        ("rubric-digest", "assessment", "rubric_digest"), ("review-assessment-digest", "review", "assessment_digest"),
    ]:
        supplied = copy.deepcopy(baseline); supplied["assessment_bases"][0][source][key] = "sha256:" + "0" * 64
        deny(supplied, "BINDING_MISMATCH", "A copied or changed local " + key + " does not bind the recorded content and approval.", label)
    for label, change in [
        ("review-issue-identity", lambda v: v["assessment_bases"][0]["review"].update(id="CM-REVIEW-OTHER")),
        ("assessment-evaluator", lambda v: v["assessment_bases"][0]["assessment"]["evaluator"].update(version="revision-2")),
        ("snapshot-record-identity", lambda v: v["assessment_bases"][0]["supporting_context"][0].update(provider_record_id="other-facts")),
        ("snapshot-record-revision", lambda v: v["assessment_bases"][0]["supporting_context"][0].update(provider_revision="revision-2")),
        ("snapshot-value", lambda v: v["assessment_bases"][0]["supporting_context"][0]["fields"][0]["value"].update(value="84001")),
        ("copy-other-instance", lambda v: v["proposal"].update(instance="another-instance")),
        ("copy-other-occurrence", lambda v: v["proposal"].update(occurrence="another-occurrence")),
        ("copy-other-principal", lambda v: v["proposal"]["executor"].update(principal="another-principal")),
    ]:
        supplied = copy.deepcopy(baseline); change(supplied)
        deny(supplied, "BINDING_MISMATCH", "The exact assessment/review subject does not transfer across this changed identity or dependency: " + label + ".", label)
    for name in sorted(row["name"] for row in baseline["proposal"]["fields"]):
        supplied = copy.deepcopy(baseline); row = next(r for r in supplied["proposal"]["fields"] if r["name"] == name)
        row["value"]["value"] = "1" if name == "attachment_count" else row["value"]["value"] + " changed"
        deny(supplied, "BINDING_MISMATCH", "All native request fields enter the exact subject. Changing " + name + " requires a fresh assessment and human approval.", "native-" + name)
    supplied, _, _ = authority(model={"grounded-factual-request": "FAIL"})
    supplied["assessment_bases"][0]["review"]["criteria"][0]["reason"] = None
    deny(supplied, "BINDING_MISMATCH", "A required adverse-model criterion reason is absent; a human conclusion alone does not complete the exact review.", "adverse-reason-missing")
    supplied, _, _ = authority(assessed_at="2026-10-08T09:59:01Z")
    deny(supplied, "BINDING_MISMATCH", "An exact chain assessed after the authenticated selected human signed cannot represent that human's review of the assessment.", "assessment-after-human")
    for label, mutate, code in [
        ("rubric-unknown-obligation", lambda e: e["assessment_requirements"][0]["rubric"]["obligations"][0].update(id="unknown-obligation"), "REFERENCE_INVALID"),
        ("rubric-source-text", lambda e: e["assessment_requirements"][0]["rubric"]["obligations"][0].update(text="Different known source obligation."), "DEPENDENCY_MISMATCH"),
        ("rubric-coverage-gap", lambda e: e["assessment_requirements"][0]["rubric"]["criteria"][0].update(obligation_ids=[e["assessment_requirements"][0]["rubric"]["obligations"][1]["id"]]), "REFERENCE_INVALID"),
        ("selection-fields-same", lambda e: e["assessment_requirements"][0]["sources"]["selection"].update(identity_field="assessment_digest"), "UNSUPPORTED_RELATION"),
        ("role-overlap", lambda e: e["assessment_requirements"][0]["sources"].update(content="customer-facts"), "UNSUPPORTED_RELATION"),
        ("blocker-overlap", lambda e: e["assessment_requirements"][0]["sources"]["blockers"].append("customer-facts"), "UNSUPPORTED_RELATION"),
        ("profile-declaration-removed", lambda e: e.pop("assessment_requirements"), "REFERENCE_INVALID"),
    ]:
        supplied = copy.deepcopy(baseline); mutate(supplied["envelope"])
        if label == "blocker-overlap": supplied["envelope"]["assessment_requirements"][0]["sources"]["blockers"].sort()
        if label == "rubric-unknown-obligation": supplied["envelope"]["assessment_requirements"][0]["rubric"]["obligations"].sort(key=lambda row: row["id"])
        if label == "profile-declaration-removed": supplied.pop("assessment_bases")
        rebind_outer(supplied)
        deny(supplied, code, "Static selected profile admission: " + label + ".", label)
    derived = [row for row in baseline["envelope"]["decision_requirements"][0]["context_bindings"] if row["value"]["kind"] == "ASSESSMENT"]
    for member in derived:
        name = member["field"]
        supplied = copy.deepcopy(baseline)
        binding = next(row for row in supplied["envelope"]["decision_requirements"][0]["context_bindings"] if row["field"] == name)
        old = next(row["value"] for row in supplied["decision_bases"][0]["evidence"]["authority_input"]["proposal"]["fields"] if row["name"] == name)
        binding["value"] = {"kind": "LITERAL", "value": copy.deepcopy(old)}; rebind_outer(supplied)
        deny(supplied, "UNSUPPORTED_RELATION", "A copied literal cannot replace the required computed " + member["value"]["member"] + " binding.", "computed-copy-" + name)
    supplied = copy.deepcopy(baseline)
    supplied["envelope"]["decision_requirements"][0]["context_bindings"][0]["value"] = {"kind": "ASSESSMENT", "requirement_id": "unknown-assessment", "member": "SUBJECT_DIGEST", "type_ref": "IDENTITY"}
    rebind_outer(supplied); deny(supplied, "REFERENCE_INVALID", "An unknown derived-selector target remains a reference fault before induced null-record or member-coverage consequences.", "selector-unknown")
    supplied = copy.deepcopy(baseline)
    sibling = copy.deepcopy(supplied["envelope"]["decision_requirements"][0]); sibling["id"] = "sibling-review"
    supplied["envelope"]["decision_requirements"].append(sibling)
    supplied["decision_bases"].append({**copy.deepcopy(supplied["decision_bases"][0]), "requirement_id": "sibling-review"})
    rebind_outer(supplied)
    deny(supplied, "UNSUPPORTED_RELATION", "A computed assessment selector cannot be reused on a sibling human requirement.", "selector-sibling")
    for label, role, changed, code in [
        ("evaluator-fields-same", "evaluator", {"provider_field": "model"}, "UNSUPPORTED_RELATION"),
        ("effectiveness-fields-same", "effectiveness", {"identity_field": "effective"}, "TYPE_INVALID"),
    ]:
        supplied = copy.deepcopy(baseline)
        supplied["envelope"]["assessment_requirements"][0]["sources"][role].update(changed); rebind_outer(supplied)
        deny(supplied, code, "Distinct source map names are required. The unavoidable BOOLEAN/identity effectiveness collision retains earlier nominal TYPE_INVALID precedence.", label)
    for label, mutation in [
        ("review-human-reference-missing", lambda v: v["envelope"]["assessment_requirements"][0].update(review_decision_requirement_id="unknown-human")),
        ("approval-source-missing", lambda v: v["envelope"]["decision_requirements"][0].update(record_requirement_id="unknown-source")),
        ("issuance-source-missing", lambda v: v["envelope"]["assessment_requirements"][0]["sources"]["assessment"].update(requirement_id="unknown-source")),
        ("selection-source-missing", lambda v: v["envelope"]["assessment_requirements"][0]["sources"]["selection"].update(requirement_id="unknown-source")),
    ]:
        supplied = copy.deepcopy(baseline); mutation(supplied); rebind_outer(supplied)
        deny(supplied, "REFERENCE_INVALID", "An unresolved selected profile reference defers coverage/null-record/relation consequences: " + label + ".", label)
    supplied = copy.deepcopy(baseline)
    human = supplied["decision_bases"][0]["evidence"]["authority_input"]
    human["envelope"]["gate"]["criteria"][0]["predicate"] = {"kind": "EQUAL", "left": {"kind": "FIELD", "name": "review_digest"},
        "right": {"kind": "LITERAL", "value": next(row["value"] for row in human["proposal"]["fields"] if row["name"] == "review_digest")}}
    rebind_outer(human); replace_human(supplied)
    deny(supplied, "UNSUPPORTED_RELATION", "An actual supplied leaf cannot use a computed assessment field in a gate predicate. The selected leaf and its wrapper are otherwise reissued coherently.", "leaf-computed-predicate")
    for offset in [-1, 0, 1]:
        supplied = copy.deepcopy(baseline); leaf = supplied["decision_bases"][0]["evidence"]["authority_input"]
        target = 262144 + offset
        leaf["source"]["obligations"][0]["text"] += "x" * (target - len(canonical_bytes(leaf)))
        rebind_outer(leaf); replace_human(supplied)
        if len(canonical_bytes(leaf)) != target: raise ValueError("leaf canonical boundary constructor")
        evaluate(supplied, expected_authority(supplied) if offset <= 0 else authority_refusal([], code="LIMIT_EXCEEDED"),
            "The complete supplied human leaf canonical byte ceiling is inclusive at 262144; outer complete input remains below its independent ceiling.", "leaf-byte-" + str(offset))
    for offset in [-1, 0, 1]:
        supplied = copy.deepcopy(baseline)
        target = 1048576 + offset
        supplied["source"]["obligations"][0]["text"] += "x" * (target - len(canonical_bytes(supplied)))
        rebind_outer(supplied)
        if len(canonical_bytes(supplied)) != target: raise ValueError("outer canonical boundary constructor")
        evaluate(supplied, expected_authority(supplied) if offset <= 0 else authority_refusal([], code="LIMIT_EXCEEDED"),
            "The complete decision-bearing authority canonical byte ceiling is inclusive at 1048576; the independent leaf remains below its separate ceiling.", "outer-byte-" + str(offset))
    for req_id in sorted(row["id"] for row in baseline["envelope"]["source_observation_requirements"]):
        supplied = copy.deepcopy(baseline); observed = selected_observation(supplied, req_id)
        observed.update(status="UNAVAILABLE", as_of=None, revision=None, fields=[], relations=[])
        observed.pop("provider_record_id", None); observed.pop("coverage", None); sort_observations(supplied)
        evaluate(supplied, policy_refusal(supplied, [("SOURCE_OBSERVATION", req_id, "SOURCE_OBSERVATION_UNAVAILABLE")]),
            "An unavailable current " + req_id + " record supplies no profile value. The inherited source reason remains decisive without a duplicate dependency-change reason.", "unavailable-" + req_id)
    for req_id, name, value, relation_failure in [
        ("current-message-content", "body", "Different current draft.", True),
        ("customer-facts", "aggregate_usd_amount", "84001", False),
        ("current-context", "context_digest", "sha256:" + "0" * 64, False),
        ("current-rubric", "rubric_digest", "sha256:" + "0" * 64, False),
        ("current-evaluator", "version", "revision-2", False),
        ("immutable-assessment", "assessment_digest", "sha256:" + "0" * 64, True),
        ("current-assessment-selection", "assessment_digest", "sha256:" + "0" * 64, True),
        ("current-assessment-selection", "assessment_identity", "another-issuance", False),
        ("assessment-effectiveness", "effective", False, False),
    ]:
        supplied = copy.deepcopy(baseline); selected_field(selected_observation(supplied, req_id), name)["value"] = value; sort_observations(supplied)
        failed = [("ASSESSMENT", ASSESSMENT, "ASSESSMENT_DEPENDENCY_CHANGED")]
        if relation_failure: failed.append(("SOURCE_OBSERVATION", req_id, "SOURCE_OBSERVATION_RELATIONS"))
        evaluate(supplied, policy_refusal(supplied, failed), "A usable current " + req_id + "." + name + " contradicts the exact retained chain. False declared relations remain independently visible.", "current-" + req_id + "-" + name)
    for req_id, name in [("contact-authority", "authorized"), ("current-human-authority", "no_applicable_revocation"), ("message-governance-coordinator", "complete_writer_coverage")]:
        supplied = copy.deepcopy(baseline); selected_field(selected_observation(supplied, req_id), name)["value"] = False; sort_observations(supplied)
        evaluate(supplied, policy_refusal(supplied, [("SOURCE_OBSERVATION", req_id, "SOURCE_OBSERVATION_RELATIONS")]), "A complete human/model review cannot waive the independent current " + req_id + " condition.", "blocker-" + req_id)
    supplied = copy.deepcopy(baseline); selected_observation(supplied, "customer-facts")["fields"].reverse(); sort_observations(supplied)
    evaluate(supplied, expected_authority(supplied), "Current fields compare as named typed inventories; provider array order does not change the retained sorted context snapshot.", "current-field-order")
    supplied = copy.deepcopy(baseline); selected_observation(supplied, "immutable-assessment")["revision"] = "revision-2"; sort_observations(supplied)
    evaluate(supplied, policy_refusal(supplied, [("ASSESSMENT", ASSESSMENT, "ASSESSMENT_DEPENDENCY_CHANGED")]), "A current record with the same immutable issuance id and a different revision contradicts the exact issuance. This detects the supplied conflict, not hidden provider history.", "same-issuance-id-conflict")
    supplied = copy.deepcopy(baseline); observed = selected_observation(supplied, "current-message-content")
    selected_field(observed, "body")["value"] = "Different draft"; observed["relations"] = []; sort_observations(supplied)
    evaluate(supplied, policy_refusal(supplied, [("SOURCE_OBSERVATION", "current-message-content", "SOURCE_OBSERVATION_RELATIONS")]), "A copied relation-inventory gap makes this record structurally unusable for profile-map comparison.", "unusable-relations-no-map")
    supplied = copy.deepcopy(baseline); selected_observation(supplied, "current-context")["as_of"] = "2026-10-08T09:59:59Z"; sort_observations(supplied)
    evaluate(supplied, policy_refusal(supplied, [("SOURCE_OBSERVATION", "current-context", "SOURCE_OBSERVATION_STALE")]), "Zero freshness requires the accepted current instant. An unusable stale row supplies no map value.", "source-zero-freshness")
    # Ordinary compatibility includes the exact presence matrix in both envelope and evidence preimage.
    for declared in [False, True]:
        for supplied_empty in [False, True]:
            def configure(value, _original):
                if declared: value["envelope"]["assessment_requirements"] = []
            ordinary, wanted = authority_specimen(shared_budget=False, mutator=configure)
            if supplied_empty:
                ordinary["assessment_bases"] = []
                evidence = {key: ordinary[key] for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock"]}
                evidence["assessment_bases"] = []
                wanted["evidence_digest"] = digest("authority-evidence", evidence)
            evaluate(ordinary, wanted, "Ordinary authority preserves omitted/explicit-empty declarations and bases. Explicit empty bases enter the evidence digest without requiring an assessment.", "ordinary-matrix-" + str(declared).lower() + "-" + str(supplied_empty).lower())
    from equipment_correction_fixture import correction_fixture, correction_result, correction_refusal, rebind_authority, seal_correction
    for declared in [False, True]:
        for supplied_empty in [False, True]:
            ordinary, _ = correction_fixture()
            current = ordinary["correction"]["correction_authority_input"]
            if declared: current["envelope"]["assessment_requirements"] = []
            if supplied_empty: current["assessment_bases"] = []
            current, result = rebind_authority(current)
            if supplied_empty:
                evidence = {key: current[key] for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock"]}
                evidence["assessment_bases"] = []
                result["evidence_digest"] = digest("authority-evidence", evidence)
            ordinary["correction"]["correction_authority_input"] = current
            selected = next(row for row in current["acts"] if row["kind"] == "INSTANCE_DECISION")
            ordinary["correction"]["correction_authorization_digest"] = digest("authority-act", selected)
            seal_correction(ordinary["correction"])
            emit("check-evidence", ordinary, correction_result(ordinary, result), "The ordinary equipment correction explicitly demonstrates compatibility of omitted/empty assessment collections. This does not add a correction procedure to the customer-message component.", "correction-empty-" + str(declared).lower() + "-" + str(supplied_empty).lower(), ["ASSESS-004", "LIFE-020A"])
    for member in ["assessment_bases", "assessment_requirements"]:
        ordinary, _ = correction_fixture()
        current = ordinary["correction"]["correction_authority_input"]
        if member == "assessment_bases": current[member] = copy.deepcopy(baseline[member])
        else: current["envelope"][member] = copy.deepcopy(baseline["envelope"][member])
        emit("check-evidence", ordinary, correction_refusal("UNSUPPORTED_RELATION"), "Nonempty assessment profile carriers remain explicitly unsupported in correction authority.", "correction-nonempty-" + member, ["ASSESS-004", "LIFE-020A"])
    facts = trace()
    for index, (operation, supplied, expected) in enumerate(facts["stages"], 1):
        emit(operation, supplied, expected, "Complete source-derived lifecycle stage " + str(index) + ": " + expected.get("disposition", expected.get("status", "")) + ". All assessment bodies remain retained.", "lifecycle-" + str(index), ["ASSESS-006", "LIFE-003", "LIFE-007", "LIFE-008", "LIFE-010", "LIFE-019"])
    emit("readback", {"kind": "WORK_CLASS", "specification_pin": PIN,
        "artifact_bytes_base64": base64.b64encode(canonical_bytes(facts["base"]["definition"])).decode()},
        readback(facts["base"]["definition"]), "Complete deterministic definition readback is independent of semantic source correspondence acceptance.", "readback", ["WCD-001", "ASSESS-005"])
    for name, state, event in [
        ("proposal", facts["permitted"]["state"], facts["base"]["proposal_event"]),
        ("authorization", facts["authorized"]["state"], facts["authorization_event"]),
        ("completion", facts["completed"]["state"], facts["completion_event"]),
    ]:
        emit("step", step_input(facts["base"], state, event), replay_result(state, event["event_id"]), "Exact " + name + " replay returns retained conclusions without a model call or new human act.", "replay-" + name, ["ASSESS-006", "LIFE-016", "LIFE-019"])
    checkpoint_input, checkpoint_expected = clock_checkpoint(facts["base"], facts["permitted"]["state"], "assessment-checkpoint-clock")
    emit("step", checkpoint_input, checkpoint_expected, "Public admission reconstructs the complete permitted assessment and human evidence before recording a fresh clock after restart.", "checkpoint-valid", ["ASSESS-006", "LIFE-019"])
    checkpoint_input, checkpoint_expected = clock_checkpoint(facts["base"], facts["authorized"]["state"], "assessment-authorized-checkpoint-clock")
    emit("step", checkpoint_input, checkpoint_expected, "Public admission also reconstructs the complete refreshed assessment-bearing authorization/evaluation and immutable permit after restart.", "checkpoint-authorized-valid", ["ASSESS-006", "LIFE-019"])
    for name, mutation in [
        ("assessment-bases-omitted", lambda v: v.pop("assessment_bases")),
        ("changed-review", lambda v: v["assessment_bases"][0]["review"]["criteria"][0].update(reason="Changed retained review.")),
        ("changed-context", lambda v: v["assessment_bases"][0]["supporting_context"][0].update(provider_revision="revision-2")),
    ]:
        attacked = forged_permitted_checkpoint(facts, mutation)
        supplied, _ = clock_checkpoint(facts["base"], attacked, "assessment-attack-" + name)
        emit("step", supplied, stateful_refusal(attacked, "STATE_INVALID"), "Resealed retained permit attack " + name + " recomputes last receipt/root/replay commitments. Complete semantic reconstruction still refuses the supplied checkpoint; protected custody remains a premise.", "checkpoint-" + name, ["ASSESS-006", "LIFE-019"])
    for explicit_empty in [False, True]:
        control = ordinary_trace(explicit_empty)
        name = "empty" if explicit_empty else "omitted"
        for index, (operation, supplied, expected) in enumerate(control["stages"], 1):
            emit(operation, supplied, expected, "Ordinary " + name + " assessment-member compatibility control stage " + str(index) + ". The computed selectors are replaced by ordinary exhaustive literal bindings and the approval record uses its inherited nonnull identity. This control does not relax the component's mandatory assessment business policy.", "ordinary-" + name + "-lifecycle-" + str(index), ["ASSESS-006", "LIFE-019"])
        for replay_name, state, event in [("proposal", control["permitted"]["state"], control["base"]["proposal_event"]),
                ("authorization", control["authorized"]["state"], control["authorization_event"]),
                ("completion", control["completed"]["state"], control["completion_event"])]:
            emit("step", step_input(control["base"], state, event), replay_result(state, event["event_id"]),
                "Exact ordinary " + name + " optional-member " + replay_name + " replay preserves retained presence and its evidence digest.", "ordinary-" + name + "-replay-" + replay_name, ["ASSESS-006", "LIFE-019"])
        for checkpoint_name, state in [("permit", control["permitted"]["state"]), ("authorization", control["authorized"]["state"])]:
            supplied, expected = clock_checkpoint(control["base"], state, "ordinary-" + name + "-" + checkpoint_name + "-restart")
            emit("step", supplied, expected, "Public restart reconstructs the ordinary " + name + " optional-member " + checkpoint_name + " checkpoint from complete retained bytes, including the iff-present evidence preimage.", "ordinary-" + name + "-checkpoint-" + checkpoint_name, ["ASSESS-006", "LIFE-019"])
    base, state, event, withheld = empty_separation_control()
    emit("step", step_input(base, state, event), withheld, "An explicit-empty ordinary assessment basis enters the current authority evidence preimage and the complete failed-separation carrier, even without independent decision results.", "empty-separation-withheld", ["ASSESS-006", "LIFE-019"])
    supplied, expected = clock_checkpoint(base, withheld["state"], "empty-separation-restart")
    emit("step", supplied, expected, "Public restart reconstructs the complete explicit-empty failed-separation authority and exact selected ordinary decision.", "empty-separation-restart", ["ASSESS-006", "LIFE-019"])
    attacked = copy.deepcopy(withheld["state"]); attacked["receipts"][-1]["details"][0].pop("authority_basis")
    reseal_last_transition(attacked)
    supplied, expected = clock_checkpoint(base, attacked, "empty-separation-stripped-restart")
    emit("step", supplied, expected, "Observability limit: after stripping the complete explicit-empty ordinary failed-separation carrier and coherently resealing the supplied claims, the result has neither independent decision results nor an ASSESSMENT check that reveals the prior empty member. The visible claim remains an inherited ordinary separation checkpoint. Protected checkpoint custody must prevent this substitution; standalone reconstruction does not prove authenticity.", "empty-separation-stripped", ["ASSESS-006", "LIFE-019"])
    ordinary = base_lifecycle(instance_id="ordinary-no-gate-empty-assessment")
    current = ordinary["authority_input"]
    current["assessment_bases"] = []
    evidence = {key: current[key] for key in ["host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock", "assessment_bases"]}
    ordinary["authority_result"]["evidence_digest"] = digest("authority-evidence", evidence)
    ordinary["proposal_event"]["authority_input"] = current
    event = ordinary["proposal_event"]
    permit = proposal_permit(ordinary)
    permit["authority_basis"] = copy.deepcopy(current)
    permit["permit_id"] = digest("permit", {key: value for key, value in permit.items() if key != "permit_id"})
    def retain_empty_permit(state):
        next(row for row in state["active"] if row["occurrence"]["occurrence_id"] == event["occurrence"]["occurrence_id"])["status"] = "PERMITTED"
        state["total_actuations"] = str(int(state["total_actuations"]) + 1)
        counter = next(row for row in state["step_counters"] if row["step_id"] == event["occurrence"]["step_id"])
        counter["actuations"] = str(int(counter["actuations"]) + 1)
        state["proposals"].append({"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "proposal_digest": digest("proposal", event),
            "occurrence_id": event["occurrence"]["occurrence_id"], "disposition": "PERMITTED", "permit_digest": permit["permit_id"],
            "authority_result_digest": permit["authority_result_digest"], "reservation_receipt_digests": [], "prior_permit_digest": None})
        state["proposals"].sort(key=lambda row: row["event_id"])
        state["permits"].append(copy.deepcopy(permit)); state["permits"].sort(key=lambda row: row["permit_id"])
    permitted = admitted_transition(ordinary["clock_result"]["state"], event, disposition="PERMITTED", reason_codes=[], details=[], permit=permit,
        receipt_authority_result_digest=permit["authority_result_digest"], mutate=retain_empty_permit)
    emit("step", step_input(ordinary, ordinary["clock_result"]["state"], event), permitted,
        "An ordinary no-dispatch-gate LEGACY_NONTERMINAL operation still retains complete authority_basis solely because assessment_bases was explicitly supplied as[]. No independent human-decision result or assessment policy is present.", "ordinary-no-gate-empty-permit", ["ASSESS-006", "LIFE-008", "LIFE-019"])
    supplied, expected = clock_checkpoint(ordinary, permitted["state"], "ordinary-no-gate-empty-restart")
    emit("step", supplied, expected, "Public restart reconstructs the ordinary no-gate explicit-empty permit and the iff-present manual evidence digest from the complete retained authority input.", "ordinary-no-gate-empty-restart", ["ASSESS-006", "LIFE-008", "LIFE-019"])
    for member in ["assessment", "review"]:
        supplied = copy.deepcopy(baseline)
        supplied["assessment_bases"][0][member]["criteria"][-1]["id"] = "zz-unknown"
        deny(supplied, "EVIDENCE_UNAVAILABLE", "The original replacement-criterion stimulus omits required no-sar-implication and supplies unknown zz-unknown. Inherited phase2 missing-evidence precedence governs before the reference fault; preserved after source adjudication01/02.", "criterion-replacement-precedence-" + member)
    for declaration_empty, basis_empty in [(False, True), (True, False)]:
        name = "declaration-" + ("empty" if declaration_empty else "omitted") + "-basis-" + ("empty" if basis_empty else "omitted")
        control = ordinary_trace(False, declaration_empty=declaration_empty, basis_empty=basis_empty, instance="ordinary-" + name)
        for index, (operation, supplied, expected) in enumerate(control["stages"], 1):
            emit(operation, supplied, expected, "Ordinary off-diagonal " + name + " compatibility control stage " + str(index) + ". Complete retained inputs preserve the independently selected declaration and basis presence without adding assessment business policy.", "ordinary-" + name + "-lifecycle-" + str(index), ["ASSESS-006", "LIFE-019"])
        for replay_name, state, event in [("proposal", control["permitted"]["state"], control["base"]["proposal_event"]),
                ("authorization", control["authorized"]["state"], control["authorization_event"]),
                ("completion", control["completed"]["state"], control["completion_event"])]:
            emit("step", step_input(control["base"], state, event), replay_result(state, event["event_id"]),
                "Exact ordinary off-diagonal " + name + " " + replay_name + " replay preserves original optional-member presence and authority evidence.", "ordinary-" + name + "-replay-" + replay_name, ["ASSESS-006", "LIFE-019"])
        for checkpoint_name, state in [("permit", control["permitted"]["state"]), ("authorization", control["authorized"]["state"])]:
            supplied, expected = clock_checkpoint(control["base"], state, "ordinary-" + name + "-" + checkpoint_name + "-restart")
            emit("step", supplied, expected, "Public restart reconstructs the complete ordinary off-diagonal " + name + " " + checkpoint_name + " carrier and exact iff-present evidence preimage.", "ordinary-" + name + "-checkpoint-" + checkpoint_name, ["ASSESS-006", "LIFE-019"])
    supplied = assessment_operation_scope_control()
    emit("evaluate", {"kind": "AUTHORITY", "request": supplied}, authority_refusal([], code="REFERENCE_INVALID"), 'Both work-class steps are known. The envelope authorizes only send-customer-message. The complete assessment declaration, linked human declaration and role sources instead resolve to zz-known-review-step, which has no envelope operation. ASSESS-001 requires every role to resolve to the same operation step, so phase2 REFERENCE_INVALID precedes any later proposal binding or missing human evidence. Bases are omitted and source observations for the dormant step are not supplied, avoiding an unrelated extra-basis failure. No consumer was imported or executed.', "review-operation-scope-composite", ['ASSESS-001', 'ASSESS-002'])
    supplied = content_reissuance_control()
    emit("evaluate", {"kind": "AUTHORITY", "request": supplied}, expected_authority(supplied), 'Only the current-message-content observation revision advances from current-message-content-revision-1 to current-message-content-revision-2. All six native fields, context, rubric, evaluator, immutable assessment/review/human body and current assessment selector remain exact and unchanged. ASSESS-003 binds native bytes and complete context, not current content observation revision. ASSESS-005 content equality compares the six native fields. Mechanical result is READY_FOR_RESERVATION. If the provider declares this to be a new immutable content issuance requiring fresh review under component source01, retaining the old selected assessment violates the external current-selector/coordination premise; acceptance proves no compliance with that premise. The complete evidence digest changes because the observation revision is retained. No consumer was imported or executed.', "content-reissuance-selector-limit", ['ASSESS-003', 'ASSESS-005', 'ASSESS-006'])
    supplied = assessment_operation_scope_control(criterion_on_operation=True)
    emit("evaluate", {"kind": "AUTHORITY", "request": supplied}, authority_refusal([], code="REFERENCE_INVALID"), "Both work-class steps are known. The sole envelope operation and valid zero-attachments criterion remain on send-customer-message. The assessment declaration, linked human declaration and all their role source requirements name known zz-known-review-step, which has no envelope operation. The original step has no dangling SOURCE_REQUIREMENTS gate; the second step retains its complete gate. Bases are omitted because none is selected for the proposed primary step. ASSESS-001 operation scope requires phase2 REFERENCE_INVALID before later application binding. This new source-owned probe removes original209's separate inherited gate-criterion reference fault, grounded in AUTHORITY-CHECKS's requirement that each criterion step occur in envelope.operations. Expected refusal was derived before execution, without consumer code or outputs. Original209/210 remain frozen unchanged.", "review-operation-scope-isolated", ['ASSESS-001', 'ASSESS-002'])
    return rows, labels, facts


def main():
    rows, labels, facts = build()
    for row in rows: write_canonical_json(GROUP / (row["id"] + ".json"), row)
    SPECIMEN.mkdir(parents=True, exist_ok=True)
    (SPECIMEN / "source-packet.md").write_bytes(SOURCE_PATH.read_bytes())
    clarification = HERE / "fixtures/factual-customer-message-review-revision1-selector-clarification.md"
    (SPECIMEN / "source-selector-clarification.md").write_bytes(clarification.read_bytes())
    clarification_ref = {"path": "source-selector-clarification.md", "raw_sha256": sha(clarification),
        "original_source_sha256": sha(SOURCE_PATH), "case_ids": [labels["content-reissuance-selector-limit"]],
        "scope": "No business prohibition changes. Current content issuance invalidation depends on truthful current assessment selection and coordinated writers; native equality alone does not detect a false unchanged selector."}
    write_canonical_json(SPECIMEN / "normalized-obligations.json", normalized_obligations())
    write_canonical_json(SPECIMEN / "authority-input.json", rows[0]["input"]["request"])
    write_canonical_json(SPECIMEN / "authority-result-derived.json", rows[0]["expected"])
    write_canonical_json(SPECIMEN / "work-class.json", facts["base"]["definition"])
    write_canonical_json(SPECIMEN / "readback-derived.json", readback(facts["base"]["definition"]))
    write_canonical_json(SPECIMEN / "digest-known-answers.json", digest_vectors())
    streams = {"lifecycle": [row for row in rows if row["id"] in [labels["lifecycle-" + str(i)] for i in range(1, 9)]],
        "restart": [row for row in rows if row["id"] in [labels["checkpoint-valid"], *[labels["checkpoint-" + name] for name in ["assessment-bases-omitted", "changed-review", "changed-context"]]]],
        "replay": [row for row in rows if row["id"] in [labels["replay-" + name] for name in ["proposal", "authorization", "completion"]]]}
    for name in ["omitted", "empty"]:
        streams["ordinary-" + name] = [row for row in rows if row["id"] in [value for label, value in labels.items() if label.startswith("ordinary-" + name + "-")]]
    for name in ["declaration-omitted-basis-empty", "declaration-empty-basis-omitted"]:
        streams["ordinary-" + name] = [row for row in rows if row["id"] in [value for label, value in labels.items() if label.startswith("ordinary-" + name + "-")]]
    streams["ordinary-no-gate-empty"] = [row for row in rows if row["id"] in [labels["ordinary-no-gate-empty-permit"], labels["ordinary-no-gate-empty-restart"]]]
    streams["ordinary-empty-separation"] = [row for row in rows if row["id"] in [labels["empty-separation-withheld"], labels["empty-separation-restart"], labels["empty-separation-stripped"]]]
    for name, stream in streams.items():
        target = SPECIMEN / name; target.mkdir(parents=True, exist_ok=True)
        requests = [{"protocol": PROTOCOL, "request_id": row["id"], "operation": row["operation"], "input": row["input"]} for row in stream]
        (target / "requests.jsonl").write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in requests))
        write_canonical_json(target / "results-derived.json", [row["expected"] for row in stream])
    inventory = {"candidate_pin": PIN, "source_sha256": sha(SOURCE_PATH), "cases": [{"id": row["id"], "path": "../../cases/assessment-source/" + row["id"] + ".json", "raw_sha256": sha(GROUP / (row["id"] + ".json"))} for row in rows]}
    write_canonical_json(SPECIMEN / "case-inventory.json", inventory)
    paths = readback_paths(facts["base"]["definition"])
    obligations = normalized_obligations()["obligations"]
    correspondence = {"candidate_pin": PIN, "status": "PENDING_SOURCE_REVIEW", "source_sha256": sha(SOURCE_PATH), "source_clarifications": [clarification_ref],
        "definition_digest": facts["base"]["definition_digest"], "complete_obligation_ids": [row["id"] for row in obligations],
        "complete_provision_paths": paths, "mappings": [],
        "residue": "No human semantic correspondence acceptance has occurred. Deployment evidence uses a separately labeled synthetic deterministic partition only for mechanical development admission."}
    write_canonical_json(SPECIMEN / "source-correspondence.json", correspondence)
    coverage = {"candidate_pin": PIN, "status": "DEVELOPMENT_SYNTHETIC_COMPONENT_NOT_INDUSTRY_ACCEPTANCE", "source_sha256": sha(SOURCE_PATH), "source_clarifications": [clarification_ref],
        "normalized_clause_count": str(len(obligations)), "native_field_count": "6", "context_field_count": "14", "criterion_count": "5",
        "normative_coverage": [{"requirement": "ASSESS-00" + str(i), "case_ids": [row["id"] for row in rows if "ASSESS-00" + str(i) in row["requirements"]]} for i in range(1, 7)],
        "source_clauses": [{"id": clause["id"], "heading": clause["heading"], "case_ids": [row["id"] for row in rows if
            (clause["heading"].startswith("02.") and (row["id"] == labels["authority-positive"] or row["id"] in [labels["native-" + name] for name in ["recipient", "destination", "subject", "body", "attachment_count", "message_id"]])) or
            (clause["heading"].startswith("10.") and row["id"] in [labels["lifecycle-8"], labels["replay-completion"]]) or
            (not clause["heading"].startswith(("02.", "10.")) and any(ref.startswith("ASSESS-") for ref in row["requirements"]))],
            "host_oracle": "../../review/ASSESSMENT-HOST-EXPECTED-JUDGMENTS.json" if clause["heading"].startswith(("07.", "08.", "09.")) else None,
            "disposition": "EXACT_COMPONENT_CASES_AND_DECLARED_HOST_PROVIDER_PREMISES"} for clause in obligations],
        "host_residue": ["provider authenticity/current truth and complete immutable history", "semantic assessment and citation relevance", "actual human presentation and understanding", "all real writer participation", "protected custody and durable recovery", "actual portal integration and rendering", "lawful disclosure and information flow"],
        "synthetic_deployment_mapping": "Deterministic sparse partition covers every obligation and readback path solely to admit the controlled fictional deployment; source-correspondence remains PENDING."}
    write_canonical_json(SPECIMEN / "source-coverage.json", coverage)
    artifacts = [path for path in SPECIMEN.rglob("*") if path.is_file() and path.name != "artifact-index.json"]
    write_canonical_json(SPECIMEN / "artifact-index.json", {"candidate_pin": PIN, "artifacts": [{"path": str(path.relative_to(SPECIMEN)), "sha256": sha(path)} for path in sorted(artifacts)]})
    print(json.dumps({"candidate_pin": PIN, "cases": len(rows), "labels": labels}, indent=2))


if __name__ == "__main__":
    main()
