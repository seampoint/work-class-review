#!/usr/bin/env python3
"""Construct fixed CDMO source judgments before invoking any consumer."""
from __future__ import annotations
import copy
import runpy
from pathlib import Path
from authority_fixture import authority_refusal
from corpus_common import CASES, candidate_pin, canonical_bytes, digest, exact_case, write_canonical_json
from cdmo_fixture import (SCHEMA, cdmo_authority, cdmo_trace, cdmo_correction, cdmo_completed, cdmo_late_exact, cdmo_native, expected_authority,
    fields, refreshed, seal_correction, typed)
from equipment_completion_fixture import lookup_event, lookup_result
from equipment_observation_fixture import observation, source_check
from lifecycle_factory import replay_result, step_input

GROUP = CASES / 'cdmo-source'


def public_result(value):
    result = copy.deepcopy(value)
    if result.get('status') == 'STEP' and result['decision']['disposition'] != 'PERMITTED':
        result['permit'] = None
    return result


def readback(definition):
    lines = []
    def walk(node, path):
        if isinstance(node, dict) and node:
            for name, value in node.items():
                walk(value, path + '/' + name.replace('~', '~0').replace('/', '~1'))
        elif isinstance(node, list) and node:
            for index, value in enumerate(node):
                walk(value, path + '/' + str(index))
        else:
            lines.append({'path': path, 'value': canonical_bytes(node).decode()})
    walk(definition, '')
    return {'status': 'READBACK', 'digest': digest('work-class-definition', definition),
        'lines': sorted(lines, key=lambda row: row['path'].encode())}


def phase5_refusal(authority, failed_checks, *, leaf_results=None):
    result = authority_refusal(failed_checks)
    result['decision_results'] = expected_authority(authority, selected_leaf_results=leaf_results)['decision_results']
    return result


def correction_refusal(code):
    return {'status': 'EVIDENCE_INVALID', 'profile': 'LINEAR', 'role': 'REVIEW_EVIDENCE',
        'specification_pin': candidate_pin(), 'code': code, 'path': ''}


def construct_cases():
    cases, groups = [], {}
    def emit(operation, supplied, expected, derivation, refs, family=None):
        row = exact_case('C3-CD-' + str(len(cases) + 1).zfill(3), operation, supplied,
            public_result(expected), refs, derivation)
        cases.append(row)
        if family:
            groups.setdefault(family, []).append(row)
        return row
    def step(base, prior, event, expected, derivation, refs, family=None):
        return emit('step', step_input(base, prior, event), expected, derivation, refs, family)
    trace = cdmo_trace(); base = trace['base']
    emit('evaluate', {'kind': 'AUTHORITY', 'request': base['authority_input']}, base['authority_result'],
        'Both complete independent HUMAN decisions remain effective after ordinary signer occupancy ends; the actual executor is current. HIGH materiality and LOW reversibility select the exact Cedar decision as the DECIDE gate without a third approval.', ['AUTH-008','AUTH-009'], 'authority-positive')
    emit('readback', {'kind': 'WORK_CLASS', 'specification_pin': candidate_pin(),
        'artifact_bytes_base64': __import__('base64').b64encode(canonical_bytes(base['definition'])).decode()}, readback(base['definition']),
        'Read back every complete definition leaf, including independent-decision correction policy, source-vector gate and historical authorization revision binding.', ['WCS2-005'], 'readback')
    emit('deploy', base['deploy_input'], base['deploy_result'],
        'Deploy one administrative inventory transition with fourteen native fields, no numeric quantity, two exclusive identities and synthetic review/confirmation carriers. Synthetic acceptance does not prove source fidelity.', ['LIFE-001','WCS2-006'], 'valid-trace')
    step(base, base['deploy_result']['state'], base['clock_event'], base['clock_result'],
        'Record the 12:10 proposal clock after both human signers ordinary occupancy has ended.', ['LIFE-014','AUTH-008'], 'valid-trace')
    for supplied, expected in base['registry_seed_trace']:
        emit('aggregate-step', supplied, expected,
            'Seed complete empty prior history for one immutable request/disposition uniqueness domain under separately authenticated administration. All-writer mediation and complete history remain host premises.', ['RES-001A','RES-007A'], 'valid-trace')
    step(base, base['clock_result']['state'], base['key_proposal_event'], trace['permitted'],
        'Permit the exact fourteen-field request after admitting both human decisions and twenty independent current source requirements. Atomically hold request and approved-disposition keys.', ['AUTH-008','AUTH-009','LIFE-008','RES-001A'], 'valid-trace')
    step(base, trace['permitted']['state'], base['dispatch_clock_event'], base['dispatch_clock_result'],
        'Record a separate 12:11 dispatch clock; the proposal snapshot does not replace fresh current facts.', ['LIFE-014','LIFE-009B'], 'valid-trace')
    step(base, base['dispatch_clock_result']['state'], trace['authorization_event'], trace['authorized'],
        'Refresh both complete leaves and all mutable observations. Bind eighteen guarded sources, exact coordinator QG-42, both decision endpoints and effective reliance ends into one dispatch authorization.', ['AUTH-008','LIFE-009B'], 'valid-trace')
    step(base, trace['authorized']['state'], trace['dispatch_event'], trace['dispatched'],
        'Retain one possibly sent native invocation attributed to the exact connector, permit and authorization. Executor validity is checked at dispatch.', ['LIFE-009','LIFE-009B'], 'valid-trace')
    step(base, trace['dispatched']['state'], trace['completion_clock_event'], trace['completion_ready'],
        'Record the 12:11:01 completion clock and bind reservation settlement to that same accepted instant.', ['LIFE-014','RES-001A'], 'valid-trace')
    step(base, trace['completion_ready']['state'], trace['completion_event'], trace['completed'],
        'The real new_status field satisfies both exact request binding and completion-status membership. All eighteen native fields match, including old status and QG-42 from this exact historical dispatch authorization; consume both claims.', ['LIFE-010','LIFE-015','RES-001A'], 'valid-trace')
    step(base, trace['completed']['state'], trace['completion_event'], replay_result(trace['completed']['state'], trace['completion_event']['event_id']),
        'Exact completion replay returns the retained result with no new effect or key settlement.', ['LIFE-013'], 'replay')
    for point in ['PROPOSE','DISPATCH']:
        original = base['authority_input'] if point == 'PROPOSE' else trace['authorization_event']['authority_input']
        for requirement in original['envelope']['source_observation_requirements']:
            req_id = requirement['id']
            old = next(row for row in original['observations'] if row['query'].get('requirement_id') == req_id)
            variants = ['UNAVAILABLE','STALE','CONTRADICTORY']
            for variant in variants:
                authority = copy.deepcopy(original)
                selected = next(row for row in authority['observations'] if row['query'].get('requirement_id') == req_id)
                reason = 'SOURCE_OBSERVATION_UNAVAILABLE' if variant == 'UNAVAILABLE' else 'SOURCE_OBSERVATION_STALE' if variant == 'STALE' else 'SOURCE_OBSERVATION_BINDING' if requirement['expected_status'] == 'ABSENT' else 'SOURCE_OBSERVATION_RELATIONS'
                if variant == 'STALE':
                    from fixture_factory import add_seconds
                    selected['as_of'] = add_seconds(selected['query']['at'], '-1')
                else:
                    values = {row['name']: copy.deepcopy(row['value']) for row in old['fields']}
                    status = 'UNAVAILABLE' if variant == 'UNAVAILABLE' else 'AVAILABLE'
                    if variant == 'CONTRADICTORY' and values:
                        name = next((name for name,value in values.items() if value['type_ref'] == 'BOOLEAN'), next(iter(values)))
                        values[name]['value'] = not values[name]['value'] if values[name]['type_ref'] == 'BOOLEAN' else 'other-source-value'
                    replacement = observation(requirement, authority, values=values, status=status, revision=old['revision'], record_id=old.get('provider_record_id'))
                    selected.clear(); selected.update(replacement)
                authority['observations'].sort(key=lambda row: digest('authority-observation', row))
                refusal = phase5_refusal(authority, [source_check(authority, req_id, reason)])
                emit('evaluate', {'kind':'AUTHORITY','request':authority}, refusal,
                    point + ': ' + req_id + ' ' + variant.lower() + ' fails its exact current source fact. Both complete leaf results remain retained; no model score or other passing record cures the failure.', ['AUTH-007','AUTH-008'], 'source-' + point.lower())
    for label, options, failed_ids in [
        ('same-canonical-human-across-parties', {'alder':{'actor':'canonical-human-42'}, 'cedar':{'actor':'canonical-human-42'}}, ['alder-decision','cedar-decision']),
        ('human-decision-equals-executor', {'cedar':{'actor':'inventory-agent-01'}}, ['cedar-decision'])]:
        authority, _, _ = cdmo_authority(leaf_options=options)
        failed = [{'purpose':'SEPARATION','subject_digest':next(row['evidence']['decision_act_digest'] for row in authority['decision_bases'] if row['requirement_id']==req_id),
            'requirement_ref':req_id,'at':authority['clock']['instant'],'reason':'DECISION_SEPARATION'} for req_id in failed_ids]
        emit('evaluate',{'kind':'AUTHORITY','request':authority},phase5_refusal(authority,failed),
            label + ' violates exact source-selected actor separation. Account aliases must already resolve to canonical host-selected subjects.', ['AUTH-008'], 'separation')
    clipped=cdmo_trace(leaf_options={'cedar':{'capacity_until':'2026-10-06T12:11:20Z'}})
    step(clipped['base'],clipped['base']['dispatch_clock_result']['state'],clipped['authorization_event'],clipped['authorized'],
        'Cedar current capacity reliance ends at 12:11:20 although its signed decision and source interval end later. Clip dispatch authorization to the independently derived leaf effective_until.', ['AUTH-008','LIFE-009B'], 'reliance-cutoff')
    for party in ['alder','cedar']:
        authority = copy.deepcopy(base['authority_input'])
        evidence = next(row['evidence'] for row in authority['decision_bases'] if row['requirement_id'] == party + '-decision')
        leaf = evidence['authority_input']
        subject = digest('authority-envelope',leaf['envelope'])
        selected = next(row for row in leaf['observations'] if row['query']['subject_digest'] == subject and row['query']['at'] == leaf['clock']['instant'])
        selected['revoked'] = True
        leaf['observations'].sort(key=lambda row: digest('authority-observation',row))
        leaf_refusal = authority_refusal([{'purpose':'REVOCATION','subject_digest':subject,'requirement_ref':selected['query_digest'],'at':leaf['clock']['instant'],'reason':'REVOKED'}])
        refusal = phase5_refusal(authority,[{'purpose':'HUMAN_DECISION','subject_digest':evidence['decision_act_digest'],'requirement_ref':party + '-decision','at':authority['clock']['instant'],'reason':'DECISION_NOT_EFFECTIVE'}],leaf_results={party + '-decision':leaf_refusal})
        emit('evaluate',{'kind':'AUTHORITY','request':authority},refusal,
            'Current scoped revocation of the ' + party + ' decision invalidates new reliance despite valid signing-time occupancy. Retain the complete underlying leaf refusal.', ['AUTH-005','AUTH-008'], 'leaf-current-failures')
    for party in ['alder','cedar']:
        for variant in ['missing','unrequested']:
            authority=copy.deepcopy(base['authority_input'])
            evidence=next(row['evidence'] for row in authority['decision_bases'] if row['requirement_id']==party+'-decision')
            leaf=evidence['authority_input']
            code='EVIDENCE_UNAVAILABLE' if variant=='missing' else 'DEPENDENCY_MISMATCH'
            if variant=='missing':
                leaf['observations']=[]
            else:
                extra=copy.deepcopy(leaf['observations'][0]);extra['query']['subject_digest']='sha256:'+'0'*64
                extra['query_digest']=digest('authority-query',extra['query']);leaf['observations'].append(extra)
                leaf['observations'].sort(key=lambda row:digest('authority-observation',row))
            refused=authority_refusal([],code=code)
            expected=authority_refusal([],code=code)
            expected['decision_results']=expected_authority(authority,selected_leaf_results={party+'-decision':refused})['decision_results']
            emit('evaluate',{'kind':'AUTHORITY','request':authority},expected,
                variant + ' ' + party + ' leaf query inventory fails the joined phase5 admission. Retain both complete leaf results, including the unaffected valid decision.', ['AUTH-008'], 'leaf-query-inventory')
    for label,mutator,code in [
        ('missing-basis',lambda value:value['decision_bases'].pop(),'EVIDENCE_UNAVAILABLE'),
        ('unrequested-basis',lambda value:value['decision_bases'][0].update(requirement_id='aaa-unrequested'),'DEPENDENCY_MISMATCH'),
        ('wrong-wrapper-digest',lambda value:value['decision_bases'][0]['evidence'].update(decision_act_digest='sha256:'+'0'*64),'BINDING_MISMATCH'),
        ('wrong-leaf-clock',lambda value:value['decision_bases'][0]['evidence']['authority_input']['clock'].update(instant='2026-10-06T12:09:00Z'),'BINDING_MISMATCH'),
        ('invalid-known-leaf-scalar',lambda value:value['decision_bases'][0]['evidence']['authority_input']['proposal']['fields'][next(i for i,row in enumerate(value['decision_bases'][0]['evidence']['authority_input']['proposal']['fields']) if row['name']=='effective_until')]['value'].update(value='2026-02-30T12:00:00Z'),'TYPE_INVALID')]:
        authority=copy.deepcopy(base['authority_input']); mutator(authority)
        emit('evaluate',{'kind':'AUTHORITY','request':authority},authority_refusal([],code=code),
            label + ' is an admission failure before current-policy judgments. A complete parent cannot hide invalid or missing independent evidence.', ['AUTH-008'], 'admission')
    for label, leaf_bound in [('leaf-canonical-byte-bound',True),('outer-canonical-byte-bound',False)]:
        authority,_,_=cdmo_authority(leaf_options={'alder':{'source_padding':270000}} if leaf_bound else None, source_padding=0 if leaf_bound else 1050000)
        emit('evaluate',{'kind':'AUTHORITY','request':authority},authority_refusal([],code='LIMIT_EXCEEDED'),
            label + ' exceeds the independently specified complete canonical input bound before current-policy evaluation; all exact source/root/act dependencies are independently rebuilt.', ['AUTH-008'], 'byte-bounds')
    authority=copy.deepcopy(base['authority_input']); authority['clock'].update(status='UNAVAILABLE',instant=None)
    for row in authority['decision_bases']:
        row['evidence']['authority_input']['clock'].update(status='UNAVAILABLE',instant=None)
    emit('evaluate',{'kind':'AUTHORITY','request':authority},authority_refusal([],code='AUTHORITY_NOT_ESTABLISHED',reasons=['CLOCK_UNAVAILABLE']),
        'Unavailable outer and leaf clocks establish no current authority after directly checkable admission phases; no local wall clock supplies a substitute.', ['AUTH-008','LIFE-014'], 'clock')
    actual=trace['completion_event']['native_evidence']['actual_fields']
    for field in actual:
        changed=[copy.deepcopy(row) for row in actual if row['name']!=field['name']]
        event,result,_=cdmo_completed(base,trace['completion_ready'],actual_fields=changed,mismatch=True)
        step(base,trace['completion_ready']['state'],event,result,'Missing native field ' + field['name'] + ' cannot establish the closed eighteen-field completion. Retain the attributable event, stop and hold both claims for investigation.', ['LIFE-010','LIFE-015','RES-001A'], 'native-missing')
    for name in ['old_status','new_status','committed_quality_gate_revision','dossier_digest','cedar_approval_identity','customer_assent_identity']:
        changed=copy.deepcopy(actual); next(row for row in changed if row['name']==name)['value']['value']='WRONG_NATIVE_VALUE'
        event,result,_=cdmo_completed(base,trace['completion_ready'],actual_fields=changed,mismatch=True)
        step(base,trace['completion_ready']['state'],event,result,'A well-formed native mismatch in ' + name + ' is retained UNEXPECTED evidence. Current reads, another approval or another authorization cannot repair historical completion.', ['LIFE-010','LIFE-015'], 'native-mismatch')
    for status in ['NOT_FOUND','UNAVAILABLE','AMBIGUOUS','OVERFLOW']:
        event=lookup_event(base,trace['dispatched'],status=status,event_id='cdmo-lookup-'+status.lower())
        result=lookup_result(base,trace['dispatched'],event)
        step(base,trace['dispatched']['state'],event,result,'Authoritative lookup ' + status + ' stops the current instance and retains claims. It grants no blind resend or automatic successor.', ['LIFE-015'], 'lookup')
    for status in ['NOT_FOUND','AMBIGUOUS']:
        event=lookup_event(base,trace['completion_ready'],status=status,event_id='cdmo-late-lookup-'+status.lower())
        stopped=lookup_result(base,trace['completion_ready'],event)
        stopped['permit']=trace['completion_ready']['permit']
        step(base,trace['completion_ready']['state'],event,stopped,'Late-evidence prerequisite: stop after ' + status + ' while retaining held claims and the exact dispatch authorization.', ['LIFE-015'], 'late-evidence')
        late_event,late_result,_=cdmo_late_exact(base,stopped,blocked=status=='AMBIGUOUS')
        step(base,stopped['state'],late_event,late_result,'An independently exact late native event consumes eligible claims without reopening the stopped instance or erasing its first terminal/referral evidence. An existing ambiguous dispute remains blocked.', ['LIFE-012','LIFE-015','RES-001A'], 'late-evidence')
    for business in [False,True]:
        supplied,expected=cdmo_correction(trace,business_change=business)
        emit('check-evidence',supplied,expected,
            'Append a separately Head-of-Quality-authorized ' + ('business correction with new dossier revision/digest and two fresh immutable human issuances.' if business else 'timestamp correction with no new business decision. Original native history and permit remain unchanged.'), ['LIFE-020A','AUTH-008'], 'correction')
    for label, options in [('new-revision-reuses-immutable-issue',{'reuse_issue':True}),
        ('new-decisions-reuse-dossier-revision',{'reuse_dossier_revision':True}),('new-decisions-reuse-dossier-digest',{'reuse_dossier_digest':True})]:
        selected_trace=cdmo_trace(correction_options=options)
        supplied,_=cdmo_correction(selected_trace)
        emit('check-evidence',supplied,correction_refusal('BINDING_MISMATCH'),
            label + ' has coherently reconstructed source declarations and fresh act digests, but fails the independent immutable-identity/fresh-dossier rule against the exact original request and native event.', ['LIFE-020A','AUTH-008'], 'correction-freshness')
    business_input,_=cdmo_correction(trace)
    for label,mutator in [
        ('legacy-policy-marker',lambda value:value['correction'].pop('decision_policy')),
        ('missing-fresh-assent',lambda value:value['correction']['correction_authority_input']['decision_bases'].pop(0)),
        ('changed-historical-commit-revision',lambda value:value['correction']['changes'].append({'field':'committed_quality_gate_revision','old_value':typed('QG-42','REVISION'),'new_value':typed('QG-43','REVISION')})),
        ('wrong-original-digest',lambda value:value['correction'].update(original_record_digest='sha256:'+'0'*64)),
        ('wrong-current-revision',lambda value:value['correction'].update(expected_revision='CV-BTA-026-001-R0')),
        ('result-digest-unbound',lambda value:next(row for row in value['correction']['correction_authority_input']['proposal']['fields'] if row['name']=='corrected_result_digest')['value'].update(value='sha256:'+'0'*64))]:
        supplied=copy.deepcopy(business_input); mutator(supplied); seal_correction(supplied['correction'])
        expected = {'status':'REFUSED','code':'SCHEMA_INVALID','path':''} if label == 'legacy-policy-marker' else correction_refusal('EVIDENCE_UNAVAILABLE' if label == 'missing-fresh-assent' else 'BINDING_MISMATCH')
        emit('check-evidence',supplied,expected,label + ' cannot establish the selected linked correction; no new decision rewrites the original event or creates a new execution opportunity.', ['LIFE-020A','AUTH-008'], 'correction-negative')
    source_package = Path(__file__).resolve().parents[1] / 'specimens/pharmaceutical-batch-disposition/build-specimen.py'
    correspondence,_ = runpy.run_path(str(source_package))['source_mapping'](base,readback(base['definition']))
    supplied={'profile':'LINEAR','role':'REVIEW_EVIDENCE','specification_pin':candidate_pin(),
        'subject':{'kind':'WORK_CLASS','subject_id':base['definition']['id'],'subject_digest':base['definition_digest'],
            'candidate_identity':'seampoint.work-class/1.0.0-draft.3','specification_pin':candidate_pin()},
        'work_class':base['definition'],'work_class_digest':base['definition_digest'],'evidence':correspondence}
    emit('check-evidence',supplied,correction_refusal('EVIDENCE_NOT_ACCEPTED'),
        'The source correspondence records complete readback accounting and explicit host/source residue, but its independent review remains PENDING. Mechanical coverage does not manufacture source acceptance.', ['WCS2-006'], 'source-correspondence')
    return cases,groups,trace


def main():
    cases,groups,trace=construct_cases()
    for row in cases:
        write_canonical_json(GROUP/(row['id']+'.json'),row)
    write_canonical_json(GROUP/'index.json',{'group':'cdmo-source','status':'AUTHOR_DERIVED_NOT_CONSUMER_VERIFIED','candidate_pin':candidate_pin(),'case_ids':[row['id'] for row in cases]})
    print({'cases':len(cases),'groups':{name:len(rows) for name,rows in groups.items()}})

if __name__=='__main__':
    main()
