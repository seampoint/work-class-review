import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { respond } from './adapter.ts';
import { canonical, digest } from './canonical.ts';
import { PROTOCOL, selectedCandidate } from './schema.ts';
import { validateWorkClass } from './work-class.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);
const index = JSON.parse(readFileSync(new URL('cases/index.json', candidate), 'utf8')).cases as Row[];

test('all 94 frozen corrections recompute exact authority without changing the supplied original evidence', () => {
  const pin = selectedCandidate(); let count = 0;
  for (const row of index.filter(row => row.path.startsWith('cases/equipment-correction/'))) {
    const source = JSON.parse(readFileSync(new URL(row.path, candidate), 'utf8'));
    const original = canonical(source.input);
    const result = respond({ protocol: PROTOCOL, request_id: source.id, operation: source.operation, input: source.input }, pin).result as Row;
    assert.equal(canonical(result), canonical(source.expected), source.id);
    assert.equal(canonical(source.input), original, source.id);
    for (const name of ['state', 'registry', 'budget_states', 'terminal_records', 'referrals', 'dispatch_performed']) assert.equal(Object.hasOwn(result, name), false, `${source.id}/${name}`);
    count++;
  }
  assert.equal(count, 94);
});

test('correction and approval operations can independently declare the same commitment field name', () => {
  const source = JSON.parse(readFileSync(new URL('cases/equipment-correction/C3-ER-001.json', candidate), 'utf8'));
  const definition = structuredClone(source.input.definition), policy = definition.steps.find((row: Row) => row.completion?.correction_policy).completion.correction_policy;
  policy.result_digest_field = policy.original_digest_field;
  assert.doesNotThrow(() => validateWorkClass(definition, source.input.specification_pin));
});

test('matches frozen authority referrals, ungated completions and fully rebound retained evidence faults', t => {
  const pin = selectedCandidate(); let count = 0;
  for (const group of ['equipment-referrals', 'equipment-ungated-completion', 'equipment-retained-evidence']) {
    for (const row of index.filter(row => row.path.startsWith(`cases/${group}/`))) {
      const source = JSON.parse(readFileSync(new URL(row.path, candidate), 'utf8'));
      const result = respond({ protocol: PROTOCOL, request_id: source.id, operation: source.operation, input: source.input }, pin).result;
      assert.equal(canonical(result), canonical(source.expected), source.id); count++;
    }
  }
  assert.ok(count >= 18);
  t.diagnostic(JSON.stringify({ indexed_referral_ungated_and_retained_evidence_cases: count }));
});

test('original permit expiry and outer date precedence are independently checked after digest resealing', () => {
  const source = JSON.parse(readFileSync(new URL('cases/equipment-correction/C3-ER-001.json', candidate), 'utf8'));
  const changed = structuredClone(source.input), permit = changed.original_permit;
  permit.expires_at = '2026-09-12T14:30:01Z';
  const body = structuredClone(permit); delete body.permit_id; permit.permit_id = digest('permit', body);
  const result = respond({ protocol: PROTOCOL, request_id: 'resealed-old-expiry', operation: 'check-evidence', input: changed }, selectedCandidate()).result as Row;
  assert.equal(result.code, 'DEPENDENCY_MISMATCH');
  const dates = structuredClone(source.input); dates.definition_digest = digest('wrong-definition', {});
  dates.correction.custodian_return.at = '2026-02-31T15:00:00Z';
  const invalid = respond({ protocol: PROTOCOL, request_id: 'outer-date-precedence', operation: 'check-evidence', input: dates }, selectedCandidate()).result as Row;
  assert.equal(invalid.code, 'INPUT_INVALID');
});

test('the final operation declarations and reservation capability reject inherited omissions', () => {
  const source = JSON.parse(readFileSync(new URL('cases/equipment-correction/C3-ER-001.json', candidate), 'utf8'));
  const omitted = structuredClone(source.input.definition), operation = omitted.steps.find((row: Row) => row.kind === 'OPERATION');
  delete operation.quantity_mode;
  assert.throws(() => validateWorkClass(omitted, source.input.specification_pin), { code: 'SCHEMA_INVALID' });
  const structural = structuredClone(source.input.definition), terminal = structural.steps.find((row: Row) => row.kind === 'TERMINAL');
  terminal.quantity_mode = 'NONE';
  assert.throws(() => validateWorkClass(structural, source.input.specification_pin), { code: 'DEFINITION_INVALID' });
  const capabilities = respond({ protocol: PROTOCOL, request_id: 'migrated-roles', operation: 'capabilities', input: {} }, selectedCandidate()).result as Row;
  assert.ok(capabilities.roles.includes('RESERVATION_TRANSITIONS')); assert.equal(capabilities.roles.includes('SHARED_BUDGET_TRANSITIONS'), false);
});
