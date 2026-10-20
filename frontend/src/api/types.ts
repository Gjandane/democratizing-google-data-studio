// Types and runtime guards for ../contracts/api.md 1.5 (and the dashboard-intent and synthetic-data
// contracts it cites). Names in the "Types" blocks are used exactly; the rest are named after their
// endpoint or event.
// A guard accepts exactly the contract's keys with the contract's JSON types (extra keys fail),
// so tests/contract.test.ts can check the shared fixtures with them.

// ---------- Guard toolkit ----------

/** `problems`, when given, collects one line per mismatch ("$.stage: expected one of ..."). */
export type Guard<T> = (value: unknown, path?: string, problems?: string[]) => value is T;

function fail(path: string, problems: string[] | undefined, message: string): false {
  problems?.push(`${path}: ${message}`);
  return false;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function primitive<T>(test: (v: unknown) => boolean, expected: string): Guard<T> {
  return (v, path = '$', problems): v is T => test(v) || fail(path, problems, `expected ${expected}`);
}

const isString = primitive<string>((v) => typeof v === 'string', 'a string');
const isInt = primitive<number>(Number.isInteger, 'an integer');
const isBoolean = primitive<boolean>((v) => typeof v === 'boolean', 'a boolean');
const isObject = primitive<Record<string, unknown>>(isRecord, 'an object');

function oneOf<const T extends readonly string[]>(values: T): Guard<T[number]> {
  return (v, path = '$', problems): v is T[number] =>
    (typeof v === 'string' && values.includes(v)) ||
    fail(path, problems, `expected one of ${values.join(' | ')}, got ${JSON.stringify(v)}`);
}

function nullable<T>(guard: Guard<T>): Guard<T | null> {
  return (v, path = '$', problems): v is T | null => v === null || guard(v, path, problems);
}

export function arrayOf<T>(guard: Guard<T>): Guard<T[]> {
  return (v, path = '$', problems): v is T[] => {
    if (!Array.isArray(v)) return fail(path, problems, 'expected an array');
    let ok = true;
    v.forEach((item, i) => {
      ok = guard(item, `${path}[${i}]`, problems) && ok;
    });
    return ok;
  };
}

type Fields<T> = { [K in keyof T]-?: Guard<T[K]> };

function shape<T extends object>(fields: Fields<T>): Guard<T> {
  const guards = fields as Record<string, Guard<unknown>>;
  return (v, path = '$', problems): v is T => {
    if (!isRecord(v)) return fail(path, problems, 'expected an object');
    let ok = true;
    for (const [key, guard] of Object.entries(guards)) {
      if (!Object.hasOwn(v, key)) ok = fail(`${path}.${key}`, problems, 'missing');
      else ok = guard(v[key], `${path}.${key}`, problems) && ok;
    }
    for (const key of Object.keys(v)) {
      if (!Object.hasOwn(guards, key)) ok = fail(`${path}.${key}`, problems, 'not in the contract');
    }
    return ok;
  };
}

/** Every mismatch between `value` and `guard`, empty when it conforms. */
export function problemsOf<T>(guard: Guard<T>, value: unknown, path = '$'): string[] {
  const problems: string[] = [];
  guard(value, path, problems);
  return problems;
}

// ---------- Contract types ----------

export const STAGES = ['connect', 'interview', 'plan', 'prototype', 'build', 'done'] as const;
export const ARCHETYPES = ['executive', 'storytelling', 'operational', 'analytical'] as const;
export const MODES = ['data', 'research'] as const;
export const COLUMN_TYPES = ['string', 'number', 'date', 'datetime', 'boolean', 'geo'] as const;
export const SOURCE_KINDS = ['upload', 'gcs', 'bigquery', 'research', 'synthetic'] as const;
export const VERSION_STATUSES = ['draft', 'building', 'published', 'failed'] as const;
export const MESSAGE_ROLES = ['user', 'assistant', 'system'] as const;

export type Stage = (typeof STAGES)[number];
export type Archetype = (typeof ARCHETYPES)[number];
export type Mode = (typeof MODES)[number];
export type ColumnType = (typeof COLUMN_TYPES)[number];
export type SourceKind = (typeof SOURCE_KINDS)[number];

export interface Column {
  name: string;
  type: ColumnType;
  sample: string[];
}

export interface Source {
  id: string;
  kind: SourceKind;
  name: string;
  /** project.dataset.table */
  bq_table: string;
  row_count: number;
  columns: Column[];
}

export type ReferenceMode = 'style' | 'recreate';
export interface ReferenceSet {
  id: string;
  mode: ReferenceMode;
  instructions: string;
  images: { id: string; name: string; file: string }[];
  summary: string;
}

/** User-facing reference constraints; backend also validates signatures and decoded images. */
export function referenceValidation(files: File[], mode: ReferenceMode, instructions = ''): string | null {
  if (mode === 'recreate' && files.length !== 1) return 'Recreate dashboard requires exactly 1 PNG/JPEG image.';
  if (mode === 'style' && (files.length < 1 || files.length > 3)) return 'Use style accepts 1-3 PNG/JPEG images.';
  if (files.reduce((sum, file) => sum + file.size, 0) > 15 * 1024 * 1024) return 'References must total at most 15 MiB; each image must be at most 5 MiB.';
  if (files.some((file) => file.size > 5 * 1024 * 1024)) return 'Each reference image must be at most 5 MiB.';
  if (files.some((file) => !((file.type === 'image/png' && /\.png$/i.test(file.name)) || (file.type === 'image/jpeg' && /\.jpe?g$/i.test(file.name))))) return 'Upload PNG/JPEG reference images only (.png, .jpg or .jpeg).';
  if (instructions.length > 2000) return 'Reference instructions must be at most 2000 characters.';
  return null;
}

export interface Issue {
  id: string;
  requirement: string;
  status: 'unsupported_product' | 'unsupported_app' | 'needs_data' | 'needs_clarification' | 'unknown';
  reason: string;
  evidence: string[];
  alternatives: { id: string; label: string }[];
  resolution: 'unresolved' | 'accepted_alternative' | 'dropped';
}
export interface Assessment {
  id: string | null;
  state: 'unchecked' | 'blocked' | 'ready' | 'stale';
  input_digest: string | null;
  prototype_stale: boolean;
  issues: Issue[];
  pending_comments: { id: string; comments: Comment[] } | null;
}
export interface FeasibilityDecision {
  issue_id: string;
  action: 'accept_alternative' | 'drop';
  alternative_id: string | null;
}

// Synthetic sample data (../contracts/synthetic-data.md 1.1). `Generator` is the contract's name;
// it shadows the built-in generator type inside this module only.
export const SPEC_COLUMN_TYPES = ['integer', 'number', 'string', 'boolean', 'date'] as const;
export const GENERATION_STATES = ['queued', 'generating', 'loading', 'succeeded', 'failed'] as const;
export type Generator =
  | { kind: 'sequence'; start: number; step: number; prefix: string }
  | { kind: 'integer'; min: number; max: number }
  | { kind: 'decimal'; min: number; max: number; decimals: number }
  | { kind: 'choice'; values: (string | number | boolean)[] }
  | { kind: 'boolean'; true_probability: number }
  | { kind: 'date'; start: string; end: string }
  | { kind: 'product'; fields: string[]; decimals: number }
  | { kind: 'lookup'; field: string; mapping: Record<string, string | number | boolean> };
export interface ColumnSpec {
  name: string;
  type: (typeof SPEC_COLUMN_TYPES)[number];
  nullable_fraction: number;
  generator: Generator;
}
export interface GenerationSpec {
  schema_version: 1;
  row_count: number;
  seed: number;
  columns: ColumnSpec[];
}
/** POST /api/builds/{id}/synthetic-data: `generation_key` binds this exact request. */
export interface GenerationRequest {
  generation_key: string;
  proposal_id: string | null;
  spec: GenerationSpec;
}
export interface Proposal {
  id: string;
  reference_set_id: string;
  spec: GenerationSpec;
  assumptions: string[];
}
export interface SyntheticDataset {
  source_id: string;
  generation_key: string;
  synthetic: true;
  spec: GenerationSpec;
  assumptions: string[];
  generator_version: string;
  sha256: string;
  bytes: number;
  created_at: string;
}
export interface GenerationStatus {
  generation_key: string;
  run_id: string;
  state: (typeof GENERATION_STATES)[number];
  source_id: string | null;
  retry_ready: boolean;
  error: { code: string; message: string } | null;
}

export interface DocRef {
  /** Relative to the version's docs/. */
  path: string;
  title: string;
  type: string;
}

export interface Version {
  n: number;
  status: (typeof VERSION_STATUSES)[number];
  report_url: string | null;
  created_at: string;
}

export interface Build {
  id: string;
  title: string;
  archetype: Archetype;
  mode: Mode;
  stage: Stage;
  created_at: string;
  updated_at: string;
  sources: Source[];
  docs: DocRef[];
  spec_version: number | null;
  current_version: number;
  versions: Version[];
  report_url: string | null;
  /** The interview has enough to plan. */
  ready_for_plan: boolean;
}

export type BuildSummary = Pick<Build, 'id' | 'title' | 'archetype' | 'stage' | 'updated_at' | 'report_url'>;

export interface Message {
  id: string;
  role: (typeof MESSAGE_ROLES)[number];
  /** Markdown. */
  text: string;
  node: string | null;
  created_at: string;
}

export interface Comment {
  component_id: string;
  text: string;
}

export interface Trace {
  run_id: string;
  build_id: string | null;
  node: string;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  tool_calls: number;
  status: 'ok' | 'error';
  error: string | null;
  started_at: string;
}

export interface Settings {
  planner_model: string;
  worker_model: string;
  gcp_project_id: string;
  bq_dataset: string;
  bq_location: string;
  gcs_bucket: string;
  google_api_key_set: boolean;
}

// ---------- Request and response bodies ----------

/** PUT /api/settings: partial fields, plus the write-only key. */
export type SettingsUpdate = Partial<Omit<Settings, 'google_api_key_set'>> & { google_api_key?: string };

/** POST /api/builds */
export interface NewBuild {
  title?: string;
  archetype: Archetype;
  mode: Mode;
}

/** POST /api/builds/{id}/sources: `gs://bucket/path.csv` or `project.dataset.table`. */
export interface SourceUri {
  kind: 'gcs' | 'bigquery';
  uri: string;
}

/** 202 body of every long-running action. */
export interface RunAccepted {
  run_id: string;
}

/** 202 body of POST /api/builds/{id}/messages. */
export interface MessageAccepted {
  run_id: string;
  /** The user message's id. */
  message_id: string;
}

/** 201 body of POST /api/builds/{id}/sources/upload. */
export interface SourcesUploaded {
  sources: Source[];
}

export interface RecipeOp {
  op_id: string;
  /** dsengine print line. */
  line: string;
}

/** 200 body of POST /api/builds/{id}/recipe. */
export interface Recipe {
  op_count: number;
  ops: RecipeOp[];
}

export const ENGINE_MODES = ['local', 'agent'] as const;
export type EngineMode = (typeof ENGINE_MODES)[number];

export interface EngineStatus {
  /** `agent`: builds run on a build agent (Cloud Run); chrome_running and signed_in come from its heartbeat. */
  mode: EngineMode;
  chrome_running: boolean;
  signed_in: boolean;
  /** A heartbeat in the last 30 s; false in local mode. */
  agent_connected: boolean;
  agent_last_seen: string | null;
}

/** GET/POST /api/session (contracts/api.md, Access). */
export interface Session {
  /** DSS_ACCESS_CODE is set. */
  required: boolean;
  /** This request carries a valid code. */
  ok: boolean;
}

/** A queued build for the build agent (Agent endpoints; the frontend only checks the fixture). */
export interface Job {
  run_id: string;
  build_id: string;
  version: number;
  dry_run: boolean;
  timeout_s: number;
  /** "recipe.jsonl" first, then every file the recipe's ops name. */
  files: string[];
}

export interface Health {
  status: 'ok';
}

/** Error body (contracts/conventions.md, "Errors"). */
export interface ApiErrorBody {
  error: { code: string; message: string; detail: Record<string, unknown> };
}

/** The engine's `op_finished` event (contracts/recipe.md), forwarded as `build.op`. */
export interface OpFinished {
  event: 'op_finished';
  ts: string;
  op_id: string;
  op: string;
  status: 'ok' | 'failed' | 'skipped';
  /** Empty when ok. */
  message: string;
  /** Relative to the screens dir. */
  screenshot: string | null;
  duration_ms: number;
}

/** Cloud Run refuses request bodies over 32 MB (contracts/api.md): uploads are checked first. */
export const UPLOAD_LIMIT_BYTES = 32 * 1024 * 1024;
export const UPLOAD_TOO_LARGE = "Files over 32 MB can't be uploaded to the hosted app.";

/** A failed API call: the HTTP status plus the contract's error code, message and detail. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: Record<string, unknown>;

  constructor(status: number, code: string, message: string, detail: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

/** The 413 for a batch of files over the upload limit, or null when they fit. */
export function oversizeError(files: File[]): ApiError | null {
  const total = files.reduce((sum, file) => sum + file.size, 0);
  return total > UPLOAD_LIMIT_BYTES ? new ApiError(413, 'payload_too_large', UPLOAD_TOO_LARGE, { bytes: total }) : null;
}

/** The backend refuses a sample-data request body over 64 KiB (contracts/synthetic-data.md). */
export const SYNTHETIC_LIMIT_BYTES = 64 * 1024;
export const SYNTHETIC_TOO_LARGE = 'This sample-data request is over 64 KiB. Use fewer columns or shorter value lists, then generate again.';

/** The 413 for a generation request over 64 KiB as sent (compact JSON), or null when it fits. */
export function syntheticOversizeError(request: GenerationRequest): ApiError | null {
  const bytes = new TextEncoder().encode(JSON.stringify(request)).length;
  return bytes > SYNTHETIC_LIMIT_BYTES ? new ApiError(413, 'payload_too_large', SYNTHETIC_TOO_LARGE, { bytes }) : null;
}

/** One `422 invalid_generation_spec` problem: its path inside the spec (`row_count`, `columns[1].name`) and why. */
export interface SpecFieldError {
  field: string;
  reason: string;
}

/** The field errors of a `422 invalid_generation_spec`: detail `{field, reason}`, or a list of them under `errors`. */
export function specFieldErrors(error: ApiError): SpecFieldError[] {
  const items = Array.isArray(error.detail.errors) ? (error.detail.errors as unknown[]) : [error.detail];
  return items.flatMap((item) => {
    if (!isRecord(item) || typeof item.field !== 'string' || typeof item.reason !== 'string') return [];
    return [{ field: item.field.replace(/^spec\./, ''), reason: item.reason }];
  });
}

// ---------- Guards ----------

export const isStage = oneOf(STAGES);
export const isArchetype = oneOf(ARCHETYPES);
export const isMode = oneOf(MODES);

export const isColumn = shape<Column>({ name: isString, type: oneOf(COLUMN_TYPES), sample: arrayOf(isString) });

export const isSource = shape<Source>({
  id: isString,
  kind: oneOf(SOURCE_KINDS),
  name: isString,
  bq_table: isString,
  row_count: isInt,
  columns: arrayOf(isColumn),
});

export const isReferenceSet = shape<ReferenceSet>({
  id: isString,
  mode: oneOf(['style', 'recreate']),
  instructions: isString,
  images: arrayOf(shape<ReferenceSet['images'][number]>({ id: isString, name: isString, file: isString })),
  summary: isString,
});

export const isDocRef = shape<DocRef>({ path: isString, title: isString, type: isString });

export const isVersion = shape<Version>({
  n: isInt,
  status: oneOf(VERSION_STATUSES),
  report_url: nullable(isString),
  created_at: isString,
});

export const isBuild = shape<Build>({
  id: isString,
  title: isString,
  archetype: isArchetype,
  mode: isMode,
  stage: isStage,
  created_at: isString,
  updated_at: isString,
  sources: arrayOf(isSource),
  docs: arrayOf(isDocRef),
  spec_version: nullable(isInt),
  current_version: isInt,
  versions: arrayOf(isVersion),
  report_url: nullable(isString),
  ready_for_plan: isBoolean,
});

export const isBuildSummary = shape<BuildSummary>({
  id: isString,
  title: isString,
  archetype: isArchetype,
  stage: isStage,
  updated_at: isString,
  report_url: nullable(isString),
});

export const isMessage = shape<Message>({
  id: isString,
  role: oneOf(MESSAGE_ROLES),
  text: isString,
  node: nullable(isString),
  created_at: isString,
});

export const isComment = shape<Comment>({ component_id: isString, text: isString });

export const isIssue = shape<Issue>({
  id: isString, requirement: isString,
  status: oneOf(['unsupported_product', 'unsupported_app', 'needs_data', 'needs_clarification', 'unknown']),
  reason: isString, evidence: arrayOf(isString),
  alternatives: arrayOf(shape<Issue['alternatives'][number]>({ id: isString, label: isString })),
  resolution: oneOf(['unresolved', 'accepted_alternative', 'dropped']),
});
export const isAssessment = shape<Assessment>({
  id: nullable(isString), state: oneOf(['unchecked', 'blocked', 'ready', 'stale']),
  input_digest: nullable(isString), prototype_stale: isBoolean, issues: arrayOf(isIssue),
  pending_comments: nullable(shape<NonNullable<Assessment['pending_comments']>>({ id: isString, comments: arrayOf(isComment) })),
});

const isNumber = primitive<number>((v) => typeof v === 'number' && Number.isFinite(v), 'a finite number');
const isScalar = primitive<string | number | boolean>(
  (v) => typeof v === 'string' || typeof v === 'boolean' || (typeof v === 'number' && Number.isFinite(v)),
  'a string, number or boolean',
);
const literal = <T extends string | number | boolean>(value: T): Guard<T> =>
  primitive<T>((v) => v === value, JSON.stringify(value));

function recordOf<T>(guard: Guard<T>): Guard<Record<string, T>> {
  return (v, path = '$', problems): v is Record<string, T> => {
    if (!isRecord(v)) return fail(path, problems, 'expected an object');
    let ok = true;
    for (const [key, item] of Object.entries(v)) ok = guard(item, `${path}.${key}`, problems) && ok;
    return ok;
  };
}

type Kind = Generator['kind'];
const generatorGuards: { [K in Kind]: Guard<Extract<Generator, { kind: K }>> } = {
  sequence: shape({ kind: literal('sequence'), start: isInt, step: isInt, prefix: isString }),
  integer: shape({ kind: literal('integer'), min: isInt, max: isInt }),
  decimal: shape({ kind: literal('decimal'), min: isNumber, max: isNumber, decimals: isInt }),
  choice: shape({ kind: literal('choice'), values: arrayOf(isScalar) }),
  boolean: shape({ kind: literal('boolean'), true_probability: isNumber }),
  date: shape({ kind: literal('date'), start: isString, end: isString }),
  product: shape({ kind: literal('product'), fields: arrayOf(isString), decimals: isInt }),
  lookup: shape({ kind: literal('lookup'), field: isString, mapping: recordOf(isScalar) }),
};

/** A tagged union: `kind` picks the exact shape. */
export const isGenerator: Guard<Generator> = (v, path = '$', problems): v is Generator => {
  if (!isRecord(v)) return fail(path, problems, 'expected an object');
  const kind = v.kind;
  if (typeof kind !== 'string' || !Object.hasOwn(generatorGuards, kind)) {
    return fail(`${path}.kind`, problems, `expected one of ${Object.keys(generatorGuards).join(' | ')}, got ${JSON.stringify(kind)}`);
  }
  return (generatorGuards[kind as Kind] as Guard<Generator>)(v, path, problems);
};

export const isColumnSpec = shape<ColumnSpec>({
  name: isString,
  type: oneOf(SPEC_COLUMN_TYPES),
  nullable_fraction: isNumber,
  generator: isGenerator,
});
export const isGenerationSpec = shape<GenerationSpec>({
  schema_version: literal(1),
  row_count: isInt,
  seed: isInt,
  columns: arrayOf(isColumnSpec),
});
export const isGenerationRequest = shape<GenerationRequest>({
  generation_key: isString,
  proposal_id: nullable(isString),
  spec: isGenerationSpec,
});
export const isProposal = shape<Proposal>({
  id: isString,
  reference_set_id: isString,
  spec: isGenerationSpec,
  assumptions: arrayOf(isString),
});
export const isSyntheticDataset = shape<SyntheticDataset>({
  source_id: isString,
  generation_key: isString,
  synthetic: literal(true),
  spec: isGenerationSpec,
  assumptions: arrayOf(isString),
  generator_version: isString,
  sha256: isString,
  bytes: isInt,
  created_at: isString,
});
export const isGenerationStatus = shape<GenerationStatus>({
  generation_key: isString,
  run_id: isString,
  state: oneOf(GENERATION_STATES),
  source_id: nullable(isString),
  retry_ready: isBoolean,
  error: nullable(shape<NonNullable<GenerationStatus['error']>>({ code: isString, message: isString })),
});

export const isTrace = shape<Trace>({
  run_id: isString,
  build_id: nullable(isString),
  node: isString,
  model: nullable(isString),
  input_tokens: isInt,
  output_tokens: isInt,
  latency_ms: isInt,
  tool_calls: isInt,
  status: oneOf(['ok', 'error']),
  error: nullable(isString),
  started_at: isString,
});

export const isSettings = shape<Settings>({
  planner_model: isString,
  worker_model: isString,
  gcp_project_id: isString,
  bq_dataset: isString,
  bq_location: isString,
  gcs_bucket: isString,
  google_api_key_set: isBoolean,
});

export const isRunAccepted = shape<RunAccepted>({ run_id: isString });
export const isMessageAccepted = shape<MessageAccepted>({ run_id: isString, message_id: isString });
export const isSourcesUploaded = shape<SourcesUploaded>({ sources: arrayOf(isSource) });
export const isRecipeOp = shape<RecipeOp>({ op_id: isString, line: isString });
export const isRecipe = shape<Recipe>({ op_count: isInt, ops: arrayOf(isRecipeOp) });
export const isEngineStatus = shape<EngineStatus>({
  mode: oneOf(ENGINE_MODES),
  chrome_running: isBoolean,
  signed_in: isBoolean,
  agent_connected: isBoolean,
  agent_last_seen: nullable(isString),
});
export const isSession = shape<Session>({ required: isBoolean, ok: isBoolean });
export const isJob = shape<Job>({
  run_id: isString,
  build_id: isString,
  version: isInt,
  dry_run: isBoolean,
  timeout_s: isInt,
  files: arrayOf(isString),
});

export const isApiErrorBody = shape<ApiErrorBody>({
  error: shape<ApiErrorBody['error']>({ code: isString, message: isString, detail: isObject }),
});

export const isOpFinished = shape<OpFinished>({
  event: oneOf(['op_finished']),
  ts: isString,
  op_id: isString,
  op: isString,
  status: oneOf(['ok', 'failed', 'skipped']),
  message: isString,
  screenshot: nullable(isString),
  duration_ms: isInt,
});

// ---------- Event stream: GET /api/builds/{id}/events ----------

export interface BuildEventMap {
  ready: { build_id: string };
  /** Append `text` to that assistant message. */
  'message.delta': { message_id: string; text: string };
  'message.done': { message: Message };
  'stage.changed': { stage: Stage };
  'build.updated': { build: Build };
  'run.started': { run_id: string; node: string };
  /** The run's token totals so far; they only grow within a run. */
  'run.usage': { run_id: string; node: string; input_tokens: number; output_tokens: number };
  /** Short status line, e.g. "Writing questions.md". */
  'node.progress': { run_id: string; node: string; text: string };
  'run.finished': { run_id: string; node: string; status: 'ok' | 'error'; error: string | null };
  'docs.updated': { docs: DocRef[] };
  'prototype.updated': { spec_version: number };
  'build.op': OpFinished;
  /** Base64 JPEG (stretch, screencast). */
  'build.frame': { data: string };
  'build.finished': { status: 'ok' | 'partial' | 'failed'; report_url: string | null; version: number };
}

export type BuildEventName = keyof BuildEventMap;

/** One event from the stream: `name` is the SSE `event:` field, `data` its parsed JSON. */
export type BuildEvent = { [K in BuildEventName]: { name: K; data: BuildEventMap[K] } }[BuildEventName];

type M = BuildEventMap;

export const buildEventGuards: { [K in BuildEventName]: Guard<M[K]> } = {
  ready: shape<M['ready']>({ build_id: isString }),
  'message.delta': shape<M['message.delta']>({ message_id: isString, text: isString }),
  'message.done': shape<M['message.done']>({ message: isMessage }),
  'stage.changed': shape<M['stage.changed']>({ stage: isStage }),
  'build.updated': shape<M['build.updated']>({ build: isBuild }),
  'run.started': shape<M['run.started']>({ run_id: isString, node: isString }),
  'run.usage': shape<M['run.usage']>({ run_id: isString, node: isString, input_tokens: isInt, output_tokens: isInt }),
  'node.progress': shape<M['node.progress']>({ run_id: isString, node: isString, text: isString }),
  'run.finished': shape<M['run.finished']>({
    run_id: isString,
    node: isString,
    status: oneOf(['ok', 'error']),
    error: nullable(isString),
  }),
  'docs.updated': shape<M['docs.updated']>({ docs: arrayOf(isDocRef) }),
  'prototype.updated': shape<M['prototype.updated']>({ spec_version: isInt }),
  'build.op': isOpFinished,
  'build.frame': shape<M['build.frame']>({ data: isString }),
  'build.finished': shape<M['build.finished']>({
    status: oneOf(['ok', 'partial', 'failed']),
    report_url: nullable(isString),
    version: isInt,
  }),
};

export const BUILD_EVENT_NAMES = Object.keys(buildEventGuards) as BuildEventName[];

export function isBuildEventName(name: string): name is BuildEventName {
  return Object.hasOwn(buildEventGuards, name);
}

/** The typed event, or null when the name is unknown or the data doesn't match the contract. */
export function toBuildEvent(name: string, data: unknown, problems?: string[]): BuildEvent | null {
  if (!isBuildEventName(name)) {
    problems?.push(`${name}: not an event in the contract`);
    return null;
  }
  const guard = buildEventGuards[name] as Guard<unknown>;
  return guard(data, `${name}.data`, problems) ? ({ name, data } as BuildEvent) : null;
}
