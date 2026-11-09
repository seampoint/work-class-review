#!/usr/bin/env python3
"""Compare independently derived complete assessment records with both adapters."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[2]
sys.path.insert(0, str(BASE / "runner"))
from transport import invoke, PROTOCOL, run_captured

CONSUMERS = {"python": [sys.executable, "-B", str(BASE / "python/adapter.py")],
             "typescript": ["node", str(BASE / "typescript/adapter.ts")]}


def load(path):
    return json.loads(path.read_bytes())


def sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    results = []
    def check(name, actual, expected):
        results.append({"name": name, "passed": actual == expected})
    pin = sha(ROOT / "library/work-class-specification/1.0.0-draft.3/contract-manifest.json")
    index = load(HERE / "artifact-index.json")
    check("candidate pin", index["candidate_pin"], pin)
    for row in index["artifacts"]:
        check("artifact:" + row["path"], sha(HERE / row["path"]), row["sha256"])
    check("source bytes", (HERE / "source-packet.md").read_bytes(),
          (BASE / "review/fixtures/factual-customer-message-review-revision1-source.md").read_bytes())
    authority_input = {"kind": "AUTHORITY", "request": load(HERE / "authority-input.json")}
    authority_expected = load(HERE / "authority-result-derived.json")
    for language, command in CONSUMERS.items():
        check("authority:" + language, invoke(command, "assessment-authority", "evaluate", authority_input,
              300, 64 * 1024 * 1024, str(ROOT)), authority_expected)
    for requests_path in sorted(HERE.rglob("requests.jsonl")):
        name = str(requests_path.parent.relative_to(HERE))
        requests = [json.loads(line) for line in requests_path.read_bytes().splitlines()]
        expected = load(requests_path.parent / "results-derived.json")
        check(name + ":count", len(requests), len(expected))
        wanted = [{"protocol": PROTOCOL, "request_id": row["request_id"], "operation": row["operation"], "result": result}
                  for row, result in zip(requests, expected, strict=True)]
        def stream(item):
            language, command = item
            completed = run_captured(command, requests_path.read_bytes(), cwd=ROOT, timeout=600)
            if completed.returncode:
                raise RuntimeError(language + ": " + completed.stderr.decode("utf-8", "replace")[-1000:])
            return language, [json.loads(line) for line in completed.stdout.splitlines()]
        outputs = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            for language, actual in executor.map(stream, CONSUMERS.items()):
                outputs[language] = actual
                check(name + ":stream:" + language, actual, wanted)
        check(name + ":cross-language", outputs["python"], outputs["typescript"])
        for row, result in zip(requests, expected, strict=True):
            for language, command in CONSUMERS.items():
                check(name + ":fresh:" + language + ":" + row["request_id"],
                    invoke(command, row["request_id"], row["operation"], row["input"], 300, 64 * 1024 * 1024, str(ROOT)), result)
    inventory = load(HERE / "case-inventory.json")
    for row in inventory["cases"]:
        check("case:" + row["id"], sha(HERE / row["path"]), row["raw_sha256"])
    for row in load(HERE / "digest-known-answers.json")["vectors"]:
        # The fixed expected hash is compared with each runtime's exported canonical primitive
        # by focused consumer units. This verifier establishes its frozen preimage inventory.
        check("known-answer-preimage:" + row["id"], bytes.fromhex(row["canonical_utf8_hex"]),
              json.dumps(row["body"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    passed = sum(row["passed"] for row in results)
    print(json.dumps({"candidate_pin": pin, "status": "PASS" if passed == len(results) else "FAIL",
        "qualification": "DEVELOPMENT_RUN_NOT_QUALIFYING", "checks": len(results), "passed": passed,
        "failed": len(results) - passed, "source_cases": len(inventory["cases"]), "results": results}, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
