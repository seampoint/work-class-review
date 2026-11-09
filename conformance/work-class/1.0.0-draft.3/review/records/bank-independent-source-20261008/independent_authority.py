"""Handwritten source-derived authority judgments, bounded to frozen input profiles.
Sources: AUTH-001..009; AUTHORITY-CHECKS; HOLD-006; FLOW-004..008;
OBSERVATIONS-AND-DISPATCH 1..4; ASSESS-001..006. No consumer imports.
"""
from independent_common import *
from independent_holdings import validate_state as holdings_state,validate_configuration as holdings_configuration,held
class Admission(Exception):
 def __init__(self,code):self.code=code

def require(ok,code):
 if not ok:raise Admission(code)
def unique_order(rows,key):require([key(r)for r in rows]==sorted(set(key(r)for r in rows)),'INPUT_INVALID')
def typ(t,v):
 k=t['kind'];x=v['value'];require(v['type_ref']==t['id'],'TYPE_INVALID')
 if k=='BOOLEAN':require(type(x)is bool,'TYPE_INVALID')
 elif k in ['STRING','IDENTITY']:require(isinstance(x,str)and(k!='IDENTITY'or bool(x)),'TYPE_INVALID')
 elif k=='INSTANT':
  try:instant(x)
  except Exception:raise Admission('TYPE_INVALID')
 elif k in ['DECIMAL','INTEGER']:
  pat=r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?'if k=='DECIMAL'else r'-?(?:0|[1-9][0-9]*)'
  require(isinstance(x,str)and re.fullmatch(pat,x)is not None and x not in ['-0'],'TYPE_INVALID')
  require(not t['nonnegative']or Decimal(x)>=0,'TYPE_INVALID')
 else:raise Admission('TYPE_INVALID')
def pred(p,fs):
 k=p['kind']
 if k in ['AND','OR']:return (all if k=='AND'else any)(pred(a,fs)for a in p['operands'])
 if k=='NOT':return not pred(p['operand'],fs)
 if k=='TRUE':return True
 if k=='FALSE':return False
 def operand(o):return fs[o['name']]if o['kind']=='FIELD'else o['value']
 l,r=operand(p['left']),operand(p['right']);require(l['type_ref']==r['type_ref'],'TYPE_INVALID')
 if k in ['EQUAL','NOT_EQUAL']:return (l==r)if k=='EQUAL'else(l!=r)
 x,y=Decimal(l['value']),Decimal(r['value'])
 return {'LT':x<y,'LTE':x<=y,'GT':x>y,'GTE':x>=y}[k]
def selected_sources(a):
 return [r for r in a['envelope'].get('source_observation_requirements',[])if r['step']==a['proposal']['step']and(a.get('evaluation_point','PROPOSE')=='PROPOSE'or r.get('evaluation_point','PROPOSE')=='PROPOSE_AND_DISPATCH')]
def source_query(a,r):
 q={k:clone(v)for k,v in r.items()if k not in ['id','key_projection']};q['requirement_id']=r['id'];q['at']=a['clock']['instant']if r['at']=='CLOCK'else r['at'];s=r['subject'];fs=fields(a['proposal']['fields'])
 if isinstance(s,dict):q['subject']=fs[s['field']]['value']if s['kind']=='PROPOSAL_FIELD'else a['proposal']['executor'][s['member']]
 if 'key_projection'in r:q['key']=sorted([dict(name=k.get('key_field',k['field']),value=clone(fs[k['field']]))for k in r['key_projection']],key=lambda x:x['name'])
 return q
def assessment_values(a,decl,basis):
 reqs={r['id']:r for r in a['envelope'].get('source_observation_requirements',[])}
 records=[dict(requirement_id=s['requirement_id'],provider=reqs[s['requirement_id']]['provider'],source=reqs[s['requirement_id']]['source'],record_type=reqs[s['requirement_id']]['record_type'],provider_record_id=s['provider_record_id'],provider_revision=s['provider_revision'],fields=s['fields'])for s in basis['supporting_context']]
 cd=digest('content-assessment-context',dict(types=a['work_class']['types'],records=records));rd=digest('content-assessment-rubric',decl['rubric']);p=a['proposal']
 sb={k:clone(p[k])for k in ['work_class_digest','instance','occurrence','step','interface','operation','fields']};sb.update(principal=p['executor']['principal'],context_digest=cd,rubric_digest=rd,evaluator=decl['evaluator'])
 sd=digest('content-assessment-subject',sb);ad=digest('content-assessment',basis['assessment']);rv=digest('content-assessment-review',basis['review'])
 dr=next(r for r in a['envelope']['decision_requirements']if r['id']==decl['review_decision_requirement_id']);ar=reqs[dr['record_requirement_id']]
 ri=canon(dict(provider=ar['provider'],source=ar['source'],record_type=ar['record_type'],provider_record_id=basis['review']['id'])).decode()
 return dict(SUBJECT_DIGEST=sd,ASSESSMENT_DIGEST=ad,REVIEW_DIGEST=rv,REVIEW_IDENTITY=ri,CONTEXT_DIGEST=cd,RUBRIC_DIGEST=rd)
def flow_disclosure_subject(a,r,b):
 c=next(c for c in b['state']['core']['contexts']if c['id']==r['context_id']);art=next(x for x in b['state']['core']['artifacts']if x['id']==r['artifact_id']);p=a['proposal'];fs=fields(p['fields'])
 subject={k:clone(p[k])for k in ['work_class_digest','instance','occurrence','step','interface','operation','fields']}
 subject.update(principal=p['executor']['principal'],configuration_digest=r['configuration_digest'],policy_digest=digest('flow-policy',r['policy']),context_digest=digest('flow-context',c),artifact_digest=digest('flow-artifact',art),recipient=fs[r['recipient_field']]['value'],channel=r['channel'],purpose=r['purpose'],intent_id=r['intent_id'],claim_id=r['claim_id'],released_restrictions=b['released_restrictions'])
 return digest('flow-disclosure-subject',subject)
def _authority(a,leaf=False):
 try:shape('authority','humanDecisionInput'if leaf else'input',a)
 except Exception as exc:
  if type(exc).__module__.startswith('jsonschema'):return authority_refusal('SCHEMA_INVALID')
  raise
 p,e,w,s=a['proposal'],a['envelope'],a['work_class'],a['source'];now=a['clock']['instant'];fs=fields(p['fields']);types={t['id']:t for t in w['types']};steps={x['id']:x for x in w['steps']};root=a['host_selection']['root'];occs={o['id']:o for o in a['occupancies']};caps={c['id']:c for c in a['capacities']};acts=a['acts'];amap={digest('authority-act',x):x for x in acts};returns={r['act_digest']:r for r in a['returns']}
 unique_order(w['types'],lambda x:x['id']);unique_order(w['steps'],lambda x:x['id']);unique_order(p['fields'],lambda x:x['name'])
 for collection in ['occupancies','capacities','credentials','returns']:unique_order(a[collection],lambda x:x['id'])
 unique_order(acts,lambda x:digest('authority-act',x));unique_order(a['host_selection']['authenticated_records'],canon)
 for f in p['fields']:
  require(f['value']['type_ref']in types,'REFERENCE_INVALID');typ(types[f['value']['type_ref']],f['value'])
 for r in a['returns']:
  try:raw=base64.b64decode(r['act_bytes_base64'],validate=True);body=json.loads(raw)
  except Exception:raise Admission('ARTIFACT_ENCODING_INVALID')
  require(base64.b64encode(raw).decode()==r['act_bytes_base64'],'ARTIFACT_ENCODING_INVALID');require(raw==canon(body),'ARTIFACT_NONCANONICAL');require(r['act_digest']==digest('authority-act',body),'DEPENDENCY_MISMATCH')
 for rec in [root,e]+a['occupancies']+a['capacities']+a['credentials']:
  v=rec.get('validity',rec.get('temporal_validity'));require(v is not None,'INPUT_INVALID')
  try:instant(v['valid_from']);(instant(v['valid_until'])if v['valid_until']is not None else None)
  except Exception:raise Admission('INPUT_INVALID')
  require(v['valid_until']is None or v['valid_from']<v['valid_until'],'INPUT_INVALID')
  if rec.get('reliance',{}).get('kind')=='SURVIVE_EXPIRY':
   v=rec['reliance']['validity'];instant(v['valid_from']);(instant(v['valid_until'])if v['valid_until']is not None else None)
 for act in acts:instant(act['occurred_at'])
 for r in a['returns']:instant(r['returned_at'])
 if now is not None:instant(now)
 require(a['specification_pin']==PIN,'VERSION_UNSUPPORTED')
 S,W,E,P,R=[digest(k,x)for k,x in [('authority-source',s),('authority-work-class',w),('authority-envelope',e),('authority-proposal',p),('authority-root',root)]];O=digest('authority-operation',dict(envelope_digest=E,work_class_digest=W,proposal_digest=P))
 require(e['source_digest']==S and e['work_class_digest']==W and p['work_class_digest']==W,'DEPENDENCY_MISMATCH')
 require(all(root[k]==v for k,v in [('source_digest',S),('work_class_digest',W),('envelope_digest',E),('principal',e['principal'])]),'DEPENDENCY_MISMATCH')
 require(a['clock']['source']==e['clock_source'],'DEPENDENCY_MISMATCH')
 expected_auth=[]
 for name,kind,domain in [('occupancies','OCCUPANCY','authority-occupancy'),('capacities','CAPACITY','authority-capacity'),('credentials','CREDENTIAL','authority-credential'),('returns','RETURN','authority-return')]:
  for r in a[name]:expected_auth.append(dict(kind=kind,record_digest=digest(domain,r),provider=r['provider'],channel=r.get('channel')if kind=='RETURN'else None))
 require(canon(sorted_set(expected_auth))==canon(a['host_selection']['authenticated_records']),'DEPENDENCY_MISMATCH')
 require(set(occs)==set(root['occupancy_ids'])and set(caps)==set(root['capacity_ids']),'DEPENDENCY_MISMATCH')
 for c in a['capacities']:require(c['root_digest']==R and c['envelope_digest']==E and c['principal']==e['principal'],'DEPENDENCY_MISMATCH')
 for c in a['credentials']:
  require(c['occupancy']in occs,'EVIDENCE_UNAVAILABLE');require(c['actor']==occs[c['occupancy']]['actor'],'DEPENDENCY_MISMATCH')
 for b in a.get('holdings_bases',[]):
  try:holdings_configuration(b['configuration']);holdings_state(b['configuration'],b['state'],b['state_digest'])
  except Exception:raise Admission('STATE_INVALID')
  require(b['configuration']['principal']==e['principal']and b['configuration']['clock_source']==e['clock_source'],'DEPENDENCY_MISMATCH')
  cd=digest('holdings-configuration',b['configuration']);require(b['selection']['configuration_digest']==cd and b['selection']['state_digest']==b['state_digest']and b['selection']['revision']==b['state']['core']['revision'],'DEPENDENCY_MISMATCH')
 for b in a.get('flow_bases',[]):
  from independent_flow import validate_state as flow_state
  try:flow_state(b['configuration'],b['state'],b['state_digest'])
  except Exception as exc:raise Admission('STATE_INVALID')from exc
 require(len(canon(a))<=(262144 if leaf else 1048576),'LIMIT_EXCEEDED')
 require(not e['limitations']and not root['limitations'],'UNSUPPORTED_RELATION')
 require(p['step']in steps,'REFERENCE_INVALID');step=steps[p['step']]
 require(p['work_class']==w['id']and p['operation']==step['operation']and p['interface']==step['interface'],'BINDING_MISMATCH')
 require([(f['name'],f['value']['type_ref'])for f in p['fields']]==[(f['name'],f['type_ref'])for f in step['fields']],'BINDING_MISMATCH')
 require(p['executor']['role']==step['executor_role']==e['executor_role']and p['executor']['principal']==e['principal'],'BINDING_MISMATCH');require(p['executor']['occupancy']in occs,'EVIDENCE_UNAVAILABLE')
 xo=occs[p['executor']['occupancy']];require(all(xo[k]==p['executor'][k]for k in ['actor','role','principal']),'BINDING_MISMATCH')
 require(any(op==dict(step=p['step'],operation=p['operation'],interface=p['interface'])for op in e['operations']),'BINDING_MISMATCH')
 bindings={b['id']:fs[b['field']]['value']for b in e['bindings']};scope=dict(subjects=[],resources=[])
 for k in ['subjects','resources']:scope[k]=sorted(set(x['value']if x['kind']=='CONSTANT'else bindings[x['binding']]for x in e['scope'][k]))
 actual=dict(subjects=sorted(set(fs[n]['value']for n in step['scope_fields']['subjects'])),resources=sorted(set(fs[n]['value']for n in step['scope_fields']['resources'])))
 require(all(set(actual[k])<=set(scope[k])for k in ['subjects','resources']),'BINDING_MISMATCH')
 decs={d['id']:d for d in e.get('decision_requirements',[])if d['step']==p['step']};dbs={b['requirement_id']:b for b in a.get('decision_bases',[])}
 require(set(dbs)<=set(decs),'DEPENDENCY_MISMATCH');require(set(decs)<=set(dbs),'EVIDENCE_UNAVAILABLE')
 ars={d['id']:d for d in e.get('assessment_requirements',[])if d['step']==p['step']};abs_={b['requirement_id']:b for b in a.get('assessment_bases',[])};require(set(abs_)<=set(ars),'DEPENDENCY_MISMATCH');require(set(ars)<=set(abs_),'EVIDENCE_UNAVAILABLE')
 av={k:assessment_values(a,d,abs_[k])for k,d in ars.items()}
 for k,d in ars.items():
  b=abs_[k];v=av[k];ass=b['assessment'];require(ass['subject_digest']==v['SUBJECT_DIGEST']and ass['context_digest']==v['CONTEXT_DIGEST']and ass['rubric_digest']==v['RUBRIC_DIGEST']and ass['evaluator']==d['evaluator']and b['review']['assessment_digest']==v['ASSESSMENT_DIGEST'],'BINDING_MISMATCH')
 for k,d in decs.items():
  b=dbs[k]['evidence'];l=b['authority_input'];require(digest('authority-work-class',l['work_class'])==d['work_class_digest']and digest('authority-envelope',l['envelope'])==d['envelope_digest'],'DEPENDENCY_MISMATCH')
  lf=fields(l['proposal']['fields']);ltypes={t['id']:t for t in l['work_class']['types']};require(l['clock']['status']==a['clock']['status']and l['clock']['instant']==now,'BINDING_MISMATCH')
  require(set(lf)=={x['field']for x in d['context_bindings']},'BINDING_MISMATCH')
  for binding in d['context_bindings']:
   v=binding['value'];actualvalue=lf[binding['field']]
   if v['kind']=='PROPOSAL_FIELD':expect=fs[v['field']]
   elif v['kind']=='LITERAL':expect=v['value']
   elif v['kind']=='ASSESSMENT':expect=dict(type_ref=v['type_ref'],value=av[v['requirement_id']][v['member']])
   elif v['kind']=='FLOW_DISCLOSURE':
    fr=next(r for r in e['flow_requirements']if r['id']==v['requirement_id']);fb=next(x for x in a['flow_bases']if x['requirement_id']==fr['id']);expect=dict(type_ref=v['type_ref'],value=flow_disclosure_subject(a,fr,fb))
   else:raise Admission('UNSUPPORTED_RELATION')
   require(types[expect['type_ref']]==ltypes[actualvalue['type_ref']],'TYPE_INVALID');require(actualvalue==expect,'BINDING_MISMATCH')
  da=next(x for x in l['acts']if x['kind']=='INSTANCE_DECISION');require(b['decision_act_digest']==digest('authority-act',da),'BINDING_MISMATCH');require(l['proposal']['executor']==dict(actor=da['actor'],role=da['role'],principal=da['principal'],occupancy=da['occupancy']),'BINDING_MISMATCH')
  require(da['principal']==d['principal']and da['role']==d['role'],'BINDING_MISMATCH')
 for r in e.get('flow_requirements',[]):
  if r['step']!=p['step']:continue
  b=next((b for b in a.get('flow_bases',[])if b['requirement_id']==r['id']),None);require(b is not None,'EVIDENCE_UNAVAILABLE');c=next((c for c in b['state']['core']['contexts']if c['id']==r['context_id']),None);art=next((x for x in b['state']['core']['artifacts']if x['id']==r['artifact_id']),None)
  require(c is not None and art is not None,'BINDING_MISMATCH');require(c['actor']==p['executor']['actor']and c['scope']==e['scope']['id']and art['context_id']==c['id'],'BINDING_MISMATCH');require(art['types']==w['types']and art['fields']==p['fields'],'BINDING_MISMATCH')
 gate=e['gate'];gd=None
 if gate.get('decision_requirement'):gd=next(x for x in dbs[gate['decision_requirement']]['evidence']['authority_input']['acts']if x['kind']=='INSTANCE_DECISION')
 elif gate['kind']!='NONE':
  kind='VERIFY'if gate['kind']=='VERIFY'else'INSTANCE_DECISION';candidates=[x for x in acts if x['kind']==kind];require(len(candidates)==1,'GATE_REQUIRED');gd=candidates[0]
 grants=[x for x in acts if x['kind']=='GRANT'];att=[x for x in acts if x['kind']=='ORGANISATIONAL_ATTESTATION'];require(len(grants)==1 and len(att)==(2 if gate['kind']=='DECIDE'and not gate.get('decision_requirement')else 1),'ACT_CONFLICT')
 require(grants[0]['id']==e['grant_ref']and grants[0]['subject_digest']==E and grants[0]['role']==e['grantor_role'],'ACT_NOT_AUTHORIZED')
 for ad,act in amap.items():
  require(act['capacity']in caps and act['occupancy']in occs,'EVIDENCE_UNAVAILABLE');c=caps[act['capacity']];o=occs[act['occupancy']]
  require(all(act[k]==c[k]==o[k]for k in ['actor','role','principal'])and c['occupancy']==act['occupancy']and o['kind']=='HUMAN'and act['kind']in c['act_kinds'],'ACT_NOT_AUTHORIZED')
  require(active(root['validity'],act['occurred_at'])and active(c['validity'],act['occurred_at'])and active(o['validity'],act['occurred_at'])and(now is None or act['occurred_at']<=now),'ACT_NOT_AUTHORIZED')
  require(ad in returns,'EVIDENCE_UNAVAILABLE');r=returns[ad];require(base64.b64decode(r['act_bytes_base64'])==canon(act)and r['actor']==act['actor'],'ACT_NOT_AUTHORIZED')
  ch=next((x for x in root['channels']if x['id']==r['channel']and x['provider']==r['provider']),None);require(ch is not None and active(ch['validity'],r['returned_at'])and act['occurred_at']<=r['returned_at']and(now is None or r['returned_at']<=now),'ACT_NOT_AUTHORIZED');require(now is None or ch['prior_returns_survive_expiry']or active(ch['validity'],now),'ACT_NOT_AUTHORIZED')
  if act['kind']=='ORGANISATIONAL_ATTESTATION':
   target=amap.get(act['subject_digest']);require(target is not None and target['kind']in ['GRANT','INSTANCE_DECISION']and act['attested_actor']==target['actor']and act['role']==e['attester_role']and act['occurred_at']>=target['occurred_at'],'ACT_NOT_AUTHORIZED');require(act['actor']!=target['actor']or(root['allow_self_attestation']and c['may_self_attest']),'ACT_NOT_AUTHORIZED')
  elif act['kind']in ['VERIFY','INSTANCE_DECISION']:require(act['subject_digest']==O and act['role']==gate['role']and act['criteria']==[r['id']for r in gate['criteria']if r['step']==p['step']],'ACT_NOT_AUTHORIZED')
  require(act['disposition']=='ACCEPT','ACT_NOT_ACCEPTED')
 drs=[]
 for k,d in decs.items():
  lr=authority(dbs[k]['evidence']['authority_input'],True)
  if lr['status']=='REFUSED'and lr['code']!='AUTHORITY_NOT_ESTABLISHED':raise Admission(lr['code'])
  drs.append(dict(requirement_id=k,result=lr,result_digest=digest('authority-result',lr)))
 for k,d in ars.items():require(abs_[k]['assessment']['assessed_at']<=gd['occurred_at'],'BINDING_MISMATCH')
 if now is None:return authority_refusal('AUTHORITY_NOT_ESTABLISHED',['CLOCK_UNAVAILABLE'])
 checks=[];failed=[]
 def check(purpose,subject,ref,at=now,reasons=()):
  row=dict(purpose=purpose,subject_digest=subject,requirement_ref=ref,at=at);checks.append(row)
  for reason in reasons:failed.append(dict(row,reason=reason))
 for pu,sub,ref in [('SOURCE_BINDING',E,s['id']),('ROOT_BINDING',E,root['id']),('INPUT_SUPPORT',O,p['step']),('BINDING',O,e['scope']['id']),('GATE_FLOOR',E,e['id'])]:check(pu,sub,ref)
 if not root['prior_acts_survive_expiry']and not active(root['validity'],now):failed.append(dict(checks[1],reason='ROOT_EXPIRED'))
 check('ENVELOPE_VALIDITY',E,e['id'],reasons=[]if active(e['temporal_validity'],now)else['ENVELOPE_EXPIRED'])
 if not leaf:check('EXECUTOR_OCCUPANCY',O,p['executor']['occupancy'],reasons=[]if active(xo['validity'],now)else['ACT_EXPIRED'])
 for r in e['conditions']:
  if r['step']==p['step']:check('CONDITION',O,r['id'],reasons=[]if pred(r['predicate'],fs)else['CONDITION_VIOLATED'])
 for r in e['limits']['per_action']:
  if r['step']==p['step']:
   val=Decimal(fs[r['field']]['value']);bound=Decimal(r['bound']['value']);ok=val<bound if r['operator']=='LT'else val<=bound;check('PER_ACTION_LIMIT',O,r['id'],reasons=[]if ok else['PER_ACTION_LIMIT_VIOLATED'])
 for c in a['credentials']:check('CREDENTIAL',O,c['id'],reasons=[]if active(c['validity'],now)else['CREDENTIAL_EXPIRED'])
 for ad,act in amap.items():
  c=caps[act['capacity']];check('ACT_CAPACITY',ad,c['id'],act['occurred_at']);check('ACT_OCCUPANCY',ad,act['occupancy'],act['occurred_at']);ok=active(c['validity'],now)or(c['reliance']['kind']=='SURVIVE_EXPIRY'and active(c['reliance']['validity'],now));check('ACT_RELIANCE',ad,c['id'],reasons=[]if ok else['RELIANCE_EXPIRED']);check('RETURN',ad,returns[ad]['id'])
  if act['kind']=='ORGANISATIONAL_ATTESTATION':check('SEPARATION',ad,c['id'])
 if gd is not None:
  for r in gate['criteria']:
   if r['step']==p['step']:check('GATE_CRITERION',digest('authority-act',gd),r['id'],gd['occurred_at'],[]if pred(r['predicate'],fs)else['GATE_CRITERION_VIOLATED'])
 queries={}
 def rev(subject,declaration,at):
  q=dict(purpose='REVOCATION',subject_digest=subject,at=at,provider=declaration['provider'],source=declaration['source']);queries[digest('authority-query',q)]=(q,declaration)
 for act in acts:
  c=caps[act['capacity']]
  for t in [act['occurred_at'],now]:rev(R,root['revocation'],t);rev(digest('authority-capacity',c),c['revocation'],t)
 rev(E,e['revocation'],now)
 for c in a['credentials']:rev(digest('authority-credential',c),c['revocation'],now)
 for r in selected_sources(a):q=source_query(a,r);queries[digest('authority-query',q)]=(q,r)
 groups={}
 for o in a['observations']:
  qd=digest('authority-query',o['query']);require(o['query_digest']==qd and qd in queries and o['query']==queries[qd][0],'DEPENDENCY_MISMATCH');groups.setdefault(qd,[]).append(o)
 require(set(queries)<=set(groups),'EVIDENCE_UNAVAILABLE')
 usable={}
 for qd,(q,declaration)in queries.items():
  rows=sorted_set(groups[qd]);reasons=[];o=rows[0]
  if q['purpose']=='REVOCATION':
   if len(rows)>1:reasons=['OBSERVATION_CONFLICT']
   elif o['status']!='AVAILABLE':reasons=[{'UNAVAILABLE':'OBSERVATION_UNAVAILABLE','INCOMPLETE':'OBSERVATION_INCOMPLETE','CONFLICT':'OBSERVATION_CONFLICT'}[o['status']]]
   else:
    require(o['as_of']<=q['at'],'INPUT_INVALID')
    if(instant(q['at'])-instant(o['as_of'])).total_seconds()>int(declaration['max_age_seconds']):reasons.append('OBSERVATION_STALE')
    if o['revoked']:reasons.append('REVOKED')
   check('REVOCATION',q['subject_digest'],qd,q['at'],reasons)
  else:
   if len(rows)>1:reasons=['SOURCE_OBSERVATION_CONFLICT']
   elif o['status']not in ['AVAILABLE','ABSENT']:reasons=['SOURCE_OBSERVATION_'+o['status']]
   else:
    if not(o['as_of']<=q['at']<=now):reasons.append('SOURCE_OBSERVATION_TIME')
    if(instant(q['at'])-instant(o['as_of'])).total_seconds()>int(q['freshness_seconds']):reasons.append('SOURCE_OBSERVATION_STALE')
    if o['status']!=q['expected_status']or(o['status']=='AVAILABLE'and q['record_id']is not None and o['provider_record_id']!=q['record_id']):reasons.append('SOURCE_OBSERVATION_BINDING')
    if o['status']=='AVAILABLE':
     if sorted((x['name'],x['value']['type_ref'])for x in o['fields'])!=sorted((x['name'],x['type_ref'])for x in q['fields']):reasons.append('SOURCE_OBSERVATION_FIELDS')
     for f in o['fields']:typ(types[f['value']['type_ref']],f['value'])
    if not reasons:usable[q['requirement_id']]=o
   check('SOURCE_OBSERVATION',E,q['requirement_id'],q['at'],reasons)
 def sel(v,current):
  if isinstance(v,str):return fields(usable[current]['fields'])[v]
  k=v['kind']
  if k=='LITERAL':return v['value']
  if k=='PROPOSAL_FIELD':return fs[v['field']]
  if k=='EXECUTOR':return dict(type_ref=v['type_ref'],value=p['executor'][v['member']])
  if k=='CLOCK':return dict(type_ref=v['type_ref'],value=now)
  if k=='OBSERVATION_FIELD':return fields(usable[v['requirement_id']]['fields'])[v['field']]
  if k=='OBSERVATION_ID':return dict(type_ref=v['type_ref'],value=usable[v['requirement_id']]['provider_record_id'])
  if k in ['DECISION_ACT','DECISION_FIELD','DECISION_BASIS']:
   l=dbs[v['requirement_id']]['evidence']['authority_input'];da=next(x for x in l['acts']if x['kind']=='INSTANCE_DECISION')
   if k=='DECISION_FIELD':return fields(l['proposal']['fields'])[v['field']]
   if k=='DECISION_BASIS':return dict(type_ref=v['type_ref'],value=digest('human-decision-reliance-subjects',dict(root_digest=digest('authority-root',l['host_selection']['root']),envelope_digest=digest('authority-envelope',l['envelope']),capacities=[dict(id=c['id'],capacity_digest=digest('authority-capacity',c))for c in l['capacities']])))
   return dict(type_ref=v['type_ref'],value=digest('authority-act',da)if v['member']=='digest'else da[v['member']])
  if k=='ACT':
   ac=next(x for x in acts if x['kind']==v['act_kind']);return dict(type_ref=v['type_ref'],value=ac[v['member']])
  raise ValueError(k)
 for r in selected_sources(a):
  if r['id']not in usable:continue
  o=usable[r['id']];bad=o['relations']!=r['relations']
  for rel in r['relations']:
   try:
    l,rr=sel(rel['left'],r['id']),sel(rel['right'],r['id']);require(l['type_ref']==rr['type_ref'],'TYPE_INVALID');x,y=l['value'],rr['value'];kind=rel['kind']
    ok={'EQUALS':x==y,'NOT_EQUALS':x!=y,'BEFORE':x<y,'AFTER':x>y,'AT_OR_BEFORE':x<=y,'AT_OR_AFTER':x>=y}.get(kind)
    if kind=='ELAPSED_LTE':ok=0<=(instant(y)-instant(x)).total_seconds()<=int(rel['maximum_seconds'])
    if not ok:bad=True
   except KeyError:bad=True
  if bad:check('SOURCE_OBSERVATION',E,r['id'],source_query(a,r)['at'],['SOURCE_OBSERVATION_RELATIONS'])
 for k,d in decs.items():
  lr=next(x['result']for x in drs if x['requirement_id']==k);da=next(x for x in dbs[k]['evidence']['authority_input']['acts']if x['kind']=='INSTANCE_DECISION');ad=digest('authority-act',da);check('HUMAN_DECISION',ad,k,reasons=[]if lr['status']=='EVIDENCE_VALID'else['DECISION_NOT_EFFECTIVE'])
  for distinct in d['distinct_from']:
   other=p['executor']['actor']if distinct['kind']=='EXECUTOR'else next(x for x in dbs[distinct['requirement_id']]['evidence']['authority_input']['acts']if x['kind']=='INSTANCE_DECISION')['actor'];check('SEPARATION',ad,k,reasons=[]if da['actor']!=other else['DECISION_SEPARATION'])
 for r in e.get('holdings_requirements',[]):
  if r['step']!=p['step']:continue
  actor=p['executor']['actor']if r['actor']=='EXECUTOR'else gd['actor'];sub=digest('holdings-query',dict(requirement=r,actor=actor,at=now));b=next((b for b in a.get('holdings_bases',[])if digest('holdings-configuration',b['configuration'])==r['configuration_digest']),None);rs=[]
  if b is None or b['selection']['status']!='AVAILABLE':rs=['HOLDINGS_UNAVAILABLE']
  elif b['selection']['at']!=now or now<b['state']['core']['last_clock']:rs=['HOLDINGS_STALE']
  elif len(b['state']['records'])>=64:rs=['HOLDINGS_CAPACITY_EXHAUSTED']
  elif not any(g['actor']==actor and g['permission']==r['permission']and held(g,now)for g in b['state']['core']['grants']):rs=['CURRENT_HOLDING_REQUIRED']
  check('HOLDINGS',sub,r['id'],reasons=rs)
 for k,d in ars.items():
  b=abs_[k];v=av[k];src=d['sources'];changed=False
  def current(role):
   rid=src[role]if isinstance(src[role],str)else src[role]['requirement_id'];return usable.get(rid)
  def compare(role,key,value):
   nonlocal changed
   o=current(role)
   if o is not None and fields(o['fields']).get(src[role][key],{}).get('value')!=value:changed=True
  o=current('content')
  if o is not None and fields(o['fields'])!=fs:changed=True
  for snap in b['supporting_context']:
   o=usable.get(snap['requirement_id'])
   if o is not None and(o['provider_record_id']!=snap['provider_record_id']or o['revision']!=snap['provider_revision']or fields(o['fields'])!=fields(snap['fields'])):changed=True
  compare('context_selection','digest_field',v['CONTEXT_DIGEST']);compare('rubric','digest_field',v['RUBRIC_DIGEST']);compare('assessment','digest_field',v['ASSESSMENT_DIGEST']);compare('selection','digest_field',v['ASSESSMENT_DIGEST'])
  aid=canon(dict(provider=b['assessment']['provider'],source=b['assessment']['source'],record_type=b['assessment']['record_type'],provider_record_id=b['assessment']['id'])).decode();compare('selection','identity_field',aid);compare('effectiveness','identity_field',aid);compare('effectiveness','effective_field',True)
  for key in ['provider','model','version']:compare('evaluator',key+'_field',d['evaluator'][key])
  rs=[]
  if changed:rs.append('ASSESSMENT_DEPENDENCY_CHANGED')
  if b['review']['decision']!='APPROVE'or any(x['disposition']!='SATISFIED'for x in b['review']['criteria']):rs.append('ASSESSMENT_NOT_SATISFIED')
  check('ASSESSMENT',v['ASSESSMENT_DIGEST'],k,reasons=rs)
 for r in e.get('flow_requirements',[]):
  if r['step']!=p['step']:continue
  b=next(b for b in a['flow_bases']if b['requirement_id']==r['id']);c=next(c for c in b['state']['core']['contexts']if c['id']==r['context_id']);art=next(x for x in b['state']['core']['artifacts']if x['id']==r['artifact_id']);recipient=fs[r['recipient_field']]['value'];sub=digest('flow-query',dict(requirement_id=r['id'],context_digest=digest('flow-context',c),artifact_digest=digest('flow-artifact',art),intent_id=r['intent_id'],claim_id=r['claim_id'],recipient=recipient,channel=r['channel'],purpose=r['purpose'],at=now));rs=[];core=b['state']['core'];src=r['sources']
  if b['selection']['status']!='AVAILABLE':rs.append('FLOW_UNAVAILABLE')
  elif b['selection']['at']!=now or now<core['last_clock']:rs.append('FLOW_STALE')
  if len(b['state']['records'])>=128 or len(core['claims'])>=128:rs.append('FLOW_CAPACITY_EXHAUSTED')
  po=usable.get(src['policy']['requirement_id']);ro=usable.get(src['recipient']['requirement_id'])
  if po is not None and fields(po['fields'])[src['policy']['digest_field']]['value']!=digest('flow-policy',r['policy']):rs.append('FLOW_DEPENDENCY_CHANGED')
  if ro is not None:
   rfs=fields(ro['fields'])
   if any(rfs[src['recipient'][key+'_field']]['value']!=val for key,val in [('recipient',recipient),('channel',r['channel']),('purpose',r['purpose'])]):rs.append('FLOW_DEPENDENCY_CHANGED')
   if rfs[src['recipient']['effective_field']]['value']is not True:rs.append('FLOW_RECIPIENT_NOT_ENTITLED')
  union=set(c['restrictions'])|set(art['restrictions']);released=set(b['released_restrictions'])
  if any(not any(row==dict(restriction_id=rid,scope=c['scope'],recipient=recipient,channel=r['channel'],purpose=r['purpose'])for row in r['policy']['entitlements'])for rid in union-released):rs.append('FLOW_RECIPIENT_NOT_ENTITLED')
  if released:raise Admission('UNSUPPORTED_RELATION')
  if any(cl['id']==r['claim_id']or cl['intent_id']==r['intent_id']for cl in core['claims']):rs.append('FLOW_CLAIM_CONSUMED')
  check('FLOW',sub,r['id'],reasons=rs)
 extra=dict(decision_results=drs)if'decision_bases'in a else{}
 if failed:return authority_refusal('AUTHORITY_NOT_ESTABLISHED',[f['reason']for f in failed],failed,**extra)
 evidence={k:clone(a[k])for k in ['host_selection','occupancies','capacities','credentials','acts','returns','observations','clock']}
 for k in ['evaluation_point','decision_bases','holdings_bases','flow_bases','assessment_bases']:
  if k in a:evidence[k]=clone(a[k])
 result=dict(schema=PREFIX+('human-decision-result'if leaf else'authority-result'),specification_pin=PIN,status='EVIDENCE_VALID'if leaf else'READY_FOR_RESERVATION',source_digest=S,work_class_digest=W,envelope_digest=E,proposal_digest=P,operation_digest=O,scope=scope,actual_scope=actual,act_digests=sorted(amap),checks=sorted_set(checks),required_budgets=e['limits']['shared_budgets'],evidence_digest=digest('authority-evidence',evidence),**extra)
 if leaf:
  result['decision_act_digest']=digest('authority-act',gd);ends=[e['temporal_validity']['valid_until']]
  if not root['prior_acts_survive_expiry']:ends.append(root['validity']['valid_until'])
  for ch in root['channels']:
   if not ch['prior_returns_survive_expiry']:ends.append(ch['validity']['valid_until'])
  for c in caps.values():
   if c['reliance']['kind']=='CURRENT_ONLY':ends.append(c['validity']['valid_until'])
   else:
    v,rv=c['validity'],c['reliance']['validity'];intervals=sorted([v,rv],key=lambda x:x['valid_from']);start=intervals[0]['valid_from'];end=intervals[0]['valid_until']
    if end is None or intervals[1]['valid_from']<=end:end=None if end is None or intervals[1]['valid_until']is None else max(end,intervals[1]['valid_until'])
    elif active(rv,now):end=rv['valid_until']
    ends.append(end)
  result['effective_until']=min(x for x in ends if x is not None)
 return result
_cache={}
def authority(a,leaf=False):
 key=(digest('independent-source-authority-cache',a),leaf)
 if key in _cache:return clone(_cache[key])
 try:out=_authority(a,leaf)
 except Admission as exc:out=authority_refusal(exc.code)
 _cache[key]=clone(out);return out
