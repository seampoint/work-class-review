# Exact-content assessments and attributable human review

Status: `DRAFT_NOT_ADOPTED`, `APPARATUS_ONLY`. This normative companion defines one bounded assessment and human-review profile using existing execution authority, independent HUMAN evidence and source-vector commitment. Omitted new members retain inherited rules and bytes. A model judgment grants no authority.

## ASSESS-001. Closed declarations, complete obligations and supporting bodies

Ordinary envelopes gain optional `assessment_requirements`, an array of zero or one rows. Ordinary inputs gain optional `assessment_bases`, an array of zero or one rows. Omission and explicit empty remain distinct canonical bytes. The selected proposal step requires its one declared basis. Another step may not supply that basis. There is no assessment collection inside an evidence-only human leaf.

The assessment requirement is exactly:

```text
{id,step,review_decision_requirement_id,rubric,evaluator,sources}

rubric = {id,revision,obligations,criteria}
criterion = {id,obligation_ids,citation_policy}
citation_policy = "CONTEXT" | "PROPOSAL" | "ANY"
evaluator = {provider,model,version}

sources = {
  content,
  context,
  context_selection:{requirement_id,digest_field},
  rubric:{requirement_id,digest_field},
  evaluator:{requirement_id,provider_field,model_field,version_field},
  assessment:{requirement_id,digest_field},
  selection:{requirement_id,identity_field,digest_field},
  effectiveness:{requirement_id,identity_field,effective_field},
  blockers
}
```

`content` is one source requirement id; `context` and `blockers` are sorted unique source requirement id arrays. Every role resolves to the same operation step. Rubric obligations are complete `{id,text}` rows, sorted uniquely by id, each exactly equal to its corresponding `authority.source.obligations` row. Each criterion's nonempty sorted unique `obligation_ids` resolves within that rubric inventory. Their union equals the rubric obligation inventory, so no selected obligation is silently unassessed. Every selected row and its exact text enters the full rubric digest. No source text is inferred from the criterion name or evaluator. Other source obligations, including independently enforced prohibitions, remain governed by their existing checks. Mapping criteria to the intended source obligations remains source correspondence work.

Optional-member admission is exact. With no declaration selected for the proposed step, omitted or explicit-empty bases are admitted and no assessment policy check is emitted; a nonempty basis refuses DEPENDENCY_MISMATCH. With a declaration selected, omitted or empty bases refuse EVIDENCE_UNAVAILABLE. A supplied basis must name that exact declaration. Explicit-empty collections are never normalized to omission. The declaration collection may be omitted or empty; a nonempty collection contains one declaration. All ordinary unrelated authority checks still apply.

The supplied basis is exactly:

```text
{requirement_id,supporting_context,assessment,review}

snapshot = {requirement_id,provider_record_id,provider_revision,fields}
assessment = {
  provider,source,record_type,id,revision,
  subject_digest,context_digest,rubric_digest,evaluator,
  assessed_at,criteria
}
assessment_criterion = {
  id,verdict,explanation,escalation,citations
}
verdict = "PASS" | "FAIL" | "UNCERTAIN"
escalation = {required,reason}

review = {id,assessment_digest,decision,criteria}
decision = "APPROVE" | "REJECT"
review_criterion = {id,disposition,reason,citations}
disposition = "SATISFIED" | "NOT_SATISFIED" | "UNRESOLVED"
```

`fields` is the existing complete sorted named typed field array. `supporting_context` contains exactly the declared `sources.context` set, sorted by requirement id. A snapshot's names and nominal types equal that source requirement's complete field declarations; every scalar validates under the outer work-class types. Provider/source/record-type coordinates come from that pinned requirement, rather than another caller-controlled copy. The assessment's provider/source/record_type equal its declared assessment source coordinates. Its `id` is the immutable provider record identity and `revision` the exact opaque issuance revision. They are not chosen by timestamp order.

Rubric, assessment and review criterion arrays sort uniquely by id and have exactly the same id inventory. Each model explanation is nonempty. `escalation.required` is boolean; its reason is nonempty exactly when required is true, otherwise null. Human reason is null or nonempty. It must be nonempty when the matching model verdict is not PASS, model escalation is required, or the human disposition is not SATISFIED. An unflagged PASS/SATISFIED may carry a reason but need not. Mandatory overall human routing does not imply criterion escalation.

Use one to 32 criteria and rubric obligations, one to 32 obligation ids per criterion, zero to 64 context snapshots and zero to 64 blocker references. Model citation arrays contain one to 32 entries; human citation arrays contain zero to 32. Obligation text, explanation and reason strings contain one to 8,192 Unicode code points; all identifiers retain inherited id bounds. The complete assessment-bearing authority input remains at most 1,048,576 canonical bytes; human inputs remain at most 262,144. Source and relation bounds still apply to the complete step, so 64 context rows do not imply room for 64 additional role sources. Schema maxima retain SCHEMA_INVALID; canonical-byte ceilings retain phase-2 LIMIT_EXCEEDED.

## ASSESS-002. Exact criterion judgments and scalar citations

Each citation is one of these two closed objects:

```text
{kind:"PROPOSAL_FIELD",field}
{kind:"CONTEXT_FIELD",requirement_id,field}
```

The first resolves one complete exact native proposal scalar. The second resolves one complete scalar in a supplied selected snapshot, including that snapshot's exact provider identity/revision. These are the entire supported locators. No offsets, external URL, raw MIME or implicit document parser is admitted. Citations sort uniquely by complete canonical bytes. Every model citation must meet its criterion's policy: CONTEXT permits context citations, PROPOSAL permits proposal citations and ANY permits either. Human citations, when present, may use either admitted kind. Correct references prove neither factual support nor model reasoning quality.

A real connector with additional hidden or rendered content needs a different complete native request contract before this profile can cover those bytes.

## ASSESS-003. Complete canonical assessment identities

The following objects contain only admitted bodies and existing proposal/declaration coordinates. The context domain's `types` array is the outer authority work class's complete type declaration inventory, sorted by id. This conservative choice binds nominal meanings without adding a second type projection rule. The existing work_class_digest is available before assessment/human construction because assessment declarations live in the envelope, not the work-class projection. No completed outer envelope, root, proposal, operation or future human digest enters these preimages. First-profile unsupported mixed correction carriers cannot create an indirect leaf reference through the work class.

```text
context_body = {
  types,
  records:[{
    requirement_id,provider,source,record_type,
    provider_record_id,provider_revision,fields
  }]
}
context_digest = digest("content-assessment-context",context_body)

rubric_digest = digest("content-assessment-rubric",declaration.rubric)

subject_body = {
  principal:proposal.executor.principal,
  work_class_digest:proposal.work_class_digest,
  instance:proposal.instance,
  occurrence:proposal.occurrence,
  step:proposal.step,
  interface:proposal.interface,
  operation:proposal.operation,
  fields:proposal.fields,
  context_digest,rubric_digest,evaluator:declaration.evaluator
}
subject_digest = digest("content-assessment-subject",subject_body)
assessment_digest = digest("content-assessment",basis.assessment)
review_digest = digest("content-assessment-review",basis.review)
```

Context records sort by requirement id; each record's provider/source/type comes from that exact source declaration. Rubric obligation rows sort by id. All native fields are included, unchanged, with their exact nominal typed values, and the existing exact work-class digest fixes their nominal declarations. Ordinary application admission independently establishes principal, operation/interface, complete field inventory, instance and occurrence. Lifecycle binds the same proposal fields to the connector request. In standalone evaluation, those coordinates remain claims under the ordinary input contract; evaluation grants no native effect.

Recompute every digest. The assessment's subject/context/rubric digests equal the computed values and its evaluator equals the complete selected evaluator object exactly. The review's assessment_digest equals the full computed assessment digest. The assessment body has no self digest. The review body has no self digest, human act digest, return, approval-source wrapper or future event. Its `id` is preallocated before signing. One-way construction is native content/context and rubric/evaluator, assessment, review, human signing, outer evidence. A model rerun creates a separate immutable assessment issuance even if the result bytes agree.

Text values retain the exact admitted scalar, with no Unicode, whitespace or line-ending normalization. Canonical JSON escaping is transport serialization. The synthetic sink consumes those exact native strings and zero attachments. Arbitrary rendered bytes and generation configuration are outside this profile.

## ASSESS-004. Authentic human review and reusable issuance binding

The requirement's review_decision_requirement_id equals outer `gate.decision_requirement`; gate kind is DECIDE. It names the exact same-step HUMAN requirement admitted under AUTH-008/009. There is at most one assessment declaration total, so no sibling leaf or shared-review ambiguity arises. Other independent decisions may still supply their own ordinary evidence.

That human requirement has exactly one binding of each following member, all pointing to this assessment requirement:

```text
{kind:"ASSESSMENT",requirement_id,member,type_ref}
member = "SUBJECT_DIGEST" | "ASSESSMENT_DIGEST" |
         "REVIEW_DIGEST" | "REVIEW_IDENTITY"
```

No literal or proposal-field copy substitutes for these four bindings. Existing remaining context fields, including validity endpoints, continue using their ordinary exhaustive bindings. Each derived type is STRING/IDENTITY and has the same complete nominal declaration in outer and leaf classes. `identity_field` is precisely the leaf field bound by REVIEW_IDENTITY. The other three values are the recomputed digests above. The fourth is the canonical JSON string of:

```text
{provider:<approval requirement.provider>,
 source:<approval requirement.source>,
 record_type:<approval requirement.record_type>,
 provider_record_id:review.id}
```

Require review.id to equal the unique selected human INSTANCE_DECISION act id. Phase 3 can compare directly present id coordinates; phase 4 must still authenticate and admit that actual act and its attributable return. The ordinary act disposition must remain ACCEPT; an actual rejected act retains ACT_NOT_ACCEPTED. A valid ACCEPT act may attest to a review body whose business decision is REJECT, which then withholds by the assessment policy. Do not convert an actual rejected act into accepted evidence.

Only this precisely assessment-linked approval source may declare `record_id:null`. This profile requires that null form and the exact returned identity checks below. Its mandatory AUTH-008 `OBSERVATION_ID == DECISION_ACT.id` and complete act/context field coverage remain unchanged. The returned record must therefore have exactly review.id. Ordinary decisions retain their nonnull record_id rule. Existing native message/case keys or fixed subjects locate current approval records; no computed query key or generic SELF selector is introduced.

ASSESSMENT values are permitted only in outer independent-human context bindings. They cannot occur inside a leaf, refer to another assessment, enter generic queries or relations, or recurse. A selected leaf gate predicate using any of these four bound fields refuses UNSUPPORTED_RELATION before translation. Native-field and literal predicate translations remain unchanged. A correction policy cannot gain support for these computed values through schema reuse without its own explicit selected mapping; mixed correction use refuses UNSUPPORTED_RELATION statically in this profile. A correction authority input with nonempty assessment requirements, nonempty assessment bases or a computed ASSESSMENT selector also refuses UNSUPPORTED_RELATION. Explicit-empty collections retain ordinary correction behavior. This restriction does not prohibit assessment-bearing original business evidence retained by a separately supported correction procedure.

## ASSESS-005. Current dependencies, admission and exact enforcement

All singular role sources and every supporting context source expect AVAILABLE. Singular role ids, context ids and the selected approval id are pairwise distinct; blocker ids are disjoint from them. Every same-step outer source requirement belongs to the selected SOURCE_REQUIREMENTS fence and uses its required current-source profile. The existing combined source/holdings bound remains 64. Supporting-context relations may use local field strings, PROPOSAL_FIELD, LITERAL, EXECUTOR and CLOCK, and OBSERVATION_FIELD/OBSERVATION_ID targeting selected context sources. Content relations admit the same non-act selectors, with observation targets limited to its own record or selected context sources. ACT and all DECISION selectors are forbidden in both predecision roles. These syntactic restrictions cannot establish when a provider actually produced a field or detect an opaque copied future identifier. These restrictions preserve the one-way body construction. All selected role sources, the approval source, every blocker and the selected coordinator belong to the step's SOURCE_REQUIREMENTS fence. Each uses CLOCK, zero freshness and explicit PROPOSE_AND_DISPATCH. Blockers use their existing declared AVAILABLE/ABSENT policies and independently evaluated relations. The gate can contain additional source-selected current conditions. Every map field resolves statically to a declared in-step field; hash/identity/text fields use declared STRING/IDENTITY types. Selection identity/digest field names are distinct. Evaluator provider/model/version field names are distinct. Effectiveness identity/effective fields are distinct, the latter is BOOLEAN, and the effectiveness requirement is distinct from both immutable issuance and current selection.

| Role | Required local/current equality |
| --- | --- |
| content | Complete source field declaration inventory equals the native field declaration inventory, using the same names and types. For every field, require an explicit EQUALS relation from that source's OBSERVATION_FIELD to the same PROPOSAL_FIELD. |
| context | Current provider_record_id, revision and complete fields equal the retained snapshot. Compare current fields as a named typed inventory, independent of array order; retained snapshot fields remain sorted. Immutable provider/source/type are supplied by the named source declaration. No as_of/query wrapper enters context_digest. |
| context_selection | Named digest_field equals recomputed context_digest. |
| rubric | Named digest_field equals recomputed rubric_digest, including complete selected obligation text. |
| evaluator | Named provider/model/version fields equal the exact declaration values. |
| assessment | Current metadata equals assessment.provider/source/record_type/id/revision; named digest_field equals assessment_digest. Require a direct EQUALS relation from that OBSERVATION_FIELD to the ASSESSMENT_DIGEST-bound DECISION_FIELD. |
| selection | Named identity_field equals canonical `{provider,source,record_type,provider_record_id}` for this assessment issuance; named digest_field equals assessment_digest. Require the same direct digest-to-DECISION_FIELD relation. |
| effectiveness | Named identity_field equals that same canonical assessment issuance identity, and named effective_field is exactly true. This is a separately current assertion, independent of unchanged selection. |
| human approval | Retain every AUTH-008 act and exhaustive context equality, including the four computed fields, validity endpoints and exact OBSERVATION_ID/act id equality. |
| blockers | Existing independently enforced conditions pass. A criterion reason cannot waive them. |

The helper compares local recomputed values to the named typed source fields; no new generic selector is needed for context/rubric/evaluator/selection/effectiveness identity. Existing source subject and key_projection select by native message/case fields. No record reference fetches absent evidence. Immutable assessment issuance metadata never changes to express withdrawal; the separately fenced effectiveness assertion changes instead. Current selection cannot override false effectiveness. Source correspondence must name human approval withdrawal/current-reliance and contact rules among the complete blockers/guards, plus every writer participating in the coordinator. Matching revisions cannot prove provider authentication, completeness, truthful current selection, nonrollback or all-writer participation.

### Admission and current policy

1. Phase 1 checks original closed shape/scalars/calendars, sorted/duplicate arrays and local escalation reason consistency. Explanation/model citation minima are schema constraints. Criterion-dependent human reason and citation-policy checks wait until phase 3, after all criterion/reference inventories are admitted.
2. Phase 2 checks the exact selected basis/context/criterion inventories, declaration maps, source coverage, the narrow null-record exception, nonrecursive profile and unsupported predicates/combinations. Missing selected bodies, snapshots or criteria are EVIDENCE_UNAVAILABLE; extra unrequested bases or context snapshots are DEPENDENCY_MISMATCH; extra or unknown criterion/citation references are REFERENCE_INVALID; duplicate/order faults remain phase-1 INPUT_INVALID. Preserve inherited extra-base/pin/reference and within-phase precedence. Static definition/readback checks do not require runtime bodies.
3. Phase 3 checks local body/subject/dependency digests, review id coordinates, native applications, complete nominal bridges, criterion-dependent human reasons and matching model citation-policy compliance. Directly known incompatible snapshot field nominal declarations and human nominal bridges retain phase-1 TYPE_INVALID; unresolved references retain phase-2 REFERENCE_INVALID. A contradictory local computed application, absent required human reason or wrong known criterion citation policy is BINDING_MISMATCH.
4. After all outer/leaf phase-4 act admission, require assessed_at no later than the authenticated selected human occurred_at, otherwise BINDING_MISMATCH. This runs before the special unavailable-clock result. Ordinary act admission already prevents an admitted signer time after available now, so a separate ASSESSMENT_POSTDATED policy is unnecessary.
5. After exact outer/leaf query inventory and ordinary source usability/status admission, compare the complete role maps and snapshot values against usable single AVAILABLE records with admitted fields. A usable row has one exact-query AVAILABLE record with correct expected identity, time/freshness, complete correctly typed fields, exact declared relation inventory and a satisfied declared source validity interval. A declared relation evaluating false does not suppress a concrete profile-map comparison: SOURCE_OBSERVATION_RELATIONS and ASSESSMENT_DEPENDENCY_CHANGED may both occur. An unavailable, conflicting or structurally unusable group supplies no profile value and contributes its inherited source reason, not a duplicate dependency-change reason. A usable contradictory current role value contributes ASSESSMENT_DEPENDENCY_CHANGED. Review decision REJECT or any nonsatisfied/unresolved human criterion contributes ASSESSMENT_NOT_SATISFIED. Both produce AUTHORITY_NOT_ESTABLISHED and union with independent ordinary/human/source failures.

The following cases fix refusal precedence within the inherited phases. An unknown assessment target defers the narrow null-record and four-member coverage checks, so those consequences do not replace REFERENCE_INVALID with UNSUPPORTED_RELATION. Ordinary human requirements without computed selectors retain their inherited nonnull-record rule.

| Condition | Phase and result |
| --- | --- |
| Impossible raw assessed_at calendar; locally inconsistent escalation reason | Phase 1 INPUT_INVALID |
| Invalid typed snapshot INSTANT; known incompatible snapshot, content or derived-selector nominal declaration | Phase 1 TYPE_INVALID |
| Unknown assessment target, derived type, rubric obligation or native content field reference | Phase 2 REFERENCE_INVALID |
| Known missing/copied/repeated computed member coverage, computed selector on another human requirement, overlapping role/context/approval/blocker ids, or one selection field used for both identity and digest | Phase 2 UNSUPPORTED_RELATION |
| Known rubric obligation text differs from its source row | Phase 2 DEPENDENCY_MISMATCH |
| A rubric obligation has no criterion mapping | Phase 2 REFERENCE_INVALID |
| Missing selected basis, snapshot, criterion or snapshot field | Phase 2 EVIDENCE_UNAVAILABLE |
| Extra unrequested basis or snapshot | Phase 2 DEPENDENCY_MISMATCH |
| Extra snapshot field or unknown criterion/citation reference | Phase 2 REFERENCE_INVALID |
| Missing criterion-dependent human reason or a resolved model citation violates its criterion policy | Phase 3 BINDING_MISMATCH |

Duplicate binding field names retain phase-1 INPUT_INVALID, independently of computed-member coverage. A declared validity interval failure makes its current source row unusable for the assessment map and retains SOURCE_OBSERVATION_TIME. A usable content-value mismatch may contribute both SOURCE_OBSERVATION_RELATIONS and ASSESSMENT_DEPENDENCY_CHANGED. No structurally unusable row supplies a value for comparison.

Use exactly one check per selected requirement: `{purpose:"ASSESSMENT",subject_digest:<assessment_digest>,requirement_ref:<requirement id>,at:<accepted now>}`. Its failed check carries the applicable new policy reason. Human/source checks remain independent. There is no assessment readiness status and no model result grants authority.

## ASSESS-006. Complete retention, replay and coordinated commitment

Include supplied assessment_bases in the authority-evidence preimage if and only if present. All complete bodies and optional-member presence remain immutable between proposal and dispatch; only existing clocks, observations, evaluation point and allowed holdings refresh can change. A changed subject, rubric/evaluator, selected assessment, review or human act needs a new chain and proposal. Current change before commitment blocks conditional acceptance; change after commitment preserves historical decisions/effects. Existing expiry clipping, pending/uncertain intent custody and no blind reinvocation remain intact.

Retained reservations, permits, authorizations, proposal evaluations and separation details reconstruct the complete original authority input at its retained clock without rerunning a model. Real immutable issuance storage, all assessment attempts, actual reviewer presentation, provider authentication/current truth, exact connector mediation, coordinated writers and durable recovery remain host/provider premises. This adds no operation, ledger, pruning rule or automatic assessment TTL.


The authority-evidence preimage retains every inherited member and adds exactly assessment_bases when that input member was supplied, including explicit []. This rule applies to the central authority result and every manual retained-permit evidence reconstruction. Complete input clones in reservation events, permits, proposal evaluations, dispatch authorizations/evaluations, separation details, replay and restart preserve those bodies and optional-member presence. A proposal that supplies assessment_bases, including [], retains its complete authority_basis in its permit and in a withheld SEPARATION detail. These carriers reconstruct the original input and complete result even when decision_results is omitted or empty; ordinary omission preserves inherited carriers. No redundant assessment result carrier is added. A successful assessment check cannot substitute for the complete retained basis. The required independent decision and source gate also retain their inherited complete-basis reconstruction duties.

The source correspondence enumerates every participating message-content, supporting-evidence/context-selection, rubric/coverage, evaluator-selection, immutable assessment issuance, assessment effectiveness/withdrawal, current selection, human review/approval/withdrawal, authenticated identity/remit and root/capacity/envelope/return-channel revocation writer, plus independent blockers and native acceptance. Current source observations authenticate no writer participation by themselves. The host orders these writers with current checks, intent retention and controlled acceptance. A relevant change before commitment blocks that authorization; a change after commitment preserves its historical evidence and established effect. Pending or uncertain invocation retains its original intent and existing coordination without blind reinvocation. Both synchronous and deferred acceptance retain that boundary until acceptance settles.

All complete content, context, criteria, dispositions, reviewer identities, source records and detailed refusals use the existing protected internal audit boundary. Public closed status/digest carriers grant no access to those bodies. The provider retains actual immutable issuances and prior attempts; standalone exact matching cannot detect an unreported competing record, global identity reuse, rollback or false provider assertions. Reconstruction checks retained complete bodies and semantic links; a protected checkpoint and authentic provider records remain premises. Resealing attacker-authored claims does not establish their authenticity.

Mechanical enforcement establishes exact declared relationships and attributable recorded conclusions. It does not prove semantic accuracy, citation relevance, actual reviewer presentation or understanding, model reliability, lawful disclosure, information-flow propagation, exact external rendering, durable storage or external-writer coverage. No model API, automatic threshold, new runtime operation, pruning policy or assessment lifetime is defined.
