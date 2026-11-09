#!/usr/bin/env python3
"""Build supplementary static controls for structured graph and fan-out bindings."""

from __future__ import annotations

import json
from pathlib import Path
import runpy

from corpus_common import CASES, exact_case, write_canonical_json
from fixture_factory import structural_step


ADVANCED = runpy.run_path(str(Path(__file__).with_name("build-advanced-static-cases.py")))
base_definition = ADVANCED["base_definition"]
operation = ADVANCED["operation"]
validate_input = ADVANCED["validate_input"]


GROUP = CASES / "structured-static"


def cross_branch_definition() -> dict:
    steps = [
        operation("branch-a", ["item-id"]),
        operation("branch-b", ["item-id"]),
        operation("root", ["seed-id"]),
        structural_step("join", "PARALLEL_JOIN"),
        structural_step("split", "PARALLEL_SPLIT"),
        structural_step("terminal", "TERMINAL"),
    ]
    definition = base_definition(
        steps,
        [
            {"kind": "SEQUENCE", "from": "root", "to": "split"},
            {"kind": "SEQUENCE", "from": "branch-a", "to": "branch-b"},
            {"kind": "SEQUENCE", "from": "branch-b", "to": "join"},
            {"kind": "SEQUENCE", "from": "join", "to": "terminal"},
        ],
        "root",
    )
    definition["id"] = "cross-branch-entry"
    definition["parallel_blocks"] = [
        {
            "id": "parallel-1",
            "split_step_id": "split",
            "branches": [
                {"id": "a", "head_step_id": "branch-a"},
                {"id": "b", "head_step_id": "branch-b"},
            ],
            "join_step_id": "join",
        }
    ]
    return definition


def fanout_definition(*, missing_field: bool = False, wrong_type: bool = False) -> dict:
    expand = operation("expand", ["seed-id"], kind="FANOUT_EXPAND")
    fields = ["other-id"] if missing_field else ["item-id"]
    process = operation("process", fields)
    if wrong_type:
        process["fields"][0]["type_ref"] = "route"
    definition = base_definition(
        [expand, process, structural_step("join", "FANOUT_JOIN"), structural_step("terminal", "TERMINAL")],
        [
            {"kind": "SEQUENCE", "from": "process", "to": "join"},
            {"kind": "SEQUENCE", "from": "join", "to": "terminal"},
        ],
        "expand",
    )
    definition["id"] = "fanout-field-missing" if missing_field else "fanout-field-wrong-type"
    definition["fanouts"] = [
        {
            "id": "items",
            "expand_step_id": "expand",
            "region_head_step_id": "process",
            "join_step_id": "join",
            "object_field": "items",
            "object_request_field": "item-id",
            "object_type_ref": "identity",
            "empty_set_behavior": "ADVANCE_TO_JOIN",
        }
    ]
    return definition


def main() -> None:
    cases = [
        exact_case(
            "C2-static-cross-branch",
            "validate",
            validate_input(cross_branch_definition()),
            {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""},
            ["WCD-001", "PAR-001"],
            "branch-a routes directly into sibling branch-b. A sibling branch head may have only its block's implicit incoming edge, and a branch cannot enter another branch before its join, so the graph is statically invalid.",
        ),
        exact_case(
            "C2-static-fanout-field-missing",
            "validate",
            validate_input(fanout_definition(missing_field=True)),
            {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""},
            ["WCD-001", "FAN-001"],
            "The fan-out declares item-id as its object-request field, but its proposal-capable region head has only other-id. Static admission rejects a fan-out region that cannot bind each object occurrence to the exact native request field.",
        ),
        exact_case(
            "C2-static-fanout-field-type",
            "validate",
            validate_input(fanout_definition(wrong_type=True)),
            {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""},
            ["WCD-001", "FAN-001"],
            "The region head declares item-id with nominal type route while the fan-out declares object type identity. Static admission rejects the unequal object-request field type before any expansion can occur.",
        ),
    ]
    for case in cases:
        write_canonical_json(GROUP / f"{case['id']}.json", case)
    print(json.dumps({"case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
