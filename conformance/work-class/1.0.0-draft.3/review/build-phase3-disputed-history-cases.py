#!/usr/bin/env python3
"""Probe-informed R-o disputed-renewal controls; no consumer imports or calls."""
import copy
import json
from corpus_common import CASES, candidate_pin, digest, exact_case, write_canonical_json
import recovery_fixture as rec
from reservation_fixture import host_and_event, request, transition


def main():
    f = rec.facts_for('2')
    state = rec.disputed(f)
    group = CASES / 'phase3-disputed-history'
    group.mkdir(parents=True, exist_ok=True)
    ids = []
    statuses = [('UNAVAILABLE', 'HISTORY_UNAVAILABLE'),
                           ('INCOMPLETE', 'HISTORY_INCOMPLETE'),
                           ('CONFLICT', 'HISTORY_CONFLICT'),
                           ('STALE', 'HISTORY_STALE'), ('AVAILABLE', None)]
    for status, reason, pending in [(*s, False) for s in statuses] + [(*s, True) for s in statuses]:
        history = copy.deepcopy(f['history'])
        if status == 'STALE':
            history['as_of'] = '2026-09-10T04:20:00Z'
        elif status != 'AVAILABLE':
            history.update(status=status, complete=False, as_of=None, revision=None, journal=None)
        event, host = host_and_event(f, 'RENEW', 'renew-disputed-' + status.lower(),
                                    state['core']['revision'],
                                    {'reservation': 'reserve-a', 'authority': f['authority_a'],
                                     'histories': [history]}, administration=False)
        if pending:
            host['recovery'] = {
                'caller': f['authority_a']['proposal']['executor']['actor'],
                'recovery_bases': [], 'authenticated_records': [],
                'pending_evidence': [{'target': {'kind': 'RESERVATION',
                    'registry_digest': digest('reservation-registry', state['core']['configuration']),
                    'reservation': 'reserve-a'}, 'record_digest': 'sha256:' + '9' * 64}]}
        # No permission, renewal or aggregate result. The unusable supplied journal
        # cannot replace retained history; the usable control supplies identical bytes.
        reasons = sorted(['EXPOSURE_DISPUTED'] + ([reason] if reason else []) +
                         (['RECOVERY_PENDING_EVIDENCE'] if pending else []))
        expected = transition(state, event, host, copy.deepcopy(state['core']), 'WITHHELD',
                              reservation_id='reserve-a', budgets=[],
                              authority_result=f['authority_a_result'], reasons=reasons)
        cid = f'C3-P3-DHIST-{len(ids) + 1:03d}'
        ids.append(cid)
        write_canonical_json(group / (cid + '.json'), exact_case(
            cid, 'aggregate-step', request(state, event, host), expected,
            ['RES-005', 'RES-WIRE-004'],
            'Approved R-o retains applicable numerical history reasons; a RENEW of its own '
            'DISPUTED reservation additionally retains EXPOSURE_DISPUTED and performs no '
            'aggregate evaluation. No reservation, permit or unusable journal replacement. '
            'Probe-informed source derivation, sealed before consumer execution. Status=' + status +
            ('; pending evidence independently adds RECOVERY_PENDING_EVIDENCE under REC-016.' if pending else '')))
    print(json.dumps({'candidate_pin': candidate_pin(), 'cases': len(ids)}, indent=2))


if __name__ == '__main__':
    main()
