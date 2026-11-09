"""Rule-derived multi-operation and structured-composition fixture helpers."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

from authority_fixture import authority_specimen
from corpus_common import canonical_bytes, digest
from fixture_factory import occurrence, structural_step
from lifecycle_factory import admitted_transition, governed_outcome, proposal_permit, state_digest


def add_authority_operations(step_ids: list[str]):
    def mutate(request: dict[str, Any], _original: dict[str, Any]) -> None:
        template = request["work_class"]["steps"][0]
        for step_id in sorted(set(step_ids), key=lambda value: value.encode("utf-8")):
            step = copy.deepcopy(template)
            step["id"] = step_id
            step["operation"] = "issue-card-" + step_id
            request["work_class"]["steps"].append(step)
        request["work_class"]["steps"].sort(key=lambda row: row["id"].encode("utf-8"))

    return mutate


def authority_projection(definition: dict[str, Any]) -> dict[str, Any]:
    referenced = {
        field["type_ref"]
        for step in definition["steps"]
        if step["kind"] in {"OPERATION", "FANOUT_EXPAND"}
        for field in step["fields"]
    }
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/authority-work-class",
        "id": definition["id"],
        "revision": definition["revision"],
        "types": sorted(
            [copy.deepcopy(row) for row in definition["types"] if row["id"] in referenced],
            key=lambda row: row["id"].encode("utf-8"),
        ),
        "steps": sorted(
            [
                {
                    key: copy.deepcopy(step[key])
                    for key in (
                        "id",
                        "operation",
                        "interface",
                        "executor_role",
                        "fields",
                        "scope_fields",
                        "required_credentials",
                        "quantity_mode",
                        "exclusive_keys",
                    )
                }
                for step in definition["steps"]
                if step["kind"] in {"OPERATION", "FANOUT_EXPAND"}
            ],
            key=lambda row: row["id"].encode("utf-8"),
        ),
    }


def authority_for_occurrence(
    base: dict[str, Any],
    occurrence_value: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    step = next(row for row in base["definition"]["steps"] if row["id"] == occurrence_value["step_id"])

    def mutate(request: dict[str, Any], _original: dict[str, Any]) -> None:
        request["work_class"] = authority_projection(base["definition"])
        request["envelope"]["id"] = "authority-" + step["id"]
        request["envelope"]["operations"] = [
            {"interface": step["interface"], "operation": step["operation"], "step": step["id"]}
        ]
        for binding in request["envelope"]["bindings"]:
            binding["step"] = step["id"]
        for condition in request["envelope"]["conditions"]:
            condition["step"] = step["id"]
        request["envelope"]["limits"]["per_action"] = [
            {
                "id": "authority-only-amount-limit",
                "step": step["id"],
                "field": "amount",
                "operator": "LTE",
                "bound": {"type_ref": "amount", "value": "1000000"},
            }
        ]
        request["proposal"]["step"] = step["id"]
        request["proposal"]["operation"] = step["operation"]
        request["proposal"]["interface"] = step["interface"]
        request["proposal"]["occurrence"] = occurrence_value["occurrence_id"]
        request["proposal"]["instance"] = occurrence_value["instance_id"]
        request["proposal"]["fields"] = [
            {
                "name": field["name"],
                "value": copy.deepcopy(next(
                    row["value"] for row in request["proposal"]["fields"] if row["name"] == field["name"]
                )),
            }
            for field in step["fields"]
        ]
        if occurrence_value["object_key"] is not None:
            fanout = next(
                row for row in base["definition"]["fanouts"]
                if row["id"] == next(
                    segment["construct_id"]
                    for segment in reversed(occurrence_value["enclosing"])
                    if segment["kind"] == "FANOUT"
                )
            )
            next(
                row for row in request["proposal"]["fields"] if row["name"] == fanout["object_request_field"]
            )["value"] = copy.deepcopy(occurrence_value["object_key"])
        request["proposal"]["fields"].sort(key=lambda row: row["name"].encode("utf-8"))
        credential = request["credentials"][0]
        credential["step"] = step["id"]
        credential["operation"] = step["operation"]
        credential["interface"] = step["interface"]

    return authority_specimen(
        shared_budget=False,
        instance_id=occurrence_value["instance_id"],
        occurrence_id=occurrence_value["occurrence_id"],
        mutator=mutate,
    )


def proposal_for_occurrence(
    base: dict[str, Any],
    state: dict[str, Any],
    occurrence_value: dict[str, Any],
    *,
    event_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    authority_input, authority_result = authority_for_occurrence(base, occurrence_value)
    step = next(row for row in base["definition"]["steps"] if row["id"] == occurrence_value["step_id"])
    executor = authority_input["proposal"]["executor"]
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "PROPOSE",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "occurrence": copy.deepcopy(occurrence_value),
        "native_request": {
            "interface": step["interface"],
            "operation": step["operation"],
            "fields": copy.deepcopy(authority_input["proposal"]["fields"]),
        },
        "executor": {
            "participant_id": executor["actor"],
            "role": executor["role"],
            "binding_digest": digest(
                "executor-binding",
                {key: executor[key] for key in ["actor", "role", "principal", "occupancy"]},
            ),
        },
        "credential_ids": sorted(
            (row["id"] for row in authority_input["credentials"]),
            key=lambda value: value.encode("utf-8"),
        ),
        "authority_input": authority_input,
        "budget_inputs": [],
        "clock_revision": "1",
        "observation_digests": sorted(
            (digest("authority-observation", row) for row in authority_input["observations"]),
            key=lambda value: value.encode("utf-8"),
        ),
    }
    return event, authority_result


def permitted_operation_proposal(
    base: dict[str, Any],
    state: dict[str, Any],
    event: dict[str, Any],
    authority_result: dict[str, Any],
) -> dict[str, Any]:
    permit_base = {**copy.deepcopy(base), "authority_result": copy.deepcopy(authority_result)}
    permit = proposal_permit(permit_base, event)
    event_digest = digest("runtime-event", event)
    proposal_digest = digest("proposal", event)

    def mutate(next_state: dict[str, Any]) -> None:
        active = next(
            row for row in next_state["active"]
            if row["occurrence"]["occurrence_id"] == event["occurrence"]["occurrence_id"]
        )
        active["status"] = "PERMITTED"
        next_state["total_actuations"] = str(int(next_state["total_actuations"]) + 1)
        counter = next(row for row in next_state["step_counters"] if row["step_id"] == event["occurrence"]["step_id"])
        counter["actuations"] = str(int(counter["actuations"]) + 1)
        next_state["proposals"].append(
            {
                "event_id": event["event_id"],
                "event_digest": event_digest,
                "proposal_digest": proposal_digest,
                "occurrence_id": event["occurrence"]["occurrence_id"],
                "disposition": "PERMITTED",
                "permit_digest": permit["permit_id"],
                "authority_result_digest": permit["authority_result_digest"],
                "reservation_receipt_digests": [],
                "prior_permit_digest": None,
            }
        )
        next_state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
        next_state["permits"].append(copy.deepcopy(permit))
        next_state["permits"].sort(key=lambda row: row["permit_id"].encode("utf-8"))

    return admitted_transition(
        state,
        event,
        disposition="PERMITTED",
        reason_codes=[],
        details=[],
        permit=permit,
        mutate=mutate,
    )


def parallel_definition(branch_ids: list[str]):
    def mutate(definition: dict[str, Any]) -> None:
        definition["profile"] = "PARALLEL_FANOUT"
        definition["steps"].extend(
            [structural_step("parallel-join", "PARALLEL_JOIN"), structural_step("parallel-split", "PARALLEL_SPLIT")]
        )
        definition["steps"].sort(key=lambda row: row["id"].encode("utf-8"))
        definition["relationships"] = [
            {"kind": "SEQUENCE", "from": "issue", "to": "parallel-split"},
            *({"kind": "SEQUENCE", "from": step_id, "to": "parallel-join"} for step_id in branch_ids),
            {"kind": "SEQUENCE", "from": "parallel-join", "to": "terminal"},
        ]
        definition["parallel_blocks"] = [
            {
                "id": "parallel-1",
                "split_step_id": "parallel-split",
                "branches": [
                    {"id": "branch-" + str(index + 1), "head_step_id": step_id}
                    for index, step_id in enumerate(branch_ids)
                ],
                "join_step_id": "parallel-join",
            }
        ]
        definition["occurrence_limits"].sort(key=lambda row: row["step_id"].encode("utf-8"))

    return mutate


def branch_occurrence(
    base: dict[str, Any],
    event: dict[str, Any],
    step_id: str,
    branch_id: str,
) -> dict[str, Any]:
    source_occurrence = event["permit"]["occurrence"]
    return occurrence(
        base["definition_digest"],
        source_occurrence["instance_id"],
        step_id,
        "1",
        [source_occurrence["occurrence_id"]],
        [
            {
                "kind": "BRANCH",
                "construct_id": "parallel-1",
                "pass": "1",
                "branch_id": branch_id,
                "object_key": None,
            }
        ],
    )


def branch_obligation(
    base: dict[str, Any],
    event: dict[str, Any],
    step_id: str,
    branch_id: str,
    occurrence_value: dict[str, Any],
) -> dict[str, Any]:
    source_id = event["permit"]["occurrence"]["occurrence_id"]
    subject = {
        "kind": "PARALLEL_BRANCH",
        "construct_id": "parallel-1",
        "pass": "1",
        "source_occurrence_ids": [source_id],
        "branch_id": branch_id,
        "object_key": None,
        "join_step_id": "parallel-join",
    }
    operation = next(row for row in base["definition"]["steps"] if row["id"] == step_id)["operation"]
    return {
        "obligation_id": digest("obligation", subject),
        **subject,
        "creation_event_digest": digest("runtime-event", event),
        "status": "OPEN",
        "expected_occurrence_id": occurrence_value["occurrence_id"],
        "required_operation": operation,
        "waiting_on": None,
        "completion_basis": None,
    }


def parallel_entry_result(
    base: dict[str, Any],
    dispatched: dict[str, Any],
    event: dict[str, Any],
    branch_ids: list[str],
    *,
    stop_step: str | None = None,
    install_deadlines: bool = False,
) -> dict[str, Any]:
    outcome = governed_outcome(event, dispatched, classification="MATCHED", disputed=False)
    selected = next(
        row
        for row in base["definition"]["relationships"]
        if row["kind"] == "SEQUENCE" and row["from"] == event["permit"]["occurrence"]["step_id"]
    )
    selected_digest = digest("relationship", selected)
    source_occurrence = event["permit"]["occurrence"]
    branch_rows: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    for index, step_id in enumerate(branch_ids):
        branch_id = "branch-" + str(index + 1)
        occurrence_value = branch_occurrence(base, event, step_id, branch_id)
        branch_rows.append(
            (step_id, branch_id, occurrence_value, branch_obligation(base, event, step_id, branch_id, occurrence_value))
        )

    def mutate(state: dict[str, Any]) -> None:
        state["outcomes"].append(copy.deepcopy(outcome))
        state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active_index = next(
            index
            for index, row in enumerate(state["active"])
            if row["occurrence"]["occurrence_id"] == source_occurrence["occurrence_id"]
        )
        state["active"].pop(active_index)
        state["completed"].append(
            {
                "occurrence": copy.deepcopy(source_occurrence),
                "disposition": "SUCCEEDED",
                "evidence_digest": digest("native-evidence", event["native_evidence"]),
                "occurred_at": event["native_evidence"]["event_time"],
                "route_label": None,
                "selected_relationship_digest": selected_digest,
                "late": False,
            }
        )
        state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        if stop_step is not None:
            state["status"] = "STOPPED"
            return
        for step_id, _branch_id, occurrence_value, obligation in branch_rows:
            deadline_ids: list[str] = []
            if install_deadlines:
                definition_deadline = next(
                    row for row in base["definition"]["deadlines"] if row["step_id"] == step_id
                )
                activation_clock = next(
                    row for row in event["activation_clocks"] if row["source"] == definition_deadline["clock_source"]
                )
                due_rule = definition_deadline["due"]
                if due_rule["kind"] == "ABSOLUTE_INSTANT":
                    due = due_rule["instant"]
                else:
                    seconds_per_unit = {"SECOND": 1, "MINUTE": 60, "HOUR": 3600, "DAY": 86400}
                    instant = datetime.strptime(activation_clock["observed_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    due = (instant + timedelta(seconds=int(due_rule["value"]) * seconds_per_unit[due_rule["unit"]])).strftime("%Y-%m-%dT%H:%M:%SZ")
                activation_subject = {
                    "deadline_id": definition_deadline["id"],
                    "occurrence_id": occurrence_value["occurrence_id"],
                    "trigger_digest": digest("runtime-event", event),
                    "source": definition_deadline["clock_source"],
                    "activation_revision": state["revision"],
                    "activation_clock_revision": activation_clock["revision"],
                    "activation_instant": activation_clock["observed_time"],
                    "activation_clock_evidence_digest": activation_clock["evidence_digest"],
                    "due": due,
                    "boundary": definition_deadline["boundary"],
                }
                state["deadlines"].append(
                    {
                        "activation_digest": digest("deadline-activation", activation_subject),
                        **activation_subject,
                        "status": "PENDING",
                        "expiry_event_digest": None,
                    }
                )
                deadline_ids = [definition_deadline["id"]]
            state["active"].append(
                {
                    "occurrence": copy.deepcopy(occurrence_value),
                    "activation_event_digest": digest("runtime-event", event),
                    "status": "ACTIVE",
                    "deadline_ids": deadline_ids,
                }
            )
            counter = next(row for row in state["step_counters"] if row["step_id"] == step_id)
            counter["activations"] = str(int(counter["activations"]) + 1)
            state["obligations"].append(copy.deepcopy(obligation))
        state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        state["obligations"].sort(key=lambda row: row["obligation_id"].encode("utf-8"))
        state["deadlines"].sort(
            key=lambda row: (
                row["due"].encode("utf-8"),
                canonical_bytes(next(
                    active["occurrence"] for active in state["active"]
                    if active["occurrence"]["occurrence_id"] == row["occurrence_id"]
                )),
                row["deadline_id"].encode("utf-8"),
            )
        )
        state["total_activations"] = str(int(state["total_activations"]) + len(branch_rows))

    details = [
        {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": event["native_evidence"]["evidence_id"]},
        {"kind": "ROUTE", "relationship_digests": [selected_digest], "construct_ids": ["parallel-1"]},
    ]
    if stop_step is None:
        return admitted_transition(
            dispatched["state"],
            event,
            disposition="COMPLETED",
            reason_codes=[],
            details=details,
            receipt_permit_digest=event["permit"]["permit_id"],
            mutate=mutate,
        )
    limit = next(row for row in base["definition"]["occurrence_limits"] if row["step_id"] == stop_step)["maximum"]
    details.append(
        {
            "kind": "LIMIT",
            "limit_kind": "STEP_OCCURRENCES",
            "limit": limit,
            "current": str(int(limit) + 1),
            "step_id": stop_step,
            "relationship_digest": selected_digest,
        }
    )
    return admitted_transition(
        dispatched["state"],
        event,
        disposition="STOPPED",
        reason_codes=["LIMIT_EXCEEDED"],
        details=details,
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )
