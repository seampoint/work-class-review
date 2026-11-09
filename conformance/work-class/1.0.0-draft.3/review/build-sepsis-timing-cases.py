"""Expose the independently derived successor requests in the common corpus."""

from __future__ import annotations

import json

from corpus_common import CASES, CONFORMANCE, exact_case, write_canonical_json


GROUP = CASES / "sepsis-timing"


def build():
    rows = []
    specimen = CONFORMANCE / "specimens/sepsis-surveillance-timing"
    for suite in ("valid-trace", "scenarios"):
        requests = [json.loads(line) for line in (specimen / suite / "requests.jsonl").read_bytes().splitlines()]
        expected = [json.loads(line) for line in (specimen / suite / "results-derived.jsonl").read_bytes().splitlines()]
        for request, result in zip(requests, expected, strict=True):
            assert request["request_id"] == result["request_id"] and request["operation"] == result["operation"]
            cid = "C3-ST-" + str(len(rows) + 1).zfill(3)
            rows.append(exact_case(cid, request["operation"], request["input"], result["result"],
                ["TIME-001", "TIME-003", "TIME-004", "TIME-005", "TIME-006", "TIME-007", "TIME-008"],
                "Copied without evaluation from the independently constructed sepsis source revision v5, "
                + suite + "/" + request["request_id"] + ". SOURCE-CHOICES.md and DERIVATIONS.md "
                "fix recognition, subject bindings, preactivation duties, possible-send trigger and exact restart judgments. "
                "Source authenticity and the prospective culture-delay exception remain external or uncovered premises."))
    return rows


if __name__ == "__main__":
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print(json.dumps({"sepsis_timing_cases": len(rows), "implementation_or_output_consulted": False}))
