// Typed client for ../contracts/api.md. Only relative /api URLs (Vite proxies them to :8000).
// With VITE_MOCK=1, `api` is the fixture-backed mock from src/mocks/ with the same signatures.
import { withAccessNotice } from '../features/access/accessNotice';
import { withServiceNotice } from '../features/settings/serviceNotice';
import { createMockApi } from '../mocks/api';
import {
  ApiError,
  arrayOf,
  type GenerationStatus,
  type Guard,
  isGenerationStatus,
  isSyntheticDataset,
  type SyntheticDataset,
  isAssessment,
  type Assessment,
  type FeasibilityDecision,
  isReferenceSet,
  isProposal,
  referenceValidation,
  type ReferenceSet,
  type ReferenceMode,
  isApiErrorBody,
  type Build,
  type BuildCost,
  type BriefReview,
  type BriefReviewApproval,
  type BriefReviewSave,
  type BuildSummary,
  type DesignPages,
  type Comment,
  type GenerationRequest,
  type Proposal,
  type EngineStatus,
  type Health,
  type Message,
  type Blueprint,
  type Context,
  type ContextUpdate,
  type Design,
  type DesignUpdate,
  isBlueprint,
  isBriefReview,
  isBuild,
  isBuildCost,
  isDesignPages,
  isRunCalls,
  isSettings,
  isSettingsCapabilities,
  isContext,
  isDesign,
  isOutline,
  isRunAccepted,
  isThemePreset,
  nullable,
  type Outline,
  type QuestionSelection,
  type ThemePreset,
  type NewBuild,
  oversizeError,
  type Recipe,
  type RunAccepted,
  type RunCalls,
  type Session,
  type Settings,
  type SettingsCapabilities,
  type SettingsUpdate,
  type Source,
  type SourcesUploaded,
  type SourceUri,
  SYNTHETIC_TOO_LARGE,
  syntheticOversizeError,
  type Trace,
  UPLOAD_TOO_LARGE,
} from './types';

export interface ApiClient {
  health(): Promise<Health>;
  /** Whether an access code is needed, and whether this browser's cookie carries a valid one. */
  getSession(): Promise<Session>;
  /** Sends the access code once; the backend answers with the session cookie. The code is never kept. */
  createSession(code: string): Promise<Session>;
  getSettings(): Promise<Settings>;
  /** Any validation issue answers `422 invalid_settings` (`detail.issues`, read with `artifactIssues`) and saves nothing. */
  updateSettings(update: SettingsUpdate): Promise<Settings>;
  /** The model table, defaults and limits the stage editor validates against (3.0). */
  getSettingsCapabilities(): Promise<SettingsCapabilities>;
  /** Newest `updated_at` first. */
  listBuilds(): Promise<BuildSummary[]>;
  createBuild(body: NewBuild): Promise<Build>;
  getBuild(buildId: string): Promise<Build>;
  uploadSources(buildId: string, files: File[]): Promise<SourcesUploaded>;
  addSource(buildId: string, body: SourceUri): Promise<Source>;
  getFeasibility(buildId: string): Promise<Assessment>;
  checkFeasibility(buildId: string): Promise<RunAccepted>;
  decideFeasibility(buildId: string, assessmentId: string, decisions: FeasibilityDecision[]): Promise<Assessment>;
  reapplyComments(buildId: string, assessmentId: string, batchId: string): Promise<RunAccepted>;
  discardComments(buildId: string, assessmentId: string): Promise<Assessment>;
  getReferences(buildId: string): Promise<ReferenceSet | null>;
  uploadReferences(buildId: string, files: File[], mode: ReferenceMode, instructions: string): Promise<RunAccepted>;
  deleteReferences(buildId: string): Promise<void>;
  /** Proposes sample-data columns from the current recreate reference set (no data source needed). */
  proposeSyntheticSchema(buildId: string, referenceSetId: string): Promise<RunAccepted>;
  getSyntheticProposal(buildId: string): Promise<Proposal | null>;
  /** The explicit Generate sample data action; a retry of the same request reuses its `generation_key`. */
  generateSyntheticData(buildId: string, request: GenerationRequest): Promise<RunAccepted>;
  /** Successful sample datasets with their provenance (seed, checksum, generator, assumptions). */
  listSyntheticDatasets(buildId: string): Promise<SyntheticDataset[]>;
  /** The latest 20 generation jobs, newest first: what a reload or reconnect recovers. */
  listSyntheticJobs(buildId: string): Promise<GenerationStatus[]>;
  /** One job's persisted state; `404` when the backend never registered the key. Never starts work. */
  getSyntheticJob(buildId: string, generationKey: string): Promise<GenerationStatus>;
  /** URL of a synthetic source's CSV attachment (`synthetic-sample.csv`). */
  syntheticCsvUrl(buildId: string, sourceId: string): string;
  uploadStyleImages(buildId: string, files: File[]): Promise<RunAccepted>;
  startResearch(buildId: string, prompt: string): Promise<RunAccepted>;
  /** Oldest first: assistant explanations, refusals and revise outcomes (2.0 has no chat input). */
  listMessages(buildId: string): Promise<Message[]>;
  /** Saves the "about this data" notes (at most 4000 chars) and drafts the Context (node `context`). */
  draftContext(buildId: string, notes?: string): Promise<RunAccepted>;
  getContext(buildId: string): Promise<Context | null>;
  updateContext(buildId: string, context: ContextUpdate): Promise<Context>;
  /** Needs no open issues; proposes or revalidates the Outline (node `outline_propose`). */
  confirmContext(buildId: string): Promise<RunAccepted>;
  getOutline(buildId: string): Promise<Outline | null>;
  /** Re-proposes explicitly, keeping `other` questions and unchanged selections. */
  proposeOutline(buildId: string): Promise<RunAccepted>;
  /** 1-100 questions per call; code only, no run. */
  updateOutlineSelection(buildId: string, questions: QuestionSelection[]): Promise<Outline>;
  /** 1-1000 chars; `sectionId` null adds a new section. */
  addOutlineQuestions(buildId: string, sectionId: string | null, text: string): Promise<RunAccepted>;
  suggestOutlineQuestions(buildId: string, sectionId: string): Promise<RunAccepted>;
  /** Needs 1-24 selected questions; prefills a missing Design. */
  confirmOutline(buildId: string): Promise<Build>;
  listDesignPresets(buildId: string): Promise<ThemePreset[]>;
  getDesign(buildId: string): Promise<Design | null>;
  /** Replaces the Design with a fresh prefill (code only). */
  prefillDesign(buildId: string): Promise<Design>;
  updateDesign(buildId: string, design: DesignUpdate): Promise<Design>;
  /** Needs no open issues; drafts the Blueprint (node `blueprint`). */
  confirmDesign(buildId: string): Promise<RunAccepted>;
  getBlueprint(buildId: string): Promise<Blueprint | null>;
  regenerateBlueprint(buildId: string): Promise<RunAccepted>;
  /** Needs a ready assessment and an ok row; lays out the spec and renders (node `prototype`). */
  acceptBlueprint(buildId: string): Promise<RunAccepted>;
  /** The current version's per-page layout, published briefs and the pending brief review, if any (3.0). */
  getDesignPages(buildId: string): Promise<DesignPages>;
  /** Saves an edit of the pending review's brief: `409 brief_review_conflict` (`detail.revision`) on a stale revision, `404 review_not_found`. */
  saveBriefReview(buildId: string, body: BriefReviewSave): Promise<BriefReview>;
  /** Approves what the user saw (revision and sha256); needs no issues (`409 artifact_invalid`) and fresh inputs (`409 brief_review_stale`). */
  approveBriefReview(buildId: string, body: BriefReviewApproval): Promise<RunAccepted>;
  /** Drops the unpublished candidate; repeating it returns the current Build. */
  cancelBriefReview(buildId: string, reviewId: string): Promise<Build>;
  /** Markdown of one build doc. */
  getDoc(buildId: string, path: string): Promise<string>;
  /** The current spec JSON, for read-only display. */
  getSpec(buildId: string): Promise<unknown>;
  /** iframe src of the prototype page; `v` busts the cache when the spec changes. */
  prototypeUrl(buildId: string, specVersion: number | null, layer?: 'all' | 'decoration'): string;
  /** 1 to 20 comments in one batch. */
  postComments(buildId: string, comments: Comment[]): Promise<RunAccepted>;
  runAudit(buildId: string): Promise<RunAccepted>;
  compileRecipe(buildId: string): Promise<Recipe>;
  runBuild(buildId: string): Promise<RunAccepted>;
  createVersion(buildId: string): Promise<Build>;
  /** URL of a file in the current version folder (`background_p1.png`, `screens/<file>`). */
  fileUrl(buildId: string, name: string): string;
  /** Newest first. */
  listTraces(buildId?: string): Promise<Trace[]>;
  /** The Settings snapshot a run used and its model calls in order; `404 run_not_found` for an unknown run (3.0). */
  getRunCalls(runId: string): Promise<RunCalls>;
  /** Every run of the build, newest first, with its estimated cost (3.0). */
  getBuildCost(buildId: string): Promise<BuildCost>;
  getEngineStatus(): Promise<EngineStatus>;
  engineLogin(): Promise<RunAccepted>;
}

const UNREACHABLE = "Can't reach the backend. Start it on port 8000, then try again.";

const seg = encodeURIComponent;
const segs = (path: string) => path.split('/').map(seg).join('/');
const buildPath = (buildId: string, rest = '') => `/builds/${seg(buildId)}${rest}`;

async function toApiError(res: Response): Promise<ApiError> {
  const body: unknown = await res.json().catch(() => null);
  if (isApiErrorBody(body)) {
    const { code, message, detail } = body.error;
    return new ApiError(res.status, code, message, detail);
  }
  // The Vite proxy answers 502-504 without a body when nothing listens on :8000.
  // Cloud Run answers an oversized body with its own HTML page, not the error shape.
  if (res.status === 413) return new ApiError(413, 'payload_too_large', UPLOAD_TOO_LARGE);
  if (res.status >= 502 && res.status <= 504) return new ApiError(res.status, 'network_error', UNREACHABLE);
  return new ApiError(res.status, 'http_error', `The backend answered ${res.status} without details. Check its log, then try again.`);
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { 'Content-Type': 'application/json' };
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, 'network_error', UNREACHABLE);
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

const json = async <T>(method: string, path: string, body?: unknown): Promise<T> =>
  (await (await send(method, path, body)).json()) as T;

const text = async (path: string): Promise<string> => (await send('GET', path)).text();

/** Checks the upload limit before anything is sent. */
async function upload<T>(path: string, files: File[]): Promise<T> {
  const tooLarge = oversizeError(files);
  if (tooLarge) throw tooLarge;
  return json<T>('POST', path, filesForm(files));
}

function filesForm(files: File[]): FormData {
  const form = new FormData();
  for (const file of files) form.append('files', file);
  return form;
}

async function assessment(method: string, path: string, body?: unknown): Promise<Assessment> {
  const value: unknown = await json(method, path, body);
  if (!isAssessment(value)) throw new ApiError(502, 'invalid_response', "Couldn't read feasibility. Try again.");
  return value;
}

/** A JSON response checked against its contract guard; `unreadable` is the message when it doesn't match. */
async function checkedJson<T>(method: string, path: string, guard: Guard<T>, unreadable: string, body?: unknown): Promise<T> {
  const value: unknown = await json(method, path, body);
  if (!guard(value)) throw new ApiError(502, 'invalid_response', unreadable);
  return value;
}

const UNREADABLE = {
  context: "Couldn't read the context. Try again.",
  outline: "Couldn't read the outline. Try again.",
  design: "Couldn't read the design. Try again.",
  blueprint: "Couldn't read the blueprint. Try again.",
  settings: "Couldn't read the settings: the backend may predate API 3.0. Update it, then try again.",
  capabilities: "Couldn't read the model list. Try again.",
  designPages: "Couldn't read the page designs. Try again.",
  review: "Couldn't read the brief review. Try again.",
  calls: "Couldn't read this run's model calls. Try again.",
  cost: "Couldn't read the cost estimate. Try again.",
  build: "Couldn't read this build: the backend may predate API 2.0. Update it, then try again.",
};

/** A staged action's `202 {run_id}`. */
const accepted = (path: string, body?: unknown) => checkedJson('POST', path, isRunAccepted, "Couldn't read the server's answer. Reload the page.", body);

export const httpApi: ApiClient = {
  health: () => json('GET', '/health'),
  getSession: () => json('GET', '/session'),
  createSession: (code) => json('POST', '/session', { code }),
  getSettings: () => checkedJson('GET', '/settings', isSettings, UNREADABLE.settings),
  updateSettings: (update) => checkedJson('PUT', '/settings', isSettings, UNREADABLE.settings, update),
  getSettingsCapabilities: () => checkedJson('GET', '/settings/capabilities', isSettingsCapabilities, UNREADABLE.capabilities),
  listBuilds: () => json('GET', '/builds'),
  createBuild: (body) => checkedJson('POST', '/builds', isBuild, UNREADABLE.build, body),
  getBuild: (id) => checkedJson('GET', buildPath(id), isBuild, UNREADABLE.build),
  uploadSources: (id, files) => upload(buildPath(id, '/sources/upload'), files),
  addSource: (id, body) => json('POST', buildPath(id, '/sources'), body),
  getFeasibility: (id) => assessment('GET', buildPath(id, '/feasibility')),
  checkFeasibility: (id) => json('POST', buildPath(id, '/feasibility/check')),
  decideFeasibility: (id, assessmentId, decisions) => assessment('POST', buildPath(id, '/feasibility/decisions'), { assessment_id: assessmentId, decisions }),
  reapplyComments: (id, assessmentId, batchId) => json('POST', buildPath(id, '/feasibility/reapply'), { assessment_id: assessmentId, batch_id: batchId }),
  discardComments: (id, assessmentId) => assessment('DELETE', buildPath(id, `/feasibility/pending-comments?assessment_id=${seg(assessmentId)}`)),
  getReferences: async (id) => {
    const value: unknown = await json('GET', buildPath(id, '/reference-images'));
    if (value !== null && !isReferenceSet(value)) throw new ApiError(502, 'invalid_response', "Couldn't read the saved references. Try again.");
    return value;
  },
  uploadReferences: async (id, files, mode, instructions) => {
    const problem = referenceValidation(files, mode, instructions);
    if (problem) throw new ApiError(422, 'invalid_source', problem);
    const form = filesForm(files);
    form.append('mode', mode);
    form.append('instructions', instructions);
    try {
      return await json('POST', buildPath(id, '/reference-images'), form);
    } catch (error) {
      if (error instanceof ApiError && error.status === 413) throw new ApiError(413, error.code, 'Reference images exceed the upload limit. Use at most 5 MiB each and 15 MiB total.');
      if (error instanceof ApiError && error.status === 422) throw new ApiError(422, error.code, 'Could not read these reference images. Use valid, non-animated PNG/JPEG images, at most 20 million pixels each, and instructions up to 2000 characters.');
      throw error;
    }
  },
  deleteReferences: async (id) => { await send('DELETE', buildPath(id, '/reference-images')); },
  proposeSyntheticSchema: (id, referenceSetId) => json('POST', buildPath(id, '/synthetic-data/proposal'), { reference_set_id: referenceSetId }),
  getSyntheticProposal: async (id) => {
    const value: unknown = await json('GET', buildPath(id, '/synthetic-data/proposal'));
    if (value !== null && !isProposal(value)) throw new ApiError(502, 'invalid_response', "Couldn't read the proposed schema. Try again.");
    return value;
  },
  generateSyntheticData: async (id, request) => {
    const tooLarge = syntheticOversizeError(request);
    if (tooLarge) throw tooLarge;
    try {
      return await json('POST', buildPath(id, '/synthetic-data'), request);
    } catch (error) {
      // The generic 413 text is about 32 MB CSV uploads; this route's limit is 64 KiB of JSON.
      if (error instanceof ApiError && error.status === 413) throw new ApiError(413, error.code, SYNTHETIC_TOO_LARGE, error.detail);
      throw error;
    }
  },
  listSyntheticDatasets: (id) => checkedJson('GET', buildPath(id, '/synthetic-data'), arrayOf(isSyntheticDataset), "Couldn't read the sample data details. Try again."),
  listSyntheticJobs: (id) => checkedJson('GET', buildPath(id, '/synthetic-data/jobs'), arrayOf(isGenerationStatus), "Couldn't read the sample-data runs. Try again."),
  getSyntheticJob: (id, key) => checkedJson('GET', buildPath(id, `/synthetic-data/jobs/${seg(key)}`), isGenerationStatus, "Couldn't read the sample-data run. Try again."),
  syntheticCsvUrl: (id, sourceId) => `/api${buildPath(id, `/synthetic-data/${seg(sourceId)}/csv`)}`,
  uploadStyleImages: (id, files) => upload(buildPath(id, '/style-images'), files),
  startResearch: (id, prompt) => json('POST', buildPath(id, '/research'), { prompt }),
  listMessages: (id) => json('GET', buildPath(id, '/messages')),
  draftContext: (id, notes) => accepted(buildPath(id, '/context'), notes === undefined ? {} : { notes }),
  getContext: (id) => checkedJson('GET', buildPath(id, '/context'), nullable(isContext), UNREADABLE.context),
  updateContext: (id, context) => checkedJson('PUT', buildPath(id, '/context'), isContext, UNREADABLE.context, context),
  confirmContext: (id) => accepted(buildPath(id, '/context/confirm')),
  getOutline: (id) => checkedJson('GET', buildPath(id, '/outline'), nullable(isOutline), UNREADABLE.outline),
  proposeOutline: (id) => accepted(buildPath(id, '/outline/propose')),
  updateOutlineSelection: (id, questions) => checkedJson('PUT', buildPath(id, '/outline/selection'), isOutline, UNREADABLE.outline, { questions }),
  addOutlineQuestions: (id, sectionId, text) => accepted(buildPath(id, '/outline/other'), { section_id: sectionId, text }),
  suggestOutlineQuestions: (id, sectionId) => accepted(buildPath(id, '/outline/suggest'), { section_id: sectionId }),
  confirmOutline: (id) => checkedJson('POST', buildPath(id, '/outline/confirm'), isBuild, "Couldn't read the build. Reload the page."),
  listDesignPresets: (id) => checkedJson('GET', buildPath(id, '/design/presets'), arrayOf(isThemePreset), "Couldn't read the design presets. Try again."),
  getDesign: (id) => checkedJson('GET', buildPath(id, '/design'), nullable(isDesign), UNREADABLE.design),
  prefillDesign: (id) => checkedJson('POST', buildPath(id, '/design/prefill'), isDesign, UNREADABLE.design),
  updateDesign: (id, design) => checkedJson('PUT', buildPath(id, '/design'), isDesign, UNREADABLE.design, design),
  confirmDesign: (id) => accepted(buildPath(id, '/design/confirm')),
  getBlueprint: (id) => checkedJson('GET', buildPath(id, '/blueprint'), nullable(isBlueprint), UNREADABLE.blueprint),
  regenerateBlueprint: (id) => accepted(buildPath(id, '/blueprint/regenerate')),
  acceptBlueprint: (id) => accepted(buildPath(id, '/blueprint/accept')),
  getDesignPages: (id) => checkedJson('GET', buildPath(id, '/design-pages'), isDesignPages, UNREADABLE.designPages),
  saveBriefReview: (id, body) => checkedJson('PUT', buildPath(id, '/briefs/review'), isBriefReview, UNREADABLE.review, body),
  approveBriefReview: (id, body) => accepted(buildPath(id, '/briefs/review/approve'), body),
  cancelBriefReview: (id, reviewId) => checkedJson('POST', buildPath(id, '/briefs/review/cancel'), isBuild, UNREADABLE.build, { review_id: reviewId }),
  getDoc: (id, path) => text(buildPath(id, `/docs/${segs(path)}`)),
  getSpec: (id) => json('GET', buildPath(id, '/spec')),
  prototypeUrl: (id, v, layer = 'all') =>
    `/api${buildPath(id, '/prototype')}?layer=${layer}&v=${v ?? 0}`,
  postComments: (id, comments) => json('POST', buildPath(id, '/comments'), { comments }),
  runAudit: (id) => json('POST', buildPath(id, '/audit')),
  compileRecipe: (id) => json('POST', buildPath(id, '/recipe')),
  runBuild: (id) => json('POST', buildPath(id, '/run')),
  createVersion: (id) => json('POST', buildPath(id, '/versions')),
  fileUrl: (id, name) => `/api${buildPath(id, `/files/${segs(name)}`)}`,
  listTraces: (buildId) => json('GET', buildId ? `/traces?build_id=${seg(buildId)}` : '/traces'),
  getRunCalls: (runId) => checkedJson('GET', `/traces/${seg(runId)}/calls`, isRunCalls, UNREADABLE.calls),
  getBuildCost: (id) => checkedJson('GET', buildPath(id, '/cost'), isBuildCost, UNREADABLE.cost),
  getEngineStatus: () => json('GET', '/engine/status'),
  engineLogin: () => json('POST', '/engine/login'),
};

export const isMockMode = import.meta.env.VITE_MOCK === '1';

/**
 * The client every component uses; a 503 that points at Settings also raises the app banner, and a
 * `401 access_required` sends the app back to the access-code gate.
 */
export const api: ApiClient = withAccessNotice(withServiceNotice(isMockMode ? createMockApi() : httpApi));
