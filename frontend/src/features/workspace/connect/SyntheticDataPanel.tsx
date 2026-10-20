import { FlaskConical } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../../../api/client';
import {
  ApiError,
  specFieldErrors,
  type BuildEventMap,
  type ColumnSpec,
  type GenerationRequest,
  type GenerationStatus,
  type Generator,
  type Proposal,
  type ReferenceSet,
  type Source,
  type SpecFieldError,
  type SyntheticDataset,
} from '../../../api/types';
import { Button } from '../../../components/Button';
import { ErrorState } from '../../../components/ErrorState';
import { Input, TextArea } from '../../../components/Input';
import { Spinner } from '../../../components/Spinner';
import { Table, type Column as TableColumn } from '../../../components/Table';
import { openReferencePanel, subscribeWorkspace, useRefocusAfter } from '../stretch';

type Finished = BuildEventMap['run.finished'];
type Busy = 'proposing' | 'checking' | 'generating' | 'loading';
type Field = 'columns' | 'row_count' | 'seed';
interface Failure {
  title: string;
  message: string;
  /** Show Retry: the same request again (a transport error), or a new key once a failed run is cleaned up. */
  retry?: boolean;
  /** The generation job this failure reports. */
  job?: string;
  /** The build already has data: offer New dashboard. */
  newDashboard?: boolean;
}
interface FieldErrors {
  columns?: SpecFieldError[];
  row_count?: string;
  seed?: string;
}
/** The generation being followed: its key, and its run once the 202 or the job status names it. */
interface Followed {
  key: string;
  runId: string | null;
}

export const DEFAULT_ROW_COUNT = 1000;
export const DEFAULT_SEED = 42;
/** How often an active generation job's persisted status is read (contracts/synthetic-data.md). */
export const POLL_MS = 2000;
/** What every view calls generated data, keyed by `source.kind`. */
export const SYNTHETIC_LABEL = 'Synthetic sample data';

const BUSY: Record<Busy, string> = {
  proposing: 'Proposing schema…',
  checking: 'Checking whether the request arrived…',
  generating: 'Generating CSV…',
  loading: 'Loading sample data…',
};
const CLEANING = 'Cleaning up the failed run…';
const ACTIVE: ReadonlySet<GenerationStatus['state']> = new Set(['queued', 'generating', 'loading']);
const STYLE_ONLY =
  "Your reference is a style example: it shows how a dashboard looks, not what data it holds, so it can't propose columns. Switch it to Recreate dashboard, or enter the columns yourself.";
const PROPOSE_FAILED = "Couldn't propose a schema";
const GENERATE_FAILED = "Couldn't generate sample data";
const LAST_RUN_FAILED = 'The last sample-data run failed';
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
/** No answer, or a server error: the request may or may not have registered. */
const ambiguous = (error: unknown) => !(error instanceof ApiError) || error.status === 0 || error.code === 'network_error' || error.status >= 500;
/** The backend has no job with this key (`build_not_found` is a different, real error). */
const unknownJob = (error: unknown) => error instanceof ApiError && error.status === 404 && error.code !== 'build_not_found';
export const hasSyntheticSource = (sources: readonly Source[]) => sources.some((source) => source.kind === 'synthetic');

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
  /** The generation succeeded: the build now has the synthetic source, so refetch it. */
  onGenerated?: () => void;
  /** A recovered job needs the panel in view: an active run, or a failed one found on load. */
  onJobFound?: () => void;
  /** Sample data can't join a build that has data: offer a new dashboard instead. */
  onNewDashboard?: () => void;
}

/**
 * Connect's sample-data path: propose columns from a recreate reference or write them as JSON, then
 * generate an invented CSV once. A generation_key binds one exact request; only a transport retry
 * reuses it. The job's persisted status (not the event stream alone) decides the outcome: it is read
 * on load, on reconnect and after an unanswered POST, and polled every 2 s while the job runs.
 */
export function SyntheticDataPanel({ buildId, reference, disabled = false, onBusyChange, onGenerated, onJobFound, onNewDashboard }: SyntheticDataPanelProps) {
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
  /** The latest job failed and its cleanup isn't done: no new generation until it is (retry_ready). */
  const [cleaning, setCleaning] = useState(false);
  /** The first look at earlier jobs has answered (or failed): until then a job may be running unseen. */
  const [jobsChecked, setJobsChecked] = useState(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  /** The followed job's status couldn't be read last time: polling goes on, and the status line says so. */
  const [unreadable, setUnreadable] = useState(false);
  const [focusRequest, setFocusRequest] = useState<{ field: Field } | null>(null);
  const columnsInput = useRef<HTMLTextAreaElement>(null);
  const rowInput = useRef<HTMLInputElement>(null);
  const seedInput = useRef<HTMLInputElement>(null);
  const proposeButton = useRef<HTMLButtonElement>(null);
  const generateButton = useRef<HTMLButtonElement>(null);
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const busyNow = useRef<Busy | null>(null);
  const proposalRun = useRef<string | null>(null);
  // A run.finished can arrive before the 202 or status that names its run: keep recent ones by run_id.
  const finished = useRef(new Map<string, Finished>());
  const activeRuns = useRef(new Set<string>());
  /** The exact request the current generation_key is bound to; an edit, a conflict or a failed run drops it. */
  const request = useRef<GenerationRequest | null>(null);
  const job = useRef<Followed | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollSeq = useRef(0);
  const jobsSeq = useRef(0);
  /** Keys this panel sent: their failure keeps the columns in view. */
  const sentKeys = useRef(new Set<string>());
  /** Jobs whose outcome was already shown, so a reconnect doesn't show it again. */
  const reported = useRef(new Set<string>());
  /** The job the visible failure belongs to, if any. */
  const failureJob = useRef<string | null>(null);
  const touched = useRef({ rowCount: false, seed: false });
  const autoSeeded = useRef(false);
  const fetchSeq = useRef(0);
  const latestReference = useRef(reference);
  latestReference.current = reference;
  const busyChange = useRef(onBusyChange);
  busyChange.current = onBusyChange;
  const generated = useRef(onGenerated);
  generated.current = onGenerated;
  const jobFound = useRef(onJobFound);
  jobFound.current = onJobFound;

  const locked = busy !== null || disabled || externalBusy;
  const generateLocked = locked || cleaning || !jobsChecked;
  const current = proposal && reference && proposal.reference_set_id === reference.id ? proposal : null;
  const proposalId = seededFrom !== null && current?.id === seededFrom && seededFrom !== staleProposal ? seededFrom : null;
  const parsed = parseColumns(columnsText);
  const rows = wholeNumber(rowCount);
  const seedValue = wholeNumber(seed);
  const ready = parsed.columns !== null && rows !== null && seedValue !== null;
  const generating = busy !== null && busy !== 'proposing';

  useRefocusAfter(busy === 'proposing', proposeButton);
  useRefocusAfter(generating, generateButton);
  useLayoutEffect(() => {
    busyChange.current?.(busy !== null);
  }, [busy]);
  useEffect(() => () => busyChange.current?.(false), []);
  useLayoutEffect(() => {
    if (!focusRequest) return;
    ({ columns: columnsInput, row_count: rowInput, seed: seedInput })[focusRequest.field].current?.focus();
  }, [focusRequest]);

  const enter = (next: Busy | null) => {
    busyNow.current = next;
    setBusy(next);
  };
  const release = () => {
    inFlight.current = false;
    enter(null);
  };
  /** Ends a generation's busy state, never a proposal's. */
  const releaseGeneration = () => {
    if (busyNow.current !== 'proposing') release();
  };
  const showFailure = (next: Failure | null) => {
    failureJob.current = next?.job ?? null;
    setFailure(next);
  };

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

  const settleProposal = async (result: Finished) => {
    if (proposalRun.current !== result.run_id) return;
    proposalRun.current = null;
    const reason = result.error ? `${sentence(result.error)} ` : '';
    if (result.status === 'ok') {
      const value = await loadProposal();
      if (!mounted.current) return;
      if (matches(value)) {
        seedFrom(value);
        setStatus('Schema proposed. Review the invented columns and assumptions, then generate.');
      } else {
        setStatus('');
        showFailure({
          title: PROPOSE_FAILED,
          message: value === undefined ? "The proposal couldn't be loaded. Select Propose schema again." : 'The reference changed while the schema was proposed. Select Propose schema again.',
        });
      }
    } else {
      setStatus('');
      showFailure({ title: PROPOSE_FAILED, message: `${reason}Enter the columns yourself, or select Propose schema to try again.` });
    }
    release();
  };

  // ---------- The generation job: its persisted status decides ----------

  const stopPolling = () => {
    if (pollTimer.current !== null) clearTimeout(pollTimer.current);
    pollTimer.current = null;
  };
  const letGo = () => {
    job.current = null;
    stopPolling();
    ++pollSeq.current;
  };
  const schedulePoll = () => {
    stopPolling();
    pollTimer.current = setTimeout(() => void handlers.current.poll(), POLL_MS);
  };

  const succeed = () => {
    if (job.current) reported.current.add(job.current.key);
    letGo();
    setCleaning(false);
    showFailure(null);
    setStatus('Sample data generated. It shows under Sources as Synthetic sample data.');
    releaseGeneration();
    generated.current?.();
  };

  const fail = (state: GenerationStatus) => {
    const key = state.generation_key;
    const seen = reported.current.has(key);
    reported.current.add(key);
    if (sentKeys.current.has(key)) request.current = null; // Trying again after a failed run is a new request with a new key.
    setCleaning(!state.retry_ready);
    if (state.retry_ready) letGo();
    else schedulePoll(); // Cleanup still runs: Retry waits for retry_ready.
    if (seen) {
      // Cleanup just finished. Update a failure still on screen; otherwise say it once in the status line.
      if (state.retry_ready && failureJob.current !== key) setStatus('The failed run is cleaned up. You can generate sample data again.');
      if (failureJob.current !== key) return;
    } else {
      releaseGeneration();
      setStatus('');
    }
    const own = sentKeys.current.has(key);
    const reason = state.error ? `${sentence(state.error.message)} ` : '';
    const next = state.retry_ready
      ? own ? 'Your columns are kept. Select Retry to generate them again.' : 'Check the columns below, then select Retry to generate them.'
      : `${own ? 'Your columns are kept. ' : ''}Retry shows here once the failed run is cleaned up.`;
    showFailure({ title: own ? GENERATE_FAILED : LAST_RUN_FAILED, message: `${reason}${next}`, retry: state.retry_ready, job: key });
  };

  /** The backend has no job with this key: nothing was registered, so nothing runs. */
  const vanished = (followed: Followed) => {
    letGo();
    setCleaning(false);
    releaseGeneration();
    setStatus('');
    const same = request.current?.generation_key === followed.key;
    showFailure({
      title: GENERATE_FAILED,
      message: same ? "The backend has no record of this request, so nothing was generated. Select Retry to send it again." : 'The backend has no record of this run. Select Generate sample data to try again.',
      retry: same,
    });
  };

  /** Run results reported for the followed job. */
  const generationFinished = (result: Finished) => {
    if (result.status === 'ok') succeed();
    else void handlers.current.poll(); // Its status says whether the cleanup is done (retry_ready).
  };

  /** A status read for the followed job: act on its state. */
  const apply = (state: GenerationStatus) => {
    const followed = job.current;
    if (!followed || followed.key !== state.generation_key) return;
    const learned = followed.runId === null;
    followed.runId = state.run_id;
    setUnreadable(false);
    if (state.state === 'succeeded') return succeed();
    if (state.state === 'failed') return fail(state);
    inFlight.current = true;
    enter(state.state === 'loading' ? 'loading' : 'generating');
    const early = learned ? finished.current.get(state.run_id) : undefined;
    if (early) return generationFinished(early);
    schedulePoll();
  };

  const poll = async () => {
    stopPolling();
    const followed = job.current;
    if (!followed) return;
    const seq = ++pollSeq.current;
    try {
      const state = await api.getSyntheticJob(buildId, followed.key);
      if (!mounted.current || job.current !== followed || seq !== pollSeq.current) return;
      apply(state);
    } catch (reason) {
      if (!mounted.current || job.current !== followed || seq !== pollSeq.current) return;
      if (unknownJob(reason)) vanished(followed);
      else if (reason instanceof ApiError && reason.code === 'build_not_found') {
        letGo();
        setCleaning(false);
        releaseGeneration();
        showFailure({ title: GENERATE_FAILED, message: reason.message });
      } else {
        setUnreadable(true);
        schedulePoll(); // Can't read it now: read it again in 2 s.
      }
    }
  };

  /** The newest earlier job, found on load or reconnect. */
  const adopt = (latest: GenerationStatus, onLoad: boolean) => {
    const key = latest.generation_key;
    if (job.current) {
      if (job.current.key === key) apply(latest);
      return;
    }
    if (inFlight.current) return; // This panel's own action is answering; it decides.
    if (ACTIVE.has(latest.state)) {
      job.current = { key, runId: null };
      showFailure(null);
      setStatus('');
      jobFound.current?.();
      apply(latest);
      return;
    }
    if (reported.current.has(key)) return;
    if (latest.state === 'succeeded') {
      // This build's view predates the source: read the build again.
      reported.current.add(key);
      generated.current?.();
      return;
    }
    if (onLoad) jobFound.current?.();
    job.current = { key, runId: null };
    apply(latest);
  };

  const recover = async (onLoad: boolean) => {
    const seq = ++jobsSeq.current;
    try {
      const jobs = await api.listSyntheticJobs(buildId);
      if (!mounted.current || seq !== jobsSeq.current) return;
      setJobsError(null);
      if (jobs[0]) adopt(jobs[0], onLoad);
    } catch (reason) {
      if (!mounted.current || seq !== jobsSeq.current) return;
      const detail = reason instanceof ApiError && reason.code !== 'invalid_response' ? sentence(reason.message) : 'Try again.';
      setJobsError(`Couldn't check for an earlier sample-data run. ${detail}`);
    } finally {
      if (mounted.current && seq === jobsSeq.current) setJobsChecked(true);
    }
  };

  /** The POST got no answer: read the job by its key instead of posting again. */
  const recoverLostPost = async (body: GenerationRequest, reason: unknown) => {
    const followed: Followed = { key: body.generation_key, runId: null };
    job.current = followed;
    enter('checking');
    try {
      const state = await api.getSyntheticJob(buildId, followed.key);
      if (!mounted.current || job.current !== followed) return;
      apply(state);
    } catch (error) {
      if (!mounted.current || job.current !== followed) return;
      letGo();
      release();
      showFailure({
        title: GENERATE_FAILED,
        message: !unknownJob(error)
          ? `${sentence(message(reason, "Couldn't start generating."))} Retry sends the same request, so it can't start a second run.`
          : reason instanceof ApiError && reason.status > 0
            ? `${sentence(reason.message)} Nothing was generated. Select Retry to send the request again.` // The backend answered with an error.
            : "The request didn't reach the backend, so nothing was generated. Select Retry to send it again.",
        retry: true,
      });
    }
  };

  const handlers = useRef({ settleProposal, generationFinished, poll, recover });
  handlers.current = { settleProposal, generationFinished, poll, recover };

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
        if (job.current?.runId === event.data.run_id) handlers.current.generationFinished(event.data);
        else void handlers.current.settleProposal(event.data);
      }
      if (event.name === 'ready') {
        // Events aren't replayed: let go of a proposal run whose end may have been missed.
        activeRuns.current.clear();
        setExternalBusy(false);
        const proposing = proposalRun.current !== null;
        if (proposing) {
          proposalRun.current = null;
          release();
          setStatus('Reconnected. The latest saved proposal shows here, if there is one.');
        }
        void loadProposal().then((value) => {
          if (proposing && mounted.current && matches(value)) seedFrom(value);
        });
        // A generation reads its persisted status instead.
        if (job.current) void handlers.current.poll();
        else void handlers.current.recover(false);
      }
    });
    void loadProposal();
    void handlers.current.recover(true);
    return () => {
      mounted.current = false;
      ++fetchSeq.current;
      ++jobsSeq.current;
      ++pollSeq.current;
      stopPolling();
      unsubscribe();
    };
    // loadProposal, seedFrom and matches read only refs and setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildId]);

  const propose = async () => {
    if (inFlight.current || locked || reference?.mode !== 'recreate') return;
    inFlight.current = true;
    enter('proposing');
    setStatus('');
    showFailure(null);
    try {
      const accepted = await api.proposeSyntheticSchema(buildId, reference.id);
      if (!mounted.current) return;
      proposalRun.current = accepted.run_id;
      const early = finished.current.get(accepted.run_id);
      if (early) void settleProposal(early);
    } catch (reason) {
      if (!mounted.current) return;
      release();
      const styleOnly = reason instanceof ApiError && reason.code === 'synthetic_schema_unavailable';
      showFailure({ title: PROPOSE_FAILED, message: styleOnly ? STYLE_ONLY : message(reason, "Couldn't propose a schema. Try again.") });
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
    if (inFlight.current || generateLocked || parsed.columns === null || rows === null || seedValue === null) return;
    const fresh = { proposal_id: proposalId, spec: { schema_version: 1 as const, row_count: rows, seed: seedValue, columns: parsed.columns as ColumnSpec[] } };
    const bound = request.current;
    const same = bound !== null && JSON.stringify({ proposal_id: bound.proposal_id, spec: bound.spec }) === JSON.stringify(fresh);
    const body: GenerationRequest = same ? bound : { generation_key: newGenerationKey(), ...fresh };
    request.current = body;
    sentKeys.current.add(body.generation_key);
    inFlight.current = true;
    enter('generating');
    setStatus('');
    showFailure(null);
    setFieldErrors({});
    try {
      const accepted = await api.generateSyntheticData(buildId, body);
      if (!mounted.current) return;
      job.current = { key: body.generation_key, runId: accepted.run_id };
      const early = finished.current.get(accepted.run_id);
      if (early) generationFinished(early);
      else schedulePoll();
    } catch (reason) {
      if (!mounted.current) return;
      if (ambiguous(reason)) {
        void recoverLostPost(body, reason);
        return;
      }
      release();
      if (!(reason instanceof ApiError)) return;
      if (reason.status === 422 && reason.code === 'invalid_generation_spec') {
        showSpecErrors(specFieldErrors(reason), sentence(reason.message));
        return;
      }
      if (reason.code === 'synthetic_request_conflict') {
        request.current = null;
        showFailure({
          title: GENERATE_FAILED,
          message: 'The request changed since its generation key was first used, so the backend refused it. A new key is ready: select Generate sample data again.',
        });
        return;
      }
      if (reason.code === 'synthetic_proposal_stale') {
        // The server no longer accepts this proposal: the columns become the user's own schema.
        request.current = null;
        setStaleProposal(body.proposal_id);
        showFailure({
          title: GENERATE_FAILED,
          message: 'The reference changed after these columns were proposed, so they now count as your own schema. Select Generate sample data to send them, or propose the schema again.',
        });
        return;
      }
      if (reason.code === 'synthetic_requires_empty_build' || reason.code === 'wrong_stage') {
        showFailure({
          title: GENERATE_FAILED,
          message: 'This dashboard already has data or has moved past Connect, so sample data would mix with it. Start a new dashboard to use sample data.',
          newDashboard: true,
        });
        return;
      }
      showFailure({ title: GENERATE_FAILED, message: reason.message });
    }
  };

  /**
   * Any edit makes a new request: the next Generate mints a new key. Edits survive every error; a failed
   * run's report stays while the columns are fixed, since its Retry sends the edited columns.
   */
  const edit = (field: Field) => {
    request.current = null;
    if (failureJob.current === null) showFailure(null);
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
          <Button ref={generateButton} type="submit" variant="primary" loading={generating} disabled={generateLocked || !ready}>
            Generate sample data
          </Button>
          <p role="status" className="flex min-h-5 min-w-0 flex-1 items-center gap-2 text-body text-text-muted">
            {(busy || cleaning) && <Spinner />}
            <span className="min-w-0">
              {busy ? BUSY[busy] : cleaning ? CLEANING : status}
              {(generating || cleaning) && unreadable && " Can't read the run's status right now; checking again."}
            </span>
          </p>
        </div>
        {jobsError && (
          <div className="flex flex-wrap items-center gap-2">
            <p role="alert" className="text-label text-danger">
              {jobsError}
            </p>
            <Button size="sm" variant="ghost" disabled={locked} onClick={() => void recover(true)}>
              Check again
            </Button>
          </div>
        )}
      </form>

      {failure && (
        <ErrorState
          title={failure.title}
          message={failure.message}
          onRetry={failure.retry ? () => void generate() : undefined}
          retryLabel="Retry"
          retryDisabled={generateLocked || !ready}
          actions={
            <>
              {failure.newDashboard && onNewDashboard && (
                <Button size="sm" variant="secondary" onClick={onNewDashboard}>
                  New dashboard
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => showFailure(null)}>
                Dismiss
              </Button>
            </>
          }
        />
      )}
    </section>
  );
}

// ---------- Labels for synthetic sources, shared by every stage ----------

/** The source-row badge: dashed like a placeholder, because every value is invented. */
export function SyntheticBadge() {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-control border border-dashed border-text-muted bg-surface px-1.5 py-0.5 text-caption font-medium text-text">
      <FlaskConical aria-hidden="true" className="size-3 shrink-0" />
      {SYNTHETIC_LABEL}
    </span>
  );
}

/** Says the view runs on invented rows, while any source is synthetic; nothing otherwise. */
export function SampleDataBanner({ sources, children }: { sources: readonly Source[]; children: ReactNode }) {
  if (!hasSyntheticSource(sources)) return null;
  return (
    <div role="note" aria-label={SYNTHETIC_LABEL} className="flex items-start gap-3 rounded-panel border border-dashed border-text-muted bg-surface px-4 py-3">
      <FlaskConical aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-text-muted" />
      <p className="min-w-0 text-body text-text-muted">
        <span className="font-semibold text-text">{SYNTHETIC_LABEL}.</span> {children}
      </p>
    </div>
  );
}

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const formatTime = (iso: string) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : dateFormat.format(date);
};
const formatBytes = (bytes: number) =>
  bytes < 1024 ? `${bytes} bytes` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

type Details = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; datasets: SyntheticDataset[] };

function Fact({ term, children, wide = false }: { term: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`flex min-w-0 flex-col gap-0.5 ${wide ? 'col-span-full' : ''}`}>
      <dt className="text-caption text-text-muted">{term}</dt>
      <dd className="min-w-0 text-body text-text">{children}</dd>
    </div>
  );
}

/** Provenance of the build's synthetic sources, read from GET synthetic-data, so it survives a reload. */
export function SyntheticDetails({ buildId, sources }: { buildId: string; sources: readonly Source[] }) {
  const headingId = useId();
  const synthetic = sources.filter((source) => source.kind === 'synthetic');
  const ids = synthetic.map((source) => source.id).join(' ');
  const [details, setDetails] = useState<Details>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!ids) return;
    let active = true;
    setDetails({ status: 'loading' });
    api.listSyntheticDatasets(buildId).then(
      (datasets) => {
        if (active) setDetails({ status: 'ready', datasets });
      },
      (reason: unknown) => {
        if (active) setDetails({ status: 'error', message: message(reason, "Couldn't load the sample data details. Try again.") });
      },
    );
    return () => {
      active = false;
    };
  }, [buildId, ids, attempt]);

  if (synthetic.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="mt-4 flex min-w-0 flex-col gap-3 border-t border-border pt-4">
      <div className="flex flex-col gap-0.5">
        <h3 id={headingId} className="text-body font-semibold text-text">
          Sample data details
        </h3>
        <p className="text-caption text-text-muted">The seeded generator invented every value; none comes from a screenshot or a real dataset.</p>
      </div>
      {details.status === 'loading' && (
        <p className="flex items-center gap-2 text-body text-text-muted">
          <Spinner />
          Loading sample data details…
        </p>
      )}
      {details.status === 'error' && (
        <ErrorState title="Couldn't load the sample data details" message={details.message} onRetry={() => setAttempt((n) => n + 1)} />
      )}
      {details.status === 'ready' &&
        synthetic.map((source) => {
          const dataset = details.datasets.find((d) => d.source_id === source.id);
          if (!dataset) {
            return (
              <p key={source.id} className="text-body text-text-muted">
                No details are recorded for {source.name} yet.
              </p>
            );
          }
          return (
            <div key={source.id} className="flex min-w-0 flex-col gap-3">
              <dl aria-label={`Provenance of ${source.name}`} className="grid grid-cols-3 gap-x-6 gap-y-2">
                <Fact term="Rows">{dataset.spec.row_count.toLocaleString()}</Fact>
                <Fact term="Seed">{dataset.spec.seed}</Fact>
                <Fact term="Columns">{dataset.spec.columns.length}</Fact>
                <Fact term="Generator">
                  <span className="font-mono text-label [overflow-wrap:anywhere]">{dataset.generator_version}</span>
                </Fact>
                <Fact term="File size">{formatBytes(dataset.bytes)}</Fact>
                <Fact term="Created">
                  <time dateTime={dataset.created_at}>{formatTime(dataset.created_at)}</time>
                </Fact>
                <Fact term="SHA-256 checksum" wide>
                  <span className="font-mono text-label break-all">{dataset.sha256}</span>
                </Fact>
              </dl>
              <div className="flex flex-col gap-1">
                <h4 className="text-caption text-text-muted">Assumptions</h4>
                {dataset.assumptions.length > 0 ? (
                  <ul aria-label={`Assumptions of ${source.name}`} className="list-disc space-y-0.5 pl-5 text-body text-text [overflow-wrap:anywhere]">
                    {dataset.assumptions.map((assumption, i) => (
                      <li key={i}>{assumption}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-body text-text">None recorded.</p>
                )}
              </div>
            </div>
          );
        })}
    </section>
  );
}
