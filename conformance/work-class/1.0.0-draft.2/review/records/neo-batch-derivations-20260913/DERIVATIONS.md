# Amendment batch derivations, 2026-09-13

Written from the amended specification text before constructing any case and before reading either
consumer's batch changes. Pin after the batch edits: `sha256:ed4ea75218780d1b29b23ae1657cba0c9b9bf864fae24f0a2fe24825435502b4`.
Each entry names the rule, the construction and the expected result. Implementation output never decides.

## CR-01 deployment evidence (LIFE-003, PROTOCOL deploy)

Base: the accepted deployment fixture (`fixture_factory.deployment`), which now carries an accepted
correspondence mapping every source obligation to the complete readback path set with empty residue, an
accepted source confirmation over `digest("work-class-source", source)` with the complete obligation list,
and an accepted policy decision over the definition digest, each digest inside the authorization subject.

1. Substituted definition. The correspondence record is the accepted record of another definition (its
   `work_class_digest` and `subject_digest` are that other digest); the authorization's
   `correspondence_evidence_digest` equals this record's digest, so the digest check passes and the
   correspondence form's work-class digest equality fails. Refusal `BINDING_MISMATCH`, no state.
2. Pending residue. One provision path is moved from the mapping to `unsupported_provision_paths` with a
   residue row of disposition `PENDING`; partition and coverage hold. A pending residue row yields
   `EVIDENCE_UNAVAILABLE`, no state.
3. Pending nested review. Correspondence status `ACCEPTED`, nested review status `PENDING`, review subject
   digest rebound. `EVIDENCE_UNAVAILABLE`, no state.
4. One identifier, two kinds. The policy-decision record's `evidence_id` equals the source confirmation's.
   Both records are otherwise valid and their digests are in the authorization. Identifier distinctness fails:
   `BINDING_MISMATCH`, no state (wording decision W2).
5. Rejected policy decision. Status `REJECTED`, digest rebound in the authorization. `EVIDENCE_UNAVAILABLE`.
6. Restart with a stale correspondence digest. A committed lifecycle checkpoint's
   `deployment_correspondence_evidence_digest` is changed to another digest and the last transition is
   recommitted so only the evidence binding is wrong; a fresh available CLOCK asks for restart. LIFE-019:
   changed digest or broken binding is `STATE_INVALID`; the refusal returns the exact supplied state.

Each of 1 to 5 binds the digests so that exactly the named check fails; in every case the organizational
authorization passes its own checks, so the refusal is the new rule's and not an earlier one.

## D2 (LIFE-010): D2-270 rebuilt

One permit, attempt A `NOT_SENT` with acknowledgement `NONE` (DISPATCH_REFUSED, NATIVE_NOT_SENT, occurrence
stays PERMITTED, permit still dispatchable), then attempt B `SENT` acknowledged `ACCEPTED` (ACKNOWLEDGED,
occurrence DISPATCHED). A `NO_EFFECT_ESTABLISHED` assertion bound to attempt A with a valid nonnull completion
authorization (organization equal to the deployment organization, subject `digest("no-effect-completion", ...)`
over the seven values, scope those values, recorded no later than observed_at, expiry later). Attempt A is not
disqualified (D2), so the authorization is admitted and checked; the attempt set is not final and safe because
B exists, so classification `UNEXPECTED`, `completion_mismatch:true`, `mismatch_reason:UNEXPECTED_EFFECT`; the
registry RELEASE/NO_EFFECT with a mismatched record is `EFFECT_DISPUTED`, reservation `DISPUTED`, blocked
partitions the reservation's own keys; lifecycle decision `DISPUTED` with reason codes
`BUDGET_EFFECT_DISPUTED`, `UNEXPECTED_EFFECT`; the outcome is `disputed:true` (D1); the occurrence becomes
`OUTCOME_UNKNOWN`; nothing completes, routes or releases. The companion D2-271 (assertion bound to B, final and
safe) keeps its result.

## D3 (LIFE-014, LIFE-019): restart after an evidence-only expiry

Checkpoint: D2-237's result, in which a dependency-blocked occurrence's due deadline expired evidence-only and
the active row still names the deadline. A fresh available CLOCK asks for restart. The list names every deadline
declared for the step with a retained record in any status, so the checkpoint is admitted: `CLOCK_RECORDED`,
clock appended, nothing else changes.

## D4 (LIFE-010 foreign branch, RES-WIRE-003): D2-180 and D2-232 rebuilt

A foreign established effect whose `actual_fields` are the attributed step's bound fields plus the declared
status field projects through the completion bindings: `observed_request` carries the bound fields only, the
status field is ignored. For a known reservation the record is projectable, so `blocked_partitions` is the
sorted unique union of the original reserved key and the projected key; when they coincide, one entry. A record
with a field that is neither bound nor declared, or a bound field missing, has `observed_request:null` and blocks
the anchor with one null-key entry only. D2-180's expected registry state changes from the anchor-level entry to
the projected union; D2-232's foreign setup likewise.

## D5 (RES-WIRE-004): D2-232 and C2-unknown-keeps-blocked-dispute rebuilt

A clean record (`completion_mismatch:false`) against a `DISPUTED` reservation: receipt decision
`EFFECT_DISPUTED`, receipt reason the record's own effect reason. D2-232's second matching effect carries
`MATCHED_EFFECT`, so the lifecycle reason codes are `BUDGET_EFFECT_DISPUTED` and `MATCHED_EFFECT` (two codes, as
the contract label says). C2-unknown-keeps-blocked-dispute's clean UNKNOWN carries `UNKNOWN_OUTCOME` in the
BUDGET detail; lifecycle reason codes `BUDGET_EFFECT_DISPUTED`, `UNKNOWN_OUTCOME`; outcome `disputed:true`
(D1); occurrence stays `BLOCKED_DISPUTE`.

## D6 (LIFE-019): restart of a completion-based DISPUTED obligation

Checkpoint: a committed dependency-disputes case whose branch obligation became `DISPUTED` after its
discharged head received a conflicting conclusive record (the disputing record is not the completion
evidence). A fresh available CLOCK asks for restart. The completed head has disputed conclusive evidence under
D6, its frontier intersects its own dependency-affected set, so the obligation's DISPUTED variant is valid:
`CLOCK_RECORDED`, nothing else changes.

## D7 (LIFE-009): fresh attempt on a consumed permit

Base: a permit consumed by attempt A (`SENT`, `ACCEPTED`; occurrence `DISPATCHED`).
1. Attempt B under a fresh identifier, `SENT`, acknowledgement `NONE`, same request bytes. Retained as a
   dispatch record; decision `DISPUTED`, reasons `LATE_OR_PROHIBITED_DISPATCH` (the base row SENT/NONE adds
   none); the occurrence stays `DISPATCHED`; the DISPATCH detail names attempt B.
2. Attempt B under a fresh identifier, `NOT_SENT`, acknowledgement `NONE`. Nothing reached the connector:
   refusal `PREREQUISITE_MISSING`, exact supplied state returned.

## Procedure note

The JSON schemas under `library/` are generated by `review/build-contract-schemas.py`; a schema change is made
there and regenerated, then `build-contract-requirements.py` and `build-contract-manifest.py`, then
`python/input/` is synced from `library/` (the Python consumer's embedded contract copy). TypeScript reads the
library directly.
