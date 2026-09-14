#!/usr/bin/env python3
"""Verify draft-2 specimens against both adapters and reference hosts."""

from __future__ import annotations

import argparse
import copy
import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT / "conformance/work-class/1.0.0-draft.2"
SPECIMENS = BASE / "specimens"
PYTHON = BASE / "python"
TYPESCRIPT = BASE / "typescript"
PIN = "sha256:" + hashlib.sha256((HERE.parents[3] / "library/work-class-specification/1.0.0-draft.2/contract-manifest.json").read_bytes()).hexdigest()  # the selected candidate pin, read from the manifest
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.2"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


def run(command: list[str], payload: bytes) -> bytes:
    completed = subprocess.run(command, cwd=ROOT, input=payload, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"{' '.join(command)} exited {completed.returncode}: {completed.stderr.decode(errors='replace')}")
    return completed.stdout


def lines(payload: bytes) -> list[dict]:
    return [json.loads(line) for line in payload.splitlines()]


class Checks:
    def __init__(self):
        self.rows: list[dict] = []

    def equal(self, group: str, name: str, actual, expected) -> None:
        passed = actual == expected
        row = {"group": group, "name": name, "passed": passed}
        if not passed:
            def serializable(value):
                if isinstance(value, bytes):
                    return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                return value
            row.update({"actual": serializable(actual), "expected": serializable(expected)})
        self.rows.append(row)

    def true(self, group: str, name: str, actual: bool) -> None:
        self.equal(group, name, bool(actual), True)


def detail(result: dict, kind: str) -> dict | None:
    return next((row for row in result.get("decision", {}).get("details", []) if row.get("kind") == kind), None)


def budget_result(result: dict) -> dict | None:
    rows = result.get("budget_results", [])
    return rows[0]["result"] if rows else None


def reservation(result: dict) -> dict | None:
    budget = budget_result(result)
    if budget is None:
        return None
    reservation_id = budget["receipt"].get("reservation")
    return next((row for row in budget["state"]["core"]["reservations"] if row["id"] == reservation_id), None)


def occurrence_status(result: dict, request: dict) -> str | None:
    event = request["input"]["event"]
    permit = event.get("permit")
    occurrence = permit.get("occurrence") if isinstance(permit, dict) else event.get("proposal", {}).get("occurrence")
    occurrence_id = occurrence.get("occurrence_id") if isinstance(occurrence, dict) else None
    state = result.get("state", {})
    for row in state.get("active", []) + state.get("completed", []):
        if row.get("occurrence", {}).get("occurrence_id") == occurrence_id:
            return row.get("status") or row.get("disposition")
    return None


def supplied_budget_states(request: dict) -> list[dict]:
    result = []
    for row in request.get("input", {}).get("event", {}).get("budget_inputs", []):
        result.append({
            "registry_digest": row["registry_digest"],
            "affected_anchors": row["affected_anchors"],
            "state": row["request"]["state"],
            "state_digest": row["request"]["state_digest"],
        })
    return result


def history_accumulator(result: dict) -> str:
    budget = budget_result(result)["state"]["core"]["budgets"][0]
    values = []
    for row in budget["history"]["journal"]:
        if row["event"]["state"] == "ACTIVE":
            field = next((x for x in row["event"]["fields"] if x["name"] == "amount"), None)
            values.append(Decimal(field["value"]["value"]) if field else Decimal(1))
    total = sum(values, Decimal(0))
    return format(total, "f")


def observed_assertions(scenario_id: str, result: dict, request: dict, valid: dict[str, list[dict]]) -> dict:
    decision = result.get("decision", {})
    authority = detail(result, "AUTHORITY") or {}
    effect = detail(result, "EFFECT") or {}
    budget = budget_result(result)
    receipt = budget["receipt"] if budget else {}
    reservation_row = reservation(result)
    observed = {
        "status": result.get("status"), "code": result.get("code"),
        "disposition": decision.get("disposition"), "reason_codes": decision.get("reason_codes"),
        "permit": result.get("permit"), "budget_results": result.get("budget_results"),
        "classification": effect.get("classification"), "budget_decision": receipt.get("decision"),
        "budget_reasons": receipt.get("reasons"), "next_registry_revision": receipt.get("revision"),
        "reservation_status": reservation_row.get("status") if reservation_row else None,
        "blocked_partitions": budget["state"]["core"]["effects"][-1]["blocked_partitions"] if budget and budget["state"]["core"]["effects"] else None,
        "budget_revision": budget["state"]["core"]["revision"] if budget else None,
        "occurrence_status": occurrence_status(result, request) if request.get("operation") == "step" else None,
        "work_revision": result.get("state", {}).get("revision"), "work_status": result.get("state", {}).get("status"),
        "replay": result.get("replay"), "authority_code": authority.get("code"),
        "authority_reasons": authority.get("reasons"), "authority_failed_checks": authority.get("failed_checks"),
    }
    if authority:
        observed["authority_status"] = "REFUSED" if authority.get("code") else authority.get("authority_result", {}).get("status")
    if request.get("operation") == "evaluate" and result.get("partitions"):
        partition = result["partitions"][0]
        accumulator = partition.get("accumulator")
        observed.update({
            "accumulator": accumulator.get("value") if isinstance(accumulator, dict) else None,
            "partition_status": partition.get("status"),
            "reasons": result.get("reasons"),
        })
    observed["state_unchanged"] = result.get("state") == request.get("input", {}).get("state") and result.get("state_digest") == request.get("input", {}).get("state_digest")
    observed["budget_unchanged"] = result.get("budget_states") == supplied_budget_states(request)
    if reservation_row:
        contributions = reservation_row.get("contributions", [])
        observed["pending_contribution"] = contributions[0]["value"]["value"] if reservation_row["status"] in ("OPEN", "UNKNOWN", "DISPUTED") and contributions else "0"
    if budget and receipt.get("budgets"):
        observed["candidate_accumulator"] = receipt["budgets"][0]["result"]["partitions"][0]["accumulator"]["value"]
    if scenario_id == "access-card-exact-replay":
        original = valid["access-card"][-1]["result"]
        observed.update({
            "decision_digest_equals_original": result.get("decision_digest") == original.get("decision_digest"),
            "transaction_digest_equals_original": result.get("transaction_digest") == original.get("transaction_digest"),
            "budget_revision_unchanged": budget is not None and budget["state"]["core"]["revision"] == budget_result(original)["state"]["core"]["revision"],
        })
    if scenario_id == "supplier-payment-prior-effect-and-distinct-actors":
        permit = result["permit"]
        separation = permit["separation_bases"][0]
        observed.update({
            "budget_decisions": [row["result"]["receipt"]["decision"] for row in result["budget_results"]],
            "prior_effect_binding_ids": [row["binding_id"] for row in permit["prior_effect_bases"]],
            "prior_actor_separation_ids": [row["requirement_id"] for row in permit["separation_bases"]],
            "current_actor": separation["current_act"]["act"]["actor"],
            "prior_actor": separation["prior_act"]["act"]["actor"],
        })
    if scenario_id == "supplier-payment-same-confirmation-and-release-actor":
        basis = detail(result, "SEPARATION")["basis"]
        observed.update({
            "current_actor": basis["current_act"]["act"]["actor"],
            "prior_actor": basis["prior_act"]["act"]["actor"],
            "separation_requirement_id": basis["requirement_id"],
            "budget_unchanged": result.get("budget_results") == [],
        })
    if scenario_id == "supplier-payment-changed-dispatch":
        observed["dispatch_record_added"] = len(result["state"]["dispatches"]) == len(request["input"]["state"]["dispatches"]) + 1
    if scenario_id == "supplier-payment-late-matching-settlement":
        observed["committed_accumulator"] = history_accumulator(result)
    if scenario_id == "supplier-payment-acknowledgement-only":
        retained = request["input"]["event"]["permit"]["budget_revisions"][0]
        proposal = valid["supplier-payment"][5]["result"]
        observed.update({"budget_revision": retained["revision"], "reservation_status": reservation(proposal)["status"]})
    return observed


def validate_scenarios(checks: Checks, specimen: str, responses: list[dict], valid: dict[str, list[dict]]) -> int:
    root = SPECIMENS / specimen
    requests = load(root / "scenarios/requests.json")
    request_by_id = {row["request_id"]: row for row in requests}
    response_by_id = {row["request_id"]: row["result"] for row in responses}
    expectations = load(root / "scenarios/expectations.json")["scenarios"]
    host_only = {"supplier-payment-two-concurrent-proposals", "supplier-payment-stale-second", "supplier-payment-commit-failure"}
    count = 0
    for scenario in expectations:
        scenario_id = scenario["id"]
        if scenario_id in host_only:
            continue
        expected = scenario["expected_assertions"]
        group = f"scenario:{scenario_id}"
        if "trace" in scenario["input"]:
            trace = valid[specimen]
            final = trace[-1]["result"]
            budget = budget_result(final)
            observed = {
                "response_dispositions": [row["result"].get("decision", {}).get("disposition", row["result"]["status"]) for row in trace],
                "final_work_revision": final["state"]["revision"], "final_work_status": final["state"]["status"],
                "final_budget_revision": budget["state"]["core"]["revision"],
                "final_reservation_status": reservation(final)["status"],
                "pending_count": str(sum(row["status"] in ("OPEN", "UNKNOWN", "DISPUTED") for row in budget["state"]["core"]["reservations"])),
                "committed_count": history_accumulator(final),
                "final_committed_accumulator": history_accumulator(final),
            }
        elif scenario_id == "supplier-payment-restart-every-stage":
            trace = valid[specimen]
            replay_request = request_by_id["supplier-payment-settlement-replay"]
            replay_result = response_by_id["supplier-payment-settlement-replay"]
            replay_budget = budget_result(replay_result)
            observed = {
                "checkpoint_index": "restart/checkpoints.json",
                "requires_process_local_history": False,
                "exact_replay": replay_result.get("replay") is True,
                "replay_changes_work_revision": replay_result["state"]["revision"] != replay_request["input"]["state"]["revision"],
                "replay_changes_budget_revision": replay_budget["state"]["core"]["revision"] != budget_result(valid[specimen][-1]["result"])["state"]["core"]["revision"],
            }
            checks.true(group, "checkpoint index exists", (root / observed["checkpoint_index"]).is_file())
            checks.equal(group, "fresh-process result count", sum(bool(row.get("fresh_process_exact")) for row in trace), len(trace))
        else:
            request_id = scenario["input"]["request_id"]
            observed = observed_assertions(scenario_id, response_by_id[request_id], request_by_id[request_id], valid)
        for key, value in expected.items():
            checks.equal(group, key, observed.get(key), value)
        count += 1
    return count


def host_commit_failure(checks: Checks, python_host: list[str], typescript_host: list[str]) -> dict:
    case_path = SPECIMENS / "supplier-payment/host/commit-failure-case.json"
    case = load(case_path)
    envelope = {"protocol": PROTOCOL, "request_id": case["id"], "operation": "host-harness", "input": case["input"]}
    expected = canonical({"protocol": PROTOCOL, "request_id": case["id"], "operation": "host-harness", "result": case["expected"]}) + b"\n"
    actual_python = run(python_host, canonical(envelope) + b"\n")
    actual_typescript = run(typescript_host, canonical(envelope) + b"\n")
    checks.equal("host:commit-failure", "Python exact expected bytes", actual_python, expected)
    checks.equal("host:commit-failure", "TypeScript exact expected bytes", actual_typescript, expected)
    checks.equal("host:commit-failure", "cross-language exact bytes", actual_python, actual_typescript)
    return case["expected"]


def python_host_contention() -> dict:
    sys.path[:0] = [str(PYTHON), str(PYTHON / "vendor")]
    from consumer import Consumer
    from implementation.reference_host import SingleProcessReferenceHost

    supplier = SPECIMENS / "supplier-payment"
    initial = load(supplier / "shared-budget-register-result-derived.json")
    registry_digest = load(supplier / "shared-budget-definition.json")
    proposal_a, proposal_b, stale_b, _retry_b = load(supplier / "contention/requests.json")
    budget_root = [{
        "registry_digest": proposal_a["input"]["event"]["budget_inputs"][0]["registry_digest"],
        "affected_anchors": [registry_digest["anchor"]], "state": initial["state"], "state_digest": initial["state_digest"],
    }]

    def prepared():
        host = SingleProcessReferenceHost(Consumer())
        for instance in ("a", "b"):
            requests = load(supplier / f"instances/{instance}/through-master-change-requests.json")
            host.install(requests[0]["input"], budget_root)
        for instance in ("a", "b"):
            requests = load(supplier / f"instances/{instance}/through-master-change-requests.json")
            for request in requests[1:]:
                submitted = host.submit("sample-buying-organization", request["input"])
                if submitted.get("host_commit", {}).get("disposition") != "COMMITTED":
                    raise RuntimeError(f"Python host setup failed at {request['request_id']}")
        return host

    host = prepared()
    with ThreadPoolExecutor(max_workers=2) as pool:
        contention = list(pool.map(lambda row: host.submit("sample-buying-organization", row["input"]), (proposal_a, proposal_b)))
    committed = sum(row.get("host_commit", {}).get("disposition") == "COMMITTED" for row in contention)
    conflicts = sum(row.get("code") == "REVISION_CONFLICT" for row in contention)

    host = prepared()
    first = host.submit("sample-buying-organization", proposal_a["input"])
    before = host.snapshot("sample-buying-organization", "supplier-payment-instance-b")
    second = host.submit("sample-buying-organization", stale_b["input"])
    after = host.snapshot("sample-buying-organization", "supplier-payment-instance-b")
    return {
        "contention": {"committed": committed, "revision_conflicts": conflicts},
        "stale_revision": {
            "first_disposition": first["host_commit"]["disposition"], "status": second["status"], "code": second["code"],
            "authoritative_registry_revision": second["budget_states"][0]["state"]["core"]["revision"],
            "state_unchanged": before == after,
            "dispatch_performed": "INFERRED_FALSE_BECAUSE_SUBMIT_REFUSED_BEFORE_DISPATCH_API",
        },
    }


NODE_HOST_DRIVER = r"""
import fs from 'node:fs';
import { SingleProcessReferenceHost } from './conformance/work-class/1.0.0-draft.2/typescript/reference-host.ts';
import { selectedCandidate } from './conformance/work-class/1.0.0-draft.2/typescript/schema.ts';
const base = './conformance/work-class/1.0.0-draft.2/specimens/supplier-payment';
const load = path => JSON.parse(fs.readFileSync(`${base}/${path}`, 'utf8'));
const initial = load('shared-budget-register-result-derived.json');
const definition = load('shared-budget-definition.json');
const [proposalA, proposalB, staleB] = load('contention/requests.json');
const budgetRoot = [{registry_digest: proposalA.input.event.budget_inputs[0].registry_digest, affected_anchors: [definition.anchor], state: initial.state, state_digest: initial.state_digest}];
async function prepared() {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  for (const instance of ['a','b']) await host.install(load(`instances/${instance}/through-master-change-requests.json`)[0].input, budgetRoot);
  for (const instance of ['a','b']) for (const request of load(`instances/${instance}/through-master-change-requests.json`).slice(1)) {
    const submitted = await host.submit('sample-buying-organization', request.input);
    if (submitted.host_commit?.disposition !== 'COMMITTED') throw new Error(`TypeScript host setup failed at ${request.request_id}`);
  }
  return host;
}
let host = await prepared();
const contention = await Promise.all([proposalA, proposalB].map(row => host.submit('sample-buying-organization', row.input)));
host = await prepared();
const first = await host.submit('sample-buying-organization', proposalA.input);
const before = await host.snapshot('sample-buying-organization', 'supplier-payment-instance-b');
const second = await host.submit('sample-buying-organization', staleB.input);
const after = await host.snapshot('sample-buying-organization', 'supplier-payment-instance-b');
process.stdout.write(JSON.stringify({
  contention: {committed: contention.filter(row => row.host_commit?.disposition === 'COMMITTED').length, revision_conflicts: contention.filter(row => row.code === 'REVISION_CONFLICT').length},
  stale_revision: {first_disposition: first.host_commit.disposition, status: second.status, code: second.code, authoritative_registry_revision: second.budget_states[0].state.core.revision, state_unchanged: JSON.stringify(before) === JSON.stringify(after), dispatch_performed: 'INFERRED_FALSE_BECAUSE_SUBMIT_REFUSED_BEFORE_DISPATCH_API'}
}));
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=HERE / "CROSS-LANGUAGE-SPECIMEN-VERIFICATION.json")
    args = parser.parse_args()
    python_adapter = [sys.executable, str(PYTHON / "adapter.py")]
    typescript_adapter = ["node", str(TYPESCRIPT / "adapter.ts")]
    python_host = [sys.executable, str(PYTHON / "host_adapter.py")]
    typescript_host = ["node", str(TYPESCRIPT / "host.ts")]
    checks = Checks()
    valid: dict[str, list[dict]] = {}
    scenario_counts = {}

    for specimen in ("access-card", "supplier-payment"):
        root = SPECIMENS / specimen
        requests = (root / "valid-trace/requests.jsonl").read_bytes()
        expected = (root / "valid-trace/results-derived.jsonl").read_bytes()
        py = run(python_adapter, requests)
        ts = run(typescript_adapter, requests)
        checks.equal(f"valid:{specimen}", "Python exact derived bytes", py, expected)
        checks.equal(f"valid:{specimen}", "TypeScript exact derived bytes", ts, expected)
        checks.equal(f"valid:{specimen}", "cross-language exact bytes", py, ts)
        valid[specimen] = lines(py)

        scenario_requests = (root / "scenarios/requests.jsonl").read_bytes()
        py_scenarios = run(python_adapter, scenario_requests)
        ts_scenarios = run(typescript_adapter, scenario_requests)
        checks.equal(f"scenario-stream:{specimen}", "cross-language exact bytes", py_scenarios, ts_scenarios)
        responses = lines(py_scenarios)

        if specimen == "supplier-payment":
            fresh_exact = []
            for request_line, expected_line in zip(requests.splitlines(keepends=True), expected.splitlines(keepends=True), strict=True):
                fresh_py = run(python_adapter, request_line)
                fresh_ts = run(typescript_adapter, request_line)
                exact = fresh_py == expected_line == fresh_ts
                fresh_exact.append(exact)
            for row, exact in zip(valid[specimen], fresh_exact, strict=True):
                row["fresh_process_exact"] = exact
        scenario_counts[specimen] = validate_scenarios(checks, specimen, responses, valid)

    commit_result = host_commit_failure(checks, python_host, typescript_host)
    py_host = python_host_contention()
    ts_host = json.loads(run(["node", "--input-type=module", "--eval", NODE_HOST_DRIVER], b"").decode())
    checks.equal("host:contention", "cross-language summary", py_host, ts_host)
    checks.equal("host:contention", "one commit", py_host["contention"]["committed"], 1)
    checks.equal("host:contention", "one stale conflict", py_host["contention"]["revision_conflicts"], 1)
    checks.equal("host:stale-revision", "first committed", py_host["stale_revision"]["first_disposition"], "COMMITTED")
    checks.equal("host:stale-revision", "second refused", (py_host["stale_revision"]["status"], py_host["stale_revision"]["code"]), ("REFUSED", "REVISION_CONFLICT"))
    checks.equal("host:stale-revision", "authoritative registry revision", py_host["stale_revision"]["authoritative_registry_revision"], "2")
    checks.true("host:stale-revision", "work state unchanged", py_host["stale_revision"]["state_unchanged"])

    manifest = ROOT / "library/work-class-specification/1.0.0-draft.2/contract-manifest.json"
    isolated_manifest = PYTHON / "input/contract-manifest.json"
    checks.equal("pin", "normative manifest hash", sha256(manifest), PIN.removeprefix("sha256:"))
    checks.equal("pin", "isolated manifest hash", sha256(isolated_manifest), PIN.removeprefix("sha256:"))
    checks.equal("pin", "isolated manifest bytes", isolated_manifest.read_bytes(), manifest.read_bytes())
    manifest_value = load(manifest)
    for row in manifest_value["files"]:
        source = manifest.parent / row["path"]
        isolated = PYTHON / "input" / row["path"]
        checks.true(
            "pin:manifested-files", row["path"],
            source.is_file() and isolated.is_file() and sha256(source) == row["sha256"] and isolated.read_bytes() == source.read_bytes(),
        )

    # Specimens added after the first pair carry their own verifier (`verify-specimen.py`), which runs both
    # consumers against the specimen's derived files. Each one is one check here; its JSON report is retained.
    own_verifier_reports = {}
    own_verifiers = {"verify-specimen.py": [], "compare-consumers.py": ["--fresh"]}
    for specimen_root in sorted(SPECIMENS.iterdir()):
        script = next((name for name in own_verifiers if (specimen_root / name).is_file()), None)
        if script is None:
            continue
        completed = subprocess.run([sys.executable, script, *own_verifiers[script]], cwd=specimen_root, capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        stdout = completed.stdout.decode("utf-8", "replace")
        try:
            parsed = json.loads(stdout)
        except ValueError:
            parsed = {"tail": stdout[-2000:]}
        own_verifier_reports[specimen_root.name] = {"script": script, "returncode": completed.returncode, "report": parsed}
        checks.true(f"specimen-verifier:{specimen_root.name}", f"{script} passes", completed.returncode == 0 and not parsed.get("failed"))

    passed = sum(row["passed"] for row in checks.rows)
    report = {
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "candidate_pin": PIN,
        "status": "PASS" if passed == len(checks.rows) else "FAIL",
        "counts": {
            "checks": len(checks.rows), "passed": passed, "failed": len(checks.rows) - passed,
            "valid_trace_requests": {name: len(rows) for name, rows in valid.items()},
            "pure_adapter_scenarios": scenario_counts,
            "host_only_scenarios": 3,
            "manifested_contract_files": len(manifest_value["files"]),
            "own_verifier_specimens": sorted(own_verifier_reports),
        },
        "own_verifier_reports": own_verifier_reports,
        "commands": {
            "verifier": "python3 conformance/work-class/1.0.0-draft.2/review/verify-cross-language-specimens.py",
            "python_adapter": "python3 conformance/work-class/1.0.0-draft.2/python/adapter.py",
            "typescript_adapter": "node conformance/work-class/1.0.0-draft.2/typescript/adapter.ts",
            "python_host_harness": "python3 conformance/work-class/1.0.0-draft.2/python/host_adapter.py",
            "typescript_host_harness": "node conformance/work-class/1.0.0-draft.2/typescript/host.ts",
        },
        "hashes": {
            "contract_manifest": sha256(manifest), "isolated_contract_manifest": sha256(isolated_manifest),
            "python_adapter": sha256(PYTHON / "adapter.py"), "typescript_adapter": sha256(TYPESCRIPT / "adapter.ts"),
            "access_card_artifact_index": sha256(SPECIMENS / "access-card/artifact-index.json"),
            "supplier_payment_artifact_index": sha256(SPECIMENS / "supplier-payment/artifact-index.json"),
            "initial_independent_provenance_record": sha256(HERE / "python-independent-initial.md"),
        },
        "input_hashes": {
            "access_card_valid_requests": sha256(SPECIMENS / "access-card/valid-trace/requests.jsonl"),
            "access_card_valid_expectations": sha256(SPECIMENS / "access-card/valid-trace/results-derived.jsonl"),
            "access_card_scenario_requests": sha256(SPECIMENS / "access-card/scenarios/requests.jsonl"),
            "supplier_payment_valid_requests": sha256(SPECIMENS / "supplier-payment/valid-trace/requests.jsonl"),
            "supplier_payment_valid_expectations": sha256(SPECIMENS / "supplier-payment/valid-trace/results-derived.jsonl"),
            "supplier_payment_scenario_requests": sha256(SPECIMENS / "supplier-payment/scenarios/requests.jsonl"),
        },
        "toolchain": {
            "python": sys.version.split()[0],
            "node": subprocess.run(["node", "--version"], capture_output=True, text=True, check=True).stdout.strip(),
        },
        "host_results": {"contention_and_stale_revision": py_host, "commit_failure": commit_result},
        "specimen_expectation_corrections": [
            {
                "scenario": "supplier-payment-unknown", "field": "reason_codes",
                "before": ["OUTCOME_UNKNOWN"], "after": ["UNKNOWN_OUTCOME"],
                "basis": "LIFE-010 exhaustive decision-reason mapping for EFFECT_OBSERVED/UNKNOWN",
            },
            {
                "scenario": "supplier-payment-unexpected-effect", "field": "occurrence_status",
                "before": "OUTCOME_UNKNOWN", "after": "BLOCKED_DISPUTE",
                "basis": "LIFE-010 conclusive-effect consequence when budget reconciliation is EFFECT_DISPUTED",
            },
            {
                "scenario": "supplier-payment-unexpected-effect", "field": "blocked_partitions",
                "before": [{"anchor": "supplier-payment-cap", "key": [{"type_ref": "b.identity", "value": "supplier-17"}]}],
                "after": [{"anchor": "supplier-payment-cap", "key": None}],
                "basis": "LIFE-010 observed_request null on an inconsistent completion field and RES-WIRE-003 anchor fallback",
            },
        ],
        "sequence_context_assertions": [
            "Acknowledgement-only budget revision and reservation status are read from the retained permit and preceding proposal result because DISPATCH_OBSERVED returns no registry transition.",
            "Replay revision stability compares the replay result with the current final trace roots, not the historical reservation request nested in the replayed event.",
            "A separation withholding proves no registry change by returning no budget result; its response does not duplicate the supplied registry root.",
        ],
        "host_context_gaps": [
            "The reference hosts serialize only within one process and do not prove durable or distributed coordination.",
            "The stale-revision refusal schema omits dispatch_performed; false is inferred because submit refuses before the separate dispatch API is reachable.",
            "The contention test does not prescribe which eligible client wins the serialized commit.",
            "Specimen native effects are supplied evidence records; this verifier does not invoke an external card or payment provider.",
        ],
        "checks": checks.rows,
    }
    args.report.write_bytes(canonical(report) + b"\n")
    print(json.dumps({"report": str(args.report), "status": report["status"], "counts": report["counts"]}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
