# M2 derivations, ancestor dispute and dependency blocking — 2026-09-12

Candidate pin `sha256:674d2f97e5a6b8f6e812ab140a1f821544fbdd4faa3ec6a03917225a9324c5c0`.

## Process note, recorded rather than smoothed over

D2-248 was probed against both implementations before this prose was written. Its governing
derivation is therefore its judgment-contract row, which carries
`derivation_status: DERIVED_FROM_NORMATIVE_TEXT_BEFORE_IMPLEMENTATION_OUTPUT` and was independently
agreed in `review/review3.json`. The prose below for D2-248 is a restatement of that row against the
text, not a fresh pre-construction derivation, and it should be read with that limit in mind. The
remaining five are sealed here before construction.

## The shared mechanism

`LIFE-013`: "When a completed occurrence becomes disputed, the consumer computes the
dependency-affected set consisting of that occurrence and every transitive active or completed
descendant through these predecessor lists. Every active member other than the completed disputed
root becomes `BLOCKED_DISPUTE`, and the directly owning `OPEN` obligation for any such occurrence
becomes `BLOCKED`." Further: a `DISCHARGED` obligation whose completion frontier intersects the
affected set becomes `DISPUTED`, and a `WAITING` ancestor whose child-pass reference contains a
newly disputed obligation becomes `DISPUTED`, propagating outward. "This candidate has no general
dispute-resolution transition, so clearing the ancestor dispute remains outside the profile."

## D2-248 — `STEP/DISPUTED/CONFLICTING`

One branch obligation `DISCHARGED`, its sibling `OPEN`, and later conflicting conclusive evidence
disputes the completed occurrence in the discharged branch.

Derivation. The second conclusive record shares the branch occurrence's provider-native operation
identity and differs in content, so `LIFE-010` classifies it `CONFLICTING` and `LIFE-006`'s mapping
fixes the reason set to `CONFLICTING_EFFECT`. The disputed occurrence is completed, so `LIFE-013`'s
dependency rule runs: the affected set is that occurrence and its transitive descendants, of which
there are none, so no active occurrence changes and the open sibling obligation is untouched. The
discharged branch obligation's completion frontier is exactly that occurrence, so it becomes
`DISPUTED` while retaining its completion basis. `LIFE-017`: `DISPUTED` obligations do not satisfy
a join, so the pass can never join in this candidate even after the sibling discharges. The
completed row and its selected route remain historical; `LIFE-013` does not rewrite earlier
permission or completed routing.

## D2-233 — `STEP/OUTCOME_RETAINED/MATCHED+DEPENDENCY_DISPUTED`

A descendant dispatched before its completed ancestor became disputed; exact matching effect
evidence arrives while the descendant is `BLOCKED_DISPUTE`, with no shared budget.

Derivation. The evidence matches the permit, the carrier and the attempt, so the classification is
`MATCHED`. `LIFE-010`'s disposition table has a row above the ordinary completion rows: "Any
conclusive `MATCHED`, `FAILED`, authorized `NO_EFFECT_ESTABLISHED`, or `LATE_MATCHED` classification
for an occurrence already `BLOCKED_DISPUTE`, with no shared budget or a `SETTLED`/`RELEASED` receipt
as applicable | `OUTCOME_RETAINED` | Retain the evidence-derived result and reconcile exposure, but
leave the occurrence `BLOCKED_DISPUTE` and its directly owning obligation, if any, `BLOCKED` while
the ancestor dispute remains unresolved. Do not route, fire a join or create a successor. This row
precedes every ordinary or stopped-instance late-evidence row." `LIFE-006`'s mapping: "Any conclusive
effect classification for an occurrence already `BLOCKED_DISPUTE`, with no disputed budget result |
add `DEPENDENCY_DISPUTED` to the classification-specific reasons", and the `MATCHED` row with no
stop condition and no disputed budget contributes nothing, so the complete set is
`DEPENDENCY_DISPUTED`.

Expected. `STEP`, `OUTCOME_RETAINED`, classification `MATCHED`, reason codes `DEPENDENCY_DISPUTED`.
The outcome is retained; the occurrence stays `BLOCKED_DISPUTE`; no route, join or successor.

## D2-236 — `STEP/DISPUTED/LATE_OR_PROHIBITED_DISPATCH`

A previously permitted descendant becomes `BLOCKED_DISPUTE` after an ancestor conflict, then a
matching `SENT` native attempt with acknowledgement `NONE` and an otherwise valid timeline is
reported against that retained permit.

Derivation. `LIFE-009`: "a terminal instance, closed occurrence or occurrence status other than
`PERMITTED` adds `LATE_OR_PROHIBITED_DISPATCH`." The occurrence is `BLOCKED_DISPUTE`, which is not
`PERMITTED`, so the reason applies. "A possibly sent attempt produces `DISPUTED` with
`LATE_OR_PROHIBITED_DISPATCH` and never reopens its route." A `SENT` attempt is possibly sent.
`LIFE-006`: any `DISPATCH_OBSERVED` decision's reason codes are exactly the `DISPATCH` detail's
reasons. The request matches and the permit is neither expired nor superseded, so no other reason
joins. `LIFE-013` leaves the occurrence `BLOCKED_DISPUTE` and its owning obligation `BLOCKED`; the
attempt is retained for reconciliation and dispatchability is not restored.

Expected. `STEP`, `DISPUTED`, reason codes `LATE_OR_PROHIBITED_DISPATCH`, the dispatch record
retained, occurrence unchanged at `BLOCKED_DISPUTE`.

## D2-237 — `STEP/EXPIRED`

An available `CLOCK` event satisfies an `AT_OR_AFTER` pending deadline whose occurrence and
enclosing obligation are already dependency-blocked.

Derivation. `LIFE-014` decides it directly: "A due deadline whose occurrence is `BLOCKED_DISPUTE` is
evidence-only: the occurrence remains `BLOCKED_DISPUTE`, its directly owning obligation, if any,
remains `BLOCKED`, and it contributes no expiry route, join or successor while the ancestor dispute
remains unresolved." This is the explicit contrast with the sentence that follows it, which governs
an eligible non-`BLOCKED_DISPUTE` occurrence and does remove it from active work and follow the
declared expiry relationship. `LIFE-006`: "Normal `CLOCK/EXPIRED`" contributes an empty reason set,
and the decision carries `CLOCK` and `DEADLINE` details but no `ROUTE` detail, because no route is
selected.

Expected. `STEP`, disposition `EXPIRED`, empty reason codes, `CLOCK` and `DEADLINE` details only.
The deadline row becomes `EXPIRED` as evidence; the occurrence stays `BLOCKED_DISPUTE` and stays in
active work; the obligation stays `BLOCKED`; no route, join, successor or instance-status change.

## D2-256 — `STEP/DISPUTED/CONFLICTING`

In one unjoined branch, operation A completed and routed to B, B completed and discharged the branch
obligation, and later conflicting evidence disputes A while a sibling obligation remains open.

Derivation. As in D2-248 the classification is `CONFLICTING` with reason `CONFLICTING_EFFECT`. The
difference is the affected set: `LIFE-013` computes that set as the disputed occurrence "and every
transitive active or completed descendant through these predecessor lists", so it contains A and the
completed descendant B. The discharged obligation's completion frontier is B, which is in the
affected set, so that obligation becomes `DISPUTED` and the pass can never join. Both completed rows
and their routes remain historical. The open sibling obligation is untouched.

## D2-290 — `STEP/DISPUTED` with dependent blocking

Later conclusive evidence disputes the source effect used by a retained descendant permit.

Derivation. The disputing record is a conclusive conflict for the source occurrence's operation
identity, so the classification is `CONFLICTING` with reason `CONFLICTING_EFFECT`. `LIFE-008` makes
the descendant permit's prior-effect basis a retained binding rather than a live recomputation, so
`LIFE-013` "does not rewrite earlier permission or completed routing": the permit stays retained and
valid as a record of what was permitted. `LIFE-013`'s dependency fan-out still applies to the
descendant's active occurrence, which becomes `BLOCKED_DISPUTE`, and its directly owning `OPEN`
obligation, if any, becomes `BLOCKED`. `LIFE-019` keeps the event log and checkpoint bindings intact
across this transition.

## What these derivations do not establish

They fix the judgment, classification, reason codes and state consequence from the text. They do not
fix canonical bytes, which follow from construction. Any later disagreement between these
derivations and the constructed cases is to be recorded, not silently reconciled.
