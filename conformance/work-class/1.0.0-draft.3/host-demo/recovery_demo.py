#!/usr/bin/env python3
"""Exercise retained registry disposition and new facts across local restart."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
AREA = HERE.parent
sys.path[:0] = [str(AREA / "review"), str(AREA / "python"), str(AREA / "python/vendor")]
from assessment_fixture import trace
from corpus_common import digest
from recovery_fixture import facts_for, disputed, dispose_request, disposition_expected, established_history
from reservation_fixture import native, host_and_event, request as registry_request
from sqlite_host import _decode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output already exists")
    output.mkdir(parents=True)
    (output / "RETENTION.md").write_text("Retain source-derived requests, exact subprocess evidence and durable registry state.\n")
    guarded = [*HERE.glob("*.py"), *AREA.joinpath("python/implementation").glob("*.py"),
        *AREA.joinpath("python/input").glob("*"), *AREA.joinpath("review").glob("*.py"),
        *AREA.joinpath("review/fixtures").glob("*")]
    guarded = [path for path in guarded if path.is_file()]
    before = {str(path.relative_to(AREA)): hashlib.sha256(path.read_bytes()).hexdigest() for path in guarded}
    facts = facts_for()
    initial = disputed(facts)
    disposition = dispose_request(facts, initial, "ESTABLISH_NO_EFFECT")
    expected = disposition_expected(disposition)
    restored_state = expected["state"]
    fresh_native = native(facts, "EFFECT", "late-effect-after-no-effect", effect_id="late-effect-2")
    history = established_history(facts, fresh_native)
    event, host_evidence = host_and_event(facts, "SETTLE", "retain-new-conflicting-effect", restored_state["core"]["revision"],
        {"native": fresh_native, "histories": [history]}, administration=False)
    new_fact = registry_request(restored_state, event, host_evidence)
    (output / "frozen-requests.json").write_text(json.dumps({"initial": initial, "disposition": disposition, "new_fact": new_fact}, indent=2) + "\n")
    base = trace()["base"]
    organization = base["deploy_input"]["deployment_authorization"]["organization_id"]
    instance = base["deploy_input"]["instance_id"]
    registry_digest = digest("reservation-registry", initial["core"]["configuration"])
    root = {"registry_digest": registry_digest, "affected_anchors": ["license-spend"], "state": initial,
        "state_digest": digest("reservation-state", initial)}
    database, sequence = output / "recovery.sqlite", 0

    def call(operation, method, *arguments):
        nonlocal sequence
        sequence += 1
        request = {"database": str(database), "operation": operation, "method": method, "arguments": arguments}
        (output / f"{sequence:02d}-request.json").write_text(json.dumps(request, indent=2) + "\n")
        actual = subprocess.run([sys.executable, "-B", str(HERE / "worker.py")], input=json.dumps(request).encode(), capture_output=True, timeout=120)
        (output / f"{sequence:02d}-stdout.json").write_bytes(actual.stdout)
        (output / f"{sequence:02d}-stderr.log").write_bytes(actual.stderr)
        if actual.returncode:
            return {"process_returncode": actual.returncode}
        value = json.loads(actual.stdout)
        return _decode(value["result"]) if value.get("status") == "RESULT" else value

    installed = call("CALL", "install", base["deploy_input"], [root])
    disposed = call("CALL", "submit_registry", organization, disposition)
    after_restart = call("INSPECT", "snapshot", organization, instance)
    owned = after_restart["budget_states"][0]
    new_fact.update(state=owned["state"], state_digest=owned["state_digest"])
    new_fact["event"]["expected_revision"] = owned["state"]["core"]["revision"]
    conflict = call("CALL", "submit_registry", organization, new_fact)
    final = call("INSPECT", "snapshot", organization, instance)
    fresh_facts = facts_for(instance="fresh-instance-after-conflict")
    reserve_event, reserve_host = host_and_event(fresh_facts, "RESERVE", "new-work-after-conflict",
        final["budget_states"][0]["state"]["core"]["revision"], {"authority": fresh_facts["authority_a"], "histories": [history]}, administration=False)
    blocked = call("CALL", "submit_registry", organization,
        registry_request(final["budget_states"][0]["state"], reserve_event, reserve_host))
    retained = after_restart["budget_states"][0]["state"]
    transition = blocked.get("transition", {})
    checks = {"installed": installed.get("disposition") == "INSTALLED",
        "disposition_committed": disposed.get("committed") is True,
        "disposition_reproduced_after_restart": retained == disposed.get("transition", {}).get("state") and retained["core"] == restored_state["core"],
        "new_fact_committed": conflict.get("committed") is True,
        "original_disposition_retained": final["budget_states"][0]["state"]["core"]["recovery"]["dispositions"] == restored_state["core"]["recovery"]["dispositions"],
        "fresh_reliance_blocked": transition.get("status") == "TRANSITION" and transition.get("receipt", {}).get("decision") == "WITHHELD"}
    after = {str(path.relative_to(AREA)): hashlib.sha256(path.read_bytes()).hexdigest() for path in guarded}
    report = {"status": "PASS" if all(checks.values()) and before == after else "FAIL", "checks": checks,
        "candidate_pin": base["deploy_input"]["specification_pin"], "guard_unchanged": before == after,
        "qualification": "DEVELOPMENT_RUN_NOT_QUALIFYING", "scope": "REGISTRY_DISPOSITION_RESTART_AND_NEW_CONFLICT",
        "guard_before": before, "guard_after": after, "blocked_response": blocked,
        "limitation": "The registry starts from a source-derived validated disputed history. This exercise does not establish a real provider's assertion or full lifecycle recovery."}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "checks": checks, "guard_unchanged": before == after}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
