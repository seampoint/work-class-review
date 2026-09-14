import base64, datetime as dt, hashlib, json, re, sys
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT=Path(__file__).resolve().parent
VENDOR=ROOT.parent/'vendor'
if str(VENDOR) not in sys.path: sys.path.insert(0,str(VENDOR))
from jsonschema import Draft202012Validator, RefResolver

PIN='sha256:'+'0'*64
PROTOCOL='seampoint.work-class.adapter/1.0.0-draft.2'
SPEC='seampoint.work-class/1.0.0-draft.2'
LIMITS={'max_definitions':'64','max_operations':'256','max_expression_depth':'64','max_expression_nodes':'4096','max_collection_members':'1024','max_numeric_digits':'128'}

class Refusal(Exception):
 def __init__(self,code,path=''): self.code,self.path=code,path

def canon(x):
 if x is None:return b'null'
 if type(x) is bool:return b'true' if x else b'false'
 if type(x) is str:
  if any(0xD800 <= ord(c) <= 0xDFFF for c in x): raise ValueError('surrogate')
  return json.dumps(x,ensure_ascii=False,separators=(',',':')).encode('utf-8')
 if type(x) is list:return b'['+b','.join(canon(v) for v in x)+b']'
 if type(x) is dict:
  return b'{'+b','.join(canon(k)+b':'+canon(x[k]) for k in sorted(x,key=lambda z:z.encode('utf-16-be')))+b'}'
 raise ValueError('number')
def digest(kind,x): return 'sha256:'+hashlib.sha256((SPEC+'/'+kind+'\n').encode()+canon(x)).hexdigest()
def strict(pairs):
 d={}
 for k,v in pairs:
  if k in d: raise ValueError('duplicate')
  d[k]=v
 return d
def parse(raw): return json.loads(raw.decode('utf-8'),object_pairs_hook=strict,parse_int=lambda x:(_ for _ in ()).throw(ValueError('number')),parse_float=lambda x:(_ for _ in ()).throw(ValueError('number')),parse_constant=lambda x:(_ for _ in ()).throw(ValueError('constant')))
def pointer(s): return str(s).replace('~','~0').replace('/','~1')
def instant(s):
 if not isinstance(s,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{9})?Z',s): raise ValueError()
 try:
  d=dt.datetime.fromisoformat(s[:-1]+'+00:00')
  if d.second>59: raise ValueError()
  frac=s.split('.',1)[1][:-1] if '.' in s else ''
  epoch=dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)
  whole=(d-epoch).days*86400 + (d-epoch).seconds
  return whole*1000000000 + int(frac.ljust(9,'0') or 0)
 except ValueError: raise
def dec(s, nonnegative=False):
 if not isinstance(s,str) or not re.fullmatch(r'-?(?:0|[1-9]\d*)(?:\.[0-9]*[1-9])?',s): raise ValueError()
 if s.startswith('-') and Decimal(s)==0: raise ValueError()
 if nonnegative is False: pass
 return Decimal(s)
def decimal_scaled(s, scale):
 t=Decimal(s).as_tuple(); coefficient=0
 for digit in t.digits: coefficient=coefficient*10+digit
 if t.sign: coefficient=-coefficient
 exponent=t.exponent
 if exponent >= 0: return coefficient*10**exponent*scale
 divisor=10**(-exponent)
 numerator=coefficient*scale
 if numerator % divisor: raise ValueError()
 return numerator//divisor
def exact_add(a,b):
 def parts(s):
  q=s.split('.'); return int(q[0]+(q[1] if len(q)>1 else '')), len(q[1]) if len(q)>1 else 0
 ai,as_=parts(a); bi,bs=parts(b); scale=max(as_,bs)
 v=ai*10**(scale-as_)+bi*10**(scale-bs)
 out=str(v)
 if scale:
  neg=out.startswith('-'); digits=out[1:] if neg else out
  digits=digits.zfill(scale+1); out=digits[:-scale]+'.'+digits[-scale:]
  out=out.rstrip('0').rstrip('.')
  if out=='': out='0'
  if neg: out='-'+out
 return out
def schema_ok(obj,name):
 schema=json.loads((ROOT.parent/'input/aggregate.schema.json').read_text())
 ref=RefResolver.from_schema(schema)
 return not list(Draft202012Validator({'$ref':'#/$defs/'+name},resolver=ref).iter_errors(obj))
def zone(name):
 if not isinstance(name,str) or name.startswith('/') or '..' in name.split('/'):
  _fail('INPUT_INVALID')
 try:
  with (VENDOR/'tzdata'/'zoneinfo'/name).open('rb') as f: return ZoneInfo.from_file(f,key=name)
 except (OSError,ValueError): _fail('INPUT_INVALID')
def artifact(encoded):
 if not isinstance(encoded,str): raise Refusal('ARTIFACT_ENCODING_INVALID','/artifact_bytes_base64')
 try:
  raw=base64.b64decode(encoded,validate=True); obj=parse(raw)
 except Exception: raise Refusal('ARTIFACT_ENCODING_INVALID','/artifact_bytes_base64')
 if base64.b64encode(raw).decode()!=encoded: raise Refusal('ARTIFACT_ENCODING_INVALID','/artifact_bytes_base64')
 try:
  canonical=canon(obj)
 except (ValueError,UnicodeError,TypeError):
  raise Refusal('ARTIFACT_ENCODING_INVALID','/artifact_bytes_base64')
 if canonical!=raw: raise Refusal('ARTIFACT_NONCANONICAL','/artifact_bytes_base64')
 if not isinstance(obj,dict) or obj.get('schema')!=SPEC+'/aggregate-definition': raise Refusal('VERSION_UNSUPPORTED')
 if not schema_ok(obj,'definition'): raise Refusal('SCHEMA_INVALID')
 return obj

def _fail(code): raise Refusal(code)
def _ordered(xs, key): return all(key(xs[i]) < key(xs[i+1]) for i in range(len(xs)-1))
def semantic_validate(a, phase=3):
 d=a['definition']; ag=d['aggregate']; types={t['id']:t for t in d['types']}
 if len(types)!=len(d['types']) or not _ordered(d['types'],lambda x:x['id'].encode()): raise Refusal('REFERENCE_INVALID','/definition')
 if len(ag['mappings'])!=len({m['id'] for m in ag['mappings']}) or not _ordered(ag['mappings'],lambda x:x['id'].encode()): raise Refusal('REFERENCE_INVALID','/definition')
 for tid in ag['key_types']+[ag['result_type']]+([ag['element_type']] if ag['element_type'] else []):
  if tid not in types: raise Refusal('REFERENCE_INVALID','/definition')
 for m in ag['mappings']:
  if any(t not in types for t in m['step_ids'] if False): _fail('REFERENCE_INVALID')
  for t in m['key_fields']:
   if not isinstance(t,str): _fail('REFERENCE_INVALID')
 def check_value(v, expected=None):
  if not isinstance(v,dict) or v.get('type_ref') not in types or (expected and v['type_ref']!=expected): _fail('TYPE_INVALID')
  t=types[v['type_ref']]; x=v.get('value')
  ok=(t['kind'] in ('STRING','IDENTITY') and isinstance(x,str) and (t['kind']!='IDENTITY' or x!='')) or (t['kind']=='BOOLEAN' and type(x) is bool)
  if t['kind']=='INTEGER': ok=isinstance(x,str) and re.fullmatch(r'-?(0|[1-9]\d*)',x) is not None and x!='-0' and (not t['nonnegative'] or not x.startswith('-'))
  if t['kind']=='DECIMAL':
   try: dec(x); ok=not x.startswith('-') if t['nonnegative'] else True
   except Exception: ok=False
  if not ok:_fail('TYPE_INVALID')
 for v,tid in [(ag['bound'],ag['result_type'])]: check_value(v,tid)
 def predicate(p, fs=None):
  k=p['kind']
  if k in ('BOOLEAN',): return
  if k in ('ALL','ANY'):
   for x in p['operands']: predicate(x,fs)
   return
  if k=='NOT': predicate(p['operand'],fs); return
  operands=[p['value']] if k=='MEMBER' else [p['left'],p['right']]
  vals=[]
  for x in operands:
   if x['kind']=='LITERAL': check_value(x['value']); vals.append(x['value'])
   elif x['kind']=='FIELD':
    if fs is not None:
     if x['name'] not in fs: _fail('INPUT_INVALID')
     vals.append(fs[x['name']])
  if k=='MEMBER':
   for x in p['members']: check_value(x)
  elif len(vals)==2 and (vals[0]['type_ref']!=vals[1]['type_ref'] or (k=='COMPARE' and self_kind(vals[0]) not in ('INTEGER','DECIMAL'))): _fail('TYPE_INVALID')
 def self_kind(v): return types[v['type_ref']]['kind']
 missing=False
 if ag.get('qualifier') is not None: predicate(ag['qualifier'])
 for m in ag['mappings']: predicate(m['qualifier'])
 if ag['committed_source']: predicate(ag['committed_source']['qualifier'])
 for o in a['operations']:
  if not _ordered(o['fields'],lambda x:x['name'].encode()) or len({f['name'] for f in o['fields']})!=len(o['fields']): _fail('INPUT_INVALID')
  for f in o['fields']: check_value(f['value'])
  fs={f['name']:f['value'] for f in o['fields']}
  for m in ag['mappings']:
   if o['step'] in m['step_ids']:
    for name in m['key_fields'] + ([m['contribution']['field']] if m['contribution']['kind']!='COUNT' else []):
     if name not in fs: missing=True
   predicate(m['qualifier'],fs)
 operation_ids=[o['occurrence'] for o in a['operations']]
 if len(operation_ids)!=len(set(operation_ids)) or not _ordered(operation_ids,lambda x:x.encode()): _fail('INPUT_INVALID')
 for p in a['pending']:
  if not (ag['pending_policy']=='INCLUDE_ALL_RESERVED'): _fail('INPUT_INVALID')
  if p['mapping'] not in {m['id'] for m in ag['mappings']}: _fail('INPUT_INVALID')
  if len(p['key'])!=len(ag['key_types']): _fail('TYPE_INVALID')
  for v,t in zip(p['key'],ag['key_types']): check_value(v,t)
  check_value(p['contribution'],ag['result_type'] if ag['reducer']!='CARDINALITY' else ag['element_type'])
 keys=[(p['reservation'],p['mapping'],p['occurrence'],canon(p['key'])) for p in a['pending']]
 if len(keys)!=len(set(keys)) or any(p['occurrence'] in {o['occurrence'] for o in a['operations']} for p in a['pending']): _fail('INPUT_INVALID')
 if not a['operations'] and a['observations']: _fail('INPUT_INVALID')
 # Validate supplied evidence before any clock-dependent decision.
 for ob in a['observations']:
  if ob.get('status')=='AVAILABLE':
   for s in (ob.get('coverage',{}).get('start'), ob.get('coverage',{}).get('end'), ob.get('as_of')):
    if s is not None:
     try: instant(s)
     except ValueError: _fail('INPUT_INVALID')
   for e in ob.get('events',[]):
    if e.get('state')=='ACTIVE':
     try: instant(e['occurred_at'])
     except (KeyError,ValueError): _fail('INPUT_INVALID')
    efs={f['name']:f['value'] for f in e.get('fields',[])}
    for f in e.get('fields',[]): check_value(f['value'])
    src=ag.get('committed_source')
    if src and e.get('state')=='ACTIVE':
     for name in src['key_fields'] + ([src['contribution']['field']] if src['contribution']['kind']!='COUNT' else []):
      if name not in efs: _fail('INPUT_INVALID')
     predicate(src['qualifier'],efs)
 if missing: _fail('INPUT_INVALID')
 if len(d['types'])>64 or len(ag['mappings'])>64 or len(a['operations'])>256: _fail('LIMIT_EXCEEDED')
 for o in a['operations']:
  for f in o['fields']:
   v=f['value']; t=types[v['type_ref']]
   if t['kind'] in ('INTEGER','DECIMAL') and len(v['value'].lstrip('-').replace('.',''))>128: _fail('LIMIT_EXCEEDED')
 for p in a['pending']:
  if len(p['contribution']['value'].lstrip('-').replace('.',''))>128: _fail('LIMIT_EXCEEDED')
 for t in types.values():
  for field in ('unit','id'):
   if isinstance(t.get(field),str) and len(t[field])>0: pass
 return types

def format_instant(ns, precision=9):
 sec,nano=divmod(ns,1000000000); d=dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)+dt.timedelta(seconds=sec)
 return d.strftime('%Y-%m-%dT%H:%M:%S') + (('.%09d'%nano) if precision==9 else '') + 'Z'

def calendar_interval(now, window, precision):
 z=zone(window['timezone'])
 local=dt.datetime.fromtimestamp(now//1000000000,dt.timezone.utc).astimezone(z); period=window['period']; y,m=local.year,local.month
 if period=='DAY': day=local.date()
 elif period=='WEEK': day=local.date()-dt.timedelta(days=(local.weekday()-['MONDAY','TUESDAY','WEDNESDAY','THURSDAY','FRIDAY','SATURDAY','SUNDAY'].index(window['week_start']))%7)
 elif period=='MONTH': day=local.date().replace(day=1)
 elif period=='QUARTER':
  anchor=int(window['fiscal_start_month']); q=((m-anchor)%12)//3; mm=((anchor-1+q*3)%12)+1; y=y if mm<=m or anchor<=m else y-1; day=dt.date(y,mm,1)
 else:
  anchor=int(window['fiscal_start_month']); y=y if m>=anchor else y-1; day=dt.date(y,anchor,1)
 naive=dt.datetime.combine(day,dt.time())
 candidates=[]
 for fold in (0,1):
  x=naive.replace(tzinfo=z,fold=fold); back=x.astimezone(dt.timezone.utc).astimezone(z).replace(tzinfo=None)
  if back==naive: candidates.append(x.astimezone(dt.timezone.utc).replace(tzinfo=None))
 if not candidates:
  if window['nonexistent']=='INVALID': _fail('INPUT_INVALID')
  gap=naive.replace(tzinfo=z,fold=1).utcoffset()-naive.replace(tzinfo=z,fold=0).utcoffset()
  naive += gap if window['nonexistent']=='SHIFT_FORWARD' else -gap
  x=naive.replace(tzinfo=z); start=x.astimezone(dt.timezone.utc).replace(tzinfo=None)
 elif len(set(candidates))>1:
  if window['ambiguous']=='INVALID': _fail('INPUT_INVALID')
  start=min(candidates) if window['ambiguous']=='EARLIER_OFFSET' else max(candidates)
 else: start=candidates[0]
 epoch=dt.datetime(1970,1,1)
 delta=start-epoch
 return (delta.days*86400+delta.seconds)*1000000000, now

class Eval:
 def __init__(self,a):
  self.a=a; self.d=a['definition']; self.ag=self.d['aggregate']; self.types={x['id']:x for x in self.d['types']}; self.ops={o['occurrence']:o for o in a['operations']}
 def tv(self,v): return self.types[v['type_ref']],v['value']
 def valid_value(self,v,tid=None):
  if not isinstance(v,dict) or set(v)!={'type_ref','value'} or v['type_ref'] not in self.types:return False
  if tid and v['type_ref']!=tid:return False
  t=self.types[v['type_ref']]; x=v['value']; k=t['kind']
  if k in ('STRING','IDENTITY'): return isinstance(x,str) and (k!='IDENTITY' or bool(x))
  if k=='BOOLEAN':return type(x) is bool
  if k=='INTEGER':
   try: return bool(re.fullmatch(r'-?(?:0|[1-9]\d*)',x)) and (not t['nonnegative'] or not x.startswith('-'))
   except: return False
  if k=='DECIMAL':
   try: dec(x); return (not t['nonnegative']) or not x.startswith('-')
   except: return False
  return False
 def fields(self,row): return {f['name']:f['value'] for f in row['fields']}
 def pred(self,p,fs):
  k=p['kind']
  if k=='BOOLEAN':return p['value']
  if k=='NOT':return not self.pred(p['operand'],fs)
  if k in ('ALL','ANY'):
   vals=[self.pred(x,fs) for x in p['operands']]; return all(vals) if k=='ALL' else any(vals)
  def op(x): return fs[x['name']] if x['kind']=='FIELD' else x['value']
  l=op(p.get('left',p.get('value')))
  if k=='MEMBER':return any(canon(l)==canon(x) for x in p['members'])
  r=op(p['right']); a,b=l['value'],r['value']
  if l['type_ref'] in self.types and self.types[l['type_ref']]['kind'] in ('INTEGER','DECIMAL'):
   a,b=Decimal(a),Decimal(b)
  if k=='EQUAL':return l['type_ref']==r['type_ref'] and a==b
  return {'LT':a<b,'LTE':a<=b,'GT':a>b,'GTE':a>=b}[p['operator']]
 def contributions(self):
  out=[]
  for oid,o in self.ops.items():
   fs=self.fields(o)
   for m in self.ag['mappings']:
    if o['step'] not in m['step_ids'] or not self.pred(m['qualifier'],fs):continue
    key=[fs[n] for n in m['key_fields']]
    cm=m['contribution']; val={'type_ref':self.ag['result_type'],'value':'1'} if cm['kind']=='COUNT' else fs[cm['field']]
    out.append((oid,m['id'],key,val,cm['kind']))
  return out
 def add(self,acc,val,kind):
  if kind=='CARDINALITY':
   vals=acc['values'][:]
   if not any(canon(x)==canon(val) for x in vals): vals.append(val)
   vals.sort(key=canon); return {'kind':'SET','values':vals}
  return {'kind':'SCALAR','value':exact_add(acc['value'],val['value'])}
 def evaluate(self):
  ag=self.ag; clock=self.a['clock']; contrib=self.contributions(); w=ag['window']
  if not contrib:return self.result([])
  if clock['status']=='UNAVAILABLE':
   ps=[{'occurrence':None if w['kind']!='PER_ACTION' else x[0],'key':x[1],'status':'INDETERMINATE','accumulator':None,'result':None,'reasons':['TIME_UNAVAILABLE']} for x in self.parts(contrib)]
   return self.result(ps)
  now=instant(clock['instant']); selected=contrib
  if w['kind']=='ROLLING':
   start=now-decimal_scaled(w['duration_seconds'],1000000000)
   # Proposal contributions have no occurrence time, so the proposal set is always included.
  elif w['kind']=='CALENDAR':
   start,_=calendar_interval(now,w,ag['time']['precision'])
  groups={}
  for c in selected: groups.setdefault((None if w['kind']!='PER_ACTION' else c[0],canon(c[2])),(None if w['kind']!='PER_ACTION' else c[0],c[2],[]))[2].append(c)
  history=[]; obs_reason=None
  if w['kind']=='PER_ACTION':
   if self.a['observations']: raise Refusal('INPUT_INVALID')
  else:
   end=now; precision=9 if ag['time']['precision']=='NANOSECOND' else 0
   interval={'start':format_instant(start,precision),'end':format_instant(end,precision),'start_inclusive':w.get('start_inclusive',True),'end_inclusive':w.get('end_inclusive',True)}
   keys=[]
   for candidate in sorted([c[2] for c in contrib],key=canon):
    if not any(canon(candidate)==canon(existing) for existing in keys): keys.append(candidate)
   query={'definition_digest':digest('aggregate-definition',self.a['definition']),'interval':interval,'keys':keys}
   qd=digest('aggregate-query',query)
   reports=[]
   for ob in self.a['observations']:
    if ob['request_digest']!=qd or ob['provider']!=ag['committed_source']['provider'] or ob['source']!=ag['committed_source']['source']: raise Refusal('INPUT_INVALID')
    if ob not in reports: reports.append(ob)
   if not reports: obs_reason='OBSERVATION_MISSING'
   elif len(reports)>1: obs_reason='OBSERVATION_CONFLICT'
   elif reports[0]['status']=='UNAVAILABLE': obs_reason='OBSERVATION_UNAVAILABLE'
   elif reports[0]['status']=='INCOMPLETE': obs_reason='OBSERVATION_INCOMPLETE'
   else:
    ob=reports[0]; asof=instant(ob['as_of'])
    if asof>now: raise Refusal('INPUT_INVALID')
    fresh=ag['committed_source']['freshness']
    if fresh['kind']=='EXACT_REVISION' and ob['revision']!=fresh['revision']: obs_reason='OBSERVATION_STALE'
    elif fresh['kind']=='MAX_AGE' and now-asof>decimal_scaled(fresh['seconds'],1000000000): obs_reason='OBSERVATION_STALE'
    cov=ob['coverage']; cs,ce=instant(cov['start']),instant(cov['end'])
    if ob['kind']=='STATISTIC' and (cs!=start or ce!=end or cov['start_inclusive']!=interval['start_inclusive'] or cov['end_inclusive']!=interval['end_inclusive']): raise Refusal('INPUT_INVALID')
    if ob['kind']=='EVENT_SNAPSHOT' and (cs>start or ce<end): obs_reason='OBSERVATION_INCOMPLETE'
    if obs_reason is None and ob['kind']=='EVENT_SNAPSHOT':
     seen={}
     for e in ob['events']:
      if e['id'] in seen and canon(seen[e['id']])!=canon(e): obs_reason='OBSERVATION_CONFLICT'; break
      seen[e['id']]=e
     for e in seen.values():
      if e['state']=='ACTIVE':
       t=instant(e['occurred_at'])
       lo=(t>start if not interval['start_inclusive'] else t>=start)
       hi=(t<end if not interval['end_inclusive'] else t<=end)
       if lo and hi: history.append((e,ob))
    elif obs_reason is None and ob['kind']=='STATISTIC':
     pass
  statmap={}
  for ob in self.a['observations']:
   if ob.get('status')=='AVAILABLE' and ob.get('kind')=='STATISTIC':
    statmap.update({canon(s['key']):s['accumulator'] for s in ob['statistics']})
  ps=[]
  pending_groups={}
  for p in self.a['pending']:
   pending_groups.setdefault((p['occurrence'] if w['kind']=='PER_ACTION' else None,canon(p['key'])),[]).append(p)
  for occ,key,cs in sorted(groups.values(),key=lambda x:canon({'occurrence':x[0],'key':x[1]})):
   if obs_reason:
    ps.append({'occurrence':occ,'key':key,'status':'INDETERMINATE','accumulator':None,'result':None,'reasons':[obs_reason]}); continue
   acc={'kind':'SET','values':[]} if ag['reducer']=='CARDINALITY' else {'kind':'SCALAR','value':'0'}
   kind=ag['reducer']
   if statmap and canon(key) in statmap:
    acc=statmap[canon(key)]
   for e,ob in history:
    fs=self.fields(e); cm=ag['committed_source']['contribution'] if ag['committed_source'] else None
    if cm and all(canon(fs[k])==canon(v) for k,v in zip(ag['committed_source']['key_fields'],key)) and self.pred(ag['committed_source']['qualifier'],fs):
     val={'type_ref':ag['result_type'],'value':'1'} if kind=='COUNT' else fs[cm['field']]; acc=self.add(acc,val,kind)
   for p in pending_groups.get((occ,canon(key)),[]):
    acc=self.add(acc,p['contribution'],kind)
   for c in cs: acc=self.add(acc,c[3],kind)
   n=len(acc['values']) if kind=='CARDINALITY' else Decimal(acc['value']); b=Decimal(ag['bound']['value']); ok={'LT':n<b,'LTE':n<=b,'GT':n>b,'GTE':n>=b}[ag['operator']]
   ps.append({'occurrence':occ,'key':key,'status':'SATISFIED' if ok else 'VIOLATED','accumulator':acc,'result':str(n) if kind=='CARDINALITY' else acc['value'],'reasons':[] if ok else ['BOUND_VIOLATED']})
  return self.result(ps)
 def parts(self,c):
  d={}
  for x in c:d.setdefault((None if self.ag['window']['kind']!='PER_ACTION' else x[0],canon(x[2])),(None if self.ag['window']['kind']!='PER_ACTION' else x[0],x[2]))
  return list(d.values())
 def result(self,ps):
  reasons=sorted({r for p in ps for r in p['reasons']})
  status='VIOLATED' if any(p['status']=='VIOLATED' for p in ps) else ('INDETERMINATE' if any(p['status']=='INDETERMINATE' for p in ps) else 'SATISFIED')
  return {'schema':SPEC+'/aggregate-result','specification_pin':PIN,'definition_digest':digest('aggregate-definition',self.a['definition']),'status':status,'partitions':ps,'reasons':reasons}
