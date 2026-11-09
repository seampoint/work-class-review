import { AdmissionError } from './canonical.ts';
import { decimal } from './math.ts';
import { readFileSync } from 'node:fs';

const SECOND = 1_000_000_000n;
type Civil = { year: number; month: number; day: number; hour: number; minute: number; second: number };
const zones = new Set(readFileSync(new URL('./tzdb-2025a-zones.txt', import.meta.url), 'utf8').trim().split('\n'));
export const validTimezone = (value: string): boolean => zones.has(value);

function epochMilliseconds(civil: Civil): number {
  const date = new Date(0);
  date.setUTCFullYear(civil.year, civil.month - 1, civil.day);
  date.setUTCHours(civil.hour, civil.minute, civil.second, 0);
  if (date.getUTCFullYear() !== civil.year || date.getUTCMonth() + 1 !== civil.month || date.getUTCDate() !== civil.day || date.getUTCHours() !== civil.hour || date.getUTCMinutes() !== civil.minute || date.getUTCSeconds() !== civil.second) throw new AdmissionError('TIME_INVALID');
  return date.valueOf();
}

export function instant(text: string): bigint {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{9}))?Z$/.exec(text);
  if (!match || match[1] === '0000') throw new AdmissionError('TIME_INVALID');
  const parts = match.slice(1, 7).map(Number);
  const civil = { year: parts[0], month: parts[1], day: parts[2], hour: parts[3], minute: parts[4], second: parts[5] };
  return BigInt(epochMilliseconds(civil)) * 1_000_000n + BigInt(match[7] ?? '0');
}

export function instantText(value: bigint, fractional = false): string {
  let seconds = value / SECOND;
  let fraction = value % SECOND;
  if (fraction < 0n) { seconds--; fraction += SECOND; }
  const date = new Date(Number(seconds * 1000n));
  if (!Number.isFinite(date.valueOf()) || date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) throw new AdmissionError('TIME_RANGE');
  return date.toISOString().slice(0, 19) + (fractional || fraction !== 0n ? '.' + fraction.toString().padStart(9, '0') : '') + 'Z';
}

export function duration(text: string): bigint {
  const value = decimal(text);
  if (value.scale > 9) throw new AdmissionError('TIME_INVALID');
  return value.coefficient * 10n ** BigInt(9 - value.scale);
}

function formatter(timezone: string): Intl.DateTimeFormat {
  if (process.versions.tz !== '2025a') throw new Error('The calendar implementation requires IANA tzdb 2025a');
  try {
    return new Intl.DateTimeFormat('en-GB-u-ca-gregory-nu-latn', {
      timeZone: timezone === 'Factory' ? 'Etc/UTC' : timezone, era: 'short', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    });
  } catch { throw new AdmissionError('TIME_INVALID'); }
}

function localCivil(format: Intl.DateTimeFormat, seconds: bigint): Civil {
  const parts = Object.fromEntries(format.formatToParts(new Date(Number(seconds * 1000n))).map(part => [part.type, part.value]));
  return { year: parts.era === 'BC' ? 1 - Number(parts.year) : Number(parts.year), month: Number(parts.month), day: Number(parts.day), hour: Number(parts.hour), minute: Number(parts.minute), second: Number(parts.second) };
}

function localToInstant(civil: Civil, format: Intl.DateTimeFormat, ambiguous: string, nonexistent: string): bigint {
  const naive = BigInt(epochMilliseconds(civil)) / 1000n;
  const offsets = new Set<bigint>();
  for (let hour = -72; hour <= 72; hour++) {
    const probe = naive + BigInt(hour * 3600);
    offsets.add(BigInt(epochMilliseconds(localCivil(format, probe))) / 1000n - probe);
  }
  const candidates = [...offsets].map(offset => naive - offset);
  const exact = candidates.filter(candidate => epochMilliseconds(localCivil(format, candidate)) === Number(naive * 1000n)).sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
  if (exact.length === 1) return exact[0] * SECOND;
  if (exact.length > 1) {
    if (ambiguous === 'INVALID') throw new AdmissionError('TIME_INVALID');
    return (ambiguous === 'EARLIER_OFFSET' ? exact[0] : exact[exact.length - 1]) * SECOND;
  }
  if (nonexistent === 'INVALID') throw new AdmissionError('TIME_INVALID');
  const shifted = candidates.map(candidate => ({ candidate, difference: BigInt(epochMilliseconds(localCivil(format, candidate))) / 1000n - naive }));
  const forward = nonexistent === 'SHIFT_FORWARD';
  const eligible = shifted.filter(item => forward ? item.difference > 0n : item.difference < 0n).sort((a, b) => {
    const x = forward ? a.difference : -a.difference;
    const y = forward ? b.difference : -b.difference;
    return x < y ? -1 : x > y ? 1 : 0;
  });
  if (!eligible.length) throw new AdmissionError('TIME_INVALID');
  return eligible[0].candidate * SECOND;
}

export function calendarStart(now: bigint, timezone: string, period: string, weekStart: string, fiscalMonth: string, ambiguous: string, nonexistent: string): bigint {
  const format = formatter(timezone);
  let seconds = now / SECOND;
  if (now % SECOND < 0n) seconds--;
  const civil = { ...localCivil(format, seconds), hour: 0, minute: 0, second: 0 };
  if (period === 'WEEK') {
    const index = ['SUNDAY', 'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY'].indexOf(weekStart);
    if (index < 0) throw new AdmissionError('TIME_INVALID');
    const date = new Date(epochMilliseconds(civil));
    date.setUTCDate(date.getUTCDate() - (date.getUTCDay() - index + 7) % 7);
    civil.year = date.getUTCFullYear(); civil.month = date.getUTCMonth() + 1; civil.day = date.getUTCDate();
  } else if (period === 'MONTH') civil.day = 1;
  else if (period === 'QUARTER' || period === 'YEAR') {
    const anchor = Number(fiscalMonth);
    if (!Number.isInteger(anchor) || anchor < 1 || anchor > 12) throw new AdmissionError('TIME_INVALID');
    const sinceAnchor = (civil.month - anchor + 12) % 12;
    const monthsBack = period === 'YEAR' ? sinceAnchor : sinceAnchor % 3;
    civil.month -= monthsBack;
    if (civil.month < 1) { civil.month += 12; civil.year--; }
    civil.day = 1;
  } else if (period !== 'DAY') throw new AdmissionError('TIME_INVALID');
  if (civil.year < 1 || civil.year > 9999) throw new AdmissionError('TIME_RANGE');
  return localToInstant(civil, format, ambiguous, nonexistent);
}
