#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const Ajv2020 = require("ajv/dist/2020").default;
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../../../..");
const contract = process.argv[2] ? path.resolve(process.argv[2]) : path.join(root, "library/work-class-specification/1.0.0-draft.3");
const registry = JSON.parse(fs.readFileSync(path.join(contract, "schema-bundle.json"), "utf8"));
const errors = [];
const registered = new Set(registry.schemas.map((entry) => entry.uri));
const schemas = [];
let maximumWorkClassReadbackPaths = null;

function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function walk(value, pointer, file) {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => walk(entry, `${pointer}/${index}`, file));
    return;
  }
  if (!value || typeof value !== "object") return;
  if (value.type === "object" && !("additionalProperties" in value) && !("unevaluatedProperties" in value)) {
    errors.push(`${file}${pointer}: unconstrained object`);
  }
  if (typeof value.$ref === "string" && value.$ref.startsWith("https://")) {
    const uri = value.$ref.split("#", 1)[0];
    if (!registered.has(uri)) errors.push(`${file}${pointer}: undeclared schema reference ${uri}`);
  }
  for (const [key, entry] of Object.entries(value)) walk(entry, `${pointer}/${key.replaceAll("~", "~0").replaceAll("/", "~1")}`, file);
}

for (const entry of registry.schemas) {
  if (path.isAbsolute(entry.path) || entry.path.includes("..") || entry.path.includes("/")) errors.push(`${entry.path}: invalid bundle path`);
  const file = path.join(contract, entry.path);
  if (!fs.existsSync(file)) {
    errors.push(`${entry.path}: missing`);
    continue;
  }
  const bytes = fs.readFileSync(file);
  if (sha256(bytes) !== entry.sha256) errors.push(`${entry.path}: hash mismatch`);
  const schema = JSON.parse(bytes.toString("utf8"));
  if (schema.$id !== entry.uri) errors.push(`${entry.path}: registry URI does not match $id`);
  if (!["$ref", "oneOf", "anyOf", "allOf", "type"].some((key) => key in schema)) errors.push(`${entry.path}: no top-level admission constraint`);
  walk(schema, "", entry.path);
  schemas.push(schema);
}

function maximumReadbackPaths(schema, documentId, trail = new Set()) {
  if (!schema || typeof schema !== "object") return 1;
  if (typeof schema.$ref === "string") {
    const [rawDocument, rawFragment = ""] = schema.$ref.split("#", 2);
    const targetId = rawDocument || documentId;
    const key = `${targetId}#${rawFragment}`;
    if (trail.has(key)) throw new Error(`recursive schema reference ${key}`);
    const document = schemas.find((candidate) => candidate.$id === targetId);
    if (!document) throw new Error(`unresolved schema reference ${key}`);
    let target = document;
    if (rawFragment) {
      for (const token of rawFragment.replace(/^\//, "").split("/")) {
        target = target[token.replaceAll("~1", "/").replaceAll("~0", "~")];
      }
    }
    const nextTrail = new Set(trail);
    nextTrail.add(key);
    return maximumReadbackPaths(target, targetId, nextTrail);
  }
  if (Array.isArray(schema.oneOf)) return Math.max(...schema.oneOf.map((entry) => maximumReadbackPaths(entry, documentId, trail)));
  if (Array.isArray(schema.anyOf)) return Math.max(...schema.anyOf.map((entry) => maximumReadbackPaths(entry, documentId, trail)));
  if (Array.isArray(schema.allOf)) return schema.allOf.reduce((sum, entry) => sum + maximumReadbackPaths(entry, documentId, trail), 0);
  if (schema.type === "object" || schema.properties) {
    return Object.values(schema.properties || {}).reduce((sum, entry) => sum + maximumReadbackPaths(entry, documentId, trail), 0);
  }
  if (schema.type === "array") {
    if (!Number.isInteger(schema.maxItems)) throw new Error(`unbounded array in ${documentId}`);
    return Math.max(1, schema.maxItems * maximumReadbackPaths(schema.items || {}, documentId, trail));
  }
  return 1;
}

try {
  const workClassId = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/work-class.schema.json";
  const evidenceId = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/evidence.schema.json";
  const workClass = schemas.find((schema) => schema.$id === workClassId);
  const evidence = schemas.find((schema) => schema.$id === evidenceId);
  if (!workClass || !evidence) throw new Error("work-class or evidence schema missing from bundle");
  const maximumPaths = maximumReadbackPaths(workClass.$defs.definition, workClassId);
  maximumWorkClassReadbackPaths = maximumPaths;
  const mappedBound = evidence.$defs.correspondenceMapping.properties.provision_paths.maxItems;
  const unsupportedBound = evidence.$defs.correspondence.properties.unsupported_provision_paths.maxItems;
  const residueBound = evidence.$defs.correspondence.properties.residue.maxItems;
  const sourceBound = workClass.$defs.source.properties.obligations.maxItems;
  if (mappedBound < maximumPaths || unsupportedBound < maximumPaths) {
    errors.push(`correspondence provision path bound ${Math.min(mappedBound, unsupportedBound)} is below work-class readback maximum ${maximumPaths}`);
  }
  if (residueBound < maximumPaths + sourceBound) {
    errors.push(`correspondence residue bound ${residueBound} is below required maximum ${maximumPaths + sourceBound}`);
  }
} catch (error) {
  errors.push(`correspondence bound check: ${error instanceof Error ? error.message : String(error)}`);
}

try {
  const ajv = new Ajv2020({ strict: true, allErrors: true, allowUnionTypes: true });
  for (const schema of schemas) ajv.addSchema(schema);
  for (const schema of schemas) {
    if (!ajv.getSchema(schema.$id)) errors.push(`${schema.$id}: failed to compile`);
  }
} catch (error) {
  errors.push(`schema compilation: ${error instanceof Error ? error.message : String(error)}`);
}

if (errors.length) {
  console.error(JSON.stringify({ status: "FAIL", errors }, null, 2));
  process.exit(1);
}

console.log(JSON.stringify({ status: "PASS", schemas: schemas.length, open_objects: 0, undeclared_references: 0, maximum_work_class_readback_paths: maximumWorkClassReadbackPaths }, null, 2));
