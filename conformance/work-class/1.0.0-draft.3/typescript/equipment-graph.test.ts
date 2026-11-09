import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { respond } from './adapter.ts';
import { byteCompare, canonical, digest } from './canonical.ts';
import { readback } from './evidence.ts';
import { authorityProjection, checkpointBefore, deploy, occurrence, stateDigest, step } from './lifecycle.ts';
import { PROTOCOL, VERSION } from './schema.ts';
import { validateWorkClass } from './work-class.ts';
import type { RecordValue as Row } from './values.ts';

const candidate = new URL('../', import.meta.url);
const load = (path: string): Row => JSON.parse(readFileSync(new URL(path, candidate), 'utf8'));
const index = load('cases/index.json').cases as Row[];
const source = (id: string): Row => load(index.find(row => row.id === id)!.path).input;
const omit = (row: Row, key: string): Row => Object.fromEntries(Object.entries(row).filter(([name]) => name !== key));

test('rejects deployment through a non-entry member of a simple loop', () => {
  const request = source('D2-048'), definition = structuredClone(request.definition);
  const tail = structuredClone(definition.steps.find((row: Row) => row.id === 'issue'));
  tail.id = 'loop-tail'; tail.completion.route_label_field = null; tail.completion.route_label_type_ref = null;
  definition.steps.push(tail); definition.steps.sort((a: Row, b: Row) => byteCompare(a.id, b.id));
  definition.root = tail.id; definition.loops[0].member_step_ids = ['issue', tail.id]; definition.loops[0].back_edge_from_step_id = tail.id;
  definition.relationships.find((row: Row) => row.to === 'issue').to = tail.id;
  definition.relationships.push({ kind: 'SEQUENCE', from: tail.id, to: 'issue' });
  definition.occurrence_limits.push({ ...definition.occurrence_limits.find((row: Row) => row.step_id === 'issue'), step_id: tail.id });
  definition.occurrence_limits.sort((a: Row, b: Row) => byteCompare(a.step_id, b.step_id));
  assert.throws(() => validateWorkClass(definition, request.specification_pin), { code: 'UNSUPPORTED_FEATURE', path: '/loops/retry-loop' });
  const input = { kind: 'WORK_CLASS', specification_pin: request.specification_pin, artifact_bytes_base64: Buffer.from(canonical(definition)).toString('base64') };
  const result = respond({ protocol: PROTOCOL, request_id: 'non-entry-root', operation: 'validate', input }, request.specification_pin).result;
  assert.deepEqual(result, { status: 'REFUSED', code: 'UNSUPPORTED_FEATURE', path: '' });
});

test('rejects a fully rehashed root occurrence with an omitted or later loop pass', () => {
  assert.equal(step(source('C3-EVE-009'), source('C3-EVE-009').specification_pin).status, 'STEP');
  for (const pass of [null, '2']) {
    const request = structuredClone(source('C3-EVE-009')), active = request.state.active[0], original = active.occurrence;
    const enclosing = pass === null ? [] : [{ ...original.enclosing[0], pass }];
    active.occurrence = occurrence(original.work_class_digest, original.instance_id, original.step_id, original.ordinal, [], enclosing, null, request.specification_pin);
    active.activation_event_digest = digest('deployment-activation', { deployment_authorization_digest: request.state.deployment_authorization_digest, instance_id: request.state.instance_id, occurrence_id: active.occurrence.occurrence_id });
    request.state_digest = stateDigest(request.state); request.event.expected_state_digest = request.state_digest;
    assert.equal(step(request, request.specification_pin).code, 'STATE_INVALID', String(pass));
  }
});

test('reconstructs every indexed graph transition from its retained prefix', t => {
  const counts: Record<string, number> = { CHOICE_LOOPS: 0, DEADLINES: 0, PARALLEL_FANOUT: 0 };
  for (const row of index) {
    if (row.operation !== 'step' || row.execution_target !== 'ADAPTER' || row.id.startsWith('C3-ES')) continue;
    const fixture = load(row.path), input = fixture.input, result = fixture.expected;
    if (!(input.profile in counts) || result.status !== 'STEP' || result.replay || result.state.revision === input.state.revision) continue;
    assert.equal(stateDigest(checkpointBefore(result.state, input.definition, BigInt(result.state.revision))), input.state_digest, row.id);
    counts[input.profile]++;
  }
  assert.ok(counts.CHOICE_LOOPS >= 8); assert.ok(counts.DEADLINES >= 12); assert.ok(counts.PARALLEL_FANOUT >= 66);
  t.diagnostic(JSON.stringify({ reconstructed_prefixes: counts }));
});

test('restarts invalid choice labels, empty joined fanouts and stopped unexpanded over-limit sets', () => {
  for (const id of ['D2-046', 'D2-133', 'D2-056', 'D2-075', 'D2-143', 'C2-empty-fanout-advance-into-parent-join']) {
    const request = structuredClone(source(id)), result = step(request, request.specification_pin);
    assert.equal(result.status, 'STEP', id); request.state = result.state; request.state_digest = result.state_digest;
    assert.equal(step(request, request.specification_pin).replay, true, id);
    advance(request, { kind: 'CLOCK', event_id: 'restart-' + id, clock: { source: 'checkpoint-audit-clock', revision: '1', status: 'UNAVAILABLE', observed_time: null, evidence_digest: digest('checkpoint-audit-clock', { id }) }, activation_clocks: [] });
    if (id === 'D2-075') { assert.equal(request.state.fanout_passes[0].object_keys.length, 2); assert.deepEqual(request.state.obligations, []); }
  }
});

function install(template: Row, stopSteps: string[]): Row {
  const request = structuredClone(template), definition = request.definition, retained = template.state;
  if (definition.fanouts.length) {
    definition.limits.maximum_fanout_objects = '2';
    for (const fanout of definition.fanouts) definition.occurrence_limits.find((row: Row) => row.step_id === fanout.region_head_step_id).maximum = '2';
  }
  const completion = source('C3-EU-001').definition.steps.find((row: Row) => row.id === 'issue').completion;
  for (const operation of definition.steps.filter((row: Row) => stopSteps.includes(row.id))) {
    operation.completion = { ...structuredClone(completion), route_label_field: operation.completion.route_label_field, route_label_type_ref: operation.completion.route_label_type_ref };
  }
  const instant = { id: 'INSTANT', kind: 'INSTANT', nonnegative: false, unit: null };
  for (const declaration of [instant, source('C3-EU-001').definition.types.find((row: Row) => row.id === 'PROVIDER_LINK')]) {
    if (!definition.types.some((row: Row) => row.id === declaration.id)) definition.types.push(structuredClone(declaration));
  }
  definition.types.sort((a: Row, b: Row) => byteCompare(a.id, b.id));
  request.definition_digest = validateWorkClass(definition, request.specification_pin).digest;
  const authorization = structuredClone(retained.deployment_authorization), evidence = structuredClone(retained.deployment_authorization_evidence);
  const correspondence = structuredClone(retained.deployment_correspondence_evidence), policy = structuredClone(retained.deployment_policy_decision_evidence);
  correspondence.subject_digest = request.definition_digest; correspondence.work_class_digest = request.definition_digest;
  correspondence.mappings[0].provision_paths = readback(definition).map(row => row.path);
  correspondence.review.subject_digest = digest('correspondence-subject', omit(correspondence, 'review'));
  policy.subject_digest = request.definition_digest;
  authorization.work_class_digest = request.definition_digest;
  authorization.correspondence_evidence_digest = digest('evidence', correspondence); authorization.policy_decision_evidence_digest = digest('evidence', policy);
  evidence.subject_digest = digest('deployment-authorization-subject', omit(authorization, 'authorization_evidence_digest'));
  evidence.authorization_scope = [request.specification_pin, request.definition_digest, request.profile, request.role, retained.instance_id].sort(byteCompare);
  authorization.authorization_evidence_digest = digest('evidence', evidence);
  const initial = retained.clocks.filter((clock: Row) => definition.deadlines.some((row: Row) => row.step_id === definition.root && row.clock_source === clock.source));
  const deployed = deploy({ profile: request.profile, role: request.role, specification_pin: request.specification_pin, instance_id: retained.instance_id, definition, definition_digest: request.definition_digest, deployment_authorization: authorization, authorization_clock: retained.deployment_authorization_clock, authorization_evidence: evidence, correspondence_evidence: correspondence, source_confirmation_evidence: retained.deployment_source_confirmation_evidence, policy_decision_evidence: policy, initial_clocks: initial }, request.specification_pin);
  assert.equal(deployed.status, 'DEPLOYED', canonical(deployed)); request.state = deployed.state; request.state_digest = deployed.state_digest;
  const clock = structuredClone(source('D2-017').state.clocks.find((row: Row) => row.source === 'authority-clock'));
  advance(request, { kind: 'CLOCK', event_id: 'graph-clock', clock, activation_clocks: [] });
  return request;
}

function authorityFor(request: Row, occurrence: Row): Row {
  const input = structuredClone(source('D2-017').event.authority_input), operation = request.definition.steps.find((row: Row) => row.id === occurrence.step_id);
  const replacements = new Map<string, string>();
  const rebind = (domain: string, row: Row, change: () => void): void => { const before = digest(domain, row); change(); replacements.set(before, digest(domain, row)); };
  input.work_class = authorityProjection(request.definition);
  rebind('authority-envelope', input.envelope, () => {
    input.envelope.work_class_digest = digest('authority-work-class', input.work_class); input.envelope.id = operation.authority_requirements[0];
    for (const rows of [input.envelope.operations, input.envelope.bindings, input.envelope.conditions, input.envelope.limits.per_action]) {
      for (const row of rows) { row.step = operation.id; if (row.operation) row.operation = operation.operation; }
    }
  });
  const envelope = digest('authority-envelope', input.envelope);
  rebind('authority-root', input.host_selection.root, () => { input.host_selection.root.work_class_digest = input.envelope.work_class_digest; input.host_selection.root.envelope_digest = envelope; });
  for (const capacity of input.capacities) rebind('authority-capacity', capacity, () => { capacity.envelope_digest = envelope; capacity.root_digest = digest('authority-root', input.host_selection.root); });
  for (const credential of input.credentials) rebind('authority-credential', credential, () => { credential.step = operation.id; credential.operation = operation.operation; });
  for (const act of [...input.acts].sort((a: Row) => a.kind === 'GRANT' ? -1 : 1)) rebind('authority-act', act, () => { act.subject_digest = replacements.get(act.subject_digest) ?? act.subject_digest; });
  input.acts.sort((a: Row, b: Row) => byteCompare(digest('authority-act', a), digest('authority-act', b)));
  for (const returned of input.returns) {
    const act = input.acts.find((row: Row) => row.actor === returned.actor);
    returned.act_digest = digest('authority-act', act); returned.act_bytes_base64 = Buffer.from(canonical(act)).toString('base64');
  }
  input.host_selection.authenticated_records = ['capacities', 'occupancies', 'credentials', 'returns'].flatMap(key => input[key].map((row: Row) => ({ kind: ({ capacities: 'CAPACITY', occupancies: 'OCCUPANCY', credentials: 'CREDENTIAL', returns: 'RETURN' } as Row)[key], record_digest: digest('authority-' + ({ capacities: 'capacity', occupancies: 'occupancy', credentials: 'credential', returns: 'return' } as Row)[key], row), provider: row.provider, channel: key === 'returns' ? row.channel : null }))).sort((a: Row, b: Row) => byteCompare(canonical(a), canonical(b)));
  for (const observation of input.observations) { observation.query.subject_digest = replacements.get(observation.query.subject_digest) ?? observation.query.subject_digest; observation.query_digest = digest('authority-query', observation.query); }
  input.observations.sort((a: Row, b: Row) => byteCompare(canonical(a), canonical(b)));
  Object.assign(input.proposal, { work_class_digest: input.envelope.work_class_digest, instance: request.state.instance_id, occurrence: occurrence.occurrence_id, step: operation.id, operation: operation.operation });
  if (occurrence.object_key) input.proposal.fields.find((row: Row) => row.name === 'card_id').value = structuredClone(occurrence.object_key);
  return input;
}

function advance(request: Row, event: Row): Row {
  request.event = { ...event, schema: VERSION + '/runtime-event', instance_id: request.state.instance_id, expected_state_revision: request.state.revision, expected_state_digest: request.state_digest };
  const result = step(request, request.specification_pin);
  assert.equal(result.status, 'STEP', JSON.stringify({ event: event.event_id, step: event.occurrence?.step_id, profile: request.profile, code: result.code, path: result.path })); request.state = result.state; request.state_digest = result.state_digest;
  assert.equal(step(request, request.specification_pin).replay, true, event.event_id);
  return result;
}

function complete(request: Row, stepId: string, status = 'ISSUED'): Row {
  const active = request.state.active.find((row: Row) => row.occurrence.step_id === stepId && row.status === 'ACTIVE');
  assert.ok(active, JSON.stringify({ step: stepId, status: request.state.status, active: request.state.active.map((row: Row) => [row.occurrence.step_id, row.status]), prior: request.state.receipts.at(-1).reason_codes }));
  const occurrence = active.occurrence;
  const authority = authorityFor(request, occurrence), template = source('D2-017').event, operation = request.definition.steps.find((row: Row) => row.id === stepId);
  const id = 'graph-' + occurrence.occurrence_id.slice(7, 19), native = { interface: operation.interface, operation: operation.operation, fields: structuredClone(authority.proposal.fields) };
  const proposed = advance(request, { ...template, event_id: id + '-proposal', occurrence, authority_input: authority, native_request: native, observation_digests: authority.observations.map((row: Row) => digest('authority-observation', row)).sort(byteCompare) });
  assert.equal(proposed.decision.disposition, 'PERMITTED', canonical(proposed.decision));
  const permit = proposed.permit, dispatch = source('C3-EU-001').state.dispatches[0];
  const sent = advance(request, { kind: 'DISPATCH_OBSERVED', event_id: id + '-dispatch', permit, native_request: native, connector: dispatch.connector, attempt: { ...dispatch.attempt, attempt_id: id + '-attempt', request_digest: digest('dispatch-native-request', { instance_id: request.state.instance_id, occurrence_id: occurrence.occurrence_id, ...native }) }, acknowledgement: dispatch.acknowledgement, clock_revision: '1' });
  const actual = [...structuredClone(native.fields), { name: 'status', value: { type_ref: 'STRING', value: status } }];
  if (operation.completion.route_label_field) actual.push({ name: 'route', value: { type_ref: 'STRING', value: 'CONTINUE' } });
  if (operation.completion.terminal_policy === 'STOP_RETAIN') actual.push(...structuredClone(operation.completion.additional_fields), { name: 'provider_event_id', value: { type_ref: 'IDENTITY', value: id } }, { name: 'event_timestamp', value: { type_ref: 'INSTANT', value: '2026-09-10T04:30:00Z' } });
  actual.sort((a: Row, b: Row) => byteCompare(a.name, b.name));
  const collections = operation.kind === 'FANOUT_EXPAND' ? [{ name: 'items', element_type_ref: 'IDENTITY', values: [{ type_ref: 'IDENTITY', value: 'card-802' }, { type_ref: 'IDENTITY', value: 'card-803' }] }] : [];
  const attributed = { work_class: request.definition.id, instance: request.state.instance_id, occurrence: occurrence.occurrence_id, step: stepId, ...native };
  const evidence = { ...structuredClone(source('C3-EU-001').event.native_evidence), status: 'EFFECT_ESTABLISHED', event_time: '2026-09-10T04:30:00Z', evidence_id: id, evidence_ref: id + '-ref', native_operation_id: id, provider_record_id: id, provider_revision: 'graph-revision-1', actual_fields: actual, collections, attributed_request: attributed, native_request_digest: digest('native-request', attributed), record_digest: digest('graph-provider-record', actual) };
  return advance(request, { kind: 'EFFECT_OBSERVED', event_id: id + '-effect', permit, dispatch_digest: sent.state.dispatches.find((row: Row) => row.event_id === id + '-dispatch').dispatch_digest, native_evidence: evidence, completion_authorization: null, clock_revision: null, budget_inputs: [], activation_clocks: [] });
}

test('admits STOP_RETAIN and restarts after loop, deadline, parallel, nested parallel and fanout completions', t => {
  const plans: [string, string[], string[]][] = [
    ['D2-048', ['issue'], ['issue', 'issue']],
    ['C2-043-effect', ['issue'], ['issue']],
    ['D2-114', ['branch-a', 'branch-b'], ['issue', 'branch-a', 'branch-a-next', 'branch-b']],
    ['D2-200', ['child-a', 'child-b'], ['issue', 'outer-a', 'child-a', 'child-b', 'outer-successor', 'outer-b']],
    ['D2-054', ['object-step'], ['issue', 'object-step', 'object-step']],
    ['C2-empty-fanout-advance-into-parent-join', ['object-b'], ['issue', 'expand-b', 'object-b', 'object-b', 'branch-a']],
  ];
  let transitions = 0, completions = 0, terminalCompletions = 0;
  for (const [id, stops, route] of plans) {
    const request = install(source(id), stops);
    for (const [i, stepId] of route.entries()) {
      const result = complete(request, stepId, id === 'D2-048' && i === 1 ? 'UNDECLARED' : 'ISSUED');
      const outcome = result.state.outcomes.find((row: Row) => row.event_id === request.event.event_id);
      assert.equal(outcome.classification, id === 'D2-048' && i === 1 ? 'UNEXPECTED' : 'MATCHED', id + '/' + stepId);
      if (stops.includes(stepId)) assert.ok(outcome.source_event, id);
    }
    assert.equal(request.state.status, id === 'D2-048' ? 'STOPPED' : 'COMPLETE', id);
    transitions += Number(request.state.revision); completions += request.state.outcomes.length;
    terminalCompletions += request.state.outcomes.filter((row: Row) => row.source_event !== undefined).length;
  }
  t.diagnostic(JSON.stringify({ graph_contexts: plans.length, admitted_transitions_and_replays: transitions, completion_events: completions, stop_retain_completion_events: terminalCompletions }));
});
