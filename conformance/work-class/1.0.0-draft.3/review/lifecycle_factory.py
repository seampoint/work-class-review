"""Independent draft-2 lifecycle fixture and transition constructors."""

from __future__ import annotations

import copy
from typing import Any, Callable

from authority_fixture import authority_specimen
from corpus_common import digest
from fixture_factory import PIN, available_clock, deployment, occurrence, structural_step, typed


def lifecycle_definition(
    *,
    shared_budget: bool = False,
    authority_mutator: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    authority_input, _ = authority_specimen(shared_budget=shared_budget, mutator=authority_mutator)
    authority_class = authority_input["work_class"]
    operation = next(
        row for row in authority_class["steps"]
        if row["id"] == authority_input["proposal"]["step"]
    )
    types = copy.deepcopy(authority_class["types"])
    if not any(row["id"] == "STRING" for row in types):
        types.append({"id": "STRING", "kind": "STRING", "nonnegative": False, "unit": None})
    types.sort(key=lambda row: row["id"].encode("utf-8"))
    steps = []
    for operation_row in authority_class["steps"]:
        steps.append(
            {
                "id": operation_row["id"],
                "kind": "OPERATION",
                "executor_role": operation_row["executor_role"],
                "interface": operation_row["interface"],
                "operation": operation_row["operation"],
                "fields": copy.deepcopy(operation_row["fields"]),
                "scope_fields": copy.deepcopy(operation_row["scope_fields"]),
                "required_credentials": copy.deepcopy(operation_row["required_credentials"]),
                "authority_requirements": [
                    authority_input["envelope"]["id"]
                    if operation_row["id"] == authority_input["proposal"]["step"]
                    else "authority-" + operation_row["id"]
                ],
                "shared_budgets": ["license-spend"] if shared_budget else [],
                "prior_effect_bindings": [],
                "prior_actor_separations": [],
                "permit_seconds": "300",
                "failure_behavior": "STOP",
                "completion": {
                    "terminal_policy": "LEGACY_NONTERMINAL",
                    "effect_provider": "card-provider",
                    "effect_source": "card-system",
                    "effect_record_type": "card-result",
                    "no_effect_provider": "card-provider",
                    "no_effect_source": "card-system",
                    "no_effect_record_type": "card-no-effect",
                    "status_field": "status",
                    "status_type_ref": "STRING",
                    "success_values": [typed("STRING", "ISSUED")],
                    "failure_values": [typed("STRING", "REJECTED")],
                    "route_label_field": None,
                    "route_label_type_ref": None,
                    "evidence_bindings": [
                        {"request_field": row["name"], "evidence_field": row["name"]}
                        for row in operation_row["fields"]
                    ],
                },
            }
        )
        steps[-1]["quantity_mode"] = operation_row["quantity_mode"]
        for key in ("authority_type_refs", "dispatch_gate"):
            if key in operation_row:
                steps[-1][key] = copy.deepcopy(operation_row[key])
        steps[-1]["exclusive_keys"] = copy.deepcopy(operation_row["exclusive_keys"])
        if operation_row.get("exclusive_keys") or (operation_row.get("completion") or {}).get("terminal_policy") == "STOP_RETAIN":
            steps[-1]["completion"] = copy.deepcopy(operation_row["completion"])
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/work-class-definition",
        "specification_pin": PIN,
        "id": authority_class["id"],
        "revision": authority_class["revision"],
        "profile": "LINEAR",
        "root": operation["id"],
        "participants": [
            {
                "id": authority_input["proposal"]["executor"]["actor"],
                "role": operation["executor_role"],
                "kind": "AGENT",
            }
        ],
        "objects": [],
        "types": types,
        "steps": steps + [structural_step("terminal", "TERMINAL")],
        "relationships": [{"kind": "SEQUENCE", "from": operation["id"], "to": "terminal"}],
        "choices": [],
        "occurrence_limits": [
            {"step_id": operation_row["id"], "maximum": "1"}
            for operation_row in authority_class["steps"]
        ],
        "loops": [],
        "deadlines": [],
        "parallel_blocks": [],
        "fanouts": [],
        "shared_budgets": ["license-spend"] if shared_budget else [],
        "limits": {
            "maximum_proposals": "64",
            "maximum_activations": "64",
            "maximum_actuations": "64",
            "maximum_active_obligations": "64",
            "maximum_fanout_objects": "64",
        },
        "source": {
            "id": authority_input["source"]["id"],
            "revision": authority_input["source"]["revision"],
            "obligations": sorted((row["id"] for row in authority_input["source"]["obligations"]), key=lambda value: value.encode("utf-8")),
        },
    }


def state_identity(state: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(state)
    for replay in projected["replays"]:
        replay.pop("transaction_digest", None)
    return projected


def state_digest(state: dict[str, Any]) -> str:
    return digest("work-state", state_identity(state))


def state_core(state: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(state)
    projected["receipts"] = []
    projected["replays"] = []
    return projected


def admitted_transition(
    state: dict[str, Any],
    event: dict[str, Any],
    *,
    disposition: str,
    reason_codes: list[str],
    details: list[dict[str, Any]],
    permit: dict[str, Any] | None = None,
    receipt_permit_digest: str | None = None,
    receipt_authority_result_digest: str | None = None,
    budget_results: list[dict[str, Any]] | None = None,
    receipt_authorization_evaluation_digest: str | None = None,
    receipt_proposal_authority_evaluation_digest: str | None = None,
    receipt_completion_check_digest: str | None = None,
    receipt_decision_basis_digest: str | None = None,
    receipt_terminal_digest: str | None = None,
    receipt_recovery_disposition_digest: str | None = None,
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    before_digest = state_digest(state)
    event_digest = digest("runtime-event", event)
    next_state = copy.deepcopy(state)
    next_state["revision"] = str(int(state["revision"]) + 1)
    if mutate is not None:
        mutate(next_state)
    core_digest = digest("work-state-core", state_core(next_state))
    receipt_without_id = {
        "schema": "seampoint.work-class/1.0.0-draft.3/decision-receipt",
        "instance_id": state["instance_id"],
        "sequence": next_state["revision"],
        "event_id": event["event_id"],
        "event_digest": event_digest,
        "event_kind": event["kind"],
        "disposition": disposition,
        "reason_codes": sorted(reason_codes, key=lambda value: value.encode("utf-8")),
        "details": details,
        "permit_digest": receipt_permit_digest if receipt_permit_digest is not None else (digest("permit", {key: value for key, value in permit.items() if key != "permit_id"}) if permit else None),
        "authority_result_digest": receipt_authority_result_digest if receipt_authority_result_digest is not None else (permit["authority_result_digest"] if permit else None),
        "reservation_receipt_digests": sorted(
            [row["result"]["receipt_digest"] for row in (budget_results or [])],
            key=lambda value: value.encode("utf-8"),
        ),
        "state_before_digest": before_digest,
        "state_after_core_digest": core_digest,
    }
    if receipt_authorization_evaluation_digest is not None:
        receipt_without_id["authorization_evaluation_digest"] = receipt_authorization_evaluation_digest
    if receipt_proposal_authority_evaluation_digest is not None:
        receipt_without_id["proposal_authority_evaluation_digest"] = receipt_proposal_authority_evaluation_digest
    for name, value in [("completion_check_digest", receipt_completion_check_digest), ("decision_basis_digest", receipt_decision_basis_digest), ("terminal_digest", receipt_terminal_digest)]:
        if value is not None:
            receipt_without_id[name] = value
    if receipt_recovery_disposition_digest is not None:
        receipt_without_id["recovery_disposition_digest"] = receipt_recovery_disposition_digest
    decision_id = digest("decision-receipt", receipt_without_id)
    receipt = {"decision_id": decision_id, **receipt_without_id}
    decision_digest = decision_id
    budget_rows = [] if budget_results is None else copy.deepcopy(budget_results)
    transaction_digest = digest(
        "lifecycle-transaction",
        {
            "state_before_digest": before_digest,
            "event_digest": event_digest,
            "decision_receipt_digest": decision_digest,
            "state_after_core_digest": core_digest,
            "budget_results": budget_rows,
        },
    )
    replay = {
        "event_id": event["event_id"],
        "event_digest": event_digest,
        "decision": copy.deepcopy(receipt),
        "decision_receipt_digest": decision_digest,
        "permit": copy.deepcopy(permit),
        "budget_results": copy.deepcopy(budget_rows),
        "transition_state_digest": core_digest,
        "transaction_digest": transaction_digest,
    }
    next_state["receipts"].append(copy.deepcopy(receipt))
    next_state["replays"].append(replay)
    next_state["replays"].sort(key=lambda row: row["event_id"].encode("utf-8"))
    next_digest = state_digest(next_state)
    return {
        "status": "STEP",
        "profile": state["profile"],
        "role": state["role"],
        "decision": receipt,
        "decision_digest": decision_digest,
        "permit": copy.deepcopy(permit),
        "budget_results": budget_rows,
        "state": next_state,
        "state_digest": next_digest,
        "transition_state_digest": core_digest,
        "transaction_digest": transaction_digest,
        "replay": False,
    }


def base_lifecycle(
    *,
    shared_budget: bool = False,
    definition_mutator: Callable[[dict[str, Any]], None] | None = None,
    initial_clocks: list[dict[str, Any]] | None = None,
    instance_id: str = "case-1",
    authority_mutator: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    definition = lifecycle_definition(shared_budget=shared_budget, authority_mutator=authority_mutator)
    if definition_mutator is not None:
        definition_mutator(definition)
    deploy_input, deploy_result = deployment(
        definition,
        instance_id=instance_id,
        authorization_time="2026-09-10T04:00:00Z",
        evidence_expires_at="2026-09-12T00:00:00Z",
        initial_clocks=initial_clocks,
    )
    state0 = deploy_result["state"]
    clock = available_clock("authority-clock", "1", "2026-09-10T04:30:00Z")
    clock_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "clock-1",
        "kind": "CLOCK",
        "instance_id": instance_id,
        "expected_state_revision": state0["revision"],
        "expected_state_digest": state_digest(state0),
        "clock": clock,
        "activation_clocks": [],
    }

    def apply_clock(next_state: dict[str, Any]) -> None:
        next_state["clocks"].append(copy.deepcopy(clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))

    clock_result = admitted_transition(
        state0,
        clock_event,
        disposition="CLOCK_RECORDED",
        reason_codes=[],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]}],
        mutate=apply_clock,
    )
    root = state0["active"][0]["occurrence"]
    authority_input, authority_result = authority_specimen(
        shared_budget=shared_budget,
        instance_id=instance_id,
        occurrence_id=root["occurrence_id"],
        mutator=authority_mutator,
    )
    native_request = {
        "interface": authority_input["proposal"]["interface"],
        "operation": authority_input["proposal"]["operation"],
        "fields": copy.deepcopy(authority_input["proposal"]["fields"]),
    }
    authority_executor = authority_input["proposal"]["executor"]
    executor = {
        "participant_id": authority_executor["actor"],
        "role": authority_executor["role"],
        "binding_digest": digest(
            "executor-binding",
            {key: authority_executor[key] for key in ["actor", "role", "principal", "occupancy"]},
        ),
    }
    proposal_event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": "proposal-1",
        "kind": "PROPOSE",
        "instance_id": instance_id,
        "expected_state_revision": clock_result["state"]["revision"],
        "expected_state_digest": clock_result["state_digest"],
        "occurrence": copy.deepcopy(root),
        "native_request": native_request,
        "executor": executor,
        "credential_ids": sorted((row["id"] for row in authority_input["credentials"]), key=lambda value: value.encode("utf-8")),
        "authority_input": authority_input,
        "budget_inputs": [],
        "clock_revision": "1",
        "observation_digests": sorted(
            (digest("authority-observation", row) for row in authority_input["observations"]),
            key=lambda value: value.encode("utf-8"),
        ),
    }
    return {
        "definition": definition,
        "definition_digest": digest("work-class-definition", definition),
        "deploy_input": deploy_input,
        "deploy_result": deploy_result,
        "clock_event": clock_event,
        "clock_result": clock_result,
        "authority_input": authority_input,
        "authority_result": authority_result,
        "proposal_event": proposal_event,
    }


def proposal_permit(base: dict[str, Any], event: dict[str, Any] | None = None) -> dict[str, Any]:
    proposal = copy.deepcopy(base["proposal_event"] if event is None else event)
    authority_input = proposal["authority_input"]
    authority_result = base["authority_result"]
    act_by_digest = {digest("authority-act", act): act for act in authority_input["acts"]}
    authority_act_bases = [
        {"act_digest": act_digest, "act": copy.deepcopy(act_by_digest[act_digest])}
        for act_digest in authority_result["act_digests"]
    ]
    without_id = {
        "schema": "seampoint.work-class/1.0.0-draft.3/permit",
        "instance_id": proposal["instance_id"],
        "work_class_digest": base["definition_digest"],
        "profile": base["definition"]["profile"],
        "role": base["clock_result"]["role"],
        "occurrence": copy.deepcopy(proposal["occurrence"]),
        "proposal_digest": digest("proposal", proposal),
        "native_request": copy.deepcopy(proposal["native_request"]),
        "executor": copy.deepcopy(proposal["executor"]),
        "credential_ids": copy.deepcopy(proposal["credential_ids"]),
        "authority_result": copy.deepcopy(authority_result),
        "authority_result_digest": digest("authority-result", authority_result),
        "authority_evidence_digest": authority_result["evidence_digest"],
        "authority_act_bases": authority_act_bases,
        "prior_effect_bases": [],
        "separation_bases": [],
        "observation_digests": copy.deepcopy(proposal["observation_digests"]),
        "supersedes_permit_digest": None,
        "budget_revisions": [],
        "clock_source": authority_input["clock"]["source"],
        "clock_revision": proposal["clock_revision"],
        "expires_at": base.get("permit_expires_at", "2026-09-10T04:35:00Z"),
    }
    step = next(row for row in base["definition"]["steps"] if row["id"] == proposal["occurrence"]["step_id"])
    if step.get("dispatch_gate") or (step.get("completion") or {}).get("terminal_policy") == "STOP_RETAIN":
        without_id["authority_basis"] = copy.deepcopy(authority_input)
    return {"permit_id": digest("permit", without_id), **without_id}


def permitted_proposal(base: dict[str, Any], event: dict[str, Any] | None = None) -> dict[str, Any]:
    proposal = copy.deepcopy(base["proposal_event"] if event is None else event)
    before = base["clock_result"]["state"]
    permit = proposal_permit(base, proposal)
    event_digest = digest("runtime-event", proposal)
    proposal_digest = digest("proposal", proposal)
    authority_result_digest = permit["authority_result_digest"]

    def mutate(next_state: dict[str, Any]) -> None:
        active = next(row for row in next_state["active"] if row["occurrence"]["occurrence_id"] == proposal["occurrence"]["occurrence_id"])
        active["status"] = "PERMITTED"
        next_state["total_actuations"] = str(int(next_state["total_actuations"]) + 1)
        counter = next(row for row in next_state["step_counters"] if row["step_id"] == proposal["occurrence"]["step_id"])
        counter["actuations"] = str(int(counter["actuations"]) + 1)
        next_state["proposals"].append(
            {
                "event_id": proposal["event_id"],
                "event_digest": event_digest,
                "proposal_digest": proposal_digest,
                "occurrence_id": proposal["occurrence"]["occurrence_id"],
                "disposition": "PERMITTED",
                "permit_digest": permit["permit_id"],
                "authority_result_digest": authority_result_digest,
                "reservation_receipt_digests": [],
                "prior_permit_digest": None,
            }
        )
        next_state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
        next_state["permits"].append(copy.deepcopy(permit))
        next_state["permits"].sort(key=lambda row: row["permit_id"].encode("utf-8"))

    return admitted_transition(
        before,
        proposal,
        disposition="PERMITTED",
        reason_codes=[],
        details=[],
        permit=permit,
        mutate=mutate,
    )


def withheld_proposal(
    base: dict[str, Any],
    event: dict[str, Any],
    authority_refusal: dict[str, Any],
) -> dict[str, Any]:
    before = base["clock_result"]["state"]
    event_digest = digest("runtime-event", event)
    proposal_digest = digest("proposal", event)
    authority_result_digest = digest("authority-result", authority_refusal)
    reason_codes = sorted(
        set(["AUTHORITY_REQUIRED", authority_refusal["code"], *authority_refusal["reasons"]]),
        key=lambda value: value.encode("utf-8"),
    )
    evaluation = None
    if "proposal_authority_evaluations" in before:
        body = {"event": copy.deepcopy(event), "authority_result": copy.deepcopy(authority_refusal),
            "authority_result_digest": authority_result_digest}
        evaluation = {"evaluation_digest": digest("proposal-authority-evaluation", body), **body}

    def mutate(next_state: dict[str, Any]) -> None:
        next_state["proposals"].append(
            {
                "event_id": event["event_id"],
                "event_digest": event_digest,
                "proposal_digest": proposal_digest,
                "occurrence_id": event["occurrence"]["occurrence_id"],
                "disposition": "WITHHELD",
                "permit_digest": None,
                "authority_result_digest": authority_result_digest,
                "reservation_receipt_digests": [],
                "prior_permit_digest": None,
            }
        )
        next_state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
        if evaluation is not None:
            next_state["proposal_authority_evaluations"].append(copy.deepcopy(evaluation))
            next_state["proposal_authority_evaluations"].sort(key=lambda row: row["event"]["event_id"])

    return admitted_transition(
        before,
        event,
        disposition="WITHHELD",
        reason_codes=reason_codes,
        details=[
            {
                "kind": "AUTHORITY",
                "authority_result_digest": authority_result_digest,
                "code": authority_refusal["code"],
                "reasons": copy.deepcopy(authority_refusal["reasons"]),
                "failed_checks": copy.deepcopy(authority_refusal["failed_checks"]),
            }
        ],
        receipt_authority_result_digest=authority_result_digest,
        receipt_proposal_authority_evaluation_digest=evaluation["evaluation_digest"] if evaluation else None,
        mutate=mutate,
    )


def step_input(base: dict[str, Any], state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": base["definition"]["profile"],
        "role": state["role"],
        "specification_pin": PIN,
        "definition": copy.deepcopy(base["definition"]),
        "definition_digest": base["definition_digest"],
        "state": copy.deepcopy(state),
        "state_digest": state_digest(state),
        "event": copy.deepcopy(event),
    }


def stateful_refusal(state: dict[str, Any], code: str, budget_states: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "status": "REFUSED",
        "profile": state["profile"],
        "role": state["role"],
        "code": code,
        "path": "",
        "state": copy.deepcopy(state),
        "state_digest": state_digest(state),
        "budget_states": [] if budget_states is None else copy.deepcopy(budget_states),
    }


def dispatch_event(
    base: dict[str, Any],
    permitted: dict[str, Any],
    *,
    event_id: str,
    attempt_status: str = "SENT",
    acknowledgement_status: str = "NONE",
    native_request: dict[str, Any] | None = None,
    attempted_at: str = "2026-09-10T04:30:00Z",
    clock_revision: str = "1",
    request_digest: str | None = None,
    connector_digest: str | None = None,
    authorization_digest: str | None = None,
) -> dict[str, Any]:
    state = permitted["state"]
    permit = permitted["permit"]
    native = copy.deepcopy(permit["native_request"] if native_request is None else native_request)
    connector_subject = {"id": "card-connector", "version": "version-1"}
    connector = {
        **connector_subject,
        "binding_digest": digest("connector-binding", connector_subject) if connector_digest is None else connector_digest,
    }
    request_subject = {
        "instance_id": state["instance_id"],
        "occurrence_id": permit["occurrence"]["occurrence_id"],
        "interface": native["interface"],
        "operation": native["operation"],
        "fields": native["fields"],
    }
    attempt = {
        "attempt_id": "attempt-1",
        "status": attempt_status,
        "request_digest": digest("dispatch-native-request", request_subject) if request_digest is None else request_digest,
        "attempted_at": attempted_at,
    }
    acknowledgement = (
        {"status": "NONE", "reference": None, "observed_at": None}
        if acknowledgement_status == "NONE"
        else {"status": acknowledgement_status, "reference": "acknowledgement-1", "observed_at": attempted_at}
    )
    event = {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "DISPATCH_OBSERVED",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": permitted["state_digest"],
        "permit": copy.deepcopy(permit),
        "native_request": native,
        "connector": connector,
        "attempt": attempt,
        "acknowledgement": acknowledgement,
        "clock_revision": clock_revision,
    }
    if authorization_digest is not None:
        event["authorization_digest"] = authorization_digest
    return event


def dispatch_result(
    permitted: dict[str, Any],
    event: dict[str, Any],
    *,
    disposition: str,
    reasons: list[str],
    occurrence_status: str,
) -> dict[str, Any]:
    permit = event["permit"]
    event_digest = digest("runtime-event", event)
    attempt_subject = {
        "permit_id": permit["permit_id"],
        "native_request": event["native_request"],
        "connector": event["connector"],
        "attempt": event["attempt"],
    }
    attempt_digest = digest("dispatch-attempt", attempt_subject)
    record_without_digest = {
        "dispatch_attempt_digest": attempt_digest,
        "event_id": event["event_id"],
        "event_digest": event_digest,
        "permit_digest": permit["permit_id"],
        "native_request": copy.deepcopy(event["native_request"]),
        "connector": copy.deepcopy(event["connector"]),
        "attempt": copy.deepcopy(event["attempt"]),
        "acknowledgement": copy.deepcopy(event["acknowledgement"]),
        "clock_revision": event["clock_revision"],
    }
    if "authorization_digest" in event:
        record_without_digest["authorization_digest"] = event["authorization_digest"]
    dispatch_record = {"dispatch_digest": digest("dispatch", record_without_digest), **record_without_digest}

    def mutate(next_state: dict[str, Any]) -> None:
        next_state["dispatches"].append(dispatch_record)
        next_state["dispatches"].sort(key=lambda row: row["dispatch_digest"].encode("utf-8"))
        active = next(
            (
                row
                for row in next_state["active"]
                if row["occurrence"]["occurrence_id"] == permit["occurrence"]["occurrence_id"]
            ),
            None,
        )
        if active is not None:
            active["status"] = occurrence_status

    return admitted_transition(
        permitted["state"],
        event,
        disposition=disposition,
        reason_codes=reasons,
        details=[{"kind": "DISPATCH", "attempt_id": event["attempt"]["attempt_id"], "reasons": sorted(reasons, key=lambda value: value.encode("utf-8"))}],
        receipt_permit_digest=permit["permit_id"],
        mutate=mutate,
    )


def replay_result(state: dict[str, Any], event_id: str) -> dict[str, Any]:
    retained = next(row for row in state["replays"] if row["event_id"] == event_id)
    return {
        "status": "STEP",
        "profile": state["profile"],
        "role": state["role"],
        "decision": copy.deepcopy(retained["decision"]),
        "decision_digest": retained["decision_receipt_digest"],
        "permit": copy.deepcopy(retained["permit"]),
        "budget_results": copy.deepcopy(retained["budget_results"]),
        "state": copy.deepcopy(state),
        "state_digest": state_digest(state),
        "transition_state_digest": retained["transition_state_digest"],
        "transaction_digest": retained["transaction_digest"],
        "replay": True,
    }


def permit_dispatch(state: dict[str, Any], permit: dict[str, Any]) -> dict[str, Any]:
    """The permit's retained dispatch row. State collections sort by digest, so position carries no meaning;
    a fixture with several attempts on one permit names the attempt through `dispatch_digest` instead."""
    rows = [row for row in state["dispatches"] if row["permit_digest"] == permit["permit_id"]]
    if len(rows) != 1:
        raise ValueError(f"expected one dispatch for permit {permit['permit_id']}, found {len(rows)}")
    return rows[0]


def governed_native_evidence(
    base: dict[str, Any],
    permitted: dict[str, Any],
    dispatched: dict[str, Any],
    *,
    evidence_id: str,
    status: str = "EFFECT_ESTABLISHED",
    result_value: str = "ISSUED",
    native_operation_id: str = "native-operation-1",
    event_time: str | None = "2026-09-10T04:30:00Z",
    observed_at: str = "2026-09-10T04:30:00Z",
    actual_fields: list[dict[str, Any]] | None = None,
    collections: list[dict[str, Any]] | None = None,
    record_digest: str | None = None,
    evidence_ref: str | None = None,
    dispatch_digest: str | None = None,
) -> dict[str, Any]:
    permit = permitted["permit"]
    dispatch = (
        permit_dispatch(dispatched["state"], permit)
        if dispatch_digest is None
        else next(row for row in dispatched["state"]["dispatches"] if row["dispatch_digest"] == dispatch_digest)
    )
    attributed = {
        "work_class": base["definition"]["id"],
        "instance": permit["instance_id"],
        "occurrence": permit["occurrence"]["occurrence_id"],
        "step": permit["occurrence"]["step_id"],
        "operation": dispatch["native_request"]["operation"],
        "interface": dispatch["native_request"]["interface"],
        "fields": copy.deepcopy(dispatch["native_request"]["fields"]),
    }
    if actual_fields is None:
        if status == "EFFECT_ESTABLISHED":
            actual_fields = copy.deepcopy(dispatch["native_request"]["fields"]) + [
                {"name": "status", "value": {"type_ref": "STRING", "value": result_value}}
            ]
        else:
            actual_fields = []
    actual_fields = sorted(copy.deepcopy(actual_fields), key=lambda row: row["name"].encode("utf-8"))
    if status != "EFFECT_ESTABLISHED":
        event_time = None
    evidence = {
        "evidence_id": evidence_id,
        "native_operation_id": native_operation_id,
        "provider": "card-provider",
        "source": "card-system",
        "record_type": "card-no-effect" if status == "NO_EFFECT_ESTABLISHED" else "card-result",
        "record_digest": record_digest or digest("provider-native-record", {"record": evidence_id}),
        "evidence_ref": evidence_ref or "evidence-ref-" + evidence_id,
        "attributed_request": attributed,
        "native_request_digest": digest("native-request", attributed),
        "status": status,
        "actual_fields": actual_fields,
        "collections": copy.deepcopy(collections or []),
        "event_time": event_time,
        "observed_at": observed_at,
        "rules_out_past_and_future_effects": status == "NO_EFFECT_ESTABLISHED",
    }
    return evidence


def governed_effect_event(
    permitted: dict[str, Any],
    dispatched: dict[str, Any],
    native_evidence: dict[str, Any],
    *,
    event_id: str,
    completion_authorization: dict[str, Any] | None = None,
    budget_inputs: list[dict[str, Any]] | None = None,
    clock_revision: str | None = None,
    dispatch_digest: str | None = None,
) -> dict[str, Any]:
    state = dispatched["state"]
    dispatch = (
        permit_dispatch(state, permitted["permit"])
        if dispatch_digest is None
        else next(row for row in state["dispatches"] if row["dispatch_digest"] == dispatch_digest)
    )
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/runtime-event",
        "event_id": event_id,
        "kind": "EFFECT_OBSERVED",
        "instance_id": state["instance_id"],
        "expected_state_revision": state["revision"],
        "expected_state_digest": state_digest(state),
        "permit": copy.deepcopy(permitted["permit"]),
        "dispatch_digest": dispatch["dispatch_digest"],
        "native_evidence": copy.deepcopy(native_evidence),
        "completion_authorization": copy.deepcopy(completion_authorization),
        "budget_inputs": copy.deepcopy(budget_inputs or []),
        "clock_revision": clock_revision,
        "activation_clocks": [],
    }


def governed_outcome(
    event: dict[str, Any],
    dispatched: dict[str, Any],
    *,
    classification: str,
    disputed: bool,
    conflicts: list[str] | None = None,
    reservation_receipt_digests: list[str] | None = None,
) -> dict[str, Any]:
    dispatch = next(row for row in dispatched["state"]["dispatches"] if row["dispatch_digest"] == event["dispatch_digest"])
    without_digest = {
        "kind": "GOVERNED",
        "event_id": event["event_id"],
        "event_digest": digest("runtime-event", event),
        "permit_digest": event["permit"]["permit_id"],
        "dispatch_digest": event["dispatch_digest"],
        "dispatch_attempt_digest": dispatch["dispatch_attempt_digest"],
        "native_evidence": copy.deepcopy(event["native_evidence"]),
        "classification": classification,
        "reservation_receipt_digests": sorted(reservation_receipt_digests or [], key=lambda value: value.encode("utf-8")),
        "conflicts_with_evidence_ids": sorted(conflicts or [], key=lambda value: value.encode("utf-8")),
        "disputed": disputed,
    }
    basis = event["permit"].get("authority_basis")
    if basis is not None:
        step = next(row for row in basis["work_class"]["steps"] if row["id"] == event["permit"]["occurrence"]["step_id"])
        if (step.get("completion") or {}).get("terminal_policy") == "STOP_RETAIN":
            without_digest["source_event"] = copy.deepcopy(event)
    return {"outcome_digest": digest("outcome", without_digest), **without_digest}


def effect_result(
    base: dict[str, Any],
    permitted: dict[str, Any],
    dispatched: dict[str, Any],
    event: dict[str, Any],
    *,
    classification: str,
    disposition: str,
    reason_codes: list[str],
    occurrence_status: str | None,
    disputed: bool,
    conflicts: list[str] | None = None,
    complete_disposition: str | None = None,
    route: bool = False,
    append_outcome: bool = True,
    route_relationship_kind: str = "SEQUENCE",
    route_relationship: dict[str, Any] | None = None,
    route_label: dict[str, Any] | None = None,
    include_label_detail: bool = False,
    instance_status: str | None = None,
    update_conflicting_outcomes: bool = False,
) -> dict[str, Any]:
    outcome = governed_outcome(event, dispatched, classification=classification, disputed=disputed, conflicts=conflicts)
    relationship = None
    if route:
        relationship = route_relationship or next(
            row for row in base["definition"]["relationships"] if row["kind"] == route_relationship_kind
        )
    relationship_digest = digest("relationship", relationship) if relationship is not None else None

    def mutate(next_state: dict[str, Any]) -> None:
        if instance_status is not None:
            next_state["status"] = instance_status
        if update_conflicting_outcomes:
            current_evidence_id = event["native_evidence"]["evidence_id"]
            for prior in next_state["outcomes"]:
                if prior["native_evidence"]["evidence_id"] not in (conflicts or []):
                    continue
                prior["disputed"] = True
                prior["conflicts_with_evidence_ids"] = sorted(
                    set(prior["conflicts_with_evidence_ids"] + [current_evidence_id]),
                    key=lambda value: value.encode("utf-8"),
                )
                prior_without_digest = {key: value for key, value in prior.items() if key != "outcome_digest"}
                prior["outcome_digest"] = digest("outcome", prior_without_digest)
        if append_outcome:
            next_state["outcomes"].append(copy.deepcopy(outcome))
            next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        active_index = next(
            (index for index, row in enumerate(next_state["active"]) if row["occurrence"]["occurrence_id"] == event["permit"]["occurrence"]["occurrence_id"]),
            None,
        )
        if complete_disposition is not None and active_index is not None:
            active = next_state["active"].pop(active_index)
            next_state["completed"].append(
                {
                    "occurrence": copy.deepcopy(active["occurrence"]),
                    "disposition": complete_disposition,
                    "evidence_digest": digest("native-evidence", event["native_evidence"]),
                    "occurred_at": event["native_evidence"]["event_time"] or event["native_evidence"]["observed_at"],
                    "route_label": copy.deepcopy(route_label),
                    "selected_relationship_digest": relationship_digest,
                    "late": False,
                }
            )
            next_state["completed"].sort(key=lambda row: canonical_occurrence_key(row["occurrence"]))
            for deadline in next_state["deadlines"]:
                if deadline["occurrence_id"] == active["occurrence"]["occurrence_id"] and deadline["status"] == "PENDING":
                    deadline["status"] = "DISCHARGED"
            if route and instance_status is None:
                next_state["status"] = "COMPLETE"
        elif occurrence_status is not None and active_index is not None:
            next_state["active"][active_index]["status"] = occurrence_status

    details = [{"kind": "EFFECT", "classification": classification, "evidence_id": event["native_evidence"]["evidence_id"]}]
    if route:
        details.append({"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []})
    if include_label_detail:
        details.append(
            {
                "kind": "LABEL",
                "step_id": event["permit"]["occurrence"]["step_id"],
                "observed_value": copy.deepcopy(route_label),
            }
        )
    return admitted_transition(
        dispatched["state"],
        event,
        disposition=disposition,
        reason_codes=reason_codes,
        details=details,
        receipt_permit_digest=event["permit"]["permit_id"],
        mutate=mutate,
    )


def canonical_occurrence_key(value: dict[str, Any]) -> bytes:
    from corpus_common import canonical_bytes

    return canonical_bytes(value)


def no_effect_completion_authorization(
    base: dict[str, Any],
    permitted: dict[str, Any],
    dispatched: dict[str, Any],
    native_evidence: dict[str, Any],
    *,
    status: str = "ACCEPTED",
    recorded_at: str = "2026-09-10T04:30:00Z",
    expires_at: str = "2026-09-10T05:00:00Z",
    dispatch_digest: str | None = None,
) -> dict[str, Any]:
    permit = permitted["permit"]
    dispatch = (
        permit_dispatch(dispatched["state"], permit)
        if dispatch_digest is None
        else next(row for row in dispatched["state"]["dispatches"] if row["dispatch_digest"] == dispatch_digest)
    )
    native_evidence_digest = digest("native-evidence", native_evidence)
    subject_values = [
        permit["authority_result"]["specification_pin"],
        permit["work_class_digest"],
        permit["instance_id"],
        permit["occurrence"]["occurrence_id"],
        permit["permit_id"],
        dispatch["dispatch_digest"],
        native_evidence_digest,
    ]
    subject = {
        "specification_pin": permit["authority_result"]["specification_pin"],
        "work_class_digest": permit["work_class_digest"],
        "instance_id": permit["instance_id"],
        "occurrence_id": permit["occurrence"]["occurrence_id"],
        "permit_id": permit["permit_id"],
        "dispatch_digest": dispatch["dispatch_digest"],
        "native_evidence_digest": native_evidence_digest,
    }
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/evidence-record",
        "evidence_id": "completion-authorization-" + native_evidence["evidence_id"],
        "kind": "ORGANIZATIONAL_AUTHORIZATION",
        "status": status,
        "subject_digest": digest("no-effect-completion", subject),
        "organization_id": dispatched["state"]["deployment_organization_id"],
        "authorizer_id": "completion-authorizer-1",
        "authorization_scope": sorted(subject_values, key=lambda value: value.encode("utf-8")),
        "recorded_at": recorded_at,
        "expires_at": expires_at,
        "provenance_digest": digest(
            "evidence-provenance",
            {"evidence_id": "completion-authorization-" + native_evidence["evidence_id"], "purpose": "no-effect-completion"},
        ),
    }
