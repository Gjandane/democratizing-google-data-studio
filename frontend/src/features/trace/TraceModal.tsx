import { ChevronRight } from 'lucide-react';
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../../api/client';
import { ApiError, type BuildCost, type RunCost, type Trace } from '../../api/types';
import { Button } from '../../components/Button';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { focusRing } from '../../components/focus';
import { Modal } from '../../components/Modal';
import { LoadingState } from '../../components/Spinner';
import { Table, type Column } from '../../components/Table';
import { subscribeWorkspace } from '../workspace/stretch';
import { count, estimateText, formatLatency } from './format';
import { RunCallsPanel, type CallsLoad } from './RunCallsPanel';

export { formatLatency } from './format';

const time = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

function formatStart(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : time.format(date);
}

const sum = (traces: Trace[], pick: (trace: Trace) => number) => traces.reduce((total, trace) => total + pick(trace), 0);

const errorText = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

function Status({ trace }: { trace: Trace }) {
  return trace.status === 'ok' ? (
    <span className="rounded-control bg-success-soft px-1.5 py-0.5 text-caption font-medium text-success">OK</span>
  ) : (
    <span className="flex flex-col gap-0.5">
      <span className="w-fit rounded-control bg-danger-soft px-1.5 py-0.5 text-caption font-medium text-text">Error</span>
      {trace.error && <span className="max-w-64 text-caption text-text-muted">{trace.error}</span>}
    </span>
  );
}

/** A run's estimate from the build's cost (by run_id); runs before 3.0 are priced from their Trace totals. */
function RunEstimate({ cost }: { cost: RunCost | undefined }) {
  if (!cost) return <>—</>;
  const text = estimateText(cost.cost_usd_estimate, cost.complete);
  if (cost.basis === 'calls') return <>{text}</>;
  return (
    <span className="flex flex-col items-end">
      <span>{text}</span>{' '}
      <span className="text-caption text-text-muted">from run totals</span>
    </span>
  );
}

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; traces: Trace[] };
type CostLoad = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; cost: BuildCost };

/** The header line of the build's estimate (api.md 3.0, Cost estimates: always "Estimated", with the date prices were checked). */
function CostSummary({ load, onRetry }: { load: CostLoad; onRetry: () => void }) {
  if (load.status === 'loading') return <>Estimated cost of this build: loading…</>;
  if (load.status === 'error') {
    return (
      <span className="flex flex-wrap items-center gap-x-2">
        <span>{`Couldn't load the estimated cost of this build. ${load.message}`}</span>
        <Button size="sm" variant="ghost" onClick={onRetry}>
          Try again
        </Button>
      </span>
    );
  }
  const { cost_usd_estimate, complete, prices_checked_on } = load.cost;
  const notes = [
    !complete && 'Some calls have no price or thinking count.',
    prices_checked_on && `Prices checked ${prices_checked_on}.`,
    'Actual billing may differ.',
  ].filter(Boolean);
  return (
    <>
      <span className="block" data-build-cost>
        Estimated cost of this build: <span className="font-semibold text-text">{estimateText(cost_usd_estimate, complete)}</span>
      </span>
      <span className="block text-caption">{notes.join(' ')}</span>
    </>
  );
}

interface TraceModalProps {
  open: boolean;
  onClose: () => void;
  /** The open build, if any: the table can then be narrowed to its runs, and the header shows its estimated cost. */
  buildId?: string;
  /** Opens with this run expanded and focused ("View model calls" on a run error). */
  runId?: string;
}

/**
 * Every model run (newest first) with its tokens, latency and estimated cost, and the totals; a run
 * expands into the settings it used and its model calls (docs/stage-settings-ui.md).
 */
export function TraceModal({ open, onClose, buildId, runId }: TraceModalProps) {
  const [scope, setScope] = useState<'build' | 'all'>(buildId ? 'build' : 'all');
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [cost, setCost] = useState<CostLoad>({ status: 'loading' });
  const [costAttempt, setCostAttempt] = useState(0);
  // Bumped by each `run.finished` of the open build: the runs and the cost are read again in place.
  const [refresh, setRefresh] = useState(0);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set(runId ? [runId] : []));
  const [calls, setCalls] = useState<ReadonlyMap<string, CallsLoad>>(() => new Map());
  const filter = scope === 'build' ? buildId : undefined;
  const base = useId();
  // Calls requests in flight, and those whose run finished meanwhile (their answer is read again).
  const requested = useRef(new Set<string>());
  const restart = useRef(new Set<string>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // The request whose runs are on screen: a refetch of the same one (after `run.finished`) keeps
  // them there, and a failed refetch leaves them; anything else shows loading, then its error.
  const shownList = useRef<string | null>(null);
  useEffect(() => {
    if (!open) return;
    let active = true;
    const key = `${filter ?? ''}|${attempt}`;
    const quiet = shownList.current === key;
    if (!quiet) setLoad({ status: 'loading' });
    api.listTraces(filter).then(
      (traces) => {
        if (!active) return;
        shownList.current = key;
        setLoad({ status: 'ready', traces });
      },
      (error: unknown) => {
        if (!active || quiet) return;
        shownList.current = null;
        setLoad({ status: 'error', message: errorText(error, "Couldn't load the runs. Try again.") });
      },
    );
    return () => {
      active = false;
    };
  }, [open, filter, attempt, refresh]);

  const shownCost = useRef<string | null>(null);
  useEffect(() => {
    if (!open || !buildId) return;
    let active = true;
    const key = `${buildId}|${costAttempt}`;
    const quiet = shownCost.current === key;
    if (!quiet) setCost({ status: 'loading' });
    api.getBuildCost(buildId).then(
      (loaded) => {
        if (!active) return;
        shownCost.current = key;
        setCost({ status: 'ready', cost: loaded });
      },
      (error: unknown) => {
        if (!active || quiet) return;
        shownCost.current = null;
        setCost({ status: 'error', message: errorText(error, 'Try again.') });
      },
    );
    return () => {
      active = false;
    };
  }, [open, buildId, costAttempt, refresh]);

  // The workspace's stream: a finished run changes the runs, the cost and that run's calls.
  useEffect(() => {
    if (!open || !buildId) return;
    return subscribeWorkspace(buildId, (event) => {
      if (event === 'open-references' || event.name !== 'run.finished') return;
      const finished = event.data.run_id;
      if (requested.current.has(finished)) restart.current.add(finished);
      setRefresh((n) => n + 1);
      setCalls((map) => {
        if (!map.has(finished)) return map;
        const next = new Map(map);
        next.delete(finished);
        return next;
      });
    });
  }, [open, buildId]);

  // Calls load once per run, when it first expands (and again after a retry or its run.finished).
  useEffect(() => {
    if (!open) return;
    const missing = [...expanded].filter((id) => !calls.has(id) && !requested.current.has(id));
    if (missing.length === 0) return;
    for (const id of missing) requested.current.add(id);
    setCalls((map) => {
      const next = new Map(map);
      for (const id of missing) next.set(id, { status: 'loading' });
      return next;
    });
    for (const id of missing) {
      api
        .getRunCalls(id)
        .then(
          (loaded): CallsLoad => ({ status: 'ready', calls: loaded }),
          (error: unknown): CallsLoad => ({ status: 'error', message: errorText(error, "Couldn't load the model calls. Try again.") }),
        )
        .then((result) => {
          requested.current.delete(id);
          if (!mounted.current) return;
          if (restart.current.delete(id)) {
            setCalls((map) => {
              const next = new Map(map);
              next.delete(id);
              return next;
            });
            return;
          }
          setCalls((map) => new Map(map).set(id, result));
        });
    }
  }, [open, expanded, calls]);

  const toggle = (id: string) =>
    setExpanded((ids) => {
      const next = new Set(ids);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const retryCalls = useCallback((id: string) => {
    setCalls((map) => {
      const next = new Map(map);
      next.delete(id);
      return next;
    });
  }, []);

  const toggleId = (id: string) => `${base}-run-${id}`;
  const detailId = (id: string) => `${base}-calls-${id}`;

  // Opened at a run: move focus to its row once the runs are on screen.
  const focusedRun = useRef(false);
  const traces = load.status === 'ready' ? load.traces : [];
  useLayoutEffect(() => {
    if (!runId || focusedRun.current || load.status !== 'ready') return;
    focusedRun.current = true;
    const button = document.getElementById(toggleId(runId));
    button?.focus();
    button?.scrollIntoView?.({ block: 'nearest' });
  });

  const runCosts = new Map((cost.status === 'ready' ? cost.cost.runs : []).map((run) => [run.run_id, run]));
  const columns: Column<Trace>[] = [
    {
      id: 'node',
      header: 'Node',
      mono: true,
      className: 'whitespace-nowrap',
      cell: (t) => {
        const isOpen = expanded.has(t.run_id);
        return (
          <button
            type="button"
            id={toggleId(t.run_id)}
            aria-expanded={isOpen}
            aria-controls={isOpen ? detailId(t.run_id) : undefined}
            onClick={() => toggle(t.run_id)}
            className={`-ml-1 inline-flex items-center gap-1 rounded-control px-1 font-mono text-text hover:bg-surface-muted ${focusRing}`}
          >
            <ChevronRight aria-hidden="true" className={`size-3.5 shrink-0 text-text-muted motion-safe:transition-transform ${isOpen ? 'rotate-90' : ''}`} />
            {t.node}
            <span className="sr-only">, model calls</span>
          </button>
        );
      },
    },
    { id: 'model', header: 'Model', mono: true, cell: (t) => (t.model ? <span className="block max-w-48 truncate" title={t.model}>{t.model}</span> : '—') },
    { id: 'input', header: 'Input tokens', align: 'right', cell: (t) => count.format(t.input_tokens) },
    { id: 'output', header: 'Output tokens', align: 'right', cell: (t) => count.format(t.output_tokens) },
    { id: 'latency', header: 'Latency', align: 'right', className: 'whitespace-nowrap', cell: (t) => formatLatency(t.latency_ms) },
    ...(buildId
      ? [{ id: 'cost', header: 'Est. cost', align: 'right' as const, className: 'whitespace-nowrap', cell: (t: Trace) => <RunEstimate cost={runCosts.get(t.run_id)} /> }]
      : []),
    { id: 'status', header: 'Status', cell: (t) => <Status trace={t} /> },
    { id: 'started', header: 'Started', cell: (t) => formatStart(t.started_at) },
  ];

  const detail = (t: Trace): ReactNode => {
    if (!expanded.has(t.run_id)) return null;
    return (
      <div id={detailId(t.run_id)} role="region" aria-label={`Model calls of the ${t.node} run`}>
        <RunCallsPanel load={calls.get(t.run_id) ?? { status: 'loading' }} onRetry={() => retryCalls(t.run_id)} />
      </div>
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title="Trace"
      description={
        buildId ? (
          <CostSummary load={cost} onRetry={() => setCostAttempt((n) => n + 1)} />
        ) : (
          'Each model run, newest first, with its tokens and latency. Open a run to see its model calls.'
        )
      }
      footer={<Button onClick={onClose}>Close</Button>}
    >
      {buildId && (
        <div role="group" aria-label="Runs to show" className="mb-3 flex gap-1">
          <Button size="sm" variant={scope === 'build' ? 'primary' : 'secondary'} aria-pressed={scope === 'build'} onClick={() => setScope('build')}>
            This build
          </Button>
          <Button size="sm" variant={scope === 'all' ? 'primary' : 'secondary'} aria-pressed={scope === 'all'} onClick={() => setScope('all')}>
            All builds
          </Button>
        </div>
      )}
      {load.status === 'loading' && <LoadingState>Loading runs…</LoadingState>}
      {load.status === 'error' && (
        <ErrorState title="Couldn't load the runs" message={load.message} onRetry={() => setAttempt((n) => n + 1)} />
      )}
      {load.status === 'ready' && traces.length === 0 && (
        <EmptyState
          title="No runs yet"
          description="Runs show up here once the assistant has answered, planned or built something."
          headingLevel={3}
          framed
        />
      )}
      {load.status === 'ready' && traces.length > 0 && (
        <Table
          caption="Model runs"
          columns={columns}
          rows={traces}
          rowKey={(t) => t.run_id}
          rowDetail={detail}
          footer={{
            node: `Total, ${traces.length} ${traces.length === 1 ? 'run' : 'runs'}`,
            input: count.format(sum(traces, (t) => t.input_tokens)),
            output: count.format(sum(traces, (t) => t.output_tokens)),
            latency: formatLatency(sum(traces, (t) => t.latency_ms)),
          }}
        />
      )}
    </Modal>
  );
}
