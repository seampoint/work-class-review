#!/usr/bin/env python3
"""Build the CDMO source package and complete author-derived expected bytes."""
from __future__ import annotations
import hashlib
import json
import runpy
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
REVIEW=HERE.parents[1]/'review'
sys.path.insert(0,str(REVIEW))
from corpus_common import candidate_pin,canonical_bytes,digest,write_canonical_json
from cdmo_fixture import SOURCE_PATH,SCHEMA,dossier_records,cdmo_correction


def sha(path):
    return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,value):
    write_canonical_json(HERE/path,value)


def trace(name,rows):
    requests=[{'protocol':'seampoint.work-class.adapter/1.0.0-draft.3','request_id':row['id'],'operation':row['operation'],'input':row['input']} for row in rows]
    results=[row['expected'] for row in rows]
    write(name+'/requests.json',requests);write(name+'/results-derived.json',results)
    for filename,values in [('requests.jsonl',requests),('results-derived.jsonl',results)]:
        (HERE/name/filename).write_bytes(b''.join(canonical_bytes(row)+b'\n' for row in values))
    write(name+'/expectations.json',{'candidate_pin':candidate_pin(),'status':'AUTHOR_DERIVED_NOT_CONSUMER_VERIFIED','case_ids':[row['id'] for row in rows],
        'operation_count':str(len(rows)),'expected_digest':digest('cdmo-source-trace-results',results)})


def source_mapping(base,readback):
    obligations=json.loads((HERE/'normalized-obligations.json').read_bytes())['obligations']
    paths=[row['path'] for row in readback['lines']]
    prefixes={'00':['/steps/0/authority_requirements','/steps/0/dispatch_gate'], '10':[], '01':['/steps/0/interface','/steps/0/operation','/steps/0/referral_policy'],
        '02':['/steps/0/fields','/steps/0/scope_fields','/steps/0/completion/evidence_bindings'],
        '03':['/steps/0/authority_requirements','/steps/0/executor_role','/steps/0/required_credentials','/steps/0/completion/correction_policy/business_decision_requirements'],
        '04':['/steps/0/authority_requirements'],
        '05':['/steps/0/authority_requirements','/steps/0/dispatch_gate','/steps/0/completion/correction_policy/business_decision_requirements'],
        '06':['/steps/0/dispatch_gate','/steps/0/exclusive_keys','/steps/0/quantity_mode','/steps/0/fields'],
        '07':['/steps/0/completion','/steps/0/referral_policy/completion'],
        '08':['/steps/0/completion/correction_policy','/steps/0/referral_policy'], '09':[]}
    mappings=[];residue=[];coverage=[]
    for row in obligations:
        mapped=[path for path in paths if any(path==prefix or path.startswith(prefix+'/') for prefix in prefixes[row['source_heading']])]
        if row['kind']=='SELECTED_POLICY' and mapped:
            mappings.append({'source_obligation_id':row['id'],'provision_paths':mapped})
            status='MAPPED_WITH_EXPLICIT_EXTERNAL_AUTHORITY_AND_HOST_PREMISES'
        else:
            residue.append({'kind':'SOURCE_OBLIGATION','subject':row['id'],'disposition':'EXCLUDED' if row['kind']=='HOST_PREMISE' else 'PENDING',
                'explanation':row['text']+' The source package retains this obligation without claiming the work-class definition proves it.'})
            status=row['kind']
        heading=row['source_heading']
        families={'00':['authority-positive','readback'],'10':[],'01':['readback'],'02':['valid-trace','native-mismatch'],'03':['authority-positive','leaf-current-failures','admission'],
            '04':['source-propose','source-dispatch'],'05':['authority-positive','leaf-current-failures','source-propose','source-dispatch'],
            '06':['valid-trace','source-propose','source-dispatch'],'07':['native-missing','native-mismatch','lookup','replay','late-evidence'],
            '08':['correction','correction-negative'],'09':[]}[heading]
        coverage.append({'source_obligation_id':row['id'],'source_heading':heading,'kind':row['kind'],'status':status,
            'source_text_digest':digest('cdmo-source-clause',row['text']),'binding':row['text'],
            'artifact_paths':sorted(['source-packet.md','authority-input.json','work-class.json','provider-premises.json']+
                (['correction/business-input.json'] if heading=='08' else [])), 'case_families':families})
    mapped_paths={path for row in mappings for path in row['provision_paths']}
    unsupported=sorted(set(paths)-mapped_paths,key=lambda value:value.encode())
    residue += [{'kind':'ARTIFACT_PROVISION','subject':path,'disposition':'UNSUPPORTED',
        'explanation':'The selected source does not specify this representation or finite execution detail.'} for path in unsupported]
    record={'schema':SCHEMA+'evidence-record','evidence_id':'cdmo-source-correspondence','kind':'CORRESPONDENCE','status':'PENDING',
        'subject_digest':base['definition_digest'],'source_id':base['authority_input']['source']['id'],'source_revision':base['authority_input']['source']['revision'],
        'work_class_digest':base['definition_digest'],'mappings':mappings,'uncovered_source_obligation_ids':sorted(row['subject'] for row in residue if row['kind']=='SOURCE_OBLIGATION'),
        'unsupported_provision_paths':unsupported,'residue':sorted(residue,key=lambda row:(row['kind'],row['subject'])),'recorded_at':'2026-10-07T12:00:00Z',
        'provenance_digest':digest('evidence-provenance',{'evidence_id':'cdmo-source-correspondence'})}
    record['review']={'schema':SCHEMA+'evidence-record','evidence_id':'cdmo-source-correspondence-review','kind':'REVIEW','status':'PENDING',
        'subject_digest':digest('correspondence-subject',record),'reviewer_id':'pending-independent-source-review','paragraph_ids':[], 'case_ids':[], 'finding_ids':[],
        'recorded_at':'2026-10-07T12:00:00Z','provenance_digest':digest('evidence-provenance',{'evidence_id':'cdmo-source-correspondence-review'})}
    return record,coverage


def main():
    builder=runpy.run_path(str(REVIEW/'build-cdmo-source-cases.py'))
    cases,groups,facts=builder['construct_cases']();base=facts['base']
    for row in cases:write_canonical_json(builder['GROUP']/(row['id']+'.json'),row)
    write_canonical_json(builder['GROUP']/'index.json',{'group':'cdmo-source','status':'AUTHOR_DERIVED_NOT_CONSUMER_VERIFIED','candidate_pin':candidate_pin(),'case_ids':[row['id'] for row in cases]})
    readback=builder['readback'](base['definition'])
    for path,value in [('work-class.json',base['definition']),('readback-derived.json',readback),('authority-definition.json',base['authority_input']['work_class']),
        ('authority-input.json',base['authority_input']),('authority-result-derived.json',base['authority_result']),('deployment-input.json',base['deploy_input']),
        ('deployment-result-derived.json',base['deploy_result']),('registry-definition.json',base['reservation_facts']['configuration']),
        ('registry-seed-inputs.json',[row[0] for row in base['registry_seed_trace']]),('registry-seed-results-derived.json',[row[1] for row in base['registry_seed_trace']]),
        ('native-request.json',facts['permitted']['permit']['native_request']),('native-completion.json',facts['completion_event']['native_evidence']),
        ('original-batch-disposition-history.json',facts['completion_event']['native_evidence'])]:write(path,value)
    (HERE/'source-packet.md').write_bytes(SOURCE_PATH.read_bytes())
    inventory,dossier,dossier_digest=dossier_records()
    write('source-records.json',{'prerequisites':inventory,'dossier':dossier,'dossier_digest':dossier_digest})
    for row in base['authority_input']['decision_bases']:
        name=row['requirement_id']; result=next(value for value in base['authority_result']['decision_results'] if value['requirement_id']==name)
        write('human-decisions/'+name+'-evidence.json',row['evidence']);write('human-decisions/'+name+'-result-derived.json',result['result'])
    trace('valid-trace',groups['valid-trace'])
    write('valid-trace/final-work-state.json',facts['completed']['state']);write('valid-trace/final-registry-state.json',facts['settled_registry']['result']['state'])
    for family in ['lookup','native-mismatch','leaf-current-failures','correction','correction-negative','late-evidence']:
        trace('focused-traces/'+family,groups[family])
    for business,label in [(True,'business'),(False,'metadata')]:
        supplied,expected=cdmo_correction(facts,business_change=business);write('correction/'+label+'-input.json',supplied);write('correction/'+label+'-result-derived.json',expected)
    write('restart/checkpoints.json',{'candidate_pin':candidate_pin(),'status':'AUTHOR_DERIVED_NOT_CONSUMER_VERIFIED','checkpoints':[
        {'stage':name,'work_state':facts[name]['state'],'work_state_digest':facts[name]['state_digest']} for name in ['permitted','authorized','dispatched','completed']]})
    record,coverage=source_mapping(base,readback)
    write('correspondence-input.json',groups['source-correspondence'][0]['input'])
    write('correspondence-result-derived.json',groups['source-correspondence'][0]['expected'])
    write('correspondence-record.json',record)
    write('source-mapping.json',{'candidate_pin':candidate_pin(),'status':'PENDING_INDEPENDENT_REVIEW','mappings':record['mappings'],'residue':record['residue']})
    for row in coverage:
        row['case_ids']=sorted(case['id'] for family in row.pop('case_families') for case in groups.get(family,[]))
    write('source-coverage.json',{'source_sha256':sha(SOURCE_PATH),'candidate_pin':candidate_pin(),'status':'AUTHOR_DERIVED_NOT_CONSUMER_VERIFIED',
        'source_obligations':str(len(coverage)),'selected_policy':str(sum(row['kind']=='SELECTED_POLICY' for row in coverage)),
        'host_premises':str(sum(row['kind']=='HOST_PREMISE' for row in coverage)),'source_residue':str(sum(row['kind']=='SOURCE_RESIDUE' for row in coverage)),'coverage':coverage})
    write('case-inventory.json',{'candidate_pin':candidate_pin(),'status':'AUTHOR_DERIVED_NOT_CONSUMER_VERIFIED','cases':[
        {'id':row['id'],'operation':row['operation'],'path':'../../cases/cdmo-source/'+row['id']+'.json','raw_sha256':sha(builder['GROUP']/(row['id']+'.json'))} for row in cases]})
    write('scenario-expectations.json',{'candidate_pin':candidate_pin(),'status':'AUTHOR_DERIVED_NOT_CONSUMER_VERIFIED','groups':[
        {'name':name,'case_ids':[row['id'] for row in rows],'judgments':[row['derivation'] for row in rows]} for name,rows in groups.items()]})
    write('provider-premises.json',{'status':'APPARATUS_ONLY_NOT_PROVIDER_VALIDATION','premises':[
        'The host authenticates canonical human identities across principals and complete authority/return/source bodies.',
        'The coordinator includes every writer listed in source section10, including roots, capacities, envelopes and both remit registers.',
        'The complete prior-attempt query excludes the registered candidate; all other attempt writers advance the guarded revision.',
        'One conditional native transaction checks the complete vector, exact inventory revision, current decision intervals and two uniqueness domains before update and event creation.',
        'Protected retained audit bodies, complete provider history and truthful lookup responses remain integration responsibilities.',
        'Synthetic accepted deployment review and correspondence carriers exercise admission; the separate source correspondence is PENDING and records residue.',
        'A postcommit hold creates a separate containment referral intent; no artifact proves delivery or containment.']})
    paths=sorted((path for path in HERE.rglob('*') if path.is_file() and path.name!='artifact-index.json' and '__pycache__' not in path.parts),key=lambda path:str(path.relative_to(HERE)).encode())
    write('artifact-index.json',{'candidate_pin':candidate_pin(),'status':'AUTHOR_DERIVED_NOT_CONSUMER_VERIFIED','source_sha256':sha(SOURCE_PATH),'artifacts':[
        {'path':str(path.relative_to(HERE)),'sha256':sha(path)} for path in paths]})
    print({'cases':len(cases),'source_obligations':len(coverage),'mapped_obligations':len(record['mappings']),'unsupported_paths':len(record['unsupported_provision_paths']),'readback_paths':len(readback['lines'])})

if __name__=='__main__':main()
