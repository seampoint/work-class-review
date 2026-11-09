"""Derive civilian timing and current-clock decisions without a consumer."""

from __future__ import annotations

import copy
import json

from authority_fixture import authority_refusal
from corpus_common import CASES, digest, exact_case, write_canonical_json
from equipment_observation_fixture import expected_ready, refresh, source_refusal
from fixture_factory import add_seconds
from lifecycle_factory import (
    dispatch_event, dispatch_result, effect_result, governed_effect_event, governed_native_evidence,
    permitted_proposal, replay_result, state_digest, stateful_refusal, step_input,
)
from timing_fixture import (
    CONTROL_CHECK, CONTROL_DEADLINE, clock_event, clock_result, decorate, deferred_control,
    qualifying_withholding, stop_expiry,
)


GROUP = CASES / "timing-lifecycle"


def proposal(base, state, event_id, *, instant="2026-09-10T04:30:00Z", revision="1", failure=None):
    event = copy.deepcopy(base["proposal_event"])
    event.update(event_id=event_id, expected_state_revision=state["revision"],
        expected_state_digest=state_digest(state), clock_revision=revision)
    authority = refresh(base["authority_input"], instant, evaluation_point="PROPOSE")
    if failure == "CLOCK_UNAVAILABLE":
        authority["clock"].update(status="UNAVAILABLE", instant=None)
        authority["observations"] = []
        event["clock_revision"] = None
    elif failure:
        row = next(row for row in authority["observations"]
            if row["query"].get("requirement_id") == CONTROL_CHECK)
        if failure == "SOURCE_OBSERVATION_RELATIONS":
            row["fields"][0]["value"]["value"] = False
        elif failure == "SOURCE_OBSERVATION_STALE":
            row["as_of"] = "2026-09-10T04:29:59Z"
        else:
            raise ValueError(failure)
    event["authority_input"] = authority
    event["observation_digests"] = sorted(digest("authority-observation", row)
        for row in authority["observations"])
    refusal = (authority_refusal([], reasons=[failure]) if failure == "CLOCK_UNAVAILABLE"
        else source_refusal(authority, CONTROL_CHECK, failure) if failure else None)
    return event, refusal


def build():
    rows = []

    def add(operation, supplied, expected, derivation):
        cid = "C3-TL-" + str(len(rows) + 1).zfill(3)
        rows.append(exact_case(cid, operation, supplied, expected,
            ["TIME-001", "TIME-005", "TIME-006", "TIME-007"], derivation))

    def step(base, state, event, expected, derivation):
        add("step", step_input(base, state, event), expected, derivation)

    base = deferred_control()
    add("deploy", base["deploy_input"], base["deploy_result"],
        "The fictional civilian control selects 600 seconds from the first proved content-check failure. Deployment creates a WAITING timer, an empty complete authority-evaluation carrier and an empty complete CLOCK-event carrier. Activation alone starts no interval.")
    initial = base["deploy_result"]["state"]
    current = base["clock_result"]["state"]
    step(base, initial, base["clock_event"], base["clock_result"],
        "An available current clock is retained with its exact complete event, but no failure has occurred and the deferred timer remains WAITING.")

    event, refusal = proposal(base, current, "content-first-failure", failure="SOURCE_OBSERVATION_RELATIONS")
    armed = qualifying_withholding(base, current, event, refusal)
    step(base, current, event, armed,
        "The exact content requirement's false Boolean fails its declared relation. The complete authority refusal is retained and its first qualified receipt starts the immutable 600-second interval at04:30, due04:40.")

    repeated, repeated_refusal = proposal(base, armed["state"], "content-repeat-failure", failure="SOURCE_OBSERVATION_RELATIONS")
    step(base, armed["state"], repeated,
        qualifying_withholding(base, armed["state"], repeated, repeated_refusal),
        "A repeated qualifying failure retains a second complete evaluation but leaves the first trigger and04:40due unchanged.")

    stale, stale_refusal = proposal(base, current, "content-other-failure", failure="SOURCE_OBSERVATION_STALE")
    step(base, current, stale, qualifying_withholding(base, current, stale, stale_refusal, arm=False),
        "A stale content response withholds authority and remains attributable, but does not match the source's exact RELATIONS selector. The timer stays WAITING.")

    outage_event = clock_event(current, "2", status="UNAVAILABLE")
    outage = clock_result(current, outage_event)
    step(base, current, outage_event, outage,
        "A later unavailable clock supersedes the earlier available permission clock. It preserves evidence and starts no selected-check interval.")
    unavailable_event, unavailable_refusal = proposal(base, outage["state"], "content-clock-unknown", failure="CLOCK_UNAVAILABLE")
    unknown = qualifying_withholding(base, outage["state"], unavailable_event, unavailable_refusal, arm=False)
    step(base, outage["state"], unavailable_event, unknown,
        "An admitted null-revision unavailable-clock evaluation is retained completely. It proves neither the selected content failure nor its time and cannot arm the timer.")

    for failure in (None, "SOURCE_OBSERVATION_RELATIONS"):
        old, _ = proposal(base, outage["state"], "old-available-" + str(failure), failure=failure)
        step(base, outage["state"], old, stateful_refusal(outage["state"], "CLOCK_INVALID"),
            "The proposal presents revision1 after revision2became unavailable. Current-clock binding fails before either authority readiness or a policy refusal can be accepted.")

    resumed_event = clock_event(unknown["state"], "3", "2026-09-10T04:31:00Z")
    resumed = clock_result(unknown["state"], resumed_event)
    step(base, unknown["state"], resumed_event, resumed,
        "The available revision3restores current-clock evidence while retaining the earlier unavailable evaluation. No selected failure has yet been proved.")
    first_known, known_refusal = proposal(base, resumed["state"], "content-first-proved-after-outage",
        instant="2026-09-10T04:31:00Z", revision="3", failure="SOURCE_OBSERVATION_RELATIONS")
    step(base, resumed["state"], first_known,
        qualifying_withholding(base, resumed["state"], first_known, known_refusal),
        "The first qualified selected-check failure after the outage starts the expressly declared first proved interval at04:31, due04:41. It does not claim the earlier unknown-time attempt began a divergence interval.")

    before = clock_event(armed["state"], "2", "2026-09-10T04:39:59Z")
    step(base, armed["state"], before, clock_result(armed["state"], before),
        "One second before the inclusive boundary the original timer remains PENDING.")
    equal = clock_event(armed["state"], "2", "2026-09-10T04:40:00Z")
    step(base, armed["state"], equal, stop_expiry(armed["state"], equal),
        "At the inclusive600-second boundary the pending transmission expires and the explicit source stop applies. No permit or dispatch is invented.")

    armed_outage_event = clock_event(armed["state"], "2", status="UNAVAILABLE", event_id="armed-clock-outage")
    armed_outage = clock_result(armed["state"], armed_outage_event)
    step(base, armed["state"], armed_outage_event, armed_outage,
        "An outage preserves the armed trigger and04:40due. It neither expires nor resets the interval.")
    beyond = clock_event(armed_outage["state"], "3", "2026-09-10T04:41:00Z")
    step(base, armed_outage["state"], beyond, stop_expiry(armed_outage["state"], beyond),
        "The resumed clock is beyond the original due, so restart plus outage cannot extend the source interval. The admitted clock and expiry are retained together.")

    replay = step_input(base, armed["state"], event)
    add("step", replay, replay_result(armed["state"], event["event_id"]),
        "Exact replay returns the original first failure decision and the current complete state, with no new evaluation or timer trigger.")

    for key in ("due", "proposal_authority_evaluations", "timing_clock_events"):
        changed = copy.deepcopy(armed["state"])
        if key == "due":
            changed["deferred_deadlines"][0]["due"] = "2026-09-10T04:41:00Z"
        else:
            changed[key] = []
        next_event = clock_event(changed, "2", "2026-09-10T04:31:00Z", event_id="tamper-" + key)
        step(base, changed, next_event, stateful_refusal(changed, "STATE_INVALID"),
            "Rehashing a checkpoint cannot validate a changed fixed due or omitted original authority/CLOCK evidence. Restart reconstructs the first decision and its complete admitted inputs.")

    ready_event, _ = proposal(base, armed["state"], "content-ready-after-failure")
    local = {**base, "clock_result": {"state": armed["state"], "role": armed["state"]["role"]},
        "authority_result": expected_ready(ready_event["authority_input"], base["authority_result"]),
        "permit_expires_at": add_seconds("2026-09-10T04:30:00Z", "300")}
    ready = permitted_proposal(local, ready_event)
    step(base, armed["state"], ready_event, ready,
        "Later successful content authority can issue a bounded permit, but readiness alone does not discharge the source timer. The first failure interval remains fixed until terminal completion or expiry.")

    for starting in (current, armed["state"]):
        ready_event, _ = proposal(base, starting, "ready-before-terminal-" + starting["revision"])
        local = {**base, "clock_result": {"state": starting, "role": starting["role"]},
            "authority_result": expected_ready(ready_event["authority_input"], base["authority_result"])}
        permitted = permitted_proposal(local, ready_event)
        sent_event = dispatch_event(base, permitted, event_id="send-before-terminal-" + starting["revision"])
        sent = dispatch_result(permitted, sent_event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")
        native = governed_native_evidence(base, permitted, sent, evidence_id="terminal-transmission-" + starting["revision"])
        terminal_event = governed_effect_event(permitted, sent, native, event_id="complete-transmission-" + starting["revision"])
        ordinary = effect_result(base, permitted, sent, terminal_event, classification="MATCHED",
            disposition="COMPLETED", reason_codes=[], occurrence_status=None, disputed=False,
            complete_disposition="SUCCEEDED", route=True)
        def discharge(next_state):
            outcome = next_state["outcomes"][-1]
            outcome["source_event"] = copy.deepcopy(terminal_event)
            outcome["outcome_digest"] = digest("outcome", {key: value for key, value in outcome.items()
                if key != "outcome_digest"})
            next_state["deferred_deadlines"][0].update(status="DISCHARGED", discharge_basis={
                "kind": "COMPLETION", "event_digest": digest("runtime-event", terminal_event),
                "occurrence_id": terminal_event["permit"]["occurrence"]["occurrence_id"],
                "evidence_digest": digest("native-evidence", native)})
        completed = decorate(sent["state"], terminal_event, ordinary, discharge)
        step(base, sent["state"], terminal_event, completed,
            "Exact native terminal completion discharges the same-occurrence timer. A WAITING timer gains no invented trigger or due; an armed timer retains its original trigger and due together with the completion basis.")
        terminal_replay = step_input(base, completed["state"], terminal_event)
        add("step", terminal_replay, replay_result(completed["state"], terminal_event["event_id"]),
            "Fresh restart verifies the discharged timer against terminal native evidence and exact replay leaves its trigger history unchanged.")

    overflow_base = deferred_control("999999999999")
    overflow_state = overflow_base["clock_result"]["state"]
    overflow_event, overflow_refusal = proposal(overflow_base, overflow_state, "overflow-first-content-failure",
        failure="SOURCE_OBSERVATION_RELATIONS")
    original = qualifying_withholding(overflow_base, overflow_state, overflow_event, overflow_refusal, arm=False)
    try:
        add_seconds("2026-09-10T04:30:00Z", "999999999999")
        raise AssertionError("independent overflow premise did not hold")
    except OverflowError:
        pass
    def retain_overflow(next_state):
        evaluation = next_state["proposal_authority_evaluations"][0]
        next_state["deferred_deadlines"][0].update(status="TRIGGER_OVERFLOW", trigger={
            "kind": "FIRST_WITHHELD", "evaluation_digest": evaluation["evaluation_digest"],
            "sequence": str(int(overflow_state["revision"]) + 1), "clock": copy.deepcopy(overflow_state["clocks"][0])},
            reason="DEADLINE_TIME_OVERFLOW")
        next_state["status"] = "STOPPED"
    overflow = decorate(overflow_state, overflow_event, original, retain_overflow, disposition="STOPPED",
        reason_codes=sorted([*original["decision"]["reason_codes"], "DEADLINE_TIME_OVERFLOW"]),
        details=[*original["decision"]["details"], {"kind": "DEADLINE", "deadline_ids": [CONTROL_DEADLINE],
            "reasons": ["DEADLINE_TIME_OVERFLOW"]}])
    step(overflow_base, overflow_state, overflow_event, overflow,
        "The first proved failure is retained as a complete original AUTHORITY/WITHHELD evaluation. Adding the source duration exceeds year9999, so the final decision stops and the separate overflow timer keeps its trigger with no fabricated due.")
    add("step", step_input(overflow_base, overflow["state"], overflow_event),
        replay_result(overflow["state"], overflow_event["event_id"]),
        "Restart reproduces the base authority refusal before the timer overflow and exact replay cannot rearm or erase the retained failure.")
    return rows


if __name__ == "__main__":
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print(json.dumps({"civilian_timing_cases": len(rows), "implementation_or_output_consulted": False}))
