#!/usr/bin/env python3
"""Build draft-3 quantity-mode definition cases from the normative fixture."""

from __future__ import annotations

import copy
import base64

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from corpus_common import candidate_pin
from fixture_factory import work_class


GROUP = CASES / "quantity-mode"


def artifact_input(raw: bytes) -> dict:
    return {
        "kind": "WORK_CLASS",
        "specification_pin": candidate_pin(),
        "artifact_bytes_base64": base64.b64encode(raw).decode("ascii"),
    }


def accepted(definition: dict) -> dict:
    return {"status": "ACCEPTED", "digest": digest("work-class-definition", definition)}


def refused(code: str) -> dict:
    return {"status": "REFUSED", "code": code, "path": ""}


def case(case_id: str, definition: dict, expected: dict, derivation: str) -> dict:
    return exact_case(
        case_id,
        "validate",
        artifact_input(canonical_bytes(definition)),
        expected,
        ["WCD-001"],
        derivation,
    )


def main() -> None:
    bounded = work_class(quantity_mode="BOUNDED")
    quantity_free = work_class(quantity_mode="NONE")

    cases = [
        case(
            "C3-QTY-001",
            quantity_free,
            accepted(quantity_free),
            "A proposal-capable operation may explicitly declare NONE when it contributes no quantity-bearing shared reservation. The definition remains otherwise closed and valid.",
        ),
        case(
            "C3-QTY-002",
            bounded,
            accepted(bounded),
            "The explicit legacy BOUNDED mode remains valid for an operation without shared reservation anchors.",
        ),
    ]

    budgeted_none = copy.deepcopy(quantity_free)
    budgeted_none["steps"][0]["shared_budgets"] = ["license-spend"]
    budgeted_none["shared_budgets"] = ["license-spend"]
    cases.append(
        case(
            "C3-QTY-003",
            budgeted_none,
            refused("DEFINITION_INVALID"),
            "NONE cannot be combined with a shared budget anchor because the operation declares no quantity contribution while the anchor requires reservation accounting.",
        )
    )

    invalid_enum = copy.deepcopy(quantity_free)
    invalid_enum["steps"][0]["quantity_mode"] = "UNBOUNDED"
    cases.append(
        case(
            "C3-QTY-004",
            invalid_enum,
            refused("SCHEMA_INVALID"),
            "The quantity mode is a closed enum. An undeclared mode fails artifact shape admission before work-class semantics are evaluated.",
        )
    )

    structural = copy.deepcopy(quantity_free)
    structural["steps"][1]["quantity_mode"] = "NONE"
    cases.append(
        case(
            "C3-QTY-005",
            structural,
            refused("DEFINITION_INVALID"),
            "Quantity mode belongs only to proposal-capable operations. A structural terminal step cannot carry it.",
        )
    )

    for case_id, member in (("C3-QTY-006", "quantity_mode"), ("C3-QTY-007", "exclusive_keys")):
        missing = copy.deepcopy(bounded)
        missing["steps"][0].pop(member)
        cases.append(case(case_id, missing, refused("SCHEMA_INVALID"),
            "Every migrated proposal-capable step explicitly declares " + member + ". Omission refuses shape admission and cannot acquire an implicit inherited default."))
    missing_policy = copy.deepcopy(bounded)
    missing_policy["steps"][0]["completion"].pop("terminal_policy")
    cases.append(case("C3-QTY-008", missing_policy, refused("SCHEMA_INVALID"),
        "Every completion carrier explicitly declares its terminal policy. An omitted policy cannot silently acquire LEGACY_NONTERMINAL behavior."))

    for item in cases:
        write_canonical_json(GROUP / f"{item['id']}.json", item)
    print({"case_ids": [item["id"] for item in cases]})


if __name__ == "__main__":
    main()
