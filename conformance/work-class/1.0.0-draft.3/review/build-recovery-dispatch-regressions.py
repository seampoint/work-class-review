#!/usr/bin/env python3
"""Build unindexed recovery regression inputs from source fixture formulas only."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def build(repository, expected_pin):
    review = repository / 'conformance/work-class/1.0.0-draft.3/review'
    sys.path.insert(0, str(review))
    from corpus_common import candidate_pin, canonical_bytes, digest
    if candidate_pin() != expected_pin:
        raise RuntimeError("Selected contract differs from the released fixture candidate")
    from equipment_dispatch_fixture import authorization_event, authorization_result, clock_transition, retained
    from equipment_observation_fixture import authority_mutator
    from lifecycle_factory import (admitted_transition, base_lifecycle, dispatch_event, dispatch_result,
        effect_result, governed_effect_event, governed_native_evidence, permitted_proposal, step_input)
    from recovery_fixture import (authorize, configuration, disposition_expected, dispose_request,
        disputed, evidence_for, facts_for, generation, normalize_native, refresh_authentication, registered, reserve)
    from recovery_lifecycle_fixture import (PBR, PROJECTION_KEYS, dispute_prerequisite, supplier_chain,
        work_dispose_expected, work_dispose_request)
    from reservation_fixture import host_and_event, native, request

    def append(trace, name, operation, supplied, expected):
        trace.append({'name': name, 'operation': operation, 'input': copy.deepcopy(supplied),
                      'expected': copy.deepcopy(expected)})

    def work_dispose(base, before, original, permit, dispatch, desired, event_id):
        outcome = next(row for row in before['outcomes'] if row['native_evidence']['evidence_id'] == original['evidence_id'])
        target = {'kind': 'WORK_OUTCOME', 'instance_id': before['instance_id'],
                  'occurrence_id': permit['occurrence']['occurrence_id'], 'outcome_digest': outcome['outcome_digest']}
        retained_native = [row['native_evidence'] for row in before['outcomes'] if row['permit_digest'] == permit['permit_id']]
        retained_native.extend(value for row in before['recovery_records'] if row['disposition']['target'] == target
                               for value in row['disposition']['evidence']['native_outcomes'])
        selected = []
        if desired == 'ESTABLISH_NO_EFFECT':
            selected_native = copy.deepcopy(original)
            selected_native.update(evidence_id=event_id + '-no-effect', native_operation_id=event_id + '-no-effect',
                record_type='card-no-effect', status='NO_EFFECT_ESTABLISHED', event_time=None,
                actual_fields=[], collections=[], rules_out_past_and_future_effects=True)
            selected = [selected_native]
        facts = sorted({digest('recovery-fact', normalize_native(row)) for row in retained_native})
        clock = max((row for row in before['clocks'] if row['source'] == permit['clock_source']), key=lambda row: int(row['revision']))
        packet = {'id': event_id + '-packet', 'provider': original['provider'], 'source': original['source'],
            'record_type': 'RECOVERY_ADJUDICATION', 'record_digest': digest('provider-recovery-record', {'target': target, 'result': desired}),
            'evidence_ref': event_id + '-protected-evidence', 'provider_revision': '3', 'target': target,
            'request': copy.deepcopy(original['attributed_request']),
            'covered_evidence_digests': sorted(set(facts) | {digest('recovery-fact', normalize_native(row)) for row in selected}),
            'superseded_evidence_digests': facts, 'attempts': [{'id': dispatch['attempt']['attempt_id'],
                'attempt_digest': dispatch['dispatch_attempt_digest'], 'executor': permit['executor']['participant_id'],
                'connector': dispatch['connector']['id'], 'request_digest': digest('reservation-native-request', original['attributed_request']),
                'maximum_executions': '1', 'effect_ids': [], 'no_effect': desired == 'ESTABLISH_NO_EFFECT'}],
            'conclusion': 'NO_EFFECT_ESTABLISHED' if selected else 'UNRESOLVED', 'native_outcomes': selected,
            'rules_out_past_and_future_effects': bool(selected), 'complete_attempt_inventory': True}
        previous = [row['disposition'] for row in before['recovery_records'] if row['disposition']['target'] == target]
        event = {'schema': before['schema'].rsplit('/', 1)[0] + '/runtime-event', 'event_id': event_id, 'kind': 'DISPOSE',
            'instance_id': before['instance_id'], 'expected_state_revision': before['revision'], 'expected_state_digest': digest_state(before),
            'target': target, 'requested_result': desired, 'evidence': packet, 'controller': None, 'policy_digest': None,
            'supersedes': previous[-1]['id'] if previous else None, 'clock_revision': clock['revision'], 'activation_clocks': []}
        host = {'caller': permit['executor']['participant_id'], 'recovery_bases': [], 'authenticated_records': [
            {'kind': 'RECOVERY_EVIDENCE', 'record_digest': digest('recovery-evidence', packet),
             'provider': packet['provider'], 'source': packet['source']}], 'pending_evidence': []}
        if selected:
            authority_facts = {'configuration': {'principal': before['deployment_organization_id'], 'recovery': base['definition']['recovery']},
                               'clock': {'instant': clock['observed_time']}}
            authorize(authority_facts, event, host, operation=desired, scope_digest=digest('recovery-target', target))
        supplied = step_input(base, before, event)
        supplied['recovery_host'] = host
        identity = {'incident_digest': digest('recovery-incident', {'principal': before['deployment_organization_id'], 'target': target}),
            'generation_digest': generation(packet), 'result': desired, 'policy_digest': None,
            'controller': copy.deepcopy(event['controller']), 'supersedes': event['supersedes']}
        disposition = {'id': digest('recovery-disposition', identity), **identity, 'acceptance_basis_digest': None,
            'target': target, 'evidence': copy.deepcopy(packet), 'event_digest': digest('runtime-event', event),
            'accepted_at': clock['observed_time'], 'source_event': copy.deepcopy(event)}

        def mutate(state):
            before_projection = {name: copy.deepcopy(state[name]) for name in PROJECTION_KEYS}
            if selected:
                active = next(row for row in state['active'] if row['occurrence']['occurrence_id'] == target['occurrence_id'])
                state['active'].remove(active)
                state['completed'].append({'occurrence': copy.deepcopy(active['occurrence']), 'disposition': 'NO_EFFECT',
                    'evidence_digest': digest('native-evidence', selected[0]), 'occurred_at': selected[0]['observed_at'],
                    'route_label': None, 'selected_relationship_digest': None, 'late': False})
                state['completed'].sort(key=lambda row: canonical_bytes(row['occurrence']))
                state['status'] = 'STOPPED'
            state['recovery_records'].append({'event': copy.deepcopy(event), 'host_evidence': copy.deepcopy(host),
                'disposition': copy.deepcopy(disposition), 'before_projection': before_projection,
                'after_projection': {name: copy.deepcopy(state[name]) for name in PROJECTION_KEYS}})

        expected = admitted_transition(before, event, disposition='STOPPED' if selected else 'DISPOSITION_RECORDED',
            reason_codes=['NO_EFFECT_ESTABLISHED'] if selected else [], details=[],
            receipt_recovery_disposition_digest=disposition['id'], mutate=mutate)
        return supplied, expected

    from lifecycle_factory import state_digest as digest_state
    base = base_lifecycle(instance_id='recovery-dispatch-regression', authority_mutator=authority_mutator,
                          definition_mutator=lambda definition: definition.update(recovery=configuration()))
    trace = []
    append(trace, 'deployment', 'deploy', base['deploy_input'], base['deploy_result'])
    append(trace, 'clock', 'step', step_input(base, base['deploy_result']['state'], base['clock_event']), base['clock_result'])
    proposed = permitted_proposal(base)
    append(trace, 'proposal', 'step', step_input(base, base['clock_result']['state'], base['proposal_event']), proposed)
    permit = proposed['permit']
    event = authorization_event(base, retained(proposed, permit))
    authorized = authorization_result(base, retained(proposed, permit), event)
    append(trace, 'authorization', 'step', step_input(base, proposed['state'], event), authorized)
    current = retained(authorized, permit)
    event = dispatch_event(base, current, event_id='recovery-regression-send',
                           authorization_digest=authorized['state']['authorizations'][0]['authorization_digest'])
    sent = dispatch_result(current, event, disposition='DISPATCH_RECORDED', reasons=[], occurrence_status='DISPATCHED')
    append(trace, 'dispatch', 'step', step_input(base, authorized['state'], event), sent)
    evidence = governed_native_evidence(base, retained(proposed, permit), sent, evidence_id='recovery-regression-unknown', status='OUTCOME_UNKNOWN')
    event = governed_effect_event(retained(proposed, permit), sent, evidence, event_id='recovery-regression-unknown-event')
    unknown = effect_result(base, retained(proposed, permit), sent, event, classification='UNKNOWN',
                            disposition='OUTCOME_RETAINED', reason_codes=['UNKNOWN_OUTCOME'], occurrence_status='OUTCOME_UNKNOWN', disputed=False)
    append(trace, 'unknown-outcome', 'step', step_input(base, sent['state'], event), unknown)
    dispatch = sent['state']['dispatches'][0]
    supplied, first = work_dispose(base, unknown['state'], evidence, permit, dispatch, 'LEAVE_UNRESOLVED', 'recovery-regression-leave')
    append(trace, 'first-recovery', 'step', supplied, first)
    supplied, second = work_dispose(base, first['state'], evidence, permit, dispatch, 'ESTABLISH_NO_EFFECT', 'recovery-regression-complete')
    append(trace, 'completion-recovery', 'step', supplied, second)
    event, clocked = clock_transition(retained(second, permit), revision='2')
    clocked['permit'] = None
    append(trace, 'post-recovery-clock', 'step', step_input(base, second['state'], event), clocked)

    chain = supplier_chain()
    restoration = [{'name': 'supplier-' + str(index), 'operation': operation, 'input': supplied, 'expected': expected}
                   for index, ((operation, supplied), expected) in enumerate(zip(chain['requests'], chain['results'], strict=True))]
    supplied, blocked = dispute_prerequisite(chain)
    append(restoration, 'supplier-dispute', 'step', supplied, blocked)
    supplied = work_dispose_request(chain, blocked['state'], event_id='recovery-regression-restore')
    restored = work_dispose_expected(supplied)
    append(restoration, 'supplier-restoration', 'step', supplied, restored)
    supplied = work_dispose_request(chain, restored['state'], result='LEAVE_UNRESOLVED', event_id='recovery-regression-after-restore')
    supplied['event']['supersedes'] = restored['state']['recovery_records'][-1]['disposition']['id']
    latest = work_dispose_expected(supplied)
    append(restoration, 'supplier-second-recovery', 'step', supplied, latest)
    event = PBR['clock_event'](latest['state'], 'recovery-regression-supplier-clock', source='governance-clock', revision='2', observed_time='2026-09-11T12:00:01Z')
    _, clocked = PBR['accepted_clock'](latest['state'], event)
    append(restoration, 'supplier-post-recovery-clock', 'step', PBR['lifecycle_input'](chain['definition'], chain['definition_digest'], latest['state'], event), clocked)

    application_source = review.parent / 'specimens/supplier-payment-recovery'
    source_spec = importlib.util.spec_from_file_location('recovery_application_source', application_source / 'build-specimen.py')
    application_builder = importlib.util.module_from_spec(source_spec)
    source_spec.loader.exec_module(application_builder)
    application_base = application_builder.load_base()
    _, application_definition, _, _ = application_base.build_static_contract()
    application_work = json.loads((application_source / 'restart/after-payment-unknown-work-state.json').read_bytes())
    application_budget = json.loads((application_source / 'restart/after-payment-unknown-budget-state.json').read_bytes())
    if (application_definition['specification_pin'] != expected_pin
            or application_work['work_class_digest'] != digest('work-class-definition', application_definition)
            or application_budget['specification_pin'] != expected_pin):
        raise RuntimeError('Authored application checkpoint differs from selected source definition')
    application_facts = {'configuration': application_budget['core']['configuration'],
        'clock': {'source': application_budget['core']['configuration']['clock_source'], 'status': 'AVAILABLE',
                  'instant': application_budget['core']['last_clock']}, 'budget': application_budget['core']['budgets'][0]['definition'],
        'history': application_budget['core']['budgets'][0]['history'],
        'authority_a': application_budget['core']['reservations'][0]['authority']}
    application_native = copy.deepcopy(application_budget['core']['effects'][0]['native'])
    application_native.update(id='recovery-regression-application-no-effect', outcome='NO_EFFECT', effect_id=None,
        occurred_at=None, observed_request=None, actual_fields=[], collections=[],
        rules_out_past_and_future_effects=True, completion_mismatch=True, mismatch_reason='UNEXPECTED_EFFECT')
    packet = application_builder.packet_for(application_base, application_budget, application_work,
        application_native, 'NO_EFFECT_ESTABLISHED')
    registry_request = dispose_request(application_facts, application_budget, 'ESTABLISH_NO_EFFECT',
        event_id='recovery-regression-application-registry-dispose', evidence=packet)
    registry_expected = disposition_expected(registry_request)
    disposition = registry_expected['state']['core']['recovery']['dispositions'][0]
    applied_input = application_builder.apply_request(application_base, application_definition, application_work,
        registry_expected['state'], disposition, 'recovery-regression-apply-disposition')
    applied_input['recovery_registries'] = [copy.deepcopy(applied_input['event']['registry'])]

    def apply_registry(state):
        before_projection = {name: copy.deepcopy(state[name]) for name in PROJECTION_KEYS}
        if state['status'] == 'ACTIVE':
            active = next(row for row in state['active'] if row['occurrence']['step_id'] == 'pay-invoice')
            evidence = application_builder.lifecycle_native(application_definition, disposition)
            state['active'].remove(active)
            state['completed'].append({'occurrence': copy.deepcopy(active['occurrence']), 'disposition': 'NO_EFFECT',
                'evidence_digest': digest('native-evidence', evidence), 'occurred_at': evidence['observed_at'],
                'route_label': None, 'selected_relationship_digest': None, 'late': False})
            state['completed'].sort(key=lambda row: canonical_bytes(row['occurrence']))
            state['status'] = 'STOPPED'
        state['recovery_records'].append({'event': copy.deepcopy(applied_input['event']),
            'host_evidence': copy.deepcopy(applied_input['recovery_host']), 'disposition': copy.deepcopy(disposition),
            'before_projection': before_projection, 'after_projection': {name: copy.deepcopy(state[name]) for name in PROJECTION_KEYS},
            'registry_selections': copy.deepcopy(applied_input['recovery_registries'])})

    stops = application_work['status'] == 'ACTIVE'
    applied = admitted_transition(application_work, applied_input['event'], disposition='STOPPED' if stops else 'DISPOSITION_APPLIED',
        reason_codes=['NO_EFFECT_ESTABLISHED'] if stops else [], details=[],
        receipt_recovery_disposition_digest=disposition['id'], mutate=apply_registry)
    application = []
    append(application, 'registry-application', 'step', applied_input, applied)
    event = PBR['clock_event'](applied['state'], 'recovery-regression-application-clock', source='governance-clock',
                             revision='2', observed_time='2026-09-11T12:00:01Z')
    _, clocked = PBR['accepted_clock'](applied['state'], event)
    append(application, 'application-post-recovery-clock', 'step',
        application_builder.lifecycle_input(application_definition, applied['state'], event), clocked)

    facts = facts_for()
    before = disputed(facts)
    packet = evidence_for(facts, before, conclusion='NO_EFFECT_ESTABLISHED', attempts=1)
    clean_digest = digest('recovery-fact', normalize_native(packet['native_outcomes'][0]))
    packet['native_outcomes'][0].update(completion_mismatch=True, mismatch_reason='UNEXPECTED_EFFECT')
    packet['covered_evidence_digests'] = sorted((set(packet['covered_evidence_digests']) - {clean_digest})
        | {digest('recovery-fact', normalize_native(packet['native_outcomes'][0]))})
    positive = dispose_request(facts, before, 'ESTABLISH_NO_EFFECT', event_id='recovery-regression-mismatch', evidence=packet)
    registry = [{'name': 'mismatch-no-effect', 'input': positive, 'expected': disposition_expected(positive)}]
    for name in ('mixed-unknown', 'empty-native', 'false-native-exclusion', 'incomplete-attempt-inventory'):
        supplied = copy.deepcopy(positive)
        supplied['event']['id'] = 'recovery-regression-' + name
        evidence = supplied['event']['payload']['evidence']
        if name == 'mixed-unknown':
            old = digest('recovery-fact', normalize_native(evidence['native_outcomes'][0]))
            evidence['native_outcomes'][0].update(completion_mismatch=False, mismatch_reason=None)
            evidence['covered_evidence_digests'] = sorted((set(evidence['covered_evidence_digests']) - {old})
                | {digest('recovery-fact', normalize_native(evidence['native_outcomes'][0]))})
            extra = native(facts, 'UNKNOWN', name, reservation_id=evidence['target']['reservation'], request_record=evidence['request'])
            extra.update(provider=evidence['provider'], source=evidence['source'])
            evidence['native_outcomes'].append(extra)
            evidence['covered_evidence_digests'] = sorted(set(evidence['covered_evidence_digests']) | {digest('recovery-fact', normalize_native(extra))})
        elif name == 'empty-native':
            old = digest('recovery-fact', normalize_native(evidence['native_outcomes'][0]))
            evidence['native_outcomes'] = []
            evidence['covered_evidence_digests'] = sorted(set(evidence['covered_evidence_digests']) - {old})
        elif name == 'false-native-exclusion':
            old = digest('recovery-fact', normalize_native(evidence['native_outcomes'][0]))
            evidence['native_outcomes'][0]['rules_out_past_and_future_effects'] = False
            evidence['covered_evidence_digests'] = sorted((set(evidence['covered_evidence_digests']) - {old}) | {digest('recovery-fact', normalize_native(evidence['native_outcomes'][0]))})
        else:
            evidence['complete_attempt_inventory'] = False
        refresh_authentication(facts, supplied)
        registry.append({'name': name, 'input': supplied, 'selected_expected': {'decision': 'WITHHELD', 'reason': 'RECOVERY_EVIDENCE_INCOMPLETE'}})
    missing_remit = copy.deepcopy(positive)
    missing_remit['host_evidence']['recovery']['recovery_bases'][0]['operations'].remove('RELEASE_DISPUTED_EXPOSURE')
    registry.append({'name': 'missing-release-remit', 'input': missing_remit,
                     'selected_expected': {'status': 'REFUSED', 'code': 'ADMINISTRATION_NOT_ESTABLISHED'}})
    contrary_before = disputed(facts, result_kind='EFFECT')
    contrary_packet = evidence_for(facts, contrary_before, conclusion='NO_EFFECT_ESTABLISHED', attempts=1)
    contrary_packet['superseded_evidence_digests'] = []
    supplied = dispose_request(facts, contrary_before, 'ESTABLISH_NO_EFFECT', event_id='recovery-regression-contrary-effect', evidence=contrary_packet)
    registry.append({'name': 'contrary-effect', 'input': supplied,
                     'selected_expected': {'decision': 'WITHHELD', 'reason': 'RECOVERY_CONFLICT_UNRESOLVED'}})
    _, reserved = reserve(facts, registered(facts))
    no_effect = native(facts, 'NO_EFFECT', 'recovery-regression-ordinary-mismatch', completion_mismatch=True, mismatch_reason='UNEXPECTED_EFFECT')
    event, host = host_and_event(facts, 'RELEASE', 'recovery-regression-ordinary-release', reserved['state']['core']['revision'], {'native': no_effect}, administration=False)
    ordinary = {'input': request(reserved['state'], event, host), 'selected_expected': {
        'decision': 'EFFECT_DISPUTED', 'reason': 'UNEXPECTED_EFFECT', 'reservation_status': 'DISPUTED'}}
    if any(name == 'consumer' or name.startswith('implementation.') for name in sys.modules):
        raise RuntimeError('Source fixture constructor imported a consumer')
    sources = {Path(module.__file__).resolve() for module in sys.modules.values()
               if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(review)}
    sources.update({Path(__file__).resolve(), review / 'build-prior-binding-restart-cases.py',
        review.parent / 'specimens/supplier-payment/build-specimen.py',
        application_source / 'build-specimen.py', application_source / 'restart/after-payment-unknown-work-state.json',
        application_source / 'restart/after-payment-unknown-budget-state.json',
        repository / 'conformance/work-class/1.0.0-draft.1/cases-authority-initial/positive-access-card.json',
        repository / 'library/work-class-specification/1.0.0-draft.1/examples/aggregate-sum-boundary.json',
        *(repository / 'library/work-class-specification/1.0.0-draft.3' / name for name in
          ('contract-manifest.json', 'RECOVERY.md', 'LIFECYCLE.md', 'OBSERVATIONS-AND-DISPATCH.md'))})
    sources = sorted(sources)
    if any(not path.is_relative_to(repository) or 'runs' in path.relative_to(repository).parts for path in sources):
        raise RuntimeError('Fixture sources must be public repository-relative files')
    return {'specification_pin': candidate_pin(), 'expected_basis': 'Source fixture formulas and selected RECOVERY/LIFECYCLE properties; consumer outputs not used.',
        'sources': [{'path': str(path.relative_to(repository)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in sources],
        'traces': [{'name': 'gated-completion', 'rows': trace}, {'name': 'supplier-restoration', 'rows': restoration},
                   {'name': 'registry-application', 'rows': application}],
        'application_registry': {'input': registry_request, 'expected': registry_expected},
        'registry_controls': registry, 'ordinary_release': ordinary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument('--output-file', type=Path, required=True)
    parser.add_argument('--expected-pin', required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    data = build(args.repository.resolve(), args.expected_pin)
    with args.output_file.open('xb') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode() + b'\n')
    print(json.dumps({'fixture': str(args.output_file), 'specification_pin': data['specification_pin'],
                      'sha256': hashlib.sha256(args.output_file.read_bytes()).hexdigest(),
                      'consumer_imports': 0, 'adapter_processes': 0}))


if __name__ == '__main__':
    main()
