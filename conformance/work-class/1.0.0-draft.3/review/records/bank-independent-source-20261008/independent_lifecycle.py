"""Source-derived lifecycle formulas for the frozen bank input scope.

Only the frozen inputs and draft-3 normative contract are used. Prior states are
reconstructed from their frozen deployment and preceding event preimages before
they may enter a new transition. This is a bank-scope oracle, not a runtime.
"""
import json
from functools import lru_cache
from independent_common import BASE, PREFIX, PIN, canon, clone, digest, fields, add_seconds


def same(left, right, label):
    if canon(left) != canon(right):
        raise ValueError(label)


def without(record, *names):
    return {key: value for key, value in record.items() if key not in names}


def state_digest(state):
    projection = clone(state)
    for replay in projection['replays']:
        replay.pop('transaction_digest')
    return digest('work-state', projection)


def readback_paths(value, path=''):
    if isinstance(value, dict) and value:
        return set().union(*(readback_paths(v, path + '/' + k.replace('~', '~0').replace('/', '~1')) for k, v in value.items()))
    if isinstance(value, list) and value:
        return set().union(*(readback_paths(v, path + '/' + str(j)) for j, v in enumerate(value)))
    return {path}


def admitted_definition(i):
    d = i['definition']
    same(i['specification_pin'], PIN, 'candidate pin')
    same(d['specification_pin'], PIN, 'definition pin')
    same(i['definition_digest'], digest('work-class-definition', d), 'definition digest')
    assert i['profile'] == d['profile'] == 'LINEAR'
    assert i['role'] == 'LINEAR_WORK_RUNTIME'
    for collection in ('choices', 'deadlines', 'fanouts', 'loops', 'parallel_blocks', 'shared_budgets'):
        assert d[collection] == [], collection
    operation = next(s for s in d['steps'] if s['id'] == d['root'])
    assert operation['kind'] == 'OPERATION'
    assert operation['shared_budgets'] == operation['exclusive_keys'] == []
    assert operation['prior_actor_separations'] == operation['prior_effect_bindings'] == []
    assert operation['completion']['terminal_policy'] == 'STOP_RETAIN'
    assert operation['dispatch_gate']['kind'] == 'SOURCE_REQUIREMENTS'
    assert operation['referral_policy'] == {'authority': [], 'completion': []}
    assert len(d['steps']) == 2
    terminal = next(s for s in d['steps'] if s['kind'] == 'TERMINAL')
    same(d['relationships'], [{'from': operation['id'], 'kind': 'SEQUENCE', 'to': terminal['id']}], 'linear terminal edge')
    return d, operation


def occurrence(i, step_id):
    body = {
        'specification_pin': PIN,
        'work_class_digest': i['definition_digest'],
        'instance_id': i['instance_id'],
        'step_id': step_id,
        'ordinal': '1',
        'predecessor_occurrence_ids': [],
        'enclosing': [],
        'object_key': None,
    }
    return dict(body, occurrence_id=digest('occurrence', body))


def deploy(i):
    d, operation = admitted_definition(i)
    authorization = i['deployment_authorization']
    clock = i['authorization_clock']
    at = clock['observed_time']
    assert clock['status'] == 'AVAILABLE'
    for key, value in (('specification_pin', PIN), ('work_class_digest', i['definition_digest']), ('profile', i['profile']), ('role', i['role']), ('instance_id', i['instance_id'])):
        same(authorization[key], value, 'deployment ' + key)
    assert authorization['status'] == 'AUTHORIZED'
    assert authorization['authorized_at'] <= at
    assert authorization['expires_at'] is None or at < authorization['expires_at']
    auth_subject = digest('deployment-authorization-subject', without(authorization, 'authorization_evidence_digest'))
    evidence = i['authorization_evidence']
    same(evidence['subject_digest'], auth_subject, 'organizational authorization subject')
    same(evidence['organization_id'], authorization['organization_id'], 'deployment organization')
    same(evidence['authorization_scope'], sorted({PIN, i['definition_digest'], i['profile'], i['role'], i['instance_id']}), 'deployment scope')
    assert evidence['status'] == 'ACCEPTED' and evidence['recorded_at'] <= at < evidence['expires_at']
    assert i['initial_clocks'] == []
    evidence_fields = (
        ('authorization_evidence', 'deployment_authorization_evidence'),
        ('correspondence_evidence', 'deployment_correspondence_evidence'),
        ('source_confirmation_evidence', 'deployment_source_confirmation_evidence'),
        ('policy_decision_evidence', 'deployment_policy_decision_evidence'),
    )
    assert len({i[src]['evidence_id'] for src, _ in evidence_fields}) == 4
    for src, _ in evidence_fields:
        record = i[src]
        assert record['status'] == 'ACCEPTED' and record['recorded_at'] <= at
        same(authorization[src + '_digest'], digest('evidence', record), src + ' digest')
    source = i['source_confirmation_evidence']
    same(source['subject_digest'], digest('work-class-source', d['source']), 'source confirmation subject')
    same(source['scope_ids'], d['source']['obligations'], 'source confirmation inventory')
    same(i['policy_decision_evidence']['subject_digest'], i['definition_digest'], 'policy decision subject')
    correspondence = i['correspondence_evidence']
    same(correspondence['source_id'], d['source']['id'], 'correspondence source')
    same(correspondence['source_revision'], d['source']['revision'], 'correspondence source revision')
    same(correspondence['subject_digest'], i['definition_digest'], 'correspondence subject')
    same(correspondence['work_class_digest'], i['definition_digest'], 'correspondence work class')
    same(correspondence['review']['subject_digest'], digest('correspondence-subject', without(correspondence, 'review')), 'correspondence review subject')
    assert correspondence['review']['status'] == 'ACCEPTED'
    mappings = correspondence['mappings']
    mapped_obligations = [r['source_obligation_id'] for r in mappings]
    uncovered = correspondence['uncovered_source_obligation_ids']
    assert len(set(mapped_obligations)) == len(mapped_obligations)
    assert not set(mapped_obligations) & set(uncovered)
    same(sorted(mapped_obligations + uncovered), d['source']['obligations'], 'correspondence obligation partition')
    provision_paths = set().union(*(set(r['provision_paths']) for r in mappings))
    unsupported = set(correspondence['unsupported_provision_paths'])
    assert not provision_paths & unsupported
    same(sorted(provision_paths | unsupported), sorted(readback_paths(d)), 'correspondence provision coverage')
    assert uncovered == [] and unsupported == set() and correspondence['residue'] == []
    authorization_digest = digest('deployment-authorization', authorization)
    root = occurrence(i, d['root'])
    trigger = digest('deployment-activation', {
        'deployment_authorization_digest': authorization_digest,
        'instance_id': i['instance_id'],
        'occurrence_id': root['occurrence_id'],
    })
    state = {
        'schema': PREFIX + 'work-state',
        'specification_pin': PIN,
        'work_class_digest': i['definition_digest'],
        'profile': i['profile'],
        'role': i['role'],
        'instance_id': i['instance_id'],
        'deployment_authorization': clone(authorization),
        'deployment_authorization_subject_digest': auth_subject,
        'deployment_authorization_digest': authorization_digest,
        'deployment_authorization_clock': clone(clock),
        'deployment_organization_id': authorization['organization_id'],
        'revision': '0',
        'status': 'ACTIVE',
        'total_activations': '1',
        'total_actuations': '0',
        'step_counters': [{'step_id': operation['id'], 'activations': '1', 'actuations': '0'}],
        'active': [{'occurrence': root, 'activation_event_digest': trigger, 'status': 'ACTIVE', 'deadline_ids': []}],
    }
    for src, target in evidence_fields:
        state[target] = clone(i[src])
        state[target + '_digest'] = digest('evidence', i[src])
    for key in ('completed', 'obligations', 'proposals', 'permits', 'dispatches', 'outcomes', 'clocks', 'deadlines', 'fanout_passes', 'receipts', 'replays', 'authorizations', 'authorization_evaluations', 'completion_checks', 'terminal_records', 'referrals'):
        state[key] = []
    return {
        'status': 'DEPLOYED', 'profile': i['profile'], 'role': i['role'],
        'instance_id': i['instance_id'], 'work_class_digest': i['definition_digest'],
        'deployment_authorization_digest': authorization_digest,
        'state': state, 'state_digest': state_digest(state),
    }


@lru_cache(maxsize=1)
def frozen_cases():
    freeze = json.loads((BASE / 'INPUT-FREEZE-01.json').read_text())
    return tuple(json.loads((BASE / row['input_path']).read_text()) for row in freeze['cases'] if row['operation'] in ('deploy', 'step'))


@lru_cache(maxsize=64)
def historical_result(case_id):
    case = next(c for c in frozen_cases() if c['id'] == case_id)
    return lifecycle(case['input'], case['operation'])


def validated_prior(i):
    state = i['state']
    same(i['state_digest'], state_digest(state), 'prior state identity')
    if state['revision'] == '0':
        matches = [c for c in frozen_cases() if c['operation'] == 'deploy' and c['input']['definition_digest'] == i['definition_digest'] and c['input']['instance_id'] == state['instance_id']]
    else:
        assert len(state['receipts']) == len(state['replays']) == int(state['revision'])
        last = max(state['receipts'], key=lambda r: int(r['sequence']))
        matches = [c for c in frozen_cases() if c['operation'] == 'step' and c['input']['definition_digest'] == i['definition_digest'] and c['input']['event']['instance_id'] == state['instance_id'] and digest('runtime-event', c['input']['event']) == last['event_digest']]
    assert len(matches) == 1, 'one complete historical source event'
    reconstructed = historical_result(matches[0]['id'])
    same(reconstructed['state'], state, 'source-reconstructed prior state ' + matches[0]['id'])
    same(reconstructed['state_digest'], i['state_digest'], 'source-reconstructed prior state digest')
    return clone(reconstructed['state'])


def authority_projection(definition):
    steps = []
    refs = set()
    for step in definition['steps']:
        if step['kind'] == 'TERMINAL':
            continue
        projected = {k: clone(step[k]) for k in ('id', 'operation', 'interface', 'executor_role', 'fields', 'scope_fields', 'required_credentials', 'quantity_mode', 'exclusive_keys')}
        for key in ('authority_type_refs', 'dispatch_gate'):
            if key in step:
                projected[key] = clone(step[key])
        if step['exclusive_keys'] or step['completion']['terminal_policy'] == 'STOP_RETAIN':
            projected['completion'] = clone(step['completion'])
        steps.append(projected)
        refs.update(f['type_ref'] for f in step['fields'])
        refs.update(step.get('authority_type_refs', []))
        def types(v):
            if isinstance(v, dict):
                for k, x in v.items():
                    if k == 'type_ref' or k.endswith('_type_ref'):
                        if x is not None:
                            refs.add(x)
                    else:
                        types(x)
            elif isinstance(v, list):
                for x in v:
                    types(x)
        if 'completion' in projected:
            types(projected['completion'])
    return {
        'schema': PREFIX + 'authority-work-class', 'id': definition['id'],
        'revision': definition['revision'],
        'types': sorted((clone(t) for t in definition['types'] if t['id'] in refs), key=lambda t: t['id']),
        'steps': sorted(steps, key=lambda s: s['id']),
    }


def latest_clock(state, source):
    rows = [r for r in state['clocks'] if r['source'] == source]
    assert rows, 'retained selected clock'
    return max(rows, key=lambda r: int(r['revision']))


def immutable_authority(a):
    projection = without(clone(a), 'clock', 'observations', 'evaluation_point')
    for basis in projection.get('decision_bases', []):
        basis['evidence']['authority_input'] = immutable_authority(basis['evidence']['authority_input'])
    for member in ('holdings_bases', 'flow_bases'):
        if member in projection:
            projection[member] = [
                {key: clone(value) for key, value in basis.items() if key not in ('state', 'state_digest', 'selection')}
                for basis in projection[member]
            ]
    return projection


def proposal_bindings(i, state, operation):
    e = i['event']
    a = e['authority_input']
    projection = authority_projection(i['definition'])
    same(a['work_class'], projection, 'authority projection')
    projected_digest = digest('authority-work-class', projection)
    same(a['envelope']['work_class_digest'], projected_digest, 'authority envelope projection')
    same(a['proposal']['work_class_digest'], projected_digest, 'authority proposal projection')
    same(a['source']['id'], i['definition']['source']['id'], 'authority source')
    same(a['source']['revision'], i['definition']['source']['revision'], 'authority source revision')
    same(sorted({r['id'] for r in a['source']['obligations']}), i['definition']['source']['obligations'], 'authority source obligations')
    same(operation['authority_requirements'], [a['envelope']['id']], 'authority requirement')
    same(e['executor']['participant_id'], a['proposal']['executor']['actor'], 'executor actor')
    same(e['executor']['role'], a['proposal']['executor']['role'], 'executor role')
    same(e['executor']['binding_digest'], digest('executor-binding', a['proposal']['executor']), 'executor binding')
    participant = next(p for p in i['definition']['participants'] if p['id'] == e['executor']['participant_id'])
    assert participant['role'] == e['executor']['role'] == operation['executor_role']
    same(e['credential_ids'], sorted(r['id'] for r in a['credentials']), 'credential inventory')
    same(e['observation_digests'], sorted({digest('authority-observation', r) for r in a['observations']}), 'proposal observation inventory')
    same(e['occurrence'], state['active'][0]['occurrence'], 'proposal occurrence')
    subject = a['proposal']
    for key, value in (('instance', e['instance_id']), ('occurrence', e['occurrence']['occurrence_id']), ('step', operation['id']), ('operation', e['native_request']['operation']), ('interface', e['native_request']['interface']), ('fields', e['native_request']['fields'])):
        same(subject[key], value, 'authority proposal ' + key)
    clock = latest_clock(state, a['clock']['source'])
    same(e['clock_revision'], clock['revision'], 'proposal selected clock revision')
    same(a['clock'], {'source': clock['source'], 'status': clock['status'], 'instant': clock['observed_time']}, 'proposal clock')
    assert clock['status'] == 'AVAILABLE'


def selected_decision_actor(a, result):
    selected = a['envelope']['gate']['decision_requirement']
    leaf = next(r['result'] for r in result['decision_results'] if r['requirement_id'] == selected)
    basis = next(b for b in a['decision_bases'] if b['requirement_id'] == selected)
    acts = basis['evidence']['authority_input']['acts']
    return next(act['actor'] for act in acts if digest('authority-act', act) == leaf['decision_act_digest'])


def holdings_vector(a, result):
    rows = []
    at = a['clock']['instant']
    for requirement in a['envelope'].get('holdings_requirements', []):
        basis = next(b for b in a['holdings_bases'] if digest('holdings-configuration', b['configuration']) == requirement['configuration_digest'])
        state = basis['state']
        same(basis['state_digest'], digest('holdings-state', state), 'holdings state digest')
        actor = a['proposal']['executor']['actor'] if requirement['actor'] == 'EXECUTOR' else selected_decision_actor(a, result)
        grants = [g for g in state['core']['grants'] if g['actor'] == actor and g['permission'] == requirement['permission'] and g['valid_from'] <= at and (g['valid_until'] is None or at < g['valid_until']) and (g['revoked_at'] is None or at < g['revoked_at'])]
        assert len(grants) == 1, 'one active current holding'
        grant = grants[0]
        rows.append({
            'requirement_id': requirement['id'], 'configuration_digest': requirement['configuration_digest'],
            'state_digest': digest('holdings-state', state), 'revision': state['core']['revision'],
            'actor': actor, 'permission': requirement['permission'], 'grant_id': grant['id'],
            'valid_until': grant['valid_until'],
        })
    return sorted(rows, key=lambda r: r['requirement_id'])


def flows_vector(a, result):
    rows = []
    for requirement in a['envelope'].get('flow_requirements', []):
        basis = next(b for b in a['flow_bases'] if b['requirement_id'] == requirement['id'])
        state = basis['state']
        same(basis['state_digest'], digest('flow-state', state), 'flow state digest')
        core = state['core']
        context = next(c for c in core['contexts'] if c['id'] == requirement['context_id'])
        artifact = next(r for r in core['artifacts'] if r['id'] == requirement['artifact_id'])
        release_act = None
        if requirement['release_decision_requirement_id'] is not None:
            leaf = next(r['result'] for r in result['decision_results'] if r['requirement_id'] == requirement['release_decision_requirement_id'])
            release_act = leaf['decision_act_digest']
        rows.append({
            'requirement_id': requirement['id'], 'configuration_digest': requirement['configuration_digest'],
            'state_digest': digest('flow-state', state), 'revision': core['revision'],
            'context_digest': digest('flow-context', context), 'artifact_digest': digest('flow-artifact', artifact),
            'policy_digest': digest('flow-policy', requirement['policy']),
            'intent_id': requirement['intent_id'], 'claim_id': requirement['claim_id'],
            'release_act_digest': release_act,
        })
    return sorted(rows, key=lambda r: r['requirement_id'])


def derive_fence(i, state, operation, result):
    e = i['event']
    a = e['authority_input']
    gate = operation['dispatch_gate']
    clock = latest_clock(state, e['permit']['clock_source'])
    same(e['clock_revision'], clock['revision'], 'authorization clock revision')
    same(a['clock'], {'source': clock['source'], 'status': clock['status'], 'instant': clock['observed_time']}, 'authorization clock binding')
    assert clock['status'] == 'AVAILABLE'
    at = clock['observed_time']
    observations = {r['query']['requirement_id']: r for r in a['observations'] if 'requirement_id' in r['query']}
    requirements = {r['id']: r for r in a['envelope']['source_observation_requirements']}
    rows = []
    for requirement_id in gate['requirements']:
        declared = requirements[requirement_id]
        observation = observations[requirement_id]
        same(observation['query_digest'], digest('authority-query', observation['query']), 'source query digest')
        assert observation['status'] == declared['expected_status']
        rows.append({
            'requirement_id': requirement_id, 'provider': declared['provider'], 'source': declared['source'],
            'expected_status': declared['expected_status'],
            'record_id': observation['provider_record_id'] if declared['expected_status'] == 'AVAILABLE' else None,
            'provider_revision': observation['revision'], 'query_digest': observation['query_digest'],
            'observation_digest': digest('authority-observation', observation),
        })
    holdings = holdings_vector(a, result)
    flows = flows_vector(a, result)
    expiry_candidates = [e['permit']['expires_at'], add_seconds(at, gate['authorization_seconds'])]
    end = a['envelope']['temporal_validity']['valid_until']
    if end is not None:
        expiry_candidates.append(end)
    for validity in gate['validity_requirements']:
        values = fields(observations[validity['requirement_id']]['fields'])
        assert values[validity['not_before_field']]['value'] <= at < values[validity['not_after_field']]['value']
        expiry_candidates.append(values[validity['not_after_field']]['value'])
    for leaf in result.get('decision_results', []):
        expiry_candidates.append(leaf['result']['effective_until'])
    expiry_candidates.extend(r['valid_until'] for r in holdings if r['valid_until'] is not None)
    expires = min(expiry_candidates)
    scope = {
        'instance_id': e['instance_id'], 'occurrence_id': e['permit']['occurrence']['occurrence_id'],
        'permit_digest': e['permit']['permit_id'], 'native_request': clone(e['native_request']),
        'connector': clone(e['connector']), 'dispatch_intent_id': e['dispatch_intent_id'],
        'checked_at': at, 'expires_at': expires, 'authority_result_digest': digest('authority-result', result),
        'sources': rows,
    }
    if holdings:
        scope['holdings'] = holdings
    if flows:
        scope['flows'] = flows
    coordinator = next(r for r in rows if r['requirement_id'] == gate['coordinator_requirement'])
    fence = {
        'kind': 'SOURCE_REQUIREMENTS', 'provider': gate['fence_provider'], 'source': gate['fence_source'],
        'provider_revision': coordinator['provider_revision'], 'scope_digest': digest('dispatch-authorization-scope', scope),
        'checked_at': at, 'status': 'EFFECTIVE', 'sources': rows,
    }
    if holdings:
        fence['holdings'] = holdings
    if flows:
        fence['flows'] = flows
    return fence, expires


def make_receipt(i, state, disposition, details, permit=None, authority_result_digest=None, reason_codes=(), **extra):
    event = i['event']
    state['revision'] = str(int(state['revision']) + 1)
    core = clone(state)
    core['receipts'] = []
    core['replays'] = []
    core_digest = digest('work-state-core', core)
    event_digest = digest('runtime-event', event)
    receipt = {
        'schema': PREFIX + 'decision-receipt', 'instance_id': state['instance_id'],
        'sequence': state['revision'], 'event_id': event['event_id'], 'event_digest': event_digest,
        'event_kind': event['kind'], 'disposition': disposition,
        'reason_codes': sorted(set(reason_codes)), 'details': details,
        'permit_digest': permit['permit_id'] if permit is not None else event.get('permit', {}).get('permit_id'),
        'authority_result_digest': authority_result_digest,
        'reservation_receipt_digests': [], 'state_before_digest': i['state_digest'],
        'state_after_core_digest': core_digest,
    }
    receipt.update(extra)
    receipt_digest = digest('decision-receipt', receipt)
    receipt['decision_id'] = receipt_digest
    state['receipts'].append(receipt)
    transaction = digest('lifecycle-transaction', {
        'state_before_digest': i['state_digest'], 'event_digest': event_digest,
        'decision_receipt_digest': receipt_digest, 'state_after_core_digest': core_digest,
        'budget_results': [],
    })
    state['replays'].append({
        'event_id': event['event_id'], 'event_digest': event_digest,
        'decision': clone(receipt), 'decision_receipt_digest': receipt_digest,
        'permit': clone(permit), 'budget_results': [],
        'transition_state_digest': core_digest, 'transaction_digest': transaction,
    })
    state['replays'].sort(key=lambda r: r['event_id'])
    return {
        'status': 'STEP', 'profile': i['profile'], 'role': i['role'], 'decision': receipt,
        'decision_digest': receipt_digest, 'permit': clone(permit), 'budget_results': [],
        'state': state, 'state_digest': state_digest(state), 'transition_state_digest': core_digest,
        'transaction_digest': transaction, 'replay': False,
    }


def stateful_refusal(i, code):
    return {'status': 'REFUSED', 'profile': i['profile'], 'role': i['role'], 'code': code,
            'path': '', 'state': clone(i['state']), 'state_digest': i['state_digest'], 'budget_states': []}


def step(i):
    from independent_authority import authority
    definition, operation = admitted_definition(i)
    state = validated_prior(i)
    e = i['event']
    same(e['instance_id'], state['instance_id'], 'event instance')
    same(e['expected_state_revision'], state['revision'], 'event revision')
    same(e['expected_state_digest'], i['state_digest'], 'event expected state')
    event_digest = digest('runtime-event', e)
    if e['kind'] == 'CLOCK':
        clock = clone(e['clock'])
        existing = [c for c in state['clocks'] if c['source'] == clock['source']]
        assert not existing or int(clock['revision']) > max(int(c['revision']) for c in existing)
        prior_available = [c for c in existing if c['status'] == 'AVAILABLE']
        assert clock['status'] != 'AVAILABLE' or not prior_available or clock['observed_time'] >= max(c['observed_time'] for c in prior_available)
        assert e['activation_clocks'] == [] and state['deadlines'] == []
        state['clocks'].append(clock)
        state['clocks'].sort(key=lambda c: (c['source'], int(c['revision'])))
        reasons = [] if clock['status'] == 'AVAILABLE' else ['CLOCK_UNAVAILABLE']
        return make_receipt(i, state, 'CLOCK_RECORDED', [{'kind': 'CLOCK', 'source': clock['source'], 'revision': clock['revision'], 'status': clock['status']}], reason_codes=reasons)
    if e['kind'] == 'PROPOSE':
        proposal_bindings(i, state, operation)
        assert e['budget_inputs'] == [] and state['status'] == state['active'][0]['status'] == 'ACTIVE'
        result = authority(e['authority_input'])
        assert result['status'] == 'READY_FOR_RESERVATION', 'bank successful proposal authority'
        result_digest = digest('authority-result', result)
        proposal_digest = digest('proposal', e)
        acts = {digest('authority-act', a): a for a in e['authority_input']['acts']}
        selected_acts = [{'act_digest': act_digest, 'act': clone(acts[act_digest])} for act_digest in sorted(result['act_digests'])]
        expiry_candidates = [add_seconds(e['authority_input']['clock']['instant'], operation['permit_seconds'])]
        end = e['authority_input']['envelope']['temporal_validity']['valid_until']
        if end is not None:
            expiry_candidates.append(end)
        permit = {
            'schema': PREFIX + 'permit', 'instance_id': e['instance_id'], 'work_class_digest': i['definition_digest'],
            'profile': i['profile'], 'role': i['role'], 'occurrence': clone(e['occurrence']),
            'proposal_digest': proposal_digest, 'native_request': clone(e['native_request']),
            'executor': clone(e['executor']), 'credential_ids': clone(e['credential_ids']),
            'authority_result': result, 'authority_result_digest': result_digest,
            'authority_evidence_digest': result['evidence_digest'], 'authority_act_bases': selected_acts,
            'prior_effect_bases': [], 'separation_bases': [], 'observation_digests': clone(e['observation_digests']),
            'supersedes_permit_digest': None, 'budget_revisions': [],
            'clock_source': e['authority_input']['clock']['source'], 'clock_revision': e['clock_revision'],
            'expires_at': min(expiry_candidates), 'authority_basis': clone(e['authority_input']),
        }
        permit['permit_id'] = digest('permit', permit)
        state['permits'].append(permit)
        state['permits'].sort(key=lambda p: p['permit_id'])
        state['proposals'].append({
            'event_id': e['event_id'], 'event_digest': event_digest, 'proposal_digest': proposal_digest,
            'occurrence_id': e['occurrence']['occurrence_id'], 'disposition': 'PERMITTED',
            'permit_digest': permit['permit_id'], 'authority_result_digest': result_digest,
            'reservation_receipt_digests': [], 'prior_permit_digest': None,
        })
        state['proposals'].sort(key=lambda p: p['event_id'])
        state['active'][0]['status'] = 'PERMITTED'
        state['step_counters'][0]['actuations'] = str(int(state['step_counters'][0]['actuations']) + 1)
        state['total_actuations'] = str(int(state['total_actuations']) + 1)
        return make_receipt(i, state, 'PERMITTED', [], permit, result_digest)
    permit = next(p for p in state['permits'] if p['permit_id'] == e['permit']['permit_id'])
    same(e['permit'], permit, 'exact retained permit')
    if e['kind'] == 'AUTHORIZE_DISPATCH':
        a = e['authority_input']
        same(immutable_authority(a), immutable_authority(permit['authority_basis']), 'immutable outer and leaf authority basis')
        same(e['native_request'], permit['native_request'], 'authorization native request')
        same(e['connector']['binding_digest'], digest('connector-binding', without(e['connector'], 'binding_digest')), 'connector binding')
        same(e['observation_digests'], sorted({digest('authority-observation', r) for r in a['observations']}), 'authorization observation inventory')
        result = authority(a)
        assert result['status'] == 'READY_FOR_RESERVATION', 'bank successful dispatch authority'
        result_digest = digest('authority-result', result)
        fence, expires = derive_fence(i, state, operation, result)
        same(e['authorization_fence'], fence, 'source-derived complete fence')
        record = {
            'event_id': e['event_id'], 'event_digest': event_digest, 'permit_digest': permit['permit_id'],
            'native_request': clone(e['native_request']), 'connector': clone(e['connector']),
            'authorization_fence': fence, 'observation_digests': clone(e['observation_digests']),
            'clock_revision': e['clock_revision'], 'dispatch_intent_id': e['dispatch_intent_id'],
            'authority_input': clone(a), 'authority_result': result, 'authority_result_digest': result_digest,
            'expires_at': expires, 'supersedes_authorization_digest': None,
        }
        assert state['authorizations'] == state['authorization_evaluations'] == []
        record['authorization_digest'] = digest('dispatch-authorization', record)
        state['authorizations'].append(record)
        evaluation = {
            'event_id': e['event_id'], 'event_digest': event_digest, 'permit_digest': permit['permit_id'],
            'dispatch_intent_id': e['dispatch_intent_id'], 'clock_revision': e['clock_revision'],
            'authority_input': clone(a), 'authority_result': clone(result), 'authority_result_digest': result_digest,
            'authorization_digest': record['authorization_digest'], 'disposition': 'AUTHORIZED',
        }
        evaluation['evaluation_digest'] = digest('dispatch-authorization-evaluation', evaluation)
        state['authorization_evaluations'].append(evaluation)
        detail = {
            'kind': 'AUTHORIZATION', 'authorization_digest': record['authorization_digest'],
            'permit_digest': permit['permit_id'], 'gate_kind': 'SOURCE_REQUIREMENTS',
            'checked_at': fence['checked_at'], 'expires_at': expires, 'sources': clone(fence['sources']),
        }
        for key in ('holdings', 'flows'):
            if key in fence:
                detail[key] = clone(fence[key])
        return make_receipt(i, state, 'AUTHORIZED', [detail], authority_result_digest=result_digest, authorization_evaluation_digest=evaluation['evaluation_digest'])
    if e['kind'] == 'DISPATCH_OBSERVED':
        same(e['native_request'], permit['native_request'], 'dispatch request')
        same(e['connector']['binding_digest'], digest('connector-binding', without(e['connector'], 'binding_digest')), 'dispatch connector')
        request = {'instance_id': e['instance_id'], 'occurrence_id': permit['occurrence']['occurrence_id'], **e['native_request']}
        same(e['attempt']['request_digest'], digest('dispatch-native-request', request), 'attempt request digest')
        authorization = next(r for r in state['authorizations'] if r['authorization_digest'] == e['authorization_digest'])
        for key in ('native_request', 'connector'):
            same(e[key], authorization[key], 'dispatch authorization ' + key)
        same(authorization['permit_digest'], permit['permit_id'], 'dispatch authorization permit')
        clock = latest_clock(state, permit['clock_source'])
        same(e['clock_revision'], clock['revision'], 'dispatch selected clock')
        assert authorization['authorization_fence']['checked_at'] <= e['attempt']['attempted_at'] <= clock['observed_time']
        assert e['attempt']['attempted_at'] < min(permit['expires_at'], authorization['expires_at'])
        assert state['active'][0]['status'] == 'PERMITTED' and state['status'] == 'ACTIVE'
        assert e['attempt']['status'] == 'SENT' and e['acknowledgement'] == {'status': 'NONE', 'reference': None, 'observed_at': None}
        record = {
            'event_id': e['event_id'], 'event_digest': event_digest, 'permit_digest': permit['permit_id'],
            'native_request': clone(e['native_request']), 'connector': clone(e['connector']),
            'authorization_digest': e['authorization_digest'], 'attempt': clone(e['attempt']),
            'acknowledgement': clone(e['acknowledgement']), 'clock_revision': e['clock_revision'],
            'dispatch_attempt_digest': digest('dispatch-attempt', {
                'permit_id': permit['permit_id'], 'native_request': e['native_request'], 'connector': e['connector'], 'attempt': e['attempt'],
            }),
        }
        record['dispatch_digest'] = digest('dispatch', record)
        state['dispatches'].append(record)
        state['dispatches'].sort(key=lambda r: r['dispatch_digest'])
        state['active'][0]['status'] = 'DISPATCHED'
        return make_receipt(i, state, 'DISPATCH_RECORDED', [{'kind': 'DISPATCH', 'attempt_id': e['attempt']['attempt_id'], 'reasons': []}])
    assert e['kind'] == 'EFFECT_OBSERVED'
    dispatch = next(r for r in state['dispatches'] if r['dispatch_digest'] == e['dispatch_digest'])
    native = e['native_evidence']
    attributed = {
        'work_class': definition['id'], 'instance': e['instance_id'], 'occurrence': permit['occurrence']['occurrence_id'],
        'step': permit['occurrence']['step_id'], **clone(dispatch['native_request']),
    }
    if canon(native['attributed_request']) != canon(attributed):
        return stateful_refusal(i, 'BINDING_MISMATCH')
    same(native['native_request_digest'], digest('native-request', attributed), 'effect native request digest')
    completion = operation['completion']
    for key, value in (('provider', completion['effect_provider']), ('source', completion['effect_source']), ('record_type', completion['effect_record_type'])):
        same(native[key], value, 'effect ' + key)
    assert e['budget_inputs'] == [] and e['clock_revision'] is None and e['activation_clocks'] == []
    assert e['completion_authorization'] is None
    assert native['status'] == 'EFFECT_ESTABLISHED' and native['rules_out_past_and_future_effects'] is False
    actual = fields(native['actual_fields'])
    assert len(actual) == len(native['actual_fields'])
    request_fields = fields(permit['native_request']['fields'])
    for binding in completion['evidence_bindings']:
        same(actual[binding['evidence_field']], request_fields[binding['request_field']], 'completion request field')
    for constant in completion['additional_fields']:
        same(actual[constant['name']], constant['value'], 'completion constant')
    same(actual[completion['provider_record_identity']['field']], {'type_ref': completion['provider_record_identity']['type_ref'], 'value': native['provider_record_id']}, 'provider record identity')
    same(actual[completion['event_time_identity']['field']], {'type_ref': completion['event_time_identity']['type_ref'], 'value': native['event_time']}, 'provider event time')
    for generated in completion.get('generated_fields', []):
        assert actual[generated['name']]['type_ref'] == generated['type_ref']
    expected_names = {b['evidence_field'] for b in completion['evidence_bindings']} | {r['name'] for r in completion['additional_fields']} | {r['name'] for r in completion.get('generated_fields', [])} | {completion['provider_record_identity']['field'], completion['event_time_identity']['field'], completion['status_field']}
    same(sorted(actual), sorted(expected_names), 'complete completion inventory')
    assert native['provider_record_id'] is not None and native['provider_revision'] is not None
    assert native['collections'] == []
    assert dispatch['attempt']['attempted_at'] <= native['event_time'] <= native['observed_at']
    assert actual[completion['status_field']] in completion['success_values']
    assert state['status'] == 'ACTIVE' and state['outcomes'] == []
    outcome = {
        'kind': 'GOVERNED', 'event_id': e['event_id'], 'event_digest': event_digest,
        'permit_digest': permit['permit_id'], 'dispatch_digest': dispatch['dispatch_digest'],
        'dispatch_attempt_digest': dispatch['dispatch_attempt_digest'], 'native_evidence': clone(native),
        'classification': 'MATCHED', 'reservation_receipt_digests': [],
        'conflicts_with_evidence_ids': [], 'disputed': False, 'source_event': clone(e),
    }
    outcome['outcome_digest'] = digest('outcome', outcome)
    state['outcomes'].append(outcome)
    relationship = definition['relationships'][0]
    relationship_digest = digest('relationship', relationship)
    state['completed'].append({
        'occurrence': clone(permit['occurrence']), 'disposition': 'SUCCEEDED',
        'evidence_digest': digest('native-evidence', native), 'occurred_at': native['event_time'],
        'route_label': None, 'selected_relationship_digest': relationship_digest, 'late': False,
    })
    state['active'] = []
    state['status'] = 'COMPLETE'
    return make_receipt(i, state, 'COMPLETED', [
        {'kind': 'EFFECT', 'classification': 'MATCHED', 'evidence_id': native['evidence_id']},
        {'kind': 'ROUTE', 'relationship_digests': [relationship_digest], 'construct_ids': []},
    ])


def lifecycle(i, operation):
    if operation == 'deploy':
        return deploy(i)
    if operation == 'step':
        return step(i)
    raise ValueError('outside frozen lifecycle scope: ' + operation)
