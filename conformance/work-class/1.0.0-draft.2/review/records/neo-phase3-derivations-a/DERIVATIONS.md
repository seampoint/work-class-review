# Family A derivations, sealed before construction — 2026-09-12

Candidate pin `sha256:674d2f97e5a6b8f6e812ab140a1f821544fbdd4faa3ec6a03917225a9324c5c0`. Derived from
the normative text only. No implementation source or adapter output was consulted for the judgments
below; implementation source was read earlier this session for construction mechanics only.

## D2-263 — `STEP/OUTCOME_RETAINED/DUPLICATE`

Not re-derived. Its derivation is sealed in the B2 seal at
`/Volumes/ssd/agent-data/claude/neo-phase3-derivations-b2/DERIVATIONS.md`, sha256
`16ccb3a3669ccd956699a34cd540c1b58c01768f33ae9db0407c661452890555`. That derivation governs.

## D2-235 — `STEP/DISPUTED/LATE_MATCHED/BUDGET_EFFECT_DISPUTED+HISTORY_UNCORROBORATED+LATE_EFFECT`

Cites `LIFE-006`, `LIFE-010`, `LIFE-012`, `RES-WIRE-003`.

A budget-backed occurrence has a pending deadline. An available clock event satisfies the deadline
before any effect arrives, so the occurrence closes as `EXPIRED` and its route is decided. A matching
established effect for the retained permit and stable dispatch attempt then arrives, with a supplied
journal that never recorded the effect's prescribed committed event.

Derivation. The dispatch exactly matches the permit and is eligible, and the evidence's actual
fields match the completion carrier, so the lifecycle classification would be `MATCHED`. `LIFE-012`:
"A matching effect that arrives after deadline closure or instance stop is `LATE_MATCHED`." The
occurrence is already closed by the deadline, so the classification is `LATE_MATCHED`. No
lifecycle-side mismatch applies: `completion_mismatch` is false and `mismatch_reason` null in the
embedded settlement, because the request did not change and no dispatch-disqualifying fact applies.
`RES-WIRE-003`: "A matching settlement requires `completion_mismatch:false`, equality of attributed,
observed and reserved requests, and all prescribed committed event records in every supplied current
journal. Missing journal corroboration retains `EFFECT_DISPUTED` rather than claiming settlement."
The supplied history is the registry's original opening journal; the prescribed committed event,
whose id is a digest of the budget, effect id and mapping, is absent from it. `RES-WIRE-004`: "An
effect with no mismatch but missing complete journal corroboration uses `HISTORY_UNCORROBORATED`."
So the registry decision is `EFFECT_DISPUTED` with reason `HISTORY_UNCORROBORATED`, the reservation
becomes `DISPUTED`, and the reservation's own original contribution partition is blocked.

`LIFE-010`'s budget-disputed disposition row: "Any other budget-backed classification whose
reservation receipt decision is `EFFECT_DISPUTED` | `DISPUTED` | ... a closed occurrence and its
route remain unchanged." `LATE_MATCHED` is not in the row above it (`FOREIGN`, `UNEXPECTED`,
`CONFLICTING`, `LATE_AFTER_RELEASE`), so this row governs; the occurrence is closed, so its
`EXPIRED` completed row and its route are unchanged. `LIFE-012`: evidence after a deadline "cannot
create a new permission, erase an earlier closure, reopen completed routing." `LIFE-013` names the
classification-specific reason for `LATE_MATCHED` as `LATE_EFFECT`. `LIFE-006` fixes the reason set
as the sorted union of `BUDGET_EFFECT_DISPUTED`, the registry's retained reason and the
classification reason.

Expected result. `STEP`, disposition `DISPUTED`, classification `LATE_MATCHED`, reason codes sort to
`BUDGET_EFFECT_DISPUTED`, `HISTORY_UNCORROBORATED`, `LATE_EFFECT`. Details: a `BUDGET` detail carrying
the registry reason `HISTORY_UNCORROBORATED` and the receipt digest, then the `EFFECT` detail. The
governed outcome is retained, disputed, carrying the receipt digest. The completed `EXPIRED` row and
its route are unchanged; the instance status is unchanged. The reservation is `DISPUTED` with the
original contribution partition blocked; no route, completion or release occurs.

## D2-197 — `STEP/DISPUTED/LATE_AFTER_RELEASE`

Cites `LIFE-010`, `LIFE-012`, `LIFE-013`.

A budget-backed permit's final safe attempt received an authorized `NO_EFFECT_ESTABLISHED` assertion,
which released the reservation and closed the occurrence as `NO_EFFECT` along its failure edge
(the D2-271 state). A matching `EFFECT_ESTABLISHED` record with a distinct evidence identity then
arrives for the same provider-native operation identity, governed permit and stable dispatch-attempt
digest.

Derivation. `LIFE-010`: "`LATE_AFTER_RELEASE` is the directional special case in which established
effect evidence follows an authorized no-effect release for the same provider-native operation
identity, permit and stable dispatch-attempt digest." The new record is conclusive and conflicts
with the retained no-effect outcome on the same attempt (an `EFFECT_ESTABLISHED` against a retained
`NO_EFFECT_ESTABLISHED`), and the retained conflicting outcome's classification is
`NO_EFFECT_ESTABLISHED` for the same operation identity, which is exactly the directional case. The
classification is therefore `LATE_AFTER_RELEASE`, not `CONFLICTING`.

The embedded settlement carries no lifecycle-side mismatch: the request matches the permit, the
attempt is eligible, and `LATE_AFTER_RELEASE` is not among the classifications that force
`completion_mismatch:true` (`RES-WIRE-003` names `UNEXPECTED` and `CONFLICTING` for
`UNEXPECTED_EFFECT`). `RES-WIRE-003`'s table: "`RELEASED`; later `EFFECT` | `EFFECT_DISPUTED` |
become `DISPUTED`; restore the unresolved pending charge, retain the actual effect and block affected
partitions." `RES-WIRE-004`: "`UNKNOWN_RESERVATION` and `LATE_EFFECT_AFTER_RELEASE` take precedence
over the native record's mismatch reason," so the registry reason is `LATE_EFFECT_AFTER_RELEASE`.

`LIFE-010`'s disposition table places `LATE_AFTER_RELEASE` in the retained-dispute row: `DISPUTED`,
retain and reconcile conservatively, do not route; that row does not block the occurrence, which is
in any case already closed. `LIFE-013`: a conflicting record marks the prior conflicting outcome
disputed and records the new evidence identity on it. `LIFE-012`: the evidence cannot erase the
earlier closure or reopen completed routing, so the `NO_EFFECT` completed row and the failure route
stand.

Expected result. `STEP`, disposition `DISPUTED`, classification `LATE_AFTER_RELEASE`. Reason codes:
`BUDGET_EFFECT_DISPUTED` and `LATE_EFFECT_AFTER_RELEASE` (the classification reason and the registry
reason coincide, so the sorted set has two members). Details: `BUDGET` with reason
`LATE_EFFECT_AFTER_RELEASE`, then `EFFECT`. The new outcome is retained, disputed, with the prior
no-effect outcome's evidence id in its conflicts; the prior no-effect outcome becomes disputed and
records the new evidence id. The reservation moves from `RELEASED` to `DISPUTED` with its original
contribution partition blocked and the pending charge restored. The completed `NO_EFFECT` row, the
selected failure route and the instance status are unchanged.

## What these derivations do not establish

They fix the judgment, classification, reason codes and state consequence from the text. They do not
fix canonical bytes, which follow from construction. Any later disagreement between these
derivations and the constructed cases is to be recorded, not silently reconciled.
