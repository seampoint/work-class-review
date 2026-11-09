#!/usr/bin/env python3
"""Build phase-3 predicate refusal-order cases for authority definitions.

Each case places a phase-2 reference fault and a phase-1 type fault in the
envelope conditions or gate criteria of the access-card authority specimen and
submits the complete definition through `validate` (AUTHORITY_DEFINITION) and
the complete evaluation input through `evaluate` (AUTHORITY). Every expected
code is derived from AUTHORITY-CHECKS "Deterministic refusal selection" and the
static predicate rules; no consumer output is read.
"""

from __future__ import annotations

import base64
import copy
import json

from authority_fixture import authority_refusal, authority_specimen
from corpus_common import CASES, canonical_bytes, candidate_pin, exact_case, write_canonical_json


EXPECTED_PIN = "sha256:fd52d69dd3c3546bff2cec9d46fb8d6b942fd57b77b0a3ab8377a592e80d00b6"
GROUP = CASES / "phase3-predicate-order"
SCHEMA = "seampoint.work-class/1.0.0-draft.3/"
STEP = "issue"

# Reference fault: both operands carry the same nominal type_ref, which the
# work class does not declare. The operands' nominal types are equal, so no
# operand-compatibility fault exists; the sole fault is the unknown type
# reference (AUTHORITY-CHECKS: "unknown type references are REFERENCE_INVALID";
# type-reference resolution is deferred to phase 2).
UNKNOWN_TYPE = "zz-undeclared-type"
REF = {
    "kind": "EQUAL",
    "left": {"kind": "LITERAL", "value": {"type_ref": UNKNOWN_TYPE, "value": "x"}},
    "right": {"kind": "LITERAL", "value": {"type_ref": UNKNOWN_TYPE, "value": "x"}},
}

# Type fault: COMPARE over two well-formed operands of the declared IDENTITY
# type. AGG-003 COMPARE accepts only equal INTEGER or DECIMAL types.
TYPE = {
    "kind": "COMPARE",
    "left": {"kind": "FIELD", "name": "beneficiary"},
    "right": {"kind": "LITERAL", "value": {"type_ref": "IDENTITY", "value": "employee-7"}},
    "operator": "LT",
}

# Undeclared-field fault: a FIELD operand naming no field of step issue.
UNDECLARED_FIELD = {
    "kind": "EQUAL",
    "left": {"kind": "FIELD", "name": "zz-undeclared-field"},
    "right": {"kind": "LITERAL", "value": {"type_ref": "IDENTITY", "value": "employee-7"}},
}

TRUE = {"kind": "BOOLEAN", "value": True}
FALSE = {"kind": "BOOLEAN", "value": False}

PHASE_RULE = (
    "AUTHORITY-CHECKS Deterministic refusal selection: phase order governs before within-phase code order; "
    "directly checkable failures are accumulated within the phase and loop order cannot choose a different result. "
    "TYPE_INVALID is a phase-1 code; REFERENCE_INVALID is a phase-2 code, and type-reference resolution is deferred "
    "to phase 2 to distinguish a missing declaration from a malformed known value."
)
STATIC_RULE = (
    "AUTHORITY-CHECKS Static definition admission: static literal types and all operand compatibility are checked "
    "even if another branch determines the predicate; AUTH-001: all branches are type-checked, including false or "
    "unused branches. AGG-003: COMPARE accepts equal INTEGER or DECIMAL types, so COMPARE over IDENTITY beneficiary "
    "and an IDENTITY literal is a type fault (AGGREGATES dynamic matrix: qualifier operand types are TYPE_INVALID)."
)
REF_RULE = (
    "AUTHORITY-CHECKS Record and time admission: unknown type references are REFERENCE_INVALID. The reference-fault "
    "EQUAL compares two literals with the same undeclared type_ref, so its operand types are nominally equal and its "
    "only fault is the unknown reference."
)
RC_RULE = (
    "AUTHORITY-CHECKS Static definition admission (R-c): a FIELD operand naming a field its row's step does not "
    "declare is REFERENCE_INVALID; AGG-003's missing-field input error applies to a declared field absent from "
    "supplied values."
)
RB_RULE = (
    "AUTHORITY-CHECKS Deterministic refusal selection, phase-1 item (R-b): an operand whose known nominal type alone "
    "violates its operator's type rule is TYPE_INVALID even when another operand's type reference is unknown; when "
    "the violation depends on the unknown type, the result is REFERENCE_INVALID."
)
SHAPE_RULE = (
    "For validate the refusal uses the PROTOCOL shapeRefusal {status,code,path:\"\"}. For evaluate AUTHORITY-CHECKS "
    "gives {status,code,path:\"\",reasons,failed_checks}; reasons are empty for every code except "
    "AUTHORITY_NOT_ESTABLISHED and failed_checks is empty for every other code."
)


def condition(row_id: str, predicate: dict) -> dict:
    return {"id": row_id, "step": STEP, "predicate": copy.deepcopy(predicate)}


def conditions_mutator(rows: list[dict]):
    def mutate(request: dict, _original: dict) -> None:
        request["envelope"]["conditions"] = sorted(copy.deepcopy(rows), key=lambda row: row["id"].encode("utf-8"))
    return mutate


def gate_mutator(condition_rows: list[dict], criterion_rows: list[dict]):
    """A VERIFY gate is stricter than the LOW/HIGH floor and is valid (AUTH-002)."""
    def mutate(request: dict, _original: dict) -> None:
        request["envelope"]["conditions"] = sorted(copy.deepcopy(condition_rows), key=lambda row: row["id"].encode("utf-8"))
        request["envelope"]["gate"] = {
            "materiality": "LOW",
            "reversibility": "HIGH",
            "kind": "VERIFY",
            "role": "card-verifier",
            "criteria": sorted(copy.deepcopy(criterion_rows), key=lambda row: row["id"].encode("utf-8")),
        }
    return mutate


def validate_input(request: dict) -> dict:
    definition = {
        "schema": SCHEMA + "authority-definition",
        "source": copy.deepcopy(request["source"]),
        "work_class": copy.deepcopy(request["work_class"]),
        "envelope": copy.deepcopy(request["envelope"]),
    }
    return {
        "kind": "AUTHORITY_DEFINITION",
        "specification_pin": candidate_pin(),
        "artifact_bytes_base64": base64.b64encode(canonical_bytes(definition)).decode("ascii"),
    }


# (slug, mutator, code, requirements, arrangement description)
BASE_REQ = ["AUTH-001", "AUTH-006", "AGG-003"]
GATE_REQ = ["AUTH-001", "AUTH-002", "AUTH-006", "AGG-003"]

ARRANGEMENTS = [
    ("rows-reference-first",
     conditions_mutator([condition("a-reference-fault", REF), condition("b-type-fault", TYPE), condition("issue-condition", TRUE)]),
     "TYPE_INVALID", BASE_REQ,
     "Separate condition rows sorted by id: a-reference-fault (unknown type reference) precedes b-type-fault (COMPARE over IDENTITY)."),
    ("rows-type-first",
     conditions_mutator([condition("a-type-fault", TYPE), condition("b-reference-fault", REF), condition("issue-condition", TRUE)]),
     "TYPE_INVALID", BASE_REQ,
     "Separate condition rows sorted by id: a-type-fault (COMPARE over IDENTITY) precedes b-reference-fault (unknown type reference)."),
    ("all-reference-type",
     conditions_mutator([condition("issue-condition", {"kind": "ALL", "operands": [REF, TYPE]})]),
     "TYPE_INVALID", BASE_REQ,
     "One condition predicate ALL[reference fault, type fault]."),
    ("all-type-reference",
     conditions_mutator([condition("issue-condition", {"kind": "ALL", "operands": [TYPE, REF]})]),
     "TYPE_INVALID", BASE_REQ,
     "One condition predicate ALL[type fault, reference fault]."),
    ("any-reference-type",
     conditions_mutator([condition("issue-condition", {"kind": "ANY", "operands": [REF, TYPE]})]),
     "TYPE_INVALID", BASE_REQ,
     "One condition predicate ANY[reference fault, type fault]."),
    ("any-type-reference",
     conditions_mutator([condition("issue-condition", {"kind": "ANY", "operands": [TYPE, REF]})]),
     "TYPE_INVALID", BASE_REQ,
     "One condition predicate ANY[type fault, reference fault]."),
    ("not-all-reference-type",
     conditions_mutator([condition("issue-condition", {"kind": "NOT", "operand": {"kind": "ALL", "operands": [REF, TYPE]}})]),
     "TYPE_INVALID", BASE_REQ,
     "One condition predicate NOT[ALL[reference fault, type fault]]."),
    ("all-not-reference-not-type",
     conditions_mutator([condition("issue-condition", {"kind": "ALL", "operands": [
         {"kind": "NOT", "operand": REF}, {"kind": "NOT", "operand": TYPE}]})]),
     "TYPE_INVALID", BASE_REQ,
     "One condition predicate ALL[NOT[reference fault], NOT[type fault]]."),
    ("any-true-decides-reference-type",
     conditions_mutator([condition("issue-condition", {"kind": "ANY", "operands": [TRUE, REF, TYPE]})]),
     "TYPE_INVALID", BASE_REQ,
     "One condition predicate ANY[BOOLEAN true, reference fault, type fault]; the leading true branch already decides the value, so both faults sit in unused branches."),
    ("all-false-decides-type-reference",
     conditions_mutator([condition("issue-condition", {"kind": "ALL", "operands": [FALSE, TYPE, REF]})]),
     "TYPE_INVALID", BASE_REQ,
     "One condition predicate ALL[BOOLEAN false, type fault, reference fault]; the leading false branch already decides the value, so both faults sit in unused branches."),
    ("gate-type-condition-reference",
     gate_mutator([condition("issue-condition", REF)], [condition("verify-criterion", TYPE)]),
     "TYPE_INVALID", GATE_REQ,
     "A stricter VERIFY gate criterion carries the type fault; the step's condition carries the reference fault."),
    ("gate-reference-condition-type",
     gate_mutator([condition("issue-condition", TYPE)], [condition("verify-criterion", REF)]),
     "TYPE_INVALID", GATE_REQ,
     "A stricter VERIFY gate criterion carries the reference fault; the step's condition carries the type fault."),
    ("rows-undeclared-field-first",
     conditions_mutator([condition("a-reference-fault", UNDECLARED_FIELD), condition("b-type-fault", TYPE), condition("issue-condition", TRUE)]),
     "TYPE_INVALID", BASE_REQ,
     "Separate condition rows: a-reference-fault has a FIELD operand naming zz-undeclared-field, which step issue does not declare, and sorts before b-type-fault. By AUTHORITY-CHECKS Static definition admission (R-c) that operand is REFERENCE_INVALID, a phase-2 code; AGG-003's missing-field input error does not apply because the field is undeclared, not a declared field absent from supplied values."),
    ("all-undeclared-field-type",
     conditions_mutator([condition("issue-condition", {"kind": "ALL", "operands": [UNDECLARED_FIELD, TYPE]})]),
     "TYPE_INVALID", BASE_REQ,
     "One condition predicate ALL[FIELD zz-undeclared-field EQUAL IDENTITY literal, type fault]. By AUTHORITY-CHECKS Static definition admission (R-c) the FIELD operand naming a field step issue does not declare is REFERENCE_INVALID, a phase-2 code, not AGG-003's missing-field input error."),
    ("control-reference-alone",
     conditions_mutator([condition("a-reference-fault", REF), condition("issue-condition", TRUE)]),
     "REFERENCE_INVALID", BASE_REQ,
     "Control: the reference-fault row alone, with no type fault anywhere. The baseline specimen is otherwise unchanged, so no other phase-2 code that precedes REFERENCE_INVALID applies."),
    ("control-type-alone",
     conditions_mutator([condition("a-type-fault", TYPE), condition("issue-condition", TRUE)]),
     "TYPE_INVALID", BASE_REQ,
     "Control: the type-fault row alone, with no reference fault."),
    ("control-gate-type-alone",
     gate_mutator([condition("issue-condition", TRUE)], [condition("verify-criterion", TYPE)]),
     "TYPE_INVALID", GATE_REQ,
     "Control: a stricter VERIFY gate whose only criterion carries the type fault; no reference fault."),
]


# Owner rulings R-b and R-c (cases numbered from 035). Each derivation is explicit.
COMPARE_IDENTITY_UNKNOWN = {
    "kind": "COMPARE",
    "left": {"kind": "FIELD", "name": "beneficiary"},
    "right": {"kind": "LITERAL", "value": {"type_ref": UNKNOWN_TYPE, "value": "1"}},
    "operator": "LT",
}
INTEGER_TYPE = {"id": "count", "kind": "INTEGER", "nonnegative": False, "unit": None}
COMPARE_INTEGER_UNKNOWN = {
    "kind": "COMPARE",
    "left": {"kind": "LITERAL", "value": {"type_ref": "count", "value": "1"}},
    "right": {"kind": "LITERAL", "value": {"type_ref": UNKNOWN_TYPE, "value": "1"}},
    "operator": "LT",
}
COMPARE_DECIMAL_UNKNOWN = {
    "kind": "COMPARE",
    "left": {"kind": "FIELD", "name": "amount"},
    "right": {"kind": "LITERAL", "value": {"type_ref": UNKNOWN_TYPE, "value": "1"}},
    "operator": "LT",
}


def integer_type_mutator(rows: list[dict]):
    """Declare a known INTEGER scalar type (AGG-001) and install the condition rows."""
    install = conditions_mutator(rows)

    def mutate(request: dict, original: dict) -> None:
        types = request["work_class"]["types"] + [copy.deepcopy(INTEGER_TYPE)]
        request["work_class"]["types"] = sorted(types, key=lambda row: row["id"].encode("utf-8"))
        install(request, original)
    return mutate


EXTENSION = [
    ("rb-compare-identity-vs-unknown",
     conditions_mutator([condition("a-compare-fault", COMPARE_IDENTITY_UNKNOWN), condition("issue-condition", TRUE)]),
     "TYPE_INVALID", BASE_REQ,
     " ".join([
         "One condition COMPARE(FIELD beneficiary, LITERAL with undeclared type_ref zz-undeclared-type). beneficiary is declared IDENTITY on step issue.",
         "AGG-003: COMPARE accepts only equal INTEGER or DECIMAL types, so the known IDENTITY operand alone violates COMPARE's type rule whatever the unknown type is.",
         RB_RULE, PHASE_RULE,
         "The violation does not depend on the unknown type, so R-b makes it a phase-1 TYPE_INVALID failure, which precedes the phase-2 unknown-reference failure."])),
    ("rb-compare-integer-vs-unknown",
     integer_type_mutator([condition("a-compare-fault", COMPARE_INTEGER_UNKNOWN), condition("issue-condition", TRUE)]),
     "REFERENCE_INVALID", BASE_REQ,
     " ".join([
         "The work class additionally declares scalar type count of kind INTEGER (nonnegative false, unit null, valid under AGG-001; types stay sorted by id). One condition COMPARE(LITERAL count \"1\", LITERAL with undeclared type_ref zz-undeclared-type).",
         "AGG-003: COMPARE accepts equal INTEGER or DECIMAL types. The known INTEGER operand alone satisfies its side of that rule; whether the pair is compatible depends only on the unknown type.",
         RB_RULE, REF_RULE.split(". The reference-fault")[0] + ".", PHASE_RULE,
         "No phase-1 failure exists, so the first failing phase is phase 2 and R-b gives REFERENCE_INVALID."])),
    ("rb-compare-decimal-field-vs-unknown",
     conditions_mutator([condition("a-compare-fault", COMPARE_DECIMAL_UNKNOWN), condition("issue-condition", TRUE)]),
     "REFERENCE_INVALID", BASE_REQ,
     " ".join([
         "Companion to the INTEGER case with no added declaration: one condition COMPARE(FIELD amount, LITERAL with undeclared type_ref zz-undeclared-type). amount is declared on step issue as the nonnegative DECIMAL type amount.",
         "AGG-003: COMPARE accepts equal INTEGER or DECIMAL types. The known DECIMAL operand alone does not violate that rule; the violation depends only on the unknown type.",
         RB_RULE, REF_RULE.split(". The reference-fault")[0] + ".", PHASE_RULE,
         "No phase-1 failure exists, so the first failing phase is phase 2 and R-b gives REFERENCE_INVALID."])),
    ("rc-control-undeclared-field-alone",
     conditions_mutator([condition("a-reference-fault", UNDECLARED_FIELD), condition("issue-condition", TRUE)]),
     "REFERENCE_INVALID", BASE_REQ,
     " ".join([
         "Control: one condition EQUAL(FIELD zz-undeclared-field, LITERAL IDENTITY \"employee-7\"); step issue declares no field zz-undeclared-field. No other fault is present; the IDENTITY literal is well formed and EQUAL places no kind restriction a known IDENTITY operand violates alone.",
         RC_RULE, RB_RULE, PHASE_RULE,
         "The only fault is the undeclared-field reference, so the first failing phase is phase 2 and the code is REFERENCE_INVALID. The baseline specimen is otherwise unchanged, so no earlier phase-2 code applies."])),
    ("rb-member-known-value-unknown-member",
     conditions_mutator([condition("a-member-fault", {
         "kind": "MEMBER",
         "value": {"kind": "FIELD", "name": "beneficiary"},
         "members": [{"type_ref": UNKNOWN_TYPE, "value": "employee-7"}],
     }), condition("issue-condition", TRUE)]),
     "REFERENCE_INVALID", BASE_REQ,
     " ".join([
         "One condition MEMBER(FIELD beneficiary, members [{type_ref zz-undeclared-type, value \"employee-7\"}]). beneficiary is declared IDENTITY on step issue; zz-undeclared-type is not declared. The one-member list is a canonical sorted set.",
         "AGG-003: MEMBER requires every member to have the operand's nominal type and places no kind restriction on the value operand, so the known IDENTITY value is admissible for MEMBER on its own.",
         "Whether the member's nominal type equals IDENTITY depends only on the unknown type reference.",
         RB_RULE, REF_RULE.split(". The reference-fault")[0] + ".", PHASE_RULE,
         "No phase-1 failure exists, so the first failing phase is phase 2 and R-b gives REFERENCE_INVALID."])),
    ("member-known-type-mismatch-control",
     conditions_mutator([condition("a-member-fault", {
         "kind": "MEMBER",
         "value": {"kind": "FIELD", "name": "beneficiary"},
         "members": [{"type_ref": "amount", "value": "1"}],
     }), condition("issue-condition", TRUE)]),
     "TYPE_INVALID", BASE_REQ,
     " ".join([
         "Control: one condition MEMBER(FIELD beneficiary, members [{type_ref amount, value \"1\"}]). beneficiary is declared IDENTITY; amount is the declared nonnegative DECIMAL type and \"1\" is a valid nonnegative canonical decimal, so both types are known and every scalar is well formed.",
         "AGG-003: MEMBER requires every member to have the operand's nominal type; amount differs from IDENTITY, an operand-compatibility fault.",
         STATIC_RULE.split(" AGG-003:")[0], PHASE_RULE,
         "No reference fault exists, so the only fault is phase-1 TYPE_INVALID."])),
]


def derivation(description: str, code: str) -> str:
    if code == "REFERENCE_INVALID":
        decision = "The only fault is the unknown type reference, so the first failing phase is phase 2 and the code is REFERENCE_INVALID."
        rules = [REF_RULE, PHASE_RULE]
    elif "reference" in description or "undeclared" in description:
        decision = ("Phase 1 already has a directly checkable TYPE_INVALID failure, so phase 1 is the first failing phase "
                    "and the refusal is TYPE_INVALID regardless of row order, operand order or connective.")
        rules = [STATIC_RULE, REF_RULE, PHASE_RULE]
        if "undeclared" in description:
            rules = [STATIC_RULE, RC_RULE, PHASE_RULE]
    else:
        decision = "The only fault is the phase-1 operand-compatibility failure, so the code is TYPE_INVALID."
        rules = [STATIC_RULE, PHASE_RULE]
    return " ".join([description, *rules, decision, SHAPE_RULE,
                     "Every source, class, envelope, proposal, operation, root, capacity and act digest is rebound after the mutation. "
                     "Expected judgment derived from the specification text before any consumer execution."])


def main() -> None:
    pin = candidate_pin()
    if pin != EXPECTED_PIN:
        raise SystemExit(f"candidate pin {pin} differs from expected {EXPECTED_PIN}")
    cases = []
    number = 0
    for slug, mutate, code, requirements, description in ARRANGEMENTS:
        request, _ready = authority_specimen(mutator=mutate)
        text = derivation(description, code)
        number += 1
        cases.append(exact_case(
            f"C3-P3-PRED-{number:03d}", "validate", validate_input(request),
            {"status": "REFUSED", "code": code, "path": ""},
            list(requirements), f"[{slug}; validate AUTHORITY_DEFINITION] " + text,
        ))
        number += 1
        cases.append(exact_case(
            f"C3-P3-PRED-{number:03d}", "evaluate", {"kind": "AUTHORITY", "request": request},
            authority_refusal([], code=code),
            list(requirements), f"[{slug}; evaluate AUTHORITY] " + text,
        ))
    for slug, mutate, code, requirements, explicit in EXTENSION:
        request, _ready = authority_specimen(mutator=mutate)
        text = " ".join([explicit, SHAPE_RULE,
                         "Every source, class, envelope, proposal, operation, root, capacity and act digest is rebound after the mutation. "
                         "Expected judgment derived from the specification text before any consumer execution."])
        number += 1
        cases.append(exact_case(
            f"C3-P3-PRED-{number:03d}", "validate", validate_input(request),
            {"status": "REFUSED", "code": code, "path": ""},
            list(requirements), f"[{slug}; validate AUTHORITY_DEFINITION] " + text,
        ))
        number += 1
        cases.append(exact_case(
            f"C3-P3-PRED-{number:03d}", "evaluate", {"kind": "AUTHORITY", "request": request},
            authority_refusal([], code=code),
            list(requirements), f"[{slug}; evaluate AUTHORITY] " + text,
        ))
    for case in cases:
        write_canonical_json(GROUP / f"{case['id']}.json", case)
    print(json.dumps({
        "candidate_pin": pin,
        "cases": [{"id": case["id"], "operation": case["operation"], "code": case["expected"]["code"],
                   "arrangement": case["derivation"].split("]", 1)[0].lstrip("[")} for case in cases],
    }, indent=2))


if __name__ == "__main__":
    main()
