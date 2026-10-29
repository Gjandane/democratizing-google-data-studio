// Types and runtime guards for ../contracts/api.md 2.0 (and the dashboard-intent and synthetic-data
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

export function nullable<T>(guard: Guard<T>): Guard<T | null> {
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

/** The order of the workflow (api.md 2.0, Staged workflow endpoints). */
export const STAGES = ['connect', 'context', 'outline', 'design', 'blueprint', 'prototype', 'build', 'done'] as const;
/** The four confirmed artifacts, in workflow order; each is produced in the stage of the same name. */
export const ARTIFACTS = ['context', 'outline', 'design', 'blueprint'] as const;
export const ARTIFACT_STATES = ['missing', 'draft', 'confirmed', 'stale'] as const;
export const AGGS = ['sum', 'avg', 'count', 'count_distinct', 'min', 'max'] as const;
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
export type ArtifactName = (typeof ARTIFACTS)[number];
export type ArtifactState = (typeof ARTIFACT_STATES)[number];
export type Agg = (typeof AGGS)[number];

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
  /** dashboard-intent.md 1.3: recreate only; null in style mode and for a recreate set saved before 1.3. */
  analysis: ReferenceAnalysis | null;
}

export const REFERENCE_ITEM_KINDS = ['chart', 'control', 'kpi', 'text', 'image', 'legend', 'other'] as const;
export type ReferenceItemKind = (typeof REFERENCE_ITEM_KINDS)[number];
export type ReferenceDisposition = 'native' | 'static';

/** One visible item of a recreate screenshot (dashboard-intent.md 1.3). */
export interface ReferenceItem {
  /** r1, r2 ... stable for this analysis. */
  id: string;
  label: string;
  kind: ReferenceItemKind;
  /** 0..1 of the image. */
  box: { x: number; y: number; w: number; h: number };
  disposition: ReferenceDisposition;
  /** An `allowed_types` entry when native, null when static. */
  type: string | null;
  /** Display text read from the image, never a field binding. */
  shows: string;
  reason: string;
  /** The analysis' own choice, read-only. */
  proposed: { disposition: ReferenceDisposition; type: string | null };
}

export interface ReferenceAnalysis {
  /** 1 = as analyzed; +1 on every saved edit. */
  revision: number;
  state: 'pending' | 'approved';
  summary: string;
  /** 1-24, in reading order. */
  items: ReferenceItem[];
  /** The user's note to the planner, 0-1000 chars. */
  note: string;
  allowed_types: string[];
  /** Paths into the analysis (`/items/<i>/type`); approve needs []. */
  issues: ValidationIssue[];
}

/** Body of PUT /api/builds/{id}/reference-images/analysis (api.md 3.2): every item id exactly once. */
export interface ReferenceAnalysisUpdate {
  revision: number;
  items: { id: string; disposition: ReferenceDisposition; type: string | null }[];
  note: string;
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
  /** The user's "about this data" text. */
  notes: string | null;
  artifacts: Record<ArtifactName, ArtifactState>;
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

// Stage settings and design briefs (api.md 3.0, Stage settings and design briefs).

export const STAGE_IDS = ['interview', 'routine', 'reference_interpretation', 'native_planning', 'html_brief', 'reference_html', 'html_no_reference'] as const;
/** The stages with a generation profile (token caps, retries, repairs). */
export const GENERATION_STAGE_IDS = ['reference_interpretation', 'native_planning', 'html_brief', 'reference_html', 'html_no_reference'] as const;
export const THINKING_LEVELS = ['low', 'medium', 'high'] as const;
export type StageId = (typeof STAGE_IDS)[number];
export type GenerationStageId = (typeof GENERATION_STAGE_IDS)[number];
export type ThinkingLevel = (typeof THINKING_LEVELS)[number];

export interface ModelProfile {
  model: string;
  thinking: ThinkingLevel;
  /** Per provider request. */
  timeout_s: number;
}
export interface GenerationProfile extends ModelProfile {
  /** The complete counted request. */
  input_tokens: number;
  /** Thinking included. */
  output_tokens: number;
  /** One total clock: per action (analysis) or per page (brief, HTML). */
  timeout_s: number;
  transport_retries: number;
  validation_repairs: number;
  input_margin_pct: number;
}
export interface NoReferenceProfile extends GenerationProfile {
  layout_fallback: boolean;
}
export interface StageProfiles {
  interview: ModelProfile;
  routine: ModelProfile;
  reference_interpretation: GenerationProfile;
  native_planning: GenerationProfile;
  html_brief: GenerationProfile;
  reference_html: GenerationProfile;
  html_no_reference: NoReferenceProfile;
}

export interface Settings {
  stages: StageProfiles;
  fallback_model: string;
  review_briefs: boolean;
  gcp_project_id: string;
  bq_dataset: string;
  bq_location: string;
  gcs_bucket: string;
  google_api_key_set: boolean;
  /** One line per stage seeded from a legacy model on first read. */
  notices: string[];
  /** Stored values that fail validation now; the UI shows each on its field (paths like `/stages/html_brief/model`). */
  issues: ValidationIssue[];
}

export interface ModelPrice {
  input_usd_per_mtok: number;
  /** Thinking is billed as output. */
  output_usd_per_mtok: number;
  /** Prompt tokens above which the long-context rates apply. */
  long_context_over: number | null;
  long_input_usd_per_mtok: number | null;
  long_output_usd_per_mtok: number | null;
  /** Date the backend's table was checked on Google's pricing page. */
  checked_on: string;
}
export interface ModelCapability {
  id: string;
  thinking_levels: ThinkingLevel[];
  max_input_tokens: number;
  /** Thinking included. */
  max_output_tokens: number;
  images: boolean;
  /** From the last model listing; null = no key or the listing failed. */
  available: boolean | null;
  /** null = no verified price: costs show as unknown. */
  price: ModelPrice | null;
}
export interface SettingsCapabilities {
  models: ModelCapability[];
  defaults: { stages: StageProfiles; fallback_model: string; review_briefs: boolean };
  limits: {
    model_timeout_s: [number, number];
    generation_timeout_s: [number, number];
    transport_retries: [number, number];
    validation_repairs: Record<GenerationStageId, [number, number]>;
    input_margin_pct: [number, number];
    min_input_tokens: number;
    min_output_tokens: number;
  };
}

/** A design page's brief (api.md 3.0): the treatments are the only parts a user edits. */
export interface BriefSlot {
  /** A component id on the page; fixed. */
  id: string;
  /** Non-empty. */
  treatment: string;
}
export interface PageBrief {
  page: number;
  /** Non-empty. */
  overall: string;
  /** Exactly the page's component ids. */
  slots: BriefSlot[];
}
export interface BriefRecord {
  page: number;
  origin: 'generated' | 'edited';
  brief: PageBrief;
  /** The code's readable rendering of `brief`. */
  markdown: string;
  /** Of the canonical JSON. */
  sha256: string;
  /** The actual brief model. */
  model: string;
  created_at: string;
}
export interface DesignPage {
  page: number;
  layout: 'designed' | 'standard';
  /** null when designed; `not_designed` = code layout with no designer attempt. */
  standard_reason: 'layout_fallback' | 'not_designed' | null;
  brief: BriefRecord | null;
  html_model: string | null;
}
export interface BriefReview {
  review_id: string;
  /** 1 = as generated; +1 on every saved edit. */
  revision: number;
  action: 'prototype' | 'revise';
  page: number;
  pages: number;
  /** This page's components, read-only. */
  components: Array<{ id: string; type: string; label: string }>;
  brief: BriefRecord;
  /** Paths into the PageBrief (`/overall`, `/slots/<i>/treatment`); "" for the whole brief. */
  issues: ValidationIssue[];
  stale: boolean;
  created_at: string;
}
export interface DesignPages {
  version: number;
  spec_version: number | null;
  pages: DesignPage[];
  review: BriefReview | null;
}
/** PUT /api/builds/{id}/briefs/review */
export interface BriefReviewSave {
  review_id: string;
  revision: number;
  brief: PageBrief;
}
/** POST /api/builds/{id}/briefs/review/approve: what the user saw. */
export interface BriefReviewApproval {
  review_id: string;
  revision: number;
  sha256: string;
}

export const CALL_OUTCOMES = ['ok', 'invalid', 'output_cutoff', 'input_over_limit', 'timeout', 'provider_error', 'cancelled'] as const;
export type CallOutcome = (typeof CALL_OUTCOMES)[number];
export interface StageCall {
  run_id: string;
  stage: StageId;
  node: string;
  page: number | null;
  /** Content attempt, 1 = first generation. */
  attempt: number;
  transport_attempt: number;
  requested_model: string;
  /** Actual. */
  model: string;
  fallback: boolean;
  thinking: ThinkingLevel;
  /** Provider count. */
  input_measured: number | null;
  /** Provider-reported billed prompt tokens. */
  input_billed: number | null;
  input_enforced: number | null;
  input_limit: number | null;
  output_limit: number | null;
  output_tokens: number | null;
  /** null = unknown, never 0 by default. */
  thinking_tokens: number | null;
  outcome: CallOutcome;
  duration_ms: number;
  started_at: string;
  cost_usd_estimate: number | null;
}
export interface RunCalls {
  run_id: string;
  /** The run's snapshot; null before 3.0. */
  settings: { stages: StageProfiles; fallback_model: string; review_briefs: boolean } | null;
  calls: StageCall[];
  cost_usd_estimate: number | null;
  /** false when any call is unpriced or lacks usage. */
  cost_complete: boolean;
}
export interface RunCost {
  run_id: string;
  node: string;
  started_at: string;
  cost_usd_estimate: number | null;
  complete: boolean;
  /** `trace` = a run before 3.0, priced from its Trace; always incomplete. */
  basis: 'calls' | 'trace';
}
export interface BuildCost {
  build_id: string;
  cost_usd_estimate: number | null;
  complete: boolean;
  /** Newest first. */
  runs: RunCost[];
  prices_checked_on: string | null;
}

// Staged workflow artifacts (api.md 2.0, Staged workflow endpoints). Colors are `#RRGGBB`.

export interface ValidationIssue {
  /** JSON pointer into the artifact. */
  path: string;
  message: string;
}

export interface DerivedField {
  /** snake_case, unique across base and derived fields. */
  name: string;
  /** BigQuery row-level SQL over base columns; no aggregates. */
  expression: string;
  type: ColumnType;
  description: string;
}

export interface Kpi {
  /** snake_case */
  id: string;
  name: string;
  description: string;
  unit: string | null;
  /** Exactly one of `measure` and `ratio` is non-null. */
  measure: { field: string; agg: Agg } | null;
  /** Kpi ids. */
  ratio: { numerator: string; denominator: string } | null;
}

export interface Threshold {
  id: string;
  name: string;
  field: string;
  operator: '>' | '>=' | '<' | '<=' | '=';
  value: number;
  unit: string | null;
  description: string;
}

export interface Term {
  term: string;
  definition: string;
}

export interface Context {
  revision: number;
  title: string;
  goal: string;
  audience: string | null;
  datasets: { source_id: string; summary: string }[];
  derived_fields: DerivedField[];
  kpis: Kpi[];
  thresholds: Threshold[];
  glossary: Term[];
  /** Code checks; confirm needs []. */
  issues: ValidationIssue[];
}

export interface OutlineQuestion {
  /** q1, q2 ... stable */
  id: string;
  text: string;
  rationale: string;
  recommended: boolean;
  selected: boolean;
  kpi_refs: string[];
  origin: 'proposed' | 'suggested' | 'other';
}

export interface OutlineSection {
  /** s1 ... */
  id: string;
  title: string;
  purpose: string;
  questions: OutlineQuestion[];
}

export interface Outline {
  revision: number;
  sections: OutlineSection[];
}

export interface ThemePreset {
  id: string;
  name: string;
  description: string;
  archetypes: Archetype[];
  background: string;
  surface: string;
  text: string;
  muted: string;
  accent: string;
  palette: string[];
  font_family: string;
  radius: number;
  decoration_kit: string;
}

export interface Design {
  revision: number;
  preset_id: string;
  background: string;
  surface: string;
  text: string;
  accent: string;
  /** 3-8 colors. */
  palette: string[];
  /** One of the presets' fonts. */
  font_family: string;
  page_structure: 'single' | 'per_section';
  density: 'comfortable' | 'compact';
  title: string;
  subtitle: string | null;
  source: 'preset' | 'user' | 'reference';
  issues: ValidationIssue[];
}

export interface BlueprintComponent {
  /** A catalog type allowed by DSS_ALLOWED_TYPES. */
  type: string;
  label: string;
  dimensions: string[];
  metrics: { field: string; agg: Agg | 'none' }[];
  date_dimension: string | null;
  breakdown: string | null;
  sort: { field: string; order: 'asc' | 'desc' } | null;
  options: Record<string, unknown>;
}

export interface BlueprintRow {
  /** null for a supporting control. */
  question_id: string | null;
  section_id: string;
  /** 1-based */
  page: number;
  component: BlueprintComponent;
  note: string;
  status: 'ok' | 'blocked';
  issue_ids: string[];
  /** api.md 3.2: the approved native ReferenceItem id this row recreates; null otherwise. */
  reference_item: string | null;
}

export interface ViewSources {
  /** Source id. */
  base: string;
  joins: { source_id: string; on: { left: string; right: string }[] }[];
  /** Source ids stacked under base; joins and union are never both non-empty. */
  union: string[];
}

export interface Blueprint {
  revision: number;
  view_sources: ViewSources;
  derived_fields: DerivedField[];
  rows: BlueprintRow[];
  /** project.dataset.table, after a dry run passes. */
  view_table: string | null;
  assessment_id: string | null;
}

// ---------- Request and response bodies ----------

/** PUT /api/settings (3.0): a partial profile per stage and the other fields, plus the write-only key. */
export interface SettingsUpdate {
  stages?: { [S in StageId]?: Partial<StageProfiles[S]> };
  fallback_model?: string;
  review_briefs?: boolean;
  gcp_project_id?: string;
  bq_dataset?: string;
  bq_location?: string;
  gcs_bucket?: string;
  google_api_key?: string;
}

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

/** PUT /api/builds/{id}/context: code fills `issues` and bumps `revision`. */
export type ContextUpdate = Omit<Context, 'revision' | 'issues'>;
/** PUT /api/builds/{id}/design */
export type DesignUpdate = Omit<Design, 'revision' | 'issues'>;
/** One entry of PUT /api/builds/{id}/outline/selection (1-100 per call). */
export interface QuestionSelection {
  id: string;
  selected: boolean;
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
  /** A heartbeat in the last 30 s; false in local mode, and always false in agent mode since 3.4 (no heartbeat). */
  agent_connected: boolean;
  agent_last_seen: string | null;
}

/** GET/POST /api/session (contracts/api.md, Access). */
export interface Session {
  /** DSS_ACCESS_CODE is set. */
  required: boolean;
  /** This request carries a valid code or session cookie. */
  ok: boolean;
  /** Set when Google sign-in is on: the gate shows the Google button instead of the code form. */
  google_client_id: string | null;
  /** The signed-in Google email, or null (no Google session). */
  user: string | null;
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

export const JOB_TICKET_STATES = ['waiting', 'running', 'finished', 'expired'] as const;
export type JobTicketState = (typeof JOB_TICKET_STATES)[number];

/** GET /api/builds/{id}/job (api.md 3.4, agent mode): the one-shot job of the build's latest run. */
export interface JobTicket {
  run_id: string;
  build_id: string;
  version: number;
  /** One-time job code, "XXXX-XXXX" from A-Z and 2-9 without I, O, 0, 1. */
  code: string;
  state: JobTicketState;
  /** Creation + 30 min; a waiting ticket expires then. */
  expires_at: string;
  claimed_at: string | null;
}

export const AGENT_CHECK_STATES = ['waiting', 'passed', 'failed', 'expired'] as const;
export type AgentCheckState = (typeof AGENT_CHECK_STATES)[number];

/** What the setup check found on the visitor's computer (api.md 3.4 Checks). */
export interface AgentCheckResult {
  agent_version: string;
  api_version_ok: boolean;
  chrome_running: boolean;
  signed_in: boolean;
}

/** POST /api/agent-checks, GET /api/agent-checks/{check_id} (api.md 3.4, agent mode): the setup check. */
export interface AgentCheck {
  /** "c_" + 12 hex. */
  check_id: string;
  /** One-time check code, same alphabet as a job code. */
  code: string;
  state: AgentCheckState;
  /** Creation + 30 min; a waiting check expires then. */
  expires_at: string;
  checked_at: string | null;
  /** Null until the agent reports; `passed` means all three flags are true. */
  result: AgentCheckResult | null;
}

/** 200 body of POST /api/agent/claim (api.md 3.4; the frontend only checks the fixture). */
export interface ClaimedJob {
  job: Job;
  /** Per-job bearer token for that job's routes. */
  job_token: string;
  api_version: string;
}

/** The source kinds an open link locks (api.md 3.4, `403 source_locked`). */
export const LOCKABLE_SOURCE_KINDS = ['gcs', 'bigquery'] as const;
export type LockableSourceKind = (typeof LOCKABLE_SOURCE_KINDS)[number];

/** GET /api/hosting (api.md 3.4). */
export interface Hosting {
  mode: EngineMode;
  /** DSS_PUBLIC=1 on Cloud Run. */
  public: boolean;
  /** Both when public, else []. */
  locked_sources: LockableSourceKind[];
  /** Agent mode with a share bucket: the build's data goes to a public-read CSV the report reads. */
  share_data: boolean;
  api_version: string;
}

/** Error codes added by api.md 3.4 (hosted builds); the 424 for an offline polling agent is retired. */
export const HOSTED_ERROR_CODES = [
  'source_locked',
  'share_too_large',
  'share_export_failed',
  'job_not_found',
  'job_code_invalid',
  'job_expired',
  'agent_timeout',
  'agent_mode_off',
] as const;
export type HostedErrorCode = (typeof HOSTED_ERROR_CODES)[number];

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

/** The open issues of a `409 artifact_invalid` (`detail.issues`); malformed entries are skipped. */
export function artifactIssues(error: ApiError): ValidationIssue[] {
  const items = Array.isArray(error.detail.issues) ? (error.detail.issues as unknown[]) : [];
  return items.flatMap((item) => (isRecord(item) && typeof item.path === 'string' && typeof item.message === 'string' ? [{ path: item.path, message: item.message }] : []));
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
  notes: nullable(isString),
  artifacts: shape<Build['artifacts']>({
    context: oneOf(ARTIFACT_STATES),
    outline: oneOf(ARTIFACT_STATES),
    design: oneOf(ARTIFACT_STATES),
    blueprint: oneOf(ARTIFACT_STATES),
  }),
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

export const isValidationIssue = shape<ValidationIssue>({ path: isString, message: isString });

const isDisposition = oneOf(['native', 'static']);
export const isReferenceItem = shape<ReferenceItem>({
  id: isString,
  label: isString,
  kind: oneOf(REFERENCE_ITEM_KINDS),
  box: shape<ReferenceItem['box']>({ x: isNumber, y: isNumber, w: isNumber, h: isNumber }),
  disposition: isDisposition,
  type: nullable(isString),
  shows: isString,
  reason: isString,
  proposed: shape<ReferenceItem['proposed']>({ disposition: isDisposition, type: nullable(isString) }),
});
export const isReferenceAnalysis = shape<ReferenceAnalysis>({
  revision: isInt,
  state: oneOf(['pending', 'approved']),
  summary: isString,
  items: arrayOf(isReferenceItem),
  note: isString,
  allowed_types: arrayOf(isString),
  issues: arrayOf(isValidationIssue),
});
export const isReferenceSet = shape<ReferenceSet>({
  id: isString,
  mode: oneOf(['style', 'recreate']),
  instructions: isString,
  images: arrayOf(shape<ReferenceSet['images'][number]>({ id: isString, name: isString, file: isString })),
  summary: isString,
  analysis: nullable(isReferenceAnalysis),
});

// ---------- Stage settings and design briefs (api.md 3.0) ----------

export const isStageId = oneOf(STAGE_IDS);
export const isThinkingLevel = oneOf(THINKING_LEVELS);
const modelFields = { model: isString, thinking: isThinkingLevel, timeout_s: isInt };
const generationFields = {
  ...modelFields,
  input_tokens: isInt,
  output_tokens: isInt,
  transport_retries: isInt,
  validation_repairs: isInt,
  input_margin_pct: isInt,
};
export const isModelProfile = shape<ModelProfile>(modelFields);
export const isGenerationProfile = shape<GenerationProfile>(generationFields);
export const isNoReferenceProfile = shape<NoReferenceProfile>({ ...generationFields, layout_fallback: isBoolean });
export const isStageProfiles = shape<StageProfiles>({
  interview: isModelProfile,
  routine: isModelProfile,
  reference_interpretation: isGenerationProfile,
  native_planning: isGenerationProfile,
  html_brief: isGenerationProfile,
  reference_html: isGenerationProfile,
  html_no_reference: isNoReferenceProfile,
});

export const isSettings = shape<Settings>({
  stages: isStageProfiles,
  fallback_model: isString,
  review_briefs: isBoolean,
  gcp_project_id: isString,
  bq_dataset: isString,
  bq_location: isString,
  gcs_bucket: isString,
  google_api_key_set: isBoolean,
  notices: arrayOf(isString),
  issues: arrayOf(isValidationIssue),
});

/** `[min, max]`, both integers. */
const isIntRange: Guard<[number, number]> = (v, path = '$', problems): v is [number, number] => {
  if (!Array.isArray(v) || v.length !== 2) return fail(path, problems, 'expected [min, max]');
  const min = isInt(v[0], `${path}[0]`, problems);
  const max = isInt(v[1], `${path}[1]`, problems);
  return min && max;
};

export const isModelPrice = shape<ModelPrice>({
  input_usd_per_mtok: isNumber,
  output_usd_per_mtok: isNumber,
  long_context_over: nullable(isInt),
  long_input_usd_per_mtok: nullable(isNumber),
  long_output_usd_per_mtok: nullable(isNumber),
  checked_on: isString,
});
export const isModelCapability = shape<ModelCapability>({
  id: isString,
  thinking_levels: arrayOf(isThinkingLevel),
  max_input_tokens: isInt,
  max_output_tokens: isInt,
  images: isBoolean,
  available: nullable(isBoolean),
  price: nullable(isModelPrice),
});
export const isSettingsCapabilities = shape<SettingsCapabilities>({
  models: arrayOf(isModelCapability),
  defaults: shape<SettingsCapabilities['defaults']>({ stages: isStageProfiles, fallback_model: isString, review_briefs: isBoolean }),
  limits: shape<SettingsCapabilities['limits']>({
    model_timeout_s: isIntRange,
    generation_timeout_s: isIntRange,
    transport_retries: isIntRange,
    validation_repairs: shape<SettingsCapabilities['limits']['validation_repairs']>({
      reference_interpretation: isIntRange,
      native_planning: isIntRange,
      html_brief: isIntRange,
      reference_html: isIntRange,
      html_no_reference: isIntRange,
    }),
    input_margin_pct: isIntRange,
    min_input_tokens: isInt,
    min_output_tokens: isInt,
  }),
});

export const isBriefSlot = shape<BriefSlot>({ id: isString, treatment: isString });
export const isPageBrief = shape<PageBrief>({ page: isInt, overall: isString, slots: arrayOf(isBriefSlot) });
export const isBriefRecord = shape<BriefRecord>({
  page: isInt,
  origin: oneOf(['generated', 'edited']),
  brief: isPageBrief,
  markdown: isString,
  sha256: isString,
  model: isString,
  created_at: isString,
});
export const isDesignPage = shape<DesignPage>({
  page: isInt,
  layout: oneOf(['designed', 'standard']),
  standard_reason: nullable(oneOf(['layout_fallback', 'not_designed'])),
  brief: nullable(isBriefRecord),
  html_model: nullable(isString),
});
export const isBriefReview = shape<BriefReview>({
  review_id: isString,
  revision: isInt,
  action: oneOf(['prototype', 'revise']),
  page: isInt,
  pages: isInt,
  components: arrayOf(shape<BriefReview['components'][number]>({ id: isString, type: isString, label: isString })),
  brief: isBriefRecord,
  issues: arrayOf(isValidationIssue),
  stale: isBoolean,
  created_at: isString,
});
export const isDesignPages = shape<DesignPages>({
  version: isInt,
  spec_version: nullable(isInt),
  pages: arrayOf(isDesignPage),
  review: nullable(isBriefReview),
});

export const isStageCall = shape<StageCall>({
  run_id: isString,
  stage: isStageId,
  node: isString,
  page: nullable(isInt),
  attempt: isInt,
  transport_attempt: isInt,
  requested_model: isString,
  model: isString,
  fallback: isBoolean,
  thinking: isThinkingLevel,
  input_measured: nullable(isInt),
  input_billed: nullable(isInt),
  input_enforced: nullable(isInt),
  input_limit: nullable(isInt),
  output_limit: nullable(isInt),
  output_tokens: nullable(isInt),
  thinking_tokens: nullable(isInt),
  outcome: oneOf(CALL_OUTCOMES),
  duration_ms: isInt,
  started_at: isString,
  cost_usd_estimate: nullable(isNumber),
});
export const isRunCalls = shape<RunCalls>({
  run_id: isString,
  settings: nullable(shape<NonNullable<RunCalls['settings']>>({ stages: isStageProfiles, fallback_model: isString, review_briefs: isBoolean })),
  calls: arrayOf(isStageCall),
  cost_usd_estimate: nullable(isNumber),
  cost_complete: isBoolean,
});
export const isRunCost = shape<RunCost>({
  run_id: isString,
  node: isString,
  started_at: isString,
  cost_usd_estimate: nullable(isNumber),
  complete: isBoolean,
  basis: oneOf(['calls', 'trace']),
});
export const isBuildCost = shape<BuildCost>({
  build_id: isString,
  cost_usd_estimate: nullable(isNumber),
  complete: isBoolean,
  runs: arrayOf(isRunCost),
  prices_checked_on: nullable(isString),
});
export const isDerivedField = shape<DerivedField>({ name: isString, expression: isString, type: oneOf(COLUMN_TYPES), description: isString });
export const isKpi = shape<Kpi>({
  id: isString,
  name: isString,
  description: isString,
  unit: nullable(isString),
  measure: nullable(shape<NonNullable<Kpi['measure']>>({ field: isString, agg: oneOf(AGGS) })),
  ratio: nullable(shape<NonNullable<Kpi['ratio']>>({ numerator: isString, denominator: isString })),
});
export const isThreshold = shape<Threshold>({
  id: isString,
  name: isString,
  field: isString,
  operator: oneOf(['>', '>=', '<', '<=', '=']),
  value: isNumber,
  unit: nullable(isString),
  description: isString,
});
export const isContext = shape<Context>({
  revision: isInt,
  title: isString,
  goal: isString,
  audience: nullable(isString),
  datasets: arrayOf(shape<Context['datasets'][number]>({ source_id: isString, summary: isString })),
  derived_fields: arrayOf(isDerivedField),
  kpis: arrayOf(isKpi),
  thresholds: arrayOf(isThreshold),
  glossary: arrayOf(shape<Term>({ term: isString, definition: isString })),
  issues: arrayOf(isValidationIssue),
});
export const isOutlineQuestion = shape<OutlineQuestion>({
  id: isString,
  text: isString,
  rationale: isString,
  recommended: isBoolean,
  selected: isBoolean,
  kpi_refs: arrayOf(isString),
  origin: oneOf(['proposed', 'suggested', 'other']),
});
export const isOutline = shape<Outline>({
  revision: isInt,
  sections: arrayOf(shape<OutlineSection>({ id: isString, title: isString, purpose: isString, questions: arrayOf(isOutlineQuestion) })),
});
export const isThemePreset = shape<ThemePreset>({
  id: isString,
  name: isString,
  description: isString,
  archetypes: arrayOf(isArchetype),
  background: isString,
  surface: isString,
  text: isString,
  muted: isString,
  accent: isString,
  palette: arrayOf(isString),
  font_family: isString,
  radius: isInt,
  decoration_kit: isString,
});
export const isDesign = shape<Design>({
  revision: isInt,
  preset_id: isString,
  background: isString,
  surface: isString,
  text: isString,
  accent: isString,
  palette: arrayOf(isString),
  font_family: isString,
  page_structure: oneOf(['single', 'per_section']),
  density: oneOf(['comfortable', 'compact']),
  title: isString,
  subtitle: nullable(isString),
  source: oneOf(['preset', 'user', 'reference']),
  issues: arrayOf(isValidationIssue),
});
export const isBlueprintComponent = shape<BlueprintComponent>({
  type: isString,
  label: isString,
  dimensions: arrayOf(isString),
  metrics: arrayOf(shape<BlueprintComponent['metrics'][number]>({ field: isString, agg: oneOf([...AGGS, 'none']) })),
  date_dimension: nullable(isString),
  breakdown: nullable(isString),
  sort: nullable(shape<NonNullable<BlueprintComponent['sort']>>({ field: isString, order: oneOf(['asc', 'desc']) })),
  options: isObject,
});
export const isBlueprintRow = shape<BlueprintRow>({
  question_id: nullable(isString),
  section_id: isString,
  page: isInt,
  component: isBlueprintComponent,
  note: isString,
  status: oneOf(['ok', 'blocked']),
  issue_ids: arrayOf(isString),
  reference_item: nullable(isString),
});
export const isBlueprint = shape<Blueprint>({
  revision: isInt,
  view_sources: shape<ViewSources>({
    base: isString,
    joins: arrayOf(shape<ViewSources['joins'][number]>({
      source_id: isString,
      on: arrayOf(shape<ViewSources['joins'][number]['on'][number]>({ left: isString, right: isString })),
    })),
    union: arrayOf(isString),
  }),
  derived_fields: arrayOf(isDerivedField),
  rows: arrayOf(isBlueprintRow),
  view_table: nullable(isString),
  assessment_id: nullable(isString),
});

export const isRunAccepted = shape<RunAccepted>({ run_id: isString });
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
export const isSession = shape<Session>({ required: isBoolean, ok: isBoolean, google_client_id: nullable(isString), user: nullable(isString) });
export const isJob = shape<Job>({
  run_id: isString,
  build_id: isString,
  version: isInt,
  dry_run: isBoolean,
  timeout_s: isInt,
  files: arrayOf(isString),
});
export const isJobTicket = shape<JobTicket>({
  run_id: isString,
  build_id: isString,
  version: isInt,
  code: isString,
  state: oneOf(JOB_TICKET_STATES),
  expires_at: isString,
  claimed_at: nullable(isString),
});
export const isAgentCheckResult = shape<AgentCheckResult>({
  agent_version: isString,
  api_version_ok: isBoolean,
  chrome_running: isBoolean,
  signed_in: isBoolean,
});
export const isAgentCheck = shape<AgentCheck>({
  check_id: isString,
  code: isString,
  state: oneOf(AGENT_CHECK_STATES),
  expires_at: isString,
  checked_at: nullable(isString),
  result: nullable(isAgentCheckResult),
});
export const isClaimedJob = shape<ClaimedJob>({ job: isJob, job_token: isString, api_version: isString });
export const isHosting = shape<Hosting>({
  mode: oneOf(ENGINE_MODES),
  public: isBoolean,
  locked_sources: arrayOf(oneOf(LOCKABLE_SOURCE_KINDS)),
  share_data: isBoolean,
  api_version: isString,
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
  /** Follows every artifact write: the client refetches that artifact. */
  'artifact.updated': { artifact: ArtifactName; revision: number };
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
  /** 3.0: the run paused before this page's HTML for the user's brief review; `run.finished` (ok) follows. */
  'brief.review': { review_id: string; page: number; pages: number };
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
  'artifact.updated': shape<M['artifact.updated']>({ artifact: oneOf(ARTIFACTS), revision: isInt }),
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
  'brief.review': shape<M['brief.review']>({ review_id: isString, page: isInt, pages: isInt }),
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
