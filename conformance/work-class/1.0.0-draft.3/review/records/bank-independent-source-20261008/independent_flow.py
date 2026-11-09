"""Fresh FLOW-001..003 transition and reconstruction formulas; source-only inputs."""
from independent_common import *
from independent_authority import authority,flow_disclosure_subject,typ
_verified={}
def control_subject(c,e):
 ev=clone(e)
 for k in ['access_authority','transfer_authority']:ev['payload'].pop(k,None)
 return digest('flow-control-subject',dict(configuration_digest=digest('flow-configuration',c),event=ev))
def validate_state(c,s,sd):
 require(sd==digest('flow-state',s),'flow outer digest')
 if sd in _verified:return
 rebuilt=None
 for record in s['records']:
  base=dict(schema=PREFIX+'flow-step-input',specification_pin=PIN,configuration=c,state=rebuilt,state_digest=None if rebuilt is None else digest('flow-state',rebuilt),event=record['event'],host_evidence=record['host_evidence'])
  result=flow(base,historical=True);require(result['status']=='TRANSITION','historical flow refusal');rebuilt=result['state']
 assert_same(rebuilt,s,'complete flow reconstruction');_verified[sd]=True

def require(ok,label):
 if not ok:raise ValueError(label)
def validate_access(a,c,context,operation,t,subject):
 p=a['proposal'];fs=fields(p['fields']);require(p['executor']['actor']==context['actor'],'access actor');require(p['executor']['principal']==c['principal'],'access principal');require(p['interface']==c['control_interface']and p['operation']==operation,'access operation');require(set(fs)=={'admission_subject'}and fs['admission_subject']['value']==subject,'access subject');require(a['clock']==dict(source=c['clock_source'],status='AVAILABLE',instant=t),'access clock');r=authority(a);require(r['status']=='READY_FOR_RESERVATION'and r['required_budgets']==[],'access authority');return r

def flow(i,historical=False):
 c,e,h,s,sd=i['configuration'],i['event'],i['host_evidence'],i['state'],i['state_digest'];cd=digest('flow-configuration',c);ed=digest('flow-event',dict(event=e,host_evidence=h));t=e['clock']['instant'];instant(t);subject=control_subject(c,e);p=e['payload'];kind=e['kind'];rs=[]
 if not historical:
  shape('information-flow','input',i)
  ra=i['response_authority'];rf=fields(ra['proposal']['fields']);require(ra['proposal']['executor']['role']==c['response_role']and ra['proposal']['operation']==c['response_operation']and ra['proposal']['interface']==c['control_interface'],'response role/route')
  expected=digest('flow-response-subject',dict(configuration_digest=cd,state_digest=sd,event_id=e['id'],event_digest=ed,protected_channel=c['protected_channel']))
  require(rf['admission_subject']['value']==expected,'response subject');rr=authority(ra);require(rr['status']=='READY_FOR_RESERVATION'and rr['required_budgets']==[],'response authority')
  if s is not None:validate_state(c,s,sd)
 require(c['specification_pin']==PIN,'flow pin');catalogue={r['id']:r for r in c['restrictions']};require(list(catalogue)==sorted(catalogue)and len(catalogue)==len(c['restrictions']),'flow catalogue order');require(e['clock']==dict(source=c['clock_source'],status='AVAILABLE',instant=t),'flow clock');require(h['configuration_digest']==cd and h['event_subject_digest']==subject,'flow host bindings')
 if s is None:
  require(sd is None and kind=='CREATE_CONTEXT'and e['expected_revision']=='0'and e['expected_state_digest']is None,'flow initial event');core=dict(configuration_digest=cd,revision='0',last_clock=t,contexts=[],artifacts=[],claims=[],consumed_release_acts=[])
 else:
  require(s['core']['configuration_digest']==cd and sd==digest('flow-state',s),'flow prior binding');core=clone(s['core']);require(e['expected_revision']==core['revision']and e['expected_state_digest']==sd,'flow revision');require(t>=core['last_clock'],'flow ordered clock')
 expected_at=[]
 if kind=='CREATE_CONTEXT':expected_at=[dict(kind='INITIAL_INVENTORY',subject_digest=digest('flow-initial-inventory',p),provider=c['provider'],source=c['source'],channel=c['protected_channel'],evidence_ref=h['attestations'][0]['evidence_ref'])]
 elif kind=='READ':expected_at=[dict(kind='SOURCE_CLASSIFICATION',subject_digest=digest('flow-source',p['source']),provider=c['provider'],source=c['source'],channel=c['protected_channel'],evidence_ref=h['attestations'][0]['evidence_ref'])]
 elif kind=='MATERIALIZE':expected_at=[dict(kind='MATERIALIZED_CONTENT',subject_digest=digest('flow-materialized-content',dict(types=p['types'],fields=p['fields'])),provider=c['provider'],source=c['source'],channel=c['protected_channel'],evidence_ref=h['attestations'][0]['evidence_ref'])]
 require(h['attestations']==expected_at,'flow attestation');contexts={x['id']:x for x in core['contexts']};artifacts={x['id']:x for x in core['artifacts']}
 def union_origins(rows):return [rows[k]for k in sorted(rows)]
 def restrictions(origins):return sorted(set(r for o in origins for r in o['restrictions']))
 def claim(context,recipient,channel,purpose,sub,release=None):
  require(all(x['id']!=p['claim_id']and x['intent_id']!=p['intent_id']for x in core['claims']),'flow unique claim/intent')
  core['claims'].append(dict(id=p['claim_id'],intent_id=p['intent_id'],status='POSSIBLE_EXPOSURE',kind=kind,context_id=context,recipient=recipient,channel=channel,purpose=purpose,subject_digest=sub,release_act_digest=release))
 if kind=='CREATE_CONTEXT':
  require(p['context_id']not in contexts and p['initial_sources']==[],'flow dormant context');require(all(r in catalogue and catalogue[r]['scope']==p['scope']for r in p['ceiling']),'flow ceiling catalogue')
  core['contexts'].append(dict(id=p['context_id'],actor=p['actor'],scope=p['scope'],purpose=p['purpose'],revision='1',ceiling=p['ceiling'],restrictions=[],origins=[]));decision='CONTEXT_CREATED'
 elif kind=='READ':
  ctx=contexts[p['context_id']];source=p['source'];require(source['scope']==ctx['scope'],'flow scope');require(all(r in catalogue and catalogue[r]['scope']==source['scope']for r in source['restrictions']),'flow source catalogue');coordinates=['provider','source','record_type','record_id','revision','scope'];
  for retained in [o for context in contexts.values()for o in context['origins']]:
   if all(retained[k]==source[k]for k in coordinates):assert_same(retained,source,'immutable flow source issuance')
  r=validate_access(p['access_authority'],c,ctx,c['access_operation'],t,subject);rs=[r]
  require(set(source['restrictions'])<=set(ctx['ceiling']),'flow source ceiling');orig={digest('flow-source',o):o for o in ctx['origins']};orig[digest('flow-source',source)]=clone(source);ctx['origins']=union_origins(orig);ctx['restrictions']=sorted(set(ctx['restrictions'])|set(source['restrictions']));ctx['revision']=str(int(ctx['revision'])+1);claim(ctx['id'],ctx['id'],c['control_interface'],ctx['purpose'],subject);decision='READ_RECORDED'
 elif kind=='IMPORT':
  sender=contexts[p['sender_context_id']];receiver=contexts[p['receiver_context_id']];art=artifacts[p['artifact_id']];require(art['context_id']==sender['id']and sender['scope']==receiver['scope'],'flow import relation');rs=[validate_access(p['access_authority'],c,receiver,c['access_operation'],t,subject),validate_access(p['transfer_authority'],c,sender,c['transfer_operation'],t,subject)]
  union=set(receiver['restrictions'])|set(sender['restrictions'])|set(art['restrictions']);require(union<=set(receiver['ceiling']),'flow import ceiling');orig={digest('flow-source',o):o for o in receiver['origins']+sender['origins']+art['origins']};receiver['origins']=union_origins(orig);receiver['restrictions']=sorted(union);receiver['revision']=str(int(receiver['revision'])+1);claim(receiver['id'],receiver['id'],c['control_interface'],receiver['purpose'],subject);decision='IMPORT_RECORDED'
 elif kind=='MATERIALIZE':
  ctx=contexts[p['context_id']];ts={t['id']:t for t in p['types']};
  for f in p['fields']:typ(ts[f['value']['type_ref']],f['value'])
  require(ctx['revision']!='1'and p['artifact_id']not in artifacts,'flow materialization prerequisites');core['artifacts'].append(dict(id=p['artifact_id'],context_id=ctx['id'],context_revision=ctx['revision'],context_digest=digest('flow-context',ctx),types=clone(p['types']),fields=clone(p['fields']),restrictions=clone(ctx['restrictions']),origins=clone(ctx['origins'])));decision='ARTIFACT_RECORDED'
 elif kind=='EXPOSE':
  a=clone(p['authority_projection']);require(a['clock']==e['clock'],'exposure event clock');b=next(b for b in a['flow_bases']if b['requirement_id']==p['requirement_id']);require('state'not in b and b['state_digest']==sd and b['configuration']==c,'flow exposure projection');b['state']=clone(s);r=authority(a);require(r['status']=='READY_FOR_RESERVATION','exposure authority');rs=[r];req=next(r for r in a['envelope']['flow_requirements']if r['id']==p['requirement_id']);ctx=contexts[req['context_id']];recipient=fields(a['proposal']['fields'])[req['recipient_field']]['value'];p=dict(claim_id=req['claim_id'],intent_id=req['intent_id']);require(b['released_restrictions']==[],'bank selects no release');claim(ctx['id'],recipient,req['channel'],req['purpose'],flow_disclosure_subject(a,req,b));decision='EXPOSURE_RECORDED'
 else:raise ValueError(kind)
 core['revision']=str(int(core['revision'])+1);core['last_clock']=t
 for k in ['contexts','artifacts','claims']:core[k].sort(key=lambda x:x['id'])
 receipt=dict(schema=PREFIX+'flow-receipt',event_id=e['id'],event_digest=ed,state_before_digest=sd,revision=core['revision'],core_after_digest=digest('flow-core',core),decision=decision,authority_result_digests=[digest('authority-result',r)for r in rs],authority_evidence_digests=[r['evidence_digest']for r in rs],protected_channel=c['protected_channel']);rd=digest('flow-receipt',receipt)
 state=dict(schema=PREFIX+'flow-state',specification_pin=PIN,core=core,records=[]if s is None else clone(s['records']));state['records'].append(dict(event=clone(e),host_evidence=clone(h),event_digest=ed,receipt=receipt,receipt_digest=rd))
 return dict(status='TRANSITION',receipt=receipt,receipt_digest=rd,state=state,state_digest=digest('flow-state',state),replay=False)
