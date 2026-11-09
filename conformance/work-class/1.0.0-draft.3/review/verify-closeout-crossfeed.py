#!/usr/bin/env python3
"""Feed actual producer state to the other consumer against sealed next judgments."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from corpus_common import canonical_bytes, candidate_pin

HERE = Path(__file__).resolve().parent
AREA = HERE.parent
sys.path.insert(0, str(AREA / 'runner'))
from transport import PROTOCOL, read_json, run_captured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.environ['WORK_CLASS_CHILD_CAPTURE_DIR'] = str(out / 'raw')
    commands = {'python': [sys.executable, '-B', str(AREA / 'python/adapter.py')],
                'typescript': [os.environ['WORK_CLASS_NODE'], str(AREA / 'typescript/adapter.ts')]}
    groups = ['phase3-dispose-closeout', 'phase3-closeout-boundaries',
              'phase3-closeout-replay', 'phase3-review-findings',
              'phase3-mixed-history', 'phase3-disputed-history', 'phase3-pending-identity',
              'phase3-mixed-exclusive-history','phase3-unassessed-actual']
    paths = sorted(p for name in groups for p in (AREA / 'cases' / name).glob('*.json'))
    cases = [json.loads(p.read_bytes()) for p in paths]
    producers = {c['expected']['state_digest']: c for c in cases
                 if c['expected'].get('status') == 'TRANSITION' and not c['expected'].get('replay')}
    pairs = [(producers[c['input']['state_digest']], c) for c in cases
             if c.get('operation') == 'aggregate-step' and
             (c['expected'].get('replay') or c['input']['event']['kind'] in ['RESERVE', 'RENEW']) and
             c['input'].get('state_digest') in producers and
             producers[c['input']['state_digest']]['id'] != c['id']]
    if not pairs:
        raise RuntimeError('No source-bound crossfeed pairs found')
    guarded = paths + [Path(__file__).resolve(), HERE / 'corpus_common.py']
    for directory in [AREA / 'python', AREA / 'typescript',
                      AREA.parents[2] / 'library/work-class-specification/1.0.0-draft.3']:
        guarded.extend(p for p in directory.rglob('*') if p.is_file() and
                       not {'node_modules', '__pycache__'}.intersection(p.parts))
    def guard():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(guarded))}
    guarded.extend(Path(command[0]).resolve() for command in commands.values())
    before = guard()
    (out / 'guard-before.json').write_text(json.dumps(before, indent=2) + '\n')
    def execute(language, case, value, request_id):
        payload = canonical_bytes({'protocol': PROTOCOL, 'request_id': request_id,
                                   'operation': case['operation'], 'input': value}) + b'\n'
        result = run_captured(commands[language], payload, cwd=str(AREA), timeout=600, new_session=True)
        if result.returncode != 0 or len(result.stdout.splitlines()) != 1:
            raise RuntimeError(f'{language} process failed for {case["id"]}')
        line = result.stdout.rstrip(b'\n')
        envelope = read_json(line.decode())
        if canonical_bytes(envelope) != line or envelope.get('protocol') != PROTOCOL or envelope.get('request_id') != request_id or envelope.get('operation') != case['operation']:
            raise RuntimeError('Noncanonical or mismatched transport envelope')
        if envelope['result'] != case['expected']:
            raise RuntimeError(f'{language} differs from sealed expected judgment: {case["id"]}')
        return envelope['result']
    rows = []
    with (out / 'RESULTS.jsonl').open('x') as results:
        for producer, receiver in pairs:
            for source, target in [('python', 'typescript'), ('typescript', 'python')]:
                actual = execute(source, producer, producer['input'], 'crossfeed-producer')
                supplied = copy.deepcopy(receiver['input'])
                # Equality is checked, not used to learn or rewrite an expectation.
                if actual['state'] != supplied['state'] or actual['state_digest'] != supplied['state_digest']:
                    raise RuntimeError('Producer does not match independently sealed receiver basis')
                supplied['state'] = actual['state']
                supplied['state_digest'] = actual['state_digest']
                received = execute(target, receiver, supplied, 'crossfeed-receiver')
                row = {'source': source, 'target': target, 'producer_case': producer['id'],
                       'receiver_case': receiver['id'], 'receiver_event': supplied['event']['kind'],
                       'status': 'PASS', 'producer_actual': actual, 'receiver_actual': received}
                results.write(json.dumps(row, separators=(',', ':')) + '\n')
                rows.append({k: v for k, v in row.items() if not k.endswith('_actual')})
    after = guard()
    (out / 'guard-after.json').write_text(json.dumps(after, indent=2) + '\n')
    report = {'status': 'PASS' if before == after else 'FAIL', 'candidate_pin': candidate_pin(),
              'claim': 'BOUNDED_CROSS_CONSUMER_STATE_READBACK_NOT_QUALIFICATION',
              'pairs': len(pairs), 'directions_checked': len(rows), 'native_processes': 2 * len(rows),
              'source_guard_unchanged': before == after, 'rows': rows}
    (out / 'REPORT.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
