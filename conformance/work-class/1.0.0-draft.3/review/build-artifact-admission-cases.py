#!/usr/bin/env python3
"""Build exact draft-2 work-class artifact admission vectors.

The accepted fixture and each single-fault mutation are authored from the
closed work-class schema and COMPOSITION.md. No implementation is used.
"""

from __future__ import annotations

import base64
import copy
import json

from corpus_common import CASES, candidate_pin, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import work_class as factory_work_class


PIN = candidate_pin()


def value(type_ref: str, text: str) -> dict:
    return {"type_ref": type_ref, "value": text}


def operation_step() -> dict:
    return {
        "id": "issue-card",
        "kind": "OPERATION",
        "quantity_mode": "BOUNDED",
        "exclusive_keys": [],
        "executor_role": "access-operator",
        "interface": "access-control",
        "operation": "issue-card",
        "fields": [
            {"name": "card-id", "type_ref": "identity"},
            {"name": "employee-id", "type_ref": "identity"},
        ],
        "scope_fields": {"subjects": ["employee-id"], "resources": ["card-id"]},
        "required_credentials": ["access-operator-credential"],
        "authority_requirements": ["access-card-authority"],
        "shared_budgets": [],
        "prior_effect_bindings": [],
        "prior_actor_separations": [],
        "permit_seconds": "300",
        "failure_behavior": "STOP",
        "completion": {
            "terminal_policy": "LEGACY_NONTERMINAL", "effect_provider": "access-provider",
            "effect_source": "access-control",
            "effect_record_type": "card-result",
            "no_effect_provider": "access-provider",
            "no_effect_source": "access-control",
            "no_effect_record_type": "card-no-effect",
            "status_field": "status",
            "status_type_ref": "status",
            "success_values": [value("status", "ISSUED")],
            "failure_values": [value("status", "REJECTED")],
            "route_label_field": None,
            "route_label_type_ref": None,
            "evidence_bindings": [
                {"request_field": "card-id", "evidence_field": "card-id"},
                {"request_field": "employee-id", "evidence_field": "employee-id"},
            ],
        },
    }


def structural_step(step_id: str, kind: str) -> dict:
    return {
        "id": step_id,
        "kind": kind,
        "exclusive_keys": [],
        "executor_role": None,
        "interface": None,
        "operation": None,
        "fields": [],
        "scope_fields": None,
        "required_credentials": [],
        "authority_requirements": [],
        "shared_budgets": [],
        "prior_effect_bindings": [],
        "prior_actor_separations": [],
        "permit_seconds": None,
        "failure_behavior": None,
        "completion": None,
    }


def definition() -> dict:
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/work-class-definition",
        "specification_pin": PIN,
        "id": "access-card",
        "revision": "revision-1",
        "profile": "LINEAR",
        "root": "issue-card",
        "participants": [{"id": "operator-1", "role": "access-operator", "kind": "AGENT"}],
        "objects": [],
        "types": [
            {"id": "identity", "kind": "IDENTITY", "nonnegative": False, "unit": None},
            {"id": "status", "kind": "STRING", "nonnegative": False, "unit": None},
        ],
        "steps": [operation_step(), structural_step("terminal", "TERMINAL")],
        "relationships": [{"kind": "SEQUENCE", "from": "issue-card", "to": "terminal"}],
        "choices": [],
        "occurrence_limits": [{"step_id": "issue-card", "maximum": "1"}],
        "loops": [],
        "deadlines": [],
        "parallel_blocks": [],
        "fanouts": [],
        "shared_budgets": [],
        "limits": {
            "maximum_proposals": "64",
            "maximum_activations": "64",
            "maximum_actuations": "64",
            "maximum_active_obligations": "64",
            "maximum_fanout_objects": "64",
        },
        "source": {
            "id": "access-policy",
            "revision": "revision-1",
            "obligations": ["authorize-card-issuance"],
        },
    }


def artifact_input(raw: bytes) -> dict:
    return {
        "kind": "WORK_CLASS",
        "specification_pin": PIN,
        "artifact_bytes_base64": base64.b64encode(raw).decode("ascii"),
    }


def refused(code: str) -> dict:
    return {"status": "REFUSED", "code": code, "path": ""}


def main() -> None:
    base = definition()
    base_raw = canonical_bytes(base)
    cases = []
    cases.append(
        exact_case(
            "D2-001",
            "validate",
            artifact_input(base_raw),
            {"status": "ACCEPTED", "digest": digest("work-class-definition", base)},
            ["WCS2-001", "WCS2-004"],
            "The bytes are the WCS2-001 canonical serialization of a closed, self-contained LINEAR work class that satisfies the static graph and completion-carrier rules.",
        )
    )

    choice = copy.deepcopy(base)
    choice["profile"] = "CHOICE_LOOPS"
    choice["types"].append({"id": "route", "kind": "STRING", "nonnegative": False, "unit": None})
    choice["steps"][0]["completion"]["route_label_field"] = "route"
    choice["steps"][0]["completion"]["route_label_type_ref"] = "route"
    choice["relationships"] = [
        {"kind": "LABEL", "from": "issue-card", "to": "terminal", "label": value("route", "ALLOW")}
    ]
    choice["choices"] = [
        {
            "step_id": "issue-card",
            "label_type_ref": "route",
            "label_values": [value("route", "ALLOW"), value("route", "DENY")],
        }
    ]
    cases.append(
        exact_case(
            "D2-047",
            "validate",
            artifact_input(canonical_bytes(choice)),
            refused("DEFINITION_INVALID"),
            ["COMP-001", "WCD-001"],
            "The choice declares ALLOW and DENY but contains an exact label relationship only for ALLOW. The closed label domain lacks one target.",
        )
    )

    failure_edge_missing = copy.deepcopy(base)
    failure_edge_missing["steps"][0]["failure_behavior"] = "FAILURE_EDGE"
    cases.append(
        exact_case(
            "D2-111",
            "validate",
            artifact_input(canonical_bytes(failure_edge_missing)),
            refused("DEFINITION_INVALID"),
            ["COMP-001", "WCD-001"],
            "The proposal-capable step changes only its declared failure behavior to FAILURE_EDGE while the definition still contains no FAILURE relationship.",
        )
    )

    deadline = factory_work_class(
        "DEADLINES", deadline_due={"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-12T00:00:00Z"}
    )
    deadline["relationships"] = [row for row in deadline["relationships"] if row["kind"] != "EXPIRY"]
    cases.append(
        exact_case(
            "D2-112",
            "validate",
            artifact_input(canonical_bytes(deadline)),
            refused("DEFINITION_INVALID"),
            ["DEAD-001", "WCD-001"],
            "The deadline keeps a nonnull expiry target, but the otherwise admitted definition removes its one exact EXPIRY relationship.",
        )
    )

    parallel = copy.deepcopy(base)
    parallel["profile"] = "PARALLEL_FANOUT"
    branch_a = copy.deepcopy(parallel["steps"][0])
    branch_a["id"] = "branch-a"
    branch_a["operation"] = "branch-a"
    branch_b = copy.deepcopy(parallel["steps"][0])
    branch_b["id"] = "branch-b"
    branch_b["operation"] = "branch-b"
    parallel["steps"] = [
        branch_a,
        branch_b,
        parallel["steps"][0],
        structural_step("join", "PARALLEL_JOIN"),
        structural_step("split", "PARALLEL_SPLIT"),
        parallel["steps"][1],
    ]
    parallel["relationships"] = [
        {"kind": "SEQUENCE", "from": "issue-card", "to": "split"},
        {"kind": "SEQUENCE", "from": "branch-a", "to": "join"},
        {"kind": "SEQUENCE", "from": "branch-b", "to": "join"},
        {"kind": "SEQUENCE", "from": "join", "to": "terminal"},
    ]
    parallel["occurrence_limits"] = [
        {"step_id": "branch-a", "maximum": "1"},
        {"step_id": "branch-b", "maximum": "1"},
        {"step_id": "issue-card", "maximum": "1"},
    ]
    parallel["parallel_blocks"] = [
        {
            "id": "background-checks",
            "split_step_id": "split",
            "branches": [
                {"id": "identity", "head_step_id": "branch-a"},
                {"id": "training", "head_step_id": "branch-b"},
            ],
            "join_step_id": "join",
        }
    ]
    cases.append(
        exact_case(
            "D2-130",
            "validate",
            artifact_input(canonical_bytes(parallel)),
            {"status": "ACCEPTED", "digest": digest("work-class-definition", parallel)},
            ["PAR-001", "WCD-001"],
            "Each branch head has only its declared implicit split edge. Both branch paths reach the matching join, and the join has one sequence successor.",
        )
    )

    wrong_status_type = copy.deepcopy(base)
    wrong_status_type["steps"][0]["completion"]["success_values"] = [value("identity", "ISSUED")]
    cases.append(
        exact_case(
            "D2-136",
            "validate",
            artifact_input(canonical_bytes(wrong_status_type)),
            refused("DEFINITION_INVALID"),
            ["WCD-001"],
            "The success value names nominal type identity while the completion carrier's status_type_ref remains status.",
        )
    )

    empty_source = copy.deepcopy(base)
    empty_source["source"]["obligations"] = []
    cases.append(
        exact_case(
            "D2-137",
            "validate",
            artifact_input(canonical_bytes(empty_source)),
            refused("SCHEMA_INVALID"),
            ["WCD-001"],
            "The otherwise admitted definition changes only its source obligation inventory to the schema-forbidden empty array.",
        )
    )

    duplicate_deadline = factory_work_class(
        "DEADLINES", deadline_due={"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-12T00:00:00Z"}
    )
    second_deadline = copy.deepcopy(duplicate_deadline["deadlines"][0])
    second_deadline["id"] = "issue-card-deadline-2"
    second_deadline["due"]["instant"] = "2026-09-13T00:00:00Z"
    duplicate_deadline["deadlines"].append(second_deadline)
    duplicate_deadline["relationships"].append(
        {
            "kind": "EXPIRY",
            "from": "issue-card",
            "to": "terminal",
            "deadline_ref": "issue-card-deadline-2",
        }
    )
    cases.append(
        exact_case(
            "D2-140",
            "validate",
            artifact_input(canonical_bytes(duplicate_deadline)),
            refused("DEFINITION_INVALID"),
            ["DEAD-001", "WCD-001"],
            "Two complete deadlines and their exact expiry relationships name the same proposal-capable step. The candidate permits at most one deadline per step.",
        )
    )

    omitted_budget = copy.deepcopy(base)
    omitted_budget["steps"][0]["shared_budgets"] = ["card-issuance-budget"]
    cases.append(
        exact_case(
            "D2-163",
            "validate",
            artifact_input(canonical_bytes(omitted_budget)),
            refused("DEFINITION_INVALID"),
            ["WCD-001", "LIFE-007"],
            "The operation uses card-issuance-budget while the top-level exact shared-budget union remains empty.",
        )
    )

    duplicate_step = copy.deepcopy(base)
    duplicate_step["steps"][1]["id"] = "issue-card"
    cases.append(
        exact_case(
            "D2-164",
            "validate",
            artifact_input(canonical_bytes(duplicate_step)),
            refused("DEFINITION_INVALID"),
            ["WCD-001"],
            "The terminal step reuses the operation step's exact identifier. Definition inventories require unique step identifiers.",
        )
    )

    structural_permit = copy.deepcopy(base)
    structural_permit["steps"][1]["permit_seconds"] = "1"
    cases.append(
        exact_case(
            "D2-205",
            "validate",
            artifact_input(canonical_bytes(structural_permit)),
            refused("DEFINITION_INVALID"),
            ["WCD-001", "WCS2-006"],
            "The terminal structural step changes only permit_seconds from null to a positive value. Structural steps cannot issue permits.",
        )
    )

    missing_triple = copy.deepcopy(base)
    del missing_triple["steps"][0]["completion"]["no_effect_provider"]
    cases.append(
        exact_case(
            "D2-206",
            "validate",
            artifact_input(canonical_bytes(missing_triple)),
            refused("SCHEMA_INVALID"),
            ["WCD-001", "LIFE-015"],
            "The otherwise complete proposal-capable completion carrier omits one member of its required no-effect evidence triple.",
        )
    )

    missing_permit = copy.deepcopy(base)
    del missing_permit["steps"][0]["permit_seconds"]
    cases.append(
        exact_case(
            "D2-259",
            "validate",
            artifact_input(canonical_bytes(missing_permit)),
            refused("SCHEMA_INVALID"),
            ["WCD-001", "WCS2-006"],
            "The proposal-capable step omits the closed schema's required permit_seconds field.",
        )
    )

    zero_permit = copy.deepcopy(base)
    zero_permit["steps"][0]["permit_seconds"] = "0"
    cases.append(
        exact_case(
            "D2-260",
            "validate",
            artifact_input(canonical_bytes(zero_permit)),
            refused("SCHEMA_INVALID"),
            ["WCD-001", "WCS2-006"],
            "The proposal-capable step supplies zero where the closed schema requires a positive natural permit duration.",
        )
    )

    duplicate_raw = base_raw.replace(
        b'"id":"access-card"', b'"id":"access-card","id":"access-card"', 1
    )
    cases.append(
        exact_case(
            "D2-002",
            "validate",
            artifact_input(duplicate_raw),
            refused("ARTIFACT_ENCODING_INVALID"),
            ["WCS2-001"],
            "The accepted D2-001 bytes are changed only by repeating the top-level id key. Duplicate-key detection precedes map construction.",
        )
    )

    number_raw = base_raw.replace(b'"maximum_proposals":"64"', b'"maximum_proposals":64', 1)
    cases.append(
        exact_case(
            "D2-003",
            "validate",
            artifact_input(number_raw),
            refused("ARTIFACT_NONCANONICAL"),
            ["WCS2-001"],
            "The accepted D2-001 bytes are changed only by replacing one natural-integer string with a JSON number token, which WCS2-001 forbids before schema interpretation.",
        )
    )

    dynamic = copy.deepcopy(base)
    dynamic["dynamic_fanout"] = {"source": "ambient"}
    cases.append(
        exact_case(
            "D2-004",
            "validate",
            artifact_input(canonical_bytes(dynamic)),
            refused("SCHEMA_INVALID"),
            ["WCS2-004", "FAN-001"],
            "The D2-001 definition gains one undeclared dynamic fan-out property. The closed work-class schema rejects it before semantic graph evaluation.",
        )
    )

    nested_extra = copy.deepcopy(base)
    nested_extra["participants"][0]["display_name"] = "Operator"
    cases.append(
        exact_case(
            "D2-006",
            "validate",
            artifact_input(canonical_bytes(nested_extra)),
            refused("SCHEMA_INVALID"),
            ["WCS2-001", "WCS2-004"],
            "The D2-001 definition gains one undeclared property in a nested participant record. Every public object is closed.",
        )
    )

    unknown_ref = copy.deepcopy(base)
    unknown_ref["steps"][0]["fields"][0]["type_ref"] = "undeclared-type"
    cases.append(
        exact_case(
            "D2-007",
            "validate",
            artifact_input(canonical_bytes(unknown_ref)),
            refused("REFERENCE_INVALID"),
            ["WCS2-010", "WCS2-012"],
            "The D2-001 definition changes only one field type reference to an identifier absent from the definition's closed type inventory. No external lookup is permitted.",
        )
    )

    for case in cases:
        write_canonical_json(CASES / "artifact-admission" / f"{case['id']}.json", case)
    print(json.dumps({"candidate_pin": PIN, "case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
