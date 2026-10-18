import { CircleCheck, MousePointerClick, ScanSearch } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, type Build } from '../../../api/types';
import { Button } from '../../../components/Button';
import { EmptyState } from '../../../components/EmptyState';
import { Spinner } from '../../../components/Spinner';
import type { BuildStream, StretchRuns } from '../chat/useBuildStream';
import { useRefocusAfter, useStretchAction } from '../stretch';
import { PendingList } from './PendingList';
import { PrototypeCanvas } from './PrototypeCanvas';
import type { PendingComment, Target } from './types';

interface PrototypeStageProps {
  build: Build;
  /** A `comments` run is open (also true when another tab started it). */
  applying: boolean;
  commentsError: BuildStream['commentsError'];
  /** Run state of the UX audit, from the build's event stream. */
  stretchRuns?: StretchRuns;
  /** Told how many comments wait to be applied, so the shell can guard leaving the stage. */
  onPendingChange?: (count: number) => void;
}

const noRuns: StretchRuns = {};

export function PrototypeStage({ build, applying, commentsError, stretchRuns = noRuns, onPendingChange }: PrototypeStageProps) {
  const audit = useStretchAction('audit', 'audit', stretchRuns);
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
    const ids = new Set(batch.map((c) => c.id));
    setPending((list) => list.filter((c) => !ids.has(c.id)));
    setSubmitting(false);
  }, [specVersion]);

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
    setError(null);
    setSubmitting(true);
    // The button disables as the batch starts: keep keyboard focus on the page.
    heading.current?.focus();
    api.postComments(build.id, batch.map(({ component_id, text }) => ({ component_id, text }))).catch((reason: unknown) => {
      sent.current = null;
      setSubmitting(false);
      setError(reason instanceof ApiError ? reason.message : "Couldn't apply the comments. Try again.");
    });
  };

  const busy = submitting || applying;
  const batchSize = sent.current?.length ?? pending.length;

  return (
    <div className="mt-6 flex flex-col gap-4">
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
                Audit done. The findings are in the chat.
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
