import { AdmissionError, byteCompare, canonical, decodeArtifact, digest } from './canonical.ts';
import { requireShape, VERSION } from './schema.ts';
import { instant } from './time.ts';
import { ordered, same, setOrder } from './values.ts';
import type { RecordValue as Row } from './values.ts';
import { selectedAuthorityAct } from './human-decisions.ts';

const clone = <T>(value: T): T => structuredClone(value);
function check(value: unknown, code: string): asserts value { if (!value) throw new AdmissionError(code); }
function second(value: string): bigint {
  try { check(!value.includes('.'), 'CLOCK_INVALID'); return instant(value); }
  catch (error) { if (error instanceof AdmissionError) throw new AdmissionError('CLOCK_INVALID'); throw error; }
}
export function activeHolding(grant: Row, at: string): boolean {
  const now = second(at);
  return second(grant.valid_from) <= now && (grant.valid_until === null || now < second(grant.valid_until)) && (grant.revoked_at === null || now < second(grant.revoked_at));
}
export function admitHoldingsConfiguration(configuration: Row, pin: string): void {
  requireShape('holdings.schema.json', 'configuration', configuration);
  check(configuration.specification_pin === pin, 'VERSION_UNSUPPORTED');
  check(ordered(configuration.permissions) && setOrder(configuration.conflicts), 'DEFINITION_INVALID');
  for (const pair of configuration.conflicts) check(byteCompare(pair.left, pair.right) < 0 && configuration.permissions.includes(pair.left) && configuration.permissions.includes(pair.right), 'DEFINITION_INVALID');
}
function conflict(configuration: Row, left: string, right: string): boolean {
  return configuration.conflicts.some((pair: Row) => pair.left === left && pair.right === right || pair.left === right && pair.right === left);
}
function inventory(configuration: Row, grants: Row[], at: string): void {
  check(ordered(grants.map(row => row.id)), 'STATE_INVALID');
  const pairs = new Set<string>();
  for (const grant of grants) {
    check(configuration.permissions.includes(grant.permission), 'STATE_INVALID');
    second(grant.valid_from); if (grant.valid_until !== null) check(second(grant.valid_from) < second(grant.valid_until), 'STATE_INVALID');
    if (grant.revoked_at !== null) second(grant.revoked_at);
    if (!activeHolding(grant, at)) continue;
    const key = canonical([grant.actor, grant.permission]); check(!pairs.has(key), 'STATE_INVALID'); pairs.add(key);
    check(!grants.some(other => other.id !== grant.id && other.actor === grant.actor && activeHolding(other, at) && conflict(configuration, grant.permission, other.permission)), 'STATE_INVALID');
  }
}
function administration(configuration: Row, event: Row, host: Row): void {
  check(event.administration, 'ADMINISTRATION_NOT_ESTABLISHED');
  const { basis, act, return: returned } = event.administration, configurationDigest = digest('holdings-configuration', configuration);
  const projection = clone(event); delete projection.administration;
  const subject = digest('holdings-administration-subject', { configuration_digest: configurationDigest, event: projection });
  check(host.configuration_digest === configurationDigest, 'DEPENDENCY_MISMATCH');
  check(basis.configuration_digest === configurationDigest && basis.principal === configuration.principal && basis.provider === configuration.provider && basis.source === configuration.source, 'DEPENDENCY_MISMATCH');
  check(act.basis_id === basis.id && act.actor === basis.actor && act.principal === basis.principal && act.role === basis.role && act.kind === event.kind && act.subject_digest === subject && act.occurred_at === event.clock.instant && basis.observed_at === event.clock.instant, 'DEPENDENCY_MISMATCH');
  check(returned, 'EVIDENCE_UNAVAILABLE');
  let decoded: unknown;
  try { decoded = decodeArtifact(returned.act_bytes_base64).value; }
  catch (error) { if (!(error instanceof AdmissionError)) throw error; throw new AdmissionError(error.code === 'NONCANONICAL' ? 'ARTIFACT_NONCANONICAL' : 'ARTIFACT_ENCODING_INVALID'); }
  check(returned.actor === act.actor && returned.provider === configuration.provider && returned.source === configuration.source && returned.channel === configuration.protected_channel && returned.observed_at === event.clock.instant && returned.act_digest === digest('holdings-administration-act', act) && same(decoded, act), 'DEPENDENCY_MISMATCH');
  check(setOrder(host.authenticated_records), 'DEPENDENCY_MISMATCH');
  const expected = [
    { kind: 'ADMIN_BASIS', record_digest: digest('holdings-administration-basis', basis), provider: configuration.provider, source: configuration.source, channel: null },
    { kind: 'ADMIN_RETURN', record_digest: digest('holdings-administration-return', returned), provider: configuration.provider, source: configuration.source, channel: configuration.protected_channel },
  ];
  check(host.authenticated_records.every((row: Row) => expected.some(value => same(value, row))), 'DEPENDENCY_MISMATCH');
  check(expected.every(value => host.authenticated_records.some((row: Row) => same(value, row))), 'EVIDENCE_UNAVAILABLE');
  const now = second(event.clock.instant), from = second(basis.valid_from);
  const until = basis.valid_until === null ? null : second(basis.valid_until), revoked = basis.revoked_at === null ? null : second(basis.revoked_at);
  second(basis.observed_at); second(act.occurred_at); second(returned.observed_at);
  check(ordered(basis.allowed_operations) && basis.role === configuration.administration_role && basis.actor_kind === 'HUMAN' && basis.allowed_operations.includes(event.kind) && from <= now && (until === null || now < until) && (revoked === null || now < revoked) && act.status === 'ACCEPTED', 'ADMINISTRATION_NOT_ESTABLISHED');
}
function transition(configuration: Row, state: Row | null, event: Row, host: Row): Row {
  const configurationDigest = digest('holdings-configuration', configuration), beforeDigest = state === null ? null : digest('holdings-state', state);
  check(event.expected_revision === (state?.core.revision ?? '0') && event.expected_state_digest === beforeDigest, 'REVISION_CONFLICT');
  check(event.clock.status === 'AVAILABLE' && event.clock.source === configuration.clock_source, 'CLOCK_INVALID');
  const now = second(event.clock.instant);
  if (state !== null) check(now >= second(state.core.last_clock), 'CLOCK_INVALID');
  administration(configuration, event, host);
  check((state?.records.length ?? 0) < 64, 'LIMIT_EXCEEDED');
  let grants = clone(state?.core.grants ?? []) as Row[], decision: string, reasons: string[] = [];
  if (event.kind === 'INITIALIZE') {
    check(state === null, 'DEFINITION_CONFLICT');
    check(host.seed_inventory, 'EVIDENCE_UNAVAILABLE');
    check(host.seed_inventory.inventory_digest === digest('holdings-seed-inventory', event.payload.grants), 'DEPENDENCY_MISMATCH');
    grants = event.payload.grants.map((grant: Row) => ({ ...clone(grant), revoked_at: null }));
    inventory(configuration, grants, event.clock.instant);
    check(grants.every(grant => activeHolding(grant, event.clock.instant)), 'STATE_INVALID'); decision = 'INITIALIZED';
  } else {
    check(state !== null, 'STATE_INVALID');
    const target = event.payload;
    check(configuration.permissions.includes(target.permission), 'DEPENDENCY_MISMATCH');
    if (event.kind === 'GRANT') {
      check(!grants.some(grant => grant.id === target.grant_id), 'DEPENDENCY_MISMATCH');
      if (target.valid_until !== null) check(now < second(target.valid_until), 'CLOCK_INVALID');
      const active = grants.filter(grant => grant.actor === target.actor && activeHolding(grant, event.clock.instant));
      if (active.some(grant => grant.permission === target.permission)) { decision = 'UNCHANGED'; reasons = ['ALREADY_HELD']; }
      else if (active.some(grant => conflict(configuration, grant.permission, target.permission))) { decision = 'WITHHELD'; reasons = ['CONFLICTING_HOLDING']; }
      else { check(grants.length < 256, 'LIMIT_EXCEEDED'); grants.push({ id: target.grant_id, actor: target.actor, permission: target.permission, valid_from: event.clock.instant, valid_until: target.valid_until, revoked_at: null }); decision = 'GRANTED'; }
    } else {
      const grant = grants.find(row => row.id === target.grant_id);
      check(grant && grant.actor === target.actor && grant.permission === target.permission, 'DEPENDENCY_MISMATCH');
      if (!activeHolding(grant, event.clock.instant)) { decision = 'UNCHANGED'; reasons = ['NOT_ACTIVE']; }
      else { grant.revoked_at = event.clock.instant; decision = 'REVOKED'; }
    }
  }
  grants.sort((a, b) => byteCompare(a.id, b.id));
  const core = { configuration_digest: configurationDigest, revision: (BigInt(state?.core.revision ?? '0') + 1n).toString(), last_clock: event.clock.instant, grants };
  const eventDigest = digest('holdings-event', { event, host_evidence: host });
  const receipt = { schema: VERSION + '/holdings-receipt', event_id: event.id, event_digest: eventDigest, state_before_digest: beforeDigest, revision: core.revision, core_after_digest: digest('holdings-core', core), decision, reasons, protected_channel: configuration.protected_channel };
  const receiptDigest = digest('holdings-receipt', receipt);
  const next = { schema: VERSION + '/holdings-state', specification_pin: configuration.specification_pin, core, records: [...(state?.records ?? []), { event: clone(event), host_evidence: clone(host), event_digest: eventDigest, receipt, receipt_digest: receiptDigest }] };
  return { status: 'TRANSITION', receipt, receipt_digest: receiptDigest, state: next, state_digest: digest('holdings-state', next), replay: false };
}
export function admitHoldingsState(configuration: Row, state: Row, suppliedDigest: string, pin: string): void {
  requireShape('holdings.schema.json', 'state', state);
  check(state.specification_pin === pin, 'VERSION_UNSUPPORTED');
  check(digest('holdings-state', state) === suppliedDigest, 'DIGEST_MISMATCH');
  check(state.core.configuration_digest === digest('holdings-configuration', configuration), 'DEPENDENCY_MISMATCH');
  let rebuilt: Row | null = null;
  try {
    const ids = new Set<string>();
    for (const record of state.records) {
      check(!ids.has(record.event.id), 'STATE_INVALID'); ids.add(record.event.id);
      const result = transition(configuration, rebuilt, record.event, record.host_evidence);
      check(same(result.state.records.at(-1), record), 'STATE_INVALID'); rebuilt = result.state;
    }
    check(same(rebuilt, state), 'STATE_INVALID');
  } catch (error) { if (error instanceof AdmissionError) throw new AdmissionError('STATE_INVALID'); throw error; }
}
export function holdingsStep(input: unknown, pin: string): Row {
  try { requireShape('holdings.schema.json', 'input', input); }
  catch (error) { if (error instanceof AdmissionError) return { status: 'REFUSED', code: error.code, path: '' }; throw error; }
  const request = input as Row;
  try {
    check(Buffer.byteLength(canonical(request)) <= 16777216, 'LIMIT_EXCEEDED');
    check(request.specification_pin === pin, 'VERSION_UNSUPPORTED'); admitHoldingsConfiguration(request.configuration, pin);
    check((request.state === null) === (request.state_digest === null), 'STATE_INVALID');
    if (request.state !== null) admitHoldingsState(request.configuration, request.state, request.state_digest, pin);
    const previous = request.state?.records.find((record: Row) => record.event.id === request.event.id);
    if (previous) {
      check(same(previous.event, request.event) && same(previous.host_evidence, request.host_evidence), 'REPLAY_CONFLICT');
      return { status: 'TRANSITION', receipt: clone(previous.receipt), receipt_digest: previous.receipt_digest, state: clone(request.state), state_digest: request.state_digest, replay: true };
    }
    return transition(request.configuration, request.state, request.event, request.host_evidence);
  } catch (error) { if (error instanceof AdmissionError) return { status: 'REFUSED', code: error.code, path: '', state: request.state, state_digest: request.state_digest }; throw error; }
}

export function holdingsRequirements(input: Row): Row[] { return (input.envelope.holdings_requirements ?? []).filter((row: Row) => row.step === input.proposal.step); }
export function admitHoldingsDeclarations(input: Row, check: (value: unknown, code: string) => void): void {
  for (const requirement of input.envelope.holdings_requirements ?? []) {
    check(input.work_class.steps.some((step: Row) => step.id === requirement.step), 'REFERENCE_INVALID');
    check(requirement.actor !== 'GATE_ACTOR' || input.envelope.gate.kind !== 'NONE', 'UNSUPPORTED_RELATION');
  }
}
export function admitHoldingsBases(input: Row, pin: string, record: (value: unknown, code: string) => void): void {
  if (input.envelope.holdings_requirements !== undefined || input.holdings_bases !== undefined) record(Buffer.byteLength(canonical(input)) <= 1048576, 'LIMIT_EXCEEDED');
  for (const basis of input.holdings_bases ?? []) {
    const configuration = basis.configuration, state = basis.state;
    try { second(basis.selection.at); } catch (error) { if (!(error instanceof AdmissionError)) throw error; record(false, error.code); }
    record(configuration.specification_pin === pin && state.specification_pin === pin, 'VERSION_UNSUPPORTED');
    record(state.core.configuration_digest === digest('holdings-configuration', configuration), 'DEPENDENCY_MISMATCH');
    record(digest('holdings-state', state) === basis.state_digest, 'DIGEST_MISMATCH');
    try { admitHoldingsConfiguration(configuration, pin); }
    catch (error) { if (!(error instanceof AdmissionError)) throw error; record(false, error.code); }
    if (configuration.specification_pin === pin && state.specification_pin === pin && state.core.configuration_digest === digest('holdings-configuration', configuration) && digest('holdings-state', state) === basis.state_digest) {
      try { admitHoldingsState(configuration, state, basis.state_digest, pin); }
      catch (error) { if (!(error instanceof AdmissionError)) throw error; record(false, error.code); }
    }
  }
}
export function bindHoldingsBases(input: Row, check: (value: unknown, code: string) => void): void {
  const requirements = holdingsRequirements(input), required = new Set(requirements.map(row => row.configuration_digest)), bases = input.holdings_bases ?? [];
  const actual = bases.map((basis: Row) => digest('holdings-configuration', basis.configuration));
  check(new Set(actual).size === actual.length && actual.every((id: string) => required.has(id)), 'BINDING_MISMATCH');
  for (const basis of bases) {
    const config = basis.configuration, selection = basis.selection, id = digest('holdings-configuration', config);
    check(config.principal === input.envelope.principal && config.clock_source === input.clock.source && requirements.filter(row => row.configuration_digest === id).every(row => config.permissions.includes(row.permission)), 'DEPENDENCY_MISMATCH');
    check(selection.configuration_digest === id && selection.state_digest === basis.state_digest && selection.revision === basis.state.core.revision && selection.provider === config.provider && selection.source === config.source && selection.channel === config.protected_channel, 'DEPENDENCY_MISMATCH');
  }
}
export function holdingsActor(input: Row, requirement: Row): string | undefined {
  if (requirement.actor === 'EXECUTOR') return input.proposal.executor.actor;
  const gate = input.envelope.gate, kind = gate.kind === 'DECIDE' ? 'INSTANCE_DECISION' : gate.kind === 'VERIFY' ? 'VERIFY' : null;
  if (kind === null) return undefined;
  const acts = selectedAuthorityAct(input, kind).filter(row => row.act.role === gate.role);
  return acts.length === 1 ? acts[0].act.actor : undefined;
}
export function holdingsChecks(input: Row): Row[] {
  return holdingsRequirements(input).map(requirement => {
    const actor = holdingsActor(input, requirement), at = input.clock.instant;
    const basis = (input.holdings_bases ?? []).find((row: Row) => digest('holdings-configuration', row.configuration) === requirement.configuration_digest);
    let reason: string | undefined, grant: Row | undefined;
    if (!basis || basis.selection.status !== 'AVAILABLE') reason = 'HOLDINGS_UNAVAILABLE';
    else if (basis.selection.at !== at || second(at) < second(basis.state.core.last_clock)) reason = 'HOLDINGS_STALE';
    else if (basis.state.records.length >= 64) reason = 'HOLDINGS_CAPACITY_EXHAUSTED';
    else { const grants = basis.state.core.grants.filter((row: Row) => row.actor === actor && row.permission === requirement.permission && activeHolding(row, at)); if (grants.length !== 1) reason = 'CURRENT_HOLDING_REQUIRED'; else grant = grants[0]; }
    return { requirement, actor, at, basis, grant, reason, subject_digest: digest('holdings-query', { requirement, actor, at }) };
  });
}
export function holdingsFence(input: Row): Row[] {
  return holdingsChecks(input).map(row => {
    check(!row.reason && row.grant, 'BINDING_MISMATCH');
    return { requirement_id: row.requirement.id, configuration_digest: row.requirement.configuration_digest, state_digest: row.basis.state_digest, revision: row.basis.state.core.revision, actor: row.actor, permission: row.requirement.permission, grant_id: row.grant.id, valid_until: row.grant.valid_until };
  }).sort((a, b) => byteCompare(a.requirement_id, b.requirement_id));
}
export function admitHoldingsDispatch(input: Row, step: Row): void {
  const requirements = holdingsRequirements(input);
  if (!requirements.length) return;
  check(step.dispatch_gate?.kind === 'SOURCE_REQUIREMENTS', 'UNSUPPORTED_RELATION');
  check(step.dispatch_gate.requirements.length + requirements.length <= 64, 'LIMIT_EXCEEDED');
}
