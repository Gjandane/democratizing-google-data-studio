import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { ApiError, type Trace } from '../../api/types';
import { Button } from '../../components/Button';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { Modal } from '../../components/Modal';
import { LoadingState } from '../../components/Spinner';
import { Table, type Column } from '../../components/Table';

const count = new Intl.NumberFormat('en-US');
const time = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

/** 2300 -> "2.3 s"; under a second stays in ms. */
export function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  return seconds < 60 ? `${seconds.toFixed(1)} s` : `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

function formatStart(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : time.format(date);
}

const sum = (traces: Trace[], pick: (trace: Trace) => number) => traces.reduce((total, trace) => total + pick(trace), 0);

const COLUMNS: Column<Trace>[] = [
  { id: 'node', header: 'Node', mono: true, cell: (t) => t.node },
  { id: 'model', header: 'Model', mono: true, cell: (t) => t.model ?? '—' },
  { id: 'input', header: 'Input tokens', align: 'right', cell: (t) => count.format(t.input_tokens) },
  { id: 'output', header: 'Output tokens', align: 'right', cell: (t) => count.format(t.output_tokens) },
  { id: 'latency', header: 'Latency', align: 'right', cell: (t) => formatLatency(t.latency_ms) },
  {
    id: 'status',
    header: 'Status',
    cell: (t) =>
      t.status === 'ok' ? (
        <span className="rounded-control bg-success-soft px-1.5 py-0.5 text-caption font-medium text-success">OK</span>
      ) : (
        <span className="flex flex-col gap-0.5">
          <span className="w-fit rounded-control bg-danger-soft px-1.5 py-0.5 text-caption font-medium text-danger">Error</span>
          {t.error && <span className="max-w-64 text-caption text-text-muted">{t.error}</span>}
        </span>
      ),
  },
  { id: 'started', header: 'Started', cell: (t) => formatStart(t.started_at) },
];

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; traces: Trace[] };

interface TraceModalProps {
  open: boolean;
  onClose: () => void;
  /** The open build, if any: the table can then be narrowed to its runs. */
  buildId?: string;
}

/** Every model run (newest first) with its tokens and latency, and the totals. */
export function TraceModal({ open, onClose, buildId }: TraceModalProps) {
  const [scope, setScope] = useState<'build' | 'all'>(buildId ? 'build' : 'all');
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const filter = scope === 'build' ? buildId : undefined;

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoad({ status: 'loading' });
    api.listTraces(filter).then(
      (traces) => {
        if (active) setLoad({ status: 'ready', traces });
      },
      (error: unknown) => {
        const message = error instanceof ApiError ? error.message : "Couldn't load the runs. Try again.";
        if (active) setLoad({ status: 'error', message });
      },
    );
    return () => {
      active = false;
    };
  }, [open, filter, attempt]);

  const traces = load.status === 'ready' ? load.traces : [];
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="Trace"
      description="Each model run, newest first, with its tokens and latency."
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
          columns={COLUMNS}
          rows={traces}
          rowKey={(t) => t.run_id}
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
