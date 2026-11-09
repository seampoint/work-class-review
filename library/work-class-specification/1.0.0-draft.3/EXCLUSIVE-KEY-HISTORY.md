# Exclusive-key history

Normative draft 3 contract. Status: `DRAFT_NOT_ADOPTED`; claim ceiling: `APPARATUS_ONLY`. Bundled schemas govern closed shape admission. The rules below govern semantic admission, deterministic decisions and retained evidence. Provider truth, durable coordination and source fidelity require separate evidence.

## 1. Closed profile and per-slot guarantees

Every shape below is closed. Listed members are required unless explicitly optional. Identifiers, digests, whole-second UTC instants, natural strings, nominal scalar types, typed values `{type_ref,value}` and named typed fields `{name,value}` use the existing bundled ABI. No JSON numbers, unknown fields, type coercion or ambient history reads are admitted.

A new-profile exclusive slot has exactly:

```text
{slot, namespace, authorized_classes, retention, permit_seconds,
 key_shape, types, history_record_fields, history_projection, uniqueness}
```

The five inherited members retain their existing meaning. `key_shape` is an ordered nonempty array of at most 64 `{name,type_ref}` rows with unique names. Its declared order is the canonical positional key order; a caller cannot reorder it. `types` is a raw-UTF-8-sorted unique inventory of at most 64 complete supported scalar declarations, including every referenced nominal type. Type identifiers and complete declarations must agree with every admitted work-class projection. A different type name or declaration cannot establish an alias for the same business identity.

`history_record_fields` is exactly `{held,consumed}`, each a raw-UTF-8-name-sorted unique array of at most 64 `{name,type_ref}` declarations. Each inventory declares the complete normalized native field set for that historical record state. Distinct inventories allow an unresolved attempt to lack generated completion fields. They do not authorize fabricated completion metadata. Every field used by a NATIVE_FIELD history projection occurs in both inventories with the exact same nominal type. Metadata outside native_fields is fixed by the record carrier below; undeclared provider metadata is not silently dropped. The host must retain the underlying provider record and the selected complete normalization evidence.

`history_projection` contains exactly one row for every key_shape position. Each row's `key_field` equals that position's name, and its selected nominal type equals the position's type_ref. Rows do not sort independently of key_shape. The closed selector union is:

```text
{key_field, kind:"NATIVE_FIELD", field, type_ref}
{key_field, kind:"SOURCE_REQUEST", member, type_ref}
{key_field, kind:"RECORD", member, type_ref}
{key_field, kind:"LITERAL", value}
```

SOURCE_REQUEST member is issuer, provider, source or request_id. RECORD member is provider, source or record_id. These metadata selectors require a declared IDENTITY or STRING type and nonempty selected values. NATIVE_FIELD resolves only a complete retained typed field, never a similar field name or unrecorded property. LITERAL carries its complete typed value and must use the slot's canonical type. Static admission checks every declaration, including unused slots; unsupported selector kinds are UNSUPPORTED_RELATION, missing references REFERENCE_INVALID, known incompatible types TYPE_INVALID, and duplicate names or ordering violations INPUT_INVALID.

`uniqueness` is exactly one of:

```text
{kind:"PROVIDER_UNIQUENESS", provider, source, atomic_scope, evidence_ref}
{kind:"EXCLUSIVE_MEDIATOR_SEEDED", provider, source, record_type,
 history_scope, cutover_id, evidence_ref}
```

For PROVIDER_UNIQUENESS, atomic_scope is exactly `{slot,namespace,key_shape}` and equals the complete enclosing declaration. The host must establish that the named provider atomically enforces that exact key across every native writer. That guarantee discharges only that slot. It does not prove historical freshness or protection of another slot.

For EXCLUSIVE_MEDIATOR_SEEDED, provider/source/record_type name the complete historical native-record interface; history_scope names the complete identity universe, including unresolved attempts and any other prior uses that the source's freshness rule covers; cutover_id names one authenticated synchronization boundary. The host must establish complete history at that boundary and exclusive mediation of every writer from that boundary onward. No registry-wide Boolean discharges these independent slot obligations. Declaration admission binds evidence references but does not authenticate the real guarantee.

The equipment specimen may declare EXCLUSIVE_MEDIATOR_SEEDED for all five slots and separately retain the Maintenance Register's atomic tuple-uniqueness premise. The tuple provider premise does not discharge the request, approval, work-order or inspection freshness requirements. Inherited apparatus slots without this complete profile retain their existing carrier only until explicit migration; they cannot satisfy equipment history coverage.

## 2. Complete historical evidence and owners

A historical native record is exactly:

```text
{provider, source, record_type, record_id, revision, occurred_at,
 state, native_fields, work_occurrence, evidence_ref}
```

Provider/source/record_type equal the selected slot's mediated uniqueness declaration. The selected interface must supply the complete HELD and CONSUMED inventories uniformly. If the native provider has no unresolved-attempt record, an explicitly declared authenticated coordinator must supply the complete interface for both states; the consumer does not relabel a missing completion as a native-provider record. Canonical key coordinates and new-operation constants must use that same declared identity domain. record_id and revision are nonempty opaque identifiers. occurred_at is a valid instant no later than coverage.as_of. state is HELD or CONSUMED. native_fields is the exact sorted named typed inventory selected by history_record_fields.held or .consumed. Values satisfy the slot's complete canonical type declarations. Missing, extra or nominally changed fields are BINDING_MISMATCH; malformed known scalar values TYPE_INVALID. HELD means the authenticated source asserts an unresolved historical attempt or prior use that remains occupied. CONSUMED means it asserts a conclusive completed use. Hashing that assertion does not prove the provider conclusion; authenticated attribution and complete normalization are host premises.

work_occurrence is null or exactly `{work_class,instance_id,occurrence_id}`. A nonnull body is the provider's retained original attribution to an actual Work-Class occurrence. No caller can supply a synthetic class or occurrence merely to fit an owner carrier. The record digest is digest("exclusive-native-history",the complete historical native record).

`source_request` is exactly `{issuer,provider,source,request_id}`, with four nonempty identity strings. These are source-request metadata, not an eighth native request argument. The source request digest is digest("exclusive-source-request",complete_source_request).

Separate request provenance is exactly:

```text
{provider, source, native_record_digest, source_request_digest,
 evidence_ref, provenance_digest}
```

Its provider/source equal the slot's declared historical interface. native_record_digest equals the full record digest above and source_request_digest equals the exact four-member metadata digest. Its complete record digest is digest("exclusive-request-provenance",complete_request_provenance). The host independently selects and authenticates this record as evidence linking the original source request to that native record. provenance_digest is a retained host assertion, not a signature verified by the consumer. An unattached request name, a copied provenance digest or a caller claim key cannot establish this linkage. The real provider need not already expose this wire; an authenticated coordinator may supply it under an explicitly declared premise. Its existence and truth remain unproven by synthetic cases.

The owner union is exactly:

```text
{kind:"WORK_OCCURRENCE", work_class, instance_id, occurrence_id}
{kind:"NATIVE_HISTORY", provider, source, record_id, record_digest}
```

WORK_OCCURRENCE requires a nonnull native record work_occurrence equal in all three members. NATIVE_HISTORY requires null work_occurrence and exact provider/source/record_id/record_digest from the retained native record. A genuine older provider record does not acquire a fabricated lifecycle owner. Different record revisions or digests are not ordered by their spelling and cannot replace a retained owner.

## 3. Seed claim and deterministic projection

Each seed claim is exactly:

```text
{slot, namespace, key, key_digest, owner, acquisition_event, status,
 settlement_evidence, native_record, record_digest,
 source_request, request_provenance}
```

slot/namespace equal the target declaration. native_record is the complete record from section 2; record_digest is recomputed from it. source_request and request_provenance are their complete records. status equals native_record.state. acquisition_event equals the SEED_EXCLUSIVE event id. For HELD, settlement_evidence is null. For CONSUMED, settlement_evidence equals native_record.record_id. This seed event records historical occupancy; it does not establish a new lifecycle effect or grant.

Derive key as a positional array of complete typed values by evaluating every history_projection row against that claim's admitted full evidence. NATIVE_FIELD copies the exact named typed value. SOURCE_REQUEST and RECORD wrap the exact metadata string under the declared nominal type. LITERAL copies its declared typed value. Compare the caller's complete key to this derived array. Any unequal value, order, nominal type or length is BINDING_MISMATCH. No assertion that two strings identify the same object replaces byte equality.

The key digest retains its established owner-independent preimage:

```text
digest("exclusive-key", {registry, slot, namespace, key})
```

registry is digest("reservation-registry",complete_configuration). Changing owner does not change key identity; changing registry configuration does. Claims sort by key_digest, with any tied group sorted by full canonical claim bytes. Exact duplicate complete claims are INPUT_INVALID. Distinct claims in a tied group with different owners or contradictory records refuse OCCURRENCE_CONFLICT and install no coverage or claims. A usable installed snapshot has one claim per key. A provider history with genuine repeated uses of one fresh identity cannot silently drop a record or choose an owner; this bounded profile fails closed until that history is represented under a separately reviewed contract. The host retains the rejected full evidence.

## 4. Coverage, event and administration

Coverage is exactly:

```text
{slot, provider, source, record_type, history_scope, cutover_id,
 as_of, revision, complete, exclusive_writers, evidence_ref, provenance_digest}
```

Coordinates, history_scope and cutover_id equal the target mediated slot. as_of equals the event's available accepted clock instant. revision is a nonempty opaque provider identifier. complete and exclusive_writers are Booleans. Complete coverage asserts that claims represent every occupied identity in the exact history_scope through the cutover, including every unresolved prior attempt and all relevant completed uses. An empty history is usable only under this same complete, exclusive-writer assertion; an empty caller list alone proves nothing. Revisions and provenance are authenticated host premises, with no hidden ordering inference.

Add the closed reservation event:

```text
{id, expected_revision, kind:"SEED_EXCLUSIVE", clock,
 payload:{slot,coverage,claims}, administration}
```

administration remains the existing nonnull `{act,returned}` member at event level; it is not nested in payload. Its selected complete HUMAN basis permits SEED_EXCLUSIVE and uses the configuration's administration provider/source/role and registry principal. The ordinary attributed administration return and exact authenticated ADMIN_RETURN tuple remain required. Cutover requires an AVAILABLE clock from configuration.clock_source, no earlier than the retained last_clock. An unavailable clock refuses CLOCK_INVALID; it cannot select a prior available cutover. Provider record dates and coverage dates are validated before any occupancy decision.

Define the full derived seed snapshot:

```text
{registry_digest, event_id, slot, coverage, claims}
```

registry_digest is the immutable selected registry digest, event_id is event.id, and the other members are the complete payload bodies. snapshot_digest is digest("exclusive-history-snapshot",complete_snapshot). It includes every native record, actual projected key, owner, status and linked source-request record. No own digest is included. The ordinary administration subject preimage remains exactly:

```text
{registry_digest, event_id, expected_revision, kind, clock, payload}
```

act.subject_digest equals digest("reservation-administration-subject",that complete body). The payload binds the complete snapshot and coverage rather than a caller's digest-only summary; event_id and registry_digest supply the remaining snapshot members. Standard administration checks independently admit the basis, role, principal, HUMAN actor, act time/disposition, attributed return and complete canonical act bytes. A machine executor credential cannot authorize seed installation.

Add these authenticated-record kinds to the existing host tuple shape `{kind,record_digest,provider,source}`:

- EXCLUSIVE_COVERAGE: digest("exclusive-history-coverage",complete_coverage), with coverage provider/source.
- EXCLUSIVE_NATIVE_HISTORY: each distinct digest("exclusive-native-history",complete_native_record), with record provider/source.
- EXCLUSIVE_REQUEST_PROVENANCE: each distinct digest("exclusive-request-provenance",complete_request_provenance), with provenance provider/source.

The host authenticated_records inventory is the exact canonical sorted unique union of these tuples and the ordinary required administrative/native/history tuples. Missing selected complete evidence or tuples is EVIDENCE_UNAVAILABLE; extras or mismatches are DEPENDENCY_MISMATCH. Authenticating the native record alone does not independently authenticate its source-request linkage. No metadata lookup or English interpretation occurs during the transition.

## 5. Installation, append, replay and restart

Add optional core.key_history. For a registry with any new mediated slot it is required, initially empty, and contains at most one record per seeded slot, sorted uniquely by snapshot.slot. Each record is exactly `{snapshot_digest,snapshot}` with the full snapshot defined above. It is an immutable installed cutover record; later reservations, effects and corrections never amend its original coverage or seed claims. Retain the seed event, full host evidence and receipt in the existing append-only receipts journal.

New-profile core.exclusive_keys rows use exactly:

```text
{key_digest, slot, namespace, key, owner, acquisition_event,
 status, settlement_evidence}
```

Inherited slot rows retain the old owner_instance/owner_occurrence shape only for inherited apparatus definitions. Carrier choice follows the immutable slot declaration; a missing owner union never selects compatibility for a new slot. A new reservation derives WORK_OCCURRENCE from its actual stable class, instance and occurrence. A seed row derives the historical owner and fields exactly from its claim.

SEED_EXCLUSIVE is allowed only for an EXCLUSIVE_MEDIATOR_SEEDED slot without an installed snapshot. A different event attempting a second seed refuses DEFINITION_CONFLICT even if it repeats the same claims; ordinary exact event replay is the sole reuse path. A partial or contradictory snapshot never replaces complete history. Existing live claims for that unseeded slot are not overwritten or relabelled: any overlap refuses OCCURRENCE_CONFLICT. New slots may append their own snapshots in later serialized seed transitions.

After complete input, attribution and administration admission, false complete or false exclusive_writers produces admitted WITHHELD with EXCLUSIVE_HISTORY_UNAVAILABLE, no installed snapshot and no new keys. The complete attempted event remains in the protected receipt journal. A usable complete snapshot atomically appends its one key_history record and every derived live claim, returning SEEDED_EXCLUSIVE. An empty complete seed appends coverage and zero keys. All other slots, numerical budgets, reservations and effects remain unchanged. Every admitted result advances the registry revision once and updates last_clock under existing rules. A refused input changes no state, log or receipt.

Exact replay returns the stored original receipt, replay:true and the current full state, without another seed, revision or permission. Altered bytes under the same id refuse REPLAY_CONFLICT before stale expected_revision. A new stale event refuses REVISION_CONFLICT before collision lookup. Preserve the existing core/receipt digest construction: next_core_digest includes key_history and all resulting claims; reservation-event hashes the full event, reservation-receipt hashes the unchanged receipt shape, and reservation-state hashes the full next state after receipt append.

Restart replays every retained admitted event from the empty core under the same immutable configuration and candidate. It recomputes coverage, native/request/provenance/snapshot/key digests, all projection values, owner/state/evidence bindings, administrative subjects and returns, initial-seed uniqueness, receipt roots and final live claims. Changed history, truncation, forged owner, missing coverage, altered status or changed old evidence is STATE_INVALID. Genuine later live HELD-to-CONSUMED settlement does not rewrite the immutable initial seed status; restart derives that later state from its own exact admitted native event. A correct top-level rehash does not excuse an unreachable checkpoint.

## 6. Reservation and reconciliation consequences

For RESERVE and RENEW preserve the existing phase order: shape/canonical admission, candidate and full state integrity, exact replay, expected registry revision and clock, then action-specific complete evidence and policy. Exact principal/class/slot/namespace/canonical type/shape/guarantee binding precedes protected history and occupancy lookup. Missing or unauthorized declarations refuse under existing action-specific codes. A different registry principal is DEPENDENCY_MISMATCH even when a protected key is occupied.

Reevaluate the complete supplied PROPOSE authority input. Require every requested mediated slot to have its exact installed complete/exclusive snapshot under the same registry declaration and selected latest state. Any missing usable coverage produces admitted WITHHELD with EXCLUSIVE_HISTORY_UNAVAILABLE before occupancy lookup; it creates no reservation or key and performs no partial write. A provider guarantee for the tuple cannot substitute for a missing seed on another requested slot. Authority failures retain their ordinary precedence and protected evidence. An exclusive withholding takes precedence over numerical history reasons. The old cutover as_of does not become a cache expiry: continuing all-writer mediation and selection of the latest durable registry are the explicit premises that keep it usable.

Only after all required coverage is usable may the transition check each exact owner-independent key. Any existing HELD or CONSUMED owner occupies it. An occupied requested key produces WITHHELD with EXCLUSIVE_KEY_OCCUPIED, no new reservation and no new keys. If all keys and any required numerical budgets are admissible, acquire the whole requested set atomically under one WORK_OCCURRENCE owner and expected revision. Failed revision/commit or one failed slot installs none. A WITHHELD with EXCLUSIVE_HISTORY_UNAVAILABLE or EXCLUSIVE_KEY_OCCUPIED carries that reason alone and empty budgets. The prohibition on partial writes covers reservations and keys. A current complete history supplied with such a WITHHELD is still committed, and the retraction marking in RESERVATION-RECORDS applies.

Exact independently attributed native completion may consume the complete retained reserved WORK_OCCURRENCE key set through the existing SETTLE transition. UNKNOWN, unavailable, missing, ambiguous or mismatched completion, expiry, abandonment and safe NOT_SENT keep the keys held. No seed, policy amendment, later source correction or terminal lookup erases prior occupied identities or grants reuse. Late exact evidence can consume those genuinely reserved HELD keys under existing native attribution rules, while preserving earlier disputes, terminal state and immutable seed records. A seeded NATIVE_HISTORY HELD owner has no invented current reservation to settle. It remains occupied; a later history status refinement requires its own exact retained reconciliation carrier. Foreign native effects need their own retained reconciliation contract; they cannot enter through a second seed or be assigned to an invented work occurrence.

## 7. Receipt, refusal codes and protected limits

The existing receipt shape stays exactly `{event_digest,prior_state_digest,revision,next_core_digest,decision,reservation,budgets,authority_result,reasons}`. Add decision SEEDED_EXCLUSIVE. Both seed outcomes have reservation:null, budgets:[] and authority_result:null. Success has reasons:[]; coverage policy withholding has reasons:[EXCLUSIVE_HISTORY_UNAVAILABLE]. The full receipt journal retains the attempted snapshot and administrative evidence, and its digest commits them through event_digest. Snapshot and collision details do not become new public receipt fields.

Use the existing admission phase code order without creating actor or administration models. Seed-specific action checks fit phase 5. Missing selected evidence is EVIDENCE_UNAVAILABLE, extra or mismatched authenticated/dependency tuples and incorrectly computed native/request/provenance/key digests DEPENDENCY_MISMATCH, unsupported guarantee/projection UNSUPPORTED_RELATION, unknown references REFERENCE_INVALID, bad projection/owner/source/date binding BINDING_MISMATCH, known scalar/type mismatch TYPE_INVALID, exact duplicate claim/declaration order INPUT_INVALID, supported-shape count overflow LIMIT_EXCEEDED, an already seeded slot DEFINITION_CONFLICT, incompatible existing/historical owners OCCURRENCE_CONFLICT, and unauthorized/revoked/negative administration ADMINISTRATION_NOT_ESTABLISHED. Structural omissions and forbidden fields remain SCHEMA_INVALID. Earlier state integrity, replay, revision and clock failures win over these action faults. Wrong digests cannot become a policy inability to prove coverage.

Claims per seed are bounded to 256 and the registry retains at most 4096 live key rows, including HELD and CONSUMED; an attempted addition beyond that semantic live limit refuses LIMIT_EXCEEDED before mutation. These advertised retained-state limits are distinct from the per-operation key-count bound. Slot inventories, type inventories, fields and key projection have their explicit 64 bounds. Full source/request/provenance bodies and immutable snapshots cannot be truncated to fit a bound. Full artifact and transport limits still apply. Histories exceeding the declared support bounds fail closed; this apparatus cannot claim large production histories qualified. Protected external request-size limits remain separately advertised transport controls and do not authorize dropping old governed evidence.

aggregate-step results, admitted state, receipt journals, native/request metadata and internal collision evidence are protected storage/administration material. They are not agent-facing collision probes. An external response may disclose only the applicable EXCLUSIVE_KEY_OCCUPIED or EXCLUSIVE_HISTORY_UNAVAILABLE reason, with no owner, key, native record, request values, count, slot-identifying collision detail or full state. An external response cannot reuse a protected stateful refusal body. Internal evidence access requires its own organization authority; this carrier grants none. Generic definition readback may show declared projection rules and guarantees, but no runtime history.

## 8. Equipment keys and exact source boundary

The equipment key inventory uses canonical source-selected field names and nominal types, with the following projection meanings. AP-091 remains the native approval identity, not a lifecycle grant or event identifier. Request issuer/provider/source/request_id remain the source-bound request metadata selected in the equipment definition.

| Slot meaning | Historical projection | New operation projection |
|---|---|---|
| Request identity | SOURCE_REQUEST issuer/request_id | Source-bound issuer and RTS-REQ-417 literals. Request provider/source remain retained provenance and cannot broaden this key to permit reuse through another provider. |
| Completed or unresolved asset/work-order/inspection/approval combination | RECORD provider/source, then NATIVE_FIELD asset/work_order/inspection/approval | Source-bound provider/source constants and the four unchanged native proposal fields |
| Approval freshness | RECORD provider/source, then NATIVE_FIELD approval | Source-bound provider/source constants and native proposal approval AP-091 |
| Work-order freshness | SOURCE_REQUEST issuer, then NATIVE_FIELD asset/work_order | Source-bound issuer, native proposal asset EQ-204 and work_order WO-7304 |
| Inspection freshness | SOURCE_REQUEST issuer, then NATIVE_FIELD asset/inspection | Source-bound issuer, native proposal asset EQ-204 and inspection IN-552 |

The specimen must define each namespace and complete key_shape rather than treating this prose table as the ABI. Source-selected constants do not enter the seven-field native request. The complete history_scope must include every relevant older request and use of those identifiers, including attempts without a conclusive completion when source policy makes them occupied. If the provider history lacks original request metadata or pre-native attempted uses, the host needs an independently authenticated complete coordinator history and corresponding declaration. It cannot assert complete coverage by reconstructing missing names from a completed tuple.

The Maintenance Register's provider atomic tuple uniqueness is an additional native guarantee. Seeded exclusive mediation provides the five local collision checks only while authenticated complete cutover history, durable serialization, ongoing all-writer exclusion and real provider/coordinator attribution hold. Snapshot hashing and synthetic cases prove none of those real facts. No uncertain send establishes rollback or absence of an effect; the safe-state interpretation remains no additional write or physical command.

## 9. Required decisive cases

Derive complete input and expected bytes before either consumer runs. Cover each projection selector, each metadata member, source-bound constants, nominal aliases, reordered key_shape, full native fields, exact provenance linkage and wrong request metadata with independently rebound digests. Include older native owners without Work-Class attribution, genuine WORK_OCCURRENCE attribution, forged lifecycle owners and changed record revisions.

Cover complete empty and nonempty seeds, HELD and CONSUMED histories, false completeness or writer exclusion, missing/mismatched authenticated coverage/native/provenance tuples, wrong provider/scope/cutover, unavailable/backwards clock, duplicate/conflicting claims, second seed, exact/altered replay, stale seed/reserve races, rehashed forged checkpoint and immutable prefix history. Cover all five slots separately and atomically, missing one mediated seed while tuple provider uniqueness is present, collisions with consumed or unresolved history, wrong principal before protected lookup, missing coverage before collision detail, exact late consumption without seed mutation, ceiling overflow and no partial commit. Provider external writes during cutover or after it require host trace evidence and remain production premises beyond the pure apparatus.

Not checked: normative/schema promotion, final pin, vector generation, either consumer, complete native equipment specimen, authenticated historical records, production cutover synchronization, real all-writer exclusion or large-history capacity. This proposed wire needs review and recorded disposition before independent implementation.
