import { CircleCheck, ExternalLink, Plus } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { ApiError, type Build, type Version } from '../../api/types';
import { Button, buttonClass } from '../../components/Button';
import { focusRing } from '../../components/focus';
import { Panel } from '../../components/Panel';

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : dateFormat.format(date);
}

const STATUS_LABEL: Record<Version['status'], string> = {
  draft: 'Draft',
  building: 'Building',
  published: 'Published',
  failed: 'Failed',
};

const STATUS_TONE: Record<Version['status'], string> = {
  draft: 'bg-surface-muted text-text-muted',
  building: 'bg-surface-muted text-text-muted',
  published: 'bg-success-soft text-success',
  failed: 'bg-danger-soft text-text',
};

function ReportLink({ href, className }: { href: string; className: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      <ExternalLink aria-hidden="true" className="size-3.5" />
      Open in Data Studio
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

interface DoneStageProps {
  build: Build;
  /** Ops that failed in the run just finished in this session (a partial build); 0 when none is known. */
  failedOps?: number;
  onBuildChange: (build: Build) => void;
  /** Called once a new version exists, so the workspace leaves any build result it kept open. */
  onNewVersion?: () => void;
}

/** The Done stage: the published dashboard's link, every version with its link, and "New version". */
export function DoneStage({ build, failedOps = 0, onBuildChange, onNewVersion }: DoneStageProps) {
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const versions = [...build.versions].sort((a, b) => b.n - a.n);
  const current = build.versions.find((v) => v.n === build.current_version);
  const link = current?.report_url ?? build.report_url;

  const newVersion = async () => {
    setCreating(true);
    setError(null);
    try {
      const next = await api.createVersion(build.id);
      if (!mounted.current) return;
      onNewVersion?.();
      onBuildChange(next);
    } catch (e) {
      if (mounted.current) setError(e instanceof ApiError ? e.message : "Couldn't start a new version. Try again.");
    } finally {
      if (mounted.current) setCreating(false);
    }
  };

  return (
    <div className="mt-6 space-y-4">
      <section
        aria-label="Published dashboard"
        className={`flex items-start gap-3 rounded-panel border px-4 py-3 ${link ? 'border-success bg-success-soft' : 'border-border bg-surface-muted'}`}
      >
        <CircleCheck aria-hidden="true" className={`mt-0.5 size-5 shrink-0 ${link ? 'text-success' : 'text-text-muted'}`} />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-body font-semibold text-text">{link ? 'Your dashboard is in Data Studio.' : 'No link yet.'}</p>
          {failedOps > 0 && (
            <p className="text-body font-medium text-danger">
              {failedOps} {failedOps === 1 ? 'op' : 'ops'} failed. Fix them in Data Studio or start a new version.
            </p>
          )}
          {link ? (
            <a href={link} target="_blank" rel="noopener noreferrer" className={`${buttonClass('primary', 'md')} mt-2`}>
              <ExternalLink aria-hidden="true" />
              Open in Data Studio
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          ) : (
            <p className="text-body text-text-muted">The engine didn't return a link. Start a new version to build again.</p>
          )}
        </div>
      </section>

      <Panel
        title="Versions"
        actions={
          <Button variant="secondary" size="sm" icon={<Plus aria-hidden="true" />} loading={creating} onClick={newVersion}>
            New version
          </Button>
        }
      >
        {error && (
          <p role="alert" className="border-b border-border px-4 py-2 text-label text-danger">
            {error}
          </p>
        )}
        <ul aria-label="Versions" className="divide-y divide-border">
          {versions.map((v) => (
            <li key={v.n} className="flex items-center gap-4 px-4 py-3">
              <span className="w-10 shrink-0 font-mono text-body font-medium text-text">v{v.n}</span>
              <span className={`shrink-0 rounded-control px-2 py-0.5 text-caption font-medium ${STATUS_TONE[v.status]}`}>
                {STATUS_LABEL[v.status]}
              </span>
              <p className="min-w-0 flex-1 text-caption text-text-muted">
                Created <time dateTime={v.created_at}>{formatTime(v.created_at)}</time>
                {v.n === build.current_version ? ', current' : ''}
              </p>
              <div className="w-40 shrink-0 text-right text-label">
                {v.report_url ? (
                  <ReportLink
                    href={v.report_url}
                    className={`inline-flex items-center gap-1 rounded-sm font-medium text-primary hover:text-primary-hover hover:underline ${focusRing}`}
                  />
                ) : (
                  <span className="text-text-muted">Not published</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
