#!/usr/bin/env python3
"""Source-derived, probe-informed complete cases for D1-D6 and owner rulings R-j..R-n.

No consumer implementation or output is imported. Expected state is assembled from
REC-002/008/010/016 and the ordinary receipt/digest constructors. Reason sets are
specified per scenario rather than learned from execution. All expected files must
be hash-sealed before either consumer runs them.
"""
from __future__ import annotations
import copy
import json
from decimal import Decimal
from corpus_common import CASES, canonical_bytes, candidate_pin, digest, exact_case, write_canonical_json
import recovery_fixture as rec
from reservation_fixture import budget_result, effect_record, host_and_event, native, refusal, request, transition

GROUP = CASES / 'phase3-dispose-closeout'


def history_for(facts, kind, effect=None):
    h=copy.deepcopy(facts['history'])
    if kind == 'corroborating': return rec.established_history(facts,effect)
    if kind == 'stale': h['as_of']='2026-09-10T04:20:00Z'
    elif kind in ('unavailable','incomplete','conflict'):
        h.update(status=kind.upper(),as_of=None,complete=False,revision=None,journal=None)
    return h


def rows_for(supplied, record):
    p=supplied['event']['payload']; e=p['evidence']; before=supplied['state']
    reservation=next(r for r in before['core']['reservations'] if r['id']==p['target']['reservation'])
    # The originating reservation accounts for exactly one unresolved slot.
    slots=[(a,i) for a in e['attempts'] if not a['no_effect'] for i in range(len(a['effect_ids'])+1,int(a['maximum_executions'])+1)]
    rows=[]
    for a,i in slots[1:]:
        for c in reservation['contributions']:
            identity={'registry_digest':p['target']['registry_digest'],'reservation':reservation['id'],'attempt_id':a['id'],'execution_index':str(i),**{k:copy.deepcopy(c[k]) for k in ('anchor','mapping','key')}}
            rows.append({'id':digest('recovery-contingent',identity),'disposition_digest':record['id'],'reservation':reservation['id'],'attempt_id':a['id'],'execution_index':str(i),**copy.deepcopy(c)})
    return sorted(rows,key=canonical_bytes)


def expected(supplied, reasons=(), *, usable=True):
    p=supplied['event']['payload']; e=p['evidence']; reasons=sorted(set(reasons))
    before=supplied['state']; core=copy.deepcopy(before['core'])
    record=rec.disposition_record(supplied,result='LEAVE_UNRESOLVED' if reasons else None)
    core['recovery']['dispositions'].append(record);core['recovery']['dispositions'].sort(key=canonical_bytes)
    if e['complete_attempt_inventory']:
        rid=p['target']['reservation']
        core['recovery']['contingent']=[r for r in core['recovery']['contingent'] if r['reservation']!=rid]+rows_for(supplied,record)
        core['recovery']['contingent'].sort(key=canonical_bytes)
    if usable:
        for h in p['histories']:
            next(b for b in core['budgets'] if b['definition_digest']==h['budget_digest'])['history']=copy.deepcopy(h)
    budgets=[]
    if p['requested_result']=='ACCEPT_UNRESOLVED' and 'HISTORY_UNCORROBORATED' not in reasons:
        # Use the independently written REC-010 arithmetic/allowance constructor.
        base=rec.disposition_expected(supplied,reasons=reasons,effective_result='LEAVE_UNRESOLVED' if reasons else None)
        budgets=base['receipt']['budgets'];core['recovery']['allowances']=copy.deepcopy(base['state']['core']['recovery']['allowances'])
    result=transition(before,supplied['event'],supplied['host_evidence'],core,'WITHHELD' if reasons else 'DISPOSITION_RECORDED',reservation_id=p['target']['reservation'],reasons=reasons,budgets=budgets)
    result['receipt']['recovery_disposition_digest']=record['id']
    result['receipt_digest']=digest('reservation-receipt',result['receipt'])
    result['state']['receipts'][-1]['receipt']=copy.deepcopy(result['receipt'])
    result['state_digest']=digest('reservation-state',result['state'])
    return result


def main():
    GROUP.mkdir(parents=True,exist_ok=True)
    produced=[]
    def add(label,value,result,refs,rule):
        case_id=f'C3-P3-CLOSE-{len(produced)+1:03d}'
        write_canonical_json(GROUP/f'{case_id}.json',exact_case(case_id,'aggregate-step',value,result,refs,label+'. '+rule+' Expectations are source-derived and probe-informed; no consumer runs in this builder.'))
        produced.append(case_id)
    f=rec.facts_for('2');s=rec.disputed(f)
    rj='Approved R-j: wrong conclusion adds RECOVERY_EVIDENCE_INCOMPLETE independently of packet exclusion adding RECOVERY_CONFLICT_UNRESOLVED. REC-006 requires a corroborated attributable effect. REC-008 preserves bounded unresolved charges.'
    for has_effect in (False,True):
        for conclusion in ('EFFECT_ESTABLISHED','NO_EFFECT_ESTABLISHED','UNRESOLVED'):
            for excluded in (False,True):
                for hist in ('base','corroborating') if has_effect else ('base',):
                    e=rec.evidence_for(f,s,conclusion='EFFECT_ESTABLISHED' if has_effect else 'UNRESOLVED',attempts=1)
                    e.update(conclusion=conclusion,rules_out_past_and_future_effects=excluded)
                    h=history_for(f,hist,e['native_outcomes'][0] if has_effect else None)
                    v=rec.dispose_request(f,s,'ESTABLISH_EFFECT',evidence=e,histories=[h])
                    reasons=[]
                    if conclusion!='EFFECT_ESTABLISHED' or not has_effect:reasons.append('RECOVERY_EVIDENCE_INCOMPLETE')
                    if excluded:reasons.append('RECOVERY_CONFLICT_UNRESOLVED')
                    if has_effect and hist=='base':reasons+=['RECOVERY_EVIDENCE_INCOMPLETE','HISTORY_UNCORROBORATED']
                    out=expected(v,reasons)
                    add(f'R-j conclusion={conclusion}, excluded={excluded}, effect={has_effect}, history={hist}',v,out,['REC-006','REC-008','REC-016'],rj)
                    if has_effect and hist=='corroborating' and conclusion=='UNRESOLVED' and not excluded:
                        ev,ho=host_and_event(f,'RESERVE','reserve-b-after-incomplete',out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[h]},administration=False)
                        after=copy.deepcopy(out['state']['core'])
                        add('D2 follow-through: incomplete effect must not clear next RESERVE',request(out['state'],ev,ho),transition(out['state'],ev,ho,after,'WITHHELD',budgets=budget_result(f,'952'),authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED']),['REC-006','REC-008','REC-011','RES-WIRE-004'],'The failed conclusion retains an operational dispute. R-p independently substitutes the corroborated actual for the original 2 USD pending: 802 committed plus 150 proposed is 952.')
    for kind,reason in [('unavailable','HISTORY_UNAVAILABLE'),('incomplete','HISTORY_INCOMPLETE'),('conflict','HISTORY_CONFLICT'),('stale','HISTORY_STALE')]:
        for desired in ('ESTABLISH_EFFECT','ESTABLISH_NO_EFFECT','LEAVE_UNRESOLVED'):
            e=rec.evidence_for(f,s,conclusion={'ESTABLISH_EFFECT':'EFFECT_ESTABLISHED','ESTABLISH_NO_EFFECT':'NO_EFFECT_ESTABLISHED'}.get(desired,'UNRESOLVED'),attempts=1)
            v=rec.dispose_request(f,s,desired,evidence=e,histories=[history_for(f,kind)])
            reasons=[] if desired=='LEAVE_UNRESOLVED' else ['RECOVERY_EVIDENCE_INCOMPLETE',reason]
            add(f'D6/R-l unusable {kind} history for {desired}',v,expected(v,reasons,usable=False),['REC-006','REC-007','REC-016'],'R-l adds incomplete evidence with the single applicable history reason; R-i exempts explicit LEAVE. No fabricated history adoption or aggregate result.')
    # R-k: semantic attribution gaps are substantive; omitted known facts are admission errors.
    for requested in ('LEAVE_UNRESOLVED','ACCEPT_UNRESOLVED'):
        prior=rec.disputed(f,result_kind='EFFECT')
        issued=rec.policy_issue(f,prior);prior=issued[1]['state'];pd=issued[0]['event']['payload']['policy_digest']
        e=rec.evidence_for(f,prior,conclusion='UNRESOLVED',attempts=2);e['superseded_evidence_digests']=[]
        v=rec.dispose_request(f,prior,requested,evidence=e,policy_digest=pd if requested=='ACCEPT_UNRESOLVED' else None)
        reasons=['RECOVERY_CONFLICT_UNRESOLVED','RECOVERY_EVIDENCE_INCOMPLETE','HISTORY_UNCORROBORATED']+(['RECOVERY_EXCEPTION_INELIGIBLE'] if requested=='ACCEPT_UNRESOLVED' else [])
        add('R-k retained conclusive effect without supersession, '+requested,v,expected(v,reasons),['REC-004','REC-008','REC-016'],'A retained effect absent from selected native effects remains an unresolved contradiction; no allowance or clearance, complete inventory remains charged.')
        e=rec.evidence_for(f,s,conclusion='EFFECT_ESTABLISHED',attempts=1);e['attempts'][0]['effect_ids']=[];e['conclusion']='UNRESOLVED'
        v=rec.dispose_request(f,s,requested,evidence=e)
        reasons=['RECOVERY_EVIDENCE_INCOMPLETE','HISTORY_UNCORROBORATED']+(['RECOVERY_EXCEPTION_INELIGIBLE','RECOVERY_POLICY_INVALID'] if requested=='ACCEPT_UNRESOLVED' else [])
        add('R-k new native effect lacks attempt attribution, '+requested,v,expected(v,reasons),['REC-004','REC-008','REC-016'],'Approved R-k: uncovered supplied effect adds incomplete evidence; ACCEPT is also ineligible and has no policy.')
    # D3/D5: retained changed-request facts do not erase bounded possible executions.
    _, reserved=rec.reserve(f,rec.registered(f));before=reserved['state']
    changed=native(f,'UNKNOWN','native-changed-request',completion_mismatch=True,mismatch_reason='NATIVE_REQUEST_MISMATCH')
    next(row for row in changed['request']['fields'] if row['name']=='amount')['value']['value']='3'
    ev,ho=host_and_event(f,'SETTLE','retain-changed-request',before['core']['revision'],{'native':changed,'histories':[f['history']]},administration=False)
    core=copy.deepcopy(before['core']);core['reservations'][0]['status']='DISPUTED'
    core['effects'].append(effect_record(changed,'DISPUTED','NATIVE_REQUEST_MISMATCH',[{'anchor':'license-spend','key':None}]))
    changed_state=transition(before,ev,ho,core,'EFFECT_DISPUTED',reservation_id='reserve-a',reasons=['NATIVE_REQUEST_MISMATCH'])['state']
    _,issued=rec.policy_issue(f,changed_state);changed_state=issued['state'];pd=changed_state['core']['recovery']['policies'][0]['policy_digest']
    for desired in ('LEAVE_UNRESOLVED','ACCEPT_UNRESOLVED'):
        for attempts in (3,6):
            e=rec.evidence_for(f,changed_state,attempts=attempts)
            v=rec.dispose_request(f,changed_state,desired,evidence=e,policy_digest=pd if desired=='ACCEPT_UNRESOLVED' else None)
            reasons=[] if desired=='LEAVE_UNRESOLVED' else ['RECOVERY_EXCEPTION_INELIGIBLE','RECOVERY_INCIDENT_LIMIT_EXCEEDED']+(['RECOVERY_ALLOWANCE_EXCEEDED'] if attempts==6 else [])
            out=expected(v,reasons)
            add(f'D3/D5 changed request retained: {desired}, {attempts} executions',v,out,['REC-008','REC-009','REC-010','REC-016'],'The prior changed request makes acceptance ineligible but does not erase original-source contingent rows or skip incident/allowance/budget evaluation. Explicit LEAVE grants no exception. Rows are rebuilt from the complete inventory.')
            if desired=='LEAVE_UNRESOLVED' and attempts==3:
                ev,ho=host_and_event(f,'RESERVE','reserve-b-after-changed-request',out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[f['history']]},administration=False)
                add('D3 next RESERVE includes both contingent rows',request(out['state'],ev,ho),transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',budgets=budget_result(f,'956'),authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED']),['REC-008','REC-011','RES-WIRE-004'],'800 committed plus 2 original plus two 2 USD contingent rows plus 150 is 956. Changed-request evidence remains blocking.')
    # Resource preflight: count rows arithmetically, never enumerate huge rejected counts.
    for count in (4095,4096,4097,4999,10**20-1):
        for complete in (True,False):
            e=rec.evidence_for(f,s,attempts=1);e['attempts'][0]['maximum_executions']=str(count+1);e['complete_attempt_inventory']=complete
            v=rec.dispose_request(f,s,'LEAVE_UNRESOLVED',evidence=e)
            out=refusal(s,'LIMIT_EXCEEDED') if count>4096 else expected(v,[] if complete else ['RECOVERY_EVIDENCE_INCOMPLETE'])
            add(f'R-m projected rows={count}, complete={complete}',v,out,['REC-008','REC-016'],'The ordinary reservation represents the first unresolved execution. Above 4096 rows refuses unchanged, including incomplete inventory; exactly 4096 is admitted, but incomplete inventory cannot replace retained charges.')
    # Genuine acceptance and its incident/cumulative limits, with complete monetary SUM data.
    _,issued=rec.policy_issue(f,s);state=issued['state'];pd=state['core']['recovery']['policies'][0]['policy_digest']
    for attempts in (2,3,6):
        e=rec.evidence_for(f,state,attempts=attempts)
        v=rec.dispose_request(f,state,'ACCEPT_UNRESOLVED',evidence=e,policy_digest=pd)
        reasons=[] if attempts==2 else ['RECOVERY_INCIDENT_LIMIT_EXCEEDED']+(['RECOVERY_ALLOWANCE_EXCEEDED'] if attempts==6 else [])
        add(f'ACCEPT monetary finite inventory: {attempts} executions',v,expected(v,reasons),['REC-008','REC-009','REC-010','REC-016'],'Whole case exposure is 2 USD times execution count; incident cap 5, cumulative cap 10, ordinary sum 800 plus exposure. Failed acceptance still evaluates and retains all bounded charges, without allowance consumption.')
    for pending in (1023,1024,1025):
        e=rec.evidence_for(f,state,attempts=1);e['attempts'][0]['maximum_executions']=str(pending+1)
        v=rec.dispose_request(f,state,'ACCEPT_UNRESOLVED',evidence=e,policy_digest=pd)
        out=refusal(state,'LIMIT_EXCEEDED') if pending>1024 else expected(v,['BOUND_VIOLATED','RECOVERY_INCIDENT_LIMIT_EXCEEDED','RECOVERY_ALLOWANCE_EXCEEDED'])
        add(f'R-n exact derived aggregate pending={pending}',v,out,['REC-008','REC-010','REC-016'],'REC-010 excludes the ordinary originating reservation and includes the new operation once; pending count equals execution count minus one. AGG collection bound is independent of recovery rows. Totals above 1000 violate ordinary budget; full incident and allowance checks still apply.')
    print(json.dumps({'candidate_pin':candidate_pin(),'cases':len(produced),'ids':produced},indent=2))

if __name__=='__main__':main()
