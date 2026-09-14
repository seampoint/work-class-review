# Independent review round at pin 5a75779d (2026-09-13)

Workflow `wf_a813bfe2-859`, 10 agents, 2.06M subagent tokens. Five read-only reviewers over `git diff 7ce93525..2a3f70bd` (normative text and schemas, TypeScript consumer, Python consumer, sepsis and roe-engagement specimens with the SEI mapping, access-card and supplier-payment specimens with the 2026-09-11 specimen review blockers), each followed by one skeptic that tried to refute every finding. Reviewers derived from the text before comparing. Full structured results: `freeze-review-20260913/result.json`; reviewer probes under `/Volumes/ssd/agent-data/claude/freeze-review/` (scratch, not a record).

Result: 34 findings raised, 5 refuted by their skeptics (F7, F8, NS-05, NS-07, NS-09), 28 confirmed and 1 uncertain (AC-SPEC-002). Prior blockers: SPECIMEN-DIGEST-001, SPECIMEN-HOST-CONTEXT-001 and AC-REV-003 resolved; AC-REV-001 and AC-REV-002 open (the skeptic agreed with every status).

## Dispositions

Fixed in both or one consumer because the text decides (overnight authorization, one repin with the batch below):

| Finding | Defect | Change | Case |
|---|---|---|---|
| TS-01 | TypeScript nulled `observed_request` when the status value was in neither list | observed request no longer depends on the status lists | `C2-status-outside-lists-keeps-observed-request` |
| TS-02 | TypeScript admitted a clean EFFECT with a null observed request | phase-5 `INPUT_INVALID` | `C2-refuse-clean-effect-null-observed-request` |
| PY-2 | Python did not treat NOT_SENT with an ACCEPTED acknowledgement as consuming the permit | counts the accepted acknowledgement | `C2-fresh-not-sent-after-not-sent-accepted` |
| PY-3 | Python chose phase-4 authority codes by loop order | accumulates and selects by phase order | `C2-authority-missing-return-and-expired-channel`, `C2-authority-expired-channel-and-pending-grant` |
| PY-4 | Both consumers rechecked only the review-record digests on restart | both recheck statuses, subjects, scope, times and distinct identifiers | `C2-restart-policy-decision-subject-mismatch`, `C2-restart-source-confirmation-pending`, `C2-restart-correspondence-after-authorization-clock` |

Reverted: PY-1. The observed-request-versus-actual-fields name check added earlier on 2026-09-13 refused every budget-backed effect under a completion binding that renames a field, which COMPOSITION 2.2 allows and LIFE-010 prescribes. Both consumers return to the prior behavior; cases `C2-refuse-observed-request-not-actual-projection` and `C2-refuse-observed-request-missing-actual-field` are removed (derivations 28 and 29 withdrawn). The underlying question goes to Jeff.

Clarifying sentences applied (no observable result changes in either consumer; overnight authorization 1):

- F1 and PY-6, RESERVATION-RECORDS RES-WIRE-004: UNKNOWN_RESERVATION and then LATE_EFFECT_AFTER_RELEASE take precedence over every other reason, including the ordered list for a clean record, which now begins "Otherwise". D2-197 and both consumers already behave this way.
- F2, LIFECYCLE LIFE-010: the inherently disputed classification sentence excludes a `BLOCKED_DISPUTE` occurrence, which stays `BLOCKED_DISPUTE`, matching LIFE-006 and LIFE-013.
- F6, RESERVATION-RECORDS: the known-reservation `blocked_partitions` sentence names the single null-key entry for an unprojectable fact.
- F9, LIFECYCLE LIFE-006: the DISPUTED governed-effect row gives the `UNKNOWN` consequence.
- NS-01, LIFECYCLE LIFE-006: an effect observation that applies a registry result carries `BUDGET`, as every committed case and specimen already does.

Non-normative records corrected: F10 (CONTRACT-DECISIONS S1 summary now says completion, not activation); NS-02 (roe-02 basis is RA 4.3, marked a synthetic extension); NS-06 (sepsis provenance statements agree); NS-08 (engagement count marked synthetic); NS-10 (variant 9 no longer claims instance A's effect stands); AC-SPEC-001 (access-card correspondence review relabelled a synthetic proxy); AC-SPEC-002 (READMEs state the organizational authorization evidence is synthetic); AC-SPEC-003 (READMEs name the pin by reference); AC-REV-002 (access-card README states correspondence is mechanical coverage evidence). NS-03 and NS-04 recorded as sepsis exposed rules 7 and 8 with a proposed draft 3 disposition.

Held for Jeff (behavior-changing or design):

1. F4, TS-03, PY-5: LIFE-003 sets no order between `EVIDENCE_UNAVAILABLE` and `BINDING_MISMATCH` across the three deployment review records, and the consumers diverge on two-fault deployments.
2. F3, TS-04, PY-7: a fresh `REJECTED` attempt without an accepted acknowledgement on a consumed permit. Both consumers refuse `PREREQUISITE_MISSING`; two skeptics read LIFE-009 line 139 as admitting it (`DISPATCH_REFUSED` when the request matches, `DISPUTED` when it changed).
3. F5: the lifecycle AUTHORITY detail caps `failed_checks` at 256 rows; the authority result is unbounded.
4. PY-1: how a reservation consumer relates a nonnull observed request to actual fields when bindings rename fields.
5. AC-REV-001: no accepted independent review exists for the current access-card correspondence subject.
6. Sepsis exposed rules 7 and 8: dispositions.
