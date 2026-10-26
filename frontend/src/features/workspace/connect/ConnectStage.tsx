import { Database, Download, FileUp, Plus, Upload } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { api } from '../../../api/client';
import { ApiError, type Build, type ReferenceSet, type Source, type SourceKind } from '../../../api/types';
import { Button } from '../../../components/Button';
import { EmptyState } from '../../../components/EmptyState';
import { ErrorState } from '../../../components/ErrorState';
import { Input, TextArea } from '../../../components/Input';
import { focusRing } from '../../../components/focus';
import { Spinner } from '../../../components/Spinner';
import { Table, type Column as TableColumn } from '../../../components/Table';
import { ARCHETYPE_INFO, NewBuildDialog } from '../../history/NewBuildDialog';
import type { StretchRuns } from '../../activity/useBuildStream';
import { ResearchPanel } from './ResearchPanel';
import { hasSyntheticSource, SYNTHETIC_LABEL, SyntheticBadge, SyntheticDataPanel, SyntheticDetails } from './SyntheticDataPanel';
import { ReferencePanel } from '../ReferencePanel';
import { useReviewLock } from '../briefs/reviewLock';

type UriKind = 'gcs' | 'bigquery';
type DataChoice = 'upload' | 'generate';

const DATA_CHOICES: Record<DataChoice, { label: string; description: string }> = {
  upload: { label: 'Upload/connect data', description: 'CSV files, a GCS path or a BigQuery table.' },
  generate: { label: 'Generate sample data', description: 'Invented rows from columns you review. No data needed.' },
};

const choiceCard =
  'flex h-full cursor-pointer flex-col gap-0.5 rounded-panel border border-border-strong bg-surface p-3 transition-[border-color,background-color] hover:border-text-muted peer-checked:border-primary peer-checked:bg-primary-soft peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus peer-disabled:cursor-not-allowed peer-disabled:opacity-50 peer-disabled:hover:border-border-strong';

type Busy = { kind: 'upload'; count: number } | { kind: 'uri' } | { kind: 'start' } | null;
interface Failure {
  title: string;
  message: string;
  retry?: () => void;
}

const URI_KINDS: Record<UriKind, { label: string; placeholder: string; field: string }> = {
  gcs: { label: 'Google Cloud Storage', placeholder: 'gs://bucket/path/file.csv', field: 'GCS path' },
  bigquery: { label: 'BigQuery', placeholder: 'project.dataset.table', field: 'BigQuery table' },
};

const KIND_LABELS: Record<SourceKind, string> = {
  upload: 'CSV upload',
  gcs: 'GCS',
  bigquery: 'BigQuery',
  research: 'Research',
  synthetic: SYNTHETIC_LABEL,
};

const sourceColumns = (buildId: string): TableColumn<Source>[] => [
  {
    id: 'name',
    header: 'Name',
    className: 'align-top',
    cell: (s) => (
      <span className="flex flex-col items-start gap-1">
        <span className="font-medium">{s.name}</span>
        {s.kind === 'synthetic' && (
          <a
            href={api.syntheticCsvUrl(buildId, s.id)}
            download="synthetic-sample.csv"
            className={`inline-flex items-center gap-1 whitespace-nowrap rounded-sm text-label font-medium text-primary hover:text-primary-hover hover:underline ${focusRing}`}
          >
            <Download aria-hidden="true" className="size-3.5" />
            Download CSV
          </a>
        )}
      </span>
    ),
  },
  { id: 'kind', header: 'Kind', cell: (s) => (s.kind === 'synthetic' ? <SyntheticBadge /> : KIND_LABELS[s.kind]), className: 'align-top whitespace-nowrap' },
  { id: 'bq_table', header: 'BigQuery table', cell: (s) => <span className="break-all text-caption">{s.bq_table}</span>, mono: true, className: 'align-top' },
  { id: 'rows', header: 'Rows', cell: (s) => s.row_count.toLocaleString(), align: 'right', className: 'align-top' },
  {
    id: 'columns',
    header: 'Columns',
    className: 'align-top',
    cell: (s) => (
      <ul aria-label={`Columns of ${s.name}`} className="flex flex-wrap gap-1">
        {s.columns.map((c) => (
          <li key={c.name} className="inline-flex items-baseline gap-1 rounded-control bg-surface-muted px-1.5 py-0.5">
            <span className="font-mono text-caption text-text">{c.name}</span>
            <span className="text-caption text-text-muted">{c.type}</span>
          </li>
        ))}
      </ul>
    ),
  },
];

const message = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

/** Most characters of "About this data" a context draft accepts (api.md 2.0, POST context). */
export const MAX_NOTES = 4000;

interface ConnectStageProps {
  onReferenceReadyChange?: (ready: boolean) => void;
  build: Build;
  onBuildChange: (build: Build) => void;
  /** Run state of the stretch actions, from the build's event stream. */
  stretchRuns?: StretchRuns;
  /** Generated sample data changed the build's sources: read feasibility again. */
  onAssessmentInvalidated?: () => void;
}

/**
 * The Connect stage: add CSV files, a GCS path or a BigQuery table, or (with no source yet) generate
 * invented sample data, then draft the context.
 */
const noRuns: StretchRuns = {};

export function ConnectStage({ build, onBuildChange, stretchRuns = noRuns, onReferenceReadyChange, onAssessmentInvalidated }: ConnectStageProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const chooseButton = useRef<HTMLButtonElement>(null);
  const uriInput = useRef<HTMLInputElement>(null);
  const lastFiles = useRef<File[]>([]);
  // Latest build and busy flag for async callbacks and retries made in an earlier render.
  const latest = useRef(build);
  latest.current = build;
  const busyRef = useRef(false);
  const uriId = useId();
  const [busy, setBusy] = useState<Busy>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uriKind, setUriKind] = useState<UriKind>('gcs');
  const [uri, setUri] = useState('');
  const [uriError, setUriError] = useState<string | null>(null);
  const [choice, setChoice] = useState<DataChoice>('upload');
  const [newDashboard, setNewDashboard] = useState(false);
  const [reference, setReference] = useState<ReferenceSet | null | undefined>(undefined);
  const [sampleBusy, setSampleBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [notes, setNotes] = useState(build.notes ?? '');
  const startButton = useRef<HTMLButtonElement>(null);
  const notesOver = notes.length > MAX_NOTES;
  const notesRef = useRef(notes);
  notesRef.current = notes;

  // A brief review waits (WorkspaceShell's lock): adding data and drafting the context wait with it.
  const reviewLock = useReviewLock();
  const reviewLocked = useRef(false);
  reviewLocked.current = reviewLock !== null;
  const isBusy = busy !== null || reviewLock !== null;
  const hasSources = build.sources.length > 0;
  const generating = !hasSources && choice === 'generate';
  const realSources = hasSources && !hasSyntheticSource(build.sources);
  const hadSources = useRef(hasSources);

  // Generated sample data replaces the panel with the Sources table: say so, and keep keyboard focus.
  useLayoutEffect(() => {
    if (!hadSources.current && hasSources && build.sources.some((s) => s.kind === 'synthetic')) {
      setNotice('Synthetic sample data added. Review it under Sources, then draft the context.');
      refocus(startButton.current);
    }
    hadSources.current = hasSources;
  }, [hasSources, build.sources]);

  // A drop that misses the zone would open the file in the tab: ignore drops anywhere else.
  useEffect(() => {
    const block = (event: globalThis.DragEvent) => event.preventDefault();
    window.addEventListener('dragover', block);
    window.addEventListener('drop', block);
    return () => {
      window.removeEventListener('dragover', block);
      window.removeEventListener('drop', block);
    };
  }, []);

  const begin = (next: NonNullable<Busy>) => {
    busyRef.current = true;
    setBusy(next);
    setFailure(null);
  };
  const finish = () => {
    busyRef.current = false;
    setBusy(null);
  };
  const addToBuild = (sources: Source[]) => {
    const current = latest.current;
    const next = { ...current, sources: [...current.sources, ...sources] };
    latest.current = next;
    onBuildChange(next);
  };
  /** Disabling the focused control drops focus to the body; put it back. */
  const refocus = (target: HTMLElement | null) => {
    if (document.activeElement === document.body || document.activeElement === null) target?.focus();
  };

  const upload = async (files: File[]) => {
    if (files.length === 0 || busyRef.current || reviewLocked.current) return;
    lastFiles.current = files;
    begin({ kind: 'upload', count: files.length });
    try {
      const { sources } = await api.uploadSources(latest.current.id, files);
      addToBuild(sources);
    } catch (e) {
      setFailure({
        title: "Couldn't upload the files",
        message: message(e, "Couldn't add the source. Try again."),
        // A 422 or 413 fails the same way again: the user has to pick other files.
        retry: e instanceof ApiError && (e.status === 422 || e.status === 413) ? undefined : () => void upload(lastFiles.current),
      });
    } finally {
      finish();
      requestAnimationFrame(() => refocus(chooseButton.current));
    }
  };

  const onDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    setDragging(false);
    void upload(Array.from(event.dataTransfer.files));
  };

  const addUri = async (event: FormEvent) => {
    event.preventDefault();
    const value = uri.trim();
    if (!value || busyRef.current || reviewLocked.current) return;
    begin({ kind: 'uri' });
    setUriError(null);
    try {
      const source = await api.addSource(latest.current.id, { kind: uriKind, uri: value });
      addToBuild([source]);
      setUri('');
    } catch (e) {
      setUriError(message(e, "Couldn't add the source. Try again."));
    } finally {
      finish();
      requestAnimationFrame(() => refocus(uriInput.current));
    }
  };

  /**
   * Generation succeeded: read the build (its sources and docs) in case build.updated was missed, and
   * feasibility, which the new source may change. Nothing is decided or started for the user.
   */
  const refreshBuild = async () => {
    onAssessmentInvalidated?.();
    try {
      onBuildChange(await api.getBuild(latest.current.id));
    } catch {
      // The stream's build.updated or the next reconnect brings the new source.
    }
  };

  const draftContext = async () => {
    if (latest.current.sources.length === 0 || busyRef.current || reviewLocked.current || notesRef.current.length > MAX_NOTES) return;
    const id = latest.current.id;
    const text = notesRef.current;
    begin({ kind: 'start' });
    try {
      // Empty notes clear saved ones; with none saved, nothing is sent.
      await (text === '' && !latest.current.notes ? api.draftContext(id) : api.draftContext(id, text));
    } catch (e) {
      finish();
      setFailure({
        title: "Couldn't draft the context",
        message: message(e, "Couldn't draft the context. Try again."),
        retry: () => void draftContext(),
      });
      return;
    }
    // The 202 already moved the build to context: never draft it twice, even if this read fails.
    try {
      onBuildChange(await api.getBuild(id));
    } catch {
      onBuildChange({ ...latest.current, stage: 'context' });
    }
  };

  return (
    <div className="mt-6 flex flex-col gap-6">
      <p className="flex flex-wrap items-center gap-2 text-body text-text-muted">
        <span>
          <span className="font-medium text-text">{ARCHETYPE_INFO[build.archetype].label}</span> dashboard. {ARCHETYPE_INFO[build.archetype].description}
        </span>
        <span className="rounded-control bg-surface-muted px-2 py-0.5 text-caption font-medium text-text-muted">
          {build.mode === 'data' ? 'Data mode' : 'Research mode'}
        </span>
      </p>

      {!hasSources && (
        <fieldset disabled={isBusy || sampleBusy} className="flex flex-col gap-2">
          <legend className="mb-2 text-title font-semibold text-text">Add data</legend>
          <div className="grid grid-cols-2 gap-2">
            {(Object.keys(DATA_CHOICES) as DataChoice[]).map((value) => (
              <label key={value} className="relative block">
                <input
                  type="radio"
                  name="data-choice"
                  value={value}
                  checked={choice === value}
                  onChange={() => setChoice(value)}
                  className="peer sr-only"
                />
                <span className={choiceCard}>
                  <span className="text-body font-medium text-text">{DATA_CHOICES[value].label}</span>
                  <span className="text-caption text-text-muted">{DATA_CHOICES[value].description}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {/* Mounted (hidden) whenever there is no source, so it recovers an earlier job and keeps edits across switching. */}
      {!hasSources && (
        <div hidden={!generating} className="min-w-0">
          <SyntheticDataPanel
            buildId={build.id}
            reference={reference}
            disabled={isBusy}
            onBusyChange={setSampleBusy}
            onGenerated={() => void refreshBuild()}
            onJobFound={() => setChoice('generate')}
            onNewDashboard={() => setNewDashboard(true)}
          />
        </div>
      )}

      <section
        hidden={generating}
        aria-label="Upload CSV files"
        onDragOver={(e) => {
          e.preventDefault();
          if (!isBusy) setDragging(true);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={onDrop}
        className={`flex flex-col items-center gap-3 rounded-panel border border-dashed px-6 py-8 text-center transition-colors ${
          dragging ? 'border-primary bg-primary-soft' : 'border-border-strong bg-surface'
        }`}
      >
        <span aria-hidden="true" className="flex size-10 items-center justify-center rounded-full bg-surface-muted text-text-muted">
          <FileUp className="size-5" />
        </span>
        <div>
          <h3 className="text-title font-semibold text-text">Drop CSV files here</h3>
          <p className="mt-0.5 text-body text-text-muted">Drop one or more files, or choose them from your computer.</p>
        </div>
        <input
          ref={fileInput}
          type="file"
          accept=".csv,text/csv"
          multiple
          tabIndex={-1}
          aria-label="CSV files"
          className="sr-only"
          disabled={isBusy}
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = '';
            void upload(files);
          }}
        />
        <Button ref={chooseButton} variant="secondary" icon={<Upload aria-hidden="true" />} disabled={isBusy} onClick={() => fileInput.current?.click()}>
          Choose CSV files
        </Button>
        <div aria-live="polite" className="flex h-6 items-center text-body text-text-muted">
          {busy?.kind === 'upload' && (
            <span className="inline-flex items-center gap-2">
              <Spinner />
              Uploading {busy.count} {busy.count === 1 ? 'file' : 'files'}…
            </span>
          )}
        </div>
      </section>

      <form hidden={generating} onSubmit={(e) => void addUri(e)} className="flex flex-col gap-3 rounded-panel border border-border bg-surface p-4">
        <h3 className="text-title font-semibold text-text">Or add a table from Google Cloud</h3>
        <div role="radiogroup" aria-label="Source type" className="inline-flex w-fit rounded-control border border-border-strong p-0.5">
          {(Object.keys(URI_KINDS) as UriKind[]).map((kind) => (
            <label key={kind} className="relative">
              <input
                type="radio"
                name="uri-kind"
                value={kind}
                checked={uriKind === kind}
                disabled={isBusy}
                onChange={() => {
                  setUriKind(kind);
                  setUriError(null);
                }}
                className="peer sr-only"
              />
              <span className="flex h-7 cursor-pointer items-center rounded-control px-3 text-label font-medium text-text-muted transition-colors hover:text-text peer-checked:bg-primary peer-checked:text-on-primary peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus peer-disabled:cursor-not-allowed peer-disabled:opacity-50">
                {URI_KINDS[kind].label}
              </span>
            </label>
          ))}
        </div>
        <div className="flex items-start gap-2">
          <Input
            id={uriId}
            label={URI_KINDS[uriKind].field}
            hideLabel
            className="flex-1"
            placeholder={URI_KINDS[uriKind].placeholder}
            value={uri}
            ref={uriInput}
            error={uriError}
            readOnly={isBusy}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => {
              setUri(e.target.value);
              setUriError(null);
            }}
          />
          <Button type="submit" variant="secondary" loading={busy?.kind === 'uri'} disabled={isBusy || uri.trim() === ''}>
            Add source
          </Button>
        </div>
      </form>

      <ReferencePanel
        buildId={build.id}
        version={build.current_version}
        disabled={isBusy || sampleBusy}
        onReadyChange={onReferenceReadyChange}
        onSavedChange={setReference}
      />
      {build.mode === 'research' && <ResearchPanel buildId={build.id} stretchRuns={stretchRuns} />}

      {failure && (
        <ErrorState
          title={failure.title}
          message={failure.message}
          onRetry={failure.retry && !isBusy ? failure.retry : undefined}
          actions={
            <Button size="sm" variant="ghost" onClick={() => setFailure(null)}>
              Dismiss
            </Button>
          }
        />
      )}

      <section aria-label="Sources">
        {hasSources ? (
          <div className="rounded-panel border border-border bg-surface p-4">
            <Table columns={sourceColumns(build.id)} rows={build.sources} rowKey={(s) => s.id} caption="Sources" showCaption />
            <SyntheticDetails buildId={build.id} sources={build.sources} />
            {realSources && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-4">
                <p className="min-w-0 flex-1 text-body text-text-muted">
                  Want invented sample data instead? It can't be mixed with these sources, so it needs a new dashboard.
                </p>
                <Button size="sm" variant="secondary" icon={<Plus aria-hidden="true" />} disabled={busy !== null} onClick={() => setNewDashboard(true)}>
                  New dashboard
                </Button>
              </div>
            )}
          </div>
        ) : (
          <EmptyState
            framed
            icon={<Database />}
            title="No sources yet"
            description={
              generating
                ? 'Generated sample data shows up here as Synthetic sample data.'
                : 'Drop CSV files above or add a table from Google Cloud. Their columns show up here.'
            }
            headingLevel={3}
          />
        )}
      </section>

      <section aria-labelledby={`${uriId}-notes`} className="flex flex-col gap-2 rounded-panel border border-border bg-surface p-4">
        <div>
          <h3 id={`${uriId}-notes`} className="text-title font-semibold text-text">About this data</h3>
          <p className="mt-0.5 text-body text-text-muted">What the columns can't say: what a value means, what to leave out, who reads the dashboard. The context draft uses it.</p>
        </div>
        <TextArea
          label="Notes about this data"
          hideLabel
          rows={4}
          value={notes}
          readOnly={isBusy}
          placeholder="Revenue is already net of discounts. The sales director reviews it monthly."
          hint={`${notes.length.toLocaleString('en-US')} / ${MAX_NOTES.toLocaleString('en-US')} characters`}
          error={
            notesOver
              ? `${notes.length.toLocaleString('en-US')} / ${MAX_NOTES.toLocaleString('en-US')} characters. Remove ${(notes.length - MAX_NOTES).toLocaleString('en-US')} to draft the context.`
              : null
          }
          onChange={(e) => setNotes(e.target.value)}
        />
      </section>

      <div className="flex items-center justify-end gap-3 border-t border-border pt-4">
        <p role="status" className="sr-only">
          {notice}
        </p>
        {reviewLock && <p className="text-body text-text-muted">{reviewLock}</p>}
        {!reviewLock && !hasSources && <p className="text-body text-text-muted">Add at least one source to start.</p>}
        {hasSources && notesOver && <p className="text-body text-text-muted">Shorten the notes to 4,000 characters to start.</p>}
        <Button
          ref={startButton}
          variant="primary"
          loading={busy?.kind === 'start'}
          disabled={!hasSources || isBusy || notesOver}
          onClick={() => void draftContext()}
        >
          Draft context
        </Button>
      </div>
      {newDashboard && <NewBuildDialog open onClose={() => setNewDashboard(false)} />}
    </div>
  );
}
