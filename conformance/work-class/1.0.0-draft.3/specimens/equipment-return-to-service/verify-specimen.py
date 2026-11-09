#!/usr/bin/env python3
"""Compare the source specimen with both consumers without changing its oracle."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[2]
sys.path.insert(0, str(BASE / 'runner'))
from transport import invoke, PROTOCOL, run_captured

CONSUMERS = {
    'python': [sys.executable, '-B', str(BASE / 'python/adapter.py')],
    'typescript': ['node', str(BASE / 'typescript/adapter.ts')],
}


def load(path):
    return json.loads(path.read_bytes())


def sha(path):
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rows = []

    def check(name, actual, expected):
        row = {'name': name, 'passed': actual == expected}
        if not row['passed']:
            row['actual_digest'] = sha_value(actual)
            row['expected_digest'] = sha_value(expected)
        rows.append(row)

    pin = sha(ROOT / 'library/work-class-specification/1.0.0-draft.3/contract-manifest.json')
    index = load(HERE / 'artifact-index.json')
    check('current contract pin', index['candidate_pin'], pin)
    for row in index['artifacts']:
        check('artifact:' + row['path'], sha(HERE / row['path']), row['sha256'])
    source = HERE / '../../review/fixtures/equipment-return-to-service-revision3-source.txt'
    check('original source bytes', (HERE / 'source-packet.txt').read_bytes(), source.read_bytes())

    singles = [
        ('authority', 'evaluate', {'kind': 'AUTHORITY', 'request': load(HERE / 'authority-input.json')},
         load(HERE / 'authority-result-derived.json')),
        ('correction', 'check-evidence', load(HERE / 'correction/input.json'), load(HERE / 'correction/result-derived.json')),
        ('new approval correction', 'check-evidence', load(HERE / 'correction/new-approval-input.json'),
         load(HERE / 'correction/new-approval-result-derived.json')),
        ('readback', 'readback', {'kind': 'WORK_CLASS', 'specification_pin': pin,
         'artifact_bytes_base64': base64.b64encode((HERE / 'work-class.json').read_bytes().rstrip(b'\n')).decode()},
         load(HERE / 'readback-derived.json')),
    ]
    for name, operation, supplied, expected in singles:
        for language, command in CONSUMERS.items():
            actual = invoke(command, name.replace(' ', '-'), operation, supplied, 120, 64 * 1024 * 1024, str(ROOT))
            check(name + ':' + language, actual, expected)

    traces = sorted(HERE.rglob('requests.jsonl'))
    for path in traces:
        name = str(path.parent.relative_to(HERE))
        requests = [json.loads(line) for line in path.read_bytes().splitlines()]
        expected = load(path.parent / 'results-derived.json')
        check(name + ':request count', len(requests), len(expected))
        payload = path.read_bytes()

        def run_stream(item):
            language, command = item
            completed = run_captured(command, payload, cwd=ROOT, timeout=300)
            if completed.returncode:
                raise RuntimeError(language + ': ' + completed.stderr.decode('utf-8', 'replace')[-1000:])
            responses = [json.loads(line) for line in completed.stdout.splitlines()]
            wanted = [{'protocol': PROTOCOL, 'request_id': request['request_id'],
                       'operation': request['operation'], 'result': result}
                      for request, result in zip(requests, expected, strict=True)]
            return language, responses, wanted

        outputs = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            for language, responses, wanted in executor.map(run_stream, CONSUMERS.items()):
                check(name + ':' + language + ':stream', responses, wanted)
                outputs[language] = responses
        check(name + ':cross-language', outputs['python'], outputs['typescript'])
        # Each request supplies its full prior state. A new process must admit that
        # checkpoint independently of the stream's earlier requests.
        for request, result in zip(requests, expected, strict=True):
            for language, command in CONSUMERS.items():
                actual = invoke(command, request['request_id'], request['operation'], request['input'],
                                120, 64 * 1024 * 1024, str(ROOT))
                check(name + ':' + language + ':fresh:' + request['request_id'], actual, result)
        if name in {'valid-trace', 'fresh-instance'}:
            check(name + ':final work state', expected[-1]['state'], load(path.parent / 'final-work-state.json'))
            check(name + ':final registry state', expected[-1]['budget_results'][0]['result']['state'],
                  load(path.parent / 'final-registry-state.json'))

    inventory = load(HERE / 'case-inventory.json')
    case_ids = set()
    for row in inventory['cases']:
        case_ids.add(row['id'])
        check('case bytes:' + row['id'], sha(HERE / row['path']), row['raw_sha256'])
    coverage = load(HERE / 'source-coverage.json')
    obligations = load(HERE / 'authority-input.json')['source']['obligations']
    check('source obligation inventory', sorted(row['source_obligation_id'] for row in coverage['coverage']),
          sorted(row['id'] for row in obligations))
    for row in coverage['coverage']:
        check('coverage cases:' + row['source_obligation_id'], set(row['case_ids']) <= case_ids, True)
        for path in row['artifact_paths']:
            check('coverage artifact:' + row['source_obligation_id'] + ':' + path, (HERE / path).is_file(), True)
    check('original history preserved', load(HERE / 'original-return-to-service-history.json'),
          load(HERE / 'correction/input.json')['original_record'])
    passed = sum(row['passed'] for row in rows)
    report = {'candidate_pin': pin, 'status': 'PASS' if passed == len(rows) else 'FAIL',
              'qualification': 'DEVELOPMENT_RUN_NOT_QUALIFYING', 'checks': len(rows),
              'passed': passed, 'failed': len(rows) - passed,
              'source_cases': len(case_ids), 'source_obligations': len(obligations),
              'trace_groups': [str(path.parent.relative_to(HERE)) for path in traces], 'results': rows}
    print(json.dumps(report, indent=2))
    return 0 if passed == len(rows) else 1


def sha_value(value):
    if isinstance(value, bytes):
        return 'sha256:' + hashlib.sha256(value).hexdigest()
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


if __name__ == '__main__':
    raise SystemExit(main())
