import { AdmissionError, byteCompare, canonical, decodeArtifact, digest } from './canonical.ts';
import { evaluateAggregate, historyRequest, projectOperation, validateDefinition, validateHistoryRecord } from './aggregate.ts';
import { evaluateAuthority, validateAuthorityDefinition } from './authority.ts';
import { instant, instantText } from './time.ts';
import { ordered, predicateTypes, same, setOrder, typed } from './values.ts';
import { requireShape, shape, VERSION } from './schema.ts';
import type { RecordValue as Row } from './values.ts';
import { admitHistorySlot, admitRequestedKey, mediatedSlot, newSlot, occurrenceOwns, seedHistory } from './key-history.ts';
import { recoveryAllowanceExceeded, recoveryAllowanceRows, recoveryAuthority, recoveryCoverage, recoveryDisposition, recoveryFact, recoveryHostAdmission, recoveryPacket, recoveryPolicyCurrent, recoveryPolicyTransition, recoverySorted } from './recovery.ts';
import { independentActors, selectedAuthorityAct } from './human-decisions.ts';
import { compare, decimal, decimalText, sum } from './math.ts';

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
function completeDates(value: unknown, deferredHistories: ReadonlySet<unknown> = new Set<unknown>()): void {
  if (deferredHistories.has(value)) return;
  if (Array.isArray(value)) { value.forEach(child => completeDates(child, deferredHistories)); return; }
  if (!value || typeof value !== 'object') return;
  const row = value as Row;
  for (const key of ['valid_from', 'valid_until', 'at', 'occurred_at', 'returned_at', 'as_of', 'instant']) if (typeof row[key] === 'string' && !(key === 'at' && row[key] === 'CLOCK')) second(row[key]);
  if (row.valid_from && row.valid_until) requireFact(second(row.valid_from) < second(row.valid_until), 'INPUT_INVALID');
  Object.values(row).forEach(child => completeDates(child, deferredHistories));
}
function embeddedReturns(value: unknown): void {
  const errors = new Set<string>(), pending: unknown[] = [value];
  while (pending.length) {
    const item = pending.pop();
    if (Array.isArray(item)) { for (const child of item) pending.push(child); continue; }
    if (!item || typeof item !== 'object') continue;
    for (const [key, child] of Object.entries(item)) {
      if (key === 'act_bytes_base64') {
        try { decodeArtifact(child as string); }
        catch (error) {
          if (!(error instanceof AdmissionError)) throw error;
          errors.add(['NONCANONICAL', 'NUMBER_FORBIDDEN'].includes(error.code) ? 'ARTIFACT_NONCANONICAL' : 'ARTIFACT_ENCODING_INVALID');
        }
      } else pending.push(child);
    }
  }
  // Phase 1 covers every current and retained carrier before dependency checks.
  for (const code of ['ARTIFACT_ENCODING_INVALID', 'ARTIFACT_NONCANONICAL']) if (errors.has(code)) throw new Refusal(code);
}
function configurationAdmission(configuration: Row): void {
  requireShape('reservation.schema.json', 'configuration', configuration);
  requireFact(ordered(configuration.slots.map((slot: Row) => slot.anchor)) && new Set(configuration.slots.map((slot: Row) => slot.exposure_domain)).size === configuration.slots.length, 'INPUT_INVALID');
  const exclusive = configuration.exclusive_slots ?? [];
  requireFact(ordered(exclusive.map((slot: Row) => slot.slot)) && new Set(exclusive.map((slot: Row) => slot.slot)).size === exclusive.length, 'INPUT_INVALID');
  for (const slot of exclusive) { requireFact(ordered(slot.authorized_classes) && BigInt(slot.permit_seconds) > 0n, 'INPUT_INVALID'); admitHistorySlot(slot); }
  if (configuration.recovery) requireFact(ordered(configuration.recovery.policy_families) && ordered(configuration.recovery.exception_profiles), 'INPUT_INVALID');
}
export function initialReservationState(configuration: Row, selectedPin: string): Row {
  configurationAdmission(configuration);
  const core: Row = { configuration: clone(configuration), revision: '0', last_clock: null, budgets: [], reservations: [], effects: [] };
  if ((configuration.exclusive_slots ?? []).length) core.exclusive_keys = [];
  if ((configuration.exclusive_slots ?? []).some(mediatedSlot)) core.key_history = [];
  if (configuration.recovery) core.recovery = { policies: [], dispositions: [], contingent: [], allowances: [] };
  return { schema: VERSION + '/reservation-state', specification_pin: selectedPin, core, receipts: [] };
}

function exclusiveSlot(core: Row, slotId: string): Row {
  const slot = (core.configuration.exclusive_slots ?? []).find((row: Row) => row.slot === slotId);
  requireFact(slot, 'REFERENCE_INVALID');
  return slot;
}
function exclusiveKeyDigest(core: Row, row: Row): string {
  return digest('exclusive-key', { registry: digest('reservation-registry', core.configuration), slot: row.slot, namespace: row.namespace, key: row.key });
}
function resolvedExclusiveKeys(core: Row, authority: Row, authorityResult: Row, supplied: Row[] | undefined): Row[] {
  const required = authorityResult.required_exclusive_keys ?? [];
  if (supplied !== undefined) requireFact(same(supplied, required), 'DEPENDENCY_MISMATCH');
  const keys = (supplied ?? required).map((row: Row) => {
    const slot = exclusiveSlot(core, row.slot);
    requireFact(slot.namespace === row.namespace && slot.authorized_classes.includes(authority.proposal.work_class) && slot.retention === row.retention, 'DEPENDENCY_MISMATCH');
    admitRequestedKey(slot, authority, row);
    return { id: row.id, slot: row.slot, namespace: row.namespace, key: clone(row.key), retention: row.retention };
  });
  const digests = keys.map((row: Row) => exclusiveKeyDigest(core, row));
  requireFact(new Set(digests).size === digests.length, 'INPUT_INVALID');
  return keys;
}

function hostAdmission(core: Row, event: Row, host: Row): void {
  const configuration = core.configuration, registryDigest = digest('reservation-registry', configuration);
  requireFact(host.registry_digest === registryDigest, 'DEPENDENCY_MISMATCH');
  requireFact(ordered(host.administration_bases.map((basis: Row) => basis.id)), 'INPUT_INVALID');
  const histories = event.kind === 'REGISTER' ? [event.payload.history] : event.payload.histories ?? [];
  const records = histories.map((history: Row) => ({ kind: 'HISTORY', record_digest: digest('budget-history', history), provider: history.provider, source: history.source }));
  if (event.payload.native) records.push({ kind: 'NATIVE_OUTCOME', record_digest: digest('reservation-native-outcome', event.payload.native), provider: event.payload.native.provider, source: event.payload.native.source });
  if (event.administration) records.push({ kind: 'ADMIN_RETURN', record_digest: digest('reservation-administration-return', event.administration.returned), provider: event.administration.returned.provider, source: event.administration.returned.source });
  if (event.kind === 'SEED_EXCLUSIVE') {
    const coverage = event.payload.coverage;
    records.push({ kind: 'EXCLUSIVE_COVERAGE', record_digest: digest('exclusive-history-coverage', coverage), provider: coverage.provider, source: coverage.source });
    for (const claim of event.payload.claims) {
      records.push({ kind: 'EXCLUSIVE_NATIVE_HISTORY', record_digest: digest('exclusive-native-history', claim.native_record), provider: claim.native_record.provider, source: claim.native_record.source });
      records.push({ kind: 'EXCLUSIVE_REQUEST_PROVENANCE', record_digest: digest('exclusive-request-provenance', claim.request_provenance), provider: claim.request_provenance.provider, source: claim.request_provenance.source });
    }
  }
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


function historyBinding(budget: Row, history: Row): void {
  // No definition-reference, scalar, date, freshness or policy evaluation here.
  requireFact(history.budget_digest === budget.definition_digest, 'DEPENDENCY_MISMATCH');
  const source = budget.definition.aggregate.aggregate.committed_source;
  if (source && typeof source === 'object') requireFact(history.provider === source.provider && history.source === source.source, 'DEPENDENCY_MISMATCH');
}
function historySelection(budgets: Row[], histories: Row[]): void {
  // Identity-set admission is independent of the supplied row order/multiplicity.
  requireFact(same(uniqueSorted(histories.map((row: Row) => row.budget_digest)), uniqueSorted(budgets.map(row => row.definition_digest))), 'DEPENDENCY_MISMATCH');
}
function currentHistoryBindings(core: Row, event: Row): void {
  const payload = event.payload;
  if (event.kind === 'REGISTER') {
    historyBinding({ definition: payload.definition, definition_digest: digest('budget-definition', payload.definition) }, payload.history);
    return;
  }
  let histories: Row[] = [], budgets: Row[] = [], completeSelection = true;
  if (event.kind === 'RESERVE' || event.kind === 'RENEW') {
    const anchors = payload.authority.envelope.limits.shared_budgets;
    histories = payload.histories;
    for (const anchor of anchors) {
      const budget = registered(core, anchor);
      if (budget) budgets.push(budget); else completeSelection = false;
    }
  } else if (event.kind === 'SETTLE') {
    histories = payload.histories;
    const reservation = core.reservations.find((row: Row) => row.id === payload.native.reservation);
    if (reservation) {
      for (const anchor of affectedAnchors(reservation)) {
        const budget = registered(core, anchor);
        if (budget) budgets.push(budget); else completeSelection = false;
      }
    } else {
      for (const history of histories) {
        const budget = core.budgets.find((row: Row) => row.definition_digest === history.budget_digest);
        if (budget) budgets.push(budget); else completeSelection = false;
      }
    }
    for (const budget of budgets) {
      const provider = budget.definition.reservation_policy.settlement;
      requireFact(payload.native.provider === provider.provider && payload.native.source === provider.source, 'DEPENDENCY_MISMATCH');
    }
    if (reservation && affectedAnchors(reservation).length === 0 && reservation.exclusive_keys?.length) {
      const step = reservation.authority.work_class.steps.find((row: Row) => row.id === reservation.authority.proposal.step), completion = step?.completion;
      requireFact(completion && payload.native.provider === completion.effect_provider && payload.native.source === completion.effect_source, 'DEPENDENCY_MISMATCH');
    }
  } else if (event.kind === 'DISPOSE') {
    if (payload.target.kind !== 'RESERVATION' || payload.target.registry_digest !== digest('reservation-registry', core.configuration)) return;
    const reservation = core.reservations.find((row: Row) => row.id === payload.target.reservation);
    if (!reservation) return;
    histories = payload.histories;
    for (const anchor of affectedAnchors(reservation)) {
      const budget = registered(core, anchor);
      if (budget) budgets.push(budget); else completeSelection = false;
    }
  } else return;
  if (completeSelection) historySelection(budgets, histories);
  if (event.kind === 'SETTLE' && !core.reservations.some((row: Row) => row.id === payload.native.reservation)) requireFact(histories.length > 0 && completeSelection, 'DEPENDENCY_MISMATCH');
  for (const budget of budgets) {
    const matches = histories.filter((row: Row) => row.budget_digest === budget.definition_digest);
    requireFact(matches.length > 0, 'DEPENDENCY_MISMATCH');
    for (const history of matches) historyBinding(budget, history);
  }
}

function historyAdmission(budget: Row, history: Row, clock: Row, prior?: Row): void {
  historyBinding(budget, history);
  if (!fullHistory(history)) return;
  const errors = new Set<string>();
  const check = (admit: () => void): void => {
    try { admit(); }
    catch (error) {
      if (!(error instanceof Refusal || error instanceof AdmissionError) || !['TYPE_INVALID', 'INPUT_INVALID'].includes(error.code)) throw error;
      errors.add(error.code);
    }
  };
  check(() => requireFact(BigInt(history.revision) === BigInt(history.journal.length), 'INPUT_INVALID'));
  if (prior && fullHistory(prior)) check(() => requireFact(history.journal.length >= prior.journal.length && same(history.journal.slice(0, prior.journal.length), prior.journal), 'INPUT_INVALID'));
  for (const [index, row] of history.journal.entries()) {
    check(() => requireFact(row.sequence === String(index + 1), 'INPUT_INVALID'));
    check(() => validateHistoryRecord(budget.definition.aggregate, row.event));
    if (row.event.state === 'ACTIVE') check(() => requireFact(second(row.event.occurred_at) <= second(history.as_of), 'INPUT_INVALID'));
  }
  // This obligation is independent of journal contents. Report history type
  // faults before timestamp and other integrity faults under phase 5's order.
  check(() => { const asOf = second(history.as_of); requireFact(clock.status !== 'AVAILABLE' || asOf <= second(clock.instant), 'INPUT_INVALID'); });
  for (const code of ['TYPE_INVALID', 'INPUT_INVALID']) if (errors.has(code)) throw new Refusal(code);
}

function historiesAdmission(budgets: Row[], histories: Row[], clock: Row, incompatibleSources = false): void {
  const order = ['DEPENDENCY_MISMATCH', 'EVIDENCE_UNAVAILABLE', 'UNSUPPORTED_RELATION', 'REFERENCE_INVALID', 'BINDING_MISMATCH', 'TYPE_INVALID', 'INPUT_INVALID', 'LIMIT_EXCEEDED', 'DEFINITION_CONFLICT', 'OCCURRENCE_CONFLICT', 'RESERVATION_NOT_FOUND', 'ADMINISTRATION_NOT_ESTABLISHED'];
  historySelection(budgets, histories);
  const errors = new Set<string>(incompatibleSources ? ['UNSUPPORTED_RELATION'] : []);
  if (!ordered(histories.map((row: Row) => row.budget_digest))) errors.add('INPUT_INVALID');
  // Validate every supplied body before duplicate/order refusal. Selection never
  // hides a malformed row behind an earlier or later row for the same budget.
  for (const history of histories) {
    const budget = budgets.find((row: Row) => row.definition_digest === history.budget_digest)!;
    try { historyAdmission(budget, history, clock, budget.history); }
    catch (error) {
      if (!(error instanceof Refusal || error instanceof AdmissionError) || !order.includes(error.code)) throw error;
      errors.add(error.code);
    }
  }
  // Validate the complete affected set before policy or history retention.
  for (const code of order) if (errors.has(code)) throw new Refusal(code);
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
// R-p: assessed numerical accounting is derived from retained evidence, never a prior reason list.
function retainedActuals(core: Row, reservation: Row, evidence?: Row): Row[] {
  const facts = new Map<string, Row>();
  for (const row of core.effects.filter((row: Row) => row.reservation === reservation.id && row.reason !== 'UNKNOWN_RESERVATION')) facts.set(recoveryFact(row.native), row.native);
  const packets = (core.recovery?.dispositions ?? []).filter((row: Row) => row.target.reservation === reservation.id)
    .sort((a: Row, b: Row) => BigInt(a.source_event.expected_revision) < BigInt(b.source_event.expected_revision) ? -1 : 1).map((row: Row) => row.evidence);
  if (evidence) packets.push(evidence);
  for (const packet of packets) {
    for (const identity of packet.superseded_evidence_digests) facts.delete(identity);
    for (const native of selectedActuals(packet)) facts.set(recoveryFact(native), native);
  }
  return [...facts.values()].filter(row => row.outcome === 'EFFECT');
}
function foreignActualReasons(core: Row, scope: Row[]): string[] {
  return core.effects.some((effect: Row) => effect.native.outcome === 'EFFECT' && effect.reason === 'UNKNOWN_RESERVATION'
    && effect.blocked_partitions.some((part: Row) => scope.some(row => row.anchor === part.anchor && (part.key === null || same(row.key, part.key)))))
    ? ['RECOVERY_EVIDENCE_INCOMPLETE'] : [];
}
function actualAccounting(core: Row, reservation: Row, budgets: Row[], histories: Row[], clock: Row, evidence?: Row, scope?: Row[]): { reasons: string[]; amounts: Map<string, string> } {
  const reasons = new Set<string>(), amounts = new Map<string, string>();
  const anchors = affectedAnchors(reservation);
  if (!anchors.length) return { reasons: [], amounts };
  const selected = budgets.filter(row => anchors.includes(row.definition.anchor));
  if (!selected.length) return { reasons: [], amounts };
  const actuals = retainedActuals(core, reservation, evidence), counts = new Map<string, number>();
  for (const row of actuals) counts.set(row.effect_id, (counts.get(row.effect_id) ?? 0) + 1);
  for (const native of actuals) {
    if (!native.observed_request) { reasons.add('RECOVERY_EVIDENCE_INCOMPLETE'); continue; }
    for (const budget of selected) {
      let contributions: Row[];
      try {
        const observed = native.observed_request, authority = reservation.authority;
        const step = authority.work_class.steps.find((row: Row) => row.id === authority.proposal.step);
        requireFact(step && observed.work_class === authority.proposal.work_class && observed.step === step.id
          && observed.operation === step.operation && observed.interface === step.interface, 'TYPE_INVALID');
        const fields = [...step.fields].sort((l: Row, r: Row) => byteCompare(l.name, r.name));
        requireFact(fields.length === observed.fields.length && fields.every((row: Row, index: number) =>
          row.name === observed.fields[index].name && row.type_ref === observed.fields[index].value.type_ref), 'TYPE_INVALID');
        const types = new Map(authority.work_class.types.map((type: Row) => [type.id, type]));
        for (const row of observed.fields) typed(row.value, types as any);
        contributions = projectedContributions(budget, projectNative(budget, selectedAuthorization(budget, authority), observed, reservation.occurrence_key));
      }
      catch (error) { if (!(error instanceof Refusal || error instanceof AdmissionError) || error.code === 'LIMIT_EXCEEDED') throw error; reasons.add('RECOVERY_EVIDENCE_INCOMPLETE'); continue; }
      if (contributions.length && scope && !scope.some(row => row.anchor === budget.definition.anchor &&
        [...contributions, ...reservation.contributions.filter((original: Row) => original.anchor === row.anchor)].some(projected => same(projected.key, row.key)))) continue;
      if (counts.get(native.effect_id)! > 1) { reasons.add('RECOVERY_CONFLICT_UNRESOLVED'); reasons.add('RECOVERY_EVIDENCE_INCOMPLETE'); continue; }
      if (!contributions.length) { reasons.add('RECOVERY_EVIDENCE_INCOMPLETE'); continue; }
      const history = histories.find(row => row.budget_digest === budget.definition_digest);
      if (!history || historyReason(budget, history, clock)) { reasons.add('RECOVERY_EVIDENCE_INCOMPLETE'); continue; }
      for (const contribution of contributions) {
        const prescribed = committedRecord(budget, contribution, native.effect_id, native.occurred_at);
        const found = latestHistory(history).get(prescribed.id);
        if (!found || !same(found, prescribed)) { reasons.add('RECOVERY_EVIDENCE_INCOMPLETE'); reasons.add('HISTORY_UNCORROBORATED'); }
        else if (budget.definition.aggregate.aggregate.reducer === 'SUM') {
          const anchor = budget.definition.anchor;
          amounts.set(anchor, sum([amounts.get(anchor) ?? '0', contribution.value.value]));
        }
      }
    }
  }
  return { reasons: [...reasons].sort(byteCompare), amounts };
}
export function selectedRegistryNatives(evidence: Row): Row[] {
  const superseded = new Set(evidence.superseded_evidence_digests);
  return evidence.native_outcomes.filter((row: Row) => !superseded.has(recoveryFact(row)));
}
function selectedActuals(evidence: Row): Row[] {
  return selectedRegistryNatives(evidence).filter(row => row.outcome === 'EFFECT');
}
function attributedEffectIds(evidence: Row): Set<string> {
  return new Set(selectedActuals(evidence).map(row => row.effect_id));
}
function remainingSlots(evidence: Row): bigint {
  const actual = attributedEffectIds(evidence);
  return evidence.attempts.reduce((total: bigint, row: Row) => total +
    (row.no_effect ? 0n : BigInt(row.maximum_executions) - BigInt(row.effect_ids.filter((id: string) => actual.has(id)).length)), 0n);
}
function retainedRegistryFacts(core: Row, reservation: Row): Row[] {
  return [...core.effects.filter((row: Row) => row.reservation === reservation.id).map((row: Row) => row.native),
    ...(core.recovery?.dispositions ?? []).filter((row: Row) => row.target.kind === 'RESERVATION' && row.target.reservation === reservation.id)
      .flatMap((row: Row) => row.evidence.native_outcomes)];
}
function originalActualSubstitution(core: Row, reservation: Row, at: string): boolean {
  const rows = (core.recovery?.dispositions ?? []).filter((row: Row) => row.target.reservation === reservation.id);
  const superseded = new Set(rows.map((row: Row) => row.supersedes));
  const head = rows.find((row: Row) => !superseded.has(row.id));
  if (!head?.evidence.complete_attempt_inventory || remainingSlots(head.evidence) > 0n || !recoveryCoverage(head, retainedRegistryFacts(core, reservation))) return false;
  const actuals = retainedActuals(core, reservation), owned = new Set(head.evidence.attempts.flatMap((row: Row) => row.effect_ids));
  if (!actuals.length || new Set(actuals.map(row => row.effect_id)).size !== owned.size || actuals.some(row => !owned.has(row.effect_id))) return false;
  return !actualAccounting(core, reservation, core.budgets, core.budgets.map((row: Row) => row.history), { status: 'AVAILABLE', instant: at }).reasons.length;
}
function pending(core: Row, anchor: string, excluded: string | null, at = core.last_clock): Row[] {
  const original = core.reservations.filter((reservation: Row) => {
    if (reservation.id === excluded || !open(reservation)) return false;
    if (at && originalActualSubstitution(core, reservation, at)) return false;
    const disposition = at ? effectiveReservationDisposition(core, reservation, at) : null;
    if (disposition?.result === 'ESTABLISH_NO_EFFECT') return false;
    return disposition?.result !== 'ESTABLISH_EFFECT' || remainingSlots(disposition.evidence) > 0n;
  }).flatMap((reservation: Row) => reservation.contributions.filter((row: Row) => row.anchor === anchor).map((row: Row) => ({ reservation: reservation.id, mapping: row.mapping, occurrence: row.occurrence, key: row.key, contribution: row.value })));
  const contingent = (core.recovery?.contingent ?? []).filter((row: Row) => row.anchor === anchor && row.reservation !== excluded).map((row: Row) => ({ reservation: row.id, mapping: row.mapping, occurrence: row.id, key: row.key, contribution: row.value }));
  return [...original, ...contingent].sort((a: Row, b: Row) => byteCompare(canonical([a.reservation, a.mapping, a.occurrence, a.key]), canonical([b.reservation, b.mapping, b.occurrence, b.key])));
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
export function effectiveReservationDisposition(core: Row, reservation: Row, at: string): Row | null {
  const rows = (core.recovery?.dispositions ?? []).filter((row: Row) => row.target.kind === 'RESERVATION' && row.target.reservation === reservation.id);
  const current = rows.filter((row: Row) => !rows.some((next: Row) => next.supersedes === row.id)).at(-1);
  if (!current || !recoveryCoverage(current, retainedRegistryFacts(core, reservation)) || !recoveryPolicyCurrent(core, current, at)) return null;
  if (current.result === 'ESTABLISH_EFFECT' && actualAccounting(core, reservation, core.budgets,
      core.budgets.map((row: Row) => row.history), { status: 'AVAILABLE', instant: at }).reasons.length) return null;
  return current;
}
function reservationDispositionClears(core: Row, reservation: Row, at: string): boolean {
  const row = effectiveReservationDisposition(core, reservation, at);
  return !!row && (row.result !== 'ESTABLISH_EFFECT' || remainingSlots(row.evidence) === 0n
    && selectedActuals(row.evidence).every(native => !native.completion_mismatch && same(native.observed_request, row.evidence.request)));
}

function compatibleNativeSources(budgets: Row[]): boolean {
  if (budgets.length < 2) return true;
  const first = budgets[0].definition.reservation_policy;
  return budgets.slice(1).every((budget: Row) => {
    const policy = budget.definition.reservation_policy;
    return same(policy.settlement, first.settlement) && same(policy.no_effect, first.no_effect);
  });
}

// RESERVATION-RECORDS: a newly admitted history (with a non-duplicate event)
// that revises or retracts the prescribed committed record of a SETTLED
// reservation marks it DISPUTED. Its MATCHED effect record, matched_effect and
// native records stay unchanged; as an open reservation it again supplies its
// pending charge, and its reserved partitions block new contributions. The
// usable supplied history is the one that counts; stale or unavailable history
// leaves the retained journal in force.
function usableHistory(budget: Row, histories: Row[], clock: Row): Row {
  const history = histories.find((row: Row) => row.budget_digest === budget.definition_digest);
  return history && !historyReason(budget, history, clock) ? history : budget.history;
}
function markRevisedSettlements(core: Row, budgets: Row[], histories: Row[], clock: Row): void {
  const journal = (anchor: string): Row => {
    const budget = registered(core, anchor)!;
    return budgets.some((row: Row) => row.definition.anchor === anchor) ? usableHistory(budget, histories, clock) : budget.history;
  };
  for (const reservation of core.reservations) if (reservation.status === 'SETTLED') {
    const effect = core.effects.find((effect: Row) => effect.reservation === reservation.id && effect.native.effect_id === reservation.matched_effect && effect.disposition === 'MATCHED');
    requireFact(effect, 'STATE_INVALID');
    for (const contribution of reservation.contributions) {
      const budget = registered(core, contribution.anchor)!;
      const expected = committedRecord(budget, contribution, effect.native.effect_id, effect.native.occurred_at);
      const actual = latestHistory(journal(contribution.anchor)).get(expected.id);
      if (!actual || !same(actual, expected)) { reservation.status = 'DISPUTED'; break; }
    }
  }
}
function reconcile(core: Row, budgets: Row[], histories: Row[], clock: Row): void {
  for (const budget of budgets) budget.history = clone(usableHistory(budget, histories, clock));
  markRevisedSettlements(core, budgets, histories, clock);
}
type Transition = { core: Row; decision: string; reservation: string | null; budgets: Row[]; authority_result: Row | null; reasons: string[]; recovery_disposition_digest?: string };
function transition(coreValue: Row, event: Row, host: Row, selectedPin: string): Transition {
  // Delay pure tuple inventory integrity until higher-priority phase-5 facts
  // have been admitted. The body mutates a private clone, never supplied state.
  const inventoryInvalid = !setOrder(host.authenticated_records)
    || ['DISPOSE', 'RECOVERY_POLICY'].includes(event.kind) && host.recovery && !setOrder(host.recovery.authenticated_records);
  let result: Transition;
  try { result = transitionBody(coreValue, event, host, selectedPin); }
  catch (error) {
    if (inventoryInvalid && (error instanceof Refusal || error instanceof AdmissionError)
      && ['LIMIT_EXCEEDED', 'DEFINITION_CONFLICT', 'OCCURRENCE_CONFLICT', 'RESERVATION_NOT_FOUND', 'ADMINISTRATION_NOT_ESTABLISHED'].includes(error.code)) throw new Refusal('INPUT_INVALID');
    throw error;
  }
  requireFact(!inventoryInvalid, 'INPUT_INVALID');
  return result;
}
function transitionBody(coreValue: Row, event: Row, host: Row, selectedPin: string): Transition {
  const core = clone(coreValue), result: Transition = { core, decision: 'WITHHELD', reservation: null, budgets: [], authority_result: null, reasons: [] };
  if (event.kind === 'RESERVE' || event.kind === 'RENEW') requireFact(same(event.payload.authority.clock, event.clock), 'DEPENDENCY_MISMATCH');
  if (event.kind === 'SEED_EXCLUSIVE') requireFact(event.clock.status === 'AVAILABLE', 'CLOCK_INVALID');
  const deferredHistories = new Set<unknown>();
  if (event.kind === 'REGISTER') deferredHistories.add(event.payload.history);
  else if (['SETTLE', 'DISPOSE', 'RESERVE', 'RENEW'].includes(event.kind)) {
    // Current-history dates follow affected-set and authentication admission,
    // including an invalid supplied history when the affected set is empty.
    for (const history of event.payload.histories) deferredHistories.add(history);
  }
  completeDates(event, deferredHistories); completeDates(host);
  currentHistoryBindings(core, event);
  if (event.kind !== 'DISPOSE') hostAdmission(core, event, host);
  else requireFact(host.registry_digest === digest('reservation-registry', core.configuration) && host.administration_bases.length === 0, 'DEPENDENCY_MISMATCH');
  if (event.kind === 'RECOVERY_POLICY') {
    recoveryPolicyTransition(core, event, host.recovery, true); result.decision = 'POLICY_RECORDED';
  } else if (event.kind === 'DISPOSE') {
    return dispose(core, event, host, result, selectedPin);
  } else if (event.kind === 'REGISTER') {
    const { definition, authorizations, history } = event.payload;
    definitionAdmission(core.configuration, definition, authorizations);
    const existing = registered(core, definition.anchor), identity = digest('budget-definition', definition);
    requireFact(!existing || existing.definition_digest === identity, 'DEFINITION_CONFLICT');
    requireFact(!existing, 'DEFINITION_CONFLICT');
    const budget = { definition, definition_digest: identity, authorizations, history };
    historyAdmission(budget, history, event.clock);
    requireFact(fullHistory(history) && !historyReason(budget, history, event.clock), 'EVIDENCE_UNAVAILABLE');
    core.budgets.push(clone(budget)); core.budgets.sort((a: Row, b: Row) => byteCompare(a.definition.anchor, b.definition.anchor)); result.decision = 'REGISTERED';
  } else if (event.kind === 'SEED_EXCLUSIVE') {
    requireFact(event.administration, 'EVIDENCE_UNAVAILABLE');
    const seeded = seedHistory(core, event);
    result.decision = seeded.usable ? 'SEEDED_EXCLUSIVE' : 'WITHHELD';
    if (!seeded.usable) result.reasons = ['EXCLUSIVE_HISTORY_UNAVAILABLE'];
  } else if (event.kind === 'RESERVE' || event.kind === 'RENEW') {
    const { authority, histories } = event.payload;
    requireFact((authority.evaluation_point ?? 'PROPOSE') === 'PROPOSE', 'INPUT_INVALID');
    const authorityResult = evaluateAuthority(authority, selectedPin); result.authority_result = authorityResult;
    const anchors = authority.envelope.limits.shared_budgets;
    const clockUnavailable = authorityResult.code === 'AUTHORITY_NOT_ESTABLISHED' && same(authorityResult.reasons, ['CLOCK_UNAVAILABLE']) && event.clock.status === 'UNAVAILABLE';
    let requirements = authorityResult;
    if (clockUnavailable) {
      // Static authority admission succeeded; these requirements confer no permission.
      const step = authority.work_class.steps.find((row: Row) => row.id === authority.proposal.step);
      const fields = new Map<string, Row>(authority.proposal.fields.map((row: Row) => [row.name, row.value]));
      requirements = { required_exclusive_keys: (step.exclusive_keys ?? []).map((key: Row) => ({ id: key.id, slot: key.slot, namespace: key.namespace, key: key.projection.map((row: Row) => row.value ?? fields.get(row.field)), retention: key.retention })) };
    }
    if (authorityResult.status === 'READY_FOR_RESERVATION' || clockUnavailable) requireFact(authority.envelope.principal === core.configuration.principal, 'DEPENDENCY_MISMATCH');
    const exclusiveKeys = authorityResult.status === 'READY_FOR_RESERVATION' || clockUnavailable ? resolvedExclusiveKeys(core, authority, requirements, event.payload.exclusive_keys) : [];
    if (authorityResult.status !== 'READY_FOR_RESERVATION') result.reasons.push('AUTHORITY_WITHHELD');
    // RENEW of a terminal (SETTLED or RELEASED) reservation is a phase-5
    // INPUT_INVALID admission refusal, never a WITHHELD decision. It follows
    // current-history dependency, authentication and type admission and precedes
    // the proposal and envelope check (RESERVATION-RECORDS, refused RENEW).
    const terminalRenewTarget = (): void => {
      if (event.kind !== 'RENEW') return;
      const target = core.reservations.find((reservation: Row) => reservation.id === event.payload.reservation);
      requireFact(!target || !['SETTLED', 'RELEASED'].includes(target.status), 'INPUT_INVALID');
    };
    const key = occurrenceKey(authority.proposal);
    // Phase-5 occurrence and target admission precedes policy on every path.
    // RENEW names the retained reservation explicitly. A changed proposal cannot
    // turn that present reference into a missing-reservation failure.
    const admittedOccurrence = (): Row | undefined => {
      const found = core.reservations.find((reservation: Row) => event.kind === 'RENEW'
        ? reservation.id === event.payload.reservation : reservation.occurrence_key === key);
      if (event.kind === 'RESERVE') requireFact(!found, 'OCCURRENCE_CONFLICT');
      else {
        requireFact(found && found.id === event.payload.reservation, 'RESERVATION_NOT_FOUND');
        requireFact(found.proposal_digest === digest('authority-proposal', authority.proposal) && found.envelope_digest === digest('authority-envelope', authority.envelope), 'OCCURRENCE_CONFLICT');
        result.reservation = found.id;
      }
      return found;
    };
    if (authorityResult.status !== 'READY_FOR_RESERVATION' && !clockUnavailable && anchors.length === 0) { terminalRenewTarget(); admittedOccurrence(); result.reasons = ['AUTHORITY_WITHHELD']; return result; }
    requireFact(anchors.length > 0 || exclusiveKeys.length > 0, 'UNSUPPORTED_RELATION');
    const budgets = anchors.map((anchor: string) => { const budget = registered(core, anchor); requireFact(budget, 'REFERENCE_INVALID'); return budget; });
    historySelection(budgets, histories);
    historiesAdmission(budgets, histories, event.clock, !compatibleNativeSources(budgets));
    terminalRenewTarget();
    const existing = admittedOccurrence();
    const operations = new Map<string, Row>(), contributions: Row[] = [];
    for (const budget of budgets) {
      const authorization = selectedAuthorization(budget, authority), operation = projectNative(budget, authorization, authority.proposal, key);
      const projected = projectedContributions(budget, operation); requireFact(projected.length > 0, 'UNSUPPORTED_RELATION');
      operations.set(budget.definition.anchor, operation); contributions.push(...projected);
    }
    contributions.sort((a, b) => byteCompare(canonical([a.anchor, a.mapping, a.occurrence, a.key]), canonical([b.anchor, b.mapping, b.occurrence, b.key])));
    if (existing) requireFact(same(existing.contributions, contributions), 'OCCURRENCE_CONFLICT');
    if (exclusiveKeys.length) {
      const claimed = new Set(exclusiveKeys.map((row: Row) => exclusiveKeyDigest(core, row)));
      for (const occupied of core.exclusive_keys ?? []) {
        if (!claimed.has(occupied.key_digest)) continue;
        if (!existing || !occurrenceOwns(occupied, authority.proposal)) result.reasons.push('EXCLUSIVE_KEY_OCCUPIED');
      }
      if (existing) requireFact(same(existing.exclusive_keys ?? [], exclusiveKeys.map((row: Row) => ({ key_digest: exclusiveKeyDigest(core, row), slot: row.slot, namespace: row.namespace, key: row.key }))), 'OCCURRENCE_CONFLICT');
    }
    if (event.clock.status === 'UNAVAILABLE') { result.reasons = ['CLOCK_UNAVAILABLE']; return result; }
    if (exclusiveKeys.some((row: Row) => mediatedSlot(exclusiveSlot(core, row.slot)) && !(core.key_history ?? []).some((history: Row) => history.snapshot.slot === row.slot && history.snapshot.coverage.complete && history.snapshot.coverage.exclusive_writers))) {
      // R-f: this reason stands alone with empty budgets; a current complete
      // history is still committed and marked ("no partial write" refers to keys).
      reconcile(core, budgets, histories, event.clock);
      result.reasons = ['EXCLUSIVE_HISTORY_UNAVAILABLE']; return result;
    }
    for (const budget of budgets) { const reason = historyReason(budget, histories.find((history: Row) => history.budget_digest === budget.definition_digest), event.clock); if (reason) result.reasons.push(reason); }
    reconcile(core, budgets, histories, event.clock);
    // R-f: an occupied key stands alone with empty budgets, after the commit above.
    if (result.reasons.includes('EXCLUSIVE_KEY_OCCUPIED')) { result.reasons = ['EXCLUSIVE_KEY_OCCUPIED']; return result; }
    for (const budget of budgets) {
      const anchor = budget.definition.anchor;
      const keys = contributions.filter(row => row.anchor === anchor).map(row => row.key);
      const resolved = (reservationId: string): boolean => { const reservation = core.reservations.find((row: Row) => row.id === reservationId); return !!reservation && reservationDispositionClears(core, reservation, event.clock.instant); };
      const effectsBlock = core.effects.some((effect: Row) => effect.disposition === 'DISPUTED' && (effect.reason === 'UNKNOWN_RESERVATION' || !resolved(effect.reservation)) && effect.blocked_partitions.some((blocked: Row) => blocked.anchor === anchor && (blocked.key === null || keys.some(key => same(key, blocked.key)))));
      const blocking = core.reservations.filter((reservation: Row) => reservation.status === 'DISPUTED' && !resolved(reservation.id) && reservation.contributions.some((row: Row) => row.anchor === anchor && keys.some(key => same(key, row.key))));
      if (effectsBlock || blocking.length) result.reasons.push('EXPOSURE_DISPUTED');
    }
    if (host.recovery?.pending_evidence.some((row: Row) => row.target.kind === 'RESERVATION' && row.target.registry_digest === digest('reservation-registry', core.configuration) && core.reservations.some((reservation: Row) => reservation.id === row.target.reservation && reservation.contributions.some((contribution: Row) => contributions.some(candidate => candidate.anchor === contribution.anchor && same(candidate.key, contribution.key)))))) result.reasons.push('RECOVERY_PENDING_EVIDENCE');
    if (existing && existing.status === 'DISPUTED') result.reasons.push('EXPOSURE_DISPUTED');
    // RESERVATION-RECORDS: a blocked new contribution (any DISPUTED effect
    // partition, DISPUTED reservation or revised settlement) is still evaluated
    // against each affected partition; the WITHHELD receipt carries those
    // judgments with EXPOSURE_DISPUTED, and BOUND_VIOLATED when one is violated.
    // A RENEW whose own reservation is DISPUTED is withheld by that status
    // without aggregate evaluation.
    const evaluateBlocked = !(existing && existing.status === 'DISPUTED') && result.reasons.every(reason => reason === 'EXPOSURE_DISPUTED');
    const historyUsable = budgets.every((budget: Row) => !historyReason(budget, histories.find((row: Row) => row.budget_digest === budget.definition_digest), event.clock));
    if (historyUsable && authorityResult.status === 'READY_FOR_RESERVATION') {
      result.reasons.push(...foreignActualReasons(core, contributions));
      for (const retained of core.reservations) {
        if (retained.contributions.some((row: Row) => anchors.includes(row.anchor))) result.reasons.push(...actualAccounting(core, retained, budgets, histories, event.clock, undefined, contributions).reasons);
      }
    }
    if (result.reasons.some(reason => reason === 'RECOVERY_EVIDENCE_INCOMPLETE' || reason === 'HISTORY_UNCORROBORATED')) return result;
    if (result.reasons.length && !evaluateBlocked) return result;
    for (const budget of budgets) {
      const anchor = budget.definition.anchor, request = historyRequest(budget.definition.aggregate, [operations.get(anchor)!], pending(core, anchor, existing?.id ?? null, event.clock.instant), event.clock, budget.history, selectedPin);
      const evaluated = evaluateAggregate(request, selectedPin); result.budgets.push({ anchor, result: evaluated });
      if (evaluated.status !== 'SATISFIED') result.reasons.push(evaluated.status === 'VIOLATED' ? 'BOUND_VIOLATED' : 'HISTORY_INCOMPLETE');
    }
    if (result.reasons.length) return result;
    const step = authority.work_class.steps.find((row: Row) => row.id === authority.proposal.step);
    const durations = [
      ...budgets.map((budget: Row) => BigInt(budget.definition.reservation_policy.permit_seconds)),
      ...exclusiveKeys.map((row: Row) => BigInt(exclusiveSlot(core, row.slot).permit_seconds)),
    ];
    requireFact(durations.length > 0, 'REFERENCE_INVALID');
    const duration = durations.reduce((a: bigint, b: bigint) => a < b ? a : b);
    let until: string;
    try { until = instantText(second(event.clock.instant) + duration * 1000000000n, false); }
    catch (error) { if (error instanceof AdmissionError) throw new Refusal('LIMIT_EXCEEDED'); throw error; }
    const fixedExpiry = authority.envelope.temporal_validity.valid_until;
    if (fixedExpiry !== null && second(fixedExpiry) < second(until)) until = fixedExpiry;
    if (existing) {
      existing.authority = clone(authority); existing.authority_result = clone(authorityResult); existing.permit_until = until; result.decision = 'RENEWED';
    } else {
      requireFact((core.exclusive_keys ?? []).length + exclusiveKeys.length <= 4096, 'LIMIT_EXCEEDED');
      core.reservations.push({ id: event.id, occurrence_key: key, proposal_digest: digest('authority-proposal', authority.proposal), envelope_digest: digest('authority-envelope', authority.envelope), authority: clone(authority), authority_result: clone(authorityResult), contributions, ...(exclusiveKeys.length ? { exclusive_keys: exclusiveKeys.map((row: Row) => ({ key_digest: exclusiveKeyDigest(core, row), slot: row.slot, namespace: row.namespace, key: clone(row.key) })) } : {}), created_at: event.clock.instant, permit_until: until, status: 'OPEN', matched_effect: null });
      if (exclusiveKeys.length) {
        const rows = exclusiveKeys.map((row: Row) => ({ key_digest: exclusiveKeyDigest(core, row), slot: row.slot, namespace: row.namespace, key: clone(row.key), ...(newSlot(exclusiveSlot(core, row.slot)) ? { owner: { kind: 'WORK_OCCURRENCE', work_class: authority.proposal.work_class, instance_id: authority.proposal.instance, occurrence_id: authority.proposal.occurrence } } : { owner_instance: authority.proposal.instance, owner_occurrence: authority.proposal.occurrence }), acquisition_event: event.id, status: 'HELD', settlement_evidence: null }));
        core.exclusive_keys.push(...rows);
        core.exclusive_keys.sort((a: Row, b: Row) => byteCompare(a.key_digest, b.key_digest));
      }
      byId(core.reservations); result.decision = 'RESERVED'; result.reservation = event.id;
    }
  } else {
    return nativeTransition(core, event, result);
  }
  return result;
}

export function recoveryControllerActors(reservation: Row): string[] {
  const authority = reservation.authority, executor = authority.proposal.executor.actor;
  if ((authority.decision_bases ?? []).length > 0) return [executor, ...authority.acts.map((row: Row) => row.actor), ...independentActors(authority)];
  const gate = authority.envelope.gate, kind = gate.kind === 'DECIDE' ? 'INSTANCE_DECISION' : gate.kind === 'VERIFY' ? 'VERIFY' : null;
  const actors = kind === null ? [] : selectedAuthorityAct(authority, kind)
    .filter((row: Row) => row.act.role === gate.role && reservation.authority_result.act_digests.includes(row.act_digest))
    .map((row: Row) => row.act.actor);
  return [executor, ...actors];
}

function dispose(core: Row, event: Row, host: Row, result: Transition, selectedPin: string): Transition {
  const payload = event.payload, configuration = core.configuration.recovery, recovery = core.recovery;
  requireFact(configuration && recovery && event.administration === null && event.clock.status === 'AVAILABLE' && host.recovery, 'DEPENDENCY_MISMATCH');
  const registry = digest('reservation-registry', core.configuration), target = payload.target;
  requireFact(target.kind === 'RESERVATION' && target.registry_digest === registry, 'DEPENDENCY_MISMATCH');
  const reservation = core.reservations.find((row: Row) => row.id === target.reservation);
  requireFact(reservation, 'RESERVATION_NOT_FOUND'); result.reservation = reservation.id;
  const evidence = payload.evidence, facts = core.effects.filter((row: Row) => row.reservation === reservation.id).map((row: Row) => row.native);
  const previous = recovery.dispositions.filter((row: Row) => same(row.target, target)).filter((row: Row, _index: number, rows: Row[]) => !rows.some(next => next.supersedes === row.id)).at(-1);
  const request = nativeRequest(reservation.authority.proposal), budgets = affectedAnchors(reservation).map(anchor => registered(core, anchor)!);
  requireFact(budgets.length > 0 || (reservation.exclusive_keys ?? []).length > 0, 'UNSUPPORTED_RELATION');
  requireFact(evidence.record_type === 'RECOVERY_ADJUDICATION', 'DEPENDENCY_MISMATCH');
  const noEffect = payload.requested_result === 'ESTABLISH_NO_EFFECT' || payload.requested_result === 'LEAVE_UNRESOLVED' && evidence.conclusion === 'NO_EFFECT_ESTABLISHED';
  const step = reservation.authority.work_class.steps.find((row: Row) => row.id === reservation.authority.proposal.step);
  const completion = step?.completion;
  requireFact(budgets.length > 0 || completion, 'UNSUPPORTED_RELATION');
  const provider = budgets.length > 0 ? (noEffect ? budgets[0].definition.reservation_policy.no_effect : budgets[0].definition.reservation_policy.settlement)
    : { provider: noEffect ? completion.no_effect_provider : completion.effect_provider, source: noEffect ? completion.no_effect_source : completion.effect_source };
  requireFact(evidence.provider === provider.provider && evidence.source === provider.source && compatibleNativeSources(budgets), 'DEPENDENCY_MISMATCH');
  historySelection(budgets, payload.histories);
  const packetHistory = recovery.dispositions.filter((row: Row) => same(row.target, target));
  const priorFacts = [...facts, ...packetHistory.flatMap((row: Row) => row.evidence.native_outcomes)], reasons = recoveryPacket(evidence, target, request, priorFacts, packetHistory.flatMap((row: Row) => row.evidence.attempts));
  const native = evidence.native_outcomes;
  for (const row of native) {
    requireShape('reservation.schema.json', 'native', row);
    requireFact(row.reservation === reservation.id && same(row.request, request) && row.provider === evidence.provider && row.source === evidence.source, 'DEPENDENCY_MISMATCH');
    requireFact(row.outcome === 'EFFECT' ? row.effect_id !== null && row.occurred_at !== null && !row.rules_out_past_and_future_effects : row.effect_id === null && row.occurred_at === null && (row.outcome === 'NO_EFFECT' || !row.rules_out_past_and_future_effects), 'INPUT_INVALID');
    requireFact(row.completion_mismatch ? ['NATIVE_REQUEST_MISMATCH', 'UNEXPECTED_EFFECT'].includes(row.mismatch_reason) : row.mismatch_reason === null, 'INPUT_INVALID');
    if (row.outcome !== 'EFFECT') requireFact(row.observed_request === null && row.actual_fields.length === 0 && row.collections.length === 0, 'INPUT_INVALID');
    else requireFact(row.observed_request !== null || row.completion_mismatch, 'INPUT_INVALID');
  }
  if (['ESTABLISH_EFFECT', 'ESTABLISH_NO_EFFECT'].includes(payload.requested_result)) requireFact(payload.controller, 'ADMINISTRATION_NOT_ESTABLISHED');
  recoveryHostAdmission(configuration, host.recovery, evidence, payload.controller, true);
  if (['ESTABLISH_EFFECT', 'ESTABLISH_NO_EFFECT'].includes(payload.requested_result)) {
    requireFact(payload.policy_digest === null, 'DEPENDENCY_MISMATCH');
    recoveryAuthority(configuration, host.recovery, payload.controller, event, core.configuration.principal, digest('recovery-target', target), payload.requested_result, event.clock.instant, recoveryControllerActors(reservation));
  } else requireFact(payload.controller === null, 'DEPENDENCY_MISMATCH');
  hostAdmission(core, event, host);
  historiesAdmission(budgets, payload.histories, event.clock);
  const candidate = recoveryDisposition(core.configuration.principal, registry, reservation, target, payload, event, event.clock.instant);
  const reused = recovery.dispositions.find((row: Row) => row.id === previous?.id && row.incident_digest === candidate.incident_digest && row.generation_digest === candidate.generation_digest && row.result === candidate.result && row.policy_digest === candidate.policy_digest);
  if (!reasons.length && candidate.acceptance_basis_digest && reused && recoveryPolicyCurrent(core, reused, event.clock.instant) && recovery.policies.some((row: Row) => row.policy_digest === reused.policy_digest && row.policy.scope.executors.includes(host.recovery.caller)) && recoveryCoverage(reused, priorFacts) && budgets.every((budget: Row) => !historyReason(budget, payload.histories.find((row: Row) => row.budget_digest === budget.definition_digest), event.clock)) && !host.recovery.pending_evidence.some((row: Row) => same(row.target, target) && row.record_digest !== digest('recovery-evidence', evidence))) {
    reconcile(core, budgets, payload.histories, event.clock);
    result.decision = 'DISPOSITION_REUSED'; result.recovery_disposition_digest = reused.id; return result;
  }
  // The revised-settlement marking applies when the history is admitted, before
  // this event's own policy evaluation; the journal is stored with it below.
  markRevisedSettlements(core, budgets, payload.histories, event.clock);
  requireFact(payload.supersedes === (previous?.id ?? null), 'REVISION_CONFLICT');
  requireFact(!previous || previous.generation_digest !== candidate.generation_digest || previous.result === 'LEAVE_UNRESOLVED' || candidate.result === previous.result || candidate.result === 'LEAVE_UNRESOLVED', 'INPUT_INVALID');
  if (host.recovery.pending_evidence.some((row: Row) => same(row.target, target) && row.record_digest !== digest('recovery-evidence', evidence))) reasons.push('RECOVERY_PENDING_EVIDENCE');
  const effects = selectedActuals(evidence);
  const ambiguous = new Set(effects.filter((row: Row) => effects.some((other: Row) => other.effect_id === row.effect_id && recoveryFact(other) !== recoveryFact(row))).map((row: Row) => row.effect_id));
  if (ambiguous.size) reasons.push('RECOVERY_CONFLICT_UNRESOLVED');
  const actual = [...new Map(effects.filter((row: Row) => !ambiguous.has(row.effect_id)).map((row: Row) => [row.effect_id, row])).values()] as Row[];
  const actualIds = [...new Set<string>(effects.map((row: Row) => row.effect_id))].sort(byteCompare), attemptIds = evidence.attempts.flatMap((row: Row) => row.effect_ids).sort(byteCompare);
  if (!same(actualIds, attemptIds)) reasons.push('RECOVERY_EVIDENCE_INCOMPLETE');
  const slotCount = remainingSlots(evidence), attributed = attributedEffectIds(evidence);
  const originalSlot = ['OPEN', 'UNKNOWN', 'DISPUTED'].includes(reservation.status) ? 1n : 0n;
  const accounting = actualAccounting(core, reservation, budgets, payload.histories, event.clock, evidence);
  reasons.push(...accounting.reasons);
  const existingCount = recovery.contingent.filter((row: Row) => row.reservation !== reservation.id).length;
  requireFact(BigInt(existingCount) + (slotCount > originalSlot ? slotCount - originalSlot : 0n) * BigInt(reservation.contributions.length) <= 4096n, 'LIMIT_EXCEEDED');
  const unresolvedSlots: { attempt: Row; index: string }[] = [];
  // R-m bounds projected rows, not slots: 4097 slots can mean 4096 rows.
  // Key-only targets need no numerical rows and must not enumerate huge maxima.
  if (reservation.contributions.length) for (const attempt of evidence.attempts) {
    if (!attempt.no_effect) for (let index = BigInt(attempt.effect_ids.filter((id: string) => attributed.has(id)).length); index < BigInt(attempt.maximum_executions); index++) {
      unresolvedSlots.push({ attempt, index: String(index + 1n) });
    }
  }
  const contradictions = [...priorFacts, ...native].filter(row => row.outcome === 'NO_EFFECT' && effects.length > 0 || row.outcome === 'EFFECT' && !native.some((selected: Row) => recoveryFact(selected) === recoveryFact(row)));
  if (contradictions.some(row => !evidence.superseded_evidence_digests.includes(recoveryFact(row)))) reasons.push('RECOVERY_CONFLICT_UNRESOLVED');
  // R-i: an unusable history is not adopted and adds no reason to an explicit LEAVE_UNRESOLVED.
  if (payload.requested_result !== 'LEAVE_UNRESOLVED') for (const budget of budgets) { const reason = historyReason(budget, payload.histories.find((row: Row) => row.budget_digest === budget.definition_digest), event.clock); if (reason) reasons.push(reason); }
  if (payload.requested_result === 'ESTABLISH_EFFECT') {
    if (evidence.conclusion !== 'EFFECT_ESTABLISHED' || !effects.length || actual.some(row => row.observed_request === null)) reasons.push('RECOVERY_EVIDENCE_INCOMPLETE');
    if (evidence.rules_out_past_and_future_effects) reasons.push('RECOVERY_CONFLICT_UNRESOLVED');
  } else if (payload.requested_result === 'ESTABLISH_NO_EFFECT') {
    if (budgets.some((budget: Row) => historyReason(budget, payload.histories.find((row: Row) => row.budget_digest === budget.definition_digest), event.clock))) reasons.push('RECOVERY_EVIDENCE_INCOMPLETE');
    if (evidence.conclusion !== 'NO_EFFECT_ESTABLISHED' || !evidence.rules_out_past_and_future_effects || slotCount > 0n || effects.length || evidence.attempts.some((row: Row) => !row.no_effect) || !native.length || native.some((row: Row) => row.outcome !== 'NO_EFFECT' || !same(row.request, request) || !row.rules_out_past_and_future_effects)) reasons.push('RECOVERY_EVIDENCE_INCOMPLETE');
  } else if (payload.requested_result === 'ACCEPT_UNRESOLVED') {
    const row = recovery.policies.find((row: Row) => row.policy_digest === payload.policy_digest), policy = row?.policy;
    if (!policy || !recoveryPolicyCurrent(core, candidate, event.clock.instant)) reasons.push('RECOVERY_POLICY_INVALID');
    const eligible = budgets.length > 0 && configuration.exception_profiles.includes('MONETARY_DUPLICATE_SEND') && evidence.complete_attempt_inventory && evidence.conclusion === 'UNRESOLVED' && !evidence.rules_out_past_and_future_effects && actual.length === 0 && unresolvedSlots.length > 1 && priorFacts.every(row => row.outcome === 'UNKNOWN' && same(row.request, request)) && native.every((row: Row) => row.outcome === 'UNKNOWN') && budgets.every(row => { const aggregate = row.definition.aggregate.aggregate, type = row.definition.aggregate.types.find((type: Row) => type.id === aggregate.result_type); return aggregate.reducer === 'SUM' && type?.unit === 'USD' && type.nonnegative && !historyReason(row, payload.histories.find((history: Row) => history.budget_digest === row.definition_digest), event.clock); });
    if (!eligible) reasons.push('RECOVERY_EXCEPTION_INELIGIBLE');
    if (policy && (!policy.scope.work_classes.includes(request.work_class) || !policy.scope.executors.includes(host.recovery.caller) || affectedAnchors(reservation).some(anchor => !policy.scope.budget_anchors.includes(anchor)) || evidence.attempts.some((attempt: Row) => !policy.scope.executors.includes(attempt.executor) || !policy.scope.connectors.includes(attempt.connector)))) reasons.push('RECOVERY_POLICY_INVALID');
  } else if (payload.requested_result !== 'LEAVE_UNRESOLVED') requireFact(false, 'INPUT_INVALID');
  const bounded = evidence.complete_attempt_inventory;
  const contingent: Row[] = [];
  if (bounded) for (const slot of unresolvedSlots.slice(Number(originalSlot))) for (const contribution of reservation.contributions) {
    const identity = { registry_digest: registry, reservation: reservation.id, attempt_id: slot.attempt.id, execution_index: slot.index, anchor: contribution.anchor, mapping: contribution.mapping, key: contribution.key };
    contingent.push({ id: digest('recovery-contingent', identity), disposition_digest: candidate.id, reservation: reservation.id, attempt_id: slot.attempt.id, execution_index: slot.index, anchor: contribution.anchor, mapping: contribution.mapping, occurrence: contribution.occurrence, key: clone(contribution.key), value: clone(contribution.value) });
  }
  let allowances: Row[] = [];
  const otherAccounting = payload.requested_result === 'ACCEPT_UNRESOLVED' && budgets.every((budget: Row) =>
    !historyReason(budget, payload.histories.find((row: Row) => row.budget_digest === budget.definition_digest), event.clock))
    ? [...foreignActualReasons(core, reservation.contributions), ...core.reservations.filter((row: Row) => row.id !== reservation.id).flatMap((row: Row) =>
      actualAccounting(core, row, budgets, payload.histories, event.clock, undefined, reservation.contributions).reasons)]
    : [];
  reasons.push(...otherAccounting);
  if (payload.requested_result === 'ACCEPT_UNRESOLVED') {
    const assessedCore = { ...core, budgets: core.budgets.map((row: Row) => ({
      ...row, history: payload.histories.find((history: Row) => history.budget_digest === row.definition_digest) ?? row.history,
    })) };
    if (bounded && !accounting.reasons.length && !otherAccounting.length && budgets.every((budget: Row) => !historyReason(budget, payload.histories.find((row: Row) => row.budget_digest === budget.definition_digest), event.clock))) for (const budget of budgets) {
      const anchor = budget.definition.anchor, authorization = selectedAuthorization(budget, reservation.authority), operation = projectNative(budget, authorization, request, reservation.occurrence_key);
      const incremental = contingent.filter(row => row.anchor === anchor).map(row => ({ reservation: row.id, mapping: row.mapping, occurrence: row.id, key: row.key, contribution: row.value }));
      const assessedPending = [...pending(assessedCore, anchor, reservation.id, event.clock.instant), ...incremental].sort((a: Row, b: Row) => byteCompare(canonical([a.reservation, a.mapping, a.occurrence, a.key]), canonical([b.reservation, b.mapping, b.occurrence, b.key])));
      const history = payload.histories.find((row: Row) => row.budget_digest === budget.definition_digest);
      if (!historyReason(budget, history, event.clock)) {
        requireFact(assessedPending.length <= 1024, 'LIMIT_EXCEEDED');
        const useOriginal = originalSlot > 0n && (slotCount > 0n || !retainedActuals(core, reservation, evidence).length);
        const assessedRequest = historyRequest(budget.definition.aggregate, [operation], assessedPending, event.clock, history, selectedPin);
        const evaluated = evaluateAggregate(assessedRequest, selectedPin, useOriginal);
        result.budgets.push({ anchor, result: evaluated });
        if (evaluated.status !== 'SATISFIED') reasons.push(evaluated.status === 'VIOLATED' ? 'BOUND_VIOLATED' : 'HISTORY_INCOMPLETE');
      }
    }
    const policy = recovery.policies.find((row: Row) => row.policy_digest === payload.policy_digest)?.policy;
    const amounts = new Map<string, string>();
    if (policy && !accounting.reasons.length) for (const anchor of affectedAnchors(reservation)) {
      const budget = registered(core, anchor)!, aggregate = budget.definition.aggregate.aggregate;
      const declaration = budget.definition.aggregate.types.find((row: Row) => row.id === aggregate.result_type);
      if (aggregate.reducer !== 'SUM' || declaration?.unit !== 'USD' || !declaration.nonnegative) continue;
      // Whole case exposure includes established slots, excluding affirmative no-effect closures.
      const chargedExecutions = slotCount;
      const perExecution = decimal(sum(reservation.contributions.filter((row: Row) => row.anchor === anchor).map((row: Row) => row.value.value)));
      const amount = sum([decimalText({ coefficient: perExecution.coefficient * chargedExecutions, scale: perExecution.scale }), accounting.amounts.get(anchor) ?? '0']);
      amounts.set(anchor, amount); if (compare(decimal(amount), decimal(policy.per_incident_limit)) > 0) reasons.push('RECOVERY_INCIDENT_LIMIT_EXCEEDED');
    }
    if (policy && amounts.size) {
      allowances = recoveryAllowanceRows(candidate, policy, reservation, amounts, event.clock.instant);
      if (recoveryAllowanceExceeded(core, policy, allowances, event.clock.instant)) reasons.push('RECOVERY_ALLOWANCE_EXCEEDED');
    }
  }
  const retained = reasons.length ? recoveryDisposition(core.configuration.principal, registry, reservation, target, payload, event, event.clock.instant, 'LEAVE_UNRESOLVED') : candidate;
  // R-h: any retained disposition with a complete finite inventory replaces the
  // rows and binds them to itself, including one that fell back to LEAVE_UNRESOLVED.
  if (bounded) {
    recovery.contingent = recovery.contingent.filter((row: Row) => row.reservation !== reservation.id);
    for (const row of contingent) row.disposition_digest = retained.id;
    recovery.contingent.push(...contingent); recoverySorted(recovery.contingent);
    requireFact(recovery.contingent.length <= 4096, 'LIMIT_EXCEEDED');
  }
  recovery.dispositions.push(retained); recoverySorted(recovery.dispositions);
  reconcile(core, budgets, payload.histories, event.clock);
  if (!reasons.length) {
    if (payload.requested_result === 'ACCEPT_UNRESOLVED') { recovery.allowances.push(...allowances); recoverySorted(recovery.allowances); }
  }
  result.recovery_disposition_digest = retained.id; result.decision = reasons.length ? 'WITHHELD' : 'DISPOSITION_RECORDED'; result.reasons = uniqueSorted(reasons);
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
  const keyOnly = Boolean(reservation?.exclusive_keys?.length) && budgets.length === 0;
  requireFact(budgets.length > 0 || keyOnly, 'REFERENCE_INVALID');
  for (const budget of budgets) {
    const provider = event.kind === 'RELEASE' ? budget.definition.reservation_policy.no_effect : budget.definition.reservation_policy.settlement;
    requireFact(native.provider === provider.provider && native.source === provider.source, 'DEPENDENCY_MISMATCH');
  }
  if (keyOnly) {
    const step = reservation!.authority.work_class.steps.find((row: Row) => row.id === reservation!.authority.proposal.step), completion = step?.completion;
    requireFact(completion && native.provider === (event.kind === 'RELEASE' ? completion.no_effect_provider : completion.effect_provider) && native.source === (event.kind === 'RELEASE' ? completion.no_effect_source : completion.effect_source), 'DEPENDENCY_MISMATCH');
  }
  if (event.kind === 'SETTLE') {
    historySelection(budgets, histories);
    historiesAdmission(budgets, histories, event.clock);
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
      let actual: Row[] | null = reservation && native.observed_request === null && !native.completion_mismatch ? [] : null;
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
  for (const claim of reservation.exclusive_keys ?? []) {
    const occupied = (core.exclusive_keys ?? []).find((row: Row) => row.key_digest === claim.key_digest);
    requireFact(occupied && occurrenceOwns(occupied, reservation.authority.proposal), 'STATE_INVALID');
    occupied.status = 'CONSUMED'; occupied.settlement_evidence = native.effect_id;
  }
  return retain('MATCHED', 'SETTLED', 'MATCHED_EFFECT');
}

function append(state: Row, event: Row, host: Row, selectedPin: string): Row {
  requireFact(event.expected_revision === state.core.revision, 'REVISION_CONFLICT');
  requireFact(event.clock.source === state.core.configuration.clock_source, 'DEPENDENCY_MISMATCH');
  let clockInstant: bigint | null = null;
  if (event.clock.status === 'AVAILABLE') {
    try { clockInstant = second(event.clock.instant); }
    catch (error) { if (error instanceof Refusal) throw new Refusal('CLOCK_INVALID'); throw error; }
  }
  requireFact(event.clock.status !== 'AVAILABLE' || state.core.last_clock === null || clockInstant! >= second(state.core.last_clock), 'CLOCK_INVALID');
  const outcome = transition(state.core, event, host, selectedPin);
  if (event.payload.native) {
    const prior = state.receipts.find((row: Row) => row.event.payload.native?.id === event.payload.native.id);
    requireFact(!prior || same(prior.event.payload.native, event.payload.native), 'INPUT_INVALID');
  }
  outcome.core.revision = (BigInt(state.core.revision) + 1n).toString();
  if (event.clock.status === 'AVAILABLE') outcome.core.last_clock = event.clock.instant;
  const receipt = { event_digest: digest('reservation-event', event), prior_state_digest: stateDigest(state), revision: outcome.core.revision, next_core_digest: digest('reservation-core', outcome.core), decision: outcome.decision, reservation: outcome.reservation, budgets: outcome.budgets, authority_result: outcome.authority_result, reasons: uniqueSorted(outcome.reasons) };
  if (outcome.recovery_disposition_digest) Object.assign(receipt, { recovery_disposition_digest: outcome.recovery_disposition_digest });
  return { schema: VERSION + '/reservation-state', specification_pin: selectedPin, core: outcome.core, receipts: [...state.receipts, { event: clone(event), host_evidence: clone(host), receipt }] };
}
export function stateAdmission(state: Row, selectedPin: string): void {
  requireShape('reservation.schema.json', 'state', state);
  requireFact(state.specification_pin === selectedPin, 'STATE_INVALID');
  const ids = new Set<string>();
  try {
    let replay = initialReservationState(state.core.configuration, selectedPin);
    for (const record of state.receipts) {
      requireFact(!ids.has(record.event.id), 'STATE_INVALID'); ids.add(record.event.id);
      replay = append(replay, record.event, record.host_evidence, selectedPin);
      requireFact(same(replay.receipts.at(-1).receipt, record.receipt), 'STATE_INVALID');
    }
    requireFact(same(replay, state), 'STATE_INVALID');
  } catch (error) { if (error instanceof Refusal || error instanceof AdmissionError) throw new Refusal('STATE_INVALID'); throw error; }
}
export function reservationPermissionReasons(core: Row, reservationId: string, at: string, selectedPin: string): string[] {
  const reservation = core.reservations.find((row: Row) => row.id === reservationId);
  if (!reservation) return ['RESERVATION_NOT_FOUND'];
  const reasons: string[] = [], contributions = reservation.contributions;
  const intersects = (anchor: string, key: Row[] | null): boolean => contributions.some((row: Row) => row.anchor === anchor && (key === null || same(row.key, key)));
  const resolved = (id: string): boolean => { const selected = core.reservations.find((row: Row) => row.id === id); return !!selected && reservationDispositionClears(core, selected, at); };
  if (core.effects.some((row: Row) => row.disposition === 'DISPUTED' && (row.reason === 'UNKNOWN_RESERVATION' || !resolved(row.reservation)) && row.blocked_partitions.some((partition: Row) => intersects(partition.anchor, partition.key))) || core.reservations.some((row: Row) => row.status === 'DISPUTED' && !resolved(row.id) && row.contributions.some((contribution: Row) => intersects(contribution.anchor, contribution.key)))) reasons.push('EXPOSURE_DISPUTED');
  const clock = { source: core.configuration.clock_source, status: 'AVAILABLE', instant: at };
  for (const anchor of affectedAnchors(reservation)) {
    const budget = registered(core, anchor)!, history = budget.history, reason = historyReason(budget, history, clock);
    if (reason) { reasons.push(reason); continue; }
    const authorization = selectedAuthorization(budget, reservation.authority), operation = projectNative(budget, authorization, nativeRequest(reservation.authority.proposal), reservation.occurrence_key);
    const result = evaluateAggregate(historyRequest(budget.definition.aggregate, [operation], pending(core, anchor, reservation.id, at), clock, history, selectedPin), selectedPin);
    if (result.status !== 'SATISFIED') reasons.push(result.status === 'VIOLATED' ? 'BOUND_VIOLATED' : 'HISTORY_INCOMPLETE');
  }
  return uniqueSorted(reasons);
}
export function reservationCompletionReasons(core: Row, reservationId: string, evidence: Row, at: string): string[] {
  const reservation = core.reservations.find((row: Row) => row.id === reservationId);
  if (!reservation) return ['RESERVATION_NOT_FOUND'];
  const noEffect = evidence.status === 'NO_EFFECT_ESTABLISHED', effectId = noEffect ? null : evidence.native_operation_id;
  const reasons: string[] = [], current = effectiveReservationDisposition(core, reservation, at), requiredResult = noEffect ? 'ESTABLISH_NO_EFFECT' : 'ESTABLISH_EFFECT';
  const selected = current?.result === requiredResult ? selectedRegistryNatives(current.evidence).find((row: Row) => row.outcome === (noEffect ? 'NO_EFFECT' : 'EFFECT') && row.effect_id === effectId) : core.effects.find((row: Row) => row.reservation === reservationId && row.native.effect_id === effectId && row.disposition === (noEffect ? 'RELEASED' : 'MATCHED'))?.native;
  const request = nativeRequest(reservation.authority.proposal);
  if (!selected || !same(selected.request, request) || (noEffect ? !selected.rules_out_past_and_future_effects : !same(selected.observed_request, request)) || reservation.status === 'DISPUTED' && current?.result !== requiredResult) return ['RECOVERY_BASIS_CHANGED'];
  if (selected.provider !== evidence.provider || selected.source !== evidence.source || selected.occurred_at !== evidence.event_time || !same(selected.actual_fields, evidence.actual_fields) || !same(selected.collections, evidence.collections)) return ['RECOVERY_BASIS_CHANGED'];
  const intersects = (anchor: string, key: Row[] | null): boolean => reservation.contributions.some((row: Row) => row.anchor === anchor && (key === null || same(row.key, key)));
  const resolved = (id: string): boolean => { const row = core.reservations.find((row: Row) => row.id === id); return !!row && reservationDispositionClears(core, row, at); };
  if (core.effects.some((row: Row) => row.disposition === 'DISPUTED' && (row.reason === 'UNKNOWN_RESERVATION' || !resolved(row.reservation)) && row.blocked_partitions.some((partition: Row) => intersects(partition.anchor, partition.key))) || core.reservations.some((row: Row) => row.status === 'DISPUTED' && !resolved(row.id) && row.contributions.some((row: Row) => intersects(row.anchor, row.key)))) reasons.push('EXPOSURE_DISPUTED');
  const clock = { source: core.configuration.clock_source, status: 'AVAILABLE', instant: at };
  for (const anchor of affectedAnchors(reservation)) {
    const budget = registered(core, anchor)!, history = budget.history, reason = historyReason(budget, history, clock);
    if (reason) { reasons.push(reason); continue; }
    if (noEffect) continue;
    for (const contribution of projectedContributions(budget, projectNative(budget, selectedAuthorization(budget, reservation.authority), selected.observed_request, reservation.occurrence_key))) {
      const expected = committedRecord(budget, contribution, selected.effect_id, selected.occurred_at);
      if (!fullHistory(history) || !same(latestHistory(history).get(expected.id), expected)) reasons.push('HISTORY_UNCORROBORATED');
    }
  }
  return uniqueSorted(reasons);
}
export function aggregateStep(input: unknown, selectedPin: string): Row {
  if (!shape('reservation.schema.json', 'input', input)) return { status: 'REFUSED', code: 'SCHEMA_INVALID', path: '' };
  const request = input as Row;
  try {
    embeddedReturns(input);
    requireFact(request.specification_pin === selectedPin, 'DEPENDENCY_MISMATCH');
    requireFact(request.host_evidence.registry_digest === digest('reservation-registry', request.state.core.configuration) && request.event.clock.source === request.state.core.configuration.clock_source, 'DEPENDENCY_MISMATCH');
    requireFact(request.state_digest === stateDigest(request.state), 'STATE_INVALID');
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
