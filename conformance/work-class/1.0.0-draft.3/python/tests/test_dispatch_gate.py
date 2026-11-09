from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from consumer import Consumer
from implementation import completion, dispatch_gate, lifecycle, source_observations
from implementation.common import PIN, PREFIX, Refusal, digest
from implementation.reference_host import SingleProcessReferenceHost


def case_input(number):
    path = ROOT.parent / "cases" / "equipment-dispatch" / f"C3-ED-{number:03}.json"
    return json.loads(path.read_text())["input"]


def bind_event(request, state):
    value = copy.deepcopy(request)
    value["state"] = copy.deepcopy(state)
    value["state_digest"] = lifecycle.state_digest(state)
    value["event"]["expected_state_revision"] = state["revision"]
    value["event"]["expected_state_digest"] = value["state_digest"]
    return value


def connector_binding(authorization, invoke):
    return {**authorization["connector"], "invoke": invoke}


def recovery_regressions():
    path = ROOT.parent / "review" / "fixtures" / "recovery-dispatch-regressions.json"
    value = json.loads(path.read_text())
    if value["specification_pin"] != PIN:
        raise AssertionError("Recovery regression fixture differs from the selected candidate")
    if sorted(row["name"] for row in value["traces"]) != ["gated-completion", "registry-application", "supplier-restoration"]:
        raise AssertionError("Recovery regression trace inventory differs from the reviewed source scope")
    return value


def reseal_last_recovery_projection(state):
    core = copy.deepcopy(state)
    core["receipts"] = []
    core["replays"] = []
    receipt = state["receipts"][-1]
    receipt["state_after_core_digest"] = digest("work-state-core", core)
    receipt["decision_id"] = digest("decision-receipt", {name: value for name, value in receipt.items() if name != "decision_id"})
    replay = next(row for row in state["replays"] if row["event_id"] == receipt["event_id"])
    replay.update(event_digest=receipt["event_digest"], decision_receipt_digest=receipt["decision_id"],
                  decision=copy.deepcopy(receipt), transition_state_digest=receipt["state_after_core_digest"])
    replay["transaction_digest"] = digest("lifecycle-transaction", {
        "state_before_digest": receipt["state_before_digest"], "event_digest": receipt["event_digest"],
        "decision_receipt_digest": receipt["decision_id"], "state_after_core_digest": receipt["state_after_core_digest"],
        "budget_results": replay["budget_results"],
    })


class DispatchGateTests(unittest.TestCase):
    def test_recovery_emitted_state_retry_preserves_exact_history(self):
        for trace in recovery_regressions()["traces"]:
            consumer, previous = Consumer(), None
            for row in trace["rows"]:
                with self.subTest(trace=trace["name"], event=row["name"]):
                    request = copy.deepcopy(row["input"])
                    if previous is not None:
                        self.assertEqual(request["state"], previous["state"])
                        request["state"] = copy.deepcopy(previous["state"])
                        request["state_digest"] = previous["state_digest"]
                    actual = consumer.call(row["operation"], request)
                    self.assertEqual(actual, row["expected"])
                    previous = actual
                    if row["operation"] == "step" and request["event"]["kind"] in {"DISPOSE", "APPLY_DISPOSITION"}:
                        if request["event"]["kind"] == "APPLY_DISPOSITION":
                            self.assertEqual(actual["state"]["recovery_records"][-1]["registry_selections"], request["recovery_registries"])
                        retry = copy.deepcopy(request)
                        retry["state"], retry["state_digest"] = copy.deepcopy(actual["state"]), actual["state_digest"]
                        replay = consumer.step(retry)
                        self.assertEqual(replay["status"], "STEP")
                        self.assertTrue(replay["replay"])
                        self.assertEqual(replay["decision"], row["expected"]["decision"])
                        self.assertEqual(replay["budget_results"], row["expected"]["budget_results"])
                        self.assertEqual(replay["state"], actual["state"])
                        self.assertEqual(replay["state_digest"], actual["state_digest"])
            for row in trace["rows"]:
                if row["operation"] == "step" and row["input"]["event"]["kind"] in {"DISPOSE", "APPLY_DISPOSITION"}:
                    retry = copy.deepcopy(row["input"])
                    retry["state"], retry["state_digest"] = copy.deepcopy(previous["state"]), previous["state_digest"]
                    replay = consumer.step(retry)
                    self.assertEqual(replay["status"], "STEP", trace["name"])
                    self.assertTrue(replay["replay"])
                    self.assertEqual(replay["decision"], row["expected"]["decision"])
                    self.assertEqual(replay["state"], previous["state"])

    def test_recovery_checkpoints_match_complete_source_states(self):
        for trace in recovery_regressions()["traces"]:
            latest = trace["rows"][-1]["expected"]["state"]
            original = copy.deepcopy(latest)
            for row in trace["rows"]:
                if row["operation"] != "step":
                    continue
                with self.subTest(trace=trace["name"], before=row["name"]):
                    sequence = int(row["input"]["state"]["revision"]) + 1
                    prior = completion._prior_evidence(latest, sequence, row["input"]["definition"])
                    self.assertEqual(prior, row["input"]["state"])
                    self.assertEqual(lifecycle.state_digest(prior), row["input"]["state_digest"])
            self.assertEqual(latest, original)

    def test_substituted_recovery_projection_fails_exact_prefix_replay(self):
        for trace in recovery_regressions()["traces"]:
            request = copy.deepcopy(trace["rows"][-1]["input"])
            request["state"] = copy.deepcopy(trace["rows"][-1]["expected"]["state"])
            state = request["state"]
            first = state["recovery_records"][0]
            self.assertTrue(first["before_projection"]["active"] or first["before_projection"]["completed"])
            first["before_projection"]["active"] = []
            first["before_projection"]["completed"] = []
            reseal_last_recovery_projection(state)
            request["state_digest"] = lifecycle.state_digest(state)
            receipt = next(row for row in state["receipts"] if row["event_id"] == first["event"]["event_id"])
            with self.assertRaisesRegex(Refusal, "STATE_INVALID"):
                completion._prior_evidence(state, int(receipt["sequence"]) + 1, request["definition"])
            result = Consumer().step(request)
            self.assertEqual((result["status"], result["code"]), ("REFUSED", "STATE_INVALID"), trace["name"])
            self.assertEqual(result["state"], state)
            self.assertEqual(result["state_digest"], request["state_digest"])


    def test_expiry_arithmetic_preserves_four_digit_year_and_refuses_overflow(self):
        self.assertEqual(lifecycle._add_seconds("0001-01-01T00:00:00Z", 60), "0001-01-01T00:01:00Z")
        with self.assertRaisesRegex(Refusal, "LIMIT_EXCEEDED"):
            lifecycle._add_seconds("9999-12-31T23:59:59Z", 1)

    def installed_host(self):
        deployed, proposed, authorized = (case_input(number) for number in (1, 2, 3))
        host = SingleProcessReferenceHost(Consumer())
        organization = deployed["deployment_authorization"]["organization_id"]
        instance = deployed["instance_id"]
        self.assertEqual(host.install(deployed)["disposition"], "INSTALLED")
        snapshot = host.snapshot(organization, instance)
        clock = copy.deepcopy(proposed["state"]["clocks"][0])
        clock_request = bind_event(proposed, snapshot["state"])
        clock_request["event"] = {
            "schema": PREFIX + "runtime-event", "kind": "CLOCK",
            "event_id": proposed["state"]["receipts"][0]["event_id"], "instance_id": instance,
            "expected_state_revision": snapshot["state"]["revision"],
            "expected_state_digest": snapshot["state_digest"], "clock": clock, "activation_clocks": [],
        }
        self.assertEqual(host.submit(organization, clock_request)["host_commit"]["disposition"], "COMMITTED")
        self.assertEqual(host.submit(organization, proposed)["host_commit"]["disposition"], "COMMITTED")
        self.assertEqual(host.submit(organization, authorized)["host_commit"]["disposition"], "COMMITTED")
        authorization = host.snapshot(organization, instance)["state"]["authorizations"][0]
        return host, organization, instance, authorization

    @staticmethod
    def observation(payload, status="SENT", attempt_id="native-attempt-1"):
        permit = case_input(3)["event"]["permit"]
        return {"attempt": {
            "attempt_id": attempt_id, "status": status,
            "attempted_at": payload["authorization_fence"]["checked_at"],
            "request_digest": digest("dispatch-native-request", {
                "instance_id": payload["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
                **payload["native_request"],
            }),
        }, "acknowledgement": {"status": "NONE", "observed_at": None, "reference": None}}

    def test_claim_serializes_calls_and_blocks_new_authorization(self):
        host, organization, instance, authorization = self.installed_host()
        entered, release = threading.Event(), threading.Event()
        calls, results = [], []

        def connector(payload):
            calls.append(payload)
            entered.set()
            self.assertTrue(release.wait(10))
            return self.observation(payload)

        thread = threading.Thread(target=lambda: results.append(host.dispatch(
            organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "native-send-1")))
        thread.start()
        try:
            self.assertTrue(entered.wait(10))
            replay = host.dispatch(organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "native-send-1")
            self.assertTrue(replay["replay"])
            self.assertFalse(replay["dispatch_performed"])
            fresh = bind_event(case_input(3), host.snapshot(organization, instance)["state"])
            fresh["event"]["event_id"] = "another-authorization"
            fresh["event"]["dispatch_intent_id"] = "another-intent"
            self.assertEqual(host.submit(organization, fresh)["code"], "PREREQUISITE_MISSING")
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertEqual(results[0]["host_commit"]["disposition"], "COMMITTED")
        self.assertEqual(host.dispatch_claims(organization, instance)[0]["status"], "CONSUMED")
        replay = host.dispatch(organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "native-send-1")
        self.assertTrue(replay["replay"])
        self.assertEqual(len(calls), 1)

    def test_connector_exception_preserves_pending_until_conservative_recovery(self):
        host, organization, instance, authorization = self.installed_host()
        connector = mock.Mock(side_effect=RuntimeError("remote response lost"))
        result = host.dispatch(organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "exception-send")
        self.assertEqual(result["disposition"], "PENDING")
        self.assertEqual(host.dispatch_claims(organization, instance)[0]["status"], "PENDING")
        replay = host.dispatch(organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "exception-send")
        self.assertFalse(replay["dispatch_performed"])
        recovered = host.recover_dispatch(organization, instance, authorization["dispatch_intent_id"], "recover-exception")
        self.assertEqual(recovered["transition"]["decision"]["disposition"], "DISPATCH_RECORDED")
        self.assertEqual(recovered["transition"]["state"]["dispatches"][0]["attempt"]["status"], "UNKNOWN")
        self.assertEqual(connector.call_count, 1)
        self.assertEqual(host.dispatch_claims(organization, instance)[0]["status"], "CONSUMED")

    def test_malformed_connector_result_preserves_pending(self):
        host, organization, instance, authorization = self.installed_host()
        connector = mock.Mock(return_value={"status": "NOT_SENT"})
        result = host.dispatch(organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "malformed-send")
        self.assertEqual(result["disposition"], "PENDING")
        self.assertEqual(host.dispatch_claims(organization, instance)[0]["status"], "PENDING")
        self.assertEqual(host.snapshot(organization, instance)["state"]["dispatches"], [])

    def test_commit_exception_preserves_pending(self):
        host, organization, instance, authorization = self.installed_host()
        connector = mock.Mock(side_effect=self.observation)
        with mock.patch.object(host, "submit", side_effect=RuntimeError("commit uncertain")):
            result = host.dispatch(organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "commit-send")
        self.assertEqual(result["disposition"], "PENDING")
        self.assertEqual(host.dispatch_claims(organization, instance)[0]["status"], "PENDING")
        self.assertEqual(connector.call_count, 1)

    def test_safe_not_sent_requires_new_intent(self):
        host, organization, instance, authorization = self.installed_host()
        connector = mock.Mock(side_effect=lambda payload: self.observation(payload, "NOT_SENT"))
        result = host.dispatch(organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "not-sent")
        self.assertEqual(result["transition"]["decision"]["disposition"], "DISPATCH_REFUSED")
        self.assertEqual(host.dispatch_claims(organization, instance)[0]["status"], "NOT_SENT")
        host.dispatch(organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "not-sent-again")
        self.assertEqual(connector.call_count, 1)
        fresh = bind_event(case_input(22), host.snapshot(organization, instance)["state"])
        self.assertEqual(host.submit(organization, fresh)["transition"]["decision"]["disposition"], "AUTHORIZED")

    def test_unknown_authorization_never_invokes_connector(self):
        host, organization, instance, _ = self.installed_host()
        connector = mock.Mock()
        with self.assertRaisesRegex(Refusal, "PREREQUISITE_MISSING"):
            host.dispatch(organization, instance, "sha256:" + "0" * 64, connector, "unknown-send")
        connector.assert_not_called()

    def test_later_withheld_evaluation_blocks_old_successful_head(self):
        host, organization, instance, authorization = self.installed_host()
        later = case_input(29)
        snapshot = host.snapshot(organization, instance)
        clock = max(later["state"]["clocks"], key=lambda row: int(row["revision"]))
        clock_request = bind_event(case_input(3), snapshot["state"])
        clock_request["event"] = {
            "schema": PREFIX + "runtime-event", "kind": "CLOCK", "event_id": "withdrawal-clock",
            "instance_id": instance, "expected_state_revision": snapshot["state"]["revision"],
            "expected_state_digest": snapshot["state_digest"], "clock": clock, "activation_clocks": [],
        }
        self.assertEqual(host.submit(organization, clock_request)["host_commit"]["disposition"], "COMMITTED")
        fresh = bind_event(case_input(3), host.snapshot(organization, instance)["state"])
        evaluation = next(row for row in later["state"]["authorization_evaluations"] if row["disposition"] == "WITHHELD")
        event = fresh["event"]
        event.update({"event_id": "withdrawal-refresh", "dispatch_intent_id": "withdrawal-intent", "clock_revision": clock["revision"],
                      "authority_input": copy.deepcopy(evaluation["authority_input"]), "authorization_fence": None})
        event["observation_digests"] = dispatch_gate.observation_digests(event["authority_input"])
        result = host.submit(organization, fresh)
        self.assertEqual(result["transition"]["decision"]["disposition"], "WITHHELD")
        self.assertEqual(dispatch_gate.head(result["transition"]["state"], authorization["permit_digest"])["authorization_digest"], authorization["authorization_digest"])
        connector = mock.Mock()
        with self.assertRaisesRegex(Refusal, "PREREQUISITE_MISSING"):
            host.dispatch(organization, instance, authorization["authorization_digest"], connector_binding(authorization, connector), "send-after-withdrawal")
        connector.assert_not_called()

    def test_restart_recomputes_historical_dispatch_prohibition(self):
        for number in (28, 29, 30, 31, 32):
            with self.subTest(number=number):
                request = case_input(number)
                result = Consumer().step(request)
                self.assertEqual(result["status"], "STEP")
                self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))
                dispatch = next(row for row in result["state"]["dispatches"] if row["event_id"] == request["event"]["event_id"])
                self.assertTrue(dispatch_gate.dispatch_integrity(result["state"], request["definition"], dispatch))
                reasons = result["state"]["receipts"][-1]["reason_codes"]
                if "LATE_OR_PROHIBITED_DISPATCH" in reasons:
                    reasons.remove("LATE_OR_PROHIBITED_DISPATCH")
                else:
                    reasons.append("LATE_OR_PROHIBITED_DISPATCH")
                self.assertFalse(dispatch_gate.dispatch_integrity(result["state"], request["definition"], dispatch))

    def test_withheld_evaluation_retains_input_and_receipt_binding(self):
        request = case_input(13)
        result = Consumer().step(request)
        self.assertEqual(result["decision"]["disposition"], "WITHHELD")
        self.assertEqual(result["state"]["authorizations"], [])
        evaluation = result["state"]["authorization_evaluations"][0]
        self.assertEqual(evaluation["authority_input"], request["event"]["authority_input"])
        self.assertEqual(result["decision"]["authorization_evaluation_digest"], evaluation["evaluation_digest"])
        self.assertEqual(result["decision"]["authority_result_digest"], evaluation["authority_result_digest"])
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))
        evaluation["dispatch_intent_id"] = "substituted-intent"
        self.assertFalse(dispatch_gate.state_integrity(result["state"], request["definition"]))

    def test_unavailable_clock_withholds_without_query_inventory(self):
        request = case_input(25)
        result = Consumer().step(request)
        self.assertEqual(result["decision"]["disposition"], "WITHHELD")
        evaluation = result["state"]["authorization_evaluations"][-1]
        self.assertEqual(evaluation["authority_result"]["reasons"], ["CLOCK_UNAVAILABLE"])
        self.assertEqual(evaluation["authority_result"]["failed_checks"], [])
        self.assertIsNone(evaluation["authorization_digest"])
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))

    def test_later_clock_preserves_historical_authorization_evaluation(self):
        request = case_input(3)
        authorized = Consumer().step(request)
        clock_request = bind_event(request, authorized["state"])
        clock_request["event"] = {
            "schema": PREFIX + "runtime-event", "kind": "CLOCK", "event_id": "later-unavailable-clock",
            "instance_id": request["state"]["instance_id"], "expected_state_revision": authorized["state"]["revision"],
            "expected_state_digest": authorized["state_digest"], "activation_clocks": [],
            "clock": {"source": request["event"]["permit"]["clock_source"], "revision": "2", "status": "UNAVAILABLE",
                      "observed_time": None, "evidence_digest": "sha256:" + "4" * 64},
        }
        result = Consumer().step(clock_request)
        self.assertEqual(result["decision"]["disposition"], "CLOCK_RECORDED")
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))
        observation = bind_event(case_input(19), result["state"])
        self.assertEqual(Consumer().step(observation)["decision"]["disposition"], "DISPATCH_RECORDED")

    def test_substituted_evaluation_clock_is_invalid_restart_state(self):
        request = case_input(25)
        result = Consumer().step(request)
        evaluation = result["state"]["authorization_evaluations"][0]
        evaluation["clock_revision"] = "1"
        evaluation["authority_input"]["clock"] = {"source": request["event"]["permit"]["clock_source"],
            "status": "AVAILABLE", "instant": request["state"]["clocks"][0]["observed_time"]}
        self.assertFalse(dispatch_gate.state_integrity(result["state"], request["definition"]))

    def test_prohibited_not_sent_is_retained_after_consumption(self):
        request = case_input(19)
        sent = Consumer().step(request)
        observed = bind_event(case_input(21), sent["state"])
        observed["event"]["event_id"] = "prohibited-not-sent"
        observed["event"]["attempt"]["attempt_id"] = "prohibited-attempt"
        result = Consumer().step(observed)
        self.assertEqual(result["decision"]["disposition"], "DISPATCH_REFUSED")
        self.assertEqual(result["decision"]["reason_codes"], ["LATE_OR_PROHIBITED_DISPATCH", "NATIVE_NOT_SENT"])
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))

    def test_prohibited_rejected_attempt_is_restartable(self):
        request = case_input(18)
        request["event"]["attempt"]["status"] = "REJECTED"
        result = Consumer().step(request)
        self.assertEqual(result["decision"]["disposition"], "DISPATCH_REFUSED")
        self.assertIn("LATE_OR_PROHIBITED_DISPATCH", result["decision"]["reason_codes"])
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))

    def test_missing_local_observation_field_fails_inventory_and_relation(self):
        requirement = {"id": "required-subject", "step": "operate", "at": "CLOCK", "provider": "provider", "source": "source",
            "record_type": "record", "subject": "subject", "record_id": None, "purpose": "AUTHORITY",
            "freshness_seconds": "0", "expected_status": "AVAILABLE", "fields": [{"name": "subject", "type_ref": "identity"}],
            "relations": [{"id": "subject-check", "kind": "EQUALS", "left": "subject",
                "right": {"kind": "LITERAL", "value": {"type_ref": "identity", "value": "subject"}}}]}
        request = {"work_class": {"steps": [{"id": "operate"}]}, "proposal": {"step": "operate", "fields": []}, "clock": {"instant": "2026-09-10T04:30:00Z"},
            "envelope": {"source_observation_requirements": [requirement]}, "observations": []}
        query = source_observations.source_query(requirement, request)
        request["observations"] = [{"query": query, "query_digest": digest("authority-query", query), "status": "AVAILABLE",
            "as_of": request["clock"]["instant"], "revision": "revision", "provider_record_id": "subject", "fields": [],
            "relations": requirement["relations"], "evidence_ref": "evidence", "provenance_digest": "sha256:" + "1" * 64}]
        result = source_observations.observe_source(request, request["envelope"], [])
        self.assertEqual(result["reasons"], {"SOURCE_OBSERVATION_FIELDS", "SOURCE_OBSERVATION_RELATIONS"})
        self.assertEqual(result["checks"], [])
        self.assertEqual({(row["requirement_ref"], row["reason"]) for row in result["failed"]},
            {("required-subject", "SOURCE_OBSERVATION_FIELDS"), ("required-subject", "SOURCE_OBSERVATION_RELATIONS")})

    def test_failed_dependency_relation_cannot_supply_a_value(self):
        def requirement(name, relation):
            return {"id": name, "step": "operate", "at": "CLOCK", "provider": "provider", "source": "source",
                    "record_type": "record", "subject": "subject", "record_id": None, "purpose": "AUTHORITY",
                    "freshness_seconds": "0", "expected_status": "AVAILABLE",
                    "fields": [{"name": "subject", "type_ref": "identity"}], "relations": [relation]}

        literal = lambda value: {"kind": "LITERAL", "value": {"type_ref": "identity", "value": value}}
        dependent = requirement("a-dependent", {"id": "dependent-check", "kind": "EQUALS", "left": "subject",
            "right": {"kind": "OBSERVATION_ID", "requirement_id": "z-dependency", "type_ref": "identity"}})
        dependency = requirement("z-dependency", {"id": "failed-check", "kind": "EQUALS", "left": "subject", "right": literal("other")})
        request = {"work_class": {"steps": [{"id": "operate"}]}, "proposal": {"step": "operate", "fields": []}, "clock": {"instant": "2026-09-10T04:30:00Z"},
                   "envelope": {"source_observation_requirements": [dependent, dependency]}, "observations": []}
        for requirement in request["envelope"]["source_observation_requirements"]:
            query = source_observations.source_query(requirement, request)
            request["observations"].append({"query": query, "query_digest": digest("authority-query", query),
                "status": "AVAILABLE", "as_of": request["clock"]["instant"], "revision": "revision", "provider_record_id": "subject",
                "fields": [{"name": "subject", "value": {"type_ref": "identity", "value": "subject"}}],
                "relations": requirement["relations"], "evidence_ref": "evidence", "provenance_digest": "sha256:" + "1" * 64})
        result = source_observations.observe_source(request, request["envelope"], [])
        self.assertEqual(result["reasons"], {"SOURCE_OBSERVATION_RELATIONS"})
        self.assertEqual({row["requirement_ref"] for row in result["failed"]}, {"a-dependent", "z-dependency"})


if __name__ == "__main__":
    unittest.main()
