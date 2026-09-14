"""Build-time helpers for draft-2 expected vectors.

This module implements only the canonical byte and digest constructions stated
in Specification.md. It is not imported by the qualification runner and does
not evaluate governance policy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
CONTRACT = ROOT / "library" / "work-class-specification" / "1.0.0-draft.2"
CONFORMANCE = ROOT / "conformance" / "work-class" / "1.0.0-draft.2"
CASES = CONFORMANCE / "cases"
EXPECTED_JUDGMENTS = CONFORMANCE / "review" / "EXPECTED-JUDGMENTS-CONTRACT.json"
DOMAIN_PREFIX = b"seampoint.work-class/1.0.0-draft.2/"


def _utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be", "surrogatepass")


def canonical_bytes(value: Any) -> bytes:
    """Serialize the number-free RFC 8785 subset in WCS2-001."""
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(canonical_bytes(member) for member in value) + b"]"
    if isinstance(value, dict):
        members = []
        for key in sorted(value, key=_utf16_sort_key):
            if not isinstance(key, str):
                raise TypeError("canonical object keys must be strings")
            members.append(canonical_bytes(key) + b":" + canonical_bytes(value[key]))
        return b"{" + b",".join(members) + b"}"
    raise TypeError(f"JSON numbers and unsupported value {type(value).__name__} are forbidden")


def digest(kind: str, value: Any) -> str:
    preimage = DOMAIN_PREFIX + kind.encode("utf-8") + b"\n" + canonical_bytes(value)
    return "sha256:" + hashlib.sha256(preimage).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_pin() -> str:
    return "sha256:" + raw_sha256(CONTRACT / "contract-manifest.json")


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def exact_case(
    case_id: str,
    operation: str,
    input_value: Any,
    expected: Any,
    requirements: list[str],
    derivation: str,
) -> dict[str, Any]:
    if case_id.startswith("D2-"):
        contract = json.loads(EXPECTED_JUDGMENTS.read_text())
        judgment = next((row for row in contract["judgments"] if row["id"] == case_id), None)
        if judgment is None:
            raise ValueError(f"unknown contract judgment {case_id}")
        if judgment["operation"] != operation:
            raise ValueError(
                f"{case_id} operation {operation!r} differs from judgment operation {judgment['operation']!r}"
            )
        requirements = judgment["normative_references"]
    return {
        "id": case_id,
        "operation": operation,
        "input": input_value,
        "expected": expected,
        "requirements": requirements,
        "derivation": derivation,
    }
