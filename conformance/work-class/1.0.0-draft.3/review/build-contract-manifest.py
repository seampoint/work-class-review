#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parents[4]/'library/work-class-specification/1.0.0-draft.3'
include=[
 'README.md','SCOPE-AND-BOUNDARY.md','Specification.md','LIFECYCLE.md','COMPOSITION.md','PROTOCOL.md',
 'AUTHORITY.md','OBSERVATIONS-AND-DISPATCH.md','AUTHORITY-CHECKS.md','AGGREGATES.md','RESERVATIONS.md','RESERVATION-RECORDS.md',
 'EXCLUSIVE-KEY-HISTORY.md','INDEPENDENT-HUMAN-DECISIONS.md','COMPLETION-AND-REFERRALS.md','SOURCE-CORRECTIONS.md','RECOVERY.md','TIMING.md','HOLDINGS.md','ASSESSMENTS.md','INFORMATION-FLOW.md',
 'EXTERNAL-DEPENDENCIES.md','requirements.json','work-class.schema.json','lifecycle.schema.json',
 'authority.schema.json','aggregate.schema.json','reservation.schema.json','evidence.schema.json',
 'boundary.schema.json','protocol.schema.json','holdings.schema.json','information-flow.schema.json','schema-bundle.json'
]
files=[]
for rel in sorted(include):
 data=(root/rel).read_bytes()
 files.append({'path':rel,'sha256':hashlib.sha256(data).hexdigest()})
manifest={'claim_ceiling':'APPARATUS_ONLY','files':files,'identity':'seampoint.work-class/1.0.0-draft.3','status':'DRAFT_NOT_ADOPTED'}
path=root/'contract-manifest.json'
path.write_text(json.dumps(manifest,indent=2)+'\n')
pin='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
expected=Path(__file__).with_name('EXPECTED-JUDGMENTS-CONTRACT.json')
d=json.loads(expected.read_text()); d['candidate_pin']=pin; expected.write_text(json.dumps(d,indent=2)+'\n')
print(json.dumps({'manifest':str(path),'files':len(files),'specification_pin':pin},indent=2))
