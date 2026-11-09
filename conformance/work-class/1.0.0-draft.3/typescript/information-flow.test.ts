import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { AdmissionError, byteCompare, canonical, digest, hashBytes } from './canonical.ts';
import { evaluateAuthority } from './authority.ts';
import { admitFlowState, flowControlSubject, flowResponseSubject, flowStep, flowFence } from './information-flow.ts';
import { FLOW_FRAME_BYTES, FLOW_PUBLIC_STATUS, parseFlowFrame } from './flow-host.ts';
import { authorizationExpiry, deriveAuthorizationFence, immutableAuthority } from './dispatch-authority.ts';
import { readback } from './evidence.ts';
import { SingleProcessReferenceHost } from './reference-host.ts';
import { selectedCandidate, VERSION } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const trustedSelections = new Set<string>();
const authenticateAuthority = (_configuration: Row, input: Row): boolean => trustedSelections.has(canonical(input.host_selection));
const pin = selectedCandidate(), at = '2026-10-08T12:00:00Z';
const clone = <T>(value: T): T => structuredClone(value);
const sort = (rows: Row[], key = 'id'): Row[] => rows.sort((a, b) => byteCompare(a[key], b[key]));
const validity = { valid_from: '2026-10-01T00:00:00Z', valid_until: '2026-11-01T00:00:00Z' };
const revocation = { provider: 'identity', source: 'revocations', max_age_seconds: '0' };

// Complete ordinary authority, constructed from the public contract without consumer results.
function authority(subject: string, actor = 'auditor', operation = 'read-state'): Row {
  const source = { schema: VERSION + '/authority-source', id: 'flow-source', revision: '1', obligations: [{ id: 'access', text: 'Require current ordinary authority for this exact mediator request.' }] };
  const work = { schema: VERSION + '/authority-work-class', id: 'mediator', revision: '1', types: [{ id: 'Identity', kind: 'IDENTITY', unit: null, nonnegative: false }], steps: [{ id: 'access', interface: 'mediator', operation, executor_role: 'Agent', fields: [{ name: 'admission_subject', type_ref: 'Identity' }], scope_fields: { subjects: ['admission_subject'], resources: ['admission_subject'] }, required_credentials: [], exclusive_keys: [], quantity_mode: 'NONE' }] };
  const envelope = { schema: VERSION + '/authority-envelope', id: 'mediator-envelope', source_digest: digest('authority-source', source), work_class_digest: digest('authority-work-class', work), source_obligations: ['access'], principal: 'bank', clock_source: 'clock', executor_role: 'Agent', grantor_role: 'Grantor', attester_role: 'Attester', grant_ref: 'grant', operations: [{ step: 'access', interface: 'mediator', operation }], bindings: [{ id: 'subject', step: 'access', field: 'admission_subject', type_ref: 'Identity' }], scope: { id: 'scope', subjects: [{ kind: 'BINDING', binding: 'subject' }], resources: [{ kind: 'BINDING', binding: 'subject' }] }, conditions: [], limits: { per_action: [], shared_budgets: [] }, gate: { kind: 'NONE', role: null, materiality: 'LOW', reversibility: 'HIGH', criteria: [] }, temporal_validity: clone(validity), enforcement: { mechanisms: ['AUTHORITY_BEFORE_RESERVATION'], out_of_envelope: 'REFUSE', safe_state: 'NO_NEW_DISPATCH' }, escalation: { kind: 'DECLARED_NONE' }, limitations: [], revocation: clone(revocation) };
  const occupancies = sort([['attester', 'Attester', 'HUMAN'], ['grantor', 'Grantor', 'HUMAN'], [actor, 'Agent', 'MACHINE']].map(([id, role, kind]) => ({ id: 'occupancy-' + id, actor: id, role, kind, principal: 'bank', provider: 'identity', validity: clone(validity), evidence_ref: 'occupancy-evidence' })));
  const root = { schema: VERSION + '/authority-root', id: 'root', revision: '1', source_digest: envelope.source_digest, work_class_digest: envelope.work_class_digest, envelope_digest: digest('authority-envelope', envelope), principal: 'bank', designator: 'bank-root', capacity_ids: ['capacity-attester', 'capacity-grantor'], occupancy_ids: occupancies.map(row => row.id), providers: ['identity'], channels: [{ id: 'returns', provider: 'identity', validity: clone(validity), prior_returns_survive_expiry: false }], validity: clone(validity), prior_acts_survive_expiry: false, allow_self_attestation: false, limitations: [], revocation: clone(revocation) };
  const capacities = ['attester', 'grantor'].map(id => ({ id: 'capacity-' + id, actor: id, role: id === 'grantor' ? 'Grantor' : 'Attester', occupancy: 'occupancy-' + id, principal: 'bank', provider: 'identity', root_digest: digest('authority-root', root), envelope_digest: digest('authority-envelope', envelope), act_kinds: [id === 'grantor' ? 'GRANT' : 'ORGANISATIONAL_ATTESTATION'], may_self_attest: false, validity: clone(validity), reliance: { kind: 'CURRENT_ONLY' }, revocation: clone(revocation), evidence_ref: 'capacity-evidence' }));
  const act = (id: string, kind: string, subject_digest: string): Row => ({ id, kind, subject_digest, actor: id === 'grant' ? 'grantor' : 'attester', role: id === 'grant' ? 'Grantor' : 'Attester', principal: 'bank', occupancy: id === 'grant' ? 'occupancy-grantor' : 'occupancy-attester', capacity: id === 'grant' ? 'capacity-grantor' : 'capacity-attester', occurred_at: at, disposition: 'ACCEPT', criteria: [], attested_actor: id === 'grant' ? null : 'grantor', recorder: 'recorder' });
  const grant = act('grant', 'GRANT', digest('authority-envelope', envelope)), attest = act('attest', 'ORGANISATIONAL_ATTESTATION', digest('authority-act', grant));
  const acts = [grant, attest].sort((a, b) => byteCompare(digest('authority-act', a), digest('authority-act', b)));
  const returns = sort(acts.map(row => ({ id: 'return-' + row.id, act_digest: digest('authority-act', row), act_bytes_base64: Buffer.from(canonical(row)).toString('base64'), actor: row.actor, provider: 'identity', channel: 'returns', returned_at: at, evidence_ref: 'return-evidence' })));
  const authenticated = [...occupancies.map(row => ({ kind: 'OCCUPANCY', record_digest: digest('authority-occupancy', row), provider: 'identity', channel: null })), ...capacities.map(row => ({ kind: 'CAPACITY', record_digest: digest('authority-capacity', row), provider: 'identity', channel: null })), ...returns.map(row => ({ kind: 'RETURN', record_digest: digest('authority-return', row), provider: 'identity', channel: 'returns' }))].sort((a, b) => byteCompare(canonical(a), canonical(b)));
  const subjects = [digest('authority-root', root), digest('authority-envelope', envelope), ...capacities.map(row => digest('authority-capacity', row))];
  const observations = subjects.map(subject_digest => { const query = { purpose: 'REVOCATION', subject_digest, at, provider: 'identity', source: 'revocations' }; return { query, query_digest: digest('authority-query', query), status: 'AVAILABLE', as_of: at, revision: '1', revoked: false, evidence_ref: 'revocation-evidence' }; });
  const input = { schema: VERSION + '/authority-input', specification_pin: pin, source, work_class: work, envelope, proposal: { schema: VERSION + '/authority-proposal', work_class: work.id, work_class_digest: digest('authority-work-class', work), instance: 'instance', occurrence: 'access:1', step: 'access', interface: 'mediator', operation, executor: { actor, role: 'Agent', principal: 'bank', occupancy: 'occupancy-' + actor }, fields: [{ name: 'admission_subject', value: { type_ref: 'Identity', value: subject } }] }, clock: { source: 'clock', status: 'AVAILABLE', instant: at }, host_selection: { root, selection_evidence: 'selected', authenticated_records: authenticated }, occupancies, capacities, credentials: [], acts, returns, observations };
  trustedSelections.add(canonical(input.host_selection)); return input;
}
function configuration(): Row { return { schema: VERSION + '/flow-configuration', specification_pin: pin, id: 'bank-registry', principal: 'bank', provider: 'registry', source: 'flow', protected_channel: 'control', clock_source: 'clock', control_interface: 'mediator', access_operation: 'read', transfer_operation: 'transfer', response_operation: 'read-state', response_role: 'Agent', restrictions: [{ id: 'SAR', scope: 'scope', meaning: 'SAR confidential', releasable: false, release_role: null }] }; }
function request(kind: string, payload: Row, state: Row | null = null, id = 'event-' + (state?.core.revision ?? '0')): Row {
  const config = configuration(), event: Row = { schema: VERSION + '/flow-event', id, kind, expected_revision: state?.core.revision ?? '0', expected_state_digest: state ? digest('flow-state', state) : null, clock: { source: 'clock', status: 'AVAILABLE', instant: at }, payload: clone(payload) };
  const control = flowControlSubject(config, event);
  if (kind === 'READ') event.payload.access_authority = authority(control, state!.core.contexts.find((row: Row) => row.id === payload.context_id).actor, 'read');
  if (kind === 'IMPORT') { event.payload.access_authority = authority(control, state!.core.contexts.find((row: Row) => row.id === payload.receiver_context_id).actor, 'read'); event.payload.transfer_authority = authority(control, state!.core.contexts.find((row: Row) => row.id === payload.sender_context_id).actor, 'transfer'); }
  const kinds: Record<string, [string, string]> = { CREATE_CONTEXT: ['INITIAL_INVENTORY', digest('flow-initial-inventory', payload)], READ: ['SOURCE_CLASSIFICATION', kind === 'READ' ? digest('flow-source', payload.source) : ''], MATERIALIZE: ['MATERIALIZED_CONTENT', kind === 'MATERIALIZE' ? digest('flow-materialized-content', { types: payload.types, fields: payload.fields }) : ''] };
  const expected = kinds[kind], host = { configuration_digest: digest('flow-configuration', config), event_subject_digest: flowControlSubject(config, event), selection_evidence: 'selected', attestations: expected ? [{ kind: expected[0], subject_digest: expected[1], provider: config.provider, source: config.source, channel: config.protected_channel, evidence_ref: 'classified' }] : [] };
  const input: Row = { schema: VERSION + '/flow-input', specification_pin: pin, configuration: config, state, state_digest: state ? digest('flow-state', state) : null, event, host_evidence: host };
  input.response_authority = authority(flowResponseSubject(input)); return input;
}
function response(input: Row): Row { input.response_authority = authority(flowResponseSubject(input)); return input; }
function created(id = 'agent', state: Row | null = null, ceiling = ['SAR']): Row { const result = flowStep(request('CREATE_CONTEXT', { context_id: id, actor: id, scope: 'scope', purpose: 'INVESTIGATION', ceiling, initial_sources: [] }, state), pin); assert.equal(result.status, 'TRANSITION', JSON.stringify(result)); return result.state; }
function descriptor(restrictions = ['SAR']): Row { return { provider: 'facts', source: 'cases', record_type: 'evidence', record_id: 'record-1', revision: '1', content_digest: hashBytes(Buffer.from('secret')), scope: 'scope', restrictions }; }
function read(state: Row, source = descriptor(), context_id = 'agent'): Row { return request('READ', { context_id, intent_id: 'read-intent-' + state.core.revision, claim_id: 'read-claim-' + state.core.revision, source }, state); }
function reader(state: Row | null): Row { return request('CREATE_CONTEXT', { context_id: 'reader-probe', actor: 'auditor', scope: 'scope', purpose: 'INVESTIGATION', ceiling: [], initial_sources: [] }, state, 'read-protected-state'); }
const refuses = (code: string) => (error: unknown): boolean => error instanceof AdmissionError && error.code === code;

function reseal(input: Row, sourceValues: Record<string, Row[]> = {}): Row {
  const env = input.envelope, root = input.host_selection.root;
  env.source_digest = digest('authority-source', input.source); env.work_class_digest = digest('authority-work-class', input.work_class); input.proposal.work_class_digest = env.work_class_digest;
  root.source_digest = env.source_digest; root.work_class_digest = env.work_class_digest; root.envelope_digest = digest('authority-envelope', env);
  for (const capacity of input.capacities) { capacity.root_digest = digest('authority-root', root); capacity.envelope_digest = root.envelope_digest; }
  const grant = input.acts.find((row: Row) => row.kind === 'GRANT'); grant.subject_digest = root.envelope_digest;
  input.acts.find((row: Row) => row.kind === 'ORGANISATIONAL_ATTESTATION').subject_digest = digest('authority-act', grant);
  input.acts.sort((a: Row, b: Row) => byteCompare(digest('authority-act', a), digest('authority-act', b)));
  input.returns = sort(input.acts.map((row: Row) => ({ id: 'return-' + row.id, act_digest: digest('authority-act', row), act_bytes_base64: Buffer.from(canonical(row)).toString('base64'), actor: row.actor, provider: 'identity', channel: 'returns', returned_at: row.occurred_at, evidence_ref: 'return-evidence' })));
  input.host_selection.authenticated_records = [...input.occupancies.map((row: Row) => ({ kind: 'OCCUPANCY', record_digest: digest('authority-occupancy', row), provider: 'identity', channel: null })), ...input.capacities.map((row: Row) => ({ kind: 'CAPACITY', record_digest: digest('authority-capacity', row), provider: 'identity', channel: null })), ...input.returns.map((row: Row) => ({ kind: 'RETURN', record_digest: digest('authority-return', row), provider: 'identity', channel: 'returns' }))].sort((a, b) => byteCompare(canonical(a), canonical(b)));
  input.observations = [digest('authority-root', root), root.envelope_digest, ...input.capacities.map((row: Row) => digest('authority-capacity', row))].map(subject_digest => { const query = { purpose: 'REVOCATION', subject_digest, at, provider: 'identity', source: 'revocations' }; return { query, query_digest: digest('authority-query', query), status: 'AVAILABLE', as_of: at, revision: '1', revoked: false, evidence_ref: 'revocation-evidence' }; });
  for (const source of env.source_observation_requirements ?? []) {
    const query = { purpose: source.purpose, requirement_id: source.id, step: source.step, provider: source.provider, source: source.source, record_type: source.record_type, subject: source.subject, record_id: source.record_id, at, freshness_seconds: source.freshness_seconds, expected_status: source.expected_status, fields: source.fields, relations: source.relations, evaluation_point: source.evaluation_point };
    input.observations.push({ query, query_digest: digest('authority-query', query), status: 'AVAILABLE', as_of: at, revision: '1', provider_record_id: source.record_id, fields: clone(sourceValues[source.id]), relations: [], evidence_ref: 'source-evidence', provenance_digest: digest('test-source-provenance', { id: source.id }) });
  }
  trustedSelections.add(canonical(input.host_selection)); return input;
}
function outgoing(): Row {
  const input = authority('recipient', 'agent', 'send'); input.work_class.types.unshift({ id: 'Boolean', kind: 'BOOLEAN', unit: null, nonnegative: false });
  const source = (id: string, fields: Row[]): Row => ({ id, step: 'access', purpose: 'AUTHORITY', provider: 'identity', source: 'policy', record_type: id, subject: 'sender', record_id: id + '-record', at: 'CLOCK', freshness_seconds: '0', expected_status: 'AVAILABLE', fields, relations: [], evaluation_point: 'PROPOSE_AND_DISPATCH' });
  const records = [source('policy', [{ name: 'digest', type_ref: 'Identity' }]), source('recipient', [{ name: 'channel', type_ref: 'Identity' }, { name: 'effective', type_ref: 'Boolean' }, { name: 'purpose', type_ref: 'Identity' }, { name: 'recipient', type_ref: 'Identity' }])];
  input.work_class.steps[0].dispatch_gate = { kind: 'SOURCE_REQUIREMENTS', requirements: ['policy', 'recipient'], coordinator_requirement: 'policy', fence_provider: 'identity', fence_source: 'policy', authorization_seconds: '60', validity_requirements: [] }; input.envelope.source_observation_requirements = records;
  const config = configuration(), policy = { id: 'policy', revision: '1', configuration_digest: digest('flow-configuration', config), entitlements: [{ restriction_id: 'SAR', scope: 'scope', recipient: 'recipient', channel: 'custody', purpose: 'INVESTIGATION' }], release_rules: [] };
  input.envelope.flow_requirements = [{ id: 'flow', step: 'access', configuration_digest: policy.configuration_digest, context_id: 'agent', artifact_id: 'message', intent_id: 'send-intent', claim_id: 'send-claim', recipient_field: 'admission_subject', channel: 'custody', purpose: 'INVESTIGATION', policy, release_decision_requirement_id: null, sources: { policy: { requirement_id: 'policy', digest_field: 'digest' }, recipient: { requirement_id: 'recipient', recipient_field: 'recipient', channel_field: 'channel', purpose_field: 'purpose', effective_field: 'effective' }, release_selection: null, release_effectiveness: null, blockers: [] } }];
  const state = flowStep(request('MATERIALIZE', { context_id: 'agent', artifact_id: 'message', types: input.work_class.types, fields: input.proposal.fields }, flowStep(read(created()), pin).state), pin).state;
  input.flow_bases = [{ requirement_id: 'flow', configuration: config, state, state_digest: digest('flow-state', state), selection: { configuration_digest: policy.configuration_digest, state_digest: digest('flow-state', state), revision: state.core.revision, provider: config.provider, source: config.source, channel: config.protected_channel, at, status: 'AVAILABLE', selection_evidence: 'selected-current' }, released_restrictions: [] }];
  const field = (name: string, value: any): Row => ({ name, value: { type_ref: typeof value === 'boolean' ? 'Boolean' : 'Identity', value } });
  return reseal(input, { policy: [field('digest', digest('flow-policy', policy))], recipient: [field('channel', 'custody'), field('effective', true), field('purpose', 'INVESTIGATION'), field('recipient', 'recipient')] });
}

test('flow ordinary control authority is complete and independently ready', () => { assert.equal(evaluateAuthority(authority('subject'), pin).status, 'READY_FOR_RESERVATION'); });
test('flow creation is dormant, exact read activates and preserves its immutable origin', () => {
  const state = created(); assert.equal(state.core.contexts[0].revision, '1');
  const dormant = request('MATERIALIZE', { context_id: 'agent', artifact_id: 'artifact', types: [], fields: [] }, state); assert.equal(flowStep(dormant, pin).code, 'ACCESS_NOT_ESTABLISHED');
  const result = flowStep(read(state), pin); assert.equal(result.status, 'TRANSITION'); assert.deepEqual(result.state.core.contexts[0].restrictions, ['SAR']); assert.equal(result.state.core.contexts[0].revision, '2'); assert.equal(result.state.core.claims[0].status, 'POSSIBLE_EXPOSURE'); assert.equal(result.receipt.authority_result_digests.length, 1);
});
test('flow every protected output and replay requires current independently bound reader authority', () => {
  const input = read(created()), first = flowStep(input, pin); assert.equal(first.status, 'TRANSITION');
  const replay = response({ ...clone(input), state: first.state, state_digest: first.state_digest }); assert.equal(flowStep(replay, pin).replay, true);
  replay.response_authority.proposal.fields[0].value.value = 'wrong'; const denial = flowStep(replay, pin); assert.deepEqual(denial, { status: 'REFUSED', code: 'BINDING_MISMATCH', path: '' });
  const changed = response({ ...clone(input), state: first.state, state_digest: first.state_digest }); changed.event.clock.instant = '2026-10-08T11:00:00Z'; response(changed); assert.equal(flowStep(changed, pin).code, 'REPLAY_CONFLICT');
});
test('flow denials consume no claim and unknown or conflicting origins cannot be reclassified', () => {
  const state = created('agent', null, []), input = read(state), refused = flowStep(input, pin); assert.equal(refused.code, 'ACCESS_NOT_ESTABLISHED'); assert.deepEqual(refused.state, state);
  const first = flowStep(read(created()), pin), changed = descriptor([]); assert.equal(flowStep(read(first.state, changed), pin).code, 'DEPENDENCY_MISMATCH');
});
test('flow materialization retains full native values, summaries and imports preserve current sending restrictions', () => {
  let state = flowStep(read(created()), pin).state;
  const materialized = flowStep(request('MATERIALIZE', { context_id: 'agent', artifact_id: 'summary', types: [{ id: 'Text', kind: 'STRING', unit: null, nonnegative: false }], fields: [{ name: 'summary', value: { type_ref: 'Text', value: 'Condensed.' } }] }, state), pin); assert.equal(materialized.status, 'TRANSITION'); state = created('receiver', materialized.state);
  const input = request('IMPORT', { sender_context_id: 'agent', receiver_context_id: 'receiver', artifact_id: 'summary', intent_id: 'import-intent', claim_id: 'import-claim' }, state);
  const imported = flowStep(input, pin); assert.equal(imported.status, 'TRANSITION'); assert.deepEqual(imported.state.core.contexts.find((row: Row) => row.id === 'receiver').restrictions, ['SAR']); assert.equal(imported.receipt.authority_result_digests.length, 2);
  const unauthorized = clone(input); unauthorized.event.payload.transfer_authority.proposal.executor.actor = 'other'; response(unauthorized); assert.equal(flowStep(unauthorized, pin).code, 'BINDING_MISMATCH');
});
test('flow rehashing edited origins, receipts or history cannot repair complete reconstruction', () => {
  const result = flowStep(read(created()), pin), state = clone(result.state); state.core.contexts[0].restrictions = []; assert.throws(() => admitFlowState(configuration(), state, digest('flow-state', state), pin), refuses('STATE_INVALID'));
  const history = clone(result.state); history.records[1].receipt.authority_result_digests = []; history.records[1].receipt_digest = digest('flow-receipt', history.records[1].receipt); assert.throws(() => admitFlowState(configuration(), history, digest('flow-state', history), pin), refuses('STATE_INVALID'));
});
test('flow stable intent identity prevents renamed attempts after possible exposure', () => {
  const input = read(created()), first = flowStep(input, pin), retry = read(first.state); retry.event.payload.intent_id = input.event.payload.intent_id;
  retry.event.payload.access_authority = authority(flowControlSubject(retry.configuration, retry.event), 'agent', 'read'); response(retry);
  assert.equal(flowStep(retry, pin).code, 'DEPENDENCY_MISMATCH');
});
test('flow raw route bounds bytes and depth before recursive parsing', () => {
  assert.throws(() => parseFlowFrame(Buffer.alloc(FLOW_FRAME_BYTES + 1)), refuses('LIMIT_EXCEEDED'));
  assert.throws(() => parseFlowFrame(Buffer.from('['.repeat(129) + 'null' + ']'.repeat(129) + '\n')), refuses('LIMIT_EXCEEDED'));
  assert.throws(() => parseFlowFrame(Buffer.from('{"a":null,"a":null}\n')), refuses('SCHEMA_INVALID'));
  assert.deepEqual(parseFlowFrame(Buffer.from('{"text":"[[[\\\""}\n')), { text: '[[["' });
  assert.deepEqual(parseFlowFrame(Buffer.from('{}\r\n')), {});
  for (const frame of ['{}', '{}\n\n', '{\n}\n', '{}\n{}\n']) assert.throws(() => parseFlowFrame(Buffer.from(frame)), refuses('SCHEMA_INVALID'));
  const bounded = Buffer.concat([Buffer.from('{}'), Buffer.alloc(FLOW_FRAME_BYTES - 3, 32), Buffer.from('\n')]);
  assert.deepEqual(parseFlowFrame(bounded), {});
  assert.throws(() => parseFlowFrame(Buffer.concat([bounded.subarray(0, -1), Buffer.from(' \n')])), refuses('LIMIT_EXCEEDED'));
});
test('flow refresh preserves immutable selected configuration and release subset with optional empty evidence', () => {
  const input = authority('subject'); input.flow_bases = []; const omitted = clone(input); delete omitted.flow_bases; assert.notDeepEqual(evaluateAuthority(input, pin).evidence_digest, evaluateAuthority(omitted, pin).evidence_digest);
  input.flow_bases = [{ requirement_id: 'flow', configuration: configuration(), released_restrictions: ['SAR'], state: {}, state_digest: 'old', selection: {} }];
  const next = clone(input); next.flow_bases[0].state = { changed: true }; next.flow_bases[0].state_digest = 'new'; next.flow_bases[0].selection = { changed: true }; assert.deepEqual(immutableAuthority(input), immutableAuthority(next));
  next.flow_bases[0].released_restrictions = []; assert.notDeepEqual(immutableAuthority(input), immutableAuthority(next));
});
test('flow current outgoing authority uses exact materialization and complete source policy', () => {
  const input = outgoing(), result = evaluateAuthority(input, pin); assert.equal(result.status, 'READY_FOR_RESERVATION', JSON.stringify(result)); assert.equal(result.checks.filter((row: Row) => row.purpose === 'FLOW').length, 1); assert.equal(flowFence(input)[0].intent_id, 'send-intent');
  const artifact = clone(input); artifact.proposal.fields[0].value.value = 'other'; assert.equal(evaluateAuthority(artifact, pin).code, 'BINDING_MISMATCH');
  const missing = clone(input); missing.flow_bases = []; assert.equal(evaluateAuthority(missing, pin).code, 'EVIDENCE_UNAVAILABLE');
  const stale = clone(input); stale.flow_bases[0].selection.at = '2026-10-08T11:59:59Z'; assert.deepEqual(evaluateAuthority(stale, pin).reasons, ['FLOW_STALE']);
  const unavailable = clone(input); unavailable.flow_bases[0].selection.status = 'CONFLICTING'; assert.deepEqual(evaluateAuthority(unavailable, pin).reasons, ['FLOW_UNAVAILABLE']);
  const changed = clone(input); changed.observations.find((row: Row) => row.query.requirement_id === 'policy').fields[0].value.value = digest('different-policy', {}); changed.observations.find((row: Row) => row.query.requirement_id === 'recipient').fields.find((row: Row) => row.name === 'effective').value.value = false; assert.deepEqual(evaluateAuthority(changed, pin).reasons, ['FLOW_DEPENDENCY_CHANGED', 'FLOW_RECIPIENT_NOT_ENTITLED']);
});
test('flow EXPOSE projects only prior state, reconstructs exactly and never authorizes a second claim', () => {
  const input = outgoing(), projection = clone(input), state = projection.flow_bases[0].state; delete projection.flow_bases[0].state;
  const exposure = request('EXPOSE', { requirement_id: 'flow', authority_projection: projection }, state), result = flowStep(exposure, pin); assert.equal(result.status, 'TRANSITION', JSON.stringify(result)); assert.equal(result.receipt.decision, 'EXPOSURE_RECORDED'); assert.equal(result.state.core.claims.find((row: Row) => row.id === 'send-claim').intent_id, 'send-intent');
  assert.doesNotThrow(() => admitFlowState(configuration(), result.state, result.state_digest, pin));
  const replay = response({ ...clone(exposure), state: result.state, state_digest: result.state_digest }); assert.equal(flowStep(replay, pin).replay, true);
  const refresh = clone(input); refresh.flow_bases[0].state = result.state; refresh.flow_bases[0].state_digest = result.state_digest; refresh.flow_bases[0].selection.state_digest = result.state_digest; refresh.flow_bases[0].selection.revision = result.state.core.revision;
  assert.deepEqual(evaluateAuthority(refresh, pin).reasons, ['FLOW_CLAIM_CONSUMED']);
});
test('flow host selects installed current state, authentic source bytes and commits before read delivery', async () => {
  const host = new SingleProcessReferenceHost(pin, authenticateAuthority), config = configuration(), initial = request('CREATE_CONTEXT', { context_id: 'agent', actor: 'agent', scope: 'scope', purpose: 'INVESTIGATION', ceiling: ['SAR'], initial_sources: [] });
  await host.installFlow('org', config, initial.event.clock, []); const first = await host.submitFlow('org', initial); assert.equal(first.status, 'TRANSITION');
  const input = read(first.state); assert.equal((await host.submitFlow('org', input)).code, 'EVIDENCE_UNAVAILABLE');
  await host.installFlowSource('org', 'bank', descriptor(), Buffer.from('secret'));
  let calls = 0; const result = await host.submitFlow('org', input, null, { context_id: 'agent', actor: 'agent', invoke: async bytes => { calls++; assert.equal(bytes.toString(), 'secret'); const checkpoint = await Promise.resolve(); assert.equal(checkpoint, undefined); } }); assert.equal(result.status, 'TRANSITION'); assert.equal(calls, 1);
  const checkpoint = await host.exportCheckpoint({ org: [reader(result.state)] }); assert.equal(checkpoint.flows[0][1].state.core.claims.length, 1); assert.equal(checkpoint.flow_deliveries[0][1].status, 'ESTABLISHED');
  const restarted = SingleProcessReferenceHost.fromCheckpoint(pin, checkpoint, authenticateAuthority), replay = response({ ...clone(input), state: result.state, state_digest: result.state_digest }); assert.equal((await restarted.submitFlow('org', replay, null, { context_id: 'agent', actor: 'agent', invoke: () => { calls++; } })).replay, true); assert.equal(calls, 1);
  const rollback = await restarted.submitFlow('org', input); assert.deepEqual(rollback, { status: 'REFUSED', code: 'REVISION_CONFLICT', path: '' });
});
test('flow host read failure cuts preserve possible exposure and never retry partial or uncertain delivery', async (t) => {
  for (const cut of ['BEFORE_COMMIT', 'AFTER_COMMIT', 'AFTER_INVOKE', 'PROVIDER_ERROR']) await t.test(cut, async () => {
    const host = new SingleProcessReferenceHost(pin, authenticateAuthority), config = configuration(), state = created(), input = read(state); let calls = 0;
    await host.installFlow('org', config, input.event.clock, [], state, input.state_digest); await host.installFlowSource('org', 'bank', descriptor(), Buffer.from('secret'));
    const delivery = { context_id: 'agent', actor: 'agent', invoke: () => { calls++; if (cut === 'PROVIDER_ERROR') throw new Error('Partial result or existence-sensitive error escaped.'); } };
    const result = await host.submitFlow('org', input, cut, delivery), checkpoint = await host.exportCheckpoint({ org: [reader(cut === 'BEFORE_COMMIT' ? state : result.state)] }), current = checkpoint.flows[0][1];
    assert.equal(calls, cut === 'BEFORE_COMMIT' || cut === 'AFTER_COMMIT' ? 0 : 1);
    assert.equal(current.state.core.claims.length, cut === 'BEFORE_COMMIT' ? 0 : 1);
    if (cut === 'BEFORE_COMMIT') { assert.equal(result.status, 'COMMIT_FAILED'); assert.equal((await host.submitFlow('org', input, null, delivery)).status, 'TRANSITION'); assert.equal(calls, 1); }
    else {
      assert.deepEqual(current.state.core.contexts[0].restrictions, ['SAR']); const replay = response({ ...clone(input), state: current.state, state_digest: current.state_digest });
      assert.equal((await SingleProcessReferenceHost.fromCheckpoint(pin, checkpoint, authenticateAuthority).submitFlow('org', replay, null, delivery)).replay, true); assert.equal(calls, cut === 'AFTER_COMMIT' ? 0 : 1);
    }
  });
});
test('flow host holds all participating local writers until asynchronous first custody returns', async () => {
  const host = new SingleProcessReferenceHost(pin, authenticateAuthority), state = created(), input = read(state); await host.installFlow('org', configuration(), input.event.clock, [], state, input.state_digest); await host.installFlowSource('org', 'bank', descriptor(), Buffer.from('secret'));
  let entered!: () => void, finish!: () => void; const called = new Promise<void>(resolve => { entered = resolve; }), pending = new Promise<void>(resolve => { finish = resolve; });
  const transition = host.submitFlow('org', input, null, { context_id: 'agent', actor: 'agent', invoke: () => { entered(); return pending; } }); await called;
  try { await assert.rejects(() => host.advanceFlowClock('org', 'bank', input.event.clock), refuses('OPERATION_NOT_ALLOWED')); await assert.rejects(() => host.installFlowSource('org', 'bank', descriptor(), Buffer.from('secret')), refuses('OPERATION_NOT_ALLOWED')); }
  finally { finish(); }
  assert.equal((await transition).status, 'TRANSITION');
});
test('flow host constant status uses only two independent clean origins and exact request destination', async () => {
  const host = new SingleProcessReferenceHost(pin, authenticateAuthority), config = configuration();
  const initial = request('CREATE_CONTEXT', { context_id: 'status', actor: 'auditor', scope: 'scope', purpose: 'PUBLIC_STATUS', ceiling: [], initial_sources: [] }); await host.installFlow('org', config, initial.event.clock, []);
  let state = (await host.submitFlow('org', initial)).state;
  const independent = { id: 'request-1', recipient: 'client-1', digest: digest('flow-public-status-request', { id: 'request-1', recipient: 'client-1' }) };
  const constant = { provider: config.provider, source: config.source, record_type: 'HOST_CONSTANT', record_id: 'flow-public-status', revision: '1', content_digest: hashBytes(Buffer.from(FLOW_PUBLIC_STATUS)), scope: 'scope', restrictions: [] };
  const trigger = { ...constant, record_type: 'INDEPENDENT_REQUEST', record_id: independent.id, content_digest: independent.digest };
  const triggerBytes = Buffer.from(VERSION + '/flow-public-status-request\n' + canonical({ id: independent.id, recipient: independent.recipient }));
  for (const [source, bytes] of [[constant, Buffer.from(FLOW_PUBLIC_STATUS)], [trigger, triggerBytes]] as const) { await host.installFlowSource('org', 'bank', source, bytes); state = (await host.submitFlow('org', read(state, source, 'status'))).state; }
  const result = await host.publicFlowStatus('org', 'bank', independent, authority(independent.digest)); assert.equal(result.body, FLOW_PUBLIC_STATUS); assert.equal(result.body.endsWith('\n'), false); assert.equal(result.recipient, 'client-1'); assert.equal('protected_diagnostics' in result, false);
  await assert.rejects(() => host.publicFlowStatus('org', 'bank', { ...independent, recipient: 'other-client' }, authority(independent.digest)), refuses('BINDING_MISMATCH'));
  await assert.rejects(() => host.publicFlowStatus('org', 'bank', { ...independent, diagnostics: 'protected case' } as any, authority(independent.digest)), refuses('ACCESS_NOT_ESTABLISHED'));
});
test('flow fence expiry clips current ordinary remit and executor session ends', () => {
  const input = outgoing(), gate = input.work_class.steps[0].dispatch_gate, permit = { expires_at: '2026-10-08T12:05:00Z' };
  input.capacities[0].validity.valid_until = '2026-10-08T12:00:20Z'; assert.equal(authorizationExpiry(permit, gate, input), '2026-10-08T12:00:20Z');
  input.occupancies.find((row: Row) => row.id === input.proposal.executor.occupancy).validity.valid_until = '2026-10-08T12:00:10Z'; assert.equal(authorizationExpiry(permit, gate, input), '2026-10-08T12:00:10Z');
});

async function businessHost(authenticate = authenticateAuthority): Promise<Row> {
  const auth = outgoing(), sourceValues = Object.fromEntries(auth.observations.filter((row: Row) => row.query.requirement_id).map((row: Row) => [row.query.requirement_id, row.fields]));
  auth.work_class.revision = 'r1'; auth.source.revision = 'r1'; auth.work_class.steps[0].authority_type_refs = ['Boolean']; reseal(auth, sourceValues);
  const operation = { ...clone(auth.work_class.steps[0]), kind: 'OPERATION', authority_requirements: [auth.envelope.id], shared_budgets: [], prior_effect_bindings: [], prior_actor_separations: [], permit_seconds: '300', failure_behavior: 'STOP', completion: { effect_provider: 'custody', effect_source: 'connector', effect_record_type: 'accepted', no_effect_provider: 'custody', no_effect_source: 'connector', no_effect_record_type: 'no-effect', evidence_bindings: [{ evidence_field: 'admission_subject', request_field: 'admission_subject' }], status_field: 'status', status_type_ref: 'Identity', route_label_field: null, route_label_type_ref: null, success_values: [{ type_ref: 'Identity', value: 'ACCEPTED' }], failure_values: [], terminal_policy: 'LEGACY_NONTERMINAL' } };
  const terminal = { id: 'terminal', kind: 'TERMINAL', executor_role: null, interface: null, operation: null, fields: [], scope_fields: null, required_credentials: [], authority_requirements: [], shared_budgets: [], exclusive_keys: [], prior_effect_bindings: [], prior_actor_separations: [], permit_seconds: null, failure_behavior: null, completion: null };
  const definition = { schema: VERSION + '/work-class-definition', specification_pin: pin, profile: 'LINEAR', id: auth.work_class.id, revision: auth.work_class.revision, source: { id: auth.source.id, revision: auth.source.revision, obligations: auth.source.obligations.map((row: Row) => row.id) }, participants: [{ id: 'agent', kind: 'AGENT', role: 'Agent' }], types: clone(auth.work_class.types), objects: [], steps: [operation, terminal], relationships: [{ from: 'access', kind: 'SEQUENCE', to: 'terminal' }], root: 'access', occurrence_limits: [{ step_id: 'access', maximum: '1' }], limits: { maximum_activations: '8', maximum_actuations: '8', maximum_proposals: '8', maximum_fanout_objects: '8', maximum_active_obligations: '8' }, shared_budgets: [], choices: [], deadlines: [], fanouts: [], loops: [], parallel_blocks: [] };
  const workDigest = digest('work-class-definition', definition), common = { schema: VERSION + '/evidence-record', status: 'ACCEPTED', recorded_at: at, provenance_digest: digest('test-evidence-provenance', {}) };
  const correspondence: Row = { ...common, kind: 'CORRESPONDENCE', evidence_id: 'correspondence', subject_digest: workDigest, work_class_digest: workDigest, source_id: definition.source.id, source_revision: definition.source.revision, mappings: [{ source_obligation_id: 'access', provision_paths: readback(definition).map(row => row.path) }], uncovered_source_obligation_ids: [], unsupported_provision_paths: [], residue: [] };
  correspondence.review = { ...common, kind: 'REVIEW', evidence_id: 'correspondence-review', subject_digest: digest('correspondence-subject', correspondence), reviewer_id: 'reviewer', paragraph_ids: [], case_ids: [], finding_ids: [] };
  const confirmation = { ...common, kind: 'SOURCE_CONFIRMATION', evidence_id: 'confirmation', subject_digest: digest('work-class-source', definition.source), actor_id: 'source-owner', scope_ids: ['access'] };
  const decision = { ...common, kind: 'POLICY_DECISION', evidence_id: 'decision', subject_digest: workDigest, decision_maker_id: 'policy-owner', decision_ids: ['decision'] };
  const authorization: Row = { schema: VERSION + '/deployment-authorization', specification_pin: pin, organization_id: 'org', authorization_id: 'deploy', instance_id: 'instance', work_class_digest: workDigest, profile: 'LINEAR', role: 'LINEAR_WORK_RUNTIME', status: 'AUTHORIZED', authorized_at: at, expires_at: null, correspondence_evidence_digest: digest('evidence', correspondence), source_confirmation_evidence_digest: digest('evidence', confirmation), policy_decision_evidence_digest: digest('evidence', decision) };
  const evidence = { ...common, kind: 'ORGANIZATIONAL_AUTHORIZATION', evidence_id: 'authorization', subject_digest: digest('deployment-authorization-subject', authorization), organization_id: 'org', authorizer_id: 'authorizer', authorization_scope: [pin, workDigest, 'LINEAR', 'LINEAR_WORK_RUNTIME', 'instance'].sort(byteCompare), expires_at: validity.valid_until };
  authorization.authorization_evidence_digest = digest('evidence', evidence);
  const deployment = { profile: 'LINEAR', role: 'LINEAR_WORK_RUNTIME', specification_pin: pin, definition, definition_digest: workDigest, instance_id: 'instance', deployment_authorization: authorization, authorization_evidence: evidence, correspondence_evidence: correspondence, source_confirmation_evidence: confirmation, policy_decision_evidence: decision, authorization_clock: { source: 'deployment', revision: '1', status: 'AVAILABLE', observed_time: at, evidence_digest: digest('test-clock', {}) }, initial_clocks: [] };
  const host = new SingleProcessReferenceHost(pin, authenticate), connector = { id: 'connector', version: 'v1', binding_digest: digest('connector-binding', { id: 'connector', version: 'v1' }) }, flow = auth.flow_bases[0];
  await host.installFlow('org', flow.configuration, auth.clock, [{ interface: 'mediator', operation: 'send', recipient_field: 'admission_subject', channel: 'custody', purpose: 'INVESTIGATION', connector, immediate_custody: true }], flow.state, flow.state_digest);
  const installed = await host.install(deployment); assert.equal(installed.disposition, 'INSTALLED', JSON.stringify(installed));
  const submit = async (event: Row): Promise<Row> => {
    const snapshot = await host.snapshot('org', 'instance', [reader(flow.state)]);
    const complete = { schema: VERSION + '/runtime-event', instance_id: 'instance', expected_state_revision: snapshot.state.revision, expected_state_digest: snapshot.state_digest, ...event };
    const result = await host.submit('org', { profile: 'LINEAR', role: 'LINEAR_WORK_RUNTIME', specification_pin: pin, definition, definition_digest: workDigest, state: snapshot.state, state_digest: snapshot.state_digest, event: complete }, null, [reader(flow.state)]); assert.equal(result.host_commit?.disposition, 'COMMITTED', JSON.stringify(result)); return result.transition;
  };
  await submit({ event_id: 'clock', kind: 'CLOCK', activation_clocks: [], clock: { source: 'clock', revision: '1', status: 'AVAILABLE', observed_time: at, evidence_digest: digest('test-clock', {}) } });
  const snapshot = await host.snapshot('org', 'instance', [reader(flow.state)]); auth.proposal.occurrence = snapshot.state.active[0].occurrence.occurrence_id; reseal(auth, sourceValues);
  const native = { interface: auth.proposal.interface, operation: auth.proposal.operation, fields: clone(auth.proposal.fields) };
  const proposal = await submit({ event_id: 'propose', kind: 'PROPOSE', clock_revision: '1', occurrence: snapshot.state.active[0].occurrence, native_request: native, executor: { participant_id: 'agent', role: 'Agent', binding_digest: digest('executor-binding', auth.proposal.executor) }, credential_ids: [], observation_digests: auth.observations.map((row: Row) => digest('authority-observation', row)).sort(byteCompare), authority_input: auth, budget_inputs: [] });
  const permit = proposal.state.permits[0]; assert.ok(permit.authority_basis.flow_bases);
  const dispatchAuthority = clone(auth); dispatchAuthority.evaluation_point = 'DISPATCH';
  const event: Row = { instance_id: 'instance', event_id: 'authorize', kind: 'AUTHORIZE_DISPATCH', clock_revision: '1', permit, native_request: native, connector, dispatch_intent_id: 'business-intent', observation_digests: dispatchAuthority.observations.map((row: Row) => digest('authority-observation', row)).sort(byteCompare), authority_input: dispatchAuthority };
  event.authorization_fence = deriveAuthorizationFence(event, operation.dispatch_gate, evaluateAuthority(dispatchAuthority, pin), authorizationExpiry(permit, operation.dispatch_gate, dispatchAuthority));
  const authorized = await submit(event); assert.equal(authorized.state.authorizations[0].authorization_fence.flows.length, 1); assert.deepEqual(authorized.decision.details[0].flows, authorized.state.authorizations[0].authorization_fence.flows);
  const projection = clone(dispatchAuthority); delete projection.flow_bases[0].state;
  const exposure = request('EXPOSE', { requirement_id: 'flow', authority_projection: projection }, flow.state);
  return { host, native, permit, connector, exposure, before: flow.state, after: flowStep(exposure, pin).state }; 
}
test('flow protected business dispatch joins lifecycle authorization and claim before one custody invocation', async () => {
  const row = await businessHost(); let calls = 0;
  const connector = { ...row.connector, invoke: () => { calls++; return { accepted: true }; } };
  const readers = () => [reader(calls ? row.after : row.before)];
  const result = await row.host.dispatchPermitted('org', 'instance', row.permit.permit_id, row.native, connector, undefined, null, row.exposure, readers);
  assert.equal(result.status, 'COMMITTED'); assert.equal(calls, 1); assert.equal(result.invocation.flow_receipt.decision, 'EXPOSURE_RECORDED');
  const checkpoint = await row.host.exportCheckpoint({ org: readers }), current = checkpoint.flows[0][1], replay = response({ ...clone(row.exposure), state: current.state, state_digest: current.state_digest });
  const retained = await SingleProcessReferenceHost.fromCheckpoint(pin, checkpoint, authenticateAuthority).dispatchPermitted<Row>('org', 'instance', row.permit.permit_id, row.native, connector, undefined, null, replay, readers); assert.equal(retained.status, 'RETAINED_RESULT'); assert.equal(calls, 1);
});

test('flow protected business failure cuts never restore a possible disclosure or retry custody', async t => {
  for (const cut of ['BEFORE_INTENT', 'AFTER_INTENT', 'AFTER_INVOKE', 'OUTCOME_WRITE', 'PROVIDER_ERROR', 'NOT_SENT']) await t.test(cut, async () => {
    const row = await businessHost(); let calls = 0;
    const connector = { ...row.connector, invoke: () => { calls++; if (cut === 'PROVIDER_ERROR') throw new Error('Custody may have received bytes.'); return { status: cut === 'NOT_SENT' ? 'NOT_SENT' : 'ACCEPTED' }; } };
    const committed = cut !== 'BEFORE_INTENT', readers = () => [reader(committed ? row.after : row.before)];
    let sampled = 0; const responseReaders = () => [reader(++sampled === 1 ? row.before : committed ? row.after : row.before)];
    const result = await row.host.dispatchPermitted('org', 'instance', row.permit.permit_id, row.native, connector, undefined, cut, row.exposure, responseReaders);
    assert.equal(calls, ['BEFORE_INTENT', 'AFTER_INTENT'].includes(cut) ? 0 : 1);
    const checkpoint = await row.host.exportCheckpoint({ org: readers }), current = checkpoint.flows[0][1];
    assert.equal(current.state.core.claims.some((claim: Row) => claim.intent_id === 'send-intent'), committed);
    if (!committed) { assert.equal(result.status, 'COMMIT_FAILED'); return; }
    assert.equal(result.status, ['NOT_SENT'].includes(cut) ? 'COMMITTED' : 'PENDING_RECONCILIATION');
    const replay = response({ ...clone(row.exposure), state: current.state, state_digest: current.state_digest });
    const retained = await SingleProcessReferenceHost.fromCheckpoint(pin, checkpoint, authenticateAuthority).dispatchPermitted<Row>('org', 'instance', row.permit.permit_id, row.native, connector, undefined, null, replay, readers);
    assert.equal(retained.status, cut === 'NOT_SENT' ? 'RETAINED_RESULT' : 'PENDING_RECONCILIATION'); assert.equal(calls, cut === 'AFTER_INTENT' ? 0 : 1);
  });
});
test('flow inherited display and mutation routes require a current reader before every protected result', async () => {
  const row = await businessHost(), valid = () => [reader(row.before)];
  await assert.rejects(() => row.host.snapshot('org', 'instance'), refuses('ACCESS_NOT_ESTABLISHED'));
  await assert.rejects(() => row.host.pendingEvidence('org', 'instance'), refuses('ACCESS_NOT_ESTABLISHED'));
  await assert.rejects(() => row.host.exportCheckpoint(), refuses('ACCESS_NOT_ESTABLISHED'));
  assert.deepEqual(await row.host.pendingEvidence('org', 'instance', valid), []);
  const snapshot = await row.host.snapshot('org', 'instance', valid), checkpoint = await row.host.exportCheckpoint({ org: valid }), root = checkpoint.roots[0][1], deployment = JSON.parse(root.deploy_request);
  const event = { schema: VERSION + '/runtime-event', kind: 'CLOCK', event_id: 'later-clock', instance_id: 'instance', expected_state_revision: snapshot.state.revision, expected_state_digest: snapshot.state_digest, activation_clocks: [], clock: { source: 'clock', revision: '2', status: 'AVAILABLE', observed_time: at, evidence_digest: digest('test-clock', { later: true }) } };
  const input = { profile: deployment.profile, role: deployment.role, specification_pin: pin, definition: deployment.definition, definition_digest: deployment.definition_digest, state: snapshot.state, state_digest: snapshot.state_digest, event };
  assert.deepEqual(await row.host.submit('org', input), SingleProcessReferenceHost.publicFailure());
  let reads = 0; const changingReader = () => { const selected = reader(row.before); if (++reads > 1) selected.response_authority.observations[0].revoked = true; return [selected]; };
  assert.deepEqual(await row.host.submit('org', input, null, changingReader), SingleProcessReferenceHost.publicFailure());
  assert.equal((await row.host.snapshot('org', 'instance', valid)).state.revision, (BigInt(snapshot.state.revision) + 1n).toString());
});
test('flow reader denial after custody preserves committed evidence and suppresses the protected response', async () => {
  const row = await businessHost(); let calls = 0, reads = 0;
  const connector = { ...row.connector, invoke: () => { calls++; return { accepted: true }; } };
  const readers = () => { const selected = reader(reads++ ? row.after : row.before); if (reads > 1) selected.response_authority.observations[0].revoked = true; return [selected]; };
  assert.deepEqual(await row.host.dispatchPermitted('org', 'instance', row.permit.permit_id, row.native, connector, undefined, null, row.exposure, readers), SingleProcessReferenceHost.publicFailure());
  assert.equal(calls, 1); const checkpoint = await row.host.exportCheckpoint({ org: [reader(row.after)] });
  assert.equal(checkpoint.invocations[0][1].status, 'ESTABLISHED'); assert.equal(checkpoint.flows[0][1].state.core.claims.length, row.after.core.claims.length);
});
test('flow undeclared native routes and altered custody bindings refuse before invocation', async () => {
  const row = await businessHost(); let calls = 0; const connector = { ...row.connector, invoke: () => { calls++; } };
  await assert.rejects(() => row.host.dispatchPermitted('org', 'instance', row.permit.permit_id, { ...row.native, operation: 'alternate-route' }, connector, undefined, null, row.exposure), refuses('EVIDENCE_UNAVAILABLE'));
  await assert.rejects(() => row.host.dispatchPermitted('org', 'instance', row.permit.permit_id, row.native, { ...connector, id: 'alternate-custody' }, undefined, null, row.exposure), refuses('BINDING_MISMATCH'));
  assert.equal(calls, 0);
});
test('flow context capacity refuses a fresh creation and permits exact replay at capacity', () => {
  let state: Row | null = null, last: Row;
  for (let i = 0; i < 16; i++) { last = request('CREATE_CONTEXT', { context_id: 'context-' + i, actor: 'agent', scope: 'scope', purpose: 'INVESTIGATION', ceiling: [], initial_sources: [] }, state, 'create-' + i); const result = flowStep(last, pin); assert.equal(result.status, 'TRANSITION'); state = result.state; }
  const refused = flowStep(request('CREATE_CONTEXT', { context_id: 'overflow', actor: 'agent', scope: 'scope', purpose: 'INVESTIGATION', ceiling: [], initial_sources: [] }, state, 'overflow'), pin); assert.equal(refused.code, 'LIMIT_EXCEEDED'); assert.deepEqual(refused.state, state);
  const replay = response({ ...clone(last!), state, state_digest: digest('flow-state', state) }); assert.equal(flowStep(replay, pin).replay, true);
});
test('flow adapter can decline transitions while retaining ordinary authority evaluation', () => {
  const input = request('CREATE_CONTEXT', { context_id: 'agent', actor: 'agent', scope: 'scope', purpose: 'INVESTIGATION', ceiling: [], initial_sources: [] });
  const envelope = (operation: string, input: Row) => canonical({ protocol: 'seampoint.work-class.adapter/1.0.0-draft.3', request_id: 'disabled-flow', operation, input });
  const executed = spawnSync(process.execPath, ['adapter.ts'], { cwd: new URL('.', import.meta.url), input: envelope('capabilities', {}) + '\n' + envelope('flow-step', input) + '\n', env: { ...process.env, WORK_CLASS_ADAPTER_ROLES: 'AUTHORITY_EVALUATOR' }, encoding: 'utf8' });
  assert.equal(executed.status, 0, executed.stderr); const [capabilities, refused] = executed.stdout.trim().split('\n').map(row => JSON.parse(row).result);
  assert.equal(capabilities.roles.includes('FLOW_TRANSITIONS'), false); assert.equal(capabilities.operations.includes('flow-step'), false); assert.equal(capabilities.operations.includes('evaluate'), true); assert.deepEqual(refused, { status: 'REFUSED', code: 'ROLE_UNSUPPORTED', path: '' });
});

test('flow host requires a trusted authority authenticator and rejects caller supplied selection assertions', async () => {
  const config = configuration(), state = created(), input = read(state);
  await assert.rejects(() => new SingleProcessReferenceHost(pin).installFlow('org', config, input.event.clock, []), refuses('ACCESS_NOT_ESTABLISHED'));
  for (const proof of ['response_authority', 'access_authority']) {
    const host = new SingleProcessReferenceHost(pin, authenticateAuthority); await host.installFlow('org', config, input.event.clock, [], state, input.state_digest); await host.installFlowSource('org', 'bank', descriptor(), Buffer.from('secret'));
    const forged = clone(input); (proof === 'response_authority' ? forged.response_authority : forged.event.payload.access_authority).host_selection.selection_evidence = 'caller-selected-untrusted-root';
    if (proof !== 'response_authority') response(forged);
    assert.equal(flowStep(forged, pin).status, 'TRANSITION'); let calls = 0;
    const result = await host.submitFlow('org', forged, null, { context_id: 'agent', actor: 'agent', invoke: () => { calls++; } }); assert.deepEqual(result, { status: 'REFUSED', code: 'ACCESS_NOT_ESTABLISHED', path: '' }); assert.equal(calls, 0);
    const checkpoint = await host.exportCheckpoint({ org: [reader(state)] }); assert.equal(checkpoint.flows[0][1].state.core.claims.length, 0); assert.throws(() => SingleProcessReferenceHost.fromCheckpoint(pin, checkpoint), refuses('ACCESS_NOT_ESTABLISHED'));
  }
});
test('flow host reauthenticates the current reader after read delivery and retains the possible exposure', async () => {
  const config = configuration(), state = created(), input = read(state); let readerCurrent = true, calls = 0;
  const host = new SingleProcessReferenceHost(pin, (configuration, authority) => authenticateAuthority(configuration, authority) && (authority.proposal.executor.actor !== 'auditor' || readerCurrent));
  await host.installFlow('org', config, input.event.clock, [], state, input.state_digest); await host.installFlowSource('org', 'bank', descriptor(), Buffer.from('secret'));
  const result = await host.submitFlow('org', input, null, { context_id: 'agent', actor: 'agent', invoke: () => { calls++; readerCurrent = false; } });
  assert.deepEqual(result, { status: 'REFUSED', code: 'ACCESS_NOT_ESTABLISHED', path: '' }); assert.equal(calls, 1);
  readerCurrent = true; const after = flowStep(input, pin).state, checkpoint = await host.exportCheckpoint({ org: [reader(after)] }); assert.equal(checkpoint.flows[0][1].state.core.claims.length, 1); assert.equal(checkpoint.flow_deliveries[0][1].status, 'ESTABLISHED');
});

test('flow canonical input admission returns closed refusals before authentication', async () => {
  const state = flowStep(read(created()), pin).state;
  const input = request('MATERIALIZE', { context_id: 'agent', artifact_id: 'large', types: [{ id: 'Text', kind: 'STRING', unit: null, nonnegative: false }], fields: [{ name: 'body', value: { type_ref: 'Text', value: 'x'.repeat(16777216) } }] }, state);
  assert.ok(Buffer.byteLength(canonical(input)) > 16777216);
  assert.ok(Buffer.byteLength(canonical(input)) < FLOW_FRAME_BYTES);
  let authentications = 0;
  const host = new SingleProcessReferenceHost(pin, () => { authentications++; return true; });
  await host.installFlow('org', input.configuration, input.event.clock, [], state, input.state_digest);
  assert.deepEqual(await host.submitFlow('org', input), { status: 'REFUSED', code: 'LIMIT_EXCEEDED', path: '' });
  assert.equal(authentications, 0);
  assert.deepEqual(flowStep(input, pin), { status: 'REFUSED', code: 'LIMIT_EXCEEDED', path: '' });
  for (const malformed of [{ ...reader(null), unexpected: 1 }, { ...reader(null), schema: 1 }]) {
    assert.deepEqual(flowStep(malformed, pin), { status: 'REFUSED', code: 'SCHEMA_INVALID', path: '' });
  }
  const unicode = reader(null); unicode.response_authority.source.obligations[0].text = '\ud800';
  assert.deepEqual(flowStep(unicode, pin), { status: 'REFUSED', code: 'SCHEMA_INVALID', path: '' });
});

test('flow dispatch admits supplied input before separate reader sampling and authentication', async t => {
  let authentications = 0, readerCalls = 0, connectorCalls = 0;
  const row = await businessHost((configuration, input) => { authentications++; return authenticateAuthority(configuration, input); });
  const validReader = reader(row.before), readers = () => { readerCalls++; return [validReader]; };
  const connector = { ...row.connector, invoke: () => { connectorCalls++; } };
  const before = await row.host.exportCheckpoint({ org: readers });
  const oversized = clone(row.exposure); oversized.response_authority.source.obligations[0].text = '';
  oversized.response_authority.source.obligations[0].text = 'x'.repeat(16777217 - Buffer.byteLength(canonical(oversized)));
  assert.equal(Buffer.byteLength(canonical(oversized)), 16777217);
  const unicode = clone(row.exposure); unicode.response_authority.source.obligations[0].text = '\ud800';
  const cases = [
    { name: 'unexpected member', input: { ...clone(row.exposure), unexpected: true }, code: 'SCHEMA_INVALID' },
    { name: 'numeric schema', input: { ...clone(row.exposure), schema: 1 }, code: 'SCHEMA_INVALID' },
    { name: 'null input', input: null, code: 'SCHEMA_INVALID' },
    { name: 'false input', input: false, code: 'SCHEMA_INVALID' },
    { name: 'lone surrogate', input: unicode, code: 'SCHEMA_INVALID' },
    { name: 'oversized input', input: oversized, code: 'LIMIT_EXCEEDED' },
  ];
  for (const rowCase of cases) await t.test(rowCase.name, async () => {
    authentications = 0; readerCalls = 0;
    await assert.rejects(() => row.host.dispatchPermitted('org', 'instance', row.permit.permit_id, row.native, connector, undefined, null, rowCase.input as unknown as Row, readers), refuses(rowCase.code));
    assert.equal(readerCalls, 0); assert.equal(authentications, 0); assert.equal(connectorCalls, 0);
    assert.deepEqual(await row.host.exportCheckpoint({ org: readers }), before);
  });
});

test('flow reader guard admits every supplied reader before authenticating the first', async () => {
  let authentications = 0;
  const host = new SingleProcessReferenceHost(pin, (configuration, input) => { authentications++; return authenticateAuthority(configuration, input); });
  const first = reader(null), second = clone(first);
  second.configuration.principal = 'second-bank'; second.configuration.id = 'second-registry'; second.schema = 1;
  await host.installFlow('org', first.configuration, first.event.clock, []);
  await host.installFlow('org', second.configuration, second.event.clock, []);
  await assert.rejects(() => host.pendingEvidence('org', 'instance', [first, second]), refuses('ACCESS_NOT_ESTABLISHED'));
  assert.equal(authentications, 0);
});

test('flow projected state overflow preserves the exact prior state', () => {
  const state = flowStep(read(created()), pin).state;
  const payload = { context_id: 'agent', artifact_id: 'large', types: [{ id: 'Text', kind: 'STRING', unit: null, nonnegative: false }], fields: [{ name: 'body', value: { type_ref: 'Text', value: 'x'.repeat(9 * 1024 * 1024) } }] };
  const input = request('MATERIALIZE', payload, state);
  assert.ok(Buffer.byteLength(canonical(input)) < 16777216);
  assert.deepEqual(flowStep(input, pin), { status: 'REFUSED', code: 'LIMIT_EXCEEDED', path: '', state, state_digest: input.state_digest });
  const oversized = clone(state);
  oversized.core.artifacts.push({ id: 'large', context_id: 'agent', context_revision: '2', context_digest: digest('flow-context', state.core.contexts[0]), types: payload.types, fields: payload.fields, restrictions: ['SAR'], origins: state.core.contexts[0].origins });
  oversized.core.artifacts.push({ ...clone(oversized.core.artifacts[0]), id: 'large-copy' });
  assert.ok(Buffer.byteLength(canonical(oversized)) > 16777216);
  assert.throws(() => admitFlowState(configuration(), oversized, digest('flow-state', oversized), pin), refuses('LIMIT_EXCEEDED'));
});

test('flow control authority byte boundary applies to every optional presence and control role', () => {
  const padded = (input: Row, bytes: number, presence: number): Row => {
    if (presence & 1) input.flow_bases = [];
    if (presence & 2) input.envelope.flow_requirements = [];
    input.source.obligations[0].text = ''; reseal(input);
    input.source.obligations[0].text = 'x'.repeat(bytes - Buffer.byteLength(canonical(input))); reseal(input);
    assert.equal(Buffer.byteLength(canonical(input)), bytes); return input;
  };
  let importedState = flowStep(read(created()), pin).state;
  importedState = flowStep(request('MATERIALIZE', { context_id: 'agent', artifact_id: 'summary', types: [], fields: [] }, importedState), pin).state;
  importedState = created('receiver', importedState);
  for (let presence = 0; presence < 4; presence++) for (const bytes of [1048576, 1048577]) for (const role of ['response', 'read', 'import-access', 'import-transfer']) {
    let input: Row;
    if (role === 'response') { input = reader(null); input.response_authority = padded(input.response_authority, bytes, presence); }
    else {
      input = role === 'read' ? read(created()) : request('IMPORT', { sender_context_id: 'agent', receiver_context_id: 'receiver', artifact_id: 'summary', intent_id: 'import-intent', claim_id: 'import-claim' }, importedState);
      const member = role === 'import-transfer' ? 'transfer_authority' : 'access_authority';
      input.event.payload[member] = padded(input.event.payload[member], bytes, presence); response(input);
    }
    const result = flowStep(input, pin);
    assert.equal(result.status, bytes === 1048576 ? 'TRANSITION' : 'REFUSED', `${role}/${presence}/${bytes}: ${JSON.stringify({ status: result.status, code: result.code })}`);
    if (bytes > 1048576) {
      assert.equal(result.code, 'LIMIT_EXCEEDED');
      if (role === 'response') assert.deepEqual(Object.keys(result).sort(), ['code', 'path', 'status']);
      else { assert.deepEqual(result.state, input.state); assert.equal(result.state_digest, input.state_digest); }
    }
  }
});

test('flow restore requires every retained authority registry and preserves its historical prefix', async () => {
  const row = await businessHost(), checkpoint = await row.host.exportCheckpoint({ org: [reader(row.before)] });
  const stripped = clone(checkpoint);
  for (const member of ['flows', 'flow_routes', 'flow_clocks', 'flow_sources', 'flow_deliveries']) stripped[member] = [];
  assert.throws(() => SingleProcessReferenceHost.fromCheckpoint(pin, stripped), refuses('STATE_INVALID'));
  const wrongKey = clone(checkpoint); wrongKey.flows[0][0] = canonical(['other-org', 'bank']);
  assert.throws(() => SingleProcessReferenceHost.fromCheckpoint(pin, wrongKey, authenticateAuthority), refuses('STATE_INVALID'));
  const earlier = clone(checkpoint); earlier.flows[0][1].state = created(); earlier.flows[0][1].state_digest = digest('flow-state', earlier.flows[0][1].state);
  assert.throws(() => SingleProcessReferenceHost.fromCheckpoint(pin, earlier, authenticateAuthority), refuses('STATE_INVALID'));
  const advanced = created('later-context', row.before), current = clone(checkpoint);
  current.flows[0][1].state = advanced; current.flows[0][1].state_digest = digest('flow-state', advanced);
  const restored = SingleProcessReferenceHost.fromCheckpoint(pin, current, authenticateAuthority);
  await assert.rejects(() => restored.snapshot('org', 'instance'), refuses('ACCESS_NOT_ESTABLISHED'));
  assert.equal((await restored.snapshot('org', 'instance', [reader(advanced)])).state_digest, checkpoint.roots[0][1].state_digest);
});

export { authority as flowTestAuthority, configuration as flowTestConfiguration, request as flowTestRequest, response as flowTestResponse };
