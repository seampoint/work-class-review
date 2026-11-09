#!/usr/bin/env python3
"""Exact owner-approved R-p examples, derived without consumers or their outputs."""
import copy,json
from corpus_common import CASES,canonical_bytes,candidate_pin,digest,exact_case,write_canonical_json
import recovery_fixture as rec
from authority_fixture import authority_specimen
from reservation_fixture import transition,request,host_and_event,budget_result,native,effect_record,reservation_record,zero_state


def history(f,e,kind):
 h=copy.deepcopy(f['history'])
 if kind=='repaired':
  n=e['native_outcomes'][0];h=rec.established_history(f,n)
  fields={row['name']:row['value'] for row in n['observed_request']['fields']}
  for row in h['journal'][1:]:
   for field in row['event'].get('fields',[]):
    if field['name'] in fields:field['value']['value']=copy.deepcopy(fields[field['name']]['value'])
 elif kind=='stale':h['as_of']='2026-09-10T04:20:00Z'
 elif kind in ['unavailable','incomplete','conflict']:h.update(status=kind.upper(),complete=False,as_of=None,revision=None,journal=None)
 return h


def outcome(v,reasons,usable=True,budgets=None):
 before=v['state'];p=v['event']['payload'];e=p['evidence'];core=copy.deepcopy(before['core'])
 record=rec.disposition_record(v,result='LEAVE_UNRESOLVED' if reasons or p['requested_result']=='LEAVE_UNRESOLVED' else None)
 core['recovery']['dispositions'].append(record);core['recovery']['dispositions'].sort(key=canonical_bytes)
 target=next(row for row in core['reservations'] if row['id']==p['target']['reservation'])
 if e['complete_attempt_inventory']:
  actual={row['effect_id'] for row in e['native_outcomes'] if row['outcome']=='EFFECT' and digest('recovery-fact',rec.normalize_native(row)) not in e['superseded_evidence_digests']}
  slots=[(a,i) for a in e['attempts'] if not a['no_effect'] for i in range(1+len(actual.intersection(a['effect_ids'])),int(a['maximum_executions'])+1)]
  rows=[]
  for a,i in slots[1 if target['status'] in ['OPEN','UNKNOWN','DISPUTED'] else 0:]:
   for c in target['contributions']:
    ident={'registry_digest':p['target']['registry_digest'],'reservation':target['id'],'attempt_id':a['id'],'execution_index':str(i),**{k:copy.deepcopy(c[k]) for k in ['anchor','mapping','key']}}
    rows.append({'id':digest('recovery-contingent',ident),'disposition_digest':record['id'],'reservation':target['id'],'attempt_id':a['id'],'execution_index':str(i),**copy.deepcopy(c)})
  core['recovery']['contingent']=[x for x in core['recovery']['contingent'] if x['reservation']!=target['id']]+rows;core['recovery']['contingent'].sort(key=canonical_bytes)
 if usable:
  for h in p['histories']:next(b for b in core['budgets'] if b['definition_digest']==h['budget_digest'])['history']=copy.deepcopy(h)
 result=transition(before,v['event'],v['host_evidence'],core,'WITHHELD' if reasons else 'DISPOSITION_RECORDED',reservation_id=target['id'],reasons=reasons,budgets=budgets or [])
 result['receipt']['recovery_disposition_digest']=record['id'];result['receipt_digest']=digest('reservation-receipt',result['receipt']);result['state']['receipts'][-1]['receipt']=copy.deepcopy(result['receipt']);result['state_digest']=digest('reservation-state',result['state'])
 return result


def main():
 group=CASES / 'phase3-unassessed-actual';group.mkdir(parents=True,exist_ok=True);ids=[]
 def add(value,expected,text):
  cid=f'C3-P3-UACT-{len(ids)+1:03d}';ids.append(cid);write_canonical_json(group/(cid+'.json'),exact_case(cid,'aggregate-step',value,expected,['REC-006','REC-008','REC-010','REC-016','RES-005'],text+' Exact R-p source derivation, sealed before consumers; no consumer output is an oracle.'))
 f=rec.facts_for('2');state=rec.disputed(f)
 for change in ['unchanged','amount','key','unprojectable']:
  for kind in ['missing','repaired','unavailable','stale']:
   if change=='unprojectable' and kind=='repaired':continue
   for desired in ['LEAVE_UNRESOLVED','ESTABLISH_EFFECT']:
    e=rec.evidence_for(f,state,conclusion='EFFECT_ESTABLISHED',attempts=1);e['attempts'][0]['maximum_executions']='3'
    n=e['native_outcomes'][0]
    if change in ['amount','key']:
     next(x for x in n['observed_request']['fields'] if x['name']==('amount' if change=='amount' else 'beneficiary'))['value']['value']='3' if change=='amount' else 'employee-9'
     n.update(completion_mismatch=True,mismatch_reason='NATIVE_REQUEST_MISMATCH')
    if change=='unprojectable':n.update(observed_request=None,completion_mismatch=True,mismatch_reason='UNEXPECTED_EFFECT')
    e['covered_evidence_digests']=sorted({digest('recovery-fact',rec.normalize_native(row)) for row in [*[x['native'] for x in state['core']['effects']],*e['native_outcomes']]})
    h=history(f,e,kind);v=rec.dispose_request(f,state,desired,event_id='uact-'+str(len(ids)+1),evidence=e,histories=[h])
    reasons=[] if kind=='repaired' else ['RECOVERY_EVIDENCE_INCOMPLETE']
    if kind=='missing' and change!='unprojectable':reasons+=['HISTORY_UNCORROBORATED']
    if kind in ['unavailable','stale'] and desired!='LEAVE_UNRESOLVED':reasons+=[{'unavailable':'HISTORY_UNAVAILABLE','stale':'HISTORY_STALE'}[kind]]
    out=outcome(v,reasons,kind in ['missing','repaired']);add(v,out,f'R-p {desired}, native={change}, history={kind}; two remaining possible executions, one contingent row, no allowance.')
    if desired=='LEAVE_UNRESOLVED' and kind in ['missing','repaired']:
     for next_kind in ['RESERVE','RENEW']:
      payload={'authority':f['authority_b' if next_kind=='RESERVE' else 'authority_a'],'histories':[h]}
      if next_kind=='RENEW':payload['reservation']='reserve-a'
      ev,ho=host_and_event(f,next_kind,'uact-next-'+str(len(ids)+1),out['state']['core']['revision'],payload,administration=False)
      rs=['EXPOSURE_DISPUTED'];bs=[]
      if reasons:rs+=reasons
      elif next_kind=='RESERVE':bs=budget_result(f,{'unchanged':'956','amount':'957','key':'954'}[change])
      expected=transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',reservation_id='reserve-a' if next_kind=='RENEW' else None,authority_result=f['authority_a_result' if next_kind=='RENEW' else 'authority_b_result'],reasons=rs,budgets=bs)
      add(request(out['state'],ev,ho),expected,'R-p subsequent '+next_kind+': whole budgets empty while unassessed; repaired journal permits assessment, operational dispute remains.')
    replay=copy.deepcopy(out);replay['replay']=True;add(request(out['state'],v['event'],v['host_evidence']),replay,'Exact replay of R-p disposition retains complete receipt and current state.')
 # Complete versus incomplete/all-no-effect cannot manufacture original release.
 for complete in [True,False]:
  e=rec.evidence_for(f,state,conclusion='EFFECT_ESTABLISHED',attempts=1);e['complete_attempt_inventory']=complete;h=history(f,e,'repaired')
  v=rec.dispose_request(f,state,'LEAVE_UNRESOLVED',event_id='uact-all-actual-'+str(complete),evidence=e,histories=[h]);out=outcome(v,[] if complete else ['RECOVERY_EVIDENCE_INCOMPLETE']);add(v,out,'All actual: only current complete covering inventory may substitute exact corroborated actual for original pending.')
  ev,ho=host_and_event(f,'RESERVE','uact-next-all-'+str(complete),out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[h]},administration=False)
  add(request(out['state'],ev,ho),transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED'],budgets=budget_result(f,'952' if complete else '954')),'R-p complete all-actual removes own pending once; incomplete inventory retains it. Neither clears dispute.')
 e=rec.evidence_for(f,state,conclusion='NO_EFFECT_ESTABLISHED',attempts=1);v=rec.dispose_request(f,state,'LEAVE_UNRESOLVED',event_id='uact-noeffect-leave',evidence=e);out=outcome(v,[]);add(v,out,'All-no-effect LEAVE grants no REC-007 release authority.')
 ev,ho=host_and_event(f,'RESERVE','uact-after-noeffect-leave',out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[f['history']]},administration=False)
 add(request(out['state'],ev,ho),transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED'],budgets=budget_result(f,'952')),'All-no-effect LEAVE retains original pending 2 and block.')
 # OPEN target: original pending exists. SETTLED target: every remaining possible slot needs its own row.
 _,reserved=rec.reserve(f,rec.registered(f));opened=reserved['state']
 n=native(f,'EFFECT','native-matched');h=rec.established_history(f,n);ev,ho=host_and_event(f,'SETTLE','uact-normal-settle',opened['core']['revision'],{'native':n,'histories':[h]},administration=False)
 core=copy.deepcopy(opened['core']);core['budgets'][0]['history']=copy.deepcopy(h);core['reservations'][0].update(status='SETTLED',matched_effect=n['effect_id']);core['effects'].append(effect_record(n,'MATCHED','MATCHED_EFFECT'))
 settled=transition(opened,ev,ho,core,'SETTLED',reservation_id='reserve-a')['state']
 for prior,label in [(opened,'OPEN'),(settled,'SETTLED')]:
  e=rec.evidence_for(f,prior,conclusion='EFFECT_ESTABLISHED',attempts=1);e['attempts'][0]['maximum_executions']='3';e['superseded_evidence_digests']=[] if label=='SETTLED' else e['superseded_evidence_digests'];hh=history(f,e,'repaired');v=rec.dispose_request(f,prior,'LEAVE_UNRESOLVED',event_id='uact-target-'+label,evidence=e,histories=[hh]);add(v,outcome(v,[]),'R-p '+label+' target; original supplies first remaining execution only if currently pending. No implicit lifecycle status change.')
 # Failed ACCEPT cannot claim assessed amounts while a known actual is absent.
 for prior,amount,kind in [(state,'3','missing'),(state,'3','repaired'),(state,'1','repaired'),(settled,'2','repaired')]:
  _,issued=rec.policy_issue(f,prior);current=issued['state'];pd=current['core']['recovery']['policies'][0]['policy_digest']
  e=rec.evidence_for(f,current,conclusion='EFFECT_ESTABLISHED',attempts=1)
  e['attempts'][0]['maximum_executions']='3'
  n=e['native_outcomes'][0]
  if amount!='2':
   next(x for x in n['observed_request']['fields'] if x['name']=='amount')['value']['value']=amount
   n.update(completion_mismatch=True,mismatch_reason='NATIVE_REQUEST_MISMATCH')
  e['covered_evidence_digests']=sorted({digest('recovery-fact',rec.normalize_native(row)) for row in [*[x['native'] for x in current['core']['effects']],n]})
  if prior is settled:e['superseded_evidence_digests']=[]
  h=history(f,e,kind)
  v=rec.dispose_request(f,current,'ACCEPT_UNRESOLVED',event_id='uact-accept-'+str(len(ids)+1),evidence=e,histories=[h],policy_digest=pd)
  reasons=['RECOVERY_EXCEPTION_INELIGIBLE']
  if kind=='missing':reasons+=['RECOVERY_EVIDENCE_INCOMPLETE','HISTORY_UNCORROBORATED']
  elif int(amount)+4>5:reasons+=['RECOVERY_INCIDENT_LIMIT_EXCEEDED']
  bs=[] if kind=='missing' else budget_result(f,str(800+int(amount)+4))
  add(v,outcome(v,reasons,budgets=bs),'Failed ACCEPT: two remaining executions at 2 USD each, exact actual only when corroborated; cap 5, no allowance. Terminal original charge is absent.')
 # Two incompatible assertions of the same effect remain unresolved until the
 # provider supersedes the rejected assertion. The journal already matches one.
 e=rec.evidence_for(f,state,conclusion='EFFECT_ESTABLISHED',attempts=1)
 chosen=e['native_outcomes'][0]; h=history(f,e,'repaired')
 other=copy.deepcopy(chosen);other['id']='native-conflicting'
 next(x for x in other['observed_request']['fields'] if x['name']=='amount')['value']['value']='3'
 other.update(completion_mismatch=True,mismatch_reason='NATIVE_REQUEST_MISMATCH')
 other_digest=digest('recovery-fact',rec.normalize_native(other))
 e['native_outcomes'].append(other);e['native_outcomes'].sort(key=canonical_bytes)
 e['covered_evidence_digests']=sorted({*e['covered_evidence_digests'],other_digest})
 v=rec.dispose_request(f,state,'LEAVE_UNRESOLVED',event_id='uact-conflicting-assertions',evidence=e,histories=[h])
 out=outcome(v,['RECOVERY_CONFLICT_UNRESOLVED','RECOVERY_EVIDENCE_INCOMPLETE'])
 add(v,out,'One corroborated journal entry does not settle two incompatible actual assertions for the same effect.')
 successor=copy.deepcopy(e);successor['id']='provider-adjudication-2';successor['provider_revision']='3'
 successor['record_digest']=digest('provider-recovery-record',{'target':e['target'],'conclusion':'resolved-conflict'})
 successor['native_outcomes']=[chosen];successor['superseded_evidence_digests']=sorted({*e['superseded_evidence_digests'],other_digest})
 v=rec.dispose_request(f,out['state'],'LEAVE_UNRESOLVED',event_id='uact-superseded-assertion',evidence=successor,histories=[h],supersedes=out['receipt']['recovery_disposition_digest'])
 add(v,outcome(v,[]),'Authoritative supersession removes the conflicting native assertion from assessment, retaining history and LEAVE block.')
 ev,ho=host_and_event(f,'RESERVE','uact-after-conflicting',out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[h]},administration=False)
 add(request(out['state'],ev,ho),transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',
     authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED','RECOVERY_CONFLICT_UNRESOLVED','RECOVERY_EVIDENCE_INCOMPLETE'],budgets=[]),
     'A subsequent ordinary reservation keeps independent exposure and actual conflict reasons without an aggregate.')
 e=rec.evidence_for(f,state,conclusion='EFFECT_ESTABLISHED',attempts=1)
 e['attempts'][0].update(maximum_executions='2',effect_ids=['effect-1','ghost-effect'])
 h=history(f,e,'repaired')
 v=rec.dispose_request(f,state,'LEAVE_UNRESOLVED',event_id='uact-unproved-inventory',evidence=e,histories=[h])
 out=outcome(v,['RECOVERY_EVIDENCE_INCOMPLETE'])
 add(v,out,'A complete flag cannot establish a listed effect without its native fact; that does not authorize omission of the original pending charge.')
 ev,ho=host_and_event(f,'RESERVE','uact-after-unproved-inventory',out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[h]},administration=False)
 add(request(out['state'],ev,ho),transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',
     authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED'],budgets=budget_result(f,'954')),
     'The one corroborated actual supplies 2 committed USD; the unsupported slot cannot remove the separate original 2 USD pending.')
 e['attempts'][0].update(maximum_executions='4',effect_ids=['effect-1','ghost-a','ghost-b'])
 v=rec.dispose_request(f,state,'LEAVE_UNRESOLVED',event_id='uact-multiple-unproved-inventory',evidence=e,histories=[h])
 out=outcome(v,['RECOVERY_EVIDENCE_INCOMPLETE'])
 add(v,out,'Four possible slots minus the one attributable native effect leaves three possible executions; the original supplies one, and two contingent rows remain.')
 ev,ho=host_and_event(f,'RESERVE','uact-after-multiple-unproved-inventory',out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[h]},administration=False)
 add(request(out['state'],ev,ho),transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',
     authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED'],budgets=budget_result(f,'958')),
     'One corroborated actual and three possible executions each contribute 2 USD, alongside opening 800 and proposed 150.')
 same_packet=copy.deepcopy(successor);same_packet['native_outcomes']=sorted([chosen,other],key=canonical_bytes)
 h=history(f,{'native_outcomes':[chosen]},'repaired')
 v=rec.dispose_request(f,state,'LEAVE_UNRESOLVED',event_id='uact-same-packet-supersession',evidence=same_packet,histories=[h])
 out=outcome(v,[])
 add(v,out,'Authoritative exclusion applies to a superseded actual even when the packet retains its original bytes alongside the selected fact.')
 ev,ho=host_and_event(f,'RESERVE','uact-after-same-packet-supersession',out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[h]},administration=False)
 add(request(out['state'],ev,ho),transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',
     authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED'],budgets=budget_result(f,'952')),
     'One selected corroborated actual replaces the original pending charge; superseded alternate assertion does not restore it.')
 # Two required, independently authenticated numerical histories. A usable
 # journal missing a single exact actual entry suppresses both judgments.
 g=rec.facts_for('2');anchors=['anchor-a','anchor-b']
 g['configuration']['slots']=[{'anchor':name,'exposure_domain':'exposure-'+name} for name in anchors]
 def small(value,_):
  next(row for row in value['proposal']['fields'] if row['name']=='amount')['value']['value']='2'
 for key,instance,occurrence,mutator in [('authority_a','instance-1','issue:1',small),('authority_b','instance-2','issue:2',None)]:
  g[key],g[key+'_result']=authority_specimen(shared_budgets=anchors,instance_id=instance,occurrence_id=occurrence,mutator=mutator)
  g[key]['clock']=copy.deepcopy(g['clock'])
 multi=zero_state(g);multi['core']['recovery']=rec.empty_recovery();families=[]
 for anchor in anchors:
  b=copy.deepcopy(g['budget']);b.update(anchor=anchor,exposure_domain='exposure-'+anchor);bd=digest('budget-definition',b)
  auth=copy.deepcopy(g['authorizations'][0]);auth.update(budget_digest=bd,envelope_digest=digest('authority-envelope',g['authority_a']['envelope']),work_class_digest=digest('authority-work-class',g['authority_a']['work_class']))
  auth['authority_definition'].update({key:copy.deepcopy(g['authority_a'][key]) for key in ('source','work_class','envelope')})
  hh=copy.deepcopy(g['history']);hh['budget_digest']=bd;families.append({**g,'budget':b,'history':hh})
  ev,ho=host_and_event(g,'REGISTER','register-'+anchor,multi['core']['revision'],{'definition':b,'authorizations':[auth],'history':hh})
  core=copy.deepcopy(multi['core']);core['budgets'].append({'definition':b,'definition_digest':bd,'authorizations':[auth],'history':hh})
  multi=transition(multi,ev,ho,core,'REGISTERED')['state']
 hh=sorted([x['history'] for x in families],key=lambda row:row['budget_digest'])
 ev,ho=host_and_event(g,'RESERVE','reserve-a',multi['core']['revision'],{'authority':g['authority_a'],'histories':hh},administration=False)
 core=copy.deepcopy(multi['core']);row=reservation_record(g,'authority_a','reserve-a')
 row['contributions']=[{**copy.deepcopy(row['contributions'][0]),'anchor':name,'value':{'type_ref':'amount','value':'2'}} for name in anchors]
 core['reservations'].append(row)
 multi=transition(multi,ev,ho,core,'RESERVED',reservation_id='reserve-a',authority_result=g['authority_a_result'],budgets=[b for x in families for b in budget_result(x,'802')])['state']
 n=native(g,'UNKNOWN','multi-unknown',completion_mismatch=True,mismatch_reason='UNEXPECTED_EFFECT')
 ev,ho=host_and_event(g,'SETTLE','multi-dispute',multi['core']['revision'],{'native':n,'histories':hh},administration=False)
 core=copy.deepcopy(multi['core']);core['reservations'][0]['status']='DISPUTED'
 core['effects'].append(effect_record(n,'DISPUTED','UNEXPECTED_EFFECT',[{'anchor':name,'key':None} for name in anchors],affected_anchors=anchors))
 multi=transition(multi,ev,ho,core,'EFFECT_DISPUTED',reservation_id='reserve-a',reasons=['UNEXPECTED_EFFECT'])['state']
 e=rec.evidence_for(g,multi,conclusion='EFFECT_ESTABLISHED',attempts=1);e['attempts'][0]['maximum_executions']='3'
 first=history(families[0],e,'repaired'); second=history(families[1],e,'repaired')
 mixed=sorted([first,families[1]['history']],key=lambda row:row['budget_digest'])
 v=rec.dispose_request(g,multi,'LEAVE_UNRESOLVED',event_id='uact-mixed-actual',evidence=e,histories=mixed)
 reasons=['HISTORY_UNCORROBORATED','RECOVERY_EVIDENCE_INCOMPLETE'];out=outcome(v,reasons)
 add(v,out,'Two usable journals: the first exactly corroborates the actual; the second is missing the prescribed record. Both journals commit and the entire receipt is unassessed.')
 for repaired in [False,True]:
  hs=sorted([first,second],key=lambda row:row['budget_digest']) if repaired else mixed
  ev,ho=host_and_event(g,'RESERVE','uact-mixed-next-'+str(repaired),out['state']['core']['revision'],{'authority':g['authority_b'],'histories':hs},administration=False)
  core=copy.deepcopy(out['state']['core']);core['budgets'][1]['history']=copy.deepcopy(second if repaired else families[1]['history'])
  add(request(out['state'],ev,ho),transition(out['state'],ev,ho,core,'WITHHELD',authority_result=g['authority_b_result'],
      reasons=['EXPOSURE_DISPUTED']+([] if repaired else reasons),budgets=[b for x in families for b in budget_result(x,'956')] if repaired else []),
      'A second corroboration restores both ordinary judgments without clearing the separate dispute; one missing record suppresses both.')
 # A newer attributable fact invalidates the old complete covering inventory.
 e=rec.evidence_for(f,state,conclusion='EFFECT_ESTABLISHED',attempts=1);h=history(f,e,'repaired')
 old=rec.dispose_request(f,state,'LEAVE_UNRESOLVED',event_id='uact-all-actual-True',evidence=e,histories=[h])
 covering=outcome(old,[])['state']
 n=native(f,'UNKNOWN','post-disposition-unknown',completion_mismatch=True,mismatch_reason='NATIVE_REQUEST_MISMATCH')
 next(row for row in n['request']['fields'] if row['name']=='amount')['value']['value']='3'
 ev,ho=host_and_event(f,'SETTLE','uact-new-fact',covering['core']['revision'],{'native':n,'histories':[h]},administration=False)
 core=copy.deepcopy(covering['core']);core['effects'].append(effect_record(n,'DISPUTED','NATIVE_REQUEST_MISMATCH',[{'anchor':'license-spend','key':None}]))
 core['effects'].sort(key=lambda row:row['id'].encode())
 out=transition(covering,ev,ho,core,'EFFECT_DISPUTED',reservation_id='reserve-a',reasons=['NATIVE_REQUEST_MISMATCH'])
 add(request(covering,ev,ho),out,'A distinct newly retained native fact is outside the earlier complete disposition coverage; both retained facts and journal remain visible.')
 ev,ho=host_and_event(f,'RESERVE','uact-after-new-fact',out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[h]},administration=False)
 add(request(out['state'],ev,ho),transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',
     authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED'],budgets=budget_result(f,'954')),
     'Noncurrent inventory cannot omit the original pending contribution: 802 committed + 2 original + 150 proposed.')
 v=rec.dispose_request(f,state,'ESTABLISH_EFFECT',event_id='uact-establish-supersession',evidence=same_packet,histories=[h])
 out=outcome(v,[])
 add(v,out,'The authorized establishment selects only the exact journal-correlated actual; a superseded conflicting body remains in custody.')
 ev,ho=host_and_event(f,'RESERVE','uact-after-establish-supersession',out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[h]},administration=False)
 core=copy.deepcopy(out['state']['core']);core['reservations'].append(reservation_record(f,'authority_b',ev['id']));core['reservations'].sort(key=lambda row:row['id'].encode())
 add(request(out['state'],ev,ho),transition(out['state'],ev,ho,core,'RESERVED',reservation_id=ev['id'],
     authority_result=f['authority_b_result'],budgets=budget_result(f,'952')),
     'Continuing coverage and authorized establishment of the selected matching actual clear the independent dispute; 802 committed + 150 proposed.')
 # Unknown origin cannot supply an exact retained class and envelope. Its
 # actual blocks the affected anchor, while a merely UNKNOWN outcome does
 # not create an unassessed actual and leaves the ordinary bound check intact.
 for kind in ['EFFECT','UNKNOWN']:
  h=settled['core']['budgets'][0]['history']
  n=native(f,kind,'uact-foreign-'+kind,reservation_id='reserve-ghost',effect_id='effect-foreign' if kind=='EFFECT' else None)
  ev,ho=host_and_event(f,'SETTLE','uact-retain-foreign-'+kind,settled['core']['revision'],{'native':n,'histories':[h]},administration=False)
  core=copy.deepcopy(settled['core']);core['effects'].append(effect_record(n,'DISPUTED','UNKNOWN_RESERVATION',[{'anchor':'license-spend','key':None}]))
  core['effects'].sort(key=lambda row:row['id'].encode())
  out=transition(settled,ev,ho,core,'EFFECT_DISPUTED',reservation_id='reserve-ghost',reasons=['UNKNOWN_RESERVATION'])
  add(request(settled,ev,ho),out,'Foreign outcome lacks exact retained authorization; keep the original anchor-wide block and native evidence.')
  ev,ho=host_and_event(f,'RESERVE','uact-after-foreign-'+kind,out['state']['core']['revision'],{'authority':f['authority_b'],'histories':[h]},administration=False)
  add(request(out['state'],ev,ho),transition(out['state'],ev,ho,copy.deepcopy(out['state']['core']),'WITHHELD',
      authority_result=f['authority_b_result'],reasons=['EXPOSURE_DISPUTED','RECOVERY_EVIDENCE_INCOMPLETE'] if kind=='EFFECT' else ['EXPOSURE_DISPUTED'],
      budgets=[] if kind=='EFFECT' else budget_result(f,'952')),
      'An unattributed actual makes the anchor unassessed. An UNKNOWN outcome independently blocks permission but supplies no known actual and leaves the ordinary aggregate assessable.')
 # Reusing the string of a foreign record's reservation on a distinct
 # anchor cannot retroactively bind its earlier exact class/envelope.
 g=rec.facts_for('2');g['configuration']['slots']=[{'anchor':name,'exposure_domain':'exposure-'+name} for name in anchors]
 foreign=zero_state(g);foreign['core']['recovery']=rec.empty_recovery();single=[]
 for key,anchor,instance,occurrence in [('authority_a','anchor-a','instance-1','issue:1'),('authority_b','anchor-b','instance-2','issue:2')]:
  g[key],g[key+'_result']=authority_specimen(shared_budgets=[anchor],instance_id=instance,occurrence_id=occurrence)
  g[key]['clock']=copy.deepcopy(g['clock'])
  b=copy.deepcopy(g['budget']);b.update(anchor=anchor,exposure_domain='exposure-'+anchor);bd=digest('budget-definition',b)
  auth=copy.deepcopy(g['authorizations'][0]);auth.update(budget_digest=bd,envelope_digest=digest('authority-envelope',g[key]['envelope']),work_class_digest=digest('authority-work-class',g[key]['work_class']))
  auth['authority_definition'].update({name:copy.deepcopy(g[key][name]) for name in ('source','work_class','envelope')})
  hh=copy.deepcopy(g['history']);hh['budget_digest']=bd;single.append({**g,'budget':b,'history':hh})
  ev,ho=host_and_event(g,'REGISTER','register-'+anchor,foreign['core']['revision'],{'definition':b,'authorizations':[auth],'history':hh})
  core=copy.deepcopy(foreign['core']);core['budgets'].append({'definition':b,'definition_digest':bd,'authorizations':[auth],'history':hh})
  foreign=transition(foreign,ev,ho,core,'REGISTERED')['state']
 h=single[0]['history'];n=native(g,'EFFECT','uact-foreign-id',reservation_id='reserve-ghost')
 ev,ho=host_and_event(g,'SETTLE','uact-foreign-before-id',foreign['core']['revision'],{'native':n,'histories':[h]},administration=False)
 core=copy.deepcopy(foreign['core']);core['effects'].append(effect_record(n,'DISPUTED','UNKNOWN_RESERVATION',[{'anchor':'anchor-a','key':None}],affected_anchors=['anchor-a']))
 out=transition(foreign,ev,ho,core,'EFFECT_DISPUTED',reservation_id='reserve-ghost',reasons=['UNKNOWN_RESERVATION'])
 add(request(foreign,ev,ho),out,'Foreign exact attribution is unavailable when its fact is admitted on anchor A.')
 ev,ho=host_and_event(g,'RESERVE','reserve-ghost',out['state']['core']['revision'],{'authority':g['authority_b'],'histories':[single[1]['history']]},administration=False)
 core=copy.deepcopy(out['state']['core']);row=reservation_record(g,'authority_b','reserve-ghost');row['contributions'][0]['anchor']='anchor-b';core['reservations'].append(row)
 later=transition(out['state'],ev,ho,core,'RESERVED',reservation_id='reserve-ghost',authority_result=g['authority_b_result'],budgets=budget_result(single[1],'950'))
 add(request(out['state'],ev,ho),later,'An unrelated anchor B may use the same text as an event/reservation identifier; that cannot bind the older foreign effect to this request.')
 ev,ho=host_and_event(g,'RESERVE','uact-after-foreign-id',later['state']['core']['revision'],{'authority':g['authority_a'],'histories':[h]},administration=False)
 add(request(later['state'],ev,ho),transition(later['state'],ev,ho,copy.deepcopy(later['state']['core']),'WITHHELD',
     authority_result=g['authority_a_result'],reasons=['EXPOSURE_DISPUTED','RECOVERY_EVIDENCE_INCOMPLETE'],budgets=[]),
     'Anchor A remains unassessed from the immutable foreign actual. The later unrelated identifier does not remove the block or authorize guessed projection.')
 print(json.dumps({'candidate_pin':candidate_pin(),'cases':len(ids)},indent=2))

if __name__=='__main__':main()
