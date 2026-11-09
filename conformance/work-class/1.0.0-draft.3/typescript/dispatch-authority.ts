import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { deriveSourceQueries } from './authority.ts';
import { instant, instantText } from './time.ts';
import { same } from './values.ts';
import { admitHoldingsDispatch, holdingsFence } from './holdings.ts';
import { flowFence } from './information-flow.ts';
import { effectiveUntil } from './human-decisions.ts';
import type { RecordValue as Row } from './values.ts';

export function immutableAuthority(input: Row): Row {
  const body = structuredClone(input);
  for (const key of ['clock', 'observations', 'evaluation_point', 'holdings_bases']) delete body[key];
  if (body.flow_bases !== undefined) body.flow_bases = body.flow_bases.map((row: Row) => ({ requirement_id: row.requirement_id, configuration: row.configuration, released_restrictions: row.released_restrictions }));
  if (body.decision_bases !== undefined) for (const row of body.decision_bases) row.evidence.authority_input = immutableAuthority(row.evidence.authority_input);
  return body;
}

export function authorizationHead(state: Row, permitId: string): Row | null {
  const rows = (state.authorizations ?? []).filter((row: Row) => row.permit_digest === permitId);
  if (!rows.length) return null;
  const ids = new Map<string, Row>(rows.map((row: Row) => [row.authorization_digest, row]));
  const successors = new Map<string, Row>();
  for (const row of rows) {
    const prior = row.supersedes_authorization_digest;
    if (prior === null) continue;
    if (!ids.has(prior) || prior === row.authorization_digest || successors.has(prior)) throw new AdmissionError('STATE_INVALID');
    successors.set(prior, row);
  }
  const roots = rows.filter((row: Row) => row.supersedes_authorization_digest === null);
  if (roots.length !== 1) throw new AdmissionError('STATE_INVALID');
  const visited = new Set<string>(); let head = roots[0];
  while (head) {
    if (visited.has(head.authorization_digest)) throw new AdmissionError('STATE_INVALID');
    visited.add(head.authorization_digest);
    const next = successors.get(head.authorization_digest);
    if (!next) break;
    head = next;
  }
  if (visited.size !== rows.length) throw new AdmissionError('STATE_INVALID');
  return head;
}

export function dispatchPermissionConsumed(state: Row, permitId: string): boolean {
  return state.dispatches.some((row: Row) => row.permit_digest === permitId && (row.attempt.status !== 'NOT_SENT' || row.acknowledgement.status === 'ACCEPTED'))
    || state.outcomes.some((row: Row) => row.permit_digest === permitId)
    || (state.completion_checks ?? []).some((row: Row) => row.permit_digest === permitId);
}

export function latestAuthorizationEvaluation(state: Row, permitId: string): Row | null {
  const sequence = (row: Row): bigint => BigInt(state.receipts.find((receipt: Row) => receipt.event_id === row.event_id)?.sequence ?? '0');
  return (state.authorization_evaluations ?? []).filter((row: Row) => row.permit_digest === permitId).sort((a: Row, b: Row) => sequence(a) < sequence(b) ? -1 : 1).at(-1) ?? null;
}

export function authorizationExpiry(permit: Row, gate: Row, authority: Row): string {
  let expiry: string;
  try { expiry = instantText(instant(authority.clock.instant) + BigInt(gate.authorization_seconds) * 1_000_000_000n); }
  catch { throw new AdmissionError('LIMIT_EXCEEDED'); }
  for (const candidate of [permit.expires_at, authority.envelope.temporal_validity.valid_until]) if (candidate !== null && instant(candidate) < instant(expiry)) expiry = candidate;
  if (gate.kind === 'SOURCE_REQUIREMENTS') {
    for (const validity of gate.validity_requirements) {
      const query = deriveSourceQueries(authority).find((row: Row) => row.requirement_id === validity.requirement_id);
      const observation = authority.observations.find((row: Row) => row.query_digest === digest('authority-query', query));
      const end = observation?.fields.find((row: Row) => row.name === validity.not_after_field)?.value.value;
      if (!end) throw new AdmissionError('BINDING_MISMATCH');
      if (instant(end) < instant(expiry)) expiry = end;
    }
    for (const row of authority.decision_bases ?? []) { const end = effectiveUntil(row.evidence.authority_input); if (instant(end) < instant(expiry)) expiry = end; }
  }
  for (const row of holdingsFence(authority)) if (row.valid_until !== null && instant(row.valid_until) < instant(expiry)) expiry = row.valid_until;
  if (flowFence(authority).length) {
    const bounded = structuredClone(authority); bounded.envelope.temporal_validity.valid_until = expiry;
    const end = effectiveUntil(bounded); if (instant(end) < instant(expiry)) expiry = end;
    const executor = authority.occupancies.find((row: Row) => row.id === authority.proposal.executor.occupancy);
    for (const record of [executor, ...authority.credentials]) if (record?.validity.valid_until !== null && record?.validity.valid_until !== undefined && instant(record.validity.valid_until) < instant(expiry)) expiry = record.validity.valid_until;
  }
  return expiry;
}

export function deriveAuthorizationFence(event: Row, gate: Row, result: Row, expiresAt: string): Row {
  const authority = event.authority_input;
  admitHoldingsDispatch(authority, { dispatch_gate: gate });
  const holdings = holdingsFence(authority), flows = flowFence(authority);
  if (flows.length && gate.kind !== 'SOURCE_REQUIREMENTS') throw new AdmissionError('UNSUPPORTED_RELATION');
  if (gate.kind === 'SOURCE_REQUIREMENTS' && gate.requirements.length + holdings.length + flows.length > 64) throw new AdmissionError('LIMIT_EXCEEDED');
  const required = new Set<string>(gate.kind === 'SOURCE_REQUIREMENTS' ? gate.requirements : [gate.approval_requirement, gate.withdrawal_requirement, ...gate.policy_withdrawal_requirements]);
  const sources = deriveSourceQueries(authority).filter(query => required.has(query.requirement_id)).map(query => {
    const queryDigest = digest('authority-query', query);
    const rows = [...new Map<string, Row>(authority.observations.filter((row: Row) => row.query_digest === queryDigest).map((row: Row) => [canonical(row), row])).values()];
    if (rows.length !== 1) throw new AdmissionError('BINDING_MISMATCH');
    const observation = rows[0];
    return { requirement_id: query.requirement_id, provider: query.provider, source: query.source, expected_status: query.expected_status, record_id: observation.status === 'AVAILABLE' ? observation.provider_record_id : null, provider_revision: observation.revision, query_digest: queryDigest, observation_digest: digest('authority-observation', observation) };
  }).sort((a, b) => byteCompare(a.requirement_id, b.requirement_id));
  if (sources.length !== required.size) throw new AdmissionError('BINDING_MISMATCH');
  const approval = sources.find(row => row.requirement_id === gate.approval_requirement)!;
  const grant = authority.acts.find((row: Row) => row.kind === 'GRANT');
  const checkedAt = authority.clock.instant;
  const scope = { instance_id: event.instance_id, occurrence_id: event.permit.occurrence.occurrence_id, permit_digest: event.permit.permit_id, native_request: event.native_request, connector: event.connector, dispatch_intent_id: event.dispatch_intent_id, checked_at: checkedAt, expires_at: expiresAt, authority_result_digest: digest('authority-result', result), sources, ...(holdings.length ? { holdings } : {}), ...(flows.length ? { flows } : {}) };
  if (gate.kind === 'SOURCE_REQUIREMENTS') {
    const coordinator = sources.find(row => row.requirement_id === gate.coordinator_requirement);
    if (!coordinator || coordinator.expected_status !== 'AVAILABLE') throw new AdmissionError('BINDING_MISMATCH');
    return { kind: 'SOURCE_REQUIREMENTS', provider: gate.fence_provider, source: gate.fence_source, provider_revision: coordinator.provider_revision, scope_digest: digest('dispatch-authorization-scope', scope), checked_at: checkedAt, status: 'EFFECTIVE', sources, ...(holdings.length ? { holdings } : {}), ...(flows.length ? { flows } : {}) };
  }
  return { provider: gate.fence_provider, source: gate.fence_source, approval_id: approval.record_id, scope_digest: digest('dispatch-authorization-scope', scope), approver_role: grant.role, signed_at: grant.occurred_at, provider_revision: approval.provider_revision, checked_at: checkedAt, status: 'EFFECTIVE', sources, ...(holdings.length ? { holdings } : {}), ...(flows.length ? { flows } : {}) };
}

export function authorizationAttemptPermitted(state: Row, permit: Row, digestValue: string | undefined, nativeRequest: Row, connector: Row, at: string, sequence?: bigint): boolean {
  const rows = (state.authorizations ?? []).filter((row: Row) => row.permit_digest === permit.permit_id && row.dispatch_intent_id !== undefined && instant(row.authorization_fence.checked_at) <= instant(at) && (sequence === undefined || BigInt(state.receipts.find((receipt: Row) => receipt.event_id === row.event_id)?.sequence ?? '0') < sequence));
  const priorState = { authorizations: rows };
  const head = authorizationHead(priorState, permit.permit_id);
  if (!head || head.authorization_digest !== digestValue || !same(head.native_request, nativeRequest) || !same(head.connector, connector) || instant(at) >= instant(head.expires_at)) return false;
  const authorizedSequence = BigInt(state.receipts.find((receipt: Row) => receipt.event_id === head.event_id)?.sequence ?? '0');
  if ((state.authorization_evaluations ?? []).some((row: Row) => {
    const evaluatedSequence = BigInt(state.receipts.find((receipt: Row) => receipt.event_id === row.event_id)?.sequence ?? '0');
    return row.permit_digest === permit.permit_id && evaluatedSequence > authorizedSequence && (sequence === undefined || evaluatedSequence < sequence) && row.disposition === 'WITHHELD' && row.authority_input.clock.status === 'AVAILABLE' && instant(row.authority_input.clock.instant) <= instant(at);
  })) return false;
  return !state.dispatches.some((row: Row) => row.authorization_digest === digestValue && (sequence === undefined || BigInt(state.receipts.find((receipt: Row) => receipt.event_id === row.event_id)?.sequence ?? '0') < sequence));
}
