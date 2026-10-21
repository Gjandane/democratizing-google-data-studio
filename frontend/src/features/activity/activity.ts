// Client-only activity of the open build's runs, folded from the event stream (contracts/api.md 1.2).
// Events aren't replayed, so a reload mid-run shows nothing until the next run starts.
import { useEffect, useReducer } from 'react';
import type { BuildEvent } from '../../api/types';
import { PHRASE_MS, presetFor, type PresetStep } from './presets';

/** The strip appears this long after `run.started`; shorter runs never show it. */
export const SHOW_DELAY_MS = 400;
/** How long the "Done in" / "Stopped after" line stays after `run.finished`. */
export const LINGER_MS = 5000;
const KEEP_RUNS = 10;

export interface ActivityRun {
  runId: string;
  /** The contract name of the node (contracts/api.md 1.2). */
  node: string;
  startedAt: number;
  finishedAt: number | null;
  status: 'running' | 'ok' | 'error';
  usage: { input: number; output: number } | null;
  /** `build.op` events counted while an `execute` run goes. */
  ops: number;
  /** `node.progress` texts by the step index current when they arrived. */
  labels: Readonly<Record<number, string>>;
  /** The step that was current when the run failed. */
  failedStep: number | null;
  /**
   * Activity messages known when the run started: its card sits after them, so later messages render
   * below it. null while the log's first load hasn't landed (the card then goes after all of it).
   */
  after: number | null;
}

export type Activity = readonly ActivityRun[];

/** Index of the step in progress `elapsed` ms into the run; the last one waits for `run.finished`. */
export function currentStep(steps: readonly PresetStep[], elapsed: number): number {
  let end = 0;
  for (let i = 0; i < steps.length - 1; i++) {
    end += steps[i]!.seconds * 1000;
    if (elapsed < end) return i;
  }
  return Math.max(0, steps.length - 1);
}

const update = (runs: Activity, runId: string, change: (run: ActivityRun) => ActivityRun): Activity =>
  runs.some((r) => r.runId === runId) ? runs.map((r) => (r.runId === runId ? change(r) : r)) : runs;

/** `messages` is how many chat messages are known as the event arrives, null before the first load (used by `run.started`). */
export function reduceActivity(runs: Activity, event: BuildEvent, now: number, messages: number | null = null): Activity {
  switch (event.name) {
    case 'ready':
      // A run.finished missed while disconnected must not leave a run going forever.
      return runs.some((r) => r.status === 'running') ? runs.filter((r) => r.status !== 'running') : runs;
    case 'run.started': {
      const run: ActivityRun = {
        runId: event.data.run_id,
        node: event.data.node,
        startedAt: now,
        finishedAt: null,
        status: 'running',
        usage: null,
        ops: 0,
        labels: {},
        failedStep: null,
        after: messages,
      };
      return [...runs.filter((r) => r.runId !== run.runId), run].slice(-KEEP_RUNS);
    }
    case 'run.usage': {
      const { input_tokens: input, output_tokens: output } = event.data;
      return update(runs, event.data.run_id, (r) => ({ ...r, usage: { input, output } }));
    }
    case 'node.progress':
      return update(runs, event.data.run_id, (r) => {
        const steps = presetFor(r.node).steps;
        if (!steps || r.status !== 'running') return r;
        return { ...r, labels: { ...r.labels, [currentStep(steps, now - r.startedAt)]: event.data.text } };
      });
    case 'build.op': {
      const run = [...runs].reverse().find((r) => r.status === 'running' && r.node === 'execute');
      return run ? update(runs, run.runId, (r) => ({ ...r, ops: r.ops + 1 })) : runs;
    }
    case 'run.finished': {
      const ok = event.data.status === 'ok';
      return update(runs, event.data.run_id, (r) => {
        if (r.status !== 'running') return r;
        const steps = presetFor(r.node).steps;
        return {
          ...r,
          status: ok ? 'ok' : 'error',
          finishedAt: now,
          failedStep: ok || !steps ? null : currentStep(steps, now - r.startedAt),
        };
      });
    }
    default:
      return runs;
  }
}

const lasted = (run: ActivityRun) => (run.finishedAt ?? Infinity) - run.startedAt;

/** The run the strip shows at `now`: the newest one running, else the newest finished one while it lingers. */
export function stripRun(runs: Activity, now: number): ActivityRun | null {
  const running = [...runs].reverse().find((r) => r.status === 'running');
  const run = running ?? runs[runs.length - 1];
  if (!run || now - run.startedAt < SHOW_DELAY_MS || lasted(run) < SHOW_DELAY_MS) return null;
  if (run.finishedAt !== null && now - run.finishedAt >= LINGER_MS) return null;
  return run;
}

/** The newest run with steps: the one a checklist card can show, whether or not it shows yet. */
export function cardCandidate(runs: Activity): ActivityRun | null {
  return [...runs].reverse().find((r) => presetFor(r.node).steps) ?? null;
}

/** The run whose checklist card shows: the newest run with steps that outlasted the strip delay. */
export function cardRun(runs: Activity, now: number): ActivityRun | null {
  const run = cardCandidate(runs);
  if (!run || now - run.startedAt < SHOW_DELAY_MS || lasted(run) < SHOW_DELAY_MS) return null;
  return run;
}

/** The ms until the strip or card next changes at `now`, or null when nothing will. */
export function nextChange(run: ActivityRun | null, runs: Activity, now: number): number | null {
  const waits: number[] = [];
  for (const r of runs) {
    const elapsed = now - r.startedAt;
    if (elapsed < SHOW_DELAY_MS && r.status === 'running') waits.push(SHOW_DELAY_MS - elapsed);
    if (r.finishedAt !== null && now - r.finishedAt < LINGER_MS) waits.push(LINGER_MS - (now - r.finishedAt));
  }
  if (run?.status === 'running') {
    const elapsed = now - run.startedAt;
    waits.push(1000 - (elapsed % 1000), PHRASE_MS - (elapsed % PHRASE_MS));
    let end = 0;
    for (const step of presetFor(run.node).steps ?? []) {
      end += step.seconds * 1000;
      if (end > elapsed) {
        waits.push(end - elapsed);
        break;
      }
    }
  }
  return waits.length ? Math.max(1, Math.min(...waits)) : null;
}

/** Re-renders when `nextChange` says the view changes; the timer is cleared on every render and on unmount. */
export function useActivityClock(next: number | null): void {
  const [, tick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (next === null) return;
    const timer = setTimeout(tick, next);
    return () => clearTimeout(timer);
  });
}

/** m:ss */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/** 950, 12.4k, 1.2M */
export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${trim(n / 1000)}k`;
  return `${trim(n / 1_000_000)}M`;
}
const trim = (x: number) => (Math.floor(x * 10) / 10).toFixed(1).replace(/\.0$/, '');
