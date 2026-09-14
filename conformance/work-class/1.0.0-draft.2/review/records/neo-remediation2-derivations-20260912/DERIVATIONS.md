# Remediation 2 derivations, 2026-09-12

Written from the text before reading either implementation's code for these rules, and before any
edit. Candidate pin `sha256:674d2f97e5a6b8f6e812ab140a1f821544fbdd4faa3ec6a03917225a9324c5c0`.
Each rule is stated for both implementations. Where the text does not settle a rule, that is stated
and no implementation change follows.

---

## R1. Restart must find the exact child pass a WAITING obligation names

Text. COMPOSITION.md:425: fan-out passes are ordered "by fan-out identifier, numerical pass and
expand occurrence identifier", and "No two rows may share that tuple" (LIFECYCLE.md:313). COMPOSITION:
`waiting_on` is `{kind,construct_id,pass,outer_enclosing,obligation_ids}`, where "`outer_enclosing`
is the complete enclosing prefix before the child construct's branch or object segment; it
distinguishes passes whose numerical pass values restart in different contexts." LIFECYCLE.md:321:
"`WAITING` names one existing unique child pass with the exact kind, construct, pass, common outer
enclosing prefix and complete obligation inventory".

Derivation. Fan-out id plus pass number does not identify a pass once the same fan-out has been
entered under two outer prefixes, each of which starts at pass 1 (COMP-002, FAN-001, and the
committed vector D2-115). The identifying context is the outer enclosing prefix. Admission must select
the child pass whose kind, construct, pass **and** outer enclosing prefix all match the reference, and
must then require that pass's obligation inventory to equal the reference's.

Required, both implementations: a checkpoint holding two pass-1 rows of one fan-out under different
outer prefixes, each with its own WAITING parent, is admitted.

## R2. Restart admits a completion-based DISPUTED obligation through the dependency-affected set

Text. LIFECYCLE.md:321: "A completion-based `DISPUTED` obligation retains a valid former discharge
basis whose frontier intersects the dependency-affected set of at least one retained completed
occurrence with disputed conclusive evidence; restart recomputes each such set from predecessor lists
under LIFE-013." LIFECYCLE.md:261 defines the set: "that occurrence and every transitive active or
completed descendant through these predecessor lists."

Derivation. The frontier need not contain the disputed occurrence itself. It must intersect the set
consisting of that occurrence **and its transitive descendants**. A branch whose operation A routed to
B, where B discharged the obligation, has frontier {B}; a dispute on A puts B in A's affected set, so
the intersection is nonempty and the state is admissible. The D2-256 contract row states this
directly: "Restart recomputes the same intersection and admits the resulting disputed-completion
variant."

Required, both implementations: D2-256's resulting state is admitted on restart.

## R3. A region head occurrence's predecessors equal its obligation's source occurrences

Text. COMPOSITION.md:282: "A structural closure carries a nonempty frontier of predecessor occurrence
identities ... Every new branch occurrence copies the current sorted frontier into
`predecessor_occurrence_ids`." COMPOSITION.md:288: "`source_occurrence_ids` equals the current
structural frontier". LIFECYCLE.md:261: "parallel and fan-out heads name the structural frontier that
entered their pass". LIFECYCLE.md:291: "a retained obligation set, completion frontier or occurrence
path that disagrees is `STATE_INVALID` on restart."

Derivation. At creation, the branch or object head occurrence and its obligation both record the one
structural frontier, so they are equal, and both are immutable identity fields thereafter. After an
onward route inside the region (PAR-001) the obligation's **expected** occurrence moves to a successor
whose predecessor is the head, so equality holds against the **head** occurrence, not against
whatever the obligation currently expects. A checkpoint in which an obligation's
`source_occurrence_ids` disagree with the predecessors of its region head occurrence is `STATE_INVALID`.

Required, both implementations: that disagreement is refused; D2-114's onward-routed state (expected
occurrence is a non-head successor) stays admitted.

## R4. A waiting reference lists its child obligation ids in raw UTF-8 order

Text. LIFECYCLE.md:313: "Credential IDs, observation digests, receipt digests, predecessor occurrence
IDs, source occurrence IDs, child-pass obligation IDs, conflict evidence IDs and other identifier sets
use raw UTF-8 order." COMPOSITION.md:425: "Each fan-out pass retains source order in `object_keys` and
`obligation_ids`."

Derivation. Two different fields are governed by two different sentences. The fan-out **pass row's**
`obligation_ids` keeps source order, because the pass is the frozen, source-ordered inventory. The
**waiting reference's** `obligation_ids` is the "child-pass obligation IDs" set that LIFECYCLE.md:313
names explicitly, and it uses raw UTF-8 order. The reference must contain the same identities as the
pass inventory; its order is independent of source order. The rule is not limited to fan-out, so a
parallel child-pass reference is sorted the same way.

Required, both implementations: an expansion whose object source order is not raw UTF-8 order writes
the pass row in source order and the parent's `waiting_on.obligation_ids` in raw UTF-8 order; restart
admits that state and refuses a waiting reference that is out of raw UTF-8 order.

## R5. D2-237's `deadline_ids` after an evidence-only expiry: not settled

Text. LIFE-014 (LIFECYCLE.md:277) marks the deadline `EXPIRED` and keeps the occurrence
`BLOCKED_DISPUTE`. Neither it nor LIFE-019 says what the active occurrence's `deadline_ids` holds
afterward. The schema defines the field as an identifier array with no stated meaning.

Derivation. The text does not decide between "declared deadlines of the step" and "pending deadlines".
No implementation change. Recorded as a specification question.

## R6. An ACTIVE checkpoint cannot hold a pass whose complete inventory is DISCHARGED and unjoined

Text. LIFECYCLE.md:321: "If an `ACTIVE` state contains a pass whose complete obligation inventory is
`DISCHARGED`, that checkpoint is invalid because the eligible join should have fired atomically. A
`STOPPED` state may contain an all-`DISCHARGED`, not-`JOINED` pass only when the retained stop
decision and the direct completion bases prove that the join was suppressed".

Derivation. A vector for this rule is decisive only if the state is otherwise valid, so that the
refusal can come from this rule alone: a reachable ACTIVE state in which a child pass has joined, and
an adjacent state identical except that the join markers are reversed (child obligations DISCHARGED
rather than JOINED, pass `joined:false`, parent back to WAITING on that pass). The first is admitted
and the second refused `STATE_INVALID`. Unrelated unresolved work must keep the instance ACTIVE.

## R7. D2-227 must carry exactly one fault

Text. LIFECYCLE.md:168: "For every budget-backed effect, `native_evidence.observed_at` is no later than
the selected latest retained registry clock; a later observation is `CLOCK_INVALID` and leaves
governed state unchanged". LIFE-010: the embedded reservation-native record copies id, provider,
source, evidence reference, actual fields and collections from the native evidence.

Derivation. The expected judgment `REFUSED/CLOCK_INVALID` is unchanged. The embedded record must be a
correct copy of the evidence, so that correcting only the observation time yields an admitted
decision rather than a different refusal.

## R8. D2-232 needs a reachable prior state

Text. Contract row: "A governed UNKNOWN outcome is otherwise exact, but its shared-budget registry is
already disputed and returns EFFECT_DISPUTED." RES-WIRE-003, prior-state table: "`DISPUTED`; any new
attributable fact → `EFFECT_DISPUTED`; remain `DISPUTED` ... perform no automatic resolution".
LIFECYCLE.md:241: a foreign effect "retains the effect as disputed exposure under its known-reservation
... rules" and LIFE-006's consequence table: a `DISPUTED` foreign effect leaves current occurrences
unchanged.

Derivation. A foreign effect against the occurrence's own known reservation disputes the registry
without changing the occurrence, which stays `DISPATCHED` on a clean dispatch. A governed UNKNOWN on
that clean dispatch then meets an already `DISPUTED` reservation and gets `EFFECT_DISPUTED`. That is
the contract scenario with a history a host can produce. The judgment is unchanged. Two fields remain
subject to open questions and are carried at their current values, not decided here: the outcome's
`disputed` flag (Q1) and the receipt reason for a clean fact against an already disputed reservation
(recorded gap).

## R9. D2-270 rests on an undecided rule

Text. LIFECYCLE.md:170, :209, :215 do not say whether a `NOT_SENT` attempt with no accepted
acknowledgement is dispatch-disqualifying for no-effect authorization and mismatch reason.

Derivation. The contract scenario cannot be derived until that is decided. The committed vector
replaced the scenario with an unreachable state. Retract it to pending.
