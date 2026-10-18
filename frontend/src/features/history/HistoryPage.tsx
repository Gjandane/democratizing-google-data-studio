import { ExternalLink, LayoutDashboard, Plus } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { ApiError, type BuildSummary } from '../../api/types';
import { Button } from '../../components/Button';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { focusRing } from '../../components/focus';
import { Panel } from '../../components/Panel';
import { LoadingState } from '../../components/Spinner';
import { NewBuildDialog } from './NewBuildDialog';

type Load =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; builds: BuildSummary[] };

const sentence = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : dateFormat.format(date);
}

/** The API already sorts; sorting again keeps the page right whatever the source. */
const newestFirst = (builds: BuildSummary[]) => [...builds].sort((a, b) => b.updated_at.localeCompare(a.updated_at));

const textLink = `rounded-sm ${focusRing}`;

function BuildRow({ build }: { build: BuildSummary }) {
  const done = build.stage === 'done';
  return (
    <li className="flex items-center gap-4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <h2 className="text-body font-medium">
          {/* Truncate on the link, not the heading: overflow on the heading would clip the focus ring. */}
          <Link
            to={`/builds/${encodeURIComponent(build.id)}`}
            className={`inline-block max-w-full truncate align-bottom text-text hover:text-primary hover:underline ${textLink}`}
          >
            {build.title}
          </Link>
        </h2>
        <p className="mt-0.5 text-caption text-text-muted">
          {sentence(build.archetype)} dashboard, updated <time dateTime={build.updated_at}>{formatTime(build.updated_at)}</time>
        </p>
      </div>
      <span
        className={`shrink-0 rounded-control px-2 py-0.5 text-caption font-medium ${
          done ? 'bg-success-soft text-success' : 'bg-surface-muted text-text-muted'
        }`}
      >
        {sentence(build.stage)}
      </span>
      <div className="w-40 shrink-0 text-right text-label">
        {build.report_url ? (
          <a
            href={build.report_url}
            target="_blank"
            rel="noopener noreferrer"
            className={`inline-flex items-center gap-1 font-medium text-primary hover:text-primary-hover hover:underline ${textLink}`}
          >
            Open in Data Studio
            <ExternalLink aria-hidden="true" className="size-3.5" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : (
          <span className="text-text-muted">Not published yet</span>
        )}
      </div>
    </li>
  );
}

export function HistoryPage() {
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const retried = useRef(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let active = true;
    setLoad({ status: 'loading' });
    api.listBuilds().then(
      (builds) => {
        if (active) setLoad({ status: 'ready', builds: newestFirst(builds) });
      },
      (error: unknown) => {
        if (!active) return;
        const message = error instanceof ApiError ? error.message : "Couldn't load your dashboards. Try again.";
        setLoad({ status: 'error', message });
      },
    );
    return () => {
      active = false;
    };
  }, [attempt]);

  // "Try again" unmounts while loading; put keyboard focus back at the top of the page after.
  // Layout effect: focus lands in the same commit as the content, before anything can observe it.
  useLayoutEffect(() => {
    if (!retried.current || load.status === 'loading') return;
    retried.current = false;
    heading.current?.focus();
  }, [load.status]);

  const retry = () => {
    retried.current = true;
    setAttempt((n) => n + 1);
  };

  return (
    <main className="mx-auto w-full max-w-(--layout-page) px-6 py-8">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 ref={heading} tabIndex={-1} className="text-display font-semibold text-text outline-none">
            Dashboards
          </h1>
          <p className="mt-1 text-body text-text-muted">Every build you started, most recently updated first.</p>
        </div>
        <Button variant="primary" icon={<Plus aria-hidden="true" />} onClick={() => setCreating(true)}>
          New build
        </Button>
      </header>
      {/* Mounted only while open, so each new build starts from a blank form. */}
      {creating && <NewBuildDialog open onClose={() => setCreating(false)} />}

      {load.status === 'loading' && (
        <Panel>
          <LoadingState>Loading dashboards…</LoadingState>
        </Panel>
      )}

      {load.status === 'error' && <ErrorState title="Couldn't load your dashboards" message={load.message} onRetry={retry} />}

      {load.status === 'ready' && load.builds.length === 0 && (
        <EmptyState
          framed
          icon={<LayoutDashboard />}
          title="No dashboards yet"
          description="Builds you start show up here, with a link once they're published."
          action={
            <Button variant="primary" onClick={() => setCreating(true)}>
              Start a build
            </Button>
          }
        />
      )}

      {load.status === 'ready' && load.builds.length > 0 && (
        <ul aria-label="Dashboards" className="divide-y divide-border rounded-panel border border-border bg-surface">
          {load.builds.map((build) => (
            <BuildRow key={build.id} build={build} />
          ))}
        </ul>
      )}
    </main>
  );
}
