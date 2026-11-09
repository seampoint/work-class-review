#!/usr/bin/env python3
"""Build static fan-out and maximum-enclosing-depth vectors."""

from __future__ import annotations

import base64
import json

from corpus_common import CASES, canonical_bytes, exact_case, write_canonical_json
from fixture_factory import PIN, structural_step, typed


def completion(fields: list[str], collection: str | None = None, choice: bool = False) -> dict:
    return {
        "terminal_policy": "LEGACY_NONTERMINAL", "effect_provider": "structure-provider",
        "effect_source": "structure-system",
        "effect_record_type": "structure-result",
        "no_effect_provider": "structure-provider",
        "no_effect_source": "structure-system",
        "no_effect_record_type": "structure-no-effect",
        "status_field": "status",
        "status_type_ref": "status",
        "success_values": [typed("status", "SUCCEEDED")],
        "failure_values": [typed("status", "FAILED")],
        "route_label_field": "route" if choice else None,
        "route_label_type_ref": "route" if choice else None,
        "evidence_bindings": [
            {"request_field": name, "evidence_field": name}
            for name in fields
        ],
    }


def operation(step_id: str, fields: list[str], *, kind: str = "OPERATION", choice: bool = False) -> dict:
    declarations = [{"name": name, "type_ref": "identity"} for name in fields]
    scope = fields[0] if fields else "seed-id"
    if not declarations:
        declarations = [{"name": "seed-id", "type_ref": "identity"}]
        fields = ["seed-id"]
    return {
        "id": step_id,
        "kind": kind,
        "quantity_mode": "BOUNDED",
        "exclusive_keys": [],
        "executor_role": "structure-operator",
        "interface": "structure-system",
        "operation": step_id,
        "fields": declarations,
        "scope_fields": {"subjects": [scope], "resources": [scope]},
        "required_credentials": ["structure-credential"],
        "authority_requirements": ["structure-authority"],
        "shared_budgets": [],
        "prior_effect_bindings": [],
        "prior_actor_separations": [],
        "permit_seconds": "300",
        "failure_behavior": "STOP",
        "completion": completion(fields, choice=choice),
    }


def base_definition(steps: list[dict], relationships: list[dict], root: str) -> dict:
    proposal_ids = sorted(
        [step["id"] for step in steps if step["kind"] in {"OPERATION", "FANOUT_EXPAND"}],
        key=lambda value: value.encode("utf-8"),
    )
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/work-class-definition",
        "specification_pin": PIN,
        "id": "structured-depth",
        "revision": "revision-1",
        "profile": "PARALLEL_FANOUT",
        "root": root,
        "participants": [{"id": "structure-operator-1", "role": "structure-operator", "kind": "AGENT"}],
        "objects": [],
        "types": [
            {"id": "identity", "kind": "IDENTITY", "nonnegative": False, "unit": None},
            {"id": "route", "kind": "STRING", "nonnegative": False, "unit": None},
            {"id": "status", "kind": "STRING", "nonnegative": False, "unit": None},
        ],
        "steps": sorted(steps, key=lambda row: row["id"].encode("utf-8")),
        "relationships": relationships,
        "choices": [],
        "occurrence_limits": [{"step_id": step_id, "maximum": "2"} for step_id in proposal_ids],
        "loops": [],
        "deadlines": [],
        "parallel_blocks": [],
        "fanouts": [],
        "shared_budgets": [],
        "limits": {
            "maximum_proposals": "4096",
            "maximum_activations": "4096",
            "maximum_actuations": "4096",
            "maximum_active_obligations": "4096",
            "maximum_fanout_objects": "1024",
        },
        "source": {"id": "structure-policy", "revision": "revision-1", "obligations": ["bounded-structure"]},
    }


def validate_input(definition: dict) -> dict:
    return {
        "kind": "WORK_CLASS",
        "specification_pin": PIN,
        "artifact_bytes_base64": base64.b64encode(canonical_bytes(definition)).decode("ascii"),
    }


def repeated_fanout() -> dict:
    expand = operation("expand", ["seed-id"], kind="FANOUT_EXPAND")
    process = operation("process", ["item-id"])
    steps = [expand, structural_step("join", "FANOUT_JOIN"), process]
    definition = base_definition(
        steps,
        [
            {"kind": "SEQUENCE", "from": "process", "to": "join"},
            {"kind": "SEQUENCE", "from": "join", "to": "expand"},
        ],
        "expand",
    )
    definition["id"] = "repeated-fanout"
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


def nested_same_field() -> dict:
    outer = operation("outer-expand", ["seed-id"], kind="FANOUT_EXPAND")
    inner = operation("inner-expand", ["object-id"], kind="FANOUT_EXPAND")
    process = operation("process", ["object-id"])
    steps = [
        inner,
        structural_step("inner-join", "FANOUT_JOIN"),
        outer,
        structural_step("outer-join", "FANOUT_JOIN"),
        process,
        structural_step("terminal", "TERMINAL"),
    ]
    definition = base_definition(
        steps,
        [
            {"kind": "SEQUENCE", "from": "process", "to": "inner-join"},
            {"kind": "SEQUENCE", "from": "inner-join", "to": "outer-join"},
            {"kind": "SEQUENCE", "from": "outer-join", "to": "terminal"},
        ],
        "outer-expand",
    )
    definition["id"] = "nested-same-field"
    definition["fanouts"] = [
        {
            "id": "inner",
            "expand_step_id": "inner-expand",
            "region_head_step_id": "process",
            "join_step_id": "inner-join",
            "object_field": "inner-items",
            "object_request_field": "object-id",
            "object_type_ref": "identity",
            "empty_set_behavior": "ADVANCE_TO_JOIN",
        },
        {
            "id": "outer",
            "expand_step_id": "outer-expand",
            "region_head_step_id": "inner-expand",
            "join_step_id": "outer-join",
            "object_field": "outer-items",
            "object_request_field": "object-id",
            "object_type_ref": "identity",
            "empty_set_behavior": "ADVANCE_TO_JOIN",
        },
    ]
    return definition


def depth_65() -> dict:
    count = 64
    steps = []
    relationships = []
    fanouts = []
    for index in range(count):
        prefix_fields = [f"object-{field_index:02d}" for field_index in range(index)]
        expand_id = f"expand-{index:02d}"
        join_id = f"join-{index:02d}"
        steps.append(operation(expand_id, prefix_fields, kind="FANOUT_EXPAND"))
        steps.append(structural_step(join_id, "FANOUT_JOIN"))
        fanouts.append(
            {
                "id": f"fanout-{index:02d}",
                "expand_step_id": expand_id,
                "region_head_step_id": f"expand-{index + 1:02d}" if index + 1 < count else "loop-operation",
                "join_step_id": join_id,
                "object_field": f"objects-{index:02d}",
                "object_request_field": f"object-{index:02d}",
                "object_type_ref": "identity",
                "empty_set_behavior": "ADVANCE_TO_JOIN",
            }
        )
        if index > 0:
            relationships.append(
                {"kind": "SEQUENCE", "from": join_id, "to": f"join-{index - 1:02d}"}
            )
    loop_fields = [f"object-{index:02d}" for index in range(count)]
    loop_operation = operation("loop-operation", loop_fields, choice=True)
    steps.extend([loop_operation, structural_step("terminal", "TERMINAL")])
    relationships.extend(
        [
            {"kind": "LABEL", "from": "loop-operation", "to": "loop-operation", "label": typed("route", "CONTINUE")},
            {"kind": "LABEL", "from": "loop-operation", "to": "join-63", "label": typed("route", "DONE")},
            {"kind": "SEQUENCE", "from": "join-00", "to": "terminal"},
        ]
    )
    definition = base_definition(steps, relationships, "expand-00")
    definition["id"] = "enclosing-depth-65"
    definition["choices"] = [
        {
            "step_id": "loop-operation",
            "label_type_ref": "route",
            "label_values": [typed("route", "CONTINUE"), typed("route", "DONE")],
        }
    ]
    definition["loops"] = [
        {
            "id": "inner-loop",
            "entry_step_id": "loop-operation",
            "member_step_ids": ["loop-operation"],
            "back_edge_from_step_id": "loop-operation",
            "maximum_passes": "2",
        }
    ]
    definition["fanouts"] = fanouts
    return definition


def main() -> None:
    cases = [
        exact_case(
            "D2-005",
            "validate",
            validate_input(repeated_fanout()),
            {"status": "REFUSED", "code": "UNSUPPORTED_FEATURE", "path": ""},
            ["FAN-001", "WCS2-004"],
            "The fan-out join routes to the same expand step under the same outer prefix, selecting a repeated expansion pass that the candidate explicitly excludes.",
        ),
        exact_case(
            "D2-167",
            "validate",
            validate_input(depth_65()),
            {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""},
            ["WCD-001", "FAN-001", "COMP-002"],
            "The deepest loop operation is enclosed by 64 nested fan-out object regions and one loop segment. Its construct path has 65 segments, exceeding the static maximum of 64.",
        ),
        exact_case(
            "D2-254",
            "validate",
            validate_input(nested_same_field()),
            {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""},
            ["FAN-001", "WCD-001"],
            "The inner fan-out lies inside the outer object region, but both constructs declare object-id as their object-request field on the descendant path. Nested fan-out identities require distinct field names.",
        ),
    ]
    for case in cases:
        write_canonical_json(CASES / "advanced-static" / f"{case['id']}.json", case)
    print(json.dumps({"candidate_pin": PIN, "case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
