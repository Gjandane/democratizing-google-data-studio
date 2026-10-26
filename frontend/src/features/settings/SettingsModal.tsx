import { CircleCheck, Lock } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { api } from '../../api/client';
import {
  ApiError,
  artifactIssues,
  type Settings,
  type SettingsCapabilities,
  type SettingsUpdate,
  type StageId,
  type ValidationIssue,
} from '../../api/types';
import { Button } from '../../components/Button';
import { ErrorState } from '../../components/ErrorState';
import { Input } from '../../components/Input';
import { Modal } from '../../components/Modal';
import { LoadingState } from '../../components/Spinner';
import { focusRing } from '../../components/focus';
import { ModelsTab, type ModelsDraft } from './ModelsTab';
import {
  GOOGLE_FIELDS,
  fieldId,
  isGenerationStage,
  isGooglePath,
  newIssues,
  placePath,
  stageChanges,
  validateSettings,
  type SettingsTarget,
} from './stageSettings';

export type { SettingsTarget } from './stageSettings';

const FORM_ID = 'settings-form';

type GoogleField = (typeof GOOGLE_FIELDS)[number];
type Tab = 'models' | 'google';

const FIELDS: Array<{ key: GoogleField; label: string; hint?: string }> = [
  { key: 'gcp_project_id', label: 'GCP project', hint: 'Where uploaded data is loaded into BigQuery.' },
  { key: 'bq_dataset', label: 'BigQuery dataset' },
  { key: 'bq_location', label: 'BigQuery location', hint: 'For example US or EU.' },
  { key: 'gcs_bucket', label: 'GCS bucket', hint: 'Optional. Only needed to read CSV files from Cloud Storage.' },
];

const FIXED_HINT = 'Fixed by the deployment.';

/** Set by the first `403 settings_locked`; the deployment doesn't change while the page is open. */
let deploymentLocked = false;

/** What the form edits: the model settings plus the Google Cloud targets (the key has its own field). */
export type SettingsDraft = ModelsDraft & Record<GoogleField, string>;

/** The fields whose value differs from what the backend holds (deep per stage), plus the key when one was typed. */
export function changedFields(saved: Settings, draft: SettingsDraft, key: string): SettingsUpdate {
  const update: SettingsUpdate = {};
  const stages = stageChanges(saved.stages, draft.stages);
  if (stages) update.stages = stages;
  if (draft.fallback_model !== saved.fallback_model) update.fallback_model = draft.fallback_model;
  if (draft.review_briefs !== saved.review_briefs) update.review_briefs = draft.review_briefs;
  for (const field of GOOGLE_FIELDS) {
    const value = draft[field].trim();
    if (value !== saved[field]) update[field] = value;
  }
  if (key.trim() !== '') update.google_api_key = key.trim();
  return update;
}

const draftOf = (settings: Settings): SettingsDraft => ({
  stages: settings.stages,
  fallback_model: settings.fallback_model,
  review_briefs: settings.review_briefs,
  gcp_project_id: settings.gcp_project_id,
  bq_dataset: settings.bq_dataset,
  bq_location: settings.bq_location,
  gcs_bucket: settings.gcs_bucket,
});

/**
 * The draft after a save: the saved settings, except fields the user changed while the request
 * was in flight (still differing from what was sent), which keep the newer edit.
 */
export function rebaseDraft(saved: Settings, sent: SettingsDraft, current: SettingsDraft): SettingsDraft {
  const next = draftOf(saved);
  const stages = { ...next.stages } as unknown as Record<string, Record<string, unknown>>;
  for (const stage of Object.keys(stages)) {
    const before = sent.stages[stage as StageId] as unknown as Record<string, unknown>;
    const now = current.stages[stage as StageId] as unknown as Record<string, unknown>;
    for (const field of Object.keys(now)) {
      if (now[field] !== before[field]) stages[stage] = { ...stages[stage], [field]: now[field] };
    }
  }
  next.stages = stages as unknown as SettingsDraft['stages'];
  if (current.fallback_model !== sent.fallback_model) next.fallback_model = current.fallback_model;
  if (current.review_briefs !== sent.review_briefs) next.review_briefs = current.review_briefs;
  for (const field of GOOGLE_FIELDS) if (current[field] !== sent[field]) next[field] = current[field];
  return next;
}

/** The draft's value at an issue path (undefined for a path the form has no field for). */
function valueAt(draft: SettingsDraft, key: string, path: string): unknown {
  const place = placePath(path, draft.stages);
  if (!place) return undefined;
  if ('top' in place) return place.top === 'google_api_key' ? key : (draft as unknown as Record<string, unknown>)[place.top];
  return (draft.stages[place.stage] as unknown as Record<string, unknown>)[place.field];
}

type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; value: T };

/** A 422 issue and the value it was about: it shows until that field changes. */
type SaveIssue = ValidationIssue & { value: unknown };

const messageOf = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  /** The backend's settings after a successful save. */
  onSaved: (settings: Settings) => void;
  /** Open at a tab, or at a stage of the Models tab (expanded, its field focused). */
  at?: SettingsTarget;
}

/** Per-stage model settings, the write-only API key and the Google Cloud targets (docs/stage-settings-ui.md, Settings). */
export function SettingsModal({ open, onClose, onSaved, at }: SettingsModalProps) {
  const base = useId();
  const [load, setLoad] = useState<Load<Settings>>({ status: 'loading' });
  const [caps, setCaps] = useState<Load<SettingsCapabilities>>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [capsAttempt, setCapsAttempt] = useState(0);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [key, setKey] = useState('');
  const [tab, setTab] = useState<Tab>(at && 'tab' in at ? at.tab : 'models');
  const [expanded, setExpanded] = useState<ReadonlySet<StageId>>(new Set());
  const [advanced, setAdvanced] = useState<ReadonlySet<StageId>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<{ message: string; loose: string[] } | null>(null);
  const [saveIssues, setSaveIssues] = useState<SaveIssue[]>([]);
  const [saved, setSaved] = useState(false);
  const [locked, setLocked] = useState(deploymentLocked);
  const [lockNote, setLockNote] = useState(false);
  const [invalidText, setInvalidText] = useState<ReadonlySet<string>>(new Set());
  const [focusPath, setFocusPath] = useState<string | null>(null);
  const errorBox = useRef<HTMLDivElement>(null);
  const atRef = useRef(at);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoad({ status: 'loading' });
    setDraft(null);
    setKey('');
    setSaveError(null);
    setSaveIssues([]);
    setSaved(false);
    api.getSettings().then(
      (settings) => {
        if (!active) return;
        setDraft(draftOf(settings));
        setLoad({ status: 'ready', value: settings });
        // Stored issues open their rows; a target stage opens too, with its field focused.
        const target = atRef.current;
        const open = new Set<StageId>();
        const more = new Set<StageId>();
        for (const issue of settings.issues) {
          const place = placePath(issue.path, settings.stages);
          if (place && 'stage' in place) {
            open.add(place.stage);
            if (place.field === 'input_margin_pct') more.add(place.stage);
          }
        }
        if (target && 'stage' in target) {
          open.add(target.stage);
          let field: string = target.field ?? 'model';
          if (!isGenerationStage(target.stage) && field !== 'timeout_s') field = 'model';
          setFocusPath(`/stages/${target.stage}/${field}`);
        } else {
          // Focus starts on the selected tab once there is something to work with.
          setFocusPath('tab');
        }
        setExpanded(open);
        setAdvanced(more);
      },
      (error: unknown) => {
        if (active) setLoad({ status: 'error', message: messageOf(error, "Couldn't load the settings. Try again.") });
      },
    );
    return () => {
      active = false;
    };
  }, [open, attempt]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setCaps({ status: 'loading' });
    api.getSettingsCapabilities().then(
      (value) => {
        if (active) setCaps({ status: 'ready', value });
      },
      (error: unknown) => {
        if (active) setCaps({ status: 'error', message: messageOf(error, "Couldn't load the models. Try again.") });
      },
    );
    return () => {
      active = false;
    };
  }, [open, attempt, capsAttempt]);

  const settings = load.status === 'ready' ? load.value : null;
  const capabilities = caps.status === 'ready' ? caps.value : null;

  // Focus lands once its field is on screen (after a load, a tab switch or a row expanding).
  useLayoutEffect(() => {
    if (!focusPath) return;
    if (focusPath === 'error') {
      errorBox.current?.focus();
      setFocusPath(null);
      return;
    }
    const element = document.getElementById(focusPath === 'tab' ? `${base}-tab-${tab}` : fieldId(focusPath));
    if (element) {
      element.focus();
      setFocusPath(null);
    }
  });

  const clientIssues = useMemo(
    () =>
      settings && draft && capabilities
        ? {
            draft: validateSettings(draft.stages, draft.fallback_model, capabilities),
            saved: validateSettings(settings.stages, settings.fallback_model, capabilities),
          }
        : null,
    [settings, draft, capabilities],
  );
  const blockingIssues = clientIssues ? newIssues(clientIssues.draft, clientIssues.saved) : [];
  const update = settings && draft ? changedFields(settings, draft, key) : {};
  const dirty = Object.keys(update).length > 0;
  const blocked = invalidText.size > 0 || blockingIssues.length > 0;

  /** The messages a field shows: a failed save's, then the form's own check, then a stored issue while the value is unchanged. */
  const issuesAt = (path: string): string[] => {
    if (!settings || !draft) return [];
    const current = valueAt(draft, key, path);
    const fromSave = saveIssues.filter((i) => i.path === path && i.value === current);
    if (fromSave.length > 0) return fromSave.map((i) => i.message);
    const stored = current === valueAt(draftOf(settings), '', path) ? settings.issues.filter((i) => i.path === path) : [];
    if (stored.length > 0) return stored.map((i) => i.message);
    return clientIssues?.draft.filter((i) => i.path === path).map((i) => i.message) ?? [];
  };

  /** Shows a field: its tab, its row and its Advanced part, then focuses it. */
  const reveal = (path: string) => {
    const place = draft ? placePath(path, draft.stages) : null;
    if (!place) return;
    if ('stage' in place) {
      setTab('models');
      setExpanded((s) => new Set(s).add(place.stage));
      if (place.field === 'input_margin_pct') setAdvanced((s) => new Set(s).add(place.stage));
    } else {
      setTab(isGooglePath(path) ? 'google' : 'models');
    }
    setFocusPath(path);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!settings || !draft || !dirty || saving) return;
    if (blocked) {
      const first = blockingIssues[0];
      if (first) reveal(first.path);
      return;
    }
    const sent = draft;
    const sentKey = key;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    setLockNote(false);
    api.updateSettings(update).then(
      (settings) => {
        setSaving(false);
        setDraft((current) => (current ? rebaseDraft(settings, sent, current) : draftOf(settings)));
        setKey((current) => (current === sentKey ? '' : current));
        setSaveIssues([]);
        setSaved(true);
        setLoad({ status: 'ready', value: settings });
        onSaved(settings);
      },
      (error: unknown) => {
        setSaving(false);
        if (error instanceof ApiError && error.code === 'settings_locked') {
          // Nothing was saved: put the fixed fields back and let the models be saved alone.
          deploymentLocked = true;
          setLocked(true);
          setKey('');
          const restored = { ...sent };
          for (const field of GOOGLE_FIELDS) restored[field] = settings[field];
          setDraft((current) => {
            if (!current) return current;
            const next = { ...current };
            for (const field of GOOGLE_FIELDS) next[field] = settings[field];
            return next;
          });
          setLockNote(Object.keys(changedFields(settings, restored, '')).length > 0);
          return;
        }
        if (error instanceof ApiError && error.code === 'invalid_settings') {
          const issues = artifactIssues(error);
          const known = issues.filter((i) => placePath(i.path, sent.stages));
          const loose = issues.filter((i) => !placePath(i.path, sent.stages)).map((i) => i.message);
          setSaveIssues(known.map((i) => ({ ...i, value: valueAt(sent, sentKey, i.path) })));
          setSaveError({ message: error.message, loose });
          for (const issue of known) {
            const place = placePath(issue.path, sent.stages);
            if (place && 'stage' in place) setExpanded((s) => new Set(s).add(place.stage));
          }
          if (known[0]) reveal(known[0].path);
          else setFocusPath('error');
          return;
        }
        setSaveError({ message: messageOf(error, "Couldn't save the settings. Try again."), loose: [] });
      },
    );
  };

  const edit = (next: (d: SettingsDraft) => SettingsDraft) => {
    setSaved(false);
    setDraft((current) => (current ? next(current) : current));
  };

  const toggle = (set: (f: (s: ReadonlySet<StageId>) => ReadonlySet<StageId>) => void) => (stage: StageId) =>
    set((s) => {
      const next = new Set(s);
      if (next.has(stage)) next.delete(stage);
      else next.add(stage);
      return next;
    });

  const onInvalidText = (path: string, invalid: boolean) =>
    setInvalidText((s) => {
      if (s.has(path) === invalid) return s;
      const next = new Set(s);
      if (invalid) next.add(path);
      else next.delete(path);
      return next;
    });

  const onReset = (stage: StageId) => {
    if (caps.status !== 'ready') return;
    const defaults = caps.value.defaults.stages[stage];
    edit((d) => ({ ...d, stages: { ...d.stages, [stage]: { ...defaults } } }));
  };

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'models', label: 'Models' },
    { id: 'google', label: 'Google Cloud' },
  ];
  const tabId = (t: Tab) => `${base}-tab-${t}`;
  const panelId = (t: Tab) => `${base}-panel-${t}`;
  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = tabs.findIndex((t) => t.id === tab);
    let next: number | null = null;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    const id = tabs[next]!.id;
    setTab(id);
    document.getElementById(tabId(id))?.focus();
  };

  const storedLoose = settings ? settings.issues.filter((i) => !placePath(i.path, settings.stages)).map((i) => i.message) : [];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Settings"
      size="wide"
      description="Models for each stage, Google Cloud targets and your API key. The backend stores them."
      footer={
        <>
          <Button onClick={onClose}>Close</Button>
          <Button variant="primary" type="submit" form={FORM_ID} loading={saving} disabled={!dirty || blocked}>
            Save settings
          </Button>
        </>
      }
    >
      {load.status === 'loading' && <LoadingState>Loading settings…</LoadingState>}
      {load.status === 'error' && (
        <ErrorState title="Couldn't load the settings" message={load.message} onRetry={() => setAttempt((n) => n + 1)} />
      )}
      {settings && draft && (
        <form id={FORM_ID} onSubmit={submit} noValidate className="flex flex-col gap-3">
          {saveError && (
            <div ref={errorBox} tabIndex={-1} className="outline-none">
              <ErrorState
                title="Couldn't save the settings"
                message={
                  <>
                    {saveError.message}
                    {saveError.loose.map((message, i) => (
                      <span key={i} className="mt-0.5 block text-text">
                        {message}
                      </span>
                    ))}
                  </>
                }
              />
            </div>
          )}
          {lockNote && (
            <p role="status" className="flex items-start gap-2 rounded-panel border border-border bg-surface-muted px-3 py-2 text-body text-text">
              <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-text-muted" />
              Nothing was saved: the API key and Google Cloud settings are fixed here. Save again to keep your model changes.
            </p>
          )}
          <p role="status" className={saved ? 'flex items-center gap-1 text-label text-success' : 'sr-only'}>
            {saved ? 'Settings saved.' : ''}
          </p>
          <div role="tablist" aria-label="Settings sections" className="flex gap-1 border-b border-border">
            {tabs.map((t) => (
              <button
                key={t.id}
                id={tabId(t.id)}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                aria-controls={panelId(t.id)}
                tabIndex={tab === t.id ? 0 : -1}
                onClick={() => setTab(t.id)}
                onKeyDown={onTabKey}
                className={`-mb-px rounded-t-control border-b-2 px-3 py-1.5 text-body font-medium ${
                  tab === t.id ? 'border-primary text-primary' : 'border-transparent text-text-muted hover:text-text'
                } ${focusRing}`}
              >
                {t.label}
              </button>
            ))}
          </div>
          {tab === 'models' && (
            <div role="tabpanel" id={panelId('models')} aria-labelledby={tabId('models')}>
              {caps.status === 'loading' && <LoadingState>Loading models…</LoadingState>}
              {caps.status === 'error' && (
                <ErrorState title="Couldn't load the models" message={caps.message} onRetry={() => setCapsAttempt((n) => n + 1)} />
              )}
              {caps.status === 'ready' && (
                <ModelsTab
                  caps={caps.value}
                  draft={draft}
                  onDraft={(next) => edit((d) => ({ ...d, ...next(d) }))}
                  expanded={expanded}
                  onToggle={toggle(setExpanded)}
                  advanced={advanced}
                  onToggleAdvanced={toggle(setAdvanced)}
                  issuesAt={issuesAt}
                  onInvalidText={onInvalidText}
                  onReset={onReset}
                  notices={settings.notices}
                  looseIssues={storedLoose}
                />
              )}
            </div>
          )}
          {tab === 'google' && (
            <div role="tabpanel" id={panelId('google')} aria-labelledby={tabId('google')} className="flex flex-col gap-3">
              {locked && (
                <p className="flex items-start gap-2 rounded-panel border border-border bg-surface-muted px-3 py-2 text-body text-text">
                  <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-text-muted" />
                  The hosted app fixes the API key and Google Cloud settings.
                </p>
              )}
              <div className="flex flex-col gap-1">
                <Input
                  id={fieldId('/google_api_key')}
                  label="Google API key"
                  type="password"
                  value={key}
                  onChange={(e) => {
                    setSaved(false);
                    setKey(e.target.value);
                  }}
                  autoComplete="new-password"
                  aria-describedby={`${fieldId('/google_api_key')}-${issuesAt('/google_api_key')[0] ? 'error' : 'hint'} settings-key-status`}
                  spellCheck={false}
                  placeholder={locked ? '' : settings.google_api_key_set ? 'Paste a new key to replace it' : 'Paste your key'}
                  hint={locked ? FIXED_HINT : 'Sent to the backend and never shown again.'}
                  error={issuesAt('/google_api_key')[0]}
                  disabled={locked}
                />
                {settings.google_api_key_set ? (
                  <p id="settings-key-status" className="flex items-center gap-1 text-label font-medium text-success">
                    <CircleCheck aria-hidden="true" className="size-3.5" />
                    Key set
                  </p>
                ) : (
                  <p id="settings-key-status" className="text-label font-medium text-danger">
                    No key yet
                  </p>
                )}
              </div>
              {FIELDS.map(({ key: field, label, hint }) => (
                <Input
                  key={field}
                  id={fieldId(`/${field}`)}
                  label={label}
                  hint={locked ? FIXED_HINT : hint}
                  error={issuesAt(`/${field}`)[0]}
                  value={draft[field]}
                  onChange={(e) => {
                    const value = e.target.value;
                    edit((d) => ({ ...d, [field]: value }));
                  }}
                  disabled={locked}
                  autoComplete="off"
                  spellCheck={false}
                />
              ))}
            </div>
          )}
        </form>
      )}
    </Modal>
  );
}
