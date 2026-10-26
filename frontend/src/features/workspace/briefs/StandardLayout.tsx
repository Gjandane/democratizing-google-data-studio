import { LayoutTemplate } from 'lucide-react';
import type { DesignPage } from '../../../api/types';

/** The one-line note of a standard-layout page (docs/stage-settings-ui.md, Design briefs). */
export function standardNote(page: Pick<DesignPage, 'layout' | 'standard_reason'>): string | null {
  if (page.layout !== 'standard') return null;
  return page.standard_reason === 'layout_fallback'
    ? 'The designed page still failed its checks after its repairs, so this page uses the standard layout (switch in Settings, HTML without a reference)'
    : 'This page uses the standard layout.';
}

/** "Standard layout" on a page tab: text and an outline, never color alone. Fits a 20 px line, so the tab row keeps its height. */
export function StandardLayoutChip({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-flex h-5 shrink-0 items-center gap-1 rounded-control border border-border-strong bg-surface px-1.5 text-caption font-medium whitespace-nowrap text-text-muted [&_svg]:size-3 ${className}`}
    >
      <LayoutTemplate aria-hidden="true" />
      Standard layout
    </span>
  );
}

/** The note shown in the brief panel (and, from 16.4, wherever a page's layout is explained). */
export function StandardLayoutNote({ page }: { page: Pick<DesignPage, 'layout' | 'standard_reason'> }) {
  const note = standardNote(page);
  if (!note) return null;
  return (
    <p className="flex items-start gap-2 rounded-control border border-border-strong bg-surface-muted px-3 py-2 text-label text-text [&_svg]:mt-0.5 [&_svg]:size-3.5 [&_svg]:shrink-0">
      <LayoutTemplate aria-hidden="true" />
      <span>
        <span className="font-semibold">Standard layout.</span> <span>{note}</span>
      </span>
    </p>
  );
}
