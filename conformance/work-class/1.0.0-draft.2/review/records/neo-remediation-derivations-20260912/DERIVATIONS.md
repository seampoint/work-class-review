# Remediation derivations, 2026-09-12

Written before reading either implementation for these three rules, and before any edit. Candidate
pin `sha256:674d2f97e5a6b8f6e812ab140a1f821544fbdd4faa3ec6a03917225a9324c5c0`. Each rule is derived
for **both** implementations from the text alone; which side currently disagrees is not consulted
here. That ordering is the point: the previous round repaired whichever side was in view.

---

## Rule A. Dependent blocking when a governed effect is disputed

### Text

LIFE-006's occurrence-and-instance consequence table, the two rows that govern a disputed effect:

> | `DISPUTED` governed effect | an unresolved occurrence becomes `OUTCOME_UNKNOWN` for an inherently
> disputed native classification or `BLOCKED_DISPUTE` for a conclusive effect whose budget
> reconciliation is disputed; dependent descendants are blocked; a completed occurrence remains
> unchanged | ... |
> | `DISPUTED` foreign effect | current occurrences do not change | retains its prior status |

LIFE-010's narrative, closing the same subject:

> When any of these disputes concerns an already completed occurrence, the completed row and its
> route stay unchanged; the occurrence is not recreated, but dependent active descendants and
> obligations become blocked.

LIFE-013:

> When a completed occurrence becomes disputed, the consumer computes the dependency-affected set
> consisting of that occurrence and every transitive active or completed descendant through these
> predecessor lists. Every active member other than the completed disputed root becomes
> `BLOCKED_DISPUTE`, and the directly owning `OPEN` obligation for any such occurrence becomes
> `BLOCKED`.

### Derivation

Three separate sentences require dependent blocking and none of them conditions it on the
classification. LIFE-006's governed row lists "dependent descendants are blocked" as its own clause,
parallel to and independent of the clause that decides the occurrence's own status. The occurrence's
own status does split on classification: `OUTCOME_UNKNOWN` for an inherently disputed native
classification, `BLOCKED_DISPUTE` for a conclusive effect whose budget reconciliation is disputed.
The descendant clause does not split. LIFE-010 confirms it for the completed case with the words
"any of these disputes", whose antecedent is the whole preceding enumeration, inherently disputed
and budget-disputed alike.

Two exclusions are equally explicit:

1. **Foreign.** LIFE-006's foreign row says current occurrences do not change. A foreign effect
   "cannot discharge a current occurrence" (LIFE-010) and never establishes an authorized occurrence,
   so it has no descendants to block. Foreign disputes do not block.
2. **Duplicate.** A duplicate's disposition is `OUTCOME_RETAINED`, not `DISPUTED`, so neither row
   reaches it. LIFE-010 adds that "A duplicate or later unknown record does not alter an earlier
   completed disposition." Duplicates do not block.

The blocking itself is LIFE-013's: the dependency-affected set computed through predecessor lists,
every active member other than the disputed root to `BLOCKED_DISPUTE`, and the directly owning `OPEN`
obligation of any such member to `BLOCKED`.

### Required behavior, both implementations

On an admitted `DISPUTED` governed effect whose classification is not `DUPLICATE` and whose path is
not the foreign path, compute the LIFE-013 dependency-affected set from the occurrence the effect
concerns and apply the blocking, whether that occurrence is still active or already completed. The
occurrence's own status follows the split above and is a separate question.

---

## Rule B. A repeated evidence identity appends no outcome record

### Text

LIFE-013:

> A new event carrying an existing `evidence_id` with byte-identical native evidence records
> `OUTCOME_RETAINED/DUPLICATE`, adds no duplicate outcome or exposure because the original outcome
> already retains those bytes, and commits any corresponding idempotent registry receipt. Reusing
> that evidence ID with changed native-evidence bytes is `INPUT_INVALID`. ... A new evidence ID with
> the same fact digest is also `DUPLICATE`; the consumer appends one outcome record with
> classification `DUPLICATE` and the new complete native evidence but does not repeat completion or
> exposure. This representable duplicate rule applies to governed and foreign outcomes.

### Derivation

The paragraph draws one distinction and then removes one possible escape from it. The distinction is
between a repeated evidence **identity**, which adds no outcome record because the retained outcome
already holds those exact bytes, and a fresh evidence identity carrying the same **fact**, which
appends exactly one new outcome record because those bytes are not yet retained anywhere. The escape
it removes is the governed/foreign split: "This representable duplicate rule applies to governed and
foreign outcomes." The sentence exists precisely so that the foreign path cannot be read as having
its own duplicate handling.

So the guard is not a property of the governed path. It is a property of the duplicate rule, and the
foreign path is inside that rule's scope by an explicit sentence.

### Required behavior, both implementations

On an admitted effect whose `evidence_id` already names a retained outcome with byte-identical native
evidence, record `OUTCOME_RETAINED/DUPLICATE` and append no outcome row, on the foreign path exactly
as on the governed path. On a new evidence identity with the same fact digest, append exactly one
outcome row, on both paths.

---

## Rule C. A foreign effect with a disputed budget receipt carries the budget reasons

### Text

LIFE-006, the decision-reason mapping:

> | Any non-`DUPLICATE` effect classification whose budget receipt decision is `EFFECT_DISPUTED` |
> add `BUDGET_EFFECT_DISPUTED` and every reservation receipt reason to the classification-specific
> reasons |
> | `EFFECT_OBSERVED/FOREIGN` | `FOREIGN_EFFECT` |

and, closing the table:

> Rows that say "add" combine with the effect-classification row. The `DUPLICATE` row takes
> precedence and fixes the complete set to `DUPLICATE_EVIDENCE` ... Every other row fixes the
> complete set. No other reason code is admitted for these transitions.

and, on the general construction:

> `reason_codes` is the raw UTF-8 sorted unique union required by the included details and the
> applicable transition rule.

LIFE-010 on the foreign path:

> The registry transition retains the effect as disputed exposure under its known-reservation or
> unknown-reservation rules and blocks every projectable partition or the anchor-level fallback fixed
> by the immutable policy. The work outcome retains the affected anchors and the exact reservation
> receipt digest.

### Derivation

The additive row names its scope as "any non-`DUPLICATE` effect classification". `FOREIGN` is an
effect classification and is not `DUPLICATE`, so the row reaches it on a plain reading of its own
words. The only carve-out the table states is the `DUPLICATE` precedence, which does not apply.

The general construction sentence reaches the same result independently and without relying on the
table row at all. `reason_codes` is the union required by the **included details**. LIFE-010 puts a
reservation receipt on the foreign path, and a decision that carries a `BUDGET` detail therefore owes
that detail's reasons. Two independent routes, one answer.

LIFE-013's foreign paragraph, read in full, states no exception to either. It restricts what a
foreign record can do to an occurrence; it says nothing about reason codes.

### Required behavior, both implementations

A foreign effect whose reservation receipt decision is `EFFECT_DISPUTED` produces the raw UTF-8
sorted unique union of `FOREIGN_EFFECT`, `BUDGET_EFFECT_DISPUTED`, and every reason on that receipt.

### Consequence for two committed cases

`cases/foreign-budget-effects/D2-180.json` and `D2-181.json` assert `["FOREIGN_EFFECT"]` alone
against receipts whose decision is `EFFECT_DISPUTED` and whose reasons are `["UNEXPECTED_EFFECT"]`
and `["UNKNOWN_RESERVATION"]`. Under this derivation their expected bytes are wrong and must become
`["BUDGET_EFFECT_DISPUTED","FOREIGN_EFFECT","UNEXPECTED_EFFECT"]` and
`["BUDGET_EFFECT_DISPUTED","FOREIGN_EFFECT","UNKNOWN_RESERVATION"]` respectively. That is a retracted
assertion by the author, not a regression.

---

## What these derivations do not establish

They fix the required behavior and the reason sets from the text. They do not fix canonical bytes,
which follow from construction, and they say nothing about the four findings the review established
by code reading rather than by running the adapters.
