import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { AdmissionError } from './canonical.ts';
import { validateWorkClass } from './work-class.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);
const caseFile = (path: string): Row => JSON.parse(readFileSync(new URL(path, candidate), 'utf8'));

function definition(path: string): Row { return caseFile(path).input.definition; }

const pin = definition('cases/authority-withholding/D2-014.json').specification_pin;

function refused(value: Row, code: string, path?: string): void {
  assert.throws(() => validateWorkClass(value, pin), (error: unknown) => error instanceof AdmissionError && error.code === code && (path === undefined || error.path === path));
}

test('retains admitted loop and structured definitions', () => {
  assert.doesNotThrow(() => validateWorkClass(definition('cases/bounded-loops/D2-048.json'), pin));
  assert.doesNotThrow(() => validateWorkClass(definition('cases/parallel-completion/D2-052.json'), pin));
  assert.doesNotThrow(() => validateWorkClass(definition('cases/fanout-expansion/D2-054.json'), pin));
});

test('rejects explicit split edges and paths that bypass a structured join', () => {
  const splitEdge = structuredClone(definition('cases/parallel-completion/D2-052.json'));
  splitEdge.relationships.push({ from: 'parallel-split', kind: 'SEQUENCE', to: 'terminal' });
  refused(splitEdge, 'DEFINITION_INVALID');

  const bypass = structuredClone(definition('cases/parallel-completion/D2-052.json'));
  const branchEdge = bypass.relationships.find((edge: Row) => edge.from === 'branch-a' && edge.kind === 'SEQUENCE');
  assert.ok(branchEdge);
  branchEdge.to = 'terminal';
  refused(bypass, 'DEFINITION_INVALID');
});

test('rejects undeclared and malformed loop cycles', () => {
  const undeclared = structuredClone(definition('cases/bounded-loops/D2-048.json'));
  undeclared.loops = [];
  refused(undeclared, 'UNSUPPORTED_FEATURE');

  const wrongEntry = structuredClone(definition('cases/bounded-loops/D2-048.json'));
  wrongEntry.loops[0].entry_step_id = 'terminal';
  refused(wrongEntry, 'UNSUPPORTED_FEATURE');
});

test('requires occurrence limits for proposal steps and enforces candidate ceilings', () => {
  const missing = structuredClone(definition('cases/authority-withholding/D2-014.json'));
  missing.occurrence_limits = [];
  refused(missing, 'DEFINITION_INVALID');

  const proposals = structuredClone(definition('cases/authority-withholding/D2-014.json'));
  proposals.limits.maximum_proposals = '4097';
  refused(proposals, 'DEFINITION_INVALID');

  const activations = structuredClone(definition('cases/authority-withholding/D2-014.json'));
  activations.limits.maximum_activations = '4097';
  refused(activations, 'DEFINITION_INVALID');

  const structural = structuredClone(definition('cases/parallel-completion/D2-052.json'));
  structural.occurrence_limits.push({ maximum: '1', step_id: 'parallel-split' });
  refused(structural, 'DEFINITION_INVALID');

  const zeroBranch = structuredClone(definition('cases/parallel-entry/D2-051.json'));
  assert.doesNotThrow(() => validateWorkClass(zeroBranch, pin));

  const zeroRoot = structuredClone(definition('cases/authority-withholding/D2-014.json'));
  zeroRoot.occurrence_limits.find((row: Row) => row.step_id === zeroRoot.root).maximum = '0';
  refused(zeroRoot, 'DEFINITION_INVALID');

  const zeroLoopMember = structuredClone(definition('cases/bounded-loops/D2-048.json'));
  const retry = structuredClone(zeroLoopMember.steps.find((step: Row) => step.id === 'issue'));
  retry.id = 'retry'; retry.operation = 'retry-card';
  zeroLoopMember.steps.push(retry);
  zeroLoopMember.steps.sort((left: Row, right: Row) => Buffer.from(left.id).compare(Buffer.from(right.id)));
  zeroLoopMember.relationships.find((edge: Row) => edge.from === 'issue' && edge.label?.value === 'CONTINUE').to = 'retry';
  zeroLoopMember.relationships.push(
    { from: 'retry', kind: 'LABEL', label: { type_ref: 'STRING', value: 'CONTINUE' }, to: 'issue' },
    { from: 'retry', kind: 'LABEL', label: { type_ref: 'STRING', value: 'EXIT' }, to: 'terminal' },
  );
  zeroLoopMember.choices.push({ ...structuredClone(zeroLoopMember.choices[0]), step_id: 'retry' });
  zeroLoopMember.choices.sort((left: Row, right: Row) => Buffer.from(left.step_id).compare(Buffer.from(right.step_id)));
  zeroLoopMember.occurrence_limits.push({ maximum: '0', step_id: 'retry' });
  zeroLoopMember.occurrence_limits.sort((left: Row, right: Row) => Buffer.from(left.step_id).compare(Buffer.from(right.step_id)));
  zeroLoopMember.loops[0].member_step_ids = ['issue', 'retry'];
  zeroLoopMember.loops[0].back_edge_from_step_id = 'retry';
  refused(zeroLoopMember, 'DEFINITION_INVALID');
});

test('rejects duplicate structured owners', () => {
  const parallel = structuredClone(definition('cases/parallel-completion/D2-052.json'));
  const duplicateBlock = structuredClone(parallel.parallel_blocks[0]);
  duplicateBlock.id = 'parallel-2';
  parallel.parallel_blocks.push(duplicateBlock);
  refused(parallel, 'DEFINITION_INVALID');

  const fanout = structuredClone(definition('cases/fanout-expansion/D2-054.json'));
  const duplicateFanout = structuredClone(fanout.fanouts[0]);
  duplicateFanout.id = 'fanout-2';
  fanout.fanouts.push(duplicateFanout);
  refused(fanout, 'DEFINITION_INVALID');
});

test('rejects unowned structural steps and structured steps below their profile', () => {
  const unowned = structuredClone(definition('cases/authority-withholding/D2-014.json'));
  const terminal = unowned.steps.find((step: Row) => step.id === 'terminal');
  assert.ok(terminal);
  unowned.steps.push({ ...structuredClone(terminal), id: 'unowned-join', kind: 'PARALLEL_JOIN' });
  unowned.steps.sort((left: Row, right: Row) => Buffer.from(left.id).compare(Buffer.from(right.id)));
  const issueEdge = unowned.relationships.find((edge: Row) => edge.from === 'issue');
  assert.ok(issueEdge);
  issueEdge.to = 'unowned-join';
  unowned.relationships.push({ from: 'unowned-join', kind: 'SEQUENCE', to: 'terminal' });
  refused(unowned, 'UNSUPPORTED_FEATURE', '/profile');

  unowned.profile = 'PARALLEL_FANOUT';
  refused(unowned, 'DEFINITION_INVALID', '/parallel_blocks');
});

test('rejects partially overlapping fan-out regions', () => {
  const crossed = structuredClone(definition('cases/nested-fanout-binding/D2-253.json'));
  const outerJoin = crossed.steps.find((step: Row) => step.id === 'outer-join');
  const operation = crossed.steps.find((step: Row) => step.id === 'inner-operation');
  assert.ok(outerJoin && operation);
  crossed.steps = crossed.steps.filter((step: Row) => step.id !== 'outer-join');
  crossed.steps.push({ ...structuredClone(operation), id: 'middle-operation', operation: 'middle-operation' });
  crossed.steps.push({ ...structuredClone(outerJoin), id: 'new-join' });
  crossed.steps.sort((left: Row, right: Row) => Buffer.from(left.id).compare(Buffer.from(right.id)));
  crossed.occurrence_limits.push({ maximum: '1', step_id: 'middle-operation' });
  crossed.occurrence_limits.sort((left: Row, right: Row) => Buffer.from(left.step_id).compare(Buffer.from(right.step_id)));
  crossed.relationships = [
    { from: 'inner-operation', kind: 'SEQUENCE', to: 'inner-join' },
    { from: 'inner-join', kind: 'SEQUENCE', to: 'middle-operation' },
    { from: 'middle-operation', kind: 'SEQUENCE', to: 'new-join' },
    { from: 'new-join', kind: 'SEQUENCE', to: 'terminal' },
  ];
  crossed.fanouts.find((fanout: Row) => fanout.id === 'fanout-outer').join_step_id = 'inner-join';
  crossed.fanouts.find((fanout: Row) => fanout.id === 'fanout-inner').join_step_id = 'new-join';
  refused(crossed, 'DEFINITION_INVALID', '/steps');
});
