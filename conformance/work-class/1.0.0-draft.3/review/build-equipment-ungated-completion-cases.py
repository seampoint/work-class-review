"""Derive STOP_RETAIN records for explicitly ungated operation declarations."""
from __future__ import annotations

from corpus_common import CASES, exact_case, write_canonical_json
from equipment_completion_fixture import (completion_authority_mutator, completion_definition_mutator,
    completion_native, lookup_event, lookup_result, terminal_effect_result)
from equipment_dispatch_fixture import retained
from lifecycle_factory import (base_lifecycle, dispatch_event, dispatch_result, governed_effect_event,
    permitted_proposal, step_input)


GROUP = CASES / 'equipment-ungated-completion'


def base_and_dispatch():
    def authority(supplied, original):
        completion_authority_mutator(supplied, original)
        supplied['work_class']['steps'][0].pop('dispatch_gate')
    base = base_lifecycle(authority_mutator=authority, definition_mutator=completion_definition_mutator)
    permitted = permitted_proposal(base)
    event = dispatch_event(base, permitted, event_id='ungated-send')
    output = dispatch_result(permitted, event, disposition='DISPATCH_RECORDED', reasons=[], occurrence_status='DISPATCHED')
    return base, permitted, retained(output, permitted['permit'])


def main():
    cases = []
    base, permitted, dispatched = base_and_dispatch()
    native = completion_native(base, dispatched, status='OUTCOME_UNKNOWN')
    event = governed_effect_event(permitted, dispatched, native, event_id='ungated-unknown')
    expected = terminal_effect_result(base, dispatched, event, classification='UNKNOWN',
        disposition='OUTCOME_RETAINED', reason_codes=['UNKNOWN_OUTCOME'],
        occurrence_status='OUTCOME_UNKNOWN', disputed=False)
    cases.append(exact_case('C3-EU-001', 'step', step_input(base, dispatched['state'], event), expected,
        ['LIFE-006A', 'LIFE-010'], 'A declared ungated STOP_RETAIN operation retains its original complete authority basis and exact dispatch. Unknown completion stops it, with authorization_digest:null and no invented authorization.'))
    event = lookup_event(base, dispatched)
    expected = lookup_result(base, dispatched, event)
    cases.append(exact_case('C3-EU-002', 'step', step_input(base, dispatched['state'], event), expected,
        ['LIFE-006A', 'LIFE-010'], 'Ungated completion lookup binds the exact permit and dispatch with null authorization throughout query, event, retained check and terminal record. It does not create or bypass a declared gate.'))
    native = completion_native(base, dispatched)
    event = governed_effect_event(permitted, dispatched, native, event_id='ungated-exact')
    expected = terminal_effect_result(base, dispatched, event, classification='MATCHED',
        disposition='COMPLETED', reason_codes=[], occurrence_status=None, disputed=False,
        complete_disposition='SUCCEEDED', route=True)
    cases.append(exact_case('C3-EU-003', 'step', step_input(base, dispatched['state'], event), expected,
        ['LIFE-006A', 'LIFE-010'], 'An exact full completion for an explicitly ungated profile can finish normally. Its complete retained proposal basis is checked, and no terminal failure or synthetic gate evidence is added.'))
    for row in cases:
        write_canonical_json(GROUP / (row['id'] + '.json'), row)
    print({'cases': len(cases), 'derivation': 'normative-only; consumers not consulted'})


if __name__ == '__main__':
    main()
