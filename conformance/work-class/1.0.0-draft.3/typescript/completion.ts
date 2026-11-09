import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { instant } from './time.ts';
import { ordered, same, typed } from './values.ts';
import type { RecordValue as Row, Types } from './values.ts';
import { firstWithheldStep, timingEvaluationInventory } from './timing.ts';

const fail = (code: string): never => { throw new AdmissionError(code); };
const check = (condition: unknown, code = 'BINDING_MISMATCH'): void => { if (!condition) fail(code); };
const omit = (row: Row, ...keys: string[]): Row => Object.fromEntries(Object.entries(row).filter(([key]) => !keys.includes(key)));
const sorted = (values: string[]): string[] => [...new Set(values)].sort(byteCompare);
const eventHash = (event: Row): string => event.event_digest ?? digest('runtime-event', event);
export const terminalCompletion = (step: Row): boolean => step.completion?.terminal_policy === 'STOP_RETAIN';
export const authorityReferrals = (definition: Row): boolean => definition.steps.some((step: Row) => (step.referral_policy?.authority ?? []).length > 0);
export const proposalEvaluationInventory = (definition: Row): boolean => authorityReferrals(definition) || timingEvaluationInventory(definition);
export function completionTypeRefs(carrier: Row): string[] {
  return [carrier.status_type_ref, ...(carrier.route_label_type_ref ? [carrier.route_label_type_ref] : []), ...(carrier.terminal_policy === 'STOP_RETAIN' ? [carrier.provider_record_identity.type_ref, carrier.event_time_identity.type_ref, ...carrier.additional_fields.map((row: Row) => row.value.type_ref), ...(carrier.generated_fields ?? []).map((row: Row) => row.type_ref), ...(carrier.authorization_revision_bindings ?? []).map((row: Row) => row.type_ref), ...carrier.lookup.key_projection.map((row: Row) => row.value?.type_ref ?? row.type_ref)] : [])];
}

export function admitCompletion(step: Row, types: Types): void {
  if (!terminalCompletion(step)) return;
  const carrier = step.completion, identity = carrier.provider_record_identity, time = carrier.event_time_identity;
  for (const ref of completionTypeRefs(carrier)) check(types.has(ref), 'REFERENCE_INVALID');
  check(['IDENTITY', 'STRING'].includes(types.get(identity.type_ref)!.kind) && types.get(time.type_ref)!.kind === 'INSTANT', 'TYPE_INVALID');
  check(ordered(carrier.additional_fields.map((row: Row) => row.name)), 'DEFINITION_INVALID');
  check(ordered((carrier.generated_fields ?? []).map((row: Row) => row.name)), 'DEFINITION_INVALID');
  const revisionBindings = carrier.authorization_revision_bindings ?? [];
  check(ordered(revisionBindings.map((row: Row) => row.evidence_field)), 'DEFINITION_INVALID');
  for (const binding of revisionBindings) {
    check(['STRING', 'IDENTITY'].includes(types.get(binding.type_ref)?.kind ?? ''), 'TYPE_INVALID');
    const gate = step.dispatch_gate, ids = gate?.kind === 'SOURCE_REQUIREMENTS' ? gate.requirements : gate ? [gate.approval_requirement, gate.withdrawal_requirement, ...gate.policy_withdrawal_requirements] : [];
    check(ids.includes(binding.requirement_id), 'REFERENCE_INVALID');
  }
  const fields = [carrier.status_field, ...carrier.evidence_bindings.map((row: Row) => row.evidence_field), ...(carrier.route_label_field ? [carrier.route_label_field] : []), identity.field, time.field, ...carrier.additional_fields.map((row: Row) => row.name), ...(carrier.generated_fields ?? []).map((row: Row) => row.name), ...revisionBindings.map((row: Row) => row.evidence_field)];
  const overlap = carrier.status_request_field !== undefined;
  if (overlap) {
    const binding = carrier.evidence_bindings.find((row: Row) => row.request_field === carrier.status_request_field), field = step.fields.find((row: Row) => row.name === carrier.status_request_field);
    check(binding?.evidence_field === carrier.status_field && field?.type_ref === carrier.status_type_ref, 'DEFINITION_INVALID');
  }
  check(new Set(fields).size <= 66, 'LIMIT_EXCEEDED'); check(new Set(fields).size === fields.length - (overlap ? 1 : 0), 'DEFINITION_INVALID');
  for (const row of carrier.additional_fields) typed(row.value, types);
  const names = carrier.lookup.key_projection.map((row: Row) => row.key_field ?? row.field);
  check(new Set(names).size === names.length, 'DEFINITION_INVALID');
  for (const row of carrier.lookup.key_projection) {
    if (row.value !== undefined) typed(row.value, types);
    else {
      const field = step.fields.find((field: Row) => field.name === row.field);
      check(field, 'REFERENCE_INVALID'); check(field.type_ref === row.type_ref, 'TYPE_INVALID');
    }
  }
  if (carrier.correction_policy) {
    const policy = carrier.correction_policy;
    check(ordered(policy.business_result_fields) && ordered(policy.provider_link_bindings.map((row: Row) => row.field)), 'DEFINITION_INVALID');
    const inventory = new Map<string, string>(carrier.evidence_bindings.map((row: Row) => [row.evidence_field, step.fields.find((field: Row) => field.name === row.request_field)?.type_ref]));
    inventory.set(carrier.status_field, carrier.status_type_ref); inventory.set(identity.field, identity.type_ref); inventory.set(time.field, time.type_ref);
    if (carrier.route_label_field) inventory.set(carrier.route_label_field, carrier.route_label_type_ref);
    for (const field of carrier.additional_fields) inventory.set(field.name, field.value.type_ref);
    for (const field of carrier.generated_fields ?? []) inventory.set(field.name, field.type_ref);
    for (const field of revisionBindings) inventory.set(field.evidence_field, field.type_ref);
    if (policy.kind === 'INDEPENDENT_HUMAN_DECISIONS') {
      check(policy.business_decision_requirements.every((row: Row) => row.context_bindings.every((binding: Row) => !['ASSESSMENT', 'FLOW_DISCLOSURE'].includes(binding.value.kind))), 'UNSUPPORTED_RELATION');
      check(ordered(policy.business_decision_requirements.map((row: Row) => row.id)) && ordered(policy.business_context_bindings.map((row: Row) => row.proposal_field)) && ordered(policy.fresh_result_fields), 'DEFINITION_INVALID');
      for (const field of policy.fresh_result_fields) check(carrier.evidence_bindings.some((row: Row) => row.evidence_field === field), 'REFERENCE_INVALID');
      for (const binding of policy.business_context_bindings) {
        if (binding.value.kind === 'CORRECTED_FIELD') check(inventory.has(binding.value.field), 'REFERENCE_INVALID');
        else typed(binding.value.value, types);
      }
    }
    for (const name of policy.business_result_fields) check(inventory.has(name), 'REFERENCE_INVALID');
    for (const binding of policy.provider_link_bindings) for (const name of [binding.field, binding.record_id_field]) {
      check(inventory.has(name), 'REFERENCE_INVALID'); check(['IDENTITY', 'STRING'].includes(types.get(inventory.get(name)!)!.kind), 'TYPE_INVALID');
    }
  }
}

export function terminalFieldsMatch(step: Row, evidence: Row, types: Types, authorization?: Row, claimOnly = false): boolean {
  const carrier = step.completion, fields = evidence.actual_fields;
  if (!evidence.provider_record_id || !evidence.provider_revision || fields.length > 66 || new Set(fields.map((row: Row) => row.name)).size !== fields.length) return false;
  const selected = (name: string): Row | undefined => fields.find((row: Row) => row.name === name)?.value;
  if (!same(selected(carrier.provider_record_identity.field) ?? null, { type_ref: carrier.provider_record_identity.type_ref, value: evidence.provider_record_id }) || !same(selected(carrier.event_time_identity.field) ?? null, { type_ref: carrier.event_time_identity.type_ref, value: evidence.event_time })) return false;
  for (const binding of carrier.authorization_revision_bindings ?? []) {
    if (!authorization && claimOnly) {
      if (selected(binding.evidence_field)?.type_ref !== binding.type_ref) return false;
      continue;
    }
    if (!authorization) fail('STATE_INVALID');
    const rows = authorization!.authorization_fence.sources.filter((row: Row) => row.requirement_id === binding.requirement_id);
    if (rows.length !== 1 || rows[0].expected_status !== 'AVAILABLE') fail('STATE_INVALID');
    if (!same(selected(binding.evidence_field) ?? null, { type_ref: binding.type_ref, value: rows[0].provider_revision })) return false;
  }
  if (carrier.additional_fields.some((row: Row) => !same(selected(row.name) ?? null, row.value))) return false;
  if ((carrier.generated_fields ?? []).some((row: Row) => selected(row.name)?.type_ref !== row.type_ref)) return false;
  try { for (const row of fields) typed(row.value, types); }
  catch (error) { if (error instanceof AdmissionError) return false; throw error; }
  return true;
}

export function nativeFact(evidence: Row, terminal: boolean): string {
  return digest('native-evidence-fact', omit(evidence, 'evidence_id', 'evidence_ref', ...(terminal ? ['observed_at'] : [])));
}
export function providerIdentity(evidence: Row): string | null {
  return evidence.provider_record_id ? canonical([evidence.provider, evidence.source, evidence.record_type, evidence.provider_record_id]) : null;
}

export function lookupQuery(state: Row, permit: Row, dispatch: Row, step: Row, clock: Row): Row {
  const declaration = step.completion.lookup, fields = new Map(permit.native_request.fields.map((row: Row) => [row.name, row.value]));
  const key = declaration.key_projection.map((row: Row) => ({ name: row.key_field ?? row.field, value: structuredClone(row.value ?? fields.get(row.field)) })).sort((a: Row, b: Row) => byteCompare(a.name, b.name));
  return { instance_id: state.instance_id, occurrence_id: permit.occurrence.occurrence_id, permit_digest: permit.permit_id, dispatch_digest: dispatch.dispatch_digest, authorization_digest: dispatch.authorization_digest ?? null, provider: declaration.provider, source: declaration.source, record_type: declaration.record_type, namespace: declaration.namespace, key, at: clock.observed_time };
}

export function admitLookup(lookup: Row, query: Row): string[] {
  check(same(lookup.query, query) && lookup.query_digest === digest('completion-query', query) && lookup.provenance_digest === digest('completion-lookup-provenance', omit(lookup, 'provenance_digest')) && lookup.observed_at === query.at);
  const candidates = lookup.candidates, identities = candidates.map(providerIdentity);
  check(ordered(identities as string[]) && candidates.every((row: Row) => ['provider', 'source', 'record_type'].every(name => row[name] === query[name])));
  if (lookup.status === 'UNAVAILABLE') check(lookup.as_of === null && lookup.provider_revision === null && lookup.coverage === 'UNAVAILABLE' && candidates.length === 0 && !lookup.truncated);
  else {
    check(lookup.as_of !== null && lookup.provider_revision !== null && ['COMPLETE', 'INCOMPLETE'].includes(lookup.coverage));
    try { check(instant(lookup.as_of) <= instant(query.at)); } catch { fail('BINDING_MISMATCH'); }
    check(lookup.status === 'NOT_FOUND' ? candidates.length === 0 && !lookup.truncated : lookup.status === 'AMBIGUOUS' ? candidates.length >= 2 && candidates.length <= 64 && !lookup.truncated : candidates.length === 64 && lookup.truncated);
  }
  const reasons = [lookup.status === 'AMBIGUOUS' ? 'COMPLETION_AMBIGUOUS' : lookup.status === 'OVERFLOW' ? 'COMPLETION_OVERFLOW' : 'UNKNOWN_OUTCOME'];
  if (lookup.coverage === 'INCOMPLETE') reasons.push('LOOKUP_INCOMPLETE');
  if (lookup.as_of !== null && instant(lookup.as_of) < instant(query.at)) reasons.push('LOOKUP_STALE');
  return sorted(reasons);
}

export function decisionBasis(state: Row, event: Row, input: Row, outcome: Row | null = null, completionCheck: Row | null = null): Row {
  return { instance_id: state.instance_id, event_id: event.event_id, event_digest: eventHash(event), disposition: input.disposition, reason_codes: sorted(input.reasons ?? []), permit_digest: input.decisionPermitDigest ?? input.permit?.permit_id ?? null, authority_result_digest: input.authorityResultDigest ?? null, outcome_digest: outcome?.outcome_digest ?? null, completion_check_digest: completionCheck?.check_digest ?? null };
}

function referralRows(state: Row, event: Row, basis: Row, routes: Row[], terminalDigest: string | null, causeDigest: string, evidence: string[], occurrenceId: string): Row[] {
  const rows = routes.map(route => {
    const body = { event_id: event.event_id, event_digest: eventHash(event), instance_id: state.instance_id, occurrence_id: occurrenceId, decision_basis_digest: digest('decision-basis', basis), terminal_digest: terminalDigest, cause_digest: causeDigest, destination_role: route.destination_role, queue: route.queue, purpose: route.purpose, safe_state: route.safe_state, via_role: route.via_role, evidence_digests: sorted(evidence) };
    return { referral_digest: digest('referral-intent', body), ...body };
  });
  return [...new Map(rows.map(row => [canonical(row), row])).values()];
}

export function retainDecisionRecords(previous: Row, next: Row, definition: Row, event: Row, input: Row): void {
  const authorityDetail = input.details?.find((row: Row) => row.kind === 'AUTHORITY');
  const authorityWithheld = input.disposition === 'WITHHELD' || input.disposition === 'STOPPED' && input.details?.some((row: Row) => row.kind === 'DEADLINE' && row.reasons.includes('DEADLINE_TIME_OVERFLOW'));
  if (event.kind === 'PROPOSE' && authorityWithheld && authorityDetail && (authorityReferrals(definition) || firstWithheldStep(definition, event.occurrence.step_id))) {
    if (event.authority_input !== undefined) {
      check(next.proposal_authority_evaluations.length < 128, 'LIMIT_EXCEEDED');
      const body = { event: structuredClone(event), authority_result: structuredClone(input.authorityResult), authority_result_digest: input.authorityResultDigest };
      next.proposal_authority_evaluations.push({ evaluation_digest: digest('proposal-authority-evaluation', body), ...body });
      next.proposal_authority_evaluations.sort((a: Row, b: Row) => byteCompare(a.event.event_id, b.event.event_id));
    }
    input.proposalAuthorityEvaluationDigest = next.proposal_authority_evaluations.find((row: Row) => row.event.event_id === event.event_id)?.evaluation_digest;
  }
  const outcome = next.outcomes.find((row: Row) => row.event_id === event.event_id) ?? null;
  const completionCheck = (next.completion_checks ?? []).find((row: Row) => row.event_id === event.event_id) ?? null;
  const basis = decisionBasis(previous, event, input, outcome, completionCheck);
  let referrals: Row[] = [], terminal: Row | null = null;
  if (authorityWithheld && authorityDetail && ['PROPOSE', 'AUTHORIZE_DISPATCH'].includes(event.kind)) {
    const stepId = event.kind === 'PROPOSE' ? event.occurrence.step_id : event.permit.occurrence.step_id;
    const step = definition.steps.find((row: Row) => row.id === stepId), routes = step.referral_policy?.authority ?? [];
    const evaluation = (next.authorization_evaluations ?? []).find((row: Row) => row.event_id === event.event_id) ?? (next.proposal_authority_evaluations ?? []).find((row: Row) => row.event.event_id === event.event_id);
    const result = evaluation?.authority_result ?? input.authorityResult ?? input.details?.find((row: Row) => row.kind === 'AUTHORITY');
    const selected = routes.filter((route: Row) => route.requirement_ids.length === 0 || (result?.failed_checks ?? []).some((row: Row) => row.purpose === 'SOURCE_OBSERVATION' && route.requirement_ids.includes(row.requirement_ref)));
    if (selected.length) referrals = referralRows(next, event, basis, selected, null, input.authorityResultDigest, [input.authorityResultDigest, ...(evaluation ? [evaluation.evaluation_digest] : [])], event.kind === 'PROPOSE' ? event.occurrence.occurrence_id : event.permit.occurrence.occurrence_id);
  }
  if ((outcome && outcome.kind === 'GOVERNED' && !['MATCHED', 'LATE_MATCHED', 'DUPLICATE'].includes(outcome.classification)) || completionCheck) {
    const permit = next.permits.find((row: Row) => row.permit_id === (outcome?.permit_digest ?? completionCheck.permit_digest));
    const step = definition.steps.find((row: Row) => row.id === permit.occurrence.step_id);
    if (terminalCompletion(step) && !(previous.terminal_records ?? []).some((row: Row) => row.occurrence_id === permit.occurrence.occurrence_id)) {
      const dispatch = next.dispatches.find((row: Row) => row.dispatch_digest === (outcome?.dispatch_digest ?? completionCheck.dispatch_digest));
      const active = next.active.find((row: Row) => row.occurrence.occurrence_id === permit.occurrence.occurrence_id);
      const status = active?.status === 'BLOCKED_DISPUTE' ? 'BLOCKED_DISPUTE' : outcome?.classification === 'UNKNOWN' || completionCheck && ['NOT_FOUND', 'UNAVAILABLE'].includes(completionCheck.lookup.status) ? 'OUTCOME_UNKNOWN' : 'BLOCKED_DISPUTE';
      const evidence = completionCheck ? [completionCheck.check_digest] : [digest('native-evidence', outcome.native_evidence), ...next.outcomes.filter((row: Row) => outcome.conflicts_with_evidence_ids.includes(row.native_evidence.evidence_id)).map((row: Row) => digest('native-evidence', row.native_evidence))];
      const body = { event_id: event.event_id, event_digest: eventHash(event), instance_id: next.instance_id, occurrence_id: permit.occurrence.occurrence_id, permit_digest: permit.permit_id, authorization_digest: dispatch.authorization_digest ?? null, dispatch_digest: dispatch.dispatch_digest, decision_basis_digest: digest('decision-basis', basis), cause: completionCheck ? 'COMPLETION_LOOKUP_FAILED' : ({ UNKNOWN: 'UNKNOWN_COMPLETION', UNEXPECTED: 'UNEXPECTED_COMPLETION', CONFLICTING: 'CONFLICTING_COMPLETION', LATE_AFTER_RELEASE: 'CONFLICTING_COMPLETION', FAILED: 'DECLARED_COMPLETION_FAILURE', NO_EFFECT_ESTABLISHED: 'NO_EFFECT_COMPLETION' } as Row)[outcome.classification], occurrence_status: status, evidence_digests: sorted(evidence), retained_reservation_bases: structuredClone(permit.budget_revisions) };
      terminal = { terminal_digest: digest('terminal-record', body), ...body };
      referrals = referralRows(next, event, basis, step.referral_policy?.completion ?? [], terminal.terminal_digest, outcome?.outcome_digest ?? completionCheck.check_digest, evidence, permit.occurrence.occurrence_id);
      if (active) active.status = status;
      next.status = 'STOPPED';
    }
  }
  check((next.referrals ?? []).length + referrals.length <= 4096 && (next.terminal_records ?? []).length + (terminal ? 1 : 0) <= 128, 'LIMIT_EXCEEDED');
  if (terminal) { next.terminal_records.push(terminal); next.terminal_records.sort((a: Row, b: Row) => byteCompare(a.terminal_digest, b.terminal_digest)); input.terminalDigest = terminal.terminal_digest; }
  if (referrals.length) { next.referrals.push(...referrals); next.referrals.sort((a: Row, b: Row) => byteCompare(a.referral_digest, b.referral_digest)); }
  if (terminal || referrals.length) input.decisionBasisDigest = digest('decision-basis', basis);
}

export function validateCompletionRecords(state: Row, definition: Row, checkpointBefore: (sequence: bigint) => Row): void {
  const stops = definition.steps.some(terminalCompletion), hasRoutes = stops || definition.steps.some((row: Row) => row.referral_policy);
  check(stops ? Array.isArray(state.completion_checks) && Array.isArray(state.terminal_records) : state.completion_checks === undefined && state.terminal_records === undefined, 'STATE_INVALID');
  check(hasRoutes ? Array.isArray(state.referrals) : state.referrals === undefined, 'STATE_INVALID');
  const sequence = (eventId: string): bigint => BigInt(state.receipts.find((row: Row) => row.event_id === eventId)?.sequence ?? '0');
  const checkIds = new Set<string>(), checkOccurrences = new Set<string>();
  check(ordered((state.completion_checks ?? []).map((row: Row) => row.event_id)), 'STATE_INVALID');
  for (const row of state.completion_checks ?? []) {
    const receipt = state.receipts.find((receipt: Row) => receipt.event_id === row.event_id), permit = state.permits.find((permit: Row) => permit.permit_id === row.permit_digest), dispatch = state.dispatches.find((dispatch: Row) => dispatch.dispatch_digest === row.dispatch_digest);
    check(receipt && permit && dispatch && receipt.event_kind === 'COMPLETION_CHECKED' && receipt.event_digest === row.event_digest && receipt.permit_digest === permit.permit_id && dispatch.permit_digest === permit.permit_id && (dispatch.authorization_digest ?? null) === row.authorization_digest && sequence(dispatch.event_id) < sequence(row.event_id), 'STATE_INVALID');
    check(!checkIds.has(row.event_id) && !checkOccurrences.has(permit.occurrence.occurrence_id), 'STATE_INVALID'); checkIds.add(row.event_id); checkOccurrences.add(permit.occurrence.occurrence_id);
    const step = definition.steps.find((step: Row) => step.id === permit.occurrence.step_id);
    check(terminalCompletion(step) && same(dispatch.native_request, permit.native_request) && (['SENT', 'UNKNOWN', 'REJECTED'].includes(dispatch.attempt.status) || dispatch.acknowledgement.status === 'ACCEPTED'), 'STATE_INVALID');
    const dispatchReceipt = state.receipts.find((candidate: Row) => candidate.event_id === dispatch.event_id && candidate.event_kind === 'DISPATCH_OBSERVED');
    const authorization = (state.authorizations ?? []).find((candidate: Row) => candidate.authorization_digest === dispatch.authorization_digest);
    const exactAuthorization = authorization && authorization.permit_digest === permit.permit_id && same(authorization.native_request, dispatch.native_request) && same(authorization.connector, dispatch.connector);
    check(step.dispatch_gate ? exactAuthorization || dispatchReceipt?.reason_codes.includes('LATE_OR_PROHIBITED_DISPATCH') : dispatch.authorization_digest === undefined || exactAuthorization, 'STATE_INVALID');
    check(!state.outcomes.some((outcome: Row) => state.permits.find((candidate: Row) => candidate.permit_id === outcome.permit_digest)?.occurrence.occurrence_id === permit.occurrence.occurrence_id && outcome.native_evidence.status !== 'OUTCOME_UNKNOWN' && sequence(outcome.event_id) < sequence(row.event_id)), 'STATE_INVALID');
    const clocks = state.clocks.filter((clock: Row) => clock.status === 'AVAILABLE' && clock.source === permit.clock_source && (!state.receipts.some((receipt: Row) => receipt.event_kind === 'CLOCK' && receipt.details.some((detail: Row) => detail.kind === 'CLOCK' && detail.source === clock.source && detail.revision === clock.revision)) || state.receipts.some((receipt: Row) => receipt.event_kind === 'CLOCK' && BigInt(receipt.sequence) < sequence(row.event_id) && receipt.details.some((detail: Row) => detail.kind === 'CLOCK' && detail.source === clock.source && detail.revision === clock.revision)))).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1);
    const clock = clocks.at(-1); check(clock, 'STATE_INVALID');
    const reasons = admitLookup(row.lookup, lookupQuery(state, permit, dispatch, step, clock));
    const event = { schema: permit.schema.replace('/permit', '/runtime-event'), event_id: row.event_id, kind: 'COMPLETION_CHECKED', instance_id: state.instance_id, expected_state_revision: String(sequence(row.event_id) - 1n), expected_state_digest: receipt.state_before_digest, permit, authorization_digest: row.authorization_digest, dispatch_digest: row.dispatch_digest, lookup: row.lookup, clock_revision: clock.revision };
    check(row.event_digest === digest('runtime-event', event) && row.check_digest === digest('completion-check', omit(row, 'check_digest')) && same(row.reason_codes, reasons) && row.disposition === 'COMPLETION_FAILED' && receipt.disposition === row.disposition && same(receipt.reason_codes, reasons) && receipt.completion_check_digest === row.check_digest && same(receipt.details, [{ kind: 'COMPLETION_CHECK', check_digest: row.check_digest, status: row.lookup.status, reasons }]), 'STATE_INVALID');
    check(state.replays.find((replay: Row) => replay.event_id === row.event_id)?.budget_results.length === 0, 'STATE_INVALID');
  }
  check(state.receipts.filter((row: Row) => row.event_kind === 'COMPLETION_CHECKED').length === checkIds.size, 'STATE_INVALID');
  const rebuilt = structuredClone(state); rebuilt.terminal_records = []; rebuilt.referrals = []; rebuilt.outcomes = []; rebuilt.completion_checks = [];
  for (const receipt of state.receipts) {
    const previous = structuredClone(rebuilt);
    rebuilt.outcomes = state.outcomes.filter((row: Row) => sequence(row.event_id) <= BigInt(receipt.sequence)).map((row: Row) => {
      const body = structuredClone(row), original = state.receipts.find((receipt: Row) => receipt.event_id === row.event_id);
      body.conflicts_with_evidence_ids = row.conflicts_with_evidence_ids.filter((id: string) => sequence(state.outcomes.find((row: Row) => row.native_evidence.evidence_id === id).event_id) <= BigInt(receipt.sequence));
      body.disputed = row.kind === 'FOREIGN' || ['UNEXPECTED', 'CONFLICTING', 'LATE_AFTER_RELEASE'].includes(row.classification) || original.reason_codes.includes('BUDGET_EFFECT_DISPUTED') || body.conflicts_with_evidence_ids.length > 0;
      body.outcome_digest = digest('outcome', omit(body, 'outcome_digest')); return body;
    });
    rebuilt.completion_checks = (state.completion_checks ?? []).filter((row: Row) => sequence(row.event_id) <= BigInt(receipt.sequence));
    const permit = state.permits.find((row: Row) => row.permit_id === receipt.permit_digest);
    const proposal = state.proposals.find((row: Row) => row.event_id === receipt.event_id);
    const occurrence = permit?.occurrence ?? [...state.active, ...state.completed].find((row: Row) => row.occurrence.occurrence_id === proposal?.occurrence_id)?.occurrence;
    const event = { kind: receipt.event_kind, event_id: receipt.event_id, event_digest: receipt.event_digest, permit, occurrence };
    const input: Row = { disposition: receipt.disposition, reasons: receipt.reason_codes, details: receipt.details, decisionPermitDigest: receipt.permit_digest, authorityResultDigest: receipt.authority_result_digest };
    if (receipt.event_kind === 'EFFECT_OBSERVED' || receipt.event_kind === 'COMPLETION_CHECKED') {
      rebuilt.active = checkpointBefore(BigInt(receipt.sequence)).active;
      const current = rebuilt.active.find((row: Row) => row.occurrence.occurrence_id === permit?.occurrence.occurrence_id);
      const classification = rebuilt.outcomes.find((row: Row) => row.event_id === receipt.event_id)?.classification;
      if (current && current.status !== 'BLOCKED_DISPUTE' && receipt.event_kind === 'EFFECT_OBSERVED') {
        if (receipt.reason_codes.includes('BUDGET_EFFECT_DISPUTED') && !['UNKNOWN', 'UNEXPECTED', 'CONFLICTING', 'LATE_AFTER_RELEASE'].includes(classification)) current.status = 'BLOCKED_DISPUTE';
        else if (['UNKNOWN', 'UNEXPECTED', 'CONFLICTING', 'LATE_AFTER_RELEASE'].includes(classification)) current.status = 'OUTCOME_UNKNOWN';
      }
    }
    retainDecisionRecords(previous, rebuilt, definition, event, input);
    check(receipt.decision_basis_digest === input.decisionBasisDigest && receipt.terminal_digest === input.terminalDigest && receipt.proposal_authority_evaluation_digest === input.proposalAuthorityEvaluationDigest, 'STATE_INVALID');
  }
  check(same(state.terminal_records ?? [], rebuilt.terminal_records) && same(state.referrals ?? [], rebuilt.referrals), 'STATE_INVALID');
  for (const terminal of rebuilt.terminal_records) {
    const active = state.active.find((row: Row) => row.occurrence.occurrence_id === terminal.occurrence_id), completed = state.completed.find((row: Row) => row.occurrence.occurrence_id === terminal.occurrence_id);
    check(state.status === 'STOPPED' && (active || completed), 'STATE_INVALID');
    if (terminal.occurrence_status === 'BLOCKED_DISPUTE' && active) check(active.status === 'BLOCKED_DISPUTE', 'STATE_INVALID');
    if (terminal.occurrence_status === 'OUTCOME_UNKNOWN' && active) check(['OUTCOME_UNKNOWN', 'BLOCKED_DISPUTE'].includes(active.status), 'STATE_INVALID');
    if (terminal.occurrence_status === 'OUTCOME_UNKNOWN' && completed) check(completed.late && completed.selected_relationship_digest === null, 'STATE_INVALID');
  }
}
