"""Derive boundary-referral bindings without consulting consumers."""
from __future__ import annotations

import copy

from corpus_common import CASES, candidate_pin, digest, exact_case, write_canonical_json
from equipment_completion_fixture import completion_base


GROUP = CASES / 'equipment-boundary'


def boundary_fixture(scope='PHYSICAL_CONTROL'):
    base = completion_base()
    definition = copy.deepcopy(base['definition'])
    definition['boundary_exits'] = [{
        'id': 'equipment-control-exit', 'scope': scope,
        'owner_role': 'OperationsControlRoomLead', 'queue': 'operations-control-room',
        'purpose': 'separate-control-procedure', 'safe_state': 'no-register-write-or-physical-command',
        'reentry_requirements': ['new-approval', 'new-request', 'separate-control-procedure'],
    }]
    definition_digest = digest('work-class-definition', definition)
    request_digest = digest('external-boundary-request', {'request_id': 'physical-request-1', 'scope': scope})
    body = {'definition_digest': definition_digest, 'exit_id': 'equipment-control-exit',
        'request_digest': request_digest, 'scope': scope, 'owner_role': 'OperationsControlRoomLead',
        'queue': 'operations-control-room', 'purpose': 'separate-control-procedure',
        'safe_state': 'no-register-write-or-physical-command', 'evidence_ref': 'host-boundary-classification-1'}
    body['provenance_digest'] = digest('boundary-referral-provenance', body)
    referral = {'referral_digest': digest('boundary-referral', body), **body}
    supplied = {'profile': 'LINEAR', 'role': 'REVIEW_EVIDENCE', 'specification_pin': candidate_pin(),
        'definition': definition, 'definition_digest': definition_digest,
        'request_digest': request_digest, 'boundary_referral': referral}
    expected = {'status': 'EVIDENCE_VALID', 'profile': 'LINEAR', 'role': 'REVIEW_EVIDENCE',
        'specification_pin': candidate_pin(), 'kind': 'BOUNDARY_REFERRAL',
        'definition_digest': definition_digest, 'request_digest': request_digest,
        'referral_digest': referral['referral_digest']}
    return supplied, expected


def reseal(supplied):
    row = supplied['boundary_referral']
    body = {k: v for k, v in row.items() if k not in {'referral_digest', 'provenance_digest'}}
    row['provenance_digest'] = digest('boundary-referral-provenance', body)
    row['referral_digest'] = digest('boundary-referral', {k: v for k, v in row.items() if k != 'referral_digest'})


def main():
    rows = []
    def add(number, supplied, expected, rule):
        rows.append(exact_case(f'C3-EB-{number:03d}', 'check-evidence', supplied, expected,
            ['LIFE-006A', 'BOUND-001'], rule))
    for number, scope in [(1, 'PHYSICAL_CONTROL'), (2, 'MIXED_CONTROL')]:
        supplied, expected = boundary_fixture(scope)
        add(number, supplied, expected, 'The complete host boundary record binds the exact definition, request digest and declared exit. Binding validation creates no lifecycle state, work permission or delivery assertion.')
    for number, field, replacement in [(3, 'exit_id', 'invented-exit'),
            (4, 'owner_role', 'MaintenanceRecordsClerk'), (5, 'queue', 'undeclared-queue'),
            (6, 'purpose', 'execute-physical-command'), (7, 'safe_state', 'send-again'),
            (8, 'scope', 'MIXED_CONTROL'), (9, 'request_digest', 'sha256:' + '1' * 64),
            (10, 'definition_digest', 'sha256:' + '2' * 64)]:
        supplied, _ = boundary_fixture()
        supplied['boundary_referral'][field] = replacement
        reseal(supplied)
        expected = {'status': 'EVIDENCE_INVALID', 'profile': 'LINEAR', 'role': 'REVIEW_EVIDENCE',
            'specification_pin': candidate_pin(), 'code': 'BINDING_MISMATCH', 'path': ''}
        add(number, supplied, expected, f'A fully rehashed boundary referral changes {field}; its bytes cannot change the declared exit or outer binding.')
    for number, field in [(11, 'provenance_digest'), (12, 'referral_digest')]:
        supplied, _ = boundary_fixture()
        supplied['boundary_referral'][field] = 'sha256:' + '3' * 64
        expected = {'status': 'EVIDENCE_INVALID', 'profile': 'LINEAR', 'role': 'REVIEW_EVIDENCE',
            'specification_pin': candidate_pin(), 'code': 'BINDING_MISMATCH', 'path': ''}
        add(number, supplied, expected, 'Complete provenance and referral digest preimages are recomputed; a caller digest alone establishes no binding.')
    for row in rows:
        write_canonical_json(GROUP / (row['id'] + '.json'), row)
    print({'cases': len(rows), 'derivation': 'normative-only; consumers not consulted'})


if __name__ == '__main__':
    main()
