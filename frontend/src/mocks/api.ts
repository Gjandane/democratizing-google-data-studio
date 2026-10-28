// Fixture-backed fake of the backend API (VITE_MOCK=1, and every test). Same signatures as
// httpApi in src/api/client.ts; state is in memory, seeded from ../contracts/fixtures/api/.
// Long-running actions answer at once with a run id and play their events on the fake stream.
import type { ApiClient } from '../api/client';
import {
  ApiError,
  ARTIFACTS,
  type ArtifactName,
  type Assessment,
  type Blueprint,
  type BriefReview,
  type BuildCost,
  type Context,
  type Design,
  type DesignPage,
  type DesignPages,
  type PageBrief,
  type RunCalls,
  type SettingsUpdate,
  type StageId,
  STAGE_IDS,
  type Issue,
  type Outline,
  type OutlineQuestion,
  type ValidationIssue,
  type ColumnSpec,
  type GenerationRequest,
  type GenerationStatus,
  isGenerationSpec,
  problemsOf,
  type Proposal,
  referenceValidation,
  type ReferenceSet,
  type ReferenceAnalysis,
  type ReferenceItem,
  isArchetype,
  isComment,
  isMode,
  oversizeError,
  type Build,
  type BuildSummary,
  type EngineStatus,
  type Message,
  type OpFinished,
  type RunAccepted,
  type Session,
  type Settings,
  type Source,
  type Stage,
  type SyntheticDataset,
  syntheticOversizeError,
  type Trace,
} from '../api/types';
import { newIssues, validateSettings } from '../features/settings/stageSettings';
import { emit } from './events';
import { clone, fixtures } from './fixtures';
import { mockFrame } from './frame';

const isTest = import.meta.env.MODE === 'test';
/** Delay before each response, so loading states show in the dev server. */
const LATENCY_MS = isTest ? 0 : 250;
/** Delay between the events of one run. */
const STEP_MS = isTest ? 0 : 400;
/** Delay between the ops of a build run, slow enough to watch them tick. */
const BUILD_STEP_MS = isTest ? 0 : 1200;

export type MockBuildOutcome = 'ok' | 'partial' | 'failed';
/** A 503 the mock answers on every action of that kind, whatever the settings say. */
export type MockServiceFault = 'llm_unavailable' | 'gcp_not_configured' | null;
/** The staged workflow's runs (api.md 2.0 `node` values). */
type StagedNode = 'context' | 'outline_propose' | 'outline_other' | 'outline_suggest' | 'blueprint' | 'prototype';
/** The runs the mock can fail (setMockRunFailure). */
export type MockFailingNode = StagedNode | 'revise' | 'synthetic_schema' | 'synthetic_generate';

/** The four artifacts of a build; null until first written. */
interface Artifacts {
  context: Context | null;
  outline: Outline | null;
  design: Design | null;
  blueprint: Blueprint | null;
}

/** The access code the mock accepts when the gate is on (setMockSession). */
export const MOCK_ACCESS_CODE = 'mock-access-code';

interface MockState {
  assessments: Map<string, Assessment>;
  assessmentBusy: Set<string>;
  pendingIssueIds: Map<string, Set<string>>;
  references: Map<string, ReferenceSet>;
  referenceFiles: Map<string, string>;
  referenceBusy: Set<string>;
  proposals: Map<string, Proposal>;
  /** Generation requests by `<build id>:<generation_key>`: the canonical body and its job. */
  generations: Map<string, { body: string; job: GenerationStatus }>;
  datasets: Map<string, SyntheticDataset[]>;
  syntheticBusy: Set<string>;
  session: Session;
  builds: Map<string, Build>;
  artifacts: Map<string, Artifacts>;
  /** Builds with a staged action running (api.md 2.0: one action per build at a time). */
  stagedBusy: Set<string>;
  messages: Map<string, Message[]>;
  settings: Settings;
  /** Per build: the published pages and the pending brief review (api.md 3.0); filled on first read. */
  designPages: Map<string, DesignPages>;
  /** Consumed reviews by `<build id>:<review_id>` with the run their approval started, so a repeated approve answers the same run. */
  approvedReviews: Map<string, string>;
  traces: Trace[];
  engine: EngineStatus;
  engineBusy: boolean;
  buildOutcome: MockBuildOutcome;
  screencast: boolean;
  serviceFault: MockServiceFault;
  /** Nodes whose next runs fail, with their `run.finished` error text (null: no text). */
  runFailures: Partial<Record<MockFailingNode, string | null>>;
  /** Blueprint drafts block the ratio KPI row (q2), as blueprint.blocked.json does. */
  blueprintBlocked: boolean;
  nextSeq: number;
}

function seed(): MockState {
  const builds = new Map<string, Build>();
  for (const build of [fixtures.build, fixtures.buildDone]) builds.set(build.id, clone(build));
  return {
    assessments: new Map([fixtures.build, fixtures.buildDone].map((build) => [build.id, { id: `assessment_${build.id}`, state: 'ready', input_digest: `digest_${build.id}`, prototype_stale: false, issues: [], pending_comments: null }])),
    assessmentBusy: new Set(),
    pendingIssueIds: new Map(),
    references: new Map(),
    referenceFiles: new Map(),
    referenceBusy: new Set(),
    proposals: new Map(),
    generations: new Map(),
    datasets: new Map(),
    syntheticBusy: new Set(),
    session: { required: false, ok: true },
    builds,
    // Both fixture builds have all four artifacts confirmed.
    artifacts: new Map([fixtures.build, fixtures.buildDone].map((build) => [build.id, {
      context: clone(fixtures.context), outline: clone(fixtures.outline), design: clone(fixtures.design), blueprint: clone(fixtures.blueprint),
    }])),
    stagedBusy: new Set(),
    messages: new Map([[fixtures.build.id, clone(fixtures.messages)]]),
    settings: clone(fixtures.settings),
    designPages: new Map(),
    approvedReviews: new Map(),
    traces: clone(fixtures.traces),
    engine: clone(fixtures.engineStatusLocal),
    engineBusy: false,
    buildOutcome: 'ok',
    screencast: true,
    serviceFault: null,
    runFailures: {},
    blueprintBlocked: false,
    nextSeq: 0x1000,
  };
}

let state = /* @__PURE__ */ seed();
const runTimers = new Set<ReturnType<typeof setTimeout>>();
const blobUrls = new Map<string, string>();

/** Back to the fixtures; pending run events are dropped. For tests. */
export function resetMockState(): void {
  for (const timer of runTimers) clearTimeout(timer);
  runTimers.clear();
  state = seed();
}

/**
 * Sets what the engine reports next, over the current status (signed in or not, local or agent
 * mode, agent connected or not). For tests and the dev server.
 */
export function setMockEngine(status: Partial<EngineStatus>): void {
  state.engine = { ...state.engine, ...status };
}

/** Turns the access-code gate on or off; `{required: true, ok: false}` also ends a session. For tests and the dev server. */
export function setMockSession(session: Session): void {
  state.session = { ...session };
}

/** Sets how the next build run ends. For tests and the dev server. */
export function setMockBuildOutcome(outcome: MockBuildOutcome): void {
  state.buildOutcome = outcome;
}

/** Turns the build run's screencast frames on or off (default on). For tests and the dev server. */
export function setMockScreencast(on: boolean): void {
  state.screencast = on;
}

/** Changes the stored settings (for example no key or no project). For tests and the dev server. */
export function setMockSettings(settings: Partial<Settings>): void {
  Object.assign(state.settings, settings);
}

/** Replaces a build's design pages and pending brief review (pass `review` to wait for one) without events. For tests and previews. */
export function setMockDesignPages(buildId: string, pages: DesignPages): void {
  findBuild(buildId);
  state.designPages.set(buildId, clone(pages));
}

/** Makes model actions or Google Cloud actions answer 503 until reset with null. For tests and the dev server. */
export function setMockServiceFault(fault: MockServiceFault): void {
  state.serviceFault = fault;
}

/**
 * Makes every next `node` run fail with `error` as its `run.finished` text (null: no text), until
 * reset with undefined. A failed staged run writes nothing; a failed accept stays in Blueprint. For tests and the dev server.
 */
export function setMockRunFailure(node: MockFailingNode, error: string | null | undefined): void {
  if (error === undefined) delete state.runFailures[node];
  else state.runFailures[node] = error;
}

/** The issue a blocked ratio row names (blueprint.blocked.json): the code-built alternative splits it (dashboard-intent.md 1.2). */
export const MOCK_RATIO_ISSUE_ID = 'i_aov_ratio';
export function mockRatioIssue(): Issue {
  return {
    id: MOCK_RATIO_ISSUE_ID,
    requirement: 'Show the average order value (net revenue / orders) as one scorecard.',
    status: 'unsupported_app',
    reason: 'A view column cannot hold SUM(revenue)/COUNT(DISTINCT order_id), and the recipe has no calculated-field op for it.',
    evidence: ['contracts/recipe.md#Operations', 'context:avg_order_value'],
    alternatives: [{ id: 'alt_aov_split', label: 'Show net revenue and orders as two scorecards' }],
    resolution: 'unresolved',
  };
}

/**
 * Makes every next blueprint draft block the ratio row (q2) with mockRatioIssue, until reset with
 * false. A decision on the issue is kept: a later draft shows the alternative (accepted) or drops
 * the row (dropped). For tests and the dev server.
 */
export function setMockBlueprintBlocked(on: boolean): void {
  state.blueprintBlocked = on;
}

/** Changes a stored build (its stage, artifact states, spec version...) without events. For tests and previews. */
export function patchMockBuild(buildId: string, patch: Partial<Build>): void {
  Object.assign(findBuild(buildId), clone(patch));
}

/** Replaces one stored artifact (null removes it) without events. For tests and previews. */
export function setMockArtifact<K extends ArtifactName>(buildId: string, name: K, value: Artifacts[K]): void {
  artifactsOf(buildId)[name] = clone(value);
}

/** Replaces the current version's reference set (null removes it) without events. For tests and previews. */
export function setMockReferences(buildId: string, set: ReferenceSet | null): void {
  const key = `${buildId}:${findBuild(buildId).current_version}`;
  if (set) state.references.set(key, clone(set));
  else state.references.delete(key);
}

/** Overrides feasibility without mutating shared fixtures. For tests and previews. */
export function setMockAssessment(buildId: string, assessment: Assessment, pendingIssueIds?: string[]): void {
  if (assessment.pending_comments) state.pendingIssueIds.set(buildId, new Set(pendingIssueIds ?? assessment.issues.map((issue) => issue.id)));
  state.assessments.set(buildId, clone(assessment));
}

const uncheckedAssessment = (): Assessment => ({ id: null, state: 'unchecked', input_digest: null, prototype_stale: false, issues: [], pending_comments: null });
const currentAssessment = (id: string): Assessment => {
  findBuild(id);
  return state.assessments.get(id) ?? uncheckedAssessment();
};

/** Synthetic writes: connect only, no sources, no other action running (contracts/synthetic-data.md 1.2). */
function requireSyntheticWrite(build: Build): void {
  requireNoReview(build);
  requireStage(build, ['connect'], 'Sample data can only be added in Connect, before the context.');
  if (build.sources.length > 0) {
    throw new ApiError(409, 'synthetic_requires_empty_build', 'This build already has data. Start a new dashboard to use sample data.');
  }
  if ([state.syntheticBusy, state.referenceBusy, state.assessmentBusy].some((busy) => busy.has(build.id))) {
    throw new ApiError(409, 'action_in_progress', 'Wait for the current action to finish.');
  }
}

/** The first `invalid_generation_spec` problem, as the backend reports it: `{field, reason}` relative to the spec. */
function specProblem(spec: unknown): { field: string; reason: string } | null {
  const [first] = problemsOf(isGenerationSpec, spec, '$');
  if (first) {
    const at = first.indexOf(': ');
    return { field: first.slice(0, at).replace(/^\$\.?/, '') || 'spec', reason: first.slice(at + 2) };
  }
  const { row_count, seed, columns } = spec as { row_count: number; seed: number; columns: ColumnSpec[] };
  if (row_count < 1 || row_count > 100_000) return { field: 'row_count', reason: 'must be between 1 and 100000' };
  if (seed < 0 || seed > 0xffffffff) return { field: 'seed', reason: 'must be between 0 and 4294967295' };
  if (columns.length < 1 || columns.length > 40) return { field: 'columns', reason: 'must have 1 to 40 columns' };
  const seen = new Set<string>();
  for (const [i, column] of columns.entries()) {
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(column.name)) return { field: `columns[${i}].name`, reason: 'must be snake_case: a lowercase letter, then lowercase letters, digits or _' };
    if (seen.has(column.name)) return { field: `columns[${i}].name`, reason: 'must be unique' };
    seen.add(column.name);
    const g = column.generator;
    if ((g.kind === 'integer' || g.kind === 'decimal') && g.max < g.min) return { field: `columns[${i}].generator.max`, reason: 'must be >= min' };
  }
  return null;
}

/** The Source a successful generation registers; column types follow the accepted spec. */
function syntheticSource(build: Build, spec: GenerationRequest['spec']): Source {
  const { gcp_project_id, bq_dataset } = state.settings;
  return {
    id: nextId('s'),
    kind: 'synthetic',
    name: 'Synthetic sample data',
    bq_table: `${gcp_project_id || 'my-gcp-project'}.${bq_dataset}.syn_${build.id}`,
    row_count: spec.row_count,
    columns: spec.columns.map((column) => ({
      name: column.name,
      type: column.type === 'integer' ? 'number' : column.type,
      sample: column.generator.kind === 'choice' ? column.generator.values.slice(0, 2).map(String) : [],
    })),
  };
}

const failureOf = (node: MockFailingNode) => () => (node in state.runFailures ? { error: state.runFailures[node] ?? null } : null);

// ---------- Helpers ----------

const nextId = (prefix: 'b' | 'm' | 'r' | 's') => `${prefix}_${(state.nextSeq++).toString(16).padStart(12, '0')}`;
const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

/** Runs `answer` after the latency and resolves with a copy, so callers never hold mock state. */
function respond<T>(answer: () => T): Promise<T> {
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      try {
        resolve(clone(answer()));
      } catch (error) {
        reject(error);
      }
    }, LATENCY_MS);
  });
}

function findBuild(buildId: string): Build {
  const build = state.builds.get(buildId);
  if (!build) throw new ApiError(404, 'build_not_found', 'This build no longer exists. Open another one from History.', { build_id: buildId });
  return build;
}

function requireStage(build: Build, allowed: Stage[], message: string): void {
  if (!allowed.includes(build.stage)) throw new ApiError(409, 'wrong_stage', message, { stage: build.stage });
}

/** Actions that call the model: 503 `llm_unavailable` without a key, or when the call fails. */
function requireModel(): void {
  if (state.serviceFault === 'llm_unavailable' || !state.settings.google_api_key_set) {
    throw new ApiError(503, 'llm_unavailable', 'The model could not be reached. Open Settings, check the API key and model names, then try again.');
  }
}

/** Actions that touch BigQuery or Cloud Storage: 503 `gcp_not_configured` without a project. */
function requireGcp(): void {
  if (state.serviceFault === 'gcp_not_configured' || state.settings.gcp_project_id.trim() === '') {
    throw new ApiError(503, 'gcp_not_configured', 'No GCP project is set. Open Settings, enter the project, then try again.');
  }
}

const invalid = (code: string, message: string, detail: Record<string, unknown> = {}) => new ApiError(422, code, message, detail);

function touch(build: Build): void {
  build.updated_at = now();
}

function setStage(build: Build, stage: Stage): void {
  build.stage = stage;
  touch(build);
  emit(build.id, { name: 'stage.changed', data: { stage } });
}

function announce(build: Build): void {
  emit(build.id, { name: 'build.updated', data: { build: clone(build) } });
}

/** Plays `steps` one STEP_MS apart. */
function schedule(steps: Array<() => void>, stepMs = STEP_MS): void {
  steps.forEach((step, i) => {
    const timer = setTimeout(() => {
      runTimers.delete(timer);
      step();
    }, stepMs * (i + 1));
    runTimers.add(timer);
  });
}

/** A run of `node` on the build's stream: run.started, the steps, run.finished. */
function startRun(
  build: Build,
  node: string,
  steps: (runId: string) => Array<() => void> = () => [],
  options: { stepMs?: number; failure?: () => { error: string | null } | null; finishInSteps?: boolean } = {},
): RunAccepted {
  const run_id = nextId('r');
  const buildId = build.id;
  const startedAt = Date.now();
  // Every mocked run reports growing token totals, before each step so run.finished follows the last.
  let input = 0;
  let output = 0;
  const usage = () => {
    input += 3120;
    output += 455;
    emit(buildId, { name: 'run.usage', data: { run_id, node, input_tokens: input, output_tokens: output } });
  };
  schedule(
    [
      () => {
        emit(buildId, { name: 'run.started', data: { run_id, node } });
        usage();
      },
      ...steps(run_id).map((step) => () => {
        usage();
        step();
      }),
      ...(options.finishInSteps
        ? []
        : [
            () => {
              const failure = options.failure?.() ?? null;
              // Trace records the run, so "View model calls" finds it.
              state.traces.push({
                run_id,
                build_id: buildId,
                node,
                model: state.settings.stages.routine.model,
                input_tokens: input,
                output_tokens: output,
                latency_ms: Date.now() - startedAt,
                tool_calls: 0,
                status: failure ? 'error' : 'ok',
                error: failure?.error ?? null,
                started_at: new Date(startedAt).toISOString().replace(/\.\d{3}Z$/, 'Z'),
              });
              emit(buildId, { name: 'run.finished', data: { run_id, node, status: failure ? 'error' : 'ok', error: failure?.error ?? null } });
            },
          ]),
    ],
    options.stepMs,
  );
  return { run_id };
}

/** Steps that stream an assistant message in three deltas, then store it. */
function streamAssistant(buildId: string, text: string, node: string): Array<() => void> {
  const id = nextId('m');
  const words = text.split(/(?<= )/);
  const third = Math.ceil(words.length / 3);
  const chunks = [0, 1, 2].map((i) => words.slice(i * third, (i + 1) * third).join('')).filter(Boolean);
  return [
    ...chunks.map((chunk) => () => emit(buildId, { name: 'message.delta', data: { message_id: id, text: chunk } })),
    () => {
      const message: Message = { id, role: 'assistant', text, node, created_at: now() };
      state.messages.set(buildId, [...(state.messages.get(buildId) ?? []), message]);
      emit(buildId, { name: 'message.done', data: { message: clone(message) } });
    },
  ];
}

function summary(build: Build): BuildSummary {
  const { id, title, archetype, stage, updated_at, report_url } = build;
  return { id, title, archetype, stage, updated_at, report_url };
}

const newestFirst = <T>(items: T[], key: (item: T) => string) => [...items].sort((a, b) => key(b).localeCompare(key(a)));

function newSource(build: Build, kind: Source['kind'], name: string): Source {
  const template = fixtures.build.sources[0];
  const table = name.replace(/\.csv$/i, '').toLowerCase().replace(/[^a-z0-9]+/g, '_');
  const { gcp_project_id, bq_dataset } = state.settings;
  return {
    id: nextId('s'),
    kind,
    name,
    bq_table: `${gcp_project_id || 'my-gcp-project'}.${bq_dataset}.src_${build.id}_${table}`,
    row_count: template?.row_count ?? 0,
    columns: clone(template?.columns ?? []),
  };
}

function addSources(build: Build, sources: Source[]): void {
  build.sources.push(...sources);
  touch(build);
  announce(build);
}

const opName = (line: string) => (line.split(' ')[1] ?? 'op').replace(/-/g, '_');

const agentMode = () => state.engine.mode === 'agent';

/** Settings the hosted app lets the user change (contracts/api.md, PUT /api/settings). */
const UNLOCKED_SETTINGS = new Set(['stages', 'fallback_model', 'review_briefs']);

/** Calls that work without the access code (contracts/api.md, Access), plus the URL builders. */
const UNGATED = new Set(['health', 'getSession', 'createSession', 'prototypeUrl', 'fileUrl', 'syntheticCsvUrl']);

/** Every other call answers `401 access_required` while the gate is on and the session isn't valid. */
function gated(client: ApiClient): ApiClient {
  const wrapped: Record<string, unknown> = {};
  for (const [name, fn] of Object.entries(client) as Array<[string, (...args: unknown[]) => unknown]>) {
    wrapped[name] = UNGATED.has(name)
      ? fn
      : (...args: unknown[]) =>
          state.session.required && !state.session.ok
            ? Promise.reject(new ApiError(401, 'access_required', 'Enter the access code to use the app.'))
            : fn(...args);
  }
  return wrapped as unknown as ApiClient;
}

// ---------- Staged workflow (api.md 2.0) ----------

/** The stages before the engine run: references, feasibility and artifact edits work here. */
const BEFORE_BUILD: Stage[] = ['connect', 'context', 'outline', 'design', 'blueprint', 'prototype'];

function artifactsOf(buildId: string): Artifacts {
  let artifacts = state.artifacts.get(buildId);
  if (!artifacts) {
    artifacts = { context: null, outline: null, design: null, blueprint: null };
    state.artifacts.set(buildId, artifacts);
  }
  return artifacts;
}

/** Stores the next revision of an artifact; `artifact.updated` follows every write. */
function save<K extends ArtifactName>(build: Build, name: K, value: NonNullable<Artifacts[K]>): NonNullable<Artifacts[K]> {
  const artifacts = artifactsOf(build.id);
  value.revision = (artifacts[name]?.revision ?? 0) + 1;
  artifacts[name] = value;
  emit(build.id, { name: 'artifact.updated', data: { artifact: name, revision: value.revision } });
  return value;
}

/**
 * An edit of `name`: it becomes a draft, every later artifact that exists goes stale, and the stage
 * moves back to that artifact's stage (api.md 2.0 Stage rules). The spec and prototype stay.
 */
function markEdited(build: Build, name: ArtifactName): void {
  build.artifacts[name] = 'draft';
  for (const later of ARTIFACTS.slice(ARTIFACTS.indexOf(name) + 1)) {
    if (build.artifacts[later] !== 'missing') build.artifacts[later] = 'stale';
  }
  if (build.stage !== name) setStage(build, name);
  else touch(build);
  announce(build);
}

/** Edits of `name`: allowed from its own stage up to prototype, never in build or done. */
function requireEditable(build: Build, name: ArtifactName): void {
  const at = BEFORE_BUILD.indexOf(build.stage);
  if (at < BEFORE_BUILD.indexOf(name)) {
    const message = build.stage === 'build' ? 'Wait for the build to finish.' : build.stage === 'done' ? 'Start a new version to change this dashboard.' : `Finish the earlier steps before the ${name}.`;
    throw new ApiError(409, 'wrong_stage', message, { stage: build.stage });
  }
}

function requireIdle(build: Build): void {
  if (state.stagedBusy.has(build.id)) throw new ApiError(409, 'action_in_progress', 'Wait for the current action to finish.');
  requireNoReview(build);
}

/** api.md 3.0: while a brief review waits, every other mutating build route refuses (reads and settings still work). */
function requireNoReview(build: Build): void {
  const review = state.designPages.get(build.id)?.review;
  if (review) throw new ApiError(409, 'brief_review_pending', 'Approve or cancel the brief review first.', { review_id: review.review_id });
}

/** dashboard-intent.md 1.3 gate: a recreate set whose analysis isn't approved (pending, or null before 1.3) blocks design/confirm, blueprint, recipe and run. */
function requireReferenceApproved(build: Build): void {
  const reference = state.references.get(`${build.id}:${build.current_version}`);
  if (reference?.mode === 'recreate' && reference.analysis?.state !== 'approved') {
    throw new ApiError(409, 'reference_unapproved', 'Review and approve the reference analysis first.', { reference_set_id: reference.id });
  }
}

/** The code-written analysis summary, e.g. "3 charts and 1 control can be native Data Studio components; 2 items stay static art." */
function analysisSummary(items: ReferenceItem[]): string {
  const native = items.filter((item) => item.disposition === 'native');
  const controls = native.filter((item) => item.kind === 'control').length;
  const charts = native.length - controls;
  const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const parts = [charts && count(charts, 'chart', 'charts'), controls && count(controls, 'control', 'controls')].filter(Boolean);
  const head = parts.length > 0 ? `${parts.join(' and ')} can be native Data Studio components` : 'No item can be a native Data Studio component';
  const statics = items.length - native.length;
  return statics > 0 ? `${head}; ${count(statics, 'item stays', 'items stay')} static art.` : `${head}.`;
}

/** Code checks of a saved split: a native item needs a type from `allowed_types`; the note is at most 1000 chars. */
function analysisIssues(analysis: ReferenceAnalysis): ValidationIssue[] {
  const issues: ValidationIssue[] = analysis.items.flatMap((item, i) =>
    item.disposition === 'native' && (item.type === null || !analysis.allowed_types.includes(item.type))
      ? [{ path: `/items/${i}/type`, message: 'Choose a Data Studio component type, or keep this item as static art.' }]
      : [],
  );
  if (analysis.note.length > 1000) issues.push({ path: '/note', message: 'Keep the note to at most 1000 characters.' });
  return issues;
}

/** The current recreate set and its analysis, for an analysis edit or approval. */
function requireAnalysis(build: Build): ReferenceSet & { analysis: ReferenceAnalysis } {
  requireNoReview(build);
  requireStage(build, BEFORE_BUILD, 'Start a new version to change references.');
  if (state.referenceBusy.has(build.id) || state.stagedBusy.has(build.id)) throw new ApiError(409, 'action_in_progress', 'Wait for the current action to finish.');
  const reference = state.references.get(`${build.id}:${build.current_version}`);
  if (!reference?.analysis) throw new ApiError(404, 'reference_not_found', 'Upload a dashboard screenshot to recreate first.');
  return reference as ReferenceSet & { analysis: ReferenceAnalysis };
}

function requireAnalysisRevision(analysis: ReferenceAnalysis, revision: number, verb: string): void {
  if (revision !== analysis.revision) {
    throw new ApiError(409, 'reference_analysis_conflict', `The analysis changed. Reload it, then ${verb} again.`, { revision: analysis.revision });
  }
}

/** The prototype run's result: the plan docs, the next spec version and the Prototype stage (api.md 2.0). */
function publishPrototype(build: Build): void {
  const id = build.id;
  build.artifacts.blueprint = 'confirmed';
  build.docs = clone(fixtures.build.docs);
  emit(id, { name: 'docs.updated', data: { docs: clone(build.docs) } });
  build.spec_version = (build.spec_version ?? 0) + 1;
  emit(id, { name: 'prototype.updated', data: { spec_version: build.spec_version } });
  setStage(build, 'prototype');
  announce(build);
  // A build that had no pages yet gets the fixture's layout once its first prototype is published.
  const pages = pagesOf(build);
  if (pages.pages.length === 0) pages.pages = clone(fixtures.designPages.pages);
  pages.version = build.current_version;
  pages.spec_version = build.spec_version;
}

// ---------- Stage settings and design briefs (api.md 3.0) ----------

const noPages = (build: Build): DesignPages => ({ version: build.current_version, spec_version: null, pages: [], review: null });

/** The build's design pages: the fixture's once it has a spec, until a test or a review replaces them. */
function pagesOf(build: Build): DesignPages {
  let pages = state.designPages.get(build.id);
  if (!pages) {
    pages = build.spec_version === null ? noPages(build) : clone(fixtures.designPages);
    state.designPages.set(build.id, pages);
  }
  return pages;
}

/** A value that changes with the content: the mock needs a stable stand-in for the canonical JSON's sha256, not a real digest. */
function fakeSha256(text: string): string {
  // Eight FNV-1a style chunks of 8 hex digits, each seeded differently and mixing every character.
  let out = '';
  for (let chunk = 0; chunk < 8; chunk++) {
    let hash = (0x811c9dc5 ^ Math.imul(chunk + 1, 0x9e3779b1)) >>> 0;
    for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619) >>> 0;
    out += hash.toString(16).padStart(8, '0');
  }
  return out;
}

/** The code's readable rendering of a brief (the shape of the contract's `markdown`). */
function briefMarkdown(brief: PageBrief, components: BriefReview['components']): string {
  const slots = brief.slots.map((slot) => {
    const component = components.find((c) => c.id === slot.id);
    return `## ${slot.id}${component ? ` (${component.type}: ${component.label})` : ''}\n\n${slot.treatment.trim()}\n\n`;
  });
  return `# Page ${brief.page} brief\n\n## Overall\n\n${brief.overall.trim()}\n\n${slots.join('')}`.trimEnd() + '\n';
}

/** The issues the backend's content checks would report for an edited brief (paths into the PageBrief). */
function briefIssues(brief: PageBrief, components: BriefReview['components']): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  if (brief.overall.trim() === '') issues.push({ path: '/overall', message: 'Write the overall look of this page.' });
  const ids = brief.slots.map((slot) => slot.id);
  if (ids.length !== components.length || components.some((c, i) => ids[i] !== c.id)) {
    issues.push({ path: '/slots', message: "Keep one treatment for each of this page's components." });
  }
  brief.slots.forEach((slot, i) => {
    if (slot.treatment.trim() === '') {
      const label = components.find((c) => c.id === slot.id)?.label ?? slot.id;
      issues.push({ path: `/slots/${i}/treatment`, message: `Write a treatment for ${label}.` });
    }
  });
  return issues;
}

/** The run stops before this page's HTML: `brief.review`, then `run.finished` ok (the steps' caller adds it). */
function pauseForReview(build: Build, action: BriefReview['action']): void {
  const pages = pagesOf(build);
  const review = clone(fixtures.designPagesReview.review!);
  review.review_id = `br_${(state.nextSeq++).toString(16).padStart(12, '0')}`;
  review.action = action;
  review.created_at = now();
  pages.review = review;
  emit(build.id, { name: 'brief.review', data: { review_id: review.review_id, page: review.page, pages: review.pages } });
}

/** Approve: the reviewed page is generated and published under the review's node. */
function publishReviewed(build: Build, review: BriefReview): RunAccepted {
  state.stagedBusy.add(build.id);
  return startRun(build, review.action, (runId) => [
    () => emit(build.id, { name: 'node.progress', data: { run_id: runId, node: review.action, text: 'Writing the page HTML' } }),
    () => {
      const pages = pagesOf(build);
      const page: DesignPage = { page: review.page, layout: 'designed', standard_reason: null, brief: clone(review.brief), html_model: fixtures.settings.stages.html_no_reference.model };
      pages.pages = [...pages.pages.filter((p) => p.page !== page.page), page].sort((a, b) => a.page - b.page);
      if (review.action === 'prototype') publishPrototype(build);
      else {
        build.spec_version = (build.spec_version ?? 0) + 1;
        emit(build.id, { name: 'prototype.updated', data: { spec_version: build.spec_version } });
        touch(build);
        announce(build);
      }
      pages.spec_version = build.spec_version;
    },
    () => state.stagedBusy.delete(build.id),
  ]);
}

/** Fields PUT /api/settings knows; anything else is an issue (api.md 3.0, Validation). */
const SETTINGS_KEYS = new Set(['stages', 'fallback_model', 'review_briefs', 'gcp_project_id', 'bq_dataset', 'bq_location', 'gcs_bucket', 'google_api_key']);

/**
 * Issues of a merged Settings update (api.md 3.0, Validation): unknown keys, plus every check on the
 * merged whole that the stored Settings didn't already fail (stored failures never block a PUT).
 */
function settingsUpdateIssues(current: Settings, next: Settings, update: SettingsUpdate): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  for (const key of Object.keys(update)) {
    if (!SETTINGS_KEYS.has(key)) issues.push({ path: `/${key}`, message: 'This is not a setting.' });
  }
  for (const [stage, patch] of Object.entries(update.stages ?? {})) {
    if (!(STAGE_IDS as readonly string[]).includes(stage)) {
      issues.push({ path: `/stages/${stage}`, message: 'This is not a stage.' });
      continue;
    }
    const profile = current.stages[stage as StageId] as unknown as Record<string, unknown>;
    for (const key of Object.keys(patch ?? {})) {
      if (!(key in profile)) issues.push({ path: `/stages/${stage}/${key}`, message: 'This stage has no such setting.' });
    }
  }
  if (issues.length > 0) return issues;
  const { capabilities } = fixtures;
  return newIssues(validateSettings(next.stages, next.fallback_model, capabilities), validateSettings(current.stages, current.fallback_model, capabilities));
}

/** A build made before 2.0: all artifacts missing, with a spec. */
const isLegacy = (build: Build) => ARTIFACTS.every((name) => build.artifacts[name] === 'missing') && build.spec_version !== null;

/** `recipe` and `run` need all four artifacts confirmed; a pre-2.0 build is exempt. */
function requireConfirmed(build: Build): void {
  if (!isLegacy(build) && ARTIFACTS.some((name) => build.artifacts[name] !== 'confirmed')) {
    throw new ApiError(409, 'wrong_stage', 'Confirm every step, then build.', { stage: build.stage });
  }
}

const artifactInvalid = (issues: ValidationIssue[]) =>
  new ApiError(409, 'artifact_invalid', 'Fix the open issues, then confirm again.', { issues });

function requireArtifact<K extends ArtifactName>(build: Build, name: K): NonNullable<Artifacts[K]> {
  const value = artifactsOf(build.id)[name];
  if (!value) throw new ApiError(409, 'wrong_stage', `There is no ${name} yet.`, { stage: build.stage });
  return value as NonNullable<Artifacts[K]>;
}

const PROGRESS: Record<StagedNode, string> = {
  context: 'Reading the data profile',
  outline_propose: 'Proposing questions',
  outline_other: 'Reading your question',
  outline_suggest: 'Suggesting questions',
  blueprint: 'Drafting the blueprint',
  prototype: 'Laying out the pages',
};

/** A staged run: holds the build's action lock; a failing node (setMockRunFailure) writes nothing. */
function stagedRun(build: Build, node: StagedNode, steps: (runId: string) => Array<() => void>): RunAccepted {
  state.stagedBusy.add(build.id);
  const failed = failureOf(node)();
  return startRun(
    build,
    node,
    (runId) => [
      () => emit(build.id, { name: 'node.progress', data: { run_id: runId, node, text: PROGRESS[node] } }),
      ...(failed ? [] : steps(runId)),
      () => state.stagedBusy.delete(build.id),
    ],
    { failure: () => failed },
  );
}

const columnNames = (build: Build) => new Set(build.sources.flatMap((source) => source.columns.map((column) => column.name)));

/** The code checks of a Context: known fields, exactly one of measure and ratio, known ratio KPIs. */
function contextIssues(build: Build, context: Omit<Context, 'revision' | 'issues'>): ValidationIssue[] {
  const fields = columnNames(build);
  for (const derived of context.derived_fields) fields.add(derived.name);
  const kpiIds = new Set(context.kpis.map((kpi) => kpi.id));
  const issues: ValidationIssue[] = [];
  context.kpis.forEach((kpi, i) => {
    if ((kpi.measure === null) === (kpi.ratio === null)) issues.push({ path: `/kpis/${i}`, message: 'Pick a measure or a ratio, not both.' });
    if (kpi.measure && !fields.has(kpi.measure.field)) issues.push({ path: `/kpis/${i}/measure/field`, message: `Unknown field ${kpi.measure.field}. Pick a column or a derived field.` });
    for (const part of ['numerator', 'denominator'] as const) {
      const ref = kpi.ratio?.[part];
      if (ref !== undefined && (!kpiIds.has(ref) || ref === kpi.id)) issues.push({ path: `/kpis/${i}/ratio/${part}`, message: `Pick another KPI as the ${part}.` });
    }
  });
  context.thresholds.forEach((threshold, i) => {
    if (!fields.has(threshold.field)) issues.push({ path: `/thresholds/${i}/field`, message: `Unknown field ${threshold.field}. Pick a column or a derived field.` });
  });
  return issues;
}

/** The fixture context, describing this build's own sources. */
function draftedContext(build: Build): Context {
  const context = clone(fixtures.context);
  context.datasets = build.sources.map((source) => ({
    source_id: source.id,
    summary: fixtures.context.datasets.find((d) => d.source_id === source.id)?.summary ?? `${source.row_count.toLocaleString('en-US')} rows from ${source.name}.`,
  }));
  context.issues = contextIssues(build, context);
  return context;
}

/** A first proposal: the fixture's proposed questions, the recommended ones ticked. */
function proposedOutline(): Outline {
  const outline = clone(fixtures.outline);
  for (const section of outline.sections) {
    section.questions = section.questions.filter((q) => q.origin === 'proposed').map((q) => ({ ...q, selected: q.recommended }));
  }
  return outline;
}

/** Other text asking for what the app can't draw: the assistant explains it (mock oracle: GPS animation). */
const UNSUPPORTED_OTHER = /\bgps\b/i;
const GPS_EXPLANATION =
  'This app cannot animate GPS points. I kept your question as a requirement: the blueprint marks it blocked and offers supported alternatives, such as totals by country on a map or a trend over time, when your data has the fields for them.';

const nextQuestionId = (outline: Outline) =>
  `q${Math.max(0, ...outline.sections.flatMap((s) => s.questions.map((q) => Number(q.id.slice(1)) || 0))) + 1}`;

/** Every question of the outline. */
const questionsOf = (outline: Outline): OutlineQuestion[] => outline.sections.flatMap((section) => section.questions);

function hex(value: string): boolean {
  return /^#[0-9A-Fa-f]{6}$/.test(value);
}

/** WCAG contrast ratio of two #RRGGBB colors. */
function contrast(a: string, b: string): number {
  const luminance = (color: string) => {
    const [r, g, bl] = [1, 3, 5].map((i) => {
      const c = parseInt(color.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    }) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** The code checks of a Design: colors, palette size, a preset font, readable text, a title. */
function designIssues(design: Omit<Design, 'revision' | 'issues'>): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  for (const key of ['background', 'surface', 'text', 'accent'] as const) {
    if (!hex(design[key])) issues.push({ path: `/${key}`, message: 'Use a color like #1E40AF.' });
  }
  if (design.palette.length < 3 || design.palette.length > 8) issues.push({ path: '/palette', message: 'Use 3 to 8 palette colors.' });
  design.palette.forEach((color, i) => {
    if (!hex(color)) issues.push({ path: `/palette/${i}`, message: 'Use a color like #1E40AF.' });
  });
  if (!fixtures.designPresets.some((preset) => preset.font_family === design.font_family)) issues.push({ path: '/font_family', message: 'Pick one of the listed fonts.' });
  if (hex(design.text) && hex(design.background)) {
    const ratio = contrast(design.text, design.background);
    if (ratio < 4.5) issues.push({ path: '/text', message: `Text on the background has ${ratio.toFixed(1)}:1 contrast. Use 4.5:1 or more.` });
  }
  if (design.title.trim() === '') issues.push({ path: '/title', message: 'Enter a title.' });
  return issues;
}

/** The mock's stand-in for colors read from a style reference: a teal accent leading the palette. */
const REFERENCE_ACCENT = '#0F766E';

/**
 * A fresh Design: the archetype's preset, then the style reference's colors (source `reference`)
 * when the current version has a style reference; one page per section when 1-5 sections have a
 * selected question.
 */
function prefilledDesign(build: Build): Design {
  const preset = fixtures.designPresets.find((p) => p.archetypes.includes(build.archetype)) ?? fixtures.designPresets[0]!;
  const { context, outline } = artifactsOf(build.id);
  const sections = outline?.sections.filter((s) => s.questions.some((q) => q.selected)).length ?? 0;
  const styled = state.references.get(`${build.id}:${build.current_version}`)?.mode === 'style';
  return {
    revision: 0,
    preset_id: preset.id,
    background: preset.background,
    surface: preset.surface,
    text: preset.text,
    accent: styled ? REFERENCE_ACCENT : preset.accent,
    palette: styled ? [REFERENCE_ACCENT, ...preset.palette.slice(1)] : clone(preset.palette),
    font_family: preset.font_family,
    page_structure: sections >= 1 && sections <= 5 ? 'per_section' : 'single',
    density: 'comfortable',
    title: context?.title ?? build.title,
    subtitle: null,
    source: styled ? 'reference' : 'preset',
    issues: [],
  };
}

/** The fixture blueprint for this build's base source and selected questions, bound to `assessmentId`. */
function draftedBlueprint(build: Build, assessmentId: string): Blueprint {
  const blueprint = clone(fixtures.blueprint);
  const selected = new Set(questionsOf(artifactsOf(build.id).outline ?? fixtures.outline).filter((q) => q.selected).map((q) => q.id));
  blueprint.rows = blueprint.rows.filter((row) => row.question_id === null || selected.has(row.question_id));
  blueprint.view_sources.base = build.sources[0]?.id ?? blueprint.view_sources.base;
  blueprint.view_table = `${state.settings.gcp_project_id || 'my-gcp-project'}.${state.settings.bq_dataset}.dash_${build.id}_v${build.current_version}`;
  blueprint.assessment_id = assessmentId;
  return blueprint;
}

/** Drafts the blueprint, checking feasibility: a ready assessment unless one with open issues is set. */
function draftBlueprint(build: Build): void {
  const assessment = clone(currentAssessment(build.id));
  assessment.id = `assessment_${nextId('r')}`;
  assessment.input_digest ??= `digest_${build.id}`;
  assessment.state = assessment.issues.some((issue) => issue.resolution === 'unresolved') ? 'blocked' : 'ready';
  assessment.prototype_stale = false;
  const blueprint = draftedBlueprint(build, assessment.id);
  if (state.blueprintBlocked && blueprint.rows.some((row) => row.question_id === 'q2')) {
    const prior = assessment.issues.find((issue) => issue.id === MOCK_RATIO_ISSUE_ID);
    if (!prior) assessment.issues.push(mockRatioIssue());
    const resolution = prior?.resolution ?? 'unresolved';
    // Accepted: the fixture's own q2 row is the alternative (net revenue and orders apart).
    if (resolution === 'dropped') blueprint.rows = blueprint.rows.filter((row) => row.question_id !== 'q2');
    else if (resolution === 'unresolved') blueprint.rows = blueprint.rows.map((row) => (row.question_id === 'q2' ? clone(fixtures.blueprintBlocked.rows.find((r) => r.question_id === 'q2')!) : row));
    assessment.state = assessment.issues.some((issue) => issue.resolution === 'unresolved') ? 'blocked' : 'ready';
  }
  state.assessments.set(build.id, assessment);
  save(build, 'blueprint', blueprint);
  build.artifacts.blueprint = 'draft';
  touch(build);
  announce(build);
}

// ---------- The mock client ----------

export function createMockApi(): ApiClient {
  return gated({
    health: () => respond(() => ({ status: 'ok' as const })),

    getSession: () => respond(() => state.session),

    createSession: (code) =>
      respond(() => {
        if (!state.session.required) return state.session;
        if (code !== MOCK_ACCESS_CODE) throw new ApiError(401, 'access_denied', 'The access code is wrong.');
        state.session = { required: true, ok: true };
        return state.session;
      }),

    getSettings: () => respond(() => state.settings),

    updateSettings: (update) =>
      respond(() => {
        const locked = Object.keys(update).filter((field) => !UNLOCKED_SETTINGS.has(field));
        if (agentMode() && locked.length > 0) {
          throw new ApiError(403, 'settings_locked', 'The hosted app fixes the API key and Google Cloud settings. Change only the models here.', { fields: locked });
        }
        const { google_api_key, stages, ...fields } = update;
        const next = clone(state.settings);
        for (const [stage, patchOf] of Object.entries(stages ?? {})) {
          if (stage in next.stages) Object.assign(next.stages[stage as StageId], patchOf);
        }
        Object.assign(next, fields);
        const issues = settingsUpdateIssues(state.settings, next, update);
        if (issues.length > 0) throw new ApiError(422, 'invalid_settings', 'Fix the highlighted settings and save again.', { issues });
        // A stored issue goes once the update fixes its field (a new failure answered 422 above).
        const stillFailing = validateSettings(next.stages, next.fallback_model, fixtures.capabilities);
        const touched = new Set([
          ...Object.keys(fields).map((k) => `/${k}`),
          ...Object.entries(stages ?? {}).flatMap(([stage, patch]) => Object.keys(patch ?? {}).map((k) => `/stages/${stage}/${k}`)),
        ]);
        next.issues = next.issues.filter((i) => !touched.has(i.path) || stillFailing.some((f) => f.path === i.path));
        state.settings = next;
        // The key is write-only: the mock only remembers that one is set.
        if (google_api_key !== undefined) state.settings.google_api_key_set = google_api_key !== '';
        return state.settings;
      }),

    getSettingsCapabilities: () => respond(() => fixtures.capabilities),

    listBuilds: () => respond(() => newestFirst([...state.builds.values()].map(summary), (b) => b.updated_at)),

    createBuild: ({ title, archetype, mode }) =>
      respond(() => {
        if (!isArchetype(archetype) || !isMode(mode)) throw invalid('invalid_request', 'Pick an archetype and a mode.');
        const at = now();
        const build: Build = {
          id: nextId('b'),
          title: title?.trim() || 'Untitled dashboard',
          archetype,
          mode,
          stage: 'connect',
          created_at: at,
          updated_at: at,
          sources: [],
          docs: [],
          spec_version: null,
          current_version: 1,
          versions: [{ n: 1, status: 'draft', report_url: null, created_at: at }],
          report_url: null,
          notes: null,
          artifacts: { context: 'missing', outline: 'missing', design: 'missing', blueprint: 'missing' },
        };
        state.builds.set(build.id, build);
        return build;
      }),

    getBuild: (id) => respond(() => findBuild(id)),

    uploadSources: (id, files) =>
      respond(() => {
        requireNoReview(findBuild(id));
        const tooLarge = oversizeError(files);
        if (tooLarge) throw tooLarge;
        const build = findBuild(id);
        requireGcp();
        if (files.length === 0) throw invalid('invalid_source', 'Choose at least one .csv file.', { reason: 'no_files' });
        const notCsv = files.find((file) => !file.name.toLowerCase().endsWith('.csv'));
        if (notCsv) {
          throw invalid('invalid_source', `${notCsv.name} isn't a CSV file. Upload .csv files only.`, {
            reason: 'not_csv',
            file: notCsv.name,
          });
        }
        const sources = files.map((file) => newSource(build, 'upload', file.name));
        addSources(build, sources);
        return { sources };
      }),

    addSource: (id, { kind, uri }) =>
      respond(() => {
        requireNoReview(findBuild(id));
        const build = findBuild(id);
        requireGcp();
        const value = uri.trim();
        if (kind === 'gcs' && !/^gs:\/\/[^/\s]+\/\S+\.csv$/i.test(value)) {
          throw invalid('invalid_source', 'Enter a GCS path like gs://bucket/path/file.csv.', { reason: 'bad_uri' });
        }
        if (kind === 'bigquery' && !/^[\w-]+\.\w+\.[\w$-]+$/.test(value)) {
          throw invalid('invalid_source', 'Enter a BigQuery table like project.dataset.table.', { reason: 'bad_uri' });
        }
        const source = newSource(build, kind, value.split(kind === 'gcs' ? '/' : '.').pop() ?? value);
        addSources(build, [source]);
        return source;
      }),

    getFeasibility: (id) => respond(() => currentAssessment(id)),
    checkFeasibility: (id) => respond(() => {
      requireNoReview(findBuild(id));
      const build = findBuild(id);
      requireStage(build, BEFORE_BUILD, 'Check feasibility before building.');
      if (state.assessmentBusy.has(id)) throw new ApiError(409, 'action_in_progress', 'Wait for the current check.');
      state.assessmentBusy.add(id);
      return startRun(build, 'capability_check', () => [() => {
        const current = clone(currentAssessment(id));
        current.id = `assessment_${nextId('r')}`;
        current.input_digest ??= `digest_${id}`;
        current.state = current.issues.some((issue) => issue.resolution === 'unresolved') ? 'blocked' : current.prototype_stale ? 'stale' : 'ready';
        state.assessments.set(id, current);
        state.assessmentBusy.delete(id);
      }]);
    }),
    decideFeasibility: (id, assessmentId, decisions) => respond(() => {
      requireNoReview(findBuild(id));
      const current = currentAssessment(id);
      if (!current.id || current.id !== assessmentId) throw new ApiError(409, 'feasibility_stale', 'Feasibility changed. Refresh and choose again.');
      if (state.assessmentBusy.has(id)) throw new ApiError(409, 'action_in_progress', 'Wait for the current check.');
      if (decisions.length < 1 || decisions.length > 20 || new Set(decisions.map((decision) => decision.issue_id)).size !== decisions.length) throw invalid('invalid_request', 'Choose 1 to 20 distinct requirements.');
      const updated = clone(current);
      for (const decision of decisions) {
        const issue = updated.issues.find((entry) => entry.id === decision.issue_id);
        if (!issue || issue.resolution !== 'unresolved' ||
          (decision.action !== 'drop' && decision.action !== 'accept_alternative') ||
          (decision.action === 'drop' ? decision.alternative_id !== null : !issue.alternatives.some((alternative) => alternative.id === decision.alternative_id))) {
          throw invalid('invalid_request', 'Choose an offered alternative or explicitly drop the requirement.');
        }
        issue.resolution = decision.action === 'drop' ? 'dropped' : 'accepted_alternative';
      }
      updated.id = `assessment_${nextId('r')}`;
      updated.state = updated.issues.some((issue) => issue.resolution === 'unresolved') ? 'blocked' : updated.prototype_stale ? 'stale' : 'ready';
      state.assessments.set(id, updated);
      // A decision on the ratio row rewrites it in code, as the live backend does: the alternative
      // (the fixture's own q2 row) or no row. Like the live backend, no artifact.updated follows
      // (seen 2026-10-21): the client reads the blueprint again after a saved decision.
      const ratio = decisions.find((decision) => decision.issue_id === MOCK_RATIO_ISSUE_ID);
      const blueprint = artifactsOf(id).blueprint;
      if (ratio && blueprint?.rows.some((row) => row.issue_ids.includes(MOCK_RATIO_ISSUE_ID))) {
        const alternative = fixtures.blueprint.rows.find((row) => row.question_id === 'q2')!;
        const rows = blueprint.rows.flatMap((row) => (!row.issue_ids.includes(MOCK_RATIO_ISSUE_ID) ? [row] : ratio.action === 'drop' ? [] : [clone(alternative)]));
        artifactsOf(id).blueprint = { ...clone(blueprint), rows, revision: blueprint.revision + 1, assessment_id: updated.id };
      }
      return updated;
    }),
    reapplyComments: (id, assessmentId, batchId) => respond(() => {
      requireNoReview(findBuild(id));
      const build = findBuild(id);
      requireStage(build, ['prototype'], 'Open the prototype to reapply comments.');
      const current = currentAssessment(id);
      if (current.id !== assessmentId || current.pending_comments?.id !== batchId) throw new ApiError(409, 'feasibility_stale', 'The saved batch changed. Refresh and choose again.');
      if (!['ready', 'stale'].includes(current.state) || current.issues.some((issue) => issue.resolution === 'unresolved')) throw new ApiError(409, 'feasibility_blocked', 'Resolve requirements first.');
      if (state.assessmentBusy.has(id)) throw new ApiError(409, 'action_in_progress', 'Wait for the current action.');
      state.assessmentBusy.add(id);
      return startRun(build, 'revise', () => [() => {
        const updated = clone(currentAssessment(id));
        updated.id = `assessment_${nextId('r')}`;
        updated.pending_comments = null; updated.prototype_stale = false; updated.state = 'ready';
        state.assessments.set(id, updated);
        state.pendingIssueIds.delete(id); state.assessmentBusy.delete(id);
        build.spec_version = (build.spec_version ?? 0) + 1;
        emit(id, { name: 'prototype.updated', data: { spec_version: build.spec_version } });
        announce(build);
      }]);
    }),
    discardComments: (id, assessmentId) => respond(() => {
      requireNoReview(findBuild(id));
      const current = currentAssessment(id);
      if (current.id !== assessmentId) throw new ApiError(409, 'feasibility_stale', 'The saved batch changed. Refresh and choose again.');
      if (state.assessmentBusy.has(id)) throw new ApiError(409, 'action_in_progress', 'Wait for the current action.');
      const updated = clone(current);
      const owned = state.pendingIssueIds.get(id) ?? new Set<string>();
      updated.issues = updated.issues.filter((issue) => !owned.has(issue.id));
      updated.id = `assessment_${nextId('r')}`; updated.pending_comments = null;
      // Preserve independent intent/prototype invalidation; abandoning a batch never edits the spec.
      updated.state = updated.issues.some((issue) => issue.resolution === 'unresolved') ? 'blocked' : updated.prototype_stale ? 'stale' : 'ready';
      state.pendingIssueIds.delete(id); state.assessments.set(id, updated);
      return updated;
    }),
    getReferences: (id) => respond(() => {
      const build = findBuild(id);
      return state.references.get(`${id}:${build.current_version}`) ?? null;
    }),
    uploadReferences: (id, files, mode, instructions) => respond(() => {
      requireNoReview(findBuild(id));
      const build = findBuild(id);
      requireStage(build, BEFORE_BUILD, 'Start a new version to change references.');
      if (state.referenceBusy.has(id)) throw new ApiError(409, 'build_busy', 'Wait for the current reference upload.');
      const problem = referenceValidation(files, mode, instructions);
      if (problem) throw new ApiError(422, 'invalid_source', problem);
      requireModel();
      const key = `${id}:${build.current_version}`;
      const images = files.map((file) => {
        const imageId = nextId('s');
        const name = `reference_${imageId}.${file.type === 'image/png' ? 'png' : 'jpg'}`;
        const url = typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : '';
        state.referenceFiles.set(`${key}:${name}`, url);
        return { id: imageId, name: file.name.split(/[\\/]/).pop() ?? 'Reference image', file: name };
      });
      state.referenceBusy.add(id);
      return startRun(build, 'reference_extract', () => [() => {
        // A recreate upload commits a pending analysis (revision 1); a style set has none (dashboard-intent.md 1.3).
        const base = mode === 'recreate' ? clone(fixtures.referenceSetPending) : { ...clone(fixtures.referenceSet), analysis: null };
        state.references.set(key, { ...base, id: nextId('s'), mode, instructions, images });
        state.referenceBusy.delete(id);
        emit(id, { name: 'docs.updated', data: { docs: clone(build.docs) } });
      }]);
    }),
    deleteReferences: (id) => respond(() => {
      requireNoReview(findBuild(id));
      const build = findBuild(id);
      requireStage(build, BEFORE_BUILD, 'Start a new version to change references.');
      if (state.referenceBusy.has(id)) throw new ApiError(409, 'build_busy', 'Wait for the current reference upload.');
      state.references.delete(`${id}:${build.current_version}`);
    }),
    updateReferenceAnalysis: (id, body) => respond(() => {
      const build = findBuild(id);
      const reference = requireAnalysis(build);
      const current = reference.analysis;
      requireAnalysisRevision(current, body.revision, 'save');
      const byId = new Map(body.items.map((item) => [item.id, item]));
      if (byId.size !== body.items.length || body.items.length !== current.items.length || current.items.some((item) => !byId.has(item.id))) {
        throw new ApiError(422, 'invalid_request', 'Send every analysis item exactly once.');
      }
      const items = current.items.map((item) => {
        const { disposition, type } = byId.get(item.id)!;
        return { ...item, disposition, type: disposition === 'static' ? null : type };
      });
      const analysis: ReferenceAnalysis = { ...current, revision: current.revision + 1, state: 'pending', items, note: body.note, summary: analysisSummary(items), issues: [] };
      analysis.issues = analysisIssues(analysis);
      if (current.state === 'approved') {
        // Editing an approved analysis is a reference change: assessment, a saved blueprint and the prototype go stale.
        const assessment = currentAssessment(id);
        if (assessment.id) state.assessments.set(id, { ...assessment, state: 'stale', prototype_stale: assessment.prototype_stale || build.spec_version !== null });
        if (build.artifacts.blueprint !== 'missing') { build.artifacts.blueprint = 'stale'; announce(build); }
      }
      reference.analysis = analysis;
      return reference;
    }),
    approveReferenceAnalysis: (id, revision) => respond(() => {
      const reference = requireAnalysis(findBuild(id));
      const current = reference.analysis;
      requireAnalysisRevision(current, revision, 'approve');
      if (current.state === 'approved') return reference;
      if (current.issues.length > 0) throw artifactInvalid(current.issues);
      current.state = 'approved';
      return reference;
    }),
    proposeSyntheticSchema: (id, referenceSetId) => respond(() => {
      const build = findBuild(id);
      requireSyntheticWrite(build);
      const reference = state.references.get(`${id}:${build.current_version}`);
      if (!reference || reference.mode !== 'recreate') {
        throw invalid('synthetic_schema_unavailable', 'A style reference shows how a dashboard looks, not its data. Switch the reference to Recreate dashboard, or enter the columns yourself.');
      }
      if (reference.id !== referenceSetId) throw new ApiError(409, 'synthetic_proposal_stale', 'The reference changed. Propose the schema again.');
      requireModel();
      state.syntheticBusy.add(id);
      const failed = failureOf('synthetic_schema')();
      return startRun(build, 'synthetic_schema', () => [() => {
        state.syntheticBusy.delete(id);
        if (!failed) state.proposals.set(id, { ...clone(fixtures.syntheticProposal), id: `proposal_${nextId('r')}`, reference_set_id: reference.id });
      }], { failure: () => failed });
    }),
    getSyntheticProposal: (id) => respond(() => {
      findBuild(id);
      return state.proposals.get(id) ?? null;
    }),
    generateSyntheticData: (id, request) => respond(() => {
      const tooLarge = syntheticOversizeError(request);
      if (tooLarge) throw tooLarge;
      const build = findBuild(id);
      const { generation_key: key, proposal_id, spec } = request;
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(key)) throw invalid('invalid_request', 'Invalid request');
      // Replay comes before every other check: the same key and request always answer its first run.
      const body = JSON.stringify({ proposal_id, spec });
      const replay = state.generations.get(`${id}:${key}`);
      if (replay) {
        if (replay.body !== body) throw new ApiError(409, 'synthetic_request_conflict', 'This generation key was already used for a different request.');
        return { run_id: replay.job.run_id };
      }
      requireSyntheticWrite(build);
      const problem = specProblem(spec);
      if (problem) throw invalid('invalid_generation_spec', 'The generation spec is invalid', problem);
      if (proposal_id !== null) {
        const proposal = state.proposals.get(id);
        const reference = state.references.get(`${id}:${build.current_version}`);
        if (proposal?.id !== proposal_id || proposal.reference_set_id !== reference?.id) {
          throw new ApiError(409, 'synthetic_proposal_stale', 'The proposal is out of date. Propose the schema again.');
        }
      }
      requireGcp();
      const job: GenerationStatus = { generation_key: key, run_id: '', state: 'queued', source_id: null, retry_ready: false, error: null };
      const failed = failureOf('synthetic_generate')();
      state.syntheticBusy.add(id);
      const accepted = startRun(build, 'synthetic_generate', () => [
        () => { job.state = 'generating'; },
        () => { job.state = 'loading'; },
        () => {
          state.syntheticBusy.delete(id);
          if (failed) {
            // The shared failed fixture (cleanup done, retry ready), with this run's key, id and error text.
            const shape = clone(fixtures.syntheticJobFailed);
            Object.assign(job, { ...shape, generation_key: key, run_id: job.run_id, error: { code: shape.error!.code, message: failed.error ?? shape.error!.message } });
            return;
          }
          const source = syntheticSource(build, spec);
          const proposal = proposal_id ? state.proposals.get(id) : undefined;
          state.datasets.set(id, [...(state.datasets.get(id) ?? []), {
            ...clone(fixtures.syntheticDataset), source_id: source.id, generation_key: key, spec: clone(spec), assumptions: clone(proposal?.assumptions ?? []), created_at: now(),
          }]);
          Object.assign(job, { ...clone(fixtures.syntheticJobSucceeded), generation_key: key, run_id: job.run_id, source_id: source.id });
          addSources(build, [source]);
          emit(id, { name: 'docs.updated', data: { docs: clone(build.docs) } });
        },
      ], { failure: () => failed });
      job.run_id = accepted.run_id;
      state.generations.set(`${id}:${key}`, { body, job });
      return accepted;
    }),
    listSyntheticDatasets: (id) => respond(() => {
      findBuild(id);
      return state.datasets.get(id) ?? [];
    }),
    listSyntheticJobs: (id) => respond(() => {
      findBuild(id);
      return [...state.generations.entries()].filter(([at]) => at.startsWith(`${id}:`)).map(([, { job }]) => job).reverse().slice(0, 20);
    }),
    getSyntheticJob: (id, key) => respond(() => {
      findBuild(id);
      const generation = state.generations.get(`${id}:${key}`);
      if (!generation) throw new ApiError(404, 'generation_not_found', 'No sample-data run has this key.', { generation_key: key });
      return generation.job;
    }),
    syntheticCsvUrl: (id, sourceId) => `/api/builds/${encodeURIComponent(id)}/synthetic-data/${encodeURIComponent(sourceId)}/csv`,
    uploadStyleImages: (id, files) =>
      respond(() => {
        requireNoReview(findBuild(id));
        const tooLarge = oversizeError(files);
        if (tooLarge) throw tooLarge;
        const build = findBuild(id);
        requireModel();
        if (files.length === 0 || !files.every((f) => /\.(png|jpe?g)$/i.test(f.name))) {
          throw invalid('invalid_request', 'Upload .png or .jpg images only.');
        }
        return startRun(build, 'style_extract', (runId) => [
          () => emit(id, { name: 'node.progress', data: { run_id: runId, node: 'style_extract', text: `Reading ${files.length} style ${files.length === 1 ? 'image' : 'images'}` } }),
        ]);
      }),

    startResearch: (id, prompt) =>
      respond(() => {
        requireNoReview(findBuild(id));
        const build = findBuild(id);
        requireModel();
        if (!prompt.trim()) throw invalid('invalid_request', 'Describe what to research.');
        return startRun(build, 'research', (runId) => [
          () => emit(id, { name: 'node.progress', data: { run_id: runId, node: 'research', text: 'Searching the web' } }),
          () => addSources(build, [newSource(build, 'research', 'research_findings')]),
        ]);
      }),

    listMessages: (id) =>
      respond(() => {
        findBuild(id);
        return state.messages.get(id) ?? [];
      }),

    draftContext: (id, notes) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(build, ['connect', 'context'], 'Draft the context from Connect or Context.');
        if (build.sources.length === 0) throw new ApiError(409, 'wrong_stage', 'Add at least one source, then draft the context.', { stage: build.stage });
        if (notes !== undefined && notes.length > 4000) throw invalid('invalid_request', 'Keep the notes to 4000 characters.', { field: 'notes' });
        requireIdle(build);
        requireModel();
        if (notes !== undefined) build.notes = notes;
        if (build.stage !== 'context') setStage(build, 'context');
        announce(build);
        return stagedRun(build, 'context', () => [
          () => {
            save(build, 'context', draftedContext(build));
            markEdited(build, 'context');
          },
          ...streamAssistant(id, fixtures.messages[0]?.text ?? 'I drafted the context. Check it, then confirm.', 'context'),
        ]);
      }),

    getContext: (id) => respond(() => artifactsOf(findBuild(id).id).context),

    updateContext: (id, body) =>
      respond(() => {
        const build = findBuild(id);
        requireEditable(build, 'context');
        requireArtifact(build, 'context');
        requireIdle(build);
        const { revision: _r, issues: _i, ...fields } = body as Context;
        const context = save(build, 'context', { ...clone(fields), revision: 0, issues: contextIssues(build, fields) });
        markEdited(build, 'context');
        return context;
      }),

    confirmContext: (id) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(build, ['context'], 'Open the Context step to confirm it.');
        const context = requireArtifact(build, 'context');
        if (context.issues.length > 0) throw artifactInvalid(context.issues);
        requireIdle(build);
        const hasOutline = artifactsOf(id).outline !== null;
        if (!hasOutline) requireModel();
        build.artifacts.context = 'confirmed';
        setStage(build, 'outline');
        announce(build);
        return stagedRun(build, 'outline_propose', () => [
          () => {
            const existing = artifactsOf(id).outline;
            if (existing) {
              // Revalidated in code: unknown KPI refs go, every selection stays.
              const kpis = new Set(context.kpis.map((kpi) => kpi.id));
              const outline = clone(existing);
              for (const q of questionsOf(outline)) q.kpi_refs = q.kpi_refs.filter((ref) => kpis.has(ref));
              save(build, 'outline', outline);
            } else {
              save(build, 'outline', proposedOutline());
              build.artifacts.outline = 'draft';
            }
            touch(build);
            announce(build);
          },
        ]);
      }),

    getOutline: (id) => respond(() => artifactsOf(findBuild(id).id).outline),

    proposeOutline: (id) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(build, ['outline'], 'Open the Outline step to propose questions again.');
        requireIdle(build);
        requireModel();
        return stagedRun(build, 'outline_propose', () => [
          () => {
            const old = artifactsOf(id).outline;
            const outline = proposedOutline();
            const kept = new Map(old ? questionsOf(old).map((q) => [q.text, q.selected]) : []);
            for (const q of questionsOf(outline)) q.selected = kept.get(q.text) ?? q.selected;
            // `other` questions stay, in their section (or one of their own when it's gone).
            for (const section of old?.sections ?? []) {
              const others = section.questions.filter((q) => q.origin === 'other');
              if (others.length === 0) continue;
              const target = outline.sections.find((s) => s.id === section.id);
              const ids = new Set(questionsOf(outline).map((q) => q.id));
              const moved = others.map((q) => (ids.has(q.id) ? { ...q, id: nextQuestionId(outline) } : q));
              if (target) target.questions.push(...moved);
              else outline.sections.push({ ...section, questions: moved });
            }
            save(build, 'outline', outline);
            markEdited(build, 'outline');
          },
        ]);
      }),

    updateOutlineSelection: (id, questions) =>
      respond(() => {
        const build = findBuild(id);
        requireEditable(build, 'outline');
        const outline = clone(requireArtifact(build, 'outline'));
        requireIdle(build);
        if (questions.length < 1 || questions.length > 100) throw invalid('invalid_request', 'Send 1 to 100 questions.');
        const byId = new Map(questionsOf(outline).map((q) => [q.id, q]));
        const unknown = questions.find((q) => !byId.has(q.id));
        if (unknown) throw invalid('invalid_request', `There's no question ${unknown.id} in this outline.`, { question_id: unknown.id });
        for (const { id: qid, selected } of questions) byId.get(qid)!.selected = selected;
        const saved = save(build, 'outline', outline);
        markEdited(build, 'outline');
        return saved;
      }),

    addOutlineQuestions: (id, sectionId, text) =>
      respond(() => {
        const build = findBuild(id);
        requireEditable(build, 'outline');
        const outline = requireArtifact(build, 'outline');
        const trimmed = text.trim();
        if (trimmed.length < 1 || text.length > 1000) throw invalid('invalid_request', 'Write 1 to 1000 characters.', { field: 'text' });
        if (sectionId !== null && !outline.sections.some((s) => s.id === sectionId)) throw invalid('invalid_request', `There's no section ${sectionId} in this outline.`, { section_id: sectionId });
        requireIdle(build);
        requireModel();
        markEdited(build, 'outline');
        return stagedRun(build, 'outline_other', () => [
          // Unsupported behavior is explained at once and kept as a requirement (dashboard-intent.md 1.2).
          ...(UNSUPPORTED_OTHER.test(trimmed) ? streamAssistant(id, GPS_EXPLANATION, 'outline_other') : []),
          () => {
            const next = clone(artifactsOf(id).outline!);
            const question: OutlineQuestion = {
              id: nextQuestionId(next),
              text: `${trimmed.charAt(0).toUpperCase()}${trimmed.slice(1).replace(/[.?!]*$/, '')}?`,
              rationale: 'Added by you.',
              recommended: false,
              selected: true,
              kpi_refs: [],
              origin: 'other',
            };
            const section = next.sections.find((s) => s.id === sectionId);
            if (section) section.questions.push(question);
            else next.sections.push({ id: `s${next.sections.length + 1}`, title: 'Your questions', purpose: 'Questions you added.', questions: [question] });
            save(build, 'outline', next);
          },
        ]);
      }),

    suggestOutlineQuestions: (id, sectionId) =>
      respond(() => {
        const build = findBuild(id);
        requireEditable(build, 'outline');
        const section = requireArtifact(build, 'outline').sections.find((s) => s.id === sectionId);
        if (!section) throw invalid('invalid_request', `There's no section ${sectionId} in this outline.`, { section_id: sectionId });
        requireIdle(build);
        requireModel();
        markEdited(build, 'outline');
        return stagedRun(build, 'outline_suggest', () => [
          () => {
            const next = clone(artifactsOf(id).outline!);
            const target = next.sections.find((s) => s.id === sectionId)!;
            const topic = target.title.toLowerCase();
            for (const text of [`Which segment leads in ${topic}?`, `How has ${topic} changed since last quarter?`]) {
              target.questions.push({ id: nextQuestionId(next), text, rationale: 'Suggested to round out this section.', recommended: false, selected: false, kpi_refs: [], origin: 'suggested' });
            }
            save(build, 'outline', next);
          },
        ]);
      }),

    confirmOutline: (id) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(build, ['outline'], 'Open the Outline step to confirm it.');
        const selected = questionsOf(requireArtifact(build, 'outline')).filter((q) => q.selected).length;
        if (selected < 1) throw artifactInvalid([{ path: '/sections', message: 'Select at least one question.' }]);
        if (selected > 24) throw artifactInvalid([{ path: '/sections', message: `Select 24 questions at most (${selected} selected).` }]);
        requireIdle(build);
        build.artifacts.outline = 'confirmed';
        const existing = artifactsOf(id).design;
        if (existing) {
          // Kept and revalidated; a stale design stays stale until confirmed again.
          const { revision: _r, issues: _i, ...fields } = existing;
          save(build, 'design', { ...clone(existing), issues: designIssues(fields) });
        } else {
          save(build, 'design', prefilledDesign(build));
          build.artifacts.design = 'draft';
        }
        setStage(build, 'design');
        announce(build);
        return build;
      }),

    listDesignPresets: (id) =>
      respond(() => {
        findBuild(id);
        return fixtures.designPresets;
      }),

    getDesign: (id) => respond(() => artifactsOf(findBuild(id).id).design),

    prefillDesign: (id) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(build, ['design'], 'Open the Design step to reset it.');
        requireIdle(build);
        const design = save(build, 'design', prefilledDesign(build));
        markEdited(build, 'design');
        return design;
      }),

    updateDesign: (id, body) =>
      respond(() => {
        const build = findBuild(id);
        requireEditable(build, 'design');
        requireArtifact(build, 'design');
        requireIdle(build);
        const { revision: _r, issues: _i, ...fields } = body as Design;
        const design = save(build, 'design', { ...clone(fields), revision: 0, issues: designIssues(fields) });
        markEdited(build, 'design');
        return design;
      }),

    confirmDesign: (id) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(build, ['design'], 'Open the Design step to confirm it.');
        requireReferenceApproved(build);
        const design = requireArtifact(build, 'design');
        if (design.issues.length > 0) throw artifactInvalid(design.issues);
        requireIdle(build);
        requireModel();
        build.artifacts.design = 'confirmed';
        setStage(build, 'blueprint');
        announce(build);
        return stagedRun(build, 'blueprint', (runId) => [
          () => emit(id, { name: 'node.progress', data: { run_id: runId, node: 'blueprint', text: 'Checking feasibility' } }),
          () => draftBlueprint(build),
        ]);
      }),

    getBlueprint: (id) => respond(() => artifactsOf(findBuild(id).id).blueprint),

    regenerateBlueprint: (id) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(build, ['blueprint', 'prototype'], 'Regenerate the blueprint from Blueprint or Prototype.');
        requireReferenceApproved(build);
        requireIdle(build);
        requireModel();
        if (build.stage !== 'blueprint') setStage(build, 'blueprint');
        return stagedRun(build, 'blueprint', () => [() => draftBlueprint(build)]);
      }),

    acceptBlueprint: (id) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(build, ['blueprint'], 'Open the Blueprint step to accept it.');
        requireReferenceApproved(build);
        const blueprint = requireArtifact(build, 'blueprint');
        const assessment = currentAssessment(id);
        if (assessment.state !== 'ready') {
          const open = assessment.issues.filter((issue) => issue.resolution === 'unresolved').map((issue) => issue.id);
          throw new ApiError(409, 'feasibility_blocked', 'Resolve the blocked requirements, then accept.', { assessment_id: assessment.id, issue_ids: open });
        }
        if (!blueprint.rows.some((row) => row.status === 'ok')) throw artifactInvalid([{ path: '/rows', message: 'Every row is blocked. Resolve one, then accept.' }]);
        requireIdle(build);
        requireModel();
        // On failure the stage stays Blueprint and nothing is confirmed (run.finished carries the error).
        return stagedRun(build, 'prototype', (runId) => [
          () => emit(id, { name: 'node.progress', data: { run_id: runId, node: 'prototype', text: 'Rendering the prototype' } }),
          // With review_briefs on, the run pauses for the user's brief review instead of publishing (stage stays Blueprint).
          () => (state.settings.review_briefs ? pauseForReview(build, 'prototype') : publishPrototype(build)),
        ]);
      }),

    getDesignPages: (id) => respond(() => pagesOf(findBuild(id))),

    saveBriefReview: (id, body) =>
      respond(() => {
        const review = pagesOf(findBuild(id)).review;
        if (!review || review.review_id !== body.review_id) throw new ApiError(404, 'review_not_found', 'There is no brief waiting for review. Reload the page.');
        if (body.revision !== review.revision) throw new ApiError(409, 'brief_review_conflict', 'The brief changed since you opened it. Reload it, then edit again.', { revision: review.revision });
        const brief = clone(body.brief);
        review.revision += 1;
        review.brief = { ...review.brief, origin: 'edited', brief, markdown: briefMarkdown(brief, review.components), sha256: fakeSha256(JSON.stringify(brief)) };
        review.issues = briefIssues(brief, review.components);
        return review;
      }),

    approveBriefReview: (id, body) =>
      respond(() => {
        const build = findBuild(id);
        const pages = pagesOf(build);
        const done = state.approvedReviews.get(`${id}:${body.review_id}`);
        if (done && pages.review?.review_id !== body.review_id) return { run_id: done };
        const review = pages.review;
        if (!review || review.review_id !== body.review_id) throw new ApiError(404, 'review_not_found', 'There is no brief waiting for review. Reload the page.');
        if (body.revision !== review.revision || body.sha256 !== review.brief.sha256) {
          throw new ApiError(409, 'brief_review_conflict', 'The brief changed since you opened it. Reload it, then approve again.', { revision: review.revision });
        }
        if (review.issues.length > 0) throw artifactInvalid(review.issues);
        if (review.stale) throw new ApiError(409, 'brief_review_stale', 'The inputs changed since this brief was written. Cancel the review and run it again.');
        requireModel();
        pages.review = null;
        const accepted = publishReviewed(build, review);
        state.approvedReviews.set(`${id}:${body.review_id}`, accepted.run_id);
        return accepted;
      }),

    cancelBriefReview: (id, reviewId) =>
      respond(() => {
        const build = findBuild(id);
        const pages = pagesOf(build);
        if (pages.review?.review_id === reviewId) pages.review = null;
        return build;
      }),

    getDoc: (id, path) =>
      respond(() => {
        const doc = findBuild(id).docs.find((d) => d.path === path);
        if (!doc) throw new ApiError(404, 'doc_not_found', `There's no ${path} in this build. Generate the plan first.`);
        return `# ${doc.title}\n\n*${doc.type}* · mock document for \`${doc.path}\`.\n\n- Written from the confirmed context, outline, design and blueprint.\n- Shown read-only here.\n`;
      }),

    getSpec: (id) =>
      respond(() => {
        const build = findBuild(id);
        if (build.spec_version === null) throw new ApiError(404, 'spec_not_found', 'There is no spec yet. Accept the blueprint first.');
        return { spec_version: build.spec_version };
      }),

    prototypeUrl: (id, v, layer = 'all') => {
      const path = `/api/builds/${encodeURIComponent(id)}/prototype?layer=${layer}&v=${v ?? 0}`;
      // Without blob URLs (some test DOMs) the plain path; tests load the fixture into their iframe themselves.
      if (typeof URL.createObjectURL !== 'function') return path;
      // A per_section design renders one page per section: the two-page fixture.
      const pages = state.artifacts.get(id)?.design?.page_structure === 'per_section' ? fixtures.prototypeMultipageHtml : fixtures.prototypeHtml;
      const key = `${path}|${pages === fixtures.prototypeHtml ? 'single' : 'per_section'}`;
      const cached = blobUrls.get(key);
      if (cached) return cached;
      const hide = '<style>[data-kind="component"]{visibility:hidden}</style></head>';
      const html = layer === 'decoration' ? pages.replace('</head>', hide) : pages;
      // A blob URL made by this page is same-origin, so the overlay can read the iframe's DOM.
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
      blobUrls.set(key, url);
      return url;
    },

    postComments: (id, comments) =>
      respond(() => {
        requireNoReview(findBuild(id));
        const build = findBuild(id);
        if (comments.length < 1 || comments.length > 20 || !comments.every((c) => isComment(c) && c.text.trim())) {
          throw invalid('invalid_request', 'Send 1 to 20 comments, each with text.');
        }
        requireStage(build, ['prototype'], 'Comments apply to the prototype. Open the Prototype stage first.');
        const current = clone(currentAssessment(id));
        if (current.issues.some((issue) => issue.resolution === 'unresolved') || current.pending_comments) {
          const owned = state.pendingIssueIds.get(id) ?? new Set<string>();
          current.issues.forEach((issue) => { if (owned.has(issue.id)) issue.resolution = 'unresolved'; });
          current.id = `assessment_${nextId('r')}`;
          current.state = 'blocked';
          current.pending_comments = { id: `batch_${nextId('r')}`, comments: clone(comments) };
          state.assessments.set(id, current);
          throw new ApiError(409, 'feasibility_blocked', 'Comments saved. Resolve the requirements, then reapply the saved batch.');
        }
        requireModel();
        const failure = failureOf('revise');
        return startRun(build, 'revise', (runId) => [
          () => emit(id, { name: 'node.progress', data: { run_id: runId, node: 'revise', text: `Applying ${comments.length} comments` } }),
          () => {
            // A failed revise publishes nothing (api.md 3.0, Run errors).
            if (failure()) return;
            build.spec_version = (build.spec_version ?? 0) + 1;
            touch(build);
            emit(id, { name: 'prototype.updated', data: { spec_version: build.spec_version } });
            announce(build);
          },
        ], { failure });
      }),

    runAudit: (id) =>
      respond(() => {
        requireNoReview(findBuild(id));
        const build = findBuild(id);
        requireStage(build, ['prototype'], 'Run the audit on the prototype. Open the Prototype stage first.');
        requireModel();
        return startRun(build, 'ux_audit', () =>
          streamAssistant(
            id,
            '**UX audit findings**\n\n1. The headline metric is easy to miss. Make it larger.\n2. The two charts use different colors for the same series. Pick one.\n3. The filter bar has no label. Add one.',
            'ux_audit',
          ),
        );
      }),

    compileRecipe: (id) =>
      respond(() => {
        requireNoReview(findBuild(id));
        const build = findBuild(id);
        if (build.spec_version === null) throw new ApiError(409, 'wrong_stage', 'Accept the blueprint before the recipe.', { stage: build.stage });
        requireConfirmed(build);
        // dashboard-intent.md 1.3: a pre-2.0 build's recipe and run are not gated.
        if (!isLegacy(build)) requireReferenceApproved(build);
        return fixtures.recipe;
      }),

    runBuild: (id) =>
      respond(() => {
        requireNoReview(findBuild(id));
        const build = findBuild(id);
        if (state.engineBusy) throw new ApiError(409, 'engine_busy', 'Another build is running in Data Studio. Wait for it to finish, then try again.');
        if (agentMode() && !state.engine.agent_connected) {
          throw new ApiError(424, 'agent_offline', "The build agent isn't connected. Start it on the machine with Chrome, then build again.");
        }
        if (!state.engine.signed_in) {
          throw new ApiError(424, 'engine_not_signed_in', agentMode() ? "Run dsengine login on the agent's machine, then build again." : 'Sign in to Google first, then build again.');
        }
        requireStage(build, ['prototype'], 'Build from the Prototype stage.');
        requireConfirmed(build);
        // dashboard-intent.md 1.3: a pre-2.0 build's recipe and run are not gated.
        if (!isLegacy(build)) requireReferenceApproved(build);
        const version = build.versions.find((v) => v.n === build.current_version);
        state.engineBusy = true;
        setStage(build, 'build');
        if (version) version.status = 'building';
        const outcome = state.buildOutcome;
        const ops = fixtures.recipe.ops;
        const failedAt = outcome === 'failed' ? 0 : outcome === 'partial' ? ops.length - 1 : -1;
        const failMessage =
          outcome === 'failed' ? "Data Studio didn't open the report: sign-in expired" : 'style panel: colors control not found';
        const opEvent = (op: (typeof ops)[number], i: number): OpFinished => {
          const status = failedAt < 0 || i < failedAt ? 'ok' : i === failedAt ? 'failed' : 'skipped';
          return {
            event: 'op_finished',
            ts: now(),
            op_id: op.op_id,
            op: opName(op.line),
            status,
            message: status === 'failed' ? failMessage : '',
            screenshot: null,
            duration_ms: status === 'ok' ? 1200 : 0,
          };
        };
        const runError = outcome === 'failed' ? "The engine stopped before the dashboard was saved. Sign in to Google again, then build again." : null;
        return startRun(
          build,
          'execute',
          (run_id) => [
            ...ops.map((op, i) => () => {
              emit(id, { name: 'build.op', data: opEvent(op, i) });
              if (state.screencast) emit(id, { name: 'build.frame', data: { data: mockFrame(op.line, i) } });
            }),
            () => {
              state.engineBusy = false;
              if (outcome === 'failed') {
                if (version) version.status = 'draft';
                emit(id, { name: 'build.finished', data: { status: 'failed', report_url: null, version: build.current_version } });
                emit(id, { name: 'run.finished', data: { run_id, node: 'execute', status: 'error', error: runError } });
                setStage(build, 'prototype');
                announce(build);
                return;
              }
              const reportUrl = fixtures.buildDone.report_url;
              if (version) Object.assign(version, { status: 'published', report_url: reportUrl });
              build.report_url = reportUrl;
              emit(id, { name: 'build.finished', data: { status: outcome, report_url: reportUrl, version: build.current_version } });
              emit(id, { name: 'run.finished', data: { run_id, node: 'execute', status: 'ok', error: null } });
              setStage(build, 'done');
              announce(build);
            },
          ],
          { stepMs: BUILD_STEP_MS, finishInSteps: true },
        );
      }),

    createVersion: (id) =>
      respond(() => {
        requireNoReview(findBuild(id));
        const build = findBuild(id);
        requireStage(build, ['prototype', 'done'], 'Wait for the build to finish, then start a new version.');
        const n = Math.max(0, ...build.versions.map((v) => v.n)) + 1;
        build.versions.push({ n, status: 'draft', report_url: null, created_at: now() });
        const refs = state.references.get(`${id}:${build.current_version}`);
        if (refs) {
          state.references.set(`${id}:${n}`, clone(refs));
          for (const image of refs.images) {
            const url = state.referenceFiles.get(`${id}:${build.current_version}:${image.file}`);
            if (url) state.referenceFiles.set(`${id}:${n}:${image.file}`, url);
          }
        }
        build.current_version = n;
        build.stage = 'prototype';
        touch(build);
        return build;
      }),

    fileUrl: (id, name) => state.referenceFiles.get(`${id}:${findBuild(id).current_version}:${name}`) || `/api/builds/${encodeURIComponent(id)}/files/${name.split('/').map(encodeURIComponent).join('/')}`,

    listTraces: (buildId) =>
      respond(() => newestFirst(state.traces.filter((t) => !buildId || t.build_id === buildId), (t) => t.started_at)),

    getRunCalls: (runId) =>
      respond((): RunCalls => {
        if (runId === fixtures.runCalls.run_id) return fixtures.runCalls;
        // A run before 3.0 (the fixture traces) has no recorded calls or settings snapshot; a mocked run
        // reports the settings in force and no calls (the mock calls no model).
        if (fixtures.traces.some((t) => t.run_id === runId)) return { run_id: runId, settings: null, calls: [], cost_usd_estimate: null, cost_complete: false };
        if (state.traces.some((t) => t.run_id === runId)) {
          const { stages, fallback_model, review_briefs } = state.settings;
          return { run_id: runId, settings: { stages, fallback_model, review_briefs }, calls: [], cost_usd_estimate: 0, cost_complete: true };
        }
        throw new ApiError(404, 'run_not_found', 'This run is not recorded.', { run_id: runId });
      }),

    getBuildCost: (id) =>
      respond((): BuildCost => {
        const build = findBuild(id);
        if (build.id === fixtures.buildCost.build_id) return fixtures.buildCost;
        return { build_id: build.id, cost_usd_estimate: null, complete: true, runs: [], prices_checked_on: null };
      }),

    getEngineStatus: () => respond(() => state.engine),

    engineLogin: () =>
      respond(() => {
        if (agentMode()) throw new ApiError(409, 'login_on_agent', "Run dsengine login on the agent's machine.");
        schedule([() => (state.engine = { ...state.engine, chrome_running: true, signed_in: true })]);
        return { run_id: nextId('r') };
      }),
  });
}
