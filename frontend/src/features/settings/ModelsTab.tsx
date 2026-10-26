import { ChevronRight, Info, RotateCcw, TriangleAlert } from 'lucide-react';
import { useId, useState, type ReactNode, type SelectHTMLAttributes } from 'react';
import { THINKING_LEVELS, type GenerationProfile, type ModelCapability, type NoReferenceProfile, type SettingsCapabilities, type StageId, type StageProfiles, type ThinkingLevel } from '../../api/types';
import { Button } from '../../components/Button';
import { Input } from '../../components/Input';
import { focusRing } from '../../components/focus';
import {
  STAGE_META,
  STAGE_ORDER,
  boundsOf,
  callCost,
  fieldId,
  formatUsd,
  isGenerationStage,
  pricesCheckedOn,
  rangeText,
  stageDiffers,
  stagePath,
  timeHint,
  type StageField,
} from './stageSettings';

export interface ModelsDraft {
  stages: StageProfiles;
  fallback_model: string;
  review_briefs: boolean;
}

interface ModelsTabProps {
  caps: SettingsCapabilities;
  draft: ModelsDraft;
  onDraft: (update: (draft: ModelsDraft) => ModelsDraft) => void;
  expanded: ReadonlySet<StageId>;
  onToggle: (stage: StageId) => void;
  advanced: ReadonlySet<StageId>;
  onToggleAdvanced: (stage: StageId) => void;
  /** The messages to show on a field (by issue path), if any. */
  issuesAt: (path: string) => string[];
  /** A field holds text that isn't a number (only while it is focused). */
  onInvalidText: (path: string, invalid: boolean) => void;
  onReset: (stage: StageId) => void;
  notices: string[];
  /** Issues the form has no field for. */
  looseIssues: string[];
}

const control = `h-8 w-full rounded-control border border-border-strong bg-surface px-2 text-body text-text enabled:hover:border-text-muted disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted aria-invalid:border-danger ${focusRing}`;

const LEVEL_LABEL: Record<ThinkingLevel, string> = { low: 'Low', medium: 'Medium', high: 'High' };

const errorText = (messages: string[]): ReactNode =>
  messages.length === 0
    ? null
    : messages.map((message, i) => (
        <span key={i} className="block">
          {message}
        </span>
      ));

function Select({ id, label, hint, error, className = '', children, ...rest }: { id: string; label: string; hint?: ReactNode; error: ReactNode; className?: string; children: ReactNode } & SelectHTMLAttributes<HTMLSelectElement>) {
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <label htmlFor={id} className="text-label font-medium text-text">
        {label}
      </label>
      <select id={id} aria-invalid={error ? true : undefined} aria-describedby={describedBy} className={control} {...rest}>
        {children}
      </select>
      {hint && !error && (
        <p id={`${id}-hint`} className="text-caption text-text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-caption text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

/** A whole-number field: text that isn't one stays only while focused, and leaving shows the draft value again. */
function NumberInput({ path, label, hint, value, error, onValue, onInvalidText }: { path: string; label: string; hint: ReactNode; value: number; error: ReactNode; onValue: (n: number) => void; onInvalidText: (path: string, invalid: boolean) => void }) {
  const [text, setText] = useState<string | null>(null);
  const invalid = text !== null && !/^\d+$/.test(text.trim());
  return (
    <Input
      id={fieldId(path)}
      label={label}
      inputMode="numeric"
      autoComplete="off"
      spellCheck={false}
      value={text ?? String(value)}
      hint={hint}
      error={invalid ? 'Enter a whole number.' : error}
      onChange={(e) => {
        const next = e.target.value;
        setText(next);
        const ok = /^\d+$/.test(next.trim());
        onInvalidText(path, !ok);
        if (ok) onValue(Number(next.trim()));
      }}
      onBlur={() => {
        setText(null);
        onInvalidText(path, false);
      }}
    />
  );
}

function modelLabel(model: ModelCapability): string {
  if (model.available === false) return `${model.id} (unavailable)`;
  if (model.available === null) return `${model.id} (availability unknown)`;
  return model.id;
}

function ModelOptions({ caps, current }: { caps: SettingsCapabilities; current: string }) {
  return (
    <>
      {!caps.models.some((m) => m.id === current) && <option value={current}>{`${current} (unknown model)`}</option>}
      {caps.models.map((m) => (
        <option key={m.id} value={m.id}>
          {modelLabel(m)}
        </option>
      ))}
    </>
  );
}

function StageRow({ stage, props }: { stage: StageId; props: ModelsTabProps }) {
  const { caps, draft, onDraft, expanded, onToggle, advanced, onToggleAdvanced, issuesAt, onInvalidText, onReset } = props;
  const meta = STAGE_META[stage];
  const profile = draft.stages[stage];
  const model = caps.models.find((m) => m.id === profile.model);
  const open = expanded.has(stage);
  const edited = stageDiffers(profile, caps.defaults.stages[stage]);
  const generation = isGenerationStage(stage);
  const fields = Object.keys(profile);
  const issueCount = fields.filter((f) => issuesAt(stagePath(stage, f)).length > 0).length;
  const base = useId();
  const nameId = `${base}-name`;
  const summaryId = `${base}-summary`;
  const bodyId = `${base}-body`;

  const set = (field: StageField, value: string | number | boolean) =>
    onDraft((d) => ({ ...d, stages: { ...d.stages, [stage]: { ...d.stages[stage], [field]: value } } }));

  const number = (field: StageField, label: string, hint?: string) => {
    const path = stagePath(stage, field);
    const bounds = boundsOf(stage, field, model, caps);
    const limitsKnown = bounds && bounds[1] !== Number.MAX_SAFE_INTEGER;
    const rangeHint = limitsKnown ? `${rangeText(bounds)}.` : '';
    return (
      <NumberInput
        path={path}
        label={label}
        hint={[hint, rangeHint].filter(Boolean).join(' ')}
        value={(profile as unknown as Record<string, number>)[field] as number}
        error={errorText(issuesAt(path))}
        onValue={(n) => set(field, n)}
        onInvalidText={onInvalidText}
      />
    );
  };

  // An unknown model (a stored issue) can't say which levels it has: offer them all.
  const levels: readonly ThinkingLevel[] = model?.thinking_levels ?? THINKING_LEVELS;
  const thinkingOptions = levels.includes(profile.thinking) ? levels : [...levels, profile.thinking];

  let cost: string | null = null;
  if (generation) {
    const g = profile as GenerationProfile;
    cost = model?.price ? `Up to ${formatUsd(callCost(model.price, g.input_tokens, g.output_tokens))} per call (estimated)` : 'Cost unknown';
  }

  const repairs = generation ? caps.limits.validation_repairs[stage] : null;
  const advancedOpen = advanced.has(stage);

  return (
    <li className="border-b border-border last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        aria-labelledby={`${nameId} ${summaryId}`}
        onClick={() => onToggle(stage)}
        className={`flex w-full items-start gap-2 px-3 py-2 text-left enabled:hover:bg-surface-muted ${focusRing}`}
      >
        <ChevronRight aria-hidden="true" className={`mt-0.5 size-4 shrink-0 text-text-muted transition-transform motion-reduce:transition-none ${open ? 'rotate-90' : ''}`} />
        <span className="min-w-0 flex-1">
          <span id={nameId} className="block text-body font-medium text-text">
            {meta.name}
          </span>
          <span className="block text-caption text-text-muted">{meta.description}</span>
        </span>
        <span id={summaryId} className="flex shrink-0 items-center gap-2 pt-px">
          {issueCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-control bg-danger-soft px-1.5 text-caption font-medium text-text">
              <TriangleAlert aria-hidden="true" className="size-3 text-danger" />
              {issueCount === 1 ? '1 issue' : `${issueCount} issues`}
            </span>
          )}
          {edited && <span className="rounded-control bg-primary-soft px-1.5 text-caption font-medium text-primary">Edited</span>}
          <span className="max-w-48 truncate font-mono text-caption text-text" title={profile.model}>
            {profile.model}
          </span>
          <span className="text-caption text-text-muted">{`${LEVEL_LABEL[profile.thinking]} thinking`}</span>
        </span>
      </button>
      {open && (
        <div id={bodyId} role="region" aria-labelledby={nameId} className="flex flex-col gap-3 px-3 pt-1 pb-3 pl-9">
          <div className="grid grid-cols-3 gap-3">
            <Select
              id={fieldId(stagePath(stage, 'model'))}
              label="Model"
              className="col-span-2"
              value={profile.model}
              error={errorText(issuesAt(stagePath(stage, 'model')))}
              onChange={(e) => set('model', e.target.value)}
            >
              <ModelOptions caps={caps} current={profile.model} />
            </Select>
            <Select
              id={fieldId(stagePath(stage, 'thinking'))}
              label="Thinking"
              value={profile.thinking}
              error={errorText(issuesAt(stagePath(stage, 'thinking')))}
              onChange={(e) => set('thinking', e.target.value)}
            >
              {thinkingOptions.map((level) => (
                <option key={level} value={level}>
                  {levels.includes(level) ? LEVEL_LABEL[level] : `${LEVEL_LABEL[level]} (not supported)`}
                </option>
              ))}
            </Select>
            {generation ? (
              <>
                {number('input_tokens', 'Input tokens')}
                {number('output_tokens', 'Output tokens', 'Thinking counts toward this limit.')}
                {number('timeout_s', 'Total time (s)', timeHint(stage))}
                {number('transport_retries', 'Transport retries')}
                {repairs && repairs[0] === repairs[1] ? (
                  // Bounded to one value: read-only, showing what is stored. Focusable (not in the Tab
                  // order) so a save or stored issue on it can take focus; Reset to defaults fixes it.
                  <div role="group" aria-labelledby={`${base}-repairs`} className="flex flex-col gap-1">
                    <span id={`${base}-repairs`} className="text-label font-medium text-text">
                      Validation repairs
                    </span>
                    <p
                      id={fieldId(stagePath(stage, 'validation_repairs'))}
                      tabIndex={-1}
                      aria-describedby={issuesAt(stagePath(stage, 'validation_repairs')).length > 0 ? `${base}-repairs-error` : undefined}
                      className={`flex h-8 items-center rounded-control text-body text-text-muted ${focusRing}`}
                    >
                      {(profile as GenerationProfile).validation_repairs}
                      {repairs[0] === 0 && repairs[1] === 0 ? ' (this stage has no repair step)' : ''}
                    </p>
                    {issuesAt(stagePath(stage, 'validation_repairs')).length > 0 && (
                      <p id={`${base}-repairs-error`} className="text-caption text-danger">
                        {errorText(issuesAt(stagePath(stage, 'validation_repairs')))}
                      </p>
                    )}
                  </div>
                ) : (
                  number('validation_repairs', 'Validation repairs')
                )}
              </>
            ) : (
              number('timeout_s', 'Request timeout (s)', 'Per model request.')
            )}
          </div>
          {stage === 'html_no_reference' && (
            <label className="flex items-start gap-2 text-body text-text">
              <input
                id={fieldId(stagePath(stage, 'layout_fallback'))}
                type="checkbox"
                className={`mt-0.5 size-4 shrink-0 accent-primary ${focusRing}`}
                checked={(profile as NoReferenceProfile).layout_fallback}
                onChange={(e) => set('layout_fallback', e.target.checked)}
              />
              Use the standard layout when the designed page still fails its checks
            </label>
          )}
          {generation && (
            <div className="flex flex-col gap-2">
              <button
                type="button"
                aria-expanded={advancedOpen}
                onClick={() => onToggleAdvanced(stage)}
                className={`inline-flex w-fit items-center gap-1 rounded-control text-label font-medium text-text-muted hover:text-text ${focusRing}`}
              >
                <ChevronRight aria-hidden="true" className={`size-3.5 transition-transform motion-reduce:transition-none ${advancedOpen ? 'rotate-90' : ''}`} />
                Advanced
              </button>
              {advancedOpen && <div className="grid grid-cols-3 gap-3">{number('input_margin_pct', 'Input count margin (%)', "Added to the provider's token count.")}</div>}
            </div>
          )}
          <div className="flex items-center justify-between gap-3">
            {cost ? <p className="text-label text-text">{cost}</p> : <span />}
            <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden="true" />} onClick={() => onReset(stage)} aria-label={`Reset ${meta.name} to defaults`}>
              Reset to defaults
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

/** The fallback model, the brief review switch and one profile per stage (docs/stage-settings-ui.md, Settings). */
export function ModelsTab(props: ModelsTabProps) {
  const { caps, draft, onDraft, issuesAt, notices, looseIssues } = props;
  const checkedOn = pricesCheckedOn(caps.models);
  const fallbackIssues = issuesAt('/fallback_model');
  return (
    <div className="flex flex-col gap-4">
      {notices.length > 0 && (
        <ul role="status" aria-label="Notices" className="flex flex-col gap-1 rounded-panel border border-border bg-surface-muted px-3 py-2">
          {notices.map((notice, i) => (
            <li key={i} className="flex items-start gap-2 text-label text-text">
              <Info aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-text-muted" />
              {notice}
            </li>
          ))}
        </ul>
      )}
      {looseIssues.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-panel border border-danger bg-danger-soft px-3 py-2" aria-label="Settings that need attention">
          {looseIssues.map((message, i) => (
            <li key={i} className="flex items-start gap-2 text-label text-text">
              <TriangleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-danger" />
              {message}
            </li>
          ))}
        </ul>
      )}
      <div className="grid grid-cols-3 gap-3">
        <Select
          id={fieldId('/fallback_model')}
          label="Fallback model"
          className="col-span-2"
          value={draft.fallback_model}
          hint="Used when a stage's model is unavailable or keeps failing. Not used for limits or invalid output."
          error={errorText(fallbackIssues)}
          onChange={(e) => {
            const value = e.target.value;
            onDraft((d) => ({ ...d, fallback_model: value }));
          }}
        >
          <ModelOptions caps={caps} current={draft.fallback_model} />
        </Select>
      </div>
      <label className="flex items-start gap-2 text-body text-text">
        <input
          id={fieldId('/review_briefs')}
          type="checkbox"
          className={`mt-0.5 size-4 shrink-0 accent-primary ${focusRing}`}
          checked={draft.review_briefs}
          onChange={(e) => {
            const value = e.target.checked;
            onDraft((d) => ({ ...d, review_briefs: value }));
          }}
        />
        Review each page's design brief before its HTML is generated
      </label>
      <div className="flex flex-col gap-2">
        <h3 className="text-label font-semibold text-text">Stages</h3>
        <ul aria-label="Stages" className="rounded-panel border border-border">
          {STAGE_ORDER.map((stage) => (
            <StageRow key={stage} stage={stage} props={props} />
          ))}
        </ul>
        {checkedOn && <p className="text-caption text-text-muted">{`Estimates from Google's list prices checked on ${checkedOn}. Actual billing may differ.`}</p>}
      </div>
    </div>
  );
}
