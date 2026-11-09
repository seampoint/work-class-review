#!/usr/bin/env python3
"""Build atomic structured-parallel entry and preflight-limit vectors."""

from __future__ import annotations

import copy
import json

from composition_fixture import add_authority_operations, parallel_definition, parallel_entry_result
from corpus_common import CASES, exact_case, write_canonical_json
from lifecycle_factory import (
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    permitted_proposal,
    step_input,
)


GROUP = CASES / "parallel-entry"


def definition_mutator(
    branches: list[str],
    *,
    activation_limit: str | None = None,
    occurrence_limit_step: str | None = None,
):
    parallel = parallel_definition(branches)

    def mutate(definition: dict) -> None:
        parallel(definition)
        if activation_limit is not None:
            definition["limits"]["maximum_activations"] = activation_limit
        if occurrence_limit_step is not None:
            limit = next(
                row
                for row in definition["occurrence_limits"]
                if row["step_id"] == occurrence_limit_step
            )
            limit["maximum"] = "0"
            definition["occurrence_limits"].sort(key=lambda row: row["step_id"].encode("utf-8"))

    return mutate


def setup(case_id: str, branches: list[str], **definition_options) -> tuple[dict, dict, dict, dict]:
    base = base_lifecycle(
        authority_mutator=add_authority_operations(branches),
        definition_mutator=definition_mutator(branches, **definition_options),
    )
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-before-" + case_id.lower(), acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-" + case_id.lower())
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-" + case_id.lower())
    return base, permitted, dispatched, event


def emit(case_id: str, base: dict, dispatched: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, dispatched["state"], event), expected, [], derivation),
    )


def main() -> None:
    branches = ["branch-a", "branch-b"]
    for case_id, derivation in [
        (
            "D2-050",
            "The matched root effect selects the one sequence relationship into parallel-split. Both branch heads fit their occurrence, activation and active-obligation limits. One atomic transition completes the root and creates pass 1, two OPEN obligations and their two exact active occurrences in branch source order.",
        ),
        (
            "D2-141",
            "The matching root effect enters the two-branch structured block. The immutable source frontier is the root occurrence, and the same event digest binds both obligations and branch activations. The instance remains ACTIVE while both exact obligations are OPEN.",
        ),
    ]:
        base, _permitted, dispatched, event = setup(case_id, branches)
        expected = parallel_entry_result(base, dispatched, event, branches)
        emit(case_id, base, dispatched, event, expected, derivation)

    for case_id, limited_branches, limited_step, derivation in [
        (
            "D2-051",
            ["branch-a", "branch-b"],
            "branch-b",
            "The matched root effect reaches the parallel split, but preflight finds that branch-b would create occurrence one against its declared maximum zero. The transition still retains the established root effect and closes the root occurrence, then stops the instance without creating a pass, branch occurrence, or obligation.",
        ),
        (
            "D2-074",
            ["branch-a", "branch-b", "branch-c"],
            "branch-b",
            "The three-child parallel entry is one atomic structural action. Although branch-a is individually admissible, the middle branch-b would create occurrence one against maximum zero. Preflight stops the whole entry without creating any branch occurrence, obligation, or partial pass.",
        ),
    ]:
        base, _permitted, dispatched, event = setup(
            case_id,
            limited_branches,
            occurrence_limit_step=limited_step,
        )
        expected = parallel_entry_result(
            base,
            dispatched,
            event,
            limited_branches,
            stop_step=limited_step,
        )
        emit(case_id, base, dispatched, event, expected, derivation)

    print(json.dumps({"case_ids": ["D2-050", "D2-051", "D2-074", "D2-141"]}, indent=2))


if __name__ == "__main__":
    main()
