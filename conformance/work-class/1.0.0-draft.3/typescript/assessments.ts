import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { instant } from './time.ts';
import { ordered, same, setOrder, typed } from './values.ts';
import type { RecordValue as Row, Types } from './values.ts';

type Check = (condition: unknown, code: string) => void;
const members = ['SUBJECT_DIGEST', 'ASSESSMENT_DIGEST', 'REVIEW_DIGEST', 'REVIEW_IDENTITY'];
const textKinds = ['IDENTITY', 'STRING'];
export const assessmentRequirements = (input: Row): Row[] => input.envelope.assessment_requirements ?? [];
const sourceRequirements = (input: Row): Row[] => input.envelope.source_observation_requirements ?? [];
const selected = (input: Row): Row | undefined => assessmentRequirements(input).find(row => row.step === input.proposal.step);
const basisFor = (input: Row, id: string): Row | undefined => input.assessment_bases?.find((row: Row) => row.requirement_id === id);
const decisionFor = (input: Row, id: string): Row | undefined => input.envelope.decision_requirements?.find((row: Row) => row.id === id);
const recordFor = (input: Row, id: string): Row | undefined => sourceRequirements(input).find(row => row.id === id);
const computedBindings = (decision: Row): Row[] => decision.context_bindings.filter((row: Row) => row.value.kind === 'ASSESSMENT');
const namedFields = (fields: Row[]): Row[] => [...fields].sort((a, b) => byteCompare(a.name, b.name));

export function assessmentLinkedDecision(input: Row, decision: Row): boolean {
  return assessmentRequirements(input).some(row => row.review_decision_requirement_id === decision.id && row.step === decision.step && input.envelope.gate.kind === 'DECIDE' && input.envelope.gate.decision_requirement === decision.id);
}

function equality(relation: Row, left: (value: Row) => boolean, right: (value: Row) => boolean): boolean {
  return relation.kind === 'EQUALS' && ((left(relation.left) && right(relation.right)) || (left(relation.right) && right(relation.left)));
}

export function admitAssessmentDeclarations(input: Row, types: Types, check: Check, typeCheck: Check): void {
  const declarations = assessmentRequirements(input);
  typeCheck(ordered(declarations.map(row => row.id)), 'INPUT_INVALID');
  for (const decision of input.envelope.decision_requirements ?? []) for (const binding of computedBindings(decision)) {
    const declaration = declarations.find(row => row.id === binding.value.requirement_id);
    check(declaration, 'REFERENCE_INVALID');
    if (declaration && decisionFor(input, declaration.review_decision_requirement_id) && input.work_class.steps.some((row: Row) => row.id === declaration.step)) check(assessmentLinkedDecision(input, decision) && declaration.review_decision_requirement_id === decision.id, 'UNSUPPORTED_RELATION');
    check(types.has(binding.value.type_ref), 'REFERENCE_INVALID');
    if (types.has(binding.value.type_ref)) typeCheck(textKinds.includes(types.get(binding.value.type_ref)!.kind), 'TYPE_INVALID');
  }
  for (const declaration of declarations) {
    const step = input.work_class.steps.find((row: Row) => row.id === declaration.step), decision = decisionFor(input, declaration.review_decision_requirement_id);
    const { rubric, sources } = declaration;
    check(step && decision && input.envelope.operations.some((row: Row) => row.step === declaration.step), 'REFERENCE_INVALID');
    if (step && decision) check(assessmentLinkedDecision(input, decision), 'UNSUPPORTED_RELATION');
    typeCheck(ordered(rubric.obligations.map((row: Row) => row.id)) && ordered(rubric.criteria.map((row: Row) => row.id)) && ordered(sources.context) && ordered(sources.blockers), 'INPUT_INVALID');
    const obligations = new Set<string>(rubric.obligations.map((row: Row) => row.id)), covered = new Set<string>();
    for (const obligation of rubric.obligations) {
      const original = input.source.obligations.find((row: Row) => row.id === obligation.id);
      check(original, 'REFERENCE_INVALID');
      if (original) check(same(original, obligation), 'DEPENDENCY_MISMATCH');
    }
    for (const criterion of rubric.criteria) {
      typeCheck(ordered(criterion.obligation_ids), 'INPUT_INVALID');
      for (const id of criterion.obligation_ids) { check(obligations.has(id), 'REFERENCE_INVALID'); covered.add(id); }
    }
    check([...obligations].every(id => covered.has(id)), 'REFERENCE_INVALID');
    if (!step || !decision) continue;
    const bindings = computedBindings(decision);
    const resolvedBindings = bindings.every(binding => declarations.some(row => row.id === binding.value.requirement_id));
    if (resolvedBindings) check(bindings.length === members.length && members.every(member => bindings.filter(row => row.value.member === member).length === 1), 'UNSUPPORTED_RELATION');
    for (const binding of bindings) if (declarations.some(row => row.id === binding.value.requirement_id)) check(binding.value.requirement_id === declaration.id, 'UNSUPPORTED_RELATION');
    if (resolvedBindings) check(bindings.find(row => row.value.member === 'REVIEW_IDENTITY')?.field === decision.identity_field, 'UNSUPPORTED_RELATION');
    const approval = recordFor(input, decision.record_requirement_id);
    if (approval && resolvedBindings) check(approval.record_id === null, 'UNSUPPORTED_RELATION');
    const singular = [sources.content, ...['context_selection', 'rubric', 'evaluator', 'assessment', 'selection', 'effectiveness'].map(role => sources[role].requirement_id)], roles = [...singular, ...sources.context, decision.record_requirement_id];
    check(new Set(roles).size === roles.length && sources.blockers.every((id: string) => !roles.includes(id)), 'UNSUPPORTED_RELATION');
    const gate = step.dispatch_gate;
    check(gate?.kind === 'SOURCE_REQUIREMENTS', 'UNSUPPORTED_RELATION');
    for (const id of [...roles, ...sources.blockers]) {
      const record = recordFor(input, id);
      check(record, 'REFERENCE_INVALID');
      if (record) check(record.step === step.id && (sources.blockers.includes(id) || record.expected_status === 'AVAILABLE'), 'UNSUPPORTED_RELATION');
    }
    for (const record of sourceRequirements(input).filter(row => row.step === step.id)) check(gate?.kind === 'SOURCE_REQUIREMENTS' && gate.requirements.includes(record.id) && record.at === 'CLOCK' && record.evaluation_point === 'PROPOSE_AND_DISPATCH' && record.freshness_seconds === '0', 'UNSUPPORTED_RELATION');
    if (gate?.kind === 'SOURCE_REQUIREMENTS') check(gate.requirements.length + (input.envelope.holdings_requirements ?? []).filter((row: Row) => row.step === step.id).length <= 64, 'LIMIT_EXCEEDED');
    const content = recordFor(input, sources.content);
    if (content) {
      check(same(content.fields, step.fields), 'REFERENCE_INVALID');
      for (const actual of content.fields) {
        const native = step.fields.find((row: Row) => row.name === actual.name);
        if (native && types.has(native.type_ref) && types.has(actual.type_ref)) typeCheck(native.type_ref === actual.type_ref, 'TYPE_INVALID');
      }
      for (const field of step.fields.filter((field: Row) => content.fields.some((actual: Row) => actual.name === field.name))) check(content.relations.some((relation: Row) => equality(relation, value => value?.kind === 'OBSERVATION_FIELD' && value.requirement_id === content.id && value.field === field.name, value => value?.kind === 'PROPOSAL_FIELD' && value.field === field.name)), 'UNSUPPORTED_RELATION');
    }
    for (const id of [sources.content, ...sources.context]) {
      const record = recordFor(input, id);
      const allowed = id === sources.content ? [id, ...sources.context] : sources.context;
      for (const relation of record?.relations ?? []) for (const operand of [relation.left, relation.right]) {
        if (typeof operand === 'string') continue;
        check(['PROPOSAL_FIELD', 'LITERAL', 'EXECUTOR', 'CLOCK'].includes(operand.kind) || ['OBSERVATION_FIELD', 'OBSERVATION_ID'].includes(operand.kind) && allowed.includes(operand.requirement_id), 'UNSUPPORTED_RELATION');
      }
    }
    const field = (role: Row, name: string, kind: string[] = textKinds): Row | undefined => {
      const record = recordFor(input, role.requirement_id), value = record?.fields.find((row: Row) => row.name === role[name]);
      check(value && types.has(value.type_ref), 'REFERENCE_INVALID');
      if (value && types.has(value.type_ref)) typeCheck(kind.includes(types.get(value.type_ref)!.kind), 'TYPE_INVALID');
      return value;
    };
    for (const role of ['context_selection', 'rubric', 'assessment', 'selection']) field(sources[role], 'digest_field');
    for (const name of ['provider_field', 'model_field', 'version_field']) field(sources.evaluator, name);
    check(new Set(['provider_field', 'model_field', 'version_field'].map(name => sources.evaluator[name])).size === 3, 'UNSUPPORTED_RELATION');
    field(sources.selection, 'identity_field'); field(sources.effectiveness, 'identity_field'); field(sources.effectiveness, 'effective_field', ['BOOLEAN']);
    check(sources.selection.identity_field !== sources.selection.digest_field, 'UNSUPPORTED_RELATION');
    check(sources.effectiveness.identity_field !== sources.effectiveness.effective_field, 'UNSUPPORTED_RELATION');
    const digestBinding = bindings.find(row => row.value.member === 'ASSESSMENT_DIGEST');
    for (const role of [sources.assessment, sources.selection]) {
      const record = recordFor(input, role.requirement_id);
      if (record && resolvedBindings) check(digestBinding && record.relations.some((relation: Row) => equality(relation, value => value?.kind === 'OBSERVATION_FIELD' && value.requirement_id === record.id && value.field === role.digest_field, value => value?.kind === 'DECISION_FIELD' && value.requirement_id === decision.id && value.field === digestBinding.field)), 'UNSUPPORTED_RELATION');
    }
  }
}

export function admitAssessmentInputs(input: Row, types: Types, check: Check, typeCheck: Check): void {
  const declaration = selected(input), rows = input.assessment_bases ?? [];
  typeCheck(ordered(rows.map((row: Row) => row.requirement_id)), 'INPUT_INVALID');
  check(rows.every((row: Row) => declaration?.id === row.requirement_id), 'DEPENDENCY_MISMATCH');
  check(!declaration || rows.some((row: Row) => row.requirement_id === declaration.id), 'EVIDENCE_UNAVAILABLE');
  if (input.assessment_bases !== undefined || input.envelope.assessment_requirements !== undefined) check(Buffer.byteLength(canonical(input)) <= 1048576, 'LIMIT_EXCEEDED');
  for (const basis of rows) {
    typeCheck(ordered(basis.supporting_context.map((row: Row) => row.requirement_id)) && ordered(basis.assessment.criteria.map((row: Row) => row.id)) && ordered(basis.review.criteria.map((row: Row) => row.id)), 'INPUT_INVALID');
    try { instant(basis.assessment.assessed_at); } catch { typeCheck(false, 'INPUT_INVALID'); }
    for (const criterion of basis.assessment.criteria) {
      typeCheck(setOrder(criterion.citations), 'INPUT_INVALID');
      typeCheck(criterion.escalation.required ? criterion.escalation.reason !== null : criterion.escalation.reason === null, 'INPUT_INVALID');
    }
    for (const criterion of basis.review.criteria) typeCheck(setOrder(criterion.citations), 'INPUT_INVALID');
    for (const snapshot of basis.supporting_context) {
      typeCheck(ordered(snapshot.fields.map((row: Row) => row.name)), 'INPUT_INVALID');
      for (const field of snapshot.fields) {
        check(types.has(field.value.type_ref), 'REFERENCE_INVALID');
        if (types.has(field.value.type_ref)) {
          try { typed(field.value, types); } catch (error) { if (!(error instanceof AdmissionError)) throw error; typeCheck(false, error.code); }
          if (['INTEGER', 'DECIMAL'].includes(types.get(field.value.type_ref)!.kind) && typeof field.value.value === 'string') check(field.value.value.replace(/[-.]/g, '').length <= 128, 'LIMIT_EXCEEDED');
        }
      }
    }
    if (!declaration || declaration.id !== basis.requirement_id) continue;
    check(declaration.sources.context.every((id: string) => basis.supporting_context.some((row: Row) => row.requirement_id === id)), 'EVIDENCE_UNAVAILABLE');
    check(basis.supporting_context.every((row: Row) => declaration.sources.context.includes(row.requirement_id)), 'DEPENDENCY_MISMATCH');
    for (const snapshot of basis.supporting_context) {
      const record = recordFor(input, snapshot.requirement_id);
      if (!record) { check(false, 'REFERENCE_INVALID'); continue; }
      check(record.fields.every((field: Row) => snapshot.fields.some((row: Row) => row.name === field.name)), 'EVIDENCE_UNAVAILABLE');
      check(snapshot.fields.every((row: Row) => record.fields.some((field: Row) => field.name === row.name)), 'REFERENCE_INVALID');
      for (const row of snapshot.fields) {
        const field = record.fields.find((field: Row) => field.name === row.name);
        if (field && types.has(field.type_ref) && types.has(row.value.type_ref)) typeCheck(field.type_ref === row.value.type_ref, 'TYPE_INVALID');
      }
    }
    for (const criteria of [basis.assessment.criteria, basis.review.criteria]) {
      check(declaration.rubric.criteria.every((required: Row) => criteria.some((row: Row) => row.id === required.id)), 'EVIDENCE_UNAVAILABLE');
      check(criteria.every((row: Row) => declaration.rubric.criteria.some((required: Row) => required.id === row.id)), 'REFERENCE_INVALID');
      for (const criterion of criteria) for (const citation of criterion.citations) {
        if (citation.kind === 'PROPOSAL_FIELD') check(input.work_class.steps.find((row: Row) => row.id === declaration.step)?.fields.some((row: Row) => row.name === citation.field), 'REFERENCE_INVALID');
        else check(declaration.sources.context.includes(citation.requirement_id) && recordFor(input, citation.requirement_id)?.fields.some((row: Row) => row.name === citation.field), 'REFERENCE_INVALID');
      }
    }
  }
}

export function assessmentDigests(input: Row, declaration: Row, basis: Row): Row {
  const records = basis.supporting_context.map((row: Row) => {
    const record = recordFor(input, row.requirement_id)!;
    return { requirement_id: row.requirement_id, provider: record.provider, source: record.source, record_type: record.record_type, provider_record_id: row.provider_record_id, provider_revision: row.provider_revision, fields: row.fields };
  });
  const context_digest = digest('content-assessment-context', { types: input.work_class.types, records }), rubric_digest = digest('content-assessment-rubric', declaration.rubric), proposal = input.proposal;
  const subject_digest = digest('content-assessment-subject', { principal: proposal.executor.principal, work_class_digest: proposal.work_class_digest, instance: proposal.instance, occurrence: proposal.occurrence, step: proposal.step, interface: proposal.interface, operation: proposal.operation, fields: proposal.fields, context_digest, rubric_digest, evaluator: declaration.evaluator });
  return { context_digest, rubric_digest, subject_digest, assessment_digest: digest('content-assessment', basis.assessment), review_digest: digest('content-assessment-review', basis.review) };
}

export function assessmentValue(input: Row, selector: Row): Row | undefined {
  const declaration = assessmentRequirements(input).find(row => row.id === selector.requirement_id && row.step === input.proposal.step), basis = declaration && basisFor(input, declaration.id);
  if (!declaration || !basis) return undefined;
  const values = assessmentDigests(input, declaration, basis), decision = decisionFor(input, declaration.review_decision_requirement_id), record = decision && recordFor(input, decision.record_requirement_id);
  if (!record) return undefined;
  const keys: Record<string, string> = { SUBJECT_DIGEST: 'subject_digest', ASSESSMENT_DIGEST: 'assessment_digest', REVIEW_DIGEST: 'review_digest' };
  const value = selector.member === 'REVIEW_IDENTITY' ? canonical({ provider: record.provider, source: record.source, record_type: record.record_type, provider_record_id: basis.review.id }) : values[keys[selector.member]];
  return { type_ref: selector.type_ref, value };
}

export function bindAssessmentInputs(input: Row, act: Row | undefined, check: Check): void {
  const declaration = selected(input), basis = declaration && basisFor(input, declaration.id);
  if (!declaration || !basis) return;
  const values = assessmentDigests(input, declaration, basis), assessment = basis.assessment, record = recordFor(input, declaration.sources.assessment.requirement_id)!;
  check(assessment.subject_digest === values.subject_digest && assessment.context_digest === values.context_digest && assessment.rubric_digest === values.rubric_digest && same(assessment.evaluator, declaration.evaluator), 'BINDING_MISMATCH');
  check(assessment.provider === record.provider && assessment.source === record.source && assessment.record_type === record.record_type && basis.review.assessment_digest === values.assessment_digest, 'BINDING_MISMATCH');
  if (act) check(basis.review.id === act.id, 'BINDING_MISMATCH');
  for (const row of assessment.criteria) {
    const criterion = declaration.rubric.criteria.find((criterion: Row) => criterion.id === row.id)!, review = basis.review.criteria.find((review: Row) => review.id === row.id)!;
    check(row.citations.every((citation: Row) => criterion.citation_policy === 'ANY' || citation.kind === (criterion.citation_policy === 'CONTEXT' ? 'CONTEXT_FIELD' : 'PROPOSAL_FIELD')), 'BINDING_MISMATCH');
    check(row.verdict === 'PASS' && !row.escalation.required && review.disposition === 'SATISFIED' || review.reason !== null, 'BINDING_MISMATCH');
  }
}

export function assessmentChronology(input: Row, act: Row | undefined, check: Check): void {
  const declaration = selected(input), basis = declaration && basisFor(input, declaration.id);
  if (basis && act) check(instant(basis.assessment.assessed_at) <= instant(act.occurred_at), 'BINDING_MISMATCH');
}

export function assessmentChecks(input: Row, queries: Row[], groups: Map<string, Map<string, Row>>): Row[] {
  const declaration = selected(input), basis = declaration && basisFor(input, declaration.id);
  if (!declaration || !basis) return [];
  const values = assessmentDigests(input, declaration, basis), failures = new Set<string>(), sources = declaration.sources;
  const usable = (id: string): Row | undefined => {
    const record = recordFor(input, id)!, query = queries.find((row: Row) => row.requirement_id === id);
    if (!query) return undefined;
    const rows = [...(groups.get(digest('authority-query', query))?.values() ?? [])];
    if (rows.length !== 1) return undefined;
    const row = rows[0];
    if (!same(row.query, query) || row.status !== 'AVAILABLE' || record.expected_status !== 'AVAILABLE' || record.record_id !== null && row.provider_record_id !== record.record_id || instant(row.as_of) > instant(query.at) || instant(query.at) > instant(input.clock.instant) || instant(query.at) - instant(row.as_of) > BigInt(record.freshness_seconds) * 1000000000n || !same(row.relations, record.relations)) return undefined;
    if (row.fields.length !== record.fields.length || new Set(row.fields.map((field: Row) => field.name)).size !== row.fields.length || !record.fields.every((field: Row) => row.fields.some((actual: Row) => actual.name === field.name && actual.value.type_ref === field.type_ref))) return undefined;
    const gate = input.work_class.steps.find((step: Row) => step.id === record.step)?.dispatch_gate;
    const validity = gate?.kind === 'SOURCE_REQUIREMENTS' ? gate.validity_requirements.find((value: Row) => value.requirement_id === id) : undefined;
    if (validity) {
      const before = row.fields.find((field: Row) => field.name === validity.not_before_field)!.value.value, after = row.fields.find((field: Row) => field.name === validity.not_after_field)!.value.value;
      if (instant(before) >= instant(after) || instant(before) > instant(input.clock.instant) || instant(input.clock.instant) >= instant(after)) return undefined;
    }
    return row;
  };
  const changed = (condition: unknown): void => { if (!condition) failures.add('ASSESSMENT_DEPENDENCY_CHANGED'); };
  const field = (row: Row, name: string): unknown => row.fields.find((field: Row) => field.name === name)!.value.value;
  const matches = (role: Row, expected: Row): void => {
    const row = usable(role.requirement_id);
    if (row) for (const [name, value] of Object.entries(expected)) changed(same(field(row, role[name]), value));
  };
  const content = usable(sources.content);
  if (content) changed(same(namedFields(content.fields), namedFields(input.proposal.fields)));
  for (const snapshot of basis.supporting_context) {
    const row = usable(snapshot.requirement_id);
    if (row) changed(row.provider_record_id === snapshot.provider_record_id && row.revision === snapshot.provider_revision && same(namedFields(row.fields), snapshot.fields));
  }
  matches(sources.context_selection, { digest_field: values.context_digest });
  matches(sources.rubric, { digest_field: values.rubric_digest });
  matches(sources.evaluator, { provider_field: declaration.evaluator.provider, model_field: declaration.evaluator.model, version_field: declaration.evaluator.version });
  const issuance = usable(sources.assessment.requirement_id), assessment = basis.assessment;
  if (issuance) changed(issuance.provider_record_id === assessment.id && issuance.revision === assessment.revision);
  matches(sources.assessment, { digest_field: values.assessment_digest });
  const identity = canonical({ provider: assessment.provider, source: assessment.source, record_type: assessment.record_type, provider_record_id: assessment.id });
  matches(sources.selection, { identity_field: identity, digest_field: values.assessment_digest });
  matches(sources.effectiveness, { identity_field: identity, effective_field: true });
  if (basis.review.decision !== 'APPROVE' || basis.review.criteria.some((row: Row) => row.disposition !== 'SATISFIED')) failures.add('ASSESSMENT_NOT_SATISFIED');
  const row = { subject_digest: values.assessment_digest, requirement_ref: declaration.id };
  return failures.size ? [...failures].map(reason => ({ ...row, reason })) : [row];
}
