#!/usr/bin/env python3
"""Check every work-state collection in corpus inputs and expectations."""

from __future__ import annotations

import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
REVIEW = CANDIDATE / "review"
sys.path.insert(0, str(REVIEW))
from corpus_common import canonical_bytes  # noqa: E402


WORK_STATE_SCHEMA = "seampoint.work-class/1.0.0-draft.2/work-state"


def occurrence_for(state: dict, occurrence_id: str) -> dict:
    for row in state["active"] + state["completed"]:
        if row["occurrence"]["occurrence_id"] == occurrence_id:
            return row["occurrence"]
    raise KeyError(occurrence_id)


def checks(state: dict):
    return [
        ("active", lambda row: canonical_bytes(row["occurrence"])),
        ("completed", lambda row: canonical_bytes(row["occurrence"])),
        ("obligations", lambda row: row["obligation_id"].encode("utf-8")),
        ("proposals", lambda row: row["event_id"].encode("utf-8")),
        ("permits", lambda row: row["permit_id"].encode("utf-8")),
        ("dispatches", lambda row: row["dispatch_digest"].encode("utf-8")),
        ("outcomes", lambda row: row["outcome_digest"].encode("utf-8")),
        ("clocks", lambda row: (row["source"].encode("utf-8"), int(row["revision"]))),
        (
            "deadlines",
            lambda row: (
                row["due"].encode("utf-8"),
                canonical_bytes(occurrence_for(state, row["occurrence_id"])),
                row["deadline_id"].encode("utf-8"),
            ),
        ),
        (
            "fanout_passes",
            lambda row: (
                row["fanout_id"].encode("utf-8"),
                int(row["pass"]),
                row["expand_occurrence_id"].encode("utf-8"),
            ),
        ),
        ("receipts", lambda row: int(row["sequence"])),
        ("replays", lambda row: row["event_id"].encode("utf-8")),
    ]


def main() -> int:
    failures = []
    states = 0
    for path in sorted((CANDIDATE / "cases").rglob("*.json")):
        if path.name == "index.json":
            continue
        case = json.loads(path.read_text())

        def walk(value, pointer: str) -> None:
            nonlocal states
            if isinstance(value, dict):
                if value.get("schema") == WORK_STATE_SCHEMA:
                    states += 1
                    for name, key in checks(value):
                        rows = value[name]
                        try:
                            ordered = sorted(rows, key=key)
                        except (KeyError, TypeError, ValueError) as error:
                            failures.append({"case_id": case["id"], "pointer": pointer + "/" + name, "error": str(error)})
                            continue
                        if rows != ordered:
                            failures.append({"case_id": case["id"], "pointer": pointer + "/" + name, "error": "UNSORTED"})
                for name, member in value.items():
                    walk(member, pointer + "/" + name)
            elif isinstance(value, list):
                for index, member in enumerate(value):
                    walk(member, pointer + "/" + str(index))

        walk(case, "")
    result = {"status": "PASS" if not failures else "FAIL", "work_states_checked": str(states), "failures": failures}
    print(json.dumps(result, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
