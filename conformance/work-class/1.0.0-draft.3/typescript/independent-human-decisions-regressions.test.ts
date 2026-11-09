import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { evaluateAuthority } from './authority.ts';
import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { admitDecisionDeclarations, bindDecisionInputs, decisionAct, selectedAuthorityAct } from './human-decisions.ts';
import { retainedSeparationAuthority } from './lifecycle.ts';
import { independentCorrection } from './source-corrections.ts';
import type { RecordValue as Row, Types } from './values.ts';

const source = (): Row => JSON.parse(readFileSync(new URL('../cases/cdmo-source/C3-CD-001.json', import.meta.url), 'utf8')).input.request;
const check = (condition: unknown, code: string): void => { if (!condition) throw new AdmissionError(code); };
const types = (input: Row): Types => new Map(input.work_class.types.map((row: Row) => [row.id, row]));
const sortActs = (input: Row): void => { input.acts.sort((a: Row, b: Row) => byteCompare(digest('authority-act', a), digest('authority-act', b))); };
const correctionSource = (): Row => JSON.parse(readFileSync(new URL('../cases/cdmo-source/C3-CD-184.json', import.meta.url), 'utf8')).input;
const correctionCheck = (input: Row): void => {
  const step = input.definition.steps.find((row: Row) => row.id === input.original_permit.occurrence.step_id);
  const fields = new Map<string, Row>(input.correction.corrected_fields.map((row: Row) => [row.name, row.value]));
  independentCorrection(input, step, fields, digest('source-correction-result', input.correction.corrected_fields));
};

// These calls isolate declaration/phase3 checks; source regressions reseal complete public inputs.
test('independent gate declaration binds the proposed step even when no current leaves are supplied', () => {
  const input = source();
  input.work_class.steps.push({ ...structuredClone(input.work_class.steps[0]), id: 'other-declared-step' });
  for (const declaration of input.envelope.decision_requirements) declaration.step = 'other-declared-step';
  input.decision_bases = [];
  assert.throws(() => bindDecisionInputs(input, check), { code: 'BINDING_MISMATCH' });
});

for (const member of ['principal', 'role']) test(`independent gate ${member} mismatch is phase3 binding`, () => {
  const input = source(), declaration = input.envelope.decision_requirements.find((row: Row) => row.id === input.envelope.gate.decision_requirement);
  declaration[member] = 'different-' + member;
  assert.doesNotThrow(() => admitDecisionDeclarations(input, types(input), check, check));
  assert.throws(() => bindDecisionInputs(input, check), { code: 'BINDING_MISMATCH' });
});

test('explicit empty bases omit unevaluated results on an earlier admission refusal', () => {
  const input = source(); input.decision_bases = [];
  assert.deepEqual(evaluateAuthority(input, input.specification_pin), { status: 'REFUSED', code: 'EVIDENCE_UNAVAILABLE', path: '', reasons: [], failed_checks: [] });
});

function padOccupancy(input: Row, target: number): void {
  const occupancy = input.occupancies[0], priorDigest = digest('authority-occupancy', occupancy);
  const authenticated = input.host_selection.authenticated_records.find((row: Row) => row.kind === 'OCCUPANCY' && row.record_digest === priorDigest);
  assert.ok(authenticated);
  occupancy.evidence_ref = 'é';
  occupancy.evidence_ref += 'x'.repeat(target - Buffer.byteLength(canonical(input)));
  authenticated.record_digest = digest('authority-occupancy', occupancy);
  input.host_selection.authenticated_records.sort((a: Row, b: Row) => byteCompare(canonical(a), canonical(b)));
  assert.equal(Buffer.byteLength(canonical(input)), target);
  assert.ok(canonical(input).length < target, 'the boundary must count UTF-8 bytes');
}

for (const family of ['outer', 'leaf']) {
  for (const extra of [0, 1]) test(`${family} independent evidence admits its exact canonical byte limit and refuses limit plus one (${extra})`, () => {
    const input = source(), selected = family === 'outer' ? input : input.decision_bases[0].evidence.authority_input;
    padOccupancy(selected, (family === 'outer' ? 1048576 : 262144) + extra);
    if (family === 'leaf') assert.ok(Buffer.byteLength(canonical(input)) <= 1048576);
    const result = evaluateAuthority(input, input.specification_pin);
    if (extra === 0) assert.equal(result.status, 'READY_FOR_RESERVATION', JSON.stringify(result));
    else assert.equal(result.code, 'LIMIT_EXCEEDED', JSON.stringify(result));
  });
}

test('decision records require dispatch evaluation only when selected by a source-vector gate', () => {
  const input = source(), step = input.work_class.steps.find((row: Row) => row.id === input.proposal.step);
  const gate = structuredClone(step.dispatch_gate);
  delete step.dispatch_gate;
  for (const declaration of input.envelope.decision_requirements) {
    input.envelope.source_observation_requirements.find((row: Row) => row.id === declaration.record_requirement_id).evaluation_point = 'PROPOSE';
  }
  assert.doesNotThrow(() => admitDecisionDeclarations(input, types(input), check, check));
  step.dispatch_gate = gate;
  assert.throws(() => admitDecisionDeclarations(input, types(input), check, check), { code: 'UNSUPPORTED_RELATION' });
});

test('declaration admission rejects a decision record without an immutable issue id', () => {
  const input = source();
  input.envelope.source_observation_requirements.find((row: Row) => row.id === input.envelope.decision_requirements[0].record_requirement_id).record_id = null;
  assert.throws(() => admitDecisionDeclarations(input, types(input), check, check), { code: 'UNSUPPORTED_RELATION' });
});

test('decision declaration and binding use criteria from the selected step', () => {
  const input = source(), criterion = structuredClone(input.envelope.gate.criteria[0]);
  criterion.id = 'unrelated-step-criterion'; criterion.step = 'unrelated-step';
  const step = structuredClone(input.work_class.steps.find((row: Row) => row.id === input.proposal.step));
  step.id = criterion.step; delete step.dispatch_gate;
  input.work_class.steps.push(step);
  input.envelope.gate.criteria.push(criterion);
  input.envelope.gate.criteria.sort((a: Row, b: Row) => byteCompare(a.id, b.id));
  assert.doesNotThrow(() => admitDecisionDeclarations(input, types(input), check, check));
  assert.doesNotThrow(() => bindDecisionInputs(input, check));
  input.envelope.gate.criteria.find((row: Row) => row.step === input.proposal.step).predicate = structuredClone(criterion.predicate);
  input.envelope.gate.criteria.find((row: Row) => row.step === input.proposal.step).id = 'different-selected-criterion';
  assert.throws(() => bindDecisionInputs(input, check), { code: 'BINDING_MISMATCH' });
});

test('decision wrapper mismatch precedes missing act returns', () => {
  const input = source(), evidence = input.decision_bases[0].evidence, leaf = evidence.authority_input;
  evidence.decision_act_digest = digest('wrong-decision-wrapper', {});
  leaf.returns = [];
  leaf.host_selection.authenticated_records = leaf.host_selection.authenticated_records.filter((row: Row) => row.kind !== 'RETURN');
  const result = evaluateAuthority(input, input.specification_pin);
  assert.equal(result.code, 'BINDING_MISMATCH');
});

for (const member of ['actor', 'role', 'principal', 'occupancy']) test(`historical decision executor ${member} mismatch is a phase-three binding refusal`, () => {
  const input = source(), evidence = input.decision_bases[0].evidence, leaf = evidence.authority_input;
  const act = leaf.acts.find((row: Row) => row.kind === 'INSTANCE_DECISION');
  act[member] += '-other';
  evidence.decision_act_digest = digest('authority-act', act);
  sortActs(leaf);
  const result = evaluateAuthority(input, input.specification_pin);
  assert.equal(result.code, 'BINDING_MISMATCH');
});

// These helper tests isolate post-admission correction checks; full evidence admission is tested by source cases.
test('business correction missing a required fresh decision is evidence unavailable', () => {
  const input = correctionSource();
  input.correction.correction_authority_input.decision_bases = input.correction.correction_authority_input.decision_bases.filter((row: Row) => row.requirement_id !== 'alder-decision');
  assert.throws(() => correctionCheck(input), { code: 'EVIDENCE_UNAVAILABLE' });
});

test('correction freshness rejects original issue and act identities across requirements', () => {
  assert.doesNotThrow(() => correctionCheck(correctionSource()));
  for (const mode of ['first-other-id', 'second-other-id', 'swapped-original-ids', 'other-original-act']) {
    const input = correctionSource(), original = input.original_permit.authority_basis, current = input.correction.correction_authority_input;
    const originalActs = current.decision_bases.map((row: Row) => decisionAct(original, row.requirement_id)!);
    for (const [index, row] of current.decision_bases.entries()) {
      if (mode === 'first-other-id' && index !== 0 || mode === 'second-other-id' && index !== 1 || mode === 'other-original-act' && index !== 0) continue;
      const leaf = row.evidence.authority_input, selected = decisionAct(current, row.requirement_id)!;
      const other = originalActs[1 - index];
      if (mode === 'other-original-act') leaf.acts[leaf.acts.indexOf(selected)] = structuredClone(other);
      else selected.id = other.id;
      row.evidence.decision_act_digest = digest('authority-act', mode === 'other-original-act' ? other : selected);
    }
    assert.throws(() => correctionCheck(input), { code: 'BINDING_MISMATCH' }, mode);
  }
});

test('correction helper rejects another original canonical issuance identity', () => {
  const input = correctionSource(), original = input.original_permit.authority_basis, current = input.correction.correction_authority_input;
  const step = input.definition.steps.find((row: Row) => row.id === input.original_permit.occurrence.step_id), policy = step.completion.correction_policy;
  const fresh = policy.business_decision_requirements[0], other = original.envelope.decision_requirements.find((row: Row) => row.id !== fresh.id);
  const oldField = original.decision_bases.find((row: Row) => row.requirement_id === other.id).evidence.authority_input.proposal.fields.find((row: Row) => row.name === other.identity_field);
  const proposalField = fresh.context_bindings.find((row: Row) => row.field === fresh.identity_field).value.field;
  const nativeField = policy.business_context_bindings.find((row: Row) => row.proposal_field === proposalField).value.field;
  input.correction.corrected_fields.find((row: Row) => row.name === nativeField).value = structuredClone(oldField.value);
  input.correction.changes.find((row: Row) => row.field === nativeField).new_value = structuredClone(oldField.value);
  current.proposal.fields.find((row: Row) => row.name === proposalField).value = structuredClone(oldField.value);
  current.proposal.fields.find((row: Row) => row.name === policy.result_digest_field).value.value = digest('source-correction-result', input.correction.corrected_fields);
  current.proposal.fields.find((row: Row) => row.name === policy.changes_digest_field).value.value = digest('source-correction-changes', input.correction.changes);
  assert.throws(() => correctionCheck(input), { code: 'BINDING_MISMATCH' });
});

for (const control of ['original_id_field', 'original_digest_field', 'original_revision_field', 'changes_digest_field', 'result_digest_field', 'outside-business-context']) {
  test(`correction decisions cannot select ${control}`, () => {
    const input = correctionSource(), step = input.definition.steps.find((row: Row) => row.id === input.original_permit.occurrence.step_id), policy = step.completion.correction_policy;
    const declaration = policy.business_decision_requirements[0];
    declaration.context_bindings.find((row: Row) => row.value.kind === 'PROPOSAL_FIELD' && row.field !== declaration.identity_field).value.field = control === 'outside-business-context' ? 'undeclared-business-field' : policy[control];
    input.correction.correction_authority_input.envelope.decision_requirements = structuredClone(policy.business_decision_requirements);
    assert.throws(() => correctionCheck(input), { code: 'BINDING_MISMATCH' });
  });
}

// This production helper checks carrier/selection admission; its caller checks definition, history and accepted clock.
test('retained separation admits exactly the gate leaf and requires its complete authority carrier', () => {
  const fixture = JSON.parse(readFileSync(new URL('../cases/cdmo-source/C3-CD-001.json', import.meta.url), 'utf8'));
  const authority = fixture.input.request, kind = 'INSTANCE_DECISION';
  const detail: Row = { authority_result: fixture.expected, authority_basis: authority, basis: { current_act: selectedAuthorityAct(authority, kind)[0] } };
  assert.equal(retainedSeparationAuthority(detail, kind, authority.specification_pin), authority);
  const nonGate = authority.decision_bases.find((row: Row) => row.requirement_id !== authority.envelope.gate.decision_requirement);
  const otherAct = decisionAct(authority, nonGate.requirement_id)!;
  const changed = structuredClone(detail);
  changed.basis.current_act = { act_digest: digest('authority-act', otherAct), act: otherAct };
  assert.throws(() => retainedSeparationAuthority(changed, kind, authority.specification_pin), { code: 'STATE_INVALID' });
  const missing = structuredClone(detail); delete missing.authority_basis;
  assert.throws(() => retainedSeparationAuthority(missing, kind, authority.specification_pin), { code: 'STATE_INVALID' });
  const inconsistent = structuredClone(detail); inconsistent.authority_basis.clock.instant = '2026-10-06T12:10:01Z';
  assert.throws(() => retainedSeparationAuthority(inconsistent, kind, authority.specification_pin), { code: 'STATE_INVALID' });
  detail.basis.current_act = selectedAuthorityAct(authority, 'GRANT')[0];
  assert.equal(retainedSeparationAuthority(detail, 'GRANT', authority.specification_pin), authority);
  delete detail.authority_basis;
  assert.throws(() => retainedSeparationAuthority(detail, 'GRANT', authority.specification_pin), { code: 'STATE_INVALID' });
});

test('ordinary retained separation omits the independent carrier for omitted and empty decision results', () => {
  const authority = source(), current = selectedAuthorityAct(authority, 'GRANT')[0];
  for (const results of [undefined, []]) {
    const detail: Row = { authority_result: { act_digests: [current.act_digest], ...(results === undefined ? {} : { decision_results: results }) }, basis: { current_act: current } };
    assert.equal(retainedSeparationAuthority(detail, 'GRANT', authority.specification_pin), undefined);
    detail.authority_basis = authority;
    assert.throws(() => retainedSeparationAuthority(detail, 'GRANT', authority.specification_pin), { code: 'STATE_INVALID' });
  }
});
