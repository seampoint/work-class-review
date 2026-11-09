import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { evaluateAuthority } from './authority.ts';
import { AdmissionError } from './canonical.ts';
import { typed } from './values.ts';
import type { RecordValue as Row, Types } from './values.ts';

function request(): Row {
  return JSON.parse(readFileSync(new URL('../cases/equipment-observations/C3-EO-001.json', import.meta.url), 'utf8')).input.request;
}

test('dependent relations refuse records with invalid field inventories or unproven relations', () => {
  const mutations: { mutate: (observation: Row) => void; reason: string }[] = [
    { mutate: row => { row.fields.push({ name: 'extra', value: { type_ref: 'BOOLEAN', value: true } }); }, reason: 'SOURCE_OBSERVATION_FIELDS' },
    { mutate: row => { row.relations = []; }, reason: 'SOURCE_OBSERVATION_RELATIONS' },
    { mutate: row => { row.fields.find((field: Row) => field.name === 'approval_actor').value.value = 'different-actor'; }, reason: 'SOURCE_OBSERVATION_RELATIONS' },
  ];
  for (const { mutate, reason } of mutations) {
    const input = request();
    mutate(input.observations.find((row: Row) => row.query.requirement_id === 'approval'));
    const result = evaluateAuthority(input, input.specification_pin);
    assert.equal(result.code, 'AUTHORITY_NOT_ESTABLISHED');
    assert.deepEqual(result.failed_checks.map((row: Row) => [row.requirement_ref, row.reason]).sort(), [
      ['approval', reason], ['current-session', 'SOURCE_OBSERVATION_RELATIONS'],
    ].sort());
  }
});

test('INSTANT rejects calendar overflow, leap seconds, fractions and offsets as typed value errors', () => {
  const types: Types = new Map([['time', { id: 'time', kind: 'INSTANT', unit: null, nonnegative: false }]]);
  typed({ type_ref: 'time', value: '2024-02-29T23:59:59Z' }, types);
  for (const value of ['0000-01-01T00:00:00Z', '2026-02-29T00:00:00Z', '2026-04-31T00:00:00Z', '2026-01-01T24:00:00Z', '2026-01-01T23:59:60Z', '2026-01-01T00:00:00.000000000Z', '2026-01-01T00:00:00+00:00', '10000-01-01T00:00:00Z']) {
    assert.throws(() => typed({ type_ref: 'time', value }, types), (error: unknown) => error instanceof AdmissionError && error.code === 'TYPE_INVALID');
  }
});

test('raw source observation date errors retain INPUT_INVALID admission', () => {
  const input = request();
  input.observations.find((row: Row) => row.query.requirement_id === 'approval').as_of = '2026-02-29T00:00:00Z';
  const result = evaluateAuthority(input, input.specification_pin);
  assert.equal(result.code, 'INPUT_INVALID');
  assert.deepEqual(result.reasons, []);
  assert.deepEqual(result.failed_checks, []);
});
