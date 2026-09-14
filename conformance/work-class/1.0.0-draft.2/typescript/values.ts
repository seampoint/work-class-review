import { AdmissionError, byteCompare, canonical } from './canonical.ts';
import { compare, decimal } from './math.ts';
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
  if (type.kind === 'IDENTITY' && !value.value.length) throw new AdmissionError('TYPE_INVALID');
  if (type.kind === 'INTEGER' && (!/^-?(?:0|[1-9][0-9]*)$/.test(value.value) || value.value === '-0')) throw new AdmissionError('TYPE_INVALID');
  if (type.kind === 'INTEGER' || type.kind === 'DECIMAL') decimal(value.value, !type.nonnegative);
}
export function predicateTypes(node: RecordValue, fields: Map<string, string>, types: Types): void {
  function operand(value: RecordValue): string {
    if (value.kind === 'LITERAL') { typed(value.value, types); return value.value.type_ref; }
    const type = fields.get(value.name);
    if (!type || !types.has(type)) throw new AdmissionError('REFERENCE_INVALID');
    return type;
  }
  if (node.kind === 'BOOLEAN') return;
  if (node.kind === 'ALL' || node.kind === 'ANY') { node.operands.forEach((child: RecordValue) => predicateTypes(child, fields, types)); return; }
  if (node.kind === 'NOT') { predicateTypes(node.operand, fields, types); return; }
  if (node.kind === 'MEMBER') {
    const type = operand(node.value);
    if (!setOrder(node.members)) throw new AdmissionError('TYPE_INVALID');
    for (const member of node.members) { typed(member, types); if (member.type_ref !== type) throw new AdmissionError('TYPE_INVALID'); }
    return;
  }
  const a = operand(node.left), b = operand(node.right);
  if (a !== b || (node.kind === 'COMPARE' && !['INTEGER', 'DECIMAL'].includes(types.get(a)!.kind))) throw new AdmissionError('TYPE_INVALID');
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
