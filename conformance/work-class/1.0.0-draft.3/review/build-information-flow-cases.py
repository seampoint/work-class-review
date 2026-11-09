#!/usr/bin/env python3
"""Publish independent source-selected information-flow fixtures without consumers."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

from corpus_common import CASES, CONFORMANCE, ROOT, candidate_pin, canonical_bytes, digest, exact_case, write_canonical_json
from authority_fixture import authority_refusal
from assessment_fixture import authority as assessment_authority, expected_authority as ordinary_expected, rebind_outer
from flow_fixture import (
    BANK_AT, COMPENSATION_AT, BANK_SOURCE, COMPENSATION_SOURCE, SCHEMA,
    attach_bank_flow, attach_compensation_flow, authority_evidence, authority_expected,
    authority_projection, basis, claim, compensation_skeleton, configuration, context,
    create, descriptor, event, expose, flow_check, host_evidence, import_artifact,
    materialize, policy_refusal, read, refusal, refresh_response, replay, request,
    resign_request, transition, refresh_revocations, ordered, fixture_source, access_authority, lifecycle_trace,
)

HERE = Path(__file__).resolve().parent
GROUP = CASES / "information-flow"
SPECIMEN = CONFORMANCE / "specimens/information-flow"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.3"
INVENTORY = HERE / "fixtures/information-flow-source/EXPECTED-CASES.json"
GENERATION_ROOT = Path(os.environ.get("WORK_CLASS_GENERATION_ROOT", str(ROOT / "runs/2026-10-08-overnight"))).resolve()
HOST_JUDGMENTS = INVENTORY.parent / "HOST-EXPECTED-JUDGMENTS-03.json"
HOST_INTERFACE = INVENTORY.parent / "HOST-EXPECTED-INTERFACE-02.md"
GENERIC_SOURCE = CONFORMANCE / "review/fixtures/generic-assessment-and-release-revision1-source.md"


def sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def selected_observation(supplied, req_id):
    return next(row for row in supplied["observations"] if row["query"].get("requirement_id") == req_id)


def set_observation(supplied, req_id, field, value):
    selected = selected_observation(supplied, req_id)
    next(row for row in selected["fields"] if row["name"] == field)["value"]["value"] = value


def source_trace(*, compensation=False, restricted=False, explicit_empty=False, ceiling_all=False, at=None, extra_restriction=False):
    ordinary = compensation_skeleton(now=at or COMPENSATION_AT) if compensation else assessment_authority()[0]
    scope = ordinary["envelope"]["scope"]["id"]
    restriction = "HES-COMPENSATION-INTERNAL" if compensation else "MRB-REPORTING-074"
    at = at or (COMPENSATION_AT if compensation else BANK_AT)
    actor = ordinary["proposal"]["executor"]["actor"]
    config = configuration(principal="HES-01" if compensation else "MRB-US-01",
        registry_id="HES-flow-registry" if compensation else "MRB-flow-registry", scope=scope,
        restriction_id=restriction, meaning="Approved internal compensation planning" if compensation else "Case074 reporting and report existence",
        releasable=compensation, release_role="compensation-director" if compensation else None)
    if extra_restriction:
        config["restrictions"].append({"id": "SECOND-INTERNAL-RESTRICTION", "scope": scope,
            "meaning": "Separate internal customer confidentiality", "releasable": False, "release_role": None})
        config["restrictions"].sort(key=lambda row: row["id"])
    config["clock_source"] = ordinary["clock"]["source"]
    context_id = "compensation-context" if compensation else "protected-bank-context" if restricted else "clean-customer-context"
    purpose = "INTERNAL_COMPENSATION_PLANNING" if compensation else "REPORTING_INVESTIGATION" if restricted else "REQUEST_TRANSFER_FACTS"
    role = ordinary["proposal"]["executor"]["role"]
    ceiling = sorted(row["id"] for row in config["restrictions"]) if compensation or restricted or ceiling_all else []
    stages = []
    supplied, result = create(config, context_id=context_id, actor=actor, scope=scope, purpose=purpose, ceiling=ceiling, at=at)
    stages.append((supplied, result))
    trigger = descriptor("independent-planning-trigger" if compensation else "independent-customer-request", scope=scope)
    supplied, result = read(config, result["state"], trigger, context_id=context_id, role=role,
        event_id="read-original-trigger", at=at, explicit_empty=explicit_empty)
    stages.append((supplied, result))
    source = descriptor("HES-COMP-2026-01" if compensation else "MRB-DECISION-074" if restricted else "MRB-CUSTOMER-FACTS-074",
        scope=scope, restrictions=[restriction] if compensation or restricted else [], compensation=compensation)
    if restricted:
        source.update(provider="case-records.bank.invalid", source="protected-reporting-case", record_type="SAR_DECISION")
    supplied, result = read(config, result["state"], source, context_id=context_id, role=role,
        event_id="read-exact-source", at=at, explicit_empty=explicit_empty)
    stages.append((supplied, result))
    artifact_id = "approved-midpoint" if compensation else "reporting-derived-message" if restricted else "independent-customer-message"
    supplied, result = materialize(config, result["state"], context_id=context_id, artifact_id=artifact_id,
        types=ordinary["work_class"]["types"], native_fields=ordinary["proposal"]["fields"], at=at)
    stages.append((supplied, result))
    outgoing, outgoing_result = (attach_compensation_flow(config, result["state"], ordinary, context_id=context_id, artifact_id=artifact_id)
        if compensation else attach_bank_flow(config, result["state"], ordinary, context_id=context_id, artifact_id=artifact_id))
    return {"configuration": config, "stages": stages, "state": result["state"], "authority": outgoing,
        "authority_result": outgoing_result, "context_id": context_id, "artifact_id": artifact_id,
        "restriction": restriction, "at": at}


def build():
    rows, labels, mappings, phases, streams = [], {}, {}, {}, {}
    def emit(operation, supplied, expected, text, label, *, refs=None, sources=(), phase="transition"):
        case_id = "C3-FLOW-" + str(len(rows) + 1).zfill(3)
        row = exact_case(case_id, operation, supplied, expected, refs or ["FLOW-001", "FLOW-002", "FLOW-003"], text + " Expected judgment was selected from source/contract before consumer execution.")
        rows.append(row); labels[label] = case_id; phases[case_id] = str(phase)
        for source_id in sources:
            mappings.setdefault("FLOW-SOURCE-" + str(source_id).zfill(3), []).append(case_id)
        return row
    def control(supplied, expected, text, label, **kwargs):
        return emit("flow-step", supplied, expected, text, label, **kwargs)
    def deny(supplied, code, text, label, *, shape=False, sources=(), phase="standalone"):
        return control(supplied, refusal(supplied, code, shape=shape), text, label, sources=sources, phase=phase)
    def evaluate(supplied, expected, text, label, *, sources=(), phase="authority", refs=None):
        return emit("evaluate", {"kind": "AUTHORITY", "request": supplied}, expected, text, label,
            sources=sources, phase=phase, refs=refs or ["FLOW-004", "FLOW-005", "FLOW-006", "FLOW-007"])
    def admission(supplied, code, text, label, *, sources=(), phase=2, shape=False):
        expected = {"status": "REFUSED", "code": code, "path": ""} if shape else authority_refusal([], code=code)
        if phase == 5 and "decision_bases" in supplied:
            expected["decision_results"] = ordinary_expected(supplied)["decision_results"]
        return evaluate(supplied, expected, text, label, sources=sources, phase=phase)
    def policy(supplied, reasons, text, label, *, sources=(), standalone=False):
        req = supplied["envelope"]["flow_requirements"][0]
        state = supplied["flow_bases"][0]["state"]
        sender = next(row for row in state["core"]["contexts"] if row["id"] == req["context_id"])
        artifact = next(row for row in state["core"]["artifacts"] if row["id"] == req["artifact_id"])
        recipient = next(row["value"]["value"] for row in supplied["proposal"]["fields"] if row["name"] == req["recipient_field"])
        expected = policy_refusal(supplied, ordinary_expected(supplied), req=req, sender=sender, artifact=artifact,
            recipient=recipient, reasons=reasons)
        evaluate(supplied, expected, text, label, sources=sources, phase=5)
        if standalone:
            selected_event = event(supplied["flow_bases"][0]["configuration"], state, kind="EXPOSE", event_id="refused-" + label,
                payload={"requirement_id": req["id"], "authority_projection": authority_projection(supplied)}, at=supplied["clock"]["instant"])
            flow_input = request(supplied["flow_bases"][0]["configuration"], state, selected_event,
                host_evidence(supplied["flow_bases"][0]["configuration"], selected_event))
            deny(flow_input, "ACCESS_NOT_ESTABLISHED", text + " Standalone refusal preserves exact state and consumes nothing.", label + "-control", sources=sources, phase=5)

    ordinary, ordinary_result, _ = assessment_authority()
    evaluate(ordinary, ordinary_result, "Ordinary input omits flow members and preserves every inherited check and digest.", "ordinary-omitted", sources=[1])
    empty = copy.deepcopy(ordinary); empty["flow_bases"] = []; empty["envelope"]["flow_requirements"] = []; rebind_outer(empty)
    evaluate(empty, authority_expected(empty, ordinary_expected(empty)), "Explicit empty flow bases and declarations add no FLOW check and remain in evidence.", "ordinary-empty", sources=[2])
    clean, protected, comp = source_trace(), source_trace(restricted=True), source_trace(compensation=True)
    traces = {"bank-clean": clean, "bank-protected": protected, "compensation": comp}
    for name, facts in traces.items():
        stream = []
        for index, (supplied, expected) in enumerate(facts["stages"], 1):
            source_ids = ([6] if index == 1 else [29, 74] if name == "bank-clean" else [13, 34] if name == "bank-protected" else [100])
            row = control(supplied, expected, name + " complete positive source-selected stage " + str(index) +
                ". Initial creation is dormant; authorized trigger/source reads precede immutable materialization.", name + "-" + str(index), sources=source_ids)
            stream.append(row)
        streams[name] = stream
    evaluate(clean["authority"], clean["authority_result"], "Independent customer trigger, exact facts, complete assessment and mandatory human approval establish the clean customer route.",
        "bank-clean-authority", sources=[74])
    policy(protected["authority"], ["FLOW_RECIPIENT_NOT_ENTITLED"], "Identical harmless-looking native text still carries the current reporting context; the customer has no reporting entitlement.",
        "bank-protected-denied", sources=[66, 70, 71, 72, 75, 76, 77, 79, 87, 88], standalone=True)
    evaluate(comp["authority"], comp["authority_result"], "The exact approved midpoint, current Director release as sole outer human gate, separate ordinary send grant and current consultant policy establish one disclosure.",
        "compensation-authority", sources=[101, 124, 141])
    for name in ["bank-clean", "compensation"]:
        facts = traces[name]
        supplied, result = expose(facts["configuration"], facts["state"], facts["authority"], facts["authority_result"])
        facts.update(expose_input=supplied, expose_result=result)
        row = control(supplied, result, "The serialized first-exposure transition records POSSIBLE_EXPOSURE before host delivery. No business delivery or acceptance is inferred.",
            name + "-expose", sources=[34, 101, 163, 164, 165, 166, 168, 169], refs=["FLOW-002", "FLOW-003", "FLOW-005"])
        streams[name].append(row)
        replayed = copy.deepcopy(supplied); replayed["state"] = result["state"]; replayed["state_digest"] = result["state_digest"]
        refresh_response(replayed, at="2026-10-08T12:06:00Z" if name == "compensation" else "2026-10-08T10:01:00Z")
        control(replayed, replay(replayed), "Exact event/evidence replay returns the original receipt and current state, with current separate response authority. It permits no new invocation.",
            name + "-expose-replay", sources=[170, 182])
        replay_changed = copy.deepcopy(replayed); replay_changed["event"]["payload"]["requirement_id"] = "changed-requirement"
        replay_changed["host_evidence"] = host_evidence(facts["configuration"], replay_changed["event"]); refresh_response(replay_changed)
        deny(replay_changed, "REPLAY_CONFLICT", "Changed complete bytes under the admitted event id refuse before fresh revision, clock or outgoing authority.",
            name + "-changed-replay", sources=[171], phase="replay")
        used = copy.deepcopy(facts["authority"])
        used["flow_bases"] = [basis(facts["configuration"], result["state"], requirement_id="exact-outgoing-flow", at=facts["at"],
            released_restrictions=[facts["restriction"]] if name == "compensation" else [])]
        policy(used, ["FLOW_CLAIM_CONSUMED"], "Current complete reconstruction retains the claim/intent and consumed release. An exact fresh invocation cannot reuse them, even after later no-effect proof.",
            name + "-consumed", sources=[35, 36, 45, 49, 150, 163, 164, 165, 168, 169, 172, 173, 181], standalone=True)

    base = clean["stages"][1][0]
    base_state = base["state"]
    fresh = copy.deepcopy(base)
    fresh["event"]["id"] = "fresh-missing-host-evidence"
    resign_request(fresh, access=True)
    fresh["host_evidence"]["attestations"] = []; refresh_response(fresh)
    deny(fresh, "EVIDENCE_UNAVAILABLE", "A classified READ needs exact host provenance before ordinary input becomes reachable.", "missing-source-attestation", sources=[31], phase="host evidence")
    wrong = copy.deepcopy(base); wrong["host_evidence"]["attestations"][0]["subject_digest"] = "sha256:" + "0" * 64; refresh_response(wrong)
    deny(wrong, "DEPENDENCY_MISMATCH", "Wrong authenticated classification subject cannot be replaced by a caller's matching-looking source string.", "wrong-source-attestation", sources=[31])
    initial = copy.deepcopy(clean["stages"][0][0]); initial["event"]["payload"]["initial_sources"] = [descriptor("bypass", scope=clean["authority"]["envelope"]["scope"]["id"])]
    deny(initial, "SCHEMA_INVALID", "Creation's closed dormant inventory is exactly empty. Initial prompts or memory must enter through later authorized reads.", "initial-source-bypass", shape=True, sources=[8,9,10,11,12], phase=1)
    asserted = copy.deepcopy(clean["stages"][0][0]); asserted["host_evidence"]["attestations"] = []; refresh_response(asserted)
    deny(asserted, "EVIDENCE_UNAVAILABLE", "An agent assertion of empty history supplies no protected complete-inventory attestation.", "agent-empty-assertion", sources=[7])
    dormant = clean["stages"][0][1]["state"]
    selected_event = event(clean["configuration"], dormant, kind="MATERIALIZE", event_id="dormant-materialize", at=BANK_AT,
        payload={"context_id": clean["context_id"], "artifact_id": "dormant-artifact", "types": clean["authority"]["work_class"]["types"], "fields": clean["authority"]["proposal"]["fields"]})
    supplied = request(clean["configuration"], dormant, selected_event, host_evidence(clean["configuration"], selected_event))
    deny(supplied, "ACCESS_NOT_ESTABLISHED", "A dormant empty context has received no admitted independent work trigger and cannot materialize output.", "dormant-materialize", sources=[6])
    no_state = copy.deepcopy(base); no_state.update(state=None, state_digest=None); no_state["event"].update(expected_revision="0", expected_state_digest=None); resign_request(no_state)
    deny(no_state, "STATE_INVALID", "A null registry can be established only by dormant creation.", "read-without-registry", phase="state")
    duplicate = copy.deepcopy(clean["stages"][0][0]); duplicate["state"] = clean["state"]; duplicate["state_digest"] = digest("flow-state", clean["state"])
    duplicate["event"].update(id="duplicate-context", expected_revision=clean["state"]["core"]["revision"], expected_state_digest=duplicate["state_digest"])
    resign_request(duplicate)
    deny(duplicate, "DEFINITION_CONFLICT", "An admitted context identity cannot be re-created to erase its accumulated state.", "duplicate-context")
    unknown = copy.deepcopy(base); unknown["event"]["payload"]["context_id"] = "unknown-context"; resign_request(unknown)
    deny(unknown, "DEPENDENCY_MISMATCH", "The target context must exist in the reconstructed registry.", "unknown-context")
    revision = copy.deepcopy(base); revision["event"]["expected_revision"] = "0"; resign_request(revision, access=True)
    deny(revision, "REVISION_CONFLICT", "Only one concurrent event can consume the same retained expected revision.", "expected-revision", sources=[46])
    prior_digest = copy.deepcopy(base); prior_digest["event"]["expected_state_digest"] = "sha256:" + "0" * 64; resign_request(prior_digest, access=True)
    deny(prior_digest, "REVISION_CONFLICT", "A fresh event must bind exact current supplied state digest as well as revision.", "expected-state-digest", sources=[46])
    old_clock = copy.deepcopy(base); old_clock["event"]["clock"]["instant"] = "2026-10-08T09:59:59Z"; resign_request(old_clock, access=True)
    deny(old_clock, "CLOCK_INVALID", "Event clock cannot move before the retained last clock.", "event-clock-backwards")
    raw_digest = copy.deepcopy(base); raw_digest["state_digest"] = "sha256:" + "0" * 64; refresh_response(raw_digest)
    deny(raw_digest, "DIGEST_MISMATCH", "Outer state digest must match the supplied complete retained body.", "outer-state-digest")
    for mutation, label, source_ids in [
        (lambda state: state["core"]["contexts"][0]["origins"].clear(), "trim-origins", [59]),
        (lambda state: state["records"].pop(1), "trim-read-history", [60,176]),
        (lambda state: state["records"].reverse(), "reorder-history", [61]),
        (lambda state: state["core"]["claims"].clear(), "trim-claims", [169]),
    ]:
        bad = copy.deepcopy(clean["stages"][-1][0]); mutation(bad["state"])
        bad["state_digest"] = digest("flow-state", bad["state"]); refresh_response(bad)
        deny(bad, "STATE_INVALID", "Rehashed supplied state cannot repair altered complete event reconstruction.", label, sources=source_ids, phase="state")
    ceiling = copy.deepcopy(base); ceiling["event"]["payload"]["source"]["restrictions"] = [clean["restriction"]]; resign_request(ceiling, access=True)
    deny(ceiling, "ACCESS_NOT_ESTABLISHED", "Customer context ceiling admits no reporting restriction, so the entire read is refused before union or delivery.", "ceiling-refusal", sources=[20,21,22,30,32,69,78,83,85])
    scope = copy.deepcopy(base); scope["event"]["payload"]["source"]["scope"] = "other-case"; resign_request(scope, access=True)
    deny(scope, "DEPENDENCY_MISMATCH", "A reporting/factual source for another exact scope cannot enter this context.", "wrong-source-scope", sources=[23,53,54,95])
    unknown_label = copy.deepcopy(base); unknown_label["event"]["payload"]["source"]["restrictions"] = ["unknown-restriction"]; resign_request(unknown_label, access=True)
    deny(unknown_label, "REFERENCE_INVALID", "Every exact source restriction must resolve against the immutable catalogue.", "unknown-restriction", sources=[63])
    denied_access = copy.deepcopy(base)
    access = denied_access["event"]["payload"]["access_authority"]
    for observed in access["observations"]:
        if observed["query"]["purpose"] == "REVOCATION" and observed["query"]["at"] == BANK_AT:
            observed["revoked"] = True
    denied_access["host_evidence"] = host_evidence(clean["configuration"], denied_access["event"]); refresh_response(denied_access)
    deny(denied_access, "ACCESS_NOT_ESTABLISHED", "Current ordinary read authority fails before any input, union or claim becomes reachable.", "revoked-read-authority", sources=[19,26])
    reader = copy.deepcopy(base)
    for observed in reader["response_authority"]["observations"]:
        if observed["query"]["purpose"] == "REVOCATION" and observed["query"]["at"] == BANK_AT:
            observed["revoked"] = True
    deny(reader, "ACCESS_NOT_ESTABLISHED", "An unentitled current reader receives only a generic refusal without state or receipt.", "response-reader-refused", shape=True, sources=[50,98])

    for omitted in [True, False]:
        supplied = copy.deepcopy(clean["authority"])
        if omitted:
            supplied.pop("flow_bases")
        else:
            supplied["flow_bases"] = []
        admission(supplied, "EVIDENCE_UNAVAILABLE", "The selected flow requirement requires its complete exact registry basis; an absent and an empty inventory both omit it.",
            "selected-basis-" + ("omitted" if omitted else "empty"), sources=[4 if omitted else 5,127,195])
    unrequested = copy.deepcopy(ordinary); unrequested["flow_bases"] = copy.deepcopy(clean["authority"]["flow_bases"])
    admission(unrequested, "DEPENDENCY_MISMATCH", "Nonempty evidence cannot introduce an undeclared flow requirement.", "unrequested-basis", sources=[3])
    mismatch = copy.deepcopy(clean["authority"]); mismatch["proposal"]["executor"]["actor"] = "another-actor"
    admission(mismatch, "BINDING_MISMATCH", "The actual executor actor must equal the selected sender context actor.", "sender-actor-binding", phase=3)
    mismatch = copy.deepcopy(clean["authority"]); mismatch["flow_bases"][0]["state_digest"] = "sha256:" + "0" * 64
    admission(mismatch, "DIGEST_MISMATCH", "The flow basis carries the complete exact state, whose digest must agree before current policy.", "basis-state-digest", phase=2)
    for name, status in [("unavailable", "UNAVAILABLE"), ("conflicting", "CONFLICTING")]:
        supplied = copy.deepcopy(comp["authority"]); supplied["flow_bases"][0]["selection"]["status"] = status
        policy(supplied, ["FLOW_UNAVAILABLE"], "Authenticated current registry selection is " + status + "; historical self-consistency does not establish current reliance.", "selection-" + name, sources=[47], standalone=True)
    supplied = copy.deepcopy(comp["authority"]); supplied["flow_bases"][0]["selection"]["at"] = "2026-10-08T12:04:59Z"
    policy(supplied, ["FLOW_STALE"], "Available registry selection is not at the exact accepted current query instant.", "selection-stale", sources=[47], standalone=True)
    policy_mutations = [
        ("policy-digest", "current-flow-policy", "policy_digest", "sha256:" + "0" * 64, "FLOW_DEPENDENCY_CHANGED", [159]),
        ("recipient", "current-flow-recipient", "recipient", "other-consultant", "FLOW_DEPENDENCY_CHANGED", [156]),
        ("channel", "current-flow-recipient", "channel", "other-channel", "FLOW_DEPENDENCY_CHANGED", [112]),
        ("purpose", "current-flow-recipient", "purpose", "other-engagement", "FLOW_DEPENDENCY_CHANGED", [113]),
        ("recipient-effective", "current-flow-recipient", "effective", False, "FLOW_RECIPIENT_NOT_ENTITLED", [156]),
        ("selected-act-id", "current-release-selection", "act_id", "new-release", "FLOW_RELEASE_NOT_ESTABLISHED", [153]),
        ("selected-act-digest", "current-release-selection", "act_digest", "sha256:" + "0" * 64, "FLOW_RELEASE_NOT_ESTABLISHED", [153]),
        ("selected-subject", "current-release-selection", "subject_digest", "sha256:" + "0" * 64, "FLOW_RELEASE_NOT_ESTABLISHED", [155]),
        ("selected-claim", "current-release-selection", "claim_id", "another-claim", "FLOW_RELEASE_NOT_ESTABLISHED", [155]),
        ("effective-act-id", "current-release-effectiveness", "act_id", "new-release", "FLOW_RELEASE_NOT_ESTABLISHED", [154]),
        ("release-effective", "current-release-effectiveness", "effective", False, "FLOW_RELEASE_NOT_ESTABLISHED", [135,149,151,154,175]),
    ]
    for label, req_id, field, value, reason, sources in policy_mutations:
        supplied = copy.deepcopy(comp["authority"]); set_observation(supplied, req_id, field, value)
        policy(supplied, [reason], "The complete current " + req_id + " field " + field + " differs or withholds; earlier complete bodies remain immutable.",
            "current-" + label, sources=sources, standalone=True)
    supplied = copy.deepcopy(comp["authority"]); supplied["flow_bases"][0]["selection"]["status"] = "UNAVAILABLE"
    set_observation(supplied, "current-flow-recipient", "effective", False); set_observation(supplied, "current-release-effectiveness", "effective", False)
    policy(supplied, ["FLOW_UNAVAILABLE", "FLOW_RECIPIENT_NOT_ENTITLED", "FLOW_RELEASE_NOT_ESTABLISHED"],
        "Usable complete rows retain every independently checkable current failure, with exact deterministic failed-check union.", "multiple-current-failures", sources=[201], standalone=True)
    for field in ["subject", "body", "recipient", "destination", "attachment_count", "message_id"]:
        supplied = copy.deepcopy(comp["authority"])
        native = next(row for row in supplied["proposal"]["fields"] if row["name"] == field)["value"]
        native["value"] = "1" if field == "attachment_count" else native["value"] + " "
        admission(supplied, "BINDING_MISMATCH", "Changed exact native " + field + " no longer equals the immutable selected artifact or signed release subject.",
            "compensation-native-" + field, sources=[106,107,108,109,110,111,112,123], phase=3)
    for field in ["instance", "occurrence"]:
        supplied = copy.deepcopy(comp["authority"]); supplied["proposal"][field] += "-changed"
        admission(supplied, "BINDING_MISMATCH", "The locally computed subject binds exact " + field + "; the retained release cannot move to new work.",
            "compensation-" + field, sources=[116 if field == "instance" else 117], phase=3)
    for field in ["purpose", "claim_id", "intent_id"]:
        supplied = copy.deepcopy(comp["authority"]); supplied["envelope"]["flow_requirements"][0][field] += "-changed"; rebind_outer(supplied)
        admission(supplied, "BINDING_MISMATCH", "The computed local disclosure subject includes " + field + "; a matching old literal cannot restore it.",
            "compensation-bound-" + field, sources=[113,171,172], phase=3)
    for name in ["literal", "proposal-field"]:
        supplied = copy.deepcopy(comp["authority"])
        selected = next(row for row in supplied["envelope"]["decision_requirements"][0]["context_bindings"] if row["field"] == "disclosure_subject")
        selected["value"] = ({"kind": "LITERAL", "value": copy.deepcopy(next(row for row in supplied["decision_bases"][0]["evidence"]["authority_input"]["proposal"]["fields"] if row["name"] == "disclosure_subject")["value"])}
            if name == "literal" else {"kind": "PROPOSAL_FIELD", "field": "message_id"})
        rebind_outer(supplied)
        admission(supplied, "UNSUPPORTED_RELATION", "A release needs exactly one computed FLOW_DISCLOSURE binding; a copied literal or proposal field is insufficient.",
            "release-binding-" + name, sources=[125 if name == "literal" else 126,139,140], phase=2)
    supplied = copy.deepcopy(comp["authority"]); supplied["decision_bases"] = []
    admission(supplied, "EVIDENCE_UNAVAILABLE", "Model PASS, manager request or ordinary approval cannot supply the distinct selected Director release.", "missing-director-release", sources=[102,103,104])
    supplied = copy.deepcopy(comp["authority"]); supplied["flow_bases"][0]["released_restrictions"] = []
    admission(supplied, "UNSUPPORTED_RELATION", "The first profile selects a release requirement exactly when its restriction subset is nonempty.", "empty-selected-release", sources=[118], phase=2)
    supplied = copy.deepcopy(comp["authority"])
    leaf = supplied["decision_bases"][0]["evidence"]["authority_input"]
    selected = next(row for row in supplied["envelope"]["source_observation_requirements"] if row["id"] == "release-record"); selected["record_id"] = None; rebind_outer(supplied)
    admission(supplied, "UNSUPPORTED_RELATION", "Release issuance identity uses the ordinary fixed nonnull record identity; the assessment exception does not apply.", "release-null-record-id", sources=[128], phase=2)
    supplied = copy.deepcopy(comp["authority"]); supplied["decision_bases"][0]["evidence"]["decision_act_digest"] = "sha256:" + "0" * 64
    admission(supplied, "BINDING_MISMATCH", "The wrapper must name the complete authenticated selected human act.", "release-wrapper-digest", sources=[129], phase=3)
    supplied = copy.deepcopy(comp["authority"]); leaf = supplied["decision_bases"][0]["evidence"]["authority_input"]; leaf["returns"] = []
    leaf["host_selection"]["authenticated_records"] = [row for row in leaf["host_selection"]["authenticated_records"] if row["kind"] != "RETURN"]
    admission(supplied, "EVIDENCE_UNAVAILABLE", "No attributable authenticated human return supplies the selected release.", "release-no-return", sources=[130], phase=4)

    # A valid import retains both receiver access and sender transfer, in that order.
    facts = protected; state = facts["state"]
    supplied, created = create(facts["configuration"], state, context_id="reporting-handoff", actor="filing-preparation-agent-01",
        scope=facts["authority"]["envelope"]["scope"]["id"], purpose="REPORTING_PREPARATION", ceiling=[facts["restriction"]])
    control(supplied, created, "A receiving reporting context starts dormant with an exact protected inventory attestation.", "handoff-create", sources=[68])
    supplied, imported = import_artifact(facts["configuration"], created["state"], sender_id=facts["context_id"], receiver_id="reporting-handoff",
        artifact_id=facts["artifact_id"], event_id="reporting-handoff-import", receiver_role="filing-preparation-agent", sender_role="investigation-owner")
    control(supplied, imported, "Whole historical artifact and current sender origins/restrictions enter the receiver atomically. Both complete current authorities are retained, receiver then sender.",
        "handoff-import", sources=[65,67,68,71,81,82])
    streams["reporting-handoff"] = [next(row for row in rows if row["id"] == labels["handoff-create"]), next(row for row in rows if row["id"] == labels["handoff-import"])]
    for suffix, field in [("receiver", "access_authority"), ("sender", "transfer_authority")]:
        bad = copy.deepcopy(supplied)
        for observed in bad["event"]["payload"][field]["observations"]:
            if observed["query"]["purpose"] == "REVOCATION" and observed["query"]["at"] == BANK_AT:
                observed["revoked"] = True
        bad["host_evidence"] = host_evidence(facts["configuration"], bad["event"]); refresh_response(bad)
        deny(bad, "ACCESS_NOT_ESTABLISHED", "Current " + suffix + " authority withholds the entire import; receiver state, claim and content remain unchanged.",
            "handoff-" + suffix + "-revoked", sources=[24,25,69])
    imported_replay = copy.deepcopy(supplied); imported_replay.update(state=imported["state"], state_digest=imported["state_digest"]); refresh_response(imported_replay)
    control(imported_replay, replay(imported_replay), "Exact import replay is evidence-only and cannot deliver the handoff twice.", "handoff-replay", sources=[40])

    # Optional empty and omitted access carriers remain different retained evidence.
    empty_trace = source_trace(explicit_empty=True)
    for index in [1, 2]:
        supplied, result = empty_trace["stages"][index]
        control(supplied, result, "Explicit empty access flow carriers remain complete retained ordinary evidence without adding a recursive profile.",
            "access-explicit-empty-" + str(index), sources=[2,204])
    replayed = copy.deepcopy(empty_trace["stages"][2][0]); state = empty_trace["state"]
    replayed.update(state=state, state_digest=digest("flow-state", state)); refresh_response(replayed)
    control(replayed, replay(replayed), "Restart/replay reconstructs exact empty optional-member presence and every authority evidence digest.", "empty-access-replay", sources=[204])
    stripped = copy.deepcopy(replayed)
    stripped["state"]["records"][1]["event"]["payload"]["access_authority"].pop("flow_bases")
    stripped["state_digest"] = digest("flow-state", stripped["state"]); refresh_response(stripped)
    deny(stripped, "STATE_INVALID", "Resealing only the outer state cannot repair stripped exact empty retained evidence.", "stripped-empty-access", sources=[204], phase="state")
    mismatch_clock = copy.deepcopy(comp["expose_input"]); mismatch_clock["event"]["clock"]["instant"] = "2026-10-08T12:05:01Z"
    mismatch_clock["host_evidence"] = host_evidence(comp["configuration"], mismatch_clock["event"]); refresh_response(mismatch_clock)
    deny(mismatch_clock, "BINDING_MISMATCH", "EXPOSE's expanded authority clock must equal the complete event clock, not merely remain available.", "expose-clock-binding", phase=3)
    illegal_projection = copy.deepcopy(comp["expose_input"])
    illegal_projection["event"]["payload"]["authority_projection"]["flow_bases"][0]["state"] = copy.deepcopy(comp["state"])
    deny(illegal_projection, "SCHEMA_INVALID", "The closed historical exposure projection omits exactly state; recursively embedding it is a shape violation.", "recursive-exposure-projection", shape=True, phase=1)
    # Successor04 expansion. Earlier 113 case bytes remain independently frozen.
    for source_id, role, purpose in [
        (14, "filing-preparation-agent", "REPORTING_PREPARATION"),
        (15, "human-sar-review-officer", "REPORTING_HUMAN_REVIEW"),
        (16, "filing-submission-agent", "REPORTING_SUBMISSION"),
        (17, "bsa-officer", "REPORTING_OVERSIGHT"),
        (18, "reporting-records-custodian", "REPORTING_RECONCILIATION"),
        (84, "protected-evaluator", "REPORTING_EVALUATION"),
        (86, "protected-internal-log", "REPORTING_DIAGNOSTICS"),
        (96, "reporting-records-custodian", "REPORTING_AUDIT_EXPORT"),
    ]:
        config = protected["configuration"]
        scope = protected["authority"]["envelope"]["scope"]["id"]
        _, seeded = create(config, context_id="role-" + str(source_id), actor=role + "-01", scope=scope, purpose=purpose, ceiling=[protected["restriction"]])
        source = descriptor("MRB-SAR-074-" + str(source_id), scope=scope, restrictions=[protected["restriction"]])
        source.update(provider="case-records.bank.invalid", source="protected-reporting-case", record_type="SAR_PACKAGE")
        supplied, expected = read(config, seeded["state"], source, context_id="role-" + str(source_id), role=role, event_id="read-role-" + str(source_id))
        control(supplied, expected, "The fictional selected ordinary remit explicitly authorizes this role, exact case, protected route and purpose. Registry union precedes this one delivery; it does not infer role entitlement.",
            "role-read-" + str(source_id), sources=[source_id])
    repeated, repeated_result = read(protected["configuration"], protected["state"], protected["stages"][2][0]["event"]["payload"]["source"],
        context_id=protected["context_id"], role="investigation-owner", event_id="repeat-same-source")
    control(repeated, repeated_result, "A distinct authorized delivery of the same immutable source advances context revision and records a new intent/claim, while restriction and origin sets remain unique.",
        "repeat-immutable-source", sources=[52])
    corrected_source = copy.deepcopy(protected["stages"][2][0]["event"]["payload"]["source"])
    corrected_source["revision"] = "revision-2"; corrected_source["content_digest"] = "sha256:" + "2" * 64
    corrected, corrected_result = read(protected["configuration"], protected["state"], corrected_source,
        context_id=protected["context_id"], role="investigation-owner", event_id="read-corrected-source")
    control(corrected, corrected_result, "A new immutable provider revision adds its origin without rewriting the prior delivered source or restrictions. Current use still requires selected source guards.",
        "new-source-revision", sources=[64])
    conflict_source = copy.deepcopy(protected["stages"][2][0]["event"]["payload"]["source"]); conflict_source["content_digest"] = "sha256:" + "3" * 64
    conflict, _ = read(protected["configuration"], protected["state"], conflict_source,
        context_id=protected["context_id"], role="investigation-owner", event_id="conflicting-source-issuance")
    deny(conflict, "DEPENDENCY_MISMATCH", "Identical immutable provider/source/type/id/revision/scope coordinates cannot carry different complete bytes.",
        "conflicting-source-issuance", sources=[62])
    for member, new_value, source_id in [("revision", "revision-2", 42), ("content_digest", "sha256:" + "4" * 64, 43)]:
        old_read = copy.deepcopy(protected["stages"][2][0]); old_read.update(state=protected["state"], state_digest=digest("flow-state", protected["state"]))
        old_read["event"]["payload"]["source"][member] = new_value
        old_read["host_evidence"] = host_evidence(protected["configuration"], old_read["event"]); refresh_response(old_read)
        deny(old_read, "REPLAY_CONFLICT", "Changing source " + member + " under the old event/claim cannot authorize another read or select a corrected body.",
            "changed-read-" + member, sources=[source_id], phase="replay")
    old_read = copy.deepcopy(protected["stages"][2][0]); old_read.update(state=protected["state"], state_digest=digest("flow-state", protected["state"]))
    old_read["event"]["payload"]["context_id"] = "another-receiver"; old_read["host_evidence"] = host_evidence(protected["configuration"], old_read["event"]); refresh_response(old_read)
    deny(old_read, "REPLAY_CONFLICT", "A read claim cannot be replayed into another receiving context.", "changed-read-destination", sources=[44], phase="replay")
    for member in ["claim_id", "intent_id"]:
        bad = copy.deepcopy(repeated); bad["event"]["payload"][member] = protected["state"]["core"]["claims"][0]["id" if member == "claim_id" else "intent_id"]
        resign_request(bad, access=True)
        deny(bad, "DEPENDENCY_MISMATCH", "Global delivery " + member + " cannot be reused under a fresh event or claim.", "reused-read-" + member, sources=[45])
    union = source_trace(restricted=True, extra_restriction=True)
    extra = descriptor("separate-customer-record", scope=union["authority"]["envelope"]["scope"]["id"], restrictions=["SECOND-INTERNAL-RESTRICTION"])
    supplied, expected = read(union["configuration"], union["state"], extra, context_id=union["context_id"], role="investigation-owner", event_id="union-second-restriction")
    control(supplied, expected, "The second authorized origin adds its immutable restriction without replacing the first restriction or any old origin.", "second-restriction-union", sources=[51])
    old_clean = source_trace(ceiling_all=True)
    restricted_source = descriptor("MRB-DECISION-074-later", scope=old_clean["authority"]["envelope"]["scope"]["id"], restrictions=[old_clean["restriction"]])
    supplied, tainted = read(old_clean["configuration"], old_clean["state"], restricted_source,
        context_id=old_clean["context_id"], role="investigation-owner", event_id="sender-later-restricted-read")
    control(supplied, tainted, "The sender's later restricted read changes current context without rewriting its historical clean artifact.", "old-clean-new-read", sources=[73])
    old_sender = copy.deepcopy(old_clean["authority"])
    old_sender["flow_bases"] = [basis(old_clean["configuration"], tainted["state"], requirement_id="exact-outgoing-flow", at=BANK_AT)]
    policy(old_sender, ["FLOW_RECIPIENT_NOT_ENTITLED"], "Current sender restrictions govern selection and the send trigger, so a historical clean artifact cannot authorize the customer route.",
        "old-clean-current-sender-denied", sources=[73,75,76,77,79], standalone=True)
    for source_id, record in [(142,"protected-approval-evidence"),(158,"later-internal-planning-read")]:
        source = descriptor(record, scope=comp["authority"]["envelope"]["scope"]["id"], restrictions=[comp["restriction"]], compensation=True)
        supplied, advanced = read(comp["configuration"], comp["state"], source, context_id=comp["context_id"], role="hr-compensation-analysis-agent", event_id="sender-read-" + str(source_id), at=COMPENSATION_AT)
        control(supplied, advanced, "Additional reachable input advances the sender context even when its restriction set is unchanged.", "release-context-read-" + str(source_id), sources=[source_id])
        changed = copy.deepcopy(comp["authority"]); changed["flow_bases"] = [basis(comp["configuration"], advanced["state"], requirement_id="exact-outgoing-flow", at=COMPENSATION_AT, released_restrictions=[comp["restriction"]])]
        admission(changed, "BINDING_MISMATCH", "The earlier release signed the prior exact context. New origins and context revision change the computed subject before human act/current policy checks.",
            "release-context-binding-" + str(source_id), sources=[source_id], phase=3)
    supplied, receiver = create(comp["configuration"], comp["state"], context_id="new-internal-compensation-agent", actor="compensation-second-agent-01",
        scope=comp["authority"]["envelope"]["scope"]["id"], purpose="INTERNAL_COMPENSATION_PLANNING", ceiling=[comp["restriction"]], at=COMPENSATION_AT)
    imported_input, imported = import_artifact(comp["configuration"], receiver["state"], sender_id=comp["context_id"], receiver_id="new-internal-compensation-agent",
        artifact_id=comp["artifact_id"], event_id="import-compensation-after-release", receiver_role="hr-compensation-analysis-agent", sender_role="hr-compensation-analysis-agent", at=COMPENSATION_AT)
    control(imported_input, imported, "The exact midpoint artifact imports with its original internal restrictions and origins. Its prior external release cannot make this receiving context unrestricted.", "released-artifact-stays-restricted", sources=[80,121,122])
    for field in ["revision", "id"]:
        supplied = copy.deepcopy(comp["authority"]); supplied["envelope"]["flow_requirements"][0]["policy"][field] += "-changed"; rebind_outer(supplied)
        admission(supplied, "BINDING_MISMATCH", "The computed signed disclosure subject covers the complete policy digest, including its " + field + ".", "release-policy-" + field, sources=[115], phase=3)
    for req_id, name, value, source_id in [("current-compensation-source","revision","revision-2",157),
            ("current-compensation-source","source_digest","sha256:" + "5"*64,114),
            ("current-director-remit","no_applicable_revocation",False,147)]:
        supplied = copy.deepcopy(comp["authority"]); set_observation(supplied,req_id,name,value)
        failed = [{"purpose":"SOURCE_OBSERVATION","subject_digest":digest("authority-envelope",supplied["envelope"]),
            "requirement_ref":req_id,"at":COMPENSATION_AT,"reason":"SOURCE_OBSERVATION_RELATIONS"}]
        expected = authority_refusal(failed); expected["decision_results"] = ordinary_expected(supplied)["decision_results"]
        evaluate(supplied,expected,"The separately selected current " + req_id + " guard fails. A retained release cannot waive the current source/remit condition.",
            "ordinary-current-" + req_id + "-" + name,sources=[source_id],phase=5)
    regrant = copy.deepcopy(comp["authority"]); selected_observation(regrant,"current-director-remit")["revision"]="remit-regrant-revision-2"
    evaluate(regrant,authority_expected(regrant,ordinary_expected(regrant),req=regrant["envelope"]["flow_requirements"][0],
        sender=next(row for row in comp["state"]["core"]["contexts"] if row["id"]==comp["context_id"]),
        artifact=comp["state"]["core"]["artifacts"][0],recipient="consultant-01"),
        "A truthful current remit regrant can restore this still selected, effective, unwithdrawn, unused and unexpired exact release. It changes no old act or producer restriction.",
        "unused-release-current-remit-regrant",sources=[148])
    for label, target, limit, source_id in [("outer-byte-limit","outer",1048576,187),("leaf-byte-limit","leaf",262144,188)]:
        supplied=copy.deepcopy(comp["authority"])
        selected=supplied if target=="outer" else supplied["decision_bases"][0]["evidence"]["authority_input"]
        selected["source"]["obligations"][0]["text"] += "x"*(limit+1)
        rebind_outer(selected);refresh_revocations(selected)
        if target=="leaf":
            supplied["decision_bases"][0]["evidence"]["decision_act_digest"]=ordinary_expected(selected,leaf=True)["decision_act_digest"]
            supplied["envelope"]["decision_requirements"][0]["envelope_digest"]=digest("authority-envelope",selected["envelope"])
            rebind_outer(supplied);refresh_revocations(supplied)
        admission(supplied,"LIMIT_EXCEEDED","Complete supported-shape " + target + " authority exceeds its independently applicable canonical-byte ceiling before current policy.",label,sources=[source_id],phase=2)
    supplied=copy.deepcopy(comp["authority"])
    supplied["envelope"]["decision_requirements"]=[{**copy.deepcopy(supplied["envelope"]["decision_requirements"][0]),"id":"decision-"+str(i).zfill(2)} for i in range(17)]
    admission(supplied,"SCHEMA_INVALID","Seventeen independent declarations exceed the closed16-member shape before missing current evidence is evaluated.","seventeen-decisions",sources=[190],phase=1,shape=True)
    supplied=copy.deepcopy(comp["authority"]);supplied["unexpected_member"]=True;supplied["decision_bases"]=[]
    admission(supplied,"SCHEMA_INVALID","Malformed outer shape precedes missing selected release evidence.","schema-before-missing-release",sources=[193],phase=1,shape=True)
    supplied=copy.deepcopy(comp["authority"])
    computed=next(row for row in supplied["envelope"]["decision_requirements"][0]["context_bindings"] if row["field"]=="disclosure_subject")["value"]
    computed.update(type_ref="COUNT",requirement_id="unknown-flow-requirement");rebind_outer(supplied)
    admission(supplied,"TYPE_INVALID","The directly known nominal bridge is incompatible before the unknown computed requirement reference is resolved.","known-type-before-reference",sources=[194],phase=1)
    supplied=copy.deepcopy(comp["authority"]);selected_observation(supplied,"current-release-effectiveness")["fields"][1 if selected_observation(supplied,"current-release-effectiveness")["fields"][1]["name"]=="effective" else 0]["value"]["value"]=False
    supplied["observations"]=[row for row in supplied["observations"] if row["query"].get("requirement_id")!="current-flow-policy"]
    admission(supplied,"EVIDENCE_UNAVAILABLE","The complete mandatory current query inventory is admitted before a false effectiveness value is interpreted.","missing-query-before-effectiveness",sources=[198],phase=5)
    for malformed in [False,True]:
        supplied=copy.deepcopy(comp["authority"]);supplied["clock"].update(status="UNAVAILABLE",instant=None)
        supplied["decision_bases"][0]["evidence"]["authority_input"]["clock"].update(status="UNAVAILABLE",instant=None)
        if malformed:
            selected_observation(supplied,"current-flow-recipient")["fields"][0]["value"]["type_ref"]="COUNT"
            selected_observation(supplied,"current-flow-recipient")["fields"][0]["value"]["value"]="not-a-decimal"
            admission(supplied,"TYPE_INVALID","A directly malformed known scalar precedes the unavailable-clock current-policy shortcut.","unavailable-clock-malformed-source",sources=[199],phase=1)
        else:
            expected=authority_refusal([],reasons=["CLOCK_UNAVAILABLE"])
            evaluate(supplied,expected,"Unavailable clock does not infer current state; it produces only CLOCK_UNAVAILABLE and empty failed checks after directly checkable admission.",
                "unavailable-clock",sources=[162,200],phase=5)
    # Additional exact boundaries, independent phase precedence and finite histories.
    expired_read = copy.deepcopy(clean["stages"][1][0])
    selected_access = expired_read["event"]["payload"]["access_authority"]
    selected_access["envelope"]["temporal_validity"]["valid_until"] = BANK_AT
    rebind_outer(selected_access); refresh_revocations(selected_access)
    expired_read["host_evidence"] = host_evidence(clean["configuration"], expired_read["event"]); refresh_response(expired_read)
    deny(expired_read, "ACCESS_NOT_ESTABLISHED", "Read permission's exclusive end withholds at the exact attempted delivery instant without a new writer event.", "read-exact-expiry", sources=[27])
    no_send = copy.deepcopy(comp["authority"])
    selected_revocation = next(row for row in no_send["observations"] if row["query"]["purpose"] == "REVOCATION" and row["query"]["subject_digest"] == digest("authority-envelope", no_send["envelope"]))
    selected_revocation["revoked"] = True
    expected = authority_refusal([{"purpose":"REVOCATION","subject_digest":selected_revocation["query"]["subject_digest"],
        "requirement_ref":selected_revocation["query_digest"],"at":COMPENSATION_AT,"reason":"REVOKED"}])
    expected["decision_results"] = ordinary_expected(no_send)["decision_results"]
    evaluate(no_send, expected, "The release remains independently valid, but the separate ordinary send envelope is currently revoked. Release cannot grant execution authority.", "release-without-current-send-authority", sources=[105], phase=5)
    at_start=source_trace(compensation=True,at="2026-10-08T12:00:00Z")
    evaluate(at_start["authority"],at_start["authority_result"],"The selected release interval includes its exact start; all retained signing/return and current inputs are at or before that instant.","release-inclusive-start",sources=[143])
    supplied,expected=expose(at_start["configuration"],at_start["state"],at_start["authority"],at_start["authority_result"],event_id="release-start-exposure")
    control(supplied,expected,"At the inclusive start one exact first exposure can consume the selected release.","release-start-exposure",sources=[143])
    too_early=source_trace(compensation=True,at="2026-10-08T11:59:59Z")
    admission(too_early["authority"],"ACT_NOT_AUTHORIZED","The selected release act and returned evidence occur at12:00, after this evaluation. Historical act/return admission withholds before current interval reliance.","release-before-start",sources=[144],phase=4)
    at_end=source_trace(compensation=True,at="2026-10-08T13:00:00Z")
    supplied,_=expose(at_end["configuration"],at_end["state"],at_end["authority"],at_end["authority_result"],event_id="release-end-exposure")
    deny(supplied,"ACCESS_NOT_ESTABLISHED","The selected release and current Director reliance end exactly at13:00. No new exposure or consumption occurs at that exclusive end.","release-exclusive-end",sources=[145],phase=5)
    source_conflict=copy.deepcopy(comp["authority"])
    observed=selected_observation(source_conflict,"current-flow-policy")
    observed.update(status="CONFLICT",as_of=None,revision=None,fields=[],relations=[])
    observed.pop("provider_record_id")
    expected=authority_refusal([{"purpose":"SOURCE_OBSERVATION","subject_digest":digest("authority-envelope",source_conflict["envelope"]),
        "requirement_ref":"current-flow-policy","at":COMPENSATION_AT,"reason":"SOURCE_OBSERVATION_CONFLICT"}])
    expected["decision_results"]=ordinary_expected(source_conflict)["decision_results"]
    evaluate(source_conflict,expected,"A conflicting source group is unusable; it contributes its ordinary source failure and supplies no invented policy digest for a FLOW_DEPENDENCY_CHANGED comparison.","unusable-policy-conflict",sources=[202],phase=5)
    wrong_subject=copy.deepcopy(comp["authority"])
    human=wrong_subject["decision_bases"][0]["evidence"];leaf=human["authority_input"]
    next(row for row in leaf["proposal"]["fields"] if row["name"]=="disclosure_subject")["value"]["value"]="sha256:"+"6"*64
    next(row for row in leaf["acts"] if row["kind"]=="INSTANCE_DECISION")["disposition"]="REJECT"
    rebind_outer(leaf);refresh_revocations(leaf);human["decision_act_digest"]=ordinary_expected(leaf,leaf=True)["decision_act_digest"]
    admission(wrong_subject,"BINDING_MISMATCH","The locally computed disclosure binding fails before the selected human non-ACCEPT disposition is considered.","computed-binding-before-rejected-act",sources=[196],phase=3)
    from holdings_fixture import lifecycle_base as holdings_lifecycle_base
    from lifecycle_factory import stateful_refusal, step_input as lifecycle_step_input
    combined=holdings_lifecycle_base(requirement_count=32,source_count=33)
    emit("step",lifecycle_step_input(combined,combined["clock_result"]["state"],combined["proposal_event"]),
        stateful_refusal(combined["clock_result"]["state"],"LIMIT_EXCEEDED"),
        "The inherited shared source-plus-holdings projection is65 members. The same64-member combined bound applies before a lifecycle permit can exist; adding flow cannot enlarge it.",
        "shared-combined-projection-limit",refs=["FLOW-006","HOLD-007"],sources=[189],phase=2)
    catalogue=copy.deepcopy(clean["stages"][0][0])
    catalogue["configuration"]["restrictions"]=[{**copy.deepcopy(catalogue["configuration"]["restrictions"][0]),"id":"restriction-"+str(i).zfill(2)} for i in range(65)]
    deny(catalogue,"SCHEMA_INVALID","The immutable catalogue has65 restrictions and exceeds the closed64-member shape. A valid configuration cannot later accumulate65 distinct restriction ids.","catalogue-65-restrictions",shape=True,sources=[185],phase=1)
    from flow_fixture import event_capacity, origin_capacity
    exhausted=event_capacity(clean)
    cap_event=event(clean["configuration"],exhausted,kind="READ",event_id="over-capacity-read",at=BANK_AT,
        payload={"context_id":"capacity-00","intent_id":"over-capacity-intent","claim_id":"over-capacity-claim","source":descriptor("new-capacity-source",scope=clean["authority"]["envelope"]["scope"]["id"])})
    receiver=next(row for row in exhausted["core"]["contexts"] if row["id"]=="capacity-00")
    cap_event["payload"]["access_authority"]=access_authority(clean["configuration"],cap_event,receiver,role="customer-message-agent",source=fixture_source(control=True))[0]
    supplied=request(clean["configuration"],exhausted,cap_event,host_evidence(clean["configuration"],cap_event))
    deny(supplied,"LIMIT_EXCEEDED","A fully reconstructed128-event history cannot retain a fresh read, union or claim. No provider is invoked.","event-capacity-fresh-read",sources=[183])
    historic=copy.deepcopy(exhausted["records"][16])
    supplied=request(clean["configuration"],exhausted,historic["event"],historic["host_evidence"])
    control(supplied,replay(supplied),"At event capacity exact historical READ replay remains evidence-only and retains complete current state without another delivery.","event-capacity-replay",sources=[41,191])
    exhausted_authority,_=attach_bank_flow(clean["configuration"],exhausted,assessment_authority()[0],context_id="capacity-00",artifact_id="capacity-artifact-63")
    if len(canonical_bytes(exhausted_authority)) <= 1048576:
        policy(exhausted_authority,["FLOW_CAPACITY_EXHAUSTED"],"A valid exact current authority basis cannot promise a claim when its complete registry has128 retained events.","event-capacity-current-authority",sources=[192])
    else:
        admission(exhausted_authority,"LIMIT_EXCEEDED","This complete valid128-event registry makes the outgoing authority exceed its inherited byte limit before current flow capacity can be evaluated.","event-capacity-authority-byte-precedence",sources=[192],phase=2)
    origin_state=origin_capacity(clean)
    supplied,_=import_artifact(clean["configuration"],origin_state,sender_id="origin-sender",receiver_id="origin-receiver",artifact_id="origin-sender-artifact",
        event_id="origin-overflow-import",receiver_role="customer-message-agent",sender_role="customer-message-agent")
    deny(supplied,"LIMIT_EXCEEDED","The receiver has64 exact origins and the sender contributes a distinct65th. Atomic import refuses before exposure and preserves both contexts and every claim.","origin-capacity-import",sources=[184])
    complete = lifecycle_trace(comp)
    lifecycle_rows = []
    for index, (operation, supplied, expected) in enumerate(complete["stages"], 1):
        lifecycle_rows.append(emit(operation, supplied, expected,
            "Complete source-selected compensation lifecycle stage " + str(index) + ". Actual runtime occurrence is computed before Director signing; fresh dispatch authority and exact sources/flows fence precede possible exposure.",
            "compensation-lifecycle-" + str(index), refs=["FLOW-005", "FLOW-006", "FLOW-007", "LIFE-009B"], sources=[101,146,174,203,204]))
    streams["compensation-lifecycle"] = lifecycle_rows
    traces["compensation"]["lifecycle"] = complete
    from flow_fixture import generic_combined
    generic, generic_result = generic_combined()
    evaluate(generic,generic_result,"The separately selected generic mechanical contract requires assessment review as outer gate plus one distinct exact release. Neither bank nor compensation business policy is changed.",
        "generic-assessment-and-release",sources=[133])
    same, same_result=generic_combined(same_person=True)
    evaluate(same,same_result,"One explicitly authorized person may supply the two distinct human acts because this generic source imposes no separation between those humans. Both remain distinct from the actual executing agent.",
        "generic-same-person-distinct-acts",sources=[137])
    replaced=copy.deepcopy(generic)
    release_req=next(row for row in replaced["envelope"]["decision_requirements"] if row["id"]=="generic-content-release")
    replaced["envelope"]["gate"].update(decision_requirement=release_req["id"],role=release_req["role"]);rebind_outer(replaced);refresh_revocations(replaced)
    admission(replaced,"UNSUPPORTED_RELATION","The supported combined profile preserves the assessment review as sole outer gate; the supplementary release cannot replace it.","generic-release-cannot-replace-assessment",sources=[134],phase=2)
    rejected,_=generic_combined(review_decision="REJECT")
    failed=[{"purpose":"ASSESSMENT","subject_digest":digest("content-assessment",rejected["assessment_bases"][0]["assessment"]),
        "requirement_ref":rejected["assessment_bases"][0]["requirement_id"],"at":COMPENSATION_AT,"reason":"ASSESSMENT_NOT_SATISFIED"}]
    expected=authority_refusal(failed);expected["decision_results"]=ordinary_expected(rejected)["decision_results"]
    evaluate(rejected,expected,"A valid exact release cannot waive the separately required content-review REJECT. Both authenticated human results remain retained.","generic-assessment-rejects-release-valid",sources=[136],phase=5)
    reused=copy.deepcopy(generic)
    review_basis=next(row for row in reused["decision_bases"] if row["requirement_id"]=="customer-message-review")
    next(row for row in reused["decision_bases"] if row["requirement_id"]=="generic-content-release")["evidence"]=copy.deepcopy(review_basis["evidence"])
    admission(reused,"DEPENDENCY_MISMATCH","One assessment-review act/body cannot replace the distinct declared release's complete work class and envelope dependencies.","generic-one-act-two-requirements",sources=[138],phase=2)
    broad=source_trace(compensation=True,extra_restriction=True)
    second=descriptor("second-internal-source",scope=broad["authority"]["envelope"]["scope"]["id"],restrictions=["SECOND-INTERNAL-RESTRICTION"],compensation=True)
    _,extra=read(broad["configuration"],broad["state"],second,context_id=broad["context_id"],role="hr-compensation-analysis-agent",event_id="broader-release-context",at=COMPENSATION_AT)
    supplied,_=attach_compensation_flow(broad["configuration"],extra["state"],compensation_skeleton(),context_id=broad["context_id"],artifact_id=broad["artifact_id"],
        released_restrictions=[broad["restriction"],"SECOND-INTERNAL-RESTRICTION"])
    policy(supplied,["FLOW_RELEASE_NOT_ESTABLISHED"],"The signed subset includes a nonreleasable restriction without a current release rule. A human act cannot enlarge the configured content-release remit.",
        "release-subset-beyond-remit",sources=[119],standalone=True)
    foreign=copy.deepcopy(comp["authority"]);foreign["flow_bases"]=copy.deepcopy(protected["authority"]["flow_bases"])
    admission(foreign,"DEPENDENCY_MISMATCH","Compensation authority's selected registry configuration cannot be replaced with the bank reporting registry. A valid foreign release supplies no bank disclosure basis.",
        "compensation-release-is-not-bank-exception",sources=[120],phase=2)
    outside=copy.deepcopy(comp["authority"]);leaf=outside["decision_bases"][0]["evidence"]["authority_input"]
    next(row for row in leaf["capacities"] if row["id"].endswith("-executor"))["validity"]["valid_from"]="2026-10-08T12:00:01Z"
    rebind_outer(leaf);refresh_revocations(leaf)
    admission(outside,"ACT_NOT_AUTHORIZED","The release was signed before its complete selected Director capacity became valid. Attributable return alone cannot establish signing remit.","release-outside-signing-remit",sources=[131],phase=4)
    conflict=copy.deepcopy(comp["authority"]);leaf=conflict["decision_bases"][0]["evidence"]["authority_input"]
    selected=next(row for row in leaf["acts"] if row["kind"]=="INSTANCE_DECISION")
    other=copy.deepcopy(selected);other["id"]="competing-release-act";leaf["acts"].append(other);leaf["acts"].sort(key=lambda row:digest("authority-act",row))
    removed=[row for row in leaf["returns"] if row["act_digest"]==digest("authority-act",selected)]
    leaf["returns"]=[row for row in leaf["returns"] if row not in removed]
    removed_digests={digest("authority-return",row) for row in removed}
    leaf["host_selection"]["authenticated_records"]=[row for row in leaf["host_selection"]["authenticated_records"] if row["record_digest"] not in removed_digests]
    admission(conflict,"ACT_CONFLICT","Two selected human decision acts compete while the original return is missing. Inherited phase4 act conflict precedes missing return evidence.",
        "conflicting-human-before-missing-return",sources=[197],phase=4)
    oversized=copy.deepcopy(clean["stages"][-1][0])
    oversized["event"]["payload"]["fields"]= [{"name":"content","value":{"type_ref":"STRING","value":"x"*16777216}}]
    oversized["event"]["payload"]["types"]=[{"id":"STRING","kind":"STRING","nonnegative":False,"unit":None}]
    oversized["host_evidence"]=host_evidence(clean["configuration"],oversized["event"]);refresh_response(oversized)
    deny(oversized,"LIMIT_EXCEEDED","The supported-shape materialization makes complete canonical input exceed16,777,216 bytes while its raw frame remains below17,825,792. Outer input admission refuses generically before reader/state trust; this is not a separate artifact-specific byte ceiling.",
        "materialization-input-byte-limit",shape=True,sources=[186],phase="outer canonical size")
    return rows, labels, mappings, phases, streams, traces


def main():
    rows, labels, mappings, phases, streams, traces = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    SPECIMEN.mkdir(parents=True, exist_ok=True)
    for path in [BANK_SOURCE, COMPENSATION_SOURCE, GENERIC_SOURCE]:
        (SPECIMEN / path.name).write_bytes(path.read_bytes())
    (SPECIMEN / "host-expected-judgments.json").write_bytes(HOST_JUDGMENTS.read_bytes())
    (SPECIMEN / "host-expected-interface.md").write_bytes(HOST_INTERFACE.read_bytes())
    for name, facts in traces.items():
        target = SPECIMEN / name; target.mkdir(parents=True, exist_ok=True)
        write_canonical_json(target / "configuration.json", facts["configuration"])
        write_canonical_json(target / "authority-input.json", facts["authority"])
        authority_label = "bank-protected-denied" if name == "bank-protected" else name + "-authority"
        authority_case = next(row for row in rows if row["id"] == labels[authority_label])
        write_canonical_json(target / "authority-result-derived.json", authority_case["expected"])
        write_canonical_json(target / "pre-exposure-state.json", facts["state"])
    for name, stream in streams.items():
        target = SPECIMEN / name; target.mkdir(parents=True, exist_ok=True)
        requests = [{"protocol": PROTOCOL, "request_id": row["id"], "operation": row["operation"], "input": row["input"]} for row in stream]
        (target / "requests.jsonl").write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in requests))
        write_canonical_json(target / "results-derived.json", [row["expected"] for row in stream])
    source_cases = json.loads(INVENTORY.read_text())["cases"]
    host_rows = {row["source_case_id"]: row for row in json.loads(HOST_JUDGMENTS.read_text())["cases"]}
    dispositions = []
    changed = {8,9,10,11,12,35,36,45,48,49,168,169,177,178,179,180}
    host_cases = {7,19,24,25,28,31,33,37,38,39,47,48,50,55,56,57,58,64,74,75,76,77,79,80,83,84,85,86,87,88,89,90,91,92,93,94,96,97,98,99,121,122,131,132,137,138,141,142,147,148,149,150,151,152,157,160,161,163,164,165,166,167,168,169,174,175,177,178,179,180,181,182,203,204,205,206}
    for source in source_cases:
        number = int(source["id"].rsplit("-", 1)[1])
        component_links = mappings.get(source["id"], []) if number in {203,204} else []
        exact = [] if number in {203,204} else mappings.get(source["id"], [])
        host = host_rows.get(source["id"])
        disposition = ("EXTERNAL_UNMEDIATED_ROUTE_PREMISE" if number == 99
            else "UNREACHABLE_SELECTED_NATIVE_PROFILE" if number == 132
            else "EXACT_CASES_WITH_HOST_PREMISES" if exact and number in host_cases
            else "EXACT_COMPONENT_CASES" if exact
            else "EXPLICIT_HOST_EXPECTATION" if host
            else "MISSING_SOURCE_DISPOSITION")
        reason = ("Creation is empty/dormant and admits each original source through authorized READ/IMPORT; no initial-source bypass." if number in {8,9,10,11,12}
            else "Postclaim commit is POSSIBLE_EXPOSURE, including crash before observed invocation. No same-intent automatic reset/retry after no-exposure proof; explicit later recovery policy required." if number in {35,36,45,48,49,168,169}
            else "First profile ends at one immediate custody recipient and refuses undeclared delayed onward chains. A later separately mediated boundary is a separate operation." if number in {177,178,179,180}
            else "Exact mechanical cases do not prove authentic source policies, current host selection, writer completeness or actual delivery." if exact and number in host_cases
            else "The finite exact case identifies only the consequence and contract condition described in its derivation." if exact
            else "The route is outside the mediated boundary; actual calls, delivery and state are unknown. Inventory records the coverage gap and proves no enforcement on that route." if number == 99
            else "The six selected compensation native fields contain no independent declining business disposition. The release act is the sole selected release disposition, so an accepted act plus a different declining native field is not representable. No second compensation approval is added." if number == 132
            else "Independent host expectation records the finite call counts and retained state consequence. Source construction makes no execution or deployment claim.")
        dispositions.append({**source, "case_ids": exact, "component_case_ids": component_links, "host_expectation_id": host["id"] if host else None,
            "host_expectation_path": "host-expected-judgments.json" if host else None,
            "disposition": disposition, "successor_changes_expectation": number in changed, "successor_reason": reason})
    if any(row["disposition"] == "MISSING_SOURCE_DISPOSITION" for row in dispositions):
        raise ValueError("Every original source scenario needs an explicit bounded disposition")
    coverage = {"candidate_pin": candidate_pin(), "status": "EXPECTED_CASES_FROZEN_BEFORE_RUNTIME_COMPARISON", "source_inventory_sha256": sha(INVENTORY),
        "case_count": str(len(rows)), "source_case_count": "206", "labels": labels,
        "cases": [{"id": row["id"], "phase": phases[row["id"]], "path": "../../cases/information-flow/" + row["id"] + ".json", "raw_sha256": sha(GROUP / (row["id"] + ".json"))} for row in rows],
        "source_dispositions": dispositions,
        "unreachable_boundaries": [{"boundary": "128 claims before event exhaustion", "reason": "Every claim consumes one event; creation consumes a nonclaim event, so valid history reaches 128 events first."},
            {"boundary": "65 accumulated restrictions from a valid selected catalogue", "source_case_id": "FLOW-SOURCE-185", "reason": "The catalogue admits at most64 distinct restrictions. Every admitted READ/IMPORT restriction is a member of that immutable catalogue. Their union therefore cannot contain65 members; the65-entry catalogue is refused at outer schema admission."},
            {"boundary": "Accepted release act plus independently declining compensation native disposition", "source_case_id": "FLOW-SOURCE-132", "reason": "The exact six-field selected compensation inventory has no independent disposition field. A new field would change the selected business profile."}],
        "host_expectations": {"path": "host-expected-judgments.json", "raw_sha256": sha(HOST_JUDGMENTS), "case_count": str(len(host_rows)), "status": "INDEPENDENT_EXPECTATIONS_NOT_EXECUTED"},
        "sources": [{"path": str(path.relative_to(ROOT)), "raw_sha256": sha(path)} for path in [BANK_SOURCE, COMPENSATION_SOURCE, GENERIC_SOURCE]],
        "runtime_comparisons": [], "semantic_correspondence": "SOURCE_CONSTRUCTED_NOT_INDUSTRY_REVIEWED", "industry_review": "NOT_PERFORMED"}
    write_canonical_json(SPECIMEN / "source-coverage.json", coverage)
    counts = {key: sum(row["disposition"] == key for row in dispositions) for key in sorted({row["disposition"] for row in dispositions})}
    text = "# Information-flow source coverage\n\nStatus: expected cases frozen before runtime comparison. Candidate pin `" + candidate_pin() + "`.\n\n"
    text += str(len(rows)) + " independently derived complete cases cover three source-selected traces, current response authority, exact state reconstruction, read/transfer union, clean customer assessment, one Director compensation release, current policy refusal, one-use claims, replay and optional-member evidence. No consumer implementation, observed output or model service was imported or invoked by the builder.\n\n"
    text += "The preserved 206-case source inventory is mapped in [source-coverage.json](../../specimens/information-flow/source-coverage.json). Every source scenario links exact interface cases, an independent finite host expectation, an explicit unreachable selected-profile condition, or an external unmediated-route premise. Exact cases cover only their stated mechanical condition. Host/provider conditions remain declared premises; no runtime pass is inferred from the coverage list.\n\n"
    text += "| Disposition | Source cases |\n|---|---:|\n" + "".join("| " + key + " | " + str(value) + " |\n" for key, value in counts.items())
    text += "\nThe successor bank and compensation revision2 sources preserve the original business sources and identify additions selected by the architecture. Empty dormant creation, current response-reader authority, stable intent/possible-exposure claims, first-custody scope and conservative postclaim crash behavior are explicit additions. A postclaim crash, even before observed invocation, consumes the claim/intent and selected release; a fresh release alone does not authorize an unresolved same-intent retry. The independent 128-claim boundary is unreachable before the 128-event boundary in a valid history.\n\n"
    text += "The generic registry does not infer the bank's six-role read/purpose matrix. Selected ordinary access grants must encode it, and source review must reject a newly authorized prohibited remit. Digest equality proves retained identity, not complete source truth or real isolation. The compensation fixture uses the release leaf as its sole outer human gate and requires no model assessment or second human approval.\n\n"
    text += "The separate generic synthetic source selects both assessment and release requirements for a fictional internal draft. Its cases cover distinct acts by one person, assessment rejection despite valid release, and refusal to replace the selected assessment gate. It changes no bank or compensation policy. Complete standalone canonical input above16,777,216 bytes is refused at outer admission before reader/state trust; projected state capacity remains a post-reader unchanged-state refusal.\n\n"
    text += "Runnable independent constructor: `python3 conformance/work-class/1.0.0-draft.3/review/build-information-flow-cases.py`. It writes only this case family and specimens. Parent corpus orchestration owns shared indexes and qualification.\n\nNot checked: runtime agreement; real provider isolation, classifications, latest selections and complete writer participation; durable crash recovery; customer/consultant delivery; human understanding; legal or industry acceptance.\n"
    (HERE / "fixtures/INFORMATION-FLOW-SOURCE-COVERAGE.md").write_text(text)
    write_canonical_json(SPECIMEN / "artifact-index.json", {"candidate_pin": candidate_pin(), "artifacts": [{"path": str(path.relative_to(SPECIMEN)), "raw_sha256": sha(path)}
        for path in sorted(SPECIMEN.rglob("*")) if path.is_file() and path.name != "artifact-index.json"]})
    freeze = GENERATION_ROOT / "flow-source/EXACT-CASE-FREEZE-06.json"
    if not freeze.exists():
        write_canonical_json(freeze, {"candidate_pin": candidate_pin(), "status": "EXPECTED_CASES_FROZEN_BEFORE_RUNTIME_COMPARISON",
            "case_count": str(len(rows)), "source_coverage_sha256": sha(SPECIMEN / "source-coverage.json"),
            "builder_sha256": sha(Path(__file__)), "fixture_sha256": sha(HERE / "flow_fixture.py"),
            "cases": coverage["cases"], "no_runtime_comparison_performed": True})
    print(json.dumps({"candidate_pin": candidate_pin(), "cases": len(rows), "source_dispositions": counts, "labels": labels}, indent=2))


if __name__ == "__main__":
    main()
