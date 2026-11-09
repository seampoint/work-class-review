"""Derive recovery obligations and expiry consequences from REC-013/014 and LIFE.

Only source fixture constructors are imported. Consumer code and outputs do not
participate in these expectations.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from composition_fixture import add_authority_operations, parallel_entry_result
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from dependency_dispute_common import dependency_dispute_result
from fixture_factory import available_clock
from lifecycle_factory import (
    admitted_transition, base_lifecycle, dispatch_event, dispatch_result, effect_result,
    governed_effect_event, governed_native_evidence, permit_dispatch, permitted_proposal,
    replay_result, state_digest, step_input,
)
from recovery_fixture import authorize, configuration, generation, normalize_native
from recovery_lifecycle_fixture import PROJECTION_KEYS


HERE = Path(__file__).resolve().parent
GROUP = CASES / "recovery-composition"


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / (name.replace("_", "-") + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


DEP = module("build_dependency_dispute_cases")
NEST = module("build_nested_parallel_closure_cases")
original_nested_definition = NEST.nested_definition


def recovery_nested_definition(**kwargs):
    original = original_nested_definition(**kwargs)

    def mutate(definition):
        original(definition)
        definition["recovery"] = configuration()
    return mutate


NEST.nested_definition = recovery_nested_definition


def dispose(base: dict, state: dict, original_evidence: dict, event_id: str) -> dict:
    outcome = next(row for row in state["outcomes"] if row["native_evidence"]["evidence_id"] == original_evidence["evidence_id"])
    permit = next(row for row in state["permits"] if row["permit_id"] == outcome["permit_digest"])
    dispatch = next(row for row in state["dispatches"] if row["dispatch_digest"] == outcome["dispatch_digest"])
    target = {"kind": "WORK_OUTCOME", "instance_id": state["instance_id"],
        "occurrence_id": permit["occurrence"]["occurrence_id"], "outcome_digest": outcome["outcome_digest"]}
    request = copy.deepcopy(original_evidence["attributed_request"])
    facts = [row["native_evidence"] for row in state["outcomes"] if row["permit_digest"] == permit["permit_id"]]
    covered = sorted({digest("recovery-fact", normalize_native(row)) for row in facts + [original_evidence]})
    clock = max((row for row in state["clocks"] if row["source"] == "authority-clock"), key=lambda row: int(row["revision"]))
    packet = {"id": event_id + "-packet", "provider": original_evidence["provider"], "source": original_evidence["source"],
        "record_type": "RECOVERY_ADJUDICATION", "record_digest": digest("provider-recovery-record", {"target": target}),
        "evidence_ref": event_id + "-provider-evidence", "provider_revision": "3", "target": target, "request": request,
        "covered_evidence_digests": covered, "superseded_evidence_digests": covered,
        "attempts": [{"id": dispatch["attempt"]["attempt_id"], "attempt_digest": dispatch["dispatch_attempt_digest"],
            "executor": permit["executor"]["participant_id"], "connector": dispatch["connector"]["id"],
            "request_digest": digest("reservation-native-request", request), "maximum_executions": "1",
            "effect_ids": [original_evidence["native_operation_id"]], "no_effect": False}],
        "conclusion": "EFFECT_ESTABLISHED", "native_outcomes": [copy.deepcopy(original_evidence)],
        "rules_out_past_and_future_effects": False, "complete_attempt_inventory": True}
    event = {"schema": state["schema"].rsplit("/", 1)[0] + "/runtime-event", "event_id": event_id, "kind": "DISPOSE",
        "instance_id": state["instance_id"], "expected_state_revision": state["revision"], "expected_state_digest": state_digest(state),
        "target": target, "requested_result": "ESTABLISH_EFFECT", "evidence": packet, "controller": None,
        "policy_digest": None, "supersedes": None, "clock_revision": clock["revision"], "activation_clocks": []}
    host = {"caller": permit["executor"]["participant_id"], "recovery_bases": [], "authenticated_records": [{"kind": "RECOVERY_EVIDENCE",
        "record_digest": digest("recovery-evidence", packet), "provider": packet["provider"], "source": packet["source"]}], "pending_evidence": []}
    authority = {"configuration": {"principal": state["deployment_organization_id"], "recovery": base["definition"]["recovery"]},
        "clock": {"instant": clock["observed_time"]}}
    authorize(authority, event, host, operation="ESTABLISH_EFFECT", scope_digest=digest("recovery-target", target))
    supplied = step_input(base, state, event)
    supplied["recovery_host"] = host
    return supplied


def expected(supplied: dict, mutate, *, details=None, disposition="DISPOSITION_RECORDED", reasons=None) -> dict:
    before, event = supplied["state"], supplied["event"]
    incident = digest("recovery-incident", {"principal": before["deployment_organization_id"], "target": event["target"]})
    body = {"incident_digest": incident, "generation_digest": generation(event["evidence"]), "result": "ESTABLISH_EFFECT",
        "policy_digest": None, "controller": copy.deepcopy(event["controller"]), "supersedes": None}
    clock = next(row for row in before["clocks"] if row["source"] == "authority-clock" and row["revision"] == event["clock_revision"])
    record = {"id": digest("recovery-disposition", body), **body, "acceptance_basis_digest": None, "target": copy.deepcopy(event["target"]),
        "evidence": copy.deepcopy(event["evidence"]), "event_digest": digest("runtime-event", event),
        "accepted_at": clock["observed_time"], "source_event": copy.deepcopy(event)}

    def apply(state):
        prior = {key: copy.deepcopy(before[key]) for key in PROJECTION_KEYS}
        mutate(state)
        state["recovery_records"].append({"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(supplied["recovery_host"]),
            "disposition": record, "before_projection": prior, "after_projection": {key: copy.deepcopy(state[key]) for key in PROJECTION_KEYS}})
    return admitted_transition(before, event, disposition=disposition, reason_codes=reasons or [], details=details or [],
        receipt_recovery_disposition_digest=record["id"], mutate=apply)


def build():
    rows = []

    def add(supplied, result, derivation):
        cid = "C3-RP-" + str(len(rows) + 1).zfill(3)
        rows.append(exact_case(cid, "step", supplied, result, ["REC-012", "REC-013", "REC-014", "REC-015"], derivation))

    base, outer = NEST.setup_outer("recovery-nested", child_to_parent_join=True)
    _, parent_dispatched, parent_effect = NEST.execute(base, outer["state"], "outer-a", "recovery-parent")
    nested = NEST.nested_entry_result(base, parent_dispatched, parent_effect)
    first_permit, first_dispatched, first_effect = NEST.execute(base, nested["state"], "child-a", "recovery-first-child")
    first = NEST.direct_obligation_completion(base, first_dispatched, first_effect)
    fields = copy.deepcopy(first_effect["native_evidence"]["actual_fields"])
    next(row for row in fields if row["name"] == "card_id")["value"]["value"] = "conflicting-card"
    conflict_native = governed_native_evidence(base, first_permit, {"state": first["state"]}, evidence_id="recovery-nested-conflict",
        native_operation_id=first_effect["native_evidence"]["native_operation_id"], actual_fields=fields,
        record_digest=digest("provider-native-record", {"record": "recovery-nested-conflict"}), dispatch_digest=first_effect["dispatch_digest"])
    conflict_event = governed_effect_event(first_permit, {"state": first["state"]}, conflict_native,
        event_id="retain-recovery-nested-conflict", dispatch_digest=first_effect["dispatch_digest"])
    conflict = NEST.conflict_result(base, first["state"], first_permit["permit"], first_effect["dispatch_digest"], conflict_event)
    add(step_input(base, first["state"], conflict_event), conflict,
        "A child completion dispute propagates through the child pass into its exact waiting parent, while independent siblings remain open.")
    request = dispose(base, conflict["state"], first_effect["native_evidence"], "restore-recovery-nested-frontier")

    def restore_partial(state):
        for obligation in state["obligations"]:
            if obligation["status"] == "DISPUTED":
                obligation["status"] = "DISCHARGED" if obligation["completion_basis"] is not None else "WAITING"

    restored = expected(request, restore_partial)
    add(request, restored, "Original child fact restores its discharge and outward waiting parent. Open child-b and outer-b remain unresolved, so no join or route fires and no counters change.")
    replay = copy.deepcopy(request)
    replay.update(state=copy.deepcopy(restored["state"]), state_digest=restored["state_digest"])
    add(replay, replay_result(restored["state"], request["event"]["event_id"]), "Fresh-process exact replay validates the restored nested discharge/waiting projection without joining a partial pass.")

    _, sibling_dispatch, sibling_event = NEST.execute(base, conflict["state"], "child-b", "recovery-second-child")
    second = NEST.direct_obligation_completion(base, sibling_dispatch, sibling_event)
    _, outer_dispatch, outer_event = NEST.execute(base, second["state"], "outer-b", "recovery-outer-sibling")
    waiting = NEST.direct_obligation_completion(base, outer_dispatch, outer_event)
    join_request = dispose(base, waiting["state"], first_effect["native_evidence"], "recover-and-join-both-passes")
    child_pass = copy.deepcopy(next(row["waiting_on"] for row in waiting["state"]["obligations"] if row["waiting_on"] is not None))

    def join_all(state):
        for obligation in state["obligations"]:
            obligation["status"] = "JOINED"
            if obligation["waiting_on"] is not None:
                obligation.update(waiting_on=None, expected_occurrence_id=None, required_operation=None,
                    completion_basis={"kind": "CHILD_PASS", "event_digest": digest("runtime-event", join_request["event"]), "child_pass": child_pass})
        state["status"] = "COMPLETE"

    route = {"kind": "ROUTE", "relationship_digests": sorted([digest("relationship", NEST.direct_relationship(base, step))
        for step in ("child-join", "parallel-join")]), "construct_ids": ["parallel-1", "parallel-2"]}
    joined = expected(join_request, join_all, details=[route])
    add(join_request, joined, "Every other child and outer sibling was discharged. Establishing the original disputed child restores the frontier, joins the exact nested and outer passes atomically once, and reaches COMPLETE. The trace contains only the joins' outgoing relationships; no completed branch reroutes.")
    joined_replay = copy.deepcopy(join_request)
    joined_replay.update(state=copy.deepcopy(joined["state"]), state_digest=joined["state_digest"])
    add(joined_replay, replay_result(joined["state"], join_request["event"]["event_id"]), "Restart reconstructs the recovery-induced nested join and terminal state; replay cannot fire either pass twice.")

    def deadline_definition(definition):
        DEP.branch_deadline_definition(definition)
        definition["recovery"] = configuration()

    base = base_lifecycle(instance_id="recovery-expiry", authority_mutator=add_authority_operations(DEP.BRANCHES), definition_mutator=deadline_definition)
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="recovery-expiry-root-dispatch", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    original = governed_native_evidence(base, permitted, dispatched, evidence_id="recovery-expiry-original")
    effect = governed_effect_event(permitted, dispatched, original, event_id="recovery-expiry-original-effect")
    effect["activation_clocks"] = [copy.deepcopy(base["clock_result"]["state"]["clocks"][0])]
    entered = parallel_entry_result(base, dispatched, effect, DEP.BRANCHES, install_deadlines=True)
    carrier = {**dispatched, "state": entered["state"], "state_digest": entered["state_digest"]}
    conflict_event, conflict_native = DEP.ancestor_dispute(base, permitted, dispatched, carrier,
        evidence_id="recovery-expiry-conflict", event_id="recovery-expiry-conflict-event", record="recovery-expiry-conflict")
    conflict_native["event_time"] = "2026-09-10T04:29:59Z"
    conflict_event["native_evidence"] = conflict_native
    blocked = dependency_dispute_result(base, carrier, conflict_event, conflicts=[original["evidence_id"]], source_occurrence_id=permitted["permit"]["occurrence"]["occurrence_id"])
    clock = available_clock("authority-clock", "2", "2026-09-10T04:31:00Z")
    clock_event = {"schema": conflict_event["schema"], "event_id": "recovery-expired-while-blocked", "kind": "CLOCK",
        "instance_id": blocked["state"]["instance_id"], "expected_state_revision": blocked["state"]["revision"],
        "expected_state_digest": blocked["state_digest"], "clock": clock, "activation_clocks": []}

    def expire(state):
        state["clocks"].append(copy.deepcopy(clock))
        state["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))
        deadline = next(row for row in state["deadlines"] if row["deadline_id"] == "deadline-a")
        deadline.update(status="EXPIRED", expiry_event_digest=digest("runtime-event", clock_event))

    expired = admitted_transition(blocked["state"], clock_event, disposition="EXPIRED", reason_codes=[], details=[
        {"kind": "CLOCK", "source": clock["source"], "revision": "2", "status": "AVAILABLE"},
        {"kind": "DEADLINE", "deadline_ids": ["deadline-a"], "reasons": []}], mutate=expire)
    add(step_input(base, blocked["state"], clock_event), expired, "A deadline expires while its occurrence remains dependency-blocked; no expiry route executes before recovery.")
    expiry_request = dispose(base, expired["state"], original, "recover-after-committed-expiry")
    expiry_relationship = next(row for row in base["definition"]["relationships"] if row["kind"] == "EXPIRY" and row["from"] == "branch-a")

    def follow_expiry(state):
        for active in state["active"]:
            active["status"] = "ACTIVE"
        for obligation in state["obligations"]:
            if obligation["status"] == "BLOCKED":
                obligation["status"] = "OPEN"
        active = next(row for row in state["active"] if row["occurrence"]["step_id"] == "branch-a")
        state["active"].remove(active)
        state["completed"].append({"occurrence": copy.deepcopy(active["occurrence"]), "disposition": "EXPIRED",
            "evidence_digest": clock["evidence_digest"], "occurred_at": clock["observed_time"], "route_label": None,
            "selected_relationship_digest": digest("relationship", expiry_relationship), "late": False})
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        owner = next(row for row in state["obligations"] if row["expected_occurrence_id"] == active["occurrence"]["occurrence_id"])
        owner.update(status="DISCHARGED", expected_occurrence_id=None, required_operation=None, completion_basis={"kind": "DIRECT_EVENT",
            "event_digest": digest("runtime-event", expiry_request["event"]), "evidence_digest": clock["evidence_digest"],
            "occurrence_id": active["occurrence"]["occurrence_id"], "operation": next(row["operation"] for row in base["definition"]["steps"] if row["id"] == "branch-a")})

    expiry_result = expected(expiry_request, follow_expiry, details=[{"kind": "ROUTE", "relationship_digests": [digest("relationship", expiry_relationship)], "construct_ids": ["parallel-1"]}])
    add(expiry_request, expiry_result, "Restoring the prerequisite follows the already committed expiry of branch-a, discharges its exact owner through the declared expiry edge and leaves branch-b OPEN. No due instant, permit, actuation or activation changes.")
    expiry_replay = copy.deepcopy(expiry_request)
    expiry_replay.update(state=copy.deepcopy(expiry_result["state"]), state_digest=expiry_result["state_digest"])
    add(expiry_replay, replay_result(expiry_result["state"], expiry_request["event"]["event_id"]), "Restart validates recovery-driven expiry against the original committed expiry clock, without granting a deadline extension or firing an incomplete join.")

    def parallel_definition(definition):
        DEP.parallel_definition(DEP.BRANCHES)(definition)
        definition["recovery"] = configuration()

    base = base_lifecycle(instance_id="recovery-retained-descendant", authority_mutator=add_authority_operations(DEP.BRANCHES), definition_mutator=parallel_definition)
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="retained-root-dispatch", acknowledgement_status="ACCEPTED")
    dispatched = dispatch_result(permitted, dispatch, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    root_native = governed_native_evidence(base, permitted, dispatched, evidence_id="retained-root-native")
    root_event = governed_effect_event(permitted, dispatched, root_native, event_id="retained-root-completion")
    entered = parallel_entry_result(base, dispatched, root_event, DEP.BRANCHES)
    branch_permitted = DEP.permit_branch(base, entered, "branch-a", "retained-branch-proposal")
    branch_dispatch_event = dispatch_event(base, branch_permitted, event_id="retained-branch-dispatch", acknowledgement_status="ACCEPTED")
    branch_dispatched = dispatch_result(branch_permitted, branch_dispatch_event, disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    conflict_event, conflict_native = DEP.ancestor_dispute(base, permitted, dispatched, branch_dispatched,
        evidence_id="retained-root-conflict", event_id="retained-root-conflict-event", record="retained-root-conflict")
    conflict_native["event_time"] = "2026-09-10T04:29:59Z"
    conflict_event["native_evidence"] = conflict_native
    blocked = dependency_dispute_result(base, branch_dispatched, conflict_event, conflicts=[root_native["evidence_id"]],
        source_occurrence_id=permitted["permit"]["occurrence"]["occurrence_id"])
    branch_native = governed_native_evidence(base, branch_permitted, branch_dispatched, evidence_id="retained-branch-native", native_operation_id="retained-branch-effect")
    branch_effect_event = governed_effect_event(branch_permitted, blocked, branch_native, event_id="retain-conclusive-blocked-branch",
        dispatch_digest=permit_dispatch(branch_dispatched["state"], branch_permitted["permit"])["dispatch_digest"])
    retained = effect_result(base, branch_permitted, blocked, branch_effect_event, classification="MATCHED", disposition="OUTCOME_RETAINED",
        reason_codes=["DEPENDENCY_DISPUTED"], occurrence_status=None, disputed=False)
    add(step_input(base, blocked["state"], branch_effect_event), retained, "A previously dispatched branch supplies its exact conclusive result while the ancestor is disputed. Retain the result without completing the branch or discharging its blocked obligation.")
    restore_retained = dispose(base, retained["state"], root_native, "restore-and-apply-retained-branch")
    relationship = next(row for row in base["definition"]["relationships"] if row["kind"] == "SEQUENCE" and row["from"] == "branch-a")

    def complete_retained(state):
        for active in state["active"]:
            active["status"] = "ACTIVE"
        for obligation in state["obligations"]:
            if obligation["status"] == "BLOCKED":
                obligation["status"] = "OPEN"
        active = next(row for row in state["active"] if row["occurrence"]["step_id"] == "branch-a")
        state["active"].remove(active)
        evidence_digest = digest("native-evidence", branch_native)
        state["completed"].append({"occurrence": copy.deepcopy(active["occurrence"]), "disposition": "SUCCEEDED",
            "evidence_digest": evidence_digest, "occurred_at": branch_native["event_time"], "route_label": None,
            "selected_relationship_digest": digest("relationship", relationship), "late": False})
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        owner = next(row for row in state["obligations"] if row["expected_occurrence_id"] == active["occurrence"]["occurrence_id"])
        operation = owner["required_operation"]
        owner.update(status="DISCHARGED", expected_occurrence_id=None, required_operation=None, completion_basis={"kind": "DIRECT_EVENT",
            "event_digest": digest("runtime-event", restore_retained["event"]), "evidence_digest": evidence_digest,
            "occurrence_id": active["occurrence"]["occurrence_id"], "operation": operation})

    drained = expected(restore_retained, complete_retained, details=[{"kind": "ROUTE", "relationship_digests": [digest("relationship", relationship)], "construct_ids": ["parallel-1"]}])
    add(restore_retained, drained, "Original ancestor adjudication permits the already retained exact descendant result to complete once and discharge its owner. The independent sibling remains open. No resend, actuation, activation or new effect record occurs; the recovery receipt names no new permit or authority result.")
    drained_replay = copy.deepcopy(restore_retained)
    drained_replay.update(state=copy.deepcopy(drained["state"]), state_digest=drained["state_digest"])
    add(drained_replay, replay_result(drained["state"], restore_retained["event"]["event_id"]), "Fresh-process replay reconstructs retained descendant completion and its current recovery event discharge basis without applying the native result twice.")
    return rows


def main():
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print({"recovery_composition_cases": len(rows), "implementation_or_output_consulted": False})


if __name__ == "__main__":
    main()
