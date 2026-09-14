import { AdmissionError, byteCompare, canonical, digest } from './canonical.ts';
import { boundSatisfied, decimal, sum } from './math.ts';
import { calendarStart, duration, instant, instantText, validTimezone } from './time.ts';
import { requireShape, VERSION } from './schema.ts';

type Node = Record<string, any>;
type Value = { type_ref: string; value: string | boolean };
type Type = { id: string; kind: string; unit: string | null; nonnegative: boolean };
export type Contribution = { mapping?: string; occurrence: string; key: Value[]; value: Value };
type TypeMap = Map<string, Type>;
function fail(code: string, path = ''): never { throw new AdmissionError(code, path); }
const equal = (left: unknown, right: unknown) => canonical(left) === canonical(right);
const sortedUnique = (values: string[]) => values.every((value, index) => index === 0 || byteCompare(values[index - 1], value) < 0);
const unique = (values: unknown[]) => new Set(values.map(canonical)).size === values.length;

function typed(value: Value, types: TypeMap): Type {
  const type = types.get(value.type_ref);
  if (!type) fail('TYPE_INVALID');
  const payload = value.value;
  if (type.kind === 'BOOLEAN') { if (typeof payload !== 'boolean') fail('TYPE_INVALID'); }
  else {
    if (typeof payload !== 'string') fail('TYPE_INVALID');
    if (type.kind === 'IDENTITY' && !payload.length) fail('TYPE_INVALID');
    if (type.kind === 'INTEGER' && (!/^-?(?:0|[1-9][0-9]*)$/.test(payload) || payload === '-0')) fail('TYPE_INVALID');
    if (type.kind === 'INTEGER' || type.kind === 'DECIMAL') {
      const parsed = decimal(payload, !type.nonnegative);
      if (type.nonnegative && parsed.coefficient < 0n) fail('TYPE_INVALID');
    }
  }
  return type;
}

function walkLiterals(node: Node, types: TypeMap): void {
  if (node.kind === 'LITERAL') typed(node.value, types);
  if (node.kind === 'MEMBER') {
    for (const member of node.members) typed(member, types);
    if (!sortedUnique(node.members.map(canonical))) fail('TYPE_INVALID');
    if (node.members.some((value: Value) => value.type_ref !== node.members[0]?.type_ref)) fail('TYPE_INVALID');
  }
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) for (const child of value) { if (child && typeof child === 'object' && 'kind' in child) walkLiterals(child, types); }
    else if (value && typeof value === 'object' && 'kind' in value) walkLiterals(value, types);
  }
}

function qualifierTypes(node: Node, fields: Node[], types: TypeMap): void {
  const values = (operand: Node): Value[] => operand.kind === 'LITERAL' ? [operand.value] : fields.filter(row => row.name === operand.name).map(row => row.value);
  if (node.kind === 'BOOLEAN') return;
  if (node.kind === 'ALL' || node.kind === 'ANY') { node.operands.forEach((child: Node) => qualifierTypes(child, fields, types)); return; }
  if (node.kind === 'NOT') { qualifierTypes(node.operand, fields, types); return; }
  if (node.kind === 'MEMBER') {
    for (const value of values(node.value)) for (const member of node.members) if (value.type_ref !== member.type_ref) fail('TYPE_INVALID');
    return;
  }
  const left = values(node.left), right = values(node.right);
  if (node.kind === 'COMPARE') for (const value of [...left, ...right]) if (!['INTEGER', 'DECIMAL'].includes(types.get(value.type_ref)!.kind)) fail('TYPE_INVALID');
  for (const a of left) for (const b of right) if (a.type_ref !== b.type_ref) fail('TYPE_INVALID');
}

// Type admission is a complete pass before field presence, ordering or observation binding.
function dynamicTypes(input: Node, aggregate: Node, types: TypeMap): void {
  function fields(rows: Node[], mappings: Node[]) {
    for (const row of rows) typed(row.value, types);
    for (const mapping of mappings) {
      mapping.key_fields.forEach((name: string, index: number) => {
        for (const row of rows.filter(row => row.name === name)) if (row.value.type_ref !== aggregate.key_types[index]) fail('TYPE_INVALID');
      });
      if (aggregate.reducer !== 'COUNT') for (const row of rows.filter(row => row.name === mapping.contribution.field)) if (row.value.type_ref !== (aggregate.reducer === 'SUM' ? aggregate.result_type : aggregate.element_type)) fail('TYPE_INVALID');
      qualifierTypes(mapping.qualifier, rows, types);
    }
  }
  function key(values: Value[]) {
    if (values.length !== aggregate.key_types.length) fail('TYPE_INVALID');
    values.forEach((value, index) => { typed(value, types); if (value.type_ref !== aggregate.key_types[index]) fail('TYPE_INVALID'); });
  }
  for (const operation of input.operations) fields(operation.fields, aggregate.mappings.filter((mapping: Node) => mapping.step_ids.includes(operation.step)));
  for (const pending of input.pending) {
    key(pending.key); typed(pending.contribution, types);
    if (pending.contribution.type_ref !== (aggregate.reducer === 'CARDINALITY' ? aggregate.element_type : aggregate.result_type) || (aggregate.reducer === 'COUNT' && pending.contribution.value !== '1')) fail('TYPE_INVALID');
  }
  for (const observation of input.observations) if (observation.status === 'AVAILABLE') {
    if (observation.kind === 'EVENT_SNAPSHOT') {
      for (const event of observation.events) if (event.state === 'ACTIVE') fields(event.fields, aggregate.committed_source ? [aggregate.committed_source] : []);
    } else for (const statistic of observation.statistics) {
      key(statistic.key);
      if (aggregate.reducer === 'CARDINALITY') {
        if (statistic.accumulator.kind !== 'SET') fail('TYPE_INVALID');
        for (const value of statistic.accumulator.values) { typed(value, types); if (value.type_ref !== aggregate.element_type) fail('TYPE_INVALID'); }
        if (!sortedUnique(statistic.accumulator.values.map(canonical))) fail('TYPE_INVALID');
      } else {
        if (statistic.accumulator.kind !== 'SCALAR') fail('TYPE_INVALID');
        typed({ type_ref: aggregate.result_type, value: statistic.accumulator.value }, types);
      }
    }
  }
}

function operand(node: Node, fields: Map<string, Value>, types: TypeMap): Value {
  const value = node.kind === 'LITERAL' ? node.value : fields.get(node.name);
  if (!value) fail('INPUT_INVALID');
  typed(value, types);
  return value;
}

function predicate(node: Node, fields: Map<string, Value>, types: TypeMap): boolean {
  if (node.kind === 'BOOLEAN') return node.value;
  if (node.kind === 'NOT') return !predicate(node.operand, fields, types);
  if (node.kind === 'ALL' || node.kind === 'ANY') {
    const results = node.operands.map((item: Node) => predicate(item, fields, types));
    return node.kind === 'ALL' ? results.every(Boolean) : results.some(Boolean);
  }
  if (node.kind === 'MEMBER') {
    const value = operand(node.value, fields, types);
    for (const member of node.members) if (member.type_ref !== value.type_ref) fail('TYPE_INVALID');
    return node.members.some((member: Value) => equal(member, value));
  }
  const left = operand(node.left, fields, types), right = operand(node.right, fields, types);
  if (left.type_ref !== right.type_ref) fail('TYPE_INVALID');
  if (node.kind === 'EQUAL') return equal(left, right);
  if (!['INTEGER', 'DECIMAL'].includes(types.get(left.type_ref)!.kind)) fail('TYPE_INVALID');
  const a = decimal(left.value as string, true), b = decimal(right.value as string, true);
  const scale = Math.max(a.scale, b.scale);
  const aa = a.coefficient * 10n ** BigInt(scale - a.scale), bb = b.coefficient * 10n ** BigInt(scale - b.scale);
  return node.operator === 'LT' ? aa < bb : node.operator === 'LTE' ? aa <= bb : node.operator === 'GT' ? aa > bb : aa >= bb;
}

function precision(text: string, kind: string): bigint {
  if ((kind === 'SECOND' && text.includes('.')) || (kind === 'NANOSECOND' && !text.includes('.'))) fail('INPUT_INVALID');
  try { return instant(text); } catch { return fail('INPUT_INVALID'); }
}

function fieldMap(rows: Node[], types: TypeMap): Map<string, Value> {
  for (const row of rows) typed(row.value, types);
  if (!sortedUnique(rows.map(row => row.name))) fail('INPUT_INVALID');
  return new Map(rows.map(row => [row.name, row.value]));
}

function project(fields: Map<string, Value>, mapping: Node, aggregate: Node, types: TypeMap): { key: Value[]; value: Value; selected: boolean } {
  const key = mapping.key_fields.map((name: string, index: number) => {
    const value = fields.get(name); if (!value) fail('INPUT_INVALID');
    if (value.type_ref !== aggregate.key_types[index]) fail('TYPE_INVALID');
    return value;
  });
  let value: Value = { type_ref: aggregate.result_type, value: '1' };
  if (aggregate.reducer !== 'COUNT') {
    value = fields.get(mapping.contribution.field) ?? fail('INPUT_INVALID');
    if (value.type_ref !== (aggregate.reducer === 'SUM' ? aggregate.result_type : aggregate.element_type)) fail('TYPE_INVALID');
  }
  const selected = predicate(mapping.qualifier, fields, types);
  return { key, value, selected };
}

function checkLimits(definition: Node, input?: Node): void {
  const aggregate = definition.aggregate;
  if (definition.types.length > 64 || aggregate.mappings.length > 64 || (input && input.operations.length > 256)) fail('LIMIT_EXCEEDED');
  let nodes = 0;
  function expression(node: Node, depth: number) {
    if (++nodes > 4096 || depth > 64) fail('LIMIT_EXCEEDED');
    for (const child of node.operands ?? []) expression(child, depth + 1);
    if (node.kind === 'NOT') expression(node.operand, depth + 1);
  }
  for (const mapping of aggregate.mappings) expression(mapping.qualifier, 1);
  if (aggregate.committed_source) expression(aggregate.committed_source.qualifier, 1);
  function inspect(value: unknown) {
    if (Array.isArray(value)) { if (value.length > 1024) fail('LIMIT_EXCEEDED'); value.forEach(inspect); }
    else if (value && typeof value === 'object') Object.values(value).forEach(inspect);
  }
  inspect(definition);
  if (input) {
    const normalized = structuredClone(input);
    normalized.observations = [...new Map(normalized.observations.map((item: Node) => [canonical(item), item])).values()];
    for (const observation of normalized.observations) if (observation.events) observation.events = [...new Map(observation.events.map((item: Node) => [canonical(item), item])).values()];
    inspect(normalized);
  }
  const types = new Map<string, Type>(definition.types.map((type: Type) => [type.id, type]));
  function numbers(value: unknown) {
    if (Array.isArray(value)) value.forEach(numbers);
    else if (value && typeof value === 'object') {
      const node = value as Node;
      if (typeof node.type_ref === 'string' && ['INTEGER', 'DECIMAL'].includes(types.get(node.type_ref)?.kind ?? '') && typeof node.value === 'string' && node.value.replace(/[-.]/g, '').length > 128) fail('LIMIT_EXCEEDED');
      if (node.kind === 'SCALAR' && node.value.replace('.', '').length > 128) fail('LIMIT_EXCEEDED');
      if (typeof node.duration_seconds === 'string' && node.duration_seconds.replace('.', '').length > 128) fail('LIMIT_EXCEEDED');
      if (node.kind === 'MAX_AGE' && node.seconds.replace('.', '').length > 128) fail('LIMIT_EXCEEDED');
      Object.values(node).forEach(numbers);
    }
  }
  numbers(input ?? definition);
}

export function validateDefinition(value: unknown, limits = true, integrity = true): { definition: Node; types: TypeMap; identity: string } {
  requireShape('aggregate.schema.json', 'definition', value);
  const definition = value as Node, aggregate = definition.aggregate;
  const types = new Map<string, Type>(definition.types.map((type: Type) => [type.id, type]));
  if (!sortedUnique(definition.types.map((type: Type) => type.id)) || !sortedUnique(aggregate.mappings.map((mapping: Node) => mapping.id))) fail('REFERENCE_INVALID', '/definition');
  for (const id of [aggregate.result_type, ...aggregate.key_types, ...(aggregate.element_type === null ? [] : [aggregate.element_type])]) if (!types.has(id)) fail('REFERENCE_INVALID', '/definition');
  for (const mapping of aggregate.mappings) if (!sortedUnique(mapping.step_ids) || mapping.key_fields.length !== aggregate.key_types.length || mapping.contribution.kind !== aggregate.reducer) fail('REFERENCE_INVALID', '/definition');
  if (aggregate.committed_source && (aggregate.committed_source.key_fields.length !== aggregate.key_types.length || aggregate.committed_source.contribution.kind !== aggregate.reducer)) fail('REFERENCE_INVALID', '/definition');
  if (aggregate.window.kind === 'PER_ACTION' ? aggregate.committed_source !== null || aggregate.pending_policy !== 'EXCLUDE_RESERVED' : aggregate.committed_source === null) fail('REFERENCE_INVALID', '/definition');
  for (const type of types.values()) {
    if (type.unit !== null && type.kind !== 'DECIMAL') fail('TYPE_INVALID');
    if (type.nonnegative && !['INTEGER', 'DECIMAL'].includes(type.kind)) fail('TYPE_INVALID');
  }
  const resultType = types.get(aggregate.result_type)!;
  if (aggregate.reducer === 'SUM' ? resultType.kind !== 'DECIMAL' || resultType.unit === null || !resultType.nonnegative || aggregate.element_type !== null : resultType.kind !== 'INTEGER' || resultType.unit !== null || !resultType.nonnegative || (aggregate.reducer === 'COUNT' ? aggregate.element_type !== null : aggregate.element_type === null)) fail('TYPE_INVALID');
  typed(aggregate.bound, types);
  if (aggregate.bound.type_ref !== aggregate.result_type) fail('TYPE_INVALID');
  for (const mapping of aggregate.mappings) { walkLiterals(mapping.qualifier, types); qualifierTypes(mapping.qualifier, [], types); }
  if (aggregate.committed_source) { walkLiterals(aggregate.committed_source.qualifier, types); qualifierTypes(aggregate.committed_source.qualifier, [], types); }
  if (integrity) definitionIntegrity(aggregate);
  if (limits) checkLimits(definition);
  return { definition, types, identity: digest('aggregate-definition', definition) };
}

function definitionIntegrity(aggregate: Node): void {
  const grid = aggregate.time.precision === 'SECOND' ? 1_000_000_000n : 1n;
  if (aggregate.window.kind === 'ROLLING') {
    const elapsed = duration(aggregate.window.duration_seconds);
    if (elapsed <= 0n || elapsed % grid !== 0n) fail('INPUT_INVALID');
  }
  if (aggregate.committed_source?.freshness.kind === 'MAX_AGE' && duration(aggregate.committed_source.freshness.seconds) % grid !== 0n) fail('INPUT_INVALID');
  if (aggregate.window.kind === 'CALENDAR') {
    if (!validTimezone(aggregate.window.timezone)) fail('INPUT_INVALID');
  }
}

export function evaluateAggregate(value: unknown, selectedPin: string): Node {
  requireShape('aggregate.schema.json', 'input', value);
  const input = value as Node;
  if (input.specification_pin !== selectedPin) fail('VERSION_UNSUPPORTED', '/specification_pin');
  if (input.definition_digest !== digest('aggregate-definition', input.definition)) fail('INPUT_INVALID', '/definition_digest');
  const { definition, types, identity } = validateDefinition(input.definition, false, false);
  const aggregate = definition.aggregate, timeKind = aggregate.time.precision;
  dynamicTypes(input, aggregate, types);
  definitionIntegrity(aggregate);
  if (input.clock.source !== aggregate.time.clock_source) fail('INPUT_INVALID');
  const now = input.clock.status === 'AVAILABLE' ? precision(input.clock.instant, timeKind) : null;
  const contributions: Contribution[] = [];
  for (const operation of input.operations) {
    const fields = fieldMap(operation.fields, types);
    for (const mapping of aggregate.mappings) if (mapping.step_ids.includes(operation.step)) {
      const projected = project(fields, mapping, aggregate, types);
      if (projected.selected) contributions.push({ occurrence: operation.occurrence, key: projected.key, value: projected.value });
    }
  }
  if (!sortedUnique(input.operations.map((operation: Node) => operation.occurrence))) fail('INPUT_INVALID');
  for (const pending of input.pending) {
    typed(pending.contribution, types);
    if (pending.contribution.type_ref !== (aggregate.reducer === 'CARDINALITY' ? aggregate.element_type : aggregate.result_type)) fail('TYPE_INVALID');
    if (aggregate.reducer === 'COUNT' && pending.contribution.value !== '1') fail('TYPE_INVALID');
    if (pending.key.length !== aggregate.key_types.length) fail('TYPE_INVALID');
    pending.key.forEach((element: Value, index: number) => { typed(element, types); if (element.type_ref !== aggregate.key_types[index]) fail('TYPE_INVALID'); });
    if (!aggregate.mappings.some((mapping: Node) => mapping.id === pending.mapping) || input.operations.some((operation: Node) => operation.occurrence === pending.occurrence)) fail('INPUT_INVALID');
  }
  if (!sortedUnique(input.pending.map((pending: Node) => canonical([pending.reservation, pending.mapping, pending.occurrence, pending.key]))) || (aggregate.pending_policy === 'EXCLUDE_RESERVED' && input.pending.length)) fail('INPUT_INVALID');
  const partitions = new Map<string, Node>();
  for (const contribution of contributions) {
    const key = { occurrence: aggregate.window.kind === 'PER_ACTION' ? contribution.occurrence : null, key: contribution.key };
    if (!partitions.has(canonical(key))) partitions.set(canonical(key), { ...key, contributions: [] });
    partitions.get(canonical(key))!.contributions.push(contribution.value);
  }
  const keys = [...new Map(contributions.map(item => [canonical(item.key), item.key])).entries()].sort(([a], [b]) => byteCompare(a, b)).map(([, key]) => key);
  let interval: Node | null = null, queryDigest: string | null = null;
  if (now !== null && partitions.size && aggregate.window.kind !== 'PER_ACTION') {
    const window = aggregate.window;
    let start: bigint;
    try {
      start = window.kind === 'ROLLING' ? now - duration(window.duration_seconds) : calendarStart(now, window.timezone, window.period, window.week_start, window.fiscal_start_month, window.ambiguous, window.nonexistent);
      interval = { start: instantText(start, timeKind === 'NANOSECOND'), end: instantText(now, timeKind === 'NANOSECOND'), start_inclusive: window.start_inclusive, end_inclusive: window.end_inclusive };
    } catch (error) { if (error instanceof AdmissionError) fail(error.code === 'TIME_RANGE' ? 'LIMIT_EXCEEDED' : error.code === 'TIME_INVALID' ? 'INPUT_INVALID' : error.code); throw error; }
    queryDigest = digest('aggregate-query', { definition_digest: identity, interval, keys });
  }
  for (const observation of input.observations) {
    if (!aggregate.committed_source || !partitions.size || observation.provider !== aggregate.committed_source.provider || observation.source !== aggregate.committed_source.source || (queryDigest !== null && observation.request_digest !== queryDigest)) fail('INPUT_INVALID');
    if (observation.status !== 'AVAILABLE') continue;
    const asOf = precision(observation.as_of, timeKind), start = precision(observation.coverage.start, timeKind), end = precision(observation.coverage.end, timeKind);
    if (start > end || (now !== null && asOf > now)) fail('INPUT_INVALID');
    if (observation.kind === 'EVENT_SNAPSHOT') {
      for (const event of observation.events) if (event.state === 'ACTIVE') {
        precision(event.occurred_at, timeKind);
        project(fieldMap(event.fields, types), aggregate.committed_source, aggregate, types);
      }
    } else {
      for (const statistic of observation.statistics) {
        if (statistic.key.length !== aggregate.key_types.length) fail('TYPE_INVALID');
        statistic.key.forEach((element: Value, index: number) => { typed(element, types); if (element.type_ref !== aggregate.key_types[index]) fail('TYPE_INVALID'); });
        if (aggregate.reducer === 'CARDINALITY') {
          if (statistic.accumulator.kind !== 'SET') fail('TYPE_INVALID');
          for (const element of statistic.accumulator.values) { typed(element, types); if (element.type_ref !== aggregate.element_type) fail('TYPE_INVALID'); }
          if (!sortedUnique(statistic.accumulator.values.map(canonical))) fail('TYPE_INVALID');
        } else {
          if (statistic.accumulator.kind !== 'SCALAR') fail('TYPE_INVALID');
          typed({ type_ref: aggregate.result_type, value: statistic.accumulator.value }, types);
        }
      }
      if (!equal(observation.statistics.map((statistic: Node) => statistic.key), keys)) fail('INPUT_INVALID');
      if (interval && !equal(observation.coverage, interval)) fail('INPUT_INVALID');
    }
  }
  checkLimits(definition, input);
  const observations = [...new Map<string, Node>(input.observations.map((item: Node) => [canonical(item), item])).values()];
  let reason: string | null = now === null && partitions.size ? 'TIME_UNAVAILABLE' : null;
  const observation = observations[0];
  if (!reason && partitions.size && aggregate.window.kind !== 'PER_ACTION') {
    if (!observations.length) reason = 'OBSERVATION_MISSING';
    else if (observations.length > 1) reason = 'OBSERVATION_CONFLICT';
    else if (observation.status !== 'AVAILABLE') reason = 'OBSERVATION_' + observation.status;
    else {
      const freshness = aggregate.committed_source.freshness;
      if ((freshness.kind === 'MAX_AGE' && now! - instant(observation.as_of) > duration(freshness.seconds)) || (freshness.kind === 'EXACT_REVISION' && freshness.revision !== observation.revision)) reason = 'OBSERVATION_STALE';
      else {
        const requiredStart = instant(interval!.start), requiredEnd = instant(interval!.end), observedStart = instant(observation.coverage.start), observedEnd = instant(observation.coverage.end);
        if (observedStart > requiredStart || observedEnd < requiredEnd || (observedStart === requiredStart && interval!.start_inclusive && !observation.coverage.start_inclusive) || (observedEnd === requiredEnd && interval!.end_inclusive && !observation.coverage.end_inclusive)) reason = 'OBSERVATION_INCOMPLETE';
        if (!reason && observation.kind === 'EVENT_SNAPSHOT') {
          const events = [...new Map<string, Node>(observation.events.map((event: Node) => [canonical(event), event])).values()];
          if (!unique(events.map(event => event.id))) reason = 'OBSERVATION_CONFLICT';
        }
      }
    }
  }
  const resultPartitions = [...partitions.entries()].sort(([a], [b]) => byteCompare(a, b)).map(([, partition]) => {
    const base = { occurrence: partition.occurrence, key: partition.key };
    if (reason) return { ...base, status: 'INDETERMINATE', accumulator: null, result: null, reasons: [reason] };
    const values: Value[] = [...partition.contributions, ...input.pending.filter((pending: Node) => equal(pending.key, partition.key)).map((pending: Node) => pending.contribution)];
    let committed = '0';
    if (aggregate.window.kind !== 'PER_ACTION') {
      if (observation.kind === 'STATISTIC') {
        const statistic = observation.statistics.find((item: Node) => equal(item.key, partition.key));
        if (aggregate.reducer === 'CARDINALITY') values.push(...statistic.accumulator.values);
        else committed = statistic.accumulator.value;
      } else {
        const events = [...new Map<string, Node>(observation.events.map((event: Node) => [canonical(event), event])).values()];
        for (const event of events) if (event.state === 'ACTIVE') {
          const at = instant(event.occurred_at), start = instant(interval!.start), end = instant(interval!.end);
          if (at < start || at > end || (at === start && !interval!.start_inclusive) || (at === end && !interval!.end_inclusive)) continue;
          const item = project(fieldMap(event.fields, types), aggregate.committed_source, aggregate, types);
          if (item.selected && equal(item.key, partition.key)) values.push(item.value);
        }
      }
    }
    let accumulator: Node, total: string;
    if (aggregate.reducer === 'CARDINALITY') {
      const members = [...new Map(values.map(value => [canonical(value), value])).entries()].sort(([a], [b]) => byteCompare(a, b)).map(([, value]) => value);
      total = String(members.length); accumulator = { kind: 'SET', values: members };
    } else {
      total = sum([committed, ...values.map(value => value.value as string)]); accumulator = { kind: 'SCALAR', value: total };
    }
    const satisfied = boundSatisfied(total, aggregate.operator, aggregate.bound.value);
    return { ...base, status: satisfied ? 'SATISFIED' : 'VIOLATED', accumulator, result: total, reasons: satisfied ? [] : ['BOUND_VIOLATED'] };
  });
  const status = resultPartitions.some(partition => partition.status === 'VIOLATED') ? 'VIOLATED' : resultPartitions.some(partition => partition.status === 'INDETERMINATE') ? 'INDETERMINATE' : 'SATISFIED';
  return { schema: VERSION + '/aggregate-result', specification_pin: selectedPin, definition_digest: identity, status, partitions: resultPartitions, reasons: [...new Set(resultPartitions.flatMap(partition => partition.reasons))].sort(byteCompare) };
}

export function projectOperation(definitionValue: unknown, operation: Node): Contribution[] {
  const { definition, types } = validateDefinition(definitionValue);
  const fields = fieldMap(operation.fields, types), aggregate = definition.aggregate;
  return aggregate.mappings.filter((mapping: Node) => mapping.step_ids.includes(operation.step)).flatMap((mapping: Node) => {
    qualifierTypes(mapping.qualifier, operation.fields, types);
    const result = project(fields, mapping, aggregate, types);
    return result.selected ? [{ mapping: mapping.id, occurrence: operation.occurrence, key: result.key, value: result.value }] : [];
  });
}

export function validateHistoryRecord(definitionValue: unknown, event: Node): void {
  const { definition, types } = validateDefinition(definitionValue);
  requireShape('aggregate.schema.json', 'event', event);
  if (event.state === 'RETRACTED') return;
  precision(event.occurred_at, definition.aggregate.time.precision);
  qualifierTypes(definition.aggregate.committed_source.qualifier, event.fields, types);
  project(fieldMap(event.fields, types), definition.aggregate.committed_source, definition.aggregate, types);
}

export function historyRequest(definitionValue: unknown, operations: Node[], pending: Node[], clock: Node, history: Node, selectedPin: string): Node {
  const { definition, identity } = validateDefinition(definitionValue), aggregate = definition.aggregate;
  const now = instant(clock.instant);
  const contributions = operations.flatMap(operation => projectOperation(definition, operation));
  const keys = [...new Map(contributions.map(row => [canonical(row.key), row.key])).entries()].sort(([a], [b]) => byteCompare(a, b)).map(([, value]) => value);
  const window = aggregate.window;
  const start = window.kind === 'ROLLING' ? now - duration(window.duration_seconds) : calendarStart(now, window.timezone, window.period, window.week_start, window.fiscal_start_month, window.ambiguous, window.nonexistent);
  const interval = { start: instantText(start, false), end: clock.instant, start_inclusive: window.start_inclusive, end_inclusive: window.end_inclusive };
  const source = aggregate.committed_source, latest = new Map<string, Node>();
  for (const row of history.journal) latest.set(row.event.id, row.event);
  const observation = { status: 'AVAILABLE', kind: 'EVENT_SNAPSHOT', provider: source.provider, source: source.source, request_digest: digest('aggregate-query', { definition_digest: identity, interval, keys }), as_of: history.as_of, revision: history.revision, coverage: { start: '0001-01-01T00:00:00Z', end: clock.instant, start_inclusive: true, end_inclusive: true }, events: [...latest.values()], evidence_ref: history.evidence_ref };
  return { schema: VERSION + '/aggregate-input', specification_pin: selectedPin, definition, definition_digest: identity, operations, pending, clock, observations: keys.length ? [observation] : [] };
}
