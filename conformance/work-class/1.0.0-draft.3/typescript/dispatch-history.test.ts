import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { byteCompare, digest } from './canonical.ts';
import { checkpointBefore, stateDigest, step } from './lifecycle.ts';
import { VERSION } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);
const index = JSON.parse(readFileSync(new URL('cases/index.json', candidate), 'utf8')).cases as Row[];
const source = (id: string): Row => JSON.parse(readFileSync(new URL(index.find(row => row.id === id)!.path, candidate), 'utf8')).input;
const omit = (row: Row, name: string): Row => Object.fromEntries(Object.entries(row).filter(([key]) => key !== name));

function advance(request: Row, event: Row): Row {
  request.event = { ...structuredClone(event), instance_id: request.state.instance_id,
    expected_state_revision: request.state.revision, expected_state_digest: request.state_digest };
  const result = step(request, request.specification_pin);
  assert.equal(result.status, 'STEP', JSON.stringify({ event: event.event_id, code: result.code }));
  request.state = result.state; request.state_digest = result.state_digest;
  const replay = step(request, request.specification_pin);
  assert.equal(replay.status, 'STEP', JSON.stringify({ event: event.event_id, code: replay.code }));
  assert.equal(replay.replay, true);
  return result;
}

function retainedEvent(state: Row, row: Row, receipt: Row): Row {
  return { schema: VERSION + '/runtime-event', kind: 'DISPATCH_OBSERVED', event_id: row.event_id,
    instance_id: state.instance_id, expected_state_revision: String(BigInt(receipt.sequence) - 1n),
    expected_state_digest: receipt.state_before_digest, permit: state.permits.find((permit: Row) => permit.permit_id === row.permit_digest),
    native_request: row.native_request, connector: row.connector, attempt: row.attempt,
    acknowledgement: row.acknowledgement, clock_revision: row.clock_revision,
    ...(row.authorization_digest === undefined ? {} : { authorization_digest: row.authorization_digest }) };
}

function requestDigest(state: Row, row: Row): string {
  const permit = state.permits.find((permit: Row) => permit.permit_id === row.permit_digest);
  return digest('dispatch-native-request', { instance_id: state.instance_id,
    occurrence_id: permit.occurrence.occurrence_id, ...row.native_request });
}

function forge(request: Row, mutate: (row: Row, receipt: Row) => void, mutateEvent?: (event: Row) => void): void {
  const state = request.state, receipt = state.receipts.findLast((receipt: Row) => receipt.event_kind === 'DISPATCH_OBSERVED');
  const row = state.dispatches.find((row: Row) => row.event_id === receipt.event_id);
  mutate(row, receipt);
  const event = retainedEvent(state, row, receipt);
  mutateEvent?.(event);
  row.dispatch_attempt_digest = digest('dispatch-attempt', { permit_id: row.permit_digest,
    native_request: row.native_request, connector: row.connector, attempt: row.attempt });
  row.event_digest = digest('runtime-event', event);
  row.dispatch_digest = digest('dispatch', omit(row, 'dispatch_digest'));
  state.dispatches.sort((a: Row, b: Row) => byteCompare(a.dispatch_digest, b.dispatch_digest));
  receipt.event_digest = row.event_digest;
  const core = structuredClone(state); core.receipts = []; core.replays = [];
  state.receipts.at(-1).state_after_core_digest = digest('work-state-core', core);
  for (const receipt of state.receipts) {
    receipt.decision_id = digest('decision-receipt', omit(receipt, 'decision_id'));
    const replay = state.replays.find((row: Row) => row.event_id === receipt.event_id);
    replay.event_digest = receipt.event_digest; replay.decision = structuredClone(receipt);
    replay.decision_receipt_digest = receipt.decision_id; replay.transition_state_digest = receipt.state_after_core_digest;
    replay.transaction_digest = digest('lifecycle-transaction', { state_before_digest: receipt.state_before_digest,
      event_digest: receipt.event_digest, decision_receipt_digest: receipt.decision_id,
      state_after_core_digest: receipt.state_after_core_digest, budget_results: replay.budget_results });
  }
  request.state_digest = stateDigest(state); request.event = event;
}

function sent(): Row {
  const request = source('D2-022'); advance(request, request.event); return request;
}

function invalid(request: Row): void {
  const result = step(request, request.specification_pin);
  assert.equal(result.status, 'REFUSED'); assert.equal(result.code, 'STATE_INVALID');
}

test('restart rejects a coherently rehashed amount151 dispatch with a clean amount150 receipt', () => {
  const request = sent();
  forge(request, row => {
    row.native_request.fields.find((field: Row) => field.name === 'amount').value.value = '151';
    row.attempt.request_digest = requestDigest(request.state, row);
  });
  invalid(request);
});

for (const [name, mutate] of [
  ['request digest', (row: Row) => { row.attempt.request_digest = digest('wrong-request', {}); }],
  ['connector binding', (row: Row) => { row.connector.binding_digest = digest('wrong-connector', {}); }],
  ['attempt before issuance', (row: Row) => { row.attempt.attempted_at = '2026-09-10T04:29:59Z'; }],
  ['attempt after selected clock', (row: Row) => { row.attempt.attempted_at = '2026-09-10T04:30:01Z'; }],
  ['acknowledgement before attempt', (row: Row) => { row.acknowledgement = { status: 'ACCEPTED', reference: 'early', observed_at: '2026-09-10T04:29:59Z' }; }],
  ['invented reason', (_row: Row, receipt: Row) => { receipt.reason_codes = ['PERMIT_EXPIRED']; receipt.details[0].reasons = receipt.reason_codes; }],
  ['forged disposition', (_row: Row, receipt: Row) => { receipt.disposition = 'ACKNOWLEDGED'; }],
] as [string, (row: Row, receipt: Row) => void][]) {
  test(`restart rejects rehashed dispatch history with ${name}`, () => {
    const request = sent(); forge(request, mutate); invalid(request);
  });
}

test('restart reconstructs the complete original dispatch event header', () => {
  const request = sent(); forge(request, () => {}, event => { event.expected_state_revision = '999'; }); invalid(request);
});

test('restart rejects a retained dispatch bound to an earlier available clock', () => {
  const request = source('D2-022'), dispatch = structuredClone(request.event);
  advance(request, { schema: VERSION + '/runtime-event', kind: 'CLOCK', event_id: 'restart-clock-2',
    clock: { ...request.state.clocks[0], revision: '2', evidence_digest: digest('clock-2', {}) }, activation_clocks: [] });
  dispatch.clock_revision = '2'; advance(request, dispatch);
  forge(request, row => { row.clock_revision = '1'; }); invalid(request);
});

for (const attempt of ['NOT_SENT', 'SENT', 'REJECTED', 'UNKNOWN']) for (const acknowledgement of ['NONE', 'ACCEPTED', 'REJECTED', 'UNKNOWN']) {
  test(`restart retains matching ${attempt}/${acknowledgement} dispatch classification`, () => {
    const request = source('D2-022'), event = request.event;
    event.attempt.status = attempt;
    event.acknowledgement = acknowledgement === 'NONE'
      ? { status: 'NONE', reference: null, observed_at: null }
      : { status: acknowledgement, reference: 'matching-ack', observed_at: event.attempt.attempted_at };
    advance(request, event);
  });
}

test('restart retains an honestly disputed changed request and rejects erased disqualifiers', () => {
  const request = source('D2-022'), event = request.event;
  event.native_request.fields.find((field: Row) => field.name === 'amount').value.value = '151';
  event.attempt.request_digest = digest('dispatch-native-request', { instance_id: request.state.instance_id,
    occurrence_id: event.permit.occurrence.occurrence_id, ...event.native_request });
  const result = advance(request, event);
  assert.equal(result.decision.disposition, 'DISPUTED');
  assert.deepEqual(result.decision.reason_codes, ['NATIVE_ARGUMENT_MISMATCH']);
  forge(request, (_row, receipt) => { receipt.reason_codes = []; receipt.details[0].reasons = []; }); invalid(request);
});

test('restart retains a safe NOT_SENT retry and marks a fresh consumed-permit send disputed', () => {
  const request = source('D2-022'), event = structuredClone(request.event);
  event.attempt.status = 'NOT_SENT'; advance(request, event);
  event.event_id = 'restart-retry'; event.attempt.attempt_id = 'restart-retry-attempt'; event.attempt.status = 'SENT';
  const retry = advance(request, event); assert.equal(retry.decision.disposition, 'DISPATCH_RECORDED');
  event.event_id = 'restart-consumed'; event.attempt.attempt_id = 'restart-consumed-attempt';
  const consumed = advance(request, event);
  assert.equal(consumed.decision.disposition, 'DISPUTED');
  assert.deepEqual(consumed.decision.reason_codes, ['LATE_OR_PROHIBITED_DISPATCH']);
  forge(request, (_row, receipt) => { receipt.disposition = 'DISPATCH_RECORDED'; receipt.reason_codes = []; receipt.details[0].reasons = []; });
  invalid(request);
});

test('restart retains an observed expired send with its exact disqualifier', () => {
  const request = source('D2-022'), event = structuredClone(request.event);
  advance(request, { schema: VERSION + '/runtime-event', kind: 'CLOCK', event_id: 'restart-expiry-clock',
    clock: { ...request.state.clocks[0], revision: '2', observed_time: event.permit.expires_at,
      evidence_digest: digest('expiry-clock', {}) }, activation_clocks: [] });
  event.clock_revision = '2'; event.attempt.attempted_at = event.permit.expires_at;
  const result = advance(request, event);
  assert.equal(result.decision.disposition, 'DISPUTED'); assert.deepEqual(result.decision.reason_codes, ['PERMIT_EXPIRED']);
  forge(request, (_row, receipt) => { receipt.reason_codes = []; receipt.details[0].reasons = []; }); invalid(request);
});

test('restart retains an expired superseded send instead of discarding its evidence', () => {
  const request = source('D2-175'); request.event.attempt.status = 'SENT';
  const result = advance(request, request.event);
  assert.equal(result.decision.disposition, 'DISPUTED');
  assert.deepEqual(result.decision.reason_codes, ['PERMIT_EXPIRED', 'PERMIT_SUPERSEDED']);
});

test('acknowledgement after unknown effect preserves occurrence status on restart', () => {
  const request = sent(), first = structuredClone(request.event), row = request.state.dispatches[0];
  const effect = source('D2-026').event;
  effect.permit = first.permit; effect.dispatch_digest = row.dispatch_digest;
  effect.native_evidence.status = 'OUTCOME_UNKNOWN'; effect.native_evidence.event_time = null; effect.native_evidence.actual_fields = [];
  advance(request, effect);
  assert.equal(request.state.active[0].status, 'OUTCOME_UNKNOWN');
  first.event_id = 'restart-ack-after-unknown';
  first.acknowledgement = { status: 'ACCEPTED', reference: 'accepted-after-unknown', observed_at: first.attempt.attempted_at };
  advance(request, first);
  assert.equal(request.state.active[0].status, 'OUTCOME_UNKNOWN');
  assert.equal(checkpointBefore(request.state, request.definition, BigInt(request.state.revision) + 1n).active[0].status, 'OUTCOME_UNKNOWN');
});

test('acknowledgement after terminal stop preserves instance and occurrence status on restart', () => {
  const request = source('C3-SNAPSHOT-024'), row = request.state.dispatches[0];
  const receipt = request.state.receipts.find((receipt: Row) => receipt.event_id === row.event_id);
  const event = retainedEvent(request.state, row, receipt), statuses = request.state.active.map((row: Row) => row.status);
  event.event_id = 'restart-ack-after-stop'; event.acknowledgement = { status: 'ACCEPTED', reference: 'accepted-after-stop', observed_at: event.attempt.attempted_at };
  advance(request, event);
  assert.equal(request.state.status, 'STOPPED'); assert.deepEqual(request.state.active.map((row: Row) => row.status), statuses);
  assert.deepEqual(checkpointBefore(request.state, request.definition, BigInt(request.state.revision) + 1n).active.map((row: Row) => row.status), statuses);
});

for (const id of ['C3-SNAPSHOT-016', 'C3-SNAPSHOT-029', 'C3-SNAPSHOT-024']) {
  test(`restart retains admitted snapshot or legacy authorization history from ${id}`, () => {
    const request = source(id); advance(request, request.event);
  });
}

test('ungated authorization refuses a null required fence as INPUT_INVALID', () => {
  const request = source('C3-SNAPSHOT-027');
  assert.equal(request.definition.steps.find((row: Row) => row.id === request.event.permit.occurrence.step_id).dispatch_gate, undefined);
  assert.equal(request.event.authorization_fence, null);
  const result = step(request, request.specification_pin);
  assert.equal(result.status, 'REFUSED'); assert.equal(result.code, 'INPUT_INVALID');
  assert.deepEqual(result.state, request.state);
});

test('gated successful authority still refuses a null derived fence as BINDING_MISMATCH', () => {
  const request = source('C3-ED-003'); request.event.authorization_fence = null;
  const result = step(request, request.specification_pin);
  assert.equal(result.status, 'REFUSED'); assert.equal(result.code, 'BINDING_MISMATCH');
  assert.deepEqual(result.state, request.state);
});

test('gated withheld authority retains a null fence without creating authorization', () => {
  const request = source('C3-ED-013'); assert.equal(request.event.authorization_fence, null);
  const original = structuredClone(request.state.authorizations), result = advance(request, request.event);
  assert.equal(result.decision.disposition, 'WITHHELD');
  assert.deepEqual(result.state.authorizations, original);
  assert.equal(result.state.active[0].status, 'PERMITTED');
});
