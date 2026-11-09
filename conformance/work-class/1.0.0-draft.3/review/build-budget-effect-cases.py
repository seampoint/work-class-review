#!/usr/bin/env python3
"""Build budget-backed effect-observation vectors from LIFE-010 and WCS2-006.

No budget-backed EFFECT_OBSERVED case existed in the corpus before this builder: every
prior effect case carried an empty budget_inputs array and a null clock_revision. The
shared path here dispatches a budget-backed permit and embeds a SETTLE reservation event
in the effect, so the LIFE-010 rules that apply only when budget_inputs is nonempty
become reachable. Constructors are local so existing case bytes are unchanged.
"""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_factory import (
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    stateful_refusal,
    step_input,
)
from lifecycle_budget_fixture import initial_budget_success
from reservation_fixture import (
    host_and_event,
    native as native_record,
    request as reservation_request,
)


GROUP = CASES / "budget-effects"

# The registry clock source is authority-clock and the retained available clock for it
# is revision 1 at 04:30:00Z, so that instant is the selected latest retained registry
# clock for every case in this builder.
REGISTRY_CLOCK_REVISION = "1"
REGISTRY_CLOCK_INSTANT = "2026-09-10T04:30:00Z"


def settle_budget_input(facts: dict, registry_state: dict, reservation_id: str, effect_event_id: str, evidence: dict) -> dict:
    """Embed one SETTLE reservation event for a governed effect.

    LIFE-010 fixes the embedded record: id, provider, source, evidence reference, actual fields and
    collections copy the native evidence, and effect_id and occurred_at come from it for EFFECT. A
    record that does not copy them is a second fault that a clock refusal would hide.
    """
    registry_digest = digest("reservation-registry", registry_state["core"]["configuration"])
    reservation_event_id = digest(
        "lifecycle-reservation-event",
        {
            "instance_id": facts["authority_a"]["proposal"]["instance"],
            "lifecycle_event_id": effect_event_id,
            "lifecycle_event_kind": "EFFECT_OBSERVED",
            "reservation_event_kind": "SETTLE",
            "registry_digest": registry_digest,
        },
    )
    record = native_record(facts, "EFFECT", evidence["evidence_id"], reservation_id=reservation_id)
    record["provider"] = evidence["provider"]
    record["source"] = evidence["source"]
    record["evidence_ref"] = evidence["evidence_ref"]
    record["actual_fields"] = copy.deepcopy(evidence["actual_fields"])
    record["collections"] = copy.deepcopy(evidence["collections"])
    record["rules_out_past_and_future_effects"] = evidence["rules_out_past_and_future_effects"]
    record["effect_id"] = evidence["native_operation_id"]
    record["occurred_at"] = evidence["event_time"]
    event, host = host_and_event(
        facts,
        "SETTLE",
        reservation_event_id,
        registry_state["core"]["revision"],
        {"native": record, "histories": [facts["history"]]},
        event_clock=facts["clock"],
        administration=False,
    )
    return {
        "registry_digest": registry_digest,
        "affected_anchors": ["license-spend"],
        "expected_revision": registry_state["core"]["revision"],
        "request": reservation_request(registry_state, event, host),
    }


def dispatched_budget_permit(instance_id: str, case_id: str):
    """A budget-backed permit that has been dispatched SENT."""
    base, facts, proposal, permitted = initial_budget_success(
        instance_id=instance_id, event_id=f"proposal-{case_id.lower()}"
    )
    sent_event = dispatch_event(
        base,
        permitted,
        event_id=f"dispatch-{case_id.lower()}",
        attempt_status="SENT",
        attempted_at=REGISTRY_CLOCK_INSTANT,
        clock_revision=REGISTRY_CLOCK_REVISION,
    )
    dispatched = dispatch_result(
        permitted,
        sent_event,
        disposition="DISPATCH_RECORDED",
        reasons=[],
        occurrence_status="DISPATCHED",
    )
    registry_state = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    return base, facts, permitted, dispatched, registry_state, reservation_id


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    produced = []

    # D2-227 -- budget-backed effect observed after the selected registry clock.
    base, facts, permitted, dispatched, registry_state, reservation_id = dispatched_budget_permit(
        "case-d2-227", "D2-227"
    )
    event_id = "effect-d2-227"
    evidence = governed_native_evidence(
        base,
        permitted,
        dispatched,
        evidence_id="evidence-d2-227",
        status="EFFECT_ESTABLISHED",
        event_time=REGISTRY_CLOCK_INSTANT,
        # Later than the selected latest retained registry clock at 04:30:00Z.
        observed_at="2026-09-10T04:31:00Z",
    )
    budget_input = settle_budget_input(facts, registry_state, reservation_id, event_id, evidence)
    event = governed_effect_event(
        permitted,
        dispatched,
        evidence,
        event_id=event_id,
        budget_inputs=[budget_input],
        clock_revision=REGISTRY_CLOCK_REVISION,
    )
    emit(
        "D2-227",
        base,
        dispatched["state"],
        event,
        stateful_refusal(
            dispatched["state"],
            "CLOCK_INVALID",
            # An admission refusal returns the supplied registry state unchanged, one row
            # per affected registry, so the host can resubmit after admitting a clock.
            budget_states=[{
                "affected_anchors": copy.deepcopy(budget_input["affected_anchors"]),
                "registry_digest": budget_input["registry_digest"],
                "state": copy.deepcopy(registry_state),
                "state_digest": digest("reservation-state", registry_state),
            }],
        ),
        "LIFE-010 makes clock_revision nonnull exactly when budget_inputs is nonempty, and it identifies the latest retained available lifecycle clock for the registry clock source, here revision 1 at 04:30:00Z. The evidence timeline rule then requires native_evidence.observed_at to be no later than that selected clock for every budget-backed effect. The observation at 04:31:00Z is later, so the transition is CLOCK_INVALID. PROTOCOL places CLOCK_INVALID in the common lifecycle admission-refusal vocabulary, so no proposal record, outcome or decision receipt is appended and the supplied work and registry states are returned unchanged. WCS2-006 leaves retention of the raw evidence and resubmission after admitting a current clock to the host, outside the consumer result.",
    )
    produced.append("D2-227")

    print(json.dumps({"case_ids": produced, "count": len(produced), "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
