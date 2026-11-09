#!/usr/bin/env python3
"""Build the amendment-batch controls for decisions D3, D6 and D7 and the CR-01 restart binding.

Derivations sealed 2026-09-13 (neo-batch-derivations-20260913/DERIVATIONS.md) before construction. Restart
controls start from committed checkpoints; the dispatch controls extend the linear fixture. Expected results
are derived with the fixture helpers, never taken from a consumer.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from checkpoint_reseal import reseal_last_transition
from composition_fixture import (
    add_authority_operations, branch_obligation, branch_occurrence, parallel_definition, permitted_operation_proposal,
    proposal_for_occurrence,
)
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from dependency_dispute_common import dependency_dispute_result
from fixture_factory import available_clock
from lifecycle_factory import (
    admitted_transition, base_lifecycle, dispatch_event, dispatch_result, governed_effect_event, governed_native_evidence,
    governed_outcome, permit_dispatch, permitted_proposal, state_digest, stateful_refusal, step_input,
)


def _module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESTART = _module("restart_admission_controls", "build-restart-admission-controls.py")
PARALLEL = _module("parallel_completion_cases", "build-parallel-completion-cases.py")
GROUP = CASES / "amendment-batch-controls"


def load(relative: str) -> dict:
    return json.loads((CASES / relative).read_text())


def emit(case_id: str, input_value: dict, expected: dict, requirements: list[str], derivation: str) -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(GROUP / f"{case_id}.json", exact_case(case_id, "step", input_value, expected, requirements, derivation))


def restart_control(case_id: str, source: str, requirements: list[str], derivation: str, *, mutate=None, refuse: bool = False) -> None:
    case = load(source)
    state = copy.deepcopy(case["expected"]["state"])
    if mutate is not None:
        mutate(state)
        reseal_last_transition(state)
    event = RESTART.clock_event(state, "clock-" + case_id.lower())
    expected = stateful_refusal(state, "STATE_INVALID") if refuse else RESTART.clock_recorded(state, event)
    emit(case_id, RESTART.restart_input(case, state, event), expected, requirements, derivation)


def deadline_ids_after_evidence_only_expiry() -> None:
    state = load("dependency-disputes/D2-237.json")["expected"]["state"]
    assert any(row["status"] == "BLOCKED_DISPUTE" and row["deadline_ids"] for row in state["active"])
    assert any(row["status"] == "EXPIRED" for row in state["deadlines"])
    restart_control(
        "C2-restart-after-evidence-only-expiry", "dependency-disputes/D2-237.json", ["LIFE-014", "LIFE-019"],
        "The checkpoint is D2-237's result: a due deadline on a dependency-blocked occurrence expired evidence-only, so the deadline record is EXPIRED while the occurrence stays BLOCKED_DISPUTE and its active row still names the deadline. A fresh available CLOCK sample asks the consumer to restart. LIFE-014 makes an active occurrence's deadline_ids the names of every deadline activated for it whatever the record's status, and LIFE-019 admits the list when it equals the deadlines declared for the step, each with a retained record in any status. The checkpoint is admitted and the CLOCK sample recorded with no other change.",
    )


def disputed_obligation_restarts() -> None:
    state = load("dependency-disputes/D2-248.json")["expected"]["state"]
    disputed = [row for row in state["obligations"] if row["status"] == "DISPUTED"]
    assert len(disputed) == 1 and disputed[0]["completion_basis"]["kind"] == "DIRECT_EVENT"
    completion_digest = disputed[0]["completion_basis"]["evidence_digest"]
    assert all(digest("native-evidence", row["native_evidence"]) != completion_digest for row in state["outcomes"] if row["classification"] == "CONFLICTING")
    restart_control(
        "C2-restart-disputed-obligation-conflicting-record", "dependency-disputes/D2-248.json", ["LIFE-013", "LIFE-019"],
        "The checkpoint is D2-248's result: branch-a's head completed and discharged its obligation, then a second conclusive record for the same permit and attempt conflicted with the completion evidence, so the completed occurrence's outcomes are disputed and the discharged obligation became DISPUTED with its DIRECT_EVENT basis retained. The record that disputes the head is the CONFLICTING outcome, whose digest differs from the completion evidence digest in the basis. A fresh available CLOCK sample asks the consumer to restart. LIFE-019 admits a completion-based DISPUTED obligation when its frontier intersects the dependency-affected set of a retained completed occurrence with disputed conclusive evidence, and a completed occurrence has such evidence when any retained governed outcome bound to its permit is disputed and asserts an established effect or no effect; it need not be the completion record. The checkpoint is admitted and the CLOCK sample recorded.",
    )
    restart_control(
        "C2-restart-disputed-waiting-ancestor", "nested-parallel-closure/D2-249.json", ["LIFE-013", "LIFE-019", "PAR-001"],
        "The checkpoint is D2-249's result: an inner branch's discharged head was disputed by a conflicting conclusive record, its obligation became DISPUTED with its direct basis retained, and the outer obligation waiting on that child pass took the waiting form of DISPUTED. A fresh available CLOCK sample asks the consumer to restart. LIFE-019 admits the completion-based DISPUTED variant through the disputed CONFLICTING outcome bound to the head's permit, and the waiting-based variant through its exact child-pass reference containing a DISPUTED obligation. The checkpoint is admitted and the CLOCK sample recorded.",
    )


def stale_correspondence_digest() -> None:
    def mutate(state: dict) -> None:
        state["deployment_correspondence_evidence_digest"] = digest("provider-native-record", {"record": "C2-STALE-CORRESPONDENCE-DIGEST"})

    restart_control(
        "C2-refuse-stale-correspondence-digest", "branch-routes/D2-114.json", ["LIFE-003", "LIFE-019"], mutate=mutate, refuse=True,
        derivation="The checkpoint is D2-114's result with its retained deployment_correspondence_evidence_digest replaced by another digest and the last transition recommitted, so the receipt binding holds and the only fault is that the retained digest matches neither digest(\"evidence\", record) for the retained correspondence record nor the deployment authorization's correspondence_evidence_digest. A fresh available CLOCK sample asks the consumer to restart. LIFE-003 retains the three review records and their digests so that restart recomputes every binding, and LIFE-019 refuses a changed digest or broken binding as STATE_INVALID before applying the next event. The refusal returns the exact supplied state.",
    )


def fresh_attempt_on_consumed_permit() -> None:
    base = base_lifecycle()
    permitted = permitted_proposal(base)
    first = dispatch_event(base, permitted, event_id="dispatch-c2-consumed-a", attempt_status="SENT", acknowledgement_status="ACCEPTED")
    consumed = dispatch_result(permitted, first, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    after = {"state": consumed["state"], "state_digest": consumed["state_digest"], "permit": permitted["permit"]}

    second = dispatch_event(base, after, event_id="dispatch-c2-consumed-b", attempt_status="SENT", acknowledgement_status="NONE")
    second["attempt"]["attempt_id"] = "attempt-2"
    expected = dispatch_result(after, second, disposition="DISPUTED", reasons=["LATE_OR_PROHIBITED_DISPATCH"], occurrence_status="BLOCKED_DISPUTE")
    emit(
        "C2-fresh-sent-attempt-on-consumed-permit", step_input(base, consumed["state"], second), expected, ["LIFE-009"],
        "Attempt attempt-1 was SENT and acknowledged ACCEPTED, so the permit is consumed. The host reports a distinct SENT attempt-2. LIFE-009 retains it as DISPUTED with LATE_OR_PROHIBITED_DISPATCH. LIFE-006 blocks the still-active source because another physical attempt may have executed. An effect attributed to attempt-1 cannot route while attempt-2 remains possible.",
    )

    not_sent = dispatch_event(base, after, event_id="dispatch-c2-consumed-c", attempt_status="NOT_SENT", acknowledgement_status="NONE")
    not_sent["attempt"]["attempt_id"] = "attempt-2"
    emit(
        "C2-fresh-not-sent-attempt-on-consumed-permit", step_input(base, consumed["state"], not_sent), stateful_refusal(consumed["state"], "PREREQUISITE_MISSING"), ["LIFE-009"],
        "The same consumed permit receives attempt-2 reported NOT_SENT with no acknowledgement. Nothing reached the connector, so there is no fact to retain for later reconciliation, and the permit was already consumed by the acknowledged first attempt. LIFE-009 refuses the fresh attempt as PREREQUISITE_MISSING and returns the exact supplied state.",
    )

    rejected = dispatch_event(base, after, event_id="dispatch-c2-consumed-d", attempt_status="REJECTED", acknowledgement_status="NONE")
    rejected["attempt"]["attempt_id"] = "attempt-2"
    emit(
        "C2-fresh-rejected-attempt-on-consumed-permit", step_input(base, consumed["state"], rejected),
        dispatch_result(after, rejected, disposition="DISPATCH_REFUSED", reasons=["LATE_OR_PROHIBITED_DISPATCH", "NATIVE_DISPATCH_REJECTED"], occurrence_status="BLOCKED_DISPUTE"), ["LIFE-006", "LIFE-009"],
        "The consumed permit receives a distinct matching REJECTED attempt. Rejection may have reached the connector, so LIFE-009 retains DISPATCH_REFUSED with LATE_OR_PROHIBITED_DISPATCH and NATIVE_DISPATCH_REJECTED. LIFE-006 blocks the active source for the disqualified possible attempt.",
    )

    changed_request = copy.deepcopy(permitted["permit"]["native_request"])
    next(row for row in changed_request["fields"] if row["name"] == "card_id")["value"]["value"] = "card-803"
    changed = dispatch_event(base, after, event_id="dispatch-c2-consumed-e", attempt_status="REJECTED", acknowledgement_status="NONE", native_request=changed_request)
    changed["attempt"]["attempt_id"] = "attempt-2"
    emit(
        "C2-fresh-rejected-changed-attempt-on-consumed-permit", step_input(base, consumed["state"], changed),
        dispatch_result(after, changed, disposition="DISPUTED", reasons=["LATE_OR_PROHIBITED_DISPATCH", "NATIVE_ARGUMENT_MISMATCH", "NATIVE_DISPATCH_REJECTED"], occurrence_status="BLOCKED_DISPUTE"), ["LIFE-006", "LIFE-009"],
        "The consumed permit receives a distinct REJECTED attempt with changed card arguments. LIFE-009 retains it as DISPUTED with LATE_OR_PROHIBITED_DISPATCH, NATIVE_ARGUMENT_MISMATCH and NATIVE_DISPATCH_REJECTED. LIFE-006 blocks the active source while that physical attempt remains possible.",
    )


def clock_sample_event(state: dict, event_id: str, clock: dict) -> dict:
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": event_id, "kind": "CLOCK",
        "instance_id": state["instance_id"], "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state), "clock": copy.deepcopy(clock), "activation_clocks": [],
    }


def deadline_parallel_entry(base: dict, carrier: dict, event: dict, heads: list[str]) -> dict:
    """The parallel entry of composition_fixture.parallel_entry_result, installing a deadline only on a head that declares
    one (COMPOSITION 6.1, LIFE-014); that helper installs one for every head."""
    outcome = governed_outcome(event, carrier, classification="MATCHED", disputed=False)
    source = event["permit"]["occurrence"]
    selected = next(row for row in base["definition"]["relationships"] if row["kind"] == "SEQUENCE" and row["from"] == source["step_id"])
    selected_digest = digest("relationship", selected)
    event_digest = digest("runtime-event", event)
    rows = []
    for index, step_id in enumerate(heads):
        branch_id = "branch-" + str(index + 1)
        occurrence_value = branch_occurrence(base, event, step_id, branch_id)
        rows.append((step_id, occurrence_value, branch_obligation(base, event, step_id, branch_id, occurrence_value)))

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        state["active"] = [row for row in state["active"] if row["occurrence"]["occurrence_id"] != source["occurrence_id"]]
        state["completed"].append({
            "occurrence": copy.deepcopy(source), "disposition": "SUCCEEDED",
            "evidence_digest": digest("native-evidence", event["native_evidence"]), "occurred_at": event["native_evidence"]["event_time"],
            "route_label": None, "selected_relationship_digest": selected_digest, "late": False,
        })
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        for step_id, occurrence_value, obligation in rows:
            deadline_ids = []
            for declared in base["definition"]["deadlines"]:
                if declared["step_id"] != step_id:
                    continue
                assert declared["due"]["kind"] == "ABSOLUTE_INSTANT"
                clock = next(row for row in event["activation_clocks"] if row["source"] == declared["clock_source"])
                subject = {
                    "deadline_id": declared["id"], "occurrence_id": occurrence_value["occurrence_id"], "trigger_digest": event_digest,
                    "source": declared["clock_source"], "activation_revision": state["revision"],
                    "activation_clock_revision": clock["revision"], "activation_instant": clock["observed_time"],
                    "activation_clock_evidence_digest": clock["evidence_digest"], "due": declared["due"]["instant"],
                    "boundary": declared["boundary"],
                }
                state["deadlines"].append({"activation_digest": digest("deadline-activation", subject), **subject, "status": "PENDING", "expiry_event_digest": None})
                deadline_ids.append(declared["id"])
            state["active"].append({
                "occurrence": copy.deepcopy(occurrence_value), "activation_event_digest": event_digest, "status": "ACTIVE",
                "deadline_ids": sorted(deadline_ids, key=lambda value: value.encode("utf-8")),
            })
            counter = next(row for row in state["step_counters"] if row["step_id"] == step_id)
            counter["activations"] = str(int(counter["activations"]) + 1)
            state["obligations"].append(copy.deepcopy(obligation))
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["obligations"].sort(key=lambda row: row["obligation_id"].encode("utf-8"))
        state["deadlines"].sort(key=lambda row: (
            row["due"].encode("utf-8"),
            canonical_bytes(next(active["occurrence"] for active in state["active"] if active["occurrence"]["occurrence_id"] == row["occurrence_id"])),
            row["deadline_id"].encode("utf-8"),
        ))
        state["total_activations"] = str(int(state["total_activations"]) + len(rows))

    return admitted_transition(
        carrier["state"], event, disposition="COMPLETED", reason_codes=[],
        details=[
            {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
            {"kind": "ROUTE", "relationship_digests": [selected_digest], "construct_ids": ["parallel-1"]},
        ],
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


def late_effect_retained(carrier: dict, event: dict) -> dict:
    """LIFE-010: a matching effect after deadline closure is LATE_MATCHED, OUTCOME_RETAINED with LATE_EFFECT, and changes
    neither the completed row, its route, the expired deadline nor the discharged obligation."""
    outcome = governed_outcome(event, carrier, classification="LATE_MATCHED", disputed=False)

    def mutate(state: dict) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))

    return admitted_transition(
        carrier["state"], event, disposition="OUTCOME_RETAINED", reason_codes=["LATE_EFFECT"],
        details=[{"kind": "EFFECT", "classification": "LATE_MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]}],
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


def disputed_expired_head_restarts() -> None:
    heads = ["outer-a", "outer-b"]
    due = "2026-09-10T04:31:00Z"

    def definition_mutator(definition: dict) -> None:
        parallel_definition(heads)(definition)
        definition["deadlines"] = [{
            "id": "outer-b-deadline", "step_id": "outer-b", "clock_source": "work-clock",
            "due": {"kind": "ABSOLUTE_INSTANT", "instant": due}, "boundary": "AT_OR_AFTER", "expiry_target": "parallel-join",
        }]
        definition["relationships"].append({"kind": "EXPIRY", "from": "outer-b", "to": "parallel-join", "deadline_ref": "outer-b-deadline"})
        definition["relationships"].sort(key=canonical_bytes)

    base = base_lifecycle(authority_mutator=add_authority_operations(heads), definition_mutator=definition_mutator)
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-c2-expired-head-root", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    work_clock = available_clock("work-clock", "1", "2026-09-10T04:30:00Z")
    clocked = RESTART.clock_recorded(dispatched["state"], clock_sample_event(dispatched["state"], "clock-c2-expired-head-work", work_clock))
    evidence = governed_native_evidence(base, permitted, clocked, evidence_id="evidence-c2-expired-head-root", native_operation_id="native-operation-c2-expired-head-root")
    effect = governed_effect_event(permitted, clocked, evidence, event_id="effect-c2-expired-head-root")
    effect["activation_clocks"] = [copy.deepcopy(work_clock)]
    entry = deadline_parallel_entry(base, clocked, effect, heads)

    outer_b = next(row["occurrence"] for row in entry["state"]["active"] if row["occurrence"]["step_id"] == "outer-b")
    proposal, authority_result = proposal_for_occurrence(base, entry["state"], outer_b, event_id="proposal-c2-expired-head")
    permitted_b = permitted_operation_proposal(base, entry["state"], proposal, authority_result)
    dispatch_b = dispatch_event(base, permitted_b, event_id="dispatch-c2-expired-head", acknowledgement_status="ACCEPTED")
    dispatched_b = dispatch_result(permitted_b, dispatch_b, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")

    expiry = clock_sample_event(dispatched_b["state"], "clock-c2-expired-head-expiry", available_clock("work-clock", "2", due))
    expired = PARALLEL.expiration_result(base, dispatched_b["state"], expiry, deadline_id="outer-b-deadline", final_join=False)
    attempt = permit_dispatch(expired["state"], permitted_b["permit"])["dispatch_digest"]
    late_evidence = governed_native_evidence(
        base, permitted_b, expired, evidence_id="evidence-c2-expired-head-late", native_operation_id="native-operation-c2-expired-head", dispatch_digest=attempt,
    )
    late = late_effect_retained(expired, governed_effect_event(permitted_b, expired, late_evidence, event_id="effect-c2-expired-head-late", dispatch_digest=attempt))
    conflict_evidence = governed_native_evidence(
        base, permitted_b, late, evidence_id="evidence-c2-expired-head-conflict", native_operation_id="native-operation-c2-expired-head",
        record_digest=digest("provider-native-record", {"record": "C2-restart-disputed-expired-head"}), dispatch_digest=attempt,
    )
    conflict = governed_effect_event(permitted_b, late, conflict_evidence, event_id="effect-c2-expired-head-conflict", dispatch_digest=attempt)
    disputed = dependency_dispute_result(base, late, conflict, conflicts=[late_evidence["evidence_id"]], source_occurrence_id=outer_b["occurrence_id"])

    state = disputed["state"]
    completed_b = next(row for row in state["completed"] if row["occurrence"]["occurrence_id"] == outer_b["occurrence_id"])
    obligation = next(row for row in state["obligations"] if row["branch_id"] == "branch-2")
    assert completed_b["disposition"] == "EXPIRED" and completed_b["evidence_digest"] == expiry["clock"]["evidence_digest"]
    assert obligation["status"] == "DISPUTED" and obligation["completion_basis"]["evidence_digest"] == expiry["clock"]["evidence_digest"]
    disputed_outcomes = [row for row in state["outcomes"] if row["disputed"]]
    assert len(disputed_outcomes) == 2 and all(row["permit_digest"] == permitted_b["permit"]["permit_id"] for row in disputed_outcomes)
    assert all(digest("native-evidence", row["native_evidence"]) != completed_b["evidence_digest"] for row in disputed_outcomes)
    event = RESTART.clock_event(state, "clock-c2-restart-disputed-expired-head")
    emit(
        "C2-restart-disputed-expired-head", step_input(base, state, event), RESTART.clock_recorded(state, event), ["LIFE-013", "LIFE-014", "LIFE-019"],
        "The checkpoint is built from a two-branch parallel block whose second head, outer-b, declares an absolute AT_OR_AFTER deadline on work-clock with expiry target parallel-join; the root effect enters the split carrying the latest work-clock record, so LIFE-014 installs that deadline PENDING on outer-b. outer-b is permitted and dispatched with an accepted acknowledgement, then a work-clock sample at the due instant expires it: the occurrence moves to completed as EXPIRED with the accepted clock evidence digest, the expiry relationship to parallel-join is selected, and under COMPOSITION 6.2 the branch-2 obligation becomes DISCHARGED with a DIRECT_EVENT basis whose evidence digest is the clock's; branch-1 stays OPEN, so no join fires. The dispatched request's matching effect then arrives for the closed occurrence: LIFE-010 classifies it LATE_MATCHED, LIFE-006 gives LATE_EFFECT, and OUTCOME_RETAINED changes nothing but the outcome list. A second conclusive record with the same provider-native operation identity and a different record digest is CONFLICTING under LIFE-013 with CONFLICTING_EFFECT; both outcomes become disputed and name each other, the dependency-affected set is outer-b alone, and the discharged branch-2 obligation becomes DISPUTED with its basis retained. A fresh available authority-clock sample asks the consumer to restart. LIFE-019 admits a completion-based DISPUTED obligation when its former discharge frontier intersects the dependency-affected set of a retained completed occurrence with disputed conclusive evidence, and a completed occurrence has such evidence when any retained governed outcome bound to its permit is disputed and asserts an established effect or no effect; that outcome need not be the record that completed the occurrence. Here no disputed outcome's digest equals the completed row's evidence digest, which is the clock's; the two disputed outcomes are bound to outer-b's permit, so the frontier, outer-b itself, intersects the set and the checkpoint is admitted. The authority-clock sample satisfies no deadline and is recorded with an empty reason set and no other change.",
    )


BUILDERS = [
    deadline_ids_after_evidence_only_expiry, disputed_obligation_restarts, disputed_expired_head_restarts, stale_correspondence_digest,
    fresh_attempt_on_consumed_permit,
]


def main() -> None:
    for build in BUILDERS:
        build()
    print(json.dumps({"output": str(GROUP), "case_ids": sorted(path.stem for path in GROUP.glob("*.json"))}, indent=2))


if __name__ == "__main__":
    main()
