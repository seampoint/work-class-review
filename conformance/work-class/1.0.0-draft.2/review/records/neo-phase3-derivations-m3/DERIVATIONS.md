# M3 derivations, restart and checkpoint integrity — 2026-09-12

Candidate pin `sha256:674d2f97e5a6b8f6e812ab140a1f821544fbdd4faa3ec6a03917225a9324c5c0`. Sealed before
construction.

## D2-251 — `REFUSED/STATE_INVALID`

An `ACTIVE` checkpoint contains a pass whose complete obligation inventory is `DISCHARGED` but not
`JOINED`.

Derivation. `LIFE-019` decides it in one sentence: "If an `ACTIVE` state contains a pass whose
complete obligation inventory is `DISCHARGED`, that checkpoint is invalid because the eligible join
should have fired atomically." `PAR-001` supplies the reason that makes it atomic: "When every
obligation in the exact child-pass reference has status `DISCHARGED` during an eligible transition,
the child join marks them `JOINED` and resumes the one parent obligation that waits on that pass",
and "When the join fires, every `DISCHARGED` obligation in that pass becomes `JOINED` and retains
its completion basis." So no admissible `ACTIVE` checkpoint can rest between the final discharge and
the join.

The contrast is explicit and is what makes this a state-integrity rule rather than a timing
accident: "A `STOPPED` state may contain an all-`DISCHARGED`, not-`JOINED` pass only when the
retained stop decision and the direct completion bases prove that the join was suppressed by branch
or object stop, stopped-instance late evidence, or fixed-point preflight failure." The instance here
is `ACTIVE` with no stop decision, so that exception cannot apply.

Expected result. A stateful refusal: `REFUSED` with code `STATE_INVALID`, returning the exact
supplied work state unchanged, creating no permit, reservation or decision receipt. The refusal is
reached during state admission, before the event is considered, so the event's own shape does not
affect the outcome.

## D2-247 — `STEP/PERMITTED`

A fresh process receives a valid `ACTIVE` checkpoint whose parent obligation is `WAITING` on an
exact existing incomplete child pass, then receives a proposal for one `OPEN` child occurrence with
current accepted authority and no shared budget.

Derivation. `LIFE-019` admits a checkpoint by replaying its retained structure: the waiting variant
is closed and admissible when the child-pass identity, the outer prefix, the obligation inventory
and the acyclic nesting all agree. Nothing about the pass is complete, so the rule above does not
bite. `LIFE-007` then governs the proposal itself: current accepted authority, no shared budget, so
the decision is `PERMITTED` with an empty reason set and exactly one permit created. `PAR-001` keeps
the parent obligation `WAITING` with its child-pass reference retained, because only the child join
resumes it, and no obligation in that pass has completed.

Expected result. `STEP`, disposition `PERMITTED`, empty reason codes, one new permit, the child
occurrence moving to `PERMITTED`, and the parent obligation still `WAITING` on the same pass.

## D2-250 — `STEP/OUTCOME_RETAINED/LATE_MATCHED`

A one-object fan-out is in a `STOPPED` instance, and a matching effect reaches its still-active,
non-`BLOCKED_DISPUTE` object occurrence with no shared budget.

Derivation. `LIFE-012`: "A matching effect that arrives after deadline closure or instance stop is
`LATE_MATCHED`", and evidence after a stop "cannot create a new permission, erase an earlier
closure, reopen completed routing". The same requirement's stopped-instance table row moves the
still-active non-`BLOCKED_DISPUTE` sibling to completed with `late:true`, null route fields and the
evidence-derived disposition, and discharges its directly owning obligation without firing the join.
`LIFE-006` maps `EFFECT_OBSERVED/LATE_MATCHED` to `LATE_EFFECT`, with no budget row to add since
there is no shared budget.

`LIFE-019` is what makes the resulting checkpoint admissible: the pass ends all-`DISCHARGED` and not
`JOINED`, which an `ACTIVE` state may never contain, but "A `STOPPED` state may contain an
all-`DISCHARGED`, not-`JOINED` pass only when the retained stop decision and the direct completion
bases prove that the join was suppressed by branch or object stop, stopped-instance late evidence,
or fixed-point preflight failure." Here the retained stop decision plus the direct completion basis
supply exactly that proof. `FAN-001` fixes the object-region identity and its single object pass.

Expected result. `STEP`, disposition `OUTCOME_RETAINED`, classification `LATE_MATCHED`, reason codes
`LATE_EFFECT`. The object occurrence moves to completed with `late:true` and null route fields, its
owning obligation discharges without firing the join, and the instance stays `STOPPED`.

## What these derivations do not establish

They fix the judgment, classification, reason codes and state consequence from the text. They do not
fix canonical bytes, which follow from construction.
