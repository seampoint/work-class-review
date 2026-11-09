"""Static candidate-pin checks over current executable cases, including encoded artifacts.

Historical review records are outside this inventory. Negative-case exceptions are
bound to exact case, pointer, value and expected result; no hash is globally exempt.
"""
from __future__ import annotations
import argparse
import base64
import binascii
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
AREA = HERE.parent
ROOT = AREA.parents[2]
ONES = "sha256:" + "1" * 64
PREDECESSOR = "sha256:120242f6e3a9cc67348932386460144ace5924d9b02852b878093b74a7af82a3"
ANOTHER = "sha256:df4d311d16e2e662547e2f32300e9bedf3fe4a8c0dc58bce75d2c18ebf876634"

# Each exception is a deliberate subject/version fault in its source builder.
# build-evidence-readback-cases.py: D2-212/213.
# build-equipment-correction-cases.py: C3-ER-094.
# build-holdings-source-cases.py: C3-HOLD-136/137.
# build-snapshot-eligibility-cases.py: C3-SNAPSHOT-031/032.
# build-step4-controls.py: C2-refuse-state-bound-to-other-pin.
INTENTIONAL_NONCURRENT = {
    ("D2-212", "/input/subject/specification_pin", ONES, "EVIDENCE_INVALID", "BINDING_MISMATCH"),
    ("D2-213", "/input/specification_pin", ONES, "REFUSED", "VERSION_UNSUPPORTED"),
    ("C3-ER-094", "/input/specification_pin", ANOTHER, "REFUSED", "VERSION_UNSUPPORTED"),
    ("C3-HOLD-136", "/input/request/holdings_bases/0/configuration/specification_pin", ONES, "REFUSED", "VERSION_UNSUPPORTED"),
    ("C3-HOLD-137", "/input/request/holdings_bases/0/state/specification_pin", ONES, "REFUSED", "VERSION_UNSUPPORTED"),
    ("C3-SNAPSHOT-031", "/input/specification_pin", PREDECESSOR, "REFUSED", "VERSION_UNSUPPORTED"),
    ("C3-SNAPSHOT-032", "/input/state/specification_pin", PREDECESSOR, "REFUSED", "STATE_INVALID"),
    ("C3-SNAPSHOT-032", "/expected/state/specification_pin", PREDECESSOR, "REFUSED", "STATE_INVALID"),
    ("C2-refuse-state-bound-to-other-pin", "/input/state/specification_pin", ONES, "REFUSED", "STATE_INVALID"),
    ("C2-refuse-state-bound-to-other-pin", "/expected/state/specification_pin", ONES, "REFUSED", "STATE_INVALID"),
}

def pin_fields(value, pointer=""):
    if isinstance(value, dict):
        for key, member in value.items():
            child = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            if key in {"candidate_pin", "specification_pin", "contract_manifest_pin"}:
                yield child, member
            yield from pin_fields(member, child)
            if isinstance(member, str) and key.endswith("bytes_base64"):
                try:
                    decoded = json.loads(base64.b64decode(member, validate=True))
                except (binascii.Error, ValueError, UnicodeError):
                    # Deliberately malformed artifacts are checked by schema/admission tests.
                    continue
                yield from pin_fields(decoded, child + "[decoded]")
    elif isinstance(value, list):
        for index, member in enumerate(value):
            yield from pin_fields(member, f"{pointer}/{index}")

def inspect_case(case, pin):
    errors, allowed = [], []
    expected = case.get("expected", {})
    for pointer, value in pin_fields(case):
        if value == pin:
            continue
        identity = (case.get("id"), pointer, value, expected.get("status"), expected.get("code"))
        row = {"id": case.get("id"), "pointer": pointer, "value": value}
        if isinstance(value, str) and identity in INTENTIONAL_NONCURRENT:
            allowed.append(row)
        else:
            errors.append(row)
    return errors, allowed

def inspect_corpus(cases, pin, *, verify_index=True):
    failures, exceptions, ids, file_ids = [], [], set(), {}
    paths = sorted(p for p in cases.rglob("*.json") if p.name != "index.json")
    for path in paths:
        case = json.loads(path.read_text())
        case_id = case.get("id")
        if case_id in ids:
            failures.append({"path": str(path), "error": "DUPLICATE_CASE_ID", "id": case_id})
        ids.add(case_id)
        file_ids[path.resolve()] = case_id
        bad, allowed = inspect_case(case, pin)
        failures.extend({"path": str(path), **row} for row in bad)
        exceptions.extend({"path": str(path), **row} for row in allowed)
    if verify_index:
        index = json.loads((cases / "index.json").read_text())
        if index.get("candidate_pin") != pin:
            failures.append({"path": str(cases / "index.json"), "error": "INDEX_PIN_MISMATCH"})
        indexed = {row["id"] for row in index["cases"]}
        if indexed != ids:
            failures.append({"error": "INDEX_CASE_SET_MISMATCH", "missing": sorted(ids-indexed), "extra": sorted(indexed-ids)})
        if len(index["cases"]) != len(indexed):
            failures.append({"error": "DUPLICATE_INDEX_ID"})
        indexed_paths = set()
        for row in index["cases"]:
            path = (cases.parent / row["path"]).resolve()
            if not path.is_relative_to(cases.resolve()):
                failures.append({"error": "INDEX_PATH_OUTSIDE_CASES", "id": row["id"], "path": str(path)})
                continue
            if path in indexed_paths:
                failures.append({"error": "DUPLICATE_INDEX_PATH", "id": row["id"], "path": str(path)})
            indexed_paths.add(path)
            if file_ids.get(path) != row["id"]:
                failures.append({"error": "INDEX_CASE_ID_MISMATCH", "id": row["id"],
                                 "file_id": file_ids.get(path), "path": str(path)})
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                failures.append({"error": "INDEX_HASH_MISMATCH", "id": row["id"], "path": str(path)})
    return {"status": "FAIL" if failures else "PASS", "candidate_pin": pin, "case_count": len(paths),
            "failing_case_count": len({r.get("id") for r in failures if r.get("id")}),
            "intentional_noncurrent_case_count": len({r["id"] for r in exceptions}),
            "intentional_noncurrent_fields": exceptions, "failures": failures}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=AREA / "cases")
    parser.add_argument("--contract-manifest", type=Path, default=ROOT / "library/work-class-specification/1.0.0-draft.3/contract-manifest.json")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    pin = "sha256:" + hashlib.sha256(args.contract_manifest.read_bytes()).hexdigest()
    result = inspect_corpus(args.cases, pin)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"failures", "intentional_noncurrent_fields"}},
                     indent=2))
    return 0 if result["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())

