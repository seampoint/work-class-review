"""Closed boundary-referral binding evidence; no lifecycle transition."""
from __future__ import annotations

from equipment_schema_extensions import BASE, DIGEST, obj


def extend_boundary_evidence(evidence_schema):
    defs = evidence_schema['$defs']
    defs['boundaryReferralInput'] = obj({
        'profile': {'const': 'LINEAR'}, 'role': {'const': 'REVIEW_EVIDENCE'},
        'specification_pin': DIGEST,
        'definition': {'$ref': BASE + 'work-class.schema.json#/$defs/definition'},
        'definition_digest': DIGEST, 'request_digest': DIGEST,
        'boundary_referral': {'$ref': BASE + 'lifecycle.schema.json#/$defs/boundaryReferral'},
    })
    defs['boundaryReferralResult'] = obj({
        'status': {'const': 'EVIDENCE_VALID'}, 'profile': {'const': 'LINEAR'},
        'role': {'const': 'REVIEW_EVIDENCE'}, 'specification_pin': DIGEST,
        'kind': {'const': 'BOUNDARY_REFERRAL'}, 'definition_digest': DIGEST,
        'request_digest': DIGEST, 'referral_digest': DIGEST,
    })
    defs['input']['oneOf'].append({'$ref': '#/$defs/boundaryReferralInput'})
    if 'oneOf' not in defs['result']:
        defs['result'] = {'oneOf': [defs['result']]}
    defs['result']['oneOf'].append({'$ref': '#/$defs/boundaryReferralResult'})
