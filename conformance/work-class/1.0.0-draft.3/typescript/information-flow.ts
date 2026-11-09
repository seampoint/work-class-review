import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { evaluateAuthority } from './authority.ts';
import { decisionAct, decisionRequirements } from './human-decisions.ts';
import { requireShape, VERSION } from './schema.ts';
import { instant } from './time.ts';
import { ordered, same, setOrder, typed } from './values.ts';
import type { RecordValue as Row, Types } from './values.ts';

type Check = (condition: unknown, code: string) => void;
const clone = <T>(value: T): T => structuredClone(value);
const check: Check = (value, code) => { if (!value) throw new AdmissionError(code); };
const sorted = (values: string[]): string[] => [...new Set(values)].sort(byteCompare);
const recordFor = (input: Row, id: string): Row | undefined => input.envelope.source_observation_requirements?.find((row: Row) => row.id === id);
export const flowRequirements = (input: Row): Row[] => (input.envelope.flow_requirements ?? []).filter((row: Row) => row.step === input.proposal.step);
const basisFor = (input: Row, id: string): Row | undefined => input.flow_bases?.find((row: Row) => row.requirement_id === id);
let verifiedPrefixes: Map<string, { configuration: Row; state: Row; pin: string }> | undefined;

export function withFlowEvaluation<T>(action: () => T): T {
  if (verifiedPrefixes) return action();
  verifiedPrefixes = new Map();
  try { return action(); } finally { verifiedPrefixes = undefined; }
}
function remember(configuration: Row, state: Row, pin: string): void {
  verifiedPrefixes?.set(digest('flow-state', state), { configuration: clone(configuration), state: clone(state), pin });
}
function second(text: string): bigint {
  try { check(!text.includes('.'), 'CLOCK_INVALID'); return instant(text); }
  catch { throw new AdmissionError('CLOCK_INVALID'); }
}
export function flowControlSubject(configuration: Row, event: Row): string {
  const body = clone(event); delete body.payload.access_authority; delete body.payload.transfer_authority;
  return digest('flow-control-subject', { configuration_digest: digest('flow-configuration', configuration), event: body });
}
export function flowResponseSubject(input: Row): string {
  return digest('flow-response-subject', { configuration_digest: digest('flow-configuration', input.configuration), state_digest: input.state_digest, event_id: input.event.id, event_digest: digest('flow-event', { event: input.event, host_evidence: input.host_evidence }), protected_channel: input.configuration.protected_channel });
}
export function admitFlowConfiguration(configuration: Row, pin: string): void {
  requireShape('information-flow.schema.json', 'configuration', configuration);
  check(configuration.specification_pin === pin, 'VERSION_UNSUPPORTED');
  check(ordered(configuration.restrictions.map((row: Row) => row.id)), 'INPUT_INVALID');
  for (const row of configuration.restrictions) check(row.releasable ? row.release_role !== null : row.release_role === null, 'DEFINITION_INVALID');
}
function noBudgets(input: Row): void {
  check(Buffer.byteLength(canonical(input)) <= 1048576, 'LIMIT_EXCEEDED');
  check(!(input.work_class.shared_budgets ?? []).length && input.work_class.steps.every((row: Row) => !(row.shared_budgets ?? []).length) && input.envelope.limits.shared_budgets.length === 0, 'UNSUPPORTED_RELATION');
}
function ordinary(input: Row, pin: string): Row {
  noBudgets(input);
  const result = evaluateAuthority(input, pin);
  check(result.status === 'READY_FOR_RESERVATION', result.code === 'AUTHORITY_NOT_ESTABLISHED' ? 'ACCESS_NOT_ESTABLISHED' : result.code);
  check(result.required_budgets.length === 0, 'UNSUPPORTED_RELATION');
  return result;
}
function access(configuration: Row, authority: Row, subject: string, pin: string, operation: string, actor?: string, clock?: Row, role?: string): Row {
  check(!(authority.envelope.flow_requirements ?? []).length && !(authority.flow_bases ?? []).length, 'UNSUPPORTED_RELATION');
  noBudgets(authority);
  const proposal = authority.proposal, fields = proposal.fields, type = authority.work_class.types.find((row: Row) => row.id === fields[0]?.value.type_ref);
  check(fields.length === 1 && fields[0].name === 'admission_subject' && ['STRING', 'IDENTITY'].includes(type?.kind) && fields[0].value.value === subject, 'BINDING_MISMATCH');
  check(authority.envelope.principal === configuration.principal && proposal.executor.principal === configuration.principal && proposal.interface === configuration.control_interface && proposal.operation === operation && (actor === undefined || proposal.executor.actor === actor) && (role === undefined || proposal.executor.role === role), 'BINDING_MISMATCH');
  check(authority.clock.status === 'AVAILABLE' && authority.clock.source === configuration.clock_source && (clock === undefined || same(authority.clock, clock)), 'CLOCK_INVALID');
  return ordinary(authority, pin);
}
export function authorizeFlowResponse(input: Row, pin: string): Row {
  return access(input.configuration, input.response_authority, flowResponseSubject(input), pin, input.configuration.response_operation, undefined, undefined, input.configuration.response_role);
}
function hostEvidence(configuration: Row, event: Row, host: Row): void {
  check(host.configuration_digest === digest('flow-configuration', configuration) && host.event_subject_digest === flowControlSubject(configuration, event), 'DEPENDENCY_MISMATCH');
  check(setOrder(host.attestations), 'INPUT_INVALID');
  const subjects: Record<string, [string, string]> = {
    CREATE_CONTEXT: ['INITIAL_INVENTORY', digest('flow-initial-inventory', event.payload)],
    READ: ['SOURCE_CLASSIFICATION', event.kind === 'READ' ? digest('flow-source', event.payload.source) : ''],
    MATERIALIZE: ['MATERIALIZED_CONTENT', event.kind === 'MATERIALIZE' ? digest('flow-materialized-content', { types: event.payload.types, fields: event.payload.fields }) : ''],
  };
  const expected = subjects[event.kind];
  check(host.attestations.every((row: Row) => expected && row.kind === expected[0] && row.subject_digest === expected[1] && row.provider === configuration.provider && row.source === configuration.source && row.channel === configuration.protected_channel), 'DEPENDENCY_MISMATCH');
  check(!expected || host.attestations.length === 1, 'EVIDENCE_UNAVAILABLE');
}
function native(types: Row[], fields: Row[]): void {
  check(ordered(types.map(row => row.id)) && ordered(fields.map(row => row.name)), 'INPUT_INVALID');
  const table: Types = new Map(types.map(row => [row.id, row as any]));
  for (const type of types) check((type.unit === null || type.kind === 'DECIMAL') && (!type.nonnegative || ['INTEGER', 'DECIMAL'].includes(type.kind)), 'TYPE_INVALID');
  for (const field of fields) {
    typed(field.value, table);
    if (['INTEGER', 'DECIMAL'].includes(table.get(field.value.type_ref)!.kind)) check(field.value.value.replace(/[-.]/g, '').length <= 128, 'LIMIT_EXCEEDED');
  }
}
function source(configuration: Row, state: Row | null, descriptor: Row, scope: string): void {
  check(descriptor.scope === scope, 'DEPENDENCY_MISMATCH');
  check(ordered(descriptor.restrictions), 'INPUT_INVALID');
  for (const id of descriptor.restrictions) {
    const restriction = configuration.restrictions.find((row: Row) => row.id === id);
    check(restriction, 'REFERENCE_INVALID'); check(restriction.scope === scope, 'DEPENDENCY_MISMATCH');
  }
  const coordinates = (row: Row): unknown[] => ['provider', 'source', 'record_type', 'record_id', 'revision', 'scope'].map(key => row[key]);
  for (const context of state?.core.contexts ?? []) for (const previous of context.origins) if (same(coordinates(descriptor), coordinates(previous))) check(same(descriptor, previous), 'DEPENDENCY_MISMATCH');
}
function unionOrigins(...rows: Row[][]): Row[] {
  return [...new Map(rows.flat().map(row => [digest('flow-source', row), clone(row)])).entries()].sort(([a], [b]) => byteCompare(a, b)).map(([, row]) => row);
}
function transition(configuration: Row, state: Row | null, event: Row, host: Row, pin: string): Row {
  const configurationDigest = digest('flow-configuration', configuration), before = state === null ? null : digest('flow-state', state);
  check(state !== null || event.kind === 'CREATE_CONTEXT', 'STATE_INVALID');
  check(event.expected_revision === (state?.core.revision ?? '0') && event.expected_state_digest === before, 'REVISION_CONFLICT');
  check(event.clock.status === 'AVAILABLE' && event.clock.source === configuration.clock_source, 'CLOCK_INVALID');
  const now = second(event.clock.instant); if (state) check(now >= second(state.core.last_clock), 'CLOCK_INVALID');
  hostEvidence(configuration, event, host); check((state?.records.length ?? 0) < 128, 'LIMIT_EXCEEDED');
  const core: Row = clone(state?.core ?? { configuration_digest: configurationDigest, revision: '0', last_clock: event.clock.instant, contexts: [], artifacts: [], claims: [], consumed_release_acts: [] });
  const payload = event.payload, results: Row[] = [];
  const find = (id: string): Row => { const context = core.contexts.find((row: Row) => row.id === id); check(context, 'DEPENDENCY_MISMATCH'); return context; };
  const addClaim = (id: string, intent: string, context: Row, recipient: string, channel: string, purpose: string, subject: string, released: string | null): void => {
    check(!core.claims.some((row: Row) => row.id === id || row.intent_id === intent), 'DEPENDENCY_MISMATCH');
    check(released === null || !core.consumed_release_acts.includes(released), 'DEPENDENCY_MISMATCH');
    core.claims.push({ id, intent_id: intent, status: 'POSSIBLE_EXPOSURE', kind: event.kind, context_id: context.id, recipient, channel, purpose, subject_digest: subject, release_act_digest: released });
    if (released !== null) core.consumed_release_acts.push(released);
  };
  let decision: string;
  if (event.kind === 'CREATE_CONTEXT') {
    check(!core.contexts.some((row: Row) => row.id === payload.context_id), 'DEFINITION_CONFLICT');
    check(ordered(payload.ceiling), 'INPUT_INVALID');
    for (const id of payload.ceiling) { const row = configuration.restrictions.find((row: Row) => row.id === id); check(row, 'REFERENCE_INVALID'); check(row.scope === payload.scope, 'DEPENDENCY_MISMATCH'); }
    core.contexts.push({ id: payload.context_id, actor: payload.actor, scope: payload.scope, purpose: payload.purpose, revision: '1', ceiling: clone(payload.ceiling), restrictions: [], origins: [] }); decision = 'CONTEXT_CREATED';
  } else if (event.kind === 'READ' || event.kind === 'IMPORT') {
    const receiver = find(event.kind === 'READ' ? payload.context_id : payload.receiver_context_id), subject = flowControlSubject(configuration, event);
    check(!core.claims.some((row: Row) => row.id === payload.claim_id || row.intent_id === payload.intent_id), 'DEPENDENCY_MISMATCH');
    let origins: Row[], restrictions: string[];
    if (event.kind === 'READ') { source(configuration, state, payload.source, receiver.scope); origins = [payload.source]; restrictions = payload.source.restrictions; }
    else {
      const sender = find(payload.sender_context_id), artifact = core.artifacts.find((row: Row) => row.id === payload.artifact_id);
      check(artifact && artifact.context_id === sender.id && sender.scope === receiver.scope, 'DEPENDENCY_MISMATCH');
      origins = unionOrigins(sender.origins, artifact.origins); restrictions = sorted([...sender.restrictions, ...artifact.restrictions]);
    }
    const accumulated = sorted([...receiver.restrictions, ...restrictions]);
    check(accumulated.every(id => receiver.ceiling.includes(id)), 'ACCESS_NOT_ESTABLISHED');
    results.push(access(configuration, payload.access_authority, subject, pin, configuration.access_operation, receiver.actor, event.clock));
    if (event.kind === 'IMPORT') results.push(access(configuration, payload.transfer_authority, subject, pin, configuration.transfer_operation, find(payload.sender_context_id).actor, event.clock));
    receiver.restrictions = accumulated; receiver.origins = unionOrigins(receiver.origins, origins); receiver.revision = (BigInt(receiver.revision) + 1n).toString();
    addClaim(payload.claim_id, payload.intent_id, receiver, receiver.id, configuration.control_interface, receiver.purpose, subject, null);
    decision = event.kind === 'READ' ? 'READ_RECORDED' : 'IMPORT_RECORDED';
  } else if (event.kind === 'MATERIALIZE') {
    const context = find(payload.context_id); check(context.revision !== '1', 'ACCESS_NOT_ESTABLISHED');
    check(!core.artifacts.some((row: Row) => row.id === payload.artifact_id), 'DEPENDENCY_MISMATCH'); native(payload.types, payload.fields);
    core.artifacts.push({ id: payload.artifact_id, context_id: context.id, context_revision: context.revision, context_digest: digest('flow-context', context), types: clone(payload.types), fields: clone(payload.fields), restrictions: clone(context.restrictions), origins: clone(context.origins) }); decision = 'ARTIFACT_RECORDED';
  } else {
    check(state, 'STATE_INVALID');
    const authority = clone(payload.authority_projection), basis = authority.flow_bases[0];
    check(same(basis.configuration, configuration) && basis.state_digest === before, 'DEPENDENCY_MISMATCH');
    basis.state = clone(state); check(same(authority.clock, event.clock), 'BINDING_MISMATCH');
    remember(configuration, state!, pin); results.push(ordinary(authority, pin));
    const requirement = flowRequirements(authority).find(row => row.id === payload.requirement_id)!;
    check(requirement && requirement.id === basis.requirement_id, 'DEPENDENCY_MISMATCH');
    const context = find(requirement.context_id), recipient = authority.proposal.fields.find((row: Row) => row.name === requirement.recipient_field).value.value;
    const act = requirement.release_decision_requirement_id === null ? undefined : decisionAct(authority, requirement.release_decision_requirement_id);
    addClaim(requirement.claim_id, requirement.intent_id, context, recipient, requirement.channel, requirement.purpose, flowDisclosureSubject(authority, requirement, basis), act ? digest('authority-act', act) : null); decision = 'EXPOSURE_RECORDED';
  }
  check(core.contexts.length <= 16 && core.artifacts.length <= 64 && core.claims.length <= 128 && core.contexts.every((row: Row) => row.origins.length <= 64), 'LIMIT_EXCEEDED');
  for (const name of ['contexts', 'artifacts', 'claims']) core[name].sort((a: Row, b: Row) => byteCompare(a.id, b.id));
  core.consumed_release_acts.sort(byteCompare); core.revision = (BigInt(core.revision) + 1n).toString(); core.last_clock = event.clock.instant;
  const eventDigest = digest('flow-event', { event, host_evidence: host });
  const receipt = { schema: VERSION + '/flow-receipt', event_id: event.id, event_digest: eventDigest, state_before_digest: before, revision: core.revision, core_after_digest: digest('flow-core', core), decision, authority_result_digests: results.map(row => digest('authority-result', row)), authority_evidence_digests: results.map(row => row.evidence_digest), protected_channel: configuration.protected_channel };
  const next = { schema: VERSION + '/flow-state', specification_pin: pin, core, records: [...(state?.records ?? []), { event: clone(event), host_evidence: clone(host), event_digest: eventDigest, receipt, receipt_digest: digest('flow-receipt', receipt) }] };
  check(Buffer.byteLength(canonical(next)) <= 16777216, 'LIMIT_EXCEEDED');
  return { status: 'TRANSITION', receipt, receipt_digest: digest('flow-receipt', receipt), state: next, state_digest: digest('flow-state', next), replay: false };
}
export function admitFlowState(configuration: Row, state: Row, suppliedDigest: string, pin: string): void {
  requireShape('information-flow.schema.json', 'state', state);
  check(Buffer.byteLength(canonical(state)) <= 16777216, 'LIMIT_EXCEEDED');
  check(state.specification_pin === pin, 'VERSION_UNSUPPORTED'); check(digest('flow-state', state) === suppliedDigest, 'DIGEST_MISMATCH');
  check(state.core.configuration_digest === digest('flow-configuration', configuration), 'DEPENDENCY_MISMATCH');
  const memo = verifiedPrefixes?.get(suppliedDigest);
  if (memo && memo.pin === pin && same(memo.configuration, configuration) && same(memo.state, state)) return;
  try {
    let rebuilt: Row | null = null; const ids = new Set<string>();
    for (const record of state.records) {
      check(!ids.has(record.event.id), 'STATE_INVALID'); ids.add(record.event.id);
      const result = transition(configuration, rebuilt, record.event, record.host_evidence, pin);
      check(same(result.state.records.at(-1), record), 'STATE_INVALID'); rebuilt = result.state; remember(configuration, rebuilt!, pin);
    }
    check(same(rebuilt, state), 'STATE_INVALID');
  } catch (error) { if (error instanceof AdmissionError) throw new AdmissionError('STATE_INVALID'); throw error; }
  remember(configuration, state, pin);
}
export function admitFlowInput(input: unknown): Row {
  try {
    requireShape('information-flow.schema.json', 'input', input);
    check(Buffer.byteLength(canonical(input)) <= 16777216, 'LIMIT_EXCEEDED');
    return input as Row;
  } catch (error) {
    if (error instanceof AdmissionError && error.code === 'LIMIT_EXCEEDED') throw error;
    throw new AdmissionError('SCHEMA_INVALID');
  }
}
export function flowStep(input: unknown, pin: string): Row {
  return withFlowEvaluation(() => {
    let request: Row;
    try { request = admitFlowInput(input); }
    catch (error) { if (error instanceof AdmissionError) return { status: 'REFUSED', code: error.code, path: '' }; throw error; }
    try { authorizeFlowResponse(request, pin); }
    catch (error) { if (error instanceof AdmissionError) return { status: 'REFUSED', code: error.code, path: '' }; throw error; }
    try {
      check(request.specification_pin === pin, 'VERSION_UNSUPPORTED'); admitFlowConfiguration(request.configuration, pin);
      check((request.state === null) === (request.state_digest === null), 'STATE_INVALID');
      if (request.state) admitFlowState(request.configuration, request.state, request.state_digest, pin);
      const previous = request.state?.records.find((row: Row) => row.event.id === request.event.id);
      if (previous) { check(same(previous.event, request.event) && same(previous.host_evidence, request.host_evidence), 'REPLAY_CONFLICT'); return { status: 'TRANSITION', receipt: clone(previous.receipt), receipt_digest: previous.receipt_digest, state: clone(request.state), state_digest: request.state_digest, replay: true }; }
      return transition(request.configuration, request.state, request.event, request.host_evidence, pin);
    } catch (error) { if (error instanceof AdmissionError) return { status: 'REFUSED', code: error.code, path: '', state: request.state, state_digest: request.state_digest }; throw error; }
  });
}

export function flowLinkedDecision(input: Row, decision: Row): boolean {
  return (input.envelope.flow_requirements ?? []).some((row: Row) => row.step === decision.step && row.release_decision_requirement_id === decision.id);
}
export function flowDisclosureSubject(input: Row, requirement: Row, basis: Row): string {
  const context = basis.state.core.contexts.find((row: Row) => row.id === requirement.context_id), artifact = basis.state.core.artifacts.find((row: Row) => row.id === requirement.artifact_id), proposal = input.proposal;
  return digest('flow-disclosure-subject', { principal: input.envelope.principal, configuration_digest: digest('flow-configuration', basis.configuration), policy_digest: digest('flow-policy', requirement.policy), context_digest: digest('flow-context', context), artifact_digest: digest('flow-artifact', artifact), work_class_digest: proposal.work_class_digest, instance: proposal.instance, occurrence: proposal.occurrence, step: proposal.step, interface: proposal.interface, operation: proposal.operation, fields: proposal.fields, recipient: proposal.fields.find((row: Row) => row.name === requirement.recipient_field)?.value.value, channel: requirement.channel, purpose: requirement.purpose, intent_id: requirement.intent_id, claim_id: requirement.claim_id, released_restrictions: basis.released_restrictions });
}
export function flowValue(input: Row, selector: Row): Row | undefined {
  const requirement = flowRequirements(input).find(row => row.id === selector.requirement_id), basis = requirement && basisFor(input, requirement.id);
  if (!requirement || !basis || !basis.state.core.contexts.some((row: Row) => row.id === requirement.context_id) || !basis.state.core.artifacts.some((row: Row) => row.id === requirement.artifact_id)) return undefined;
  return { type_ref: selector.type_ref, value: flowDisclosureSubject(input, requirement, basis) };
}
export function admitFlowDeclarations(input: Row, types: Types, record: Check, typeCheck: Check): void {
  const requirements = input.envelope.flow_requirements ?? [];
  typeCheck(ordered(requirements.map((row: Row) => row.id)), 'INPUT_INVALID');
  for (const decision of decisionRequirements(input)) for (const binding of decision.context_bindings.filter((row: Row) => row.value.kind === 'FLOW_DISCLOSURE')) {
    const declaration = requirements.find((row: Row) => row.id === binding.value.requirement_id);
    record(declaration && declaration.step === decision.step && declaration.release_decision_requirement_id === decision.id, 'REFERENCE_INVALID');
    record(types.has(binding.value.type_ref), 'REFERENCE_INVALID'); if (types.has(binding.value.type_ref)) typeCheck(['STRING', 'IDENTITY'].includes(types.get(binding.value.type_ref)!.kind), 'TYPE_INVALID');
  }
  for (const requirement of requirements) {
    const step = input.work_class.steps.find((row: Row) => row.id === requirement.step), field = step?.fields.find((row: Row) => row.name === requirement.recipient_field), sources = requirement.sources, policy = requirement.policy;
    record(step && field && input.envelope.operations.some((row: Row) => row.step === requirement.step), 'REFERENCE_INVALID');
    if (field && types.has(field.type_ref)) typeCheck(['STRING', 'IDENTITY'].includes(types.get(field.type_ref)!.kind), 'TYPE_INVALID');
    typeCheck(setOrder(policy.entitlements) && setOrder(policy.release_rules) && ordered(sources.blockers), 'INPUT_INVALID');
    record(policy.configuration_digest === requirement.configuration_digest, 'DEPENDENCY_MISMATCH');
    const releasing = requirement.release_decision_requirement_id !== null, decision = decisionRequirements(input).find(row => row.id === requirement.release_decision_requirement_id);
    record(releasing === (sources.release_selection !== null) && releasing === (sources.release_effectiveness !== null), 'UNSUPPORTED_RELATION');
    if (releasing) {
      record(decision && decision.step === requirement.step, 'REFERENCE_INVALID');
      if (decision) {
        const bindings = decision.context_bindings.filter((row: Row) => row.value.kind === 'FLOW_DISCLOSURE');
        record(bindings.length === 1 && bindings[0].value.requirement_id === requirement.id, 'UNSUPPORTED_RELATION');
        const assessment = (input.envelope.assessment_requirements ?? []).find((row: Row) => row.step === requirement.step);
        record(!assessment || assessment.review_decision_requirement_id !== decision.id, 'UNSUPPORTED_RELATION');
        if (assessment) record(input.envelope.gate.decision_requirement === assessment.review_decision_requirement_id, 'UNSUPPORTED_RELATION');
      }
    }
    const roles = [sources.policy.requirement_id, sources.recipient.requirement_id, ...(releasing && sources.release_selection && sources.release_effectiveness ? [sources.release_selection.requirement_id, sources.release_effectiveness.requirement_id] : [])];
    record(step?.dispatch_gate?.kind === 'SOURCE_REQUIREMENTS', 'UNSUPPORTED_RELATION');
    for (const id of [...roles, ...sources.blockers]) { const source = recordFor(input, id); record(source, 'REFERENCE_INVALID'); if (source) record(source.step === requirement.step && (sources.blockers.includes(id) || source.expected_status === 'AVAILABLE'), 'UNSUPPORTED_RELATION'); }
    for (const source of (input.envelope.source_observation_requirements ?? []).filter((row: Row) => row.step === requirement.step)) record(step?.dispatch_gate?.kind === 'SOURCE_REQUIREMENTS' && step.dispatch_gate.requirements.includes(source.id) && source.at === 'CLOCK' && source.evaluation_point === 'PROPOSE_AND_DISPATCH' && source.freshness_seconds === '0', 'UNSUPPORTED_RELATION');
    if (step?.dispatch_gate?.kind === 'SOURCE_REQUIREMENTS') record(step.dispatch_gate.requirements.length + (input.envelope.holdings_requirements ?? []).filter((row: Row) => row.step === requirement.step).length + 1 <= 64, 'LIMIT_EXCEEDED');
    const inspect = (role: Row, names: string[], boolean: string[] = []): void => {
      const source = recordFor(input, role.requirement_id);
      for (const name of names) { const field = source?.fields.find((row: Row) => row.name === role[name]); record(field && types.has(field.type_ref), 'REFERENCE_INVALID'); if (field && types.has(field.type_ref)) typeCheck((boolean.includes(name) ? ['BOOLEAN'] : ['STRING', 'IDENTITY']).includes(types.get(field.type_ref)!.kind), 'TYPE_INVALID'); }
    };
    inspect(sources.policy, ['digest_field']); inspect(sources.recipient, ['recipient_field', 'channel_field', 'purpose_field', 'effective_field'], ['effective_field']);
    if (sources.release_selection) inspect(sources.release_selection, ['act_id_field', 'act_digest_field', 'subject_digest_field', 'claim_id_field']);
    if (sources.release_effectiveness) inspect(sources.release_effectiveness, ['act_id_field', 'effective_field'], ['effective_field']);
  }
}
export function admitFlowBases(input: Row, pin: string, record: Check, typeCheck: Check): void {
  const requirements = flowRequirements(input), bases = input.flow_bases ?? [];
  typeCheck(ordered(bases.map((row: Row) => row.requirement_id)), 'INPUT_INVALID');
  record(bases.every((row: Row) => requirements.some(required => required.id === row.requirement_id)), 'DEPENDENCY_MISMATCH');
  record(requirements.every(required => bases.some((row: Row) => row.requirement_id === required.id)), 'EVIDENCE_UNAVAILABLE');
  if (input.flow_bases !== undefined || input.envelope.flow_requirements !== undefined) record(Buffer.byteLength(canonical(input)) <= 1048576, 'LIMIT_EXCEEDED');
  for (const basis of bases) {
    typeCheck(ordered(basis.released_restrictions), 'INPUT_INVALID');
    try { second(basis.selection.at); admitFlowConfiguration(basis.configuration, pin); admitFlowState(basis.configuration, basis.state, basis.state_digest, pin); }
    catch (error) { if (!(error instanceof AdmissionError)) throw error; (error.code === 'INPUT_INVALID' || error.code === 'TYPE_INVALID' ? typeCheck : record)(false, error.code); }
    const required = requirements.find(row => row.id === basis.requirement_id); if (!required) continue;
    record(required.configuration_digest === digest('flow-configuration', basis.configuration), 'DEPENDENCY_MISMATCH');
    for (const row of [...required.policy.entitlements, ...required.policy.release_rules]) { const restriction = basis.configuration.restrictions.find((value: Row) => value.id === row.restriction_id); record(restriction, 'REFERENCE_INVALID'); if (restriction) record(restriction.scope === row.scope, 'DEPENDENCY_MISMATCH'); }
    for (const id of basis.released_restrictions) record(basis.configuration.restrictions.some((row: Row) => row.id === id), 'REFERENCE_INVALID');
    record(required.release_decision_requirement_id === null ? basis.released_restrictions.length === 0 : basis.released_restrictions.length > 0, 'UNSUPPORTED_RELATION');
    try { noBudgets(input); } catch (error) { if (!(error instanceof AdmissionError)) throw error; record(false, error.code); }
  }
}
export function bindFlowBases(input: Row, record: Check): void {
  for (const requirement of flowRequirements(input)) {
    const basis = basisFor(input, requirement.id); if (!basis) continue;
    const config = basis.configuration, selection = basis.selection, context = basis.state.core.contexts.find((row: Row) => row.id === requirement.context_id), artifact = basis.state.core.artifacts.find((row: Row) => row.id === requirement.artifact_id);
    record(config.principal === input.envelope.principal, 'BINDING_MISMATCH');
    record(selection.configuration_digest === requirement.configuration_digest && selection.state_digest === basis.state_digest && selection.revision === basis.state.core.revision && selection.provider === config.provider && selection.source === config.source && selection.channel === config.protected_channel, 'DEPENDENCY_MISMATCH');
    record(context && artifact && artifact.context_id === context.id && context.scope === input.envelope.scope.id && context.actor === input.proposal.executor.actor, 'BINDING_MISMATCH');
    if (artifact) record(same(artifact.types, input.work_class.types) && same(artifact.fields, input.proposal.fields), 'BINDING_MISMATCH');
    if (context && artifact) record(basis.released_restrictions.every((id: string) => [...context.restrictions, ...artifact.restrictions].includes(id)), 'BINDING_MISMATCH');
    const decision = decisionRequirements(input).find(row => row.id === requirement.release_decision_requirement_id);
    if (decision) record(decision.principal === config.principal, 'BINDING_MISMATCH');
  }
}
export function flowChecks(input: Row, queries: Row[], groups: Map<string, Map<string, Row>>): Row[] {
  const results: Row[] = [];
  for (const requirement of flowRequirements(input)) {
    const basis = basisFor(input, requirement.id); if (!basis) continue;
    const context = basis.state.core.contexts.find((row: Row) => row.id === requirement.context_id), artifact = basis.state.core.artifacts.find((row: Row) => row.id === requirement.artifact_id), recipient = input.proposal.fields.find((row: Row) => row.name === requirement.recipient_field).value.value, config = basis.configuration;
    const subject = digest('flow-query', { requirement_id: requirement.id, context_digest: digest('flow-context', context), artifact_digest: digest('flow-artifact', artifact), intent_id: requirement.intent_id, claim_id: requirement.claim_id, recipient, channel: requirement.channel, purpose: requirement.purpose, at: input.clock.instant }), reasons = new Set<string>();
    const fail = (condition: unknown, reason: string): void => { if (!condition) reasons.add(reason); };
    fail(basis.selection.status === 'AVAILABLE', 'FLOW_UNAVAILABLE');
    if (basis.selection.status === 'AVAILABLE') fail(basis.selection.at === input.clock.instant && second(input.clock.instant) >= second(basis.state.core.last_clock), 'FLOW_STALE');
    fail(basis.state.records.length < 128 && basis.state.core.claims.length < 128, 'FLOW_CAPACITY_EXHAUSTED');
    const usable = (id: string): Row | undefined => {
      const source = recordFor(input, id)!, query = queries.find((row: Row) => row.requirement_id === id); if (!query) return undefined;
      const rows = [...(groups.get(digest('authority-query', query))?.values() ?? [])]; if (rows.length !== 1) return undefined;
      const row = rows[0];
      if (!same(row.query, query) || row.status !== 'AVAILABLE' || source.expected_status !== 'AVAILABLE' || source.record_id !== null && row.provider_record_id !== source.record_id || instant(row.as_of) !== instant(query.at) || !same(row.relations, source.relations)) return undefined;
      if (row.fields.length !== source.fields.length || !source.fields.every((field: Row) => row.fields.some((value: Row) => value.name === field.name && value.value.type_ref === field.type_ref))) return undefined;
      const gate = input.work_class.steps.find((row: Row) => row.id === source.step).dispatch_gate, validity = gate.validity_requirements.find((row: Row) => row.requirement_id === id);
      if (validity) { const field = (name: string): string => row.fields.find((field: Row) => field.name === name).value.value; if (!(instant(field(validity.not_before_field)) <= instant(input.clock.instant) && instant(input.clock.instant) < instant(field(validity.not_after_field)))) return undefined; }
      return row;
    };
    const field = (row: Row, name: string): any => row.fields.find((row: Row) => row.name === name).value.value;
    const sources = requirement.sources, policy = usable(sources.policy.requirement_id), target = usable(sources.recipient.requirement_id), policyDigest = digest('flow-policy', requirement.policy);
    if (policy) fail(field(policy, sources.policy.digest_field) === policyDigest, 'FLOW_DEPENDENCY_CHANGED');
    if (target) { fail(field(target, sources.recipient.recipient_field) === recipient && field(target, sources.recipient.channel_field) === requirement.channel && field(target, sources.recipient.purpose_field) === requirement.purpose, 'FLOW_DEPENDENCY_CHANGED'); fail(field(target, sources.recipient.effective_field) === true, 'FLOW_RECIPIENT_NOT_ENTITLED'); }
    const union = sorted([...context.restrictions, ...artifact.restrictions]), released = basis.released_restrictions;
    const matches = (row: Row, id: string): boolean => row.restriction_id === id && row.scope === context.scope && row.recipient === recipient && row.channel === requirement.channel && row.purpose === requirement.purpose;
    for (const id of union.filter(id => !released.includes(id))) fail(requirement.policy.entitlements.some((row: Row) => matches(row, id)), 'FLOW_RECIPIENT_NOT_ENTITLED');
    const act = requirement.release_decision_requirement_id === null ? undefined : decisionAct(input, requirement.release_decision_requirement_id), actDigest = act ? digest('authority-act', act) : null;
    for (const id of released) { const restriction = config.restrictions.find((row: Row) => row.id === id); fail(restriction.releasable && restriction.release_role === act?.role && requirement.policy.release_rules.some((row: Row) => matches(row, id) && row.release_role === act?.role), 'FLOW_RELEASE_NOT_ESTABLISHED'); }
    if (sources.release_selection && act) { const row = usable(sources.release_selection.requirement_id), map = sources.release_selection; if (row) fail(field(row, map.act_id_field) === act.id && field(row, map.act_digest_field) === actDigest && field(row, map.subject_digest_field) === flowDisclosureSubject(input, requirement, basis) && field(row, map.claim_id_field) === requirement.claim_id, 'FLOW_RELEASE_NOT_ESTABLISHED'); }
    if (sources.release_effectiveness && act) { const row = usable(sources.release_effectiveness.requirement_id), map = sources.release_effectiveness; if (row) fail(field(row, map.act_id_field) === act.id && field(row, map.effective_field) === true, 'FLOW_RELEASE_NOT_ESTABLISHED'); }
    fail(!basis.state.core.claims.some((row: Row) => row.id === requirement.claim_id || row.intent_id === requirement.intent_id) && (actDigest === null || !basis.state.core.consumed_release_acts.includes(actDigest)), 'FLOW_CLAIM_CONSUMED');
    const row = { subject_digest: subject, requirement_ref: requirement.id }; results.push(...(reasons.size ? [...reasons].map(reason => ({ ...row, reason })) : [row]));
  }
  return results;
}
export function flowFence(input: Row): Row[] {
  return flowRequirements(input).map(requirement => {
    const basis = basisFor(input, requirement.id)!, context = basis.state.core.contexts.find((row: Row) => row.id === requirement.context_id), artifact = basis.state.core.artifacts.find((row: Row) => row.id === requirement.artifact_id), act = requirement.release_decision_requirement_id === null ? undefined : decisionAct(input, requirement.release_decision_requirement_id);
    return { requirement_id: requirement.id, configuration_digest: requirement.configuration_digest, state_digest: basis.state_digest, revision: basis.state.core.revision, context_digest: digest('flow-context', context), artifact_digest: digest('flow-artifact', artifact), policy_digest: digest('flow-policy', requirement.policy), intent_id: requirement.intent_id, claim_id: requirement.claim_id, release_act_digest: act ? digest('authority-act', act) : null };
  });
}
