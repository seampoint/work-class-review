import { AdmissionError, byteCompare, canonical, decodeArtifact, digest } from './canonical.ts';
import { instant as parseInstant } from './time.ts';
import { ordered, same, setOrder } from './values.ts';
import { compare, decimal, sum } from './math.ts';
import type { RecordValue as Row } from './values.ts';

const clone = <T>(value: T): T => structuredClone(value);
const check = (condition: unknown, code = 'DEPENDENCY_MISMATCH'): void => { if (!condition) throw new AdmissionError(code); };
const instant = (value: string): bigint => { try { return parseInstant(value); } catch (error) { if (!(error instanceof AdmissionError)) throw error; throw new AdmissionError('INPUT_INVALID'); } };
function boundedNumeric(value: string): void { check(value.replace('.', '').length <= 128, 'LIMIT_EXCEEDED'); }
export const recoverySorted = (rows: Row[]): Row[] => rows.sort((a, b) => byteCompare(canonical(a), canonical(b)));
export function recoveryFact(value: Row): string {
  const normalized = clone(value);
  for (const name of ['id', 'evidence_id', 'evidence_ref', 'record_digest', 'observed_at']) delete normalized[name];
  return digest('recovery-fact', normalized);
}
export function recoveryGeneration(evidence: Row): string {
  const normalized = clone(evidence);
  for (const name of ['id', 'provider', 'source', 'record_type', 'record_digest', 'evidence_ref', 'provider_revision', 'complete_attempt_inventory']) delete normalized[name];
  normalized.native_outcomes = [...new Map(evidence.native_outcomes.map((row: Row) => {
    const fact = clone(row); for (const name of ['id', 'evidence_id', 'evidence_ref', 'record_digest', 'observed_at']) delete fact[name];
    return [canonical(fact), fact];
  })).entries()].sort(([a], [b]) => byteCompare(a as string, b as string)).map(([, row]) => row);
  return digest('recovery-generation', normalized);
}
export function recoverySubject(event: Row): string {
  const subject = clone(event);
  if (subject.payload) { delete subject.payload.authorization; delete subject.payload.controller; }
  else delete subject.controller;
  return digest('recovery-subject', subject);
}
export function recoveryHostAdmission(configuration: Row, host: Row, evidence: Row | null, authorization: Row | null, deferAuthenticationOrder = false): void {
  check(host && ordered(host.recovery_bases.map((row: Row) => row.id)) && (deferAuthenticationOrder || setOrder(host.authenticated_records)), 'INPUT_INVALID');
  const records: Row[] = [];
  if (evidence) records.push({ kind: 'RECOVERY_EVIDENCE', record_digest: digest('recovery-evidence', evidence), provider: evidence.provider, source: evidence.source });
  if (authorization) records.push({ kind: 'RECOVERY_RETURN', record_digest: digest('recovery-return', authorization.returned), provider: authorization.returned.provider, source: authorization.returned.source });
  const expected = new Set(records.map(canonical)), actual = new Set(host.authenticated_records.map(canonical));
  check([...actual].every(row => expected.has(row as string)), 'DEPENDENCY_MISMATCH');
  check([...expected].every(row => actual.has(row)), 'EVIDENCE_UNAVAILABLE');
  for (const basis of host.recovery_bases) check(basis.provider === configuration.provider && basis.source === configuration.source, 'DEPENDENCY_MISMATCH');
}
export function recoveryAuthority(configuration: Row, host: Row, authorization: Row, event: Row, principal: string, scope: string, operation: string, at: string, excluded: string[] = []): void {
  check(authorization, 'ADMINISTRATION_NOT_ESTABLISHED');
  const { act, returned } = authorization, basis = host.recovery_bases.find((row: Row) => row.id === act.basis);
  check(basis && host.recovery_bases.length === 1, 'ADMINISTRATION_NOT_ESTABLISHED');
  const role = ['ISSUE_POLICY', 'REVOKE_POLICY'].includes(operation) ? configuration.policy_owner_role : configuration.controller_role;
  check(basis.principal === principal && basis.scope_digest === scope && basis.provider === configuration.provider && basis.source === configuration.source, 'DEPENDENCY_MISMATCH');
  check(basis.kind === 'HUMAN' && basis.role === role, 'ADMINISTRATION_NOT_ESTABLISHED');
  check(act.actor === basis.actor && act.principal === principal && act.role === role && act.kind === operation && act.subject_digest === recoverySubject(event), 'DEPENDENCY_MISMATCH');
  check(returned.act_digest === digest('recovery-act', act) && same(decodeArtifact(returned.act_bytes_base64).value, act) && returned.actor === act.actor && returned.provider === configuration.provider && returned.source === configuration.source, 'DEPENDENCY_MISMATCH');
  check(basis.at === at && act.occurred_at === at && returned.returned_at === at && act.disposition === 'ACCEPT' && !basis.revoked && basis.operations.includes(operation) && instant(basis.validity.valid_from) <= instant(at) && (basis.validity.valid_until === null || instant(at) < instant(basis.validity.valid_until)) && !excluded.includes(basis.actor), 'ADMINISTRATION_NOT_ESTABLISHED');
  if (operation === 'ESTABLISH_NO_EFFECT' && event.payload?.target.kind === 'RESERVATION') check(basis.operations.includes('RELEASE_DISPUTED_EXPOSURE'), 'ADMINISTRATION_NOT_ESTABLISHED');
}
export function recoveryPacket(evidence: Row, target: Row, request: Row, facts: Row[], priorAttempts: Row[] = []): string[] {
  check(same(evidence.target, target) && same(evidence.request, request), 'DEPENDENCY_MISMATCH');
  check(ordered(evidence.covered_evidence_digests) && ordered(evidence.superseded_evidence_digests) && ordered(evidence.attempts.map((row: Row) => row.id)), 'INPUT_INVALID');
  for (const attempt of evidence.attempts) {
    boundedNumeric(attempt.maximum_executions);
    check(BigInt(attempt.maximum_executions) > 0n && ordered(attempt.effect_ids) && BigInt(attempt.effect_ids.length) <= BigInt(attempt.maximum_executions) && (!attempt.no_effect || attempt.effect_ids.length === 0), 'INPUT_INVALID');
    check(attempt.request_digest === digest('reservation-native-request', request), 'DEPENDENCY_MISMATCH');
  }
  check(new Set(evidence.attempts.map((row: Row) => row.attempt_digest)).size === evidence.attempts.length && new Set(evidence.attempts.flatMap((row: Row) => row.effect_ids)).size === evidence.attempts.flatMap((row: Row) => row.effect_ids).length, 'INPUT_INVALID');
  const reasons: string[] = [];
  boundedNumeric(evidence.provider_revision);
  const factSet = [...new Set([...facts, ...evidence.native_outcomes].map(recoveryFact))].sort(byteCompare);
  check(same(factSet, evidence.covered_evidence_digests) && !priorAttempts.some(row => !evidence.attempts.some((attempt: Row) => attempt.id === row.id && attempt.attempt_digest === row.attempt_digest && attempt.executor === row.executor && attempt.connector === row.connector && attempt.request_digest === row.request_digest)), 'DEPENDENCY_MISMATCH');
  check(!priorAttempts.some(row => row.effect_ids.some((effect: string) => evidence.attempts.some((attempt: Row) => attempt.id !== row.id && attempt.effect_ids.includes(effect)))), 'DEPENDENCY_MISMATCH');
  if (!evidence.complete_attempt_inventory || !evidence.attempts.length) reasons.push('RECOVERY_EVIDENCE_INCOMPLETE');
  if (evidence.superseded_evidence_digests.some((value: string) => !evidence.covered_evidence_digests.includes(value))) reasons.push('RECOVERY_CONFLICT_UNRESOLVED');
  return reasons;
}
export function recoveryDisposition(principal: string, registryDigest: string | null, reservation: Row | null, target: Row, payload: Row, event: Row, at: string, result = payload.requested_result): Row {
  const incident = reservation ? { principal, registry_digest: registryDigest, reservation: reservation.id, occurrence: reservation.occurrence_key, error_class: 'DUPLICATE_SEND_UNCERTAINTY' } : { principal, target };
  const incidentDigest = digest('recovery-incident', incident), generation = recoveryGeneration(payload.evidence);
  const body = { incident_digest: incidentDigest, generation_digest: generation, result, policy_digest: payload.policy_digest, controller: payload.controller, supersedes: payload.supersedes };
  return { id: digest('recovery-disposition', body), incident_digest: incidentDigest, generation_digest: generation, acceptance_basis_digest: result === 'ACCEPT_UNRESOLVED' ? digest('recovery-acceptance-basis', { incident_digest: incidentDigest, generation_digest: generation, policy_digest: payload.policy_digest }) : null, target: clone(target), result, evidence: clone(payload.evidence), policy_digest: payload.policy_digest, controller: clone(payload.controller), supersedes: payload.supersedes, event_digest: digest(event.kind === 'DISPOSE' && event.event_id ? 'runtime-event' : 'reservation-event', event), accepted_at: at, source_event: clone(event) };
}
export function recoveryCoverage(disposition: Row, facts: Row[]): boolean {
  return facts.every(row => disposition.evidence.covered_evidence_digests.includes(recoveryFact(row)) || disposition.evidence.native_outcomes.some((native: Row) => recoveryFact(native) === recoveryFact(row)));
}
export function recoveryPolicyCurrent(core: Row, disposition: Row, at: string): boolean {
  if (disposition.result !== 'ACCEPT_UNRESOLVED') return disposition.result !== 'LEAVE_UNRESOLVED';
  const row = core.recovery?.policies.find((record: Row) => record.policy_digest === disposition.policy_digest);
  return !!row && !row.revoked && !core.recovery.policies.some((record: Row) => record.policy.family === row.policy.family && BigInt(record.policy.version) > BigInt(row.policy.version)) && instant(row.policy.validity.valid_from) <= instant(at) && (row.policy.validity.valid_until === null || instant(at) < instant(row.policy.validity.valid_until));
}
export function recoveryPolicyTransition(core: Row, event: Row, host: Row, deferAuthenticationOrder = false): void {
  const configuration = core.configuration.recovery, payload = event.payload, policy = payload.policy, registry = digest('reservation-registry', core.configuration);
  check(configuration && core.recovery && event.administration === null && event.clock.status === 'AVAILABLE', 'DEPENDENCY_MISMATCH');
  check(policy && payload.family === policy.family && configuration.policy_families.includes(policy.family) && policy.scope.principal === core.configuration.principal && policy.scope.registry_digest === registry && policy.scope.unit === 'USD' && policy.scope.window_seconds === '86400' && configuration.exception_profiles.includes(policy.scope.profile), 'DEPENDENCY_MISMATCH');
  for (const name of ['budget_anchors', 'work_classes', 'executors', 'connectors']) check(ordered(policy.scope[name]) && policy.scope[name].length > 0, 'INPUT_INVALID');
  for (const value of [policy.version, policy.per_incident_limit, policy.cumulative_limit]) boundedNumeric(value);
  check(BigInt(policy.version) > 0n && compare(decimal(policy.per_incident_limit), decimal('0')) >= 0 && compare(decimal(policy.cumulative_limit), decimal('0')) >= 0 && policy.validity.valid_until !== null && instant(policy.validity.valid_from) < instant(policy.validity.valid_until), 'INPUT_INVALID');
  for (const anchor of policy.scope.budget_anchors) check(core.budgets.some((row: Row) => row.definition.anchor === anchor), 'DEPENDENCY_MISMATCH');
  recoveryHostAdmission(configuration, host, null, payload.authorization, deferAuthenticationOrder);
  recoveryAuthority(configuration, host, payload.authorization, event, core.configuration.principal, digest('recovery-policy-scope', policy.scope), payload.action === 'ISSUE' ? 'ISSUE_POLICY' : 'REVOKE_POLICY', event.clock.instant);
  const history = core.recovery.policies.filter((row: Row) => row.policy.family === payload.family), current = history.reduce((latest: Row | null, row: Row) => !latest || BigInt(row.policy.version) > BigInt(latest.policy.version) ? row : latest, null);
  check(payload.policy_digest === digest('recovery-policy', policy), 'DEPENDENCY_MISMATCH');
  if (payload.action === 'ISSUE') {
    check(payload.supersedes === (current?.policy_digest ?? null) && (!current || BigInt(policy.version) > BigInt(current.policy.version)), 'REVISION_CONFLICT');
    check(!current || same(current.policy.scope, policy.scope), 'UNSUPPORTED_RELATION');
    check(!core.recovery.policies.some((row: Row) => row.policy.id === policy.id), 'DEPENDENCY_MISMATCH');
    core.recovery.policies.push({ policy: clone(policy), policy_digest: digest('recovery-policy', policy), revoked: false, event_digest: digest('reservation-event', event), authorization: clone(payload.authorization) });
    recoverySorted(core.recovery.policies);
  } else {
    check(current && !current.revoked && payload.policy_digest === current.policy_digest && payload.supersedes === null && same(policy, current.policy), 'REVISION_CONFLICT');
    current.revoked = true;
  }
}
export function recoveryAllowanceRows(disposition: Row, policy: Row, reservation: Row, amounts: Map<string, string>, at: string): Row[] {
  const result: Row[] = [];
  for (const [anchor, amount] of amounts) {
    const actors: [string, string][] = [['BUDGET', anchor], ...[...new Set(disposition.evidence.attempts.map((row: Row) => row.executor))].map(actor => ['EXECUTOR', actor] as [string, string]), ...[...new Set(disposition.evidence.attempts.map((row: Row) => row.connector))].map(actor => ['CONNECTOR', actor] as [string, string])];
    for (const [actor_kind, actor] of actors) result.push({ acceptance_basis_digest: disposition.acceptance_basis_digest, policy_family: policy.family, budget: anchor, actor_kind, actor, amount, accepted_at: at });
  }
  return recoverySorted(result);
}
export function recoveryAllowanceExceeded(core: Row, policy: Row, incoming: Row[], at: string): boolean {
  const now = instant(at), lower = now - 86_400_000_000_000n;
  return incoming.some(row => compare(decimal(sum([row.amount, ...core.recovery.allowances.filter((prior: Row) => prior.policy_family === row.policy_family && prior.budget === row.budget && prior.actor_kind === row.actor_kind && prior.actor === row.actor && lower < instant(prior.accepted_at) && instant(prior.accepted_at) <= now).map((prior: Row) => prior.amount)])), decimal(policy.cumulative_limit)) > 0);
}
