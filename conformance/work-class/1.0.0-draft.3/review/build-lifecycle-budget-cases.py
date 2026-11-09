#!/usr/bin/env python3
"""Build composite proposal and shared-reservation vectors from the frozen rules."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_budget_fixture import (
    budget_lifecycle,
    initial_budget_success,
    permitted_budget_proposal,
    reserve_for_proposal,
    withheld_budget_proposal,
)
from lifecycle_factory import replay_result, stateful_refusal, step_input
from reservation_fixture import registered_state


GROUP = CASES / "lifecycle-budget"


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def main() -> None:
    base, facts, proposal, accepted = initial_budget_success()
    before = base["clock_result"]["state"]
    emit(
        "D2-018",
        base,
        before,
        proposal,
        accepted,
        "The current authority result requires license-spend. The one registry-scoped RESERVE input selects that exact anchor, revision, authority proposal, authority clock and complete history. Committed 800 plus new unsettled 150 satisfies the inclusive 1000 cap. The lifecycle and registry commit one permit, reservation and both next states atomically.",
    )

    emit(
        "D2-058",
        base,
        accepted["state"],
        proposal,
        replay_result(accepted["state"], proposal["event_id"]),
        "A fresh consumer receives the complete state returned by D2-018 and the byte-identical retained proposal event. LIFE-004 resolves the exact event replay before current revision admission and returns the retained decision, permit, registry transition, state and transaction commitments with replay true.",
    )

    base_121, facts_121, proposal_121, accepted_121 = initial_budget_success(event_id="proposal-d2-121")
    emit(
        "D2-121",
        base_121,
        base_121["clock_result"]["state"],
        proposal_121,
        accepted_121,
        "The successful registry-scoped RESERVE creates one OPEN reservation, advances the registry from revision 1 to 2, and returns that reservation identifier and receipt digest in the permit budget row. The same one transition records the permit and registry result in work state.",
    )

    base_first, facts_first, first_proposal, first_accepted = initial_budget_success(event_id="proposal-first-150")
    shared_state = first_accepted["budget_results"][0]["result"]["state"]
    base_second, facts_second = budget_lifecycle(instance_id="case-2")
    second_proposal = copy.deepcopy(base_second["proposal_event"])
    second_proposal["event_id"] = "proposal-second-150"
    budget_input, budget_output, _ = reserve_for_proposal(
        base_second,
        facts_second,
        shared_state,
        second_proposal,
        total="1100",
        decision="WITHHELD",
    )
    second_proposal["budget_inputs"] = [budget_input]
    withheld = withheld_budget_proposal(base_second, second_proposal, budget_output)
    emit(
        "D2-019",
        base_second,
        base_second["clock_result"]["state"],
        second_proposal,
        withheld,
        "The shared registry already retains the first instance's unsettled 150 reservation. For the second instance, committed 800 plus distinct unsettled 150 plus new 150 equals 1100, which violates the inclusive 1000 bound. The registry advances with a WITHHELD receipt but creates no reservation; the lifecycle records the budget withholding and no permit.",
    )

    base_violated, facts_violated = budget_lifecycle()
    facts_violated["history"]["journal"][0]["event"]["fields"][0]["value"]["value"] = "900"
    registry_violated = registered_state(facts_violated)
    proposal_violated = copy.deepcopy(base_violated["proposal_event"])
    proposal_violated["event_id"] = "proposal-bound-violated"
    budget_input, budget_output, _ = reserve_for_proposal(
        base_violated,
        facts_violated,
        registry_violated,
        proposal_violated,
        total="1050",
        decision="WITHHELD",
    )
    proposal_violated["budget_inputs"] = [budget_input]
    withheld = withheld_budget_proposal(base_violated, proposal_violated, budget_output)
    emit(
        "D2-021",
        base_violated,
        base_violated["clock_result"]["state"],
        proposal_violated,
        withheld,
        "The complete current history contributes 900 to the selected partition and the proposal contributes 150. The exact 1050 accumulator violates the 1000 upper bound. The registry records WITHHELD without a reservation, and the lifecycle records BOUND_VIOLATED plus BUDGET_WITHHELD without creating a permit.",
    )

    base_119, facts_119 = budget_lifecycle()
    registry_119 = registered_state(facts_119)
    proposal_119 = copy.deepcopy(base_119["proposal_event"])
    proposal_119["event_id"] = "proposal-two-registry-inputs"
    budget_input_119, _budget_output_119, _ = reserve_for_proposal(
        base_119,
        facts_119,
        registry_119,
        proposal_119,
    )
    proposal_119["budget_inputs"] = [copy.deepcopy(budget_input_119), copy.deepcopy(budget_input_119)]
    emit(
        "D2-119",
        base_119,
        base_119["clock_result"]["state"],
        proposal_119,
        {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
        "The closed PROPOSE shape admits at most one registry-scoped budget input. Supplying the same complete registry input twice is a schema failure before a stateful request is admitted, so the response is the generic shape refusal and carries no work-state or budget-state echo.",
    )

    base_194, facts_194 = budget_lifecycle()
    facts_194["budget"]["reservation_policy"]["settlement"] = {
        "provider": "other-provider",
        "source": "other-ledger",
    }
    budget_digest_194 = digest("budget-definition", facts_194["budget"])
    facts_194["authorizations"][0]["budget_digest"] = budget_digest_194
    facts_194["history"]["budget_digest"] = budget_digest_194
    registry_194 = registered_state(facts_194)
    proposal_194 = copy.deepcopy(base_194["proposal_event"])
    proposal_194["event_id"] = "proposal-incompatible-completion-carrier"
    budget_input_194, _budget_output_194, _ = reserve_for_proposal(
        base_194,
        facts_194,
        registry_194,
        proposal_194,
    )
    proposal_194["budget_inputs"] = [budget_input_194]
    registry_echo_194 = {
        "registry_digest": budget_input_194["registry_digest"],
        "affected_anchors": copy.deepcopy(budget_input_194["affected_anchors"]),
        "state": copy.deepcopy(registry_194),
        "state_digest": digest("reservation-state", registry_194),
    }
    emit(
        "D2-194",
        base_194,
        base_194["clock_result"]["state"],
        proposal_194,
        stateful_refusal(base_194["clock_result"]["state"], "UNSUPPORTED_RELATION", [registry_echo_194]),
        "The active step requires the registered license-spend budget, but that budget's immutable settlement provider and source differ from the step's completion-effect carrier. LIFE-007 rejects the relationship before reservation evaluation and returns both supplied states unchanged.",
    )

    print(json.dumps({"case_ids": ["D2-018", "D2-019", "D2-021", "D2-058", "D2-119", "D2-121", "D2-194"]}, indent=2))


if __name__ == "__main__":
    main()
