import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { AdmissionError } from './canonical.ts';
import { SingleProcessReferenceHost } from './reference-host.ts';
import { selectedCandidate } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const pin = selectedCandidate();
async function prepared(): Promise<Row> {
  const base = '../specimens/factual-customer-message-review/lifecycle/';
  const requests = readFileSync(new URL(base + 'requests.jsonl', import.meta.url), 'utf8').trim().split('\n').map(line => JSON.parse(line).input);
  const expected = JSON.parse(readFileSync(new URL(base + 'results-derived.json', import.meta.url), 'utf8'));
  const deployment = requests[0], organization = deployment.deployment_authorization.organization_id, host = new SingleProcessReferenceHost(pin);
  assert.equal((await host.install(deployment)).disposition, 'INSTALLED');
  for (let index = 1; index <= 4; index++) {
    const result = await host.submit(organization, requests[index]);
    assert.deepEqual(result.transition, expected[index]);
    assert.equal(result.host_commit?.disposition, 'COMMITTED');
  }
  const authorization = requests[4].event;
  return { host, organization, instance: deployment.instance_id, permit: authorization.permit, native: authorization.native_request, connector: authorization.connector, nextClock: requests[6] };
}

test('assessment host without holdings retains complete results and exact retry across protected restart', async () => {
  const row = await prepared(); let calls = 0;
  const connector = { ...row.connector, invoke: () => { calls++; return { accepted: true }; } };
  const result = await row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
  assert.equal(result.status, 'COMMITTED'); assert.equal(result.invocation.status, 'ESTABLISHED');
  assert.deepEqual(result.invocation.holdings, []);
  const checkpoint = await row.host.exportCheckpoint(); assert.deepEqual(checkpoint.holdings, []);
  assert.equal(checkpoint.invocations.length, 1);
  const restored = SingleProcessReferenceHost.fromCheckpoint(pin, checkpoint);
  const replay = await restored.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
  assert.equal(replay.status, 'RETAINED_RESULT'); assert.deepEqual(replay.invocation.result, { accepted: true }); assert.equal(calls, 1);
});

test('assessment host retains pending and uncertain intents without a permission registry or blind retry', async (t) => {
  for (const [stage, expectedCalls, status] of [['AFTER_INTENT', 0, 'PENDING'], ['AFTER_INVOKE', 1, 'UNCERTAIN'], ['OUTCOME_WRITE', 1, 'UNCERTAIN']] as const) await t.test(stage, async () => {
    const row = await prepared(); let calls = 0;
    const connector = { ...row.connector, invoke: () => { calls++; return { accepted: true }; } };
    const result = await row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector, stage);
    assert.equal(result.status, 'PENDING_RECONCILIATION'); assert.equal(result.invocation.status, status);
    const restored = SingleProcessReferenceHost.fromCheckpoint(pin, await row.host.exportCheckpoint());
    const replay = await restored.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
    assert.equal(replay.status, 'PENDING_RECONCILIATION'); assert.equal(replay.invocation.status, status); assert.equal(calls, expectedCalls);
  });
});

test('assessment host holds the existing mutation guard until deferred acceptance settles', async () => {
  const row = await prepared(); let entered!: () => void, resolveNative!: (value: string) => void;
  const invoked = new Promise<void>(resolve => { entered = resolve; }), pending = new Promise<string>(resolve => { resolveNative = resolve; });
  const dispatch = row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, { ...row.connector, invoke: () => { entered(); return pending; } });
  await invoked;
  try {
    await assert.rejects(() => row.host.submit(row.organization, row.nextClock), (error: unknown) => error instanceof AdmissionError && error.code === 'OPERATION_NOT_ALLOWED');
  } finally { resolveNative('accepted'); }
  assert.equal((await dispatch).status, 'COMMITTED');
  const snapshot = await row.host.snapshot(row.organization, row.instance), clock = structuredClone(row.nextClock);
  clock.state = snapshot.state; clock.state_digest = snapshot.state_digest;
  clock.event.expected_state_revision = snapshot.state.revision; clock.event.expected_state_digest = snapshot.state_digest;
  assert.equal((await row.host.submit(row.organization, clock)).transition.status, 'STEP');
});

test('assessment host deferred rejection retains uncertain custody across restart', async () => {
  const row = await prepared(); let entered!: () => void, rejectNative!: (error: Error) => void, calls = 0;
  const invoked = new Promise<void>(resolve => { entered = resolve; }), pending = new Promise<never>((_resolve, reject) => { rejectNative = reject; });
  const connector = { ...row.connector, invoke: () => { calls++; entered(); return pending; } };
  const dispatch = row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
  await invoked;
  try {
    await assert.rejects(() => row.host.submit(row.organization, row.nextClock), (error: unknown) => error instanceof AdmissionError && error.code === 'OPERATION_NOT_ALLOWED');
  } finally { rejectNative(new Error('Acceptance unknown')); }
  const uncertain = await dispatch;
  assert.equal(uncertain.status, 'PENDING_RECONCILIATION'); assert.equal(uncertain.invocation.status, 'UNCERTAIN');
  const restored = SingleProcessReferenceHost.fromCheckpoint(pin, await row.host.exportCheckpoint());
  const retry = await restored.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
  assert.equal(retry.status, 'PENDING_RECONCILIATION'); assert.equal(calls, 1);
});
