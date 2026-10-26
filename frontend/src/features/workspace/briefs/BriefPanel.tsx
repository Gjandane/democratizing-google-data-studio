import { Download, FileText, X } from 'lucide-react';
import { useId, useLayoutEffect, useRef, type KeyboardEvent } from 'react';
import { api } from '../../../api/client';
import type { BriefRecord, DesignPage } from '../../../api/types';
import { Button, buttonClass } from '../../../components/Button';
import { EmptyState } from '../../../components/EmptyState';
import { ErrorState } from '../../../components/ErrorState';
import { LoadingState } from '../../../components/Spinner';
import { BriefMarkdown } from './BriefMarkdown';
import { StandardLayoutNote } from './StandardLayout';
import type { DesignPagesState } from './useDesignPages';

/** "Brief by <model> · HTML by <model> · Generated|Edited · <first 8 of sha256>"; no HTML part when the page has no HTML model. */
export function BriefMeta({ brief, htmlModel, className = '' }: { brief: BriefRecord; htmlModel: string | null; className?: string }) {
  const origin = brief.origin === 'edited' ? 'Edited' : 'Generated';
  return (
    <p data-testid="brief-meta" className={`text-label text-text-muted [overflow-wrap:anywhere] ${className}`}>
      Brief by {brief.model}{htmlModel !== null && <> · HTML by {htmlModel}</>} · {origin} · <span className="font-mono" title={`sha256 ${brief.sha256}`}>{brief.sha256.slice(0, 8)}</span>
    </p>
  );
}

interface BriefPanelProps {
  /** For the toggle's aria-controls. */
  id: string;
  buildId: string;
  /** The page shown: its `data-page` number and name (null when the prototype has no page names). */
  page: { n: number; name: string | null };
  pages: DesignPagesState;
  onClose: () => void;
}

/**
 * The saved design brief of one prototype page (docs/stage-settings-ui.md, Design briefs): a
 * 440 px side panel beside the canvas, so it never covers the page or its pins. It follows the
 * page tab chosen while it is open. Focus moves to its heading on open; Esc closes it.
 */
export function BriefPanel({ id, buildId, page, pages, onClose }: BriefPanelProps) {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    heading.current?.focus();
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    onClose();
  };

  const { data, error, loading, reload } = pages;
  const design = data?.pages.find((p) => p.page === page.n) ?? null;
  const label = page.name ? `Page ${page.n} · ${page.name}` : `Page ${page.n}`;

  return (
    <section
      id={id}
      aria-labelledby={headingId}
      onKeyDown={onKeyDown}
      className="sticky top-4 flex max-h-[calc(100dvh-var(--layout-topbar)-2rem)] w-110 shrink-0 flex-col self-start rounded-panel border border-border bg-surface shadow-popover"
    >
      <header className="flex items-start gap-2 border-b border-border py-3 pr-2.5 pl-4">
        <div className="min-w-0 flex-1">
          <h2 ref={heading} id={headingId} tabIndex={-1} className="text-title font-semibold text-text outline-none">
            Design brief
          </h2>
          <p className="truncate text-label text-text-muted" title={label}>
            {label}
          </p>
        </div>
        <Button variant="ghost" size="sm" icon={<X aria-hidden="true" />} aria-label="Close design brief" onClick={onClose} />
      </header>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
        {data === null ? (
          loading ? (
            <LoadingState className="py-10">Loading the brief…</LoadingState>
          ) : (
            <ErrorState title="Couldn't load the brief" message={error ?? "Couldn't read the page designs. Try again."} onRetry={reload} />
          )
        ) : (
          <>
            {error && (
              <div role="alert" className="flex items-center gap-2 rounded-control border border-danger bg-danger-soft px-3 py-1.5 text-label text-text">
                <span className="min-w-0 flex-1">Couldn't refresh the brief. This is the last one loaded.</span>
                <Button size="sm" variant="ghost" disabled={loading} onClick={reload}>
                  Try again
                </Button>
              </div>
            )}
            {design && <StandardLayoutNote page={design} />}
            {design?.brief ? <SavedBrief buildId={buildId} design={design as DesignPage & { brief: BriefRecord }} /> : (
              <EmptyState
                icon={<FileText />}
                title="No saved brief for this page"
                description="Pages made before design briefs were saved have none."
                headingLevel={3}
                className="py-8"
              />
            )}
          </>
        )}
      </div>
    </section>
  );
}

function SavedBrief({ buildId, design }: { buildId: string; design: DesignPage & { brief: BriefRecord } }) {
  const file = (ext: 'md' | 'json') => `brief_p${design.page}.${ext}`;
  return (
    <>
      <div className="flex flex-col gap-2">
        <BriefMeta brief={design.brief} htmlModel={design.html_model} />
        <div className="flex flex-wrap gap-2">
          {(['md', 'json'] as const).map((ext) => (
            <a key={ext} href={api.fileUrl(buildId, file(ext))} download={file(ext)} className={buttonClass('secondary', 'sm')}>
              <Download aria-hidden="true" />
              Download .{ext}
            </a>
          ))}
        </div>
      </div>
      <BriefMarkdown className="border-t border-border pt-1">{design.brief.markdown}</BriefMarkdown>
    </>
  );
}
