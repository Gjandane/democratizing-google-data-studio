import { useId, type InputHTMLAttributes, type ReactNode, type Ref, type TextareaHTMLAttributes } from 'react';
import { focusRing } from './focus';

interface FieldProps {
  label: string;
  /** Keeps the label for screen readers only (a chat box with a visible placeholder). */
  hideLabel?: boolean;
  hint?: ReactNode;
  /** What is wrong and how to fix it; marks the control invalid. */
  error?: ReactNode;
}

const control = `w-full rounded-control border border-border-strong bg-surface px-2.5 text-body text-text placeholder:text-text-muted enabled:hover:border-text-muted disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted aria-invalid:border-danger ${focusRing}`;

function Field({
  id,
  label,
  hideLabel,
  hint,
  error,
  className = '',
  children,
}: FieldProps & { id: string; className?: string; children: ReactNode }) {
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : 'text-label font-medium text-text'}>
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-caption text-text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-caption text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

const describedBy = (id: string, hint: ReactNode, error: ReactNode) =>
  error ? `${id}-error` : hint ? `${id}-hint` : undefined;

export interface InputProps extends FieldProps, Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  id?: string;
  ref?: Ref<HTMLInputElement>;
}

export function Input({ id, label, hideLabel, hint, error, className, ...rest }: InputProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <Field id={inputId} label={label} hideLabel={hideLabel} hint={hint} error={error} className={className}>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(inputId, hint, error)}
        className={`h-8 ${control}`}
        {...rest}
      />
    </Field>
  );
}

export interface TextAreaProps extends FieldProps, Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> {
  id?: string;
  ref?: Ref<HTMLTextAreaElement>;
}

export function TextArea({ id, label, hideLabel, hint, error, className, rows = 3, ...rest }: TextAreaProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <Field id={inputId} label={label} hideLabel={hideLabel} hint={hint} error={error} className={className}>
      <textarea
        id={inputId}
        rows={rows}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(inputId, hint, error)}
        className={`resize-y py-1.5 ${control}`}
        {...rest}
      />
    </Field>
  );
}
