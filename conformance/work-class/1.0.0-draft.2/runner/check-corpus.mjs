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
const casesRoot = path.join(candidate, "cases");
const expectedContract = JSON.parse(fs.readFileSync(path.join(candidate, "review/EXPECTED-JUDGMENTS-CONTRACT.json"), "utf8"));
const judgments = new Map(expectedContract.judgments.map((row) => [row.id, row]));
const bundle = JSON.parse(fs.readFileSync(path.join(contract, "schema-bundle.json"), "utf8"));
const ajv = new Ajv2020({ strict: true, allErrors: true, allowUnionTypes: true });
const errors = [];
const caseIds = new Set();
const caseKeys = ["derivation", "expected", "id", "input", "operation", "requirements"];
const protocol = "seampoint.work-class.adapter/1.0.0-draft.2";

function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

for (const entry of bundle.schemas) {
  const bytes = fs.readFileSync(path.join(contract, entry.path));
  if (sha256(bytes) !== entry.sha256) errors.push(`${entry.path}: bundle hash mismatch`);
  ajv.addSchema(JSON.parse(bytes.toString("utf8")));
}

const protocolId = "https://schemas.seampoint.com/work-class/1.0.0-draft.2/protocol.schema.json";
const requestValidator = ajv.getSchema(`${protocolId}#/$defs/request`);
const responseValidator = ajv.getSchema(`${protocolId}#/$defs/response`);
const hostCommitValidator = ajv.getSchema("https://schemas.seampoint.com/work-class/1.0.0-draft.2/lifecycle.schema.json#/$defs/hostCommitResult");
const hostDeployValidator = ajv.getSchema("https://schemas.seampoint.com/work-class/1.0.0-draft.2/lifecycle.schema.json#/$defs/hostDeploymentResult");
const adapterOperations = new Set(["capabilities", "validate", "evaluate", "aggregate-step", "deploy", "step", "readback", "check-evidence"]);

function walkJsonFiles(directory) {
  const result = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...walkJsonFiles(full));
    else if (entry.isFile() && entry.name.endsWith(".json") && entry.name !== "index.json") result.push(full);
  }
  return result.sort();
}

function formatAjv(validate) {
  return ajv.errorsText(validate.errors, { separator: "; " });
}

for (const file of walkJsonFiles(casesRoot)) {
  let value;
  try {
    value = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    errors.push(`${path.relative(candidate, file)}: invalid case JSON: ${error.message}`);
    continue;
  }
  const label = `${path.relative(candidate, file)} (${value.id ?? "missing id"})`;
  if (JSON.stringify(Object.keys(value).sort()) !== JSON.stringify(caseKeys)) errors.push(`${label}: case must have exactly the six public case fields`);
  if (caseIds.has(value.id)) errors.push(`${label}: duplicate case id`);
  caseIds.add(value.id);
  if (path.basename(file, ".json") !== value.id) errors.push(`${label}: filename does not equal id`);
  if (typeof value.derivation !== "string" || value.derivation.length === 0) errors.push(`${label}: missing derivation`);
  if (!Array.isArray(value.requirements) || value.requirements.length === 0) errors.push(`${label}: missing requirement citations`);

  if (value.id.startsWith("D2-")) {
    const judgment = judgments.get(value.id);
    if (!judgment) errors.push(`${label}: no frozen judgment`);
    else {
      if (judgment.operation !== value.operation) errors.push(`${label}: operation differs from judgment`);
      if (JSON.stringify(judgment.normative_references) !== JSON.stringify(value.requirements)) errors.push(`${label}: citations differ from judgment`);
    }
  }

  if (adapterOperations.has(value.operation)) {
    const request = { protocol, request_id: value.id, operation: value.operation, input: value.input };
    const requestValid = requestValidator(request);
    const expectedOuterSchemaFailure =
      value.expected?.status === "REFUSED" &&
      ["ROLE_UNSUPPORTED", "SCHEMA_INVALID"].includes(value.expected?.code);
    if (!requestValid && !expectedOuterSchemaFailure) errors.push(`${label}: request is not admitted by protocol schema: ${formatAjv(requestValidator)}`);
    const response = { protocol, request_id: value.id, operation: value.operation, result: value.expected };
    if (!responseValidator(response)) errors.push(`${label}: expected result is not admitted by protocol schema: ${formatAjv(responseValidator)}`);
  } else if (value.operation === "host-harness") {
    const validator = value.expected?.status === "HOST_DEPLOY" ? hostDeployValidator : hostCommitValidator;
    if (!validator(value.expected)) errors.push(`${label}: host result is not admitted by its closed schema: ${formatAjv(validator)}`);
  }
}

const result = {
  status: errors.length === 0 ? "PASS" : "FAIL",
  cases: caseIds.size,
  judgments: judgments.size,
  exact_judgments: [...caseIds].filter((id) => judgments.has(id)).length,
  pending_judgments: [...judgments.keys()].filter((id) => !caseIds.has(id)).length,
  errors,
};
console.log(JSON.stringify(result, null, 2));
process.exit(errors.length === 0 ? 0 : 1);
