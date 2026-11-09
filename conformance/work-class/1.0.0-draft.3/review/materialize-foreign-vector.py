#!/usr/bin/env python3
"""Materialize the distinct D2-068 foreign-effect vector."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

from corpus_common import exact_case, write_canonical_json


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cases" / "foreign-effects" / "D2-118.json"
ADAPTER = ROOT / "typescript" / "adapter.ts"
OUT = ROOT / "cases" / "morning-vector-batch" / "D2-068.json"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.3"


def main() -> None:
    source = json.loads(SOURCE.read_text())
    request_input = copy.deepcopy(source["input"])
    event = request_input["event"]
    event["event_id"] = "effect-d2-068"
    evidence = event["native_evidence"]
    evidence["evidence_id"] = "evidence-d2-068"
    evidence["evidence_ref"] = "evidence-ref-d2-068"
    evidence["observed_at"] = "2026-09-10T04:30:02Z"
    evidence["event_time"] = "2026-09-10T04:30:02Z"
    evidence["record_digest"] = "sha256:" + ("068" * 22)[:64]
    request = {"protocol": PROTOCOL, "request_id": "D2-068", "operation": "step", "input": request_input}
    result = json.loads(
        subprocess.run(
            ["node", str(ADAPTER)], input=(json.dumps(request) + "\n").encode(), stdout=subprocess.PIPE, check=True
        ).stdout
    )["result"]
    if result.get("status") != "STEP" or result.get("decision", {}).get("disposition") != "DISPUTED":
        raise RuntimeError(result)
    case = exact_case(
        "D2-068",
        "step",
        request_input,
        result,
        ["LIFE-010"],
        "LIFE-010 retains an attributable foreign effect as visible and disputed. The distinct evidence identity and observation time make this a separate exact vector; the unprojectable shared-budget anchor variant remains pending.",
    )
    write_canonical_json(OUT, case)
    print(json.dumps({"case": str(OUT), "status": "MATERIALIZED", "judgment": "STEP/DISPUTED/FOREIGN"}, indent=2))


if __name__ == "__main__":
    main()
