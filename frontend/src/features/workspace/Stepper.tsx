import { Check } from 'lucide-react';
import { STAGES, type Stage } from '../../api/types';

export const STAGE_LABELS: Record<Stage, string> = {
  connect: 'Connect',
  interview: 'Interview',
  plan: 'Plan',
  prototype: 'Prototype',
  build: 'Build',
  done: 'Done',
};

type StepState = 'done' | 'current' | 'upcoming';

const dot = 'flex size-5 shrink-0 items-center justify-center rounded-full text-caption font-semibold tabular-nums';

function Step({ n, label, state, last }: { n: number; label: string; state: StepState; last: boolean }) {
  if (state === 'current') {
    return (
      <span className="flex h-7 items-center gap-1.5 rounded-full bg-primary pr-3 pl-1 text-on-primary">
        <span className={`${dot} bg-on-primary text-primary`}>
          {last ? <Check aria-hidden="true" className="size-3" strokeWidth={3} /> : n}
        </span>
        <span className="text-label font-semibold">{label}</span>
      </span>
    );
  }
  if (state === 'done') {
    return (
      <span className="flex items-center gap-1.5">
        <span className={`${dot} bg-primary-soft text-primary`}>
          <Check aria-hidden="true" className="size-3" strokeWidth={3} />
        </span>
        <span className="text-label text-text">{label}</span>
        <span className="sr-only">(done)</span>
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5">
      <span className={`${dot} border border-border-strong text-text-muted`}>{n}</span>
      <span className="text-label text-text-muted">{label}</span>
    </span>
  );
}

/** The six build stages in a row: done ones checked, the current one filled. Display only. */
export function Stepper({ current }: { current: Stage }) {
  const at = STAGES.indexOf(current);
  return (
    <nav aria-label="Build stages">
      <ol className="flex items-center">
        {STAGES.map((stage, i) => {
          const state: StepState = i < at ? 'done' : i === at ? 'current' : 'upcoming';
          return (
            <li key={stage} data-state={state} aria-current={state === 'current' ? 'step' : undefined} className="flex items-center">
              {i > 0 && <span aria-hidden="true" className={`mx-2 h-0.5 w-4 rounded-full ${i <= at ? 'bg-primary' : 'bg-border-strong'}`} />}
              <Step n={i + 1} label={STAGE_LABELS[stage]} state={state} last={i === STAGES.length - 1} />
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
