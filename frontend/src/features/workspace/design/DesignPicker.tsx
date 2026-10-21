// The Design stage's picker (docs/staged-ui.md): preset cards, then the editable fields beside a
// mini preview that redraws on every change. Picking a preset, palette add/remove, selects and
// radios save at once with PUT design; text and hex fields save when they lose focus. Saving never
// disables a control, so focus stays where the user is.
import { Plus, X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { api } from '../../../api/client';
import { ApiError, type Build, type Design, type DesignUpdate, type ThemePreset } from '../../../api/types';
import { Button } from '../../../components/Button';
import { ErrorState } from '../../../components/ErrorState';
import { Input } from '../../../components/Input';
import { focusRing } from '../../../components/focus';
import { LoadingState } from '../../../components/Spinner';
import { IssueList, issueText, SelectField } from '../context/fields';
import { placeIssues } from '../context/model';
import { DesignPreview, Swatch } from './DesignPreview';

/** Colors are `#RRGGBB` (api.md 2.0). */
export const HEX = /^#[0-9A-Fa-f]{6}$/;
/** The palette's size limits (api.md 2.0, Design). */
export const PALETTE_MIN = 3;
export const PALETTE_MAX = 8;
/** Most pages a per-section Design lays out (api.md 2.0, Prototype HTML). */
export const MAX_PAGES = 5;

const COLOR_HINT = 'Use a color like #1E40AF.';
const BASE_COLORS = [
  { key: 'background', label: 'Background' },
  { key: 'surface', label: 'Surface' },
  { key: 'text', label: 'Text' },
  { key: 'accent', label: 'Accent' },
] as const;
type StyleKey = 'background' | 'surface' | 'text' | 'accent' | 'palette' | 'font_family';

const groupTitle = 'text-title font-semibold text-text';
const radio = `size-4 shrink-0 cursor-pointer accent-primary disabled:cursor-not-allowed ${focusRing}`;
const chip = 'inline-flex h-5 items-center rounded-full px-2 text-caption';

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Couldn't save your change. Try again.");
const toUpdate = ({ revision: _r, issues: _i, ...rest }: Design): DesignUpdate => structuredClone(rest);
const normal = (color: string) => color.toUpperCase();

/** Every path the picker shows: issues land on the deepest one that contains them. */
function renderedPaths(draft: DesignUpdate): Set<string> {
  const paths = new Set(['/preset_id', '/background', '/surface', '/text', '/accent', '/palette', '/font_family', '/page_structure', '/density', '/title', '/subtitle', '/source']);
  draft.palette.forEach((_, i) => paths.add(`/palette/${i}`));
  return paths;
}

export function DesignPicker({
  build,
  design,
  disabled,
  onSaved,
  onSavingChange,
}: {
  build: Build;
  /** The latest Design from the server: its issues show on their fields. */
  design: Design;
  /** A run holds the build's lock, or the build is past editing. */
  disabled: boolean;
  onSaved: (design: Design) => void;
  /** True while a save runs or after one failed: the server's copy isn't what the user sees. */
  onSavingChange: (saving: boolean) => void;
}) {
  const uid = useId();
  const [draft, setDraft] = useState<DesignUpdate>(() => toUpdate(design));
  const [saveError, setSaveError] = useState<string | null>(null);
  const [presets, setPresets] = useState<{ status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; value: ThemePreset[] }>({ status: 'loading' });
  const [presetAttempt, setPresetAttempt] = useState(0);
  // Sections with a selected question in the outline: the pages of a per-section Design.
  const [sections, setSections] = useState<number | null>(null);
  const [adding, setAdding] = useState('');
  const latest = useRef(draft);
  latest.current = draft;
  // Edit counters as in the context editor: the server's value replaces the draft only when
  // nothing newer is waiting.
  const edited = useRef(0);
  const sent = useRef(0);
  const acked = useRef(0);
  const inFlight = useRef(false);
  const queued = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // A reset or another tab's save arrives through artifact.updated: adopt it unless edits wait.
  useEffect(() => {
    if (!inFlight.current && edited.current === acked.current) setDraft(toUpdate(design));
  }, [design]);

  useEffect(() => {
    let active = true;
    api.listDesignPresets(build.id).then(
      (value) => {
        if (active) setPresets({ status: 'ready', value });
      },
      (error: unknown) => {
        if (active) setPresets({ status: 'error', message: error instanceof ApiError ? error.message : "Couldn't load the presets. Try again." });
      },
    );
    return () => {
      active = false;
    };
  }, [build.id, presetAttempt]);

  useEffect(() => {
    let active = true;
    api.getOutline(build.id).then(
      (outline) => {
        if (active && outline) setSections(outline.sections.filter((s) => s.questions.some((q) => q.selected)).length);
      },
      () => {},
    );
    return () => {
      active = false;
    };
  }, [build.id]);

  const save = async (): Promise<void> => {
    if (inFlight.current) {
      if (edited.current !== sent.current) queued.current = true;
      return;
    }
    inFlight.current = true;
    onSavingChange(true);
    const seq = edited.current;
    sent.current = seq;
    let failed = false;
    try {
      const saved = await api.updateDesign(build.id, latest.current);
      if (!mounted.current) return;
      acked.current = seq;
      setSaveError(null);
      if (edited.current === seq) setDraft(toUpdate(saved));
      onSaved(saved);
    } catch (error) {
      failed = true;
      if (mounted.current) setSaveError(errorText(error));
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        if (queued.current) {
          queued.current = false;
          void save();
        } else onSavingChange(failed);
      }
    }
  };

  /** Applies a change; `commit` saves it now, else on blur. */
  const change = (update: (d: DesignUpdate) => DesignUpdate, commit = false) => {
    const next = update(latest.current);
    latest.current = next;
    edited.current += 1;
    setDraft(next);
    if (commit) void save();
  };
  const commitText = () => {
    if (edited.current !== acked.current) void save();
  };
  /** A color, palette or font edit: the values are the user's own from now on. */
  const setStyle = (patch: Partial<Pick<DesignUpdate, StyleKey>>, commit = false) => change((d) => ({ ...d, ...patch, source: 'user' }), commit);

  const pick = (preset: ThemePreset) =>
    change(
      (d) => ({
        ...d,
        preset_id: preset.id,
        background: preset.background,
        surface: preset.surface,
        text: preset.text,
        accent: preset.accent,
        palette: [...preset.palette],
        font_family: preset.font_family,
        source: 'preset',
      }),
      true,
    );

  const addColor = () => {
    if (!HEX.test(adding) || latest.current.palette.length >= PALETTE_MAX) return;
    setStyle({ palette: [...latest.current.palette, normal(adding)] }, true);
    setAdding('');
  };

  const placed = placeIssues(design.issues, renderedPaths(draft));
  const err = (path: string) => issueText(placed.get(path));
  const presetList = presets.status === 'ready' ? presets.value : [];
  const basedOn = presetList.find((p) => p.id === draft.preset_id);
  const fonts = [...new Set([...presetList.map((p) => p.font_family), draft.font_family])];
  const full = draft.palette.length >= PALETTE_MAX;
  const addProblem = adding !== '' && !HEX.test(adding) ? COLOR_HINT : null;

  let origin: ReactNode;
  if (draft.source === 'reference') origin = <span className={`${chip} bg-primary-soft font-medium text-primary`}>From your reference</span>;
  else if (draft.source === 'user') origin = <span className={`${chip} bg-surface-muted text-text`}>Edited{basedOn ? ` from ${basedOn.name}` : ''}</span>;
  else origin = <span className={`${chip} bg-surface-muted text-text`}>{basedOn ? `${basedOn.name} preset` : 'Preset'}</span>;

  let pagesHint: string | null = null;
  if (sections !== null) {
    if (sections > MAX_PAGES) pagesHint = `${sections} sections have questions: one page per section allows ${MAX_PAGES} at most.`;
    else pagesHint = sections === 1 ? '1 page from your confirmed outline' : `${sections} pages from your confirmed outline`;
  }

  return (
    <div className="mt-4">
      {saveError && (
        <ErrorState className="mb-4" title="Couldn't save your change" message={`${saveError} Your edits are kept here.`} onRetry={disabled ? undefined : () => void save()} retryLabel="Save again" />
      )}
      <IssueList issues={placed.get('')} className="mb-3" />
      <fieldset disabled={disabled} className="min-w-0">
        <legend className="sr-only">Design</legend>

        <section aria-labelledby={`${uid}-presets`}>
          <h3 id={`${uid}-presets`} className={`mb-2 ${groupTitle}`}>
            Presets
          </h3>
          {presets.status === 'loading' && <LoadingState>Loading the presets…</LoadingState>}
          {presets.status === 'error' && (
            <ErrorState title="Couldn't load the presets" message={`${presets.message} You can still edit the fields below.`} onRetry={() => { setPresets({ status: 'loading' }); setPresetAttempt((n) => n + 1); }} />
          )}
          {presets.status === 'ready' && presets.value.length === 0 && <p className="text-body text-text-muted">No presets to pick from. Edit the fields below.</p>}
          {presetList.length > 0 && (
            <ul className="grid grid-cols-3 gap-3">
              {presetList.map((preset) => (
                <li key={preset.id} className="min-w-0">
                  <PresetCard id={`${uid}-${preset.id}`} preset={preset} selected={preset.id === draft.preset_id} onPick={() => pick(preset)} />
                </li>
              ))}
            </ul>
          )}
          <IssueList issues={placed.get('/preset_id')} className="mt-2" />
        </section>

        <div className="mt-6 grid grid-cols-[minmax(0,1fr)_17rem] items-start gap-6">
          <div className="min-w-0 space-y-5">
            <fieldset className="min-w-0">
              <legend className="mb-2 flex flex-wrap items-center gap-2">
                <span className={groupTitle}>Colors and font</span>
                {origin}
              </legend>
              <div className="grid grid-cols-2 gap-3">
                {BASE_COLORS.map(({ key, label }) => (
                  <HexField key={key} label={label} value={draft[key]} error={err(`/${key}`)} onValue={(value) => setStyle({ [key]: value } as Partial<Pick<DesignUpdate, StyleKey>>)} onBlur={commitText} />
                ))}
              </div>

              <div className="mt-4">
                <p id={`${uid}-palette`} className="text-label font-medium text-text">
                  Palette <span className="font-normal text-text-muted tabular-nums">{draft.palette.length} of {PALETTE_MAX}</span>
                </p>
                <p className="text-caption text-text-muted">Charts use these colors in order. Keep {PALETTE_MIN} to {PALETTE_MAX}.</p>
                <ul aria-labelledby={`${uid}-palette`} className="mt-2 flex flex-wrap gap-2">
                  {draft.palette.map((color, i) => (
                    <li key={i} className="flex items-start gap-1 rounded-control border border-border bg-surface py-1 pr-1 pl-2">
                      <span aria-hidden="true" className="mt-2 size-4 shrink-0 rounded-control border border-border" style={{ backgroundColor: color }} />
                      <HexInput
                        label={`Palette color ${i + 1}`}
                        hideLabel
                        className="w-24"
                        value={color}
                        error={err(`/palette/${i}`)}
                        onValue={(value) => setStyle({ palette: latest.current.palette.map((c, j) => (j === i ? value : c)) })}
                        onBlur={commitText}
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<X aria-hidden="true" />}
                        aria-label={`Remove palette color ${i + 1} ${color}`}
                        disabled={draft.palette.length <= PALETTE_MIN}
                        title={draft.palette.length <= PALETTE_MIN ? `Keep at least ${PALETTE_MIN} colors.` : undefined}
                        onClick={() => setStyle({ palette: latest.current.palette.filter((_, j) => j !== i) }, true)}
                      />
                    </li>
                  ))}
                </ul>
                <IssueList issues={placed.get('/palette')} className="mt-1.5" />
                <div className="mt-2 flex items-start gap-2">
                  <Input
                    label="Add a palette color"
                    hideLabel
                    className="w-32 [&_input]:font-mono"
                    placeholder="#RRGGBB"
                    spellCheck={false}
                    autoComplete="off"
                    maxLength={16}
                    value={adding}
                    disabled={full}
                    error={addProblem}
                    hint={full ? `${PALETTE_MAX} colors at most. Remove one to add another.` : undefined}
                    onChange={(e) => setAdding(e.target.value.trim())}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        addColor();
                      }
                    }}
                  />
                  <Button size="md" icon={<Plus aria-hidden="true" />} disabled={full || !HEX.test(adding)} onClick={addColor}>
                    Add color
                  </Button>
                </div>
              </div>

              <SelectField label="Font" className="mt-4 max-w-64" value={draft.font_family} error={err('/font_family')} onChange={(e) => setStyle({ font_family: e.target.value }, true)}>
                {fonts.map((font) => (
                  <option key={font} value={font}>
                    {font}
                  </option>
                ))}
              </SelectField>
            </fieldset>

            <RadioGroup
              legend="Pages"
              name={`${uid}-pages`}
              value={draft.page_structure}
              error={err('/page_structure')}
              options={[
                { value: 'single', label: 'A single page' },
                { value: 'per_section', label: 'One page per section', hint: pagesHint },
              ]}
              onChange={(value) => change((d) => ({ ...d, page_structure: value as DesignUpdate['page_structure'] }), true)}
            />
            <RadioGroup
              legend="Density"
              name={`${uid}-density`}
              value={draft.density}
              error={err('/density')}
              options={[
                { value: 'comfortable', label: 'Comfortable', hint: 'More room around each chart' },
                { value: 'compact', label: 'Compact', hint: 'More charts above the fold' },
              ]}
              onChange={(value) => change((d) => ({ ...d, density: value as DesignUpdate['density'] }), true)}
            />

            <div className="grid grid-cols-2 gap-3">
              <Input label="Title" value={draft.title} error={err('/title')} onChange={(e) => change((d) => ({ ...d, title: e.target.value }))} onBlur={commitText} />
              <Input label="Subtitle" placeholder="None" value={draft.subtitle ?? ''} error={err('/subtitle')} onChange={(e) => change((d) => ({ ...d, subtitle: e.target.value === '' ? null : e.target.value }))} onBlur={commitText} />
            </div>
            <IssueList issues={placed.get('/source')} />
          </div>
          <div className="sticky top-0">
            <DesignPreview design={draft} />
          </div>
        </div>
      </fieldset>
    </div>
  );
}

/** A preset as a card: pressing it applies its colors, palette and font. */
function PresetCard({ id, preset, selected, onPick }: { id: string; preset: ThemePreset; selected: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-labelledby={`${id}-name`}
      aria-describedby={`${id}-desc`}
      onClick={onPick}
      className={`flex h-full w-full flex-col items-start gap-2 rounded-panel border p-3 text-left disabled:cursor-not-allowed disabled:opacity-60 ${selected ? 'border-primary bg-primary-soft' : 'border-border bg-surface enabled:hover:border-border-strong'} ${focusRing}`}
    >
      <span className="flex w-full items-baseline justify-between gap-2">
        <span id={`${id}-name`} className="min-w-0 truncate text-body font-semibold text-text">
          {preset.name}
        </span>
        {selected && <span className="shrink-0 text-caption font-medium text-primary">Selected</span>}
      </span>
      <span id={`${id}-desc`} className="block text-caption text-text-muted">
        {preset.description} {preset.font_family}.
      </span>
      <span className="flex flex-wrap gap-x-2.5 gap-y-1">
        <Swatch small name="bg" color={preset.background} />
        {preset.palette.map((color, i) => (
          <Swatch key={i} small color={color} />
        ))}
      </span>
    </button>
  );
}

/**
 * A hex input that keeps what the user types while focused and reports only `#RRGGBB` values;
 * leaving it shows the stored color again.
 */
function HexInput({
  label,
  hideLabel,
  value,
  error,
  onValue,
  onBlur,
  className = '',
}: {
  label: string;
  hideLabel?: boolean;
  value: string;
  error?: ReactNode;
  onValue: (value: string) => void;
  onBlur: () => void;
  className?: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const invalid = text !== null && !HEX.test(text);
  return (
    <Input
      label={label}
      hideLabel={hideLabel}
      className={`${className} [&_input]:font-mono`}
      spellCheck={false}
      autoComplete="off"
      maxLength={16}
      value={text ?? value}
      error={invalid ? COLOR_HINT : error}
      onChange={(e) => {
        const next = e.target.value.trim();
        setText(next);
        if (HEX.test(next)) onValue(normal(next));
      }}
      onBlur={() => {
        setText(null);
        onBlur();
      }}
    />
  );
}

/** A base color: its swatch beside the hex input. */
function HexField({ label, value, error, onValue, onBlur }: { label: string; value: string; error?: ReactNode; onValue: (value: string) => void; onBlur: () => void }) {
  return (
    <div className="flex min-w-0 items-start gap-2">
      <span aria-hidden="true" className="mt-6.5 size-6 shrink-0 rounded-control border border-border" style={{ backgroundColor: HEX.test(value) ? value : undefined }} />
      <HexInput label={label} className="min-w-0 flex-1" value={value} error={error} onValue={onValue} onBlur={onBlur} />
    </div>
  );
}

function RadioGroup({
  legend,
  name,
  value,
  options,
  error,
  onChange,
}: {
  legend: string;
  name: string;
  value: string;
  options: { value: string; label: string; hint?: string | null }[];
  error?: ReactNode;
  onChange: (value: string) => void;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1.5 text-label font-medium text-text">{legend}</legend>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        {options.map((option) => {
          const id = `${name}-${option.value}`;
          return (
            <div key={option.value} className="flex items-start gap-2">
              <input id={id} type="radio" name={name} value={option.value} checked={value === option.value} aria-describedby={option.hint ? `${id}-hint` : undefined} onChange={() => onChange(option.value)} className={`mt-0.5 ${radio}`} />
              <div>
                <label htmlFor={id} className="block cursor-pointer text-body text-text">
                  {option.label}
                </label>
                {option.hint && (
                  <p id={`${id}-hint`} className="text-caption text-text-muted">
                    {option.hint}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {error && <p className="mt-1 text-caption text-danger">{error}</p>}
    </fieldset>
  );
}
