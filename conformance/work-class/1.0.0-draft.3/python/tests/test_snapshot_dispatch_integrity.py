from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from consumer import Consumer
from implementation import dispatch_gate, lifecycle
from implementation.common import PREFIX, digest
from test_dispatch_gate import bind_event


def case(number, group="snapshot-eligibility", prefix="C3-SNAPSHOT"):
    return json.loads((ROOT.parent / "cases" / group / f"{prefix}-{number:03}.json").read_text())["input"]


def dispatch_event(state, row, receipt):
    permit = next(permit for permit in state["permits"] if permit["permit_id"] == row["permit_digest"])
    event = {"schema": PREFIX + "runtime-event", "kind": "DISPATCH_OBSERVED", "event_id": row["event_id"],
             "instance_id": state["instance_id"], "expected_state_revision": str(int(receipt["sequence"]) - 1),
             "expected_state_digest": receipt["state_before_digest"], "permit": copy.deepcopy(permit),
             **{key: copy.deepcopy(row[key]) for key in ("native_request", "connector", "attempt", "acknowledgement", "clock_revision")}}
    if "authorization_digest" in row:
        event["authorization_digest"] = row["authorization_digest"]
    return event


def reseal_last_dispatch(state, event_digest=None):
    receipt = state["receipts"][-1]
    row = next(row for row in state["dispatches"] if row["event_id"] == receipt["event_id"])
    row["dispatch_attempt_digest"] = digest("dispatch-attempt", {"permit_id": row["permit_digest"],
        **{key: row[key] for key in ("native_request", "connector", "attempt")}})
    row["event_digest"] = event_digest or digest("runtime-event", dispatch_event(state, row, receipt))
    row["dispatch_digest"] = digest("dispatch", {key: value for key, value in row.items() if key != "dispatch_digest"})
    state["dispatches"].sort(key=lambda row: row["dispatch_digest"])
    core = copy.deepcopy(state)
    core["receipts"] = []; core["replays"] = []
    receipt["event_digest"] = row["event_digest"]
    receipt["state_after_core_digest"] = digest("work-state-core", core)
    receipt["decision_id"] = digest("decision-receipt", {key: value for key, value in receipt.items() if key != "decision_id"})
    replay = next(row for row in state["replays"] if row["event_id"] == receipt["event_id"])
    replay.update(event_digest=receipt["event_digest"], decision_receipt_digest=receipt["decision_id"],
        decision=copy.deepcopy(receipt), transition_state_digest=receipt["state_after_core_digest"])
    replay["transaction_digest"] = digest("lifecycle-transaction", {
        "state_before_digest": receipt["state_before_digest"], "event_digest": receipt["event_digest"],
        "decision_receipt_digest": receipt["decision_id"], "state_after_core_digest": receipt["state_after_core_digest"],
        "budget_results": replay["budget_results"],
    })
    return row


class SnapshotDispatchIntegrityTests(unittest.TestCase):
    def admitted(self, request):
        result = Consumer().step(request)
        self.assertEqual(result["status"], "STEP", result)
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))
        return result

    def assert_invalid_restart(self, request, state):
        row = next(row for row in state["dispatches"] if row["event_id"] == state["receipts"][-1]["event_id"])
        self.assertFalse(dispatch_gate.dispatch_integrity(state, request["definition"], row))
        restarted = bind_event(request, state)
        restarted["event"] = {"schema": PREFIX + "runtime-event", "kind": "CLOCK", "event_id": "fresh-restart-clock",
            "instance_id": state["instance_id"], "expected_state_revision": state["revision"],
            "expected_state_digest": lifecycle.state_digest(state), "clock": {"source": "authority-clock", "revision": "20",
                "status": "AVAILABLE", "observed_time": "2026-09-10T04:40:00Z", "evidence_digest": "sha256:" + "a" * 64},
            "activation_clocks": []}
        result = Consumer().step(restarted)
        self.assertEqual((result["status"], result["code"]), ("REFUSED", "STATE_INVALID"))
        self.assertEqual(result["state"], state)

    def test_rehashed_changed_request_cannot_claim_clean_dispatch(self):
        request = case(16)
        result = self.admitted(request)
        state = copy.deepcopy(result["state"])
        row = state["dispatches"][0]
        next(field for field in row["native_request"]["fields"] if field["name"] == "amount")["value"]["value"] = "151"
        permit = request["event"]["permit"]
        row["attempt"]["request_digest"] = digest("dispatch-native-request", {"instance_id": state["instance_id"],
            "occurrence_id": permit["occurrence"]["occurrence_id"], **row["native_request"]})
        reseal_last_dispatch(state)
        self.assert_invalid_restart(request, state)

    def test_legitimate_changed_request_is_retained_disputed(self):
        request = case(16)
        event = request["event"]
        next(field for field in event["native_request"]["fields"] if field["name"] == "amount")["value"]["value"] = "151"
        event["attempt"]["request_digest"] = digest("dispatch-native-request", {"instance_id": event["instance_id"],
            "occurrence_id": event["permit"]["occurrence"]["occurrence_id"], **event["native_request"]})
        result = self.admitted(request)
        self.assertEqual(result["decision"]["disposition"], "DISPUTED")
        self.assertEqual(result["decision"]["reason_codes"], ["NATIVE_ARGUMENT_MISMATCH"])

    def test_rehashed_event_request_connector_clock_and_timeline_corruption(self):
        request = case(16)
        result = self.admitted(request)
        mutations = {
            "request-digest": lambda row: row["attempt"].update(request_digest="sha256:" + "b" * 64),
            "connector-digest": lambda row: row["connector"].update(binding_digest="sha256:" + "b" * 64),
            "missing-clock": lambda row: row.update(clock_revision="19"),
            "attempt-after-clock": lambda row: row["attempt"].update(attempted_at="2026-09-10T04:30:01Z"),
            "missing-base-reason": lambda row: row["attempt"].update(status="UNKNOWN"),
            "acknowledgement-after-clock": lambda row: row["acknowledgement"].update(status="ACCEPTED", reference="ack", observed_at="2026-09-10T04:30:01Z"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                state = copy.deepcopy(result["state"])
                mutate(state["dispatches"][0])
                reseal_last_dispatch(state)
                self.assert_invalid_restart(request, state)
        state = copy.deepcopy(result["state"])
        reseal_last_dispatch(state, event_digest="sha256:" + "b" * 64)
        self.assert_invalid_restart(request, state)

    def test_expired_and_superseded_dispatch_facts_are_recomputed(self):
        for request, missing in ((case(20), "PERMIT_EXPIRED"), (case(175, "permit-renewal", "D2"), "PERMIT_SUPERSEDED")):
            with self.subTest(reason=missing):
                result = self.admitted(request)
                self.assertIn(missing, result["decision"]["reason_codes"])
                state = copy.deepcopy(result["state"])
                receipt = state["receipts"][-1]
                receipt["reason_codes"].remove(missing)
                next(detail for detail in receipt["details"] if detail["kind"] == "DISPATCH")["reasons"].remove(missing)
                reseal_last_dispatch(state)
                self.assert_invalid_restart(request, state)

    def test_retry_consumption_and_terminal_late_dispatch_are_recomputed(self):
        self.admitted(case(18))
        for number in (16, 24):
            with self.subTest(number=number):
                request = case(number)
                result = self.admitted(request)
                if number == 16:
                    request = bind_event(request, result["state"])
                    request["event"]["event_id"] = "fresh-attempt-after-consumption"
                    request["event"]["attempt"]["attempt_id"] = "second-physical-attempt"
                    result = self.admitted(request)
                self.assertEqual(result["decision"]["disposition"], "DISPUTED")
                self.assertIn("LATE_OR_PROHIBITED_DISPATCH", result["decision"]["reason_codes"])
                state = copy.deepcopy(result["state"])
                receipt = state["receipts"][-1]
                receipt["reason_codes"].remove("LATE_OR_PROHIBITED_DISPATCH")
                next(detail for detail in receipt["details"] if detail["kind"] == "DISPATCH")["reasons"].remove("LATE_OR_PROHIBITED_DISPATCH")
                reseal_last_dispatch(state)
                self.assert_invalid_restart(request, state)

    def test_optional_retained_authorization_cannot_disappear_from_history(self):
        request = case(29)
        result = self.admitted(request)
        state = copy.deepcopy(result["state"])
        row = next(row for row in state["dispatches"] if row["event_id"] == request["event"]["event_id"])
        del row["authorization_digest"]
        reseal_last_dispatch(state)
        self.assert_invalid_restart(request, state)

    def test_acknowledgement_update_preserves_prior_attempt_facts(self):
        for request in (case(16), case(24)):
            with self.subTest(event_id=request["event"]["event_id"]):
                first = self.admitted(request)
                update = bind_event(request, first["state"])
                update["event"]["event_id"] += "-acknowledged"
                update["event"]["acknowledgement"] = {"status": "ACCEPTED", "reference": "later-ack", "observed_at": request["event"]["attempt"]["attempted_at"]}
                updated = self.admitted(update)
                self.assertEqual(updated["state"]["active"], first["state"]["active"])
                self.assertEqual(updated["state"]["status"], first["state"]["status"])
                state = copy.deepcopy(updated["state"])
                row = next(row for row in state["dispatches"] if row["event_id"] == update["event"]["event_id"])
                row["connector"]["id"] = "different-connector"
                row["connector"]["binding_digest"] = digest("connector-binding", {key: row["connector"][key] for key in ("id", "version")})
                reseal_last_dispatch(state)
                self.assert_invalid_restart(update, state)

    def test_stopped_proposal_and_retained_wrong_pin_refusals(self):
        for number, code in ((22, "INSTANCE_NOT_ACTIVE"), (31, "VERSION_UNSUPPORTED"), (32, "STATE_INVALID")):
            with self.subTest(number=number):
                result = Consumer().step(case(number))
                self.assertEqual((result["status"], result["code"]), ("REFUSED", code))

    def test_timing_dispatch_reconstructs_complete_decision_details(self):
        for number, group, prefix in ((4, "sepsis-timing", "C3-ST"), (35, "sepsis-timing", "C3-ST"),
                (64, "sepsis-timing", "C3-ST"), (23, "timing-recovery", "C3-TR")):
            with self.subTest(group=group, number=number):
                request = case(number, group, prefix)
                result = self.admitted(request)
                row = next(row for row in result["state"]["dispatches"] if row["event_id"] == request["event"]["event_id"])
                self.assertTrue(dispatch_gate.dispatch_integrity(result["state"], request["definition"], row))


if __name__ == "__main__":
    unittest.main()
