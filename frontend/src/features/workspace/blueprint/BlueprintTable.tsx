// The Blueprint stage body: one row per component (question -> chart type -> fields -> page ->
// status), grouped by page; a blocked row expands into its Feasibility issue (docs/staged-ui.md).
import {
  CalendarRange,
  ChartArea,
  ChartColumn,
  ChartBar,
  ChartLine,
  ChartPie,
  ChartScatter,
  CircleCheck,
  Grid3x3,
  Hash,
  Image,
  ListChecks,
  ListFilter,
  Map as MapIcon,
  OctagonAlert,
  Shapes,
  Table as TableIcon,
  Type,
  type LucideIcon,
} from 'lucide-react';
import { useContext, useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import type { Blueprint, BlueprintComponent, BlueprintRow, Build, Outline } from '../../../api/types';
import { focusRing } from '../../../components/focus';
import { IssueSlotContext, rowResolved } from './issueSlots';

const TYPES: Record<string, { label: string; icon: LucideIcon }> = {
  scorecard: { label: 'Scorecard', icon: Hash },
  time_series: { label: 'Time series', icon: ChartLine },
  bar: { label: 'Bar chart', icon: ChartColumn },
  pie: { label: 'Pie chart', icon: ChartPie },
  table: { label: 'Table', icon: TableIcon },
  pivot_table: { label: 'Pivot table', icon: Grid3x3 },
  geo_map: { label: 'Geo map', icon: MapIcon },
  scatter: { label: 'Scatter chart', icon: ChartScatter },
  text: { label: 'Text', icon: Type },
  image: { label: 'Image', icon: Image },
  date_range: { label: 'Date range control', icon: CalendarRange },
  dropdown: { label: 'Dropdown control', icon: ListFilter },
  area: { label: 'Area chart', icon: ChartArea },
  fixed_size_list: { label: 'Fixed-size list control', icon: ListChecks },
};

/** A catalog type as an icon plus a label; an unknown type keeps its id as the label. */
export function chartType(component: BlueprintComponent): { label: string; icon: LucideIcon } {
  if (component.type === 'bar') {
    const horizontal = component.options.orientation === 'horizontal';
    const percent = component.options.stacked_percent === true;
    const notes = [horizontal && 'horizontal', percent && '100% stacked'].filter(Boolean).join(', ');
    if (notes) return { label: `Bar chart (${notes})`, icon: horizontal ? ChartBar : ChartColumn };
  }
  return TYPES[component.type] ?? { label: component.type, icon: Shapes };
}

const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []);

/** The fields a component reads, in reading order: dimensions, metrics with their aggregation, then the rest. */
export function fieldsOf(component: BlueprintComponent): string[] {
  const metric = ({ field, agg }: BlueprintComponent['metrics'][number]) =>
    agg === 'none' ? field : agg === 'count_distinct' ? `COUNT(DISTINCT ${field})` : `${agg.toUpperCase()}(${field})`;
  const rows = strings(component.options.row_dimensions);
  const columns = strings(component.options.column_dimensions);
  return [
    ...component.dimensions,
    ...(rows.length ? [`rows: ${rows.join(', ')}`] : []),
    ...(columns.length ? [`columns: ${columns.join(', ')}`] : []),
    ...component.metrics.map(metric),
    ...(component.date_dimension ? [`date: ${component.date_dimension}`] : []),
    ...(component.breakdown ? [`breakdown: ${component.breakdown}`] : []),
    ...(component.sort ? [`sort: ${component.sort.field} ${component.sort.order}`] : []),
  ];
}

const cell = 'px-3 py-2 align-top text-left';

function Status({ row, resolved }: { row: BlueprintRow; resolved: boolean }) {
  if (row.status === 'ok')
    return (
      <span className="inline-flex items-center gap-1 font-medium text-success">
        <CircleCheck aria-hidden="true" className="size-3.5 shrink-0" />
        OK
      </span>
    );
  return (
    <span className={`inline-flex items-center gap-1 font-medium ${resolved ? 'text-text' : 'text-danger'}`}>
      <OctagonAlert aria-hidden="true" className="size-3.5 shrink-0" />
      {resolved ? 'Resolved' : 'Blocked'}
    </span>
  );
}

/**
 * The issue slot under a blocked row: the panel portals its decision (or its resolution) in. An
 * issue several rows share has one slot, under its first row; the others point to it.
 */
function IssueRow({ row, columns, owns, ownerLabel, slotRef }: {
  row: BlueprintRow;
  columns: number;
  owns: (issueId: string) => boolean;
  ownerLabel: (issueId: string) => string;
  slotRef: (issueId: string) => (el: HTMLElement | null) => void;
}) {
  const host = useContext(IssueSlotContext);
  const known = row.issue_ids.filter((id) => host?.issues?.has(id));
  return (
    <tr className="border-b border-border bg-danger-soft/40">
      <td colSpan={columns} className="px-3 pb-3">
        {known.map((id) =>
          owns(id) ? (
            <div key={id} ref={slotRef(id)} data-issue-slot={id} className="min-w-0 empty:hidden" />
          ) : (
            <p key={id} className="text-body text-text-muted [overflow-wrap:anywhere]">
              Decided with “{ownerLabel(id)}” above.
            </p>
          ),
        )}
        {known.length < row.issue_ids.length && (
          <p className="text-body text-text-muted">
            {host?.issues === null ? 'Loading this requirement…' : 'This row is blocked by a requirement the current check does not list. Check feasibility or regenerate the blueprint.'}
          </p>
        )}
      </td>
    </tr>
  );
}

export function BlueprintTable({ build, blueprint, outlineSeq }: { build: Build; blueprint: Blueprint; outlineSeq: number }) {
  const host = useContext(IssueSlotContext);
  const [outline, setOutline] = useState<Outline | null>(null);
  // One stable ref callback per issue id, so React never detaches a slot the panel portals into.
  const refs = useRef(new Map<string, (el: HTMLElement | null) => void>());
  const register = host?.register;
  const slotRef = (issueId: string) => {
    let ref = refs.current.get(issueId);
    if (!ref) {
      ref = (el) => register?.(issueId, el);
      refs.current.set(issueId, ref);
    }
    return ref;
  };

  // Question texts and section titles; ids stand in until it loads (or if it fails).
  useEffect(() => {
    let active = true;
    api.getOutline(build.id).then(
      (value) => active && setOutline(value),
      () => {},
    );
    return () => {
      active = false;
    };
  }, [build.id, outlineSeq]);

  const questions = new Map(outline?.sections.flatMap((s) => s.questions.map((q) => [q.id, q.text] as const)) ?? []);
  const sections = new Map(outline?.sections.map((s) => [s.id, s.title]) ?? []);
  const pages = [...new Set(blueprint.rows.map((r) => r.page))].sort((a, b) => a - b);
  const sourceName = (id: string) => build.sources.find((s) => s.id === id)?.name ?? id;
  const { base, joins, union } = blueprint.view_sources;
  const columns = 5;
  // The first blocked row (in page order) that names an issue holds its decision.
  const owner = new Map<string, BlueprintRow>();
  for (const page of pages)
    for (const row of blueprint.rows)
      if (row.page === page && row.status === 'blocked') for (const issueId of row.issue_ids) if (!owner.has(issueId)) owner.set(issueId, row);

  return (
    <div className="mt-4 min-w-0">
      <p className="text-body text-text-muted [overflow-wrap:anywhere]">
        Reads from <span className="font-medium text-text">{sourceName(base)}</span>
        {joins.length > 0 && <> joined with {joins.map((j) => sourceName(j.source_id)).join(', ')}</>}
        {union.length > 0 && <> stacked with {union.map(sourceName).join(', ')}</>}
        {blueprint.view_table && (
          <>
            {' '}through the view <code className="font-mono text-label">{blueprint.view_table}</code>
          </>
        )}
        .
      </p>
      <div className="mt-3 overflow-x-auto rounded-panel border border-border bg-surface">
        <table className="w-full table-fixed border-collapse text-label text-text">
          <caption className="sr-only">Blueprint: the chart chosen for each question, by page</caption>
          <colgroup>
            <col />
            <col className="w-44" />
            <col className="w-56" />
            <col className="w-14" />
            <col className="w-24" />
          </colgroup>
          <thead>
            <tr className="border-b border-border bg-surface-muted text-text-muted">
              <th scope="col" className={`${cell} h-8 font-medium`}>Question</th>
              <th scope="col" className={`${cell} h-8 font-medium`}>Chart</th>
              <th scope="col" className={`${cell} h-8 font-medium`}>Fields</th>
              <th scope="col" className={`${cell} h-8 font-medium`}>Page</th>
              <th scope="col" className={`${cell} h-8 font-medium`}>Status</th>
            </tr>
          </thead>
          {pages.map((page) => {
            const rows = blueprint.rows.filter((r) => r.page === page);
            const titles = [...new Set(rows.map((r) => sections.get(r.section_id)).filter((t): t is string => Boolean(t)))];
            return (
              <tbody key={page}>
                <tr className="border-b border-border bg-surface-muted/60">
                  <th scope="rowgroup" colSpan={columns} className={`${cell} text-body font-semibold`}>
                    Page {page}
                    {titles.length > 0 && <span className="font-normal text-text-muted"> · {titles.join(', ')}</span>}
                  </th>
                </tr>
                {rows.map((row, i) => {
                  const type = chartType(row.component);
                  const Icon = type.icon;
                  const fields = fieldsOf(row.component);
                  const resolved = row.status === 'blocked' && rowResolved(row.issue_ids, host?.issues ?? null);
                  const key = `${page}-${i}`;
                  return [
                    <tr key={key} data-row-status={row.status} className={row.status === 'blocked' ? 'border-b border-border bg-danger-soft/40' : 'border-b border-border'}>
                      <th scope="row" className={`${cell} font-normal`}>
                        <span className="block text-body text-text [overflow-wrap:anywhere]">
                          {row.question_id === null ? 'Supporting control' : (questions.get(row.question_id) ?? row.question_id)}
                        </span>
                        <span className="block text-text-muted [overflow-wrap:anywhere]">
                          {row.component.label}
                          {row.note && <> · {row.note}</>}
                        </span>
                      </th>
                      <td className={cell}>
                        <span className="inline-flex min-w-0 items-start gap-1.5">
                          <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-primary" />
                          <span className="min-w-0 [overflow-wrap:anywhere]">{type.label}</span>
                        </span>
                      </td>
                      <td className={`${cell} font-mono text-text-muted [overflow-wrap:anywhere]`}>
                        {fields.length === 0 ? '—' : fields.map((f, j) => <span key={j} className="block">{f}</span>)}
                      </td>
                      <td className={`${cell} tabular-nums`}>{row.page}</td>
                      <td className={cell}>
                        <Status row={row} resolved={resolved} />
                      </td>
                    </tr>,
                    row.status === 'blocked' && <IssueRow key={`${key}-issue`} row={row} columns={columns} owns={(issueId) => owner.get(issueId) === row} ownerLabel={(issueId) => owner.get(issueId)?.component.label ?? ''} slotRef={slotRef} />,
                  ];
                })}
              </tbody>
            );
          })}
        </table>
      </div>
      {blueprint.derived_fields.length > 0 && (
        <details className="mt-4 rounded-panel border border-border bg-surface">
          <summary className={`cursor-pointer rounded-panel px-4 py-2 text-body font-semibold text-text hover:bg-surface-muted ${focusRing}`}>Derived fields ({blueprint.derived_fields.length})</summary>
          <ul className="space-y-2 border-t border-border px-4 py-3">
            {blueprint.derived_fields.map((field) => (
              <li key={field.name} className="min-w-0 text-body">
                <code className="font-mono text-label text-text">{field.name}</code>
                <span className="text-text-muted"> ({field.type}) · {field.description}</span>
                <code className="block font-mono text-label text-text-muted [overflow-wrap:anywhere]">{field.expression}</code>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
