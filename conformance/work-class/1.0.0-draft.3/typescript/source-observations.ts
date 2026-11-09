import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { instant } from './time.ts';
import { ordered, same, typed } from './values.ts';
import type { RecordValue as Row, Types, TypedValue } from './values.ts';
import { decisionOperand, decisionRequirements } from './human-decisions.ts';

type Check = (condition: unknown, code: string) => void;
const identityKinds = ['IDENTITY', 'STRING'];
const temporalKinds = ['BEFORE', 'AFTER', 'AT_OR_BEFORE', 'AT_OR_AFTER', 'ELAPSED_LTE'];
const requirements = (request: Row): Row[] => request.envelope.source_observation_requirements ?? [];
const point = (requirement: Row): string => requirement.evaluation_point ?? 'PROPOSE';
const keyName = (projection: Row): string => projection.key_field ?? projection.field;

export function admitSourceRequirements(request: Row, types: Types, check: Check, typeCheck: Check): void {
  const steps = new Map<string, Row>(request.work_class.steps.map((row: Row) => [row.id, row]));
  const declarations = new Map<string, Row>(requirements(request).map(row => [row.id, row]));
  const edges = new Map<string, string[]>();
  function selectorType(selector: Row | string, requirement: Row): string | undefined {
    const step = steps.get(requirement.step);
    if (typeof selector === 'string') {
      const field = requirement.fields.find((row: Row) => row.name === selector);
      check(field, 'REFERENCE_INVALID'); return field?.type_ref;
    }
    if (['DECISION_ACT', 'DECISION_FIELD', 'DECISION_BASIS'].includes(selector.kind)) {
      const selected = decisionRequirements(request).find(row => row.id === selector.requirement_id);
      check(selected && selected.step === requirement.step, 'REFERENCE_INVALID');
      if (selector.kind === 'DECISION_FIELD') {
        const binding = selected?.context_bindings.find((row: Row) => row.field === selector.field);
        check(binding, 'REFERENCE_INVALID');
        return binding?.value.kind === 'LITERAL' ? binding.value.value.type_ref : ['ASSESSMENT', 'FLOW_DISCLOSURE'].includes(binding?.value.kind) ? binding.value.type_ref : step?.fields.find((field: Row) => field.name === binding?.value.field)?.type_ref;
      }
    }
    if (selector.kind === 'PROPOSAL_FIELD') {
      const field = step?.fields.find((row: Row) => row.name === selector.field);
      check(field, 'REFERENCE_INVALID'); return field?.type_ref;
    }
    if (selector.kind === 'OBSERVATION_FIELD' || selector.kind === 'OBSERVATION_ID') {
      const target = declarations.get(selector.requirement_id);
      check(target, 'REFERENCE_INVALID');
      if (!target) return undefined;
      check(target.step === requirement.step && target.expected_status === 'AVAILABLE' && (point(requirement) !== 'PROPOSE_AND_DISPATCH' || point(target) === 'PROPOSE_AND_DISPATCH'), 'UNSUPPORTED_RELATION');
      if (target.id !== requirement.id) edges.set(requirement.id, [...(edges.get(requirement.id) ?? []), target.id]);
      if (selector.kind === 'OBSERVATION_FIELD') {
        const field = target.fields.find((row: Row) => row.name === selector.field);
        check(field, 'REFERENCE_INVALID'); return field?.type_ref;
      }
    }
    const typeRef = selector.kind === 'LITERAL' ? selector.value.type_ref : selector.type_ref;
    const type = types.get(typeRef);
    check(type, 'REFERENCE_INVALID');
    if (type) {
      if (selector.kind === 'CLOCK' || (['ACT', 'DECISION_ACT'].includes(selector.kind) && selector.member === 'occurred_at')) typeCheck(type.kind === 'INSTANT', 'TYPE_INVALID');
      else if (['EXECUTOR', 'ACT', 'OBSERVATION_ID', 'DECISION_ACT', 'DECISION_BASIS'].includes(selector.kind)) typeCheck(identityKinds.includes(type.kind), 'TYPE_INVALID');
      if (selector.kind === 'LITERAL') {
        try { typed(selector.value, types); }
        catch (error) { if (!(error instanceof AdmissionError)) throw error; typeCheck(false, error.code); }
      }
    }
    return typeRef;
  }
  for (const requirement of declarations.values()) {
    const step = steps.get(requirement.step);
    check(step, 'REFERENCE_INVALID');
    if (requirement.expected_status === 'ABSENT') {
      typeCheck(requirement.fields.length === 0, 'INPUT_INVALID');
      check(requirement.relations.length === 0, 'UNSUPPORTED_RELATION');
    }
    if (typeof requirement.subject !== 'string') {
      const type = selectorType(requirement.subject, requirement);
      if (type && types.has(type)) typeCheck(identityKinds.includes(types.get(type)!.kind), 'TYPE_INVALID');
    }
    const projection = requirement.key_projection ?? [];
    typeCheck(ordered(projection.map(keyName)), 'INPUT_INVALID');
    for (const row of projection) {
      const field = step?.fields.find((field: Row) => field.name === row.field);
      check(field && types.has(row.type_ref), 'REFERENCE_INVALID');
      if (field) typeCheck(field.type_ref === row.type_ref, 'TYPE_INVALID');
    }
    for (const relation of requirement.relations) {
      const left = selectorType(relation.left, requirement), right = selectorType(relation.right, requirement);
      check(relation.kind !== 'INCLUDES', 'UNSUPPORTED_RELATION');
      if (relation.kind === 'ELAPSED_LTE') check(relation.maximum_seconds.length <= 128, 'LIMIT_EXCEEDED');
      if (left && right && types.has(left) && types.has(right)) {
        typeCheck(left === right, 'TYPE_INVALID');
        if (temporalKinds.includes(relation.kind)) typeCheck(types.get(left)!.kind === 'INSTANT' && types.get(right)!.kind === 'INSTANT', 'TYPE_INVALID');
      }
    }
  }
  const visiting = new Set<string>(), visited = new Set<string>();
  function visit(id: string): void {
    if (visiting.has(id)) { typeCheck(false, 'INPUT_INVALID'); return; }
    if (visited.has(id)) return;
    visiting.add(id); for (const target of edges.get(id) ?? []) visit(target);
    visiting.delete(id); visited.add(id);
  }
  for (const id of declarations.keys()) visit(id);
  for (const step of steps.values()) {
    const refs = step.authority_type_refs ?? [];
    typeCheck(ordered(refs), 'INPUT_INVALID');
    for (const ref of refs) check(types.has(ref), 'REFERENCE_INVALID');
    check(requirements(request).filter(row => row.step === step.id).reduce((count, row) => count + row.relations.length, 0) <= 256, 'LIMIT_EXCEEDED');
    const gate = step.dispatch_gate;
    if (!gate) continue;
    const vector = gate.kind === 'SOURCE_REQUIREMENTS';
    const ids = vector ? gate.requirements : [gate.approval_requirement, gate.withdrawal_requirement, ...gate.policy_withdrawal_requirements];
    for (const binding of step.completion?.authorization_revision_bindings ?? []) check(ids.includes(binding.requirement_id) && declarations.get(binding.requirement_id)?.expected_status === 'AVAILABLE', 'REFERENCE_INVALID');
    typeCheck((vector ? ordered(ids) && ordered(gate.validity_requirements.map((row: Row) => row.requirement_id)) : ordered(gate.policy_withdrawal_requirements)) && new Set(ids).size === ids.length, 'INPUT_INVALID');
    check(ids.length <= 64, 'LIMIT_EXCEEDED');
    for (const id of ids) {
      const requirement = declarations.get(id);
      check(requirement, 'REFERENCE_INVALID');
      if (!requirement) continue;
      check(requirement.step === step.id && requirement.at === 'CLOCK' && requirement.evaluation_point === 'PROPOSE_AND_DISPATCH' && requirement.freshness_seconds === '0', 'UNSUPPORTED_RELATION');
      check(vector ? ['AVAILABLE', 'ABSENT'].includes(requirement.expected_status) : id === gate.approval_requirement ? requirement.purpose === 'AUTHORITY' && requirement.expected_status === 'AVAILABLE' && requirement.record_id !== null : requirement.expected_status === 'ABSENT', 'UNSUPPORTED_RELATION');
    }
    if (vector) {
      const coordinator = declarations.get(gate.coordinator_requirement);
      check(ids.includes(gate.coordinator_requirement) && coordinator?.expected_status === 'AVAILABLE' && coordinator.provider === gate.fence_provider && coordinator.source === gate.fence_source, 'UNSUPPORTED_RELATION');
      for (const validity of gate.validity_requirements) {
        const requirement = declarations.get(validity.requirement_id);
        check(ids.includes(validity.requirement_id) && requirement?.expected_status === 'AVAILABLE', 'REFERENCE_INVALID');
        check(validity.not_before_field !== validity.not_after_field, 'REFERENCE_INVALID');
        for (const name of [validity.not_before_field, validity.not_after_field]) {
          const field = requirement?.fields.find((row: Row) => row.name === name);
          check(field, 'REFERENCE_INVALID'); if (field) typeCheck(types.get(field.type_ref)?.kind === 'INSTANT', 'TYPE_INVALID');
        }
      }
      for (const decision of decisionRequirements(request).filter(row => row.step === step.id)) {
        const record = declarations.get(decision.record_requirement_id), validity = gate.validity_requirements.find((row: Row) => row.requirement_id === decision.record_requirement_id);
        check(ids.includes(decision.record_requirement_id) && validity, 'REFERENCE_INVALID');
        if (record && validity) for (const end of ['not_before_field', 'not_after_field']) {
          check(record.relations.some((relation: Row) => {
            const matches = (a: Row, b: Row): boolean => a?.kind === 'OBSERVATION_FIELD' && a.requirement_id === record.id && a.field === validity[end] && b?.kind === 'DECISION_FIELD' && b.requirement_id === decision.id && b.field === decision.validity_fields[end];
            return relation.kind === 'EQUALS' && (matches(relation.left, relation.right) || matches(relation.right, relation.left));
          }), 'UNSUPPORTED_RELATION');
        }
      }
    }
  }
}

export function sourceSubject(request: Row, requirement: Row): string {
  const selector = requirement.subject;
  const subject = typeof selector === 'string' ? selector : selector.kind === 'PROPOSAL_FIELD' ? request.proposal.fields.find((row: Row) => row.name === selector.field)?.value.value : request.proposal.executor[selector.member];
  if (typeof subject !== 'string' || !subject.length) throw new AdmissionError('BINDING_MISMATCH');
  return subject;
}

export function deriveSourceQueries(request: Row): Row[] {
  const fields = new Map<string, TypedValue>(request.proposal.fields.map((row: Row) => [row.name, row.value]));
  return requirements(request).filter(row => row.step === request.proposal.step && ((request.evaluation_point ?? 'PROPOSE') !== 'DISPATCH' || point(row) === 'PROPOSE_AND_DISPATCH')).map(requirement => {
    const subject = sourceSubject(request, requirement);
    const query: Row = { requirement_id: requirement.id, step: requirement.step, at: requirement.at === 'CLOCK' ? request.clock.instant : requirement.at, provider: requirement.provider, source: requirement.source, record_type: requirement.record_type, subject, record_id: requirement.record_id, purpose: requirement.purpose, freshness_seconds: requirement.freshness_seconds, expected_status: requirement.expected_status, fields: requirement.fields, relations: requirement.relations };
    if (requirement.evaluation_point !== undefined) query.evaluation_point = requirement.evaluation_point;
    if (requirement.key_projection !== undefined) query.key = requirement.key_projection.map((row: Row) => ({ name: keyName(row), value: fields.get(row.field) })).sort((a: Row, b: Row) => byteCompare(a.name, b.name));
    return query;
  });
}

export function sourcePolicyFailures(request: Row, types: Types, queries: Row[], groups: Map<string, Map<string, Row>>): Row[] {
  const declarations = new Map<string, Row>(requirements(request).map(row => [row.id, row]));
  const byRequirement = new Map<string, Row>();
  const queryByRequirement = new Map<string, Row>(queries.map(row => [row.requirement_id, row]));
  for (const query of queries) {
    const rows = [...(groups.get(digest('authority-query', query))?.values() ?? [])];
    if (rows.length === 1) byRequirement.set(query.requirement_id, rows[0]);
  }
  const failures: Row[] = [];
  const fail = (requirement: Row, query: Row, reason: string): void => { failures.push({ requirement_ref: requirement.id, at: query.at, reason }); };
  function actualField(observation: Row | undefined, requirement: Row, name: string): TypedValue | undefined {
    if (!observation || observation.status !== 'AVAILABLE') return undefined;
    const declaration = requirement.fields.find((row: Row) => row.name === name), fields = observation.fields.filter((row: Row) => row.name === name);
    return declaration && fields.length === 1 && fields[0].value.type_ref === declaration.type_ref ? fields[0].value : undefined;
  }
  function fieldsMatch(observation: Row, requirement: Row): boolean {
    return observation.fields.length === requirement.fields.length && new Set(observation.fields.map((row: Row) => row.name)).size === observation.fields.length && requirement.fields.every((row: Row) => actualField(observation, requirement, row.name));
  }
  const dependencyUsability = new Map<string, boolean>();
  function usable(requirement: Row): Row | undefined {
    const observation = byRequirement.get(requirement.id), query = queryByRequirement.get(requirement.id);
    if (!observation || !query || observation.status !== 'AVAILABLE' || (requirement.record_id !== null && observation.provider_record_id !== requirement.record_id) || instant(observation.as_of) > instant(query.at) || instant(query.at) > instant(request.clock.instant) || instant(query.at) - instant(observation.as_of) > BigInt(requirement.freshness_seconds) * 1_000_000_000n) return undefined;
    if (!dependencyUsability.has(requirement.id)) dependencyUsability.set(requirement.id, fieldsMatch(observation, requirement) && same(observation.relations, requirement.relations) && requirement.relations.every((relation: Row) => relationHolds(relation, requirement)));
    return dependencyUsability.get(requirement.id) ? observation : undefined;
  }
  function resolve(selector: Row | string, requirement: Row): TypedValue | undefined {
    if (typeof selector === 'string') return actualField(byRequirement.get(requirement.id), requirement, selector);
    if (selector.kind === 'LITERAL') return selector.value;
    if (selector.kind === 'PROPOSAL_FIELD') return request.proposal.fields.find((row: Row) => row.name === selector.field)?.value;
    if (selector.kind === 'EXECUTOR') return { type_ref: selector.type_ref, value: request.proposal.executor[selector.member] };
    if (selector.kind === 'CLOCK') return { type_ref: selector.type_ref, value: request.clock.instant };
    if (['DECISION_ACT', 'DECISION_FIELD', 'DECISION_BASIS'].includes(selector.kind)) return decisionOperand(request, selector) as TypedValue | undefined;
    if (selector.kind === 'ACT') {
      const acts = request.acts.filter((row: Row) => row.kind === selector.act_kind);
      return acts.length === 1 ? { type_ref: selector.type_ref, value: acts[0][selector.member] } : undefined;
    }
    const target = declarations.get(selector.requirement_id);
    if (!target) return undefined;
    const observation = target.id === requirement.id ? byRequirement.get(target.id) : usable(target);
    if (!observation) return undefined;
    if (observation.status !== 'AVAILABLE') return undefined;
    return selector.kind === 'OBSERVATION_ID' ? { type_ref: selector.type_ref, value: observation.provider_record_id } : actualField(observation, target, selector.field);
  }
  function relationHolds(relation: Row, requirement: Row): boolean {
    const left = resolve(relation.left, requirement), right = resolve(relation.right, requirement);
    if (!left || !right || left.type_ref !== right.type_ref) return false;
    try { typed(left, types); typed(right, types); } catch (error) { if (!(error instanceof AdmissionError)) throw error; return false; }
    if (relation.kind === 'EQUALS') return same(left, right);
    if (relation.kind === 'NOT_EQUALS') return !same(left, right);
    const a = instant(left.value as string), b = instant(right.value as string);
    if (relation.kind === 'ELAPSED_LTE') return b >= a && b - a <= BigInt(relation.maximum_seconds) * 1_000_000_000n;
    return relation.kind === 'BEFORE' ? a < b : relation.kind === 'AFTER' ? a > b : relation.kind === 'AT_OR_BEFORE' ? a <= b : a >= b;
  }
  for (const query of queries) {
    const requirement = declarations.get(query.requirement_id)!, rows = [...(groups.get(digest('authority-query', query))?.values() ?? [])];
    if (rows.length !== 1) { fail(requirement, query, 'SOURCE_OBSERVATION_CONFLICT'); continue; }
    const observation = rows[0];
    if (!['AVAILABLE', 'ABSENT'].includes(observation.status)) { fail(requirement, query, 'SOURCE_OBSERVATION_' + observation.status); continue; }
    if (observation.status !== requirement.expected_status || (observation.status === 'AVAILABLE' && requirement.record_id !== null && observation.provider_record_id !== requirement.record_id)) fail(requirement, query, 'SOURCE_OBSERVATION_BINDING');
    if (instant(observation.as_of) > instant(query.at) || instant(query.at) > instant(request.clock.instant)) fail(requirement, query, 'SOURCE_OBSERVATION_TIME');
    if (instant(query.at) - instant(observation.as_of) > BigInt(requirement.freshness_seconds) * 1_000_000_000n) fail(requirement, query, 'SOURCE_OBSERVATION_STALE');
    if (observation.status !== 'AVAILABLE') continue;
    if (!fieldsMatch(observation, requirement)) fail(requirement, query, 'SOURCE_OBSERVATION_FIELDS');
    const gate = request.work_class.steps.find((row: Row) => row.id === requirement.step)?.dispatch_gate;
    const validity = gate?.kind === 'SOURCE_REQUIREMENTS' ? gate.validity_requirements.find((row: Row) => row.requirement_id === requirement.id) : undefined;
    if (validity) {
      const before = actualField(observation, requirement, validity.not_before_field), after = actualField(observation, requirement, validity.not_after_field);
      if (!before || !after || instant(before.value as string) >= instant(after.value as string) || instant(before.value as string) > instant(request.clock.instant) || instant(request.clock.instant) >= instant(after.value as string)) fail(requirement, query, 'SOURCE_OBSERVATION_TIME');
    }
    let relationsHold = same(observation.relations, requirement.relations);
    for (const relation of requirement.relations) {
      relationsHold = relationHolds(relation, requirement) && relationsHold;
    }
    if (!relationsHold) fail(requirement, query, 'SOURCE_OBSERVATION_RELATIONS');
  }
  return [...new Map(failures.map(row => [canonical(row), row])).values()];
}
