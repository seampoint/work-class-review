import { AdmissionError, byteCompare, canonical, decodeArtifact, digest } from './canonical.ts';
import { boundSatisfied } from './math.ts';
import { instant } from './time.ts';
import { requireShape, VERSION } from './schema.ts';
import { ordered, predicate, predicateTypes, same, setOrder, typed } from './values.ts';
import type { RecordValue as Row, ScalarType, Types, TypedValue } from './values.ts';

class AuthorityRefusal extends Error {
  code: string;
  reasons: string[];
  failedChecks: Row[];
  constructor(code: string, reasons: string[] = [], failedChecks: Row[] = []) { super(code); this.code = code; this.reasons = reasons; this.failedChecks = failedChecks; }
}
class Phase {
  failures = new Set<string>();
  check(condition: unknown, code: string): void { if (!condition) this.failures.add(code); }
  attempt(action: () => void): void {
    try { action(); }
    catch (error) { if (error instanceof AdmissionError) this.failures.add(error.code); else throw error; }
  }
  finish(order: string[]): void {
    for (const code of order) if (this.failures.has(code)) throw new AuthorityRefusal(code);
    if (this.failures.size) throw new Error('Unclassified authority admission failure: ' + [...this.failures]);
  }
}
const P1 = ['SCHEMA_INVALID', 'ARTIFACT_ENCODING_INVALID', 'ARTIFACT_NONCANONICAL', 'TYPE_INVALID', 'INPUT_INVALID'];
const P2 = ['VERSION_UNSUPPORTED', 'DEPENDENCY_MISMATCH', 'EVIDENCE_UNAVAILABLE', 'UNSUPPORTED_RELATION', 'REFERENCE_INVALID', 'LIMIT_EXCEEDED'];
const P4 = ['ACT_CONFLICT', 'GATE_REQUIRED', 'EVIDENCE_UNAVAILABLE', 'ACT_NOT_AUTHORIZED', 'ACT_NOT_ACCEPTED'];
const table = (rows: Row[], key = 'id'): Map<string, Row> => new Map(rows.map(row => [row[key], row]));
const wholeSecond = (text: string): bigint => {
  if (text.includes('.')) throw new AdmissionError('INPUT_INVALID');
  try { return instant(text); } catch { throw new AdmissionError('INPUT_INVALID'); }
};
const within = (validity: Row, at: bigint): boolean => wholeSecond(validity.valid_from) <= at && (validity.valid_until === null || at < wholeSecond(validity.valid_until));
const sortedStrings = (values: string[]): string[] => [...new Set(values)].sort(byteCompare);
function walk(value: unknown, visit: (node: Row) => void): void {
  if (Array.isArray(value)) value.forEach(child => walk(child, visit));
  else if (value !== null && typeof value === 'object') { visit(value as Row); Object.values(value).forEach(child => walk(child, visit)); }
}
function datesAndValues(value: unknown, types: Types, phase: Phase): void {
  walk(value, node => {
    for (const key of ['valid_from', 'valid_until', 'occurred_at', 'returned_at', 'as_of', 'at', 'instant']) {
      if (typeof node[key] === 'string') phase.attempt(() => { wholeSecond(node[key]); });
    }
    if (node.valid_from && node.valid_until) phase.attempt(() => { if (wholeSecond(node.valid_from) >= wholeSecond(node.valid_until)) throw new AdmissionError('INPUT_INVALID'); });
    if (typeof node.type_ref === 'string' && 'value' in node && types.has(node.type_ref)) phase.attempt(() => typed(node as TypedValue, types));
    if (node.status === 'AVAILABLE' && node.query && node.as_of) phase.attempt(() => { if (wholeSecond(node.as_of) > wholeSecond(node.query.at)) throw new AdmissionError('INPUT_INVALID'); });
  });
}
function inventory(phase: Phase, rows: Row[], key = 'id'): void { phase.check(ordered(rows.map(row => row[key])), 'INPUT_INVALID'); }
function definitionOrder(definition: Row, phase: Phase): void {
  const work = definition.work_class, env = definition.envelope;
  inventory(phase, definition.source.obligations); inventory(phase, work.types); inventory(phase, work.steps);
  for (const step of work.steps) {
    inventory(phase, step.fields, 'name');
    for (const values of [step.required_credentials, step.scope_fields.subjects, step.scope_fields.resources]) phase.check(ordered(values), 'INPUT_INVALID');
  }
  inventory(phase, env.bindings); inventory(phase, env.operations, 'step'); inventory(phase, env.conditions); inventory(phase, env.gate.criteria); inventory(phase, env.limits.per_action);
  for (const values of [env.source_obligations, env.limits.shared_budgets, env.enforcement.mechanisms, env.limitations]) phase.check(ordered(values), 'INPUT_INVALID');
  phase.check(setOrder(env.scope.subjects) && setOrder(env.scope.resources), 'INPUT_INVALID');
}
function typeDeclarations(work: Row, phase: Phase): Types {
  const types: Types = new Map(work.types.map((type: ScalarType) => [type.id, type]));
  for (const type of types.values()) phase.check((type.unit === null || type.kind === 'DECIMAL') && (!type.nonnegative || ['INTEGER', 'DECIMAL'].includes(type.kind)), 'TYPE_INVALID');
  return types;
}
function referenceTypes(value: unknown, types: Types, phase: Phase): void {
  walk(value, node => { if (typeof node.type_ref === 'string') phase.check(types.has(node.type_ref), 'REFERENCE_INVALID'); });
}
function finiteLimits(value: unknown, types: Types, phase: Phase): void {
  function arrays(node: unknown): void {
    if (Array.isArray(node)) { phase.check(node.length <= 1024, 'LIMIT_EXCEEDED'); node.forEach(arrays); }
    else if (node && typeof node === 'object') Object.values(node).forEach(arrays);
  }
  arrays(value);
  walk(value, node => {
    if (typeof node.max_age_seconds === 'string') phase.check(node.max_age_seconds.length <= 128, 'LIMIT_EXCEEDED');
    if (typeof node.type_ref === 'string' && ['INTEGER', 'DECIMAL'].includes(types.get(node.type_ref)?.kind ?? '') && typeof node.value === 'string') phase.check(node.value.replace(/[-.]/g, '').length <= 128, 'LIMIT_EXCEEDED');
  });
  let nodes = 0;
  function expression(node: Row, depth: number): void {
    nodes++; phase.check(nodes <= 4096 && depth <= 64, 'LIMIT_EXCEEDED');
    if (node.kind === 'ALL' || node.kind === 'ANY') node.operands.forEach((child: Row) => expression(child, depth + 1));
    if (node.kind === 'NOT') expression(node.operand, depth + 1);
  }
  const env = (value as Row).envelope;
  for (const row of [...env.conditions, ...env.gate.criteria]) expression(row.predicate, 1);
  const work = (value as Row).work_class;
  phase.check(work.types.length <= 64 && work.steps.length <= 64 && env.operations.length <= 256, 'LIMIT_EXCEEDED');
}
function definitionRelations(definition: Row, types: Types, phase: Phase, typePhase: Phase): void {
  const work = definition.work_class, env = definition.envelope, steps = table(work.steps), bindings = table(env.bindings);
  phase.check(env.source_digest === digest('authority-source', definition.source) && env.work_class_digest === digest('authority-work-class', work), 'DEPENDENCY_MISMATCH');
  const obligations = table(definition.source.obligations);
  phase.check(env.source_obligations.every((id: string) => obligations.has(id)), 'REFERENCE_INVALID');
  phase.check(!env.limitations.length, 'UNSUPPORTED_RELATION');
  referenceTypes(definition, types, phase);
  const allowedSteps = new Set<string>(env.operations.map((operation: Row) => operation.step));
  for (const operation of env.operations) phase.check(steps.has(operation.step), 'REFERENCE_INVALID');
  if (env.bindings.length) phase.check(env.operations.length === 1, 'UNSUPPORTED_RELATION');
  for (const binding of env.bindings) {
    const step = steps.get(binding.step), field = step?.fields.find((field: Row) => field.name === binding.field);
    phase.check(Boolean(field) && env.operations.every((operation: Row) => operation.step === binding.step), 'REFERENCE_INVALID');
    if (field) phase.check(field.type_ref === binding.type_ref, 'REFERENCE_INVALID');
    if (types.has(binding.type_ref)) phase.check(['IDENTITY', 'STRING'].includes(types.get(binding.type_ref)!.kind), 'UNSUPPORTED_RELATION');
  }
  for (const selector of [...env.scope.subjects, ...env.scope.resources]) if (selector.kind === 'BINDING') phase.check(bindings.has(selector.binding), 'REFERENCE_INVALID');
  for (const step of work.steps) for (const name of [...step.scope_fields.subjects, ...step.scope_fields.resources]) {
    const field = step.fields.find((field: Row) => field.name === name);
    phase.check(Boolean(field), 'REFERENCE_INVALID');
    if (field && types.has(field.type_ref)) typePhase.check(['IDENTITY', 'STRING'].includes(types.get(field.type_ref)!.kind), 'TYPE_INVALID');
  }
  for (const row of [...env.conditions, ...env.gate.criteria]) {
    const step = steps.get(row.step);
    phase.check(Boolean(step) && allowedSteps.has(row.step), 'REFERENCE_INVALID');
    if (step) {
      try { predicateTypes(row.predicate, new Map(step.fields.map((field: Row) => [field.name, field.type_ref])), types); }
      catch (error) { if (!(error instanceof AdmissionError)) throw error; (error.code === 'TYPE_INVALID' ? typePhase : phase).failures.add(error.code); }
    }
  }
  for (const limit of env.limits.per_action) {
    const step = steps.get(limit.step), field = step?.fields.find((field: Row) => field.name === limit.field);
    phase.check(Boolean(field) && allowedSteps.has(limit.step), 'REFERENCE_INVALID');
    if (field && types.has(field.type_ref)) {
      const type = types.get(field.type_ref)!;
      typePhase.check(type.nonnegative && ['INTEGER', 'DECIMAL'].includes(type.kind) && limit.bound.type_ref === type.id, 'TYPE_INVALID');
    }
  }
}
function gateAndOperationDefinition(definition: Row, phase: Phase): void {
  const work = definition.work_class, env = definition.envelope, gate = env.gate;
  const minimum = gate.materiality === 'HIGH' || ['LOW', 'NONE'].includes(gate.reversibility) ? 2 : gate.materiality === 'MEDIUM' || gate.reversibility === 'MEDIUM' ? 1 : 0;
  const rank = ['NONE', 'VERIFY', 'DECIDE'].indexOf(gate.kind);
  phase.check(rank >= minimum, 'BINDING_MISMATCH');
  phase.check(gate.kind === 'NONE' ? gate.role === null && !gate.criteria.length : gate.role !== null && gate.criteria.length > 0, 'BINDING_MISMATCH');
  const mechanisms = env.limits.shared_budgets.length ? ['ATOMIC_SHARED_RESERVATION', 'AUTHORITY_BEFORE_RESERVATION'] : ['AUTHORITY_BEFORE_RESERVATION'];
  phase.check(same(env.enforcement.mechanisms, mechanisms), 'BINDING_MISMATCH');
  for (const operation of env.operations) {
    const step = work.steps.find((step: Row) => step.id === operation.step);
    phase.check(step?.operation === operation.operation && step?.interface === operation.interface && step?.executor_role === env.executor_role, 'BINDING_MISMATCH');
    phase.check(env.limits.shared_budgets.length || env.limits.per_action.some((limit: Row) => limit.step === operation.step), 'BINDING_MISMATCH');
    if (gate.kind !== 'NONE') phase.check(gate.criteria.some((criterion: Row) => criterion.step === operation.step), 'BINDING_MISMATCH');
  }
}
function refusal(error: unknown): Row {
  if (error instanceof AuthorityRefusal) return { status: 'REFUSED', code: error.code, path: '', reasons: error.reasons, failed_checks: error.failedChecks };
  if (error instanceof AdmissionError) return { status: 'REFUSED', code: error.code, path: '', reasons: [], failed_checks: [] };
  throw error;
}
export function validateAuthorityDefinition(input: unknown): Row {
  try {
    requireShape('authority.schema.json', 'definition', input);
    const definition = input as Row, one = new Phase(), two = new Phase(), three = new Phase();
    const types = typeDeclarations(definition.work_class, one);
    definitionOrder(definition, one); datesAndValues(definition, types, one); definitionRelations(definition, types, two, one);
    one.finish(P1); finiteLimits(definition, types, two); two.finish(P2); gateAndOperationDefinition(definition, three); three.finish(['BINDING_MISMATCH']);
    return { status: 'ACCEPTED', digest: digest('authority-definition', definition) };
  } catch (error) { return refusal(error); }
}

export function evaluateAuthority(input: unknown, selectedPin: string): Row {
  try {
    requireShape('authority.schema.json', 'input', input);
    const request = input as Row;
    const { source, work_class: work, envelope: env, proposal, host_selection: host } = request;
    const root = host.root, one = new Phase(), two = new Phase(), three = new Phase(), four = new Phase();
    const types = typeDeclarations(work, one);
    definitionOrder(request, one); datesAndValues(request, types, one);
    for (const key of ['occupancies', 'capacities', 'credentials', 'returns']) inventory(one, request[key]);
    inventory(one, proposal.fields, 'name'); inventory(one, root.channels);
    for (const values of [root.capacity_ids, root.occupancy_ids, root.providers, root.limitations]) one.check(ordered(values), 'INPUT_INVALID');
    for (const capacity of request.capacities) one.check(ordered(capacity.act_kinds), 'INPUT_INVALID');
    for (const act of request.acts) one.check(ordered(act.criteria), 'INPUT_INVALID');
    const actDigests = request.acts.map((act: Row) => digest('authority-act', act));
    one.check(ordered(actDigests) && new Set(request.acts.map((act: Row) => act.id)).size === request.acts.length, 'INPUT_INVALID');
    one.check(setOrder(host.authenticated_records), 'INPUT_INVALID');
    const decodedReturns = new Map<string, unknown>();
    for (const returned of request.returns) {
      try {
        const decoded = decodeArtifact(returned.act_bytes_base64).value;
        requireShape('authority.schema.json', 'act', decoded);
        datesAndValues(decoded, types, one);
        decodedReturns.set(returned.id, decoded);
      } catch (error) {
        if (!(error instanceof AdmissionError)) throw error;
        one.failures.add(error.code === 'SCHEMA_INVALID' ? error.code : error.code === 'NONCANONICAL' ? 'ARTIFACT_NONCANONICAL' : 'ARTIFACT_ENCODING_INVALID');
      }
    }
    definitionRelations(request, types, two, one);
    one.finish(P1);

    const S = digest('authority-source', source), W = digest('authority-work-class', work), E = digest('authority-envelope', env);
    const P = digest('authority-proposal', proposal), O = digest('authority-operation', { envelope_digest: E, work_class_digest: W, proposal_digest: P });
    const R = digest('authority-root', root), capacities = table(request.capacities), occupancies = table(request.occupancies), channels = table(root.channels);
    two.check(request.specification_pin === selectedPin, 'DEPENDENCY_MISMATCH');
    two.check(proposal.work_class_digest === W && root.source_digest === S && root.work_class_digest === W && root.envelope_digest === E && root.principal === env.principal, 'DEPENDENCY_MISMATCH');
    two.check(request.clock.source === env.clock_source, 'DEPENDENCY_MISMATCH');
    two.check(!root.limitations.length, 'UNSUPPORTED_RELATION');
    for (const [permitted, supplied] of [[root.capacity_ids, capacities], [root.occupancy_ids, occupancies]] as [string[], Map<string, Row>][]) {
      two.check([...supplied.keys()].every(id => permitted.includes(id)), 'DEPENDENCY_MISMATCH');
      two.check(permitted.every(id => supplied.has(id)), 'EVIDENCE_UNAVAILABLE');
    }
    for (const capacity of request.capacities) two.check(capacity.root_digest === R && capacity.envelope_digest === E && capacity.principal === env.principal, 'DEPENDENCY_MISMATCH');
    const authenticated: Row[] = [];
    for (const [key, kind] of [['capacities', 'CAPACITY'], ['occupancies', 'OCCUPANCY'], ['credentials', 'CREDENTIAL'], ['returns', 'RETURN']]) {
      for (const record of request[key]) {
        const channel = kind === 'RETURN' ? record.channel : null;
        authenticated.push({ kind, record_digest: digest('authority-' + kind.toLowerCase(), record), provider: record.provider, channel });
        two.check(root.providers.includes(record.provider) && (channel === null || channels.has(channel)), 'DEPENDENCY_MISMATCH');
      }
    }
    for (const channel of root.channels) two.check(root.providers.includes(channel.provider), 'DEPENDENCY_MISMATCH');
    const expectedAuthentication = new Set(authenticated.map(canonical)), actualAuthentication = new Set(host.authenticated_records.map(canonical));
    two.check([...actualAuthentication].every(row => expectedAuthentication.has(row as string)), 'DEPENDENCY_MISMATCH');
    two.check([...expectedAuthentication].every(row => actualAuthentication.has(row)), 'EVIDENCE_UNAVAILABLE');
    for (const record of [root, env, ...request.capacities, ...request.credentials]) two.check(root.providers.includes(record.revocation.provider), 'DEPENDENCY_MISMATCH');
    for (const credential of request.credentials) {
      const occupancy = occupancies.get(credential.occupancy);
      two.check(occupancy, 'EVIDENCE_UNAVAILABLE');
      if (occupancy) two.check(credential.actor === occupancy.actor, 'DEPENDENCY_MISMATCH');
    }
    for (const observation of request.observations) two.check(observation.query_digest === digest('authority-query', observation.query) && root.providers.includes(observation.query.provider), 'DEPENDENCY_MISMATCH');
    const step = work.steps.find((row: Row) => row.id === proposal.step);
    if (step) {
      const kinds = request.credentials.map((credential: Row) => credential.kind);
      two.check(kinds.every((kind: string) => step.required_credentials.includes(kind)) && new Set(kinds).size === kinds.length, 'DEPENDENCY_MISMATCH');
      two.check(step.required_credentials.every((kind: string) => kinds.includes(kind)), 'EVIDENCE_UNAVAILABLE');
    }
    finiteLimits(request, types, two); two.finish(P2);

    const now = request.clock.status === 'AVAILABLE' ? wholeSecond(request.clock.instant) : null;
    const fields = new Map<string, TypedValue>(proposal.fields.map((field: Row) => [field.name, field.value]));
    gateAndOperationDefinition(request, three);
    three.check(step && proposal.work_class === work.id && env.operations.some((operation: Row) => operation.step === proposal.step && operation.operation === proposal.operation && operation.interface === proposal.interface), 'BINDING_MISMATCH');
    three.check(step && proposal.operation === step.operation && proposal.interface === step.interface && proposal.executor.role === step.executor_role && proposal.executor.role === env.executor_role && proposal.executor.principal === env.principal, 'BINDING_MISMATCH');
    if (step) three.check(fields.size === step.fields.length && step.fields.every((field: Row) => fields.get(field.name)?.type_ref === field.type_ref), 'BINDING_MISMATCH');
    const executor = occupancies.get(proposal.executor.occupancy);
    three.check(executor && executor.actor === proposal.executor.actor && executor.role === proposal.executor.role && executor.principal === proposal.executor.principal, 'BINDING_MISMATCH');
    for (const credential of request.credentials) three.check(credential.actor === proposal.executor.actor && credential.occupancy === proposal.executor.occupancy && credential.step === proposal.step && credential.operation === proposal.operation && credential.interface === proposal.interface, 'BINDING_MISMATCH');
    three.finish(['BINDING_MISMATCH']);
    const scope: Row = {}, actualScope: Row = {}, bindingRows = table(env.bindings);
    for (const key of ['subjects', 'resources']) {
      scope[key] = sortedStrings(env.scope[key].map((selector: Row) => selector.kind === 'CONSTANT' ? selector.value : fields.get(bindingRows.get(selector.binding)!.field)!.value));
      actualScope[key] = sortedStrings(step.scope_fields[key].map((name: string) => fields.get(name)!.value));
      three.check(scope[key].every((value: string) => value.length > 0) && actualScope[key].every((value: string) => value.length > 0 && scope[key].includes(value)), 'BINDING_MISMATCH');
    }
    three.finish(['BINDING_MISMATCH']);

    const grants = request.acts.filter((act: Row) => act.kind === 'GRANT');
    const verifications = request.acts.filter((act: Row) => act.kind === 'VERIFY');
    const decisions = request.acts.filter((act: Row) => act.kind === 'INSTANCE_DECISION');
    const attestations = request.acts.filter((act: Row) => act.kind === 'ORGANISATIONAL_ATTESTATION');
    const expectedVerify = env.gate.kind === 'VERIFY' ? 1 : 0, expectedDecision = env.gate.kind === 'DECIDE' ? 1 : 0, expectedAttest = 1 + expectedDecision;
    four.check(grants.length <= 1 && verifications.length <= expectedVerify && decisions.length <= expectedDecision && attestations.length <= expectedAttest, 'ACT_CONFLICT');
    four.check(verifications.length >= expectedVerify && decisions.length >= expectedDecision, 'GATE_REQUIRED');
    four.check(grants.length === 1 && attestations.length === expectedAttest, 'EVIDENCE_UNAVAILABLE');
    const grant = grants[0], gateAct = env.gate.kind === 'VERIFY' ? verifications[0] : env.gate.kind === 'DECIDE' ? decisions[0] : undefined;
    const attestedSubjects = new Map<string, Row>();
    if (grant) attestedSubjects.set(digest('authority-act', grant), grant);
    if (env.gate.kind === 'DECIDE' && gateAct) attestedSubjects.set(digest('authority-act', gateAct), gateAct);
    four.check(new Set(attestations.map((act: Row) => act.subject_digest)).size === attestations.length, 'ACT_CONFLICT');
    const applicableCriteria = env.gate.criteria.filter((row: Row) => row.step === proposal.step);
    const returnsByAct = new Map<string, Row[]>();
    for (const returned of request.returns) {
      const rows = returnsByAct.get(returned.act_digest) ?? []; rows.push(returned); returnsByAct.set(returned.act_digest, rows);
      four.check(actDigests.includes(returned.act_digest), 'ACT_NOT_AUTHORIZED');
    }
    for (const rows of returnsByAct.values()) four.check(rows.length <= 1, 'ACT_CONFLICT');
    for (const act of request.acts) {
      const A = digest('authority-act', act), capacity = capacities.get(act.capacity), occupancy = occupancies.get(act.occupancy), at = wholeSecond(act.occurred_at);
      const returned = returnsByAct.get(A)?.[0];
      four.check(capacity && occupancy && returned, 'EVIDENCE_UNAVAILABLE');
      four.check(act.disposition === 'ACCEPT', 'ACT_NOT_ACCEPTED');
      four.check(act.principal === env.principal && (now === null || at <= now) && within(root.validity, at), 'ACT_NOT_AUTHORIZED');
      if (capacity && occupancy) {
        four.check(capacity.actor === act.actor && capacity.role === act.role && capacity.principal === act.principal && capacity.occupancy === act.occupancy && capacity.act_kinds.includes(act.kind), 'ACT_NOT_AUTHORIZED');
        four.check(occupancy.actor === act.actor && occupancy.role === act.role && occupancy.principal === act.principal && occupancy.kind === 'HUMAN' && within(capacity.validity, at) && within(occupancy.validity, at), 'ACT_NOT_AUTHORIZED');
      }
      if (act.kind === 'GRANT') four.check(act.id === env.grant_ref && act.subject_digest === E && act.role === env.grantor_role && act.attested_actor === null && !act.criteria.length, 'ACT_NOT_AUTHORIZED');
      else if (act.kind === 'ORGANISATIONAL_ATTESTATION') {
        const subject = attestedSubjects.get(act.subject_digest);
        four.check(subject && act.attested_actor === subject.actor && act.role === env.attester_role && !act.criteria.length && at >= wholeSecond(subject.occurred_at), 'ACT_NOT_AUTHORIZED');
        if (subject?.actor === act.actor) four.check(root.allow_self_attestation && capacity?.may_self_attest, 'ACT_NOT_AUTHORIZED');
      } else four.check(act.subject_digest === O && act.role === env.gate.role && act.attested_actor === null && same(act.criteria, applicableCriteria.map((row: Row) => row.id)), 'ACT_NOT_AUTHORIZED');
      if (returned) {
        const channel = channels.get(returned.channel), returnedAt = wholeSecond(returned.returned_at);
        four.check(same(decodedReturns.get(returned.id), act) && returned.actor === act.actor && channel?.provider === returned.provider && returnedAt >= at && (now === null || returnedAt <= now) && within(channel!.validity, returnedAt), 'ACT_NOT_AUTHORIZED');
        if (channel && now !== null) four.check(within(channel.validity, now) || channel.prior_returns_survive_expiry, 'ACT_NOT_AUTHORIZED');
      }
    }
    four.finish(P4);
    if (now === null) throw new AuthorityRefusal('AUTHORITY_NOT_ESTABLISHED', ['CLOCK_UNAVAILABLE']);

    const queries = new Map<string, { query: Row; declaration: Row }>();
    function addQuery(subject: string, declaration: Row, at: string): void {
      const query = { purpose: 'REVOCATION', subject_digest: subject, at, provider: declaration.provider, source: declaration.source };
      queries.set(digest('authority-query', query), { query, declaration });
    }
    for (const act of request.acts) {
      const capacity = capacities.get(act.capacity)!;
      for (const at of [act.occurred_at, request.clock.instant]) {
        addQuery(R, root.revocation, at); addQuery(digest('authority-capacity', capacity), capacity.revocation, at);
      }
    }
    addQuery(E, env.revocation, request.clock.instant);
    for (const credential of request.credentials) addQuery(digest('authority-credential', credential), credential.revocation, request.clock.instant);
    const five = new Phase(), observations = new Map<string, Map<string, Row>>();
    for (const observation of request.observations) {
      five.check(queries.has(observation.query_digest), 'DEPENDENCY_MISMATCH');
      const rows = observations.get(observation.query_digest) ?? new Map(); rows.set(canonical(observation), observation); observations.set(observation.query_digest, rows);
    }
    five.check([...queries.keys()].every(query => observations.has(query)), 'EVIDENCE_UNAVAILABLE');
    five.finish(['DEPENDENCY_MISMATCH', 'EVIDENCE_UNAVAILABLE']);
    // AUTHORITY-CHECKS: each failed phase-5 check is recorded with its Exact successful check construction values.
    const reasons = new Set<string>(), failedChecks = new Map<string, Row>();
    const policy = (condition: unknown, reason: string, purpose: string, subject_digest: string, requirement_ref: string, at = request.clock.instant): void => {
      if (condition) return;
      const row = { purpose, subject_digest, requirement_ref, at, reason }; reasons.add(reason); failedChecks.set(canonical(row), row);
    };
    for (const [id, { query, declaration }] of queries) {
      const rows = [...observations.get(id)!.values()];
      const revocation = (condition: unknown, reason: string): void => policy(condition, reason, 'REVOCATION', query.subject_digest, id, query.at);
      if (rows.length > 1) { revocation(false, 'OBSERVATION_CONFLICT'); continue; }
      const observation = rows[0];
      if (observation.status !== 'AVAILABLE') { revocation(false, 'OBSERVATION_' + observation.status); continue; }
      revocation(wholeSecond(query.at) - wholeSecond(observation.as_of) <= BigInt(declaration.max_age_seconds) * 1000000000n, 'OBSERVATION_STALE');
      revocation(!observation.revoked, 'REVOKED');
    }
    policy(within(env.temporal_validity, now), 'ENVELOPE_EXPIRED', 'ENVELOPE_VALIDITY', E, env.id);
    policy(within(root.validity, now) || root.prior_acts_survive_expiry, 'ROOT_EXPIRED', 'ROOT_BINDING', E, root.id);
    policy(within(executor!.validity, now), 'ACT_EXPIRED', 'EXECUTOR_OCCUPANCY', O, proposal.executor.occupancy);
    for (const credential of request.credentials) policy(within(credential.validity, now), 'CREDENTIAL_EXPIRED', 'CREDENTIAL', O, credential.id);
    for (const act of request.acts) {
      const capacity = capacities.get(act.capacity)!;
      policy(within(capacity.validity, now) || (capacity.reliance.kind === 'SURVIVE_EXPIRY' && within(capacity.reliance.validity, now)), 'RELIANCE_EXPIRED', 'ACT_RELIANCE', digest('authority-act', act), act.capacity);
    }
    const conditions = env.conditions.filter((row: Row) => row.step === proposal.step), limits = env.limits.per_action.filter((row: Row) => row.step === proposal.step);
    for (const row of conditions) policy(predicate(row.predicate, fields), 'CONDITION_VIOLATED', 'CONDITION', O, row.id);
    for (const row of applicableCriteria) policy(predicate(row.predicate, fields), 'GATE_CRITERION_VIOLATED', 'GATE_CRITERION', digest('authority-act', gateAct), row.id, gateAct.occurred_at);
    for (const row of limits) policy(boundSatisfied(fields.get(row.field)!.value as string, row.operator, row.bound.value), 'PER_ACTION_LIMIT_VIOLATED', 'PER_ACTION_LIMIT', O, row.id);
    if (reasons.size) throw new AuthorityRefusal('AUTHORITY_NOT_ESTABLISHED', [...reasons].sort(byteCompare), [...failedChecks.entries()].sort(([a], [b]) => byteCompare(a, b)).map(([, row]) => row));

    const checks = new Map<string, Row>();
    function check(purpose: string, subject_digest: string, requirement_ref: string, at = request.clock.instant): void {
      const row = { purpose, subject_digest, requirement_ref, at }; checks.set(canonical(row), row);
    }
    check('SOURCE_BINDING', E, source.id); check('ROOT_BINDING', E, root.id); check('INPUT_SUPPORT', O, proposal.step); check('BINDING', O, env.scope.id);
    check('GATE_FLOOR', E, env.id); check('ENVELOPE_VALIDITY', E, env.id); check('EXECUTOR_OCCUPANCY', O, proposal.executor.occupancy);
    for (const row of conditions) check('CONDITION', O, row.id);
    for (const row of limits) check('PER_ACTION_LIMIT', O, row.id);
    for (const row of request.credentials) check('CREDENTIAL', O, row.id);
    for (const act of request.acts) {
      const A = digest('authority-act', act);
      check('ACT_CAPACITY', A, act.capacity, act.occurred_at); check('ACT_OCCUPANCY', A, act.occupancy, act.occurred_at);
      check('ACT_RELIANCE', A, act.capacity); check('RETURN', A, returnsByAct.get(A)![0].id);
      if (act.kind === 'ORGANISATIONAL_ATTESTATION') check('SEPARATION', A, act.capacity);
    }
    if (gateAct) for (const row of applicableCriteria) check('GATE_CRITERION', digest('authority-act', gateAct), row.id, gateAct.occurred_at);
    for (const [id, { query }] of queries) check('REVOCATION', query.subject_digest, id, query.at);
    const evidence = Object.fromEntries(['host_selection', 'occupancies', 'capacities', 'credentials', 'acts', 'returns', 'observations', 'clock'].map(key => [key, request[key]]));
    return { schema: VERSION + '/authority-result', specification_pin: selectedPin, status: 'READY_FOR_RESERVATION', source_digest: S, work_class_digest: W, envelope_digest: E, proposal_digest: P, operation_digest: O, scope, actual_scope: actualScope, act_digests: actDigests, checks: [...checks.entries()].sort(([a], [b]) => byteCompare(a, b)).map(([, value]) => value), required_budgets: env.limits.shared_budgets, evidence_digest: digest('authority-evidence', evidence) };
  } catch (error) { return refusal(error); }
}
