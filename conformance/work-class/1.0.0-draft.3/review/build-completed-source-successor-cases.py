#!/usr/bin/env python3
"""Construct exact successor completion and recovery cases from the approved rules."""

from __future__ import annotations

import copy
import json

from composition_fixture import add_authority_operations, parallel_definition, parallel_entry_result
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from dependency_dispute_common import apply_dependency_block
from fixture_factory import available_clock
from lifecycle_factory import (
    admitted_transition,
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    governed_effect_event,
    governed_native_evidence,
    permitted_proposal,
    stateful_refusal,
    step_input,
)
from recovery_fixture import authorize
from recovery_lifecycle_fixture import (
    PBR,
    dispatch_event_from_record,
    supplier_chain,
    work_dispose_expected,
    work_dispose_request,
)


GROUP = CASES / "completed-source-successor"


def record_for(event: dict) -> dict:
    permit = event["permit"]
    body = {
        "dispatch_attempt_digest": digest("dispatch-attempt", {
            "permit_id": permit["permit_id"], "native_request": event["native_request"],
            "connector": event["connector"], "attempt": event["attempt"]}),
        "event_id": event["event_id"], "event_digest": digest("runtime-event", event),
        "permit_digest": permit["permit_id"], "native_request": copy.deepcopy(event["native_request"]),
        "connector": copy.deepcopy(event["connector"]), "attempt": copy.deepcopy(event["attempt"]),
        "acknowledgement": copy.deepcopy(event["acknowledgement"]), "clock_revision": event["clock_revision"],
    }
    return {"dispatch_digest": digest("dispatch", body), **body}


def late_source_attempt(chain: dict, before: dict, *, event_id: str) -> tuple[dict, dict, dict]:
    permit, first = chain["change_permit"], chain["change_dispatch"]
    event = dispatch_event_from_record(before, permit, first)
    event["event_id"] = event_id
    event["attempt"]["attempt_id"] = event_id + "-attempt"
    event["acknowledgement"] = {"status": "NONE", "reference": None, "observed_at": None}
    record = record_for(event)

    def mutate(state: dict, _event_digest: str) -> None:
        state["dispatches"].append(copy.deepcopy(record))
        state["dispatches"].sort(key=lambda row: row["dispatch_digest"].encode())
        source_id = permit["occurrence"]["occurrence_id"]
        if any(row["occurrence"]["occurrence_id"] == source_id for row in state["completed"]):
            apply_dependency_block(state, source_id)
        else:
            next(row for row in state["active"] if row["occurrence"]["occurrence_id"] == source_id)["status"] = "BLOCKED_DISPUTE"

    after, expected = PBR["work_transition"](before, event, disposition="DISPUTED",
        reasons=["LATE_OR_PROHIBITED_DISPATCH"],
        details=[{"kind": "DISPATCH", "attempt_id": event["attempt"]["attempt_id"],
                  "reasons": ["LATE_OR_PROHIBITED_DISPATCH"]}],
        permit=None, budget_results=[], authority_result_digest=None,
        reservation_receipt_digests=[], mutate=mutate)
    return event, record, expected


def reauthorize(chain: dict, supplied: dict) -> None:
    event, host = supplied["event"], supplied["recovery_host"]
    packet = event["evidence"]
    host["recovery_bases"] = []
    host["authenticated_records"] = [{"kind": "RECOVERY_EVIDENCE",
        "record_digest": digest("recovery-evidence", packet),
        "provider": packet["provider"], "source": packet["source"]}]
    event["controller"] = None
    facts = {"configuration": {"principal": supplied["state"]["deployment_organization_id"],
        "recovery": chain["definition"]["recovery"]}, "clock": {"instant": PBR["NOW"]}}
    authorize(facts, event, host, operation=event["requested_result"],
        scope_digest=digest("recovery-target", event["target"]))


def completion_cases() -> list[dict]:
    rows = []

    chain = supplier_chain(permitted_payment=True)
    before = chain["before_dispute"]
    event, late, blocked = late_source_attempt(chain, before, event_id="completion-late-source-send")
    rows.append(exact_case("C3-COMP-001", "step",
        PBR["lifecycle_input"](chain["definition"], chain["definition_digest"], before, event), blocked,
        ["LIFE-006", "LIFE-009", "LIFE-013", "REC-013"],
        "The completed supplier change retains its original successful route. A distinct possibly sent attempt on the consumed permit is dispatch-disqualified, blocks the permitted payment descendant, and does not rewrite its permit."))

    recovery = work_dispose_request(chain, blocked["state"], event_id="cover-completion-late-attempt")
    packet = recovery["event"]["evidence"]
    packet["attempts"].append({
        "id": late["attempt"]["attempt_id"], "attempt_digest": late["dispatch_attempt_digest"],
        "executor": chain["change_permit"]["executor"]["participant_id"],
        "connector": late["connector"]["id"], "request_digest": digest("reservation-native-request", packet["request"]),
        "maximum_executions": "1", "effect_ids": [], "no_effect": True,
    })
    packet["attempts"].sort(key=lambda row: row["id"].encode())
    packet["superseded_evidence_digests"] = []
    packet["record_digest"] = digest("provider-recovery-record", {
        "target": recovery["event"]["target"], "covered_attempt": late["dispatch_attempt_digest"]})
    packet["provider_revision"] = "4"
    reauthorize(chain, recovery)
    restored = work_dispose_expected(recovery, restored_status="PERMITTED")
    rows.append(exact_case("C3-COMP-002", "step", recovery, restored,
        ["REC-002", "REC-004", "REC-006", "REC-012", "REC-013", "REC-015"],
        "The effective work-outcome disposition establishes the original supplier-change fact and affirmatively excludes execution by the later physical attempt. Its complete attempt inventory covers both stable digests. The payment descendant returns to PERMITTED without reviving its old dispatch permission or changing the completed source's route."))

    no_outcome_chain = supplier_chain()
    pending = no_outcome_chain["results"][3]["state"]
    no_target_event, _no_target_attempt, no_target_blocked = late_source_attempt(no_outcome_chain, pending,
        event_id="completion-dispatch-only-late-send")
    rows.append(exact_case("C3-COMP-003", "step",
        PBR["lifecycle_input"](no_outcome_chain["definition"], no_outcome_chain["definition_digest"],
                                   pending, no_target_event), no_target_blocked,
        ["LIFE-006", "LIFE-009", "REC-013"],
        "A second possibly sent attempt blocks the still-active source. This checkpoint contains no governed outcome and no reservation that a recovery carrier can target."))

    invented = work_dispose_request(no_outcome_chain, no_outcome_chain["before_dispute"],
        event_id="invent-dispatch-only-recovery-target")
    invented["state"] = copy.deepcopy(no_target_blocked["state"])
    invented["state_digest"] = PBR["work_state_digest"](invented["state"])
    invented["event"]["expected_state_revision"] = invented["state"]["revision"]
    invented["event"]["expected_state_digest"] = invented["state_digest"]
    reauthorize(no_outcome_chain, invented)
    rows.append(exact_case("C3-COMP-004", "step", invented,
        stateful_refusal(invented["state"], "DEPENDENCY_MISMATCH"),
        ["REC-002", "REC-012", "REC-013", "REC-016"],
        "A dispatch-only block has no retained outcome or reservation target. A work disposition naming an outcome from a different event history refuses exact target binding and cannot clear the block."))

    deadline = {"id": "issue-deadline", "step_id": "issue", "clock_source": "work-clock",
        "due": {"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-10T04:31:00Z"},
        "boundary": "AT_OR_AFTER", "expiry_target": "terminal"}

    def add_deadline(definition: dict) -> None:
        definition["profile"] = "DEADLINES"
        definition["deadlines"] = [copy.deepcopy(deadline)]
        definition["relationships"].append({"kind": "EXPIRY", "from": "issue", "to": "terminal",
            "deadline_ref": deadline["id"]})
        definition["relationships"].sort(key=canonical_bytes)

    base = base_lifecycle(definition_mutator=add_deadline,
        initial_clocks=[available_clock("work-clock", "1", "2026-09-10T04:00:00Z")])
    proposed = permitted_proposal(base)
    first = dispatch_event(base, proposed, event_id="completion-deadline-first-send",
        acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(proposed, first, disposition="ACKNOWLEDGED", reasons=[],
        occurrence_status="DISPATCHED")
    second_carrier = {"state": dispatched["state"], "state_digest": dispatched["state_digest"],
        "permit": proposed["permit"]}
    second = dispatch_event(base, second_carrier, event_id="completion-deadline-late-send")
    second["attempt"]["attempt_id"] = "completion-deadline-attempt-2"
    blocked_active = dispatch_result(second_carrier, second, disposition="DISPUTED",
        reasons=["LATE_OR_PROHIBITED_DISPATCH"], occurrence_status="BLOCKED_DISPUTE")
    due_clock = available_clock("work-clock", "2", "2026-09-10T04:31:00Z")
    due_event = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "completion-blocked-deadline-due", "kind": "CLOCK",
        "instance_id": blocked_active["state"]["instance_id"],
        "expected_state_revision": blocked_active["state"]["revision"],
        "expected_state_digest": blocked_active["state_digest"],
        "clock": due_clock, "activation_clocks": []}

    def expire_evidence_only(state: dict) -> None:
        state["clocks"].append(copy.deepcopy(due_clock))
        state["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))
        state["deadlines"][0]["status"] = "EXPIRED"
        state["deadlines"][0]["expiry_event_digest"] = digest("runtime-event", due_event)

    evidence_only = admitted_transition(blocked_active["state"], due_event,
        disposition="EXPIRED", reason_codes=[],
        details=[{"kind": "CLOCK", "source": due_clock["source"], "revision": "2", "status": "AVAILABLE"},
                 {"kind": "DEADLINE", "deadline_ids": [deadline["id"]], "reasons": []}],
        mutate=expire_evidence_only)
    rows.append(exact_case("C3-COMP-005", "step", step_input(base, blocked_active["state"], due_event),
        evidence_only, ["LIFE-006", "LIFE-014"],
        "The due deadline is recorded as EXPIRED evidence while its occurrence remains BLOCKED_DISPUTE. The expiry edge does not route, no completed row is added, and the instance remains ACTIVE."))

    parallel_base = base_lifecycle(instance_id="completion-parallel-late-source",
        authority_mutator=add_authority_operations(["branch-a", "branch-b"]),
        definition_mutator=parallel_definition(["branch-a", "branch-b"]))
    parallel_permit = permitted_proposal(parallel_base)
    parallel_first = dispatch_event(parallel_base, parallel_permit,
        event_id="completion-parallel-original-send", acknowledgement_status="ACCEPTED")
    parallel_dispatched = dispatch_result(parallel_permit, parallel_first,
        disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    original_native = governed_native_evidence(parallel_base, parallel_permit, parallel_dispatched,
        evidence_id="completion-parallel-original-effect")
    original_effect = governed_effect_event(parallel_permit, parallel_dispatched, original_native,
        event_id="completion-parallel-original-route")
    entered = parallel_entry_result(parallel_base, parallel_dispatched, original_effect,
        ["branch-a", "branch-b"])
    parallel_carrier = {"state": entered["state"], "state_digest": entered["state_digest"],
        "permit": parallel_permit["permit"]}
    parallel_late = dispatch_event(parallel_base, parallel_carrier,
        event_id="completion-parallel-late-send")
    parallel_late["attempt"]["attempt_id"] = "completion-parallel-attempt-2"
    parallel_record = record_for(parallel_late)

    def block_parallel(state: dict) -> None:
        state["dispatches"].append(copy.deepcopy(parallel_record))
        state["dispatches"].sort(key=lambda row: row["dispatch_digest"].encode())
        apply_dependency_block(state, parallel_permit["permit"]["occurrence"]["occurrence_id"])

    parallel_blocked = admitted_transition(entered["state"], parallel_late,
        disposition="DISPUTED", reason_codes=["LATE_OR_PROHIBITED_DISPATCH"],
        details=[{"kind": "DISPATCH", "attempt_id": parallel_late["attempt"]["attempt_id"],
                  "reasons": ["LATE_OR_PROHIBITED_DISPATCH"]}],
        receipt_permit_digest=parallel_permit["permit"]["permit_id"], mutate=block_parallel)
    rows.append(exact_case("C3-COMP-006", "step",
        step_input(parallel_base, entered["state"], parallel_late), parallel_blocked,
        ["LIFE-006", "LIFE-009", "LIFE-013", "COMP-001"],
        "A fresh disqualified send after the entry effect routed into a parallel block preserves the completed entry and its route. Both active dependent branches become BLOCKED_DISPUTE and both directly owning OPEN obligations become BLOCKED in the same transition."))

    # Construct a different physical attempt that was safely NOT_SENT before the source completed.
    # Its late ACCEPTED acknowledgement must block the routed descendant, even without a new send.
    ack_chain = supplier_chain()
    ack_permit = ack_chain["change_permit"]
    ack_ready = ack_chain["results"][2]["state"]
    safe_event = dispatch_event_from_record(ack_ready, ack_permit, ack_chain["change_dispatch"])
    safe_event["event_id"] = "completion-source-safe-first"
    safe_event["attempt"]["attempt_id"] = "completion-source-safe-attempt"
    safe_event["attempt"]["status"] = "NOT_SENT"
    safe_event["acknowledgement"] = {"status": "NONE", "reference": None, "observed_at": None}
    safe_record = record_for(safe_event)

    def keep_safe(state: dict, _event_digest: str) -> None:
        state["dispatches"].append(copy.deepcopy(safe_record))
        state["dispatches"].sort(key=lambda row: row["dispatch_digest"].encode())

    safe_state, _safe_result = PBR["work_transition"](ack_ready, safe_event,
        disposition="DISPATCH_REFUSED", reasons=["NATIVE_NOT_SENT"],
        details=[{"kind": "DISPATCH", "attempt_id": safe_event["attempt"]["attempt_id"],
                  "reasons": ["NATIVE_NOT_SENT"]}], permit=None, budget_results=[],
        authority_result_digest=None, reservation_receipt_digests=[], mutate=keep_safe)
    sent_state, _sent_result, actual_dispatch = PBR["dispatch_result"](safe_state,
        "completion-source-valid-second", ack_permit)
    completed_state, _completed_result, _payment, _native = PBR["change_effect_result"](
        ack_chain["definition"], ack_chain["definition_digest"], sent_state,
        ack_chain["change_occurrence"], ack_permit, actual_dispatch,
        ack_permit["native_request"]["fields"])
    update = copy.deepcopy(safe_event)
    update["event_id"] = "completion-source-safe-now-accepted"
    update["expected_state_revision"] = completed_state["revision"]
    update["expected_state_digest"] = PBR["work_state_digest"](completed_state)
    update["acknowledgement"] = {"status": "ACCEPTED",
        "reference": "completion-source-late-ack", "observed_at": PBR["NOW"]}
    update_record = record_for(update)

    def block_ack_descendant(state: dict, _event_digest: str) -> None:
        state["dispatches"].append(copy.deepcopy(update_record))
        state["dispatches"].sort(key=lambda row: row["dispatch_digest"].encode())
        apply_dependency_block(state, ack_permit["occurrence"]["occurrence_id"])

    _accepted_state, accepted = PBR["work_transition"](completed_state, update,
        disposition="DISPUTED", reasons=["DISPATCH_EVIDENCE_CONFLICT"],
        details=[{"kind": "DISPATCH", "attempt_id": update["attempt"]["attempt_id"],
                  "reasons": ["DISPATCH_EVIDENCE_CONFLICT"]}], permit=None,
        budget_results=[], authority_result_digest=None, reservation_receipt_digests=[],
        mutate=block_ack_descendant)
    rows.append(exact_case("C3-COMP-007", "step",
        PBR["lifecycle_input"](ack_chain["definition"], ack_chain["definition_digest"],
                               completed_state, update), accepted,
        ["LIFE-006", "LIFE-009", "LIFE-010", "LIFE-013", "REC-013"],
        "The original safe NOT_SENT attempt predates a distinct sent attempt whose effect completed the supplier change and routed to payment. ACCEPTED on that first stable attempt adds a second possible execution. The source route stays historical, while its active payment descendant blocks."))

    return rows


def main() -> None:
    rows = completion_cases()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print(json.dumps({"source_case_ids": [row["id"] for row in rows], "consumer_execution": "NONE"}))


if __name__ == "__main__":
    main()
