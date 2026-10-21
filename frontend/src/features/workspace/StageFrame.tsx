import { Check, Pencil, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import type { ArtifactState } from '../../api/types';
import { ARTIFACT_STATE_LABELS } from './Stepper';

const badgeTone: Record<Exclude<ArtifactState, 'missing'>, { className: string; icon: ReactNode }> = {
  confirmed: { className: 'bg-success-soft text-success', icon: <Check aria-hidden="true" strokeWidth={3} /> },
  draft: { className: 'bg-primary-soft text-primary', icon: <Pencil aria-hidden="true" strokeWidth={2.5} /> },
  stale: { className: 'border border-dashed border-text-muted text-text', icon: <TriangleAlert aria-hidden="true" strokeWidth={2.5} /> },
};

/** An artifact's state as a small labelled badge (the icon repeats the label, never replaces it). */
export function ArtifactBadge({ state, why }: { state: ArtifactState; why?: string | null }) {
  if (state === 'missing') return null;
  const tone = badgeTone[state];
  return (
    <span data-badge={state} className={`inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-caption font-medium [&_svg]:size-3 ${tone.className}`}>
      {tone.icon}
      {ARTIFACT_STATE_LABELS[state]}
      {why && <span className="font-normal">· {why}</span>}
    </span>
  );
}

/**
 * The frame of every staged area (docs/staged-ui.md): a header row (title, artifact state badge,
 * revision), the scrolling body, and a sticky footer with the secondary actions on the left and
 * the primary action on the right.
 */
export function StageFrame({
  title,
  lead,
  state,
  why,
  revision,
  secondary,
  primary,
  status,
  children,
}: {
  title: string;
  lead: ReactNode;
  state: ArtifactState;
  why?: string | null;
  revision: number | null;
  secondary?: ReactNode;
  primary?: ReactNode;
  /** Text beside the primary action: a count, open issues, or why the actions are disabled. */
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-heading font-semibold text-text">{title}</h2>
        <ArtifactBadge state={state} why={why} />
        {revision !== null && <span className="text-label text-text-muted tabular-nums">Revision {revision}</span>}
      </div>
      <p className="mt-0.5 text-body text-text-muted">{lead}</p>
      <div className="flex-1 pb-6">{children}</div>
      <div className="sticky bottom-0 -mx-6 -mb-6 flex items-center gap-3 border-t border-border bg-surface px-6 py-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{secondary}</div>
        {status && <p className="min-w-0 text-label text-text-muted">{status}</p>}
        {primary}
      </div>
    </div>
  );
}
