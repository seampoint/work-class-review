from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT.parent / "review")]

from consumer import Consumer
from implementation import completion, lifecycle, source_corrections, work_class
from implementation.common import PREFIX, Refusal, digest, schema_valid
from equipment_completion_fixture import completion_authority_mutator, completion_native
from lifecycle_factory import base_lifecycle, dispatch_event
from test_dispatch_gate import bind_event


def generated_authority(supplied, original):
    completion_authority_mutator(supplied, original)
    step = supplied["work_class"]["steps"][0]
    step["completion"]["generated_fields"] = [{"name": "provider_acknowledgement", "type_ref": "IDENTITY"}]
    step.pop("dispatch_gate", None)
    supplied["envelope"].pop("source_observation_requirements", None)
    supplied["observations"] = [row for row in supplied["observations"] if row["query"]["purpose"] == "REVOCATION"]


class GeneratedCompletionTests(unittest.TestCase):
    def setUp(self):
        self.base = base_lifecycle(authority_mutator=generated_authority)
        self.step = next(row for row in self.base["definition"]["steps"] if row["kind"] == "OPERATION")
        self.types = {row["id"]: row for row in self.base["definition"]["types"]}

    def retained_native(self, value="provider-selected-acknowledgement"):
        consumer = Consumer()
        deployed = consumer.deploy(self.base["deploy_input"])
        common = {key: self.base["deploy_input"][key] for key in ("profile", "role", "specification_pin", "definition", "definition_digest")}
        clocked = consumer.step(bind_event({**common, "event": self.base["clock_event"]}, deployed["state"]))
        permitted = consumer.step(bind_event({**common, "event": self.base["proposal_event"]}, clocked["state"]))
        self.assertEqual(permitted.get("decision", {}).get("disposition"), "PERMITTED", permitted)
        dispatched = consumer.step(bind_event({**common, "event": dispatch_event(self.base, permitted, event_id="dispatch-generated-native")}, permitted["state"]))
        native = completion_native(self.base, {**dispatched, "permit": permitted["permit"]}, evidence_id="generated-native-evidence",
            provider_record_id="generated-provider-record", native_operation_id="generated-native-operation")
        native["actual_fields"].append({"name": "provider_acknowledgement", "value": {"type_ref": "IDENTITY", "value": value}})
        native["actual_fields"].sort(key=lambda row: row["name"].encode())
        native["record_digest"] = digest("provider-native-record", {key: native[key] for key in
            ("provider", "source", "record_type", "provider_record_id", "provider_revision", "native_operation_id", "actual_fields", "collections", "event_time", "status")})
        dispatch = dispatched["state"]["dispatches"][0]
        event = {"schema": PREFIX + "runtime-event", "event_id": "observe-generated-native", "kind": "EFFECT_OBSERVED",
            "instance_id": dispatched["state"]["instance_id"], "permit": permitted["permit"], "dispatch_digest": dispatch["dispatch_digest"],
            "native_evidence": native, "completion_authorization": None, "budget_inputs": [], "clock_revision": None, "activation_clocks": []}
        return consumer, common, permitted["permit"], dispatched["state"], native, event

    def test_generated_value_is_required_typed_and_provider_selected(self):
        for value in ("provider-acknowledgement-one", "unpredicted-provider-acknowledgement-two"):
            _, _, permit, _, native, _ = self.retained_native(value)
            self.assertEqual(completion.fields(self.step, permit, native, self.types), ("MATCHED", None, True))
            changed = copy.deepcopy(native)
            changed["actual_fields"] = [row for row in changed["actual_fields"] if row["name"] != "provider_acknowledgement"]
            self.assertEqual(completion.fields(self.step, permit, changed, self.types), ("UNEXPECTED", None, False))
            changed = copy.deepcopy(native)
            next(row for row in changed["actual_fields"] if row["name"] == "provider_acknowledgement")["value"] = {"type_ref": "STRING", "value": value}
            self.assertEqual(completion.fields(self.step, permit, changed, self.types), ("UNEXPECTED", None, False))

    def test_generated_malformed_scalar_and_undeclared_extra_are_not_complete(self):
        _, _, permit, _, native, _ = self.retained_native()
        for value in ({"type_ref": "IDENTITY", "value": ""}, {"type_ref": "IDENTITY", "value": False}):
            changed = copy.deepcopy(native)
            next(row for row in changed["actual_fields"] if row["name"] == "provider_acknowledgement")["value"] = value
            self.assertEqual(completion.fields(self.step, permit, changed, self.types), ("UNEXPECTED", None, False))
        native["actual_fields"].append({"name": "undeclared", "value": {"type_ref": "IDENTITY", "value": "extra"}})
        self.assertEqual(completion.fields(self.step, permit, native, self.types), ("UNEXPECTED", None, False))

    def test_generated_disjoint_inventory_and_finite_bounds(self):
        for name in ("status", "card_id", "provider_event_id", "event_timestamp", "approval_link"):
            changed = copy.deepcopy(self.step)
            changed["completion"]["generated_fields"][0]["name"] = name
            with self.assertRaises(Refusal) as caught: completion.validate_step(changed, self.types)
            self.assertEqual(caught.exception.code, "DEFINITION_INVALID")
        changed = copy.deepcopy(self.step)
        changed["completion"]["generated_fields"] = [{"name": "generated-" + str(index).zfill(2), "type_ref": "IDENTITY"} for index in range(65)]
        with self.assertRaises(Refusal) as caught: completion.validate_step(changed, self.types)
        self.assertEqual(caught.exception.code, "LIMIT_EXCEEDED")

    def test_projection_and_correction_inventory_preserve_exact_declaration(self):
        projected = lifecycle._authority_projection(self.base["definition"])
        self.assertEqual(projected["steps"][0]["completion"]["generated_fields"], self.step["completion"]["generated_fields"])
        self.assertEqual(source_corrections.inventory(self.step)["provider_acknowledgement"], "IDENTITY")
        empty = copy.deepcopy(self.base["definition"])
        empty["steps"][0]["completion"]["generated_fields"] = []
        omitted = copy.deepcopy(empty)
        del omitted["steps"][0]["completion"]["generated_fields"]
        self.assertNotEqual(lifecycle._authority_projection(empty), lifecycle._authority_projection(omitted))
        legacy = copy.deepcopy(self.step["completion"])
        legacy["terminal_policy"] = "LEGACY_NONTERMINAL"
        for name in ("provider_record_identity", "event_time_identity", "additional_fields", "lookup"):
            del legacy[name]
        self.assertFalse(schema_valid(legacy, "authority.schema.json", "completionCarrier"))
        del legacy["generated_fields"]
        self.assertTrue(schema_valid(legacy, "authority.schema.json", "completionCarrier"))

    def test_generated_native_fact_reconstructs_and_replays_without_reset(self):
        consumer, common, _, state, native, event = self.retained_native()
        request = bind_event({**common, "event": event}, state)
        result = consumer.step(request)
        self.assertEqual(result.get("decision", {}).get("disposition"), "COMPLETED")
        self.assertEqual(result["state"]["outcomes"][0]["native_evidence"]["actual_fields"], native["actual_fields"])
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], self.base["definition"]))
        replay_request = copy.deepcopy(request)
        replay_request.update(state=copy.deepcopy(result["state"]), state_digest=result["state_digest"])
        replay = consumer.step(replay_request)
        self.assertTrue(replay["replay"])
        self.assertEqual(replay["state"], result["state"])

    def test_prior_effect_declaration_can_select_every_terminal_coordinate(self):
        for name, type_ref in completion.inventory(self.step).items():
            definition = copy.deepcopy(self.base["definition"])
            target = copy.deepcopy(self.step)
            target["id"] = "consume"
            target["fields"] = [{"name": "target", "type_ref": type_ref}]
            target["scope_fields"] = {"subjects": ["target"], "resources": ["target"]}
            if self.types[type_ref]["kind"] not in {"STRING", "IDENTITY"}:
                target["fields"].append({"name": "identity", "type_ref": "IDENTITY"})
                target["fields"].sort(key=lambda row: row["name"])
                target["scope_fields"] = {"subjects": ["identity"], "resources": ["identity"]}
            target["completion"] = {"effect_provider": "target-provider", "effect_source": "target-source", "effect_record_type": "target-result",
                "no_effect_provider": "target-provider", "no_effect_source": "target-source", "no_effect_record_type": "target-no-effect",
                "status_field": "status", "status_type_ref": "STRING", "success_values": [{"type_ref": "STRING", "value": "OK"}],
                "failure_values": [{"type_ref": "STRING", "value": "FAILED"}], "route_label_field": None, "route_label_type_ref": None,
                "evidence_bindings": [{"request_field": row["name"], "evidence_field": row["name"]} for row in target["fields"]], "terminal_policy": "LEGACY_NONTERMINAL"}
            target["prior_effect_bindings"] = [{"id": "source-to-target", "selection": "UNIQUE_COMPLETED_ANCESTOR", "source_step_id": self.step["id"],
                "source_evidence_field": name, "target_request_field": "target"}]
            definition["steps"].append(target)
            definition["steps"].sort(key=lambda row: row["id"])
            definition["relationships"] = [{"kind": "SEQUENCE", "from": self.step["id"], "to": "consume"}, {"kind": "SEQUENCE", "from": "consume", "to": "terminal"}]
            definition["occurrence_limits"].append({"step_id": "consume", "maximum": "1"})
            definition["occurrence_limits"].sort(key=lambda row: row["step_id"])
            self.assertIsInstance(work_class.validate(definition), str, name)
            target["fields"][next(i for i, row in enumerate(target["fields"]) if row["name"] == "target")]["type_ref"] = "COUNT"
            if type_ref != "COUNT":
                with self.assertRaises(Refusal): work_class.validate(definition)


if __name__ == "__main__": unittest.main()
