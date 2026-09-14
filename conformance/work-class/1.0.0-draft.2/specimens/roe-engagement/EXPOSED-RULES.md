# Exposed rules: roe-engagement specimen

Each entry names a general rule that building this specimen showed the draft-2 text cannot express or leaves ambiguous, the paragraphs it touches, the specimen artifact that exposes it, and the smallest wording that would close it. Entries are candidate contract issues for the completion plan's step 4 or for draft 3; none is normative. The specimen was built to the current text in every case, with the nearest expressible construction.

Dispositions, decided 2026-09-13 (option 2 of `review/records/EXPOSED-RULES-DISPOSITION-PROPOSAL-20260913.md`, recorded in `review/CONTRACT-DECISIONS.md`, wording in `review/records/STEP4-WORDING-20260913.md`): E2 is closed in draft 2 and E6 is resolved by a clarifying sentence in draft 2; E1, E3, E4, E5, E7 and E8 are recorded as draft 3 design inputs. The specimen was rebuilt at the step 4 pin with E2's closing text.

## E1. A disputed engagement effect has no attributable human exit

Touches: RES-007 ("An already DISPUTED reservation cannot be renewed or released"), RESERVATION-RECORDS prior-state table (row "DISPUTED; any new attributable fact: remain DISPUTED; perform no automatic resolution"), LIFE-013 ("This candidate has no general dispute-resolution transition"). Exposed by scenario `roe-foreign-effect-other-entity`: the reservation is `DISPUTED`, the mission partition is blocked, the occurrence stays `DISPATCHED`, and no admitted event in draft 2 changes any of that. The direction anticipated this as the deferred CR-02 disposition. The specimen records the retained dispute as the expected behavior.

Disposition: draft 3 design input (human exit from a dispute, CR-02). Variant 8 is unchanged.

Smallest wording: a `RESOLVE` reservation event kind that carries the same selected administration basis and attributable return as `REGISTER`, names one `DISPUTED` reservation and one retained effect record as the accepted conclusion, and moves the reservation to `SETTLED` or `RELEASED` while retaining every record; the lifecycle mirrors it through the governed `EFFECT_OBSERVED` branch with a completion-authorization record for a `BLOCKED_DISPUTE` or `OUTCOME_UNKNOWN` occurrence. Draft 3 (CR-02).

## E2. An authority withholding does not name the failed condition

Touches: AUTH-006 (refusal reasons are the sorted union of failed check reasons; the refusal has an empty path), `authority.schema.json` refusal `reasons` enum, LIFE-006 `AUTHORITY` detail `{code, reasons}`. Exposed by scenarios `roe-confidence-below-bound` and `roe-protected-status`: both return `[AUTHORITY_NOT_ESTABLISHED, AUTHORITY_REQUIRED, CONDITION_VIOLATED]`; only the proposal bytes reveal which rule failed. RA 2.3.1 requirement 4 asks the system to communicate how it decided; the receipt communicates that a condition failed, not which.

Smallest wording: an `AUTHORITY_NOT_ESTABLISHED` refusal carries `failed_checks`, the sorted unique `{purpose, requirement_ref}` pairs of every failed check, and the lifecycle `AUTHORITY` detail copies that list. Schema change to the authority refusal and `decisionDetailAuthority`.

Disposition: closed in draft 2. AUTHORITY-CHECKS now gives every refusal `failed_checks`: for `AUTHORITY_NOT_ESTABLISHED`, one row `{purpose, subject_digest, requirement_ref, at, reason}` per failed phase-5 check, with the first four values exactly those of the check construction table, sorted by canonical bytes and unique, whose reasons equal `reasons`; empty for every other code and for `CLOCK_UNAVAILABLE`. LIFE-007 copies the rows into the `AUTHORITY` detail. The landed wording carries more than the smallest wording above (subject digest, instant and reason per row). In the rebuilt specimen variant 2 names `roe-confidence-at-or-above-bound`, variant 3 `roe-target-not-protected`, variant 5 `roe-demonstrated-intent-present`, and variant 9 the `REVOCATION` query on the envelope, so the two condition variants' records differ by the condition they name. This answers RA 2.3.1 requirement 4 at the record level: the receipt says which rule failed.

## E3. A deadline is anchored to activation, not to the divergence

Touches: COMPOSITION 5.1 ("An elapsed declaration is added to the admitted activation instant"), LIFE-014 (activation record from the retained clock; root deadlines use the deployment clock). Exposed by scenario `roe-no-direction-by-deadline-stop`: the direction bound runs from the occurrence's activation at deployment, so a withholding at `10:01:00Z` and one at `10:09:00Z` leave nine minutes and one minute respectively. RA 2.3.1 requirement 3 measures direction from the divergence. The synthetic source policy (`roe-06`) was written to the expressible anchor. This is the same family as the sepsis handoff's expected gap (a deadline measured from an ancestor occurrence's activation).

Smallest wording: a deadline declares `anchor`, either `ACTIVATION` (this candidate's rule) or `FIRST_WITHHOLDING`; under `FIRST_WITHHOLDING` the deadline record is created by the first admitted `WITHHELD` proposal for the occurrence, with that event's accepted clock as the activation clock, and `activation_clocks` on that `PROPOSE` event carries the copy.

Disposition: draft 3 design input (a deadline anchored to the first withholding). The draft 2 `ELAPSED_FROM_ANCESTOR` due kind does not close it: its anchor is a completed ancestor occurrence, the divergence here is a withholding on the same occurrence, and this deadline sits on the root step, where an ancestor declaration is `DEFINITION_INVALID`. The specimen should not adopt it; roe-06 and the deadline are unchanged.

## E4. A required escalation leaves no runtime trace

Touches: AUTH-001 ("A required escalation creates no implicit message or additional permission. Its runtime delivery remains unqualified"), AUTHORITY-CHECKS static admission ("Required escalation is retained policy; neither definition validation nor authority readiness asserts its delivery"). Exposed by scenario `roe-intent-absent-withheld`: the envelope declares `escalation.kind: REQUIRED` naming the operator role, yet the withheld decision is byte-for-byte the shape it would have under `DECLARED_NONE`. The record cannot show that direction was required.

Smallest wording: a `WITHHELD` proposal whose envelope escalation is `REQUIRED` carries an `ESCALATION` decision detail `{kind, destination_role, authority_ref, decision_required}` immediately after `AUTHORITY` in the LIFE-006 detail order; delivery remains a host obligation recorded in `EXTERNAL-DEPENDENCIES.md`.

Disposition: draft 3 design input (an escalation decision detail).

## E5. No operator-initiated stop event

Touches: LIFE-002 and COMPOSITION 1 (general cancellation excluded), LIFE-006 `STOPPED` row, GB 3.3.13 (emergency stop and manual override). Exposed by the mapping: after a permit is issued, an operator no-go has no lifecycle event; the host must decline to dispatch (a host obligation), the permit expires, and the instance stops only through deadline expiry, `failure_behavior: STOP` or a limit. The specimen's stop is the deadline.

Smallest wording: a fifth event kind `STOP` carrying an accepted organizational-authorization record whose subject is `digest("instance-stop", {specification_pin, work_class_digest, instance_id})` records `STOPPED` with reason `OPERATOR_STOP`; active occurrences retain their statuses as for the actuation-limit stop; a later `DISPATCH_OBSERVED` that may have reached the connector is `DISPUTED` with `LATE_OR_PROHIBITED_DISPATCH`. Draft 3; LIFE-005's four-kind event union and LIFE-006 precedence would change.

Disposition: draft 3 design input (an operator stop event). Draft 2 adds to LIFE-008 that a host honouring a revocation after a permit declines to dispatch and the permit expires unused, which is the host path this entry describes; it adds no event.

## E6. Occurrence consequence of an UNEXPECTED effect with a disputed budget receipt (observed, not exercised here)

Touches: LIFE-006 decision table row "DISPUTED governed effect" (`OUTCOME_UNKNOWN` for an inherently disputed native classification, `BLOCKED_DISPUTE` for a conclusive effect whose budget reconciliation is disputed) and LIFE-010 ("UNEXPECTED has disputed:true"; "When an inherently disputed governed classification concerns an active occurrence, the occurrence becomes or remains OUTCOME_UNKNOWN"; "When a conclusive MATCHED, FAILED, or NO_EFFECT_ESTABLISHED classification is blocked solely by an EFFECT_DISPUTED budget result, an unresolved occurrence becomes BLOCKED_DISPUTE"). A budget-backed `UNEXPECTED` effect is both inherently disputed and a conclusive `EFFECT_ESTABLISHED` record whose reconciliation is disputed, so the two rows select different statuses. Both implementations give `OUTCOME_UNKNOWN`, following the LIFE-010 sentence and the 2026-09-12 decision pinned by D2-242; the supplier-payment expectation `supplier-payment-unexpected-effect` was corrected to that value on 2026-09-13 after reading `BLOCKED_DISPUTE` from the LIFE-006 row. The LIFE-006 row is therefore the sentence to align. Found while deriving variant 8; this specimen built the foreign branch instead and does not exercise the governed `UNEXPECTED` path.

Smallest wording: in the LIFE-006 row, name the classifications explicitly, for example "becomes `OUTCOME_UNKNOWN` for `CONFLICTING` or `LATE_AFTER_RELEASE`, `BLOCKED_DISPUTE` for `UNEXPECTED` and for a `MATCHED`, `FAILED` or `NO_EFFECT_ESTABLISHED` classification whose budget reconciliation is disputed", and align the LIFE-010 sentence. Whichever status the maintainers intend, one sentence must yield.

Disposition: resolved in draft 2. The LIFE-006 row now reads that an unresolved occurrence becomes `OUTCOME_UNKNOWN` for an inherently disputed classification (`UNEXPECTED`, `CONFLICTING` or `LATE_AFTER_RELEASE`), including when its budget reconciliation is also disputed, and `BLOCKED_DISPUTE` only for a conclusive `MATCHED`, `FAILED` or `NO_EFFECT_ESTABLISHED` effect whose budget reconciliation alone is disputed. The row now agrees with LIFE-010, both implementations and the corrected supplier-payment expectation; the alternative sketched above (`BLOCKED_DISPUTE` for `UNEXPECTED`) was not taken. This specimen does not exercise the path, so no derived result changed.

## E7. The operator's decision act has no age bound

Touches: AUTH-002 (DECIDE requires an actual per-instance decision), AUTH-004 ("Each act occurs within root, capacity and occupancy validity and no later than evaluation"), LIFE-008 (permit expiry is the proposal clock plus `permit_seconds`). Exposed by scenario `roe-authorization-expired-before-dispatch` read against the direction's row "operator approval whose delay can invalidate a response: a per-instance human act with a validity window". The window the contract enforces belongs to the permit and starts at the proposal clock; the `INSTANCE_DECISION` act itself is accepted at any earlier instant inside capacity validity. A decision recorded hours before the proposal passes.

Smallest wording: the gate declares `max_decision_age_seconds`; a selected `VERIFY` or `INSTANCE_DECISION` act whose `occurred_at` is earlier than the evaluation instant minus that value fails phase 5 with reason `DECISION_STALE`.

Disposition: draft 3 design input (an age bound on the per-instance decision act).

## E8. Proposal observation fields carry no provenance or freshness

Touches: AUTH-001 ("Observation-based general predicates ... remain unsupported"), AUTH-005 ("independent time-varying facts need a later supported observation predicate contract"), RA 5.7.1. Exposed by the mapping of the situational awareness blackboard: classification, confidence, demonstrated intent and protected status enter as bare typed fields; only revocation observations carry provider, revision, `as_of` and a freshness bound. A stale track record and a current one are indistinguishable to the contract, so the direction's "stale or conflicting observations are indeterminate and hold the dependent action" holds for withdrawal facts only. The mapping row was changed to say so.

Smallest wording: a step field may declare `observation: {provider, source, max_age_seconds}`; a proposal then supplies, for each such field, one record `{field, provider, source, revision, as_of, evidence_ref}` whose `as_of` is no later than the authority clock and within the bound, else the proposal is withheld with `OBSERVATION_STALE`; the permit retains the records. Draft 3 design input, as AUTH-005 already anticipates.

Disposition: draft 3 design input (provenance and freshness on proposal observation fields). Draft 2 adds to AUTH-001 that freshness predicates on proposal fields are among the unsupported predicates in this candidate, which states the limitation without closing it.
