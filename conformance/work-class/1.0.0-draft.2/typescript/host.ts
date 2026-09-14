import { pathToFileURL } from 'node:url';
import { canonical, parseRestricted } from './canonical.ts';
import { PROTOCOL, requireShape } from './schema.ts';
import { same } from './values.ts';
import type { RecordValue as Row } from './values.ts';

const clone = <T>(value: T): T => structuredClone(value);

function commit(input: Row): Row {
  if (input.inject_failure) {
    const result = {
      status: 'HOST_COMMIT', disposition: 'COMMIT_FAILED', transaction_digest: input.transaction_digest,
      state_before_digest: input.authoritative_state_digest, authoritative_state_digest: input.authoritative_state_digest,
      budget_before: clone(input.authoritative_budgets), authoritative_budgets: clone(input.authoritative_budgets),
      failure_reference: input.failure_reference, dispatch_performed: false,
    };
    requireShape('lifecycle.schema.json', 'hostCommitResult', result);
    return result;
  }
  const result = {
    status: 'HOST_COMMIT', disposition: 'COMMITTED', transaction_digest: input.transaction_digest,
    state_before_digest: input.authoritative_state_digest, state_after_digest: input.calculated_state_digest,
    budget_before: clone(input.authoritative_budgets), budget_after: clone(input.calculated_budgets), dispatch_performed: false,
  };
  requireShape('lifecycle.schema.json', 'hostCommitResult', result);
  return result;
}

function install(input: Row): Row {
  const replay = same(input.request, input.authoritative_request) && same(input.calculated, input.authoritative_result);
  const result = replay ? {
    status: 'HOST_DEPLOY', disposition: 'INSTALLED', organization: input.organization, instance_id: input.instance_id,
    state_digest: input.authoritative_result.state_digest, replay: true, dispatch_performed: false,
  } : {
    status: 'HOST_DEPLOY', disposition: 'INSTANCE_OCCUPIED', organization: input.organization, instance_id: input.instance_id,
    authoritative_state_digest: input.authoritative_result.state_digest, proposed_state_digest: input.calculated.state_digest,
    replay: false, dispatch_performed: false,
  };
  requireShape('lifecycle.schema.json', 'hostDeploymentResult', result);
  return result;
}

export function hostHarness(input: unknown): Row {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) throw new Error('Invalid host harness input');
  const row = input as Row;
  if (row.kind === 'COMMIT') return commit(row);
  if (row.kind === 'INSTALL') return install(row);
  throw new Error('Unsupported host harness input');
}

async function main(): Promise<void> {
  let pending = Buffer.alloc(0);
  for await (const chunk of process.stdin) {
    pending = Buffer.concat([pending, chunk]);
    let boundary: number;
    while ((boundary = pending.indexOf(10)) >= 0) {
      const line = pending.subarray(0, boundary); pending = pending.subarray(boundary + 1);
      const request = JSON.parse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(line)) as Row;
      parseRestricted(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(line));
      if (request.protocol !== PROTOCOL || request.operation !== 'host-harness' || typeof request.request_id !== 'string') throw new Error('Invalid host harness envelope');
      const response = { protocol: PROTOCOL, request_id: request.request_id, operation: 'host-harness', result: hostHarness(request.input) };
      process.stdout.write(canonical(response) + '\n');
    }
  }
  if (pending.length) throw new Error('Transport request lacks its final line-feed');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch(error => { process.stderr.write(String(error) + '\n'); process.exitCode = 1; });
