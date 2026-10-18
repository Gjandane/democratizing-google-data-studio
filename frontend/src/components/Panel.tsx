import { useId, type ReactNode } from 'react';

interface PanelProps {
  /** Shown in the panel's header and used as its accessible name. */
  title?: ReactNode;
  /** Controls at the right end of the header. */
  actions?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}

/** A bordered surface (radius 10). No shadow: shadows are for popovers and modals. */
export function Panel({ title, actions, className = '', bodyClassName = '', children }: PanelProps) {
  const titleId = useId();
  return (
    <section
      aria-labelledby={title ? titleId : undefined}
      className={`rounded-panel border border-border bg-surface ${className}`}
    >
      {title && (
        <header className="flex min-h-11 items-center justify-between gap-3 border-b border-border px-4 py-2">
          <h2 id={titleId} className="text-body font-semibold text-text">
            {title}
          </h2>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
