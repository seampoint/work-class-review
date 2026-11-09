# Source observations and current dispatch authorization

The explicit independent-decision, source-vector, dynamic completion and correction alternatives in [INDEPENDENT-HUMAN-DECISIONS.md](INDEPENDENT-HUMAN-DECISIONS.md) govern when selected. All inherited carrier inventories and behavior remain unchanged when those members are absent.

Status: `DRAFT_NOT_ADOPTED`, `APPARATUS_ONLY`. This normative candidate companion defines the exact observation and gated dispatch ABI used by AUTH-007 and LIFE-009A. Shape admission and matching synthetic evidence do not authenticate host facts or establish real provider coordination.

## 1. Closed values, types and inventories

Every shape below is a closed JSON object. Listed fields are required unless explicitly marked optional. `id`, `digest`, natural-number strings, nominal type declarations, typed values and named typed fields use the existing aggregate ABI. A typed value is `{type_ref,value}`; a named typed field is `{name,value}` with a complete typed value. A reference does not fetch an absent record. Existing canonical-byte, digest, scalar, resource and protocol rules apply.

Add scalar kind `INSTANT`. Its type declaration has `nonnegative:false` and `unit:null`; values are strictly valid whole-second UTC strings in `YYYY-MM-DDTHH:MM:SSZ` form. Calendar validation rejects impossible dates, leap seconds, fractions, offsets and overflow. Typed malformed values are `TYPE_INVALID`; raw date-member errors retain existing `INPUT_INVALID` admission. There is no implicit string-to-instant conversion. Scope selectors remain IDENTITY/STRING, and numerical operators remain numerical.

Add optional operation-step member `authority_type_refs`, a sorted unique array of at most 64 nominal type identifiers. Each resolves to an authority-supported scalar declaration in the work class. It can name observation-only and literal-key types without creating native request fields. The lifecycle authority projection copies this member when present and includes the union of native field types, declared references and every type referenced by a projected completion carrier. It projects a LEGACY_NONTERMINAL carrier when exclusive keys apply, and always projects a STOP_RETAIN carrier, including its identity, event-time and additional field types when no exclusive keys apply. It also copies `dispatch_gate` when present, independently of keys. Empty or omitted `authority_type_refs` preserves the inherited projection. Every observation field, selector result, literal and literal exclusive-key value must use a type inside that exact projection universe. Unknown references are `REFERENCE_INVALID`; no consumer adds types by reading values or inventing fields.

Source requirements sort uniquely by `id`; each requirement's field declarations sort uniquely by `name`, and relations sort uniquely by `id`, all in raw UTF-8 order. The existing envelope ABI admits at most 64 source requirements. Each requirement admits at most 64 fields and 256 relations, with a semantic maximum of 256 source relations for one step. Schema maxima produce `SCHEMA_INVALID`; a semantic bound or calendar-arithmetic overflow produces `LIMIT_EXCEEDED` at its prescribed admission phase. Dispatch fence sources admit 1..64 rows. Optional properties remain absent when omitted; default semantics do not insert properties into canonical bytes.

## 2. Requirement and selector ABI

A source-observation requirement has exactly these required members:

```text
{id, step, purpose, provider, source, record_type, subject, record_id,
 at, freshness_seconds, expected_status, fields, relations}
```

`purpose` retains the closed inventory AUTHENTICATED_SESSION, ROLE_ASSIGNMENT, DUTY_ASSIGNMENT, SAFETY_HOLD, AUTHORITY, COMPLETION and DUPLICATE. `record_id` is an id or null. `fields` contains `{name,type_ref}` declarations. `expected_status` is AVAILABLE or ABSENT. `at` is a strict raw instant or the exact string `CLOCK`. Optional `evaluation_point` is PROPOSE or PROPOSE_AND_DISPATCH, with omitted meaning PROPOSE. Optional `key_projection` is a nonempty bounded array of the closed shapes `{field,type_ref}` or `{field,type_ref,key_field}`. Every field resolves to the requirement step's native proposal declaration with its exact nominal type. `key_field`, or `field` when omitted, is the unique canonical query-key name; projection rows sort by that effective name. This source-query projection does not admit constants or arbitrary selectors.

`subject` is either the inherited nonempty fixed id string or one of these closed selectors:

```text
{kind:"PROPOSAL_FIELD", field}
{kind:"EXECUTOR", member, type_ref}
```

Executor `member` is actor, role, principal or occupancy. Subject-selector types must be IDENTITY or STRING in the declared projection. Proposal-field selectors infer the field's declared nominal type. The resolved subject is a nonempty identity string. Empty or unequal application binding is `BINDING_MISMATCH`; unknown field/type references are `REFERENCE_INVALID`. A subject selector never changes the proposal or selects a different executor.

A relation has exactly `{id,kind,left,right}`, except `ELAPSED_LTE`, which has exactly `{id,kind,left,right,maximum_seconds}`. Each operand is an inherited local observation-field name or one closed selector:

| Selector shape | Exact value selection |
|---|---|
| `{kind:"PROPOSAL_FIELD",field}` | The unique named typed field in this step's exact authority proposal. |
| `{kind:"EXECUTOR",member,type_ref}` | The complete proposal executor's actor, role, principal or occupancy, represented by a declared IDENTITY/STRING nominal type. |
| `{kind:"ACT",act_kind,member,type_ref}` | The unique independently admitted selected act of kind GRANT, VERIFY or INSTANCE_DECISION. Members id, actor, role and principal require IDENTITY/STRING; occurred_at requires INSTANT. |
| `{kind:"OBSERVATION_FIELD",requirement_id,field}` | The referenced requirement's declared field and matching actual typed value. |
| `{kind:"OBSERVATION_ID",requirement_id,type_ref}` | The referenced AVAILABLE record's provider_record_id, under a declared IDENTITY/STRING type. |
| `{kind:"CLOCK",type_ref}` | The accepted available authority clock instant, under a declared INSTANT type. |
| `{kind:"LITERAL",value}` | The complete, statically admitted nominal typed value. |

Inherited local strings resolve only against the current requirement's field declarations. All operands are statically checked, including unused requirements and branches. ACT resolves only among the acts selected and admitted by existing authority rules; no selector supplies an act, bypasses an attestation or turns a copied identity into authority. Missing or competing selected acts retain phase-4 EVIDENCE_UNAVAILABLE/GATE_REQUIRED or ACT_CONFLICT precedence.

OBSERVATION_FIELD and OBSERVATION_ID must target an in-step requirement whose expected status is AVAILABLE and whose evaluation selection supplies it whenever the referencing requirement runs. Otherwise admission is `UNSUPPORTED_RELATION`. A PROPOSE_AND_DISPATCH requirement cannot depend on a PROPOSE-only requirement. Historical fixed-instant requirements may themselves be PROPOSE_AND_DISPATCH. Requirement-reference edges must be acyclic; a cycle is `INPUT_INVALID`. Local field operands create no cross-requirement edge. A known field/type mismatch is `TYPE_INVALID`; a missing declared reference is `REFERENCE_INVALID`.

EQUALS and NOT_EQUALS require identical nominal type references and compare canonical scalar values. BEFORE, AFTER, AT_OR_BEFORE and AT_OR_AFTER require identical nominal types of kind INSTANT and compare validated instants with their stated strict or inclusive boundaries. INCLUDES remains `UNSUPPORTED_RELATION` because this slice has no collection operand. No alias, case conversion, coercion or lexical comparison of arbitrary strings supplies a typed relation.

ELAPSED_LTE requires identical nominal types of kind INSTANT. Its canonical natural `maximum_seconds` permits zero and is subject to the existing 128-digit coefficient bound. It holds exactly when `0 <= right - left <= maximum_seconds`, using exact whole-second arithmetic. A future left-hand measurement fails. Missing, unusable or false operands contribute SOURCE_OBSERVATION_RELATIONS against the declaring requirement. The complete relation, including its bound, belongs to the derived query and copied observation relations. Other relation variants reject `maximum_seconds`. This relation measures the difference between the selected events; `freshness_seconds` independently limits response age from `as_of`. Fetching a record now cannot make an older measurement current.

## 3. Evaluation selection and exact queries

Authority input gains optional `evaluation_point`, PROPOSE or DISPATCH; omission means PROPOSE. PROPOSE selects all source requirements for the proposed step. DISPATCH selects only that step's PROPOSE_AND_DISPATCH requirements. Standard authority selection, historical act checks, current validity and ordinary root/capacity/envelope/credential revocation checks always run under both points. Source requirement selection does not suppress them.

Lifecycle PROPOSE and registry RESERVE/RENEW require effective PROPOSE; supplying effective DISPATCH is `INPUT_INVALID`. Standalone authority evaluation may select DISPATCH, but readiness grants no reservation, dispatch or effect. AUTHORIZE_DISPATCH requires an explicitly supplied DISPATCH input for a gated step. It cannot reuse the proposal's result as its current authority judgment.

A derived source query has exactly these required members:

```text
{requirement_id, step, at, provider, source, record_type, subject, record_id,
 purpose, freshness_seconds, expected_status, fields, relations}
```

Derive `requirement_id` from requirement.id; resolve CLOCK to the accepted authority clock instant; resolve the subject selector to its nonempty string; copy every other required declaration member exactly. Copy optional `evaluation_point` only when it was explicitly present on the requirement. Do not copy `key_projection`. When it exists, derive optional `key` as named typed proposal fields using each effective key name, sorted by that name. No key member appears otherwise. Query digest is `digest("authority-query",complete_query)`. Neither evaluation defaults nor selector objects leak into the resolved query.

All source and ordinary revocation queries form one exact derived inventory. Ordinary revocation queries retain `{purpose:"REVOCATION",subject_digest,at,provider,source}`. Their current at values refresh to the new accepted clock; historical at values remain the selected act's occurrence instant. Provider/source/subject coordinates come from immutable declarations and selected bodies. Different nominally similar queries remain different. Missing queries are `EVIDENCE_UNAVAILABLE`; unrequested, substituted or wrong-digest queries are `DEPENDENCY_MISMATCH`, which wins when both faults occur.

Observation order is immaterial. Exact canonical duplicate rows collapse. Distinct rows for the same query produce the applicable conflict reason; no timestamp or opaque revision spelling selects a winner. A missing or unusable dependency never supplies a default relation value. After inventory admission, a requirement depending on such a record fails SOURCE_OBSERVATION_RELATIONS in addition to the referenced requirement's own failure.

An unavailable authority clock retains existing special precedence: after directly checkable phases 1..4, return AUTHORITY_NOT_ESTABLISHED with sole reason CLOCK_UNAVAILABLE and no failed checks before deriving current queries or requiring their inventory. Earlier malformed supplied query/date/dependency faults still refuse. No ambient clock or prior available clock fills the missing instant.

## 4. Observation records and policy checks

AVAILABLE has exactly:

```text
{query, query_digest, status:"AVAILABLE", as_of, revision, provider_record_id,
 fields, relations, evidence_ref, provenance_digest}
```

`as_of` is a valid instant, revision and provider_record_id are nonempty opaque ids, fields are named typed values, and relations are copied declarations. Query identity supplies provider/source/type; provenance and evidence references remain retained host assertions. The actual field inventory must match every declared name and nominal type exactly. A missing, extra, duplicated or wrong-declaration-type actual field contributes SOURCE_OBSERVATION_FIELDS. Malformed known typed values remain earlier TYPE_INVALID. Available copied relations must equal the requirement's complete relation declarations, but that equality never proves their truth. Independently resolve and compare every actual operand; a copied-declaration mismatch or any false/unproven relation contributes SOURCE_OBSERVATION_RELATIONS.

Complete ABSENT has exactly:

```text
{query, query_digest, status:"ABSENT", as_of, revision,
 fields:[], relations:[], coverage:"COMPLETE", evidence_ref, provenance_digest}
```

`as_of` and revision are nonnull; there is no provider_record_id or usable record value. ABSENT requirements declare empty fields and relations; nonempty field declarations are INPUT_INVALID and unsupported absence relations are UNSUPPORTED_RELATION. The old ABSENT branch with null time/revision is removed. Existing author-derived ABSENT evidence must be migrated explicitly; a complete ABSENT response still withholds when AVAILABLE is required. Unavailable evidence cannot satisfy an absence requirement.

UNAVAILABLE, INCOMPLETE, CONFLICT and ROLLED_BACK retain the closed unavailable shape with null as_of/revision, empty fields/relations and nonempty evidence/provenance references. ROLLED_BACK is an attributed provider assertion; the consumer cannot infer it from opaque revisions. The host owns authentication, coverage, applicability and nonrollback truth.

Require `as_of <= query.at <= current evaluation instant` and `query.at - as_of <= freshness_seconds` for usable AVAILABLE/ABSENT evidence. A future or inconsistent instant contributes SOURCE_OBSERVATION_TIME; exceeding freshness contributes SOURCE_OBSERVATION_STALE. Zero freshness means exact as_of equality with query.at. Current equipment facts use CLOCK and zero freshness. A fixed historical query measures freshness against its declared historical instant, while current reliance is checked independently. Authentic fresh provider access is not established by matching timestamps alone.

Check expected status and, for AVAILABLE with nonnull requested record_id, exact provider_record_id. A complete usable status unequal to expected or wrong record identity contributes SOURCE_OBSERVATION_BINDING. SOURCE_OBSERVATION_ABSENT is not emitted for a complete status mismatch under this wire. Unusable statuses contribute their exact SOURCE_OBSERVATION_UNAVAILABLE, INCOMPLETE, CONFLICT or ROLLED_BACK reasons. A contradictory query group contributes only its conflict check before interpreting its competing values. Collect all independent applicable failures canonically; do not let iteration order choose a result.

Each requirement emits successful check `{purpose:"SOURCE_OBSERVATION",subject_digest:envelope_digest,requirement_ref:requirement.id,at:resolved_query_at}`, where envelope_digest is the existing digest("authority-envelope",envelope). Failed checks add the exact reason to that same row. requirement_ref remains the requirement id, including relation failures; the retained full declaration and evidence inventory reproduce the comparison. Checks/failed checks sort uniquely by canonical bytes. Policy failure is AUTHORITY_NOT_ESTABLISHED with the sorted unique union of reasons; other refusal codes have empty reasons and failed checks.

The authority-evidence preimage retains existing host_selection, occupancies, capacities, credentials, acts, returns, observations and clock members. Add evaluation_point if and only if it is explicitly present in the authority input. This preserves inherited omitted-member bytes and binds explicit point selection in new evidence. All other authority digest domains retain their existing complete-body construction.

## 5. Dispatch gate and immutable permit basis

The inherited `approval_requirement` form of an operation's optional `dispatch_gate` has exactly:

```text
{approval_requirement, withdrawal_requirement, policy_withdrawal_requirements,
 fence_provider, fence_source, authorization_seconds}
```

`authorization_seconds` is a strictly positive natural string. The policy requirement inventory is sorted unique, bounded to 64, and disjoint from the two singular requirement ids. Every reference resolves within the selected step, uses at:CLOCK and explicit PROPOSE_AND_DISPATCH, and has zero freshness. Approval is an AUTHORITY-purpose AVAILABLE requirement with a nonnull exact requested record identity; approval-withdrawal and policy-withdrawal requirements expect ABSENT. Admission and authority evaluation enforce this complete gate inventory before readiness or dispatch. The complete union is bounded to 64 sources. Equipment declares exactly approval, approval withdrawal, MCS-12 policy withdrawal and DR-08 policy withdrawal. fence_provider/source identify the conditional-write coordinator; they do not collapse those independently named evidence sources into one revision.

A structurally admitted gate that violates these gate-specific declaration constraints refuses UNSUPPORTED_RELATION. Earlier canonical, schema, reference-resolution and nominal-type refusals retain their existing precedence. A failed current observation follows the authority policy-result rules rather than this static declaration rule.

A successful proposal for a gated step retains complete authority_basis in its permit. It is the exact original admitted PROPOSE authority input, including every supplied record and optional-member presence. Restart recomputes that original result, selected acts, subject/projection bindings, clock, fixed envelope validity and original permit expiry. A missing basis for a gated permit is STATE_INVALID. It is not inferred from a result digest or reconstructed by fetching current records.

The refreshed authority_input may change only clock, observations and evaluation_point. Its schema, pin, source, work_class, envelope, proposal, host_selection, occupancies, capacities, credentials, acts and returns are byte-identical to authority_basis. In particular root, selection_evidence, authenticated-record tuples, selected providers/channels, credential identities, executor and grant/attestation/gate acts remain immutable. A new actor, grant, envelope, root or authenticated-record selection requires a new proposal under its own admission rules; a dispatch refresh cannot amend it.

The observation inventory is freshly derived for DISPATCH. Current ordinary revocation query at values and query digests may change; their immutable subjects and declarations may not. Historical queries retain exact historical subjects/times but may carry newly attributable evidence for those same queries. Source queries resolve their declared dynamic subject, key and CLOCK from the same immutable proposal/executor and new clock. PROPOSE-only rows are excluded, and an extra old row is DEPENDENCY_MISMATCH. Do not merge stale proposal observations into a fresh input or silently choose their result.

## 6. AUTHORIZE_DISPATCH ABI and derived fence

For a gated step the complete event is:

```text
{schema:"seampoint.work-class/1.0.0-draft.3/runtime-event", event_id,
 kind:"AUTHORIZE_DISPATCH", instance_id, expected_state_revision,
 expected_state_digest, permit, native_request, connector,
 authorization_fence, observation_digests, clock_revision,
 authority_input, dispatch_intent_id}
```

Permit is the exact admitted unsuperseded permit; native_request equals its complete request; connector retains `{id,version,binding_digest}` with the existing connector-binding digest. dispatch_intent_id identifies only one admitted event across retained authorization records and authorization evaluations in the work instance, including withheld evaluations. A successful event's paired authorization and evaluation share that same identifier. Reusing it in another event is BINDING_MISMATCH; exact lifecycle-event replay returns the original committed result without a new authorization or connector invocation. The host's claim identity is `{instance_id,dispatch_intent_id}`. The submitted authorization_fence may be null on this gated event; ungated AUTHORIZE_DISPATCH events still require their nonnull fence.

clock_revision remains a required natural string naming the latest accepted retained lifecycle clock for permit.clock_source. There is no nullable revision. A retained AVAILABLE clock is `{source,revision,status:"AVAILABLE",observed_time,evidence_digest}` and binds authority.clock `{source,status:"AVAILABLE",instant:observed_time}`. A retained UNAVAILABLE clock is `{source,revision,status:"UNAVAILABLE",observed_time:null,evidence_digest}` and binds authority.clock `{source,status:"UNAVAILABLE",instant:null}`. Unknown, missing, nonlatest, wrongly sourced or temporally regressed selection is CLOCK_INVALID. A matching unavailable clock produces ordinary CLOCK_UNAVAILABLE withholding before unresolved CLOCK queries; it cannot fall back to an old available clock. A retained CONFLICTING clock cannot be represented as an equal authority clock in this slice and refuses CLOCK_INVALID, with no fallback or send. For success, checked_at is the selected available instant and is no earlier than permit issuance. observation_digests is the sorted unique digest("authority-observation",row) set of the admitted fresh DISPATCH observation inventory after exact duplicate collapse, including ordinary revocation evidence.

For the `approval_requirement` gate form, expiry is exclusive:

```text
expires_at = min(permit.expires_at,
                 nonnull fixed authority-envelope valid_until,
                 checked_at + dispatch_gate.authorization_seconds)
```

For `SOURCE_REQUIREMENTS`, LIFE-009B defines the complete expiry, including selected validity and leaf ends; the three-term approval formula does not replace it. Overflow is LIMIT_EXCEEDED. A permit already expired at the selected available clock, superseded, consumed, terminal or otherwise ineligible cannot obtain a new authorization: PREREQUISITE_MISSING. Current authority is evaluated under existing phases and current reliance checks. A well-formed policy withholding precedes any comparison against a derived fence. It creates no authorization, performs no reservation and permits no connector call. Its admitted evaluation consumes the unique intent identifier; a later authorization attempt requires a fresh identifier.

A source row has exactly:

```text
{requirement_id, provider, source, expected_status, record_id,
 provider_revision, query_digest, observation_digest}
```

Derive one row for every gate requirement, no addition or omission, sorted uniquely by requirement_id. Coordinates and expected status come from the declaration; revision, query digest and observation digest come from its single admitted matching fresh observation. AVAILABLE uses provider_record_id as record_id; complete ABSENT uses null. A row cannot be manufactured from caller EFFECTIVE or a copied status string.

For the `approval_requirement` gate form, the gated authorization_fence retains exactly:

```text
{provider, source, approval_id, scope_digest, approver_role, signed_at,
 provider_revision, checked_at, status, sources}
```

provider/source equal dispatch_gate.fence_provider/source. approval_id is the AVAILABLE approval provider_record_id; provider_revision is that approval observation's revision. These are approval metadata, not a substitute for sources. approver_role/signed_at equal the independently admitted selected GRANT's role/occurred_at. The source's declared relations establish the grant, record and native approval bindings; the consumer does not infer them from similar spelling. For this `approval_requirement` fence, success derives status EFFECTIVE. Existing WITHDRAWN/EXPIRED/MISMATCHED spellings may remain transport-admissible, but none creates a successful fence inconsistent with current evidence. For `SOURCE_REQUIREMENTS`, LIFE-009B supplies its coordinator fence fields and statuses, including UNKNOWN; it does not inherit the approval identifier, approver role or signed-at fields. The common event, source-row, scope-digest, immutable-basis, evaluation, intent and receipt rules in this section still apply.

Derive scope_digest as digest("dispatch-authorization-scope", this complete body):

```text
{instance_id, occurrence_id, permit_digest, native_request, connector,
 dispatch_intent_id, checked_at, expires_at, authority_result_digest, sources}
```

After current authority succeeds, a null submitted fence is BINDING_MISMATCH and a nonnull submitted fence must equal the independently derived complete fence. Any mismatch is BINDING_MISMATCH. Structurally malformed nonnull submitted fences remain earlier refusals. A fresh authority failure is retained before derived-fence comparison, so null needs no invented metadata and an obsolete EFFECTIVE assertion cannot override withdrawal, expiry, unavailable evidence or failed relations. Successful authorization records always retain the complete nonnull derived fence.

A successful authorization record has exactly:

```text
{authorization_digest, event_id, event_digest, permit_digest, native_request,
 connector, authorization_fence, observation_digests, clock_revision,
 dispatch_intent_id, authority_input, authority_result, authority_result_digest,
 expires_at, supersedes_authorization_digest}
```

event_digest uses runtime-event; authority_result is the newly recomputed complete readiness result and authority_result_digest uses authority-result. authorization_digest uses dispatch-authorization over the full record with that digest omitted. supersedes_authorization_digest is null for the permit's first record, otherwise the exact current head's digest derived from retained state. No caller-selected predecessor or unbound field can change it. Retain records sorted by authorization digest; determine the head by the acyclic predecessor chain, never array position or digest spelling. One new committed record supersedes its predecessor without deleting history.

Success records AUTHORIZED with empty reasons, one AUTHORIZATION detail and unchanged occurrence/permit/registry state apart from the authorization, retained evaluation and ordinary receipt/replay/log transition. For the `approval_requirement` gate form, the new AUTHORIZATION detail is exactly `{kind:"AUTHORIZATION",authorization_digest,permit_digest,approval_id,checked_at,expires_at,sources}`; the vector replaces its incomplete singular revision summary. For `SOURCE_REQUIREMENTS`, LIFE-009B defines the alternative detail with `gate_kind` and no approval identifier. Policy withholding records WITHHELD, leaves the occurrence PERMITTED and the previous authorization head unchanged, and uses the existing complete AUTHORITY refusal detail. Its reasons are the sorted union of AUTHORITY_REQUIRED, the authority refusal code and its reasons.

Deployment of a definition with any dispatch_gate initializes authorizations and authorization_evaluations as empty arrays. Add optional state.authorization_evaluations, an array of at most 128 records sorted uniquely by event_id. Omission means no evaluations for inherited state; it is not allowed to omit an admitted gated evaluation. Every admitted gated AUTHORIZE_DISPATCH, successful or withheld, appends exactly:

```text
{evaluation_digest, event_id, event_digest, permit_digest, dispatch_intent_id, clock_revision,
 authority_input, authority_result, authority_result_digest,
 authorization_digest, disposition}
```

authority_result is the full readiness result or full authority refusal; its digest uses authority-result in either case. AUTHORIZED has the exact nonnull successful authorization_digest; WITHHELD has null and creates no successful authorization record. evaluation_digest is digest("dispatch-authorization-evaluation",the full evaluation record with evaluation_digest omitted). Add optional decision-receipt member authorization_evaluation_digest, required on both admitted gated outcomes and absent on ungated outcomes; it equals the retained evaluation_digest. The existing receipt authority_result_digest equals the fresh authority-result digest on both gated AUTHORIZED and WITHHELD outcomes. Ungated authorization retains null for that receipt member. Declared referral evidence binds this same evaluation digest. Admission refusals append neither evaluation nor authorization and consume no intent identifier. At the 128-record ceiling, refuse LIMIT_EXCEEDED without discarding earlier evidence.

Restart checks each evaluation's digest, event/permit/unique-intent bindings, selected accepted clock, full immutable basis comparison, recomputed point-selected result/digest and exact success/null binding to the corresponding authorization and receipt. It uses the retained evaluation clock, not a later current clock, to reproduce the historical judgment. An unavailable-clock evaluation reproduces CLOCK_UNAVAILABLE with no authorization. The host also retains the full canonical accepted request/response in its protected audit log; that external log is not a substitute for the portable evaluation record.

## 7. Send eligibility, supersession and consumption

A later admitted WITHHELD evaluation prevents an older retained successful head from authorizing a new send, although that head remains in history. New send eligibility requires the latest admitted gated evaluation for that permit to be AUTHORIZED and to bind the selected head. The host gated dispatch API receives an explicit retained authorization reference. It verifies the current head, exact permit/request/connector, accepted clock and exclusive expiry; durably claims `{instance_id,dispatch_intent_id}` before connector invocation. Each intent permits at most one attempt. A record is authorization evidence, not proof that the call happened. Safe NOT_SENT with no accepted acknowledgement leaves the permit eligible only for a fresh unique authorization under current checks. Reusing the old intent, including replaying its request after a crash, never invokes again.

The host treats an unresolved prior intent claim as may-have-sent. When the selected completion carrier declares lookup, the host uses that exact authoritative lookup to investigate the claimed attempt. Otherwise no provider lookup is implied; the intent and permit remain blocked until authenticated source-selected investigation establishes a safe NOT_SENT observation or an applicable recovery disposition resolves the cause. The host cannot recreate send permission by replaying AUTHORIZED or choosing a fresh intent while that attempt remains unresolved. Claim recovery and a conservative dispatch observation must precede any further send for the same permit; a lookup or disposition does not by itself restore consumed permission. No CLAIM_DISPATCH runtime event is added in this slice. AUTHORIZED alone does not prove durable invocation safety. A reference host can establish its exercised single-process claim/commit behavior; real durability, distributed coordination and crash recovery remain explicit host premises.

REJECTED, SENT or UNKNOWN attempt, accepted acknowledgement, native effect evidence or a decisive completion lookup consumes dispatch permission. A new authorization cannot override any of that retained history. Expiry and supersession also make the old authorization ineligible. A new authorization may replace an unattempted head or follow safe NOT_SENT, provided the original permit remains eligible; it does not extend that permit.

For a declared gated step, DISPATCH_OBSERVED reports the authorization_digest actually claimed. An omitted, unknown or mismatched claim is retained only as a prohibited attempt under the rule below; it never makes the send eligible. For an authorized attempt, the selected retained record must be the head, bind the exact request/connector/permit, and be timely at attempted_at. For a later-received observation, an older authorization remains historically eligible only when attempted_at is strictly before every later authorization or withheld evaluation's selected available clock instant. Equal timestamps fail conservatively because whole-second evidence does not establish ordering. A later unavailable evaluation blocks new host sends but does not by itself prove that an earlier available-clock attempt was unauthorized; the retained chronological event and attempt bindings still apply. An observation received after expiry still retains a timely past attempt under LIFE-009. Exact event replay and the existing byte-identical acknowledgement-update path observe the same physical attempt; they never create another call. Changed request/connector/attempt under an acknowledgement update is BINDING_MISMATCH, and an unchanged or already conclusive acknowledgement is PREREQUISITE_MISSING.

A prohibited attempt is retained conservatively once it is attributable to the admitted permit and exact observed request/connector. Missing, unknown, stale, superseded, expired or already-attempted authorization adds LATE_OR_PROHIBITED_DISPATCH; existing native argument, permit-expiry and acknowledgement reasons remain applicable. Its supplied authorization digest is an observed claim, allowed to remain unresolved or mismatched only on such a prohibited row. It never establishes a usable authorization or head.

SENT/UNKNOWN or accepted acknowledgement with an authorization failure is DISPUTED. Safe NOT_SENT without accepted acknowledgement, including stale authorization, is DISPATCH_REFUSED and records NATIVE_NOT_SENT plus applicable prohibition reasons. Connector REJECTED follows LIFE-009's retained refusal/dispute distinction and consumes permission; it is not proof of no remote effect. Terminal or completed work never reopens. These observations do not settle keys or invoke the connector.

The ungated API and old single-provider carrier remain available for a selected operation step that explicitly omits `dispatch_gate` within a definition that has the complete accepted correspondence, source-confirmation, policy-decision and organizational-authorization evidence required by LIFE-003. The confirmed source and accepted policy decisions must permit the finite proposal-authority snapshot rule in LIFE-008. Such a step may occur in a newly authored or inherited definition. Determining that the source permits this rule is a documentary correspondence and source-approval obligation; accepted evidence status alone does not establish that meaning. An ungated step cannot satisfy a source requirement for the dispatch refresh or native commitment guarantees supplied by a dispatch gate, including an equipment gate. A step selecting `dispatch_gate` retains every requirement of that gate and cannot fall back to the ungated path. Gated permits and evaluations retain the complete basis, refreshed input and unique intent; successful authorization records additionally retain expiry and the complete sources vector. A submitted null gated fence permits only policy withholding, never successful authorization. No missing carrier defaults to the ungated path. Old-pin states and active permits have no automatic migration.

## 8. Admission codes and precedence

Use AUTHORITY-CHECKS phases and within-phase order unchanged, adding the source checks at their declared phase. Phase 1 covers closed shape, canonical bytes, complete scalar/calendar admission and duplicate/sort declaration errors. Phase 2 covers exact pin/digest bodies, references, unsupported selectors/relations, source providers and semantic bounds. Phase 3 covers exact application field/scope/executor binding. Phase 4 independently selects and admits acts/returns. Phase 5 first resolves the complete source and revocation query inventory (DEPENDENCY_MISMATCH before EVIDENCE_UNAVAILABLE), then collects current policy failures. Only AUTHORITY_NOT_ESTABLISHED emits reasons/failed checks; unavailable current clock keeps its special empty failed-check result.

AUTHORIZE_DISPATCH applies: protocol/schema; definition/state identity and restart invariants; exact event replay; instance/permit/request/connector and immutable-basis binding; unique intent and eligibility; current lifecycle clock binding; refreshed authority phases; source vector and full derived-fence equality; atomic authorization/receipt/replay commit. Wrong immutable basis is BINDING_MISMATCH. A missing gated authority_basis in admitted state is STATE_INVALID; missing required refreshed input is EVIDENCE_UNAVAILABLE; missing intent is INPUT_INVALID. Wrong current clock is CLOCK_INVALID. Consumed/superseded/expired/terminal permit is PREREQUISITE_MISSING. Fence comparison cannot turn a well-formed current policy failure into an admission refusal or readiness result.

Lifecycle maps existing authority admission codes to unchanged-state refusals and existing authority policy codes to admitted WITHHELD exactly as LIFE-007 does. Authorization success and withholding do not increment proposal or actuation counters and do not run another reservation transition. All arithmetic is exact. A failed expected-revision or durable commit leaves authoritative roots and event log unchanged and permits no connector invocation.

## 9. Provider and host boundary

The host authenticates identities, remits, signatures, current and historical facts, query coverage, revisions and clocks. It durably stores every `authority_basis` and refreshed authority input required by the selected step and profile, protects detailed refusals and original authorization/attempt records, and serializes intent claims and lifecycle/registry/receipt/referral/request-response roots at expected revisions. The connector remains outside that local transaction.

For the `approval_requirement` gate, at native write commitment the declared coordinator/provider must atomically validate every sources row against the corresponding authoritative provider/source revision and expected AVAILABLE/ABSENT state, enforce approval effectiveness, policy withdrawal and authorization expiry, and enforce any tuple uniqueness required by the source. No earlier digest, recent check, polling interval or singular approval revision substitutes for the complete conditional-write guarantee. Unavailable or uncheckable blocking sources mean no conforming send. A change ordered before commit rejects the write; one after commit preserves the earlier event and follows separate source-selected duties. Prevention of unfenced external writers is an explicit host premise.

The four equipment blocking authority sources form the provider fence. Other refreshed facts establish what was true at checked_at; this carrier does not claim that unlisted records remain unchanged until commit. A source requiring more atomic guards must declare the corresponding contract need. Authentic coordination among real systems, process-crash recovery after the intent claim, lookup reconciliation and external-writer exclusion require separate qualification. Synthetic provider traces establish only apparatus behavior. No unknown response establishes rollback, absence of an effect or permission to retry.
