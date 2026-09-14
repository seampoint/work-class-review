import { createHash } from 'node:crypto';

export type Json = null | boolean | string | Json[] | { [key: string]: Json };
export class AdmissionError extends Error {
  code: string;
  path: string;
  constructor(code: string, path = '') { super(code); this.code = code; this.path = path; }
}
export function scalarString(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const c = value.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const next = value.charCodeAt(++i);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
    } else if (c >= 0xdc00 && c <= 0xdfff) return false;
  }
  return true;
}
export function canonical(value: unknown): string {
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'string') {
    if (!scalarString(value)) throw new AdmissionError('UNICODE_INVALID');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (typeof value !== 'object') throw new AdmissionError('NUMBER_FORBIDDEN');
  return `{${Object.keys(value).sort().map(key => `${canonical(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(',')}}`;
}

// This parser preserves duplicate-key detection before JavaScript object admission.
export function parseRestricted(text: string): Json {
  let cursor = 0;
  function space() { while (/[ \t\r\n]/.test(text[cursor] ?? '') && cursor < text.length) cursor++; }
  function string(): string {
    const start = cursor++;
    while (cursor < text.length) {
      const c = text[cursor++];
      if (c === '\\') { cursor++; continue; }
      if (c === '"') {
        let value: string;
        try { value = JSON.parse(text.slice(start, cursor)) as string; }
        catch { throw new AdmissionError('JSON_INVALID'); }
        if (!scalarString(value)) throw new AdmissionError('UNICODE_INVALID');
        return value;
      }
    }
    throw new AdmissionError('JSON_INVALID');
  }
  function value(): Json {
    space(); const c = text[cursor];
    if (c === '"') return string();
    if (c === '{') {
      cursor++; space(); const out: Record<string, Json> = Object.create(null);
      if (text[cursor] === '}') { cursor++; return out; }
      while (cursor < text.length) {
        if (text[cursor] !== '"') throw new AdmissionError('JSON_INVALID');
        const key = string();
        if (Object.hasOwn(out, key)) throw new AdmissionError('DUPLICATE_KEY');
        space(); if (text[cursor++] !== ':') throw new AdmissionError('JSON_INVALID');
        out[key] = value(); space();
        const end = text[cursor++]; if (end === '}') return out;
        if (end !== ',') throw new AdmissionError('JSON_INVALID'); space();
      }
    }
    if (c === '[') {
      cursor++; space(); const out: Json[] = [];
      if (text[cursor] === ']') { cursor++; return out; }
      while (cursor < text.length) {
        out.push(value()); space(); const end = text[cursor++];
        if (end === ']') return out;
        if (end !== ',') throw new AdmissionError('JSON_INVALID');
      }
    }
    for (const [token, result] of [['null', null], ['true', true], ['false', false]] as const) {
      if (text.slice(cursor, cursor + token.length) === token) { cursor += token.length; return result; }
    }
    if (c === '-' || (c >= '0' && c <= '9')) throw new AdmissionError('NUMBER_FORBIDDEN');
    throw new AdmissionError('JSON_INVALID');
  }
  const result = value(); space();
  if (cursor !== text.length) throw new AdmissionError('JSON_INVALID');
  return result;
}
export function decodeArtifact(encoded: string): { value: Json; bytes: Buffer } {
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) throw new AdmissionError('BASE64_INVALID');
  const bytes = Buffer.from(encoded, 'base64');
  if (bytes.toString('base64') !== encoded) throw new AdmissionError('BASE64_INVALID');
  let text: string;
  try { text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes); }
  catch { throw new AdmissionError('UTF8_INVALID'); }
  const value = parseRestricted(text);
  if (canonical(value) !== text) throw new AdmissionError('NONCANONICAL');
  // Duplicate-key and canonical-byte admission already ran through the
  // restricted parser. Reparse the admitted bytes to ordinary objects because
  // JSON Schema's uniqueItems comparison expects the standard Object prototype.
  return { value: JSON.parse(text) as Json, bytes };
}
export function hashBytes(bytes: Uint8Array): string { return `sha256:${createHash('sha256').update(bytes).digest('hex')}`; }
export function digest(role: string, value: unknown): string {
  return hashBytes(Buffer.concat([Buffer.from(`seampoint.work-class/1.0.0-draft.2/${role}\n`), Buffer.from(canonical(value))]));
}
export const byteCompare = (a: string, b: string): number => Buffer.compare(Buffer.from(a), Buffer.from(b));
