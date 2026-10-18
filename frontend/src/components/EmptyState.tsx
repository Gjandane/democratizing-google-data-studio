import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  /** What will show up here, or what to do to fill it. */
  description?: ReactNode;
  icon?: ReactNode;
  /** The action that fills the view, if the user can take one here. */
  action?: ReactNode;
  /** 1 when the empty state is the whole page. */
  headingLevel?: 1 | 2 | 3;
  /** Draws a dashed frame, for an empty view that stands alone on the page. */
  framed?: boolean;
  className?: string;
}

export function EmptyState({ title, description, icon, action, headingLevel = 2, framed = false, className = '' }: EmptyStateProps) {
  const Heading = (['h1', 'h2', 'h3'] as const)[headingLevel - 1] ?? 'h2';
  return (
    <div
      className={`flex flex-col items-center px-6 py-10 text-center ${
        framed ? 'rounded-panel border border-dashed border-border-strong bg-surface' : ''
      } ${className}`}
    >
      {icon && (
        <span aria-hidden="true" className="mb-3 flex size-10 items-center justify-center rounded-full bg-surface-muted text-text-muted [&_svg]:size-5">
          {icon}
        </span>
      )}
      <Heading className="text-title font-semibold text-text">{title}</Heading>
      {description && <p className="mt-1 max-w-sm text-body text-text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
