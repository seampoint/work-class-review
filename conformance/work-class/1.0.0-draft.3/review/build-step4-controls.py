#!/usr/bin/env python3
"""Build the step 4 controls: ancestor-anchored deadlines (S1), failed checks in authority withholdings (E2), and the
clarifying sentences for LIFE-006, LIFE-010 and RES-WIRE-004.

Derivations sealed 2026-09-13 (neo-step4-derivations-20260913/DERIVATIONS.md) before construction. Expected results
are derived with the fixture helpers from the text, never taken from a consumer.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import runpy
from pathlib import Path

from authority_fixture import (
    authority_refusal, authority_specimen, credential_check, envelope_digest, envelope_validity_check, old_digest,
    revocation_check,
)
from checkpoint_reseal import reseal_last_transition
from composition_fixture import add_authority_operations, parallel_definition
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import available_clock, deployment, occurrence, typed
from lifecycle_budget_fixture import initial_budget_success
from lifecycle_factory import (
    admitted_transition, base_lifecycle, dispatch_event, dispatch_result, governed_effect_event, governed_native_evidence,
    governed_outcome, lifecycle_definition, permitted_proposal, state_digest, stateful_refusal, step_input, withheld_proposal,
)
from reservation_fixture import (
    effect_record, fixture, host_and_event, matching_history, native, open_state, refusal as reservation_refusal, released_state,
    request as reservation_request, settled_state, transition as reservation_transition,
)


def _module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
ADVANCED = runpy.run_path(str(HERE / "build-advanced-static-cases.py"))
FANOUT = runpy.run_path(str(HERE / "build-fanout-cases.py"))
RESTART = _module("restart_admission_controls", "build-restart-admission-controls.py")
SUCCESSORS = runpy.run_path(str(HERE / "build-deadline-successor-cases.py"))
SIBLINGS = _module("stopped_siblings", "build-stopped-sibling-cases.py")
WITHHOLDING = _module("authority_withholding", "build-authority-withholding-cases.py")
B2 = _module("budget_effect_b2", "build-budget-effect-b2-cases.py")
EDGES = _module("reservation_edges", "build-reservation-edge-cases.py")
GOVERNED = _module("governed_budget_disputes", "build-governed-budget-dispute-cases.py")
GROUP = CASES / "step4-controls"
NOW = "2026-09-10T04:30:00Z"


def emit(case_id: str, operation: str, input_value: dict, expected: dict, requirements: list[str], derivation: str) -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(GROUP / f"{case_id}.json", exact_case(case_id, operation, input_value, expected, requirements, derivation))


def ancestor_due(anchor: str, value: str = "30", unit: str = "MINUTE") -> dict:
    return {"kind": "ELAPSED_FROM_ANCESTOR", "value": value, "unit": unit, "anchor_step_id": anchor}


def stop_deadline(step_id: str, anchor: str) -> dict:
    return {
        "id": step_id + "-deadline", "step_id": step_id, "clock_source": "work-clock", "due": ancestor_due(anchor),
        "boundary": "AT_OR_AFTER", "expiry_target": None,
    }


def sequences(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"kind": "SEQUENCE", "from": source, "to": target} for source, target in pairs]


# S1 static admission.

def parallel_static(deadline_step: str, anchor: str) -> dict:
    definition = lifecycle_definition(authority_mutator=add_authority_operations(["after", "branch-a", "branch-b"]))
    parallel_definition(["branch-a", "branch-b"])(definition)
    definition["relationships"] = sequences([
        ("issue", "parallel-split"), ("branch-a", "parallel-join"), ("branch-b", "parallel-join"),
        ("parallel-join", "after"), ("after", "terminal"),
    ])
    definition["deadlines"] = [stop_deadline(deadline_step, anchor)]
    return definition


def loop_static() -> dict:
    definition = lifecycle_definition(authority_mutator=add_authority_operations(["after"]))
    definition["profile"] = "DEADLINES"
    root = next(row for row in definition["steps"] if row["id"] == "issue")
    root["completion"]["route_label_field"] = "route"
    root["completion"]["route_label_type_ref"] = "STRING"
    definition["relationships"] = [
        {"kind": "LABEL", "from": "issue", "to": "issue", "label": typed("STRING", "CONTINUE")},
        {"kind": "LABEL", "from": "issue", "to": "after", "label": typed("STRING", "EXIT")},
        {"kind": "SEQUENCE", "from": "after", "to": "terminal"},
    ]
    definition["choices"] = [{"step_id": "issue", "label_type_ref": "STRING", "label_values": [typed("STRING", "CONTINUE"), typed("STRING", "EXIT")]}]
    definition["occurrence_limits"] = [{"step_id": "after", "maximum": "1"}, {"step_id": "issue", "maximum": "2"}]
    definition["loops"] = [{
        "id": "retry-loop", "entry_step_id": "issue", "member_step_ids": ["issue"], "back_edge_from_step_id": "issue", "maximum_passes": "2",
    }]
    definition["deadlines"] = [stop_deadline("after", "issue")]
    return definition


def fanout_static(*, same_region: bool) -> dict:
    extra = "object-next" if same_region else "after"
    definition = lifecycle_definition(authority_mutator=add_authority_operations([extra, "object-step"]))
    FANOUT["fanout_definition"]("ADVANCE_TO_JOIN")(definition)
    if same_region:
        definition["relationships"] = sequences([("object-step", "object-next"), ("object-next", "fanout-join"), ("fanout-join", "terminal")])
        next(row for row in definition["occurrence_limits"] if row["step_id"] == "object-next")["maximum"] = "2"
        definition["deadlines"] = [stop_deadline("object-next", "object-step")]
    else:
        definition["relationships"] = sequences([("object-step", "fanout-join"), ("fanout-join", "after"), ("after", "terminal")])
        definition["deadlines"] = [stop_deadline("after", "object-step")]
    return definition


def static_controls() -> None:
    validate = ADVANCED["validate_input"]
    requirements = ["DEAD-001", "WCD-001"]
    admitted = parallel_static("after", "issue")
    emit(
        "C2-ancestor-deadline-static-admitted", "validate", validate(admitted),
        {"status": "ACCEPTED", "digest": digest("work-class-definition", admitted)}, requirements,
        "A parallel block runs from root issue through branch-a and branch-b to parallel-join, then after, then terminal. after declares an ELAPSED_FROM_ANCESTOR deadline of 30 minutes anchored at issue with an explicit stop. COMPOSITION 5.1 requires the anchor to be a proposal-capable step other than the deadline's step, in no loop, not inside a fan-out region that excludes the deadline's step, and on every path from the root to the deadline's step in the normalized graph. The root lies on every path and meets the other conditions, so the definition is accepted with its definition digest.",
    )
    emit(
        "C2-ancestor-deadline-anchor-one-branch", "validate", validate(parallel_static("after", "branch-a")),
        {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""}, requirements + ["PAR-001"],
        "The same definition anchors after's deadline at branch-a. The normalized graph includes the split-to-branch-head construct edges, so the path issue, parallel-split, branch-b, parallel-join, after reaches the deadline step without the anchor. COMPOSITION 5.1 makes an anchor that is not on every path DEFINITION_INVALID.",
    )
    emit(
        "C2-ancestor-deadline-on-root", "validate", validate(parallel_static("issue", "after")),
        {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""}, requirements,
        "The ancestor deadline is declared on the root issue with anchor after. The only path from the root to the root is the root itself, so no other step can lie on every path to it. COMPOSITION 5.1 names an ancestor declaration on the root step as DEFINITION_INVALID.",
    )
    emit(
        "C2-ancestor-deadline-undeclared-anchor", "validate", validate(parallel_static("after", "missing-step")),
        {"status": "REFUSED", "code": "REFERENCE_INVALID", "path": ""}, requirements,
        "after's ancestor deadline names anchor_step_id missing-step, which is not a declared step. COMPOSITION 5.1 makes an undeclared anchor step REFERENCE_INVALID, and reference validity precedes the graph checks in the static refusal order.",
    )
    emit(
        "C2-ancestor-deadline-anchor-loop-member", "validate", validate(loop_static()),
        {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""}, requirements + ["COMP-002"],
        "Root issue is a choice whose CONTINUE label returns to itself and whose EXIT label reaches after; retry-loop declares issue as its entry and sole member. after declares an ancestor deadline anchored at issue. The anchor is proposal-capable, differs from after, lies on every path and is in no fan-out, but it is a loop member, so its completed occurrence is not unique. COMPOSITION 5.1 makes that DEFINITION_INVALID.",
    )
    emit(
        "C2-ancestor-deadline-anchor-outside-region", "validate", validate(fanout_static(same_region=False)),
        {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""}, requirements + ["FAN-001"],
        "Root issue expands fanout-1 whose region head object-step reaches fanout-join; the join continues to after. after declares an ancestor deadline anchored at object-step. The expand-to-region-head construct edge puts object-step on every path to after, but object-step is inside a fan-out region that does not contain after, where there may be zero or several object occurrences. COMPOSITION 5.1 makes that DEFINITION_INVALID.",
    )
    same_region = fanout_static(same_region=True)
    emit(
        "C2-ancestor-deadline-anchor-same-region", "validate", validate(same_region),
        {"status": "ACCEPTED", "digest": digest("work-class-definition", same_region)}, requirements + ["FAN-001"],
        "Root issue expands fanout-1 whose region runs object-step, then object-next, then fanout-join. object-next declares an ancestor deadline anchored at object-step. Both steps are in the same fan-out region, the anchor lies on every path through the construct edge, is proposal-capable, differs from object-next and is in no loop. COMPOSITION 5.1 excludes only a region that does not also contain the deadline's step, so the definition is accepted with its definition digest.",
    )


# S1 lifecycle.

def chain_definition(definition: dict) -> None:
    definition["profile"] = "DEADLINES"
    definition["relationships"] = [
        *sequences([("issue", "middle"), ("middle", "review"), ("review", "terminal")]),
        {"kind": "EXPIRY", "from": "review", "to": "terminal", "deadline_ref": "review-deadline"},
    ]
    definition["deadlines"] = [{
        "id": "review-deadline", "step_id": "review", "clock_source": "work-clock", "due": ancestor_due("issue"),
        "boundary": "AT_OR_AFTER", "expiry_target": "terminal",
    }]


def complete_and_activate(base: dict, carrier: dict, event: dict, successor: str, deadline_due: str | None) -> dict:
    """A matched effect completes its occurrence and follows its sequence edge to one proposal-capable successor,
    installing the successor's declared deadline with the stated due instant."""
    source = event["permit"]["occurrence"]
    outcome = governed_outcome(event, carrier, classification="MATCHED", disputed=False)
    selected = next(row for row in base["definition"]["relationships"] if row["kind"] == "SEQUENCE" and row["from"] == source["step_id"])
    selected_digest = digest("relationship", selected)
    event_digest = digest("runtime-event", event)
    successor_occurrence = occurrence(base["definition_digest"], source["instance_id"], successor, "1", [source["occurrence_id"]], [])

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [row for row in state["active"] if row["occurrence"]["occurrence_id"] != source["occurrence_id"]]
        state["completed"].append({
            "occurrence": copy.deepcopy(source), "disposition": "SUCCEEDED", "evidence_digest": digest("native-evidence", event["native_evidence"]),
            "occurred_at": event["native_evidence"]["event_time"], "route_label": None, "selected_relationship_digest": selected_digest, "late": False,
        })
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        deadline_ids = []
        if deadline_due is not None:
            declared = next(row for row in base["definition"]["deadlines"] if row["step_id"] == successor)
            clock = next(row for row in event["activation_clocks"] if row["source"] == declared["clock_source"])
            subject = {
                "deadline_id": declared["id"], "occurrence_id": successor_occurrence["occurrence_id"], "trigger_digest": event_digest,
                "source": declared["clock_source"], "activation_revision": state["revision"], "activation_clock_revision": clock["revision"],
                "activation_instant": clock["observed_time"], "activation_clock_evidence_digest": clock["evidence_digest"],
                "due": deadline_due, "boundary": declared["boundary"],
            }
            state["deadlines"].append({"activation_digest": digest("deadline-activation", subject), **subject, "status": "PENDING", "expiry_event_digest": None})
            deadline_ids = [declared["id"]]
        state["active"].append({"occurrence": successor_occurrence, "activation_event_digest": event_digest, "status": "ACTIVE", "deadline_ids": deadline_ids})
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        counter = next(row for row in state["step_counters"] if row["step_id"] == successor)
        counter["activations"] = str(int(counter["activations"]) + 1)
        state["total_activations"] = str(int(state["total_activations"]) + 1)

    return admitted_transition(
        carrier["state"], event, disposition="COMPLETED", reason_codes=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [selected_digest], "construct_ids": []},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


def ancestor_deadline_controls() -> None:
    base = base_lifecycle(authority_mutator=add_authority_operations(["middle", "review"]), definition_mutator=chain_definition)
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-c2-ancestor-issue", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-c2-ancestor-issue", native_operation_id="native-c2-ancestor-issue")
    anchor_effect = governed_effect_event(permitted, dispatched, evidence, event_id="effect-c2-ancestor-issue")
    anchored = complete_and_activate(base, dispatched, anchor_effect, "middle", None)
    anchor_row = next(row for row in anchored["state"]["completed"] if row["occurrence"]["step_id"] == "issue")
    assert anchor_row["occurred_at"] == NOW

    middle = SIBLINGS.occurrence_for(anchored["state"], "middle")
    _proposal, middle_permitted, middle_dispatched = SIBLINGS.propose_and_dispatch(base, anchored["state"], middle, suffix="c2-ancestor-middle")
    work_clock = available_clock("work-clock", "1", "2026-09-10T04:50:00Z")
    clock_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "clock-c2-ancestor-work", "kind": "CLOCK",
        "instance_id": middle_dispatched["state"]["instance_id"], "expected_state_revision": middle_dispatched["state"]["revision"],
        "expected_state_digest": state_digest(middle_dispatched["state"]), "clock": copy.deepcopy(work_clock), "activation_clocks": [],
    }
    clocked = RESTART.clock_recorded(middle_dispatched["state"], clock_event)
    middle_evidence = governed_native_evidence(
        base, middle_permitted, clocked, evidence_id="evidence-c2-ancestor-middle", native_operation_id="native-c2-ancestor-middle",
    )
    effect = governed_effect_event(middle_permitted, clocked, middle_evidence, event_id="effect-c2-ancestor-middle")
    effect["activation_clocks"] = [copy.deepcopy(work_clock)]
    due = "2026-09-10T05:00:00Z"
    expected = complete_and_activate(base, clocked, effect, "review", due)
    emit(
        "C2-ancestor-deadline-due-from-anchor", "step", step_input(base, clocked["state"], effect), expected, ["DEAD-001", "LIFE-014"],
        "The DEADLINES chain runs issue, middle, review, terminal; review declares review-deadline, ELAPSED_FROM_ANCESTOR 30 minutes anchored at issue on work-clock with expiry to terminal. issue's matching effect at event time 04:30:00 completed it with occurred_at 04:30:00 and activated middle. middle was permitted and dispatched, and a work-clock sample at 04:50:00 was recorded. middle's matching effect now completes it as SUCCEEDED and follows its sequence edge to review, carrying the 04:50:00 work-clock record in activation_clocks. COMPOSITION 5.1 and LIFE-014: the anchor occurrence is the one completed issue occurrence in the recursive predecessor closure of review (review to middle to issue), so due is its occurred_at plus 30 minutes, 05:00:00, not the activation instant plus 30 minutes, 05:20:00. The activation clock 04:50:00 is before due, so the deadline is PENDING and review is ACTIVE with deadline_ids [review-deadline]; activation fields copy the work-clock record and the activation revision is the new state revision.",
    )

    state = expected["state"]
    restart = RESTART.clock_event(state, "clock-c2-restart-ancestor-deadline")
    emit(
        "C2-restart-ancestor-deadline", "step", step_input(base, state, restart), RESTART.clock_recorded(state, restart),
        ["DEAD-001", "LIFE-014", "LIFE-019"],
        "The checkpoint is C2-ancestor-deadline-due-from-anchor's result, holding review-deadline with due 05:00:00. A fresh available authority-clock sample asks the consumer to restart. LIFE-014 restart verifies every deadline field and recomputes due from the retained anchor row: the completed issue occurrence in review's predecessor closure has occurred_at 04:30:00, plus 30 minutes is 05:00:00, which equals the persisted due. The authority-clock source cannot expire a work-clock deadline, so the sample is recorded with no other change.",
    )

    damaged = copy.deepcopy(state)
    row = next(row for row in damaged["deadlines"] if row["deadline_id"] == "review-deadline")
    row["due"] = "2026-09-10T05:20:00Z"
    row["activation_digest"] = digest("deadline-activation", {key: row[key] for key in (
        "deadline_id", "occurrence_id", "trigger_digest", "source", "activation_revision", "activation_clock_revision",
        "activation_instant", "activation_clock_evidence_digest", "due", "boundary",
    )})
    reseal_last_transition(damaged)
    refused = RESTART.clock_event(damaged, "clock-c2-refuse-ancestor-deadline")
    emit(
        "C2-refuse-ancestor-deadline-due-from-activation", "step", step_input(base, damaged, refused), stateful_refusal(damaged, "STATE_INVALID"),
        ["DEAD-001", "LIFE-014", "LIFE-019"],
        "The same checkpoint with review-deadline's due changed to 05:20:00, the activation instant plus the duration, its activation_digest recomputed over the changed fields, and the last transition resealed so every commitment is consistent. A fresh available authority-clock sample asks the consumer to restart. Restart recomputes due for an ancestor declaration from the retained anchor occurrence's occurred_at, 04:30:00 plus 30 minutes, which is 05:00:00 and differs from the persisted value. LIFE-019 refuses the checkpoint as STATE_INVALID and returns the exact supplied state.",
    )


# E2.

def three_failures(request: dict, original: dict) -> None:
    request["envelope"]["temporal_validity"]["valid_until"] = NOW
    credential = next(row for row in request["credentials"] if row["id"] == "credential-1")
    credential["validity"]["valid_until"] = NOW
    old_envelope = old_digest("authority-envelope", original["envelope"])
    observation = next(row for row in request["observations"] if row["query"]["at"] == NOW and row["query"]["subject_digest"] == old_envelope)
    observation["revoked"] = True


def clock_unavailable(request: dict, _original: dict) -> None:
    request["clock"]["status"] = "UNAVAILABLE"
    request["clock"]["instant"] = None


def three_failure_refusal(request: dict) -> dict:
    return authority_refusal([
        envelope_validity_check(request), credential_check(request, "credential-1"),
        revocation_check(request, envelope_digest(request), NOW),
    ])


def authority_controls() -> None:
    request, _ = authority_specimen(shared_budget=False, mutator=three_failures)
    refusal = three_failure_refusal(request)
    assert [row["purpose"] for row in refusal["failed_checks"]] == ["CREDENTIAL", "ENVELOPE_VALIDITY", "REVOCATION"]
    emit(
        "C2-authority-failed-checks-evaluate", "evaluate", {"kind": "AUTHORITY", "request": request}, refusal,
        ["AUTH-005", "AUTH-CHECK-003", "AUTH-CHECK-004"],
        "The access-card authority input, without shared budgets, has its envelope valid_until and credential-1 valid_until both at the current authority instant, and its current envelope revocation observation reports revoked true; every dependent digest is rebound. Three phase-5 checks fail: ENVELOPE_VALIDITY with ENVELOPE_EXPIRED, CREDENTIAL with CREDENTIAL_EXPIRED and REVOCATION with REVOKED. AUTHORITY-CHECKS: the refusal is AUTHORITY_NOT_ESTABLISHED with the sorted reason union, and failed_checks has one row per failed check whose purpose, subject_digest, requirement_ref and at are the values the check construction table assigns: the envelope digest, envelope id and now for ENVELOPE_VALIDITY; the operation digest, credential-1 and now for CREDENTIAL; the envelope digest, the exact query digest and the query instant for REVOCATION. Rows sort by canonical bytes, so CREDENTIAL, ENVELOPE_VALIDITY, REVOCATION.",
    )

    base = base_lifecycle()
    event = WITHHOLDING.authority_event(base, three_failures)
    event["event_id"] = "proposal-c2-authority-failed-checks"
    refusal = three_failure_refusal(event["authority_input"])
    emit(
        "C2-authority-failed-checks-withholding", "step", step_input(base, base["clock_result"]["state"], event), withheld_proposal(base, event, refusal),
        ["AUTH-CHECK-004", "LIFE-007"],
        "The same three-failure authority input, bound to the linear root occurrence, arrives as its first proposal. AUTH-005 returns AUTHORITY_NOT_ESTABLISHED with reasons CREDENTIAL_EXPIRED, ENVELOPE_EXPIRED and REVOKED and three failed_checks rows. LIFE-007 records an admitted policy withholding whose reason codes are the union of AUTHORITY_REQUIRED, the refusal code and its reasons; its AUTHORITY detail carries the code, the reasons and the exact failed_checks rows; the proposal record and receipt retain digest(authority-result, refusal); no permit is created.",
    )

    request, _ = authority_specimen(shared_budget=False, mutator=clock_unavailable)
    emit(
        "C2-authority-clock-unavailable-evaluate", "evaluate", {"kind": "AUTHORITY", "request": request},
        authority_refusal([], reasons=["CLOCK_UNAVAILABLE"]), ["AUTH-CHECK-002", "AUTH-CHECK-004"],
        "The access-card authority input, without shared budgets, supplies an UNAVAILABLE clock with a null instant and is otherwise exact. AUTHORITY-CHECKS returns AUTHORITY_NOT_ESTABLISHED with sole reason CLOCK_UNAVAILABLE in phase 5 before deriving current queries, and failed_checks is empty for that refusal because it evaluates no check.",
    )

    from timing_fixture import clock_event, clock_result
    outage_event = clock_event(base["clock_result"]["state"], "2", status="UNAVAILABLE", event_id="outage-before-c2-authority-withholding")
    outage = clock_result(base["clock_result"]["state"], outage_event)
    event = WITHHOLDING.authority_event(base, clock_unavailable)
    event["event_id"] = "proposal-c2-authority-clock-unavailable"
    event["clock_revision"] = None
    emit(
        "C2-authority-clock-unavailable-withholding", "step", step_input(base, outage["state"], {**event, "expected_state_revision": outage["state"]["revision"], "expected_state_digest": outage["state_digest"]}),
        withheld_proposal({**base, "clock_result": outage}, {**event, "expected_state_revision": outage["state"]["revision"], "expected_state_digest": outage["state_digest"]}, authority_refusal([], reasons=["CLOCK_UNAVAILABLE"])), ["AUTH-CHECK-004", "LIFE-007"],
        "After an explicit retained UNAVAILABLE lifecycle sample supersedes its available sample, a first proposal for the linear root carries an authority input whose clock is UNAVAILABLE with a null instant, and a null lifecycle clock_revision, which only an authority-withheld proposal with an unavailable selected clock may carry. AUTH-005 returns AUTHORITY_NOT_ESTABLISHED with sole reason CLOCK_UNAVAILABLE and empty failed_checks. LIFE-007 records the withholding with reason codes AUTHORITY_NOT_ESTABLISHED, AUTHORITY_REQUIRED and CLOCK_UNAVAILABLE, and its AUTHORITY detail carries empty failed_checks.",
    )


# LIFE-010 and LIFE-006.

def dispatch_conflict_effect() -> None:
    base, facts, _proposal, permitted = initial_budget_success(instance_id="case-c2-dispatch-conflict", event_id="proposal-c2-dispatch-conflict")
    registry = permitted["budget_results"][0]["result"]["state"]
    reservation_id = permitted["budget_results"][0]["result"]["receipt"]["reservation"]
    assert registry["core"]["budgets"][0]["history"] == facts["history"]
    dispatch = dispatch_event(
        base, permitted, event_id="dispatch-c2-dispatch-conflict", attempt_status="NOT_SENT", acknowledgement_status="ACCEPTED",
        attempted_at=NOW, clock_revision="1",
    )
    dispatched = dispatch_result(permitted, dispatch, disposition="DISPUTED", reasons=["DISPATCH_EVIDENCE_CONFLICT"], occurrence_status="OUTCOME_UNKNOWN")
    evidence = governed_native_evidence(
        base, permitted, dispatched, evidence_id="evidence-c2-dispatch-conflict", native_operation_id="native-c2-dispatch-conflict", observed_at=NOW,
    )
    record = B2.embedded_native_record(facts, reservation_id, evidence, outcome="EFFECT", completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT")
    assert record["observed_request"] == record["request"]
    reservation = next(row for row in registry["core"]["reservations"] if row["id"] == reservation_id)
    blocked = sorted(
        {canonical_bytes({"anchor": row["anchor"], "key": row["key"]}): {"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation["contributions"]}.values(),
        key=canonical_bytes,
    )
    budget_input, budget_output = B2.embed_reservation_event(
        facts, registry, reservation_id, "effect-c2-dispatch-conflict", record, kind="SETTLE", decision="EFFECT_DISPUTED",
        reservation_status="DISPUTED", effect_disposition="DISPUTED", effect_reason="UNEXPECTED_EFFECT", blocked=blocked,
        reasons=["UNEXPECTED_EFFECT"], administration=False,
    )
    event = governed_effect_event(permitted, dispatched, evidence, event_id="effect-c2-dispatch-conflict", budget_inputs=[budget_input], clock_revision="1")
    expected = B2.budget_effect_result(
        base, dispatched, event, budget_output, classification="UNEXPECTED", disposition="DISPUTED",
        reason_codes=["BUDGET_EFFECT_DISPUTED", "UNEXPECTED_EFFECT"], occurrence_status="OUTCOME_UNKNOWN", disputed=True,
    )
    emit(
        "C2-effect-on-dispatch-evidence-conflict", "step", step_input(base, dispatched["state"], event), expected,
        ["LIFE-006", "LIFE-010", "RES-WIRE-004"],
        "A budget-backed root holds an OPEN reservation. Its dispatch reports attempt NOT_SENT with an ACCEPTED acknowledgement, which LIFE-009 records as DISPUTED with DISPATCH_EVIDENCE_CONFLICT and the occurrence OUTCOME_UNKNOWN. An EFFECT_ESTABLISHED record with the permitted fields and success status is bound to that dispatch row. LIFE-010: a DISPUTED row with DISPATCH_EVIDENCE_CONFLICT is not dispatch-disqualifying but cannot support normal completion, so the established effect is UNEXPECTED with completion_mismatch true and mismatch_reason UNEXPECTED_EFFECT. The embedded SETTLE/EFFECT record has the dispatch-attributed request as its observed request; against an OPEN reservation the unexpected attributable effect yields EFFECT_DISPUTED, the reservation becomes DISPUTED, the receipt and effect record copy UNEXPECTED_EFFECT, and the reserved and projected partitions, one key, are blocked. LIFE-006 gives DISPUTED with BUDGET_EFFECT_DISPUTED and UNEXPECTED_EFFECT, and its DISPUTED governed-effect row keeps an unresolved occurrence with an UNEXPECTED classification OUTCOME_UNKNOWN even though its budget reconciliation is also disputed, rather than BLOCKED_DISPUTE. The outcome is disputed with an empty conflict list; nothing completes, routes or releases.",
    )


# RES-WIRE-004.

def disputed_second_effect_identifier() -> None:
    facts = fixture()
    no_effect = native(facts, "NO_EFFECT", "contradictory-no-effect")
    _input, disputed = EDGES.retained_effect_transition(
        facts, settled_state(facts), "D2-145", "RELEASE", no_effect, decision="EFFECT_DISPUTED", next_status="DISPUTED",
        disposition="DISPUTED", reason="UNEXPECTED_EFFECT",
        blocked=[{"anchor": "license-spend", "key": [{"type_ref": "beneficiary", "value": "employee-7"}]}],
    )
    state = disputed["state"]
    reservation = state["core"]["reservations"][0]
    assert reservation["status"] == "DISPUTED" and reservation["matched_effect"] == "effect-1"
    second = native(facts, "EFFECT", "native-second-effect", effect_id="effect-2")
    history = copy.deepcopy(state["core"]["budgets"][0]["history"])
    matched = next(row["event"] for row in history["journal"] if row["event"]["id"] == digest(
        "reservation-committed-event", {"budget_digest": history["budget_digest"], "effect_id": "effect-1", "mapping": "pay"},
    ))
    sequence = str(len(history["journal"]) + 1)
    history["journal"].append({
        "sequence": sequence,
        "event": {
            "id": digest("reservation-committed-event", {"budget_digest": history["budget_digest"], "effect_id": "effect-2", "mapping": "pay"}),
            "state": "ACTIVE", "occurred_at": second["occurred_at"], "fields": copy.deepcopy(matched["fields"]),
        },
    })
    history["revision"] = sequence
    assert history["as_of"] >= second["occurred_at"]
    event, host = host_and_event(
        facts, "SETTLE", "event-c2-second-effect-identifier", state["core"]["revision"], {"native": second, "histories": [history]}, administration=False,
    )
    blocked = sorted(
        {canonical_bytes({"anchor": row["anchor"], "key": row["key"]}): {"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation["contributions"]}.values(),
        key=canonical_bytes,
    )
    core = copy.deepcopy(state["core"])
    core["budgets"][0]["history"] = history
    core["effects"].append(effect_record(second, "DISPUTED", "UNEXPECTED_EFFECT", blocked))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    expected = reservation_transition(state, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["UNEXPECTED_EFFECT"])
    emit(
        "C2-disputed-reservation-second-effect-identifier", "aggregate-step", reservation_request(state, event, host), expected,
        ["RES-WIRE-003", "RES-WIRE-004"],
        "The registry is D2-145's result: reservation reserve-a settled with matched effect-1 and then became DISPUTED when a contradictory no-effect record arrived. A SETTLE now carries a new EFFECT record with effect_id effect-2, completion_mismatch false and a null mismatch reason, observing the reserved request, together with a history that extends the retained journal by the prescribed committed event for effect-2, so journal corroboration is complete. RESERVATION-RECORDS: a second distinct effect identifier for one occurrence is unexpected additional exposure, and RES-WIRE-004 gives a clean record against an already DISPUTED reservation the effect reason it would carry against an OPEN or UNKNOWN reservation, UNEXPECTED_EFFECT for a second distinct effect identifier. The receipt is EFFECT_DISPUTED with that reason, the reservation remains DISPUTED with matched_effect effect-1 and no automatic resolution, the admitted history is retained, and the new effect record is DISPUTED with reason UNEXPECTED_EFFECT blocking the reserved and projected partition, one key.",
    )


# Corrections after the adversarial check: RES-WIRE-004 reason order.

def reserved_blocked(reservation: dict) -> list[dict]:
    return sorted(
        {canonical_bytes({"anchor": row["anchor"], "key": row["key"]}): {"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation["contributions"]}.values(),
        key=canonical_bytes,
    )


def committed_event_id(history: dict, effect_id: str) -> str:
    return digest("reservation-committed-event", {"budget_digest": history["budget_digest"], "effect_id": effect_id, "mapping": "pay"})


def unexpected_settle(facts: dict, state: dict, record: dict, case_id: str, derivation: str) -> None:
    """SETTLE with the retained history; the record takes UNEXPECTED_EFFECT and the reservation is or stays DISPUTED."""
    reservation = next(row for row in state["core"]["reservations"] if row["id"] == "reserve-a")
    budget = next(row for row in state["core"]["budgets"] if row["definition"]["anchor"] == "license-spend")
    history = copy.deepcopy(budget["history"])
    event, host = host_and_event(facts, "SETTLE", "event-" + case_id.lower(), state["core"]["revision"], {"native": record, "histories": [history]}, administration=False)
    blocked = reserved_blocked(reservation)
    assert blocked == [{"anchor": "license-spend", "key": [{"type_ref": "beneficiary", "value": "employee-7"}]}]
    core = copy.deepcopy(state["core"])
    next(row for row in core["reservations"] if row["id"] == "reserve-a")["status"] = "DISPUTED"
    core["effects"].append(effect_record(record, "DISPUTED", "UNEXPECTED_EFFECT", blocked))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    expected = reservation_transition(state, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["UNEXPECTED_EFFECT"])
    assert next(row for row in expected["state"]["core"]["reservations"] if row["id"] == "reserve-a")["matched_effect"] == "effect-1"
    emit(case_id, "aggregate-step", reservation_request(state, event, host), expected, ["RES-WIRE-003", "RES-WIRE-004"], derivation)


def reason_order_controls() -> None:
    facts = fixture()
    settled = settled_state(facts)
    no_effect = native(facts, "NO_EFFECT", "contradictory-no-effect")
    _input, disputed_result = EDGES.retained_effect_transition(
        facts, settled, "D2-145", "RELEASE", no_effect, decision="EFFECT_DISPUTED", next_status="DISPUTED",
        disposition="DISPUTED", reason="UNEXPECTED_EFFECT",
        blocked=[{"anchor": "license-spend", "key": [{"type_ref": "beneficiary", "value": "employee-7"}]}],
    )
    disputed = disputed_result["state"]
    for state, status in ((settled, "SETTLED"), (disputed, "DISPUTED")):
        reservation = next(row for row in state["core"]["reservations"] if row["id"] == "reserve-a")
        assert reservation["status"] == status and reservation["matched_effect"] == "effect-1"
        history = next(row for row in state["core"]["budgets"] if row["definition"]["anchor"] == "license-spend")["history"]
        journal_ids = {row["event"]["id"] for row in history["journal"]}
        assert committed_event_id(history, "effect-1") in journal_ids and committed_event_id(history, "effect-2") not in journal_ids

    second = native(facts, "EFFECT", "native-c2-second-effect-uncorroborated", effect_id="effect-2")
    unexpected_settle(
        facts, settled, second, "C2-settled-reservation-second-effect-uncorroborated",
        "reservation_fixture's SETTLED registry holds reserve-a settled with matched effect-1 and a history carrying effect-1's prescribed committed event. A SETTLE carries a new EFFECT record with effect_id effect-2, completion_mismatch false, a null mismatch reason and the reserved request as observed request, together with the retained history, which has no prescribed committed event for effect-2. Two reasons apply: a second distinct effect identifier for the occurrence (UNEXPECTED_EFFECT) and missing journal corroboration (HISTORY_UNCORROBORATED). RES-WIRE-004 takes the first applicable reason in a fixed order whatever the prior status, and UNEXPECTED_EFFECT comes first. The terminal-state table moves SETTLED to DISPUTED with EFFECT_DISPUTED for a nonduplicate EFFECT, retaining all conclusions, so matched_effect stays effect-1. RES-WIRE-003 blocks the union of the reserved and projected partitions, one key. The effect record is DISPUTED with UNEXPECTED_EFFECT, the receipt reasons copy it, and the history is unchanged.",
    )
    unexpected_settle(
        facts, disputed, second, "C2-disputed-reservation-second-effect-uncorroborated",
        "The registry is D2-145's result: reserve-a settled with matched effect-1 and then became DISPUTED when a contradictory no-effect record arrived; its history carries effect-1's prescribed committed event and none for effect-2. A SETTLE carries a new EFFECT record with effect_id effect-2, completion_mismatch false and the reserved request as observed request, with the retained history. Both a second distinct effect identifier and missing corroboration apply; RES-WIRE-004's order selects UNEXPECTED_EFFECT whatever the prior status. Against an already DISPUTED reservation the receipt is EFFECT_DISPUTED and the reservation remains DISPUTED with matched_effect effect-1. The effect record is DISPUTED with UNEXPECTED_EFFECT blocking the one reserved and projected key; the history is unchanged.",
    )

    changed = native(facts, "EFFECT", "native-c2-effect-1-changed-fact", effect_id="effect-1")
    changed["actual_fields"].append({"name": "note", "value": {"type_ref": "beneficiary", "value": "employee-7"}})
    changed["actual_fields"].sort(key=lambda row: row["name"].encode("utf-8"))
    assert changed["observed_request"] == changed["request"]
    unexpected_settle(
        facts, disputed, changed, "C2-disputed-reservation-changed-fact-retained-effect",
        "The registry is D2-145's result: reserve-a DISPUTED with matched effect-1, whose prescribed committed event is in the retained history. A SETTLE carries a new native record under the retained effect_id effect-1 with completion_mismatch false; its request and observed request equal the reserved request, and it adds one non-operation actual field, so its fact differs from the retained effect-1 fact and it is not a duplicate. The retained history is supplied, so journal corroboration for effect-1 is complete. RESERVATION-RECORDS makes a changed conclusive fact under one effect_id conflicting and disputed with no second committed contribution; RES-WIRE-004 gives it UNEXPECTED_EFFECT first whatever the prior status, and against DISPUTED the receipt is EFFECT_DISPUTED with the reservation remaining DISPUTED. The effect record is DISPUTED with UNEXPECTED_EFFECT blocking the one reserved key; the history is unchanged.",
    )
    unexpected_settle(
        facts, settled, changed, "C2-settled-reservation-changed-fact-retained-effect",
        "reservation_fixture's SETTLED registry holds reserve-a settled with matched effect-1 and its prescribed committed event. A SETTLE carries a new native record under effect_id effect-1 with completion_mismatch false, the reserved request as request and observed request, and one added non-operation actual field, so the fact changes without changing the projection; the retained history gives complete corroboration. The terminal-state table moves SETTLED to DISPUTED with EFFECT_DISPUTED for any conclusive conflict, retaining all conclusions and adding no second committed contribution. RES-WIRE-004 selects UNEXPECTED_EFFECT for a changed conclusive fact under a retained effect identifier. The effect record is DISPUTED with UNEXPECTED_EFFECT blocking the one reserved key; matched_effect stays effect-1 and the history is unchanged.",
    )


# Second corrections: an observed request that differs from the reserved request, and a clean no-effect on DISPUTED.

def partition_key(budget: dict, authorization: dict, fields: list[dict]) -> list[dict]:
    mapping = next(row for row in budget["aggregate"]["aggregate"]["mappings"] if row["id"] == "pay")
    by_budget_field = {row["budget_field"]: row for row in authorization["projection"]}
    values = {row["name"]: row["value"]["value"] for row in fields}
    return [
        {"type_ref": by_budget_field[field]["budget_type"], "value": values[by_budget_field[field]["native_field"]]}
        for field in mapping["key_fields"]
    ]


def corroborated_history(retained: dict, record: dict, effect_id: str) -> dict:
    """The retained history extended by the record's prescribed committed event for its observed contribution."""
    history = copy.deepcopy(retained)
    sequence = str(len(history["journal"]) + 1)
    committed = {row["name"]: row["value"] for row in record["observed_request"]["fields"]}
    history["journal"].append({
        "sequence": sequence,
        "event": {
            "id": committed_event_id(history, effect_id), "state": "ACTIVE", "occurred_at": record["occurred_at"],
            "fields": [
                {"name": "amount", "value": {"type_ref": "amount", "value": committed["amount"]["value"]}},
                {"name": "beneficiary", "value": {"type_ref": "beneficiary", "value": committed["beneficiary"]["value"]}},
            ],
        },
    })
    history["revision"] = sequence
    return history


def differing_settle(facts: dict, state: dict, effect_id: str, case_id: str, derivation: str) -> None:
    reservation = next(row for row in state["core"]["reservations"] if row["id"] == "reserve-a")
    budget_row = next(row for row in state["core"]["budgets"] if row["definition"]["anchor"] == "license-spend")
    authorization = budget_row["authorizations"][0]
    record = native(facts, "EFFECT", "native-" + case_id.lower(), effect_id=effect_id)
    for row in record["observed_request"]["fields"] + record["actual_fields"]:
        if row["name"] == "beneficiary":
            row["value"]["value"] = "employee-8"
    assert {key: record["request"][key] for key in record["request"]} == {
        key: reservation["authority"]["proposal"][key] for key in record["request"]
    }
    reserved_key = partition_key(budget_row["definition"], authorization, reservation["authority"]["proposal"]["fields"])
    projected_key = partition_key(budget_row["definition"], authorization, record["observed_request"]["fields"])
    assert reserved_key == [row["key"] for row in reservation["contributions"]][0]
    assert projected_key != reserved_key
    blocked = sorted(
        {canonical_bytes(entry): entry for entry in (
            {"anchor": "license-spend", "key": reserved_key}, {"anchor": "license-spend", "key": projected_key},
        )}.values(),
        key=canonical_bytes,
    )
    assert len(blocked) == 2
    history = corroborated_history(budget_row["history"], record, effect_id)
    event, host = host_and_event(facts, "SETTLE", "event-" + case_id.lower(), state["core"]["revision"], {"native": record, "histories": [history]}, administration=False)
    core = copy.deepcopy(state["core"])
    next(row for row in core["budgets"] if row["definition"]["anchor"] == "license-spend")["history"] = history
    next(row for row in core["reservations"] if row["id"] == "reserve-a")["status"] = "DISPUTED"
    core["effects"].append(effect_record(record, "DISPUTED", "UNEXPECTED_EFFECT", blocked))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    expected = reservation_transition(state, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["UNEXPECTED_EFFECT"])
    emit(case_id, "aggregate-step", reservation_request(state, event, host), expected, ["RES-WIRE-003", "RES-WIRE-004"], derivation)


def second_correction_controls() -> None:
    facts = fixture()
    opened = open_state(facts)
    settled = settled_state(facts)
    assert next(row for row in opened["core"]["reservations"] if row["id"] == "reserve-a")["status"] == "OPEN"
    settled_reservation = next(row for row in settled["core"]["reservations"] if row["id"] == "reserve-a")
    assert settled_reservation["status"] == "SETTLED" and settled_reservation["matched_effect"] == "effect-1"

    differing_settle(
        facts, opened, "effect-1", "C2-open-reservation-observed-request-differs",
        "reservation_fixture's OPEN registry holds reserve-a for beneficiary employee-7, amount 150. A SETTLE carries an EFFECT record for effect-1 with completion_mismatch false and a null mismatch reason; its attributed request is the reserved request, but its observed request and actual fields name beneficiary employee-8. The supplied history extends the opening journal by effect-1's prescribed committed event for the projected contribution, so corroboration is complete. RES-WIRE-003: a matching settlement requires equality of attributed, observed and reserved requests; different native fields retain EFFECT_DISPUTED. RES-WIRE-004 gives a clean record whose observed request differs from the reserved request UNEXPECTED_EFFECT before any other reason. The OPEN row for an unexpected attributable EFFECT gives EFFECT_DISPUTED and DISPUTED, matched_effect stays null, and the effect record blocks the sorted union of the reserved key (employee-7) and the key projected through the budget's beneficiary grouping field (employee-8). The record is not a duplicate, so the supplied history is retained.",
    )
    differing_settle(
        facts, settled, "effect-2", "C2-settled-reservation-second-effect-observed-request-differs",
        "reservation_fixture's SETTLED registry holds reserve-a settled with matched effect-1 for beneficiary employee-7. A SETTLE carries an EFFECT record for effect-2 with completion_mismatch false whose observed request and actual fields name beneficiary employee-8, with a history extending the settled journal by effect-2's prescribed committed event for the projected contribution, so corroboration is complete. RES-WIRE-004 gives UNEXPECTED_EFFECT for a second distinct effect identifier and for an observed request that differs from the reserved request. The terminal-state table moves SETTLED to DISPUTED with EFFECT_DISPUTED for a nonduplicate EFFECT, retaining all conclusions, so matched_effect stays effect-1. RES-WIRE-003 blocks the sorted union of the reserved key (employee-7) and the projected key (employee-8). The supplied history is retained.",
    )

    matching = native(facts, "EFFECT", "native-c2-uncorroborated-effect-1")
    opening_history = next(row for row in opened["core"]["budgets"] if row["definition"]["anchor"] == "license-spend")["history"]
    assert committed_event_id(opening_history, "effect-1") not in {row["event"]["id"] for row in opening_history["journal"]}
    reserved = reserved_blocked(next(row for row in opened["core"]["reservations"] if row["id"] == "reserve-a"))
    _input, disputed_result = EDGES.retained_effect_transition(
        facts, opened, "C2-disputed-reservation-clean-no-effect-prior", "SETTLE", matching, decision="EFFECT_DISPUTED", next_status="DISPUTED",
        disposition="DISPUTED", reason="HISTORY_UNCORROBORATED", blocked=reserved, histories=[opening_history],
    )
    disputed = disputed_result["state"]
    reservation = next(row for row in disputed["core"]["reservations"] if row["id"] == "reserve-a")
    assert reservation["status"] == "DISPUTED" and reservation["matched_effect"] is None
    no_effect = native(facts, "NO_EFFECT", "native-c2-disputed-clean-no-effect")
    _input, expected = EDGES.retained_effect_transition(
        facts, disputed, "C2-disputed-reservation-clean-no-effect", "RELEASE", no_effect, decision="EFFECT_DISPUTED", next_status="DISPUTED",
        disposition="DISPUTED", reason="AFFIRMATIVE_NO_EFFECT", blocked=reserved,
    )
    assert _input["event"]["administration"] is None
    assert next(row for row in expected["state"]["core"]["reservations"] if row["id"] == "reserve-a")["matched_effect"] is None
    emit(
        "C2-disputed-reservation-clean-no-effect", "aggregate-step", _input, expected, ["RES-WIRE-003", "RES-WIRE-004"],
        "The input registry is reservation_fixture's OPEN registry after a SETTLE of the clean matching effect-1 record with the retained opening history, which lacks effect-1's prescribed committed event: no identity conflict and missing corroboration give EFFECT_DISPUTED with HISTORY_UNCORROBORATED, so reserve-a is DISPUTED with matched_effect null and the reserved key blocked. A RELEASE now carries a clean NO_EFFECT record with completion_mismatch false and null administration, because a DISPUTED reservation does not newly become RELEASED. RES-WIRE-004: there is no matched effect to contradict, no effect identifier and no request difference, and corroboration applies only to effects, so the record takes AFFIRMATIVE_NO_EFFECT. The DISPUTED row gives EFFECT_DISPUTED with no automatic resolution: the reservation remains DISPUTED with matched_effect null, the history is unchanged, and the new effect record is DISPUTED with AFFIRMATIVE_NO_EFFECT blocking the reserved key, the record having no projectable actual fields and no mismatch.",
    )


# Corrections: LIFE-006 row for an occurrence already BLOCKED_DISPUTE.

def conflicting_effect_on_blocked_dispute() -> None:
    base, facts, _proposal, permitted = initial_budget_success(instance_id="case-d2-230", event_id="proposal-d2-230")
    budget_row = next(row for row in permitted["budget_results"] if "license-spend" in row["affected_anchors"])
    registry = budget_row["result"]["state"]
    reservation_id = budget_row["result"]["receipt"]["reservation"]
    instant, revision = GOVERNED.REGISTRY_CLOCK_INSTANT, GOVERNED.REGISTRY_CLOCK_REVISION

    # D2-230's construction: a matching settle the registry disputes for missing corroboration.
    dispatch = dispatch_event(base, permitted, event_id="dispatch-d2-230", attempt_status="SENT", attempted_at=instant, clock_revision=revision)
    dispatched = dispatch_result(permitted, dispatch, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")
    first_evidence = governed_native_evidence(base, permitted, dispatched, evidence_id="evidence-d2-230", status="EFFECT_ESTABLISHED", observed_at=instant)
    first_record = GOVERNED.matching_native_record(facts, first_evidence, reservation_id)
    reservation = next(row for row in registry["core"]["reservations"] if row["id"] == reservation_id)
    first_input, first_output = GOVERNED.uncorroborated_settle(
        facts, registry, reservation_id, "effect-d2-230", first_record, [{"anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation["contributions"]],
    )
    first_event = governed_effect_event(permitted, dispatched, first_evidence, event_id="effect-d2-230", budget_inputs=[first_input], clock_revision=revision)
    first_receipt = first_output["result"]["receipt_digest"]
    first_outcome = governed_outcome(first_event, dispatched, classification="MATCHED", disputed=True, reservation_receipt_digests=[first_receipt])
    occurrence_id = permitted["permit"]["occurrence"]["occurrence_id"]

    def block(next_state: dict) -> None:
        next_state["outcomes"].append(copy.deepcopy(first_outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        next(row for row in next_state["active"] if row["occurrence"]["occurrence_id"] == occurrence_id)["status"] = "BLOCKED_DISPUTE"

    prior = admitted_transition(
        dispatched["state"], first_event, disposition="DISPUTED", reason_codes=["BUDGET_EFFECT_DISPUTED", "HISTORY_UNCORROBORATED"],
        details=[
            {"kind": "BUDGET", "registry_digest": first_output["registry_digest"], "receipt_digest": first_receipt, "reasons": ["HISTORY_UNCORROBORATED"]},
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": first_evidence["evidence_id"]},
        ],
        receipt_permit_digest=first_event["permit"]["permit_id"], budget_results=[first_output], mutate=block,
    )
    committed = json.loads((CASES / "governed-budget-disputes" / "D2-230.json").read_text())
    assert committed["expected"] == prior, "D2-230 rebuild differs from the committed expected result"

    registry_after = first_output["result"]["state"]
    budget = next(row for row in registry_after["core"]["budgets"] if row["definition"]["anchor"] == "license-spend")
    assert budget["history"] == facts["history"]
    assert next(row for row in registry_after["core"]["reservations"] if row["id"] == reservation_id)["status"] == "DISPUTED"
    assert next(row for row in prior["state"]["active"] if row["occurrence"]["occurrence_id"] == occurrence_id)["status"] == "BLOCKED_DISPUTE"

    evidence = governed_native_evidence(base, permitted, prior, evidence_id="evidence-c2-conflict-blocked-dispute", status="EFFECT_ESTABLISHED", observed_at=instant)
    assert evidence["native_operation_id"] == first_evidence["native_operation_id"] and evidence["record_digest"] != first_evidence["record_digest"]
    record = B2.embedded_native_record(facts, reservation_id, evidence, outcome="EFFECT", completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT")
    assert record["observed_request"] == record["request"] and record["effect_id"] == first_record["effect_id"]
    budget_input, budget_output = B2.embed_reservation_event(
        facts, registry_after, reservation_id, "effect-c2-conflict-blocked-dispute", record, kind="SETTLE", decision="EFFECT_DISPUTED",
        reservation_status="DISPUTED", effect_disposition="DISPUTED", effect_reason="UNEXPECTED_EFFECT",
        blocked=reserved_blocked(next(row for row in registry_after["core"]["reservations"] if row["id"] == reservation_id)),
        reasons=["UNEXPECTED_EFFECT"], administration=False,
    )
    event = governed_effect_event(permitted, prior, evidence, event_id="effect-c2-conflict-blocked-dispute", budget_inputs=[budget_input], clock_revision=revision)
    assert event["dispatch_digest"] == first_event["dispatch_digest"]
    expected = B2.budget_effect_result(
        base, prior, event, budget_output, classification="CONFLICTING", disposition="DISPUTED",
        reason_codes=["BUDGET_EFFECT_DISPUTED", "CONFLICTING_EFFECT", "UNEXPECTED_EFFECT"], occurrence_status="BLOCKED_DISPUTE", disputed=True,
        conflicts=[first_evidence["evidence_id"]],
    )
    earlier = next(row for row in expected["state"]["outcomes"] if row["native_evidence"]["evidence_id"] == first_evidence["evidence_id"])
    assert earlier["disputed"] and earlier["conflicts_with_evidence_ids"] == [evidence["evidence_id"]]
    emit(
        "C2-conflicting-effect-on-blocked-dispute-occurrence", "step", step_input(base, prior["state"], event), expected,
        ["LIFE-006", "LIFE-010", "LIFE-013", "RES-WIRE-004"],
        "The input state is D2-230's result: a budget-backed root whose matching effect evidence-d2-230 (provider-native operation native-operation-1) the registry disputed with HISTORY_UNCORROBORATED, so the reservation is DISPUTED, the outcome is MATCHED and disputed with no conflicts, and the occurrence is BLOCKED_DISPUTE. A new EFFECT_ESTABLISHED record bound to the same permit and dispatch row names the same provider-native operation and request but a different evidence identity and record digest. LIFE-010: a changed conclusive fact for the same provider-native operation is CONFLICTING; its conflict list is evidence-d2-230, and that earlier outcome gains the new evidence identity and stays disputed. The classification sets completion_mismatch true with UNEXPECTED_EFFECT, and the embedded SETTLE carries the registry's retained history. RES-WIRE-004: a completion-mismatched record copies UNEXPECTED_EFFECT; its fact differs from the retained record, so it is no duplicate; against the DISPUTED reservation the receipt is EFFECT_DISPUTED and the reservation remains DISPUTED, with the one reserved key blocked. LIFE-006 gives DISPUTED with BUDGET_EFFECT_DISPUTED, CONFLICTING_EFFECT and UNEXPECTED_EFFECT; DEPENDENCY_DISPUTED does not apply because the budget result is disputed. The occurrence is already BLOCKED_DISPUTE, and the DISPUTED governed-effect row keeps a BLOCKED_DISPUTE occurrence BLOCKED_DISPUTE rather than moving it to OUTCOME_UNKNOWN. Nothing completes or routes.",
    )


# Corrections: failed_checks rows per contributed reason and the ROOT_BINDING row.

def stale_and_revoked(request: dict, original: dict) -> None:
    old_envelope = old_digest("authority-envelope", original["envelope"])
    observation = next(row for row in request["observations"] if row["query"]["at"] == NOW and row["query"]["subject_digest"] == old_envelope)
    observation["as_of"] = "2026-09-10T03:00:00Z"
    observation["revoked"] = True


def root_expired(request: dict, _original: dict) -> None:
    request["host_selection"]["root"]["validity"]["valid_until"] = NOW


def failed_check_corrections() -> None:
    requirements = ["AUTH-005", "AUTH-CHECK-003", "AUTH-CHECK-004"]
    request, _ = authority_specimen(shared_budget=False, mutator=stale_and_revoked)
    assert request["envelope"]["revocation"]["max_age_seconds"] == "3600"
    subject = envelope_digest(request)
    refusal = authority_refusal([
        revocation_check(request, subject, NOW, reason="OBSERVATION_STALE"), revocation_check(request, subject, NOW, reason="REVOKED"),
    ])
    assert [row["reason"] for row in refusal["failed_checks"]] == ["OBSERVATION_STALE", "REVOKED"]
    emit(
        "C2-authority-stale-and-revoked-observation", "evaluate", {"kind": "AUTHORITY", "request": request}, refusal, requirements,
        "The access-card authority input, without shared budgets, has its current envelope revocation observation (query at now, 04:30:00) with as_of 03:00:00 and revoked true; every other fact is current. The envelope revocation declaration's max_age_seconds is 3600 and now minus as_of is 5400 seconds, so the observation is stale, and its revoked value is true. AUTHORITY-CHECKS: the refusal is AUTHORITY_NOT_ESTABLISHED with reasons OBSERVATION_STALE and REVOKED. failed_checks has one row per reason the failed REVOCATION check contributed, so two rows with equal check values: subject the envelope digest, requirement the exact envelope query digest, at now. Rows sort by canonical bytes, so the OBSERVATION_STALE row precedes the REVOKED row.",
    )

    request, _ = authority_specimen(shared_budget=False, mutator=root_expired)
    root = request["host_selection"]["root"]
    assert root["prior_acts_survive_expiry"] is False
    row = {"purpose": "ROOT_BINDING", "subject_digest": envelope_digest(request), "requirement_ref": root["id"], "at": NOW, "reason": "ROOT_EXPIRED"}
    emit(
        "C2-authority-root-expired", "evaluate", {"kind": "AUTHORITY", "request": request}, authority_refusal([row]), requirements,
        "The access-card authority input, without shared budgets, has its host root valid_until at now with prior_acts_survive_expiry false; every act occurred during root validity, capacities, occupancies, channels and credentials are current, and every observation is fresh and unrevoked, with digests rebound. AUTHORITY-CHECKS: current root expiry without survival gives ROOT_EXPIRED, and it is reported against the ROOT_BINDING check, whose construction values are the envelope digest, root.id and now. The refusal is AUTHORITY_NOT_ESTABLISHED with reasons ROOT_EXPIRED and that one failed_checks row.",
    )


# Third corrections: a clean no-effect against a disputed reservation that keeps its matched effect, the observed request as
# the projection of the actual fields, and the three consumer divergences decided 2026-09-13.

def third_correction_reservations() -> None:
    facts = fixture()
    settled = settled_state(facts)
    reservation = next(row for row in settled["core"]["reservations"] if row["id"] == "reserve-a")
    assert reservation["status"] == "SETTLED" and reservation["matched_effect"] == "effect-1"
    budget_row = next(row for row in settled["core"]["budgets"] if row["definition"]["anchor"] == "license-spend")
    second = native(facts, "EFFECT", "native-c2-matched-dispute-effect-2", effect_id="effect-2")
    history = corroborated_history(budget_row["history"], second, "effect-2")
    event, host = host_and_event(facts, "SETTLE", "event-c2-matched-dispute-effect-2", settled["core"]["revision"], {"native": second, "histories": [history]}, administration=False)
    reserved = reserved_blocked(reservation)
    core = copy.deepcopy(settled["core"])
    next(row for row in core["budgets"] if row["definition"]["anchor"] == "license-spend")["history"] = history
    next(row for row in core["reservations"] if row["id"] == "reserve-a")["status"] = "DISPUTED"
    core["effects"].append(effect_record(second, "DISPUTED", "UNEXPECTED_EFFECT", reserved))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    disputed = reservation_transition(settled, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["UNEXPECTED_EFFECT"])["state"]
    assert next(row for row in disputed["core"]["reservations"] if row["id"] == "reserve-a")["matched_effect"] == "effect-1"
    assert not any(row["native"]["outcome"] == "NO_EFFECT" for row in disputed["core"]["effects"])

    no_effect = native(facts, "NO_EFFECT", "native-c2-matched-dispute-clean-no-effect")
    case_id = "C2-disputed-reservation-matched-effect-clean-no-effect"
    _input, expected = EDGES.retained_effect_transition(
        facts, disputed, case_id, "RELEASE", no_effect, decision="EFFECT_DISPUTED", next_status="DISPUTED",
        disposition="DISPUTED", reason="UNEXPECTED_EFFECT", blocked=reserved,
    )
    assert _input["event"]["administration"] is None
    assert next(row for row in expected["state"]["core"]["reservations"] if row["id"] == "reserve-a")["matched_effect"] == "effect-1"
    emit(
        case_id, "aggregate-step", _input, expected, ["RES-WIRE-003", "RES-WIRE-004"],
        "The input registry is reservation_fixture's SETTLED registry (reserve-a settled with matched effect-1) after a SETTLE of a clean EFFECT for effect-2 with the reserved request and a history carrying effect-2's prescribed committed event: a second distinct effect identifier gives EFFECT_DISPUTED with UNEXPECTED_EFFECT, reserve-a DISPUTED, and matched_effect stays effect-1 because the SETTLED row retains all conclusions. A RELEASE now carries a clean NO_EFFECT record with null administration; no no-effect fact is retained, so it is not a duplicate. RES-WIRE-004 takes the first applicable reason whatever the prior status, and a no-effect record that contradicts the reservation's matched effect takes UNEXPECTED_EFFECT. Against the DISPUTED reservation the receipt is EFFECT_DISPUTED with that reason, the reservation remains DISPUTED with matched_effect effect-1, and the effect record is DISPUTED with UNEXPECTED_EFFECT blocking the reserved key only, the record having no actual fields and no mismatch. The history is unchanged.",
    )


def return_channel_expired(request: dict, _original: dict) -> None:
    channel = next(row for row in request["host_selection"]["root"]["channels"] if row["id"] == "identity-channel")
    assert channel["prior_returns_survive_expiry"] is False
    channel["validity"]["valid_until"] = NOW


def observation_after_query(request: dict, original: dict) -> None:
    old_envelope = old_digest("authority-envelope", original["envelope"])
    observation = next(row for row in request["observations"] if row["query"]["at"] == NOW and row["query"]["subject_digest"] == old_envelope)
    observation["as_of"] = "2026-09-10T04:30:01Z"


def third_correction_divergences() -> None:
    definition = copy.deepcopy(SUCCESSORS["base_lifecycle"](
        authority_mutator=add_authority_operations(["successor"]), definition_mutator=SUCCESSORS["definition"],
        initial_clocks=[available_clock("work-clock", "1", NOW)],
    )["definition"])
    assert definition["profile"] == "DEADLINES" and definition["deadlines"] and not definition["choices"] and not definition["loops"]
    definition["profile"] = "CHOICE_LOOPS"
    emit(
        "C2-deadline-under-choice-loops-profile", "validate", ADVANCED["validate_input"](definition),
        {"status": "REFUSED", "code": "UNSUPPORTED_FEATURE", "path": ""}, ["PROF-001"],
        "The deadline-successor definition, which the DEADLINES profile admits (D2-139 runs it), declares profile CHOICE_LOOPS instead. It declares two deadlines, a DEADLINES construct. COMPOSITION section 1 requires refusal of a definition that contains a higher-profile construct under a lower profile, with code UNSUPPORTED_FEATURE.",
    )

    request, _ = authority_specimen(shared_budget=False, mutator=return_channel_expired)
    assert all(row["returned_at"] < NOW for row in request["returns"])
    emit(
        "C2-authority-return-channel-expired", "evaluate", {"kind": "AUTHORITY", "request": request},
        authority_refusal([], code="ACT_NOT_AUTHORIZED", reasons=[]), ["AUTH-CHECK-002"],
        "The access-card authority input, without shared budgets, has identity-channel valid_until at now with prior_returns_survive_expiry false. Both returns were received on 2026-09-08 inside channel validity; every other fact is current and digests are rebound. AUTHORITY-CHECKS: current channel reliance requires validity at evaluation or the survival flag, and a channel that fails this at evaluation is a phase-4 return-channel failure. The refusal is ACT_NOT_AUTHORIZED with empty reasons and empty failed_checks.",
    )

    request, _ = authority_specimen(shared_budget=False, mutator=observation_after_query)
    emit(
        "C2-authority-observation-after-query", "evaluate", {"kind": "AUTHORITY", "request": request},
        authority_refusal([], code="INPUT_INVALID", reasons=[]), ["AUTH-005"],
        "The access-card authority input, without shared budgets, has its current envelope revocation observation (query at now, 04:30:00) with as_of 04:30:01, one second after query.at; every other fact is current. AUTHORITY: an AVAILABLE as_of later than query.at is a phase-1 date-validity failure, INPUT_INVALID, and freshness is not measured for it. The refusal carries empty reasons and empty failed_checks.",
    )


# Fourth corrections (Jeff's A1, B1 and C1): a differing attributed request, late-after-release scope, a state bound to another pin.

def with_amount(record: dict, value: str) -> dict:
    row = next(row for row in record["request"]["fields"] if row["name"] == "amount")
    assert row["value"]["value"] == "150"
    row["value"]["value"] = value
    return record


def fourth_correction_controls() -> None:
    facts = fixture()
    opened, settled, released = open_state(facts), settled_state(facts), released_state(facts)
    reserved = reserved_blocked(next(row for row in opened["core"]["reservations"] if row["id"] == "reserve-a"))
    anchor_only = [{"anchor": "license-spend", "key": None}]
    assert next(row for row in released["core"]["reservations"] if row["id"] == "reserve-a")["status"] == "RELEASED"
    requirements = ["RES-WIRE-003", "RES-WIRE-004"]

    unknown = with_amount(native(facts, "UNKNOWN", "native-c2-settled-unknown-attributed-differs"), "151")
    unexpected_settle(
        facts, settled, unknown, "C2-settled-reservation-clean-unknown-attributed-differs",
        "reservation_fixture's SETTLED registry holds reserve-a settled with matched effect-1. A SETTLE carries a clean UNKNOWN record whose attributed request has amount 151 where 150 was reserved, with the retained history. The UNKNOWN row for a SETTLED reservation applies only to an attributed request equal to the reserved request, so the ordered reason list governs and a differing attributed request gives UNEXPECTED_EFFECT. The receipt is EFFECT_DISPUTED with that reason; reserve-a becomes DISPUTED and keeps matched_effect effect-1; the effect record is DISPUTED with UNEXPECTED_EFFECT, blocking the reserved key because a clean record with a null observed request has no projectable actual partition. The history is unchanged.",
    )

    for case_id, record, reason, blocked, derivation in (
        (
            "C2-open-reservation-release-attributed-differs",
            with_amount(native(facts, "NO_EFFECT", "native-c2-release-attributed-differs"), "151"), "UNEXPECTED_EFFECT", reserved,
            "reservation_fixture's OPEN registry. A RELEASE carries a clean NO_EFFECT record whose attributed request has amount 151 where 150 was reserved, with null administration because the reservation does not newly become RELEASED. The NO_EFFECT row applies only to an attributed request equal to the reserved request; the record is retained under the ordered reason list with UNEXPECTED_EFFECT, for RELEASE as for SETTLE. The receipt is EFFECT_DISPUTED; reserve-a becomes DISPUTED with matched_effect null; the effect record is DISPUTED with UNEXPECTED_EFFECT, blocking the reserved key.",
        ),
        (
            "C2-open-reservation-mismatched-release-attributed-differs",
            with_amount(native(facts, "NO_EFFECT", "native-c2-mismatched-release-attributed-differs", completion_mismatch=True, mismatch_reason="NATIVE_REQUEST_MISMATCH"), "151"),
            "NATIVE_REQUEST_MISMATCH", anchor_only,
            "reservation_fixture's OPEN registry. A RELEASE carries a NO_EFFECT record with completion_mismatch true, mismatch_reason NATIVE_REQUEST_MISMATCH, attributed amount 151 and null administration. The row for any state with an UNKNOWN or NO_EFFECT mismatch gives EFFECT_DISPUTED, and the record copies its mismatch reason. reserve-a becomes DISPUTED; the effect record is DISPUTED with NATIVE_REQUEST_MISMATCH and, as a no-effect mismatch without actual fields, blocks license-spend through a null key only.",
        ),
    ):
        _input, expected = EDGES.retained_effect_transition(
            facts, opened, case_id, "RELEASE", record, decision="EFFECT_DISPUTED", next_status="DISPUTED",
            disposition="DISPUTED", reason=reason, blocked=blocked,
        )
        assert _input["event"]["administration"] is None
        emit(case_id, "aggregate-step", _input, expected, requirements, derivation)

    case_id = "C2-released-reservation-mismatched-unknown"
    record = native(facts, "UNKNOWN", "native-c2-released-mismatched-unknown", completion_mismatch=True, mismatch_reason="NATIVE_REQUEST_MISMATCH")
    _input, expected = EDGES.retained_effect_transition(
        facts, released, case_id, "SETTLE", record, decision="EFFECT_DISPUTED", next_status="DISPUTED",
        disposition="DISPUTED", reason="NATIVE_REQUEST_MISMATCH", blocked=anchor_only,
    )
    emit(
        case_id, "aggregate-step", _input, expected, requirements,
        "reservation_fixture's RELEASED registry holds reserve-a released. A SETTLE carries an UNKNOWN record with completion_mismatch true, mismatch_reason NATIVE_REQUEST_MISMATCH, the reserved request as attributed request and the retained history. LATE_EFFECT_AFTER_RELEASE applies only to an EFFECT record, so the record copies NATIVE_REQUEST_MISMATCH. The mismatched row gives EFFECT_DISPUTED; reserve-a becomes DISPUTED; the effect record is DISPUTED with NATIVE_REQUEST_MISMATCH and a null-key block only. The history is unchanged.",
    )

    case_id = "C2-refuse-state-bound-to-other-pin"
    stale = copy.deepcopy(opened)
    stale["specification_pin"] = "sha256:" + "1" * 64
    record = native(facts, "EFFECT", "native-" + case_id.lower())
    event, host = host_and_event(facts, "SETTLE", "event-" + case_id.lower(), stale["core"]["revision"], {"native": record, "histories": [matching_history(facts, record)]})
    emit(
        case_id, "aggregate-step", reservation_request(stale, event, host), reservation_refusal(stale, "STATE_INVALID"), ["RES-WIRE-004"],
        "reservation_fixture's OPEN registry with its top-level specification_pin replaced by a different well-formed pin; the input's own pin is the candidate pin and its state digest is the digest of the supplied state, so the input pin, state digest, registry digest and clock source checks pass. The event is a SETTLE of the clean matching effect-1 record with a corroborating history. A supplied state bound to a different specification pin fails state admission with STATE_INVALID, and the exact supplied state and digest are returned.",
    )


# Freeze review corrections: findings TS-02, PY-2, PY-3 and PY-4 of the 2026-09-13 review round.

def missing_attestation_return(request: dict) -> None:
    attestation = next(row for row in request["acts"] if row["id"] == "attest-1")
    returned = next(row for row in request["returns"] if row["act_digest"] == digest("authority-act", attestation))
    request["returns"].remove(returned)
    record_digest = digest("authority-return", returned)
    records = request["host_selection"]["authenticated_records"]
    kept = [row for row in records if not (row["kind"] == "RETURN" and row["record_digest"] == record_digest)]
    assert len(kept) == len(records) - 1
    request["host_selection"]["authenticated_records"] = kept


def expired_channel_pending_grant(request: dict, original: dict) -> None:
    return_channel_expired(request, original)
    next(row for row in request["acts"] if row["id"] == "grant-1")["disposition"] = "PENDING"


def rechain_deployed(state: dict) -> None:
    authorization = state["deployment_authorization"]
    for name in ("correspondence", "source_confirmation", "policy_decision"):
        record_digest = digest("evidence", state[f"deployment_{name}_evidence"])
        state[f"deployment_{name}_evidence_digest"] = record_digest
        authorization[name + "_evidence_digest"] = record_digest
    subject = {key: value for key, value in authorization.items() if key != "authorization_evidence_digest"}
    subject_digest = digest("deployment-authorization-subject", subject)
    state["deployment_authorization_subject_digest"] = subject_digest
    state["deployment_authorization_evidence"]["subject_digest"] = subject_digest
    evidence_digest = digest("evidence", state["deployment_authorization_evidence"])
    state["deployment_authorization_evidence_digest"] = evidence_digest
    authorization["authorization_evidence_digest"] = evidence_digest
    state["deployment_authorization_digest"] = digest("deployment-authorization", authorization)
    for row in state["active"]:
        if not row["occurrence"]["predecessor_occurrence_ids"]:
            row["activation_event_digest"] = digest("deployment-activation", {
                "deployment_authorization_digest": state["deployment_authorization_digest"], "instance_id": state["instance_id"],
                "occurrence_id": row["occurrence"]["occurrence_id"],
            })


def review_round_corrections() -> None:
    facts = fixture()
    opened = open_state(facts)
    record = native(facts, "EFFECT", "native-c2-refuse-clean-effect-null-observed", observed_request=None)
    assert record["observed_request"] is None and record["actual_fields"] == [] and not record["completion_mismatch"]
    event, host = host_and_event(facts, "SETTLE", "event-c2-refuse-clean-effect-null-observed", opened["core"]["revision"], {"native": record, "histories": [copy.deepcopy(facts["history"])]})
    emit(
        "C2-refuse-clean-effect-null-observed-request", "aggregate-step", reservation_request(opened, event, host), reservation_refusal(opened, "INPUT_INVALID"), ["RES-WIRE-003"],
        "reservation_fixture's OPEN registry. A SETTLE carries a clean EFFECT for effect-1 whose observed request is null and whose actual fields are empty, with the retained history. RES-WIRE-003: a missing or unprojectable actual field permits a null observed request only with completion_mismatch true, and these relationships are semantic admission requirements. Admission fails with INPUT_INVALID and the exact supplied state is returned.",
    )

    base = base_lifecycle()
    permitted = permitted_proposal(base)
    first = dispatch_event(base, permitted, event_id="dispatch-c2-not-sent-accepted-a", attempt_status="NOT_SENT", acknowledgement_status="ACCEPTED")
    consumed = dispatch_result(permitted, first, disposition="DISPUTED", reasons=["DISPATCH_EVIDENCE_CONFLICT"], occurrence_status="OUTCOME_UNKNOWN")
    after = {"state": consumed["state"], "state_digest": consumed["state_digest"], "permit": permitted["permit"]}
    fresh = dispatch_event(base, after, event_id="dispatch-c2-not-sent-accepted-b", attempt_status="NOT_SENT", acknowledgement_status="NONE")
    emit(
        "C2-fresh-not-sent-after-not-sent-accepted", "step", step_input(base, consumed["state"], fresh), stateful_refusal(consumed["state"], "PREREQUISITE_MISSING"), ["LIFE-009"],
        "The linear root is permitted. Attempt a reports NOT_SENT with an ACCEPTED acknowledgement; the LIFE-009 table records it as DISPUTED with DISPATCH_EVIDENCE_CONFLICT, the occurrence becomes OUTCOME_UNKNOWN, and the permit may not support a fresh attempt, because disputed evidence consumes the permit. A fresh attempt b reports NOT_SENT with acknowledgement NONE. LIFE-009: a fresh attempt reported NOT_SENT with no accepted acknowledgement on a consumed permit is PREREQUISITE_MISSING, and the supplied state is returned.",
    )

    request, _ = authority_specimen(shared_budget=False, mutator=return_channel_expired)
    missing_attestation_return(request)
    emit(
        "C2-authority-missing-return-and-expired-channel", "evaluate", {"kind": "AUTHORITY", "request": request},
        authority_refusal([], code="EVIDENCE_UNAVAILABLE", reasons=[]), ["AUTH-CHECK-002", "AUTH-CHECK-004"],
        "The access-card authority input, without shared budgets, has identity-channel valid_until at now without prior_returns_survive_expiry, and the attestation act's return is removed together with its authenticated RETURN record. Phase 4 has two failures: a missing required return, EVIDENCE_UNAVAILABLE, and a return channel invalid at evaluation, ACT_NOT_AUTHORIZED. AUTHORITY-CHECKS accumulates the phase's failures and selects the first code in the order ACT_CONFLICT, GATE_REQUIRED, EVIDENCE_UNAVAILABLE, ACT_NOT_AUTHORIZED, ACT_NOT_ACCEPTED, so the refusal is EVIDENCE_UNAVAILABLE with empty reasons and failed checks.",
    )
    request, _ = authority_specimen(shared_budget=False, mutator=expired_channel_pending_grant)
    emit(
        "C2-authority-expired-channel-and-pending-grant", "evaluate", {"kind": "AUTHORITY", "request": request},
        authority_refusal([], code="ACT_NOT_AUTHORIZED", reasons=[]), ["AUTH-CHECK-002", "AUTH-CHECK-004"],
        "The access-card authority input, without shared budgets, has identity-channel valid_until at now without prior_returns_survive_expiry and the grant act's disposition PENDING, with digests rebound. Phase 4 has two failures: a return channel invalid at evaluation, ACT_NOT_AUTHORIZED, and a non-accepting act, ACT_NOT_ACCEPTED. The first in phase order is ACT_NOT_AUTHORIZED, with empty reasons and failed checks.",
    )

    definition = lifecycle_definition()
    _deploy_input, deployed = deployment(definition, authorization_time="2026-09-10T04:00:00Z")
    assert deployed["state"]["revision"] == "0"
    lifecycle_base = {"definition": definition, "definition_digest": digest("work-class-definition", definition)}

    def policy_subject(state: dict) -> None:
        state["deployment_policy_decision_evidence"]["subject_digest"] = "sha256:" + "1" * 64

    def source_pending(state: dict) -> None:
        state["deployment_source_confirmation_evidence"]["status"] = "PENDING"

    def correspondence_late(state: dict) -> None:
        assert state["deployment_authorization_clock"]["observed_time"] == "2026-09-10T04:00:00Z"
        state["deployment_correspondence_evidence"]["recorded_at"] = "2026-09-10T05:00:00Z"

    common = " The input state is the base lifecycle definition deployed at 04:00:00 (revision 0), with every dependent digest recomputed after the change: the three evidence digests, the authorization subject, authorization and evidence digests, and the root activation digest. A CLOCK event follows. "
    for case_id, mutate, rule in (
        ("C2-restart-policy-decision-subject-mismatch", policy_subject, "The retained policy-decision record names a subject digest other than the definition digest." + common + "LIFE-003 requires the policy decision's subject to be the definition digest and says restart recomputes every digest, time relation and binding; LIFE-019 refuses a broken binding as STATE_INVALID before applying the event, returning the supplied state."),
        ("C2-restart-source-confirmation-pending", source_pending, "The retained source confirmation has status PENDING." + common + "LIFE-003 requires an ACCEPTED source confirmation; LIFE-019 refuses a status violation as STATE_INVALID, returning the supplied state."),
        ("C2-restart-correspondence-after-authorization-clock", correspondence_late, "The retained correspondence record's recorded_at is 05:00:00, after the authorization clock." + common + "LIFE-003 requires each review record to be recorded no later than the authorization clock and restart recomputes every time relation; LIFE-019 refuses the broken relation as STATE_INVALID, returning the supplied state."),
    ):
        state = copy.deepcopy(deployed["state"])
        mutate(state)
        rechain_deployed(state)
        clock_event = {
            "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "clock-" + case_id.lower(), "kind": "CLOCK",
            "instance_id": state["instance_id"], "expected_state_revision": state["revision"], "expected_state_digest": state_digest(state),
            "clock": available_clock("authority-clock", "1", "2026-09-10T04:30:00Z"), "activation_clocks": [],
        }
        emit(case_id, "step", step_input(lifecycle_base, state, clock_event), stateful_refusal(state, "STATE_INVALID"), ["LIFE-003", "LIFE-019"], rule)


# Decision round (Jeff, 2026-09-14): the reservation transition does not compare the observed request with actual fields.

def decision_round_controls() -> None:
    facts = fixture()
    opened = open_state(facts)
    base_record = native(facts, "EFFECT", "native-c2-settle-renamed-actual-fields")
    history = matching_history(facts, base_record)
    record = copy.deepcopy(base_record)
    next(row for row in record["actual_fields"] if row["name"] == "amount")["name"] = "amount-paid"
    record["actual_fields"].sort(key=lambda row: row["name"].encode("utf-8"))
    assert record["observed_request"] == record["request"] and not record["completion_mismatch"]
    event, host = host_and_event(facts, "SETTLE", "event-c2-settle-renamed-actual-fields", opened["core"]["revision"], {"native": record, "histories": [history]}, administration=False)
    core = copy.deepcopy(opened["core"])
    next(row for row in core["budgets"] if row["definition"]["anchor"] == "license-spend")["history"] = history
    next(row for row in core["reservations"] if row["id"] == "reserve-a").update(status="SETTLED", matched_effect="effect-1")
    core["effects"].append(effect_record(record, "MATCHED", "MATCHED_EFFECT"))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    expected = reservation_transition(opened, event, host, core, "SETTLED", reservation_id="reserve-a")
    emit(
        "C2-settle-renamed-actual-fields", "aggregate-step", reservation_request(opened, event, host), expected, ["RES-WIRE-003"],
        "reservation_fixture's OPEN registry. A SETTLE carries a clean EFFECT for effect-1 whose attributed and observed requests equal the reserved request and whose actual fields carry the same values with amount recorded under the evidence name amount-paid, as a completion binding that renames the field produces, with the matching history. RES-WIRE-003: the reservation transition cannot see completion bindings and does not compare a nonnull observed request with the actual fields. Attributed, observed and reserved requests are equal and the journal corroborates, so the receipt is SETTLED, reserve-a is SETTLED with matched effect-1, the effect record is MATCHED with MATCHED_EFFECT, and the supplied history is retained.",
    )


BUILDERS = [
    static_controls, ancestor_deadline_controls, authority_controls, dispatch_conflict_effect, disputed_second_effect_identifier,
    reason_order_controls, conflicting_effect_on_blocked_dispute, failed_check_corrections, second_correction_controls,
    third_correction_reservations, third_correction_divergences, fourth_correction_controls,
    review_round_corrections, decision_round_controls,
]


def main() -> None:
    for build in BUILDERS:
        build()
    print(json.dumps({"output": str(GROUP), "case_ids": sorted(path.stem for path in GROUP.glob("*.json"))}, indent=2))


if __name__ == "__main__":
    main()
