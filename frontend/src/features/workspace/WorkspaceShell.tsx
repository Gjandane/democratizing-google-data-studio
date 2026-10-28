import { Activity, ArrowLeft, ChartColumn, CircleUserRound, Hammer, Settings } from 'lucide-react';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import { ApiError, ARTIFACTS, type ArtifactName, type Assessment, type Build, type Stage } from '../../api/types';
import { Button, buttonClass } from '../../components/Button';
import { ErrorState } from '../../components/ErrorState';
import { focusRing } from '../../components/focus';
import { useSessionUser } from '../access/sessionUser';
import { LoadingState } from '../../components/Spinner';
import { ActivityColumn } from '../activity/ActivityColumn';
import { useBuildStream, type BuildStream } from '../activity/useBuildStream';
import { DoneStage } from '../history/DoneStage';
import type { SettingsTarget } from '../settings/stageSettings';
import { RunErrorActionsContext, type RunErrorActions } from '../trace/stageErrors';
import { ConnectStage } from './connect/ConnectStage';
import { BuildStage } from './build/BuildStage';
import { failedCount, idleRun } from './build/buildRun';
import { PrototypeStage } from './prototype/PrototypeStage';
import { ArtifactStage } from './ArtifactStage';
import { FeasibilityPanel, type FeasibilityGates } from './FeasibilityPanel';
import { ReferencePanel } from './ReferencePanel';
import { AnalysisGateContext, GateReason, onReferenceUnapproved, useAnalysisGate, useAnalysisGateState } from './reference/gate';
import { prototypeStale, STAGE_LABELS, staleCause, Stepper } from './Stepper';
import { BriefReviewPanel } from './briefs/BriefReviewPanel';
import { onReviewPending, REVIEW_LOCK_REASON, ReviewLockContext } from './briefs/reviewLock';
import { useDesignPages } from './briefs/useDesignPages';
import { AWAIT_RUN_MS } from './outline/OutlinePicker';

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; build: Build };

/** The lead line of the stage areas without an artifact (the artifact stages have their own). */
const STAGE_LEADS: Record<'connect' | 'prototype' | 'build' | 'done', string> = {
  connect: 'Add the data this dashboard reads from.',
  prototype: 'Click any part of the prototype to comment on it.',
  build: 'The engine builds the dashboard in Data Studio.',
  done: 'The dashboard is published in Data Studio.',
};

const isArtifact = (stage: Stage): stage is ArtifactName => (ARTIFACTS as readonly string[]).includes(stage);

interface WorkspaceShellProps {
  /** The Trace and Settings buttons stay disabled until something handles them. A run error's "View model calls" passes its run. */
  onOpenTrace?: (runId?: string) => void;
  /** A stage-limit error's "Adjust in Settings" passes its stage. */
  onOpenSettings?: (target?: SettingsTarget) => void;
}

function TopBar({ build, viewing, onSelect, onOpenTrace, onOpenSettings }: { build: Build | null; viewing: Stage | null; onSelect: (stage: Stage) => void } & WorkspaceShellProps) {
  const user = useSessionUser();
  return (
    <header className="grid h-(--layout-topbar) grid-cols-[var(--layout-chat)_minmax(0,1fr)_auto] items-center border-b border-border bg-surface">
      <div className="flex h-full min-w-0 items-center gap-3 border-r border-border px-4">
        <Link
          to="/"
          aria-label="All dashboards"
          className={`flex size-7 shrink-0 items-center justify-center rounded-control bg-primary text-on-primary hover:bg-primary-hover ${focusRing}`}
        >
          <ChartColumn aria-hidden="true" className="size-4" />
        </Link>
        {build && (
          <h1 className="truncate text-body font-semibold text-text" title={build.title}>
            {build.title}
          </h1>
        )}
      </div>
      <div className="min-w-0 px-4">{build && <Stepper build={build} viewing={viewing ?? build.stage} onSelect={onSelect} />}</div>
      {/* Below 1440 px the eight-step stepper needs the room: Trace and Settings keep their names for screen readers only. */}
      <div className="flex items-center gap-1 px-3">
        {user && (
          // Icon only at every width: the stepper needs the room; History shows the email in full.
          <span className="flex items-center px-1.5 text-text-muted" title={user}>
            <CircleUserRound aria-hidden="true" className="size-4 shrink-0" />
            <span className="sr-only">Signed in as {user}</span>
          </span>
        )}
        <Button variant="ghost" size="sm" icon={<Activity aria-hidden="true" />} disabled={!onOpenTrace} onClick={() => onOpenTrace?.()} title="Trace" className="max-[1439px]:gap-0 max-[1439px]:px-1.5">
          <span className="max-[1439px]:sr-only">Trace</span>
        </Button>
        <Button variant="ghost" size="sm" icon={<Settings aria-hidden="true" />} disabled={!onOpenSettings} onClick={() => onOpenSettings?.()} title="Settings" className="max-[1439px]:gap-0 max-[1439px]:px-1.5">
          <span className="max-[1439px]:sr-only">Settings</span>
        </Button>
      </div>
    </header>
  );
}

function StageArea({
  build,
  shown,
  mainRef,
  stream,
  buildOpen,
  onBuildOpen,
  pendingComments,
  onPendingChange,
  onBuildChange,
  review,
  reviewLock,
}: {
  build: Build;
  /** The brief review panel, at the top of the stage area whatever the stage. */
  review: ReactNode;
  /** The review lock's reason while a brief review waits, else null. */
  reviewLock: string | null;
  /** The stage area on screen: the build's stage, or an earlier step the stepper reopened. */
  shown: Stage;
  mainRef: RefObject<HTMLElement | null>;
  stream: BuildStream;
  buildOpen: boolean;
  onBuildOpen: (open: boolean) => void;
  pendingComments: number;
  onPendingChange: (count: number) => void;
  onBuildChange: (build: Build) => void;
}) {
  // The Build view shows in the build stage, and from the prototype or done stage once opened (a run that just finished
  // in this session stays open in done); a done build opened from History has no such run and shows the Done view.
  const [referencesReady, setReferencesReady] = useState(false);
  const [feasibility, setFeasibility] = useState<FeasibilityGates>({ planReady: false, buildReady: false });
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [assessmentRefresh, refreshAssessment] = useState(0);
  const { applying, commentsError, buildRun, stretchRuns } = stream;
  // A recreate analysis waiting for approval keeps Generate recipe and Build off (reference/gate).
  const analysisPending = useAnalysisGate()?.pending === true;
  const showBuild = shown === build.stage && (build.stage === 'build' || ((build.stage === 'prototype' || build.stage === 'done') && buildOpen));
  // A result from an earlier version's run doesn't belong to the current version.
  const run = buildRun.finished && buildRun.finished.version !== build.current_version ? idleRun : buildRun;
  const view: Stage = showBuild ? 'build' : shown;
  const staleProto = shown === 'prototype' && prototypeStale(build);
  const feasibilityPanel = build.stage !== 'done' && (
    <FeasibilityPanel key={`${build.id}-${build.current_version}`} buildId={build.id} referencesReady={referencesReady} readOnly={build.stage === 'build'} onReadyChange={setFeasibility} onAssessmentChange={setAssessment} refreshKey={assessmentRefresh} canReplan={build.stage === 'prototype'} localCommentsPending={pendingComments > 0} />
  );
  const references = (
    <div className="mt-6">
      <ReferencePanel buildId={build.id} version={build.current_version} readOnly={build.stage === 'build' || build.stage === 'done'} onReadyChange={setReferencesReady} />
    </div>
  );
  return (
    <main ref={mainRef} tabIndex={-1} className="relative min-h-0 scroll-pb-20 overflow-y-auto outline-none">
      <div className="flex min-h-full flex-col px-6 py-6">
        {review}
        {isArtifact(view) ? (
          <ArtifactStage
            key={view}
            build={build}
            name={view}
            stream={stream}
            feasibility={feasibilityPanel}
            acceptReady={referencesReady && feasibility.planReady}
            onBuildChange={onBuildChange}
          >
            {references}
          </ArtifactStage>
        ) : (
          <>
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="text-heading font-semibold text-text">{STAGE_LABELS[view]}</h2>
                <p className="mt-0.5 text-body text-text-muted">{STAGE_LEADS[view]}</p>
              </div>
              {build.stage === 'prototype' && !showBuild && (
                <div className="flex shrink-0 items-center gap-3">
                  {(reviewLock !== null || pendingComments > 0) && (
                    <p id="continue-hint" className="text-label text-text-muted">
                      {reviewLock ?? 'Apply or remove your comments first.'}
                    </p>
                  )}
                  <Button
                    variant="primary"
                    icon={<Hammer aria-hidden="true" />}
                    disabled={applying || reviewLock !== null || pendingComments > 0 || !referencesReady || !feasibility.buildReady}
                    aria-describedby={reviewLock !== null || pendingComments > 0 ? 'continue-hint' : undefined}
                    onClick={() => onBuildOpen(true)}
                  >
                    Continue to build
                  </Button>
                </div>
              )}
              {build.stage === 'prototype' && showBuild && (
                <Button variant="ghost" icon={<ArrowLeft aria-hidden="true" />} onClick={() => onBuildOpen(false)}>
                  Back to prototype
                </Button>
              )}
              {build.stage === 'done' && showBuild && (
                <Button variant="ghost" icon={<ArrowLeft aria-hidden="true" />} onClick={() => onBuildOpen(false)}>
                  Back to versions
                </Button>
              )}
            </div>
            {staleProto && (
              <p role="status" className="mt-4 rounded-control border border-dashed border-text-muted px-3 py-2 text-body text-text">
                This prototype is stale ({`Changed: ${STAGE_LABELS[staleCause(build, 'prototype') ?? 'blueprint']}`}). Accept the blueprint again to update it; Build stays off until then.
              </p>
            )}
            {feasibilityPanel}
            {showBuild ? (
              <>
                {references}
                {analysisPending && build.stage !== 'done' && (
                  <p className="mt-4 rounded-control bg-surface-muted px-3 py-2 text-body text-text">
                    <GateReason />
                  </p>
                )}
                <BuildStage build={build} run={run} referencesReady={referencesReady && !analysisPending} feasibilityReady={feasibility.buildReady} />
              </>
            ) : view === 'connect' ? (
              <ConnectStage build={build} onBuildChange={onBuildChange} stretchRuns={stretchRuns} onReferenceReadyChange={setReferencesReady} onAssessmentInvalidated={() => refreshAssessment((n) => n + 1)} />
            ) : view === 'prototype' ? (
              <PrototypeStage assessment={assessment} onAssessmentInvalidated={() => refreshAssessment((n) => n + 1)} build={build} applying={applying} commentsError={commentsError} stretchRuns={stretchRuns} onPendingChange={onPendingChange} onReferenceReadyChange={setReferencesReady} />
            ) : (
              <DoneStage
                build={build}
                failedOps={run.finished?.status === 'partial' ? failedCount(run) : 0}
                onBuildChange={onBuildChange}
                onNewVersion={() => buildOpen && onBuildOpen(false)}
              />
            )}
          </>
        )}
      </div>
    </main>
  );
}

/** The open build: activity column and stage area share its one event stream. */
function Workspace({ build, shown, mainRef, onBuildChange }: { build: Build; shown: Stage; mainRef: RefObject<HTMLElement | null>; onBuildChange: (build: Build) => void }) {
  const stream = useBuildStream(build, onBuildChange);
  const [buildOpen, setBuildOpen] = useState(false);
  const [pendingComments, setPendingComments] = useState(0);
  const movedFocus = useRef(false);
  // The stage is `build` exactly while a run goes (a missed build.finished can't leave it stuck).
  const running = build.stage === 'build';
  useEffect(() => {
    if (running) setBuildOpen(true);
  }, [running]);
  // The toggle button unmounts itself: keep keyboard focus on the stage area.
  const toggleBuild = (open: boolean) => {
    movedFocus.current = true;
    setBuildOpen(open);
  };
  useLayoutEffect(() => {
    if (!movedFocus.current) return;
    movedFocus.current = false;
    mainRef.current?.focus();
  }, [buildOpen, mainRef]);

  // The brief review (api.md 3.0): one lock for the whole workspace, from GET design-pages.
  const designPages = useDesignPages(build.id);
  const reloadPages = designPages.reload;
  // Any action answered 409 brief_review_pending: a review waits that this window never saw.
  useEffect(() => onReviewPending(reloadPages), [reloadPages]);
  // Reviews approved or cancelled here: hidden at once, even before the refetch lands.
  const [handled, setHandled] = useState<ReadonlySet<string>>(() => new Set());
  // After an approve's 202, controls stay off until its run shows on the stream (fallback AWAIT_RUN_MS).
  const [awaitRun, setAwaitRun] = useState<string | null>(null);
  const runSeen = awaitRun !== null && stream.activity.some((run) => run.runId === awaitRun);
  useEffect(() => {
    if (awaitRun === null) return;
    if (runSeen) {
      setAwaitRun(null);
      return;
    }
    const timer = setTimeout(() => setAwaitRun(null), AWAIT_RUN_MS);
    return () => clearTimeout(timer);
  }, [awaitRun, runSeen]);
  const fetched = designPages.data?.review ?? null;
  const review = fetched && !handled.has(fetched.review_id) ? fetched : null;
  // `brief.review` arrived and its refetch is still out: lock in the event's own render.
  const announced = stream.briefReview;
  const unread = announced !== null && !handled.has(announced.review_id) && designPages.loading;
  const reviewLock = review !== null || unread || (awaitRun !== null && !runSeen) ? REVIEW_LOCK_REASON : null;

  // The reference analysis gate: one per workspace; a 409 reference_unapproved from any action opens its review.
  const analysisGate = useAnalysisGateState();
  const focusAnalysis = analysisGate.focusReview;
  useEffect(() => onReferenceUnapproved(focusAnalysis), [focusAnalysis]);

  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const leftReview = useRef(false);
  const shownReview = review?.review_id ?? null;
  useLayoutEffect(() => {
    if (shownReview === null) {
      // Approve or Cancel unmounted the panel with focus in it: keep keyboard focus on the stage area.
      if (leftReview.current) mainRef.current?.focus();
      leftReview.current = false;
      return;
    }
    // A review appeared: take focus to it, unless the user is in the top bar or the activity column.
    const active = document.activeElement;
    if (!active || active === document.body || mainRef.current?.contains(active)) reviewHeading.current?.focus();
  }, [shownReview, mainRef]);
  const settle = (reviewId: string) => {
    leftReview.current = true;
    setHandled((ids) => new Set(ids).add(reviewId));
    reloadPages();
  };
  const reviewPanel = review && (
    <BriefReviewPanel
      key={review.review_id}
      buildId={build.id}
      review={review}
      headingRef={reviewHeading}
      onReload={reloadPages}
      onApproved={(reviewId, runId) => {
        setAwaitRun(runId);
        settle(reviewId);
      }}
      onCancelled={(reviewId) => {
        settle(reviewId);
        // Cancel drops the candidate: read the build again (its stage and artifacts).
        api.getBuild(build.id).then(onBuildChange, () => {
          // The stream's next event or reconnect brings it.
        });
      }}
    />
  );

  return (
    <ReviewLockContext.Provider value={reviewLock}>
      <AnalysisGateContext.Provider value={analysisGate}>
        <div className="grid min-h-0 grid-cols-[var(--layout-chat)_minmax(0,1fr)]">
          <ActivityColumn build={build} stream={stream} />
          <StageArea build={build} shown={shown} mainRef={mainRef} stream={stream} buildOpen={buildOpen} onBuildOpen={toggleBuild} pendingComments={pendingComments} onPendingChange={setPendingComments} onBuildChange={onBuildChange} review={reviewPanel} reviewLock={reviewLock} />
        </div>
      </AnalysisGateContext.Provider>
    </ReviewLockContext.Provider>
  );
}

/** The workspace: top bar with the stepper, the activity column on the left, the stage area. */
export function WorkspaceShell({ onOpenTrace, onOpenSettings }: WorkspaceShellProps) {
  const { id = '' } = useParams();
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  // A step the stepper reopened, kept only while the build stays in the stage it was opened from.
  const [reopened, setReopened] = useState<{ stage: Stage; from: Stage } | null>(null);
  const main = useRef<HTMLElement>(null);
  const retried = useRef(false);
  const selected = useRef(false);

  useEffect(() => {
    let active = true;
    setLoad({ status: 'loading' });
    api.getBuild(id).then(
      (build) => {
        if (active) setLoad({ status: 'ready', build });
      },
      (error: unknown) => {
        if (!active) return;
        const message = error instanceof ApiError ? error.message : "Couldn't open this build. Try again.";
        setLoad({ status: 'error', message });
      },
    );
    return () => {
      active = false;
    };
  }, [id, attempt]);

  // "Try again" unmounts while loading; put keyboard focus back on the page's main area after.
  // Layout effect: focus lands in the same commit as the content, before anything can observe it.
  useLayoutEffect(() => {
    if (!retried.current || load.status === 'loading') return;
    retried.current = false;
    main.current?.focus();
  }, [load.status]);

  // A stage change unmounts the control that started it; move keyboard focus to the new stage.
  const stage = load.status === 'ready' ? load.build.stage : null;
  const shown = stage !== null && reopened?.from === stage ? reopened.stage : stage;
  useEffect(() => {
    if (reopened && reopened.from !== stage) setReopened(null);
  }, [reopened, stage]);
  const shownStage = useRef<string | null>(null);
  useEffect(() => {
    if (shown === null) return;
    // Stream-driven changes arrive with no user action: never pull focus out of the top bar or a control outside the stage.
    const active = document.activeElement;
    const free = selected.current || !active || active === document.body || main.current?.contains(active);
    if (shownStage.current !== null && shownStage.current !== shown && free) main.current?.focus();
    selected.current = false;
    shownStage.current = shown;
  }, [shown]);

  const retry = () => {
    retried.current = true;
    setAttempt((n) => n + 1);
  };

  const select = (next: Stage) => {
    if (stage === null) return;
    selected.current = true;
    setReopened(next === stage ? null : { stage: next, from: stage });
  };

  // Run errors anywhere in the workspace open Settings at a stage or Trace at a run.
  const runErrorActions = useMemo<RunErrorActions>(
    () => ({ openSettings: onOpenSettings && ((target) => onOpenSettings(target)), openTrace: onOpenTrace && ((runId) => onOpenTrace(runId)) }),
    [onOpenSettings, onOpenTrace],
  );

  const title = load.status === 'ready' ? load.build.title : null;
  useEffect(() => {
    if (!title) return;
    const previous = document.title;
    document.title = `${title} - Data Studio builder`;
    return () => {
      document.title = previous;
    };
  }, [title]);

  return (
    <RunErrorActionsContext.Provider value={runErrorActions}>
      <div className="grid h-full grid-rows-[var(--layout-topbar)_minmax(0,1fr)]">
        <TopBar build={load.status === 'ready' ? load.build : null} viewing={shown} onSelect={select} onOpenTrace={onOpenTrace} onOpenSettings={onOpenSettings} />
        {load.status === 'ready' && shown !== null ? (
          <Workspace build={load.build} shown={shown} mainRef={main} onBuildChange={(b) => setLoad({ status: 'ready', build: b })} />
        ) : (
          <main ref={main} tabIndex={-1} className="mx-auto w-full max-w-(--layout-page) px-6 py-8 outline-none">
            {load.status === 'error' ? (
              <ErrorState
                title="Couldn't open this build"
                message={load.message}
                onRetry={retry}
                actions={
                  <Link to="/" className={buttonClass('ghost', 'sm')}>
                    Back to dashboards
                  </Link>
                }
              />
            ) : (
              <LoadingState>Loading the build…</LoadingState>
            )}
          </main>
        )}
      </div>
    </RunErrorActionsContext.Provider>
  );
}
