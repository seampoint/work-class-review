#!/usr/bin/env python3
"""Build the complete synthetic equipment specimen from source and author rules."""
from __future__ import annotations

import hashlib
import runpy
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
REVIEW = HERE.parents[1] / 'review'
sys.path.insert(0, str(REVIEW))

from corpus_common import candidate_pin, canonical_bytes, digest, write_canonical_json
from equipment_source_fixture import CAPABILITY_FIELDS, SOURCE_PATH, equipment_readback


def write(name, value):
    write_canonical_json(HERE / name, value)


def raw_sha(path):
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def trace(name, rows):
    requests = [{'protocol': 'seampoint.work-class.adapter/1.0.0-draft.3',
        'request_id': row['id'], 'operation': row['operation'], 'input': row['input']} for row in rows]
    results = [row['expected'] for row in rows]
    write(name + '/requests.json', requests)
    write(name + '/results-derived.json', results)
    for filename, values in [('requests.jsonl', requests), ('results-derived.jsonl', results)]:
        (HERE / name / filename).write_bytes(b''.join(canonical_bytes(row) + b'\n' for row in values))
    write(name + '/expectations.json', {'candidate_pin': candidate_pin(), 'status': 'AUTHOR_DERIVED_UNRELEASED',
        'case_ids': [row['id'] for row in rows], 'operation_count': str(len(rows)),
        'expected_digest': digest('equipment-source-trace-results', results)})


def coverage(cases, base):
    valid = [row['id'] for row in cases[:11]]
    def matching(*phrases):
        return [row['id'] for row in cases if any(text in row['derivation'] for text in phrases)]
    sections = {
        '4': ('Request identity stays outside the native payload.', ['source-packet.txt', 'registry-definition.json'], matching('request-use')),
        '5': ('NPO-7 is the separately bound principal and request issuer.', ['authority-input.json', 'source-owners.json'], valid),
        '6': ('The original request and all original trace facts use September 12, 2026.', ['source-packet.txt', 'valid-trace/requests.json'], valid),
        '8': ('Complete inspection, exact approval and one administrative result are independently bound.', ['authority-input.json', 'work-class.json'], matching('inspection', 'approval')),
        '10': ('Seven native arguments follow authority, gate, one dispatch and exact completion.', ['native-request.json', 'valid-trace/requests.json'], valid),
        '12': ('Six source participants are retained without adding policy/fact owners to the native payload.', ['work-class.json', 'source-owners.json'], valid),
        '14': ('Medium materiality/reversibility and administrative scope are declared. Separate correction and control procedures remain external.', ['work-class.json', 'correction/input.json', 'provider-premises.json'], matching('Correction Authorization')),
        '19': ('One exact grant scope and five identifier keys prevent reuse of the declared operation.', ['authority-input.json', 'registry-definition.json'], matching('identifier', 'five-key')),
        '21': ('The complete inspection, approval, current clerk facts, safety status and historical supervisor duty are required.', ['authority-input.json'], matching('current-', 'inspection', 'historical-supervisor-duty', 'approval')),
        '23': ('Four distinct returned current records bind the same clerk, role, principal, duty instant and asset.', ['authority-input.json', 'source-owners.json'], matching('current-')),
        '25': ('Every live query uses the exact gate instant; stale or unavailable records withhold the gate.', ['authority-input.json'], matching('stale', 'unavailable', 'current-')),
        '27': ('Original grant 14:00, inspection 13:55 and exclusive 23:59 expiry are explicit. WD-552 has exact approval-register coordinates.', ['authority-input.json', 'valid-trace/requests.json'], matching('withdrawal', 'expires')),
        '29': ('Failed authority leaves no new transaction and routes review to Reliability Supervisor.', ['failure-traces/proposal-identity/requests.json'], matching('PROPOSE:')),
        '34': ('The gate verifies AP-091 after inspection, checks authoritative tuple absence, and independently refreshes before dispatch.', ['authority-input.json', 'valid-trace/requests.json'], matching('inspection', 'completed-tuple-absence', 'fresh immediate')),
        '36': ('Four independent current record requirements enforce actual values and common subjects.', ['authority-input.json'], matching('current-')),
        '38': ('Failure referrals preserve safe state. Safety reaches Safety Compliance Lead through Reliability Supervisor.', ['failure-traces/proposal-safety/results-derived.json'], matching('current-safety')),
        '40': ('Physical/mixed control exits bind Operations Control Room Lead and reentry requirements. Missing or contradictory administrative business facts use Reliability Supervisor under the recorded source interpretation. External classification and delivery remain host/source-review premises.', ['boundary-exits/requests.json', 'boundary-exits/results-derived.json', 'provider-premises.json'], matching('source PHYSICAL_CONTROL', 'source MIXED_CONTROL', 'source readback', 'business fact', 'request-identity')),
        '45': ('Eleven completion fields include generated identity/time, seven source values, status and a qualified approval link.', ['native-completion.json', 'valid-trace/results-derived.json'], matching('native', 'eleven-field')),
        '47': ('Missing or mismatched completion stops the instance, preserves unresolved registry claims and emits both completion owner referrals.', ['failure-traces/missing-completion/results-derived.json', 'failure-traces/native-mismatch/results-derived.json'], matching('Missing native', 'mismatch', 'native lookup')),
        '49': ('Custodian attribution and separately authorized corrections preserve original native history. No event proves physical equipment state.', ['correction/input.json', 'provider-premises.json'], matching('Correction Authorization', 'corrected approval-register')),
        '54': ('Exact duplicate absence precedes submission. Possibly sent lookup never creates a replay permission, and late evidence preserves STOPPED status.', ['failure-traces/missing-completion/requests.json', 'late-evidence/not-found/results-derived.json'], matching('completed-tuple-absence', 'native lookup', 'late native', 'stopped source')),
        '56': ('Corrections require separate authorities; fresh later admission requires disjoint request, work-order, inspection, approval and tuple keys.', ['correction/input.json', 'correction/new-approval-input.json', 'fresh-instance/requests.json'], matching('correction', 'identifier', 'hypothetical fresh', 'fresh request', 'fresh completion')),
        '58': ('MCS-12-r4, DR-08-r2, policy owners, fact owners and source remits remain explicit.', ['source-owners.json', 'authority-input.json'], valid),
        '60': ('A selected independent Governance Lead organizational attestation binds the exact original scope and grant/withdrawal remit.', ['authority-input.json'], valid),
        '62': ('Recorded policy withdrawal withholds an undispatched instance. A policy amendment requires new source/definition review; prior history remains immutable.', ['authority-input.json', 'provider-premises.json'], matching('policy-dr-withdrawal', 'policy-mcs-withdrawal')),
        '68': ('Provider capabilities are explicit current requirements. Actual atomic uniqueness, lookup and fenced-write truth are external implementation premises.', ['provider-premises.json', 'authority-input.json'], matching('provider-capabilit')),
        '69': ('Four distinct session/role/duty/safety responses are required independently.', ['authority-input.json'], matching('current-')),
        '70': ('Zero freshness and exact query instant prevent cached capability or live-fact substitution.', ['authority-input.json'], matching('stale', 'provider-capabilit')),
        '71': ('The original AP-091 interval has an exclusive upper bound at the source timestamp.', ['authority-input.json'], matching('expires')),
        '72': ('Six business-result fields require fresh approval; other field corrections still require separate correction authority and a qualified approval link.', ['work-class.json', 'correction/new-approval-input.json'], matching('Correction Authorization', 'changed approval', 'corrected approval-register')),
        '73': ('Policy withdrawal joins the dispatch fence; policy amendment requires a new request and separately reviewed source revision.', ['authority-input.json', 'provider-premises.json'], matching('policy-dr-withdrawal', 'policy-mcs-withdrawal')),
        'equipment-provider-capability-premise': ('The separately attributable capability record/channel is a current implementation premise from amendment 1 and the approved history profile. Each false/missing capability or absent/unavailable record withholds authority at proposal and dispatch; authentication and actual provider truth remain host premises.', ['authority-input.json', 'provider-premises.json', 'failure-traces/provider-capability/results-derived.json'], matching('provider-capabilit')),
    }
    rows = []
    for obligation in base['authority_input']['source']['obligations']:
        number = obligation['id'].removeprefix('equipment-source-line-')
        text, paths, ids = sections.get(number, ('Source inventory or explicit apparatus premise; semantic fidelity requires independent source review.', ['source-packet.txt', 'provider-premises.json'], []))
        rows.append({'source_obligation_id': obligation['id'], 'source_line': number if number.isdigit() else None,
            'source_text_digest': digest('equipment-source-clause', obligation['text']),
            'status': 'AUTHOR_DERIVED_PENDING_SOURCE_REVIEW_AND_CONSUMERS', 'binding': text,
            'artifact_paths': sorted(paths), 'case_ids': sorted(set(ids)),
            'unproven_premises': ['source-fidelity-review', 'host-authentication-and-source-truth', 'external-provider-and-owner-performance']})
    return {'source_sha256': raw_sha(SOURCE_PATH), 'candidate_pin': candidate_pin(),
        'status': 'DRAFT_NOT_ADOPTED_APPARATUS_ONLY', 'coverage': rows}


def main():
    build = runpy.run_path(str(REVIEW / 'build-equipment-source-cases.py'))
    cases, traces, facts = build['construct_cases']()
    for row in cases:
        write_canonical_json(build['GROUP'] / (row['id'] + '.json'), row)
    base = facts['base']
    write('work-class.json', base['definition'])
    write('readback-derived.json', equipment_readback(base)[1])
    write('authority-definition.json', base['authority_input']['work_class'])
    write('authority-input.json', base['authority_input'])
    write('authority-result-derived.json', base['authority_result'])
    write('deployment-input.json', base['deploy_input'])
    write('deployment-result-derived.json', base['deploy_result'])
    write('registry-definition.json', base['reservation_facts']['configuration'])
    write('registry-seed-inputs.json', [row[0] for row in base['registry_seed_trace']])
    write('registry-seed-results-derived.json', [row[1] for row in base['registry_seed_trace']])
    write('native-request.json', facts['permitted']['permit']['native_request'])
    write('native-completion.json', facts['completion_event']['native_evidence'])
    write('original-return-to-service-history.json', facts['completion_event']['native_evidence'])
    write('correction/input.json', facts['correction_input'])
    write('correction/result-derived.json', facts['correction_output'])
    linked = traces['source-correction-new-approval'][0]
    write('correction/new-approval-input.json', linked['input'])
    write('correction/new-approval-result-derived.json', linked['expected'])
    trace('boundary-exits', traces['boundary-exits'])
    trace('valid-trace', traces['valid'])
    write('valid-trace/final-work-state.json', facts['completed']['state'])
    write('valid-trace/final-registry-state.json', facts['settled']['result']['state'])
    write('restart/checkpoints.json', {'candidate_pin': candidate_pin(), 'checkpoints': [
        {'stage': name, 'work_state': facts[name]['state'], 'work_state_digest': facts[name]['state_digest']}
        for name in ['permitted', 'authorized', 'dispatched', 'completed']]})
    for name, family in [('proposal-identity', 'propose-current-session'), ('proposal-safety', 'propose-current-safety'),
            ('dispatch-withdrawal', 'dispatch-withdrawal'), ('missing-completion', 'lookup-not_found'),
            ('native-mismatch', 'mismatch-asset'), ('provider-capability', 'dispatch-capability-tuple_uniqueness-false')]:
        trace('failure-traces/' + name, traces[family][-1:])
    for status, family in [('not-found', 'not_found'), ('ambiguous', 'ambiguous')]:
        trace('late-evidence/' + status, traces['late-exact-' + family][-2:])
    trace('fresh-instance', traces['fresh-instance'])
    write('fresh-instance/final-work-state.json', facts['fresh_completed']['state'])
    write('fresh-instance/final-registry-state.json', facts['fresh_settled']['result']['state'])
    write('source-owners.json', {'participants': base['definition']['participants'], 'owners': [
        {'role': 'maintenance-governance-lead', 'sources': ['MCS-12-r4', 'DR-08-r2', 'recorded-policy-amendments', 'recorded-policy-withdrawals'], 'source_lines': ['58', '60', '62']},
        {'role': 'reliability-supervisor', 'sources': ['AP-091', 'WD-552', 'correction-authorization'], 'source_lines': ['27', '56']},
        {'role': 'maintenance-records-custodian', 'sources': ['native-return-to-service-history', 'correction-entry'], 'source_lines': ['49', '56', '58']},
        {'role': 'inspection-engineer', 'sources': ['IN-552'], 'source_lines': ['12']},
        {'role': 'access-administration-lead', 'sources': ['authenticated-session', 'active-role-assignment'], 'source_lines': ['23', '36']},
        {'role': 'maintenance-scheduling-lead', 'sources': ['maintenance-duty-roster'], 'source_lines': ['23', '36']},
        {'role': 'safety-compliance-lead', 'sources': ['equipment-safety-hold-register'], 'source_lines': ['23', '36', '38']},
        {'role': 'operations-control-room-lead', 'sources': ['separate-equipment-control-procedure'], 'source_lines': ['40']},
    ], 'source_review_unknowns': ['The source identifies named operational roles for work-order facts without assigning a particular work-order owner identity.']})
    write('provider-premises.json', {'status': 'DRAFT_NOT_ADOPTED_APPARATUS_ONLY',
        'source_sha256': raw_sha(SOURCE_PATH), 'capability_fields': CAPABILITY_FIELDS,
        'capability_record': {'provider': 'maintenance-register', 'source': 'provider-capabilities',
            'record_type': 'capability-declaration', 'record_id': 'maintenance-register-revision-3-capabilities'},
        'premises': [
            'The host authenticates complete normalized source observations, capability declarations, organizational remits, role occupancies, signatures, clocks and provider record identities against actual returned records. Their synthetic provenance digests do not establish authenticity or provider truth.',
            'Amendment 1 requires actual provider atomic tuple uniqueness, authoritative tuple and generated-event-ID lookup, and write commitment only under the current effective/unwithdrawn approval and policy fence. The portable apparatus records and checks these declarations; it does not implement a real provider.',
            'Every writer uses one serialized, durable mediation and complete historical cutover. History includes prior completed native records and retained uncertain attempts, together with authentic request-to-event bindings for keys absent from the seven-field native request.',
            'The return-to-service-history record type is a chosen host normalization of native events and uncertain attempts. A HELD record identity denotes an attributable uncertain-attempt/history record with seven native request fields and original request provenance; it is not a generated Return-to-Service Event and asserts no completion. This additional provider/mediator history interface must cover unresolved attempts as well as completed events. It preserves the original return-to-service-events record separately and keeps approval-use coordinates at approval-register.',
            'The host commits work, registry and event-log roots atomically at expected revisions before dispatch, preserves roots on failed commit, protects occupancy and history from public lookup, and durably restores the complete retained authority and governed source events after restart.',
            'Referral records are intents. The host must deliver to the declared owners and queues, preserve safety routing through Reliability Supervisor, and obtain new authority and source review for reentry.',
            'Physical-control requests leave this administrative class through the declared Operations Control Room boundary. The apparatus proves no physical action or equipment state.',
            'Policy amendments require a new source and definition review for a new instance. The source fixture tests current policy withdrawal but does not provide an authentic amended organizational policy.',
        ], 'fixture_facts': [
            'Original source request RTS-REQ-417, NPO-7, EQ-204, WO-7304, IN-552, AP-091, effective time 2026-09-12T14:30:00Z. The original AP-091 signing time is 14:00 and expiry 23:59 exclusive.',
            'Inspection completion at 13:55, participant identifiers, provider channels/revisions, connector identity, generated event identities, gate duration 60 seconds and reservation duration 300 seconds are chosen fixture facts.',
            'The default permit ends at 14:35. Fresh hypothetical source line 56 facts use RTS-REQ-418, WO-7305, IN-553, AP-093, inspection at 14:32, approval at 14:35 and gate/effective time 14:40. The independent changed-business-result correction uses AP-092 at 15:00.',
            'Partial identifier reuse cases deliberately provide internally complete altered external authority facts as apparatus premises, then show that retained HELD or CONSUMED history still withholds local admission. They are not accepted translations of an actually issued later request.',
            'Deployment correspondence, review, source-confirmation, policy-decision and organizational authorization records are synthetic fixture proxy acts. No person has accepted source fidelity for this subject.',
        ], 'recorded_source_interpretations': [
            'After a possibly sent write, leaving prior register status in place means no further status-changing act by this class. It supplies neither rollback nor evidence that the first invocation had no remote effect.',
            'Administrative business-fact failures follow the expressly named Reliability Supervisor route; physical or mixed control uses Operations Control Room Lead. The source interpretation remains subject to independent source review.',
            'Late exact evidence may settle a historical effect without reopening STOPPED work, rerouting, replacing the original terminal/referral history or clearing an earlier ambiguous dispute.',
        ]})
    (HERE / 'source-packet.txt').write_bytes(SOURCE_PATH.read_bytes())
    write('source-coverage.json', coverage(cases, base))
    write('case-inventory.json', {'candidate_pin': candidate_pin(), 'status': 'AUTHOR_DERIVED_BEFORE_CONSUMERS',
        'case_count': str(len(cases)), 'inventory_digest': digest('equipment-source-author-cases', cases),
        'cases': [{'id': row['id'], 'path': '../../cases/equipment-source/' + row['id'] + '.json',
            'operation': row['operation'], 'input_digest': digest('equipment-source-case-input', row['input']),
            'expected_digest': digest('equipment-source-case-expected', row['expected']),
            'raw_sha256': 'sha256:' + hashlib.sha256(canonical_bytes(row) + b'\n').hexdigest()} for row in cases]})
    paths = sorted(p for p in HERE.rglob('*') if p.is_file() and p.name != 'artifact-index.json'
        and p.suffix in {'.json', '.jsonl', '.txt', '.md'})
    write('artifact-index.json', {'candidate_pin': candidate_pin(), 'status': 'AUTHOR_DERIVED_BEFORE_CONSUMERS',
        'source_sha256': raw_sha(SOURCE_PATH), 'artifacts': [
            {'path': str(path.relative_to(HERE)), 'sha256': raw_sha(path)} for path in paths]})
    print({'cases': len(cases), 'artifacts': len(paths), 'candidate_pin': candidate_pin(),
        'inventory_digest': digest('equipment-source-author-cases', cases)})


if __name__ == '__main__':
    main()
