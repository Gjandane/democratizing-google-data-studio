import { LoaderCircle } from 'lucide-react';
import type { ReactNode } from 'react';

const sizes = { sm: 'size-3.5', md: 'size-4', lg: 'size-5' } as const;

/** Decorative spinner; it stops turning under prefers-reduced-motion. Pair it with text. */
export function Spinner({ size = 'md', className = '' }: { size?: keyof typeof sizes; className?: string }) {
  return <LoaderCircle aria-hidden="true" className={`shrink-0 motion-safe:animate-spin ${sizes[size]} ${className}`} />;
}

/** The loading state of a data view: announced to screen readers, text always visible. */
export function LoadingState({ children = 'Loading…', className = '' }: { children?: ReactNode; className?: string }) {
  return (
    <div role="status" className={`flex items-center justify-center gap-2 px-4 py-8 text-body text-text-muted ${className}`}>
      <Spinner />
      <span>{children}</span>
    </div>
  );
}
