#!/usr/bin/env python3
"""Exercise the fictional conditional provider and both process-local hosts."""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = HERE.parents[3]
FAILURE_REPORT = None
HOST_API_OUTCOMES = {}
sys.path.insert(0, str(BASE / "python"))
from consumer import Consumer
from implementation.common import Refusal
from implementation.reference_host import SingleProcessReferenceHost
from cdmo_provider_simulator import ConditionalInventory


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provider_checks(trace, judgments):
    authorization = trace["authorized"]["state"]["authorizations"][0]
    request = authorization["native_request"]
    results = {}
    for case in judgments:
        provider = ConditionalInventory(authorization, request)
        kind = case["mutation"]["kind"]
        selected = next((row for row in provider.sources if row["requirement_id"] == case["mutation"].get("requirement_id")), None)
        if kind == "REVISION": selected["provider_revision"] += ":changed"
        elif kind == "STATUS": selected["expected_status"] = "AVAILABLE"
        elif kind == "COORDINATOR": provider.coordinator += ":changed"
        elif kind == "OMIT": provider.sources.pop()
        elif kind == "REORDER": provider.sources.reverse()
        elif kind == "COORDINATES": provider.sources[0]["provider"] += ":other"
        elif kind == "EXPIRED": provider.now = authorization["expires_at"]
        elif kind == "INVENTORY": provider.inventory_revision = "other-opaque-revision"
        elif kind in {"PRIOR_UNRESOLVED", "PRIOR_FRESH_KEYS"}: provider.progress("other-request", "POSSIBLY_SENT")
        elif kind == "OWN_PROGRESS": provider.progress(provider.candidate, "POSSIBLY_SENT")
        elif kind == "SESSION_ENDED": provider.executor_session_current = False
        elif kind == "REQUEST_KEY":
            values = {row["name"]: row["value"]["value"] for row in request["fields"]}
            provider.keys.add(("request", "cedar-vector-manufacturing", values["request_id"]))
        elif kind == "DISPOSITION_KEY":
            values = {row["name"]: row["value"]["value"] for row in request["fields"]}
            provider.keys.add(("disposition", "cedar-inventory-ledger", values["batch_id"], values["site_id"], values["cedar_approval_identity"], "3"))
        elif kind == "CEDAR_WITHDRAWN": provider.decision_effective["cedar"] = False
        elif kind == "ALDER_WITHDRAWN": provider.decision_effective["alder"] = False
        before = provider.snapshot()
        committed = provider.commit(request, fail_commit=kind == "FAIL_COMMIT")
        if kind == "LATER_HOLD": provider.hold_after_commit()
        after = provider.snapshot()
        actual = {"committed": committed, "event_count": len(provider.events),
                  "write_roots_unchanged_on_refusal": not committed and after == before}
        if kind == "LATER_HOLD":
            actual.update(retained_event=len(provider.events) == 1, containment_intents=len(provider.containment_intents))
        results[case["id"]] = actual
    return results


def host_checks(trace):
    base = trace["base"]
    organization = base["deploy_input"]["deployment_authorization"]["organization_id"]
    instance = base["deploy_input"]["instance_id"]
    expected_dispatch = json.loads((BASE / "cases/cdmo-source/C3-CD-010.json").read_bytes())["expected"]
    expected_observation = {name: copy.deepcopy(trace["dispatch_event"][name]) for name in ("attempt", "acknowledgement")}

    def step_input(host, event):
        snapshot = host.snapshot(organization, instance)
        event = copy.deepcopy(event)
        event.update(expected_state_revision=snapshot["state"]["revision"], expected_state_digest=snapshot["state_digest"])
        return {"profile": base["deploy_input"]["profile"], "role": base["deploy_input"]["role"],
                "specification_pin": base["deploy_input"]["specification_pin"], "definition": base["definition"],
                "definition_digest": base["definition_digest"], "state": snapshot["state"],
                "state_digest": snapshot["state_digest"], "event": event}

    def install(through_authorization=True):
        host = SingleProcessReferenceHost(Consumer())
        seeded = base["registry_seed_trace"][-1][1]
        root = {"registry_digest": base["key_proposal_event"]["budget_inputs"][0]["registry_digest"],
                "affected_anchors": [], "state": seeded["state"], "state_digest": seeded["state_digest"]}
        assert host.install(base["deploy_input"], [root])["disposition"] == "INSTALLED"
        events = [base["clock_event"]]
        if through_authorization:
            events += [base["key_proposal_event"], base["dispatch_clock_event"], trace["authorization_event"]]
        for event in events:
            response = host.submit(organization, step_input(host, event))
            if response.get("host_commit", {}).get("disposition") != "COMMITTED":
                failure = FAILURE_REPORT.with_name(FAILURE_REPORT.stem + "-" + event["kind"] + "-failure.json")
                assert not failure.exists()
                failure.write_text(json.dumps(response, indent=2) + "\n")
                raise AssertionError(f"{event['kind']}: {response.get('status')} {response.get('code')} {response.get('host_commit')}; full result {failure}")
        return host

    results = {}
    host = install(False)
    before = host.snapshot(organization, instance)
    response = host.submit(organization, step_input(host, base["key_proposal_event"]), "cdmo-test-commit-failure")
    assert response["host_commit"]["disposition"] == "COMMIT_FAILED", response
    results["commit-failure-before-proposal"] = {"roots_unchanged": host.snapshot(organization, instance) == before, "invocations": 0}

    for name in ("one-invocation-and-no-repeat", "connector-throws-and-no-repeat", "wrong-connector-binding", "expired-authorization", "unavailable-clock", "parallel-invocation-requests"):
        host = install()
        authorization = host.snapshot(organization, instance)["state"]["authorizations"][0]
        provider = ConditionalInventory(authorization, authorization["native_request"])
        calls = []
        callback_errors = []
        injected_error = RuntimeError("injected connector failure")
        entered, release = threading.Event(), threading.Event()
        expected_payload = {
            "instance_id": instance, "authorization_digest": authorization["authorization_digest"],
            "dispatch_intent_id": authorization["dispatch_intent_id"], "native_request": authorization["native_request"],
            "connector": authorization["connector"], "authorization_fence": authorization["authorization_fence"],
            "expires_at": authorization["expires_at"],
        }

        def invoke(payload):
            calls.append(copy.deepcopy(payload))
            try:
                assert payload == expected_payload, "connector authorization payload mismatch"
                if name == "connector-throws-and-no-repeat": raise injected_error
                if name == "parallel-invocation-requests":
                    entered.set()
                    assert release.wait(15), "parallel invocation was not released"
                assert provider.commit(payload["native_request"]) is True, "provider refused the authorized native request"
                return copy.deepcopy(expected_observation)
            except Exception as error:
                if error is not injected_error: callback_errors.append(error)
                raise

        connector = {**authorization["connector"], "invoke": invoke}
        if name == "wrong-connector-binding": connector["id"] += "-other"
        if name in {"expired-authorization", "unavailable-clock"}:
            event = copy.deepcopy(base["dispatch_clock_event"])
            event["event_id"] = "cdmo-probe-clock-3"
            event["clock"]["revision"] = "3"
            if name == "expired-authorization": event["clock"]["observed_time"] = authorization["expires_at"]
            else: event["clock"].update(status="UNAVAILABLE", observed_time=None)
            response = host.submit(organization, step_input(host, event))
            assert response["host_commit"]["disposition"] == "COMMITTED", response

        before_dispatch = host.snapshot(organization, instance)
        outcomes = {}

        def dispatch(ordinal):
            try:
                event_id = trace["dispatch_event"]["event_id"] if ordinal == 1 else "cdmo-host-dispatch-" + str(ordinal)
                result = host.dispatch(organization, instance, authorization["authorization_digest"], connector, event_id)
            except Refusal as error:
                expected_code = {"wrong-connector-binding": "BINDING_MISMATCH", "expired-authorization": "PREREQUISITE_MISSING", "unavailable-clock": "CLOCK_INVALID"}.get(name)
                assert ordinal == 1 and expected_code is not None and error.code == expected_code, f"unexpected host refusal: {name}/{ordinal}/{error.code}"
                result = {"error": error.code}
            outcomes[ordinal] = result
            return result

        def committed(result):
            assert set(result) == {"transition", "host_commit"}, "successful dispatch did not return a committed transition"
            assert result["transition"] == expected_dispatch, "dispatch differs from the independent C3-CD-010 oracle"
            commit = result["host_commit"]
            assert commit["disposition"] == "COMMITTED" and commit["transaction_digest"] == expected_dispatch["transaction_digest"]
            assert commit["state_before_digest"] == before_dispatch["state_digest"] and commit["state_after_digest"] == expected_dispatch["state_digest"]
            retained = host.snapshot(organization, instance)
            assert retained["state"] == expected_dispatch["state"] and retained["state_digest"] == expected_dispatch["state_digest"]
            assert retained["budget_states"] == before_dispatch["budget_states"], "dispatch unexpectedly changed reservation roots"

        def replay(result, statuses):
            assert result in [{"status": "HOST_DISPATCH", "disposition": status, "dispatch_performed": False, "replay": True} for status in statuses], "unexpected repeat dispatch outcome"

        if name == "parallel-invocation-requests":
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(dispatch, 1)
                try:
                    assert entered.wait(15), "first parallel invocation did not enter the connector"
                    second = pool.submit(dispatch, 2)
                    loser = second.result(timeout=15)
                    replay(loser, {"PENDING", "CONSUMED"})
                finally:
                    release.set()
                committed(first.result(timeout=30))
        else:
            first = dispatch(1)
            if name == "one-invocation-and-no-repeat": committed(first)
            elif name == "connector-throws-and-no-repeat":
                assert first == {"status": "HOST_DISPATCH", "disposition": "PENDING", "dispatch_performed": True}, "connector failure did not retain a pending claim"
            else:
                assert set(first) == {"error"}, "expected a specific host refusal"
                assert host.snapshot(organization, instance) == before_dispatch, "refused dispatch changed authoritative roots"
        result = {"invocations": len(calls), "commits": len(provider.events)}
        if name in {"one-invocation-and-no-repeat", "connector-throws-and-no-repeat"}:
            before_count = len(calls)
            replay(dispatch(2), {"CONSUMED" if name == "one-invocation-and-no-repeat" else "PENDING"})
            result["repeat_invoked"] = len(calls) != before_count
        assert not callback_errors, f"unexpected callback error: {callback_errors!r}"
        claims = host.dispatch_claims(organization, instance)
        if calls:
            assert len(claims) == 1 and claims[0]["authorization"] == authorization, "dispatch claim authorization mismatch"
            assert claims[0]["status"] == ("PENDING" if name == "connector-throws-and-no-repeat" else "CONSUMED"), "unexpected retained dispatch claim"
            if name != "connector-throws-and-no-repeat":
                assert claims[0]["observation"] == expected_observation and claims[0]["result"] == outcomes[1]
        else:
            assert not claims, "refused dispatch retained a claim"
        HOST_API_OUTCOMES[name] = {str(ordinal): {"sha256": hashlib.sha256(canonical(outcome)).hexdigest(), "status": outcome.get("status", outcome.get("transition", {}).get("status")), "disposition": outcome.get("disposition", outcome.get("host_commit", {}).get("disposition")), "error": outcome.get("error")} for ordinal, outcome in sorted(outcomes.items())}
        if name in {"wrong-connector-binding", "expired-authorization", "unavailable-clock"}: result["withheld"] = not calls
        results[name] = result
    return results


def main():
    global FAILURE_REPORT
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    FAILURE_REPORT = args.report
    assert not args.report.exists(), "preserve prior report"
    oracle_path = HERE / "CDMO-HOST-EXPECTED-JUDGMENTS.json"
    judgments = json.loads(oracle_path.read_bytes())
    trace = json.loads(args.trace.read_bytes())
    files = [args.trace, oracle_path, BASE / "cases/cdmo-source/C3-CD-010.json"]
    for directory in [BASE / "python", BASE / "typescript", HERE]:
        files += [p for p in directory.rglob("*") if p.is_file() and p.suffix in {".py", ".ts"}
                  and not any(x in p.parts for x in ("vendor", "node_modules", "__pycache__", "records"))]
    norm = ROOT / "library/work-class-specification/1.0.0-draft.3"
    files += [norm / "contract-manifest.json"] + [norm / row["path"] for row in json.loads((norm / "contract-manifest.json").read_bytes())["files"]]
    inventory = [{"path": str(p.resolve()), "sha256": sha(p)} for p in sorted(set(files))]
    py = {"provider": provider_checks(trace, judgments["provider_cases"]), "host": host_checks(trace)}
    command = ["node", str(HERE / "cdmo-host-probe.ts"), str(args.trace.resolve())]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=300)
    args.report.with_suffix(".typescript.stdout").write_bytes(completed.stdout)
    args.report.with_suffix(".typescript.stderr").write_bytes(completed.stderr)
    ts = json.loads(completed.stdout) if completed.returncode == 0 else {"error": completed.returncode}
    ts_api_outcomes = ts.pop("host_api_outcomes", None)
    expected = {"provider": {row["id"]: row["expected"] for row in judgments["provider_cases"]},
                "host": {row["id"]: row["expected"] for row in judgments["host_cases"]}}
    changes = [row["path"] for row in inventory if sha(Path(row["path"])) != row["sha256"]]
    passed = py == expected == ts and not changes
    record = {"status": "PASS" if passed else "FAIL", "qualification": "DEVELOPMENT_PROCESS_LOCAL_SIMULATION",
              "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "command": sys.argv,
              "typescript_command": command, "typescript_exit_code": completed.returncode,
              "candidate_pin": "sha256:" + sha(norm / "contract-manifest.json"),
              "provider_cases": len(judgments["provider_cases"]), "host_cases": len(judgments["host_cases"]),
              "expected": expected, "actual_python": py, "actual_typescript": ts,
              "host_api_outcomes": {"python": HOST_API_OUTCOMES, "typescript": ts_api_outcomes},
              "provider_commit_failure_scope": "Injected provider failure is a pre-write veto; partial-write rollback is not exercised.",
              "input_and_consumer_hashes_verified_before_and_after": not changes,
              "changed_files": changes, "files": inventory, "scope": judgments["scope"]}
    args.report.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k not in {"expected", "actual_python", "actual_typescript", "files"}}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
