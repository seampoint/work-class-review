#!/usr/bin/env python3
"""Rebuild the current-pinned prior-binding review packet from the case files on disk.

Every digest is recomputed from the case bytes. The normative sources are derived from
the requirements the cases cite rather than listed by hand. The cross-language fields
are adapter output and are retained under an explicit exception instead of being removed.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
ROOT = CANDIDATE.parents[2]
CONTRACT = ROOT / "library" / "work-class-specification" / "1.0.0-draft.3"
sys.path.insert(0, str(HERE))
from corpus_common import candidate_pin, canonical_bytes, digest, raw_sha256  # noqa: E402


IDENTITY = "seampoint.work-class.prior-binding-runtime-current-review/1.0.0-draft.3/2026-09-11"
GROUP = "cases/prior-binding-runtime"
CASE_IDS = ("D2-277", "D2-278", "D2-281")
INPUT_DOMAIN = "adapter-input"
RESULT_DOMAIN = "adapter-result"

METHOD = {
    "judgment_basis": "Each expected result is derived from the cited normative rule and the complete input before any comparison with implementation output.",
    "canonical_hash": "lowercase SHA-256 of the UTF-8 number-free RFC 8785 canonical serialization of the named JSON value",
    "superseded_predecessor": "PRIOR-BINDING-RUNTIME-JUDGMENT-DELTA-20260911.json binds a superseded pin and is retained as historical provenance. It is not converted into an approval.",
}

CROSS_LANGUAGE_EXCEPTION = (
    "The result_code, result_disposition, result_matches_case_expected, result_status and "
    "typescript_python_exact members are adapter output. Every other review in this directory "
    "excludes adapter output from its scope. They are retained rather than removed by an explicit "
    "decision of the project owner on 2026-09-11, and are recorded here as an author observation. "
    "An independent reviewer must derive each complete result from the cited normative rule and "
    "the exact input without consulting either implementation, and must not treat these members "
    "as evidence for the judgment they describe."
)

SCOPE = {
    "case_ids": list(CASE_IDS),
    "excluded": [
        "implementation source",
        "adapter output",
        "prior review conclusions",
        "batch run reports",
    ],
}

REVIEW_BASIS = {
    "implementation_blind": True,
    "implementation_source_inspected": False,
    "implementation_output_inspected": True,
    "implementation_output_scope": "Recorded as a declared exception in each row's cross_language_observation member. It did not choose any expected classification.",
    "fixture_source_inspected": True,
    "fixture_source_scope": "case construction only, recorded in PRIOR-BINDING-RUNTIME-VECTOR-CONSTRUCTION-20260911.md",
}

LIMIT = (
    "This packet establishes that three corrected prior-binding refusals bind the current pin and "
    "reproduce their own digests. It does not establish that the expected results are correct; that "
    "is what independent review must decide. D2-084 in EXACT-VECTOR-MORNING-BATCH-20260911.json is "
    "sourced from D2-277 and carries the same expected-result digest, so a finding against D2-277 "
    "also lands on D2-084. The two packets are not independent and must be reviewed together or in "
    "a fixed order."
)


def requirements_index() -> dict:
    rows = json.loads((CONTRACT / "requirements.json").read_text())["requirements"]
    return {row["id"]: row for row in rows}


def judgments() -> dict:
    contract = json.loads((HERE / "EXPECTED-JUDGMENTS-CONTRACT.json").read_text())
    return {row["id"]: row for row in contract["judgments"]}


def observation(case_id: str, previous: dict) -> dict:
    """Read the recorded adapter values from either the flat or the nested row shape."""
    row = previous.get(case_id, {})
    row = row.get("cross_language_observation", row)
    return {
        "adapter_command": "node typescript/adapter.ts and python3 python/adapter.py",
        "exception": CROSS_LANGUAGE_EXCEPTION,
        "result_code": row.get("result_code"),
        "result_disposition": row.get("result_disposition"),
        "result_matches_case_expected": row.get("result_matches_case_expected"),
        "result_status": row.get("result_status"),
        "typescript_python_exact": row.get("typescript_python_exact"),
    }


def build() -> dict:
    pin = candidate_pin()
    contract_path = HERE / "EXPECTED-JUDGMENTS-CONTRACT.json"
    contract = judgments()
    requirements = requirements_index()
    packet_path = HERE / "PRIOR-BINDING-RUNTIME-CURRENT-REVIEW-20260911.json"
    previous = {}
    if packet_path.exists():
        previous = {row["case_id"]: row for row in json.loads(packet_path.read_text())["rows"]}

    rows = []
    documents = set()
    for case_id in CASE_IDS:
        relative = f"{GROUP}/{case_id}.json"
        path = CANDIDATE / relative
        if not path.exists():
            raise SystemExit(f"{case_id}: case file absent at {relative}")
        case = json.loads(path.read_text())
        judgment = contract.get(case_id)
        if judgment is None:
            raise SystemExit(f"{case_id}: no frozen judgment in the contract")
        if case["operation"] != judgment["operation"]:
            raise SystemExit(f"{case_id}: operation differs from the judgment")
        if case["requirements"] != judgment["normative_references"]:
            raise SystemExit(f"{case_id}: citations differ from the judgment")
        for requirement in case["requirements"]:
            row = requirements.get(requirement)
            if row is None:
                raise SystemExit(f"{case_id}: cites undefined requirement {requirement}")
            documents.add(row["document"])

        rows.append({
            "case_id": case_id,
            "case_path": relative,
            "case_sha256": raw_sha256(path),
            "cross_language_observation": observation(case_id, previous),
            "derivation": case["derivation"],
            "expected_digest": digest(RESULT_DOMAIN, case["expected"]),
            "expected_judgment": judgment["expected_judgment"],
            "expected_result_sha256": "sha256:" + hashlib.sha256(canonical_bytes(case["expected"])).hexdigest(),
            "input_digest": digest(INPUT_DOMAIN, case["input"]),
            "normative_references": judgment["normative_references"],
            "operation": case["operation"],
            "review_status": "PENDING_INDEPENDENT_REVIEW",
        })

    sources = [{"path": "library/work-class-specification/1.0.0-draft.3/contract-manifest.json",
                "raw_sha256": raw_sha256(CONTRACT / "contract-manifest.json")}]
    for name in sorted(documents) + ["work-class.schema.json", "lifecycle.schema.json", "protocol.schema.json"]:
        sources.append({
            "path": f"library/work-class-specification/1.0.0-draft.3/{name}",
            "raw_sha256": raw_sha256(CONTRACT / name),
        })

    return {
        "candidate_pin": pin,
        "case_count": str(len(rows)),
        "digest_domain": {"expected": RESULT_DOMAIN, "input": INPUT_DOMAIN},
        "expected_judgments_sha256": raw_sha256(contract_path),
        "findings": [],
        "identity": IDENTITY,
        "limit": LIMIT,
        "method": METHOD,
        "normative_sources": sources,
        "review_basis": REVIEW_BASIS,
        "rows": rows,
        "scope": SCOPE,
        "status": "PENDING_INDEPENDENT_REVIEW",
    }


def markdown(packet: dict) -> str:
    lines = [
        "# Current-pinned prior-binding review",
        "",
        f"Identity: `{packet['identity']}`",
        "",
        f"Candidate pin: `{packet['candidate_pin']}`",
        "",
        f"Status: `{packet['status']}`. {packet['case_count']} cases.",
        "",
        "Every digest in this packet is recomputed from the case bytes by",
        "`review/build-prior-binding-current-packet.py`, so a row cannot drift from its case file.",
        "The earlier prior-binding delta binds a superseded pin and is retained as historical",
        "provenance rather than converted into an approval.",
        "",
        "## Cases",
        "",
        "| Case | Expected judgment | Cited rules |",
        "| --- | --- | --- |",
    ]
    for row in packet["rows"]:
        refs = ", ".join(f"`{value}`" for value in row["normative_references"])
        lines.append(f"| `{row['case_id']}` | `{row['expected_judgment']}` | {refs} |")
    lines += [
        "",
        "## Adapter-output exception",
        "",
        "Each row carries a `cross_language_observation` member recording what the two adapters",
        "returned. That is adapter output, which every other review in this directory excludes.",
        "It is retained by an explicit decision of the project owner on 2026-09-11 and marked as an",
        "author observation. It is not evidence for the judgment it describes.",
        "",
        "## Normative sources",
        "",
        "| Document | Raw SHA-256 |",
        "| --- | --- |",
    ]
    for source in packet["normative_sources"]:
        lines.append(f"| `{Path(source['path']).name}` | `{source['raw_sha256']}` |")
    lines += [
        "",
        "## Limit",
        "",
        packet["limit"],
        "",
        "## What independent review must do",
        "",
        "Derive each complete refusal from the cited normative rule and the exact input without",
        "inspecting either implementation or its output. Confirm each refusal returns the supplied",
        "state unchanged and that its state digest recomputes over that state. Reproduce every digest",
        "in the row. Record findings against the scope stated above.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    packet = build()
    (HERE / "PRIOR-BINDING-RUNTIME-CURRENT-REVIEW-20260911.json").write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n"
    )
    (HERE / "PRIOR-BINDING-RUNTIME-CURRENT-REVIEW-20260911.md").write_text(markdown(packet))
    print(json.dumps({
        "status": "WRITTEN",
        "identity": packet["identity"],
        "candidate_pin": packet["candidate_pin"],
        "case_count": packet["case_count"],
        "normative_sources": str(len(packet["normative_sources"])),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
