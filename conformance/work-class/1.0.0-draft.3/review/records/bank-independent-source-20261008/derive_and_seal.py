#!/usr/bin/env python3
"""Regenerate all complete source-derived expectations without loading consumers.

The input directory contains INPUT-FREEZE-01.json, inputs/ and sources/. Inputs
must contain only id/operation/input/requirements; expected/derivation are absent.
"""
import argparse,datetime,hashlib,json,os,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input-root',type=pathlib.Path,default=HERE)
parser.add_argument('--contract-root',type=pathlib.Path,default=HERE.parents[2]/'library/work-class-specification/1.0.0-draft.3')
parser.add_argument('--vendor-root',type=pathlib.Path,default=HERE.parents[2]/'conformance/work-class/1.0.0-draft.3/python/vendor')
parser.add_argument('--output-root',type=pathlib.Path)
parser.add_argument('--seal',action='store_true',help='Write SEAL-01.json after complete derivation and shape validation.')
args=parser.parse_args()
args.input_root=args.input_root.resolve();args.contract_root=args.contract_root.resolve();args.vendor_root=args.vendor_root.resolve();args.output_root=(args.output_root or args.input_root/'expected').resolve()
os.environ['BANK_ORACLE_INPUT_ROOT']=str(args.input_root);os.environ['BANK_ORACLE_CONTRACT_ROOT']=str(args.contract_root);os.environ['BANK_ORACLE_VENDOR_ROOT']=str(args.vendor_root)
sys.path.insert(0,str(HERE))
from independent_common import canon,digest,shape,PIN
from independent_authority import authority
from independent_holdings import holdings
from independent_flow import flow
from independent_lifecycle import lifecycle

def rawhash(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_json(path,value):path.write_bytes(canon(value))
freeze=json.loads((args.input_root/'INPUT-FREEZE-01.json').read_text())
assert freeze['candidate_pin']==PIN
assert 'sha256:'+rawhash(args.contract_root/'contract-manifest.json')==PIN
assert len(freeze['cases'])==54
for name,expected_hash in freeze['sources'].items():assert rawhash(args.input_root/'sources'/name)==expected_hash,name
args.output_root.mkdir(parents=True,exist_ok=True)
records=[];counts={};derivations=[]
common_citations=['Specification.md:WCS2-001..004','PROTOCOL.md:WCS2-013..014']
operation_citations={
 'holdings-step':['HOLDINGS.md:HOLD-001..005'],
 'flow-step':['INFORMATION-FLOW.md:FLOW-001..003,006..008','AUTHORITY.md:AUTH-001..007','AUTHORITY-CHECKS.md:Exact successful check construction'],
 'evaluate':['AUTHORITY.md:AUTH-001..007','AUTHORITY-CHECKS.md:Admission phases and check construction','INDEPENDENT-HUMAN-DECISIONS.md:AUTH-008..009','HOLDINGS.md:HOLD-006','INFORMATION-FLOW.md:FLOW-004..008','ASSESSMENTS.md:ASSESS-001..006','OBSERVATIONS-AND-DISPATCH.md:1..4'],
 'deploy':['LIFECYCLE.md:LIFE-001..004','Specification.md:WCS2-005'],
 'step':['LIFECYCLE.md:LIFE-005..010,019','INDEPENDENT-HUMAN-DECISIONS.md:LIFE-009B','COMPLETION-AND-REFERRALS.md:STOP_RETAIN','AUTHORITY.md:AUTH-001..007','AUTHORITY-CHECKS.md:Admission phases and check construction','HOLDINGS.md:HOLD-006..007','INFORMATION-FLOW.md:FLOW-004..007','ASSESSMENTS.md:ASSESS-001..006','TIMING.md:TIME-006'],
}
for row in freeze['cases']:
 path=args.input_root/row['input_path'];assert rawhash(path)==row['input_sha256'],row['id'];case=json.loads(path.read_text());assert set(case)=={'id','operation','input','requirements'};assert case['id']==row['id']and case['operation']==row['operation']
 operation=case['operation'];i=case['input']
 if operation=='evaluate':result=authority(i['request']);shape('authority','result'if result['status']=='READY_FOR_RESERVATION'else'refusal',result)
 elif operation=='holdings-step':result=holdings(i);shape('holdings','result'if result['status']=='TRANSITION'else'refusal',result)
 elif operation=='flow-step':result=flow(i);shape('information-flow','result'if result['status']=='TRANSITION'else'refusal',result)
 else:
  result=lifecycle(i,operation);shape('lifecycle','deployResult'if result['status']=='DEPLOYED'else'stepResult'if result['status']=='STEP'else'statefulRefusal',result)
 output=args.output_root/(case['id']+'.json');write_json(output,result)
 records.append(dict(id=case['id'],operation=operation,input_path=row['input_path'],input_sha256=row['input_sha256'],expected_path=output.name,expected_sha256=rawhash(output),expected_canonical_bytes=str(len(output.read_bytes()))))
 counts[operation]=str(int(counts.get(operation,'0'))+1)
 derivations.append(dict(id=case['id'],requirements=case['requirements'],normative_citations=common_citations+operation_citations[operation],source_citations=sorted(freeze['sources']),method='Complete deterministic source formulas. Historical states are reconstructed from retained complete events and independently recomputed authority preimages before current reliance.'))
 print(case['id']+' complete '+result['status'],flush=True)
write_json(args.output_root/'EXPECTED-HASHES-01.json',dict(candidate_pin=PIN,case_count=str(len(records)),operations=counts,cases=records))
write_json(args.output_root/'DERIVATIONS-01.json',dict(candidate_pin=PIN,cases=derivations))
imports={}
for name,module in sorted(sys.modules.items()):
 filename=getattr(module,'__file__',None)
 if filename:
  path=pathlib.Path(filename).resolve()
  if args.vendor_root in path.parents and path.is_file():imports[str(path.relative_to(args.vendor_root))]=rawhash(path)
write_json(args.output_root/'MECHANICAL-DEPENDENCIES-01.json',dict(purpose='JSON Schema shape validation only. No consumer modules or bootstrap code.',vendor_files=imports))
if args.seal:
 constructors={name:rawhash(HERE/name)for name in ['derive_and_seal.py','independent_common.py','independent_authority.py','independent_holdings.py','independent_flow.py','independent_lifecycle.py']}
 notes={name:rawhash(HERE/name)for name in ['PROVENANCE-01.md','independent-lifecycle-notes.md']}
 seal=dict(schema='bank-independent-source-seal/1',sealed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),candidate_pin=PIN,authors=['/root/bank_independent_oracles','/root/bank_independent_oracles/lifecycle_oracles'],input_freeze_sha256=rawhash(args.input_root/'INPUT-FREEZE-01.json'),sources=freeze['sources'],normative_files={p.name:rawhash(p)for p in sorted(args.contract_root.iterdir())if p.is_file()},constructors=constructors,provenance_notes=notes,expected_inventory_sha256=rawhash(args.output_root/'EXPECTED-HASHES-01.json'),derivations_sha256=rawhash(args.output_root/'DERIVATIONS-01.json'),mechanical_dependencies_sha256=rawhash(args.output_root/'MECHANICAL-DEPENDENCIES-01.json'),case_count=str(len(records)),operations=counts,independence='Complete expectations authored from frozen input-only records, selected normative contract and fictional business sources. Neither consumer nor existing expectation/actual/result-derived constructor was consulted. Retained prior-state proofs were validated from normative formulas, as permitted inputs. No comparison occurred before this seal.',original_corpus_provenance='Unchanged. This successor expectation set does not retroactively make original TypeScript-implementer expectations independent.',interpretive_uncertainty='No unresolved wire rule prevents construction of these 54 full results. Host/provider authenticity, truth, historical permission eligibility assertion, source fidelity, all-writer mediation and real native acceptance remain outside mechanical conformance.')
 write_json(args.output_root/'SEAL-01.json',seal)
 print('SEALED '+rawhash(args.output_root/'SEAL-01.json'),flush=True)
