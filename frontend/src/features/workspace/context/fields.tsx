import { TriangleAlert } from 'lucide-react';
import { useId, useState, type ReactNode, type SelectHTMLAttributes } from 'react';
import type { ValidationIssue } from '../../../api/types';
import { Input } from '../../../components/Input';
import { focusRing } from '../../../components/focus';

/** Issue messages as a field error (Input's `error`): one line each. */
export function issueText(issues: ValidationIssue[] | undefined): ReactNode {
  if (!issues || issues.length === 0) return null;
  return issues.map((issue, i) => (
    <span key={i} className="block">
      {issue.message}
    </span>
  ));
}

/** Issues that belong to a card, a row or a list rather than one field. */
export function IssueList({ issues, className = '' }: { issues: ValidationIssue[] | undefined; className?: string }) {
  if (!issues || issues.length === 0) return null;
  return (
    <ul className={`space-y-0.5 ${className}`}>
      {issues.map((issue, i) => (
        <li key={i} className="flex items-start gap-1.5 text-caption text-danger [overflow-wrap:anywhere]">
          <TriangleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0" />
          {issue.message}
        </li>
      ))}
    </ul>
  );
}

const control = `h-8 w-full rounded-control border border-border-strong bg-surface px-2 text-body text-text enabled:hover:border-text-muted disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted aria-invalid:border-danger ${focusRing}`;

interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> {
  label: string;
  hideLabel?: boolean;
  error?: ReactNode;
  className?: string;
  children: ReactNode;
}

/** A labelled native select, styled like Input; an error marks it invalid and describes it. */
export function SelectField({ label, hideLabel, error, className = '', children, ...rest }: SelectFieldProps) {
  const id = useId();
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : 'text-label font-medium text-text'}>
        {label}
      </label>
      <select id={id} aria-invalid={error ? true : undefined} aria-describedby={error ? `${id}-error` : undefined} className={control} {...rest}>
        {children}
      </select>
      {error && (
        <p id={`${id}-error`} className="text-caption text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * A number field that keeps what the user types (an empty or partial value) while focused and
 * reports only parsable numbers; leaving it shows the saved number again.
 */
export function NumberField({
  label,
  value,
  error,
  onValue,
  onBlur,
  className,
}: {
  label: string;
  value: number;
  error?: ReactNode;
  onValue: (value: number) => void;
  onBlur: () => void;
  className?: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const invalid = text !== null && (text.trim() === '' || !Number.isFinite(Number(text)));
  return (
    <Input
      label={label}
      hideLabel
      inputMode="decimal"
      autoComplete="off"
      className={className}
      value={text ?? String(value)}
      error={invalid ? 'Enter a number.' : error}
      onChange={(e) => {
        setText(e.target.value);
        const next = Number(e.target.value);
        if (e.target.value.trim() !== '' && Number.isFinite(next)) onValue(next);
      }}
      onBlur={() => {
        setText(null);
        onBlur();
      }}
    />
  );
}
