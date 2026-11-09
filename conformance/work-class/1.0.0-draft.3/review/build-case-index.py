#!/usr/bin/env python3
"""Bind every current draft-2 case to one runner target and exact bytes."""

from __future__ import annotations

import json

from corpus_common import CASES, CONFORMANCE, candidate_pin, raw_sha256, write_canonical_json


def target(operation: str, case_id: str) -> str:
    if case_id == "D2-272":
        return "ADAPTER_WITHOUT_RESERVATION_TRANSITIONS"
    if case_id == "C3-HOLD-ROLE-001":
        return "ADAPTER_WITHOUT_HOLDINGS_TRANSITIONS"
    if case_id == "C3-FLOW-ROLE-001":
        return "ADAPTER_WITHOUT_FLOW_TRANSITIONS"
    if operation in {"capabilities", "validate", "evaluate", "aggregate-step", "holdings-step", "flow-step", "deploy", "step", "readback", "check-evidence"}:
        return "ADAPTER"
    if operation == "host-harness":
        return "REFERENCE_HOST"
    if operation in {"property", "validate vectors", "boundary"}:
        return "LOCAL_CONTROL"
    if operation == "transport":
        return "RAW_TRANSPORT"
    raise ValueError(f"unsupported case operation {operation}")


def main() -> None:
    entries = []
    seen = set()
    for path in sorted(CASES.rglob("*.json")):
        if path.name == "index.json":
            continue
        case = json.loads(path.read_text())
        if case["id"] in seen:
            raise ValueError(f"duplicate case id {case['id']}")
        seen.add(case["id"])
        entries.append(
            {
                "id": case["id"],
                "operation": case["operation"],
                "execution_target": target(case["operation"], case["id"]),
                "path": str(path.relative_to(CONFORMANCE)),
                "sha256": raw_sha256(path),
                "requirements": case["requirements"],
            }
        )
    value = {
        "identity": "seampoint.work-class.case-index/1.0.0-draft.3/development",
        "candidate_pin": candidate_pin(),
        "status": "DEVELOPMENT_NOT_QUALIFYING",
        "implementation_or_output_consulted": False,
        "count": str(len(entries)),
        "cases": entries,
    }
    write_canonical_json(CASES / "index.json", value)
    print(json.dumps({"count": value["count"], "candidate_pin": value["candidate_pin"]}, indent=2))


if __name__ == "__main__":
    main()
