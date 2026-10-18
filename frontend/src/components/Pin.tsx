import type { CSSProperties } from 'react';
import { focusRing } from './focus';

interface PinProps {
  /** The comment's number, from 1. */
  n: number;
  /** Accessible name; defaults to "Comment n". */
  label?: string;
  /** The pin whose comment is open. */
  active?: boolean;
  /** Makes the pin a button (jump to its comment). */
  onClick?: () => void;
  className?: string;
  style?: CSSProperties;
}

/** A numbered amber comment pin. */
export function Pin({ n, label, active = false, onClick, className = '', style }: PinProps) {
  const look = `inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-accent text-caption font-semibold tabular-nums text-on-accent ring-2 ${
    active ? 'ring-text' : 'ring-surface'
  } ${className}`;
  const name = label ?? `Comment ${n}`;
  if (onClick) {
    return (
      <button type="button" aria-label={name} aria-pressed={active} onClick={onClick} className={`${look} enabled:hover:bg-accent-hover ${focusRing}`} style={style}>
        {n}
      </button>
    );
  }
  return (
    <span role="img" aria-label={name} className={look} style={style}>
      {n}
    </span>
  );
}
