import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { AdmissionError, digest } from './canonical.ts';
import { SingleProcessReferenceHost } from './reference-host.ts';
import { selectedCandidate } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const pin = selectedCandidate();
function source(id: string): Row { return JSON.parse(readFileSync(new URL('../cases/holdings/C3-HOLD-' + id + '.json', import.meta.url), 'utf8')); }
async function prepared(): Promise<Row> {
  const host = new SingleProcessReferenceHost(pin), deployment = source('081').input, authorization = source('084').input;
  const organization = deployment.deployment_authorization.organization_id, instance = deployment.instance_id;
  const basis = authorization.event.authority_input.holdings_bases[0];
  await host.installHoldings(organization, basis.configuration, basis.state, basis.state_digest);
  assert.equal((await host.install(deployment)).disposition, 'INSTALLED');
  for (const id of ['082', '083', '084']) {
    const result = await host.submit(organization, source(id).input);
    assert.equal(result.transition?.status, 'STEP', JSON.stringify(result)); assert.equal(result.host_commit?.disposition, 'COMMITTED');
    assert.deepEqual(result.transition, source(id).expected);
  }
  return { host, organization, instance, basis, permit: authorization.event.permit, native: authorization.event.native_request, connector: authorization.event.connector };
}

test('holdings host exact committed retry retains result without reinvocation', async () => {
  const row = await prepared(); let calls = 0;
  const connector = { ...row.connector, invoke: () => { calls++; return { accepted: true }; } };
  const first = await row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
  assert.equal(first.status, 'COMMITTED'); assert.equal(first.invocation.status, 'ESTABLISHED');
  const replay = await row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
  assert.equal(replay.status, 'RETAINED_RESULT'); assert.equal(calls, 1);
});

test('holdings host failures retain exact pending or uncertain invocation and prohibit blind retries', async () => {
  for (const [stage, expectedCalls, retained] of [['AFTER_INTENT', 0, 'PENDING'], ['AFTER_INVOKE', 1, 'UNCERTAIN'], ['OUTCOME_WRITE', 1, 'UNCERTAIN']] as const) {
    const row = await prepared(); let calls = 0;
    const connector = { ...row.connector, invoke: () => { calls++; return { accepted: true }; } };
    const first = await row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector, stage);
    assert.equal(first.status, 'PENDING_RECONCILIATION'); assert.equal(first.invocation.status, retained);
    const restored = SingleProcessReferenceHost.fromCheckpoint(pin, await row.host.exportCheckpoint());
    const replay = await restored.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
    assert.equal(replay.status, 'PENDING_RECONCILIATION'); assert.equal(calls, expectedCalls);
  }
});

test('holdings host failure before intent preserves state and permits a later admitted attempt', async () => {
  const row = await prepared(); let calls = 0;
  const connector = { ...row.connector, invoke: () => { calls++; return 'accepted'; } };
  assert.equal((await row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector, 'BEFORE_INTENT')).status, 'COMMIT_FAILED');
  assert.equal(calls, 0); assert.equal((await row.host.exportCheckpoint()).invocations.length, 0);
  assert.equal((await row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector)).status, 'COMMITTED'); assert.equal(calls, 1);
});

test('holdings host rejects reentrant registry writers while synchronous commitment holds the queue', async () => {
  const row = await prepared(); let rejection: Promise<unknown> | undefined;
  const before = await row.host.holdingsSnapshot(row.organization, digest('holdings-configuration', row.basis.configuration));
  const connector = { ...row.connector, invoke: () => {
    rejection = row.host.submitHoldings(row.organization, source('001').input).catch((error: unknown) => error);
    return 'accepted';
  } };
  assert.equal((await row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector)).status, 'COMMITTED');
  const failure = await rejection; assert.ok(failure instanceof AdmissionError); assert.equal(failure.code, 'OPERATION_NOT_ALLOWED');
  assert.deepEqual(await row.host.holdingsSnapshot(row.organization, digest('holdings-configuration', row.basis.configuration)), before);
});

test('holdings host rejects stale authoritative snapshot selection and redacts protected denial details', async () => {
  const row = await prepared(), wrong = structuredClone(source('084').input);
  const current = await row.host.snapshot(row.organization, row.instance);
  wrong.state = current.state; wrong.state_digest = current.state_digest;
  wrong.event.expected_state_digest = current.state_digest; wrong.event.expected_state_revision = current.state.revision;
  wrong.event.authority_input.holdings_bases[0].state_digest = digest('old-state', {});
  wrong.event.event_id = 'new-authorization-attempt';
  const result = await row.host.submit(row.organization, wrong);
  assert.equal(result.code, 'DEPENDENCY_MISMATCH');
  assert.deepEqual(SingleProcessReferenceHost.publicFailure(), { status: 'REFUSED', code: 'OPERATION_NOT_ALLOWED' });
});


test('holdings protected checkpoint carriers cannot mutate authoritative replay metadata by reference', async () => {
  const row = await prepared(), checkpoint = await row.host.exportCheckpoint();
  const original = checkpoint.roots[0][1].event_log[0][1].event;
  checkpoint.roots[0][1].event_log[0][1].event = 'changed-export';
  assert.equal((await row.host.exportCheckpoint()).roots[0][1].event_log[0][1].event, original);
  const supplied = await row.host.exportCheckpoint(), restored = SingleProcessReferenceHost.fromCheckpoint(pin, supplied);
  supplied.roots[0][1].event_log[0][1].event = 'changed-import';
  assert.equal((await restored.exportCheckpoint()).roots[0][1].event_log[0][1].event, original);
});


test('holdings host keeps grant and revoke writers excluded until an asynchronous connector fulfills', async (t) => {
  for (const id of ['002', '004']) await t.test(source(id).input.event.kind, async () => {
    const row = await prepared(), writer = source(id).input;
    await row.host.installHoldings(row.organization, writer.configuration, writer.state, writer.state_digest);
    let entered!: () => void, resolveNative!: (value: { accepted: boolean }) => void, calls = 0;
    const invoked = new Promise<void>(resolve => { entered = resolve; });
    const pending = new Promise<{ accepted: boolean }>(resolve => { resolveNative = resolve; });
    const connector = { ...row.connector, invoke: () => { calls++; entered(); return pending; } };
    const dispatch = row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
    await invoked;
    try {
      await assert.rejects(() => row.host.submitHoldings(row.organization, writer), (error: unknown) => error instanceof AdmissionError && error.code === 'OPERATION_NOT_ALLOWED');
    } finally { resolveNative({ accepted: true }); }
    const committed = await dispatch;
    assert.equal(committed.status, 'COMMITTED'); assert.equal(committed.invocation.status, 'ESTABLISHED');
    assert.deepEqual(committed.invocation.result, { accepted: true });
    assert.deepEqual(await row.host.submitHoldings(row.organization, writer), source(id).expected);
    assert.equal((await row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector)).status, 'RETAINED_RESULT');
    assert.equal(calls, 1);
  });
});

test('holdings host keeps the guard through asynchronous rejection and retains uncertain custody without reinvocation', async () => {
  const row = await prepared(), writer = source('004').input;
  await row.host.installHoldings(row.organization, writer.configuration, writer.state, writer.state_digest);
  let entered!: () => void, rejectNative!: (reason: Error) => void, calls = 0;
  const invoked = new Promise<void>(resolve => { entered = resolve; });
  const pending = new Promise<never>((_resolve, reject) => { rejectNative = reject; });
  const connector = { ...row.connector, invoke: () => { calls++; entered(); return pending; } };
  const dispatch = row.host.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector);
  await invoked;
  try {
    await assert.rejects(() => row.host.submitHoldings(row.organization, writer), (error: unknown) => error instanceof AdmissionError && error.code === 'OPERATION_NOT_ALLOWED');
  } finally { rejectNative(new Error('Provider acceptance is unknown')); }
  const uncertain = await dispatch;
  assert.equal(uncertain.status, 'PENDING_RECONCILIATION'); assert.equal(uncertain.invocation.status, 'UNCERTAIN');
  assert.deepEqual(await row.host.submitHoldings(row.organization, writer), source('004').expected);
  const restored = SingleProcessReferenceHost.fromCheckpoint(pin, await row.host.exportCheckpoint());
  assert.equal((await restored.dispatch(row.organization, row.instance, row.permit.permit_id, row.native, connector)).status, 'PENDING_RECONCILIATION');
  assert.equal(calls, 1);
});
