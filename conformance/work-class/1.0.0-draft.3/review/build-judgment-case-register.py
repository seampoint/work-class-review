#!/usr/bin/env python3
"""Create a complete judgment-to-vector work register without implementations."""

from __future__ import annotations

import json

from corpus_common import CASES, CONFORMANCE, EXPECTED_JUDGMENTS, candidate_pin, raw_sha256, write_canonical_json


def main() -> None:
    contract = json.loads(EXPECTED_JUDGMENTS.read_text())
    vector_paths = {
        path.stem: str(path.relative_to(CONFORMANCE))
        for path in CASES.rglob("D2-*.json")
    }
    rows = []
    for judgment in contract["judgments"]:
        path = vector_paths.get(judgment["id"])
        rows.append(
            {
                "judgment_id": judgment["id"],
                "operation": judgment["operation"],
                "scenario": judgment["scenario"],
                "expected_judgment": judgment["expected_judgment"],
                "normative_references": judgment["normative_references"],
                "case_path": path,
                "case_sha256": raw_sha256(CONFORMANCE / path) if path else None,
                "vector_status": "DERIVED_EXACT_VECTOR_PENDING_INDEPENDENT_REVIEW" if path else "PENDING_EXACT_VECTOR",
            }
        )
    value = {
        "identity": "seampoint.work-class.judgment-case-register/1.0.0-draft.3/development",
        "candidate_identity": contract["candidate_identity"],
        "candidate_pin": candidate_pin(),
        "expected_judgments_sha256": raw_sha256(EXPECTED_JUDGMENTS),
        "status": "DEVELOPMENT_NOT_QUALIFYING",
        "implementation_or_output_consulted": False,
        "counts": {
            "judgments": str(len(rows)),
            "exact_vectors": str(sum(row["case_path"] is not None for row in rows)),
            "pending_vectors": str(sum(row["case_path"] is None for row in rows)),
        },
        "rows": rows,
    }
    path = CONFORMANCE / "review" / "JUDGMENT-CASE-REGISTER.json"
    write_canonical_json(path, value)
    print(json.dumps(value["counts"], indent=2))


if __name__ == "__main__":
    main()
