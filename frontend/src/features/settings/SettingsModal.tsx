import { CircleCheck, Lock } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../../api/client';
import { ApiError, type Settings, type SettingsUpdate } from '../../api/types';
import { Button } from '../../components/Button';
import { ErrorState } from '../../components/ErrorState';
import { Input } from '../../components/Input';
import { Modal } from '../../components/Modal';
import { LoadingState } from '../../components/Spinner';

const FORM_ID = 'settings-form';

type TextField = Exclude<keyof Settings, 'google_api_key_set'>;

const FIELDS: Array<{ key: TextField; label: string; hint?: string }> = [
  { key: 'planner_model', label: 'Planner model', hint: 'Writes the interview, plan and prototype.' },
  { key: 'worker_model', label: 'Worker model', hint: 'Handles the smaller, faster steps.' },
  { key: 'gcp_project_id', label: 'GCP project', hint: 'Where uploaded data is loaded into BigQuery.' },
  { key: 'bq_dataset', label: 'BigQuery dataset' },
  { key: 'bq_location', label: 'BigQuery location', hint: 'For example US or EU.' },
  { key: 'gcs_bucket', label: 'GCS bucket', hint: 'Optional. Only needed to read CSV files from Cloud Storage.' },
];

/** The fields the hosted app fixes (`403 settings_locked`); only the models stay editable there. */
const DEPLOYMENT_FIELDS: ReadonlySet<TextField> = new Set(['gcp_project_id', 'bq_dataset', 'bq_location', 'gcs_bucket']);
const FIXED_HINT = 'Fixed by the deployment.';

/** Set by the first `403 settings_locked`; the deployment doesn't change while the page is open. */
let deploymentLocked = false;

/** The fields whose value differs from what the backend holds, plus the key when one was typed. */
export function changedFields(saved: Settings, draft: Record<TextField, string>, key: string): SettingsUpdate {
  const update: SettingsUpdate = {};
  for (const { key: field } of FIELDS) {
    const value = draft[field].trim();
    if (value !== saved[field]) update[field] = value;
  }
  if (key.trim() !== '') update.google_api_key = key.trim();
  return update;
}

const draftOf = (settings: Settings): Record<TextField, string> => ({
  planner_model: settings.planner_model,
  worker_model: settings.worker_model,
  gcp_project_id: settings.gcp_project_id,
  bq_dataset: settings.bq_dataset,
  bq_location: settings.bq_location,
  gcs_bucket: settings.gcs_bucket,
});

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; settings: Settings };

const messageOf = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  /** The backend's settings after a successful save. */
  onSaved: (settings: Settings) => void;
}

/** Planner and worker model, the write-only API key and the Google Cloud targets. */
export function SettingsModal({ open, onClose, onSaved }: SettingsModalProps) {
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [draft, setDraft] = useState<Record<TextField, string> | null>(null);
  const [key, setKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [locked, setLocked] = useState(deploymentLocked);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoad({ status: 'loading' });
    setDraft(null);
    setKey('');
    setSaveError(null);
    setSaved(false);
    api.getSettings().then(
      (settings) => {
        if (!active) return;
        setDraft(draftOf(settings));
        setLoad({ status: 'ready', settings });
      },
      (error: unknown) => {
        if (active) setLoad({ status: 'error', message: messageOf(error, "Couldn't load the settings. Try again.") });
      },
    );
    return () => {
      active = false;
    };
  }, [open, attempt]);

  const ready = load.status === 'ready' && draft !== null;
  const update = ready ? changedFields(load.settings, draft, key) : {};
  const dirty = Object.keys(update).length > 0;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!ready || !dirty || saving) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    api.updateSettings(update).then(
      (settings) => {
        setSaving(false);
        setDraft(draftOf(settings));
        setKey('');
        setSaved(true);
        setLoad({ status: 'ready', settings });
        onSaved(settings);
      },
      (error: unknown) => {
        setSaving(false);
        if (error instanceof ApiError && error.code === 'settings_locked') {
          // Nothing was saved: put the fixed fields back and let the models be saved alone.
          deploymentLocked = true;
          setLocked(true);
          setKey('');
          setDraft((current) => {
            if (!current || load.status !== 'ready') return current;
            const next = { ...current };
            for (const field of DEPLOYMENT_FIELDS) next[field] = load.settings[field];
            return next;
          });
          return;
        }
        setSaveError(messageOf(error, "Couldn't save the settings. Try again."));
      },
    );
  };

  const edit = (field: TextField, value: string) => {
    setSaved(false);
    setDraft((current) => (current ? { ...current, [field]: value } : current));
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Settings"
      description="Models, Google Cloud targets and your API key. They are stored by the backend."
      footer={
        <>
          <Button onClick={onClose}>Close</Button>
          <Button variant="primary" type="submit" form={FORM_ID} loading={saving} disabled={!dirty}>
            Save settings
          </Button>
        </>
      }
    >
      {load.status === 'loading' && <LoadingState>Loading settings…</LoadingState>}
      {load.status === 'error' && (
        <ErrorState title="Couldn't load the settings" message={load.message} onRetry={() => setAttempt((n) => n + 1)} />
      )}
      {ready && (
        <form id={FORM_ID} onSubmit={submit} className="flex flex-col gap-3">
          {saveError && <ErrorState title="Couldn't save the settings" message={saveError} />}
          {locked && (
            <p role="status" className="flex items-start gap-2 rounded-panel border border-border bg-surface-muted px-3 py-2 text-body text-text">
              <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-text-muted" />
              The hosted app fixes the API key and Google Cloud settings. You can still change the models.
            </p>
          )}
          <p role="status" className={saved ? 'flex items-center gap-1 text-label text-success' : 'sr-only'}>
            {saved ? 'Settings saved.' : ''}
          </p>
          {FIELDS.slice(0, 2).map(({ key: field, label, hint }) => (
            <Input key={field} label={label} hint={hint} value={draft[field]} onChange={(e) => edit(field, e.target.value)} autoComplete="off" spellCheck={false} />
          ))}
          <div className="flex flex-col gap-1">
            <Input
              id="settings-key"
              label="Google API key"
              type="password"
              value={key}
              onChange={(e) => {
                setSaved(false);
                setKey(e.target.value);
              }}
              autoComplete="new-password"
              aria-describedby="settings-key-hint settings-key-status"
              spellCheck={false}
              placeholder={locked ? '' : load.settings.google_api_key_set ? 'Paste a new key to replace it' : 'Paste your key'}
              hint={locked ? FIXED_HINT : 'Sent to the backend and never shown again.'}
              disabled={locked}
            />
            {load.settings.google_api_key_set ? (
              <p id="settings-key-status" className="flex items-center gap-1 text-label font-medium text-success">
                <CircleCheck aria-hidden="true" className="size-3.5" />
                Key set
              </p>
            ) : (
              <p id="settings-key-status" className="text-label font-medium text-danger">No key yet</p>
            )}
          </div>
          {FIELDS.slice(2).map(({ key: field, label, hint }) => {
            const fixed = locked && DEPLOYMENT_FIELDS.has(field);
            return (
              <Input
                key={field}
                label={label}
                hint={fixed ? FIXED_HINT : hint}
                value={draft[field]}
                onChange={(e) => edit(field, e.target.value)}
                disabled={fixed}
                autoComplete="off"
                spellCheck={false}
              />
            );
          })}
        </form>
      )}
    </Modal>
  );
}
