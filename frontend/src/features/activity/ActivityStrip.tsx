import { CircleAlert, CircleCheck, CirclePause } from 'lucide-react';
import { PHRASE_MS, presetFor } from './presets';
import { formatElapsed, formatTokens, nextChange, stripRun, useActivityClock, type Activity, type ActivityRun } from './activity';
import { PAUSED_STEP } from './RunCard';

const sep = <span aria-hidden="true">·</span>;

function Dots() {
  return (
    <span aria-hidden="true" data-dots className="inline-flex gap-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={`size-1 rounded-full bg-text-muted motion-safe:animate-pulse ${['', '[animation-delay:200ms]', '[animation-delay:400ms]'][i]}`}
        />
      ))}
    </span>
  );
}

function Tokens({ run }: { run: ActivityRun }) {
  if (!run.usage) return null;
  const { input, output } = run.usage;
  return (
    <>
      {sep}
      <span className="tabular-nums" title={`${input.toLocaleString('en-US')} input · ${output.toLocaleString('en-US')} output tokens`}>
        {formatTokens(input + output)} tokens
      </span>
    </>
  );
}

/**
 * One line at the foot of the activity column: what the current run is doing, its elapsed time and live tokens.
 * Its height is always reserved, so the message list never jumps when it appears.
 */
export function ActivityStrip({ activity }: { activity: Activity }) {
  const now = Date.now();
  const run = stripRun(activity, now);
  useActivityClock(nextChange(run, activity, now));

  let line = null;
  let announce = '';
  if (run?.status === 'running') {
    const elapsed = now - run.startedAt;
    const { phrases } = presetFor(run.node);
    line = (
      <>
        <span className="flex min-w-0 items-center gap-1.5 text-text">
          <span className="truncate">{phrases[Math.floor(elapsed / PHRASE_MS) % phrases.length]}</span>
          <Dots />
        </span>
        {sep}
        <span className="tabular-nums">{formatElapsed(elapsed)}</span>
        <Tokens run={run} />
        {run.node === 'execute' && (
          <>
            {sep}
            <span>{run.ops === 1 ? '1 op done' : `${run.ops} ops done`}</span>
          </>
        )}
      </>
    );
    announce = `${phrases[0]}…`;
  } else if (run) {
    const took = formatElapsed((run.finishedAt ?? now) - run.startedAt);
    const ok = run.status === 'ok';
    // A run that emitted brief.review finished ok but only paused: it says so, as its card does, with no success tick.
    const paused = ok && run.paused;
    announce = paused ? PAUSED_STEP : ok ? `Done in ${took}` : `Stopped after ${took}`;
    const total = ok && run.usage ? ` · ${formatTokens(run.usage.input + run.usage.output)} tokens` : '';
    line = (
      <>
        {paused ? (
          <CirclePause aria-hidden="true" className="size-3.5 shrink-0 text-primary" />
        ) : ok ? (
          <CircleCheck aria-hidden="true" className="size-3.5 shrink-0 text-success" />
        ) : (
          <CircleAlert aria-hidden="true" className="size-3.5 shrink-0 text-danger" />
        )}
        <span className="text-text">{announce}</span>
        {ok && <Tokens run={run} />}
      </>
    );
    announce += total;
  }

  return (
    <div data-activity-strip className="flex h-8 shrink-0 items-center px-3">
      {line && (
        <p aria-hidden="true" className="flex min-w-0 items-center gap-1.5 whitespace-nowrap text-caption text-text-muted">
          {line}
        </p>
      )}
      {/* The visible line ticks every second; screen readers hear the start and the end once. */}
      <p role="status" className="sr-only">
        {announce}
      </p>
    </div>
  );
}
