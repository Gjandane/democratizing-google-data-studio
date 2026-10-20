import { Sparkles } from 'lucide-react';
import { useLayoutEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, type Build, type Message, type SourceKind } from '../../../api/types';
import { Button } from '../../../components/Button';
import { ErrorState } from '../../../components/ErrorState';
import { Panel } from '../../../components/Panel';
import { LoadingState } from '../../../components/Spinner';
import { ARCHETYPE_INFO } from '../../history/NewBuildDialog';
import { Markdown } from './Markdown';
import { ReferencePanel } from '../ReferencePanel';
import type { RunErrors } from './useBuildStream';

const KIND_LABELS: Record<SourceKind, string> = {
  upload: 'CSV upload',
  gcs: 'GCS',
  bigquery: 'BigQuery',
  research: 'Research',
  synthetic: 'Synthetic sample data',
};

const MODE_LABELS = { data: 'Data mode', research: 'Research mode' } as const;

interface Answer {
  id: string;
  question: string | null;
  answer: string;
}

/** Each user message with the closest assistant message before it (the question). */
function answersOf(messages: Message[]): Answer[] {
  const answers: Answer[] = [];
  let question: string | null = null;
  for (const m of messages) {
    if (m.role === 'assistant') question = m.text;
    else if (m.role === 'user') answers.push({ id: m.id, question, answer: m.text });
  }
  return answers;
}

/** How long a posted plan may wait for its `run.started` before the retry comes back. */
export const AWAIT_RUN_MS = 30_000;

const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;

/** The Interview stage area: sources, archetype, answers so far, and "Generate plan". */
export function InterviewStage({
  build,
  messages,
  loadError,
  runErrors = {},
  referencesReady = true,
  onReferenceReadyChange,
}: {
  build: Build;
  referencesReady?: boolean;
  onReferenceReadyChange?: (ready: boolean) => void;
  messages: Message[] | null;
  loadError?: string | null;
  /** A failed plan or spec run lands the user back here: say why. */
  runErrors?: RunErrors;
}) {
  const [planning, setPlanning] = useState(false);
  // The POST went through and the shown run error waits for the next plan run to clear it.
  const [awaitingRun, setAwaitingRun] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const info = ARCHETYPE_INFO[build.archetype];

  // Blocks a second POST in the same frame and stays set until the run error clears.
  const inFlight = useRef(false);
  const hasRunError = Boolean(runErrors.plan || runErrors.spec);
  const busy = planning || awaitingRun;

  // The next `run.started` of `plan` clears the run errors; leaving Interview unmounts this stage.
  // A run missed while the stream was down never clears them: give the retry back after a while.
  useLayoutEffect(() => {
    if (!awaitingRun) return;
    const release = () => {
      inFlight.current = false;
      setAwaitingRun(false);
    };
    if (!hasRunError) return release();
    const timer = setTimeout(release, AWAIT_RUN_MS);
    return () => clearTimeout(timer);
  }, [awaitingRun, hasRunError]);

  const generate = async () => {
    if (inFlight.current || !referencesReady) return;
    inFlight.current = true;
    setPlanning(true);
    setPlanError(null);
    try {
      await api.generatePlan(build.id);
      // The stage change arrives on the event stream.
      setAwaitingRun(true);
    } catch (error) {
      inFlight.current = false;
      setPlanError(error instanceof ApiError ? error.message : "Couldn't start the plan. Try again.");
    } finally {
      setPlanning(false);
    }
  };

  const answers = messages ? answersOf(messages) : [];

  return (
    <div className="mt-6 flex flex-col gap-4">
      <ReferencePanel buildId={build.id} version={build.current_version} disabled={busy} onReadyChange={onReferenceReadyChange} />
      <Panel title="Sources">
        {build.sources.length === 0 ? (
          <p className="px-4 py-3 text-body text-text-muted">No sources added.</p>
        ) : (
          <ul className="divide-y divide-border">
            {build.sources.map((s) => (
              <li key={s.id} className="flex items-baseline gap-3 px-4 py-2 text-body">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-text" title={s.name}>
                    {s.name}
                  </span>
                </span>
                <span className="shrink-0 text-text-muted">{KIND_LABELS[s.kind]}</span>
                <span className="shrink-0 text-text-muted">{plural(s.row_count, 'row')}</span>
                <span className="shrink-0 text-text-muted">{plural(s.columns.length, 'column')}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Archetype" bodyClassName="px-4 py-3">
        <p className="text-body font-medium text-text">{info.label}</p>
        <p className="text-body text-text-muted">{info.description}</p>
        <p className="mt-1 text-caption text-text-muted">{MODE_LABELS[build.mode]}</p>
      </Panel>

      <Panel title="Questions answered so far" bodyClassName="px-4 py-3">
        {messages === null && loadError ? (
          <p className="text-body text-text-muted">Couldn't load the answers. Select Try again in the chat.</p>
        ) : messages === null ? (
          <LoadingState>Loading answers…</LoadingState>
        ) : answers.length === 0 ? (
          <p className="text-body text-text-muted">No answers yet. Answer the first question in the chat.</p>
        ) : (
          <ol className="flex list-decimal flex-col gap-3 pl-5 marker:text-text-muted">
            {answers.map((a) => (
              <li key={a.id} className="min-w-0 pl-1">
                {a.question && <Markdown className="text-label text-text-muted">{a.question}</Markdown>}
                <p className="mt-0.5 whitespace-pre-wrap text-body text-text [overflow-wrap:anywhere]">{a.answer}</p>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <fieldset disabled={!referencesReady} className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant={build.ready_for_plan ? 'primary' : 'secondary'}
            data-ready={String(build.ready_for_plan)}
            icon={<Sparkles aria-hidden="true" />}
            loading={busy}
            disabled={!referencesReady}
            onClick={() => void generate()}
          >
            Generate plan
          </Button>
          <p className="text-body text-text-muted">
            {build.ready_for_plan
              ? 'The assistant has enough to plan.'
              : 'You can plan now, but answering a few more questions helps.'}
          </p>
        </div>
        {planError && <ErrorState title="Couldn't start the plan" message={planError} onRetry={() => void generate()} retryLoading={busy} />}
        {!planError && runErrors.plan && (
          <ErrorState title="The plan didn't finish" message={runErrors.plan} onRetry={() => void generate()} retryLoading={busy} retryLabel="Generate plan again" />
        )}
        {!planError && runErrors.spec && (
          <ErrorState title="The spec didn't finish" message={runErrors.spec} onRetry={() => void generate()} retryLoading={busy} retryLabel="Generate plan again" />
        )}
      </fieldset>
    </div>
  );
}
