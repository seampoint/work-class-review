#!/usr/bin/env python3
"""Derive exact completion/lookup vectors before consulting either consumer."""

from __future__ import annotations

import copy

from corpus_common import CASES, digest, exact_case, write_canonical_json
from equipment_completion_fixture import (completion_base, completion_dispatch, completion_key_settlement,
    completion_native, lookup_event, lookup_result, seal_lookup, terminal_effect_result)
from equipment_dispatch_fixture import clock_transition, retained
from lifecycle_factory import (governed_effect_event, permitted_proposal, replay_result, stateful_refusal, step_input)


GROUP = CASES / "equipment-completion"


def main():
    base, permitted, dispatched = completion_dispatch()
    cases = []
    def emit(state, event, expected, derivation, *, selected_base=None):
        number = len(cases) + 1
        cases.append(exact_case("C3-EC-" + str(number).zfill(3), "step",
            step_input(selected_base or base, state, event), expected,
            ["LIFE-010", "LIFE-012", "LIFE-013"], derivation))
    def native_event(evidence, prior=dispatched, event_id="completion-effect-1"):
        return governed_effect_event(prior, prior, evidence, event_id=event_id)
    def unexpected(event, prior=dispatched):
        return terminal_effect_result(base, prior, event, classification="UNEXPECTED", disposition="DISPUTED",
            reason_codes=["UNEXPECTED_EFFECT"], occurrence_status="BLOCKED_DISPUTE", disputed=True)

    evidence = completion_native(base, dispatched)
    event = native_event(evidence)
    success = terminal_effect_result(base, dispatched, event, classification="MATCHED", disposition="COMPLETED",
        reason_codes=[], occurrence_status=None, disputed=False, complete_disposition="SUCCEEDED", route=True)
    emit(dispatched["state"], event, success,
        "All eleven required fields match exact nominal types, complete request values, generated identity, event time and qualified approval link. The first effect closes successfully and follows the declared sequence.")
    for field in evidence["actual_fields"]:
        missing = copy.deepcopy(evidence)
        missing["actual_fields"] = [row for row in missing["actual_fields"] if row["name"] != field["name"]]
        missing["record_digest"] = digest("synthetic-provider-fault", {"omitted_field": field["name"]})
        changed = native_event(missing, event_id="completion-missing-" + field["name"])
        emit(dispatched["state"], changed, unexpected(changed),
            "Omitting the declared " + field["name"] + " field retains complete supplied evidence as UNEXPECTED, stops the instance and emits both declared completion referrals.")
    for field_name in ("approval_link", "provider_event_id", "event_timestamp", "amount", "status"):
        wrong = copy.deepcopy(evidence)
        row = next(row for row in wrong["actual_fields"] if row["name"] == field_name)
        row["value"]["type_ref"] = "IDENTITY" if row["value"]["type_ref"] != "IDENTITY" else "STRING"
        wrong["record_digest"] = digest("synthetic-provider-fault", {"wrong_nominal_field": field_name})
        changed = native_event(wrong, event_id="completion-type-" + field_name)
        emit(dispatched["state"], changed, unexpected(changed),
            "The " + field_name + " field retains its scalar spelling under another nominal type. Exact completion requires its declared type and retains this mismatch.")
    for name, mutate, derivation in [
        ("unqualified-approval", lambda row: next(field for field in row["actual_fields"] if field["name"] == "approval_link")["value"].update(value="grant-1"), "An unqualified approval id cannot satisfy the typed provider/source/register/id link."),
        ("wrong-provider-link", lambda row: next(field for field in row["actual_fields"] if field["name"] == "approval_link")["value"].update(value='{"provider":"another-provider","provider_record_id":"grant-1","record_type":"approval","source":"equipment-synthetic-approvals"}'), "The exact approval id under another provider does not identify the declared approval record."),
        ("identity-disagreement", lambda row: row.update(provider_record_id="different-generated-id"), "Top-level provider identity must equal the declared generated-id scalar."),
        ("null-identity", lambda row: row.update(provider_record_id=None), "A null provider identity does not infer a generated event from a field or receipt."),
        ("missing-revision", lambda row: row.pop("provider_revision"), "A missing provider revision cannot establish an exact provider fact."),
        ("null-revision", lambda row: row.update(provider_revision=None), "A null provider revision remains an unproven completion."),
        ("time-disagreement", lambda row: next(field for field in row["actual_fields"] if field["name"] == "event_timestamp")["value"].update(value="2026-09-10T04:29:59Z"), "The event timestamp scalar must equal the top-level provider event_time."),
        ("malformed-time-scalar", lambda row: next(field for field in row["actual_fields"] if field["name"] == "event_timestamp")["value"].update(value="2026-02-30T04:30:00Z"), "A malformed known INSTANT scalar is retained as completion mismatch, without becoming a usable time."),
        ("unknown-nominal", lambda row: next(field for field in row["actual_fields"] if field["name"] == "inspection_id")["value"].update(type_ref="UNDECLARED_ID"), "An unknown nominal type cannot satisfy any completion constant."),
        ("unequal-request", lambda row: next(field for field in row["actual_fields"] if field["name"] == "card_id")["value"].update(value="another-card"), "A changed native request value cannot settle the retained exact request."),
        ("unequal-constant", lambda row: next(field for field in row["actual_fields"] if field["name"] == "work_order_id")["value"].update(value="another-work-order"), "A source-selected completion constant must match exactly."),
        ("extra-field", lambda row: row["actual_fields"].append({"name": "undeclared_extra", "value": {"type_ref": "STRING", "value": "extra"}}), "An undeclared native field is retained as UNEXPECTED rather than silently ignored."),
        ("duplicate-field", lambda row: row["actual_fields"].append(copy.deepcopy(row["actual_fields"][0])), "Two fields with the same name are a terminal mismatch even when their values agree."),
    ]:
        wrong = copy.deepcopy(evidence)
        mutate(wrong)
        wrong["actual_fields"].sort(key=lambda row: row["name"].encode())
        wrong["record_digest"] = digest("synthetic-provider-fault", {"fault": name})
        changed = native_event(wrong, event_id="completion-" + name)
        emit(dispatched["state"], changed, unexpected(changed), derivation)

    current = retained(success, permitted["permit"])
    repeated = copy.deepcopy(evidence)
    repeated.update(evidence_id="completion-receipt-2", evidence_ref="completion-provider-receipt-2", observed_at="2026-09-10T04:30:01Z")
    repeat_event = native_event(repeated, current, "completion-duplicate-1")
    emit(current["state"], repeat_event,
        terminal_effect_result(base, current, repeat_event, classification="DUPLICATE", disposition="OUTCOME_RETAINED",
            reason_codes=["DUPLICATE_EVIDENCE"], occurrence_status=None, disputed=False),
        "A new evidence receipt with the same provider identity and complete native fact is DUPLICATE. Receipt id, reference and observed_at do not create another effect or terminal failure.")
    changed_fact = copy.deepcopy(evidence)
    changed_fact.update(evidence_id="completion-provider-revision-2", provider_revision="provider-revision-2",
        record_digest=digest("provider-native-record", {"changed_revision": "provider-revision-2"}))
    conflict_event = native_event(changed_fact, current, "completion-conflict-1")
    emit(current["state"], conflict_event,
        terminal_effect_result(base, current, conflict_event, classification="CONFLICTING", disposition="DISPUTED",
            reason_codes=["CONFLICTING_EFFECT"], occurrence_status="BLOCKED_DISPUTE", disputed=True,
            conflicts=[evidence["evidence_id"]], update_conflicting_outcomes=True),
        "Changed provider fact under the same record identity is CONFLICTING despite a new evidence receipt. Opaque revision spelling does not select a winner; both original evidence bodies remain retained.")

    failed_evidence = completion_native(base, dispatched, result_value="REJECTED")
    failed_event = native_event(failed_evidence, event_id="completion-declared-failure")
    emit(dispatched["state"], failed_event,
        terminal_effect_result(base, dispatched, failed_event, classification="FAILED", disposition="FAILED",
            reason_codes=["DECLARED_FAILURE"], occurrence_status="BLOCKED_DISPUTE", disputed=False),
        "A declared failed result remains full native evidence, creates DECLARED_COMPLETION_FAILURE and both completion referrals, and creates no retry or success closure.")
    unknown_evidence = completion_native(base, dispatched, status="OUTCOME_UNKNOWN")
    unknown_event = native_event(unknown_evidence, event_id="completion-unknown-1")
    unknown = terminal_effect_result(base, dispatched, unknown_event, classification="UNKNOWN", disposition="OUTCOME_RETAINED",
        reason_codes=["UNKNOWN_OUTCOME"], occurrence_status="OUTCOME_UNKNOWN", disputed=False)
    emit(dispatched["state"], unknown_event, unknown,
        "Unknown native outcome stops the instance while retaining OUTCOME_UNKNOWN and both declared referral intents. It releases no keys and creates no second dispatch permission.")
    no_effect = completion_native(base, dispatched, status="NO_EFFECT_ESTABLISHED")
    no_effect_event = native_event(no_effect, event_id="completion-unsafe-no-effect")
    emit(dispatched["state"], no_effect_event, unexpected(no_effect_event),
        "A SENT invocation with no accepted acknowledgement has no final safe attempt set. Its affirmative no-effect assertion remains UNEXPECTED, grants no retry and releases no capacity.")

    checks = {}
    for status in ("NOT_FOUND", "UNAVAILABLE", "AMBIGUOUS", "OVERFLOW"):
        check = lookup_event(base, dispatched, status=status, event_id="completion-lookup-" + status.lower())
        checked = lookup_result(base, dispatched, check)
        checks[status] = check, retained(checked, permitted["permit"])
        emit(dispatched["state"], check, checked,
            "A bound " + status + " lookup retains the full provider assertion, complete check/terminal/referral records and receipt bindings, stops work, and creates no synthetic native event or registry settlement.")
    for name, kwargs, derivation in [
        ("incomplete", {"coverage": "INCOMPLETE"}, "An admitted incomplete zero-candidate lookup adds LOOKUP_INCOMPLETE; it never establishes absence or releases capacity."),
        ("stale", {"as_of": "2026-09-10T04:29:59Z"}, "A valid earlier provider as_of adds LOOKUP_STALE under the zero-freshness declaration; it cannot establish current absence."),
    ]:
        check = lookup_event(base, dispatched, event_id="completion-lookup-" + name, **kwargs)
        emit(dispatched["state"], check, lookup_result(base, dispatched, check), derivation)
    reference = checks["NOT_FOUND"][0]
    for name, mutate, reseal in [
        ("wrong-key", lambda row: row["lookup"]["query"]["key"][0]["value"].update(value="forged-key"), True),
        ("wrong-provider", lambda row: row["lookup"]["query"].update(provider="another-provider"), True),
        ("wrong-dispatch", lambda row: row.update(dispatch_digest=digest("invented-dispatch", {})), False),
        ("wrong-authorization", lambda row: row.update(authorization_digest=digest("invented-authorization", {})), False),
        ("forged-query-digest", lambda row: row["lookup"].update(query_digest=digest("invented-query", {})), False),
        ("forged-provenance", lambda row: row["lookup"].update(provenance_digest=digest("invented-provenance", {})), False),
        ("future-as-of", lambda row: row["lookup"].update(as_of="2026-09-10T04:30:01Z"), True),
        ("wrong-observed-at", lambda row: row["lookup"].update(observed_at="2026-09-10T04:29:59Z"), True),
    ]:
        check = copy.deepcopy(reference)
        check["event_id"] = "completion-lookup-" + name
        mutate(check)
        if reseal:
            seal_lookup(check["lookup"])
        emit(dispatched["state"], check, stateful_refusal(dispatched["state"], "BINDING_MISMATCH"),
            "The " + name + " fault refuses before lookup policy or mutation, even when the supplied lookup hashes are internally rebound.")
    for name, mutate, code in [
        ("duplicate-candidate", lambda row: row["lookup"]["candidates"].__setitem__(1, copy.deepcopy(row["lookup"]["candidates"][0])), "BINDING_MISMATCH"),
        ("reordered-candidates", lambda row: row["lookup"]["candidates"].reverse(), "BINDING_MISMATCH"),
        ("candidate-provider", lambda row: row["lookup"]["candidates"][0].update(source="another-register"), "BINDING_MISMATCH"),
        ("too-many-candidates", lambda row: row["lookup"]["candidates"].append({**copy.deepcopy(row["lookup"]["candidates"][-1]), "provider_record_id": "provider-event-999"}), "SCHEMA_INVALID"),
    ]:
        check = copy.deepcopy(checks["OVERFLOW" if name == "too-many-candidates" else "AMBIGUOUS"][0])
        check["event_id"] = "completion-lookup-" + name
        mutate(check)
        seal_lookup(check["lookup"])
        expected = {"status": "REFUSED", "code": code, "path": ""} if code == "SCHEMA_INVALID" else stateful_refusal(dispatched["state"], code)
        emit(dispatched["state"], check, expected,
            "The " + name + " inventory cannot be silently normalized into a usable bounded candidate assertion.")

    for attempt in ("UNKNOWN", "REJECTED", "NOT_SENT"):
        selected, selected_permit, prior = completion_dispatch(attempt)
        check = lookup_event(selected, prior, event_id="completion-after-" + attempt.lower())
        expected = stateful_refusal(prior["state"], "PREREQUISITE_MISSING") if attempt == "NOT_SENT" else lookup_result(selected, prior, check)
        emit(prior["state"], check, expected,
            "Safe NOT_SENT without accepted acknowledgement cannot support completion investigation." if attempt == "NOT_SENT" else
            "A timely " + attempt + " dispatch may have invoked the connector and remains eligible for a bound lookup.", selected_base=selected)
    selected, selected_permit, prior = completion_dispatch("NOT_SENT", acknowledgement_status="ACCEPTED")
    check = lookup_event(selected, prior, event_id="completion-after-accepted-ack")
    emit(prior["state"], check, lookup_result(selected, prior, check),
        "An accepted acknowledgement makes the exact retained invocation eligible for lookup despite a NOT_SENT attempt assertion.", selected_base=selected)
    original_check, checked = checks["NOT_FOUND"]
    emit(checked["state"], original_check, replay_result(checked["state"], original_check["event_id"]),
        "Exact completion-check replay returns the original full decision and portable records without another stop or referral.")
    new_check = lookup_event(base, checked, event_id="completion-lookup-again")
    emit(checked["state"], new_check, stateful_refusal(checked["state"], "PREREQUISITE_MISSING"),
        "One admitted completion lookup consumes the occurrence's lookup eligibility. A new event cannot repeat the investigation.")
    conclusive_check = lookup_event(base, current, event_id="completion-after-conclusive")
    emit(current["state"], conclusive_check, stateful_refusal(current["state"], "PREREQUISITE_MISSING"),
        "A conclusive native effect blocks a first COMPLETION_CHECKED. The result must enter the native effect path.")
    unknown_prior = retained(unknown, permitted["permit"])
    check = lookup_event(base, unknown_prior, event_id="completion-after-native-unknown")
    emit(unknown_prior["state"], check, lookup_result(base, unknown_prior, check),
        "Retained UNKNOWN evidence does not block the first lookup. Its original terminal cause and referral history remain unchanged.")
    _, aged = clock_transition(dispatched, instant="2026-09-10T04:31:01Z")
    check = lookup_event(base, aged, event_id="completion-after-authorization-expiry")
    emit(aged["state"], check, lookup_result(base, aged, check),
        "Investigation binds the historical authorization used by the dispatch after that authorization expired. It grants no renewed permission.")
    late_evidence = completion_native(base, checked, evidence_id="completion-late-exact")
    late_event = native_event(late_evidence, checked, "completion-late-exact-event")
    emit(checked["state"], late_event,
        terminal_effect_result(base, checked, late_event, classification="LATE_MATCHED", disposition="OUTCOME_RETAINED",
            reason_codes=["LATE_EFFECT"], occurrence_status=None, disputed=False, complete_disposition="SUCCEEDED"),
        "Late exact evidence closes a retained unknown occurrence with late=true, retains the original terminal cause and referrals, leaves the instance STOPPED and creates no route.")
    _, blocked = checks["AMBIGUOUS"]
    late_event = native_event(late_evidence, blocked, "completion-late-exact-blocked")
    emit(blocked["state"], late_event,
        terminal_effect_result(base, blocked, late_event, classification="LATE_MATCHED", disposition="OUTCOME_RETAINED",
            reason_codes=["DEPENDENCY_DISPUTED", "LATE_EFFECT"], occurrence_status="BLOCKED_DISPUTE", disputed=False),
        "Late exact evidence cannot clear an earlier ambiguous dispute. The occurrence stays BLOCKED_DISPUTE and the original stop/referrals remain portable.")
    proposal = copy.deepcopy(base["proposal_event"])
    proposal.update(event_id="completion-propose-after-stop", expected_state_revision=checked["state"]["revision"], expected_state_digest=checked["state_digest"])
    emit(checked["state"], proposal, stateful_refusal(checked["state"], "INSTANCE_NOT_ACTIVE"),
        "Completion terminalization forbids a new proposal before refreshed authority or connector authorization can create new work.")

    keyed_base, keyed_permit, keyed_dispatch = completion_dispatch(exclusive_keys=True)
    keyed_check = lookup_event(keyed_base, keyed_dispatch, event_id="completion-key-unknown")
    keyed_stop = retained(lookup_result(keyed_base, keyed_dispatch, keyed_check), keyed_permit["permit"])
    emit(keyed_dispatch["state"], keyed_check, keyed_stop | {"permit": None},
        "A possibly sent key-backed lookup failure retains the exact original reservation basis in its terminal record, with no registry transition and no released or consumed key.", selected_base=keyed_base)
    keyed_native = completion_native(keyed_base, keyed_stop, evidence_id="completion-key-late-exact")
    keyed_event = governed_effect_event(keyed_stop, keyed_stop, keyed_native, event_id="completion-key-late-exact-event", clock_revision="1")
    supplied, registry_result = completion_key_settlement(keyed_base, keyed_stop, keyed_event)
    keyed_event["budget_inputs"] = [supplied]
    emit(keyed_stop["state"], keyed_event,
        terminal_effect_result(keyed_base, keyed_stop, keyed_event, classification="LATE_MATCHED", disposition="OUTCOME_RETAINED",
            reason_codes=["LATE_EFFECT"], occurrence_status=None, disputed=False, complete_disposition="SUCCEEDED", budget_results=[registry_result]),
        "Exact attributable late evidence consumes the full held key set atomically through SETTLE, closes the unknown occurrence with late=true, preserves the initial stop/referrals and never reopens or routes work.", selected_base=keyed_base)

    before_dispatch = copy.deepcopy(reference)
    before_dispatch.update(event_id="completion-before-dispatch", expected_state_revision=permitted["state"]["revision"],
        expected_state_digest=permitted["state_digest"])
    emit(permitted["state"], before_dispatch, stateful_refusal(permitted["state"], "PREREQUISITE_MISSING"),
        "A permitted request has no retained dispatch attempt. A caller-supplied query cannot invent the missing invocation prerequisite.")
    for name, provider_id, revision, derivation in [
        ("changed-record-bytes", "provider-event-1", "provider-revision-1", "Changing only complete provider record bytes under the same provider identity is CONFLICTING even when the provider revision remains unchanged."),
        ("second-generated-event", "provider-event-2", "provider-revision-1", "A second provider record identity for the same native operation is additional execution evidence. It remains CONFLICTING despite matching request and result fields."),
    ]:
        changed_fact = copy.deepcopy(evidence)
        changed_fact.update(evidence_id=name, provider_record_id=provider_id, provider_revision=revision,
            record_digest=digest("provider-native-record", {"fact": name}))
        next(row for row in changed_fact["actual_fields"] if row["name"] == "provider_event_id")["value"]["value"] = provider_id
        changed_event = native_event(changed_fact, current, "completion-" + name)
        emit(current["state"], changed_event,
            terminal_effect_result(base, current, changed_event, classification="CONFLICTING", disposition="DISPUTED",
                reason_codes=["CONFLICTING_EFFECT"], occurrence_status="BLOCKED_DISPUTE", disputed=True,
                conflicts=[evidence["evidence_id"]], update_conflicting_outcomes=True), derivation)

    changed_candidate = copy.deepcopy(checks["AMBIGUOUS"][0])
    changed_candidate["event_id"] = "completion-candidate-identity-collision"
    changed_candidate["lookup"]["candidates"][1].update(provider_record_id=changed_candidate["lookup"]["candidates"][0]["provider_record_id"],
        record_digest=digest("provider-native-record", {"changed_bytes": "same-provider-identity"}))
    changed_candidate["lookup"]["candidates"].sort(key=lambda row: (row["provider"],row["source"],row["record_type"],row["provider_record_id"]))
    seal_lookup(changed_candidate["lookup"])
    emit(dispatched["state"], changed_candidate, stateful_refusal(dispatched["state"], "BINDING_MISMATCH"),
        "Two candidate rows cannot repeat one provider record identity under different digests. Complete row inequality does not make the identities unique.")

    for case in cases:
        write_canonical_json(GROUP / (case["id"] + ".json"), case)
    print({"group": str(GROUP), "cases": len(cases), "derivation": "normative constructors only; consumers not consulted"})


if __name__ == "__main__":
    main()
