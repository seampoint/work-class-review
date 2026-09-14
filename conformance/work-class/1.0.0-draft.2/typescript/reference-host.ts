import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { deploy, stateDigest, step } from './lifecycle.ts';
import { stateAdmission as reservationStateAdmission } from './reservations.ts';
import { requireShape } from './schema.ts';
import { instant } from './time.ts';
import { same } from './values.ts';
import type { RecordValue as Row } from './values.ts';

const clone = <T>(value: T): T => structuredClone(value);

export type BudgetRoot = {
  registry_digest: string;
  affected_anchors: string[];
  state: Row;
  state_digest: string;
};

type StoredBudget = BudgetRoot & { state_bytes: string };
type EventLogEntry = { event_digest: string; transaction_digest: string; event: string; request: string; response: string };
type StoredRoot = {
  deploy_request: string;
  state: Row;
  state_bytes: string;
  state_digest: string;
  registry_digests: string[];
  installation_budget_roots: string;
  event_log: Map<string, EventLogEntry>;
};

function budgetKey(organization: string, registryDigest: string): string { return canonical([organization, registryDigest]); }
function rootKey(organization: string, instanceId: string): string { return canonical([organization, instanceId]); }

export class SingleProcessReferenceHost {
  private readonly selectedPin: string;
  private readonly roots = new Map<string, StoredRoot>();
  private readonly budgets = new Map<string, StoredBudget>();
  private readonly dispatchClaims = new Set<string>();
  private queue: Promise<void> = Promise.resolve();

  constructor(selectedPin: string) { this.selectedPin = selectedPin; }

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
      for (const budget of admittedBudgets) this.budgets.set(budgetKey(organization, budget.registry_digest), budget);
      this.roots.set(key, nextRoot);
      return result;
    });
  }

  private budgetSnapshot(organization: string, root: StoredRoot): BudgetRoot[] {
    return root.registry_digests.map(registryDigest => {
      const row = this.budgets.get(budgetKey(organization, registryDigest));
      if (!row) throw new Error('Missing authoritative budget root');
      return { registry_digest: row.registry_digest, affected_anchors: clone(row.affected_anchors), state: clone(row.state), state_digest: row.state_digest };
    });
  }

  async snapshot(organization: string, instanceId: string): Promise<{ state: Row; state_digest: string; budget_states: BudgetRoot[] }> {
    return this.enqueue(() => {
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

  async submit(organization: string, request: Row, failureReference: string | null = null): Promise<Row> {
    const supplied = clone(request);
    return this.enqueue(() => {
      const key = rootKey(organization, supplied.state.instance_id);
      const root = this.roots.get(key);
      if (!root) throw new Error('Instance is not installed');
      const event = supplied.event as Row, retained = root.event_log.get(event.event_id);
      if (retained && retained.event !== canonical(event)) return this.statefulRefusal(organization, root, supplied, 'REPLAY_CONFLICT');
      if (supplied.state_digest !== root.state_digest || canonical(supplied.state) !== root.state_bytes) return this.statefulRefusal(organization, root, supplied, 'REVISION_CONFLICT');
      if (retained) {
        const replay = step(supplied, this.selectedPin);
        if (replay.status !== 'STEP' || replay.replay !== true) throw new Error('Consumer did not return the retained exact replay');
        return { transition: clone(replay), host_commit: null };
      }
      const budgetInputs = ['PROPOSE', 'EFFECT_OBSERVED'].includes(event.kind) ? event.budget_inputs : [];
      for (const input of budgetInputs as Row[]) {
        const budget = this.budgets.get(budgetKey(organization, input.registry_digest));
        if (!budget || input.request.state_digest !== budget.state_digest || canonical(input.request.state) !== budget.state_bytes) return this.statefulRefusal(organization, root, supplied, 'REVISION_CONFLICT');
      }
      const transition = step(supplied, this.selectedPin);
      if (transition.status !== 'STEP') return clone(transition);
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
      for (const admitted of admittedBudgets) this.budgets.set(budgetKey(organization, admitted.registry_digest), admitted);
      this.roots.set(key, nextRoot);
      return { transition: clone(transition), host_commit: committed };
    });
  }

  async dispatchPermitted<T>(organization: string, instanceId: string, permitId: string, nativeRequest: Row, connector: (request: Row) => Promise<T> | T): Promise<T> {
    const supplied = clone(nativeRequest);
    return this.enqueue(async () => {
      const root = this.roots.get(rootKey(organization, instanceId));
      if (!root) throw new Error('Instance is not installed');
      const permit = root.state.permits.find((row: Row) => row.permit_id === permitId);
      const active = root.state.active.find((row: Row) => row.occurrence.occurrence_id === permit?.occurrence.occurrence_id);
      const superseded = root.state.permits.some((row: Row) => row.supersedes_permit_digest === permitId);
      const clocks = permit ? root.state.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === permit.clock_source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1) : [];
      const now = clocks.at(-1)?.observed_time;
      if (!permit || !active || active.status !== 'PERMITTED' || superseded || !same(permit.native_request, supplied) || !now || instant(now) >= instant(permit.expires_at)) throw new AdmissionError('BINDING_MISMATCH');
      const claim = canonical([organization, instanceId, permitId]);
      if (this.dispatchClaims.has(claim)) throw new AdmissionError('PREREQUISITE_MISSING');
      this.dispatchClaims.add(claim);
      return connector(clone(supplied));
    });
  }
}
