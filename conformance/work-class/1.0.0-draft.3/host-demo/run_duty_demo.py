#!/usr/bin/env python3
"""Independent-process checks of scheduling, persistence and duty evidence."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timezone-file", default="/usr/share/zoneinfo/America/New_York", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("preserve existing output")
    output.mkdir(parents=True)
    (output / "RETENTION.md").write_text("Retain exact synthetic authenticated records, pinned timezone bytes, duty databases, crash evidence and process outputs. No real reminder or filing is sent.\n")
    timezone_file = output / "America_New_York.tzif"
    shutil.copyfile(args.timezone_file, timezone_file)
    source_paths = [HERE / name for name in ("bank_duty.py", "duty_worker.py", "run_duty_demo.py")]
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    for path in source_paths:
        shutil.copyfile(path, output / path.name)
    def event(identity, kind, at, **fields):
        return {"id": identity, "duty_id": "MRB-DUTY-074", "kind": kind, "observed_at": at, **fields}
    def clock(revision, at, status="AVAILABLE"):
        return event("clock-" + str(revision), "CLOCK", at, revision=str(revision), source="MRB-CLOCK", status=status)
    records = [clock(1, "2026-10-11T20:59:59Z"), clock(2, "2026-10-11T21:00:00Z"),
        clock(3, "2026-10-12T21:00:00Z", "UNAVAILABLE"), clock(4, "2026-10-13T21:00:00Z"),
        event("scheduler-fault", "FAULT", "2026-10-12T21:00:01Z", component="SCHEDULER", evidence="synthetic-independent-monitor", contingency_ref="MRB-HUMAN-CONTINGENCY-074"),
        event("storage-fault", "FAULT", "2026-10-12T21:00:02Z", component="STORAGE", evidence="synthetic-retained-failed-write", contingency_ref="MRB-HUMAN-CONTINGENCY-074")]
    delivery = {"intent_id": "reminder:2026-10-11T21:00:00Z", "channel": "protected-reporting", "recipients": ["bank-secrecy-act-officer", "reporting-records-custodian"]}
    records += [event("reminder-attempt-1", "DELIVERY_ATTEMPT", "2026-10-11T21:00:01Z", **delivery, disposition="RESPONSE_LOST"),
        event("reminder-ack-1", "DELIVERY_ACK", "2026-10-13T21:00:01Z", **delivery, attempt_id="reminder-attempt-1", acknowledgement="synthetic-recipient-delivery-record")]
    filing = {"bank": "MRB-US-01", "case": "MRB-CASE-074", "bsa_identifier": "31000000000001", "receipt_ref": "synthetic-accepted-filing"}
    records += [event("late-ack-timely-filing", "FILING_ACCEPTED", "2026-10-14T10:00:00Z", **filing,
        filed_at="2026-10-13T20:59:59Z", filing_date="2026-10-13"),
        event("late-filing", "FILING_ACCEPTED", "2026-10-15T10:00:00Z", **filing,
        filed_at="2026-10-15T09:59:59Z", filing_date="2026-10-15")]
    authenticated = output / "authenticated-records.json"
    authenticated.write_text(json.dumps(records, indent=2) + "\n")
    rows, sequence = [], 0
    def invoke(database, operation, **fields):
        nonlocal sequence
        sequence += 1
        request = {"database": str(database), "operation": operation, "authenticated_records": str(authenticated),
            "timezone_file": str(timezone_file), **fields}
        stem = output / f"{sequence:02d}"
        stem.with_suffix(".request.json").write_text(json.dumps(request, indent=2) + "\n")
        actual = subprocess.run([sys.executable, "-B", str(HERE / "duty_worker.py")], input=json.dumps(request).encode(), capture_output=True, timeout=30)
        stem.with_suffix(".stdout.json").write_bytes(actual.stdout)
        stem.with_suffix(".stderr.log").write_bytes(actual.stderr)
        stem.with_suffix(".process.json").write_text(json.dumps({"returncode": actual.returncode}) + "\n")
        return json.loads(actual.stdout) if actual.returncode == 0 else {"returncode": actual.returncode}
    def check(name, passed):
        rows.append({"name": name, "passed": bool(passed)})
    database = output / "duty.sqlite"
    initial = invoke(database, "INSTALL")["result"]
    check("exact selected legal date, operational instant and timezone pin", initial["legal_due_date"] == "2026-10-14" and initial["operational_deadline"] == "2026-10-13T21:00:00Z" and initial["timezone_sha256"] == hashlib.sha256(timezone_file.read_bytes()).hexdigest())
    before_reminder = invoke(database, "APPLY", record=records[0])["result"]
    check("no early reminder", not before_reminder["intents"])
    killed = invoke(database, "APPLY", record=records[1], kill_after_commit=True, kill_marker=str(output / "duty.kill.json"))
    restarted = invoke(database, "SNAPSHOT")["result"]
    check("actual kill preserves committed reminder before delivery", killed.get("returncode") == -9 and len(restarted["intents"]) == 1 and not restarted["intents"][0]["attempts"])
    replay = invoke(database, "APPLY", record=records[1])["result"]
    check("clock replay creates no second reminder", replay == restarted)
    attempt = invoke(database, "APPLY", record=records[6])["result"]
    check("lost delivery acknowledgement remains unresolved", len(attempt["intents"][0]["attempts"]) == 1 and attempt["intents"][0]["acknowledgement"] is None)
    unavailable = invoke(database, "APPLY", record=records[2])["result"]
    check("unavailable clock retains duty and schedules protected escalation", unavailable["status"] == "OPEN" and not unavailable["unresolved_at_operational_deadline"] and len(unavailable["intents"]) == 2)
    for record in records[4:6]:
        invoke(database, "APPLY", record=record)
    before_failure = invoke(database, "SNAPSHOT")["result"]
    failed = invoke(database, "APPLY", record=records[3], fail_commit=True)
    unchanged = invoke(database, "SNAPSHOT")["result"]
    check("failed persistence creates no partial deadline or notification", failed.get("type") == "OperationalError" and unchanged == before_failure)
    overdue = invoke(database, "APPLY", record=records[3])["result"]
    check("restored clock preserves missed reminder and overdue duty", overdue["status"] == "OPEN" and overdue["unresolved_at_operational_deadline"] and len([row for row in overdue["intents"] if row["kind"] == "FILING_REMINDER"]) == 2)
    acknowledged = invoke(database, "APPLY", record=records[7])["result"]
    check("late delivery evidence links the retained attempt", acknowledged["intents"][0]["acknowledgement"]["attempt_id"] == "reminder-attempt-1")
    closed = invoke(database, "APPLY", record=records[8])["result"]
    check("late acknowledgement preserves unresolved deadline without inventing late filing", closed["status"] == "CLOSED" and closed["unresolved_at_operational_deadline"] and not closed["filing"]["after_operational_deadline"] and not closed["filing"]["after_legal_due_date"])
    check("retention uses accepted filing date", closed["filing"]["minimum_retention_date"] == "2031-10-13")
    late_database = output / "late-duty.sqlite"
    invoke(late_database, "INSTALL")
    invoke(late_database, "APPLY", record=records[3])
    late = invoke(late_database, "APPLY", record=records[9])["result"]
    check("late filing remains recordable and preserves overdue evidence", late["status"] == "CLOSED" and late["unresolved_at_operational_deadline"] and late["filing"]["after_legal_due_date"] and late["filing"]["after_operational_deadline"])
    forged = copy.deepcopy(records[0]); forged["id"] = "forged-clock"
    refused = invoke(database, "APPLY", record=forged)
    check("self asserted clock record fails operator authentication", refused.get("status") == "REFUSED" and refused.get("reason") == "record authentication unavailable")
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    report = {"status": "PASS" if all(row["passed"] for row in rows) and before == after else "FAIL", "checks": rows,
        "guard_unchanged": before == after, "guard_before": before, "guard_after": after,
        "qualification": "DEVELOPMENT_RUN_NOT_QUALIFYING", "scope": "PERSISTENT_SYNTHETIC_DUTY_AND_DELIVERY_EVIDENCE",
        "limits": ["No reminder or filing was sent. Delivery and filing records are selected authenticated fixtures.",
            "Monitor fault reports exercise retained escalation intent; no real scheduler silence or physical storage outage is established.",
            "This store grants no filing authority and does not establish confidentiality of a deployment.",
            "Timezone bytes are pinned in this run. Legal date interpretation and provider filing time need bank review."]}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "checks": len(rows), "passed": sum(row["passed"] for row in rows), "guard_unchanged": before == after}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
