#!/usr/bin/env python3
"""Build static prior-effect and actor-separation definition vectors."""

from __future__ import annotations

import base64
import copy
import json

from corpus_common import CASES, canonical_bytes, exact_case, write_canonical_json
from fixture_factory import PIN, structural_step, typed


def completion() -> dict:
    return {
        "terminal_policy": "LEGACY_NONTERMINAL", "effect_provider": "payment-provider",
        "effect_source": "payment-system",
        "effect_record_type": "operation-result",
        "no_effect_provider": "payment-provider",
        "no_effect_source": "payment-system",
        "no_effect_record_type": "operation-no-effect",
        "status_field": "status",
        "status_type_ref": "status",
        "success_values": [typed("status", "SUCCEEDED")],
        "failure_values": [typed("status", "FAILED")],
        "route_label_field": None,
        "route_label_type_ref": None,
        "evidence_bindings": [
            {"request_field": "destination-account", "evidence_field": "destination-account"},
            {"request_field": "supplier-id", "evidence_field": "supplier-id"},
        ],
    }


def operation(step_id: str, role: str, authority: str) -> dict:
    return {
        "id": step_id,
        "kind": "OPERATION",
        "quantity_mode": "BOUNDED",
        "exclusive_keys": [],
        "executor_role": role,
        "interface": "payment-system",
        "operation": step_id,
        "fields": [
            {"name": "destination-account", "type_ref": "identity"},
            {"name": "supplier-id", "type_ref": "identity"},
        ],
        "scope_fields": {"subjects": ["supplier-id"], "resources": ["destination-account"]},
        "required_credentials": [role + "-credential"],
        "authority_requirements": [authority],
        "shared_budgets": [],
        "prior_effect_bindings": [],
        "prior_actor_separations": [],
        "permit_seconds": "300",
        "failure_behavior": "STOP",
        "completion": completion(),
    }


def definition() -> dict:
    confirm = operation("confirm-destination", "confirmation-operator", "confirmation-authority")
    payment = operation("pay-invoice", "payment-operator", "payment-authority")
    payment["prior_effect_bindings"] = [
        {
            "id": "confirmed-destination",
            "selection": "UNIQUE_COMPLETED_ANCESTOR",
            "source_step_id": "confirm-destination",
            "source_evidence_field": "destination-account",
            "target_request_field": "destination-account",
        }
    ]
    payment["prior_actor_separations"] = [
        {
            "id": "confirmation-payment-separation",
            "relation": "DISTINCT_ACTOR",
            "selection": "UNIQUE_COMPLETED_ANCESTOR",
            "prior_step_id": "confirm-destination",
            "prior_act_kind": "VERIFY",
            "current_act_kind": "INSTANCE_DECISION",
        }
    ]
    return {
        "schema": "seampoint.work-class/1.0.0-draft.3/work-class-definition",
        "specification_pin": PIN,
        "id": "supplier-payment",
        "revision": "revision-1",
        "profile": "LINEAR",
        "root": "confirm-destination",
        "participants": [
            {"id": "confirmation-operator-1", "role": "confirmation-operator", "kind": "PERSON"},
            {"id": "payment-operator-1", "role": "payment-operator", "kind": "PERSON"},
        ],
        "objects": [],
        "types": [
            {"id": "identity", "kind": "IDENTITY", "nonnegative": False, "unit": None},
            {"id": "status", "kind": "STRING", "nonnegative": False, "unit": None},
        ],
        "steps": [confirm, payment, structural_step("terminal", "TERMINAL")],
        "relationships": [
            {"kind": "SEQUENCE", "from": "confirm-destination", "to": "pay-invoice"},
            {"kind": "SEQUENCE", "from": "pay-invoice", "to": "terminal"},
        ],
        "choices": [],
        "occurrence_limits": [
            {"step_id": "confirm-destination", "maximum": "1"},
            {"step_id": "pay-invoice", "maximum": "1"},
        ],
        "loops": [],
        "deadlines": [],
        "parallel_blocks": [],
        "fanouts": [],
        "shared_budgets": [],
        "limits": {
            "maximum_proposals": "16",
            "maximum_activations": "16",
            "maximum_actuations": "16",
            "maximum_active_obligations": "16",
            "maximum_fanout_objects": "16",
        },
        "source": {
            "id": "supplier-payment-policy",
            "revision": "revision-1",
            "obligations": ["confirm-destination", "separate-confirmation-and-payment"],
        },
    }


def validate_input(definition_value: dict) -> dict:
    return {
        "kind": "WORK_CLASS",
        "specification_pin": PIN,
        "artifact_bytes_base64": base64.b64encode(canonical_bytes(definition_value)).decode("ascii"),
    }


def refusal(code: str) -> dict[str, str]:
    return {"status": "REFUSED", "code": code, "path": ""}


def build() -> list[dict]:
    base = definition()
    missing = copy.deepcopy(base)
    del missing["steps"][0]["prior_effect_bindings"]
    cases = [
        exact_case(
            "D2-273",
            "validate",
            validate_input(missing),
            refusal("SCHEMA_INVALID"),
            ["WCD-001"],
            "The otherwise complete proposal-capable confirmation step omits the required closed prior_effect_bindings array. Schema admission fails before semantic checks.",
        )
    ]
    unknown = copy.deepcopy(base)
    unknown["steps"][1]["prior_effect_bindings"][0]["source_evidence_field"] = "unknown-field"
    cases.append(
        exact_case(
            "D2-274",
            "validate",
            validate_input(unknown),
            refusal("REFERENCE_INVALID"),
            ["WCD-001", "LIFE-007"],
            "The source step and binding are structurally admitted, but unknown-field is absent from the source completion carrier's closed evidence field inventory.",
        )
    )
    nominal = copy.deepcopy(base)
    nominal["steps"][0]["fields"][0]["type_ref"] = "status"
    nominal["steps"][0]["completion"]["evidence_bindings"][0] = {
        "request_field": "destination-account",
        "evidence_field": "destination-account",
    }
    cases.append(
        exact_case(
            "D2-275",
            "validate",
            validate_input(nominal),
            refusal("DEFINITION_INVALID"),
            ["WCD-001", "LIFE-007"],
            "The declared source evidence field inherits nominal type status while the target request field remains identity. Prior-effect bindings require equal nominal type references.",
        )
    )
    structural = copy.deepcopy(base)
    structural["steps"][2]["prior_actor_separations"] = [
        copy.deepcopy(base["steps"][1]["prior_actor_separations"][0])
    ]
    cases.append(
        exact_case(
            "D2-276",
            "validate",
            validate_input(structural),
            refusal("DEFINITION_INVALID"),
            ["WCD-001"],
            "The terminal step carries a nonempty prior-actor array. Structural steps cannot propose work and therefore require both prior-binding arrays to be empty.",
        )
    )
    return cases


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "prior-binding-static" / f"{case['id']}.json", case)
    print(json.dumps({"candidate_pin": PIN, "case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
