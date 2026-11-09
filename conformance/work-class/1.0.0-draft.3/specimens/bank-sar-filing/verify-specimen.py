#!/usr/bin/env python3
"""Compare the retained author-derived bank traces in both consumers."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import os
from datetime import datetime, timezone
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[2]
sys.path.insert(0, str(BASE / 'runner'))
from transport import canonical, run_captured  # noqa: E402
sys.path.insert(0, str(BASE / "review"))
from verification_output import output_directory  # noqa: E402


def sha(path):
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report-directory', type=Path)
    parser.add_argument('--timeout-seconds', type=int, default=int(os.environ.get('WORK_CLASS_SPECIMEN_TIMEOUT_SECONDS', '900')))
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error('The timeout must be positive')
    output = (args.report_directory or ROOT / 'runs' / ('bank-specimen-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + str(os.getpid()))).resolve()
    try:
        output = output_directory(output, ROOT)
    except ValueError as error:
        parser.error(str(error))
    output.mkdir(parents=True, exist_ok=False)
    checks = []
    def check(name, actual, expected):
        row = {'name': name, 'passed': actual == expected}
        if not row['passed']:
            row['actual'] = actual
            row['expected'] = expected
        checks.append(row)
    index = load(HERE / 'artifact-index.json')
    pin = sha(ROOT / 'library/work-class-specification/1.0.0-draft.3/contract-manifest.json')
    check('contract pin', index['candidate_pin'], pin)
    for artifact in index['artifacts']:
        check('artifact:' + artifact['path'], sha(HERE / artifact['path']), artifact['raw_sha256'])
    guard_paths = [HERE / row['path'] for row in index['artifacts']] + [HERE / 'artifact-index.json']
    for folder in [BASE / 'typescript', BASE / 'python']:
        guard_paths.extend(sorted(path for path in folder.rglob('*') if path.is_file()
            and not {'__pycache__', 'node_modules'}.intersection(path.parts)
            and path.suffix != '.pyc' and path.name != '.DS_Store'))
    dependency_paths = [BASE / 'typescript/package.json', BASE / 'typescript/package-lock.json']
    modules = BASE / 'typescript/node_modules'
    dependency_paths.extend(sorted(modules.rglob('package.json')))
    if (modules / '.package-lock.json').is_file():
        dependency_paths.append(modules / '.package-lock.json')
    guard_paths.extend(dependency_paths)
    before = {str(path.relative_to(ROOT)): sha(path) for path in guard_paths}
    commands = {'python': [sys.executable, '-B', str(BASE / 'python/adapter.py')], 'typescript': ['node', str(BASE / 'typescript/adapter.ts')]}
    groups = [('initial', 'requests.jsonl', 'results-derived.json'), ('amendment', 'amendment-requests.jsonl', 'amendment-results-derived.json'), ('customer', 'customer-requests.jsonl', 'customer-results-derived.json')]
    jobs = []
    for label, request_file, result_file in groups:
        payload = (HERE / request_file).read_bytes()
        requests = [json.loads(line) for line in payload.splitlines()]
        expected_records = load(HERE / result_file)
        expected = [row['expected'] for row in expected_records]
        check(label + ':case identity inventory', [row['case_id'] for row in expected_records], [request['request_id'] for request in requests])
        check(label + ':request count', len(requests), len(expected))
        wanted = [{'protocol': request['protocol'], 'request_id': request['request_id'], 'operation': request['operation'], 'result': result} for request, result in zip(requests, expected, strict=True)]
        # The adapter must emit exactly these bytes: one canonical response per line.
        wanted_bytes = b''.join(canonical(row).encode('utf-8') + b'\n' for row in wanted)
        (output / (label + '.requests.jsonl')).write_bytes(payload)
        (output / (label + '.expected.json')).write_text(json.dumps(wanted, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n')
        (output / (label + '.expected.jsonl')).write_bytes(wanted_bytes)
        for language, command in commands.items():
            jobs.append((label, language, command, payload, wanted_bytes))
    def execute(job):
        label, language, command, payload, wanted_bytes = job
        prefix = output / (label + '.' + language)
        stdout_path = prefix.with_suffix(prefix.suffix + '.stdout.jsonl')
        stderr_path = prefix.with_suffix(prefix.suffix + '.stderr.txt')
        started = time.monotonic()
        timed_out = False
        try:
            process = run_captured(command, payload, cwd=ROOT, timeout=args.timeout_seconds)
            returncode, stdout, stderr = process.returncode, process.stdout, process.stderr
        except subprocess.TimeoutExpired as error:
            timed_out = True
            returncode, stdout, stderr = -1, error.output or b'', error.stderr or b''
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        metadata = {'command': command, 'returncode': returncode, 'timed_out': timed_out, 'timeout_seconds': args.timeout_seconds, 'elapsed_seconds': time.monotonic() - started}
        prefix.with_suffix(prefix.suffix + '.process.json').write_text(json.dumps(metadata, indent=2) + '\n')
        return label, language, returncode, stdout, wanted_bytes, metadata
    streams = {}
    timings = []
    def run_language(language):
        return [execute(job) for job in jobs if job[1] == language]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outputs = list(executor.map(run_language, commands))
    for language_outputs in outputs:
        for label, language, returncode, actual_bytes, wanted_bytes, metadata in language_outputs:
            timings.append({'trace': label, 'language': language, **metadata})
            check(label + ':' + language + ':exit', returncode, 0)
            # Exact bytes, not parsed JSON: non-canonical but JSON-equal output fails.
            # Complete actual bytes and expected bytes are retained separately.
            matched = actual_bytes == wanted_bytes
            check(label + ':' + language + ':complete trace', matched, True)
            streams[(label, language)] = actual_bytes
    for label, _, _ in groups:
        check(label + ':cross-language', streams[(label, 'python')] == streams[(label, 'typescript')], True)
    coverage = load(HERE / 'source-coverage.json')
    obligations = load(HERE / 'normalized-obligations.json')['obligations']
    check('all source paragraphs dispositioned', sorted(row['source_obligation_id'] for row in coverage['coverage']), sorted(row['id'] for row in obligations))
    inventory = load(HERE / 'case-inventory.json')
    ids = {row['id'] for row in inventory['cases']}
    for case in inventory['cases']:
        check('case:' + case['id'], sha(BASE / case['candidate_path']), case['raw_sha256'])
    for row in coverage['coverage']:
        check('coverage case references:' + row['source_obligation_id'], set(row['case_ids']) <= ids, True)
    check('source bytes', (HERE / 'source-packet.md').read_bytes() == (BASE / 'review/fixtures/bank-sar-filing-and-customer-communication-revision2-source.md').read_bytes(), True)
    after = {str(path.relative_to(ROOT)): sha(path) for path in guard_paths}
    check('artifact/runtime/input bytes unchanged', before, after)
    (output / 'guarded-hashes.json').write_text(json.dumps({'before': before, 'after': after, 'unchanged': before == after,
        'runtime_scope': 'Recursive consumer files, including implementation, vendored binaries/provenance and input. Bytecode, node_modules source and .DS_Store are excluded.',
        'dependency_metadata': {str(path.relative_to(ROOT)): before[str(path.relative_to(ROOT))] for path in dependency_paths}}, indent=2) + '\n')
    failed = sum(not row['passed'] for row in checks)
    report = {'status': 'FAIL' if failed else 'PASS', 'qualification': 'DEVELOPMENT_RUN_NOT_QUALIFYING', 'candidate_pin': pin, 'source_cases': len(ids), 'source_obligations': len(obligations), 'trace_groups': [row[0] for row in groups], 'consumer_streams': len(jobs), 'stream_timings': timings, 'checks': len(checks), 'passed': len(checks) - failed, 'failed': failed, 'results': checks}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ['status', 'qualification', 'candidate_pin', 'source_cases', 'source_obligations', 'trace_groups', 'consumer_streams', 'checks', 'passed', 'failed']}, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
