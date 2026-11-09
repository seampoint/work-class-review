import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { respond } from './adapter.ts';
import { canonical } from './canonical.ts';
import { PROTOCOL, selectedCandidate } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);

test('matches all frozen equipment source decisions without mutating their complete supplied evidence', () => {
  const pin = selectedCandidate(), index = JSON.parse(readFileSync(new URL('cases/index.json', candidate), 'utf8')).cases as Row[];
  const cases = index.filter(row => row.id.startsWith('C3-ES-') && row.execution_target === 'ADAPTER');
  assert.equal(cases.length, 147);
  for (const row of cases) {
    const fixture = JSON.parse(readFileSync(new URL(row.path, candidate), 'utf8')), before = canonical(fixture.input);
    const result = respond({ protocol: PROTOCOL, request_id: fixture.id, operation: fixture.operation, input: fixture.input }, pin).result;
    assert.equal(canonical(result), canonical(fixture.expected), row.id);
    assert.equal(canonical(fixture.input), before, row.id);
  }
});
