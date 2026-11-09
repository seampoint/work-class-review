#!/usr/bin/env python3
"""Verify frozen information-flow cases and ordered streams in both consumers."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
TIMEOUT = 600
MAXIMUM_OUTPUT = 32 * 1024 * 1024
STREAMS = (('compensation', 5), ('bank-protected', 4), ('bank-clean', 5),
           ('compensation-lifecycle', 6), ('reporting-handoff', 2))
AUTHORITIES = (('compensation', 'compensation-authority'),
               ('bank-clean', 'bank-clean-authority'),
               ('bank-protected', 'bank-protected-denied'))


def sha(path):
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--conformance-root', type=Path, default=HERE.parent)
    parser.add_argument('--report-directory', type=Path, required=True)
    args = parser.parse_args()
    base, output = args.conformance_root.resolve(), args.report_directory.resolve()
    root = base.parents[2]
    normative = root / 'library/work-class-specification' / base.name
    specimen = base / 'specimens/information-flow'
    selected_roots = [normative, base / 'python', base / 'typescript', base / 'runner', specimen,
                      root / 'node_modules']
    if any(output.is_relative_to(path) for path in selected_roots):
        parser.error('Report directory must be outside consumed source trees')
    if Path('/Volumes/ssd').exists() and not output.is_relative_to(Path('/Volumes/ssd')):
        parser.error('Report directory must be under /Volumes/ssd')
    output.mkdir(parents=True, exist_ok=False)
    cache = output / 'unused-bytecode-cache'
    cache.mkdir()
    temporary = output / 'temporary'
    temporary.mkdir()
    (output / 'RETENTION.md').write_text('Retain guarded frozen information-flow verification, exact requests, expected responses, raw process outputs and temporary/cache disposition. No consumer or expected source files are generated or changed.\n')
    sys.path.insert(0, str(base / 'runner'))
    from transport import PROTOCOL, canonical, read_json

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    checks = []

    def check(name, actual, expected):
        row = {'name': name, 'passed': actual == expected}
        if not row['passed']:
            row.update(actual=actual, expected=expected)
        checks.append(row)

    artifact_index = load(specimen / 'artifact-index.json')
    coverage = load(specimen / 'source-coverage.json')
    index = load(base / 'cases/index.json')
    case_entries = {row['id']: row for row in coverage['cases']}
    case_paths = {case_id: (specimen / row['path']).resolve() for case_id, row in case_entries.items()}
    sources = [(root / row['path']).resolve() for row in coverage['sources']]
    extra_paths = [Path(__file__).resolve(), base / 'cases/index.json', *case_paths.values(), *sources]
    extra_paths += [path for name in ('package.json', 'package-lock.json') if (path := root / name).is_file()]
    runtime_paths = {'runtime/python': Path(sys.executable).resolve(),
                     'runtime/node': Path(shutil.which('node')).resolve()}

    def inventory():
        paths = set(extra_paths)
        for folder in selected_roots:
            paths.update(path for path in folder.rglob('*') if path.is_file()
                         and '__pycache__' not in path.parts and path.suffix != '.pyc'
                         and path.name != '.DS_Store')
        result = {str(path.relative_to(root)) if path.is_relative_to(root)
                  else 'verifier/' + path.name: sha(path) for path in sorted(paths)}
        result.update({name: sha(path) for name, path in runtime_paths.items()})
        return result

    before = inventory()
    write(output / 'guard-before.json', before)
    pin = sha(normative / 'contract-manifest.json')
    manifest = load(normative / 'contract-manifest.json')
    check('artifact candidate pin', artifact_index['candidate_pin'], pin)
    check('coverage candidate pin', coverage['candidate_pin'], pin)
    check('case index candidate pin', index['candidate_pin'], pin)
    for row in manifest['files']:
        check('normative:' + row['path'], sha(normative / row['path']), 'sha256:' + row['sha256'])
    for row in artifact_index['artifacts']:
        check('artifact:' + row['path'], sha(specimen / row['path']), row['raw_sha256'])
    check('artifact inventory count', len(artifact_index['artifacts']), 28)
    check('coverage case count', len(case_entries), 183)
    check('declared coverage case count', coverage['case_count'], '183')
    check('coverage case identity uniqueness', len(case_entries), len(coverage['cases']))
    for case_id, row in case_entries.items():
        check('coverage case:' + case_id, sha(case_paths[case_id]), row['raw_sha256'])
    check('coverage label identities', sorted(coverage['labels'].values()), sorted(case_entries))
    check('source inventory count', len(sources), 3)
    for row, path in zip(coverage['sources'], sources, strict=True):
        check('source:' + row['path'], sha(path), row['raw_sha256'])
    dispositions = coverage['source_dispositions']
    check('source disposition count', len(dispositions), 206)
    check('declared source disposition count', coverage['source_case_count'], '206')
    check('source disposition identity uniqueness', len({row['id'] for row in dispositions}), 206)
    host_inventory = load(specimen / coverage['host_expectations']['path'])
    host_ids = {row['id'] for row in host_inventory['cases']}
    check('host inventory count only, not execution', len(host_ids), 80)
    check('host inventory hash', sha(specimen / coverage['host_expectations']['path']), coverage['host_expectations']['raw_sha256'])
    all_case_ids = {row['id'] for row in index['cases']}
    check('source case references', all(set(row['case_ids'] + row['component_case_ids']) <= all_case_ids
                                       for row in dispositions), True)
    check('source host references', all(row['host_expectation_id'] is None
                                       or row['host_expectation_id'] in host_ids for row in dispositions), True)

    jobs = []
    fresh_requests = []
    for label, count in STREAMS:
        payload = (specimen / label / 'requests.jsonl').read_bytes()
        requests = [read_json(line.decode('utf-8')) for line in payload.splitlines()]
        expected = load(specimen / label / 'results-derived.json')
        check(label + ':request count', len(requests), count)
        check(label + ':result count', len(expected), count)
        wanted = []
        for request, result in zip(requests, expected, strict=True):
            case_id = request['request_id']
            case = load(case_paths[case_id])
            check(label + ':' + case_id + ':protocol', request['protocol'], PROTOCOL)
            check(label + ':' + case_id + ':frozen input', canonical(request['input']), canonical(case['input']))
            check(label + ':' + case_id + ':operation', request['operation'], case['operation'])
            check(label + ':' + case_id + ':frozen result', canonical(result), canonical(case['expected']))
            response = {key: request[key] for key in ('protocol', 'request_id', 'operation')}
            response['result'] = result
            wanted.append(response)
            fresh_requests.append(('fresh-' + case_id, (canonical(request) + '\n').encode(), [response]))
        jobs.append(('stream-' + label, payload, wanted))
    check('ordered stream count', len(jobs), 5)
    check('stream request inventory', len(fresh_requests), 22)
    check('stream request identity uniqueness', len({row[0] for row in fresh_requests}), 22)
    for label, coverage_label in AUTHORITIES:
        case_id = coverage['labels'][coverage_label]
        case = load(case_paths[case_id])
        request = {'protocol': PROTOCOL, 'request_id': case_id, 'operation': 'evaluate',
                   'input': {'kind': 'AUTHORITY', 'request': load(specimen / label / 'authority-input.json')}}
        result = load(specimen / label / 'authority-result-derived.json')
        check(label + ':authority operation', request['operation'], case['operation'])
        check(label + ':authority frozen input', canonical(request['input']), canonical(case['input']))
        check(label + ':authority frozen result', canonical(result), canonical(case['expected']))
        response = {key: request[key] for key in ('protocol', 'request_id', 'operation')}
        response['result'] = result
        fresh_requests.append(('authority-' + label, (canonical(request) + '\n').encode(), [response]))
    check('fresh request count per consumer', len(fresh_requests), 25)
    jobs = fresh_requests + jobs
    for label, payload, wanted in jobs:
        (output / (label + '.requests.jsonl')).write_bytes(payload)
        (output / (label + '.expected.jsonl')).write_bytes(b''.join((canonical(row) + '\n').encode() for row in wanted))

    commands = {'python': [sys.executable, '-B', '-X', 'pycache_prefix=' + str(cache), str(base / 'python/adapter.py')],
                'typescript': ['node', str(base / 'typescript/adapter.ts')]}
    environment = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT') if key in os.environ}
    environment.update(LANG='C.UTF-8', TZ='UTC', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(temporary))

    def execute(language, job):
        label, payload, wanted = job
        prefix = output / (label + '.' + language)
        raw_paths = [Path(str(prefix) + '.stdout.jsonl'), Path(str(prefix) + '.stderr.txt')]
        captured = [bytearray(), bytearray()]
        begin = time.monotonic()
        failure = None
        process = subprocess.Popen(commands[language], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=output, env=environment, start_new_session=True)
        selector = selectors.DefaultSelector()
        try:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, None)
            selector.register(process.stdout, selectors.EVENT_READ, 0)
            selector.register(process.stderr, selectors.EVENT_READ, 1)
            written = 0
            while selector.get_map():
                remaining = TIMEOUT - (time.monotonic() - begin)
                if remaining <= 0:
                    raise RuntimeError('TIMEOUT')
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.fileobj is process.stdin:
                        written += os.write(process.stdin.fileno(), payload[written:written + 65536])
                        if written == len(payload):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            captured[key.data].extend(chunk)
                            if len(captured[key.data]) > MAXIMUM_OUTPUT:
                                raise RuntimeError('OUTPUT_LIMIT')
            process.wait(timeout=max(0.01, TIMEOUT - (time.monotonic() - begin)))
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            failure = 'TIMEOUT' if isinstance(error, subprocess.TimeoutExpired) else str(error)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            for pipe in (process.stdin, process.stdout, process.stderr):
                if not pipe.closed:
                    pipe.close()
            selector.close()
        for path, raw in zip(raw_paths, captured, strict=True):
            path.write_bytes(raw)
        transport_error = None
        try:
            actual = [read_json(line.decode('utf-8', errors='strict')) for line in bytes(captured[0]).splitlines()]
            if bytes(captured[0]) != b''.join((canonical(row) + '\n').encode() for row in actual):
                raise ValueError('NONCANONICAL_OUTPUT')
            if len(actual) != len(wanted):
                raise ValueError('OUTPUT_LINE_COUNT')
            for response, expected in zip(actual, wanted, strict=True):
                if not isinstance(response, dict) or set(response) != {'protocol', 'request_id', 'operation', 'result'}:
                    raise ValueError('RESPONSE_ENVELOPE_INVALID')
                if any(response[key] != expected[key] for key in ('protocol', 'request_id', 'operation')):
                    raise ValueError('RESPONSE_BINDING_MISMATCH')
                if not isinstance(response['result'], dict):
                    raise ValueError('RESULT_NOT_OBJECT')
        except (ValueError, UnicodeError) as error:
            transport_error = str(error)
        expected_bytes = (output / (label + '.expected.jsonl')).read_bytes()
        metadata = {'label': label, 'language': language, 'command': commands[language],
                    'returncode': process.returncode, 'execution_failure': failure, 'transport_error': transport_error,
                    'timeout_seconds': TIMEOUT, 'maximum_output_bytes_per_channel': MAXIMUM_OUTPUT,
                    'stdout_bytes': len(captured[0]), 'stderr_bytes': len(captured[1]),
                    'elapsed_seconds': time.monotonic() - begin,
                    'request_sha256': sha(output / (label + '.requests.jsonl')),
                    'expected_sha256': sha(output / (label + '.expected.jsonl')),
                    'stdout_sha256': sha(raw_paths[0]), 'stderr_sha256': sha(raw_paths[1]),
                    'exact_complete_responses': bytes(captured[0]) == expected_bytes}
        metadata['status'] = 'PASS' if process.returncode == 0 and failure is None and transport_error is None and metadata['exact_complete_responses'] else 'FAIL'
        write(Path(str(prefix) + '.process.json'), metadata)
        return metadata

    results = []
    if all(row['passed'] for row in checks):
        with ThreadPoolExecutor(max_workers=2) as executor:
            for language_rows in executor.map(lambda language: [execute(language, job) for job in jobs], commands):
                results.extend(language_rows)
    for row in results:
        check(row['label'] + ':' + row['language'] + ':complete execution', row['status'], 'PASS')
    cross_labels = []
    for label, _, _ in jobs:
        paths = [output / (label + '.' + language + '.stdout.jsonl') for language in commands]
        if all(path.exists() for path in paths):
            check(label + ':cross-language exact bytes', paths[0].read_bytes() == paths[1].read_bytes(), True)
            cross_labels.append(label)
    after = inventory()
    write(output / 'guard-after.json', after)
    check('consumed source and input bytes unchanged', before, after)
    check('unused bytecode cache remains empty', [str(path) for path in cache.iterdir()], [])
    failed = sum(not row['passed'] for row in checks)
    report = {'status': 'PASS' if not failed and len(results) == 60 else 'FAIL',
              'qualification': 'DEVELOPMENT_RUN_NOT_QUALIFYING', 'candidate_pin': pin,
              'started_at': started_at, 'finished_at': datetime.now(timezone.utc).isoformat(),
              'elapsed_seconds': time.monotonic() - started, 'verifier_sha256': sha(Path(__file__).resolve()),
              'fresh_requests_per_consumer': 25, 'fresh_stream_requests_per_consumer': 22,
              'fresh_authority_requests_per_consumer': 3, 'ordered_streams_per_consumer': 5,
              'ordered_stream_request_counts': dict(STREAMS), 'processes_executed': len(results),
              'fresh_cross_language_comparisons': sum(not label.startswith('stream-') for label in cross_labels),
              'stream_cross_language_comparisons': sum(label.startswith('stream-') for label in cross_labels),
              'checks': len(checks), 'passed': len(checks) - failed, 'failed': failed,
              'guard_unchanged': before == after, 'guarded_files': len(before),
              'source_roots': [str(path) for path in selected_roots],
              'output_limit_scope': '32 MiB independently per stdout/stderr channel, monitored incrementally. An exceeding read chunk is retained before terminating the task-owned process group.',
              'bytecode_scope': 'Python consumers use -B and an initially empty task-local pycache_prefix. No cache is written. This guard does not claim an interpreter file-read audit.',
              'scope': 'Frozen complete inputs/results, three separate authority inputs and five ordered streams. Coverage inventories are checked, not re-derived. Host expectations and providers are not executed or qualified.',
              'runtime': {'python': sys.version, 'node': subprocess.run(['node', '--version'], capture_output=True, text=True, check=True).stdout.strip()},
              'process_results': results, 'results': checks}
    write(output / 'report.json', report)
    print(json.dumps({key: report[key] for key in ('status', 'processes_executed', 'checks', 'passed', 'failed', 'guard_unchanged', 'guarded_files', 'elapsed_seconds')}, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
