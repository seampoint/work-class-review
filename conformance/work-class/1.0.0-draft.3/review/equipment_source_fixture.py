"""Complete revision-3 equipment source facts and independent trace constructors."""
from __future__ import annotations

import copy
import base64
import runpy
from pathlib import Path

from corpus_common import candidate_pin, canonical_bytes, digest
from equipment_correction_fixture import correction_fixture, correction_result, equipment_original_fixture, rebind_authority, ORIGINAL_AT, PRINCIPAL
from equipment_observation_fixture import observation, relation, requirement, expected_ready, source_refusal, typed
from equipment_dispatch_fixture import authorization_event, authorization_result, derived_fence, retained
from equipment_history_fixture import history_state, project_history, seed_request, seed_result
from equipment_completion_fixture import completion_native, lookup_event, lookup_result, terminal_effect_result
from fixture_factory import add_seconds, available_clock, deployment, occurrence
from lifecycle_factory import admitted_transition, dispatch_event, dispatch_result, governed_effect_event, state_digest, withheld_proposal
from lifecycle_budget_fixture import permitted_budget_proposal, withheld_budget_proposal
from reservation_fixture import effect_record, host_and_event, native, request as reservation_request, reservation_record, transition


SOURCE_PATH = Path(__file__).with_name('fixtures') / 'equipment-return-to-service-revision3-source.txt'
PROVIDER = 'maintenance-register'
SOURCE = 'return-to-service-events'
ISSUER = PRINCIPAL
REQUEST_ID = 'RTS-REQ-417'
CAPABILITY_FIELDS = ['all_writers_mediated', 'conditional_write', 'event_id_lookup', 'tuple_lookup', 'tuple_uniqueness']
GATE_IDS = ['approval', 'approval-withdrawal', 'policy-dr-withdrawal', 'policy-mcs-withdrawal']
SHAPES = {
    'approval-use': ['provider', 'source', 'approval'],
    'inspection-use': ['issuer', 'asset', 'inspection'],
    'request-use': ['issuer', 'request_id'],
    'tuple-use': ['provider', 'source', 'asset', 'work_order', 'inspection', 'approval'],
    'work-order-use': ['issuer', 'asset', 'work_order'],
}
CONSTANTS = {'provider': PROVIDER, 'source': SOURCE, 'issuer': ISSUER, 'request_id': REQUEST_ID}


def source_obligations():
    rows = []
    for line_number, line in enumerate(SOURCE_PATH.read_text().splitlines(), 1):
        if line and not line.startswith(('### ', 'Business record:')):
            rows.append({'id': 'equipment-source-line-' + str(line_number), 'text': line})
    return sorted(rows, key=lambda row: row['id'].encode('utf-8'))


def source_keys(fields, request_id=REQUEST_ID):
    types = {row['name']: row['value']['type_ref'] for row in fields}
    keys = []
    for slot, names in SHAPES.items():
        projection = []
        for name in names:
            if name in CONSTANTS:
                value = request_id if name == 'request_id' else 'approval-register' if slot == 'approval-use' and name == 'source' else CONSTANTS[name]
                projection.append({'key_field': name, 'value': typed('REQUEST_ID' if name == 'request_id' else 'IDENTITY', value)})
            else:
                projection.append({'key_field': name, 'field': name, 'type_ref': types[name]})
        keys.append({'id': slot + '-key', 'slot': slot, 'namespace': 'equipment-return-to-service',
            'projection': projection, 'retention': 'RETAIN_UNTIL_SETTLED_OR_AUTHORIZED_RELEASE'})
    return keys


def source_requirements(authority, request_id=REQUEST_ID, inspection_at='2026-09-12T13:55:00Z'):
    step = authority['proposal']['step']
    executor = authority['proposal']['executor']
    grant = next(row for row in authority['acts'] if row['kind'] == 'GRANT')
    proposal = {row['name']: row['value'] for row in authority['proposal']['fields']}
    rows, facts = [], {}
    def add(req_id, *, provider, source, record_type, purpose, subject, record_id,
            values, comparisons, at='CLOCK', expected_status='AVAILABLE', key_projection=None):
        declarations = [{'name': name, 'type_ref': value['type_ref']} for name, value in sorted(values.items())]
        relations = sorted([relation(req_id + '-' + str(index), kind, left, right)
            for index, (kind, left, right) in enumerate(comparisons, 1)], key=lambda row: row['id'])
        row = requirement(req_id, step=step, provider=provider, source=source, record_type=record_type,
            purpose=purpose, subject=subject, record_id=record_id, fields=declarations, relations=relations,
            at=at, expected_status=expected_status)
        if key_projection is not None:
            row['key_projection'] = key_projection
        rows.append(row)
        facts[req_id] = values
    def executor_value(member, type_ref='IDENTITY'):
        return {'kind': 'EXECUTOR', 'member': member, 'type_ref': type_ref}
    def grant_value(member, type_ref='IDENTITY'):
        return {'kind': 'ACT', 'act_kind': 'GRANT', 'member': member, 'type_ref': type_ref}
    def literal(value):
        return {'kind': 'LITERAL', 'value': value}
    def proposed(name):
        return {'kind': 'PROPOSAL_FIELD', 'field': name}
    common = {'actor': typed('IDENTITY', executor['actor']), 'principal': typed('IDENTITY', PRINCIPAL)}
    common_relations = [('EQUALS', 'actor', executor_value('actor')), ('EQUALS', 'principal', executor_value('principal'))]
    live_actor = executor_value('actor')
    add('current-session', provider='workforce-identity-and-access-service', source='authenticated-session',
        record_type='authenticated-session', purpose='AUTHENTICATED_SESSION', subject=live_actor,
        record_id='clerk-session-17', values={**common, 'authenticated': typed('BOOLEAN', True)},
        comparisons=common_relations + [('EQUALS', 'authenticated', literal(typed('BOOLEAN', True)))])
    add('current-role', provider='workforce-identity-and-access-service', source='active-role-assignment',
        record_type='active-role-assignment', purpose='ROLE_ASSIGNMENT', subject=live_actor,
        record_id='clerk-role-17', values={**common, 'role': typed('ROLE_ID', executor['role']), 'active': typed('BOOLEAN', True)},
        comparisons=common_relations + [('EQUALS', 'role', executor_value('role', 'ROLE_ID')),
            ('EQUALS', 'active', literal(typed('BOOLEAN', True)))])
    add('current-duty', provider='maintenance-duty-roster', source='duty-assignment',
        record_type='duty-assignment', purpose='DUTY_ASSIGNMENT', subject=live_actor,
        record_id='clerk-duty-17', values={**common, 'on_duty': typed('BOOLEAN', True)},
        comparisons=common_relations + [('EQUALS', 'on_duty', literal(typed('BOOLEAN', True)))])
    add('current-safety', provider='equipment-safety-hold-register', source='asset-status',
        record_type='asset-status', purpose='SAFETY_HOLD', subject=proposed('asset'), record_id=proposal['asset']['value'] + '-hold-status',
        values={'asset': proposal['asset'], 'no_open_hold': typed('BOOLEAN', True)},
        comparisons=[('EQUALS', 'asset', proposed('asset')), ('EQUALS', 'no_open_hold', literal(typed('BOOLEAN', True)))])
    add('inspection', provider='maintenance-inspection-service', source='inspection-register',
        record_type='inspection', purpose='AUTHORITY', subject=proposed('inspection'), record_id=proposal['inspection']['value'],
        values={name: proposal[name] for name in ['asset', 'inspection', 'work_order']} | {
            'complete': typed('BOOLEAN', True), 'completed_at': typed('INSTANT', inspection_at)},
        comparisons=[('EQUALS', name, proposed(name)) for name in ['asset', 'inspection', 'work_order']] + [
            ('EQUALS', 'complete', literal(typed('BOOLEAN', True))), ('BEFORE', 'completed_at', grant_value('occurred_at', 'INSTANT'))])
    add('historical-supervisor-duty', provider='maintenance-duty-roster', source='duty-assignment',
        record_type='duty-assignment', purpose='DUTY_ASSIGNMENT', subject=grant['actor'],
        record_id='supervisor-duty-4', at=grant['occurred_at'],
        values={'actor': typed('IDENTITY', grant['actor']), 'principal': typed('IDENTITY', PRINCIPAL),
            'role': typed('ROLE_ID', grant['role']), 'on_duty': typed('BOOLEAN', True)},
        comparisons=[('EQUALS', 'actor', grant_value('actor')), ('EQUALS', 'principal', grant_value('principal')),
            ('EQUALS', 'role', grant_value('role', 'ROLE_ID')), ('EQUALS', 'on_duty', literal(typed('BOOLEAN', True)))])
    add('approval', provider=PROVIDER, source='approval-register', record_type='approval', purpose='AUTHORITY',
        subject=proposed('approval'), record_id=proposal['approval']['value'], values={name: proposal[name] for name in ['approval', 'asset', 'inspection', 'work_order']} | {
            'approval_actor': typed('IDENTITY', grant['actor']), 'approval_role': typed('ROLE_ID', grant['role']),
            'signed_at': typed('INSTANT', grant['occurred_at']), 'effective': typed('BOOLEAN', True)},
        comparisons=[('EQUALS', name, proposed(name)) for name in ['approval', 'asset', 'inspection', 'work_order']] + [
            ('EQUALS', 'approval', grant_value('id', 'APPROVAL_ID')), ('EQUALS', 'approval_actor', grant_value('actor')),
            ('EQUALS', 'approval_role', grant_value('role', 'ROLE_ID')), ('EQUALS', 'signed_at', grant_value('occurred_at', 'INSTANT')),
            ('EQUALS', 'effective', literal(typed('BOOLEAN', True)))])
    for req_id, source, subject, record_id in [
            ('approval-withdrawal', 'approval-register', proposal['approval']['value'], 'WD-552' if proposal['approval']['value'] == 'AP-091' else 'WD-553'),
            ('policy-dr-withdrawal', 'delegation-policy-withdrawals', 'DR-08-r2', None),
            ('policy-mcs-withdrawal', 'maintenance-policy-withdrawals', 'MCS-12-r4', None)]:
        add(req_id, provider=PROVIDER if req_id == 'approval-withdrawal' else 'maintenance-governance-register',
            source=source, record_type='withdrawal-notice', purpose='AUTHORITY', subject=subject,
            record_id=record_id, values={}, comparisons=[], expected_status='ABSENT')
    add('completed-tuple-absence', provider=PROVIDER, source=SOURCE, record_type='return-to-service-event',
        purpose='DUPLICATE', subject=proposed('asset'), record_id=None, values={}, comparisons=[],
        expected_status='ABSENT', key_projection=[{'field': name, 'type_ref': proposal[name]['type_ref']}
            for name in ['approval', 'asset', 'inspection', 'work_order']])
    for req_id, record_id, revision in [('delegation-policy', 'DR-08', '2'), ('maintenance-policy', 'MCS-12', '4')]:
        add(req_id, provider='maintenance-governance-register', source='policy-register', record_type='policy-revision',
            purpose='AUTHORITY', subject=record_id, record_id=record_id + '-r' + revision,
            values={'revision': typed('POLICY_REVISION', revision)},
            comparisons=[('EQUALS', 'revision', literal(typed('POLICY_REVISION', revision)))])
    add('request-identity', provider='maintenance-request-coordinator', source='request-register', record_type='maintenance-request',
        purpose='AUTHORITY', subject=request_id, record_id=request_id,
        values={'request_id': typed('REQUEST_ID', request_id), 'issuer': typed('IDENTITY', ISSUER),
            **{name: proposal[name] for name in ['asset', 'approval', 'inspection', 'work_order']}},
        comparisons=[('EQUALS', 'request_id', literal(typed('REQUEST_ID', request_id))),
            ('EQUALS', 'issuer', literal(typed('IDENTITY', ISSUER)))] + [('EQUALS', name, proposed(name))
            for name in ['asset', 'approval', 'inspection', 'work_order']])
    add('work-order', provider='maintenance-work-order-service', source='work-order-register', record_type='work-order',
        purpose='AUTHORITY', subject=proposed('work_order'), record_id=proposal['work_order']['value'],
        values={name: proposal[name] for name in ['asset', 'work_order']},
        comparisons=[('EQUALS', name, proposed(name)) for name in ['asset', 'work_order']])
    add('provider-capabilities', provider=PROVIDER, source='provider-capabilities', record_type='capability-declaration',
        purpose='AUTHORITY', subject=PROVIDER, record_id='maintenance-register-revision-3-capabilities',
        values={'provider': typed('IDENTITY', PROVIDER), **{name: typed('BOOLEAN', True) for name in CAPABILITY_FIELDS}},
        comparisons=[('EQUALS', 'provider', literal(typed('IDENTITY', PROVIDER)))] +
            [('EQUALS', name, literal(typed('BOOLEAN', True))) for name in CAPABILITY_FIELDS])
    return sorted(rows, key=lambda row: row['id']), facts


def source_referral_policy():
    common = {'queue': 'maintenance-review', 'safe_state': 'no-new-register-entry-or-physical-command'}
    return {'authority': [
        {'id': 'authority-reliability', 'destination_role': 'reliability-supervisor',
            'purpose': 'review-authority-or-gate-failure', 'via_role': None, 'requirement_ids': [], **common},
        {'id': 'authority-safety', 'destination_role': 'safety-compliance-lead',
            'purpose': 'review-safety-hold', 'via_role': 'reliability-supervisor',
            'requirement_ids': ['current-safety'], **common}],
        'completion': [
            {'id': 'completion-custodian', 'destination_role': 'maintenance-records-custodian',
                'purpose': 'investigate-native-record', 'via_role': None, 'requirement_ids': [], **common},
            {'id': 'completion-reliability', 'destination_role': 'reliability-supervisor',
                'purpose': 'review-completion-authority', 'via_role': None, 'requirement_ids': [], **common}]}


def source_authority(*, request_id=REQUEST_ID, instance_id=None, work_order='WO-7304', inspection='IN-552',
        approval='AP-091', gate_at=ORIGINAL_AT, inspection_at='2026-09-12T13:55:00Z', signed_at='2026-09-12T14:00:00Z'):
    original = equipment_original_fixture()
    authority = copy.deepcopy(original['authority_input'])
    authority['proposal']['instance'] = instance_id or request_id
    authority['clock']['instant'] = gate_at
    selected = {'work_order': work_order, 'inspection': inspection, 'approval': approval, 'effective_time': gate_at}
    for field in authority['proposal']['fields']:
        if field['name'] in selected:
            field['value']['value'] = selected[field['name']]
    for act in authority['acts']:
        if act['kind'] == 'GRANT':
            act.update(id=approval, occurred_at=signed_at)
        elif act['kind'] == 'VERIFY':
            act['occurred_at'] = gate_at
        elif act['kind'] == 'ORGANISATIONAL_ATTESTATION':
            act['occurred_at'] = signed_at
    authority['envelope']['grant_ref'] = approval
    authority['envelope']['temporal_validity']['valid_from'] = signed_at
    authority['source']['id'] = 'equipment-return-to-service-revision3-source'
    authority['source']['revision'] = 'revision-3-MCS-12-r4-DR-08-r2'
    authority['source']['obligations'] = source_obligations()
    authority['source']['obligations'].append({'id': 'equipment-provider-capability-premise',
        'text': 'Apparatus-only interface premise from revision 3 amendment 1 and the approved mediated-history profile: the Maintenance Register returns an authenticated current capability declaration for atomic tuple uniqueness, authoritative tuple and generated-event-ID lookup, conditional approval/policy-fenced write, and participation of all writers in the declared mediation. This fixture does not establish actual provider truth.'})
    authority['source']['obligations'].sort(key=lambda row: row['id'])
    if request_id != REQUEST_ID or authority['proposal']['instance'] != REQUEST_ID or selected != {
            'work_order': 'WO-7304', 'inspection': 'IN-552', 'approval': 'AP-091', 'effective_time': ORIGINAL_AT}:
        authority['source']['revision'] += '-later-facts'
        authority['source']['obligations'].append({'id': 'equipment-later-request-facts',
            'text': 'Apparatus-only complete later request facts under source line 56: ' + canonical_bytes({
                'request_id': request_id, 'instance_id': authority['proposal']['instance'], 'asset': 'EQ-204',
                **selected, 'inspection_completed_at': inspection_at, 'approval_signed_at': signed_at}).decode('utf-8')})
        authority['source']['obligations'].sort(key=lambda row: row['id'])
    authority['envelope']['source_obligations'] = sorted(row['id'] for row in authority['source']['obligations'])
    work = authority['work_class']
    for name, kind in [('BOOLEAN', 'BOOLEAN'), ('IDENTITY', 'IDENTITY'), ('POLICY_REVISION', 'STRING'), ('REQUEST_ID', 'IDENTITY')]:
        work['types'].append({'id': name, 'kind': kind, 'nonnegative': False, 'unit': None})
    work['types'].sort(key=lambda row: row['id'])
    step = work['steps'][0]
    step['exclusive_keys'] = source_keys(authority['proposal']['fields'], request_id)
    step['completion']['additional_fields'][0]['value']['value'] = canonical_bytes({
        'provider': PROVIDER, 'source': 'approval-register', 'record_type': 'approval',
        'provider_record_id': approval}).decode('utf-8')
    step['authority_type_refs'] = sorted(row['id'] for row in work['types'])
    step['dispatch_gate'] = {'approval_requirement': 'approval', 'withdrawal_requirement': 'approval-withdrawal',
        'policy_withdrawal_requirements': ['policy-dr-withdrawal', 'policy-mcs-withdrawal'],
        'fence_provider': PROVIDER, 'fence_source': 'conditional-return-to-service-write', 'authorization_seconds': '60'}
    requirements, values = source_requirements(authority, request_id, inspection_at)
    authority['envelope']['source_observation_requirements'] = requirements
    root = authority['host_selection']['root']
    root['providers'] = sorted(set(root['providers']) | {row['provider'] for row in requirements})
    mechanisms = authority['envelope']['enforcement']['mechanisms']
    if 'ATOMIC_RESERVATION_TRANSITION' not in mechanisms:
        mechanisms.append('ATOMIC_RESERVATION_TRANSITION')
    mechanisms.sort()
    authority, result = rebind_authority(authority)
    authority['observations'].extend(observation(row, authority, values=values[row['id']]) for row in requirements)
    authority['observations'].sort(key=lambda row: digest('authority-observation', row))
    result = expected_ready(authority, result)
    fields = {row['name']: row['value'] for row in authority['proposal']['fields']}
    result['required_exclusive_keys'] = [{'id': row['id'], 'slot': row['slot'], 'namespace': row['namespace'],
        'key': [copy.deepcopy(p.get('value', fields.get(p.get('field')))) for p in row['projection']],
        'retention': row['retention']} for row in step['exclusive_keys']]
    return original, authority, result, values


def equipment_base(**facts):
    original, authority, result, values = source_authority(**facts)
    instance_id = authority['proposal']['instance']
    definition = copy.deepcopy(original['definition'])
    source_step = authority['work_class']['steps'][0]
    step = definition['steps'][0]
    for name in ['quantity_mode', 'exclusive_keys', 'authority_type_refs', 'dispatch_gate', 'completion']:
        step[name] = copy.deepcopy(source_step[name])
    step['referral_policy'] = source_referral_policy()
    definition['types'] = copy.deepcopy(authority['work_class']['types'])
    definition['limits']['maximum_actuations'] = '1'
    definition['source'] = {'id': authority['source']['id'], 'revision': authority['source']['revision'],
        'obligations': sorted(row['id'] for row in authority['source']['obligations'])}
    definition['participants'] = sorted([
        {'id': 'shift-maintenance-coordinator-3', 'role': 'shift-maintenance-coordinator', 'kind': 'PERSON'},
        {'id': 'inspection-engineer-8', 'role': 'inspection-engineer', 'kind': 'PERSON'},
        {'id': 'reliability-supervisor-4', 'role': 'reliability-supervisor', 'kind': 'PERSON'},
        {'id': 'maintenance-records-clerk-17', 'role': 'maintenance-records-clerk', 'kind': 'PERSON'},
        {'id': PROVIDER, 'role': 'maintenance-register-service', 'kind': 'SYSTEM'},
        {'id': 'maintenance-records-custodian-12', 'role': 'maintenance-records-custodian', 'kind': 'PERSON'},
    ], key=lambda row: row['id'])
    definition['boundary_exits'] = [{'id': scope.lower() + '-exit', 'scope': scope,
        'owner_role': 'operations-control-room-lead', 'queue': 'operations-control-room',
        'purpose': 'separate-equipment-control-procedure', 'safe_state': 'no-register-update-or-physical-command',
        'reentry_requirements': ['new-approval', 'new-maintenance-request', 'separate-control-procedure']}
        for scope in ['MIXED_CONTROL', 'PHYSICAL_CONTROL']]
    definition['boundary_exits'].sort(key=lambda row: row['id'])
    definition_digest = digest('work-class-definition', definition)
    root_occurrence = occurrence(definition_digest, instance_id, step['id'])
    authority['proposal']['occurrence'] = root_occurrence['occurrence_id']
    authority, initial_result = rebind_authority(authority)
    authority['observations'].extend(observation(row, authority, values=values[row['id']])
        for row in authority['envelope']['source_observation_requirements'])
    authority['observations'].sort(key=lambda row: digest('authority-observation', row))
    updated = expected_ready(authority, initial_result)
    updated['required_exclusive_keys'] = result['required_exclusive_keys']
    result = updated
    deploy_input, deploy_result = deployment(definition, instance_id=instance_id,
        organization_id=PRINCIPAL, authorization_time='2026-09-12T13:59:00Z', evidence_expires_at='2026-09-13T00:00:00Z')
    clock = available_clock(authority['clock']['source'], '1', authority['clock']['instant'])
    clock_event = {'schema': 'seampoint.work-class/1.0.0-draft.3/runtime-event', 'event_id': 'equipment-clock-1',
        'kind': 'CLOCK', 'instance_id': instance_id, 'expected_state_revision': deploy_result['state']['revision'],
        'expected_state_digest': deploy_result['state_digest'], 'clock': clock, 'activation_clocks': []}
    def add_clock(state):
        state['clocks'].append(copy.deepcopy(clock))
    clock_result = admitted_transition(deploy_result['state'], clock_event, disposition='CLOCK_RECORDED',
        reason_codes=[], details=[{'kind': 'CLOCK', 'source': clock['source'], 'revision': '1', 'status': 'AVAILABLE'}], mutate=add_clock)
    executor = authority['proposal']['executor']
    proposal = {'schema': 'seampoint.work-class/1.0.0-draft.3/runtime-event', 'kind': 'PROPOSE',
        'event_id': 'equipment-proposal-1', 'instance_id': instance_id,
        'expected_state_revision': clock_result['state']['revision'], 'expected_state_digest': clock_result['state_digest'],
        'occurrence': root_occurrence,
        'native_request': {name: copy.deepcopy(authority['proposal'][name]) for name in ['interface', 'operation', 'fields']},
        'executor': {'participant_id': executor['actor'], 'role': executor['role'],
            'binding_digest': digest('executor-binding', executor)},
        'credential_ids': sorted(row['id'] for row in authority['credentials']), 'authority_input': authority,
        'budget_inputs': [], 'clock_revision': '1',
        'observation_digests': sorted(digest('authority-observation', row) for row in authority['observations'])}
    return {'definition': definition, 'definition_digest': definition_digest, 'deploy_input': deploy_input,
        'deploy_result': deploy_result, 'clock_event': clock_event, 'clock_result': clock_result,
        'authority_input': authority, 'authority_result': result, 'proposal_event': proposal,
        'source_values': values,
        'permit_expires_at': min(add_seconds(authority['clock']['instant'], '300'),
            authority['envelope']['temporal_validity']['valid_until'])}


def equipment_registry(base, *, history_records=None):
    authority = base['authority_input']
    config = {'schema': 'seampoint.work-class/1.0.0-draft.3/reservation-registry',
        'id': 'equipment-return-to-service-registry', 'principal': PRINCIPAL,
        'clock_source': authority['clock']['source'], 'administration_provider': 'maintenance-governance-register',
        'administration_source': 'exclusive-identifier-cutover', 'administration_role': 'maintenance-governance-lead',
        'slots': [], 'exclusive_slots': [{'slot': key['slot'], 'namespace': key['namespace'],
            'authorized_classes': [base['definition']['id']], 'retention': key['retention'], 'permit_seconds': '300'}
            for key in authority['work_class']['steps'][0]['exclusive_keys']]}
    facts = {'configuration': config, 'clock': copy.deepcopy(authority['clock']), 'authority_a': copy.deepcopy(authority),
        'authority_a_result': copy.deepcopy(base['authority_result'])}
    fields = {row['name']: row['value']['type_ref'] for row in authority['proposal']['fields']}
    held = [{'name': name, 'type_ref': fields[name]} for name in sorted(fields)]
    completed = held + [{'name': 'approval_register_link', 'type_ref': 'PROVIDER_LINK'},
        {'name': 'event_id', 'type_ref': 'EVENT_ID'}, {'name': 'event_timestamp', 'type_ref': 'INSTANT'},
        {'name': 'resulting_status', 'type_ref': 'STATUS'}]
    completed.sort(key=lambda row: row['name'])
    for slot in config['exclusive_slots']:
        names = SHAPES[slot['slot']]
        slot.update(authorized_classes=[base['definition']['id']],
            key_shape=[{'name': name, 'type_ref': fields.get(name, 'REQUEST_ID' if name == 'request_id' else 'IDENTITY')} for name in names],
            types=copy.deepcopy(base['definition']['types']), history_record_fields={'held': held, 'consumed': completed},
            history_projection=[{'key_field': name, 'kind': 'RECORD' if name in ['provider', 'source'] else
                'SOURCE_REQUEST' if name in ['issuer', 'request_id'] else 'NATIVE_FIELD',
                **({'member': name} if name in CONSTANTS else {'field': name}),
                'type_ref': fields.get(name, 'REQUEST_ID' if name == 'request_id' else 'IDENTITY')} for name in names],
            uniqueness={'kind': 'EXCLUSIVE_MEDIATOR_SEEDED', 'provider': PROVIDER, 'source': SOURCE,
                'record_type': 'return-to-service-history', 'history_scope': slot['slot'] + '-complete-prior-uses',
                'cutover_id': 'NPO-7-return-to-service-cutover-1', 'evidence_ref': 'host-all-writer-mediation-premise'})
        if slot['slot'] == 'approval-use':
            slot['history_projection'][1] = {'key_field': 'source', 'kind': 'LITERAL',
                'value': typed('IDENTITY', 'approval-register')}
    state = history_state(facts)
    seeds = []
    for slot in SHAPES:
        claims = [equipment_history_claim(facts, slot, record, request_id=request_id, status=status,
            work_occurrence=work_occurrence) for record, request_id, status, work_occurrence in (history_records or [])]
        supplied = seed_request(facts, state, slot, claims, 'equipment-seed-' + slot)
        basis = supplied['host_evidence']['administration_bases'][0]
        basis['actor'] = 'maintenance-governance-lead-2'
        act, returned = (supplied['event']['administration'][name] for name in ('act', 'returned'))
        act['actor'] = basis['actor']
        returned.update(actor=act['actor'], act_digest=digest('reservation-administration-act', act),
            act_bytes_base64=base64.b64encode(canonical_bytes(act)).decode('ascii'))
        for row in supplied['host_evidence']['authenticated_records']:
            if row['kind'] == 'ADMIN_RETURN':
                row['record_digest'] = digest('reservation-administration-return', returned)
        supplied['host_evidence']['authenticated_records'].sort(key=canonical_bytes)
        output = seed_result(facts, supplied)
        seeds.append((supplied, output))
        state = output['state']
    return facts, state, seeds


def equipment_history_claim(facts, slot, record, *, request_id=REQUEST_ID, status='CONSUMED', work_occurrence=None):
    configured = next(row for row in facts['configuration']['exclusive_slots'] if row['slot'] == slot)
    fields = copy.deepcopy(record['actual_fields'])
    if status == 'HELD':
        native_names = {row['name'] for row in facts['authority_a']['proposal']['fields']}
        fields = [row for row in fields if row['name'] in native_names]
    native_record = {'provider': record['provider'], 'source': record['source'],
        'record_type': configured['uniqueness']['record_type'], 'record_id': record['provider_record_id'],
        'revision': record['provider_revision'], 'occurred_at': record['event_time'], 'state': status,
        'native_fields': fields, 'work_occurrence': copy.deepcopy(work_occurrence),
        'evidence_ref': 'normalized-full-register-history-' + record['provider_record_id']}
    if status == 'HELD':
        native_record.update(record_id='retained-uncertain-attempt-' + request_id,
            revision='mediated-attempt-history-revision-1', evidence_ref='attributable-uncertain-attempt-history-' + request_id)
    record_digest = digest('exclusive-native-history', native_record)
    source_request = {'issuer': ISSUER, 'provider': 'maintenance-request-coordinator',
        'source': 'request-register', 'request_id': request_id}
    provenance = {'provider': PROVIDER, 'source': SOURCE, 'native_record_digest': record_digest,
        'source_request_digest': digest('exclusive-source-request', source_request),
        'evidence_ref': 'retained-request-to-event-binding-' + request_id,
        'provenance_digest': digest('source-observation-provenance', {'native_record_digest': record_digest,
            'source_request': source_request})}
    owner = {'kind': 'WORK_OCCURRENCE', **copy.deepcopy(work_occurrence)} if work_occurrence is not None else {
        'kind': 'NATIVE_HISTORY', 'provider': PROVIDER, 'source': SOURCE,
        'record_id': native_record['record_id'], 'record_digest': record_digest}
    key = project_history(configured, native_record, source_request)
    return {'slot': slot, 'namespace': configured['namespace'], 'key': key,
        'key_digest': digest('exclusive-key', {'registry': digest('reservation-registry', facts['configuration']),
            'slot': slot, 'namespace': configured['namespace'], 'key': key}),
        'owner': owner, 'acquisition_event': 'equipment-history-cutover', 'status': status,
        'settlement_evidence': native_record['record_id'] if status == 'CONSUMED' else None,
        'native_record': native_record, 'record_digest': record_digest,
        'source_request': source_request, 'request_provenance': provenance}


def equipment_permitted(base, *, registry_state=None, occupied=False, history_records=None):
    facts, seeded, seeds = equipment_registry(base, history_records=history_records)
    registry = copy.deepcopy(seeded if registry_state is None else registry_state)
    assert registry['core']['configuration'] == facts['configuration']
    proposal = copy.deepcopy(base['proposal_event'])
    registry_digest = digest('reservation-registry', facts['configuration'])
    reserve_id = digest('lifecycle-reservation-event', {'instance_id': proposal['instance_id'],
        'lifecycle_event_id': proposal['event_id'], 'lifecycle_event_kind': 'PROPOSE',
        'reservation_event_kind': 'RESERVE', 'registry_digest': registry_digest})
    event, host = host_and_event(facts, 'RESERVE', reserve_id, registry['core']['revision'],
        {'authority': facts['authority_a'], 'histories': [], 'exclusive_keys': base['authority_result']['required_exclusive_keys']}, administration=False)
    core = copy.deepcopy(registry['core'])
    record = reservation_record(facts, 'authority_a', reserve_id)
    record['permit_until'] = base['permit_expires_at']
    owner = {'kind': 'WORK_OCCURRENCE', 'work_class': base['definition']['id'],
        'instance_id': proposal['instance_id'], 'occurrence_id': proposal['occurrence']['occurrence_id']}
    occupied_keys = {row['key_digest'] for row in core['exclusive_keys']}
    assert occupied == any(row['key_digest'] in occupied_keys for row in record['exclusive_keys'])
    if not occupied:
        core['reservations'].append(record)
        core['reservations'].sort(key=lambda row: row['id'])
        core['exclusive_keys'].extend({**copy.deepcopy(row), 'owner': owner, 'acquisition_event': reserve_id,
            'status': 'HELD', 'settlement_evidence': None} for row in record['exclusive_keys'])
    core['exclusive_keys'].sort(key=lambda row: row['key_digest'])
    reserved = transition(registry, event, host, core, 'WITHHELD' if occupied else 'RESERVED',
        reservation_id=None if occupied else reserve_id, authority_result=base['authority_result'],
        reasons=['EXCLUSIVE_KEY_OCCUPIED'] if occupied else [])
    supplied = reservation_request(registry, event, host)
    proposal['budget_inputs'] = [{'registry_digest': registry_digest, 'affected_anchors': [],
        'expected_revision': registry['core']['revision'], 'request': supplied}]
    budget_output = {'registry_digest': registry_digest, 'affected_anchors': [], 'result': reserved}
    output = withheld_budget_proposal(base, proposal, budget_output) if occupied else permitted_budget_proposal(base, proposal, budget_output)
    base.update(reservation_facts=facts, reservation_result=reserved, key_proposal_event=proposal,
        registry_seed_trace=seeds, reservation_input=supplied)
    return output


def equipment_refresh(base, instant=None):
    authority = copy.deepcopy(base['authority_input'])
    authority['clock']['instant'] = instant or base['authority_input']['clock']['instant']
    authority['evaluation_point'] = 'DISPATCH'
    authority, result = rebind_authority(authority)
    authority['observations'].extend(observation(row, authority, values=base['source_values'][row['id']])
        for row in authority['envelope']['source_observation_requirements'])
    authority['observations'].sort(key=lambda row: digest('authority-observation', row))
    return authority


def equipment_authorized(base, permitted):
    event = authorization_event(base, permitted, event_id='equipment-authorize-1',
        intent='equipment-intent-1', authority_input=equipment_refresh(base))
    connector_body = {'id': 'maintenance-register-connector', 'version': 'revision-3'}
    event['connector'] = {**connector_body, 'binding_digest': digest('connector-binding', connector_body)}
    fresh_result = expected_ready(event['authority_input'], base['authority_result'])
    event['authorization_fence'], _ = derived_fence(base, event, fresh_result)
    output = authorization_result(base, permitted, event)
    return event, retained(output, permitted['permit'])


def equipment_dispatched(base, permitted, *, attempt_status='SENT', acknowledgement_status='NONE'):
    authorized_event, authorized = equipment_authorized(base, permitted)
    authorization = authorized['state']['authorizations'][0]
    event = dispatch_event(base, authorized, event_id='equipment-dispatch-1', attempt_status=attempt_status,
        acknowledgement_status=acknowledgement_status, attempted_at=base['authority_input']['clock']['instant'],
        authorization_digest=authorization['authorization_digest'])
    event['connector'] = copy.deepcopy(authorized_event['connector'])
    disposition, reasons, status = 'DISPATCH_RECORDED', [], 'DISPATCHED'
    if attempt_status == 'NOT_SENT':
        disposition, reasons, status = 'DISPATCH_REFUSED', ['NATIVE_NOT_SENT'], 'PERMITTED'
    elif attempt_status == 'REJECTED':
        disposition, reasons, status = 'DISPATCH_REFUSED', ['NATIVE_DISPATCH_REJECTED'], 'PERMITTED'
    elif acknowledgement_status == 'ACCEPTED':
        disposition = 'ACKNOWLEDGED'
    elif attempt_status == 'UNKNOWN':
        reasons = ['DISPATCH_STATUS_UNKNOWN']
    output = dispatch_result(authorized, event, disposition=disposition, reasons=reasons, occurrence_status=status)
    return authorized_event, authorized, event, retained(output, permitted['permit'])


def equipment_native(base, prior, *, evidence_id='equipment-completion-evidence-1',
        provider_record_id='RTS-EVT-901', provider_revision='maintenance-register-r17',
        actual_fields=None, status='EFFECT_ESTABLISHED', observed_at=None):
    at = base['authority_input']['clock']['instant']
    record = completion_native(base, prior, evidence_id=evidence_id, status=status,
        result_value='Return to Service', provider_record_id=provider_record_id, provider_revision=provider_revision,
        event_time=at, observed_at=observed_at or at, actual_fields=actual_fields,
        native_operation_id='maintenance-register-operation-' + base['proposal_event']['instance_id'])
    carrier = next(row for row in base['definition']['steps']
        if row['id'] == prior['permit']['occurrence']['step_id'])['completion']
    prefix = 'no_effect_' if status == 'NO_EFFECT_ESTABLISHED' else 'effect_'
    record.update({name: carrier[prefix + name] for name in ('provider', 'source', 'record_type')})
    record['record_digest'] = digest('provider-native-record', {name: record[name] for name in (
        'provider', 'source', 'record_type', 'provider_record_id', 'provider_revision', 'actual_fields', 'event_time')})
    return record


def equipment_settlement(base, prior, event, *, registry_state=None, mismatch=False,
        mismatch_reason='UNEXPECTED_EFFECT'):
    facts = base['reservation_facts']
    state = copy.deepcopy(base['reservation_result']['state'] if registry_state is None else registry_state)
    evidence = event['native_evidence']
    basis = prior['permit']['budget_revisions'][0]
    record = native(facts, 'EFFECT', evidence['evidence_id'], reservation_id=basis['reservation_id'])
    for name in ('provider', 'source', 'evidence_ref', 'actual_fields', 'collections', 'rules_out_past_and_future_effects'):
        record[name] = copy.deepcopy(evidence[name])
    native_names = {row['name'] for row in prior['permit']['native_request']['fields']}
    projected = [copy.deepcopy(row) for row in evidence['actual_fields'] if row['name'] in native_names]
    projected.sort(key=lambda row: row['name'])
    record['observed_request'] = copy.deepcopy(record['request']) if not mismatch and projected == prior['permit']['native_request']['fields'] else None
    record.update(effect_id=evidence['native_operation_id'], occurred_at=evidence['event_time'],
        completion_mismatch=mismatch, mismatch_reason=mismatch_reason if mismatch else None)
    settlement_id = digest('lifecycle-reservation-event', {'instance_id': event['instance_id'],
        'lifecycle_event_id': event['event_id'], 'lifecycle_event_kind': 'EFFECT_OBSERVED',
        'reservation_event_kind': 'SETTLE', 'registry_digest': basis['registry_digest']})
    settle, host = host_and_event(facts, 'SETTLE', settlement_id, state['core']['revision'],
        {'native': record, 'histories': []}, administration=False)
    supplied = {'registry_digest': basis['registry_digest'], 'affected_anchors': [],
        'expected_revision': state['core']['revision'], 'request': reservation_request(state, settle, host)}
    core = copy.deepcopy(state['core'])
    reservation = next(row for row in core['reservations'] if row['id'] == basis['reservation_id'])
    reservation['status'] = 'DISPUTED' if mismatch else 'SETTLED'
    if not mismatch:
        reservation['matched_effect'] = evidence['native_operation_id']
    if not mismatch:
        selected_keys = {row['key_digest'] for row in reservation['exclusive_keys']}
        for row in core['exclusive_keys']:
            if row['key_digest'] in selected_keys:
                row.update(status='CONSUMED', settlement_evidence=evidence['native_operation_id'])
    core['effects'].append(effect_record(record, 'DISPUTED' if mismatch else 'MATCHED',
        mismatch_reason if mismatch else 'MATCHED_EFFECT', affected_anchors=[]))
    core['effects'].sort(key=lambda row: row['id'])
    result = transition(state, settle, host, core, 'EFFECT_DISPUTED' if mismatch else 'SETTLED',
        reservation_id=basis['reservation_id'], reasons=[mismatch_reason] if mismatch else [])
    return supplied, {'registry_digest': basis['registry_digest'], 'affected_anchors': [], 'result': result}


def equipment_completed(base, prior, *, registry_state=None, evidence_id='equipment-completion-evidence-1',
        provider_record_id='RTS-EVT-901'):
    record = equipment_native(base, prior, evidence_id=evidence_id, provider_record_id=provider_record_id)
    event = governed_effect_event(prior, prior, record, event_id='equipment-effect-1', clock_revision=prior['permit']['clock_revision'])
    supplied, registry = equipment_settlement(base, prior, event, registry_state=registry_state)
    event['budget_inputs'] = [supplied]
    result = terminal_effect_result(base, prior, event, classification='MATCHED', disposition='COMPLETED',
        reason_codes=[], occurrence_status=None, disputed=False, complete_disposition='SUCCEEDED',
        route=True, budget_results=[registry])
    return event, retained(result, prior['permit']), registry


def equipment_failed(base, prior, actual_fields, *, event_id='equipment-completion-mismatch-1'):
    record = equipment_native(base, prior, actual_fields=actual_fields)
    event = governed_effect_event(prior, prior, record, event_id=event_id, clock_revision=prior['permit']['clock_revision'])
    mismatch_reason = 'UNEXPECTED_EFFECT'
    supplied, registry = equipment_settlement(base, prior, event, mismatch=True, mismatch_reason=mismatch_reason)
    event['budget_inputs'] = [supplied]
    reasons = sorted(['BUDGET_EFFECT_DISPUTED', mismatch_reason, 'UNEXPECTED_EFFECT'])
    result = terminal_effect_result(base, prior, event, classification='UNEXPECTED', disposition='DISPUTED',
        reason_codes=sorted(set(reasons)), occurrence_status='BLOCKED_DISPUTE', disputed=True, budget_results=[registry])
    return event, retained(result, prior['permit']), registry


def equipment_lookup(base, prior, *, status='NOT_FOUND', coverage='COMPLETE', as_of=None,
        event_id='equipment-lookup-1'):
    event = lookup_event(base, prior, status=status, coverage=coverage, as_of=as_of, event_id=event_id)
    return event, retained(lookup_result(base, prior, event), prior['permit'])


def equipment_late_exact(base, prior, *, blocked=False):
    record = equipment_native(base, prior, evidence_id='equipment-late-exact-evidence')
    event = governed_effect_event(prior, prior, record, event_id='equipment-late-exact-event',
        clock_revision=prior['permit']['clock_revision'])
    supplied, registry = equipment_settlement(base, prior, event)
    event['budget_inputs'] = [supplied]
    result = terminal_effect_result(base, prior, event, classification='LATE_MATCHED', disposition='OUTCOME_RETAINED',
        reason_codes=['DEPENDENCY_DISPUTED', 'LATE_EFFECT'] if blocked else ['LATE_EFFECT'],
        occurrence_status='BLOCKED_DISPUTE' if blocked else None, disputed=False,
        complete_disposition=None if blocked else 'SUCCEEDED', budget_results=[registry])
    return event, retained(result, prior['permit']), registry


def equipment_gate_failure(base, requirement_id, *, variant='FALSE', permitted=None, field_name=None):
    if permitted is None:
        event = copy.deepcopy(base['proposal_event'])
        before = base['clock_result']['state']
    else:
        event, _ = equipment_authorized(base, permitted)
        before = permitted['state']
        event['authorization_fence'] = None
    supplied = event['authority_input']
    row = next(row for row in supplied['observations'] if row['query'].get('requirement_id') == requirement_id)
    reason = 'SOURCE_OBSERVATION_RELATIONS'
    if variant == 'FALSE':
        boolean = next(field for field in row['fields'] if field['name'] == field_name) if field_name else next(field for field in row['fields'] if field['value']['type_ref'] == 'BOOLEAN')
        boolean['value']['value'] = False
    elif variant == 'MISSING_FIELD':
        row['fields'] = [field for field in row['fields'] if field['name'] != field_name]
        reason = 'SOURCE_OBSERVATION_FIELDS'
    elif variant == 'WRONG_ACTOR':
        next(field for field in row['fields'] if field['name'] == 'actor')['value']['value'] = 'another-clerk'
    elif variant == 'WRONG_ASSET':
        next(field for field in row['fields'] if field['name'] == 'asset')['value']['value'] = 'EQ-OTHER'
    elif variant == 'STALE':
        row['as_of'] = add_seconds(row['query']['at'], '-1')
        reason = 'SOURCE_OBSERVATION_STALE'
    elif variant in {'UNAVAILABLE', 'INCOMPLETE', 'ROLLED_BACK'}:
        req = next(item for item in supplied['envelope']['source_observation_requirements'] if item['id'] == requirement_id)
        changed = observation(req, supplied, values=base['source_values'][requirement_id], status=variant)
        row.clear()
        row.update(changed)
        reason = 'SOURCE_OBSERVATION_' + variant
    elif variant in {'AVAILABLE', 'ABSENT'}:
        req = next(item for item in supplied['envelope']['source_observation_requirements'] if item['id'] == requirement_id)
        changed = observation(req, supplied, values=base['source_values'][requirement_id], status=variant)
        row.clear()
        row.update(changed)
        reason = 'SOURCE_OBSERVATION_BINDING'
    elif variant == 'AT_GRANT':
        next(field for field in row['fields'] if field['name'] == 'completed_at')['value']['value'] = '2026-09-12T14:00:00Z'
    else:
        raise ValueError(variant)
    event['observation_digests'] = sorted(digest('authority-observation', row) for row in supplied['observations'])
    refusal = source_refusal(supplied, requirement_id, *([reason, 'SOURCE_OBSERVATION_RELATIONS'] if variant == 'MISSING_FIELD' else [reason]))
    result = withheld_proposal(base, event, refusal) if permitted is None else authorization_result(base, permitted, event, refusal=refusal)
    referrals = runpy.run_path(str(Path(__file__).with_name('build-equipment-referral-cases.py')))['add_referrals']
    result = referrals(base, before, event, result, refusal, requirement_id)
    return event, result, refusal


def equipment_correction(base, prior, original_record, *, changes=None):
    supplied, result = correction_fixture(changes=changes, original_record=original_record)
    supplied.update(definition=copy.deepcopy(base['definition']), definition_digest=base['definition_digest'],
        original_permit=copy.deepcopy(prior['permit']))
    result = correction_result(supplied, result['correction_authority_result'], result['new_approval_result'])
    return supplied, result


def equipment_boundary(base, scope):
    declared = next(row for row in base['definition']['boundary_exits'] if row['scope'] == scope)
    request_digest = digest('external-boundary-request', {'request_id': 'equipment-external-' + scope.lower(), 'scope': scope})
    body = {'definition_digest': base['definition_digest'], 'exit_id': declared['id'],
        'request_digest': request_digest, 'scope': scope, **{name: declared[name] for name in
            ['owner_role', 'queue', 'purpose', 'safe_state']}, 'evidence_ref': 'host-boundary-classification-' + scope.lower()}
    body['provenance_digest'] = digest('boundary-referral-provenance', body)
    record = {'referral_digest': digest('boundary-referral', body), **body}
    supplied = {'profile': 'LINEAR', 'role': 'REVIEW_EVIDENCE', 'specification_pin': candidate_pin(),
        'definition': copy.deepcopy(base['definition']), 'definition_digest': base['definition_digest'],
        'request_digest': request_digest, 'boundary_referral': record}
    expected = {'status': 'EVIDENCE_VALID', 'profile': 'LINEAR', 'role': 'REVIEW_EVIDENCE',
        'specification_pin': candidate_pin(), 'kind': 'BOUNDARY_REFERRAL', 'definition_digest': base['definition_digest'],
        'request_digest': request_digest, 'referral_digest': record['referral_digest']}
    return supplied, expected


def equipment_readback(base):
    lines = []
    def walk(node, path):
        if isinstance(node, dict) and node:
            for name, child in node.items():
                walk(child, path + '/' + name.replace('~', '~0').replace('/', '~1'))
        elif isinstance(node, list) and node:
            for index, child in enumerate(node):
                walk(child, path + '/' + str(index))
        else:
            lines.append({'path': path, 'value': canonical_bytes(node).decode('utf-8')})
    walk(base['definition'], '')
    supplied = {'kind': 'WORK_CLASS', 'specification_pin': candidate_pin(),
        'artifact_bytes_base64': base64.b64encode(canonical_bytes(base['definition'])).decode('ascii')}
    expected = {'status': 'READBACK', 'digest': base['definition_digest'],
        'lines': sorted(lines, key=lambda row: row['path'].encode('utf-8'))}
    return supplied, expected
