#!/usr/bin/env python3
"""Additional source-derived G7/multiple-projection cases. No consumer imports."""
import copy,importlib.util,json
from pathlib import Path
from corpus_common import CASES,canonical_bytes,candidate_pin,digest,exact_case,write_canonical_json
import recovery_fixture as rec
from reservation_fixture import effect_record,host_and_event,native,refusal,request,transition

HERE=Path(__file__).resolve().parent

def module(name):
 spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def main():
 close=module('build-phase3-dispose-closeout-cases');alias=module('build-phase3-alias-cases')
 group=CASES / 'phase3-closeout-boundaries';group.mkdir(parents=True,exist_ok=True);ids=[]
 def add(value,out,refs,text):
  cid=f'C3-P3-BOUND-{len(ids)+1:03d}';ids.append(cid)
  write_canonical_json(group/(cid+'.json'),exact_case(cid,'aggregate-step',value,out,refs,text+' Source-derived/probe-informed; no consumer output consulted.'))
 f=rec.facts_for('2')
 for kind,reason in [('stale','HISTORY_STALE'),('unavailable','HISTORY_UNAVAILABLE'),('incomplete','HISTORY_INCOMPLETE'),('conflict','HISTORY_CONFLICT')]:
  for operation in ['RESERVE','RENEW']:
   before=rec.registered(f) if operation=='RESERVE' else rec.reserve(f,rec.registered(f))[1]['state']
   payload={'authority':f['authority_a'],'histories':[close.history_for(f,kind)]}
   if operation=='RENEW':payload['reservation']='reserve-a'
   ev,ho=host_and_event(f,operation,'g7-'+operation.lower()+'-'+kind,before['core']['revision'],payload,administration=False)
   v=request(before,ev,ho)
   out=transition(before,ev,ho,copy.deepcopy(before['core']),'WITHHELD',reservation_id='reserve-a' if operation=='RENEW' else None,authority_result=f['authority_a_result'],reasons=[reason])
   add(v,out,['RES-005','RES-006','RES-WIRE-004'],'G7: '+operation+' with '+kind+' required history. Structural admission succeeds; unusable/stale history withholds, preserves the prior journal and reservation/permit, and supplies no fabricated aggregate result.')
 # Two mappings multiply contingent rows, not possible executions themselves.
 f=alias.shape_facts(rec.facts_for('2'),aliased=False,two_mappings=True)
 before=alias.reserved(f,rec.registered(f))
 n=native(f,'UNKNOWN','two-mapping-unknown',completion_mismatch=True,mismatch_reason='UNEXPECTED_EFFECT')
 ev,ho=host_and_event(f,'SETTLE','retain-two-mapping-unknown',before['core']['revision'],{'native':n,'histories':[f['history']]},administration=False)
 core=copy.deepcopy(before['core']);core['reservations'][0]['status']='DISPUTED'
 core['effects'].append(effect_record(n,'DISPUTED','UNEXPECTED_EFFECT',[{'anchor':'license-spend','key':None}]))
 state=transition(before,ev,ho,core,'EFFECT_DISPUTED',reservation_id='reserve-a',reasons=['UNEXPECTED_EFFECT'])['state']
 for executions in (2049,2050):
  for complete in (True,False):
   e=rec.evidence_for(f,state,attempts=1);e['attempts'][0]['maximum_executions']=str(executions);e['complete_attempt_inventory']=complete
   v=rec.dispose_request(f,state,'LEAVE_UNRESOLVED',evidence=e)
   out=refusal(state,'LIMIT_EXCEEDED') if executions==2050 else close.expected(v,[] if complete else ['RECOVERY_EVIDENCE_INCOMPLETE'])
   add(v,out,['REC-008','REC-016'],f'R-m with two mappings: ({executions}-1)*2 rows. 4096 admitted; 4098 refuses without mutation, independently of completeness. Incomplete inventory cannot install new rows.')
 print(json.dumps({'candidate_pin':candidate_pin(),'cases':len(ids),'ids':ids},indent=2))

if __name__=='__main__':main()
