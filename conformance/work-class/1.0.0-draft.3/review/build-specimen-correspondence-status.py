#!/usr/bin/env python3
"""Rebuild the specimen correspondence status from the specimen artifacts on disk.

Every count is computed from the correspondence record and the derived readback, so the
status cannot drift from the specimens it describes. Mapped paths are reported both as
entries and as unique paths, because a path may be mapped by more than one source
obligation and reporting only the entry count makes the accounting look unbalanced.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
sys.path.insert(0, str(HERE))
from corpus_common import candidate_pin, raw_sha256  # noqa: E402


IDENTITY = "seampoint.work-class.specimen-correspondence-status/1.0.0-draft.3/2026-09-11"
SPECIMENS = ("access-card", "supplier-payment")
METHOD = (
    "Current-pinned mechanical inventory only. Every count is recomputed from the correspondence "
    "record and the derived readback. This record does not approve correspondence or establish "
    "fidelity to source policy."
)


def measure(name: str) -> dict:
    root = CANDIDATE / "specimens" / name
    record = json.loads((root / "correspondence-record.json").read_text())
    readback = json.loads((root / "readback-derived.json").read_text())

    entries = [path for mapping in record["mappings"] for path in mapping["provision_paths"]]
    unique = set(entries)
    unsupported = set(record["unsupported_provision_paths"])
    universe = len(readback["lines"])
    overlap = sorted(unique & unsupported)
    accounted = len(unique) + len(unsupported)

    return {
        "correspondence_review_status": record["review"]["status"],
        "correspondence_reviewer_id": record["review"]["reviewer_id"],
        "correspondence_sha256": raw_sha256(root / "correspondence-record.json"),
        "mapped_path_entry_count": str(len(entries)),
        "mapped_path_unique_count": str(len(unique)),
        "mapping_row_count": str(len(record["mappings"])),
        "overlapping_paths": overlap,
        "path_accounting": f"{len(unique)} unique mapped + {len(unsupported)} residue = {accounted} of {universe} readback paths",
        "path_accounting_balances": accounted == universe and not overlap,
        "readback_path_count": str(universe),
        "readback_sha256": raw_sha256(root / "readback-derived.json"),
        "residue_count": str(len(record["residue"])),
        "unsupported_path_count": str(len(unsupported)),
        "uncovered_source_obligation_ids": record["uncovered_source_obligation_ids"],
    }


def build() -> dict:
    specimens = {name: measure(name) for name in SPECIMENS}
    unbalanced = [name for name, row in specimens.items() if not row["path_accounting_balances"]]
    if unbalanced:
        raise SystemExit(f"path accounting does not balance for: {', '.join(unbalanced)}")
    pending = sorted(
        name for name, row in specimens.items()
        if row["correspondence_review_status"] != "ACCEPTED"
    )
    return {
        "candidate_identity": "seampoint.work-class/1.0.0-draft.3",
        "candidate_pin": candidate_pin(),
        "identity": IDENTITY,
        "method": METHOD,
        "pending_correspondence_reviews": pending,
        "residual_limitation": (
            "Each record accounts for every current readback path through a unique mapping or a "
            "residue row, with no path in both. A specimen whose embedded review is not ACCEPTED "
            "yields EVIDENCE_NOT_ACCEPTED under PROTOCOL.md check-evidence, and the cross-language "
            "specimen verifier does not remove that requirement."
        ),
        "specimens": specimens,
        "status": "PENDING_INDEPENDENT_REVIEW" if pending else "ALL_CORRESPONDENCE_REVIEWS_ACCEPTED",
    }


def markdown(record: dict) -> str:
    lines = [
        "# Current specimen correspondence status",
        "",
        f"Candidate pin: `{record['candidate_pin']}`",
        "",
        "Every count below is recomputed from the correspondence record and the derived readback by",
        "`review/build-specimen-correspondence-status.py`.",
        "",
        "A path may be mapped by more than one source obligation, so the mapped entry count can",
        "exceed the number of distinct paths. The accounting balances against unique paths, not",
        "entries.",
        "",
        "| Specimen | Readback paths | Mapping rows | Mapped entries | Unique mapped | Residue | Accounting | Embedded review |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in sorted(record["specimens"].items()):
        lines.append(
            f"| `{name}` | {row['readback_path_count']} | {row['mapping_row_count']} | "
            f"{row['mapped_path_entry_count']} | {row['mapped_path_unique_count']} | "
            f"{row['residue_count']} | {row['path_accounting']} | `{row['correspondence_review_status']}` |"
        )
    lines += [
        "",
        "## What this record does not establish",
        "",
        record["residual_limitation"],
        "",
    ]
    if record["pending_correspondence_reviews"]:
        names = ", ".join(f"`{name}`" for name in record["pending_correspondence_reviews"])
        lines += [
            f"Pending acceptance: {names}. A fresh reviewer must accept the subject before the",
            "package can claim accepted correspondence evidence. Acceptance rewrites the embedded",
            "review, which changes the correspondence record bytes and every artifact bound to them.",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    record = build()
    (HERE / "SPECIMEN-CORRESPONDENCE-STATUS-20260911.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    (HERE / "SPECIMEN-CORRESPONDENCE-STATUS-20260911.md").write_text(markdown(record))
    print(json.dumps({
        "status": "WRITTEN",
        "record_status": record["status"],
        "pending_correspondence_reviews": record["pending_correspondence_reviews"],
        "accounting": {name: row["path_accounting"] for name, row in sorted(record["specimens"].items())},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
