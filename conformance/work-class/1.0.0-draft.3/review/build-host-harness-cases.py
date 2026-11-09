#!/usr/bin/env python3
"""Build exact closed host-result cases and host-harness inputs."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, digest, exact_case, write_canonical_json
from fixture_factory import available_clock, deployment, work_class


def host_budget(registry: str, state: str, anchors: list[str]) -> dict:
    return {"registry_digest": registry, "affected_anchors": anchors, "state_digest": state}


def build() -> list[dict]:
    initial_clock = available_clock("work-clock", "1", "2026-09-11T00:00:00Z")
    absolute_definition = work_class(
        "DEADLINES",
        deadline_due={"kind": "ABSOLUTE_INSTANT", "instant": "2026-09-11T01:00:00Z"},
    )
    elapsed_definition = work_class(
        "DEADLINES",
        deadline_due={"kind": "ELAPSED_DURATION", "value": "1", "unit": "HOUR"},
    )
    installed_input, installed_expected = deployment(absolute_definition, initial_clocks=[initial_clock])
    proposed_input, proposed_expected = deployment(elapsed_definition, initial_clocks=[initial_clock])
    before = installed_expected["state_digest"]
    after = digest("work-state", {"host-vector": "after-permit"})
    transaction = digest("lifecycle-transaction", {"host-vector": "permit"})
    registry = digest("reservation-registry", {"host-vector": "payment-registry"})
    budget_before_digest = digest("reservation-state", {"host-vector": "budget-before"})
    budget_after_digest = digest("reservation-state", {"host-vector": "budget-after"})
    budget_before = [host_budget(registry, budget_before_digest, ["payment-cap"])]
    budget_after = [host_budget(registry, budget_after_digest, ["payment-cap"])]

    failure_input = {
        "kind": "COMMIT",
        "transaction_digest": transaction,
        "authoritative_state_digest": before,
        "authoritative_budgets": [],
        "calculated_state_digest": after,
        "calculated_budgets": [],
        "inject_failure": True,
        "failure_reference": "injected-before-swap",
    }
    failure_result = {
        "status": "HOST_COMMIT",
        "disposition": "COMMIT_FAILED",
        "transaction_digest": transaction,
        "state_before_digest": before,
        "authoritative_state_digest": before,
        "budget_before": [],
        "authoritative_budgets": [],
        "failure_reference": "injected-before-swap",
        "dispatch_performed": False,
    }
    cases = [
        exact_case(
            "D2-060",
            "host-harness",
            failure_input,
            failure_result,
            ["LIFE-008", "LIFE-020"],
            "The injected failure occurs before the one authoritative-root swap. LIFE-020 requires the before digest to remain authoritative, no event-log entry, and dispatch_performed false.",
        )
    ]

    success_input = {
        "kind": "COMMIT",
        "transaction_digest": transaction,
        "authoritative_state_digest": before,
        "authoritative_budgets": budget_before,
        "calculated_state_digest": after,
        "calculated_budgets": budget_after,
        "inject_failure": False,
        "failure_reference": None,
    }
    success_result = {
        "status": "HOST_COMMIT",
        "disposition": "COMMITTED",
        "transaction_digest": transaction,
        "state_before_digest": before,
        "state_after_digest": after,
        "budget_before": budget_before,
        "budget_after": budget_after,
        "dispatch_performed": False,
    }
    cases.append(
        exact_case(
            "D2-088",
            "host-harness",
            success_input,
            success_result,
            ["LIFE-008", "LIFE-020"],
            "The serialized host commit binds the transaction and exact before and after work and budget digests. Native dispatch remains a later host action.",
        )
    )

    budget_failure = copy.deepcopy(success_input)
    budget_failure["inject_failure"] = True
    budget_failure["failure_reference"] = "injected-after-calculation"
    budget_failure_result = {
        "status": "HOST_COMMIT",
        "disposition": "COMMIT_FAILED",
        "transaction_digest": transaction,
        "state_before_digest": before,
        "authoritative_state_digest": before,
        "budget_before": budget_before,
        "authoritative_budgets": budget_before,
        "failure_reference": "injected-after-calculation",
        "dispatch_performed": False,
    }
    cases.append(
        exact_case(
            "D2-089",
            "host-harness",
            budget_failure,
            budget_failure_result,
            ["LIFE-008", "LIFE-020"],
            "A deterministic failure after transition calculation but before the immutable-root swap retains the exact authoritative work and budget digests and performs no dispatch.",
        )
    )

    duplicate_install = {
        "kind": "INSTALL",
        "organization": installed_input["deployment_authorization"]["organization_id"],
        "instance_id": installed_input["instance_id"],
        "request": installed_input,
        "calculated": installed_expected,
        "authoritative_request": copy.deepcopy(installed_input),
        "authoritative_result": copy.deepcopy(installed_expected),
    }
    installed_result = {
        "status": "HOST_DEPLOY",
        "disposition": "INSTALLED",
        "organization": duplicate_install["organization"],
        "instance_id": duplicate_install["instance_id"],
        "state_digest": installed_expected["state_digest"],
        "replay": True,
        "dispatch_performed": False,
    }
    cases.append(
        exact_case(
            "D2-264",
            "host-harness",
            duplicate_install,
            installed_result,
            ["LIFE-003", "LIFE-020"],
            "The successful deploy request and calculated initial state are byte-identical to the installed authoritative root. LIFE-020 returns that root as an idempotent replay and creates no second root.",
        )
    )

    occupied_input = {
        "kind": "INSTALL",
        "organization": duplicate_install["organization"],
        "instance_id": duplicate_install["instance_id"],
        "request": proposed_input,
        "calculated": proposed_expected,
        "authoritative_request": installed_input,
        "authoritative_result": installed_expected,
    }
    occupied_result = {
        "status": "HOST_DEPLOY",
        "disposition": "INSTANCE_OCCUPIED",
        "organization": occupied_input["organization"],
        "instance_id": occupied_input["instance_id"],
        "authoritative_state_digest": installed_expected["state_digest"],
        "proposed_state_digest": proposed_expected["state_digest"],
        "replay": False,
        "dispatch_performed": False,
    }
    cases.append(
        exact_case(
            "D2-265",
            "host-harness",
            occupied_input,
            occupied_result,
            ["LIFE-003", "LIFE-020"],
            "The namespace already holds D2-008, while the proposed request and calculated root are D2-138. LIFE-020 returns both state digests, preserves the authoritative root, and performs no dispatch.",
        )
    )
    return cases


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "host-harness" / f"{case['id']}.json", case)
    print(json.dumps({"case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
