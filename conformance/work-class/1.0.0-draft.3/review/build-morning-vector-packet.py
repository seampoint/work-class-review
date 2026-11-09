#!/usr/bin/env python3
"""Rebuild the morning exact-vector review packet from the case files on disk.

Every digest is recomputed from the case bytes, so the packet cannot drift from
the corpus it describes. Rows materialized with adapter output carry an explicit
exception record naming the producer and the limit of its check.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
sys.path.insert(0, str(HERE))
from corpus_common import candidate_pin, canonical_bytes, digest, raw_sha256  # noqa: E402


IDENTITY = "seampoint.work-class.exact-vector-morning-batch/1.0.0-draft.3/2026-09-11"
GROUP = "cases/morning-vector-batch"
INPUT_DOMAIN = "adapter-input"
RESULT_DOMAIN = "adapter-result"

METHOD = [
    "Derive each expected judgment from the cited normative rule and complete input before comparing implementation output.",
    "Use adapter output only to materialize and cross-check complete canonical result bytes. Every row produced that way carries an explicit materialization exception.",
    "Reuse an admitted fixture only where the derivation states the remaining scenario limitation explicitly.",
]

DERIVED = {
    "method": "DERIVED_FROM_ADMITTED_FIXTURE",
    "producer": "review/build-morning-vector-batch.py",
    "adapter_output_consulted": False,
}

ADAPTER_EXCEPTION = (
    "The complete canonical result bytes were produced by invoking node typescript/adapter.ts. "
    "This departs from the zero-adapter derivation standard recorded in "
    "EXACT-VECTOR-CLOSURE-BATCH-1-REVIEW.json, which declares adapter_outputs_consulted 0. "
    "The exception is recorded rather than removed by an explicit decision of the project owner "
    "on 2026-09-11. An independent reviewer must derive the complete result from the cited "
    "normative rule and the exact input without consulting either implementation, and must treat "
    "the stored expected bytes as an author assertion until that derivation agrees."
)

MATERIALIZED = {
    "D2-036": {
        "method": "ADAPTER_MATERIALIZED",
        "producer": "review/materialize-late-effect-vector.py",
        "adapter_output_consulted": True,
        "adapter_command": "node typescript/adapter.ts",
        "producer_check": "The producer asserts status STEP on both the seeding D2-099 transition and the late-effect transition. It does not verify the DISPUTED disposition or the LATE_AFTER_RELEASE classification.",
        "exception": ADAPTER_EXCEPTION,
    },
    "D2-068": {
        "method": "ADAPTER_MATERIALIZED",
        "producer": "review/materialize-foreign-vector.py",
        "adapter_output_consulted": True,
        "adapter_command": "node typescript/adapter.ts",
        "producer_check": "The producer asserts status STEP and decision disposition DISPUTED. It does not verify the FOREIGN classification or any state or digest member.",
        "exception": ADAPTER_EXCEPTION,
    },
}

LIMITATION = {
    "D2-020": "The vector establishes stale lifecycle-state refusal; the multi-budget registry stale-revision variant remains pending.",
    "D2-031": "The vector establishes foreign-effect retention without the requested shared-budget projection; the payment-specific projection variant remains pending.",
    "D2-034": None,
    "D2-036": None,
    "D2-067": "The vector establishes a distinct foreign-effect fixture, without the requested shared-budget projection; the payment-specific projection variant remains pending.",
    "D2-068": "The vector establishes a distinct foreign-effect fixture, without the requested unprojectable shared-budget anchor; that variant remains pending.",
    "D2-084": None,
    "D2-086": None,
    "D2-101": "The vector establishes unexpected governed-effect retention, without the requested unprojectable payment fields; that payment-specific variant remains pending.",
    "D2-128": "The vector establishes evidence-unavailable refusal, without the requested budget-backed release-administration variant; that variant remains pending.",
    "D2-155": None,
    "D2-156": "The vector establishes matching completion, without the requested later-registry-revision settlement; that variant remains pending.",
}

CASE_IDS = sorted(LIMITATION)


def judgments() -> dict:
    contract = json.loads((HERE / "EXPECTED-JUDGMENTS-CONTRACT.json").read_text())
    return {row["id"]: row for row in contract["judgments"]}


def build() -> dict:
    pin = candidate_pin()
    contract_path = HERE / "EXPECTED-JUDGMENTS-CONTRACT.json"
    contract = judgments()
    rows = []

    for case_id in CASE_IDS:
        relative = f"{GROUP}/{case_id}.json"
        path = CANDIDATE / relative
        if not path.exists():
            raise SystemExit(f"{case_id}: case file absent at {relative}")
        case = json.loads(path.read_text())
        judgment = contract.get(case_id)
        if judgment is None:
            raise SystemExit(f"{case_id}: no frozen judgment in the contract")
        if case["id"] != case_id:
            raise SystemExit(f"{case_id}: case id member is {case['id']}")
        if case["operation"] != judgment["operation"]:
            raise SystemExit(f"{case_id}: operation differs from the judgment")
        if case["requirements"] != judgment["normative_references"]:
            raise SystemExit(f"{case_id}: citations differ from the judgment")

        rows.append({
            "case_id": case_id,
            "case_path": relative,
            "case_sha256": raw_sha256(path),
            "derivation": case["derivation"],
            "expected_digest": digest(RESULT_DOMAIN, case["expected"]),
            "expected_judgment": judgment["expected_judgment"],
            "input_digest": digest(INPUT_DOMAIN, case["input"]),
            "limitation": LIMITATION[case_id],
            "materialization": MATERIALIZED.get(case_id, DERIVED),
            "normative_references": judgment["normative_references"],
            "operation": case["operation"],
            "review_status": "PENDING_INDEPENDENT_REVIEW",
            "source_expected_digest": "sha256:" + hashlib.sha256(canonical_bytes(case["expected"])).hexdigest(),
        })

    return {
        "candidate_pin": pin,
        "case_count": str(len(rows)),
        "digest_domain": {"expected": RESULT_DOMAIN, "input": INPUT_DOMAIN},
        "expected_judgments_sha256": raw_sha256(contract_path),
        "identity": IDENTITY,
        "materialization_exceptions": sorted(MATERIALIZED),
        "method": METHOD,
        "rows": rows,
        "status": "PENDING_INDEPENDENT_REVIEW",
    }


def markdown(packet: dict) -> str:
    lines = [
        "# Morning exact-vector batch",
        "",
        f"Identity: `{packet['identity']}`",
        "",
        f"Candidate pin: `{packet['candidate_pin']}`",
        "",
        f"Status: `{packet['status']}`. {packet['case_count']} cases.",
        "",
        "Every digest in this packet is recomputed from the case bytes by",
        "`review/build-morning-vector-packet.py`. Rerunning that builder against an unchanged",
        "corpus reproduces the packet exactly, so a row cannot silently drift from its case file.",
        "",
        "## Method",
        "",
    ]
    lines += [f"{index}. {rule}" for index, rule in enumerate(packet["method"], start=1)]
    lines += [
        "",
        "## Materialization exceptions",
        "",
        "Two rows were produced with adapter output rather than derived without it. They are",
        "retained by an explicit decision of the project owner on 2026-09-11 and are recorded",
        "here so an independent reviewer can weigh them accordingly.",
        "",
        "| Case | Producer | What the producer checked |",
        "| --- | --- | --- |",
    ]
    for case_id in packet["materialization_exceptions"]:
        record = MATERIALIZED[case_id]
        lines.append(f"| `{case_id}` | `{record['producer']}` | {record['producer_check']} |")
    lines += [
        "",
        "The remaining ten rows reuse an admitted fixture verbatim through",
        "`review/build-morning-vector-batch.py` and consult no adapter output.",
        "",
        "## Cases",
        "",
        "| Case | Expected judgment | Cited rules | Residual limitation |",
        "| --- | --- | --- | --- |",
    ]
    for row in packet["rows"]:
        refs = ", ".join(f"`{value}`" for value in row["normative_references"])
        limit = row["limitation"] or "None recorded."
        lines.append(f"| `{row['case_id']}` | `{row['expected_judgment']}` | {refs} | {limit} |")
    lines += [
        "",
        "## What independent review must do",
        "",
        "Derive each complete result from the cited normative rule and the exact input without",
        "inspecting either implementation or its output. Compare the exact expected bytes,",
        "reproduce every digest in the row, and review the residual limitations. Treat the two",
        "materialized rows as author assertions until an independent derivation agrees.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    packet = build()
    (HERE / "EXACT-VECTOR-MORNING-BATCH-20260911.json").write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n"
    )
    (HERE / "EXACT-VECTOR-MORNING-BATCH-20260911.md").write_text(markdown(packet))
    print(json.dumps({
        "status": "WRITTEN",
        "identity": packet["identity"],
        "candidate_pin": packet["candidate_pin"],
        "case_count": packet["case_count"],
        "materialization_exceptions": packet["materialization_exceptions"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
