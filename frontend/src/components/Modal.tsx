import { X } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { Button } from './Button';
import { focusableIn } from './focus';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  /** Buttons at the bottom right, main action last. */
  footer?: ReactNode;
  /** Element to focus on open; defaults to the first focusable one in the body. */
  initialFocus?: RefObject<HTMLElement | null>;
  /** `wide`: 720 px at most (Settings). */
  size?: 'sm' | 'md' | 'wide' | 'lg';
  children: ReactNode;
}

const widths = { sm: 'max-w-sm', md: 'max-w-lg', wide: 'max-w-180', lg: 'max-w-4xl' } as const;

/**
 * A modal dialog: focus is trapped inside while it is open and returns to where it was on close;
 * Esc, the close button and a press on the backdrop close it.
 */
export function Modal({ open, onClose, title, description, footer, initialFocus, size = 'md', children }: ModalProps) {
  const dialog = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const onCloseRef = useRef(onClose);
  useLayoutEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const node = dialog.current;
    if (!node) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    (initialFocus?.current ?? focusableIn(node)[0] ?? node).focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusableIn(node).filter((el) => el.getAttribute('tabindex') !== '-1');
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (!first || !last) {
        event.preventDefault();
        node.focus();
      } else if (event.shiftKey && (active === first || !node.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !node.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [open, initialFocus]);

  if (!open) return null;
  return createPortal(
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-text/40 p-6"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onCloseRef.current();
      }}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={`relative flex max-h-full w-full flex-col rounded-panel bg-surface shadow-popover outline-none ${widths[size]}`}
      >
        <header className="border-b border-border py-3 pr-12 pl-4">
          <h2 id={titleId} className="text-title font-semibold text-text">
            {title}
          </h2>
          {description && (
            <p id={descriptionId} className="mt-0.5 text-body text-text-muted">
              {description}
            </p>
          )}
        </header>
        <div className="min-h-0 overflow-y-auto p-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-border px-4 py-3">{footer}</footer>}
        {/* Last in the DOM so focus starts in the body; shown at the top right. */}
        <Button
          variant="ghost"
          size="sm"
          icon={<X aria-hidden="true" />}
          aria-label="Close"
          onClick={() => onCloseRef.current()}
          className="absolute top-2.5 right-2.5"
        />
      </div>
    </div>,
    document.body,
  );
}
