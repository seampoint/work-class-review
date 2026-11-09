import { AdmissionError, parseRestricted } from './canonical.ts';
import type { RecordValue as Row } from './values.ts';

export const FLOW_FRAME_BYTES = 17825792;
export const FLOW_PUBLIC_STATUS = 'Unable to process this request.';
export type FlowRoute = {
  interface: string;
  operation: string;
  recipient_field: string;
  channel: string;
  purpose: string;
  connector: { id: string; version: string; binding_digest: string };
  immediate_custody: true;
};

export function parseFlowFrame(frame: Uint8Array): Row {
  if (frame.byteLength > FLOW_FRAME_BYTES) throw new AdmissionError('LIMIT_EXCEEDED');
  if (frame[frame.byteLength - 1] !== 10 || frame.subarray(0, -1).includes(10)) throw new AdmissionError('SCHEMA_INVALID');
  let text: string;
  try { text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(frame); }
  catch { throw new AdmissionError('SCHEMA_INVALID'); }
  let depth = 0, quoted = false, escaped = false;
  for (const character of text) {
    if (quoted) {
      if (escaped) escaped = false;
      else if (character === '\\') escaped = true;
      else if (character === '"') quoted = false;
    } else if (character === '"') quoted = true;
    else if (character === '{' || character === '[') { if (++depth > 128) throw new AdmissionError('LIMIT_EXCEEDED'); }
    else if (character === '}' || character === ']') depth--;
  }
  try { parseRestricted(text); return JSON.parse(text); }
  catch { throw new AdmissionError('SCHEMA_INVALID'); }
}
