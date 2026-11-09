#!/usr/bin/env python3
"""Read frozen CDMO artifacts and compare both consumers without editing oracles."""
from __future__ import annotations
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]
ROOT=BASE.parents[2]
sys.path.insert(0,str(BASE/'runner'))
from transport import invoke,PROTOCOL,run_captured
CONSUMERS={'python':[sys.executable,'-B',str(BASE/'python/adapter.py')], 'typescript':['node',str(BASE/'typescript/adapter.ts')]}


def load(path):return json.loads(path.read_bytes())
def sha(path):return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
def sha_value(value):
    if isinstance(value,set):value=sorted(value)
    return 'sha256:'+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    checks=[]
    def check(name,actual,expected):
        row={'name':name,'passed':actual==expected}
        if not row['passed']:row.update(actual_digest=sha_value(actual),expected_digest=sha_value(expected))
        checks.append(row)
    pin=sha(ROOT/'library/work-class-specification/1.0.0-draft.3/contract-manifest.json')
    index=load(HERE/'artifact-index.json');check('current contract pin',index['candidate_pin'],pin)
    for row in index['artifacts']:check('artifact:'+row['path'],sha(HERE/row['path']),row['sha256'])
    check('source bytes',(HERE/'source-packet.md').read_text(),(BASE/'review/fixtures/pharmaceutical-batch-disposition-revision3-source.md').read_text())
    singles=[('authority','evaluate',{'kind':'AUTHORITY','request':load(HERE/'authority-input.json')},load(HERE/'authority-result-derived.json')),
        ('readback','readback',{'kind':'WORK_CLASS','specification_pin':pin,'artifact_bytes_base64':base64.b64encode((HERE/'work-class.json').read_bytes().rstrip(b'\n')).decode()},load(HERE/'readback-derived.json'))]
    singles.append(('source-correspondence','check-evidence',load(HERE/'correspondence-input.json'),load(HERE/'correspondence-result-derived.json')))
    for label in ['business','metadata']:
        singles.append(('correction-'+label,'check-evidence',load(HERE/'correction'/ (label+'-input.json')),load(HERE/'correction'/(label+'-result-derived.json'))))
    for name,operation,supplied,expected in singles:
        for language,command in CONSUMERS.items():
            actual=invoke(command,name,operation,supplied,120,64*1024*1024,str(ROOT));check(name+':'+language,actual,expected)
    trace_groups=[]
    for path in sorted(HERE.rglob('requests.jsonl')):
        name=str(path.parent.relative_to(HERE));trace_groups.append(name)
        requests=[json.loads(row) for row in path.read_bytes().splitlines()];expected=load(path.parent/'results-derived.json')
        check(name+':count',len(requests),len(expected));payload=path.read_bytes()
        def stream(item):
            language,command=item;process=run_captured(command,payload,cwd=ROOT,timeout=300)
            if process.returncode:raise RuntimeError(language+': '+process.stderr.decode('utf-8','replace')[-1000:])
            responses=[json.loads(row) for row in process.stdout.splitlines()]
            wanted=[{'protocol':PROTOCOL,'request_id':request['request_id'],'operation':request['operation'],'result':result} for request,result in zip(requests,expected,strict=True)]
            return language,responses,wanted
        outputs={}
        with ThreadPoolExecutor(max_workers=2) as executor:
            for language,responses,wanted in executor.map(stream,CONSUMERS.items()):
                check(name+':'+language+':stream',responses,wanted);outputs[language]=responses
        check(name+':cross-language',outputs['python'],outputs['typescript'])
        for request,result in zip(requests,expected,strict=True):
            for language,command in CONSUMERS.items():
                actual=invoke(command,request['request_id'],request['operation'],request['input'],120,64*1024*1024,str(ROOT))
                check(name+':'+language+':fresh:'+request['request_id'],actual,result)
        if name=='valid-trace':
            check('final work state',expected[-1]['state'],load(HERE/'valid-trace/final-work-state.json'))
            check('final registry state',expected[-1]['budget_results'][0]['result']['state'],load(HERE/'valid-trace/final-registry-state.json'))
    inventory=load(HERE/'case-inventory.json');ids={row['id'] for row in inventory['cases']}
    for row in inventory['cases']:check('case bytes:'+row['id'],sha(HERE/row['path']),row['raw_sha256'])
    coverage=load(HERE/'source-coverage.json');obligations=load(HERE/'normalized-obligations.json')['obligations']
    check('complete obligation inventory',sorted(row['source_obligation_id'] for row in coverage['coverage']),sorted(row['id'] for row in obligations))
    for row in coverage['coverage']:
        check('coverage cases:'+row['source_obligation_id'],set(row['case_ids'])<=ids,True)
        for path in row['artifact_paths']:check('coverage artifact:'+row['source_obligation_id']+':'+path,(HERE/path).is_file(),True)
    check('original correction history retained',load(HERE/'original-batch-disposition-history.json'),load(HERE/'correction/business-input.json')['original_record'])
    correspondence=load(HERE/'correspondence-record.json');paths={row['path'] for row in load(HERE/'readback-derived.json')['lines']}
    mapped={path for row in correspondence['mappings'] for path in row['provision_paths']};unsupported=set(correspondence['unsupported_provision_paths'])
    check('readback path coverage',mapped|unsupported,paths);check('no mapped/residue overlap',mapped&unsupported,set())
    check('source review remains pending',correspondence['review']['status'],'PENDING')
    passed=sum(row['passed'] for row in checks)
    print(json.dumps({'candidate_pin':pin,'status':'PASS' if passed==len(checks) else 'FAIL','qualification':'DEVELOPMENT_RUN_NOT_QUALIFYING',
        'checks':len(checks),'passed':passed,'failed':len(checks)-passed,'source_cases':len(ids),'source_obligations':len(obligations),
        'trace_groups':trace_groups,'results':checks},indent=2))
    return 0 if passed==len(checks) else 1
if __name__=='__main__':raise SystemExit(main())
