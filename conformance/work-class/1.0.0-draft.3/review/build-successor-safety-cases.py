#!/usr/bin/env python3
"""Derive successor dispatch cases from approved source rules without consumers."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import runpy
import lifecycle_factory

from corpus_common import CASES, exact_case, write_canonical_json
from dependency_dispute_common import apply_dependency_block
from equipment_completion_fixture import (
    completion_base,
    lookup_event,
    lookup_result,
)
from equipment_dispatch_fixture import authorization_event, authorization_result, retained
from fixture_factory import available_clock
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    effect_result,
    governed_effect_event,
    governed_native_evidence,
    permitted_proposal,
    state_digest,
    stateful_refusal,
    step_input,
)
from corpus_common import digest
from checkpoint_reseal import reseal_last_transition


HERE = Path(lifecycle_factory.__file__).resolve().parent


GROUP = CASES / "successor-dispatch-safety"
ROWS = []


def carrier(result, permit):
    return {"state": result["state"], "state_digest": result["state_digest"], "permit": permit}


def emit(base, before, event, expected, requirements, derivation):
    case_id = "C3-SUCC-" + str(len(ROWS) + 1).zfill(3)
    ROWS.append(exact_case(case_id, "step", step_input(base, before["state"], event), expected, requirements, derivation))


def fresh_attempt(base, before, *, name, status="SENT", acknowledgement="NONE", attempt_id="attempt-2"):
    event = dispatch_event(base, before, event_id=name, attempt_status=status, acknowledgement_status=acknowledgement)
    event["attempt"]["attempt_id"] = attempt_id
    return event


def clock_after(base, before, instant="2026-09-10T04:35:00Z"):
    clock = available_clock("authority-clock", "2", instant)
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "successor-clock-2",
        "kind": "CLOCK",
        "instance_id": before["state"]["instance_id"],
        "expected_state_revision": before["state"]["revision"],
        "expected_state_digest": before["state_digest"],
        "clock": clock,
        "activation_clocks": [],
    }

    def mutate(state):
        state["clocks"].append(copy.deepcopy(clock))
        state["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))

    result = admitted_transition(before["state"], event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]}], mutate=mutate)
    return carrier(result, before["permit"])


def changed_request(permit):
    native = copy.deepcopy(permit["native_request"])
    next(row for row in native["fields"] if row["name"] == "card_id")["value"]["value"] = "card-803"
    return native


def stable_dispatch(state, event_id):
    return next(row for row in state["dispatches"] if row["event_id"] == event_id)


def source_module(name):
    return runpy.run_path(str(HERE / name))


def mixed_gate_base():
    gated = completion_base()
    gate = next(row["dispatch_gate"] for row in gated["definition"]["steps"]
        if row["kind"] == "OPERATION")
    gate_ids = {gate["approval_requirement"], gate["withdrawal_requirement"],
        *gate["policy_withdrawal_requirements"]}
    gate_requirements = [row for row in gated["authority_input"]["envelope"]["source_observation_requirements"]
        if row["id"] in gate_ids]
    instant_type = next(row for row in gated["authority_input"]["work_class"]["types"]
        if row["id"] == "INSTANT")

    def authority_mutator(supplied, original):
        root = supplied["work_class"]["steps"][0]
        peer = copy.deepcopy(root)
        peer.update(id="gated-peer", operation="issue-card-gated-peer", dispatch_gate=copy.deepcopy(gate),
            authority_type_refs=["INSTANT"])
        supplied["work_class"]["steps"].append(peer)
        supplied["work_class"]["steps"].sort(key=lambda row: row["id"].encode())
        supplied["work_class"]["types"].append(copy.deepcopy(instant_type))
        supplied["work_class"]["types"].sort(key=lambda row: row["id"].encode())
        requirements = supplied["envelope"].setdefault("source_observation_requirements", [])
        for requirement in gate_requirements:
            peer_requirement = copy.deepcopy(requirement)
            peer_requirement["step"] = "gated-peer"
            requirements.append(peer_requirement)
        requirements.sort(key=lambda row: row["id"].encode())

    def definition_mutator(definition):
        definition["relationships"] = [
            {"kind": "SEQUENCE", "from": definition["root"], "to": "gated-peer"},
            {"kind": "SEQUENCE", "from": "gated-peer", "to": "terminal"},
        ]

    return base_lifecycle(authority_mutator=authority_mutator,
        definition_mutator=definition_mutator, instance_id="mixed-gate-instance")


def completed_source_late_attempt():
    source = source_module("build-disputed-permit-basis-case.py")
    pbr = source["PBR"]
    definition, definition_digest, state, occurrence, permit, _ = source["permitted_descendant_state"]()
    prior = next(row for row in state["dispatches"] if row["permit_digest"] == permit["permit_id"])
    attempt = copy.deepcopy(prior["attempt"])
    attempt.update(attempt_id="late-completed-source-attempt", status="SENT")
    acknowledgement = {"status": "NONE", "reference": None, "observed_at": None}
    event = {
        "schema": pbr.SCHEMA + "runtime-event", "event_id": "late-completed-source-send",
        "kind": "DISPATCH_OBSERVED", "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": pbr.work_state_digest(state),
        "permit": copy.deepcopy(permit), "native_request": copy.deepcopy(prior["native_request"]),
        "connector": copy.deepcopy(prior["connector"]), "attempt": attempt,
        "acknowledgement": acknowledgement, "clock_revision": "1",
    }
    attempt_digest = pbr.digest("dispatch-attempt", {
        "permit_id": permit["permit_id"], "native_request": event["native_request"],
        "connector": event["connector"], "attempt": attempt,
    })
    body = {
        "dispatch_attempt_digest": attempt_digest, "event_id": event["event_id"],
        "event_digest": pbr.digest("runtime-event", event), "permit_digest": permit["permit_id"],
        "native_request": copy.deepcopy(event["native_request"]), "connector": copy.deepcopy(event["connector"]),
        "attempt": copy.deepcopy(attempt), "acknowledgement": copy.deepcopy(acknowledgement), "clock_revision": "1",
    }
    record = {"dispatch_digest": pbr.digest("dispatch", body), **body}

    def mutate(next_state, _event_digest):
        next_state["dispatches"].append(copy.deepcopy(record))
        next_state["dispatches"].sort(key=lambda row: row["dispatch_digest"].encode())
        apply_dependency_block(next_state, occurrence["occurrence_id"])

    after, expected = pbr.work_transition(state, event, disposition="DISPUTED",
        reasons=["LATE_OR_PROHIBITED_DISPATCH"],
        details=[{"kind": "DISPATCH", "attempt_id": attempt["attempt_id"],
            "reasons": ["LATE_OR_PROHIBITED_DISPATCH"]}], permit=None, budget_results=[],
        authority_result_digest=None, reservation_receipt_digests=[], mutate=mutate)
    supplied = pbr.lifecycle_input(definition, definition_digest, state, event)
    return pbr, definition, definition_digest, after, supplied, expected


def source_cases():
    base = base_lifecycle()
    proposal = permitted_proposal(base)
    permitted = carrier(proposal, proposal["permit"])

    changed = dispatch_event(base, permitted, event_id="successor-changed-send",
        native_request=changed_request(permitted["permit"]))
    emit(base, permitted, changed, dispatch_result(permitted, changed, disposition="DISPUTED",
        reasons=["NATIVE_ARGUMENT_MISMATCH"], occurrence_status="BLOCKED_DISPUTE"),
        ["LIFE-006", "LIFE-009"],
        "A possibly sent ungated request with changed arguments is dispatch-disqualified. Its active source blocks even though this step has no declared gate.")

    expired = clock_after(base, permitted)
    late = dispatch_event(base, expired, event_id="successor-expired-send",
        attempted_at="2026-09-10T04:35:00Z", clock_revision="2")
    emit(base, expired, late, dispatch_result(expired, late, disposition="DISPUTED",
        reasons=["PERMIT_EXPIRED"], occurrence_status="BLOCKED_DISPUTE"),
        ["LIFE-006", "LIFE-009"],
        "An ungated possibly sent attempt at the exclusive permit expiry is retained and blocks its active source.")

    conflict = dispatch_event(base, permitted, event_id="successor-ungated-conflict",
        attempt_status="NOT_SENT", acknowledgement_status="ACCEPTED")
    emit(base, permitted, conflict, dispatch_result(permitted, conflict, disposition="DISPUTED",
        reasons=["DISPATCH_EVIDENCE_CONFLICT"], occurrence_status="OUTCOME_UNKNOWN"),
        ["LIFE-006", "LIFE-009", "LIFE-010"],
        "The only ungated stable attempt is a timely NOT_SENT/ACCEPTED conflict. The final-safe-attempt exception leaves it OUTCOME_UNKNOWN pending evidence.")

    first = dispatch_event(base, permitted, event_id="successor-valid-first", acknowledgement_status="ACCEPTED")
    first_result = dispatch_result(permitted, first, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    after_first = carrier(first_result, permitted["permit"])
    second = fresh_attempt(base, after_first, name="successor-prohibited-second")
    second_result = dispatch_result(after_first, second, disposition="DISPUTED",
        reasons=["LATE_OR_PROHIBITED_DISPATCH"], occurrence_status="BLOCKED_DISPUTE")
    emit(base, after_first, second, second_result, ["LIFE-006", "LIFE-009"],
        "A second possibly sent attempt after a valid acknowledged dispatch is disqualified. The active source blocks rather than remaining DISPATCHED.")

    rejected = fresh_attempt(base, after_first, name="successor-prohibited-rejected", status="REJECTED")
    rejected_result = dispatch_result(after_first, rejected, disposition="DISPATCH_REFUSED",
        reasons=["LATE_OR_PROHIBITED_DISPATCH", "NATIVE_DISPATCH_REJECTED"], occurrence_status="BLOCKED_DISPUTE")
    emit(base, after_first, rejected, rejected_result, ["LIFE-006", "LIFE-009"],
        "A matching REJECTED attempt on a consumed permit may have reached the connector. Its refusal and late reason block the active source.")

    safe = fresh_attempt(base, after_first, name="successor-safe-after-consumed", status="NOT_SENT")
    emit(base, after_first, safe, stateful_refusal(after_first["state"], "PREREQUISITE_MISSING"),
        ["LIFE-009"],
        "A fresh NOT_SENT attempt without accepted acknowledgement on a consumed permit did not reach the connector and is refused without a state change.")

    for label, prior in (("sent", second_result), ("rejected", rejected_result)):
        current = carrier(prior, permitted["permit"])
        first_dispatch = stable_dispatch(current["state"], first["event_id"])
        evidence = governed_native_evidence(base, permitted, current,
            evidence_id="successor-effect-after-" + label, dispatch_digest=first_dispatch["dispatch_digest"])
        effect = governed_effect_event(permitted, current, evidence,
            event_id="successor-effect-event-after-" + label, dispatch_digest=first_dispatch["dispatch_digest"])
        expected = effect_result(base, permitted, current, effect, classification="UNEXPECTED", disposition="DISPUTED",
            reason_codes=["DEPENDENCY_DISPUTED", "UNEXPECTED_EFFECT"], occurrence_status="BLOCKED_DISPUTE", disputed=True)
        emit(base, current, effect, expected, ["LIFE-006", "LIFE-010", "LIFE-013"],
            "The effect is attributed to the earlier valid attempt, but a distinct retained " + label +
            " attempt may also have executed. At this event prefix the effect is UNEXPECTED, cannot route, and leaves the source blocked.")

    safe_first = dispatch_event(base, permitted, event_id="successor-safe-first", attempt_status="NOT_SENT")
    safe_result = dispatch_result(permitted, safe_first, disposition="DISPATCH_REFUSED",
        reasons=["NATIVE_NOT_SENT"], occurrence_status="PERMITTED")
    after_safe = carrier(safe_result, permitted["permit"])
    valid_second = fresh_attempt(base, after_safe, name="successor-valid-second")
    valid_result = dispatch_result(after_safe, valid_second, disposition="DISPATCH_RECORDED",
        reasons=[], occurrence_status="DISPATCHED")
    emit(base, after_safe, valid_second, valid_result, ["LIFE-009", "LIFE-010"],
        "A definitely NOT_SENT first attempt permits a distinct timely second attempt. The safe first attempt adds no unsafe block.")

    after_valid_second = carrier(valid_result, permitted["permit"])
    update = copy.deepcopy(safe_first)
    update.update(event_id="successor-ack-safe-first", expected_state_revision=after_valid_second["state"]["revision"],
        expected_state_digest=after_valid_second["state_digest"])
    update["acknowledgement"] = {"status": "ACCEPTED", "reference": "successor-accepted-first", "observed_at": "2026-09-10T04:30:00Z"}
    emit(base, after_valid_second, update, dispatch_result(after_valid_second, update, disposition="DISPUTED",
        reasons=["DISPATCH_EVIDENCE_CONFLICT"], occurrence_status="BLOCKED_DISPUTE"),
        ["LIFE-006", "LIFE-009", "LIFE-010"],
        "A later ACCEPTED acknowledgement makes the earlier distinct NOT_SENT attempt possibly effective after another send. The active source blocks.")

    gated = completion_base()
    gated_permitted = permitted_proposal(gated)
    gated_current = carrier(gated_permitted, gated_permitted["permit"])
    authorization = authorization_event(gated, gated_current, event_id="successor-gated-authorize")
    authorized = authorization_result(gated, gated_current, authorization)
    gated_current = carrier(authorized, gated_permitted["permit"])
    auth_digest = authorized["state"]["authorizations"][0]["authorization_digest"]

    gated_conflict = dispatch_event(gated, gated_current, event_id="successor-gated-conflict",
        attempt_status="NOT_SENT", acknowledgement_status="ACCEPTED", authorization_digest=auth_digest)
    emit(gated, gated_current, gated_conflict, dispatch_result(gated_current, gated_conflict,
        disposition="DISPUTED", reasons=["DISPATCH_EVIDENCE_CONFLICT"], occurrence_status="BLOCKED_DISPUTE"),
        ["LIFE-006", "LIFE-009"],
        "A gated NOT_SENT/ACCEPTED conflict blocks the active source even if it is the only stable attempt.")

    prohibited = dispatch_event(gated, gated_current, event_id="successor-gated-null-claim")
    prohibited_result = dispatch_result(gated_current, prohibited, disposition="DISPUTED",
        reasons=["LATE_OR_PROHIBITED_DISPATCH"], occurrence_status="BLOCKED_DISPUTE")
    emit(gated, gated_current, prohibited, prohibited_result, ["LIFE-006", "LIFE-009"],
        "The exact gated permit and request make a null observed authorization claim attributable, but the claim grants no permission. Retain and block the attempt.")

    gated_blocked = carrier(prohibited_result, gated_permitted["permit"])
    lookup = lookup_event(gated, gated_blocked, event_id="successor-claim-only-lookup")
    emit(gated, gated_blocked, lookup, lookup_result(gated, gated_blocked, lookup),
        ["LIFE-006A", "LIFE-010"],
        "An exact-request prohibited gated attempt with null authorization claim is eligible for claim-only lookup correlation. NOT_FOUND preserves BLOCKED_DISPUTE in the terminal record.")

    changed_gated = dispatch_event(gated, gated_current, event_id="successor-gated-changed-claim",
        native_request=changed_request(gated_permitted["permit"]))
    changed_result = dispatch_result(gated_current, changed_gated, disposition="DISPUTED",
        reasons=["LATE_OR_PROHIBITED_DISPATCH", "NATIVE_ARGUMENT_MISMATCH"], occurrence_status="BLOCKED_DISPUTE")
    changed_current = carrier(changed_result, gated_permitted["permit"])
    changed_lookup = lookup_event(gated, changed_current, event_id="successor-changed-claim-lookup")
    emit(gated, changed_current, changed_lookup, stateful_refusal(changed_current["state"], "BINDING_MISMATCH"),
        ["LIFE-006A", "LIFE-010"],
        "The changed attempted request is not covered by the permit-derived lookup query. Claim-only correlation refuses this lookup.")

    mixed = mixed_gate_base()
    mixed_proposal = permitted_proposal(mixed)
    ROWS.append(exact_case("C3-SUCC-" + str(len(ROWS) + 1).zfill(3), "step",
        step_input(mixed, mixed["clock_result"]["state"], mixed["proposal_event"]), mixed_proposal,
        ["LIFE-007", "LIFE-009A"],
        "A definition has an ungated selected operation followed by a separately gated peer. The selected step's proposal remains permitted and its permit has no gated authority basis."))
    mixed_current = carrier(mixed_proposal, mixed_proposal["permit"])
    mixed_send = dispatch_event(mixed, mixed_current, event_id="mixed-ungated-send")
    emit(mixed, mixed_current, mixed_send,
        dispatch_result(mixed_current, mixed_send, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED"),
        ["LIFE-009", "LIFE-009A"],
        "The selected ungated operation uses its source-approved finite snapshot even though a later operation declares a gate.")

    inherited = source_module("build-dispatch-authorization-cases.py")
    wrong_form = inherited["authorization_event"](base, permitted, event_id="inherited-wrong-fence-form")
    old_fence = wrong_form["authorization_fence"]
    wrong_form["authorization_fence"] = {
        "kind": "SOURCE_REQUIREMENTS", "provider": old_fence["provider"], "source": old_fence["source"],
        "provider_revision": old_fence["provider_revision"], "scope_digest": old_fence["scope_digest"],
        "checked_at": old_fence["checked_at"], "status": "EFFECTIVE", "sources": [{
            "requirement_id": "approval", "provider": old_fence["provider"], "source": old_fence["source"],
            "expected_status": "AVAILABLE", "record_id": old_fence["approval_id"],
            "provider_revision": old_fence["provider_revision"],
            "query_digest": digest("authority-query", {"id": "inherited-wrong-fence-form"}),
            "observation_digest": permitted["permit"]["observation_digests"][0],
        }],
    }
    emit(base, permitted, wrong_form, stateful_refusal(permitted["state"], "BINDING_MISMATCH"),
        ["LIFE-009A"],
        "An inherited single-provider authorization cannot accept the SOURCE_REQUIREMENTS fence form, even when that form is schema-valid.")

    pbr, completed_definition, completed_digest, blocked, late_input, late_expected = completed_source_late_attempt()
    ROWS.append(exact_case("C3-SUCC-" + str(len(ROWS) + 1).zfill(3), "step", late_input, late_expected,
        ["LIFE-009", "LIFE-013", "REC-013"],
        "A fresh possibly sent attempt on a completed supplier-change source is dispatch-disqualified. The completed source stays historical while its permitted payment descendant becomes BLOCKED_DISPUTE."))

    clock = pbr.clock_event(blocked, "late-source-followup-clock", source="governance-clock",
        revision="2", observed_time="2026-09-11T12:01:00Z")
    clocked, clock_expected = pbr.accepted_clock(blocked, clock)
    ROWS.append(exact_case("C3-SUCC-" + str(len(ROWS) + 1).zfill(3), "step",
        pbr.lifecycle_input(completed_definition, completed_digest, blocked, clock), clock_expected,
        ["LIFE-013", "REC-013"],
        "A later clock observation does not clear the unresolved completed-source dispatch cause or restore its dependent payment."))

    forged = copy.deepcopy(blocked)
    next(row for row in forged["active"] if row["occurrence"]["step_id"] == "pay-invoice")["status"] = "PERMITTED"
    for obligation in forged["obligations"]:
        if obligation["status"] == "BLOCKED":
            obligation["status"] = "OPEN"
    reseal_last_transition(forged)
    forge_clock = pbr.clock_event(forged, "forged-recovery-clearance-clock", source="governance-clock",
        revision="2", observed_time="2026-09-11T12:01:00Z")
    ROWS.append(exact_case("C3-SUCC-" + str(len(ROWS) + 1).zfill(3), "step",
        pbr.lifecycle_input(completed_definition, completed_digest, forged, forge_clock),
        pbr.refusal(forged, "STATE_INVALID"), ["LIFE-013", "REC-013"],
        "A self-consistently resealed restart checkpoint cannot clear a completed-source dispatch cause without effective exact recovery coverage."))


def main():
    source_cases()
    for row in ROWS:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print({"count": len(ROWS), "case_ids": [row["id"] for row in ROWS], "consumer_execution": "NONE"})


if __name__ == "__main__":
    main()
