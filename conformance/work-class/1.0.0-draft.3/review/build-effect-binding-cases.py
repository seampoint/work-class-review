#!/usr/bin/env python3
"""Build exact governed-effect permit and dispatch binding vectors."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

from corpus_common import CASES, exact_case, write_canonical_json
from lifecycle_factory import (
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    permitted_proposal,
    stateful_refusal,
    step_input,
)


LOOPS = runpy.run_path(str(Path(__file__).with_name("build-loop-cases.py")))
GROUP = CASES / "effect-bindings"


def main() -> None:
    base = base_lifecycle(definition_mutator=LOOPS["loop_definition"])
    first_permitted = permitted_proposal(base)
    first_dispatch_event = dispatch_event(
        base,
        first_permitted,
        event_id="dispatch-before-d2-028-pass-1",
        acknowledgement_status="ACCEPTED",
    )
    first_dispatched = dispatch_result(
        first_permitted,
        first_dispatch_event,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    first_effect_event = LOOPS["effect_event"](
        base,
        first_permitted,
        first_dispatched,
        "D2-028-pass-1",
    )
    first_effect = LOOPS["loop_effect"](
        base,
        first_permitted,
        first_dispatched,
        first_effect_event,
        activate=True,
    )

    second_occurrence = first_effect["state"]["active"][0]["occurrence"]
    proposal, authority_result = LOOPS["event_for_occurrence"](
        base,
        first_effect["state"],
        second_occurrence,
        "D2-028-pass-2",
    )
    second_base = copy.deepcopy(base)
    second_base["proposal_event"] = proposal
    second_base["authority_input"] = proposal["authority_input"]
    second_base["authority_result"] = authority_result
    second_base["clock_result"] = {
        "state": first_effect["state"],
        "state_digest": first_effect["state_digest"],
        "role": first_effect["role"],
    }
    second_permitted = permitted_proposal(second_base, proposal)
    second_dispatch_event = dispatch_event(
        base,
        second_permitted,
        event_id="dispatch-before-d2-028-pass-2",
        acknowledgement_status="ACCEPTED",
    )
    second_dispatched = dispatch_result(
        second_permitted,
        second_dispatch_event,
        disposition="ACKNOWLEDGED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    second_dispatch_digest = next(
        row["dispatch_digest"]
        for row in second_dispatched["state"]["dispatches"]
        if row["event_id"] == second_dispatch_event["event_id"]
    )
    evidence = governed_native_evidence(
        base,
        second_permitted,
        second_dispatched,
        evidence_id="evidence-d2-028",
        native_operation_id="native-operation-d2-028-pass-2",
        dispatch_digest=second_dispatch_digest,
    )
    event = governed_effect_event(
        first_permitted,
        second_dispatched,
        evidence,
        event_id="effect-d2-028",
        dispatch_digest=second_dispatch_digest,
    )
    case = exact_case(
        "D2-028",
        "step",
        step_input(base, second_dispatched["state"], event),
        stateful_refusal(second_dispatched["state"], "BINDING_MISMATCH"),
        [],
        "The state retains both loop permits and the second occurrence's accepted dispatch. The event supplies the first occurrence's committed permit with the second occurrence's exact dispatch digest. Both records are individually known, but their exact permit and occurrence bindings differ, so LIFE-010 refuses the event before interpreting its otherwise closed native evidence.",
    )
    write_canonical_json(GROUP / "D2-028.json", case)
    print(json.dumps({"case_ids": ["D2-028"]}, indent=2))


if __name__ == "__main__":
    main()
