import { AdmissionError, byteCompare, canonical } from './canonical.ts';
import { compare, decimal } from './math.ts';
import { instant } from './time.ts';
export type RecordValue = Record<string, any>;
export type TypedValue = { type_ref: string; value: string | boolean };
export type ScalarType = { id: string; kind: string; unit: string | null; nonnegative: boolean };
export type Types = Map<string, ScalarType>;
export const same = (a: unknown, b: unknown): boolean => canonical(a) === canonical(b);
export const ordered = (values: string[]): boolean => values.every((value, index) => index === 0 || byteCompare(values[index - 1], value) < 0);
export const setOrder = (values: unknown[]): boolean => ordered(values.map(canonical));
export function typed(value: TypedValue, types: Types): void {
  const type = types.get(value.type_ref);
  if (!type) throw new AdmissionError('REFERENCE_INVALID');
  if (type.kind === 'BOOLEAN') {
    if (typeof value.value !== 'boolean') throw new AdmissionError('TYPE_INVALID');
    return;
  }
  if (typeof value.value !== 'string') throw new AdmissionError('TYPE_INVALID');
  if (type.kind === 'INSTANT') {
    try { if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value.value)) throw new Error(); instant(value.value); }
    catch { throw new AdmissionError('TYPE_INVALID'); }
  }
  if (type.kind === 'IDENTITY' && !value.value.length) throw new AdmissionError('TYPE_INVALID');
  if (type.kind === 'INTEGER' && (!/^-?(?:0|[1-9][0-9]*)$/.test(value.value) || value.value === '-0')) throw new AdmissionError('TYPE_INVALID');
  if (type.kind === 'INTEGER' || type.kind === 'DECIMAL') decimal(value.value, !type.nonnegative);
}
// Static predicate admission accumulates every fault in the tree: a reference
// fault in one branch cannot hide a type fault in another, and the caller picks
// the refusal by phase (TYPE_INVALID is phase 1, REFERENCE_INVALID phase 2).
// An operand with an unknown type reference (or a FIELD its row's step does not
// declare) has no nominal type: only rules its known type violates on its own
// are TYPE_INVALID; a violation that depends on the unknown type is left to the
// REFERENCE_INVALID fault already recorded for that operand.
export function predicateFaults(node: RecordValue, fields: Map<string, string>, types: Types, checkMemberOrder = true, faults = new Set<string>()): Set<string> {
  const attempt = (action: () => void): void => {
    try { action(); } catch (error) { if (error instanceof AdmissionError) faults.add(error.code); else throw error; }
  };
  function literal(value: TypedValue): string | null {
    if (!types.has(value.type_ref)) { faults.add('REFERENCE_INVALID'); return null; }
    attempt(() => typed(value, types)); return value.type_ref;
  }
  function operand(value: RecordValue): string | null {
    if (value.kind === 'LITERAL') return literal(value.value);
    const type = fields.get(value.name);
    if (!type || !types.has(type)) { faults.add('REFERENCE_INVALID'); return null; }
    return type;
  }
  if (node.kind === 'BOOLEAN') return faults;
  if (node.kind === 'ALL' || node.kind === 'ANY') { for (const child of node.operands) predicateFaults(child, fields, types, checkMemberOrder, faults); return faults; }
  if (node.kind === 'NOT') return predicateFaults(node.operand, fields, types, checkMemberOrder, faults);
  if (node.kind === 'MEMBER') {
    const type = operand(node.value);
    if (checkMemberOrder && !setOrder(node.members)) faults.add('TYPE_INVALID');
    for (const member of node.members) { const memberType = literal(member); if (type !== null && memberType !== null && memberType !== type) faults.add('TYPE_INVALID'); }
    return faults;
  }
  const a = operand(node.left), b = operand(node.right);
  if (a !== null && b !== null && a !== b) faults.add('TYPE_INVALID');
  if (node.kind === 'COMPARE') for (const type of [a, b]) if (type !== null && !['INTEGER', 'DECIMAL'].includes(types.get(type)!.kind)) faults.add('TYPE_INVALID');
  return faults;
}
export function predicateTypes(node: RecordValue, fields: Map<string, string>, types: Types, checkMemberOrder = true): void {
  const faults = predicateFaults(node, fields, types, checkMemberOrder);
  for (const code of ['TYPE_INVALID', 'REFERENCE_INVALID']) if (faults.has(code)) throw new AdmissionError(code);
  if (faults.size) throw new AdmissionError([...faults][0]);
}
export function predicate(node: RecordValue, fields: Map<string, TypedValue>): boolean {
  const value = (operand: RecordValue): TypedValue => operand.kind === 'LITERAL' ? operand.value : fields.get(operand.name)!;
  if (node.kind === 'BOOLEAN') return node.value;
  if (node.kind === 'ALL' || node.kind === 'ANY') {
    const values = node.operands.map((child: RecordValue) => predicate(child, fields));
    return node.kind === 'ALL' ? values.every(Boolean) : values.some(Boolean);
  }
  if (node.kind === 'NOT') return !predicate(node.operand, fields);
  if (node.kind === 'MEMBER') return node.members.some((member: TypedValue) => same(member, value(node.value)));
  const a = value(node.left), b = value(node.right);
  if (node.kind === 'EQUAL') return same(a, b);
  const comparison = compare(decimal(a.value as string, true), decimal(b.value as string, true));
  return node.operator === 'LT' ? comparison < 0 : node.operator === 'LTE' ? comparison <= 0 : node.operator === 'GT' ? comparison > 0 : comparison >= 0;
}
