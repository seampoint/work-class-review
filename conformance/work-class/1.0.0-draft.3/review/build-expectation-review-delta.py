#!/usr/bin/env python3
"""Build the exact-vector delta since the first independent expectation review."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from corpus_common import CONFORMANCE, write_canonical_json


REVIEW = CONFORMANCE / "review"


def raw_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    prior_path = REVIEW / "EXPECTATION-REVIEW-1.json"
    packet_path = REVIEW / "EXPECTATION-REVIEW-PACKET-1.json"
    index_path = CONFORMANCE / "cases" / "index.json"
    prior = json.loads(prior_path.read_text())
    packet = json.loads(packet_path.read_text())
    index = json.loads(index_path.read_text())
    approved = {
        row["case_id"]: row["case_sha256"]
        for row in prior["rows"]
        if row["review_status"] == "PASS"
    }
    current_hashes = {row["id"]: row["sha256"] for row in index["cases"]}
    delta_ids = {
        case_id
        for case_id, case_hash in current_hashes.items()
        if approved.get(case_id) != case_hash
    }
    rows = [row for row in packet["rows"] if row["case_id"] in delta_ids]
    rows.sort(key=lambda row: (row["case_path"].encode("utf-8"), row["case_id"].encode("utf-8")))
    groups = Counter(Path(row["case_path"]).parts[1] for row in rows)
    value = {
        "identity": "seampoint.work-class.expectation-review-delta/1.0.0-draft.3/2",
        "status": "PENDING_INDEPENDENT_DERIVATION",
        "candidate_pin": packet["candidate_pin"],
        "expected_judgments_sha256": packet["expected_judgments_sha256"],
        "implementation_source_or_output_included": False,
        "basis": {
            "prior_review_path": "review/EXPECTATION-REVIEW-1.json",
            "prior_review_sha256": raw_hash(prior_path),
            "current_packet_path": "review/EXPECTATION-REVIEW-PACKET-1.json",
            "current_packet_sha256": raw_hash(packet_path),
            "current_index_path": "cases/index.json",
            "current_index_sha256": raw_hash(index_path),
        },
        "counts": {
            "rows": str(len(rows)),
            "new_or_changed_contract_vectors": str(sum(1 for row in rows if row["judgment_contract_case"])),
            "new_or_changed_supplementary_vectors": str(sum(1 for row in rows if not row["judgment_contract_case"])),
            "by_case_group": {key: str(groups[key]) for key in sorted(groups, key=lambda value: value.encode("utf-8"))},
        },
        "method": packet["method"],
        "rows": rows,
    }
    output = REVIEW / "EXPECTATION-REVIEW-DELTA-2.json"
    write_canonical_json(output, value)
    print(json.dumps({"output": str(output.relative_to(CONFORMANCE)), "counts": value["counts"]}, indent=2))


if __name__ == "__main__":
    main()
