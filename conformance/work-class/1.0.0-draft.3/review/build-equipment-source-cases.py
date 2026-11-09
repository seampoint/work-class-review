#!/usr/bin/env python3
"""Construct complete source-derived equipment judgments without a consumer."""
from __future__ import annotations

import copy

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from authority_fixture import authority_refusal, envelope_validity_check
from equipment_correction_fixture import correction_refusal, seal_correction
from equipment_source_fixture import (CAPABILITY_FIELDS, REQUEST_ID, equipment_base, equipment_boundary, equipment_completed, equipment_correction,
    equipment_dispatched, equipment_failed, equipment_gate_failure, equipment_late_exact, equipment_lookup,
    equipment_permitted, equipment_readback, equipment_refresh)
from lifecycle_factory import replay_result, stateful_refusal, step_input


GROUP = CASES / 'equipment-source'


def public_result(result):
    value = copy.deepcopy(result)
    if value.get('status') == 'STEP' and value['decision']['disposition'] != 'PERMITTED':
        value['permit'] = None
    return value


def construct_cases():
    cases = []
    traces = {}
    def emit(operation, supplied, expected, derivation, refs):
        row = exact_case('C3-ES-' + str(len(cases) + 1).zfill(3), operation, supplied,
            public_result(expected), refs, derivation)
        cases.append(row)
        return row
    def step(base, before, event, result, derivation, refs=None):
        return emit('step', step_input(base, before, event), result, derivation, refs or ['LIFE-010', 'LIFE-012', 'RES-001A'])

    base = equipment_base()
    permitted = equipment_permitted(base)
    authorization_event, authorized, dispatch_event, dispatched = equipment_dispatched(base, permitted)
    completion_event, completed, settled = equipment_completed(base, dispatched)
    valid = []
    valid.append(emit('deploy', base['deploy_input'], base['deploy_result'],
        'The complete revision-3 source declares seven native fields, six participants, current source checks, five exclusive identifiers, four dispatch-fence sources and eleven completion fields. Deployment uses synthetic review and confirmation records.', ['LIFE-001', 'WCS2-006']))
    valid.append(step(base, base['deploy_result']['state'], base['clock_event'], base['clock_result'],
        'Accept the source gate clock at 2026-09-12T14:30:00Z. The grant is effective from 14:00 until the exclusive 23:59 end.', ['LIFE-014', 'AUTH-004']))
    for supplied, result in base['registry_seed_trace']:
        valid.append(emit('aggregate-step', supplied, result,
            'Seed one complete empty historical slot under an attributed Governance Lead cutover act. Native history, request-to-event provenance and all-writer mediation are explicit host premises.', ['RES-001A', 'RES-007A']))
    valid.append(step(base, base['clock_result']['state'], base['key_proposal_event'], permitted,
        'All sixteen source requirements establish the exact source and declared provider-capability facts. Reserve the complete five-key set atomically; the source selects NONE quantity and no numeric budget.', ['AUTH-007', 'LIFE-008', 'RES-001A']))
    valid.append(step(base, permitted['state'], authorization_event, authorized,
        'A fresh immediate gate verifies the existing AP-091 grant, independently reobtains four live records, and binds approval and three withdrawal sources under one provider fence.', ['AUTH-007', 'LIFE-009A']))
    valid.append(step(base, authorized['state'], dispatch_event, dispatched,
        'Retain one possibly sent seven-field Maintenance Register invocation. Request identity and issuer stay in source provenance and the reservation keys.', ['LIFE-009', 'LIFE-009A']))
    valid.append(step(base, dispatched['state'], completion_event, completed,
        'The exact eleven-field native event establishes one administrative result. Consume only the five keys of this reservation and retain the complete governed source event.', ['LIFE-010', 'LIFE-015', 'RES-001A']))
    traces['valid'] = valid
    step(base, completed['state'], completion_event, replay_result(completed['state'], completion_event['event_id']),
        'Exact completion replay returns the original result and preserves work and registry roots without another effect or reservation settlement.', ['LIFE-013'])
    expired = equipment_refresh(base, '2026-09-12T23:59:00Z')
    emit('evaluate', {'kind': 'AUTHORITY', 'request': expired}, authority_refusal([envelope_validity_check(expired)]),
        'AP-091 expires at the actual source end 2026-09-12T23:59:00Z. Fresh source observations at that instant cannot make the exclusive upper bound inclusive.', ['AUTH-005', 'WCS2-003'])

    for point in ['PROPOSE', 'DISPATCH']:
        selected_prior = None if point == 'PROPOSE' else permitted
        before = base['clock_result']['state'] if point == 'PROPOSE' else permitted['state']
        for requirement_id in ['current-session', 'current-role', 'current-duty', 'current-safety']:
            for variant in ['FALSE', 'STALE', 'UNAVAILABLE']:
                event, result, _ = equipment_gate_failure(base, requirement_id, variant=variant, permitted=selected_prior)
                row = step(base, before, event, result,
                    f'{point}: {requirement_id} {variant.lower()} does not establish its source fact. No transaction follows; Reliability Supervisor receives the failure, and only a safety failure adds the Safety Compliance Lead route through that owner.', ['AUTH-007', 'LIFE-006A', 'LIFE-009A'])
                if variant == 'FALSE':
                    traces[point.lower() + '-' + requirement_id] = valid[:7] + ([valid[7]] if selected_prior is not None else []) + [row]
        for requirement_id, variant in [
            ('current-session', 'WRONG_ACTOR'), ('current-role', 'WRONG_ACTOR'),
            ('current-duty', 'WRONG_ACTOR'), ('current-safety', 'WRONG_ASSET'),
            ('inspection', 'AT_GRANT'), ('historical-supervisor-duty', 'FALSE'),
            ('approval', 'FALSE'), ('request-identity', 'WRONG_ASSET'), ('work-order', 'WRONG_ASSET'),
            ('approval-withdrawal', 'AVAILABLE'), ('policy-dr-withdrawal', 'AVAILABLE'),
            ('policy-mcs-withdrawal', 'AVAILABLE'), ('completed-tuple-absence', 'AVAILABLE')]:
            event, result, _ = equipment_gate_failure(base, requirement_id, variant=variant, permitted=selected_prior)
            row = step(base, before, event, result,
                f'{point}: {requirement_id} fails its exact source relation or expected absence. The source permits no discretionary replacement fact, physical command or reused approval.', ['AUTH-004', 'AUTH-007', 'LIFE-006A'])
            if requirement_id == 'approval-withdrawal':
                traces[point.lower() + '-withdrawal'] = valid[:7] + ([valid[7]] if selected_prior is not None else []) + [row]
        for capability in CAPABILITY_FIELDS:
            for variant in ['FALSE', 'MISSING_FIELD']:
                event, result, _ = equipment_gate_failure(base, 'provider-capabilities', variant=variant,
                    permitted=selected_prior, field_name=capability)
                row = step(base, before, event, result,
                    f'{point}: the provider-capability {capability} is {variant.lower()}. The exact interface premise is unproven, so no permit or invocation follows and the general Reliability Supervisor referral retains the capability failure.', ['AUTH-007', 'LIFE-006A', 'LIFE-009A'])
                traces[point.lower() + '-capability-' + capability + '-' + variant.lower()] = [row]
        for variant in ['ABSENT', 'UNAVAILABLE']:
            event, result, _ = equipment_gate_failure(base, 'provider-capabilities', variant=variant, permitted=selected_prior)
            row = step(base, before, event, result,
                f'{point}: a provider-capabilities record returned {variant} establishes none of the five required capabilities. Host authentication of a record does not establish absent, unavailable or false values.', ['AUTH-007', 'LIFE-006A', 'LIFE-009A'])
            traces[point.lower() + '-capability-record-' + variant.lower()] = [row]

    full_record = completion_event['native_evidence']
    for field in full_record['actual_fields']:
        actual = [copy.deepcopy(row) for row in full_record['actual_fields'] if row['name'] != field['name']]
        event, result, _ = equipment_failed(base, dispatched, actual, event_id='equipment-missing-' + field['name'])
        row = step(base, dispatched['state'], event, result,
            'Missing native ' + field['name'] + ' is terminal completion failure. Preserve the full provider record, disputed reservation, held keys and both completion owner referrals.', ['LIFE-010', 'LIFE-012', 'RES-007'])
        if field['name'] == 'reason':
            traces['missing-native-field'] = valid[:-1] + [row]
    for field_name, wrong_value in [
        ('asset', 'EQ-OTHER'), ('approval_register_link', 'AP-091'),
        ('event_id', 'RTS-EVT-OTHER'), ('event_timestamp', '2026-09-12T14:29:59Z')]:
        actual = copy.deepcopy(full_record['actual_fields'])
        next(row for row in actual if row['name'] == field_name)['value']['value'] = wrong_value
        event, result, _ = equipment_failed(base, dispatched, actual, event_id='equipment-wrong-' + field_name)
        row = step(base, dispatched['state'], event, result,
            'The native ' + field_name + ' mismatch remains complete retained evidence and stops this instance. No inferred rollback, correction authority, second write or key release follows.', ['LIFE-010', 'LIFE-012', 'RES-007'])
        traces['mismatch-' + field_name] = valid[:-1] + [row]

    stopped = {}
    for status in ['NOT_FOUND', 'UNAVAILABLE', 'AMBIGUOUS', 'OVERFLOW']:
        event, result = equipment_lookup(base, dispatched, status=status, event_id='equipment-lookup-' + status.lower())
        stopped[status] = result
        row = step(base, dispatched['state'], event, result,
            'The bound ' + status + ' native lookup makes the source instance terminal and preserves both completion referral intents and the original five-key reservation. It does not create a native event or settle registry state.', ['LIFE-010', 'LIFE-012'])
        traces['lookup-' + status.lower()] = valid[:-1] + [row]
    for kwargs in [{'coverage': 'INCOMPLETE'}, {'as_of': '2026-09-12T14:29:59Z'}]:
        event, result = equipment_lookup(base, dispatched, **kwargs)
        step(base, dispatched['state'], event, result,
            'An incomplete or stale lookup remains uncertainty and retains the source safe state, terminal record, owner referrals and held identifier keys.', ['LIFE-010', 'LIFE-012'])
    for status in ['NOT_FOUND', 'AMBIGUOUS']:
        prior = stopped[status]
        event, result, _ = equipment_late_exact(base, prior, blocked=status == 'AMBIGUOUS')
        row = step(base, prior['state'], event, result,
            'Independently exact late native evidence consumes eligible held keys but preserves STOPPED status, the first terminal/referral history and absence of a new route. A prior ambiguous dispute remains blocked.', ['LIFE-012', 'RES-001A'])
        traces['late-exact-' + status.lower()] = traces['lookup-' + status.lower()] + [row]
    prior = stopped['NOT_FOUND']
    proposal = copy.deepcopy(base['proposal_event'])
    proposal.update(event_id='equipment-proposal-after-stop', expected_state_revision=prior['state']['revision'], expected_state_digest=prior['state_digest'])
    step(base, prior['state'], proposal, stateful_refusal(prior['state'], 'INSTANCE_NOT_ACTIVE'),
        'A stopped source instance cannot propose another transaction even with the original source authority packet.', ['LIFE-012'])

    correction_input, correction_output = equipment_correction(base, completed, full_record)
    row = emit('check-evidence', correction_input, correction_output,
        'A separate complete Correction Authorization and current Custodian attribution establish one reason correction linked to the exact original native identity, revision and provider record digest. Original work history and keys remain untouched.', ['WCS2-006', 'AUTH-004', 'LIFE-020A'])
    traces['source-correction'] = [row]
    invalid = copy.deepcopy(correction_input)
    invalid['correction']['expected_revision'] = 'another-original-revision'
    seal_correction(invalid['correction'])
    emit('check-evidence', invalid, correction_refusal('BINDING_MISMATCH'),
        'A separately authorized correction must still identify the exact original provider revision. Internal correction hashes do not replace that source binding.', ['WCS2-006', 'AUTH-004', 'LIFE-020A'])
    original_fields = {row['name']: row['value'] for row in full_record['actual_fields']}
    qualified = canonical_bytes({'provider': 'maintenance-register', 'source': 'approval-register',
        'record_type': 'approval', 'provider_record_id': 'AP-092'}).decode('utf-8')
    changes = [{'field': name, 'old_value': copy.deepcopy(original_fields[name]),
        'new_value': {'type_ref': original_fields[name]['type_ref'], 'value': value}}
        for name, value in [('approval', 'AP-092'), ('approval_register_link', qualified)]]
    supplied, result = equipment_correction(base, completed, full_record, changes=changes)
    row = emit('check-evidence', supplied, result,
        'A changed approval business field has a separately evaluated fresh AP-092 approval basis and a qualified corrected link to that exact approval-register identity. Correction admission supplies no fresh runtime permit or key release.', ['AUTH-004', 'LIFE-020A'])
    traces['source-correction-new-approval'] = [row]
    changes[1]['new_value']['value'] = 'AP-092'
    supplied, _ = equipment_correction(base, completed, full_record, changes=changes)
    emit('check-evidence', supplied, correction_refusal('BINDING_MISMATCH'),
        'Fresh correction and approval authorities cannot cure an unqualified corrected approval-register link. The exact declared provider/source/type/id tuple remains required.', ['LIFE-020A'])

    fresh_facts = {'request_id': 'RTS-REQ-418', 'instance_id': 'equipment-later-instance-418',
        'work_order': 'WO-7305', 'inspection': 'IN-553', 'approval': 'AP-093',
        'gate_at': '2026-09-12T14:40:00Z', 'inspection_at': '2026-09-12T14:32:00Z', 'signed_at': '2026-09-12T14:35:00Z'}
    collision_variants = [
        ('request-use', {'request_id': REQUEST_ID}), ('approval-use', {'approval': 'AP-091'}),
        ('work-order-use', {'work_order': 'WO-7304'}), ('inspection-use', {'inspection': 'IN-552'}),
        ('tuple-use', {'work_order': 'WO-7304', 'inspection': 'IN-552', 'approval': 'AP-091'})]
    for prior_status, registry in [('HELD', base['reservation_result']['state']), ('CONSUMED', settled['result']['state'])]:
        for slot, overrides in collision_variants:
            later = equipment_base(**(fresh_facts | overrides))
            refused = equipment_permitted(later, registry_state=registry, occupied=True)
            row = step(later, later['clock_result']['state'], later['key_proposal_event'], refused,
                'A distinct hypothetical later instance reuses a ' + prior_status + ' ' + slot + ' identifier. The altered external authority facts are explicit apparatus premises; atomic admission still withholds the whole set without disclosing the prior owner or reserving disjoint keys.', ['RES-001A', 'LIFE-008'])
            traces['collision-' + prior_status.lower() + '-' + slot] = [row]
    registry = settled['result']['state']
    later = equipment_base(**fresh_facts)
    later_permitted = equipment_permitted(later, registry_state=registry)
    row = step(later, later['clock_result']['state'], later['key_proposal_event'], later_permitted,
        'A distinct source-declared later request with new work order, completed inspection and independently fresh approval acquires five disjoint identifiers while the prior consumed claims remain retained.', ['RES-001A', 'LIFE-008'])
    traces['fresh-instance'] = [row]
    fresh_base = later
    fresh_authorization_event, fresh_authorized, fresh_dispatch_event, fresh_dispatched = equipment_dispatched(later, later_permitted)
    fresh_completion_event, fresh_completed, fresh_settled = equipment_completed(later, fresh_dispatched,
        registry_state=later['reservation_result']['state'], evidence_id='equipment-fresh-completion-evidence', provider_record_id='RTS-EVT-902')
    traces['fresh-instance'].append(step(later, later_permitted['state'], fresh_authorization_event, fresh_authorized,
        'The hypothetical fresh request obtains its own immediate gate and fresh approval fence. Prior instance authorizations supply no authority for this new native request.', ['AUTH-007', 'LIFE-009A']))
    traces['fresh-instance'].append(step(later, fresh_authorized['state'], fresh_dispatch_event, fresh_dispatched,
        'A separately permitted fresh request records its own seven-field invocation without reopening the completed original instance.', ['LIFE-009', 'LIFE-009A']))
    traces['fresh-instance'].append(step(later, fresh_dispatched['state'], fresh_completion_event, fresh_completed,
        'Exact fresh completion consumes only its own five held keys. The first instance native record, five consumed claims and settled reservation remain byte-for-byte retained.', ['LIFE-010', 'RES-001A']))
    for status in ['HELD', 'CONSUMED']:
        later = equipment_base(**fresh_facts)
        previous_occurrence = {'work_class': base['definition']['id'], 'instance_id': base['proposal_event']['instance_id'],
            'occurrence_id': base['proposal_event']['occurrence']['occurrence_id']}
        histories = [(full_record, REQUEST_ID, status, previous_occurrence if status == 'HELD' else None)]
        admitted = equipment_permitted(later, history_records=histories)
        for supplied, result in later['registry_seed_trace']:
            emit('aggregate-step', supplied, result,
                'Complete attributable ' + status + ' history preserves its ordered native projection and separate original request provenance. All five slots are protected before later admission.', ['RES-001A', 'RES-007A'])
        step(later, later['clock_result']['state'], later['key_proposal_event'], admitted,
            'The complete seeded ' + status + ' history has disjoint identifiers from the fresh later request. Its five prior claims remain protected while new keys become held.', ['RES-001A', 'LIFE-008'])
    traces['boundary-exits'] = []
    for scope in ['PHYSICAL_CONTROL', 'MIXED_CONTROL']:
        supplied, result = equipment_boundary(base, scope)
        traces['boundary-exits'].append(emit('check-evidence', supplied, result,
            'The complete source ' + scope + ' exit binds Operations Control Room Lead, the declared review queue, no-register-update-or-physical-command safe state and separate-procedure reentry requirements. Evidence validity supplies no work permit, physical command or delivery assertion.', ['LIFE-006A', 'BOUND-001']))
    supplied, result = equipment_readback(base)
    traces['boundary-exits'].append(emit('readback', supplied, result,
        'Complete source readback retains both physical/mixed-control exits, six participants, administrative scope and exactly seven native inputs. The source declares no physical-control operation.', ['WCS2-001', 'WCS2-002', 'BOUND-001']))
    supplied, _ = equipment_boundary(base, 'PHYSICAL_CONTROL')
    record = supplied['boundary_referral']
    record['owner_role'] = 'maintenance-records-clerk'
    body = {key: value for key, value in record.items() if key not in ['referral_digest', 'provenance_digest']}
    record['provenance_digest'] = digest('boundary-referral-provenance', body)
    record['referral_digest'] = digest('boundary-referral', {key: value for key, value in record.items() if key != 'referral_digest'})
    emit('check-evidence', supplied, correction_refusal('BINDING_MISMATCH'),
        'Fully rehashed boundary evidence cannot transfer physical-control ownership from Operations Control Room Lead to the Clerk.', ['BOUND-001'])
    for point in ['PROPOSE', 'DISPATCH']:
        prior = None if point == 'PROPOSE' else permitted
        before = base['clock_result']['state'] if prior is None else prior['state']
        event, result, _ = equipment_gate_failure(base, 'request-identity', variant='MISSING_FIELD', field_name='asset', permitted=prior)
        emit('step', step_input(base, before, event), result,
            point + ': a missing business fact follows the explicit Reliability Supervisor administrative review route. The source interpretation supplies no in-class fact-resolution branch, physical command or new register entry.', ['AUTH-007', 'LIFE-006A', 'BOUND-001'])
    return cases, traces, {'base': base, 'permitted': permitted, 'authorized': authorized, 'dispatched': dispatched,
        'completed': completed, 'settled': settled, 'completion_event': completion_event,
        'correction_input': correction_input, 'correction_output': correction_output, 'fresh_base': fresh_base,
        'fresh_permitted': later_permitted, 'fresh_completed': fresh_completed, 'fresh_settled': fresh_settled}


def main():
    cases, _, _ = construct_cases()
    for row in cases:
        write_canonical_json(GROUP / (row['id'] + '.json'), row)
    print({'cases': len(cases), 'inventory_digest': digest('equipment-source-author-cases', cases),
        'derivation': 'source and normative constructors only; consumers not consulted'})


if __name__ == '__main__':
    main()
