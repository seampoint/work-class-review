"""Regressions for the Phase 3 repairs: alias settlement, retraction marking,
predicate fault order and native projection through a known reservation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT.parent / "review")]

from consumer import Consumer
from implementation import authority, reservation_v2

CASES = ROOT.parent / "cases"


def sealed(case_id):
    path = next(CASES.glob(f"phase3-*/{case_id}.json"))
    return json.loads(path.read_text())


def run_sealed(case_id):
    case = sealed(case_id)
    return case, Consumer().call(case["operation"], case["input"])


def alias_budget(contribution_kind="SUM"):
    source_contribution = {"kind": contribution_kind}
    mapping_contribution = {"kind": contribution_kind}
    if contribution_kind != "COUNT":
        source_contribution["field"] = "historical-amount"
        mapping_contribution["field"] = "amount"
    return {
        "definition_digest": "sha256:" + "0" * 64,
        "definition": {"aggregate": {"aggregate": {
            "committed_source": {"key_fields": ["historical-beneficiary"], "contribution": source_contribution},
            "mappings": [{"id": "pay", "key_fields": ["beneficiary"], "contribution": mapping_contribution}],
        }}},
    }


class AliasSettlementTests(unittest.TestCase):
    contribution = {
        "anchor": "license-spend",
        "mapping": "pay",
        "key": [{"type_ref": "IDENTITY", "value": "employee-7"}],
        "value": {"type_ref": "amount", "value": "150"},
    }

    def test_prescribed_record_uses_committed_source_names(self):
        record = reservation_v2._prescribed_event(alias_budget(), self.contribution, "effect-1", "2026-09-10T04:30:00Z")
        self.assertEqual([row["name"] for row in record["fields"]], ["historical-amount", "historical-beneficiary"])
        self.assertEqual(record["state"], "ACTIVE")
        self.assertEqual(record["id"], reservation_v2.digest("reservation-committed-event", {
            "budget_digest": "sha256:" + "0" * 64, "effect_id": "effect-1", "mapping": "pay"}))

    def test_count_prescribed_record_has_no_contribution_field(self):
        record = reservation_v2._prescribed_event(alias_budget("COUNT"), self.contribution, "effect-1", "2026-09-10T04:30:00Z")
        self.assertEqual([row["name"] for row in record["fields"]], ["historical-beneficiary"])

    def test_record_with_mapping_names_is_not_the_prescribed_record(self):
        expected = reservation_v2._prescribed_event(alias_budget(), self.contribution, "effect-1", "2026-09-10T04:30:00Z")
        wrong = copy.deepcopy(expected)
        wrong["fields"] = [{"name": "amount", "value": self.contribution["value"]},
                           {"name": "beneficiary", "value": self.contribution["key"][0]}]
        history = {"status": "AVAILABLE", "journal": [{"sequence": "1", "event": wrong}]}
        self.assertFalse(reservation_v2._history_has_prescribed(history, expected))
        extra = copy.deepcopy(expected)
        extra["fields"].append({"name": "zz-extra", "value": self.contribution["value"]})
        history["journal"][0]["event"] = extra
        self.assertFalse(reservation_v2._history_has_prescribed(history, expected))

    def test_sealed_alias_settlement_and_recovery_cases(self):
        for case_id in ("C3-P3-ALIAS-001", "C3-P3-ALIAS-004", "C3-P3-ALIAS-010", "C3-P3-ALIAS-018"):
            with self.subTest(case_id):
                case, actual = run_sealed(case_id)
                self.assertEqual(actual, case["expected"])


class RetractionMarkingTests(unittest.TestCase):
    def test_retraction_marks_settled_reservation_and_keeps_matched_effect(self):
        case = sealed("C3-P3-ALIAS-016")
        core = copy.deepcopy(case["input"]["state"]["core"])
        history = case["input"]["event"]["payload"]["histories"][0]
        budget = next(row for row in core["budgets"] if row["definition_digest"] == history["budget_digest"])
        effects_before = copy.deepcopy(core["effects"])
        self.assertEqual([row["status"] for row in core["reservations"]], ["SETTLED"])
        reservation_v2._mark_retracted_matches(core, budget, history)
        self.assertEqual([row["status"] for row in core["reservations"]], ["DISPUTED"])
        self.assertEqual(core["effects"], effects_before)
        self.assertIsNotNone(core["reservations"][0]["matched_effect"])
        anchor = budget["definition"]["anchor"]
        key = core["reservations"][0]["contributions"][0]["key"]
        self.assertTrue(reservation_v2._blocked(core, anchor, key))

    def test_unchanged_history_does_not_mark(self):
        case = sealed("C3-P3-ALIAS-016")
        core = copy.deepcopy(case["input"]["state"]["core"])
        budget = core["budgets"][0]
        reservation_v2._mark_retracted_matches(core, budget, copy.deepcopy(budget["history"]))
        self.assertEqual([row["status"] for row in core["reservations"]], ["SETTLED"])

    def test_retracted_actual_preserves_dispute_without_numerical_judgment(self):
        for case_id in ("C3-P3-ALIAS-014", "C3-P3-ALIAS-015", "C3-P3-ALIAS-016", "C3-P3-ALIAS-017"):
            with self.subTest(case_id):
                case, actual = run_sealed(case_id)
                self.assertEqual(actual["receipt"]["decision"], "WITHHELD")
                self.assertEqual(actual["receipt"]["reasons"],
                                 ["EXPOSURE_DISPUTED", "HISTORY_UNCORROBORATED", "RECOVERY_EVIDENCE_INCOMPLETE"])
                self.assertEqual(actual["receipt"]["budgets"], [])
                self.assertEqual(actual, case["expected"])


def predicate_definition(conditions, criteria=()):
    return {
        "work_class": {
            "types": [
                {"id": "IDENTITY", "kind": "IDENTITY", "nonnegative": False, "unit": None},
                {"id": "amount", "kind": "DECIMAL", "nonnegative": True, "unit": "USD"},
            ],
            "steps": [{"id": "issue", "fields": [
                {"name": "amount", "type_ref": "amount"},
                {"name": "beneficiary", "type_ref": "IDENTITY"},
            ]}],
        },
        "envelope": {
            "conditions": [{"id": f"row-{index}", "step": "issue", "predicate": row} for index, row in enumerate(conditions)],
            "gate": {"criteria": [{"id": f"gate-{index}", "step": "issue", "predicate": row} for index, row in enumerate(criteria)]},
        },
    }


FIELD_BENEFICIARY = {"kind": "FIELD", "name": "beneficiary"}
FIELD_AMOUNT = {"kind": "FIELD", "name": "amount"}
UNKNOWN_LITERAL = {"kind": "LITERAL", "value": {"type_ref": "zz-undeclared-type", "value": "1"}}
REFERENCE_FAULT = {"kind": "EQUAL", "left": UNKNOWN_LITERAL, "right": UNKNOWN_LITERAL}
UNDECLARED_FIELD = {"kind": "EQUAL", "left": {"kind": "FIELD", "name": "zz-undeclared-field"},
                    "right": {"kind": "LITERAL", "value": {"type_ref": "IDENTITY", "value": "employee-7"}}}
TYPE_FAULT = {"kind": "COMPARE", "operator": "LT", "left": FIELD_BENEFICIARY, "right": FIELD_BENEFICIARY}


class PredicateOrderTests(unittest.TestCase):
    def code(self, conditions, criteria=()):
        return authority._predicate_admission(predicate_definition(conditions, criteria))

    def test_row_order_does_not_choose(self):
        self.assertEqual(self.code([REFERENCE_FAULT, TYPE_FAULT]), "TYPE_INVALID")
        self.assertEqual(self.code([TYPE_FAULT, REFERENCE_FAULT]), "TYPE_INVALID")
        self.assertEqual(self.code([UNDECLARED_FIELD, TYPE_FAULT]), "TYPE_INVALID")

    def test_every_branch_is_checked(self):
        for kind in ("ALL", "ANY"):
            self.assertEqual(self.code([{"kind": kind, "operands": [REFERENCE_FAULT, TYPE_FAULT]}]), "TYPE_INVALID")
        deciding = {"kind": "ANY", "operands": [{"kind": "BOOLEAN", "value": True}, REFERENCE_FAULT, TYPE_FAULT]}
        self.assertEqual(self.code([deciding]), "TYPE_INVALID")
        nested = {"kind": "NOT", "operand": {"kind": "ALL", "operands": [REFERENCE_FAULT, TYPE_FAULT]}}
        self.assertEqual(self.code([nested]), "TYPE_INVALID")

    def test_gate_criteria_and_conditions_accumulate(self):
        self.assertEqual(self.code([REFERENCE_FAULT], [TYPE_FAULT]), "TYPE_INVALID")
        self.assertEqual(self.code([TYPE_FAULT], [REFERENCE_FAULT]), "TYPE_INVALID")

    def test_reference_faults_alone(self):
        self.assertEqual(self.code([REFERENCE_FAULT]), "REFERENCE_INVALID")
        self.assertEqual(self.code([UNDECLARED_FIELD]), "REFERENCE_INVALID")

    def test_known_type_violation_beside_unknown_type(self):
        identity_compare = {"kind": "COMPARE", "operator": "LT", "left": FIELD_BENEFICIARY, "right": UNKNOWN_LITERAL}
        self.assertEqual(self.code([identity_compare]), "TYPE_INVALID")
        decimal_compare = {"kind": "COMPARE", "operator": "LT", "left": FIELD_AMOUNT, "right": UNKNOWN_LITERAL}
        self.assertEqual(self.code([decimal_compare]), "REFERENCE_INVALID")

    def test_member_with_unknown_member_type_is_reference_invalid(self):
        unknown_member = {"kind": "MEMBER", "value": FIELD_BENEFICIARY,
                          "members": [{"type_ref": "zz-undeclared-type", "value": "employee-7"}]}
        self.assertEqual(self.code([unknown_member]), "REFERENCE_INVALID")
        mismatched_member = {"kind": "MEMBER", "value": FIELD_BENEFICIARY,
                             "members": [{"type_ref": "amount", "value": "1"}]}
        self.assertEqual(self.code([mismatched_member]), "TYPE_INVALID")
        self.assertEqual(self.code([unknown_member, mismatched_member]), "TYPE_INVALID")

    def test_sealed_predicate_order_cases(self):
        for path in sorted(CASES.glob("phase3-predicate-order/*.json")):
            case = json.loads(path.read_text())
            with self.subTest(case["id"]):
                self.assertEqual(Consumer().call(case["operation"], case["input"]), case["expected"])


class KnownReservationProjectionTests(unittest.TestCase):
    def test_known_reservation_projects_through_its_own_authorization(self):
        case = sealed("C3-P3-RENEW-010")
        core = case["input"]["state"]["core"]
        reservation = core["reservations"][0]
        budget = next(row for row in core["budgets"] if row["definition"]["anchor"] == reservation["contributions"][0]["anchor"])
        self.assertEqual(len(budget["authorizations"]), 2)
        request, _ = reservation_v2._native_request(reservation, budget)
        self.assertIsNone(reservation_v2._native_contributions(budget, request))
        projected = reservation_v2._native_contributions(budget, request, reservation)
        self.assertEqual([row["key"] for row in projected], [row["key"] for row in reservation["contributions"]])

    def test_renew_of_settled_target_with_two_authorizations(self):
        case, actual = run_sealed("C3-P3-RENEW-010")
        self.assertEqual(actual["code"], "INPUT_INVALID")
        self.assertEqual(actual, case["expected"])


class ReturnChannelTests(unittest.TestCase):
    """M1: a returned act must name a declared channel and a declared provider
    (the October 21 repair to authority._phase_two)."""

    def mutated(self, field, value):
        from authority_fixture import authority_specimen
        from implementation.common import canonical, digest
        request, _ = authority_specimen(shared_budget=False)
        original = request["returns"][0]
        changed = copy.deepcopy(original)
        changed[field] = value
        request["returns"][0] = changed
        old, new = digest("authority-return", original), digest("authority-return", changed)
        for record in request["host_selection"]["authenticated_records"]:
            if record["kind"] == "RETURN" and record["record_digest"] == old:
                record.update(record_digest=new, provider=changed["provider"], channel=changed["channel"])
        request["host_selection"]["authenticated_records"].sort(key=canonical)
        return request

    def test_unchanged_specimen_is_ready(self):
        from authority_fixture import authority_specimen
        from implementation.completion import PIN
        request, _ = authority_specimen(shared_budget=False)
        self.assertEqual(authority.evaluate_authority(request, PIN)["status"], "READY_FOR_RESERVATION")

    def test_undeclared_return_channel_or_provider_is_dependency_mismatch(self):
        from implementation.completion import PIN
        for field, value in (("channel", "undeclared-channel"), ("provider", "undeclared-provider")):
            with self.subTest(field=field):
                result = authority.evaluate_authority(self.mutated(field, value), PIN)
                self.assertEqual((result["status"], result["code"]), ("REFUSED", "DEPENDENCY_MISMATCH"))


if __name__ == "__main__":
    unittest.main()
