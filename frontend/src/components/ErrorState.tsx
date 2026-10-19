import { CircleAlert, RotateCw } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from './Button';

interface ErrorStateProps {
  /** What failed, e.g. "Couldn't load your dashboards". */
  title: string;
  /** What to do next (the API error's message says it). */
  message: ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
  /** Disables the retry button while a retry is running. */
  retryDisabled?: boolean;
  /** Shows the retry's spinner and aria-busy (and disables it) while the retried work runs. */
  retryLoading?: boolean;
  /** More actions next to the retry button, e.g. a link back. */
  actions?: ReactNode;
  className?: string;
}

/** The error state of a data view, announced to screen readers. */
export function ErrorState({ title, message, onRetry, retryLabel = 'Try again', retryDisabled = false, retryLoading = false, actions, className = '' }: ErrorStateProps) {
  return (
    <div role="alert" className={`flex items-start gap-3 rounded-panel border border-danger bg-danger-soft px-4 py-3 ${className}`}>
      <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <p className="text-body font-semibold text-text">{title}</p>
        <p className="mt-0.5 text-body text-text-muted">{message}</p>
      </div>
      {(onRetry || actions) && (
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          {onRetry && (
            <Button size="sm" icon={<RotateCw aria-hidden="true" />} disabled={retryDisabled} loading={retryLoading} onClick={onRetry}>
              {retryLabel}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
