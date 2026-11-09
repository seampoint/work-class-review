import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { aggregateStep } from './reservations.ts';
import { byteCompare, canonical, digest } from './canonical.ts';
import { validateAuthorityDefinition } from './authority.ts';
import { predicateFaults, predicateTypes } from './values.ts';
import type { RecordValue as Row, Types } from './values.ts';

const candidate = new URL('../', import.meta.url);
const index = JSON.parse(readFileSync(new URL('cases/index.json', candidate), 'utf8')).cases as Row[];
const input = (id: string): Row => JSON.parse(readFileSync(new URL(index.find(row => row.id === id)!.path, candidate), 'utf8')).input;
const step = (id: string, mutate: (value: Row) => void = () => {}): Row => {
  const value = input(id); mutate(value);
  return aggregateStep(value, value.specification_pin);
};

// Predicate static admission: every branch and operand is checked, and the
// refusal is chosen by phase, never by branch, operand or connective order.
const types: Types = new Map([
  ['IDENTITY', { id: 'IDENTITY', kind: 'IDENTITY', unit: null, nonnegative: false }],
  ['count', { id: 'count', kind: 'INTEGER', unit: null, nonnegative: false }],
]);
const fields = new Map([['beneficiary', 'IDENTITY'], ['quantity', 'count']]);
const literal = (type_ref: string, value: string): Row => ({ kind: 'LITERAL', value: { type_ref, value } });
const field = (name: string): Row => ({ kind: 'FIELD', name });
const referenceFault: Row = { kind: 'EQUAL', left: literal('zz-unknown', 'x'), right: literal('zz-unknown', 'x') };
const typeFault: Row = { kind: 'COMPARE', operator: 'LT', left: field('beneficiary'), right: literal('IDENTITY', 'employee-7') };
const codes = (node: Row): string[] => [...predicateFaults(node, fields, types)].sort();

test('predicate faults accumulate across every branch regardless of order or connective', () => {
  for (const node of [
    { kind: 'ALL', operands: [referenceFault, typeFault] },
    { kind: 'ANY', operands: [typeFault, referenceFault] },
    { kind: 'NOT', operand: { kind: 'ALL', operands: [referenceFault, typeFault] } },
    { kind: 'ALL', operands: [{ kind: 'NOT', operand: referenceFault }, { kind: 'NOT', operand: typeFault }] },
    { kind: 'ANY', operands: [{ kind: 'BOOLEAN', value: true }, referenceFault, typeFault] },
  ]) {
    assert.deepEqual(codes(node), ['REFERENCE_INVALID', 'TYPE_INVALID']);
    assert.throws(() => predicateTypes(node, fields, types), { code: 'TYPE_INVALID' });
  }
  assert.deepEqual(codes(referenceFault), ['REFERENCE_INVALID']);
  assert.deepEqual(codes(typeFault), ['TYPE_INVALID']);
});

test('an undeclared FIELD operand is REFERENCE_INVALID and does not hide a type fault', () => {
  const undeclared: Row = { kind: 'EQUAL', left: field('zz-undeclared-field'), right: literal('IDENTITY', 'employee-7') };
  assert.deepEqual(codes(undeclared), ['REFERENCE_INVALID']);
  assert.deepEqual(codes({ kind: 'ALL', operands: [undeclared, typeFault] }), ['REFERENCE_INVALID', 'TYPE_INVALID']);
});

test('a known operand that alone violates its operator rule is TYPE_INVALID beside an unknown type', () => {
  // COMPARE over a known IDENTITY operand fails on that operand alone.
  assert.deepEqual(codes({ kind: 'COMPARE', operator: 'LT', left: field('beneficiary'), right: literal('zz-unknown', '1') }), ['REFERENCE_INVALID', 'TYPE_INVALID']);
  // A known INTEGER operand is fine alone; the mismatch would depend on the unknown type.
  assert.deepEqual(codes({ kind: 'COMPARE', operator: 'LT', left: field('quantity'), right: literal('zz-unknown', '1') }), ['REFERENCE_INVALID']);
  assert.deepEqual(codes({ kind: 'EQUAL', left: field('beneficiary'), right: literal('zz-unknown', 'x') }), ['REFERENCE_INVALID']);
  assert.deepEqual(codes({ kind: 'MEMBER', value: field('beneficiary'), members: [{ type_ref: 'zz-unknown', value: 'x' }] }), ['REFERENCE_INVALID']);
  assert.deepEqual(codes({ kind: 'MEMBER', value: field('beneficiary'), members: [{ type_ref: 'count', value: '1' }] }), ['TYPE_INVALID']);
});

test('authority definition admission picks TYPE_INVALID over a reference fault in the same predicate tree', () => {
  const definition = JSON.parse(Buffer.from(input('C3-P3-PRED-005').artifact_bytes_base64, 'base64').toString('utf8'));
  assert.equal(validateAuthorityDefinition(definition).code, 'TYPE_INVALID');
  const condition = definition.envelope.conditions[0];
  condition.predicate = { ...condition.predicate, operands: [...condition.predicate.operands].reverse() };
  assert.equal(validateAuthorityDefinition(definition).code, 'TYPE_INVALID');
  condition.predicate = condition.predicate.operands.find((row: Row) => row.kind === 'EQUAL');
  assert.equal(validateAuthorityDefinition(definition).code, 'REFERENCE_INVALID');
});

test('RENEW of a SETTLED or RELEASED reservation is INPUT_INVALID admission, ahead of OCCURRENCE_CONFLICT', () => {
  for (const id of ['C3-P3-RENEW-001', 'C3-P3-RENEW-002', 'C3-P3-RENEW-003', 'C3-P3-RENEW-006', 'C3-P3-RENEW-010']) {
    const result = step(id);
    assert.equal(result.status, 'REFUSED', id);
    assert.equal(result.code, 'INPUT_INVALID', id);
    assert.equal(result.receipt, undefined, id);
  }
  // History, authentication and type admission still come first.
  assert.equal(step('C3-P3-RENEW-004').code, 'EVIDENCE_UNAVAILABLE');
  assert.equal(step('C3-P3-RENEW-005').code, 'TYPE_INVALID');
  // An OPEN target renews; a DISPUTED target stays an admitted WITHHELD decision.
  assert.equal(step('C3-P3-RENEW-011').receipt.decision, 'RENEWED');
  const disputed = step('C2-renew-disputed-reservation-withheld').receipt;
  assert.equal(disputed.decision, 'WITHHELD');
  assert.deepEqual(disputed.reasons, ['EXPOSURE_DISPUTED']);
  assert.deepEqual(disputed.budgets, []);
});

test('a history retracting a SETTLED prescribed record disputes it, restores its charge and blocks its partitions', () => {
  for (const id of ['C3-P3-ALIAS-016', 'C3-P3-ALIAS-017']) {
    const result = step(id);
    assert.equal(result.receipt.decision, 'WITHHELD', id);
    assert.deepEqual(result.receipt.reasons, ['EXPOSURE_DISPUTED', 'HISTORY_UNCORROBORATED', 'RECOVERY_EVIDENCE_INCOMPLETE'], id);
    assert.equal(result.receipt.reservation, null, id);
    assert.deepEqual(result.receipt.budgets, [], id);
    const [reservation] = result.state.core.reservations;
    assert.equal(reservation.status, 'DISPUTED', id);
    assert.equal(reservation.matched_effect, 'effect-1', id);
    assert.deepEqual(result.state.core.effects.map((row: Row) => row.disposition), ['MATCHED'], id);
  }
  // An unrelated partition is not blocked by the disputed reservation.
  const unrelated = step('C3-P3-ALIAS-018');
  assert.equal(unrelated.receipt.decision, 'RESERVED');
  assert.equal(unrelated.state.core.reservations.find((row: Row) => row.id === 'reserve-a').status, 'DISPUTED');
});

// Host evidence authenticates exactly the supplied history and native bodies.
const authenticate = (event: Row, host: Row): Row => {
  const records = event.payload.histories.map((history: Row) => ({ kind: 'HISTORY', record_digest: digest('budget-history', history), provider: history.provider, source: history.source }));
  if (event.payload.native) records.push({ kind: 'NATIVE_OUTCOME', record_digest: digest('reservation-native-outcome', event.payload.native), provider: event.payload.native.provider, source: event.payload.native.source });
  return { ...host, authenticated_records: records.sort((a: Row, b: Row) => byteCompare(canonical(a), canonical(b))) };
};

test('a foreign EFFECT stays unassessed; an UNKNOWN native outcome still evaluates the bound', () => {
  // Prior state: reserve-a SETTLED against opening 800 plus its committed 150.
  const base = input('C3-P3-ALIAS-016'), settle = base.state.receipts.at(-1).event, pin = base.specification_pin;
  const settledHistory = structuredClone(settle.payload.histories[0]);
  // A settlement for an unknown reservation is retained as a DISPUTED effect
  // whose blocked_partitions entry blocks the whole anchor.
  const foreign: Row = structuredClone(settle);
  Object.assign(foreign, { id: 'settle-foreign', expected_revision: base.state.core.revision, clock: structuredClone(base.event.clock) });
  Object.assign(foreign.payload.native, { id: 'native-foreign', reservation: 'reserve-ghost', effect_id: 'effect-foreign', evidence_ref: 'evidence-foreign' });
  for (const actual of [true, false]) {
    const observed = structuredClone(foreign);
    if (!actual) Object.assign(observed.payload.native, { outcome: 'UNKNOWN', effect_id: null, occurred_at: null, observed_request: null, actual_fields: [] });
    const disputed = aggregateStep({ ...base, event: observed, host_evidence: authenticate(observed, base.host_evidence) }, pin);
    assert.equal(disputed.receipt.decision, 'EFFECT_DISPUTED');
    assert.deepEqual(disputed.state.core.effects.find((row: Row) => row.id === 'native-foreign').blocked_partitions, [{ anchor: 'license-spend', key: null }]);
    assert.equal(disputed.state.core.reservations[0].status, 'SETTLED');
    const reserve: Row = structuredClone(base.event);
    reserve.expected_revision = disputed.state.core.revision; reserve.payload.histories = [settledHistory];
    const blocked = aggregateStep({ ...base, state: disputed.state, state_digest: disputed.state_digest, event: reserve, host_evidence: authenticate(reserve, base.host_evidence) }, pin);
    assert.equal(blocked.receipt.decision, 'WITHHELD');
    assert.equal(blocked.receipt.reservation, null);
    if (actual) {
      assert.deepEqual(blocked.receipt.reasons, ['EXPOSURE_DISPUTED', 'RECOVERY_EVIDENCE_INCOMPLETE']);
      assert.deepEqual(blocked.receipt.budgets, []);
    } else {
      assert.deepEqual(blocked.receipt.reasons, ['BOUND_VIOLATED', 'EXPOSURE_DISPUTED']);
      assert.equal(blocked.receipt.budgets[0].result.status, 'VIOLATED');
      assert.equal(blocked.receipt.budgets[0].result.partitions[0].accumulator.value, '1100');
    }
  }
});

// M1: a returned act must name a declared channel and a declared provider.
test('a return naming an undeclared channel or provider is DEPENDENCY_MISMATCH', async () => {
  const { evaluateAuthority } = await import('./authority.ts');
  const { selectedCandidate } = await import('./schema.ts');
  const request = (input('C3-ASMT-001') as Row).request as Row;
  assert.equal(evaluateAuthority(structuredClone(request), selectedCandidate()).status, 'READY_FOR_RESERVATION');
  for (const [key, value] of [['channel', 'undeclared-channel'], ['provider', 'undeclared-provider']] as const) {
    const changed = structuredClone(request), original = changed.returns[0] as Row;
    const record: Row = { ...original, [key]: value }, before = digest('authority-return', original), after = digest('authority-return', record);
    changed.returns[0] = record;
    for (const row of changed.host_selection.authenticated_records as Row[]) {
      if (row.kind === 'RETURN' && row.record_digest === before) Object.assign(row, { record_digest: after, provider: record.provider, channel: record.channel });
    }
    (changed.host_selection.authenticated_records as Row[]).sort((a, b) => byteCompare(canonical(a), canonical(b)));
    const result = evaluateAuthority(changed, selectedCandidate());
    assert.deepEqual([result.status, result.code], ['REFUSED', 'DEPENDENCY_MISMATCH'], key);
  }
});
