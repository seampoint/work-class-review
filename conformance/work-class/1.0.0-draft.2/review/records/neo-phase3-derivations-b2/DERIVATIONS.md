# Batch B2 pre-comparison derivations

Candidate: `seampoint.work-class/1.0.0-draft.2`
Pin: `sha256:674d2f97e5a6b8f6e812ab140a1f821544fbdd4faa3ec6a03917225a9324c5c0`
Written 2026-09-11, before constructing any case input or expected value for these five cases, and before opening any existing `expected` member.

Sources read: `LIFECYCLE.md` (LIFE-010, LIFE-011), `RESERVATIONS.md` (RES-008), `RESERVATION-RECORDS.md` (RES-WIRE-002, RES-WIRE-003, RES-WIRE-004), and `requirements.json`. No implementation source, adapter output, runner report, or existing case `expected` member was consulted.

## Governing rules extracted

**Classification mapping (LIFE-010).** The lifecycle determines the outcome classification before constructing a shared-budget event. `EFFECT_ESTABLISHED` maps to `SETTLE/EFFECT`, `OUTCOME_UNKNOWN` to `SETTLE/UNKNOWN`, and `NO_EFFECT_ESTABLISHED` to `RELEASE/NO_EFFECT`, including when a changed, disqualified or incomplete attempt account makes the lifecycle classification `UNEXPECTED`.

**Final safe attempt set (LIFE-010).** For one permit, distinct attempts are the unique stable `dispatch_attempt_digest` values ordered by the decision-receipt sequence that first retained each value. A no-effect assertion has a final safe attempt set **only when** its stable attempt digest is the last value in that order **and** every other distinct attempt for the permit has attempt status `NOT_SENT` with no retained `ACCEPTED` acknowledgement. An acknowledgement update for the same stable attempt does not create another attempt in this ordering.

**completion_mismatch (LIFE-010).** True exactly when the dispatch-attributed request differs from the permit, a dispatch-disqualifying reason applies, a no-effect assertion lacks a final safe attempt set, or the lifecycle classification is `UNEXPECTED` or `CONFLICTING`. When changed native arguments or another dispatch-disqualifying fact causes the mismatch, `mismatch_reason` is `NATIVE_REQUEST_MISMATCH`; **every other true mismatch uses `UNEXPECTED_EFFECT`**. A false mismatch uses null. The reservation transition treats `completion_mismatch:true` as disputed exposure.

**Duplicate construction (LIFE-010).** For a lifecycle `DUPLICATE`, the consumer copies the retained same-fact outcome's complete embedded reservation-native record and changes only `id` and `evidence_ref`. It preserves `completion_mismatch`, `mismatch_reason`, `observed_request`, the original request, outcome, effect identity, occurrence time and no-effect flag exactly. Exact or same-fact duplicates return the established reservation disposition without adding exposure.

**Release preconditions (RES-008, LIFE-011).** `RELEASE` requires complete affirmative no-effect evidence from the declared no-effect provider and source, bound to the exact occurrence, reservation and original native request, plus a separate `ACCEPT` organizational release act with its selected authority basis and attributed return. The native record must have `completion_mismatch:false` and `mismatch_reason:null`. A step with `FAILURE_EDGE` records `FAILED` with reason `NO_EFFECT_ESTABLISHED`, completes the occurrence as `NO_EFFECT`, and follows that exact edge.

---

## D2-241 — `STEP/DISPUTED/UNKNOWN/BUDGET_EFFECT_DISPUTED+NATIVE_REQUEST_MISMATCH+UNKNOWN_OUTCOME`

Cites `LIFE-010`, `RES-WIRE-003`.

An `OUTCOME_UNKNOWN` assertion is attributed to a dispatch request that differed from the committed permit, for a budget-backed occurrence.

Derivation. LIFE-010 maps `OUTCOME_UNKNOWN` to `SETTLE/UNKNOWN`, so the embedded reservation event kind is `SETTLE` with native outcome `UNKNOWN`. The dispatch-attributed request differs from the permit, which is one of the four conditions making `completion_mismatch` true; because changed native arguments cause it, `mismatch_reason` is `NATIVE_REQUEST_MISMATCH` rather than `UNEXPECTED_EFFECT`. The reservation transition treats `completion_mismatch:true` as disputed exposure even when the provider attributes the effect to the changed dispatch request. LIFE-011 adds that an `UNKNOWN` outcome records that the effect has not been established, so the occurrence remains unresolved, every unsettled reservation remains charged once, and the work graph does not advance along a success route.

Expected result. `STEP` with disposition `DISPUTED` and classification `UNKNOWN`. Reason codes sort to `BUDGET_EFFECT_DISPUTED`, `NATIVE_REQUEST_MISMATCH`, `UNKNOWN_OUTCOME`. The native fact is retained. The reservation becomes or remains `DISPUTED`, unresolved pending exposure stays charged, the affected anchors are blocked, and the occurrence neither routes nor completes.

## D2-242 — `STEP/DISPUTED/UNEXPECTED/BUDGET_EFFECT_DISPUTED+NATIVE_REQUEST_MISMATCH+UNEXPECTED_EFFECT`

Cites `LIFE-010`, `RES-WIRE-003`.

A `NO_EFFECT_ESTABLISHED` assertion is attributed to a dispatch request that differed from the committed permit, for a budget-backed occurrence.

Derivation. LIFE-010 states directly that a no-effect assertion attributed to a changed or otherwise disqualified dispatch carries **null** completion authorization and is retained as `UNEXPECTED`. The classification is therefore `UNEXPECTED`, not `NO_EFFECT_ESTABLISHED`, before any release is considered. The assertion still maps to `RELEASE/NO_EFFECT` as the embedded reservation event kind. `completion_mismatch` is true because the attributed request differs from the permit, and `mismatch_reason` is `NATIVE_REQUEST_MISMATCH`. RES-008 is explicit that a changed or otherwise disqualified dispatch attribution uses exactly that pair and that the transition retains it as disputed exposure and cannot release capacity.

Expected result. `STEP` with disposition `DISPUTED` and classification `UNEXPECTED`. Reason codes sort to `BUDGET_EFFECT_DISPUTED`, `NATIVE_REQUEST_MISMATCH`, `UNEXPECTED_EFFECT` — the mismatch reason and the effect reason are distinct members. Completion authorization on the retained record is null. The reservation becomes or remains `DISPUTED`, unresolved pending exposure stays charged, the affected anchors are blocked, and no release, completion or route occurs.

## D2-263 — `STEP/OUTCOME_RETAINED/DUPLICATE`

Cites `LIFE-010`, `RES-WIRE-002`, `RES-WIRE-004`.

A budget-backed governed effect duplicates a retained same-fact `CONFLICTING` outcome under a new evidence identity and reference.

Derivation. The duplicate rule in LIFE-010 is mechanical: the consumer copies the retained same-fact outcome's complete embedded reservation-native record and changes only `id` and `evidence_ref` to the new evidence values. Everything else is preserved exactly, including `completion_mismatch:true`, `mismatch_reason`, `observed_request`, the original request, outcome, effect identity, occurrence time and the no-effect flag. A duplicate of `UNEXPECTED` or `CONFLICTING` therefore remains completion-mismatched, and the reservation transition recognizes it as the same fact rather than inventing a second conclusion. LIFE-010 adds that exact or same-fact duplicates return the established reservation disposition without adding exposure. RES-WIRE-004 requires every admitted event to increment the registry revision by one, so a receipt is still produced.

Expected result. `STEP` with disposition `OUTCOME_RETAINED` and classification `DUPLICATE`. The embedded reservation-native record differs from the retained one only in `id` and `evidence_ref`, with `completion_mismatch:true` carried over. The reservation transition returns the established disputed disposition without adding exposure and without creating a different conflict. The completed route and the blocked dependencies are unchanged.

## D2-270 — `STEP/DISPUTED/UNEXPECTED/BUDGET_EFFECT_DISPUTED+UNEXPECTED_EFFECT`

Cites `LIFE-010`, `LIFE-011`, `RES-WIRE-003`.

A budget-backed permit has attempt A recorded `NOT_SENT` with no accepted acknowledgement, then attempt B recorded `SENT`. A first `NO_EFFECT_ESTABLISHED` assertion with valid completion authorization binds attempt A.

Derivation. The attempt-set rule decides this. Distinct attempts are ordered by the decision-receipt sequence that first retained each stable `dispatch_attempt_digest`, so the order is A then B. The assertion binds A, which is not the last value in that order, so the attempt set is not final and safe regardless of A's own `NOT_SENT` status. LIFE-010 covers this case explicitly: an assertion whose authorization is valid but whose attempt set is not final and safe is retained as `UNEXPECTED`, and the authorization cannot close the occurrence or release exposure. `completion_mismatch` is true because a no-effect assertion lacks a final safe attempt set. The attributed request did not change and no dispatch-disqualifying reason applies to A itself, so this is not the `NATIVE_REQUEST_MISMATCH` branch; every other true mismatch uses `UNEXPECTED_EFFECT`. That is why this judgment carries two reason codes where D2-242 carries three.

Expected result. `STEP` with disposition `DISPUTED` and classification `UNEXPECTED`. Reason codes sort to `BUDGET_EFFECT_DISPUTED`, `UNEXPECTED_EFFECT`. The no-effect fact is retained with `completion_mismatch:true`. Attempt B remains possibly effective, the reservation becomes or remains `DISPUTED`, pending exposure stays charged, and no completion, route or release occurs.

## D2-271 — `STEP/FAILED/NO_EFFECT_ESTABLISHED`

Cites `LIFE-010`, `LIFE-011`, `RES-008`.

The same two attempts, but the assertion binds attempt B and supplies release administration.

Derivation. B is the last distinct attempt in the receipt-sequence order, and the only other distinct attempt, A, has status `NOT_SENT` with no retained `ACCEPTED` acknowledgement. Both conditions of the final-safe-attempt-set rule hold. The LIFE-010 outcome table then gives the admitted row: `NO_EFFECT_ESTABLISHED` with exact affirmative evidence, completion authorization for the unresolved occurrence, and a final safe attempt set produces one `RELEASE` transition with native outcome `NO_EFFECT`, closes the unresolved occurrence as `NO_EFFECT`, and follows its failure behavior. `completion_mismatch` is false and `mismatch_reason` null, which RES-008 requires before capacity can be released, and the separate `ACCEPT` organizational release act with its selected authority basis and attributed return supplies the release administration. LIFE-011 fixes the work-side result: a step with `FAILURE_EDGE` records `FAILED` with reason `NO_EFFECT_ESTABLISHED`, completes the occurrence as `NO_EFFECT`, and follows that exact edge.

Expected result. `STEP` with disposition `FAILED` and reason `NO_EFFECT_ESTABLISHED`. The reservation is released exactly once, removing the reserved exposure. The occurrence completes as `NO_EFFECT` and the declared failure edge is followed. Release does not make the operation successful.

---

## The pair D2-270 and D2-271

These two differ in exactly one input fact: which attempt the assertion binds. Everything else — the permit, both dispatch rows, the evidence content, the completion authorization — is the same fixture. They must be built together so the contrast is exact, and the divergence in expected result must be traceable solely to the attempt-set rule rather than to any other fixture difference.

## What these derivations do not establish

They fix the expected judgment, classification, reason codes and state consequence for each case from the normative text alone. They do not fix the canonical bytes, which follow from fixture construction. They are recorded so an independent reviewer can confirm the judgment was derived before any expected value was opened, and so any later disagreement between these derivations and the constructed cases is visible rather than silently reconciled.
