#!/usr/bin/env python3
"""Source-derived cases for independent build-6 findings; no consumer imports/output."""
import copy,importlib.util,json
from pathlib import Path
from corpus_common import CASES,canonical_bytes,candidate_pin,digest,exact_case,write_canonical_json
import recovery_fixture as rec
from reservation_fixture import native,transition,host_and_event,request,reservation_record,budget_result,refusal
from authority_fixture import authority_specimen

HERE=Path(__file__).resolve().parent

def main():
 spec=importlib.util.spec_from_file_location('close',HERE/'build-phase3-dispose-closeout-cases.py');close=importlib.util.module_from_spec(spec);spec.loader.exec_module(close)
 group=CASES / 'phase3-review-findings';group.mkdir(parents=True,exist_ok=True);ids=[]
 def add(v,out,refs,text):
  cid=f'C3-P3-REVIEW-{len(ids)+1:03d}';ids.append(cid);write_canonical_json(group/(cid+'.json'),exact_case(cid,'aggregate-step',v,out,refs,text+' Source-derived, probe-informed; no actual result is an oracle.'))
 f=rec.facts_for('2');f['budget']['reservation_policy']['no_effect']=copy.deepcopy(f['budget']['reservation_policy']['settlement'])
 bd=digest('budget-definition',f['budget']);f['history']['budget_digest']=bd
 for a in f['authorizations']:a['budget_digest']=bd
 s=rec.disputed(f)
 # Legitimate shared provider pair makes the contradiction independent of binding faults.
 for supersede in (False,True):
  e=rec.evidence_for(f,s,conclusion='EFFECT_ESTABLISHED',attempts=1)
  no=native(f,'NO_EFFECT','native-contradictory-no-effect',reservation_id='reserve-a',request_record=rec.native_request(s))
  no.update(provider=e['provider'],source=e['source']);e['native_outcomes'].append(no)
  fd=digest('recovery-fact',rec.normalize_native(no));e['covered_evidence_digests']=sorted(set(e['covered_evidence_digests']+[fd]))
  if supersede:e['superseded_evidence_digests']=sorted(set(e['superseded_evidence_digests']+[fd]))
  h=rec.established_history(f,e['native_outcomes'][0]);v=rec.dispose_request(f,s,'ESTABLISH_EFFECT',evidence=e,histories=[h])
  add(v,close.expected(v,[] if supersede else ['RECOVERY_CONFLICT_UNRESOLVED']),['REC-004','REC-006','REC-016'],'REC-006 requires resolution of every covered conclusive contradiction, including inside the newly supplied packet. Settlement and no-effect providers are explicitly identical. An authenticated supersession resolves exactly the contrary no-effect fact; without it no positive effect clearance is possible.')
 _,issued=rec.policy_issue(f,s);state=issued['state'];pd=state['core']['recovery']['policies'][0]['policy_digest']
 for executions in (3,6):
  e=rec.evidence_for(f,state,conclusion='EFFECT_ESTABLISHED',attempts=1);e['conclusion']='UNRESOLVED';e['attempts'][0]['maximum_executions']=str(executions)
  h=rec.established_history(f,e['native_outcomes'][0]);v=rec.dispose_request(f,state,'ACCEPT_UNRESOLVED',evidence=e,policy_digest=pd,histories=[h])
  reasons=['RECOVERY_EXCEPTION_INELIGIBLE','RECOVERY_INCIDENT_LIMIT_EXCEEDED']+(['RECOVERY_ALLOWANCE_EXCEEDED'] if executions==6 else [])
  add(v,close.expected(v,reasons),['REC-006','REC-008','REC-009','REC-010','REC-016'],f'Whole case exposure includes one established 2 USD execution plus {executions-1} possible executions. Full incident amount {2*executions} USD must not lose the established slot. ACCEPT is ineligible, but incident/cumulative and ordinary-budget checks still run independently. No allowance is consumed.')
 # Affirmatively closed slots contribute neither possible charge nor cap amount.
 e=rec.evidence_for(f,state,attempts=2);e['attempts'][0].update(maximum_executions='100000000000000000000',no_effect=True);e['attempts'][1]['maximum_executions']='2'
 no=native(f,'NO_EFFECT','native-final-closed-attempt',reservation_id='reserve-a',request_record=rec.native_request(state));no.update(provider=e['provider'],source=e['source']);e['native_outcomes']=[no]
 e['covered_evidence_digests']=sorted(set(e['covered_evidence_digests']+[digest('recovery-fact',rec.normalize_native(no))]))
 v=rec.dispose_request(f,state,'ACCEPT_UNRESOLVED',evidence=e,policy_digest=pd)
 add(v,close.expected(v,['RECOVERY_EXCEPTION_INELIGIBLE']),['REC-006','REC-008','REC-009','REC-010'],'Affirmatively excluded executions supply no contingent rows and are not possible charge. Two remaining executions measure 4 USD, within both caps; the no-effect evidence makes ACCEPT ineligible but does not justify charging closed executions or enumerating their huge declared maximum.')
 # REC-010 derives/evaluates aggregate requests only with usable histories.
 e=rec.evidence_for(f,state,attempts=1);e['attempts'][0]['maximum_executions']='1026';h=close.history_for(f,'unavailable')
 v=rec.dispose_request(f,state,'ACCEPT_UNRESOLVED',evidence=e,policy_digest=pd,histories=[h])
 reasons=['HISTORY_UNAVAILABLE','RECOVERY_EXCEPTION_INELIGIBLE','RECOVERY_INCIDENT_LIMIT_EXCEEDED','RECOVERY_ALLOWANCE_EXCEEDED']
 record=rec.disposition_record(v,result='LEAVE_UNRESOLVED');core=copy.deepcopy(state['core']);core['recovery']['dispositions'].append(record);core['recovery']['dispositions'].sort(key=canonical_bytes);core['recovery']['contingent']=close.rows_for(v,record)
 out=transition(state,v['event'],v['host_evidence'],core,'WITHHELD',reservation_id='reserve-a',budgets=[],reasons=reasons)
 out['receipt']['recovery_disposition_digest']=record['id'];out['receipt_digest']=digest('reservation-receipt',out['receipt']);out['state']['receipts'][-1]['receipt']=copy.deepcopy(out['receipt']);out['state_digest']=digest('reservation-state',out['state'])
 add(v,out,['REC-008','REC-009','REC-010','REC-016'],'With an unusable history REC-010 supplies no aggregate request/evaluation, so its derived-request 1024 bound is not triggered. The separate 4096 recovery-row preflight admits 1025 rows. Full known exposure is retained and incident/allowance failures still accumulate with the history and eligibility reasons.')
 # Other-key pending rows still count toward the aggregate request's collection bound.
 def other_authority(value, original):
  next(row for row in value['proposal']['fields'] if row['name']=='amount')['value']['value']='2'
  next(row for row in value['proposal']['fields'] if row['name']=='beneficiary')['value']['value']='employee-9'
 other=copy.deepcopy(f);other['authority_a'],other['authority_a_result']=authority_specimen(shared_budget=True,instance_id='instance-other',occurrence_id='issue:other',mutator=other_authority)
 other['authority_a']['clock']=copy.deepcopy(f['clock'])
 # AUTH-CHECKS: actual_scope projects the changed proposal's declared coordinates.
 proposal=other['authority_a']['proposal'];step=next(row for row in other['authority_a']['work_class']['steps'] if row['id']==proposal['step'])
 fields={row['name']:row['value']['value'] for row in proposal['fields']}
 other['authority_a_result']['actual_scope']={kind:sorted({fields[name] for name in step['scope_fields'][kind]}) for kind in ('subjects','resources')}
 envelope=other['authority_a']['envelope'];bindings={row['id']:fields[row['field']] for row in envelope['bindings']}
 other['authority_a_result']['scope']={kind:sorted({selector['value'] if selector['kind']=='CONSTANT' else bindings[selector['binding']] for selector in envelope['scope'][kind]}) for kind in ('subjects','resources')}


 for other_count in (1022,1023,4096):
  initial=rec.registered(f)
  ev,ho=host_and_event(other,'RESERVE','reserve-other',initial['core']['revision'],{'authority':other['authority_a'],'histories':[f['history']]},administration=False)
  core=copy.deepcopy(initial['core']);row=reservation_record(other,'authority_a','reserve-other');row['contributions'][0]['value']['value']='2';row['contributions'][0]['key']=[{'type_ref':'beneficiary','value':fields['beneficiary']}];core['reservations']=[row]
  evaluated=budget_result(f,'2');evaluated[0]['result']['partitions'][0]['key']=[{'type_ref':'beneficiary','value':'employee-9'}]
  first=transition(initial,ev,ho,core,'RESERVED',reservation_id='reserve-other',budgets=evaluated,authority_result=other['authority_a_result'])['state']
  evidence=rec.evidence_for(other,first,attempts=1);evidence['attempts'][0]['maximum_executions']=str(other_count+1)
  # Reserve the target before expanding the other incident, so setup never
  # exceeds an ordinary aggregate request bound. Select the other target explicitly.
  _,reserved=rec.reserve(f,first);both=reserved['state']
  payload={'target':copy.deepcopy(evidence['target']),'requested_result':'LEAVE_UNRESOLVED','evidence':evidence,'histories':[f['history']],'policy_digest':None,'controller':None,'supersedes':None}
  ev,ho=rec.recovery_event(other,both,'DISPOSE','leave-other-mixed-key',payload)
  leave=request(both,ev,ho);target_state=close.expected(leave)['state']
  _,issued=rec.policy_issue(f,target_state);target_state=issued['state'];pd=target_state['core']['recovery']['policies'][0]['policy_digest']
  e=rec.evidence_for(f,target_state,attempts=2);v=rec.dispose_request(f,target_state,'ACCEPT_UNRESOLVED',event_id='accept-target-mixed-key',evidence=e,policy_digest=pd)
  if other_count>=1023:out=refusal(target_state,'LIMIT_EXCEEDED')
  else:
   out=close.expected(v);out['receipt']['budgets']=budget_result(f,'804')
   out['receipt_digest']=digest('reservation-receipt',out['receipt']);out['state']['receipts'][-1]['receipt']=copy.deepcopy(out['receipt']);out['state_digest']=digest('reservation-state',out['state'])
  add(v,out,['REC-008','REC-010','REC-016'],f'Other reservation has {other_count} contingent rows on employee-9. The other ordinary reservation adds one pending row and target employee-7 adds one contingent row, for {other_count+2} derived pending rows. All anchor rows count before AGG partitions by key: 1024 fits, 1025 refuses. With 4096 other rows, the recovery preflight also refuses the proposed 4097-row replacement without mutation. Other-key charges never inflate the employee-7 arithmetic: 800 committed plus 4 target exposure is 804.')
 print(json.dumps({'candidate_pin':candidate_pin(),'cases':len(ids)},indent=2))

if __name__=='__main__':main()
