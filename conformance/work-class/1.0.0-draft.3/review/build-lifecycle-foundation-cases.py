#!/usr/bin/env python3
"""Build lifecycle admission, restart, and authority-only proposal vectors."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from fixture_factory import occurrence
from lifecycle_factory import base_lifecycle, permitted_proposal, state_digest, stateful_refusal, step_input


from checkpoint_reseal import reseal_last_transition


def build() -> list[dict]:
    base = base_lifecycle()
    admitted_state = base["clock_result"]["state"]
    proposal = base["proposal_event"]
    accepted = permitted_proposal(base)
    cases = []

    stale = copy.deepcopy(proposal)
    stale["event_id"] = "proposal-stale-revision"
    stale["expected_state_revision"] = "0"
    cases.append(
        exact_case(
            "D2-012",
            "step",
            step_input(base, admitted_state, stale),
            stateful_refusal(admitted_state, "REVISION_CONFLICT"),
            ["LIFE-004"],
            "The supplied state is intact, but the new event selects revision 0 after the admitted clock decision created revision 1. Revision refusal leaves the state unchanged.",
        )
    )

    foreign = copy.deepcopy(proposal)
    foreign["event_id"] = "proposal-other-instance"
    foreign["instance_id"] = "case-2"
    foreign["occurrence"] = occurrence(
        base["definition_digest"],
        "case-2",
        proposal["occurrence"]["step_id"],
    )
    cases.append(
        exact_case(
            "D2-013",
            "step",
            step_input(base, admitted_state, foreign),
            stateful_refusal(admitted_state, "BINDING_MISMATCH"),
            ["LIFE-004"],
            "The complete event occurrence and event instance agree with each other but identify case-2, while the admitted work state identifies case-1. Instance binding fails before authority evaluation.",
        )
    )

    cases.append(
        exact_case(
            "D2-017",
            "step",
            step_input(base, admitted_state, proposal),
            accepted,
            ["LIFE-005", "LIFE-007"],
            "The exact active occurrence, native request, executor, credentials, authority input, observation digests, and retained available authority clock all agree. No shared budget is declared, so the transition creates the authority-only permit.",
        )
    )

    corrupted_state = copy.deepcopy(admitted_state)
    corrupted_state["total_activations"] = "2"
    corrupted_input = step_input(base, corrupted_state, proposal)
    corrupted_input["state_digest"] = base["clock_result"]["state_digest"]
    corrupted_input["event"]["expected_state_digest"] = corrupted_input["state_digest"]
    cases.append(
        exact_case(
            "D2-059",
            "step",
            corrupted_input,
            {
                "status": "REFUSED",
                "profile": admitted_state["profile"],
                "role": admitted_state["role"],
                "code": "STATE_INVALID",
                "path": "",
                "state": corrupted_state,
                "state_digest": corrupted_input["state_digest"],
                "budget_states": [],
            },
            ["LIFE-019", "WCS2-002"],
            "The supplied complete state changes total_activations without changing its supplied digest. State identity admission fails before the proposal is considered.",
        )
    )

    replay_corrupt = copy.deepcopy(admitted_state)
    replay_corrupt["replays"][0]["transaction_digest"] = "sha256:" + "f" * 64
    replay_corrupt_digest = state_digest(replay_corrupt)
    replay_event = copy.deepcopy(proposal)
    replay_event["event_id"] = "proposal-after-corrupt-replay"
    replay_event["expected_state_digest"] = replay_corrupt_digest
    cases.append(
        exact_case(
            "D2-090",
            "step",
            step_input(base, replay_corrupt, replay_event),
            stateful_refusal(replay_corrupt, "STATE_INVALID"),
            ["LIFE-019", "WCS2-002"],
            "The state identity projection omits retained transaction_digest, so its outer state digest remains valid. Independent replay-record verification detects the changed transaction commitment.",
        )
    )

    broken_reverse = copy.deepcopy(accepted["state"])
    broken_reverse["permits"] = []
    reseal_last_transition(broken_reverse)
    broken_digest = state_digest(broken_reverse)
    broken_event = copy.deepcopy(proposal)
    broken_event["event_id"] = "proposal-after-missing-permit"
    broken_event["expected_state_revision"] = broken_reverse["revision"]
    broken_event["expected_state_digest"] = broken_digest
    cases.append(
        exact_case(
            "D2-116",
            "step",
            step_input(base, broken_reverse, broken_event),
            stateful_refusal(broken_reverse, "STATE_INVALID"),
            ["LIFE-019"],
            "The retained PERMITTED proposal names a permit digest, but the corresponding complete permit is absent. The last receipt and replay are recommitted to the changed state and the outer state identity is recomputed, so no stale commitment is the fault; neither can make the broken reverse link admissible.",
        )
    )

    changed_evidence = copy.deepcopy(admitted_state)
    changed_evidence["deployment_authorization_evidence"]["status"] = "PENDING"
    changed_evidence_digest = state_digest(changed_evidence)
    evidence_event = copy.deepcopy(proposal)
    evidence_event["event_id"] = "proposal-after-deployment-evidence-change"
    evidence_event["expected_state_digest"] = changed_evidence_digest
    cases.append(
        exact_case(
            "D2-214",
            "step",
            step_input(base, changed_evidence, evidence_event),
            stateful_refusal(changed_evidence, "STATE_INVALID"),
            ["LIFE-003", "LIFE-019"],
            "The complete retained deployment evidence changes to PENDING while its stored evidence digest and authorization binding remain the old values. The outer state digest is recomputed, so the inner retained binding is the decisive state defect.",
        )
    )

    profile_input = step_input(base, admitted_state, proposal)
    profile_input["profile"] = "CHOICE_LOOPS"
    profile_input["role"] = "CHOICE_LOOP_RUNTIME"
    cases.append(
        exact_case(
            "D2-223",
            "step",
            profile_input,
            {
                **stateful_refusal(admitted_state, "BINDING_MISMATCH"),
                "profile": "CHOICE_LOOPS",
                "role": "CHOICE_LOOP_RUNTIME",
            },
            ["LIFE-002", "WCS2-012"],
            "The request's profile and role form an admitted pair but differ from both the LINEAR definition and retained state pair. Exact profile-role binding fails.",
        )
    )

    cases.append(
        exact_case(
            "D2-266",
            "step",
            step_input(base, admitted_state, proposal),
            accepted,
            ["LIFE-007", "LIFE-014"],
            "The deployed lower-profile state began with no initial lifecycle clocks. Its retained first CLOCK decision introduced authority-clock revision 1, and the proposal selects that exact clock for current authority and permit construction.",
        )
    )
    return cases


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "lifecycle-foundation" / f"{case['id']}.json", case)
    print(json.dumps({"case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
