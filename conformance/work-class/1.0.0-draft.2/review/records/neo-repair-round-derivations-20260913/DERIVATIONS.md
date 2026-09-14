# Gate-2 repair round derivations, 2026-09-13

Written from the specification text before reading either consumer's code for these rules. Candidate pin
`sha256:674d2f97e5a6b8f6e812ab140a1f821544fbdd4faa3ec6a03917225a9324c5c0`. Approved by Jeff: repair round on
the current fingerprint, plus ruling C. Each rule states what both consumers must do; the demonstration
that motivated it is cited but does not decide it.

## A. A duplicate copies the retained record of its fact group

Text. LIFECYCLE.md:215: "For a lifecycle `DUPLICATE`, the consumer copies the retained same-fact outcome's
complete embedded reservation-native record and changes only `id` and `evidence_ref`". LIFECYCLE.md:265: a
repeated evidence identity "records `OUTCOME_RETAINED/DUPLICATE` ... and commits any corresponding idempotent
registry receipt", and "A new evidence ID with the same fact digest is also `DUPLICATE`". RESERVATION-RECORDS.md
:54: "A duplicate returns the established disposition named above and does not repeat an effect record or
charge."

Derivation. The registry retains exactly one effect record per fact group, under the evidence identity of the
first record of that fact. A DUPLICATE outcome row is never given a registry record. The copy source is therefore
the registry record of the fact group, found through any retained outcome whose native fact digest equals the
new evidence's, not the registry record of whichever outcome row happens to sort first or be named by the
repeated evidence identity. Required, both consumers: re-delivering a DUPLICATE row's own evidence, and a later
new-identity record of the same fact when a DUPLICATE row sorts first, are admitted as `OUTCOME_RETAINED/
DUPLICATE_EVIDENCE` with the idempotent receipt.

## B. A clean UNKNOWN after RELEASED changes nothing

Text. RESERVATION-RECORDS.md:48: "| `SETTLED` or `RELEASED`; later `UNKNOWN` | `UNKNOWN` | retain the native
evidence and prior terminal state; change no exposure |". LIFECYCLE.md:211: "An unknown record after `SETTLED`
or `RELEASED` is retained without changing that conclusion." The `LATE_EFFECT_AFTER_RELEASE` row is "`RELEASED`;
later `EFFECT`" (RESERVATION-RECORDS.md:50).

Derivation. For a reservation already RELEASED, a SETTLE whose native outcome is UNKNOWN with
`completion_mismatch:false` takes the later-UNKNOWN row: receipt `UNKNOWN`, reservation stays `RELEASED`, no
exposure change, and at the lifecycle `OUTCOME_RETAINED/UNKNOWN_OUTCOME`. Only a later `EFFECT` takes the
late-after-release row. A mismatched UNKNOWN stays under the first table row (any state, mismatched UNKNOWN or
NO_EFFECT: `EFFECT_DISPUTED`). Required, both consumers.

## C. A duplicate with a newer supplied history is still a duplicate (ruling, Jeff, 2026-09-13)

Text. LIFECYCLE.md:265 and RESERVATION-RECORDS.md:54 above; LIFECYCLE.md:211: "Exact or same-fact duplicates
return the established reservation disposition without adding exposure."

Derivation and ruling. Duplicate recognition depends on the native fact, not on the supplied history. A
same-fact duplicate against a SETTLED reservation returns receipt `SETTLED`, adds no effect record, and does not
store the newer history, so a retry never changes registry facts beyond the receipt. The rule "When a newly
admitted history revises or retracts a prescribed event for a SETTLED reservation, mark it DISPUTED"
(RESERVATION-RECORDS.md:58) applies to non-duplicate admissions, not to a duplicate retry. Required, both
consumers.

## D. An UNKNOWN never lifts BLOCKED_DISPUTE

Text. LIFECYCLE.md:261: "Unknown or disputed reconciliation also leaves the occurrence `BLOCKED_DISPUTE`."
LIFECYCLE.md:265: "An `UNKNOWN` after a conclusive governed result is retained without changing the earlier
conclusion." LIFECYCLE.md:193: "`UNKNOWN` leaves it `OUTCOME_UNKNOWN`" refers to an unresolved occurrence that is
not already blocked.

Derivation. When the occurrence is already `BLOCKED_DISPUTE`, an UNKNOWN record, including one whose budget
result is `EFFECT_DISPUTED`, leaves it `BLOCKED_DISPUTE` and leaves its directly owning obligation `BLOCKED`.
Required, both consumers.

## E. A new-identity duplicate joins the conflict group on the foreign path too

Text. LIFECYCLE.md:205: "A `DUPLICATE` outcome inherits the disputed value and conflict set of the retained
same-fact outcome. When that fact already conflicts with another fact, the new duplicate lists every evidence
identity in the other fact group, and each member of that group adds the duplicate evidence identity to its
sorted conflict set." The same paragraph: "A foreign conflict list uses the same symmetric rule."

Derivation. On the foreign path, a new-identity DUPLICATE of a conflicted fact updates every member of the other
fact group exactly as on the governed path, with `disputed:true` and recomputed outcome digests. A repeated
evidence identity appends no row and updates no group. Required, both consumers.

## F. An OPEN or BLOCKED obligation names an occurrence its own region directly owns

Text. COMPOSITION.md:300: "Only the innermost branch or object region directly owns that occurrence. An enclosing
parent obligation is `WAITING` on the exact child pass and does not also name the inner occurrence."
LIFECYCLE.md:321: "`OPEN` names one current active occurrence other than `BLOCKED_DISPUTE`; `BLOCKED` names one
exact `BLOCKED_DISPUTE` occurrence; and that occurrence belongs directly to the obligation's branch or object
region."

Derivation. The expected occurrence of an OPEN or BLOCKED obligation may be any occurrence reached by an onward
route inside its region, but its innermost BRANCH or FANOUT enclosing segment must be the obligation's own
(kind, construct, pass, branch or object key). Otherwise the checkpoint is `STATE_INVALID`. The head-source rule
(R3) stays. Required, both consumers.

## G. A join's continuation drops the joined region and names the joined construct, whatever follows

Text. LIFECYCLE.md:289: "`construct_ids` is the raw UTF-8 sorted unique set of every parallel block or fan-out
whose split, expansion or join the closure traverses." LIFECYCLE.md:291: "When the pass joins, the successor
removes the discharged branch or fan-out segment and every region-local segment after it, retains the common
outer prefix, and then appends only segments introduced by the continuing structural closure." COMPOSITION.md
:302: "`outer_enclosing` is the complete enclosing prefix before the child construct's branch or object
segment". COMPOSITION.md:306: "If it immediately enters another child split or nonempty fan-out, the transition
replaces `waiting_on` with the new exact child-pass reference ... Empty fan-out advance creates no child
obligations and uses the expand occurrence as the structural frontier, so it either resumes, waits on a later
nonempty child pass or discharges the parent within the same event".

Derivation. After any join, whether the continuation reaches an operation, another join, a split, a fan-out
expand or a terminal, the continuing occurrences and any new waiting reference use the joined pass's common outer
prefix, and the ROUTE detail names the joined construct together with every construct the continuation
traverses. An empty fan-out advance is a join traversal from the expand occurrence and continues through the same
join, split and operation handling. Required, both consumers; no consumer may fail on these shapes.

## H. A stop during a join's continuation leaves the pass unjoined

Text. COMPOSITION.md:308: "The consumer preflights the complete fixed-point result before creating any successor,
replacement wait or ancestor discharge. A stop anywhere in that preflight retains the direct event results,
creates none of the proposed continuation, discharges only the directly triggering obligations with their direct
bases, and leaves waiting ancestors unresolved in the stopped instance." LIFECYCLE.md:321: "A `STOPPED` state may
contain an all-`DISCHARGED`, not-`JOINED` pass only when the retained stop decision and the direct completion
bases prove that the join was suppressed by branch or object stop, stopped-instance late evidence, or fixed-point
preflight failure."

Derivation. When the effect discharges the last obligation of a pass and the join's continuation fails
preflight on a limit, the decision is `STOPPED` with `LIMIT_EXCEEDED` and the LIMIT detail; the discharged
obligations stay `DISCHARGED` (not `JOINED`); no successor is created; the instance becomes `STOPPED`. A
consumer must admit the event and must not mark the pass joined. Required, both consumers.

## I. A branch or fan-out region head may be a loop entry, and its occurrences carry the LOOP segment

Text. COMPOSITION.md:76: "A parallel branch head has only its block's implicit incoming edge, except for an
admitted back edge wholly inside that branch. A fan-out region head has only its fan-out's implicit incoming edge,
except for an admitted back edge wholly inside that object region." COMPOSITION.md:318: "A cycle may be contained
wholly inside one branch". COMPOSITION.md:193: "Every operation occurrence in the loop carries one `LOOP` enclosing
segment with the loop identifier and current pass; branch and fan-out segments remain in their outer-to-inner
positions." COMPOSITION.md:195: "Entry from outside allocates pass `1`."

Derivation. A definition whose branch or fan-out region head is the entry of a loop wholly inside that region is
admissible. When the split or expansion activates that head, the head occurrence's enclosing path is the outer
prefix, then the BRANCH or FANOUT segment, then one `LOOP` segment for that loop at pass 1. Required, both
consumers; no consumer may refuse the definition or fail on activation.

## R-a. Restart refuses a last receipt that does not commit the supplied state

Text. LIFECYCLE.md:315: "The consumer first hashes that core as `state_after_core_digest`, constructs and hashes
the decision receipt, and appends the receipt and replay record." LIFECYCLE.md:323: "The consumer refuses any
changed digest, missing record, broken binding, status violation or noncanonical ordering as `STATE_INVALID`
before applying the next event."

Derivation. The last receipt's `state_after_core_digest` must equal `digest("work-state-core", core)` of the
supplied state. A checkpoint where it does not is `STATE_INVALID`. Required, both consumers.

## R-b. Renewing a disputed reservation is withheld, not refused

Text. RES-WIRE-004: "An already DISPUTED reservation cannot be renewed or released; WITHHELD with
EXPOSURE_DISPUTED retains it."

Derivation. A well-formed RENEW naming a `DISPUTED` reservation is an admitted policy decision: receipt `WITHHELD`
with reason `EXPOSURE_DISPUTED`, reservation unchanged. It is not an admission refusal. Required, both consumers.

## R-d. The foreign conflict scope includes a retained no-effect conclusion

Text. LIFECYCLE.md:205: a CONFLICTING conflict list covers "every other retained evidence identity whose
conclusive fact conflicts under either of two exact scopes: the same provider-native operation identity ...";
"a changed conclusive foreign fact has `CONFLICTING`"; "A foreign conflict list uses the same symmetric rule."
LIFECYCLE.md:259: "A second conclusive record with the same provider-native operation identity and different
content is conflicting evidence." A `NO_EFFECT_ESTABLISHED` record is conclusive (LIFECYCLE.md:205, :265).

Derivation. A foreign established effect whose provider-native operation identity equals that of any retained
conclusive record, effect or no-effect, with a different fact, is `CONFLICTING`. Required, both consumers.

## R-e. observed_request projection depends on fields, not collections

Text. LIFECYCLE.md:215: "For `EFFECT`, `observed_request` is the dispatch-attributed request when every completion
binding maps the actual evidence fields back to that exact request with complete declared types; it is null when
any field is missing, extra, inconsistent or unprojectable." RES-WIRE-003: "Its observed request is the complete
operation-field projection when that projection is possible."

Derivation. Collections do not enter the field projection. A governed EFFECT on an operation step that carries a
collection is completion-mismatched (both consumers already agree), but its `observed_request` is the projected
request whenever the fields project. Required, both consumers.

## Not in this round

- J (Python restart seed after an expired, later-disputed branch head): covered by decision D6 and landed in the
  amendment batch with its text clarification.
- The Python budget-disputed branch not blocking the owning obligation: not demonstrated; no budget-backed branch
  fixture exists. Recorded, not repaired.
