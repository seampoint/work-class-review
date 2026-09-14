#!/bin/bash
# One complete verification pass for the current candidate: the corpus check, both reference consumers over every case with
# every actual result compared across languages, the four specimen verifiers, the TypeScript consumer's typecheck and unit
# tests, and the pin-currency control. Reports go to a new run directory; nothing is written into the repository.
set -u
REPO=$(cd "$(dirname "$0")/.." && pwd)
D2=$REPO/conformance/work-class/1.0.0-draft.2
TAG=${1:?usage: scripts/verify.sh <run-name>}
OUT=${WORK_CLASS_RUNS:-$REPO/runs}/$TAG
[ -e "$OUT" ] && { echo "exists: $OUT"; exit 1; }
mkdir -p "$OUT"
export PYTHONDONTWRITEBYTECODE=1
ROLES=AGGREGATE_EVALUATOR,AUTHORITY_EVALUATOR,CHOICE_LOOP_RUNTIME,DEADLINE_RUNTIME,LINEAR_WORK_RUNTIME,PARALLEL_FANOUT_RUNTIME,REFERENCE_SINGLE_PROCESS_CONTENTION,REVIEW_EVIDENCE
failed=()
step() { local name=$1; shift; if "$@" > "$OUT/$name.log" 2>&1; then echo "PASS $name"; else echo "FAIL $name (log: $OUT/$name.log)"; failed+=("$name"); fi; }

step check-corpus node "$D2/runner/check-corpus.mjs"
step corpus-typescript python3 "$D2/runner/run-development.py" --adapter-command "node $D2/typescript/adapter.ts" \
  --adapter-without-shared-budget-command "env WORK_CLASS_ADAPTER_ROLES=$ROLES node $D2/typescript/adapter.ts" \
  --host-command "node $D2/typescript/host.ts" --scratch-root "$OUT/typescript-scratch" --report "$OUT/typescript.json"
step corpus-python python3 "$D2/runner/run-development.py" --adapter-command "python3 $D2/python/adapter.py" \
  --adapter-without-shared-budget-command "env WORK_CLASS_ADAPTER_ROLES=$ROLES python3 $D2/python/adapter.py" \
  --host-command "python3 $D2/python/host_adapter.py" --scratch-root "$OUT/python-scratch" --report "$OUT/python.json"
step compare-consumers python3 - "$OUT" <<'PY'
import json, sys
out = sys.argv[1]
reports = {name: json.load(open(f"{out}/{name}.json")) for name in ("typescript", "python")}
rows = {name: {row["id"]: row for row in report["case_results"]} for name, report in reports.items()}
for name, report in reports.items():
    failing = [row["id"] for row in report["case_results"] if row.get("status") != "PASS"]
    print(name, report["status"], "total", report["total_cases"], "passed", report["passed_cases"], "failing", failing[:20])
ids = sorted(set(rows["typescript"]) | set(rows["python"]))
differing = [case_id for case_id in ids if rows["typescript"].get(case_id, {}).get("actual") != rows["python"].get(case_id, {}).get("actual")]
print("differing actual results:", len(differing), differing[:20])
sys.exit(1 if differing or any(r["status"] != "PASS" for r in reports.values()) else 0)
PY
step specimens-shared bash -c "cd '$D2/review' && python3 verify-cross-language-specimens.py --report '$OUT/specimens.json'"
step specimen-roe-engagement bash -c "cd '$D2/specimens/roe-engagement' && python3 verify-specimen.py"
step specimen-sepsis-surveillance bash -c "cd '$D2/specimens/sepsis-surveillance' && python3 compare-consumers.py --fresh"
step typescript-typecheck bash -c "cd '$D2/typescript' && npm run --silent typecheck"
step typescript-unit-tests bash -c "cd '$D2/typescript' && npm test --silent"
step pin-currency python3 "$D2/runner/check-pin-currency.py"

echo "reports: $OUT"
if [ ${#failed[@]} -eq 0 ]; then echo "verification PASS"; else echo "verification FAIL: ${failed[*]}"; exit 1; fi
