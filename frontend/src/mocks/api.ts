// Fixture-backed fake of the backend API (VITE_MOCK=1, and every test). Same signatures as
// httpApi in src/api/client.ts; state is in memory, seeded from ../contracts/fixtures/api/.
// Long-running actions answer at once with a run id and play their events on the fake stream.
import type { ApiClient } from '../api/client';
import {
  ApiError,
  type Assessment,
  referenceValidation,
  type ReferenceSet,
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
  type Trace,
} from '../api/types';
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
/** The chat-side runs the mock can fail (setMockRunFailure). */
export type MockFailingNode = 'plan' | 'interview';

/** The access code the mock accepts when the gate is on (setMockSession). */
export const MOCK_ACCESS_CODE = 'mock-access-code';

interface MockState {
  assessments: Map<string, Assessment>;
  assessmentBusy: Set<string>;
  pendingIssueIds: Map<string, Set<string>>;
  references: Map<string, ReferenceSet>;
  referenceFiles: Map<string, string>;
  referenceBusy: Set<string>;
  session: Session;
  builds: Map<string, Build>;
  messages: Map<string, Message[]>;
  settings: Settings;
  traces: Trace[];
  engine: EngineStatus;
  engineBusy: boolean;
  buildOutcome: MockBuildOutcome;
  screencast: boolean;
  serviceFault: MockServiceFault;
  /** Nodes whose next runs fail, with their `run.finished` error text (null: no text). */
  runFailures: Partial<Record<MockFailingNode, string | null>>;
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
    session: { required: false, ok: true },
    builds,
    messages: new Map([[fixtures.build.id, clone(fixtures.messages)]]),
    settings: clone(fixtures.settings),
    traces: clone(fixtures.traces),
    engine: clone(fixtures.engineStatusLocal),
    engineBusy: false,
    buildOutcome: 'ok',
    screencast: true,
    serviceFault: null,
    runFailures: {},
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

/** Makes model actions or Google Cloud actions answer 503 until reset with null. For tests and the dev server. */
export function setMockServiceFault(fault: MockServiceFault): void {
  state.serviceFault = fault;
}

/**
 * Makes every next `node` run fail with `error` as its `run.finished` text (null: no text), until
 * reset with undefined. A failed plan goes back to the Interview stage. For tests and the dev server.
 */
export function setMockRunFailure(node: MockFailingNode, error: string | null | undefined): void {
  if (error === undefined) delete state.runFailures[node];
  else state.runFailures[node] = error;
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
const UNLOCKED_SETTINGS = new Set(['planner_model', 'worker_model']);

/** Calls that work without the access code (contracts/api.md, Access), plus the two URL builders. */
const UNGATED = new Set(['health', 'getSession', 'createSession', 'prototypeUrl', 'fileUrl']);

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
        const { google_api_key, ...fields } = update;
        Object.assign(state.settings, fields);
        // The key is write-only: the mock only remembers that one is set.
        if (google_api_key !== undefined) state.settings.google_api_key_set = google_api_key !== '';
        return state.settings;
      }),

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
          ready_for_plan: false,
        };
        state.builds.set(build.id, build);
        return build;
      }),

    getBuild: (id) => respond(() => findBuild(id)),

    uploadSources: (id, files) =>
      respond(() => {
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
      const build = findBuild(id);
      requireStage(build, ['connect', 'interview', 'prototype'], 'Check feasibility before building.');
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
      return updated;
    }),
    reapplyComments: (id, assessmentId, batchId) => respond(() => {
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
      const build = findBuild(id);
      requireStage(build, ['connect', 'interview', 'prototype'], 'Start a new version to change references.');
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
        state.references.set(key, { ...clone(fixtures.referenceSet), id: nextId('s'), mode, instructions, images });
        state.referenceBusy.delete(id);
        emit(id, { name: 'docs.updated', data: { docs: clone(build.docs) } });
      }]);
    }),
    deleteReferences: (id) => respond(() => {
      const build = findBuild(id);
      requireStage(build, ['connect', 'interview', 'prototype'], 'Start a new version to change references.');
      if (state.referenceBusy.has(id)) throw new ApiError(409, 'build_busy', 'Wait for the current reference upload.');
      state.references.delete(`${id}:${build.current_version}`);
    }),
    uploadStyleImages: (id, files) =>
      respond(() => {
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
        const build = findBuild(id);
        requireModel();
        if (!prompt.trim()) throw invalid('invalid_request', 'Describe what to research.');
        return startRun(build, 'research', (runId) => [
          () => emit(id, { name: 'node.progress', data: { run_id: runId, node: 'research', text: 'Searching the web' } }),
          () => addSources(build, [newSource(build, 'research', 'research_findings')]),
        ]);
      }),

    startInterview: (id) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(build, ['connect', 'interview'], 'The interview has already finished for this build.');
        requireModel();
        setStage(build, 'interview');
        const firstQuestion = fixtures.messages[0]?.text ?? 'Who will read this dashboard?';
        return startRun(build, 'interview', () => streamAssistant(build.id, firstQuestion, 'interview'));
      }),

    listMessages: (id) =>
      respond(() => {
        findBuild(id);
        return state.messages.get(id) ?? [];
      }),

    sendMessage: (id, text) =>
      respond(() => {
        const build = findBuild(id);
        requireModel();
        if (!text.trim()) throw invalid('invalid_request', 'Type a message first.');
        const message: Message = { id: nextId('m'), role: 'user', text, node: null, created_at: now() };
        const messages = [...(state.messages.get(id) ?? []), message];
        state.messages.set(id, messages);
        touch(build);
        const answered = messages.filter((m) => m.role === 'user').length;
        const enough = answered >= 2 && !build.ready_for_plan;
        const reply = enough
          ? "Thanks, that's enough to plan. Select **Generate plan** when you're ready, or keep adding detail."
          : (fixtures.messages[2]?.text ?? 'Tell me more.');
        const failure = failureOf('interview');
        const run = failure()
          ? startRun(build, 'interview', () => [], { failure })
          : startRun(build, 'interview', () => [
              ...streamAssistant(id, reply, 'interview'),
              () => {
                if (!enough) return;
                build.ready_for_plan = true;
                announce(build);
              },
            ]);
        return { ...run, message_id: message.id };
      }),

    generatePlan: (id) =>
      respond(() => {
        const build = findBuild(id);
        requireStage(
          build,
          ['interview', 'prototype'],
          build.stage === 'connect' ? fixtures.error.error.message : `Planning isn't available while the build is in ${build.stage}.`,
        );
        requireModel();
        const from = build.stage;
        setStage(build, 'plan');
        const failure = failureOf('plan');
        if (failure()) {
          return startRun(
            build,
            'plan',
            (runId) => [
              () => emit(id, { name: 'node.progress', data: { run_id: runId, node: 'plan', text: 'Reading the data profile' } }),
              () => setStage(build, from),
            ],
            { failure },
          );
        }
        return startRun(build, 'plan', (runId) => [
          ...fixtures.build.docs.map(
            (doc) => () => emit(id, { name: 'node.progress', data: { run_id: runId, node: 'plan', text: `Writing ${doc.path}` } }),
          ),
          () => {
            build.docs = clone(fixtures.build.docs);
            emit(id, { name: 'docs.updated', data: { docs: clone(build.docs) } });
          },
          () => {
            const assessment = clone(currentAssessment(id));
            assessment.id = `assessment_${nextId('r')}`; assessment.state = 'ready'; assessment.prototype_stale = false;
            state.assessments.set(id, assessment);
            build.spec_version = (build.spec_version ?? 0) + 1;
            emit(id, { name: 'prototype.updated', data: { spec_version: build.spec_version } });
            setStage(build, 'prototype');
            announce(build);
          },
        ]);
      }),

    getDoc: (id, path) =>
      respond(() => {
        const doc = findBuild(id).docs.find((d) => d.path === path);
        if (!doc) throw new ApiError(404, 'doc_not_found', `There's no ${path} in this build. Generate the plan first.`);
        return `# ${doc.title}\n\n*${doc.type}* · mock document for \`${doc.path}\`.\n\n- Written by the planner from the interview.\n- Shown read-only here.\n`;
      }),

    getSpec: (id) =>
      respond(() => {
        const build = findBuild(id);
        if (build.spec_version === null) throw new ApiError(404, 'spec_not_found', 'There is no spec yet. Generate the plan first.');
        return { spec_version: build.spec_version };
      }),

    prototypeUrl: (id, v, layer = 'all') => {
      const path = `/api/builds/${encodeURIComponent(id)}/prototype?layer=${layer}&v=${v ?? 0}`;
      // Without blob URLs (some test DOMs) the plain path; tests load the fixture into their iframe themselves.
      if (typeof URL.createObjectURL !== 'function') return path;
      const cached = blobUrls.get(path);
      if (cached) return cached;
      const hide = '<style>[data-kind="component"]{visibility:hidden}</style></head>';
      const html = layer === 'decoration' ? fixtures.prototypeHtml.replace('</head>', hide) : fixtures.prototypeHtml;
      // A blob URL made by this page is same-origin, so the overlay can read the iframe's DOM.
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
      blobUrls.set(path, url);
      return url;
    },

    postComments: (id, comments) =>
      respond(() => {
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
        return startRun(build, 'revise', (runId) => [
          () => emit(id, { name: 'node.progress', data: { run_id: runId, node: 'revise', text: `Applying ${comments.length} comments` } }),
          () => {
            build.spec_version = (build.spec_version ?? 0) + 1;
            touch(build);
            emit(id, { name: 'prototype.updated', data: { spec_version: build.spec_version } });
            announce(build);
          },
        ]);
      }),

    runAudit: (id) =>
      respond(() => {
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
        const build = findBuild(id);
        if (build.spec_version === null) throw new ApiError(409, 'wrong_stage', 'Generate the plan before the recipe.', { stage: build.stage });
        return fixtures.recipe;
      }),

    runBuild: (id) =>
      respond(() => {
        const build = findBuild(id);
        if (state.engineBusy) throw new ApiError(409, 'engine_busy', 'Another build is running in Data Studio. Wait for it to finish, then try again.');
        if (agentMode() && !state.engine.agent_connected) {
          throw new ApiError(424, 'agent_offline', "The build agent isn't connected. Start it on the machine with Chrome, then build again.");
        }
        if (!state.engine.signed_in) {
          throw new ApiError(424, 'engine_not_signed_in', agentMode() ? "Run dsengine login on the agent's machine, then build again." : 'Sign in to Google first, then build again.');
        }
        requireStage(build, ['prototype'], 'Build from the Prototype stage.');
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

    getEngineStatus: () => respond(() => state.engine),

    engineLogin: () =>
      respond(() => {
        if (agentMode()) throw new ApiError(409, 'login_on_agent', "Run dsengine login on the agent's machine.");
        schedule([() => (state.engine = { ...state.engine, chrome_running: true, signed_in: true })]);
        return { run_id: nextId('r') };
      }),
  });
}
