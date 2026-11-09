#!/usr/bin/env python3
"""Bind the first high-risk lifecycle vector closure batch for review."""

from __future__ import annotations

import json
from pathlib import Path

from corpus_common import CONFORMANCE, EXPECTED_JUDGMENTS, candidate_pin, digest, raw_sha256, write_canonical_json


PIN = "sha256:fb5217778257b5be25ee09a63cfa30e4874dfec4fd49775709e34d961504a130"
EXPECTED_CONTRACT_SHA256 = "ab05c10a2be0d547dcdd55c386824ed946c29c57ca6b66a51134612a9152d526"
CASE_PATHS = {
    "D2-200": "cases/nested-parallel-closure/D2-200.json",
    "D2-243": "cases/nested-parallel-closure/D2-243.json",
    "D2-244": "cases/nested-parallel-closure/D2-244.json",
    "D2-245": "cases/nested-parallel-closure/D2-245.json",
    "D2-246": "cases/nested-parallel-closure/D2-246.json",
    "D2-249": "cases/nested-parallel-closure/D2-249.json",
    "D2-253": "cases/nested-fanout-binding/D2-253.json",
    "D2-255": "cases/nested-parallel-closure/D2-255.json",
    "D2-288": "cases/prior-binding-restart/D2-288.json",
    "D2-289": "cases/prior-binding-restart/D2-289.json",
    "D2-291": "cases/prior-binding-restart/D2-291.json",
    "D2-295": "cases/prior-binding-restart/D2-295.json",
}
BUILDERS = [
    "review/build-nested-parallel-closure-cases.py",
    "review/build-nested-fanout-binding-case.py",
    "review/build-prior-binding-restart-cases.py",
]
RUNNER_INDEX = CONFORMANCE / "runner" / "exact-vector-closure-batch-1.json"
REVIEW_PACKET = CONFORMANCE / "review" / "EXACT-VECTOR-CLOSURE-BATCH-1-REVIEW.json"
REVIEW_GUIDE = CONFORMANCE / "review" / "EXACT-VECTOR-CLOSURE-BATCH-1-REVIEW.md"


def main() -> None:
    if candidate_pin() != PIN:
        raise ValueError(f"candidate pin changed: {candidate_pin()}")
    if raw_sha256(EXPECTED_JUDGMENTS) != EXPECTED_CONTRACT_SHA256:
        raise ValueError(f"expected-judgment contract changed: {raw_sha256(EXPECTED_JUDGMENTS)}")

    contract = json.loads(EXPECTED_JUDGMENTS.read_text())
    judgments = {row["id"]: row for row in contract["judgments"]}
    rows = []
    for case_id, relative in CASE_PATHS.items():
        path = CONFORMANCE / relative
        case = json.loads(path.read_text())
        judgment = judgments[case_id]
        if case["id"] != case_id:
            raise ValueError(f"case identity mismatch in {relative}")
        if case["operation"] != judgment["operation"]:
            raise ValueError(f"operation mismatch for {case_id}")
        if case["requirements"] != judgment["normative_references"]:
            raise ValueError(f"requirement mismatch for {case_id}")
        rows.append(
            {
                "case_id": case_id,
                "operation": case["operation"],
                "execution_target": "ADAPTER",
                "case_path": relative,
                "case_sha256": raw_sha256(path),
                "input_digest": digest("expectation-review-input", case["input"]),
                "expected_digest": digest("expectation-review-expected", case["expected"]),
                "expected_judgment": judgment["expected_judgment"],
                "scenario": judgment["scenario"],
                "state_and_budget_consequence": judgment["state_and_budget_consequence"],
                "normative_references": judgment["normative_references"],
                "derivation": case["derivation"],
                "review_status": "PENDING_INDEPENDENT_DERIVATION",
            }
        )

    builder_rows = [
        {"path": relative, "sha256": raw_sha256(CONFORMANCE / relative)}
        for relative in BUILDERS
    ]
    runner = {
        "identity": "seampoint.work-class.exact-vector-closure-batch/1.0.0-draft.3/1",
        "candidate_pin": PIN,
        "expected_judgments_sha256": EXPECTED_CONTRACT_SHA256,
        "status": "DEVELOPMENT_EXPECTATIONS_PENDING_INDEPENDENT_REVIEW",
        "implementation_source_or_output_consulted": False,
        "count": str(len(rows)),
        "cases": [
            {
                "id": row["case_id"],
                "operation": row["operation"],
                "execution_target": row["execution_target"],
                "path": row["case_path"],
                "sha256": row["case_sha256"],
                "requirements": row["normative_references"],
            }
            for row in rows
        ],
    }
    write_canonical_json(RUNNER_INDEX, runner)

    packet = {
        "identity": "seampoint.work-class.expectation-review-packet/1.0.0-draft.3/exact-vector-closure-batch-1",
        "candidate_pin": PIN,
        "expected_judgments_sha256": EXPECTED_CONTRACT_SHA256,
        "runner_metadata_path": str(RUNNER_INDEX.relative_to(CONFORMANCE)),
        "runner_metadata_sha256": raw_sha256(RUNNER_INDEX),
        "status": "PENDING_INDEPENDENT_REVIEW",
        "implementation_source_or_output_included": False,
        "builders": builder_rows,
        "method": [
            "Use each exact case input as the complete specimen and the cited draft-2 requirements as authority.",
            "Derive the complete expected adapter result without consulting an implementation or implementation output.",
            "Record the derivation before comparing it with the proposed expected bytes.",
            "Report PASS or a concrete finding for every row; the reviewed judgment label does not approve its exact vector.",
        ],
        "counts": {
            "cases": str(len(rows)),
            "pending_independent_derivations": str(len(rows)),
            "adapter_outputs_consulted": "0",
        },
        "rows": rows,
    }
    write_canonical_json(REVIEW_PACKET, packet)

    lines = [
        "# Exact-vector closure batch 1 review",
        "",
        f"Candidate pin: `{PIN}`",
        "",
        f"Expected-judgment contract SHA-256: `{EXPECTED_CONTRACT_SHA256}`",
        "",
        "Status: `PENDING_INDEPENDENT_REVIEW`",
        "",
        "This packet contains twelve complete adapter inputs and proposed exact results for the highest-risk pending lifecycle judgments. The builders used only the normative draft-2 contract and the repository's fixture-construction helpers. They did not inspect either implementation, adapter output, or runner report.",
        "",
        "For each row, derive the complete result from the cited rules before opening the case's `expected` member. Record `PASS` or a concrete finding. A judgment label previously reviewed at scenario level does not approve these exact bytes.",
        "",
        "| Case | Judgment | Requirements | Case SHA-256 |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['case_id']}` | `{row['expected_judgment']}` | "
            f"{', '.join(f'`{value}`' for value in row['normative_references'])} | `{row['case_sha256']}` |"
        )
    lines.extend(
        [
            "",
            "The JSON packet binds each case path, complete case hash, input digest, expected-result digest, scenario, derivation, and current review status. The batch-local runner metadata is developmental and does not change the shared case index, judgment register, suite identity, or contract manifest.",
            "",
        ]
    )
    REVIEW_GUIDE.write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "cases": len(rows),
                "runner_metadata": str(RUNNER_INDEX.relative_to(CONFORMANCE)),
                "review_packet": str(REVIEW_PACKET.relative_to(CONFORMANCE)),
                "review_guide": str(REVIEW_GUIDE.relative_to(CONFORMANCE)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
