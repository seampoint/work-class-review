"""Verify successor source-derived expectations without adapter responses."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repository', type=Path, required=True)
args = parser.parse_args()
SPEC = args.repository.resolve()
NATIVE = SPEC / 'conformance/work-class/1.0.0-draft.3'
sys.dont_write_bytecode = True
sys.path[:0] = [str(HERE), str(NATIVE / 'review')]
from projection_source import projection_proposal_inputs

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

def digest(kind, value):
    return 'sha256:' + hashlib.sha256(('seampoint.work-class/1.0.0-draft.3/' + kind + '\n').encode() + canonical(value)).hexdigest()

def flatten(value, path=''):
    rows = []
    if isinstance(value, dict) and value:
        for key, item in value.items():
            rows.extend(flatten(item, path + '/' + key.replace('~', '~0').replace('/', '~1')))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            rows.extend(flatten(item, path + '/' + str(index)))
    else:
        rows.append({'path': path, 'value': canonical(value).decode()})
    return sorted(rows, key=lambda row: row['path'].encode())

choice = json.loads((HERE / 'sources/original-choice-work-class.json').read_bytes())
pin = choice['specification_pin']
rows = []

def append(name, operation, input_value, expected, complete=True):
    envelope = {'protocol': 'seampoint.work-class.adapter/1.0.0-draft.3', 'request_id': 'public.' + name,
                'operation': operation, 'input': input_value}
    rows.append({'name': name, 'request': envelope, 'expected': expected,
                 'expectation_kind': 'COMPLETE_RESULT' if complete else 'SELECTED_DISPOSITION',
                 'wire_base64': base64.b64encode(canonical(envelope) + b'\n').decode()})

def artifact_input(kind, artifact):
    return {'kind': kind, 'specification_pin': pin, 'artifact_bytes_base64': base64.b64encode(canonical(artifact)).decode()}

def admitted(name, kind, artifact, domain):
    identity = digest(domain, artifact)
    value = artifact_input(kind, artifact)
    append(name + '-validate', 'validate', value, {'status': 'ACCEPTED', 'digest': identity})
    append(name + '-readback', 'readback', value, {'status': 'READBACK', 'digest': identity, 'lines': flatten(artifact)})

for labels_reverse in (False, True):
    for routes_reverse in (False, True):
        artifact = copy.deepcopy(choice)
        if labels_reverse:
            artifact['choices'][0]['label_values'].reverse()
        if routes_reverse:
            artifact['relationships'][0:2] = list(reversed(artifact['relationships'][0:2]))
        admitted('choice-labels-' + str(labels_reverse).lower() + '-routes-' + str(routes_reverse).lower(), 'WORK_CLASS', artifact, 'work-class-definition')

for name in ('duplicate-label', 'missing-route', 'extra-route', 'ambiguous-route', 'wrong-type'):
    artifact = copy.deepcopy(choice)
    if name == 'duplicate-label':
        artifact['choices'][0]['label_values'][1] = copy.deepcopy(artifact['choices'][0]['label_values'][0])
    elif name == 'missing-route':
        artifact['relationships'].pop(1)
    elif name == 'extra-route':
        edge = copy.deepcopy(artifact['relationships'][1])
        edge['label']['value'] = 'UNDECLARED'
        artifact['relationships'].insert(2, edge)
    elif name == 'ambiguous-route':
        artifact['relationships'][1]['label'] = copy.deepcopy(artifact['relationships'][0]['label'])
    else:
        artifact['choices'][0]['label_values'][0]['type_ref'] = 't.identity'
        artifact['relationships'][0]['label']['type_ref'] = 't.identity'
    append(name, 'validate', artifact_input('WORK_CLASS', artifact),
           {'status': 'REFUSED', 'code': 'SCHEMA_INVALID' if name == 'duplicate-label' else 'DEFINITION_INVALID', 'path': ''})

legacy = json.loads((HERE / 'sources/legacy-work-class.json').read_bytes())
admitted('legacy-work', 'WORK_CLASS', legacy, 'work-class-definition')
for filename in ('legacy-authority-authority-index-dossier.json', 'legacy-authority-authority-seal-dossier.json'):
    artifact = json.loads((HERE / 'sources' / filename).read_bytes())
    admitted(filename.replace('.json', ''), 'AUTHORITY_DEFINITION', artifact, 'authority-definition')
standalone = json.loads((HERE / 'sources/standalone-authority.json').read_bytes())
admitted('legacy-standalone-full-carrier', 'AUTHORITY_DEFINITION', standalone, 'authority-definition')
for row in projection_proposal_inputs():
    append(row['name'], 'step', row['input'], row['expected'], row['expected']['status'] != 'STEP')

artifact = copy.deepcopy(choice)
artifact['relationships'][0]['label']['value'] = 'ESCALATE'
append('route-domain-mismatch', 'validate', artifact_input('WORK_CLASS', artifact),
       {'status': 'REFUSED', 'code': 'DEFINITION_INVALID', 'path': ''})

manifest = json.loads((HERE / 'CASES.json').read_bytes())
assert len(rows) == len(manifest['cases']) == 28
assert manifest['base_case_count'] == 27
for row, sealed in zip(rows, manifest['cases']):
    assert row['name'] == sealed['name']
    assert row['expectation_kind'] == sealed['expectation_kind']
    assert hashlib.sha256(canonical(row)).hexdigest() == sealed['sealed_row_sha256']
    assert base64.b64decode(row['wire_base64'], validate=True) == (HERE / sealed['request']['path']).read_bytes()
    assert canonical(row['expected']) + b'\n' == (HERE / sealed['expected']['path']).read_bytes()
assert hashlib.sha256(canonical(rows[:27])).hexdigest() == manifest['base_case_rows_sha256']
assert hashlib.sha256(canonical(rows)).hexdigest() == manifest['case_rows_sha256']
print(json.dumps({'cases': len(rows), 'derivation_matches_presealed_cases': True, 'predecessor_sealed_inputs_sha256': manifest['predecessor_sealed_inputs_sha256']}))
