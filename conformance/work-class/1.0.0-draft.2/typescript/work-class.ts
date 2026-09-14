import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { instant } from './time.ts';
import { requireShape, VERSION } from './schema.ts';
import { ordered, same, setOrder, typed } from './values.ts';
import type { RecordValue as Row, ScalarType, Types } from './values.ts';

const PROFILES = ['LINEAR', 'CHOICE_LOOPS', 'DEADLINES', 'PARALLEL_FANOUT'] as const;
export const PROFILE_ROLES: Record<string, string> = {
  LINEAR: 'LINEAR_WORK_RUNTIME',
  CHOICE_LOOPS: 'CHOICE_LOOP_RUNTIME',
  DEADLINES: 'DEADLINE_RUNTIME',
  PARALLEL_FANOUT: 'PARALLEL_FANOUT_RUNTIME',
};
const STRUCTURAL = new Set(['PARALLEL_SPLIT', 'PARALLEL_JOIN', 'FANOUT_JOIN', 'TERMINAL']);
const PROPOSABLE = new Set(['OPERATION', 'FANOUT_EXPAND']);
type GraphEdge = Row & { implicit?: boolean };
type NormalizedGraph = { outgoing: Map<string, GraphEdge[]>; incoming: Map<string, GraphEdge[]> };

function fail(code: string, path = ''): never { throw new AdmissionError(code, path); }
function index(rows: Row[], key = 'id'): Map<string, Row> { return new Map(rows.map(row => [row[key], row])); }
function unique(rows: Row[], key: (row: Row) => string): boolean { return new Set(rows.map(key)).size === rows.length; }
function canonicalUnique(rows: unknown[]): boolean { return new Set(rows.map(canonical)).size === rows.length; }
function mustOrder(values: string[], path: string): void { if (!ordered(values)) fail('DEFINITION_INVALID', path); }
function mustSetOrder(values: unknown[], path: string): void { if (!setOrder(values)) fail('DEFINITION_INVALID', path); }
function edgeDigest(edge: Row): string { return digest('relationship', edge); }

function normalizedGraph(definition: Row): NormalizedGraph {
  const outgoing = new Map<string, GraphEdge[]>((definition.steps as Row[]).map(step => [step.id, []]));
  const incoming = new Map<string, GraphEdge[]>((definition.steps as Row[]).map(step => [step.id, []]));
  const add = (edge: GraphEdge): void => {
    outgoing.get(edge.from)?.push(edge);
    incoming.get(edge.to)?.push(edge);
  };
  for (const edge of definition.relationships as Row[]) add(edge);
  for (const block of definition.parallel_blocks as Row[]) for (const branch of block.branches) {
    add({ kind: 'STRUCTURAL', from: block.split_step_id, to: branch.head_step_id, implicit: true });
  }
  for (const fanout of definition.fanouts as Row[]) {
    add({ kind: 'STRUCTURAL', from: fanout.expand_step_id, to: fanout.region_head_step_id, implicit: true });
  }
  return { outgoing, incoming };
}

function stronglyConnected(graph: Map<string, GraphEdge[]>): string[][] {
  const nodeIndexes = new Map<string, number>(), lowLinks = new Map<string, number>(), stack: string[] = [];
  const onStack = new Set<string>(), components: string[][] = [];
  let nextIndex = 0;
  function visit(node: string): void {
    nodeIndexes.set(node, nextIndex); lowLinks.set(node, nextIndex); nextIndex++;
    stack.push(node); onStack.add(node);
    for (const edge of graph.get(node) ?? []) {
      if (!nodeIndexes.has(edge.to)) {
        visit(edge.to);
        lowLinks.set(node, Math.min(lowLinks.get(node)!, lowLinks.get(edge.to)!));
      } else if (onStack.has(edge.to)) {
        lowLinks.set(node, Math.min(lowLinks.get(node)!, nodeIndexes.get(edge.to)!));
      }
    }
    if (lowLinks.get(node) !== nodeIndexes.get(node)) return;
    const component: string[] = [];
    let member: string;
    do { member = stack.pop()!; onStack.delete(member); component.push(member); } while (member !== node);
    components.push(component);
  }
  for (const node of graph.keys()) if (!nodeIndexes.has(node)) visit(node);
  return components;
}

function cyclic(component: string[], graph: Map<string, GraphEdge[]>): boolean {
  return component.length > 1 || (graph.get(component[0]) ?? []).some(edge => edge.to === component[0]);
}

function hasCycle(graph: Map<string, GraphEdge[]>, members: Set<string>, skip?: GraphEdge): boolean {
  const state = new Map<string, number>();
  function visit(node: string): boolean {
    state.set(node, 1);
    for (const edge of graph.get(node) ?? []) {
      if (edge === skip || !members.has(edge.to)) continue;
      if (state.get(edge.to) === 1 || (!state.has(edge.to) && visit(edge.to))) return true;
    }
    state.set(node, 2); return false;
  }
  return [...members].some(node => !state.has(node) && visit(node));
}

function typeTable(definition: Row): Types {
  const types: Types = new Map(definition.types.map((row: ScalarType) => [row.id, row]));
  for (const row of types.values()) {
    if ((row.unit !== null && row.kind !== 'DECIMAL') || (row.nonnegative && !['INTEGER', 'DECIMAL'].includes(row.kind))) fail('DEFINITION_INVALID', '/types');
  }
  return types;
}

function inventories(definition: Row): void {
  for (const [name, key] of [
    ['participants', 'id'], ['objects', 'id'], ['types', 'id'], ['steps', 'id'], ['choices', 'step_id'],
    ['occurrence_limits', 'step_id'], ['loops', 'id'], ['deadlines', 'id'], ['parallel_blocks', 'id'], ['fanouts', 'id'],
  ]) {
    const rows = definition[name] as Row[];
    mustOrder(rows.map(row => row[key]), '/' + name);
  }
  mustOrder(definition.shared_budgets, '/shared_budgets');
  mustOrder(definition.source.obligations, '/source/obligations');
  if (!canonicalUnique(definition.relationships)) fail('DEFINITION_INVALID', '/relationships');
  for (const [i, step] of definition.steps.entries()) {
    mustOrder(step.fields.map((row: Row) => row.name), `/steps/${i}/fields`);
    for (const field of ['required_credentials', 'authority_requirements', 'shared_budgets']) mustOrder(step[field], `/steps/${i}/${field}`);
    mustOrder(step.prior_effect_bindings.map((row: Row) => row.id), `/steps/${i}/prior_effect_bindings`);
    mustOrder(step.prior_actor_separations.map((row: Row) => row.id), `/steps/${i}/prior_actor_separations`);
    if (step.scope_fields) {
      mustOrder(step.scope_fields.subjects, `/steps/${i}/scope_fields/subjects`);
      mustOrder(step.scope_fields.resources, `/steps/${i}/scope_fields/resources`);
    }
    if (step.completion) {
      mustSetOrder(step.completion.success_values, `/steps/${i}/completion/success_values`);
      mustSetOrder(step.completion.failure_values, `/steps/${i}/completion/failure_values`);
      mustOrder(step.completion.evidence_bindings.map((row: Row) => row.evidence_field), `/steps/${i}/completion/evidence_bindings`);
    }
  }
  for (const [i, loop] of definition.loops.entries()) mustOrder(loop.member_step_ids, `/loops/${i}/member_step_ids`);
  for (const [i, block] of definition.parallel_blocks.entries()) {
    if (!unique(block.branches, row => row.id) || !unique(block.branches, row => row.head_step_id)) fail('DEFINITION_INVALID', `/parallel_blocks/${i}/branches`);
  }
}

function stepSemantics(definition: Row, types: Types): void {
  const steps = index(definition.steps);
  if (!steps.has(definition.root)) fail('REFERENCE_INVALID', '/root');
  if (!PROPOSABLE.has(steps.get(definition.root)!.kind)) fail('DEFINITION_INVALID', '/root');
  const participants = definition.participants as Row[];
  const declaredRoles = new Set(participants.map(row => row.role));
  for (const object of definition.objects as Row[]) if (!types.has(object.type_ref)) fail('REFERENCE_INVALID', '/objects');
  for (const [i, step] of (definition.steps as Row[]).entries()) {
    const structural = STRUCTURAL.has(step.kind);
    if (structural) {
      if (step.executor_role !== null || step.interface !== null || step.operation !== null || step.fields.length || step.scope_fields !== null || step.required_credentials.length || step.authority_requirements.length || step.shared_budgets.length || step.prior_effect_bindings.length || step.prior_actor_separations.length || step.permit_seconds !== null || step.failure_behavior !== null || step.completion !== null) fail('DEFINITION_INVALID', `/steps/${i}`);
      continue;
    }
    if (!PROPOSABLE.has(step.kind) || step.executor_role === null || step.interface === null || step.operation === null || step.scope_fields === null || step.permit_seconds === null || step.failure_behavior === null || step.completion === null || step.authority_requirements.length !== 1) fail('DEFINITION_INVALID', `/steps/${i}`);
    if (!declaredRoles.has(step.executor_role)) fail('REFERENCE_INVALID', `/steps/${i}/executor_role`);
    const fields = index(step.fields, 'name');
    for (const field of step.fields as Row[]) if (!types.has(field.type_ref)) fail('REFERENCE_INVALID', `/steps/${i}/fields`);
    for (const name of [...step.scope_fields.subjects, ...step.scope_fields.resources]) if (!fields.has(name)) fail('REFERENCE_INVALID', `/steps/${i}/scope_fields`);
    const carrier = step.completion;
    if (!types.has(carrier.status_type_ref)) fail('REFERENCE_INVALID', `/steps/${i}/completion/status_type_ref`);
    for (const value of [...carrier.success_values, ...carrier.failure_values]) {
      typed(value, types);
      if (value.type_ref !== carrier.status_type_ref) fail('DEFINITION_INVALID', `/steps/${i}/completion`);
    }
    if (!canonicalUnique([...carrier.success_values, ...carrier.failure_values])) fail('DEFINITION_INVALID', `/steps/${i}/completion`);
    const requestNames = carrier.evidence_bindings.map((row: Row) => row.request_field);
    const evidenceNames = carrier.evidence_bindings.map((row: Row) => row.evidence_field);
    if (!unique(carrier.evidence_bindings, row => row.request_field) || !unique(carrier.evidence_bindings, row => row.evidence_field) || requestNames.length !== step.fields.length || requestNames.some((name: string) => !fields.has(name))) fail('DEFINITION_INVALID', `/steps/${i}/completion/evidence_bindings`);
    const distinctCarrierFields = [carrier.status_field, ...(carrier.route_label_field === null ? [] : [carrier.route_label_field]), ...evidenceNames];
    if (new Set(distinctCarrierFields).size !== distinctCarrierFields.length) fail('DEFINITION_INVALID', `/steps/${i}/completion`);
    if ((carrier.route_label_field === null) !== (carrier.route_label_type_ref === null)) fail('DEFINITION_INVALID', `/steps/${i}/completion`);
  }
}

function graphSemantics(definition: Row, types: Types): void {
  const steps = index(definition.steps), choices = index(definition.choices, 'step_id'), deadlines = index(definition.deadlines, 'id');
  const relations = definition.relationships as Row[];
  for (const edge of relations) {
    if (!steps.has(edge.from) || !steps.has(edge.to)) fail('REFERENCE_INVALID', '/relationships');
    if (edge.kind === 'EXPIRY' && !deadlines.has(edge.deadline_ref)) fail('REFERENCE_INVALID', '/relationships');
    if (edge.kind === 'LABEL') typed(edge.label, types);
  }
  for (const [i, choice] of (definition.choices as Row[]).entries()) {
    const step = steps.get(choice.step_id);
    if (!step || !PROPOSABLE.has(step.kind) || !types.has(choice.label_type_ref)) fail('REFERENCE_INVALID', `/choices/${i}`);
    mustSetOrder(choice.label_values, `/choices/${i}/label_values`);
    for (const value of choice.label_values) { typed(value, types); if (value.type_ref !== choice.label_type_ref) fail('DEFINITION_INVALID', `/choices/${i}/label_values`); }
    const labels = relations.filter(edge => edge.from === choice.step_id && edge.kind === 'LABEL');
    if (labels.length !== choice.label_values.length || !choice.label_values.every((value: Row) => labels.filter(edge => same(edge.label, value)).length === 1)) fail('DEFINITION_INVALID', `/choices/${i}`);
    const carrier = step.completion;
    if (carrier.route_label_field === null || carrier.route_label_type_ref !== choice.label_type_ref) fail('DEFINITION_INVALID', `/choices/${i}`);
  }
  for (const step of definition.steps as Row[]) {
    const outgoing = relations.filter(edge => edge.from === step.id);
    const failures = outgoing.filter(edge => edge.kind === 'FAILURE');
    const labels = outgoing.filter(edge => edge.kind === 'LABEL');
    const sequences = outgoing.filter(edge => edge.kind === 'SEQUENCE');
    if (PROPOSABLE.has(step.kind)) {
      if (step.failure_behavior === 'FAILURE_EDGE' ? failures.length !== 1 : failures.length !== 0) fail('DEFINITION_INVALID', '/relationships');
      if (step.kind === 'FANOUT_EXPAND') {
        if (sequences.length || labels.length) fail('DEFINITION_INVALID', '/relationships');
      } else if (choices.has(step.id)) {
        if (sequences.length) fail('DEFINITION_INVALID', '/relationships');
      } else if (sequences.length !== 1 || labels.length) fail('DEFINITION_INVALID', '/relationships');
    } else if (step.kind === 'PARALLEL_SPLIT') {
      if (outgoing.length) fail('DEFINITION_INVALID', '/relationships');
    } else if (step.kind === 'PARALLEL_JOIN' || step.kind === 'FANOUT_JOIN') {
      if (sequences.length !== 1 || outgoing.length !== 1) fail('DEFINITION_INVALID', '/relationships');
    } else if (step.kind === 'TERMINAL' && outgoing.length) fail('DEFINITION_INVALID', '/relationships');
  }
  if (!unique(definition.deadlines, row => row.step_id)) fail('DEFINITION_INVALID', '/deadlines');
  for (const [i, deadline] of (definition.deadlines as Row[]).entries()) {
    const step = steps.get(deadline.step_id);
    if (!step || !PROPOSABLE.has(step.kind)) fail('REFERENCE_INVALID', `/deadlines/${i}`);
    if (deadline.due.kind === 'ELAPSED_FROM_ANCESTOR' && !steps.has(deadline.due.anchor_step_id)) fail('REFERENCE_INVALID', `/deadlines/${i}/due/anchor_step_id`);
    if (deadline.due.kind === 'ABSOLUTE_INSTANT') { try { instant(deadline.due.instant); } catch { fail('DEFINITION_INVALID', `/deadlines/${i}/due`); } }
    const edges = relations.filter(edge => edge.kind === 'EXPIRY' && edge.from === deadline.step_id && edge.deadline_ref === deadline.id);
    if (deadline.expiry_target === null ? edges.length !== 0 : edges.length !== 1 || edges[0]?.to !== deadline.expiry_target) fail('DEFINITION_INVALID', `/deadlines/${i}`);
  }
  const graph = normalizedGraph(definition).outgoing;
  const reachable = new Set<string>(), pending = [definition.root as string];
  while (pending.length) { const next = pending.pop()!; if (reachable.has(next)) continue; reachable.add(next); for (const edge of graph.get(next) ?? []) pending.push(edge.to); }
  if (reachable.size !== definition.steps.length) fail('DEFINITION_INVALID', '/steps');
}

function memberKey(members: Iterable<string>): string { return JSON.stringify([...members].sort(byteCompare)); }

function loopSemantics(definition: Row, graph: NormalizedGraph): void {
  const steps = index(definition.steps), relations = definition.relationships as Row[];
  const cyclicComponents = stronglyConnected(graph.outgoing).filter(component => cyclic(component, graph.outgoing));
  if (definition.profile === 'LINEAR' && cyclicComponents.length) fail('UNSUPPORTED_FEATURE', '/relationships');
  const componentKeys = new Set(cyclicComponents.map(memberKey));
  const loopForComponent = new Map<string, Row>(), loopByStep = new Map<string, string>();
  for (const [i, loop] of (definition.loops as Row[]).entries()) {
    for (const member of loop.member_step_ids) if (!steps.has(member)) fail('REFERENCE_INVALID', `/loops/${i}/member_step_ids`);
    if (!steps.has(loop.entry_step_id) || !steps.has(loop.back_edge_from_step_id)) fail('REFERENCE_INVALID', `/loops/${i}`);
    const members = new Set<string>(loop.member_step_ids);
    if (!members.has(loop.entry_step_id) || !members.has(loop.back_edge_from_step_id)) fail('UNSUPPORTED_FEATURE', `/loops/${i}`);
    const key = memberKey(members);
    if (!componentKeys.has(key)) fail('UNSUPPORTED_FEATURE', `/loops/${i}`);
    if (loopForComponent.has(key)) fail('UNSUPPORTED_FEATURE', `/loops/${i}`);
    loopForComponent.set(key, loop);
    for (const member of members) {
      const prior = loopByStep.get(member);
      if (prior && prior !== loop.id) fail('UNSUPPORTED_FEATURE', `/loops/${i}/member_step_ids`);
      loopByStep.set(member, loop.id);
    }
  }
  for (const component of cyclicComponents) {
    const key = memberKey(component), loop = loopForComponent.get(key);
    if (!loop) fail('UNSUPPORTED_FEATURE', '/relationships');
    const members = new Set(component);
    if (component.some(step => ['FANOUT_EXPAND', 'FANOUT_JOIN', 'PARALLEL_SPLIT', 'PARALLEL_JOIN'].includes(steps.get(step)?.kind))) fail('UNSUPPORTED_FEATURE', `/loops/${loop.id}`);
    const backEdges = relations.filter(edge => edge.from === loop.back_edge_from_step_id && edge.to === loop.entry_step_id);
    if (backEdges.length !== 1) fail('UNSUPPORTED_FEATURE', `/loops/${loop.id}`);
    const backEdge = backEdges[0];
    const internalEntryEdges = relations.filter(edge => members.has(edge.from) && edge.to === loop.entry_step_id);
    if (internalEntryEdges.length !== 1 || internalEntryEdges[0] !== backEdge) fail('UNSUPPORTED_FEATURE', `/loops/${loop.id}`);
    if (hasCycle(graph.outgoing, members, backEdge)) fail('UNSUPPORTED_FEATURE', `/loops/${loop.id}`);
    for (const member of members) for (const edge of graph.incoming.get(member) ?? []) {
      if (!members.has(edge.from) && edge.to !== loop.entry_step_id) fail('UNSUPPORTED_FEATURE', `/loops/${loop.id}`);
    }
  }
  for (const [from, edges] of graph.outgoing) for (const edge of edges) {
    const fromLoop = loopByStep.get(from), toLoop = loopByStep.get(edge.to);
    if (fromLoop && toLoop && fromLoop !== toLoop) fail('UNSUPPORTED_FEATURE', '/loops');
  }
}

type Region = { head: string; join: string; nodes: Set<string>; crossedSibling: boolean; crossedBoundary: boolean };
type StructuredRegion = Region & { boundary: string };

function forwardReach(start: string, graph: NormalizedGraph): Set<string> {
  const reachable = new Set<string>(), pending = [start];
  while (pending.length) {
    const node = pending.pop()!;
    if (reachable.has(node)) continue;
    reachable.add(node); pending.push(...(graph.outgoing.get(node) ?? []).map(edge => edge.to));
  }
  return reachable;
}

function collectRegion(head: string, join: string, siblingHeads: Set<string>, graph: NormalizedGraph, afterJoin = new Set<string>()): Region {
  const nodes = new Set<string>(), pending = [head]; let crossedSibling = false, crossedBoundary = false;
  while (pending.length) {
    const node = pending.pop()!;
    if (node === join || nodes.has(node)) continue;
    nodes.add(node);
    for (const edge of graph.outgoing.get(node) ?? []) {
      if (edge.to === join) continue;
      if (afterJoin.has(edge.to)) crossedBoundary = true;
      if (siblingHeads.has(edge.to)) { crossedSibling = true; continue; }
      pending.push(edge.to);
    }
  }
  return { head, join, nodes, crossedSibling, crossedBoundary };
}

function regionReachesJoin(region: Region, graph: NormalizedGraph): boolean {
  const reaches = new Set<string>([region.join]), pending = [region.join];
  while (pending.length) {
    const node = pending.pop()!;
    for (const edge of graph.incoming.get(node) ?? []) {
      if (!region.nodes.has(edge.from) || reaches.has(edge.from)) continue;
      reaches.add(edge.from); pending.push(edge.from);
    }
  }
  return [...region.nodes].every(node => reaches.has(node));
}

function isLoopBack(edge: GraphEdge, loops: Row[]): boolean {
  return !edge.implicit && loops.some(loop => loop.back_edge_from_step_id === edge.from && loop.entry_step_id === edge.to);
}

function uniqueOwner(seen: Map<string, string>, value: string, owner: string, path: string): void {
  if (seen.has(value)) fail('DEFINITION_INVALID', path);
  seen.set(value, owner);
}

function structuredSemantics(definition: Row, graph: NormalizedGraph): void {
  const steps = index(definition.steps), loops = definition.loops as Row[];
  const splitOwners = new Map<string, string>(), parallelJoinOwners = new Map<string, string>(), expandOwners = new Map<string, string>(), fanoutJoinOwners = new Map<string, string>();
  const branchHeads = new Map<string, string>(), fanoutHeads = new Map<string, string>();
  const structuredRegions: StructuredRegion[] = [];
  for (const block of definition.parallel_blocks as Row[]) {
    uniqueOwner(splitOwners, block.split_step_id, block.id, '/parallel_blocks');
    uniqueOwner(parallelJoinOwners, block.join_step_id, block.id, '/parallel_blocks');
    for (const branch of block.branches) {
      const head = steps.get(branch.head_step_id);
      if (!head || !PROPOSABLE.has(head.kind)) fail('DEFINITION_INVALID', '/parallel_blocks');
      uniqueOwner(branchHeads, branch.head_step_id, block.id + ':' + branch.id, '/parallel_blocks');
    }
  }
  for (const fanout of definition.fanouts as Row[]) {
    uniqueOwner(expandOwners, fanout.expand_step_id, fanout.id, '/fanouts');
    uniqueOwner(fanoutJoinOwners, fanout.join_step_id, fanout.id, '/fanouts');
    const head = steps.get(fanout.region_head_step_id);
    if (!head || !PROPOSABLE.has(head.kind)) fail('DEFINITION_INVALID', '/fanouts');
    uniqueOwner(fanoutHeads, fanout.region_head_step_id, fanout.id, '/fanouts');
  }
  for (const step of definition.steps as Row[]) {
    if (step.kind === 'PARALLEL_SPLIT' && !splitOwners.has(step.id)) fail('DEFINITION_INVALID', '/parallel_blocks');
    if (step.kind === 'PARALLEL_JOIN' && !parallelJoinOwners.has(step.id)) fail('DEFINITION_INVALID', '/parallel_blocks');
    if (step.kind === 'FANOUT_EXPAND' && !expandOwners.has(step.id)) fail('DEFINITION_INVALID', '/fanouts');
    if (step.kind === 'FANOUT_JOIN' && !fanoutJoinOwners.has(step.id)) fail('DEFINITION_INVALID', '/fanouts');
  }
  for (const block of definition.parallel_blocks as Row[]) {
    const siblingHeads = new Set<string>(block.branches.map((branch: Row) => branch.head_step_id));
    const afterJoin = forwardReach(block.join_step_id, graph);
    const regions = block.branches.map((branch: Row) => collectRegion(branch.head_step_id, block.join_step_id, new Set([...siblingHeads].filter(head => head !== branch.head_step_id)), graph, afterJoin));
    structuredRegions.push(...regions.map((region: Region) => ({ ...region, boundary: block.split_step_id })));
    if (regions.some((region: Region) => region.crossedSibling || region.crossedBoundary || !regionReachesJoin(region, graph))) fail('DEFINITION_INVALID', `/parallel_blocks/${block.id}`);
    for (let i = 0; i < regions.length; i++) for (let j = i + 1; j < regions.length; j++) {
      if ([...regions[i].nodes].some(node => regions[j].nodes.has(node))) fail('DEFINITION_INVALID', `/parallel_blocks/${block.id}/branches`);
    }
    const incomingSplit = (graph.incoming.get(block.split_step_id) ?? []).filter(edge => !edge.implicit);
    if (incomingSplit.length !== 1 || regions.some((region: Region) => region.nodes.has(incomingSplit[0]?.from))) fail('DEFINITION_INVALID', `/parallel_blocks/${block.id}/split_step_id`);
    if ((graph.outgoing.get(block.split_step_id) ?? []).some(edge => !edge.implicit)) fail('DEFINITION_INVALID', `/parallel_blocks/${block.id}/split_step_id`);
    for (const region of regions) {
      for (const edge of (graph.incoming.get(region.head) ?? []).filter(candidate => !candidate.implicit)) {
        if (!region.nodes.has(edge.from) || !isLoopBack(edge, loops)) fail('DEFINITION_INVALID', `/parallel_blocks/${block.id}/branches`);
      }
    }
    const joinIncoming = (graph.incoming.get(block.join_step_id) ?? []).filter(edge => !edge.implicit);
    const branchNodes = new Set(regions.flatMap((region: Region) => [...region.nodes]));
    if (joinIncoming.some(edge => !branchNodes.has(edge.from))) fail('DEFINITION_INVALID', `/parallel_blocks/${block.id}/join_step_id`);
  }
  for (const fanout of definition.fanouts as Row[]) {
    const afterJoin = forwardReach(fanout.join_step_id, graph);
    const region = collectRegion(fanout.region_head_step_id, fanout.join_step_id, new Set(), graph, afterJoin);
    structuredRegions.push({ ...region, boundary: fanout.expand_step_id });
    if (region.crossedBoundary || !regionReachesJoin(region, graph)) fail('DEFINITION_INVALID', `/fanouts/${fanout.id}`);
    const incomingExpand = (graph.incoming.get(fanout.expand_step_id) ?? []).filter(edge => !edge.implicit);
    if (incomingExpand.length > 1 || incomingExpand.some(edge => region.nodes.has(edge.from))) fail('DEFINITION_INVALID', `/fanouts/${fanout.id}/expand_step_id`);
    for (const edge of (graph.incoming.get(region.head) ?? []).filter(candidate => !candidate.implicit)) {
      if (!region.nodes.has(edge.from) || !isLoopBack(edge, definition.loops as Row[])) fail('DEFINITION_INVALID', `/fanouts/${fanout.id}/region_head_step_id`);
    }
    const joinIncoming = (graph.incoming.get(region.join) ?? []).filter(edge => !edge.implicit);
    if (joinIncoming.some(edge => !region.nodes.has(edge.from))) fail('DEFINITION_INVALID', `/fanouts/${fanout.id}/join_step_id`);
  }
  for (let i = 0; i < structuredRegions.length; i++) for (let j = i + 1; j < structuredRegions.length; j++) {
    const left = structuredRegions[i], right = structuredRegions[j];
    if (![...left.nodes].some(node => right.nodes.has(node))) continue;
    const leftWithinRight = [...left.nodes].every(node => right.nodes.has(node));
    const rightWithinLeft = [...right.nodes].every(node => left.nodes.has(node));
    if (leftWithinRight === rightWithinLeft) fail('DEFINITION_INVALID', '/steps');
    const child = leftWithinRight ? left : right;
    const parent = leftWithinRight ? right : left;
    if (!parent.nodes.has(child.boundary)) fail('DEFINITION_INVALID', '/steps');
  }
}

function limitSemantics(definition: Row): void {
  const steps = index(definition.steps), occurrenceLimits = index(definition.occurrence_limits, 'step_id');
  const maximums: Record<string, bigint> = {
    maximum_proposals: 4096n,
    maximum_activations: 4096n,
    maximum_actuations: 4096n,
    maximum_active_obligations: 4096n,
    maximum_fanout_objects: 1024n,
  };
  for (const [field, maximum] of Object.entries(maximums)) {
    if (BigInt(definition.limits[field]) > maximum) fail('DEFINITION_INVALID', `/limits/${field}`);
  }
  for (const [i, limit] of (definition.occurrence_limits as Row[]).entries()) {
    const step = steps.get(limit.step_id);
    if (!step) fail('REFERENCE_INVALID', `/occurrence_limits/${i}/step_id`);
    if (!PROPOSABLE.has(step.kind)) fail('DEFINITION_INVALID', `/occurrence_limits/${i}/step_id`);
  }
  for (const step of definition.steps as Row[]) {
    if (PROPOSABLE.has(step.kind) && !occurrenceLimits.has(step.id)) fail('DEFINITION_INVALID', '/occurrence_limits');
  }
  if (BigInt(occurrenceLimits.get(definition.root)?.maximum ?? '0') <= 0n) fail('DEFINITION_INVALID', '/occurrence_limits');
  for (const loop of definition.loops as Row[]) for (const member of loop.member_step_ids as string[]) {
    const step = steps.get(member), limit = occurrenceLimits.get(member);
    if (step && PROPOSABLE.has(step.kind) && (!limit || BigInt(limit.maximum) <= 0n)) fail('DEFINITION_INVALID', '/occurrence_limits');
  }
}

function profileSemantics(definition: Row): void {
  const rank = PROFILES.indexOf(definition.profile);
  if (rank < 0) fail('UNSUPPORTED_FEATURE', '/profile');
  const steps = index(definition.steps);
  if (rank < 1 && (definition.choices.length || definition.loops.length)) fail('UNSUPPORTED_FEATURE', '/profile');
  if (rank < 2 && definition.deadlines.length) fail('UNSUPPORTED_FEATURE', '/profile');
  if (rank < 3 && (definition.parallel_blocks.length || definition.fanouts.length || (definition.steps as Row[]).some(step => ['PARALLEL_SPLIT', 'PARALLEL_JOIN', 'FANOUT_EXPAND', 'FANOUT_JOIN'].includes(step.kind)))) fail('UNSUPPORTED_FEATURE', '/profile');
  for (const [i, block] of (definition.parallel_blocks as Row[]).entries()) {
    if (steps.get(block.split_step_id)?.kind !== 'PARALLEL_SPLIT' || steps.get(block.join_step_id)?.kind !== 'PARALLEL_JOIN') fail('DEFINITION_INVALID', `/parallel_blocks/${i}`);
    for (const branch of block.branches) if (!steps.has(branch.head_step_id)) fail('REFERENCE_INVALID', `/parallel_blocks/${i}/branches`);
  }
  for (const [i, fanout] of (definition.fanouts as Row[]).entries()) {
    if (steps.get(fanout.expand_step_id)?.kind !== 'FANOUT_EXPAND' || steps.get(fanout.join_step_id)?.kind !== 'FANOUT_JOIN' || !steps.has(fanout.region_head_step_id)) fail('DEFINITION_INVALID', `/fanouts/${i}`);
  }
  const normalized = normalizedGraph(definition);
  const graph = new Map<string, string[]>([...normalized.outgoing].map(([step, edges]) => [step, edges.map(edge => edge.to)]));
  for (const fanout of definition.fanouts as Row[]) {
    const stack = [fanout.join_step_id], seen = new Set<string>();
    while (stack.length) {
      const node = stack.pop()!; if (seen.has(node)) continue; seen.add(node);
      if (node === fanout.expand_step_id) fail('UNSUPPORTED_FEATURE', `/fanouts/${fanout.id}`);
      stack.push(...(graph.get(node) ?? []));
    }
  }
  loopSemantics(definition, normalized);
  structuredSemantics(definition, normalized);
  // The candidate permits at most 64 nested loop, branch, or fan-out segments.
  const context = new Map<string, Set<string>>((definition.steps as Row[]).map(step => [step.id, new Set()]));
  for (const loop of definition.loops as Row[]) for (const member of loop.member_step_ids) context.get(member)?.add('L:' + loop.id);
  for (const block of definition.parallel_blocks as Row[]) for (const branch of block.branches) {
    const stack = [branch.head_step_id], seen = new Set<string>();
    while (stack.length) { const node = stack.pop()!; if (seen.has(node) || node === block.join_step_id) continue; seen.add(node); context.get(node)?.add('B:' + block.id + ':' + branch.id); stack.push(...(graph.get(node) ?? [])); }
  }
  for (const fanout of definition.fanouts as Row[]) {
    const stack = [fanout.region_head_step_id], seen = new Set<string>();
    while (stack.length) { const node = stack.pop()!; if (seen.has(node) || node === fanout.join_step_id) continue; seen.add(node); context.get(node)?.add('F:' + fanout.id); stack.push(...(graph.get(node) ?? [])); }
  }
  for (const block of definition.parallel_blocks as Row[]) {
    for (const stepContext of context.values()) {
      const siblingMemberships = [...stepContext].filter(segment => segment.startsWith('B:' + block.id + ':'));
      if (siblingMemberships.length > 1) fail('DEFINITION_INVALID', '/parallel_blocks');
    }
  }
  for (const fanout of definition.fanouts as Row[]) {
    for (const step of definition.steps as Row[]) {
      if (!PROPOSABLE.has(step.kind) || !context.get(step.id)?.has('F:' + fanout.id)) continue;
      const fields = step.fields.filter((field: Row) => field.name === fanout.object_request_field);
      if (fields.length !== 1 || fields[0].type_ref !== fanout.object_type_ref) fail('DEFINITION_INVALID', '/fanouts');
    }
  }
  for (const [step, segments] of context) if (segments.size > 64) fail('DEFINITION_INVALID', `/steps/${step}`);
  // Nested fan-outs must use distinct object request fields along one descendant path.
  for (const outer of definition.fanouts as Row[]) for (const inner of definition.fanouts as Row[]) {
    if (outer.id === inner.id || outer.object_request_field !== inner.object_request_field) continue;
    const stack = [outer.region_head_step_id], seen = new Set<string>();
    while (stack.length) { const node = stack.pop()!; if (seen.has(node) || node === outer.join_step_id) continue; seen.add(node); if (node === inner.expand_step_id) fail('DEFINITION_INVALID', '/fanouts'); stack.push(...(graph.get(node) ?? [])); }
  }
  // COMPOSITION 5.1: an ancestor anchor is proposal-capable, not the deadline's step, in no loop, in no fan-out region
  // lacking the deadline's step, and on every root path to the deadline's step (unreachable once the anchor is removed).
  for (const [i, deadline] of (definition.deadlines as Row[]).entries()) {
    if (deadline.due.kind !== 'ELAPSED_FROM_ANCESTOR') continue;
    const anchor = deadline.due.anchor_step_id, reached = new Set<string>(), stack = [definition.root as string];
    while (stack.length) { const node = stack.pop()!; if (node === anchor || reached.has(node)) continue; reached.add(node); stack.push(...(graph.get(node) ?? [])); }
    const outsideRegion = [...context.get(anchor)!].some(segment => segment.startsWith('F:') && !context.get(deadline.step_id)!.has(segment));
    if (!PROPOSABLE.has(steps.get(anchor)!.kind) || anchor === deadline.step_id || (definition.loops as Row[]).some(loop => loop.member_step_ids.includes(anchor)) || outsideRegion || reached.has(deadline.step_id)) fail('DEFINITION_INVALID', `/deadlines/${i}/due`);
  }
  limitSemantics(definition);
}

function historyBindings(definition: Row): void {
  const steps = index(definition.steps), types = typeTable(definition);
  for (const [i, step] of (definition.steps as Row[]).entries()) {
    if (STRUCTURAL.has(step.kind)) continue;
    const targetFields = index(step.fields, 'name');
    if (!unique(step.prior_effect_bindings, row => row.target_request_field)) fail('DEFINITION_INVALID', `/steps/${i}/prior_effect_bindings`);
    for (const binding of step.prior_effect_bindings as Row[]) {
      const source = steps.get(binding.source_step_id), target = targetFields.get(binding.target_request_field);
      if (!source || !PROPOSABLE.has(source.kind) || !target) fail('REFERENCE_INVALID', `/steps/${i}/prior_effect_bindings`);
      const carrierRows = source.completion.evidence_bindings.filter((row: Row) => row.evidence_field === binding.source_evidence_field);
      if (carrierRows.length !== 1) fail('REFERENCE_INVALID', `/steps/${i}/prior_effect_bindings`);
      const sourceField = source.fields.find((row: Row) => row.name === carrierRows[0].request_field);
      if (!sourceField) fail('REFERENCE_INVALID', `/steps/${i}/prior_effect_bindings`);
      if (sourceField.type_ref !== target.type_ref || !['IDENTITY', 'STRING', 'BOOLEAN', 'INTEGER', 'DECIMAL', 'INSTANT'].includes(types.get(target.type_ref)?.kind ?? '')) fail('DEFINITION_INVALID', `/steps/${i}/prior_effect_bindings`);
    }
    for (const separation of step.prior_actor_separations as Row[]) {
      const source = steps.get(separation.prior_step_id);
      if (!source || !PROPOSABLE.has(source.kind)) fail('REFERENCE_INVALID', `/steps/${i}/prior_actor_separations`);
    }
  }
}

export function validateWorkClass(input: unknown, selectedPin: string): { definition: Row; digest: string } {
  requireShape('work-class.schema.json', 'definition', input);
  const definition = input as Row;
  if (definition.specification_pin !== selectedPin) fail('VERSION_UNSUPPORTED', '/specification_pin');
  if (definition.schema !== VERSION + '/work-class-definition') fail('VERSION_UNSUPPORTED', '/schema');
  inventories(definition);
  const types = typeTable(definition);
  stepSemantics(definition, types);
  graphSemantics(definition, types);
  profileSemantics(definition);
  historyBindings(definition);
  const union = [...new Set((definition.steps as Row[]).flatMap(step => step.shared_budgets))].sort(byteCompare);
  if (!same(union, definition.shared_budgets)) fail('DEFINITION_INVALID', '/shared_budgets');
  return { definition, digest: digest('work-class-definition', definition) };
}

export function relationshipDigest(edge: Row): string { return edgeDigest(edge); }
