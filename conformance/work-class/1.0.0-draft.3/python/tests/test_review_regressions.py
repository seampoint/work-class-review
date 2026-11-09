from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT.parent / "review")]

from consumer import Consumer
from implementation import authority, dispatch_gate, exclusive_history, lifecycle, reference_host, reservation_v2, source_observations
from implementation.common import PIN, Refusal, canonical, digest
from equipment_correction_fixture import correction_fixture, rebind_authority, seal_correction
from equipment_history_fixture import history_fixture
from equipment_completion_fixture import completion_authority_mutator, completion_definition_mutator, completion_native, lookup_event
from equipment_dispatch_fixture import authorization_event
from equipment_observation_fixture import refresh
from fixture_factory import available_clock
from lifecycle_factory import base_lifecycle, dispatch_event, governed_effect_event
from test_dispatch_gate import bind_event
from test_foundations import linear_deploy_request


def rebind_original_permit(request):
    permit = request["original_permit"]
    basis, _ = rebind_authority(permit["authority_basis"])
    result = Consumer().evaluate({"kind": "AUTHORITY", "request": basis})
    if result["status"] != "READY_FOR_RESERVATION":
        raise AssertionError(result)
    permit.update(authority_basis=basis, authority_result=result,
                  authority_result_digest=digest("authority-result", result),
                  authority_evidence_digest=result["evidence_digest"],
                  observation_digests=sorted(digest("authority-observation", row) for row in basis["observations"]))
    permit["authority_act_bases"] = sorted([
        {"act_digest": digest("authority-act", row), "act": copy.deepcopy(row)}
        for row in basis["acts"] if digest("authority-act", row) in result["act_digests"]
    ], key=lambda row: row["act_digest"])
    permit["permit_id"] = digest("permit", {name: value for name, value in permit.items() if name != "permit_id"})


def append_authorization(request):
    state, event = copy.deepcopy(request["state"]), request["event"]
    permit, fresh = event["permit"], event["authority_input"]
    result = Consumer().evaluate({"kind": "AUTHORITY", "request": fresh})
    result_digest = digest("authority-result", result)
    authorization, details, reasons = None, [], []
    disposition = "WITHHELD"
    if result["status"] == "READY_FOR_RESERVATION":
        checked = fresh["clock"]["instant"]
        gate = dispatch_gate.step_definition(request["definition"], permit)["dispatch_gate"]
        end = dispatch_gate.expiry(permit, fresh, gate, checked)
        fence = dispatch_gate.fence(event, result, gate, checked, end)
        previous = dispatch_gate.head(state, permit["permit_id"])
        authorization = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": permit["permit_id"],
                         **{name: copy.deepcopy(event[name]) for name in ("native_request", "connector", "observation_digests", "clock_revision", "dispatch_intent_id", "authority_input")},
                         "authorization_fence": fence, "authority_result": result, "authority_result_digest": result_digest,
                         "expires_at": end, "supersedes_authorization_digest": None if previous is None else previous["authorization_digest"]}
        authorization["authorization_digest"] = digest("dispatch-authorization", authorization)
        state["authorizations"].append(authorization)
        state["authorizations"].sort(key=lambda row: row["authorization_digest"])
        disposition = "AUTHORIZED"
        details = [{"kind": "AUTHORIZATION", "authorization_digest": authorization["authorization_digest"], "permit_digest": permit["permit_id"], "approval_id": fence["approval_id"], "checked_at": checked, "expires_at": end, "sources": fence["sources"]}]
    else:
        if result["code"] in dispatch_gate.ADMISSION_CODES:
            raise AssertionError(result)
        reasons = sorted(set(["AUTHORITY_REQUIRED", result["code"], *result["reasons"]]), key=str.encode)
        details = [{"kind": "AUTHORITY", "authority_result_digest": result_digest, "code": result["code"], "reasons": result["reasons"], "failed_checks": result["failed_checks"]}]
    evaluation = {"event_id": event["event_id"], "event_digest": digest("runtime-event", event), "permit_digest": permit["permit_id"],
                  **{name: copy.deepcopy(event[name]) for name in ("dispatch_intent_id", "clock_revision", "authority_input")},
                  "authority_result": result, "authority_result_digest": result_digest,
                  "authorization_digest": None if authorization is None else authorization["authorization_digest"], "disposition": disposition}
    evaluation["evaluation_digest"] = digest("dispatch-authorization-evaluation", evaluation)
    state["authorization_evaluations"].append(evaluation)
    state["authorization_evaluations"].sort(key=lambda row: row["event_id"].encode())
    return lifecycle._finish(request, state, disposition, reasons, details, authority_result_digest=result_digest,
                             permit_digest=permit["permit_id"], authorization_evaluation_digest=evaluation["evaluation_digest"])


def dispatch_record(event, attempt_digest):
    body = {"dispatch_attempt_digest": attempt_digest, "event_id": event["event_id"],
            "event_digest": digest("runtime-event", event), "permit_digest": event["permit"]["permit_id"],
            **{name: copy.deepcopy(event[name]) for name in ("native_request", "connector", "attempt", "acknowledgement", "clock_revision")}}
    if event.get("authorization_digest") is not None:
        body["authorization_digest"] = event["authorization_digest"]
    return {"dispatch_digest": digest("dispatch", body), **body}


class ReviewRegressionTests(unittest.TestCase):
    def test_acknowledgement_progression_uses_receipt_order_for_both_digest_orders(self):
        consumer = Consumer()
        for gated in (False, True):
            for pending, conclusive in (("NONE", "ACCEPTED"), ("UNKNOWN", "REJECTED")):
                for digest_before in (False, True):
                    with self.subTest(gated=gated, pending=pending, digest_before=digest_before):
                        base = base_lifecycle(definition_mutator=completion_definition_mutator, authority_mutator=completion_authority_mutator) if gated else base_lifecycle()
                        deployment = base["deploy_input"]
                        request = {name: deployment[name] for name in ("specification_pin", "definition", "definition_digest", "profile", "role")}
                        deployed = consumer.deploy(deployment)
                        clocked = consumer.step(bind_event({**request, "event": base["clock_event"]}, deployed["state"]))
                        permitted = consumer.step(bind_event({**request, "event": base["proposal_event"]}, clocked["state"]))
                        prior, authorization_digest = permitted, None
                        if gated:
                            prior = consumer.step(bind_event({**request, "event": authorization_event(base, permitted)}, permitted["state"]))
                            authorization_digest = prior["state"]["authorizations"][0]["authorization_digest"]
                        event = dispatch_event(base, {**prior, "permit": permitted["permit"]}, event_id="digest-order-send", acknowledgement_status=pending, authorization_digest=authorization_digest)
                        event = bind_event({**request, "event": event}, prior["state"])["event"]
                        dispatched = consumer.step({**request, "state": prior["state"], "state_digest": prior["state_digest"], "event": event})
                        self.assertEqual(dispatched["status"], "STEP")
                        original = dispatched["state"]["dispatches"][0]
                        update = copy.deepcopy(event)
                        update["acknowledgement"] = {"status": conclusive, "observed_at": event["attempt"]["attempted_at"], "reference": "digest-order-ack"}
                        for nonce in range(1024):
                            update["event_id"] = "digest-order-ack-" + str(nonce)
                            supplied = bind_event({**request, "event": update}, dispatched["state"])
                            record = dispatch_record(supplied["event"], original["dispatch_attempt_digest"])
                            if (record["dispatch_digest"] < original["dispatch_digest"]) == digest_before:
                                break
                        else:
                            self.fail("could not construct both canonical digest orders")
                        acknowledged = consumer.step(supplied)
                        self.assertEqual(acknowledged["status"], "STEP")
                        self.assertTrue(lifecycle._validate_state_integrity(acknowledged["state"], request["definition"]))
                        second = copy.deepcopy(update)
                        second["event_id"] = "second-conclusive-ack"
                        second["acknowledgement"] = {"status": "REJECTED" if conclusive == "ACCEPTED" else "ACCEPTED", "observed_at": event["attempt"]["attempted_at"], "reference": "second-conclusion"}
                        rejected = consumer.step(bind_event({**request, "event": second}, acknowledged["state"]))
                        self.assertEqual(rejected.get("code"), "PREREQUISITE_MISSING")
                        supplied = bind_event({**request, "event": second}, acknowledged["state"])
                        state = copy.deepcopy(acknowledged["state"])
                        state["dispatches"].append(dispatch_record(supplied["event"], original["dispatch_attempt_digest"]))
                        state["dispatches"].sort(key=lambda row: row["dispatch_digest"])
                        disposition, reasons = lifecycle._dispatch_base(second["attempt"], second["acknowledgement"])
                        forged = lifecycle._finish(supplied, state, disposition, reasons, [{"kind": "DISPATCH", "attempt_id": second["attempt"]["attempt_id"], "reasons": reasons}], permit_digest=permitted["permit"]["permit_id"])
                        self.assertFalse(lifecycle._validate_state_integrity(forged["state"], request["definition"]))

    def test_restart_rejects_authorization_after_expiry_supersession_completion_or_lookup(self):
        consumer = Consumer()
        for context in ("expiry", "supersession", "completion", "lookup"):
            with self.subTest(context=context):
                base = base_lifecycle(definition_mutator=completion_definition_mutator, authority_mutator=completion_authority_mutator)
                deployment = base["deploy_input"]
                request = {name: deployment[name] for name in ("specification_pin", "definition", "definition_digest", "profile", "role")}
                deployed = consumer.deploy(deployment)
                clocked = consumer.step(bind_event({**request, "event": base["clock_event"]}, deployed["state"]))
                permitted = consumer.step(bind_event({**request, "event": base["proposal_event"]}, clocked["state"]))
                self.assertEqual(permitted["decision"]["disposition"], "PERMITTED")
                permit = permitted["permit"]
                if context in {"expiry", "supersession"}:
                    clock = {**base["clock_event"], "event_id": "exclusive-permit-expiry", "clock": available_clock(permit["clock_source"], "2", permit["expires_at"])}
                    prior = consumer.step(bind_event({**request, "event": clock}, permitted["state"]))
                    if context == "supersession":
                        renewal = copy.deepcopy(base["proposal_event"])
                        renewal.update(event_id="renew-expired-permit", clock_revision="2", authority_input=refresh(permit["authority_basis"], permit["expires_at"], evaluation_point="PROPOSE"))
                        renewal["observation_digests"] = dispatch_gate.observation_digests(renewal["authority_input"])
                        prior = consumer.step(bind_event({**request, "event": renewal}, prior["state"]))
                        self.assertEqual(prior["permit"]["supersedes_permit_digest"], permit["permit_id"])
                        unavailable = {**clock, "event_id": "unavailable-after-renewal", "clock": {"source": permit["clock_source"], "revision": "3", "status": "UNAVAILABLE", "observed_time": None, "evidence_digest": digest("unavailable-clock", {})}}
                        prior = consumer.step(bind_event({**request, "event": unavailable}, prior["state"]))
                else:
                    authorized = consumer.step(bind_event({**request, "event": authorization_event(base, permitted)}, permitted["state"]))
                    current = {**authorized, "permit": permit}
                    event = dispatch_event(base, current, event_id="completion-context-dispatch", attempt_status="SENT", authorization_digest=authorized["state"]["authorizations"][0]["authorization_digest"])
                    prior = consumer.step(bind_event({**request, "event": event}, authorized["state"]))
                    current = {**prior, "permit": permit}
                    if context == "lookup":
                        event = lookup_event(base, current, event_id="complete-lookup-before-authorization")
                    else:
                        native = completion_native(base, current)
                        event = governed_effect_event(permitted, current, native, event_id="complete-before-authorization")
                    prior = consumer.step(bind_event({**request, "event": event}, prior["state"]))
                    self.assertEqual(prior["status"], "STEP")
                    self.assertEqual(prior["state"]["status"], "STOPPED" if context == "lookup" else "COMPLETE")
                self.assertTrue(lifecycle._validate_state_integrity(prior["state"], request["definition"]))
                fresh = None
                if context == "supersession":
                    fresh = copy.deepcopy(permit["authority_basis"])
                    fresh.update(evaluation_point="DISPATCH", clock={"source": permit["clock_source"], "status": "UNAVAILABLE", "instant": None})
                event = authorization_event(base, {"state": prior["state"], "permit": permit}, event_id="ineligible-authorization-" + context, intent="ineligible-intent-" + context, authority_input=fresh)
                attempted = bind_event({**request, "event": event}, prior["state"])
                self.assertEqual(consumer.step(attempted).get("code"), "PREREQUISITE_MISSING")
                forged = append_authorization(attempted)
                self.assertFalse(lifecycle._validate_state_integrity(forged["state"], request["definition"]))

    def test_gate_declaration_faults_follow_static_refusal_precedence(self):
        base = base_lifecycle(definition_mutator=completion_definition_mutator, authority_mutator=completion_authority_mutator)
        original = base["authority_input"]
        self.assertIsNone(source_observations.declaration_admission(original["work_class"], original["envelope"]))
        gate = original["work_class"]["steps"][0]["dispatch_gate"]
        for member, value in (("purpose", "COMPLETION"), ("freshness_seconds", "1"), ("evaluation_point", "PROPOSE"), ("record_id", None)):
            with self.subTest(member=member):
                changed = copy.deepcopy(original)
                requirement = next(row for row in changed["envelope"]["source_observation_requirements"] if row["id"] == gate["approval_requirement"])
                requirement[member] = value
                self.assertEqual(source_observations.declaration_admission(changed["work_class"], changed["envelope"]), "UNSUPPORTED_RELATION")
        changed = copy.deepcopy(original)
        next(row for row in changed["envelope"]["source_observation_requirements"] if row["id"] == gate["approval_requirement"])["freshness_seconds"] = "1"
        changed["work_class"]["steps"][0]["dispatch_gate"]["withdrawal_requirement"] = "missing-requirement"
        self.assertEqual(source_observations.declaration_admission(changed["work_class"], changed["envelope"]), "UNSUPPORTED_RELATION")
        changed = copy.deepcopy(original)
        next(row for row in changed["envelope"]["source_observation_requirements"] if row["id"] == gate["approval_requirement"])["freshness_seconds"] = "1"
        next(row for row in changed["work_class"]["types"] if row["kind"] == "IDENTITY")["nonnegative"] = True
        self.assertEqual(Consumer().evaluate({"kind": "AUTHORITY", "request": changed}).get("code"), "TYPE_INVALID")
        definition = {"schema": "seampoint.work-class/1.0.0-draft.3/authority-definition", **{name: changed[name] for name in ("source", "work_class", "envelope")}}
        self.assertEqual(authority.validate_definition(definition).get("code"), "TYPE_INVALID")

    def test_gate_fault_does_not_mask_missing_capacity_or_provider_dependency(self):
        base = base_lifecycle(definition_mutator=completion_definition_mutator, authority_mutator=completion_authority_mutator)
        original = base["authority_input"]
        self.assertEqual(Consumer().evaluate({"kind": "AUTHORITY", "request": original})["status"], "READY_FOR_RESERVATION")
        for fault, code in (("capacity", "EVIDENCE_UNAVAILABLE"), ("provider", "DEPENDENCY_MISMATCH")):
            with self.subTest(fault=fault):
                changed = copy.deepcopy(original)
                gate = changed["work_class"]["steps"][0]["dispatch_gate"]
                requirement = next(row for row in changed["envelope"]["source_observation_requirements"] if row["id"] == gate["approval_requirement"])
                requirement["freshness_seconds"] = "1"
                if fault == "provider":
                    requirement["provider"] = "unselected-provider"
                source_digest = digest("authority-source", changed["source"])
                work_digest = digest("authority-work-class", changed["work_class"])
                changed["envelope"].update(source_digest=source_digest, work_class_digest=work_digest)
                envelope_digest = digest("authority-envelope", changed["envelope"])
                changed["proposal"]["work_class_digest"] = work_digest
                root = changed["host_selection"]["root"]
                root.update(source_digest=source_digest, work_class_digest=work_digest, envelope_digest=envelope_digest)
                for capacity in changed["capacities"]:
                    capacity.update(root_digest=digest("authority-root", root), envelope_digest=envelope_digest)
                if fault == "capacity":
                    changed["capacities"].pop()
                authenticated = []
                for collection, kind in (("occupancies", "OCCUPANCY"), ("capacities", "CAPACITY"), ("credentials", "CREDENTIAL"), ("returns", "RETURN")):
                    authenticated.extend({"kind": kind, "record_digest": digest("authority-" + kind.lower(), row), "provider": row["provider"], "channel": row.get("channel")} for row in changed[collection])
                changed["host_selection"]["authenticated_records"] = sorted(authenticated, key=canonical)
                self.assertEqual(Consumer().evaluate({"kind": "AUTHORITY", "request": changed}).get("code"), code)

    def test_connector_identity_mismatch_creates_no_claim_or_invocation(self):
        base = base_lifecycle(definition_mutator=completion_definition_mutator, authority_mutator=completion_authority_mutator)
        host = reference_host.SingleProcessReferenceHost(Consumer())
        deployment = base["deploy_input"]
        organization = deployment["deployment_authorization"]["organization_id"]
        instance = deployment["instance_id"]
        host.install(deployment)
        request = {name: deployment[name] for name in ("specification_pin", "definition", "definition_digest", "profile", "role")}
        clocked = host.submit(organization, bind_event({**request, "event": base["clock_event"]}, host.snapshot(organization, instance)["state"]))["transition"]
        permitted = host.submit(organization, bind_event({**request, "event": base["proposal_event"]}, clocked["state"]))["transition"]
        event = authorization_event(base, permitted)
        authorized = host.submit(organization, bind_event({**request, "event": event}, permitted["state"]))["transition"]
        authorization = authorized["state"]["authorizations"][0]
        invoke = mock.Mock(return_value={})
        selected = {**authorization["connector"], "invoke": invoke}
        before = host.snapshot(organization, instance)
        for member in ("id", "version", "binding_digest"):
            with self.subTest(member=member):
                wrong = {**selected, member: "wrong-connector" if member != "binding_digest" else digest("wrong-connector", {})}
                with self.assertRaises(Refusal) as refused:
                    host.dispatch(organization, instance, authorization["authorization_digest"], wrong, "connector-mismatch")
                self.assertEqual(refused.exception.code, "BINDING_MISMATCH")
                self.assertEqual(host.dispatch_claims(organization, instance), [])
                self.assertEqual(host.snapshot(organization, instance), before)
        for malformed in (invoke, {**selected, "extra": True}, {**selected, "invoke": None}):
            with self.assertRaises(Refusal) as refused:
                host.dispatch(organization, instance, authorization["authorization_digest"], malformed, "malformed-connector")
            self.assertEqual(refused.exception.code, "INPUT_INVALID")
            self.assertEqual(host.dispatch_claims(organization, instance), [])
        invoke.assert_not_called()
        result = host.dispatch(organization, instance, authorization["authorization_digest"], selected, "selected-connector")
        self.assertEqual(result["disposition"], "PENDING")
        self.assertEqual(invoke.call_count, 1)

    def test_restart_rejects_fully_committed_authorization_after_deadline_stop(self):
        def definition_layout(definition):
            completion_definition_mutator(definition)
            definition["profile"] = "DEADLINES"
            definition["deadlines"] = [{"id": "stop-deadline", "step_id": "issue", "due": {"kind": "ELAPSED_DURATION", "value": "60", "unit": "SECOND"}, "clock_source": "expiry-clock", "boundary": "AT_OR_AFTER", "expiry_target": None}]

        base = base_lifecycle(definition_mutator=definition_layout, authority_mutator=completion_authority_mutator,
                              initial_clocks=[available_clock("expiry-clock", "1", "2026-09-10T04:30:00Z")])
        consumer = Consumer()
        deployed = consumer.deploy(base["deploy_input"])
        request = {name: base["deploy_input"][name] for name in ("specification_pin", "definition", "definition_digest", "profile", "role")}
        clocked = consumer.step(bind_event({**request, "event": base["clock_event"]}, deployed["state"]))
        permitted = consumer.step(bind_event({**request, "event": base["proposal_event"]}, clocked["state"]))
        self.assertEqual(permitted["decision"]["disposition"], "PERMITTED")
        expiry = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "stop-deadline-clock", "kind": "CLOCK", "instance_id": permitted["state"]["instance_id"], "clock": available_clock("expiry-clock", "2", "2026-09-10T04:31:00Z"), "activation_clocks": []}
        stopped = consumer.step(bind_event({**request, "event": expiry}, permitted["state"]))
        self.assertEqual(stopped["state"]["status"], "STOPPED")
        self.assertTrue(lifecycle._validate_state_integrity(stopped["state"], request["definition"]))
        event = authorization_event(base, {"state": stopped["state"], "permit": permitted["permit"]}, event_id="after-deadline-stop", intent="after-stop-intent")
        attempted = bind_event({**request, "event": event}, stopped["state"])
        self.assertEqual(consumer.step(attempted).get("code"), "PREREQUISITE_MISSING")
        with mock.patch.object(dispatch_gate, "eligible", return_value=True):
            forged = dispatch_gate.authorize(attempted)
        self.assertEqual(forged["decision"]["disposition"], "AUTHORIZED")
        self.assertFalse(lifecycle._validate_state_integrity(forged["state"], request["definition"]))
        restarted = consumer.step(bind_event({**request, "event": {**expiry, "event_id": "after-forged-authorization", "clock": available_clock("expiry-clock", "3", "2026-09-10T04:32:00Z")}}, forged["state"]))
        self.assertEqual(restarted.get("code"), "STATE_INVALID")

    def test_fresh_correction_grant_cannot_reuse_original_approval_identity(self):
        changes = [{"field": "resulting_status", "old_value": {"type_ref": "STATUS", "value": "Return to Service"},
                    "new_value": {"type_ref": "STATUS", "value": "Rejected"}}]
        request, _ = correction_fixture(changes=changes)
        grant = next(row for row in request["original_permit"]["authority_basis"]["acts"] if row["kind"] == "GRANT")
        grant["id"] = "distinct-original-grant"
        request["original_permit"]["authority_basis"]["envelope"]["grant_ref"] = grant["id"]
        rebind_original_permit(request)
        self.assertEqual(Consumer().check_evidence(request)["status"], "EVIDENCE_VALID")
        fresh = request["correction"]["new_approval_basis"]
        next(row for row in fresh["acts"] if row["kind"] == "GRANT")["id"] = "AP-091"
        fresh["envelope"]["grant_ref"] = "AP-091"
        request["correction"]["new_approval_basis"], _ = rebind_authority(fresh)
        self.assertEqual(Consumer().evaluate({"kind": "AUTHORITY", "request": request["correction"]["new_approval_basis"]})["status"], "READY_FOR_RESERVATION")
        request["correction"] = seal_correction(request["correction"])
        self.assertEqual(Consumer().check_evidence(request).get("code"), "BINDING_MISMATCH")

    def test_correction_definition_profile_must_equal_original_permit(self):
        request, _ = correction_fixture()
        self.assertEqual(Consumer().check_evidence(request)["status"], "EVIDENCE_VALID")
        request["definition"]["profile"] = "CHOICE_LOOPS"
        request["definition_digest"] = digest("work-class-definition", request["definition"])
        permit = request["original_permit"]
        permit["work_class_digest"] = request["definition_digest"]
        occurrence = permit["occurrence"]
        occurrence["work_class_digest"] = request["definition_digest"]
        occurrence["occurrence_id"] = digest("occurrence", {name: value for name, value in occurrence.items() if name != "occurrence_id"})
        permit["authority_basis"]["proposal"]["occurrence"] = occurrence["occurrence_id"]
        rebind_original_permit(request)
        original = request["original_record"]
        original["attributed_request"]["occurrence"] = occurrence["occurrence_id"]
        original["native_request_digest"] = digest("native-request", original["attributed_request"])
        self.assertEqual(Consumer().check_evidence(request).get("code"), "DEPENDENCY_MISMATCH")

    def test_exclusive_slot_declarations_enforce_scalar_restrictions(self):
        configuration = history_fixture()["configuration"]
        reservation_v2.ReferenceHost(configuration)
        for member, value in (("nonnegative", True), ("unit", "equipment-count")):
            with self.subTest(member=member):
                changed = copy.deepcopy(configuration)
                declaration = next(row for row in changed["exclusive_slots"][0]["types"] if row["kind"] == "IDENTITY")
                declaration[member] = value
                with self.assertRaisesRegex(ValueError, "invalid registry configuration"):
                    reservation_v2.ReferenceHost(changed)
                with self.assertRaises(Refusal) as refused:
                    exclusive_history.validate_slot(changed["exclusive_slots"][0])
                self.assertEqual(refused.exception.code, "TYPE_INVALID")

    def test_install_validation_failure_publishes_no_work_or_reservation_root(self):
        deployment = linear_deploy_request()
        configuration = {"schema": "seampoint.work-class/1.0.0-draft.3/reservation-registry", "id": "registry.review", "principal": "principal.1", "clock_source": "clock.1", "administration_provider": "provider.1", "administration_source": "source.1", "administration_role": "administrator", "slots": [{"anchor": "budget.1", "exposure_domain": "domain.1"}]}
        budget = reservation_v2.ReferenceHost(configuration).export_state()
        rows = [{"registry_digest": digest("reservation-registry", configuration), "affected_anchors": ["budget.1"], "state": budget, "state_digest": reservation_v2._state_digest(budget)}]
        valid, clone = reference_host.schema_valid, copy.deepcopy
        for fault in ("validation", "response"):
            with self.subTest(fault=fault):
                host = reference_host.SingleProcessReferenceHost(Consumer())
                before_roots, before_budgets = clone(host._roots), clone(host._budgets)

                def copy_fault(value, memo=None):
                    if fault == "response" and isinstance(value, dict) and value.get("status") == "HOST_DEPLOY":
                        raise RuntimeError("injected deployment response preparation failure")
                    return clone(value, memo)

                with mock.patch.object(reference_host, "schema_valid", side_effect=lambda value, filename, definition=None: False if fault == "validation" and definition == "hostDeploymentResult" else valid(value, filename, definition)), mock.patch.object(reference_host.copy, "deepcopy", side_effect=copy_fault):
                    with self.assertRaises(RuntimeError):
                        host.install(deployment, rows)
                self.assertEqual(host._roots, before_roots)
                self.assertEqual(host._budgets, before_budgets)
                self.assertEqual(host.install(deployment, rows)["disposition"], "INSTALLED")
                self.assertTrue(host.install(deployment, rows)["replay"])

    def test_submit_prepublication_faults_preserve_work_budget_and_log(self):
        old = {"instance_id": "instance.1", "value": "old"}
        new = {"instance_id": "instance.1", "value": "new"}
        configuration = {"schema": "seampoint.work-class/1.0.0-draft.3/reservation-registry", "id": "registry.review", "principal": "principal.1", "clock_source": "clock.1", "administration_provider": "provider.1", "administration_source": "source.1", "administration_role": "administrator", "slots": [{"anchor": "budget.1", "exposure_domain": "domain.1"}]}
        budget = reservation_v2.ReferenceHost(configuration).export_state()
        next_budget = copy.deepcopy(budget)
        next_budget["core"]["revision"] = "1"
        registry = digest("reservation-registry", configuration)
        transition = {"status": "STEP", "state": new, "state_digest": digest("work-state", new), "transaction_digest": digest("lifecycle-transaction", {}), "replay": False,
                      "budget_results": [{"registry_digest": registry, "affected_anchors": ["budget.1"], "result": {"state": next_budget}}]}

        class SuppliedConsumer:
            def deploy(self, request):
                return {"status": "DEPLOYED", "state": copy.deepcopy(old), "state_digest": digest("work-state", old)}

            def step(self, request):
                return transition

        deployment = {"instance_id": "instance.1", "definition_digest": digest("work-class-definition", {}), "deployment_authorization": {"organization_id": "organization.1"}}
        rows = [{"registry_digest": registry, "affected_anchors": ["budget.1"], "state": budget, "state_digest": reservation_v2._state_digest(budget)}]
        request = {"profile": "LINEAR", "role": "LINEAR_WORK_RUNTIME", "state": old, "state_digest": digest("work-state", old), "event": {"event_id": "event.review", "budget_inputs": [{"registry_digest": registry, "affected_anchors": ["budget.1"], "request": {"state": budget, "state_digest": reservation_v2._state_digest(budget)}}]}}
        valid, encode, clone = reference_host.schema_valid, reference_host.canonical, copy.deepcopy
        for fault in ("validation", "log", "response"):
            with self.subTest(fault=fault):
                host = reference_host.SingleProcessReferenceHost(SuppliedConsumer())
                host.install(deployment, rows)
                prior_root = host._roots[("organization.1", "instance.1")]
                before_roots, before_budgets = clone(host._roots), clone(host._budgets)

                def encode_fault(value):
                    if fault == "log" and value is transition:
                        raise RuntimeError("injected log preparation failure")
                    return encode(value)

                def copy_fault(value, memo=None):
                    if fault == "response" and value is transition:
                        raise RuntimeError("injected response preparation failure")
                    return clone(value, memo)

                with mock.patch.object(reference_host, "schema_valid", side_effect=lambda value, filename, definition=None: False if fault == "validation" and definition == "hostCommitResult" else valid(value, filename, definition)), mock.patch.object(reference_host, "canonical", side_effect=encode_fault), mock.patch.object(reference_host.copy, "deepcopy", side_effect=copy_fault):
                    with self.assertRaises(RuntimeError):
                        host.submit("organization.1", request)
                self.assertEqual(host._roots, before_roots)
                self.assertEqual(host._budgets, before_budgets)
                self.assertEqual(prior_root, before_roots[("organization.1", "instance.1")])
                committed = host.submit("organization.1", request)
                self.assertEqual(committed["host_commit"]["disposition"], "COMMITTED")
                self.assertEqual(host.snapshot("organization.1", "instance.1")["budget_states"][0]["state"], next_budget)
                self.assertEqual(prior_root, before_roots[("organization.1", "instance.1")])
                self.assertIsNot(host._roots[("organization.1", "instance.1")]["registry_digests"], prior_root["registry_digests"])


if __name__ == "__main__":
    unittest.main()
