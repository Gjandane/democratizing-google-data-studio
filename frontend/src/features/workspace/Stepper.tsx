import { Check, Pencil, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { ARTIFACTS, STAGES, type ArtifactName, type ArtifactState, type Build, type Stage } from '../../api/types';
import { focusRing } from '../../components/focus';

export const STAGE_LABELS: Record<Stage, string> = {
  connect: 'Connect',
  context: 'Context',
  outline: 'Outline',
  design: 'Design',
  blueprint: 'Blueprint',
  prototype: 'Prototype',
  build: 'Build',
  done: 'Done',
};

export const ARTIFACT_STATE_LABELS: Record<ArtifactState, string> = {
  missing: 'Not started',
  draft: 'Draft',
  confirmed: 'Confirmed',
  stale: 'Stale',
};

const isArtifact = (stage: Stage): stage is ArtifactName => (ARTIFACTS as readonly string[]).includes(stage);

/**
 * Why a step is stale: the nearest earlier artifact that isn't stale itself (the one edited, or
 * re-confirmed since). `prototype` is stale while its blueprint isn't confirmed again.
 */
export function staleCause(build: Build, step: ArtifactName | 'prototype'): ArtifactName | null {
  const before = step === 'prototype' ? [...ARTIFACTS] : ARTIFACTS.slice(0, ARTIFACTS.indexOf(step));
  return before.reverse().find((name) => build.artifacts[name] !== 'stale') ?? null;
}

/** A prototype exists but a step it was built from changed: it stays visible, marked stale, until a new accept. */
export function prototypeStale(build: Build): boolean {
  return build.spec_version !== null && STAGES.indexOf(build.stage) < STAGES.indexOf('prototype') && build.artifacts.blueprint !== 'missing';
}

type Position = 'done' | 'current' | 'upcoming';

interface StepModel {
  stage: Stage;
  position: Position;
  /** The artifact state, or `stale` for an outdated prototype; null for steps without one. */
  state: ArtifactState | null;
  /** "Changed: Context" for a stale step. */
  why: string | null;
  /** Opens this step's stage area (a confirmed earlier step reopens for editing). */
  reachable: boolean;
}

function steps(build: Build): StepModel[] {
  const at = STAGES.indexOf(build.stage);
  return STAGES.map((stage, i) => {
    const position: Position = i < at ? 'done' : i === at ? 'current' : 'upcoming';
    let state: ArtifactState | null = null;
    if (isArtifact(stage)) state = build.artifacts[stage];
    else if (stage === 'prototype' && prototypeStale(build)) state = 'stale';
    const cause = state === 'stale' ? staleCause(build, stage as ArtifactName | 'prototype') : null;
    const reachable = position === 'current' || (state !== null && state !== 'missing');
    return { stage, position, state: state === 'missing' ? null : state, why: cause ? `Changed: ${STAGE_LABELS[cause]}` : null, reachable };
  });
}

const dot = 'flex size-5 shrink-0 items-center justify-center rounded-full text-caption font-semibold tabular-nums';
const icon = 'size-3';

/** The dot: the artifact state when there is one (check, pencil, warning), else a check for done steps or the number. */
function Dot({ n, step, filled }: { n: number; step: StepModel; filled: boolean }) {
  let content: ReactNode = n;
  let tone = 'border border-border-strong text-text-muted';
  if (step.state === 'confirmed' || (step.state === null && step.position === 'done') || (step.stage === 'done' && step.position === 'current')) {
    content = <Check aria-hidden="true" className={icon} strokeWidth={3} />;
    tone = 'bg-primary-soft text-primary';
  } else if (step.state === 'draft') {
    content = <Pencil aria-hidden="true" className={icon} strokeWidth={2.5} />;
    tone = 'border border-primary text-primary';
  } else if (step.state === 'stale') {
    content = <TriangleAlert aria-hidden="true" className={icon} strokeWidth={2.5} />;
    tone = 'border border-dashed border-text-muted text-text';
  }
  if (filled) tone = 'bg-on-primary text-primary';
  return <span className={`${dot} ${tone}`}>{content}</span>;
}

function StepBody({ n, step, viewing }: { n: number; step: StepModel; viewing: boolean }) {
  const current = step.position === 'current';
  const label = STAGE_LABELS[step.stage];
  // Screen readers hear the state and the reason; sighted users get the same as a tooltip.
  const described = [step.state ? ARTIFACT_STATE_LABELS[step.state].toLowerCase() : step.position === 'done' ? 'done' : null, step.why, viewing && !current ? 'open' : null]
    .filter(Boolean)
    .join(', ');
  const shape = current
    ? 'h-7 rounded-full bg-primary pr-2.5 pl-1 text-on-primary'
    : `h-7 rounded-full px-1 ${viewing ? 'bg-surface-muted ring-1 ring-border-strong' : ''}`;
  return (
    <span className={`flex items-center gap-1.5 ${shape}`} title={step.why ?? undefined}>
      <Dot n={n} step={step} filled={current} />
      <span className={`whitespace-nowrap text-label ${current ? 'font-semibold' : viewing || step.position === 'done' || step.state ? 'text-text' : 'text-text-muted'}`}>
        {label}
      </span>
      {described && <span className="sr-only">({described})</span>}
    </span>
  );
}

/**
 * The eight stages in a row. Artifact steps show draft, confirmed or stale (with why); a reached
 * step is a button that opens its stage area, and the current stage's button returns to it.
 */
export function Stepper({ build, viewing = build.stage, onSelect }: { build: Build; viewing?: Stage; onSelect?: (stage: Stage) => void }) {
  return (
    <nav aria-label="Build stages">
      <ol className="flex items-center">
        {steps(build).map((step, i) => {
          const open = step.stage === viewing;
          const body = <StepBody n={i + 1} step={step} viewing={open} />;
          return (
            <li
              key={step.stage}
              data-state={step.position}
              data-artifact={step.state ?? undefined}
              aria-current={step.position === 'current' ? 'step' : undefined}
              className="flex items-center"
            >
              {i > 0 && <span aria-hidden="true" className={`mx-1 h-0.5 w-2.5 rounded-full ${step.position !== 'upcoming' ? 'bg-primary' : 'bg-border-strong'}`} />}
              {onSelect && step.reachable && !(open && step.position === 'current') ? (
                <button type="button" onClick={() => onSelect(step.stage)} className={`rounded-full hover:bg-surface-muted ${focusRing}`}>
                  {body}
                </button>
              ) : (
                body
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
