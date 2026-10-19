import type { BuildEvent, OpFinished, RecipeOp } from '../../../api/types';

export type BuildFinished = Extract<BuildEvent, { name: 'build.finished' }>['data'];

/** What the build stage knows about the current engine run, folded from the build's event stream. */
export interface BuildRun {
  running: boolean;
  /** Result of each finished op, by op_id. */
  ops: Record<string, OpFinished>;
  finished: BuildFinished | null;
  /** Set when the build run ends in error. */
  error: string | null;
  /** Latest screencast frame of the engine run (base64 JPEG), once one has arrived. */
  frame: string | null;
}

export const idleRun: BuildRun = { running: false, ops: {}, finished: null, error: null, frame: null };

const fresh: BuildRun = { running: true, ops: {}, finished: null, error: null, frame: null };

export function reduceBuildRun(run: BuildRun, event: BuildEvent): BuildRun {
  switch (event.name) {
    case 'run.started':
      return event.data.node === 'execute' ? { ...fresh } : run;
    case 'stage.changed':
      // Another tab started the run: its run.started was never seen here.
      return event.data.stage === 'build' && !run.running ? { ...fresh } : run;
    case 'build.op':
      return { ...run, ops: { ...run.ops, [event.data.op_id]: event.data } };
    case 'build.frame':
      return { ...run, frame: event.data.data };
    case 'build.finished':
      return { ...run, finished: event.data, running: false };
    case 'run.finished':
      return event.data.node === 'execute' && event.data.status === 'error'
        ? { ...run, error: event.data.error ?? null, running: false }
        : run;
    default:
      return run;
  }
}

/** Ops that did not finish ok or skipped, whether or not the recipe lists them. */
export const failedCount = (run: BuildRun): number => Object.values(run.ops).filter((op) => op.status === 'failed').length;

/** The op shown as running: the first recipe op without a result while the run goes. */
export function runningOpId(run: BuildRun, ops: RecipeOp[]): string | null {
  if (!run.running) return null;
  return ops.find((op) => !run.ops[op.op_id])?.op_id ?? null;
}
