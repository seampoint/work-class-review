import { AdmissionError, byteCompare, canonical, decodeArtifact, digest } from './canonical.ts';
import { evaluateAggregate, historyRequest, projectOperation, validateDefinition, validateHistoryRecord } from './aggregate.ts';
import { evaluateAuthority, validateAuthorityDefinition } from './authority.ts';
import { instant, instantText } from './time.ts';
import { ordered, predicateTypes, same, setOrder, typed } from './values.ts';
import { requireShape, shape, VERSION } from './schema.ts';
import type { RecordValue as Row } from './values.ts';

class Refusal extends Error {
  code: string;
  constructor(code: string) { super(code); this.code = code; }
}
function requireFact(condition: unknown, code: string): asserts condition { if (!condition) throw new Refusal(code); }
const clone = <T>(value: T): T => structuredClone(value);
const byId = (rows: Row[]): Row[] => rows.sort((a, b) => byteCompare(a.id, b.id));
const uniqueSorted = (values: string[]): string[] => [...new Set(values)].sort(byteCompare);
const occurrenceKey = (proposal: Row): string => digest('reservation-occurrence', { work_class: proposal.work_class, instance: proposal.instance, occurrence: proposal.occurrence });
const nativeRequest = (proposal: Row): Row => Object.fromEntries(['work_class', 'instance', 'occurrence', 'step', 'operation', 'interface', 'fields'].map(key => [key, proposal[key]]));
const sameNativeFact = (left: Row, right: Row): boolean => {
  const first = clone(left), second = clone(right);
  delete first.id; delete first.evidence_ref;
  delete second.id; delete second.evidence_ref;
  return same(first, second);
};
const open = (reservation: Row): boolean => ['OPEN', 'UNKNOWN', 'DISPUTED'].includes(reservation.status);
const stateDigest = (state: Row): string => digest('reservation-state', state);
const registered = (core: Row, anchor: string): Row | undefined => core.budgets.find((budget: Row) => budget.definition.anchor === anchor);
const fullHistory = (history: Row): boolean => history.status === 'AVAILABLE';

function second(value: string): bigint {
  try { requireFact(!value.includes('.'), 'INPUT_INVALID'); return instant(value); }
  catch (error) { if (error instanceof AdmissionError) throw new Refusal('INPUT_INVALID'); throw error; }
}
function within(interval: Row, at: bigint): boolean { return second(interval.valid_from) <= at && (interval.valid_until === null || at < second(interval.valid_until)); }
function completeDates(value: unknown): void {
  if (Array.isArray(value)) { value.forEach(completeDates); return; }
  if (!value || typeof value !== 'object') return;
  const row = value as Row;
  for (const key of ['valid_from', 'valid_until', 'at', 'occurred_at', 'returned_at', 'as_of', 'instant']) if (typeof row[key] === 'string') second(row[key]);
  if (row.valid_from && row.valid_until) requireFact(second(row.valid_from) < second(row.valid_until), 'INPUT_INVALID');
  Object.values(row).forEach(completeDates);
}
function embeddedReturns(value: unknown): void {
  if (Array.isArray(value)) { value.forEach(embeddedReturns); return; }
  if (!value || typeof value !== 'object') return;
  for (const [key, child] of Object.entries(value)) {
    if (key === 'act_bytes_base64') {
      try { decodeArtifact(child as string); }
      catch (error) { if (!(error instanceof AdmissionError)) throw error; throw new Refusal(error.code === 'NONCANONICAL' ? 'ARTIFACT_NONCANONICAL' : 'ARTIFACT_ENCODING_INVALID'); }
    } else embeddedReturns(child);
  }
}
function configurationAdmission(configuration: Row): void {
  requireShape('reservation.schema.json', 'configuration', configuration);
  requireFact(ordered(configuration.slots.map((slot: Row) => slot.anchor)) && new Set(configuration.slots.map((slot: Row) => slot.exposure_domain)).size === configuration.slots.length, 'INPUT_INVALID');
}
export function initialReservationState(configuration: Row, selectedPin: string): Row {
  configurationAdmission(configuration);
  return { schema: VERSION + '/reservation-state', specification_pin: selectedPin, core: { configuration: clone(configuration), revision: '0', last_clock: null, budgets: [], reservations: [], effects: [] }, receipts: [] };
}

function hostAdmission(core: Row, event: Row, host: Row): void {
  const configuration = core.configuration, registryDigest = digest('reservation-registry', configuration);
  requireFact(host.registry_digest === registryDigest, 'DEPENDENCY_MISMATCH');
  requireFact(ordered(host.administration_bases.map((basis: Row) => basis.id)) && setOrder(host.authenticated_records), 'INPUT_INVALID');
  const histories = event.kind === 'REGISTER' ? [event.payload.history] : event.payload.histories ?? [];
  const records = histories.map((history: Row) => ({ kind: 'HISTORY', record_digest: digest('budget-history', history), provider: history.provider, source: history.source }));
  if (event.payload.native) records.push({ kind: 'NATIVE_OUTCOME', record_digest: digest('reservation-native-outcome', event.payload.native), provider: event.payload.native.provider, source: event.payload.native.source });
  if (event.administration) records.push({ kind: 'ADMIN_RETURN', record_digest: digest('reservation-administration-return', event.administration.returned), provider: event.administration.returned.provider, source: event.administration.returned.source });
  const expected = new Set(records.map(canonical)), actual = new Set(host.authenticated_records.map(canonical));
  requireFact([...actual].every(row => expected.has(row as string)), 'DEPENDENCY_MISMATCH');
  requireFact([...expected].every(row => actual.has(row)), 'EVIDENCE_UNAVAILABLE');
  if (!event.administration) { requireFact(host.administration_bases.length === 0, 'DEPENDENCY_MISMATCH'); return; }
  const { act, returned } = event.administration, basis = host.administration_bases.find((basis: Row) => basis.id === act.basis);
  requireFact(host.administration_bases.length <= 1, 'DEPENDENCY_MISMATCH');
  requireFact(basis, 'EVIDENCE_UNAVAILABLE');
  const subject = digest('reservation-administration-subject', { registry_digest: registryDigest, event_id: event.id, expected_revision: event.expected_revision, kind: event.kind, clock: event.clock, payload: event.payload });
  requireFact(basis.registry_digest === registryDigest && basis.provider === configuration.administration_provider && basis.source === configuration.administration_source && basis.principal === configuration.principal && basis.role === configuration.administration_role, 'DEPENDENCY_MISMATCH');
  requireFact(act.actor === basis.actor && act.principal === basis.principal && act.role === basis.role && act.kind === event.kind && act.subject_digest === subject, 'DEPENDENCY_MISMATCH');
  requireFact(returned.act_digest === digest('reservation-administration-act', act) && same(decodeArtifact(returned.act_bytes_base64).value, act) && returned.actor === act.actor && returned.provider === configuration.administration_provider && returned.source === configuration.administration_source, 'DEPENDENCY_MISMATCH');
  requireFact(event.clock.status === 'AVAILABLE' && basis.at === event.clock.instant && act.occurred_at === event.clock.instant && returned.returned_at === event.clock.instant, 'ADMINISTRATION_NOT_ESTABLISHED');
  requireFact(act.disposition === 'ACCEPT' && !basis.revoked && basis.operations.includes(event.kind) && within(basis.validity, second(event.clock.instant)), 'ADMINISTRATION_NOT_ESTABLISHED');
}

function definitionAdmission(configuration: Row, definition: Row, authorizations: Row[]): void {
  const slot = configuration.slots.find((slot: Row) => slot.anchor === definition.anchor);
  requireFact(slot && slot.exposure_domain === definition.exposure_domain && definition.principal === configuration.principal, 'DEPENDENCY_MISMATCH');
  const { definition: aggregateDefinition } = validateDefinition(definition.aggregate), aggregate = aggregateDefinition.aggregate;
  requireFact(['LT', 'LTE'].includes(aggregate.operator) && ['ROLLING', 'CALENDAR'].includes(aggregate.window.kind) && aggregate.time.precision === 'SECOND' && aggregate.pending_policy === 'INCLUDE_ALL_RESERVED', 'UNSUPPORTED_RELATION');
  requireFact(aggregate.time.clock_source === configuration.clock_source && BigInt(definition.reservation_policy.permit_seconds) > 0n, 'INPUT_INVALID');
  const source = aggregate.committed_source;
  requireFact(same(source.qualifier, { kind: 'BOOLEAN', value: true }), 'UNSUPPORTED_RELATION');
  const sourceFields = [...source.key_fields, ...(source.contribution.kind === 'COUNT' ? [] : [source.contribution.field])];
  requireFact(new Set(sourceFields).size === sourceFields.length && ordered(definition.contributor_classes) && ordered(authorizations.map(row => row.id)), 'INPUT_INVALID');
  const budgetDigest = digest('budget-definition', definition), types = new Map<string, Row>(aggregateDefinition.types.map((type: Row) => [type.id, type]));
  const supported = new Set<string>();
  for (const authorization of authorizations) {
    const admitted = validateAuthorityDefinition(authorization.authority_definition);
    requireFact(admitted.status === 'ACCEPTED', admitted.code ?? 'INPUT_INVALID');
    const { work_class: work, envelope } = authorization.authority_definition, step = work.steps.find((step: Row) => step.id === authorization.step);
    requireFact(authorization.budget_digest === budgetDigest && authorization.work_class === work.id && authorization.work_class_digest === digest('authority-work-class', work) && authorization.envelope_digest === digest('authority-envelope', envelope) && authorization.principal === definition.principal && envelope.principal === definition.principal && definition.contributor_classes.includes(work.id) && envelope.limits.shared_budgets.includes(definition.anchor), 'DEPENDENCY_MISMATCH');
    requireFact(step, 'REFERENCE_INVALID');
    const identity = canonical([authorization.work_class_digest, authorization.envelope_digest, authorization.step]);
    requireFact(!supported.has(identity), 'INPUT_INVALID'); supported.add(identity);
    requireFact(ordered(authorization.projection.map((row: Row) => row.budget_field)) && new Set(authorization.projection.map((row: Row) => row.native_field)).size === authorization.projection.length, 'INPUT_INVALID');
    for (const row of authorization.projection) {
      const field = step.fields.find((field: Row) => field.name === row.native_field), nativeType = work.types.find((type: Row) => type.id === row.native_type), budgetType = types.get(row.budget_type);
      requireFact(field && nativeType && budgetType && field.type_ref === row.native_type, 'REFERENCE_INVALID');
      requireFact(nativeType.kind === budgetType.kind && nativeType.unit === budgetType.unit && nativeType.nonnegative === budgetType.nonnegative, 'TYPE_INVALID');
    }
    const fields = new Map<string, string>(authorization.projection.map((row: Row) => [row.budget_field, row.budget_type]));
    for (const mapping of aggregate.mappings.filter((mapping: Row) => mapping.step_ids.includes(step.id))) {
      mapping.key_fields.forEach((name: string, index: number) => {
        requireFact(fields.has(name), 'REFERENCE_INVALID');
        requireFact(fields.get(name) === aggregate.key_types[index], 'TYPE_INVALID');
      });
      if (mapping.contribution.kind !== 'COUNT') {
        requireFact(fields.has(mapping.contribution.field), 'REFERENCE_INVALID');
        requireFact(fields.get(mapping.contribution.field) === (mapping.contribution.kind === 'SUM' ? aggregate.result_type : aggregate.element_type), 'TYPE_INVALID');
      }
      predicateTypes(mapping.qualifier, fields, types as any);
    }
  }
}

function historyAdmission(budget: Row, history: Row, clock: Row, prior?: Row): void {
  const source = budget.definition.aggregate.aggregate.committed_source;
  requireFact(history.budget_digest === budget.definition_digest && history.provider === source.provider && history.source === source.source, 'DEPENDENCY_MISMATCH');
  if (!fullHistory(history)) return;
  requireFact(BigInt(history.revision) === BigInt(history.journal.length), 'INPUT_INVALID');
  requireFact(clock.status !== 'AVAILABLE' || second(history.as_of) <= second(clock.instant), 'INPUT_INVALID');
  if (prior && fullHistory(prior)) requireFact(history.journal.length >= prior.journal.length && same(history.journal.slice(0, prior.journal.length), prior.journal), 'INPUT_INVALID');
  for (const [index, row] of history.journal.entries()) {
    requireFact(row.sequence === String(index + 1), 'INPUT_INVALID'); validateHistoryRecord(budget.definition.aggregate, row.event);
    if (row.event.state === 'ACTIVE') requireFact(second(row.event.occurred_at) <= second(history.as_of), 'INPUT_INVALID');
  }
}
function historyReason(budget: Row, history: Row, clock: Row): string | null {
  if (!fullHistory(history)) return 'HISTORY_' + history.status;
  if (clock.status !== 'AVAILABLE') return 'CLOCK_UNAVAILABLE';
  const freshness = budget.definition.aggregate.aggregate.committed_source.freshness;
  if (freshness.kind === 'NONE') return null;
  if (freshness.kind === 'EXACT_REVISION') return history.revision === freshness.revision ? null : 'HISTORY_STALE';
  const age = second(clock.instant) - second(history.as_of);
  const scale = freshness.seconds.split('.')[1]?.length ?? 0;
  const coefficient = BigInt(freshness.seconds.replace('.', ''));
  return age * 10n ** BigInt(scale) <= coefficient * 1000000000n ? null : 'HISTORY_STALE';
}
function selectedAuthorization(budget: Row, authority: Row): Row {
  const W = digest('authority-work-class', authority.work_class), E = digest('authority-envelope', authority.envelope);
  const candidates = budget.authorizations.filter((authorization: Row) => authorization.work_class_digest === W && authorization.envelope_digest === E && authorization.step === authority.proposal.step);
  requireFact(candidates.length === 1, 'DEPENDENCY_MISMATCH'); return candidates[0];
}
function projectNative(budget: Row, authorization: Row, native: Row, occurrence: string): Row {
  const fields = new Map<string, Row>(native.fields.map((field: Row) => [field.name, field.value]));
  const projected = authorization.projection.map((row: Row) => {
    const value = fields.get(row.native_field); requireFact(value && value.type_ref === row.native_type, 'TYPE_INVALID');
    return { name: row.budget_field, value: { type_ref: row.budget_type, value: value.value } };
  });
  return { occurrence, step: native.step, fields: projected.sort((a: Row, b: Row) => byteCompare(a.name, b.name)) };
}
function projectedContributions(budget: Row, operation: Row): Row[] {
  return projectOperation(budget.definition.aggregate, operation).map(row => ({ anchor: budget.definition.anchor, mapping: row.mapping!, occurrence: row.occurrence, key: row.key, value: row.value }));
}
function pending(core: Row, anchor: string, excluded: string | null): Row[] {
  return core.reservations.filter((reservation: Row) => reservation.id !== excluded && open(reservation)).flatMap((reservation: Row) => reservation.contributions.filter((row: Row) => row.anchor === anchor).map((row: Row) => ({ reservation: reservation.id, mapping: row.mapping, occurrence: row.occurrence, key: row.key, contribution: row.value }))).sort((a: Row, b: Row) => byteCompare(canonical([a.reservation, a.mapping, a.occurrence, a.key]), canonical([b.reservation, b.mapping, b.occurrence, b.key])));
}
function committedRecord(budget: Row, contribution: Row, effectId: string, at: string): Row {
  const source = budget.definition.aggregate.aggregate.committed_source;
  const fields = source.key_fields.map((name: string, index: number) => ({ name, value: contribution.key[index] }));
  if (source.contribution.kind !== 'COUNT') fields.push({ name: source.contribution.field, value: contribution.value });
  fields.sort((a: Row, b: Row) => byteCompare(a.name, b.name));
  return { id: digest('reservation-committed-event', { budget_digest: budget.definition_digest, effect_id: effectId, mapping: contribution.mapping }), state: 'ACTIVE', occurred_at: at, fields };
}
function latestHistory(history: Row): Map<string, Row> { return new Map(history.journal.map((row: Row) => [row.event.id, row.event])); }
function affectedAnchors(reservation: Row): string[] { return uniqueSorted(reservation.contributions.map((row: Row) => row.anchor)); }
function compatibleNativeSources(budgets: Row[]): boolean {
  if (budgets.length < 2) return true;
  const first = budgets[0].definition.reservation_policy;
  return budgets.slice(1).every((budget: Row) => {
    const policy = budget.definition.reservation_policy;
    return same(policy.settlement, first.settlement) && same(policy.no_effect, first.no_effect);
  });
}

function reconcile(core: Row, budgets: Row[], histories: Row[], clock: Row): void {
  for (const budget of budgets) {
    const history = histories.find((history: Row) => history.budget_digest === budget.definition_digest)!;
    if (!historyReason(budget, history, clock)) budget.history = clone(history);
  }
  for (const reservation of core.reservations) if (reservation.status === 'SETTLED') {
    const effect = core.effects.find((effect: Row) => effect.reservation === reservation.id && effect.native.effect_id === reservation.matched_effect && effect.disposition === 'MATCHED');
    requireFact(effect, 'STATE_INVALID');
    for (const contribution of reservation.contributions) {
      const budget = registered(core, contribution.anchor)!;
      const expected = committedRecord(budget, contribution, effect.native.effect_id, effect.native.occurred_at);
      const actual = latestHistory(budget.history).get(expected.id);
      if (!actual || !same(actual, expected)) { reservation.status = 'DISPUTED'; break; }
    }
  }
}

type Transition = { core: Row; decision: string; reservation: string | null; budgets: Row[]; authority_result: Row | null; reasons: string[] };
function transition(coreValue: Row, event: Row, host: Row, selectedPin: string): Transition {
  const core = clone(coreValue), result: Transition = { core, decision: 'WITHHELD', reservation: null, budgets: [], authority_result: null, reasons: [] };
  requireFact(event.clock.source === core.configuration.clock_source, 'DEPENDENCY_MISMATCH');
  completeDates(event); completeDates(host); hostAdmission(core, event, host);
  if (event.kind === 'REGISTER') {
    const { definition, authorizations, history } = event.payload;
    definitionAdmission(core.configuration, definition, authorizations);
    const existing = registered(core, definition.anchor), identity = digest('budget-definition', definition);
    requireFact(!existing || existing.definition_digest === identity, 'DEFINITION_CONFLICT');
    requireFact(!existing, 'DEFINITION_CONFLICT');
    const budget = { definition, definition_digest: identity, authorizations, history };
    historyAdmission(budget, history, event.clock);
    requireFact(fullHistory(history) && !historyReason(budget, history, event.clock), 'EVIDENCE_UNAVAILABLE');
    core.budgets.push(clone(budget)); core.budgets.sort((a: Row, b: Row) => byteCompare(a.definition.anchor, b.definition.anchor)); result.decision = 'REGISTERED';
  } else if (event.kind === 'RESERVE' || event.kind === 'RENEW') {
    const { authority, histories } = event.payload;
    requireFact(same(authority.clock, event.clock), 'DEPENDENCY_MISMATCH');
    const anchors = authority.envelope.limits.shared_budgets;
    requireFact(anchors.length > 0, 'UNSUPPORTED_RELATION');
    const budgets = anchors.map((anchor: string) => { const budget = registered(core, anchor); requireFact(budget, 'REFERENCE_INVALID'); return budget; });
    requireFact(ordered(histories.map((history: Row) => history.budget_digest)) && same(histories.map((history: Row) => history.budget_digest), budgets.map((budget: Row) => budget.definition_digest).sort(byteCompare)), 'DEPENDENCY_MISMATCH');
    for (const budget of budgets) historyAdmission(budget, histories.find((history: Row) => history.budget_digest === budget.definition_digest), event.clock, budget.history);
    requireFact(compatibleNativeSources(budgets), 'UNSUPPORTED_RELATION');
    const key = occurrenceKey(authority.proposal), existing = core.reservations.find((reservation: Row) => reservation.occurrence_key === key);
    if (event.kind === 'RESERVE') requireFact(!existing, 'OCCURRENCE_CONFLICT');
    else {
      requireFact(existing && existing.id === event.payload.reservation, 'RESERVATION_NOT_FOUND');
      requireFact(existing.proposal_digest === digest('authority-proposal', authority.proposal) && existing.envelope_digest === digest('authority-envelope', authority.envelope), 'OCCURRENCE_CONFLICT');
      result.reservation = existing.id;
    }
    const operations = new Map<string, Row>(), contributions: Row[] = [];
    for (const budget of budgets) {
      const authorization = selectedAuthorization(budget, authority), operation = projectNative(budget, authorization, authority.proposal, key);
      const projected = projectedContributions(budget, operation); requireFact(projected.length > 0, 'UNSUPPORTED_RELATION');
      operations.set(budget.definition.anchor, operation); contributions.push(...projected);
    }
    contributions.sort((a, b) => byteCompare(canonical([a.anchor, a.mapping, a.occurrence, a.key]), canonical([b.anchor, b.mapping, b.occurrence, b.key])));
    if (existing) requireFact(same(existing.contributions, contributions), 'OCCURRENCE_CONFLICT');
    const authorityResult = evaluateAuthority(authority, selectedPin); result.authority_result = authorityResult;
    if (authorityResult.status !== 'READY_FOR_RESERVATION') result.reasons.push('AUTHORITY_WITHHELD');
    if (event.clock.status === 'UNAVAILABLE') { result.reasons = ['CLOCK_UNAVAILABLE']; return result; }
    for (const budget of budgets) { const reason = historyReason(budget, histories.find((history: Row) => history.budget_digest === budget.definition_digest), event.clock); if (reason) result.reasons.push(reason); }
    reconcile(core, budgets, histories, event.clock);
    for (const budget of budgets) {
      const anchor = budget.definition.anchor;
      const keys = contributions.filter(row => row.anchor === anchor).map(row => row.key);
      const effectsBlock = core.effects.some((effect: Row) => effect.disposition === 'DISPUTED' && effect.blocked_partitions.some((blocked: Row) => blocked.anchor === anchor && (blocked.key === null || keys.some(key => same(key, blocked.key)))));
      const reservationsBlock = core.reservations.some((reservation: Row) => reservation.status === 'DISPUTED' && reservation.contributions.some((row: Row) => row.anchor === anchor && keys.some(key => same(key, row.key))));
      if (effectsBlock || reservationsBlock) result.reasons.push('EXPOSURE_DISPUTED');
    }
    if (existing && !['OPEN', 'UNKNOWN'].includes(existing.status)) result.reasons.push('EXPOSURE_DISPUTED');
    if (result.reasons.length) return result;
    for (const budget of budgets) {
      const anchor = budget.definition.anchor, request = historyRequest(budget.definition.aggregate, [operations.get(anchor)!], pending(core, anchor, existing?.id ?? null), event.clock, budget.history, selectedPin);
      const evaluated = evaluateAggregate(request, selectedPin); result.budgets.push({ anchor, result: evaluated });
      if (evaluated.status !== 'SATISFIED') result.reasons.push(evaluated.status === 'VIOLATED' ? 'BOUND_VIOLATED' : 'HISTORY_INCOMPLETE');
    }
    if (result.reasons.length) return result;
    const duration = budgets.map((budget: Row) => BigInt(budget.definition.reservation_policy.permit_seconds)).reduce((a: bigint, b: bigint) => a < b ? a : b);
    let until: string;
    try { until = instantText(second(event.clock.instant) + duration * 1000000000n, false); }
    catch (error) { if (error instanceof AdmissionError) throw new Refusal('LIMIT_EXCEEDED'); throw error; }
    if (existing) {
      existing.authority = clone(authority); existing.authority_result = clone(authorityResult); existing.permit_until = until; result.decision = 'RENEWED';
    } else {
      core.reservations.push({ id: event.id, occurrence_key: key, proposal_digest: digest('authority-proposal', authority.proposal), envelope_digest: digest('authority-envelope', authority.envelope), authority: clone(authority), authority_result: clone(authorityResult), contributions, created_at: event.clock.instant, permit_until: until, status: 'OPEN', matched_effect: null });
      byId(core.reservations); result.decision = 'RESERVED'; result.reservation = event.id;
    }
  } else {
    return nativeTransition(core, event, result);
  }
  return result;
}

function nativeTransition(core: Row, event: Row, result: Transition): Transition {
  const native = event.payload.native, reservation = core.reservations.find((row: Row) => row.id === native.reservation);
  requireFact(ordered(native.request.fields.map((field: Row) => field.name)), 'INPUT_INVALID');
  requireFact(native.outcome === 'EFFECT' ? native.effect_id !== null && native.occurred_at !== null && !native.rules_out_past_and_future_effects : native.effect_id === null && native.occurred_at === null && native.rules_out_past_and_future_effects === (native.outcome === 'NO_EFFECT'), 'INPUT_INVALID');
  requireFact(native.completion_mismatch ? ['NATIVE_REQUEST_MISMATCH', 'UNEXPECTED_EFFECT'].includes(native.mismatch_reason) : native.mismatch_reason === null, 'INPUT_INVALID');
  if (native.outcome === 'UNKNOWN' || native.outcome === 'NO_EFFECT') {
    requireFact(native.observed_request === null && native.actual_fields.length === 0 && native.collections.length === 0, 'INPUT_INVALID');
    if (!native.completion_mismatch) requireFact(native.mismatch_reason === null, 'INPUT_INVALID');
  }
  // RES-WIRE-003: a missing or unprojectable actual field permits a null observed request only with completion_mismatch:true.
  requireFact(native.outcome !== 'EFFECT' || native.observed_request !== null || native.completion_mismatch, 'INPUT_INVALID');
  requireFact(event.kind === 'RELEASE' ? native.outcome === 'NO_EFFECT' : native.outcome !== 'NO_EFFECT', 'INPUT_INVALID');
  if (event.kind === 'RELEASE') requireFact(reservation, 'RESERVATION_NOT_FOUND');
  const histories = event.payload.histories ?? [];
  const budgets: Row[] = reservation ? affectedAnchors(reservation).map(anchor => registered(core, anchor)!) : histories.map((history: Row) => {
    const budget = core.budgets.find((budget: Row) => budget.definition_digest === history.budget_digest); requireFact(budget, 'REFERENCE_INVALID'); return budget;
  });
  requireFact(budgets.length > 0, 'REFERENCE_INVALID');
  for (const budget of budgets) {
    const provider = event.kind === 'RELEASE' ? budget.definition.reservation_policy.no_effect : budget.definition.reservation_policy.settlement;
    requireFact(native.provider === provider.provider && native.source === provider.source, 'DEPENDENCY_MISMATCH');
  }
  if (event.kind === 'SETTLE') {
    requireFact(ordered(histories.map((history: Row) => history.budget_digest)) && same(histories.map((history: Row) => history.budget_digest), budgets.map((budget: Row) => budget.definition_digest).sort(byteCompare)), 'DEPENDENCY_MISMATCH');
    for (const budget of budgets) historyAdmission(budget, histories.find((history: Row) => history.budget_digest === budget.definition_digest), event.clock, budget.history);
  }
  const prior = core.effects.find((effect: Row) => effect.id === native.id);
  if (prior) {
    requireFact(same(prior.native, native), 'INPUT_INVALID');
    result.reservation = prior.reservation;
    result.decision = { MATCHED: 'SETTLED', UNKNOWN: 'UNKNOWN', RELEASED: 'RELEASED', DISPUTED: 'EFFECT_DISPUTED' }[prior.disposition as string]!;
    if (prior.disposition === 'DISPUTED') result.reasons = [prior.reason];
    return result;
  }
  const duplicate = core.effects.find((effect: Row) => sameNativeFact(effect.native, native));
  if (duplicate) {
    result.reservation = duplicate.reservation;
    result.decision = { MATCHED: 'SETTLED', UNKNOWN: 'UNKNOWN', RELEASED: 'RELEASED', DISPUTED: 'EFFECT_DISPUTED' }[duplicate.disposition as string]!;
    if (duplicate.disposition === 'DISPUTED') result.reasons = [duplicate.reason];
    return result;
  }
  const anchors = uniqueSorted(budgets.map(budget => budget.definition.anchor));
  const retain = (disposition: string, decision: string, reason: string): Transition => {
    const blocked: Row[] = [];
    if (disposition === 'DISPUTED') for (const budget of budgets) {
      const anchor = budget.definition.anchor;
      if (reservation) blocked.push(...reservation.contributions.filter((row: Row) => row.anchor === anchor).map((row: Row) => ({ anchor, key: row.key })));
      let actual: Row[] | null = native.observed_request === null && !native.completion_mismatch ? [] : null;
      if (reservation) {
        const original = reservation.authority, proposal = original.proposal, request = native.observed_request;
        if (request !== null && request.work_class === proposal.work_class && request.step === proposal.step && request.operation === proposal.operation && request.interface === proposal.interface) {
          const step = original.work_class.steps.find((step: Row) => step.id === proposal.step), fields = new Map<string, Row>(request.fields.map((field: Row) => [field.name, field.value]));
          if (fields.size === step.fields.length && step.fields.every((field: Row) => fields.get(field.name)?.type_ref === field.type_ref)) {
            try {
              const types = new Map(original.work_class.types.map((type: Row) => [type.id, type]));
              for (const value of fields.values()) typed(value as any, types as any);
              const authorization = selectedAuthorization(budget, original), operation = projectNative(budget, authorization, request, reservation.occurrence_key);
              const rows = projectedContributions(budget, operation);
              if (rows.length) actual = rows.map(row => ({ anchor, key: row.key }));
            } catch (error) { if (!(error instanceof Refusal || error instanceof AdmissionError)) throw error; }
          }
        }
      }
      blocked.push(...(actual ?? [{ anchor, key: null }]));
    }
    const blockedAnchors = new Set(blocked.filter(row => row.key === null).map(row => row.anchor));
    const effectiveBlocked = blocked.filter(row => row.key === null || !blockedAnchors.has(row.anchor));
    const blockedPartitions = [...new Map(effectiveBlocked.map(row => [canonical(row), row])).entries()].sort(([a], [b]) => byteCompare(a, b)).map(([, row]) => row);
    core.effects.push({ id: native.id, native: clone(native), native_digest: digest('reservation-native-outcome', native), reservation: native.reservation, disposition, affected_anchors: anchors, blocked_partitions: blockedPartitions, reason });
    byId(core.effects); result.reservation = native.reservation; result.decision = decision;
    if (disposition === 'DISPUTED') { result.reasons = [reason]; if (reservation) reservation.status = 'DISPUTED'; }
    return result;
  };
  if (event.kind === 'RELEASE') {
    if (native.completion_mismatch) return retain('DISPUTED', 'EFFECT_DISPUTED', native.mismatch_reason);
    // RES-WIRE-004: a clean record whose attributed request differs is retained as unexpected for RELEASE as for SETTLE.
    if (!same(native.request, nativeRequest(reservation!.authority.proposal))) return retain('DISPUTED', 'EFFECT_DISPUTED', 'UNEXPECTED_EFFECT');
    // RES-WIRE-004: against an already DISPUTED reservation the decision and reservation stay DISPUTED; a clean no-effect
    // that contradicts a retained matched effect takes UNEXPECTED_EFFECT below, otherwise AFFIRMATIVE_NO_EFFECT.
    if (reservation!.status === 'DISPUTED' && reservation!.matched_effect === null) return retain('DISPUTED', 'EFFECT_DISPUTED', 'AFFIRMATIVE_NO_EFFECT');
    if (!['OPEN', 'UNKNOWN'].includes(reservation!.status) || core.effects.some((effect: Row) => effect.reservation === reservation!.id && effect.native.outcome === 'EFFECT')) return retain('DISPUTED', 'EFFECT_DISPUTED', 'UNEXPECTED_EFFECT');
    requireFact(event.administration, 'EVIDENCE_UNAVAILABLE');
    reservation!.status = 'RELEASED'; return retain('RELEASED', 'RELEASED', 'AFFIRMATIVE_NO_EFFECT');
  }
  reconcile(core, budgets, histories, event.clock);
  if (!reservation) return retain('DISPUTED', 'EFFECT_DISPUTED', 'UNKNOWN_RESERVATION');
  // RESERVATION-RECORDS: "SETTLED or RELEASED; later UNKNOWN" retains the evidence and the prior terminal
  // state with receipt UNKNOWN and changes no exposure. Only a later EFFECT is late after release.
  const reserved = nativeRequest(reservation.authority.proposal);
  if (reservation.status === 'RELEASED' && native.outcome === 'UNKNOWN' && !native.completion_mismatch && same(native.request, reserved)) return retain('UNKNOWN', 'UNKNOWN', 'UNKNOWN_OUTCOME');
  if (reservation.status === 'RELEASED' && native.outcome === 'EFFECT') return retain('DISPUTED', 'EFFECT_DISPUTED', 'LATE_EFFECT_AFTER_RELEASE');
  if (native.completion_mismatch || !same(native.request, reserved)) return retain('DISPUTED', 'EFFECT_DISPUTED', native.mismatch_reason ?? 'UNEXPECTED_EFFECT');
  // RES-WIRE-003/004: a matching settlement also requires the observed request to equal the reserved request.
  if (native.outcome === 'EFFECT' && !same(native.observed_request, reserved)) return retain('DISPUTED', 'EFFECT_DISPUTED', 'UNEXPECTED_EFFECT');
  const disputed = reservation.status === 'DISPUTED';
  if (native.outcome === 'UNKNOWN') {
    if (disputed) return retain('DISPUTED', 'EFFECT_DISPUTED', 'UNKNOWN_OUTCOME');
    if (reservation.status !== 'SETTLED') reservation.status = 'UNKNOWN';
    return retain('UNKNOWN', 'UNKNOWN', 'UNKNOWN_OUTCOME');
  }
  // RES-WIRE-004: whatever the prior status, UNEXPECTED_EFFECT precedes HISTORY_UNCORROBORATED. Exact and same-fact
  // duplicates returned above, so any retained effect for this occurrence is either a second distinct effect
  // identifier or a changed conclusive fact under a retained one.
  if (core.effects.some((effect: Row) => effect.reservation === reservation.id && effect.native.outcome === 'EFFECT')) return retain('DISPUTED', 'EFFECT_DISPUTED', 'UNEXPECTED_EFFECT');
  let corroborated = true;
  for (const contribution of reservation.contributions) {
    const budget = registered(core, contribution.anchor)!, history = histories.find((history: Row) => history.budget_digest === budget.definition_digest);
    if (historyReason(budget, history, event.clock)) { corroborated = false; continue; }
    const expected = committedRecord(budget, contribution, native.effect_id, native.occurred_at), actual = latestHistory(history).get(expected.id);
    if (!actual || !same(actual, expected)) corroborated = false;
  }
  if (!corroborated) return retain('DISPUTED', 'EFFECT_DISPUTED', 'HISTORY_UNCORROBORATED');
  if (disputed) return retain('DISPUTED', 'EFFECT_DISPUTED', 'MATCHED_EFFECT');
  reservation.status = 'SETTLED'; reservation.matched_effect = native.effect_id;
  return retain('MATCHED', 'SETTLED', 'MATCHED_EFFECT');
}

function append(state: Row, event: Row, host: Row, selectedPin: string): Row {
  requireFact(event.expected_revision === state.core.revision, 'REVISION_CONFLICT');
  requireFact(event.clock.status !== 'AVAILABLE' || state.core.last_clock === null || second(event.clock.instant) >= second(state.core.last_clock), 'CLOCK_INVALID');
  const outcome = transition(state.core, event, host, selectedPin);
  if (event.payload.native) {
    const prior = state.receipts.find((row: Row) => row.event.payload.native?.id === event.payload.native.id);
    requireFact(!prior || same(prior.event.payload.native, event.payload.native), 'INPUT_INVALID');
  }
  outcome.core.revision = (BigInt(state.core.revision) + 1n).toString();
  if (event.clock.status === 'AVAILABLE') outcome.core.last_clock = event.clock.instant;
  const receipt = { event_digest: digest('reservation-event', event), prior_state_digest: stateDigest(state), revision: outcome.core.revision, next_core_digest: digest('reservation-core', outcome.core), decision: outcome.decision, reservation: outcome.reservation, budgets: outcome.budgets, authority_result: outcome.authority_result, reasons: uniqueSorted(outcome.reasons) };
  return { schema: VERSION + '/reservation-state', specification_pin: selectedPin, core: outcome.core, receipts: [...state.receipts, { event: clone(event), host_evidence: clone(host), receipt }] };
}
export function stateAdmission(state: Row, selectedPin: string): void {
  requireShape('reservation.schema.json', 'state', state);
  requireFact(state.specification_pin === selectedPin, 'STATE_INVALID');
  let replay = initialReservationState(state.core.configuration, selectedPin);
  const ids = new Set<string>();
  try {
    for (const record of state.receipts) {
      requireFact(!ids.has(record.event.id), 'STATE_INVALID'); ids.add(record.event.id);
      replay = append(replay, record.event, record.host_evidence, selectedPin);
      requireFact(same(replay.receipts.at(-1).receipt, record.receipt), 'STATE_INVALID');
    }
    requireFact(same(replay, state), 'STATE_INVALID');
  } catch (error) { if (error instanceof Refusal || error instanceof AdmissionError) throw new Refusal('STATE_INVALID'); throw error; }
}
export function aggregateStep(input: unknown, selectedPin: string): Row {
  if (!shape('reservation.schema.json', 'input', input)) return { status: 'REFUSED', code: 'SCHEMA_INVALID', path: '' };
  const request = input as Row;
  try {
    embeddedReturns(input);
    requireFact(request.specification_pin === selectedPin && request.state_digest === stateDigest(request.state) && request.host_evidence.registry_digest === digest('reservation-registry', request.state.core.configuration) && request.event.clock.source === request.state.core.configuration.clock_source, 'DEPENDENCY_MISMATCH');
    stateAdmission(request.state, selectedPin);
    const prior = request.state.receipts.find((row: Row) => row.event.id === request.event.id);
    if (prior) {
      requireFact(same(prior.event, request.event), 'REPLAY_CONFLICT');
      return { status: 'TRANSITION', receipt: prior.receipt, receipt_digest: digest('reservation-receipt', prior.receipt), state: request.state, state_digest: request.state_digest, replay: true };
    }
    const state = append(request.state, request.event, request.host_evidence, selectedPin), receipt = state.receipts.at(-1).receipt;
    return { status: 'TRANSITION', receipt, receipt_digest: digest('reservation-receipt', receipt), state, state_digest: stateDigest(state), replay: false };
  } catch (error) {
    if (!(error instanceof Refusal || error instanceof AdmissionError)) throw error;
    return { status: 'REFUSED', code: error.code, path: '', state: request.state, state_digest: request.state_digest };
  }
}
