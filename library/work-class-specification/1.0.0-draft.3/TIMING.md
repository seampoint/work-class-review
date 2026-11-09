# Event timing and observation age

Status: `DRAFT_NOT_ADOPTED`, `APPARATUS_ONLY`. This companion defines bounded measurement age, immutable initial-event anchors, retained preactivation duties and first qualified occurrence timers. Closed schemas supply the exact carriers. For definitions selecting these features, the explicit extensions below govern the corresponding deployment, deadline, complete-state and recovery rules. Definitions without them retain inherited shapes and transitions.

## TIME-001. Shared admission and unchanged behavior

Every object below is closed. Shown fields are required unless explicitly optional. Reuse existing IDs, digests, nominal typed values, named typed fields, natural strings, strict whole-second UTC instants and canonical encoding. Optional new arrays are omitted when their feature is unselected. A selected declaration or initial-record inventory is nonempty. Matching digests do not authenticate provider assertions.

Inherited deadline declaration variants and state.deadlines records stay unchanged. New initial-event duties and deferred deadlines use separate closed inventories. The combined definition deadline inventory is at most 256; the combined runtime inventory of inherited deadlines, event duties and deferred deadlines is at most 4096. A step still has at most one deadline. Declared occurrence/activation limits and existing scalar, transport and readback limits also apply. Preflight projected expansion before allocating or mutating state. A deployment exceeding the runtime inventory bound refuses LIMIT_EXCEEDED. Expansion during an admitted fact transition retains that fact, creates none of the proposed closure and records STOPPED/LIMIT_EXCEEDED. Its LIMIT detail has limit_kind DEADLINE_RECORDS, limit "4096", current equal to the projected count, and step_id and relationship_digest from the first violating target in deterministic closure order; relationship_digest is null when that closure has no relationship.

Preserve LIFE-009 historical dispatch reporting, acknowledgement updates, effect reconciliation, exact replay, terminal history and REC-014 expiry ordering. No new general event correction, timer reset, cancellation, calendar arithmetic or arbitrary expiry action is added. An expiry still follows its declared expiry_target or explicit stop.

## TIME-002. Maximum elapsed observation relation

The additional closed sourceObservationRelation alternative is:

```text
{id,kind:"ELAPSED_LTE",left,right,maximum_seconds}
```

Operands use existing source-observation selectors. They must resolve to the identical nominal type of kind INSTANT. maximum_seconds is a canonical natural string, including zero, within existing numerical bounds. The exact predicate is `0 <= right - left <= maximum_seconds`. Subtract admitted whole-second instants exactly; no unit, arithmetic expression or callback is selected.

Inherited relations remain their four-field shapes and reject maximum_seconds. Copy the complete new declaration into derived queries and returned copied relations. Existing relation ordering, dependency admission, query identity, per-step relation limit and failed-check attribution apply. A false or unproven comparison contributes SOURCE_OBSERVATION_RELATIONS against its declaring requirement. freshness_seconds independently checks response age from as_of.

The sepsis successor selects the provider's measured_at field as left, current authority CLOCK as right and 900 seconds as the bound. Ages 900 and 901 produce different judgments even when retrieval/as_of is current. Exact subject and value relations bind measurement to the patient and proposed facts.

## TIME-003. Initial event declarations and immutable records

Optional definition.event_anchors is sorted uniquely by id, with at most 64 declarations:

```text
{id,provider,source,record_type,time,fields,subject_fields,request_bindings}

time =
  {kind:"EVENT_TIME",type_ref}
  | {kind:"FIELD",field_ref}

request_binding =
  {step_id,subject_field,target_request_field}
```

fields is a nonempty array of at most 64 existing {name,type_ref} declarations, sorted uniquely by name. It declares the complete native field inventory. subject_fields is a nonempty sorted unique subset of these names, bounded to 64. EVENT_TIME projects the native record's raw event_time under the specified declared INSTANT type. FIELD selects the exact declared named typed field, whose type must be INSTANT. No arbitrary string is converted to an instant. A declared time selection with a resolved non-INSTANT type is DEFINITION_INVALID; an undeclared type or field remains REFERENCE_INVALID.

request_bindings is a nonempty array of at most 64 rows sorted uniquely by (step_id,target_request_field). Every row resolves to a subject field and native proposal field with identical nominal type. A resolved static nominal-type mismatch is DEFINITION_INVALID; a missing reference remains REFERENCE_INVALID. Every subject field has a binding on the root and each deadline target using that anchor; additional source-selected steps may bind it. PROPOSE and renewal compare exact typed values before authority readiness. A mismatch is BINDING_MISMATCH. Dispatch refresh preserves the immutable request and those bindings.

Deployment input gains optional event_anchors containing exactly one wrapper per declaration, sorted by anchor_ref:

```text
wrapper =
{anchor_ref,specification_pin,work_class_digest,organization_id,
 instance_id,record,record_digest}

record =
{provider,source,record_type,provider_record_id,provider_revision,
 event_time,observed_at,fields,evidence_ref,provenance_digest}
```

Native event_time and observed_at are raw strict instants. fields contains exactly the declared complete named typed values. Provider record identity and revision are nonempty opaque IDs. Provider/source/type match the declaration. Wrapper pin, definition digest, organization and instance match deployment. Require native event_time <= observed_at <= deployment_authorization_clock.observed_time and selected anchor time <= observed_at. The native record contains no deployment or instance wrapper. Provider authenticity, truthful time and complete native facts remain host assertions.

record_digest is digest("event-anchor-record",record). anchor_digest is digest("initial-event-anchor",wrapper). Add optional deployment_authorization.event_anchor_digests, exactly {anchor_ref,anchor_digest} rows in declaration order, covering every supplied wrapper. The existing deployment-authorization subject includes this vector before organizational authorization evidence is attached. Neither native record nor wrapper contains the deployment authorization digest, so the subject binding is acyclic. Organizational authorization covers the exact initial values transitively through native digest and wrapper digest.

State retains the complete wrappers in initial_event_anchors. Their digest vector remains in deployment_authorization and is not duplicated. These records never change after deployment. Missing required rows refuse EVIDENCE_UNAVAILABLE. Wrapper specification pin or definition digest mismatch refuses DEPENDENCY_MISMATCH. A native record_digest that differs from its complete record refuses DIGEST_MISMATCH. A different native field-name inventory refuses BINDING_MISMATCH; malformed or wrongly nominally typed supplied field values refuse TYPE_INVALID. Wrong provider/source/record_type, organization, instance or bound subject refuses BINDING_MISMATCH. A well-formed instant violating the required native or selected time ordering refuses CLOCK_INVALID. Duplicate anchor refs or competing records are invalid input; malformed or wrongly nominally typed values retain existing type/admission precedence. No revision spelling or latest timestamp chooses a winner.

A source-confirmation review timestamp supplies no recognition time. The immutable recognition record is an explicit provider contract in the fictional sepsis successor, not an existing live-provider fact. Late event discovery and corrections are outside this initial form and cannot replace its retained basis.

## TIME-004. Fixed initial event duties

The initial-event deadline due alternative is:

```text
{kind:"ELAPSED_FROM_EVENT_ANCHOR",anchor_ref,value,unit}
```

value is strictly positive; unit is existing SECOND, MINUTE, HOUR or DAY. The surrounding deadline retains id, step_id, clock_source, boundary and expiry_target. Derive due once from the selected initial anchor instant plus exact elapsed seconds. Overflow at deployment refuses LIMIT_EXCEEDED.

The target is proposal-capable, is not the root, is outside all loops and fan-out, and can activate at most once. Every normal completing execution must include it, including source-declared expiry routes that can COMPLETE. A parallel join requires completion of every mandatory branch; a graph path through one branch alone cannot bypass a target on another required branch. Explicit STOP paths may bypass the target and retain its duty. A definition permitting normal completion without the target is DEFINITION_INVALID. Root and target requests bind the declared subject fields.

Create one state.event_duties row per declaration at deployment, before the target activates. Sort uniquely by deadline_id. Every row has this common body:

```text
{deadline_id,target_step_id,source,boundary,anchor_ref,
 anchor_digest,due,creation_digest}
```

creation_digest is digest("initial-event-duty",{specification_pin,work_class_digest,instance_id,deadline_id,anchor_digest,due,boundary,source}). Complete wrappers remain in state. Extend the common body by one separately closed alternative:

```text
{status:"PENDING",occurrence_id:null,binding_event_digest:null}
{status:"PENDING",occurrence_id,binding_event_digest}
{status:"EXPIRED",occurrence_id:null,binding_event_digest:null,expiry_basis}
{status:"EXPIRED",occurrence_id,binding_event_digest,expiry_basis}
{status:"DISCHARGED",occurrence_id,binding_event_digest,discharge_basis}

expiry_basis =
  {kind:"DEPLOYMENT",deployment_authorization_digest,clock}
  | {kind:"CLOCK",event_digest,clock}

discharge_basis =
  {kind:"COMPLETION",event_digest,occurrence_id,evidence_digest}
```

A nonnull occurrence_id names the sole target occurrence; binding_event_digest names its exact activation trigger. clock is the complete accepted available lifecycle clock. Deployment basis uses an exact initial clock and installed deployment authorization; CLOCK basis resolves to the retained event receipt and clock. No universal nullable fields enter inherited deadline records.

The initial clock inventory is the union of inherited root-deadline sources and initial event-duty sources. Inherited root deadlines still require available initial clocks. A source used only by an event duty may start unavailable/conflicting, leaving that duty pending. Deployment authorization retains its independently available clock requirement. Deferred timers need no trigger clock simply to create WAITING state.

If an available initial clock already satisfies an event duty, deployment retains EXPIRED with a deployment expiry basis. It does not reject the overdue duty through the inherited already-due root rule. A later available CLOCK expires satisfied pending duties. An unbound duty expires as evidence only: no occurrence, successor, join, actuation or reservation is invented. A bound dependency-blocked duty likewise expires as evidence only under LIFE-014.

When structural closure reaches the target, bind the exact occurrence once without changing due. If the duty is already expired, apply its original expiry consequence before making the target dispatchable. A still-pending duty whose selected current accepted clock proves it due expires at binding and follows the same consequence. Its expiry basis identifies that retained available clock's original DEPLOYMENT or CLOCK basis, rather than treating the binding event as a clock. A successful combined closure retains its target occurrence as expired without a target actuation; ordinary occurrence/activation limits and ownership updates still apply. A failed combined closure creates no new target or sibling and leaves the duty unbound with its retained expiry basis. If predecessors remain dependency-blocked, retain the expired duty until safe recovery can apply the consequence. Include all these closures in one preflight; do not partially install targets or routes.

Expiry stays EXPIRED after its consequence is applied. The expired target occurrence and receipt prove application. Eligible terminal completion before expiry changes PENDING to DISCHARGED with the retained completion basis. Unknown or disputed outcomes do not discharge it. STOPPED or COMPLETE instances retain later expiry evidence and never create a new target, join or route.

Normal COMPLETE requires no active occurrence, unresolved ordinary obligation or pending event duty, and no expired unbound duty whose consequence remains unapplied. The every-normal-path restriction prevents an ordinary idle ACTIVE graph from skipping the target. A checkpoint that bypasses the target while retaining an unresolved duty is STATE_INVALID; no implicit stop replaces its declared expiry route. A prior explicit stop retains duties without reactivation.

## TIME-005. Deferred same-occurrence deadlines

The two deferred deadline due alternatives are:

```text
{kind:"ELAPSED_FROM_FIRST_WITHHELD",value,unit,failed_checks}
{kind:"ELAPSED_FROM_FIRST_DISPATCH",value,unit}

failed_check_selector =
{purpose:"SOURCE_OBSERVATION",requirement_ref,reason}
```

FIRST_WITHHELD failed_checks is nonempty, bounded to 64 and sorted uniquely by canonical bytes. requirement_ref selects a source-declared observation requirement. reason is one of SOURCE_OBSERVATION_BINDING, SOURCE_OBSERVATION_CONFLICT, SOURCE_OBSERVATION_FIELDS, SOURCE_OBSERVATION_INCOMPLETE, SOURCE_OBSERVATION_RELATIONS, SOURCE_OBSERVATION_ROLLED_BACK, SOURCE_OBSERVATION_STALE, SOURCE_OBSERVATION_TIME or SOURCE_OBSERVATION_UNAVAILABLE. These reuse the inherited closed failed-check reason inventory; an inherited reason that is not emitted cannot create a trigger. The civilian control selects SOURCE_OBSERVATION_RELATIONS for one exact requirement. A selector matches purpose, requirement_ref and reason on an actual authority failed_checks row. subject_digest and at remain retained evidence, not selectable substitutions. CLOCK_UNAVAILABLE is excluded by this closed purpose/reason inventory.

Static admission checks the selector's closed shape, order and reason. The work definition names an authority envelope but does not contain its observation requirements. At PROPOSE, resolve each selector requirement_ref against the exact admitted authority envelope for the selected step; a missing or substituted requirement refuses REFERENCE_INVALID before permission or timer arming.

The trigger is the first admitted PROPOSE/WITHHELD for that exact occurrence with a matched failed check and AVAILABLE current clock. Its authority source must equal the deadline clock_source. Budget/separation withholding, admission refusals and unavailable-clock failure do not qualify. Source wording must say first proven selected authority-check failure, established by the first qualified admitted decision. It cannot claim the unobserved original divergence interval.

FIRST_DISPATCH uses the permit source, equal to the deadline source. It qualifies on the first admitted observation with attempt SENT or UNKNOWN, or acknowledgement ACCEPTED. NOT_SENT without accepted acknowledgement does not arm it. NOT_SENT/ACCEPTED and REJECTED/ACCEPTED arm a conservative disputed timer. REJECTED without accepted acknowledgement does not establish this send premise; existing consumption/reconciliation consequences remain. Possible send is not delivery.

At occurrence activation create one state.deferred_deadlines row. Sort by canonical occurrence bytes and deadline ID. Each row has this common body:

```text
{deadline_id,occurrence_id,source,boundary,
 activation_event_digest,creation_digest}
```

creation_digest is digest("deferred-deadline",{specification_pin,work_class_digest,instance_id,deadline_id,occurrence_id,activation_event_digest}). Separately closed alternatives extend it:

```text
{status:"WAITING"}
{status:"PENDING",trigger,due}
{status:"EXPIRED",trigger,due,expiry_basis}
{status:"DISCHARGED",trigger,due,discharge_basis}
{status:"DISCHARGED",discharge_basis}
{status:"TRIGGER_OVERFLOW",trigger,reason:"DEADLINE_TIME_OVERFLOW"}

trigger =
  {kind:"FIRST_WITHHELD",evaluation_digest,sequence,clock}
  | {kind:"FIRST_DISPATCH",event_digest,sequence,
     dispatch_digest,dispatch_attempt_digest,clock}
```

Reuse state.proposal_authority_evaluations, initialized when existing referral rules require it or a FIRST_WITHHELD deadline is declared. Event duties and FIRST_DISPATCH alone do not initialize this carrier. Retain every admitted AUTHORITY/WITHHELD evaluation on FIRST_WITHHELD-bearing steps, including unavailable clocks, plus all inherited referral-required evaluations, using the existing complete {evaluation_digest,event,authority_result,authority_result_digest} row. Preserve the original event, full authority input and exact receipt binding. Do not duplicate complete evaluations inside timers or retain unrelated successes. Preserve the existing global carrier ceiling of 128. A definition selecting FIRST_WITHHELD must declare maximum_proposals <= 128; a greater bound refuses LIMIT_EXCEEDED during static admission. Project carrier size before admission and preserve the existing LIMIT_EXCEEDED refusal without authorizing, releasing a duty or partially retaining a decision. A missing or truncated earlier qualifying evaluation invalidates firstness.

FIRST_WITHHELD evaluation_digest resolves exactly once to that complete carrier. Recompute the authority refusal, failed-check match, occurrence/source binding and latest available clock at its original sequence. FIRST_DISPATCH resolves complete retained attempt, acknowledgement, dispatch and receipt. Its trigger time is attempt.attempted_at. An accepted acknowledgement update can be the first qualified observation for an earlier NOT_SENT/REJECTED attempt; the original immutable attempt time supplies the conservative due.

Firstness is admitted receipt sequence, not a timestamp-based latest-wins rule. Later earlier-dated attempts remain attributable disputed evidence under existing consumption rules. They cannot extend due or clear the dispute. On the first qualified event compute due once. Refresh, retries, acknowledgement updates, later withholding, replay, restart and recovery cannot reset it.

An earlier unavailable-clock authority evaluation remains visible in the complete inventory. It leaves WAITING unchanged and cannot establish selected divergence or its time. A later qualified available-clock withholding starts the explicitly defined first proven interval; it does not rewrite the earlier unknown-time attempt. Host outage monitoring and source referral responsibilities remain separate.

Terminal completion while WAITING records DISCHARGED with no invented trigger or due. Unknown/disputed outcomes preserve the duty. Armed timers use ordinary boundaries, blocked evidence-only expiry, declared expiry response and terminal preservation. Unavailable/conflicting clocks leave them unchanged. A resumed clock beyond due expires the original interval.

A historical dispatch report can arm an already-overdue timer. Retain the attempt, arm it from its original time, and expire in the same transition when its selected available timeline clock proves due. For this deferred variant only, expiry_basis also admits {kind:"DISPATCH",event_digest,clock}. Apply eligible expiry consequences atomically; use evidence-only expiry when blocked or terminal. Do not refuse or erase the attempt.

Overflow stores the separate TRIGGER_OVERFLOW record with original trigger and no due. It records STOPPED/DEADLINE_TIME_OVERFLOW, preserves the original evaluation/attempt facts and cannot arm again. Trigger eligibility is computed from the ordinary proposal/dispatch result before timer consequences. The final decision carries original AUTHORITY or DISPATCH detail plus DEADLINE with the overflow reason. Evaluation retention and restart recognize this exact overflow STOPPED combination and reproduce its base authority withholding first.

## TIME-006. Current permission and historical clocks

Available authority input on PROPOSE or renewal must bind the latest retained record across all statuses for that source, and that row must be AVAILABLE. An older available revision refuses CLOCK_INVALID. Unavailable authority input requires null clock_revision and no latest retained AVAILABLE row; a contradictory submitted outage or a nonnull revision refuses CLOCK_INVALID. No retained sample, or a latest UNAVAILABLE or CONFLICTING sample, can project to authority UNAVAILABLE because the authority clock has no separate CONFLICTING alternative. Such valid unavailable input retains ordinary CLOCK_UNAVAILABLE withholding and cannot trigger FIRST_WITHHELD. Perform these clock checks after existing exact state/replay/event binding, prerequisites, proposal limits, prior-effect checks and embedded authority admission errors, before admitting authority withholding, separation or budget results. No old or ambient clock substitutes.

Fresh AUTHORIZE_DISPATCH uses the same latest all-status clock selection. Legacy authorization requires AVAILABLE and an exact revision. Gated authorization retains its existing unavailable-clock withholding and conflicting-clock refusal. Historical authorization validation selects the clock state before its original receipt; a later outage cannot invalidate the old decision.

The TypeScript host's common connector preflight checks latest source status before gated or ungated invocation. Existing gated TypeScript/Python checks remain. Keep request/connector equality, complete commitment, consumption, pending custody, recovery restrictions and provider fencing.

Historical DISPATCH_OBSERVED keeps its latest-available timeline rule. Later outage records cannot erase an earlier bounded attempt. Effects and acknowledgement updates keep existing reconciliation rules; none invokes a connector. An invoked-but-unreported Python host claim remains in protected PENDING custody through an outage and is reconciled after time resumes without resend.

Restart selects clocks as of the checked receipt sequence. Initial clocks have sequence zero; later clocks resolve through retained CLOCK receipts. A successful permit clock must have been latest across all statuses before its proposal. Retained unavailable proposal evaluations obey the same preceding-checkpoint predicate; a later outage cannot justify an earlier contradictory submitted outage. Later outages cannot invalidate historical permission. New permission uses latest current status. Silence still requires host monitoring because no missing event supplies consumer time.

## TIME-007. Unified expiry, details and restart

Collect the complete due set from inherited deadlines, bound deferred deadlines and initial event duties before changing state. Sort by due, then bound rows before unbound rows, then canonical occurrence bytes for bound rows or canonical {step_id:target_step_id} for unbound rows, then deadline ID. This preserves inherited simultaneous-expiry order exactly within ordinary rows. No step ID is inserted ahead of existing occurrence comparison. Preflight the union of eligible expiry closures atomically in this order; blocked/unbound expiries contribute evidence only. Limits, missing clocks, already-due successor conditions and overflow retain existing all-or-none closure consequences.

At binding, include any newly reachable expired duties in that event's complete closure preflight. Source target uniqueness and graph limits bound the closure. Never partially create targets, route some expiries or join one parent before a later closure fails. If any closure stops or fails preflight, retain the original event facts and completion or settlement of original source occurrences, but roll back every successor, obligation, deadline activation and activation counter introduced by the combined closure. Restore the prior binding fields of event duties whose new targets were rolled back, while retaining their newly established expiry evidence. Existing due occurrences retain the inherited completion and directly owned obligation consequences; unrelated preexisting siblings remain unchanged.

CLOCK DEADLINE details include expired unbound duty IDs without invented occurrences. Binding-time and dispatch-time expiry retain the base event's original details, then DEADLINE and eligible ROUTE/LIMIT in existing LIFE-006 kind order. Disposition is STOPPED for a stop/overflow; otherwise EXPIRED when expiry closure is committed. With no expiry closure preserve the base disposition, including DISPUTED and its original reasons. Evidence-only CLOCK expiry retains ordinary EXPIRED. Reason codes are the sorted union of base and deadline reasons. A disputed attempt never becomes proof of permission or delivery because a deadline also expired.

Active deadline_ids still names the source-declared deadline. Resolve it through exactly one inventory selected by its definition due kind: inherited deadlines, event_duties or deferred_deadlines. Reject missing or duplicate representations. Unbound duties exist at instance scope before an occurrence can reference them.

For definitions selecting event_anchors or any new deadline due kind, state.timing_clock_events is required and initialized empty. It contains every complete admitted CLOCK event sorted uniquely by event_id in raw UTF-8 order. Each row binds one-to-one to its CLOCK receipt by event_id and runtime-event digest. Retain it before computing the resulting core digest; refusal and exact replay append nothing. Its complete activation_clocks preserves projected closure inputs even when no activation committed. This append-only evidence inventory has no additional policy ceiling and remains outside mutable recovery projections.

For the same selected definitions, each GOVERNED outcome retains the complete original EFFECT_OBSERVED event in its existing source_event member, including activation_clocks. Restart binds it to the outcome's event_id and event_digest, the exact instance and its receipt. This requirement also applies when the completion policy is LEGACY_NONTERMINAL; terminal-completion evidence retains its inherited requirements. The retained source event proves the original input rather than reconstructing unused closure inputs from successful activations.

Restart recomputes native/wrapper digests, deployment subject binding, selected time, request subjects, fixed due, first trigger, complete original authority and clock event sequences, expiry/discharge basis, target occurrence and terminal consequences. It must reject changed anchors, omitted earlier qualifying evaluations or clock events, rewritten due, invented triggers, fabricated expiry clocks and completed roots that bypass unresolved duties. Recompute historical eligibility from preceding checkpoints; retain all original recovery and dispute bases.

Recovery before_projection and after_projection gain feature-conditional event_duties and deferred_deadlines, required when their corresponding feature is selected and omitted otherwise. Recovery checkpoint reversal restores these inventories together with inherited projected state. Immutable initial_event_anchors remain outside the mutable projection and are checked against the retained deployment binding.

## TIME-008. Source choices and external evidence

The source selects the event and subject, immutable record contract, measurement-age bound, duration, boundary, exact qualifying failed check and expiry response. A possible-send trigger proves no delivery. An unavailable clock proves no unobserved divergence time. Permit lifetime supplies neither observation age nor decision age. A prospective delay condition cannot be replaced by time already elapsed.

The host authenticates provider records, the organization and accepted clock source, checks truthful time and complete native facts, and monitors missing clock delivery. Digest equality proves binding, not those facts. A model judgment supplies neither an event timestamp nor authority. Source confirmation and organizational approval remain distinct from provider evidence. The readback includes every selected declaration and source mapping; omitted or unsupported source obligations remain visible through ordinary correspondence residue.
