"""Derive portable original-event admission and fully rehashed refusal controls."""
from __future__ import annotations

import base64
import copy
import json
import runpy

from checkpoint_reseal import reseal_last_transition
from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from equipment_completion_fixture import decision_basis
from fixture_factory import add_seconds, available_clock
from lifecycle_factory import admitted_transition, base_lifecycle, state_digest, stateful_refusal, step_input


GROUP = CASES / 'equipment-retained-evidence'


def load(group, name):
    return json.loads((CASES / group / (name + '.json')).read_text())


def input_after(case, event_id):
    value = copy.deepcopy(case['input'])
    state = copy.deepcopy(case['expected']['state'])
    latest = max((row for row in state['clocks'] if row['status'] == 'AVAILABLE'), key=lambda row: int(row['revision']))
    clock = available_clock(latest['source'], str(int(latest['revision']) + 1), add_seconds(latest['observed_time'], '60'))
    value.update(state=state, state_digest=state_digest(state), event={
        'schema': 'seampoint.work-class/1.0.0-draft.3/runtime-event', 'event_id': event_id,
        'kind': 'CLOCK', 'instance_id': state['instance_id'], 'expected_state_revision': state['revision'],
        'expected_state_digest': state_digest(state), 'clock': clock, 'activation_clocks': []})
    return value


def seal(value):
    reseal_last_transition(value['state'])
    value['state_digest'] = state_digest(value['state'])
    value['event']['expected_state_digest'] = value['state_digest']


def retarget_event(state, event):
    event_digest = digest('runtime-event', event)
    receipt = next(row for row in state['receipts'] if row['event_id'] == event['event_id'])
    receipt['event_digest'] = event_digest
    replay = next(row for row in state['replays'] if row['event_id'] == event['event_id'])
    replay['event_digest'] = event_digest
    for row in state['proposals']:
        if row['event_id'] == event['event_id']:
            row['event_digest'] = event_digest
            row['proposal_digest'] = digest('proposal', event)
    return receipt


def main():
    cases = []
    native = input_after(load('equipment-completion', 'C3-EC-001'), 'restart-full-native-event')
    proposal = input_after(load('equipment-referrals', 'C3-EAR-003'), 'restart-full-proposal-referral')
    for value in [native, proposal]:
        clock = value['event']['clock']
        def mutate(state):
            state['clocks'].append(copy.deepcopy(clock))
            state['clocks'].sort(key=lambda row: (row['source'].encode('utf-8'), int(row['revision'])))
        expected = admitted_transition(value['state'], value['event'], disposition='CLOCK_RECORDED', reason_codes=[],
            details=[{'kind': 'CLOCK', 'source': clock['source'], 'revision': clock['revision'], 'status': 'AVAILABLE'}], mutate=mutate)
        cases.append(exact_case(f'C3-EVE-{len(cases)+1:03d}', 'step', value, expected, ['LIFE-006A', 'LIFE-019'],
            'The exact author-derived checkpoint retains complete original evidence. Restart admits it and records the next clock without changing the original decision, terminal state or referrals.'))

    missing = copy.deepcopy(native)
    missing['state']['outcomes'][0].pop('source_event')
    outcome = missing['state']['outcomes'][0]
    outcome['outcome_digest'] = digest('outcome', {key: value for key, value in outcome.items() if key != 'outcome_digest'})
    faults = [(missing, 'A STOP_RETAIN outcome cannot omit its complete original event after all outer checkpoint commitments are recomputed.')]

    changed = copy.deepcopy(native)
    outcome = changed['state']['outcomes'][0]
    field = next(row for row in outcome['native_evidence']['actual_fields'] if row['name'] == 'amount')
    field['value']['value'] = '151'
    outcome['native_evidence']['record_digest'] = digest('synthetic-provider-changed-fields', outcome['native_evidence']['actual_fields'])
    outcome['source_event']['native_evidence'] = copy.deepcopy(outcome['native_evidence'])
    outcome['event_digest'] = digest('runtime-event', outcome['source_event'])
    retarget_event(changed['state'], outcome['source_event'])
    outcome['outcome_digest'] = digest('outcome', {key: value for key, value in outcome.items() if key != 'outcome_digest'})
    changed['state']['completed'][0]['evidence_digest'] = digest('native-evidence', outcome['native_evidence'])
    faults.append((changed, 'Both retained native bodies, the full original event and all outcome/completion/checkpoint commitments are rebound to changed amount151. The unchanged MATCHED classification is unreachable because the permitted request amount is150.'))

    wrong_root = copy.deepcopy(native)
    outcome = wrong_root['state']['outcomes'][0]
    outcome['source_event']['expected_state_digest'] = digest('wrong-original-state', {})
    outcome['event_digest'] = digest('runtime-event', outcome['source_event'])
    receipt = retarget_event(wrong_root['state'], outcome['source_event'])
    receipt['state_before_digest'] = outcome['source_event']['expected_state_digest']
    outcome['outcome_digest'] = digest('outcome', {key: value for key, value in outcome.items() if key != 'outcome_digest'})
    faults.append((wrong_root, 'The full original event and receipt cannot replace the preceding authoritative state root with a rehashed unrelated digest.'))

    missing = copy.deepcopy(proposal)
    missing['state']['proposal_authority_evaluations'] = []
    faults.append((missing, 'An admitted authority withholding with governed referrals must retain its full original PROPOSE evaluation; a receipt digest cannot replace that input and result.'))

    changed = copy.deepcopy(proposal)
    state = changed['state']
    evaluation = state['proposal_authority_evaluations'][0]
    original_evaluation_digest = evaluation['evaluation_digest']
    event = evaluation['event']
    observation = next(row for row in event['authority_input']['observations'] if row['query'].get('requirement_id') == 'current-safety')
    observation['fields'][0]['value']['value'] = True
    event['observation_digests'] = sorted({digest('authority-observation', row) for row in event['authority_input']['observations']})
    receipt = retarget_event(state, event)
    evaluation['evaluation_digest'] = digest('proposal-authority-evaluation', {key: value for key, value in evaluation.items() if key != 'evaluation_digest'})
    receipt['proposal_authority_evaluation_digest'] = evaluation['evaluation_digest']
    basis = decision_basis(state, event, receipt['disposition'], receipt['reason_codes'], receipt['permit_digest'], authority_result_digest=evaluation['authority_result_digest'])
    receipt['decision_basis_digest'] = digest('decision-basis', basis)
    for referral in state['referrals']:
        referral['event_digest'] = digest('runtime-event', event)
        referral['decision_basis_digest'] = receipt['decision_basis_digest']
        referral['evidence_digests'] = sorted(evaluation['evaluation_digest'] if value == original_evaluation_digest else value for value in referral['evidence_digests'])
        referral['referral_digest'] = digest('referral-intent', {key: value for key, value in referral.items() if key != 'referral_digest'})
    state['referrals'].sort(key=lambda row: row['referral_digest'])
    faults.append((changed, 'The complete original authority observation is changed to a passing safety fact, and event/proposal/evaluation/decision-basis/referral/checkpoint digests are all rebound. Independent authority reevaluation cannot retain the old safety refusal and safety referral.'))

    for value, derivation in faults:
        seal(value)
        cases.append(exact_case(f'C3-EVE-{len(cases)+1:03d}', 'step', value, stateful_refusal(value['state'], 'STATE_INVALID'),
            ['LIFE-006A', 'LIFE-019'], derivation))
    loop_definition = runpy.run_path(str(GROUP.parents[1] / 'review/build-loop-cases.py'))['loop_definition']
    loop = base_lifecycle(definition_mutator=loop_definition)
    cases.append(exact_case('C3-EVE-008', 'deploy', loop['deploy_input'], loop['deploy_result'],
        ['LIFE-003', 'LIFE-019'], 'Deployment of a declared loop entry creates its LOOP/pass 1 enclosing segment, exact occurrence identity and activation basis under COMPOSITION 4.2.'))
    loop_clock = step_input(loop, loop['deploy_result']['state'], loop['clock_event'])
    cases.append(exact_case('C3-EVE-009', 'step', loop_clock, loop['clock_result'], ['LIFE-014', 'LIFE-019'],
        'A fresh process admits the independently derived LOOP/pass 1 deployment checkpoint and records its first authority clock without dropping the loop occurrence identity.'))
    frozen = input_after(load('fanout-expansion', 'D2-075'), 'restart-stopped-unexpanded-fanout')
    clock = frozen['event']['clock']
    def retain_clock(state):
        state['clocks'].append(copy.deepcopy(clock))
        state['clocks'].sort(key=lambda row: (row['source'].encode('utf-8'), int(row['revision'])))
    frozen_expected = admitted_transition(frozen['state'], frozen['event'], disposition='CLOCK_RECORDED', reason_codes=[],
        details=[{'kind': 'CLOCK', 'source': clock['source'], 'revision': clock['revision'], 'status': 'AVAILABLE'}], mutate=retain_clock)
    cases.append(exact_case('C3-EVE-010', 'step', frozen, frozen_expected, ['LIFE-014', 'LIFE-019'],
        'COMPOSITION preflight retains the exact frozen fanout object set after LIMIT_EXCEEDED while creating zero obligations. A fresh process admits this stopped checkpoint, records a new clock and creates no object execution.'))
    for group, name in [('choice-routing', 'D2-046'), ('choice-routing', 'D2-133'),
            ('fanout-expansion', 'D2-056'), ('fanout-expansion', 'D2-143'),
            ('repair-round-composition-controls', 'C2-empty-fanout-advance-into-parent-join')]:
        value = input_after(load(group, name), 'restart-after-' + name.lower())
        clock = value['event']['clock']
        expected = admitted_transition(value['state'], value['event'], disposition='CLOCK_RECORDED', reason_codes=[],
            details=[{'kind': 'CLOCK', 'source': clock['source'], 'revision': clock['revision'], 'status': 'AVAILABLE'}], mutate=retain_clock)
        cases.append(exact_case(f'C3-EVE-{len(cases)+1:03d}', 'step', value, expected, ['LIFE-014', 'LIFE-019'],
            'The independently derived ' + name + ' result retains an invalid choice label or a joined empty fanout under COMPOSITION and LIFE-010. Fresh checkpoint admission preserves its disposition, exact evidence and any owning parent before recording the next clock.'))
    missing_root_loop = copy.deepcopy(loop_clock)
    state = missing_root_loop['state']
    active = state['active'][0]
    root = active['occurrence']
    root['enclosing'] = []
    root['occurrence_id'] = digest('occurrence', {key: value for key, value in root.items() if key != 'occurrence_id'})
    active['activation_event_digest'] = digest('deployment-activation', {
        'deployment_authorization_digest': state['deployment_authorization_digest'],
        'instance_id': state['instance_id'], 'occurrence_id': root['occurrence_id']})
    missing_root_loop['state_digest'] = state_digest(state)
    missing_root_loop['event']['expected_state_digest'] = missing_root_loop['state_digest']
    cases.append(exact_case('C3-EVE-016', 'step', missing_root_loop, stateful_refusal(state, 'STATE_INVALID'),
        ['COMP-002', 'LIFE-003', 'LIFE-004', 'LIFE-019'],
        'COMPOSITION 4.2 requires every operation in the declared loop to carry its LOOP segment, and first entry from outside allocates pass 1. LIFE-003 activates that exact root at deployment. This deployment checkpoint omits the root LOOP/pass 1 segment while recomputing its occurrence identity, deployment activation, complete state digest and incoming clock binding. Revision 0 has no receipt or replay to leave stale. All supplied commitments are self-consistent, but the root is unreachable from the declared deployment, so LIFE-019 checkpoint admission returns STATE_INVALID and preserves the exact supplied state.'))
    outside_entry = copy.deepcopy(loop['definition'])
    entry_id = outside_entry['root']
    entry = next(row for row in outside_entry['steps'] if row['id'] == entry_id)
    tail = copy.deepcopy(entry)
    tail['id'] = 'loop-tail'
    entry['completion']['route_label_field'] = None
    entry['completion']['route_label_type_ref'] = None
    outside_entry['steps'].append(tail)
    outside_entry['steps'].sort(key=lambda row: row['id'].encode('utf-8'))
    outside_entry['root'] = tail['id']
    outside_entry['relationships'] = [
        {'kind': 'SEQUENCE', 'from': entry_id, 'to': tail['id']},
        {'kind': 'LABEL', 'from': tail['id'], 'to': entry_id, 'label': {'type_ref': 'STRING', 'value': 'CONTINUE'}},
        {'kind': 'LABEL', 'from': tail['id'], 'to': 'terminal', 'label': {'type_ref': 'STRING', 'value': 'EXIT'}}]
    outside_entry['choices'][0]['step_id'] = tail['id']
    outside_entry['occurrence_limits'].append({'step_id': tail['id'], 'maximum': '2'})
    outside_entry['occurrence_limits'].sort(key=lambda row: row['step_id'].encode('utf-8'))
    declared_loop = outside_entry['loops'][0]
    declared_loop['member_step_ids'] = sorted([entry_id, tail['id']], key=lambda value: value.encode('utf-8'))
    declared_loop['back_edge_from_step_id'] = tail['id']
    cases.append(exact_case('C3-EVE-017', 'validate', {
        'kind': 'WORK_CLASS', 'specification_pin': outside_entry['specification_pin'],
        'artifact_bytes_base64': base64.b64encode(canonical_bytes(outside_entry)).decode('ascii')},
        {'status': 'REFUSED', 'code': 'UNSUPPORTED_FEATURE', 'path': ''},
        ['COMP-002', 'LIFE-003'],
        'The complete two-step loop has the exact cyclic member set, entry, one back edge, positive pass/occurrence bounds and valid tail choice. Its only changed entry premise is that deployment root names the loop tail instead of the declared entry. COMPOSITION 4.2 requires a root inside a loop to equal its entry; deployment is an outside activation and cannot begin at another member. Static admission returns UNSUPPORTED_FEATURE before constructing any root occurrence. The generic protocol refusal has an empty path; a loop diagnostic path is not part of its wire result.'))
    external_tail = copy.deepcopy(outside_entry)
    outside = copy.deepcopy(entry)
    outside['id'] = 'outside-root'
    external_tail['steps'].append(outside)
    external_tail['steps'].sort(key=lambda row: row['id'].encode('utf-8'))
    external_tail['root'] = outside['id']
    external_tail['relationships'].insert(0, {'kind': 'SEQUENCE', 'from': outside['id'], 'to': tail['id']})
    external_tail['occurrence_limits'].append({'step_id': outside['id'], 'maximum': '1'})
    external_tail['occurrence_limits'].sort(key=lambda row: row['step_id'].encode('utf-8'))
    cases.append(exact_case('C3-EVE-018', 'validate', {
        'kind': 'WORK_CLASS', 'specification_pin': external_tail['specification_pin'],
        'artifact_bytes_base64': base64.b64encode(canonical_bytes(external_tail)).decode('ascii')},
        {'status': 'REFUSED', 'code': 'UNSUPPORTED_FEATURE', 'path': ''},
        ['COMP-002'],
        'The root is a separately declared operation outside the exact two-step loop, with its own positive occurrence bound. The one outside relationship targets loop-tail instead of the declared entry; the cyclic member set, unique back edge, loop bounds and tail choice remain valid. COMPOSITION 4.2 requires every relationship entering from outside to target the declared entry. Static admission returns UNSUPPORTED_FEATURE and cannot allocate pass 1 at the loop tail. The generic protocol refusal retains its required empty path.'))
    for row in cases:
        write_canonical_json(GROUP / (row['id'] + '.json'), row)
    print({'cases': len(cases), 'derivation': 'normative-only; consumers not consulted'})


if __name__ == '__main__':
    main()
