# Work-class 1.0 scope and boundary

Identity: `seampoint.work-class/1.0.0-draft.2`. This open review candidate defines a portable contract for deterministic governance of bounded work. It is a draft for technical review and does not qualify a production deployment.

The candidate includes four executable profiles:

* `LINEAR` admits a single successor for each completed occurrence.
* `CHOICE_LOOPS` adds total labelled routing and bounded recurrence.
* `DEADLINES` adds persisted clock events, due instants and expiry routing.
* `PARALLEL_FANOUT` adds structured parallel obligations and frozen object sets.

All profiles use the same canonical bytes, exact digest domains, authority bindings, aggregate and reservation records, refusal precedence, and state-transition shape. One lifecycle occurrence may reserve several budget anchors when they belong to one shared reservation registry; cross-registry atomic proposals are outside this candidate. A profile declaration is part of the work-class definition digest. A consumer must refuse a profile it does not claim rather than interpreting it as linear work.

Repeated expansion passes remain excluded. The source material contains both a prohibition on expansion cycles and a later description of repeat passes. The disputed edge is the all-done join returning to the same expand step. Dynamic fan-out, compensation, general cancellation and distributed execution are also excluded from this candidate.

## Boundary records

The contract separates semantic rules from facts supplied by a host or organization. A `CLOSED_DOCUMENTED_BOUNDARY` record closes the description of that dependency. It contains the affected paragraph and requirement identifiers, the external fact or capability, its responsible party, the control or integration that supplies it, the evidence format, failure behavior, verification method and residual limitation. It does not assert that the host has supplied a true fact.

The reference consumers qualify semantic decisions over supplied records. The reference host qualifies serialized single-process transitions, state persistence within the process, and reservation contention. Deployment assurance remains with the host. In particular, the host must authenticate people and credentials, establish the truth and freshness of observations, protect and durably commit state, perform conditional native dispatch, and provide distributed coordination if it runs more than one process. A missing boundary input produces the specified refusal or hold; it never creates a permissive default.

## Roles and claims

`AGGREGATE_EVALUATOR` evaluates typed cumulative exposure. `AUTHORITY_EVALUATOR` evaluates business authority and exact subject bindings. `SHARED_BUDGET_TRANSITIONS` applies reservation, renewal, settlement and release transitions. `LINEAR_WORK_RUNTIME`, `CHOICE_LOOP_RUNTIME`, `DEADLINE_RUNTIME` and `PARALLEL_FANOUT_RUNTIME` implement the corresponding state machines. `REFERENCE_SINGLE_PROCESS_CONTENTION` qualifies the serialized reference host. `REVIEW_EVIDENCE` checks mechanical correspondence and review records.

Each capability claim is tied to the exact candidate pin, protocol, role and implementation manifest. Passing the suite establishes the reported semantic role for that implementation and suite. It does not establish organizational authorization, observation truth, identity authentication, durable crash recovery, native connector behavior or distributed atomicity.
