import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { requireShape, shape, VERSION } from './schema.ts';
import { same } from './values.ts';
import type { RecordValue as Row } from './values.ts';
import { validateWorkClass } from './work-class.ts';

const clone = <T>(value: T): T => structuredClone(value);
const fail = (code: string, path = ''): never => { throw new AdmissionError(code, path); };

export function readback(value: unknown, path = ''): { path: string; value: string }[] {
  if (value === null || typeof value !== 'object') return [{ path, value: canonical(value) }];
  const entries = Object.entries(value as object);
  if (!entries.length) return [{ path, value: canonical(value) }];
  return entries.flatMap(([key, child]) => readback(child, path + '/' + key.replaceAll('~', '~0').replaceAll('/', '~1')))
    .sort((a, b) => byteCompare(a.path, b.path));
}

function failure(request: Row, code: string): Row {
  return { status: 'EVIDENCE_INVALID', profile: request.profile, role: request.role, code, path: '', specification_pin: request.specification_pin };
}

function sorted(values: string[]): boolean { return values.every((value, i) => i === 0 || byteCompare(values[i - 1], value) < 0); }

// The correspondence form of `check-evidence` after the shared subject and status checks; `deploy`
// applies the same conditions to the correspondence record named by the deployment authorization.
export function correspondenceCode(evidence: Row, workClass: Row, workDigest: string): string | null {
  if (evidence.work_class_digest !== workDigest || evidence.source_id !== workClass.source.id || evidence.source_revision !== workClass.source.revision) return 'BINDING_MISMATCH';
  const mappings = evidence.mappings as Row[];
  if (!sorted(mappings.map(row => row.source_obligation_id)) || mappings.some(row => !sorted(row.provision_paths))) return 'BINDING_MISMATCH';
  if (!sorted(evidence.uncovered_source_obligation_ids) || !sorted(evidence.unsupported_provision_paths)) return 'BINDING_MISMATCH';
  const mappedIds = mappings.map(row => row.source_obligation_id), allSource = [...mappedIds, ...evidence.uncovered_source_obligation_ids].sort(byteCompare);
  if (new Set(allSource).size !== allSource.length || !same(allSource, workClass.source.obligations)) return 'BINDING_MISMATCH';
  const universe = readback(workClass).map(row => row.path);
  const mappedPaths = mappings.flatMap(row => row.provision_paths);
  const coveredPaths = [...new Set([...mappedPaths, ...evidence.unsupported_provision_paths])].sort(byteCompare);
  if (mappedPaths.some((path: string) => evidence.unsupported_provision_paths.includes(path)) || !same(coveredPaths, universe)) return 'BINDING_MISMATCH';
  const edges = mappings.flatMap(row => row.provision_paths.map((path: string) => canonical([row.source_obligation_id, path])));
  if (new Set(edges).size !== edges.length) return 'BINDING_MISMATCH';
  const residue = evidence.residue as Row[];
  const residueKeys = residue.map(row => canonical([row.kind, row.subject]));
  if (new Set(residueKeys).size !== residueKeys.length || !sorted(residueKeys)) return 'BINDING_MISMATCH';
  const expectedResidue = [
    ...evidence.uncovered_source_obligation_ids.map((value: string) => canonical(['SOURCE_OBLIGATION', value])),
    ...evidence.unsupported_provision_paths.map((value: string) => canonical(['ARTIFACT_PROVISION', value])),
  ].sort(byteCompare);
  if (!same(residueKeys, expectedResidue)) return 'BINDING_MISMATCH';
  const reviewSubject = clone(evidence); delete reviewSubject.review;
  if (evidence.review.subject_digest !== digest('correspondence-subject', reviewSubject)) return 'BINDING_MISMATCH';
  if (evidence.review.status !== 'ACCEPTED') return 'EVIDENCE_NOT_ACCEPTED';
  return null;
}

export function checkEvidence(input: unknown, selectedPin: string): Row {
  if (!shape('evidence.schema.json', 'input', input)) return { status: 'REFUSED', code: 'SCHEMA_INVALID', path: '' };
  const request = input as Row;
  if (request.specification_pin !== selectedPin) return { status: 'REFUSED', code: 'VERSION_UNSUPPORTED', path: '' };
  if (request.role !== 'REVIEW_EVIDENCE') return failure(request, 'BINDING_MISMATCH');
  const subject = request.subject, evidence = request.evidence;
  if (subject.candidate_identity !== VERSION || subject.specification_pin !== selectedPin || evidence.subject_digest !== subject.subject_digest) return failure(request, 'BINDING_MISMATCH');
  if (evidence.status !== 'ACCEPTED') return failure(request, 'EVIDENCE_NOT_ACCEPTED');

  if (evidence.kind === 'CORRESPONDENCE') {
    let workDigest: string;
    try { workDigest = validateWorkClass(request.work_class, selectedPin).digest; }
    catch { return failure(request, 'BINDING_MISMATCH'); }
    if (request.profile !== request.work_class.profile || subject.kind !== 'WORK_CLASS' || subject.subject_id !== request.work_class.id || request.work_class_digest !== workDigest || subject.subject_digest !== workDigest) return failure(request, 'BINDING_MISMATCH');
    const code = correspondenceCode(evidence, request.work_class, workDigest);
    if (code) return failure(request, code);
  }
  return { status: 'EVIDENCE_VALID', profile: request.profile, role: request.role, subject_digest: subject.subject_digest, evidence_digest: digest('evidence', evidence), specification_pin: selectedPin };
}

export function validateEvidenceArtifact(value: unknown): string {
  requireShape('evidence.schema.json', 'record', value);
  return digest('evidence', value);
}

export function validateBoundary(value: unknown, selectedPin: string): string {
  requireShape('boundary.schema.json', 'record', value);
  const record = value as Row;
  if (record.candidate_identity !== VERSION || record.specification_pin !== selectedPin) fail('VERSION_UNSUPPORTED');
  if (!sorted(record.paragraph_ids) || !sorted(record.requirement_ids)) fail('INPUT_INVALID');
  if (record.establishes === record.does_not_establish) fail('INPUT_INVALID');
  return digest('boundary', record);
}
