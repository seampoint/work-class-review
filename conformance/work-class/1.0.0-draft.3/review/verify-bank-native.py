#!/usr/bin/env python3
"""Retain exact offline native XML checks without contacting a filing service."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET

from bank_ack_fixture import acknowledgement, correlate, messages, selected_correlation
from bank_native_fixture import NS, package
from bank_native_validation import PACKET, validate_native, validators


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-directory", type=Path, required=True)
    args = parser.parse_args()
    out = args.report_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_paths = [*PACKET.rglob("*"), *[Path(__file__).with_name(name) for name in
        ("verify-bank-native.py", "bank_native_fixture.py", "bank_ack_fixture.py", "bank_native_validation.py")],
        *Path(__file__).with_name("fixtures").glob("bank-native-*")]
    source_paths = sorted({path.resolve() for path in source_paths if path.is_file()})
    hashes = lambda: {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    before = hashes()
    expectations = {
        "initial-schema": "VALID", "amendment-schema": "VALID", "messages-schema": "VALID", "ack-schema": "VALID", "substitute-ack-schema": "VALID",
        "clean-ack": "FILING_WITHOUT_INVENTED_PROVIDER_TIME", "warnings-ack": "COMPLETE_TWO_WARNINGS_AND_CORRECTION",
        "processing-only": "NO_ESTABLISHED_FILING", "rejected-processing": "NO_ESTABLISHED_FILING_OR_GLOBAL_ABSENCE",
        "amendment-ack": "DISTINCT_NEW_BSA_IDENTIFIER", "wrong-tracking": "REFUSED", "wrong-payload": "REFUSED",
        "wrong-activity": "REFUSED", "forged-correlation": "REFUSED", "wrong-ack-association": "REFUSED",
        "amendment-old-ack": "REFUSED", "missing-bsa": "REFUSED", "duplicate-warning-sequence": "REFUSED",
        "malformed-observation-time": "REFUSED", "external-entity": "REFUSED", "extra-activity": "REFUSED",
        "same-activity-substituted-ack": "REFUSED", "forged-ack-byte-envelope": "REFUSED", "substituted-messages": "REFUSED",
        "partial-authentication": "REFUSED", "legacy-boolean-authentication": "REFUSED"}
    (out / "expected.json").write_text(json.dumps(expectations, indent=2) + "\n")
    schemas = validators()
    rows = []
    def check(name, passed, actual):
        rows.append({"name": name, "expected": expectations[name], "passed": bool(passed), "actual": actual})
    native = lambda kind, raw: validate_native(kind, raw, schemas)
    for amended, name in ((False, "initial"), (True, "amendment")):
        selected = package(amended=amended)
        raw = selected["payload"].encode()
        (out / (name + ".xml")).write_bytes(raw)
        (out / (name + "-correspondence.json")).write_text(json.dumps(selected, indent=2) + "\n")
        errors = [str(error) for error in schemas["SUBMISSION"].iter_errors(raw)]
        check(name + "-schema", not errors, errors)
    message, ack = messages(), acknowledgement()
    (out / "messages.xml").write_bytes(message)
    (out / "ack.xml").write_bytes(ack)
    check("messages-schema", native("MESSAGES", message), [])
    check("ack-schema", native("ACK", ack), [])
    substitute_ack = acknowledgement(bsa_id="31000000000999")
    (out / "substitute-ack.xml").write_bytes(substitute_ack)
    check("substitute-ack-schema", native("ACK", substitute_ack), [])
    calls = out / "calls"
    calls.mkdir()
    call_number = 0
    def invoke(*, message_raw=message, ack_raw=ack, amended=False, correlation=None, authenticate=True, time="2026-10-08T10:00:00Z", payload=None, trusted_correlation=None, authentication_proof="full"):
        nonlocal call_number
        call_number += 1
        stem = calls / f"{call_number:04d}"
        submitted = package(amended=amended)["payload"].encode() if payload is None else payload
        selected = correlation if correlation is not None else selected_correlation(amended=amended, message_bytes=message_raw, ack_bytes=ack_raw)
        trusted = copy.deepcopy(selected if trusted_correlation is None else trusted_correlation)
        proof = trusted if authenticate else None
        if authenticate and authentication_proof == "association-only":
            proof = {key: value for key, value in trusted.items() if key not in {"native_payload_sha256", "message_sha256", "acknowledgement_sha256"}}
        elif authenticate and authentication_proof == "boolean":
            proof = True
        stem.with_suffix(".messages.xml").write_bytes(message_raw)
        stem.with_suffix(".submitted.xml").write_bytes(submitted)
        if ack_raw is not None:
            stem.with_suffix(".ack.xml").write_bytes(ack_raw)
        stem.with_suffix(".host-input.json").write_text(json.dumps({"correlation": selected,
            "fixture_authentication": authenticate, "fixture_trusted_correlation": trusted, "fixture_authentication_proof": proof, "observed_at": time,
            "observation_id": "synthetic-native-observation-1"}, indent=2) + "\n")
        return correlate(message_raw, ack_raw, selected,
            submitted_payload=submitted,
            validate_native=native, authenticate_correlation=lambda _: copy.deepcopy(proof),
            ack_received_at=time, observation_id="synthetic-native-observation-1")
    clean = invoke()
    check("clean-ack", clean["filing_established"] and clean["provider_event_time"] is None and clean["historical_filing_instant"] is None and clean["acknowledgement_errors"] == [{"sequence": "1", "fields": {}}], clean)
    warned = invoke(message_raw=messages(status="ACCEPTED-WITH-WARNINGS", warning=True), ack_raw=acknowledgement(warnings=True))
    check("warnings-ack", warned["filing_established"] and warned["correction_required"] and warned["warning_review_required"] and len(warned["acknowledgement_errors"]) == 2 and [row["fields"]["ErrorTypeCode"] for row in warned["acknowledgement_errors"]] == ["C21", "C4"], warned)
    processing = invoke(ack_raw=None)
    check("processing-only", not processing["filing_established"], processing)
    rejected = invoke(message_raw=messages(status="REJECTED"), ack_raw=None)
    check("rejected-processing", not rejected["filing_established"] and not rejected["no_filing_established"], rejected)
    amended = invoke(message_raw=messages(amended=True), ack_raw=acknowledgement(amended=True), amended=True)
    check("amendment-ack", amended["filing_established"] and amended["bsa_identifier"] == "31000000000002", amended)
    def altered(raw, update):
        root = ET.fromstring(raw)
        update(root)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    clean_correlation = selected_correlation(message_bytes=message, ack_bytes=ack)
    wrong_tracking = copy.deepcopy(clean_correlation); wrong_tracking["tracking_id"] = "SXST26-00000099"
    wrong_association = copy.deepcopy(clean_correlation); wrong_association["ack_file_submission_tracking_id"] = "SXST26-00000099"
    negatives = {
        "wrong-tracking": {"correlation": wrong_tracking}, "wrong-payload": {"payload": package()["payload"].encode() + b" "},
        "wrong-activity": {"ack_raw": acknowledgement(activity_sequence="999")}, "forged-correlation": {"authenticate": False},
        "wrong-ack-association": {"correlation": wrong_association},
        "amendment-old-ack": {"message_raw": messages(amended=True), "ack_raw": acknowledgement(), "amended": True},
        "missing-bsa": {"ack_raw": altered(ack, lambda root: root.find(".//{" + NS + "}BSAID").__setattr__("text", ""))},
        "duplicate-warning-sequence": {"ack_raw": altered(acknowledgement(warnings=True), lambda root: root.findall(".//{" + NS + "}EFilingActivityErrorXML")[1].set("SeqNum", "1"))},
        "malformed-observation-time": {"time": "2026-02-30T00:00:00Z"},
        "external-entity": {"ack_raw": b'<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]><x>&leak;</x>'},
        "extra-activity": {"ack_raw": altered(ack, lambda root: root[0].append(copy.deepcopy(root[0][0])))},
        "same-activity-substituted-ack": {"ack_raw": substitute_ack, "correlation": clean_correlation},
        "forged-ack-byte-envelope": {"ack_raw": substitute_ack, "trusted_correlation": clean_correlation},
        "substituted-messages": {"message_raw": messages(status="ACCEPTED-WITH-WARNINGS", warning=True), "correlation": clean_correlation},
        "partial-authentication": {"authentication_proof": "association-only"},
        "legacy-boolean-authentication": {"authentication_proof": "boolean"}}
    for name, supplied in negatives.items():
        try:
            result = invoke(**supplied)
            check(name, False, result)
        except ValueError as exc:
            check(name, True, {"error": str(exc)})
    import xmlschema, elementpath
    report = {"status": "PASS" if all(row["passed"] for row in rows) and before == hashes() else "FAIL",
        "checks": rows, "guard_unchanged": before == hashes(), "guarded_files": before,
        "versions": {"python": sys.version, "platform": platform.platform(), "xmlschema": xmlschema.__version__, "elementpath": elementpath.__version__},
        "scope": "Offline exact native-format admission and synthetic authenticated-correlation fixtures. No real filing, provider authentication, business content completeness or compliance claim."}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "checks": len(rows), "passed": sum(row["passed"] for row in rows), "guard_unchanged": report["guard_unchanged"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
