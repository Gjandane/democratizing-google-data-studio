import { CircleCheck, MousePointerClick, ScanSearch } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, type Assessment, type Build } from '../../../api/types';
import { Button } from '../../../components/Button';
import { EmptyState } from '../../../components/EmptyState';
import { Spinner } from '../../../components/Spinner';
import type { BuildStream, StretchRuns } from '../../activity/useBuildStream';
import { useRefocusAfter, useStretchAction } from '../stretch';
import { PendingList } from './PendingList';
import { ReferencePanel } from '../ReferencePanel';
import { SampleDataBanner } from '../connect/SyntheticDataPanel';
import { PrototypeCanvas } from './PrototypeCanvas';
import type { PendingComment, Target } from './types';

interface PrototypeStageProps {
  assessment?: Assessment | null;
  onAssessmentInvalidated?: () => void;
  onReferenceReadyChange?: (ready: boolean) => void;
  build: Build;
  /** A `revise` run is open (also true when another tab started it). */
  applying: boolean;
  commentsError: BuildStream['commentsError'];
  /** Run state of the UX audit, from the build's event stream. */
  stretchRuns?: StretchRuns;
  /** Told how many comments wait to be applied, so the shell can guard leaving the stage. */
  onPendingChange?: (count: number) => void;
}

const noRuns: StretchRuns = {};

export function PrototypeStage({ build, applying, commentsError, stretchRuns = noRuns, onPendingChange, onReferenceReadyChange, assessment, onAssessmentInvalidated }: PrototypeStageProps) {
  const audit = useStretchAction('audit', 'ux_audit', stretchRuns);
  const auditing = audit.state === 'starting' || audit.state === 'running';
  const auditButton = useRef<HTMLButtonElement>(null);
  useRefocusAfter(auditing, auditButton);
  const [pending, setPending] = useState<PendingComment[]>([]);
  const notify = useRef(onPendingChange);
  useEffect(() => {
    notify.current = onPendingChange;
  });
  useEffect(() => {
    notify.current?.(pending.length);
  }, [pending.length]);
  useEffect(() => () => notify.current?.(0), []);
  const [presentCids, setPresentCids] = useState<Set<string>>(new Set());
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sent = useRef<PendingComment[] | null>(null);
  // A revise failure may persist the blocked batch before its assessment GET arrives.
  const savedCandidate = useRef<PendingComment[] | null>(null);
  const nextId = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const seenError = useRef(commentsError?.seq ?? 0);
  const specVersion = build.spec_version;
  const seenVersion = useRef(specVersion);

  // The new version arrived: the comments of the batch are applied, so their pins go.
  useLayoutEffect(() => {
    if (seenVersion.current === specVersion) return;
    seenVersion.current = specVersion;
    const batch = sent.current;
    if (!batch) return;
    sent.current = null;
    savedCandidate.current = null;
    const ids = new Set(batch.map((c) => c.id));
    setPending((list) => list.filter((c) => !ids.has(c.id)));
    setSubmitting(false);
  }, [specVersion]);

  // Once GET confirms the server owns this batch, remove its local duplicate.
  useLayoutEffect(() => {
    const batch = savedCandidate.current;
    const saved = assessment?.pending_comments?.comments;
    if (!batch || !saved || batch.length !== saved.length || !batch.every((c, i) => c.component_id === saved[i]?.component_id && c.text === saved[i]?.text)) return;
    const ids = new Set(batch.map((c) => c.id));
    savedCandidate.current = null;
    sent.current = null;
    setPending((list) => list.filter((c) => !ids.has(c.id)));
    setSubmitting(false);
    setError(null);
  }, [assessment]);

  // A failed run keeps the comments and says why.
  useLayoutEffect(() => {
    if (!commentsError || commentsError.seq === seenError.current) return;
    seenError.current = commentsError.seq;
    sent.current = null;
    setSubmitting(false);
    setError(commentsError.text);
  }, [commentsError]);

  if (specVersion === null) {
    return (
      <EmptyState
        icon={<MousePointerClick />}
        title="No prototype yet"
        description="The prototype shows up here, ready for comments, once the plan is done."
        headingLevel={3}
        framed
        className="mt-6"
      />
    );
  }

  const add = (target: Target, text: string) =>
    setPending((list) => [...list, { id: ++nextId.current, component_id: target.cid, label: target.label, text }]);

  const apply = () => {
    const batch = pending;
    if (batch.length === 0 || submitting) return;
    sent.current = batch;
    savedCandidate.current = batch;
    setError(null);
    setSubmitting(true);
    // The button disables as the batch starts: keep keyboard focus on the page.
    heading.current?.focus();
    api.postComments(build.id, batch.map(({ component_id, text }) => ({ component_id, text }))).catch((reason: unknown) => {
      if (reason instanceof ApiError && reason.code === 'feasibility_blocked') onAssessmentInvalidated?.();
      else { sent.current = null; savedCandidate.current = null; }
      setSubmitting(false);
      setError(reason instanceof ApiError ? reason.message : "Couldn't apply the comments. Try again.");
    });
  };

  const busy = submitting || applying;
  const batchSize = sent.current?.length ?? pending.length;

  return (
    <div className="mt-6 flex flex-col gap-4">
      {/* Collapsed so the canvas top shows above the fold; the header toggle opens it. */}
      <ReferencePanel buildId={build.id} version={build.current_version} disabled={busy} defaultOpen={false} onReadyChange={onReferenceReadyChange} />
      {!audit.hidden && (
        <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
          <div aria-live="polite" className="text-body text-text-muted">
            {auditing && (
              <span className="inline-flex items-center gap-2">
                <Spinner />
                Auditing…
              </span>
            )}
            {audit.state === 'ok' && (
              <span className="inline-flex items-center gap-2 text-success">
                <CircleCheck aria-hidden="true" className="size-4 shrink-0" />
                Audit done. The findings are in the activity column.
              </span>
            )}
          </div>
          <Button
            ref={auditButton}
            variant="secondary"
            icon={<ScanSearch aria-hidden="true" />}
            disabled={busy || auditing}
            onClick={() => void audit.start(() => api.runAudit(build.id))}
          >
            Run UX audit
          </Button>
          {audit.state === 'error' && audit.error && (
            <p role="alert" className="basis-full text-right text-label text-danger">
              {audit.error}
            </p>
          )}
        </div>
      )}
      <SampleDataBanner sources={build.sources}>
        The prototype runs on invented rows, so its numbers are placeholders, not your data or the values in your screenshot.
      </SampleDataBanner>
      {assessment?.prototype_stale && <p className="flex items-center gap-2 text-body text-text-muted"><span className="rounded-control bg-accent px-2 py-1 font-semibold text-on-accent">Stale</span> This preview shows the previous prototype. Replan or reapply saved comments to update it.</p>}
      <PrototypeCanvas
        url={api.prototypeUrl(build.id, specVersion)}
        title={`Prototype of ${build.title}`}
        pending={pending}
        disabled={busy}
        hoveredId={hoveredId}
        onAdd={add}
        onRead={setPresentCids}
      />
      <PendingList
        comments={pending}
        presentCids={presentCids}
        applying={busy}
        batchSize={batchSize}
        error={error}
        headingRef={heading}
        onRemove={(id) => setPending((list) => list.filter((c) => c.id !== id))}
        onApply={apply}
        onHover={setHoveredId}
      />
    </div>
  );
}
