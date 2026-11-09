#!/usr/bin/env python3
"""Build proposal and no-effect behavior after terminal lifecycle states."""

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
    effect_result,
    governed_effect_event,
    governed_native_evidence,
    no_effect_completion_authorization,
    permitted_proposal,
    stateful_refusal,
    step_input,
)


GROUP = CASES / "terminal-reconciliation"
DEADLINE = runpy.run_path(str(Path(__file__).with_name("build-deadline-order-cases.py")))


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def ordinary_setup() -> tuple[dict, dict, dict]:
    base = base_lifecycle()
    permitted = permitted_proposal(base)
    event = dispatch_event(base, permitted, event_id="dispatch-terminal", acknowledgement_status="NONE")
    dispatched = dispatch_result(permitted, event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")
    return base, permitted, dispatched


def main() -> None:
    base, permitted, dispatched = ordinary_setup()
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-before-d2-151")
    effect_event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-before-d2-151")
    completed = effect_result(
        base,
        permitted,
        dispatched,
        effect_event,
        classification="MATCHED",
        disposition="COMPLETED",
        reason_codes=[],
        occurrence_status=None,
        disputed=False,
        complete_disposition="SUCCEEDED",
        route=True,
    )
    proposal = copy.deepcopy(base["proposal_event"])
    proposal["event_id"] = "proposal-d2-151"
    proposal["expected_state_revision"] = completed["state"]["revision"]
    proposal["expected_state_digest"] = completed["state_digest"]
    emit(
        "D2-151",
        base,
        completed["state"],
        proposal,
        stateful_refusal(completed["state"], "INSTANCE_NOT_ACTIVE"),
        "The instance already completed and the named root occurrence is historical. After replay and binding admission, COMPLETE instance status refuses every new proposal before occurrence or authority evaluation.",
    )

    no_effect = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-before-d2-162",
        status="NO_EFFECT_ESTABLISHED",
    )
    authorization = no_effect_completion_authorization(base, permitted, dispatched, no_effect)
    no_effect_event = governed_effect_event(
        permitted,
        dispatched,
        no_effect,
        event_id="effect-before-d2-162",
        completion_authorization=authorization,
    )
    closed = effect_result(
        base,
        permitted,
        dispatched,
        no_effect_event,
        classification="NO_EFFECT_ESTABLISHED",
        disposition="STOPPED",
        reason_codes=["NO_EFFECT_ESTABLISHED"],
        occurrence_status=None,
        disputed=False,
        complete_disposition="NO_EFFECT",
        route=False,
        instance_status="STOPPED",
    )
    repeated = copy.deepcopy(no_effect)
    repeated["evidence_id"] = "evidence-d2-162"
    repeated["evidence_ref"] = "evidence-ref-d2-162"
    repeated_event = governed_effect_event(
        permitted,
        {"state": closed["state"]},
        repeated,
        event_id="effect-d2-162",
    )
    expected = effect_result(
        base,
        permitted,
        {"state": closed["state"]},
        repeated_event,
        classification="DUPLICATE",
        disposition="OUTCOME_RETAINED",
        reason_codes=["DUPLICATE_EVIDENCE"],
        occurrence_status=None,
        disputed=False,
    )
    emit(
        "D2-162",
        base,
        closed["state"],
        repeated_event,
        expected,
        "The new evidence identity and reference omit to the same native-evidence-fact bytes as the retained authorized no-effect conclusion. Duplicate classification precedes authorization, retains one duplicate outcome, and does not close or route the occurrence again.",
    )

    deadline_base, deadline_permitted, deadline_dispatched = DEADLINE["setup"]()
    expiry_event = DEADLINE["clock_event"](deadline_dispatched["state"], "clock-before-d2-185")
    expired = DEADLINE["expire"](deadline_base, deadline_dispatched["state"], expiry_event)
    evidence = governed_native_evidence(
        deadline_base,
        deadline_permitted,
        expired,
        evidence_id="evidence-d2-185",
        status="NO_EFFECT_ESTABLISHED",
        observed_at="2026-09-10T04:31:01Z",
    )
    event = governed_effect_event(
        deadline_permitted,
        expired,
        evidence,
        event_id="effect-d2-185",
        completion_authorization=None,
    )
    expected = effect_result(
        deadline_base,
        deadline_permitted,
        expired,
        event,
        classification="NO_EFFECT_ESTABLISHED",
        disposition="OUTCOME_RETAINED",
        reason_codes=["NO_EFFECT_ESTABLISHED"],
        occurrence_status=None,
        disputed=False,
    )
    emit(
        "D2-185",
        deadline_base,
        expired["state"],
        event,
        expected,
        "The occurrence already closed through deadline expiry, so the first affirmative no-effect fact carries null lifecycle completion authorization. It is retained without changing the EXPIRED completed row, expiry route, or terminal instance.",
    )

    print(json.dumps({"case_ids": ["D2-151", "D2-162", "D2-185"]}, indent=2))


if __name__ == "__main__":
    main()
