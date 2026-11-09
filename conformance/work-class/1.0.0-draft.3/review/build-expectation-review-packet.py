#!/usr/bin/env python3
"""Bind the current exact vectors for independent expectation review."""

from __future__ import annotations

import json

from corpus_common import CASES, CONFORMANCE, EXPECTED_JUDGMENTS, candidate_pin, digest, raw_sha256, write_canonical_json


OUTPUT = CONFORMANCE / "review" / "EXPECTATION-REVIEW-PACKET-1.json"


def main() -> None:
    contract = json.loads(EXPECTED_JUDGMENTS.read_text())
    judgments = {row["id"]: row for row in contract["judgments"]}
    rows = []
    for path in sorted(CASES.rglob("*.json")):
        if path.name == "index.json":
            continue
        case = json.loads(path.read_text())
        judgment = judgments.get(case["id"])
        rows.append(
            {
                "case_id": case["id"],
                "operation": case["operation"],
                "judgment_contract_case": judgment is not None,
                "scenario": judgment["scenario"] if judgment else case["derivation"],
                "proposed_judgment": judgment["expected_judgment"] if judgment else "EXACT_EXPECTED_VALUE_IN_BOUND_CASE",
                "proposed_state_and_budget_consequence": judgment["state_and_budget_consequence"] if judgment else None,
                "normative_references": case["requirements"],
                "case_path": str(path.relative_to(CONFORMANCE)),
                "case_sha256": raw_sha256(path),
                "input_digest": digest("expectation-review-input", case["input"]),
                "expected_digest": digest("expectation-review-expected", case["expected"]),
                "derivation": case["derivation"],
                "review_status": "PENDING_INDEPENDENT_DERIVATION",
            }
        )
    value = {
        "identity": "seampoint.work-class.expectation-review-packet/1.0.0-draft.3/1",
        "candidate_pin": candidate_pin(),
        "expected_judgments_sha256": raw_sha256(EXPECTED_JUDGMENTS),
        "status": "PENDING_INDEPENDENT_REVIEW",
        "implementation_source_or_output_included": False,
        "method": [
            "Open the exact case_path and use its input as the complete specimen.",
            "Derive the expected result from normative_references without implementation output.",
            "Compare canonical expected bytes only after recording the independent derivation.",
            "Record PASS or a concrete finding for every row; a judgment-contract label does not approve its exact vector.",
        ],
        "counts": {
            "all_cases": str(len(rows)),
            "judgment_contract_cases": str(sum(row["judgment_contract_case"] for row in rows)),
            "supplementary_cases": str(sum(not row["judgment_contract_case"] for row in rows)),
        },
        "rows": rows,
    }
    write_canonical_json(OUTPUT, value)
    print(json.dumps({"output": str(OUTPUT.relative_to(CONFORMANCE)), **value["counts"]}, indent=2))


if __name__ == "__main__":
    main()
