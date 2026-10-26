import {
  GENERATION_STAGE_IDS,
  STAGE_IDS,
  type GenerationProfile,
  type GenerationStageId,
  type ModelCapability,
  type ModelPrice,
  type SettingsCapabilities,
  type SettingsUpdate,
  type StageId,
  type StageProfiles,
  type ValidationIssue,
} from '../../api/types';

/** The stages in pipeline order, as the Models tab lists them (docs/stage-settings-ui.md, Settings). */
export const STAGE_ORDER: readonly StageId[] = [
  'interview',
  'reference_interpretation',
  'native_planning',
  'html_brief',
  'reference_html',
  'html_no_reference',
  'routine',
];

export const STAGE_META: Record<StageId, { name: string; description: string }> = {
  interview: { name: 'Interview', description: 'Asks about your data and proposes the context and outline.' },
  reference_interpretation: { name: 'Reference interpretation', description: 'Reads your reference dashboards and images into a style and layout.' },
  native_planning: { name: 'Native chart planning', description: 'Plans the Data Studio charts, fields and view SQL of the blueprint.' },
  html_brief: { name: 'HTML brief', description: 'Writes the full design brief the HTML model follows, for pages with and without a reference.' },
  reference_html: { name: 'HTML with a reference', description: 'Writes the HTML of each page that follows a reference.' },
  html_no_reference: { name: 'HTML without a reference', description: 'Writes the HTML of each page that has no reference.' },
  routine: { name: 'Other model work (routine)', description: 'Runs the smaller jobs: checks, revisions, synthetic data, audits and research.' },
};

/** Stages whose total time covers one action; the others (brief and HTML) one page. */
const PER_ACTION: ReadonlySet<StageId> = new Set(['reference_interpretation', 'native_planning']);
/** Stages that read images, so their model needs `images` (api.md 3.0, Validation). */
const NEEDS_IMAGES: ReadonlySet<StageId> = new Set(['reference_interpretation', 'html_brief', 'reference_html']);

export const isGenerationStage = (stage: StageId): stage is GenerationStageId => (GENERATION_STAGE_IDS as readonly string[]).includes(stage);

export const timeHint = (stage: StageId) => (PER_ACTION.has(stage) ? 'Per action, retries and repairs included.' : 'Per page, retries and repairs included.');

export type StageField = keyof GenerationProfile | 'layout_fallback';
/** Fields Settings can be opened at (from a stage-limit error). */
export type StageFocusField = 'model' | 'input_tokens' | 'output_tokens' | 'timeout_s';
export type SettingsTarget = { tab: 'models' | 'google' } | { stage: StageId; field?: StageFocusField };

/** A value that really is a SettingsTarget (an onClick handler passes its event instead). */
export function asSettingsTarget(value: unknown): SettingsTarget | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const target = value as Record<string, unknown>;
  if (target.tab === 'models' || target.tab === 'google') return { tab: target.tab };
  if (typeof target.stage === 'string' && (STAGE_IDS as readonly string[]).includes(target.stage)) {
    const field = target.field;
    const known = field === 'model' || field === 'input_tokens' || field === 'output_tokens' || field === 'timeout_s';
    return { stage: target.stage as StageId, field: known ? field : undefined };
  }
  return undefined;
}

export const stagePath = (stage: StageId, field: string) => `/stages/${stage}/${field}`;

/** The DOM id of a field's control, from its issue path. */
export const fieldId = (path: string) => `settings${path.replace(/\//g, '-')}`;

export const GOOGLE_FIELDS = ['gcp_project_id', 'bq_dataset', 'bq_location', 'gcs_bucket'] as const;
const TOP_PATHS = new Set(['/fallback_model', '/review_briefs', '/google_api_key', ...GOOGLE_FIELDS.map((f) => `/${f}`)]);

/** Where an issue path lands: a stage field, a top-level field, or nowhere the form shows. */
export function placePath(path: string, stages: StageProfiles): { stage: StageId; field: string } | { top: string } | null {
  if (TOP_PATHS.has(path)) return { top: path.slice(1) };
  const match = /^\/stages\/([a-z_]+)\/([a-z_]+)$/.exec(path);
  if (!match) return null;
  const [, stage, field] = match as unknown as [string, string, string];
  if (!(STAGE_IDS as readonly string[]).includes(stage)) return null;
  if (!(field in stages[stage as StageId])) return null;
  return { stage: stage as StageId, field };
}

export const isGooglePath = (path: string) => path === '/google_api_key' || GOOGLE_FIELDS.some((f) => path === `/${f}`);

/** The changed fields of each stage, deep per stage and field; undefined when nothing changed. */
export function stageChanges(saved: StageProfiles, draft: StageProfiles): SettingsUpdate['stages'] {
  const out: Record<string, Record<string, unknown>> = {};
  for (const stage of STAGE_IDS) {
    const before = saved[stage] as unknown as Record<string, unknown>;
    const after = draft[stage] as unknown as Record<string, unknown>;
    for (const key of Object.keys(after)) {
      if (after[key] !== before[key]) (out[stage] ??= {})[key] = after[key];
    }
  }
  return Object.keys(out).length > 0 ? (out as SettingsUpdate['stages']) : undefined;
}

/** True when any field of the stage differs from the other profile (the defaults, for the Edited chip). */
export function stageDiffers(a: StageProfiles[StageId], b: StageProfiles[StageId]): boolean {
  const x = a as unknown as Record<string, unknown>;
  const y = b as unknown as Record<string, unknown>;
  return Object.keys(x).some((key) => x[key] !== y[key]);
}

export const formatInt = (n: number) => n.toLocaleString('en-US');

const range = ([lo, hi]: [number, number]) => `${formatInt(lo)} to ${formatInt(hi)}`;

/** Bounds of a stage's number field: from `limits` and, for token caps, the selected model. */
export function boundsOf(stage: StageId, field: StageField, model: ModelCapability | undefined, caps: SettingsCapabilities): [number, number] | null {
  const { limits } = caps;
  switch (field) {
    case 'timeout_s':
      return isGenerationStage(stage) ? limits.generation_timeout_s : limits.model_timeout_s;
    case 'input_tokens':
      return [limits.min_input_tokens, model?.max_input_tokens ?? Number.MAX_SAFE_INTEGER];
    case 'output_tokens':
      return [limits.min_output_tokens, model?.max_output_tokens ?? Number.MAX_SAFE_INTEGER];
    case 'transport_retries':
      return limits.transport_retries;
    case 'validation_repairs':
      return isGenerationStage(stage) ? limits.validation_repairs[stage] : null;
    case 'input_margin_pct':
      return limits.input_margin_pct;
    default:
      return null;
  }
}

export const rangeText = (bounds: [number, number]) => range(bounds);

/**
 * api.md 3.0 Validation, mirrored so the form can say what is wrong before saving; the backend
 * stays the authority (its `422 invalid_settings` lands on the same paths).
 */
export function validateSettings(stages: StageProfiles, fallbackModel: string, caps: SettingsCapabilities): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const modelOf = (id: string) => caps.models.find((m) => m.id === id);
  const push = (path: string, message: string) => issues.push({ path, message });
  const fallback = modelOf(fallbackModel);
  if (!fallback) push('/fallback_model', `${fallbackModel} is not a known model. Pick another.`);

  for (const stage of STAGE_ORDER) {
    const profile = stages[stage];
    const at = (field: string) => stagePath(stage, field);
    const model = modelOf(profile.model);
    if (!model) {
      push(at('model'), `${profile.model} is not a known model. Pick another.`);
    } else {
      if (!model.thinking_levels.includes(profile.thinking)) {
        push(at('thinking'), `${model.id} doesn't support ${profile.thinking} thinking. Pick ${model.thinking_levels.join(' or ')}.`);
      }
      if (NEEDS_IMAGES.has(stage) && !model.images) push(at('model'), `${model.id} can't read images, which this stage needs.`);
    }
    const numbers: StageField[] = isGenerationStage(stage)
      ? ['input_tokens', 'output_tokens', 'timeout_s', 'transport_retries', 'validation_repairs', 'input_margin_pct']
      : ['timeout_s'];
    for (const field of numbers) {
      const value = (profile as unknown as Record<string, number>)[field] as number;
      if (!Number.isInteger(value)) {
        push(at(field), 'Enter a whole number.');
        continue;
      }
      if ((field === 'input_tokens' || field === 'output_tokens') && !model) continue;
      const bounds = boundsOf(stage, field, model, caps);
      if (!bounds || (value >= bounds[0] && value <= bounds[1])) continue;
      // Plain digits, as the backend writes them (stage-settings/error.invalid_settings.json).
      if (field === 'input_tokens') push(at(field), `${model!.id} allows ${bounds[0]} to ${bounds[1]} input tokens.`);
      else if (field === 'output_tokens') {
        push(at(field), value < bounds[0] ? `Output needs at least ${bounds[0]} tokens.` : `${model!.id} allows at most ${bounds[1]} output tokens.`);
      } else push(at(field), bounds[0] === bounds[1] ? `This stage allows only ${bounds[0]}.` : `Use ${bounds[0]} to ${bounds[1]}.`);
    }

    // The fallback model stands in for every generation stage that uses another model; a value the
    // stage's own model already refuses is flagged on its field, not again here.
    if (fallback && isGenerationStage(stage) && profile.model !== fallback.id) {
      const g = profile as GenerationProfile;
      const flagged = (field: string) => issues.some((i) => i.path === at(field));
      const gaps: string[] = [];
      if (!fallback.thinking_levels.includes(g.thinking) && !flagged('thinking')) gaps.push(`no ${g.thinking} thinking`);
      if (g.input_tokens > fallback.max_input_tokens && !flagged('input_tokens')) gaps.push(`at most ${fallback.max_input_tokens} input tokens`);
      if (g.output_tokens > fallback.max_output_tokens && !flagged('output_tokens')) gaps.push(`at most ${fallback.max_output_tokens} output tokens`);
      if (NEEDS_IMAGES.has(stage) && !fallback.images) gaps.push('no image input');
      if (gaps.length > 0) push('/fallback_model', `${fallback.id} can't stand in for ${STAGE_META[stage].name}: ${gaps.join(', ')}.`);
    }
  }
  return issues;
}

/** Issues of `next` that `before` didn't already have: stored failures never block saving another field. */
export function newIssues(next: ValidationIssue[], before: ValidationIssue[]): ValidationIssue[] {
  const seen = new Set(before.map((i) => `${i.path}\n${i.message}`));
  return next.filter((i) => !seen.has(`${i.path}\n${i.message}`));
}

/** The most one call of a generation stage can cost at its caps, in USD, from the model's price. */
export function callCost(price: ModelPrice, inputTokens: number, outputTokens: number): number {
  const long =
    price.long_context_over !== null && inputTokens > price.long_context_over && price.long_input_usd_per_mtok !== null && price.long_output_usd_per_mtok !== null;
  const inputRate = long ? price.long_input_usd_per_mtok! : price.input_usd_per_mtok;
  const outputRate = long ? price.long_output_usd_per_mtok! : price.output_usd_per_mtok;
  return (inputTokens * inputRate + outputTokens * outputRate) / 1_000_000;
}

/** "$0.26", "$0.0442", "<$0.0001". */
export function formatUsd(usd: number): string {
  if (usd === 0) return '$0.00';
  if (usd < 0.0001) return '<$0.0001';
  return `$${usd < 0.1 ? usd.toFixed(4) : usd.toFixed(2)}`;
}

/** The latest date any model's price was checked on, or null when no model has a price. */
export function pricesCheckedOn(models: ModelCapability[]): string | null {
  const dates = models.flatMap((m) => (m.price ? [m.price.checked_on] : [])).sort();
  return dates[dates.length - 1] ?? null;
}
