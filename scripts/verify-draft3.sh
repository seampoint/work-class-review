#!/bin/bash
# Reproduce the draft3 development suite at one unchanged candidate.
set -u
REPO=$(cd "$(dirname "$0")/.." && pwd)
D3=$REPO/conformance/work-class/1.0.0-draft.3
TAG=${1:?usage: scripts/verify-draft3.sh <fresh-run-name>}
OUT=${WORK_CLASS_RUNS:-$REPO/runs}/$TAG
[ -e "$OUT" ] && { echo "exists: $OUT"; exit 1; }
mkdir -p "$OUT"
export PYTHONDONTWRITEBYTECODE=1
CASE_TIMEOUT=${WORK_CLASS_CASE_TIMEOUT_SECONDS:-600}
ROLES=AGGREGATE_EVALUATOR,AUTHORITY_EVALUATOR,CHOICE_LOOP_RUNTIME,DEADLINE_RUNTIME,FLOW_TRANSITIONS,HOLDINGS_TRANSITIONS,LINEAR_WORK_RUNTIME,PARALLEL_FANOUT_RUNTIME,REFERENCE_SINGLE_PROCESS_CONTENTION,REVIEW_EVIDENCE,RESERVATION_TRANSITIONS
without_role() { python3 -c 'import sys;print(",".join(r for r in sys.argv[1].split(",") if r!=sys.argv[2]))' "$ROLES" "$1"; }
NO_RESERVATION=$(without_role RESERVATION_TRANSITIONS)
NO_HOLDINGS=$(without_role HOLDINGS_TRANSITIONS)
NO_FLOW=$(without_role FLOW_TRANSITIONS)
failed=()
step() {
    local name=$1
    shift
    if "$@" > "$OUT/$name.log" 2>&1; then record_step_status "$name" 0; else record_step_status "$name" "$?"; fi
}
record_step_status() {
    local name=$1 status=$2
    if [ "$status" -eq 0 ]; then echo "PASS $name"; else echo "FAIL $name (log: $OUT/$name.log)"; failed+=("$name"); fi
}
guard() {
    python3 - "$REPO" "$OUT" "$1" <<'PY'
from pathlib import Path
import hashlib,json,platform,sys
root,out,phase=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
area=root/'conformance/work-class/1.0.0-draft.3'
paths=[]
for selected in (root/'library/work-class-specification/1.0.0-draft.3',area/'cases',area/'specimens',area/'python',area/'typescript',area/'review',area/'runner',area/'suite',area/'host-demo'):
    for path in selected.rglob('*'):
        if path.is_file() and not {'__pycache__','node_modules'}.intersection(path.parts) and not any(path.is_relative_to(area/'review'/name) for name in ('paper','records')):paths.append(path)
paths.append(root/'scripts/verify-draft3.sh')
value={str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(paths))}
(out/('guard-'+phase+'.json')).write_text(json.dumps(value,indent=2)+'\n')
if phase=='before':
    (out/'runtime.json').write_text(json.dumps({'python':sys.version,'platform':platform.platform(),'sqlite':__import__('sqlite3').sqlite_version},indent=2)+'\n')
else:
    before=json.loads((out/'guard-before.json').read_text())
    if before!=value:raise SystemExit('Source/input/runtime guard changed during verification')
print('guard',phase,len(value),'files')
PY
}

step guard-before guard before
step runtime-node node --version
step verification-time-budget printf 'Per fresh-process corpus case: %s seconds\nThis is a verification allowance, not a production latency claim.\n' "$CASE_TIMEOUT"
step contract-schemas node "$D3/review/check-contract-schemas.mjs"
step check-corpus node "$D3/runner/check-corpus.mjs"
# Reject stale executable inputs, including C3 and encoded artifacts, before any
# consumer can return a masking compatibility error or accidental expected refusal.
if ! python3 "$D3/review/candidate_pin_preflight.py" --report "$OUT/candidate-pin-preflight.json" > "$OUT/candidate-pin-preflight.log" 2>&1; then
    echo "FAIL candidate-pin-preflight (log: $OUT/candidate-pin-preflight.log)"
    step guard-after guard after
    echo "verification FAIL: candidate-pin-preflight"
    exit 1
fi
echo "PASS candidate-pin-preflight"
corpus_typescript() {
    python3 "$D3/runner/run-development.py" --adapter-command "node $D3/typescript/adapter.ts" \
    --adapter-without-reservation-command "env WORK_CLASS_ADAPTER_ROLES=$NO_RESERVATION node $D3/typescript/adapter.ts" \
    --adapter-without-holdings-command "env WORK_CLASS_ADAPTER_ROLES=$NO_HOLDINGS node $D3/typescript/adapter.ts" \
    --adapter-without-flow-command "env WORK_CLASS_ADAPTER_ROLES=$NO_FLOW node $D3/typescript/adapter.ts" \
    --host-command "node $D3/typescript/host.ts" --scratch-root "$OUT/typescript-scratch" --report "$OUT/typescript.json" --timeout "$CASE_TIMEOUT" --maximum-output 33554432
}
corpus_python() {
    python3 "$D3/runner/run-development.py" --adapter-command "python3 $D3/python/adapter.py" \
    --adapter-without-reservation-command "env WORK_CLASS_ADAPTER_ROLES=$NO_RESERVATION python3 $D3/python/adapter.py" \
    --adapter-without-holdings-command "env WORK_CLASS_ADAPTER_ROLES=$NO_HOLDINGS python3 $D3/python/adapter.py" \
    --adapter-without-flow-command "env WORK_CLASS_ADAPTER_ROLES=$NO_FLOW python3 $D3/python/adapter.py" \
    --host-command "python3 $D3/python/host_adapter.py" --scratch-root "$OUT/python-scratch" --report "$OUT/python.json" --timeout "$CASE_TIMEOUT" --maximum-output 33554432
}
run_corpora() {
    case "${WORK_CLASS_PARALLEL_CONSUMERS:-0}" in
        0)
            step corpus-typescript corpus_typescript
            step corpus-python corpus_python
            ;;
        1)
            corpus_typescript > "$OUT/corpus-typescript.log" 2>&1 &
            local typescript_pid=$!
            corpus_python > "$OUT/corpus-python.log" 2>&1 &
            local python_pid=$!
            # Keep both statuses in the parent; background step() would lose failed[].
            if wait "$typescript_pid"; then record_step_status corpus-typescript 0; else record_step_status corpus-typescript "$?"; fi
            if wait "$python_pid"; then record_step_status corpus-python 0; else record_step_status corpus-python "$?"; fi
            ;;
        *) echo "WORK_CLASS_PARALLEL_CONSUMERS must be 0 or 1"; exit 2 ;;
    esac
}
run_corpora
step compare-consumers python3 - "$OUT" <<'PY'
import json,sys
out=sys.argv[1]
reports={name:json.load(open(f'{out}/{name}.json')) for name in ('typescript','python')}
rows={name:{row['id']:row for row in report['case_results']} for name,report in reports.items()}
ids=sorted(set(rows['typescript'])|set(rows['python']))
differing=[case_id for case_id in ids if rows['typescript'].get(case_id,{}).get('actual')!=rows['python'].get(case_id,{}).get('actual')]
print('different complete actual results',len(differing),differing[:20])
for name,report in reports.items():print(name,report['status'],report['passed_cases'],report['total_cases'])
raise SystemExit(bool(differing) or any(report['status']!='PASS' for report in reports.values()))
PY
step specimens python3 "$D3/review/verify-cross-language-specimens.py" --report "$OUT/specimens.json"
step typescript-typecheck bash -c 'cd "$1" && npm run --silent typecheck' _ "$D3/typescript"
step typescript-unit-tests bash -c 'cd "$1" && npm test --silent' _ "$D3/typescript"
step python-unit-tests python3 -B -m unittest discover -s "$D3/python/tests" -v
step durable-host python3 -B "$D3/host-demo/run_demo.py" --output "$OUT/durable"
step durable-recovery python3 -B "$D3/host-demo/recovery_demo.py" --output "$OUT/recovery"
step bank-duty python3 -B "$D3/host-demo/run_duty_demo.py" --output "$OUT/duty"
step guard-after guard after
echo "reports: $OUT"
if [ ${#failed[@]} -eq 0 ]; then echo "verification PASS"; else echo "verification FAIL: ${failed[*]}"; exit 1; fi
