#!/usr/bin/env python3
"""REC-016 exact pending-packet identity exception; source-derived, probe-informed."""
import json
from corpus_common import CASES, candidate_pin, digest, exact_case, write_canonical_json
import recovery_fixture as rec


def main():
    facts = rec.facts_for('2')
    state = rec.disputed(facts)
    group = CASES / 'phase3-pending-identity'
    group.mkdir(parents=True, exist_ok=True)
    for index, kind in enumerate(['packet', 'covered', 'other'], 1):
        evidence = rec.evidence_for(facts, state, attempts=1)
        value = rec.dispose_request(facts, state, 'LEAVE_UNRESOLVED', evidence=evidence,
                                    event_id='leave-pending-' + kind)
        identity = (digest('recovery-evidence', evidence) if kind == 'packet' else
                    evidence['covered_evidence_digests'][0] if kind == 'covered' else 'sha256:' + '9' * 64)
        value['host_evidence']['recovery']['pending_evidence'] = [
            {'target': rec.target_for(state), 'record_digest': identity}]
        reasons = [] if kind == 'packet' else ['RECOVERY_PENDING_EVIDENCE']
        expected = rec.disposition_expected(value, reasons=reasons, effective_result='LEAVE_UNRESOLVED')
        cid = f'C3-P3-PIDENT-{index:03d}'
        write_canonical_json(group / (cid + '.json'), exact_case(
            cid, 'aggregate-step', value, expected, ['REC-008', 'REC-016'],
            'REC-016 consumes only pending identity equal to the complete admitted packet. '
            'A digest listed as a covered native fact is not the packet identity and supplies '
            'no retained irrelevance classification. Other target-relevant pending evidence '
            'adds RECOVERY_PENDING_EVIDENCE. Complete one-attempt inventory adds no contingent '
            'rows. Independently reproduced, source-derived and probe-informed; no consumer '
            'is used to derive expectations. Pending identity=' + kind))
    print(json.dumps({'candidate_pin': candidate_pin(), 'cases': 3}, indent=2))


if __name__ == '__main__':
    main()
