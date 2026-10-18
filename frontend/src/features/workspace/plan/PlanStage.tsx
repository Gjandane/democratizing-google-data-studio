import { CircleCheck, FileText } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, type Build, type DocRef } from '../../../api/types';
import { EmptyState } from '../../../components/EmptyState';
import { ErrorState } from '../../../components/ErrorState';
import { focusRing } from '../../../components/focus';
import { Panel } from '../../../components/Panel';
import { LoadingState, Spinner } from '../../../components/Spinner';
import { Markdown } from '../chat/Markdown';
import type { ProgressLine } from '../chat/useBuildStream';

/** Doc headings: the shared Markdown component leaves them unstyled. */
const HEADINGS =
  '[&_h1]:text-heading [&_h1]:font-semibold [&_h2]:text-title [&_h2]:font-semibold [&_h3]:font-semibold [&_:is(h1,h2,h3)]:mb-1 [&_:is(h1,h2,h3):not(:first-child)]:mt-4';

type DocLoad = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; text: string };

/** The open doc: fetched from `GET /docs/{path}` when picked, read-only. */
function DocViewer({ buildId, doc, docs }: { buildId: string; doc: DocRef; docs: DocRef[] }) {
  const [load, setLoad] = useState<DocLoad>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const path = doc.path;

  useEffect(() => {
    let active = true;
    // A refetch after docs.updated keeps the text on screen until the new one arrives.
    setLoad((current) => (current.status === 'ready' ? current : { status: 'loading' }));
    api.getDoc(buildId, path).then(
      (text) => {
        if (active) setLoad({ status: 'ready', text });
      },
      (error: unknown) => {
        if (active) setLoad({ status: 'error', message: error instanceof ApiError ? error.message : "Couldn't load this doc. Try again." });
      },
    );
    return () => {
      active = false;
    };
  }, [buildId, path, attempt, docs]);

  if (load.status === 'loading') return <LoadingState>Loading {path}…</LoadingState>;
  if (load.status === 'error') {
    return (
      <div className="p-4">
        <ErrorState title={`Couldn't open ${path}`} message={load.message} onRetry={() => setAttempt((n) => n + 1)} />
      </div>
    );
  }
  return <Markdown className={`px-4 py-3 text-body text-text ${HEADINGS}`}>{load.text}</Markdown>;
}

/** The Plan stage area: the planner's status lines while it works, then the build docs. */
export function PlanStage({ build, progress: lines, planning }: { build: Build; progress: ProgressLine[]; planning: boolean }) {
  const [selected, setSelected] = useState<string | null>(null);
  const docs = build.docs;
  const progress = lines.filter((line) => line.node === 'plan');
  const hasDocs = docs.length > 0;
  const doc = docs.find((d) => d.path === selected) ?? null;

  // A doc that left the list must not reopen on its own if it comes back later.
  useEffect(() => {
    if (selected !== null && !doc) setSelected(null);
  }, [selected, doc]);

  return (
    <div className="mt-6 flex flex-col gap-4">
      {(planning || !hasDocs || progress.length > 0) && (
        <Panel title="Progress" bodyClassName="px-4 py-3">
          {progress.length === 0 ? (
            <LoadingState className="py-2">Waiting for the planner…</LoadingState>
          ) : (
            <ol aria-label="Planner progress" aria-live="polite" className="flex flex-col gap-1.5">
              {progress.map((line, i) => {
                const last = i === progress.length - 1;
                const running = last && planning;
                return (
                  <li key={line.key} className="flex items-center gap-2 text-body text-text">
                    {running ? (
                      <Spinner size="sm" className="text-primary" />
                    ) : (
                      <CircleCheck aria-hidden="true" className="size-3.5 shrink-0 text-success" />
                    )}
                    <span className="min-w-0 [overflow-wrap:anywhere]">{line.text}</span>
                  </li>
                );
              })}
            </ol>
          )}
        </Panel>
      )}

      <Panel title="Build docs">
        {!hasDocs ? (
          <EmptyState
            icon={<FileText />}
            title="No docs yet"
            description="The planner's docs show up here as soon as they are written."
            headingLevel={3}
            className="py-8"
          />
        ) : (
          <div className="grid grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
            <ul aria-label="Build docs" className="flex flex-col gap-0.5 border-r border-border p-2">
              {docs.map((d) => (
                <li key={d.path}>
                  <button
                    type="button"
                    aria-current={d.path === selected ? 'true' : undefined}
                    onClick={() => setSelected(d.path)}
                    className={`flex w-full flex-col rounded-control px-2 py-1.5 text-left hover:bg-surface-muted aria-[current=true]:bg-primary-soft ${focusRing}`}
                  >
                    <span className="truncate text-body font-medium text-text" title={d.title}>
                      {d.title}
                    </span>
                    <span className="truncate font-mono text-caption text-text-muted" title={d.path}>
                      {d.path}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <section aria-label={doc ? doc.title : 'Doc viewer'} className="min-h-40 min-w-0">
              {doc ? (
                <DocViewer key={doc.path} buildId={build.id} doc={doc} docs={docs} />
              ) : (
                <p className="px-4 py-6 text-body text-text-muted">Select a doc to read it.</p>
              )}
            </section>
          </div>
        )}
      </Panel>
    </div>
  );
}
