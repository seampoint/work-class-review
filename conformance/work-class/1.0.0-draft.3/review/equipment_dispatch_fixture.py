"""Author-derived current-dispatch carriers, independent of both consumers."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from corpus_common import digest
from lifecycle_factory import admitted_transition, state_digest
from equipment_observation_fixture import expected_ready, refresh


def retained(result, permit):
    return {**copy.deepcopy(result), "permit": copy.deepcopy(permit)}


def clock_transition(result, *, revision="2", instant="2026-09-10T04:30:01Z", status="AVAILABLE"):
    state = result["state"]
    clock = {"source": "authority-clock", "revision": revision, "status": status,
             "observed_time": instant if status == "AVAILABLE" else None,
             "evidence_digest": digest("clock-evidence", {"source": "authority-clock", "revision": revision, "status": status})}
    event = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "dispatch-clock-" + revision,
             "kind": "CLOCK", "instance_id": state["instance_id"], "expected_state_revision": state["revision"],
             "expected_state_digest": state_digest(state), "clock": clock, "activation_clocks": []}
    def mutate(next_state):
        next_state["clocks"].append(copy.deepcopy(clock))
        next_state["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))
    outcome = admitted_transition(state, event, disposition="CLOCK_RECORDED",
        reason_codes=[] if status == "AVAILABLE" else ["CLOCK_UNAVAILABLE"],
        details=[{"kind": "CLOCK", "source": clock["source"], "revision": revision, "status": status}], mutate=mutate)
    return event, retained(outcome, result["permit"])


def authorization_event(base, prior, *, event_id="gate-authorize-1", intent="intent-1", authority_input=None):
    state, permit = prior["state"], prior["permit"]
    clock = max((row for row in state["clocks"] if row["source"] == permit["clock_source"]), key=lambda row: int(row["revision"]))
    fresh = refresh(permit["authority_basis"], clock["observed_time"]) if authority_input is None else copy.deepcopy(authority_input)
    connector_body = {"id": "card-connector", "version": "version-1"}
    connector = {**connector_body, "binding_digest": digest("connector-binding", connector_body)}
    event = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "kind": "AUTHORIZE_DISPATCH", "event_id": event_id,
             "instance_id": state["instance_id"], "expected_state_revision": state["revision"], "expected_state_digest": state_digest(state),
             "permit": copy.deepcopy(permit), "native_request": copy.deepcopy(permit["native_request"]), "connector": connector,
             "authorization_fence": None, "authority_input": fresh, "dispatch_intent_id": intent,
             "observation_digests": sorted({digest("authority-observation", row) for row in fresh["observations"]}),
             "clock_revision": clock["revision"]}
    if fresh["clock"]["status"] == "AVAILABLE":
        result = expected_ready(fresh, base["authority_result"])
        fence, _ = derived_fence(base, event, result)
        event["authorization_fence"] = fence
    return event


def derived_fence(base, event, result):
    fresh, permit = event["authority_input"], event["permit"]
    step = next(row for row in fresh["work_class"]["steps"] if row["id"] == fresh["proposal"]["step"])
    gate = step["dispatch_gate"]
    ids = sorted([gate["approval_requirement"], gate["withdrawal_requirement"], *gate["policy_withdrawal_requirements"]])
    sources = []
    for requirement_id in ids:
        row = next(row for row in fresh["observations"] if row["query"].get("requirement_id") == requirement_id)
        query = row["query"]
        sources.append({"requirement_id": requirement_id, "provider": query["provider"], "source": query["source"],
                        "expected_status": query["expected_status"], "record_id": row.get("provider_record_id"),
                        "provider_revision": row["revision"], "query_digest": row["query_digest"],
                        "observation_digest": digest("authority-observation", row)})
    checked = fresh["clock"]["instant"]
    duration_end = (datetime.fromisoformat(checked.replace("Z", "+00:00")) + timedelta(seconds=int(gate["authorization_seconds"]))).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ends = [permit["expires_at"], duration_end]
    if fresh["envelope"]["temporal_validity"]["valid_until"] is not None:
        ends.append(fresh["envelope"]["temporal_validity"]["valid_until"])
    expires = min(ends)
    scope = {"instance_id": event["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
             "permit_digest": permit["permit_id"], "native_request": event["native_request"], "connector": event["connector"],
             "dispatch_intent_id": event["dispatch_intent_id"], "checked_at": checked, "expires_at": expires,
             "authority_result_digest": digest("authority-result", result), "sources": sources}
    approval = next(row for row in sources if row["requirement_id"] == gate["approval_requirement"])
    grant = next(row for row in fresh["acts"] if row["kind"] == "GRANT")
    fence = {"provider": gate["fence_provider"], "source": gate["fence_source"], "approval_id": approval["record_id"],
             "scope_digest": digest("dispatch-authorization-scope", scope), "approver_role": grant["role"],
             "signed_at": grant["occurred_at"], "provider_revision": approval["provider_revision"], "checked_at": checked,
             "status": "EFFECTIVE", "sources": sources}
    return fence, expires


def authorization_result(base, prior, event, *, refusal=None):
    result = expected_ready(event["authority_input"], base["authority_result"]) if refusal is None else copy.deepcopy(refusal)
    result_digest = digest("authority-result", result)
    permit_id = event["permit"]["permit_id"]
    disposition = "AUTHORIZED" if refusal is None else "WITHHELD"
    record = None
    if refusal is None:
        fence, expires = derived_fence(base, event, result)
        predecessors = [row for row in prior["state"].get("authorizations", []) if row["permit_digest"] == permit_id]
        referenced = {row["supersedes_authorization_digest"] for row in predecessors}
        heads = [row for row in predecessors if row["authorization_digest"] not in referenced]
        body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": permit_id,
                "native_request": copy.deepcopy(event["native_request"]), "connector": copy.deepcopy(event["connector"]),
                "authorization_fence": fence, "observation_digests": copy.deepcopy(event["observation_digests"]),
                "clock_revision": event["clock_revision"], "dispatch_intent_id": event["dispatch_intent_id"],
                "authority_input": copy.deepcopy(event["authority_input"]), "authority_result": result,
                "authority_result_digest": result_digest, "expires_at": expires,
                "supersedes_authorization_digest": heads[0]["authorization_digest"] if heads else None}
        record = {"authorization_digest": digest("dispatch-authorization", body), **body}
        details = [{"kind": "AUTHORIZATION", "authorization_digest": record["authorization_digest"], "permit_digest": permit_id,
                    "approval_id": fence["approval_id"], "checked_at": fence["checked_at"], "expires_at": expires, "sources": fence["sources"]}]
        reasons = []
    else:
        details = [{"kind": "AUTHORITY", "authority_result_digest": result_digest, "code": refusal["code"], "reasons": copy.deepcopy(refusal["reasons"]), "failed_checks": copy.deepcopy(refusal["failed_checks"])}]
        reasons = sorted({"AUTHORITY_REQUIRED", refusal["code"], *refusal["reasons"]})
    evaluation_body = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": permit_id,
        "dispatch_intent_id": event["dispatch_intent_id"], "clock_revision": event["clock_revision"],
        "authority_input": copy.deepcopy(event["authority_input"]), "authority_result": result,
        "authority_result_digest": result_digest, "authorization_digest": None if record is None else record["authorization_digest"], "disposition": disposition}
    evaluation = {"evaluation_digest": digest("dispatch-authorization-evaluation", evaluation_body), **evaluation_body}
    def mutate(state):
        if record is not None:
            state["authorizations"].append(record)
            state["authorizations"].sort(key=lambda row: row["authorization_digest"])
        state["authorization_evaluations"].append(evaluation)
        state["authorization_evaluations"].sort(key=lambda row: row["event_id"])
    return admitted_transition(prior["state"], event, disposition=disposition, reason_codes=reasons, details=details,
        receipt_permit_digest=permit_id, receipt_authority_result_digest=result_digest,
        receipt_authorization_evaluation_digest=evaluation["evaluation_digest"], mutate=mutate)
