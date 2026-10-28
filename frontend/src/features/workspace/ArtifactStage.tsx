// The four artifact stages (context, outline, design, blueprint) in one frame: load, refetch on
// `artifact.updated`, a read-only summary, and the stage's confirm and secondary actions.
// The context has its editor (14.2), the outline its picker (14.3), the design its picker (14.4)
// and the blueprint its table with each blocked row's Feasibility issue inline (14.5).
import { FileQuestion } from 'lucide-react';
import { useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../../api/client';
import {
  ApiError,
  artifactIssues,
  STAGES,
  type ArtifactName,
  type Blueprint,
  type Build,
  type Context,
  type Design,
  type Outline,
  type Stage,
  type ValidationIssue,
} from '../../api/types';
import { Button } from '../../components/Button';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { LoadingState } from '../../components/Spinner';
import { presetFor } from '../activity/presets';
import { parseStageError, StageErrorActions } from '../trace/stageErrors';
import type { BuildStream, RunErrorNode } from '../activity/useBuildStream';
import { BlueprintTable } from './blueprint/BlueprintTable';
import { IssueSlotContext, IssueSlotProvider, rowResolved } from './blueprint/issueSlots';
import { ContextEditor } from './context/ContextEditor';
import { DesignPicker } from './design/DesignPicker';
import { OutlinePicker, selectedCount } from './outline/OutlinePicker';
import { useReviewLock } from './briefs/reviewLock';
import { GateReason, isReferenceUnapproved, useAnalysisGate } from './reference/gate';
import { StageFrame } from './StageFrame';
import { STAGE_LABELS, staleCause } from './Stepper';

interface Values {
  context: Context;
  outline: Outline;
  design: Design;
  blueprint: Blueprint;
}
type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; value: T | null };

const FETCH: { [K in ArtifactName]: (buildId: string) => Promise<Values[K] | null> } = {
  context: (id) => api.getContext(id),
  outline: (id) => api.getOutline(id),
  design: (id) => api.getDesign(id),
  blueprint: (id) => api.getBlueprint(id),
};

/** Most selected questions a confirm accepts (api.md 2.0, outline/confirm). */
export const MAX_SELECTED = 24;

interface StageCopy {
  lead: string;
  empty: string;
  confirm: string;
  secondary: string;
  /** Stages where the secondary action is allowed. */
  secondaryIn: readonly Stage[];
  /** Runs whose failure shows here, with the action that retries each. */
  runs: readonly RunErrorNode[];
}

const COPY: Record<ArtifactName, StageCopy> = {
  context: {
    lead: 'Check the KPIs, derived fields and thresholds drafted from your data, then confirm.',
    empty: 'The draft shows up here when the context run finishes.',
    confirm: 'Confirm context',
    secondary: 'Redraft',
    secondaryIn: ['connect', 'context'],
    runs: ['context'],
  },
  outline: {
    lead: 'Pick the questions the dashboard answers, then confirm.',
    empty: 'Proposed questions show up here when the outline run finishes.',
    confirm: 'Confirm outline',
    secondary: 'Re-propose',
    secondaryIn: ['outline'],
    runs: ['outline_propose', 'outline_other', 'outline_suggest'],
  },
  design: {
    lead: 'Choose colors, font and page structure, then confirm.',
    empty: 'The design is prefilled when you confirm the outline.',
    confirm: 'Confirm design',
    secondary: 'Reset to preset',
    secondaryIn: ['design'],
    runs: [],
  },
  blueprint: {
    lead: 'Check the chart chosen for each question, then accept to render the prototype.',
    empty: 'The blueprint shows up here when the blueprint run finishes.',
    confirm: 'Accept blueprint',
    secondary: 'Regenerate',
    secondaryIn: ['blueprint', 'prototype'],
    runs: ['blueprint', 'prototype'],
  },
};

/** A late refetch (from an earlier artifact.updated) never replaces a newer revision. */
function newer<T extends { revision: number }>(current: Load<T>, value: T | null): Load<T> {
  if (current.status === 'ready' && current.value && value && value.revision < current.value.revision) return current;
  return { status: 'ready', value };
}

const errorText = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);
const mono = 'font-mono text-label text-text-muted';

function Issues({ issues }: { issues: ValidationIssue[] }) {
  if (issues.length === 0) return null;
  return (
    <ul aria-label="Open issues" className="mt-4 space-y-1 rounded-control border border-danger bg-danger-soft px-3 py-2">
      {issues.map((issue, i) => (
        <li key={i} className="text-body text-text [overflow-wrap:anywhere]">
          <code className={mono}>{issue.path}</code> {issue.message}
        </li>
      ))}
    </ul>
  );
}

type ArtifactStageProps = {
  build: Build;
  name: ArtifactName;
  stream: Pick<BuildStream, 'artifactSeq' | 'running' | 'runErrors'> & Partial<Pick<BuildStream, 'activity' | 'runErrorIds'>>;
  /** The Feasibility panel, under the header. */
  feasibility?: ReactNode;
  /** Blueprint only: feasibility resolved and references ready, so Accept may run. */
  acceptReady: boolean;
  onBuildChange: (build: Build) => void;
  /** More panels at the end of the body (references). */
  children?: ReactNode;
};

/** Mount with `key={name}`: its loaded value belongs to one artifact. */
export function ArtifactStage(props: ArtifactStageProps) {
  // The blueprint table and the Feasibility panel share the blocked rows' issues.
  return (
    <IssueSlotProvider>
      <ArtifactStageBody {...props} />
    </IssueSlotProvider>
  );
}

function ArtifactStageBody({
  build,
  name,
  stream,
  feasibility,
  acceptReady,
  onBuildChange,
  children,
}: ArtifactStageProps) {
  const copy = COPY[name];
  const slotHost = useContext(IssueSlotContext);
  const [load, setLoad] = useState<Load<Values[ArtifactName]>>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [pending, setPending] = useState<'primary' | 'secondary' | null>(null);
  const [actionError, setActionError] = useState<{ message: string; issues: ValidationIssue[] } | null>(null);
  const busy = useRef(false);
  // An editor's PUT is on its way: confirming now would confirm the version before it.
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  // The picker's count, unsaved ticks included.
  const [outlineCount, setOutlineCount] = useState<number | null>(null);
  const mounted = useRef(true);
  // A saved feasibility decision may rewrite the blueprint rows (the live backend does): read it again.
  const seq = build.id + name + stream.artifactSeq[name] + (name === 'blueprint' ? `|${slotHost?.decided ?? 0}` : '');

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // A refetch after artifact.updated keeps the old content on screen until the new one lands.
  useEffect(() => {
    let active = true;
    FETCH[name](build.id).then(
      (value) => {
        if (active) setLoad((current) => newer(current, value));
      },
      (error: unknown) => {
        if (active) setLoad((current) => (current.status === 'ready' ? current : { status: 'error', message: errorText(error, `Couldn't load the ${name}. Try again.`) }));
      },
    );
    return () => {
      active = false;
    };
  }, [build.id, name, seq, attempt]);

  const value = load.status === 'ready' ? load.value : null;
  const state = build.artifacts[name];
  const here = build.stage === name;
  const stageAt = STAGES.indexOf(build.stage);
  const readOnly = build.stage === 'build' || build.stage === 'done';
  // A brief review waits (WorkspaceShell's lock): every action and editor here waits with it.
  const reviewLock = useReviewLock();
  const reviewLockRef = useRef(reviewLock);
  reviewLockRef.current = reviewLock;
  const locked = stream.running !== null || pending !== null || readOnly || reviewLock !== null;
  // A recreate analysis waits for approval (reference/gate): Confirm design and Regenerate/Accept blueprint wait with it.
  const analysisPending = useAnalysisGate()?.pending === true;
  const gated = { primary: analysisPending && (name === 'design' || name === 'blueprint'), secondary: analysisPending && name === 'blueprint' };
  const gatedRef = useRef(gated);
  gatedRef.current = gated;
  const gateId = `${name}-analysis-gate`;

  let valid = value !== null;
  let status: ReactNode = null;
  if (value && name === 'context') {
    const open = (value as Context).issues.length;
    valid = open === 0;
    status = open === 0 ? 'No open issues' : open === 1 ? '1 open issue' : `${open} open issues`;
  } else if (value && name === 'outline') {
    const n = outlineCount ?? selectedCount(value as Outline);
    valid = n >= 1 && n <= MAX_SELECTED;
    status = n > MAX_SELECTED ? `${n} of ${MAX_SELECTED} selected: ${MAX_SELECTED} at most` : `${n} of ${MAX_SELECTED} selected`;
  } else if (value && name === 'design') {
    valid = (value as Design).issues.length === 0;
    if (!valid) status = 'Fix the open issues to confirm';
  } else if (value && name === 'blueprint') {
    const rows = (value as Blueprint).rows;
    const blocked = rows.filter((r) => r.status === 'blocked' && !rowResolved(r.issue_ids, slotHost?.issues ?? null)).length;
    valid = acceptReady && rows.some((r) => r.status === 'ok');
    if (blocked > 0) status = blocked === 1 ? '1 blocked row' : `${blocked} blocked rows`;
    else if (!rows.some((r) => r.status === 'ok')) status = 'Accept needs at least one row that is not blocked';
    else if (!acceptReady) status = 'Accept opens once feasibility and references are ready';
  }
  if (gated.primary) status = <GateReason id={gateId} />;
  // While a run holds the build's lock, the strip's phrase says why everything waits.
  if (stream.running) status = `${presetFor(stream.running).phrases[0]}…`;
  if (reviewLock) status = reviewLock;

  const confirm = (): Promise<unknown> => {
    if (name === 'context') return api.confirmContext(build.id);
    if (name === 'outline') return api.confirmOutline(build.id);
    if (name === 'design') return api.confirmDesign(build.id);
    return api.acceptBlueprint(build.id);
  };
  const secondary = (): Promise<unknown> => {
    if (name === 'context') return api.draftContext(build.id);
    if (name === 'outline') return api.proposeOutline(build.id);
    if (name === 'design') return api.prefillDesign(build.id);
    return api.regenerateBlueprint(build.id);
  };

  const onSavingChange = (next: boolean) => {
    savingRef.current = next;
    setSaving(next);
  };
  const onSaved = async (saved: Values[ArtifactName]) => {
    setLoad((current) => newer(current, saved));
    // An edit in a later stage moved the build back here: read it in case stage.changed was missed.
    if (build.stage === name) return;
    try {
      const next = await api.getBuild(build.id);
      if (mounted.current) onBuildChange(next);
    } catch {
      // The stream's next event or reconnect brings it.
    }
  };

  const act = async (kind: 'primary' | 'secondary') => {
    if (busy.current || savingRef.current || reviewLockRef.current || gatedRef.current[kind]) return;
    busy.current = true;
    setPending(kind);
    setActionError(null);
    try {
      const result = await (kind === 'primary' ? confirm() : secondary());
      if (!mounted.current) return;
      if (name === 'design' && kind === 'secondary') setLoad({ status: 'ready', value: result as Design });
      // The action may have moved the stage: read the build in case its stage.changed was missed.
      try {
        onBuildChange(await api.getBuild(build.id));
      } catch {
        // The stream's next event or reconnect brings it.
      }
    } catch (error) {
      if (!mounted.current) return;
      // The analysis isn't approved after all: the gate's notice already takes focus to the review.
      if (isReferenceUnapproved(error)) return;
      const issues = error instanceof ApiError && error.code === 'artifact_invalid' ? artifactIssues(error) : [];
      // The assessment changed under us: the panel refetches, so the rows show what blocks now.
      if (error instanceof ApiError && error.code === 'feasibility_blocked') slotHost?.requestRefresh();
      setActionError({ message: errorText(error, `${kind === 'primary' ? copy.confirm : copy.secondary} didn't work. Try again.`), issues });
    } finally {
      busy.current = false;
      if (mounted.current) setPending(null);
    }
  };

  const startedRuns = (stream.activity ?? []).map((run) => run.runId);
  const runError = copy.runs.map((node) => ({ node, text: stream.runErrors[node] })).find((e) => e.text);
  const retryNode = runError?.node;
  // A stage limit or used-up repairs (api.md 3.0): the message without its code, and where to look next.
  const stageError = parseStageError(runError?.text);
  const why = state === 'stale' ? staleCause(build, name) : null;

  let body: ReactNode;
  if (load.status === 'loading') body = <LoadingState className="mt-6">Loading the {name}…</LoadingState>;
  else if (load.status === 'error')
    body = <ErrorState className="mt-4" title={`Couldn't load the ${name}`} message={load.message} onRetry={() => { setLoad({ status: 'loading' }); setAttempt((n) => n + 1); }} />;
  else if (value === null) body = <EmptyState framed className="mt-4" icon={<FileQuestion />} title={`No ${name} yet`} description={copy.empty} headingLevel={3} />;
  else if (name === 'context')
    body = <ContextEditor build={build} context={value as Context} disabled={locked} onSaved={(saved) => void onSaved(saved)} onSavingChange={onSavingChange} />;
  else if (name === 'outline')
    body = <OutlinePicker build={build} outline={value as Outline} disabled={locked} onSaved={(saved) => void onSaved(saved)} onSavingChange={onSavingChange} onCountChange={setOutlineCount} startedRuns={startedRuns} />;
  else if (name === 'design')
    body = <DesignPicker build={build} design={value as Design} disabled={locked} onSaved={(saved) => void onSaved(saved)} onSavingChange={onSavingChange} />;
  else body = <BlueprintTable build={build} blueprint={value as Blueprint} outlineSeq={stream.artifactSeq.outline} />;

  return (
    <StageFrame
      title={STAGE_LABELS[name]}
      lead={copy.lead}
      state={state}
      why={why ? `Changed: ${STAGE_LABELS[why]}` : null}
      revision={value?.revision ?? null}
      status={status}
      secondary={
        <Button disabled={locked || saving || gated.secondary || !copy.secondaryIn.includes(build.stage)} aria-describedby={gated.secondary ? gateId : undefined} loading={pending === 'secondary'} onClick={() => void act('secondary')}>
          {copy.secondary}
        </Button>
      }
      primary={
        <Button variant="primary" disabled={locked || saving || gated.primary || !here || !valid} aria-describedby={gated.primary ? gateId : undefined} loading={pending === 'primary'} onClick={() => void act('primary')}>
          {copy.confirm}
        </Button>
      }
    >
      {feasibility}
      {stageAt > STAGES.indexOf(name) && !readOnly && (
        <p className="mt-4 rounded-control bg-surface-muted px-3 py-2 text-body text-text">
          You reopened this step. Editing it moves the build back here and marks the later steps stale.
        </p>
      )}
      {runError && retryNode && (
        <ErrorState
          className="mt-4"
          title={retryNode === 'prototype' ? "Couldn't render the prototype" : `The ${STAGE_LABELS[name].toLowerCase()} run failed`}
          message={stageError?.message ?? runError.text}
          actions={stageError && <StageErrorActions error={stageError} runId={stream.runErrorIds?.[retryNode]} />}
          onRetry={() => void act(retryNode === 'prototype' ? 'primary' : 'secondary')}
          retryDisabled={locked || (retryNode === 'prototype' ? gated.primary || !here || !valid : gated.secondary || !copy.secondaryIn.includes(build.stage))}
        />
      )}
      {actionError && (
        <div role="alert" className="mt-4">
          <p className="text-body text-danger">{actionError.message}</p>
          <Issues issues={actionError.issues} />
        </div>
      )}
      {body}
      {children}
    </StageFrame>
  );
}
