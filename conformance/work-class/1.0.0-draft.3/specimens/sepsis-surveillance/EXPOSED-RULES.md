# Rules exposed by the sepsis surveillance specimen

Each entry names a general rule the specimen needed that the draft-2 text cannot express or leaves ambiguous, the paragraph it touches, how the specimen worked around it, and the smallest wording that would close it. Entries 1 to 4 are gaps in expressiveness; entries 5 and 6 are readings the text leaves to the corpus. None is a defect in what the text does say.

Step 4 of the completion plan (2026-09-13, option 2 of `review/records/EXPOSED-RULES-DISPOSITION-PROPOSAL-20260913.md`, wording in `review/records/STEP4-WORDING-20260913.md`) disposed of every entry; each entry's status line records the outcome. The specimen was rebuilt at the step 4 pin.

## 1. A deadline measured from an ancestor's activation

Status: closed in draft 2 by the `ELAPSED_FROM_ANCESTOR` due kind (COMPOSITION 5.1, LIFE-014). The landed wording differs from the proposal below in two ways: `due` is the anchor occurrence's completed-row `occurred_at` plus the duration, not its activation instant, and uniqueness is secured by static admission alone (the anchor is proposal-capable, outside every loop, outside any fan-out region not containing the deadline's step, and on every root path to that step), with no separate anchor field in the activation digest. The rebuilt specimen declares `antibiotic-window` as 60 minutes from `raise-alert`, which satisfies every admission condition without restructuring; the valid trace's antibiotic deadline is due 09:00, the `sepsis-unknown-then-deadline-stop` clock at 09:00 now stops the instance, and the correspondence maps the deadline to `hour-one-bundle` with no mismatch residue. The paragraphs below record the gap as found.

Touches: COMPOSITION 5.1 (`due` is `ABSOLUTE_INSTANT` or `ELAPSED_DURATION` added to "the admitted activation instant"), LIFE-014 (`due` is "activation instant plus the elapsed duration").

The source policy's hour-one bundle binds every element to time zero, the alert's recognition time. The two branch deadlines measure from time zero only because the alert's completion activates them while the time-zero clock sample is the latest retained sample. The antibiotic step is activated after the join and the readiness choice; its `antibiotic-window` deadline measures from the clock retained at that activation (08:30 in the valid trace, due 09:30), not from time zero (due 09:00). The specimen declares the nearest expressible deadline and records the mismatch in the correspondence residue for every `antibiotic-window` path.

Smallest wording: add a third `due` kind, `ELAPSED_FROM_ANCESTOR`, with `value`, `unit` and `anchor_step_id`. The anchor is a proposal-capable step in the recursive predecessor closure of the activated occurrence; `due` is the anchor occurrence's retained `activation_instant` plus the duration, and the anchor's identity is added to the `deadline-activation` digest subject. Zero or several eligible anchors is `DEFINITION_INVALID` statically where the graph makes it so and `STATE_INVALID` on restart. A due instant already passed at activation stays under the existing `DEADLINE_ALREADY_DUE` rule.

## 2. A condition on elapsed time

Status: stated as an unsupported limitation in AUTH-001, which now names conditions on the time elapsed since another occurrence among the unsupported predicates in this candidate. The capability is recorded for draft 3. The specimen's override criterion and its reason text are unchanged.

Touches: AUTH-001 ("Observation-based general predicates ... remain unsupported"), AUTH-002 gate criteria ("exact field predicates").

The override clause permits antibiotics before cultures only when drawing cultures would delay antibiotics more than forty-five minutes. Authority predicates range over proposal fields, so the specimen expresses the clause as `cultures_drawn_first == true OR override_reason != ""` and leaves the forty-five-minute test to the recorded reason text.

Smallest wording: admit one more operand kind in gate criteria and conditions, `ELAPSED_SINCE_ANCHOR` returning `INTEGER` seconds between the authority clock instant and a named ancestor occurrence's retained activation instant, resolved by the lifecycle from state before it calls the authority evaluator. Until then the text should say plainly that time-relative source conditions are unsupported limitations under AUTH-001.

## 3. Withdrawal of a per-instance act between permit and dispatch

Status: resolved by the LIFE-008 sentence: a host that honours a revocation or changed observation declines to dispatch under the committed permit, the permit expires unused, and a later renewal under LIFE-007 evaluates current authority. The snapshot rule stands. The specimen's `sepsis-order-expired-dispatch` request records the host reporting its declined attempt at the exclusive expiry.

Touches: LIFE-008 ("A later revocation or changed observation ... does not erase a still-valid committed permit"), LIFE-009 dispatch reasons.

The handoff's variant 4 asks for a dispatch refused because the physician order was revoked after the permit. Draft 2 fixes the authority snapshot until the permit's exclusive expiry by design, and the dispatch table has no revocation row. The specimen builds the expiry form (`PERMIT_EXPIRED` with `NATIVE_NOT_SENT`) and records that the revocation form is not a construct in this candidate.

Smallest wording: none is recommended for draft 2; the snapshot rule is deliberate and an organization that needs a shorter window declares a shorter `permit_seconds`. LIFE-008 could state in one sentence that a host wishing to honour a revocation between permit and dispatch must report the attempt as `NOT_SENT` and obtain a fresh proposal, so the specimen's form is the sanctioned one.

## 4. An indeterminate observation that holds a proposal

Status: stated as an unsupported limitation in AUTH-001, which now names freshness predicates on proposal fields among the unsupported predicates in this candidate. The `FRESHNESS` query is recorded for draft 3. The specimen's two expressions of the rule are unchanged, and the stale-vitals withholding now names its failed `vitals-age-bound` check in `failed_checks`.

Touches: AUTH-001 (observation predicates unsupported), AUTH-005 (observations are revocation queries only), AGG-007 (`INDETERMINATE` exists for aggregates).

"Vitals older than fifteen minutes are indeterminate; an indeterminate observation holds the dependent action." The lifecycle has no observation of a clinical feed and no hold disposition. The specimen expresses the rule twice: as a choice label (`REASSESS`) reported by the monitoring feed's native record, which routes into the bounded re-assessment loop, and as a caller-declared `vitals_age_seconds` field bounded `LTE 900`, whose violation withholds the proposal. Neither is a consumer-evaluated freshness check, and `WITHHELD` is not `INDETERMINATE`.

Smallest wording: extend the authority observation inventory with a `FRESHNESS` query purpose `{purpose:"FRESHNESS", provider, source, subject, at}` whose `AVAILABLE` row carries `as_of`; an envelope condition of kind `OBSERVATION_FRESH` names the query and a `max_age_seconds`; a stale or unavailable row yields `AUTHORITY_NOT_ESTABLISHED` with `OBSERVATION_STALE` or `OBSERVATION_UNAVAILABLE`, which the lifecycle already maps to a retained withholding. This reuses the existing status and reason vocabulary.

## 5. The `ROUTE` detail's construct set when a branch reaches a join that does not fire

Status: resolved by the LIFE-015 sentence: `construct_ids` names every construct whose split, expansion or join the closure reaches or passes through, and a closure that ends at a join that does not fire names that join's construct. The specimen's reading (the page effect names `hour-one-bundle`) is now the text's.

Touches: LIFE-015 ("every parallel block or fan-out whose split, expansion or join the closure traverses").

When the page branch completes first, its closure reaches `bundle-join` and stops there. Whether reaching a join without firing it "traverses" the join is not stated. The specimen follows corpus case D2-052 and names the block. Both implementations agree with that reading.

Smallest wording: in LIFE-015, replace "traverses" with "reaches or passes through", or state that a closure that ends at a join names that join's construct.

## 6. Every envelope operation needs a numeric bound or a shared budget

Status: unchanged. No wording landed in step 4; the specimen keeps its bounded counters.

Touches: AUTH-001 ("Every operation allowed by this envelope requires either a per-action upper bound or at least one declared shared-budget anchor").

Alerts, pages, escalations, assessments and refreshes carry no natural quantity. The specimen invents bounded counters (`attempt_number LTE 3`, `risk_score LTE 1`, `lookback_seconds LTE 900`) to satisfy the rule; two of them (`lookback_seconds`, `vitals_age_seconds`) do carry source meaning, the others are apparatus. Not a gap in expressiveness, but the rule pushes source-free fields into definitions and their correspondence residue.

Smallest wording: none required for draft 2. If the freeze wants to remove the friction, AUTH-001 could admit an explicit `limits.per_action:[]` with `limits.unbounded_operations:[step ids]` recorded as a limitation, so the absence of a quantity is declared rather than simulated.

## 7. Time zero is the alert's delivery, not its recognition

Found by the 2026-09-13 review round (finding NS-03). The source policy's hour-one bundle runs from "the alert's recorded recognition time". `antibiotic-window` is `ELAPSED_FROM_ANCESTOR` anchored at `raise-alert`, and COMPOSITION 5.1 adds the duration to that occurrence's completed-row `occurred_at`, which LIFE-010 sets to the native delivery `event_time`, never earlier than the dispatch attempt or the proposal clock. In the valid trace recognition, proposal, dispatch and delivery share 08:00:00, so the difference is invisible; a recognition at 07:58 with delivery at 08:01 would move the deadline to 09:01. The correspondence maps the deadline to `hour-one-bundle` without residue. Disposition (Jeff, 2026-09-14): a draft 3 design input alongside roe E3 (a deadline anchored to an observed fact rather than to a completed occurrence).

## 8. The attending's fifteen minutes run from the page step's activation

Found by the 2026-09-13 review round (finding NS-04). The policy's `escalate-unacknowledged-page` gives the attending fifteen minutes "of the page". `attending-acknowledgement` is `ELAPSED_DURATION` on the page step, so it runs from that step's activation at the alert's completion (08:00), not from the page dispatch (08:02 in the valid trace). A page proposed at 08:14 would expire one minute after it was sent. No residue records this. Disposition (Jeff, 2026-09-14): the same draft 3 design input as rule 7 and roe E3.

## Derived-order difference found in the step 4 rebuild

Not a text gap, though LIFE-019's short form "occurrence bytes" is less explicit than LIFE-014's "canonical occurrence bytes" for the same ordering. After the rebuild, `labs-hour-one` and `antibiotic-window` share the due instant 09:00 from revision 15 of the valid trace. The builder ordered them by the occurrence identifier string; both consumers ordered them by the canonical bytes of the occurrence record, which places `antibiotic-window` first and is what both paragraphs say. The builder was corrected to the text (DERIVATIONS.md section 4); that reading was written after the comparison run exposed the error, and the comparison then matched every request. A one-word edit to LIFE-019 ("canonical occurrence bytes") would remove the shorter phrasing; no wording is proposed here.

## Consumer difference recorded during comparison

Not a text gap. LIFE-019 orders the `deadlines` collection "by due instant, occurrence bytes and deadline identifier". In the valid trace's alert effect (`sepsis-effect-alert`), two deadlines are created in one transition: `attending-acknowledgement` due 08:15 and `labs-hour-one` due 09:00. The derived state and the TypeScript consumer place the 08:15 deadline first; the Python consumer places `labs-hour-one` first, and its `state_after_core_digest`, `decision_id` and `activation_digest` values differ accordingly. Python accepted the derived (due-ordered) state on the following requests and matched every later derived byte, so the difference was confined to how Python ordered newly created deadline rows after a parallel split. Confirmed as a Python defect and fixed on 2026-09-13 in `python/implementation/lifecycle.py` (`_enter_parallel` now applies the LIFE-019 sort that the fan-out and single-successor paths already applied); the comparison now matches on every request in both consumers.
