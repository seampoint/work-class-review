#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../../../..");
const source = path.join(root, "library/work-class-specification/1.0.0-draft.3");
const checker = path.join(here, "check-contract-schemas.mjs");
const tempParent = process.env.WORK_CLASS_SCHEMA_CONTROL_ROOT || path.join(root, "runs");
fs.mkdirSync(tempParent, { recursive: true });
const tempRoot = fs.mkdtempSync(path.join(tempParent, "draft3-schema-control-"));
const failures = [];
const results = [];

function hash(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function updateBundle(contract, schemaName) {
  const bundlePath = path.join(contract, "schema-bundle.json");
  const bundle = JSON.parse(fs.readFileSync(bundlePath, "utf8"));
  const entry = bundle.schemas.find((candidate) => candidate.path === schemaName);
  entry.sha256 = hash(fs.readFileSync(path.join(contract, schemaName)));
  fs.writeFileSync(bundlePath, `${JSON.stringify(bundle, null, 2)}\n`);
}

function run(name, mutate, expectedText) {
  const contract = path.join(tempRoot, name);
  fs.cpSync(source, contract, { recursive: true });
  mutate(contract);
  const result = spawnSync(process.execPath, [checker, contract], { encoding: "utf8" });
  const output = `${result.stdout}${result.stderr}`;
  const detected = result.status !== 0 && output.includes(expectedText);
  results.push({ name, detected, exit_code: result.status, expected_text: expectedText });
  if (!detected) failures.push({ name, exit_code: result.status, output });
}

try {
  const baseline = spawnSync(process.execPath, [checker, source], { encoding: "utf8" });
  if (baseline.status !== 0) failures.push({ name: "baseline", output: `${baseline.stdout}${baseline.stderr}` });

  run("open-object", (contract) => {
    const file = path.join(contract, "lifecycle.schema.json");
    const schema = JSON.parse(fs.readFileSync(file, "utf8"));
    delete schema.$defs.nativeEvidence.additionalProperties;
    fs.writeFileSync(file, `${JSON.stringify(schema, null, 2)}\n`);
    updateBundle(contract, "lifecycle.schema.json");
  }, "unconstrained object");

  run("undeclared-reference", (contract) => {
    const file = path.join(contract, "lifecycle.schema.json");
    const schema = JSON.parse(fs.readFileSync(file, "utf8"));
    schema.$defs.nativeEvidence.properties.injected = { $ref: "https://invalid.example/schema.json" };
    fs.writeFileSync(file, `${JSON.stringify(schema, null, 2)}\n`);
    updateBundle(contract, "lifecycle.schema.json");
  }, "undeclared schema reference");

  run("hash-mismatch", (contract) => {
    fs.appendFileSync(path.join(contract, "lifecycle.schema.json"), " \n");
  }, "hash mismatch");

  run("identity-mismatch", (contract) => {
    const file = path.join(contract, "lifecycle.schema.json");
    const schema = JSON.parse(fs.readFileSync(file, "utf8"));
    schema.$id = "https://schemas.seampoint.com/work-class/1.0.0-draft.3/wrong.schema.json";
    fs.writeFileSync(file, `${JSON.stringify(schema, null, 2)}\n`);
    updateBundle(contract, "lifecycle.schema.json");
  }, "registry URI does not match $id");

  run("missing-schema", (contract) => {
    fs.unlinkSync(path.join(contract, "evidence.schema.json"));
  }, "missing");

  run("unconstrained-root", (contract) => {
    const file = path.join(contract, "protocol.schema.json");
    const schema = JSON.parse(fs.readFileSync(file, "utf8"));
    delete schema.oneOf;
    fs.writeFileSync(file, `${JSON.stringify(schema, null, 2)}\n`);
    updateBundle(contract, "protocol.schema.json");
  }, "no top-level admission constraint");

  run("correspondence-path-bound", (contract) => {
    const file = path.join(contract, "evidence.schema.json");
    const schema = JSON.parse(fs.readFileSync(file, "utf8"));
    schema.$defs.correspondenceMapping.properties.provision_paths.maxItems = 4096;
    fs.writeFileSync(file, `${JSON.stringify(schema, null, 2)}\n`);
    updateBundle(contract, "evidence.schema.json");
  }, "correspondence provision path bound");
} finally {
  for (const name of fs.readdirSync(tempRoot)) {
    const directory = path.join(tempRoot, name);
    for (const file of fs.readdirSync(directory)) fs.unlinkSync(path.join(directory, file));
    fs.rmdirSync(directory);
  }
  fs.rmdirSync(tempRoot);
}

if (failures.length) {
  console.error(JSON.stringify({ status: "FAIL", results, failures }, null, 2));
  process.exit(1);
}
console.log(JSON.stringify({ status: "PASS", baseline: "PASS", mutations: results }, null, 2));
