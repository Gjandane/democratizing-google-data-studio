import { CircleCheck, CircleX, ExternalLink, Hammer } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, HOSTED_ERROR_CODES, type Build, type EngineStatus, type Recipe } from '../../../api/types';
import { Button, buttonClass } from '../../../components/Button';
import { Spinner } from '../../../components/Spinner';
import { SampleDataBanner } from '../connect/SyntheticDataPanel';
import { failedCount, idleRun, type BuildRun } from './buildRun';
import { EnginePanel, engineReady } from './EnginePanel';
import { useHosting } from './hosting';
import { JobPanel, type JobStatus } from './JobPanel';
import { LiveViewPanel } from './LiveViewPanel';
import { RecipePanel } from './RecipePanel';
import { useReviewLock } from '../briefs/reviewLock';

const messageOf = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

/** Hosted runs report `<code>: message` (api.md 3.4); the code is for machines, the message for people. */
function hostedErrorText(error: string | null): string | null {
  const at = error?.indexOf(': ') ?? -1;
  if (!error || at < 0) return error;
  return (HOSTED_ERROR_CODES as readonly string[]).includes(error.slice(0, at)) ? error.slice(at + 2) : error;
}

const failedText = (failed: number) => (failed === 0 ? 'Some ops failed' : `${failed} ${failed === 1 ? 'op' : 'ops'} failed`);

/** The outcome as one sentence for the live region. */
function outcomeSentence(run: BuildRun): string {
  const finished = run.finished;
  if (!finished) return '';
  if (finished.status === 'ok') return 'Build finished. Your dashboard is in Data Studio.';
  if (finished.status === 'partial') return `Build finished with errors: ${failedText(failedCount(run)).toLowerCase()}.`;
  return `Build finished. The build failed.${run.error ? ` ${run.error}` : ''}`;
}

function ResultCard({ run }: { run: BuildRun }) {
  const finished = run.finished;
  if (!finished) return null;
  const failed = failedCount(run);
  const ok = finished.status !== 'failed';
  const Icon = ok ? CircleCheck : CircleX;
  return (
    <section
      className={`flex items-start gap-3 rounded-panel border px-4 py-3 ${ok ? 'border-success bg-success-soft' : 'border-danger bg-danger-soft'}`}
    >
      <Icon aria-hidden="true" className={`mt-0.5 size-5 shrink-0 ${ok ? 'text-success' : 'text-danger'}`} />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-body font-semibold text-text">{ok ? 'Your dashboard is in Data Studio.' : 'The build failed.'}</p>
        {finished.status === 'partial' && (
          <>
            <p className="text-body font-medium text-danger">
              {failedText(failed)}
            </p>
            <p className="text-body text-text-muted">The dashboard is saved; fix the failed steps in Data Studio or build a new version.</p>
          </>
        )}
        {finished.status === 'failed' && (
          <p className="text-body text-text-muted">
            {run.error ?? 'The engine stopped before the dashboard was saved. Check the failed step, then build again.'}
          </p>
        )}
        {finished.report_url && (
          <a href={finished.report_url} target="_blank" rel="noopener noreferrer" className={`${buttonClass('primary', 'md')} mt-2`}>
            <ExternalLink aria-hidden="true" />
            Open in Data Studio
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
      </div>
    </section>
  );
}

/** The Build stage: engine status, the recipe with live per-op status, the build action, the result. */
export function BuildStage({ build, run: streamRun, referencesReady = true, feasibilityReady = true }: { build: Build; run: BuildRun; referencesReady?: boolean; feasibilityReady?: boolean }) {
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [engineKey, setEngineKey] = useState(0);
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [generating, setGenerating] = useState(false);
  const [recipeError, setRecipeError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const hosting = useHosting();
  /** Agent mode (api.md 3.4): builds are one-shot jobs on the visitor's computer, no engine panel. */
  const agent = (hosting?.mode ?? engine?.mode) === 'agent';
  const [jobKey, setJobKey] = useState(0);
  const [job, setJob] = useState<JobStatus>({ waiting: false, lost: false });
  const mounted = useRef(true);
  // A brief review waits (WorkspaceShell's lock): the recipe and the build wait with it.
  const reviewLock = useReviewLock();
  const reviewLocked = useRef(false);
  reviewLocked.current = reviewLock !== null;
  /** The run object at the time the recipe was compiled while idle: its results belong to the old recipe. */
  const compiledFor = useRef<BuildRun | null>(null);
  const autoCompiled = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // The stage is `build` exactly while a run goes, so a missed build.finished cannot leave it running.
  // A lost build code (agent mode, restored in the build stage) is not a run anyone can finish.
  const lost = agent && job.lost && build.stage === 'build';
  const running = build.stage === 'build' && !lost;
  const latestRun = useRef(streamRun);
  latestRun.current = streamRun;
  const stale = !running && streamRun === compiledFor.current;
  const run: BuildRun = stale ? idleRun : { ...streamRun, running };

  const buildId = build.id;
  const generate = async () => {
    if ((!referencesReady || !feasibilityReady) || reviewLocked.current) return;
    setGenerating(true);
    setRecipeError(null);
    try {
      const next = await api.compileRecipe(buildId);
      if (mounted.current) {
        compiledFor.current = latestRun.current;
        setRecipe(next);
      }
    } catch (error) {
      if (mounted.current) setRecipeError(messageOf(error, "Couldn't generate the recipe. Try again."));
    } finally {
      if (mounted.current) setGenerating(false);
    }
  };

  // Opened with a run already going (another tab, a reload): fetch the recipe once so the lines can tick.
  const going = running;
  useEffect(() => {
    if ((!referencesReady || !feasibilityReady) || !going || recipe || autoCompiled.current) return;
    autoCompiled.current = true;
    void generate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [going, recipe, referencesReady, feasibilityReady]);

  // The run has begun (or the stage moved on): the click is no longer pending.
  useEffect(() => {
    if (build.stage !== 'prototype') setStarting(false);
  }, [build.stage]);

  const start = async () => {
    if ((!referencesReady || !feasibilityReady) || reviewLocked.current) return;
    setStarting(true);
    setStartError(null);
    try {
      await api.runBuild(buildId);
      if (mounted.current) setJobKey((n) => n + 1);
    } catch (error) {
      if (!mounted.current) return;
      // 409 engine_busy in agent mode: the build already has a code; show it.
      if (error instanceof ApiError && error.code === 'engine_busy') setJobKey((n) => n + 1);
      setStarting(false);
      setStartError(messageOf(error, "Couldn't start the build. Try again."));
      if (error instanceof ApiError && error.status === 424) setEngineKey((n) => n + 1);
    }
  };

  const total = recipe?.ops.length ?? 0;
  const done = recipe ? recipe.ops.filter((op) => run.ops[op.op_id]).length : Object.keys(run.ops).length;
  const ready = engine !== null && engineReady(engine);
  const signedOut = !agent && engine !== null && !engine.signed_in;
  const canBuild =
    referencesReady && feasibilityReady && reviewLock === null && (agent || ready) && recipe !== null && !run.running && !starting && (build.stage === 'prototype' || lost);
  // An expired code is told by the job panel; the failed result card would say it twice.
  const jobExpired = agent && (run.error?.startsWith('job_expired') ?? false);
  const shownRun: BuildRun = agent ? { ...run, error: hostedErrorText(run.error) } : run;

  return (
    <div className="mt-6 space-y-4">
      <SampleDataBanner sources={build.sources}>
        This dashboard is built from invented rows, and Data Studio shows it with the same label.
      </SampleDataBanner>
      {agent ? (
        <JobPanel
          buildId={buildId}
          stage={build.stage}
          jobKey={jobKey}
          starting={starting}
          shareData={hosting?.share_data ?? false}
          runExpired={jobExpired}
          onStatus={setJob}
        />
      ) : (
        <EnginePanel refreshKey={engineKey} onEngine={setEngine} />
      )}
      <fieldset disabled={(!referencesReady || !feasibilityReady) || reviewLock !== null} className="min-w-0"><RecipePanel recipe={recipe} run={run} generating={generating} error={recipeError} onGenerate={generate} /></fieldset>
      <LiveViewPanel frame={run.frame} running={run.running} />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {build.stage === 'done' ? (
          <p className="text-label text-text-muted">Start a new version to build again.</p>
        ) : (
          <Button variant="primary" icon={<Hammer aria-hidden="true" />} disabled={!canBuild} onClick={start}>
            Build in Data Studio
          </Button>
        )}
        {reviewLock && build.stage !== 'done' && <p className="text-label text-text-muted">{reviewLock}</p>}
        {signedOut && <p className="text-label text-text-muted">Sign in to Google to build.</p>}
        {(agent || engine === null || ready) && recipe === null && build.stage === 'prototype' && !run.running && (
          <p className="text-label text-text-muted">Generate the recipe first.</p>
        )}
        {(run.running || starting) && (
          <p className="flex items-center gap-2 text-body text-text">
            <Spinner className="text-primary" />
            {agent && job.waiting ? 'Waiting for your computer…' : 'Building in Data Studio…'}
          </p>
        )}
        {run.running && (
          <p aria-live="polite" className="text-label text-text-muted">
            {done} of {total || '?'} ops done
          </p>
        )}
      </div>
      {startError && (
        <p role="alert" className="text-label text-danger">
          {startError}
        </p>
      )}
      <p role="status" className="sr-only">
        {outcomeSentence(shownRun)}
      </p>
      {!jobExpired && <ResultCard run={shownRun} />}
    </div>
  );
}
