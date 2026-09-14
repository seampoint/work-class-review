import { pathToFileURL } from 'node:url';
import { AdmissionError, canonical, decodeArtifact, parseRestricted } from './canonical.ts';
import { evaluateAggregate, validateDefinition } from './aggregate.ts';
import { evaluateAuthority, validateAuthorityDefinition } from './authority.ts';
import { checkEvidence, readback, validateBoundary, validateEvidenceArtifact } from './evidence.ts';
import { deploy, step } from './lifecycle.ts';
import { aggregateStep } from './reservations.ts';
import { LIMITS, PROTOCOL, requireShape, selectedCandidate, VERSION } from './schema.ts';
import { validateWorkClass } from './work-class.ts';
import type { RecordValue as Row } from './values.ts';

const OPERATIONS = ['aggregate-step', 'capabilities', 'check-evidence', 'deploy', 'evaluate', 'readback', 'step', 'validate'];
const ROLES = ['AGGREGATE_EVALUATOR', 'AUTHORITY_EVALUATOR', 'CHOICE_LOOP_RUNTIME', 'DEADLINE_RUNTIME', 'LINEAR_WORK_RUNTIME', 'PARALLEL_FANOUT_RUNTIME', 'REFERENCE_SINGLE_PROCESS_CONTENTION', 'REVIEW_EVIDENCE', 'SHARED_BUDGET_TRANSITIONS'];
const CLAIMED_ROLES = process.env.WORK_CLASS_ADAPTER_ROLES === undefined
  ? ROLES
  : process.env.WORK_CLASS_ADAPTER_ROLES.split(',').filter(Boolean).sort();
const CLAIMED_OPERATIONS = CLAIMED_ROLES.includes('SHARED_BUDGET_TRANSITIONS') ? OPERATIONS : OPERATIONS.filter(operation => operation !== 'aggregate-step');
function object(value: unknown): value is Row { return value !== null && typeof value === 'object' && !Array.isArray(value); }

function operationResult(operation: string, input: Row, pin: string): unknown {
  if (operation === 'capabilities') {
    requireShape('protocol.schema.json', 'capabilitiesInput', input);
    return { status: 'CAPABILITIES', protocol: PROTOCOL, specification_pin: pin, roles: CLAIMED_ROLES, operations: CLAIMED_OPERATIONS, tzdb: '2025a', limits: LIMITS };
  }
  if (operation === 'deploy') return deploy(input, pin);
  if (operation === 'step') return step(input, pin);
  if (operation === 'check-evidence') return checkEvidence(input, pin);
  if (operation === 'aggregate-step') return CLAIMED_ROLES.includes('SHARED_BUDGET_TRANSITIONS') ? aggregateStep(input, pin) : { status: 'REFUSED', code: 'ROLE_UNSUPPORTED', path: '' };
  if (operation === 'evaluate') {
    requireShape('protocol.schema.json', 'evaluateInput', input);
    return input.kind === 'AUTHORITY' ? evaluateAuthority(input.request, pin) : evaluateAggregate(input.request, pin);
  }
  requireShape('protocol.schema.json', 'artifactInput', input);
  let artifact: unknown;
  try { artifact = decodeArtifact(input.artifact_bytes_base64).value; }
  catch (error) {
    if (!(error instanceof AdmissionError)) throw error;
    throw new AdmissionError(error.code === 'NONCANONICAL' || error.code === 'NUMBER_FORBIDDEN' ? 'ARTIFACT_NONCANONICAL' : 'ARTIFACT_ENCODING_INVALID');
  }
  if (input.specification_pin !== pin) throw new AdmissionError('VERSION_UNSUPPORTED');
  const suffix: Record<string, string> = {
    AGGREGATE_DEFINITION: '/aggregate-definition', AUTHORITY_DEFINITION: '/authority-definition', WORK_CLASS: '/work-class-definition',
    BOUNDARY_RECORD: '/boundary-record', EVIDENCE_RECORD: '/evidence-record',
  };
  if (object(artifact) && typeof artifact.schema === 'string' && artifact.schema !== VERSION + suffix[input.kind]) throw new AdmissionError('VERSION_UNSUPPORTED');
  let identity: string;
  if (input.kind === 'AGGREGATE_DEFINITION') identity = validateDefinition(artifact).identity;
  else if (input.kind === 'AUTHORITY_DEFINITION') {
    const result = validateAuthorityDefinition(artifact);
    if (result.status !== 'ACCEPTED') throw new AdmissionError(result.code);
    identity = result.digest;
  } else if (input.kind === 'WORK_CLASS') identity = validateWorkClass(artifact, pin).digest;
  else if (input.kind === 'BOUNDARY_RECORD') identity = validateBoundary(artifact, pin);
  else identity = validateEvidenceArtifact(artifact);
  return operation === 'validate' ? { status: 'ACCEPTED', digest: identity } : { status: 'READBACK', digest: identity, lines: readback(artifact) };
}

export function respond(value: unknown, pin: string): Row {
  const requestId = object(value) && typeof value.request_id === 'string' ? value.request_id : null;
  const operation = object(value) && typeof value.operation === 'string' ? value.operation : null;
  const responseOperation = operation;
  if (!object(value) || !operation || !OPERATIONS.includes(operation) || !object(value.input) || value.protocol !== PROTOCOL || !('request_id' in value) || Object.keys(value).sort().join('|') !== 'input|operation|protocol|request_id') {
    return { protocol: PROTOCOL, request_id: requestId, operation: responseOperation, result: { status: 'REFUSED', code: 'PROTOCOL_INVALID', path: '' } };
  }
  try {
    return { protocol: PROTOCOL, request_id: requestId, operation, result: operationResult(operation, value.input, pin) };
  } catch (error) {
    if (!(error instanceof AdmissionError)) throw error;
    return { protocol: PROTOCOL, request_id: requestId, operation, result: { status: 'REFUSED', code: error.code === 'TIME_INVALID' ? 'INPUT_INVALID' : error.code, path: '' } };
  }
}

async function main(): Promise<void> {
  const pin = selectedCandidate();
  let pending = Buffer.alloc(0);
  for await (const chunk of process.stdin) {
    pending = Buffer.concat([pending, chunk]);
    let boundary: number;
    while ((boundary = pending.indexOf(10)) >= 0) {
      const line = pending.subarray(0, boundary); pending = pending.subarray(boundary + 1);
      const decoded = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(line);
      parseRestricted(decoded);
      process.stdout.write(canonical(respond(JSON.parse(decoded), pin)) + '\n');
    }
  }
  if (pending.length) throw new Error('Transport request lacks its final line-feed');
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch(error => { process.stderr.write(String(error) + '\n'); process.exitCode = 1; });
