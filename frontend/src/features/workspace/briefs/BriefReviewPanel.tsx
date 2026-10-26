// The brief review gate (docs/stage-settings-ui.md, Brief review; api.md 3.0): a pending review of
// one page's design brief, edited in place (text saves on blur, one PUT at a time), approved with
// what is on screen, or cancelled. The server decides stale and pending; this panel only shows it.
import { CirclePause, Download, Info, TriangleAlert } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { api } from '../../../api/client';
import { ApiError, type BriefReview, type PageBrief, type ValidationIssue } from '../../../api/types';
import { Button } from '../../../components/Button';
import { Modal } from '../../../components/Modal';
import { focusRing } from '../../../components/focus';
import { IssueList } from '../context/fields';
import { placeIssues } from '../context/model';

export const REVIEW_CONFLICT_NOTE = 'This brief changed in another window. Check it, then approve again.';
export const REVIEW_STALE_NOTE = 'The build changed after this brief was written. Cancel and run it again.';

/** The editable text of a review: Overall, then one treatment per slot (in `brief.slots` order). */
interface Draft {
  overall: string;
  treatments: string[];
}
type FieldKey = 'overall' | number;

const draftOf = (review: BriefReview): Draft => ({
  overall: review.brief.brief.overall,
  treatments: review.brief.brief.slots.map((slot) => slot.treatment),
});
const textOf = (draft: Draft, key: FieldKey) => (key === 'overall' ? draft.overall : (draft.treatments[key] ?? ''));
const keysOf = (draft: Draft): FieldKey[] => ['overall', ...draft.treatments.map((_, i) => i)];
const sameText = (a: Draft, b: Draft) => keysOf(a).every((key) => textOf(a, key) === textOf(b, key)) && a.treatments.length === b.treatments.length;
const briefOf = (review: BriefReview, draft: Draft): PageBrief => ({
  page: review.brief.brief.page,
  overall: draft.overall,
  slots: review.brief.brief.slots.map((slot, i) => ({ id: slot.id, treatment: draft.treatments[i] ?? slot.treatment })),
});
const messageOf = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);
const codeOf = (error: unknown) => (error instanceof ApiError ? error.code : null);
const issueCount = (n: number) => (n === 0 ? 'No open issues' : n === 1 ? '1 open issue' : `${n} open issues`);

/** Grows a textarea with its content (no inner scrollbar, no character limit). */
function grow(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = 'auto';
  if (el.scrollHeight > 0) el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`;
}

function ReviewField({
  label,
  context,
  value,
  issues,
  flagged,
  disabled,
  readOnly,
  onChange,
  onBlur,
}: {
  label: string;
  /** Read by screen readers after the visible label ("for Total access"). */
  context?: string;
  value: string;
  issues: ValidationIssue[] | undefined;
  flagged: boolean;
  disabled: boolean;
  readOnly: boolean;
  onChange: (value: string) => void;
  onBlur: () => void;
}) {
  const id = useId();
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => grow(ref.current), [value]);
  const errorId = `${id}-error`;
  const flagId = `${id}-flag`;
  const describedBy = [issues?.length ? errorId : null, flagged ? flagId : null].filter(Boolean).join(' ') || undefined;
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-label font-medium text-text">
        {label}
        {context && (
          <>
            {' '}
            <span className="sr-only">{context}</span>
          </>
        )}
      </label>
      <textarea
        ref={ref}
        id={id}
        rows={2}
        value={value}
        disabled={disabled}
        readOnly={readOnly}
        aria-invalid={issues?.length ? true : undefined}
        aria-describedby={describedBy}
        onChange={(event) => {
          onChange(event.target.value);
          grow(event.target);
        }}
        onBlur={onBlur}
        className={`w-full resize-none overflow-hidden rounded-control border border-border-strong bg-surface px-2.5 py-1.5 text-body text-text enabled:hover:border-text-muted disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted aria-invalid:border-danger ${flagged ? 'border-accent' : ''} ${focusRing}`}
      />
      {issues && issues.length > 0 && (
        <p id={errorId} className="flex items-start gap-1.5 text-caption text-danger [overflow-wrap:anywhere]">
          <TriangleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0" />
          <span>
            {issues.map((issue, i) => (
              <span key={i} className="block">
                {issue.message}
              </span>
            ))}
          </span>
        </p>
      )}
      {flagged && (
        <p id={flagId} className="text-caption text-text">
          <span className="font-semibold">Not saved yet.</span> Your text is kept here; leaving the field saves it over the other window's version.
        </p>
      )}
    </div>
  );
}

export interface BriefReviewPanelProps {
  buildId: string;
  /** The pending review as last read from `GET design-pages`. Mount with `key={review.review_id}`. */
  review: BriefReview;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  /** Read design-pages again (a conflict, a stale or invalid answer, a review that is gone). */
  onReload: () => void;
  /** Approve answered `202`: the review is consumed and `runId` continues under the review's node. */
  onApproved: (reviewId: string, runId: string) => void;
  /** Cancel answered: nothing was published; the shell refetches the build. */
  onCancelled: (reviewId: string) => void;
}

export function BriefReviewPanel({ buildId, review, headingRef, onReload, onApproved, onCancelled }: BriefReviewPanelProps) {
  const headingId = useId();
  // The server's copy as this panel last saw it (from GET or from its own PUT).
  const [server, setServerState] = useState(review);
  const serverRef = useRef(review);
  const setServer = (next: BriefReview) => {
    serverRef.current = next;
    setServerState(next);
  };
  const [draft, setDraftState] = useState<Draft>(() => draftOf(review));
  const latest = useRef(draft);
  const setDraft = (next: Draft) => {
    latest.current = next;
    setDraftState(next);
  };
  // Edit counters, as in the artifact editors: a response replaces the text only when nothing newer was typed.
  const edited = useRef(0);
  const inFlight = useRef(false);
  const queued = useRef(false);
  const [saving, setSaving] = useState(false);
  // Bumped when a save settles, so a design-pages read that landed meanwhile is merged after it.
  const [settled, setSettled] = useState(0);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [flagged, setFlagged] = useState<ReadonlySet<FieldKey>>(new Set());
  const [conflict, setConflict] = useState(false);
  const [staleHere, setStaleHere] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const approvingRef = useRef(false);
  const [cancelling, setCancelling] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // A newer read of the review (another window saved, or the refetch after a conflict): take the
  // server's text, except a field holding typing that was never saved, which stays and is flagged.
  useEffect(() => {
    if (inFlight.current) return;
    const known = serverRef.current;
    if (review.review_id !== known.review_id || review.revision < known.revision) return;
    if (review.revision === known.revision) {
      // Same text; issues or stale may have changed (after an artifact_invalid or stale answer).
      if (review !== known && (review.stale !== known.stale || review.issues !== known.issues)) setServer({ ...known, issues: review.issues, stale: review.stale });
      return;
    }
    const before = draftOf(known);
    const theirs = draftOf(review);
    const mine = latest.current;
    const keep = new Set<FieldKey>();
    const merged: Draft = { overall: theirs.overall, treatments: [...theirs.treatments] };
    for (const key of keysOf(theirs)) {
      const typed = textOf(mine, key);
      if (typed !== textOf(before, key) && typed !== textOf(theirs, key)) {
        keep.add(key);
        if (key === 'overall') merged.overall = typed;
        else merged.treatments[key] = typed;
      }
    }
    if (!sameText(merged, mine)) setConflict(true);
    setServer(review);
    setDraft(merged);
    setFlagged(keep);
    setSaveError(null);
    edited.current += 1;
  }, [review, settled]);

  const stale = server.stale || staleHere;
  const dirty = !sameText(draft, draftOf(server));
  const busy = approving || cancelling;

  const save = async (): Promise<void> => {
    if (inFlight.current) {
      queued.current = true;
      return;
    }
    if (stale || sameText(latest.current, draftOf(serverRef.current))) return;
    inFlight.current = true;
    setSaving(true);
    const seq = edited.current;
    const base = serverRef.current;
    const sent = latest.current;
    let retry = false;
    try {
      const next = await api.saveBriefReview(buildId, { review_id: base.review_id, revision: base.revision, brief: briefOf(base, sent) });
      if (!mounted.current) return;
      setServer(next);
      setSaveError(null);
      setConflict(false);
      // A late response never overwrites newer typing.
      if (edited.current === seq) {
        setDraft(draftOf(next));
        setFlagged(new Set());
      } else {
        const saved = draftOf(next);
        setFlagged((current) => new Set([...current].filter((key) => textOf(latest.current, key) !== textOf(saved, key))));
      }
      retry = true;
    } catch (error) {
      if (!mounted.current) return;
      const code = codeOf(error);
      if (code === 'brief_review_conflict') {
        // The refetch brings the other window's text; unsaved typing stays, flagged.
        setConflict(true);
        onReload();
      } else if (code === 'brief_review_stale') {
        setStaleHere(true);
        onReload();
      } else {
        if (code === 'review_not_found') onReload();
        setSaveError(messageOf(error, "Couldn't save the brief. Try again."));
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setSaving(false);
        setSettled((n) => n + 1);
        if (queued.current) {
          queued.current = false;
          if (retry) void save();
        }
      }
    }
  };

  const change = (key: FieldKey, value: string) => {
    const current = latest.current;
    const next: Draft = key === 'overall' ? { ...current, overall: value } : { ...current, treatments: current.treatments.map((t, i) => (i === key ? value : t)) };
    edited.current += 1;
    setDraft(next);
  };

  const approve = async () => {
    if (approvingRef.current || inFlight.current || !canApprove) return;
    approvingRef.current = true;
    setApproving(true);
    setActionError(null);
    setConflict(false);
    const current = serverRef.current;
    try {
      const { run_id } = await api.approveBriefReview(buildId, { review_id: current.review_id, revision: current.revision, sha256: current.brief.sha256 });
      if (mounted.current) onApproved(current.review_id, run_id);
    } catch (error) {
      if (!mounted.current) return;
      const code = codeOf(error);
      if (code === 'brief_review_conflict') {
        setConflict(true);
        onReload();
      } else if (code === 'brief_review_stale') {
        setStaleHere(true);
        onReload();
      } else {
        // artifact_invalid brings its issues with the refetch; a lost response can be approved again (same run).
        if (code === 'artifact_invalid' || code === 'review_not_found') onReload();
        setActionError(messageOf(error, "Couldn't approve the brief. Try again."));
      }
    } finally {
      approvingRef.current = false;
      if (mounted.current) setApproving(false);
    }
  };

  const cancel = async () => {
    setConfirming(false);
    if (cancelling) return;
    setCancelling(true);
    setActionError(null);
    try {
      await api.cancelBriefReview(buildId, serverRef.current.review_id);
      if (mounted.current) onCancelled(serverRef.current.review_id);
    } catch (error) {
      if (mounted.current) setActionError(messageOf(error, "Couldn't cancel the run. Try again."));
    } finally {
      if (mounted.current) setCancelling(false);
    }
  };

  const download = () => {
    const name = `brief_p${server.page}.md`;
    const url = URL.createObjectURL(new Blob([server.brief.markdown], { type: 'text/markdown' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const slots = server.brief.brief.slots;
  const rendered = new Set(['/overall', '/slots', ...slots.flatMap((_, i) => [`/slots/${i}`, `/slots/${i}/treatment`])]);
  const placed = placeIssues(server.issues, rendered);
  const above = [...(placed.get('') ?? []), ...(placed.get('/slots') ?? [])];
  const canApprove = !stale && !saving && !saveError && !dirty && server.issues.length === 0 && !busy;

  let progress: ReactNode = null;
  if (saving) progress = 'Saving…';
  else if (saveError) progress = 'Not saved';
  else if (dirty) progress = 'Unsaved changes';

  return (
    <section aria-labelledby={headingId} data-brief-review={server.review_id} className="mb-6 rounded-panel border border-primary bg-surface">
      <header className="flex items-start gap-3 rounded-t-panel border-b border-border bg-primary-soft px-4 py-3">
        <CirclePause aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-primary" />
        <div className="min-w-0">
          <h2 ref={headingRef} id={headingId} tabIndex={-1} className="text-title font-semibold text-text outline-none">
            Review the design brief · Page {server.page} of {server.pages}
          </h2>
          <p className="text-body text-text-muted">HTML generation waits for you. Edit the design text; components and data stay fixed.</p>
        </div>
      </header>

      <div className="flex flex-col gap-4 px-4 py-4">
        {stale && (
          <p role="alert" className="flex items-start gap-2 rounded-control border border-danger bg-danger-soft px-3 py-2 text-body text-text">
            <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-danger" />
            {REVIEW_STALE_NOTE}
          </p>
        )}
        {conflict && !stale && (
          <p role="status" className="flex items-start gap-2 rounded-control border border-primary bg-primary-soft px-3 py-2 text-body text-text">
            <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-primary" />
            {REVIEW_CONFLICT_NOTE}
          </p>
        )}
        {saveError && (
          <div role="alert" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-control border border-danger bg-danger-soft px-3 py-2">
            <p className="min-w-0 flex-1 text-body text-text">{saveError} Your text is kept here.</p>
            <Button size="sm" variant="secondary" disabled={stale || busy} onClick={() => { setSaveError(null); void save(); }}>
              Save again
            </Button>
          </div>
        )}
        {actionError && (
          <p role="alert" className="text-body text-danger">
            {actionError}
          </p>
        )}
        <IssueList issues={above} />

        <ReviewField
          label="Overall"
          value={draft.overall}
          issues={placed.get('/overall')}
          flagged={flagged.has('overall')}
          disabled={stale}
          readOnly={busy}
          onChange={(value) => change('overall', value)}
          onBlur={() => void save()}
        />

        <ul aria-label="Components on this page" className="flex flex-col divide-y divide-border border-t border-border">
          {slots.map((slot, i) => {
            const component = server.components.find((c) => c.id === slot.id);
            const label = component?.label ?? slot.id;
            const labelId = `${headingId}-c${i}`;
            return (
              <li key={slot.id} className="pt-3 [&:not(:last-child)]:pb-3">
                <div role="group" aria-labelledby={labelId} className="grid grid-cols-[minmax(0,13rem)_minmax(0,1fr)] gap-x-4 gap-y-1">
                  <div className="min-w-0">
                    <p id={labelId} className="text-body font-semibold text-text [overflow-wrap:anywhere]">
                      {label}
                    </p>
                    <p className="flex flex-wrap gap-x-2 font-mono text-caption text-text-muted">
                      <span>{component?.type ?? 'component'}</span>
                      <span className="[overflow-wrap:anywhere]">{slot.id}</span>
                    </p>
                    <IssueList issues={placed.get(`/slots/${i}`)} className="mt-1" />
                  </div>
                  <ReviewField
                    label="Treatment"
                    context={`for ${label}`}
                    value={draft.treatments[i] ?? ''}
                    issues={placed.get(`/slots/${i}/treatment`)}
                    flagged={flagged.has(i)}
                    disabled={stale}
                    readOnly={busy}
                    onChange={(value) => change(i, value)}
                    onBlur={() => void save()}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      <footer className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-b-panel border-t border-border px-4 py-3">
        <p className="flex min-w-0 flex-1 items-center gap-1.5 text-label text-text-muted" aria-live="polite">
          <span className={server.issues.length > 0 ? 'font-medium text-danger' : undefined}>{issueCount(server.issues.length)}</span>
          {progress && (
            <>
              <span aria-hidden="true">·</span>
              <span>{progress}</span>
            </>
          )}
        </p>
        <Button variant="ghost" icon={<Download aria-hidden="true" />} onClick={download}>
          Download .md
        </Button>
        <Button variant="secondary" loading={cancelling} disabled={approving} onClick={() => setConfirming(true)}>
          Cancel run
        </Button>
        <Button variant="primary" loading={approving} disabled={!canApprove} onClick={() => void approve()}>
          Approve and generate HTML
        </Button>
      </footer>

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title="Discard this prototype run?"
        description="Nothing is published; pending comments stay."
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirming(false)}>
              Keep reviewing
            </Button>
            <Button variant="danger" onClick={() => void cancel()}>
              Discard run
            </Button>
          </>
        }
      >
        <p className="text-body text-text">The brief of page {server.page} and your edits to it are dropped.</p>
      </Modal>
    </section>
  );
}
