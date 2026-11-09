"""Fresh source formulas: Specification WCS2-001/002/003. No consumer imports."""
import base64,copy,datetime,hashlib,json,pathlib,re,sys,os
from decimal import Decimal
BASE=pathlib.Path(os.environ.get('BANK_ORACLE_INPUT_ROOT',pathlib.Path(__file__).resolve().parent)).resolve()
NORM=pathlib.Path(os.environ.get('BANK_ORACLE_CONTRACT_ROOT',BASE.parents[2]/'library/work-class-specification/1.0.0-draft.3')).resolve()
VENDOR=pathlib.Path(os.environ.get('BANK_ORACLE_VENDOR_ROOT',NORM.parents[2]/'conformance/work-class/1.0.0-draft.3/python/vendor')).resolve()
sys.path.insert(0,str(VENDOR))
PREFIX='seampoint.work-class/1.0.0-draft.3/'
PIN='sha256:120242f6e3a9cc67348932386460144ace5924d9b02852b878093b74a7af82a3'
def canon(v):
 def ordered(x):
  if isinstance(x,dict): return {k:ordered(x[k]) for k in sorted(x,key=lambda k:k.encode('utf-16-be'))}
  if isinstance(x,list): return [ordered(a) for a in x]
  if isinstance(x,(int,float)) and not isinstance(x,bool): raise ValueError('number token')
  return x
 return json.dumps(ordered(v),ensure_ascii=False,separators=(',',':')).encode()
def digest(kind,v):return 'sha256:'+hashlib.sha256((PREFIX+kind+'\n').encode()+canon(v)).hexdigest()
def clone(v):return copy.deepcopy(v)
def sorted_set(rows):return [json.loads(x) for x in sorted(set(canon(r) for r in rows))]
def fields(rows):return {r['name']:r['value'] for r in rows}
def instant(s):
 if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',s):raise ValueError('instant')
 return datetime.datetime.strptime(s,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
def active(interval,at):return interval['valid_from']<=at and (interval['valid_until'] is None or at<interval['valid_until'])
def add_seconds(t,s):return (instant(t)+datetime.timedelta(seconds=int(s))).strftime('%Y-%m-%dT%H:%M:%SZ')
def refusal(code,**extra):return dict(status='REFUSED',code=code,path='',**extra)
def authority_refusal(code,reasons=(),failed_checks=(),**extra):return refusal(code,reasons=sorted(set(reasons)),failed_checks=sorted_set(failed_checks),**extra)
def assert_same(a,b,label):
 if canon(a)!=canon(b):raise ValueError(label)
def shape(name,definition,value):
 import jsonschema
 from referencing import Registry,Resource
 documents={p.name:json.loads(p.read_text()) for p in NORM.glob('*.schema.json')}
 registry=Registry()
 for document in documents.values():registry=registry.with_resource(document['$id'],Resource.from_contents(document))
 doc=documents[name+'.schema.json'];schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$ref':doc['$id']+'#/$defs/'+definition}
 jsonschema.Draft202012Validator(schema,registry=registry).validate(value)
