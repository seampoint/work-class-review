#!/usr/bin/env python3
"""Retain actual independent-process durability and crash evidence."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

HERE = Path(__file__).resolve().parent
AREA = HERE.parent
sys.path[:0] = [str(AREA / "review"), str(AREA / "python"), str(AREA / "python/vendor")]
from assessment_fixture import trace, completed
from lifecycle_factory import step_input
from sqlite_host import _decode


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output already exists; preserve prior evidence")
    if Path("/Volumes/ssd").is_dir() and not str(output).startswith("/Volumes/ssd/"):
        parser.error("output must be under /Volumes/ssd")
    output.mkdir(parents=True)
    (output / "calls").mkdir()
    (output / "RETENTION.md").write_text("Retain exact process requests, responses, crash markers and separate databases as development evidence. No automatic deletion is scheduled.\n")
    guarded = sorted(list(HERE.glob("*.py")) + list((AREA / "python/implementation").glob("*.py")) + list((AREA / "python/input").glob("*"))
        + list((AREA / "review").glob("*.py")) + list((AREA / "review/fixtures").glob("*"))
        + list((AREA / "specimens/supplier-payment").rglob("*.json")))
    guarded = [path for path in guarded if path.is_file()]
    before = {str(path.relative_to(AREA)): sha(path) for path in guarded}
    write(output / "guard-before.json", before)
    import shutil
    for path in guarded + list(HERE.glob("*.md")):
        destination = output / "source-snapshot" / path.relative_to(AREA)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    facts = trace()
    write(output / "assessment-inputs.json", facts)
    sequence, rows = 0, []

    def worker(request, background=False):
        nonlocal sequence
        sequence += 1
        stem = output / "calls" / f"{sequence:04d}"
        write(stem.with_suffix(".request.json"), request)
        process = subprocess.Popen([sys.executable, "-B", str(HERE / "worker.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if background:
            process.stdin.write(json.dumps(request).encode())
            process.stdin.close()
            process.stdin = None
            return process, stem
        return complete(process, stem, json.dumps(request).encode())

    def complete(process, stem, data=None):
        stdout, stderr = process.communicate(data, timeout=120)
        stem.with_suffix(".stdout.json").write_bytes(stdout)
        stem.with_suffix(".stderr.log").write_bytes(stderr)
        write(stem.with_suffix(".process.json"), {"pid": process.pid, "returncode": process.returncode})
        if process.returncode != 0:
            return {"process_returncode": process.returncode}
        raw = json.loads(stdout)
        return _decode(raw["result"]) if raw.get("status") == "RESULT" else raw

    def call(database, method, *arguments, **options):
        return worker({"database": str(database), "operation": "CALL", "method": method, "arguments": arguments, **options})

    def inspect(database, method, *arguments):
        return worker({"database": str(database), "operation": "INSPECT", "method": method, "arguments": arguments})

    def check(name, passed, observed):
        rows.append({"exercise": name, "passed": bool(passed), "observed": observed})

    organization = facts["base"]["deploy_input"]["deployment_authorization"]["organization_id"]
    instance = facts["base"]["deploy_input"]["instance_id"]
    initial = facts["stages"][:5]

    def prepare(database):
        results = []
        for operation, request, expected in initial:
            result = call(database, "install", request) if operation == "deploy" else call(database, "submit", organization, request)
            results.append(result)
            if operation == "deploy":
                assert result.get("disposition") == "INSTALLED", result
            else:
                assert result.get("host_commit", {}).get("disposition") == "COMMITTED", result
        return results

    database = output / "baseline.sqlite"
    prepare(database)
    snapshot = inspect(database, "snapshot", organization, instance)
    check("install and restart", snapshot["state"] == facts["authorized"]["state"], {"state_digest": snapshot["state_digest"]})
    changed = copy.deepcopy(initial[0][1])
    changed["authorization_evidence"]["evidence_id"] += "-other"
    # A changed deployment with independently valid organizational evidence.
    from fixture_factory import deployment
    changed, _ = deployment(facts["base"]["definition"], instance_id=instance, organization_id=organization,
        authorization_time="2026-10-08T09:58:00Z", evidence_expires_at="2026-10-09T00:00:00Z")
    occupied = call(database, "install", changed)
    current = inspect(database, "snapshot", organization, instance)
    check("occupied instance", occupied.get("disposition") == "INSTANCE_OCCUPIED" and current == snapshot, occupied)

    wrong_pin_database = output / "wrong-pin.sqlite"
    with sqlite3.connect(database) as source, sqlite3.connect(wrong_pin_database) as destination:
        source.backup(destination)
    with sqlite3.connect(wrong_pin_database) as connection:
        connection.execute("UPDATE checkpoints SET pin=?", ("sha256:" + "0" * 64,))
    refused = inspect(wrong_pin_database, "snapshot", organization, instance)
    check("wrong candidate", refused == {"status": "REFUSED", "code": "PIN_MISMATCH"}, refused)

    failed_database = output / "failed-commit.sqlite"
    failed = call(failed_database, "install", initial[0][1], fail_commit=True)
    failed_checkpoint = inspect(failed_database, "export_checkpoint")
    check("failed state and event-log commit", failed.get("type") == "OperationalError" and not failed_checkpoint["authoritative"]["roots"], failed)

    # Exercise the same atomic rollback against an already installed root.
    current = inspect(database, "snapshot", organization, instance)
    next_clock = copy.deepcopy(facts["stages"][6][1])
    next_clock.update(state=current["state"], state_digest=current["state_digest"])
    next_clock["event"].update(expected_state_revision=current["state"]["revision"], expected_state_digest=current["state_digest"])
    failed_event = call(database, "submit", organization, next_clock, fail_commit=True)
    after_failure = inspect(database, "snapshot", organization, instance)
    check("failed event persistence preserves installed root", failed_event.get("type") == "OperationalError" and after_failure == current, failed_event)

    killed_database = output / "before-commit.sqlite"
    marker = output / "before-commit.kill.json"
    killed = call(killed_database, "install", initial[0][1], kill_at="BEFORE_COMMIT", kill_marker=str(marker))
    checkpoint = inspect(killed_database, "export_checkpoint")
    check("kill before commit", killed.get("process_returncode") == -9 and marker.exists() and not checkpoint["authoritative"]["roots"], killed)

    key = output / "operator.key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    authorization = facts["authorized"]["state"]["authorizations"][-1]
    for label, failure in (("failed-intent", "FAIL"), ("after-intent", "AFTER_INTENT_COMMIT"), ("after-effect", "AFTER_RESOURCE_EFFECT")):
        host_database, resource_database = output / f"{label}.sqlite", output / f"{label}-resource.sqlite"
        prepare(host_database)
        command = {"database": str(host_database), "operation": "DISPATCH", "organization": organization,
            "instance_id": instance, "authorization_digest": authorization["authorization_digest"],
            "connector": authorization["connector"], "event_id": "durable-dispatch-1",
            "operator_key": str(key), "resource_database": str(resource_database)}
        if failure == "FAIL":
            command["fail_commit"] = True
        else:
            command.update(kill_at=failure, kill_marker=str(output / f"{label}.kill.json"))
        result = worker(command)
        claims = inspect(host_database, "dispatch_claims", organization, instance)
        if failure == "FAIL":
            check("failed intent commit", result.get("disposition") == "COMMIT_FAILED" and not claims and not resource_database.exists(), result)
            continue
        replay = worker({key: value for key, value in command.items() if key not in {"kill_at", "kill_marker"}})
        resource = subprocess.run([sys.executable, "-B", str(HERE / "connector_process.py"), "--database", str(resource_database), "--operator-key", str(key)],
            input=b'{"operation":"READ"}', capture_output=True, check=True)
        resource_state = json.loads(resource.stdout)
        write(output / f"{label}-resource-state.json", resource_state)
        wanted = 0 if failure == "AFTER_INTENT_COMMIT" else 1
        passed = (result.get("process_returncode") == -9 and len(claims) == 1 and claims[0]["status"] == "PENDING"
            and replay.get("replay") is True and replay.get("dispatch_performed") is False
            and resource_state["accepted_calls"] == wanted and len(resource_state["effects"]) == wanted)
        check("kill after intent commit" if wanted == 0 else "kill after resource effect", passed,
            {"kill": result, "replay": replay, "resource": resource_state, "claim_status": [row["status"] for row in claims]})

    # Reconcile the same retained invocation using independently journaled effect
    # fields and the specimen's synthetic provider evidence conversion.
    host_database = output / "after-effect.sqlite"
    recovered = call(host_database, "recover_dispatch", organization, instance, authorization["dispatch_intent_id"], "durable-unknown-1")
    for _, original, _ in facts["stages"][6:7]:
        current = inspect(host_database, "snapshot", organization, instance)
        request = copy.deepcopy(original)
        request.update(state=current["state"], state_digest=current["state_digest"])
        request["event"].update(expected_state_revision=current["state"]["revision"], expected_state_digest=current["state_digest"])
        reconciled = call(host_database, "submit", organization, request)
    current = inspect(host_database, "snapshot", organization, instance)
    event, expected_completion = completed(facts["base"], {**current, "permit": facts["permitted"]["permit"]})
    reconciled = call(host_database, "submit", organization, step_input(facts["base"], current["state"], event))
    final = inspect(host_database, "snapshot", organization, instance)
    resource_database = output / "after-effect-resource.sqlite"
    with sqlite3.connect(resource_database) as connection:
        effects = connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
        accepted_calls = connection.execute("SELECT COUNT(*) FROM calls WHERE accepted=1").fetchone()[0]
    check("explicit reconciliation", final["state"]["status"] == "COMPLETE" and effects == accepted_calls == 1,
        {"unknown_disposition": recovered.get("transition", {}).get("decision", {}).get("disposition"), "final_status": final["state"]["status"],
            "reconciliation_disposition": reconciled.get("transition", {}).get("decision", {}).get("disposition"), "effects": effects, "accepted_calls": accepted_calls})

    supplier = AREA / "specimens/supplier-payment"
    contention_database = output / "contention.sqlite"
    registration = json.loads((supplier / "shared-budget-register-result-derived.json").read_bytes())
    proposals = json.loads((supplier / "contention/requests.json").read_bytes())
    nested = proposals[0]["input"]["event"]["budget_inputs"][0]
    budget_root = {"registry_digest": nested["registry_digest"], "affected_anchors": nested["affected_anchors"],
        "state": registration["state"], "state_digest": registration["state_digest"]}
    supplier_organization = None
    for suffix in ("a", "b"):
        requests = json.loads((supplier / f"instances/{suffix}/through-master-change-requests.json").read_bytes())
        for row in requests:
            if row["operation"] == "deploy":
                supplier_organization = row["input"]["deployment_authorization"]["organization_id"]
                result = call(contention_database, "install", row["input"], [budget_root])
                assert result.get("disposition") == "INSTALLED", result
            else:
                result = call(contention_database, "submit", supplier_organization, row["input"])
                assert result.get("host_commit", {}).get("disposition") == "COMMITTED", result
    processes = [worker({"database": str(contention_database), "operation": "CALL", "method": "submit",
        "arguments": [supplier_organization, row["input"]]}, background=True) for row in proposals[:2]]
    outcomes = [complete(process, stem) for process, stem in processes]
    snapshot = inspect(contention_database, "snapshot", supplier_organization, proposals[0]["input"]["state"]["instance_id"])
    reservations = snapshot["budget_states"][0]["state"]["core"]["reservations"]
    permitted = sum(row.get("transition", {}).get("decision", {}).get("disposition") == "PERMITTED" for row in outcomes)
    check("two clients share last budget allocation", permitted == 1 and len(reservations) == 1,
        {"permitted": permitted, "reservation_count": len(reservations), "decisions": [row.get("transition", {}).get("decision", {}).get("disposition", row.get("code")) for row in outcomes]})

    direct = {"operation": "WRITE", "payload": {"dispatch_intent_id": "unauthorized-direct-write"}, "signature": "0" * 64}
    refused = subprocess.run([sys.executable, "-B", str(HERE / "connector_process.py"), "--database", str(resource_database), "--operator-key", str(key)],
        input=json.dumps(direct).encode(), capture_output=True, check=True)
    read = subprocess.run([sys.executable, "-B", str(HERE / "connector_process.py"), "--database", str(resource_database), "--operator-key", str(key)],
        input=b'{"operation":"READ"}', capture_output=True, check=True)
    refusal, readable = json.loads(refused.stdout), json.loads(read.stdout)
    write(output / "alternate-resource-write.json", {"request": direct, "response": refusal, "read": readable})
    check("alternate resource clients", refusal.get("status") == "REFUSED" and readable["status"] == "READ"
        and len(readable["effects"]) == 1 and readable["accepted_calls"] == 1, {"write": refusal, "readable": readable["status"], "effects": len(readable["effects"])})

    after = {str(path.relative_to(AREA)): sha(path) for path in guarded}
    write(output / "guard-after.json", after)
    failed = sum(not row["passed"] for row in rows)
    report = {"status": "PASS" if failed == 0 and before == after else "FAIL", "scope": "LOCAL_DURABILITY_CONTENTION_RECONCILIATION",
        "candidate_pin": initial[0][1]["specification_pin"], "guard_unchanged": before == after,
        "qualification": "DEVELOPMENT_RUN_NOT_QUALIFYING", "passed": len(rows) - failed, "failed": failed, "results": rows,
        "remaining_approved_exercises": ["disposition restart and new conflict"]}
    write(output / "report.json", report)
    print(json.dumps({key: report[key] for key in ["status", "scope", "passed", "failed", "guard_unchanged"]}))
    return 0 if failed == 0 and before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
