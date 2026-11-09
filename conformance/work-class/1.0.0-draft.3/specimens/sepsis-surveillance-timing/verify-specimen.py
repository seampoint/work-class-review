#!/usr/bin/env python3
"""Compare both adapters with frozen, independently constructed specimen bytes.

Every request runs in a stream and a fresh process. Checkpoint probes replay an
original event against each frozen checkpoint and use its retained replay result.
The verifier writes reports and failure evidence only outside the specimen.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT / "conformance/work-class/1.0.0-draft.3"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.3"
PREFIX = b"seampoint.work-class/1.0.0-draft.3/"
ADAPTERS = {"python": [sys.executable, "python/adapter.py"], "typescript": ["node", "typescript/adapter.ts"]}
sys.path.insert(0, str(BASE / "runner"))
from transport import run_captured  # noqa: E402
sys.path.insert(0, str(BASE / "review"))
from verification_output import output_directory  # noqa: E402


def canonical(value):
    if isinstance(value, dict):
        return "{" + ",".join(canonical(key) + ":" + canonical(value[key]) for key in sorted(value, key=lambda key: key.encode("utf-16-be"))) + "}"
    if isinstance(value, list):
        return "[" + ",".join(canonical(item) for item in value) + "]"
    if value is None or isinstance(value, (str, bool)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raise ValueError("restricted JSON excludes numbers")


def encoded(value):
    return canonical(value).encode("utf-8") + b"\n"


def read_json(data):
    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out

    def number(value):
        raise ValueError("forbidden JSON number: " + value)

    return json.loads(data, object_pairs_hook=pairs, parse_int=number, parse_float=number, parse_constant=number)


def load(path):
    return read_json(path.read_bytes())


def artifact_payload(path):
    data = path.read_bytes()
    if data != encoded(read_json(data)):
        raise ValueError("noncanonical stored artifact: " + str(path))
    return data[:-1]


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest(kind, value):
    return sha(PREFIX + kind.encode() + b"\n" + encoded(value)[:-1])


def envelope(request_id, operation, value, member="input"):
    return {"protocol": PROTOCOL, "request_id": request_id, "operation": operation, member: value}


def frozen_suite(name):
    requests = (HERE / name / "requests.jsonl").read_bytes().splitlines(keepends=True)
    expected = (HERE / name / "results-derived.jsonl").read_bytes().splitlines(keepends=True)
    if len(requests) != len(expected):
        raise ValueError(name + " has mismatched fixture counts")
    for left, right in zip(requests, expected):
        if encoded(read_json(left)) != left or encoded(read_json(right)) != right:
            raise ValueError(name + " contains noncanonical fixture bytes")
    return list(zip(requests, expected))


def suites(pin):
    out = {name: frozen_suite(name) for name in ("valid-trace", "scenarios")}
    schema = []
    artifacts = [("WORK_CLASS", "work-class-definition", HERE / "work-class.json"),
                 ("AGGREGATE_DEFINITION", "aggregate-definition", HERE / "alert-count-definition.json")]
    artifacts += [("AUTHORITY_DEFINITION", "authority-definition", path) for path in sorted((HERE / "authority").glob("*-definition.json"))]
    for kind, domain, path in artifacts:
        request_id = "schema-" + path.stem
        value = {"kind": kind, "specification_pin": pin, "artifact_bytes_base64": base64.b64encode(artifact_payload(path)).decode()}
        schema.append((encoded(envelope(request_id, "validate", value)), encoded(envelope(request_id, "validate", {"status": "ACCEPTED", "digest": digest(domain, load(path))}, "result"))))
    out["schema"] = schema
    readback_input = {"kind": "WORK_CLASS", "specification_pin": pin, "artifact_bytes_base64": base64.b64encode(artifact_payload(HERE / "work-class.json")).decode()}
    out["readback"] = [(encoded(envelope("readback-work-class", "readback", readback_input)), encoded(envelope("readback-work-class", "readback", load(HERE / "readback-derived.json"), "result")))]
    authority = []
    for path in sorted((HERE / "authority").glob("*-input.json")):
        request_id = "evaluate-" + path.stem.removesuffix("-input")
        expected_path = path.with_name(path.name.replace("-input.json", "-result-derived.json"))
        authority.append((encoded(envelope(request_id, "evaluate", {"kind": "AUTHORITY", "request": load(path)})), encoded(envelope(request_id, "evaluate", load(expected_path), "result"))))
    out["authority"] = authority

    original = [tuple(read_json(value) for value in pair) for name in ("valid-trace", "scenarios") for pair in out[name]]
    events = {digest("runtime-event", request["input"]["event"]): request["input"]["event"] for request, _ in original if request["operation"] == "step"}
    deploys = {result["result"]["state_digest"]: (request, result) for request, result in original if request["operation"] == "deploy" and result["result"]["status"] == "DEPLOYED"}
    definition = load(HERE / "work-class.json")
    checkpoints = []
    for index, row in enumerate(load(HERE / "restart/checkpoints.json")["checkpoints"]):
        state = load(HERE / row["path"])
        request_id = "checkpoint-" + str(index + 1)
        if state["revision"] == "0":
            request, result = deploys[row["state_digest"]]
            checkpoints.append((encoded({**request, "request_id": request_id}), encoded({**result, "request_id": request_id})))
            continue
        receipt = state["receipts"][-1]
        replay = next(item for item in state["replays"] if item["event_id"] == receipt["event_id"])
        value = {"definition": definition, "definition_digest": digest("work-class-definition", definition),
                 "profile": state["profile"], "role": state["role"], "specification_pin": pin,
                 "state": state, "state_digest": row["state_digest"], "event": events[replay["event_digest"]]}
        expected = {"status": "STEP", "profile": state["profile"], "role": state["role"],
                    "decision": replay["decision"], "decision_digest": replay["decision_receipt_digest"],
                    "permit": replay["permit"], "budget_results": replay["budget_results"], "state": state,
                    "state_digest": row["state_digest"], "transition_state_digest": replay["transition_state_digest"],
                    "transaction_digest": replay["transaction_digest"], "replay": True}
        checkpoints.append((encoded(envelope(request_id, "step", value)), encoded(envelope(request_id, "step", expected, "result"))))
    out["checkpoints"] = checkpoints
    return out


def short(value):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= 220 else text[:217] + "..."


def difference(expected, actual, path=""):
    if type(expected) is not type(actual):
        return {"pointer": path or "/", "expected": short(expected), "actual": short(actual)}
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in expected or key not in actual:
                return {"pointer": pointer, "expected": short(expected[key]) if key in expected else "<absent>", "actual": short(actual[key]) if key in actual else "<absent>"}
            found = difference(expected[key], actual[key], pointer)
            if found:
                return found
    elif isinstance(expected, list):
        for index, (left, right) in enumerate(zip(expected, actual)):
            found = difference(left, right, path + "/" + str(index))
            if found:
                return found
        if len(expected) != len(actual):
            return {"pointer": path or "/", "expected_length": len(expected), "actual_length": len(actual)}
    elif expected != actual:
        return {"pointer": path or "/", "expected": short(expected), "actual": short(actual)}
    return None


def execute(command, payload, timeout):
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "TZ": "UTC", "LANG": "C.UTF-8"})
    error = None
    try:
        process = run_captured(command, payload, cwd=BASE, timeout=timeout, env=environment, new_session=True)
        stdout, stderr = process.stdout, process.stderr
    except subprocess.TimeoutExpired as expired:
        stdout, stderr = expired.output or b"", expired.stderr or b""
        error = "TIMEOUT"
    if error is None and process.returncode:
        error = "PROCESS_EXIT_" + str(process.returncode)
    if len(stdout) > 64_000_000 or len(stderr) > 64_000_000:
        error = "OUTPUT_LIMIT"
    return stdout, stderr, error


def compare_rows(adapter, mode, name, rows, output, output_dir, suffix, process_error):
    actual = output.splitlines(keepends=True)
    failures = []
    exact = 0
    for index, (request, expected) in enumerate(rows):
        response = actual[index] if index < len(actual) else b""
        if response == expected:
            exact += 1
            continue
        failure = {"request_id": read_json(request)["request_id"], "index": index + 1}
        try:
            found = difference(read_json(expected), read_json(response))
            if found:
                failure["smallest_difference"] = found
            else:
                failure["error"] = "NONCANONICAL_OUTPUT"
                failure["first_different_byte"] = next((i for i, pair in enumerate(zip(expected, response)) if pair[0] != pair[1]), min(len(expected), len(response)))
        except (ValueError, UnicodeError) as error:
            failure["error"] = "MALFORMED_OR_MISSING_RESPONSE: " + str(error)
        stem = adapter + "-" + mode + "-" + name + "-" + str(suffix + index + 1)
        for ending, data in (("request.json", request), ("expected.json", expected), ("actual.json", response)):
            (output_dir / (stem + "-" + ending)).write_bytes(data)
        failure["evidence_prefix"] = str(output_dir / stem)
        failures.append(failure)
        print(adapter + " " + mode + " " + name + ": " + json.dumps(failure, ensure_ascii=False), file=sys.stderr, flush=True)
    if len(actual) != len(rows):
        failures.append({"error": "OUTPUT_LINE_COUNT", "expected": len(rows), "actual": len(actual)})
        (output_dir / (adapter + "-" + mode + "-" + name + "-" + str(suffix) + "-output.bin")).write_bytes(output)
    if process_error:
        failures.append({"error": process_error})
    return exact, failures


def snapshot(paths):
    return {str(path.relative_to(ROOT)): sha(path.read_bytes()) if path.is_file() else "MISSING" for path in sorted(set(paths))}


def tree_files(roots):
    return [path for root in roots for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts]


def consumer_files():
    return [path for path in tree_files([BASE / "python", BASE / "typescript"])
            if not {"node_modules", "input"}.intersection(path.relative_to(BASE).parts)
            and path.suffix in {".py", ".ts", ".json"}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--consumer-inventory", type=Path)
    parser.add_argument("--timeout", type=float, default=120.0, help="fresh-process timeout in seconds; a stream receives this times its request count")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_dir = (args.output_dir or ROOT / "runs/2026-10-07-timing-freshness" / ("standalone-sepsis-" + stamp + "-" + str(os.getpid()))).resolve()
    try:
        output_dir = output_directory(output_dir, ROOT)
    except ValueError as error:
        parser.error(str(error))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "RETENTION.md").write_text("Retain this directory as local verification evidence: complete failure inputs, expected and actual bytes, stderr, hash snapshots and JSON reports. Frozen specimen files are never written by the verifier.\n")
    index = load(HERE / "artifact-index.json")
    fixture_paths = tree_files([HERE])
    consumer_inventory = json.loads(args.consumer_inventory.read_text()) if args.consumer_inventory else None
    consumer_paths = [ROOT / row["path"] for row in consumer_inventory["files"]] if consumer_inventory else consumer_files()
    contract_roots = [ROOT / name for name in ("library/work-class-specification/1.0.0-draft.3", "conformance/work-class/1.0.0-draft.3/python/input")]
    contract_paths = tree_files(contract_roots)
    before = {"fixtures": snapshot(fixture_paths), "consumers": snapshot(consumer_paths), "contract": snapshot(contract_paths)}
    index_errors = [row["path"] for row in index["files"] if sha((HERE / row["path"]).read_bytes()) != row["sha256"]]
    inventory_errors = [row["path"] for row in consumer_inventory["files"] if before["consumers"][row["path"]].removeprefix("sha256:") != row["sha256"].removeprefix("sha256:")] if consumer_inventory else []
    if index_errors or inventory_errors:
        raise ValueError("frozen input mismatch: " + json.dumps({"fixtures": index_errors, "consumers": inventory_errors}))
    all_suites = suites(index["candidate_pin"])
    report = {"candidate_pin": index["candidate_pin"], "expected_source": "INDEPENDENT_FIXED_CONSTRUCTOR_AND_RETAINED_CHECKPOINT_REPLAYS",
              "output_directory": str(output_dir), "consumer_inventory": str(args.consumer_inventory.resolve()) if args.consumer_inventory else "AUTO_SOURCE_SNAPSHOT",
              "counts": {name: len(rows) for name, rows in all_suites.items()},
              "refusal_count": sum(read_json(expected)["result"]["status"] == "REFUSED" for rows in all_suites.values() for _, expected in rows),
              "request_sha256": {name: sha(b"".join(request for request, _ in rows)) for name, rows in all_suites.items()},
              "expected_sha256": {name: sha(b"".join(expected for _, expected in rows)) for name, rows in all_suites.items()},
              "hashes_before": before, "results": []}
    started = time.monotonic()
    for mode in ("stream", "fresh"):
        for adapter, command in ADAPTERS.items():
            for name, rows in all_suites.items():
                exact = 0
                failures = []
                stderr_reports = []
                groups = [rows] if mode == "stream" else [[row] for row in rows]
                for offset, group in enumerate(groups):
                    stdout, stderr, error = execute(command, b"".join(request for request, _ in group), args.timeout * len(group))
                    matched, found = compare_rows(adapter, mode, name, group, stdout, output_dir, offset if mode == "fresh" else 0, error)
                    exact += matched
                    failures += found
                    if stderr:
                        path = output_dir / (adapter + "-" + mode + "-" + name + "-" + str(offset) + "-stderr.txt")
                        path.write_bytes(stderr)
                        stderr_reports.append({"path": str(path), "sha256": sha(stderr), "bytes": len(stderr), "text": stderr[:1600].decode(errors="replace")})
                summary = {"adapter": adapter, "mode": mode, "suite": name, "exact": exact, "total": len(rows), "failures": failures, "stderr": stderr_reports}
                report["results"].append(summary)
                print(adapter + " " + mode + " " + name + ": " + str(exact) + "/" + str(len(rows)) + " exact; " + str(len(failures)) + " failures", file=sys.stderr, flush=True)
                (output_dir / "report.partial.json").write_text(json.dumps(report, indent=2) + "\n")
    after = {"fixtures": snapshot(tree_files([HERE])), "consumers": snapshot(consumer_paths if consumer_inventory else consumer_files()), "contract": snapshot(tree_files(contract_roots))}
    report["hashes_after"] = after
    report["changed_files"] = [path for section in before for path in sorted(set(before[section]) | set(after[section])) if before[section].get(path) != after[section].get(path)]
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["status"] = "PASS" if not report["changed_files"] and all(not row["failures"] for row in report["results"]) else "FAIL"
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
