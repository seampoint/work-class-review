import { AdmissionError, byteCompare, canonical, digest, hashBytes } from './canonical.ts';
import { deploy, recoveryPermitNeedsRenewal, stateDigest, step } from './lifecycle.ts';
import { authorizationHead, dispatchPermissionConsumed, latestAuthorizationEvaluation } from './dispatch-authority.ts';
import { aggregateStep, reservationPermissionReasons, stateAdmission as reservationStateAdmission } from './reservations.ts';
import { requireShape, shape } from './schema.ts';
import { instant } from './time.ts';
import { same } from './values.ts';
import { projectOperation } from './aggregate.ts';
import { activeHolding, admitHoldingsConfiguration, admitHoldingsState, holdingsStep } from './holdings.ts';
import { admitFlowConfiguration, admitFlowInput, admitFlowState, authorizeFlowResponse, flowRequirements, flowStep } from './information-flow.ts';
import { FLOW_PUBLIC_STATUS, parseFlowFrame } from './flow-host.ts';
import type { FlowRoute } from './flow-host.ts';
import { evaluateAuthority } from './authority.ts';
import { recoveryFact } from './recovery.ts';
import type { RecordValue as Row } from './values.ts';

const clone = <T>(value: T): T => structuredClone(value);

export type BudgetRoot = {
  registry_digest: string;
  affected_anchors: string[];
  state: Row;
  state_digest: string;
};

export type BoundConnector<T> = {
  id: string;
  version: string;
  binding_digest: string;
  invoke: (request: Row) => Promise<T> | T;
};

export type FlowAuthorityAuthenticator = (configuration: Row, authority: Row) => boolean;
export type FlowReaders = Row[] | (() => Row[]);

type StoredBudget = BudgetRoot & { state_bytes: string };
type EventLogEntry = { event_digest: string; transaction_digest: string; event: string; request: string; response: string };
type StoredRoot = {
  deploy_request: string;
  state: Row;
  state_bytes: string;
  state_digest: string;
  registry_digests: string[];
  installation_budget_roots: string;
  event_log: ReadonlyMap<string, EventLogEntry>;
};
type AuthoritativeRoot = {
  readonly roots: ReadonlyMap<string, StoredRoot>;
  readonly budgets: ReadonlyMap<string, StoredBudget>;
};

function budgetKey(organization: string, registryDigest: string): string { return canonical([organization, registryDigest]); }
function rootKey(organization: string, instanceId: string): string { return canonical([organization, instanceId]); }

function* retainedFlowAuthorities(root: StoredRoot): Generator<Row> {
  for (const permit of root.state.permits ?? []) if (permit.authority_basis) yield permit.authority_basis;
  for (const row of [...root.state.authorizations ?? [], ...root.state.authorization_evaluations ?? []]) if (row.authority_input) yield row.authority_input;
  for (const row of root.state.proposal_authority_evaluations ?? []) if (row.event?.authority_input) yield row.event.authority_input;
  for (const replay of root.state.replays ?? []) if (replay.permit?.authority_basis) yield replay.permit.authority_basis;
  for (const receipt of [...root.state.receipts ?? [], ...(root.state.replays ?? []).map((row: Row) => row.decision)]) {
    for (const detail of receipt?.details ?? []) if (detail.kind === 'SEPARATION' && detail.authority_basis) yield detail.authority_basis;
  }
  for (const retained of root.event_log.values()) {
    const event = JSON.parse(retained.event);
    if (['PROPOSE', 'AUTHORIZE_DISPATCH'].includes(event.kind) && event.authority_input) yield event.authority_input;
  }
}

export class SingleProcessReferenceHost {
  private readonly selectedPin: string;
  private readonly authenticateAuthority?: FlowAuthorityAuthenticator;
  // Published maps are never mutated: work, registry state and event logs share
  // one prepared container, replaced once for each authoritative commit.
  private authoritative: AuthoritativeRoot = { roots: new Map(), budgets: new Map() };
  private get roots(): ReadonlyMap<string, StoredRoot> { return this.authoritative.roots; }
  private get budgets(): ReadonlyMap<string, StoredBudget> { return this.authoritative.budgets; }
  private readonly dispatchClaims = new Set<string>();
  private readonly gatedDispatchClaims = new Map<string, { organization: string; instanceId: string; permitId: string; authorizationDigest: string }>();
  private readonly pending = new Map<string, Row>();
  private readonly holdings = new Map<string, Row>();
  private readonly invocations = new Map<string, Row>();
  private readonly flows = new Map<string, Row>();
  private readonly flowRoutes = new Map<string, FlowRoute>();
  private readonly flowClocks = new Map<string, Row>();
  private readonly flowSources = new Map<string, Row>();
  private readonly flowDeliveries = new Map<string, Row>();
  private committingHoldings = false;
  private queue: Promise<void> = Promise.resolve();

  constructor(selectedPin: string, authenticateAuthority?: FlowAuthorityAuthenticator) { this.selectedPin = selectedPin; this.authenticateAuthority = authenticateAuthority; }

  private enqueue<T>(operation: () => Promise<T> | T): Promise<T> {
    const task = this.queue.then(operation, operation);
    this.queue = task.then(() => undefined, () => undefined);
    return task;
  }

  private admitBudget(root: BudgetRoot): StoredBudget {
    reservationStateAdmission(root.state, this.selectedPin);
    const calculatedStateDigest = digest('reservation-state', root.state);
    const calculatedRegistryDigest = digest('reservation-registry', root.state.core.configuration);
    const anchors = [...root.affected_anchors].sort(byteCompare);
    if (root.state_digest !== calculatedStateDigest || root.registry_digest !== calculatedRegistryDigest || !same(anchors, root.affected_anchors) || new Set(anchors).size !== anchors.length) throw new AdmissionError('STATE_INVALID');
    return { ...clone(root), state_bytes: canonical(root.state) };
  }

  async install(request: Row, budgetRoots: BudgetRoot[] = []): Promise<Row> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const supplied = clone(request), suppliedBudgets = clone(budgetRoots);
    return this.enqueue(() => {
      const calculated = deploy(supplied, this.selectedPin);
      if (calculated.status !== 'DEPLOYED') return clone(calculated);
      const organization = supplied.deployment_authorization.organization_id as string;
      const key = rootKey(organization, supplied.instance_id);
      const admittedBudgets = suppliedBudgets.map(row => this.admitBudget(row));
      const registryDigests = admittedBudgets.map(row => row.registry_digest).sort(byteCompare);
      const installationBudgetRoots = canonical(admittedBudgets.map(row => ({
        registry_digest: row.registry_digest,
        affected_anchors: clone(row.affected_anchors),
        state: clone(row.state),
        state_digest: row.state_digest,
      })).sort((a, b) => byteCompare(a.registry_digest, b.registry_digest)));
      if (new Set(registryDigests).size !== registryDigests.length) throw new AdmissionError('STATE_INVALID');
      const current = this.roots.get(key);
      if (current) {
        const replay = current.deploy_request === canonical(supplied) && current.state_bytes === canonical(calculated.state) && current.installation_budget_roots === installationBudgetRoots;
        const result = replay ? {
          status: 'HOST_DEPLOY', disposition: 'INSTALLED', organization, instance_id: supplied.instance_id,
          state_digest: current.state_digest, replay: true, dispatch_performed: false,
        } : {
          status: 'HOST_DEPLOY', disposition: 'INSTANCE_OCCUPIED', organization, instance_id: supplied.instance_id,
          authoritative_state_digest: current.state_digest, proposed_state_digest: calculated.state_digest, replay: false, dispatch_performed: false,
        };
        requireShape('lifecycle.schema.json', 'hostDeploymentResult', result);
        return result;
      }
      for (const budget of admittedBudgets) {
        const stored = this.budgets.get(budgetKey(organization, budget.registry_digest));
        if (stored && (stored.state_digest !== budget.state_digest || stored.state_bytes !== budget.state_bytes)) throw new AdmissionError('REVISION_CONFLICT');
      }
      const nextRoot = {
        deploy_request: canonical(supplied), state: clone(calculated.state), state_bytes: canonical(calculated.state), state_digest: calculated.state_digest,
        registry_digests: registryDigests, installation_budget_roots: installationBudgetRoots, event_log: new Map(),
      };
      const result = { status: 'HOST_DEPLOY', disposition: 'INSTALLED', organization, instance_id: supplied.instance_id, state_digest: calculated.state_digest, replay: false, dispatch_performed: false };
      requireShape('lifecycle.schema.json', 'hostDeploymentResult', result);
      const nextBudgets = new Map(this.budgets), nextRoots = new Map(this.roots);
      for (const budget of admittedBudgets) nextBudgets.set(budgetKey(organization, budget.registry_digest), budget);
      nextRoots.set(key, nextRoot);
      const response = clone(result);
      this.authoritative = { roots: nextRoots, budgets: nextBudgets };
      return response;
    });
  }

  private budgetSnapshot(organization: string, root: StoredRoot): BudgetRoot[] {
    return root.registry_digests.map(registryDigest => {
      const row = this.budgets.get(budgetKey(organization, registryDigest));
      if (!row) throw new Error('Missing authoritative budget root');
      return { registry_digest: row.registry_digest, affected_anchors: clone(row.affected_anchors), state: clone(row.state), state_digest: row.state_digest };
    });
  }

  private retainedFlowDependencies(organization?: string, validateHistory = false): Set<string> {
    const required = new Set<string>(), validated = new Map<string, Row>();
    try {
      for (const [key, root] of this.roots) {
        const [rootOrganization, instance] = JSON.parse(key), deployment = JSON.parse(root.deploy_request);
        if (organization !== undefined && rootOrganization !== organization) continue;
        for (const authority of retainedFlowAuthorities(root)) {
          const bases = authority.flow_bases ?? [], requirements = authority.envelope?.flow_requirements ?? [];
          if (!bases.length && !requirements.length) continue;
          if (deployment.deployment_authorization.organization_id !== rootOrganization || deployment.instance_id !== instance) throw new AdmissionError('STATE_INVALID');
          const principal = authority.envelope.principal, registryKey = budgetKey(rootOrganization, principal), installed = this.flows.get(registryKey);
          if (!installed || installed.state === null) throw new AdmissionError('STATE_INVALID');
          required.add(registryKey);
          for (const requirement of requirements) if (requirement.configuration_digest !== digest('flow-configuration', installed.configuration)) throw new AdmissionError('STATE_INVALID');
          for (const basis of bases) {
            if (basis.configuration.principal !== principal || !same(basis.configuration, installed.configuration) || installed.state === null) throw new AdmissionError('STATE_INVALID');
            if (!validateHistory) continue;
            const historicalKey = canonical([registryKey, basis.state_digest]);
            if (validated.has(historicalKey)) { if (!same(validated.get(historicalKey), basis.state)) throw new AdmissionError('STATE_INVALID'); continue; }
            admitFlowState(basis.configuration, basis.state, basis.state_digest, this.selectedPin);
            if (installed.state.records.length < basis.state.records.length || !same(installed.state.records.slice(0, basis.state.records.length), basis.state.records)) throw new AdmissionError('STATE_INVALID');
            validated.set(historicalKey, basis.state);
          }
        }
      }
    } catch { throw new AdmissionError('STATE_INVALID'); }
    return required;
  }

  private guardFlowReaders(organization: string, requests: FlowReaders): void {
    const readers = clone(typeof requests === 'function' ? requests() : requests);
    try {
      if (!Array.isArray(readers)) throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
      for (const input of readers) admitFlowInput(input);
      this.retainedFlowDependencies(organization);
      const installed = [...this.flows.entries()].filter(([key]) => JSON.parse(key)[0] === organization);
      if (readers.length !== installed.length) throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
      for (const [, registry] of installed) {
        const selected = readers.filter(input => same(input.configuration, registry.configuration));
        if (selected.length !== 1) throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
        this.currentFlow(organization, selected[0]);
      }
    } catch (error) { if (error instanceof AdmissionError) throw new AdmissionError('ACCESS_NOT_ESTABLISHED'); throw error; }
  }

  async pendingEvidence(organization: string, instanceId: string, responseRequests: FlowReaders = []): Promise<Row[]> {
    return this.enqueue(() => { this.guardFlowReaders(organization, responseRequests); return [...this.pending.values()].filter(row => row.organization === organization && row.instance_id === instanceId).sort((a, b) => byteCompare(a.evidence_digest, b.evidence_digest)).map(row => Object.fromEntries(['evidence_digest', 'event_id', 'instance_id', 'occurrence_id', 'registry_digests', 'status'].map(name => [name, clone(row[name])]))); });
  }

  private retainPending(organization: string, root: StoredRoot, request: Row): string | null {
    if (!shape('lifecycle.schema.json', 'stepInput', request)) return null;
    if (request.event.kind === 'DISPOSE') {
      const event = request.event, evidence = event.evidence, outcome = root.state.outcomes.find((row: Row) => row.outcome_digest === event.target.outcome_digest), permit = root.state.permits.find((row: Row) => row.permit_id === outcome?.permit_digest);
      const definition = JSON.parse(root.deploy_request).definition, step = permit && definition.steps.find((row: Row) => row.id === permit.occurrence.step_id);
      const noEffect = event.requested_result === 'ESTABLISH_NO_EFFECT' || event.requested_result === 'LEAVE_UNRESOLVED' && evidence.conclusion === 'NO_EFFECT_ESTABLISHED';
      const provider = noEffect ? [step?.completion.no_effect_provider, step?.completion.no_effect_source] : [step?.completion.effect_provider, step?.completion.effect_source];
      const authenticated = { kind: 'RECOVERY_EVIDENCE', record_digest: digest('recovery-evidence', evidence), provider: evidence.provider, source: evidence.source };
      if (!permit || event.target.instance_id !== root.state.instance_id || event.target.occurrence_id !== permit.occurrence.occurrence_id || !same(evidence.target, event.target) || !same(provider, [evidence.provider, evidence.source]) || !request.recovery_host?.authenticated_records.some((row: Row) => same(row, authenticated))) return null;
      const key = canonical([organization, root.state.instance_id, authenticated.record_digest]);
      this.pending.set(key, { organization, instance_id: root.state.instance_id, occurrence_id: permit.occurrence.occurrence_id, evidence_digest: authenticated.record_digest, event_id: event.event_id, registry_digests: [], status: 'PENDING', event: clone(event), target: clone(event.target), partitions: [] });
      return key;
    }
    if (request.event.kind !== 'EFFECT_OBSERVED') return null;
    const event = request.event, permit = root.state.permits.find((row: Row) => row.permit_id === event.permit?.permit_id);
    const dispatch = root.state.dispatches.find((row: Row) => row.dispatch_digest === event.dispatch_digest);
    if (!permit || !same(permit, event.permit) || !dispatch || dispatch.permit_digest !== permit.permit_id || event.instance_id !== root.state.instance_id) return null;
    const definition = JSON.parse(root.deploy_request).definition, step = definition.steps.find((row: Row) => row.id === permit.occurrence.step_id);
    const evidence = event.native_evidence;
    const provider = evidence.status === 'NO_EFFECT_ESTABLISHED' ? [step.completion.no_effect_provider, step.completion.no_effect_source, step.completion.no_effect_record_type] : [step.completion.effect_provider, step.completion.effect_source, step.completion.effect_record_type];
    if (evidence.native_request_digest !== digest('native-request', evidence.attributed_request) || !same([evidence.provider, evidence.source, evidence.record_type], provider)) return null;
    const evidenceDigest = recoveryFact(evidence);
    if (root.state.outcomes.some((row: Row) => recoveryFact(row.native_evidence) === evidenceDigest)) return null;
    const key = canonical([organization, root.state.instance_id, evidenceDigest]);
    const partitions = this.permissionPartitions(organization, permit, []);
    this.pending.set(key, { organization, instance_id: root.state.instance_id, occurrence_id: permit.occurrence.occurrence_id, evidence_digest: evidenceDigest, event_id: event.event_id, registry_digests: (permit.budget_revisions ?? []).map((row: Row) => row.registry_digest).sort(byteCompare), status: 'PENDING', event: clone(event), target: { kind: 'WORK_OUTCOME', instance_id: root.state.instance_id, occurrence_id: permit.occurrence.occurrence_id, outcome_digest: digest('pending-work-outcome', { evidence_digest: evidenceDigest }) }, partitions });
    return key;
  }

  private permissionPartitions(organization: string, permit: Row | null, inputs: Row[]): Row[] {
    const result: Row[] = [];
    for (const revision of permit?.budget_revisions ?? []) {
      const budget = this.budgets.get(budgetKey(organization, revision.registry_digest)), reservation = budget?.state.core.reservations.find((row: Row) => row.id === revision.reservation_id);
      for (const row of reservation?.contributions ?? []) result.push({ registry_digest: revision.registry_digest, anchor: row.anchor, key: clone(row.key) });
    }
    for (const input of inputs) {
      const authority = input.request?.event.payload.authority;
      if (!authority) continue;
      const core = this.budgets.get(budgetKey(organization, input.registry_digest))?.state.core;
      for (const budget of core?.budgets ?? []) {
        if (!input.affected_anchors.includes(budget.definition.anchor)) continue;
        const authorization = budget.authorizations.find((row: Row) => row.work_class_digest === digest('authority-work-class', authority.work_class) && row.envelope_digest === digest('authority-envelope', authority.envelope) && row.step === authority.proposal.step);
        if (!authorization) continue;
        const fields = authorization.projection.map((row: Row) => ({ name: row.budget_field, value: { type_ref: row.budget_type, value: authority.proposal.fields.find((field: Row) => field.name === row.native_field)?.value.value } })).sort((a: Row, b: Row) => byteCompare(a.name, b.name));
        try { for (const row of projectOperation(budget.definition.aggregate, { occurrence: authority.proposal.occurrence, step: authority.proposal.step, fields })) result.push({ registry_digest: input.registry_digest, anchor: budget.definition.anchor, key: clone(row.key) }); }
        catch (error) { if (!(error instanceof AdmissionError)) throw error; }
      }
    }
    return result;
  }

  private pendingBlocks(organization: string, root: StoredRoot, occurrenceId: string, partitions: Row[]): boolean {
    const ancestors = new Set<string>([occurrenceId]), inventory = [...root.state.active, ...root.state.completed];
    const visit = (id: string): void => { for (const predecessor of inventory.find((row: Row) => row.occurrence.occurrence_id === id)?.occurrence.predecessor_occurrence_ids ?? []) if (!ancestors.has(predecessor)) { ancestors.add(predecessor); visit(predecessor); } };
    visit(occurrenceId);
    return [...this.pending.values()].some(row => row.organization === organization && ((row.instance_id === root.state.instance_id && ancestors.has(row.occurrence_id)) || (row.partitions ?? []).some((pending: Row) => partitions.some(candidate => candidate.registry_digest === pending.registry_digest && candidate.anchor === pending.anchor && (pending.key === null || candidate.key === null || same(candidate.key, pending.key))))));
  }

  async submitRegistry(organization: string, request: Row, failureReference: string | null = null): Promise<Row> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const supplied = clone(request);
    return this.enqueue(() => {
      const registry = supplied.host_evidence?.registry_digest, stored = this.budgets.get(budgetKey(organization, registry));
      if (!stored) throw new Error('Registry is not installed');
      if (!shape('reservation.schema.json', 'input', supplied)) return { transition: aggregateStep(supplied, this.selectedPin), committed: false };
      let pendingKey: string | null = null;
      if (shape('reservation.schema.json', 'input', supplied) && supplied.event.kind === 'DISPOSE') {
        const payload = supplied.event.payload, evidence = payload.evidence, reservation = stored.state.core.reservations.find((row: Row) => row.id === payload.target.reservation), tuple = { kind: 'RECOVERY_EVIDENCE', record_digest: digest('recovery-evidence', evidence), provider: evidence.provider, source: evidence.source };
        const noEffect = payload.requested_result === 'ESTABLISH_NO_EFFECT' || payload.requested_result === 'LEAVE_UNRESOLVED' && evidence.conclusion === 'NO_EFFECT_ESTABLISHED';
        const providersMatch = reservation?.contributions.every((row: Row) => { const policy = stored.state.core.budgets.find((budget: Row) => budget.definition.anchor === row.anchor)?.definition.reservation_policy; const provider = noEffect ? policy?.no_effect : policy?.settlement; return provider?.provider === evidence.provider && provider?.source === evidence.source; });
        if (reservation && providersMatch && payload.target.registry_digest === registry && same(evidence.target, payload.target) && supplied.host_evidence.recovery?.authenticated_records.some((row: Row) => same(row, tuple))) {
          pendingKey = canonical([organization, reservation.authority.proposal.instance, tuple.record_digest]);
          this.pending.set(pendingKey, { organization, instance_id: reservation.authority.proposal.instance, occurrence_id: reservation.authority.proposal.occurrence, evidence_digest: tuple.record_digest, event_id: supplied.event.id, registry_digests: [registry], status: 'PENDING', event: clone(supplied.event), target: clone(payload.target), partitions: reservation.contributions.map((row: Row) => ({ registry_digest: registry, anchor: row.anchor, key: clone(row.key) })) });
        }
      }
      if (['SETTLE', 'RELEASE'].includes(supplied.event.kind)) {
        const native = supplied.event.payload.native, reservation = stored.state.core.reservations.find((row: Row) => row.id === native.reservation);
        const tuple = { kind: 'NATIVE_OUTCOME', record_digest: digest('reservation-native-outcome', native), provider: native.provider, source: native.source };
        const providerMatches = reservation?.contributions.every((row: Row) => {
          const policy = stored.state.core.budgets.find((budget: Row) => budget.definition.anchor === row.anchor)?.definition.reservation_policy;
          const provider = supplied.event.kind === 'RELEASE' ? policy?.no_effect : policy?.settlement;
          return provider?.provider === native.provider && provider?.source === native.source;
        });
        if (reservation && providerMatches && supplied.host_evidence.authenticated_records.some((row: Row) => same(row, tuple)) && !stored.state.core.effects.some((row: Row) => recoveryFact(row.native) === recoveryFact(native))) {
          const evidenceDigest = recoveryFact(native);
          pendingKey = canonical([organization, reservation.authority.proposal.instance, evidenceDigest]);
          this.pending.set(pendingKey, { organization, instance_id: reservation.authority.proposal.instance, occurrence_id: reservation.authority.proposal.occurrence, evidence_digest: evidenceDigest, event_id: supplied.event.id, registry_digests: [registry], status: 'PENDING', event: clone(supplied.event), target: { kind: 'RESERVATION', registry_digest: registry, reservation: reservation.id }, partitions: reservation.contributions.map((row: Row) => ({ registry_digest: registry, anchor: row.anchor, key: native.completion_mismatch ? null : clone(row.key) })) });
        }
      }
      if (supplied.state_digest !== stored.state_digest || canonical(supplied.state) !== stored.state_bytes) return { transition: { status: 'REFUSED', code: 'REVISION_CONFLICT', path: '', state: clone(stored.state), state_digest: stored.state_digest }, committed: false };
      if (['RESERVE', 'RENEW'].includes(supplied.event.kind)) {
        const input = { registry_digest: registry, affected_anchors: supplied.event.payload.authority.envelope.limits.shared_budgets, request: supplied }, partitions = this.permissionPartitions(organization, null, [input]);
        if ([...this.pending.values()].some(row => row.organization === organization && row.partitions.some((pending: Row) => partitions.some(candidate => candidate.registry_digest === pending.registry_digest && candidate.anchor === pending.anchor && (pending.key === null || same(candidate.key, pending.key)))))) return { transition: { status: 'REFUSED', code: 'EVIDENCE_UNAVAILABLE', path: '', state: clone(stored.state), state_digest: stored.state_digest }, committed: false };
      }
      if (supplied.host_evidence.recovery) supplied.host_evidence.recovery.pending_evidence = [...(supplied.host_evidence.recovery.pending_evidence ?? []), ...[...this.pending.values()].filter(row => row.organization === organization && row.registry_digests.includes(registry)).map(row => ({ target: clone(row.target), record_digest: row.evidence_digest }))].filter((row, index, rows) => rows.findIndex(candidate => same(candidate, row)) === index);
      const transition = aggregateStep(supplied, this.selectedPin);
      if (transition.status !== 'TRANSITION') return { transition: clone(transition), committed: false };
      if (failureReference !== null) return { transition: clone(transition), committed: false };
      const nextBudgets = new Map(this.budgets);
      nextBudgets.set(budgetKey(organization, registry), this.admitBudget({ registry_digest: registry, affected_anchors: clone(stored.affected_anchors), state: transition.state, state_digest: transition.state_digest }));
      const response = { transition: clone(transition), committed: true };
      this.authoritative = { roots: this.roots, budgets: nextBudgets };
      if (pendingKey) this.pending.delete(pendingKey);
      return response;
    });
  }

  async snapshot(organization: string, instanceId: string, responseRequests: FlowReaders = []): Promise<{ state: Row; state_digest: string; budget_states: BudgetRoot[] }> {
    return this.enqueue(() => {
      this.guardFlowReaders(organization, responseRequests);
      const root = this.roots.get(rootKey(organization, instanceId));
      if (!root) throw new Error('Instance is not installed');
      return { state: clone(root.state), state_digest: root.state_digest, budget_states: this.budgetSnapshot(organization, root) };
    });
  }

  private statefulRefusal(organization: string, root: StoredRoot, request: Row, code: string): Row {
    const result = { status: 'REFUSED', profile: request.profile, role: request.role, code, path: '', state: clone(root.state), state_digest: root.state_digest, budget_states: this.budgetSnapshot(organization, root) };
    requireShape('lifecycle.schema.json', 'statefulRefusal', result);
    return result;
  }

  private permitRegistriesCurrent(organization: string, root: StoredRoot, permit: Row): boolean {
    try {
      const definition = JSON.parse(root.deploy_request).definition;
      const selectedStep = definition.steps.find((row: Row) => row.id === permit.occurrence.step_id);
      const retained = root.state.permits.find((row: Row) => row.permit_id === permit.permit_id);
      if (!same(permit, retained) || root.state.deployment_organization_id !== organization) return false;
      const bindings = permit.budget_revisions as Row[];
      if (!selectedStep.shared_budgets.length && !selectedStep.exclusive_keys?.length) return bindings.length === 0;
      if (bindings.length !== 1) return false;
      const proposal = root.state.proposals.find((row: Row) => row.permit_digest === permit.permit_id);
      const issuedResult = root.state.replays.find((row: Row) => row.event_id === proposal.event_id);
      if (!same(issuedResult.permit, permit)) return false;
      for (const binding of bindings) {
        const registry = this.budgets.get(budgetKey(organization, binding.registry_digest));
        if (!registry || !root.registry_digests.includes(binding.registry_digest)) return false;
        const originals = issuedResult.budget_results.filter((row: Row) => row.registry_digest === binding.registry_digest);
        if (originals.length !== 1) return false;
        const original = originals[0], originalReserved = original.result.state.core.reservations.find((row: Row) => row.id === binding.reservation_id);
        const authority = originalReserved.authority;
        if (permit.authority_basis && !same(permit.authority_basis, authority)) return false;
        const current = registry.state, core = current.core;
        if (current.specification_pin !== this.selectedPin || root.state.specification_pin !== this.selectedPin
          || digest('reservation-registry', core.configuration) !== binding.registry_digest
          || core.configuration.principal !== authority.envelope.principal || core.revision !== binding.revision
          || !same(binding.affected_anchors, selectedStep.shared_budgets)
          || registry.state_digest !== digest('reservation-state', current) || registry.state_bytes !== canonical(current)) return false;
        const reservations = core.reservations.filter((row: Row) => row.id === binding.reservation_id);
        const records = current.receipts.filter((row: Row) => digest('reservation-receipt', row.receipt) === binding.receipt_digest);
        if (reservations.length !== 1 || records.length !== 1) return false;
        const reserved = reservations[0], record = records[0], receipt = record.receipt;
        const kind = permit.supersedes_permit_digest !== null ? 'RENEW' : 'RESERVE';
        if (reserved.status !== 'OPEN' || !same(reserved.authority, authority) || !same(reserved.authority_result, permit.authority_result)
          || !same([...new Set<string>(reserved.contributions.map((row: Row) => row.anchor))].sort(byteCompare), binding.affected_anchors)
          || receipt.revision !== binding.revision || receipt.reservation !== binding.reservation_id
          || receipt.decision !== (kind === 'RENEW' ? 'RENEWED' : 'RESERVED')
          || !same(receipt.authority_result, permit.authority_result) || !same(receipt.budgets.map((row: Row) => row.anchor), binding.affected_anchors)
          || receipt.next_core_digest !== digest('reservation-core', core) || record.event.kind !== kind
          || !same(record.event.payload.authority, authority) || record.host_evidence.registry_digest !== binding.registry_digest
          || !same(original.affected_anchors, binding.affected_anchors) || original.result.receipt_digest !== binding.receipt_digest
          || !same(original.result.receipt, receipt) || !same(original.result.state, current)) return false;
      }
      return true;
    } catch { return false; }
  }

  async submit(organization: string, request: Row, failureReference: string | null = null, responseRequests: FlowReaders = []): Promise<Row> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const supplied = clone(request);
    return this.enqueue(() => {
      try { this.guardFlowReaders(organization, responseRequests); } catch (error) { if (error instanceof AdmissionError) return SingleProcessReferenceHost.publicFailure(); throw error; }
      const result = (() => {
      const key = rootKey(organization, supplied.state.instance_id);
      const root = this.roots.get(key);
      if (!root) throw new Error('Instance is not installed');
      const event = supplied.event as Row, retained = root.event_log.get(event.event_id);
      const pendingKey = event.kind === 'DISPOSE' && retained?.event === canonical(event) ? null : this.retainPending(organization, root, supplied);
      if (retained && retained.event !== canonical(event)) return this.statefulRefusal(organization, root, supplied, 'REPLAY_CONFLICT');
      if (supplied.state_digest !== root.state_digest || canonical(supplied.state) !== root.state_bytes) return this.statefulRefusal(organization, root, supplied, 'REVISION_CONFLICT');
      if (retained) {
        const replay = step(supplied, this.selectedPin);
        if (replay.status !== 'STEP' || replay.replay !== true) throw new Error('Consumer did not return the retained exact replay');
        return { transition: clone(replay), host_commit: null };
      }
      const budgetInputs = ['PROPOSE', 'EFFECT_OBSERVED'].includes(event.kind) ? event.budget_inputs : [];
      const permit = event.permit ?? null;
      if (['PROPOSE', 'AUTHORIZE_DISPATCH'].includes(event.kind) && this.pendingBlocks(organization, root, event.occurrence?.occurrence_id ?? event.permit?.occurrence.occurrence_id, this.permissionPartitions(organization, permit, budgetInputs))) return this.statefulRefusal(organization, root, supplied, 'EVIDENCE_UNAVAILABLE');
      const selections = [...(supplied.recovery_registries ?? []), ...(event.registry ? [event.registry] : [])];
      for (const selection of selections) {
        const registry = digest('reservation-registry', selection.state.core.configuration), budget = this.budgets.get(budgetKey(organization, registry));
        if (!budget || selection.state_digest !== budget.state_digest || canonical(selection.state) !== budget.state_bytes) return this.statefulRefusal(organization, root, supplied, 'REVISION_CONFLICT');
      }
      if (supplied.recovery_host) supplied.recovery_host.pending_evidence = [...(supplied.recovery_host.pending_evidence ?? []), ...[...this.pending.values()].filter(row => row.organization === organization && row.instance_id === root.state.instance_id).map(row => ({ target: clone(row.target), record_digest: row.evidence_digest }))].filter((row, index, rows) => rows.findIndex(candidate => same(candidate, row)) === index);
      for (const input of budgetInputs as Row[]) {
        const budget = this.budgets.get(budgetKey(organization, input.registry_digest));
        if (!budget || input.request.state_digest !== budget.state_digest || canonical(input.request.state) !== budget.state_bytes) return this.statefulRefusal(organization, root, supplied, 'REVISION_CONFLICT');
      }
      for (const basis of supplied.event.authority_input?.holdings_bases ?? []) {
        const selected = this.holdings.get(budgetKey(organization, digest('holdings-configuration', basis.configuration)));
        if (!selected || !same(selected.configuration, basis.configuration) || selected.state_digest !== basis.state_digest || !same(selected.state, basis.state)) return this.statefulRefusal(organization, root, supplied, 'DEPENDENCY_MISMATCH');
      }
      for (const basis of supplied.event.authority_input?.flow_bases ?? []) { const installed = this.flows.get(budgetKey(organization, basis.configuration.principal)); if (!installed || !same(installed.configuration, basis.configuration) || installed.state_digest !== basis.state_digest || !same(installed.state, basis.state)) return this.statefulRefusal(organization, root, supplied, 'DEPENDENCY_MISMATCH'); }
      const transition = step(supplied, this.selectedPin);
      if (transition.status !== 'STEP') return clone(transition);
      if (event.kind === 'AUTHORIZE_DISPATCH' && !this.permitRegistriesCurrent(organization, root, permit)) return this.statefulRefusal(organization, root, supplied, 'EVIDENCE_UNAVAILABLE');
      const before = (budgetInputs as Row[]).map(input => ({ registry_digest: input.registry_digest, affected_anchors: clone(input.affected_anchors), state_digest: input.request.state_digest })).sort((a, b) => byteCompare(a.registry_digest, b.registry_digest));
      if (failureReference !== null) {
        const failed = { status: 'HOST_COMMIT', disposition: 'COMMIT_FAILED', transaction_digest: transition.transaction_digest, state_before_digest: supplied.state_digest, authoritative_state_digest: root.state_digest, budget_before: before, authoritative_budgets: clone(before), failure_reference: failureReference, dispatch_performed: false };
        requireShape('lifecycle.schema.json', 'hostCommitResult', failed);
        return { transition: clone(transition), host_commit: failed };
      }
      const admittedBudgets = (transition.budget_results as Row[]).map(row => this.admitBudget({ registry_digest: row.registry_digest, affected_anchors: clone(row.affected_anchors), state: clone(row.result.state), state_digest: digest('reservation-state', row.result.state) }));
      const after = admittedBudgets.map(row => ({ registry_digest: row.registry_digest, affected_anchors: clone(row.affected_anchors), state_digest: row.state_digest })).sort((a, b) => byteCompare(a.registry_digest, b.registry_digest));
      const registryDigests = [...new Set([...root.registry_digests, ...admittedBudgets.map(row => row.registry_digest)])].sort(byteCompare);
      const eventLog = new Map(root.event_log);
      eventLog.set(event.event_id, { event_digest: digest('runtime-event', event), transaction_digest: transition.transaction_digest, event: canonical(event), request: canonical(supplied), response: canonical(transition) });
      const nextRoot: StoredRoot = { ...root, state: clone(transition.state), state_bytes: canonical(transition.state), state_digest: transition.state_digest, registry_digests: registryDigests, event_log: eventLog };
      const committed = { status: 'HOST_COMMIT', disposition: 'COMMITTED', transaction_digest: transition.transaction_digest, state_before_digest: supplied.state_digest, state_after_digest: transition.state_digest, budget_before: before, budget_after: after, dispatch_performed: false };
      requireShape('lifecycle.schema.json', 'hostCommitResult', committed);
      const nextBudgets = new Map(this.budgets), nextRoots = new Map(this.roots);
      for (const admitted of admittedBudgets) nextBudgets.set(budgetKey(organization, admitted.registry_digest), admitted);
      nextRoots.set(key, nextRoot);
      const response = { transition: clone(transition), host_commit: clone(committed) };
      this.authoritative = { roots: nextRoots, budgets: nextBudgets };
      if (pendingKey) this.pending.delete(pendingKey);
      return response;
      })();
      try { this.guardFlowReaders(organization, responseRequests); } catch (error) { if (error instanceof AdmissionError) return SingleProcessReferenceHost.publicFailure(); throw error; }
      return result;
    });
  }

  async installHoldings(organization: string, configuration: Row, state: Row, stateDigestValue: string): Promise<Row> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const supplied = clone({ configuration, state, state_digest: stateDigestValue });
    return this.enqueue(() => {
      admitHoldingsConfiguration(supplied.configuration, this.selectedPin);
      admitHoldingsState(supplied.configuration, supplied.state, supplied.state_digest, this.selectedPin);
      const key = budgetKey(organization, digest('holdings-configuration', supplied.configuration)), prior = this.holdings.get(key);
      if (prior && !same(prior, supplied)) throw new AdmissionError('REVISION_CONFLICT');
      this.holdings.set(key, supplied); return clone(supplied);
    });
  }

  async submitHoldings(organization: string, input: Row, failureReference: string | null = null): Promise<Row> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const supplied = clone(input);
    return this.enqueue(() => {
      requireShape('holdings.schema.json', 'input', supplied);
      const key = budgetKey(organization, digest('holdings-configuration', supplied.configuration)), stored = this.holdings.get(key);
      if (stored && (!same(stored.configuration, supplied.configuration) || !same(stored.state, supplied.state) || stored.state_digest !== supplied.state_digest) || !stored && supplied.state !== null) return { status: 'REFUSED', code: 'REVISION_CONFLICT', path: '', state: clone(stored?.state ?? null), state_digest: stored?.state_digest ?? null };
      const transition = holdingsStep(supplied, this.selectedPin);
      if (transition.status !== 'TRANSITION') return clone(transition);
      if (failureReference !== null) return { status: 'COMMIT_FAILED', transition: clone(transition), state: clone(stored?.state ?? null), state_digest: stored?.state_digest ?? null };
      this.holdings.set(key, { configuration: clone(supplied.configuration), state: clone(transition.state), state_digest: transition.state_digest });
      return clone(transition);
    });
  }

  async holdingsSnapshot(organization: string, configurationDigest: string): Promise<Row> {
    return this.enqueue(() => {
      const stored = this.holdings.get(budgetKey(organization, configurationDigest));
      if (!stored) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
      return clone(stored);
    });
  }

  async installFlow(organization: string, configuration: Row, clock: Row, routes: FlowRoute[], state: Row | null = null, stateDigestValue: string | null = null): Promise<void> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const supplied = clone({ configuration, clock, routes, state, state_digest: stateDigestValue });
    return this.enqueue(() => {
      if (typeof this.authenticateAuthority !== 'function') throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
      admitFlowConfiguration(supplied.configuration, this.selectedPin);
      if (supplied.clock.status !== 'AVAILABLE' || supplied.clock.source !== supplied.configuration.clock_source) throw new AdmissionError('CLOCK_INVALID');
      instant(supplied.clock.instant);
      if ((supplied.state === null) !== (supplied.state_digest === null)) throw new AdmissionError('STATE_INVALID');
      if (supplied.state) admitFlowState(supplied.configuration, supplied.state, supplied.state_digest!, this.selectedPin);
      const key = budgetKey(organization, supplied.configuration.principal), prior = this.flows.get(key);
      const installed = { configuration: supplied.configuration, state: supplied.state, state_digest: supplied.state_digest };
      if (prior && !same(prior, installed)) throw new AdmissionError('REVISION_CONFLICT');
      const keys = new Set<string>();
      for (const route of supplied.routes) {
        const routeKey = canonical([organization, route.interface, route.operation]);
        if (!same(Object.keys(route).sort(), ['channel', 'connector', 'immediate_custody', 'interface', 'operation', 'purpose', 'recipient_field']) || route.immediate_custody !== true || !shape('lifecycle.schema.json', 'connector', route.connector) || ['interface', 'operation', 'recipient_field', 'channel', 'purpose'].some(name => typeof (route as Row)[name] !== 'string' || !(route as Row)[name].length) || keys.has(routeKey)) throw new AdmissionError('INPUT_INVALID');
        keys.add(routeKey);
        const existing = this.flowRoutes.get(routeKey);
        if (existing && !same(existing, route)) throw new AdmissionError('DEFINITION_CONFLICT');
      }
      if (prior && !same(this.flowClocks.get(key), supplied.clock)) throw new AdmissionError('REVISION_CONFLICT');
      this.flows.set(key, installed); this.flowClocks.set(key, supplied.clock);
      for (const route of supplied.routes) this.flowRoutes.set(canonical([organization, route.interface, route.operation]), route);
    });
  }

  async installFlowSource(organization: string, principal: string, descriptor: Row, bytes: Uint8Array): Promise<void> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const supplied = clone(descriptor), contents = Buffer.from(bytes);
    return this.enqueue(() => {
      requireShape('information-flow.schema.json', 'source', supplied);
      if (!this.flows.has(budgetKey(organization, principal)) || supplied.content_digest !== hashBytes(contents)) throw new AdmissionError('DEPENDENCY_MISMATCH');
      const coordinates = ['provider', 'source', 'record_type', 'record_id', 'revision', 'scope'].map(name => supplied[name]);
      const key = canonical([organization, principal, coordinates]), current = this.flowSources.get(key), value = { descriptor: supplied, bytes_base64: contents.toString('base64') };
      if (current && !same(current, value)) throw new AdmissionError('DEPENDENCY_MISMATCH');
      this.flowSources.set(key, value);
    });
  }

  async advanceFlowClock(organization: string, principal: string, clock: Row): Promise<void> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const supplied = clone(clock);
    return this.enqueue(() => {
      const key = budgetKey(organization, principal), prior = this.flowClocks.get(key), installed = this.flows.get(key);
      if (!installed || supplied.source !== installed.configuration.clock_source || supplied.status !== 'AVAILABLE' || !prior || instant(supplied.instant) < instant(prior.instant)) throw new AdmissionError('CLOCK_INVALID');
      this.flowClocks.set(key, supplied);
    });
  }

  private authenticateFlowAuthority(organization: string, configuration: Row, authority: Row): void {
    if (!this.authenticateAuthority || this.authenticateAuthority(clone(configuration), clone(authority)) !== true) throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
    for (const basis of authority.holdings_bases ?? []) {
      const installed = this.holdings.get(budgetKey(organization, digest('holdings-configuration', basis.configuration)));
      if (!installed || !same(installed.configuration, basis.configuration) || installed.state_digest !== basis.state_digest || !same(installed.state, basis.state)) throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
    }
    for (const basis of authority.flow_bases ?? []) {
      const installed = this.flows.get(budgetKey(organization, basis.configuration.principal));
      if (!installed || !same(installed.configuration, basis.configuration) || installed.state_digest !== basis.state_digest || !same(installed.state, basis.state)) throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
    }
  }

  private currentFlow(organization: string, input: Row): Row {
    admitFlowInput(input);
    const key = budgetKey(organization, input.configuration.principal), installed = this.flows.get(key), clock = this.flowClocks.get(key);
    if (!installed || !same(installed.configuration, input.configuration) || !same(clock, input.response_authority.clock)) throw new AdmissionError('DEPENDENCY_MISMATCH');
    this.authenticateFlowAuthority(organization, installed.configuration, input.response_authority);
    authorizeFlowResponse(input, this.selectedPin);
    if (!same(installed.state, input.state) || installed.state_digest !== input.state_digest) throw new AdmissionError('REVISION_CONFLICT');
    const replay = installed.state?.records.some((row: Row) => row.event.id === input.event.id);
    if (!replay && !same(input.event.clock, clock)) throw new AdmissionError('CLOCK_INVALID');
    return installed;
  }

  async submitFlow(organization: string, input: Row, failurePoint: string | null = null, delivery?: { context_id: string; actor: string; invoke: (bytes: Buffer) => Promise<unknown> | unknown }): Promise<Row> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const supplied = clone(input);
    return this.enqueue(async () => {
      try {
        const installed = this.currentFlow(organization, supplied);
        // Business exposure is committed exclusively inside dispatchPermitted.
        if (supplied.event.kind === 'EXPOSE') throw new AdmissionError('OPERATION_NOT_ALLOWED');
        let bytes: Buffer | undefined;
        if (supplied.event.kind === 'READ') {
          const descriptor = supplied.event.payload.source, coordinates = ['provider', 'source', 'record_type', 'record_id', 'revision', 'scope'].map(name => descriptor[name]);
          const selected = this.flowSources.get(canonical([organization, supplied.configuration.principal, coordinates]));
          if (!selected || !same(selected.descriptor, descriptor)) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
          bytes = Buffer.from(selected.bytes_base64, 'base64');
        } else if (supplied.event.kind === 'IMPORT') {
          const artifact = installed.state?.core.artifacts.find((row: Row) => row.id === supplied.event.payload.artifact_id);
          if (artifact) bytes = Buffer.from(canonical({ types: artifact.types, fields: artifact.fields }));
        }
        if (delivery) {
          const id = supplied.event.kind === 'READ' ? supplied.event.payload.context_id : supplied.event.payload.receiver_context_id;
          const receiver = installed.state?.core.contexts.find((row: Row) => row.id === id);
          if (!bytes || !receiver || delivery.context_id !== id || delivery.actor !== receiver.actor || typeof delivery.invoke !== 'function') throw new AdmissionError('BINDING_MISMATCH');
        }
        for (const authority of [supplied.event.payload.access_authority, supplied.event.payload.transfer_authority].filter(Boolean)) this.authenticateFlowAuthority(organization, supplied.configuration, authority);
        const result = flowStep(supplied, this.selectedPin);
        if (result.status === 'TRANSITION' && !result.replay && failurePoint !== 'BEFORE_COMMIT') { installed.state = clone(result.state); installed.state_digest = result.state_digest; }
        if (failurePoint === 'BEFORE_COMMIT' && result.status === 'TRANSITION') return { status: 'COMMIT_FAILED' };
        if (result.status === 'TRANSITION' && !result.replay && delivery) {
          const key = canonical([organization, supplied.configuration.principal, supplied.event.payload.intent_id]);
          const retained: Row = { intent_id: supplied.event.payload.intent_id, claim_id: supplied.event.payload.claim_id, receipt_digest: result.receipt_digest, status: 'PENDING' }; this.flowDeliveries.set(key, retained);
          if (failurePoint !== 'AFTER_COMMIT') {
            this.committingHoldings = true;
            try { await delivery.invoke(Buffer.from(bytes!)); retained.status = failurePoint === 'AFTER_INVOKE' ? 'UNCERTAIN' : 'ESTABLISHED'; }
            catch { retained.status = 'UNCERTAIN'; }
            finally { this.committingHoldings = false; }
          }
        }
        this.authenticateFlowAuthority(organization, supplied.configuration, supplied.response_authority); authorizeFlowResponse(supplied, this.selectedPin);
        return clone(result);
      } catch (error) { if (error instanceof AdmissionError) return { status: 'REFUSED', code: error.code, path: '' }; throw error; }
    });
  }

  async submitFlowFrame(organization: string, frame: Uint8Array): Promise<Row> {
    try { return await this.submitFlow(organization, parseFlowFrame(frame)); }
    catch (error) { if (error instanceof AdmissionError) return { status: 'REFUSED', code: error.code, path: '' }; throw error; }
  }

  async publicFlowStatus(organization: string, principal: string, request: { id: string; recipient: string; digest: string }, authority: Row): Promise<Row> {
    const independent = clone(request), supplied = clone(authority);
    return this.enqueue(() => {
      const key = budgetKey(organization, principal), installed = this.flows.get(key), clock = this.flowClocks.get(key);
      if (!installed || !same(Object.keys(independent).sort(), ['digest', 'id', 'recipient']) || !same(supplied.clock, clock) || supplied.proposal.executor.role !== installed.configuration.response_role || supplied.envelope.principal !== principal || supplied.proposal.interface !== installed.configuration.control_interface || supplied.proposal.operation !== installed.configuration.response_operation || supplied.proposal.fields.length !== 1 || supplied.proposal.fields[0].name !== 'admission_subject' || supplied.proposal.fields[0].value.value !== independent.digest || (supplied.flow_bases ?? []).length || (supplied.envelope.flow_requirements ?? []).length || supplied.envelope.limits.shared_budgets.length) throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
      this.authenticateFlowAuthority(organization, installed.configuration, supplied);
      const result = evaluateAuthority(supplied, this.selectedPin);
      if (result.status !== 'READY_FOR_RESERVATION' || result.required_budgets.length) throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
      if (independent.digest !== digest('flow-public-status-request', { id: independent.id, recipient: independent.recipient })) throw new AdmissionError('BINDING_MISMATCH');
      const clean = installed.state?.core.contexts.find((context: Row) => context.actor === supplied.proposal.executor.actor && context.purpose === 'PUBLIC_STATUS' && context.restrictions.length === 0 && context.origins.length === 2 && context.origins.every((origin: Row) => origin.provider === installed.configuration.provider && origin.source === installed.configuration.source && origin.restrictions.length === 0) && context.origins.some((origin: Row) => origin.record_type === 'HOST_CONSTANT' && origin.record_id === 'flow-public-status' && origin.content_digest === hashBytes(Buffer.from(FLOW_PUBLIC_STATUS))) && context.origins.some((origin: Row) => origin.record_type === 'INDEPENDENT_REQUEST' && origin.record_id === independent.id && origin.content_digest === independent.digest));
      if (!clean) throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
      return { request_id: independent.id, recipient: independent.recipient, body: FLOW_PUBLIC_STATUS, provenance: { constant_digest: digest('flow-public-status-constant', FLOW_PUBLIC_STATUS), request_digest: independent.digest, authority_result_digest: digest('authority-result', result) } };
    });
  }

  async exportCheckpoint(responseRequests: Record<string, FlowReaders> = {}): Promise<Row> {
    return this.enqueue(() => {
      for (const organization of new Set([...this.flows.keys()].map(key => JSON.parse(key)[0]))) this.guardFlowReaders(organization, responseRequests[organization] ?? []);
      return ({ specification_pin: this.selectedPin,
      flow_sources: [...this.flowSources.entries()].map(clone), flow_deliveries: [...this.flowDeliveries.entries()].map(clone),
      flows: [...this.flows.entries()].map(clone), flow_routes: [...this.flowRoutes.entries()].map(clone), flow_clocks: [...this.flowClocks.entries()].map(clone),
      roots: [...this.roots.entries()].map(([key, value]) => [key, { ...clone(value), event_log: clone([...value.event_log.entries()]) }]),
      budgets: [...this.budgets.entries()].map(clone), holdings: [...this.holdings.entries()].map(clone),
      invocations: [...this.invocations.entries()].map(clone), dispatch_claims: [...this.dispatchClaims],
      gated_dispatch_claims: [...this.gatedDispatchClaims.entries()].map(clone), pending: [...this.pending.entries()].map(clone),
    }); });
  }

  static fromCheckpoint(pin: string, checkpoint: Row, authenticateAuthority?: FlowAuthorityAuthenticator): SingleProcessReferenceHost {
    if (checkpoint.specification_pin !== pin) throw new AdmissionError('VERSION_UNSUPPORTED');
    if ((checkpoint.flows ?? []).length && typeof authenticateAuthority !== 'function') throw new AdmissionError('ACCESS_NOT_ESTABLISHED');
    const host = new SingleProcessReferenceHost(pin, authenticateAuthority);
    // This carrier is a protected process checkpoint, not an untrusted protocol input.
    const roots = new Map<string, StoredRoot>(), budgets = new Map<string, StoredBudget>();
    for (const [key, value] of checkpoint.roots) roots.set(key, { ...clone(value), event_log: new Map(clone(value.event_log)) });
    for (const [key, value] of checkpoint.budgets) budgets.set(key, host.admitBudget(value));
    host.authoritative = { roots, budgets };
    for (const [key, value] of checkpoint.holdings) {
      admitHoldingsConfiguration(value.configuration, pin); admitHoldingsState(value.configuration, value.state, value.state_digest, pin);
      host.holdings.set(key, clone(value));
    }
    for (const [key, value] of checkpoint.flows ?? []) {
      admitFlowConfiguration(value.configuration, pin);
      const parsedKey = JSON.parse(key);
      if (!Array.isArray(parsedKey) || parsedKey.length !== 2 || typeof parsedKey[0] !== 'string' || key !== budgetKey(parsedKey[0], value.configuration.principal) || host.flows.has(key)) throw new AdmissionError('STATE_INVALID');
      if (value.state === null) { if (value.state_digest !== null) throw new AdmissionError('STATE_INVALID'); }
      else admitFlowState(value.configuration, value.state, value.state_digest, pin);
      host.flows.set(key, clone(value));
    }
    for (const [key, value] of checkpoint.flow_sources ?? []) { if (value.descriptor.content_digest !== hashBytes(Buffer.from(value.bytes_base64, 'base64'))) throw new AdmissionError('STATE_INVALID'); host.flowSources.set(key, clone(value)); }
    for (const [key, value] of checkpoint.flow_deliveries ?? []) host.flowDeliveries.set(key, clone(value));
    for (const [key, value] of checkpoint.flow_routes ?? []) host.flowRoutes.set(key, clone(value));
    for (const [key, value] of checkpoint.flow_clocks ?? []) host.flowClocks.set(key, clone(value));
    for (const [key, value] of checkpoint.invocations) host.invocations.set(key, clone(value));
    for (const value of checkpoint.dispatch_claims) host.dispatchClaims.add(value);
    for (const [key, value] of checkpoint.gated_dispatch_claims) host.gatedDispatchClaims.set(key, clone(value));
    for (const [key, value] of checkpoint.pending) host.pending.set(key, clone(value));
    host.retainedFlowDependencies(undefined, true);
    return host;
  }

  async dispatch<T>(organization: string, instanceId: string, permitId: string, nativeRequest: Row, connector: BoundConnector<T>, failurePoint: string | null = null): Promise<Row> {
    return this.dispatchPermitted(organization, instanceId, permitId, nativeRequest, connector, undefined, failurePoint) as Promise<Row>;
  }

  static publicFailure(): Row { return { status: 'REFUSED', code: 'OPERATION_NOT_ALLOWED' }; }

  async dispatchPermitted<T>(organization: string, instanceId: string, permitId: string, nativeRequest: Row, connector: BoundConnector<T> | ((request: Row) => Promise<T> | T), authorizationReference?: Row, failurePoint: string | null = null, flowInput?: Row, responseRequests?: FlowReaders): Promise<T> {
    if (this.committingHoldings) throw new AdmissionError('OPERATION_NOT_ALLOWED');
    const suppliedFlow = flowInput === undefined ? undefined : clone(flowInput);
    const supplied = clone(nativeRequest), suppliedAuthorization = authorizationReference === undefined ? undefined : clone(authorizationReference);
    const callable = typeof connector === 'function', invoke = callable ? connector : connector?.invoke;
    const metadata = callable ? null : { id: connector?.id, version: connector?.version, binding_digest: connector?.binding_digest };
    const validConnector = callable || connector !== null && typeof connector === 'object' && same(Object.keys(connector).sort(), ['binding_digest', 'id', 'invoke', 'version']) && typeof invoke === 'function' && shape('lifecycle.schema.json', 'connector', metadata);
    return this.enqueue(async () => {
      if (suppliedFlow !== undefined) admitFlowInput(suppliedFlow);
      const readers = responseRequests ?? (suppliedFlow ? [suppliedFlow] : []);
      this.guardFlowReaders(organization, readers);
      const protect = (result: Row): T => { try { this.guardFlowReaders(organization, readers); return clone(result) as T; } catch (error) { if (error instanceof AdmissionError) return SingleProcessReferenceHost.publicFailure() as T; throw error; } };
      const root = this.roots.get(rootKey(organization, instanceId));
      if (!root) throw new Error('Instance is not installed');
      const protectedRoute = this.flowRoutes.get(canonical([organization, supplied.interface, supplied.operation]));
      const installedProtected = [...this.flows.keys()].some(key => key.startsWith(canonical([organization]).slice(0, -1) + ','));
      if (installedProtected && !protectedRoute || protectedRoute && !suppliedFlow) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
      if (suppliedFlow) { this.currentFlow(organization, suppliedFlow); if (!protectedRoute || suppliedFlow.event.kind !== 'EXPOSE') throw new AdmissionError('BINDING_MISMATCH'); }
      const retained = [...this.invocations.values()].find(row => row.organization === organization && row.instance_id === instanceId && row.permit_id === permitId);
      if (retained) {
        if (!same(retained.native_request, supplied) || !same(retained.connector, metadata) || suppliedAuthorization !== undefined && !same(retained.authorization, suppliedAuthorization)) throw new AdmissionError('BINDING_MISMATCH');
        return protect({ status: retained.status === 'ESTABLISHED' ? 'RETAINED_RESULT' : 'PENDING_RECONCILIATION', invocation: retained });
      }
      const permit = root.state.permits.find((row: Row) => row.permit_id === permitId);
      if (permit && !this.permitRegistriesCurrent(organization, root, permit)) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
      if (permit && this.pendingBlocks(organization, root, permit.occurrence.occurrence_id, this.permissionPartitions(organization, permit, []))) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
      const active = root.state.active.find((row: Row) => row.occurrence.occurrence_id === permit?.occurrence.occurrence_id);
      const superseded = root.state.permits.some((row: Row) => row.supersedes_permit_digest === permitId);
      const clocks = permit ? root.state.clocks.filter((row: Row) => row.source === permit.clock_source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1) : [];
      const latest = clocks.at(-1), now = latest?.status === 'AVAILABLE' ? latest.observed_time : null;
      if (root.state.status !== 'ACTIVE' || !permit || !active || active.status !== 'PERMITTED' || superseded || !same(permit.native_request, supplied) || !now || instant(now) >= instant(permit.expires_at)) throw new AdmissionError('BINDING_MISMATCH');
      if (recoveryPermitNeedsRenewal(root.state, permit)) throw new AdmissionError('PREREQUISITE_MISSING');
      for (const revision of permit.budget_revisions ?? []) {
        const registry = this.budgets.get(budgetKey(organization, revision.registry_digest));
        if (!registry) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
        if (registry.state.core.configuration.recovery && registry.state.core.last_clock !== null && instant(now) < instant(registry.state.core.last_clock)) throw new AdmissionError('CLOCK_INVALID');
        if (registry.state.core.configuration.recovery && reservationPermissionReasons(registry.state.core, revision.reservation_id, now, this.selectedPin).length) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
      }
      const definition = JSON.parse(root.deploy_request).definition;
      const gated = Boolean(definition.steps.find((row: Row) => row.id === permit.occurrence.step_id)?.dispatch_gate);
      if (gated) {
        const authorization = authorizationHead(root.state, permitId);
        const retainedInvocation = Boolean(authorization?.authorization_fence.holdings?.length || permit.authority_basis?.assessment_bases?.length || authorization?.authorization_fence.flows?.length);
        if (!authorization || (retainedInvocation ? suppliedAuthorization !== undefined && !same(authorization, suppliedAuthorization) : !suppliedAuthorization || !same(authorization, suppliedAuthorization)) || !same(authorization.native_request, supplied) || authorization.connector.binding_digest !== digest('connector-binding', { id: authorization.connector.id, version: authorization.connector.version }) || latest?.status !== 'AVAILABLE' || instant(latest.observed_time) < instant(authorization.authorization_fence.checked_at) || instant(latest.observed_time) >= instant(authorization.expires_at)) throw new AdmissionError('BINDING_MISMATCH');
        const evaluation = latestAuthorizationEvaluation(root.state, permitId);
        if (evaluation?.disposition !== 'AUTHORIZED' || evaluation.authorization_digest !== authorization.authorization_digest) throw new AdmissionError('PREREQUISITE_MISSING');
        if (dispatchPermissionConsumed(root.state, permitId)) throw new AdmissionError('PREREQUISITE_MISSING');
        if (!validConnector || callable) throw new AdmissionError('INPUT_INVALID');
        if (!same(metadata, authorization.connector)) throw new AdmissionError('BINDING_MISMATCH');
        if (retainedInvocation) {
          for (const row of authorization.authorization_fence.holdings ?? []) {
            const stored = this.holdings.get(budgetKey(organization, row.configuration_digest));
            if (!stored || stored.state_digest !== row.state_digest || stored.state.core.revision !== row.revision || stored.state.records.length >= 64 || instant(now) < instant(stored.state.core.last_clock)) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
            const grant = stored.state.core.grants.find((grant: Row) => grant.id === row.grant_id);
            if (!grant || grant.actor !== row.actor || grant.permission !== row.permission || grant.valid_until !== row.valid_until || !activeHolding(grant, now)) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
          }
          let flowResult: Row | undefined, installedFlow: Row | undefined;
          if (authorization.authorization_fence.flows?.length) {
            if (!suppliedFlow || !protectedRoute) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
            installedFlow = this.currentFlow(organization, suppliedFlow);
            const projected = suppliedFlow.event.payload.authority_projection, expanded = clone(projected); expanded.flow_bases[0].state = clone(installedFlow.state);
            this.authenticateFlowAuthority(organization, installedFlow.configuration, expanded);
            const latestAuthority = evaluation.authority_input, requirement = flowRequirements(expanded)[0];
            if (!same(expanded, latestAuthority) || requirement.id !== suppliedFlow.event.payload.requirement_id || requirement.recipient_field !== protectedRoute.recipient_field || requirement.channel !== protectedRoute.channel || requirement.purpose !== protectedRoute.purpose || !same(protectedRoute.connector, metadata) || !same({ interface: expanded.proposal.interface, operation: expanded.proposal.operation, fields: expanded.proposal.fields }, supplied)) throw new AdmissionError('BINDING_MISMATCH');
            flowResult = flowStep(suppliedFlow, this.selectedPin);
            if (flowResult.status !== 'TRANSITION' || flowResult.replay) throw new AdmissionError(flowResult.code ?? 'PREREQUISITE_MISSING');
          } else if (protectedRoute) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
          const claim = canonical([organization, instanceId, authorization.dispatch_intent_id]);
          if (this.gatedDispatchClaims.has(claim)) throw new AdmissionError('PREREQUISITE_MISSING');
          if (failurePoint === 'BEFORE_INTENT') return protect({ status: 'COMMIT_FAILED' });
          const intent: Row = { organization, instance_id: instanceId, permit_id: permitId, invocation_id: authorization.dispatch_intent_id, authorization: clone(authorization), holdings: clone(authorization.authorization_fence.holdings ?? []), native_request: clone(supplied), connector: clone(metadata), status: 'PENDING' };
          if (flowResult && installedFlow) { installedFlow.state = clone(flowResult.state); installedFlow.state_digest = flowResult.state_digest; intent.flow_receipt = clone(flowResult.receipt); intent.flow_receipt_digest = flowResult.receipt_digest; }
          this.invocations.set(claim, intent);
          this.gatedDispatchClaims.set(claim, { organization, instanceId, permitId, authorizationDigest: authorization.authorization_digest });
          if (failurePoint === 'AFTER_INTENT') return protect({ status: 'PENDING_RECONCILIATION', invocation: intent });
          this.committingHoldings = true;
          try {
            const result = await invoke!(clone(supplied));
            if (failurePoint === 'AFTER_INVOKE' || failurePoint === 'OUTCOME_WRITE') intent.status = 'UNCERTAIN';
            else { intent.status = 'ESTABLISHED'; intent.result = clone(result); }
          } catch { intent.status = 'UNCERTAIN'; }
          finally { this.committingHoldings = false; }
          return protect({ status: intent.status === 'ESTABLISHED' ? 'COMMITTED' : 'PENDING_RECONCILIATION', invocation: intent });
        }
        if (protectedRoute) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
        const claim = canonical([organization, instanceId, authorization.dispatch_intent_id]);
        if (this.gatedDispatchClaims.has(claim) || root.state.dispatches.some((row: Row) => row.authorization_digest === authorization.authorization_digest)) throw new AdmissionError('PREREQUISITE_MISSING');
        for (const prior of this.gatedDispatchClaims.values()) if (prior.organization === organization && prior.instanceId === instanceId && prior.permitId === permitId) {
          const observations = root.state.dispatches.filter((row: Row) => row.authorization_digest === prior.authorizationDigest);
          if (!observations.length || observations.some((row: Row) => row.attempt.status !== 'NOT_SENT' || row.acknowledgement.status === 'ACCEPTED')) throw new AdmissionError('PREREQUISITE_MISSING');
        }
        this.gatedDispatchClaims.set(claim, { organization, instanceId, permitId, authorizationDigest: authorization.authorization_digest });
      } else {
        if (protectedRoute) throw new AdmissionError('EVIDENCE_UNAVAILABLE');
        if (!validConnector) throw new AdmissionError('INPUT_INVALID');
        const claim = canonical([organization, instanceId, permitId]);
        if (this.dispatchClaims.has(claim)) throw new AdmissionError('PREREQUISITE_MISSING');
        this.dispatchClaims.add(claim);
      }
      return invoke!(clone(supplied));
    });
  }
}
