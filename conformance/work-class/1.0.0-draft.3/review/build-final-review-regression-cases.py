#!/usr/bin/env python3
"""Derive final-review regressions from the normative contract and author fixtures."""

from __future__ import annotations

import base64
import copy
import runpy
from pathlib import Path

from authority_fixture import authority_refusal
from checkpoint_reseal import reseal_last_transition
from corpus_common import CASES, canonical_bytes, candidate_pin, digest, exact_case, write_canonical_json
from equipment_completion_fixture import (completion_authority_mutator, completion_base,
    completion_definition_mutator, completion_dispatch, completion_native, terminal_effect_result)
from equipment_correction_fixture import (correction_fixture, correction_refusal, correction_result,
    equipment_original_fixture, rebind_authority, seal_correction)
from equipment_dispatch_fixture import authorization_event, authorization_result, clock_transition, retained
from equipment_history_fixture import history_fixture, history_state, seed_request, selected_slot
from equipment_observation_fixture import expected_ready, observation, refresh, source_refusal
from fixture_factory import available_clock, deployment, occurrence, typed
from lifecycle_factory import (admitted_transition, base_lifecycle, dispatch_event, dispatch_result,
    governed_effect_event, no_effect_completion_authorization, permitted_proposal, state_digest,
    stateful_refusal, step_input)
from reservation_fixture import refusal as reservation_refusal


REVIEW = Path(__file__).parent
GROUP = CASES / "final-review-regressions"
SCHEMA = "seampoint.work-class/1.0.0-draft.3/"
NOW = "2026-09-10T04:30:00Z"


def next_clock(base, prior, event_id):
    state = prior["state"]
    selected = max(state["clocks"], key=lambda row: int(row["revision"]))
    event, result = clock_transition(retained(prior, prior["permit"]),
        revision=str(int(selected["revision"]) + 1), instant=selected["observed_time"])
    event["event_id"] = event_id
    clock = copy.deepcopy(event["clock"])
    def mutate(value):
        value["clocks"].append(clock)
        value["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))
    result = admitted_transition(state, event, disposition="CLOCK_RECORDED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": "AVAILABLE"}],
        mutate=mutate)
    return event, result


def reseal_result(result):
    state = result["state"]
    reseal_last_transition(state)
    receipt = state["receipts"][-1]
    replay = next(row for row in state["replays"] if row["event_id"] == receipt["event_id"])
    result.update(decision=copy.deepcopy(receipt), decision_digest=receipt["decision_id"],
        state_digest=state_digest(state), transition_state_digest=replay["transition_state_digest"],
        transaction_digest=replay["transaction_digest"])
    return result


def deduplicate_referrals(result):
    result["state"]["referrals"] = sorted({row["referral_digest"]: row
        for row in result["state"]["referrals"]}.values(), key=lambda row: row["referral_digest"])
    return reseal_result(result)


def acknowledge_cases(emit):
    variants = [(gated, order, "NONE", "ACCEPTED") for gated in [False, True] for order in ["before", "after"]]
    variants += [(gated, "before", "UNKNOWN", "REJECTED") for gated in [False, True]]
    for gated, order, initial_ack, first_ack in variants:
        label = f"{'gated' if gated else 'inherited'}-{order}-{initial_ack.lower()}-{first_ack.lower()}"
        base = completion_base() if gated else base_lifecycle()
        permitted = permitted_proposal(base)
        current = retained(permitted, permitted["permit"])
        authorization_digest = None
        if gated:
            gate = authorization_event(base, current, event_id="frr-authorize-" + label, intent="frr-intent-" + label)
            current = retained(authorization_result(base, current, gate), permitted["permit"])
            authorization_digest = current["state"]["authorizations"][0]["authorization_digest"]
        first = dispatch_event(base, current, event_id="frr-send-" + label,
            acknowledgement_status=initial_ack, authorization_digest=authorization_digest)
        sent = retained(dispatch_result(current, first, disposition="DISPATCH_RECORDED",
            reasons=[] if initial_ack == "NONE" else ["DISPATCH_STATUS_UNKNOWN"], occurrence_status="DISPATCHED"), permitted["permit"])
        old_digest = sent["state"]["dispatches"][0]["dispatch_digest"]
        for index in range(1024):
            update = copy.deepcopy(first)
            update.update(event_id=f"frr-first-ack-{label}-{index}", expected_state_revision=sent["state"]["revision"],
                expected_state_digest=sent["state_digest"])
            update["acknowledgement"] = {"status": first_ack, "reference": f"first-{index}", "observed_at": NOW}
            update_result = dispatch_result(sent, update,
                disposition="ACKNOWLEDGED" if first_ack == "ACCEPTED" else "DISPATCH_RECORDED",
                reasons=[] if first_ack == "ACCEPTED" else ["ACKNOWLEDGEMENT_REJECTED"], occurrence_status="DISPATCHED")
            updated = retained(update_result, permitted["permit"])
            row = next(row for row in updated["state"]["dispatches"] if row["event_id"] == update["event_id"])
            if (row["dispatch_digest"] < old_digest) == (order == "before"):
                break
        else:
            raise AssertionError("no author-selected digest ordering")
        assert len({row["dispatch_attempt_digest"] for row in updated["state"]["dispatches"]}) == 1
        emit("step", step_input(base, sent["state"], update), update_result, ["LIFE-009", "LIFE-009A"],
            f"The {label} attempt accepts its one first conclusive {first_ack} update. Canonical digest construction places the conclusive row {order} the original row; digest sort position does not select acknowledgement history.")
        second_ack = "REJECTED" if first_ack == "ACCEPTED" else "ACCEPTED"
        second = copy.deepcopy(update)
        second.update(event_id="frr-second-ack-" + label, expected_state_revision=updated["state"]["revision"],
            expected_state_digest=updated["state_digest"])
        second["acknowledgement"] = {"status": second_ack, "reference": "second-conclusive", "observed_at": NOW}
        emit("step", step_input(base, updated["state"], second), stateful_refusal(updated["state"], "PREREQUISITE_MISSING"),
            ["LIFE-009"], "LIFE-009 permits exactly one NONE/UNKNOWN-to-conclusive update. A new event cannot replace the retained conclusive acknowledgement, irrespective of dispatch digest order.")
        forged = retained(dispatch_result(updated, second,
            disposition="ACKNOWLEDGED" if second_ack == "ACCEPTED" else "DISPATCH_RECORDED",
            reasons=[] if second_ack == "ACCEPTED" else ["ACKNOWLEDGEMENT_REJECTED"], occurrence_status="DISPATCHED"), permitted["permit"])
        assert len(forged["state"]["dispatches"]) == 3
        clock, _ = next_clock(base, forged, "frr-restart-ack-" + label)
        emit("step", step_input(base, forged["state"], clock), stateful_refusal(forged["state"], "STATE_INVALID"),
            ["LIFE-009", "LIFE-019"], "All three dispatch rows and receipt/replay/core commitments are constructed exactly, but the second conclusive update is unreachable. Restart must reconstruct the single-update rule and reject this checkpoint.")


def no_effect_cases(emit):
    for gated in [False, True]:
        def authority(value, original):
            completion_authority_mutator(value, original)
            if not gated:
                value["work_class"]["steps"][0].pop("dispatch_gate")
        base = base_lifecycle(authority_mutator=authority, definition_mutator=completion_definition_mutator)
        permitted = permitted_proposal(base)
        current = retained(permitted, permitted["permit"])
        authorization_digest = None
        if gated:
            event = authorization_event(base, current, event_id="frr-safe-authorize", intent="frr-safe-intent")
            current = retained(authorization_result(base, current, event), permitted["permit"])
            authorization_digest = current["state"]["authorizations"][0]["authorization_digest"]
        dispatch = dispatch_event(base, current, event_id="frr-safe-not-sent", attempt_status="NOT_SENT",
            authorization_digest=authorization_digest)
        current = retained(dispatch_result(current, dispatch, disposition="DISPATCH_REFUSED",
            reasons=["NATIVE_NOT_SENT"], occurrence_status="PERMITTED"), permitted["permit"])
        native = completion_native(base, current, status="NO_EFFECT_ESTABLISHED")
        completion_authorization = no_effect_completion_authorization(base, current, current, native)
        event = governed_effect_event(current, current, native, event_id="frr-terminal-authorized-no-effect",
            completion_authorization=completion_authorization)
        expected = terminal_effect_result(base, current, event, classification="UNEXPECTED", disposition="DISPUTED",
            reason_codes=["UNEXPECTED_EFFECT"], occurrence_status="BLOCKED_DISPUTE", disputed=True)
        assert expected["state"]["terminal_records"][0]["cause"] == "UNEXPECTED_COMPLETION"
        emit("step", step_input(base, current["state"], event), expected, ["LIFE-006A", "LIFE-010"],
            "The exact affirmative no-effect assertion has accepted completion authorization and a final safe NOT_SENT attempt. STOP_RETAIN still retains UNEXPECTED/DISPUTED, stops work with UNEXPECTED_COMPLETION and permits no portable no-effect closure or retry.")


def rebind_original(supplied, basis, definition=None):
    original = equipment_original_fixture()
    definition = supplied["definition"] if definition is None else definition
    definition_digest = digest("work-class-definition", definition)
    permit = supplied["original_permit"]
    selected = occurrence(definition_digest, permit["instance_id"], permit["occurrence"]["step_id"])
    basis["proposal"]["occurrence"] = selected["occurrence_id"]
    basis, result = rebind_authority(basis)
    event = copy.deepcopy(original["original_proposal_event"])
    event.update(authority_input=basis, occurrence=selected,
        observation_digests=sorted(digest("authority-observation", row) for row in basis["observations"]))
    if definition != supplied["definition"]:
        _, deployed = deployment(definition, instance_id=permit["instance_id"], organization_id=basis["envelope"]["principal"],
            authorization_time="2026-09-12T14:00:00Z", evidence_expires_at="2026-09-13T00:00:00Z",
            initial_clocks=[available_clock(basis["clock"]["source"], "1", basis["clock"]["instant"])])
        event.update(expected_state_revision=deployed["state"]["revision"], expected_state_digest=state_digest(deployed["state"]))
    permit.update(work_class_digest=definition_digest, occurrence=selected, proposal_digest=digest("proposal", event),
        authority_basis=basis, authority_result=result, authority_result_digest=digest("authority-result", result),
        authority_evidence_digest=result["evidence_digest"], observation_digests=event["observation_digests"],
        authority_act_bases=sorted([{"act_digest": digest("authority-act", act), "act": copy.deepcopy(act)}
            for act in basis["acts"]], key=lambda row: row["act_digest"]))
    permit["permit_id"] = digest("permit", {key: value for key, value in permit.items() if key != "permit_id"})
    supplied.update(definition=definition, definition_digest=definition_digest)
    record = supplied["original_record"]
    record["attributed_request"]["occurrence"] = selected["occurrence_id"]
    record["native_request_digest"] = digest("native-request", record["attributed_request"])


def correction_cases(emit):
    changes = [{"field": "asset", "old_value": typed("ASSET_ID", "EQ-204"), "new_value": typed("ASSET_ID", "EQ-205")}]
    supplied, admitted = correction_fixture(changes=changes)
    basis = copy.deepcopy(supplied["original_permit"]["authority_basis"])
    next(row for row in basis["acts"] if row["kind"] == "GRANT")["id"] = "original-grant-distinct-from-approval"
    basis["envelope"]["grant_ref"] = "original-grant-distinct-from-approval"
    rebind_original(supplied, basis)
    correction = supplied["correction"]
    _, correction_result_body = rebind_authority(correction["correction_authority_input"])
    _, new_result = rebind_authority(correction["new_approval_basis"])
    admitted = correction_result(supplied, correction_result_body, new_result)
    emit("check-evidence", supplied, admitted, ["LIFE-020A", "LIFE-008", "AUTH-001"],
        "The original selected grant has an identity distinct from original approval AP-091. Current independently evaluated AP-092 authority binds the changed complete result and satisfies both fresh-identity exclusions.")
    reused = copy.deepcopy(supplied)
    fresh = reused["correction"]["new_approval_basis"]
    next(row for row in fresh["acts"] if row["kind"] == "GRANT")["id"] = "AP-091"
    fresh["envelope"]["grant_ref"] = "AP-091"
    reused["correction"]["new_approval_basis"], _ = rebind_authority(fresh)
    seal_correction(reused["correction"])
    emit("check-evidence", reused, correction_refusal("BINDING_MISMATCH"), ["LIFE-020A", "AUTH-001"],
        "The current grant and all returned authority preimages are rebound, but its id reuses original approval AP-091 while the original selected grant and completion event have different ids. SOURCE-CORRECTIONS 4 excludes the original approval identity independently of both other identities.")
    profile, _ = correction_fixture()
    definition = copy.deepcopy(profile["definition"])
    definition["profile"] = "CHOICE_LOOPS"
    rebind_original(profile, copy.deepcopy(profile["original_permit"]["authority_basis"]), definition)
    emit("check-evidence", profile, correction_refusal("DEPENDENCY_MISMATCH"), ["LIFE-020A", "LIFE-008"],
        "Definition, occurrence, original authority, proposal, request and permit hashes are rebound to a valid CHOICE_LOOPS definition. The retained original permit still declares LINEAR and its LINEAR role. Exact original definition/permit profile agreement fails before current correction evaluation.")
    inversion, _ = correction_fixture()
    inversion["original_record"]["observed_at"] = "2026-09-12T14:29:59Z"
    emit("check-evidence", inversion, correction_refusal("BINDING_MISMATCH"), ["LIFE-020A", "LIFE-010"],
        "The original top-level event_time is 14:30:00 but observed_at is 14:29:59. The normalized seven-member provider commitment remains exact because observed_at is not in it. The original provider chronology invariant refuses before applying corrections to actual_fields.")


def authorization_cases(emit):
    renewal = runpy.run_path(str(REVIEW / "build-renewal-cases.py"))["renewal_result"]
    for condition in ["expiry", "supersession", "completion", "stopped"]:
        base = completion_base()
        permitted = permitted_proposal(base)
        prior = retained(permitted, permitted["permit"])
        if condition in {"expiry", "supersession"}:
            _, prior = clock_transition(prior, instant=permitted["permit"]["expires_at"])
            if condition == "supersession":
                event = copy.deepcopy(base["proposal_event"])
                authority = refresh(permitted["permit"]["authority_basis"], "2026-09-10T04:35:00Z", evaluation_point="PROPOSE")
                event.update(event_id="frr-renew-before-authorization", expected_state_revision=prior["state"]["revision"],
                    expected_state_digest=prior["state_digest"], authority_input=authority, clock_revision="2",
                    observation_digests=sorted(digest("authority-observation", row) for row in authority["observations"]))
                renewed = renewal(base, prior, event, expected_ready(authority, base["authority_result"]))
                prior = retained(renewed, permitted["permit"])
        else:
            base, permitted, prior = completion_dispatch()
            native = completion_native(base, prior, status="EFFECT_ESTABLISHED" if condition == "completion" else "OUTCOME_UNKNOWN")
            event = governed_effect_event(prior, prior, native, event_id="frr-close-before-authorization-" + condition)
            closed = terminal_effect_result(base, prior, event,
                classification="MATCHED" if condition == "completion" else "UNKNOWN",
                disposition="COMPLETED" if condition == "completion" else "OUTCOME_RETAINED",
                reason_codes=[] if condition == "completion" else ["UNKNOWN_OUTCOME"],
                occurrence_status=None if condition == "completion" else "OUTCOME_UNKNOWN", disputed=False,
                complete_disposition="SUCCEEDED" if condition == "completion" else None, route=condition == "completion")
            prior = retained(closed, permitted["permit"])
        event = authorization_event(base, prior, event_id="frr-ineligible-authorization-" + condition,
            intent="frr-ineligible-intent-" + condition)
        emit("step", step_input(base, prior["state"], event), stateful_refusal(prior["state"], "PREREQUISITE_MISSING"),
            ["LIFE-009A", "LIFE-008"], f"A new authorization after {condition} is ineligible under the exact retained permit and state. Current authority cannot revive expired, superseded, consumed or terminal dispatch permission.")
        forged = retained(authorization_result(base, prior, event), permitted["permit"])
        clock, _ = next_clock(base, forged, "frr-restart-ineligible-authorization-" + condition)
        emit("step", step_input(base, forged["state"], clock), stateful_refusal(forged["state"], "STATE_INVALID"),
            ["LIFE-009A", "LIFE-019"], f"A complete current authorization/evaluation/receipt/replay is appended after {condition}, with all digests and roots recomputed. Restart reconstructs eligibility at the appended event and rejects this unreachable state.")


def scalar_cases(emit):
    for kind, member, changed in [("IDENTITY", "nonnegative", True), ("IDENTITY", "unit", "unit-1"),
            ("STRING", "nonnegative", True), ("STRING", "unit", "unit-1"),
            ("BOOLEAN", "nonnegative", True), ("INTEGER", "unit", "unit-1"),
            ("INSTANT", "nonnegative", True), ("INSTANT", "unit", "unit-1")]:
        facts = history_fixture()
        slot = selected_slot(facts, "request-use")
        row = {"id": "zz-invalid-slot-type", "kind": kind, "nonnegative": False, "unit": None}
        row[member] = changed
        slot["types"].append(row)
        supplied = seed_request(facts, history_state(facts), "request-use", [], "frr-seed-invalid-scalar")
        emit("aggregate-step", supplied, reservation_refusal(supplied["state"], "STATE_INVALID"),
            ["RES-007A", "RES-WIRE-004", "WCS2-004"],
            f"The complete exclusive-slot scalar declaration has {kind} with illegal {member}:{changed}. The type is unused but all declarations require scalar admission. This malformed declaration belongs to the retained immutable revision-0 registry configuration. RESERVATION-RECORDS state reconstruction and EXCLUSIVE-KEY-HISTORY section 177 put STATE_INVALID before action-level TYPE_INVALID, despite exact registry, state and administration commitments.")


def referral_cases(emit):
    helpers = runpy.run_path(str(REVIEW / "build-equipment-referral-cases.py"))
    def definition(value):
        completion_definition_mutator(value)
        policy = value["steps"][0]["referral_policy"]
        completion_copy = copy.deepcopy(policy["completion"][0])
        completion_copy["id"] += "-copy"
        policy["completion"].append(completion_copy)
        policy["completion"].sort(key=lambda row: row["id"])
        common = {"destination_role": "reliability-supervisor", "queue": "maintenance-review",
            "purpose": "review-authority-failure", "safe_state": "no-entry-or-command", "via_role": None, "requirement_ids": []}
        policy["authority"] = [{"id": name, **common} for name in ["authority-owner", "authority-owner-copy"]]
    base = base_lifecycle(authority_mutator=completion_authority_mutator, definition_mutator=definition)
    permitted = permitted_proposal(base)
    for point in ["PROPOSE", "DISPATCH"]:
        before = base["clock_result"]["state"] if point == "PROPOSE" else permitted["state"]
        event = copy.deepcopy(base["proposal_event"]) if point == "PROPOSE" else authorization_event(base, permitted)
        event = helpers["fail_event"](event, "current-session")
        failure = source_refusal(event["authority_input"], "current-session", "SOURCE_OBSERVATION_RELATIONS")
        if point == "PROPOSE":
            from lifecycle_factory import withheld_proposal
            result = withheld_proposal(base, event, failure)
        else:
            result = authorization_result(base, permitted, event, refusal=failure)
        result = deduplicate_referrals(helpers["add_referrals"](base, before, event, result, failure, "current-session"))
        assert len(result["state"]["referrals"]) == 1
        emit("step", step_input(base, before, event), result, ["LIFE-006A", "AUTH-007"],
            "Two distinct selected authority route identifiers produce the same complete referral body. Referral identity excludes route id; state retains one unique referral_digest in the same withholding transition, with no delivery assertion.")
    gate = authorization_event(base, permitted)
    prior = retained(authorization_result(base, permitted, gate), permitted["permit"])
    authorization_digest = prior["state"]["authorizations"][0]["authorization_digest"]
    send = dispatch_event(base, prior, event_id="frr-referral-send", authorization_digest=authorization_digest)
    prior = retained(dispatch_result(prior, send, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED"), permitted["permit"])
    native = completion_native(base, prior, status="OUTCOME_UNKNOWN")
    event = governed_effect_event(prior, prior, native, event_id="frr-duplicate-completion-routes")
    result = deduplicate_referrals(terminal_effect_result(base, prior, event, classification="UNKNOWN",
        disposition="OUTCOME_RETAINED", reason_codes=["UNKNOWN_OUTCOME"], occurrence_status="OUTCOME_UNKNOWN", disputed=False))
    assert len(result["state"]["referrals"]) == 2
    emit("step", step_input(base, prior["state"], event), result, ["LIFE-006A", "LIFE-010"],
        "Three selected completion routes contain two identical bodies under different route ids. The two distinct referral bodies retain exactly two uniquely sorted digests alongside the single terminal cause, receipt and replay.")


def gate_cases(emit):
    authority = completion_base()["authority_input"]
    def selected(value, requirement_id):
        return next(row for row in value["envelope"]["source_observation_requirements"] if row["id"] == requirement_id)
    mutations = [
        ("missing-reference", lambda x: x["work_class"]["steps"][0]["dispatch_gate"].update(approval_requirement="missing-approval"), "REFERENCE_INVALID"),
        ("zero-duration", lambda x: x["work_class"]["steps"][0]["dispatch_gate"].update(authorization_seconds="0"), "SCHEMA_INVALID"),
        ("fixed-time", lambda x: selected(x, "approval").update(at="2026-09-10T04:30:00Z"), "UNSUPPORTED_RELATION"),
        ("propose-only", lambda x: selected(x, "approval").update(evaluation_point="PROPOSE"), "UNSUPPORTED_RELATION"),
        ("omitted-point", lambda x: selected(x, "approval").pop("evaluation_point"), "UNSUPPORTED_RELATION"),
        ("nonzero-freshness", lambda x: selected(x, "approval").update(freshness_seconds="1"), "UNSUPPORTED_RELATION"),
        ("wrong-purpose", lambda x: selected(x, "approval").update(purpose="SAFETY_HOLD"), "UNSUPPORTED_RELATION"),
        ("null-approval-id", lambda x: selected(x, "approval").update(record_id=None), "UNSUPPORTED_RELATION"),
        ("withdrawal-available", lambda x: selected(x, "approval-withdrawal").update(expected_status="AVAILABLE"), "UNSUPPORTED_RELATION"),
        ("policy-available", lambda x: selected(x, "policy-dr-withdrawal").update(expected_status="AVAILABLE"), "UNSUPPORTED_RELATION"),
        ("overlapping-inventory", lambda x: x["work_class"]["steps"][0]["dispatch_gate"].update(policy_withdrawal_requirements=["approval-withdrawal", "policy-dr-withdrawal", "policy-mcs-withdrawal"]), "INPUT_INVALID"),
    ]
    for name, mutate, code in mutations:
        value = copy.deepcopy(authority)
        mutate(value)
        value["envelope"].update(source_digest=digest("authority-source", value["source"]),
            work_class_digest=digest("authority-work-class", value["work_class"]))
        definition = {"schema": SCHEMA + "authority-definition", **{key: value[key] for key in ["source", "work_class", "envelope"]}}
        supplied = {"kind": "AUTHORITY_DEFINITION", "specification_pin": candidate_pin(),
            "artifact_bytes_base64": base64.b64encode(canonical_bytes(definition)).decode("ascii")}
        derivation = f"The isolated dispatch-gate declaration fault {name} is rebound in the complete authority definition. Earlier schema or missing-reference admission retains its code; other otherwise admitted gate constraints refuse UNSUPPORTED_RELATION before authority readiness. Provider coordinator identity is not inferred from approval query identity."
        if name == "overlapping-inventory":
            derivation = "The complete gate inventory repeats the singular approval-withdrawal requirement in its policy inventory. OBSERVATIONS-AND-DISPATCH section 9 retains AUTHORITY-CHECKS phase-1 duplicate-inventory INPUT_INVALID before the gate-specific UNSUPPORTED_RELATION rule. All complete authority-definition dependencies are rebound; the refusal has the public empty path."
        emit("validate", supplied, {"status": "REFUSED", "code": code, "path": ""}, ["AUTH-007", "AUTH-001"], derivation)


def gate_precedence_cases(emit):
    for fault, code in [("missing-capacity", "EVIDENCE_UNAVAILABLE"), ("unselected-source-provider", "DEPENDENCY_MISMATCH"),
            ("invalid-scalar", "TYPE_INVALID")]:
        def mutate(value, original):
            completion_authority_mutator(value, original)
            requirement = next(row for row in value["envelope"]["source_observation_requirements"] if row["id"] == "approval")
            requirement["purpose"] = "SAFETY_HOLD"
            if fault == "unselected-source-provider":
                requirement["provider"] = "unselected-source-provider"
            elif fault == "invalid-scalar":
                next(row for row in value["work_class"]["types"] if row["id"] == "BOOLEAN")["nonnegative"] = True
            value["observations"] = [observation(requirement, value)
                if row["query"].get("requirement_id") == requirement["id"] else row for row in value["observations"]]
        value = base_lifecycle(authority_mutator=mutate, definition_mutator=completion_definition_mutator)["authority_input"]
        if fault == "missing-capacity":
            selected = next(row for row in value["capacities"] if row["id"] == value["acts"][0]["capacity"])
            value["capacities"].remove(selected)
            capacity_digest = digest("authority-capacity", selected)
            value["host_selection"]["authenticated_records"] = [row for row in value["host_selection"]["authenticated_records"]
                if not (row["kind"] == "CAPACITY" and row["record_digest"] == capacity_digest)]
            derivation = "The admitted wrong-purpose approval gate also lacks a capacity body selected by the complete root inventory and an act. Its authenticated tuple is removed with that body, so no extra-tuple mismatch masks the missing evidence. AUTHORITY-CHECKS phase 2 orders EVIDENCE_UNAVAILABLE before UNSUPPORTED_RELATION; all surviving source/class/envelope/root/proposal/return commitments remain exact."
        elif fault == "unselected-source-provider":
            derivation = "The admitted wrong-purpose approval gate also selects a source-observation provider absent from the root's permitted providers. Its complete requirement and observation query use that provider and all source/class/envelope/root/proposal/return commitments are rebound. AUTHORITY-CHECKS phase 2 orders DEPENDENCY_MISMATCH before UNSUPPORTED_RELATION."
        else:
            derivation = "The wrong-purpose approval gate also has a known BOOLEAN scalar declaration with nonnegative:true. AUTHORITY-CHECKS applies AGG-001 scalar rules to all work-class types, allowing nonnegative only on INTEGER and DECIMAL declarations. All source/class/envelope/root/proposal/return commitments are rebound, so AUTHORITY-CHECKS phase-1 TYPE_INVALID precedes the phase-2 UNSUPPORTED_RELATION gate failure."
        emit("evaluate", {"kind": "AUTHORITY", "request": value}, authority_refusal([], code=code),
            ["AUTH-001", "AUTH-002", "AUTH-007"] + (["AGG-001"] if fault == "invalid-scalar" else []), derivation)


def derived_cases():
    cases = []
    def emit(operation, supplied, expected, requirements, derivation):
        cases.append(exact_case(f"C3-FRR-{len(cases) + 1:03d}", operation, supplied, expected, requirements, derivation))
    for build in [acknowledge_cases, no_effect_cases, correction_cases, authorization_cases, scalar_cases, referral_cases, gate_cases, gate_precedence_cases]:
        build(emit)
    return cases


def main():
    cases = derived_cases()
    for case in cases:
        write_canonical_json(GROUP / (case["id"] + ".json"), case)
    print({"cases": len(cases), "candidate_pin": candidate_pin(), "derivation": "normative-only; no consumer consulted"})


if __name__ == "__main__":
    main()
