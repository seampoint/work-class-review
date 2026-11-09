#!/usr/bin/env python3
"""Build exact common timestamp-grammar property controls."""

from __future__ import annotations

import json

from corpus_common import CASES, exact_case, write_canonical_json


def build() -> list[dict]:
    second_accepted = [
        "0001-01-01T00:00:00Z",
        "2000-02-29T23:59:59Z",
        "9999-12-31T23:59:59Z",
    ]
    second_rejected = [
        "0000-12-31T23:59:59Z",
        "2025-02-29T00:00:00Z",
        "2026-01-01T24:00:00Z",
        "2026-01-01T00:00:60Z",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:00.000000000Z",
    ]
    nano_accepted = [
        "0001-01-01T00:00:00.000000000Z",
        "2000-02-29T23:59:59.000000001Z",
        "9999-12-31T23:59:59.999999999Z",
    ]
    nano_rejected = [
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00.1Z",
        "2026-01-01T00:00:00.00000000Z",
        "2026-01-01T00:00:00.0000000000Z",
        "2026-04-31T00:00:00.000000000Z",
        "2026-01-01T00:00:60.000000000Z",
    ]
    return [
        exact_case(
            "T2-001",
            "property",
            {"kind": "TIMESTAMP_GRAMMAR", "precision": "SECOND", "values": second_accepted + second_rejected},
            {"accepted": second_accepted, "rejected": second_rejected},
            ["WCS2-001", "AGG-002", "LIFE-014"],
            "Whole-second UTC timestamps admit valid Gregorian dates in years 0001 through 9999 and reject fractions, offsets, leap seconds, 24:00, year zero, and nonexistent dates.",
        ),
        exact_case(
            "T2-002",
            "property",
            {"kind": "TIMESTAMP_GRAMMAR", "precision": "NANOSECOND", "values": nano_accepted + nano_rejected},
            {"accepted": nano_accepted, "rejected": nano_rejected},
            ["WCS2-001", "AGG-002"],
            "Nanosecond UTC timestamps require exactly nine fractional digits and the same valid Gregorian and clock-field bounds.",
        ),
    ]


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "temporal-controls" / f"{case['id']}.json", case)
    print(json.dumps({"case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
