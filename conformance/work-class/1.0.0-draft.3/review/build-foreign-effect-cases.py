#!/usr/bin/env python3
"""Build authority-only foreign-effect retention and admission cases."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_factory import admitted_transition, base_lifecycle, state_digest, stateful_refusal, step_input


GROUP = CASES / "foreign-effects"


def native_evidence(base: dict, case_id: str, *, status: str = "EFFECT_ESTABLISHED", event_time: str | None = "2026-09-10T04:30:00Z", observed_at: str = "2026-09-10T04:30:00Z") -> dict:
    proposal = base["proposal_event"]
    attributed = {
        "work_class": base["definition"]["id"],
        "instance": proposal["instance_id"],
        "occurrence": proposal["occurrence"]["occurrence_id"],
        "step": proposal["occurrence"]["step_id"],
        "operation": proposal["native_request"]["operation"],
        "interface": proposal["native_request"]["interface"],
        "fields": copy.deepcopy(proposal["native_request"]["fields"]),
    }
    actual = []
    if status == "EFFECT_ESTABLISHED":
        actual = copy.deepcopy(proposal["native_request"]["fields"]) + [
            {"name": "status", "value": {"type_ref": "STRING", "value": "ISSUED"}}
        ]
        actual.sort(key=lambda row: row["name"].encode("utf-8"))
    return {
        "evidence_id": "evidence-" + case_id.lower(),
        "native_operation_id": "foreign-native-operation",
        "provider": "card-provider",
        "source": "card-system",
        "record_type": "card-result" if status != "NO_EFFECT_ESTABLISHED" else "card-no-effect",
        "record_digest": digest("provider-native-record", {"record": case_id}),
        "evidence_ref": "evidence-ref-" + case_id.lower(),
        "attributed_request": attributed,
        "native_request_digest": digest("native-request", attributed),
        "status": status,
        "actual_fields": actual,
        "collections": [],
        "event_time": event_time if status == "EFFECT_ESTABLISHED" else None,
        "observed_at": observed_at,
        "rules_out_past_and_future_effects": status == "NO_EFFECT_ESTABLISHED",
    }


def event(state: dict, evidence: dict, case_id: str) -> dict:
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "effect-" + case_id.lower(),
        "kind": "EFFECT_OBSERVED",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "permit": None,
        "dispatch_digest": None,
        "native_evidence": copy.deepcopy(evidence),
        "completion_authorization": None,
        "reservation_id": None,
        "affected_budget_anchors": [],
        "budget_inputs": [],
        "clock_revision": None,
        "activation_clocks": [],
    }


def foreign_outcome(event_value: dict, *, classification: str = "FOREIGN", disputed: bool = True) -> dict:
    without_digest = {
        "kind": "FOREIGN",
        "event_id": event_value["event_id"],
        "event_digest": digest("runtime-event", event_value),
        "permit_digest": None,
        "dispatch_digest": None,
        "dispatch_attempt_digest": None,
        "native_evidence": copy.deepcopy(event_value["native_evidence"]),
        "classification": classification,
        "affected_budget_anchors": copy.deepcopy(event_value["affected_budget_anchors"]),
        "reservation_receipt_digests": [],
        "conflicts_with_evidence_ids": [],
        "disputed": disputed,
    }
    return {"outcome_digest": digest("outcome", without_digest), **without_digest}


def transition(state: dict, event_value: dict, *, classification: str, disposition: str, reason_codes: list[str]) -> dict:
    outcome = foreign_outcome(event_value, classification=classification)

    def mutate(next_state: dict) -> None:
        next_state["outcomes"].append(outcome)
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    return admitted_transition(
        state,
        event_value,
        disposition=disposition,
        reason_codes=reason_codes,
        details=[{"kind": "EFFECT", "classification": classification, "evidence_id": event_value["native_evidence"]["evidence_id"]}],
        mutate=mutate,
    )


def repeated_identity_transition(state: dict, event_value: dict) -> dict:
    """LIFE-013: a repeated evidence identity adds no outcome row, on the foreign path too."""
    return admitted_transition(
        state,
        event_value,
        disposition="OUTCOME_RETAINED",
        reason_codes=["DUPLICATE_EVIDENCE"],
        details=[{"kind": "EFFECT", "classification": "DUPLICATE", "evidence_id": event_value["native_evidence"]["evidence_id"]}],
        mutate=lambda next_state: None,
    )


def emit(case_id: str, base: dict, state: dict, event_value: dict, expected: dict, derivation: str, requirements: list[str] | None = None) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event_value), expected, requirements or [], derivation),
    )


def main() -> None:
    base = base_lifecycle()
    state = base["clock_result"]["state"]

    evidence = native_evidence(base, "D2-118")
    first_event = event(state, evidence, "D2-118")
    first_result = transition(state, first_event, classification="FOREIGN", disposition="DISPUTED", reason_codes=["FOREIGN_EFFECT"])
    emit(
        "D2-118",
        base,
        state,
        first_event,
        first_result,
        "The governed branch is absent, so the well-formed attributable authority-only effect is foreign. With no shared budget the exact affected-anchor inventory and registry inputs are empty; the work occurrence is unchanged while a disputed FOREIGN outcome is retained.",
    )

    same_identity_event = event(first_result["state"], copy.deepcopy(evidence), "C2-foreign-duplicate-evidence-identity")
    emit(
        "C2-foreign-duplicate-evidence-identity",
        base,
        first_result["state"],
        same_identity_event,
        repeated_identity_transition(first_result["state"], same_identity_event),
        "A second event carries the byte-identical native evidence of the retained foreign outcome under its exact evidence identity. LIFE-013 states the consequence directly: such an event records OUTCOME_RETAINED/DUPLICATE and adds no duplicate outcome or exposure, because the original outcome already retains those bytes. The same paragraph closes the one escape from that rule by saying the representable duplicate rule applies to governed and foreign outcomes alike, so the foreign path has no separate duplicate handling. The retained outcome inventory is therefore unchanged, which is what distinguishes this case from D2-182: a new evidence identity carrying the same fact appends exactly one row, because those bytes are not yet retained anywhere. LIFE-006's DUPLICATE row takes precedence over every other and fixes the complete reason set to DUPLICATE_EVIDENCE. The step declares no shared budget, so the anchor inventory and registry inputs stay empty and no receipt is committed.",
        requirements=["LIFE-006", "LIFE-013"],
    )

    repeated = copy.deepcopy(evidence)
    repeated["evidence_id"] = "evidence-d2-182"
    repeated["evidence_ref"] = "evidence-ref-d2-182"
    duplicate_event = event(first_result["state"], repeated, "D2-182")
    duplicate_result = transition(
        first_result["state"],
        duplicate_event,
        classification="DUPLICATE",
        disposition="OUTCOME_RETAINED",
        reason_codes=["DUPLICATE_EVIDENCE"],
    )
    emit(
        "D2-182",
        base,
        first_result["state"],
        duplicate_event,
        duplicate_result,
        "The new foreign evidence identity omits only a changed evidence_id and evidence_ref from the same complete fact. It is retained as a disputed DUPLICATE and does not change work or exposure.",
    )

    evidence = native_evidence(
        base,
        "D2-228",
        event_time="2026-09-10T04:30:01Z",
        observed_at="2026-09-10T04:30:00Z",
    )
    late_event = event(state, evidence, "D2-228")
    late_result = transition(state, late_event, classification="FOREIGN", disposition="DISPUTED", reason_codes=["FOREIGN_EFFECT"])
    emit(
        "D2-228",
        base,
        state,
        late_event,
        late_result,
        "The foreign effect claims event_time after observed_at. The contract retains schema-valid foreign evidence as FOREIGN and disputed rather than accepting its timeline or erasing it.",
    )

    evidence = native_evidence(base, "D2-192", status="OUTCOME_UNKNOWN", event_time=None)
    invalid_event = event(state, evidence, "D2-192")
    emit(
        "D2-192",
        base,
        state,
        invalid_event,
        stateful_refusal(state, "INPUT_INVALID"),
        "The foreign branch admits only established effects. OUTCOME_UNKNOWN has a valid native-evidence shape but is semantically INPUT_INVALID for this branch, leaving work state unchanged.",
    )

    budget_base = base_lifecycle(shared_budget=True)
    budget_state = budget_base["clock_result"]["state"]
    evidence = native_evidence(budget_base, "D2-240")
    missing_budget_event = event(budget_state, evidence, "D2-240")
    emit(
        "D2-240",
        budget_base,
        budget_state,
        missing_budget_event,
        stateful_refusal(budget_state, "BINDING_MISMATCH"),
        "The attributed request resolves to the issue step, whose declared shared-budget set is nonempty. Null reservation identity, an empty affected-anchor set and no registry input cannot represent that operation as an authority-only foreign effect, so binding admission fails before evidence retention.",
    )

    print(json.dumps({"case_ids": ["D2-118", "C2-foreign-duplicate-evidence-identity", "D2-182", "D2-192", "D2-228", "D2-240"]}, indent=2))


if __name__ == "__main__":
    main()
