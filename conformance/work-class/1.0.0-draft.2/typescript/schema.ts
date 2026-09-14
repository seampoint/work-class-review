import { readFileSync, lstatSync } from 'node:fs';
import Ajv from 'ajv/dist/2020.js';
import { AdmissionError, hashBytes } from './canonical.ts';

export const VERSION = 'seampoint.work-class/1.0.0-draft.2';
const directory = new URL('../../../../library/work-class-specification/1.0.0-draft.2/', import.meta.url);
const ajv = new Ajv.default({ strict: true, allowUnionTypes: true });
for (const file of ['aggregate.schema.json', 'authority.schema.json', 'reservation.schema.json', 'work-class.schema.json', 'lifecycle.schema.json', 'evidence.schema.json', 'boundary.schema.json', 'protocol.schema.json']) ajv.addSchema(JSON.parse(readFileSync(new URL(file, directory), 'utf8')));
const validators = new Map<string, ReturnType<typeof ajv.compile>>();
export function shape(file: string, name: string, value: unknown): boolean {
  const id = file + ':' + name;
  let validator = validators.get(id);
  if (!validator) {
    validator = ajv.compile({ $ref: 'https://schemas.seampoint.com/work-class/1.0.0-draft.2/' + file + '#/$defs/' + name });
    validators.set(id, validator);
  }
  return Boolean(validator(value));
}
export function requireShape(file: string, name: string, value: unknown): void {
  if (!shape(file, name, value)) throw new AdmissionError('SCHEMA_INVALID');
}

export const PROTOCOL = 'seampoint.work-class.adapter/1.0.0-draft.2';
export const LIMITS = {
  max_definitions: '64', max_operations: '256', max_collection_members: '1024',
  max_numeric_digits: '128', max_expression_depth: '64', max_expression_nodes: '4096',
};
const normativeFiles = ['AGGREGATES.md', 'AUTHORITY-CHECKS.md', 'AUTHORITY.md', 'COMPOSITION.md', 'EXTERNAL-DEPENDENCIES.md', 'LIFECYCLE.md', 'PROTOCOL.md', 'README.md', 'RESERVATION-RECORDS.md', 'RESERVATIONS.md', 'SCOPE-AND-BOUNDARY.md', 'Specification.md', 'aggregate.schema.json', 'authority.schema.json', 'boundary.schema.json', 'evidence.schema.json', 'lifecycle.schema.json', 'protocol.schema.json', 'requirements.json', 'reservation.schema.json', 'schema-bundle.json', 'work-class.schema.json'];
export function selectedCandidate(): string {
  const bytes = readFileSync(new URL('contract-manifest.json', directory));
  const manifest = JSON.parse(bytes.toString());
  if (manifest.identity !== VERSION || !Array.isArray(manifest.files) || manifest.files.length !== normativeFiles.length) throw new Error('Wrong or incomplete contract manifest');
  const paths = new Set<string>();
  for (const entry of manifest.files) {
    if (!entry || !normativeFiles.includes(entry.path) || paths.has(entry.path) || !/^[a-f0-9]{64}$/.test(entry.sha256)) throw new Error('Invalid contract manifest entry');
    paths.add(entry.path);
    const file = new URL(entry.path, directory);
    if (!lstatSync(file).isFile() || hashBytes(readFileSync(file)) !== 'sha256:' + entry.sha256) throw new Error('Bundled file differs from selected contract: ' + entry.path);
  }
  return hashBytes(bytes);
}
