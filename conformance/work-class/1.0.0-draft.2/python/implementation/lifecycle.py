"""Draft-2 deployment and lifecycle state construction."""

from __future__ import annotations

import copy
import datetime as dt

from . import authority, evidence as evidence_checks, reservation_v2, work_class
from .common import PIN, Refusal, canonical, digest, schema_valid, utf8_sorted_unique, valid_instant


PROFILE_ROLES = {
    "LINEAR": "LINEAR_WORK_RUNTIME",
    "CHOICE_LOOPS": "CHOICE_LOOP_RUNTIME",
    "DEADLINES": "DEADLINE_RUNTIME",
    "PARALLEL_FANOUT": "PARALLEL_FANOUT_RUNTIME",
}


def _parse(value):
    if not valid_instant(value):
        raise Refusal("CLOCK_INVALID")
    base, _, fraction = value[:-1].partition(".")
    seconds = int(dt.datetime.fromisoformat(base + "+00:00").timestamp())
    return seconds * 1_000_000_000 + (int(fraction) if fraction else 0)


def _add_seconds(value, seconds):
    base, _, fraction = value[:-1].partition(".")
    try:
        shifted = dt.datetime.fromisoformat(base + "+00:00") + dt.timedelta(seconds=seconds)
    except (OverflowError, ValueError):
        raise Refusal("LIMIT_EXCEEDED") from None
    result = shifted.strftime("%Y-%m-%dT%H:%M:%S")
    return result + (("." + fraction) if fraction else "") + "Z"


def _occurrence(pin, work_digest, instance_id, step_id, ordinal="1", predecessors=None, enclosing=None, object_key=None):
    body = {
        "specification_pin": pin,
        "work_class_digest": work_digest,
        "instance_id": instance_id,
        "step_id": step_id,
        "ordinal": ordinal,
        "predecessor_occurrence_ids": [] if predecessors is None else copy.deepcopy(predecessors),
        "enclosing": [] if enclosing is None else copy.deepcopy(enclosing),
        "object_key": copy.deepcopy(object_key),
    }
    return {"occurrence_id": digest("occurrence", body), **body}


def _deadline(definition, deadline, occurrence, trigger, activation_revision, clock, state=None):
    due_rule = deadline["due"]
    if due_rule["kind"] == "ABSOLUTE_INSTANT":
        due = due_rule["instant"]
        _parse(due)
    else:
        base = clock["observed_time"]
        if due_rule["kind"] == "ELAPSED_FROM_ANCESTOR":
            # COMPOSITION 5.1: the one completed anchor occurrence in the recursive predecessor closure.
            closure = _predecessor_closure(state, occurrence)
            anchors = [row for row in state["completed"] if row["occurrence"]["occurrence_id"] in closure and row["occurrence"]["step_id"] == due_rule["anchor_step_id"]]
            if len(anchors) != 1:
                raise Refusal("STATE_INVALID")
            base = anchors[0]["occurred_at"]
        multipliers = {"SECOND": 1, "MINUTE": 60, "HOUR": 3600, "DAY": 86400}
        try:
            due = _add_seconds(base, int(due_rule["value"]) * multipliers[due_rule["unit"]])
        except (OverflowError, ValueError):
            raise Refusal("LIMIT_EXCEEDED") from None
    body = {
        "deadline_id": deadline["id"],
        "occurrence_id": occurrence["occurrence_id"],
        "trigger_digest": trigger,
        "source": deadline["clock_source"],
        "activation_revision": activation_revision,
        "activation_clock_revision": clock["revision"],
        "activation_instant": clock["observed_time"],
        "activation_clock_evidence_digest": clock["evidence_digest"],
        "due": due,
        "boundary": deadline["boundary"],
    }
    activation_digest = digest("deadline-activation", body)
    return {
        "deadline_id": deadline["id"],
        "occurrence_id": occurrence["occurrence_id"],
        "source": deadline["clock_source"],
        "activation_revision": activation_revision,
        "activation_digest": activation_digest,
        "trigger_digest": trigger,
        "activation_clock_revision": clock["revision"],
        "activation_instant": clock["observed_time"],
        "activation_clock_evidence_digest": clock["evidence_digest"],
        "due": due,
        "boundary": deadline["boundary"],
        "status": "PENDING",
        "expiry_event_digest": None,
    }


def _due(deadline, instant):
    left, right = _parse(instant), _parse(deadline["due"])
    return left >= right if deadline["boundary"] == "AT_OR_AFTER" else left > right


def _state_projection(state):
    value = copy.deepcopy(state)
    for row in value["replays"]:
        row.pop("transaction_digest", None)
    return value


def state_digest(state):
    return digest("work-state", _state_projection(state))


def _self_digest(kind, row, field):
    value=copy.deepcopy(row); retained=value.pop(field)
    return retained == digest(kind,value)


def _predecessor_ids(occurrence_by_id, occurrence_id):
    result=set();pending=list(occurrence_by_id[occurrence_id]["predecessor_occurrence_ids"])
    while pending:
        current=pending.pop()
        if current in result or current not in occurrence_by_id: continue
        result.add(current);pending.extend(occurrence_by_id[current]["predecessor_occurrence_ids"])
    return result


def _permit_budget_integrity(permit, proposal, replay, step):
    results=replay["budget_results"]
    expected_receipts=[row["result"]["receipt_digest"] for row in results]
    if proposal["reservation_receipt_digests"]!=expected_receipts:
        return False
    if not step["shared_budgets"]:
        return not results and not permit["budget_revisions"]
    if len(results)!=1 or len(permit["budget_revisions"])!=1:
        return False
    wrapped=results[0];transition=wrapped["result"];revision=permit["budget_revisions"][0]
    if transition["status"]!="TRANSITION" or transition["receipt"]["decision"] not in {"RESERVED","RENEWED"}:
        return False
    return (
        wrapped["registry_digest"]==revision["registry_digest"]
        and wrapped["affected_anchors"]==step["shared_budgets"]==revision["affected_anchors"]
        and transition["state"]["core"]["revision"]==revision["revision"]
        and transition["receipt"]["reservation"]==revision["reservation_id"]
        and transition["receipt_digest"]==revision["receipt_digest"]
    )


def _permit_history_integrity(permit, step, occurrence_by_id, completed_by_id, permit_by_id, outcomes):
    ancestors=_predecessor_ids(occurrence_by_id,permit["occurrence"]["occurrence_id"])
    bindings={row["id"]:row for row in step["prior_effect_bindings"]}
    bases=permit["prior_effect_bases"]
    if [row["binding_id"] for row in bases]!=sorted(bindings,key=str.encode) or len(bases)!=len(bindings):
        return False
    for basis in bases:
        binding=bindings[basis["binding_id"]]
        completed=completed_by_id.get(basis["source_occurrence_id"])
        source_permit=permit_by_id.get(basis["source_permit_digest"])
        matching=[row for row in outcomes if row["kind"]=="GOVERNED" and row["classification"]=="MATCHED" and row["permit_digest"]==basis["source_permit_digest"] and digest("native-evidence",row["native_evidence"])==basis["source_native_evidence_digest"]]
        fields=[] if len(matching)!=1 else [row for row in matching[0]["native_evidence"]["actual_fields"] if row["name"]==binding["source_evidence_field"]]
        target=[row for row in permit["native_request"]["fields"] if row["name"]==binding["target_request_field"]]
        if (
            completed is None or completed["disposition"]!="SUCCEEDED" or completed["evidence_digest"]!=basis["source_native_evidence_digest"]
            or basis["source_occurrence_id"] not in ancestors or occurrence_by_id[basis["source_occurrence_id"]]["step_id"]!=binding["source_step_id"]
            or source_permit is None or source_permit["occurrence"]["occurrence_id"]!=basis["source_occurrence_id"]
            or basis["source_field"]!=binding["source_evidence_field"] or basis["target_field"]!=binding["target_request_field"]
            or len(fields)!=1 or len(target)!=1 or canonical(fields[0]["value"])!=canonical(basis["value"]) or canonical(target[0]["value"])!=canonical(basis["value"])
        ):
            return False
    separations={row["id"]:row for row in step["prior_actor_separations"]}
    bases=permit["separation_bases"]
    if [row["requirement_id"] for row in bases]!=sorted(separations,key=str.encode) or len(bases)!=len(separations):
        return False
    for basis in bases:
        requirement=separations[basis["requirement_id"]]
        prior_permits=[row for row in permit_by_id.values() if row["occurrence"]["occurrence_id"]==basis["prior_occurrence_id"]]
        if (
            basis["relation"]!="DISTINCT_ACTOR" or basis["current_occurrence_id"]!=permit["occurrence"]["occurrence_id"]
            or basis["prior_occurrence_id"] not in ancestors or occurrence_by_id[basis["prior_occurrence_id"]]["step_id"]!=requirement["prior_step_id"]
            or len(prior_permits)<1
            or basis["prior_act"]["act"]["kind"]!=requirement["prior_act_kind"] or basis["current_act"]["act"]["kind"]!=requirement["current_act_kind"]
            or basis["prior_act"]["act_digest"]!=digest("authority-act",basis["prior_act"]["act"])
            or basis["current_act"]["act_digest"]!=digest("authority-act",basis["current_act"]["act"])
            or not any(canonical(basis["prior_act"])==canonical(row) for prior in prior_permits for row in prior["authority_act_bases"])
            or not any(canonical(basis["current_act"])==canonical(row) for row in permit["authority_act_bases"])
            or basis["prior_act"]["act"]["actor"]==basis["current_act"]["act"]["actor"]
        ):
            return False
    return True


def _completed_integrity(completed, definition, outcomes, deadlines, clocks, receipts, permit_by_id):
    occurrence=completed["occurrence"];step=next((row for row in definition["steps"] if row["id"]==occurrence["step_id"]),None)
    if step is None or not valid_instant(completed["occurred_at"]) or completed["evidence_digest"] is None:
        return False
    if completed["disposition"]=="EXPIRED":
        expired=[row for row in deadlines if row["occurrence_id"]==occurrence["occurrence_id"] and row["status"]=="EXPIRED"]
        if not expired:
            return False
        expiry_events={row["expiry_event_digest"] for row in expired}
        clock_details=[detail for receipt in receipts if receipt["event_kind"]=="CLOCK" and receipt["event_digest"] in expiry_events for detail in receipt["details"] if detail["kind"]=="CLOCK"]
        if not any(clock["source"]==detail["source"] and clock["revision"]==detail["revision"] and clock["evidence_digest"]==completed["evidence_digest"] for detail in clock_details for clock in clocks):
            return False
    else:
        matches=[]
        for outcome in outcomes:
            if digest("native-evidence",outcome["native_evidence"])!=completed["evidence_digest"]:
                continue
            permit=permit_by_id.get(outcome["permit_digest"])
            if permit is not None and permit["occurrence"]["occurrence_id"]==occurrence["occurrence_id"]:
                matches.append(outcome)
        if len(matches)!=1:
            return False
    if completed["selected_relationship_digest"] is not None:
        relationships=[row for row in definition["relationships"] if digest("relationship",row)==completed["selected_relationship_digest"]]
        if len(relationships)!=1 or relationships[0]["from"]!=step["id"]:
            return False
        expected={"SUCCEEDED":{"SEQUENCE","LABEL"},"FAILED":{"FAILURE"},"NO_EFFECT":{"FAILURE"},"EXPIRED":{"EXPIRY"}}[completed["disposition"]]
        if relationships[0]["kind"] not in expected:
            return False
        if relationships[0]["kind"]=="LABEL" and canonical(relationships[0]["label"])!=canonical(completed["route_label"]):
            return False
    if completed["late"] and completed["selected_relationship_digest"] is not None:
        return False
    return True


def _deployment_integrity(state,definition):
    authorization=state["deployment_authorization"]
    evidence=state["deployment_authorization_evidence"]
    clock=state["deployment_authorization_clock"]
    subject=copy.deepcopy(authorization);subject.pop("authorization_evidence_digest")
    subject_digest=digest("deployment-authorization-subject",subject)
    evidence_digest=digest("evidence",evidence)
    if (
        state["deployment_authorization_subject_digest"]!=subject_digest
        or state["deployment_authorization_digest"]!=digest("deployment-authorization",authorization)
        or state["deployment_authorization_evidence_digest"]!=evidence_digest
        or authorization["authorization_evidence_digest"]!=evidence_digest
        or evidence["subject_digest"]!=subject_digest
        or authorization["specification_pin"]!=state["specification_pin"]
        or authorization["work_class_digest"]!=state["work_class_digest"]
        or authorization["profile"]!=state["profile"]
        or authorization["role"]!=state["role"]
        or authorization["instance_id"]!=state["instance_id"]
        or authorization["organization_id"]!=state["deployment_organization_id"]
        or evidence["organization_id"]!=state["deployment_organization_id"]
        or authorization["status"]!="AUTHORIZED"
        or evidence["status"]!="ACCEPTED"
        or clock["status"]!="AVAILABLE"
        or not valid_instant(clock["observed_time"])
    ):
        return False
    for name in ("correspondence","source_confirmation","policy_decision"):
        review_digest=digest("evidence",state[f"deployment_{name}_evidence"])
        if state[f"deployment_{name}_evidence_digest"]!=review_digest or authorization[f"{name}_evidence_digest"]!=review_digest:
            return False
    records={name:state[f"deployment_{name}_evidence"] for name in ("correspondence","source_confirmation","policy_decision")}
    try:
        # LIFE-003: restart recomputes every digest, time relation and binding of the three review records.
        _deployment_review_evidence(definition,state["work_class_digest"],state["profile"],state["role"],evidence,records,_parse(clock["observed_time"]))
    except (Refusal,KeyError,TypeError,ValueError):
        return False
    expected_scope=sorted([state["specification_pin"],state["work_class_digest"],state["profile"],state["role"],state["instance_id"]],key=str.encode)
    if evidence["authorization_scope"]!=expected_scope:
        return False
    root=next((row for row in state["active"] if row["occurrence"]["step_id"]==definition["root"] and row["occurrence"]["ordinal"]=="1" and not row["occurrence"]["predecessor_occurrence_ids"] and not row["occurrence"]["enclosing"] and row["occurrence"]["object_key"] is None),None)
    if root is not None:
        activation=digest("deployment-activation",{"deployment_authorization_digest":state["deployment_authorization_digest"],"instance_id":state["instance_id"],"occurrence_id":root["occurrence"]["occurrence_id"]})
        if root["activation_event_digest"]!=activation:
            return False
    try:
        now=_parse(clock["observed_time"])
        if _parse(authorization["authorized_at"])>now or authorization["expires_at"] is not None and now>=_parse(authorization["expires_at"]):
            return False
        if _parse(evidence["recorded_at"])>now or evidence["expires_at"] is None or now>=_parse(evidence["expires_at"]):
            return False
    except (TypeError,ValueError):
        return False
    return True


def _decision_integrity(receipt,replay,state):
    if receipt["instance_id"]!=state["instance_id"]:
        return False
    details={row["kind"]:row for row in receipt["details"]}
    kinds=[row["kind"] for row in receipt["details"]]
    event_kind=receipt["event_kind"];disposition=receipt["disposition"]
    if event_kind=="PROPOSE" and receipt["permit_digest"] is None and replay["permit"] is not None:
        return False
    if event_kind=="PROPOSE" and receipt["permit_digest"] is not None and (replay["permit"] is None or replay["permit"]["permit_id"]!=receipt["permit_digest"]):
        return False
    if event_kind!="PROPOSE" and replay["permit"] is not None:
        return False
    budget_details=[row for row in receipt["details"] if row["kind"]=="BUDGET"]
    budget_results=replay["budget_results"]
    if len(budget_results)>1 or len(budget_details)>1:
        return False
    if budget_results:
        result=budget_results[0]
        budget_detail=budget_details[0] if budget_details else None
        if budget_detail is None:
            if not (event_kind=="PROPOSE" and disposition=="PERMITTED"):
                return False
        elif (
            budget_detail["registry_digest"]!=result["registry_digest"]
            or budget_detail["receipt_digest"]!=result["result"]["receipt_digest"]
            or budget_detail["reasons"]!=result["result"]["receipt"]["reasons"]
        ):
            return False
    elif budget_details:
        return False
    if event_kind=="PROPOSE":
        if disposition=="PERMITTED":
            return kinds==[] and receipt["reason_codes"]==[] and receipt["permit_digest"] is not None and receipt["authority_result_digest"] is not None
        if disposition=="STOPPED":
            return kinds==["LIMIT"] and receipt["reason_codes"]==["LIMIT_EXCEEDED"] and details["LIMIT"]["limit_kind"]=="ACTUATIONS" and receipt["permit_digest"] is None and receipt["authority_result_digest"] is not None
        if disposition!="WITHHELD" or len(kinds)!=1 or receipt["permit_digest"] is not None or receipt["authority_result_digest"] is None:
            return False
        if kinds==["AUTHORITY"]:
            expected=sorted(set(["AUTHORITY_REQUIRED",details["AUTHORITY"]["code"],*details["AUTHORITY"]["reasons"]]),key=str.encode)
            return receipt["reason_codes"]==expected and details["AUTHORITY"]["authority_result_digest"]==receipt["authority_result_digest"]
        if kinds==["SEPARATION"]:
            separation=details["SEPARATION"]
            basis=separation["basis"]
            proposal=next((row for row in state["proposals"] if row["event_id"]==receipt["event_id"]),None)
            current=basis["current_act"]
            prior=basis["prior_act"]
            occurrences={row["occurrence"]["occurrence_id"]:row["occurrence"] for row in state["active"]+state["completed"]}
            current_occurrence=occurrences.get(basis["current_occurrence_id"])
            prior_occurrence=occurrences.get(basis["prior_occurrence_id"])
            prior_permits=[row for row in state["permits"] if row["occurrence"]["occurrence_id"]==basis["prior_occurrence_id"]]
            return (
                receipt["reason_codes"]==["SEPARATION_VIOLATED"]
                and digest("authority-result",separation["authority_result"])==receipt["authority_result_digest"]
                and basis["relation"]=="DISTINCT_ACTOR"
                and proposal is not None
                and proposal["occurrence_id"]==basis["current_occurrence_id"]
                and current_occurrence is not None
                and prior_occurrence is not None
                and basis["prior_occurrence_id"] in _predecessor_ids(occurrences,basis["current_occurrence_id"])
                and current["act_digest"]==digest("authority-act",current["act"])
                and prior["act_digest"]==digest("authority-act",prior["act"])
                and current["act_digest"] in separation["authority_result"]["act_digests"]
                and any(canonical(prior)==canonical(row) for permit in prior_permits for row in permit["authority_act_bases"])
                and current["act"]["actor"]==prior["act"]["actor"]
            )
        if kinds==["BUDGET"]:
            expected=sorted(set(["BUDGET_WITHHELD",*details["BUDGET"]["reasons"]]),key=str.encode)
            return receipt["reason_codes"]==expected
        return False
    if receipt["authority_result_digest"] is not None:
        return False
    if event_kind=="DISPATCH_OBSERVED":
        if kinds!=["DISPATCH"] or budget_results or receipt["reservation_receipt_digests"]:
            return False
        rows=[row for row in state["dispatches"] if row["event_id"]==receipt["event_id"]]
        if len(rows)!=1 or rows[0]["event_digest"]!=receipt["event_digest"] or rows[0]["attempt"]["attempt_id"]!=details["DISPATCH"]["attempt_id"] or rows[0]["permit_digest"]!=receipt["permit_digest"]:
            return False
        dispatch=rows[0];base_disposition,base_reasons=_dispatch_base(dispatch["attempt"],dispatch["acknowledgement"])
        disqualifiers={"NATIVE_ARGUMENT_MISMATCH","PERMIT_EXPIRED","PERMIT_SUPERSEDED","LATE_OR_PROHIBITED_DISPATCH"}
        reasons=details["DISPATCH"]["reasons"]
        if receipt["reason_codes"]!=reasons or not set(base_reasons).issubset(reasons) or not set(reasons).issubset(set(base_reasons)|disqualifiers):
            return False
        if set(reasons)&disqualifiers:
            expected="DISPATCH_REFUSED" if dispatch["attempt"]["status"]=="NOT_SENT" and dispatch["acknowledgement"]["status"]!="ACCEPTED" else "DISPUTED"
        else:
            expected=base_disposition
        return disposition==expected
    if event_kind=="CLOCK":
        if receipt["permit_digest"] is not None or not kinds or kinds[0]!="CLOCK" or any(kind not in {"CLOCK","DEADLINE","ROUTE","LIMIT"} for kind in kinds):
            return False
        clock=details["CLOCK"]
        retained=[row for row in state["clocks"] if row["source"]==clock["source"] and row["revision"]==clock["revision"]]
        if len(retained)!=1 or retained[0]["status"]!=clock["status"]:
            return False
        expired={row["deadline_id"] for row in state["deadlines"] if row["expiry_event_digest"]==receipt["event_digest"]}
        if clock["status"]!="AVAILABLE":
            return kinds==["CLOCK"] and disposition=="CLOCK_RECORDED" and receipt["reason_codes"]==["CLOCK_UNAVAILABLE"] and not expired
        if disposition=="CLOCK_RECORDED":
            return kinds==["CLOCK"] and receipt["reason_codes"]==[] and not expired
        if disposition not in {"EXPIRED","STOPPED"} or "DEADLINE" not in details or not expired.issubset(set(details["DEADLINE"]["deadline_ids"])):
            return False
        if disposition=="EXPIRED":
            return receipt["reason_codes"]==[] and details["DEADLINE"]["reasons"]==[] and "LIMIT" not in details
        expected=set(details["DEADLINE"]["reasons"])
        if "LIMIT" in details: expected.add("LIMIT_EXCEEDED")
        return set(receipt["reason_codes"])==expected
    if event_kind!="EFFECT_OBSERVED" or "EFFECT" not in kinds or any(kind not in {"EFFECT","BUDGET","DEADLINE","ROUTE","LABEL","LIMIT"} for kind in kinds):
        return False
    effect=details["EFFECT"];classification=effect["classification"]
    outcomes=[row for row in state["outcomes"] if row["native_evidence"]["evidence_id"]==effect["evidence_id"]]
    if not outcomes or classification!="DUPLICATE" and not any(row["classification"]==classification and row["event_digest"]==receipt["event_digest"] for row in outcomes):
        return False
    governed=[row for row in outcomes if row["kind"]=="GOVERNED"]
    if governed and receipt["permit_digest"]!=governed[0]["permit_digest"] or not governed and receipt["permit_digest"] is not None:
        return False
    base={"UNKNOWN":{"UNKNOWN_OUTCOME"},"NO_EFFECT_ESTABLISHED":{"NO_EFFECT_ESTABLISHED"},"UNEXPECTED":{"UNEXPECTED_EFFECT"},"CONFLICTING":{"CONFLICTING_EFFECT"},"FOREIGN":{"FOREIGN_EFFECT"},"LATE_MATCHED":{"LATE_EFFECT"},"LATE_AFTER_RELEASE":{"LATE_EFFECT_AFTER_RELEASE"},"DUPLICATE":{"DUPLICATE_EVIDENCE"}}.get(classification,set())
    reasons=set(receipt["reason_codes"])
    if classification=="DUPLICATE":
        return disposition=="OUTCOME_RETAINED" and reasons==base
    budget_disputed=False
    if budget_results:
        budget_receipt=budget_results[0]["result"]["receipt"]
        budget_disputed=budget_receipt["decision"]=="EFFECT_DISPUTED"
        if budget_disputed:
            base|={"BUDGET_EFFECT_DISPUTED",*budget_receipt["reasons"]}
    if not base.issubset(reasons):
        return False
    allowed=base|{"DEPENDENCY_DISPUTED","DECLARED_FAILURE","LABEL_INVALID","LOOP_BOUND_REACHED","FANOUT_SET_DUPLICATE","FANOUT_EMPTY","LIMIT_EXCEEDED","ACTIVATION_CLOCK_UNAVAILABLE","DEADLINE_ALREADY_DUE","DEADLINE_TIME_OVERFLOW"}
    if not reasons.issubset(allowed):
        return False
    if "LIMIT_EXCEEDED" in reasons and "LIMIT" not in details or any(reason in reasons for reason in {"ACTIVATION_CLOCK_UNAVAILABLE","DEADLINE_ALREADY_DUE","DEADLINE_TIME_OVERFLOW"}) and "DEADLINE" not in details:
        return False
    if budget_disputed:
        return disposition=="DISPUTED"
    if classification in {"FOREIGN","UNEXPECTED","CONFLICTING","LATE_AFTER_RELEASE"}:
        return disposition=="DISPUTED"
    if classification in {"UNKNOWN","LATE_MATCHED"}:
        return disposition=="OUTCOME_RETAINED"
    if classification=="MATCHED":
        return disposition in {"COMPLETED","STOPPED","OUTCOME_RETAINED"}
    if classification in {"FAILED","NO_EFFECT_ESTABLISHED"}:
        return disposition in {"FAILED","STOPPED","OUTCOME_RETAINED"}
    return False


def _validate_state_integrity(state, definition):
    if not _deployment_integrity(state,definition):
        return False
    if int(state["revision"]) != len(state["receipts"]) or len(state["receipts"]) != len(state["replays"]):
        return False
    if [row["sequence"] for row in state["receipts"]] != [str(index) for index in range(1,len(state["receipts"])+1)]:
        return False
    if [row["event_id"] for row in state["replays"]] != sorted([row["event_id"] for row in state["replays"]],key=str.encode):
        return False
    receipts={row["event_id"]:row for row in state["receipts"]}
    replays={row["event_id"]:row for row in state["replays"]}
    if len(receipts)!=len(state["receipts"]) or len(replays)!=len(state["replays"]): return False
    if sum(row["event_kind"]=="PROPOSE" for row in state["receipts"])>int(definition["limits"]["maximum_proposals"]): return False
    for replay in state["replays"]:
        receipt=receipts.get(replay["event_id"])
        if receipt is None or replay["event_digest"]!=receipt["event_digest"] or replay["decision_receipt_digest"]!=receipt["decision_id"] or canonical(replay["decision"])!=canonical(receipt): return False
        detail_order={name:index for index,name in enumerate(["AUTHORITY","SEPARATION","BUDGET","DISPATCH","EFFECT","CLOCK","DEADLINE","ROUTE","LABEL","LIMIT"])}
        kinds=[detail["kind"] for detail in receipt["details"]]
        if kinds!=sorted(set(kinds),key=lambda value:detail_order[value]) or receipt["reason_codes"]!=sorted(set(receipt["reason_codes"]),key=str.encode): return False
        receipt_body=copy.deepcopy(receipt);del receipt_body["decision_id"]
        if receipt["decision_id"]!=digest("decision-receipt",receipt_body): return False
        expected=digest("lifecycle-transaction",{"state_before_digest":receipt["state_before_digest"],"event_digest":replay["event_digest"],"decision_receipt_digest":replay["decision_receipt_digest"],"state_after_core_digest":replay["transition_state_digest"],"budget_results":replay["budget_results"]})
        if replay["transaction_digest"]!=expected: return False
        budget_receipts=[row["result"]["receipt_digest"] for row in replay["budget_results"]]
        if receipt["reservation_receipt_digests"] != budget_receipts: return False
        if not _decision_integrity(receipt,replay,state): return False
    if state["receipts"]:
        core=copy.deepcopy(state);core["receipts"]=[];core["replays"]=[]
        if state["receipts"][-1]["state_after_core_digest"]!=digest("work-state-core",core): return False
    collections=[
        ([canonical(row["occurrence"]) for row in state["active"]],lambda values:sorted(values)),
        ([canonical(row["occurrence"]) for row in state["completed"]],lambda values:sorted(values)),
        ([row["obligation_id"] for row in state["obligations"]],lambda values:sorted(values,key=str.encode)),
        ([row["event_id"] for row in state["proposals"]],lambda values:sorted(values,key=str.encode)),
        ([row["permit_id"] for row in state["permits"]],lambda values:sorted(values,key=str.encode)),
        ([row["dispatch_digest"] for row in state["dispatches"]],lambda values:sorted(values,key=str.encode)),
        ([row["outcome_digest"] for row in state["outcomes"]],lambda values:sorted(values,key=str.encode)),
    ]
    if any(values!=sorter(values) or len(values)!=len(set(values)) for values,sorter in collections): return False
    active_ids={row["occurrence"]["occurrence_id"] for row in state["active"]};completed_ids={row["occurrence"]["occurrence_id"] for row in state["completed"]}
    if active_ids & completed_ids: return False
    all_occurrences=[row["occurrence"] for row in state["active"]]+[row["occurrence"] for row in state["completed"]]
    for occurrence in all_occurrences:
        body=copy.deepcopy(occurrence);retained=body.pop("occurrence_id")
        if retained!=digest("occurrence",body) or occurrence["specification_pin"]!=PIN or occurrence["work_class_digest"]!=state["work_class_digest"] or occurrence["instance_id"]!=state["instance_id"]: return False
        if occurrence["predecessor_occurrence_ids"] != sorted(set(occurrence["predecessor_occurrence_ids"]),key=str.encode): return False
        if any(value not in {row["occurrence_id"] for row in all_occurrences} for value in occurrence["predecessor_occurrence_ids"]): return False
    if any(not _self_digest("permit",row,"permit_id") for row in state["permits"]): return False
    if any(not _self_digest("dispatch",row,"dispatch_digest") for row in state["dispatches"]): return False
    if any(not _self_digest("outcome",row,"outcome_digest") for row in state["outcomes"]): return False
    occurrence_by_id={row["occurrence_id"]:row for row in all_occurrences}
    completed_by_id={row["occurrence"]["occurrence_id"]:row for row in state["completed"]}
    proposal_by_digest={row["proposal_digest"]:row for row in state["proposals"]}
    permit_by_id={row["permit_id"]:row for row in state["permits"]}
    dispatch_by_id={row["dispatch_digest"]:row for row in state["dispatches"]}
    if len(proposal_by_digest)!=len(state["proposals"]): return False
    for proposal in state["proposals"]:
        receipt=receipts.get(proposal["event_id"]);replay=replays.get(proposal["event_id"])
        if receipt is None or replay is None or receipt["event_kind"]!="PROPOSE" or proposal["event_digest"]!=receipt["event_digest"]: return False
        if proposal["authority_result_digest"]!=receipt["authority_result_digest"] or proposal["reservation_receipt_digests"]!=receipt["reservation_receipt_digests"]: return False
        if proposal["disposition"]!=receipt["disposition"] or proposal["occurrence_id"] not in {row["occurrence_id"] for row in all_occurrences}: return False
        if proposal["proposal_digest"]==proposal["event_digest"] or proposal["prior_permit_digest"] is not None and proposal["prior_permit_digest"] not in permit_by_id: return False
        if proposal["disposition"]=="PERMITTED":
            permit=permit_by_id.get(proposal["permit_digest"])
            if permit is None or receipt["permit_digest"]!=permit["permit_id"] or canonical(replay["permit"])!=canonical(permit): return False
            step=next(row for row in definition["steps"] if row["id"]==permit["occurrence"]["step_id"])
            if not _permit_budget_integrity(permit,proposal,replay,step): return False
        elif proposal["permit_digest"] is not None or receipt["permit_digest"] is not None or replay["permit"] is not None: return False
    successors={}
    roots={}
    for permit in state["permits"]:
        proposal=proposal_by_digest.get(permit["proposal_digest"])
        if proposal is None or proposal["permit_digest"]!=permit["permit_id"] or permit["instance_id"]!=state["instance_id"] or permit["work_class_digest"]!=state["work_class_digest"] or permit["profile"]!=state["profile"] or permit["role"]!=state["role"]: return False
        if permit["occurrence"]["occurrence_id"]!=proposal["occurrence_id"] or permit["occurrence"]["occurrence_id"] not in {row["occurrence_id"] for row in all_occurrences}: return False
        step=next((row for row in definition["steps"] if row["id"]==permit["occurrence"]["step_id"]),None)
        fields=[] if step is None else step["fields"]
        if step is None or permit["native_request"]["operation"]!=step["operation"] or permit["native_request"]["interface"]!=step["interface"] or [row["name"] for row in permit["native_request"]["fields"]]!=[row["name"] for row in fields]: return False
        if permit["authority_result_digest"]!=digest("authority-result",permit["authority_result"]) or permit["authority_evidence_digest"]!=permit["authority_result"]["evidence_digest"]: return False
        if permit["authority_act_bases"] != sorted(permit["authority_act_bases"],key=lambda row:row["act_digest"].encode("utf-8")) or any(row["act_digest"]!=digest("authority-act",row["act"]) for row in permit["authority_act_bases"]): return False
        if [row["act_digest"] for row in permit["authority_act_bases"]] != permit["authority_result"]["act_digests"]: return False
        if permit["credential_ids"]!=sorted(set(permit["credential_ids"]),key=str.encode) or permit["observation_digests"]!=sorted(set(permit["observation_digests"]),key=str.encode): return False
        if not _permit_history_integrity(permit,step,occurrence_by_id,completed_by_id,permit_by_id,state["outcomes"]): return False
        clocks=[row for row in state["clocks"] if row["source"]==permit["clock_source"] and row["revision"]==permit["clock_revision"] and row["status"]=="AVAILABLE"]
        if len(clocks)!=1 or _parse(permit["expires_at"])<=_parse(clocks[0]["observed_time"]): return False
        prior=permit["supersedes_permit_digest"]
        if prior is None:
            roots.setdefault(permit["occurrence"]["occurrence_id"],[]).append(permit["permit_id"])
        else:
            old=permit_by_id.get(prior)
            if old is None or old["occurrence"]["occurrence_id"]!=permit["occurrence"]["occurrence_id"] or prior in successors: return False
            successors[prior]=permit["permit_id"]
    if any(len(values)!=1 for values in roots.values()): return False
    for occurrence_id in {row["occurrence"]["occurrence_id"] for row in state["permits"]}:
        roots_for_occurrence=roots.get(occurrence_id,[])
        if len(roots_for_occurrence)!=1: return False
        seen=set();current=roots_for_occurrence[0]
        while current is not None:
            if current in seen: return False
            seen.add(current);current=successors.get(current)
        if seen!={row["permit_id"] for row in state["permits"] if row["occurrence"]["occurrence_id"]==occurrence_id}: return False
        active=next((row for row in state["active"] if row["occurrence"]["occurrence_id"]==occurrence_id),None)
        heads=[row["permit_id"] for row in state["permits"] if row["occurrence"]["occurrence_id"]==occurrence_id and row["permit_id"] not in successors]
        if active is not None and active["status"]=="PERMITTED" and len(heads)!=1: return False
    for dispatch in state["dispatches"]:
        permit=permit_by_id.get(dispatch["permit_digest"]);receipt=receipts.get(dispatch["event_id"])
        expected_attempt=digest("dispatch-attempt",{"permit_id":dispatch["permit_digest"],"native_request":dispatch["native_request"],"connector":dispatch["connector"],"attempt":dispatch["attempt"]})
        if permit is None or receipt is None or receipt["event_kind"]!="DISPATCH_OBSERVED" or receipt["event_digest"]!=dispatch["event_digest"] or expected_attempt!=dispatch["dispatch_attempt_digest"] or dispatch["permit_digest"] in successors: return False
    evidence_ids={row["native_evidence"]["evidence_id"] for row in state["outcomes"]}
    if len(evidence_ids)!=len(state["outcomes"]): return False
    for outcome in state["outcomes"]:
        receipt=receipts.get(outcome["event_id"])
        if receipt is None or receipt["event_kind"]!="EFFECT_OBSERVED" or receipt["event_digest"]!=outcome["event_digest"]: return False
        if outcome["conflicts_with_evidence_ids"]!=sorted(set(outcome["conflicts_with_evidence_ids"]),key=str.encode) or any(value not in evidence_ids for value in outcome["conflicts_with_evidence_ids"]): return False
        if bool(outcome["conflicts_with_evidence_ids"]) and not outcome["disputed"] or outcome["classification"]=="MATCHED" and not outcome["disputed"] and outcome["conflicts_with_evidence_ids"]: return False
        for conflict_id in outcome["conflicts_with_evidence_ids"]:
            other=next(row for row in state["outcomes"] if row["native_evidence"]["evidence_id"]==conflict_id)
            if outcome["native_evidence"]["evidence_id"] not in other["conflicts_with_evidence_ids"]: return False
        if outcome["kind"]=="GOVERNED":
            permit=permit_by_id.get(outcome["permit_digest"]);dispatch=dispatch_by_id.get(outcome["dispatch_digest"])
            if permit is None or dispatch is None or dispatch["permit_digest"]!=permit["permit_id"] or outcome["dispatch_attempt_digest"]!=dispatch["dispatch_attempt_digest"]: return False
        elif outcome["permit_digest"] is not None or outcome["dispatch_digest"] is not None or outcome["dispatch_attempt_digest"] is not None: return False
    if any(not _completed_integrity(row,definition,state["outcomes"],state["deadlines"],state["clocks"],state["receipts"],permit_by_id) for row in state["completed"]): return False
    if [row["step_id"] for row in state["step_counters"]] != sorted([step["id"] for step in definition["steps"] if step["kind"] in work_class.PROPOSAL],key=str.encode): return False
    for counter in state["step_counters"]:
        occurrences=sum(row["step_id"]==counter["step_id"] for row in all_occurrences)
        actuations=sum(row["occurrence_id"] in {item["occurrence_id"] for item in all_occurrences} and row["disposition"]=="PERMITTED" and row["prior_permit_digest"] is None for row in state["proposals"])
        if int(counter["activations"])!=occurrences:
            return False
        step_occurrence_ids={row["occurrence_id"] for row in all_occurrences if row["step_id"]==counter["step_id"]}
        actuations=sum(row["occurrence_id"] in step_occurrence_ids and row["disposition"]=="PERMITTED" and row["prior_permit_digest"] is None for row in state["proposals"])
        if int(counter["actuations"])!=actuations: return False
    if int(state["total_activations"])!=sum(int(row["activations"]) for row in state["step_counters"]) or int(state["total_actuations"])!=sum(int(row["actuations"]) for row in state["step_counters"]): return False
    clock_keys=[(row["source"],int(row["revision"])) for row in state["clocks"]]
    if clock_keys != sorted(clock_keys,key=lambda value:(value[0].encode("utf-8"),value[1])) or len(clock_keys)!=len(set(clock_keys)): return False
    available_by_source={}
    for row in state["clocks"]:
        if row["status"]=="AVAILABLE":
            if not valid_instant(row["observed_time"]) or row["source"] in available_by_source and _parse(row["observed_time"])<available_by_source[row["source"]]: return False
            available_by_source[row["source"]]=_parse(row["observed_time"])
    deadline_defs={row["id"]:row for row in definition["deadlines"]}
    deadline_keys=[]
    for row in state["deadlines"]:
        occurrence=occurrence_by_id.get(row["occurrence_id"]);declared=deadline_defs.get(row["deadline_id"])
        if occurrence is None or declared is None or declared["step_id"]!=occurrence["step_id"] or row["source"]!=declared["clock_source"] or row["boundary"]!=declared["boundary"]: return False
        clock_rows=[clock for clock in state["clocks"] if clock["source"]==row["source"] and clock["revision"]==row["activation_clock_revision"] and clock["status"]=="AVAILABLE"]
        if len(clock_rows)!=1: return False
        try: expected=_deadline(definition,declared,occurrence,row["trigger_digest"],row["activation_revision"],clock_rows[0],state)
        except (Refusal,ValueError,OverflowError): return False
        if any(canonical(row[key])!=canonical(expected[key]) for key in expected if key not in {"status","expiry_event_digest"}): return False
        if row["status"]=="PENDING" and (row["expiry_event_digest"] is not None or row["occurrence_id"] not in active_ids): return False
        if row["status"]=="EXPIRED" and row["expiry_event_digest"] is None: return False
        if row["status"]=="DISCHARGED" and (row["expiry_event_digest"] is not None or row["occurrence_id"] not in completed_ids): return False
        deadline_keys.append((row["due"],canonical(occurrence),row["deadline_id"].encode("utf-8")))
    if deadline_keys!=sorted(deadline_keys) or len({(row["deadline_id"],row["occurrence_id"]) for row in state["deadlines"]})!=len(state["deadlines"]): return False
    for active in state["active"]:
        expected_ids=sorted([row["id"] for row in definition["deadlines"] if row["step_id"]==active["occurrence"]["step_id"]],key=str.encode)
        if active["deadline_ids"]!=expected_ids or any(not any(deadline["deadline_id"]==value and deadline["occurrence_id"]==active["occurrence"]["occurrence_id"] for deadline in state["deadlines"]) for value in expected_ids): return False
    obligation_ids={row["obligation_id"] for row in state["obligations"]}
    waiting_references=[]
    for row in state["obligations"]:
        identity={key:copy.deepcopy(row[key]) for key in ("kind","construct_id","pass","source_occurrence_ids","branch_id","object_key","join_step_id")}
        if row["obligation_id"]!=digest("obligation",identity) or row["source_occurrence_ids"]!=sorted(set(row["source_occurrence_ids"]),key=str.encode): return False
        if any(value not in occurrence_by_id for value in row["source_occurrence_ids"]): return False
        # COMPOSITION: the branch or object head copies the structural frontier that its obligation records as
        # source_occurrence_ids, and both are immutable. An onward route moves the expected occurrence, not the
        # head, so the equality is checked against the head occurrence.
        if row["kind"]=="PARALLEL_BRANCH":
            block=next((item for item in definition["parallel_blocks"] if item["id"]==row["construct_id"]),{})
            head=next((branch["head_step_id"] for branch in block.get("branches",[]) if branch["id"]==row["branch_id"]),None);segment_kind="BRANCH"
        else:
            head=next((item["region_head_step_id"] for item in definition["fanouts"] if item["id"]==row["construct_id"]),None);segment_kind="FANOUT"
        if not any(occurrence["step_id"]==head and occurrence["predecessor_occurrence_ids"]==row["source_occurrence_ids"] and any(segment["kind"]==segment_kind and segment["construct_id"]==row["construct_id"] and segment["pass"]==row["pass"] and segment["branch_id"]==row["branch_id"] and canonical(segment["object_key"])==canonical(row["object_key"]) for segment in occurrence["enclosing"]) for occurrence in all_occurrences): return False
        if row["status"] in {"OPEN","BLOCKED"}:
            active=next((item for item in state["active"] if item["occurrence"]["occurrence_id"]==row["expected_occurrence_id"]),None)
            if active is None or (row["status"]=="BLOCKED")!=(active["status"]=="BLOCKED_DISPUTE") or row["waiting_on"] is not None or row["completion_basis"] is not None: return False
            owner=next((segment for segment in reversed(active["occurrence"]["enclosing"]) if segment["kind"] in {"BRANCH","FANOUT"}),None)
            if owner is None or owner["kind"]!=segment_kind or owner["construct_id"]!=row["construct_id"] or owner["pass"]!=row["pass"] or owner["branch_id"]!=row["branch_id"] or canonical(owner["object_key"])!=canonical(row["object_key"]): return False
        elif row["status"] in {"DISCHARGED","JOINED"} and (row["expected_occurrence_id"] is not None or row["waiting_on"] is not None or row["completion_basis"] is None): return False
        elif row["status"]=="WAITING" and (row["expected_occurrence_id"] is not None or row["waiting_on"] is None or row["completion_basis"] is not None): return False
        elif row["status"]=="DISPUTED" and (row["expected_occurrence_id"] is not None or (row["waiting_on"] is None)==(row["completion_basis"] is None)): return False
        if row["waiting_on"] is not None:
            child=row["waiting_on"]
            children=[item for item in state["obligations"] if item["obligation_id"] in child["obligation_ids"]]
            if child["obligation_ids"]!=sorted(set(child["obligation_ids"]),key=str.encode) or len(children)!=len(child["obligation_ids"]): return False
            expected_kind="PARALLEL_BRANCH" if child["kind"]=="PARALLEL" else "FANOUT_OBJECT"
            siblings=[item for item in state["obligations"] if item["kind"]==expected_kind and item["construct_id"]==child["construct_id"] and item["pass"]==child["pass"] and canonical(_obligation_outer(state,item))==canonical(child["outer_enclosing"])]
            if set(child["obligation_ids"])!={item["obligation_id"] for item in siblings}: return False
            if row["status"]=="WAITING" and all(item["status"]=="JOINED" for item in children): return False
            if row["status"]=="DISPUTED" and not any(item["status"]=="DISPUTED" for item in children): return False
            waiting_references.append((row["obligation_id"],canonical(child),child["obligation_ids"]))
        if row["completion_basis"] is not None:
            basis=row["completion_basis"]
            if basis["kind"]=="DIRECT_EVENT":
                occurrence=occurrence_by_id.get(basis["occurrence_id"])
                step=next((item for item in definition["steps"] if occurrence is not None and item["id"]==occurrence["step_id"]),None)
                if step is None or basis["operation"]!=step["operation"] or not any(receipt["event_digest"]==basis["event_digest"] for receipt in state["receipts"]): return False
            else:
                child=basis["child_pass"]
                if child["obligation_ids"]!=sorted(set(child["obligation_ids"]),key=str.encode) or any(value not in obligation_ids for value in child["obligation_ids"]): return False
                try: _completion_frontier(state,row)
                except Refusal: return False
    if len({reference for _,reference,_ in waiting_references})!=len(waiting_references): return False
    waiting_graph={owner:list(children) for owner,_,children in waiting_references}
    def waiting_acyclic(owner,path):
        if owner in path: return False
        return all(waiting_acyclic(child,path|{owner}) for child in waiting_graph.get(owner,[]))
    if any(not waiting_acyclic(owner,set()) for owner in waiting_graph): return False
    pass_groups={}
    for row in state["obligations"]: pass_groups.setdefault((row["kind"],row["construct_id"],row["pass"],canonical(_obligation_outer(state,row))),[]).append(row)
    if state["status"]=="ACTIVE" and any(rows and all(row["status"]=="DISCHARGED" for row in rows) for rows in pass_groups.values()): return False
    disputed_permits={row["permit_digest"] for row in state["outcomes"] if row["kind"]=="GOVERNED" and row["disputed"] and row["native_evidence"]["status"] in {"EFFECT_ESTABLISHED","NO_EFFECT_ESTABLISHED"}}
    disputed_roots={permit_by_id[permit_id]["occurrence"]["occurrence_id"] for permit_id in disputed_permits if permit_id in permit_by_id} & completed_ids
    dependency_affected=set(disputed_roots);changed=True
    while changed:
        changed=False
        for occurrence in all_occurrences:
            if occurrence["occurrence_id"] not in dependency_affected and set(occurrence["predecessor_occurrence_ids"]) & dependency_affected:
                dependency_affected.add(occurrence["occurrence_id"]);changed=True
    for row in state["obligations"]:
        if row["status"]=="DISPUTED" and row["completion_basis"] is not None:
            try: frontier=_completion_frontier(state,{**row,"status":"DISCHARGED"})
            except Refusal: return False
            if not set(frontier)&dependency_affected: return False
    pass_keys=[]
    fanouts={row["id"]:row for row in definition["fanouts"]}
    for row in state["fanout_passes"]:
        fanout=fanouts.get(row["fanout_id"]);expand=occurrence_by_id.get(row["expand_occurrence_id"])
        if fanout is None or expand is None or expand["step_id"]!=fanout["expand_step_id"]: return False
        duplicate_keys=len(row["object_keys"])!=len({canonical(value) for value in row["object_keys"]})
        if duplicate_keys:
            if state["status"]!="STOPPED" or row["obligation_ids"] or row["joined"] or not any(receipt["disposition"]=="STOPPED" and "FANOUT_SET_DUPLICATE" in receipt["reason_codes"] for receipt in state["receipts"]): return False
            pass_keys.append((row["fanout_id"].encode("utf-8"),int(row["pass"]),row["expand_occurrence_id"].encode("utf-8")))
            continue
        expected=[]
        for key in row["object_keys"]:
            matches=[item for item in state["obligations"] if item["kind"]=="FANOUT_OBJECT" and item["construct_id"]==row["fanout_id"] and item["pass"]==row["pass"] and item["source_occurrence_ids"]==[row["expand_occurrence_id"]] and canonical(item["object_key"])==canonical(key)]
            if len(matches)!=1: return False
            expected.append(matches[0]["obligation_id"])
        if row["obligation_ids"]!=expected or any(value not in obligation_ids for value in row["obligation_ids"]): return False
        if row["joined"] and any(next(item for item in state["obligations"] if item["obligation_id"]==value)["status"]!="JOINED" for value in row["obligation_ids"]): return False
        pass_keys.append((row["fanout_id"].encode("utf-8"),int(row["pass"]),row["expand_occurrence_id"].encode("utf-8")))
    if pass_keys!=sorted(pass_keys) or len(pass_keys)!=len(set(pass_keys)): return False
    unresolved=any(row["status"] in {"OPEN","BLOCKED","WAITING","DISPUTED"} for row in state["obligations"])
    if state["status"]=="ACTIVE" and not state["active"] and not unresolved: return False
    if state["status"]=="COMPLETE" and (state["active"] or unresolved): return False
    if state["status"]=="STOPPED" and not any(row["disposition"]=="STOPPED" for row in state["receipts"]): return False
    return True


def _budget_states(event):
    return [
        {
            "registry_digest": row["registry_digest"],
            "affected_anchors": copy.deepcopy(row["affected_anchors"]),
            "state": copy.deepcopy(row["request"]["state"]),
            "state_digest": row["request"]["state_digest"],
        }
        for row in event.get("budget_inputs", [])
    ]


def refusal(request, code):
    return {
        "status": "REFUSED", "profile": request["profile"], "role": request["role"],
        "code": code, "path": "", "state": copy.deepcopy(request["state"]),
        "state_digest": request["state_digest"], "budget_states": _budget_states(request["event"]),
    }


def _finish(request, next_state, disposition, reasons, details, permit=None, budget_results=None, authority_result_digest=None, permit_digest=None):
    event = request["event"]
    event_digest = digest("runtime-event", event)
    budget_results = [] if budget_results is None else copy.deepcopy(budget_results)
    next_state["revision"] = str(int(request["state"]["revision"]) + 1)
    next_state["receipts"] = copy.deepcopy(request["state"]["receipts"])
    next_state["replays"] = copy.deepcopy(request["state"]["replays"])
    core = copy.deepcopy(next_state); core["receipts"] = []; core["replays"] = []
    core_digest = digest("work-state-core", core)
    authority_digest = authority_result_digest
    reservation_digests = []
    for detail in details:
        if detail["kind"] == "AUTHORITY": authority_digest = detail["authority_result_digest"]
        if detail["kind"] == "SEPARATION": authority_digest = digest("authority-result", detail["authority_result"])
        if detail["kind"] == "BUDGET": reservation_digests.append(detail["receipt_digest"])
    if permit is not None:
        authority_digest = permit["authority_result_digest"]
        reservation_digests = [row["receipt_digest"] for row in permit["budget_revisions"]]
    receipt = {
        "schema": "seampoint.work-class/1.0.0-draft.2/decision-receipt",
        "decision_id": "sha256:" + "0" * 64,
        "instance_id": event["instance_id"], "sequence": next_state["revision"],
        "event_id": event["event_id"], "event_digest": event_digest, "event_kind": event["kind"],
        "disposition": disposition, "reason_codes": sorted(set(reasons), key=str.encode),
        "details": copy.deepcopy(details), "permit_digest": permit_digest if permit is None else permit["permit_id"],
        "authority_result_digest": authority_digest,
        "reservation_receipt_digests": reservation_digests,
        "state_before_digest": request["state_digest"], "state_after_core_digest": core_digest,
    }
    receipt_body = copy.deepcopy(receipt); del receipt_body["decision_id"]
    decision_digest = digest("decision-receipt", receipt_body)
    receipt["decision_id"] = decision_digest
    next_state["receipts"].append(copy.deepcopy(receipt))
    transaction = digest("lifecycle-transaction", {
        "state_before_digest": request["state_digest"], "event_digest": event_digest,
        "decision_receipt_digest": decision_digest, "state_after_core_digest": core_digest,
        "budget_results": budget_results,
    })
    replay = {
        "event_id": event["event_id"], "event_digest": event_digest,
        "decision": copy.deepcopy(receipt), "decision_receipt_digest": decision_digest,
        "permit": copy.deepcopy(permit), "budget_results": copy.deepcopy(budget_results),
        "transition_state_digest": core_digest, "transaction_digest": transaction,
    }
    next_state["replays"].append(replay)
    next_state["receipts"].sort(key=lambda row: int(row["sequence"]))
    next_state["replays"].sort(key=lambda row: row["event_id"].encode("utf-8"))
    result = {
        "status": "STEP", "profile": request["profile"], "role": request["role"],
        "decision": receipt, "decision_digest": decision_digest, "permit": copy.deepcopy(permit),
        "budget_results": budget_results, "state": next_state, "state_digest": state_digest(next_state),
        "transition_state_digest": core_digest, "transaction_digest": transaction, "replay": False,
    }
    if not schema_valid(result, "lifecycle.schema.json", "stepResult"):
        raise RuntimeError("lifecycle transition produced an invalid result")
    return result


def _replay(request):
    event = request["event"]
    retained = next((row for row in request["state"]["replays"] if row["event_id"] == event["event_id"]), None)
    if retained is None:
        return None
    if retained["event_digest"] != digest("runtime-event", event):
        raise Refusal("REPLAY_CONFLICT")
    if event["kind"]=="PROPOSE":
        proposals=[row for row in request["state"]["proposals"] if row["event_id"]==event["event_id"]]
        if len(proposals)!=1 or proposals[0]["proposal_digest"]!=digest("proposal",event):
            raise Refusal("STATE_INVALID")
        if retained["permit"] is not None and retained["permit"]["proposal_digest"]!=proposals[0]["proposal_digest"]:
            raise Refusal("STATE_INVALID")
    return {
        "status": "STEP", "profile": request["profile"], "role": request["role"],
        "decision": copy.deepcopy(retained["decision"]), "decision_digest": retained["decision_receipt_digest"],
        "permit": copy.deepcopy(retained["permit"]), "budget_results": copy.deepcopy(retained["budget_results"]),
        "state": copy.deepcopy(request["state"]), "state_digest": request["state_digest"],
        "transition_state_digest": retained["transition_state_digest"], "transaction_digest": retained["transaction_digest"],
        "replay": True,
    }


def _clock_step(request):
    event = request["event"]; clock = event["clock"]; state = copy.deepcopy(request["state"])
    prior = [row for row in state["clocks"] if row["source"] == clock["source"]]
    if prior and int(clock["revision"]) <= max(int(row["revision"]) for row in prior):
        raise Refusal("CLOCK_INVALID")
    if clock["status"] == "AVAILABLE":
        if not valid_instant(clock["observed_time"]): raise Refusal("CLOCK_INVALID")
        available = [row for row in prior if row["status"] == "AVAILABLE"]
        if available and _parse(clock["observed_time"]) < max(_parse(row["observed_time"]) for row in available):
            raise Refusal("CLOCK_INVALID")
    state["clocks"].append(copy.deepcopy(clock))
    state["clocks"].sort(key=lambda row: (row["source"].encode("utf-8"), int(row["revision"])))
    clock_detail = {"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]}
    if clock["status"] != "AVAILABLE":
        return _finish(request, state, "CLOCK_RECORDED", ["CLOCK_UNAVAILABLE"], [clock_detail])
    due = [row for row in state["deadlines"] if row["status"] == "PENDING" and row["source"] == clock["source"] and _due(row, clock["observed_time"])]
    if not due:
        return _finish(request, state, "CLOCK_RECORDED", [], [clock_detail])
    due.sort(key=lambda row: (row["due"], canonical(next(item["occurrence"] for item in state["active"] if item["occurrence"]["occurrence_id"] == row["occurrence_id"])), row["deadline_id"].encode("utf-8")))
    event_digest = digest("runtime-event", event)
    for deadline in due:
        deadline["status"] = "EXPIRED"
        deadline["expiry_event_digest"] = event_digest
    eligible_ids = []
    for deadline in due:
        active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == deadline["occurrence_id"]), None)
        if active is not None and active["status"] != "BLOCKED_DISPUTE":
            eligible_ids.append(deadline["occurrence_id"])
    deadline_ids = {row["deadline_id"] for row in due}
    if request["state"]["status"] == "STOPPED":
        for occurrence_id in eligible_ids:
            active = next(row for row in state["active"] if row["occurrence"]["occurrence_id"] == occurrence_id)
            _complete_late_occurrence(request, state, active, "EXPIRED", clock["evidence_digest"], clock["observed_time"])
        detail = {"kind":"DEADLINE","deadline_ids":sorted(deadline_ids,key=str.encode),"reasons":[]}
        return _finish(request,state,"EXPIRED",[],[clock_detail,detail])

    simulated = copy.deepcopy(state)
    route_digests = set()
    construct_ids = set()
    stop_reasons = []
    deadline_reasons = set()
    limit_detail = None
    for position, occurrence_id in enumerate(eligible_ids):
        active = next(row for row in simulated["active"] if row["occurrence"]["occurrence_id"] == occurrence_id)
        disposition, reasons, details = _complete_simple_route(
            request, simulated, active, "EXPIRED", clock["evidence_digest"], None,
            clock["observed_time"], None,
        )
        for detail in details:
            if detail["kind"] == "ROUTE":
                route_digests.update(detail["relationship_digests"])
                construct_ids.update(detail["construct_ids"])
            elif detail["kind"] == "DEADLINE":
                deadline_ids.update(detail["deadline_ids"])
                deadline_reasons.update(detail["reasons"])
            elif detail["kind"] == "LIMIT" and limit_detail is None:
                limit_detail = detail
        if disposition == "STOPPED":
            stop_reasons.extend(reasons)
            simulated["status"] = "ACTIVE"
        elif simulated["status"] == "COMPLETE" and position + 1 < len(eligible_ids):
            simulated["status"] = "ACTIVE"
    if stop_reasons:
        stopped = state
        definitions = {row["id"]:row for row in request["definition"]["deadlines"]}
        for occurrence_id in eligible_ids:
            active = next(row for row in stopped["active"] if row["occurrence"]["occurrence_id"] == occurrence_id)
            deadline = next(row for row in due if row["occurrence_id"] == occurrence_id)
            rule = definitions[deadline["deadline_id"]]
            relation = next((row for row in request["definition"]["relationships"] if row["kind"] == "EXPIRY" and row["deadline_ref"] == rule["id"]), None)
            stopped["active"].remove(active)
            stopped["completed"].append({
                "occurrence":copy.deepcopy(active["occurrence"]),"disposition":"EXPIRED",
                "evidence_digest":clock["evidence_digest"],"occurred_at":clock["observed_time"],
                "route_label":None,"selected_relationship_digest":None if relation is None else digest("relationship",relation),"late":False,
            })
            _discharge_obligation(request,stopped,active,clock["evidence_digest"])
        stopped["active"].sort(key=lambda row:canonical(row["occurrence"]))
        stopped["completed"].sort(key=lambda row:canonical(row["occurrence"]))
        stopped["status"]="STOPPED"
        deadline_reasons.update(reason for reason in stop_reasons if reason in {"EXPIRY_STOP","ACTIVATION_CLOCK_UNAVAILABLE","DEADLINE_ALREADY_DUE","DEADLINE_TIME_OVERFLOW"})
        reasons=sorted(deadline_reasons | ({"LIMIT_EXCEEDED"} if limit_detail is not None else set()),key=str.encode)
        details=[clock_detail,{"kind":"DEADLINE","deadline_ids":sorted(deadline_ids,key=str.encode),"reasons":sorted(deadline_reasons,key=str.encode)}]
        if limit_detail is not None: details.append(limit_detail)
        return _finish(request,stopped,"STOPPED",reasons,details)
    simulated["active"].sort(key=lambda row:canonical(row["occurrence"]))
    simulated["completed"].sort(key=lambda row:canonical(row["occurrence"]))
    if not simulated["active"] and not any(row["status"] in {"OPEN","BLOCKED","WAITING","DISPUTED"} for row in simulated["obligations"]):
        simulated["status"]="COMPLETE"
    details=[clock_detail,{"kind":"DEADLINE","deadline_ids":sorted(deadline_ids,key=str.encode),"reasons":[]}]
    if route_digests or construct_ids:
        details.append({"kind":"ROUTE","relationship_digests":sorted(route_digests,key=str.encode),"construct_ids":sorted(construct_ids,key=str.encode)})
    return _finish(request,simulated,"EXPIRED",[],details)


def _dispatch_base(attempt, acknowledgement):
    a, k = attempt["status"], acknowledgement["status"]
    if a == "NOT_SENT":
        return ("DISPUTED", ["DISPATCH_EVIDENCE_CONFLICT"]) if k == "ACCEPTED" else ("DISPATCH_REFUSED", ["NATIVE_NOT_SENT"])
    if a == "SENT":
        if k == "ACCEPTED": return "ACKNOWLEDGED", []
        if k == "NONE": return "DISPATCH_RECORDED", []
        if k == "REJECTED": return "DISPATCH_RECORDED", ["ACKNOWLEDGEMENT_REJECTED"]
        return "DISPATCH_RECORDED", ["DISPATCH_STATUS_UNKNOWN"]
    if a == "REJECTED":
        return ("DISPUTED", ["DISPATCH_EVIDENCE_CONFLICT"]) if k == "ACCEPTED" else ("DISPATCH_REFUSED", ["NATIVE_DISPATCH_REJECTED"])
    return ("ACKNOWLEDGED", []) if k == "ACCEPTED" else ("DISPATCH_RECORDED", ["DISPATCH_STATUS_UNKNOWN"])


def _dispatch_step(request):
    event = request["event"]; state = copy.deepcopy(request["state"]); permit = event["permit"]
    retained_permit = next((row for row in state["permits"] if row["permit_id"] == permit["permit_id"]), None)
    if retained_permit is None:
        raise Refusal("PREREQUISITE_MISSING")
    if canonical(retained_permit) != canonical(permit):
        raise Refusal("BINDING_MISMATCH")
    clocks = [row for row in state["clocks"] if row["source"] == permit["clock_source"] and row["status"] == "AVAILABLE"]
    if not clocks:
        raise Refusal("CLOCK_INVALID")
    latest = max(clocks, key=lambda row: int(row["revision"]))
    if event["clock_revision"] != latest["revision"]:
        raise Refusal("CLOCK_INVALID")
    attempt = event["attempt"]; acknowledgement = event["acknowledgement"]
    attempted = _parse(attempt["attempted_at"])
    issued = next((row for row in clocks if row["revision"] == permit["clock_revision"]), None)
    if issued is None or attempted < _parse(issued["observed_time"]) or attempted > _parse(latest["observed_time"]):
        raise Refusal("CLOCK_INVALID")
    if acknowledgement["status"] != "NONE":
        observed = _parse(acknowledgement["observed_at"])
        if observed < attempted: raise Refusal("INPUT_INVALID")
        if observed > _parse(latest["observed_time"]): raise Refusal("CLOCK_INVALID")
    expected_request_digest = digest("dispatch-native-request", {
        "instance_id": event["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
        "interface": event["native_request"]["interface"], "operation": event["native_request"]["operation"],
        "fields": event["native_request"]["fields"],
    })
    if attempt["request_digest"] != expected_request_digest:
        raise Refusal("BINDING_MISMATCH")
    connector_body = {"id": event["connector"]["id"], "version": event["connector"]["version"]}
    if event["connector"]["binding_digest"] != digest("connector-binding", connector_body):
        raise Refusal("BINDING_MISMATCH")
    attempt_digest = digest("dispatch-attempt", {"permit_id": permit["permit_id"], "native_request": event["native_request"], "connector": event["connector"], "attempt": attempt})
    prior_identifier = [
        row for row in state["dispatches"]
        if row["permit_digest"] == permit["permit_id"]
        and row["attempt"]["attempt_id"] == attempt["attempt_id"]
    ]
    if prior_identifier and any(row["dispatch_attempt_digest"] != attempt_digest for row in prior_identifier):
        raise Refusal("BINDING_MISMATCH")
    prior_same = [row for row in prior_identifier if row["dispatch_attempt_digest"] == attempt_digest]
    update = bool(prior_same)
    original_disqualifiers = []
    if update:
        prior = prior_same[-1]
        if prior["acknowledgement"]["status"] not in {"NONE", "UNKNOWN"} or acknowledgement["status"] not in {"ACCEPTED", "REJECTED"}:
            raise Refusal("PREREQUISITE_MISSING")
        original = _dispatch_decision(state, prior)
        original_disqualifiers = [
            reason for reason in original["reason_codes"]
            if reason in {
                "NATIVE_ARGUMENT_MISMATCH", "PERMIT_EXPIRED",
                "PERMIT_SUPERSEDED", "LATE_OR_PROHIBITED_DISPATCH",
            }
        ]
    else:
        other = [row for row in state["dispatches"] if row["permit_digest"] == permit["permit_id"]]
        consumed = any(row["attempt"]["status"] != "NOT_SENT" or row["acknowledgement"]["status"] == "ACCEPTED" for row in other)
        if consumed and attempt["status"] not in {"SENT", "UNKNOWN", "REJECTED"} and acknowledgement["status"] != "ACCEPTED":
            raise Refusal("PREREQUISITE_MISSING")
    disposition, reasons = _dispatch_base(attempt, acknowledgement)
    active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == permit["occurrence"]["occurrence_id"]), None)
    if update:
        reasons.extend(original_disqualifiers)
    else:
        if canonical(event["native_request"]) != canonical(permit["native_request"]): reasons.append("NATIVE_ARGUMENT_MISMATCH")
        if attempted >= _parse(permit["expires_at"]): reasons.append("PERMIT_EXPIRED")
        if any(row["supersedes_permit_digest"] == permit["permit_id"] for row in state["permits"]): reasons.append("PERMIT_SUPERSEDED")
        if consumed or state["status"] != "ACTIVE" or active is None or active["status"] != "PERMITTED":
            reasons.append("LATE_OR_PROHIBITED_DISPATCH")
    disqualified = any(reason in reasons for reason in ("NATIVE_ARGUMENT_MISMATCH","PERMIT_EXPIRED","PERMIT_SUPERSEDED","LATE_OR_PROHIBITED_DISPATCH"))
    if disqualified:
        # LIFE-009: a safe NOT_SENT row, or a matching REJECTED row without an accepted acknowledgement, stays DISPATCH_REFUSED.
        matching = canonical(event["native_request"]) == canonical(permit["native_request"])
        refused = acknowledgement["status"] != "ACCEPTED" and (attempt["status"] == "NOT_SENT" or (attempt["status"] == "REJECTED" and matching))
        disposition = "DISPATCH_REFUSED" if refused else "DISPUTED"
    record_body = {
        "dispatch_attempt_digest": attempt_digest, "event_id": event["event_id"], "event_digest": digest("runtime-event", event),
        "permit_digest": permit["permit_id"], "native_request": copy.deepcopy(event["native_request"]),
        "connector": copy.deepcopy(event["connector"]), "attempt": copy.deepcopy(attempt),
        "acknowledgement": copy.deepcopy(acknowledgement), "clock_revision": event["clock_revision"],
    }
    record = {"dispatch_digest": digest("dispatch", record_body), **record_body}
    state["dispatches"].append(record); state["dispatches"].sort(key=lambda row: row["dispatch_digest"])
    if active is not None and not update:
        if disposition in {"ACKNOWLEDGED", "DISPATCH_RECORDED"}: active["status"] = "DISPATCHED"
        elif disposition == "DISPUTED" and active["status"] == "PERMITTED": active["status"] = "OUTCOME_UNKNOWN"
    detail = {"kind": "DISPATCH", "attempt_id": attempt["attempt_id"], "reasons": sorted(set(reasons), key=str.encode)}
    return _finish(request, state, disposition, reasons, [detail], permit_digest=permit["permit_id"])


def _authority_projection(definition):
    proposal_steps = [row for row in definition["steps"] if row["kind"] in work_class.PROPOSAL]
    type_ids = sorted({field["type_ref"] for step in proposal_steps for field in step["fields"]}, key=str.encode)
    types = {row["id"]: row for row in definition["types"]}
    return {
        "schema": "seampoint.work-class/1.0.0-draft.2/authority-work-class",
        "id": definition["id"], "revision": definition["revision"],
        "types": [copy.deepcopy(types[type_id]) for type_id in type_ids],
        "steps": [{key: copy.deepcopy(step[key]) for key in ("id","operation","interface","executor_role","fields","scope_fields","required_credentials")} for step in proposal_steps],
    }


def _all_occurrences(state):
    rows = [row["occurrence"] for row in state["active"]]
    rows.extend(row["occurrence"] for row in state["completed"])
    return {row["occurrence_id"]: row for row in rows}


def _predecessor_closure(state, occurrence):
    occurrences = _all_occurrences(state)
    pending = list(occurrence["predecessor_occurrence_ids"])
    result = set()
    while pending:
        occurrence_id = pending.pop()
        if occurrence_id in result:
            continue
        prior = occurrences.get(occurrence_id)
        if prior is None:
            raise Refusal("STATE_INVALID")
        result.add(occurrence_id)
        pending.extend(prior["predecessor_occurrence_ids"])
    return result


def _eligible_prior(state, current_occurrence, source_step_id):
    closure = _predecessor_closure(state, current_occurrence)
    eligible = []
    for completed in state["completed"]:
        occurrence = completed["occurrence"]
        if occurrence["occurrence_id"] not in closure or occurrence["step_id"] != source_step_id or completed["disposition"] != "SUCCEEDED":
            continue
        outcomes = [
            row for row in state["outcomes"]
            if row["kind"] == "GOVERNED" and row["classification"] == "MATCHED"
            and not row["disputed"] and row["permit_digest"] is not None
            and digest("native-evidence", row["native_evidence"]) == completed["evidence_digest"]
        ]
        outcomes = [
            row for row in outcomes
            if any(
                permit["permit_id"] == row["permit_digest"]
                and permit["occurrence"]["occurrence_id"] == occurrence["occurrence_id"]
                for permit in state["permits"]
            )
        ]
        if len(outcomes) == 1:
            eligible.append((completed, outcomes[0]))
    if not eligible:
        raise Refusal("PREREQUISITE_MISSING")
    if len(eligible) != 1:
        raise Refusal("BINDING_MISMATCH")
    return eligible[0]


def _prior_effect_bases(state, step, occurrence, native):
    result = []
    for binding in step["prior_effect_bindings"]:
        _, outcome = _eligible_prior(state, occurrence, binding["source_step_id"])
        source_fields = [row for row in outcome["native_evidence"]["actual_fields"] if row["name"] == binding["source_evidence_field"]]
        target_fields = [row for row in native["fields"] if row["name"] == binding["target_request_field"]]
        if len(source_fields) != 1 or len(target_fields) != 1 or canonical(source_fields[0]["value"]) != canonical(target_fields[0]["value"]):
            raise Refusal("BINDING_MISMATCH")
        result.append({
            "binding_id": binding["id"],
            "source_occurrence_id": next(
                permit["occurrence"]["occurrence_id"] for permit in state["permits"]
                if permit["permit_id"] == outcome["permit_digest"]
            ),
            "source_permit_digest": outcome["permit_digest"],
            "source_native_evidence_digest": digest("native-evidence", outcome["native_evidence"]),
            "source_field": binding["source_evidence_field"],
            "target_field": binding["target_request_field"],
            "value": copy.deepcopy(source_fields[0]["value"]),
        })
    return result


def _separation_bases(state, step, occurrence, current_acts):
    result = []
    for requirement in step["prior_actor_separations"]:
        completed, outcome = _eligible_prior(state, occurrence, requirement["prior_step_id"])
        permits = [row for row in state["permits"] if row["permit_id"] == outcome["permit_digest"]]
        if len(permits) != 1:
            raise Refusal("PREREQUISITE_MISSING")
        prior = [row for row in permits[0]["authority_act_bases"] if row["act"]["kind"] == requirement["prior_act_kind"]]
        current = [row for row in current_acts if row["act"]["kind"] == requirement["current_act_kind"]]
        if not prior or not current:
            raise Refusal("PREREQUISITE_MISSING")
        if len(prior) != 1 or len(current) != 1:
            raise Refusal("BINDING_MISMATCH")
        basis = {
            "requirement_id": requirement["id"], "relation": "DISTINCT_ACTOR",
            "prior_occurrence_id": completed["occurrence"]["occurrence_id"],
            "current_occurrence_id": occurrence["occurrence_id"],
            "prior_act": copy.deepcopy(prior[0]), "current_act": copy.deepcopy(current[0]),
        }
        result.append(basis)
        if prior[0]["act"]["actor"] == current[0]["act"]["actor"]:
            return result, basis
    return result, None


def _proposal_budget_binding(event, definition, step, authority_input, selected_clock, prior_permit):
    if not step["shared_budgets"]:
        if event["budget_inputs"]:
            raise Refusal("BINDING_MISMATCH")
        return None
    if len(event["budget_inputs"]) != 1:
        raise Refusal("BINDING_MISMATCH")
    supplied = event["budget_inputs"][0]
    request = supplied["request"]
    configuration = request["state"]["core"]["configuration"]
    registry_digest = digest("reservation-registry", configuration)
    if (
        supplied["affected_anchors"] != step["shared_budgets"]
        or supplied["registry_digest"] != registry_digest
        or request["host_evidence"]["registry_digest"] != registry_digest
        or supplied["expected_revision"] != request["event"]["expected_revision"]
        or supplied["expected_revision"] != request["state"]["core"]["revision"]
    ):
        raise Refusal("BINDING_MISMATCH")
    slots = [row["anchor"] for row in configuration["slots"]]
    if any(slots.count(anchor) != 1 for anchor in step["shared_budgets"]):
        raise Refusal("BINDING_MISMATCH")
    budgets = {row["definition"]["anchor"]: row for row in request["state"]["core"]["budgets"]}
    completion = step["completion"]
    for anchor in step["shared_budgets"]:
        budget = budgets.get(anchor)
        if budget is None:
            raise Refusal("BINDING_MISMATCH")
        policy = budget["definition"]["reservation_policy"]
        if (policy["settlement"]["provider"], policy["settlement"]["source"]) != (completion["effect_provider"], completion["effect_source"]):
            raise Refusal("UNSUPPORTED_RELATION")
        if (policy["no_effect"]["provider"], policy["no_effect"]["source"]) != (completion["no_effect_provider"], completion["no_effect_source"]):
            raise Refusal("UNSUPPORTED_RELATION")
    reservation_kind = "RENEW" if prior_permit is not None else "RESERVE"
    embedded = request["event"]
    expected_id = digest("lifecycle-reservation-event", {
        "instance_id": event["instance_id"], "lifecycle_event_id": event["event_id"],
        "lifecycle_event_kind": "PROPOSE", "reservation_event_kind": reservation_kind,
        "registry_digest": registry_digest,
    })
    if embedded["id"] != expected_id or embedded["kind"] != reservation_kind or embedded["administration"] is not None:
        raise Refusal("BINDING_MISMATCH")
    if canonical(embedded["payload"]["authority"]) != canonical(authority_input):
        raise Refusal("BINDING_MISMATCH")
    if canonical(embedded["clock"]) != canonical({"source": selected_clock["source"], "status": "AVAILABLE", "instant": selected_clock["observed_time"]}):
        raise Refusal("BINDING_MISMATCH")
    projected = {
        "work_class": definition["id"], "instance": event["instance_id"],
        "occurrence": event["occurrence"]["occurrence_id"], "step": event["occurrence"]["step_id"],
        "operation": event["native_request"]["operation"], "interface": event["native_request"]["interface"],
        "fields": copy.deepcopy(event["native_request"]["fields"]),
    }
    for key, value in projected.items():
        if canonical(authority_input["proposal"][key]) != canonical(value):
            raise Refusal("BINDING_MISMATCH")
    if prior_permit is not None:
        if embedded["payload"]["reservation"] != prior_permit["budget_revisions"][0]["reservation_id"]:
            raise Refusal("BINDING_MISMATCH")
    return supplied


def _proposal_step(request):
    event = request["event"]; state = copy.deepcopy(request["state"]); definition = request["definition"]
    if state["status"] != "ACTIVE": raise Refusal("INSTANCE_NOT_ACTIVE")
    active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == event["occurrence"]["occurrence_id"]), None)
    if active is None or canonical(active["occurrence"]) != canonical(event["occurrence"]): raise Refusal("BINDING_MISMATCH")
    if active["status"] == "DISPATCHED": raise Refusal("PREREQUISITE_MISSING")
    if active["status"] not in {"ACTIVE", "PERMITTED"}: raise Refusal("OCCURRENCE_NOT_ACTIVE")
    step = next(row for row in definition["steps"] if row["id"] == active["occurrence"]["step_id"])
    native = event["native_request"]
    expected_names = [row["name"] for row in step["fields"]]
    if (
        native["operation"] != step["operation"] or native["interface"] != step["interface"]
        or [row["name"] for row in native["fields"]] != expected_names
        or any(row["value"]["type_ref"] != declaration["type_ref"] for row,declaration in zip(native["fields"],step["fields"]))
    ): raise Refusal("BINDING_MISMATCH")
    participant = next((row for row in definition["participants"] if row["id"] == event["executor"]["participant_id"]), None)
    authority_input = event["authority_input"]
    auth_executor = authority_input["proposal"]["executor"]
    if participant is None or participant["role"] != step["executor_role"] or event["executor"]["role"] != step["executor_role"] or auth_executor["actor"] != participant["id"] or auth_executor["role"] != step["executor_role"]:
        raise Refusal("BINDING_MISMATCH")
    if event["executor"]["binding_digest"] != digest("executor-binding", auth_executor): raise Refusal("BINDING_MISMATCH")
    if not utf8_sorted_unique(event["credential_ids"]) or event["credential_ids"] != sorted([row["id"] for row in authority_input["credentials"]], key=str.encode): raise Refusal("BINDING_MISMATCH")
    observation_digests = sorted([digest("authority-observation", row) for row in authority_input["observations"]], key=str.encode)
    if event["observation_digests"] != observation_digests: raise Refusal("BINDING_MISMATCH")
    projection = _authority_projection(definition)
    projection_digest = digest("authority-work-class", projection)
    if canonical(authority_input["work_class"]) != canonical(projection): raise Refusal("BINDING_MISMATCH")
    if authority_input["source"]["id"] != definition["source"]["id"] or authority_input["source"]["revision"] != definition["source"]["revision"] or [row["id"] for row in authority_input["source"]["obligations"]] != definition["source"]["obligations"]: raise Refusal("BINDING_MISMATCH")
    proposal = authority_input["proposal"]
    if (
        authority_input["envelope"]["id"] != step["authority_requirements"][0]
        or proposal["work_class_digest"] != projection_digest or authority_input["envelope"]["work_class_digest"] != projection_digest
        or proposal["work_class"] != definition["id"] or proposal["instance"] != event["instance_id"]
        or proposal["occurrence"] != event["occurrence"]["occurrence_id"] or proposal["step"] != step["id"]
        or proposal["operation"] != native["operation"] or proposal["interface"] != native["interface"]
        or canonical(proposal["fields"]) != canonical(native["fields"])
    ): raise Refusal("BINDING_MISMATCH")
    for segment in event["occurrence"]["enclosing"]:
        if segment["kind"] != "FANOUT": continue
        fanout = next(row for row in definition["fanouts"] if row["id"] == segment["construct_id"])
        field = next((row for row in native["fields"] if row["name"] == fanout["object_request_field"]), None)
        if field is None or field["value"]["type_ref"] != fanout["object_type_ref"] or canonical(field["value"]) != canonical(segment["object_key"]): raise Refusal("BINDING_MISMATCH")
    renewal = active["status"] == "PERMITTED"
    prior_permit = None
    if renewal:
        candidates = [row for row in state["permits"] if row["occurrence"]["occurrence_id"] == active["occurrence"]["occurrence_id"] and not any(later["supersedes_permit_digest"] == row["permit_id"] for later in state["permits"])]
        if len(candidates) != 1: raise Refusal("STATE_INVALID")
        prior_permit = candidates[0]
        if canonical(prior_permit["native_request"]) != canonical(native): raise Refusal("BINDING_MISMATCH")
        latest = [row for row in state["clocks"] if row["source"] == prior_permit["clock_source"] and row["status"] == "AVAILABLE"]
        if not latest or max(_parse(row["observed_time"]) for row in latest) < _parse(prior_permit["expires_at"]): raise Refusal("PREREQUISITE_MISSING")
        if any(row["permit_digest"] == prior_permit["permit_id"] and row["attempt"]["status"] != "NOT_SENT" for row in state["dispatches"]): raise Refusal("PREREQUISITE_MISSING")
    elif active["status"] != "ACTIVE":
        raise Refusal("OCCURRENCE_NOT_ACTIVE")
    proposal_count = sum(1 for row in state["receipts"] if row["event_kind"] == "PROPOSE")
    if proposal_count >= int(definition["limits"]["maximum_proposals"]):
        raise Refusal("LIMIT_EXCEEDED")
    prior_effect_bases = _prior_effect_bases(state, step, active["occurrence"], native)
    authority_result = authority.evaluate_authority(authority_input, PIN)
    admission_codes = {"SCHEMA_INVALID","ARTIFACT_ENCODING_INVALID","ARTIFACT_NONCANONICAL","TYPE_INVALID","INPUT_INVALID","LIMIT_EXCEEDED","VERSION_UNSUPPORTED","DEPENDENCY_MISMATCH","UNSUPPORTED_RELATION","REFERENCE_INVALID","BINDING_MISMATCH"}
    authority_digest = digest("authority-result", authority_result)
    event_digest = digest("runtime-event", event); proposal_digest = digest("proposal", event)
    prior_digest = None if prior_permit is None else prior_permit["permit_id"]
    if authority_result["status"] == "REFUSED":
        if authority_result["code"] in admission_codes: raise Refusal(authority_result["code"])
        reasons = sorted(set(["AUTHORITY_REQUIRED", authority_result["code"], *authority_result["reasons"]]), key=str.encode)
        detail = {"kind":"AUTHORITY","authority_result_digest":authority_digest,"code":authority_result["code"],"reasons":copy.deepcopy(authority_result["reasons"]),"failed_checks":copy.deepcopy(authority_result["failed_checks"])}
        state["proposals"].append({"event_id":event["event_id"],"event_digest":event_digest,"proposal_digest":proposal_digest,"occurrence_id":active["occurrence"]["occurrence_id"],"disposition":"WITHHELD","permit_digest":None,"authority_result_digest":authority_digest,"reservation_receipt_digests":[],"prior_permit_digest":prior_digest})
        state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
        return _finish(request,state,"WITHHELD",reasons,[detail])
    if authority_result["required_budgets"] != step["shared_budgets"]: raise Refusal("BINDING_MISMATCH")
    available_clocks = [row for row in state["clocks"] if row["status"] == "AVAILABLE" and row["source"] == authority_input["clock"]["source"]]
    selected_clock = next((row for row in available_clocks if row["revision"] == event["clock_revision"]), None)
    if selected_clock is None or selected_clock["observed_time"] != authority_input["clock"]["instant"]: raise Refusal("BINDING_MISMATCH")
    selected_acts = []
    for act_digest in authority_result["act_digests"]:
        acts = [row for row in authority_input["acts"] if digest("authority-act", row) == act_digest]
        if len(acts) != 1: raise Refusal("BINDING_MISMATCH")
        selected_acts.append({"act_digest":act_digest,"act":copy.deepcopy(acts[0])})
    selected_acts.sort(key=lambda row: row["act_digest"])
    separation_bases, failed_separation = _separation_bases(state, step, active["occurrence"], selected_acts)
    if failed_separation is not None:
        detail = {"kind":"SEPARATION", "authority_result":copy.deepcopy(authority_result), "basis":failed_separation}
        state["proposals"].append({"event_id":event["event_id"],"event_digest":event_digest,"proposal_digest":proposal_digest,"occurrence_id":active["occurrence"]["occurrence_id"],"disposition":"WITHHELD","permit_digest":None,"authority_result_digest":authority_digest,"reservation_receipt_digests":[],"prior_permit_digest":prior_digest})
        state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
        return _finish(request,state,"WITHHELD",["SEPARATION_VIOLATED"],[detail])
    if prior_permit is None and int(state["total_actuations"]) >= int(definition["limits"]["maximum_actuations"]):
        state["status"] = "STOPPED"
        detail = {"kind":"LIMIT","limit_kind":"ACTUATIONS","limit":definition["limits"]["maximum_actuations"],"current":str(int(state["total_actuations"])+1),"step_id":step["id"],"relationship_digest":None}
        return _finish(request,state,"STOPPED",["LIMIT_EXCEEDED"],[detail],authority_result_digest=authority_digest)
    budget_results=[]; budget_revisions=[]; receipt_digests=[]
    try:
        expires = _add_seconds(selected_clock["observed_time"], int(step["permit_seconds"]))
    except (OverflowError, ValueError):
        raise Refusal("LIMIT_EXCEEDED") from None
    if step["shared_budgets"]:
        budget_input = _proposal_budget_binding(event, definition, step, authority_input, selected_clock, prior_permit)
        budget_result=reservation_v2.aggregate_step(budget_input["request"], PIN)
        if budget_result["status"] == "REFUSED": raise Refusal(budget_result["code"])
        budget_results=[{"registry_digest":budget_input["registry_digest"],"affected_anchors":copy.deepcopy(budget_input["affected_anchors"]),"result":budget_result}]
        receipt_digests=[budget_result["receipt_digest"]]
        if budget_result["receipt"]["decision"] == "WITHHELD":
            reasons=sorted(set(["BUDGET_WITHHELD",*budget_result["receipt"]["reasons"]]),key=str.encode)
            detail={"kind":"BUDGET","registry_digest":budget_input["registry_digest"],"receipt_digest":budget_result["receipt_digest"],"reasons":copy.deepcopy(budget_result["receipt"]["reasons"])}
            state["proposals"].append({"event_id":event["event_id"],"event_digest":event_digest,"proposal_digest":proposal_digest,"occurrence_id":active["occurrence"]["occurrence_id"],"disposition":"WITHHELD","permit_digest":None,"authority_result_digest":authority_digest,"reservation_receipt_digests":receipt_digests,"prior_permit_digest":prior_digest})
            state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8"))
            return _finish(request,state,"WITHHELD",reasons,[detail],budget_results=budget_results,authority_result_digest=authority_digest)
        reservation_id=budget_result["receipt"]["reservation"]
        reservation_row=next(row for row in budget_result["state"]["core"]["reservations"] if row["id"]==reservation_id)
        expires=min(expires,reservation_row["permit_until"])
        budget_revisions=[{"registry_digest":budget_input["registry_digest"],"affected_anchors":copy.deepcopy(budget_input["affected_anchors"]),"revision":budget_result["state"]["core"]["revision"],"reservation_id":reservation_id,"receipt_digest":budget_result["receipt_digest"]}]
    else:
        _proposal_budget_binding(event, definition, step, authority_input, selected_clock, prior_permit)
    permit_body={"schema":"seampoint.work-class/1.0.0-draft.2/permit","instance_id":event["instance_id"],"work_class_digest":request["definition_digest"],"profile":request["profile"],"role":request["role"],"occurrence":copy.deepcopy(active["occurrence"]),"proposal_digest":proposal_digest,"native_request":copy.deepcopy(native),"executor":copy.deepcopy(event["executor"]),"credential_ids":copy.deepcopy(event["credential_ids"]),"authority_result":copy.deepcopy(authority_result),"authority_result_digest":authority_digest,"authority_evidence_digest":authority_result["evidence_digest"],"authority_act_bases":selected_acts,"prior_effect_bases":prior_effect_bases,"separation_bases":separation_bases,"observation_digests":copy.deepcopy(event["observation_digests"]),"supersedes_permit_digest":prior_digest,"budget_revisions":budget_revisions,"clock_source":selected_clock["source"],"clock_revision":selected_clock["revision"],"expires_at":expires}
    permit={"permit_id":digest("permit",permit_body),**permit_body}
    state["permits"].append(permit); state["permits"].sort(key=lambda row: row["permit_id"])
    state["proposals"].append({"event_id":event["event_id"],"event_digest":event_digest,"proposal_digest":proposal_digest,"occurrence_id":active["occurrence"]["occurrence_id"],"disposition":"PERMITTED","permit_digest":permit["permit_id"],"authority_result_digest":authority_digest,"reservation_receipt_digests":receipt_digests,"prior_permit_digest":prior_digest})
    state["proposals"].sort(key=lambda row: row["event_id"].encode("utf-8")); active["status"]="PERMITTED"
    if prior_permit is None:
        counter=next(row for row in state["step_counters"] if row["step_id"]==step["id"]); counter["actuations"]=str(int(counter["actuations"])+1); state["total_actuations"]=str(int(state["total_actuations"])+1)
    return _finish(request,state,"PERMITTED",[],[],permit,budget_results)


def _native_fact_digest(native):
    value = copy.deepcopy(native)
    del value["evidence_id"]
    del value["evidence_ref"]
    return digest("native-evidence-fact", value)


def _outcome_record(body):
    return {"outcome_digest": digest("outcome", body), **body}


def _dispatch_decision(state, dispatch):
    rows = [row for row in state["receipts"] if row["event_id"] == dispatch["event_id"] and row["event_kind"] == "DISPATCH_OBSERVED"]
    if len(rows) != 1:
        raise Refusal("STATE_INVALID")
    return rows[0]


def _dispatch_attempt_groups(state, permit_id):
    sequence = {row["event_id"]: int(row["sequence"]) for row in state["receipts"]}
    rows = sorted(
        [row for row in state["dispatches"] if row["permit_digest"] == permit_id],
        key=lambda row: (sequence[row["event_id"]], row["dispatch_digest"]),
    )
    groups = []
    by_digest = {}
    for row in rows:
        key = row["dispatch_attempt_digest"]
        if key not in by_digest:
            group = {"digest": key, "records": []}
            by_digest[key] = group
            groups.append(group)
        by_digest[key]["records"].append(row)
    return groups


def _final_safe_attempt_set(state, permit_id, selected_attempt_digest):
    groups = _dispatch_attempt_groups(state, permit_id)
    if not groups or groups[-1]["digest"] != selected_attempt_digest:
        return False
    for group in groups[:-1]:
        first = group["records"][0]
        if first["attempt"]["status"] != "NOT_SENT" or any(row["acknowledgement"]["status"] == "ACCEPTED" for row in group["records"]):
            return False
    return True


def _rehash_outcome(row):
    body = copy.deepcopy(row)
    del body["outcome_digest"]
    row["outcome_digest"] = digest("outcome", body)


def _extend_duplicate_conflicts(state, source, evidence_id):
    for row in state["outcomes"]:
        if row["native_evidence"]["evidence_id"] in source["conflicts_with_evidence_ids"]:
            row["conflicts_with_evidence_ids"] = sorted(set(row["conflicts_with_evidence_ids"] + [evidence_id]), key=str.encode)
            row["disputed"] = True
            _rehash_outcome(row)


def _block_dependents(state, source_occurrence_id):
    affected = {source_occurrence_id}
    changed = True
    while changed:
        changed = False
        for row in state["active"] + state["completed"]:
            occurrence = row["occurrence"]
            if occurrence["occurrence_id"] not in affected and set(occurrence["predecessor_occurrence_ids"]) & affected:
                affected.add(occurrence["occurrence_id"]); changed = True
    for row in state["active"]:
        if row["occurrence"]["occurrence_id"] in affected and row["occurrence"]["occurrence_id"] != source_occurrence_id:
            row["status"] = "BLOCKED_DISPUTE"
    for obligation in state["obligations"]:
        if obligation["status"] == "OPEN" and obligation["expected_occurrence_id"] in affected:
            obligation["status"] = "BLOCKED"
        elif obligation["status"] == "DISCHARGED":
            try: frontier=_completion_frontier(state,obligation)
            except Refusal: raise Refusal("STATE_INVALID") from None
            if set(frontier)&affected: obligation["status"] = "DISPUTED"
    changed = True
    while changed:
        changed = False
        disputed = {row["obligation_id"] for row in state["obligations"] if row["status"] == "DISPUTED"}
        for obligation in state["obligations"]:
            if obligation["status"] == "WAITING" and set(obligation["waiting_on"]["obligation_ids"]) & disputed:
                obligation["status"] = "DISPUTED"; changed = True


def _complete_late_occurrence(request, state, active, classification, evidence_digest, occurred_at):
    state["active"] = [row for row in state["active"] if row["occurrence"]["occurrence_id"] != active["occurrence"]["occurrence_id"]]
    state["completed"].append({
        "occurrence": copy.deepcopy(active["occurrence"]),
        "disposition": "EXPIRED" if classification == "EXPIRED" else ("NO_EFFECT" if classification == "NO_EFFECT_ESTABLISHED" else ("FAILED" if classification == "FAILED" else "SUCCEEDED")),
        "evidence_digest": evidence_digest, "occurred_at": occurred_at,
        "route_label": None, "selected_relationship_digest": None, "late": True,
    })
    for deadline in state["deadlines"]:
        if deadline["occurrence_id"] == active["occurrence"]["occurrence_id"] and deadline["status"] == "PENDING":
            deadline["status"] = "DISCHARGED"
    _discharge_obligation(request, state, active, evidence_digest)
    state["completed"].sort(key=lambda row: canonical(row["occurrence"]))


def _completion_fields(step, permit, evidence):
    completion = step["completion"]
    actual = evidence["actual_fields"]
    by_name = {}
    for row in actual:
        by_name.setdefault(row["name"], []).append(row)
    status = by_name.get(completion["status_field"], [])
    expected_bound = {row["evidence_field"]: row["request_field"] for row in completion["evidence_bindings"]}
    request_fields = {row["name"]: row["value"] for row in permit["native_request"]["fields"]}
    bound_ok = all(
        len(by_name.get(evidence_name, [])) == 1
        and canonical(by_name[evidence_name][0]["value"]) == canonical(request_fields[request_name])
        for evidence_name, request_name in expected_bound.items()
    )
    if len(status) != 1 or status[0]["value"]["type_ref"] != completion["status_type_ref"]:
        return "UNEXPECTED", None, False
    value = status[0]["value"]
    success = any(canonical(value) == canonical(row) for row in completion["success_values"])
    failure = any(canonical(value) == canonical(row) for row in completion["failure_values"])
    base_names = set(expected_bound) | {completion["status_field"]}
    allowed_names = set(base_names)
    if success and completion["route_label_field"] is not None:
        allowed_names.add(completion["route_label_field"])
    if not bound_ok or not base_names <= set(by_name) or set(by_name) - allowed_names or any(len(by_name[name]) != 1 for name in base_names):
        return "UNEXPECTED", None, False
    if failure:
        if evidence["collections"]:
            return "UNEXPECTED", None, False
        return "FAILED", None, True
    if success:
        label = None
        if completion["route_label_field"] is not None:
            rows = by_name.get(completion["route_label_field"], [])
            if len(rows) == 1:
                label = copy.deepcopy(rows[0]["value"])
        if step["kind"] != "FANOUT_EXPAND" and evidence["collections"]:
            return "UNEXPECTED", None, False
        return "MATCHED", label, True
    return "UNEXPECTED", None, False


def _relation_for(definition, step, classification, label):
    relationships = definition["relationships"]
    if classification in {"FAILED", "NO_EFFECT_ESTABLISHED"}:
        return next((row for row in relationships if row["from"] == step["id"] and row["kind"] == "FAILURE"), None), None
    choice = next((row for row in definition["choices"] if row["step_id"] == step["id"]), None)
    if choice is not None:
        if label is None or not any(canonical(label) == canonical(value) for value in choice["label_values"]):
            return None, "LABEL_INVALID"
        return next((row for row in relationships if row["from"] == step["id"] and row["kind"] == "LABEL" and canonical(row["label"]) == canonical(label)), None), None
    return next((row for row in relationships if row["from"] == step["id"] and row["kind"] == "SEQUENCE"), None), None


def _next_enclosing(definition, source_occurrence, relation, target_id):
    enclosing = copy.deepcopy(source_occurrence["enclosing"])
    loops = definition["loops"]
    source_id = source_occurrence["step_id"]
    target_loop = next((row for row in loops if target_id in row["member_step_ids"]), None)
    source_loop = next((row for row in loops if source_id in row["member_step_ids"]), None)
    if source_loop is not None and target_loop is None:
        enclosing = [row for row in enclosing if not (row["kind"] == "LOOP" and row["construct_id"] == source_loop["id"])]
    elif target_loop is not None:
        segment = next((row for row in enclosing if row["kind"] == "LOOP" and row["construct_id"] == target_loop["id"]), None)
        if segment is None:
            enclosing.append({"kind":"LOOP","construct_id":target_loop["id"],"pass":"1","branch_id":None,"object_key":None})
        elif relation is not None and source_id == target_loop["back_edge_from_step_id"] and target_id == target_loop["entry_step_id"]:
            segment["pass"] = str(int(segment["pass"])+1)
    return enclosing, target_loop


def _activation_preflight(request, state, source_occurrence, relation, target, predecessors=None, enclosing_override=None, activation_clocks=None, ordinal=None):
    definition=request["definition"]
    counter=next(row for row in state["step_counters"] if row["step_id"]==target["id"])
    projected_step=int(counter["activations"])+1 if ordinal is None else int(ordinal)
    limit=next((row for row in definition["occurrence_limits"] if row["step_id"]==target["id"]),None)
    relationship_digest=None if relation is None else digest("relationship",relation)
    if limit is not None and projected_step > int(limit["maximum"]):
        return None,None,["LIMIT_EXCEEDED"],{"kind":"LIMIT","limit_kind":"STEP_OCCURRENCES","limit":limit["maximum"],"current":str(projected_step),"step_id":target["id"],"relationship_digest":relationship_digest}
    enclosing,target_loop=_next_enclosing(definition,source_occurrence,relation,target["id"])
    if enclosing_override is not None:
        enclosing=copy.deepcopy(enclosing_override)
        if target_loop is not None and not any(row["kind"]=="LOOP" and row["construct_id"]==target_loop["id"] for row in enclosing):
            enclosing.append({"kind":"LOOP","construct_id":target_loop["id"],"pass":"1","branch_id":None,"object_key":None})
    if target_loop is not None:
        segment=next(row for row in enclosing if row["kind"]=="LOOP" and row["construct_id"]==target_loop["id"])
        if int(segment["pass"]) > int(target_loop["maximum_passes"]):
            return None,None,["LOOP_BOUND_REACHED"],{"kind":"LIMIT","limit_kind":"LOOP_PASSES","limit":target_loop["maximum_passes"],"current":segment["pass"],"step_id":target["id"],"relationship_digest":relationship_digest}
    projected_total=int(state["total_activations"])+1
    if projected_total > int(definition["limits"]["maximum_activations"]):
        return None,None,["LIMIT_EXCEEDED"],{"kind":"LIMIT","limit_kind":"ACTIVATIONS","limit":definition["limits"]["maximum_activations"],"current":str(projected_total),"step_id":target["id"],"relationship_digest":relationship_digest}
    object_key=None
    for segment in reversed(enclosing):
        if segment["kind"]=="FANOUT": object_key=segment["object_key"]; break
    occurrence=_occurrence(PIN,request["definition_digest"],state["instance_id"],target["id"],str(projected_step) if ordinal is None else ordinal,[source_occurrence["occurrence_id"]] if predecessors is None else predecessors,enclosing,object_key)
    deadline_defs=[row for row in definition["deadlines"] if row["step_id"]==target["id"]]
    required_sources=sorted({row["clock_source"] for row in deadline_defs},key=str.encode)
    supplied=request["event"].get("activation_clocks",[]) if activation_clocks is None else activation_clocks
    if [row["source"] for row in supplied] != required_sources:
        if set(row["source"] for row in supplied) != set(required_sources):
            if set(row["source"] for row in supplied) - set(required_sources): raise Refusal("DEPENDENCY_MISMATCH")
        if supplied: raise Refusal("DEPENDENCY_MISMATCH")
        return occurrence,None,["ACTIVATION_CLOCK_UNAVAILABLE"],None
    clocks=[]
    for row in supplied:
        available=[prior for prior in state["clocks"] if prior["source"]==row["source"] and prior["status"]=="AVAILABLE"]
        if not available:
            return occurrence,None,["ACTIVATION_CLOCK_UNAVAILABLE"],None
        latest=max(available,key=lambda item:int(item["revision"]))
        if canonical(row)!=canonical(latest): raise Refusal("DEPENDENCY_MISMATCH")
        clocks.append(row)
    deadlines=[]
    for definition_deadline in deadline_defs:
        try:
            deadline=_deadline(definition,definition_deadline,occurrence,digest("runtime-event",request["event"]),str(int(state["revision"])+1),next(row for row in clocks if row["source"]==definition_deadline["clock_source"]),state)
        except Refusal as error:
            if error.code=="LIMIT_EXCEEDED": return occurrence,None,["DEADLINE_TIME_OVERFLOW"],None
            raise
        if _due(deadline,deadline["activation_instant"]): return occurrence,None,["DEADLINE_ALREADY_DUE"],None
        deadlines.append(deadline)
    return occurrence,deadlines,[],None


def _obligation(kind, construct_id, pass_value, sources, branch_id, object_key, join_step_id, event_digest, occurrence, operation):
    identity={"kind":kind,"construct_id":construct_id,"pass":pass_value,"source_occurrence_ids":copy.deepcopy(sources),"branch_id":branch_id,"object_key":copy.deepcopy(object_key),"join_step_id":join_step_id}
    return {"obligation_id":digest("obligation",identity),**identity,"creation_event_digest":event_digest,"status":"OPEN","expected_occurrence_id":occurrence["occurrence_id"],"required_operation":operation,"waiting_on":None,"completion_basis":None}


def _occurrence_from_state(state, occurrence_id):
    return next(
        (
            row["occurrence"] for row in state["active"] + state["completed"]
            if row["occurrence"]["occurrence_id"] == occurrence_id
        ),
        None,
    )


def _obligation_outer(state, obligation):
    occurrence_ids=[]
    if obligation["expected_occurrence_id"] is not None:
        occurrence_ids=[obligation["expected_occurrence_id"]]
    elif obligation["completion_basis"] is not None:
        try: occurrence_ids=_completion_frontier(state,obligation)
        except Refusal: return None
    segment_kind="BRANCH" if obligation["kind"]=="PARALLEL_BRANCH" else "FANOUT"
    if obligation["waiting_on"] is not None:
        enclosing=obligation["waiting_on"]["outer_enclosing"]
        for index,segment in enumerate(enclosing):
            if segment["kind"]==segment_kind and segment["construct_id"]==obligation["construct_id"] and segment["pass"]==obligation["pass"]:
                return copy.deepcopy(enclosing[:index])
        return None
    prefixes=[]
    for occurrence_id in occurrence_ids:
        occurrence=_occurrence_from_state(state,occurrence_id)
        if occurrence is None: return None
        prefix=[];found=False
        for segment in occurrence["enclosing"]:
            if segment["kind"]==segment_kind and segment["construct_id"]==obligation["construct_id"] and segment["pass"]==obligation["pass"]:
                found=True;break
            prefix.append(copy.deepcopy(segment))
        if not found: return None
        prefixes.append(prefix)
    if not prefixes or any(canonical(prefix)!=canonical(prefixes[0]) for prefix in prefixes[1:]): return None
    return prefixes[0]


def _next_construct_pass(state, construct_id, outer_enclosing, kind):
    passes = []
    if kind == "FANOUT":
        for row in state["fanout_passes"]:
            if row["fanout_id"] != construct_id:
                continue
            source = _occurrence_from_state(state, row["expand_occurrence_id"])
            if source is not None and canonical(source["enclosing"]) == canonical(outer_enclosing):
                passes.append(int(row["pass"]))
    else:
        seen = set()
        for row in state["obligations"]:
            key = (row["construct_id"], row["pass"])
            if row["kind"] != "PARALLEL_BRANCH" or row["construct_id"] != construct_id or key in seen:
                continue
            seen.add(key)
            sources = [_occurrence_from_state(state, occurrence_id) for occurrence_id in row["source_occurrence_ids"]]
            if sources and all(source is not None and canonical(source["enclosing"]) == canonical(outer_enclosing) for source in sources):
                passes.append(int(row["pass"]))
    return str(1 + max(passes or [0]))


def _enter_parallel(request,state,source_occurrence,split,predecessors):
    definition=request["definition"]; block=next(row for row in definition["parallel_blocks"] if row["split_step_id"]==split["id"])
    incoming=[row for row in definition["relationships"] if row["to"]==split["id"]]
    if len(incoming)!=1: raise Refusal("STATE_INVALID")
    relationship=incoming[0]
    pass_value=_next_construct_pass(state,block["id"],source_occurrence["enclosing"],"PARALLEL")
    projected_total=int(state["total_activations"])+len(block["branches"])
    projected_obligations=sum(row["status"] in {"OPEN","BLOCKED","WAITING","DISPUTED"} for row in state["obligations"])+len(block["branches"])
    needed=sorted({deadline["clock_source"] for branch in block["branches"] for deadline in definition["deadlines"] if deadline["step_id"]==branch["head_step_id"]},key=str.encode)
    supplied=request["event"].get("activation_clocks",[])
    if [row["source"] for row in supplied] != needed:
        if set(row["source"] for row in supplied)-set(needed): raise Refusal("DEPENDENCY_MISMATCH")
        return ["ACTIVATION_CLOCK_UNAVAILABLE"],[{"kind":"DEADLINE","deadline_ids":sorted([row["id"] for row in definition["deadlines"] if row["step_id"] in {branch["head_step_id"] for branch in block["branches"]}],key=str.encode),"reasons":["ACTIVATION_CLOCK_UNAVAILABLE"]}],[],[block["id"]]
    event_digest=digest("runtime-event",request["event"]);created=[];obligations=[];all_deadlines=[]
    steps={row["id"]:row for row in definition["steps"]}
    for branch in block["branches"]:
        target=steps[branch["head_step_id"]];enclosing=copy.deepcopy(source_occurrence["enclosing"])+[{"kind":"BRANCH","construct_id":block["id"],"pass":pass_value,"branch_id":branch["id"],"object_key":None}]
        subset=[row for row in supplied if row["source"] in {deadline["clock_source"] for deadline in definition["deadlines"] if deadline["step_id"]==target["id"]}]
        occurrence,deadlines,reasons,detail=_activation_preflight(request,state,source_occurrence,None,target,predecessors,enclosing,subset)
        if reasons:
            if detail is not None and detail["kind"]=="LIMIT" and detail["relationship_digest"] is None:
                detail["relationship_digest"]=digest("relationship",relationship)
            return reasons,([] if detail is None else [detail]),[],[block["id"]]
        created.append({"occurrence":occurrence,"activation_event_digest":event_digest,"status":"ACTIVE","deadline_ids":[row["deadline_id"] for row in deadlines]});all_deadlines.extend(deadlines)
        obligations.append(_obligation("PARALLEL_BRANCH",block["id"],pass_value,predecessors,branch["id"],None,block["join_step_id"],event_digest,occurrence,target["operation"]))
    if projected_total>int(definition["limits"]["maximum_activations"]):
        detail={"kind":"LIMIT","limit_kind":"ACTIVATIONS","limit":definition["limits"]["maximum_activations"],"current":str(projected_total),"step_id":block["branches"][0]["head_step_id"],"relationship_digest":digest("relationship",relationship)}
        return ["LIMIT_EXCEEDED"],[detail],[],[block["id"]]
    if projected_obligations>int(definition["limits"]["maximum_active_obligations"]):
        detail={"kind":"LIMIT","limit_kind":"ACTIVE_OBLIGATIONS","limit":definition["limits"]["maximum_active_obligations"],"current":str(projected_obligations),"step_id":block["branches"][0]["head_step_id"],"relationship_digest":digest("relationship",relationship)}
        return ["LIMIT_EXCEEDED"],[detail],[],[block["id"]]
    state["active"].extend(created);state["obligations"].extend(obligations);state["deadlines"].extend(all_deadlines)
    state["active"].sort(key=lambda row:canonical(row["occurrence"]));state["obligations"].sort(key=lambda row:row["obligation_id"])
    # LIFE-019: deadlines sort by due instant, occurrence bytes and deadline identifier, not branch source order.
    state["deadlines"].sort(key=lambda row:(row["due"],canonical(_occurrence_from_state(state,row["occurrence_id"])),row["deadline_id"].encode("utf-8")))
    for row in created:
        counter=next(item for item in state["step_counters"] if item["step_id"]==row["occurrence"]["step_id"]);counter["activations"]=str(int(counter["activations"])+1)
    state["total_activations"]=str(projected_total)
    return [],[],[row["obligation_id"] for row in obligations],[block["id"]]


def _enter_fanout(request,state,source_occurrence,evidence):
    definition=request["definition"];fanout=next(row for row in definition["fanouts"] if row["expand_step_id"]==source_occurrence["step_id"])
    collection=evidence["collections"][0];keys=copy.deepcopy(collection["values"])
    pass_value=_next_construct_pass(state,fanout["id"],source_occurrence["enclosing"],"FANOUT")
    pass_row={"fanout_id":fanout["id"],"pass":pass_value,"expand_occurrence_id":source_occurrence["occurrence_id"],"object_keys":keys,"obligation_ids":[],"joined":False}
    if len({canonical(row) for row in keys})!=len(keys):
        state["fanout_passes"].append(pass_row);state["fanout_passes"].sort(key=lambda row:(row["fanout_id"].encode("utf-8"),int(row["pass"]),row["expand_occurrence_id"].encode("utf-8")))
        return ["FANOUT_SET_DUPLICATE"],[],[fanout["id"]]
    if not keys:
        if fanout["empty_set_behavior"]=="STOP":
            state["fanout_passes"].append(pass_row);state["fanout_passes"].sort(key=lambda row:(row["fanout_id"].encode("utf-8"),int(row["pass"]),row["expand_occurrence_id"].encode("utf-8")))
            return ["FANOUT_EMPTY"],[],[fanout["id"]]
        pass_row["joined"]=True;state["fanout_passes"].append(pass_row);state["fanout_passes"].sort(key=lambda row:(row["fanout_id"].encode("utf-8"),int(row["pass"]),row["expand_occurrence_id"].encode("utf-8")))
        return [],[],[fanout["id"]]
    projected_obligations=sum(row["status"] in {"OPEN","BLOCKED","WAITING","DISPUTED"} for row in state["obligations"])+len(keys)
    projected_total=int(state["total_activations"])+len(keys)
    target=next(row for row in definition["steps"] if row["id"]==fanout["region_head_step_id"]);event_digest=digest("runtime-event",request["event"]);created=[];obligations=[];all_deadlines=[]
    required_sources=sorted({row["clock_source"] for row in definition["deadlines"] if row["step_id"]==target["id"]},key=str.encode)
    supplied=request["event"].get("activation_clocks",[])
    if [row["source"] for row in supplied] != required_sources:
        if set(row["source"] for row in supplied)-set(required_sources): raise Refusal("DEPENDENCY_MISMATCH")
        return ["ACTIVATION_CLOCK_UNAVAILABLE"],[{"kind":"DEADLINE","deadline_ids":sorted([row["id"] for row in definition["deadlines"] if row["step_id"]==target["id"]],key=str.encode),"reasons":["ACTIVATION_CLOCK_UNAVAILABLE"]}],[fanout["id"]]
    for key in keys:
        counter=next(row for row in state["step_counters"] if row["step_id"]==target["id"]);ordinal=str(int(counter["activations"])+len(created)+1)
        enclosing=copy.deepcopy(source_occurrence["enclosing"])+[{"kind":"FANOUT","construct_id":fanout["id"],"pass":pass_value,"branch_id":None,"object_key":copy.deepcopy(key)}]
        occurrence,deadlines,reasons,detail=_activation_preflight(request,state,source_occurrence,None,target,[source_occurrence["occurrence_id"]],enclosing,supplied,ordinal)
        if reasons:
            return reasons,([] if detail is None else [detail]),[fanout["id"]]
        created.append({"occurrence":occurrence,"activation_event_digest":event_digest,"status":"ACTIVE","deadline_ids":[row["deadline_id"] for row in deadlines]});all_deadlines.extend(deadlines)
        obligations.append(_obligation("FANOUT_OBJECT",fanout["id"],pass_value,[source_occurrence["occurrence_id"]],None,key,fanout["join_step_id"],event_digest,occurrence,target["operation"]))
    limit_failure=None
    if projected_total>int(definition["limits"]["maximum_activations"]):
        limit_failure=("ACTIVATIONS",definition["limits"]["maximum_activations"],projected_total)
    elif projected_obligations>int(definition["limits"]["maximum_active_obligations"]):
        limit_failure=("ACTIVE_OBLIGATIONS",definition["limits"]["maximum_active_obligations"],projected_obligations)
    elif len(keys)>int(definition["limits"]["maximum_fanout_objects"]):
        limit_failure=("FANOUT_OBJECTS",definition["limits"]["maximum_fanout_objects"],len(keys))
    if limit_failure is not None:
        kind,limit,current=limit_failure;state["fanout_passes"].append(pass_row);state["fanout_passes"].sort(key=lambda row:(row["fanout_id"].encode("utf-8"),int(row["pass"]),row["expand_occurrence_id"].encode("utf-8")))
        return ["LIMIT_EXCEEDED"],[{"kind":"LIMIT","limit_kind":kind,"limit":limit,"current":str(current),"step_id":fanout["region_head_step_id"],"relationship_digest":None}],[fanout["id"]]
    pass_row["obligation_ids"]=[row["obligation_id"] for row in obligations];state["fanout_passes"].append(pass_row);state["active"].extend(created);state["obligations"].extend(obligations);state["deadlines"].extend(all_deadlines)
    state["active"].sort(key=lambda row:canonical(row["occurrence"]));state["obligations"].sort(key=lambda row:row["obligation_id"]);state["fanout_passes"].sort(key=lambda row:(row["fanout_id"].encode("utf-8"),int(row["pass"]),row["expand_occurrence_id"].encode("utf-8")))
    state["deadlines"].sort(key=lambda row:(row["due"],canonical(_occurrence_from_state(state,row["occurrence_id"])),row["deadline_id"].encode("utf-8")))
    counter=next(row for row in state["step_counters"] if row["step_id"]==target["id"]);counter["activations"]=str(int(counter["activations"])+len(created));state["total_activations"]=str(projected_total)
    return [],[],[fanout["id"]]


def _direct_basis(request,active,evidence_digest):
    return {"kind":"DIRECT_EVENT","event_digest":digest("runtime-event",request["event"]),"occurrence_id":active["occurrence"]["occurrence_id"],"operation":next(row for row in request["definition"]["steps"] if row["id"]==active["occurrence"]["step_id"])["operation"],"evidence_digest":evidence_digest}


def _discharge_obligation(request,state,active,evidence_digest):
    owning=next((row for row in state["obligations"] if row["expected_occurrence_id"]==active["occurrence"]["occurrence_id"] and row["status"] in {"OPEN","BLOCKED"}),None)
    if owning is not None:
        owning["status"]="DISCHARGED";owning["expected_occurrence_id"]=None;owning["required_operation"]=None;owning["completion_basis"]=_direct_basis(request,active,evidence_digest)
    return owning


def _completion_frontier(state, obligation, seen=None):
    seen=set() if seen is None else seen
    if obligation["obligation_id"] in seen:
        raise Refusal("STATE_INVALID")
    seen.add(obligation["obligation_id"])
    basis=obligation["completion_basis"]
    if basis is None:
        raise Refusal("STATE_INVALID")
    if basis["kind"]=="DIRECT_EVENT":
        return [basis["occurrence_id"]]
    child=basis["child_pass"]
    children=[]
    for obligation_id in child["obligation_ids"]:
        matches=[row for row in state["obligations"] if row["obligation_id"]==obligation_id and row["status"]=="JOINED"]
        if len(matches)!=1:
            raise Refusal("STATE_INVALID")
        children.extend(_completion_frontier(state,matches[0],seen))
    return sorted(set(children),key=str.encode)


def _advance_join(request,state,owning,source_occurrence):
    if owning is None: return None,[],[]
    segment_kind="BRANCH" if owning["kind"]=="PARALLEL_BRANCH" else "FANOUT"
    parent_prefix=[]
    for segment in source_occurrence["enclosing"]:
        if segment["kind"]==segment_kind and segment["construct_id"]==owning["construct_id"]: break
        parent_prefix.append(copy.deepcopy(segment))
    def same_outer(row):
        return canonical(_obligation_outer(state,row))==canonical(parent_prefix)
    siblings=[row for row in state["obligations"] if row["kind"]==owning["kind"] and row["construct_id"]==owning["construct_id"] and row["pass"]==owning["pass"] and same_outer(row)]
    if not siblings or any(row["status"]!="DISCHARGED" for row in siblings): return None,[],[]
    for row in siblings: row["status"]="JOINED"
    join_id=owning["join_step_id"]
    relation=next(row for row in request["definition"]["relationships"] if row["from"]==join_id and row["kind"]=="SEQUENCE")
    frontier=sorted({occurrence_id for row in siblings for occurrence_id in _completion_frontier(state,row)},key=str.encode)
    if owning["kind"]=="FANOUT_OBJECT":
        pass_row=next((row for row in state["fanout_passes"] if row["fanout_id"]==owning["construct_id"] and row["pass"]==owning["pass"] and set(row["obligation_ids"])=={item["obligation_id"] for item in siblings}),None)
        if pass_row is None: raise Refusal("STATE_INVALID")
        pass_row["joined"]=True
        obligation_ids=sorted(pass_row["obligation_ids"],key=str.encode)
    else:
        block=next(row for row in request["definition"]["parallel_blocks"] if row["id"]==owning["construct_id"])
        obligation_ids=sorted((next(item["obligation_id"] for item in siblings if item["branch_id"]==branch["id"]) for branch in block["branches"]),key=str.encode)
    child_pass={"kind":"PARALLEL" if owning["kind"]=="PARALLEL_BRANCH" else "FANOUT","construct_id":owning["construct_id"],"pass":owning["pass"],"outer_enclosing":parent_prefix,"obligation_ids":obligation_ids}
    return relation,frontier,child_pass


def _complete_simple_route(request, state, active, classification, evidence_digest, label, occurred_at, evidence=None):
    definition = request["definition"]
    steps = {row["id"]: row for row in definition["steps"]}
    step = steps[active["occurrence"]["step_id"]]
    if classification == "EXPIRED":
        deadline = next(row for row in definition["deadlines"] if row["step_id"] == step["id"])
        relation = next((row for row in definition["relationships"] if row["kind"] == "EXPIRY" and row["deadline_ref"] == deadline["id"]), None)
        error = None
    else:
        relation, error = _relation_for(definition, step, classification, label)
    selected_digest = None if relation is None else digest("relationship", relation)
    disposition = "EXPIRED" if classification == "EXPIRED" else ("NO_EFFECT" if classification == "NO_EFFECT_ESTABLISHED" else ("FAILED" if classification == "FAILED" else "SUCCEEDED"))
    state["active"] = [row for row in state["active"] if row["occurrence"]["occurrence_id"] != active["occurrence"]["occurrence_id"]]
    state["completed"].append({
        "occurrence": copy.deepcopy(active["occurrence"]), "disposition": disposition,
        "evidence_digest": evidence_digest, "occurred_at": occurred_at,
        "route_label": copy.deepcopy(label) if classification == "MATCHED" else None,
        "selected_relationship_digest": selected_digest, "late": state["status"] != "ACTIVE",
    })
    for deadline in state["deadlines"]:
        if deadline["occurrence_id"] == active["occurrence"]["occurrence_id"] and deadline["status"] == "PENDING":
            deadline["status"] = "DISCHARGED"
    state["completed"].sort(key=lambda row: canonical(row["occurrence"]))
    if state["status"] != "ACTIVE":
        return "OUTCOME_RETAINED", [], []
    owning=next((row for row in state["obligations"] if row["expected_occurrence_id"]==active["occurrence"]["occurrence_id"] and row["status"] in {"OPEN","BLOCKED"}),None)
    route_detail=None
    if step["kind"]=="FANOUT_EXPAND" and classification=="MATCHED":
        reasons,details,constructs=_enter_fanout(request,state,active["occurrence"],evidence)
        route_detail={"kind":"ROUTE","relationship_digests":[],"construct_ids":constructs}
        if reasons:
            if owning is not None: _discharge_obligation(request,state,active,evidence_digest)
            state["status"]="STOPPED";return "STOPPED",reasons,[route_detail,*details]
        fanout=next(row for row in definition["fanouts"] if row["expand_step_id"]==step["id"])
        pass_row=next(row for row in state["fanout_passes"] if row["fanout_id"]==fanout["id"] and row["expand_occurrence_id"]==active["occurrence"]["occurrence_id"])
        if pass_row["object_keys"]:
            if owning is not None:
                owning["status"]="WAITING";owning["expected_occurrence_id"]=None;owning["required_operation"]=None;owning["waiting_on"]={"kind":"FANOUT","construct_id":fanout["id"],"pass":pass_row["pass"],"outer_enclosing":copy.deepcopy(active["occurrence"]["enclosing"]),"obligation_ids":sorted(pass_row["obligation_ids"],key=str.encode)}
            return "COMPLETED",[],[route_detail]
        # COMPOSITION: empty fan-out advance uses the expand occurrence as the structural frontier and
        # continues through the same join, split and operation handling as any other closure.
        relation=next(row for row in definition["relationships"] if row["from"]==fanout["join_step_id"] and row["kind"]=="SEQUENCE")
        route_detail["relationship_digests"]=[digest("relationship",relation)];route_details=[route_detail]
    if route_detail is None and error is not None:
        state["status"] = "STOPPED"
        return "STOPPED", [error], [{"kind":"LABEL","step_id":step["id"],"observed_value":copy.deepcopy(label)}]
    if route_detail is None and classification in {"FAILED", "NO_EFFECT_ESTABLISHED"} and step["failure_behavior"] == "STOP":
        state["status"] = "STOPPED"
        reason = ["DECLARED_FAILURE"] if classification == "FAILED" else ["NO_EFFECT_ESTABLISHED"]
        return "STOPPED", reason, []
    if route_detail is None and classification == "EXPIRED" and relation is None:
        _discharge_obligation(request,state,active,evidence_digest)
        state["status"]="STOPPED"
        return "STOPPED",["EXPIRY_STOP"],[]
    if relation is None:
        raise Refusal("STATE_INVALID")
    target = steps[relation["to"]]
    if route_detail is None:
        route_detail = {"kind":"ROUTE", "relationship_digests":[selected_digest], "construct_ids":[]}
        choice_detail = None
        if classification == "MATCHED" and any(row["step_id"] == step["id"] for row in definition["choices"]):
            choice_detail = {"kind":"LABEL","step_id":step["id"],"observed_value":copy.deepcopy(label)}
        route_details = [route_detail, *([] if choice_detail is None else [choice_detail])]
    if target["kind"] == "TERMINAL":
        if owning is not None:
            _discharge_obligation(request,state,active,evidence_digest)
        if not state["active"] and not any(row["status"] in {"OPEN","BLOCKED","WAITING","DISPUTED"} for row in state["obligations"]):
            state["status"] = "COMPLETE"
        return "FAILED" if classification in {"FAILED", "NO_EFFECT_ESTABLISHED"} else "COMPLETED", [], route_details
    predecessors=[active["occurrence"]["occurrence_id"]];enclosing_override=None;after_direct=None
    if target["kind"] in {"PARALLEL_JOIN","FANOUT_JOIN"}:
        construct = next((row["id"] for row in definition["parallel_blocks"] if row["join_step_id"]==target["id"]),None)
        if construct is None:
            construct = next(row["id"] for row in definition["fanouts"] if row["join_step_id"]==target["id"])
        route_detail["construct_ids"]=sorted(set(route_detail["construct_ids"]+[construct]),key=str.encode)
        owning=_discharge_obligation(request,state,active,evidence_digest)
        after_direct=(copy.deepcopy(state["obligations"]),copy.deepcopy(state["fanout_passes"]))
        join_relation,frontier,joined=_advance_join(request,state,owning,active["occurrence"])
        if join_relation is None:
            return "FAILED" if classification in {"FAILED","NO_EFFECT_ESTABLISHED"} else "COMPLETED",[],route_details
        relation=join_relation;selected_join=digest("relationship",relation);route_detail["relationship_digests"].append(selected_join);route_detail["relationship_digests"].sort(key=str.encode);route_detail["construct_ids"]=sorted(set(route_detail["construct_ids"]+[joined["construct_id"]]),key=str.encode)
        predecessors=frontier;enclosing_override=joined["outer_enclosing"];target=steps[relation["to"]]
        owning=next((row for row in state["obligations"] if row["status"]=="WAITING" and canonical(row["waiting_on"])==canonical(joined)),None)
        while target["kind"] in {"PARALLEL_JOIN","FANOUT_JOIN"}:
            if owning is None: raise Refusal("STATE_INVALID")
            # LIFECYCLE.md:289 names every construct whose join the closure traverses. Reaching an enclosing
            # join through a child join traverses it whether or not it fires, exactly as a direct arrival does.
            reached=next((row["id"] for row in definition["parallel_blocks"] if row["join_step_id"]==target["id"]),None) or next(row["id"] for row in definition["fanouts"] if row["join_step_id"]==target["id"])
            route_detail["construct_ids"]=sorted(set(route_detail["construct_ids"]+[reached]),key=str.encode)
            owning["status"]="DISCHARGED";owning["waiting_on"]=None;owning["completion_basis"]={"kind":"CHILD_PASS","event_digest":digest("runtime-event",request["event"]),"child_pass":copy.deepcopy(joined)}
            join_relation,frontier,joined=_advance_join(request,state,owning,active["occurrence"])
            if join_relation is None:
                return "FAILED" if classification in {"FAILED","NO_EFFECT_ESTABLISHED"} else "COMPLETED",[],route_details
            relation=join_relation;route_detail["relationship_digests"].append(digest("relationship",relation));route_detail["relationship_digests"].sort(key=str.encode);route_detail["construct_ids"]=sorted(set(route_detail["construct_ids"]+[joined["construct_id"]]),key=str.encode)
            predecessors=frontier;enclosing_override=joined["outer_enclosing"];target=steps[relation["to"]]
            owning=next((row for row in state["obligations"] if row["status"]=="WAITING" and canonical(row["waiting_on"])==canonical(joined)),None)
        if target["kind"]=="TERMINAL":
            if not state["active"] and not any(row["status"] in {"OPEN","BLOCKED","WAITING","DISPUTED"} for row in state["obligations"]):state["status"]="COMPLETE"
            return "FAILED" if classification in {"FAILED","NO_EFFECT_ESTABLISHED"} else "COMPLETED",[],route_details
    if target["kind"]=="PARALLEL_SPLIT":
        split_source=active["occurrence"] if enclosing_override is None else {**active["occurrence"],"enclosing":copy.deepcopy(enclosing_override)}
        reasons,details,obligation_ids,constructs=_enter_parallel(request,state,split_source,target,predecessors)
        route_detail["construct_ids"]=sorted(set(route_detail["construct_ids"]+constructs),key=str.encode)
        if reasons:
            if after_direct is not None: state["obligations"],state["fanout_passes"]=after_direct
            if owning is not None:
                _discharge_obligation(request,state,active,evidence_digest)
            state["status"]="STOPPED";return "STOPPED",reasons,[*route_details,*details]
        if owning is not None:
            block=next(row for row in definition["parallel_blocks"] if row["split_step_id"]==target["id"])
            owning["status"]="WAITING";owning["expected_occurrence_id"]=None;owning["required_operation"]=None;owning["waiting_on"]={"kind":"PARALLEL","construct_id":block["id"],"pass":next(row["pass"] for row in state["obligations"] if row["obligation_id"]==obligation_ids[0]),"outer_enclosing":copy.deepcopy(split_source["enclosing"]),"obligation_ids":sorted(obligation_ids,key=str.encode)}
        return "FAILED" if classification in {"FAILED","NO_EFFECT_ESTABLISHED"} else "COMPLETED",[],route_details
    if target["kind"] not in work_class.PROPOSAL:
        raise Refusal("UNSUPPORTED_FEATURE")
    occurrence,deadlines,stop_reasons,limit_detail=_activation_preflight(request,state,active["occurrence"],relation,target,predecessors,enclosing_override)
    if stop_reasons:
        if after_direct is not None: state["obligations"],state["fanout_passes"]=after_direct
        state["status"]="STOPPED"
        details=[*route_details,*([] if limit_detail is None else [limit_detail])]
        deadline_reasons=[reason for reason in stop_reasons if reason.startswith("DEADLINE_") or reason=="ACTIVATION_CLOCK_UNAVAILABLE"]
        if deadline_reasons:
            details.insert(0,{"kind":"DEADLINE","deadline_ids":[row["id"] for row in definition["deadlines"] if row["step_id"]==target["id"]],"reasons":sorted(deadline_reasons,key=str.encode)})
        return "STOPPED",stop_reasons,details
    state["active"].append({"occurrence":occurrence,"activation_event_digest":digest("runtime-event",request["event"]),"status":"ACTIVE","deadline_ids":[row["deadline_id"] for row in deadlines]})
    state["deadlines"].extend(deadlines);state["deadlines"].sort(key=lambda row:(row["due"],canonical(next(item["occurrence"] for item in state["active"]+state["completed"] if item["occurrence"]["occurrence_id"]==row["occurrence_id"])),row["deadline_id"].encode("utf-8")))
    state["active"].sort(key=lambda row: canonical(row["occurrence"]))
    counter = next(row for row in state["step_counters"] if row["step_id"] == target["id"])
    counter["activations"] = str(int(counter["activations"])+1)
    state["total_activations"] = str(int(state["total_activations"])+1)
    if owning is not None:
        owning["status"]="OPEN";owning["expected_occurrence_id"]=occurrence["occurrence_id"];owning["required_operation"]=target["operation"];owning["waiting_on"]=None
    return "FAILED" if classification in {"FAILED", "NO_EFFECT_ESTABLISHED"} else "COMPLETED", [], route_details


def _completion_authorization(request, permit, dispatch, evidence):
    authorization = request["event"]["completion_authorization"]
    if authorization is None:
        raise Refusal("EVIDENCE_UNAVAILABLE")
    native_digest = digest("native-evidence", evidence)
    subject_values = [PIN, request["definition_digest"], request["event"]["instance_id"], permit["occurrence"]["occurrence_id"], permit["permit_id"], dispatch["dispatch_digest"], native_digest]
    subject = {
        "specification_pin": PIN, "work_class_digest": request["definition_digest"],
        "instance_id": request["event"]["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
        "permit_id": permit["permit_id"], "dispatch_digest": dispatch["dispatch_digest"],
        "native_evidence_digest": native_digest,
    }
    if authorization["status"] != "ACCEPTED" or authorization["expires_at"] is None:
        raise Refusal("EVIDENCE_UNAVAILABLE")
    if authorization["organization_id"] != request["state"]["deployment_organization_id"] or authorization["subject_digest"] != digest("no-effect-completion", subject) or authorization["authorization_scope"] != sorted(subject_values, key=str.encode):
        raise Refusal("BINDING_MISMATCH")
    observed = _parse(evidence["observed_at"])
    if _parse(authorization["recorded_at"]) > observed or observed >= _parse(authorization["expires_at"]):
        raise Refusal("EVIDENCE_UNAVAILABLE")


def _project_observed_request(request, dispatch, step, evidence):
    if evidence["status"] != "EFFECT_ESTABLISHED":
        return None
    completion = step["completion"]
    actual_rows = evidence["actual_fields"]
    actual = {}
    for row in actual_rows:
        if row["name"] in actual:
            return None
        actual[row["name"]] = row["value"]
    dispatch_fields = {row["name"]: row["value"] for row in dispatch["native_request"]["fields"]}
    bindings = completion["evidence_bindings"]
    expected = {row["evidence_field"] for row in bindings} | {completion["status_field"]}
    status = actual.get(completion["status_field"])
    if status is None or status["type_ref"] != completion["status_type_ref"]:
        return None
    success = any(canonical(status) == canonical(value) for value in completion["success_values"])
    if success and completion["route_label_field"] is not None:
        expected.add(completion["route_label_field"])
    if set(actual) != expected:
        return None
    types = {row["id"]: row for row in request["definition"]["types"]}
    if any(not work_class._typed(row["value"], types) for row in actual_rows):
        return None
    if any(
        row["request_field"] not in dispatch_fields
        or canonical(actual[row["evidence_field"]]) != canonical(dispatch_fields[row["request_field"]])
        for row in bindings
    ):
        return None
    return copy.deepcopy(evidence["attributed_request"])


def _effect_budget_transition(request, permit, dispatch, step, classification, duplicate_source=None):
    event = request["event"]
    if len(permit["budget_revisions"]) != 1 or len(event["budget_inputs"]) != 1:
        raise Refusal("BINDING_MISMATCH")
    retained_budget = permit["budget_revisions"][0]
    supplied = event["budget_inputs"][0]
    registry_request = supplied["request"]
    configuration = registry_request["state"]["core"]["configuration"]
    registry_digest = digest("reservation-registry", configuration)
    if (
        supplied["registry_digest"] != retained_budget["registry_digest"]
        or supplied["registry_digest"] != registry_digest
        or supplied["affected_anchors"] != retained_budget["affected_anchors"]
        or registry_request["host_evidence"]["registry_digest"] != registry_digest
        or supplied["expected_revision"] != registry_request["state"]["core"]["revision"]
        or supplied["expected_revision"] != registry_request["event"]["expected_revision"]
    ):
        raise Refusal("BINDING_MISMATCH")
    embedded = registry_request["event"]
    reservation_kind = "RELEASE" if event["native_evidence"]["status"] == "NO_EFFECT_ESTABLISHED" else "SETTLE"
    expected_id = digest("lifecycle-reservation-event", {
        "instance_id": event["instance_id"], "lifecycle_event_id": event["event_id"],
        "lifecycle_event_kind": "EFFECT_OBSERVED", "reservation_event_kind": reservation_kind,
        "registry_digest": registry_digest,
    })
    if embedded["id"] != expected_id or embedded["kind"] != reservation_kind:
        raise Refusal("BINDING_MISMATCH")
    clocks = [row for row in request["state"]["clocks"] if row["source"] == configuration["clock_source"] and row["status"] == "AVAILABLE"]
    if not clocks:
        raise Refusal("CLOCK_INVALID")
    latest = max(clocks, key=lambda row: int(row["revision"]))
    if event["clock_revision"] != latest["revision"] or _parse(event["native_evidence"]["observed_at"]) > _parse(latest["observed_time"]):
        raise Refusal("CLOCK_INVALID")
    if canonical(embedded["clock"]) != canonical({"source":latest["source"],"status":"AVAILABLE","instant":latest["observed_time"]}):
        raise Refusal("BINDING_MISMATCH")
    evidence = event["native_evidence"]
    if duplicate_source is not None:
        prior_native = None
        # The registry keeps one record per fact group, under its first evidence identity; a DUPLICATE
        # outcome row never gets a record of its own, so the copy source is found through the fact group.
        fact_group = {row["native_evidence"]["evidence_id"] for row in request["state"]["outcomes"] if _native_fact_digest(row["native_evidence"]) == _native_fact_digest(evidence)}
        for effect in registry_request["state"]["core"]["effects"]:
            if effect["native"]["id"] in fact_group:
                prior_native = copy.deepcopy(effect["native"])
                break
        if prior_native is None:
            raise Refusal("BINDING_MISMATCH")
        prior_native["id"] = evidence["evidence_id"]
        prior_native["evidence_ref"] = evidence["evidence_ref"]
        native = prior_native
    else:
        request_matches = canonical(dispatch["native_request"]) == canonical(permit["native_request"])
        dispatch_receipt = _dispatch_decision(request["state"], dispatch)
        disqualifying = {"NATIVE_ARGUMENT_MISMATCH","PERMIT_EXPIRED","PERMIT_SUPERSEDED","LATE_OR_PROHIBITED_DISPATCH"}
        dispatch_bad = bool(set(dispatch_receipt["reason_codes"]) & disqualifying)
        final_safe = _final_safe_attempt_set(request["state"], permit["permit_id"], dispatch["dispatch_attempt_digest"])
        completion_mismatch = (not request_matches or dispatch_bad or (evidence["status"] == "NO_EFFECT_ESTABLISHED" and not final_safe) or classification in {"UNEXPECTED","CONFLICTING"})
        mismatch_reason = None
        if completion_mismatch:
            mismatch_reason = "NATIVE_REQUEST_MISMATCH" if not request_matches or dispatch_bad else "UNEXPECTED_EFFECT"
        observed_request = _project_observed_request(request, dispatch, step, evidence)
        native = {
            "id":evidence["evidence_id"], "provider":evidence["provider"], "source":evidence["source"],
            "reservation":retained_budget["reservation_id"],
            "outcome":{"EFFECT_ESTABLISHED":"EFFECT","OUTCOME_UNKNOWN":"UNKNOWN","NO_EFFECT_ESTABLISHED":"NO_EFFECT"}[evidence["status"]],
            "request":{"work_class":request["definition"]["id"],"instance":event["instance_id"],"occurrence":permit["occurrence"]["occurrence_id"],"step":permit["occurrence"]["step_id"],"operation":permit["native_request"]["operation"],"interface":permit["native_request"]["interface"],"fields":copy.deepcopy(permit["native_request"]["fields"])},
            "effect_id":evidence["native_operation_id"] if evidence["status"] == "EFFECT_ESTABLISHED" else None,
            "occurred_at":evidence["event_time"] if evidence["status"] == "EFFECT_ESTABLISHED" else None,
            "rules_out_past_and_future_effects":evidence["rules_out_past_and_future_effects"],
            "evidence_ref":evidence["evidence_ref"], "observed_request":observed_request,
            "actual_fields":copy.deepcopy(evidence["actual_fields"]), "collections":copy.deepcopy(evidence["collections"]),
            "completion_mismatch":completion_mismatch, "mismatch_reason":mismatch_reason,
        }
    if embedded["payload"]["native"]["reservation"] != retained_budget["reservation_id"] or canonical(embedded["payload"]["native"]) != canonical(native):
        raise Refusal("BINDING_MISMATCH")
    result = reservation_v2.aggregate_step(registry_request, PIN)
    if result["status"] == "REFUSED":
        raise Refusal(result["code"])
    wrapped = {"registry_digest":registry_digest,"affected_anchors":copy.deepcopy(supplied["affected_anchors"]),"result":result}
    return wrapped, result["receipt"]


def _effect_step(request):
    event = request["event"]; state = copy.deepcopy(request["state"]); evidence = event["native_evidence"]
    status = evidence["status"]
    if status == "EFFECT_ESTABLISHED":
        if evidence["event_time"] is None or evidence["rules_out_past_and_future_effects"]:
            raise Refusal("INPUT_INVALID")
    elif status == "OUTCOME_UNKNOWN":
        if evidence["event_time"] is not None or evidence["actual_fields"] or evidence["collections"] or evidence["rules_out_past_and_future_effects"]:
            raise Refusal("INPUT_INVALID")
    elif evidence["event_time"] is not None or evidence["actual_fields"] or evidence["collections"] or not evidence["rules_out_past_and_future_effects"]:
        raise Refusal("INPUT_INVALID")
    if not event["budget_inputs"] and event["clock_revision"] is not None:
        raise Refusal("CLOCK_INVALID")
    if event["budget_inputs"] and event["clock_revision"] is None:
        raise Refusal("CLOCK_INVALID")
    if event["permit"] is None:
        return _foreign_effect_step(request, state, evidence)
    permit = event["permit"]
    retained_permit = next((row for row in state["permits"] if row["permit_id"] == permit["permit_id"]), None)
    if retained_permit is None:
        raise Refusal("PREREQUISITE_MISSING")
    if canonical(retained_permit) != canonical(permit):
        raise Refusal("BINDING_MISMATCH")
    dispatch = next((row for row in state["dispatches"] if row["dispatch_digest"] == event["dispatch_digest"]), None)
    if dispatch is None or dispatch["permit_digest"] != permit["permit_id"]:
        raise Refusal("BINDING_MISMATCH")
    attributed = evidence["attributed_request"]
    expected_attributed = {"work_class":request["definition"]["id"],"instance":event["instance_id"],"occurrence":permit["occurrence"]["occurrence_id"],"step":permit["occurrence"]["step_id"],"interface":dispatch["native_request"]["interface"],"operation":dispatch["native_request"]["operation"],"fields":copy.deepcopy(dispatch["native_request"]["fields"])}
    if canonical(attributed) != canonical(expected_attributed) or evidence["native_request_digest"] != digest("native-request", attributed):
        raise Refusal("BINDING_MISMATCH")
    step = next(row for row in request["definition"]["steps"] if row["id"] == permit["occurrence"]["step_id"])
    completion = step["completion"]
    triple = (completion["no_effect_provider"],completion["no_effect_source"],completion["no_effect_record_type"]) if status == "NO_EFFECT_ESTABLISHED" else (completion["effect_provider"],completion["effect_source"],completion["effect_record_type"])
    if (evidence["provider"],evidence["source"],evidence["record_type"]) != triple:
        raise Refusal("BINDING_MISMATCH")
    if status == "EFFECT_ESTABLISHED" and step["kind"] == "FANOUT_EXPAND" and len(evidence["collections"]) == 1:
        fanout = next(row for row in request["definition"]["fanouts"] if row["expand_step_id"] == step["id"])
        collection = evidence["collections"][0]
        if collection["name"] == fanout["object_field"] and collection["element_type_ref"] == fanout["object_type_ref"]:
            types = {row["id"]: row for row in request["definition"]["types"]}
            if any(not work_class._typed(value, types) or value["type_ref"] != fanout["object_type_ref"] for value in collection["values"]):
                raise Refusal("INPUT_INVALID")
    attempted = _parse(dispatch["attempt"]["attempted_at"]); observed = _parse(evidence["observed_at"])
    temporal_mismatch = False
    if status in {"OUTCOME_UNKNOWN","NO_EFFECT_ESTABLISHED"} and observed < attempted:
        raise Refusal("INPUT_INVALID")
    if status == "EFFECT_ESTABLISHED" and not (attempted <= _parse(evidence["event_time"]) <= observed):
        temporal_mismatch = True
    receipt = _dispatch_decision(state, dispatch)
    disqualifying = {"NATIVE_ARGUMENT_MISMATCH","PERMIT_EXPIRED","PERMIT_SUPERSEDED","LATE_OR_PROHIBITED_DISPATCH"}
    dispatch_bad = bool(set(receipt["reason_codes"]) & disqualifying)
    not_sent = dispatch["attempt"]["status"] == "NOT_SENT" and dispatch["acknowledgement"]["status"] != "ACCEPTED"
    active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == permit["occurrence"]["occurrence_id"]), None)
    completed = next((row for row in state["completed"] if row["occurrence"]["occurrence_id"] == permit["occurrence"]["occurrence_id"]), None)
    existing_id = next((row for row in state["outcomes"] if row["native_evidence"]["evidence_id"] == evidence["evidence_id"]), None)
    if existing_id is not None and canonical(existing_id["native_evidence"]) != canonical(evidence):
        raise Refusal("INPUT_INVALID")
    fact = _native_fact_digest(evidence)
    same_fact = next((row for row in state["outcomes"] if _native_fact_digest(row["native_evidence"]) == fact), None)
    classification = None; label = None; carrier_classification = None
    if existing_id is not None or same_fact is not None:
        source = existing_id or same_fact
        classification = "DUPLICATE"
        conflicts = copy.deepcopy(source["conflicts_with_evidence_ids"])
        disputed = source["disputed"]
        if existing_id is None and conflicts:
            _extend_duplicate_conflicts(state, source, evidence["evidence_id"])
    else:
        conclusive = status in {"EFFECT_ESTABLISHED","NO_EFFECT_ESTABLISHED"}
        scope = [row for row in state["outcomes"] if row["kind"] == "GOVERNED" and row["permit_digest"] == permit["permit_id"] and row["dispatch_attempt_digest"] == dispatch["dispatch_attempt_digest"]]
        conflicts_rows = [row for row in state["outcomes"] if row["native_evidence"]["native_operation_id"] == evidence["native_operation_id"] and row["native_evidence"]["status"] in {"EFFECT_ESTABLISHED","NO_EFFECT_ESTABLISHED"}]
        conflicts_rows += [row for row in scope if conclusive and row["native_evidence"]["status"] in {"EFFECT_ESTABLISHED","NO_EFFECT_ESTABLISHED"} and row["native_evidence"]["status"] != status]
        conflicts_rows = list({row["outcome_digest"]: row for row in conflicts_rows}.values())
        released = next((row for row in scope if row["classification"] == "NO_EFFECT_ESTABLISHED" and not row["disputed"]), None)
        prior_effects = [row for row in scope if row["native_evidence"]["status"] == "EFFECT_ESTABLISHED"]
        if status == "EFFECT_ESTABLISHED" and released is not None and released["native_evidence"]["native_operation_id"] == evidence["native_operation_id"]:
            classification = "LATE_AFTER_RELEASE"; conflicts_rows = [released]
        elif conclusive and conflicts_rows:
            classification = "CONFLICTING"
        elif status == "EFFECT_ESTABLISHED" and prior_effects:
            classification = "UNEXPECTED"
        elif status == "OUTCOME_UNKNOWN":
            classification = "UNKNOWN"
        elif status == "NO_EFFECT_ESTABLISHED":
            final_safe = _final_safe_attempt_set(state, permit["permit_id"], dispatch["dispatch_attempt_digest"])
            if active is not None and not dispatch_bad:
                _completion_authorization(request, permit, dispatch, evidence)
            elif event["completion_authorization"] is not None:
                raise Refusal("BINDING_MISMATCH")
            if completed is not None or state["status"] == "STOPPED":
                classification = "NO_EFFECT_ESTABLISHED"
            else:
                classification = "NO_EFFECT_ESTABLISHED" if active is not None and final_safe and not dispatch_bad else "UNEXPECTED"
        else:
            classification, label, _ = _completion_fields(step, permit, evidence)
            carrier_classification = classification
            if classification=="MATCHED" and step["kind"]=="FANOUT_EXPAND":
                fanout=next(row for row in request["definition"]["fanouts"] if row["expand_step_id"]==step["id"])
                collections=evidence["collections"]
                if len(collections)!=1 or collections[0]["name"]!=fanout["object_field"] or collections[0]["element_type_ref"]!=fanout["object_type_ref"]:
                    classification="UNEXPECTED"
            # LIFE-010: a DISPUTED dispatch row with DISPATCH_EVIDENCE_CONFLICT cannot support normal completion.
            if dispatch_bad or not_sent or temporal_mismatch or "DISPATCH_EVIDENCE_CONFLICT" in receipt["reason_codes"]:
                classification = "UNEXPECTED"
            elif completed is not None or state["status"] == "STOPPED":
                classification = "LATE_MATCHED" if classification in {"MATCHED","FAILED"} else classification
        if classification not in {"CONFLICTING","LATE_AFTER_RELEASE"}:
            conflicts_rows=[]
        conflicts = sorted({row["native_evidence"]["evidence_id"] for row in conflicts_rows}, key=str.encode)
        disputed = classification in {"UNEXPECTED","CONFLICTING","LATE_AFTER_RELEASE"}
        for row in conflicts_rows:
            row["conflicts_with_evidence_ids"] = sorted(set(row["conflicts_with_evidence_ids"] + [evidence["evidence_id"]]), key=str.encode)
            row["disputed"] = True
            _rehash_outcome(row)
            if row["permit_digest"] is not None:
                prior_permit = next((item for item in state["permits"] if item["permit_id"] == row["permit_digest"]), None)
                if prior_permit is not None and any(item["occurrence"]["occurrence_id"] == prior_permit["occurrence"]["occurrence_id"] for item in state["completed"]):
                    _block_dependents(state, prior_permit["occurrence"]["occurrence_id"])
    budget_results = []
    budget_receipt = None
    if permit["budget_revisions"]:
        wrapped, budget_receipt = _effect_budget_transition(request, permit, dispatch, step, classification, existing_id or same_fact if classification == "DUPLICATE" else None)
        budget_results = [wrapped]
    elif event["budget_inputs"] or event["clock_revision"] is not None:
        raise Refusal("BINDING_MISMATCH")
    receipt_digests = [] if budget_receipt is None else [wrapped["result"]["receipt_digest"]]
    outcome_body = {"kind":"GOVERNED","event_id":event["event_id"],"event_digest":digest("runtime-event",event),"permit_digest":permit["permit_id"],"dispatch_digest":dispatch["dispatch_digest"],"dispatch_attempt_digest":dispatch["dispatch_attempt_digest"],"native_evidence":copy.deepcopy(evidence),"classification":classification,"reservation_receipt_digests":receipt_digests,"conflicts_with_evidence_ids":conflicts,"disputed":disputed or (budget_receipt is not None and budget_receipt["decision"] == "EFFECT_DISPUTED")}
    outcome = _outcome_record(outcome_body)
    if existing_id is None:
        state["outcomes"].append(outcome); state["outcomes"].sort(key=lambda row: row["outcome_digest"])
    if completed is not None and outcome["disputed"] and classification != "DUPLICATE":
        _block_dependents(state, permit["occurrence"]["occurrence_id"])
    effect_detail = {"kind":"EFFECT","classification":classification,"evidence_id":evidence["evidence_id"]}
    details = []
    if budget_receipt is not None:
        details.append({"kind":"BUDGET","registry_digest":wrapped["registry_digest"],"receipt_digest":wrapped["result"]["receipt_digest"],"reasons":copy.deepcopy(budget_receipt["reasons"])})
    details.append(effect_detail)
    reasons_by_class = {"UNKNOWN":["UNKNOWN_OUTCOME"],"NO_EFFECT_ESTABLISHED":["NO_EFFECT_ESTABLISHED"],"UNEXPECTED":["UNEXPECTED_EFFECT"],"CONFLICTING":["CONFLICTING_EFFECT"],"LATE_MATCHED":["LATE_EFFECT"],"LATE_AFTER_RELEASE":["LATE_EFFECT_AFTER_RELEASE"],"DUPLICATE":["DUPLICATE_EVIDENCE"]}
    reasons = reasons_by_class.get(classification, [])
    if classification == "DUPLICATE":
        return _finish(request,state,"OUTCOME_RETAINED",reasons,details,budget_results=budget_results,permit_digest=permit["permit_id"])
    if classification in {"UNEXPECTED","CONFLICTING","LATE_AFTER_RELEASE"}:
        budget_disputed = budget_receipt is not None and budget_receipt["decision"] == "EFFECT_DISPUTED"
        if budget_disputed:
            reasons = sorted(set(reasons + ["BUDGET_EFFECT_DISPUTED", *budget_receipt["reasons"]]), key=str.encode)
        # LIFE-010 places this classification row above the budget-disputed row, which reads
        # "any other budget-backed classification". A disputed budget result reconciles exposure
        # here but does not block the occurrence.
        if active is not None and active["status"] != "BLOCKED_DISPUTE":
            active["status"] = "OUTCOME_UNKNOWN"
        return _finish(request,state,"DISPUTED",reasons,details,budget_results=budget_results,permit_digest=permit["permit_id"])
    if budget_receipt is not None and budget_receipt["decision"] == "EFFECT_DISPUTED":
        reasons = sorted(set(reasons + ["BUDGET_EFFECT_DISPUTED", *budget_receipt["reasons"]]), key=str.encode)
        # LIFE-013: "Unknown or disputed reconciliation also leaves the occurrence BLOCKED_DISPUTE."
        if active is not None and active["status"] != "BLOCKED_DISPUTE":
            active["status"] = "OUTCOME_UNKNOWN" if classification == "UNKNOWN" else "BLOCKED_DISPUTE"
        return _finish(request,state,"DISPUTED",reasons,details,budget_results=budget_results,permit_digest=permit["permit_id"])
    if classification == "UNKNOWN":
        if active is not None and active["status"] != "BLOCKED_DISPUTE": active["status"] = "OUTCOME_UNKNOWN"
        return _finish(request,state,"OUTCOME_RETAINED",reasons,details,budget_results=budget_results,permit_digest=permit["permit_id"])
    if active is not None and active["status"] == "BLOCKED_DISPUTE" and classification in {"MATCHED","FAILED","NO_EFFECT_ESTABLISHED","LATE_MATCHED"}:
        return _finish(request,state,"OUTCOME_RETAINED",sorted(set(reasons+["DEPENDENCY_DISPUTED"]),key=str.encode),details,budget_results=budget_results,permit_digest=permit["permit_id"])
    if classification == "LATE_MATCHED":
        if active is not None and active["status"] != "BLOCKED_DISPUTE":
            _complete_late_occurrence(request,state,active,carrier_classification or "MATCHED",digest("native-evidence",evidence),evidence["event_time"])
        return _finish(request,state,"OUTCOME_RETAINED",reasons,details,budget_results=budget_results,permit_digest=permit["permit_id"])
    if active is None:
        return _finish(request,state,"OUTCOME_RETAINED",reasons,details,budget_results=budget_results,permit_digest=permit["permit_id"])
    if budget_receipt is not None:
        expected_decision = "RELEASED" if classification == "NO_EFFECT_ESTABLISHED" else "SETTLED"
        if budget_receipt["decision"] != expected_decision:
            if classification == "UNKNOWN" and budget_receipt["decision"] == "UNKNOWN":
                active["status"] = "OUTCOME_UNKNOWN"
                return _finish(request,state,"OUTCOME_RETAINED",["UNKNOWN_OUTCOME"],details,budget_results=budget_results,permit_digest=permit["permit_id"])
            raise Refusal("STATE_INVALID")
    if state["status"] == "STOPPED" and active is not None:
        occurred = evidence["observed_at"] if classification == "NO_EFFECT_ESTABLISHED" else evidence["event_time"]
        _complete_late_occurrence(request,state,active,classification,digest("native-evidence",evidence),occurred)
        return _finish(request,state,"OUTCOME_RETAINED",reasons,details,budget_results=budget_results,permit_digest=permit["permit_id"])
    occurred = evidence["observed_at"] if classification == "NO_EFFECT_ESTABLISHED" else evidence["event_time"]
    disposition, route_reasons, route_details = _complete_simple_route(request,state,active,classification,digest("native-evidence",evidence),label,occurred,evidence)
    return _finish(request,state,disposition,reasons + route_reasons,[*details,*route_details],budget_results=budget_results,permit_digest=permit["permit_id"])


def _project_foreign_request(request, step, evidence):
    completion = step["completion"]
    actual = {row["name"]: row["value"] for row in evidence["actual_fields"]}
    bound = {row["evidence_field"]: row["request_field"] for row in completion["evidence_bindings"]}
    ignored = {completion["status_field"], completion["route_label_field"]}
    if len(actual) != len(evidence["actual_fields"]) or any(name not in bound and name not in ignored for name in actual) or any(name not in actual for name in bound):
        return None
    by_request = {request_field: actual[evidence_field] for evidence_field, request_field in bound.items()}
    if any(row["name"] not in by_request for row in step["fields"]):
        return None
    types = {row["id"]: row for row in request["definition"]["types"]}
    fields = [{"name": row["name"], "value": copy.deepcopy(by_request[row["name"]])} for row in step["fields"]]
    if any(row["value"]["type_ref"] != declared["type_ref"] or not work_class._typed(row["value"], types) for row, declared in zip(fields, step["fields"])):
        return None
    observed = {key: copy.deepcopy(evidence["attributed_request"][key]) for key in ("work_class","instance","occurrence","step","operation","interface")}
    observed["fields"] = fields
    return observed


def _foreign_budget_transition(request, step, classification, duplicate_source=None):
    event = request["event"]
    if len(event["budget_inputs"]) != 1 or event["reservation_id"] is None or event["affected_budget_anchors"] != step["shared_budgets"]:
        raise Refusal("BINDING_MISMATCH")
    supplied = event["budget_inputs"][0]; registry_request = supplied["request"]
    configuration = registry_request["state"]["core"]["configuration"]
    registry_digest = digest("reservation-registry", configuration)
    if supplied["registry_digest"] != registry_digest or supplied["affected_anchors"] != step["shared_budgets"] or registry_request["host_evidence"]["registry_digest"] != registry_digest or supplied["expected_revision"] != registry_request["state"]["core"]["revision"] or supplied["expected_revision"] != registry_request["event"]["expected_revision"]:
        raise Refusal("BINDING_MISMATCH")
    embedded = registry_request["event"]
    expected_id = digest("lifecycle-reservation-event", {"instance_id":event["instance_id"],"lifecycle_event_id":event["event_id"],"lifecycle_event_kind":"EFFECT_OBSERVED","reservation_event_kind":"SETTLE","registry_digest":registry_digest})
    if embedded["id"] != expected_id or embedded["kind"] != "SETTLE" or embedded["administration"] is not None:
        raise Refusal("BINDING_MISMATCH")
    clocks = [row for row in request["state"]["clocks"] if row["source"] == configuration["clock_source"] and row["status"] == "AVAILABLE"]
    if not clocks: raise Refusal("CLOCK_INVALID")
    latest = max(clocks,key=lambda row:int(row["revision"]))
    evidence = event["native_evidence"]
    if event["clock_revision"] != latest["revision"] or _parse(evidence["observed_at"]) > _parse(latest["observed_time"]): raise Refusal("CLOCK_INVALID")
    if canonical(embedded["clock"]) != canonical({"source":latest["source"],"status":"AVAILABLE","instant":latest["observed_time"]}): raise Refusal("BINDING_MISMATCH")
    retained = next((row for row in registry_request["state"]["core"]["reservations"] if row["id"] == event["reservation_id"]), None)
    original_request = copy.deepcopy(retained["authority"]["proposal"] if retained is not None else evidence["attributed_request"])
    original_request.pop("schema", None); original_request.pop("work_class_digest", None); original_request.pop("executor", None)
    observed_request = _project_foreign_request(request, step, evidence) if _parse(evidence["event_time"]) <= _parse(evidence["observed_at"]) else None
    native = {"id":evidence["evidence_id"],"provider":evidence["provider"],"source":evidence["source"],"reservation":event["reservation_id"],"outcome":"EFFECT","request":original_request,"effect_id":evidence["native_operation_id"],"occurred_at":evidence["event_time"],"rules_out_past_and_future_effects":False,"evidence_ref":evidence["evidence_ref"],"observed_request":observed_request,"actual_fields":copy.deepcopy(evidence["actual_fields"]),"collections":copy.deepcopy(evidence["collections"]),"completion_mismatch":True,"mismatch_reason":"UNEXPECTED_EFFECT"}
    if canonical(embedded["payload"]["native"]) != canonical(native): raise Refusal("BINDING_MISMATCH")
    result=reservation_v2.aggregate_step(registry_request,PIN)
    if result["status"]=="REFUSED": raise Refusal(result["code"])
    return {"registry_digest":registry_digest,"affected_anchors":copy.deepcopy(supplied["affected_anchors"]),"result":result},result["receipt"]


def _foreign_effect_step(request, state, evidence):
    event=request["event"]
    if evidence["status"] != "EFFECT_ESTABLISHED" or event["dispatch_digest"] is not None or event["completion_authorization"] is not None:
        raise Refusal("INPUT_INVALID")
    attributed=evidence["attributed_request"]
    if attributed["work_class"] != request["definition"]["id"] or attributed["instance"] != event["instance_id"]:
        raise Refusal("BINDING_MISMATCH")
    step=next((row for row in request["definition"]["steps"] if row["id"]==attributed["step"]),None)
    if step is None: raise Refusal("REFERENCE_INVALID")
    if step["kind"] not in work_class.PROPOSAL: raise Refusal("BINDING_MISMATCH")
    fields=[row["name"] for row in attributed["fields"]]
    if attributed["interface"]!=step["interface"] or attributed["operation"]!=step["operation"] or fields != [row["name"] for row in step["fields"]] or any(row["value"]["type_ref"]!=decl["type_ref"] for row,decl in zip(attributed["fields"],step["fields"])):
        raise Refusal("BINDING_MISMATCH")
    if evidence["native_request_digest"] != digest("native-request",attributed): raise Refusal("BINDING_MISMATCH")
    existing_id=next((row for row in state["outcomes"] if row["native_evidence"]["evidence_id"]==evidence["evidence_id"]),None)
    if existing_id is not None and canonical(existing_id["native_evidence"])!=canonical(evidence): raise Refusal("INPUT_INVALID")
    fact=_native_fact_digest(evidence)
    same=next((row for row in state["outcomes"] if _native_fact_digest(row["native_evidence"])==fact),None)
    conflicts_rows=[]
    if existing_id is not None or same is not None:
        source=existing_id or same; classification="DUPLICATE"; conflicts=copy.deepcopy(source["conflicts_with_evidence_ids"])
        if existing_id is None and conflicts:
            _extend_duplicate_conflicts(state,source,evidence["evidence_id"])
    else:
        conflicts_rows=[row for row in state["outcomes"] if row["native_evidence"]["native_operation_id"]==evidence["native_operation_id"] and row["native_evidence"]["status"] in {"EFFECT_ESTABLISHED","NO_EFFECT_ESTABLISHED"}]
        classification="CONFLICTING" if conflicts_rows else "FOREIGN"
        conflicts=sorted({row["native_evidence"]["evidence_id"] for row in conflicts_rows},key=str.encode)
        for row in conflicts_rows:
            row["conflicts_with_evidence_ids"]=sorted(set(row["conflicts_with_evidence_ids"]+[evidence["evidence_id"]]),key=str.encode); row["disputed"]=True
            _rehash_outcome(row)
    budget_results=[];receipt_digests=[];details=[]
    if step["shared_budgets"]:
        wrapped,receipt=_foreign_budget_transition(request,step,classification,existing_id or same if classification=="DUPLICATE" else None)
        budget_results=[wrapped];receipt_digests=[wrapped["result"]["receipt_digest"]]
        details.append({"kind":"BUDGET","registry_digest":wrapped["registry_digest"],"receipt_digest":wrapped["result"]["receipt_digest"],"reasons":copy.deepcopy(receipt["reasons"])})
    elif event["reservation_id"] is not None or event["affected_budget_anchors"] or event["budget_inputs"] or event["clock_revision"] is not None:
        raise Refusal("BINDING_MISMATCH")
    body={"kind":"FOREIGN","event_id":event["event_id"],"event_digest":digest("runtime-event",event),"permit_digest":None,"dispatch_digest":None,"dispatch_attempt_digest":None,"native_evidence":copy.deepcopy(evidence),"classification":classification,"affected_budget_anchors":copy.deepcopy(event["affected_budget_anchors"]),"reservation_receipt_digests":receipt_digests,"conflicts_with_evidence_ids":conflicts,"disputed":True}
    if existing_id is None:
        state["outcomes"].append(_outcome_record(body));state["outcomes"].sort(key=lambda row:row["outcome_digest"])
    details.append({"kind":"EFFECT","classification":classification,"evidence_id":evidence["evidence_id"]})
    reasons=[{"FOREIGN":"FOREIGN_EFFECT","CONFLICTING":"CONFLICTING_EFFECT","DUPLICATE":"DUPLICATE_EVIDENCE"}[classification]]
    disposition="OUTCOME_RETAINED" if classification=="DUPLICATE" else "DISPUTED"
    # LIFE-006's budget-disputed row adds BUDGET_EFFECT_DISPUTED and the receipt reasons to "any
    # non-DUPLICATE effect classification", which reaches FOREIGN and CONFLICTING. The DUPLICATE row
    # takes precedence and fixes the complete set on its own.
    if classification != "DUPLICATE" and budget_results and receipt["decision"] == "EFFECT_DISPUTED":
        reasons = sorted(set(reasons + ["BUDGET_EFFECT_DISPUTED", *receipt["reasons"]]), key=str.encode)
    return _finish(request,state,disposition,reasons,details,budget_results=budget_results)


def step(request):
    if PROFILE_ROLES.get(request["profile"]) != request["role"]:
        raise Refusal("ROLE_UNSUPPORTED")
    if request["specification_pin"] != PIN:
        raise Refusal("VERSION_UNSUPPORTED")
    if request["definition"]["profile"] != request["profile"]:
        raise Refusal("BINDING_MISMATCH")
    definition_digest = work_class.validate(request["definition"])
    if definition_digest != request["definition_digest"]:
        raise Refusal("DIGEST_MISMATCH")
    state = request["state"]
    if state["specification_pin"] != PIN or state["work_class_digest"] != definition_digest or state["profile"] != request["profile"] or state["role"] != request["role"]:
        raise Refusal("BINDING_MISMATCH")
    if not schema_valid(state, "lifecycle.schema.json", "state") or state_digest(state) != request["state_digest"] or not _validate_state_integrity(state, request["definition"]):
        raise Refusal("STATE_INVALID")
    replayed = _replay(request)
    if replayed is not None: return replayed
    event = request["event"]
    if event["instance_id"] != state["instance_id"]:
        raise Refusal("BINDING_MISMATCH")
    if event["expected_state_revision"] != state["revision"] or event["expected_state_digest"] != request["state_digest"]:
        raise Refusal("REVISION_CONFLICT")
    if event["kind"] == "CLOCK": return _clock_step(request)
    if event["kind"] == "PROPOSE": return _proposal_step(request)
    if event["kind"] == "DISPATCH_OBSERVED": return _dispatch_step(request)
    if event["kind"] == "EFFECT_OBSERVED": return _effect_step(request)
    raise Refusal("INPUT_INVALID")


def _deployment_review_evidence(definition, definition_digest, profile, role, authorization_evidence, records, now):
    correspondence = records["correspondence"]; source_confirmation = records["source_confirmation"]; policy_decision = records["policy_decision"]
    subject = {"kind": "WORK_CLASS", "subject_id": definition["id"], "subject_digest": definition_digest, "candidate_identity": "seampoint.work-class/1.0.0-draft.2", "specification_pin": PIN}
    result = evidence_checks._correspondence({"profile": profile, "role": role, "specification_pin": PIN, "subject": subject, "work_class": definition, "work_class_digest": definition_digest, "evidence": correspondence})
    code = None if result["status"] == "EVIDENCE_VALID" else result["code"]
    review_body = {key: value for key, value in correspondence.items() if key != "review"}
    # LIFE-003: every binding condition of the three review records precedes every availability condition.
    if (
        code not in (None, "EVIDENCE_NOT_ACCEPTED")
        or correspondence["review"]["subject_digest"] != digest("correspondence-subject", review_body)
        or source_confirmation["subject_digest"] != digest("work-class-source", definition["source"])
        or source_confirmation["scope_ids"] != definition["source"]["obligations"]
        or policy_decision["subject_digest"] != definition_digest
        or any(not valid_instant(row["recorded_at"]) or _parse(row["recorded_at"]) > now for row in (correspondence, source_confirmation, policy_decision))
        or len({row["evidence_id"] for row in (authorization_evidence, correspondence, source_confirmation, policy_decision)}) != 4
    ):
        raise Refusal("BINDING_MISMATCH")
    if (
        code == "EVIDENCE_NOT_ACCEPTED"
        or any(row["disposition"] == "PENDING" for row in correspondence["residue"])
        or source_confirmation["status"] != "ACCEPTED"
        or policy_decision["status"] != "ACCEPTED"
    ):
        raise Refusal("EVIDENCE_UNAVAILABLE")


def deploy(request):
    profile, role = request["profile"], request["role"]
    if PROFILE_ROLES.get(profile) != role:
        raise Refusal("ROLE_UNSUPPORTED")
    if request["specification_pin"] != PIN:
        raise Refusal("VERSION_UNSUPPORTED")
    definition = request["definition"]
    if definition["profile"] != profile:
        raise Refusal("BINDING_MISMATCH")
    expected_definition = work_class.validate(definition)
    if request["definition_digest"] != expected_definition:
        raise Refusal("DIGEST_MISMATCH")

    authorization = request["deployment_authorization"]
    evidence = request["authorization_evidence"]
    clock = request["authorization_clock"]
    if not valid_instant(clock["observed_time"]):
        raise Refusal("CLOCK_INVALID")
    authorization_body = copy.deepcopy(authorization)
    authorization_body.pop("authorization_evidence_digest")
    subject_digest = digest("deployment-authorization-subject", authorization_body)
    evidence_digest = digest("evidence", evidence)
    expected_bindings = (
        authorization["specification_pin"] == PIN,
        authorization["work_class_digest"] == expected_definition,
        authorization["profile"] == profile,
        authorization["role"] == role,
    )
    if authorization["instance_id"] != request["instance_id"]:
        raise Refusal("DEPENDENCY_MISMATCH")
    if not all(expected_bindings) or authorization["authorization_evidence_digest"] != evidence_digest:
        raise Refusal("BINDING_MISMATCH")
    now = _parse(clock["observed_time"])
    if _parse(authorization["authorized_at"]) > now:
        raise Refusal("EVIDENCE_UNAVAILABLE")
    if authorization["expires_at"] is not None and now >= _parse(authorization["expires_at"]):
        raise Refusal("EVIDENCE_UNAVAILABLE")
    if evidence["status"] != "ACCEPTED":
        raise Refusal("EVIDENCE_UNAVAILABLE")
    if evidence["subject_digest"] != subject_digest or evidence["organization_id"] != authorization["organization_id"]:
        raise Refusal("BINDING_MISMATCH")
    if _parse(evidence["recorded_at"]) > now or evidence["expires_at"] is None or now >= _parse(evidence["expires_at"]):
        raise Refusal("EVIDENCE_UNAVAILABLE")
    scope = sorted([PIN, expected_definition, profile, role, request["instance_id"]], key=str.encode)
    if evidence["authorization_scope"] != scope:
        raise Refusal("BINDING_MISMATCH")
    review_records = {name: request[f"{name}_evidence"] for name in ("correspondence", "source_confirmation", "policy_decision")}
    review_digests = {name: digest("evidence", record) for name, record in review_records.items()}
    if any(authorization[f"{name}_evidence_digest"] != review_digests[name] for name in review_records):
        raise Refusal("BINDING_MISMATCH")
    _deployment_review_evidence(definition, expected_definition, profile, role, evidence, review_records, now)

    deadlines = [row for row in definition["deadlines"] if row["step_id"] == definition["root"]]
    required_sources = sorted({row["clock_source"] for row in deadlines}, key=str.encode)
    initial_clocks = request["initial_clocks"]
    supplied_sources = [row["source"] for row in initial_clocks]
    if supplied_sources != required_sources:
        raise Refusal("EVIDENCE_UNAVAILABLE" if set(supplied_sources) < set(required_sources) else "DEPENDENCY_MISMATCH")
    if any(row["status"] != "AVAILABLE" for row in initial_clocks):
        raise Refusal("EVIDENCE_UNAVAILABLE")
    if any(not valid_instant(row["observed_time"]) for row in initial_clocks):
        raise Refusal("CLOCK_INVALID")
    work_occurrence = _occurrence(PIN, expected_definition, request["instance_id"], definition["root"])
    authorization_digest = digest("deployment-authorization", authorization)
    activation = digest("deployment-activation", {
        "deployment_authorization_digest": authorization_digest,
        "instance_id": request["instance_id"],
        "occurrence_id": work_occurrence["occurrence_id"],
    })
    clock_by_source = {row["source"]: row for row in initial_clocks}
    deadline_states = [_deadline(definition, row, work_occurrence, activation, "0", clock_by_source[row["clock_source"]]) for row in deadlines]
    if any(_due(row, row["activation_instant"]) for row in deadline_states):
        raise Refusal("CLOCK_INVALID")
    proposal_steps = [row["id"] for row in definition["steps"] if row["kind"] in work_class.PROPOSAL]
    state = {
        "schema": "seampoint.work-class/1.0.0-draft.2/work-state",
        "specification_pin": PIN,
        "work_class_digest": expected_definition,
        "profile": profile,
        "role": role,
        "instance_id": request["instance_id"],
        "deployment_authorization": copy.deepcopy(authorization),
        "deployment_authorization_subject_digest": subject_digest,
        "deployment_authorization_digest": authorization_digest,
        "deployment_authorization_evidence": copy.deepcopy(evidence),
        "deployment_authorization_evidence_digest": evidence_digest,
        "deployment_correspondence_evidence": copy.deepcopy(review_records["correspondence"]),
        "deployment_correspondence_evidence_digest": review_digests["correspondence"],
        "deployment_source_confirmation_evidence": copy.deepcopy(review_records["source_confirmation"]),
        "deployment_source_confirmation_evidence_digest": review_digests["source_confirmation"],
        "deployment_policy_decision_evidence": copy.deepcopy(review_records["policy_decision"]),
        "deployment_policy_decision_evidence_digest": review_digests["policy_decision"],
        "deployment_authorization_clock": copy.deepcopy(clock),
        "deployment_organization_id": authorization["organization_id"],
        "revision": "0",
        "status": "ACTIVE",
        "total_activations": "1",
        "total_actuations": "0",
        "step_counters": [{"step_id": step_id, "activations": "1" if step_id == definition["root"] else "0", "actuations": "0"} for step_id in proposal_steps],
        "active": [{"occurrence": work_occurrence, "activation_event_digest": activation, "status": "ACTIVE", "deadline_ids": [row["id"] for row in deadlines]}],
        "completed": [],
        "obligations": [],
        "proposals": [],
        "permits": [],
        "dispatches": [],
        "outcomes": [],
        "clocks": copy.deepcopy(initial_clocks),
        "deadlines": deadline_states,
        "fanout_passes": [],
        "receipts": [],
        "replays": [],
    }
    if not schema_valid(state, "lifecycle.schema.json", "state"):
        raise RuntimeError("deployment constructed an invalid state")
    return {
        "status": "DEPLOYED", "profile": profile, "role": role,
        "instance_id": request["instance_id"], "work_class_digest": expected_definition,
        "deployment_authorization_digest": authorization_digest,
        "state": state, "state_digest": state_digest(state),
    }
