import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { evaluateAuthority } from './authority.ts';
import { authorityProjection, occurrence } from './lifecycle.ts';
import { instant, instantText } from './time.ts';
import { ordered, same, typed } from './values.ts';
import { validateWorkClass } from './work-class.ts';
import type { RecordValue as Row, Types, TypedValue } from './values.ts';
import { decisionAct, decisionBasis } from './human-decisions.ts';

const omit = (row: Row, key: string): Row => Object.fromEntries(Object.entries(row).filter(([name]) => name !== key));
const check = (condition: unknown, code = 'BINDING_MISMATCH'): void => { if (!condition) throw new AdmissionError(code); };
const identities = (record: Row): Row => Object.fromEntries(['provider', 'source', 'record_type', 'provider_record_id'].map(name => [name, record[name]]));
const sorted = (values: string[]): string[] => [...new Set(values)].sort(byteCompare);
const at = (value: string): bigint => { try { return instant(value); } catch { throw new AdmissionError('INPUT_INVALID'); } };

function correctionInventory(step: Row): Map<string, string> {
  const carrier = step.completion, fields = new Map<string, string>(step.fields.map((row: Row) => [row.name, row.type_ref]));
  const inventory = new Map<string, string>(carrier.evidence_bindings.map((row: Row) => [row.evidence_field, fields.get(row.request_field)!]));
  inventory.set(carrier.status_field, carrier.status_type_ref);
  inventory.set(carrier.provider_record_identity.field, carrier.provider_record_identity.type_ref);
  inventory.set(carrier.event_time_identity.field, carrier.event_time_identity.type_ref);
  if (carrier.route_label_field !== null) inventory.set(carrier.route_label_field, carrier.route_label_type_ref);
  for (const field of carrier.additional_fields) inventory.set(field.name, field.value.type_ref);
  for (const field of carrier.generated_fields ?? []) inventory.set(field.name, field.type_ref);
  for (const field of carrier.authorization_revision_bindings ?? []) inventory.set(field.evidence_field, field.type_ref);
  return inventory;
}

function originalBasis(request: Row, pin: string): Row {
  const { definition, original_permit: permit } = request;
  let workDigest: string;
  try { workDigest = validateWorkClass(definition, pin).digest; } catch { throw new AdmissionError('DEPENDENCY_MISMATCH'); }
  check(workDigest === request.definition_digest && permit.work_class_digest === workDigest && permit.permit_id === digest('permit', omit(permit, 'permit_id')), 'DEPENDENCY_MISMATCH');
  const step = definition.steps.find((row: Row) => row.id === permit.occurrence.step_id), basis = permit.authority_basis;
  check(step?.completion?.terminal_policy === 'STOP_RETAIN' && step.completion.correction_policy && basis, 'REFERENCE_INVALID');
  check(permit.profile === definition.profile && permit.role === 'LINEAR_WORK_RUNTIME' && permit.occurrence.specification_pin === pin && permit.occurrence.work_class_digest === workDigest && permit.occurrence.instance_id === permit.instance_id, 'DEPENDENCY_MISMATCH');
  const o = permit.occurrence;
  check(same(o, occurrence(workDigest, permit.instance_id, step.id, o.ordinal, o.predecessor_occurrence_ids, o.enclosing, o.object_key, pin)), 'DEPENDENCY_MISMATCH');
  check((basis.evaluation_point ?? 'PROPOSE') === 'PROPOSE' && basis.specification_pin === pin && basis.clock.status === 'AVAILABLE' && basis.clock.source === permit.clock_source && same(basis.work_class, authorityProjection(definition)), 'DEPENDENCY_MISMATCH');
  const proposal = basis.proposal;
  check(proposal.work_class === definition.id && proposal.instance === permit.instance_id && proposal.occurrence === o.occurrence_id && proposal.step === step.id && proposal.interface === step.interface && proposal.operation === step.operation && basis.envelope.id === step.authority_requirements[0], 'DEPENDENCY_MISMATCH');
  check(same(permit.native_request, { interface: proposal.interface, operation: proposal.operation, fields: proposal.fields }) && same(permit.native_request.fields.map((row: Row) => ({ name: row.name, type_ref: row.value.type_ref })), step.fields), 'DEPENDENCY_MISMATCH');
  check(permit.executor.participant_id === proposal.executor.actor && permit.executor.role === proposal.executor.role && permit.executor.binding_digest === digest('executor-binding', proposal.executor) && same(permit.credential_ids, sorted(basis.credentials.map((row: Row) => row.id))) && same(permit.observation_digests, sorted(basis.observations.map((row: Row) => digest('authority-observation', row)))), 'DEPENDENCY_MISMATCH');
  check(basis.source.id === definition.source.id && basis.source.revision === definition.source.revision && same(basis.source.obligations.map((row: Row) => row.id), definition.source.obligations), 'DEPENDENCY_MISMATCH');
  const result = evaluateAuthority(basis, pin);
  check(result.status === 'READY_FOR_RESERVATION' && same(result, permit.authority_result) && digest('authority-result', result) === permit.authority_result_digest && result.evidence_digest === permit.authority_evidence_digest, 'DEPENDENCY_MISMATCH');
  const actBases = basis.acts.map((act: Row) => ({ act_digest: digest('authority-act', act), act })).sort((a: Row, b: Row) => byteCompare(a.act_digest, b.act_digest));
  check(same(permit.authority_act_bases, actBases) && same(actBases.map((row: Row) => row.act_digest), result.act_digests), 'DEPENDENCY_MISMATCH');
  check(at(basis.clock.instant) < at(permit.expires_at) && at(permit.expires_at) <= at(basis.clock.instant) + BigInt(step.permit_seconds) * 1_000_000_000n && (basis.envelope.temporal_validity.valid_until === null || at(permit.expires_at) <= at(basis.envelope.temporal_validity.valid_until)), 'DEPENDENCY_MISMATCH');
  if (!permit.budget_revisions.length) {
    const cap = at(basis.clock.instant) + BigInt(step.permit_seconds) * 1_000_000_000n, until = basis.envelope.temporal_validity.valid_until;
    check(permit.expires_at === instantText(until !== null && at(until) < cap ? at(until) : cap), 'DEPENDENCY_MISMATCH');
  }
  return step;
}

function proposalCommitment(authority: Row, name: string, expected: string): void {
  const step = authority.work_class.steps.find((row: Row) => row.id === authority.proposal.step);
  const declaration = step?.fields.find((row: Row) => row.name === name), values = authority.proposal.fields.filter((row: Row) => row.name === name);
  const type = declaration && authority.work_class.types.find((row: Row) => row.id === declaration.type_ref);
  check(declaration && type && ['IDENTITY', 'STRING'].includes(type.kind) && values.length === 1 && values[0].value.type_ref === declaration.type_ref && values[0].value.value === expected);
}

function currentAuthority(input: Row, principal: string, instant: string, pin: string): Row {
  check(!(input.envelope.assessment_requirements ?? []).length && !(input.assessment_bases ?? []).length && !(input.envelope.decision_requirements ?? []).some((row: Row) => row.context_bindings.some((binding: Row) => binding.value.kind === 'ASSESSMENT')), 'UNSUPPORTED_RELATION');
  check((input.evaluation_point ?? 'PROPOSE') === 'PROPOSE' && input.clock.status === 'AVAILABLE' && input.clock.instant === instant && input.envelope.principal === principal, 'EVIDENCE_UNAVAILABLE');
  const result = evaluateAuthority(input, pin);
  check(result.status === 'READY_FOR_RESERVATION', 'EVIDENCE_UNAVAILABLE');
  return result;
}

function originalScope(result: Row, principal: string, identity: string): void {
  check(result.actual_scope.subjects.includes(principal) && result.actual_scope.resources.includes(identity) && result.scope.subjects.includes(principal) && result.scope.resources.includes(identity), 'EVIDENCE_UNAVAILABLE');
}

export function independentCorrection(request: Row, step: Row, fields: Map<string, Row>, resultDigest: string): void {
  const correction = request.correction, policy = step.completion.correction_policy, current = correction.correction_authority_input;
  check(policy.business_decision_requirements.every((row: Row) => row.context_bindings.every((binding: Row) => !['ASSESSMENT', 'FLOW_DISCLOSURE'].includes(binding.value.kind))), 'UNSUPPORTED_RELATION');
  check(correction.decision_policy === policy.kind);
  const business = correction.changes.some((row: Row) => policy.business_result_fields.includes(row.field));
  check(business ? same(current.envelope.decision_requirements, policy.business_decision_requirements) : (current.envelope.decision_requirements ?? []).length === 0 && (current.decision_bases ?? []).length === 0);
  const controls = ['original_id_field', 'original_digest_field', 'original_revision_field', 'changes_digest_field', 'result_digest_field'].map(name => policy[name]);
  check(new Set(controls).size === controls.length);
  const businessFields = new Set(policy.business_context_bindings.map((row: Row) => row.proposal_field));
  check(policy.business_decision_requirements.every((row: Row) => row.context_bindings.every((binding: Row) => binding.value.kind !== 'PROPOSAL_FIELD' || !controls.includes(binding.value.field) && businessFields.has(binding.value.field))));
  const ownStep = current.work_class.steps.find((row: Row) => row.id === current.proposal.step), ownTypes: Types = new Map(current.work_class.types.map((row: Row) => [row.id, row])), originalTypes: Types = new Map(request.definition.types.map((row: Row) => [row.id, row]));
  check(ownStep && same(current.proposal.fields.filter((row: Row) => !controls.includes(row.name)).map((row: Row) => row.name), policy.business_context_bindings.map((row: Row) => row.proposal_field)));
  for (const binding of policy.business_context_bindings) {
    const declaration = ownStep.fields.find((row: Row) => row.name === binding.proposal_field), value = binding.value.kind === 'CORRECTED_FIELD' ? fields.get(binding.value.field) : binding.value.value;
    check(declaration && value);
    check(value.type_ref === declaration.type_ref, 'TYPE_INVALID');
    check(same(originalTypes.get(value.type_ref), ownTypes.get(declaration.type_ref)), 'TYPE_INVALID');
    try { typed(value as TypedValue, ownTypes); } catch (error) { if (error instanceof AdmissionError) throw new AdmissionError('TYPE_INVALID'); throw error; }
    check(same(current.proposal.fields.find((row: Row) => row.name === binding.proposal_field)?.value, value));
  }
  proposalCommitment(current, policy.result_digest_field, resultDigest);
  if (!business) return;
  const originalBasis = request.original_permit.authority_basis, requestValues = new Map<string, Row>(request.original_permit.native_request.fields.map((row: Row) => [row.name, row.value])), originalValues = new Map<string, Row>(request.original_record.actual_fields.map((row: Row) => [row.name, row.value]));
  for (const field of policy.fresh_result_fields) {
    const binding = step.completion.evidence_bindings.find((row: Row) => row.evidence_field === field);
    check(binding && !same(fields.get(field), requestValues.get(binding.request_field)) && !same(fields.get(field), originalValues.get(field) ?? null));
  }
  const oldActs = (originalBasis.decision_bases ?? []).map((row: Row) => { const act = decisionAct(originalBasis, row.requirement_id); check(act); return act!; });
  const oldIds = new Set(oldActs.map((act: Row) => act.id)), oldDigests = new Set(oldActs.map((act: Row) => digest('authority-act', act)));
  const oldIdentities = new Set((originalBasis.decision_bases ?? []).map((row: Row) => {
    const declaration = originalBasis.envelope.decision_requirements.find((value: Row) => value.id === row.requirement_id);
    const field = row.evidence.authority_input.proposal.fields.find((value: Row) => value.name === declaration?.identity_field);
    check(field); return field.value.value;
  }));
  const issueIds: string[] = [], actDigests: string[] = [], identities: string[] = [];
  for (const declaration of policy.business_decision_requirements) {
    const original = originalBasis.envelope.decision_requirements?.find((row: Row) => row.id === declaration.id);
    check(original && original.principal === declaration.principal && original.role === declaration.role);
    const freshEvidence = decisionBasis(current, declaration.id), oldEvidence = decisionBasis(originalBasis, declaration.id), freshAct = decisionAct(current, declaration.id), oldAct = decisionAct(originalBasis, declaration.id);
    check(freshEvidence, 'EVIDENCE_UNAVAILABLE');
    check(freshEvidence && oldEvidence && freshAct && oldAct && !oldIds.has(freshAct.id) && !oldDigests.has(freshEvidence.decision_act_digest));
    const context = declaration.context_bindings.find((row: Row) => row.field === declaration.identity_field);
    check(context?.value.kind === 'PROPOSAL_FIELD');
    const binding = policy.business_context_bindings.find((row: Row) => row.proposal_field === context.value.field);
    check(binding?.value.kind === 'CORRECTED_FIELD');
    const nativeBinding = step.completion.evidence_bindings.find((row: Row) => row.evidence_field === binding.value.field);
    check(nativeBinding && !same(fields.get(binding.value.field), requestValues.get(nativeBinding.request_field)) && !same(fields.get(binding.value.field), originalValues.get(binding.value.field) ?? null));
    const identity = fields.get(binding.value.field)?.value;
    check(typeof identity === 'string' && !oldIdentities.has(identity));
    issueIds.push(freshAct!.id);
    actDigests.push(freshEvidence!.decision_act_digest);
    identities.push(identity);
  }
  check(new Set(issueIds).size === issueIds.length && new Set(actDigests).size === actDigests.length && new Set(identities).size === identities.length);
}

export function checkSourceCorrection(request: Row, pin: string): Row {
  try {
    const { original_permit: permit, original_record: record, correction } = request;
    const originalAt = record.event_time === null ? null : at(record.event_time), eventAt = at(correction.event_time), observedAt = at(correction.observed_at);
    const originalObservedAt = at(record.observed_at); at(permit.expires_at); at(correction.custodian_return.at);
    const step = originalBasis(request, pin), carrier = step.completion, policy = carrier.correction_policy, basis = permit.authority_basis;
    const independent = policy.kind === 'INDEPENDENT_HUMAN_DECISIONS';
    check(independent ? correction.decision_policy === policy.kind : correction.decision_policy === undefined);
    check(!correction.changes.some((row: Row) => (carrier.authorization_revision_bindings ?? []).some((binding: Row) => binding.evidence_field === row.field)));
    check(record.status === 'EFFECT_ESTABLISHED' && record.provider_record_id && record.provider_revision && !record.rules_out_past_and_future_effects && record.collections.length === 0 && originalAt !== null && originalAt <= originalObservedAt && originalAt <= eventAt && eventAt <= observedAt);
    check(same([record.provider, record.source, record.record_type], [carrier.effect_provider, carrier.effect_source, carrier.effect_record_type]));
    const attributed = { work_class: request.definition.id, instance: permit.instance_id, occurrence: permit.occurrence.occurrence_id, step: step.id, operation: permit.native_request.operation, interface: permit.native_request.interface, fields: permit.native_request.fields };
    check(same(record.attributed_request, attributed) && record.native_request_digest === digest('native-request', attributed));
    const nativeBody = Object.fromEntries(['provider', 'source', 'record_type', 'provider_record_id', 'provider_revision', 'actual_fields', 'event_time'].map(name => [name, record[name]]));
    check(record.record_digest === digest('provider-native-record', nativeBody));
    check(correction.original_provider_record_id === record.provider_record_id && correction.original_record_digest === record.record_digest && correction.expected_revision === record.provider_revision && same([correction.provider, correction.source, correction.record_type], [policy.correction_provider, policy.correction_source, policy.correction_record_type]));
    check(ordered(record.actual_fields.map((row: Row) => row.name)) && ordered(correction.changes.map((row: Row) => row.field)) && ordered(correction.corrected_fields.map((row: Row) => row.name)));
    const inventory = correctionInventory(step), original = new Map<string, Row>(record.actual_fields.map((row: Row) => [row.name, row.value])), corrected = new Map(original), types: Types = new Map(request.definition.types.map((row: Row) => [row.id, row]));
    for (const change of correction.changes) {
      const old = original.get(change.field) ?? null;
      check(same(change.old_value, old) && !same(change.old_value, change.new_value));
      if (!inventory.has(change.field)) { check(old !== null && change.new_value === null); corrected.delete(change.field); }
      else {
        check(change.new_value !== null);
        check(change.new_value.type_ref === inventory.get(change.field), 'TYPE_INVALID');
        try { typed(change.new_value, types); } catch (error) { if (error instanceof AdmissionError) throw new AdmissionError('TYPE_INVALID'); throw error; }
        corrected.set(change.field, change.new_value);
      }
    }
    const fields = [...corrected].map(([name, value]) => ({ name, value })).sort((a: Row, b: Row) => byteCompare(a.name, b.name));
    check(same(correction.corrected_fields, fields) && same(fields.map((row: Row) => row.name), [...inventory.keys()].sort(byteCompare)));
    for (const field of fields) {
      check(field.value.type_ref === inventory.get(field.name), 'TYPE_INVALID');
      try { typed(field.value as TypedValue, types); } catch (error) { if (error instanceof AdmissionError) throw new AdmissionError('TYPE_INVALID'); throw error; }
    }
    for (const binding of policy.provider_link_bindings) check(corrected.get(binding.field)!.value === canonical({ provider: binding.provider, source: binding.source, record_type: binding.record_type, provider_record_id: corrected.get(binding.record_id_field)!.value }));
    const changesDigest = digest('source-correction-changes', correction.changes), resultDigest = digest('source-correction-result', fields), identity = identities(record), identityText = canonical(identity), principal = basis.envelope.principal;
    const custodian = correction.custodian, returned = correction.custodian_return, authority = correction.correction_authority_input;
    check(custodian.role === policy.custodian_role && custodian.principal === principal);
    const occupancy = authority.occupancies.find((row: Row) => row.id === custodian.occupancy);
    check(occupancy && occupancy.actor === custodian.actor && occupancy.role === custodian.role && occupancy.principal === custodian.principal);
    check(returned.actor === custodian.actor && returned.role === custodian.role && returned.at === correction.event_time && returned.provider === occupancy.provider && returned.source === policy.custodian_identity_source && returned.occupancy_digest === digest('authority-occupancy', occupancy));
    check(returned.provenance_digest === digest('source-correction-custodian-provenance', omit(returned, 'provenance_digest')));
    check(same(authority.proposal.executor, custodian) && authority.envelope.executor_role === policy.custodian_role && authority.envelope.gate.kind === 'DECIDE', 'EVIDENCE_UNAVAILABLE');
    if (independent) independentCorrection(request, step, corrected, resultDigest);
    const authorityResult = currentAuthority(authority, principal, correction.event_time, pin);
    proposalCommitment(authority, policy.original_id_field, identityText); proposalCommitment(authority, policy.original_digest_field, record.record_digest);
    proposalCommitment(authority, policy.original_revision_field, record.provider_revision); proposalCommitment(authority, policy.changes_digest_field, changesDigest);
    originalScope(authorityResult, principal, identityText);
    const decisions = authority.acts.filter((row: Row) => row.kind === 'INSTANCE_DECISION');
    check(decisions.length === 1 && decisions[0].role === policy.issuer_role && decisions[0].disposition === 'ACCEPT' && at(decisions[0].occurred_at) <= eventAt, 'EVIDENCE_UNAVAILABLE');
    check(correction.correction_authorization_digest === digest('authority-act', decisions[0]));
    const business = correction.changes.some((row: Row) => policy.business_result_fields.includes(row.field));
    if (!independent) check(business ? correction.new_approval_basis !== null : correction.new_approval_basis === null);
    let newResult: Row | null = null;
    if (business && !independent) {
      const approval = correction.new_approval_basis;
      newResult = currentAuthority(approval, principal, correction.event_time, pin);
      const grants = approval.acts.filter((row: Row) => row.kind === 'GRANT'), originalGrants = basis.acts.filter((row: Row) => row.kind === 'GRANT');
      check(grants.length === 1 && grants[0].role === policy.issuer_role && grants[0].disposition === 'ACCEPT' && at(grants[0].occurred_at) <= eventAt, 'EVIDENCE_UNAVAILABLE');
      const originalApproval = policy.provider_link_bindings.map((row: Row) => original.get(row.record_id_field)?.value);
      check(!originalApproval.includes(grants[0].id) && !originalGrants.some((row: Row) => row.id === grants[0].id));
      proposalCommitment(approval, policy.result_digest_field, resultDigest);
      originalScope(newResult, principal, identityText);
    }
    check(correction.provenance_digest === digest('source-correction-provenance', omit(correction, 'provenance_digest')));
    return { status: 'EVIDENCE_VALID', profile: request.profile, role: request.role, specification_pin: pin, kind: 'SOURCE_CORRECTION', definition_digest: request.definition_digest, original_record_identity: identity, original_record_digest: record.record_digest, correction_digest: digest('source-correction', correction), correction_authority_result: authorityResult, correction_authority_result_digest: digest('authority-result', authorityResult), ...(independent ? { decision_policy: policy.kind } : { new_approval_result: newResult, new_approval_result_digest: newResult === null ? null : digest('authority-result', newResult) }), changes_digest: changesDigest, result_digest: resultDigest };
  } catch (error) {
    if (!(error instanceof AdmissionError)) throw error;
    return { status: 'EVIDENCE_INVALID', profile: request.profile, role: request.role, specification_pin: pin, code: error.code, path: '' };
  }
}
