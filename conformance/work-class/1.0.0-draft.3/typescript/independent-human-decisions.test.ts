import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { AdmissionError, canonical, digest } from './canonical.ts';
import { admitCompletion, terminalFieldsMatch } from './completion.ts';
import { immutableAuthority } from './dispatch-authority.ts';
import { admitDecisionInputs, bindDecisionInputs, effectiveUntil, independentActors, selectedAuthorityAct } from './human-decisions.ts';
import { admitSourceRequirements, deriveSourceQueries, sourcePolicyFailures } from './source-observations.ts';
import { validateWorkClass } from './work-class.ts';
import { aggregateStep, recoveryControllerActors } from './reservations.ts';
import { deploy, step, workRecoveryControllerActors } from './lifecycle.ts';
import { selectedCandidate } from './schema.ts';
import type { RecordValue as Row, ScalarType, Types } from './values.ts';

const time = (minute: string): string => `2026-10-06T12:${minute}:00Z`;
const scalar = (id: string, kind: string): ScalarType => ({ id, kind, unit: null, nonnegative: false });
const types: Types = new Map([['IDENTITY', scalar('IDENTITY', 'IDENTITY')], ['TIME', scalar('TIME', 'INSTANT')], ['STATUS', scalar('STATUS', 'STRING')]]);
const check = (condition: unknown, code: string): void => { if (!condition) throw new AdmissionError(code); };
const refuses = (code: string) => (error: unknown): boolean => error instanceof AdmissionError && error.code === code;
const literal = (type_ref: string, value: string): Row => ({ kind: 'LITERAL', value: { type_ref, value } });

function independentInput(): Row {
  const record = { id: 'decision-record', step: 'execute', provider: 'quality', source: 'decisions', record_type: 'approval', record_id: 'approval-1' };
  const fields = [{ name: 'approval_identity', type_ref: 'IDENTITY' }, { name: 'not_after', type_ref: 'TIME' }, { name: 'not_before', type_ref: 'TIME' }, { name: 'result', type_ref: 'STATUS' }];
  const identity = canonical({ provider: record.provider, source: record.source, record_type: record.record_type, provider_record_id: record.record_id });
  const context_bindings = fields.map(field => ({ field: field.name, value: { kind: 'PROPOSAL_FIELD', field: field.name } }));
  const act = { id: record.record_id, kind: 'INSTANCE_DECISION', actor: 'human-1', principal: 'quality-principal', role: 'Quality', occurred_at: time('05') };
  const criterion = { id: 'approved-result', step: 'execute', predicate: { kind: 'EQUAL', left: { kind: 'FIELD', name: 'result' }, right: literal('STATUS', 'APPROVED') } };
  const leaf: Row = {
    work_class: { types: structuredClone([...types.values()]), steps: [{ id: 'human', fields }] },
    envelope: { principal: 'quality-principal', clock_source: 'human-clock', temporal_validity: { valid_from: time('00'), valid_until: time('30') }, gate: { kind: 'DECIDE', role: 'Quality', criteria: [{ ...structuredClone(criterion), step: 'human' }] } },
    proposal: { step: 'human', fields: [{ name: 'approval_identity', value: { type_ref: 'IDENTITY', value: identity } }, { name: 'not_after', value: { type_ref: 'TIME', value: time('30') } }, { name: 'not_before', value: { type_ref: 'TIME', value: time('00') } }, { name: 'result', value: { type_ref: 'STATUS', value: 'APPROVED' } }] },
    acts: [act], clock: { source: 'human-clock', status: 'AVAILABLE', instant: time('10') }, observations: [], evaluation_point: 'PROPOSE',
  };
  const required = { id: 'quality-decision', step: 'execute', principal: 'quality-principal', role: 'Quality', record_requirement_id: record.id, identity_field: 'approval_identity', validity_fields: { not_before_field: 'not_before', not_after_field: 'not_after' }, context_bindings, distinct_from: [], work_class_digest: digest('authority-work-class', leaf.work_class), envelope_digest: digest('authority-envelope', leaf.envelope) };
  return { work_class: { types: [...types.values()], steps: [{ id: 'execute', fields }] }, envelope: { principal: required.principal, gate: { kind: 'DECIDE', role: required.role, decision_requirement: required.id, criteria: [criterion] }, decision_requirements: [required], source_observation_requirements: [record] }, proposal: { step: 'execute', fields: structuredClone(leaf.proposal.fields) }, decision_bases: [{ requirement_id: required.id, evidence: { decision_act_digest: digest('authority-act', act), authority_input: leaf } }], clock: structuredClone(leaf.clock), acts: [], observations: [], evaluation_point: 'PROPOSE' };
}

test('selected decision gate binds exact translated predicates, record identity and current clock', () => {
  const input = independentInput(); bindDecisionInputs(input, check);
  assert.equal(selectedAuthorityAct(input, 'INSTANCE_DECISION')[0].act.actor, 'human-1');
  assert.deepEqual(independentActors(input), ['human-1']);
  for (const mutate of [
    (row: Row) => { row.envelope.gate.criteria[0].predicate.right.value.value = 'OTHER'; },
    (row: Row) => { row.envelope.source_observation_requirements[0].record_id = 'different-approval'; },
    (row: Row) => { row.decision_bases[0].evidence.authority_input.clock.instant = time('11'); },
    (row: Row) => { row.decision_bases[0].evidence.authority_input.clock.source = 'wrong-human-clock'; },
  ]) { const changed = independentInput(); mutate(changed); assert.throws(() => bindDecisionInputs(changed, check), refuses('BINDING_MISMATCH')); }
});

test('nominal context bridges reject incompatible complete type declarations before binding', () => {
  const input = independentInput(), leaf = input.decision_bases[0].evidence.authority_input;
  leaf.work_class.types.find((row: Row) => row.id === 'STATUS').unit = 'different-unit';
  input.envelope.decision_requirements[0].work_class_digest = digest('authority-work-class', leaf.work_class);
  const structural: string[] = [], typeFailures: string[] = [];
  admitDecisionInputs(input, (value, code) => { if (!value) structural.push(code); }, (value, code) => { if (!value) typeFailures.push(code); });
  assert.deepEqual(structural, []); assert.ok(typeFailures.includes('TYPE_INVALID'));
});

test('authorization refresh removes only volatile evidence recursively and retains decision identities', () => {
  const before = independentInput(), after = structuredClone(before);
  after.clock.instant = time('11'); after.observations = [{ id: 'new-observation' }]; after.evaluation_point = 'DISPATCH';
  const leaf = after.decision_bases[0].evidence.authority_input;
  leaf.clock.instant = time('11'); leaf.observations = [{ id: 'new-leaf-observation' }]; leaf.evaluation_point = 'DISPATCH';
  assert.deepEqual(immutableAuthority(before), immutableAuthority(after));
  after.decision_bases[0].evidence.decision_act_digest = digest('changed-decision', {});
  assert.notDeepEqual(immutableAuthority(before), immutableAuthority(after));
});

test('recovery actor inventory includes every actor in every retained independent leaf', () => {
  const input = independentInput();
  input.decision_bases[0].evidence.authority_input.acts.push({ actor: 'leaf-grantor' }, { actor: 'leaf-attester' });
  input.decision_bases.push({ requirement_id: 'other-decision', evidence: { authority_input: { acts: [{ actor: 'other-principal-signer' }] } } });
  assert.deepEqual(independentActors(input), ['human-1', 'leaf-grantor', 'leaf-attester', 'other-principal-signer']);
});

test('effective decision expiry uses selected reliance and connected survival intervals', () => {
  const input: Row = { clock: { instant: time('10') }, envelope: { temporal_validity: { valid_until: time('50') } }, host_selection: { root: { prior_acts_survive_expiry: false, validity: { valid_until: time('45') }, channels: [] } }, returns: [], acts: [{ capacity: 'selected' }], capacities: [
    { id: 'selected', validity: { valid_from: time('00'), valid_until: time('15') }, reliance: { kind: 'SURVIVE_EXPIRY', validity: { valid_from: time('15'), valid_until: time('35') } } },
    { id: 'unused', validity: { valid_from: time('00'), valid_until: time('11') }, reliance: { kind: 'CURRENT_ONLY' } },
  ] };
  assert.equal(effectiveUntil(input), time('35'));
  input.capacities[0].reliance.validity.valid_from = time('16'); assert.equal(effectiveUntil(input), time('15'));
  input.capacities[0].reliance = { kind: 'CURRENT_ONLY' }; assert.equal(effectiveUntil(input), time('15'));
});

test('qualified own source fields and identity are local values rather than dependency cycles', () => {
  const requirement: Row = { id: 'record', step: 'execute', subject: 'subject', at: 'CLOCK', provider: 'quality', source: 'records', record_type: 'approval', record_id: 'approval-1', purpose: 'AUTHORITY', freshness_seconds: '0', expected_status: 'AVAILABLE', fields: [{ name: 'actor', type_ref: 'IDENTITY' }], relations: [
    { kind: 'EQUALS', left: { kind: 'OBSERVATION_FIELD', requirement_id: 'record', field: 'actor' }, right: literal('IDENTITY', 'human-1') },
    { kind: 'EQUALS', left: { kind: 'OBSERVATION_ID', requirement_id: 'record', type_ref: 'IDENTITY' }, right: literal('IDENTITY', 'approval-1') },
  ] };
  const input: Row = { work_class: { steps: [{ id: 'execute', fields: [] }] }, envelope: { source_observation_requirements: [requirement] }, proposal: { step: 'execute', fields: [] }, clock: { instant: time('10') } };
  admitSourceRequirements(input, types, check, check);
  const queries = deriveSourceQueries(input), observation: Row = { status: 'AVAILABLE', provider_record_id: 'approval-1', as_of: time('10'), fields: [{ name: 'actor', value: { type_ref: 'IDENTITY', value: 'human-1' } }], relations: requirement.relations };
  const groups = new Map([[digest('authority-query', queries[0]), new Map([['observation', observation]])]]);
  assert.deepEqual(sourcePolicyFailures(input, types, queries, groups), []);
  observation.fields[0].value.value = 'human-2';
  assert.deepEqual(sourcePolicyFailures(input, types, queries, groups).map(row => row.reason), ['SOURCE_OBSERVATION_RELATIONS']);
});

function completionStep(): Row {
  return { fields: [{ name: 'new_status', type_ref: 'STATUS' }], dispatch_gate: { kind: 'SOURCE_REQUIREMENTS', requirements: ['quality-revision'] }, completion: {
    terminal_policy: 'STOP_RETAIN', status_field: 'new_status', status_type_ref: 'STATUS', status_request_field: 'new_status', evidence_bindings: [{ request_field: 'new_status', evidence_field: 'new_status' }],
    provider_record_identity: { field: 'event_id', type_ref: 'IDENTITY' }, event_time_identity: { field: 'event_time', type_ref: 'TIME' }, additional_fields: [], lookup: { key_projection: [] },
    authorization_revision_bindings: [{ evidence_field: 'committed_quality_revision', type_ref: 'IDENTITY', requirement_id: 'quality-revision' }],
  } };
}

test('completion revision matches the historical source row and requires retained authorization', () => {
  const step = completionStep(), evidence: Row = { provider_record_id: 'event-1', provider_revision: 'native-9', event_time: time('12'), actual_fields: [
    { name: 'event_id', value: { type_ref: 'IDENTITY', value: 'event-1' } }, { name: 'event_time', value: { type_ref: 'TIME', value: time('12') } },
    { name: 'new_status', value: { type_ref: 'STATUS', value: 'APPROVED' } }, { name: 'committed_quality_revision', value: { type_ref: 'IDENTITY', value: 'quality-historical-4' } },
  ] };
  const authorization = { authorization_fence: { provider_revision: 'coordinator-99', sources: [{ requirement_id: 'quality-revision', expected_status: 'AVAILABLE', provider_revision: 'quality-historical-4' }] } };
  assert.equal(terminalFieldsMatch(step, evidence, types, authorization), true);
  authorization.authorization_fence.sources[0].provider_revision = 'quality-current-5'; assert.equal(terminalFieldsMatch(step, evidence, types, authorization), false);
  assert.throws(() => terminalFieldsMatch(step, evidence, types), refuses('STATE_INVALID'));
});

test('dual status fields permit only the declared same-type request overlap', () => {
  admitCompletion(completionStep(), types);
  const missing = completionStep(); delete missing.completion.status_request_field; assert.throws(() => admitCompletion(missing, types), refuses('DEFINITION_INVALID'));
  const extraCollision = completionStep(); extraCollision.completion.authorization_revision_bindings[0].evidence_field = 'new_status'; assert.throws(() => admitCompletion(extraCollision, types), refuses('DEFINITION_INVALID'));
  const wrongType = completionStep(); wrongType.fields[0].type_ref = 'IDENTITY'; assert.throws(() => admitCompletion(wrongType, types), refuses('DEFINITION_INVALID'));
});

test('generated completion fields retain arbitrary valid provider values with exact nominal types', () => {
  const step = completionStep(); delete step.completion.authorization_revision_bindings;
  step.completion.generated_fields = [{ name: 'bsa_identifier', type_ref: 'IDENTITY' }, { name: 'warnings', type_ref: 'STATUS' }];
  admitCompletion(step, types);
  const evidence: Row = { provider_record_id: 'receipt-1', provider_revision: 'native-1', event_time: time('12'), actual_fields: [
    { name: 'event_id', value: { type_ref: 'IDENTITY', value: 'receipt-1' } }, { name: 'event_time', value: { type_ref: 'TIME', value: time('12') } },
    { name: 'new_status', value: { type_ref: 'STATUS', value: 'APPROVED' } }, { name: 'bsa_identifier', value: { type_ref: 'IDENTITY', value: '31000000000001' } }, { name: 'warnings', value: { type_ref: 'STATUS', value: '[]' } },
  ] };
  assert.equal(terminalFieldsMatch(step, evidence, types), true);
  evidence.actual_fields.find((row: Row) => row.name === 'bsa_identifier').value.value = '31000000000002';
  evidence.actual_fields.find((row: Row) => row.name === 'warnings').value.value = '[{"code":"variable-warning"}]';
  assert.equal(terminalFieldsMatch(step, evidence, types), true);
  const missing = structuredClone(evidence); missing.actual_fields.pop(); assert.equal(terminalFieldsMatch(step, missing, types), false);
  const wrongType = structuredClone(evidence); wrongType.actual_fields.at(-1).value.type_ref = 'IDENTITY'; assert.equal(terminalFieldsMatch(step, wrongType, types), false);
  const invalid = structuredClone(evidence); invalid.actual_fields.find((row: Row) => row.name === 'event_time').value.value = '2026-02-30T00:00:00Z'; assert.equal(terminalFieldsMatch(step, invalid, types), false);
  const collision = structuredClone(step); collision.completion.generated_fields[0].name = 'event_id'; assert.throws(() => admitCompletion(collision, types), refuses('DEFINITION_INVALID'));
  const unknown = structuredClone(step); unknown.completion.generated_fields[0].type_ref = 'UNKNOWN'; assert.throws(() => admitCompletion(unknown, types), refuses('REFERENCE_INVALID'));
  const overflow = structuredClone(step); overflow.completion.generated_fields = Array.from({ length: 64 }, (_, i) => ({ name: 'generated-' + String(i).padStart(2, '0'), type_ref: 'STATUS' })); assert.throws(() => admitCompletion(overflow, types), refuses('LIMIT_EXCEEDED'));
});

test('prior effect bindings can read declared generated completion coordinates with exact nominal types', () => {
  const row = JSON.parse(readFileSync(new URL('../cases/deployment/D2-008.json', import.meta.url), 'utf8')), definition = structuredClone(row.input.definition);
  definition.profile = 'LINEAR'; definition.deadlines = [];
  definition.types.push({ id: 'time', kind: 'INSTANT', unit: null, nonnegative: false });
  const original = definition.steps.find((step: Row) => step.id === 'issue-card');
  original.completion = { ...original.completion, terminal_policy: 'STOP_RETAIN', provider_record_identity: { field: 'provider_event', type_ref: 'identity' }, event_time_identity: { field: 'provider_time', type_ref: 'time' }, additional_fields: [], generated_fields: [{ name: 'bsa_identifier', type_ref: 'identity' }], lookup: { provider: 'access-provider', source: 'access-control', record_type: 'card-result', namespace: 'events', key_projection: [{ field: 'card-id', type_ref: 'identity' }] } };
  const next = structuredClone(original); next.id = 'amend'; next.operation = 'amend'; next.prior_effect_bindings = [{ id: 'prior-bsa-id', selection: 'UNIQUE_COMPLETED_ANCESTOR', source_step_id: 'issue-card', source_evidence_field: 'bsa_identifier', target_request_field: 'card-id' }];
  definition.steps.push(next); definition.steps.sort((a: Row, b: Row) => a.id.localeCompare(b.id));
  definition.relationships = [{ from: 'issue-card', kind: 'SEQUENCE', to: 'amend' }, { from: 'amend', kind: 'SEQUENCE', to: 'terminal' }];
  definition.occurrence_limits = [{ step_id: 'amend', maximum: '1' }, { step_id: 'issue-card', maximum: '1' }];
  definition.specification_pin = selectedCandidate();
  assert.doesNotThrow(() => validateWorkClass(definition, definition.specification_pin));
  const unknown = structuredClone(definition); unknown.steps.find((step: Row) => step.id === 'amend').prior_effect_bindings[0].source_evidence_field = 'undeclared';
  assert.throws(() => validateWorkClass(unknown, definition.specification_pin), refuses('REFERENCE_INVALID'));
  const nominal = structuredClone(definition); nominal.types.push({ id: 'other-identity', kind: 'IDENTITY', unit: null, nonnegative: false }); nominal.types.sort((a: Row, b: Row) => a.id.localeCompare(b.id)); nominal.steps.find((step: Row) => step.id === 'issue-card').completion.generated_fields[0].type_ref = 'other-identity';
  assert.throws(() => validateWorkClass(nominal, definition.specification_pin), refuses('DEFINITION_INVALID'));
});

test('completion bindings follow request field order when native evidence fields use other names', () => {
  const source = JSON.parse(readFileSync(new URL('../cases/deployment/D2-008.json', import.meta.url), 'utf8'));
  const definition = source.input.definition, bindings = definition.steps[0].completion.evidence_bindings;
  bindings[0].evidence_field = 'z-generated-card-id';
  assert.doesNotThrow(() => validateWorkClass(definition, source.input.specification_pin));
  bindings.reverse();
  assert.throws(() => validateWorkClass(definition, source.input.specification_pin), refuses('DEFINITION_INVALID'));
});


test('registry recovery ordinary gate actor selection preserves omitted and empty inventories', () => {
  const acts: Row[] = [{ kind: 'GRANT', actor: 'grantor', role: 'owner' },
    { kind: 'ORGANISATIONAL_ATTESTATION', actor: 'attester', role: 'attester' },
    { kind: 'INSTANCE_DECISION', actor: 'releaser', role: 'release' },
    { kind: 'VERIFY', actor: 'verifier', role: 'verify' },
    { kind: 'INSTANCE_DECISION', actor: 'other-role', role: 'other' },
    { kind: 'INSTANCE_DECISION', actor: 'unadmitted', role: 'release' }];
  const admitted = acts.slice(0, -1).map(row => digest('authority-act', row));
  for (const inventory of [undefined, []]) for (const [kind, role, expected] of [
    ['DECIDE', 'release', ['executor', 'releaser']], ['VERIFY', 'verify', ['executor', 'verifier']], ['NONE', null, ['executor']],
  ]) {
    const authority: Row = { proposal: { executor: { actor: 'executor' } }, envelope: { gate: { kind, role } }, acts };
    if (inventory !== undefined) authority.decision_bases = inventory;
    assert.deepEqual(recoveryControllerActors({ authority, authority_result: { act_digests: admitted } }), expected);
  }
});

test('registry recovery retains all nonempty independent-decision actor exclusions', () => {
  const authority: Row = { proposal: { executor: { actor: 'executor' } },
    acts: [{ kind: 'GRANT', actor: 'grantor' }, { kind: 'ORGANISATIONAL_ATTESTATION', actor: 'attester' }],
    decision_bases: [{ evidence: { authority_input: { acts: [{ actor: 'independent-human' }, { actor: 'leaf-attester' }] } } }] };
  assert.deepEqual(recoveryControllerActors({ authority }), ['executor', 'grantor', 'attester', 'independent-human', 'leaf-attester']);
});

test('recovery source cases match complete public results', () => {
  for (let index = 1; index <= 24; index++) {
    const id = `C3-RCTRL-${String(index).padStart(3, '0')}`;
    const row = JSON.parse(readFileSync(new URL(`../cases/recovery-authority/${id}.json`, import.meta.url), 'utf8'));
    assert.deepEqual(row.operation === 'aggregate-step' ? aggregateStep(row.input, row.input.specification_pin) : step(row.input, row.input.specification_pin), row.expected, id);
  }
});


test('work recovery excludes the admitted gate actor and preserves nonempty decisions', () => {
  for (const [kind, role, actor] of [['DECIDE', 'release', 'releaser'], ['VERIFY', 'verify', 'verifier'], ['NONE', null, null]]) {
    const acts: Row[] = [{ kind: 'GRANT', actor: 'grantor', role: 'owner' }, { kind: 'ORGANISATIONAL_ATTESTATION', actor: 'attester', role: 'attester' }];
    if (actor !== null) acts.push({ kind: kind === 'DECIDE' ? 'INSTANCE_DECISION' : 'VERIFY', actor, role });
    const bases = acts.map(act => ({ act, act_digest: digest('authority-act', act) }));
    const permit: Row = { executor: { participant_id: 'executor' }, authority_act_bases: bases, authority_result: { act_digests: bases.map(row => row.act_digest) } };
    const expected = ['executor', ...(actor === null ? [] : [actor])];
    assert.deepEqual(workRecoveryControllerActors(permit), expected);
    for (const inventory of [undefined, []]) {
      permit.authority_basis = { proposal: { executor: { actor: 'executor' } }, envelope: { gate: { kind, role } }, acts };
      if (inventory !== undefined) permit.authority_basis.decision_bases = inventory;
      assert.deepEqual(workRecoveryControllerActors(permit), expected);
    }
    permit.authority_basis.decision_bases = [{ evidence: { authority_input: { acts: [{ actor: 'independent-human' }, { actor: 'leaf-attester' }] } } }];
    assert.deepEqual(workRecoveryControllerActors(permit), ['executor', ...acts.map(row => row.actor), 'independent-human', 'leaf-attester']);
  }
});

function recoveryRegressions(): Row {
  const value = JSON.parse(readFileSync(new URL('../review/fixtures/recovery-dispatch-regressions.json', import.meta.url), 'utf8'));
  assert.equal(value.specification_pin, selectedCandidate());
  return value;
}

test('explicit no-effect recovery admits mismatch evidence and exact emitted-state retry', () => {
  const fixture = recoveryRegressions(), row = fixture.registry_controls.find((row: Row) => row.name === 'mismatch-no-effect');
  const actual = aggregateStep(row.input, fixture.specification_pin);
  assert.deepEqual(actual, row.expected);
  assert.equal(actual.receipt.decision, 'DISPOSITION_RECORDED');
  const request = structuredClone(row.input);
  request.state = structuredClone(actual.state); request.state_digest = actual.state_digest;
  const replay = aggregateStep(request, fixture.specification_pin);
  assert.equal(replay.status, 'TRANSITION'); assert.equal(replay.replay, true);
  assert.deepEqual(replay.receipt, row.expected.receipt);
  assert.deepEqual(replay.state, actual.state); assert.equal(replay.state_digest, actual.state_digest);
  const registry = aggregateStep(fixture.application_registry.input, fixture.specification_pin);
  assert.deepEqual(registry, fixture.application_registry.expected);
  for (const trace of fixture.traces) {
    let previous: Row | null = null;
    for (const entry of trace.rows) {
      const supplied = structuredClone(entry.input);
      if (previous !== null) {
        assert.deepEqual(supplied.state, previous.state);
        supplied.state = structuredClone(previous.state); supplied.state_digest = previous.state_digest;
      }
      const result = entry.operation === 'deploy'
        ? deploy(supplied, fixture.specification_pin)
        : step(supplied, fixture.specification_pin);
      assert.deepEqual(result, entry.expected);
      previous = result;
      if (trace.name === 'registry-application' && supplied.event.kind === 'APPLY_DISPOSITION') {
        assert.deepEqual(supplied.event.registry.state, registry.state);
        assert.deepEqual(result.state.recovery_records.at(-1).registry_selections, supplied.recovery_registries);
        const retry = structuredClone(supplied);
        retry.state = structuredClone(result.state); retry.state_digest = result.state_digest;
        const appliedReplay = step(retry, fixture.specification_pin);
        assert.equal(appliedReplay.status, 'STEP'); assert.equal(appliedReplay.replay, true);
        assert.deepEqual(appliedReplay.decision, entry.expected.decision);
        assert.deepEqual(appliedReplay.state, result.state); assert.deepEqual(appliedReplay.budget_results, []);
      }
    }
  }
});

test('no-effect recovery requires every native conclusion and complete attempt exclusions', () => {
  const fixture = recoveryRegressions();
  for (const name of ['mixed-unknown', 'empty-native', 'false-native-exclusion', 'incomplete-attempt-inventory']) {
    const row = fixture.registry_controls.find((row: Row) => row.name === name), actual = aggregateStep(row.input, fixture.specification_pin);
    assert.equal(actual.status, 'TRANSITION', name);
    assert.equal(actual.receipt.decision, row.selected_expected.decision, name);
    assert.ok(actual.receipt.reasons.includes(row.selected_expected.reason), name);
  }
});

test('no-effect recovery retains release authority and contrary-effect safeguards', () => {
  const fixture = recoveryRegressions();
  const remit = fixture.registry_controls.find((row: Row) => row.name === 'missing-release-remit');
  const refused = aggregateStep(remit.input, fixture.specification_pin);
  assert.equal(refused.status, remit.selected_expected.status);
  assert.equal(refused.code, remit.selected_expected.code);
  assert.deepEqual(refused.state, remit.input.state);
  const contrary = fixture.registry_controls.find((row: Row) => row.name === 'contrary-effect');
  const withheld = aggregateStep(contrary.input, fixture.specification_pin);
  assert.equal(withheld.status, 'TRANSITION');
  assert.equal(withheld.receipt.decision, contrary.selected_expected.decision);
  assert.ok(withheld.receipt.reasons.includes(contrary.selected_expected.reason));
});

test('ordinary release retains mismatch refusal outside explicit recovery', () => {
  const fixture = recoveryRegressions(), row = fixture.ordinary_release;
  const actual = aggregateStep(row.input, fixture.specification_pin);
  assert.equal(actual.status, 'TRANSITION'); assert.equal(actual.receipt.decision, row.selected_expected.decision);
  assert.ok(actual.receipt.reasons.includes(row.selected_expected.reason));
  assert.equal(actual.state.core.reservations[0].status, row.selected_expected.reservation_status);
});
