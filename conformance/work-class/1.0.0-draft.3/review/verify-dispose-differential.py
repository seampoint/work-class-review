#!/usr/bin/env python3
"""Reproduce the retained DISPOSE matrix with bounded batches and strict raw capture.

Agreement is a differential diagnostic, not conformance, production qualification
or authority. Appends sealed closeout cases and corrected retained-attempt limits.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,os,shutil,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import dispose_sweep_inputs as fixtures
from corpus_common import canonical_bytes,candidate_pin,digest
HERE=Path(__file__).resolve().parent;AREA=HERE.parent
sys.path.insert(0,str(AREA/'runner'))
from transport import PROTOCOL,read_json,run_captured


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path);parser.add_argument('--batch-size',type=int,default=128);parser.add_argument('--workers',type=int,default=4);parser.add_argument('--limit',type=int,default=0);parser.add_argument('--only-supplements',action='store_true')
 args=parser.parse_args();out=args.output.resolve()
 if out.exists():parser.error('use a fresh output directory')
 if args.batch_size<1 or args.workers<1:parser.error('positive batch size/workers required')
 out.mkdir(parents=True);os.environ['WORK_CLASS_CHILD_CAPTURE_DIR']=str(out/'raw')
 commands={'py':[sys.executable,str(AREA/'python/adapter.py')],'ts':[os.environ.get('WORK_CLASS_NODE') or shutil.which('node'),str(AREA/'typescript/adapter.ts')]}
 if not commands['ts'][0]:parser.error('node is unavailable')
 def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
 # Bind transitive source constructors, their documentary fixtures, all selected
 # inputs and both complete consumers, not only the two transport entry points.
 directories=[AREA.parents[2]/'library/work-class-specification/1.0.0-draft.3',
              AREA/'python',AREA/'typescript',AREA/'cases',AREA/'specimens',
              AREA/'review',AREA/'runner',AREA/'suite']
 guarded=sorted({p for directory in directories for p in directory.rglob('*')
                 if p.is_file() and not {'node_modules','__pycache__'}.intersection(p.parts)
                 and not any(p.is_relative_to(HERE/name) for name in ['paper','records'])})
 guarded += [Path(command[0]).resolve() for command in commands.values()]
 before={str(p):sha(p) for p in guarded};(out/'guard-before.json').write_text(json.dumps(before,indent=2)+'\n')
 def run(requests,lang):
  payload=b''.join(canonical_bytes({'protocol':PROTOCOL,'request_id':'s-'+str(i),'operation':'aggregate-step','input':r})+b'\n' for i,r in enumerate(requests))
  result=run_captured(commands[lang],payload,cwd=str(AREA),timeout=1200,new_session=True)
  if result.returncode:raise RuntimeError(f'{lang} nonzero exit {result.returncode}')
  if len(result.stdout)>268435456:raise RuntimeError('batch output exceeds 256 MiB')
  lines=result.stdout.splitlines()
  if len(lines)!=len(requests):raise RuntimeError(f'{lang} output line count mismatch')
  outputs=[]
  for i,line in enumerate(lines):
   envelope=read_json(line.decode())
   if canonical_bytes(envelope)!=line or envelope.get('protocol')!=PROTOCOL or envelope.get('request_id')!='s-'+str(i) or envelope.get('operation')!='aggregate-step':raise RuntimeError(f'{lang} noncanonical or mismatched envelope')
   if set(envelope)!={'protocol','request_id','operation','result'}:raise RuntimeError(f'{lang} unexpected envelope fields')
   outputs.append(envelope['result'])
  return outputs
 fixtures.run=run;priors=fixtures.priors()
 def inputs():
  # The historical pending slice has extra fields forbidden by its closed schema.
  # Preserve it below, and separately admit the intended pending identities.
  for key,state in fixtures.matrix(priors):
   if key[0]!='pending':continue
   value=fixtures.build(state,*key[1:])
   if value is None:continue
   evidence=value['event']['payload']['evidence']
   known={a['id']:a for row in state['core']['recovery']['dispositions'] for a in row['evidence']['attempts']}
   current={a['id']:a for a in evidence['attempts']}
   for identity,attempt in known.items():current.setdefault(identity,copy.deepcopy(attempt))
   evidence['attempts']=sorted(current.values(),key=lambda a:a['id'])
   pending=value['host_evidence']['recovery']['pending_evidence'][0]
   if key[-1]=='packet':pending['record_digest']=digest('recovery-evidence',evidence)
   value['host_evidence']['recovery']['pending_evidence']=[{name:pending[name] for name in ['target','record_digest']}]
   fixtures.rec.refresh_authentication(fixtures.facts,value)
   yield 'corrected-pending|'+fixtures.key(key[1:]),value
  for key,state in fixtures.matrix(priors):
   if args.only_supplements:break
   value=fixtures.build(state,*key[1:])
   if value is not None:yield fixtures.key(key),value
  # Correct the retained-attempt omission in the old limits slice without rewriting it.
  for pname in ['P3-after-accept','P4-after-leave']:
   state=priors[pname]
   for result in ['ESTABLISH_EFFECT','ESTABLISH_NO_EFFECT','ACCEPT_UNRESOLVED','LEAVE_UNRESOLVED']:
    for count in ['max4096','max4097','max5000','max100000000000000000000']:
     for complete in [True,False]:
      value=fixtures.build(state,pname,result,{'ESTABLISH_EFFECT':'EFFECT_ESTABLISHED','ESTABLISH_NO_EFFECT':'NO_EFFECT_ESTABLISHED'}.get(result,'UNRESOLVED'),result=='ESTABLISH_NO_EFFECT',complete,count,'none','all','base','none',eid='corrected-limit')
      evidence=value['event']['payload']['evidence'];known={a['id']:a for row in state['core']['recovery']['dispositions'] for a in row['evidence']['attempts']}
      current={a['id']:a for a in evidence['attempts']}
      for identity,attempt in known.items():current.setdefault(identity,copy.deepcopy(attempt))
      evidence['attempts']=sorted(current.values(),key=lambda a:a['id'])
      fixtures.rec.refresh_authentication(fixtures.facts,value)
      yield f'corrected-limits|{pname}|{result}|{count}|{complete}',value
  for group in ['phase3-dispose-closeout','phase3-closeout-boundaries','phase3-closeout-replay','phase3-review-findings','phase3-mixed-history','phase3-disputed-history','phase3-pending-identity','phase3-mixed-exclusive-history','phase3-unassessed-actual']:
   for path in sorted((AREA/'cases'/group).glob('*.json')):
    case=json.loads(path.read_text());yield 'sealed|'+case['id'],case['input']
 def batches():
  chunk=[];n=0
  for pair in inputs():
   if args.limit and n>=args.limit:break
   chunk.append(pair);n+=1
   if len(chunk)==args.batch_size:yield chunk;chunk=[]
  if chunk:yield chunk
 def assess(chunk):
  requests=[value for _,value in chunk]
  return chunk,run(requests,'py'),run(requests,'ts')
 started=time.monotonic();total=equal=0;diffs=[];slices={};accepted={'py':0,'ts':0};outcomes={'py':{},'ts':{}}
 try:
  with (out/'inputs.jsonl').open('wb') as stimuli,(out/'results.jsonl').open('wb') as results,ThreadPoolExecutor(max_workers=args.workers) as pool:
   # Keep at most workers batches resident; do not materialize the full 9 GB matrix.
   iterator=iter(batches());pending=[]
   for _ in range(args.workers):
    chunk=next(iterator,None)
    if chunk:pending.append(pool.submit(assess,chunk))
   while pending:
    chunk,pys,tss=pending.pop(0).result()
    for (key,value),py,ts in zip(chunk,pys,tss):
     same=canonical_bytes(py)==canonical_bytes(ts);total+=1;equal+=int(same)
     bucket=key.split('|')[0];slices[bucket]=slices.get(bucket,0)+1
     for lang,actual in [('py',py),('ts',ts)]:
      label=actual.get('code') or actual.get('receipt',{}).get('decision') or actual.get('status','UNKNOWN_RESULT')
      counts=outcomes[lang].setdefault(bucket,{})
      counts[label]=counts.get(label,0)+1
     if not same:diffs.append(key)
     for lang,actual in [('py',py),('ts',ts)]:accepted[lang]+=int(actual.get('receipt',{}).get('decision')=='DISPOSITION_RECORDED' and actual.get('state',{}).get('core',{}).get('recovery',{}).get('dispositions',[{}])[-1].get('result')=='ACCEPT_UNRESOLVED')
     stimuli.write(json.dumps({'key':key,'input':value},separators=(',',':')).encode()+b'\n')
     results.write(json.dumps({'key':key,'same':same,'py':py,'ts':ts},separators=(',',':')).encode()+b'\n')
    print(json.dumps({'processed':total,'different':len(diffs),'elapsed_seconds':round(time.monotonic()-started,1)}),flush=True)
    chunk=next(iterator,None)
    if chunk:pending.append(pool.submit(assess,chunk))
  after={str(p):sha(p) for p in guarded};(out/'guard-after.json').write_text(json.dumps(after,indent=2)+'\n')
  report={'status':'PASS' if not diffs and before==after else 'FAIL','claim':'DIFFERENTIAL_DIAGNOSTIC_NOT_QUALIFICATION','pin':candidate_pin(),'original_matrix_included':not args.only_supplements,'historical_input_bytes_replayed':False,'input_limit':args.limit,'total':total,'equal':equal,'differing':len(diffs),'difference_keys':diffs,'slices':slices,'outcomes_by_slice':outcomes,'accepted_exception_observations':accepted,'source_guard_unchanged':before==after,'files':{name:sha(out/name) for name in ['inputs.jsonl','results.jsonl']}}
 except Exception as error:
  report={'status':'FAIL','failure':str(error),'completed':total,'different_so_far':len(diffs),'pin':candidate_pin()}
 (out/'SUMMARY.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0 if report['status']=='PASS' else 1

if __name__=='__main__':sys.exit(main())
