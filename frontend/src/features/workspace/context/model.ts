// Pure helpers of the Context editor: which fields a KPI may use, which aggregations fit a field's
// type, and where each code issue (a JSON pointer into the Context) shows on screen.
import type { Agg, ColumnType, Context, ContextUpdate, Kpi, Source, ValidationIssue } from '../../../api/types';

export interface FieldOption {
  name: string;
  type: ColumnType;
  derived: boolean;
}

/** Base columns of every source (first one wins on a shared name), then the derived fields. */
export function fieldOptions(sources: Source[], context: Pick<ContextUpdate, 'derived_fields'>): FieldOption[] {
  const seen = new Set<string>();
  const options: FieldOption[] = [];
  for (const column of sources.flatMap((s) => s.columns)) {
    if (seen.has(column.name)) continue;
    seen.add(column.name);
    options.push({ name: column.name, type: column.type, derived: false });
  }
  for (const field of context.derived_fields) {
    if (field.name.trim() === '' || seen.has(field.name)) continue;
    seen.add(field.name);
    options.push({ name: field.name, type: field.type, derived: true });
  }
  return options;
}

export const AGG_LABELS: Record<Agg, string> = {
  sum: 'Sum',
  avg: 'Average',
  count: 'Count',
  count_distinct: 'Count distinct',
  min: 'Minimum',
  max: 'Maximum',
};

/** Aggregations that make sense for a field type: sums and averages need numbers, min and max an order. */
export function aggsFor(type: ColumnType | undefined): Agg[] {
  if (type === 'number') return ['sum', 'avg', 'count', 'count_distinct', 'min', 'max'];
  if (type === 'date' || type === 'datetime') return ['count', 'count_distinct', 'min', 'max'];
  if (type === undefined) return ['sum', 'avg', 'count', 'count_distinct', 'min', 'max'];
  return ['count', 'count_distinct'];
}

/** The aggregation to keep after the field changes: the old one if it still fits, else the type's default. */
export function aggAfterFieldChange(agg: Agg, type: ColumnType | undefined): Agg {
  const allowed = aggsFor(type);
  if (allowed.includes(agg)) return agg;
  return type === 'number' ? 'sum' : 'count_distinct';
}

/** A KPI's definition as one formula line: SUM(revenue), or net_revenue / orders. */
export function formula(kpi: Kpi): string {
  if (kpi.measure) return `${kpi.measure.agg.toUpperCase()}(${kpi.measure.field || '?'})`;
  if (kpi.ratio) return `${kpi.ratio.numerator || '?'} / ${kpi.ratio.denominator || '?'}`;
  return 'No definition';
}

/** A snake_case id not used yet: kpi_1, kpi_2 ... (threshold_1 ...). */
export function newId(prefix: string, rows: { id: string }[]): string {
  const ids = new Set(rows.map((row) => row.id));
  let n = rows.length + 1;
  while (ids.has(`${prefix}_${n}`)) n += 1;
  return `${prefix}_${n}`;
}

/** The draft the editor sends with PUT: the Context without `revision` and `issues`. */
export function toUpdate(context: Context): ContextUpdate {
  const { revision: _revision, issues: _issues, ...rest } = context;
  return structuredClone(rest);
}

/**
 * Places each issue on the deepest rendered path that contains it, segment by segment: an issue
 * at /kpis/2/measure/field lands on that select when it is shown, else on the KPI card /kpis/2,
 * else on the KPI list /kpis, else in the general list ('').
 */
export function placeIssues(issues: ValidationIssue[], rendered: ReadonlySet<string>): Map<string, ValidationIssue[]> {
  const placed = new Map<string, ValidationIssue[]>();
  for (const issue of issues) {
    const segments = issue.path.split('/').slice(1);
    let at = '';
    for (let n = segments.length; n > 0; n -= 1) {
      const candidate = `/${segments.slice(0, n).join('/')}`;
      if (rendered.has(candidate)) {
        at = candidate;
        break;
      }
    }
    placed.set(at, [...(placed.get(at) ?? []), issue]);
  }
  return placed;
}
