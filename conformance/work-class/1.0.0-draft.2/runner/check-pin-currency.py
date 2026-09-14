#!/usr/bin/env python3
"""Inventory declared candidate pins and normative citations, and fail on stale ones.

A record that declares the current candidate pin must also cite the current bytes of
every normative document it names. Records at a superseded pin are inventoried rather
than failed, because the convention retains them as provenance.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
REVIEW = CANDIDATE / "review"
ROOT = CANDIDATE.parents[2]
CONTRACT = ROOT / "library" / "work-class-specification" / "1.0.0-draft.2"
sys.path.insert(0, str(REVIEW))
from corpus_common import candidate_pin  # noqa: E402


PIN_KEYS = ("candidate_pin", "specification_pin", "contract_manifest_pin")
CITATION_KEYS = ("contract_hashes", "normative_sources", "reviewed_contract_hashes", "source_hashes")

# Artifacts a generator rebuilds from the current contract. These are stale only when a
# repin was not propagated, so a superseded pin here is a defect rather than provenance.
# Pins that a case carries by design; a generated report that embeds that case's input repeats them.
INTENTIONAL_NONCURRENT_PINS = {
    "sha256:" + "1" * 64: "cases/step4-controls/C2-refuse-state-bound-to-other-pin.json supplies a state bound to another pin",
}
GENERATED = (
    "cases/index.json",
    "cases/vector-controls/index.json",
    "review/EXPECTED-JUDGMENTS-CONTRACT.json",
    "review/JUDGMENT-CASE-REGISTER.json",
    "review/runs/py-morning-final.json",
    "review/runs/specimen-final.json",
    "review/runs/ts-morning-final.json",
    "specimens/access-card/artifact-index.json",
    "specimens/supplier-payment/artifact-index.json",
)


def declared_pins(value: object, found: list) -> list:
    if isinstance(value, dict):
        for key, member in value.items():
            if key in PIN_KEYS and isinstance(member, str) and member.startswith("sha256:"):
                found.append(member)
            declared_pins(member, found)
    elif isinstance(value, list):
        for member in value:
            declared_pins(member, found)
    return found


def normative_citations(value: object, found: list) -> list:
    """Collect (name, sha256) pairs from every citation shape in use."""
    if isinstance(value, dict):
        path = value.get("path")
        sha = value.get("raw_sha256") or value.get("sha256")
        if isinstance(path, str) and isinstance(sha, str):
            found.append((path, sha))
        for key, member in value.items():
            if isinstance(member, str) and key not in ("path",) and len(member) == 64:
                try:
                    int(member, 16)
                except ValueError:
                    pass
                else:
                    found.append((key, member))
            else:
                normative_citations(member, found)
    elif isinstance(value, list):
        for member in value:
            normative_citations(member, found)
    return found


def contract_file(name: str) -> Path | None:
    candidate = CONTRACT / Path(name).name
    return candidate if candidate.is_file() else None


def check_citations(record: dict, relative: str, pin: str, failures: list) -> tuple[int, int]:
    """Fail a record that declares the current pin but cites superseded normative bytes.

    Returns the number of citations resolved to a normative file and the number stale,
    so a vacuous pass is distinguishable from a verified one.
    """
    declared = set(declared_pins(record, []))
    if pin not in declared:
        return 0, 0
    cited = []
    for key in CITATION_KEYS:
        if key in record:
            normative_citations(record[key], cited)
    verified = stale = 0
    for name, sha in cited:
        path = contract_file(name)
        if path is None:
            continue
        verified += 1
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != sha:
            stale += 1
            failures.append({
                "path": relative,
                "requirement": "NORMATIVE_CITATION_CURRENT",
                "detail": f"cites {Path(name).name} at {sha[:12]}, current is {actual[:12]}",
            })
    return verified, stale


def main() -> int:
    pin = candidate_pin()
    inventory: dict = {}
    failures: list = []
    citations_verified = 0
    citations_stale = 0

    for path in sorted(CANDIDATE.glob("**/*.json")):
        if "__pycache__" in path.parts:
            continue
        try:
            record = json.loads(path.read_text())
        except ValueError:
            continue
        pins = set(declared_pins(record, []))
        if not pins:
            continue
        relative = str(path.relative_to(CANDIDATE))
        for value in pins:
            inventory.setdefault(value, []).append(relative)
        verified, stale = check_citations(record, relative, pin, failures)
        citations_verified += verified
        citations_stale += stale

    generated_stale = []
    for relative in GENERATED:
        path = CANDIDATE / relative
        if not path.exists():
            # Development run reports are written by a verification pass and are not committed.
            if relative.startswith("review/runs/"):
                continue
            failures.append({"path": relative, "requirement": "GENERATED_PRESENT", "detail": "declared generated artifact is absent"})
            continue
        pins = set(declared_pins(json.loads(path.read_text()), []))
        stale = sorted(value for value in pins if value != pin and value not in INTENTIONAL_NONCURRENT_PINS)
        if stale:
            generated_stale.append(relative)
            failures.append({"path": relative, "requirement": "GENERATED_PIN_CURRENT", "detail": f"carries {', '.join(stale)}"})

    superseded = {value: sorted(paths) for value, paths in inventory.items() if value != pin}
    result = {
        "status": "PASS" if not failures else "FAIL",
        "identity": "seampoint.work-class.pin-currency-control/1.0.0-draft.2",
        "candidate_pin": pin,
        "files_at_current_pin": str(len(inventory.get(pin, []))),
        "files_at_superseded_pins": str(sum(len(paths) for paths in superseded.values())),
        "superseded_pins": {value: str(len(paths)) for value, paths in sorted(superseded.items())},
        "generated_artifacts_checked": str(len(GENERATED)),
        "generated_artifacts_stale": generated_stale,
        "normative_citations_verified": str(citations_verified),
        "normative_citations_stale": str(citations_stale),
        "superseded_inventory": superseded,
        "failures": failures,
    }
    print(json.dumps(result, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
