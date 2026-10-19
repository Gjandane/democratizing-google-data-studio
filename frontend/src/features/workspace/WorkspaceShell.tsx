import { Activity, ArrowLeft, ChartColumn, CircleCheck, Database, FileText, Hammer, MessagesSquare, MousePointerClick, Settings } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import { ApiError, type Build, type Message, type Stage } from '../../api/types';
import { Button, buttonClass } from '../../components/Button';
import { ErrorState } from '../../components/ErrorState';
import { focusRing } from '../../components/focus';
import { LoadingState } from '../../components/Spinner';
import { DoneStage } from '../history/DoneStage';
import { ChatPanel } from './chat/ChatPanel';
import { InterviewStage } from './chat/InterviewStage';
import { useBuildStream, type BuildStream, type ProgressLine, type StretchRuns } from './chat/useBuildStream';
import { ConnectStage } from './connect/ConnectStage';
import { BuildStage } from './build/BuildStage';
import { failedCount, idleRun, type BuildRun } from './build/buildRun';
import { PlanStage } from './plan/PlanStage';
import { PrototypeStage } from './prototype/PrototypeStage';
import { STAGE_LABELS, Stepper } from './Stepper';

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; build: Build };

/** Stage areas until each stage's own view replaces its entry here. */
const STAGE_VIEWS: Record<Stage, { lead: string; icon: ReactNode; title: string; text: string }> = {
  connect: {
    lead: 'Add the data this dashboard reads from.',
    icon: <Database />,
    title: 'No sources yet',
    text: 'CSV files and BigQuery tables you add show up here, with their columns.',
  },
  interview: {
    lead: "Answer the assistant's questions in the chat.",
    icon: <MessagesSquare />,
    title: 'Interview',
    text: 'Questions answered in the chat show up here.',
  },
  plan: {
    lead: 'The planner writes the build docs.',
    icon: <FileText />,
    title: 'Build docs',
    text: 'Docs show up here as the planner writes them.',
  },
  prototype: {
    lead: 'Click any part of the prototype to comment on it.',
    icon: <MousePointerClick />,
    title: 'Prototype',
    text: 'The prototype shows up here, ready for comments.',
  },
  build: {
    lead: 'The engine builds the dashboard in Data Studio.',
    icon: <Hammer />,
    title: 'Recipe',
    text: 'Recipe steps show up here and tick off as the engine runs them.',
  },
  done: {
    lead: 'The dashboard is published in Data Studio.',
    icon: <CircleCheck />,
    title: 'Published dashboard',
    text: 'The dashboard link and its versions show up here.',
  },
};

interface WorkspaceShellProps {
  /** The Trace and Settings buttons stay disabled until something handles them. */
  onOpenTrace?: () => void;
  onOpenSettings?: () => void;
}

function TopBar({ build, onOpenTrace, onOpenSettings }: { build: Build | null } & WorkspaceShellProps) {
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
      <div className="min-w-0 px-6">{build && <Stepper current={build.stage} />}</div>
      <div className="flex items-center gap-1 px-3">
        <Button variant="ghost" size="sm" icon={<Activity aria-hidden="true" />} disabled={!onOpenTrace} onClick={onOpenTrace}>
          Trace
        </Button>
        <Button variant="ghost" size="sm" icon={<Settings aria-hidden="true" />} disabled={!onOpenSettings} onClick={onOpenSettings}>
          Settings
        </Button>
      </div>
    </header>
  );
}

function StageArea({
  build,
  mainRef,
  messages,
  loadError,
  progress,
  planning,
  applying,
  commentsError,
  runErrors,
  buildRun,
  stretchRuns,
  buildOpen,
  onBuildOpen,
  pendingComments,
  onPendingChange,
  onBuildChange,
}: {
  build: Build;
  mainRef: RefObject<HTMLElement | null>;
  messages: Message[] | null;
  loadError: string | null;
  progress: ProgressLine[];
  planning: boolean;
  applying: boolean;
  commentsError: BuildStream['commentsError'];
  runErrors: BuildStream['runErrors'];
  buildRun: BuildRun;
  stretchRuns: StretchRuns;
  buildOpen: boolean;
  onBuildOpen: (open: boolean) => void;
  pendingComments: number;
  onPendingChange: (count: number) => void;
  onBuildChange: (build: Build) => void;
}) {
  // The Build view shows in the build stage, and from the prototype or done stage once opened (a run that just finished
  // in this session stays open in done); a done build opened from History has no such run and shows the Done view.
  const showBuild = build.stage === 'build' || ((build.stage === 'prototype' || build.stage === 'done') && buildOpen);
  // A result from an earlier version's run doesn't belong to the current version.
  const run = buildRun.finished && buildRun.finished.version !== build.current_version ? idleRun : buildRun;
  const view = STAGE_VIEWS[showBuild ? 'build' : build.stage];
  return (
    <main ref={mainRef} tabIndex={-1} className="relative min-h-0 overflow-y-auto outline-none">
      <div className="px-6 py-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-heading font-semibold text-text">{STAGE_LABELS[showBuild ? 'build' : build.stage]}</h2>
            <p className="mt-0.5 text-body text-text-muted">{view.lead}</p>
          </div>
          {build.stage === 'prototype' && !showBuild && (
            <div className="flex shrink-0 items-center gap-3">
              {pendingComments > 0 && (
                <p id="continue-hint" className="text-label text-text-muted">
                  Apply or remove your comments first.
                </p>
              )}
              <Button
                variant="primary"
                icon={<Hammer aria-hidden="true" />}
                disabled={applying || pendingComments > 0}
                aria-describedby={pendingComments > 0 ? 'continue-hint' : undefined}
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
        {showBuild ? (
          <BuildStage build={build} run={run} />
        ) : build.stage === 'connect' ? (
          <ConnectStage build={build} onBuildChange={onBuildChange} stretchRuns={stretchRuns} />
        ) : build.stage === 'interview' ? (
          <InterviewStage build={build} messages={messages} loadError={loadError} runErrors={runErrors} />
        ) : build.stage === 'plan' ? (
          <PlanStage build={build} progress={progress} planning={planning} />
        ) : build.stage === 'prototype' ? (
          <PrototypeStage build={build} applying={applying} commentsError={commentsError} stretchRuns={stretchRuns} onPendingChange={onPendingChange} />
        ) : (
          <DoneStage
            build={build}
            failedOps={run.finished?.status === 'partial' ? failedCount(run) : 0}
            onBuildChange={onBuildChange}
            onNewVersion={() => buildOpen && onBuildOpen(false)}
          />
        )}
      </div>
    </main>
  );
}

/** The open build: chat column and stage area share its one event stream. */
function Workspace({ build, mainRef, onBuildChange }: { build: Build; mainRef: RefObject<HTMLElement | null>; onBuildChange: (build: Build) => void }) {
  const chat = useBuildStream(build, onBuildChange);
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
  return (
    <div className="grid min-h-0 grid-cols-[var(--layout-chat)_minmax(0,1fr)]">
      <ChatPanel build={build} chat={chat} />
      <StageArea build={build} mainRef={mainRef} messages={chat.messages} loadError={chat.loadError} progress={chat.progress} planning={chat.planning} applying={chat.applying} commentsError={chat.commentsError} runErrors={chat.runErrors} buildRun={chat.buildRun} stretchRuns={chat.stretchRuns} buildOpen={buildOpen} onBuildOpen={toggleBuild} pendingComments={pendingComments} onPendingChange={setPendingComments} onBuildChange={onBuildChange} />
    </div>
  );
}

/** The workspace: top bar with the stepper, the chat column on the left, the stage area. */
export function WorkspaceShell({ onOpenTrace, onOpenSettings }: WorkspaceShellProps) {
  const { id = '' } = useParams();
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const main = useRef<HTMLElement>(null);
  const retried = useRef(false);

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
  const shownStage = useRef<string | null>(null);
  useEffect(() => {
    if (stage === null) return;
    // Stream-driven changes arrive with no user action: never pull focus out of the chat composer.
    const active = document.activeElement;
    const free = !active || active === document.body || main.current?.contains(active);
    if (shownStage.current !== null && shownStage.current !== stage && free) main.current?.focus();
    shownStage.current = stage;
  }, [stage]);

  const retry = () => {
    retried.current = true;
    setAttempt((n) => n + 1);
  };

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
    <div className="grid h-full grid-rows-[var(--layout-topbar)_minmax(0,1fr)]">
      <TopBar build={load.status === 'ready' ? load.build : null} onOpenTrace={onOpenTrace} onOpenSettings={onOpenSettings} />
      {load.status === 'ready' ? (
        <Workspace build={load.build} mainRef={main} onBuildChange={(b) => setLoad({ status: 'ready', build: b })} />
      ) : (
        <main ref={main} tabIndex={-1} className="mx-auto w-full max-w-(--layout-page) px-6 py-8 outline-none">
          {load.status === 'loading' ? (
            <LoadingState>Loading the build…</LoadingState>
          ) : (
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
          )}
        </main>
      )}
    </div>
  );
}
