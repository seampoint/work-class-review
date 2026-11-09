"""Independent fictional deferred expiry and recovery constructors."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path

from composition_fixture import (
    add_authority_operations, parallel_definition, parallel_entry_result,
    permitted_operation_proposal, proposal_for_occurrence,
)
from corpus_common import canonical_bytes, digest
from dependency_dispute_common import dependency_dispute_result
from fixture_factory import add_seconds, available_clock
from lifecycle_factory import (
    admitted_transition, base_lifecycle, dispatch_event, dispatch_result,
    effect_result, governed_effect_event, governed_native_evidence, permit_dispatch, permitted_proposal, state_digest,
)
from recovery_fixture import authorize, configuration
from recovery_lifecycle_fixture import PROJECTION_KEYS
from timing_fixture import clock_event, clock_result, decorate


COMPOSITION = runpy.run_path(str(Path(__file__).with_name("build-recovery-composition-cases.py")))
BRANCHES = ["branch-a", "branch-b"]
DEADLINE = "branch-a-first-dispatch"
EVENT_DEADLINE = "branch-b-initial-event"
SOURCE_AMENDMENT = (
    "For this fictional review variant, branch-a expires 60 seconds after its first "
    "admitted possibly sent dispatch. Its inclusive boundary routes to parallel-join. "
    "A dependency dispute preserves the original due and records expiry without routing. "
    "Establishing the original prerequisite consumes any committed expiry before "
    "the branch can resume; branch-b remains required for the join."
)
INITIAL_SOURCE_AMENDMENT = (
    "The mixed fictional variant additionally requires branch-b within 32 minutes "
    "of its authenticated case-opened record, bound to the exact beneficiary. "
    "Its inclusive expiry routes to parallel-join. Recovery consumes both original "
    "expiries atomically; the complete parallel pass then terminates once."
)
FAILURE_SOURCE_AMENDMENT = (
    "For this fictional recovery variant, branch-a expires 60 seconds after its "
    "first admitted possibly sent dispatch and routes to branch-a-next. Branch-b "
    "success routes to branch-b-next, whose inclusive absolute deadline is "
    "2026-09-10T04:31:00Z. Both successor operations normally lead to parallel-join. "
    "A dependency dispute retains original due instants and native results. "
    "Recovery consumes committed expiry and retained results in one closure. "
    "If either route cannot activate, retain the original source completions "
    "and expiry evidence, stop, and commit no successor activation."
)
FAILURE_DEADLINE = "branch-b-next-already-due"
PROJECTION = (*PROJECTION_KEYS, "deferred_deadlines")


def base_fixture(*, initial_event=False, recovery_failure=False):
    def authority_variant(request, original):
        add_authority_operations(BRANCHES + (["branch-a-next", "branch-b-next"] if recovery_failure else []))(request, original)
        request["source"]["obligations"][0]["text"] += " " + (FAILURE_SOURCE_AMENDMENT if recovery_failure else SOURCE_AMENDMENT)
        if initial_event:
            request["source"]["obligations"][0]["text"] += " " + INITIAL_SOURCE_AMENDMENT

    def definition_variant(definition):
        parallel_definition(BRANCHES)(definition)
        definition["recovery"] = configuration()
        definition["deadlines"] = [{"id": DEADLINE, "step_id": "branch-a",
            "clock_source": "authority-clock", "boundary": "AT_OR_AFTER",
            "expiry_target": "parallel-join", "due": {
                "kind": "ELAPSED_FROM_FIRST_DISPATCH", "value": "60", "unit": "SECOND"}}]
        definition["relationships"].append({"kind": "EXPIRY", "from": "branch-a",
            "to": "parallel-join", "deadline_ref": DEADLINE})
        if recovery_failure:
            definition["deadlines"][0]["expiry_target"] = "branch-a-next"
            for relation in definition["relationships"]:
                if relation["from"] in BRANCHES:
                    relation["to"] = relation["from"] + "-next"
            definition["relationships"].extend({"kind": "SEQUENCE", "from": step + "-next", "to": "parallel-join"} for step in BRANCHES)
            definition["deadlines"].append({"id": FAILURE_DEADLINE, "step_id": "branch-b-next",
                "clock_source": "authority-clock", "boundary": "AT_OR_AFTER", "expiry_target": None,
                "due": {"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-10T04:31:00Z"}})
        if initial_event:
            definition["types"].append({"id": "INSTANT", "kind": "INSTANT", "nonnegative": False, "unit": None})
            definition["types"].sort(key=lambda row: row["id"].encode())
            definition["event_anchors"] = [{"id": "case-opened", "provider": "fictional-case-provider",
                "source": "fictional-case-ledger", "record_type": "CASE_OPENED",
                "time": {"kind": "EVENT_TIME", "type_ref": "INSTANT"},
                "fields": [{"name": "beneficiary", "type_ref": "IDENTITY"}], "subject_fields": ["beneficiary"],
                "request_bindings": [{"step_id": step, "subject_field": "beneficiary", "target_request_field": "beneficiary"}
                    for step in ("branch-b", "issue")]}]
            definition["deadlines"].append({"id": EVENT_DEADLINE, "step_id": "branch-b",
                "clock_source": "authority-clock", "boundary": "AT_OR_AFTER", "expiry_target": "parallel-join",
                "due": {"kind": "ELAPSED_FROM_EVENT_ANCHOR", "anchor_ref": "case-opened", "value": "32", "unit": "MINUTE"}})
            definition["relationships"].append({"kind": "EXPIRY", "from": "branch-b",
                "to": "parallel-join", "deadline_ref": EVENT_DEADLINE})

    base = base_lifecycle(instance_id="timing-recovery-" + ("failed-closure" if recovery_failure else "mixed" if initial_event else "first-dispatch"),
        authority_mutator=authority_variant, definition_mutator=definition_variant,
        initial_clocks=[available_clock("authority-clock", "0", "2026-09-10T04:00:00Z")] if initial_event else None)
    initial = base["deploy_result"]["state"]
    initial.update(deferred_deadlines=[], timing_clock_events=[])
    if initial_event:
        value = next(row["value"] for row in base["authority_input"]["proposal"]["fields"] if row["name"] == "beneficiary")
        native = {"provider": "fictional-case-provider", "source": "fictional-case-ledger", "record_type": "CASE_OPENED",
            "provider_record_id": "case-opened-1", "provider_revision": "1", "event_time": "2026-09-10T03:59:00Z",
            "observed_at": "2026-09-10T03:59:30Z", "fields": [{"name": "beneficiary", "value": copy.deepcopy(value)}],
            "evidence_ref": "fictional-case-opened-record", "provenance_digest": digest("fictional-provenance", {"id": "case-opened-1"})}
        wrapper = {"anchor_ref": "case-opened", "specification_pin": initial["specification_pin"],
            "work_class_digest": initial["work_class_digest"], "organization_id": initial["deployment_organization_id"],
            "instance_id": initial["instance_id"], "record": native, "record_digest": digest("event-anchor-record", native)}
        anchor_digest = digest("initial-event-anchor", wrapper)
        authorization = copy.deepcopy(initial["deployment_authorization"])
        authorization["event_anchor_digests"] = [{"anchor_ref": "case-opened", "anchor_digest": anchor_digest}]
        subject = digest("deployment-authorization-subject", {k: v for k, v in authorization.items() if k != "authorization_evidence_digest"})
        evidence = copy.deepcopy(initial["deployment_authorization_evidence"])
        evidence["subject_digest"] = subject
        evidence_digest = digest("evidence", evidence)
        authorization["authorization_evidence_digest"] = evidence_digest
        authorization_digest = digest("deployment-authorization", authorization)
        initial.update(deployment_authorization=authorization, deployment_authorization_digest=authorization_digest,
            deployment_authorization_subject_digest=subject, deployment_authorization_evidence=evidence,
            deployment_authorization_evidence_digest=evidence_digest, initial_event_anchors=[wrapper])
        initial["active"][0]["activation_event_digest"] = digest("deployment-activation", {
            "deployment_authorization_digest": authorization_digest, "instance_id": initial["instance_id"],
            "occurrence_id": initial["active"][0]["occurrence"]["occurrence_id"]})
        body = {"specification_pin": initial["specification_pin"], "work_class_digest": initial["work_class_digest"],
            "instance_id": initial["instance_id"], "deadline_id": EVENT_DEADLINE, "anchor_digest": anchor_digest,
            "due": "2026-09-10T04:31:00Z", "boundary": "AT_OR_AFTER", "source": "authority-clock"}
        initial["event_duties"] = [{"deadline_id": EVENT_DEADLINE, "target_step_id": "branch-b",
            "source": "authority-clock", "boundary": "AT_OR_AFTER", "anchor_ref": "case-opened", "anchor_digest": anchor_digest,
            "due": body["due"], "creation_digest": digest("initial-event-duty", body), "status": "PENDING",
            "occurrence_id": None, "binding_event_digest": None}]
        base["deploy_input"].update(deployment_authorization=authorization, authorization_evidence=evidence, event_anchors=[wrapper])
        base["deploy_result"]["deployment_authorization_digest"] = authorization_digest
    base["deploy_result"]["state_digest"] = state_digest(initial)
    base["clock_event"]["expected_state_digest"] = state_digest(initial)
    base["clock_result"] = clock_result(initial, base["clock_event"])
    base["proposal_event"]["expected_state_digest"] = base["clock_result"]["state_digest"]
    return base


def retain_effect(before, event, ordinary, mutation=lambda _state: None):
    def mutate(state):
        outcome = next(row for row in state["outcomes"] if row["event_id"] == event["event_id"])
        outcome["source_event"] = copy.deepcopy(event)
        outcome["outcome_digest"] = digest("outcome", {k: v for k, v in outcome.items() if k != "outcome_digest"})
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode())
        mutation(state)
    return decorate(before, event, ordinary, mutate)


def enter_branches(base, dispatched, event):
    ordinary = parallel_entry_result(base, dispatched, event, BRANCHES)

    def bind(state):
        active = next(row for row in state["active"] if row["occurrence"]["step_id"] == "branch-a")
        occurrence = active["occurrence"]["occurrence_id"]
        activation = digest("runtime-event", event)
        body = {"specification_pin": state["specification_pin"], "work_class_digest": state["work_class_digest"],
            "instance_id": state["instance_id"], "deadline_id": DEADLINE,
            "occurrence_id": occurrence, "activation_event_digest": activation}
        active["deadline_ids"] = [DEADLINE]
        state["deferred_deadlines"] = [{"deadline_id": DEADLINE, "occurrence_id": occurrence,
            "source": "authority-clock", "boundary": "AT_OR_AFTER", "activation_event_digest": activation,
            "creation_digest": digest("deferred-deadline", body), "status": "WAITING"}]
        if state.get("event_duties"):
            target = next(row for row in state["active"] if row["occurrence"]["step_id"] == "branch-b")
            target["deadline_ids"] = [EVENT_DEADLINE]
            state["event_duties"][0].update(occurrence_id=target["occurrence"]["occurrence_id"], binding_event_digest=activation)

    return retain_effect(dispatched["state"], event, ordinary, bind)


def branch_proposal(base, state):
    occurrence = next(row["occurrence"] for row in state["active"] if row["occurrence"]["step_id"] == "branch-a")
    event, authority_result = proposal_for_occurrence(base, state, occurrence, event_id="timing-recovery-propose-branch-a")
    return event, permitted_operation_proposal(base, state, event, authority_result)


def arm_branch(base, permitted, event):
    ordinary = dispatch_result(permitted, event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")

    def arm(state):
        record = next(row for row in state["dispatches"] if row["event_id"] == event["event_id"])
        clock = next(row for row in state["clocks"] if row["source"] == "authority-clock" and row["revision"] == "1")
        state["deferred_deadlines"][0].update(status="PENDING", due=add_seconds(event["attempt"]["attempted_at"], "60"),
            trigger={"kind": "FIRST_DISPATCH", "event_digest": digest("runtime-event", event),
                "sequence": state["revision"], "dispatch_digest": record["dispatch_digest"],
                "dispatch_attempt_digest": record["dispatch_attempt_digest"], "clock": copy.deepcopy(clock)})
    return decorate(permitted["state"], event, ordinary, arm)


def block_branches(base, root_permitted, root_dispatched, armed):
    event, evidence = COMPOSITION["DEP"].ancestor_dispute(base, root_permitted, root_dispatched, armed,
        evidence_id="timing-recovery-root-conflict", event_id="timing-recovery-retain-root-conflict",
        record="timing-recovery-conflicting-root-record")
    evidence["event_time"] = "2026-09-10T04:29:59Z"
    event["native_evidence"] = evidence
    original = next(row for row in armed["state"]["outcomes"] if row["permit_digest"] == root_permitted["permit"]["permit_id"])
    ordinary = dependency_dispute_result(base, armed, event,
        conflicts=[original["native_evidence"]["evidence_id"]],
        source_occurrence_id=root_permitted["permit"]["occurrence"]["occurrence_id"])
    return event, retain_effect(armed["state"], event, ordinary)


def blocked_expiry(state):
    event = clock_event(state, "2", "2026-09-10T04:31:00Z", event_id="timing-recovery-expire-while-blocked")
    clock = event["clock"]

    def expire(next_state):
        next_state["clocks"].append(copy.deepcopy(clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))
        next_state["timing_clock_events"].append(copy.deepcopy(event))
        next_state["timing_clock_events"].sort(key=lambda row: row["event_id"].encode())
        for row in next_state["deferred_deadlines"] + next_state.get("event_duties", []):
            row.update(status="EXPIRED", expiry_basis={"kind": "CLOCK", "event_digest": digest("runtime-event", event), "clock": copy.deepcopy(clock)})
    expected = admitted_transition(state, event, disposition="EXPIRED", reason_codes=[], details=[
        {"kind": "CLOCK", "source": "authority-clock", "revision": "2", "status": "AVAILABLE"},
        {"kind": "DEADLINE", "deadline_ids": [DEADLINE] + ([EVENT_DEADLINE] if state.get("event_duties") else []), "reasons": []}], mutate=expire)
    return event, expected


def recover_expired(base, expired, original):
    request = COMPOSITION["dispose"](base, expired["state"], original, "timing-recovery-establish-original-root")
    before, event = request["state"], request["event"]
    relations = [row for row in base["definition"]["relationships"] if row["kind"] == "EXPIRY"]
    clock = before["deferred_deadlines"][0]["expiry_basis"]["clock"]

    def restore_and_expire(state):
        for active in state["active"]:
            active["status"] = "DISPATCHED" if active["occurrence"]["step_id"] == "branch-a" else "ACTIVE"
        for obligation in state["obligations"]:
            obligation["status"] = "OPEN"
        for relation in relations:
            active = next(row for row in state["active"] if row["occurrence"]["step_id"] == relation["from"])
            state["active"].remove(active)
            state["completed"].append({"occurrence": copy.deepcopy(active["occurrence"]), "disposition": "EXPIRED",
                "evidence_digest": clock["evidence_digest"], "occurred_at": clock["observed_time"], "route_label": None,
                "selected_relationship_digest": digest("relationship", relation), "late": False})
            owner = next(row for row in state["obligations"] if row["expected_occurrence_id"] == active["occurrence"]["occurrence_id"])
            operation = next(row["operation"] for row in base["definition"]["steps"] if row["id"] == relation["from"])
            owner.update(status="DISCHARGED", expected_occurrence_id=None, required_operation=None,
                completion_basis={"kind": "DIRECT_EVENT", "event_digest": digest("runtime-event", event),
                    "evidence_digest": clock["evidence_digest"], "occurrence_id": active["occurrence"]["occurrence_id"], "operation": operation})
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        if len(relations) == 2:
            for owner in state["obligations"]:
                owner["status"] = "JOINED"
            state["status"] = "COMPLETE"

    route = [digest("relationship", relation) for relation in relations]
    if len(relations) == 2:
        route.append(digest("relationship", next(row for row in base["definition"]["relationships"] if row["from"] == "parallel-join")))
    details = [{"kind": "DEADLINE", "deadline_ids": [DEADLINE] + ([EVENT_DEADLINE] if len(relations) == 2 else []), "reasons": []},
        {"kind": "ROUTE", "relationship_digests": sorted(route), "construct_ids": ["parallel-1"]}]
    ordinary = COMPOSITION["expected"](request, restore_and_expire, details=details, disposition="EXPIRED")

    def apply(state):
        state.update({key: copy.deepcopy(value) for key, value in ordinary["state"].items()
            if key not in {"revision", "receipts", "replays"}})
        record = state["recovery_records"][-1]
        keys = (*PROJECTION, *(["event_duties"] if "event_duties" in before else []))
        record["before_projection"] = {key: copy.deepcopy(before[key]) for key in keys}
        record["after_projection"] = {key: copy.deepcopy(state[key]) for key in keys}

    expected = admitted_transition(before, event, disposition="EXPIRED", reason_codes=[], details=details,
        receipt_recovery_disposition_digest=ordinary["decision"]["recovery_disposition_digest"], mutate=apply)
    return request, expected


def recovery_failure_trace():
    base = base_fixture(recovery_failure=True)
    root_permitted = permitted_proposal(base)
    event = dispatch_event(base, root_permitted, event_id="timing-failed-root-dispatch", acknowledgement_status="ACCEPTED")
    root_sent = dispatch_result(root_permitted, event, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    original = governed_native_evidence(base, root_permitted, root_sent, evidence_id="timing-failed-root-original")
    event = governed_effect_event(root_permitted, root_sent, original, event_id="timing-failed-root-completion")
    entered = enter_branches(base, root_sent, event)
    _, first_permitted = branch_proposal(base, entered["state"])
    event = dispatch_event(base, first_permitted, event_id="timing-failed-branch-a-dispatch")
    armed = arm_branch(base, first_permitted, event)
    occurrence = next(row["occurrence"] for row in armed["state"]["active"] if row["occurrence"]["step_id"] == "branch-b")
    event, authority = proposal_for_occurrence(base, armed["state"], occurrence, event_id="timing-failed-propose-branch-b")
    second_permitted = permitted_operation_proposal(base, armed["state"], event, authority)
    event = dispatch_event(base, second_permitted, event_id="timing-failed-branch-b-dispatch")
    second_sent = dispatch_result(second_permitted, event, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")
    _, blocked = block_branches(base, root_permitted, root_sent, second_sent)
    native = governed_native_evidence(base, second_permitted, second_sent, evidence_id="timing-failed-retained-branch-b",
        native_operation_id="timing-failed-native-branch-b")
    event = governed_effect_event(second_permitted, blocked, native, event_id="timing-failed-retain-branch-b",
        dispatch_digest=permit_dispatch(second_sent["state"], second_permitted["permit"])["dispatch_digest"])
    ordinary = effect_result(base, second_permitted, blocked, event, classification="MATCHED", disposition="OUTCOME_RETAINED",
        reason_codes=["DEPENDENCY_DISPUTED"], occurrence_status=None, disputed=False)
    retained = retain_effect(blocked["state"], event, ordinary)
    _, expired = blocked_expiry(retained["state"])
    request = COMPOSITION["dispose"](base, expired["state"], original, "timing-failed-restore-original-root")
    before, event = request["state"], request["event"]
    clock = before["deferred_deadlines"][0]["expiry_basis"]["clock"]
    event["activation_clocks"] = [copy.deepcopy(clock)]
    event["controller"] = None
    host = request["recovery_host"]
    host["authenticated_records"] = [row for row in host["authenticated_records"] if row["kind"] != "RECOVERY_RETURN"]
    authorize({"configuration": {"principal": before["deployment_organization_id"], "recovery": base["definition"]["recovery"]},
        "clock": {"instant": clock["observed_time"]}}, event, host, operation="ESTABLISH_EFFECT", scope_digest=digest("recovery-target", event["target"]))
    relations = {step: next(row for row in base["definition"]["relationships"]
        if row["from"] == step and row["kind"] == ("EXPIRY" if step == "branch-a" else "SEQUENCE")) for step in BRANCHES}

    def complete_sources(state):
        for active in list(state["active"]):
            step = active["occurrence"]["step_id"]
            evidence_digest = clock["evidence_digest"] if step == "branch-a" else digest("native-evidence", native)
            state["active"].remove(active)
            state["completed"].append({"occurrence": copy.deepcopy(active["occurrence"]),
                "disposition": "EXPIRED" if step == "branch-a" else "SUCCEEDED", "evidence_digest": evidence_digest,
                "occurred_at": clock["observed_time"] if step == "branch-a" else native["event_time"], "route_label": None,
                "selected_relationship_digest": digest("relationship", relations[step]), "late": False})
            owner = next(row for row in state["obligations"] if row["expected_occurrence_id"] == active["occurrence"]["occurrence_id"])
            owner.update(status="DISCHARGED", expected_occurrence_id=None, required_operation=None,
                completion_basis={"kind": "DIRECT_EVENT", "event_digest": digest("runtime-event", event),
                    "evidence_digest": evidence_digest, "occurrence_id": active["occurrence"]["occurrence_id"],
                    "operation": next(row["operation"] for row in base["definition"]["steps"] if row["id"] == step)})
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["status"] = "STOPPED"

    details = [{"kind": "DEADLINE", "deadline_ids": [DEADLINE, FAILURE_DEADLINE], "reasons": ["DEADLINE_ALREADY_DUE"]},
        {"kind": "ROUTE", "relationship_digests": [digest("relationship", relations["branch-b"])], "construct_ids": []}]
    ordinary = COMPOSITION["expected"](request, complete_sources, details=details, disposition="STOPPED", reasons=["DEADLINE_ALREADY_DUE"])

    def apply(state):
        state.update({key: copy.deepcopy(value) for key, value in ordinary["state"].items() if key not in {"revision", "receipts", "replays"}})
        record = state["recovery_records"][-1]
        record["before_projection"] = {key: copy.deepcopy(before[key]) for key in PROJECTION}
        record["after_projection"] = {key: copy.deepcopy(state[key]) for key in PROJECTION}
    expected = admitted_transition(before, event, disposition="STOPPED", reason_codes=["DEADLINE_ALREADY_DUE"], details=details,
        receipt_recovery_disposition_digest=ordinary["decision"]["recovery_disposition_digest"], mutate=apply)
    return base, request, expected
