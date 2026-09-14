#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";


const require = createRequire(import.meta.url);
const Ajv2020 = require("ajv/dist/2020").default;
const here = path.dirname(fileURLToPath(import.meta.url));
const candidate = path.resolve(here, "..");
const root = path.resolve(candidate, "../../..");
const contract = path.join(root, "library/work-class-specification/1.0.0-draft.2");
const protocol = "seampoint.work-class.adapter/1.0.0-draft.2";
const metadataPath = path.join(here, "exact-vector-closure-batch-1.json");
const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8"));
const bundle = JSON.parse(fs.readFileSync(path.join(contract, "schema-bundle.json"), "utf8"));
const judgments = new Map(
  JSON.parse(fs.readFileSync(path.join(candidate, "review/EXPECTED-JUDGMENTS-CONTRACT.json"), "utf8"))
    .judgments.map((row) => [row.id, row]),
);
const ajv = new Ajv2020({ strict: true, allErrors: true, allowUnionTypes: true });
const errors = [];


function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}


for (const entry of bundle.schemas) {
  const bytes = fs.readFileSync(path.join(contract, entry.path));
  if (sha256(bytes) !== entry.sha256) errors.push(`${entry.path}: schema-bundle hash mismatch`);
  ajv.addSchema(JSON.parse(bytes.toString("utf8")));
}

const protocolId = "https://schemas.seampoint.com/work-class/1.0.0-draft.2/protocol.schema.json";
const requestValidator = ajv.getSchema(`${protocolId}#/$defs/request`);
const responseValidator = ajv.getSchema(`${protocolId}#/$defs/response`);
const caseKeys = ["derivation", "expected", "id", "input", "operation", "requirements"];

for (const row of metadata.cases) {
  const file = path.join(candidate, row.path);
  const bytes = fs.readFileSync(file);
  if (sha256(bytes) !== row.sha256) errors.push(`${row.id}: metadata case hash mismatch`);
  const value = JSON.parse(bytes.toString("utf8"));
  if (JSON.stringify(Object.keys(value).sort()) !== JSON.stringify(caseKeys)) {
    errors.push(`${row.id}: case does not have exactly the six public fields`);
  }
  if (value.id !== row.id || path.basename(file, ".json") !== row.id) errors.push(`${row.id}: identity mismatch`);
  const judgment = judgments.get(row.id);
  if (!judgment) errors.push(`${row.id}: missing judgment metadata`);
  else {
    if (value.operation !== judgment.operation) errors.push(`${row.id}: operation differs from judgment`);
    if (JSON.stringify(value.requirements) !== JSON.stringify(judgment.normative_references)) {
      errors.push(`${row.id}: requirements differ from judgment`);
    }
  }
  const request = { protocol, request_id: value.id, operation: value.operation, input: value.input };
  if (!requestValidator(request)) {
    errors.push(`${row.id}: request schema: ${ajv.errorsText(requestValidator.errors, { separator: "; " })}`);
  }
  const response = { protocol, request_id: value.id, operation: value.operation, result: value.expected };
  if (!responseValidator(response)) {
    errors.push(`${row.id}: expected schema: ${ajv.errorsText(responseValidator.errors, { separator: "; " })}`);
  }
}

console.log(JSON.stringify({ status: errors.length ? "FAIL" : "PASS", cases: metadata.cases.length, errors }, null, 2));
process.exit(errors.length ? 1 : 0);
