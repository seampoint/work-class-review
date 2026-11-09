#!/usr/bin/env python3
"""Build supplementary restricted-JSON and Base64 admission cases."""

from __future__ import annotations

import base64
import copy
import json

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from fixture_factory import PIN, work_class


def artifact_input(encoded: str) -> dict[str, str]:
    return {
        "kind": "WORK_CLASS",
        "specification_pin": PIN,
        "artifact_bytes_base64": encoded,
    }


def refusal(code: str) -> dict[str, str]:
    return {"status": "REFUSED", "code": code, "path": ""}


def nonzero_pad_bits(encoded: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    padding = len(encoded) - len(encoded.rstrip("="))
    if padding not in {1, 2}:
        raise ValueError("fixture must use Base64 padding")
    index = len(encoded) - padding - 1
    original = alphabet.index(encoded[index])
    changed = original | (1 if padding == 1 else 1)
    if changed == original:
        changed = original | (2 if padding == 1 else 4)
    candidate = encoded[:index] + alphabet[changed] + encoded[index + 1 :]
    if base64.b64decode(candidate, validate=True) != base64.b64decode(encoded, validate=True):
        raise AssertionError("pad-bit mutation changed decoded bytes")
    if base64.b64encode(base64.b64decode(candidate, validate=True)).decode("ascii") == candidate:
        raise AssertionError("pad-bit mutation remained canonical")
    return candidate


def build() -> list[dict]:
    definition = work_class("LINEAR")
    admitted = canonical_bytes(definition)
    encoded = base64.b64encode(admitted).decode("ascii")
    if not encoded.endswith(("=", "==")):
        adjusted = copy.deepcopy(definition)
        adjusted["source"]["text"] += "x"
        admitted = canonical_bytes(adjusted)
        encoded = base64.b64encode(admitted).decode("ascii")
    if not encoded.endswith(("=", "==")):
        adjusted["source"]["text"] += "x"
        admitted = canonical_bytes(adjusted)
        encoded = base64.b64encode(admitted).decode("ascii")

    complete_escaped = admitted.replace(b'"schema"', b'"\\u0073chema"', 1)
    cases = [
        exact_case(
            "C2-001",
            "validate",
            artifact_input(base64.b64encode(b"\xef\xbb\xbf" + admitted).decode("ascii")),
            refusal("ARTIFACT_ENCODING_INVALID"),
            ["WCS2-001", "WCS2-012"],
            "The byte-order mark is outside the restricted artifact encoding and is rejected before JSON or work-class validation.",
        ),
        exact_case(
            "C2-002",
            "validate",
            artifact_input(base64.b64encode(b'{"s":"\xff"}').decode("ascii")),
            refusal("ARTIFACT_ENCODING_INVALID"),
            ["WCS2-001", "WCS2-012"],
            "The decoded artifact contains an invalid UTF-8 octet. Artifact encoding refusal precedes JSON shape validation.",
        ),
        exact_case(
            "C2-003",
            "validate",
            artifact_input(base64.b64encode(b'{"s":"\\ud800"}').decode("ascii")),
            refusal("ARTIFACT_ENCODING_INVALID"),
            ["WCS2-001", "WCS2-012"],
            "A syntactically escaped lone high surrogate is not a Unicode scalar value and fails restricted artifact encoding.",
        ),
        exact_case(
            "C2-004",
            "validate",
            artifact_input(base64.b64encode(b'{"a":"x","\\u0061":"y"}').decode("ascii")),
            refusal("ARTIFACT_ENCODING_INVALID"),
            ["WCS2-001", "WCS2-012"],
            "The two key spellings decode to the same key. Duplicate-key detection occurs before map construction.",
        ),
        exact_case(
            "C2-005",
            "validate",
            artifact_input(base64.b64encode(admitted + b"\n").decode("ascii")),
            refusal("ARTIFACT_NONCANONICAL"),
            ["WCS2-001", "WCS2-012"],
            "The decoded artifact is valid JSON with the same value, but its trailing line feed is absent from canonical serialization.",
        ),
        exact_case(
            "C2-006",
            "validate",
            artifact_input(base64.b64encode(complete_escaped).decode("ascii")),
            refusal("ARTIFACT_NONCANONICAL"),
            ["WCS2-001", "WCS2-012"],
            "The complete work class decodes to the admitted value but spells one ASCII character as a Unicode escape, which canonical JSON does not do.",
        ),
        exact_case(
            "C2-007",
            "validate",
            artifact_input(nonzero_pad_bits(encoded)),
            refusal("ARTIFACT_ENCODING_INVALID"),
            ["WCS2-001", "WCS2-012"],
            "The Base64 text decodes to the admitted work-class bytes but has nonzero unused pad bits. Re-encoding does not reproduce the supplied string.",
        ),
        exact_case(
            "C2-008",
            "validate",
            artifact_input(encoded + "\n"),
            refusal("ARTIFACT_ENCODING_INVALID"),
            ["WCS2-001", "WCS2-012"],
            "Whitespace is forbidden inside a Base64 field even when a permissive decoder would ignore it.",
        ),
        exact_case(
            "C2-009",
            "property",
            {"kind": "UNICODE_NO_NORMALIZATION", "values": ["é", "é"]},
            {
                "canonical_bytes_base64": [
                    base64.b64encode(canonical_bytes("é")).decode("ascii"),
                    base64.b64encode(canonical_bytes("é")).decode("ascii"),
                ],
                "digests": [digest("canonicalization-property", "é"), digest("canonicalization-property", "é")],
                "relation": "DISTINCT",
            },
            ["WCS2-001"],
            "Composed and decomposed Unicode strings remain distinct. Canonicalization preserves their exact scalar sequences and yields distinct domain-separated digests.",
        ),
    ]
    return cases


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "canonical-bytes" / f"{case['id']}.json", case)
    print(json.dumps({"candidate_pin": PIN, "case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
