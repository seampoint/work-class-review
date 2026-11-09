from __future__ import annotations

import copy
import base64
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT.parent / "review")]

from consumer import Consumer
from implementation import lifecycle, work_class
from implementation.common import PIN, canonical, digest
from authority_fixture import authority_specimen
from equipment_completion_fixture import completion_authority_mutator, completion_native, referral_policy
from fixture_factory import structural_step
from lifecycle_factory import base_lifecycle, dispatch_event
from test_dispatch_gate import bind_event


def authority_layout(request, original):
    completion_authority_mutator(request, original)
    root = request["work_class"]["steps"][0]
    root.pop("dispatch_gate", None)
    request["envelope"].pop("source_observation_requirements", None)
    request["observations"] = [row for row in request["observations"] if row["query"]["purpose"] == "REVOCATION"]
    for name in ("branch-a", "branch-b"):
        branch = copy.deepcopy(root)
        branch.update(id=name, quantity_mode="NONE")
        request["work_class"]["steps"].append(branch)
    request["work_class"]["steps"].sort(key=lambda row: row["id"])


def definition_layout(definition):
    definition["profile"] = "PARALLEL_FANOUT"
    definition["steps"].extend([structural_step("split", "PARALLEL_SPLIT"), structural_step("join", "PARALLEL_JOIN")])
    definition["steps"].sort(key=lambda row: row["id"])
    for step in definition["steps"]:
        if step["kind"] == "OPERATION":
            step["authority_requirements"] = ["access-card-envelope"]
    definition["relationships"] = [{"kind": "SEQUENCE", "from": "issue", "to": "split"}, {"kind": "SEQUENCE", "from": "branch-a", "to": "join"}, {"kind": "SEQUENCE", "from": "branch-b", "to": "join"}, {"kind": "SEQUENCE", "from": "join", "to": "terminal"}]
    definition["parallel_blocks"] = [{"id": "parallel-completion", "split_step_id": "split", "branches": [{"id": "a", "head_step_id": "branch-a"}, {"id": "b", "head_step_id": "branch-b"}], "join_step_id": "join"}]


class CompletionCompositionTests(unittest.TestCase):
    def test_root_and_external_edges_enter_loop_only_at_declared_entry(self):
        definition = json.loads((ROOT.parent / "cases/bounded-loops/D2-048.json").read_text())["input"]["definition"]
        definition["specification_pin"] = PIN
        tail = copy.deepcopy(next(row for row in definition["steps"] if row["id"] == "issue"))
        tail["id"] = "loop-tail"
        definition["steps"].append(tail)
        definition["steps"].sort(key=lambda row: row["id"])
        next(row for row in definition["relationships"] if row["from"] == "issue" and row.get("label", {}).get("value") == "CONTINUE")["to"] = "loop-tail"
        definition["relationships"].extend([{**copy.deepcopy(row), "from": "loop-tail", "to": "issue" if row["label"]["value"] == "CONTINUE" else "terminal"} for row in definition["relationships"] if row["from"] == "issue"])
        definition["choices"].append({**copy.deepcopy(definition["choices"][0]), "step_id": "loop-tail"})
        definition["occurrence_limits"].append({"step_id": "loop-tail", "maximum": "2"})
        definition["loops"][0].update(member_step_ids=["issue", "loop-tail"], back_edge_from_step_id="loop-tail")
        self.assertIsInstance(work_class.validate(definition), str)
        wrong_root = copy.deepcopy(definition)
        wrong_root["root"] = "loop-tail"
        external = copy.deepcopy(definition)
        outside = copy.deepcopy(tail)
        outside["id"] = "outside"
        outside["completion"].update(route_label_field=None, route_label_type_ref=None)
        external["root"] = "outside"
        external["steps"].append(outside)
        external["steps"].sort(key=lambda row: row["id"])
        external["occurrence_limits"].append({"step_id": "outside", "maximum": "1"})
        external["relationships"].append({"kind": "SEQUENCE", "from": "outside", "to": "loop-tail"})
        for supplied in (wrong_root, external):
            artifact = {"specification_pin": PIN, "kind": "WORK_CLASS", "artifact_bytes_base64": base64.b64encode(canonical(supplied)).decode()}
            result = Consumer().validate(artifact)
            self.assertEqual(result, {"status": "REFUSED", "code": "UNSUPPORTED_FEATURE", "path": ""})
        external["relationships"][-1]["to"] = "issue"
        self.assertIsInstance(work_class.validate(external), str)

    def test_fully_rehashed_root_loop_cannot_remove_declared_enclosing_or_activation(self):
        original = json.loads((ROOT.parent / "cases/equipment-retained-evidence/C3-EVE-009.json").read_text())["input"]
        self.assertTrue(lifecycle._validate_state_integrity(original["state"], original["definition"]))
        for remove_loop in (True, False):
            request = copy.deepcopy(original)
            active = request["state"]["active"][0]
            if remove_loop:
                occurrence = active["occurrence"]
                occurrence["enclosing"] = []
                occurrence["occurrence_id"] = digest("occurrence", {key: value for key, value in occurrence.items() if key != "occurrence_id"})
                active["activation_event_digest"] = digest("deployment-activation", {"deployment_authorization_digest": request["state"]["deployment_authorization_digest"], "instance_id": request["state"]["instance_id"], "occurrence_id": occurrence["occurrence_id"]})
            else:
                active["activation_event_digest"] = digest("substituted-loop-activation", {})
            result = Consumer().step(bind_event(request, request["state"]))
            self.assertEqual(result.get("code"), "STATE_INVALID")

    def test_fanout_preflight_stop_preserves_frozen_set_across_restart(self):
        request = json.loads((ROOT.parent / "cases/fanout-expansion/D2-075.json").read_text())["input"]
        result = Consumer().step(request)
        self.assertEqual(result["decision"]["reason_codes"], ["LIMIT_EXCEEDED"])
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))
        event = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "restart-frozen-limit-stop", "kind": "CLOCK", "instance_id": result["state"]["instance_id"], "clock": {"source": "authority-clock", "revision": "2", "status": "AVAILABLE", "observed_time": "2026-09-10T04:31:00Z", "evidence_digest": digest("frozen-stop-clock", {})}, "activation_clocks": []}
        restarted = Consumer().step(bind_event({key: request[key] for key in ("profile", "role", "specification_pin", "definition", "definition_digest")} | {"event": event}, result["state"]))
        self.assertEqual(restarted.get("status"), "STEP", restarted)
        self.assertEqual(restarted["state"]["fanout_passes"], result["state"]["fanout_passes"])
        self.assertTrue(lifecycle._validate_state_integrity(restarted["state"], request["definition"]))

    def test_parallel_stop_outcomes_replay_original_obligation_roots(self):
        base = base_lifecycle(authority_mutator=authority_layout, definition_mutator=definition_layout)
        self.exercise(base, ("issue", "branch-a", "branch-b"))

    def test_reobserved_evidence_between_stop_outcomes_retains_exact_prior_roots(self):
        base = base_lifecycle(authority_mutator=authority_layout, definition_mutator=definition_layout)
        def between(consumer, common, current, index):
            if index != 0:
                return current
            event = copy.deepcopy(current["state"]["outcomes"][0]["source_event"])
            event["event_id"] = "repeat-root-evidence"
            result = consumer.step(bind_event({**common, "event": event}, current["state"]))
            self.assertEqual(result.get("decision", {}).get("reason_codes"), ["DUPLICATE_EVIDENCE"], result)
            self.assertEqual(len(result["state"]["outcomes"]), 1)
            self.assertTrue(lifecycle._validate_state_integrity(result["state"], base["definition"]))
            return result
        self.exercise(base, ("issue", "branch-a", "branch-b"), between=between)

    def test_authority_referral_between_stop_outcomes_replays_original_obligations(self):
        def definition(supplied):
            definition_layout(supplied)
            for row in supplied["steps"]:
                if row["kind"] != "OPERATION":
                    continue
                row["referral_policy"] = referral_policy()
                route = copy.deepcopy(row["referral_policy"]["completion"][0])
                route["id"] = "authority-review"
                row["referral_policy"]["authority"] = [route]
        base = base_lifecycle(authority_mutator=authority_layout, definition_mutator=definition)
        def before(consumer, common, current, event, index):
            if index != 1:
                return current
            withheld = copy.deepcopy(event)
            withheld["event_id"] = "withheld-branch-authority"
            authority = withheld["authority_input"]
            old_digest = digest("authority-credential", authority["credentials"][0])
            authority["credentials"][0]["validity"]["valid_until"] = authority["clock"]["instant"]
            new_digest = digest("authority-credential", authority["credentials"][0])
            for row in authority["host_selection"]["authenticated_records"]:
                if row["record_digest"] == old_digest:
                    row["record_digest"] = new_digest
            for row in authority["observations"]:
                if row["query"].get("subject_digest") == old_digest:
                    row["query"]["subject_digest"] = new_digest
                    row["query_digest"] = digest("authority-query", row["query"])
            withheld["observation_digests"] = sorted(digest("authority-observation", row) for row in authority["observations"])
            result = consumer.step(bind_event({**common, "event": withheld}, current["state"]))
            self.assertEqual(result.get("decision", {}).get("disposition"), "WITHHELD", result.get("code"))
            self.assertEqual(len(result["state"]["proposal_authority_evaluations"]), 1)
            self.assertEqual(len(result["state"]["referrals"]), 1)
            self.assertTrue(lifecycle._validate_state_integrity(result["state"], base["definition"]))
            return result
        self.exercise(base, ("issue", "branch-a", "branch-b"), before_proposal=before)

    def test_nested_parallel_stop_outcomes_replay_both_obligation_levels(self):
        def authority(request, original):
            authority_layout(request, original)
            for name in ("inner-a", "inner-b"):
                row = copy.deepcopy(next(row for row in request["work_class"]["steps"] if row["id"] == "branch-a"))
                row["id"] = name
                request["work_class"]["steps"].append(row)
            request["work_class"]["steps"].sort(key=lambda row: row["id"])
        def definition(supplied):
            definition_layout(supplied)
            supplied["steps"].extend([structural_step("inner-split", "PARALLEL_SPLIT"), structural_step("inner-join", "PARALLEL_JOIN")])
            supplied["steps"].sort(key=lambda row: row["id"])
            supplied["relationships"] = [row for row in supplied["relationships"] if row["from"] != "branch-a"] + [{"kind": "SEQUENCE", "from": "branch-a", "to": "inner-split"}, {"kind": "SEQUENCE", "from": "inner-a", "to": "inner-join"}, {"kind": "SEQUENCE", "from": "inner-b", "to": "inner-join"}, {"kind": "SEQUENCE", "from": "inner-join", "to": "join"}]
            supplied["parallel_blocks"].append({"id": "nested-completion", "split_step_id": "inner-split", "branches": [{"id": "a", "head_step_id": "inner-a"}, {"id": "b", "head_step_id": "inner-b"}], "join_step_id": "inner-join"})
            supplied["parallel_blocks"].sort(key=lambda row: row["id"])
        base = base_lifecycle(authority_mutator=authority, definition_mutator=definition)
        self.exercise(base, ("issue", "branch-a", "inner-a", "branch-b", "inner-b"))

    def test_deadline_expiry_between_stop_outcomes_replays_obligation_discharge(self):
        clock = {"source": "completion-deadline", "revision": "1", "status": "AVAILABLE", "observed_time": "2026-09-10T04:30:00Z", "evidence_digest": digest("deadline-clock", {})}
        def definition(supplied):
            definition_layout(supplied)
            supplied["deadlines"] = [{"id": "branch-deadline", "step_id": "branch-a", "clock_source": clock["source"], "due": {"kind": "ELAPSED_DURATION", "value": "60", "unit": "SECOND"}, "boundary": "AT_OR_AFTER", "expiry_target": "join"}]
            supplied["relationships"].append({"kind": "EXPIRY", "from": "branch-a", "to": "join", "deadline_ref": "branch-deadline"})
        base = base_lifecycle(authority_mutator=authority_layout, definition_mutator=definition)
        def between(consumer, common, current, index):
            if index != 0:
                return current
            expired_clock = {**clock, "revision": "2", "observed_time": "2026-09-10T04:31:00Z", "evidence_digest": digest("deadline-expiry-clock", {})}
            event = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "expire-branch", "kind": "CLOCK", "instance_id": current["state"]["instance_id"], "clock": expired_clock, "activation_clocks": []}
            result = consumer.step(bind_event({**common, "event": event}, current["state"]))
            self.assertEqual(result.get("decision", {}).get("disposition"), "EXPIRED", result)
            self.assertTrue(lifecycle._validate_state_integrity(result["state"], base["definition"]))
            return result
        self.exercise(base, ("issue", "branch-b"), activation_clock=clock, between=between)

    def test_legacy_parallel_predecessor_replays_before_stop_branches(self):
        def authority(request, original):
            authority_layout(request, original)
            carrier = next(row for row in request["work_class"]["steps"] if row["id"] == "issue")["completion"]
            for name in ("provider_record_identity", "event_time_identity", "additional_fields", "lookup", "correction_policy"):
                carrier.pop(name, None)
            carrier["terminal_policy"] = "LEGACY_NONTERMINAL"
        base = base_lifecycle(authority_mutator=authority, definition_mutator=definition_layout)
        self.exercise(base, ("issue", "branch-a", "branch-b"))

    def test_root_loop_stop_outcomes_replay_passes_and_selected_choice(self):
        def authority(request, original):
            authority_layout(request, original)
            request["work_class"]["steps"] = [row for row in request["work_class"]["steps"] if row["id"] != "branch-b"]
        def definition(supplied):
            supplied["profile"] = "PARALLEL_FANOUT"
            for row in supplied["steps"]:
                if row["kind"] == "OPERATION":
                    row["authority_requirements"] = ["access-card-envelope"]
                if row["id"] == "issue":
                    row["completion"].update(route_label_field="route", route_label_type_ref="STRING")
            labels = [{"type_ref": "STRING", "value": value} for value in ("again", "done")]
            supplied["choices"] = [{"step_id": "issue", "label_type_ref": "STRING", "label_values": labels}]
            supplied["relationships"] = [{"kind": "LABEL", "from": "issue", "to": "issue", "label": labels[0]}, {"kind": "LABEL", "from": "issue", "to": "branch-a", "label": labels[1]}, {"kind": "SEQUENCE", "from": "branch-a", "to": "terminal"}]
            supplied["loops"] = [{"id": "root-loop", "entry_step_id": "issue", "member_step_ids": ["issue"], "back_edge_from_step_id": "issue", "maximum_passes": "2"}]
            next(row for row in supplied["occurrence_limits"] if row["step_id"] == "issue")["maximum"] = "2"
        base = base_lifecycle(authority_mutator=authority, definition_mutator=definition)
        self.exercise(base, ("issue", "issue", "branch-a"), route_labels={0: "again", 1: "done"})

    def test_fanout_nested_in_parallel_replays_outer_and_object_obligations(self):
        def authority(request, original):
            authority_layout(request, original)
            row = copy.deepcopy(next(row for row in request["work_class"]["steps"] if row["id"] == "branch-a"))
            row["id"] = "inner-a"
            request["work_class"]["steps"].append(row)
            request["work_class"]["steps"].sort(key=lambda row: row["id"])
        def definition(supplied):
            definition_layout(supplied)
            next(row for row in supplied["steps"] if row["id"] == "branch-a")["kind"] = "FANOUT_EXPAND"
            supplied["steps"].append(structural_step("inner-join", "FANOUT_JOIN"))
            supplied["steps"].sort(key=lambda row: row["id"])
            supplied["relationships"] = [row for row in supplied["relationships"] if row["from"] != "branch-a"] + [{"kind": "SEQUENCE", "from": "inner-a", "to": "inner-join"}, {"kind": "SEQUENCE", "from": "inner-join", "to": "join"}]
            supplied["occurrence_limits"] = [row for row in supplied["occurrence_limits"] if row["step_id"] != "inner-a"]
            supplied["fanouts"] = [{"id": "nested-fanout", "expand_step_id": "branch-a", "region_head_step_id": "inner-a", "join_step_id": "inner-join", "object_field": "objects", "object_request_field": "beneficiary", "object_type_ref": "IDENTITY", "empty_set_behavior": "ADVANCE_TO_JOIN"}]
        base = base_lifecycle(authority_mutator=authority, definition_mutator=definition)
        self.exercise(base, ("issue", "branch-a", "inner-a", "branch-b", "inner-a"), fanout=True)

    def test_fanout_stop_outcomes_replay_original_object_roots(self):
        def authority(request, original):
            authority_layout(request, original)
            request["work_class"]["steps"] = [row for row in request["work_class"]["steps"] if row["id"] != "branch-b"]
        def definition(supplied):
            supplied["profile"] = "PARALLEL_FANOUT"
            supplied["steps"].append(structural_step("join", "FANOUT_JOIN"))
            supplied["steps"].sort(key=lambda row: row["id"])
            for row in supplied["steps"]:
                if row["kind"] == "OPERATION":
                    row["authority_requirements"] = ["access-card-envelope"]
                if row["id"] == "issue":
                    row["kind"] = "FANOUT_EXPAND"
            supplied["relationships"] = [{"kind": "SEQUENCE", "from": "branch-a", "to": "join"}, {"kind": "SEQUENCE", "from": "join", "to": "terminal"}]
            supplied["occurrence_limits"] = [{"step_id": "issue", "maximum": "1"}]
            supplied["fanouts"] = [{"id": "completion-fanout", "expand_step_id": "issue", "region_head_step_id": "branch-a", "join_step_id": "join", "object_field": "objects", "object_request_field": "beneficiary", "object_type_ref": "IDENTITY", "empty_set_behavior": "ADVANCE_TO_JOIN"}]
        base = base_lifecycle(authority_mutator=authority, definition_mutator=definition)
        self.exercise(base, ("issue", "branch-a", "branch-a"), fanout=True)

    def exercise(self, base, names, fanout=False, activation_clock=None, between=None, route_labels=None, before_proposal=None):
        consumer = Consumer()
        deployed = consumer.deploy(base["deploy_input"])
        self.assertEqual(deployed["status"], "DEPLOYED")
        if base["definition"]["loops"]:
            self.assertEqual(deployed["state"]["active"][0]["occurrence"]["enclosing"][0]["pass"], "1")
        common = {"profile": "PARALLEL_FANOUT", "role": "PARALLEL_FANOUT_RUNTIME", "specification_pin": PIN, "definition": base["definition"], "definition_digest": base["definition_digest"]}
        clocked = consumer.step(bind_event({**common, "event": base["clock_event"]}, deployed["state"]))
        current = clocked
        if activation_clock is not None:
            event = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "deadline-clock", "kind": "CLOCK", "instance_id": current["state"]["instance_id"], "clock": activation_clock, "activation_clocks": []}
            current = consumer.step(bind_event({**common, "event": event}, current["state"]))
        for index, name in enumerate(names):
            label = name + str(index)
            occurrence = next(row["occurrence"] for row in current["state"]["active"] if row["occurrence"]["step_id"] == name)
            def selected(request, original):
                authority_layout(request, original)
                request["work_class"] = lifecycle._authority_projection(base["definition"])
                if occurrence["object_key"] is not None:
                    next(row for row in request["proposal"]["fields"] if row["name"] == "beneficiary")["value"] = copy.deepcopy(occurrence["object_key"])
                request["proposal"]["step"] = name
                request["proposal"]["operation"] = "issue-card"
                for row in request["envelope"]["bindings"] + request["envelope"]["conditions"] + request["credentials"]:
                    row["step"] = name
                request["envelope"]["operations"] = [{"step": name, "operation": "issue-card", "interface": "card-system"}]
            authority, _ = authority_specimen(shared_budget=False, instance_id=current["state"]["instance_id"], occurrence_id=occurrence["occurrence_id"], mutator=selected)
            executor = authority["proposal"]["executor"]
            event = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "proposal-" + label, "kind": "PROPOSE", "instance_id": current["state"]["instance_id"], "occurrence": occurrence, "native_request": {key: authority["proposal"][key] for key in ("operation", "interface", "fields")}, "executor": {"participant_id": executor["actor"], "role": executor["role"], "binding_digest": digest("executor-binding", executor)}, "credential_ids": sorted(row["id"] for row in authority["credentials"]), "authority_input": authority, "budget_inputs": [], "clock_revision": "1", "observation_digests": sorted(digest("authority-observation", row) for row in authority["observations"])}
            if before_proposal is not None:
                current = before_proposal(consumer, common, current, event, index)
            permitted = consumer.step(bind_event({**common, "event": event}, current["state"]))
            self.assertEqual(permitted.get("decision", {}).get("disposition"), "PERMITTED", permitted)
            dispatched = consumer.step(bind_event({**common, "event": dispatch_event(base, permitted, event_id="dispatch-" + label)}, permitted["state"]))
            carrier = next(row for row in base["definition"]["steps"] if row["id"] == name)["completion"]
            actual = None if carrier["terminal_policy"] == "STOP_RETAIN" else permitted["permit"]["native_request"]["fields"] + [{"name": carrier["status_field"], "value": carrier["success_values"][0]}]
            native = completion_native(base, {**dispatched, "permit": permitted["permit"]}, evidence_id="native-" + label, provider_record_id="provider-" + label, native_operation_id="operation-" + label, actual_fields=actual)
            if route_labels and index in route_labels:
                native["actual_fields"].append({"name": carrier["route_label_field"], "value": {"type_ref": carrier["route_label_type_ref"], "value": route_labels[index]}})
                native["actual_fields"].sort(key=lambda row: row["name"])
                native["record_digest"] = digest("provider-native-record", {key: native[key] for key in ("provider", "source", "record_type", "provider_record_id", "provider_revision", "native_operation_id", "actual_fields", "collections", "event_time", "status")})
            if fanout and next(row for row in base["definition"]["steps"] if row["id"] == name)["kind"] == "FANOUT_EXPAND":
                native["collections"] = [{"name": "objects", "element_type_ref": "IDENTITY", "values": [{"type_ref": "IDENTITY", "value": "object-b"}, {"type_ref": "IDENTITY", "value": "object-a"}]}]
                native["record_digest"] = digest("provider-native-record", {key: native[key] for key in ("provider", "source", "record_type", "provider_record_id", "provider_revision", "native_operation_id", "actual_fields", "collections", "event_time", "status")})
            dispatch = next(row for row in dispatched["state"]["dispatches"] if row["event_id"] == "dispatch-" + label)
            effect = {"schema": "seampoint.work-class/1.0.0-draft.3/runtime-event", "event_id": "effect-" + label, "kind": "EFFECT_OBSERVED", "instance_id": dispatched["state"]["instance_id"], "permit": permitted["permit"], "dispatch_digest": dispatch["dispatch_digest"], "native_evidence": native, "completion_authorization": None, "budget_inputs": [], "clock_revision": None, "activation_clocks": [activation_clock] if name == "issue" and activation_clock is not None else []}
            current = consumer.step(bind_event({**common, "event": effect}, dispatched["state"]))
            self.assertEqual(current.get("status"), "STEP", current)
            self.assertTrue(lifecycle._validate_state_integrity(current["state"], base["definition"]))
            if between is not None:
                current = between(consumer, common, current, index)
        self.assertEqual(current["state"]["status"], "COMPLETE")
        self.assertTrue(all(row["status"] == "JOINED" for row in current["state"]["obligations"]))


if __name__ == "__main__":
    unittest.main()
