from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from consumer import Consumer
from implementation import completion, lifecycle, reservation_v2, work_class
from implementation.common import Refusal, digest
from implementation.reference_host import SerializedReservationHost, SingleProcessReferenceHost
from test_dispatch_gate import bind_event
from test_foundations import rehash_last_lifecycle_decision


def case_input(group, prefix, number):
    return json.loads((ROOT.parent / "cases" / group / f"C3-{prefix}-{number:03}.json").read_text())["input"]


def completion_input(number):
    return case_input("equipment-completion", "EC", number)


class HistoryCompletionTests(unittest.TestCase):
    def test_seed_race_installs_one_complete_snapshot(self):
        supplied = case_input("equipment-history", "EH", 2)
        host = SerializedReservationHost(supplied["state"], supplied["specification_pin"])
        barrier = threading.Barrier(2)
        results = []

        def submit():
            barrier.wait()
            results.append(host.submit(copy.deepcopy(supplied["event"]), copy.deepcopy(supplied["host_evidence"])))

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(not row["replay"] for row in results), 1)
        state = host.snapshot()
        self.assertEqual(state["core"]["revision"], "1")
        self.assertEqual(len(state["core"]["key_history"]), 1)
        self.assertEqual(len(state["core"]["exclusive_keys"]), 1)
        self.assertTrue(reservation_v2._replay_state(state, supplied["specification_pin"]))

    def test_seed_restart_rejects_rehashed_native_history(self):
        supplied = case_input("equipment-history", "EH", 2)
        result = Consumer().aggregate_step(supplied)
        state = copy.deepcopy(result["state"])
        snapshot = state["core"]["key_history"][0]
        snapshot["snapshot"]["coverage"]["complete"] = False
        snapshot["snapshot_digest"] = digest("exclusive-history-snapshot", snapshot["snapshot"])
        receipt = state["receipts"][-1]["receipt"]
        receipt["next_core_digest"] = digest("reservation-core", state["core"])
        self.assertFalse(reservation_v2._replay_state(state, supplied["specification_pin"]))

    def test_stale_distinct_seed_race_cannot_install_a_second_event(self):
        from equipment_history_fixture import history_fixture, rebind_seed

        first = case_input("equipment-history", "EH", 2)
        second = copy.deepcopy(first)
        second["event"]["id"] = "concurrent-second-seed"
        for row in second["event"]["payload"]["claims"]:
            row["acquisition_event"] = second["event"]["id"]
        second = rebind_seed(history_fixture(), second)
        host = SerializedReservationHost(first["state"], first["specification_pin"])
        self.assertEqual(host.submit(first["event"], first["host_evidence"])["receipt"]["decision"], "SEEDED_EXCLUSIVE")
        before = host.snapshot()
        rejected = host.submit(second["event"], second["host_evidence"])
        self.assertEqual(rejected["code"], "REVISION_CONFLICT")
        self.assertEqual(host.snapshot(), before)

    def test_full_mediated_key_set_settles_without_changing_cutover_snapshots(self):
        from equipment_history_fixture import history_fixture, history_state, reserve_request, seed_request
        from reservation_fixture import host_and_event, native, request

        facts = history_fixture()
        state = history_state(facts)
        for slot in facts["configuration"]["exclusive_slots"]:
            supplied = seed_request(facts, state, slot["slot"], [], "seed-test-" + slot["slot"])
            state = Consumer().aggregate_step(supplied)["state"]
        reserved = Consumer().aggregate_step(reserve_request(facts, state, "reserve-new-occurrence"))
        self.assertEqual(reserved["receipt"]["decision"], "RESERVED")
        snapshots = copy.deepcopy(reserved["state"]["core"]["key_history"])
        evidence = native(facts, "EFFECT", "native-completion", reservation_id=reserved["receipt"]["reservation"])
        carrier = next(row["completion"] for row in facts["authority_a"]["work_class"]["steps"] if row["id"] == facts["authority_a"]["proposal"]["step"])
        evidence["provider"] = carrier["effect_provider"]
        evidence["source"] = carrier["effect_source"]
        event, host = host_and_event(facts, "SETTLE", "settle-new-occurrence", reserved["state"]["core"]["revision"], {"native": evidence, "histories": []}, administration=False)
        settled = Consumer().aggregate_step(request(reserved["state"], event, host))
        self.assertEqual(settled["receipt"]["decision"], "SETTLED")
        self.assertEqual(settled["state"]["core"]["key_history"], snapshots)
        self.assertTrue(all(row["owner"]["kind"] == "WORK_OCCURRENCE" and row["status"] == "CONSUMED" for row in settled["state"]["core"]["exclusive_keys"]))
        self.assertTrue(reservation_v2._replay_state(settled["state"], supplied["specification_pin"]))

    def test_terminal_lookup_restart_rejects_rebound_query_and_referral(self):
        supplied = completion_input(36)
        result = Consumer().step(supplied)
        self.assertEqual(result["decision"]["disposition"], "COMPLETION_FAILED")
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], supplied["definition"]))
        for mutation in ("lookup", "referral", "terminal"):
            state = copy.deepcopy(result["state"])
            if mutation == "lookup":
                row = state["completion_checks"][0]
                row["lookup"]["query"]["key"][0]["value"]["value"] = "changed"
                row["lookup"]["query_digest"] = digest("completion-query", row["lookup"]["query"])
                row["lookup"]["provenance_digest"] = digest("completion-lookup-provenance", {name: value for name, value in row["lookup"].items() if name != "provenance_digest"})
                row["check_digest"] = digest("completion-check", {name: value for name, value in row.items() if name != "check_digest"})
            elif mutation == "referral":
                row = state["referrals"][0]
                row["destination_role"] = "invented-role"
                row["referral_digest"] = digest("referral-intent", {name: value for name, value in row.items() if name != "referral_digest"})
                state["referrals"].sort(key=lambda item: item["referral_digest"])
            else:
                row = state["terminal_records"][0]
                row["cause"] = "UNEXPECTED_COMPLETION"
                row["terminal_digest"] = digest("terminal-record", {name: value for name, value in row.items() if name != "terminal_digest"})
            rehash_last_lifecycle_decision(state)
            self.assertFalse(lifecycle._validate_state_integrity(state, supplied["definition"]), mutation)

    def test_terminal_native_restart_recomputes_malformed_scalar(self):
        supplied = completion_input(2)
        result = Consumer().step(supplied)
        state = copy.deepcopy(result["state"])
        outcome = state["outcomes"][0]
        outcome["classification"] = "MATCHED"
        outcome["disputed"] = False
        outcome["outcome_digest"] = digest("outcome", {name: value for name, value in outcome.items() if name != "outcome_digest"})
        rehash_last_lifecycle_decision(state)
        self.assertFalse(lifecycle._validate_state_integrity(state, supplied["definition"]))

    def test_provider_receipt_metadata_does_not_create_second_native_fact(self):
        supplied = completion_input(31)
        result = Consumer().step(supplied)
        self.assertEqual(result["decision"]["disposition"], "OUTCOME_RETAINED")
        self.assertEqual(result["decision"]["reason_codes"], ["DUPLICATE_EVIDENCE"])
        self.assertEqual(result["state"]["status"], "COMPLETE")
        self.assertEqual(result["state"]["terminal_records"], [])

    def test_completion_static_faults_and_missing_terminal_arrays_refuse(self):
        supplied = completion_input(1)
        definition = copy.deepcopy(supplied["definition"])
        step = next(row for row in definition["steps"] if row["completion"] is not None)
        step["completion"]["event_time_identity"]["type_ref"] = "IDENTITY"
        with self.assertRaisesRegex(Refusal, "TYPE_INVALID"):
            work_class.validate(definition)
        state = copy.deepcopy(supplied["state"])
        state.pop("terminal_records")
        self.assertFalse(lifecycle._validate_state_integrity(state, supplied["definition"]))

    def test_lookup_commit_failure_keeps_root_log_and_no_referrals(self):
        from importlib import import_module
        review = str(ROOT.parent / "review")
        if review not in sys.path:
            sys.path.insert(0, review)
        fixture = import_module("equipment_completion_fixture")
        base = fixture.completion_base()
        host = SingleProcessReferenceHost(Consumer())
        deploy_request = base["deploy_input"]
        organization = deploy_request["deployment_authorization"]["organization_id"]
        instance = deploy_request["instance_id"]
        host.install(deploy_request)
        supplied = completion_input(36)
        initial = host.snapshot(organization, instance)["state"]
        clock = copy.deepcopy(supplied["state"]["clocks"][0])
        clock_event = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "clock-event-1", "kind": "CLOCK", "instance_id": instance, "clock": clock, "activation_clocks": []}
        clocked = host.submit(organization, bind_event({**supplied, "event": clock_event}, initial))["transition"]
        # Feed the source-derived event sequence into the host's owned root.
        from equipment_dispatch_fixture import authorization_event
        from lifecycle_factory import dispatch_event
        proposal = {**supplied, "state": clocked["state"], "event": copy.deepcopy(base["proposal_event"])}
        proposal = bind_event(proposal, proposal["state"])
        proposed_result = host.submit(organization, proposal)["transition"]
        author_event = authorization_event(base, proposed_result)
        authorized = host.submit(organization, bind_event({**supplied, "event": author_event}, proposed_result["state"]))["transition"]
        permit = proposed_result["permit"]
        authorization_digest = authorized["state"]["authorizations"][0]["authorization_digest"]
        dispatch = dispatch_event(base, {**authorized, "permit": permit}, event_id="completion-dispatch-1", attempt_status="SENT", authorization_digest=authorization_digest)
        dispatched = host.submit(organization, bind_event({**supplied, "event": dispatch}, authorized["state"]))["transition"]
        lookup_event = fixture.lookup_event(base, {**dispatched, "permit": permit}, event_id="host-completion-check")
        lookup = bind_event({**supplied, "event": lookup_event}, dispatched["state"])
        before = host.snapshot(organization, instance)
        before_log = copy.deepcopy(host._roots[(organization, instance)]["event_log"])
        failed = host.submit(organization, lookup, failure_reference="injected-completion-commit-failure")
        self.assertEqual(failed["host_commit"]["disposition"], "COMMIT_FAILED")
        self.assertEqual(host.snapshot(organization, instance), before)
        self.assertEqual(host._roots[(organization, instance)]["event_log"], before_log)
        committed = host.submit(organization, lookup)
        self.assertEqual(committed["host_commit"]["disposition"], "COMMITTED")
        self.assertEqual(len(committed["transition"]["state"]["referrals"]), 2)


if __name__ == "__main__":
    unittest.main()
