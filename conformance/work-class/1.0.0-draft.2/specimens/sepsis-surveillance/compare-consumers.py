#!/usr/bin/env python3
"""Compare the derived sepsis specimen against both draft-2 adapters.

Streams valid-trace and scenario requests through each adapter, compares canonical bytes line by line with the
derived results, and optionally re-runs every request in a fresh adapter process through runner/transport.py
(restart at every stage). Reports differences; never writes expected files.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT / "conformance/work-class/1.0.0-draft.2"
sys.path.insert(0, str(BASE / "runner"))
import transport  # noqa: E402

ADAPTERS = {"python": ["python3", "python/adapter.py"], "typescript": ["node", "typescript/adapter.ts"]}


def diff_paths(expected, actual, path="", limit=6):
    out = []
    if type(expected) is not type(actual):
        return [f"{path or '/'}: derived {json.dumps(expected)[:160]} | actual {json.dumps(actual)[:160]}"]
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                out.append(f"{path}/{key}: absent in derived, actual {json.dumps(actual[key])[:120]}")
            elif key not in actual:
                out.append(f"{path}/{key}: absent in actual, derived {json.dumps(expected[key])[:120]}")
            else:
                out.extend(diff_paths(expected[key], actual[key], f"{path}/{key}", limit))
            if len(out) >= limit:
                return out[:limit]
        return out
    if isinstance(expected, list):
        if len(expected) != len(actual):
            out.append(f"{path}: derived length {len(expected)} | actual length {len(actual)}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            out.extend(diff_paths(left, right, f"{path}/{index}", limit))
            if len(out) >= limit:
                return out[:limit]
        return out
    if expected != actual:
        return [f"{path or '/'}: derived {json.dumps(expected)[:160]} | actual {json.dumps(actual)[:160]}"]
    return []


def stream(command, payload: bytes) -> list[bytes]:
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "TZ": "UTC", "LANG": "C.UTF-8"}
    completed = subprocess.run(command, cwd=BASE, input=payload, capture_output=True, check=False, env=environment)
    if completed.returncode:
        print(f"  adapter exited {completed.returncode}: {completed.stderr.decode(errors='replace')[:800]}")
    return completed.stdout.splitlines()


def compare(name: str, requests_path: Path, expected_path: Path, fresh: bool) -> dict:
    requests = requests_path.read_bytes().splitlines()
    expected = expected_path.read_bytes().splitlines()
    summary = {}
    for adapter, command in ADAPTERS.items():
        actual = stream(command, requests_path.read_bytes())
        exact = 0
        rows = []
        for index, request_line in enumerate(requests):
            request = json.loads(request_line)
            derived = json.loads(expected[index])
            got = json.loads(actual[index]) if index < len(actual) else None
            if index < len(actual) and actual[index] == expected[index]:
                exact += 1
                continue
            rows.append((request["request_id"], diff_paths(derived, got) if got is not None else ["no response line"]))
        summary[adapter] = {"exact": exact, "total": len(requests), "differences": rows}
        print(f"[{name}] {adapter}: {exact}/{len(requests)} exact derived bytes")
        for request_id, paths in rows:
            print(f"  {request_id}")
            for row in paths:
                print(f"    {row}")
        if fresh:
            fresh_exact = 0
            for index, request_line in enumerate(requests):
                request = json.loads(request_line)
                try:
                    result = transport.invoke(command, request["request_id"], request["operation"], request["input"], 120.0, 64_000_000, str(BASE))
                    envelope = {"protocol": transport.PROTOCOL, "request_id": request["request_id"], "operation": request["operation"], "result": result}
                    if (transport.canonical(envelope) + "\n").encode() == expected[index] + b"\n":
                        fresh_exact += 1
                except RuntimeError as error:
                    print(f"  fresh-process {request['request_id']}: {error}")
            summary[adapter]["fresh_exact"] = fresh_exact
            print(f"[{name}] {adapter}: {fresh_exact}/{len(requests)} exact in fresh processes")
    python_lines = stream(ADAPTERS["python"], requests_path.read_bytes())
    typescript_lines = stream(ADAPTERS["typescript"], requests_path.read_bytes())
    cross = sum(1 for left, right in zip(python_lines, typescript_lines) if left == right)
    print(f"[{name}] cross-language: {cross}/{len(requests)} identical response lines")
    for index, (left, right) in enumerate(zip(python_lines, typescript_lines)):
        if left != right:
            request_id = json.loads(requests[index])["request_id"]
            print(f"  {request_id}")
            for row in diff_paths(json.loads(left), json.loads(right)):
                print(f"    python vs typescript {row}")
    summary["cross_language_identical"] = cross
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true", help="also run every request in a fresh adapter process")
    args = parser.parse_args()
    valid = compare("valid-trace", HERE / "valid-trace/requests.jsonl", HERE / "valid-trace/results-derived.jsonl", args.fresh)
    scenarios = compare("scenarios", HERE / "scenarios/requests.jsonl", HERE / "scenarios/results-derived.jsonl", args.fresh)
    ok = all(valid[a]["exact"] == valid[a]["total"] and scenarios[a]["exact"] == scenarios[a]["total"] for a in ADAPTERS)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
