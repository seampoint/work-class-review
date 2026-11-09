import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { instant, instantText } from './time.ts';
import { ordered, same, typed } from './values.ts';
import type { RecordValue as Row, Types } from './values.ts';

const clone = <T>(value: T): T => structuredClone(value);
function fail(code: string): never { throw new AdmissionError(code); }
const elapsed = (due: Row): bigint => BigInt(due.value) * BigInt(due.unit === 'SECOND' ? 1 : due.unit === 'MINUTE' ? 60 : due.unit === 'HOUR' ? 3600 : 86400) * 1_000_000_000n;
export const eventDuty = (row: Row): boolean => row.due.kind === 'ELAPSED_FROM_EVENT_ANCHOR';
export const deferredDeadline = (row: Row): boolean => ['ELAPSED_FROM_FIRST_WITHHELD', 'ELAPSED_FROM_FIRST_DISPATCH'].includes(row.due.kind);
export const ordinaryDeadline = (row: Row): boolean => !eventDuty(row) && !deferredDeadline(row);
export const timingDefinition = (definition: Row): boolean => definition.event_anchors !== undefined || definition.deadlines.some((row: Row) => !ordinaryDeadline(row));
export const firstWithheldStep = (definition: Row, step: string): boolean => definition.deadlines.some((row: Row) => row.step_id === step && row.due.kind === 'ELAPSED_FROM_FIRST_WITHHELD');
export const timingEvaluationInventory = (definition: Row): boolean => definition.deadlines.some((row: Row) => row.due.kind === 'ELAPSED_FROM_FIRST_WITHHELD');
export const declaredDeadlineIds = (definition: Row, step: string): string[] => definition.deadlines.filter((row: Row) => row.step_id === step).map((row: Row) => row.id).sort(byteCompare);
export const timingProjection = (state: Row): string[] => ['event_duties', 'deferred_deadlines'].filter(name => state[name] !== undefined);
export const dueAt = (row: Row, clock: Row): boolean => row.boundary === 'AT_OR_AFTER' ? instant(clock.observed_time) >= instant(row.due) : instant(clock.observed_time) > instant(row.due);
export function selectedAnchorTime(declaration: Row, wrapper: Row): string {
  return declaration.time.kind === 'EVENT_TIME' ? wrapper.record.event_time : wrapper.record.fields.find((row: Row) => row.name === declaration.time.field_ref)!.value.value;
}

export function admitTimingDefinition(definition: Row, types: Types, graph: Map<string, Row[]>, contexts: Map<string, Set<string>>): void {
  const declarations = definition.event_anchors ?? [], steps = new Map<string, Row>(definition.steps.map((row: Row) => [row.id, row]));
  if (!ordered(declarations.map((row: Row) => row.id))) fail('DEFINITION_INVALID');
  for (const declaration of declarations) {
    if (!ordered(declaration.fields.map((row: Row) => row.name)) || !ordered(declaration.subject_fields) || !ordered(declaration.request_bindings.map((row: Row) => canonical([row.step_id, row.target_request_field])))) fail('DEFINITION_INVALID');
    const fields = new Map<string, Row>(declaration.fields.map((row: Row) => [row.name, row]));
    if (declaration.fields.some((row: Row) => !types.has(row.type_ref)) || declaration.subject_fields.some((name: string) => !fields.has(name))) fail('REFERENCE_INVALID');
    const timeRef = declaration.time.kind === 'EVENT_TIME' ? declaration.time.type_ref : fields.get(declaration.time.field_ref)?.type_ref;
    if (!timeRef || !types.has(timeRef)) fail('REFERENCE_INVALID');
    if (types.get(timeRef)!.kind !== 'INSTANT') fail('DEFINITION_INVALID');
    for (const binding of declaration.request_bindings) {
      const step = steps.get(binding.step_id), source = fields.get(binding.subject_field), target = step?.fields.find((row: Row) => row.name === binding.target_request_field);
      if (!step || !['OPERATION', 'FANOUT_EXPAND'].includes(step.kind) || !declaration.subject_fields.includes(binding.subject_field) || !source || !target) fail('REFERENCE_INVALID');
      if (source.type_ref !== target.type_ref) fail('DEFINITION_INVALID');
    }
    const targets = [definition.root, ...definition.deadlines.filter((row: Row) => eventDuty(row) && row.due.anchor_ref === declaration.id).map((row: Row) => row.step_id)];
    for (const target of targets) for (const subject of declaration.subject_fields) if (!declaration.request_bindings.some((row: Row) => row.step_id === target && row.subject_field === subject)) fail('DEFINITION_INVALID');
  }
  for (const deadline of definition.deadlines) {
    if (deadline.due.kind === 'ELAPSED_FROM_FIRST_WITHHELD') {
      if (BigInt(definition.limits.maximum_proposals) > 128n) fail('LIMIT_EXCEEDED');
      const selectors = deadline.due.failed_checks;
      if (!ordered(selectors.map(canonical))) fail('DEFINITION_INVALID');
    }
    if (!eventDuty(deadline)) continue;
    if (!declarations.some((row: Row) => row.id === deadline.due.anchor_ref)) fail('REFERENCE_INVALID');
    const target = deadline.step_id, context = contexts.get(target)!;
    if (target === definition.root || [...context].some(value => value.startsWith('L:') || value.startsWith('F:')) || definition.occurrence_limits.find((row: Row) => row.step_id === target)?.maximum !== '1') fail('DEFINITION_INVALID');
    const reached = new Set<string>([definition.root]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const [from, edges] of graph) for (const edge of edges) {
        if (!reached.has(from) || edge.to === target || reached.has(edge.to)) continue;
        const block = definition.parallel_blocks.find((block: Row) => block.join_step_id === edge.to);
        if (block && !block.branches.every((branch: Row) => [...graph].some(([predecessor, incoming]) => reached.has(predecessor) && contexts.get(predecessor)!.has('B:' + block.id + ':' + branch.id) && incoming.some(edge => edge.to === block.join_step_id)))) continue;
        reached.add(edge.to); changed = true;
      }
    }
    if ([...reached].some(node => steps.get(node)!.kind === 'TERMINAL')) fail('DEFINITION_INVALID');
  }
}

export function admitInitialAnchors(definition: Row, wrappers: Row[] | undefined, authorization: Row, clock: Row): Row[] | undefined {
  const declarations = definition.event_anchors;
  if (declarations === undefined) {
    if (wrappers !== undefined || authorization.event_anchor_digests !== undefined) fail('DEPENDENCY_MISMATCH');
    return undefined;
  }
  if (!wrappers || declarations.some((declaration: Row) => !wrappers.some(row => row.anchor_ref === declaration.id))) fail('EVIDENCE_UNAVAILABLE');
  if (!ordered(wrappers.map(row => row.anchor_ref))) fail('INPUT_INVALID');
  if (!same(wrappers.map(row => row.anchor_ref), declarations.map((row: Row) => row.id))) fail('DEPENDENCY_MISMATCH');
  const types: Types = new Map(definition.types.map((row: Row) => [row.id, row]));
  for (const wrapper of wrappers) {
    const declaration = declarations.find((row: Row) => row.id === wrapper.anchor_ref), record = wrapper.record;
    if (wrapper.specification_pin !== authorization.specification_pin || wrapper.work_class_digest !== authorization.work_class_digest) fail('DEPENDENCY_MISMATCH');
    if (wrapper.record_digest !== digest('event-anchor-record', record)) fail('DIGEST_MISMATCH');
    if (wrapper.organization_id !== authorization.organization_id || wrapper.instance_id !== authorization.instance_id || record.provider !== declaration.provider || record.source !== declaration.source || record.record_type !== declaration.record_type) fail('BINDING_MISMATCH');
    if (!same(record.fields.map((row: Row) => row.name), declaration.fields.map((row: Row) => row.name))) fail('BINDING_MISMATCH');
    if (!same(record.fields.map((row: Row) => row.value.type_ref), declaration.fields.map((row: Row) => row.type_ref))) fail('TYPE_INVALID');
    record.fields.forEach((row: Row) => typed(row.value, types));
    try {
      const eventTime = instant(record.event_time), observed = instant(record.observed_at), selected = instant(selectedAnchorTime(declaration, wrapper));
      if (eventTime > observed || observed > instant(clock.observed_time) || selected > observed) fail('CLOCK_INVALID');
    } catch (error) { if (error instanceof AdmissionError && error.code === 'TIME_INVALID') fail('INPUT_INVALID'); throw error; }
  }
  const digests = wrappers.map(row => ({ anchor_ref: row.anchor_ref, anchor_digest: digest('initial-event-anchor', row) }));
  if (authorization.event_anchor_digests === undefined || !same(authorization.event_anchor_digests, digests)) fail('BINDING_MISMATCH');
  return clone(wrappers);
}

export function checkAnchorRequest(state: Row, definition: Row, step: string, fields: Row[]): void {
  for (const declaration of definition.event_anchors ?? []) {
    const wrapper = state.initial_event_anchors.find((row: Row) => row.anchor_ref === declaration.id);
    for (const binding of declaration.request_bindings.filter((row: Row) => row.step_id === step)) {
      const expected = wrapper.record.fields.find((row: Row) => row.name === binding.subject_field)?.value, actual = fields.find(row => row.name === binding.target_request_field)?.value;
      if (!expected || !actual || !same(expected, actual)) fail('BINDING_MISMATCH');
    }
  }
}

function dutyRow(state: Row, definition: Row, declaration: Row): Row {
  const anchor = definition.event_anchors.find((row: Row) => row.id === declaration.due.anchor_ref), wrapper = state.initial_event_anchors.find((row: Row) => row.anchor_ref === anchor.id);
  const anchorDigest = digest('initial-event-anchor', wrapper), due = instantText(instant(selectedAnchorTime(anchor, wrapper)) + elapsed(declaration.due));
  const body = { deadline_id: declaration.id, target_step_id: declaration.step_id, source: declaration.clock_source, boundary: declaration.boundary, anchor_ref: anchor.id, anchor_digest: anchorDigest, due };
  const creation = { specification_pin: state.specification_pin, work_class_digest: state.work_class_digest, instance_id: state.instance_id, deadline_id: declaration.id, anchor_digest: anchorDigest, due, boundary: declaration.boundary, source: declaration.clock_source };
  return { ...body, creation_digest: digest('initial-event-duty', creation), status: 'PENDING', occurrence_id: null, binding_event_digest: null };
}
function deferredRow(state: Row, declaration: Row, occurrence: Row, activation: string): Row {
  const body = { deadline_id: declaration.id, occurrence_id: occurrence.occurrence_id, source: declaration.clock_source, boundary: declaration.boundary, activation_event_digest: activation };
  return { ...body, creation_digest: digest('deferred-deadline', { specification_pin: state.specification_pin, work_class_digest: state.work_class_digest, instance_id: state.instance_id, deadline_id: declaration.id, occurrence_id: occurrence.occurrence_id, activation_event_digest: activation }), status: 'WAITING' };
}
export function sortTimingRows(state: Row): void {
  state.event_duties?.sort((a: Row, b: Row) => byteCompare(a.deadline_id, b.deadline_id));
  const occurrences = [...state.active, ...state.completed];
  state.deferred_deadlines?.sort((a: Row, b: Row) => byteCompare(canonical(occurrences.find((row: Row) => row.occurrence.occurrence_id === a.occurrence_id)?.occurrence ?? a.occurrence_id), canonical(occurrences.find((row: Row) => row.occurrence.occurrence_id === b.occurrence_id)?.occurrence ?? b.occurrence_id)) || byteCompare(a.deadline_id, b.deadline_id));
}
export function initializeTiming(state: Row, definition: Row, wrappers: Row[] | undefined): void {
  if (timingDefinition(definition)) state.timing_clock_events = [];
  if (wrappers !== undefined) state.initial_event_anchors = clone(wrappers);
  if (definition.deadlines.some(eventDuty)) {
    state.event_duties = definition.deadlines.filter(eventDuty).map((row: Row) => dutyRow(state, definition, row));
    for (const duty of state.event_duties) {
      const clock = state.clocks.find((row: Row) => row.source === duty.source && row.status === 'AVAILABLE');
      if (clock && dueAt(duty, clock)) { duty.status = 'EXPIRED'; duty.expiry_basis = { kind: 'DEPLOYMENT', deployment_authorization_digest: state.deployment_authorization_digest, clock: clone(clock) }; }
    }
  }
  if (definition.deadlines.some(deferredDeadline)) state.deferred_deadlines = [];
  bindTimingOccurrences(state, definition);
}
export function bindTimingOccurrences(state: Row, definition: Row): void {
  const projected = allDeadlineRows(state).length + state.active.reduce((count: number, active: Row) => count + definition.deadlines.filter((row: Row) => row.step_id === active.occurrence.step_id && deferredDeadline(row) && !(state.deferred_deadlines ?? []).some((retained: Row) => retained.deadline_id === row.id && retained.occurrence_id === active.occurrence.occurrence_id)).length, 0);
  if (projected > 4096) fail('LIMIT_EXCEEDED');
  for (const active of state.active) for (const declaration of definition.deadlines.filter((row: Row) => row.step_id === active.occurrence.step_id && !ordinaryDeadline(row))) {
    if (eventDuty(declaration)) {
      const row = state.event_duties.find((row: Row) => row.deadline_id === declaration.id);
      if (row.occurrence_id !== null && row.occurrence_id !== active.occurrence.occurrence_id) fail('STATE_INVALID');
      row.occurrence_id = active.occurrence.occurrence_id; row.binding_event_digest = active.activation_event_digest;
    } else if (!state.deferred_deadlines.some((row: Row) => row.deadline_id === declaration.id && row.occurrence_id === active.occurrence.occurrence_id)) state.deferred_deadlines.push(deferredRow(state, declaration, active.occurrence, active.activation_event_digest));
    active.deadline_ids = declaredDeadlineIds(definition, active.occurrence.step_id);
  }
  sortTimingRows(state);
}
export function allDeadlineRows(state: Row): Row[] { return [...state.deadlines, ...(state.event_duties ?? []), ...(state.deferred_deadlines ?? [])]; }
export function matchingCheck(declaration: Row, result: Row): boolean { return result.failed_checks?.some((row: Row) => declaration.due.failed_checks.some((selector: Row) => selector.purpose === row.purpose && selector.requirement_ref === row.requirement_ref && selector.reason === row.reason)) ?? false; }
export function armTiming(state: Row, definition: Row, event: Row, input: Row): string[] {
  const overflows: string[] = [];
  const sequence = String(BigInt(state.revision) + 1n);
  for (const row of state.deferred_deadlines ?? []) {
    if (row.status !== 'WAITING') continue;
    const declaration = definition.deadlines.find((declaration: Row) => declaration.id === row.deadline_id);
    let trigger: Row | undefined, start: string | undefined;
    if (declaration.due.kind === 'ELAPSED_FROM_FIRST_WITHHELD' && event.kind === 'PROPOSE' && event.occurrence.occurrence_id === row.occurrence_id && input.disposition === 'WITHHELD' && input.authorityResult?.status === 'REFUSED' && event.authority_input.clock.status === 'AVAILABLE' && matchingCheck(declaration, input.authorityResult)) {
      const clock = state.clocks.find((clock: Row) => clock.source === row.source && clock.revision === event.clock_revision && clock.status === 'AVAILABLE');
      if (!clock || event.authority_input.clock.source !== row.source) fail('CLOCK_INVALID');
      const body = { event: clone(event), authority_result: clone(input.authorityResult), authority_result_digest: input.authorityResultDigest };
      trigger = { kind: 'FIRST_WITHHELD', evaluation_digest: digest('proposal-authority-evaluation', body), sequence, clock: clone(clock) }; start = clock.observed_time;
    } else if (declaration.due.kind === 'ELAPSED_FROM_FIRST_DISPATCH' && event.kind === 'DISPATCH_OBSERVED' && event.permit.occurrence.occurrence_id === row.occurrence_id && (['SENT', 'UNKNOWN'].includes(event.attempt.status) || event.acknowledgement.status === 'ACCEPTED')) {
      const dispatch = state.dispatches.find((dispatch: Row) => dispatch.event_id === event.event_id), clock = state.clocks.find((clock: Row) => clock.source === row.source && clock.revision === event.clock_revision && clock.status === 'AVAILABLE');
      if (!dispatch || !clock || event.permit.clock_source !== row.source) fail('CLOCK_INVALID');
      trigger = { kind: 'FIRST_DISPATCH', event_digest: digest('runtime-event', event), sequence, dispatch_digest: dispatch.dispatch_digest, dispatch_attempt_digest: dispatch.dispatch_attempt_digest, clock: clone(clock) }; start = dispatch.attempt.attempted_at;
    }
    if (!trigger || start === undefined) continue;
    row.trigger = trigger;
    try { row.due = instantText(instant(start) + elapsed(declaration.due)); row.status = 'PENDING'; }
    catch (error) { if (!(error instanceof AdmissionError) || error.code !== 'TIME_RANGE') throw error; row.status = 'TRIGGER_OVERFLOW'; row.reason = 'DEADLINE_TIME_OVERFLOW'; overflows.push(row.deadline_id); }
  }
  return overflows;
}
export function dischargeTiming(state: Row, event: Row): void {
  for (const row of [...(state.event_duties ?? []), ...(state.deferred_deadlines ?? [])]) {
    if (!['PENDING', 'WAITING'].includes(row.status) || row.occurrence_id === null) continue;
    const completed = state.completed.find((completed: Row) => completed.occurrence.occurrence_id === row.occurrence_id);
    if (completed && completed.disposition !== 'EXPIRED') { row.status = 'DISCHARGED'; row.discharge_basis = { kind: 'COMPLETION', event_digest: digest('runtime-event', event), occurrence_id: row.occurrence_id, evidence_digest: completed.evidence_digest }; }
  }
}
export function markDeadlineExpired(row: Row, event: Row, clock: Row, state: Row): void {
  if (row.status === 'EXPIRED') return;
  row.status = 'EXPIRED';
  if (row.creation_digest !== undefined) {
    if (event.kind === 'DISPATCH_OBSERVED' && row.trigger?.kind === 'FIRST_DISPATCH' && row.trigger.event_digest === digest('runtime-event', event)) row.expiry_basis = { kind: 'DISPATCH', event_digest: digest('runtime-event', event), clock: clone(clock) };
    else {
      const receipt = state.receipts.find((receipt: Row) => receipt.event_kind === 'CLOCK' && receipt.details.some((detail: Row) => detail.kind === 'CLOCK' && detail.source === clock.source && detail.revision === clock.revision));
      row.expiry_basis = event.kind === 'CLOCK' && same(event.clock, clock) ? { kind: 'CLOCK', event_digest: digest('runtime-event', event), clock: clone(clock) } : receipt ? { kind: 'CLOCK', event_digest: receipt.event_digest, clock: clone(clock) } : { kind: 'DEPLOYMENT', deployment_authorization_digest: state.deployment_authorization_digest, clock: clone(clock) };
    }
  }
  else row.expiry_event_digest = digest('runtime-event', event);
}
export function deadlineExpiryClock(state: Row, row: Row): Row | undefined {
  if (row.expiry_basis) return row.expiry_basis.clock;
  const receipt = state.receipts.find((receipt: Row) => receipt.event_digest === row.expiry_event_digest), detail = receipt?.details.find((detail: Row) => detail.kind === 'CLOCK');
  return detail && state.clocks.find((clock: Row) => clock.source === detail.source && clock.revision === detail.revision);
}
export function pendingTimingDuties(state: Row): boolean { return state.event_duties?.some((row: Row) => row.status === 'PENDING' || row.status === 'EXPIRED' && (row.occurrence_id === null || !state.completed.some((completed: Row) => completed.occurrence.occurrence_id === row.occurrence_id && completed.disposition === 'EXPIRED'))) ?? false; }

export function rewindTiming(state: Row, sequence: bigint, receipts: Row[]): void {
  const before = (digest: string): boolean => BigInt(receipts.find((receipt: Row) => receipt.event_digest === digest)?.sequence ?? sequence) < sequence;
  const ids = new Set([...state.active, ...state.completed].map((row: Row) => row.occurrence.occurrence_id));
  for (const row of state.event_duties ?? []) {
    if (!ids.has(row.occurrence_id)) { row.occurrence_id = null; row.binding_event_digest = null; }
    if (row.status === 'DISCHARGED' && !before(row.discharge_basis.event_digest)) { row.status = 'PENDING'; delete row.discharge_basis; }
    if (row.status === 'EXPIRED' && row.expiry_basis.kind !== 'DEPLOYMENT' && !before(row.expiry_basis.event_digest)) { row.status = 'PENDING'; delete row.expiry_basis; }
  }
  if (state.deferred_deadlines) state.deferred_deadlines = state.deferred_deadlines.filter((row: Row) => ids.has(row.occurrence_id)).map((row: Row) => {
    if (row.status === 'DISCHARGED' && !before(row.discharge_basis.event_digest)) { row.status = row.trigger ? 'PENDING' : 'WAITING'; delete row.discharge_basis; }
    if (row.status === 'EXPIRED' && !before(row.expiry_basis.event_digest)) { row.status = 'PENDING'; delete row.expiry_basis; }
    if (row.trigger && BigInt(row.trigger.sequence) >= sequence) { row.status = 'WAITING'; delete row.trigger; delete row.due; delete row.expiry_basis; delete row.discharge_basis; delete row.reason; }
    return row;
  });
  sortTimingRows(state);
}

function completionReceipt(state: Row, completed: Row): Row | undefined {
  const receipt = (event: string): Row | undefined => state.receipts.find((receipt: Row) => receipt.event_digest === event);
  const recovery = state.recovery_records?.find((record: Row) => record.after_projection.completed.some((row: Row) => row.occurrence.occurrence_id === completed.occurrence.occurrence_id && row.evidence_digest === completed.evidence_digest) && !record.before_projection.completed.some((row: Row) => row.occurrence.occurrence_id === completed.occurrence.occurrence_id));
  if (recovery) return receipt(digest('runtime-event', recovery.event));
  if (completed.disposition !== 'EXPIRED') {
    const outcome = state.outcomes.find((outcome: Row) => digest('native-evidence', outcome.native_evidence) === completed.evidence_digest);
    return outcome && receipt(outcome.event_digest);
  }
  const deadline = allDeadlineRows(state).find((row: Row) => row.occurrence_id === completed.occurrence.occurrence_id && row.status === 'EXPIRED');
  if (!deadline) return undefined;
  return [receipt(deadline.binding_event_digest), receipt(deadline.expiry_basis?.event_digest ?? deadline.expiry_event_digest)].filter((row: Row | undefined): row is Row => row !== undefined).sort((a, b) => BigInt(a.sequence) < BigInt(b.sequence) ? -1 : 1).at(-1);
}

function activationDigest(state: Row, occurrence: Row): string | undefined {
  if (!occurrence.predecessor_occurrence_ids.length) return digest('deployment-activation', { deployment_authorization_digest: state.deployment_authorization_digest, instance_id: state.instance_id, occurrence_id: occurrence.occurrence_id });
  const predecessors = occurrence.predecessor_occurrence_ids.map((id: string) => state.completed.find((row: Row) => row.occurrence.occurrence_id === id));
  if (predecessors.some((row: Row | undefined) => row === undefined)) return undefined;
  const receipts = predecessors.map((row: Row) => completionReceipt(state, row));
  if (receipts.some((row: Row | undefined) => row === undefined)) return undefined;
  return receipts.sort((a: Row, b: Row) => BigInt(a.sequence) < BigInt(b.sequence) ? -1 : 1).at(-1)?.event_digest;
}

export function validateTimingState(state: Row, definition: Row, checkpoint: (sequence: bigint) => Row): void {
  const eventDeclarations = definition.deadlines.filter(eventDuty), deferredDeclarations = definition.deadlines.filter(deferredDeadline);
  if (definition.event_anchors === undefined ? state.initial_event_anchors !== undefined : !Array.isArray(state.initial_event_anchors)) fail('STATE_INVALID');
  if (eventDeclarations.length ? !Array.isArray(state.event_duties) : state.event_duties !== undefined) fail('STATE_INVALID');
  if (deferredDeclarations.length ? !Array.isArray(state.deferred_deadlines) : state.deferred_deadlines !== undefined) fail('STATE_INVALID');
  admitInitialAnchors(definition, state.initial_event_anchors, state.deployment_authorization, state.deployment_authorization_clock);
  if (allDeadlineRows(state).length > 4096) fail('STATE_INVALID');
  const occurrences = [...state.active, ...state.completed], receipt = (digest: string): Row | undefined => state.receipts.find((receipt: Row) => receipt.event_digest === digest);
  const clockReceipt = (clock: Row): Row | undefined => state.receipts.find((receipt: Row) => receipt.event_kind === 'CLOCK' && receipt.details.some((detail: Row) => detail.kind === 'CLOCK' && detail.source === clock.source && detail.revision === clock.revision));
  if (timingDefinition(definition)) {
    const initial = state.clocks.filter((clock: Row) => !clockReceipt(clock)), sources = [...new Set<string>(definition.deadlines.filter((row: Row) => eventDuty(row) || row.step_id === definition.root && ordinaryDeadline(row)).map((row: Row) => row.clock_source))].sort(byteCompare);
    if (!same(initial.map((clock: Row) => clock.source), sources) || definition.deadlines.some((row: Row) => row.step_id === definition.root && ordinaryDeadline(row) && initial.find((clock: Row) => clock.source === row.clock_source)?.status !== 'AVAILABLE')) fail('STATE_INVALID');
  }
  const common = (row: Row): Row => Object.fromEntries(Object.entries(row).filter(([name]) => !['status', 'occurrence_id', 'binding_event_digest', 'trigger', 'due', 'expiry_basis', 'discharge_basis', 'reason'].includes(name)));
  const expiry = (row: Row): void => {
    const basis = row.expiry_basis, clock = basis.clock;
    if (clock.status !== 'AVAILABLE' || clock.source !== row.source || !state.clocks.some((retained: Row) => same(retained, clock)) || !dueAt(row, clock)) fail('STATE_INVALID');
    const historicalDispatch = row.trigger?.kind === 'FIRST_DISPATCH' && dueAt(row, row.trigger.clock);
    const proven = state.clocks.filter((clock: Row) => clock.source === row.source && clock.status === 'AVAILABLE' && dueAt(row, clock) && (row.target_step_id !== undefined || BigInt(clockReceipt(clock)?.sequence ?? '0') >= BigInt(row.trigger.sequence))).sort((a: Row, b: Row) => BigInt(clockReceipt(a)?.sequence ?? '0') < BigInt(clockReceipt(b)?.sequence ?? '0') ? -1 : 1)[0];
    if (historicalDispatch ? basis.kind !== 'DISPATCH' || basis.event_digest !== row.trigger.event_digest || !same(clock, row.trigger.clock) : !proven || !same(clock, proven)) fail('STATE_INVALID');
    if (basis.kind === 'DEPLOYMENT') {
      if (row.target_step_id === undefined || basis.deployment_authorization_digest !== state.deployment_authorization_digest || state.receipts.some((receipt: Row) => receipt.event_kind === 'CLOCK' && receipt.details.some((detail: Row) => detail.kind === 'CLOCK' && detail.source === clock.source && detail.revision === clock.revision))) fail('STATE_INVALID');
    } else {
      const event = receipt(basis.event_digest);
      if (!event || event.event_kind !== (basis.kind === 'DISPATCH' ? 'DISPATCH_OBSERVED' : basis.kind) || basis.kind === 'CLOCK' && !event.details.some((detail: Row) => detail.kind === 'CLOCK' && detail.source === clock.source && detail.revision === clock.revision) || basis.kind === 'DISPATCH' && (row.target_step_id !== undefined || row.trigger.kind !== 'FIRST_DISPATCH' || row.trigger.event_digest !== basis.event_digest || !same(row.trigger.clock, clock))) fail('STATE_INVALID');
      if (!event.details.some((detail: Row) => detail.kind === 'DEADLINE' && detail.deadline_ids.includes(row.deadline_id))) fail('STATE_INVALID');
    }
    const completed = state.completed.find((completed: Row) => completed.occurrence.occurrence_id === row.occurrence_id);
    if (completed && (completed.disposition !== 'EXPIRED' || completed.evidence_digest !== clock.evidence_digest || completed.occurred_at !== clock.observed_time)) fail('STATE_INVALID');
    const active = state.active.find((active: Row) => active.occurrence.occurrence_id === row.occurrence_id);
    if (active && active.status !== 'BLOCKED_DISPUTE') fail('STATE_INVALID');
  };
  const discharge = (row: Row): void => {
    const basis = row.discharge_basis, event = receipt(basis.event_digest), completed = state.completed.find((completed: Row) => completed.occurrence.occurrence_id === row.occurrence_id);
    if (!event || basis.occurrence_id !== row.occurrence_id || !completed || completed.disposition === 'EXPIRED' || basis.evidence_digest !== completed.evidence_digest || !['EFFECT_OBSERVED', 'DISPOSE', 'APPLY_DISPOSITION'].includes(event.event_kind)) fail('STATE_INVALID');
    if (completionReceipt(state, completed)?.event_digest !== basis.event_digest) fail('STATE_INVALID');
    const before = checkpoint(BigInt(event.sequence));
    if (before.completed.some((completed: Row) => completed.occurrence.occurrence_id === row.occurrence_id)) fail('STATE_INVALID');
    if (row.due !== undefined && state.clocks.some((clock: Row) => clock.source === row.source && clock.status === 'AVAILABLE' && dueAt(row, clock) && BigInt(clockReceipt(clock)?.sequence ?? '0') < BigInt(event.sequence) && (row.target_step_id !== undefined || BigInt(clockReceipt(clock)?.sequence ?? '0') >= BigInt(row.trigger.sequence)))) fail('STATE_INVALID');
  };
  if (!same((state.event_duties ?? []).map((row: Row) => row.deadline_id), eventDeclarations.map((row: Row) => row.id))) fail('STATE_INVALID');
  for (const row of state.event_duties ?? []) {
    const declaration = eventDeclarations.find((declaration: Row) => declaration.id === row.deadline_id), expected = dutyRow(state, definition, declaration);
    if (!same(common(row), common(expected)) || row.due !== expected.due) fail('STATE_INVALID');
    const matching = occurrences.filter((occurrence: Row) => occurrence.occurrence.step_id === declaration.step_id);
    if (matching.length > 1 || (matching.length === 0 ? row.occurrence_id !== null || row.binding_event_digest !== null : row.occurrence_id !== matching[0].occurrence.occurrence_id || row.binding_event_digest !== activationDigest(state, matching[0].occurrence) || matching[0].activation_event_digest !== undefined && matching[0].activation_event_digest !== row.binding_event_digest)) fail('STATE_INVALID');
    if (row.occurrence_id !== null) {
      const event = receipt(row.binding_event_digest)!;
      if (checkpoint(BigInt(event.sequence)).active.some((active: Row) => active.occurrence.occurrence_id === row.occurrence_id)) fail('STATE_INVALID');
    }
    if (row.status === 'EXPIRED') expiry(row);
    else if (row.status === 'DISCHARGED') discharge(row);
    else if (row.status !== 'PENDING' || state.completed.some((completed: Row) => completed.occurrence.occurrence_id === row.occurrence_id)) fail('STATE_INVALID');
    if (row.status === 'PENDING' && state.clocks.some((clock: Row) => clock.source === row.source && clock.status === 'AVAILABLE' && dueAt(row, clock))) fail('STATE_INVALID');
  }
  const expectedDeferred = occurrences.flatMap((occurrence: Row) => deferredDeclarations.filter((declaration: Row) => declaration.step_id === occurrence.occurrence.step_id).map((declaration: Row) => canonical([declaration.id, occurrence.occurrence.occurrence_id]))).sort(byteCompare);
  if (!same((state.deferred_deadlines ?? []).map((row: Row) => canonical([row.deadline_id, row.occurrence_id])).sort(byteCompare), expectedDeferred)) fail('STATE_INVALID');
  const sorted = clone(state); sortTimingRows(sorted);
  if (state.deferred_deadlines !== undefined && !same(sorted.deferred_deadlines, state.deferred_deadlines)) fail('STATE_INVALID');
  for (const row of state.deferred_deadlines ?? []) {
    const declaration = deferredDeclarations.find((declaration: Row) => declaration.id === row.deadline_id), retained = occurrences.find((occurrence: Row) => occurrence.occurrence.occurrence_id === row.occurrence_id)!;
    if (!same(common(row), common(deferredRow(state, declaration, retained.occurrence, row.activation_event_digest)))) fail('STATE_INVALID');
    if (row.activation_event_digest !== activationDigest(state, retained.occurrence)) fail('STATE_INVALID');
    if (!retained.occurrence.predecessor_occurrence_ids.length) {
      if (row.activation_event_digest !== digest('deployment-activation', { deployment_authorization_digest: state.deployment_authorization_digest, instance_id: state.instance_id, occurrence_id: row.occurrence_id })) fail('STATE_INVALID');
    } else if (!receipt(row.activation_event_digest) || retained.activation_event_digest !== undefined && retained.activation_event_digest !== row.activation_event_digest) fail('STATE_INVALID');
    const candidates: { trigger: Row; start: string }[] = [];
    if (declaration.due.kind === 'ELAPSED_FROM_FIRST_WITHHELD') for (const evaluation of state.proposal_authority_evaluations ?? []) {
      const event = evaluation.event, decision = receipt(digest('runtime-event', event));
      if (!decision || event.occurrence.occurrence_id !== row.occurrence_id || event.authority_input.clock.status !== 'AVAILABLE' || event.authority_input.clock.source !== row.source || !matchingCheck(declaration, evaluation.authority_result)) continue;
      const clock = checkpoint(BigInt(decision.sequence)).clocks.filter((clock: Row) => clock.source === row.source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1).at(-1);
      if (!clock || clock.status !== 'AVAILABLE' || clock.revision !== event.clock_revision || clock.observed_time !== event.authority_input.clock.instant) fail('STATE_INVALID');
      candidates.push({ trigger: { kind: 'FIRST_WITHHELD', evaluation_digest: evaluation.evaluation_digest, sequence: decision.sequence, clock: clone(clock) }, start: clock.observed_time });
    }
    else for (const dispatch of state.dispatches) {
      const permit = state.permits.find((permit: Row) => permit.permit_id === dispatch.permit_digest), decision = receipt(dispatch.event_digest);
      if (!permit || !decision || permit.occurrence.occurrence_id !== row.occurrence_id || permit.clock_source !== row.source || !(['SENT', 'UNKNOWN'].includes(dispatch.attempt.status) || dispatch.acknowledgement.status === 'ACCEPTED')) continue;
      const clock = checkpoint(BigInt(decision.sequence)).clocks.filter((clock: Row) => clock.source === row.source && clock.status === 'AVAILABLE').sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1).at(-1);
      if (!clock || clock.revision !== dispatch.clock_revision) fail('STATE_INVALID');
      candidates.push({ trigger: { kind: 'FIRST_DISPATCH', event_digest: dispatch.event_digest, sequence: decision.sequence, dispatch_digest: dispatch.dispatch_digest, dispatch_attempt_digest: dispatch.dispatch_attempt_digest, clock: clone(clock) }, start: dispatch.attempt.attempted_at });
    }
    candidates.sort((a, b) => BigInt(a.trigger.sequence) < BigInt(b.trigger.sequence) ? -1 : 1);
    const completion = row.discharge_basis && receipt(row.discharge_basis.event_digest);
    const first = candidates.find(candidate => !completion || BigInt(candidate.trigger.sequence) < BigInt(completion.sequence));
    if (first ? !row.trigger || !same(row.trigger, first.trigger) : row.trigger !== undefined) fail('STATE_INVALID');
    if (first) {
      try { const due = instantText(instant(first.start) + elapsed(declaration.due)); if (row.status === 'TRIGGER_OVERFLOW' || row.due !== due) fail('STATE_INVALID'); }
      catch (error) {
        if (!(error instanceof AdmissionError) || error.code !== 'TIME_RANGE') throw error;
        const decision = state.receipts.find((receipt: Row) => receipt.sequence === first.trigger.sequence);
        if (row.status !== 'TRIGGER_OVERFLOW' || row.reason !== 'DEADLINE_TIME_OVERFLOW' || !decision || decision.disposition !== 'STOPPED' || !decision.reason_codes.includes('DEADLINE_TIME_OVERFLOW') || !decision.details.some((detail: Row) => detail.kind === 'DEADLINE' && detail.deadline_ids.includes(row.deadline_id) && detail.reasons.includes('DEADLINE_TIME_OVERFLOW'))) fail('STATE_INVALID');
      }
    }
    if (row.status === 'EXPIRED') expiry(row);
    else if (row.status === 'DISCHARGED') discharge(row);
    else if (row.status === 'WAITING' ? first !== undefined : row.status === 'PENDING' ? first === undefined : row.status !== 'TRIGGER_OVERFLOW') fail('STATE_INVALID');
    if (row.status === 'PENDING' && state.clocks.some((clock: Row) => clock.source === row.source && clock.status === 'AVAILABLE' && BigInt(clockReceipt(clock)?.sequence ?? '0') >= BigInt(row.trigger.sequence) && dueAt(row, clock)) || row.status === 'PENDING' && row.trigger.kind === 'FIRST_DISPATCH' && dueAt(row, row.trigger.clock)) fail('STATE_INVALID');
    if (state.completed.some((completed: Row) => completed.occurrence.occurrence_id === row.occurrence_id) && !['DISCHARGED', 'EXPIRED', 'TRIGGER_OVERFLOW'].includes(row.status)) fail('STATE_INVALID');
  }
}
