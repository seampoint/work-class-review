import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { instant } from './time.ts';
import { ordered, same, typed } from './values.ts';
import type { RecordValue as Row, Types } from './values.ts';

const check = (condition: unknown, code: string): void => { if (!condition) throw new AdmissionError(code); };
export const newSlot = (slot: Row): boolean => slot.uniqueness !== undefined;
export const mediatedSlot = (slot: Row): boolean => slot.uniqueness?.kind === 'EXCLUSIVE_MEDIATOR_SEEDED';
const slotTypes = (slot: Row): Types => new Map(slot.types.map((row: Row) => [row.id, row])) as Types;

export function admitHistorySlot(slot: Row): void {
  if (!newSlot(slot)) return;
  const types = slotTypes(slot);
  check(ordered(slot.types.map((row: Row) => row.id)), 'INPUT_INVALID');
  for (const type of types.values()) check((type.unit === null || type.kind === 'DECIMAL') && (!type.nonnegative || ['INTEGER', 'DECIMAL'].includes(type.kind)), 'TYPE_INVALID');
  check(new Set(slot.key_shape.map((row: Row) => row.name)).size === slot.key_shape.length, 'INPUT_INVALID');
  for (const fields of [slot.history_record_fields.held, slot.history_record_fields.consumed]) {
    check(ordered(fields.map((row: Row) => row.name)), 'INPUT_INVALID');
    for (const field of fields) check(types.has(field.type_ref), 'REFERENCE_INVALID');
  }
  check(slot.history_projection.length === slot.key_shape.length, 'INPUT_INVALID');
  for (const [i, row] of slot.history_projection.entries()) {
    const target = slot.key_shape[i], ref = row.kind === 'LITERAL' ? row.value.type_ref : row.type_ref;
    check(types.has(target.type_ref) && types.has(ref), 'REFERENCE_INVALID');
    check(row.key_field === target.name, 'INPUT_INVALID');
    check(ref === target.type_ref, 'TYPE_INVALID');
    if (row.kind === 'LITERAL') typed(row.value, types);
    else if (row.kind === 'NATIVE_FIELD') for (const fields of [slot.history_record_fields.held, slot.history_record_fields.consumed]) {
      const field = fields.find((field: Row) => field.name === row.field);
      check(field, 'REFERENCE_INVALID'); check(field.type_ref === ref, 'TYPE_INVALID');
    }
    else if (['SOURCE_REQUEST', 'RECORD'].includes(row.kind)) check(['IDENTITY', 'STRING'].includes(types.get(ref)!.kind), 'TYPE_INVALID');
    else throw new AdmissionError('UNSUPPORTED_RELATION');
  }
  if (slot.uniqueness.kind === 'PROVIDER_UNIQUENESS') check(same(slot.uniqueness.atomic_scope, { slot: slot.slot, namespace: slot.namespace, key_shape: slot.key_shape }), 'DEPENDENCY_MISMATCH');
}

export function admitRequestedKey(slot: Row, authority: Row, key: Row): void {
  if (!newSlot(slot)) return;
  const types = slotTypes(slot), step = authority.work_class.steps.find((row: Row) => row.id === authority.proposal.step);
  const declaration = step.exclusive_keys.find((row: Row) => row.id === key.id);
  check(declaration && declaration.projection.length === slot.key_shape.length && key.key.length === slot.key_shape.length, 'DEPENDENCY_MISMATCH');
  for (const [i, position] of slot.key_shape.entries()) {
    const projected = declaration.projection[i], ref = projected.value?.type_ref ?? projected.type_ref;
    check((projected.key_field ?? projected.field) === position.name && ref === position.type_ref && key.key[i].type_ref === ref, 'DEPENDENCY_MISMATCH');
    const type = authority.work_class.types.find((row: Row) => row.id === ref);
    check(type && same(type, types.get(ref)), 'DEPENDENCY_MISMATCH'); typed(key.key[i], types);
  }
}

export function seedHistory(core: Row, event: Row): { usable: boolean } {
  const slot = core.configuration.exclusive_slots.find((row: Row) => row.slot === event.payload.slot);
  check(slot, 'REFERENCE_INVALID'); check(mediatedSlot(slot), 'UNSUPPORTED_RELATION');
  check(event.clock.status === 'AVAILABLE', 'CLOCK_INVALID');
  const { coverage, claims } = event.payload, guarantee = slot.uniqueness;
  check(coverage.slot === slot.slot && ['provider', 'source', 'record_type', 'history_scope', 'cutover_id'].every(name => coverage[name] === guarantee[name]) && coverage.as_of === event.clock.instant, 'BINDING_MISMATCH');
  check(!(core.key_history ?? []).some((row: Row) => row.snapshot.slot === slot.slot), 'DEFINITION_CONFLICT');
  const registry = digest('reservation-registry', core.configuration), types = slotTypes(slot);
  const fullClaims = claims.map(canonical);
  check(new Set(fullClaims).size === claims.length, 'INPUT_INVALID');
  check(same(claims, [...claims].sort((a: Row, b: Row) => byteCompare(a.key_digest, b.key_digest) || byteCompare(canonical(a), canonical(b)))), 'INPUT_INVALID');
  for (const claim of claims) {
    const record = claim.native_record, request = claim.source_request, provenance = claim.request_provenance;
    const recordDigest = digest('exclusive-native-history', record);
    check(claim.slot === slot.slot && claim.namespace === slot.namespace && claim.acquisition_event === event.id && claim.status === record.state && claim.settlement_evidence === (record.state === 'HELD' ? null : record.record_id), 'BINDING_MISMATCH');
    check(['provider', 'source', 'record_type'].every(name => record[name] === guarantee[name]) && instant(record.occurred_at) <= instant(coverage.as_of), 'BINDING_MISMATCH');
    const inventory = slot.history_record_fields[record.state.toLowerCase()];
    check(same(record.native_fields.map((row: Row) => ({ name: row.name, type_ref: row.value.type_ref })), inventory), 'BINDING_MISMATCH');
    for (const field of record.native_fields) typed(field.value, types);
    check(claim.record_digest === recordDigest && provenance.provider === guarantee.provider && provenance.source === guarantee.source && provenance.native_record_digest === recordDigest && provenance.source_request_digest === digest('exclusive-source-request', request), 'DEPENDENCY_MISMATCH');
    const owner = record.work_occurrence === null ? { kind: 'NATIVE_HISTORY', provider: record.provider, source: record.source, record_id: record.record_id, record_digest: recordDigest } : { kind: 'WORK_OCCURRENCE', ...record.work_occurrence };
    check(same(claim.owner, owner), 'BINDING_MISMATCH');
    const key = slot.history_projection.map((row: Row) => {
      if (row.kind === 'LITERAL') return row.value;
      if (row.kind === 'NATIVE_FIELD') return record.native_fields.find((field: Row) => field.name === row.field).value;
      const value = (row.kind === 'RECORD' ? record : request)[row.member];
      check(typeof value === 'string' && value.length > 0, 'TYPE_INVALID'); return { type_ref: row.type_ref, value };
    });
    check(same(claim.key, key) && claim.key_digest === digest('exclusive-key', { registry, slot: slot.slot, namespace: slot.namespace, key }), 'BINDING_MISMATCH');
  }
  check(new Set(claims.map((row: Row) => row.key_digest)).size === claims.length, 'OCCURRENCE_CONFLICT');
  check(!claims.some((claim: Row) => core.exclusive_keys.some((row: Row) => row.key_digest === claim.key_digest)), 'OCCURRENCE_CONFLICT');
  if (!coverage.complete || !coverage.exclusive_writers) return { usable: false };
  check(core.exclusive_keys.length + claims.length <= 4096, 'LIMIT_EXCEEDED');
  const snapshot = { registry_digest: registry, event_id: event.id, slot: slot.slot, coverage: structuredClone(coverage), claims: structuredClone(claims) };
  core.key_history.push({ snapshot_digest: digest('exclusive-history-snapshot', snapshot), snapshot });
  core.key_history.sort((a: Row, b: Row) => byteCompare(a.snapshot.slot, b.snapshot.slot));
  core.exclusive_keys.push(...claims.map((claim: Row) => Object.fromEntries(['key_digest', 'slot', 'namespace', 'key', 'owner', 'acquisition_event', 'status', 'settlement_evidence'].map(name => [name, structuredClone(claim[name])]))));
  core.exclusive_keys.sort((a: Row, b: Row) => byteCompare(a.key_digest, b.key_digest));
  return { usable: true };
}

export function occurrenceOwns(row: Row, proposal: Row): boolean {
  return row.owner ? same(row.owner, { kind: 'WORK_OCCURRENCE', work_class: proposal.work_class, instance_id: proposal.instance, occurrence_id: proposal.occurrence }) : row.owner_instance === proposal.instance && row.owner_occurrence === proposal.occurrence;
}
