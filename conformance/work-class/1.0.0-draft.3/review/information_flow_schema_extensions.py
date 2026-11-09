"""Closed information-flow bodies, authority carriers and projection."""
from __future__ import annotations

import copy

from holdings_schema_extensions import BASE, PREFIX, DIGEST, ID, INSTANT, NATURAL, arr, nullable, obj, ref

AUTH = BASE + 'authority.schema.json#/$defs/'
FLOW = BASE + 'information-flow.schema.json#/$defs/'
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 8192}
FIELD = {'$ref': BASE + 'aggregate.schema.json#/$defs/field'}
TYPE = {'$ref': BASE + 'aggregate.schema.json#/$defs/type'}
REASONS = ['FLOW_UNAVAILABLE', 'FLOW_STALE', 'FLOW_CAPACITY_EXHAUSTED',
           'FLOW_DEPENDENCY_CHANGED', 'FLOW_RECIPIENT_NOT_ENTITLED', 'FLOW_RELEASE_NOT_ESTABLISHED', 'FLOW_CLAIM_CONSUMED']
CODES = ['ACCESS_NOT_ESTABLISHED', 'ACT_CONFLICT', 'GATE_REQUIRED', 'ACT_NOT_AUTHORIZED', 'ACT_NOT_ACCEPTED', 'ARTIFACT_ENCODING_INVALID', 'ARTIFACT_NONCANONICAL',
         'BINDING_MISMATCH', 'CLOCK_INVALID', 'DEFINITION_CONFLICT', 'DEFINITION_INVALID',
         'DEPENDENCY_MISMATCH', 'DIGEST_MISMATCH', 'EVIDENCE_UNAVAILABLE', 'INPUT_INVALID',
         'LIMIT_EXCEEDED', 'REFERENCE_INVALID', 'REPLAY_CONFLICT', 'REVISION_CONFLICT',
         'SCHEMA_INVALID', 'STATE_INVALID', 'TYPE_INVALID', 'UNSUPPORTED_RELATION', 'VERSION_UNSUPPORTED']


def absolute_authority_refs(value):
    if isinstance(value, dict):
        return {key: AUTH + child[len('#/$defs/'):] if key == '$ref' and child.startswith('#/$defs/')
                else absolute_authority_refs(child) for key, child in value.items()}
    if isinstance(value, list):
        return [absolute_authority_refs(child) for child in value]
    return value


def information_flow_schema(authority):
    d = {}
    d['restriction'] = obj({'id': ID, 'scope': ID, 'meaning': TEXT,
        'releasable': {'type': 'boolean'}, 'release_role': nullable(ID)})
    d['configuration'] = obj({'schema': {'const': PREFIX + 'flow-configuration'},
        'specification_pin': DIGEST, 'id': ID, 'principal': ID, 'provider': ID, 'source': ID,
        'protected_channel': ID, 'clock_source': ID, 'control_interface': ID,
        'access_operation': ID, 'transfer_operation': ID, 'response_operation': ID, 'response_role': ID, 'restrictions': arr(ref('restriction'), 64)})
    d['source'] = obj({'provider': ID, 'source': ID, 'record_type': ID,
        'record_id': ID, 'revision': ID, 'content_digest': DIGEST, 'scope': ID,
        'restrictions': arr(ID, 64)})
    d['context'] = obj({'id': ID, 'actor': ID, 'scope': ID, 'purpose': ID, 'revision': NATURAL,
        'ceiling': arr(ID, 64), 'restrictions': arr(ID, 64), 'origins': arr(ref('source'), 64)})
    d['artifact'] = obj({'id': ID, 'context_id': ID, 'context_revision': NATURAL,
        'context_digest': DIGEST, 'types': arr(TYPE, 256), 'fields': arr(FIELD, 64),
        'restrictions': arr(ID, 64), 'origins': arr(ref('source'), 64)})
    d['claim'] = obj({'id': ID, 'intent_id': ID, 'status': {'const': 'POSSIBLE_EXPOSURE'}, 'kind': {'enum': ['READ', 'IMPORT', 'EXPOSE']},
        'context_id': ID, 'recipient': ID, 'channel': ID, 'purpose': ID,
        'subject_digest': DIGEST, 'release_act_digest': nullable(DIGEST)})
    d['attestation'] = obj({'kind': {'enum': ['INITIAL_INVENTORY', 'SOURCE_CLASSIFICATION', 'MATERIALIZED_CONTENT']},
        'subject_digest': DIGEST, 'provider': ID, 'source': ID, 'channel': ID, 'evidence_ref': ID})
    d['hostEvidence'] = obj({'configuration_digest': DIGEST, 'event_subject_digest': DIGEST,
        'selection_evidence': ID, 'attestations': arr(ref('attestation'), 1)})
    d['selection'] = obj({'configuration_digest': DIGEST, 'state_digest': DIGEST, 'revision': NATURAL,
        'provider': ID, 'source': ID, 'channel': ID, 'at': INSTANT,
        'status': {'enum': ['AVAILABLE', 'UNAVAILABLE', 'CONFLICTING']}, 'selection_evidence': ID})
    d['authorityBasis'] = obj({'requirement_id': ID, 'configuration': ref('configuration'),
        'state': ref('state'), 'state_digest': DIGEST, 'selection': ref('selection'),
        'released_restrictions': arr(ID, 64)})
    d['exposureBasis'] = copy.deepcopy(d['authorityBasis'])
    d['exposureBasis']['properties'].pop('state')
    d['exposureBasis']['required'].remove('state')
    d['authorityProjection'] = absolute_authority_refs(copy.deepcopy(authority['$defs']['input']))
    d['authorityProjection']['properties']['flow_bases'] = arr(ref('exposureBasis'), 1, 1)
    if 'flow_bases' not in d['authorityProjection']['required']:
        d['authorityProjection']['required'].append('flow_bases')
    d['accessInput'] = absolute_authority_refs(copy.deepcopy(authority['$defs']['input']))
    d['accessInput']['properties']['flow_bases'] = arr({'$ref': FLOW + 'authorityBasis'}, 0)
    common = {'schema': {'const': PREFIX + 'flow-event'}, 'id': ID,
        'expected_revision': NATURAL, 'expected_state_digest': nullable(DIGEST),
        'clock': {'$ref': AUTH + 'clock'}}
    payloads = {
        'CREATE_CONTEXT': obj({'context_id': ID, 'actor': ID, 'scope': ID, 'purpose': ID,
            'ceiling': arr(ID, 64), 'initial_sources': arr(ref('source'), 0)}),
        'READ': obj({'context_id': ID, 'intent_id': ID, 'claim_id': ID, 'source': ref('source'),
            'access_authority': ref('accessInput')}),
        'IMPORT': obj({'sender_context_id': ID, 'receiver_context_id': ID, 'artifact_id': ID,
            'intent_id': ID, 'claim_id': ID, 'transfer_authority': ref('accessInput'), 'access_authority': ref('accessInput')}),
        'MATERIALIZE': obj({'context_id': ID, 'artifact_id': ID, 'types': arr(TYPE, 256), 'fields': arr(FIELD, 64)}),
        'EXPOSE': obj({'requirement_id': ID, 'authority_projection': ref('authorityProjection')}),
    }
    d['event'] = {'oneOf': [obj({**copy.deepcopy(common), 'kind': {'const': kind}, 'payload': payload})
        for kind, payload in payloads.items()]}
    d['core'] = obj({'configuration_digest': DIGEST, 'revision': NATURAL, 'last_clock': INSTANT,
        'contexts': arr(ref('context'), 16), 'artifacts': arr(ref('artifact'), 64),
        'claims': arr(ref('claim'), 128), 'consumed_release_acts': arr(DIGEST, 128)})
    d['receipt'] = obj({'schema': {'const': PREFIX + 'flow-receipt'}, 'event_id': ID,
        'event_digest': DIGEST, 'state_before_digest': nullable(DIGEST), 'revision': NATURAL,
        'core_after_digest': DIGEST, 'decision': {'enum': ['CONTEXT_CREATED', 'READ_RECORDED',
            'IMPORT_RECORDED', 'ARTIFACT_RECORDED', 'EXPOSURE_RECORDED']},
        'authority_result_digests': arr(DIGEST, 2), 'authority_evidence_digests': arr(DIGEST, 2),
        'protected_channel': ID})
    d['record'] = obj({'event': ref('event'), 'host_evidence': ref('hostEvidence'),
        'event_digest': DIGEST, 'receipt': ref('receipt'), 'receipt_digest': DIGEST})
    d['state'] = obj({'schema': {'const': PREFIX + 'flow-state'}, 'specification_pin': DIGEST,
        'core': ref('core'), 'records': arr(ref('record'), 128, 1)})
    d['input'] = obj({'schema': {'const': PREFIX + 'flow-input'}, 'specification_pin': DIGEST,
        'configuration': ref('configuration'), 'state': nullable(ref('state')), 'state_digest': nullable(DIGEST),
        'event': ref('event'), 'host_evidence': ref('hostEvidence'), 'response_authority': ref('accessInput')})
    d['result'] = obj({'status': {'const': 'TRANSITION'}, 'receipt': ref('receipt'),
        'receipt_digest': DIGEST, 'state': ref('state'), 'state_digest': DIGEST, 'replay': {'type': 'boolean'}})
    d['refusal'] = obj({'status': {'const': 'REFUSED'}, 'code': {'enum': CODES}, 'path': {'const': ''},
        'state': nullable(ref('state')), 'state_digest': nullable(DIGEST)})
    entitlement = {'restriction_id': ID, 'scope': ID, 'recipient': ID, 'channel': ID, 'purpose': ID}
    d['policy'] = obj({'id': ID, 'revision': ID, 'configuration_digest': DIGEST,
        'entitlements': arr(obj(entitlement), 128),
        'release_rules': arr(obj({**entitlement, 'release_role': ID}), 128)})
    hash_source = obj({'requirement_id': ID, 'digest_field': ID})
    d['requirement'] = obj({'id': ID, 'step': ID, 'configuration_digest': DIGEST,
        'context_id': ID, 'artifact_id': ID, 'intent_id': ID, 'claim_id': ID, 'recipient_field': ID,
        'channel': ID, 'purpose': ID, 'policy': ref('policy'), 'release_decision_requirement_id': nullable(ID),
        'sources': obj({'policy': hash_source,
            'recipient': obj({'requirement_id': ID, 'recipient_field': ID, 'channel_field': ID,
                'purpose_field': ID, 'effective_field': ID}),
            'release_selection': nullable(obj({'requirement_id': ID, 'act_id_field': ID,
                'act_digest_field': ID, 'subject_digest_field': ID, 'claim_id_field': ID})),
            'release_effectiveness': nullable(obj({'requirement_id': ID, 'act_id_field': ID, 'effective_field': ID})),
            'blockers': arr(ID, 64)})})
    d['fenceFlow'] = obj({'requirement_id': ID, 'configuration_digest': DIGEST, 'state_digest': DIGEST,
        'revision': NATURAL, 'context_digest': DIGEST, 'artifact_digest': DIGEST, 'policy_digest': DIGEST,
        'intent_id': ID, 'claim_id': ID, 'release_act_digest': nullable(DIGEST)})
    d['controlRefusal'] = obj({'status': {'const': 'REFUSED'}, 'code': {'enum': CODES}, 'path': {'const': ''}})
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
        '$id': BASE + 'information-flow.schema.json',
        '$comment': 'DRAFT_NOT_ADOPTED; APPARATUS_ONLY. Complete host mediation and custody are separate premises.',
        '$defs': d, 'oneOf': [ref(name) for name in ('input', 'result', 'refusal', 'controlRefusal')]}


def extend_information_flow_schemas(authority, lifecycle, protocol):
    a, l, p = (value['$defs'] for value in (authority, lifecycle, protocol))
    a['envelope']['properties']['flow_requirements'] = arr({'$ref': FLOW + 'requirement'}, 1)
    a['input']['properties']['flow_bases'] = arr({'$ref': FLOW + 'authorityBasis'}, 1)
    bindings = a['humanDecisionRequirement']['properties']['context_bindings']['items']['properties']['value']['oneOf']
    bindings.append(obj({'kind': {'const': 'FLOW_DISCLOSURE'}, 'requirement_id': ID, 'type_ref': ID}))
    for name in ('check', 'failedCheck'):
        a[name]['properties']['purpose']['enum'].append('FLOW')
    for name, prop in (('refusal', 'reasons'), ('failedCheck', 'reason')):
        target = a[name]['properties'][prop]
        if prop == 'reasons': target = target['items']
        target['enum'].extend(REASONS)
    for name in ('authorizationFence', 'decisionDetailAuthorization'):
        for variant in l[name]['oneOf']:
            selector = 'kind' if name == 'authorizationFence' else 'gate_kind'
            if variant['properties'].get(selector, {}).get('const') == 'SOURCE_REQUIREMENTS':
                variant['properties']['flows'] = arr({'$ref': FLOW + 'fenceFlow'}, 1, 1)
    p['capabilitiesResult']['properties']['roles']['items']['enum'].append('FLOW_TRANSITIONS')
    p['capabilitiesResult']['properties']['roles']['items']['enum'].sort()
    p['capabilitiesResult']['properties']['roles']['maxItems'] = 11
    operations = p['capabilitiesResult']['properties']['operations']
    operations['items']['enum'].append('flow-step')
    operations['items']['enum'].sort()
    operations['maxItems'] = 10
    for name, body in (('request', 'input'), ('response', 'result')):
        properties = {'protocol': {'const': 'seampoint.work-class.adapter/1.0.0-draft.3'},
            'request_id': ID, 'operation': {'const': 'flow-step'}}
        properties[body] = {'$ref': FLOW + 'input'} if body == 'input' else {'anyOf': [
            {'$ref': FLOW + 'result'}, {'$ref': FLOW + 'refusal'}, {'$ref': FLOW + 'controlRefusal'}, {'$ref': '#/$defs/shapeRefusal'}]}
        p[name]['oneOf'].append(obj(properties))
