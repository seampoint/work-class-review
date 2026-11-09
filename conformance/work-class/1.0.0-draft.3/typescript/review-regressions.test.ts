import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { byteCompare, canonical, digest } from './canonical.ts';
import { authorityProjection, deploy, stateDigest, step } from './lifecycle.ts';
import { checkSourceCorrection } from './source-corrections.ts';
import { readback } from './evidence.ts';
import { validateWorkClass } from './work-class.ts';
import { VERSION } from './schema.ts';
import { authorizationHead, deriveAuthorizationFence } from './dispatch-authority.ts';
import { deriveSourceQueries, evaluateAuthority, validateAuthorityDefinition } from './authority.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);
const index = JSON.parse(readFileSync(new URL('cases/index.json', candidate), 'utf8')).cases as Row[];
const source = (id: string): Row => JSON.parse(readFileSync(new URL(index.find(row => row.id === id)!.path, candidate), 'utf8')).input;
const omit = (row: Row, name: string): Row => Object.fromEntries(Object.entries(row).filter(([key]) => key !== name));

test('authority MEMBER inventory ordering is INPUT_INVALID and retains TYPE_INVALID precedence', () => {
  const request = source('C3-ED-003').event.authority_input;
  const definition: Row = {
    schema: `${VERSION}/authority-definition`,
    source: structuredClone(request.source),
    work_class: structuredClone(request.work_class),
    envelope: structuredClone(request.envelope),
  };
  const stepId = definition.envelope.operations[0].step;
  const step = definition.work_class.steps.find((row: Row) => row.id === stepId);
  const identityType = definition.work_class.types.find((row: Row) => row.kind === 'IDENTITY').id;
  const otherType = definition.work_class.types.find((row: Row) => row.kind === 'DECIMAL').id;
  const field = step.fields.find((row: Row) => row.type_ref === identityType);
  const membership = (values: Row[], id: string, type = identityType): Row => ({
    id,
    step: stepId,
    predicate: {
      kind: 'MEMBER',
      value: { kind: 'FIELD', name: field.name },
      members: values.map(row => ({ type_ref: row.type_ref ?? type, value: row.value })),
    },
  });
  const sorted = [{ type_ref: identityType, value: 'A' }, { type_ref: identityType, value: 'Z' }];
  const setPredicates = (conditionValues: Row[], criterionValues: Row[]) => {
    definition.envelope.conditions = [membership(conditionValues, 'condition.membership-test')];
    definition.envelope.gate.criteria = [membership(criterionValues, 'criterion.membership-test')];
  };
  definition.envelope.gate.kind = 'VERIFY';
  definition.envelope.gate.role = 'reviewer';
  setPredicates(sorted, sorted);
  assert.equal(validateAuthorityDefinition(definition).status, 'ACCEPTED');

  setPredicates([...sorted].reverse(), sorted);
  assert.equal(validateAuthorityDefinition(definition).code, 'INPUT_INVALID', 'condition member order');
  setPredicates(sorted, [...sorted].reverse());
  assert.equal(validateAuthorityDefinition(definition).code, 'INPUT_INVALID', 'gate-criterion member order');
  setPredicates([{ type_ref: identityType, value: 'A' }, { type_ref: identityType, value: 'A' }], sorted);
  assert.equal(validateAuthorityDefinition(definition).code, 'INPUT_INVALID', 'duplicate members');

  const wrongType = [{ type_ref: identityType, value: 'A' }, { type_ref: otherType, value: '1' }]
    .sort((left, right) => byteCompare(canonical(left), canonical(right)));
  setPredicates(wrongType, sorted);
  assert.equal(validateAuthorityDefinition(definition).code, 'TYPE_INVALID', 'wrong member type');
  setPredicates([...wrongType].reverse(), sorted);
  assert.equal(validateAuthorityDefinition(definition).code, 'TYPE_INVALID', 'type failure precedes unsorted inventory');

  setPredicates(sorted, sorted);
  const nestedCondition = membership(sorted, 'condition.membership-test');
  nestedCondition.predicate = { kind: 'ALL', operands: [{ kind: 'BOOLEAN', value: true }, nestedCondition.predicate] };
  definition.envelope.conditions = [nestedCondition];
  assert.equal(validateAuthorityDefinition(definition).status, 'ACCEPTED', 'nested condition member set');
  nestedCondition.predicate.operands[1].members.reverse();
  assert.equal(validateAuthorityDefinition(definition).code, 'INPUT_INVALID', 'nested condition member order');

  setPredicates(sorted, sorted);
  const nestedCriterion = membership(sorted, 'criterion.membership-test');
  nestedCriterion.predicate = { kind: 'NOT', operand: nestedCriterion.predicate };
  definition.envelope.gate.criteria = [nestedCriterion];
  assert.equal(validateAuthorityDefinition(definition).status, 'ACCEPTED', 'nested gate criterion member set');
  nestedCriterion.predicate.operand.members.reverse();
  assert.equal(validateAuthorityDefinition(definition).code, 'INPUT_INVALID', 'nested gate criterion member order');
});

function advance(request: Row, event: Row): Row {
  request.event = { ...structuredClone(event), instance_id: request.state.instance_id, expected_state_revision: request.state.revision, expected_state_digest: request.state_digest };
  const result = step(request, request.specification_pin);
  assert.equal(result.status, 'STEP', JSON.stringify({ event: event.event_id, status: result.status, code: result.code, path: result.path }));
  request.state = result.state; request.state_digest = result.state_digest;
  const replay = step(request, request.specification_pin);
  assert.equal(replay.replay, true, JSON.stringify({ status: replay.status, code: replay.code }));
  return result;
}

function appendForged(request: Row, event: Row, receiptTemplate: Row, replayTemplate: Row, mutate: (state: Row) => void): void {
  event.expected_state_revision = request.state.revision; event.expected_state_digest = request.state_digest;
  const before = request.state_digest, state = structuredClone(request.state);
  mutate(state); state.revision = String(BigInt(state.revision) + 1n);
  const core = structuredClone(state); core.receipts = []; core.replays = [];
  const receipt: Row = { ...structuredClone(receiptTemplate), event_id: event.event_id, event_digest: digest('runtime-event', event), sequence: state.revision, state_before_digest: before, state_after_core_digest: digest('work-state-core', core) };
  receipt.decision_id = digest('decision-receipt', omit(receipt, 'decision_id'));
  state.receipts.push(receipt);
  const replay: Row = { ...structuredClone(replayTemplate), event_id: event.event_id, event_digest: receipt.event_digest, decision: structuredClone(receipt), decision_receipt_digest: receipt.decision_id, transition_state_digest: receipt.state_after_core_digest };
  replay.transaction_digest = digest('lifecycle-transaction', { state_before_digest: before, event_digest: receipt.event_digest, decision_receipt_digest: receipt.decision_id, state_after_core_digest: receipt.state_after_core_digest, budget_results: replay.budget_results });
  state.replays.push(replay); state.replays.sort((a: Row, b: Row) => byteCompare(a.event_id, b.event_id));
  request.state = state; request.state_digest = stateDigest(state); request.event = event;
}

for (const gated of [false, true]) for (const initialFirst of [false, true]) {
  test(`one conclusive acknowledgement update, gated=${gated}, initial digest first=${initialFirst}`, () => {
    const request = source(gated ? 'C3-ED-019' : 'D2-022'), first = structuredClone(request.event);
    first.event_id = `review-ack-initial-${gated}-${initialFirst}`;
    const sent = advance(request, first), original = sent.state.dispatches.find((row: Row) => row.event_id === first.event_id);
    const accepted = structuredClone(first);
    accepted.acknowledgement = { status: 'ACCEPTED', reference: 'review-accepted', observed_at: first.attempt.attempted_at };
    accepted.expected_state_revision = request.state.revision; accepted.expected_state_digest = request.state_digest;
    let found = false;
    for (let i = 0; i < 128; i++) {
      accepted.event_id = `review-ack-accepted-${i}`;
      const row = { ...structuredClone(original), event_id: accepted.event_id, event_digest: digest('runtime-event', accepted), acknowledgement: accepted.acknowledgement };
      if ((byteCompare(original.dispatch_digest, digest('dispatch', omit(row, 'dispatch_digest'))) < 0) === initialFirst) { found = true; break; }
    }
    assert.ok(found, 'exercise the requested digest order');
    const updated = advance(request, accepted); assert.equal(updated.decision.disposition, 'ACKNOWLEDGED');
    assert.equal(request.state.dispatches[initialFirst ? 0 : 1].event_id, first.event_id);
    const rejected = structuredClone(accepted); rejected.event_id = 'review-second-conclusive';
    rejected.expected_state_revision = request.state.revision; rejected.expected_state_digest = request.state_digest;
    rejected.acknowledgement = { status: 'REJECTED', reference: 'review-rejected', observed_at: first.attempt.attempted_at };
    request.event = rejected;
    const before = canonical(request.state), refusal = step(request, request.specification_pin);
    assert.equal(refusal.code, 'PREREQUISITE_MISSING'); assert.equal(canonical(request.state), before);

    const receipt = structuredClone(updated.decision), replay = request.state.replays.find((row: Row) => row.event_id === accepted.event_id);
    receipt.disposition = 'DISPATCH_RECORDED'; receipt.reason_codes = ['ACKNOWLEDGEMENT_REJECTED'];
    receipt.details = [{ kind: 'DISPATCH', attempt_id: first.attempt.attempt_id, reasons: receipt.reason_codes }];
    appendForged(request, rejected, receipt, replay, state => {
      const row = { ...structuredClone(original), event_id: rejected.event_id, event_digest: digest('runtime-event', rejected), acknowledgement: rejected.acknowledgement };
      row.dispatch_digest = digest('dispatch', omit(row, 'dispatch_digest'));
      state.dispatches.push(row); state.dispatches.sort((a: Row, b: Row) => byteCompare(a.dispatch_digest, b.dispatch_digest));
    });
    assert.equal(step(request, request.specification_pin).code, 'STATE_INVALID');
  });
}

test('authorized terminal no-effect is unexpected and disputed, including restart', () => {
  const request = source('C3-EC-035'), event = request.event, permit = event.permit;
  const native = digest('native-evidence', event.native_evidence), authorization = structuredClone(request.state.deployment_authorization_evidence);
  authorization.subject_digest = digest('no-effect-completion', { specification_pin: request.specification_pin, work_class_digest: request.definition_digest, instance_id: request.state.instance_id, occurrence_id: permit.occurrence.occurrence_id, permit_id: permit.permit_id, dispatch_digest: event.dispatch_digest, native_evidence_digest: native });
  authorization.authorization_scope = [request.specification_pin, request.definition_digest, request.state.instance_id, permit.occurrence.occurrence_id, permit.permit_id, event.dispatch_digest, native].sort(byteCompare);
  authorization.recorded_at = event.native_evidence.observed_at; authorization.expires_at = '2026-09-10T05:00:00Z'; event.completion_authorization = authorization;
  const result = advance(request, event);
  assert.equal(result.state.outcomes[0].classification, 'UNEXPECTED'); assert.equal(result.state.outcomes[0].disputed, true);
  assert.equal(result.decision.disposition, 'DISPUTED'); assert.ok(result.decision.reason_codes.includes('UNEXPECTED_EFFECT'));
  assert.equal(result.state.terminal_records[0].cause, 'UNEXPECTED_COMPLETION'); assert.equal(result.state.status, 'STOPPED');
});

test('original correction provider observation cannot precede its event', () => {
  const request = source('C3-ER-001'); assert.equal(checkSourceCorrection(request, request.specification_pin).status, 'EVIDENCE_VALID');
  request.original_record.observed_at = '2026-09-10T04:29:59Z';
  const before = canonical(request), result = checkSourceCorrection(request, request.specification_pin);
  assert.equal(result.code, 'BINDING_MISMATCH'); assert.equal(canonical(request), before);
});

function deployChanged(template: Row, change: (definition: Row) => void): Row {
  const request = structuredClone(template), original = template.state, definition = request.definition;
  change(definition); request.definition_digest = validateWorkClass(definition, request.specification_pin).digest;
  const authorization = structuredClone(original.deployment_authorization), evidence = structuredClone(original.deployment_authorization_evidence);
  const correspondence = structuredClone(original.deployment_correspondence_evidence), policy = structuredClone(original.deployment_policy_decision_evidence);
  correspondence.subject_digest = request.definition_digest; correspondence.work_class_digest = request.definition_digest;
  correspondence.mappings[0].provision_paths = readback(definition).map(row => row.path);
  correspondence.review.subject_digest = digest('correspondence-subject', omit(correspondence, 'review'));
  policy.subject_digest = request.definition_digest; authorization.work_class_digest = request.definition_digest;
  authorization.correspondence_evidence_digest = digest('evidence', correspondence); authorization.policy_decision_evidence_digest = digest('evidence', policy);
  evidence.subject_digest = digest('deployment-authorization-subject', omit(authorization, 'authorization_evidence_digest'));
  evidence.authorization_scope = [request.specification_pin, request.definition_digest, request.profile, request.role, original.instance_id].sort(byteCompare);
  authorization.authorization_evidence_digest = digest('evidence', evidence);
  const result = deploy({ profile: request.profile, role: request.role, specification_pin: request.specification_pin, instance_id: original.instance_id, definition, definition_digest: request.definition_digest, deployment_authorization: authorization, authorization_clock: original.deployment_authorization_clock, authorization_evidence: evidence, correspondence_evidence: correspondence, source_confirmation_evidence: original.deployment_source_confirmation_evidence, policy_decision_evidence: policy, initial_clocks: [] }, request.specification_pin);
  assert.equal(result.status, 'DEPLOYED', canonical(result)); request.state = result.state; request.state_digest = result.state_digest;
  const clock = original.clocks[0];
  advance(request, { schema: VERSION + '/runtime-event', kind: 'CLOCK', event_id: 'review-initial-clock', instance_id: original.instance_id, clock, activation_clocks: [] });
  return request;
}

test('different route identifiers producing one referral body retain one intent and restart', () => {
  const template = source('C3-EAR-003'), request = deployChanged(template, definition => {
    const operation = definition.steps.find((row: Row) => row.referral_policy?.authority.length);
    const route = structuredClone(operation.referral_policy.authority.find((row: Row) => row.requirement_ids.length === 0));
    assert.ok(route); route.id = 'zz-review-route-alias'; operation.referral_policy.authority.push(route);
    operation.referral_policy.authority.sort((a: Row, b: Row) => byteCompare(a.id, b.id));
  });
  assert.equal(canonical(authorityProjection(request.definition)), canonical(template.event.authority_input.work_class));
  const event = structuredClone(template.event); event.occurrence = request.state.active[0].occurrence;
  event.authority_input.proposal.occurrence = event.occurrence.occurrence_id;
  const result = advance(request, event); assert.equal(result.decision.disposition, 'WITHHELD');
  const ids = result.state.referrals.map((row: Row) => row.referral_digest);
  assert.equal(new Set(ids).size, ids.length); assert.equal(ids.length, 2);
});

function refresh(authority: Row, time: string): void {
  const prior = authority.clock.instant; authority.clock.instant = time;
  for (const observation of authority.observations) if (observation.query.at === prior) {
    observation.query.at = time;
    if (observation.as_of !== null) observation.as_of = time;
    observation.query_digest = digest('authority-query', observation.query);
  }
}

function forgeAuthorization(request: Row, original: Row): void {
  const retained = request.state.authorizations.find((row: Row) => row.permit_digest === original.permit_digest);
  const receipt = structuredClone(request.state.receipts.find((row: Row) => row.event_id === retained.event_id));
  const replay = request.state.replays.find((row: Row) => row.event_id === retained.event_id);
  const permit = request.state.permits.find((row: Row) => row.permit_id === retained.permit_digest);
  const event: Row = { schema: VERSION + '/runtime-event', kind: 'AUTHORIZE_DISPATCH', instance_id: request.state.instance_id, event_id: 'review-forged-authorization', permit, native_request: structuredClone(original.native_request), connector: structuredClone(original.connector), authorization_fence: null, observation_digests: structuredClone(original.observation_digests), clock_revision: original.clock_revision, authority_input: structuredClone(original.authority_input), dispatch_intent_id: 'review-forged-intent' };
  const gate = request.definition.steps.find((row: Row) => row.id === permit.occurrence.step_id).dispatch_gate;
  event.authorization_fence = deriveAuthorizationFence(event, gate, original.authority_result, original.expires_at);
  appendForged(request, event, receipt, replay, state => {
    const authorization: Row = { ...structuredClone(original), event_id: event.event_id, event_digest: digest('runtime-event', event), dispatch_intent_id: event.dispatch_intent_id, authorization_fence: event.authorization_fence, supersedes_authorization_digest: authorizationHead(state, permit.permit_id)?.authorization_digest ?? null };
    authorization.authorization_digest = digest('dispatch-authorization', omit(authorization, 'authorization_digest'));
    const evaluation: Row = { event_id: event.event_id, event_digest: authorization.event_digest, permit_digest: permit.permit_id, dispatch_intent_id: event.dispatch_intent_id, clock_revision: event.clock_revision, authority_input: event.authority_input, authority_result: authorization.authority_result, authority_result_digest: authorization.authority_result_digest, authorization_digest: authorization.authorization_digest, disposition: 'AUTHORIZED' };
    evaluation.evaluation_digest = digest('dispatch-authorization-evaluation', evaluation);
    state.authorizations.push(authorization); state.authorizations.sort((a: Row, b: Row) => byteCompare(a.authorization_digest, b.authorization_digest));
    state.authorization_evaluations.push(evaluation); state.authorization_evaluations.sort((a: Row, b: Row) => byteCompare(a.event_id, b.event_id));
    receipt.authorization_evaluation_digest = evaluation.evaluation_digest;
    receipt.details = [{ kind: 'AUTHORIZATION', authorization_digest: authorization.authorization_digest, permit_digest: permit.permit_id, approval_id: event.authorization_fence.approval_id, checked_at: event.authorization_fence.checked_at, expires_at: authorization.expires_at, sources: event.authorization_fence.sources }];
  });
  const before = canonical(request.state), result = step(request, request.specification_pin);
  assert.equal(result.code, 'STATE_INVALID'); assert.equal(canonical(request.state), before);
}

for (const context of ['expiry', 'supersession', 'completion', 'terminal stop']) {
  test(`restart rejects a fully rehashed authorization after admitted ${context}`, () => {
    const request = source(context === 'completion' ? 'C3-EC-001' : context === 'terminal stop' ? 'C3-EC-034' : 'C3-ED-003');
    let authorization: Row;
    if (context === 'completion' || context === 'terminal stop') {
      authorization = structuredClone(request.state.authorizations[0]); advance(request, request.event);
      assert.equal(request.state.status, context === 'completion' ? 'COMPLETE' : 'STOPPED');
    } else {
      authorization = advance(request, request.event).state.authorizations[0];
      const permit = request.state.permits[0];
      advance(request, { schema: VERSION + '/runtime-event', kind: 'CLOCK', event_id: 'review-expiry-clock', instance_id: request.state.instance_id, clock: { source: permit.clock_source, revision: '2', status: 'AVAILABLE', observed_time: permit.expires_at, evidence_digest: digest('review-expiry-clock', { time: permit.expires_at }) }, activation_clocks: [] });
      if (context === 'supersession') {
        const event = source('C3-ED-002').event; event.event_id = 'review-renewed-proposal'; event.clock_revision = '2';
        refresh(event.authority_input, permit.expires_at);
        event.observation_digests = event.authority_input.observations.map((row: Row) => digest('authority-observation', row)).sort(byteCompare);
        const renewed = advance(request, event); assert.equal(renewed.decision.disposition, 'PERMITTED');
        assert.equal(renewed.permit.supersedes_permit_digest, permit.permit_id);
      }
    }
    forgeAuthorization(request, authorization);
  });
}

function rebindAuthority(input: Row, change: () => void, changeAct: (act: Row) => void = () => {}): void {
  const replacements = new Map<string, string>();
  const rebind = (domain: string, row: Row, mutate: () => void): void => { const before = digest(domain, row); mutate(); replacements.set(before, digest(domain, row)); };
  const operation = (): string => digest('authority-operation', { envelope_digest: digest('authority-envelope', input.envelope), work_class_digest: digest('authority-work-class', input.work_class), proposal_digest: digest('authority-proposal', input.proposal) });
  const priorOperation = operation();
  rebind('authority-envelope', input.envelope, change);
  replacements.set(priorOperation, operation());
  rebind('authority-root', input.host_selection.root, () => { input.host_selection.root.envelope_digest = digest('authority-envelope', input.envelope); input.host_selection.root.work_class_digest = digest('authority-work-class', input.work_class); });
  for (const capacity of input.capacities) rebind('authority-capacity', capacity, () => { capacity.envelope_digest = digest('authority-envelope', input.envelope); capacity.root_digest = digest('authority-root', input.host_selection.root); });
  for (const act of [...input.acts].sort((a: Row) => a.kind === 'GRANT' ? -1 : 1)) rebind('authority-act', act, () => { act.subject_digest = replacements.get(act.subject_digest) ?? act.subject_digest; changeAct(act); });
  input.acts.sort((a: Row, b: Row) => byteCompare(digest('authority-act', a), digest('authority-act', b)));
  for (const returned of input.returns) {
    const act = input.acts.find((row: Row) => row.actor === returned.actor);
    returned.act_digest = digest('authority-act', act); returned.act_bytes_base64 = Buffer.from(canonical(act)).toString('base64');
  }
  input.host_selection.authenticated_records = ['capacities', 'occupancies', 'credentials', 'returns'].flatMap(key => input[key].map((row: Row) => ({ kind: ({ capacities: 'CAPACITY', occupancies: 'OCCUPANCY', credentials: 'CREDENTIAL', returns: 'RETURN' } as Row)[key], record_digest: digest('authority-' + ({ capacities: 'capacity', occupancies: 'occupancy', credentials: 'credential', returns: 'return' } as Row)[key], row), provider: row.provider, channel: key === 'returns' ? row.channel : null }))).sort((a: Row, b: Row) => byteCompare(canonical(a), canonical(b)));
  for (const observation of input.observations) { observation.query.subject_digest = replacements.get(observation.query.subject_digest) ?? observation.query.subject_digest; if (observation.query.subject_digest === undefined) delete observation.query.subject_digest; observation.query_digest = digest('authority-query', observation.query); }
}

test('isolated dispatch gate declaration faults and mixed faults retain authority phase precedence', () => {
  const template = source('C3-ED-003').event.authority_input;
  assert.equal(evaluateAuthority(template, template.specification_pin).status, 'READY_FOR_RESERVATION');
  const changes = [
    (input: Row) => { input.envelope.source_observation_requirements.find((row: Row) => row.id === 'approval').at = '2026-09-10T04:30:00Z'; },
    (input: Row) => { delete input.envelope.source_observation_requirements.find((row: Row) => row.id === 'approval').evaluation_point; },
    (input: Row) => { input.envelope.source_observation_requirements.find((row: Row) => row.id === 'approval').freshness_seconds = '1'; },
    (input: Row) => { input.envelope.source_observation_requirements.find((row: Row) => row.id === 'approval').purpose = 'DUPLICATE'; },
    (input: Row) => { input.envelope.source_observation_requirements.find((row: Row) => row.id === 'approval').record_id = null; },
    (input: Row) => { input.envelope.source_observation_requirements.find((row: Row) => row.id === 'approval-withdrawal').expected_status = 'AVAILABLE'; },
  ];
  for (const [i, change] of changes.entries()) {
    const input = structuredClone(template); rebindAuthority(input, () => change(input));
    assert.equal(evaluateAuthority(input, input.specification_pin).code, 'UNSUPPORTED_RELATION', String(i));
  }
  const reference = structuredClone(template);
  rebindAuthority(reference, () => { changes[2](reference); reference.envelope.source_obligations.push('unknown-obligation'); reference.envelope.source_obligations.sort(byteCompare); });
  assert.equal(evaluateAuthority(reference, reference.specification_pin).code, 'UNSUPPORTED_RELATION');
  const missingCapacity = structuredClone(template); rebindAuthority(missingCapacity, () => changes[2](missingCapacity));
  missingCapacity.capacities.pop();
  missingCapacity.host_selection.authenticated_records = missingCapacity.host_selection.authenticated_records.filter((row: Row) => row.kind !== 'CAPACITY');
  assert.equal(evaluateAuthority(missingCapacity, missingCapacity.specification_pin).code, 'EVIDENCE_UNAVAILABLE');
  const missingAuthentication = structuredClone(template); rebindAuthority(missingAuthentication, () => changes[2](missingAuthentication));
  missingAuthentication.host_selection.authenticated_records = missingAuthentication.host_selection.authenticated_records.filter((row: Row) => row.kind !== 'CREDENTIAL');
  assert.equal(evaluateAuthority(missingAuthentication, missingAuthentication.specification_pin).code, 'EVIDENCE_UNAVAILABLE');
  const missingProvider = structuredClone(template);
  rebindAuthority(missingProvider, () => { changes[2](missingProvider); missingProvider.host_selection.root.providers = ['unrelated-provider']; });
  assert.equal(evaluateAuthority(missingProvider, missingProvider.specification_pin).code, 'DEPENDENCY_MISMATCH');
  const nominal = structuredClone(template); rebindAuthority(nominal, () => changes[2](nominal));
  nominal.observations.find((row: Row) => row.fields?.some((field: Row) => field.value.type_ref === 'BOOLEAN')).fields.find((row: Row) => row.value.type_ref === 'BOOLEAN').value.value = 'true';
  assert.equal(evaluateAuthority(nominal, nominal.specification_pin).code, 'TYPE_INVALID');
  for (const [member, value] of [['nonnegative', true], ['unit', 'SECONDS']] as const) {
    const declaration = structuredClone(template);
    rebindAuthority(declaration, () => {
      changes[2](declaration);
      declaration.work_class.types.find((row: Row) => row.kind === 'BOOLEAN')[member] = value;
      declaration.envelope.work_class_digest = digest('authority-work-class', declaration.work_class);
      declaration.proposal.work_class_digest = declaration.envelope.work_class_digest;
    });
    assert.equal(evaluateAuthority(declaration, declaration.specification_pin).code, 'TYPE_INVALID');
  }
});

function graphAuthority(request: Row, occurrence: Row): Row {
  const input = structuredClone(source('C3-ED-002').event.authority_input), operation = request.definition.steps.find((row: Row) => row.id === occurrence.step_id);
  input.work_class = authorityProjection(request.definition);
  const credential = input.credentials[0], originalCredential = digest('authority-credential', credential);
  credential.step = operation.id; credential.operation = operation.operation;
  rebindAuthority(input, () => {
    input.envelope.work_class_digest = digest('authority-work-class', input.work_class); input.envelope.id = operation.authority_requirements[0];
    for (const rows of [input.envelope.operations, input.envelope.bindings, input.envelope.conditions, input.envelope.limits.per_action]) for (const row of rows) { row.step = operation.id; if (row.operation) row.operation = operation.operation; }
    for (const requirement of input.envelope.source_observation_requirements) requirement.step = 'branch-b';
  });
  Object.assign(input.proposal, { work_class_digest: input.envelope.work_class_digest, instance: request.state.instance_id, occurrence: occurrence.occurrence_id, step: operation.id, operation: operation.operation, interface: operation.interface });
  const queries = new Map(deriveSourceQueries(input).map((row: Row) => [row.requirement_id, row]));
  input.observations = input.observations.filter((row: Row) => !row.query.requirement_id || queries.has(row.query.requirement_id));
  for (const observation of input.observations) {
    if (observation.query.requirement_id) observation.query = structuredClone(queries.get(observation.query.requirement_id));
    else if (observation.query.subject_digest === originalCredential) observation.query.subject_digest = digest('authority-credential', credential);
    observation.query_digest = digest('authority-query', observation.query);
  }
  return input;
}

function proposeGraph(request: Row, stepId: string): Row {
  const occurrence = request.state.active.find((row: Row) => row.occurrence.step_id === stepId).occurrence;
  const authority = graphAuthority(request, occurrence), operation = request.definition.steps.find((row: Row) => row.id === stepId), event = source('C3-ED-002').event;
  Object.assign(event, { event_id: 'review-proposal-' + stepId, occurrence, authority_input: authority, native_request: { interface: operation.interface, operation: operation.operation, fields: structuredClone(authority.proposal.fields) }, observation_digests: authority.observations.map((row: Row) => digest('authority-observation', row)).sort(byteCompare) });
  return advance(request, event);
}

test('restart rejects authorization after another parallel branch stops an unattempted permit', () => {
  const gated = source('C3-ED-003'), request = deployChanged(source('D2-114'), definition => {
    definition.limits.maximum_actuations = '2';
    const operation = definition.steps.find((row: Row) => row.id === 'branch-b');
    operation.dispatch_gate = structuredClone(gated.definition.steps.find((row: Row) => row.id === 'issue').dispatch_gate);
    operation.authority_type_refs = ['BOOLEAN', 'INSTANT'];
    for (const type of gated.definition.types) if (!definition.types.some((row: Row) => row.id === type.id)) definition.types.push(structuredClone(type));
    definition.types.sort((a: Row, b: Row) => byteCompare(a.id, b.id));
  });
  const proposed = proposeGraph(request, 'issue'); assert.equal(proposed.decision.disposition, 'PERMITTED');
  const permit = proposed.permit, native = permit.native_request, dispatch = structuredClone(source('C3-EU-001').state.dispatches[0]);
  dispatch.attempt.attempt_id = 'review-root-attempt'; dispatch.attempt.request_digest = digest('dispatch-native-request', { instance_id: request.state.instance_id, occurrence_id: permit.occurrence.occurrence_id, ...native });
  const sent = advance(request, { schema: VERSION + '/runtime-event', kind: 'DISPATCH_OBSERVED', event_id: 'review-root-dispatch', instance_id: request.state.instance_id, permit, native_request: native, connector: dispatch.connector, attempt: dispatch.attempt, acknowledgement: dispatch.acknowledgement, clock_revision: '1' });
  const evidence = structuredClone(source('C3-EU-001').event.native_evidence);
  evidence.evidence_id = 'review-root-effect'; evidence.native_operation_id = 'review-root-effect'; evidence.provider_record_id = 'review-root-effect';
  evidence.status = 'EFFECT_ESTABLISHED'; evidence.event_time = '2026-09-10T04:30:00Z'; evidence.provider_revision = 'review-root-revision';
  evidence.actual_fields = [...structuredClone(native.fields), { name: 'status', value: { type_ref: 'STRING', value: 'ISSUED' } }].sort((a: Row, b: Row) => byteCompare(a.name, b.name));
  evidence.attributed_request = { work_class: request.definition.id, instance: request.state.instance_id, occurrence: permit.occurrence.occurrence_id, step: 'issue', ...native };
  evidence.native_request_digest = digest('native-request', evidence.attributed_request); evidence.record_digest = digest('review-root-provider-record', evidence.actual_fields);
  const completed = advance(request, { schema: VERSION + '/runtime-event', kind: 'EFFECT_OBSERVED', event_id: 'review-root-completion', instance_id: request.state.instance_id, permit, dispatch_digest: sent.state.dispatches.find((row: Row) => row.event_id === 'review-root-dispatch').dispatch_digest, native_evidence: evidence, completion_authorization: null, budget_inputs: [], clock_revision: null, activation_clocks: [] });
  assert.equal(completed.state.outcomes[0].classification, 'MATCHED');
  const target = proposeGraph(request, 'branch-b'); assert.equal(target.decision.disposition, 'PERMITTED');
  const event = structuredClone(gated.event); event.instance_id = request.state.instance_id; event.event_id = 'review-branch-authorization'; event.dispatch_intent_id = 'review-branch-intent'; event.permit = target.permit; event.native_request = target.permit.native_request;
  event.authority_input = structuredClone(target.permit.authority_basis); event.authority_input.evaluation_point = 'DISPATCH';
  const queries = new Set(deriveSourceQueries(event.authority_input).map((row: Row) => digest('authority-query', row)));
  event.authority_input.observations = event.authority_input.observations.filter((row: Row) => !row.query.requirement_id || queries.has(row.query_digest));
  event.observation_digests = event.authority_input.observations.map((row: Row) => digest('authority-observation', row)).sort(byteCompare);
  const result = evaluateAuthority(event.authority_input, request.specification_pin); assert.equal(result.status, 'READY_FOR_RESERVATION');
  const gate = request.definition.steps.find((row: Row) => row.id === 'branch-b').dispatch_gate;
  event.authorization_fence = deriveAuthorizationFence(event, gate, result, '2026-09-10T04:31:00Z');
  const authorization = advance(request, event).state.authorizations[0];
  const stopped = proposeGraph(request, 'branch-a'); assert.equal(stopped.decision.disposition, 'STOPPED');
  assert.equal(request.state.active.find((row: Row) => row.occurrence.step_id === 'branch-b').status, 'PERMITTED');
  assert.equal(request.state.dispatches.some((row: Row) => row.permit_digest === target.permit.permit_id), false);
  assert.equal(request.state.outcomes.some((row: Row) => row.permit_digest === target.permit.permit_id), false);
  forgeAuthorization(request, authorization);
});

test('correction refuses a rehashed original permit with another profile or role', () => {
  const template = source('C3-ER-001'); assert.equal(checkSourceCorrection(template, template.specification_pin).status, 'EVIDENCE_VALID');
  for (const [member, value] of [['profile', 'DEADLINES'], ['role', 'DEADLINE_RUNTIME']]) {
    const request = structuredClone(template); request.original_permit[member] = value;
    request.original_permit.permit_id = digest('permit', omit(request.original_permit, 'permit_id'));
    const before = canonical(request), result = checkSourceCorrection(request, request.specification_pin);
    assert.equal(result.code, 'DEPENDENCY_MISMATCH'); assert.equal(canonical(request), before);
  }
});

test('business correction requires a grant distinct from the original permit approval', () => {
  const request = source('C3-ER-005'); assert.equal(checkSourceCorrection(request, request.specification_pin).status, 'EVIDENCE_VALID');
  const approval = request.correction.new_approval_basis, originalGrant = request.original_permit.authority_basis.acts.find((row: Row) => row.kind === 'GRANT').id;
  rebindAuthority(approval, () => { approval.envelope.grant_ref = originalGrant; }, act => { if (act.kind === 'GRANT') act.id = originalGrant; });
  assert.equal(evaluateAuthority(approval, request.specification_pin).status, 'READY_FOR_RESERVATION');
  request.correction.provenance_digest = digest('source-correction-provenance', omit(request.correction, 'provenance_digest'));
  const before = canonical(request), result = checkSourceCorrection(request, request.specification_pin);
  assert.equal(result.code, 'BINDING_MISMATCH'); assert.equal(canonical(request), before);
});
