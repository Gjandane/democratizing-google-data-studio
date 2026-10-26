import { X } from 'lucide-react';
import type { Ref } from 'react';
import { Button } from '../../../components/Button';
import { Pin } from '../../../components/Pin';
import { MAX_COMMENTS, type PendingComment } from './types';

interface PendingListProps {
  comments: PendingComment[];
  /** Component ids that exist in the page now. */
  presentCids: Set<string>;
  /** Each component's page name, when the prototype has 2+ pages. */
  pageNames?: Map<string, string>;
  applying: boolean;
  /** Why Apply is off while nothing is applying (the brief review lock), else null. */
  lockReason?: string | null;
  /** Size of the batch being applied. */
  batchSize: number;
  error: string | null;
  headingRef: Ref<HTMLHeadingElement>;
  onRemove: (id: number) => void;
  onApply: () => void;
  onHover: (id: number | null) => void;
}

const plural = (n: number) => `${n} comment${n === 1 ? '' : 's'}`;

export function PendingList({ comments, presentCids, pageNames, applying, lockReason = null, batchSize, error, headingRef, onRemove, onApply, onHover }: PendingListProps) {
  const tooMany = comments.length > MAX_COMMENTS;
  return (
    <section aria-labelledby="pending-heading" className="rounded-panel border border-border bg-surface">
      <header className="flex min-h-11 items-center border-b border-border px-4 py-2">
        <h3 id="pending-heading" ref={headingRef} tabIndex={-1} className="text-body font-semibold text-text outline-none">
          Comments
        </h3>
      </header>
      <div className="px-4 py-3">
        {comments.length === 0 ? (
          <p className="text-body text-text-muted">Click any part of the prototype to add a comment.</p>
        ) : (
          <ul aria-label="Pending comments" className="flex flex-col gap-2">
            {comments.map((comment, index) => (
              <li
                key={comment.id}
                onMouseEnter={() => onHover(comment.id)}
                onMouseLeave={() => onHover(null)}
                onFocus={() => onHover(comment.id)}
                onBlur={() => onHover(null)}
                className="flex items-start gap-3 rounded-control px-1 py-1 hover:bg-surface-muted"
              >
                <Pin n={index + 1} className="mt-0.5" />
                <div className="min-w-0 flex-1">
                  <p className="text-caption text-text-muted">
                    {pageNames?.get(comment.component_id) && <span>{pageNames.get(comment.component_id)} · </span>}
                    {comment.label}
                    {!presentCids.has(comment.component_id) && <span> · Not in this version</span>}
                  </p>
                  <p className="whitespace-pre-wrap break-words text-body text-text">{comment.text}</p>
                </div>
                <Button variant="ghost" size="sm" icon={<X aria-hidden="true" />} disabled={applying} aria-label={`Remove comment ${index + 1}`} onClick={() => onRemove(comment.id)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <footer className="flex flex-wrap items-center justify-end gap-3 border-t border-border px-4 py-3">
        {error && (
          <p role="alert" className="mr-auto text-label text-danger">
            {error}
          </p>
        )}
        {tooMany && <p className="text-label text-text-muted">Apply at most {MAX_COMMENTS} comments at a time.</p>}
        {lockReason && !applying && <p className="text-label text-text-muted">{lockReason}</p>}
        <Button variant="accent" loading={applying} disabled={comments.length === 0 || tooMany || lockReason !== null} onClick={onApply}>
          {applying ? `Applying ${plural(batchSize)}…` : `Apply ${plural(comments.length)}`}
        </Button>
      </footer>
    </section>
  );
}
