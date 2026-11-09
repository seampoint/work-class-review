#!/usr/bin/env python3
"""Derive gated dispatch cases from the exact candidate contract before consumers."""
from __future__ import annotations

import copy

from authority_fixture import authority_refusal
from corpus_common import CASES, exact_case, write_canonical_json, digest
from equipment_observation_fixture import authority_mutator, observation, source_refusal
from equipment_dispatch_fixture import authorization_event, authorization_result, clock_transition, retained
from lifecycle_factory import base_lifecycle, permitted_proposal, step_input, stateful_refusal, dispatch_event, dispatch_result, replay_result

GROUP = CASES / 'equipment-dispatch'


def main():
    base = base_lifecycle(authority_mutator=authority_mutator)
    permitted = permitted_proposal(base)
    event = authorization_event(base, permitted)
    authorized = authorization_result(base, permitted, event)
    current = retained(authorized, permitted['permit'])
    auth_id = authorized['state']['authorizations'][0]['authorization_digest']
    cases = []
    def emit(number, input_value, expected, derivation, operation='step'):
        cases.append(exact_case('C3-ED-' + str(number).zfill(3), operation, input_value, expected, ['AUTH-007','LIFE-009A'], derivation))
    emit(1,base['deploy_input'],base['deploy_result'],'A declared gate installs empty authorization and evaluation inventories without a native call.','deploy')
    emit(2,step_input(base,base['clock_result']['state'],base['proposal_event']),permitted,'The proposal retains the complete immutable authority basis in the permit.')
    emit(3,step_input(base,permitted['state'],event),authorized,'Fresh DISPATCH authority derives four exact fence rows, a 60-second exclusive expiry, full authorization evaluation and receipt bindings.')
    emit(4,step_input(base,current['state'],event),replay_result(current['state'],event['event_id']),'Exact replay returns the retained original outcome without new authorization or connector invocation.')
    for number, mutate, code, derivation in [
        (5,lambda row: row.pop('authority_input'),'EVIDENCE_UNAVAILABLE','A declared gate has no refreshed input; it cannot use the proposal receipt.'),
        (6,lambda row: row.pop('dispatch_intent_id'),'INPUT_INVALID','A declared gate requires a unique intent identity.'),
        (7,lambda row: row['authority_input'].update(evaluation_point='PROPOSE'),'INPUT_INVALID','A current dispatch evaluation must explicitly select DISPATCH.'),
        (8,lambda row: row['authority_input']['proposal']['executor'].update(actor='another-actor'),'BINDING_MISMATCH','Refresh cannot substitute an executor or other immutable basis member.'),
        (9,lambda row: row.update(authorization_fence=None),'BINDING_MISMATCH','Readiness requires the exact complete derived fence; null only permits withholding.'),
        (10,lambda row: row['authorization_fence']['sources'][2].update(provider_revision='forged-revision'),'BINDING_MISMATCH','Every independent source revision is compared, including policy withdrawal.'),
        (11,lambda row: row['authorization_fence']['sources'].pop(),'BINDING_MISMATCH','A fence cannot omit one declared independent source.'),
        (12,lambda row: row['authorization_fence'].update(scope_digest=digest('invented-scope',{})),'BINDING_MISMATCH','The scope commits the exact intent, request, connector, expiry, fresh result and source vector.'),
    ]:
        changed=copy.deepcopy(event);mutate(changed)
        emit(number,step_input(base,permitted['state'],changed),stateful_refusal(permitted['state'],code),derivation)
    failed = copy.deepcopy(event)
    req = next(row for row in failed['authority_input']['envelope']['source_observation_requirements'] if row['id']=='approval-withdrawal')
    failed['authority_input']['observations'] = [row for row in failed['authority_input']['observations'] if row['query'].get('requirement_id') != req['id']]
    failed['authority_input']['observations'].append(observation(req,failed['authority_input'],status='AVAILABLE',record_id='withdrawal-1'))
    failed['observation_digests'] = sorted({digest('authority-observation',row) for row in failed['authority_input']['observations']})
    failed['authorization_fence']=None
    refusal=source_refusal(failed['authority_input'],req['id'],'SOURCE_OBSERVATION_BINDING')
    withheld=authorization_result(base,permitted,failed,refusal=refusal)
    emit(13,step_input(base,permitted['state'],failed),withheld,'A complete withdrawal record contradicts required absence. Withholding retains the full refresh/refusal/evaluation and consumes its intent, with no authorization.')
    forged_withdraw=copy.deepcopy(failed);forged_withdraw['authorization_fence']=copy.deepcopy(event['authorization_fence'])
    emit(14,step_input(base,permitted['state'],forged_withdraw),authorization_result(base,permitted,forged_withdraw,refusal=refusal),'Current withdrawal withholds before comparing an obsolete EFFECTIVE fence assertion.')
    retry=authorization_event(base,current,event_id='authorize-reuse',intent='intent-1')
    emit(15,step_input(base,current['state'],retry),stateful_refusal(current['state'],'BINDING_MISMATCH'),'A second admitted event cannot reuse a successful intent.')
    withheld_current=retained(withheld,permitted['permit'])
    retry=authorization_event(base,withheld_current,event_id='authorize-after-withheld',intent='intent-1')
    emit(16,step_input(base,withheld_current['state'],retry),stateful_refusal(withheld_current['state'],'BINDING_MISMATCH'),'Withheld evaluations also consume their unique intent identity.')
    replacement=authorization_event(base,current,event_id='authorize-replacement',intent='intent-2')
    replacement_result=authorization_result(base,current,replacement)
    emit(17,step_input(base,current['state'],replacement),replacement_result,'A fresh unique authorization supersedes an unattempted head, retains history, and binds its exact predecessor.')
    latest=retained(replacement_result,permitted['permit'])
    sent=dispatch_event(base,latest,event_id='send-old-head',authorization_digest=auth_id)
    emit(18,step_input(base,latest['state'],sent),dispatch_result(latest,sent,disposition='DISPUTED',reasons=['LATE_OR_PROHIBITED_DISPATCH'],occurrence_status='BLOCKED_DISPUTE'),'A possibly sent attempt claiming a superseded authorization is retained as disputed; no usable permission is reconstructed.')
    sent=dispatch_event(base,current,event_id='send-gated',authorization_digest=auth_id)
    sent_result=dispatch_result(current,sent,disposition='DISPATCH_RECORDED',reasons=[],occurrence_status='DISPATCHED')
    emit(19,step_input(base,current['state'],sent),sent_result,'A timely exact current authorization binds the recorded SENT attempt and consumes permission.')
    sent_current=retained(sent_result,permitted['permit'])
    resend=authorization_event(base,sent_current,event_id='authorize-after-sent',intent='intent-3')
    emit(20,step_input(base,sent_current['state'],resend),stateful_refusal(sent_current['state'],'PREREQUISITE_MISSING'),'SENT evidence prevents another authorization even under fresh authority and a new intent.')
    no_send=dispatch_event(base,current,event_id='not-sent-gated',attempt_status='NOT_SENT',authorization_digest=auth_id)
    not_sent_result=dispatch_result(current,no_send,disposition='DISPATCH_REFUSED',reasons=['NATIVE_NOT_SENT'],occurrence_status='PERMITTED')
    emit(21,step_input(base,current['state'],no_send),not_sent_result,'Safe NOT_SENT retains the attempt but does not establish an effect or release a key.')
    retry_current=retained(not_sent_result,permitted['permit'])
    newevent=authorization_event(base,retry_current,event_id='authorize-after-not-sent',intent='intent-2')
    emit(22,step_input(base,retry_current['state'],newevent),authorization_result(base,retry_current,newevent),'Safe NOT_SENT permits only a fresh unique intent and a new current authorization.')
    clock_event, expired=clock_transition(current,instant='2026-09-10T04:31:00Z')
    late=dispatch_event(base,expired,event_id='send-at-exclusive-end',authorization_digest=auth_id,attempted_at='2026-09-10T04:31:00Z',clock_revision='2')
    emit(23,step_input(base,expired['state'],late),dispatch_result(expired,late,disposition='DISPUTED',reasons=['LATE_OR_PROHIBITED_DISPATCH'],occurrence_status='BLOCKED_DISPUTE'),'An attempt at the authorization exclusive expiry has no permission, although its permit expires later.')
    _, expired_permit=clock_transition(permitted,instant='2026-09-10T04:35:00Z')
    ended=authorization_event(base,expired_permit,event_id='authorize-expired-permit',intent='intent-2')
    emit(24,step_input(base,expired_permit['state'],ended),stateful_refusal(expired_permit['state'],'PREREQUISITE_MISSING'),'A fresh gate authorization cannot extend an expired permit.')
    _, unavailable=clock_transition(permitted,status='UNAVAILABLE')
    fresh=copy.deepcopy(permitted['permit']['authority_basis']);fresh['evaluation_point']='DISPATCH';fresh['clock']={'source':'authority-clock','status':'UNAVAILABLE','instant':None};fresh['observations']=[]
    unknown=authorization_event(base,unavailable,event_id='authorize-unavailable-clock',intent='intent-2',authority_input=fresh)
    clock_refusal=authority_refusal([],reasons=['CLOCK_UNAVAILABLE'])
    emit(25,step_input(base,unavailable['state'],unknown),authorization_result(base,unavailable,unknown,refusal=clock_refusal),'The latest unavailable clock withholds before unresolved current queries. It never falls back to the old available revision.')
    oldclock=copy.deepcopy(event);oldclock['expected_state_revision']=unavailable['state']['revision'];oldclock['expected_state_digest']=unavailable['state_digest']
    emit(26,step_input(base,unavailable['state'],oldclock),stateful_refusal(unavailable['state'],'CLOCK_INVALID'),'An old available clock revision cannot replace the latest unavailable evidence.')
    wrongpoint=copy.deepcopy(base['proposal_event']);wrongpoint['authority_input']['evaluation_point']='DISPATCH'
    emit(27,step_input(base,base['clock_result']['state'],wrongpoint),stateful_refusal(base['clock_result']['state'],'INPUT_INVALID'),'PROPOSE cannot select a dispatch-only authority evaluation.')
    _, later_clock = clock_transition(current, instant='2026-09-10T04:30:01Z')
    later_authorize = authorization_event(base,later_clock,event_id='authorize-later-head',intent='intent-2')
    later_result = retained(authorization_result(base,later_clock,later_authorize),permitted['permit'])
    timely_old = dispatch_event(base,later_result,event_id='old-timely-attempt-received-later',authorization_digest=auth_id,attempted_at='2026-09-10T04:30:00Z',clock_revision='2')
    emit(28,step_input(base,later_result['state'],timely_old),dispatch_result(later_result,timely_old,disposition='DISPATCH_RECORDED',reasons=[],occurrence_status='DISPATCHED'),'A retained older authorization was the head for an attempt strictly before its successor checked_at. Receiving the observation later does not make that past attempt prohibited.')
    later_failed = authorization_event(base,later_clock,event_id='authorize-later-withdrawn',intent='intent-2')
    later_req = next(row for row in later_failed['authority_input']['envelope']['source_observation_requirements'] if row['id']=='approval-withdrawal')
    later_failed['authority_input']['observations'] = [row for row in later_failed['authority_input']['observations'] if row['query'].get('requirement_id') != later_req['id']]
    later_failed['authority_input']['observations'].append(observation(later_req,later_failed['authority_input'],status='AVAILABLE',record_id='withdrawal-2'))
    later_failed['observation_digests'] = sorted({digest('authority-observation',row) for row in later_failed['authority_input']['observations']})
    later_failed['authorization_fence']=None
    later_refusal=source_refusal(later_failed['authority_input'],later_req['id'],'SOURCE_OBSERVATION_BINDING')
    later_withheld=retained(authorization_result(base,later_clock,later_failed,refusal=later_refusal),permitted['permit'])
    for number,status,at,disposition,reasons,occurrence_status in [
        (29,'SENT','2026-09-10T04:30:01Z','DISPUTED',['LATE_OR_PROHIBITED_DISPATCH'],'BLOCKED_DISPUTE'),
        (30,'NOT_SENT','2026-09-10T04:30:01Z','DISPATCH_REFUSED',['LATE_OR_PROHIBITED_DISPATCH','NATIVE_NOT_SENT'],'PERMITTED'),
        (31,'SENT','2026-09-10T04:30:00Z','DISPATCH_RECORDED',[],'DISPATCHED'),
    ]:
        attempt=dispatch_event(base,later_withheld,event_id='withheld-head-attempt-'+str(number),attempt_status=status,authorization_digest=auth_id,attempted_at=at,clock_revision='2')
        emit(number,step_input(base,later_withheld['state'],attempt),dispatch_result(later_withheld,attempt,disposition=disposition,reasons=reasons,occurrence_status=occurrence_status),'A later withheld refresh retains the old successful head as history but blocks new sends at or after its selected clock instant. A strictly earlier timely past attempt remains attributable under the earlier permission.')
    _, unavailable_after_authorization = clock_transition(current,status='UNAVAILABLE')
    unavailable_refresh = authorization_event(base,unavailable_after_authorization,event_id='authorize-unavailable-after-head',intent='intent-2',authority_input=fresh)
    unavailable_withheld = retained(authorization_result(base,unavailable_after_authorization,unavailable_refresh,refusal=clock_refusal),permitted['permit'])
    past_attempt = dispatch_event(base,unavailable_withheld,event_id='past-attempt-before-unavailable-clock',authorization_digest=auth_id,attempted_at='2026-09-10T04:30:00Z',clock_revision='1')
    emit(32,step_input(base,unavailable_withheld['state'],past_attempt),dispatch_result(unavailable_withheld,past_attempt,disposition='DISPATCH_RECORDED',reasons=[],occurrence_status='DISPATCHED'),'Later unavailable clock evidence blocks a new host send but does not disprove an earlier timely attempt bound to the retained accepted AVAILABLE clock revision.')
    for case in cases:
        write_canonical_json(GROUP/(case['id']+'.json'),case)
    print({'group':str(GROUP),'cases':len(cases),'derivation':'normative-only; consumers not consulted'})

if __name__ == '__main__':
    main()
