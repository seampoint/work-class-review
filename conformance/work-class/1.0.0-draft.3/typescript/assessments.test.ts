import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { evaluateAuthority } from './authority.ts';
import { admitAssessmentDeclarations, admitAssessmentInputs, assessmentChecks, assessmentChronology, assessmentDigests, assessmentValue, bindAssessmentInputs } from './assessments.ts';
import { immutableAuthority } from './dispatch-authority.ts';
import { step } from './lifecycle.ts';
import { independentCorrection } from './source-corrections.ts';
import { sourcePolicyFailures } from './source-observations.ts';
import { selectedCandidate } from './schema.ts';
import type { RecordValue as Row, Types } from './values.ts';

const at = '2026-10-08T12:00:00Z';
const clone = <T>(value: T): T => structuredClone(value);
const sort = (rows: Row[], key = 'id'): Row[] => rows.sort((a, b) => byteCompare(a[key], b[key]));
const value = (type_ref: string, value: string | boolean): Row => ({ type_ref, value });
const field = (name: string, type_ref: string, scalar: string | boolean): Row => ({ name, value: value(type_ref, scalar) });
const typesOf = (input: Row): Types => new Map(input.work_class.types.map((row: Row) => [row.id, row]));

// This fixture exercises profile helpers under ordinary authority admission premises.
function fixture(): Row {
  const types = sort([{ id: 'Boolean', kind: 'BOOLEAN', nonnegative: false, unit: null }, { id: 'Hash', kind: 'STRING', nonnegative: false, unit: null }, { id: 'Identity', kind: 'IDENTITY', nonnegative: false, unit: null }, { id: 'Instant', kind: 'INSTANT', nonnegative: false, unit: null }, { id: 'Number', kind: 'INTEGER', nonnegative: true, unit: null }, { id: 'Text', kind: 'STRING', nonnegative: false, unit: null }]);
  const fields = [field('body', 'Text', 'Please explain these transfers.'), field('recipient', 'Identity', 'customer-074')];
  const record = (id: string, declarations: Row[], relations: Row[] = []): Row => ({ id, step: 'send', purpose: 'AUTHORITY', provider: id + '-provider', source: id + '-source', record_type: id + '-type', subject: 'message-074', record_id: null, at: 'CLOCK', freshness_seconds: '0', expected_status: 'AVAILABLE', fields: declarations, relations, evaluation_point: 'PROPOSE_AND_DISPATCH' });
  const declaration: Row = { id: 'assessment', step: 'send', review_decision_requirement_id: 'human', rubric: { id: 'rubric', revision: '1', obligations: [{ id: 'facts', text: 'Use the selected facts.' }, { id: 'tone', text: 'Use neutral language.' }], criteria: [{ id: 'facts', obligation_ids: ['facts'], citation_policy: 'CONTEXT' }, { id: 'tone', obligation_ids: ['tone'], citation_policy: 'PROPOSAL' }] }, evaluator: { provider: 'model-provider', model: 'model', version: '1' }, sources: { content: 'content', context: ['facts'], context_selection: { requirement_id: 'context-selection', digest_field: 'digest' }, rubric: { requirement_id: 'rubric', digest_field: 'digest' }, evaluator: { requirement_id: 'evaluator', provider_field: 'provider', model_field: 'model', version_field: 'version' }, assessment: { requirement_id: 'issuance', digest_field: 'digest' }, selection: { requirement_id: 'selection', identity_field: 'identity', digest_field: 'digest' }, effectiveness: { requirement_id: 'effectiveness', identity_field: 'identity', effective_field: 'effective' }, blockers: [] } };
  const digestRelation = (id: string): Row => ({ id: 'digest', kind: 'EQUALS', left: { kind: 'OBSERVATION_FIELD', requirement_id: id, field: 'digest' }, right: { kind: 'DECISION_FIELD', requirement_id: 'human', field: 'assessment_digest' } });
  const records = sort([
    record('content', fields.map(row => ({ name: row.name, type_ref: row.value.type_ref })), fields.map(row => ({ id: row.name, kind: 'EQUALS', left: { kind: 'OBSERVATION_FIELD', requirement_id: 'content', field: row.name }, right: { kind: 'PROPOSAL_FIELD', field: row.name } }))),
    record('facts', [{ name: 'amount', type_ref: 'Number' }, { name: 'customer', type_ref: 'Identity' }]),
    record('context-selection', [{ name: 'digest', type_ref: 'Hash' }]), record('rubric', [{ name: 'digest', type_ref: 'Hash' }]),
    record('evaluator', [{ name: 'model', type_ref: 'Text' }, { name: 'provider', type_ref: 'Text' }, { name: 'version', type_ref: 'Text' }]),
    record('issuance', [{ name: 'digest', type_ref: 'Hash' }], [digestRelation('issuance')]),
    record('selection', [{ name: 'digest', type_ref: 'Hash' }, { name: 'identity', type_ref: 'Identity' }], [digestRelation('selection')]),
    record('effectiveness', [{ name: 'effective', type_ref: 'Boolean' }, { name: 'identity', type_ref: 'Identity' }]),
    record('approval', []),
  ]);
  const bindings = sort(['SUBJECT_DIGEST', 'ASSESSMENT_DIGEST', 'REVIEW_DIGEST', 'REVIEW_IDENTITY'].map(member => ({ field: member.toLowerCase(), value: { kind: 'ASSESSMENT', requirement_id: declaration.id, member, type_ref: member === 'REVIEW_IDENTITY' ? 'Identity' : 'Hash' } })), 'field');
  const input: Row = { source: { id: 'source', revision: '1', obligations: clone(declaration.rubric.obligations) }, work_class: { id: 'message', revision: '1', types, steps: [{ id: 'send', fields: fields.map(row => ({ name: row.name, type_ref: row.value.type_ref })), dispatch_gate: { kind: 'SOURCE_REQUIREMENTS', requirements: records.map(row => row.id), validity_requirements: [] } }] }, envelope: { operations: [{ step: 'send', interface: 'messages', operation: 'send' }], assessment_requirements: [declaration], decision_requirements: [{ id: 'human', step: 'send', identity_field: 'review_identity', record_requirement_id: 'approval', context_bindings: bindings }], source_observation_requirements: records, gate: { kind: 'DECIDE', decision_requirement: 'human' } }, proposal: { executor: { principal: 'bank' }, work_class_digest: digest('test-work-class', {}), instance: 'instance-1', occurrence: 'occurrence-1', step: 'send', interface: 'messages', operation: 'send', fields }, clock: { status: 'AVAILABLE', instant: at }, assessment_bases: [] };
  const snapshots = [{ requirement_id: 'facts', provider_record_id: 'facts-1', provider_revision: '1', fields: [field('amount', 'Number', '84000'), field('customer', 'Identity', 'customer-074')] }];
  const contextRecords = snapshots.map(row => { const declaration = records.find(record => record.id === row.requirement_id)!; return { requirement_id: row.requirement_id, provider: declaration.provider, source: declaration.source, record_type: declaration.record_type, provider_record_id: row.provider_record_id, provider_revision: row.provider_revision, fields: row.fields }; });
  const contextDigest = digest('content-assessment-context', { types, records: contextRecords }), rubricDigest = digest('content-assessment-rubric', declaration.rubric);
  const subjectDigest = digest('content-assessment-subject', { principal: 'bank', work_class_digest: input.proposal.work_class_digest, instance: 'instance-1', occurrence: 'occurrence-1', step: 'send', interface: 'messages', operation: 'send', fields, context_digest: contextDigest, rubric_digest: rubricDigest, evaluator: declaration.evaluator });
  const issuance = records.find(row => row.id === 'issuance')!;
  const assessment = { provider: issuance.provider, source: issuance.source, record_type: issuance.record_type, id: 'assessment-1', revision: '1', subject_digest: subjectDigest, context_digest: contextDigest, rubric_digest: rubricDigest, evaluator: clone(declaration.evaluator), assessed_at: '2026-10-08T11:58:00Z', criteria: [{ id: 'facts', verdict: 'PASS', explanation: 'Grounded.', escalation: { required: false, reason: null }, citations: [{ kind: 'CONTEXT_FIELD', requirement_id: 'facts', field: 'amount' }] }, { id: 'tone', verdict: 'PASS', explanation: 'Neutral.', escalation: { required: false, reason: null }, citations: [{ kind: 'PROPOSAL_FIELD', field: 'body' }] }] };
  const review = { id: 'human-act-1', assessment_digest: digest('content-assessment', assessment), decision: 'APPROVE', criteria: [{ id: 'facts', disposition: 'SATISFIED', reason: null, citations: [] }, { id: 'tone', disposition: 'SATISFIED', reason: null, citations: [] }] };
  input.assessment_bases = [{ requirement_id: declaration.id, supporting_context: snapshots, assessment, review }];
  return input;
}

function admission(input: Row): { one: string[]; two: string[] } {
  const one = new Set<string>(), two = new Set<string>();
  const check = (set: Set<string>) => (condition: unknown, code: string): void => { if (!condition) set.add(code); };
  admitAssessmentDeclarations(input, typesOf(input), check(two), check(one));
  admitAssessmentInputs(input, typesOf(input), check(two), check(one));
  return { one: [...one].sort(), two: [...two].sort() };
}
function bindings(input: Row, act: Row = { id: 'human-act-1' }): string[] {
  const errors = new Set<string>();
  bindAssessmentInputs(input, act, (condition, code) => { if (!condition) errors.add(code); });
  return [...errors];
}
function current(input: Row): { queries: Row[]; rows: Row[]; groups: Map<string, Map<string, Row>> } {
  const basis = input.assessment_bases[0], assessment = basis.assessment, sources = input.envelope.assessment_requirements[0].sources;
  const identity = canonical({ provider: assessment.provider, source: assessment.source, record_type: assessment.record_type, provider_record_id: assessment.id });
  const actual: Record<string, Row[]> = {
    content: clone(input.proposal.fields), facts: clone(basis.supporting_context[0].fields),
    'context-selection': [field('digest', 'Hash', assessment.context_digest)], rubric: [field('digest', 'Hash', assessment.rubric_digest)],
    evaluator: [field('model', 'Text', 'model'), field('provider', 'Text', 'model-provider'), field('version', 'Text', '1')],
    issuance: [field('digest', 'Hash', digest('content-assessment', assessment))],
    selection: [field('digest', 'Hash', digest('content-assessment', assessment)), field('identity', 'Identity', identity)],
    effectiveness: [field('effective', 'Boolean', true), field('identity', 'Identity', identity)], approval: [],
  };
  const queries = input.envelope.source_observation_requirements.map((row: Row) => ({ requirement_id: row.id, step: row.step, at, provider: row.provider, source: row.source, record_type: row.record_type, subject: row.subject, record_id: row.record_id, purpose: row.purpose, freshness_seconds: row.freshness_seconds, expected_status: row.expected_status, fields: row.fields, relations: row.relations, evaluation_point: row.evaluation_point }));
  const rows = queries.map((query: Row) => ({ query, query_digest: digest('authority-query', query), status: 'AVAILABLE', as_of: at, revision: '1', provider_record_id: query.requirement_id === sources.assessment.requirement_id ? assessment.id : query.requirement_id === 'facts' ? 'facts-1' : query.requirement_id + '-1', fields: actual[query.requirement_id], relations: clone(query.relations) }));
  return { queries, rows, groups: groups(rows) };
}
function groups(rows: Row[]): Map<string, Map<string, Row>> {
  const result = new Map<string, Map<string, Row>>();
  for (const row of rows) { const values = result.get(row.query_digest) ?? new Map<string, Row>(); values.set(canonical(row), row); result.set(row.query_digest, values); }
  return result;
}

test('assessment helpers compute complete exact subject, context, assessment and review bodies', () => {
  const input = fixture(), declaration = input.envelope.assessment_requirements[0], basis = input.assessment_bases[0];
  assert.deepEqual(admission(input), { one: [], two: [] }); assert.deepEqual(bindings(input), []);
  assert.deepEqual(assessmentDigests(input, declaration, basis), { context_digest: basis.assessment.context_digest, rubric_digest: basis.assessment.rubric_digest, subject_digest: basis.assessment.subject_digest, assessment_digest: basis.review.assessment_digest, review_digest: digest('content-assessment-review', basis.review) });
  const selector = { kind: 'ASSESSMENT', requirement_id: declaration.id, member: 'REVIEW_IDENTITY', type_ref: 'Identity' };
  assert.deepEqual(assessmentValue(input, selector), value('Identity', canonical({ provider: 'approval-provider', source: 'approval-source', record_type: 'approval-type', provider_record_id: basis.review.id })));
});

test('assessment subject changes for exact native bytes, principal, occurrence and full context', () => {
  for (const change of [(input: Row) => { input.proposal.fields[0].value.value += ' '; }, (input: Row) => { input.proposal.executor.principal = 'other-bank'; }, (input: Row) => { input.proposal.occurrence = 'occurrence-2'; }, (input: Row) => { input.assessment_bases[0].supporting_context[0].fields[0].value.value = '84001'; }]) {
    const input = fixture(); change(input); assert.deepEqual(bindings(input), ['BINDING_MISMATCH']);
  }
});

test('assessment missing inventories, unknown citations, duplicates and nominal mistakes retain phases', () => {
  const missing = fixture(); missing.assessment_bases[0].assessment.criteria.pop(); assert.deepEqual(admission(missing).two, ['EVIDENCE_UNAVAILABLE']);
  const unknown = fixture(); unknown.assessment_bases[0].assessment.criteria[0].citations[0].field = 'missing'; assert.deepEqual(admission(unknown).two, ['REFERENCE_INVALID']);
  const extraSnapshot = fixture(); extraSnapshot.assessment_bases[0].supporting_context.unshift({ requirement_id: 'approval', provider_record_id: 'approval-1', provider_revision: '1', fields: [] }); assert.deepEqual(admission(extraSnapshot).two, ['DEPENDENCY_MISMATCH']);
  const extraField = fixture(); extraField.assessment_bases[0].supporting_context[0].fields.push(field('unknown', 'Text', 'extra')); assert.deepEqual(admission(extraField).two, ['REFERENCE_INVALID']);
  const duplicate = fixture(); duplicate.assessment_bases[0].review.criteria.push(clone(duplicate.assessment_bases[0].review.criteria[0])); assert.deepEqual(admission(duplicate).one, ['INPUT_INVALID']);
  const nominal = fixture(); nominal.assessment_bases[0].supporting_context[0].fields[0].value = value('Text', '84000'); assert.deepEqual(admission(nominal).one, ['TYPE_INVALID']);
  const date = fixture(); date.assessment_bases[0].assessment.assessed_at = '2026-02-30T12:00:00Z'; assert.deepEqual(admission(date).one, ['INPUT_INVALID']);
});

test('assessment escalation is local admission while human reasons and citation policies are binding', () => {
  const local = fixture(); local.assessment_bases[0].assessment.criteria[0].escalation.required = true; assert.deepEqual(admission(local).one, ['INPUT_INVALID']);
  const input = fixture(); input.assessment_bases[0].assessment.criteria[0].verdict = 'FAIL';
  input.assessment_bases[0].review.assessment_digest = digest('content-assessment', input.assessment_bases[0].assessment); assert.deepEqual(bindings(input), ['BINDING_MISMATCH']);
  input.assessment_bases[0].review.criteria[0].reason = 'The retained facts establish the request.';
  input.assessment_bases[0].review.assessment_digest = digest('content-assessment', input.assessment_bases[0].assessment); assert.deepEqual(bindings(input), []);
  input.assessment_bases[0].assessment.criteria[0].citations = [{ kind: 'PROPOSAL_FIELD', field: 'body' }];
  input.assessment_bases[0].review.assessment_digest = digest('content-assessment', input.assessment_bases[0].assessment); assert.deepEqual(bindings(input), ['BINDING_MISMATCH']);
});

test('assessment declarations close source roles, future dependencies and all four computed members', () => {
  const future = fixture(); future.envelope.source_observation_requirements.find((row: Row) => row.id === 'facts').relations.push({ id: 'future', kind: 'EQUALS', left: 'customer', right: { kind: 'DECISION_ACT', requirement_id: 'human', member: 'id', type_ref: 'Identity' } }); assert.deepEqual(admission(future).two, ['UNSUPPORTED_RELATION']);
  const overlap = fixture(); overlap.envelope.assessment_requirements[0].sources.blockers = ['facts']; assert.deepEqual(admission(overlap).two, ['UNSUPPORTED_RELATION']);
  const copied = fixture(); copied.envelope.decision_requirements[0].context_bindings[0].value = { kind: 'LITERAL', value: value('Hash', digest('copy', {})) }; assert.deepEqual(admission(copied).two, ['UNSUPPORTED_RELATION']);
  const unknown = fixture(); unknown.envelope.decision_requirements[0].context_bindings[0].value.requirement_id = 'unknown'; assert.deepEqual(admission(unknown).two, ['REFERENCE_INVALID']);
  const unresolvedCoverage = clone(unknown); unresolvedCoverage.envelope.decision_requirements[0].context_bindings.pop(); assert.deepEqual(admission(unresolvedCoverage).two, ['REFERENCE_INVALID']);
  const missingDecision = fixture(); missingDecision.envelope.decision_requirements = []; assert.deepEqual(admission(missingDecision).two, ['REFERENCE_INVALID']);
  const missingHumanReference = fixture(); missingHumanReference.envelope.assessment_requirements[0].review_decision_requirement_id = 'unknown-human'; assert.deepEqual(admission(missingHumanReference).two, ['REFERENCE_INVALID']);
  const missingStepReference = fixture(); missingStepReference.envelope.assessment_requirements[0].step = 'unknown-step'; missingStepReference.assessment_bases = []; assert.deepEqual(admission(missingStepReference).two, ['REFERENCE_INVALID']);
  for (const id of ['approval', 'issuance', 'selection']) { const missing = fixture(); missing.envelope.source_observation_requirements = missing.envelope.source_observation_requirements.filter((row: Row) => row.id !== id); assert.deepEqual(admission(missing).two, ['REFERENCE_INVALID']); }
  const selection = fixture(); selection.envelope.assessment_requirements[0].sources.selection.identity_field = 'digest'; assert.deepEqual(admission(selection).two, ['UNSUPPORTED_RELATION']);
  const evaluator = fixture(); evaluator.envelope.assessment_requirements[0].sources.evaluator.version_field = 'model'; assert.deepEqual(admission(evaluator).two, ['UNSUPPORTED_RELATION']);
  const effectiveness = fixture(); effectiveness.envelope.assessment_requirements[0].sources.effectiveness.identity_field = 'effective'; assert.deepEqual(admission(effectiveness).one, ['TYPE_INVALID']); assert.deepEqual(admission(effectiveness).two, ['UNSUPPORTED_RELATION']);
  const nominal = fixture(); nominal.envelope.source_observation_requirements.find((row: Row) => row.id === 'content').fields[0].type_ref = 'Identity'; assert.deepEqual(admission(nominal).one, ['TYPE_INVALID']);
  const missingContent = fixture(), content = missingContent.envelope.source_observation_requirements.find((row: Row) => row.id === 'content'); content.fields.pop(); content.relations.pop(); assert.deepEqual(admission(missingContent).two, ['REFERENCE_INVALID']);
});

test('assessment declarations cannot select a known step outside the envelope operations', () => {
  assert.deepEqual(admission(fixture()), { one: [], two: [] });
  const input = fixture(), primary = input.work_class.steps[0], secondary = clone(primary);
  secondary.id = 'zz-known-review-step';
  input.work_class.steps.push(secondary);
  delete primary.dispatch_gate;
  input.envelope.assessment_requirements[0].step = secondary.id;
  input.envelope.decision_requirements[0].step = secondary.id;
  for (const record of input.envelope.source_observation_requirements) record.step = secondary.id;
  input.assessment_bases = [];
  assert.deepEqual(admission(input), { one: [], two: ['REFERENCE_INVALID'] });
});

test('assessment chronology checks authenticated signing time without an available current clock', () => {
  const input = fixture(), errors: string[] = []; input.clock = { status: 'UNAVAILABLE', instant: null };
  assessmentChronology(input, { occurred_at: '2026-10-08T11:57:59Z' }, (condition, code) => { if (!condition) errors.push(code); }); assert.deepEqual(errors, ['BINDING_MISMATCH']);
});

test('assessment current maps compare complete named fields and preserve independent source failures', () => {
  const input = fixture(), data = current(input), expected = [{ subject_digest: digest('content-assessment', input.assessment_bases[0].assessment), requirement_ref: 'assessment' }];
  assert.deepEqual(assessmentChecks(input, data.queries, data.groups), expected);
  data.rows.find(row => row.query.requirement_id === 'facts')!.fields.reverse(); assert.deepEqual(assessmentChecks(input, data.queries, groups(data.rows)), expected);
  data.rows.find(row => row.query.requirement_id === 'content')!.fields[0].value.value += ' changed';
  const changed = assessmentChecks(input, data.queries, groups(data.rows)); assert.deepEqual(changed, [{ ...expected[0], reason: 'ASSESSMENT_DEPENDENCY_CHANGED' }]);
  assert(sourcePolicyFailures(input, typesOf(input), data.queries, groups(data.rows)).some(row => row.requirement_ref === 'content' && row.reason === 'SOURCE_OBSERVATION_RELATIONS'));
});

test('assessment unusable current rows supply no false dependency value and withdrawal stays separate', () => {
  const input = fixture(), data = current(input), row = data.rows.find(row => row.query.requirement_id === 'effectiveness')!;
  row.fields[0].value.value = false;
  assert.equal(assessmentChecks(input, data.queries, groups(data.rows))[0].reason, 'ASSESSMENT_DEPENDENCY_CHANGED');
  row.as_of = '2026-10-08T11:59:59Z'; assert.equal(assessmentChecks(input, data.queries, groups(data.rows))[0].reason, undefined);
  row.as_of = at; row.relations = [{ id: 'substituted' }]; assert.equal(assessmentChecks(input, data.queries, groups(data.rows))[0].reason, undefined);
});

test('assessment expired source validity supplies no profile value', () => {
  const input = fixture(), requirement = input.envelope.source_observation_requirements.find((row: Row) => row.id === 'effectiveness');
  requirement.fields.push({ name: 'not_after', type_ref: 'Instant' }, { name: 'not_before', type_ref: 'Instant' });
  input.work_class.steps[0].dispatch_gate.validity_requirements = [{ requirement_id: 'effectiveness', not_before_field: 'not_before', not_after_field: 'not_after' }];
  const data = current(input), row = data.rows.find(row => row.query.requirement_id === 'effectiveness')!;
  row.fields[0].value.value = false;
  row.fields.push(field('not_after', 'Instant', at), field('not_before', 'Instant', '2026-10-08T11:00:00Z'));
  assert.equal(assessmentChecks(input, data.queries, groups(data.rows))[0].reason, undefined);
  assert(sourcePolicyFailures(input, typesOf(input), data.queries, groups(data.rows)).some(row => row.requirement_ref === 'effectiveness' && row.reason === 'SOURCE_OBSERVATION_TIME'));
});

test('assessment approval is mandatory business satisfaction and refresh cannot replace review bodies', () => {
  const input = fixture(), fresh = clone(input), data = current(input);
  fresh.clock.instant = '2026-10-08T12:00:01Z'; assert.deepEqual(immutableAuthority(input), immutableAuthority(fresh));
  fresh.assessment_bases[0].review.decision = 'REJECT'; assert.notDeepEqual(immutableAuthority(input), immutableAuthority(fresh));
  input.assessment_bases[0].review.decision = 'REJECT'; assert.equal(assessmentChecks(input, data.queries, data.groups)[0].reason, 'ASSESSMENT_NOT_SATISFIED');
});

test('assessment selector cannot widen independent correction business context', () => {
  const request = { correction: { correction_authority_input: {} } }, step = { completion: { correction_policy: { business_decision_requirements: [{ context_bindings: [{ value: { kind: 'ASSESSMENT' } }] }] } } };
  assert.throws(() => independentCorrection(request, step, new Map(), digest('result', {})), error => error instanceof AdmissionError && error.code === 'UNSUPPORTED_RELATION');
});

test('assessment omission preserves complete ordinary results and explicit empty enters evidence only', () => {
  const row = JSON.parse(readFileSync(new URL('../cases/assessment-source/C3-ASMT-123.json', import.meta.url), 'utf8')), input = row.input.request;
  assert.deepEqual(evaluateAuthority(input, selectedCandidate()), row.expected);
  const empty = { ...clone(input), assessment_bases: [] }, preimage: Row = Object.fromEntries(['host_selection', 'occupancies', 'capacities', 'credentials', 'acts', 'returns', 'observations', 'clock'].map(key => [key, empty[key]]));
  for (const name of ['evaluation_point', 'decision_bases', 'holdings_bases', 'assessment_bases']) if (empty[name] !== undefined) preimage[name] = empty[name];
  assert.deepEqual(evaluateAuthority(empty, selectedCandidate()), { ...row.expected, evidence_digest: digest('authority-evidence', preimage) });
});

test('assessment complete public authority matches the independent source result', () => {
  const row = JSON.parse(readFileSync(new URL('../cases/assessment-source/C3-ASMT-001.json', import.meta.url), 'utf8'));
  assert.deepEqual(evaluateAuthority(row.input.request, selectedCandidate()), row.expected);
});

test('assessment canonical bytes and all five digest domains match independent known answers', () => {
  const answers = JSON.parse(readFileSync(new URL('../specimens/factual-customer-message-review/digest-known-answers.json', import.meta.url), 'utf8'));
  assert.equal(answers.candidate_pin, selectedCandidate()); assert.equal(answers.vectors.length, 30);
  assert.deepEqual([...new Set(answers.vectors.map((row: Row) => row.domain))].sort(), ['content-assessment', 'content-assessment-context', 'content-assessment-review', 'content-assessment-rubric', 'content-assessment-subject']);
  for (const row of answers.vectors) {
    const reversed = Object.fromEntries(Object.entries(row.body).reverse());
    for (const body of [row.body, reversed]) {
      assert.equal(Buffer.from(canonical(body), 'utf8').toString('hex'), row.canonical_utf8_hex, row.id);
      assert.equal(digest(row.domain, body), row.expected_digest, row.id);
    }
  }
});

test('assessment explicit empty permit and separation carriers reconstruct within protected-custody limits', () => {
  for (const id of ['176', '177', '178', '179', '180']) {
    const row = JSON.parse(readFileSync(new URL('../cases/assessment-source/C3-ASMT-' + id + '.json', import.meta.url), 'utf8'));
    assert.deepEqual(step(row.input, selectedCandidate()), row.expected);
  }
});
