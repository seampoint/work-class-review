"""Independent constructors for the civilian timing control and clock evidence."""

from __future__ import annotations

import copy

from authority_fixture import rewrite
from corpus_common import digest
from equipment_observation_fixture import _configure, expected_ready
from fixture_factory import available_clock
from lifecycle_factory import admitted_transition, base_lifecycle, state_digest, withheld_proposal


CONTROL_CHECK = "transmission-content"
CONTROL_DEADLINE = "first-confirmed-content-failure"


def document_authority(request, _original):
    _configure(request, gated=False, include_session=True)
    changed = rewrite(request, {"card-system": "document-service", "issue-card": "transmit-document",
        "card-issuance": "document-transmission", "card_id": "document_id",
        "access-card-policy": "civilian-transmission-policy"})
    request.clear()
    request.update(changed)
    request["source"]["obligations"][0]["text"] = (
        "Document transmission requires ordinary declared authority and its independent amount limit. "
        "Stop pending automated transmission 600 seconds after the first admitted available-clock "
        "authority failure of transmission-content with SOURCE_OBSERVATION_RELATIONS; repeated "
        "failures cannot reset the interval and only terminal completion discharges it.")
    req = request["envelope"]["source_observation_requirements"][0]
    req.update({"id": CONTROL_CHECK, "provider": "transmission-policy-provider",
        "source": "civilian-transmission-content", "record_type": "transmission-content-assessment"})
    request["host_selection"]["root"]["providers"] = sorted(
        {*request["host_selection"]["root"]["providers"], req["provider"]}, key=str.encode)
    from equipment_observation_fixture import observation
    request["observations"] = [row for row in request["observations"] if row["query"]["purpose"] == "REVOCATION"]
    request["observations"].append(observation(req, request))


def deferred_control(seconds="600"):
    def authority_variant(request, original):
        document_authority(request, original)
        request["source"]["obligations"][0]["text"] = request["source"]["obligations"][0]["text"].replace(
            "600 seconds", seconds + " seconds")
    def definition_mutator(definition):
        definition["profile"] = "DEADLINES"
        definition["deadlines"] = [{"id": CONTROL_DEADLINE, "step_id": "issue",
            "clock_source": "authority-clock", "boundary": "AT_OR_AFTER", "expiry_target": None,
            "due": {"kind": "ELAPSED_FROM_FIRST_WITHHELD", "value": seconds, "unit": "SECOND",
                "failed_checks": [{"purpose": "SOURCE_OBSERVATION", "requirement_ref": CONTROL_CHECK,
                    "reason": "SOURCE_OBSERVATION_RELATIONS"}]}}]
    # The inherited constructor supplies deployment evidence and digests. Replace its
    # occurrence deadline with the explicitly derived waiting variant before emission.
    base = base_lifecycle(definition_mutator=definition_mutator, authority_mutator=authority_variant,
        initial_clocks=[available_clock("authority-clock", "0", "2026-09-10T04:00:00Z")])
    base["deploy_input"]["initial_clocks"] = []
    state = base["deploy_result"]["state"]
    state["clocks"] = []
    state["deadlines"] = []
    occurrence = state["active"][0]["occurrence"]
    activation = state["active"][0]["activation_event_digest"]
    creation = {"specification_pin": state["specification_pin"], "work_class_digest": base["definition_digest"],
        "instance_id": state["instance_id"], "deadline_id": CONTROL_DEADLINE,
        "occurrence_id": occurrence["occurrence_id"], "activation_event_digest": activation}
    state["deferred_deadlines"] = [{"deadline_id": CONTROL_DEADLINE,
        "occurrence_id": occurrence["occurrence_id"], "source": "authority-clock", "boundary": "AT_OR_AFTER",
        "activation_event_digest": activation, "creation_digest": digest("deferred-deadline", creation),
        "status": "WAITING"}]
    state["proposal_authority_evaluations"] = []
    state["timing_clock_events"] = []
    base["deploy_result"]["state_digest"] = state_digest(state)
    event = base["clock_event"]
    event["expected_state_digest"] = state_digest(state)
    base["clock_result"] = clock_result(state, event)
    base["proposal_event"]["expected_state_digest"] = base["clock_result"]["state_digest"]
    base["authority_result"] = expected_ready(base["authority_input"], base["authority_result"])
    for check in base["authority_result"]["checks"]:
        if check["purpose"] == "SOURCE_BINDING":
            check["requirement_ref"] = base["authority_input"]["source"]["id"]
    return base


def clock_event(state, revision, instant=None, *, status="AVAILABLE", event_id=None):
    source = "authority-clock"
    clock = {"source": source, "revision": revision, "status": status, "observed_time": instant,
        "evidence_digest": digest("clock-evidence", {"source": source, "revision": revision,
            "status": status, "observed_time": instant})}
    return {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id or "timing-clock-" + revision, "kind": "CLOCK", "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"], "expected_state_digest": state_digest(state),
        "clock": clock, "activation_clocks": []}


def clock_result(state, event):
    clock = event["clock"]
    def mutate(next_state):
        next_state["clocks"].append(copy.deepcopy(clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))
        if "timing_clock_events" in next_state:
            next_state["timing_clock_events"].append(copy.deepcopy(event))
            next_state["timing_clock_events"].sort(key=lambda row: row["event_id"].encode())
    return admitted_transition(state, event, disposition="CLOCK_RECORDED",
        reason_codes=[] if clock["status"] == "AVAILABLE" else ["CLOCK_UNAVAILABLE"],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"],
            "status": clock["status"]}], mutate=mutate)


def decorate(state, event, ordinary, mutate, *, disposition=None, reason_codes=None, details=None):
    receipt = ordinary["decision"]
    def apply(next_state):
        next_state.update({key: copy.deepcopy(value) for key, value in ordinary["state"].items()
            if key not in {"revision", "receipts", "replays"}})
        mutate(next_state)
    return admitted_transition(state, event, disposition=disposition or receipt["disposition"],
        reason_codes=receipt["reason_codes"] if reason_codes is None else reason_codes,
        details=copy.deepcopy(receipt["details"] if details is None else details),
        permit=ordinary["permit"], receipt_permit_digest=receipt["permit_digest"],
        receipt_authority_result_digest=receipt["authority_result_digest"],
        receipt_proposal_authority_evaluation_digest=receipt.get("proposal_authority_evaluation_digest"),
        mutate=apply)


def qualifying_withholding(base, state, event, refusal, *, arm=True):
    local = {**base, "clock_result": {"state": state}}
    ordinary = withheld_proposal(local, event, refusal)
    def mutate(next_state):
        timer = next_state["deferred_deadlines"][0]
        if not arm or timer["status"] != "WAITING":
            return
        evaluation = next(row for row in next_state["proposal_authority_evaluations"]
            if row["event"]["event_id"] == event["event_id"])
        clock = next(row for row in state["clocks"] if row["source"] == "authority-clock"
            and row["revision"] == event["clock_revision"])
        from fixture_factory import add_seconds
        timer.update({"status": "PENDING", "trigger": {"kind": "FIRST_WITHHELD",
            "evaluation_digest": evaluation["evaluation_digest"], "sequence": str(int(state["revision"]) + 1),
            "clock": copy.deepcopy(clock)}, "due": add_seconds(clock["observed_time"], "600")})
    return decorate(state, event, ordinary, mutate)


def stop_expiry(state, event):
    clock = event["clock"]
    def mutate(next_state):
        next_state["clocks"].append(copy.deepcopy(clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))
        if "timing_clock_events" in next_state:
            next_state["timing_clock_events"].append(copy.deepcopy(event))
            next_state["timing_clock_events"].sort(key=lambda row: row["event_id"].encode())
        timer = next_state["deferred_deadlines"][0]
        timer.update({"status": "EXPIRED", "expiry_basis": {"kind": "CLOCK",
            "event_digest": digest("runtime-event", event), "clock": copy.deepcopy(clock)}})
        active = next_state["active"].pop(0)
        next_state["completed"].append({"occurrence": active["occurrence"], "disposition": "EXPIRED",
            "evidence_digest": clock["evidence_digest"], "occurred_at": clock["observed_time"],
            "route_label": None, "selected_relationship_digest": None, "late": False})
        next_state["status"] = "STOPPED"
    return admitted_transition(state, event, disposition="STOPPED", reason_codes=["EXPIRY_STOP"],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"],
            "status": clock["status"]}, {"kind": "DEADLINE", "deadline_ids": [CONTROL_DEADLINE],
            "reasons": ["EXPIRY_STOP"]}], mutate=mutate)
