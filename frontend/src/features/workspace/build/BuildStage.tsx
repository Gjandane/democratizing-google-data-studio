import { CircleCheck, CircleX, ExternalLink, Hammer } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, type Build, type EngineStatus, type Recipe } from '../../../api/types';
import { Button, buttonClass } from '../../../components/Button';
import { Spinner } from '../../../components/Spinner';
import { failedCount, idleRun, type BuildRun } from './buildRun';
import { EnginePanel, engineReady } from './EnginePanel';
import { LiveViewPanel } from './LiveViewPanel';
import { RecipePanel } from './RecipePanel';

const messageOf = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

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
export function BuildStage({ build, run: streamRun, referencesReady = true }: { build: Build; run: BuildRun; referencesReady?: boolean }) {
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [engineKey, setEngineKey] = useState(0);
  const [offlineSignal, setOfflineSignal] = useState(0);
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [generating, setGenerating] = useState(false);
  const [recipeError, setRecipeError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const mounted = useRef(true);
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
  const running = build.stage === 'build';
  const latestRun = useRef(streamRun);
  latestRun.current = streamRun;
  const stale = !running && streamRun === compiledFor.current;
  const run: BuildRun = stale ? idleRun : { ...streamRun, running };

  const buildId = build.id;
  const generate = async () => {
    if (!referencesReady) return;
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
    if (!referencesReady || !going || recipe || autoCompiled.current) return;
    autoCompiled.current = true;
    void generate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [going, recipe, referencesReady]);

  // The run has begun (or the stage moved on): the click is no longer pending.
  useEffect(() => {
    if (build.stage !== 'prototype') setStarting(false);
  }, [build.stage]);

  const start = async () => {
    if (!referencesReady) return;
    setStarting(true);
    setStartError(null);
    try {
      await api.runBuild(buildId);
    } catch (error) {
      if (!mounted.current) return;
      setStarting(false);
      // The agent panel already says what to do about an offline agent.
      if (error instanceof ApiError && error.code === 'agent_offline') {
        // Turn Build off in this render: the panel's own report arrives an effect later.
        setEngine((current) => current && { ...current, mode: 'agent', agent_connected: false });
        setOfflineSignal((n) => n + 1);
        return;
      }
      setStartError(messageOf(error, "Couldn't start the build. Try again."));
      if (error instanceof ApiError && error.status === 424) setEngineKey((n) => n + 1);
    }
  };

  const total = recipe?.ops.length ?? 0;
  const done = recipe ? recipe.ops.filter((op) => run.ops[op.op_id]).length : Object.keys(run.ops).length;
  const ready = engine !== null && engineReady(engine);
  const agentOffline = engine?.mode === 'agent' && !engine.agent_connected;
  const signedOut = engine !== null && !agentOffline && !engine.signed_in;
  const canBuild = referencesReady && ready && recipe !== null && !run.running && !starting && build.stage === 'prototype';

  return (
    <div className="mt-6 space-y-4">
      <EnginePanel refreshKey={engineKey} offlineSignal={offlineSignal} onEngine={setEngine} />
      <fieldset disabled={!referencesReady} className="min-w-0"><RecipePanel recipe={recipe} run={run} generating={generating} error={recipeError} onGenerate={generate} /></fieldset>
      <LiveViewPanel frame={run.frame} running={run.running} />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {build.stage === 'done' ? (
          <p className="text-label text-text-muted">Start a new version to build again.</p>
        ) : (
          <Button variant="primary" icon={<Hammer aria-hidden="true" />} disabled={!canBuild} onClick={start}>
            Build in Data Studio
          </Button>
        )}
        {agentOffline && <p className="text-label text-text-muted">Start the build agent to build.</p>}
        {signedOut && (
          <p className="text-label text-text-muted">{engine?.mode === 'agent' ? 'Sign in on the agent to build.' : 'Sign in to Google to build.'}</p>
        )}
        {(engine === null || ready) && recipe === null && build.stage === 'prototype' && !run.running && (
          <p className="text-label text-text-muted">Generate the recipe first.</p>
        )}
        {(run.running || starting) && (
          <p className="flex items-center gap-2 text-body text-text">
            <Spinner className="text-primary" />
            Building in Data Studio…
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
        {outcomeSentence(run)}
      </p>
      <ResultCard run={run} />
    </div>
  );
}
