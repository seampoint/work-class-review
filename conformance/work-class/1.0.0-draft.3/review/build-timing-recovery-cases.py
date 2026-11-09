"""Construct timing/recovery expectations before either consumer executes."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from corpus_common import CASES, exact_case, write_canonical_json
from lifecycle_factory import (
    dispatch_event, dispatch_result, governed_effect_event, governed_native_evidence,
    permitted_proposal, replay_result, state_digest, stateful_refusal, step_input,
)
from timing_fixture import clock_event, clock_result
from timing_recovery_fixture import (
    DEADLINE, FAILURE_SOURCE_AMENDMENT, INITIAL_SOURCE_AMENDMENT, SOURCE_AMENDMENT, arm_branch, base_fixture, block_branches,
    blocked_expiry, branch_proposal, enter_branches, recover_expired, recovery_failure_trace,
)


GROUP = CASES / "timing-recovery"


def build(*, initial_event=False, offset=0):
    rows = []

    def add(operation, request, expected, derivation):
        rows.append(exact_case("C3-TR-" + str(len(rows) + offset + 1).zfill(3), operation, request, expected,
            ["TIME-005", "TIME-007", "REC-012", "REC-013", "REC-014", "REC-015"], derivation))

    def step(base, state, event, expected, derivation):
        add("step", step_input(base, state, event), expected, derivation)

    base = base_fixture(initial_event=initial_event)
    add("deploy", base["deploy_input"], base["deploy_result"],
        "The constructed source amendment selects a60-second first-possible-dispatch timer on required branch-a. Deployment initializes empty deferred_deadlines and timing_clock_events; activation and proposal do not start that timer. "
        + ("The mixed variant also binds the exact case-opened native record and its organizational digest vector, creating a PENDING32-minute branch-b duty before activation." if initial_event else "No initial-event feature is selected."))
    step(base, base["deploy_result"]["state"], base["clock_event"], base["clock_result"],
        "The complete initial available CLOCK event is retained. The deferred branch does not yet exist and no occurrence timer is invented; any selected initial event duty retains its fixed due.")
    permitted = permitted_proposal(base)
    step(base, base["clock_result"]["state"], base["proposal_event"], permitted,
        "Ordinary root permission retains the source amendment and unchanged authority checks before any recovery or timing trigger.")
    sent_event = dispatch_event(base, permitted, event_id="timing-recovery-root-dispatch", acknowledgement_status="ACCEPTED")
    sent = dispatch_result(permitted, sent_event, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    step(base, permitted["state"], sent_event, sent, "Root dispatch has no timer. Its bounded accepted attempt is retained normally.")
    original = governed_native_evidence(base, permitted, sent, evidence_id="timing-recovery-root-original")
    effect = governed_effect_event(permitted, sent, original, event_id="timing-recovery-root-completion")
    entered = enter_branches(base, sent, effect)
    step(base, sent["state"], effect, entered,
        "Root completion opens both exact branch obligations. The branch-a timer is WAITING and the complete original EFFECT input is retained for restart. Any selected branch-b event duty binds its sole occurrence without changing the initial due.")
    proposal, branch_permitted = branch_proposal(base, entered["state"])
    step(base, entered["state"], proposal, branch_permitted, "Branch-a permission leaves its deferred timer WAITING.")
    branch_send = dispatch_event(base, branch_permitted, event_id="timing-recovery-branch-a-dispatch")
    armed = arm_branch(base, branch_permitted, branch_send)
    step(base, branch_permitted["state"], branch_send, armed,
        "The first admitted SENT observation fixes the immutable trigger at04:30and due at04:31. It proves possible send, without inventing delivery.")
    conflict, blocked = block_branches(base, permitted, sent, armed)
    step(base, armed["state"], conflict, blocked,
        "Conflicting root evidence blocks both dependent branches and both OPEN obligations while preserving branch-a's original dispatch and fixed due.")
    expiry_event, expired = blocked_expiry(blocked["state"])
    step(base, blocked["state"], expiry_event, expired,
        "At the inclusive04:31boundary every selected due record becomes EXPIRED with its original CLOCK basis. Both branches remain blocked; no expiry route or join fires.")
    denied = copy.deepcopy(proposal)
    denied.update(event_id="timing-recovery-blocked-proposal", expected_state_revision=expired["state"]["revision"],
        expected_state_digest=expired["state_digest"])
    step(base, expired["state"], denied, stateful_refusal(expired["state"], "OCCURRENCE_NOT_ACTIVE"),
        "Expiry evidence cannot restore permission while the prerequisite remains disputed.")
    request, recovered = recover_expired(base, expired, original)
    add("step", request, recovered,
        "The independent controller establishes the original root fact. Recovery consumes the already committed expiry before resumption and returns EXPIRED. Before/after projections retain every selected timing inventory; due, trigger, expiry basis and counters stay unchanged. "
        + ("Both expired branches discharge their owners and join atomically once, reaching COMPLETE without proposing or actuating branch-b." if initial_event else "Only branch-a's owner discharges. Branch-b remains ACTIVE with its OPEN obligation, so the join cannot fire."))
    replay = copy.deepcopy(request)
    replay.update(state=copy.deepcopy(recovered["state"]), state_digest=recovered["state_digest"])
    add("step", replay, replay_result(recovered["state"], request["event"]["event_id"]),
        "Exact recovery replay in a fresh consumer reconstructs the complete before/after timing projections and original expiry clock without extending the due, repeating a route or changing the current state.")
    next_clock = clock_event(recovered["state"], "3", "2026-09-10T04:31:01Z", event_id="timing-recovery-next-clock")
    next_result = clock_result(recovered["state"], next_clock)
    step(base, recovered["state"], next_clock, next_result,
        "A fresh nonreplay CLOCK validates the recovered checkpoint and appends evidence. Consumed expiries cannot fire or join again.")
    members = ["due", "before_projection", "after_projection"]
    if initial_event:
        members.extend(["before_event_duties", "after_event_duties"])
    for member in members:
        changed = copy.deepcopy(recovered["state"])
        if member == "due":
            changed["deferred_deadlines"][0]["due"] = "2026-09-10T04:32:00Z"
        elif member in ("before_projection", "after_projection"):
            del changed["recovery_records"][0][member]["deferred_deadlines"]
        else:
            del changed["recovery_records"][0]["before_projection" if member == "before_event_duties" else "after_projection"]["event_duties"]
        event = clock_event(changed, "3", "2026-09-10T04:31:01Z", event_id="timing-recovery-omit-" + member)
        step(base, changed, event, stateful_refusal(changed, "STATE_INVALID"),
            "Rehashing the checkpoint cannot change the original due or omit a feature-selected timing inventory from either recovery projection.")
    return rows


def main():
    private_output = len(sys.argv) > 1
    destination = Path(sys.argv[1]).resolve() if private_output else GROUP
    if private_output and not destination.name.startswith("recovery-"):
        raise ValueError("timing recovery output must use the assigned recovery run root")
    rows = build()
    rows.extend(build(initial_event=True, offset=len(rows)))
    base, request, stopped = recovery_failure_trace()
    def failure_case(supplied, expected, derivation):
        rows.append(exact_case("C3-TR-" + str(len(rows) + 1).zfill(3), "step", supplied, expected,
            ["TIME-004", "TIME-007", "REC-013", "REC-014", "REC-015"], derivation))
    failure_case(request, stopped,
        "The fictional source selects one atomic recovery closure. Committed branch-a expiry first attempts branch-a-next. The exact branch-b native result retained during the dispute then completes branch-b, but branch-b-next has an already-due ordinary deadline. STOPPED preserves both original completions and the committed expiry, rolls back every successor and retains only the ordinary branch-b attempted route. Deadline details merge into one sorted inventory with the activation failure reason.")
    replay = copy.deepcopy(request)
    replay.update(state=copy.deepcopy(stopped["state"]), state_digest=stopped["state_digest"])
    failure_case(replay, replay_result(stopped["state"], request["event"]["event_id"]),
        "Fresh-process recovery replay reconstructs the atomic rollback and unique merged deadline and ordinary-route details without reviving a successor.")
    event = clock_event(stopped["state"], "3", "2026-09-10T04:31:01Z", event_id="timing-failed-next-clock")
    failure_case(step_input(base, stopped["state"], event), clock_result(stopped["state"], event),
        "A fresh CLOCK validates the stopped recovery checkpoint, appends historical clock evidence and leaves all rolled-back successors absent.")
    for row in rows:
        write_canonical_json(destination / (row["id"] + ".json"), row)
    if private_output:
        write_canonical_json(destination / "source.json", {"status": "FICTIONAL_REVIEW_VARIANT",
            "text": SOURCE_AMENDMENT, "initial_event_variant": INITIAL_SOURCE_AMENDMENT,
            "failure_variant": FAILURE_SOURCE_AMENDMENT,
            "deadline_id": DEADLINE, "expected_before_consumer_execution": True})
    print(json.dumps({"timing_recovery_cases": len(rows), "output": str(destination),
        "consumer_imported_or_executed": False}))


if __name__ == "__main__":
    main()
