from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT.parent / "review")]

from consumer import Consumer
from implementation import artifacts, authority, lifecycle
from implementation.common import IDENTITY, Refusal, canonical, digest, readback_lines
from authority_fixture import authority_specimen
from equipment_completion_fixture import KEYS, completion_authority_mutator, completion_carrier, completion_key_proposal
from lifecycle_factory import base_lifecycle
from test_dispatch_gate import bind_event


def definition(path):
    return json.loads((ROOT.parent / path).read_text())["input"]["definition"]


def choice_definition():
    value = definition("cases/bounded-loops/D2-048.json")
    labels = [{"type_ref": "STRING", "value": word} for word in ("REVISE", "ACCEPT")]
    value["choices"][0]["label_values"] = labels
    for edge, label in zip(value["relationships"], labels):
        edge["label"] = copy.deepcopy(label)
    return value


def no_quantity(supplied, original):
    for step in supplied["work_class"]["steps"]:
        step["quantity_mode"] = "NONE"
    supplied["envelope"]["limits"]["per_action"] = []


def legacy_carrier():
    carrier = completion_carrier()
    carrier["terminal_policy"] = "LEGACY_NONTERMINAL"
    for name in ("provider_record_identity", "event_time_identity", "additional_fields", "lookup"):
        del carrier[name]
    return carrier


def legacy_keys(supplied, original):
    no_quantity(supplied, original)
    step = supplied["work_class"]["steps"][0]
    step["exclusive_keys"] = copy.deepcopy(KEYS)
    step["completion"] = legacy_carrier()
    supplied["work_class"]["types"].append({"id": "STRING", "kind": "STRING", "nonnegative": False, "unit": None})
    supplied["work_class"]["types"].sort(key=lambda row: row["id"].encode())
    supplied["envelope"]["enforcement"]["mechanisms"] = ["ATOMIC_RESERVATION_TRANSITION", "AUTHORITY_BEFORE_RESERVATION"]


def projection_proposal_inputs():
    rows = []
    for name, mutator in (("legacy-keyless", no_quantity), ("legacy-keyed", legacy_keys),
                          ("stop-retain-keyless", completion_authority_mutator)):
        base = base_lifecycle(authority_mutator=mutator)
        if name == "legacy-keyed":
            completion_key_proposal(base)
        event = copy.deepcopy(base.get("key_proposal_event", base["proposal_event"]))
        common = {key: base["deploy_input"][key] for key in ("profile", "role", "specification_pin", "definition", "definition_digest")}
        request = {**common, "state": copy.deepcopy(base["clock_result"]["state"]),
                   "state_digest": base["clock_result"]["state_digest"], "event": event}
        rows.append({"name": name, "input": request, "expected": {"status": "STEP", "disposition": "PERMITTED"}})

        def altered(supplied, original):
            mutator(supplied, original)
            step = supplied["work_class"]["steps"][0]
            if name == "legacy-keyless":
                step["completion"] = legacy_carrier()
                supplied["work_class"]["types"].append({"id": "STRING", "kind": "STRING", "nonnegative": False, "unit": None})
                supplied["work_class"]["types"].sort(key=lambda row: row["id"].encode())
            else:
                del step["completion"]
                references = {field["type_ref"] for row in supplied["work_class"]["steps"] for field in row["fields"]}
                references.update(ref for row in supplied["work_class"]["steps"] for ref in row.get("authority_type_refs", []))
                supplied["work_class"]["types"] = [row for row in supplied["work_class"]["types"] if row["id"] in references]

        authority_input, _ = authority_specimen(shared_budget=False, instance_id=event["instance_id"],
                                                occurrence_id=event["occurrence"]["occurrence_id"], mutator=altered)
        changed = copy.deepcopy(request)
        changed["event"]["authority_input"] = authority_input
        changed["event"]["observation_digests"] = sorted((digest("authority-observation", row) for row in authority_input["observations"]), key=str.encode)
        if name == "legacy-keyed":
            changed["event"]["budget_inputs"][0]["request"]["event"]["payload"]["authority"] = copy.deepcopy(authority_input)
        expected_refusal = {"status": "REFUSED", "profile": changed["profile"], "role": changed["role"],
                            "code": "BINDING_MISMATCH", "path": "", "state": copy.deepcopy(changed["state"]),
                            "state_digest": changed["state_digest"], "budget_states": [
                                {"registry_digest": row["registry_digest"], "affected_anchors": copy.deepcopy(row["affected_anchors"]),
                                 "state": copy.deepcopy(row["request"]["state"]), "state_digest": row["request"]["state_digest"]}
                                for row in changed["event"]["budget_inputs"]]}
        rows.append({"name": name + ("-extra-carrier" if name == "legacy-keyless" else "-missing-carrier"),
                     "input": changed, "expected": expected_refusal})
    return rows


class AuthoringConsumerRegressions(unittest.TestCase):
    def test_authority_member_predicates_require_canonical_unique_sets(self):
        request, _ = authority_specimen(shared_budget=False)
        definition_value = {
            "schema": f"{IDENTITY}/authority-definition",
            "source": copy.deepcopy(request["source"]),
            "work_class": copy.deepcopy(request["work_class"]),
            "envelope": copy.deepcopy(request["envelope"]),
        }
        step_id = definition_value["envelope"]["operations"][0]["step"]
        step = next(row for row in definition_value["work_class"]["steps"] if row["id"] == step_id)
        identity_type = next(row["id"] for row in definition_value["work_class"]["types"]
                             if row["kind"] == "IDENTITY")
        field = next(row for row in step["fields"] if row["type_ref"] == identity_type)

        def membership(members, identifier="condition.membership-test"):
            return {
                "id": identifier,
                "step": step_id,
                "predicate": {
                    "kind": "MEMBER",
                    "value": {"kind": "FIELD", "name": field["name"]},
                    "members": [{"type_ref": identity_type, "value": value} for value in members],
                },
            }

        definition_value["envelope"]["conditions"] = [membership(["A", "Z"])]
        definition_value["envelope"]["gate"]["kind"] = "VERIFY"
        definition_value["envelope"]["gate"]["role"] = "reviewer"
        definition_value["envelope"]["gate"]["criteria"] = [membership(["A", "Z"], "criterion.membership-test")]
        self.assertEqual(authority.validate_definition(definition_value)["status"], "ACCEPTED")
        other_type = next(row["id"] for row in definition_value["work_class"]["types"]
                          if row["id"] != identity_type)
        for collection in ("conditions", "gate.criteria"):
            with self.subTest(collection=collection, members="reversed"):
                definition_value["envelope"]["conditions"] = [membership(["A", "Z"])]
                definition_value["envelope"]["gate"]["criteria"] = [membership(["A", "Z"], "criterion.membership-test")]
                if collection == "conditions":
                    definition_value["envelope"]["conditions"] = [membership(["Z", "A"])]
                else:
                    definition_value["envelope"]["gate"]["criteria"] = [membership(["Z", "A"], "criterion.membership-test")]
                result = authority.validate_definition(definition_value)
                self.assertEqual((result["status"], result["code"]), ("REFUSED", "INPUT_INVALID"))

        definition_value["envelope"]["conditions"] = [membership(["A", "A"])]
        definition_value["envelope"]["gate"]["criteria"] = [membership(["A", "Z"], "criterion.membership-test")]
        duplicate = authority.validate_definition(definition_value)
        self.assertEqual((duplicate["status"], duplicate["code"]), ("REFUSED", "INPUT_INVALID"))

        wrong_type_members = [
            {"type_ref": identity_type, "value": "A"},
            {"type_ref": other_type, "value": "1"},
        ]
        wrong_type_members.sort(key=canonical)
        definition_value["envelope"]["conditions"] = [membership([row["value"] for row in wrong_type_members])]
        for row, member in zip(definition_value["envelope"]["conditions"][0]["predicate"]["members"], wrong_type_members):
            row["type_ref"] = member["type_ref"]
        wrong_type = authority.validate_definition(definition_value)
        self.assertEqual((wrong_type["status"], wrong_type["code"]), ("REFUSED", "TYPE_INVALID"))

        mixed_members = [
            {"type_ref": other_type, "value": "1"},
            {"type_ref": identity_type, "value": "A"},
        ]
        if authority._ordered_unique([canonical(row) for row in mixed_members]):
            mixed_members.reverse()
        definition_value["envelope"]["conditions"] = [membership([row["value"] for row in mixed_members])]
        for row, member in zip(definition_value["envelope"]["conditions"][0]["predicate"]["members"], mixed_members):
            row["type_ref"] = member["type_ref"]
        mixed = authority.validate_definition(definition_value)
        self.assertEqual((mixed["status"], mixed["code"]), ("REFUSED", "TYPE_INVALID"))

        nested_condition = membership(["A", "Z"])
        nested_condition["predicate"] = {
            "kind": "ALL",
            "operands": [
                {"kind": "BOOLEAN", "value": True},
                nested_condition["predicate"],
            ],
        }
        definition_value["envelope"]["conditions"] = [nested_condition]
        definition_value["envelope"]["gate"]["criteria"] = [membership(["A", "Z"], "criterion.membership-test")]
        self.assertEqual(authority.validate_definition(definition_value)["status"], "ACCEPTED")
        nested_condition["predicate"]["operands"][1]["members"].reverse()
        nested_reversed = authority.validate_definition(definition_value)
        self.assertEqual((nested_reversed["status"], nested_reversed["code"]), ("REFUSED", "INPUT_INVALID"))

        nested_criterion = membership(["A", "Z"], "criterion.membership-test")
        nested_criterion["predicate"] = {"kind": "NOT", "operand": nested_criterion["predicate"]}
        definition_value["envelope"]["conditions"] = [membership(["A", "Z"])]
        definition_value["envelope"]["gate"]["criteria"] = [nested_criterion]
        self.assertEqual(authority.validate_definition(definition_value)["status"], "ACCEPTED")
        nested_criterion["predicate"]["operand"]["members"].reverse()
        nested_reversed = authority.validate_definition(definition_value)
        self.assertEqual((nested_reversed["status"], nested_reversed["code"]), ("REFUSED", "INPUT_INVALID"))

        # Predicate references are phase-two checks: the authority's source
        # binding mismatch precedes them, while pure missing references remain
        # REFERENCE_INVALID. TYPE_INVALID above still has its P1 precedence.
        reference_invalid = copy.deepcopy(definition_value)
        reference_invalid["envelope"]["conditions"] = [membership(["A", "Z"])]
        reference_invalid["envelope"]["gate"]["criteria"] = [membership(["A", "Z"], "criterion.membership-test")]
        reference_invalid["envelope"]["conditions"][0]["predicate"]["value"]["name"] = "missing-field"
        self.assertEqual(authority.validate_definition(reference_invalid)["code"], "REFERENCE_INVALID")

        dependency_precedes_reference = copy.deepcopy(reference_invalid)
        dependency_precedes_reference["envelope"]["source_digest"] = "sha256:" + "0" * 64
        refusal = authority.validate_definition(dependency_precedes_reference)
        self.assertEqual((refusal["status"], refusal["code"]), ("REFUSED", "DEPENDENCY_MISMATCH"))

    def test_choice_inventories_preserve_their_independent_source_orders(self):
        for labels_reversed in (False, True):
            for routes_reversed in (False, True):
                with self.subTest(labels=labels_reversed, routes=routes_reversed):
                    value = choice_definition()
                    if labels_reversed:
                        value["choices"][0]["label_values"].reverse()
                    if routes_reversed:
                        value["relationships"].reverse()
                    before = canonical(value)
                    self.assertEqual(artifacts.admit("WORK_CLASS", value), digest("work-class-definition", value))
                    self.assertEqual(artifacts.readback("WORK_CLASS", value)["lines"], readback_lines(value))
                    self.assertEqual(canonical(value), before)

    def test_choice_map_rejects_duplicate_missing_extra_and_ambiguous_routes(self):
        for mutation, code in (("duplicate-label", "SCHEMA_INVALID"), ("missing-route", "DEFINITION_INVALID"),
                               ("extra-route", "DEFINITION_INVALID"), ("ambiguous-route", "DEFINITION_INVALID"),
                               ("wrong-type", "DEFINITION_INVALID")):
            with self.subTest(mutation=mutation):
                value = choice_definition()
                if mutation == "duplicate-label":
                    value["choices"][0]["label_values"][1] = copy.deepcopy(value["choices"][0]["label_values"][0])
                elif mutation == "missing-route":
                    value["relationships"].pop()
                elif mutation == "extra-route":
                    edge = copy.deepcopy(value["relationships"][-1])
                    edge["label"]["value"] = "UNDECLARED"
                    value["relationships"].append(edge)
                elif mutation == "ambiguous-route":
                    value["relationships"][1]["label"] = copy.deepcopy(value["relationships"][0]["label"])
                else:
                    value["choices"][0]["label_values"][0]["type_ref"] = "IDENTITY"
                    value["relationships"][0]["label"]["type_ref"] = "IDENTITY"
                before = canonical(value)
                with self.assertRaises(Refusal) as caught:
                    artifacts.admit("WORK_CLASS", value)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(canonical(value), before)

    def test_keyless_legacy_projection_omits_carrier_and_carrier_only_type(self):
        value = definition("cases/authority-withholding/D2-014.json")
        step = value["steps"][0]
        step["quantity_mode"] = "NONE"
        before = canonical(value)
        artifacts.admit("WORK_CLASS", value)
        members = ("id", "operation", "interface", "executor_role", "fields", "scope_fields", "required_credentials", "quantity_mode", "exclusive_keys")
        expected = {"schema": IDENTITY + "/authority-work-class", "id": value["id"], "revision": value["revision"],
                    "steps": [{name: copy.deepcopy(step[name]) for name in members}],
                    "types": [copy.deepcopy(row) for row in value["types"] if row["id"] in ("IDENTITY", "amount")]}
        self.assertEqual(lifecycle._authority_projection(value), expected)
        self.assertEqual(canonical(value), before)
        step["authority_type_refs"] = ["STRING"]
        artifacts.admit("WORK_CLASS", value)
        expected["steps"][0]["authority_type_refs"] = ["STRING"]
        expected["types"] = copy.deepcopy(value["types"])
        self.assertEqual(lifecycle._authority_projection(value), expected)

    def test_nonempty_keys_and_stop_retain_copy_complete_carrier(self):
        legacy = definition("cases/authority-withholding/D2-014.json")
        key = definition("cases/equipment-completion/C3-EC-066.json")["steps"][0]["exclusive_keys"][0]
        legacy["steps"][0]["exclusive_keys"] = [copy.deepcopy(key)]
        terminal = definition("cases/equipment-completion/C3-EC-066.json")
        terminal["steps"][0]["exclusive_keys"] = []
        for value in (legacy, terminal):
            with self.subTest(policy=value["steps"][0]["completion"]["terminal_policy"]):
                artifacts.admit("WORK_CLASS", value)
                before = canonical(value)
                projected = lifecycle._authority_projection(value)
                self.assertEqual(projected["steps"][0]["completion"], value["steps"][0]["completion"])
                self.assertIn(value["steps"][0]["completion"]["status_type_ref"], [row["id"] for row in projected["types"]])
                self.assertEqual(canonical(value), before)

    def test_native_keyless_legacy_proposal_uses_exact_conditional_projection(self):
        base = base_lifecycle(authority_mutator=no_quantity)
        consumer = Consumer()
        deployed = consumer.deploy(base["deploy_input"])
        common = {key: base["deploy_input"][key] for key in ("profile", "role", "specification_pin", "definition", "definition_digest")}
        clocked = consumer.step(bind_event({**common, "event": base["clock_event"]}, deployed["state"]))
        request = bind_event({**common, "event": base["proposal_event"]}, clocked["state"])
        before = canonical(request)
        permitted = consumer.step(request)
        self.assertEqual(permitted["decision"]["disposition"], "PERMITTED")
        self.assertNotIn("completion", request["event"]["authority_input"]["work_class"]["steps"][0])
        self.assertEqual(canonical(request), before)
        changed = copy.deepcopy(request)
        authority = changed["event"]["authority_input"]
        authority["work_class"]["steps"][0]["completion"] = copy.deepcopy(common["definition"]["steps"][0]["completion"])
        authority["work_class"]["types"] = copy.deepcopy(common["definition"]["types"])
        authority["envelope"]["work_class_digest"] = digest("authority-work-class", authority["work_class"])
        authority["proposal"]["work_class_digest"] = authority["envelope"]["work_class_digest"]
        state_before = canonical(changed["state"])
        refused = consumer.step(changed)
        self.assertEqual((refused["status"], refused["code"]), ("REFUSED", "BINDING_MISMATCH"))
        self.assertEqual(canonical(changed["state"]), state_before)

    def test_proposals_reject_extra_or_missing_carriers_with_rebound_authority_digests(self):
        consumer = Consumer()
        for row in projection_proposal_inputs():
            with self.subTest(case=row["name"]):
                request = row["input"]
                authority = request["event"]["authority_input"]
                actual_digest = digest("authority-work-class", authority["work_class"])
                self.assertEqual(authority["proposal"]["work_class_digest"], actual_digest)
                self.assertEqual(authority["envelope"]["work_class_digest"], actual_digest)
                before = canonical(request)
                result = consumer.step(request)
                if row["expected"]["status"] == "STEP":
                    self.assertEqual(result["decision"]["disposition"], row["expected"]["disposition"])
                else:
                    self.assertEqual(result, row["expected"])
                self.assertEqual(canonical(request), before)


if __name__ == "__main__":
    unittest.main()
