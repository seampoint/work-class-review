import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { stateDigest, step } from './lifecycle.ts';
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
