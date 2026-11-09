import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { digest } from './canonical.ts';
import { deploy, stateDigest, step } from './lifecycle.ts';
import { VERSION } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);
const caseFile = (path: string): Row => JSON.parse(readFileSync(new URL(path, candidate), 'utf8'));

function stateRequest(path: string, mutate: (state: Row) => void): Row {
  const source = caseFile(path);
  const request = structuredClone(source.input);
  mutate(request.state);
  request.state_digest = stateDigest(request.state);
  return request;
}

function stateInvalid(request: Row): void {
  const result = step(request, request.specification_pin);
  assert.equal(result.status, 'REFUSED');
  assert.equal(result.code, 'STATE_INVALID');
}

function without(row: Row, key: string): Row { const value = structuredClone(row); delete value[key]; return value; }

test('deploy schema refusal omits profile metadata before input admission', () => {
  const source = caseFile('cases/generated-completion/C3-GEN-022.json');
  assert.deepEqual(deploy(source.input, source.input.specification_pin), { status: 'REFUSED', code: 'SCHEMA_INVALID', path: '' });
});

function resealState(request: Row): void {
  const state = request.state, core = structuredClone(state);
  core.receipts = []; core.replays = [];
  state.receipts.at(-1).state_after_core_digest = digest('work-state-core', core);
  for (const receipt of state.receipts) {
    receipt.decision_id = digest('decision-receipt', without(receipt, 'decision_id'));
    const replay = state.replays.find((row: Row) => row.event_id === receipt.event_id);
    replay.event_digest = receipt.event_digest; replay.decision = structuredClone(receipt); replay.decision_receipt_digest = receipt.decision_id;
    replay.transition_state_digest = receipt.state_after_core_digest;
    replay.transaction_digest = digest('lifecycle-transaction', { state_before_digest: receipt.state_before_digest, event_digest: receipt.event_digest, decision_receipt_digest: receipt.decision_id, state_after_core_digest: receipt.state_after_core_digest, budget_results: replay.budget_results });
  }
  request.state_digest = stateDigest(state);
}

function authorizationRequest(mutate: (authorization: Row) => void, template = caseFile('cases/equipment-dispatch/C3-ED-017.json').input): Row {
  const request = structuredClone(template), state = request.state;
  const authorization = state.authorizations[0], evaluation = state.authorization_evaluations[0];
  const receipt = state.receipts.find((row: Row) => row.event_id === authorization.event_id), permit = state.permits.find((row: Row) => row.permit_id === authorization.permit_digest);
  mutate(authorization);
  authorization.authority_result_digest = digest('authority-result', authorization.authority_result);
  authorization.authorization_fence.scope_digest = digest('dispatch-authorization-scope', {
    instance_id: state.instance_id, occurrence_id: permit.occurrence.occurrence_id, permit_digest: permit.permit_id,
    native_request: authorization.native_request, connector: authorization.connector, dispatch_intent_id: authorization.dispatch_intent_id,
    checked_at: authorization.authorization_fence.checked_at, expires_at: authorization.expires_at, authority_result_digest: authorization.authority_result_digest, sources: authorization.authorization_fence.sources,
  });
  const event = {
    schema: VERSION + '/runtime-event', event_id: authorization.event_id, kind: 'AUTHORIZE_DISPATCH', instance_id: state.instance_id,
    expected_state_revision: String(BigInt(receipt.sequence) - 1n), expected_state_digest: receipt.state_before_digest, permit,
    native_request: authorization.native_request, connector: authorization.connector, authorization_fence: authorization.authorization_fence,
    observation_digests: authorization.observation_digests, clock_revision: authorization.clock_revision, authority_input: authorization.authority_input, dispatch_intent_id: authorization.dispatch_intent_id,
  };
  authorization.event_digest = digest('runtime-event', event);
  authorization.authorization_digest = digest('dispatch-authorization', without(authorization, 'authorization_digest'));
  Object.assign(evaluation, {
    event_digest: authorization.event_digest, authority_input: structuredClone(authorization.authority_input), authority_result: structuredClone(authorization.authority_result),
    authority_result_digest: authorization.authority_result_digest, authorization_digest: authorization.authorization_digest, clock_revision: authorization.clock_revision,
  });
  evaluation.evaluation_digest = digest('dispatch-authorization-evaluation', without(evaluation, 'evaluation_digest'));
  receipt.event_digest = evaluation.event_digest; receipt.authority_result_digest = evaluation.authority_result_digest; receipt.authorization_evaluation_digest = evaluation.evaluation_digest;
  receipt.details = [{ kind: 'AUTHORIZATION', authorization_digest: authorization.authorization_digest, permit_digest: permit.permit_id, approval_id: authorization.authorization_fence.approval_id, checked_at: authorization.authorization_fence.checked_at, expires_at: authorization.expires_at, sources: structuredClone(authorization.authorization_fence.sources) }];
  resealState(request);
  return request;
}

test('accepts a retained permit chain and its budget projection before event admission', () => {
  const source = caseFile('cases/additional-precedence/D2-069.json');
  const result = step(source.input, source.input.specification_pin);
  assert.notEqual(result.code, 'STATE_INVALID');
});

test('rejects a renewal proposal whose predecessor link is missing', () => {
  stateInvalid(stateRequest('cases/permit-renewal/D2-175.json', state => {
    const renewal = state.proposals.find((row: Row) => row.event_id === 'renewal-d2-170');
    assert.ok(renewal);
    renewal.prior_permit_digest = null;
  }));
});

test('rejects a permit proposal whose retained budget receipt projection changed', () => {
  stateInvalid(stateRequest('cases/additional-precedence/D2-069.json', state => {
    const proposal = state.proposals[0];
    assert.equal(proposal.reservation_receipt_digests.length, 1);
    proposal.reservation_receipt_digests = [];
  }));
});

test('accepts rehashed retained gated evidence before admitting the next event', () => {
  const request = authorizationRequest(() => {});
  assert.notEqual(step(request, request.specification_pin).code, 'STATE_INVALID');
});

test('restart recomputes full authority results and exclusive authorization expiry after digest checks', () => {
  stateInvalid(authorizationRequest(row => { row.authority_result.evidence_digest = digest('invented-authority-evidence', { id: 'wrong' }); }));
  stateInvalid(authorizationRequest(row => { row.expires_at = row.expires_at.replace('04:31:00Z', '04:31:01Z'); }));
});

test('restart rejects a rehashed connector substitution and source revision substitution', () => {
  stateInvalid(authorizationRequest(row => { row.connector.id = 'substituted-connector'; }));
  stateInvalid(authorizationRequest(row => { row.authorization_fence.sources[0].provider_revision = 'substituted-revision'; }));
});

test('restart rejects a later accepted clock substituted into an earlier evaluation', () => {
  const clockRequest = structuredClone(caseFile('cases/equipment-dispatch/C3-ED-017.json').input);
  const clock = { ...structuredClone(clockRequest.state.clocks[0]), revision: '2', evidence_digest: digest('later-evaluation-clock', { id: 'clock-2' }) };
  clockRequest.event = { schema: VERSION + '/runtime-event', event_id: 'later-evaluation-clock', kind: 'CLOCK', instance_id: clockRequest.state.instance_id, expected_state_revision: clockRequest.state.revision, expected_state_digest: clockRequest.state_digest, clock, activation_clocks: [] };
  const accepted = step(clockRequest, clockRequest.specification_pin);
  assert.equal(accepted.status, 'STEP');
  clockRequest.state = accepted.state; clockRequest.state_digest = accepted.state_digest;
  stateInvalid(authorizationRequest(row => { row.clock_revision = '2'; }, clockRequest));
});

test('restart requires the complete gated permit authority basis after permit digest checks', () => {
  const request = structuredClone(caseFile('cases/equipment-dispatch/C3-ED-003.json').input), state = request.state;
  const permit = state.permits[0], prior = permit.permit_id;
  delete permit.authority_basis;
  permit.permit_id = digest('permit', without(permit, 'permit_id'));
  for (const proposal of state.proposals) if (proposal.permit_digest === prior) proposal.permit_digest = permit.permit_id;
  for (const receipt of state.receipts) if (receipt.permit_digest === prior) receipt.permit_digest = permit.permit_id;
  for (const replay of state.replays) if (replay.permit?.permit_id === prior) replay.permit = structuredClone(permit);
  request.event.permit = structuredClone(permit);
  resealState(request);
  stateInvalid(request);
});
