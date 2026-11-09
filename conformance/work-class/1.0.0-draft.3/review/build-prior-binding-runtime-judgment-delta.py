#!/usr/bin/env python3
"""Apply and record the bounded D2-285 expected-judgment correction."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from corpus_common import canonical_bytes, write_canonical_json


REVIEW = Path(__file__).resolve().parent
CONFORMANCE = REVIEW.parent
ROOT = CONFORMANCE.parents[2]
CONTRACT_ROOT = ROOT / "library" / "work-class-specification" / "1.0.0-draft.3"
EXPECTED = REVIEW / "EXPECTED-JUDGMENTS-CONTRACT.json"
DELTA_JSON = REVIEW / "PRIOR-BINDING-RUNTIME-JUDGMENT-DELTA-20260911.json"
DELTA_MD = REVIEW / "PRIOR-BINDING-RUNTIME-JUDGMENT-DELTA-20260911.md"
BUILDER = REVIEW / "build-prior-binding-runtime-cases.py"
PIN = "sha256:fb5217778257b5be25ee09a63cfa30e4874dfec4fd49775709e34d961504a130"
PREVIOUS_CONTRACT_SHA256 = "ab05c10a2be0d547dcdd55c386824ed946c29c57ca6b66a51134612a9152d526"

OLD_ROW = {
    "derivation_status": "DERIVED_FROM_NORMATIVE_TEXT_BEFORE_IMPLEMENTATION_OUTPUT",
    "expected_judgment": "REFUSED/BINDING_MISMATCH",
    "id": "D2-285",
    "normative_references": ["LIFE-006", "LIFE-007", "COMP-BIND-001"],
    "operation": "step",
    "scenario": "The current or prior selected authority-act projection contains more than one act of the declared separation kind",
    "state_and_budget_consequence": "Exact supplied work and budget states returned unchanged; the consumer does not choose an act.",
}

NEW_ROW = {
    "derivation_status": "AUTHOR_CONSTRUCTED_PENDING_INDEPENDENT_REVIEW",
    "expected_judgment": "REFUSED/STATE_INVALID",
    "id": "D2-285",
    "normative_references": ["AUTH-004", "LIFE-008", "LIFE-019"],
    "operation": "step",
    "scenario": "A restarted state retains a current or prior permit containing more than one authority-act basis of the separation requirement's declared act kind",
    "state_and_budget_consequence": "Exact supplied work and budget states returned unchanged; restart integrity rejects the retained permit before evaluating the new event.",
}

CASE_IDS = [f"D2-{value}" for value in range(277, 288)] + ["D2-293"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_path(case_id: str) -> Path:
    group = "prior-binding-restart" if case_id == "D2-285" else "prior-binding-runtime"
    return CONFORMANCE / "cases" / group / f"{case_id}.json"


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> None:
    original_bytes = EXPECTED.read_bytes()
    contract = json.loads(original_bytes)
    if contract["candidate_pin"] != PIN:
        raise AssertionError("candidate pin changed")
    row = next(entry for entry in contract["judgments"] if entry["id"] == "D2-285")
    if row == OLD_ROW:
        if hashlib.sha256(original_bytes).hexdigest() != PREVIOUS_CONTRACT_SHA256:
            raise AssertionError("unexpected pre-correction judgment-contract hash")
    elif row != NEW_ROW:
        raise AssertionError("D2-285 differs from both the superseded and corrected rows")

    row.clear()
    row.update(copy.deepcopy(NEW_ROW))
    contract["review_revision"] = "contract-remediation.44-author-revision"
    contract["status"] = "AUTHOR_REVISION_PENDING_INDEPENDENT_REVIEW"
    write_canonical_json(EXPECTED, contract)
    current_contract_sha256 = sha256(EXPECTED)

    cases = [
        {
            "case_id": case_id,
            "path": relative(case_path(case_id)),
            "sha256": sha256(case_path(case_id)),
        }
        for case_id in CASE_IDS
    ]
    normative_sources = [
        CONTRACT_ROOT / "AUTHORITY.md",
        CONTRACT_ROOT / "COMPOSITION.md",
        CONTRACT_ROOT / "LIFECYCLE.md",
        CONTRACT_ROOT / "contract-manifest.json",
    ]
    record = {
        "identity": "seampoint.work-class.prior-binding-runtime-author-judgment-delta/1.0.0-draft.3/1",
        "status": "AUTHOR_CONSTRUCTED_PENDING_INDEPENDENT_REVIEW",
        "candidate_pin": PIN,
        "scope": CASE_IDS,
        "normative_sources": [
            {"path": relative(path), "sha256": sha256(path)} for path in normative_sources
        ],
        "builder": {"path": relative(BUILDER), "sha256": sha256(BUILDER)},
        "cases": cases,
        "expected_judgments_contract": {
            "path": relative(EXPECTED),
            "previous_sha256": PREVIOUS_CONTRACT_SHA256,
            "current_sha256": current_contract_sha256,
            "review_revision": contract["review_revision"],
            "status": contract["status"],
        },
        "judgment_change": {
            "case_id": "D2-285",
            "superseded": OLD_ROW,
            "replacement": NEW_ROW,
            "reason": "AUTHORITY admission rejects competing selected acts before proposal-time actor separation can observe same-kind multiplicity. LIFE-019 separately requires restart integrity to reject an injected retained permit projection with STATE_INVALID.",
            "normative_semantics_changed": False,
            "candidate_pin_changed": False,
        },
        "construction_controls": {
            "canonical_case_json": "PASS",
            "protocol_schema_admission": "PASS",
            "digest_and_transaction_envelopes": "PASS",
            "scenario_specific_normative_invariants": "PASS",
            "implementation_adapters_or_outputs_used": False,
            "global_case_index_updated": False,
            "judgment_case_register_updated": False,
        },
        "limitations": [
            "This is an author construction record, not an independent semantic review.",
            "The cases are intentionally absent from the global case index and judgment register until independent review.",
            "No TypeScript or Python adapter source or adapter, runner or cross-language output artifact was opened or executed. A broad post-construction path search exposed artifact names and one unrelated prior-review result line; that material was not used to construct or validate these cases.",
        ],
    }
    write_canonical_json(DELTA_JSON, record)

    lines = [
        "# Prior-binding runtime judgment delta",
        "",
        f"Status: `{record['status']}`",
        "",
        f"Candidate pin: `{PIN}`",
        "",
        "D2-285 changes from `REFUSED/BINDING_MISMATCH` to `REFUSED/STATE_INVALID`. AUTHORITY admission makes proposal-time selected-act multiplicity unreachable because competing selected acts fail before actor separation. The exact case therefore injects a second `INSTANCE_DECISION` basis into a retained current permit and exercises LIFE-019 restart integrity with a greater-revision clock probe. The supplied state and all supplied budget states remain unchanged.",
        "",
        f"The expected-judgments contract changes from raw SHA-256 `{PREVIOUS_CONTRACT_SHA256}` to `{current_contract_sha256}` and has review revision `{contract['review_revision']}`. This author revision requires independent review.",
        "",
        "| Case | Path | Raw SHA-256 |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {entry['case_id']} | `{entry['path']}` | `{entry['sha256']}` |"
        for entry in cases
    )
    lines.extend(
        [
            "",
            "Construction controls passed for canonical JSON, protocol schema admission, digest and transaction envelopes, and the scenario-specific predecessor, effect, authority-act, precedence and restart invariants. These controls establish well-formed authored vectors; they do not independently review the expected decisions.",
            "",
            "The global case index and judgment register remain unchanged. No implementation adapter source or adapter, runner or cross-language output artifact was opened or executed. A broad post-construction path search exposed artifact names and one unrelated prior-review result line; that material was not used to construct or validate these cases.",
            "",
        ]
    )
    DELTA_MD.write_bytes("\n".join(lines).encode("utf-8"))

    print(
        json.dumps(
            {
                "status": record["status"],
                "expected_judgments_sha256": current_contract_sha256,
                "cases": len(cases),
                "global_indexes_updated": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
