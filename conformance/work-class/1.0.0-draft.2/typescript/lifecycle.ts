import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { instant, instantText } from './time.ts';
import { requireShape, shape, VERSION } from './schema.ts';
import { same, typed } from './values.ts';
import type { RecordValue as Row, Types } from './values.ts';
import { PROFILE_ROLES, validateWorkClass } from './work-class.ts';
import { correspondenceCode } from './evidence.ts';
import { evaluateAuthority } from './authority.ts';
import { aggregateStep } from './reservations.ts';

const clone = <T>(value: T): T => structuredClone(value);
const fail = (code: string, path = ''): never => { throw new AdmissionError(code, path); };
const sortStrings = (values: string[]): string[] => [...new Set(values)].sort(byteCompare);
const wholeSecond = (value: string): bigint => { try { return instant(value); } catch { return fail('INPUT_INVALID'); } };
const seconds = (value: string, unit: string): bigint => BigInt(value) * BigInt(unit === 'SECOND' ? 1 : unit === 'MINUTE' ? 60 : unit === 'HOUR' ? 3600 : 86400) * 1_000_000_000n;

export function occurrence(definitionDigest: string, instanceId: string, stepId: string, ordinal: string, predecessors: string[], enclosing: Row[], objectKey: Row | null, pin: string): Row {
  const subject = { specification_pin: pin, work_class_digest: definitionDigest, instance_id: instanceId, step_id: stepId, ordinal, predecessor_occurrence_ids: predecessors, enclosing, object_key: objectKey };
  return { occurrence_id: digest('occurrence', subject), ...subject };
}

export function stateDigest(state: Row): string {
  const projection = clone(state);
  for (const replay of projection.replays) delete replay.transaction_digest;
  return digest('work-state', projection);
}

function coreDigest(state: Row): string {
  const projection = clone(state); projection.receipts = []; projection.replays = [];
  return digest('work-state-core', projection);
}

function omitted<T extends Row>(value: T, key: string): Row { const result = clone(value); delete result[key]; return result; }
function eventDigest(event: Row): string { return digest('runtime-event', event); }
function permitDigest(permit: Row): string { return digest('permit', omitted(permit, 'permit_id')); }
function decisionDigest(decision: Row): string { return digest('decision-receipt', omitted(decision, 'decision_id')); }
function sortedRows(rows: Row[], projection: (row: Row) => unknown): Row[] { return rows.sort((a, b) => byteCompare(canonical(projection(a)), canonical(projection(b)))); }
function sortStateDeadlines(state: Row): void {
  const occurrences = [...state.active, ...state.completed];
  sortedRows(state.deadlines, (row: Row) => {
    const occurrenceRow = occurrences.find((candidate: Row) => candidate.occurrence.occurrence_id === row.occurrence_id)?.occurrence;
    if (!occurrenceRow) fail('STATE_INVALID');
    return [row.due, occurrenceRow, row.deadline_id];
  });
}

function budgetEcho(event: Row): Row[] {
  const inputs = event && ['PROPOSE', 'EFFECT_OBSERVED'].includes(event.kind) && Array.isArray(event.budget_inputs) ? event.budget_inputs : [];
  const echoes = (inputs ?? []).map((row: Row) => ({ registry_digest: row.registry_digest, affected_anchors: clone(row.affected_anchors), state: clone(row.request.state), state_digest: row.request.state_digest }));
  return [...new Map(echoes.map((row: Row) => [canonical(row), row])).values()];
}

function permitBudgetResultDigest(row: Row): string {
  if (!row || !row.result || typeof row.result.receipt_digest !== 'string') fail('STATE_INVALID');
  return row.result.receipt_digest;
}

function permitBudgetRevisionMatches(revision: Row, result: Row): boolean {
  const transition = result?.result;
  const reservation = transition?.receipt?.reservation;
  const registryRevision = transition?.state?.core?.revision;
  return !!transition && typeof registryRevision === 'string' && typeof reservation === 'string'
    && revision.registry_digest === result.registry_digest
    && same(revision.affected_anchors, result.affected_anchors)
    && revision.revision === registryRevision
    && revision.reservation_id === reservation
    && revision.receipt_digest === permitBudgetResultDigest(result);
}

function validatePermitChainsAndBudgetLinks(state: Row, definition: Row, occurrenceRows: Row[]): void {
  const occurrenceById = new Map<string, Row>(occurrenceRows.map((row: Row) => [row.occurrence.occurrence_id, row.occurrence]));
  const permitsById = new Map<string, Row>();
  const permitsByOccurrence = new Map<string, Row[]>();
  for (const permit of state.permits as Row[]) {
    if (permitsById.has(permit.permit_id)) fail('STATE_INVALID');
    const retainedOccurrence = occurrenceById.get(permit.occurrence.occurrence_id);
    if (!retainedOccurrence || !same(permit.occurrence, retainedOccurrence)) fail('STATE_INVALID');
    permitsById.set(permit.permit_id, permit);
    const rows = permitsByOccurrence.get(permit.occurrence.occurrence_id) ?? [];
    rows.push(permit); permitsByOccurrence.set(permit.occurrence.occurrence_id, rows);
  }

  const replayByEvent = new Map<string, Row>();
  const receiptByEvent = new Map<string, Row>();
  for (const replay of state.replays as Row[]) {
    if (replayByEvent.has(replay.event_id)) fail('STATE_INVALID');
    replayByEvent.set(replay.event_id, replay);
  }
  for (const receipt of state.receipts as Row[]) {
    if (receiptByEvent.has(receipt.event_id)) fail('STATE_INVALID');
    receiptByEvent.set(receipt.event_id, receipt);
  }

  const proposalByPermit = new Map<string, Row>();
  const proposalSequence = new Map<string, bigint>();
  for (const proposal of state.proposals as Row[]) {
    const replay = replayByEvent.get(proposal.event_id);
    const receipt = receiptByEvent.get(proposal.event_id);
    if (!replay || !receipt || receipt.event_kind !== 'PROPOSE' || replay.event_digest !== proposal.event_digest) fail('STATE_INVALID');
    const retainedReplay = replay!, retainedReceipt = receipt!;
    if (retainedReplay.decision.event_kind !== 'PROPOSE' || retainedReplay.decision.event_id !== proposal.event_id || retainedReplay.decision.event_digest !== proposal.event_digest) fail('STATE_INVALID');
    if (!same(retainedReplay.decision.reservation_receipt_digests, proposal.reservation_receipt_digests) || retainedReplay.decision.permit_digest !== proposal.permit_digest || retainedReplay.decision.authority_result_digest !== proposal.authority_result_digest) fail('STATE_INVALID');
    proposalSequence.set(proposal.event_id, BigInt(retainedReceipt.sequence));
    if (proposal.permit_digest !== null) {
      if (proposalByPermit.has(proposal.permit_digest)) fail('STATE_INVALID');
      proposalByPermit.set(proposal.permit_digest, proposal);
    }
    const budgetResults = retainedReplay.budget_results as Row[];
    const expectedReceiptDigests = budgetResults.map(permitBudgetResultDigest).sort(byteCompare);
    if (!same(proposal.reservation_receipt_digests, expectedReceiptDigests)) fail('STATE_INVALID');
    if (proposal.disposition === 'WITHHELD' && retainedReplay.permit !== null) fail('STATE_INVALID');
  }

  const successorByPrior = new Map<string, string>();
  for (const permit of state.permits as Row[]) {
    const proposal = proposalByPermit.get(permit.permit_id);
    if (!proposal || proposal.disposition !== 'PERMITTED' || proposal.occurrence_id !== permit.occurrence.occurrence_id || proposal.proposal_digest !== permit.proposal_digest || proposal.prior_permit_digest !== permit.supersedes_permit_digest || proposal.authority_result_digest !== permit.authority_result_digest) fail('STATE_INVALID');
    const retainedProposal = proposal!;
    const replay = replayByEvent.get(retainedProposal.event_id)!;
    if (replay.permit === null || !same(replay.permit, permit)) fail('STATE_INVALID');
    const budgetResults = replay.budget_results as Row[];
    if (permit.budget_revisions.length !== budgetResults.length || permit.budget_revisions.some((revision: Row, index: number) => !permitBudgetRevisionMatches(revision, budgetResults[index]))) fail('STATE_INVALID');
    const priorId = permit.supersedes_permit_digest;
    if (priorId === null) continue;
    const prior = permitsById.get(priorId);
    if (!prior || priorId === permit.permit_id || prior.occurrence.occurrence_id !== permit.occurrence.occurrence_id || successorByPrior.has(priorId)) fail('STATE_INVALID');
    const priorProposal = proposalByPermit.get(prior!.permit_id);
    if (!priorProposal || proposalSequence.get(priorProposal.event_id)! >= proposalSequence.get(retainedProposal.event_id)!) fail('STATE_INVALID');
    successorByPrior.set(priorId, permit.permit_id);
  }

  for (const [occurrenceId, permits] of permitsByOccurrence) {
    const roots = permits.filter((permit: Row) => permit.supersedes_permit_digest === null);
    const heads = permits.filter((permit: Row) => !successorByPrior.has(permit.permit_id));
    if (roots.length !== 1 || heads.length !== 1) fail('STATE_INVALID');
    const visited = new Set<string>();
    let current: Row | undefined = roots[0];
    while (current) {
      if (visited.has(current.permit_id)) fail('STATE_INVALID');
      visited.add(current.permit_id);
      const successor = successorByPrior.get(current.permit_id);
      if (!successor) break;
      const next = permitsById.get(successor);
      if (!next || next.occurrence.occurrence_id !== occurrenceId) fail('STATE_INVALID');
      current = next;
    }
    if (visited.size !== permits.length) fail('STATE_INVALID');
  }
  for (const active of state.active as Row[]) {
    if (active.status !== 'PERMITTED') continue;
    const permits = permitsByOccurrence.get(active.occurrence.occurrence_id) ?? [];
    const heads = permits.filter((permit: Row) => !successorByPrior.has(permit.permit_id));
    if (heads.length !== 1) fail('STATE_INVALID');
  }

  const completedIds = new Set<string>(state.completed.map((row: Row) => row.occurrence.occurrence_id));
  const isAncestor = (ancestorId: string, descendantId: string): boolean => {
    const pending = [...(occurrenceById.get(descendantId)?.predecessor_occurrence_ids ?? [])], visited = new Set<string>();
    while (pending.length) {
      const current = pending.pop()!;
      if (current === ancestorId) return true;
      if (visited.has(current)) continue;
      visited.add(current);
      pending.push(...(occurrenceById.get(current)?.predecessor_occurrence_ids ?? []));
    }
    return false;
  };
  const completedOutcome = (occurrenceId: string, evidenceDigest?: string): Row | null => {
    const matches = (state.outcomes as Row[]).filter((outcome: Row) => outcome.kind === 'GOVERNED' && outcome.permit_digest !== null && outcome.classification === 'MATCHED' && state.permits.some((permit: Row) => permit.permit_id === outcome.permit_digest && permit.occurrence.occurrence_id === occurrenceId) && (evidenceDigest === undefined || digest('native-evidence', outcome.native_evidence) === evidenceDigest));
    return matches.length === 1 ? matches[0] : null;
  };
  const authorityActs = (permit: Row, digestValue: string): Row[] => permit.authority_act_bases.filter((row: Row) => row.act_digest === digestValue);
  const fieldValue = (fields: Row[], name: string): Row | null => {
    const matches = fields.filter((row: Row) => row.name === name);
    return matches.length === 1 ? matches[0].value : null;
  };
  const sortedBasisIds = (rows: Row[], field: string): string[] => rows.map((row: Row) => row[field]).sort(byteCompare);

  for (const permit of state.permits as Row[]) {
    const step = definition.steps.find((row: Row) => row.id === permit.occurrence.step_id);
    if (!step) fail('STATE_INVALID');
    const priorBindings = (step!.prior_effect_bindings ?? []) as Row[];
    const separationRequirements = (step!.prior_actor_separations ?? []) as Row[];
    const priorBases = permit.prior_effect_bases as Row[], separationBases = permit.separation_bases as Row[];
    if (!same(sortedBasisIds(priorBases, 'binding_id'), priorBindings.map((row: Row) => row.id).sort(byteCompare)) || !same(sortedBasisIds(separationBases, 'requirement_id'), separationRequirements.map((row: Row) => row.id).sort(byteCompare))) fail('STATE_INVALID');
    for (const basis of priorBases) {
      const requirement = priorBindings.find((row: Row) => row.id === basis.binding_id), source = occurrenceById.get(basis.source_occurrence_id), targetValue = fieldValue(permit.native_request.fields, basis.target_field), sourceOutcome = completedOutcome(basis.source_occurrence_id, basis.source_native_evidence_digest), sourcePermit = basis.source_permit_digest ? permitsById.get(basis.source_permit_digest) : null;
      if (!requirement || !source || !completedIds.has(basis.source_occurrence_id) || !isAncestor(basis.source_occurrence_id, permit.occurrence.occurrence_id) || !sourceOutcome || !sourcePermit || sourcePermit.occurrence.occurrence_id !== source.occurrence_id || sourceOutcome.permit_digest !== sourcePermit.permit_id || targetValue === null || !same(targetValue, basis.value) || requirement.source_step_id !== source.step_id || requirement.source_evidence_field !== basis.source_field || requirement.target_request_field !== basis.target_field || fieldValue(sourceOutcome.native_evidence.actual_fields, basis.source_field) === null || !same(fieldValue(sourceOutcome.native_evidence.actual_fields, basis.source_field), basis.value)) fail('STATE_INVALID');
    }
    for (const basis of separationBases) {
      const requirement = separationRequirements.find((row: Row) => row.id === basis.requirement_id), source = occurrenceById.get(basis.prior_occurrence_id), currentActs = authorityActs(permit, basis.current_act.act_digest), sourceOutcome = completedOutcome(basis.prior_occurrence_id), sourcePermit = sourceOutcome ? permitsById.get(sourceOutcome.permit_digest) : null, priorActs = sourcePermit ? authorityActs(sourcePermit, basis.prior_act.act_digest) : [];
      if (!requirement || !source || !completedIds.has(basis.prior_occurrence_id) || !isAncestor(basis.prior_occurrence_id, permit.occurrence.occurrence_id) || basis.current_occurrence_id !== permit.occurrence.occurrence_id || basis.relation !== requirement.relation || basis.prior_act.act_digest !== digest('authority-act', basis.prior_act.act) || basis.current_act.act_digest !== digest('authority-act', basis.current_act.act) || currentActs.length !== 1 || priorActs.length !== 1 || !sourceOutcome || !sourcePermit || sourcePermit.occurrence.occurrence_id !== source.occurrence_id || basis.prior_act.act.actor === basis.current_act.act.actor) fail('STATE_INVALID');
    }
  }
}

function positiveNatural(value: unknown): bigint {
  if (typeof value !== 'string' || !/^[1-9][0-9]*$/.test(value)) fail('STATE_INVALID');
  return BigInt(value as string);
}

function stateSortedIds(values: unknown[], max = 4096): void {
  if (values.length > max || values.some((value: unknown) => typeof value !== 'string')) fail('STATE_INVALID');
  for (let index = 1; index < values.length; index++) if (byteCompare(values[index - 1] as string, values[index] as string) >= 0) fail('STATE_INVALID');
}

function stateSortedRows(rows: Row[], projection: (row: Row) => unknown): void {
  if (!same(rows, [...rows].sort((a: Row, b: Row) => byteCompare(canonical(projection(a)), canonical(projection(b)))))) fail('STATE_INVALID');
}

function lifecycleRegion(definition: Row, head: string, join: string): Set<string> {
  const result = new Set<string>(), pending = [head];
  const outgoing = new Map<string, string[]>();
  for (const relationship of definition.relationships as Row[]) outgoing.set(relationship.from, [...(outgoing.get(relationship.from) ?? []), relationship.to]);
  for (const block of definition.parallel_blocks as Row[]) for (const branch of block.branches as Row[]) outgoing.set(block.split_step_id, [...(outgoing.get(block.split_step_id) ?? []), branch.head_step_id]);
  for (const fanout of definition.fanouts as Row[]) outgoing.set(fanout.expand_step_id, [...(outgoing.get(fanout.expand_step_id) ?? []), fanout.region_head_step_id]);
  while (pending.length) {
    const current = pending.pop()!;
    if (current === join || result.has(current)) continue;
    result.add(current);
    pending.push(...(outgoing.get(current) ?? []));
  }
  return result;
}

function lifecycleOccurrenceOwner(definition: Row, occurrenceRow: Row, owner: Row): boolean {
  const segment = [...occurrenceRow.enclosing].reverse().find((candidate: Row) =>
    owner.kind === 'PARALLEL_BRANCH'
      ? candidate.kind === 'BRANCH' && candidate.construct_id === owner.construct_id && candidate.pass === owner.pass && candidate.branch_id === owner.branch_id && candidate.object_key === null
      : candidate.kind === 'FANOUT' && candidate.construct_id === owner.construct_id && candidate.pass === owner.pass && candidate.branch_id === null && same(candidate.object_key, owner.object_key));
  return Boolean(segment);
}

function lifecycleRepresentativeOccurrence(state: Row, obligation: Row): Row | null {
  if (obligation.expected_occurrence_id) return [...state.active, ...state.completed].find((row: Row) => row.occurrence.occurrence_id === obligation.expected_occurrence_id)?.occurrence ?? null;
  if (obligation.completion_basis?.kind === 'DIRECT_EVENT') return [...state.active, ...state.completed].find((row: Row) => row.occurrence.occurrence_id === obligation.completion_basis.occurrence_id)?.occurrence ?? null;
  for (const row of [...state.active, ...state.completed]) if (lifecycleOccurrenceOwner({ steps: [], relationships: [] }, row.occurrence, obligation)) return row.occurrence;
  return null;
}

function lifecycleOccurrenceById(rows: Row[], id: string): Row | null {
  return rows.find((row: Row) => row.occurrence.occurrence_id === id)?.occurrence ?? null;
}

function lifecycleReceiptByEventDigest(state: Row, eventDigestValue: string): Row | null {
  return state.receipts.find((row: Row) => row.event_digest === eventDigestValue) ?? null;
}

function lifecycleDisputedOccurrenceIds(state: Row): Set<string> {
  const result = new Set<string>(state.active.filter((row: Row) => row.status === 'BLOCKED_DISPUTE').map((row: Row) => row.occurrence.occurrence_id));
  for (const outcome of state.outcomes) if (outcome.disputed && outcome.kind === 'GOVERNED') {
    const permit = state.permits.find((row: Row) => row.permit_id === outcome.permit_digest);
    if (permit) result.add(permit.occurrence.occurrence_id);
  }
  return result;
}

function lifecycleCompletionFrontier(state: Row, obligationIds: string[], seen = new Set<string>()): string[] {
  const frontier: string[] = [];
  for (const id of obligationIds) {
    if (seen.has(id)) fail('STATE_INVALID');
    const obligation = state.obligations.find((row: Row) => row.obligation_id === id);
    if (!obligation || !['DISCHARGED', 'JOINED'].includes(obligation.status) || !obligation.completion_basis) fail('STATE_INVALID');
    const path = new Set(seen); path.add(id);
    if (obligation.completion_basis.kind === 'DIRECT_EVENT') frontier.push(obligation.completion_basis.occurrence_id);
    else if (obligation.completion_basis.kind === 'CHILD_PASS') {
      const childIds = obligation.completion_basis.child_pass.obligation_ids as string[];
      if (childIds.some((childId: string) => !state.obligations.some((row: Row) => row.obligation_id === childId && row.status === 'JOINED'))) fail('STATE_INVALID');
      frontier.push(...lifecycleCompletionFrontier(state, childIds, path));
    } else fail('STATE_INVALID');
  }
  return sortStrings(frontier);
}

function lifecycleValidateChildPass(state: Row, definition: Row, childPass: Row, obligationById: Map<string, Row>): Row[] {
  if (!['PARALLEL', 'FANOUT'].includes(childPass.kind) || positiveNatural(childPass.pass) <= 0n) fail('STATE_INVALID');
  if (childPass.obligation_ids.length > 1024 || new Set(childPass.obligation_ids).size !== childPass.obligation_ids.length) fail('STATE_INVALID');
  // LIFE-019: "child-pass obligation IDs" use raw UTF-8 order; the fan-out pass row keeps source order.
  stateSortedIds(childPass.obligation_ids, 1024);
  const children = childPass.obligation_ids.map((id: string) => obligationById.get(id));
  if (children.some((row: Row | undefined) => !row)) fail('STATE_INVALID');
  const exact = children as Row[];
  const expectedKind = childPass.kind === 'PARALLEL' ? 'PARALLEL_BRANCH' : 'FANOUT_OBJECT';
  if (exact.some((row: Row) => row.kind !== expectedKind || row.construct_id !== childPass.construct_id || row.pass !== childPass.pass)) fail('STATE_INVALID');
  if (childPass.kind === 'PARALLEL') {
    const block = definition.parallel_blocks.find((row: Row) => row.id === childPass.construct_id);
    if (!block || exact.length !== block.branches.length || new Set(exact.map((row: Row) => row.branch_id)).size !== exact.length || block.branches.some((branch: Row) => !exact.some((row: Row) => row.branch_id === branch.id))) fail('STATE_INVALID');
    const source = exact[0].source_occurrence_ids;
    if (exact.some((row: Row) => !same(row.source_occurrence_ids, source))) fail('STATE_INVALID');
  } else {
    // Each outer prefix restarts the same fan-out at pass 1, so the expand occurrence's enclosing
    // path, not the pass number alone, identifies the pass the reference names.
    const pass = state.fanout_passes.find((row: Row) => row.fanout_id === childPass.construct_id && row.pass === childPass.pass
      && same([...state.active, ...state.completed].find((item: Row) => item.occurrence.occurrence_id === row.expand_occurrence_id)?.occurrence.enclosing ?? null, childPass.outer_enclosing));
    if (!pass || !same(sortStrings([...pass.obligation_ids]), childPass.obligation_ids)) fail('STATE_INVALID');
  }
  for (const child of exact) {
    const representative = lifecycleRepresentativeOccurrence(state, child);
    if (!representative) fail('STATE_INVALID');
    const occurrenceRow = representative as Row;
    const ownerIndex = occurrenceRow.enclosing.findIndex((segment: Row) => lifecycleOccurrenceOwner(definition, { ...occurrenceRow, enclosing: [segment] }, child));
    if (ownerIndex < 0 || !same(occurrenceRow.enclosing.slice(0, ownerIndex), childPass.outer_enclosing)) fail('STATE_INVALID');
  }
  return exact;
}

function lifecycleValidateObligations(state: Row, definition: Row, occurrences: Row[], receiptDigests: Set<string>): void {
  const byOccurrence = new Map<string, Row>(occurrences.map((row: Row) => [row.occurrence.occurrence_id, row.occurrence]));
  const byId = new Map<string, Row>();
  // LIFE-019 admits a completion-based DISPUTED obligation whose frontier intersects the
  // dependency-affected set, which LIFE-013 defines as the disputed occurrence and every transitive
  // descendant through predecessor lists, not the disputed occurrence alone.
  const dependencyAffected = lifecycleDisputedOccurrenceIds(state);
  for (let grew = true; grew;) {
    grew = false;
    for (const row of occurrences) if (!dependencyAffected.has(row.occurrence.occurrence_id) && row.occurrence.predecessor_occurrence_ids.some((id: string) => dependencyAffected.has(id))) { dependencyAffected.add(row.occurrence.occurrence_id); grew = true; }
  }
  for (const obligation of state.obligations as Row[]) {
    if (byId.has(obligation.obligation_id)) fail('STATE_INVALID');
    const core = {
      kind: obligation.kind,
      construct_id: obligation.construct_id,
      pass: obligation.pass,
      source_occurrence_ids: obligation.source_occurrence_ids,
      branch_id: obligation.branch_id,
      object_key: obligation.object_key,
      join_step_id: obligation.join_step_id,
    };
    if (obligation.obligation_id !== digest('obligation', core)) fail('STATE_INVALID');
    positiveNatural(obligation.pass);
    stateSortedIds(obligation.source_occurrence_ids, 4096);
    if (!obligation.source_occurrence_ids.length || obligation.source_occurrence_ids.some((id: string) => !byOccurrence.has(id))) fail('STATE_INVALID');
    if (obligation.source_occurrence_ids.some((id: string) => !(state.completed as Row[]).some((row: Row) => row.occurrence.occurrence_id === id))) fail('STATE_INVALID');
    if (!receiptDigests.has(obligation.creation_event_digest)) fail('STATE_INVALID');
    if (obligation.kind === 'PARALLEL_BRANCH') {
      const block = definition.parallel_blocks.find((row: Row) => row.id === obligation.construct_id);
      if (!block || block.join_step_id !== obligation.join_step_id || obligation.object_key !== null || !block.branches.some((row: Row) => row.id === obligation.branch_id)) fail('STATE_INVALID');
    } else if (obligation.kind === 'FANOUT_OBJECT') {
      const fanout = definition.fanouts.find((row: Row) => row.id === obligation.construct_id), types: Types = new Map(definition.types.map((row: Row) => [row.id, row]));
      if (!fanout || fanout.join_step_id !== obligation.join_step_id || obligation.branch_id !== null || obligation.object_key === null) fail('STATE_INVALID');
      typed(obligation.object_key, types);
      if (obligation.object_key.type_ref !== fanout.object_type_ref) fail('STATE_INVALID');
    } else fail('STATE_INVALID');
    // COMPOSITION: the branch or object head copies the structural frontier that its obligation
    // records as source_occurrence_ids, and both are immutable. An onward route moves the expected
    // occurrence, not the head, so the equality is checked against the head occurrence.
    const headStep = obligation.kind === 'PARALLEL_BRANCH'
      ? definition.parallel_blocks.find((row: Row) => row.id === obligation.construct_id)?.branches.find((row: Row) => row.id === obligation.branch_id)?.head_step_id
      : definition.fanouts.find((row: Row) => row.id === obligation.construct_id)?.region_head_step_id;
    if (!occurrences.some((row: Row) => row.occurrence.step_id === headStep && lifecycleOccurrenceOwner(definition, row.occurrence, obligation) && same(row.occurrence.predecessor_occurrence_ids, obligation.source_occurrence_ids))) fail('STATE_INVALID');
    byId.set(obligation.obligation_id, obligation);
  }

  const validatedChildPasses = new Map<string, Row[]>();
  const validateBasis = (obligation: Row): string[] => {
    const basis = obligation.completion_basis;
    if (!basis) fail('STATE_INVALID');
    const receipt = lifecycleReceiptByEventDigest(state, basis.event_digest);
    if (!receipt || !['EFFECT_OBSERVED', 'CLOCK'].includes(receipt.event_kind)) fail('STATE_INVALID');
    if (basis.kind === 'DIRECT_EVENT') {
      const completed = state.completed.find((row: Row) => row.occurrence.occurrence_id === basis.occurrence_id);
      if (!completed || completed.evidence_digest !== basis.evidence_digest || definition.steps.find((row: Row) => row.id === completed.occurrence.step_id)?.operation !== basis.operation) fail('STATE_INVALID');
      return [basis.occurrence_id];
    }
    if (basis.kind !== 'CHILD_PASS') fail('STATE_INVALID');
    const childPass = basis.child_pass;
    const key = canonical(childPass);
    const children = validatedChildPasses.get(key) ?? lifecycleValidateChildPass(state, definition, childPass, byId);
    validatedChildPasses.set(key, children);
    if (children.some((row: Row) => row.status !== 'JOINED')) fail('STATE_INVALID');
    return lifecycleCompletionFrontier(state, childPass.obligation_ids);
  };

  const waitingEdges = new Map<string, string[]>();
  for (const obligation of state.obligations as Row[]) {
    const representative = lifecycleRepresentativeOccurrence(state, obligation);
    if (obligation.status === 'OPEN' || obligation.status === 'BLOCKED') {
      if (!obligation.expected_occurrence_id || obligation.required_operation === null || obligation.waiting_on !== null || obligation.completion_basis !== null) fail('STATE_INVALID');
      const expected = byOccurrence.get(obligation.expected_occurrence_id), active = state.active.find((row: Row) => row.occurrence.occurrence_id === obligation.expected_occurrence_id);
      // PAR-001: "When an eligible direct route within the same branch or object region activates
      // one operation successor, the obligation replaces its expected occurrence and required
      // operation atomically." The expected occurrence therefore need not remain the region head,
      // and its predecessors need not equal the obligation's creation sources. Direct membership in
      // the branch or object region is what binds it: the occurrence's innermost branch or fan-out
      // segment is the obligation's own (COMPOSITION direct ownership). The required operation is
      // compared against that occurrence's own step.
      if (!expected || !active || !lifecycleOccurrenceOwner(definition, expected, obligation)) fail('STATE_INVALID');
      const innermost = [...expected!.enclosing].reverse().find((row: Row) => row.kind === 'BRANCH' || row.kind === 'FANOUT');
      if (!lifecycleOccurrenceOwner(definition, { enclosing: [innermost] }, obligation)) fail('STATE_INVALID');
      const targetStep = obligation.kind === 'PARALLEL_BRANCH'
        ? definition.parallel_blocks.find((row: Row) => row.id === obligation.construct_id)?.branches.find((row: Row) => row.id === obligation.branch_id)?.head_step_id
        : definition.fanouts.find((row: Row) => row.id === obligation.construct_id)?.region_head_step_id;
      const step = definition.steps.find((row: Row) => row.id === expected!.step_id);
      if (!targetStep || !step || obligation.required_operation !== step.operation || (obligation.status === 'OPEN' && active.status === 'BLOCKED_DISPUTE') || (obligation.status === 'BLOCKED' && active.status !== 'BLOCKED_DISPUTE')) fail('STATE_INVALID');
      if (!representative) fail('STATE_INVALID');
    } else if (obligation.status === 'WAITING') {
      if (obligation.expected_occurrence_id !== null || obligation.required_operation !== null || obligation.completion_basis !== null || !obligation.waiting_on) fail('STATE_INVALID');
      const children = lifecycleValidateChildPass(state, definition, obligation.waiting_on, byId);
      if (children.every((row: Row) => row.status === 'JOINED')) fail('STATE_INVALID');
      waitingEdges.set(obligation.obligation_id, children.map((row: Row) => row.obligation_id));
      if (!representative) fail('STATE_INVALID');
    } else if (obligation.status === 'DISCHARGED' || obligation.status === 'JOINED') {
      if (obligation.expected_occurrence_id !== null || obligation.required_operation !== null || obligation.waiting_on !== null) fail('STATE_INVALID');
      validateBasis(obligation);
    } else if (obligation.status === 'DISPUTED') {
      if (obligation.expected_occurrence_id !== null || obligation.required_operation !== null) fail('STATE_INVALID');
      if (obligation.waiting_on) {
        const children = lifecycleValidateChildPass(state, definition, obligation.waiting_on, byId);
        waitingEdges.set(obligation.obligation_id, children.map((row: Row) => row.obligation_id));
        if (!children.some((row: Row) => row.status === 'DISPUTED')) fail('STATE_INVALID');
      } else if (obligation.completion_basis) {
        const frontier = validateBasis(obligation);
        if (!frontier.some((id: string) => dependencyAffected.has(id))) fail('STATE_INVALID');
      } else fail('STATE_INVALID');
    } else fail('STATE_INVALID');
    if (obligation.status !== 'WAITING' && obligation.status !== 'DISPUTED' && obligation.waiting_on !== null) fail('STATE_INVALID');
  }
  const visit = (id: string, active = new Set<string>(), done = new Set<string>()): void => {
    if (active.has(id)) fail('STATE_INVALID');
    if (done.has(id)) return;
    active.add(id);
    for (const child of waitingEdges.get(id) ?? []) visit(child, active, done);
    active.delete(id); done.add(id);
  };
  for (const id of waitingEdges.keys()) visit(id);

  const groups = new Map<string, Row[]>();
  for (const obligation of state.obligations as Row[]) {
    const key = canonical([obligation.kind, obligation.construct_id, obligation.pass, obligation.source_occurrence_ids]);
    groups.set(key, [...(groups.get(key) ?? []), obligation]);
  }
  for (const rows of groups.values()) {
    if (rows.length && rows.every((row: Row) => row.status === 'DISCHARGED') && state.status === 'ACTIVE') fail('STATE_INVALID');
  }
}

function lifecycleValidateOccurrences(state: Row, definition: Row, pin: string, rows: Row[]): void {
  const byId = new Map<string, Row>();
  const steps = new Map<string, Row>(definition.steps.map((row: Row) => [row.id, row]));
  const types: Types = new Map(definition.types.map((row: Row) => [row.id, row]));
  const roots: Row[] = [];
  for (const retained of rows) {
    const occurrenceRow = retained.occurrence;
    if (byId.has(occurrenceRow.occurrence_id) || occurrenceRow.specification_pin !== pin || occurrenceRow.work_class_digest !== state.work_class_digest || occurrenceRow.instance_id !== state.instance_id || occurrenceRow.occurrence_id !== occurrence(state.work_class_digest, state.instance_id, occurrenceRow.step_id, occurrenceRow.ordinal, occurrenceRow.predecessor_occurrence_ids, occurrenceRow.enclosing, occurrenceRow.object_key, pin).occurrence_id) fail('STATE_INVALID');
    const step = steps.get(occurrenceRow.step_id);
    if (!step || !['OPERATION', 'FANOUT_EXPAND'].includes(step.kind)) fail('STATE_INVALID');
    positiveNatural(occurrenceRow.ordinal);
    stateSortedIds(occurrenceRow.predecessor_occurrence_ids, 4096);
    if (occurrenceRow.predecessor_occurrence_ids.includes(occurrenceRow.occurrence_id)) fail('STATE_INVALID');
    if (!occurrenceRow.predecessor_occurrence_ids.length) roots.push(occurrenceRow);
    const constructs = new Set<string>(), fanouts: Row[] = [];
    for (const segment of occurrenceRow.enclosing as Row[]) {
      if (constructs.has(segment.construct_id) || positiveNatural(segment.pass) <= 0n) fail('STATE_INVALID');
      constructs.add(segment.construct_id);
      if (segment.kind === 'LOOP') {
        const loop = definition.loops.find((row: Row) => row.id === segment.construct_id);
        if (!loop || !loop.member_step_ids.includes(occurrenceRow.step_id) || segment.branch_id !== null || segment.object_key !== null || BigInt(segment.pass) > BigInt(loop.maximum_passes)) fail('STATE_INVALID');
      } else if (segment.kind === 'BRANCH') {
        const block = definition.parallel_blocks.find((row: Row) => row.id === segment.construct_id), branch = block?.branches.find((row: Row) => row.id === segment.branch_id);
        if (!block || !branch || segment.object_key !== null || !lifecycleRegion(definition, branch.head_step_id, block.join_step_id).has(occurrenceRow.step_id)) fail('STATE_INVALID');
      } else if (segment.kind === 'FANOUT') {
        const fanout = definition.fanouts.find((row: Row) => row.id === segment.construct_id);
        if (!fanout || segment.branch_id !== null || !lifecycleRegion(definition, fanout.region_head_step_id, fanout.join_step_id).has(occurrenceRow.step_id)) fail('STATE_INVALID');
        typed(segment.object_key, types);
        if (segment.object_key.type_ref !== fanout.object_type_ref) fail('STATE_INVALID');
        fanouts.push(segment);
      } else fail('STATE_INVALID');
    }
    const expectedObjectKey = fanouts.length ? fanouts.at(-1)!.object_key : null;
    if (!same(occurrenceRow.object_key, expectedObjectKey)) fail('STATE_INVALID');
    byId.set(occurrenceRow.occurrence_id, occurrenceRow);
  }
  if (roots.length !== 1 || roots[0].step_id !== definition.root || roots[0].ordinal !== '1' || roots[0].object_key !== null) fail('STATE_INVALID');
  for (const occurrenceRow of byId.values()) {
    for (const predecessor of occurrenceRow.predecessor_occurrence_ids) if (!byId.has(predecessor)) fail('STATE_INVALID');
    if (occurrenceRow.predecessor_occurrence_ids.some((id: string) => !rows.some((row: Row) => row.occurrence.occurrence_id === id && state.completed.some((candidate: Row) => candidate.occurrence.occurrence_id === id)))) fail('STATE_INVALID');
  }
  const active = new Set<string>(), complete = new Set<string>();
  const visit = (id: string): void => {
    if (active.has(id)) fail('STATE_INVALID');
    if (complete.has(id)) return;
    active.add(id);
    const row = byId.get(id)!;
    for (const predecessor of row.predecessor_occurrence_ids) visit(predecessor);
    active.delete(id); complete.add(id);
  };
  for (const id of byId.keys()) visit(id);
}

function lifecycleValidateFanoutPasses(state: Row, definition: Row, occurrences: Row[]): void {
  const byOccurrence = new Map<string, Row>(occurrences.map((row: Row) => [row.occurrence.occurrence_id, row.occurrence]));
  const byObligation = new Map<string, Row>(state.obligations.map((row: Row) => [row.obligation_id, row]));
  const keys = new Set<string>(), types: Types = new Map(definition.types.map((row: Row) => [row.id, row]));
  const orderedPasses = [...state.fanout_passes].sort((a: Row, b: Row) => {
    const fanoutOrder = byteCompare(a.fanout_id, b.fanout_id);
    if (fanoutOrder !== 0) return fanoutOrder;
    const passOrder = BigInt(a.pass) < BigInt(b.pass) ? -1 : BigInt(a.pass) > BigInt(b.pass) ? 1 : 0;
    return passOrder !== 0 ? passOrder : byteCompare(a.expand_occurrence_id, b.expand_occurrence_id);
  });
  if (!same(state.fanout_passes, orderedPasses)) fail('STATE_INVALID');
  for (const pass of state.fanout_passes as Row[]) {
    positiveNatural(pass.pass);
    const key = canonical([pass.fanout_id, pass.pass, pass.expand_occurrence_id]);
    if (keys.has(key)) fail('STATE_INVALID');
    keys.add(key);
    const fanout = definition.fanouts.find((row: Row) => row.id === pass.fanout_id), expand = byOccurrence.get(pass.expand_occurrence_id);
    if (!fanout || !expand || expand.step_id !== fanout.expand_step_id || !state.completed.some((row: Row) => row.occurrence.occurrence_id === expand.occurrence_id)) fail('STATE_INVALID');
    if (pass.object_keys.length > 1024) fail('STATE_INVALID');
    const duplicateKeys = new Set(pass.object_keys.map((row: Row) => canonical(row))).size !== pass.object_keys.length;
    if (duplicateKeys) {
      const duplicateStop = state.status === 'STOPPED' && state.receipts.some((receipt: Row) => receipt.event_kind === 'EFFECT_OBSERVED' && receipt.disposition === 'STOPPED' && receipt.reason_codes.includes('FANOUT_SET_DUPLICATE'));
      if (!duplicateStop || pass.obligation_ids.length !== 0) fail('STATE_INVALID');
    }
    for (const objectKey of pass.object_keys) { typed(objectKey, types); if (objectKey.type_ref !== fanout.object_type_ref) fail('STATE_INVALID'); }
    if (pass.object_keys.length === 0 && pass.obligation_ids.length !== 0) fail('STATE_INVALID');
    if (pass.object_keys.length !== pass.obligation_ids.length && pass.obligation_ids.length !== 0) fail('STATE_INVALID');
    if (pass.obligation_ids.length) {
      for (const [index, id] of pass.obligation_ids.entries()) {
        const obligationRow = byObligation.get(id), expectedKey = pass.object_keys[index];
        if (!obligationRow) fail('STATE_INVALID');
        const obligation = obligationRow as Row;
        if (obligation.kind !== 'FANOUT_OBJECT' || obligation.construct_id !== pass.fanout_id || obligation.pass !== pass.pass || !same(obligation.object_key, expectedKey) || !same(obligation.source_occurrence_ids, [pass.expand_occurrence_id])) fail('STATE_INVALID');
        const representative = obligation.expected_occurrence_id ? byOccurrence.get(obligation.expected_occurrence_id) : lifecycleRepresentativeOccurrence(state, obligation);
        if (!representative) fail('STATE_INVALID');
        const target = representative as Row;
        if (!target.enclosing.some((segment: Row) => segment.kind === 'FANOUT' && segment.construct_id === pass.fanout_id && segment.pass === pass.pass && same(segment.object_key, expectedKey))) fail('STATE_INVALID');
      }
      const children = pass.obligation_ids.map((id: string) => byObligation.get(id)!);
      if (pass.joined && children.some((row: Row) => row.status !== 'JOINED')) fail('STATE_INVALID');
      if (!pass.joined && children.some((row: Row) => row.status === 'JOINED')) fail('STATE_INVALID');
    } else if (pass.joined) fail('STATE_INVALID');
  }
}

function lifecycleValidateDeadlines(state: Row, definition: Row, occurrences: Row[]): void {
  const byOccurrence = new Map<string, Row>(occurrences.map((row: Row) => [row.occurrence.occurrence_id, row.occurrence]));
  const deadlineKeys = new Set<string>(), pendingByOccurrence = new Map<string, string[]>();
  const receiptByDigest = new Map<string, Row>(state.receipts.map((row: Row) => [row.event_digest, row] as [string, Row]));
  const ordered = [...state.deadlines].sort((a: Row, b: Row) => {
    const ao = byOccurrence.get(a.occurrence_id), bo = byOccurrence.get(b.occurrence_id);
    if (!ao || !bo) return 0;
    return byteCompare(canonical([a.due, ao, a.deadline_id]), canonical([b.due, bo, b.deadline_id]));
  });
  if (!same(state.deadlines, ordered)) fail('STATE_INVALID');
  for (const deadline of state.deadlines as Row[]) {
    const key = canonical([deadline.deadline_id, deadline.occurrence_id]);
    if (deadlineKeys.has(key)) fail('STATE_INVALID');
    deadlineKeys.add(key);
    const declaration = definition.deadlines.find((row: Row) => row.id === deadline.deadline_id), occurrenceRow = byOccurrence.get(deadline.occurrence_id);
    if (!declaration || !occurrenceRow || declaration.step_id !== occurrenceRow.step_id) fail('STATE_INVALID');
    const deadlineDeclaration = declaration as Row, retainedOccurrence = occurrenceRow as Row;
    const clock = state.clocks.find((row: Row) => row.status === 'AVAILABLE' && row.source === deadline.source && row.revision === deadline.activation_clock_revision);
    if (!clock || clock.observed_time !== deadline.activation_instant || clock.evidence_digest !== deadline.activation_clock_evidence_digest || deadline.source !== deadlineDeclaration.clock_source || deadline.boundary !== deadlineDeclaration.boundary || deadline.due !== dueInstant(deadlineDeclaration, { observed_time: deadline.activation_instant }, state, retainedOccurrence)) fail('STATE_INVALID');
    const active = state.active.find((row: Row) => row.occurrence.occurrence_id === deadline.occurrence_id), completed = state.completed.find((row: Row) => row.occurrence.occurrence_id === deadline.occurrence_id);
    const root = retainedOccurrence.predecessor_occurrence_ids.length === 0;
    if (root) {
      const trigger = digest('deployment-activation', { deployment_authorization_digest: state.deployment_authorization_digest, instance_id: state.instance_id, occurrence_id: retainedOccurrence.occurrence_id });
      if (deadline.activation_revision !== '0' || deadline.trigger_digest !== trigger || active && active.activation_event_digest !== trigger) fail('STATE_INVALID');
    } else {
      const triggeringReceipt = lifecycleReceiptByEventDigest(state, deadline.trigger_digest);
      if (!triggeringReceipt || deadline.activation_revision !== triggeringReceipt.sequence || active?.activation_event_digest !== deadline.trigger_digest && !completed) fail('STATE_INVALID');
    }
    if (deadline.status === 'PENDING') {
      if (!active || deadline.expiry_event_digest !== null) fail('STATE_INVALID');
      pendingByOccurrence.set(deadline.occurrence_id, [...(pendingByOccurrence.get(deadline.occurrence_id) ?? []), deadline.deadline_id]);
    } else if (deadline.status === 'DISCHARGED') {
      if (!completed || deadline.expiry_event_digest !== null) fail('STATE_INVALID');
    } else if (deadline.status === 'EXPIRED') {
      if (deadline.expiry_event_digest === null) fail('STATE_INVALID');
      const receipt = receiptByDigest.get(deadline.expiry_event_digest), detail = receipt?.details.find((row: Row) => row.kind === 'DEADLINE'), clockDetail = receipt?.details.find((row: Row) => row.kind === 'CLOCK');
      if (!receipt || receipt.event_kind !== 'CLOCK' || !detail || !detail.deadline_ids.includes(deadline.deadline_id)) fail('STATE_INVALID');
      const expiryClock = clockDetail ? state.clocks.find((row: Row) => row.status === 'AVAILABLE' && row.source === clockDetail.source && row.revision === clockDetail.revision) : null;
      if (completed) {
        if (!expiryClock || completed.disposition !== 'EXPIRED' || completed.evidence_digest !== expiryClock.evidence_digest || completed.occurred_at !== expiryClock.observed_time) fail('STATE_INVALID');
      } else if (!active || active.status !== 'BLOCKED_DISPUTE') fail('STATE_INVALID');
    } else fail('STATE_INVALID');
  }
  for (const active of state.active as Row[]) {
    const declared = sortStrings(definition.deadlines.filter((row: Row) => row.step_id === active.occurrence.step_id).map((row: Row) => row.id));
    if (!same(active.deadline_ids, declared) || declared.some(id => !deadlineKeys.has(canonical([id, active.occurrence.occurrence_id])))) fail('STATE_INVALID');
    stateSortedIds(active.deadline_ids, 256);
  }
  if (state.completed.some((row: Row) => (pendingByOccurrence.get(row.occurrence.occurrence_id) ?? []).length)) fail('STATE_INVALID');
}

function lifecycleValidateCompletedEvidence(state: Row, definition: Row): void {
  const byEvidence = new Map<string, Row>();
  const byOutcomeEvent = new Map<string, Row>();
  for (const outcome of state.outcomes as Row[]) {
    if (byOutcomeEvent.has(outcome.event_id)) fail('STATE_INVALID');
    byOutcomeEvent.set(outcome.event_id, outcome);
    if (byEvidence.has(outcome.native_evidence.evidence_id)) fail('STATE_INVALID');
    byEvidence.set(outcome.native_evidence.evidence_id, outcome);
    const receipt = state.receipts.find((row: Row) => row.event_id === outcome.event_id);
    if (!receipt || receipt.event_kind !== 'EFFECT_OBSERVED' || receipt.event_digest !== outcome.event_digest) fail('STATE_INVALID');
    stateSortedIds(outcome.conflicts_with_evidence_ids, 4096);
    if (outcome.conflicts_with_evidence_ids.includes(outcome.native_evidence.evidence_id) || (outcome.conflicts_with_evidence_ids.length && !outcome.disputed)) fail('STATE_INVALID');
    const replay = state.replays.find((row: Row) => row.event_id === outcome.event_id);
    if (!replay || !same(outcome.reservation_receipt_digests, (replay.budget_results as Row[]).map(permitBudgetResultDigest).sort(byteCompare))) fail('STATE_INVALID');
    if (outcome.kind === 'FOREIGN') {
      if (outcome.permit_digest !== null || outcome.dispatch_digest !== null || outcome.dispatch_attempt_digest !== null || !outcome.disputed) fail('STATE_INVALID');
      if (receipt.permit_digest !== null) fail('STATE_INVALID');
    } else {
      const permit = state.permits.find((row: Row) => row.permit_id === outcome.permit_digest), dispatchRow = state.dispatches.find((row: Row) => row.dispatch_digest === outcome.dispatch_digest);
      if (!permit || !dispatchRow || dispatchRow.permit_digest !== permit.permit_id || dispatchRow.dispatch_attempt_digest !== outcome.dispatch_attempt_digest || receipt.permit_digest !== permit.permit_id) fail('STATE_INVALID');
      const expectedRequest = attributedRequest(definition, state.instance_id, permit, dispatchRow);
      if (!same(outcome.native_evidence.attributed_request, expectedRequest) || outcome.native_evidence.native_request_digest !== digest('native-request', expectedRequest)) fail('STATE_INVALID');
      if (['UNEXPECTED', 'CONFLICTING', 'LATE_AFTER_RELEASE'].includes(outcome.classification) && !outcome.disputed) fail('STATE_INVALID');
    }
  }
  for (const outcome of state.outcomes as Row[]) if (outcome.conflicts_with_evidence_ids.some((id: string) => !byEvidence.has(id))) fail('STATE_INVALID');
  const completedIds = new Set<string>();
  for (const completed of state.completed as Row[]) {
    const id = completed.occurrence.occurrence_id;
    if (completedIds.has(id) || completed.evidence_digest === null) fail('STATE_INVALID');
    completedIds.add(id);
    const step = definition.steps.find((row: Row) => row.id === completed.occurrence.step_id);
    if (!step || completed.route_label !== null && (step.completion.route_label_type_ref === null || completed.route_label.type_ref !== step.completion.route_label_type_ref)) fail('STATE_INVALID');
    let matchingOutcome: Row | null = null;
    if (completed.disposition === 'EXPIRED') {
      const deadline = state.deadlines.find((row: Row) => row.occurrence_id === id && row.status === 'EXPIRED');
      if (!deadline) fail('STATE_INVALID');
      const receipt = state.receipts.find((row: Row) => row.event_digest === deadline.expiry_event_digest), clockDetail = receipt?.details.find((row: Row) => row.kind === 'CLOCK');
      const clock = clockDetail ? state.clocks.find((row: Row) => row.source === clockDetail.source && row.revision === clockDetail.revision) : null;
      if (!receipt || !clock || completed.evidence_digest !== clock.evidence_digest || completed.occurred_at !== clock.observed_time) fail('STATE_INVALID');
    } else {
      const candidate = [...byEvidence.values()].find((row: Row) => row.kind === 'GOVERNED' && row.permit_digest && state.permits.some((permit: Row) => permit.permit_id === row.permit_digest && permit.occurrence.occurrence_id === id) && digest('native-evidence', row.native_evidence) === completed.evidence_digest);
      if (!candidate) fail('STATE_INVALID');
      const matched = candidate as Row;
      matchingOutcome = matched;
      if (completed.disposition === 'SUCCEEDED' && !['MATCHED', 'LATE_MATCHED'].includes(matched.classification)) fail('STATE_INVALID');
      if (completed.disposition === 'FAILED' && matched.classification !== 'FAILED') fail('STATE_INVALID');
      if (completed.disposition === 'NO_EFFECT' && matched.classification !== 'NO_EFFECT_ESTABLISHED') fail('STATE_INVALID');
      const expectedAt = matched.native_evidence.status === 'NO_EFFECT_ESTABLISHED' ? matched.native_evidence.observed_at : matched.native_evidence.event_time;
      if (expectedAt !== completed.occurred_at) fail('STATE_INVALID');
    }
    if (completed.selected_relationship_digest !== null) {
      const relationship = definition.relationships.find((row: Row) => digest('relationship', row) === completed.selected_relationship_digest);
      if (!relationship || relationship.from !== completed.occurrence.step_id) fail('STATE_INVALID');
      const expectedKind = completed.disposition === 'EXPIRED' ? 'EXPIRY' : completed.disposition === 'FAILED' ? 'FAILURE' : 'LABEL';
      if (completed.disposition === 'SUCCEEDED' && relationship.kind !== 'SEQUENCE' && relationship.kind !== 'LABEL') fail('STATE_INVALID');
      if (completed.disposition === 'FAILED' && relationship.kind !== 'FAILURE') fail('STATE_INVALID');
      if (completed.disposition === 'EXPIRED' && relationship.kind !== 'EXPIRY') fail('STATE_INVALID');
      if (relationship.kind === 'LABEL') { if (!completed.route_label || !same(completed.route_label, relationship.label)) fail('STATE_INVALID'); }
      else if (completed.route_label !== null) fail('STATE_INVALID');
      if (expectedKind === 'LABEL' && relationship.kind !== 'LABEL' && completed.route_label !== null) fail('STATE_INVALID');
    } else if (completed.route_label !== null) fail('STATE_INVALID');
  }
}

function lifecycleValidateSeparationDetails(state: Row): void {
  const proposals = new Map<string, Row>(state.proposals.map((row: Row) => [row.event_id, row]));
  for (const receipt of state.receipts as Row[]) {
    const details = receipt.details.filter((row: Row) => row.kind === 'SEPARATION');
    if (!details.length) continue;
    if (details.length !== 1 || receipt.event_kind !== 'PROPOSE') fail('STATE_INVALID');
    const proposal = proposals.get(receipt.event_id), detail = details[0];
    if (!proposal || proposal.disposition !== 'WITHHELD' || proposal.permit_digest !== null || !receipt.reason_codes.includes('SEPARATION_VIOLATED') || proposal.authority_result_digest !== receipt.authority_result_digest) fail('STATE_INVALID');
    const retainedProposal = proposal as Row;
    if (!detail.authority_result || digest('authority-result', detail.authority_result) !== retainedProposal.authority_result_digest || !detail.authority_result.act_digests.includes(detail.basis.current_act.act_digest)) fail('STATE_INVALID');
    const current = detail.basis.current_act, prior = detail.basis.prior_act;
    if (current.act_digest !== digest('authority-act', current.act) || prior.act_digest !== digest('authority-act', prior.act) || current.act.actor !== prior.act.actor || detail.basis.current_occurrence_id !== retainedProposal.occurrence_id) fail('STATE_INVALID');
  }
}

function lifecycleValidateDispatches(state: Row, definition: Row): void {
  const dispatchIds = new Set<string>();
  for (const dispatchRow of state.dispatches as Row[]) {
    if (dispatchIds.has(dispatchRow.dispatch_digest) || dispatchRow.dispatch_digest !== digest('dispatch', omitted(dispatchRow, 'dispatch_digest')) || dispatchRow.dispatch_attempt_digest !== digest('dispatch-attempt', { permit_id: dispatchRow.permit_digest, native_request: dispatchRow.native_request, connector: dispatchRow.connector, attempt: dispatchRow.attempt }) || dispatchRow.attempt.request_digest !== digest('dispatch-native-request', { instance_id: state.instance_id, occurrence_id: state.permits.find((row: Row) => row.permit_id === dispatchRow.permit_digest)?.occurrence.occurrence_id, interface: dispatchRow.native_request.interface, operation: dispatchRow.native_request.operation, fields: dispatchRow.native_request.fields }) || dispatchRow.connector.binding_digest !== digest('connector-binding', { id: dispatchRow.connector.id, version: dispatchRow.connector.version })) fail('STATE_INVALID');
    dispatchIds.add(dispatchRow.dispatch_digest);
    const permit = state.permits.find((row: Row) => row.permit_id === dispatchRow.permit_digest), receipt = state.receipts.find((row: Row) => row.event_id === dispatchRow.event_id);
    if (!permit || !receipt || receipt.event_kind !== 'DISPATCH_OBSERVED' || receipt.event_digest !== dispatchRow.event_digest || receipt.instance_id !== state.instance_id || receipt.permit_digest !== permit.permit_id) fail('STATE_INVALID');
    const issuanceClock = state.clocks.find((row: Row) => row.status === 'AVAILABLE' && row.source === permit.clock_source && row.revision === permit.clock_revision), dispatchClock = state.clocks.find((row: Row) => row.status === 'AVAILABLE' && row.source === permit.clock_source && row.revision === dispatchRow.clock_revision);
    if (!issuanceClock || !dispatchClock || BigInt(dispatchRow.clock_revision) < BigInt(permit.clock_revision) || wholeSecond(dispatchRow.attempt.attempted_at) < wholeSecond(issuanceClock.observed_time) || wholeSecond(dispatchRow.attempt.attempted_at) > wholeSecond(dispatchClock.observed_time)) fail('STATE_INVALID');
    if (dispatchRow.acknowledgement.status === 'NONE') { if (dispatchRow.acknowledgement.reference !== null || dispatchRow.acknowledgement.observed_at !== null) fail('STATE_INVALID'); }
    else if (dispatchRow.acknowledgement.reference === null || dispatchRow.acknowledgement.observed_at === null || wholeSecond(dispatchRow.acknowledgement.observed_at) < wholeSecond(dispatchRow.attempt.attempted_at) || wholeSecond(dispatchRow.acknowledgement.observed_at) > wholeSecond(dispatchClock.observed_time)) fail('STATE_INVALID');
    if (state.permits.some((row: Row) => row.supersedes_permit_digest === permit.permit_id) && (dispatchRow.attempt.status !== 'NOT_SENT' || dispatchRow.acknowledgement.status === 'ACCEPTED')) fail('STATE_INVALID');
  }
}

function lifecycleValidateStateBoundsAndStatus(state: Row, definition: Row): void {
  if (state.role !== PROFILE_ROLES[state.profile] || state.deployment_organization_id !== state.deployment_authorization.organization_id || state.total_activations !== String(BigInt(state.total_activations)) || state.total_actuations !== String(BigInt(state.total_actuations))) fail('STATE_INVALID');
  if (BigInt(state.total_activations) > BigInt(definition.limits.maximum_activations) || BigInt(state.total_actuations) > BigInt(definition.limits.maximum_actuations)) fail('STATE_INVALID');
  if (state.proposals.filter((row: Row) => state.receipts.some((receipt: Row) => receipt.event_id === row.event_id && receipt.event_kind === 'PROPOSE')).length > 4096) fail('STATE_INVALID');
  const proposalReceipts = state.receipts.filter((row: Row) => row.event_kind === 'PROPOSE').length, proposalReplays = state.replays.filter((row: Row) => row.decision.event_kind === 'PROPOSE').length;
  if (proposalReceipts !== proposalReplays || proposalReceipts > Number(definition.limits.maximum_proposals)) fail('STATE_INVALID');
  const unresolved = state.obligations.filter((row: Row) => ['OPEN', 'BLOCKED', 'WAITING', 'DISPUTED'].includes(row.status));
  if (unresolved.length > Number(definition.limits.maximum_active_obligations)) fail('STATE_INVALID');
  for (const counter of state.step_counters as Row[]) {
    const limit = definition.occurrence_limits.find((row: Row) => row.step_id === counter.step_id);
    if (!limit || BigInt(counter.activations) > BigInt(limit.maximum)) fail('STATE_INVALID');
  }
  for (const pass of state.fanout_passes as Row[]) if (BigInt(pass.object_keys.length) > BigInt(definition.limits.maximum_fanout_objects)) fail('STATE_INVALID');
  for (const retained of [...state.active, ...state.completed] as Row[]) for (const segment of retained.occurrence.enclosing as Row[]) if (segment.kind === 'LOOP') {
    const loop = definition.loops.find((row: Row) => row.id === segment.construct_id);
    if (!loop || BigInt(segment.pass) > BigInt(loop.maximum_passes)) fail('STATE_INVALID');
  }
  if (state.status === 'COMPLETE') {
    const terminalRelationships = new Set((definition.relationships as Row[]).filter((row: Row) => definition.steps.find((step: Row) => step.id === row.to)?.kind === 'TERMINAL').map((row: Row) => digest('relationship', row)));
    const terminalTrace = state.receipts.some((receipt: Row) => receipt.details.some((detail: Row) => detail.kind === 'ROUTE' && detail.relationship_digests.some((id: string) => terminalRelationships.has(id))));
    if (!terminalTrace) fail('STATE_INVALID');
  }
  if (state.status === 'STOPPED' && !state.receipts.some((row: Row) => row.disposition === 'STOPPED')) fail('STATE_INVALID');
  if (state.status === 'ACTIVE' && !state.active.length && !unresolved.length) fail('STATE_INVALID');
  if (state.status === 'COMPLETE' && (state.active.length || unresolved.length)) fail('STATE_INVALID');
}

function lifecycleValidateRemainingStateInvariants(state: Row, definition: Row, pin: string, occurrences: Row[]): void {
  stateSortedRows(state.step_counters, (row: Row) => row.step_id);
  stateSortedRows(state.obligations, (row: Row) => row.obligation_id);
  lifecycleValidateOccurrences(state, definition, pin, occurrences);
  lifecycleValidateFanoutPasses(state, definition, occurrences);
  const receiptDigests = new Set<string>(state.receipts.map((row: Row) => row.event_digest));
  lifecycleValidateObligations(state, definition, occurrences, receiptDigests);
  lifecycleValidateDeadlines(state, definition, occurrences);
  lifecycleValidateDispatches(state, definition);
  lifecycleValidateCompletedEvidence(state, definition);
  lifecycleValidateSeparationDetails(state);
  lifecycleValidateStateBoundsAndStatus(state, definition);
}

function stateInvalid(state: Row, definition: Row, pin: string): void {
  try {
    requireShape('lifecycle.schema.json', 'state', state);
    if (state.specification_pin !== pin || state.work_class_digest !== digest('work-class-definition', definition) || state.profile !== definition.profile) fail('STATE_INVALID');
    if (state.deployment_authorization_subject_digest !== digest('deployment-authorization-subject', deploymentSubject(state.deployment_authorization))) fail('STATE_INVALID');
    if (state.deployment_authorization_digest !== digest('deployment-authorization', state.deployment_authorization)) fail('STATE_INVALID');
    if (state.deployment_authorization_evidence_digest !== digest('evidence', state.deployment_authorization_evidence) || state.deployment_authorization.authorization_evidence_digest !== state.deployment_authorization_evidence_digest || state.deployment_authorization_evidence.status !== 'ACCEPTED') fail('STATE_INVALID');
    for (const [record, field] of [['deployment_correspondence_evidence', 'correspondence_evidence_digest'], ['deployment_source_confirmation_evidence', 'source_confirmation_evidence_digest'], ['deployment_policy_decision_evidence', 'policy_decision_evidence_digest']]) {
      if (state[record + '_digest'] !== digest('evidence', state[record]) || state.deployment_authorization[field] !== state[record + '_digest']) fail('STATE_INVALID');
    }
    // LIFE-003: restart recomputes every digest, time relation and binding of the three review records.
    const correspondence = state.deployment_correspondence_evidence, confirmation = state.deployment_source_confirmation_evidence, decision = state.deployment_policy_decision_evidence;
    const authorizedAt = wholeSecond(state.deployment_authorization_clock.observed_time);
    if (correspondence.status !== 'ACCEPTED' || correspondence.subject_digest !== state.work_class_digest || correspondenceCode(correspondence, definition, state.work_class_digest) || correspondence.residue.some((row: Row) => row.disposition === 'PENDING')) fail('STATE_INVALID');
    if (confirmation.status !== 'ACCEPTED' || confirmation.subject_digest !== digest('work-class-source', definition.source) || !same(confirmation.scope_ids, definition.source.obligations)) fail('STATE_INVALID');
    if (decision.status !== 'ACCEPTED' || decision.subject_digest !== state.work_class_digest) fail('STATE_INVALID');
    if ([correspondence, confirmation, decision].some((row: Row) => wholeSecond(row.recorded_at) > authorizedAt)) fail('STATE_INVALID');
    if (new Set([state.deployment_authorization_evidence, correspondence, confirmation, decision].map((row: Row) => row.evidence_id)).size !== 4) fail('STATE_INVALID');
    if (state.revision !== String(state.receipts.length) || state.revision !== String(state.replays.length)) fail('STATE_INVALID');
    const proposalSteps = definition.steps.filter((row: Row) => ['OPERATION', 'FANOUT_EXPAND'].includes(row.kind)).map((row: Row) => row.id).sort(byteCompare);
    if (!same(state.step_counters.map((row: Row) => row.step_id), proposalSteps)) fail('STATE_INVALID');
    if (!same(state.active, [...state.active].sort((a: Row, b: Row) => byteCompare(canonical(a.occurrence), canonical(b.occurrence)))) || !same(state.completed, [...state.completed].sort((a: Row, b: Row) => byteCompare(canonical(a.occurrence), canonical(b.occurrence))))) fail('STATE_INVALID');
    const allOccurrences = [...state.active, ...state.completed];
    const activeIds = new Set(state.active.map((row: Row) => row.occurrence.occurrence_id)), allIds = new Set<string>();
    for (const row of allOccurrences) {
      const occurrenceRow = row.occurrence;
      if (allIds.has(occurrenceRow.occurrence_id) || occurrenceRow.occurrence_id !== occurrence(state.work_class_digest, state.instance_id, occurrenceRow.step_id, occurrenceRow.ordinal, occurrenceRow.predecessor_occurrence_ids, occurrenceRow.enclosing, occurrenceRow.object_key, pin).occurrence_id) fail('STATE_INVALID');
      allIds.add(occurrenceRow.occurrence_id);
      if (occurrenceRow.predecessor_occurrence_ids.some((id: string) => !allIds.has(id) && !allOccurrences.some((candidate: Row) => candidate.occurrence.occurrence_id === id))) fail('STATE_INVALID');
    }
    if (state.completed.some((row: Row) => activeIds.has(row.occurrence.occurrence_id))) fail('STATE_INVALID');
    validatePermitChainsAndBudgetLinks(state, definition, allOccurrences);
    lifecycleValidateRemainingStateInvariants(state, definition, pin, allOccurrences);
    if (!same(state.proposals, [...state.proposals].sort((a: Row, b: Row) => byteCompare(a.event_id, b.event_id))) || !same(state.permits, [...state.permits].sort((a: Row, b: Row) => byteCompare(a.permit_id, b.permit_id))) || !same(state.dispatches, [...state.dispatches].sort((a: Row, b: Row) => byteCompare(a.dispatch_digest, b.dispatch_digest))) || !same(state.outcomes, [...state.outcomes].sort((a: Row, b: Row) => byteCompare(a.outcome_digest, b.outcome_digest))) || !same(state.replays, [...state.replays].sort((a: Row, b: Row) => byteCompare(a.event_id, b.event_id)))) fail('STATE_INVALID');
    const proposalIds = new Set(state.proposals.map((row: Row) => row.event_id));
    if (proposalIds.size !== state.proposals.length) fail('STATE_INVALID');
    const permitIds = new Set<string>();
    const permitSuccessors = new Map<string, string>();
    for (const permit of state.permits) {
      if (permit.permit_id !== permitDigest(permit) || permitIds.has(permit.permit_id) || permit.authority_result_digest !== digest('authority-result', permit.authority_result) || permit.authority_evidence_digest !== permit.authority_result.evidence_digest) fail('STATE_INVALID');
      permitIds.add(permit.permit_id);
      const bases = permit.authority_act_bases.map((row: Row) => row.act_digest);
      if (!same(bases, [...bases].sort(byteCompare)) || !same(bases, permit.authority_result.act_digests) || permit.authority_act_bases.some((row: Row) => row.act_digest !== digest('authority-act', row.act))) fail('STATE_INVALID');
    }
    for (const permit of state.permits) {
      if (permit.supersedes_permit_digest === null) continue;
      const prior = state.permits.find((row: Row) => row.permit_id === permit.supersedes_permit_digest);
      if (!prior || prior.occurrence.occurrence_id !== permit.occurrence.occurrence_id || permitSuccessors.has(prior.permit_id)) fail('STATE_INVALID');
      permitSuccessors.set(prior.permit_id, permit.permit_id);
    }
    for (const proposal of state.proposals) {
      const replay = state.replays.find((row: Row) => row.event_id === proposal.event_id);
      if (!replay || proposal.event_digest !== replay.event_digest) fail('STATE_INVALID');
      if (proposal.disposition === 'PERMITTED' && (!proposal.permit_digest || !permitIds.has(proposal.permit_digest))) fail('STATE_INVALID');
      if (proposal.disposition === 'PERMITTED' && state.permits.find((row: Row) => row.permit_id === proposal.permit_digest)?.proposal_digest !== proposal.proposal_digest) fail('STATE_INVALID');
      if (proposal.disposition === 'WITHHELD' && proposal.permit_digest !== null) fail('STATE_INVALID');
    }
    for (const dispatchRow of state.dispatches) {
      const permit = state.permits.find((row: Row) => row.permit_id === dispatchRow.permit_digest);
      if (!permit || dispatchRow.dispatch_digest !== digest('dispatch', omitted(dispatchRow, 'dispatch_digest')) || dispatchRow.dispatch_attempt_digest !== digest('dispatch-attempt', { permit_id: dispatchRow.permit_digest, native_request: dispatchRow.native_request, connector: dispatchRow.connector, attempt: dispatchRow.attempt }) || dispatchRow.connector.binding_digest !== digest('connector-binding', { id: dispatchRow.connector.id, version: dispatchRow.connector.version })) fail('STATE_INVALID');
      const receipt = state.receipts.find((row: Row) => row.event_id === dispatchRow.event_id);
      if (!receipt || receipt.event_kind !== 'DISPATCH_OBSERVED' || receipt.event_digest !== dispatchRow.event_digest || receipt.permit_digest !== permit.permit_id) fail('STATE_INVALID');
    }
    const evidenceIds = new Set<string>();
    for (const outcome of state.outcomes) {
      if (outcome.outcome_digest !== outcomeDigest(outcome) || outcome.event_digest !== state.receipts.find((row: Row) => row.event_id === outcome.event_id)?.event_digest || evidenceIds.has(outcome.native_evidence.evidence_id)) fail('STATE_INVALID');
      evidenceIds.add(outcome.native_evidence.evidence_id);
      if (outcome.kind === 'GOVERNED') {
        const permit = state.permits.find((row: Row) => row.permit_id === outcome.permit_digest), dispatchRow = state.dispatches.find((row: Row) => row.dispatch_digest === outcome.dispatch_digest);
        if (!permit || !dispatchRow || dispatchRow.permit_digest !== permit.permit_id || dispatchRow.dispatch_attempt_digest !== outcome.dispatch_attempt_digest) fail('STATE_INVALID');
      }
      if ((outcome.disputed === false && outcome.conflicts_with_evidence_ids.length) || outcome.conflicts_with_evidence_ids.some((id: string) => !state.outcomes.some((row: Row) => row.native_evidence.evidence_id === id))) fail('STATE_INVALID');
    }
    const clocks = [...state.clocks].sort((a: Row, b: Row) => a.source === b.source ? (BigInt(a.revision) < BigInt(b.revision) ? -1 : 1) : byteCompare(a.source, b.source));
    if (!same(state.clocks, clocks) || new Set(state.clocks.map((row: Row) => canonical([row.source, row.revision]))).size !== state.clocks.length) fail('STATE_INVALID');
    const clockWatermarks = new Map<string, bigint>();
    for (const clock of state.clocks.filter((row: Row) => row.status === 'AVAILABLE')) {
      const at = wholeSecond(clock.observed_time), prior = clockWatermarks.get(clock.source);
      if (prior !== undefined && at < prior) fail('STATE_INVALID'); clockWatermarks.set(clock.source, at);
    }
    const orderedDeadlines = clone(state);
    sortStateDeadlines(orderedDeadlines);
    if (!same(state.deadlines, orderedDeadlines.deadlines)) fail('STATE_INVALID');
    for (const deadline of state.deadlines) {
      const declaration = definition.deadlines.find((row: Row) => row.id === deadline.deadline_id);
      const occurrenceRow = allOccurrences.find((row: Row) => row.occurrence.occurrence_id === deadline.occurrence_id)?.occurrence;
      const activationClock = state.clocks.find((row: Row) => row.status === 'AVAILABLE' && row.source === deadline.source && row.revision === deadline.activation_clock_revision);
      const activation = {
        deadline_id: deadline.deadline_id,
        occurrence_id: deadline.occurrence_id,
        trigger_digest: deadline.trigger_digest,
        source: deadline.source,
        activation_revision: deadline.activation_revision,
        activation_clock_revision: deadline.activation_clock_revision,
        activation_instant: deadline.activation_instant,
        activation_clock_evidence_digest: deadline.activation_clock_evidence_digest,
        due: deadline.due,
        boundary: deadline.boundary,
      };
      if (!declaration || !occurrenceRow || occurrenceRow.step_id !== declaration.step_id || deadline.source !== declaration.clock_source || deadline.boundary !== declaration.boundary || !activationClock || activationClock.observed_time !== deadline.activation_instant || activationClock.evidence_digest !== deadline.activation_clock_evidence_digest || deadline.due !== dueInstant(declaration, { observed_time: deadline.activation_instant }, state, occurrenceRow) || deadline.activation_digest !== digest('deadline-activation', activation)) fail('STATE_INVALID');
    }
    const expectedCounters = new Map<string, Row>(state.step_counters.map((row: Row) => [row.step_id, row]));
    let activations = 0n, actuations = 0n;
    for (const [stepId, counter] of expectedCounters) {
      const a = [...state.active, ...state.completed].filter((row: Row) => row.occurrence.step_id === stepId).length;
      const t = state.proposals.filter((row: Row) => row.disposition === 'PERMITTED' && row.prior_permit_digest === null && state.permits.some((permit: Row) => permit.permit_id === row.permit_digest && permit.occurrence.step_id === stepId)).length;
      if (counter.activations !== String(a) || counter.actuations !== String(t)) fail('STATE_INVALID');
      activations += BigInt(a); actuations += BigInt(t);
    }
    if (state.total_activations !== String(activations) || state.total_actuations !== String(actuations)) fail('STATE_INVALID');
    for (let i = 0; i < state.receipts.length; i++) {
      const receipt = state.receipts[i], replay = state.replays.find((row: Row) => row.event_id === receipt.event_id);
      if (!replay) fail('STATE_INVALID');
      if (receipt.sequence !== String(i + 1) || receipt.decision_id !== decisionDigest(receipt) || replay.event_id !== receipt.event_id || replay.event_digest !== receipt.event_digest || replay.decision_receipt_digest !== receipt.decision_id || !same(replay.decision, receipt) || replay.transition_state_digest !== receipt.state_after_core_digest) fail('STATE_INVALID');
      const tx = digest('lifecycle-transaction', { state_before_digest: receipt.state_before_digest, event_digest: receipt.event_digest, decision_receipt_digest: receipt.decision_id, state_after_core_digest: receipt.state_after_core_digest, budget_results: replay.budget_results });
      if (replay.transaction_digest !== tx) fail('STATE_INVALID');
    }
    if (state.receipts.length && state.receipts[state.receipts.length - 1].state_after_core_digest !== coreDigest(state)) fail('STATE_INVALID');
    const unresolved = state.obligations.some((row: Row) => ['OPEN', 'BLOCKED', 'WAITING', 'DISPUTED'].includes(row.status));
    if (state.status === 'ACTIVE' && !state.active.length && !unresolved) fail('STATE_INVALID');
    if (state.status === 'COMPLETE' && (state.active.length || unresolved)) fail('STATE_INVALID');
    if (state.status === 'STOPPED' && !state.receipts.some((row: Row) => row.disposition === 'STOPPED')) fail('STATE_INVALID');
  } catch (error) {
    if (error instanceof AdmissionError && error.code === 'STATE_INVALID') throw error;
    throw new AdmissionError('STATE_INVALID');
  }
}

type DecisionInput = { disposition: string; reasons?: string[]; details?: Row[]; permit?: Row | null; decisionPermitDigest?: string | null; authorityResultDigest?: string | null; budgetResults?: Row[] };
function admittedTransition(request: Row, next: Row, event: Row, input: DecisionInput): Row {
  const before = request.state_digest, eDigest = eventDigest(event), budgetResults = input.budgetResults ?? [], permit = input.permit ?? null;
  next.revision = (BigInt(request.state.revision) + 1n).toString();
  const afterCore = coreDigest(next);
  const receipt: Row = {
    schema: VERSION + '/decision-receipt', decision_id: '', instance_id: request.state.instance_id, sequence: next.revision,
    event_id: event.event_id, event_digest: eDigest, event_kind: event.kind, disposition: input.disposition,
    reason_codes: sortStrings(input.reasons ?? []), details: input.details ?? [], permit_digest: input.decisionPermitDigest ?? permit?.permit_id ?? null,
    authority_result_digest: input.authorityResultDigest ?? null,
    reservation_receipt_digests: budgetResults.map((row: Row) => row.result.receipt_digest).sort(byteCompare),
    state_before_digest: before, state_after_core_digest: afterCore,
  };
  receipt.decision_id = decisionDigest(receipt);
  next.receipts = [...next.receipts, receipt];
  const replay: Row = { event_id: event.event_id, event_digest: eDigest, decision: receipt, decision_receipt_digest: receipt.decision_id, permit, budget_results: clone(budgetResults), transition_state_digest: afterCore, transaction_digest: '' };
  replay.transaction_digest = digest('lifecycle-transaction', { state_before_digest: before, event_digest: eDigest, decision_receipt_digest: receipt.decision_id, state_after_core_digest: afterCore, budget_results: budgetResults });
  next.replays = [...next.replays, replay]; sortedRows(next.replays, row => row.event_id);
  const nextDigest = stateDigest(next);
  requireShape('lifecycle.schema.json', 'state', next);
  return { status: 'STEP', profile: request.profile, role: request.role, decision: receipt, decision_digest: receipt.decision_id, permit, budget_results: budgetResults, state: next, state_digest: nextDigest, transition_state_digest: afterCore, transaction_digest: replay.transaction_digest, replay: false };
}

function dueInstant(deadline: Row, activation: Row, state: Row | null, occurrenceRow: Row): string {
  if (deadline.due.kind === 'ABSOLUTE_INSTANT') return deadline.due.instant;
  const start = deadline.due.kind === 'ELAPSED_FROM_ANCESTOR' ? anchorOccurredAt(state!, occurrenceRow, deadline.due.anchor_step_id) : activation.observed_time;
  return instantText(wholeSecond(start) + seconds(deadline.due.value, deadline.due.unit));
}

// COMPOSITION 5.1: the one completed occurrence of the anchor step in the recursive predecessor closure.
function anchorOccurredAt(state: Row, occurrenceRow: Row, anchorStepId: string): string {
  const occurrences = new Map<string, Row>([...state.active, ...state.completed].map((row: Row) => [row.occurrence.occurrence_id, row.occurrence]));
  const completed = new Map<string, Row>(state.completed.map((row: Row) => [row.occurrence.occurrence_id, row]));
  const seen = new Set<string>(), pending: string[] = [...occurrenceRow.predecessor_occurrence_ids], anchors: Row[] = [];
  while (pending.length) {
    const id = pending.pop()!;
    if (seen.has(id)) continue; seen.add(id);
    const predecessor = occurrences.get(id) ?? fail('STATE_INVALID');
    if (predecessor.step_id === anchorStepId && completed.has(id)) anchors.push(completed.get(id)!);
    pending.push(...predecessor.predecessor_occurrence_ids);
  }
  if (anchors.length !== 1) fail('STATE_INVALID');
  return anchors[0].occurred_at;
}

function deadlineState(deadline: Row, occurrenceRow: Row, triggerDigest: string, activationRevision: string, clock: Row, state: Row | null): Row {
  const core = {
    deadline_id: deadline.id,
    occurrence_id: occurrenceRow.occurrence_id,
    trigger_digest: triggerDigest,
    source: deadline.clock_source,
    activation_revision: activationRevision,
    activation_clock_revision: clock.revision,
    activation_instant: clock.observed_time,
    activation_clock_evidence_digest: clock.evidence_digest,
    due: dueInstant(deadline, clock, state, occurrenceRow),
    boundary: deadline.boundary,
  };
  return { activation_digest: digest('deadline-activation', core), ...core, status: 'PENDING', expiry_event_digest: null };
}

function deploymentSubject(record: Row): Row { const subject = clone(record); delete subject.authorization_evidence_digest; return subject; }

function deployFailure(input: unknown, error: unknown): Row {
  if (!(error instanceof AdmissionError)) throw error;
  const row = input as Row;
  if (row && typeof row.profile === 'string' && typeof row.role === 'string' && Object.hasOwn(PROFILE_ROLES, row.profile) && Object.values(PROFILE_ROLES).includes(row.role)) return { status: 'REFUSED', profile: row.profile, role: row.role, code: error.code, path: error.path };
  return { status: 'REFUSED', code: 'SCHEMA_INVALID', path: '' };
}

export function deploy(input: unknown, selectedPin: string): Row {
  try {
    requireShape('lifecycle.schema.json', 'deployInput', input);
    const request = input as Row;
    if (PROFILE_ROLES[request.profile] !== request.role) fail('ROLE_UNSUPPORTED');
    if (request.specification_pin !== selectedPin) fail('VERSION_UNSUPPORTED');
    const admitted = validateWorkClass(request.definition, selectedPin);
    if (admitted.digest !== request.definition_digest) fail('DIGEST_MISMATCH');
    if (request.definition.profile !== request.profile) fail('BINDING_MISMATCH');
    const authorization = request.deployment_authorization, evidence = request.authorization_evidence, clock = request.authorization_clock;
    const subjectDigest = digest('deployment-authorization-subject', deploymentSubject(authorization));
    const evidenceDigest = digest('evidence', evidence);
    const authorizationDigest = digest('deployment-authorization', authorization);
    if (authorization.instance_id !== request.instance_id) fail('DEPENDENCY_MISMATCH');
    if (authorization.specification_pin !== selectedPin || authorization.work_class_digest !== admitted.digest || authorization.profile !== request.profile || authorization.role !== request.role || authorization.authorization_evidence_digest !== evidenceDigest) fail('BINDING_MISMATCH');
    if (evidence.subject_digest !== subjectDigest || evidence.organization_id !== authorization.organization_id) fail('BINDING_MISMATCH');
    if (authorization.status !== 'AUTHORIZED' || evidence.status !== 'ACCEPTED') fail('EVIDENCE_UNAVAILABLE');
    const now = wholeSecond(clock.observed_time);
    if (wholeSecond(authorization.authorized_at) > now || (authorization.expires_at !== null && now >= wholeSecond(authorization.expires_at))) fail('EVIDENCE_UNAVAILABLE');
    if (wholeSecond(evidence.recorded_at) > now || evidence.expires_at === null || now >= wholeSecond(evidence.expires_at)) fail('EVIDENCE_UNAVAILABLE');
    const scope = sortStrings([selectedPin, admitted.digest, request.profile, request.role, request.instance_id]);
    if (!same(scope, evidence.authorization_scope)) fail('BINDING_MISMATCH');
    const correspondence = request.correspondence_evidence, confirmation = request.source_confirmation_evidence, decision = request.policy_decision_evidence;
    const correspondenceDigest = digest('evidence', correspondence), confirmationDigest = digest('evidence', confirmation), decisionDigest = digest('evidence', decision);
    if (authorization.correspondence_evidence_digest !== correspondenceDigest || authorization.source_confirmation_evidence_digest !== confirmationDigest || authorization.policy_decision_evidence_digest !== decisionDigest) fail('BINDING_MISMATCH');
    // LIFE-003: every binding condition of the three review records precedes every availability condition.
    const correspondenceFailure = correspondenceCode(correspondence, request.definition, admitted.digest);
    if (correspondence.subject_digest !== admitted.digest || correspondenceFailure === 'BINDING_MISMATCH') fail('BINDING_MISMATCH');
    if (confirmation.subject_digest !== digest('work-class-source', request.definition.source) || !same(confirmation.scope_ids, request.definition.source.obligations)) fail('BINDING_MISMATCH');
    if (decision.subject_digest !== admitted.digest) fail('BINDING_MISMATCH');
    if ([correspondence, confirmation, decision].some((row: Row) => wholeSecond(row.recorded_at) > now)) fail('BINDING_MISMATCH');
    if (new Set([evidence, correspondence, confirmation, decision].map((row: Row) => row.evidence_id)).size !== 4) fail('BINDING_MISMATCH');
    if (correspondence.status !== 'ACCEPTED' || correspondenceFailure === 'EVIDENCE_NOT_ACCEPTED' || correspondence.residue.some((row: Row) => row.disposition === 'PENDING')) fail('EVIDENCE_UNAVAILABLE');
    if (confirmation.status !== 'ACCEPTED' || decision.status !== 'ACCEPTED') fail('EVIDENCE_UNAVAILABLE');

    const rootDeadlines = request.definition.deadlines.filter((row: Row) => row.step_id === request.definition.root);
    const sources = sortStrings(rootDeadlines.map((row: Row) => row.clock_source));
    const suppliedSources = request.initial_clocks.map((row: Row) => row.source);
    if (!same(suppliedSources, sortStrings(suppliedSources))) fail('DEPENDENCY_MISMATCH');
    if (sources.some(source => !suppliedSources.includes(source))) fail('EVIDENCE_UNAVAILABLE');
    if (!same(sources, suppliedSources)) fail('DEPENDENCY_MISMATCH');

    const root = occurrence(admitted.digest, request.instance_id, request.definition.root, '1', [], [], null, selectedPin);
    const activation = digest('deployment-activation', { deployment_authorization_digest: authorizationDigest, instance_id: request.instance_id, occurrence_id: root.occurrence_id });
    let deadlines: Row[];
    try { deadlines = rootDeadlines.map((row: Row) => deadlineState(row, root, activation, '0', request.initial_clocks.find((clockRow: Row) => clockRow.source === row.clock_source)!, null)); }
    catch (error) { if (error instanceof AdmissionError && error.code === 'TIME_RANGE') fail('LIMIT_EXCEEDED'); throw error; }
    for (const row of deadlines) {
      const at = wholeSecond(row.activation_instant), due = wholeSecond(row.due);
      if (row.boundary === 'AT_OR_AFTER' ? at >= due : at > due) fail('CLOCK_INVALID');
    }
    const proposalSteps = request.definition.steps.filter((row: Row) => ['OPERATION', 'FANOUT_EXPAND'].includes(row.kind));
    const state: Row = {
      schema: VERSION + '/work-state', specification_pin: selectedPin, work_class_digest: admitted.digest, profile: request.profile, role: request.role, instance_id: request.instance_id,
      deployment_authorization: clone(authorization), deployment_authorization_subject_digest: subjectDigest, deployment_authorization_digest: authorizationDigest,
      deployment_authorization_evidence: clone(evidence), deployment_authorization_evidence_digest: evidenceDigest,
      deployment_correspondence_evidence: clone(correspondence), deployment_correspondence_evidence_digest: correspondenceDigest,
      deployment_source_confirmation_evidence: clone(confirmation), deployment_source_confirmation_evidence_digest: confirmationDigest,
      deployment_policy_decision_evidence: clone(decision), deployment_policy_decision_evidence_digest: decisionDigest,
      deployment_authorization_clock: clone(clock), deployment_organization_id: authorization.organization_id,
      revision: '0', status: 'ACTIVE', total_activations: '1', total_actuations: '0',
      step_counters: proposalSteps.map((row: Row) => ({ step_id: row.id, activations: row.id === request.definition.root ? '1' : '0', actuations: '0' })).sort((a: Row, b: Row) => byteCompare(a.step_id, b.step_id)),
      active: [{ occurrence: root, activation_event_digest: activation, status: 'ACTIVE', deadline_ids: rootDeadlines.map((row: Row) => row.id).sort(byteCompare) }],
      completed: [], obligations: [], proposals: [], permits: [], dispatches: [], outcomes: [], clocks: clone(request.initial_clocks), deadlines, fanout_passes: [], receipts: [], replays: [],
    };
    sortStateDeadlines(state);
    requireShape('lifecycle.schema.json', 'state', state);
    return { status: 'DEPLOYED', profile: request.profile, role: request.role, instance_id: request.instance_id, work_class_digest: admitted.digest, deployment_authorization_digest: authorizationDigest, state, state_digest: stateDigest(state) };
  } catch (error) { return deployFailure(input, error); }
}

const AUTHORITY_ADMISSION = new Set(['SCHEMA_INVALID', 'ARTIFACT_ENCODING_INVALID', 'ARTIFACT_NONCANONICAL', 'TYPE_INVALID', 'INPUT_INVALID', 'LIMIT_EXCEEDED', 'VERSION_UNSUPPORTED', 'DEPENDENCY_MISMATCH', 'UNSUPPORTED_RELATION', 'REFERENCE_INVALID', 'BINDING_MISMATCH']);

function proposalStep(definition: Row, stepId: string): Row { const row = definition.steps.find((step: Row) => step.id === stepId); if (!row || !['OPERATION', 'FANOUT_EXPAND'].includes(row.kind)) fail('REFERENCE_INVALID'); return row; }
function authorityProjection(definition: Row): Row {
  const steps = definition.steps.filter((row: Row) => ['OPERATION', 'FANOUT_EXPAND'].includes(row.kind)).map((row: Row) => ({ id: row.id, operation: row.operation, interface: row.interface, executor_role: row.executor_role, fields: clone(row.fields), scope_fields: clone(row.scope_fields), required_credentials: clone(row.required_credentials) })).sort((a: Row, b: Row) => byteCompare(a.id, b.id));
  const typeIds = new Set<string>(steps.flatMap((row: Row) => row.fields.map((field: Row) => field.type_ref)));
  const types = definition.types.filter((row: Row) => typeIds.has(row.id)).map(clone).sort((a: Row, b: Row) => byteCompare(a.id, b.id));
  return { schema: VERSION + '/authority-work-class', id: definition.id, revision: definition.revision, types, steps };
}

function ancestorOccurrences(state: Row, start: Row): Set<string> {
  const byOccurrence = new Map<string, Row>([...state.active, ...state.completed].map((row: Row) => [row.occurrence.occurrence_id, row.occurrence]));
  const result = new Set<string>(), pending = [...start.predecessor_occurrence_ids];
  while (pending.length) {
    const id = pending.pop()!;
    if (result.has(id)) continue;
    result.add(id);
    const row = byOccurrence.get(id);
    if (!row) fail('STATE_INVALID');
    pending.push(...row!.predecessor_occurrence_ids);
  }
  return result;
}

function establishingOutcome(state: Row, completed: Row): Row {
  const rows = state.outcomes.filter((row: Row) => row.kind === 'GOVERNED' && row.classification === 'MATCHED' && row.disputed === false && row.native_evidence && digest('native-evidence', row.native_evidence) === completed.evidence_digest && row.permit_digest !== null && state.permits.some((permit: Row) => permit.permit_id === row.permit_digest && permit.occurrence.occurrence_id === completed.occurrence.occurrence_id));
  if (rows.length === 0) fail('PREREQUISITE_MISSING');
  if (rows.length !== 1) fail('BINDING_MISMATCH');
  return rows[0];
}

function uniqueCompletedAncestor(state: Row, current: Row, stepId: string): { completed: Row; outcome: Row; permit: Row } {
  const ancestors = ancestorOccurrences(state, current);
  const eligible = state.completed.filter((row: Row) => ancestors.has(row.occurrence.occurrence_id) && row.occurrence.step_id === stepId && row.disposition === 'SUCCEEDED');
  if (eligible.length === 0) fail('PREREQUISITE_MISSING');
  if (eligible.length !== 1) fail('BINDING_MISMATCH');
  const outcome = establishingOutcome(state, eligible[0]);
  const permit = state.permits.find((row: Row) => row.permit_id === outcome.permit_digest);
  if (!permit) fail('STATE_INVALID');
  return { completed: eligible[0], outcome, permit };
}

function priorEffectBases(state: Row, step: Row, event: Row): Row[] {
  return step.prior_effect_bindings.map((binding: Row) => {
    const selected = uniqueCompletedAncestor(state, event.occurrence, binding.source_step_id);
    const sources = selected.outcome.native_evidence.actual_fields.filter((row: Row) => row.name === binding.source_evidence_field);
    const targets = event.native_request.fields.filter((row: Row) => row.name === binding.target_request_field);
    if (sources.length !== 1 || targets.length !== 1) fail('BINDING_MISMATCH');
    if (!same(sources[0].value, targets[0].value)) fail('BINDING_MISMATCH');
    return {
      binding_id: binding.id,
      source_occurrence_id: selected.completed.occurrence.occurrence_id,
      source_permit_digest: selected.permit.permit_id,
      source_native_evidence_digest: digest('native-evidence', selected.outcome.native_evidence),
      source_field: binding.source_evidence_field,
      target_field: binding.target_request_field,
      value: clone(sources[0].value),
    };
  });
}

function selectedActBasis(bases: Row[], kind: string): Row {
  const rows = bases.filter((row: Row) => row.act.kind === kind);
  if (rows.length === 0) fail('PREREQUISITE_MISSING');
  if (rows.length !== 1) fail('BINDING_MISMATCH');
  return rows[0];
}

function separationBases(state: Row, step: Row, event: Row, currentBases: Row[], authorityResult: Row): { bases: Row[]; failed: Row | null } {
  const bases: Row[] = [];
  for (const requirement of step.prior_actor_separations) {
    const selected = uniqueCompletedAncestor(state, event.occurrence, requirement.prior_step_id);
    const prior = selectedActBasis(selected.permit.authority_act_bases, requirement.prior_act_kind);
    const current = selectedActBasis(currentBases, requirement.current_act_kind);
    const basis: Row = {
      requirement_id: requirement.id,
      relation: 'DISTINCT_ACTOR',
      prior_occurrence_id: selected.completed.occurrence.occurrence_id,
      current_occurrence_id: event.occurrence.occurrence_id,
      prior_act: clone(prior),
      current_act: clone(current),
    };
    if (prior.act.actor === current.act.actor) return { bases, failed: { authority_result: clone(authorityResult), basis } };
    bases.push(basis);
  }
  return { bases, failed: null };
}

function reservationNativeRequest(definition: Row, event: Row): Row {
  return { work_class: definition.id, instance: event.instance_id, occurrence: event.occurrence.occurrence_id, step: event.occurrence.step_id, operation: event.native_request.operation, interface: event.native_request.interface, fields: clone(event.native_request.fields) };
}

function reservationProposalTransition(request: Row, event: Row, step: Row, priorPermit: Row | null, selectedClock: Row): Row {
  if (event.budget_inputs.length !== 1) fail('DEPENDENCY_MISMATCH');
  const input = event.budget_inputs[0], registryRequest = input.request;
  if (!same(input.affected_anchors, step.shared_budgets)) fail('BINDING_MISMATCH');
  const registryDigest = digest('reservation-registry', registryRequest.state.core.configuration);
  if (input.registry_digest !== registryDigest || registryRequest.host_evidence.registry_digest !== registryDigest || registryRequest.specification_pin !== request.specification_pin) fail('BINDING_MISMATCH');
  if (input.expected_revision !== registryRequest.event.expected_revision || input.expected_revision !== registryRequest.state.core.revision) fail('REVISION_CONFLICT');
  if (registryRequest.state_digest !== digest('reservation-state', registryRequest.state)) fail('DEPENDENCY_MISMATCH');
  const slots = registryRequest.state.core.configuration.slots.filter((row: Row) => step.shared_budgets.includes(row.anchor));
  if (slots.length !== step.shared_budgets.length) fail('DEPENDENCY_MISMATCH');
  const budgets = registryRequest.state.core.budgets.filter((row: Row) => step.shared_budgets.includes(row.definition.anchor));
  if (budgets.length !== step.shared_budgets.length) fail('DEPENDENCY_MISMATCH');
  for (const budget of budgets) {
    const policy = budget.definition.reservation_policy, carrier = step.completion;
    if (policy.settlement.provider !== carrier.effect_provider || policy.settlement.source !== carrier.effect_source || policy.no_effect.provider !== carrier.no_effect_provider || policy.no_effect.source !== carrier.no_effect_source) fail('UNSUPPORTED_RELATION');
  }
  const reservationKind = priorPermit ? 'RENEW' : 'RESERVE';
  const expectedId = digest('lifecycle-reservation-event', { instance_id: event.instance_id, lifecycle_event_id: event.event_id, lifecycle_event_kind: 'PROPOSE', reservation_event_kind: reservationKind, registry_digest: registryDigest });
  const expectedClock = { source: selectedClock.source, status: 'AVAILABLE', instant: selectedClock.observed_time };
  if (registryRequest.event.id !== expectedId || registryRequest.event.kind !== reservationKind || !same(registryRequest.event.clock, expectedClock) || !same(registryRequest.event.payload.authority, event.authority_input) || registryRequest.event.administration !== null) fail('BINDING_MISMATCH');
  if (reservationKind === 'RENEW') {
    const revision = priorPermit!.budget_revisions[0];
    if (!revision || registryRequest.event.payload.reservation !== revision.reservation_id) fail('BINDING_MISMATCH');
  } else if ('reservation' in registryRequest.event.payload) fail('BINDING_MISMATCH');
  const result = aggregateStep(registryRequest, request.specification_pin);
  if (result.status === 'REFUSED') fail(result.code);
  return { registry_digest: registryDigest, affected_anchors: clone(step.shared_budgets), result };
}

function propose(request: Row, event: Row): Row {
  const state = request.state, definition = request.definition, active = state.active.find((row: Row) => row.occurrence.occurrence_id === event.occurrence.occurrence_id);
  if (event.instance_id !== state.instance_id || !same(event.occurrence, active?.occurrence)) fail('BINDING_MISMATCH');
  if (state.status !== 'ACTIVE') fail('INSTANCE_NOT_ACTIVE');
  if (!active) fail('OCCURRENCE_NOT_ACTIVE');
  const step = proposalStep(definition, event.occurrence.step_id);
  if (!['ACTIVE', 'PERMITTED'].includes(active.status)) fail('PREREQUISITE_MISSING');
  const renewal = active.status === 'PERMITTED';
  const priorPermit = renewal ? [...state.permits].reverse().find((row: Row) => row.occurrence.occurrence_id === active.occurrence.occurrence_id && !state.permits.some((later: Row) => later.supersedes_permit_digest === row.permit_id)) : null;
  if (renewal && !priorPermit) fail('STATE_INVALID');
  if (!renewal && (state.permits.some((row: Row) => row.occurrence.occurrence_id === active.occurrence.occurrence_id) || state.outcomes.some((row: Row) => row.kind === 'GOVERNED' && row.permit_digest && state.permits.some((permit: Row) => permit.permit_id === row.permit_digest && permit.occurrence.occurrence_id === active.occurrence.occurrence_id)))) fail('PREREQUISITE_MISSING');
  if (renewal) {
    if (state.dispatches.some((row: Row) => row.permit_digest === priorPermit!.permit_id && (row.attempt.status !== 'NOT_SENT' || row.acknowledgement.status === 'ACCEPTED'))) fail('PREREQUISITE_MISSING');
    const clocks = state.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === priorPermit!.clock_source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1);
    if (!clocks.length || wholeSecond(clocks.at(-1)!.observed_time) < wholeSecond(priorPermit!.expires_at)) fail('PREREQUISITE_MISSING');
  }
  if (state.receipts.filter((row: Row) => row.event_kind === 'PROPOSE').length >= Number(definition.limits.maximum_proposals)) fail('LIMIT_EXCEEDED');
  if (event.native_request.interface !== step.interface || event.native_request.operation !== step.operation || !same(event.native_request.fields.map((row: Row) => ({ name: row.name, type_ref: row.value.type_ref })), step.fields)) fail('BINDING_MISMATCH');
  if (renewal && !same(event.native_request, priorPermit.native_request)) fail('BINDING_MISMATCH');
  for (const segment of event.occurrence.enclosing.filter((row: Row) => row.kind === 'FANOUT')) {
    const fanout = definition.fanouts.find((row: Row) => row.id === segment.construct_id);
    const fields = fanout ? event.native_request.fields.filter((row: Row) => row.name === fanout.object_request_field) : [];
    if (!fanout || fields.length !== 1 || fields[0].value.type_ref !== fanout.object_type_ref || !same(fields[0].value, segment.object_key)) fail('BINDING_MISMATCH');
  }
  const priorEffectRows = priorEffectBases(state, step, event);
  const participant = definition.participants.filter((row: Row) => row.id === event.executor.participant_id);
  const authority = event.authority_input, projection = authorityProjection(definition), authorityExecutor = authority.proposal.executor;
  if (participant.length !== 1 || participant[0].role !== step.executor_role || event.executor.role !== step.executor_role || authorityExecutor.actor !== event.executor.participant_id || authorityExecutor.role !== event.executor.role || event.executor.binding_digest !== digest('executor-binding', authorityExecutor)) fail('BINDING_MISMATCH');
  const projectionDigest = digest('authority-work-class', projection);
  if (!same(authority.work_class, projection) || authority.proposal.work_class !== definition.id || authority.proposal.work_class_digest !== projectionDigest || authority.envelope.work_class_digest !== projectionDigest || authority.proposal.instance !== event.instance_id || authority.proposal.occurrence !== event.occurrence.occurrence_id || authority.proposal.step !== step.id || authority.proposal.operation !== event.native_request.operation || authority.proposal.interface !== event.native_request.interface || !same(authority.proposal.fields, event.native_request.fields) || authority.envelope.id !== step.authority_requirements[0]) fail('BINDING_MISMATCH');
  if (authority.source.id !== definition.source.id || authority.source.revision !== definition.source.revision || !same(authority.source.obligations.map((row: Row) => row.id), definition.source.obligations)) fail('BINDING_MISMATCH');
  const credentialIds = authority.credentials.map((row: Row) => row.id).sort(byteCompare);
  const observationDigests = authority.observations.map((row: Row) => digest('authority-observation', row)).sort(byteCompare);
  if (!same(event.credential_ids, credentialIds) || !same(event.observation_digests, observationDigests)) fail('BINDING_MISMATCH');
  const retainedClock = event.clock_revision === null ? null : state.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === authority.clock.source && row.revision === event.clock_revision)[0];
  if (authority.clock.status === 'AVAILABLE' && (!retainedClock || retainedClock.observed_time !== authority.clock.instant)) fail('BINDING_MISMATCH');
  if (authority.clock.status !== 'AVAILABLE' && event.clock_revision !== null) fail('BINDING_MISMATCH');
  if (!same(step.shared_budgets, authority.envelope.limits.shared_budgets)) fail('BINDING_MISMATCH');
  if (step.shared_budgets.length === 0 && event.budget_inputs.length !== 0) fail('DEPENDENCY_MISMATCH');

  const authorityResult = evaluateAuthority(authority, request.specification_pin), authorityResultDigest = digest('authority-result', authorityResult), eDigest = eventDigest(event), pDigest = digest('proposal', event);
  if (authorityResult.status !== 'READY_FOR_RESERVATION') {
    if (AUTHORITY_ADMISSION.has(authorityResult.code)) fail(authorityResult.code);
    const next = clone(state), reasons = sortStrings(['AUTHORITY_REQUIRED', authorityResult.code, ...authorityResult.reasons]);
    next.proposals.push({ event_id: event.event_id, event_digest: eDigest, proposal_digest: pDigest, occurrence_id: active.occurrence.occurrence_id, disposition: 'WITHHELD', permit_digest: null, authority_result_digest: authorityResultDigest, reservation_receipt_digests: [], prior_permit_digest: priorPermit?.permit_id ?? null });
    sortedRows(next.proposals, row => row.event_id);
    return admittedTransition(request, next, event, { disposition: 'WITHHELD', reasons, details: [{ kind: 'AUTHORITY', authority_result_digest: authorityResultDigest, code: authorityResult.code, reasons: authorityResult.reasons, failed_checks: authorityResult.failed_checks }], authorityResultDigest });
  }
  if (!same(authorityResult.required_budgets, step.shared_budgets)) fail('BINDING_MISMATCH');
  const actByDigest = new Map(authority.acts.map((act: Row) => [digest('authority-act', act), act]));
  const authorityActBases = authorityResult.act_digests.map((actDigest: string) => { const act = actByDigest.get(actDigest); if (!act) fail('BINDING_MISMATCH'); return { act_digest: actDigest, act: clone(act) }; }).sort((a: Row, b: Row) => byteCompare(a.act_digest, b.act_digest));
  const separation = separationBases(state, step, event, authorityActBases, authorityResult);
  if (separation.failed) {
    const next = clone(state);
    next.proposals.push({ event_id: event.event_id, event_digest: eDigest, proposal_digest: pDigest, occurrence_id: active.occurrence.occurrence_id, disposition: 'WITHHELD', permit_digest: null, authority_result_digest: authorityResultDigest, reservation_receipt_digests: [], prior_permit_digest: priorPermit?.permit_id ?? null });
    sortedRows(next.proposals, row => row.event_id);
    return admittedTransition(request, next, event, { disposition: 'WITHHELD', reasons: ['SEPARATION_VIOLATED'], details: [{ kind: 'SEPARATION', authority_result: separation.failed.authority_result, basis: separation.failed.basis }], authorityResultDigest });
  }
  if (!renewal && BigInt(state.total_actuations) >= BigInt(definition.limits.maximum_actuations)) {
    const next = clone(state), details = [{ kind: 'LIMIT', limit_kind: 'ACTUATIONS', limit: definition.limits.maximum_actuations, current: (BigInt(state.total_actuations) + 1n).toString(), step_id: step.id, relationship_digest: null }];
    next.status = 'STOPPED';
    return admittedTransition(request, next, event, { disposition: 'STOPPED', reasons: ['LIMIT_EXCEEDED'], details, authorityResultDigest });
  }
  let expiresAt: string;
  try { expiresAt = instantText(wholeSecond(authority.clock.instant) + BigInt(step.permit_seconds) * 1_000_000_000n); }
  catch { return fail('LIMIT_EXCEEDED'); }
  let budgetResults: Row[] = [], budgetRevisions: Row[] = [], reservationReceiptDigests: string[] = [];
  if (step.shared_budgets.length) {
    if (!retainedClock) fail('BINDING_MISMATCH');
    const budgetResult = reservationProposalTransition(request, event, step, priorPermit, retainedClock);
    budgetResults = [budgetResult];
    const receipt = budgetResult.result.receipt;
    reservationReceiptDigests = [budgetResult.result.receipt_digest];
    if (receipt.decision === 'WITHHELD') {
      const next = clone(state), reasons = sortStrings(['BUDGET_WITHHELD', ...receipt.reasons]);
      next.proposals.push({ event_id: event.event_id, event_digest: eDigest, proposal_digest: pDigest, occurrence_id: active.occurrence.occurrence_id, disposition: 'WITHHELD', permit_digest: null, authority_result_digest: authorityResultDigest, reservation_receipt_digests: reservationReceiptDigests, prior_permit_digest: priorPermit?.permit_id ?? null });
      sortedRows(next.proposals, row => row.event_id);
      return admittedTransition(request, next, event, { disposition: 'WITHHELD', reasons, details: [{ kind: 'BUDGET', registry_digest: budgetResult.registry_digest, receipt_digest: budgetResult.result.receipt_digest, reasons: clone(receipt.reasons) }], authorityResultDigest, budgetResults });
    }
    const expectedDecision = renewal ? 'RENEWED' : 'RESERVED';
    if (receipt.decision !== expectedDecision || receipt.reservation === null) fail('STATE_INVALID');
    const reservation = budgetResult.result.state.core.reservations.find((row: Row) => row.id === receipt.reservation);
    if (!reservation) fail('STATE_INVALID');
    if (wholeSecond(reservation.permit_until) < wholeSecond(expiresAt)) expiresAt = reservation.permit_until;
    budgetRevisions = [{ registry_digest: budgetResult.registry_digest, affected_anchors: clone(budgetResult.affected_anchors), revision: budgetResult.result.state.core.revision, reservation_id: receipt.reservation, receipt_digest: budgetResult.result.receipt_digest }];
  }
  const permit: Row = {
    schema: VERSION + '/permit', permit_id: '', instance_id: event.instance_id, work_class_digest: request.definition_digest, profile: request.profile, role: request.role,
    occurrence: clone(event.occurrence), proposal_digest: pDigest, native_request: clone(event.native_request), executor: clone(event.executor), credential_ids: clone(event.credential_ids),
    authority_result: clone(authorityResult), authority_result_digest: authorityResultDigest, authority_evidence_digest: authorityResult.evidence_digest, authority_act_bases: authorityActBases,
    prior_effect_bases: priorEffectRows, separation_bases: separation.bases, observation_digests: clone(event.observation_digests), supersedes_permit_digest: priorPermit?.permit_id ?? null, budget_revisions: budgetRevisions,
    clock_source: authority.clock.source, clock_revision: event.clock_revision, expires_at: expiresAt,
  };
  permit.permit_id = permitDigest(permit);
  const next = clone(state);
  const nextActive = next.active.find((row: Row) => row.occurrence.occurrence_id === event.occurrence.occurrence_id)!; nextActive.status = 'PERMITTED';
  next.proposals.push({ event_id: event.event_id, event_digest: eDigest, proposal_digest: pDigest, occurrence_id: event.occurrence.occurrence_id, disposition: 'PERMITTED', permit_digest: permit.permit_id, authority_result_digest: authorityResultDigest, reservation_receipt_digests: reservationReceiptDigests, prior_permit_digest: priorPermit?.permit_id ?? null });
  next.permits.push(clone(permit)); sortedRows(next.proposals, row => row.event_id); sortedRows(next.permits, row => row.permit_id);
  if (!renewal) { next.total_actuations = (BigInt(next.total_actuations) + 1n).toString(); const counter = next.step_counters.find((row: Row) => row.step_id === step.id)!; counter.actuations = (BigInt(counter.actuations) + 1n).toString(); }
  return admittedTransition(request, next, event, { disposition: 'PERMITTED', permit, authorityResultDigest, budgetResults });
}

function dispatch(request: Row, event: Row): Row {
  const state = request.state, suppliedPermit = event.permit, retainedPermit = state.permits.find((row: Row) => row.permit_id === suppliedPermit.permit_id);
  if (!retainedPermit) fail('PREREQUISITE_MISSING');
  if (!same(retainedPermit, suppliedPermit) || event.instance_id !== state.instance_id || suppliedPermit.instance_id !== state.instance_id) fail('BINDING_MISMATCH');
  const active = state.active.find((row: Row) => row.occurrence.occurrence_id === suppliedPermit.occurrence.occurrence_id), completed = state.completed.find((row: Row) => row.occurrence.occurrence_id === suppliedPermit.occurrence.occurrence_id);
  const available = state.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === suppliedPermit.clock_source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1);
  const dispatchClock = available.at(-1), issuanceClock = available.find((row: Row) => row.revision === suppliedPermit.clock_revision);
  if (!dispatchClock || event.clock_revision !== dispatchClock.revision || !issuanceClock) fail('CLOCK_INVALID');
  const at = wholeSecond(event.attempt.attempted_at), issued = wholeSecond(issuanceClock.observed_time), selected = wholeSecond(dispatchClock.observed_time);
  if (at < issued || at > selected) fail('CLOCK_INVALID');
  if (event.acknowledgement.status === 'NONE') {
    if (event.acknowledgement.reference !== null || event.acknowledgement.observed_at !== null) fail('INPUT_INVALID');
  } else {
    if (event.acknowledgement.reference === null || event.acknowledgement.observed_at === null) fail('INPUT_INVALID');
    const ack = wholeSecond(event.acknowledgement.observed_at); if (ack < at) fail('INPUT_INVALID'); if (ack > selected) fail('CLOCK_INVALID');
  }
  const requestDigest = digest('dispatch-native-request', { instance_id: event.instance_id, occurrence_id: suppliedPermit.occurrence.occurrence_id, interface: event.native_request.interface, operation: event.native_request.operation, fields: event.native_request.fields });
  if (event.attempt.request_digest !== requestDigest || event.connector.binding_digest !== digest('connector-binding', { id: event.connector.id, version: event.connector.version })) fail('BINDING_MISMATCH');
  const attemptDigest = digest('dispatch-attempt', { permit_id: suppliedPermit.permit_id, native_request: event.native_request, connector: event.connector, attempt: event.attempt });
  const earlier = state.dispatches.filter((row: Row) => row.permit_digest === suppliedPermit.permit_id);
  const update = earlier.find((row: Row) => row.dispatch_attempt_digest === attemptDigest);
  if (update) {
    if (!same(update.native_request, event.native_request) || !same(update.connector, event.connector) || !same(update.attempt, event.attempt)) fail('BINDING_MISMATCH');
    if (!['NONE', 'UNKNOWN'].includes(update.acknowledgement.status) || !['ACCEPTED', 'REJECTED'].includes(event.acknowledgement.status)) fail('PREREQUISITE_MISSING');
  } else if (earlier.some((row: Row) => row.attempt.attempt_id === event.attempt.attempt_id)) fail('BINDING_MISMATCH');
  // LIFE-009: a consumed permit admits a fresh attempt that may have reached the connector (SENT, UNKNOWN, REJECTED or an
  // accepted acknowledgement) as a late dispatch; a fresh NOT_SENT attempt with no accepted acknowledgement is PREREQUISITE_MISSING.
  const consumed = !update && earlier.some((row: Row) => row.attempt.status !== 'NOT_SENT' || row.acknowledgement.status === 'ACCEPTED');
  if (consumed && !(['SENT', 'UNKNOWN', 'REJECTED'].includes(event.attempt.status) || event.acknowledgement.status === 'ACCEPTED')) fail('PREREQUISITE_MISSING');

  const reasons: string[] = [];
  const matches = same(event.native_request, suppliedPermit.native_request);
  if (!matches) reasons.push('NATIVE_ARGUMENT_MISMATCH');
  if (update) {
    const originalDecision = state.receipts.find((row: Row) => row.event_id === update.event_id && row.event_kind === 'DISPATCH_OBSERVED');
    if (!originalDecision) fail('STATE_INVALID');
    reasons.push(...originalDecision.reason_codes.filter((reason: string) => ['PERMIT_EXPIRED', 'PERMIT_SUPERSEDED', 'LATE_OR_PROHIBITED_DISPATCH'].includes(reason)));
  } else {
    if (at >= wholeSecond(suppliedPermit.expires_at)) reasons.push('PERMIT_EXPIRED');
    if (state.permits.some((row: Row) => row.supersedes_permit_digest === suppliedPermit.permit_id)) reasons.push('PERMIT_SUPERSEDED');
    if (state.status !== 'ACTIVE' || !active || active.status !== 'PERMITTED' || completed || consumed) reasons.push('LATE_OR_PROHIBITED_DISPATCH');
  }
  let disposition: string;
  const attemptStatus = event.attempt.status, acknowledgement = event.acknowledgement.status;
  if (attemptStatus === 'NOT_SENT') { if (acknowledgement === 'ACCEPTED') { disposition = 'DISPUTED'; reasons.push('DISPATCH_EVIDENCE_CONFLICT'); } else { disposition = 'DISPATCH_REFUSED'; reasons.push('NATIVE_NOT_SENT'); } }
  else if (attemptStatus === 'REJECTED') { if (acknowledgement === 'ACCEPTED') { disposition = 'DISPUTED'; reasons.push('DISPATCH_EVIDENCE_CONFLICT'); } else { disposition = 'DISPATCH_REFUSED'; reasons.push('NATIVE_DISPATCH_REJECTED'); } }
  else if (acknowledgement === 'ACCEPTED') disposition = 'ACKNOWLEDGED';
  else { disposition = 'DISPATCH_RECORDED'; if (attemptStatus === 'UNKNOWN' || acknowledgement === 'UNKNOWN') reasons.push('DISPATCH_STATUS_UNKNOWN'); else if (acknowledgement === 'REJECTED') reasons.push('ACKNOWLEDGEMENT_REJECTED'); }
  const disqualifying = reasons.some(reason => ['NATIVE_ARGUMENT_MISMATCH', 'PERMIT_EXPIRED', 'PERMIT_SUPERSEDED', 'LATE_OR_PROHIBITED_DISPATCH'].includes(reason));
  if (disqualifying && !(attemptStatus === 'NOT_SENT' && acknowledgement !== 'ACCEPTED') && !(matches && attemptStatus === 'REJECTED' && acknowledgement !== 'ACCEPTED')) disposition = 'DISPUTED';
  const finalReasons = sortStrings(reasons);
  const eDigest = eventDigest(event);
  const record: Row = { dispatch_digest: '', dispatch_attempt_digest: attemptDigest, event_id: event.event_id, event_digest: eDigest, permit_digest: suppliedPermit.permit_id, native_request: clone(event.native_request), connector: clone(event.connector), attempt: clone(event.attempt), acknowledgement: clone(event.acknowledgement), clock_revision: event.clock_revision };
  record.dispatch_digest = digest('dispatch', omitted(record, 'dispatch_digest'));
  const next = clone(state); next.dispatches.push(record); sortedRows(next.dispatches, row => row.dispatch_digest);
  const nextActive = next.active.find((row: Row) => row.occurrence.occurrence_id === suppliedPermit.occurrence.occurrence_id);
  if (!update && nextActive) { if (disposition === 'DISPUTED' && nextActive.status === 'PERMITTED') nextActive.status = 'OUTCOME_UNKNOWN'; else if (['DISPATCH_RECORDED', 'ACKNOWLEDGED'].includes(disposition)) nextActive.status = 'DISPATCHED'; }
  return admittedTransition(request, next, event, { disposition, reasons: finalReasons, details: [{ kind: 'DISPATCH', attempt_id: event.attempt.attempt_id, reasons: finalReasons }], decisionPermitDigest: suppliedPermit.permit_id });
}

function outcomeDigest(outcome: Row): string { return digest('outcome', omitted(outcome, 'outcome_digest')); }
function nativeEvidenceDigest(evidence: Row): string { return digest('native-evidence', evidence); }
function nativeFactDigest(evidence: Row): string { const value = clone(evidence); delete value.evidence_id; delete value.evidence_ref; return digest('native-evidence-fact', value); }
function dispatchReceipt(state: Row, dispatchRow: Row): Row {
  const receipt = state.receipts.find((row: Row) => row.event_id === dispatchRow.event_id && row.event_kind === 'DISPATCH_OBSERVED');
  if (!receipt) fail('STATE_INVALID');
  return receipt!;
}
function attributedRequest(definition: Row, instanceId: string, permit: Row, dispatchRow: Row): Row {
  return { work_class: definition.id, instance: instanceId, occurrence: permit.occurrence.occurrence_id, step: permit.occurrence.step_id, operation: dispatchRow.native_request.operation, interface: dispatchRow.native_request.interface, fields: clone(dispatchRow.native_request.fields) };
}
function dispatchDisqualified(state: Row, dispatchRow: Row): boolean {
  return dispatchReceipt(state, dispatchRow).reason_codes.some((reason: string) => ['NATIVE_ARGUMENT_MISMATCH', 'PERMIT_EXPIRED', 'PERMIT_SUPERSEDED', 'LATE_OR_PROHIBITED_DISPATCH'].includes(reason));
}
function dispatchEligible(state: Row, permit: Row, dispatchRow: Row): boolean {
  return !dispatchDisqualified(state, dispatchRow) && !dispatchReceipt(state, dispatchRow).reason_codes.includes('DISPATCH_EVIDENCE_CONFLICT') && (['SENT', 'UNKNOWN', 'REJECTED'].includes(dispatchRow.attempt.status) || dispatchRow.acknowledgement.status === 'ACCEPTED');
}
function finalSafeAttempt(state: Row, permit: Row, dispatchRow: Row): boolean {
  const rows = state.dispatches.filter((row: Row) => row.permit_digest === permit.permit_id);
  const firstByAttempt = new Map<string, Row>();
  for (const receipt of state.receipts) {
    if (receipt.event_kind !== 'DISPATCH_OBSERVED') continue;
    const row = rows.find((candidate: Row) => candidate.event_id === receipt.event_id);
    if (row && !firstByAttempt.has(row.dispatch_attempt_digest)) firstByAttempt.set(row.dispatch_attempt_digest, row);
  }
  const attempts = [...firstByAttempt.values()];
  if (!attempts.length || attempts.at(-1)!.dispatch_attempt_digest !== dispatchRow.dispatch_attempt_digest) return false;
  return attempts.slice(0, -1).every((row: Row) => row.attempt.status === 'NOT_SENT' && !rows.some((candidate: Row) => candidate.dispatch_attempt_digest === row.dispatch_attempt_digest && candidate.acknowledgement.status === 'ACCEPTED'));
}

function completionFields(step: Row, evidence: Row, dispatchRow: Row): { kind: 'SUCCESS' | 'FAILURE' | 'UNEXPECTED'; label: Row | null; labelInvalid: boolean; observedRequest: boolean } {
  const carrier = step.completion, actual = evidence.actual_fields;
  const byName = new Map<string, Row[]>();
  for (const field of actual) byName.set(field.name, [...(byName.get(field.name) ?? []), field]);
  const requestFields = new Map<string, Row>(dispatchRow.native_request.fields.map((row: Row) => [row.name, row]));
  let matching = true;
  const allowed = new Set<string>([carrier.status_field]);
  for (const binding of carrier.evidence_bindings) {
    allowed.add(binding.evidence_field);
    const sources = byName.get(binding.evidence_field) ?? [], target = requestFields.get(binding.request_field);
    if (sources.length !== 1 || !target || !same(sources[0].value, target.value)) matching = false;
  }
  const statusRows = byName.get(carrier.status_field) ?? [];
  if (statusRows.length !== 1 || statusRows[0].value.type_ref !== carrier.status_type_ref) matching = false;
  const success = matching && carrier.success_values.some((value: Row) => same(value, statusRows[0]?.value));
  const failure = matching && carrier.failure_values.some((value: Row) => same(value, statusRows[0]?.value));
  let label: Row | null = null, labelInvalid = false;
  if (success && carrier.route_label_field !== null) {
    allowed.add(carrier.route_label_field);
    const rows = byName.get(carrier.route_label_field) ?? [];
    if (rows.length === 1) label = clone(rows[0].value);
    if (rows.length !== 1 || rows[0].value.type_ref !== carrier.route_label_type_ref) labelInvalid = true;
  }
  if (actual.some((row: Row) => !allowed.has(row.name))) matching = false;
  // LIFE-010 ties observed_request to the evidence fields; an unexpected collection on an operation step
  // makes the record completion-mismatched without making its fields unprojectable.
  const observedRequest = matching && requestFieldsFromActual(dispatchRow, step, evidence);
  if (step.kind !== 'FANOUT_EXPAND' && evidence.collections.length) matching = false;
  if (!matching || (!success && !failure)) return { kind: 'UNEXPECTED', label, labelInvalid: false, observedRequest };
  return { kind: success ? 'SUCCESS' : 'FAILURE', label, labelInvalid, observedRequest };
}

function requestFieldsFromActual(dispatchRow: Row, step: Row, evidence: Row): boolean {
  const actual = new Map<string, Row>(evidence.actual_fields.map((row: Row) => [row.name, row.value]));
  const fields: Row[] = [];
  for (const binding of step.completion.evidence_bindings) {
    const value = actual.get(binding.evidence_field);
    if (!value) return false;
    fields.push({ name: binding.request_field, value: clone(value) });
  }
  fields.sort((a: Row, b: Row) => byteCompare(a.name, b.name));
  return same(fields, dispatchRow.native_request.fields);
}

function noEffectAuthorization(state: Row, event: Row, permit: Row, evidenceDigest: string): void {
  const authorization = event.completion_authorization;
  if (!authorization) fail('EVIDENCE_UNAVAILABLE');
  const subject = digest('no-effect-completion', { specification_pin: state.specification_pin, work_class_digest: state.work_class_digest, instance_id: state.instance_id, occurrence_id: permit.occurrence.occurrence_id, permit_id: permit.permit_id, dispatch_digest: event.dispatch_digest, native_evidence_digest: evidenceDigest });
  const scope = sortStrings([state.specification_pin, state.work_class_digest, state.instance_id, permit.occurrence.occurrence_id, permit.permit_id, event.dispatch_digest, evidenceDigest]);
  if (authorization.subject_digest !== subject || authorization.organization_id !== state.deployment_organization_id || !same(authorization.authorization_scope, scope)) fail('BINDING_MISMATCH');
  if (authorization.status !== 'ACCEPTED' || authorization.expires_at === null || wholeSecond(authorization.recorded_at) > wholeSecond(event.native_evidence.observed_at) || wholeSecond(event.native_evidence.observed_at) >= wholeSecond(authorization.expires_at)) fail('EVIDENCE_UNAVAILABLE');
}

function nextOrdinal(state: Row, stepId: string): string {
  const rows = [...state.active, ...state.completed].filter((row: Row) => row.occurrence.step_id === stepId);
  return rows.length ? (rows.reduce((maximum: bigint, row: Row) => BigInt(row.occurrence.ordinal) > maximum ? BigInt(row.occurrence.ordinal) : maximum, 0n) + 1n).toString() : '1';
}

function occurrenceById(state: Row, occurrenceId: string): Row | null {
  return [...state.active, ...state.completed].find((row: Row) => row.occurrence.occurrence_id === occurrenceId)?.occurrence ?? null;
}

function nextParallelPass(state: Row, constructId: string, outerEnclosing: Row[]): string {
  const passes: bigint[] = [];
  for (const row of [...state.active, ...state.completed]) {
    const segments = row.occurrence.enclosing as Row[];
    const index = segments.findIndex(segment => segment.kind === 'BRANCH' && segment.construct_id === constructId);
    if (index >= 0 && same(segments.slice(0, index), outerEnclosing)) passes.push(BigInt(segments[index].pass));
  }
  return passes.length ? (passes.reduce((maximum, value) => value > maximum ? value : maximum, 0n) + 1n).toString() : '1';
}

function nextFanoutPass(state: Row, fanoutId: string, outerEnclosing: Row[]): string {
  const passes: bigint[] = [];
  for (const pass of state.fanout_passes as Row[]) {
    if (pass.fanout_id !== fanoutId) continue;
    const expand = occurrenceById(state, pass.expand_occurrence_id);
    if (expand && same(expand.enclosing, outerEnclosing)) passes.push(BigInt(pass.pass));
  }
  return passes.length ? (passes.reduce((maximum, value) => value > maximum ? value : maximum, 0n) + 1n).toString() : '1';
}

function directTarget(definition: Row, state: Row, source: Row, relationship: Row, triggerDigest: string, activationClocks: Row[], predecessorIds: string[] = [source.occurrence_id], enclosingBase: Row[] | null = null): { occurrence: Row | null; deadlines: Row[]; limit: Row | null; deadlineReason: string | null; failedDeadlineIds: string[] } {
  const target = definition.steps.find((row: Row) => row.id === relationship.to);
  if (!target) fail('REFERENCE_INVALID');
  if (target.kind === 'TERMINAL') return { occurrence: null, deadlines: [], limit: null, deadlineReason: null, failedDeadlineIds: [] };
  if (!['OPERATION', 'FANOUT_EXPAND'].includes(target.kind)) fail('UNSUPPORTED_FEATURE');
  let enclosing = clone(enclosingBase ?? source.enclosing);
  let loopLimit: Row | null = null;
  const sourceLoop = definition.loops.find((row: Row) => row.member_step_ids.includes(source.step_id));
  const targetLoop = definition.loops.find((row: Row) => row.member_step_ids.includes(target.id));
  if (sourceLoop?.id === targetLoop?.id && sourceLoop) {
    const index = enclosing.findIndex((row: Row) => row.kind === 'LOOP' && row.construct_id === sourceLoop.id);
    if (index < 0) fail('STATE_INVALID');
    if (sourceLoop.back_edge_from_step_id === source.step_id && sourceLoop.entry_step_id === target.id) {
      const nextPass = BigInt(enclosing[index].pass) + 1n;
      if (nextPass > BigInt(sourceLoop.maximum_passes)) loopLimit = { kind: 'LIMIT', limit_kind: 'LOOP_PASSES', limit: sourceLoop.maximum_passes, current: nextPass.toString(), step_id: target.id, relationship_digest: digest('relationship', relationship) };
      else enclosing[index].pass = nextPass.toString();
    }
  } else {
    if (sourceLoop) enclosing = enclosing.filter((row: Row) => !(row.kind === 'LOOP' && row.construct_id === sourceLoop.id));
    if (targetLoop) enclosing.push({ kind: 'LOOP', construct_id: targetLoop.id, pass: '1', branch_id: null, object_key: null });
  }
  const limit = definition.occurrence_limits.find((row: Row) => row.step_id === target.id)!;
  const projectedStep = BigInt(state.step_counters.find((row: Row) => row.step_id === target.id)!.activations) + 1n;
  if (projectedStep > BigInt(limit.maximum)) return { occurrence: null, deadlines: [], limit: { kind: 'LIMIT', limit_kind: 'STEP_OCCURRENCES', limit: limit.maximum, current: projectedStep.toString(), step_id: target.id, relationship_digest: digest('relationship', relationship) }, deadlineReason: 'LIMIT_EXCEEDED', failedDeadlineIds: [] };
  if (loopLimit) return { occurrence: null, deadlines: [], limit: loopLimit, deadlineReason: 'LOOP_BOUND_REACHED', failedDeadlineIds: [] };
  const projectedTotal = BigInt(state.total_activations) + 1n;
  if (projectedTotal > BigInt(definition.limits.maximum_activations)) return { occurrence: null, deadlines: [], limit: { kind: 'LIMIT', limit_kind: 'ACTIVATIONS', limit: definition.limits.maximum_activations, current: projectedTotal.toString(), step_id: target.id, relationship_digest: digest('relationship', relationship) }, deadlineReason: 'LIMIT_EXCEEDED', failedDeadlineIds: [] };
  const objectKey = enclosing.filter((row: Row) => row.kind === 'FANOUT').at(-1)?.object_key ?? null;
  const nextOccurrence = occurrence(state.work_class_digest, state.instance_id, target.id, nextOrdinal(state, target.id), predecessorIds, enclosing, objectKey, state.specification_pin);
  const declarations = definition.deadlines.filter((row: Row) => row.step_id === target.id);
  const sources = sortStrings(declarations.map((row: Row) => row.clock_source));
  const suppliedSources = activationClocks.map((row: Row) => row.source);
  if (!same(suppliedSources, sortStrings(suppliedSources)) || suppliedSources.some((source: string) => !sources.includes(source))) fail('DEPENDENCY_MISMATCH');
  const deadlines: Row[] = [];
  for (const declaration of declarations) {
    const clock = activationClocks.find((row: Row) => row.source === declaration.clock_source);
    if (!clock) return { occurrence: null, deadlines: [], limit: null, deadlineReason: 'ACTIVATION_CLOCK_UNAVAILABLE', failedDeadlineIds: [declaration.id] };
    const retained = state.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === clock.source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1).at(-1);
    if (!retained || !same(retained, clock)) fail('DEPENDENCY_MISMATCH');
    let row: Row;
    try { row = deadlineState(declaration, nextOccurrence, triggerDigest, (BigInt(state.revision) + 1n).toString(), clock, state); }
    catch (error) {
      if (error instanceof AdmissionError && error.code === 'TIME_RANGE') return { occurrence: null, deadlines: [], limit: null, deadlineReason: 'DEADLINE_TIME_OVERFLOW', failedDeadlineIds: [declaration.id] };
      throw error;
    }
    if (declaration.boundary === 'AT_OR_AFTER' ? wholeSecond(clock.observed_time) >= wholeSecond(row.due) : wholeSecond(clock.observed_time) > wholeSecond(row.due)) return { occurrence: null, deadlines: [], limit: null, deadlineReason: 'DEADLINE_ALREADY_DUE', failedDeadlineIds: [declaration.id] };
    deadlines.push(row);
  }
  return { occurrence: nextOccurrence, deadlines, limit: null, deadlineReason: null, failedDeadlineIds: [] };
}

function directCompletionBasis(event: Row, active: Row, step: Row, evidenceDigest: string): Row {
  return { kind: 'DIRECT_EVENT', event_digest: eventDigest(event), occurrence_id: active.occurrence.occurrence_id, operation: step.operation, evidence_digest: evidenceDigest };
}

function directOwningObligation(state: Row, active: Row): Row | null {
  const owner = [...active.occurrence.enclosing].reverse().find((row: Row) => row.kind === 'BRANCH' || row.kind === 'FANOUT');
  if (!owner) return null;
  const rows = state.obligations.filter((row: Row) => row.construct_id === owner.construct_id && row.pass === owner.pass && row.expected_occurrence_id === active.occurrence.occurrence_id && row.status === 'OPEN' && (owner.kind === 'BRANCH' ? row.kind === 'PARALLEL_BRANCH' && row.branch_id === owner.branch_id : row.kind === 'FANOUT_OBJECT' && same(row.object_key, owner.object_key)));
  if (rows.length !== 1) fail('STATE_INVALID');
  return rows[0];
}

function dischargeDirectOwner(definition: Row, state: Row, active: Row, event: Row, evidenceDigest: string): void {
  const owner = directOwningObligation(state, active);
  if (!owner) return;
  owner.status = 'DISCHARGED'; owner.expected_occurrence_id = null; owner.required_operation = null; owner.waiting_on = null;
  owner.completion_basis = directCompletionBasis(event, active, proposalStep(definition, active.occurrence.step_id), evidenceDigest);
}

function completionFrontier(obligations: Row[], state: Row | null = null, seen = new Set<string>()): string[] {
  const frontier: string[] = [];
  for (const row of obligations) {
    if (seen.has(row.obligation_id)) fail('STATE_INVALID');
    const path = new Set(seen); path.add(row.obligation_id);
    if (!['DISCHARGED', 'JOINED'].includes(row.status) || !row.completion_basis) fail('STATE_INVALID');
    if (row.completion_basis.kind === 'DIRECT_EVENT') frontier.push(row.completion_basis.occurrence_id);
    else {
      if (!state || row.completion_basis.kind !== 'CHILD_PASS') fail('STATE_INVALID');
      const exactState = state as Row;
      const childIds = row.completion_basis.child_pass.obligation_ids as string[];
      const children = childIds.map(id => exactState.obligations.find((candidate: Row) => candidate.obligation_id === id));
      if (children.some(row => !row || row.status !== 'JOINED')) fail('STATE_INVALID');
      frontier.push(...completionFrontier(children as Row[], exactState, path));
    }
  }
  return sortStrings(frontier);
}

function blockDependents(state: Row, sourceOccurrenceId: string): void {
  const affected = new Set<string>([sourceOccurrenceId]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const row of [...state.active, ...state.completed]) {
      if (!affected.has(row.occurrence.occurrence_id) && row.occurrence.predecessor_occurrence_ids.some((id: string) => affected.has(id))) {
        affected.add(row.occurrence.occurrence_id); changed = true;
      }
    }
  }
  for (const active of state.active) if (active.occurrence.occurrence_id !== sourceOccurrenceId && affected.has(active.occurrence.occurrence_id)) active.status = 'BLOCKED_DISPUTE';
  for (const obligation of state.obligations) {
    if (obligation.status === 'OPEN' && obligation.expected_occurrence_id && affected.has(obligation.expected_occurrence_id)) obligation.status = 'BLOCKED';
    else if (obligation.status === 'DISCHARGED' && completionFrontier([obligation], state).some(id => affected.has(id))) obligation.status = 'DISPUTED';
  }
  changed = true;
  while (changed) {
    changed = false;
    const disputed = new Set(state.obligations.filter((row: Row) => row.status === 'DISPUTED').map((row: Row) => row.obligation_id));
    for (const obligation of state.obligations) {
      if (obligation.status === 'WAITING' && obligation.waiting_on.obligation_ids.some((id: string) => disputed.has(id))) { obligation.status = 'DISPUTED'; changed = true; }
    }
  }
}

function blockDirectOwner(state: Row, active: Row): void {
  const owner = directOwningObligation(state, active);
  if (owner?.status === 'OPEN') owner.status = 'BLOCKED';
}

function obligationSegment(owner: Row, segment: Row): boolean {
  return owner.kind === 'PARALLEL_BRANCH'
    ? segment.kind === 'BRANCH' && segment.construct_id === owner.construct_id && segment.pass === owner.pass && segment.branch_id === owner.branch_id
    : segment.kind === 'FANOUT' && segment.construct_id === owner.construct_id && segment.pass === owner.pass && same(segment.object_key, owner.object_key);
}

function obligationOuterEnclosing(state: Row, owner: Row): Row[] {
  const occurrences = [...state.active, ...state.completed].map((row: Row) => row.occurrence).sort((a: Row, b: Row) => byteCompare(canonical(a), canonical(b)));
  for (const occurrenceRow of occurrences) {
    const index = occurrenceRow.enclosing.findIndex((segment: Row) => obligationSegment(owner, segment));
    if (index >= 0) return clone(occurrenceRow.enclosing.slice(0, index));
  }
  return fail('STATE_INVALID');
}

function exactPass(definition: Row, state: Row, owner: Row): { childPass: Row; obligations: Row[] } {
  const outerEnclosing = obligationOuterEnclosing(state, owner);
  if (owner.kind === 'PARALLEL_BRANCH') {
    const block = definition.parallel_blocks.find((row: Row) => row.id === owner.construct_id && row.join_step_id === owner.join_step_id);
    if (!block) fail('STATE_INVALID');
    const obligations = block.branches.map((branch: Row) => state.obligations.find((row: Row) => row.kind === 'PARALLEL_BRANCH' && row.construct_id === owner.construct_id && row.pass === owner.pass && same(row.source_occurrence_ids, owner.source_occurrence_ids) && row.branch_id === branch.id));
    if (obligations.some((row: Row | undefined) => !row)) fail('STATE_INVALID');
    const exact = obligations as Row[];
    return { childPass: { kind: 'PARALLEL', construct_id: owner.construct_id, pass: owner.pass, outer_enclosing: outerEnclosing, obligation_ids: sortStrings(exact.map(row => row.obligation_id)) }, obligations: exact };
  }
  const passRow = state.fanout_passes.find((row: Row) => row.fanout_id === owner.construct_id && row.pass === owner.pass && row.obligation_ids.includes(owner.obligation_id));
  if (!passRow || passRow.joined) fail('STATE_INVALID');
  const obligations = passRow.obligation_ids.map((id: string) => state.obligations.find((row: Row) => row.obligation_id === id));
  if (obligations.some((row: Row | undefined) => !row)) fail('STATE_INVALID');
  return { childPass: { kind: 'FANOUT', construct_id: owner.construct_id, pass: owner.pass, outer_enclosing: outerEnclosing, obligation_ids: sortStrings([...passRow.obligation_ids]) }, obligations: obligations as Row[] };
}

function waitingParent(state: Row, childPass: Row): Row | null {
  const rows = state.obligations.filter((row: Row) => row.status === 'WAITING' && same(row.waiting_on, childPass));
  if (rows.length > 1) fail('STATE_INVALID');
  return rows[0] ?? null;
}

function markPassJoined(state: Row, childPass: Row, obligations: Row[]): void {
  for (const row of obligations) row.status = 'JOINED';
  if (childPass.kind === 'FANOUT') {
    const passRow = state.fanout_passes.find((row: Row) => row.fanout_id === childPass.construct_id && row.pass === childPass.pass && same(sortStrings([...row.obligation_ids]), childPass.obligation_ids));
    if (!passRow || passRow.joined) fail('STATE_INVALID');
    passRow.joined = true;
  }
}

function childPassFromRoute(target: RouteTarget, outerEnclosing: Row[]): Row {
  if (!target.obligations.length) fail('STATE_INVALID');
  const first = target.obligations[0];
  const kind = first.kind === 'PARALLEL_BRANCH' ? 'PARALLEL' : 'FANOUT';
  if (target.obligations.some((row: Row) => row.kind !== first.kind || row.construct_id !== first.construct_id || row.pass !== first.pass)) fail('STATE_INVALID');
  return { kind, construct_id: first.construct_id, pass: first.pass, outer_enclosing: clone(outerEnclosing), obligation_ids: sortStrings(target.obligations.map((row: Row) => row.obligation_id)) };
}

function resumeWaitingParent(definition: Row, parent: Row | null, target: RouteTarget, outerEnclosing: Row[]): void {
  if (!parent) return;
  if (target.obligations.length) {
    parent.status = 'WAITING'; parent.expected_occurrence_id = null; parent.required_operation = null; parent.completion_basis = null;
    parent.waiting_on = childPassFromRoute(target, outerEnclosing);
  } else if (target.occurrences.length === 1) {
    const successor = target.occurrences[0], successorStep = proposalStep(definition, successor.step_id);
    parent.status = 'OPEN'; parent.expected_occurrence_id = successor.occurrence_id; parent.required_operation = successorStep.operation; parent.waiting_on = null; parent.completion_basis = null;
  } else if (target.occurrences.length > 1) fail('STATE_INVALID');
}

function joinDischargedOwner(definition: Row, state: Row, owner: Row, relationship: Row, event: Row, activationClocks: Row[]): RouteTarget {
  const joinStep = definition.steps.find((row: Row) => row.id === relationship.to);
  const expectedKind = owner.kind === 'PARALLEL_BRANCH' ? 'PARALLEL_JOIN' : 'FANOUT_JOIN';
  if (!joinStep || joinStep.kind !== expectedKind || owner.join_step_id !== joinStep.id) fail('STATE_INVALID');
  const { childPass, obligations } = exactPass(definition, state, owner);
  const incomingDigest = digest('relationship', relationship);
  if (!obligations.every((row: Row) => row.status === 'DISCHARGED')) return { occurrences: [], deadlines: [], obligations: [], limit: null, deadlineReason: null, failedDeadlineIds: [], constructIds: [owner.construct_id], relationshipDigests: [incomingDigest] };
  const frontier = completionFrontier(obligations, state);
  const outgoing = definition.relationships.find((row: Row) => row.kind === 'SEQUENCE' && row.from === joinStep.id);
  if (!outgoing) fail('STATE_INVALID');
  const parent = waitingParent(state, childPass);
  const targetStep = definition.steps.find((row: Row) => row.id === outgoing.to);
  if (!targetStep) fail('STATE_INVALID');
  if (targetStep.kind === 'PARALLEL_JOIN' || targetStep.kind === 'FANOUT_JOIN') {
    if (!parent) fail('STATE_INVALID');
    const exactParent = parent as Row;
    markPassJoined(state, childPass, obligations);
    exactParent.status = 'DISCHARGED'; exactParent.expected_occurrence_id = null; exactParent.required_operation = null; exactParent.waiting_on = null;
    exactParent.completion_basis = { kind: 'CHILD_PASS', event_digest: eventDigest(event), child_pass: clone(childPass) };
    const continuation = joinDischargedOwner(definition, state, exactParent, outgoing, event, activationClocks);
    return { ...continuation, constructIds: sortStrings([owner.construct_id, ...continuation.constructIds]), relationshipDigests: sortStrings([incomingDigest, ...continuation.relationshipDigests]) };
  }
  const source = { occurrence_id: frontier[0], step_id: joinStep.id, enclosing: childPass.outer_enclosing };
  const continuation = relationshipTarget(definition, state, source, outgoing, eventDigest(event), activationClocks, frontier, childPass.outer_enclosing);
  if (continuation.limit || continuation.deadlineReason) return { ...continuation, constructIds: sortStrings([owner.construct_id, ...continuation.constructIds]), relationshipDigests: sortStrings([incomingDigest, ...continuation.relationshipDigests]) };
  markPassJoined(state, childPass, obligations);
  resumeWaitingParent(definition, parent, continuation, childPass.outer_enclosing);
  return { ...continuation, constructIds: sortStrings([owner.construct_id, ...continuation.constructIds]), relationshipDigests: sortStrings([incomingDigest, ...continuation.relationshipDigests]) };
}

function parallelJoinTarget(definition: Row, state: Row, active: Row, relationship: Row, event: Row, evidenceDigest: string, activationClocks: Row[]): RouteTarget | null {
  const target = definition.steps.find((row: Row) => row.id === relationship.to);
  if (!target || target.kind !== 'PARALLEL_JOIN') return null;
  const owner = directOwningObligation(state, active);
  if (!owner || owner.kind !== 'PARALLEL_BRANCH') fail('STATE_INVALID');
  const exactOwner = owner as Row;
  exactOwner.status = 'DISCHARGED'; exactOwner.expected_occurrence_id = null; exactOwner.required_operation = null; exactOwner.waiting_on = null;
  exactOwner.completion_basis = directCompletionBasis(event, active, proposalStep(definition, active.occurrence.step_id), evidenceDigest);
  const afterDirectObligations = clone(state.obligations), afterDirectPasses = clone(state.fanout_passes);
  const continuation = joinDischargedOwner(definition, state, exactOwner, relationship, event, activationClocks);
  if (continuation.limit || continuation.deadlineReason) { state.obligations = afterDirectObligations; state.fanout_passes = afterDirectPasses; }
  return continuation;
}

function fanoutJoinTarget(definition: Row, state: Row, active: Row, relationship: Row, event: Row, evidenceDigest: string, activationClocks: Row[]): RouteTarget | null {
  const target = definition.steps.find((row: Row) => row.id === relationship.to);
  if (!target || target.kind !== 'FANOUT_JOIN') return null;
  const owner = directOwningObligation(state, active);
  if (!owner || owner.kind !== 'FANOUT_OBJECT') fail('STATE_INVALID');
  const exactOwner = owner as Row;
  exactOwner.status = 'DISCHARGED'; exactOwner.expected_occurrence_id = null; exactOwner.required_operation = null; exactOwner.waiting_on = null;
  exactOwner.completion_basis = directCompletionBasis(event, active, proposalStep(definition, active.occurrence.step_id), evidenceDigest);
  const afterDirectObligations = clone(state.obligations), afterDirectPasses = clone(state.fanout_passes);
  const continuation = joinDischargedOwner(definition, state, exactOwner, relationship, event, activationClocks);
  if (continuation.limit || continuation.deadlineReason) { state.obligations = afterDirectObligations; state.fanout_passes = afterDirectPasses; }
  return continuation;
}

function structuralJoinTarget(definition: Row, state: Row, active: Row, relationship: Row, event: Row, evidenceDigest: string, activationClocks: Row[]): RouteTarget | null {
  return parallelJoinTarget(definition, state, active, relationship, event, evidenceDigest, activationClocks)
    ?? fanoutJoinTarget(definition, state, active, relationship, event, evidenceDigest, activationClocks);
}

type RouteTarget = { occurrences: Row[]; deadlines: Row[]; obligations: Row[]; limit: Row | null; deadlineReason: string | null; failedDeadlineIds: string[]; constructIds: string[]; relationshipDigests: string[] };

function relationshipTarget(definition: Row, state: Row, source: Row, relationship: Row, triggerDigest: string, activationClocks: Row[], predecessorIds: string[] = [source.occurrence_id], enclosingBase: Row[] | null = null): RouteTarget {
  const target = definition.steps.find((row: Row) => row.id === relationship.to);
  if (!target) fail('REFERENCE_INVALID');
  if (target.kind !== 'PARALLEL_SPLIT') {
    const direct = directTarget(definition, state, source, relationship, triggerDigest, activationClocks, predecessorIds, enclosingBase);
    return { occurrences: direct.occurrence ? [direct.occurrence] : [], deadlines: direct.deadlines, obligations: [], limit: direct.limit, deadlineReason: direct.deadlineReason, failedDeadlineIds: direct.failedDeadlineIds, constructIds: [], relationshipDigests: [digest('relationship', relationship)] };
  }
  const block = definition.parallel_blocks.find((row: Row) => row.split_step_id === target.id);
  if (!block) fail('STATE_INVALID');
  const requiredSources = sortStrings(block.branches.flatMap((branch: Row) => definition.deadlines.filter((row: Row) => row.step_id === branch.head_step_id).map((row: Row) => row.clock_source)));
  const suppliedSources = activationClocks.map((row: Row) => row.source);
  if (!same(suppliedSources, sortStrings(suppliedSources)) || suppliedSources.some((source: string) => !requiredSources.includes(source))) fail('DEPENDENCY_MISMATCH');
  const outer = clone(enclosingBase ?? source.enclosing);
  const pass = nextParallelPass(state, block.id, outer);
  const frontier = sortStrings(predecessorIds);
  const unresolved = state.obligations.filter((row: Row) => ['OPEN', 'BLOCKED', 'WAITING', 'DISPUTED'].includes(row.status)).length;
  const projectedByStep = new Map<string, bigint>();
  const occurrences: Row[] = [], deadlines: Row[] = [], obligations: Row[] = [];
  for (const branch of block.branches as Row[]) {
    const branchStep = definition.steps.find((row: Row) => row.id === branch.head_step_id);
    if (!branchStep || !['OPERATION', 'FANOUT_EXPAND'].includes(branchStep.kind)) fail('DEFINITION_INVALID');
    const priorProjected = projectedByStep.get(branchStep.id) ?? 0n;
    const counter = state.step_counters.find((row: Row) => row.step_id === branchStep.id);
    const limit = definition.occurrence_limits.find((row: Row) => row.step_id === branchStep.id);
    if (!counter || !limit) fail('STATE_INVALID');
    const projected = BigInt(counter.activations) + priorProjected + 1n;
    if (projected > BigInt(limit.maximum)) return { occurrences: [], deadlines: [], obligations: [], limit: { kind: 'LIMIT', limit_kind: 'STEP_OCCURRENCES', limit: limit.maximum, current: projected.toString(), step_id: branchStep.id, relationship_digest: digest('relationship', relationship) }, deadlineReason: 'LIMIT_EXCEEDED', failedDeadlineIds: [], constructIds: [block.id], relationshipDigests: [digest('relationship', relationship)] };
    projectedByStep.set(branchStep.id, priorProjected + 1n);
    let enclosing = [...outer, { kind: 'BRANCH', construct_id: block.id, pass, branch_id: branch.id, object_key: null }];
    const targetLoop = definition.loops.find((row: Row) => row.entry_step_id === branchStep.id && row.member_step_ids.includes(branchStep.id));
    if (targetLoop) enclosing.push({ kind: 'LOOP', construct_id: targetLoop.id, pass: '1', branch_id: null, object_key: null });
    const ordinal = (BigInt(counter.activations) + priorProjected + 1n).toString();
    const nextOccurrence = occurrence(state.work_class_digest, state.instance_id, branchStep.id, ordinal, frontier, enclosing, enclosing.filter((row: Row) => row.kind === 'FANOUT').at(-1)?.object_key ?? null, state.specification_pin);
    const branchClocks = activationClocks.filter((clock: Row) => definition.deadlines.some((row: Row) => row.step_id === branchStep.id && row.clock_source === clock.source));
    for (const declaration of definition.deadlines.filter((row: Row) => row.step_id === branchStep.id)) {
      const clock = branchClocks.find((row: Row) => row.source === declaration.clock_source);
      if (!clock) return { occurrences: [], deadlines: [], obligations: [], limit: null, deadlineReason: 'ACTIVATION_CLOCK_UNAVAILABLE', failedDeadlineIds: [declaration.id], constructIds: [block.id], relationshipDigests: [digest('relationship', relationship)] };
      const retained = state.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === clock.source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1).at(-1);
      if (!retained || !same(retained, clock)) fail('DEPENDENCY_MISMATCH');
      let deadline: Row;
      try { deadline = deadlineState(declaration, nextOccurrence, triggerDigest, (BigInt(state.revision) + 1n).toString(), clock, state); }
      catch (error) {
        if (error instanceof AdmissionError && error.code === 'TIME_RANGE') return { occurrences: [], deadlines: [], obligations: [], limit: null, deadlineReason: 'DEADLINE_TIME_OVERFLOW', failedDeadlineIds: [declaration.id], constructIds: [block.id], relationshipDigests: [digest('relationship', relationship)] };
        throw error;
      }
      if (declaration.boundary === 'AT_OR_AFTER' ? wholeSecond(clock.observed_time) >= wholeSecond(deadline.due) : wholeSecond(clock.observed_time) > wholeSecond(deadline.due)) return { occurrences: [], deadlines: [], obligations: [], limit: null, deadlineReason: 'DEADLINE_ALREADY_DUE', failedDeadlineIds: [declaration.id], constructIds: [block.id], relationshipDigests: [digest('relationship', relationship)] };
      deadlines.push(deadline);
    }
    const obligationCore = { kind: 'PARALLEL_BRANCH', construct_id: block.id, pass, source_occurrence_ids: frontier, branch_id: branch.id, object_key: null, join_step_id: block.join_step_id };
    obligations.push({ obligation_id: digest('obligation', obligationCore), ...obligationCore, creation_event_digest: triggerDigest, status: 'OPEN', expected_occurrence_id: nextOccurrence.occurrence_id, required_operation: branchStep.operation, waiting_on: null, completion_basis: null });
    occurrences.push(nextOccurrence);
  }
  const projectedActivations = BigInt(state.total_activations) + BigInt(occurrences.length);
  if (projectedActivations > BigInt(definition.limits.maximum_activations)) return { occurrences: [], deadlines: [], obligations: [], limit: { kind: 'LIMIT', limit_kind: 'ACTIVATIONS', limit: definition.limits.maximum_activations, current: projectedActivations.toString(), step_id: occurrences[0]?.step_id ?? source.step_id, relationship_digest: digest('relationship', relationship) }, deadlineReason: 'LIMIT_EXCEEDED', failedDeadlineIds: [], constructIds: [block.id], relationshipDigests: [digest('relationship', relationship)] };
  const projectedObligations = BigInt(unresolved + obligations.length);
  if (projectedObligations > BigInt(definition.limits.maximum_active_obligations)) return { occurrences: [], deadlines: [], obligations: [], limit: { kind: 'LIMIT', limit_kind: 'ACTIVE_OBLIGATIONS', limit: definition.limits.maximum_active_obligations, current: projectedObligations.toString(), step_id: occurrences[0]?.step_id ?? source.step_id, relationship_digest: digest('relationship', relationship) }, deadlineReason: 'LIMIT_EXCEEDED', failedDeadlineIds: [], constructIds: [block.id], relationshipDigests: [digest('relationship', relationship)] };
  return { occurrences, deadlines, obligations, limit: null, deadlineReason: null, failedDeadlineIds: [], constructIds: [block.id], relationshipDigests: [digest('relationship', relationship)] };
}

function fanoutTransition(request: Row, next: Row, event: Row, active: Row, step: Row, evidenceDigest: string, details: Row[], budgetResults: Row[]): Row {
  const fanout = request.definition.fanouts.find((row: Row) => row.expand_step_id === step.id);
  if (!fanout) fail('STATE_INVALID');
  const collection = event.native_evidence.collections[0];
  const pass = nextFanoutPass(next, fanout.id, active.occurrence.enclosing);
  const keys = clone(collection.values), eventHash = eventDigest(event), sourceIds = [active.occurrence.occurrence_id];
  const passRow: Row = { fanout_id: fanout.id, pass, expand_occurrence_id: active.occurrence.occurrence_id, object_keys: keys, obligation_ids: [], joined: false };
  next.fanout_passes.push(passRow);
  const routeRelationships: string[] = [], routeConstructIds = new Set<string>([fanout.id]), reasons: string[] = [];
  let limit: Row | null = null;
  const duplicates = new Set(keys.map((row: Row) => canonical(row))).size !== keys.length;
  if (duplicates) reasons.push('FANOUT_SET_DUPLICATE');
  else if (keys.length === 0 && fanout.empty_set_behavior === 'STOP') reasons.push('FANOUT_EMPTY');
  else if (keys.length === 0) {
    passRow.joined = true;
    const joinRelationship = request.definition.relationships.find((row: Row) => row.kind === 'SEQUENCE' && row.from === fanout.join_step_id);
    if (!joinRelationship) fail('STATE_INVALID');
    const joined = structuralJoinTarget(request.definition, next, active, joinRelationship, event, evidenceDigest, event.activation_clocks);
    const continuation = joined ?? relationshipTarget(request.definition, next, active.occurrence, joinRelationship, eventHash, event.activation_clocks, sourceIds, clone(active.occurrence.enclosing));
    routeRelationships.push(...continuation.relationshipDigests);
    for (const id of continuation.constructIds) routeConstructIds.add(id);
    limit = continuation.limit;
    if (continuation.deadlineReason) reasons.push(continuation.deadlineReason);
    if (!joined && continuation.obligations.length) {
      const owner = directOwningObligation(next, active);
      if (owner) {
        owner.status = 'WAITING'; owner.expected_occurrence_id = null; owner.required_operation = null; owner.completion_basis = null;
        owner.waiting_on = childPassFromRoute(continuation, active.occurrence.enclosing);
      }
    } else if (!joined && continuation.occurrences.length === 1) {
      const owner = directOwningObligation(next, active);
      if (owner) {
        const successor = continuation.occurrences[0], successorStep = proposalStep(request.definition, successor.step_id);
        owner.status = 'OPEN'; owner.expected_occurrence_id = successor.occurrence_id; owner.required_operation = successorStep.operation; owner.waiting_on = null; owner.completion_basis = null;
      }
    } else if (!joined && !continuation.occurrences.length && !continuation.obligations.length) {
      dischargeDirectOwner(request.definition, next, active, event, evidenceDigest);
    }
    for (const nextOccurrence of continuation.occurrences) {
      const occurrenceDeadlines = continuation.deadlines.filter((row: Row) => row.occurrence_id === nextOccurrence.occurrence_id);
      next.active.push({ occurrence: nextOccurrence, activation_event_digest: eventHash, status: 'ACTIVE', deadline_ids: occurrenceDeadlines.map((row: Row) => row.deadline_id).sort(byteCompare) });
      const counter = next.step_counters.find((row: Row) => row.step_id === nextOccurrence.step_id)!;
      counter.activations = (BigInt(counter.activations) + 1n).toString();
    }
    next.total_activations = (BigInt(next.total_activations) + BigInt(continuation.occurrences.length)).toString();
    next.obligations.push(...continuation.obligations); sortedRows(next.obligations, row => row.obligation_id);
    next.deadlines.push(...continuation.deadlines);
  } else {
    const head = proposalStep(request.definition, fanout.region_head_step_id), counter = next.step_counters.find((row: Row) => row.step_id === head.id), occurrenceLimit = request.definition.occurrence_limits.find((row: Row) => row.step_id === head.id);
    if (!counter || !occurrenceLimit) fail('STATE_INVALID');
    const projectedStep = BigInt(counter.activations) + BigInt(keys.length), projectedActivations = BigInt(next.total_activations) + BigInt(keys.length);
    const unresolved = next.obligations.filter((row: Row) => ['OPEN', 'BLOCKED', 'WAITING', 'DISPUTED'].includes(row.status)).length;
    const projectedObligations = BigInt(unresolved + keys.length);
    if (projectedStep > BigInt(occurrenceLimit.maximum)) limit = { kind: 'LIMIT', limit_kind: 'STEP_OCCURRENCES', limit: occurrenceLimit.maximum, current: projectedStep.toString(), step_id: head.id, relationship_digest: null };
    else if (projectedActivations > BigInt(request.definition.limits.maximum_activations)) limit = { kind: 'LIMIT', limit_kind: 'ACTIVATIONS', limit: request.definition.limits.maximum_activations, current: projectedActivations.toString(), step_id: head.id, relationship_digest: null };
    else if (projectedObligations > BigInt(request.definition.limits.maximum_active_obligations)) limit = { kind: 'LIMIT', limit_kind: 'ACTIVE_OBLIGATIONS', limit: request.definition.limits.maximum_active_obligations, current: projectedObligations.toString(), step_id: head.id, relationship_digest: null };
    else if (BigInt(keys.length) > BigInt(request.definition.limits.maximum_fanout_objects)) limit = { kind: 'LIMIT', limit_kind: 'FANOUT_OBJECTS', limit: request.definition.limits.maximum_fanout_objects, current: String(keys.length), step_id: head.id, relationship_digest: null };
    if (limit) reasons.push('LIMIT_EXCEEDED');
    else {
      const declarations = request.definition.deadlines.filter((row: Row) => row.step_id === head.id), requiredSources = sortStrings(declarations.map((row: Row) => row.clock_source)), suppliedSources = event.activation_clocks.map((row: Row) => row.source);
      const proposedActive: Row[] = [], proposedDeadlines: Row[] = [], proposedObligations: Row[] = [];
      if (!same(suppliedSources, sortStrings(suppliedSources)) || suppliedSources.some((source: string) => !requiredSources.includes(source))) fail('DEPENDENCY_MISMATCH');
      if (requiredSources.some((source: string) => !suppliedSources.includes(source))) reasons.push('ACTIVATION_CLOCK_UNAVAILABLE');
      if (!reasons.length) for (const [index, key] of keys.entries()) {
        const enclosing = [...clone(active.occurrence.enclosing), { kind: 'FANOUT', construct_id: fanout.id, pass, branch_id: null, object_key: clone(key) }];
        const headLoop = request.definition.loops.find((row: Row) => row.entry_step_id === head.id && row.member_step_ids.includes(head.id));
        if (headLoop) enclosing.push({ kind: 'LOOP', construct_id: headLoop.id, pass: '1', branch_id: null, object_key: null });
        const ordinal = (BigInt(counter.activations) + BigInt(index) + 1n).toString();
        const nextOccurrence = occurrence(next.work_class_digest, next.instance_id, head.id, ordinal, sourceIds, enclosing, clone(key), next.specification_pin);
        const deadlines: Row[] = [];
        for (const declaration of declarations) {
          const clock = event.activation_clocks.find((row: Row) => row.source === declaration.clock_source)!;
          const retained = next.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === clock.source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1).at(-1);
          if (!retained || !same(retained, clock)) fail('DEPENDENCY_MISMATCH');
          let deadline: Row;
          try { deadline = deadlineState(declaration, nextOccurrence, eventHash, (BigInt(next.revision) + 1n).toString(), clock, next); }
          catch (error) {
            if (error instanceof AdmissionError && error.code === 'TIME_RANGE') { reasons.push('DEADLINE_TIME_OVERFLOW'); break; }
            throw error;
          }
          if (declaration.boundary === 'AT_OR_AFTER' ? wholeSecond(clock.observed_time) >= wholeSecond(deadline.due) : wholeSecond(clock.observed_time) > wholeSecond(deadline.due)) { reasons.push('DEADLINE_ALREADY_DUE'); break; }
          deadlines.push(deadline);
        }
        if (reasons.length) break;
        const core = { kind: 'FANOUT_OBJECT', construct_id: fanout.id, pass, source_occurrence_ids: sourceIds, branch_id: null, object_key: clone(key), join_step_id: fanout.join_step_id };
        const obligation: Row = { obligation_id: digest('obligation', core), ...core, creation_event_digest: eventHash, status: 'OPEN', expected_occurrence_id: nextOccurrence.occurrence_id, required_operation: head.operation, waiting_on: null, completion_basis: null };
        proposedObligations.push(obligation);
        proposedActive.push({ occurrence: nextOccurrence, activation_event_digest: eventHash, status: 'ACTIVE', deadline_ids: deadlines.map((row: Row) => row.deadline_id).sort(byteCompare) });
        proposedDeadlines.push(...deadlines);
      }
      if (!reasons.length) {
        passRow.obligation_ids.push(...proposedObligations.map(row => row.obligation_id));
        next.obligations.push(...proposedObligations); next.active.push(...proposedActive); next.deadlines.push(...proposedDeadlines);
        counter.activations = projectedStep.toString(); next.total_activations = projectedActivations.toString();
      }
    }
  }
  sortedRows(next.active, row => row.occurrence); sortedRows(next.obligations, row => row.obligation_id); sortStateDeadlines(next);
  sortedRows(next.fanout_passes, row => [row.fanout_id, BigInt(row.pass).toString().padStart(20, '0'), row.expand_occurrence_id]);
  details.push({ kind: 'ROUTE', relationship_digests: sortStrings(routeRelationships), construct_ids: sortStrings([...routeConstructIds]) });
  if (limit) details.push(limit);
  if (reasons.length) {
    dischargeDirectOwner(request.definition, next, active, event, evidenceDigest);
    next.status = 'STOPPED';
    return admittedTransition(request, next, event, { disposition: 'STOPPED', reasons, details, decisionPermitDigest: event.permit.permit_id, budgetResults });
  }
  if (keys.length && passRow.obligation_ids.length) {
    const parent = directOwningObligation(next, active);
    if (parent) {
      parent.status = 'WAITING'; parent.expected_occurrence_id = null; parent.required_operation = null; parent.completion_basis = null;
      parent.waiting_on = { kind: 'FANOUT', construct_id: fanout.id, pass, outer_enclosing: clone(active.occurrence.enclosing), obligation_ids: sortStrings([...passRow.obligation_ids]) };
    }
  }
  if (!next.active.length && !next.obligations.some((row: Row) => ['OPEN', 'BLOCKED', 'WAITING', 'DISPUTED'].includes(row.status))) next.status = 'COMPLETE';
  return admittedTransition(request, next, event, { disposition: 'COMPLETED', reasons: [], details, decisionPermitDigest: event.permit.permit_id, budgetResults });
}

function validateNativeAssertion(evidence: Row): void {
  if (evidence.status === 'EFFECT_ESTABLISHED') {
    if (evidence.event_time === null || evidence.rules_out_past_and_future_effects) fail('INPUT_INVALID');
  } else if (evidence.status === 'OUTCOME_UNKNOWN') {
    if (evidence.event_time !== null || evidence.actual_fields.length || evidence.collections.length || evidence.rules_out_past_and_future_effects) fail('INPUT_INVALID');
  } else if (evidence.event_time !== null || evidence.actual_fields.length || evidence.collections.length || !evidence.rules_out_past_and_future_effects) fail('INPUT_INVALID');
}

function selectRelationship(definition: Row, step: Row, kind: 'SUCCESS' | 'FAILURE' | 'NO_EFFECT', label: Row | null): { relationship: Row | null; labelInvalid: boolean } {
  if (kind === 'SUCCESS' && step.kind === 'FANOUT_EXPAND') return { relationship: null, labelInvalid: false };
  if (kind === 'SUCCESS') {
    const choice = definition.choices.find((row: Row) => row.step_id === step.id);
    if (choice) {
      if (!label || !choice.label_values.some((value: Row) => same(value, label))) return { relationship: null, labelInvalid: true };
      const rows = definition.relationships.filter((row: Row) => row.kind === 'LABEL' && row.from === step.id && same(row.label, label));
      return rows.length === 1 ? { relationship: rows[0], labelInvalid: false } : { relationship: null, labelInvalid: true };
    }
    const rows = definition.relationships.filter((row: Row) => row.kind === 'SEQUENCE' && row.from === step.id);
    if (rows.length !== 1) fail('STATE_INVALID');
    return { relationship: rows[0], labelInvalid: false };
  }
  if (step.failure_behavior === 'STOP') return { relationship: null, labelInvalid: false };
  const rows = definition.relationships.filter((row: Row) => row.kind === 'FAILURE' && row.from === step.id);
  if (rows.length !== 1) fail('STATE_INVALID');
  return { relationship: rows[0], labelInvalid: false };
}

function retainOutcome(next: Row, event: Row, permit: Row, dispatchRow: Row, classification: string, reservationDigests: string[], conflicts: string[], disputed: boolean): Row {
  const record: Row = {
    kind: 'GOVERNED', outcome_digest: '', event_id: event.event_id, event_digest: eventDigest(event), permit_digest: permit.permit_id,
    dispatch_digest: dispatchRow.dispatch_digest, dispatch_attempt_digest: dispatchRow.dispatch_attempt_digest, native_evidence: clone(event.native_evidence), classification,
    reservation_receipt_digests: clone(reservationDigests), conflicts_with_evidence_ids: sortStrings(conflicts), disputed,
  };
  record.outcome_digest = outcomeDigest(record);
  next.outcomes.push(record); sortedRows(next.outcomes, row => row.outcome_digest);
  return record;
}

const CLASSIFICATION_REASONS: Record<string, string> = {
  UNKNOWN: 'UNKNOWN_OUTCOME',
  NO_EFFECT_ESTABLISHED: 'NO_EFFECT_ESTABLISHED',
  UNEXPECTED: 'UNEXPECTED_EFFECT',
  CONFLICTING: 'CONFLICTING_EFFECT',
  FOREIGN: 'FOREIGN_EFFECT',
  LATE_MATCHED: 'LATE_EFFECT',
  LATE_AFTER_RELEASE: 'LATE_EFFECT_AFTER_RELEASE',
  DUPLICATE: 'DUPLICATE_EVIDENCE',
};

function reservationEffectTransition(request: Row, event: Row, permit: Row, dispatchRow: Row, classification: string, observedRequest: boolean, dispatchIsDisqualified: boolean, safeAttempts: boolean, duplicateBasis: Row | null): Row {
  if (event.budget_inputs.length !== 1 || permit.budget_revisions.length !== 1) fail('BINDING_MISMATCH');
  const input = event.budget_inputs[0], retained = permit.budget_revisions[0], registryRequest = input.request;
  if (input.registry_digest !== retained.registry_digest || !same(input.affected_anchors, retained.affected_anchors)) fail('BINDING_MISMATCH');
  const registryDigest = digest('reservation-registry', registryRequest.state.core.configuration);
  if (registryDigest !== input.registry_digest || registryRequest.host_evidence.registry_digest !== registryDigest || registryRequest.specification_pin !== request.specification_pin) fail('BINDING_MISMATCH');
  if (input.expected_revision !== registryRequest.state.core.revision || input.expected_revision !== registryRequest.event.expected_revision) fail('REVISION_CONFLICT');
  if (registryRequest.state_digest !== digest('reservation-state', registryRequest.state)) fail('DEPENDENCY_MISMATCH');
  const latest = request.state.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === registryRequest.state.core.configuration.clock_source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1).at(-1);
  if (!latest || event.clock_revision !== latest.revision || wholeSecond(event.native_evidence.observed_at) > wholeSecond(latest.observed_time)) fail('CLOCK_INVALID');
  const kind = event.native_evidence.status === 'NO_EFFECT_ESTABLISHED' ? 'RELEASE' : 'SETTLE';
  const expectedId = digest('lifecycle-reservation-event', { instance_id: event.instance_id, lifecycle_event_id: event.event_id, lifecycle_event_kind: 'EFFECT_OBSERVED', reservation_event_kind: kind, registry_digest: registryDigest });
  const changedDispatch = !same(dispatchRow.native_request, permit.native_request) || dispatchIsDisqualified;
  const mismatch = changedDispatch || classification === 'UNEXPECTED' || classification === 'CONFLICTING' || (event.native_evidence.status === 'NO_EFFECT_ESTABLISHED' && !safeAttempts);
  // LIFE-010: "For a lifecycle DUPLICATE, the consumer copies the retained same-fact outcome's
  // complete embedded reservation-native record and changes only id and evidence_ref to the new
  // evidence values." Reconstructing it instead would drop the retained completion mismatch, and
  // "a duplicate of UNEXPECTED or CONFLICTING remains completion-mismatched".
  // The registry keeps one record per fact group, under the first evidence identity of that fact; a
  // DUPLICATE outcome row never gets a record of its own, so the copy source is found through the group.
  const factGroup = new Set<string>(request.state.outcomes.filter((row: Row) => nativeFactDigest(row.native_evidence) === nativeFactDigest(event.native_evidence)).map((row: Row) => row.native_evidence.evidence_id));
  const duplicateNative = duplicateBasis ? registryRequest.state.core.effects.find((row: Row) => factGroup.has(row.native.id)) : undefined;
  if (duplicateBasis && !duplicateNative) fail('BINDING_MISMATCH');
  const native: Row = duplicateNative ? { ...clone(duplicateNative.native), id: event.native_evidence.evidence_id, evidence_ref: event.native_evidence.evidence_ref } : {
    id: event.native_evidence.evidence_id,
    provider: event.native_evidence.provider,
    source: event.native_evidence.source,
    reservation: retained.reservation_id,
    outcome: event.native_evidence.status === 'EFFECT_ESTABLISHED' ? 'EFFECT' : event.native_evidence.status === 'OUTCOME_UNKNOWN' ? 'UNKNOWN' : 'NO_EFFECT',
    request: reservationNativeRequest(request.definition, { instance_id: event.instance_id, occurrence: permit.occurrence, native_request: permit.native_request }),
    effect_id: event.native_evidence.status === 'EFFECT_ESTABLISHED' ? event.native_evidence.native_operation_id : null,
    occurred_at: event.native_evidence.status === 'EFFECT_ESTABLISHED' ? event.native_evidence.event_time : null,
    rules_out_past_and_future_effects: event.native_evidence.rules_out_past_and_future_effects,
    evidence_ref: event.native_evidence.evidence_ref,
    observed_request: event.native_evidence.status === 'EFFECT_ESTABLISHED' && observedRequest ? clone(event.native_evidence.attributed_request) : null,
    actual_fields: clone(event.native_evidence.actual_fields),
    collections: clone(event.native_evidence.collections),
    completion_mismatch: mismatch,
    mismatch_reason: mismatch ? (changedDispatch ? 'NATIVE_REQUEST_MISMATCH' : 'UNEXPECTED_EFFECT') : null,
  };
  const expectedEvent: Row = {
    id: expectedId, expected_revision: input.expected_revision, kind,
    clock: { source: latest.source, status: 'AVAILABLE', instant: latest.observed_time },
    payload: kind === 'RELEASE' ? { native } : { native, histories: clone(registryRequest.event.payload.histories) },
    administration: kind === 'RELEASE' ? clone(registryRequest.event.administration) : null,
  };
  if (!same(registryRequest.event, expectedEvent)) fail('BINDING_MISMATCH');
  const result = aggregateStep(registryRequest, request.specification_pin);
  if (result.status === 'REFUSED') fail(result.code);
  return { registry_digest: registryDigest, affected_anchors: clone(input.affected_anchors), result };
}

// LIFE-010 foreign branch: each bound evidence field supplies its request field; the declared status and
// route-label fields are ignored; any other actual field, a missing bound field or a wrongly typed value makes
// the record unprojectable.
function foreignObservedFields(definition: Row, step: Row, evidence: Row): Row[] | null {
  const carrier = step.completion, actual = new Map<string, Row>(evidence.actual_fields.map((row: Row) => [row.name, row.value]));
  const declared = new Set<string>([carrier.status_field, ...(carrier.route_label_field === null ? [] : [carrier.route_label_field]), ...carrier.evidence_bindings.map((row: Row) => row.evidence_field)]);
  if (evidence.actual_fields.some((row: Row) => !declared.has(row.name))) return null;
  const types: Types = new Map(definition.types.map((row: Row) => [row.id, row]));
  const fields: Row[] = [];
  for (const binding of carrier.evidence_bindings) {
    const value = actual.get(binding.evidence_field), field = step.fields.find((row: Row) => row.name === binding.request_field);
    if (!value || !field || value.type_ref !== field.type_ref) return null;
    try { typed(value as any, types); } catch (error) { if (error instanceof AdmissionError) return null; throw error; }
    fields.push({ name: binding.request_field, value: clone(value) });
  }
  return fields.sort((a: Row, b: Row) => byteCompare(a.name, b.name));
}

function reservationForeignTransition(request: Row, event: Row, step: Row, temporal: boolean): Row {
  if (event.budget_inputs.length !== 1 || event.reservation_id === null) fail('BINDING_MISMATCH');
  const input = event.budget_inputs[0], registryRequest = input.request;
  if (input.registry_digest !== digest('reservation-registry', registryRequest.state.core.configuration) || registryRequest.host_evidence.registry_digest !== input.registry_digest || registryRequest.specification_pin !== request.specification_pin) fail('BINDING_MISMATCH');
  if (!same(input.affected_anchors, event.affected_budget_anchors) || input.expected_revision !== registryRequest.state.core.revision || input.expected_revision !== registryRequest.event.expected_revision) fail('REVISION_CONFLICT');
  if (registryRequest.state_digest !== digest('reservation-state', registryRequest.state)) fail('DEPENDENCY_MISMATCH');
  const latest = request.state.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === registryRequest.state.core.configuration.clock_source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1).at(-1);
  if (!latest || event.clock_revision !== latest.revision || wholeSecond(event.native_evidence.observed_at) > wholeSecond(latest.observed_time)) fail('CLOCK_INVALID');
  const reservation = registryRequest.state.core.reservations.find((row: Row) => row.id === event.reservation_id);
  if (reservation && !same(sortStrings(reservation.contributions.map((row: Row) => row.anchor)), event.affected_budget_anchors)) fail('BINDING_MISMATCH');
  const retainedRequest = reservation ? reservationNativeRequest(request.definition, { instance_id: reservation.authority.proposal.instance, occurrence: { occurrence_id: reservation.authority.proposal.occurrence, step_id: reservation.authority.proposal.step }, native_request: { operation: reservation.authority.proposal.operation, interface: reservation.authority.proposal.interface, fields: reservation.authority.proposal.fields } }) : clone(event.native_evidence.attributed_request);
  const observedFields = temporal ? foreignObservedFields(request.definition, step, event.native_evidence) : null;
  const observed = observedFields ? { ...clone(event.native_evidence.attributed_request), fields: observedFields } : null;
  const native: Row = {
    id: event.native_evidence.evidence_id, provider: event.native_evidence.provider, source: event.native_evidence.source, reservation: event.reservation_id,
    outcome: 'EFFECT', request: retainedRequest, effect_id: event.native_evidence.native_operation_id, occurred_at: event.native_evidence.event_time,
    rules_out_past_and_future_effects: false, evidence_ref: event.native_evidence.evidence_ref, observed_request: observed,
    actual_fields: clone(event.native_evidence.actual_fields), collections: clone(event.native_evidence.collections), completion_mismatch: true, mismatch_reason: 'UNEXPECTED_EFFECT',
  };
  const embeddedId = digest('lifecycle-reservation-event', { instance_id: event.instance_id, lifecycle_event_id: event.event_id, lifecycle_event_kind: 'EFFECT_OBSERVED', reservation_event_kind: 'SETTLE', registry_digest: input.registry_digest });
  const expectedEvent = { id: embeddedId, expected_revision: input.expected_revision, kind: 'SETTLE', clock: { source: latest.source, status: 'AVAILABLE', instant: latest.observed_time }, payload: { native, histories: clone(registryRequest.event.payload.histories) }, administration: null };
  if (!same(registryRequest.event, expectedEvent)) fail('BINDING_MISMATCH');
  const result = aggregateStep(registryRequest, request.specification_pin);
  if (result.status === 'REFUSED') fail(result.code);
  return { registry_digest: input.registry_digest, affected_anchors: clone(input.affected_anchors), result };
}

function foreignEffect(request: Row, event: Row): Row {
  const state = request.state, evidence = event.native_evidence;
  validateNativeAssertion(evidence);
  if (evidence.status !== 'EFFECT_ESTABLISHED' || event.completion_authorization !== null || event.permit !== null || event.dispatch_digest !== null) fail('INPUT_INVALID');
  const attributed = evidence.attributed_request;
  if (attributed.work_class !== request.definition.id || attributed.instance !== event.instance_id) fail('BINDING_MISMATCH');
  const step = request.definition.steps.find((row: Row) => row.id === attributed.step);
  if (!step || !['OPERATION', 'FANOUT_EXPAND'].includes(step.kind)) fail('REFERENCE_INVALID');
  if (attributed.interface !== step.interface || attributed.operation !== step.operation || !same(attributed.fields.map((row: Row) => ({ name: row.name, type_ref: row.value.type_ref })), step.fields) || evidence.native_request_digest !== digest('native-request', attributed)) fail('BINDING_MISMATCH');
  const temporal = evidence.event_time !== null && wholeSecond(evidence.event_time) <= wholeSecond(evidence.observed_at);
  const existingId = state.outcomes.find((row: Row) => row.native_evidence.evidence_id === evidence.evidence_id);
  if (existingId && !same(existingId.native_evidence, evidence)) fail('INPUT_INVALID');
  const sameFact = state.outcomes.find((row: Row) => nativeFactDigest(row.native_evidence) === nativeFactDigest(evidence));
  const conflicts = state.outcomes.filter((row: Row) => row.native_evidence.native_operation_id === evidence.native_operation_id && ['EFFECT_ESTABLISHED', 'NO_EFFECT_ESTABLISHED'].includes(row.native_evidence.status) && nativeFactDigest(row.native_evidence) !== nativeFactDigest(evidence));
  const classification = existingId || sameFact ? 'DUPLICATE' : conflicts.length ? 'CONFLICTING' : 'FOREIGN';
  let budgetResults: Row[] = [], reservationDigests: string[] = [], budgetDecision: string | null = null, budgetReasons: string[] = [];
  if (step.shared_budgets.length === 0) {
    if (event.reservation_id !== null || event.affected_budget_anchors.length || event.budget_inputs.length || event.clock_revision !== null) fail('BINDING_MISMATCH');
  } else {
    if (!same(event.affected_budget_anchors, step.shared_budgets)) fail('BINDING_MISMATCH');
    const result = reservationForeignTransition(request, event, step, temporal);
    budgetResults = [result]; reservationDigests = [result.result.receipt_digest]; budgetDecision = result.result.receipt.decision; budgetReasons = clone(result.result.receipt.reasons);
  }
  if (event.activation_clocks.length) fail('DEPENDENCY_MISMATCH');
  const next = clone(state), conflictIds = conflicts.map((row: Row) => row.native_evidence.evidence_id);
  if (classification === 'CONFLICTING') for (const prior of next.outcomes.filter((row: Row) => conflictIds.includes(row.native_evidence.evidence_id))) { prior.disputed = true; prior.conflicts_with_evidence_ids = sortStrings([...prior.conflicts_with_evidence_ids, evidence.evidence_id]); prior.outcome_digest = outcomeDigest(prior); }
  const basis = existingId ?? sameFact;
  // LIFE-010: when the duplicated fact already conflicts, "each member of that group adds the duplicate
  // evidence identity to its sorted conflict set", and "a foreign conflict list uses the same symmetric rule".
  if (classification === 'DUPLICATE' && !existingId && basis!.conflicts_with_evidence_ids.length) {
    for (const prior of next.outcomes.filter((row: Row) => basis!.conflicts_with_evidence_ids.includes(row.native_evidence.evidence_id))) { prior.disputed = true; prior.conflicts_with_evidence_ids = sortStrings([...prior.conflicts_with_evidence_ids, evidence.evidence_id]); prior.outcome_digest = outcomeDigest(prior); }
    sortedRows(next.outcomes, row => row.outcome_digest);
  }
  const record: Row = { kind: 'FOREIGN', outcome_digest: '', event_id: event.event_id, event_digest: eventDigest(event), permit_digest: null, dispatch_digest: null, dispatch_attempt_digest: null, native_evidence: clone(evidence), classification, affected_budget_anchors: clone(event.affected_budget_anchors), reservation_receipt_digests: reservationDigests, conflicts_with_evidence_ids: classification === 'DUPLICATE' ? clone(basis!.conflicts_with_evidence_ids) : sortStrings(conflictIds), disputed: true };
  record.outcome_digest = outcomeDigest(record);
  // LIFE-013: a repeated evidence identity "adds no duplicate outcome or exposure because the
  // original outcome already retains those bytes", and that rule "applies to governed and foreign
  // outcomes". Only a new evidence identity with the same fact appends a row.
  if (!existingId) { next.outcomes.push(record); sortedRows(next.outcomes, row => row.outcome_digest); }
  const effectDetail = { kind: 'EFFECT', classification, evidence_id: evidence.evidence_id }, details: Row[] = budgetResults.length ? [{ kind: 'BUDGET', registry_digest: budgetResults[0].registry_digest, receipt_digest: budgetResults[0].result.receipt_digest, reasons: budgetReasons }, effectDetail] : [effectDetail];
  if (classification === 'DUPLICATE') return admittedTransition(request, next, event, { disposition: 'OUTCOME_RETAINED', reasons: ['DUPLICATE_EVIDENCE'], details, budgetResults });
  // LIFE-006's budget-disputed row adds BUDGET_EFFECT_DISPUTED and the receipt reasons to "any
  // non-DUPLICATE effect classification", which reaches FOREIGN and CONFLICTING here. The general
  // rule reaches the same result independently: reason_codes is the union required by the
  // included details, and this decision carries a BUDGET detail.
  const classificationReason = classification === 'CONFLICTING' ? 'CONFLICTING_EFFECT' : 'FOREIGN_EFFECT';
  const reasons = budgetDecision === 'EFFECT_DISPUTED'
    ? sortStrings(['BUDGET_EFFECT_DISPUTED', ...budgetReasons, classificationReason])
    : [classificationReason];
  return admittedTransition(request, next, event, { disposition: 'DISPUTED', reasons, details, budgetResults });
}

function effect(request: Row, event: Row): Row {
  const state = request.state, definition = request.definition, evidence = event.native_evidence;
  validateNativeAssertion(evidence);
  if (event.instance_id !== state.instance_id) fail('BINDING_MISMATCH');
  if (event.permit === null) return foreignEffect(request, event);
  const permit = state.permits.find((row: Row) => row.permit_id === event.permit.permit_id);
  if (!permit) fail('PREREQUISITE_MISSING');
  if (!same(permit, event.permit) || permit.instance_id !== event.instance_id) fail('BINDING_MISMATCH');
  const dispatchRow = state.dispatches.find((row: Row) => row.dispatch_digest === event.dispatch_digest);
  if (!dispatchRow) fail(state.dispatches.some((row: Row) => row.permit_digest === permit.permit_id) ? 'BINDING_MISMATCH' : 'PREREQUISITE_MISSING');
  if (dispatchRow.permit_digest !== permit.permit_id) fail('BINDING_MISMATCH');
  const step = proposalStep(definition, permit.occurrence.step_id), carrier = step.completion;
  const expectedTriple = evidence.status === 'NO_EFFECT_ESTABLISHED' ? [carrier.no_effect_provider, carrier.no_effect_source, carrier.no_effect_record_type] : [carrier.effect_provider, carrier.effect_source, carrier.effect_record_type];
  if (!same([evidence.provider, evidence.source, evidence.record_type], expectedTriple)) fail('BINDING_MISMATCH');
  const expectedRequest = attributedRequest(definition, event.instance_id, permit, dispatchRow);
  if (!same(evidence.attributed_request, expectedRequest) || evidence.native_request_digest !== digest('native-request', expectedRequest)) fail('BINDING_MISMATCH');
  const at = wholeSecond(evidence.observed_at), attemptAt = wholeSecond(dispatchRow.attempt.attempted_at);
  if (['OUTCOME_UNKNOWN', 'NO_EFFECT_ESTABLISHED'].includes(evidence.status) && at < attemptAt) fail('INPUT_INVALID');
  const existingId = state.outcomes.find((row: Row) => row.native_evidence.evidence_id === evidence.evidence_id);
  if (existingId && !same(existingId.native_evidence, evidence)) fail('INPUT_INVALID');
  const sameFact = state.outcomes.find((row: Row) => nativeFactDigest(row.native_evidence) === nativeFactDigest(evidence));
  let classification: string, fields: ReturnType<typeof completionFields> | null = null;
  const eligible = dispatchEligible(state, permit, dispatchRow), disqualified = dispatchDisqualified(state, dispatchRow), unresolved = state.active.find((row: Row) => row.occurrence.occurrence_id === permit.occurrence.occurrence_id);
  const closed = state.completed.find((row: Row) => row.occurrence.occurrence_id === permit.occurrence.occurrence_id);
  const conclusive = evidence.status !== 'OUTCOME_UNKNOWN';
  const attemptOutcomes = state.outcomes.filter((row: Row) => row.kind === 'GOVERNED' && row.permit_digest === permit.permit_id && row.dispatch_attempt_digest === dispatchRow.dispatch_attempt_digest);
  const conclusiveAttemptOutcomes = attemptOutcomes.filter((row: Row) => row.native_evidence.status !== 'OUTCOME_UNKNOWN');
  const sameNativeConflicts = conclusive ? state.outcomes.filter((row: Row) => row.native_evidence.status !== 'OUTCOME_UNKNOWN' && row.native_evidence.native_operation_id === evidence.native_operation_id && nativeFactDigest(row.native_evidence) !== nativeFactDigest(evidence)) : [];
  const effectNoEffectConflicts = conclusive ? conclusiveAttemptOutcomes.filter((row: Row) => new Set([row.native_evidence.status, evidence.status]).size === 2 && [row.native_evidence.status, evidence.status].every(status => ['EFFECT_ESTABLISHED', 'NO_EFFECT_ESTABLISHED'].includes(status))) : [];
  const conflicts = [...new Map([...sameNativeConflicts, ...effectNoEffectConflicts].map((row: Row) => [row.native_evidence.evidence_id, row])).values()];
  const priorEstablishedAttempt = conclusiveAttemptOutcomes.filter((row: Row) => row.native_evidence.status === 'EFFECT_ESTABLISHED');
  if (existingId || sameFact) classification = 'DUPLICATE';
  else if (conclusive && conflicts.length) classification = evidence.status === 'EFFECT_ESTABLISHED' && conflicts.some((row: Row) => row.classification === 'NO_EFFECT_ESTABLISHED' && row.native_evidence.native_operation_id === evidence.native_operation_id) ? 'LATE_AFTER_RELEASE' : 'CONFLICTING';
  else if (evidence.status === 'OUTCOME_UNKNOWN') classification = 'UNKNOWN';
  else if (evidence.status === 'NO_EFFECT_ESTABLISHED') {
    // LIFE-010: authorization is required when the dispatch request matched the permit and no dispatch-disqualifying
    // reason applies; an earlier matching NOT_SENT attempt with no accepted acknowledgement does not prevent it.
    const needsAuthorization = Boolean(unresolved && unresolved.status !== 'BLOCKED_DISPUTE' && same(dispatchRow.native_request, permit.native_request) && !disqualified);
    if (needsAuthorization) noEffectAuthorization(state, event, permit, nativeEvidenceDigest(evidence));
    else if (event.completion_authorization !== null) fail('BINDING_MISMATCH');
    classification = finalSafeAttempt(state, permit, dispatchRow) && (needsAuthorization || Boolean(closed) || unresolved?.status === 'BLOCKED_DISPUTE') ? 'NO_EFFECT_ESTABLISHED' : 'UNEXPECTED';
  } else {
    if (event.completion_authorization !== null) fail('BINDING_MISMATCH');
    const temporal = evidence.event_time !== null && attemptAt <= wholeSecond(evidence.event_time) && wholeSecond(evidence.event_time) <= at;
    fields = completionFields(step, evidence, dispatchRow);
    if (step.kind === 'FANOUT_EXPAND' && fields.kind === 'SUCCESS') {
      const fanout = definition.fanouts.find((row: Row) => row.expand_step_id === step.id), collections = evidence.collections;
      if (!fanout || collections.length !== 1 || collections[0].name !== fanout.object_field || collections[0].element_type_ref !== fanout.object_type_ref || collections[0].values.some((row: Row) => row.type_ref !== fanout.object_type_ref)) fields = { kind: 'UNEXPECTED', label: null, labelInvalid: false, observedRequest: false };
      else {
        const types: Types = new Map(definition.types.map((row: Row) => [row.id, row]));
        for (const value of collections[0].values) typed(value, types);
      }
    }
    const additionalEffect = priorEstablishedAttempt.some((row: Row) => row.native_evidence.native_operation_id !== evidence.native_operation_id);
    if (additionalEffect || !eligible || !temporal || !same(dispatchRow.native_request, permit.native_request) || fields.kind === 'UNEXPECTED') classification = 'UNEXPECTED';
    else classification = fields.kind === 'SUCCESS' ? 'MATCHED' : 'FAILED';
    if (['MATCHED', 'FAILED'].includes(classification) && (closed || (state.status === 'STOPPED' && unresolved))) classification = 'LATE_MATCHED';
  }
  if (permit.budget_revisions.length === 0 && event.budget_inputs.length) fail('BINDING_MISMATCH');
  if (permit.budget_revisions.length === 0 && event.clock_revision !== null) fail('CLOCK_INVALID');
  let budgetResults: Row[] = [], reservationDigests: string[] = [], budgetDecision: string | null = null, budgetReasons: string[] = [];
  if (permit.budget_revisions.length) {
    if (event.clock_revision === null) fail('CLOCK_INVALID');
    // RES-WIRE-003: observed_request is the complete operation-field projection when that
    // projection is possible, stated independent of classification. `fields` is only computed
    // when classification reaches the MATCHED/FAILED/UNEXPECTED branch; a classification decided
    // earlier (DUPLICATE, CONFLICTING, LATE_AFTER_RELEASE, UNKNOWN) still needs the same
    // projectability answer for an EFFECT_ESTABLISHED record.
    const observedRequestProjectable = fields ? fields.observedRequest : evidence.status === 'EFFECT_ESTABLISHED' && completionFields(step, evidence, dispatchRow).observedRequest;
    const result = reservationEffectTransition(request, event, permit, dispatchRow, classification, Boolean(observedRequestProjectable), disqualified, finalSafeAttempt(state, permit, dispatchRow), classification === 'DUPLICATE' ? (existingId ?? sameFact ?? null) : null);
    budgetResults = [result]; reservationDigests = [result.result.receipt_digest]; budgetDecision = result.result.receipt.decision; budgetReasons = clone(result.result.receipt.reasons);
  }
  if (event.activation_clocks.length && !['MATCHED', 'FAILED', 'NO_EFFECT_ESTABLISHED'].includes(classification)) fail('DEPENDENCY_MISMATCH');

  const next = clone(state), evidenceId = evidence.evidence_id;
  let conflictIds = ['CONFLICTING', 'LATE_AFTER_RELEASE'].includes(classification) ? conflicts.map((row: Row) => row.native_evidence.evidence_id) : [], disputed = ['UNEXPECTED', 'CONFLICTING', 'LATE_AFTER_RELEASE'].includes(classification);
  if (classification === 'DUPLICATE') {
    const basis = existingId ?? sameFact!;
    conflictIds = clone(basis.conflicts_with_evidence_ids); disputed = basis.disputed;
    if (!existingId && conflictIds.length) {
      for (const prior of next.outcomes.filter((row: Row) => conflictIds.includes(row.native_evidence.evidence_id))) {
        prior.disputed = true;
        prior.conflicts_with_evidence_ids = sortStrings([...prior.conflicts_with_evidence_ids, evidenceId]);
        prior.outcome_digest = outcomeDigest(prior);
      }
      sortedRows(next.outcomes, row => row.outcome_digest);
    }
  }
  if (classification === 'CONFLICTING' || classification === 'LATE_AFTER_RELEASE') {
    for (const prior of next.outcomes.filter((row: Row) => conflictIds.includes(row.native_evidence.evidence_id))) {
      prior.disputed = true; prior.conflicts_with_evidence_ids = sortStrings([...prior.conflicts_with_evidence_ids, evidenceId]); prior.outcome_digest = outcomeDigest(prior);
    }
    sortedRows(next.outcomes, row => row.outcome_digest);
    for (const prior of state.outcomes.filter((row: Row) => conflictIds.includes(row.native_evidence.evidence_id) && row.kind === 'GOVERNED')) {
      const priorPermit = next.permits.find((row: Row) => row.permit_id === prior.permit_digest);
      if (priorPermit && next.completed.some((row: Row) => row.occurrence.occurrence_id === priorPermit.occurrence.occurrence_id)) blockDependents(next, priorPermit.occurrence.occurrence_id);
    }
  }
  if (!existingId) retainOutcome(next, event, permit, dispatchRow, classification, reservationDigests, conflictIds, disputed || budgetDecision === 'EFFECT_DISPUTED');
  const effectDetail = { kind: 'EFFECT', classification, evidence_id: evidenceId };
  const detailsPrefix: Row[] = budgetResults.length ? [{ kind: 'BUDGET', registry_digest: budgetResults[0].registry_digest, receipt_digest: budgetResults[0].result.receipt_digest, reasons: budgetReasons }, effectDetail] : [effectDetail];
  if (classification === 'DUPLICATE') return admittedTransition(request, next, event, { disposition: 'OUTCOME_RETAINED', reasons: ['DUPLICATE_EVIDENCE'], details: detailsPrefix, decisionPermitDigest: permit.permit_id, budgetResults });
  if (budgetDecision === 'EFFECT_DISPUTED') {
    // LIFE-010 gives FOREIGN/UNEXPECTED/CONFLICTING/LATE_AFTER_RELEASE their own disposition row
    // above the budget-disputed row, which reads "any other budget-backed classification". Those
    // classifications retain conservatively without blocking the occurrence itself.
    const retainedDispute = ['UNEXPECTED', 'CONFLICTING', 'LATE_AFTER_RELEASE'].includes(classification);
    const blocks = conclusive && !retainedDispute;
    const active = next.active.find((row: Row) => row.occurrence.occurrence_id === permit.occurrence.occurrence_id);
    if (active && active.status !== 'BLOCKED_DISPUTE') {
      active.status = blocks ? 'BLOCKED_DISPUTE' : 'OUTCOME_UNKNOWN';
      if (blocks) blockDirectOwner(next, active);
    }
    // Dependent blocking does not split on classification. LIFE-006 lists "dependent descendants
    // are blocked" as its own clause of the DISPUTED governed row, parallel to the clause that
    // decides this occurrence's status, and LIFE-010 covers the completed case for "any of these
    // disputes". `blocks` governs the occurrence's own status only.
    if (closed) blockDependents(next, permit.occurrence.occurrence_id);
    // LIFE-006's decision-reason mapping is exhaustive: the budget-disputed row adds
    // BUDGET_EFFECT_DISPUTED and the receipt reasons *to the classification-specific reasons*,
    // so every classification that has one contributes it here. MATCHED and FAILED have none.
    const classificationReason = CLASSIFICATION_REASONS[classification] ?? null;
    return admittedTransition(request, next, event, { disposition: 'DISPUTED', reasons: sortStrings(['BUDGET_EFFECT_DISPUTED', ...budgetReasons, ...(classificationReason ? [classificationReason] : [])]), details: detailsPrefix, decisionPermitDigest: permit.permit_id, budgetResults });
  }
  if (['UNEXPECTED', 'CONFLICTING', 'LATE_AFTER_RELEASE'].includes(classification)) {
    const active = next.active.find((row: Row) => row.occurrence.occurrence_id === permit.occurrence.occurrence_id);
    if (active && active.status !== 'BLOCKED_DISPUTE') active.status = 'OUTCOME_UNKNOWN';
    if (closed) blockDependents(next, permit.occurrence.occurrence_id);
    const reason = classification === 'UNEXPECTED' ? 'UNEXPECTED_EFFECT' : classification === 'CONFLICTING' ? 'CONFLICTING_EFFECT' : 'LATE_EFFECT_AFTER_RELEASE';
    return admittedTransition(request, next, event, { disposition: 'DISPUTED', reasons: [reason], details: detailsPrefix, decisionPermitDigest: permit.permit_id, budgetResults });
  }
  if (classification === 'UNKNOWN') {
    const active = next.active.find((row: Row) => row.occurrence.occurrence_id === permit.occurrence.occurrence_id); if (active && active.status !== 'BLOCKED_DISPUTE') active.status = 'OUTCOME_UNKNOWN';
    return admittedTransition(request, next, event, { disposition: 'OUTCOME_RETAINED', reasons: ['UNKNOWN_OUTCOME'], details: detailsPrefix, decisionPermitDigest: permit.permit_id, budgetResults });
  }
  if (unresolved?.status === 'BLOCKED_DISPUTE') return admittedTransition(request, next, event, { disposition: 'OUTCOME_RETAINED', reasons: sortStrings(['DEPENDENCY_DISPUTED', classification === 'NO_EFFECT_ESTABLISHED' ? 'NO_EFFECT_ESTABLISHED' : classification === 'LATE_MATCHED' ? 'LATE_EFFECT' : ''].filter(Boolean)), details: detailsPrefix, decisionPermitDigest: permit.permit_id, budgetResults });
  if (classification === 'LATE_MATCHED' || closed) {
    const activeIndex = next.active.findIndex((row: Row) => row.occurrence.occurrence_id === permit.occurrence.occurrence_id);
    if (activeIndex >= 0) {
      const active = next.active.splice(activeIndex, 1)[0];
      const disposition = fields?.kind === 'FAILURE' ? 'FAILED' : 'SUCCEEDED';
      next.completed.push({ occurrence: active.occurrence, disposition, evidence_digest: nativeEvidenceDigest(evidence), occurred_at: evidence.event_time, route_label: null, selected_relationship_digest: null, late: true });
      sortedRows(next.completed, row => row.occurrence);
      for (const deadline of next.deadlines.filter((row: Row) => row.occurrence_id === active.occurrence.occurrence_id && row.status === 'PENDING')) deadline.status = 'DISCHARGED';
      dischargeDirectOwner(definition, next, active, event, nativeEvidenceDigest(evidence));
    }
    return admittedTransition(request, next, event, { disposition: 'OUTCOME_RETAINED', reasons: [classification === 'NO_EFFECT_ESTABLISHED' ? 'NO_EFFECT_ESTABLISHED' : 'LATE_EFFECT'], details: detailsPrefix, decisionPermitDigest: permit.permit_id, budgetResults });
  }
  if (!unresolved) fail('STATE_INVALID');
  const routeKind = classification === 'MATCHED' ? 'SUCCESS' : classification === 'FAILED' ? 'FAILURE' : 'NO_EFFECT';
  const selected = selectRelationship(definition, step, routeKind, fields?.label ?? null);
  const activeIndex = next.active.findIndex((row: Row) => row.occurrence.occurrence_id === permit.occurrence.occurrence_id);
  const activeRow = next.active.splice(activeIndex, 1)[0];
  for (const deadline of next.deadlines.filter((row: Row) => row.occurrence_id === activeRow.occurrence.occurrence_id && row.status === 'PENDING')) deadline.status = 'DISCHARGED';
  const completedDisposition = classification === 'MATCHED' ? 'SUCCEEDED' : classification === 'FAILED' ? 'FAILED' : 'NO_EFFECT';
  const occurredAt = classification === 'NO_EFFECT_ESTABLISHED' ? evidence.observed_at : evidence.event_time;
  const relationshipDigest = selected.relationship ? digest('relationship', selected.relationship) : null;
  const completed: Row = { occurrence: activeRow.occurrence, disposition: completedDisposition, evidence_digest: nativeEvidenceDigest(evidence), occurred_at: occurredAt, route_label: fields?.label ?? null, selected_relationship_digest: relationshipDigest, late: false };
  next.completed.push(completed); sortedRows(next.completed, row => row.occurrence);
  const details: Row[] = detailsPrefix, reasons: string[] = [];
  if (step.kind === 'FANOUT_EXPAND' && classification === 'MATCHED') return fanoutTransition(request, next, event, activeRow, step, completed.evidence_digest, details, budgetResults);
  if (selected.labelInvalid || fields?.labelInvalid) {
    dischargeDirectOwner(definition, next, activeRow, event, completed.evidence_digest);
    next.status = 'STOPPED'; reasons.push('LABEL_INVALID'); details.push({ kind: 'LABEL', step_id: step.id, observed_value: fields?.label ?? null });
    return admittedTransition(request, next, event, { disposition: 'STOPPED', reasons, details, decisionPermitDigest: permit.permit_id, budgetResults });
  }
  if (!selected.relationship) {
    dischargeDirectOwner(definition, next, activeRow, event, completed.evidence_digest);
    next.status = 'STOPPED'; reasons.push(classification === 'NO_EFFECT_ESTABLISHED' ? 'NO_EFFECT_ESTABLISHED' : 'DECLARED_FAILURE');
    return admittedTransition(request, next, event, { disposition: 'STOPPED', reasons, details, decisionPermitDigest: permit.permit_id, budgetResults });
  }
  const joined = structuralJoinTarget(definition, next, activeRow, selected.relationship, event, completed.evidence_digest, event.activation_clocks);
  const target = joined ?? relationshipTarget(definition, next, activeRow.occurrence, selected.relationship, eventDigest(event), event.activation_clocks);
  if (!joined && target.obligations.length) {
    const owner = directOwningObligation(next, activeRow);
    if (owner) {
      owner.status = 'WAITING'; owner.expected_occurrence_id = null; owner.required_operation = null; owner.completion_basis = null;
      owner.waiting_on = { kind: 'PARALLEL', construct_id: target.obligations[0].construct_id, pass: target.obligations[0].pass, outer_enclosing: clone(activeRow.occurrence.enclosing), obligation_ids: sortStrings(target.obligations.map((row: Row) => row.obligation_id)) };
    }
  } else if (!joined && target.occurrences.length === 1) {
    const owner = directOwningObligation(next, activeRow);
    if (owner) {
      const successor = target.occurrences[0], successorStep = proposalStep(definition, successor.step_id);
      owner.expected_occurrence_id = successor.occurrence_id; owner.required_operation = successorStep.operation;
    }
  }
  const routeDetail = { kind: 'ROUTE', relationship_digests: sortStrings(target.relationshipDigests), construct_ids: sortStrings(target.constructIds) };
  const labelDetail = fields?.label !== null && fields?.label !== undefined ? { kind: 'LABEL', step_id: step.id, observed_value: fields.label } : null;
  if (target.limit || target.deadlineReason) {
    if (!joined) dischargeDirectOwner(definition, next, activeRow, event, completed.evidence_digest);
    next.status = 'STOPPED';
    if (target.limit) {
      details.push(routeDetail); if (labelDetail) details.push(labelDetail); details.push(target.limit); reasons.push(target.deadlineReason!);
    } else {
      details.push({ kind: 'DEADLINE', deadline_ids: sortStrings(target.failedDeadlineIds), reasons: [target.deadlineReason] });
      details.push(routeDetail); if (labelDetail) details.push(labelDetail); reasons.push(target.deadlineReason!);
    }
    return admittedTransition(request, next, event, { disposition: 'STOPPED', reasons, details, decisionPermitDigest: permit.permit_id, budgetResults });
  }
  details.push(routeDetail); if (labelDetail) details.push(labelDetail);
  if (target.occurrences.length) {
    for (const nextOccurrence of target.occurrences) {
      const occurrenceDeadlines = target.deadlines.filter((row: Row) => row.occurrence_id === nextOccurrence.occurrence_id);
      next.active.push({ occurrence: nextOccurrence, activation_event_digest: eventDigest(event), status: 'ACTIVE', deadline_ids: occurrenceDeadlines.map((row: Row) => row.deadline_id).sort(byteCompare) });
      const counter = next.step_counters.find((row: Row) => row.step_id === nextOccurrence.step_id)!;
      counter.activations = (BigInt(counter.activations) + 1n).toString();
    }
    next.total_activations = (BigInt(next.total_activations) + BigInt(target.occurrences.length)).toString();
    next.obligations.push(...target.obligations); sortedRows(next.obligations, row => row.obligation_id);
    sortedRows(next.active, row => row.occurrence); next.deadlines.push(...target.deadlines); sortStateDeadlines(next);
  } else if (!next.active.length && !next.obligations.some((row: Row) => ['OPEN', 'BLOCKED', 'WAITING', 'DISPUTED'].includes(row.status))) next.status = 'COMPLETE';
  const disposition = classification === 'MATCHED' ? 'COMPLETED' : 'FAILED';
  if (classification === 'NO_EFFECT_ESTABLISHED') reasons.push('NO_EFFECT_ESTABLISHED');
  return admittedTransition(request, next, event, { disposition, reasons, details, decisionPermitDigest: permit.permit_id, budgetResults });
}

function recordClock(request: Row, event: Row): Row {
  const state = request.state, clock = event.clock;
  const sameSource = state.clocks.filter((row: Row) => row.source === clock.source);
  if (sameSource.some((row: Row) => BigInt(row.revision) >= BigInt(clock.revision))) fail('CLOCK_INVALID');
  if (clock.status === 'AVAILABLE') {
    const available = sameSource.filter((row: Row) => row.status === 'AVAILABLE').sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1);
    if (available.length && wholeSecond(clock.observed_time) < wholeSecond(available.at(-1)!.observed_time)) fail('CLOCK_INVALID');
  }
  const next = clone(state);
  next.clocks.push(clone(clock));
  next.clocks.sort((a: Row, b: Row) => a.source === b.source ? (BigInt(a.revision) < BigInt(b.revision) ? -1 : 1) : byteCompare(a.source, b.source));
  const detail = { kind: 'CLOCK', source: clock.source, revision: clock.revision, status: clock.status };
  if (clock.status !== 'AVAILABLE') {
    if (event.activation_clocks.length) fail('DEPENDENCY_MISMATCH');
    return admittedTransition(request, next, event, { disposition: 'CLOCK_RECORDED', reasons: ['CLOCK_UNAVAILABLE'], details: [detail] });
  }
  const due = next.deadlines.filter((row: Row) => row.status === 'PENDING' && row.source === clock.source && (row.boundary === 'AT_OR_AFTER' ? wholeSecond(clock.observed_time) >= wholeSecond(row.due) : wholeSecond(clock.observed_time) > wholeSecond(row.due)));
  if (due.length === 0) {
    if (event.activation_clocks.length) fail('DEPENDENCY_MISMATCH');
    return admittedTransition(request, next, event, { disposition: 'CLOCK_RECORDED', details: [detail] });
  }
  due.sort((a: Row, b: Row) => byteCompare(canonical([a.due, state.active.find((row: Row) => row.occurrence.occurrence_id === a.occurrence_id)?.occurrence ?? a.occurrence_id, a.deadline_id]), canonical([b.due, state.active.find((row: Row) => row.occurrence.occurrence_id === b.occurrence_id)?.occurrence ?? b.occurrence_id, b.deadline_id])));
  const base = clone(next), plan = clone(next), routeDigests: string[] = [], constructIds = new Set<string>(), requiredSources = new Set<string>(), reasons: string[] = [];
  const deadlineIds = new Set<string>(due.map((row: Row) => row.deadline_id));
  let selectedLimit: Row | null = null;
  for (const deadline of due) {
    const baseDeadline = base.deadlines.find((row: Row) => row.deadline_id === deadline.deadline_id && row.occurrence_id === deadline.occurrence_id)!;
    const planDeadline = plan.deadlines.find((row: Row) => row.deadline_id === deadline.deadline_id && row.occurrence_id === deadline.occurrence_id)!;
    baseDeadline.status = 'EXPIRED'; baseDeadline.expiry_event_digest = eventDigest(event);
    planDeadline.status = 'EXPIRED'; planDeadline.expiry_event_digest = eventDigest(event);
    const originalActive = state.active.find((row: Row) => row.occurrence.occurrence_id === deadline.occurrence_id);
    if (!originalActive || originalActive.status === 'BLOCKED_DISPUTE') continue;
    for (const targetState of [base, plan]) {
      const index = targetState.active.findIndex((row: Row) => row.occurrence.occurrence_id === deadline.occurrence_id);
      if (index >= 0) {
        const active = targetState.active.splice(index, 1)[0];
        const declaration = definitionDeadline(request.definition, deadline.deadline_id);
        const relation = state.status === 'STOPPED' || state.status === 'COMPLETE' || declaration.expiry_target === null ? null : request.definition.relationships.find((row: Row) => row.kind === 'EXPIRY' && row.from === active.occurrence.step_id && row.deadline_ref === declaration.id);
        targetState.completed.push({ occurrence: active.occurrence, disposition: 'EXPIRED', evidence_digest: clock.evidence_digest, occurred_at: clock.observed_time, route_label: null, selected_relationship_digest: relation ? digest('relationship', relation) : null, late: state.status === 'STOPPED' });
        sortedRows(targetState.completed, row => row.occurrence);
        if (state.status === 'STOPPED') dischargeDirectOwner(request.definition, targetState, active, event, clock.evidence_digest);
      }
    }
    if (state.status === 'STOPPED' || state.status === 'COMPLETE') continue;
    const declaration = definitionDeadline(request.definition, deadline.deadline_id);
    dischargeDirectOwner(request.definition, base, originalActive, event, clock.evidence_digest);
    if (declaration.expiry_target === null) { reasons.push('EXPIRY_STOP'); continue; }
    const relationship = request.definition.relationships.find((row: Row) => row.kind === 'EXPIRY' && row.from === originalActive.occurrence.step_id && row.deadline_ref === declaration.id);
    if (!relationship) fail('STATE_INVALID');
    const targetStep = request.definition.steps.find((row: Row) => row.id === relationship.to)!;
    request.definition.deadlines.filter((row: Row) => row.step_id === targetStep.id).forEach((row: Row) => requiredSources.add(row.clock_source));
    const clocks = event.activation_clocks.filter((row: Row) => request.definition.deadlines.some((deadlineRow: Row) => deadlineRow.step_id === targetStep.id && deadlineRow.clock_source === row.source));
    const joined = structuralJoinTarget(request.definition, plan, originalActive, relationship, event, clock.evidence_digest, clocks);
    const target = joined ?? relationshipTarget(request.definition, plan, originalActive.occurrence, relationship, eventDigest(event), clocks);
    routeDigests.push(...target.relationshipDigests); for (const id of target.constructIds) constructIds.add(id);
    if (target.limit || target.deadlineReason) {
      selectedLimit ??= target.limit;
      for (const id of target.failedDeadlineIds) deadlineIds.add(id);
      reasons.push(target.deadlineReason!);
      continue;
    }
    if (!joined && target.obligations.length) {
      const owner = directOwningObligation(plan, originalActive);
      if (owner) {
        owner.status = 'WAITING'; owner.expected_occurrence_id = null; owner.required_operation = null; owner.completion_basis = null;
        owner.waiting_on = { kind: 'PARALLEL', construct_id: target.obligations[0].construct_id, pass: target.obligations[0].pass, outer_enclosing: clone(originalActive.occurrence.enclosing), obligation_ids: sortStrings(target.obligations.map((row: Row) => row.obligation_id)) };
      }
    } else if (!joined && target.occurrences.length === 1) {
      const owner = directOwningObligation(plan, originalActive);
      if (owner) { owner.expected_occurrence_id = target.occurrences[0].occurrence_id; owner.required_operation = proposalStep(request.definition, target.occurrences[0].step_id).operation; }
    }
    for (const nextOccurrence of target.occurrences) {
      const occurrenceDeadlines = target.deadlines.filter((row: Row) => row.occurrence_id === nextOccurrence.occurrence_id);
      plan.active.push({ occurrence: nextOccurrence, activation_event_digest: eventDigest(event), status: 'ACTIVE', deadline_ids: occurrenceDeadlines.map((row: Row) => row.deadline_id).sort(byteCompare) });
      const counter = plan.step_counters.find((row: Row) => row.step_id === nextOccurrence.step_id)!; counter.activations = (BigInt(counter.activations) + 1n).toString();
    }
    plan.total_activations = (BigInt(plan.total_activations) + BigInt(target.occurrences.length)).toString();
    plan.obligations.push(...target.obligations); sortedRows(plan.obligations, row => row.obligation_id);
    sortedRows(plan.active, row => row.occurrence); plan.deadlines.push(...target.deadlines); sortStateDeadlines(plan);
  }
  const suppliedSources = event.activation_clocks.map((row: Row) => row.source);
  const retainedSources = sortStrings([...requiredSources].filter((source: string) => next.clocks.some((row: Row) => row.status === 'AVAILABLE' && row.source === source)));
  if (!same(retainedSources, suppliedSources)) fail('DEPENDENCY_MISMATCH');
  for (const supplied of event.activation_clocks) {
    const retained = next.clocks.filter((row: Row) => row.status === 'AVAILABLE' && row.source === supplied.source).sort((a: Row, b: Row) => BigInt(a.revision) < BigInt(b.revision) ? -1 : 1).at(-1);
    if (!retained || !same(retained, supplied)) fail('DEPENDENCY_MISMATCH');
  }
  const stop = reasons.length > 0;
  const resultState = stop ? base : plan;
  if (stop) resultState.status = 'STOPPED';
  else if (state.status === 'STOPPED') resultState.status = 'STOPPED';
  else if (!resultState.active.length && !resultState.obligations.some((row: Row) => ['OPEN', 'BLOCKED', 'WAITING', 'DISPUTED'].includes(row.status))) resultState.status = 'COMPLETE';
  const deadlineDetail = { kind: 'DEADLINE', deadline_ids: sortStrings([...deadlineIds]), reasons: sortStrings(reasons.filter((reason: string) => ['ACTIVATION_CLOCK_UNAVAILABLE', 'DEADLINE_ALREADY_DUE', 'DEADLINE_TIME_OVERFLOW', 'EXPIRY_STOP'].includes(reason))) };
  const details: Row[] = [detail, deadlineDetail];
  if (!stop && routeDigests.length && state.status === 'ACTIVE') details.push({ kind: 'ROUTE', relationship_digests: sortStrings(routeDigests), construct_ids: sortStrings([...constructIds]) });
  if (selectedLimit) details.push(selectedLimit);
  const finalReasons = selectedLimit ? sortStrings([...reasons, 'LIMIT_EXCEEDED']) : sortStrings(reasons);
  return admittedTransition(request, resultState, event, { disposition: stop ? 'STOPPED' : 'EXPIRED', reasons: finalReasons, details });
}

function definitionDeadline(definition: Row, id: string): Row {
  const row = definition.deadlines.find((candidate: Row) => candidate.id === id);
  if (!row) fail('STATE_INVALID');
  return row!;
}

export function step(input: unknown, selectedPin: string): Row {
  if (input !== null && typeof input === 'object' && !Array.isArray(input)) {
    const candidate = input as Row;
    if (typeof candidate.profile === 'string' && typeof candidate.role === 'string' && Object.hasOwn(PROFILE_ROLES, candidate.profile) && Object.values(PROFILE_ROLES).includes(candidate.role) && PROFILE_ROLES[candidate.profile] !== candidate.role) return { status: 'REFUSED', code: 'ROLE_UNSUPPORTED', path: '' };
  }
  if (!shape('lifecycle.schema.json', 'stepInput', input)) {
    return { status: 'REFUSED', code: 'SCHEMA_INVALID', path: '' };
  }
  const request = input as Row;
  try {
    if (PROFILE_ROLES[request.profile] !== request.role) fail('ROLE_UNSUPPORTED');
    if (request.specification_pin !== selectedPin) fail('VERSION_UNSUPPORTED');
    const admitted = validateWorkClass(request.definition, selectedPin);
    if (admitted.digest !== request.definition_digest) fail('DIGEST_MISMATCH');
    if (request.definition.profile !== request.profile || request.state.profile !== request.profile || request.state.role !== request.role || request.state.work_class_digest !== request.definition_digest) fail('BINDING_MISMATCH');
    stateInvalid(request.state, request.definition, selectedPin);
    if (stateDigest(request.state) !== request.state_digest) fail('STATE_INVALID');
    const event = request.event;
    const prior = request.state.replays.find((row: Row) => row.event_id === event.event_id);
    if (prior) {
      if (prior.event_digest !== eventDigest(event)) fail('REPLAY_CONFLICT');
      return { status: 'STEP', profile: request.profile, role: request.role, decision: prior.decision, decision_digest: prior.decision_receipt_digest, permit: prior.permit, budget_results: prior.budget_results, state: request.state, state_digest: request.state_digest, transition_state_digest: prior.transition_state_digest, transaction_digest: prior.transaction_digest, replay: true };
    }
    if (event.expected_state_revision !== request.state.revision) fail('REVISION_CONFLICT');
    if (event.expected_state_digest !== request.state_digest || event.instance_id !== request.state.instance_id) fail('BINDING_MISMATCH');
    if (request.state.status !== 'ACTIVE' && event.kind === 'PROPOSE') fail('INSTANCE_NOT_ACTIVE');
    if (event.kind === 'PROPOSE') return propose(request, event);
    if (event.kind === 'DISPATCH_OBSERVED') return dispatch(request, event);
    if (event.kind === 'EFFECT_OBSERVED') return effect(request, event);
    if (event.kind === 'CLOCK') return recordClock(request, event);
    return fail('UNSUPPORTED_FEATURE');
  } catch (error) {
    if (!(error instanceof AdmissionError)) throw error;
    return { status: 'REFUSED', profile: request.profile, role: request.role, code: error.code, path: '', state: request.state, state_digest: request.state_digest, budget_states: budgetEcho(request.event) };
  }
}
