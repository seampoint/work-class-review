#!/usr/bin/env python3
"""R-o mixed usable/unusable required history controls, constructed without consumers."""
import copy,json
from corpus_common import CASES,canonical_bytes,candidate_pin,digest,exact_case,write_canonical_json
from authority_fixture import authority_specimen
from reservation_fixture import fixture,zero_state,host_and_event,request,transition


def main():
 f=fixture();f['authority_a'],f['authority_a_result']=authority_specimen(shared_budgets=['anchor-a','anchor-b']);f['authority_a']['clock']=copy.deepcopy(f['clock'])
 f['configuration']['slots']=[{'anchor':name,'exposure_domain':'exposure-'+name} for name in ['anchor-a','anchor-b']]
 definitions=[];authorizations=[];histories=[]
 for anchor in ['anchor-a','anchor-b']:
  b=copy.deepcopy(f['budget']);b['anchor']=anchor;b['exposure_domain']='exposure-'+anchor;bd=digest('budget-definition',b)
  auth=copy.deepcopy(f['authorizations'][0]);auth['budget_digest']=bd;auth['envelope_digest']=digest('authority-envelope',f['authority_a']['envelope']);auth['work_class_digest']=digest('authority-work-class',f['authority_a']['work_class']);auth['authority_definition'].update({key:copy.deepcopy(f['authority_a'][key]) for key in ['source','work_class','envelope']})
  h=copy.deepcopy(f['history']);h['budget_digest']=bd
  definitions.append(b);authorizations.append(auth);histories.append(h)
 state=zero_state(f)
 for b,auth,h in zip(definitions,authorizations,histories):
  ev,ho=host_and_event(f,'REGISTER','register-'+b['anchor'],state['core']['revision'],{'definition':b,'authorizations':[auth],'history':h})
  core=copy.deepcopy(state['core']);core['budgets'].append({'definition':b,'definition_digest':digest('budget-definition',b),'authorizations':[auth],'history':h});core['budgets'].sort(key=lambda row:row['definition']['anchor'])
  state=transition(state,ev,ho,core,'REGISTERED')['state']
 current=copy.deepcopy(histories[0]);current['revision']='2';current['journal'].append({'sequence':'2','event':{'id':'unrelated-current-history','state':'ACTIVE','occurred_at':f['clock']['instant'],'fields':[{'name':'amount','value':{'type_ref':'amount','value':'10'}},{'name':'beneficiary','value':{'type_ref':'beneficiary','value':'employee-9'}}]}})
 group=CASES / 'phase3-mixed-history';group.mkdir(parents=True,exist_ok=True);ids=[]
 for status,reason in [('UNAVAILABLE','HISTORY_UNAVAILABLE'),('INCOMPLETE','HISTORY_INCOMPLETE'),('CONFLICT','HISTORY_CONFLICT'),('STALE','HISTORY_STALE')]:
  bad=copy.deepcopy(histories[1])
  if status=='STALE':bad['as_of']='2026-09-10T04:20:00Z'
  else:bad.update(status=status,complete=False,as_of=None,revision=None,journal=None)
  hs=sorted([copy.deepcopy(current),bad],key=lambda row:row['budget_digest'])
  ev,ho=host_and_event(f,'RESERVE','mixed-history-'+status.lower(),state['core']['revision'],{'authority':f['authority_a'],'histories':hs},administration=False)
  core=copy.deepcopy(state['core']);core['budgets'][0]['history']=copy.deepcopy(current)
  out=transition(state,ev,ho,core,'WITHHELD',budgets=[],authority_result=f['authority_a_result'],reasons=[reason])
  cid=f'C3-P3-MIXED-{len(ids)+1:03d}';ids.append(cid)
  write_canonical_json(group/(cid+'.json'),exact_case(cid,'aggregate-step',request(state,ev,ho),out,['RES-003','RES-004','RES-005','RES-WIRE-004'],'Approved R-o: one fresh complete numerical history and one '+status+' history. Both required anchors bind the same class, envelope and native provider pairs. The unusable required history gates ALL aggregate evaluation, so budgets is empty. The fresh complete journal still commits; the unusable journal does not replace its prior state. No reservation is created. Source-derived before consumer execution.'))
 print(json.dumps({'candidate_pin':candidate_pin(),'cases':len(ids)},indent=2))

if __name__=='__main__':main()
