# Work-class composition

Candidate: `seampoint.work-class/1.0.0-draft.2/composition`

Status: `DRAFT_NOT_ADOPTED`, `APPARATUS_ONLY`. This private technical-review draft replaces the draft-1 composition text for the `LINEAR`, `CHOICE_LOOPS`, `DEADLINES`, and `PARALLEL_FANOUT` profiles. It defines the admitted graph, occurrence identities, route selection, loop bounds, deadline activation, structured parallel obligations, and frozen fan-out. The lifecycle operation in `LIFECYCLE.md` applies these rules to events and state. Authority, aggregate, and shared reservation semantics remain those of `AUTHORITY.md`, `AGGREGATES.md`, `RESERVATIONS.md`, and `RESERVATION-RECORDS.md`.

## 1. Profile family

A work-class definition declares one profile. The profile is cumulative:

```text
LINEAR < CHOICE_LOOPS < DEADLINES < PARALLEL_FANOUT
```

`LINEAR` is the base profile. `CHOICE_LOOPS` includes every linear rule and adds exclusive labelled routing and bounded cycles. `DEADLINES` includes every choice and loop rule and adds explicit activity deadlines. `PARALLEL_FANOUT` includes every deadline rule and adds structured parallel blocks and frozen set fan-out.

A profile claim is a closed capability claim. The definition MUST use only fields admitted by that profile and MUST pass every lower-profile static check. A consumer MUST refuse a definition that contains a higher-profile construct under a lower profile. The refusal code is `UNSUPPORTED_FEATURE`. A consumer MUST NOT silently drop an edge, treat a structured block as a sequence, or treat a fan-out as one ordinary occurrence.

This candidate excludes invocation, dynamic fan-out, compensation, general cancellation, business-day calendars, provider-inferred deadlines, inclusive choice, first-completer joins, deadline-closed joins, nonblocking parallel blocks, distributed execution, and repeated expansion passes. Dynamic fan-out is outside the closed grammar, so an attempted dynamic field is `SCHEMA_INVALID`. A closed definition that represents a repeated expansion pass is `UNSUPPORTED_FEATURE`. Exclusion is reported as `EXCLUDED_FROM_PROFILE` in the coverage record.

## 2. Definition contract

A work-class definition contains these semantic groups. The JSON Schema gives each group a closed object shape and rejects undeclared fields.

| Group | Required meaning |
|---|---|
| Identity | Candidate pin, work-class identity, revision, profile, root and source references. The definition digest is computed from the complete canonical definition. |
| Participants | Declared participant identities, roles and kinds. Exact actor and credential bindings arrive with each proposal. |
| Objects | Declared object identities and types available to the work class. |
| Steps | Step identity, operation kind, fields, executor role, credentials, authority requirements, budgets, prior-effect field bindings, cross-occurrence actor separation, dispatch-permit duration and completion carrier. |
| Relationships | Ordered, typed graph edges with exact source and target. |
| Choices | Closed label type, completion-carrier source field and total label-edge mapping. |
| Loops and occurrence limits | Explicit bounded simple loops, per-step occurrence maxima and work-class proposal, activation and actuation maxima. |
| Deadlines | Deadline identity, active step, due rule, clock source, boundary and expiry target. |
| Blocks | Structured parallel split, branches, join and ancestry rules. |
| Fan-outs | Expand step, typed source field, region, join, object key and empty-set behavior. |
| Authority and budgets | Exact authority requirement and shared-budget identities. Their complete definitions and records use their own candidate schemas. |
| Source correspondence | The source identity, revision and obligation identifiers that the separate evidence records bind to the work class. |

The definition's graph and all referenced types are self-contained in the candidate's bundled schema graph. References are inert identifiers. They do not cause filesystem, network or repository access.

Definition inventories have unique semantic keys. Participant, object, type, step, loop, deadline, parallel-block and fan-out identifiers are unique. Choice and occurrence-limit records are unique by step. At most one deadline names a step. A step cannot be owned by two choices. A proposal-capable step cannot be a direct member of two sibling branch regions, two sibling fan-out regions or two non-ancestor structured constructs. Nested membership is permitted: the innermost branch or object region directly owns its proposal-capable steps, while each enclosing construct remains represented in occurrence ancestry and its obligation waits on the exact child pass. Structural split and join nodes form the boundary through which the parent region enters and leaves that child construct. Every proposal-capable step in a fan-out object region, including a nested child construct, contains the object-request field declared by each enclosing fan-out, with the corresponding object type. Those field names are distinct along one nested fan-out path. Participants, objects, types, steps, choices, occurrence limits, loops, deadlines, parallel blocks and fan-outs sort by their identifier or step key in raw UTF-8 order; the top-level shared-budget list and each identifier-valued set use the same order. Step fields sort by name. Relationships, choice label values and parallel branches retain declared source order and reject canonical duplicates. A fan-out pass that creates object occurrences also retains source order and rejects canonical duplicate object keys. The one `FANOUT_SET_DUPLICATE` policy-stop form defined by FAN-001 instead retains the complete duplicate source array, creates no occurrences or obligations and remains admissible on restart as evidence of the stop. Static validation rejects every other duplicate or out-of-order canonical inventory before graph evaluation.

### 2.1 Normalized relationship form

Every admitted relationship has one of four closed forms. Array order is source order. For example:

```json
{
  "kind": "SEQUENCE",
  "from": "review",
  "to": "publish"
}
```

The forms are `SEQUENCE`, `FAILURE`, `LABEL`, and `EXPIRY`. A `SEQUENCE`, `FAILURE`, or `LABEL` relationship is selected only by the corresponding terminal effect evidence. A `LABEL` relationship also carries one typed label. An `EXPIRY` relationship carries its deadline reference and is selected only by that deadline transition. A parallel or fan-out join uses its declared sequence edge only after the exact obligation inventory is discharged. A fan-out empty-set transition follows the construct's declared behavior.

A relationship has exactly one source, one target and one kind. Label and deadline fields exist only on their respective variants. A relationship cannot be selected by a proposal, dispatch observation, provider callback, or missing evidence. A consumer MUST reject duplicate canonical relationship records and ambiguous relationships before deployment.

The source order is retained in canonical form and in readback. It is used for deterministic evaluation when several independent records become eligible in one transition. A consumer MUST NOT sort source-defined arrays by a local map order or locale.

The normalized graph contains every declared relationship plus two kinds of construct edge. Each parallel block contributes one ordered edge from its split to each branch head. Each fan-out contributes one edge from its expand step to its region head. A branch or fan-out region reaches its declared join through an explicit relationship from each possible region tail; no implicit tail edge is supplied. Reachability and strongly connected component checks use this combined graph. A branch region is the set reachable from its head without crossing its block join or a sibling branch head. A fan-out region is the set reachable from its head without crossing its join. A nested child construct is treated as one structured subgraph for direct ownership: its split or expand boundary belongs to the parent path, its inner proposal-capable steps belong directly to the child regions, and its join returns to the parent path. Every path through either parent or child region must reach that region's declared join. Two regions may overlap only by strict nesting through those boundaries; partial overlap or entry into a child region anywhere except its split or expand boundary is `DEFINITION_INVALID`. Static admission rejects a graph that can produce an occurrence with more than 64 enclosing loop, branch or fan-out segments. This same bound limits the construct identifiers traversed by one structural closure. These rules determine direct ownership, ancestor membership, cross-boundary refusals and loop containment without inferring structure from step names.

Outgoing and construct edges obey this complete matrix:

| Source step or construct | Required and permitted edges |
|---|---|
| Ordinary `OPERATION` without a choice | exactly one `SEQUENCE` success edge; one `FAILURE` edge exactly when `failure_behavior` is `FAILURE_EDGE`; no `LABEL` edge |
| `OPERATION` with a choice | no `SEQUENCE` success edge; exactly one `LABEL` edge for every declared label value; one `FAILURE` edge exactly when `failure_behavior` is `FAILURE_EDGE` |
| `FANOUT_EXPAND` | exactly one fan-out construct names it; no `SEQUENCE` or `LABEL` success edge; one `FAILURE` edge exactly when `failure_behavior` is `FAILURE_EDGE` |
| `PARALLEL_SPLIT` | exactly one parallel block names it; its branch heads come only from that block's ordered implicit edges; it has no explicit outgoing relationship |
| `PARALLEL_JOIN` or `FANOUT_JOIN` | exactly one matching construct names it and exactly one outgoing `SEQUENCE` relationship selects its successor, which may be `TERMINAL`; it has no other outgoing relationship |
| `TERMINAL` | no outgoing relationship and no construct edge |
| Deadline on a proposal-capable step | at most one deadline names the step; it contributes exactly one `EXPIRY` edge when `expiry_target` is nonnull and none when expiry stops |

A parallel split has exactly one explicit incoming relationship from outside its block. A parallel branch head has only its block's implicit incoming edge, except for an admitted back edge wholly inside that branch. A fan-out region head has only its fan-out's implicit incoming edge, except for an admitted back edge wholly inside that object region. A parallel or fan-out join receives explicit relationships only from tails in its own region; every possible region path reaches that join. Ordinary operations, fan-out expand steps and terminal steps may have several incoming relationships when the closed choice, loop or structured graph rules distinguish them. A duplicate edge, an extra construct owner, an incoming cross-boundary edge or a cardinality outside this table is `DEFINITION_INVALID`; an undeclared endpoint is `REFERENCE_INVALID`.

### 2.2 Step records

A step record contains, at minimum:

```json
{
  "id": "review",
  "kind": "OPERATION",
  "executor_role": "reviewer",
  "interface": "review-service",
  "operation": "record-review",
  "fields": [{"name": "record-id", "type_ref": "identity"}],
  "scope_fields": {"subjects": ["record-id"], "resources": ["record-id"]},
  "required_credentials": ["reviewer-credential"],
  "authority_requirements": ["review-authority"],
  "shared_budgets": [],
  "prior_effect_bindings": [],
  "prior_actor_separations": [],
  "permit_seconds": "300",
  "failure_behavior": "FAILURE_EDGE",
  "completion": {
    "effect_provider": "review-provider",
    "effect_source": "review-service",
    "effect_record_type": "review-result",
    "no_effect_provider": "review-provider",
    "no_effect_source": "review-service",
    "no_effect_record_type": "review-no-effect",
    "status_field": "status",
    "status_type_ref": "status",
    "success_values": [{"type_ref": "status", "value": "ACCEPTED"}],
    "failure_values": [{"type_ref": "status", "value": "REJECTED"}],
    "route_label_field": null,
    "route_label_type_ref": null,
    "evidence_bindings": [
      {"request_field": "record-id", "evidence_field": "record-id"}
    ]
  }
}
```

The exact schema defines fields, credentials, authority, budgets, prior-history requirements and completion carriers. A `PARALLEL_SPLIT`, `PARALLEL_JOIN`, `FANOUT_JOIN`, or `TERMINAL` step is structural: it has null executor, interface, operation, scope fields, permit duration, failure behavior and completion fields and is never proposed or dispatched. It also has empty credential, authority, shared-budget, prior-effect and prior-actor arrays. An `OPERATION` or `FANOUT_EXPAND` step is proposal-capable and has nonnull executor, interface, operation, scope fields, failure behavior and completion fields. It also declares a positive `permit_seconds` value. That finite duration fixes how long the organization accepts proposal-time authority and observation snapshots for native dispatch. No implementation default supplies it. Scope fields contain sorted, unique, nonempty subject and resource field-name lists and follow the direct-authority meaning in `AUTHORITY.md`. A `FANOUT_EXPAND` completion carrier supplies the declared object collection; every other proposal-capable step requires `native_evidence.collections:[]`. An operation step has a complete, closed operation input contract. It cannot invoke another work class in this candidate. The root must be proposal-capable. A proposal-capable step carries exactly one authority requirement in this candidate. That identifier equals the complete authority input's envelope identifier. The envelope may require many checks, acts, observations and shared budgets; the one work-class identifier does not reduce that inventory. The definition's top-level `shared_budgets` is the raw UTF-8 sorted unique union of every proposal-capable step's shared-budget list, with no unused or omitted anchor. A proposal-capable step completes by routing to another proposal-capable step or to a structural node; a `TERMINAL` structural node has no outgoing relationship. The source obligation list is nonempty because every proposal must project the complete source obligation set into its authority input.

Every completion carrier declares exact `effect_provider`, `effect_source`, `effect_record_type`, `no_effect_provider`, `no_effect_source`, `no_effect_record_type`, `status_field` and `status_type_ref` values; every success and failure value has that exact scalar type. An established or unknown effect uses the effect triple. An affirmative no-effect record uses the no-effect triple. The selected triple must equal the corresponding native-evidence fields before the consumer interprets a result. The two triples may differ; neither is inferred from the other. `route_label_field` and `route_label_type_ref` are either both null or both nonnull. They are nonnull exactly for a declared choice, and the type equals that choice's `label_type_ref`. The carrier's status field, nonnull route-label field and evidence-field names are pairwise distinct. Each evidence field inherits the scalar type of its uniquely bound native request field. The success and failure arrays are canonical sets and are disjoint. The evidence bindings contain each native request field exactly once on the request side and use unique evidence field names. A missing or inconsistent reference is `REFERENCE_INVALID`; overlapping success and failure values, duplicate field names or bindings, an incomplete mapping, or a typed value that disagrees with its declared type is `DEFINITION_INVALID`. These declarations form the complete native completion-field contract; no ambient connector schema is needed to interpret a carrier. An operation's `failure_behavior` is `FAILURE_EDGE` exactly when it has one outgoing `FAILURE` relationship, and is `STOP` exactly when it has none. More than one failure edge is invalid. This step rule is the sole failure-policy declaration for choices and operations inside parallel or fan-out regions.

A matched effect performs the finite structural closure reachable from its selected relationship in that same lifecycle transition. Reaching a `PARALLEL_SPLIT` atomically creates its declared branch obligations and proposal-capable branch heads. Reaching a `PARALLEL_JOIN` or `FANOUT_JOIN` advances only when its exact retained obligations are discharged. Reaching a `TERMINAL` completes the instance. Static admission rejects a structural chain, structural cycle or structural target that would require another external event. An admitted effect whose structural closure would exceed a declared occurrence, activation, obligation or fan-out limit is retained and produces `STOPPED` with reason `LIMIT_EXCEEDED`; none of that closure's successor occurrences or obligations is created. Actuation limits are checked at proposal because structural closure creates no permit. This rule introduces no fifth lifecycle event.

An occurrence limit is a separate record containing a step identity and an exact nonnegative integer string. A limit is per work instance and step unless a containing construct explicitly declares a narrower scope. The work-class maximum actuation count is separate and cannot raise any step occurrence limit.

### 2.3 Prior-effect and actor bindings

A proposal-capable step may declare `prior_effect_bindings` and `prior_actor_separations`. Both arrays sort by record identifier in raw UTF-8 order and reject duplicate identifiers. Two prior-effect bindings on one step cannot name the same target request field. Structural steps require both arrays to be empty. These records express dependencies on retained governed history; they do not extend an authority envelope across steps.

A prior-effect binding has exactly `id`, `selection`, `source_step_id`, `source_evidence_field` and `target_request_field`. This candidate supports only `UNIQUE_COMPLETED_ANCESTOR`. The source and target are proposal-capable steps. The source step has a completion carrier whose evidence bindings contain the source evidence field exactly once, and that row binds it to exactly one source request field. The target request field occurs exactly once on the declaring step. The source request field and target request field have the same nominal `type_ref`, and the referenced type declaration is a supported scalar type. Missing steps or fields are `REFERENCE_INVALID`; a structural source or target, different types, a duplicate identifier or target, or an ineligible completion field is `DEFINITION_INVALID`.

A prior-actor separation has exactly `id`, `relation`, `selection`, `prior_step_id`, `prior_act_kind` and `current_act_kind`. This candidate supports only `DISTINCT_ACTOR` and `UNIQUE_COMPLETED_ANCESTOR`; the act kinds are `VERIFY` and `INSTANCE_DECISION`. The prior and current steps are proposal-capable and each declares one authority requirement. This work-class check cannot prove what a separately supplied authority envelope will select. LIFE-007 checks the exact selected acts at proposal time.

For both record kinds, the selected source must be in the recursive predecessor closure of the current occurrence. It must be a completed occurrence for the declared source step with disposition `SUCCEEDED`, established by exactly one retained governed `MATCHED` outcome that is not disputed and whose native-evidence digest equals the completed occurrence's evidence digest. Zero eligible occurrences, including a source whose establishing outcome is now disputed, is `PREREQUISITE_MISSING`; more than one is `BINDING_MISMATCH`. The consumer does not choose by time, ordinal, array position or graph distance. Another instance, a sibling path and any occurrence outside the predecessor closure are ineligible.

### 2.4 Choice records

A choice record contains:

```json
{
  "step_id": "route",
  "label_type_ref": "route-label",
  "label_values": [
    {"type_ref": "route-label", "value": "APPROVE"},
    {"type_ref": "route-label", "value": "REJECT"}
  ]
}
```

A choice has exactly one source step, one label type and a finite list of allowed typed values. The step's completion carrier identifies the label field. Its `LABEL` relationships provide the complete label map. Every allowed value appears exactly once, and every label edge targets one step. An ordinary `SEQUENCE` edge cannot coexist with label edges on the same choice step. A declared `FAILURE` relationship is separate from the success label map.

The label is read from `route_label_field` in the exact native record of a matching terminal `EFFECT_OBSERVED` event. The proposal cannot carry a route label. A dispatch observation cannot carry one. The lifecycle does not use a default label, a language model, a connector status or a process-local value. If the terminal effect's label is absent, unknown, duplicated, or fails the declared type, the effect record is retained and the lifecycle admits `STOPPED` with `LABEL_INVALID`. No successor is active.

The static definition is inadmissible when a route is missing, duplicated, ambiguously typed, or points outside the definition. A schema-admitted choice whose label domain lacks one exact target is `DEFINITION_INVALID`. A reference to an undeclared target is `REFERENCE_INVALID`. A static mapping error is an input refusal at validation or deployment. It is separate from an invalid label observed at runtime.

Every completion, routing, expiry and obligation-discharge rule below applies only after `LIFECYCLE.md` classifies the occurrence and event as eligible to progress. A `BLOCKED_DISPUTE`, closed, late, unknown, unexpected, foreign, conflicting or budget-disputed case retains evidence and reconciles exposure under the lifecycle rule without applying a normal composition route, except where that rule states a specific evidence-only state change.

## 3. Linear profile

A `LINEAR` definition has one root and a sequence of operation occurrences. Each admitted terminal effect selects one declared success or failure relationship. A transition may activate at most one successor for a linear occurrence. A terminal relationship records the declared terminal result and activates no successor.

The linear graph MUST satisfy all of these conditions:

- The root is declared and reachable.
- Every step is reachable from the root.
- Every nonterminal step has a declared success or failure relationship appropriate to its operation result.
- Every relationship target is declared.
- A graph cycle is absent in this profile.
- A path ends in a declared terminal or declared stop.
- No parallel, choice, deadline, fan-out or unsupported construct appears in the definition.

A `PROPOSE` event may create an actuation for the currently active occurrence after authority and reservation checks. `DISPATCH_OBSERVED` never activates a successor. A matching terminal `EFFECT_OBSERVED` for an eligible unresolved occurrence discharges the exact occurrence and applies its relationship atomically. A dependency-blocked occurrence retains later conclusive evidence without discharge or routing under LIFE-013. A foreign or wrong occurrence record cannot satisfy the active occurrence.

The first root occurrence has ordinal `1`. Each successor activation has a new occurrence identity. A completion for a prior occurrence cannot satisfy a later one, even when the step ID is the same in a profile that permits that repetition.

## 4. Choice and bounded loops

`CHOICE_LOOPS` adds exclusive labelled choices and bounded cycles to the linear graph.

### 4.1 Choice routing

A matching terminal success effect at a choice step supplies exactly one value at the declared label field. The consumer validates the value against the closed label type and looks up the exact route. It records the native effect, the selected label, and the relationship in the same atomic transition that completes the occurrence. It activates the selected target only. Unselected targets never become obligations.

A terminal failure effect uses the source step's declared failure relationship. The relationship is absent exactly when that step declares `STOP`. The consumer does not treat a failure as a success label and does not select a route from an incomplete or unknown effect.

An observed invalid label is a runtime policy stop. The transition retains the full terminal effect, actuation identity, reservation treatment, label extraction result and error reason. It returns `STOPPED` with `LABEL_INVALID`, leaves no successor active, and prevents new scheduling under the declared stop semantics. The state remains reviewable and the effect is not converted into a refusal.

### 4.2 Cycle admission

This candidate admits bounded simple loops through explicit loop records. A loop record contains `id`, `entry_step_id`, the complete sorted set of `member_step_ids`, `back_edge_from_step_id`, and positive `maximum_passes`. Its one back edge is the relationship from `back_edge_from_step_id` to `entry_step_id`. The loop member set must equal one cyclic strongly connected component in the normalized relationship graph. Every cycle in that component must cross the declared entry and the one back edge. Loop member sets cannot overlap or nest in this candidate. An undeclared cycle, another back edge, a cycle that bypasses the entry, or a cross-loop edge is `UNSUPPORTED_FEATURE`.

Pass one begins when the entry is first activated from outside the loop. Taking the declared back edge increments the pass. Every operation occurrence in the loop carries one `LOOP` enclosing segment with the loop identifier and current pass; branch and fan-out segments remain in their outer-to-inner positions. Activation beyond `maximum_passes` is a retained `STOPPED/LOOP_BOUND_REACHED` decision and creates no new occurrence. Every recurring step also has a positive `occurrence_limit`. Activation at that step maximum is allowed; the next activation is a retained `STOPPED/LIMIT_EXCEEDED` decision. These checks occur in complete structural preflight before any successor or obligation is created.

The loop record and graph must agree exactly. The entry belongs to `member_step_ids`; the named back-edge source belongs to that set; exactly one declared relationship runs from that source to the entry; and no other relationship inside the component returns to the entry. Entry from outside allocates pass `1`. A relationship inside the loop preserves the current pass, and selecting the one back edge allocates current pass plus one. An edge leaving the loop removes its segment. Since loop member sets cannot overlap or nest, the current loop pass is one plus the largest retained pass for the pair `(loop_id, exact outer enclosing prefix)` only when the back edge is selected; a new outer branch or object context begins at one. The state therefore needs no process-local loop counter.

An occurrence ordinal is one plus the largest retained ordinal for that step across the work instance, or one when no occurrence of the step exists. Root ordinal is one. Parallel-block and fan-out pass numbers are one plus the largest retained pass for the pair `(construct_id, exact outer enclosing prefix)`, or one on first entry in that context. All ordinals and passes use exact natural-integer arithmetic. When one transition activates several branch or fan-out occurrences, allocate them in declared source order after preflighting the complete set. Their persisted values cannot depend on worker order or process memory.

`maximum_activations` counts all created proposal-capable occurrences, including root, loop, branch and fan-out occurrences; structural nodes do not count. The corresponding total and per-step activation counters increment at occurrence creation. `maximum_actuations` counts initial `PERMITTED` proposals and increments only when the first permit and any required reservation commit for an occurrence. Renewing an expired, undispatched permit does not create another actuation and does not increment this counter. An initial proposal that would exceed the limit records `STOPPED/LIMIT_EXCEEDED`, creates no permit or reservation and leaves the registry unchanged. A higher work-class maximum cannot override a step occurrence or loop-pass maximum.

Static admission requires a positive root occurrence limit, a positive `maximum_activations`, and values within WCS2-004. `maximum_actuations`, `maximum_active_obligations`, and `maximum_fanout_objects` may be zero because a valid work class may deliberately admit no actuation, no concurrent obligation, or only an empty fan-out. Initial-proposal preflight checks `maximum_actuations` after authority succeeds and before evaluating a cloned reservation transition. A failure records `STOPPED` with a `LIMIT` detail of kind `ACTUATIONS`; the authority result remains retained, while no permit, reservation or registry receipt is created.

When one atomic closure would cross several limits, the one `LIMIT` detail uses this precedence: `STEP_OCCURRENCES`, `LOOP_PASSES`, `ACTIVATIONS`, `ACTIVE_OBLIGATIONS`, then `FANOUT_OBJECTS`. `ACTUATIONS` applies only during proposal preflight and therefore does not compete with a structural closure. The detail records the selected declared limit, the projected count that would result, and the applicable step or relationship. All crossed limits may remain visible in implementation diagnostics, but they do not change the canonical decision.

Structural preflight uses this first-failure order: per-step occurrence maximum, loop pass maximum, total activation maximum, active-obligation maximum, then fan-out object maximum. It computes the complete union before creating a successor. Active or unresolved obligations are those with status `OPEN`, `BLOCKED`, `WAITING` or `DISPUTED`; discharged or joined obligations do not count. `maximum_fanout_objects` applies to each frozen expansion set, while `maximum_active_obligations` bounds the instance-wide concurrent inventory. If several records fail the same limit, the detail identifies the first proposed activation in declared relationship, branch, deadline, or object source order. The triggering effect and reservation settlement commit, its occurrence closes, zero successor occurrences or obligations from the failed closure are created, and the instance becomes `STOPPED`. The `LIMIT` detail records the kind, declared limit, projected value, source step and selected relationship digest when present.

A proposal retry with the same event identity is exact replay and changes no counter. A new occurrence requires a fresh proposal, current authority evaluation, current credential and observation bindings, and current reservation evaluation. Authority for occurrence one does not authorize occurrence two. The persisted counters survive restart and are covered by state identity.

### 4.3 Choice and loop cases

A conforming suite includes every declared label, success and failure route, missing and unknown observed label, duplicate static mapping, a loop activation at its exact maximum, the next attempted activation, an earlier actuation limit, exact replay, altered replay and foreign completion. Every case includes the complete next state and retained evidence.

## 5. Activity deadlines

`DEADLINES` adds a persisted deadline to an active operation occurrence. The profile uses the clock and event rules in `LIFECYCLE.md`.

### 5.1 Deadline definition

A deadline record contains:

```json
{
  "id": "deadline-1",
  "step_id": "review",
  "due": {
    "kind": "ELAPSED_DURATION",
    "value": "60",
    "unit": "MINUTE"
  },
  "clock_source": "clock-1",
  "boundary": "AT_OR_AFTER",
  "expiry_target": "escalate"
}
```

The definition's `due` declaration is an exact UTC `ABSOLUTE_INSTANT`, an exact positive `ELAPSED_DURATION`, or an exact positive `ELAPSED_FROM_ANCESTOR` with `value`, `unit` and `anchor_step_id`. An elapsed declaration is added to the admitted activation instant. An ancestor declaration is added to the `occurred_at` instant of the anchor occurrence, which is the one completed occurrence of `anchor_step_id` in the recursive predecessor closure of the occurrence the deadline activates with. Either result is the absolute instant persisted in the deadline-state field `due`. Static admission requires an ancestor declaration's anchor to be a proposal-capable step other than the deadline's own step, not a member of any loop, not inside a fan-out region that does not also contain the deadline's step, and on every path from the root to the deadline's step in the normalized graph; together these make the anchor occurrence exist and be unique at every activation. A declaration that fails any of them, including one on the root step, is `DEFINITION_INVALID`; an undeclared anchor step is `REFERENCE_INVALID`. The profile supports `AT_OR_AFTER` and `AFTER` only. A proposal-capable step has at most one deadline, so one occurrence cannot select competing expiry routes. A deadline has exactly one expiry relationship or an explicit stop result. It cannot infer a target from a step name.

`expiry_target` is nonnull exactly when there is one `EXPIRY` relationship whose `from` equals the deadline step, whose `to` equals that target and whose `deadline_ref` equals the deadline ID. A null target means explicit stop and requires no such relationship. Another, duplicate or mismatched expiry edge is `DEFINITION_INVALID` or `REFERENCE_INVALID` as applicable.

A deadline is activated with its operation occurrence. The closed state record stores `deadline_id`, `occurrence_id`, `activation_digest`, `trigger_digest`, `source`, `activation_revision`, `activation_clock_revision`, `activation_instant`, `activation_clock_evidence_digest`, `due`, `boundary`, `status` and nullable `expiry_event_digest`, exactly as LIFE-014 and `lifecycle.schema.json` define them. Restart uses this persisted record. It does not recalculate `due` from the current clock or local timezone.

The candidate excludes business-day, holiday, fiscal-calendar, provider SLA and implicit local-time rules. Aggregate calendar windows are a separate aggregate feature and do not supply deadline semantics.

### 5.2 Clock and expiry

Only an admitted `CLOCK` event updates the accepted lifecycle clock. A clock event identifies its declared source and revision. An available sample whose revision is greater than the stored revision updates the clock. A stale or backward revision is refused. An unavailable or conflicting sample is an admitted retained fact with `CLOCK_UNAVAILABLE` and cannot establish expiry.

After accepting an available clock, the consumer evaluates every active deadline whose predicate is satisfied. It orders simultaneous expiry records by due instant, complete occurrence identity and deadline ID. For an eligible non-`BLOCKED_DISPUTE` occurrence, the expiry record removes the occurrence from dispatchable active work, retains the clock and deadline evidence, and follows the declared expiry relationship or stop result. For a dependency-blocked occurrence, the deadline becomes `EXPIRED` as evidence while the occurrence and obligation remain blocked; no expiry route or stop is applied. LIFE-014 defines the mixed due-set transition.

`AT_OR_AFTER` is satisfied when the accepted clock's `observed_time >= deadline_state.due`. `AFTER` is satisfied only when `observed_time > deadline_state.due`. A clock exactly at an `AT_OR_AFTER` `due` instant expires an eligible occurrence or records evidence-only expiry for a dependency-blocked occurrence. A clock exactly at an `AFTER` `due` instant does not.

Completion and expiry are ordered by admitted event sequence. A terminal effect admitted before the expiry transition completes the occurrence. A later clock event cannot expire it. A clock event admitted first expires the occurrence. A later effect is late evidence and cannot rewind the route, even if the provider event time precedes the due instant. The effect time remains available for review and reservation settlement.

Expiry does not release a reservation. Pending dispatch, unknown effect, and unsettled reservation records remain retained. Timeout, revocation, and permit expiry do not satisfy the affirmative no-effect evidence and organizational authorization required for release.

### 5.3 Deadline cases

A conforming suite includes one instant before due, exactly due and one instant after for both predicates, an unavailable clock, a conflicting sample, a stale revision, wrong source, replay, completion before expiry, a late effect after expiry, an unknown effect retained after expiry, and restart preserving the persisted due instant.

## 6. Structured parallel work

`PARALLEL_FANOUT` adds structured parallel blocks and frozen fan-out to all lower-profile rules.

### 6.1 Block definition

A parallel block contains one split, at least two branches and one join:

```json
{
  "id": "block-1",
  "split_step_id": "start-review",
  "branches": [
    {"id": "legal", "head_step_id": "legal-review"},
    {"id": "finance", "head_step_id": "finance-review"}
  ],
  "join_step_id": "reviews-complete"
}
```

Each proposal-capable branch step uses its own exact `failure_behavior` and matching edge. A failure edge may route within the same branch; reaching the block join discharges that branch obligation. A step-level `STOP` stops the instance and leaves sibling activity and exposure recorded. It does not cancel or release sibling activity unless a later profile explicitly adds that behavior. A branch cannot jump into another branch, leave the block before the join, or bypass the join without reaching the declared block join.

The admitted lifecycle event whose selected relationship targets `split_step_id` is the trigger. It is either an eligible matching effect for the proposal-capable predecessor or an eligible `CLOCK` event that expires that predecessor. A structural closure carries a nonempty frontier of predecessor occurrence identities. It starts with the triggering operation occurrence; after a join it becomes the recursively computed completion frontier of that joined pass. The structural split itself has no completion carrier or event. During that same effect or clock transition, the consumer creates one obligation and one active occurrence for every declared proposal-capable branch head in source order. Every new branch occurrence copies the current sorted frontier into `predecessor_occurrence_ids`. It creates none if a static or dynamic limit, identity or state check fails. A partial branch set is never returned.

Each branch occurrence's enclosing path identifies the block pass and branch ID. Branch source order determines atomic creation order and is recoverable from the immutable definition; it is not a separate occurrence-digest field. A nested block retains all outer block, branch, pass and object identities. A completion from another branch or pass is foreign and cannot discharge the obligation.

### 6.2 Obligation and join rules

The split creates an immutable obligation identity inventory for the exact pass. Each obligation's immutable fields are its ID, kind, construct and pass, sorted nonempty `source_occurrence_ids`, branch or object identity, join step and creation event digest. `source_occurrence_ids` equals the current structural frontier, and `creation_event_digest` is the digest of the exact admitted lifecycle `EFFECT_OBSERVED` or `CLOCK` event whose structural closure entered the split. The identifier is `digest("obligation",{kind,construct_id,pass,source_occurrence_ids,branch_id,object_key,join_step_id})`.

An obligation has one of five closed state variants. The two `DISPUTED` variants are distinguished by whether the unresolved conclusion came from a retained completion basis or a child pass:

| State | Occurrence fields | Child-pass field | Completion field |
|---|---|---|---|
| `OPEN` or `BLOCKED` | nonnull `expected_occurrence_id` and `required_operation` | null | null |
| `WAITING` | both null | exact nonnull `waiting_on` child-pass reference | null |
| `DISCHARGED` or `JOINED` | both null | null | exact nonnull `completion_basis` |
| `DISPUTED` after an unjoined completion becomes disputed | both null | null | the retained nonnull `completion_basis` |
| `DISPUTED` because a child pass contains a disputed obligation | both null | the retained nonnull `waiting_on` child-pass reference | null |

`OPEN` names one current active occurrence whose status is not `BLOCKED_DISPUTE`. `BLOCKED` names one exact `BLOCKED_DISPUTE` occurrence. When an eligible direct route within the same branch or object region activates one operation successor, the obligation replaces its expected occurrence and required operation atomically. When that direct route reaches its own join, the obligation becomes `DISCHARGED` with a `DIRECT_EVENT` completion basis. The basis contains the lifecycle event digest, final occurrence and operation, and either `digest("native-evidence",event.native_evidence)` for success, declared failure or authorized no-effect, or the accepted `CLOCK.evidence_digest` for expiry. Only the innermost branch or object region directly owns that occurrence. An enclosing parent obligation is `WAITING` on the exact child pass and does not also name the inner occurrence.

When the directly owned occurrence enters a nested parallel split or nonempty frozen fan-out, its `OPEN` obligation becomes `WAITING` in the same transition that creates the exact child obligations. `waiting_on` is `{kind,construct_id,pass,outer_enclosing,obligation_ids}` for that newly created pass. `outer_enclosing` is the complete enclosing prefix before the child construct's branch or object segment; it distinguishes passes whose numerical pass values restart in different contexts. A parallel reference contains at least two child obligations and a fan-out reference at least one. The occurrence and operation fields become null. Any outer ancestor obligation was already waiting on the parent pass and does not change. A child policy stop, limit stop or stopped-instance late evidence that prevents the child join leaves the parent `WAITING`; it does not manufacture parent completion.

When the transition stops during nested-entry preflight before creating a child obligation inventory, the directly owning obligation does not enter `WAITING`. It becomes `DISCHARGED` with the triggering operation's `DIRECT_EVENT` completion basis and no join fires. This rule covers occurrence, activation, obligation or fan-out limits, duplicate or explicitly stopping empty fan-out sets, and missing or invalid activation-clock consequences that retain the triggering effect or expiry as a policy stop. The instance becomes `STOPPED`; outer ancestor obligations remain `WAITING` on their existing child passes.

When every obligation in the exact child-pass reference has status `DISCHARGED` during an eligible transition, the child join marks them `JOINED` and resumes the one parent obligation that waits on that pass. `BLOCKED` or `DISPUTED` never satisfies this predicate. If the child join's closure activates one operation in the parent region, the parent becomes `OPEN` and names that occurrence and operation. If it immediately enters another child split or nonempty fan-out, the transition replaces `waiting_on` with the new exact child-pass reference. If it reaches the parent join, the parent becomes `DISCHARGED` with a `CHILD_PASS` completion basis containing the joining lifecycle event digest and the complete child-pass reference. Empty fan-out advance creates no child obligations and uses the expand occurrence as the structural frontier, so it either resumes, waits on a later nonempty child pass or discharges the parent within the same event without persisting a zero-member wait.

One event may discharge several obligations, especially one `CLOCK` event with a due set. After applying all direct discharges in an `ACTIVE` instance, the consumer repeatedly joins every newly complete pass and resumes its waiting parent until no further pass is eligible. A pass joins at most once. At each fixed-point round, eligible passes are ordered by greater enclosing depth first and then by the canonical bytes of their complete child-pass reference. Independent joins commute because their state records are disjoint; the declared order fixes occurrence allocation, limit detail selection and canonical output when their continuing closures create new work together. The consumer preflights the complete fixed-point result before creating any successor, replacement wait or ancestor discharge. A stop anywhere in that preflight retains the direct event results, creates none of the proposed continuation, discharges only the directly triggering obligations with their direct bases, and leaves waiting ancestors unresolved in the stopped instance. A stopped-instance late effect or deadline may therefore leave an all-`DISCHARGED`, not-`JOINED` pass; the retained stop decision proves why the join did not fire.

The completion frontier of a `DISCHARGED` or `JOINED` direct basis is its one final occurrence identity. The completion frontier of a `DISCHARGED` or `JOINED` child-pass basis is the raw UTF-8 sorted unique union of the recursively computed completion frontiers of every child obligation named by that exact completed pass. A `DISPUTED` obligation has no join-eligible completion frontier. Empty fan-out advance contributes the expand occurrence. The recursion follows strict enclosing depth, cannot cycle and contains at most the work class's `maximum_activations`, which is bounded at 4096. The consumer carries this complete frontier through structural joins. It writes the set into every successor occurrence's `predecessor_occurrence_ids` and every newly created obligation's `source_occurrence_ids`. Static admission or structural preflight refuses or stops any graph or transition that cannot represent the complete frontier; it never truncates the set.

When the join fires, every `DISCHARGED` obligation in that pass becomes `JOINED` and retains its completion basis. The join waits for every obligation created for that pass to have status `DISCHARGED`. It does not count graph nodes, visible workers or currently active children. Section 7 applies the same state variants and progression rules to each `FANOUT_OBJECT` obligation, using object key instead of branch ID and the fan-out join instead of the parallel join.

Branch completion and obligation discharge occur atomically. When the final obligation is discharged during an eligible `ACTIVE` transition, the join activates its declared successor in the same transition. A join with one pending or disputed obligation remains pending. A repeated completion for the same operation is exact replay or an idempotent duplicate according to the event identity rules. Conflicting terminal evidence remains retained and marks the conclusion disputed. If the affected obligation is still `DISCHARGED`, it becomes `DISPUTED` while retaining its completion basis. The consumer then changes every `WAITING` ancestor whose exact child-pass reference contains the newly disputed obligation to the waiting form of `DISPUTED`, retaining that child-pass reference, and repeats this propagation outward. A `DISPUTED` obligation cannot return to `DISCHARGED` or satisfy a join in this candidate. An obligation already `JOINED` remains historical; LIFE-013 blocks dependent active descendants through the completed occurrence frontier without rewinding the join.

A branch failure applies that operation step's declared failure behavior. Under `STOP`, the instance admits a stop, schedules no new work and discharges the triggering branch obligation without firing its join. Other open obligations remain visible with their expected active occurrences. Already dispatched sibling actuations, pending reservations and unknown effects remain in state. A late effect for a nondependency-blocked sibling may update its exact actuation and reservation and discharge that sibling obligation without firing the join; it cannot restart a stopped branch or reopen the join. A `BLOCKED_DISPUTE` sibling retains the evidence and remains blocked under LIFE-013.

A cycle may be contained wholly inside one branch or wholly outside the block. A relationship that passes through a split or join and returns to an ancestor is refused. A loop inside one branch retains branch ancestry and applies the occurrence maximum to each exact recurring step.

### 6.3 Parallel cases

A conforming suite includes atomic split creation for two branches, state restart after the split, one incomplete branch, final join after all actual obligations complete, choice within one branch, nested ancestry, nested split persistence, child join to a parent successor, a child join that discharges its parent, a child stop that leaves its parent waiting, restart from each waiting and disputed variant, dispute propagation through a child frontier, a discharged branch disputed before its sibling completes, a branch-local loop, an invalid cross-boundary edge, duplicate evidence, a failed branch, a one-object stopped pass that remains unjoined and a late sibling effect after stop.

## 7. Frozen set fan-out

A frozen fan-out creates a finite, immutable set of object-bound occurrences from one terminal effect. It is a structured construct within `PARALLEL_FANOUT`.

### 7.1 Fan-out definition

A fan-out record contains:

```json
{
  "id": "fanout-1",
  "expand_step_id": "list-objects",
  "object_field": "items",
  "object_request_field": "invoice-id",
  "object_type_ref": "invoice",
  "region_head_step_id": "process-invoice",
  "join_step_id": "all-invoices-complete",
  "empty_set_behavior": "ADVANCE_TO_JOIN"
}
```

The source `object_field` is a typed ordered collection in `native_evidence.collections` of the exact terminal record for the expand step. Each collection contains its name, element type and ordered scalar typed values. `object_type_ref` must equal that element type and declares the type of each canonical object key. `object_request_field` names the scalar native-request field that carries this object identity in every proposal-capable step reached within the object region, including steps inside nested constructs. The named step field must exist and have exactly `object_type_ref`. For nested fan-outs, every proposal-capable descendant includes one distinct request field for each enclosing fan-out; static admission rejects a missing field, a type mismatch or reuse of one field name for two fan-out identities on the same path. The work-class limits declare the maximum fan-out objects. `empty_set_behavior` is required and is one of `ADVANCE_TO_JOIN` or `STOP`. A missing policy makes the definition inadmissible. Neither behavior is a default.

The region has one head, one all-done join and a finite set of operation steps. An edge from the region to a step outside the join is invalid unless it is the declared join relationship. A cycle whose member set contains the expand step or the all-done join is invalid in this candidate, whichever relationship kind reaches that step. Cycles that stay entirely inside the region interior remain admissible. A fan-out region cannot contain a repeated expansion pass.

### 7.2 Expansion transition

A matching terminal effect at the expand step supplies the complete array. The consumer validates the field, object type, object key field, canonical key representation and declared maximum before activating any object occurrence. Malformed JSON, a value outside the closed typed-value schema or noncanonical bytes are admission refusals. Schema-valid attributable evidence with a missing or different collection name, wrong declared element type, duplicate unexpected collection or value that disagrees with the completion carrier is retained as `UNEXPECTED/DISPUTED`; it creates no object occurrence.

The consumer preserves the source array order in `object_keys`. The canonical key includes its declared type and exact canonical value. Duplicate keys are a dynamic policy stop after the effect is retained, with reason `FANOUT_SET_DUPLICATE`; no object occurrence is activated. A wrongly typed object, missing key, invalid canonical value or malformed native record is an input refusal when the effect cannot be evaluated as the declared source.

If the array is empty, the consumer follows the explicit `empty_set_behavior`. `ADVANCE_TO_JOIN` records one pass with `object_keys:[]`, `obligation_ids:[]` and `joined:true`, then follows the join's declared successor or terminal through the same finite structural closure without creating an object obligation. `STOP` records one pass with the same empty inventories and `joined:false`, then admits `STOPPED` with `FANOUT_EMPTY`. The state retains the expand effect and the selected policy. The consumer cannot infer another result.

For a nonempty valid array, the consumer freezes the full object key list and creates one obligation and one active object occurrence per array element in source order as one atomic transition. If any object would exceed a declared object, occurrence, activation, obligation, fan-out or public-state collection limit, the consumer retains the expand effect and admits the declared fan-out limit stop. It creates no partial object set. Actuation limits do not apply to expansion because expansion creates occurrences and obligations rather than permits. A failed atomic transition leaves state unchanged only when the input itself is invalid or stale. A valid policy limit is an admitted stop with the preceding effect retained.

The pass record is determined before the transition returns:

| Expansion result | `fanout_pass` row | `object_keys` | `obligation_ids` | `joined` |
|---|---|---|---|---|
| Malformed collection or an effect classified `UNEXPECTED` before expansion | none | not applicable | not applicable | not applicable |
| Duplicate canonical object key | one row for the allocated pass | exact source-order keys, including the duplicate | empty | false |
| Empty set with `ADVANCE_TO_JOIN` | one row for the allocated pass | empty | empty | true |
| Empty set with `STOP` | one row for the allocated pass | empty | empty | false |
| Valid nonempty set whose complete structural preflight fails | one row for the allocated pass | complete source-order keys | empty | false |
| Successful nonempty expansion | one row for the allocated pass | complete source-order keys | complete obligation identities in source order | false until every obligation discharges, then true in the transition that fires the join |

A policy stop therefore preserves the set that was actually evaluated without implying that any child occurrence or obligation was created. Static or event admission refusal creates no pass row. Replaying the admitted expansion returns the retained row without allocating another pass.

When the expand occurrence is directly owned by an outer obligation, successful nonempty expansion changes that parent obligation to `WAITING` on the exact `FANOUT` child-pass reference in the same transition. Empty advance uses the expand occurrence as the frontier and continues without a waiting state. Duplicate-key, empty-stop and limit-stop results discharge the directly owning obligation with a `DIRECT_EVENT` basis without firing its join, as the nested preflight-stop rule requires. A top-level fan-out has no parent obligation to update.

Each object occurrence includes the fan-out pass identity, fan-out ID, occurrence ordinal, canonical object key and complete enclosing ancestry. The pass retains the source-ordered object key list, and the allocation rule derives occurrence ordinals in that order. The object key list is immutable. A later source read cannot add, remove, reorder or replace an object. A nested fan-out retains the outer object key and all inner pass identities. Before authority or reservation evaluation, each proposal in that ancestry must supply the exact `object_request_field` for every enclosing fan-out and its typed value must equal that segment's retained object key. A missing, duplicated, wrongly typed or unequal binding is `BINDING_MISMATCH` and changes no work or budget state. Authority still governs the complete request; it cannot replace this occurrence-to-object binding.

### 7.3 Object completion and join

An object completion discharges only the exact object occurrence and operation it names. An effect for another object, region, pass or ancestry is foreign. It may be retained as unexpected evidence when it binds to the instance; it cannot satisfy an obligation.

The all-done join waits for the obligations actually created for the frozen set. It does not require a completion for an unselected branch, an object omitted by the source array, or a zero-object set under `ADVANCE_TO_JOIN`. During an eligible `ACTIVE` transition, it activates its declared successor atomically only when every actual obligation has status `DISCHARGED`.

A late object effect after expiry or stop remains retained and may settle its exact actuation under the reservation contract. It cannot create a new object occurrence, change the frozen set, reopen the join or erase the earlier expiry or stop decision.

### 7.4 Repeat expansion exclusion

The candidate excludes repeated expansion passes within one exact outer enclosing prefix. The source material contains two incompatible rules: one says expansion cycles are refused, while another describes later repeat passes. The concrete disputed shape is an edge from the completed all-done join back to the same expand step under that same outer prefix. This candidate refuses that edge as `UNSUPPORTED_FEATURE` before general graph-cycle analysis. First entry to the same fan-out under a different outer branch or object prefix is a distinct context and receives pass `1`. The consumer does not reset object limits within a context or infer whether prior object exposure carries forward.

A future profile may define repeat passes with explicit pass identities, exposure accounting, authority re-evaluation and bounds. This candidate does not qualify that behavior.

### 7.5 Fan-out cases

A conforming suite includes zero, one and several objects; explicit empty-set advance and stop; missing empty-set policy; duplicate keys; wrong types; source-order preservation; a proposal whose object-request field names another object; nested outer and inner object-request bindings; nested ancestry; a source change after expansion; a foreign object completion; full-set limit stop; attempted partial creation; and attempted repeat expansion.

## 8. Cross-profile limits and authority

Every concrete operation, branch, object, loop occurrence and deadline target is subject to the authority requirements and aggregate or shared budget rules declared by the work class. A grant covering an object type does not prove authority for an object value outside its scope. A grant used for one operation occurrence does not silently authorize a later occurrence. The authority evaluator's complete result is rechecked for each proposal and occurrence.

A structured split, join, or fan-out transition cannot bypass reservations. If the definition requires shared budgets for branch or object operations, the `PROPOSE` event for each operation uses the current budget states and exact revision. The split or expansion transition records obligations and active occurrences; it does not grant permits for every child. Each child requires a separate proposal and atomic authority/reservation decision.

A stop leaves all committed effects, actuation records, reservation exposure, unknown outcomes and evidence in the state. The profile does not treat stop as cancellation or no effect. The reservation contract determines whether later settlement, dispute or authorized release is possible.

## 9. Static admission and refusal

Static validation runs before deployment and establishes the graph's meaning. It MUST:

1. Verify that the root, steps, relationships, participant requirements and types are declared.
2. Normalize relationships and reject duplicate, ambiguous or out-of-profile triggers.
3. Check reachability from the root and termination at a declared terminal or stop.
4. Check each cycle and require a finite limit on every recurring step in `CHOICE_LOOPS` and higher profiles.
5. Check total choice label maps, closed label types and exact effect field references.
6. Check deadline references, clock sources, due rules, boundaries and expiry targets.
7. Check structured block splits, branch heads, joins, nesting and cross-boundary edges.
8. Check fan-out source field, object-request field and type bindings through every nested region, region, join, global maximum and explicit empty-set behavior.
9. Reject cycles through fan-out expansion or join and reject repeated expansion passes.
10. Check that profile, authority, aggregate, reservation and host-boundary requirements are explicit.
11. Check every prior-effect field reference, type equality, prior-actor relation and proposal-capable source and target.
12. Apply candidate limits and return typed refusal before any instance state is created.

A static refusal is distinct from a runtime policy stop. A definition with a duplicate label route is invalid before deployment. A valid definition whose native effect supplies an unknown label reaches a retained `STOPPED/LABEL_INVALID` decision. A definition with no fan-out empty-set policy is invalid. A valid definition with an empty set follows its declared `ADVANCE_TO_JOIN` or `STOP` policy.

The refusal precedence for static composition checks is: transport and schema, candidate/profile identity, canonical bytes and digest, reference and type validity, graph identity and reachability, unsupported topology, label/deadline/block/fan-out completeness, then declared limit and host-boundary checks. The lifecycle refusal precedence governs events after deployment.

## 10. Determinism and state

The definition retains source order for relationships, label routes and branch declarations. Each fan-out pass retains source order in `object_keys` and `obligation_ids`. The work-state `fanout_passes` collection sorts by fan-out identifier, numerical pass and expand occurrence identifier. No two rows may share that tuple. The work-state `obligations` collection itself sorts by obligation ID as LIFE-019 requires; it does not preserve creation order a second time. Every occurrence, pass, branch, object, actuation and deadline has an explicit identity. State updates use the event sequence and exact expected state digest. The consumer never relies on map iteration order, current process memory, current local time, a provider callback without binding, or a later reread of a mutable object set.

A split, fan-out expansion, join, expiry route and terminal effect route are each single atomic lifecycle transitions. When a transition has multiple affected state records, the work state and every affected reservation state advance together. A refusal leaves all state unchanged. A valid policy stop records the triggering evidence and stop reason and leaves prior state history intact.

The reference host serializes event submissions in one process. It does not establish durable storage, authentic observations, identity authentication, connector atomicity or distributed coordination. Those host obligations are documented in `EXTERNAL-DEPENDENCIES.md` and are reported separately from semantic consumer qualification.

## 11. Conformance obligations

A composition implementation claiming `CHOICE_LOOP_RUNTIME` MUST pass the complete linear and choice/loop cases. A `DEADLINE_RUNTIME` claim also requires every lower-profile case and the clock/deadline cases. A `PARALLEL_FANOUT_RUNTIME` claim requires all prior cases and the block/fan-out cases. Capabilities cannot claim a profile whose static, transition, state, replay or host tests are absent.

The suite compares complete canonical decisions, receipts, state and digests. It includes exact replay, altered replay, stale state, foreign subjects, invalid route labels, limit stops, late effects, state restart, generated inputs, state interchange and mutations. A pure graph validator does not qualify the lifecycle runtime. A state transition pass does not qualify serialized contention. A single-process host pass does not qualify durable or distributed enforcement.

The expected judgment for each case is derived from the rule and input before implementation output is disclosed. The derivation records the profile, paragraph IDs, exact event sequence, state transition, decision class, retained evidence and any host boundary. An implementation disagreement triggers a specification or case review. It cannot be resolved by masking fields or adding an undocumented default.
