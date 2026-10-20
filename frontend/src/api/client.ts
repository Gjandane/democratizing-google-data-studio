// Typed client for ../contracts/api.md. Only relative /api URLs (Vite proxies them to :8000).
// With VITE_MOCK=1, `api` is the fixture-backed mock from src/mocks/ with the same signatures.
import { withAccessNotice } from '../features/access/accessNotice';
import { withServiceNotice } from '../features/settings/serviceNotice';
import { createMockApi } from '../mocks/api';
import {
  ApiError,
  isAssessment,
  type Assessment,
  type FeasibilityDecision,
  isReferenceSet,
  referenceValidation,
  type ReferenceSet,
  type ReferenceMode,
  isApiErrorBody,
  type Build,
  type BuildSummary,
  type Comment,
  type EngineStatus,
  type Health,
  type Message,
  type MessageAccepted,
  type NewBuild,
  oversizeError,
  type Recipe,
  type RunAccepted,
  type Session,
  type Settings,
  type SettingsUpdate,
  type Source,
  type SourcesUploaded,
  type SourceUri,
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
  updateSettings(update: SettingsUpdate): Promise<Settings>;
  /** Newest `updated_at` first. */
  listBuilds(): Promise<BuildSummary[]>;
  createBuild(body: NewBuild): Promise<Build>;
  getBuild(buildId: string): Promise<Build>;
  uploadSources(buildId: string, files: File[]): Promise<SourcesUploaded>;
  addSource(buildId: string, body: SourceUri): Promise<Source>;
  getFeasibility(buildId: string): Promise<Assessment>;
  checkFeasibility(buildId: string): Promise<RunAccepted>;
  decideFeasibility(buildId: string, assessmentId: string, decisions: FeasibilityDecision[]): Promise<Assessment>;
  getReferences(buildId: string): Promise<ReferenceSet | null>;
  uploadReferences(buildId: string, files: File[], mode: ReferenceMode, instructions: string): Promise<RunAccepted>;
  deleteReferences(buildId: string): Promise<void>;
  uploadStyleImages(buildId: string, files: File[]): Promise<RunAccepted>;
  startResearch(buildId: string, prompt: string): Promise<RunAccepted>;
  startInterview(buildId: string): Promise<RunAccepted>;
  /** Oldest first. */
  listMessages(buildId: string): Promise<Message[]>;
  sendMessage(buildId: string, text: string): Promise<MessageAccepted>;
  generatePlan(buildId: string): Promise<RunAccepted>;
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

export const httpApi: ApiClient = {
  health: () => json('GET', '/health'),
  getSession: () => json('GET', '/session'),
  createSession: (code) => json('POST', '/session', { code }),
  getSettings: () => json('GET', '/settings'),
  updateSettings: (update) => json('PUT', '/settings', update),
  listBuilds: () => json('GET', '/builds'),
  createBuild: (body) => json('POST', '/builds', body),
  getBuild: (id) => json('GET', buildPath(id)),
  uploadSources: (id, files) => upload(buildPath(id, '/sources/upload'), files),
  addSource: (id, body) => json('POST', buildPath(id, '/sources'), body),
  getFeasibility: (id) => assessment('GET', buildPath(id, '/feasibility')),
  checkFeasibility: (id) => json('POST', buildPath(id, '/feasibility/check')),
  decideFeasibility: (id, assessmentId, decisions) => assessment('POST', buildPath(id, '/feasibility/decisions'), { assessment_id: assessmentId, decisions }),
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
  uploadStyleImages: (id, files) => upload(buildPath(id, '/style-images'), files),
  startResearch: (id, prompt) => json('POST', buildPath(id, '/research'), { prompt }),
  startInterview: (id) => json('POST', buildPath(id, '/interview/start')),
  listMessages: (id) => json('GET', buildPath(id, '/messages')),
  sendMessage: (id, message) => json('POST', buildPath(id, '/messages'), { text: message }),
  generatePlan: (id) => json('POST', buildPath(id, '/plan')),
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
  getEngineStatus: () => json('GET', '/engine/status'),
  engineLogin: () => json('POST', '/engine/login'),
};

export const isMockMode = import.meta.env.VITE_MOCK === '1';

/**
 * The client every component uses; a 503 that points at Settings also raises the app banner, and a
 * `401 access_required` sends the app back to the access-code gate.
 */
export const api: ApiClient = withAccessNotice(withServiceNotice(isMockMode ? createMockApi() : httpApi));
