import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../../../api/client';
import {
  ApiError,
  specFieldErrors,
  type BuildEventMap,
  type ColumnSpec,
  type GenerationRequest,
  type Generator,
  type Proposal,
  type ReferenceSet,
  type SpecFieldError,
} from '../../../api/types';
import { Button } from '../../../components/Button';
import { ErrorState } from '../../../components/ErrorState';
import { Input, TextArea } from '../../../components/Input';
import { Spinner } from '../../../components/Spinner';
import { Table, type Column as TableColumn } from '../../../components/Table';
import { openReferencePanel, subscribeWorkspace, useRefocusAfter } from '../stretch';

type Finished = BuildEventMap['run.finished'];
type Busy = 'proposing' | 'generating';
type Field = 'columns' | 'row_count' | 'seed';
interface Failure {
  title: string;
  message: string;
  /** Resend the same request with the same generation_key (a transport error). */
  retry?: boolean;
}
interface FieldErrors {
  columns?: SpecFieldError[];
  row_count?: string;
  seed?: string;
}

export const DEFAULT_ROW_COUNT = 1000;
export const DEFAULT_SEED = 42;

const BUSY: Record<Busy, string> = { proposing: 'Proposing schema…', generating: 'Generating CSV…' };
const STYLE_ONLY =
  "Your reference is a style example: it shows how a dashboard looks, not what data it holds, so it can't propose columns. Switch it to Recreate dashboard, or enter the columns yourself.";
const PROPOSE_FAILED = "Couldn't propose a schema";
const GENERATE_FAILED = "Couldn't generate sample data";
const EXAMPLE = `Example:
[
  {"name": "region", "type": "string", "nullable_fraction": 0,
   "generator": {"kind": "choice", "values": ["East", "West"]}}
]`;

const SENTENCE_END = /[.!?]["'”’»)\]]?$/;
const sentence = (text: string) => {
  const trimmed = text.trim();
  return trimmed && !SENTENCE_END.test(trimmed) ? `${trimmed}.` : trimmed;
};
const message = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

/** A new opaque generation_key: `[A-Za-z0-9_-]`, at most 64 characters. */
export function newGenerationKey(): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return `sd_${random}`;
}

type Parsed = { columns: unknown[]; error: null } | { columns: null; error: string | null };

/** The columns textarea as JSON: an empty box only blocks Generate, anything else must be an array. */
function parseColumns(text: string): Parsed {
  if (!text.trim()) return { columns: null, error: null };
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    return { columns: null, error: `This isn't valid JSON (${error instanceof Error ? error.message : 'parse error'}). Fix it to generate.` };
  }
  if (!Array.isArray(value)) return { columns: null, error: 'Enter a JSON array of columns: start with [ and end with ].' };
  return { columns: value, error: null };
}

const wholeNumber = (text: string): number | null => {
  const value = Number(text.trim());
  return /^\d+$/.test(text.trim()) && Number.isSafeInteger(value) ? value : null;
};

const percent = (fraction: number) => `${Math.round(fraction * 1000) / 10}%`;
const places = (n: number) => `${n} ${n === 1 ? 'place' : 'places'}`;
const listed = (values: readonly unknown[], max = 6) =>
  values.length > max ? `${values.slice(0, max).map(String).join(', ')} and ${values.length - max} more` : values.map(String).join(', ');

/** The invented values a generator makes, in words. */
export function describeGenerator(generator: Generator): string {
  switch (generator.kind) {
    case 'sequence':
      return `Sequence from ${generator.prefix}${generator.start}, step ${generator.step}`;
    case 'integer':
      return `Whole numbers ${generator.min} to ${generator.max}`;
    case 'decimal':
      return `Decimals ${generator.min} to ${generator.max}, ${places(generator.decimals)}`;
    case 'choice':
      return `One of ${listed(generator.values)}`;
    case 'boolean':
      return `True in ${percent(generator.true_probability)} of rows`;
    case 'date':
      return `Dates ${generator.start} to ${generator.end}`;
    case 'product':
      return `${generator.fields.join(' × ')}, ${places(generator.decimals)}`;
    case 'lookup':
      return `Mapped from ${generator.field}`;
  }
}

const proposedColumns: TableColumn<ColumnSpec>[] = [
  { id: 'name', header: 'Column', cell: (c) => c.name, mono: true, className: 'align-top [overflow-wrap:anywhere]' },
  { id: 'type', header: 'Type', cell: (c) => c.type, className: 'align-top whitespace-nowrap' },
  { id: 'generator', header: 'Generator', cell: (c) => describeGenerator(c.generator), className: 'align-top [overflow-wrap:anywhere]' },
  { id: 'empty', header: 'Empty', cell: (c) => percent(c.nullable_fraction), align: 'right', className: 'align-top' },
];

interface SyntheticDataPanelProps {
  buildId: string;
  /** The saved reference set: null when there is none, undefined while it loads or after a failed load. */
  reference: ReferenceSet | null | undefined;
  /** Another Connect action is running. */
  disabled?: boolean;
  onBusyChange?: (busy: boolean) => void;
  /** The generation run finished ok: the build now has the synthetic source. */
  onGenerated?: () => void;
}

/**
 * Connect's sample-data path: propose columns from a recreate reference or write them as JSON, then
 * generate an invented CSV once. A generation_key binds one exact request; only a transport retry reuses it.
 */
export function SyntheticDataPanel({ buildId, reference, disabled = false, onBusyChange, onGenerated }: SyntheticDataPanelProps) {
  const headingId = useId();
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [proposalError, setProposalError] = useState<string | null>(null);
  const [columnsText, setColumnsText] = useState('');
  const [rowCount, setRowCount] = useState(String(DEFAULT_ROW_COUNT));
  const [seed, setSeed] = useState(String(DEFAULT_SEED));
  /** The proposal the columns were filled from; null for columns written by hand. */
  const [seededFrom, setSeededFrom] = useState<string | null>(null);
  /** A proposal the server answered `409 synthetic_proposal_stale` for: never sent again. */
  const [staleProposal, setStaleProposal] = useState<string | null>(null);
  const [edited, setEdited] = useState(false);
  const [busy, setBusy] = useState<Busy | null>(null);
  const [status, setStatus] = useState('');
  const [failure, setFailure] = useState<Failure | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [externalBusy, setExternalBusy] = useState(false);
  const [focusRequest, setFocusRequest] = useState<{ field: Field } | null>(null);
  const columnsInput = useRef<HTMLTextAreaElement>(null);
  const rowInput = useRef<HTMLInputElement>(null);
  const seedInput = useRef<HTMLInputElement>(null);
  const proposeButton = useRef<HTMLButtonElement>(null);
  const generateButton = useRef<HTMLButtonElement>(null);
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const pending = useRef<{ runId: string; busy: Busy } | null>(null);
  // A run.finished can arrive before the 202 that names its run: keep recent ones by run_id.
  const finished = useRef(new Map<string, Finished>());
  const activeRuns = useRef(new Set<string>());
  /** The exact request the current generation_key is bound to; an edit, a conflict or a failed run drops it. */
  const request = useRef<GenerationRequest | null>(null);
  const touched = useRef({ rowCount: false, seed: false });
  const autoSeeded = useRef(false);
  const fetchSeq = useRef(0);
  const latestReference = useRef(reference);
  latestReference.current = reference;
  const busyChange = useRef(onBusyChange);
  busyChange.current = onBusyChange;
  const generated = useRef(onGenerated);
  generated.current = onGenerated;

  const locked = busy !== null || disabled || externalBusy;
  const current = proposal && reference && proposal.reference_set_id === reference.id ? proposal : null;
  const proposalId = seededFrom !== null && current?.id === seededFrom && seededFrom !== staleProposal ? seededFrom : null;
  const parsed = parseColumns(columnsText);
  const rows = wholeNumber(rowCount);
  const seedValue = wholeNumber(seed);
  const ready = parsed.columns !== null && rows !== null && seedValue !== null;

  useRefocusAfter(busy === 'proposing', proposeButton);
  useRefocusAfter(busy === 'generating', generateButton);
  useLayoutEffect(() => {
    busyChange.current?.(busy !== null);
  }, [busy]);
  useEffect(() => () => busyChange.current?.(false), []);
  useLayoutEffect(() => {
    if (!focusRequest) return;
    ({ columns: columnsInput, row_count: rowInput, seed: seedInput })[focusRequest.field].current?.focus();
  }, [focusRequest]);

  const seedFrom = (value: Proposal) => {
    setColumnsText(JSON.stringify(value.spec.columns, null, 2));
    if (!touched.current.rowCount) setRowCount(String(value.spec.row_count));
    if (!touched.current.seed) setSeed(String(value.spec.seed));
    setSeededFrom(value.id);
    setEdited(false);
    setFieldErrors({});
    request.current = null;
  };
  const matches = (value: Proposal | null | undefined): value is Proposal =>
    Boolean(value && latestReference.current && value.reference_set_id === latestReference.current.id);

  // A saved proposal for the current reference fills an empty editor once (after a reload, say).
  useEffect(() => {
    if (current && !autoSeeded.current && seededFrom === null && !columnsText.trim()) {
      autoSeeded.current = true;
      seedFrom(current);
    }
  });

  const loadProposal = async (): Promise<Proposal | null | undefined> => {
    const seq = ++fetchSeq.current;
    try {
      const value = await api.getSyntheticProposal(buildId);
      if (!mounted.current || seq !== fetchSeq.current) return undefined;
      setProposal(value);
      setProposalError(null);
      return value;
    } catch (reason) {
      if (mounted.current && seq === fetchSeq.current) setProposalError(message(reason, "Couldn't load the proposed schema. Try again."));
      return undefined;
    }
  };

  const release = () => {
    inFlight.current = false;
    setBusy(null);
  };

  const settle = async (result: Finished) => {
    const run = pending.current;
    if (!run || run.runId !== result.run_id) return;
    pending.current = null;
    const reason = result.error ? `${sentence(result.error)} ` : '';
    if (run.busy === 'proposing') {
      if (result.status === 'ok') {
        const value = await loadProposal();
        if (!mounted.current) return;
        if (matches(value)) {
          seedFrom(value);
          setStatus('Schema proposed. Review the invented columns and assumptions, then generate.');
        } else {
          setStatus('');
          setFailure({
            title: PROPOSE_FAILED,
            message: value === undefined ? "The proposal couldn't be loaded. Select Propose schema again." : 'The reference changed while the schema was proposed. Select Propose schema again.',
          });
        }
      } else {
        setStatus('');
        setFailure({ title: PROPOSE_FAILED, message: `${reason}Enter the columns yourself, or select Propose schema to try again.` });
      }
    } else if (result.status === 'ok') {
      setStatus('Sample data generated. It shows under Sources as Synthetic sample data.');
      generated.current?.();
    } else {
      request.current = null; // Trying again after a failed run is a new request with a new key.
      setStatus('');
      setFailure({ title: GENERATE_FAILED, message: `${reason}Your columns are kept. Select Generate sample data to try again.` });
    }
    release();
  };
  const settleRef = useRef(settle);
  settleRef.current = settle;

  useEffect(() => {
    mounted.current = true;
    const unsubscribe = subscribeWorkspace(buildId, (event) => {
      if (event === 'open-references') return;
      if (event.name === 'run.started') {
        activeRuns.current.add(event.data.run_id);
        setExternalBusy(true);
      }
      if (event.name === 'run.finished') {
        activeRuns.current.delete(event.data.run_id);
        setExternalBusy(activeRuns.current.size > 0);
        finished.current.set(event.data.run_id, event.data);
        if (finished.current.size > 50) finished.current.delete(finished.current.keys().next().value!);
        void settleRef.current(event.data);
      }
      if (event.name === 'ready') {
        // Events aren't replayed: let go of a run whose end may have been missed, keep the request's key.
        activeRuns.current.clear();
        setExternalBusy(false);
        const run = pending.current;
        if (run) {
          pending.current = null;
          inFlight.current = false;
          setBusy(null);
          setStatus(
            run.busy === 'proposing'
              ? 'Reconnected. The latest saved proposal shows here, if there is one.'
              : 'Reconnected. If the sample data loaded, it shows under Sources.',
          );
        }
        void loadProposal().then((value) => {
          if (run?.busy === 'proposing' && mounted.current && matches(value)) seedFrom(value);
        });
      }
    });
    void loadProposal();
    return () => {
      mounted.current = false;
      ++fetchSeq.current;
      unsubscribe();
    };
    // loadProposal reads only refs and setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildId]);

  const follow = (runId: string, kind: Busy) => {
    pending.current = { runId, busy: kind };
    const result = finished.current.get(runId);
    if (result) void settle(result);
  };

  const propose = async () => {
    if (inFlight.current || locked || reference?.mode !== 'recreate') return;
    inFlight.current = true;
    setBusy('proposing');
    setStatus('');
    setFailure(null);
    try {
      const accepted = await api.proposeSyntheticSchema(buildId, reference.id);
      if (mounted.current) follow(accepted.run_id, 'proposing');
    } catch (reason) {
      if (!mounted.current) return;
      release();
      const styleOnly = reason instanceof ApiError && reason.code === 'synthetic_schema_unavailable';
      setFailure({ title: PROPOSE_FAILED, message: styleOnly ? STYLE_ONLY : message(reason, "Couldn't propose a schema. Try again.") });
    }
  };

  const showSpecErrors = (errors: SpecFieldError[], fallback: string) => {
    const next: FieldErrors = {};
    for (const error of errors) {
      if (error.field === 'row_count') next.row_count ??= sentence(error.reason);
      else if (error.field === 'seed') next.seed ??= sentence(error.reason);
      else (next.columns ??= []).push(error);
    }
    if (errors.length === 0) next.columns = [{ field: 'spec', reason: fallback }];
    setFieldErrors(next);
    setStatus('Fix the highlighted field, then generate again.');
    setFocusRequest({ field: next.columns ? 'columns' : next.row_count ? 'row_count' : 'seed' });
  };

  const generate = async () => {
    if (inFlight.current || locked || parsed.columns === null || rows === null || seedValue === null) return;
    const fresh = { proposal_id: proposalId, spec: { schema_version: 1 as const, row_count: rows, seed: seedValue, columns: parsed.columns as ColumnSpec[] } };
    const bound = request.current;
    const same = bound !== null && JSON.stringify({ proposal_id: bound.proposal_id, spec: bound.spec }) === JSON.stringify(fresh);
    const body: GenerationRequest = same ? bound : { generation_key: newGenerationKey(), ...fresh };
    request.current = body;
    inFlight.current = true;
    setBusy('generating');
    setStatus('');
    setFailure(null);
    setFieldErrors({});
    try {
      const accepted = await api.generateSyntheticData(buildId, body);
      if (mounted.current) follow(accepted.run_id, 'generating');
    } catch (reason) {
      if (!mounted.current) return;
      release();
      if (!(reason instanceof ApiError)) {
        setFailure({ title: GENERATE_FAILED, message: "Couldn't start generating. Try again.", retry: true });
        return;
      }
      if (reason.status === 422 && reason.code === 'invalid_generation_spec') {
        showSpecErrors(specFieldErrors(reason), sentence(reason.message));
        return;
      }
      if (reason.code === 'synthetic_request_conflict') {
        request.current = null;
        setFailure({
          title: GENERATE_FAILED,
          message: 'The request changed since its generation key was first used, so the backend refused it. A new key is ready: select Generate sample data again.',
        });
        return;
      }
      if (reason.code === 'synthetic_proposal_stale') {
        // The server no longer accepts this proposal: the columns become the user's own schema.
        request.current = null;
        setStaleProposal(body.proposal_id);
        setFailure({
          title: GENERATE_FAILED,
          message: 'The reference changed after these columns were proposed, so they now count as your own schema. Select Generate sample data to send them, or propose the schema again.',
        });
        return;
      }
      if (reason.code === 'synthetic_requires_empty_build') {
        setFailure({ title: GENERATE_FAILED, message: 'This dashboard already has data, so sample data would mix with it. Start a new dashboard to use sample data.' });
        return;
      }
      // No answer, or a server error: the same request with the same key is safe to send again.
      const transport = reason.status === 0 || reason.code === 'network_error' || reason.status >= 500;
      setFailure({ title: GENERATE_FAILED, message: reason.message, retry: transport });
    }
  };

  /** Any edit makes a new request: the next Generate mints a new key. Edits survive every error. */
  const edit = (field: Field) => {
    request.current = null;
    setFailure(null);
    setFieldErrors(({ [field]: _dropped, ...rest }) => rest);
  };

  const columnsError =
    parsed.error ??
    (fieldErrors.columns && (
      <>
        {fieldErrors.columns.map((error, i) => (
          <span key={i} className="block [overflow-wrap:anywhere]">
            <code className="font-mono">{error.field}</code>: {sentence(error.reason)}
          </span>
        ))}
      </>
    ));

  let source: ReactNode;
  if (reference === undefined) {
    source = (
      <p className="text-body text-text-muted">
        The saved reference isn't loaded. If References below shows an error, retry it there; you can still enter the columns yourself.
      </p>
    );
  } else if (reference === null) {
    source = (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 flex-1 text-body text-text-muted">No reference yet. Add a Recreate dashboard screenshot to propose columns from it, or enter them below.</p>
        <Button size="sm" variant="secondary" disabled={locked} onClick={() => openReferencePanel(buildId)}>
          Add a reference
        </Button>
      </div>
    );
  } else if (reference.mode === 'style') {
    source = (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 flex-1 text-body text-text-muted">{STYLE_ONLY}</p>
        <Button size="sm" variant="secondary" disabled={locked} onClick={() => openReferencePanel(buildId)}>
          Change the reference
        </Button>
      </div>
    );
  } else {
    source = (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 flex-1 text-body text-text-muted">
          Propose columns from your Recreate dashboard screenshot.{columnsText.trim() ? ' The proposal replaces the columns below.' : ''}
        </p>
        <Button ref={proposeButton} variant="secondary" loading={busy === 'proposing'} disabled={locked} onClick={() => void propose()}>
          Propose schema
        </Button>
      </div>
    );
  }

  return (
    <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-4 rounded-panel border border-border bg-surface p-4">
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 id={headingId} className="text-title font-semibold text-text">
            Sample data
          </h3>
          <span className="rounded-control bg-surface-muted px-2 py-0.5 text-caption font-medium text-text-muted">Invented sample data</span>
        </div>
        <p className="text-body text-text-muted">
          Build with an invented CSV when you have no data. A screenshot can suggest column names and types; every value is made up, never read from the screenshot.
        </p>
      </div>

      {source}
      {proposalError && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-label text-danger">{proposalError}</p>
          <Button size="sm" variant="ghost" disabled={locked} onClick={() => void loadProposal()}>
            Retry proposal
          </Button>
        </div>
      )}

      {current && (
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-col gap-0.5">
            <h4 className="text-body font-semibold text-text">Proposed columns</h4>
            <p className="text-caption text-text-muted">Names and types are guesses from your screenshot. The generators invent every value.</p>
          </div>
          <Table caption="Proposed columns" columns={proposedColumns} rows={current.spec.columns} rowKey={(c) => c.name} />
          <div className="flex flex-col gap-1">
            <h4 className="text-body font-semibold text-text">Assumptions</h4>
            {current.assumptions.length > 0 ? (
              <ul aria-label="Assumptions" className="list-disc space-y-0.5 pl-5 text-body text-text-muted [overflow-wrap:anywhere]">
                {current.assumptions.map((assumption, i) => (
                  <li key={i}>{assumption}</li>
                ))}
              </ul>
            ) : (
              <p className="text-body text-text-muted">No assumptions recorded.</p>
            )}
          </div>
        </div>
      )}

      <form
        className="flex min-w-0 flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void generate();
        }}
      >
        <div className="flex min-w-0 flex-col gap-1">
          <TextArea
            ref={columnsInput}
            label="Columns (JSON)"
            name="columns"
            rows={10}
            spellCheck={false}
            autoComplete="off"
            placeholder={EXAMPLE}
            value={columnsText}
            readOnly={busy !== null}
            className="[&_textarea]:font-mono [&_textarea]:text-label"
            hint="A JSON array of columns, each with name, type, nullable_fraction and generator (sequence, integer, decimal, choice, boolean, date, product or lookup). The backend checks the limits."
            error={columnsError}
            onChange={(event) => {
              setColumnsText(event.target.value);
              if (seededFrom !== null) setEdited(true);
              edit('columns');
            }}
          />
          {seededFrom !== null && proposalId === null && (
            <p className="text-caption text-text-muted">These columns came from an earlier proposal, so they are sent as your own schema. Select Propose schema to start from the current reference.</p>
          )}
          {proposalId !== null && edited && (
            <p className="text-caption text-text-muted">You edited the proposed columns. Generate uses your version, and the proposal's assumptions are kept with a note that you edited them.</p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Input
            ref={rowInput}
            label="Row count"
            name="row_count"
            inputMode="numeric"
            autoComplete="off"
            value={rowCount}
            readOnly={busy !== null}
            hint="Default 1,000."
            error={fieldErrors.row_count ?? (rows === null ? 'Enter a whole number of rows.' : null)}
            onChange={(event) => {
              touched.current.rowCount = true;
              setRowCount(event.target.value);
              edit('row_count');
            }}
          />
          <Input
            ref={seedInput}
            label="Seed"
            name="seed"
            inputMode="numeric"
            autoComplete="off"
            value={seed}
            readOnly={busy !== null}
            hint="Default 42. The same seed and columns make the same rows."
            error={fieldErrors.seed ?? (seedValue === null ? 'Enter a whole number.' : null)}
            onChange={(event) => {
              touched.current.seed = true;
              setSeed(event.target.value);
              edit('seed');
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button ref={generateButton} type="submit" variant="primary" loading={busy === 'generating'} disabled={locked || !ready}>
            Generate sample data
          </Button>
          <p role="status" className="flex min-h-5 min-w-0 flex-1 items-center gap-2 text-body text-text-muted">
            {busy && <Spinner />}
            <span className="min-w-0">{busy ? BUSY[busy] : status}</span>
          </p>
        </div>
      </form>

      {failure && (
        <ErrorState
          title={failure.title}
          message={failure.message}
          onRetry={failure.retry ? () => void generate() : undefined}
          retryLabel="Retry"
          retryDisabled={locked}
          actions={
            <Button size="sm" variant="ghost" onClick={() => setFailure(null)}>
              Dismiss
            </Button>
          }
        />
      )}
    </section>
  );
}
