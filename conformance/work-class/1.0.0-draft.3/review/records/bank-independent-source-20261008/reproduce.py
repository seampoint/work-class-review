#!/usr/bin/env python3
"""Extract frozen bank inputs and reproduce the sealed independent expectations."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def files(root):
    return [p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc' and p.name != '.DS_Store']


def worker():
    sys.pycache_prefix = str(Path(sys.argv[4]).resolve() / 'unused-bytecode-cache')
    import runpy
    constructor, repo, work, norm, vendor = map(lambda x: Path(x).resolve(), sys.argv[2:])
    roots = {'constructors': HERE, 'input': work / 'input-root', 'normative': norm, 'vendor': vendor, 'generated': work / 'expected', 'unused-bytecode-cache': work / 'unused-bytecode-cache'}
    reads = set()

    def audit(event, args):
        if event != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        mode = args[1] or ''
        flags = args[2]
        if any(c in mode for c in 'wax+') or flags & (os.O_WRONLY | os.O_RDWR):
            return
        if path.is_relative_to(repo) and not any(path.is_relative_to(root) for root in roots.values()):
            raise RuntimeError('Source-only derivation attempted an undeclared project read')
        for label, root in roots.items():
            if path.is_relative_to(root) and path.is_file():
                reads.add((label, str(path.relative_to(root))))
                break

    sys.addaudithook(audit)
    sys.argv = [str(constructor), '--input-root', str(work / 'input-root'), '--contract-root', str(norm), '--vendor-root', str(vendor), '--output-root', str(work / 'expected')]
    try:
        runpy.run_path(str(constructor), run_name='__main__')
    finally:
        inventory = {label + '/' + relative: sha(roots[label] / relative) for label, relative in sorted(reads)}
        write_json(work / 'read-dependencies.json', inventory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, default=HERE.parents[5])
    parser.add_argument('--work-root', type=Path, required=True, help='Fresh retained directory for extracted inputs, generated outputs and logs.')
    parser.add_argument('--vendor-root', type=Path, help='Explicit compatible platform dependency directory; defaults to the package vendor tree.')
    parser.add_argument('--allow-platform-overlay', action='store_true', help='Permit only native-binary differences from the historical macOS dependency inventory; record the actual hashes separately.')
    args = parser.parse_args()
    repo = args.repository_root.resolve()
    work = args.work_root.resolve()
    packaging = json.loads((HERE / 'PACKAGING-01.json').read_bytes())
    seal = json.loads((HERE / 'SEAL-01.json').read_bytes())
    freeze = json.loads((HERE / 'INPUT-FREEZE-01.json').read_bytes())
    expected = json.loads((HERE / 'EXPECTED-HASHES-01.json').read_bytes())
    historical_deps = json.loads((HERE / 'MECHANICAL-DEPENDENCIES-01.json').read_bytes())['vendor_files']
    norm = repo / packaging['contract_directory']
    vendor = args.vendor_root.resolve() if args.vendor_root else repo / packaging['vendor_directory']
    assert not work.exists(), 'Use a fresh work directory'
    assert not any(work.is_relative_to(root) for root in (HERE, norm, vendor, repo / packaging['case_directory'])), 'Work directory overlaps source files'
    for name, value in packaging['exact_copies'].items():
        assert sha(HERE / name) == value, name
    assert sha(HERE / 'SEAL-01.json') == packaging['seal_sha256']
    for name, value in seal['normative_files'].items():
        assert sha(norm / name) == value, name
    dependency_overlay = []
    for name, value in historical_deps.items():
        path = vendor / name
        if not path.exists() or sha(path) != value:
            assert args.allow_platform_overlay and not name.endswith('.py'), 'Historical dependency differs: ' + name
            dependency_overlay.append(name)
    source_paths = files(HERE) + files(vendor) + [norm / name for name in seal['normative_files']]
    source_paths += [repo / packaging['case_directory'] / (row['id'] + '.json') for row in freeze['cases']]
    source_paths += [repo / row['path'] for row in packaging['published_sources'].values()]
    source_paths = sorted(set(source_paths))
    before = {str(path): sha(path) for path in source_paths}
    work.mkdir(parents=True)
    (work / 'RETENTION.md').write_text('Retain this source-only reproduction directory as evidence: extracted input-only freeze, unchanged fictional sources, generated complete expectations, dependency inventories, process logs and guarded receipt. No consumer runs here.\n')
    input_root = work / 'input-root'
    (input_root / 'inputs').mkdir(parents=True)
    (input_root / 'sources').mkdir()
    shutil.copyfile(HERE / 'INPUT-FREEZE-01.json', input_root / 'INPUT-FREEZE-01.json')
    for row in freeze['cases']:
        path = repo / packaging['case_directory'] / (row['id'] + '.json')
        assert sha(path) == row['original_complete_case_sha256'], row['id']
        case = json.loads(path.read_bytes())
        extracted = {key: case[key] for key in ('id', 'operation', 'input', 'requirements')}
        target = input_root / row['input_path']
        write_json(target, extracted)
        assert sha(target) == row['input_sha256'], row['id']
    for name, row in packaging['published_sources'].items():
        assert sha(repo / row['path']) == row['sha256'], name
        shutil.copyfile(repo / row['path'], input_root / 'sources' / name)
    extracted_before = {str(path.relative_to(input_root)): sha(path) for path in files(input_root)}
    command = [sys.executable, '-I', '-S', '-B', '-u', str(Path(__file__).resolve()), '--worker', str(HERE / 'derive_and_seal.py'), str(repo), str(work), str(norm), str(vendor)]
    started = time.monotonic()
    with (work / 'stdout.log').open('wb') as stdout, (work / 'stderr.log').open('wb') as stderr:
        process = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
    elapsed = time.monotonic() - started
    output = work / 'expected'
    rows = [{'id': row['id'], 'expected_sha256': row['expected_sha256'], 'actual_sha256': sha(output / row['expected_path']) if (output / row['expected_path']).exists() else None} for row in expected['cases']]
    matched = sum(row['expected_sha256'] == row['actual_sha256'] for row in rows)
    generated_deps_path = output / 'MECHANICAL-DEPENDENCIES-01.json'
    generated_deps = json.loads(generated_deps_path.read_bytes())['vendor_files'] if generated_deps_path.exists() else {}
    dependency_differences = [name for name in sorted(historical_deps.keys() | generated_deps.keys()) if historical_deps.get(name) != generated_deps.get(name)]
    dependency_ok = not dependency_differences or args.allow_platform_overlay and all(not name.endswith('.py') for name in dependency_differences)
    after = {str(path): sha(path) for path in source_paths}
    extracted_after = {str(path.relative_to(input_root)): sha(path) for path in files(input_root)}
    metadata_matches = {name: (output / name).exists() and sha(output / name) == sha(HERE / name) for name in ('EXPECTED-HASHES-01.json', 'DERIVATIONS-01.json')}
    read_inventory = json.loads((work / 'read-dependencies.json').read_bytes()) if (work / 'read-dependencies.json').exists() else {}
    guard_ok = before == after and extracted_before == extracted_after and not any(name.endswith('.pyc') for name in read_inventory)
    passed = process.returncode == 0 and matched == 54 and all(metadata_matches.values()) and dependency_ok and guard_ok
    report = {
        'schema': 'bank-independent-source-reproduction/1', 'status': 'PASS' if passed else 'FAIL',
        'candidate_pin': seal['candidate_pin'], 'seal_sha256': packaging['seal_sha256'],
        'constructor_sha256': seal['constructors'], 'exit_code': process.returncode,
        'elapsed_seconds': elapsed, 'python': platform.python_version(), 'platform': platform.platform(),
        'total': len(rows), 'matched': matched, 'rows': rows, 'metadata_matches': metadata_matches,
        'guarded_source_files': len(before), 'guarded_extracted_files': len(extracted_before),
        'guard_unchanged': guard_ok, 'changed_sources': [str(path.relative_to(repo)) if path.is_relative_to(repo) else 'vendor/' + str(path.relative_to(vendor)) for path in source_paths if before[str(path)] != after[str(path)]],
        'historical_dependency_count': len(historical_deps), 'actual_dependency_count': len(generated_deps),
        'historical_dependency_manifest_equal': generated_deps_path.exists() and sha(generated_deps_path) == sha(HERE / 'MECHANICAL-DEPENDENCIES-01.json'),
        'preexisting_bytecode_reads': [name for name in read_inventory if name.endswith('.pyc')],
        'platform_overlay_requested': args.allow_platform_overlay, 'platform_dependency_differences': dependency_differences,
        'actual_imported_vendor_files': generated_deps,
        'supplementary_read_dependencies': read_inventory,
        'dependency_scope': 'The original seal inventories imported vendor modules, including its macOS rpds binary. Actual resource reads supplement that historical inventory and are guarded against change; native platform substitutions are explicitly declared, never relabeled as sealed bytes.',
        'command': 'python3 -B reproduce.py --repository-root <repository> --work-root <fresh-work-directory>' + (' --vendor-root <platform-vendor> --allow-platform-overlay' if args.allow_platform_overlay else ''),
        'scope': 'Complete source-only regeneration from checked input-only extraction, fictional sources and selected normative bytes. No consumer, existing expected body, model API or network service is invoked by the constructor. No new seal is created.',
    }
    write_json(work / 'report.json', report)
    write_json(work / 'guard-before.json', before)
    write_json(work / 'guard-after.json', after)
    print(json.dumps({key: report[key] for key in ('status', 'matched', 'total', 'exit_code', 'elapsed_seconds', 'guard_unchanged', 'historical_dependency_manifest_equal', 'platform_dependency_differences')}, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker()
    else:
        raise SystemExit(main())
