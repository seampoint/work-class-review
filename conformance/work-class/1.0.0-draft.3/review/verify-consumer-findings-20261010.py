#!/usr/bin/env python3
"""Replay 28 unindexed consumer finding controls with both native adapters.

Capture is bounded to 8 MiB per output stream and 120 seconds per command.
POSIX commands run in a new session whose process group is killed on cleanup.
Other systems use direct-child termination only; descendant termination is not
asserted, and unsupported nonblocking pipe capture fails the run.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
MANIFEST_SHA = '019f0bacbb77aa1c0a3f8720bf1f57eca339e55f219c35e32114f9ec76fcb4e4'
PROVENANCE_SHA = '9b9f5bc10e841e2b3e1faf02df2e60e972aae24bab15162017c0542f070e6ee3'


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open('xb') as out:
        out.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b'\n')


def load_response_tools(repository: Path):
    native = repository / 'conformance/work-class/1.0.0-draft.3'
    spec = repository / 'library/work-class-specification/1.0.0-draft.3'
    module_spec = importlib.util.spec_from_file_location('supplement_transport', native / 'runner/transport.py')
    codec = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(codec)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(native / 'python/vendor'))
    from jsonschema import Draft202012Validator, RefResolver
    bundle = json.loads((spec / 'schema-bundle.json').read_bytes())
    store = {row['uri']: json.loads((spec / row['path']).read_bytes()) for row in bundle['schemas']}
    schema = json.loads((spec / 'protocol.schema.json').read_bytes())

    def unavailable(uri):
        raise RuntimeError('Response schema reference is outside the bundled graph: ' + uri)

    resolver = RefResolver(schema['$id'], schema, store=store, handlers={'https': unavailable, 'http': unavailable})
    validator = Draft202012Validator({'$ref': schema['$id'] + '#/$defs/response'}, resolver=resolver)
    return codec, validator


def read_response(raw: bytes, request: dict, codec, validator) -> dict:
    if not raw.endswith(b'\n'):
        raise RuntimeError('OUTPUT_MISSING_LF')
    response = codec.read_json(raw[:-1].decode('utf-8', errors='strict'))
    if raw != codec.canonical(response).encode('utf-8') + b'\n':
        raise RuntimeError('NONCANONICAL_OUTPUT')
    if type(response) is not dict or set(response) != {'protocol', 'request_id', 'operation', 'result'}:
        raise RuntimeError('RESPONSE_ENVELOPE_INVALID')
    if any(type(response[key]) is not str or response[key] != request[key] for key in ('protocol', 'request_id', 'operation')):
        raise RuntimeError('RESPONSE_REQUEST_MISMATCH')
    if type(response['result']) is not dict or not validator.is_valid(response):
        raise RuntimeError('RESPONSE_SCHEMA_INVALID')
    return response


def run_command(name: str, command: list[str], repository: Path, output: Path,
                environment: dict, check_sources, guard_digest: str,
                wire: bytes | None = None, timeout: float = 120,
                maximum: int = 8 * 1024 * 1024) -> subprocess.CompletedProcess:
    started = time.monotonic()
    recorded_command = [str(Path(value).relative_to(repository)) if Path(value).is_absolute() and Path(value).is_relative_to(repository) else value for value in command]
    paths = {channel: output / (name + '.' + channel) for channel in ('stdin', 'stdout', 'stderr')}
    for channel, path in paths.items():
        with path.open('xb') as stream:
            stream.write((wire or b'') if channel == 'stdin' else b'')
    write_json(output / (name + '.START.json'),
               {'argv': recorded_command, 'cwd': '.', 'started_at': datetime.now(timezone.utc).isoformat(),
                'timeout_seconds': timeout, 'maximum_output_bytes_per_stream': maximum,
                'source_seal_sha256_before': guard_digest})
    process = None
    failure = None
    unchanged = None
    selector = selectors.DefaultSelector()
    files = {}
    observed = {'stdout': 0, 'stderr': 0}
    retained = {'stdout': 0, 'stderr': 0}
    termination = 'POSIX_PROCESS_GROUP' if os.name == 'posix' else 'DIRECT_CHILD_ONLY'
    try:
        check_sources()
        process = subprocess.Popen(command, cwd=repository, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=environment, start_new_session=os.name == 'posix')
        for channel in ('stdout', 'stderr'):
            pipe = getattr(process, channel)
            os.set_blocking(pipe.fileno(), False)
            files[channel] = paths[channel].open('ab', buffering=0)
            selector.register(pipe, selectors.EVENT_READ, channel)
        payload = wire or b''
        written = 0
        if payload:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
        else:
            process.stdin.close()
        while selector.get_map():
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise RuntimeError('TIMEOUT')
            for key, _ in selector.select(min(remaining, 0.1)):
                if key.data == 'stdin':
                    written += os.write(key.fileobj.fileno(), payload[written:written + 65536])
                    if written == len(payload):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue
                content = os.read(key.fileobj.fileno(), 65536)
                if not content:
                    selector.unregister(key.fileobj)
                    continue
                channel = key.data
                observed[channel] += len(content)
                bounded = content[:maximum - retained[channel]]
                files[channel].write(bounded)
                retained[channel] += len(bounded)
                if observed[channel] > maximum:
                    raise RuntimeError('OUTPUT_LIMIT_' + channel.upper())
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise RuntimeError('TIMEOUT')
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('TIMEOUT') from error
        if process.returncode != 0:
            raise RuntimeError('PROCESS_EXIT_' + str(process.returncode))
    except Exception as error:
        failure = type(error).__name__ + ': ' + str(error)
    finally:
        if process is not None:
            try:
                if os.name == 'posix':
                    os.killpg(process.pid, signal.SIGKILL)
                elif process.poll() is None:
                    process.kill()
            except ProcessLookupError:
                pass
            process.wait()
            for pipe in (process.stdin, process.stdout, process.stderr):
                if not pipe.closed:
                    pipe.close()
        selector.close()
        for stream in files.values():
            stream.close()
        try:
            check_sources()
            unchanged = True
        except Exception as error:
            unchanged = False
            failure = failure or type(error).__name__ + ': ' + str(error)
        streams = {channel: {'path': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path.read_bytes())}
                   for channel, path in paths.items()}
        write_json(output / (name + '.command.json'),
                   {'argv': recorded_command, 'cwd': '.', 'launched': process is not None,
                    'pid': process.pid if process is not None else None,
                    'exit_code': process.returncode if process is not None else None,
                    'elapsed_seconds': time.monotonic() - started, 'failure': failure,
                    'process_termination': termination, 'timeout_seconds': timeout,
                    'maximum_output_bytes_per_stream': maximum, 'observed_output_bytes': observed,
                    'source_seal_sha256_before': guard_digest,
                    'source_seal_sha256_after': guard_digest if unchanged else None,
                    'sources_unchanged': unchanged, 'streams': streams})
    if failure is not None:
        raise RuntimeError(name + ': ' + failure)
    return subprocess.CompletedProcess(command, process.returncode,
                                       paths['stdout'].read_bytes(), paths['stderr'].read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=HERE.parents[3])
    parser.add_argument('--fixtures', type=Path, default=HERE / 'fixtures/consumer-findings-20261010')
    parser.add_argument('--output-directory', type=Path, required=True,
                        help='New directory for retained commands, raw streams and result report.')
    args = parser.parse_args()
    repository = args.repository.resolve()
    fixtures = args.fixtures.resolve()
    output = args.output_directory.resolve()
    native = repository / 'conformance/work-class/1.0.0-draft.3'
    spec = repository / 'library/work-class-specification/1.0.0-draft.3'
    manifest_raw = (fixtures / 'CASES.json').read_bytes()
    provenance_raw = (fixtures / 'PROVENANCE.json').read_bytes()
    if sha(manifest_raw) != MANIFEST_SHA or sha(provenance_raw) != PROVENANCE_SHA:
        raise RuntimeError('Supplemental manifest or oracle provenance changed before launch')
    manifest = json.loads(manifest_raw)
    provenance = json.loads(provenance_raw)
    pin = 'sha256:' + sha((spec / 'contract-manifest.json').read_bytes())
    if manifest['specification_pin'] != pin or provenance['specification_pin'] != pin:
        raise RuntimeError('Supplemental cases do not bind the current contract pin')
    if len(manifest['cases']) != 28 or manifest['original_case_count'] != 27:
        raise RuntimeError('Supplemental case inventory changed')
    codec, response_validator = load_response_tools(repository)

    for row in provenance['sources']:
        path = fixtures / row['path'] if 'path' in row else repository / row['repository_path'] if 'repository_path' in row else None
        if path is not None and sha(path.read_bytes()) != row['sha256']:
            raise RuntimeError('Oracle source changed: ' + str(path.relative_to(fixtures) if path.is_relative_to(fixtures) else path.relative_to(repository)))
    for row in provenance['tested_consumer_sources']:
        if sha((repository / row['path']).read_bytes()) != row['sha256']:
            raise RuntimeError('Tested consumer source changed: ' + row['path'])
    producer = fixtures / provenance['portable_oracle_producer']['path']
    if sha(producer.read_bytes()) != provenance['portable_oracle_producer']['sha256']:
        raise RuntimeError('Portable oracle producer changed')

    sealed_rows = []
    requests = []
    for case in manifest['cases']:
        for kind in ('request', 'expected'):
            content = (fixtures / case[kind]['path']).read_bytes()
            if len(content) != case[kind]['bytes'] or sha(content) != case[kind]['sha256']:
                raise RuntimeError('Sealed ' + kind + ' changed: ' + case['name'])
        wire = (fixtures / case['request']['path']).read_bytes()
        expected_raw = (fixtures / case['expected']['path']).read_bytes()
        request, expected = json.loads(wire), json.loads(expected_raw)
        if wire != canonical(request) + b'\n' or expected_raw != canonical(expected) + b'\n':
            raise RuntimeError('Case serialization changed: ' + case['name'])
        row = {'name': case['name'], 'expectation_kind': case['expectation_kind'], 'request': request,
               'expected': expected, 'wire_base64': base64.b64encode(wire).decode()}
        if sha(canonical(row)) != case['original_row_sha256']:
            raise RuntimeError('Case differs from its original presealed row: ' + case['name'])
        sealed_rows.append(row)
        requests.append((case, wire, request, expected))
    if sha(canonical(sealed_rows[:27])) != manifest['original_case_rows_sha256']:
        raise RuntimeError('Original presealed case inventory differs')
    if sha(canonical(sealed_rows)) != manifest['case_rows_sha256']:
        raise RuntimeError('Current sealed case inventory differs')

    def inventory() -> dict[str, str]:
        paths = list(fixtures.rglob('*')) + list(spec.rglob('*'))
        paths += list((native / 'python/implementation').rglob('*.py'))
        paths += list((native / 'python/tests').glob('*.py'))
        paths += list((native / 'typescript').glob('*.ts'))
        paths += [native / 'python/adapter.py', native / 'python/consumer.py',
                  native / 'typescript/package.json', native / 'typescript/package-lock.json',
                  native / 'runner/transport.py', Path(__file__).resolve()]
        paths += list((native / 'python/vendor').rglob('*.py'))
        result = {}
        for path in sorted(set(paths)):
            if path.is_file():
                name = 'fixtures/' + path.relative_to(fixtures).as_posix() if path.is_relative_to(fixtures) else 'repository/' + path.relative_to(repository).as_posix() if path.is_relative_to(repository) else 'verifier/' + path.name
                result[name] = sha(path.read_bytes())
        return result

    sealed_sources = inventory()
    guard_digest = sha(canonical(sealed_sources))

    def check_sources() -> None:
        if inventory() != sealed_sources:
            raise RuntimeError('Sealed sources or stimuli changed during execution')

    output.mkdir(parents=True, exist_ok=False)
    # These directories retain any task-owned temporary files and caches on the caller's chosen volume.
    temporary = output / 'temporary'
    npm_cache = output / 'npm-cache'
    temporary.mkdir()
    npm_cache.mkdir()
    (output / 'RETENTION.md').write_text('Retain this directory with its raw adapter streams, command receipts, source seal and report. The temporary and npm-cache directories are task-owned retained execution roots. No deletion or relocation is scheduled.\n')
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(temporary), 'npm_config_cache': str(npm_cache)}
    write_json(output / 'SOURCE-SEAL.json', sealed_sources)
    write_json(output / 'RUN-START.json', {'specification_pin': pin, 'cases': len(requests),
                                         'source_seal_sha256': guard_digest,
                                         'verifier_sha256': sha(Path(__file__).read_bytes())})
    started_all = time.monotonic()

    def run(name: str, command: list[str], wire: bytes | None = None) -> subprocess.CompletedProcess:
        return run_command(name, command, repository, output, environment,
                           check_sources, guard_digest, wire)

    derivation_verified = False
    results = []
    failure = None
    try:
        derivation = run('oracle-derivation', [sys.executable, '-B', str(producer), '--repository', str(repository)])
        derivation_result = json.loads(derivation.stdout)
        if derivation_result.get('cases') != 28 or derivation_result.get('derivation_matches_presealed_cases') is not True:
            raise RuntimeError('Portable source derivation did not verify all cases')
        derivation_verified = True
        for case, wire, request, expected in requests:
            actual = {}
            matches = {}
            for language, command in [('python', [sys.executable, '-B', str(native / 'python/adapter.py')]),
                                      ('typescript', ['node', str(native / 'typescript/adapter.ts')])]:
                name = language + '-' + case['name']
                process = run(name, command, wire)
                response = read_response(process.stdout, request, codec, response_validator)
                actual[language] = response['result']
                if case['expectation_kind'] == 'COMPLETE_RESULT':
                    matches[language] = codec.canonical(actual[language]) == codec.canonical(expected)
                elif case['expectation_kind'] == 'SELECTED_DISPOSITION':
                    matches[language] = actual[language]['status'] == expected['status'] and actual[language].get('decision', {}).get('disposition') == expected['disposition']
                else:
                    raise RuntimeError('Unknown expectation kind')
            results.append({'name': case['name'], 'expectation_kind': case['expectation_kind'], 'matches_expected': matches,
                            'complete_results_equal': codec.canonical(actual['python']) == codec.canonical(actual['typescript']), 'actual': actual})
        check_sources()
    except Exception as error:
        failure = type(error).__name__ + ': ' + str(error)
    sources_unchanged = inventory() == sealed_sources
    passed = failure is None and sources_unchanged and len(results) == 28 and all(all(row['matches_expected'].values()) and row['complete_results_equal'] for row in results)
    commands = [json.loads(path.read_bytes()) for path in output.glob('*.command.json') if path.name.startswith(('python-', 'typescript-'))]
    report = {'specification_pin': pin, 'cases': len(results), 'adapter_processes': sum(row['launched'] for row in commands),
              'complete_result_oracles': sum(row['expectation_kind'] == 'COMPLETE_RESULT' for row in results),
              'selected_disposition_oracles': sum(row['expectation_kind'] == 'SELECTED_DISPOSITION' for row in results),
              'oracle_derivation_verified': derivation_verified, 'indexed_corpus_cases_added': 0,
              'manifest_sha256': MANIFEST_SHA, 'provenance_sha256': PROVENANCE_SHA,
              'original_sealed_inputs_sha256': manifest['original_sealed_inputs_sha256'],
              'source_seal_sha256': guard_digest, 'sources_unchanged': sources_unchanged,
              'verifier_sha256': sha(Path(__file__).read_bytes()), 'elapsed_seconds': time.monotonic() - started_all,
              'all_passed': passed, 'status': 'PASS' if passed else 'FAIL', 'failure': failure,
              'attempted_adapter_commands': len(commands), 'launched_adapter_processes': sum(row['launched'] for row in commands),
              'results': results}
    write_json(output / 'REPORT.json', report)
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
