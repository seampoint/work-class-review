import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { digest } from './canonical.ts';
import { stateDigest } from './lifecycle.ts';
import { SingleProcessReferenceHost, type BudgetRoot } from './reference-host.ts';
import { initialReservationState } from './reservations.ts';
import { selectedCandidate, VERSION } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const fixture = (group: string, id: string): Row => JSON.parse(readFileSync(new URL(`../cases/${group}/C3-${id}.json`, import.meta.url), 'utf8'));

function deploymentInput(source: Row): Row {
  const retained = source.state;
  return { profile: source.profile, role: source.role, specification_pin: source.specification_pin, instance_id: retained.instance_id, definition: source.definition, definition_digest: source.definition_digest, deployment_authorization: retained.deployment_authorization, authorization_clock: retained.deployment_authorization_clock, authorization_evidence: retained.deployment_authorization_evidence, correspondence_evidence: retained.deployment_correspondence_evidence, source_confirmation_evidence: retained.deployment_source_confirmation_evidence, policy_decision_evidence: retained.deployment_policy_decision_evidence, initial_clocks: [] };
}

async function current(host: SingleProcessReferenceHost, organization: string, template: Row, replay = false): Promise<Row> {
  const input = structuredClone(template), snapshot = await host.snapshot(organization, input.state.instance_id);
  input.state = snapshot.state; input.state_digest = snapshot.state_digest;
  if (!replay) { input.event.expected_state_revision = snapshot.state.revision; input.event.expected_state_digest = snapshot.state_digest; }
  return input;
}

async function installCompletion(host: SingleProcessReferenceHost, keyed = false): Promise<{ organization: string; source: Row; permit: Row }> {
  const source = fixture('equipment-completion', keyed ? 'EC-067' : 'EC-001').input, retained = source.state;
  const definition = source.definition, organization = retained.deployment_organization_id;
  const deployment = deploymentInput(source);
  const roots: BudgetRoot[] = [];
  if (keyed) {
    const registry = source.event.budget_inputs[0].request.state, state = initialReservationState(registry.core.configuration, selectedCandidate());
    roots.push({ registry_digest: digest('reservation-registry', state.core.configuration), affected_anchors: [], state, state_digest: digest('reservation-state', state) });
  }
  assert.equal((await host.install(deployment, roots)).disposition, 'INSTALLED');
  const clock = structuredClone(source);
  clock.event = { schema: VERSION + '/runtime-event', event_id: 'clock-1', kind: 'CLOCK', instance_id: retained.instance_id, clock: retained.clocks[0], activation_clocks: [] };
  assert.equal((await host.submit(organization, await current(host, organization, clock))).host_commit.disposition, 'COMMITTED');
  const originalPermit = retained.permits[0], proposal = structuredClone(fixture('equipment-dispatch', 'ED-002').input);
  proposal.definition = definition; proposal.definition_digest = source.definition_digest;
  Object.assign(proposal.event, { occurrence: originalPermit.occurrence, native_request: originalPermit.native_request, executor: originalPermit.executor, credential_ids: originalPermit.credential_ids, observation_digests: originalPermit.observation_digests, clock_revision: originalPermit.clock_revision, authority_input: originalPermit.authority_basis, budget_inputs: [] });
  if (keyed) {
    const registry = source.event.budget_inputs[0].request.state, record = registry.receipts[0];
    proposal.event.budget_inputs = [{ registry_digest: roots[0].registry_digest, affected_anchors: [], expected_revision: '0', request: { ...source.event.budget_inputs[0].request, state: roots[0].state, state_digest: roots[0].state_digest, event: record.event, host_evidence: record.host_evidence } }];
  }
  const proposed = await host.submit(organization, await current(host, organization, proposal)); assert.equal(proposed.transition?.decision.disposition, 'PERMITTED');
  assert.deepEqual(proposed.transition.permit, originalPermit);
  const authorization = retained.authorizations[0], authorize = structuredClone(source);
  authorize.event = { schema: VERSION + '/runtime-event', event_id: authorization.event_id, kind: 'AUTHORIZE_DISPATCH', instance_id: retained.instance_id, permit: originalPermit, native_request: authorization.native_request, connector: authorization.connector, authorization_fence: authorization.authorization_fence, observation_digests: authorization.observation_digests, clock_revision: authorization.clock_revision, authority_input: authorization.authority_input, dispatch_intent_id: authorization.dispatch_intent_id };
  assert.equal((await host.submit(organization, await current(host, organization, authorize))).transition.decision.disposition, 'AUTHORIZED');
  const observed = retained.dispatches[0], dispatch = structuredClone(source);
  dispatch.event = { schema: VERSION + '/runtime-event', event_id: observed.event_id, kind: 'DISPATCH_OBSERVED', instance_id: retained.instance_id, permit: originalPermit, native_request: observed.native_request, connector: observed.connector, attempt: observed.attempt, acknowledgement: observed.acknowledgement, clock_revision: observed.clock_revision, authorization_digest: observed.authorization_digest };
  assert.equal((await host.submit(organization, await current(host, organization, dispatch))).transition.decision.disposition, 'DISPATCH_RECORDED');
  const snapshot = await host.snapshot(organization, retained.instance_id);
  const expected = keyed ? fixture('equipment-completion', 'EC-066').input.state : retained;
  assert.equal(snapshot.state_digest, stateDigest(expected));
  return { organization, source, permit: originalPermit };
}

test('completion commit persists the lookup, stop, referrals and log together, with no connector resend', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate()), installed = await installCompletion(host);
  const template = fixture('equipment-completion', 'EC-036').input;
  const input = await current(host, installed.organization, template), before = await host.snapshot(installed.organization, input.state.instance_id);
  const failed = await host.submit(installed.organization, input, 'lookup-commit-failure');
  assert.equal(failed.host_commit.disposition, 'COMMIT_FAILED'); assert.equal(failed.transition.state.status, 'STOPPED');
  assert.deepEqual(await host.snapshot(installed.organization, input.state.instance_id), before);
  const committed = await host.submit(installed.organization, input);
  assert.equal(committed.host_commit.disposition, 'COMMITTED'); assert.equal(committed.transition.state.completion_checks.length, 1);
  assert.equal(committed.transition.state.terminal_records.length, 1); assert.equal(committed.transition.state.referrals.length, 2);
  const replay = await host.submit(installed.organization, await current(host, installed.organization, input, true));
  assert.equal(replay.host_commit, null); assert.equal(replay.transition.replay, true);
  let sends = 0;
  await assert.rejects(host.dispatchPermitted(installed.organization, input.state.instance_id, installed.permit.permit_id, installed.permit.native_request, () => { sends++; }, installed.source.state.authorizations[0]), { code: 'BINDING_MISMATCH' });
  assert.equal(sends, 0);
  const repeated = await host.submit(installed.organization, await current(host, installed.organization, fixture('equipment-completion', 'EC-059').input));
  assert.equal(repeated.code, 'PREREQUISITE_MISSING');
});

test('late exact settlement commits every key with work evidence while retaining the initial terminal cause', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate()), installed = await installCompletion(host, true), source = installed.source;
  const beforeLookup = await host.snapshot(installed.organization, source.state.instance_id);
  const stopped = await host.submit(installed.organization, await current(host, installed.organization, fixture('equipment-completion', 'EC-066').input));
  assert.equal(stopped.host_commit.disposition, 'COMMITTED');
  const stopSnapshot = await host.snapshot(installed.organization, source.state.instance_id);
  assert.deepEqual(stopSnapshot.budget_states, beforeLookup.budget_states);
  const late = await current(host, installed.organization, source);
  const failure = await host.submit(installed.organization, late, 'settlement-commit-failure');
  assert.equal(failure.host_commit.disposition, 'COMMIT_FAILED');
  assert.deepEqual(await host.snapshot(installed.organization, source.state.instance_id), stopSnapshot);
  const committed = await host.submit(installed.organization, late);
  assert.equal(committed.host_commit.disposition, 'COMMITTED');
  const after = await host.snapshot(installed.organization, source.state.instance_id);
  assert.equal(after.state.status, 'STOPPED'); assert.equal(after.state.completed[0].late, true); assert.equal(after.state.completed[0].selected_relationship_digest, null);
  assert.deepEqual(after.state.terminal_records, stopSnapshot.state.terminal_records); assert.deepEqual(after.state.referrals, stopSnapshot.state.referrals);
  assert.ok(after.budget_states[0].state.core.exclusive_keys.every((row: Row) => row.status === 'CONSUMED'));
  const replay = await host.submit(installed.organization, await current(host, installed.organization, late, true)); assert.equal(replay.transition.replay, true);
});

test('installation cannot persist one seeded registry when another cutover root is invalid', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate()), source = fixture('equipment-completion', 'EC-001').input;
  const consumed = fixture('equipment-history', 'EH-002').expected, empty = fixture('equipment-history', 'EH-001').expected;
  const root = (result: Row): BudgetRoot => ({ registry_digest: digest('reservation-registry', result.state.core.configuration), affected_anchors: [], state: structuredClone(result.state), state_digest: result.state_digest });
  const bad = root(consumed); bad.state.core.key_history[0].snapshot.coverage.complete = false;
  bad.state.core.key_history[0].snapshot_digest = digest('exclusive-history-snapshot', bad.state.core.key_history[0].snapshot);
  bad.state_digest = digest('reservation-state', bad.state);
  await assert.rejects(host.install(deploymentInput(source), [root(consumed), bad]), { code: 'STATE_INVALID' });
  const organization = source.state.deployment_organization_id;
  await assert.rejects(host.snapshot(organization, source.state.instance_id), /Instance is not installed/);
  assert.equal((await host.install(deploymentInput(source), [root(empty)])).disposition, 'INSTALLED');
  const snapshot = await host.snapshot(organization, source.state.instance_id);
  assert.equal(snapshot.budget_states[0].state_digest, empty.state_digest);
  assert.equal(snapshot.budget_states[0].state.core.key_history.length, 1);
});

test('proposal refusal, full authority evaluation and filtered referrals share one atomic host commit', async () => {
  const host = new SingleProcessReferenceHost(selectedCandidate()), source = fixture('equipment-referrals', 'EAR-003').input;
  const organization = source.state.deployment_organization_id;
  assert.equal((await host.install(deploymentInput(source))).disposition, 'INSTALLED');
  const clock = structuredClone(source);
  clock.event = { schema: VERSION + '/runtime-event', event_id: 'clock-1', kind: 'CLOCK', instance_id: source.state.instance_id, clock: source.state.clocks[0], activation_clocks: [] };
  assert.equal((await host.submit(organization, await current(host, organization, clock))).host_commit.disposition, 'COMMITTED');
  const input = await current(host, organization, source), before = await host.snapshot(organization, source.state.instance_id);
  const failed = await host.submit(organization, input, 'authority-refusal-commit-failure');
  assert.equal(failed.host_commit.disposition, 'COMMIT_FAILED');
  assert.equal(failed.transition.state.proposal_authority_evaluations.length, 1); assert.equal(failed.transition.state.referrals.length, 2);
  assert.deepEqual(await host.snapshot(organization, source.state.instance_id), before);
  const committed = await host.submit(organization, input); assert.equal(committed.host_commit.disposition, 'COMMITTED');
  assert.deepEqual(committed.transition.state.proposal_authority_evaluations[0].event, source.event);
  const replay = await host.submit(organization, await current(host, organization, input, true));
  assert.equal(replay.host_commit, null); assert.equal(replay.transition.replay, true);
  assert.equal(replay.transition.state.proposal_authority_evaluations.length, 1); assert.equal(replay.transition.state.referrals.length, 2);
});
