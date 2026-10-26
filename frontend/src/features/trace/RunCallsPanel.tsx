// One run expanded in Trace: the settings it ran with and each model call (docs/stage-settings-ui.md,
// Stage calls and stage-limit errors; api.md 3.0 RunCalls).
import type { ReactNode } from 'react';
import type { CallOutcome, GenerationProfile, RunCalls, StageCall, StageProfiles, ThinkingLevel } from '../../api/types';
import { ErrorState } from '../../components/ErrorState';
import { LoadingState } from '../../components/Spinner';
import { formatUsd, isGenerationStage, STAGE_META, STAGE_ORDER } from '../settings/stageSettings';
import { count, estimateText, formatLatency, tokens } from './format';

export type CallsLoad = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; calls: RunCalls };

const LEVEL: Record<ThinkingLevel, string> = { low: 'Low', medium: 'Medium', high: 'High' };

const OUTCOME: Record<CallOutcome, string> = {
  ok: 'OK',
  invalid: 'Invalid output',
  output_cutoff: 'Output cut off',
  input_over_limit: 'Input over limit',
  timeout: 'Timed out',
  provider_error: 'Provider error',
  cancelled: 'Cancelled',
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** A model id cut to its column; the full id stays in the title and the accessible text. */
function ModelId({ id, className = '' }: { id: string; className?: string }) {
  return (
    <span className={`min-w-0 truncate font-mono ${className}`} title={id}>
      {id}
    </span>
  );
}

/** One stage of the run's settings snapshot, as a line. */
function profileLine(stage: keyof StageProfiles, stages: StageProfiles): ReactNode {
  const profile = stages[stage];
  const parts = [`${LEVEL[profile.thinking]} thinking`];
  if (isGenerationStage(stage)) {
    const g = profile as GenerationProfile;
    parts.push(
      `input ${count.format(g.input_tokens)}`,
      `output ${count.format(g.output_tokens)}`,
      `${count.format(g.timeout_s)} s`,
      plural(g.transport_retries, 'retry', 'retries'),
      plural(g.validation_repairs, 'repair', 'repairs'),
    );
  } else {
    parts.push(`${count.format(profile.timeout_s)} s`);
  }
  return (
    <span className="flex min-w-0 items-baseline gap-1.5">
      <ModelId id={profile.model} className="max-w-48" />{' '}
      <span className="text-text-muted">{parts.join(', ')}</span>
    </span>
  );
}

function SettingsUsed({ settings }: { settings: RunCalls['settings'] }) {
  return (
    <section aria-label="Settings used">
      <h3 className="text-label font-semibold text-text">Settings used</h3>
      {settings === null ? (
        <p className="mt-1 text-label text-text-muted">Not recorded</p>
      ) : (
        <dl className="mt-1 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-0.5 text-label">
          {STAGE_ORDER.map((stage) => (
            <div key={stage} className="contents">
              <dt className="text-text-muted">{STAGE_META[stage].name}</dt>
              <dd className="min-w-0">{profileLine(stage, settings.stages)}</dd>
            </div>
          ))}
          <dt className="text-text-muted">Fallback model</dt>
          <dd className="flex min-w-0">
            <ModelId id={settings.fallback_model} className="max-w-48" />
          </dd>
          <dt className="text-text-muted">Brief review</dt>
          <dd>{settings.review_briefs ? 'On' : 'Off'}</dd>
        </dl>
      )}
    </section>
  );
}

function Outcome({ outcome }: { outcome: CallOutcome }) {
  const tone = outcome === 'ok' ? 'bg-success-soft text-success' : outcome === 'cancelled' ? 'bg-surface-muted text-text' : 'bg-danger-soft text-text';
  return <span className={`inline-block rounded-control px-1.5 py-0.5 text-caption font-medium whitespace-nowrap ${tone}`}>{OUTCOME[outcome]}</span>;
}

function Model({ call }: { call: StageCall }) {
  const changed = call.fallback || call.requested_model !== call.model;
  if (!changed) return <ModelId id={call.model} className="block max-w-44" />;
  return (
    <span className="flex min-w-0 flex-col">
      <span className="flex min-w-0 items-baseline gap-1 text-text-muted">
        <ModelId id={call.requested_model} className="max-w-40" />{' '}
        <span aria-hidden="true">→</span>{' '}
        <span className="sr-only">then</span>{' '}
      </span>
      <span className="flex min-w-0 items-center gap-1.5">
        <ModelId id={call.model} className="max-w-36" />{' '}
        {call.fallback && <span className="shrink-0 rounded-control bg-primary-soft px-1.5 text-caption font-medium text-primary">Fallback</span>}
      </span>
    </span>
  );
}

interface CallColumn {
  id: string;
  header: string;
  /** A second header line: what the slashes or dots separate. */
  sub?: string;
  right?: boolean;
  cell: (call: StageCall) => ReactNode;
  className?: string;
}

const COLUMNS: CallColumn[] = [
  { id: 'stage', header: 'Stage', cell: (c) => <span title={c.stage}>{STAGE_META[c.stage].name}</span>, className: 'min-w-28 max-w-36' },
  { id: 'page', header: 'Page', right: true, cell: (c) => c.page ?? '—' },
  { id: 'attempt', header: 'Attempt', sub: 'content · try', cell: (c) => `${c.attempt} · try ${c.transport_attempt}`, className: 'whitespace-nowrap' },
  { id: 'model', header: 'Model', sub: 'requested → actual', cell: (c) => <Model call={c} />, className: 'max-w-52' },
  { id: 'thinking', header: 'Thinking', cell: (c) => LEVEL[c.thinking] },
  {
    id: 'input',
    header: 'Input',
    sub: 'measured / enforced / limit',
    right: true,
    cell: (c) => `${tokens(c.input_measured)} / ${tokens(c.input_enforced)} / ${tokens(c.input_limit)}`,
    className: 'whitespace-nowrap',
  },
  {
    id: 'output',
    header: 'Output',
    sub: 'answer · thinking · limit',
    right: true,
    cell: (c) => `${tokens(c.output_tokens)} · ${tokens(c.thinking_tokens)} · ${tokens(c.output_limit)}`,
    className: 'whitespace-nowrap',
  },
  { id: 'outcome', header: 'Outcome', cell: (c) => <Outcome outcome={c.outcome} /> },
  { id: 'time', header: 'Time', right: true, cell: (c) => formatLatency(c.duration_ms), className: 'whitespace-nowrap' },
  { id: 'cost', header: 'Est. cost', right: true, cell: (c) => (c.cost_usd_estimate === null ? 'unknown' : formatUsd(c.cost_usd_estimate)), className: 'whitespace-nowrap' },
];

function CallsTable({ calls }: { calls: StageCall[] }) {
  const align = (column: CallColumn) => (column.right ? 'text-right tabular-nums' : 'text-left');
  return (
    <div className="mt-1.5 overflow-x-auto rounded-control border border-border bg-surface">
      <table className="w-full border-collapse text-label text-text">
        <caption className="sr-only">Stage calls</caption>
        <thead>
          <tr className="border-b border-border bg-surface-muted">
            {COLUMNS.map((column) => (
              <th key={column.id} scope="col" className={`px-2 py-1.5 align-bottom font-medium text-text-muted ${align(column)}`}>
                <span className="block whitespace-nowrap">{column.header}</span>
                {column.sub && <span className="block text-caption font-normal whitespace-nowrap">{column.sub}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {calls.map((call, i) => (
            <tr key={i} data-outcome={call.outcome} className="border-b border-border align-top last:border-b-0">
              {COLUMNS.map((column) => (
                <td key={column.id} data-col={column.id} className={`px-2 py-1.5 ${align(column)} ${column.className ?? ''}`}>
                  {column.cell(call)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The expanded part of a Trace run row: loading, error, or the settings used and the stage calls. */
export function RunCallsPanel({ load, onRetry }: { load: CallsLoad; onRetry: () => void }) {
  if (load.status === 'loading') return <LoadingState className="py-4">Loading the model calls…</LoadingState>;
  if (load.status === 'error') return <ErrorState title="Couldn't load the model calls" message={load.message} onRetry={onRetry} />;
  const { settings, calls, cost_usd_estimate, cost_complete } = load.calls;
  return (
    <div className="flex flex-col gap-3">
      <SettingsUsed settings={settings} />
      <section aria-label="Stage calls">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          <h3 className="text-label font-semibold text-text">Stage calls</h3>
          {calls.length > 0 && (
            <p className="text-label text-text-muted">
              Estimated cost of this run: <span className="font-medium text-text">{estimateText(cost_usd_estimate, cost_complete)}</span>
            </p>
          )}
        </div>
        {calls.length === 0 ? <p className="mt-1 text-label text-text-muted">No model calls in this run</p> : <CallsTable calls={calls} />}
      </section>
    </div>
  );
}
