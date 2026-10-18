import { useEffect, useLayoutEffect, useRef, type CSSProperties, type ReactNode, type RefObject } from 'react';
import { focusableIn } from './focus';

interface PopoverProps {
  open: boolean;
  onClose: () => void;
  /** Accessible name of the dialog. */
  label: string;
  /** `dark` is the comment card; `light` is a plain menu-like surface. */
  tone?: 'dark' | 'light';
  /** Element to focus on open; defaults to the first focusable one inside. */
  initialFocus?: RefObject<HTMLElement | null>;
  /** The caller places it (absolute or fixed) so it never covers what it points at. */
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}

const tones = {
  // The focus token is redefined so rings stay visible on the dark card.
  dark: 'bg-text text-surface [--color-focus:var(--color-surface)]',
  light: 'border border-border bg-surface text-text',
} as const;

/**
 * A non-modal floating card: focus moves in on open and back on close; Esc or a press outside
 * closes it.
 */
export function Popover({ open, onClose, label, tone = 'dark', initialFocus, className = '', style, children }: PopoverProps) {
  const card = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useLayoutEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = card.current;
    if (node) (initialFocus?.current ?? focusableIn(node)[0] ?? node).focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (node && event.target instanceof Node && !node.contains(event.target)) onCloseRef.current();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
      if (previous?.isConnected) previous.focus();
    };
  }, [open, initialFocus]);

  if (!open) return null;
  return (
    <div
      ref={card}
      role="dialog"
      aria-label={label}
      tabIndex={-1}
      className={`z-30 rounded-panel p-3 shadow-popover outline-none ${tones[tone]} ${className}`}
      style={style}
    >
      {children}
    </div>
  );
}
