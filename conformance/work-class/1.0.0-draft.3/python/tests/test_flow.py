from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT.parent / "review")]

import flow_fixture as f
from consumer import Consumer
from implementation import dispatch_gate, flow
from implementation.common import PROTOCOL, Refusal, canonical, digest, parse_json
from implementation.flow_host import FlowReferenceHost, MAX_FRAME_BYTES, bounded_frame


class FlowFixture:
    def setUp(self):
        self.config = f.configuration(principal="bank", registry_id="bank-flow", scope="case-scope",
            restriction_id="bank-only", meaning="Internal investigation")
        self.created, self.created_result = f.create(self.config, context_id="agent", actor="agent-01",
            scope="case-scope", purpose="investigation", ceiling=["bank-only"])
        self.assertEqual(Consumer().flow_step(self.created), self.created_result)

    def read(self, state=None, name="read-facts", restricted=True):
        return f.read(self.config, state or self.created_result["state"],
            f.descriptor(name, scope="case-scope", restrictions=["bank-only"] if restricted else []),
            context_id="agent", role="agent-role", event_id=name)


class FlowTests(FlowFixture, unittest.TestCase):
    def test_generic_correction_preserves_explicit_empty_flow_evidence(self):
        request = json.loads((ROOT.parent / "cases/equipment-correction/C3-ER-001.json").read_text())["input"]
        omitted = Consumer().check_evidence(request)
        self.assertEqual(omitted["status"], "EVIDENCE_VALID")
        correction = request["correction"]
        correction["correction_authority_input"]["flow_bases"] = []
        correction["provenance_digest"] = digest("source-correction-provenance",
            {name: value for name, value in correction.items() if name != "provenance_digest"})
        retained = Consumer().check_evidence(request)
        self.assertEqual(retained["status"], "EVIDENCE_VALID")
        self.assertNotEqual(retained["correction_authority_result"]["evidence_digest"], omitted["correction_authority_result"]["evidence_digest"])

    def test_disabled_flow_role_omits_operation_and_refuses_valid_flow_input(self):
        requests = [{"protocol": PROTOCOL, "request_id": "disabled-capabilities", "operation": "capabilities", "input": {}},
            {"protocol": PROTOCOL, "request_id": "disabled-flow", "operation": "flow-step", "input": self.created}]
        process = subprocess.run([sys.executable, "-B", str(ROOT / "adapter.py")],
            input=b"".join(canonical(row) + b"\n" for row in requests), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "WORK_CLASS_ADAPTER_ROLES": "AUTHORITY_EVALUATOR,LINEAR_WORK_RUNTIME"}, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        capabilities, refused = [parse_json(row)["result"] for row in process.stdout.splitlines()]
        self.assertNotIn("FLOW_TRANSITIONS", capabilities["roles"])
        self.assertNotIn("flow-step", capabilities["operations"])
        self.assertEqual(refused, {"status": "REFUSED", "code": "ROLE_UNSUPPORTED", "path": ""})

    def test_context_limit_refuses_without_changing_last_admitted_state(self):
        current = self.created_result["state"]
        for index in range(2, 17):
            supplied, expected = f.create(self.config, current, context_id="context-" + str(index),
                actor="actor-" + str(index), scope="case-scope", purpose="investigation", ceiling=["bank-only"])
            self.assertEqual(Consumer().flow_step(supplied), expected)
            current = expected["state"]
        supplied, _ = f.create(self.config, current, context_id="context-17", actor="actor-17",
            scope="case-scope", purpose="investigation", ceiling=["bank-only"])
        self.assertEqual(Consumer().flow_step(supplied), f.refusal(supplied, "LIMIT_EXCEEDED"))

    def test_read_and_import_preserve_current_sender_and_historical_artifact(self):
        clean, clean_result = self.read(name="read-clean", restricted=False)
        self.assertEqual(Consumer().flow_step(clean), clean_result)
        types = [{"id": "TEXT", "kind": "STRING", "unit": None, "nonnegative": False}]
        fields = [{"name": "body", "value": {"type_ref": "TEXT", "value": "independent facts"}}]
        materialize, materialized = f.materialize(self.config, clean_result["state"], context_id="agent",
            artifact_id="clean-artifact", types=types, native_fields=fields)
        self.assertEqual(Consumer().flow_step(materialize), materialized)
        restricted, restricted_result = self.read(materialized["state"], name="read-restricted")
        self.assertEqual(Consumer().flow_step(restricted), restricted_result)
        create, receiver = f.create(self.config, restricted_result["state"], context_id="summary", actor="summary-01",
            scope="case-scope", purpose="summarize", ceiling=["bank-only"])
        self.assertEqual(Consumer().flow_step(create), receiver)
        supplied, expected = f.import_artifact(self.config, receiver["state"], sender_id="agent", receiver_id="summary",
            artifact_id="clean-artifact", event_id="import-clean-artifact", receiver_role="summary-role", sender_role="agent-role")
        self.assertEqual(Consumer().flow_step(supplied), expected)
        self.assertEqual(next(row for row in expected["state"]["core"]["contexts"] if row["id"] == "summary")["restrictions"], ["bank-only"])

    def test_replay_requires_current_reader_and_has_no_fresh_transition(self):
        supplied, expected = self.read()
        self.assertEqual(Consumer().flow_step(supplied), expected)
        replay = copy.deepcopy(supplied)
        replay.update(state=expected["state"], state_digest=expected["state_digest"])
        f.refresh_response(replay)
        self.assertEqual(Consumer().flow_step(replay), f.replay(replay))
        replay["response_authority"]["proposal"]["executor"]["role"] = "untrusted-reader"
        refused = Consumer().flow_step(replay)
        self.assertEqual(refused["status"], "REFUSED")
        self.assertEqual(set(refused), {"status", "code", "path"})

    def test_resealed_history_does_not_remove_origin_or_restriction(self):
        supplied, expected = self.read()
        forged = copy.deepcopy(expected["state"])
        forged["core"]["contexts"][0]["restrictions"] = []
        forged["core"]["contexts"][0]["origins"] = []
        with self.assertRaises(Refusal) as error:
            flow.validate_state(self.config, forged, digest("flow-state", forged))
        self.assertEqual(error.exception.code, "STATE_INVALID")

    def test_same_issuance_cannot_change_classification(self):
        supplied, expected = self.read()
        changed = copy.deepcopy(supplied["event"]["payload"]["source"])
        changed["restrictions"] = []
        next_request, _ = f.read(self.config, expected["state"], changed,
            context_id="agent", role="agent-role", event_id="read-relabeled")
        self.assertEqual(Consumer().flow_step(next_request), f.refusal(next_request, "DEPENDENCY_MISMATCH"))

    def test_same_intent_cannot_retry_with_a_new_event_and_claim(self):
        supplied, expected = self.read()
        retry, _ = self.read(expected["state"], name="retry-facts")
        retry["event"]["payload"]["intent_id"] = supplied["event"]["payload"]["intent_id"]
        f.resign_request(retry, access=True)
        self.assertEqual(Consumer().flow_step(retry), f.refusal(retry, "DEPENDENCY_MISMATCH"))

    def test_control_authority_limit_applies_with_omitted_and_empty_flow_members(self):
        read, read_result = self.read()
        create, receiver = f.create(self.config, read_result["state"], context_id="receiver", actor="receiver-01",
            scope="case-scope", purpose="review", ceiling=["bank-only"])
        types = [{"id": "TEXT", "kind": "STRING", "unit": None, "nonnegative": False}]
        fields = [{"name": "body", "value": {"type_ref": "TEXT", "value": "exact retained artifact"}}]
        _, materialized = f.materialize(self.config, receiver["state"], context_id="agent",
            artifact_id="limit-artifact", types=types, native_fields=fields)
        imported, _ = f.import_artifact(self.config, materialized["state"], sender_id="agent", receiver_id="receiver",
            artifact_id="limit-artifact", event_id="import-limit", receiver_role="receiver-role", sender_role="agent-role")
        selected = [(self.created["response_authority"], flow.response_subject(self.created), self.config["response_operation"], True),
            (read["event"]["payload"]["access_authority"], flow.control_subject(self.config, read["event"]), self.config["access_operation"], False),
            (imported["event"]["payload"]["access_authority"], flow.control_subject(self.config, imported["event"]), self.config["access_operation"], False),
            (imported["event"]["payload"]["transfer_authority"], flow.control_subject(self.config, imported["event"]), self.config["transfer_operation"], False)]
        for authority, subject, operation, response in selected:
            for empty in (False, True):
                with self.subTest(operation=operation, empty=empty):
                    supplied = copy.deepcopy(authority)
                    if empty:
                        supplied["flow_bases"] = []
                        supplied["envelope"]["flow_requirements"] = []
                    supplied["source"]["obligations"][0]["text"] = ""
                    supplied["source"]["obligations"][0]["text"] = "x" * (1048576 - len(canonical(supplied)))
                    f.rebind_outer(supplied)
                    self.assertEqual(len(canonical(supplied)), 1048576)
                    self.assertEqual(flow._access(self.config, supplied, subject, operation, response=response)["status"], "READY_FOR_RESERVATION")
                    supplied["source"]["obligations"][0]["text"] += "x"
                    self.assertEqual(len(canonical(supplied)), 1048577)
                    with mock.patch("implementation.authority.evaluate_authority") as evaluator:
                        with self.assertRaises(Refusal) as error:
                            flow._access(self.config, supplied, subject, operation, response=response)
                        self.assertEqual(error.exception.code, "LIMIT_EXCEEDED")
                        evaluator.assert_not_called()

    def test_malformed_direct_flow_inputs_return_closed_refusals(self):
        for value in (1, "\ud800"):
            malformed = copy.deepcopy(self.created)
            malformed["event"]["payload"]["purpose"] = value
            with self.subTest(value=repr(value)):
                self.assertEqual(Consumer().flow_step(malformed), {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""})

    def test_empty_basis_presence_is_immutable_while_current_state_can_refresh(self):
        supplied, _ = self.read()
        authority = supplied["event"]["payload"]["access_authority"]
        empty = copy.deepcopy(authority)
        empty["flow_bases"] = []
        self.assertFalse(dispatch_gate.immutable_binding(authority, empty))
        initial = {"flow_bases": [{"requirement_id": "flow", "configuration": self.config,
            "state": {"old": True}, "state_digest": "old", "selection": {}, "released_restrictions": []}]}
        refreshed = copy.deepcopy(initial)
        refreshed["flow_bases"][0].update(state={"new": True}, state_digest="new", selection={"at": f.BANK_AT})
        self.assertTrue(dispatch_gate.immutable_binding(initial, refreshed))
        refreshed["flow_bases"][0]["released_restrictions"] = ["bank-only"]
        self.assertFalse(dispatch_gate.immutable_binding(initial, refreshed))


class FlowHostTests(FlowFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.actual_reader = {"actor": "protected-host-reader-01", "role": self.config["response_role"],
            "principal": self.config["principal"], "clock": {"source": self.config["clock_source"], "status": "AVAILABLE", "instant": f.BANK_AT}}
        self.authenticated = {}
        self.authenticated_authorities = set()
        self.host = FlowReferenceHost(Consumer(), lambda: copy.deepcopy(self.actual_reader),
            lambda configuration, event, evidence: self.authenticated.get(canonical(event)) == canonical(evidence),
            lambda configuration, authority: canonical(authority) in self.authenticated_authorities)
        self.host.install_flow("org", self.config)
        self.authorize(self.created)
        self.assertEqual(self.host.submit_flow("org", self.created), self.created_result)

    def authorize(self, request):
        self.authenticated[canonical(request["event"])] = canonical(request["host_evidence"])
        self.authenticated_authorities.add(canonical(request["response_authority"]))
        for name in ("access_authority", "transfer_authority"):
            if name in request["event"]["payload"]:
                self.authenticated_authorities.add(canonical(request["event"]["payload"][name]))

    def test_claim_commit_precedes_partial_error_tool_delivery(self):
        for name in ("partial", "existence-error", "tool-state"):
            current = self.host._flows[("org", "bank")]["state"]
            supplied, expected = self.read(current, name=name)
            self.authorize(supplied)
            delivered = []
            def callback(payload):
                retained = self.host._flows[("org", "bank")]["state"]["core"]
                self.assertIn(payload["claim_id"], [row["id"] for row in retained["claims"]])
                self.assertIn("bank-only", retained["contexts"][0]["restrictions"])
                body = (payload["source"]["record_id"] + "/" + payload["source"]["revision"]).encode()
                self.assertEqual(payload["source"]["content_digest"], "sha256:" + hashlib.sha256(body).hexdigest())
                delivered.append(body)
                with self.assertRaises(Refusal):
                    self.host.submit_flow("org", supplied)
            self.host._input_routes.pop(("org", "bank", "agent"), None)
            self.host.install_input_route("org", "bank", "agent", "agent-01", callback)
            self.assertEqual(self.host.submit_flow("org", supplied, deliver=True), expected)
            self.assertEqual(len(delivered), 1)

    def test_retained_read_bytes_are_checked_after_claim_and_mismatch_never_delivers(self):
        source_path = Path(__file__).with_name("fixtures") / "protected-input.txt"
        retained = source_path.read_bytes()
        deliveries, callbacks = [], []
        def callback(payload):
            callbacks.append(payload["claim_id"])
            current = self.host._flows[("org", "bank")]["state"]["core"]
            self.assertIn(payload["claim_id"], [row["id"] for row in current["claims"]])
            self.assertIn("bank-only", current["contexts"][0]["restrictions"])
            actual = source_path.read_bytes()
            if "sha256:" + hashlib.sha256(actual).hexdigest() != payload["source"]["content_digest"]:
                raise Refusal("DIGEST_MISMATCH")
            deliveries.append(actual)
        # Exact byte retrieval and validation belong to this trusted adapter callback.
        self.host.install_input_route("org", "bank", "agent", "agent-01", callback)
        for name, mismatch, cut in (("retained-read", False, None), ("descriptor-mismatch", True, None), ("retained-postclaim", False, "POST_CLAIM")):
            source = f.descriptor(name, scope="case-scope", restrictions=["bank-only"])
            source["content_digest"] = "sha256:" + hashlib.sha256(retained if not mismatch else retained + b"changed").hexdigest()
            supplied, expected = f.read(self.config, self.host._flows[("org", "bank")]["state"], source,
                context_id="agent", role="agent-role", event_id=name)
            self.authorize(supplied)
            if mismatch:
                with self.assertRaises(Refusal) as error:
                    self.host.submit_flow("org", supplied, deliver=True)
                self.assertEqual(error.exception.code, "DIGEST_MISMATCH")
            else:
                self.assertEqual(self.host.submit_flow("org", supplied, deliver=True, failure_stage=cut), expected)
            self.assertEqual(self.host._flows[("org", "bank")]["state"], expected["state"])
            replay = copy.deepcopy(supplied)
            replay.update(state=expected["state"], state_digest=expected["state_digest"])
            f.refresh_response(replay)
            self.authorize(replay)
            count = len(callbacks)
            self.assertTrue(self.host.submit_flow("org", replay, deliver=True)["replay"])
            self.assertEqual(len(callbacks), count)
        self.assertEqual(deliveries, [retained])
        self.assertEqual(len(callbacks), 2)

    def test_retained_import_bytes_follow_exact_artifact_and_postclaim_cut(self):
        source_path = Path(__file__).with_name("fixtures") / "protected-input.txt"
        retained = source_path.read_bytes()
        read, read_result = self.read(name="before-retained-import")
        self.authorize(read)
        self.assertEqual(self.host.submit_flow("org", read), read_result)
        types = [{"id": "TEXT", "kind": "STRING", "unit": None, "nonnegative": False}]
        fields = [{"name": "body", "value": {"type_ref": "TEXT", "value": retained.decode("utf-8")}}]
        materialize, materialized = f.materialize(self.config, read_result["state"], context_id="agent",
            artifact_id="retained-artifact", types=types, native_fields=fields)
        self.authorize(materialize)
        self.assertEqual(self.host.submit_flow("org", materialize), materialized)
        create, receiver = f.create(self.config, materialized["state"], context_id="receiver", actor="receiver-01",
            scope="case-scope", purpose="review", ceiling=["bank-only"])
        self.authorize(create)
        self.assertEqual(self.host.submit_flow("org", create), receiver)
        calls, delivered = [], []
        selected_path = source_path
        def callback(payload):
            core = self.host._flows[("org", "bank")]["state"]["core"]
            self.assertIn(payload["claim_id"], [row["id"] for row in core["claims"]])
            self.assertEqual(next(row for row in core["contexts"] if row["id"] == "receiver")["restrictions"], ["bank-only"])
            artifact = next(row for row in core["artifacts"] if row["id"] == payload["artifact_id"])
            actual = selected_path.read_bytes()
            calls.append(payload["claim_id"])
            if actual.decode("utf-8") != artifact["fields"][0]["value"]["value"]:
                raise Refusal("DIGEST_MISMATCH")
            delivered.append(actual)
        self.host.install_input_route("org", "bank", "receiver", "receiver-01", callback)
        for name, mismatch, cut in (("import-retained", False, None), ("import-retained-mismatch", True, None), ("import-retained-postclaim", False, "POST_CLAIM")):
            selected_path = source_path.with_name("protected-input-altered.txt") if mismatch else source_path
            supplied, expected = f.import_artifact(self.config, self.host._flows[("org", "bank")]["state"],
                sender_id="agent", receiver_id="receiver", artifact_id="retained-artifact", event_id=name,
                receiver_role="receiver-role", sender_role="agent-role")
            self.authorize(supplied)
            if mismatch:
                with self.assertRaises(Refusal) as error:
                    self.host.submit_flow("org", supplied, deliver=True)
                self.assertEqual(error.exception.code, "DIGEST_MISMATCH")
            else:
                self.assertEqual(self.host.submit_flow("org", supplied, deliver=True, failure_stage=cut), expected)
            self.assertEqual(self.host._flows[("org", "bank")]["state"], expected["state"])
        self.assertEqual(delivered, [retained])
        self.assertEqual(len(calls), 2)

    def test_canonical_input_limit_precedes_all_trusted_callbacks(self):
        supplied = copy.deepcopy(self.created)
        supplied["response_authority"]["source"]["obligations"][0]["text"] = ""
        supplied["response_authority"]["source"]["obligations"][0]["text"] = "x" * (16777217 - len(canonical(supplied)))
        self.assertEqual(len(canonical(supplied)), 16777217)
        with mock.patch.object(self.host, "_current_reader") as reader, mock.patch.object(self.host, "_authenticate_authority") as authenticate, mock.patch.object(self.host, "_authenticate_event") as event:
            self.assertEqual(self.host.submit_flow("org", supplied), {"status": "REFUSED", "code": "LIMIT_EXCEEDED", "path": ""})
            reader.assert_not_called()
            authenticate.assert_not_called()
            event.assert_not_called()

    def test_preclaim_failure_preserves_state_and_postclaim_failure_prevents_retry(self):
        supplied, expected = self.read()
        self.authorize(supplied)
        calls = []
        self.host.install_input_route("org", "bank", "agent", "agent-01", calls.append)
        self.assertEqual(self.host.submit_flow("org", supplied, deliver=True, failure_stage="PRE_CLAIM")["status"], "REFUSED")
        self.assertEqual(self.host._flows[("org", "bank")]["state"], self.created_result["state"])
        self.assertEqual(self.host.submit_flow("org", supplied, deliver=True, failure_stage="POST_CLAIM"), expected)
        replay = copy.deepcopy(supplied)
        replay.update(state=expected["state"], state_digest=expected["state_digest"])
        f.refresh_response(replay)
        self.authorize(replay)
        self.assertTrue(self.host.submit_flow("org", replay, deliver=True)["replay"])
        self.assertEqual(calls, [])

    def test_concurrent_deliveries_cannot_overwrite_accumulated_state(self):
        first, _ = self.read(name="first")
        second, _ = self.read(name="second")
        for request in (first, second):
            self.authorize(request)
        calls, results = [], []
        self.host.install_input_route("org", "bank", "agent", "agent-01", calls.append)
        barrier = threading.Barrier(2)
        def worker(request):
            barrier.wait()
            results.append(self.host.submit_flow("org", request, deliver=True))
        threads = [threading.Thread(target=worker, args=(request,)) for request in (first, second)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(sorted(row["status"] for row in results), ["REFUSED", "TRANSITION"])
        self.assertEqual(next(row for row in results if row["status"] == "REFUSED")["code"], "REVISION_CONFLICT")

    def test_host_authentication_and_actual_reader_precede_protected_output(self):
        supplied, _ = self.read()
        self.authenticated_authorities.add(canonical(supplied["response_authority"]))
        self.assertEqual(self.host.submit_flow("org", supplied)["code"], "EVIDENCE_UNAVAILABLE")
        self.authorize(supplied)
        self.actual_reader["actor"] = "untrusted-reader"
        self.assertEqual(self.host.submit_flow("org", supplied), {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""})
        self.assertEqual(self.host.public_status(), b"Unable to process this request.")

    def test_valid_carrier_does_not_authenticate_caller_asserted_authority(self):
        supplied, _ = self.read()
        self.authorize(supplied)
        supplied["response_authority"]["flow_bases"] = []
        self.assertEqual(Consumer().flow_step(supplied)["status"], "TRANSITION")
        self.assertEqual(self.host.submit_flow("org", supplied),
            {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""})
        self.assertEqual(self.host._flows[("org", "bank")]["state"], self.created_result["state"])

    def test_authority_withdrawn_during_delivery_is_checked_before_response(self):
        supplied, expected = self.read()
        self.authorize(supplied)
        def withdraw_response_authority(payload):
            self.authenticated_authorities.discard(canonical(supplied["response_authority"]))
            with self.assertRaises(Refusal):
                self.host.install_holdings("org", {}, None, None)
        self.host.install_input_route("org", "bank", "agent", "agent-01", withdraw_response_authority)
        self.assertEqual(self.host.submit_flow("org", supplied, deliver=True),
            {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""})
        self.assertEqual(self.host._flows[("org", "bank")]["state"], expected["state"])

    def test_provider_exception_after_reader_withdrawal_returns_no_protected_error(self):
        supplied, expected = self.read(name="withdrawal-error")
        self.authorize(supplied)
        def revoked_error(payload):
            self.actual_reader["actor"] = "revoked-reader"
            raise RuntimeError("protected provider diagnostic that must not return")
        self.host.install_input_route("org", "bank", "agent", "agent-01", revoked_error)
        self.assertEqual(self.host.submit_flow("org", supplied, deliver=True),
            {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""})
        self.assertEqual(self.host._flows[("org", "bank")]["state"], expected["state"])

    def test_delivery_cancellation_after_reader_withdrawal_retains_claim_and_returns_no_error(self):
        def revoked_error(payload):
            self.actual_reader["actor"] = "revoked-reader"
            raise failure
        self.host.install_input_route("org", "bank", "agent", "agent-01", revoked_error)
        for index, failure in enumerate((asyncio.CancelledError("protected cancellation"), BaseException("protected abort"))):
            with self.subTest(failure=type(failure).__name__):
                self.actual_reader["actor"] = "protected-host-reader-01"
                supplied, expected = self.read(self.host._flows[("org", "bank")]["state"], name="withdrawal-abort-" + str(index))
                self.authorize(supplied)
                self.assertEqual(self.host.submit_flow("org", supplied, deliver=True),
                    {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""})
                self.assertEqual(self.host._flows[("org", "bank")]["state"], expected["state"])
                self.assertFalse(self.host._exposure_in_progress)

    def test_delivery_failure_with_authorized_reader_preserves_original_exception_and_claim(self):
        def provider_error(payload):
            raise failure
        self.host.install_input_route("org", "bank", "agent", "agent-01", provider_error)
        failures = (RuntimeError("protected diagnostic"), asyncio.CancelledError("protected cancellation"), BaseException("protected abort"))
        for index, failure in enumerate(failures):
            with self.subTest(failure=type(failure).__name__):
                supplied, expected = self.read(self.host._flows[("org", "bank")]["state"], name="authorized-error-" + str(index))
                self.authorize(supplied)
                with self.assertRaises(type(failure)) as error:
                    self.host.submit_flow("org", supplied, deliver=True)
                self.assertIs(error.exception, failure)
                self.assertEqual(self.host._flows[("org", "bank")]["state"], expected["state"])
                self.assertFalse(self.host._exposure_in_progress)

    def test_all_protected_reader_inputs_are_preflighted_before_any_reader_callback(self):
        admitted = copy.deepcopy(self.created)
        admitted.update(state=self.created_result["state"], state_digest=self.created_result["state_digest"])
        f.refresh_response(admitted)
        self.authorize(admitted)
        invalid = copy.deepcopy(admitted)
        invalid["response_authority"]["source"]["obligations"][0]["text"] = ""
        padded = "x" * (16777217 - len(canonical(invalid)))
        for value in (padded, 1, "\ud800"):
            with self.subTest(value="oversized" if value == padded else repr(value)):
                invalid["response_authority"]["source"]["obligations"][0]["text"] = value
                if value == padded:
                    self.assertEqual(len(canonical(invalid)), 16777217)
                with mock.patch.object(self.host, "_current_reader") as reader, mock.patch.object(self.host, "_authenticate_authority") as authenticate:
                    with self.assertRaises(Refusal) as error:
                        self.host.snapshot("org", "uninstalled-business-instance", response_requests=[("org", admitted), ("org", invalid)])
                    self.assertEqual(error.exception.code, "ACCESS_NOT_ESTABLISHED")
                    reader.assert_not_called()
                    authenticate.assert_not_called()
                self.assertEqual(self.host._flows[("org", "bank")]["state"], self.created_result["state"])

    def test_inherited_inspection_cannot_return_protected_business_history(self):
        for inspect in (self.host.snapshot, self.host.pending_evidence, self.host.dispatch_claims, self.host.holdings_snapshot):
            with self.assertRaises(Refusal) as error:
                inspect("org", "uninstalled-business-instance")
            self.assertEqual(error.exception.code, "ACCESS_NOT_ESTABLISHED")

    def test_reader_revoked_during_read_retains_claim_and_returns_no_state(self):
        supplied, expected = self.read()
        self.authorize(supplied)
        delivered = []
        def revoke_reader(payload):
            delivered.append(payload)
            self.actual_reader["actor"] = "revoked-reader"
        self.host.install_input_route("org", "bank", "agent", "agent-01", revoke_reader)
        self.assertEqual(self.host.submit_flow("org", supplied, deliver=True),
            {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""})
        self.assertEqual(self.host._flows[("org", "bank")]["state"], expected["state"])
        self.assertEqual(len(delivered), 1)

    def test_raw_route_bounds_before_parse_and_does_not_treat_string_braces_as_depth(self):
        with mock.patch("implementation.flow_host.parse_json") as parser:
            for raw in (b" " * MAX_FRAME_BYTES + b"\n", b"[" * 129 + b"]" * 129 + b"\n"):
                with self.assertRaises(Refusal): bounded_frame(raw)
            parser.assert_not_called()
        self.assertEqual(bounded_frame(b'{"body":"[[[\\\"{{{"}\n'), {"body": '[[["{{{'})
        self.assertEqual(bounded_frame(b"[" * 128 + b"]" * 128 + b"\n"), self._nested_empty_arrays(128))

    def test_private_raw_frame_uses_one_terminal_lf_and_closed_bound_refusals(self):
        self.assertEqual(bounded_frame(b"{}\n"), {})
        self.assertEqual(bounded_frame(b"{}\r\n"), {})
        self.assertEqual(bounded_frame(b" " * (MAX_FRAME_BYTES - 3) + b"{}\n"), {})
        malformed = (b"{}", b"{}\n\n", b"{}\n{}\n", b'{"body":"\xff"}\n', b'{"body":"\\ud800"}\n', b'{"value":1}\n')
        for raw in malformed:
            with self.subTest(raw=repr(raw)):
                self.assertEqual(self.host.handle_flow_frame("org", raw), {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""})
        for raw in (b" " * (MAX_FRAME_BYTES - 2) + b"{}\n", b"[" * 129 + b"]" * 129 + b"\n"):
            with mock.patch.object(self.host, "_current_reader") as reader, mock.patch.object(self.host, "_authenticate_authority") as authenticate, mock.patch.object(self.host, "_authenticate_event") as event:
                self.assertEqual(self.host.handle_flow_frame("org", raw), {"status": "REFUSED", "code": "LIMIT_EXCEEDED", "path": ""})
                reader.assert_not_called()
                authenticate.assert_not_called()
                event.assert_not_called()

    @staticmethod
    def _nested_empty_arrays(depth):
        value = []
        for _ in range(depth - 1): value = [value]
        return value

    def test_checkpoint_requires_current_reader_and_reconstructs_history(self):
        supplied, expected = self.read()
        self.authorize(supplied)
        self.assertEqual(self.host.submit_flow("org", supplied), expected)
        access = copy.deepcopy(supplied)
        access.update(state=expected["state"], state_digest=expected["state_digest"])
        f.refresh_response(access)
        self.authorize(access)
        with self.assertRaises(Refusal): self.host.export_checkpoint()
        checkpoint = self.host.export_checkpoint([("org", access)])
        restarted = FlowReferenceHost.from_checkpoint(Consumer(), self.host._current_reader, self.host._authenticate_event, self.host._authenticate_authority, checkpoint)
        self.assertTrue(restarted.submit_flow("org", access)["replay"])
        checkpoint["flows"][("org", "bank")]["state"]["core"]["contexts"][0]["restrictions"] = []
        checkpoint["flows"][("org", "bank")]["state_digest"] = digest("flow-state", checkpoint["flows"][("org", "bank")]["state"])
        with self.assertRaises(Refusal):
            FlowReferenceHost.from_checkpoint(Consumer(), self.host._current_reader, self.host._authenticate_event, self.host._authenticate_authority, checkpoint)


if __name__ == "__main__":
    unittest.main()
