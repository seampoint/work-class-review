#!/usr/bin/env python3
"""R-g: commit each usable numerical history despite sole exclusive withholding."""
import copy
import importlib
import json
from corpus_common import CASES, candidate_pin, digest, exact_case, write_canonical_json
from authority_fixture import authority_specimen
from reservation_fixture import zero_state, host_and_event, request, transition, reservation_record, budget_result


def main():
    admission = importlib.import_module('build-phase3-admission-cases')
    facts = admission.both_facts(admission.KEYS)
    for suffix, instance in [('a', 'instance-1'), ('b', 'instance-2')]:
        authority, result = authority_specimen(shared_budgets=['anchor-a', 'anchor-b'],
            exclusive_keys=admission.KEYS, instance_id=instance, occurrence_id='issue:1')
        authority['clock'] = copy.deepcopy(facts['clock'])
        facts['authority_' + suffix], facts['authority_' + suffix + '_result'] = authority, result
    facts['configuration']['slots'] = [{'anchor': n, 'exposure_domain': 'exposure-' + n}
                                       for n in ['anchor-a', 'anchor-b']]
    definitions, histories, authorizations = [], [], []
    state = zero_state(facts)
    for anchor in ['anchor-a', 'anchor-b']:
        budget = copy.deepcopy(facts['budget'])
        budget.update(anchor=anchor, exposure_domain='exposure-' + anchor)
        definition_digest = digest('budget-definition', budget)
        authorization = copy.deepcopy(facts['authorizations'][0])
        authorization.update(budget_digest=definition_digest,
            envelope_digest=digest('authority-envelope', facts['authority_a']['envelope']),
            work_class_digest=digest('authority-work-class', facts['authority_a']['work_class']))
        authorization['authority_definition'].update({n: copy.deepcopy(facts['authority_a'][n])
                                                     for n in ['source', 'work_class', 'envelope']})
        history = copy.deepcopy(facts['history'])
        history['budget_digest'] = definition_digest
        event, host = host_and_event(facts, 'REGISTER', 'register-' + anchor,
            state['core']['revision'], {'definition': budget, 'authorizations': [authorization], 'history': history})
        core = copy.deepcopy(state['core'])
        core['budgets'].append({'definition': budget, 'definition_digest': definition_digest,
                               'authorizations': [authorization], 'history': history})
        core['budgets'].sort(key=lambda r: r['definition']['anchor'])
        state = transition(state, event, host, core, 'REGISTERED')['state']
        definitions.append(budget); histories.append(history); authorizations.append(authorization)
    selected = sorted(copy.deepcopy(histories), key=lambda r: r['budget_digest'])
    event, host = host_and_event(facts, 'RESERVE', 'reserve-a', state['core']['revision'],
        {'authority': facts['authority_a'], 'histories': selected,
         'exclusive_keys': admission.claims(facts, 'authority_a')}, administration=False)
    core = copy.deepcopy(state['core'])
    reservation = reservation_record(facts, 'authority_a', 'reserve-a')
    reservation['contributions'] = [{'anchor': n, 'mapping': 'pay',
        'occurrence': reservation['occurrence_key'],
        'key': [{'type_ref': 'beneficiary', 'value': 'employee-7'}],
        'value': {'type_ref': 'amount', 'value': '150'}} for n in ['anchor-a', 'anchor-b']]
    core['reservations'] = [reservation]
    core['exclusive_keys'] = admission.key_states(facts, 'authority_a', 'reserve-a')
    budgets = [budget_result({**facts, 'budget': b}, '950')[0] for b in definitions]
    state = transition(state, event, host, core, 'RESERVED', reservation_id='reserve-a',
                       authority_result=facts['authority_a_result'], budgets=budgets)['state']
    group = CASES / 'phase3-mixed-exclusive-history'
    group.mkdir(parents=True, exist_ok=True)
    count = 0
    for fresh_index in [0, 1]:
        for bad_kind in ['STALE', 'UNAVAILABLE']:
            current = admission.unrelated(histories[fresh_index])
            bad = copy.deepcopy(histories[1 - fresh_index])
            if bad_kind == 'STALE':
                bad['as_of'] = '2026-09-10T04:20:00Z'
            else:
                bad.update(status='UNAVAILABLE', complete=False, as_of=None, revision=None, journal=None)
            supplied = sorted([current, bad], key=lambda r: r['budget_digest'])
            event, host = host_and_event(facts, 'RESERVE',
                f'mixed-exclusive-{fresh_index}-{bad_kind.lower()}', state['core']['revision'],
                {'authority': facts['authority_b'], 'histories': supplied,
                 'exclusive_keys': admission.claims(facts, 'authority_b')}, administration=False)
            core = copy.deepcopy(state['core'])
            core['budgets'][fresh_index]['history'] = copy.deepcopy(current)
            expected = transition(state, event, host, core, 'WITHHELD', budgets=[],
                authority_result=facts['authority_b_result'], reasons=['EXCLUSIVE_KEY_OCCUPIED'])
            derivation = ('R-g and EXCLUSIVE-KEY-HISTORY section6: occupied key withholding has '
                'sole EXCLUSIVE_KEY_OCCUPIED and empty budgets. Commit the independently fresh '
                'complete journal, retain the other journal unchanged, and create no reservation '
                'or key. Current history does not retract an effect. Source-derived before consumers.')
            for replay in [False, True]:
                count += 1
                cid = f'C3-P3-MEXH-{count:03d}'
                value = request(state, event, host)
                wanted = expected
                if replay:
                    value = request(expected['state'], event, host)
                    wanted = copy.deepcopy(expected)
                    wanted['replay'] = True
                write_canonical_json(group / (cid + '.json'), exact_case(cid, 'aggregate-step', value,
                    wanted, ['RES-003', 'RES-005', 'RES-007A', 'RES-WIRE-003', 'RES-WIRE-004'],
                    derivation + (' Exact event replay returns the retained receipt and current state without another history commit.' if replay else '')))
    print(json.dumps({'candidate_pin': candidate_pin(), 'cases': count}, indent=2))


if __name__ == '__main__':
    main()
