import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';
import { focusRing } from './focus';
import { Spinner } from './Spinner';

/** `inverse` is the quiet button on dark surfaces (the comment popover). */
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'accent' | 'danger' | 'inverse';
export type ButtonSize = 'sm' | 'md';

const base =
  'inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-control font-medium transition-[color,background-color,border-color] disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0';

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-on-primary enabled:hover:bg-primary-hover',
  secondary: 'border border-border bg-surface text-text enabled:hover:border-border-strong enabled:hover:bg-surface-muted',
  ghost: 'text-text-muted enabled:hover:bg-surface-muted enabled:hover:text-text',
  accent: 'bg-accent text-on-accent enabled:hover:bg-accent-hover',
  danger: 'bg-danger text-on-primary enabled:hover:bg-danger-hover',
  inverse: 'text-surface enabled:hover:bg-surface/15',
};

const sizes: Record<ButtonSize, { text: string; square: string }> = {
  sm: { text: 'h-7 px-2.5 text-label', square: 'size-7' },
  md: { text: 'h-8 px-3 text-body', square: 'size-8' },
};

/** Classes of a button, for a link that should look like one. */
export function buttonClass(variant: ButtonVariant = 'secondary', size: ButtonSize = 'md', iconOnly = false): string {
  return `${base} ${variants[variant]} ${iconOnly ? sizes[size].square : sizes[size].text} ${focusRing}`;
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Leading icon. A button with an icon and no text needs an aria-label. */
  icon?: ReactNode;
  /** Shows a spinner, sets aria-busy and blocks clicks while an action runs. */
  loading?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  loading = false,
  disabled,
  type = 'button',
  className = '',
  children,
  ...rest
}: ButtonProps) {
  const iconOnly = children === undefined || children === null || children === false;
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`${buttonClass(variant, size, iconOnly)} ${className}`}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}
