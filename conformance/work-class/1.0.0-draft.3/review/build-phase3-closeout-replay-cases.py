#!/usr/bin/env python3
"""Exact replay expectations derived from sealed closeout transitions, never actual output."""
import copy,json
from corpus_common import CASES,canonical_bytes,candidate_pin,digest,exact_case,write_canonical_json

def main():
 group=CASES / 'phase3-closeout-replay';group.mkdir(parents=True,exist_ok=True);ids=[]
 for source in sorted((CASES / 'phase3-dispose-closeout').glob('*.json')):
  row=json.loads(source.read_text());prior=row['expected']
  if prior['status']!='TRANSITION':continue
  supplied=copy.deepcopy(row['input']);supplied['state']=copy.deepcopy(prior['state']);supplied['state_digest']=digest('reservation-state',supplied['state'])
  expected=copy.deepcopy(prior);expected['replay']=True
  cid=f'C3-P3-REPLAY-{len(ids)+1:03d}';ids.append(cid)
  write_canonical_json(group/(cid+'.json'),exact_case(cid,'aggregate-step',supplied,expected,['REC-002','RES-003','RES-WIRE-004'],'Exact replay after '+row['id']+'. RES-003/REC-002 recognize the original event before its stale expected revision; return historical receipt, current state and replay:true with no repeated charge, allowance, disposition or revision. The request checkpoint and expected result derive from the presealed source expectation, not consumer output.'))
 print(json.dumps({'candidate_pin':candidate_pin(),'cases':len(ids)},indent=2))

if __name__=='__main__':main()
