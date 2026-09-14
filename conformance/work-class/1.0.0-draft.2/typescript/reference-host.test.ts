import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { AdmissionError, digest } from './canonical.ts';
import { SingleProcessReferenceHost, type BudgetRoot } from './reference-host.ts';
import { selectedCandidate, VERSION } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);
const caseFile = (path: string): Row => JSON.parse(readFileSync(new URL(path, candidate), 'utf8'));

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

  const retry = await host.submit(organization, contention[3].input);
  assert.equal(retry.host_commit.disposition, 'COMMITTED');
  assert.equal(retry.transition.decision.disposition, 'WITHHELD');
  assert.deepEqual(retry.transition.decision.reason_codes, ['BOUND_VIOLATED', 'BUDGET_WITHHELD']);
  assert.equal(retry.transition.permit, null);
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
});
