"""Derive authority referral filtering and replay from admitted decisions."""
from __future__ import annotations

import copy

from corpus_common import CASES, digest, exact_case, write_canonical_json
from equipment_completion_fixture import completion_authority_mutator, completion_definition_mutator, decision_basis
from equipment_dispatch_fixture import authorization_event, authorization_result, retained
from equipment_observation_fixture import observation, requirement, source_refusal
from lifecycle_factory import admitted_transition, base_lifecycle, permitted_proposal, replay_result, step_input, withheld_proposal


GROUP = CASES / 'equipment-referrals'


def referral_base():
    def authority(supplied, original):
        completion_authority_mutator(supplied, original)
        req = requirement('current-safety', purpose='SAFETY_HOLD', source='synthetic-equipment-holds',
            subject={'kind': 'PROPOSAL_FIELD', 'field': 'card_id'}, record_id='asset-safety-1')
        req['relations'][0]['id'] = 'safety-enabled'
        supplied['envelope']['source_observation_requirements'].append(req)
        supplied['envelope']['source_observation_requirements'].sort(key=lambda row: row['id'])
        supplied['observations'].append(observation(req, supplied))
    def definition(supplied):
        completion_definition_mutator(supplied)
        operation = next(row for row in supplied['steps'] if row['kind'] == 'OPERATION')
        common = {'queue': 'maintenance-review', 'safe_state': 'no-entry-or-command'}
        operation['referral_policy']['authority'] = [
            {'id': 'authority-owner', 'destination_role': 'reliability-supervisor',
                'purpose': 'review-authority-failure', 'via_role': None, 'requirement_ids': [], **common},
            {'id': 'safety-owner', 'destination_role': 'safety-compliance-lead',
                'purpose': 'review-safety-hold', 'via_role': 'reliability-supervisor',
                'requirement_ids': ['current-safety'], **common}]
    return base_lifecycle(authority_mutator=authority, definition_mutator=definition)


def add_referrals(base, before, event, outcome, authority_result, requirement_id):
    receipt = outcome['decision']
    result_digest = digest('authority-result', authority_result)
    permit_id = receipt['permit_digest']
    basis = decision_basis(before, event, receipt['disposition'], receipt['reason_codes'], permit_id,
        authority_result_digest=result_digest)
    basis_digest = digest('decision-basis', basis)
    evidence = [result_digest]
    evaluation = next((row for row in outcome['state'].get('authorization_evaluations', [])
        if row['event_id'] == event['event_id']), None)
    if evaluation is not None:
        evidence.append(evaluation['evaluation_digest'])
    proposal_evaluation = next((row for row in outcome['state'].get('proposal_authority_evaluations', [])
        if row['event']['event_id'] == event['event_id']), None)
    if proposal_evaluation is not None:
        evidence.append(proposal_evaluation['evaluation_digest'])
    routes = base['definition']['steps'][0]['referral_policy']['authority']
    referrals = []
    for route in routes:
        if route['requirement_ids'] and requirement_id not in route['requirement_ids']:
            continue
        body = {'event_id': event['event_id'], 'event_digest': digest('runtime-event', event),
            'instance_id': before['instance_id'],
            'occurrence_id': event['occurrence']['occurrence_id'] if event['kind'] == 'PROPOSE' else event['permit']['occurrence']['occurrence_id'],
            'decision_basis_digest': basis_digest, 'terminal_digest': None, 'cause_digest': result_digest,
            **{name: route[name] for name in ['destination_role', 'queue', 'purpose', 'safe_state', 'via_role']},
            'evidence_digests': sorted(set(evidence))}
        referrals.append({'referral_digest': digest('referral-intent', body), **body})
    def mutate(state):
        for name in ['proposals', 'authorizations', 'authorization_evaluations', 'proposal_authority_evaluations']:
            if name in outcome['state']:
                state[name] = copy.deepcopy(outcome['state'][name])
        state['referrals'].extend(referrals)
        state['referrals'].sort(key=lambda row: row['referral_digest'])
    return admitted_transition(before, event, disposition=receipt['disposition'], reason_codes=receipt['reason_codes'],
        details=copy.deepcopy(receipt['details']), receipt_permit_digest=permit_id,
        receipt_authority_result_digest=result_digest,
        receipt_authorization_evaluation_digest=evaluation['evaluation_digest'] if evaluation else None,
        receipt_proposal_authority_evaluation_digest=proposal_evaluation['evaluation_digest'] if proposal_evaluation else None,
        receipt_decision_basis_digest=basis_digest, mutate=mutate)


def fail_event(event, requirement_id):
    supplied = copy.deepcopy(event)
    row = next(row for row in supplied['authority_input']['observations'] if row['query'].get('requirement_id') == requirement_id)
    row['fields'][0]['value']['value'] = False
    supplied['observation_digests'] = sorted({digest('authority-observation', row) for row in supplied['authority_input']['observations']})
    if supplied['kind'] == 'AUTHORIZE_DISPATCH':
        supplied['authorization_fence'] = None
    return supplied


def main():
    cases = []
    for point in ['PROPOSE', 'DISPATCH']:
        for req_id in ['current-session', 'current-safety']:
            base = referral_base()
            permitted = permitted_proposal(base)
            event = base['proposal_event'] if point == 'PROPOSE' else authorization_event(base, permitted)
            event = fail_event(event, req_id)
            refusal = source_refusal(event['authority_input'], req_id, 'SOURCE_OBSERVATION_RELATIONS')
            before = base['clock_result']['state'] if point == 'PROPOSE' else permitted['state']
            initial = withheld_proposal(base, event, refusal) if point == 'PROPOSE' else authorization_result(base, permitted, event, refusal=refusal)
            expected = add_referrals(base, before, event, initial, refusal, req_id)
            index = len(cases) + 1
            cases.append(exact_case(f'C3-EAR-{index:03d}', 'step', step_input(base, before, event), expected,
                ['LIFE-006A', 'AUTH-007'], 'Admitted authority withholding creates the general owner referral; only a failed current-safety requirement selects the additional Safety Compliance Lead referral via Reliability Supervisor. Both bind the exact decision and evidence.'))
            replay = replay_result(expected['state'], event['event_id'])
            index = len(cases) + 1
            cases.append(exact_case(f'C3-EAR-{index:03d}', 'step', step_input(base, expected['state'], event), replay,
                ['LIFE-006A', 'LIFE-013'], 'Exact replay retains the original referral intents and decision basis without another intent, state revision or external delivery assertion.'))
    for row in cases:
        write_canonical_json(GROUP / (row['id'] + '.json'), row)
    print({'cases': len(cases), 'derivation': 'normative-only; consumers not consulted'})


if __name__ == '__main__':
    main()
