# Batch B1 pre-comparison derivations

Candidate: `seampoint.work-class/1.0.0-draft.2`
Pin: `sha256:674d2f97e5a6b8f6e812ab140a1f821544fbdd4faa3ec6a03917225a9324c5c0`
Written: 2026-09-11, before constructing any case input or expected value, and before opening any existing `expected` member.

Sources read: `library/work-class-specification/1.0.0-draft.2/LIFECYCLE.md` (LIFE-007, LIFE-008, LIFE-010, LIFE-019), `RESERVATIONS.md` (RES-006), `AUTHORITY.md` (AUTH-005), `Specification.md` (WCS2-006), and `requirements.json`. No implementation source, adapter output, runner report, or existing case `expected` member was consulted.

## Governing rules extracted

**Renewal eligibility (LIFE-007).** A renewal names an occurrence with status `PERMITTED`, the latest permit for that occurrence, an exact unchanged native request, and no dispatch record that consumed or may have reached the connector. Eligibility uses the latest retained available lifecycle clock for the permit source; that retained instant must be at or after the permit's exclusive expiry. Before that point, or without such a clock, renewal is `PREREQUISITE_MISSING`. After retained expiry is established, the new authority input is evaluated normally, and its current clock may be unavailable, producing the ordinary admitted authority withholding.

**Withholding forms (LIFE-007).** Every admitted authority, separation or budget withholding appends exactly one proposal record with disposition `WITHHELD`.
- Authority withholding: records the authority-refusal digest, an **empty** reservation-receipt digest array, a null permit digest, and leaves the registry unchanged.
- Budget withholding: records the **successful** authority-result digest and the one registry withholding receipt digest, commits work and registry withholding receipts together, creates no new or extended reservation.
- All withholding forms record a null `prior_permit_digest` for an initial proposal, or the **prior permit digest for a renewal**.
- A withheld renewal does not supersede or extend the prior permit or reservation.

**Reason-code composition (LIFE-007).** An authority withholding's sorted reason codes are the union of `AUTHORITY_REQUIRED`, the authority refusal code, and every authority refusal reason. A budget withholding's lifecycle reason codes are the sorted union of the reservation receipt's reasons and `BUDGET_WITHHELD`.

**Counters (LIFE-007, LIFE-019).** A renewal does not increment activation or actuation counters and does not create another exposure. `actuations` increments only when an occurrence's **initial** proposal becomes `PERMITTED`.

**Permit supersession (LIFE-008).** `supersedes_permit_digest` is null for an initial permit and names the immediately preceding permit for a renewal.

**Renewal semantics (RES-006).** RENEW identifies an existing `OPEN` or `UNKNOWN` reservation and supplies a complete current authority input for its unchanged exact proposal and envelope with full histories. Remove only this reservation's old unsettled contribution from the provisional pending inventory, then evaluate its same contribution once. Other pending exposure remains charged. On success atomically replace current authority evidence, permit expiry and receipt, returning `RENEWED`, keeping reservation id, occurrence and contributions unchanged. On refusal retain the previous reservation and its charge and do not extend its permit.

---

## D2-173 — `STEP/PERMITTED`

Cites `LIFE-007`, `LIFE-008`, `RES-006`.

A budget-backed occurrence renews its exact expired undispatched permit with current authority, complete current histories, and every affected budget still within bound.

Derivation. The occurrence is `PERMITTED` with the latest permit, the native request is unchanged, and no dispatch record consumed or may have reached the connector, so LIFE-007 classifies this as a renewal rather than an initial proposal. The latest retained available lifecycle clock for the permit source is at or after the permit's exclusive expiry, so eligibility holds and the result is not `PREREQUISITE_MISSING`. Current authority succeeds. The active step's `shared_budgets` is nonempty, so exactly one budget input is supplied and the embedded reservation event kind is `RENEW`, naming the exact reservation retained by the prior permit and preserving its original request, proposal fields, occurrence, contributions and creation time. Under RES-006 the registry removes only this reservation's old unsettled contribution from the provisional pending inventory and evaluates the same contribution once; every affected budget remains within bound, so the registry returns `RENEWED`.

Expected result. `STEP` with disposition `PERMITTED`. The registry state, one proposal record with disposition `PERMITTED`, one new permit and the work decision commit together in a single transition. The new permit's `supersedes_permit_digest` names the immediately preceding permit. The reservation's id, occurrence and contributions are unchanged, and its current authority evidence, permit expiry and receipt are replaced. Exactly one embedded `RENEW` updates that reservation once, so no second exposure is created. Activation and actuation counters are unchanged, including `maximum_actuations` consumption, because the renewal is not an initial proposal becoming `PERMITTED`.

## D2-174 — `STEP/WITHHELD/AUTHORITY_NOT_ESTABLISHED+AUTHORITY_REQUIRED+REVOKED`

Cites `LIFE-007`, `RES-006`.

Current authority is revoked when renewing an expired undispatched permit.

Derivation. Renewal eligibility holds as in D2-173, so evaluation proceeds to current authority. AUTH-005 requires current revocation checks for every selected act; a revoked observation cannot establish permission, and the authority evaluator returns `AUTHORITY_NOT_ESTABLISHED` with reason `REVOKED`. LIFE-007 maps `AUTHORITY_NOT_ESTABLISHED` to an admitted policy withholding rather than an admission refusal. Because authority failed, the reservation transition is never reached.

Expected result. `STEP` with disposition `WITHHELD`. Reason codes are the sorted union of `AUTHORITY_REQUIRED`, the refusal code `AUTHORITY_NOT_ESTABLISHED`, and the refusal reason `REVOKED`, giving `AUTHORITY_NOT_ESTABLISHED`, `AUTHORITY_REQUIRED`, `REVOKED` in raw UTF-8 sorted order. One proposal record is appended with disposition `WITHHELD`, the authority-refusal digest, an empty reservation-receipt digest array, a null permit digest, and the prior permit digest because this is a renewal. The registry is unchanged. The prior permit and reservation remain expired and unextended, and the prior permit is not superseded.

## D2-189 — `STEP/PERMITTED`

Cites `LIFE-007`, `LIFE-019`.

A successful renewal occurs after earlier withheld proposals but before `maximum_proposals` is reached.

Derivation. Each earlier withheld proposal appended one proposal record with disposition `WITHHELD` under LIFE-007. The current renewal is eligible and every check succeeds, so it appends one proposal record with disposition `PERMITTED` and creates one permit. LIFE-019 states that a permit renewal increments neither the activation nor the actuation counter, and that `actuations` increments only when an occurrence's initial proposal becomes `PERMITTED`; this is a renewal, so neither counter moves. The decision receipt sequence advances by one because every admitted transition appends exactly one receipt.

Expected result. `STEP` with disposition `PERMITTED`. The receipt sequence advances by one. Per-step `activations` and `actuations`, and the totals derived from them, are unchanged, so consumption against `maximum_actuations` is unchanged. The new permit supersedes the prior permit.

## D2-208 — `STEP/WITHHELD/AUTHORITY_NOT_ESTABLISHED+AUTHORITY_REQUIRED+CLOCK_UNAVAILABLE`

Cites `LIFE-007`, `AUTH-005`.

Retained lifecycle time establishes permit expiry, but the fresh renewal authority input has an unavailable current clock.

Derivation. The distinction LIFE-007 draws is decisive. Renewal eligibility is established by the latest **retained** available lifecycle clock for the permit source being at or after the permit's exclusive expiry; that condition holds, so the result is not `PREREQUISITE_MISSING`. LIFE-007 then states explicitly that after retained expiry is established the new authority input is evaluated normally and its current clock may be unavailable, producing the ordinary admitted authority withholding. AUTH-005 requires a current clock for every readiness result and states that `UNAVAILABLE` observations cannot establish permission, so the authority evaluator returns `AUTHORITY_NOT_ESTABLISHED` with reason `CLOCK_UNAVAILABLE`. LIFE-007 further notes that a null lifecycle `clock_revision` is representable only on an authority-withheld proposal whose selected clock is unavailable, which is this case.

Expected result. `STEP` with disposition `WITHHELD`. Reason codes sort to `AUTHORITY_NOT_ESTABLISHED`, `AUTHORITY_REQUIRED`, `CLOCK_UNAVAILABLE`. One proposal record with disposition `WITHHELD`, the authority-refusal digest, an empty reservation-receipt digest array, a null permit digest, and the prior permit digest for the renewal. The registry is unchanged. The prior permit and reservation remain unextended and unsuperseded.

## D2-215 — `STEP/WITHHELD/BOUND_VIOLATED+BUDGET_WITHHELD`

Cites `LIFE-007`, `RES-006`.

Current authority succeeds, but budget policy withholds renewal of an expired undispatched permit because the bound is violated.

Derivation. Renewal eligibility holds and current authority succeeds, so evaluation reaches the single reservation transition. Under RES-006 the registry removes only this reservation's old unsettled contribution from the provisional pending inventory and evaluates the same contribution once against the current committed window plus all still-unsettled exposure; the bound is violated, so the registry returns a `WITHHELD` result with reason `BOUND_VIOLATED`. LIFE-007 states that a reservation `WITHHELD` result commits that registry's complete withholding receipt and next state together with one lifecycle proposal record and the lifecycle `WITHHELD` decision, creating no reservation or permit.

Expected result. `STEP` with disposition `WITHHELD`. Reason codes are the sorted union of the reservation receipt's reasons and `BUDGET_WITHHELD`, giving `BOUND_VIOLATED`, `BUDGET_WITHHELD`. The registry withholding receipt, the next registry revision, one proposal record with disposition `WITHHELD` carrying the **successful** authority-result digest, the one registry withholding receipt digest, a null permit digest and the exact prior-permit digest, and the work decision all commit together. No new or extended reservation is created. The prior permit and reservation remain expired, unextended and unsuperseded.

## D2-227 — `REFUSED/CLOCK_INVALID`

Cites `LIFE-010`, `WCS2-006`.

A budget-backed effect observation has `observed_at` later than the selected latest retained registry clock.

Derivation. LIFECYCLE.md LIFE-010 states the rule directly: for every budget-backed effect, `native_evidence.observed_at` is no later than the selected latest retained registry clock, and a later observation is `CLOCK_INVALID` and leaves governed state unchanged so the host can retain and resubmit the raw evidence after supplying a current clock. `budget_inputs` is nonempty, so `clock_revision` is nonnull and identifies the latest retained available lifecycle clock for the registry clock source. The timeline check precedes any interpretation of result fields. `CLOCK_INVALID` is in the common lifecycle admission-refusal vocabulary in PROTOCOL.md, so this is an admission refusal, not an admitted withholding, and no proposal record or decision receipt is appended.

Expected result. `REFUSED` with code `CLOCK_INVALID`. The supplied work state is echoed unchanged with its recomputed state digest, and budget states are unchanged. No decision, decision digest, permit, replay, transition-state digest or transaction digest is produced, because an admission refusal creates no receipt and no revision change. WCS2-006 places retention of the raw evidence and resubmission after admitting a current clock on the host, outside the consumer's result.

---

## What these derivations do not establish

They fix the expected judgment and the state consequence for each case from the normative text alone. They do not fix the exact canonical bytes, which follow from the fixture construction. They are recorded here so that an independent reviewer can confirm the judgment was derived before any expected value was opened, and so that any later disagreement between these derivations and the constructed cases is visible rather than silently reconciled.
