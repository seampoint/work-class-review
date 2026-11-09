import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { step } from './lifecycle.ts';
import { evaluateAuthority } from './authority.ts';
import { activeHolding, admitHoldingsDispatch, admitHoldingsState, holdingsActor, holdingsStep } from './holdings.ts';
import { immutableAuthority } from './dispatch-authority.ts';
import { selectedCandidate, VERSION } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const pin = selectedCandidate(), at = '2026-09-10T04:00:00Z';
function source(id: string): Row { return JSON.parse(readFileSync(new URL('../cases/holdings/C3-HOLD-' + id + '.json', import.meta.url), 'utf8')); }
const clone = <T>(value: T): T => structuredClone(value);
function request(kind: string, payload: Row, state: Row | null = null, clock = at, id = 'event-' + (state?.core.revision ?? '0')): Row {
  const configuration = clone(source('001').input.configuration), configurationDigest = digest('holdings-configuration', configuration);
  const event: Row = { schema: VERSION + '/holdings-event', id, expected_revision: state?.core.revision ?? '0', expected_state_digest: state === null ? null : digest('holdings-state', state), clock: { source: configuration.clock_source, status: 'AVAILABLE', instant: clock }, administration: null, kind, payload };
  const basis = { id: 'administrator', configuration_digest: configurationDigest, principal: configuration.principal, role: configuration.administration_role, actor: 'registry-admin', actor_kind: 'HUMAN', allowed_operations: ['GRANT', 'INITIALIZE', 'REVOKE'], provider: configuration.provider, source: configuration.source, observed_at: clock, valid_from: '2026-09-01T00:00:00Z', valid_until: null, revoked_at: null, evidence_ref: 'designation-evidence' };
  const projection = clone(event); delete projection.administration;
  const act = { id: 'administration-' + id, basis_id: basis.id, actor: basis.actor, principal: basis.principal, role: basis.role, kind, subject_digest: digest('holdings-administration-subject', { configuration_digest: configurationDigest, event: projection }), occurred_at: clock, status: 'ACCEPTED' };
  const returned = { actor: act.actor, provider: configuration.provider, source: configuration.source, channel: configuration.protected_channel, observed_at: clock, act_digest: digest('holdings-administration-act', act), act_bytes_base64: Buffer.from(canonical(act)).toString('base64'), evidence_ref: 'returned-act', provenance_digest: digest('test-provenance', { id }) };
  event.administration = { basis, act, return: returned };
  const authenticated_records = [ { kind: 'ADMIN_BASIS', record_digest: digest('holdings-administration-basis', basis), provider: configuration.provider, source: configuration.source, channel: null }, { kind: 'ADMIN_RETURN', record_digest: digest('holdings-administration-return', returned), provider: configuration.provider, source: configuration.source, channel: configuration.protected_channel } ].sort((a, b) => byteCompare(canonical(a), canonical(b)));
  return { schema: VERSION + '/holdings-input', specification_pin: pin, configuration, state, state_digest: state === null ? null : digest('holdings-state', state), event, host_evidence: { configuration_digest: configurationDigest, selection_evidence: 'selected-designation', authenticated_records, seed_inventory: kind === 'INITIALIZE' ? { inventory_digest: digest('holdings-seed-inventory', payload.grants), evidence_ref: 'complete-inventory' } : null } };
}
function initialized(): Row { const result = holdingsStep(request('INITIALIZE', { grants: [] }), pin); assert.equal(result.status, 'TRANSITION'); return result.state; }
function error(code: string): (value: unknown) => boolean { return value => value instanceof AdmissionError && value.code === code; }

export { request as holdingsTestRequest, source as holdingsSourceCase };

test('holdings initialization requires exact complete human administration and seed evidence', () => {
  const input = request('INITIALIZE', { grants: [] });
  assert.equal(holdingsStep(input, pin).receipt.decision, 'INITIALIZED');
  const missing = clone(input); missing.host_evidence.seed_inventory = null;
  assert.equal(holdingsStep(missing, pin).code, 'EVIDENCE_UNAVAILABLE');
  const untrusted = clone(input); untrusted.host_evidence.authenticated_records = [];
  assert.equal(holdingsStep(untrusted, pin).code, 'EVIDENCE_UNAVAILABLE');
  const wrong = clone(input); wrong.event.administration.act.subject_digest = digest('wrong', {});
  assert.equal(holdingsStep(wrong, pin).code, 'DEPENDENCY_MISMATCH');
});

test('holdings grants serialize conflicts and no-op grants do not extend an existing grant', () => {
  const state = initialized(), configuration = source('001').input.configuration, pair = configuration.conflicts[0];
  const first = holdingsStep(request('GRANT', { grant_id: 'grant-a', actor: 'holder', permission: pair.left, valid_until: '2026-09-11T00:00:00Z' }, state), pin);
  assert.equal(first.receipt.decision, 'GRANTED');
  const same = holdingsStep(request('GRANT', { grant_id: 'grant-b', actor: 'holder', permission: pair.left, valid_until: null }, first.state), pin);
  assert.equal(same.receipt.decision, 'UNCHANGED'); assert.equal(same.state.core.grants.length, 1); assert.equal(same.state.core.grants[0].valid_until, '2026-09-11T00:00:00Z');
  const excluded = holdingsStep(request('GRANT', { grant_id: 'grant-c', actor: 'holder', permission: pair.right, valid_until: null }, same.state), pin);
  assert.equal(excluded.receipt.decision, 'WITHHELD'); assert.deepEqual(excluded.receipt.reasons, ['CONFLICTING_HOLDING']); assert.equal(excluded.state.core.revision, '4');
});

test('holdings revocation is exact, exclusive and does not remove a later regrant', () => {
  const permission = source('001').input.configuration.permissions[0];
  const first = holdingsStep(request('GRANT', { grant_id: 'first', actor: 'holder', permission, valid_until: null }, initialized()), pin);
  const revoked = holdingsStep(request('REVOKE', { grant_id: 'first', actor: 'holder', permission }, first.state), pin);
  assert.equal(revoked.receipt.decision, 'REVOKED'); assert.equal(activeHolding(revoked.state.core.grants[0], at), false);
  const later = holdingsStep(request('GRANT', { grant_id: 'later', actor: 'holder', permission, valid_until: null }, revoked.state), pin);
  const old = holdingsStep(request('REVOKE', { grant_id: 'first', actor: 'holder', permission }, later.state), pin);
  assert.equal(old.receipt.decision, 'UNCHANGED'); assert.equal(activeHolding(old.state.core.grants.find((row: Row) => row.id === 'later'), at), true);
});

test('holdings exact replay precedes fresh clock and administrator validity checks', () => {
  const input = request('INITIALIZE', { grants: [] }), first = holdingsStep(input, pin);
  const replay: Row = { ...clone(input), state: first.state, state_digest: first.state_digest };
  const result = holdingsStep(replay, pin);
  assert.equal(result.replay, true); assert.equal(result.state.core.revision, '1');
  const changed = clone(replay); changed.host_evidence.selection_evidence = 'different';
  assert.equal(holdingsStep(changed, pin).code, 'REPLAY_CONFLICT');
});

test('holdings rehashed altered historical receipt fails complete reconstruction', () => {
  const state = initialized(); state.records[0].receipt.decision = 'GRANTED';
  state.records[0].receipt_digest = digest('holdings-receipt', state.records[0].receipt);
  assert.throws(() => admitHoldingsState(source('001').input.configuration, state, digest('holdings-state', state), pin), error('STATE_INVALID'));
});

test('holdings malformed historical administration cannot become current authority', () => {
  const state = initialized(); state.records[0].event.administration.return.act_bytes_base64 = 'AAAA';
  assert.throws(() => admitHoldingsState(source('001').input.configuration, state, digest('holdings-state', state), pin), error('STATE_INVALID'));
});

test('holdings current authority binds complete state and records exact holding checks', () => {
  const row = source('068'); assert.deepEqual(evaluateAuthority(row.input.request, pin), row.expected);
  const invalid = clone(row.input.request); invalid.holdings_bases[0].state_digest = digest('wrong', {});
  assert.equal(evaluateAuthority(invalid, pin).code, 'DIGEST_MISMATCH');
});

test('holdings missing and stale current selections withhold independently of historical permission', () => {
  const input = clone(source('068').input.request); input.holdings_bases = [];
  assert.deepEqual(evaluateAuthority(input, pin).reasons, ['HOLDINGS_UNAVAILABLE']);
  const stale = clone(source('068').input.request); stale.holdings_bases[0].selection.at = '2026-09-10T03:59:59Z';
  assert.deepEqual(evaluateAuthority(stale, pin).reasons, ['HOLDINGS_STALE']);
});

test('holdings supplied admission failures use fixed phase2 precedence across registry order', () => {
  const input = clone(source('068').input.request), wrong = clone(input.holdings_bases[0]);
  wrong.state_digest = digest('wrong-state', {});
  const dependency = clone(wrong); dependency.state.core.configuration_digest = digest('wrong-configuration', {});
  for (const bases of [[wrong, dependency], [dependency, wrong]]) { input.holdings_bases = bases; assert.equal(evaluateAuthority(input, pin).code, 'DEPENDENCY_MISMATCH'); }
});

test('holdings refresh changes only evidence and keeps envelope inventory immutable', () => {
  const first = clone(source('068').input.request), fresh = clone(first);
  fresh.holdings_bases = []; assert.deepEqual(immutableAuthority(first), immutableAuthority(fresh));
  fresh.envelope.holdings_requirements = []; assert.notDeepEqual(immutableAuthority(first), immutableAuthority(fresh));
});

test('holdings gate actor selects admitted gate kind and role rather than another ordinary actor', () => {
  const input = source('068').input.request, requirement = { ...input.envelope.holdings_requirements[0], actor: 'GATE_ACTOR' };
  const kind = input.envelope.gate.kind === 'DECIDE' ? 'INSTANCE_DECISION' : 'VERIFY';
  assert.equal(holdingsActor(input, requirement), input.acts.find((row: Row) => row.kind === kind && row.role === input.envelope.gate.role)?.actor);
});

test('holdings lifecycle gate and combined projection limits precede permit issuance', () => {
  const input = source('068').input.request;
  assert.throws(() => admitHoldingsDispatch(input, {}), error('UNSUPPORTED_RELATION'));
  assert.throws(() => admitHoldingsDispatch(input, { dispatch_gate: { kind: 'SOURCE_REQUIREMENTS', requirements: Array.from({ length: 64 }, (_, id) => 'source-' + id) } }), error('LIMIT_EXCEEDED'));
});


test('holdings retained permits reconstruct the source gate and combined projection bound', () => {
  const fixture = JSON.parse(readFileSync(new URL('./test-data/holdings-retained-checkpoints.json', import.meta.url), 'utf8'));
  assert.equal(fixture.candidate_pin, pin);
  for (const row of fixture.rows) assert.deepEqual(step(row.input, pin), row.expected, row.id);
});
