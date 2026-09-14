# Authority admission and check inventory

Status: `DRAFT_NOT_ADOPTED`, `APPARATUS_ONLY`. This normative companion closes the mechanical inventory used by AUTH-005/006. The JSON Schema fixes shape; the following relations and orders remain normative semantic admission requirements.

## Static definition admission

An authority definition is exactly `{schema,source,work_class,envelope}`, with schema `seampoint.work-class/1.0.0-draft.2/authority-definition`. Its digest kind is `authority-definition`. Validate/readback admit these complete bytes, not a detached envelope whose type and source dependencies are absent. Readback renders every scalar leaf and empty collection in this complete definition. A successful validate result hashes this definition; it does not establish a grant or ready a proposal.

All work-class types have AGG-001 scalar rules. Type/step/field identifiers are unique, and every declared field resolves to one type. Every envelope operation resolves to its exact work-class triple and executor role. The work class may declare additional steps outside this envelope; their existence grants no authority for them. A complete work runtime must establish their own applicable envelopes separately. Source and class digests are recomputed. All source_obligations resolve to supplied source identifiers. This proves correspondence of identifiers only; uncovered source meaning requires human review and cannot be discharged by code.

Each step's scope_fields.subjects and scope_fields.resources are sorted unique nonempty field-name lists. Every field resolves to a declared IDENTITY/STRING type. At application its value must be nonempty; the derived actual_scope lists are sorted unique. Actual subjects/resources must be subsets of the corresponding grant scope lists; failure is BINDING_MISMATCH. The result retains both scopes without changing the native proposal.

Bindings resolve against exact step/field declarations of IDENTITY or STRING kind; their values at application must be nonempty. Binding selectors resolve by id. Selector lists sort by canonical bytes and have no duplicate selector bodies. Constant scope and the union of substituted scope follow AUTH-001. Envelope operation rows sort by step. Condition, criterion and per-action limit rows sort by id; ids are unique within their respective collection. Every row's step occurs in envelope operations. A gate with VERIFY or DECIDE has at least one criterion for every permitted step; its selected act names exactly the criterion ids applicable to the proposed step. The complete per-step criterion inventory remains immutable in the envelope.

A FIELD operand resolves against that row's declared step and has its field's nominal type. Static literal types and all operand compatibility are checked even if another branch determines the predicate. A per-action bound's field and typed bound share one nonnegative numeric type. LT/LTE have their mathematical upper-bound meaning. Every envelope operation has at least one per-action bound or the envelope names shared budgets. An applicable shared budget must later select and reserve at least one contribution from that operation; declaring an unrelated anchor cannot complete the bound.

Materiality and gate requirements are checked at definition admission and again when applying the definition. A weaker gate is BINDING_MISMATCH. Required mechanisms are exactly `[AUTHORITY_BEFORE_RESERVATION]` without shared budgets, otherwise the UTF-8 sorted set `[ATOMIC_SHARED_RESERVATION,AUTHORITY_BEFORE_RESERVATION]`. Required escalation is retained policy; neither definition validation nor authority readiness asserts its delivery.

## Record and time admission

Every complete interval has valid whole-second UTC endpoints, valid_from strictly before a nonnull valid_until. Null means explicitly unbounded above. All supplied dates are validated even in unused records. max_age_seconds is a natural integer with at most 128 digits. All nominal values are checked against the supplied class; unknown type references are REFERENCE_INVALID, malformed scalar values TYPE_INVALID. WCS2-004 finite collection, expression and number bounds also apply. Limits are checked after shape and scalar/reference integrity but before policy evaluation; they never cause wrapped arithmetic or a claimed policy refusal from a crash.

Root/source/class/envelope references match exact complete bytes. Each selected capacity binds that exact root/envelope. All supplied capacity and occupancy ids belong to the root's permitted inventories; every permitted id has exactly one supplied complete record. The authenticated-record tuples are exactly those derived from all supplied occupancy, capacity, credential and return records using their digest kind and provider/channel. Missing tuples or complete referenced bodies are EVIDENCE_UNAVAILABLE; extra or mismatched tuples are DEPENDENCY_MISMATCH. Every provider and return channel is selected by the root. Occupancy, capacity, credential and return record ids are unique within each collection; the same spelling in distinct record kinds is not an implicit relation.

Capacity act_kinds are a sorted unique list. Every selected act's capacity, occupancy, actor, role and principal match; capacity.root_digest and envelope_digest match complete selected records. Root and capacity principal equal envelope principal. The executor occupancy matches every executor field; executor role equals the envelope and work-class step role. Exactly the step's required credential kinds are selected, one record per kind, for that actor, occupancy and operation triple. Surplus credentials are DEPENDENCY_MISMATCH; missing required credentials are EVIDENCE_UNAVAILABLE. A supplied credential first binds its complete occupancy body: a different credential actor is a phase-2 DEPENDENCY_MISMATCH, and a missing occupancy body is EVIDENCE_UNAVAILABLE. Matching those complete records to the proposal executor and operation is phase 3. Credential and executor current intervals are checked at application, independently of old grant acts.

Returned_at is no earlier than its act's occurred_at and no later than the evaluation instant. Channel validity is tested at returned_at. Current channel reliance requires validity at evaluation or an explicit prior_returns_survive_expiry flag. A channel that fails this at evaluation is a phase-4 return-channel failure, so the refusal is ACT_NOT_AUTHORIZED with empty reasons and failed checks. Act-time root/capacity/occupancy checks do not use returned_at as a substitute. A current-root expiry does not erase old acts if the root explicitly permits survival; current withdrawal remains required. Occupancy expiry by itself does not erase an act made during valid occupancy; current capacity reliance determines continued use.

An unavailable clock still permits all directly checkable shape, dependency, static application and historical act checks. Omit comparisons against the missing current instant. In phase 5 return AUTHORITY_NOT_ESTABLISHED with sole reason CLOCK_UNAVAILABLE before deriving current queries or checking their inventory. Wrong digest bodies, malformed supplied queries and date errors remain earlier failures. No machine-clock read fills the missing instant.

## Exact successful check construction

Write `S`, `W`, `E`, `P`, `O`, `R` for the computed source, class, envelope, proposal, operation and root digests and `now` for the admitted clock instant. These symbols explain construction and are not wire fields. Every emitted check has exactly purpose, subject_digest, requirement_ref and at; successful readiness means all emitted checks were satisfied. There is no caller-supplied check array.

| Purpose | Subject | Requirement | Time |
|---|---|---|---|
| SOURCE_BINDING | E | source.id | now |
| ROOT_BINDING | E | root.id | now |
| INPUT_SUPPORT | O | proposal.step | now |
| BINDING | O | envelope.scope.id | now |
| GATE_FLOOR | E | envelope.id | now |
| ENVELOPE_VALIDITY | E | envelope.id | now |
| EXECUTOR_OCCUPANCY | O | executor.occupancy | now |
| CONDITION | O | each condition.id for proposal.step | now |
| PER_ACTION_LIMIT | O | each limit.id for proposal.step | now |
| CREDENTIAL | O | each required credential.id | now |
| ACT_CAPACITY | digest of each selected act | its capacity id | act.occurred_at |
| ACT_OCCUPANCY | digest of each selected act | its occupancy id | act.occurred_at |
| ACT_RELIANCE | digest of each selected act | its capacity id | now |
| RETURN | digest of each selected act | its exact return id | now |
| SEPARATION | digest of each attestation | its capacity id | now |
| GATE_CRITERION | digest of selected VERIFY/INSTANCE_DECISION | each applicable criterion.id | gate act.occurred_at |
| REVOCATION | exact root/capacity/envelope/credential digest queried | query digest | query.at |

Root and each act's capacity are queried at every relevant act occurrence and at now. Envelope and selected credentials are queried at now. One exact subject/declaration/time query is required once even if several checks use it. Query digest uses the complete query under kind `authority-query`. Historical root or capacity withdrawal evidence concerns that historical instant. Current queries concern current reliance. The matching revocation declaration determines max_age; subjects cannot select a different allowance.

Observation arrays may arrive in any order. Collapse exact canonical duplicate rows. Different rows with the same query, including different evidence references, conflict; do not choose a revision by spelling or timestamp. Check the complete derived query inventory and all exact query digests before interpreting statuses. A missing query is EVIDENCE_UNAVAILABLE; an unrequested/mismatched query is DEPENDENCY_MISMATCH. Canonical revisions are opaque nonempty identifiers. No hidden state infers which revision is newer. Authentication, completeness and nonrollback choice are host responsibilities.

## Deterministic refusal selection

Every refusal has exactly `{status:"REFUSED",code,path:"",reasons:[...],failed_checks:[...]}`. Phase order governs before the following within-phase code orders. Accumulate directly checkable failures within the phase and select its first code; do not let loop order choose a different result.

1. SCHEMA_INVALID, ARTIFACT_ENCODING_INVALID, ARTIFACT_NONCANONICAL, TYPE_INVALID, INPUT_INVALID. This includes every embedded return's bytes and schema. Duplicate/sort inventory errors are INPUT_INVALID. Type-reference resolution is deferred to phase 2 when necessary to distinguish a missing declaration from a malformed known value.
2. VERSION_UNSUPPORTED, DEPENDENCY_MISMATCH, EVIDENCE_UNAVAILABLE, UNSUPPORTED_RELATION, REFERENCE_INVALID, LIMIT_EXCEEDED. Version is checked first; complete digest bindings precede unsupported relations. An id cannot stand in for its missing body.
3. BINDING_MISMATCH. Exact field inventory, declared types at application, operation matching, scope substitution and materiality floor are application checks.
4. ACT_CONFLICT, GATE_REQUIRED, EVIDENCE_UNAVAILABLE, ACT_NOT_AUTHORIZED, ACT_NOT_ACCEPTED. Extra/competing selected acts precede missing gate evidence; missing other required acts/returns/bodies follow. Subject, principal, role, capacity, occupancy, act-time validity, return-channel and separation failures are ACT_NOT_AUTHORIZED. A selected non-ACCEPT disposition is ACT_NOT_ACCEPTED. Check inventories by expected act role/subject so swapped identities cannot masquerade as absent records.
5. DEPENDENCY_MISMATCH, EVIDENCE_UNAVAILABLE, AUTHORITY_NOT_ESTABLISHED. Resolve observation inventory before dispositions. CLOCK_UNAVAILABLE has the special early treatment above. For other AUTHORITY_NOT_ESTABLISHED results, reasons are the sorted unique union of all failed current/historical revocation, current validity, condition, per-action limit and gate-criterion checks. The enum in the schema fixes reason spelling. Missing current validity or withdrawal is never a default pass.

Reasons are empty for every code except AUTHORITY_NOT_ESTABLISHED. ACT_EXPIRED and CAPACITY_EXPIRED are reserved reason tokens and are not emitted for phase-4 act-time refusals, whose reasons remain empty. Current credential expiry uses CREDENTIAL_EXPIRED, envelope expiry ENVELOPE_EXPIRED, executor occupancy expiry ACT_EXPIRED, current capacity reliance failure RELIANCE_EXPIRED, current root expiry without survival ROOT_EXPIRED, unavailable/incomplete/conflicting/stale observations their named reason, and a true revoked value REVOKED. False field predicates and exceeded bounds use CONDITION_VIOLATED, GATE_CRITERION_VIOLATED or PER_ACTION_LIMIT_VIOLATED. Contradictory observations suppress interpreting either revoked value for that query; retain OBSERVATION_CONFLICT.

`failed_checks` records how an AUTHORITY_NOT_ESTABLISHED refusal was decided. It has one row `{purpose,subject_digest,requirement_ref,at,reason}` for every reason a failed phase-5 check contributed. `purpose`, `subject_digest`, `requirement_ref` and `at` are exactly the values the Exact successful check construction table assigns to that check, and `reason` is that reason; a check that contributed two reasons, such as an observation that is both stale and revoked, has two rows with equal check values. A current root expiry without survival is reported against the `ROOT_BINDING` check. Rows sort by canonical bytes and are unique, and the set of their reasons equals `reasons`. `failed_checks` is empty for every other code and for the CLOCK_UNAVAILABLE refusal, which evaluates no check.

Digest-domain selection is a semantic rule. All authority digest kinds are listed in AUTH-001, supplemented by authority-query in AUTH-005 and authority-definition here. A digest-shaped string alone does not validate either the subject bytes or the selected domain. The schema intentionally owns syntax while these rules own recomputation.
