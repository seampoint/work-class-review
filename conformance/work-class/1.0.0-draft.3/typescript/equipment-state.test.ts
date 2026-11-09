import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { respond } from './adapter.ts';
import { canonical, digest } from './canonical.ts';
import { stateDigest, step } from './lifecycle.ts';
import { aggregateStep, initialReservationState, stateAdmission } from './reservations.ts';
import { PROTOCOL, selectedCandidate } from './schema.ts';
import { validateWorkClass } from './work-class.ts';
import { decisionBasis } from './completion.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);
const index = JSON.parse(readFileSync(new URL('cases/index.json', candidate), 'utf8')).cases as Row[];
const fixture = (group: string, id: string): Row => JSON.parse(readFileSync(new URL(`cases/${group}/C3-${id}.json`, candidate), 'utf8'));
const omit = (row: Row, key: string): Row => Object.fromEntries(Object.entries(row).filter(([name]) => name !== key));

function seal(request: Row): void {
  const state = request.state, core = structuredClone(state); core.receipts = []; core.replays = [];
  state.receipts.at(-1).state_after_core_digest = digest('work-state-core', core);
  for (const receipt of state.receipts) {
    receipt.decision_id = digest('decision-receipt', omit(receipt, 'decision_id'));
    const replay = state.replays.find((row: Row) => row.event_id === receipt.event_id);
    replay.event_digest = receipt.event_digest; replay.decision = structuredClone(receipt); replay.decision_receipt_digest = receipt.decision_id;
    replay.transition_state_digest = receipt.state_after_core_digest;
    replay.transaction_digest = digest('lifecycle-transaction', { state_before_digest: receipt.state_before_digest, event_digest: receipt.event_digest, decision_receipt_digest: receipt.decision_id, state_after_core_digest: receipt.state_after_core_digest, budget_results: replay.budget_results });
  }
  request.state_digest = stateDigest(state);
}

function invalidState(request: Row): void {
  const result = step(request, request.specification_pin);
  assert.equal(result.status, 'REFUSED'); assert.equal(result.code, 'STATE_INVALID');
}

function resealOutcome(request: Row, outcome: Row): void {
  const receipt = request.state.receipts.find((row: Row) => row.event_id === outcome.event_id), oldNative = digest('native-evidence', outcome.native_evidence);
  outcome.event_digest = digest('runtime-event', outcome.source_event);
  outcome.outcome_digest = digest('outcome', omit(outcome, 'outcome_digest')); receipt.event_digest = outcome.event_digest;
  const basis = decisionBasis(request.state, outcome.source_event, { disposition: receipt.disposition, reasons: receipt.reason_codes, decisionPermitDigest: receipt.permit_digest, authorityResultDigest: receipt.authority_result_digest }, outcome);
  const basisDigest = digest('decision-basis', basis), terminal = request.state.terminal_records.find((row: Row) => row.event_id === outcome.event_id);
  if (terminal) {
    terminal.event_digest = outcome.event_digest; terminal.decision_basis_digest = basisDigest;
    terminal.terminal_digest = digest('terminal-record', omit(terminal, 'terminal_digest')); receipt.terminal_digest = terminal.terminal_digest;
  }
  for (const row of request.state.referrals.filter((row: Row) => row.event_id === outcome.event_id)) {
    row.event_digest = outcome.event_digest; row.decision_basis_digest = basisDigest; row.terminal_digest = terminal?.terminal_digest ?? null;
    row.cause_digest = outcome.outcome_digest;
    assert.ok(row.evidence_digests.includes(oldNative));
    row.referral_digest = digest('referral-intent', omit(row, 'referral_digest'));
  }
  if (receipt.decision_basis_digest !== undefined) receipt.decision_basis_digest = basisDigest;
  request.state.outcomes.sort((a: Row, b: Row) => a.outcome_digest.localeCompare(b.outcome_digest));
  request.state.terminal_records.sort((a: Row, b: Row) => a.terminal_digest.localeCompare(b.terminal_digest));
  request.state.referrals.sort((a: Row, b: Row) => a.referral_digest.localeCompare(b.referral_digest)); seal(request);
}

test('matches the 108 frozen history, completion and boundary author cases', () => {
  const pin = selectedCandidate(); let count = 0;
  for (const group of ['equipment-history', 'equipment-completion', 'equipment-boundary']) {
    for (const row of index.filter(row => row.path.startsWith(`cases/${group}/`))) {
      const source = JSON.parse(readFileSync(new URL(row.path, candidate), 'utf8'));
      const result = respond({ protocol: PROTOCOL, request_id: source.id, operation: source.operation, input: source.input }, pin).result;
      assert.equal(canonical(result), canonical(source.expected), source.id); count++;
    }
  }
  assert.equal(count, 108);
});

test('restart rejects a rehashed terminal cause and substituted referral destination', () => {
  const original = fixture('equipment-completion', 'EC-058').input;
  const control = structuredClone(original); seal(control);
  assert.equal(step(control, control.specification_pin).replay, true);
  const cause = structuredClone(original), terminal = cause.state.terminal_records[0], oldDigest = terminal.terminal_digest;
  terminal.cause = 'UNEXPECTED_COMPLETION'; terminal.terminal_digest = digest('terminal-record', omit(terminal, 'terminal_digest'));
  const receipt = cause.state.receipts.find((row: Row) => row.terminal_digest === oldDigest); receipt.terminal_digest = terminal.terminal_digest;
  for (const referral of cause.state.referrals) { referral.terminal_digest = terminal.terminal_digest; referral.referral_digest = digest('referral-intent', omit(referral, 'referral_digest')); }
  cause.state.referrals.sort((a: Row, b: Row) => a.referral_digest.localeCompare(b.referral_digest)); seal(cause); invalidState(cause);
  const destination = structuredClone(original), row = destination.state.referrals[0]; row.queue = 'another-queue'; row.referral_digest = digest('referral-intent', omit(row, 'referral_digest'));
  destination.state.referrals.sort((a: Row, b: Row) => a.referral_digest.localeCompare(b.referral_digest)); seal(destination); invalidState(destination);
});

test('restart recomputes full matched native fields after evidence and state hashes are rebound', () => {
  const request = structuredClone(fixture('equipment-completion', 'EC-031').input), outcome = request.state.outcomes[0];
  const field = outcome.native_evidence.actual_fields.find((row: Row) => row.name === 'amount'); field.value.value = '151';
  outcome.native_evidence.record_digest = digest('synthetic-provider-fault', outcome.native_evidence.actual_fields);
  outcome.source_event.native_evidence = structuredClone(outcome.native_evidence);
  outcome.event_digest = digest('runtime-event', outcome.source_event);
  outcome.outcome_digest = digest('outcome', omit(outcome, 'outcome_digest'));
  request.state.completed[0].evidence_digest = digest('native-evidence', outcome.native_evidence);
  request.state.receipts.find((row: Row) => row.event_id === outcome.event_id).event_digest = outcome.event_digest;
  seal(request); invalidState(request);
});

test('restart binds lookup keys after the complete lookup and check are rehashed', () => {
  const request = structuredClone(fixture('equipment-completion', 'EC-058').input), check = request.state.completion_checks[0];
  check.lookup.query.key[0].value.value = 'forged-key';
  check.lookup.query_digest = digest('completion-query', check.lookup.query);
  check.lookup.provenance_digest = digest('completion-lookup-provenance', omit(check.lookup, 'provenance_digest'));
  check.check_digest = digest('completion-check', omit(check, 'check_digest'));
  request.state.receipts.find((row: Row) => row.event_id === check.event_id).completion_check_digest = check.check_digest;
  seal(request); invalidState(request);
});

test('restart reevaluates supplied no-effect authorization after every event and terminal commitment is rebound', () => {
  const request = structuredClone(fixture('equipment-completion', 'EC-035').input), event = request.event, permit = event.permit;
  const nativeDigest = digest('native-evidence', event.native_evidence), authorization = structuredClone(request.state.deployment_authorization_evidence);
  authorization.subject_digest = digest('no-effect-completion', { specification_pin: request.specification_pin, work_class_digest: request.definition_digest, instance_id: request.state.instance_id, occurrence_id: permit.occurrence.occurrence_id, permit_id: permit.permit_id, dispatch_digest: event.dispatch_digest, native_evidence_digest: nativeDigest });
  authorization.authorization_scope = [request.specification_pin, request.definition_digest, request.state.instance_id, permit.occurrence.occurrence_id, permit.permit_id, event.dispatch_digest, nativeDigest].sort();
  authorization.recorded_at = event.native_evidence.observed_at; authorization.expires_at = '2026-09-10T05:00:00Z'; event.completion_authorization = authorization;
  const result = step(request, request.specification_pin); assert.equal(result.status, 'STEP');
  request.state = result.state; request.state_digest = result.state_digest;
  assert.equal(step(request, request.specification_pin).replay, true);
  const outcome = request.state.outcomes[0]; outcome.source_event.completion_authorization.subject_digest = digest('wrong-no-effect-authority', {});
  resealOutcome(request, outcome); invalidState(request);
});

test('restart recomputes the registry input after the complete effect event and checkpoint roots are rebound', () => {
  const request = structuredClone(fixture('equipment-completion', 'EC-067').input), result = step(request, request.specification_pin);
  assert.equal(result.status, 'STEP'); request.state = result.state; request.state_digest = result.state_digest;
  assert.equal(step(request, request.specification_pin).replay, true);
  const outcome = request.state.outcomes.find((row: Row) => row.event_id === request.event.event_id);
  outcome.source_event.budget_inputs[0].request.state_digest = digest('wrong-original-registry-root', {});
  resealOutcome(request, outcome); invalidState(request);
});

test('a later observation of the same terminal provider fact keeps its original registry settlement', () => {
  const request = structuredClone(fixture('equipment-completion', 'EC-067').input), first = step(request, request.specification_pin);
  assert.equal(first.status, 'STEP');
  const clockRequest = structuredClone(request); clockRequest.state = first.state; clockRequest.state_digest = first.state_digest;
  const clock = structuredClone(first.state.clocks.at(-1)); clock.revision = '2'; clock.observed_time = '2026-09-10T04:31:00Z';
  clock.evidence_digest = digest('clock', { source: clock.source, revision: clock.revision, status: clock.status, observed_time: clock.observed_time });
  clockRequest.event = { schema: request.event.schema, event_id: 'later-terminal-observation-clock', kind: 'CLOCK', instance_id: request.state.instance_id, expected_state_revision: first.state.revision, expected_state_digest: first.state_digest, clock, activation_clocks: [] };
  const advanced = step(clockRequest, request.specification_pin); assert.equal(advanced.status, 'STEP');
  request.state = advanced.state; request.state_digest = advanced.state_digest;
  const event = request.event, input = event.budget_inputs[0], registry = input.request, priorRegistry = first.budget_results[0].result.state;
  event.event_id = 'same-provider-fact-later-observation'; event.expected_state_revision = advanced.state.revision; event.expected_state_digest = advanced.state_digest;
  event.native_evidence.evidence_id = 'same-provider-fact-receipt-2'; event.native_evidence.evidence_ref = 'same-provider-fact-ref-2'; event.native_evidence.observed_at = clock.observed_time; event.clock_revision = clock.revision;
  input.expected_revision = priorRegistry.core.revision; registry.state = structuredClone(priorRegistry); registry.state_digest = digest('reservation-state', priorRegistry);
  const native = { ...structuredClone(priorRegistry.core.effects[0].native), id: event.native_evidence.evidence_id, evidence_ref: event.native_evidence.evidence_ref };
  registry.event = { id: digest('lifecycle-reservation-event', { instance_id: event.instance_id, lifecycle_event_id: event.event_id, lifecycle_event_kind: 'EFFECT_OBSERVED', reservation_event_kind: 'SETTLE', registry_digest: input.registry_digest }), expected_revision: input.expected_revision, kind: 'SETTLE', clock: { source: clock.source, status: 'AVAILABLE', instant: clock.observed_time }, payload: { native, histories: [] }, administration: null };
  registry.host_evidence.authenticated_records = [{ kind: 'NATIVE_OUTCOME', record_digest: digest('reservation-native-outcome', native), provider: native.provider, source: native.source }];
  const result = step(request, request.specification_pin); assert.equal(result.status, 'STEP');
  assert.equal(result.decision.disposition, 'OUTCOME_RETAINED'); assert.deepEqual(result.decision.reason_codes, ['DUPLICATE_EVIDENCE']);
  assert.deepEqual(result.state.terminal_records, advanced.state.terminal_records);
  assert.ok(result.budget_results[0].result.state.core.exclusive_keys.every((row: Row) => row.status === 'CONSUMED'));
  request.state = result.state; request.state_digest = result.state_digest;
  assert.equal(step(request, request.specification_pin).replay, true);
});

test('restart preserves the original cause after late exact evidence and after a late conflict', () => {
  for (const id of ['EC-063', 'EC-064', 'EC-069']) {
    const source = fixture('equipment-completion', id), request = structuredClone(source.input), result = step(request, request.specification_pin);
    assert.equal(result.status, 'STEP');
    request.state = result.state; request.state_digest = result.state_digest;
    assert.equal(step(request, request.specification_pin).replay, true, id);
    if (source.input.state.terminal_records.length) assert.deepEqual(result.state.terminal_records, source.input.state.terminal_records);
  }
});

test('all history declarations are admitted before use and no top-level rehash repairs altered cutover evidence', () => {
  const source = fixture('equipment-history', 'EH-001').input, configuration = structuredClone(source.state.core.configuration);
  configuration.exclusive_slots[0].history_projection[0].type_ref = 'UNKNOWN';
  assert.throws(() => initialReservationState(configuration, source.specification_pin), { code: 'REFERENCE_INVALID' });
  const seeded = fixture('equipment-history', 'EH-002').expected.state;
  const changed = structuredClone(seeded); changed.core.key_history[0].snapshot.coverage.exclusive_writers = false;
  changed.core.key_history[0].snapshot_digest = digest('exclusive-history-snapshot', changed.core.key_history[0].snapshot);
  assert.throws(() => stateAdmission(changed, source.specification_pin), { code: 'STATE_INVALID' });
});

test('settlement consumes new occurrence owners while leaving five immutable cutovers unchanged', () => {
  const source = fixture('equipment-history', 'EH-020'), state = structuredClone(source.expected.state), reservation = state.core.reservations[0];
  const request = structuredClone(source.input), clock = structuredClone(source.input.event.clock), proposal = reservation.authority.proposal;
  const nativeRequest = Object.fromEntries(['work_class', 'instance', 'occurrence', 'step', 'operation', 'interface', 'fields'].map(name => [name, structuredClone(proposal[name])]));
  const native = { id: 'history-settlement', provider: 'card-provider', source: 'card-system', reservation: reservation.id, outcome: 'EFFECT', request: nativeRequest, observed_request: nativeRequest, effect_id: 'provider-effect-history', occurred_at: clock.instant, rules_out_past_and_future_effects: false, evidence_ref: 'history-settlement-evidence', actual_fields: structuredClone(proposal.fields), collections: [], completion_mismatch: false, mismatch_reason: null };
  request.state = state; request.state_digest = digest('reservation-state', state);
  request.event = { id: 'settle-new-history-owners', expected_revision: state.core.revision, kind: 'SETTLE', clock, payload: { native, histories: [] }, administration: null };
  request.host_evidence.administration_bases = [];
  request.host_evidence.authenticated_records = [{ kind: 'NATIVE_OUTCOME', record_digest: digest('reservation-native-outcome', native), provider: native.provider, source: native.source }];
  const result = aggregateStep(request, request.specification_pin); assert.equal(result.status, 'TRANSITION'); assert.equal(result.receipt.decision, 'SETTLED');
  assert.deepEqual(result.state.core.key_history, state.core.key_history);
  assert.equal(result.state.core.exclusive_keys.length, 5); assert.ok(result.state.core.exclusive_keys.every((row: Row) => row.status === 'CONSUMED' && row.owner.kind === 'WORK_OCCURRENCE'));
  stateAdmission(result.state, request.specification_pin);
});

test('STOP_RETAIN admits complete constants and rejects a semantic completion inventory over 66 fields', () => {
  const source = fixture('equipment-completion', 'EC-001'), definition = structuredClone(source.input.definition), step = definition.steps.find((row: Row) => row.completion?.terminal_policy === 'STOP_RETAIN');
  const types = step.completion.additional_fields[0].value.type_ref;
  step.completion.additional_fields = Array.from({ length: 62 }, (_, i) => ({ name: 'extra-' + String(i).padStart(2, '0'), value: { type_ref: types, value: 'constant' } }));
  assert.throws(() => validateWorkClass(definition, source.input.specification_pin), { code: 'LIMIT_EXCEEDED' });
});

test('a declared failed native result retains every reserved key and stops work', () => {
  const request = structuredClone(fixture('equipment-completion', 'EC-067').input), dispatch = fixture('equipment-completion', 'EC-066').input;
  request.state = structuredClone(dispatch.state); request.state_digest = dispatch.state_digest;
  request.event.expected_state_revision = request.state.revision; request.event.expected_state_digest = request.state_digest;
  const evidence = request.event.native_evidence;
  evidence.actual_fields.find((row: Row) => row.name === 'status').value.value = 'REJECTED';
  evidence.record_digest = digest('synthetic-provider-fault', evidence.actual_fields);
  const registry = request.event.budget_inputs[0].request, native = registry.event.payload.native;
  native.actual_fields = structuredClone(evidence.actual_fields); native.completion_mismatch = true; native.mismatch_reason = 'UNEXPECTED_EFFECT';
  registry.host_evidence.authenticated_records = [{ kind: 'NATIVE_OUTCOME', record_digest: digest('reservation-native-outcome', native), provider: native.provider, source: native.source }];
  const result = step(request, request.specification_pin);
  assert.equal(result.status, 'STEP'); assert.equal(result.state.outcomes[0].classification, 'FAILED');
  assert.equal(result.state.status, 'STOPPED'); assert.equal(result.state.active[0].status, 'BLOCKED_DISPUTE');
  assert.ok(result.decision.reason_codes.includes('DECLARED_FAILURE'));
  assert.ok(result.budget_results[0].result.state.core.exclusive_keys.every((row: Row) => row.status === 'HELD'));
  request.state = result.state; request.state_digest = result.state_digest;
  assert.equal(step(request, request.specification_pin).replay, true);
});

test('completion inventory faults with matching request fields send no observed request to the registry', () => {
  for (const fault of ['undeclared-status', 'missing-record-identity', 'wrong-event-time', 'wrong-additional-link']) {
    const request = structuredClone(fixture('equipment-completion', 'EC-067').input), before = fixture('equipment-completion', 'EC-066').input;
    request.state = structuredClone(before.state); request.state_digest = before.state_digest;
    request.event.expected_state_revision = request.state.revision; request.event.expected_state_digest = request.state_digest;
    const evidence = request.event.native_evidence;
    if (fault === 'undeclared-status') evidence.actual_fields.find((row: Row) => row.name === 'status').value.value = 'UNDECLARED';
    if (fault === 'missing-record-identity') evidence.actual_fields = evidence.actual_fields.filter((row: Row) => row.name !== 'provider_event_id');
    if (fault === 'wrong-event-time') evidence.actual_fields.find((row: Row) => row.name === 'event_timestamp').value.value = '2026-09-10T04:29:59Z';
    if (fault === 'wrong-additional-link') evidence.actual_fields.find((row: Row) => row.name === 'approval_link').value.value = canonical({ provider: 'identity-provider', source: 'equipment-synthetic-approvals', record_type: 'approval', provider_record_id: 'another-grant' });
    evidence.record_digest = digest('synthetic-provider-fault', evidence.actual_fields);
    const registry = request.event.budget_inputs[0].request, native = registry.event.payload.native;
    native.actual_fields = structuredClone(evidence.actual_fields); native.observed_request = null; native.completion_mismatch = true; native.mismatch_reason = 'UNEXPECTED_EFFECT';
    registry.host_evidence.authenticated_records = [{ kind: 'NATIVE_OUTCOME', record_digest: digest('reservation-native-outcome', native), provider: native.provider, source: native.source }];
    const result = step(request, request.specification_pin); assert.equal(result.status, 'STEP', fault);
    assert.equal(result.state.outcomes.find((row: Row) => row.event_id === request.event.event_id).classification, 'UNEXPECTED', fault);
    assert.ok(result.budget_results[0].result.state.core.exclusive_keys.every((row: Row) => row.status === 'HELD'), fault);
    request.state = result.state; request.state_digest = result.state_digest;
    assert.equal(step(request, request.specification_pin).replay, true, fault);
  }
});

test('authority referrals select failed source requirements and retain the supervisor intermediary', () => {
  const source = fixture('equipment-referrals', 'EAR-003').input, result = step(source, source.specification_pin);
  assert.equal(result.status, 'STEP'); assert.equal(result.state.referrals.length, 2);
  const safety = result.state.referrals.find((row: Row) => row.destination_role === 'safety-compliance-lead');
  assert.equal(safety.via_role, 'reliability-supervisor'); assert.equal(safety.terminal_digest, null);
  assert.deepEqual(safety.evidence_digests, [result.decision.authority_result_digest, result.decision.proposal_authority_evaluation_digest].sort());
  assert.deepEqual(result.state.proposal_authority_evaluations[0].event, source.event);
});
