#!/usr/bin/env python3
"""Materialize D2-036 after its judgment has been independently derived.

The first request is the admitted D2-099 no-effect transition. The second
request is built from that returned state and is expected to be
STEP/DISPUTED/LATE_AFTER_RELEASE. Adapter output supplies only the complete
canonical result envelope; it does not choose the expected classification.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

from corpus_common import exact_case, write_canonical_json


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cases" / "failure-no-effect" / "D2-099.json"
ADAPTER = ROOT / "typescript" / "adapter.ts"
OUT = ROOT / "cases" / "morning-vector-batch" / "D2-036.json"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.3"


def invoke(request: dict) -> dict:
    completed = subprocess.run(
        ["node", str(ADAPTER)],
        input=(json.dumps(request) + "\n").encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    response = json.loads(completed.stdout)
    if response["result"].get("status") != "STEP":
        raise RuntimeError(response)
    return response["result"]


def main() -> None:
    source = json.loads(SOURCE.read_text())
    first_request = {"protocol": PROTOCOL, "request_id": "D2-099", "operation": "step", "input": source["input"]}
    first = invoke(first_request)

    request_input = copy.deepcopy(source["input"])
    request_input["state"] = first["state"]
    request_input["state_digest"] = first["state_digest"]
    event = request_input["event"]
    event["event_id"] = "effect-d2-036"
    event["expected_state_revision"] = first["state"]["revision"]
    event["expected_state_digest"] = first["state_digest"]
    evidence = event["native_evidence"]
    evidence.update(
        {
            "evidence_id": "evidence-d2-036",
            "evidence_ref": "evidence-ref-evidence-d2-036",
            "status": "EFFECT_ESTABLISHED",
            "record_type": "card-result",
            "event_time": "2026-09-10T04:30:00Z",
            "observed_at": "2026-09-10T04:31:00Z",
            "actual_fields": copy.deepcopy(evidence["attributed_request"]["fields"]),
            "rules_out_past_and_future_effects": False,
        }
    )
    request = {"protocol": PROTOCOL, "request_id": "D2-036", "operation": "step", "input": request_input}
    expected = invoke(request)
    if expected["decision"]["disposition"] != "DISPUTED" or "LATE_EFFECT_AFTER_RELEASE" not in expected["decision"]["reason_codes"]:
        raise RuntimeError({"unexpected_late_effect_result": expected})
    case = exact_case(
        "D2-036",
        "step",
        request_input,
        expected,
        ["LIFE-012"],
        "LIFE-012 requires a later conclusive effect with the same native operation, permit and dispatch attempt to remain disputed after an earlier no-effect conclusion. The first transition is D2-099; the second request is the late effect.",
    )
    write_canonical_json(OUT, case)
    print(json.dumps({"case": str(OUT), "status": "MATERIALIZED", "judgment": "STEP/DISPUTED/LATE_AFTER_RELEASE"}, indent=2))


if __name__ == "__main__":
    main()
