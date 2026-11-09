from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import runpy
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT.parent / "review")]

import flow_fixture as f
from consumer import Consumer
from implementation.common import Refusal, canonical, digest
from implementation.flow_host import FlowReferenceHost


class FlowBusinessHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = runpy.run_path(str(ROOT.parent / "review/build-information-flow-cases.py"))["source_trace"](compensation=True)
        cls.trace = f.lifecycle_trace(cls.source)

    def setUp(self):
        self.facts, self.path = copy.deepcopy(self.source), copy.deepcopy(self.trace)
        self.config = self.facts["configuration"]
        self.organization = self.config["principal"]
        self.instance = self.path["base"]["deploy_input"]["instance_id"]
        first_reader = self.facts["stages"][0][0]["response_authority"]
        self.reader = {**first_reader["proposal"]["executor"], "clock": copy.deepcopy(first_reader["clock"])}
        self.reader.pop("occupancy")
        self.authorities, self.events = set(), {}
        self.host = FlowReferenceHost(Consumer(), lambda: copy.deepcopy(self.reader),
            lambda configuration, event, evidence: self.events.get(canonical(event)) == canonical(evidence),
            lambda configuration, authority: canonical(authority) in self.authorities)
        self.host.install_flow(self.organization, self.config)
        for request, expected in self.facts["stages"]:
            self.authorize(request)
            self.assertEqual(self.host.submit_flow(self.organization, request), expected)
        self.states = {digest("flow-state", state): state for state in (self.facts["state"], self.path["flow_expose_result"]["state"])}
        req = self.path["dispatch_authority"]["envelope"]["flow_requirements"][0]
        native = self.path["authorization_event"]["native_request"]
        recipient = next(row["value"]["value"] for row in native["fields"] if row["name"] == req["recipient_field"])
        self.route = {"interface": native["interface"], "operation": native["operation"], "recipient_field": req["recipient_field"],
            "recipient": recipient, "channel": req["channel"], "purpose": req["purpose"],
            "connector": self.path["connector"], "onward_delivery": False}
        self.host.install_flow_routes(self.organization, self.config["principal"], [self.route])
        for operation, request, expected in self.path["stages"][:-1]:
            if operation == "deploy":
                self.assertEqual(self.host.install(request, response_requests=self.responses)["disposition"], "INSTALLED")
            else:
                if request["event"]["kind"] == "CLOCK":
                    self.reader["clock"]["instant"] = request["event"]["clock"]["observed_time"]
                result = self.host.submit(self.organization, request, response_requests=self.responses)
                self.assertEqual(result.get("transition"), expected, result.get("code"))
        self.expose = self.path["flow_expose_input"]
        self.authorize(self.expose)
        self.authorization = self.path["authorized"]["state"]["authorizations"][0]
        self.calls = []

    def authorize(self, request):
        self.events[canonical(request["event"])] = canonical(request["host_evidence"])
        self.authorities.add(canonical(request["response_authority"]))
        for name in ("access_authority", "transfer_authority"):
            if name in request["event"]["payload"]:
                self.authorities.add(canonical(request["event"]["payload"][name]))
        if request["event"]["kind"] == "EXPOSE":
            expanded = copy.deepcopy(request["event"]["payload"]["authority_projection"])
            expanded["flow_bases"][0]["state"] = copy.deepcopy(request["state"])
            self.authorities.add(canonical(expanded))

    def responses(self):
        current_digest = self.host._flows[(self.organization, self.config["principal"])]["state_digest"]
        request = copy.deepcopy(self.path["flow_expose_input"])
        request.update(state=copy.deepcopy(self.states[current_digest]), state_digest=current_digest)
        f.refresh_response(request, at=self.reader["clock"]["instant"])
        self.authorities.add(canonical(request["response_authority"]))
        return [(self.organization, request)]

    def connector(self, payload, status="SENT"):
        self.calls.append(payload)
        core = self.host._flows[(self.organization, self.config["principal"])]["state"]["core"]
        req = self.path["dispatch_authority"]["envelope"]["flow_requirements"][0]
        self.assertIn(req["claim_id"], [row["id"] for row in core["claims"]])
        self.assertTrue(core["consumed_release_acts"])
        with self.assertRaises(Refusal): self.host.submit_flow(self.organization, self.expose)
        return {"attempt": {"attempt_id": "synthetic-custody-attempt", "status": status,
            "attempted_at": payload["authorization_fence"]["checked_at"],
            "request_digest": digest("dispatch-native-request", {"instance_id": self.instance,
                "occurrence_id": self.path["permitted"]["permit"]["occurrence"]["occurrence_id"], **payload["native_request"]})},
            "acknowledgement": {"status": "NONE", "observed_at": None, "reference": None}}

    def dispatch(self, invoke=None, **options):
        return self.host.dispatch(self.organization, self.instance, self.authorization["authorization_digest"],
            {**self.path["connector"], "invoke": invoke or self.connector}, "synthetic-custody-result",
            flow_request=self.expose, response_requests=self.responses, **options)

    def assert_consumed(self, consumed):
        core = self.host._flows[(self.organization, self.config["principal"])]["state"]["core"]
        req = self.path["dispatch_authority"]["envelope"]["flow_requirements"][0]
        self.assertEqual(any(row["id"] == req["claim_id"] for row in core["claims"]), consumed)
        self.assertEqual(bool(core["consumed_release_acts"]), consumed)
        self.assertEqual(core["contexts"][0]["restrictions"], [self.facts["restriction"]])

    def test_exact_lifecycle_permit_dispatch_and_claim_precede_one_invocation(self):
        result = self.dispatch()
        self.assertEqual(result["transition"]["decision"]["disposition"], "DISPATCH_RECORDED")
        self.assertEqual(len(self.calls), 1)
        self.assert_consumed(True)
        self.assertTrue(self.dispatch()["replay"])
        self.assertEqual(len(self.calls), 1)

    def test_dispatch_flow_preflight_refuses_before_response_or_authentication_callbacks(self):
        invalid = copy.deepcopy(self.expose)
        invalid["response_authority"]["source"]["obligations"][0]["text"] = ""
        padded = "x" * (16777217 - len(canonical(invalid)))
        before_flows = copy.deepcopy(self.host._flows)
        before_roots = copy.deepcopy(self.host._roots)
        before_claims = copy.deepcopy(self.host._dispatch_claims)
        for value, code in ((padded, "LIMIT_EXCEEDED"), (1, "SCHEMA_INVALID"), ("\ud800", "SCHEMA_INVALID")):
            with self.subTest(code=code, value="oversized" if value == padded else repr(value)):
                invalid["response_authority"]["source"]["obligations"][0]["text"] = value
                if code == "LIMIT_EXCEEDED":
                    self.assertEqual(len(canonical(invalid)), 16777217)
                responses = mock.Mock(side_effect=self.responses)
                invoke = mock.Mock(side_effect=self.connector)
                with mock.patch.object(self.host, "_current_reader") as reader, mock.patch.object(self.host, "_authenticate_authority") as authority, mock.patch.object(self.host, "_authenticate_event") as event:
                    with self.assertRaises(Refusal) as error:
                        self.host.dispatch(self.organization, self.instance, self.authorization["authorization_digest"],
                            {**self.path["connector"], "invoke": invoke}, "synthetic-invalid-dispatch",
                            flow_request=invalid, response_requests=responses)
                    self.assertEqual(error.exception.code, code)
                    reader.assert_not_called()
                    authority.assert_not_called()
                    event.assert_not_called()
                responses.assert_not_called()
                invoke.assert_not_called()
                self.assertEqual(self.host._flows, before_flows)
                self.assertEqual(self.host._roots, before_roots)
                self.assertEqual(self.host._dispatch_claims, before_claims)
                self.assert_consumed(False)

    def test_restore_preserves_advanced_registry_and_refuses_missing_or_older_history(self):
        self.dispatch()
        checkpoint = self.host.export_checkpoint(self.responses)
        restored = FlowReferenceHost.from_checkpoint(Consumer(), self.host._current_reader,
            self.host._authenticate_event, self.host._authenticate_authority, checkpoint)
        self.assertEqual(restored.snapshot(self.organization, self.instance, response_requests=self.responses),
            self.host.snapshot(self.organization, self.instance, response_requests=self.responses))
        malformed_live = copy.deepcopy(restored._flows)
        restored._flows = {}
        with self.assertRaises(Refusal) as error:
            restored.snapshot(self.organization, self.instance)
        self.assertEqual(error.exception.code, "ACCESS_NOT_ESTABLISHED")
        restored._flows = malformed_live
        for missing in (True, False):
            with self.subTest(missing=missing):
                invalid = copy.deepcopy(checkpoint)
                if missing:
                    invalid["flows"], invalid["routes"] = {}, {}
                else:
                    first = self.facts["stages"][0][1]
                    invalid["flows"][(self.organization, self.config["principal"])].update(
                        state=copy.deepcopy(first["state"]), state_digest=first["state_digest"])
                with self.assertRaises(Refusal) as error:
                    FlowReferenceHost.from_checkpoint(Consumer(), self.host._current_reader,
                        self.host._authenticate_event, self.host._authenticate_authority, invalid)
                self.assertEqual(error.exception.code, "STATE_INVALID")

    def test_preclaim_failure_invokes_nothing_and_consumes_no_flow_release(self):
        self.dispatch(flow_failure_stage="PRE_CLAIM")
        self.assertEqual(self.calls, [])
        self.assert_consumed(False)
        self.assertEqual(self.host.dispatch_claims(self.organization, self.instance, response_requests=self.responses), [])
        self.dispatch()
        self.assertEqual(len(self.calls), 1)

    def test_postclaim_failure_invokes_nothing_and_replay_cannot_retry(self):
        self.dispatch(flow_failure_stage="POST_CLAIM")
        self.assert_consumed(True)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.dispatch()["replay"])
        self.assertEqual(self.calls, [])

    def test_not_sent_still_consumes_release_and_cannot_retry(self):
        result = self.dispatch(lambda payload: self.connector(payload, "NOT_SENT"))
        self.assertEqual(result["transition"]["decision"]["disposition"], "DISPATCH_REFUSED")
        self.assert_consumed(True)
        self.dispatch()
        self.assertEqual(len(self.calls), 1)

    def test_timeout_retains_one_exposure_and_recovery_never_invokes_again(self):
        def timeout(payload):
            self.connector(payload)
            raise TimeoutError("synthetic custody response lost")
        self.assertEqual(self.dispatch(timeout)["disposition"], "PENDING")
        self.assert_consumed(True)
        recovered = self.host.recover_dispatch(self.organization, self.instance, self.authorization["dispatch_intent_id"],
            "recover-synthetic-timeout", response_requests=self.responses)
        self.assertEqual(recovered["transition"]["state"]["dispatches"][0]["attempt"]["status"], "UNKNOWN")
        self.assertEqual(len(self.calls), 1)

    def test_unauthenticated_current_release_prevents_exposure(self):
        self.authorities.discard(canonical(self.path["dispatch_authority"]))
        with self.assertRaises(Refusal): self.dispatch()
        self.assertEqual(self.calls, [])
        self.assert_consumed(False)

    def test_undeclared_connector_or_onward_delivery_invokes_nothing(self):
        for field, value in (("recipient", "undeclared-forwarder"), ("connector", {**self.route["connector"], "version": "alternate-credentials"})):
            self.host._flow_routes[(self.organization, self.config["principal"])][(self.route["interface"], self.route["operation"])][field] = value
            with self.assertRaises(Refusal): self.dispatch()
            self.assertEqual(self.calls, [])
        invalid = copy.deepcopy(self.route); invalid["onward_delivery"] = True
        other = FlowReferenceHost(Consumer(), self.host._current_reader, self.host._authenticate_event, self.host._authenticate_authority)
        other.install_flow(self.organization, self.config)
        with self.assertRaises(Refusal): other.install_flow_routes(self.organization, self.config["principal"], [invalid])

    def test_revoked_reader_after_custody_keeps_effects_and_returns_no_state(self):
        def revoke_reader(payload):
            result = self.connector(payload)
            self.reader["actor"] = "reader-withdrawn-during-custody"
            return result
        self.assertEqual(self.dispatch(revoke_reader), {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""})
        self.assert_consumed(True)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.host._roots[(self.organization, self.instance)]["state_value"]["dispatches"]), 1)

    def test_connector_cancellation_after_reader_withdrawal_retains_claims_and_never_resends(self):
        reader_actor = self.reader["actor"]
        failure = asyncio.CancelledError("protected custody cancellation")
        def revoked_cancellation(payload):
            self.connector(payload)
            self.reader["actor"] = "reader-withdrawn-during-custody"
            raise failure
        self.assertEqual(self.dispatch(revoked_cancellation), {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""})
        self.assert_consumed(True)
        self.assertEqual(self.host._flows[(self.organization, self.config["principal"])]["state"], self.path["flow_expose_result"]["state"])
        claim_key = (self.organization, self.instance, self.authorization["dispatch_intent_id"])
        self.assertEqual(self.host._dispatch_claims[claim_key]["status"], "PENDING")
        self.assertEqual(len(self.calls), 1)
        self.reader["actor"] = reader_actor
        replay = self.dispatch()
        self.assertTrue(replay["replay"])
        self.assertFalse(replay["dispatch_performed"])
        self.assertEqual(replay["disposition"], "PENDING")
        self.assertEqual(len(self.calls), 1)

    def test_connector_cancellation_with_authorized_reader_preserves_exception_and_never_resends(self):
        failure = asyncio.CancelledError("protected custody cancellation")
        def cancellation(payload):
            self.connector(payload)
            raise failure
        with self.assertRaises(asyncio.CancelledError) as error:
            self.dispatch(cancellation)
        self.assertIs(error.exception, failure)
        self.assert_consumed(True)
        self.assertEqual(self.host._flows[(self.organization, self.config["principal"])]["state"], self.path["flow_expose_result"]["state"])
        claim_key = (self.organization, self.instance, self.authorization["dispatch_intent_id"])
        self.assertEqual(self.host._dispatch_claims[claim_key]["status"], "PENDING")
        self.assertEqual(len(self.calls), 1)
        replay = self.dispatch()
        self.assertTrue(replay["replay"])
        self.assertFalse(replay["dispatch_performed"])
        self.assertEqual(len(self.calls), 1)

    def test_restart_after_exposure_retains_claim_and_never_invokes_again(self):
        self.dispatch()
        checkpoint = self.host.export_checkpoint(self.responses)
        self.host = FlowReferenceHost.from_checkpoint(Consumer(), self.host._current_reader, self.host._authenticate_event,
            self.host._authenticate_authority, checkpoint)
        self.assertTrue(self.dispatch()["replay"])
        self.assertEqual(len(self.calls), 1)
        self.assert_consumed(True)


if __name__ == "__main__": unittest.main()
