"""Closed external source correction evidence schema extension."""
from __future__ import annotations

import copy

from equipment_schema_extensions import BASE, DIGEST, FIELD, ID, INSTANT, VALUE, arr, nullable, obj


def extend_correction_schemas(work_class_schema, authority_schema, evidence_schema):
    policy = obj({
        'custodian_role': ID, 'issuer_role': ID, 'correction_provider': ID,
        'correction_source': ID, 'correction_record_type': ID, 'custodian_identity_source': ID,
        'original_id_field': ID, 'original_digest_field': ID, 'original_revision_field': ID,
        'changes_digest_field': ID, 'result_digest_field': ID, 'business_result_fields': arr(ID,64,1),
        'provider_link_bindings': arr(obj({'field': ID, 'provider': ID, 'source': ID,
            'record_type': ID, 'record_id_field': ID}),64),
    })
    for schema in [work_class_schema, authority_schema]:
        carrier = schema['$defs'].get('completionCarrier')
        if carrier is None or '$ref' in carrier:
            continue
        variants = carrier.get('oneOf', [carrier])
        for variant in variants:
            if variant.get('properties', {}).get('terminal_policy', {}).get('const') == 'STOP_RETAIN':
                variant['properties']['correction_policy'] = copy.deepcopy(policy)
    defs=evidence_schema['$defs']
    identity=obj({'provider':ID,'source':ID,'record_type':ID,'provider_record_id':ID})
    defs['correctionCustodian']=obj({'actor':ID,'role':ID,'principal':ID,'occupancy':ID})
    defs['correctionCustodianReturn']=obj({'provider':ID,'source':ID,'occupancy_digest':DIGEST,
        'actor':ID,'role':ID,'at':INSTANT,'evidence_ref':ID,'provenance_digest':DIGEST})
    defs['sourceCorrectionRecord']=obj({
        'schema':{'const':'seampoint.work-class/1.0.0-draft.3/source-correction-record'},
        'evidence_id':ID,'provider':ID,'source':ID,'record_type':ID,
        'original_provider_record_id':ID,'original_record_digest':DIGEST,'expected_revision':ID,
        'custodian':{'$ref':'#/$defs/correctionCustodian'},'custodian_return':{'$ref':'#/$defs/correctionCustodianReturn'},
        'changes':arr(obj({'field':ID,'old_value':nullable(VALUE),'new_value':nullable(VALUE)}),64,1),
        'corrected_fields':arr(FIELD,66,1),
        'correction_authority_input':{'$ref':BASE+'authority.schema.json#/$defs/input'},
        'correction_authorization_digest':DIGEST,
        'new_approval_basis':nullable({'$ref':BASE+'authority.schema.json#/$defs/input'}),
        'event_time':INSTANT,'observed_at':INSTANT,'evidence_ref':ID,'provenance_digest':DIGEST,
    })
    defs['sourceCorrectionInput']=obj({
        'profile':{'const':'LINEAR'},'role':{'const':'REVIEW_EVIDENCE'},'specification_pin':DIGEST,
        'definition':{'$ref':BASE+'work-class.schema.json#/$defs/definition'},'definition_digest':DIGEST,
        'original_permit':{'$ref':BASE+'lifecycle.schema.json#/$defs/permit'},
        'original_record':{'$ref':BASE+'lifecycle.schema.json#/$defs/nativeEvidence'},
        'correction':{'$ref':'#/$defs/sourceCorrectionRecord'},
    })
    defs['sourceCorrectionResult']=obj({
        'status':{'const':'EVIDENCE_VALID'},'profile':{'const':'LINEAR'},'role':{'const':'REVIEW_EVIDENCE'},
        'specification_pin':DIGEST,'kind':{'const':'SOURCE_CORRECTION'},'definition_digest':DIGEST,
        'original_record_identity':identity,'original_record_digest':DIGEST,'correction_digest':DIGEST,
        'correction_authority_result':{'$ref':BASE+'authority.schema.json#/$defs/result'},
        'correction_authority_result_digest':DIGEST,
        'new_approval_result':nullable({'$ref':BASE+'authority.schema.json#/$defs/result'}),
        'new_approval_result_digest':nullable(DIGEST),'changes_digest':DIGEST,'result_digest':DIGEST,
    })
    defs['input']['oneOf'].append({'$ref':'#/$defs/sourceCorrectionInput'})
    for code in ('TYPE_INVALID', 'INPUT_INVALID', 'DEPENDENCY_MISMATCH', 'REFERENCE_INVALID', 'LIMIT_EXCEEDED'):
        if code not in defs['refusal']['properties']['code']['enum']:
            defs['refusal']['properties']['code']['enum'].append(code)
    legacy=copy.deepcopy(defs['result'])
    defs['result']={'oneOf':[legacy,{'$ref':'#/$defs/sourceCorrectionResult'}]}
