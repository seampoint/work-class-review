"""Derive bounded draft-3 foundation vectors without executing a consumer."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path

from authority_fixture import authority_refusal, authority_specimen
from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_budget_fixture import permitted_budget_proposal
from lifecycle_factory import base_lifecycle, replay_result, stateful_refusal, step_input
from checkpoint_reseal import reseal_last_transition
from reservation_fixture import fixture, host_and_event, request, reservation_record, transition, zero_state


GROUP = CASES / "equipment-foundation"
exclusive = runpy.run_path(str(Path(__file__).with_name("build-exclusive-key-cases.py")))
KEYS = exclusive["KEY_DEFINITION"]


def emit(case_id: str, operation: str, supplied: dict, expected: dict, requirements: list[str], derivation: str) -> None:
    write_canonical_json(GROUP / f"{case_id}.json", exact_case(case_id, operation, supplied, expected, requirements, derivation))


def key_configuration(facts: dict) -> None:
    facts["configuration"]["slots"] = []


def key_reservation(facts: dict, state: dict, event_id: str) -> tuple[dict, dict]:
    event, host = host_and_event(facts, "RESERVE", event_id, state["core"]["revision"], {
        "authority": facts["authority_a"], "histories": [],
        "exclusive_keys": copy.deepcopy(facts["authority_a_result"]["required_exclusive_keys"]),
    }, administration=False)
    core = copy.deepcopy(state["core"])
    record = reservation_record(facts, "authority_a", event_id)
    until = facts["authority_a"]["envelope"]["temporal_validity"]["valid_until"]
    if until is not None:
        record["permit_until"] = min(record["permit_until"], until)
    core["reservations"].append(record)
    core["exclusive_keys"] = exclusive["key_states"](facts, "authority_a", event_id, event_id)
    expected = transition(state, event, host, core, "RESERVED", reservation_id=event_id, authority_result=facts["authority_a_result"])
    return request(state, event, host), expected


def key_lifecycle() -> tuple[dict, dict, dict, dict]:
    def authority_mutator(supplied: dict, _original: dict) -> None:
        step = supplied["work_class"]["steps"][0]
        reference, _ = authority_specimen(shared_budget=False, exclusive_keys=KEYS)
        step["quantity_mode"] = "NONE"
        step["exclusive_keys"] = copy.deepcopy(KEYS)
        step["completion"] = copy.deepcopy(reference["work_class"]["steps"][0]["completion"])
        supplied["envelope"]["limits"]["per_action"] = []
        supplied["envelope"]["enforcement"]["mechanisms"] = ["ATOMIC_RESERVATION_TRANSITION", "AUTHORITY_BEFORE_RESERVATION"]
        supplied["envelope"]["temporal_validity"]["valid_until"] = "2026-09-10T04:32:00Z"

    base = base_lifecycle(shared_budget=False, authority_mutator=authority_mutator)
    facts = fixture(exclusive_keys=KEYS)
    key_configuration(facts)
    facts["authority_a"] = copy.deepcopy(base["authority_input"])
    facts["authority_a_result"] = copy.deepcopy(base["authority_result"])
    event = copy.deepcopy(base["proposal_event"])
    event["event_id"] = "propose-key-only"
    registry = zero_state(facts)
    registry_digest = digest("reservation-registry", facts["configuration"])
    reserve_id = digest("lifecycle-reservation-event", {
        "instance_id": event["instance_id"], "lifecycle_event_id": event["event_id"],
        "lifecycle_event_kind": "PROPOSE", "reservation_event_kind": "RESERVE", "registry_digest": registry_digest,
    })
    reserve_input, reserved = key_reservation(facts, registry, reserve_id)
    event["budget_inputs"] = [{"registry_digest": registry_digest, "affected_anchors": [], "expected_revision": "0", "request": reserve_input}]
    output = {"registry_digest": registry_digest, "affected_anchors": [], "result": reserved}
    expected = permitted_budget_proposal(base, event, output)
    permit = expected["permit"]
    # The fixture's five-minute step interval is capped by the two-minute grant.
    permit["expires_at"] = "2026-09-10T04:32:00Z"
    permit["permit_id"] = digest("permit", {key: value for key, value in permit.items() if key != "permit_id"})
    # Rebuild the transition with the rule-derived cap before any consumer runs.
    from lifecycle_factory import admitted_transition
    def mutate(state: dict) -> None:
        derived = expected["state"]
        for key in ("active", "total_actuations", "step_counters", "proposals", "permits"):
            state[key] = copy.deepcopy(derived[key])
        state["permits"] = [copy.deepcopy(permit)]
        state["proposals"][0]["permit_digest"] = permit["permit_id"]
    expected = admitted_transition(base["clock_result"]["state"], event, disposition="PERMITTED", reason_codes=[], details=[], permit=permit, budget_results=[output], mutate=mutate)
    return base, facts, event, expected


def main() -> None:
    facts = fixture(exclusive_keys=KEYS)
    key_configuration(facts)
    supplied, reserved = key_reservation(facts, zero_state(facts), "reserve-key-only")
    emit("C3-EF-001", "aggregate-step", supplied, reserved, ["RES-001A"], "A registry with no numerical slots and one exclusive slot reserves the declared key atomically. Its affected-anchor inventory is empty and its owner includes both instance and occurrence.")

    wrong_principal = copy.deepcopy(facts)
    wrong_principal["configuration"]["principal"] = "other-principal"
    wrong_input, _ = key_reservation(wrong_principal, zero_state(wrong_principal), "reserve-wrong-principal")
    wrong_state = wrong_input["state"]
    emit("C3-EF-002", "aggregate-step", wrong_input, {"status": "REFUSED", "code": "DEPENDENCY_MISMATCH", "path": "", "state": wrong_state, "state_digest": digest("reservation-state", wrong_state)}, ["RES-001A"], "Registry principal differs from the authorized principal. Dependency binding refuses before occupancy and returns the unchanged registry.")

    for case_id, mode, retain_bound in (("C3-EF-003", "NONE", True), ("C3-EF-004", "BOUNDED", False)):
        def change(supplied: dict, _original: dict) -> None:
            supplied["work_class"]["steps"][0]["quantity_mode"] = mode
            if not retain_bound:
                supplied["envelope"]["limits"]["per_action"] = []
        authority, _ = authority_specimen(shared_budget=False, mutator=change)
        emit(case_id, "evaluate", {"kind": "AUTHORITY", "request": authority}, authority_refusal([], code="BINDING_MISMATCH"), ["AUTH-001"], "NONE refuses a numerical per-action limit." if mode == "NONE" else "BOUNDED refuses an envelope with no per-action bound and no shared-budget anchor.")

    base, facts, event, permitted = key_lifecycle()
    before = base["clock_result"]["state"]
    emit("C3-EF-005", "step", step_input(base, before, event), permitted, ["LIFE-007", "LIFE-008", "RES-001A"], "A quantity-free operation retains its keys and completion carrier in the authority projection, supplies one key-only registry transition and receives a permit capped by the fixed approval end.")
    emit("C3-EF-006", "step", step_input(base, permitted["state"], event), replay_result(permitted["state"], event["event_id"]), ["LIFE-004", "LIFE-008"], "A fresh consumer rechecks the complete key-only permit and retained registry result before returning the exact proposal replay.")
    missing = copy.deepcopy(event)
    missing["budget_inputs"] = []
    emit("C3-EF-007", "step", step_input(base, before, missing), stateful_refusal(before, "BINDING_MISMATCH"), ["LIFE-007"], "An empty numerical anchor inventory does not excuse the registry transition required by the nonempty exclusive-key declaration.")

    forged = copy.deepcopy(permitted["state"])
    original_id = forged["permits"][0]["permit_id"]
    forged["permits"][0]["expires_at"] = "2026-09-10T04:34:00Z"
    forged_id = digest("permit", {key: value for key, value in forged["permits"][0].items() if key != "permit_id"})
    forged["permits"][0]["permit_id"] = forged_id
    # Rehash every retained link so expiry derivation, rather than hash syntax, is decisive.
    def replace(value):
        if isinstance(value, list):
            return [replace(row) for row in value]
        if isinstance(value, dict):
            return {key: replace(row) for key, row in value.items()}
        return forged_id if value == original_id else value
    forged = replace(forged)
    forged["replays"][-1]["permit"] = copy.deepcopy(forged["permits"][0])
    reseal_last_transition(forged)
    registry_input = event["budget_inputs"][0]
    registry_echo = {"registry_digest": registry_input["registry_digest"], "affected_anchors": [], "state": copy.deepcopy(registry_input["request"]["state"]), "state_digest": registry_input["request"]["state_digest"]}
    emit("C3-EF-008", "step", step_input(base, forged, event), stateful_refusal(forged, "STATE_INVALID", [registry_echo]), ["LIFE-004", "LIFE-008"], "A rehashed retained permit extending beyond the derived minimum expiry is impossible state. The retained grant and reservation both end at 04:32, before the five-minute step ceiling. Restart must reject the extension before replay and echo the supplied registry unchanged.")

    from reservation_fixture import native, effect_record
    # Use the independently reserved key-only state, with its original fixture identity.
    direct_facts = fixture(exclusive_keys=KEYS)
    key_configuration(direct_facts)
    _direct_input, direct_reserved = key_reservation(direct_facts, zero_state(direct_facts), "reserve-attribution-check")
    completion = native(direct_facts, "EFFECT", "native-attribution-mismatch", reservation_id="reserve-attribution-check")
    completion["provider"] = "card-provider"
    completion["source"] = "card-system"
    completion["request"]["fields"][0]["value"]["value"] = "151"
    settle, host = host_and_event(direct_facts, "SETTLE", "settle-attribution-check", "1", {"native": completion, "histories": []}, administration=False)
    mismatch_core = copy.deepcopy(direct_reserved["state"]["core"])
    mismatch_core["reservations"][0]["status"] = "DISPUTED"
    mismatch_core["effects"] = [effect_record(completion, "DISPUTED", "UNEXPECTED_EFFECT", affected_anchors=[])]
    expected = transition(direct_reserved["state"], settle, host, mismatch_core, "EFFECT_DISPUTED", reservation_id="reserve-attribution-check", reasons=["UNEXPECTED_EFFECT"])
    emit("C3-EF-009", "aggregate-step", request(direct_reserved["state"], settle, host), expected, ["RES-001A"], "The observed request matches the retained reservation and the caller asserts no completion mismatch, but the attributed request changes amount. The consumer compares both complete requests independently, records dispute and retains the key as HELD.")


if __name__ == "__main__":
    main()
