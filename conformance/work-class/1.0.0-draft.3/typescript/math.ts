import { AdmissionError } from './canonical.ts';

export type Decimal = { coefficient: bigint; scale: number };

export function decimal(text: string, signed = false): Decimal {
  const grammar = signed ? /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$/ : /^(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$/;
  if (!grammar.test(text) || text === '-0') throw new AdmissionError('TYPE_INVALID');
  const [integer, fraction = ''] = text.split('.');
  return { coefficient: BigInt(integer + fraction), scale: fraction.length };
}

export function decimalText(value: Decimal): string {
  const negative = value.coefficient < 0n;
  let coefficient = negative ? -value.coefficient : value.coefficient;
  let scale = value.scale;
  while (scale > 0 && coefficient % 10n === 0n) { coefficient /= 10n; scale--; }
  let result = coefficient.toString().padStart(scale + 1, '0');
  if (scale) result = result.slice(0, -scale) + '.' + result.slice(-scale);
  return (negative ? '-' : '') + result;
}

export function add(left: Decimal, right: Decimal): Decimal {
  const scale = Math.max(left.scale, right.scale);
  return {
    coefficient: left.coefficient * 10n ** BigInt(scale - left.scale) + right.coefficient * 10n ** BigInt(scale - right.scale),
    scale,
  };
}

export function compare(left: Decimal, right: Decimal): number {
  const scale = Math.max(left.scale, right.scale);
  const a = left.coefficient * 10n ** BigInt(scale - left.scale);
  const b = right.coefficient * 10n ** BigInt(scale - right.scale);
  return a < b ? -1 : a > b ? 1 : 0;
}

export function sum(values: string[]): string {
  return decimalText(values.reduce((total, value) => add(total, decimal(value)), { coefficient: 0n, scale: 0 }));
}

export function boundSatisfied(value: string, operator: string, bound: string): boolean {
  const order = compare(decimal(value), decimal(bound));
  switch (operator) {
    case 'LT': return order < 0;
    case 'LTE': return order <= 0;
    case 'GT': return order > 0;
    case 'GTE': return order >= 0;
    default: throw new AdmissionError('TYPE_INVALID');
  }
}
