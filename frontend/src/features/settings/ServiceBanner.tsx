import { Info, X } from 'lucide-react';
import { Button } from '../../components/Button';

interface ServiceBannerProps {
  title: string;
  message: string;
  onOpenSettings: () => void;
  onDismiss: () => void;
}

/** A strip above the app: something in Settings blocks the work, and the button opens them. */
export function ServiceBanner({ title, message, onOpenSettings, onDismiss }: ServiceBannerProps) {
  return (
    <div role="alert" className="flex shrink-0 items-center gap-3 border-b border-primary/30 bg-primary-soft px-4 py-2">
      <Info aria-hidden="true" className="size-4 shrink-0 text-primary" />
      <p className="min-w-0 flex-1 text-body text-text">
        <span className="font-semibold">{title}</span> {message}
      </p>
      <Button size="sm" variant="primary" onClick={onOpenSettings}>
        Open settings
      </Button>
      <Button size="sm" variant="ghost" icon={<X aria-hidden="true" />} aria-label="Dismiss" onClick={onDismiss} />
    </div>
  );
}
