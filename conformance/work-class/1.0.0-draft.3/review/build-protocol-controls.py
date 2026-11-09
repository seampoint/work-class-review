#!/usr/bin/env python3
"""Build supplementary protocol capability controls."""

from __future__ import annotations

import json

from corpus_common import CASES, exact_case, write_canonical_json
from fixture_factory import PIN


def build() -> list[dict]:
    return [
        exact_case(
            "P2-001",
            "capabilities",
            {},
            {
                "status": "CAPABILITIES",
                "protocol": "seampoint.work-class.adapter/1.0.0-draft.3",
                "specification_pin": PIN,
                "roles": [
                    "AGGREGATE_EVALUATOR",
                    "AUTHORITY_EVALUATOR",
                    "CHOICE_LOOP_RUNTIME",
                    "DEADLINE_RUNTIME",
                    "FLOW_TRANSITIONS",
                    "HOLDINGS_TRANSITIONS",
                    "LINEAR_WORK_RUNTIME",
                    "PARALLEL_FANOUT_RUNTIME",
                    "REFERENCE_SINGLE_PROCESS_CONTENTION",
                    "RESERVATION_TRANSITIONS",
                    "REVIEW_EVIDENCE",
                ],
                "operations": [
                    "aggregate-step",
                    "capabilities",
                    "check-evidence",
                    "deploy",
                    "evaluate",
                    "flow-step",
                    "holdings-step",
                    "readback",
                    "step",
                    "validate",
                ],
                "tzdb": "2025a",
                "limits": {
                    "max_definitions": "64",
                    "max_operations": "256",
                    "max_collection_members": "1024",
                    "max_numeric_digits": "128",
                    "max_expression_depth": "64",
                    "max_expression_nodes": "4096",
                },
            },
            ["WCS2-004", "WCS2-010", "WCS2-011"],
            "The complete candidate claims all eleven review roles, all ten adapter operations, pinned tzdb 2025a, and the common finite limits. The capability bytes bind the exact candidate pin.",
        )
    ]


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "protocol-controls" / f"{case['id']}.json", case)
    print(json.dumps({"case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
