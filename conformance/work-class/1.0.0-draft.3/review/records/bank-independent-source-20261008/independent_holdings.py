"""HOLD-001..005 deterministic registry reconstruction and transition formulas."""
from independent_common import *
_verified={}
def validate_configuration(c):
 shape('holdings','configuration',c)
 assert c['specification_pin']==PIN
 assert c['permissions']==sorted(set(c['permissions']))
 assert_same(c['conflicts'],sorted_set(c['conflicts']),'conflict order')
 for p in c['conflicts']:assert p['left']<p['right'] and p['left'] in c['permissions'] and p['right']in c['permissions']
def held(g,t):return active(g,t) and (g['revoked_at']is None or t<g['revoked_at'])
def validate_admin(c,e,h):
 cd=digest('holdings-configuration',c);a=e['administration'];b=a['basis'];act=a['act'];r=a['return'];t=e['clock']['instant']
 assert b['configuration_digest']==h['configuration_digest']==cd
 assert all(b[k]==c[k] for k in ['principal','provider','source'])
 assert b['role']==c['administration_role'] and b['actor_kind']=='HUMAN' and e['kind']in b['allowed_operations']
 assert active(b,t) and(b['revoked_at']is None or t<b['revoked_at'])and b['observed_at']==t
 proj={k:v for k,v in e.items()if k!='administration'}
 assert act['subject_digest']==digest('holdings-administration-subject',dict(configuration_digest=cd,event=proj))
 assert act['basis_id']==b['id'] and all(act[k]==b[k]for k in ['actor','principal','role'])
 assert act['kind']==e['kind']and act['occurred_at']==t and act['status']=='ACCEPTED'
 assert base64.b64decode(r['act_bytes_base64'],validate=True)==canon(act)
 assert r['act_digest']==digest('holdings-administration-act',act)and r['actor']==act['actor']and r['observed_at']==t
 assert all(r[k]==c[k]for k in ['provider','source'])and r['channel']==c['protected_channel']
 tuples=[dict(kind='ADMIN_BASIS',record_digest=digest('holdings-administration-basis',b),provider=c['provider'],source=c['source'],channel=None),dict(kind='ADMIN_RETURN',record_digest=digest('holdings-administration-return',r),provider=c['provider'],source=c['source'],channel=c['protected_channel'])]
 assert_same(h['authenticated_records'],sorted_set(tuples),'admin authentication')
def validate_state(c,s,sd):
 assert sd==digest('holdings-state',s)
 if sd in _verified:return
 rebuilt=None
 for r in s['records']:
  out=holdings(dict(schema=PREFIX+'holdings-step-input',specification_pin=PIN,configuration=c,state=rebuilt,state_digest=None if rebuilt is None else digest('holdings-state',rebuilt),event=r['event'],host_evidence=r['host_evidence']),historical=True)
  assert out['status']=='TRANSITION'
  rebuilt=out['state']
 assert_same(rebuilt,s,'complete holdings reconstruction')
 _verified[sd]=True
def holdings(i,historical=False):
 c,e,h,s,sd=i['configuration'],i['event'],i['host_evidence'],i['state'],i['state_digest'];validate_configuration(c)
 if s is not None and not historical:validate_state(c,s,sd)
 t=e['clock']['instant'];instant(t);validate_admin(c,e,h)
 assert e['expected_revision']==('0'if s is None else s['core']['revision'])and e['expected_state_digest']==sd
 if s is not None:assert t>=s['core']['last_clock']
 core=dict(configuration_digest=digest('holdings-configuration',c),revision=str(int('0'if s is None else s['core']['revision'])+1),last_clock=t,grants=[]if s is None else clone(s['core']['grants']))
 reasons=[];p=e['payload'];kind=e['kind']
 if kind=='INITIALIZE':
  assert s is None and h['seed_inventory']['inventory_digest']==digest('holdings-seed-inventory',p['grants'])
  core['grants']=[dict(g,revoked_at=None)for g in p['grants']];decision='INITIALIZED'
  for g in core['grants']:assert held(g,t)
 elif kind=='GRANT':
  assert p['permission']in c['permissions']and all(g['id']!=p['grant_id']for g in core['grants'])
  same=[g for g in core['grants']if g['actor']==p['actor']and held(g,t)]
  if any(g['permission']==p['permission']for g in same):decision='UNCHANGED';reasons=['ALREADY_HELD']
  elif any({pair['left'],pair['right']}=={p['permission'],g['permission']}for pair in c['conflicts']for g in same):decision='WITHHELD';reasons=['CONFLICTING_HOLDING']
  else:
   decision='GRANTED';core['grants'].append(dict(id=p['grant_id'],actor=p['actor'],permission=p['permission'],valid_from=t,valid_until=p['valid_until'],revoked_at=None));core['grants'].sort(key=lambda g:g['id'])
 elif kind=='REVOKE':
  g=next(g for g in core['grants']if g['id']==p['grant_id']);assert g['actor']==p['actor']and g['permission']==p['permission']
  if held(g,t):decision='REVOKED';g['revoked_at']=t
  else:decision='UNCHANGED';reasons=['NOT_ACTIVE']
 else:raise ValueError(kind)
 for actor in {g['actor']for g in core['grants']}:
  ps={g['permission']for g in core['grants']if g['actor']==actor and held(g,t)}
  assert not any(p['left']in ps and p['right']in ps for p in c['conflicts'])
 ed=digest('holdings-event',dict(event=e,host_evidence=h));receipt=dict(schema=PREFIX+'holdings-receipt',event_id=e['id'],event_digest=ed,state_before_digest=sd,revision=core['revision'],core_after_digest=digest('holdings-core',core),decision=decision,reasons=reasons,protected_channel=c['protected_channel']);rd=digest('holdings-receipt',receipt)
 outstate=dict(schema=PREFIX+'holdings-state',specification_pin=PIN,core=core,records=[]if s is None else clone(s['records']));outstate['records'].append(dict(event=clone(e),host_evidence=clone(h),event_digest=ed,receipt=receipt,receipt_digest=rd))
 return dict(status='TRANSITION',receipt=receipt,receipt_digest=rd,state=outstate,state_digest=digest('holdings-state',outstate),replay=False)
