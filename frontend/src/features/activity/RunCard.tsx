import { Check, Circle, CirclePause, X } from 'lucide-react';
import { useLayoutEffect } from 'react';
import { Spinner } from '../../components/Spinner';
import { parseStageError, StageErrorActions } from '../trace/stageErrors';
import { presetFor } from './presets';
import { cardRun, currentStep, nextChange, useActivityClock, type Activity } from './activity';

type StepStatus = 'done' | 'active' | 'pending' | 'failed' | 'paused';

const STATUS_TEXT: Record<StepStatus, string> = { done: 'done', active: 'in progress', pending: 'to do', failed: 'failed', paused: 'waiting for you' };

/** The last step of a run that stopped for the user's brief review (api.md 3.0 `brief.review`). */
export const PAUSED_STEP = 'Paused for brief review';

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'done') return <Check aria-hidden="true" className="size-3.5 shrink-0 text-success" />;
  if (status === 'failed') return <X aria-hidden="true" className="size-3.5 shrink-0 text-danger" />;
  if (status === 'paused') return <CirclePause aria-hidden="true" className="size-3.5 shrink-0 text-primary" />;
  if (status === 'active') return <Spinner size="sm" className="text-primary" />;
  return <Circle aria-hidden="true" className="size-3.5 shrink-0 text-border-strong" />;
}

/**
 * The preset checklist of the newest run with steps. Steps tick on their preset timer; the last
 * one waits for `run.finished` ok, so the card never claims a result before the server does.
 * A run that paused for a brief review ends on "Paused for brief review" instead of a tick. A run
 * that stopped on a stage limit (api.md 3.0) says why, with Adjust in Settings and View model calls.
 */
export function RunCard({ activity, onShow }: { activity: Activity; onShow?: () => void }) {
  const now = Date.now();
  const run = cardRun(activity, now);
  useActivityClock(nextChange(run, activity, now));
  // The card mounts on its own timer: let the activity log scroll to it.
  const shown = run?.runId;
  useLayoutEffect(() => {
    if (shown) onShow?.();
  }, [shown, onShow]);
  const preset = run && presetFor(run.node);
  if (!run || !preset?.steps) return null;

  const current = currentStep(preset.steps, now - run.startedAt);
  const stageError = run.status === 'error' ? parseStageError(run.error) : null;
  const last = preset.steps.length - 1;
  const pausedHere = run.paused && run.status === 'ok';
  const statusOf = (i: number): StepStatus => {
    if (pausedHere) return i < last ? 'done' : 'paused';
    if (run.status === 'ok') return 'done';
    const at = run.status === 'error' ? (run.failedStep ?? current) : current;
    if (i < at) return 'done';
    if (i > at) return 'pending';
    return run.status === 'error' ? 'failed' : 'active';
  };

  return (
    <section
      aria-label={preset.title}
      // Steps tick every few seconds: keep them out of the activity log's announcements (the strip speaks).
      aria-live="off"
      data-run-card={run.runId}
      className="w-full self-start rounded-panel border border-border bg-surface px-3 py-2"
    >
      <h3 className="mb-1.5 text-label font-semibold text-text">{preset.title}</h3>
      <ol className="flex flex-col gap-1">
        {preset.steps.map((step, i) => {
          const status = statusOf(i);
          return (
            <li key={i} data-step-status={status} className="flex items-center gap-2 text-label">
              <StepIcon status={status} />
              <span className={`min-w-0 [overflow-wrap:anywhere] ${status === 'pending' ? 'text-text-muted' : 'text-text'}`}>
                {pausedHere && i === last ? PAUSED_STEP : (run.labels[i] ?? step.label)}
              </span>
              <span className="sr-only">({STATUS_TEXT[status]})</span>
            </li>
          );
        })}
      </ol>
      {stageError && (
        <div className="mt-2 border-t border-border pt-2">
          <p className="text-label text-text [overflow-wrap:anywhere]">{stageError.message}</p>
          <div className="mt-1.5 flex flex-wrap gap-2">
            <StageErrorActions error={stageError} runId={run.runId} />
          </div>
        </div>
      )}
    </section>
  );
}
