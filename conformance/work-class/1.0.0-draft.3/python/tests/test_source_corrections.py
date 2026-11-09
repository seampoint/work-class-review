from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from consumer import Consumer
from implementation import completion, lifecycle
from implementation.common import PIN, digest
from implementation.reference_host import SingleProcessReferenceHost
from test_dispatch_gate import bind_event
from test_foundations import rehash_last_lifecycle_decision


def supplied(group, prefix, number):
    return json.loads((ROOT.parent / "cases" / group / f"C3-{prefix}-{number:03}.json").read_text())["input"]


def rebind_native(state, outcome):
    event = outcome["source_event"]
    outcome["native_evidence"] = copy.deepcopy(event["native_evidence"])
    outcome["event_digest"] = digest("runtime-event", event)
    outcome["outcome_digest"] = digest("outcome", {name: value for name, value in outcome.items() if name != "outcome_digest"})
    receipt = next(row for row in state["receipts"] if row["event_id"] == outcome["event_id"])
    receipt["event_digest"] = outcome["event_digest"]
    receipt["state_before_digest"] = event["expected_state_digest"]
    replay = next(row for row in state["replays"] if row["event_id"] == outcome["event_id"])
    replay["event_digest"] = outcome["event_digest"]
    terminal = next((row for row in state.get("terminal_records", []) if row["event_id"] == outcome["event_id"]), None)
    if terminal is not None:
        basis = digest("decision-basis", completion.decision_basis(receipt, outcome))
        terminal.update(event_digest=outcome["event_digest"], decision_basis_digest=basis)
        terminal["terminal_digest"] = digest("terminal-record", {name: value for name, value in terminal.items() if name != "terminal_digest"})
        receipt.update(decision_basis_digest=basis, terminal_digest=terminal["terminal_digest"])
        for referral in state["referrals"]:
            if referral["event_id"] == outcome["event_id"]:
                referral.update(event_digest=outcome["event_digest"], decision_basis_digest=basis, terminal_digest=terminal["terminal_digest"], cause_digest=outcome["outcome_digest"])
                referral["referral_digest"] = digest("referral-intent", {name: value for name, value in referral.items() if name != "referral_digest"})
        state["terminal_records"].sort(key=lambda row: row["terminal_digest"])
        state["referrals"].sort(key=lambda row: row["referral_digest"])
    state["outcomes"].sort(key=lambda row: row["outcome_digest"])
    rehash_last_lifecycle_decision(state)


class SourceCorrectionTests(unittest.TestCase):
    def test_observed_request_requires_full_completion_inventory(self):
        request = supplied("equipment-completion", "EC", 1)
        event = request["event"]
        step = next(row for row in request["definition"]["steps"] if row["id"] == event["permit"]["occurrence"]["step_id"])
        dispatch = next(row for row in request["state"]["dispatches"] if row["dispatch_digest"] == event["dispatch_digest"])
        native = event["native_evidence"]
        self.assertEqual(lifecycle._project_observed_request(request, dispatch, step, native), native["attributed_request"])
        carrier = step["completion"]
        names = [carrier["provider_record_identity"]["field"], carrier["event_time_identity"]["field"], carrier["status_field"]] + [row["name"] for row in carrier["additional_fields"]]
        for name in names:
            with self.subTest(field=name):
                changed = copy.deepcopy(native)
                next(row for row in changed["actual_fields"] if row["name"] == name)["value"]["value"] = "wrong"
                self.assertIsNone(lifecycle._project_observed_request(request, dispatch, step, changed))
        failed = copy.deepcopy(native)
        next(row for row in failed["actual_fields"] if row["name"] == carrier["status_field"])["value"] = copy.deepcopy(carrier["failure_values"][0])
        self.assertEqual(lifecycle._project_observed_request(request, dispatch, step, failed), failed["attributed_request"])

    def test_administrative_and_business_corrections_leave_inputs_immutable(self):
        for number, approved in ((1, False), (5, True)):
            request = supplied("equipment-correction", "ER", number)
            original = copy.deepcopy(request)
            result = Consumer().check_evidence(request)
            self.assertEqual(result["status"], "EVIDENCE_VALID")
            self.assertEqual(result["new_approval_result"] is not None, approved)
            self.assertEqual(request, original)
            self.assertNotIn("state", result)
            self.assertNotIn("budget_results", result)

    def test_correction_requires_original_commitment_and_current_authority(self):
        request = supplied("equipment-correction", "ER", 1)
        native = request["original_record"]
        native["provider_revision"] = "changed-revision"
        self.assertEqual(Consumer().check_evidence(request)["code"], "BINDING_MISMATCH")
        request = supplied("equipment-correction", "ER", 1)
        correction = request["correction"]
        correction["correction_authority_input"]["clock"]["instant"] = "2026-09-12T15:00:01Z"
        correction["provenance_digest"] = digest("source-correction-provenance", {name: value for name, value in correction.items() if name != "provenance_digest"})
        self.assertEqual(Consumer().check_evidence(request)["code"], "EVIDENCE_UNAVAILABLE")

    def test_fully_rehashed_native_event_still_recomputes_request_values(self):
        request = supplied("equipment-retained-evidence", "EVE", 1)
        state = copy.deepcopy(request["state"])
        self.assertTrue(lifecycle._validate_state_integrity(state, request["definition"]))
        outcome = state["outcomes"][0]
        previous = digest("native-evidence", outcome["native_evidence"])
        amount = next(row for row in outcome["source_event"]["native_evidence"]["actual_fields"] if row["name"] == "amount")
        amount["value"]["value"] = "151"
        evidence_digest = digest("native-evidence", outcome["source_event"]["native_evidence"])
        for completed in state["completed"]:
            if completed["evidence_digest"] == previous:
                completed["evidence_digest"] = evidence_digest
        rebind_native(state, outcome)
        self.assertFalse(lifecycle._validate_state_integrity(state, request["definition"]))

    def test_fully_rehashed_native_event_cannot_replace_prior_root(self):
        request = supplied("equipment-retained-evidence", "EVE", 1)
        state = copy.deepcopy(request["state"])
        outcome = state["outcomes"][0]
        outcome["source_event"]["expected_state_digest"] = digest("unrelated-state", {})
        rebind_native(state, outcome)
        self.assertFalse(lifecycle._validate_state_integrity(state, request["definition"]))

    def test_no_effect_authorization_is_recomputed_after_full_rehash(self):
        request = supplied("equipment-completion", "EC", 1)
        event = request["event"]
        event["event_id"] = "approved-no-effect-stop"
        native = event["native_evidence"]
        step = next(row for row in request["definition"]["steps"] if row["id"] == event["permit"]["occurrence"]["step_id"])
        native.update(status="NO_EFFECT_ESTABLISHED", actual_fields=[], collections=[], event_time=None, rules_out_past_and_future_effects=True)
        for name in ("provider", "source", "record_type"):
            native[name] = step["completion"]["no_effect_" + name]
        subject = {"specification_pin": PIN, "work_class_digest": request["definition_digest"], "instance_id": event["instance_id"], "occurrence_id": event["permit"]["occurrence"]["occurrence_id"], "permit_id": event["permit"]["permit_id"], "dispatch_digest": event["dispatch_digest"], "native_evidence_digest": digest("native-evidence", native)}
        event["completion_authorization"] = {"schema": "seampoint.work-class/1.0.0-draft.3/evidence-record", "evidence_id": "no-effect-approval", "kind": "ORGANIZATIONAL_AUTHORIZATION", "status": "ACCEPTED", "subject_digest": digest("no-effect-completion", subject), "organization_id": request["state"]["deployment_organization_id"], "authorizer_id": "completion-reviewer", "authorization_scope": sorted(subject.values(), key=str.encode), "recorded_at": native["observed_at"], "expires_at": lifecycle._add_seconds(native["observed_at"], 60), "provenance_digest": digest("approval-provenance", {})}
        result = Consumer().step(request)
        self.assertEqual(result["state"]["status"], "STOPPED")
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))
        state = copy.deepcopy(result["state"])
        outcome = next(row for row in state["outcomes"] if row["event_id"] == event["event_id"])
        outcome["source_event"]["completion_authorization"]["organization_id"] = "another-organization"
        rebind_native(state, outcome)
        self.assertFalse(lifecycle._validate_state_integrity(state, request["definition"]))

    def test_retained_registry_input_is_recomputed_after_full_rehash(self):
        request = supplied("equipment-completion", "EC", 67)
        result = Consumer().step(request)
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))
        state = copy.deepcopy(result["state"])
        outcome = next(row for row in state["outcomes"] if row["event_id"] == request["event"]["event_id"])
        outcome["source_event"]["budget_inputs"][0]["affected_anchors"] = ["substituted-anchor"]
        rebind_native(state, outcome)
        self.assertFalse(lifecycle._validate_state_integrity(state, request["definition"]))

    def test_rehashed_proposal_cannot_keep_old_refusal_after_passing_observation(self):
        request = supplied("equipment-referrals", "EAR", 3)
        result = Consumer().step(request)
        state = copy.deepcopy(result["state"])
        self.assertTrue(lifecycle._validate_state_integrity(state, request["definition"]))
        evaluation = state["proposal_authority_evaluations"][0]
        event = evaluation["event"]
        observation = next(row for row in event["authority_input"]["observations"] if row["query"].get("requirement_id") == "current-safety")
        observation["fields"][0]["value"]["value"] = True
        event["observation_digests"] = sorted({digest("authority-observation", row) for row in event["authority_input"]["observations"]})
        # The frozen attack vector also rebinds every referral and decision commitment.
        attack = supplied("equipment-retained-evidence", "EVE", 7)
        self.assertFalse(lifecycle._validate_state_integrity(attack["state"], attack["definition"]))
        evaluation["evaluation_digest"] = digest("proposal-authority-evaluation", {name: value for name, value in evaluation.items() if name != "evaluation_digest"})
        self.assertFalse(lifecycle._validate_state_integrity(state, request["definition"]))

    def test_authority_referral_commit_failure_keeps_evaluation_and_log_absent(self):
        review = str(ROOT.parent / "review")
        if review not in sys.path:
            sys.path.insert(0, review)
        base = runpy.run_path(str(ROOT.parent / "review/build-equipment-referral-cases.py"))["referral_base"]()
        request = supplied("equipment-referrals", "EAR", 3)
        host = SingleProcessReferenceHost(Consumer())
        deployment = base["deploy_input"]
        organization = deployment["deployment_authorization"]["organization_id"]
        instance = deployment["instance_id"]
        host.install(deployment)
        initial = host.snapshot(organization, instance)["state"]
        clock_event = copy.deepcopy(base["clock_event"])
        clocked = host.submit(organization, bind_event({**request, "event": clock_event}, initial))["transition"]
        withheld = bind_event(request, clocked["state"])
        before = host.snapshot(organization, instance)
        log = copy.deepcopy(host._roots[(organization, instance)]["event_log"])
        failure = host.submit(organization, withheld, failure_reference="injected-referral-commit-failure")
        self.assertEqual(failure["host_commit"]["disposition"], "COMMIT_FAILED")
        self.assertEqual(host.snapshot(organization, instance), before)
        self.assertEqual(host._roots[(organization, instance)]["event_log"], log)
        accepted = host.submit(organization, withheld)
        self.assertEqual(accepted["host_commit"]["disposition"], "COMMITTED")
        self.assertEqual(len(accepted["transition"]["state"]["proposal_authority_evaluations"]), 1)
        self.assertEqual(len(accepted["transition"]["state"]["referrals"]), 2)


if __name__ == "__main__":
    unittest.main()
