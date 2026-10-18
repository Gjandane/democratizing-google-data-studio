import { CircleAlert, CircleCheck, Info, X } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react';
import { Button } from './Button';

type Tone = 'info' | 'success' | 'danger';

const icons = {
  info: <Info aria-hidden="true" className="size-4 shrink-0 text-primary" />,
  success: <CircleCheck aria-hidden="true" className="size-4 shrink-0 text-success" />,
  danger: <CircleAlert aria-hidden="true" className="size-4 shrink-0 text-danger" />,
} as const;

/**
 * Bottom-right stack that holds the toasts. Keep it mounted (empty) so screen readers hear each
 * toast added to it: a live region that appears with its text already inside is often skipped.
 */
export function ToastRegion({ children }: { children?: ReactNode }) {
  return (
    <div
      role="region"
      aria-label="Notifications"
      aria-live="polite"
      className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2"
    >
      {children}
    </div>
  );
}

interface ToastProps {
  tone?: Tone;
  children: ReactNode;
  onDismiss?: () => void;
  /** Dismisses itself after this many ms (needs onDismiss). Leave it unset for errors. */
  duration?: number;
}

/** A short message about something that just happened, inside ToastRegion. Danger toasts are alerts. */
export function Toast({ tone = 'info', children, onDismiss, duration }: ToastProps) {
  const dismiss = useRef(onDismiss);
  useLayoutEffect(() => {
    dismiss.current = onDismiss;
  });

  useEffect(() => {
    if (!duration) return;
    const timer = setTimeout(() => dismiss.current?.(), duration);
    return () => clearTimeout(timer);
  }, [duration]);

  return (
    <div
      role={tone === 'danger' ? 'alert' : undefined}
      className="pointer-events-auto flex items-start gap-2 rounded-panel border border-border bg-surface py-2 pr-2 pl-3 text-body text-text shadow-popover"
    >
      <span className="flex h-5 items-center">{icons[tone]}</span>
      <div className="min-w-0 flex-1 py-px">{children}</div>
      {onDismiss && <Button variant="ghost" size="sm" icon={<X aria-hidden="true" />} aria-label="Dismiss" onClick={onDismiss} className="-my-1" />}
    </div>
  );
}
