import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { instant, instantText } from './time.ts';
import { ordered, same, setOrder, typed } from './values.ts';
import type { RecordValue as Row, Types } from './values.ts';
import { flowValue } from './information-flow.ts';
import { assessmentLinkedDecision, assessmentValue } from './assessments.ts';

type Check = (condition: unknown, code: string) => void;
export const decisionRequirements = (request: Row): Row[] => request.envelope.decision_requirements ?? [];
export const decisionBasis = (request: Row, id: string): Row | undefined => request.decision_bases?.find((row: Row) => row.requirement_id === id)?.evidence;
export const decisionAct = (request: Row, id: string): Row | undefined => {
  const evidence = decisionBasis(request, id);
  return evidence?.authority_input.acts.find((act: Row) => digest('authority-act', act) === evidence.decision_act_digest);
};
export function relianceDigest(input: Row): string {
  return digest('human-decision-reliance-subjects', { root_digest: digest('authority-root', input.host_selection.root), envelope_digest: digest('authority-envelope', input.envelope), capacities: input.capacities.map((row: Row) => ({ id: row.id, capacity_digest: digest('authority-capacity', row) })).sort((a: Row, b: Row) => byteCompare(a.id, b.id)) });
}
export function decisionOperand(request: Row, selector: Row): Row | undefined {
  const evidence = decisionBasis(request, selector.requirement_id);
  if (!evidence) return undefined;
  if (selector.kind === 'DECISION_FIELD') return evidence.authority_input.proposal.fields.find((row: Row) => row.name === selector.field)?.value;
  if (selector.kind === 'DECISION_BASIS') return { type_ref: selector.type_ref, value: relianceDigest(evidence.authority_input) };
  const act = decisionAct(request, selector.requirement_id);
  return act ? { type_ref: selector.type_ref, value: selector.member === 'digest' ? digest('authority-act', act) : act[selector.member] } : undefined;
}

function relationMatches(relation: Row, left: (value: Row) => boolean, right: (value: Row) => boolean): boolean {
  return relation.kind === 'EQUALS' && ((left(relation.left) && right(relation.right)) || (left(relation.right) && right(relation.left)));
}
export function admitDecisionDeclarations(request: Row, types: Types, check: Check, typeCheck: Check): void {
  const declarations = decisionRequirements(request), byId = new Map<string, Row>(declarations.map(row => [row.id, row]));
  typeCheck(ordered(declarations.map(row => row.id)), 'INPUT_INVALID');
  for (const row of declarations) {
    const step = request.work_class.steps.find((step: Row) => step.id === row.step);
    const record = request.envelope.source_observation_requirements?.find((record: Row) => record.id === row.record_requirement_id);
    check(step && record, 'REFERENCE_INVALID');
    if (!step || !record) continue;
    const unknownAssessment = row.context_bindings.some((binding: Row) => {
      if (binding.value.kind !== 'ASSESSMENT') return false;
      const required = (request.envelope.assessment_requirements ?? []).find((required: Row) => required.id === binding.value.requirement_id);
      return !required || !byId.has(required.review_decision_requirement_id) || !request.work_class.steps.some((step: Row) => step.id === required.step);
    });
    check(record.step === row.step && record.expected_status === 'AVAILABLE' && record.purpose === 'AUTHORITY' && (unknownAssessment || (assessmentLinkedDecision(request, row) ? record.record_id === null : record.record_id !== null)), 'UNSUPPORTED_RELATION');
    if (step.dispatch_gate?.kind === 'SOURCE_REQUIREMENTS' && step.dispatch_gate.requirements.includes(record.id)) check(record.evaluation_point === 'PROPOSE_AND_DISPATCH', 'UNSUPPORTED_RELATION');
    typeCheck(ordered(row.context_bindings.map((binding: Row) => binding.field)) && setOrder(row.distinct_from), 'INPUT_INVALID');
    check(row.validity_fields.not_before_field !== row.validity_fields.not_after_field, 'REFERENCE_INVALID');
    for (const binding of row.context_bindings) {
      if (binding.value.kind === 'PROPOSAL_FIELD') check(step.fields.some((field: Row) => field.name === binding.value.field), 'REFERENCE_INVALID');
      else if (['ASSESSMENT', 'FLOW_DISCLOSURE'].includes(binding.value.kind)) check(types.has(binding.value.type_ref), 'REFERENCE_INVALID');
      else { check(types.has(binding.value.value.type_ref), 'REFERENCE_INVALID'); try { typed(binding.value.value, types); } catch (error) { if (!(error instanceof AdmissionError)) throw error; typeCheck(false, error.code); } }
    }
    for (const other of row.distinct_from) if (other.kind === 'DECISION') check(other.requirement_id !== row.id && byId.get(other.requirement_id)?.step === row.step, 'REFERENCE_INVALID');
    const ownField = (value: Row): boolean => value?.kind === 'OBSERVATION_FIELD' && value.requirement_id === row.record_requirement_id && record.fields.some((field: Row) => field.name === value.field);
    for (const member of ['id', 'digest', 'actor', 'role', 'principal', 'occurred_at']) {
      check(record.relations.some((relation: Row) => relationMatches(relation, value => member === 'id' ? value?.kind === 'OBSERVATION_ID' && value.requirement_id === row.record_requirement_id : ownField(value), value => value?.kind === 'DECISION_ACT' && value.requirement_id === row.id && value.member === member)), 'UNSUPPORTED_RELATION');
    }
    for (const binding of row.context_bindings) check(record.relations.some((relation: Row) => relationMatches(relation, ownField, value => value?.kind === 'DECISION_FIELD' && value.requirement_id === row.id && value.field === binding.field)), 'UNSUPPORTED_RELATION');
  }
  const gate = request.envelope.gate;
  if (gate.decision_requirement !== undefined) {
    const row = byId.get(gate.decision_requirement);
    check(row, 'REFERENCE_INVALID');
    check(gate.kind === 'DECIDE', 'UNSUPPORTED_RELATION');
  }
}

export function admitDecisionInputs(request: Row, check: Check, typeCheck: Check): void {
  const selected = decisionRequirements(request).filter(row => row.step === request.proposal.step), rows = request.decision_bases ?? [];
  typeCheck(ordered(rows.map((row: Row) => row.requirement_id)), 'INPUT_INVALID');
  check(rows.every((row: Row) => selected.some(required => required.id === row.requirement_id)), 'DEPENDENCY_MISMATCH');
  check(selected.every(required => rows.some((row: Row) => row.requirement_id === required.id)), 'EVIDENCE_UNAVAILABLE');
  if (request.decision_bases !== undefined || request.envelope.decision_requirements !== undefined) check(Buffer.byteLength(canonical(request)) <= 1048576, 'LIMIT_EXCEEDED');
  const outerTypes = new Map<string, Row>(request.work_class.types.map((type: Row) => [type.id, type]));
  for (const required of selected) {
    const evidence = decisionBasis(request, required.id);
    if (!evidence) continue;
    const leaf = evidence.authority_input, leafTypes = new Map<string, Row>(leaf.work_class.types.map((type: Row) => [type.id, type]));
    check(Buffer.byteLength(canonical(leaf)) <= 262144, 'LIMIT_EXCEEDED');
    check(digest('authority-work-class', leaf.work_class) === required.work_class_digest && digest('authority-envelope', leaf.envelope) === required.envelope_digest, 'DEPENDENCY_MISMATCH');
    check(leaf.work_class.steps.length === 1 && leaf.work_class.steps[0].id === leaf.proposal.step, 'UNSUPPORTED_RELATION');
    check(same(required.context_bindings.map((row: Row) => row.field), leaf.work_class.steps[0].fields.map((row: Row) => row.name)), 'REFERENCE_INVALID');
    for (const binding of required.context_bindings) {
      const own = leaf.work_class.steps[0].fields.find((row: Row) => row.name === binding.field);
      const parent = binding.value.kind === 'LITERAL' ? binding.value.value.type_ref : ['ASSESSMENT', 'FLOW_DISCLOSURE'].includes(binding.value.kind) ? binding.value.type_ref : request.work_class.steps.find((step: Row) => step.id === required.step)?.fields.find((field: Row) => field.name === binding.value.field)?.type_ref;
      check(own && parent && leafTypes.has(own.type_ref) && outerTypes.has(parent), 'REFERENCE_INVALID');
      if (own && parent && leafTypes.has(own.type_ref) && outerTypes.has(parent)) typeCheck(same(leafTypes.get(own.type_ref), outerTypes.get(parent)), 'TYPE_INVALID');
    }
    for (const field of Object.values(required.validity_fields)) {
      const typeRef = leaf.work_class.steps[0].fields.find((row: Row) => row.name === field)?.type_ref;
      check(typeRef, 'REFERENCE_INVALID');
      if (typeRef) typeCheck(leafTypes.get(typeRef)?.kind === 'INSTANT', 'TYPE_INVALID');
    }
    const identity = leaf.work_class.steps[0].fields.find((row: Row) => row.name === required.identity_field);
    check(identity && required.context_bindings.some((row: Row) => row.field === required.identity_field), 'REFERENCE_INVALID');
    if (identity) typeCheck(['STRING', 'IDENTITY'].includes(leafTypes.get(identity.type_ref)?.kind ?? ''), 'TYPE_INVALID');
    if (request.envelope.gate.decision_requirement === required.id) {
      const computed = new Set<string>(required.context_bindings.filter((row: Row) => ['ASSESSMENT', 'FLOW_DISCLOSURE'].includes(row.value.kind)).map((row: Row) => row.field));
      const literals = (node: Row): void => {
        if (!node || typeof node !== 'object') return;
        if (node.kind === 'FIELD') check(!computed.has(node.name), 'UNSUPPORTED_RELATION');
        if (node.kind === 'LITERAL') { check(leafTypes.has(node.value.type_ref) && outerTypes.has(node.value.type_ref), 'REFERENCE_INVALID'); if (leafTypes.has(node.value.type_ref) && outerTypes.has(node.value.type_ref)) typeCheck(same(leafTypes.get(node.value.type_ref), outerTypes.get(node.value.type_ref)), 'TYPE_INVALID'); }
        for (const value of Object.values(node)) if (value && typeof value === 'object') literals(value as Row);
      };
      literals(leaf.envelope.gate.criteria);
    }
  }
}

function translate(node: Row, bindings: Map<string, Row>): Row {
  if (Array.isArray(node)) return node.map(child => translate(child, bindings));
  if (!node || typeof node !== 'object') return node;
  if (node.kind === 'FIELD') {
    const value = bindings.get(node.name);
    if (!value) throw new AdmissionError('BINDING_MISMATCH');
    if (['ASSESSMENT', 'FLOW_DISCLOSURE'].includes(value.kind)) throw new AdmissionError('UNSUPPORTED_RELATION');
    return value.kind === 'PROPOSAL_FIELD' ? { kind: 'FIELD', name: value.field } : structuredClone(value);
  }
  return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, value && typeof value === 'object' ? translate(value as Row, bindings) : value]));
}
export function bindDecisionInputs(request: Row, check: Check): void {
  const gate = request.envelope.gate;
  if (gate.decision_requirement !== undefined) {
    const required = decisionRequirements(request).find(row => row.id === gate.decision_requirement);
    check(required && required.step === request.proposal.step && required.principal === request.envelope.principal && required.role === gate.role, 'BINDING_MISMATCH');
  }
  for (const required of decisionRequirements(request).filter(row => row.step === request.proposal.step)) {
    const leaf = decisionBasis(request, required.id)?.authority_input;
    if (!leaf) continue;
    check(leaf.envelope.principal === required.principal && leaf.envelope.gate.role === required.role, 'BINDING_MISMATCH');
    check(leaf.clock.source === leaf.envelope.clock_source && leaf.clock.status === request.clock.status && leaf.clock.instant === request.clock.instant, 'BINDING_MISMATCH');
    for (const binding of required.context_bindings) {
      const expected = binding.value.kind === 'LITERAL' ? binding.value.value : binding.value.kind === 'ASSESSMENT' ? assessmentValue(request, binding.value) : binding.value.kind === 'FLOW_DISCLOSURE' ? flowValue(request, binding.value) : request.proposal.fields.find((field: Row) => field.name === binding.value.field)?.value;
      check(expected && same(leaf.proposal.fields.find((field: Row) => field.name === binding.field)?.value, expected), 'BINDING_MISMATCH');
    }
    const before = leaf.proposal.fields.find((field: Row) => field.name === required.validity_fields.not_before_field)?.value.value;
    const after = leaf.proposal.fields.find((field: Row) => field.name === required.validity_fields.not_after_field)?.value.value;
    check(before === leaf.envelope.temporal_validity.valid_from && after !== null && after === leaf.envelope.temporal_validity.valid_until, 'BINDING_MISMATCH');
    const act = decisionAct(request, required.id), record = request.envelope.source_observation_requirements.find((row: Row) => row.id === required.record_requirement_id);
    if (act && record) check((assessmentLinkedDecision(request, required) ? record.record_id === null : record.record_id !== null && record.record_id === act.id) && leaf.proposal.fields.find((row: Row) => row.name === required.identity_field)?.value.value === canonical({ provider: record.provider, source: record.source, record_type: record.record_type, provider_record_id: act.id }), 'BINDING_MISMATCH');
    if (request.envelope.gate.decision_requirement === required.id) {
      const own = leaf.envelope.gate.criteria.filter((criterion: Row) => criterion.step === leaf.proposal.step), parent = request.envelope.gate.criteria.filter((criterion: Row) => criterion.step === request.proposal.step);
      check(same(own.map((row: Row) => row.id), parent.map((row: Row) => row.id)), 'BINDING_MISMATCH');
      const bindings = new Map<string, Row>(required.context_bindings.map((row: Row) => [row.field, row.value]));
      for (const criterion of own) {
        try { check(same(translate(criterion.predicate, bindings), parent.find((row: Row) => row.id === criterion.id)?.predicate), 'BINDING_MISMATCH'); }
        catch (error) { if (!(error instanceof AdmissionError)) throw error; check(false, error.code); }
      }
    }
  }
}

export function effectiveUntil(input: Row): string {
  const now = instant(input.clock.instant), bounds: bigint[] = [instant(input.envelope.temporal_validity.valid_until)];
  const add = (end: string | null): void => { if (end !== null) bounds.push(instant(end)); };
  const root = input.host_selection.root;
  if (!root.prior_acts_survive_expiry) add(root.validity.valid_until);
  for (const returned of input.returns) {
    const channel = root.channels.find((row: Row) => row.id === returned.channel);
    if (!channel.prior_returns_survive_expiry) add(channel.validity.valid_until);
  }
  for (const capacity of input.capacities.filter((row: Row) => input.acts.some((act: Row) => act.capacity === row.id))) {
    if (capacity.reliance.kind === 'CURRENT_ONLY') { add(capacity.validity.valid_until); continue; }
    const intervals = [capacity.validity, capacity.reliance.validity].map((value: Row) => ({ start: instant(value.valid_from), end: value.valid_until === null ? null : instant(value.valid_until) })).sort((a, b) => a.start < b.start ? -1 : 1);
    let current = intervals.find(row => row.start <= now && (row.end === null || now < row.end));
    if (!current) throw new AdmissionError('BINDING_MISMATCH');
    for (const other of intervals) if (other !== current && (current.end === null || other.start <= current.end) && (other.end === null || current.start <= other.end)) current = { start: current.start < other.start ? current.start : other.start, end: current.end === null || other.end === null ? null : current.end > other.end ? current.end : other.end };
    if (current.end !== null) bounds.push(current.end);
  }
  return instantText(bounds.reduce((a, b) => a < b ? a : b));
}

export function selectedAuthorityAct(input: Row, kind: string): Row[] {
  if (kind === 'INSTANCE_DECISION' && input.envelope.gate.decision_requirement !== undefined) {
    const act = decisionAct(input, input.envelope.gate.decision_requirement);
    return act ? [{ act_digest: digest('authority-act', act), act }] : [];
  }
  return input.acts.filter((act: Row) => act.kind === kind).map((act: Row) => ({ act_digest: digest('authority-act', act), act }));
}
export function independentActors(input: Row): string[] {
  return (input.decision_bases ?? []).flatMap((row: Row) => row.evidence.authority_input.acts.map((act: Row) => act.actor));
}
