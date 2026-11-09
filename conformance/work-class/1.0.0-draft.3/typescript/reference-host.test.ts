import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test, { type TestContext } from 'node:test';
import { AdmissionError, canonical, digest } from './canonical.ts';
import { SingleProcessReferenceHost, type BudgetRoot, type BoundConnector } from './reference-host.ts';
import { selectedCandidate, VERSION } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);
const caseFile = (path: string): Row => JSON.parse(readFileSync(new URL(path, candidate), 'utf8'));
const equipmentCase = (number: string): Row => caseFile(`cases/equipment-dispatch/C3-ED-${number}.json`);

const bound = <T>(authorization: Row, invoke: (request: Row) => Promise<T> | T): BoundConnector<T> => ({ ...authorization.connector, invoke });

async function currentHostRequest(host: SingleProcessReferenceHost, organization: string, template: Row): Promise<Row> {
  const request = structuredClone(template), snapshot = await host.snapshot(organization, request.state.instance_id);
  request.state = snapshot.state; request.state_digest = snapshot.state_digest;
  request.event.expected_state_revision = snapshot.state.revision; request.event.expected_state_digest = snapshot.state_digest;
  return request;
}

async function installEquipment(host: SingleProcessReferenceHost): Promise<{ organization: string; instance: string; permit: Row }> {
  const deployment = equipmentCase('001'), proposal = equipmentCase('002');
  const organization = deployment.input.deployment_authorization.organization_id, instance = deployment.input.instance_id;
  assert.equal((await host.install(deployment.input)).disposition, 'INSTALLED');
  const clock = structuredClone(proposal.input);
  clock.event = {
    schema: VERSION + '/runtime-event', event_id: proposal.input.state.receipts[0].event_id, kind: 'CLOCK', instance_id: instance,
    clock: structuredClone(proposal.input.state.clocks[0]), activation_clocks: [],
  };
  assert.equal((await host.submit(organization, await currentHostRequest(host, organization, clock))).host_commit.disposition, 'COMMITTED');
  const permitted = await host.submit(organization, await currentHostRequest(host, organization, proposal.input));
  assert.equal(permitted.transition.decision.disposition, 'PERMITTED');
  return { organization, instance, permit: permitted.transition.permit };
}

async function authorizeEquipment(host: SingleProcessReferenceHost, organization: string, number = '003'): Promise<Row> {
  const committed = await host.submit(organization, await currentHostRequest(host, organization, equipmentCase(number).input));
  assert.equal(committed.host_commit.disposition, 'COMMITTED');
  assert.equal(committed.transition.decision.disposition, 'AUTHORIZED');
  return committed.transition.state.authorizations.find((row: Row) => row.event_id === committed.transition.decision.event_id);
}

function clockRequest(deployment: Row): Row {
  const state = structuredClone(deployment.expected.state);
  const event = {
    schema: VERSION + '/runtime-event', event_id: 'reference-host-clock-1', kind: 'CLOCK', instance_id: state.instance_id,
    expected_state_revision: state.revision, expected_state_digest: deployment.expected.state_digest,
    clock: { source: 'reference-host-clock', revision: '1', status: 'AVAILABLE', observed_time: '2026-09-10T04:30:00Z', evidence_digest: 'sha256:' + '1'.repeat(64) },
    activation_clocks: [],
  };
  return {
    specification_pin: selectedCandidate(), profile: deployment.input.profile, role: deployment.input.role,
    definition: structuredClone(deployment.input.definition), definition_digest: deployment.input.definition_digest,
    state, state_digest: deployment.expected.state_digest, event,
  };
}

function supplierFixture(path: string): Row {
  return caseFile(`specimens/supplier-payment/${path}`);
}

function supplierBudgetRoot(): BudgetRoot {
  const registered = supplierFixture('shared-budget-register-result-derived.json');
  return {
    registry_digest: digest('reservation-registry', registered.state.core.configuration),
    affected_anchors: ['supplier-payment-cap'],
    state: structuredClone(registered.state),
    state_digest: registered.state_digest,
  };
}

async function installSupplierInstance(host: SingleProcessReferenceHost, label: 'a' | 'b'): Promise<void> {
  const requests = supplierFixture(`instances/${label}/through-master-change-requests.json`) as unknown as Row[];
  const organization = requests[0].input.deployment_authorization.organization_id;
  const installed = await host.install(requests[0].input, [supplierBudgetRoot()]);
  assert.equal(installed.disposition, 'INSTALLED');
  for (const request of requests.slice(1)) {
    const result = await host.submit(organization, request.input);
    assert.equal(result.host_commit.disposition, 'COMMITTED');
  }
}

async function authoritativeCheckpoint(host: SingleProcessReferenceHost): Promise<Row> {
  const checkpoint = await host.exportCheckpoint();
  return { roots: checkpoint.roots, budgets: checkpoint.budgets };
}

function checkpointRoot(checkpoint: Row, organization: string, instance: string): Row {
  return checkpoint.roots.find(([key]: [string, Row]) => key === canonical([organization, instance]))[1];
}

async function assertRetainedTransition(host: SingleProcessReferenceHost, organization: string, request: Row, result: Row, before: Row): Promise<Row> {
  const checkpoint = await authoritativeCheckpoint(host), root = checkpointRoot(checkpoint, organization, request.state.instance_id);
  const prior = checkpointRoot(before, organization, request.state.instance_id);
  assert.equal(result.host_commit.disposition, 'COMMITTED');
  assert.equal(result.host_commit.dispatch_performed, false);
  assert.deepEqual(root.state, result.transition.state);
  assert.equal(root.state_bytes, canonical(result.transition.state));
  assert.equal(root.state_digest, result.transition.state_digest);
  assert.deepEqual(root.event_log, [...prior.event_log, [request.event.event_id, {
    event_digest: digest('runtime-event', request.event), transaction_digest: result.transition.transaction_digest,
    event: canonical(request.event), request: canonical(request), response: canonical(result.transition),
  }]]);
  assert.equal(result.host_commit.transaction_digest, result.transition.transaction_digest);
  assert.equal(result.host_commit.state_before_digest, request.state_digest);
  assert.equal(result.host_commit.state_after_digest, root.state_digest);
  for (const row of result.transition.budget_results) {
    const stored = checkpoint.budgets.find(([key]: [string, Row]) => key === canonical([organization, row.registry_digest]))[1];
    assert.deepEqual(stored.state, row.result.state);
    assert.equal(stored.state_bytes, canonical(row.result.state));
    assert.equal(stored.state_digest, digest('reservation-state', row.result.state));
    assert.deepEqual(result.host_commit.budget_after.find((binding: Row) => binding.registry_digest === row.registry_digest), {
      registry_digest: row.registry_digest, affected_anchors: row.affected_anchors, state_digest: stored.state_digest,
    });
  }
  if (result.transition.budget_results.length === 0) assert.deepEqual(checkpoint.budgets, before.budgets);
  return checkpoint;
}

type CommitFault = 'validation' | 'event-log' | 'response' | 'publication';

function injectCommitFault(context: TestContext, host: SingleProcessReferenceHost, fault: CommitFault, eventId: string, resultDefinition = 'hostCommitResult'): () => void {
  if (fault === 'validation') {
    // Fail the existing schema validator at the host-result boundary, without
    // substituting the lifecycle transition or introducing a host test API.
    const get = Map.prototype.get;
    const patched = context.mock.method(Map.prototype, 'get', function(this: Map<unknown, unknown>, key: unknown) {
      return key === 'lifecycle.schema.json:' + resultDefinition ? () => false : get.call(this, key);
    });
    return () => patched.mock.restore();
  }
  if (fault === 'event-log') {
    const set = Map.prototype.set;
    const patched = context.mock.method(Map.prototype, 'set', function(this: Map<unknown, unknown>, key: unknown, value: unknown) {
      if (key === eventId && value !== null && typeof value === 'object' && Object.hasOwn(value, 'request') && Object.hasOwn(value, 'response')) throw new Error('injected event-log preparation failure');
      return set.call(this, key, value);
    });
    return () => patched.mock.restore();
  }
  if (fault === 'response') {
    const copy = globalThis.structuredClone;
    const patched = context.mock.method(globalThis, 'structuredClone', function<T>(value: T): T {
      if (value !== null && typeof value === 'object' && 'status' in value && ['STEP', 'HOST_DEPLOY'].includes(String(value.status))) throw new Error('injected response preparation failure');
      return copy(value);
    });
    return () => patched.mock.restore();
  }
  const descriptor = Object.getOwnPropertyDescriptor(host, 'authoritative')!;
  Object.defineProperty(host, 'authoritative', {
    configurable: true, get: () => descriptor.value,
    set: () => { throw new Error('injected authoritative publication failure'); },
  });
  let restored = false;
  const restore = () => { if (!restored) { Object.defineProperty(host, 'authoritative', descriptor); restored = true; } };
  context.after(restore);
  return restore;
}

for (const budgetBacked of [false, true]) {
  test(`host retains the canonical log with ${budgetBacked ? 'budget-backed' : 'no-budget'} commits, failures, replay and refusal`, async () => {
    const host = new SingleProcessReferenceHost(selectedCandidate());
    const deployment = caseFile('cases/deployment/D2-008.json');
    if (budgetBacked) await installSupplierInstance(host, 'a');
    else await host.install(deployment.input);
    const request = budgetBacked ? (supplierFixture('contention/requests.json') as unknown as Row[])[0].input : clockRequest(deployment);
    const organization = request.state.deployment_organization_id, instance = request.state.instance_id;
    const before = await authoritativeCheckpoint(host);
    const failed = await host.submit(organization, request, 'opaque-atomic-commit-failure');
    assert.equal(failed.host_commit.disposition, 'COMMIT_FAILED');
    assert.equal(failed.host_commit.failure_reference, 'opaque-atomic-commit-failure');
    assert.equal(failed.host_commit.dispatch_performed, false);
    assert.equal(failed.host_commit.authoritative_state_digest, failed.host_commit.state_before_digest);
    assert.deepEqual(failed.host_commit.authoritative_budgets, failed.host_commit.budget_before);
    assert.deepEqual(await authoritativeCheckpoint(host), before);

    const committed = await host.submit(organization, request);
    const after = await assertRetainedTransition(host, organization, request, committed, before);
    if (budgetBacked) assert.equal(committed.transition.decision.disposition, 'PERMITTED');
    const stale = await host.submit(organization, request);
    assert.equal(stale.code, 'REVISION_CONFLICT');
    assert.deepEqual(await authoritativeCheckpoint(host), after);

    const replayRequest = structuredClone(request), snapshot = await host.snapshot(organization, instance);
    replayRequest.state = snapshot.state; replayRequest.state_digest = snapshot.state_digest;
    const replay = await host.submit(organization, replayRequest);
    assert.equal(replay.host_commit, null); assert.equal(replay.transition.replay, true);
    assert.deepEqual(await authoritativeCheckpoint(host), after);
    const conflictRequest = structuredClone(replayRequest);
    if (budgetBacked) conflictRequest.event.native_request.fields[0].value.value = '151';
    else conflictRequest.event.clock.evidence_digest = digest('test-altered-clock', { id: 'atomic-conflict' });
    assert.equal((await host.submit(organization, conflictRequest)).code, 'REPLAY_CONFLICT');
    assert.deepEqual(await authoritativeCheckpoint(host), after);
    assert.equal((await host.submit(organization, replayRequest)).transition.replay, true);
    assert.deepEqual(await authoritativeCheckpoint(host), after);
    const checkpoint = await host.exportCheckpoint();
    const restored = SingleProcessReferenceHost.fromCheckpoint(selectedCandidate(), checkpoint);
    assert.deepEqual(await restored.exportCheckpoint(), checkpoint);
    assert.equal((await restored.submit(organization, replayRequest)).transition.replay, true);
    assert.deepEqual(await authoritativeCheckpoint(restored), after);
  });

  test(`host preserves complete ${budgetBacked ? 'work/budget' : 'work'} roots and log across prepublication exceptions`, async context => {
    for (const fault of ['validation', 'event-log', 'response', 'publication'] as const) {
      await context.test(fault, async subtest => {
        const host = new SingleProcessReferenceHost(selectedCandidate());
        const deployment = caseFile('cases/deployment/D2-008.json');
        if (budgetBacked) await installSupplierInstance(host, 'a');
        else await host.install(deployment.input);
        const request = budgetBacked ? (supplierFixture('contention/requests.json') as unknown as Row[])[0].input : clockRequest(deployment);
        const organization = request.state.deployment_organization_id;
        const before = await authoritativeCheckpoint(host);
        const priorContainer = Reflect.get(host, 'authoritative'), priorValues = structuredClone(priorContainer);
        const restore = injectCommitFault(subtest, host, fault, request.event.event_id);
        try {
          await assert.rejects(host.submit(organization, request), fault === 'validation'
            ? (error: unknown) => error instanceof AdmissionError && error.code === 'SCHEMA_INVALID'
            : new RegExp('injected .* failure'));
        } finally { restore(); }
        assert.strictEqual(Reflect.get(host, 'authoritative'), priorContainer);
        assert.deepEqual(priorContainer, priorValues);
        assert.deepEqual(await authoritativeCheckpoint(host), before);
        const committed = await host.submit(organization, request);
        await assertRetainedTransition(host, organization, request, committed, before);
        assert.notStrictEqual(Reflect.get(host, 'authoritative'), priorContainer);
        assert.deepEqual(priorContainer, priorValues);
      });
    }
  });
}

test('host installation failures publish neither work nor supplied budget roots and leave the queue usable', async context => {
  for (const fault of ['validation', 'response', 'publication'] as const) {
    await context.test(fault, async subtest => {
      const host = new SingleProcessReferenceHost(selectedCandidate());
      const deployment = (supplierFixture('instances/a/through-master-change-requests.json') as unknown as Row[])[0].input;
      const before = await authoritativeCheckpoint(host), priorContainer = Reflect.get(host, 'authoritative');
      const restore = injectCommitFault(subtest, host, fault, '', 'hostDeploymentResult');
      try {
        await assert.rejects(host.install(deployment, [supplierBudgetRoot()]), fault === 'validation'
          ? (error: unknown) => error instanceof AdmissionError && error.code === 'SCHEMA_INVALID'
          : new RegExp('injected .* failure'));
      } finally { restore(); }
      assert.strictEqual(Reflect.get(host, 'authoritative'), priorContainer);
      assert.deepEqual(await authoritativeCheckpoint(host), before);
      assert.equal((await host.install(deployment, [supplierBudgetRoot()])).disposition, 'INSTALLED');
      assert.equal((await host.install(deployment, [supplierBudgetRoot()])).replay, true);
      assert.equal((await authoritativeCheckpoint(host)).budgets.length, 1);
    });
  }
});

test('host commits effect reconciliation with its affected registry and canonical event log', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  await installSupplierInstance(host, 'a');
  const trace = supplierFixture('valid-trace/requests.json') as unknown as Row[];
  const organization = trace[0].input.deployment_authorization.organization_id;
  for (const row of trace.slice(5, 7)) assert.equal((await host.submit(organization, row.input)).host_commit.disposition, 'COMMITTED');
  for (const row of trace.slice(7, 9)) {
    const request = row.input, before = await authoritativeCheckpoint(host);
    assert.equal(request.event.kind, 'EFFECT_OBSERVED');
    const result = await host.submit(organization, request);
    assert.equal(result.transition.budget_results.length, 1);
    const after = await assertRetainedTransition(host, organization, request, result, before);
    assert.notEqual(checkpointRoot(after, organization, request.state.instance_id).state_digest, checkpointRoot(before, organization, request.state.instance_id).state_digest);
    const registryKey = canonical([organization, request.event.budget_inputs[0].registry_digest]);
    assert.notEqual(after.budgets.find(([key]: [string, Row]) => key === registryKey)[1].state_digest, before.budgets.find(([key]: [string, Row]) => key === registryKey)[1].state_digest);
  }
});

test('registry-only admission and response preparation failures preserve the combined root and recover the queue', async context => {
  for (const fault of ['admission', 'response'] as const) {
    await context.test(fault, async subtest => {
      const host = new SingleProcessReferenceHost(selectedCandidate());
      await installSupplierInstance(host, 'a');
      const proposal = (supplierFixture('contention/requests.json') as unknown as Row[])[0].input;
      const organization = proposal.state.deployment_organization_id, request = proposal.event.budget_inputs[0].request;
      const before = await authoritativeCheckpoint(host);
      const priorContainer = Reflect.get(host, 'authoritative'), priorValues = structuredClone(priorContainer);
      const copy = globalThis.structuredClone;
      const patched = fault === 'admission'
        ? subtest.mock.method(host as unknown as { admitBudget(root: BudgetRoot): unknown }, 'admitBudget', () => { throw new AdmissionError('STATE_INVALID'); })
        : subtest.mock.method(globalThis, 'structuredClone', function<T>(value: T): T {
          if (value !== null && typeof value === 'object' && 'status' in value && value.status === 'TRANSITION') throw new Error('injected registry response preparation failure');
          return copy(value);
        });
      try {
        await assert.rejects(host.submitRegistry(organization, request), fault === 'admission'
          ? (error: unknown) => error instanceof AdmissionError && error.code === 'STATE_INVALID'
          : /injected registry response preparation failure/);
      } finally { patched.mock.restore(); }
      assert.strictEqual(Reflect.get(host, 'authoritative'), priorContainer);
      assert.deepEqual(priorContainer, priorValues);
      assert.deepEqual(await authoritativeCheckpoint(host), before);

      const result = await host.submitRegistry(organization, request), after = await authoritativeCheckpoint(host);
      assert.equal(result.committed, true); assert.equal(result.transition.status, 'TRANSITION');
      assert.deepEqual(after.roots, before.roots);
      assert.deepEqual(after.budgets, before.budgets.map(([key, budget]: [string, Row]) => [key, key === canonical([organization, request.host_evidence.registry_digest]) ? {
        ...budget, state: result.transition.state, state_bytes: canonical(result.transition.state), state_digest: result.transition.state_digest,
      } : budget]));
      assert.notEqual(result.transition.state_digest, request.state_digest);
      assert.notStrictEqual(Reflect.get(host, 'authoritative'), priorContainer);
      assert.deepEqual(priorContainer, priorValues);
    });
  }
});

test('host serializes install and commit, preserves failed roots, and replays exact events', async () => {
  const valid = caseFile('cases/deployment/D2-008.json');
  const occupied = caseFile('cases/deployment/D2-138.json');
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const installed = await host.install(valid.input);
  assert.equal(installed.disposition, 'INSTALLED'); assert.equal(installed.replay, false);
  const replayedInstall = await host.install(valid.input);
  assert.equal(replayedInstall.disposition, 'INSTALLED'); assert.equal(replayedInstall.replay, true);
  const changedBudgetRoots = [supplierBudgetRoot()];
  changedBudgetRoots[0].affected_anchors = [];
  const changedBudgetReplay = await host.install(valid.input, changedBudgetRoots);
  assert.equal(changedBudgetReplay.disposition, 'INSTANCE_OCCUPIED');
  const occupiedResult = await host.install(occupied.input);
  assert.equal(occupiedResult.disposition, 'INSTANCE_OCCUPIED');

  const request = clockRequest(valid);
  const before = await host.snapshot(valid.input.deployment_authorization.organization_id, valid.input.instance_id);
  const failed = await host.submit(valid.input.deployment_authorization.organization_id, request, 'injected-before-swap');
  assert.equal(failed.host_commit.disposition, 'COMMIT_FAILED');
  assert.deepEqual(await host.snapshot(valid.input.deployment_authorization.organization_id, valid.input.instance_id), before);

  const committed = await host.submit(valid.input.deployment_authorization.organization_id, request);
  assert.equal(committed.host_commit.disposition, 'COMMITTED');
  const after = await host.snapshot(valid.input.deployment_authorization.organization_id, valid.input.instance_id);
  assert.equal(after.state.revision, '1');
  const replayRequest = structuredClone(request);
  replayRequest.state = structuredClone(after.state); replayRequest.state_digest = after.state_digest;
  const exactReplay = await host.submit(valid.input.deployment_authorization.organization_id, replayRequest);
  assert.equal(exactReplay.host_commit, null); assert.equal(exactReplay.transition.replay, true);

  const altered = structuredClone(replayRequest); altered.event.clock.evidence_digest = digest('test-altered-clock', { id: 'different' });
  const conflict = await host.submit(valid.input.deployment_authorization.organization_id, altered);
  assert.equal(conflict.code, 'REPLAY_CONFLICT'); assert.equal(conflict.state_digest, after.state_digest);
});

test('host commits permission and reservation before dispatch and preserves both roots on failure', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  await installSupplierInstance(host, 'a');
  const proposal = (supplierFixture('contention/requests.json') as unknown as Row[])[0].input;
  const organization = proposal.state.deployment_organization_id;
  const before = await host.snapshot(organization, proposal.state.instance_id);

  const failed = await host.submit(organization, proposal, 'injected-before-authoritative-swap');
  assert.equal(failed.transition.decision.disposition, 'PERMITTED');
  assert.equal(failed.host_commit.disposition, 'COMMIT_FAILED');
  assert.deepEqual(await host.snapshot(organization, proposal.state.instance_id), before);
  await assert.rejects(
    host.dispatchPermitted(organization, proposal.state.instance_id, failed.transition.permit.permit_id, failed.transition.permit.native_request, () => 'sent'),
    /BINDING_MISMATCH/,
  );

  const committed = await host.submit(organization, proposal);
  assert.equal(committed.host_commit.disposition, 'COMMITTED');
  assert.equal(committed.transition.decision.disposition, 'PERMITTED');
  const after = await host.snapshot(organization, proposal.state.instance_id);
  assert.notEqual(after.state_digest, before.state_digest);
  assert.notEqual(after.budget_states[0].state_digest, before.budget_states[0].state_digest);

  let calls = 0;
  const permit = committed.transition.permit;
  const sent = await host.dispatchPermitted(organization, proposal.state.instance_id, permit.permit_id, permit.native_request, request => {
    calls += 1;
    return request;
  });
  assert.deepEqual(sent, permit.native_request);
  assert.equal(calls, 1);
  await assert.rejects(
    host.dispatchPermitted(organization, proposal.state.instance_id, permit.permit_id, permit.native_request, () => { calls += 1; }),
    (error: unknown) => error instanceof AdmissionError && error.code === 'PREREQUISITE_MISSING',
  );
  assert.equal(calls, 1);
  const changed = structuredClone(permit.native_request);
  changed.fields[0].value.value = '151';
  await assert.rejects(
    host.dispatchPermitted(organization, proposal.state.instance_id, permit.permit_id, changed, () => { calls += 1; }),
    /BINDING_MISMATCH/,
  );
  assert.equal(calls, 1);
});

test('host invokes a connector at most once for concurrent calls under one permit', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  await installSupplierInstance(host, 'a');
  const proposal = (supplierFixture('contention/requests.json') as unknown as Row[])[0].input;
  const organization = proposal.state.deployment_organization_id;
  const committed = await host.submit(organization, proposal);
  const permit = committed.transition.permit;
  let calls = 0;
  let release!: () => void;
  const blocked = new Promise<void>(resolve => { release = resolve; });
  let started!: () => void;
  const connectorStarted = new Promise<void>(resolve => { started = resolve; });
  const first = host.dispatchPermitted(organization, proposal.state.instance_id, permit.permit_id, permit.native_request, async () => {
    calls += 1;
    started();
    await blocked;
    return 'sent';
  });
  await connectorStarted;
  const second = host.dispatchPermitted(organization, proposal.state.instance_id, permit.permit_id, permit.native_request, () => {
    calls += 1;
    return 'duplicate';
  });
  release();
  assert.equal(await first, 'sent');
  await assert.rejects(second, (error: unknown) => error instanceof AdmissionError && error.code === 'PREREQUISITE_MISSING');
  assert.equal(calls, 1);
});

test('host retains a dispatch claim when the connector throws', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  await installSupplierInstance(host, 'a');
  const proposal = (supplierFixture('contention/requests.json') as unknown as Row[])[0].input;
  const organization = proposal.state.deployment_organization_id;
  const committed = await host.submit(organization, proposal);
  const permit = committed.transition.permit;
  let calls = 0;
  await assert.rejects(
    host.dispatchPermitted(organization, proposal.state.instance_id, permit.permit_id, permit.native_request, () => {
      calls += 1;
      throw new Error('connector failed after eligibility');
    }),
    /connector failed after eligibility/,
  );
  await assert.rejects(
    host.dispatchPermitted(organization, proposal.state.instance_id, permit.permit_id, permit.native_request, () => { calls += 1; }),
    (error: unknown) => error instanceof AdmissionError && error.code === 'PREREQUISITE_MISSING',
  );
  assert.equal(calls, 1);
});

test('gated host requires a committed explicit authorization and preserves roots on a failed commit', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const { organization, instance, permit } = await installEquipment(host);
  const before = await host.snapshot(organization, instance);
  const failed = await host.submit(organization, await currentHostRequest(host, organization, equipmentCase('003').input), 'before-authorization-swap');
  assert.equal(failed.transition.decision.disposition, 'AUTHORIZED');
  assert.equal(failed.host_commit.disposition, 'COMMIT_FAILED');
  assert.deepEqual(await host.snapshot(organization, instance), before);
  let calls = 0;
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(failed.transition.state.authorizations[0], () => { calls++; }), failed.transition.state.authorizations[0]), /BINDING_MISMATCH/);
  const authorization = await authorizeEquipment(host, organization);
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, () => { calls++; }), /BINDING_MISMATCH/);
  const changed = structuredClone(authorization); changed.connector.id = 'different-connector';
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(changed, () => { calls++; }), changed), /BINDING_MISMATCH/);
  assert.equal(calls, 0);
  await host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, () => { calls++; }), authorization);
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, () => { calls++; }), authorization), /PREREQUISITE_MISSING/);
  assert.equal(calls, 1);
});

test('gated host serializes concurrent calls under one intent', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const { organization, instance, permit } = await installEquipment(host);
  const authorization = await authorizeEquipment(host, organization);
  let calls = 0;
  let release!: () => void, started!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const invoked = new Promise<void>(resolve => { started = resolve; });
  const first = host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, async () => { calls++; started(); await pending; return 'attempted'; }), authorization);
  await invoked;
  const second = host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, () => { calls++; }), authorization);
  release();
  assert.equal(await first, 'attempted');
  await assert.rejects(second, /PREREQUISITE_MISSING/);
  assert.equal(calls, 1);
});

test('gated host validates connector identity and version before claiming an intent', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const { organization, instance, permit } = await installEquipment(host);
  const authorization = await authorizeEquipment(host, organization);
  const before = await host.snapshot(organization, instance);
  let calls = 0;
  for (const member of ['id', 'version', 'binding_digest'] as const) {
    const connector = bound(authorization, () => { calls++; });
    connector[member] = member === 'binding_digest' ? 'sha256:' + 'a'.repeat(64) : 'different-' + member;
    await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, connector, authorization), /BINDING_MISMATCH/);
    assert.equal(calls, 0);
    assert.deepEqual(await host.snapshot(organization, instance), before);
  }
  await host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, () => { calls++; }), authorization);
  assert.equal(calls, 1);
});

test('gated host rejects opaque or malformed connectors without claiming an intent', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const { organization, instance, permit } = await installEquipment(host);
  const authorization = await authorizeEquipment(host, organization);
  let calls = 0;
  const invoke = () => { calls++; };
  for (const connector of [invoke, { ...bound(authorization, invoke), extra: 'unsupported' }, { ...authorization.connector, invoke: null }]) {
    await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, connector as BoundConnector<void>, authorization), /INPUT_INVALID/);
    assert.equal(calls, 0);
  }
  await host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, invoke), authorization);
  assert.equal(calls, 1);
});

test('gated host snapshots connector metadata and invocation before queueing', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const { organization, instance, permit } = await installEquipment(host);
  const authorization = await authorizeEquipment(host, organization);
  let authorizedCalls = 0, substitutedCalls = 0;
  const connector = bound(authorization, () => { authorizedCalls++; });
  const pending = host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, connector, authorization);
  connector.id = 'substituted-connector'; connector.invoke = () => { substitutedCalls++; };
  await pending;
  assert.equal(authorizedCalls, 1); assert.equal(substitutedCalls, 0);
});

test('gated host blocks unresolved claims across a fresh authorization and records conservative recovery', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const { organization, instance, permit } = await installEquipment(host);
  const original = await authorizeEquipment(host, organization);
  let calls = 0;
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(original, () => { calls++; throw new Error('may have sent'); }), original), /may have sent/);
  const fresh = await authorizeEquipment(host, organization, '017');
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(fresh, () => { calls++; }), fresh), /PREREQUISITE_MISSING/);
  const replayRequest = structuredClone(equipmentCase('017').input), snapshot = await host.snapshot(organization, instance);
  replayRequest.state = snapshot.state; replayRequest.state_digest = snapshot.state_digest;
  const replay = await host.submit(organization, replayRequest);
  assert.equal(replay.transition.replay, true);
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(fresh, () => { calls++; }), fresh), /PREREQUISITE_MISSING/);
  const recovery = await currentHostRequest(host, organization, equipmentCase('019').input);
  recovery.event.attempt.status = 'UNKNOWN';
  const observed = await host.submit(organization, recovery);
  assert.equal(observed.host_commit.disposition, 'COMMITTED');
  assert.equal(observed.transition.decision.disposition, 'DISPUTED');
  assert.equal(observed.transition.state.active[0].status, 'BLOCKED_DISPUTE');
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(fresh, () => { calls++; }), fresh));
  assert.equal(calls, 1);
});

test('gated host requires a fresh intent after retained safe NOT_SENT', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const { organization, instance, permit } = await installEquipment(host);
  const original = await authorizeEquipment(host, organization);
  let calls = 0;
  await host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(original, () => { calls++; }), original);
  const observed = await host.submit(organization, await currentHostRequest(host, organization, equipmentCase('021').input));
  assert.equal(observed.transition.decision.disposition, 'DISPATCH_REFUSED');
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(original, () => { calls++; }), original), /PREREQUISITE_MISSING/);
  const fresh = await authorizeEquipment(host, organization, '022');
  await host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(fresh, () => { calls++; }), fresh);
  assert.equal(calls, 2);
});

test('gated host blocks the retained successful head after a later withheld evaluation and replay', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const { organization, instance, permit } = await installEquipment(host);
  const authorization = await authorizeEquipment(host, organization);
  const withdrawal = await currentHostRequest(host, organization, equipmentCase('013').input);
  withdrawal.event.event_id = 'withheld-after-authorization';
  withdrawal.event.dispatch_intent_id = 'withdrawal-after-authorization';
  const withheld = await host.submit(organization, withdrawal);
  assert.equal(withheld.host_commit.disposition, 'COMMITTED');
  assert.equal(withheld.transition.decision.disposition, 'WITHHELD');
  assert.deepEqual(withheld.transition.state.authorizations, [authorization]);
  let calls = 0;
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, () => { calls++; }), authorization), /PREREQUISITE_MISSING/);
  const replayRequest = structuredClone(equipmentCase('003').input), snapshot = await host.snapshot(organization, instance);
  replayRequest.state = snapshot.state; replayRequest.state_digest = snapshot.state_digest;
  assert.equal((await host.submit(organization, replayRequest)).transition.replay, true);
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, () => { calls++; }), authorization), /PREREQUISITE_MISSING/);
  assert.equal(calls, 0);
});

test('gated host rejects unavailable clocks and authorization expiry before connector invocation', async () => {
  for (const unavailable of [false, true]) {
    const host = new SingleProcessReferenceHost(selectedCandidate());
    const { organization, instance, permit } = await installEquipment(host);
    const authorization = await authorizeEquipment(host, organization);
    const request = await currentHostRequest(host, organization, equipmentCase('003').input);
    request.event = {
      schema: VERSION + '/runtime-event', event_id: 'gated-send-clock-2', kind: 'CLOCK', instance_id: instance,
      expected_state_revision: request.state.revision, expected_state_digest: request.state_digest,
      clock: { source: permit.clock_source, revision: '2', status: unavailable ? 'UNAVAILABLE' : 'AVAILABLE', observed_time: unavailable ? null : authorization.expires_at, evidence_digest: digest('gated-clock-test', { unavailable }) }, activation_clocks: [],
    };
    assert.equal((await host.submit(organization, request)).host_commit.disposition, 'COMMITTED');
    let calls = 0;
    await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, () => { calls++; }), authorization), /BINDING_MISMATCH/);
    assert.equal(calls, 0);
  }
});

test('later unavailable evaluation blocks sends while retaining a timely earlier dispatch observation', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const { organization, instance, permit } = await installEquipment(host);
  const authorization = await authorizeEquipment(host, organization);
  const clockRequest = await currentHostRequest(host, organization, equipmentCase('003').input);
  clockRequest.event = {
    schema: VERSION + '/runtime-event', event_id: 'unavailable-after-authorization', kind: 'CLOCK', instance_id: instance,
    expected_state_revision: clockRequest.state.revision, expected_state_digest: clockRequest.state_digest,
    clock: { source: permit.clock_source, revision: '2', status: 'UNAVAILABLE', observed_time: null, evidence_digest: digest('unavailable-dispatch-clock', { id: 'clock-2' }) }, activation_clocks: [],
  };
  assert.equal((await host.submit(organization, clockRequest)).host_commit.disposition, 'COMMITTED');
  const unavailable = await currentHostRequest(host, organization, equipmentCase('025').input);
  unavailable.event.event_id = 'withheld-unavailable-after-authorization';
  const withheld = await host.submit(organization, unavailable);
  assert.equal(withheld.transition.decision.disposition, 'WITHHELD');
  assert.deepEqual(withheld.transition.decision.reason_codes, ['AUTHORITY_NOT_ESTABLISHED', 'AUTHORITY_REQUIRED', 'CLOCK_UNAVAILABLE']);
  let calls = 0;
  await assert.rejects(host.dispatchPermitted(organization, instance, permit.permit_id, permit.native_request, bound(authorization, () => { calls++; }), authorization), /BINDING_MISMATCH/);
  const observed = await host.submit(organization, await currentHostRequest(host, organization, equipmentCase('019').input));
  assert.equal(observed.host_commit.disposition, 'COMMITTED');
  assert.equal(observed.transition.decision.disposition, 'DISPATCH_RECORDED');
  assert.deepEqual(observed.transition.decision.reason_codes, []);
  assert.equal(calls, 0);
});

test('host does not install partial roots when supplied budget admission throws', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  const requests = supplierFixture('instances/a/through-master-change-requests.json') as unknown as Row[];
  const deployment = requests[0].input;
  const invalidBudget = supplierBudgetRoot();
  invalidBudget.state_digest = digest('test-invalid-budget-state', invalidBudget.state);
  await assert.rejects(host.install(deployment, [invalidBudget]), (error: unknown) => error instanceof AdmissionError && error.code === 'STATE_INVALID');
  const installed = await host.install(deployment, [supplierBudgetRoot()]);
  assert.equal(installed.disposition, 'INSTALLED');
  const snapshot = await host.snapshot(deployment.deployment_authorization.organization_id, deployment.instance_id);
  assert.equal(snapshot.budget_states.length, 1);
});

test('host serializes two instances against one shared budget revision', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  await installSupplierInstance(host, 'a');
  await installSupplierInstance(host, 'b');
  const contention = supplierFixture('contention/requests.json') as unknown as Row[];
  const organization = contention[0].input.state.deployment_organization_id;
  const before = await authoritativeCheckpoint(host);

  const [first, second] = await Promise.all([
    host.submit(organization, contention[0].input),
    host.submit(organization, contention[1].input),
  ]);
  assert.equal(first.host_commit.disposition, 'COMMITTED');
  assert.equal(first.transition.decision.disposition, 'PERMITTED');
  assert.equal(second.status, 'REFUSED');
  assert.equal(second.code, 'REVISION_CONFLICT');
  assert.equal(second.state.revision, '4');
  assert.equal(second.budget_states[0].state.core.revision, '2');
  const afterFirst = await assertRetainedTransition(host, organization, contention[0].input, first, before);
  assert.deepEqual(checkpointRoot(afterFirst, organization, contention[1].input.state.instance_id), checkpointRoot(before, organization, contention[1].input.state.instance_id));

  const retry = await host.submit(organization, contention[3].input);
  assert.equal(retry.host_commit.disposition, 'COMMITTED');
  assert.equal(retry.transition.decision.disposition, 'WITHHELD');
  assert.deepEqual(retry.transition.decision.reason_codes, ['BOUND_VIOLATED', 'BUDGET_WITHHELD']);
  assert.equal(retry.transition.permit, null);
  const afterRetry = await assertRetainedTransition(host, organization, contention[3].input, retry, afterFirst);
  assert.deepEqual(checkpointRoot(afterRetry, organization, contention[0].input.state.instance_id), checkpointRoot(afterFirst, organization, contention[0].input.state.instance_id));
});

test('host rejects a stale effect budget and echoes the authoritative work and budget roots', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate());
  await installSupplierInstance(host, 'a');
  const trace = supplierFixture('valid-trace/requests.json') as unknown as Row[];
  const organization = trace[0].input.deployment_authorization.organization_id;
  for (const request of trace.slice(5, 8)) {
    const result = await host.submit(organization, request.input);
    assert.equal(result.host_commit.disposition, 'COMMITTED');
  }
  const authoritative = await host.snapshot(organization, trace[8].input.state.instance_id);
  const checkpoint = await authoritativeCheckpoint(host);
  assert.equal(authoritative.state.revision, '7');
  assert.equal(authoritative.budget_states[0].state.core.revision, '3');

  const staleEffect = structuredClone(trace[8].input);
  staleEffect.event.event_id = 'effect-payment-stale-budget-a-1';
  staleEffect.event.budget_inputs = structuredClone(trace[7].input.event.budget_inputs);
  const refused = await host.submit(organization, staleEffect);
  assert.equal(refused.status, 'REFUSED');
  assert.equal(refused.code, 'REVISION_CONFLICT');
  assert.equal(refused.state_digest, authoritative.state_digest);
  assert.deepEqual(refused.state, authoritative.state);
  assert.deepEqual(refused.budget_states, authoritative.budget_states);
  assert.deepEqual(await host.snapshot(organization, trace[8].input.state.instance_id), authoritative);
  assert.deepEqual(await authoritativeCheckpoint(host), checkpoint);
});
