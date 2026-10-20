import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { ApiError, referenceValidation, type BuildEventMap, type ReferenceMode, type ReferenceSet } from '../../api/types';
import { Button } from '../../components/Button';
import { ErrorState } from '../../components/ErrorState';
import { TextArea } from '../../components/Input';
import { focusRing } from '../../components/focus';
import { LoadingState } from '../../components/Spinner';
import { subscribeWorkspace, useRefocusAfter } from './stretch';

type Finished = BuildEventMap['run.finished'];
const modeName = (mode: ReferenceMode) => mode === 'style' ? 'Use style' : 'Recreate dashboard';
const displayName = (name: string) => name.split(/[\\/]/).pop() || 'Reference image';
const referenceError = (error: unknown) => {
  if (error instanceof ApiError) {
    if (error.status === 413) return 'Reference images exceed the upload limit. Use at most 5 MiB each and 15 MiB total.';
    if (error.status === 422) return 'Could not read these reference images. Use valid, non-animated PNG/JPEG images, at most 20 million pixels each, and instructions up to 2000 characters.';
    return error.message;
  }
  return "Couldn't save the references. Try again.";
};

/** One retained reference set. Chat opens this same stage panel; it has no second SSE connection. */
export function ReferencePanel({ buildId, version = 1, readOnly = false, disabled = false, defaultOpen = true, onReadyChange, onSavedChange }: {
  buildId: string; version?: number; readOnly?: boolean; disabled?: boolean; onReadyChange?: (ready: boolean) => void;
  /** Starts collapsed when false (Prototype); Attach reference still opens it. */
  defaultOpen?: boolean;
  /** The saved set once loaded (null: none); undefined while loading or after a failed load. */
  onSavedChange?: (saved: ReferenceSet | null | undefined) => void;
}) {
  const id = useId();
  const [saved, setSaved] = useState<ReferenceSet | null>(null);
  const [loading, setLoading] = useState(true);
  const readiness = useRef(onReadyChange);
  readiness.current = onReadyChange;
  const savedChange = useRef(onSavedChange);
  savedChange.current = onSavedChange;
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<ReferenceMode>('style');
  const [instructions, setInstructions] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [focusRequest, setFocusRequest] = useState(0);
  const panel = useRef<HTMLElement>(null);
  const summary = useRef<HTMLElement>(null);
  const firstMode = useRef<HTMLInputElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const upload = useRef<HTMLButtonElement>(null);
  const removing = useRef(false);
  const inFlight = useRef(false);
  const dirty = useRef(false);
  const pending = useRef<string | null>(null);
  const mounted = useRef(false);
  const fetchSeq = useRef(0);
  const finished = useRef(new Map<string, Finished>());
  const activeRuns = useRef(new Set<string>());
  const [externalBusy, setExternalBusy] = useState(false);
  const locked = busy || disabled || externalBusy;
  useRefocusAfter(busy, upload);
  // A background refetch keeps the loaded set and readiness; an error stays (closed) until a GET succeeds.
  useLayoutEffect(() => {
    readiness.current?.(loaded && !loadError && !busy);
  }, [loaded, loadError, busy]);
  useLayoutEffect(() => {
    savedChange.current?.(loaded && !loadError ? saved : undefined);
  }, [loaded, loadError, saved]);

  useLayoutEffect(() => {
    if (!focusRequest) return;
    panel.current?.scrollIntoView?.({ block: 'nearest' });
    firstMode.current?.focus();
    // Read-only, loading or busy: the first choice can't take focus, so the panel's summary does.
    if (document.activeElement !== firstMode.current) summary.current?.focus();
  }, [focusRequest]);

  useLayoutEffect(() => {
    if (!busy && removing.current) {
      removing.current = false;
      input.current?.focus();
    }
  }, [busy]);

  useEffect(() => {
    mounted.current = true;
    let current = true;
    const load = async (initial = false) => {
      const seq = ++fetchSeq.current;
      setLoading(true);
      try {
        const value = await api.getReferences(buildId);
        if (!current || seq !== fetchSeq.current) return;
        setLoading(false);
        setLoadError(null);
        setSaved(value);
        setLoaded(true);
        if (initial && value && !dirty.current) { setMode(value.mode); setInstructions(value.instructions); }
      } catch (reason) {
        if (current && seq === fetchSeq.current) {
          setLoading(false);
          setLoadError(reason instanceof ApiError ? reason.message : "Couldn't load references. Try again.");
        }
      }
    };
    // An event can precede the POST response. Keep completions keyed by run_id until it arrives.
    const settle = (result: Finished) => {
      if (pending.current !== result.run_id) return;
      pending.current = null;
      inFlight.current = false;
      setBusy(false);
      if (result.status === 'ok') {
        setFiles([]);
        if (input.current) input.current.value = '';
        setStatus('References saved. The planner uses them.');
      } else {
        setStatus('');
        setError('Could not read the reference images. Try clearer PNG/JPEG images. Your saved references are unchanged.');
      }
    };
    const unsubscribe = subscribeWorkspace(buildId, (event) => {
      if (event === 'open-references') {
        const details = panel.current?.querySelector('details');
        if (details) details.open = true;
        setFocusRequest((n) => n + 1);
        return;
      }
      if (event.name === 'run.started') {
        activeRuns.current.add(event.data.run_id);
        setExternalBusy(true);
      }
      if (event.name === 'run.finished') {
        activeRuns.current.delete(event.data.run_id);
        setExternalBusy(activeRuns.current.size > 0);
        finished.current.set(event.data.run_id, event.data);
        if (finished.current.size > 50) finished.current.delete(finished.current.keys().next().value!);
        settle(event.data);
        void load();
      }
      if (event.name === 'ready') {
        activeRuns.current.clear();
        setExternalBusy(false);
        // Events are not replayed. Recover the retained server state after a disconnect.
        if (pending.current) {
          pending.current = null;
          inFlight.current = false;
          setBusy(false);
          setStatus('Reconnected. Review the saved references before trying again.');
        }
        void load(true);
      }
      if (event.name === 'docs.updated') void load();
    });
    void load(true);
    return () => { current = false; mounted.current = false; ++fetchSeq.current; unsubscribe(); };
  }, [buildId, version]);

  const reload = () => {
    const seq = ++fetchSeq.current;
    setLoading(true);
    api.getReferences(buildId).then((value) => {
      if (!mounted.current || seq !== fetchSeq.current) return;
      setLoading(false); setLoadError(null); setSaved(value); setLoaded(true);
      if (value && !dirty.current) { setMode(value.mode); setInstructions(value.instructions); }
    }, (reason: unknown) => {
      if (mounted.current && seq === fetchSeq.current) { setLoading(false); setLoadError(referenceError(reason)); }
    });
  };

  const submit = async () => {
    if (inFlight.current || locked || !loaded || loadError) return;
    const problem = referenceValidation(files, mode, instructions);
    setError(problem);
    if (problem) { input.current?.focus(); return; }
    inFlight.current = true;
    setBusy(true); setStatus(`Uploading ${files.length} ${files.length === 1 ? 'image' : 'images'}…`);
    try {
      const accepted = await api.uploadReferences(buildId, files, mode, instructions);
      if (!mounted.current) return;
      pending.current = accepted.run_id;
      setStatus('Reading your references…');
      const result = finished.current.get(accepted.run_id);
      if (result) {
        pending.current = null; inFlight.current = false; setBusy(false);
        if (result.status === 'ok') {
          setFiles([]); if (input.current) input.current.value = '';
          setStatus('References saved. The planner uses them.'); reload();
        } else {
          setStatus(''); setError('Could not read the reference images. Try clearer PNG/JPEG images. Your saved references are unchanged.');
        }
      }
    } catch (reason) {
      if (!mounted.current) return;
      inFlight.current = false; setBusy(false); setStatus(''); setError(referenceError(reason));
    }
  };

  const remove = async () => {
    if (inFlight.current || locked || loadError) return;
    inFlight.current = true; setBusy(true); setError(null); setStatus('Removing references…');
    try {
      await api.deleteReferences(buildId);
      if (!mounted.current) return;
      setSaved(null); setFiles([]); setInstructions(''); setMode('style');
      if (input.current) input.current.value = '';
      removing.current = true; setStatus('References removed.'); reload();
    } catch (reason) {
      if (mounted.current) { setStatus(''); setError(referenceError(reason)); }
    } finally {
      if (mounted.current) { inFlight.current = false; setBusy(false); }
    }
  };

  return (
    <section ref={panel} aria-label="References" className="min-w-0 rounded-panel border border-border bg-surface p-4">
      <details open={defaultOpen}>
        <summary ref={summary} className={`cursor-pointer rounded-control text-title font-semibold text-text ${focusRing}`}>References</summary>
        <div className="mt-3 flex min-w-0 flex-col gap-3">
          {!loaded && !loadError && <LoadingState>Loading references…</LoadingState>}
          {loadError && <ErrorState title="Couldn't load references" message={loadError} onRetry={reload} retryLabel="Retry references" retryLoading={loading} />}
          {loaded && !saved && <p className="text-body text-text-muted">No references yet. Add a style example or a dashboard to recreate.</p>}
          {saved && <div className="min-w-0 space-y-2">
            <p className="text-body font-medium text-text">Saved mode: {modeName(saved.mode)}</p>
            <ul className="flex min-w-0 flex-wrap gap-3" aria-label="Saved reference images">
              {saved.images.map((image) => <li key={image.id} className="w-32 min-w-0">
                {/^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*\.(png|jpe?g)$/i.test(image.file) && <img src={api.fileUrl(buildId, image.file)} alt={`${modeName(saved.mode)} reference: ${displayName(image.name)}`} className="h-20 w-32 rounded-control border border-border bg-surface-muted object-contain" />}
                <p title={displayName(image.name)} className="truncate text-caption text-text-muted">{displayName(image.name)}</p>
              </li>)}
            </ul>
            <p className="whitespace-pre-wrap text-body text-text [overflow-wrap:anywhere]">{saved.summary}</p>
            {saved.instructions && <p className="whitespace-pre-wrap text-label text-text-muted [overflow-wrap:anywhere]">Instructions: {saved.instructions}</p>}
          </div>}
          {!readOnly && <form className="flex min-w-0 flex-col gap-3" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
            <fieldset disabled={locked || !loaded || Boolean(loadError)} className="flex min-w-0 flex-col gap-3">
              <legend className="sr-only">Reference mode</legend>
              <div className="flex flex-wrap gap-4">
                {(['style', 'recreate'] as const).map((choice) => <label key={choice} className="inline-flex items-center gap-2 text-body text-text">
                  <input ref={choice === 'style' ? firstMode : undefined} type="radio" name={`${id}-mode`} value={choice} checked={mode === choice} onChange={() => { dirty.current = true; setMode(choice); setError(null); }} className={`accent-primary ${focusRing}`} />
                  {modeName(choice)}
                </label>)}
              </div>
              <TextArea label="Reference instructions" name="instructions" autoComplete="off" value={instructions} maxLength={2000} rows={2} onChange={(event) => { dirty.current = true; setInstructions(event.target.value); }} hint="Optional, up to 2000 characters. Describe what to use or change." />
              <p id={`${id}-limits`} className="text-caption text-text-muted">Use style: 1-3 images. Recreate dashboard: exactly 1. PNG/JPEG only, 5 MiB each, 15 MiB total.</p>
              <label htmlFor={`${id}-files`} className="text-label font-medium text-text">Reference images</label>
              <input ref={input} id={`${id}-files`} name="files" type="file" multiple={mode === 'style'} accept="image/png,image/jpeg,.png,.jpg,.jpeg" aria-describedby={`${id}-limits${error ? ` ${id}-error` : ''}`} aria-invalid={error ? true : undefined} className={`w-full min-w-0 truncate rounded-control text-body text-text file:mr-3 file:rounded-control file:border file:border-border-strong file:bg-surface-muted file:px-3 file:py-1 file:text-text hover:file:bg-primary-soft ${focusRing}`} onChange={(event) => {
                dirty.current = true;
                const selection = Array.from(event.target.files ?? []); setFiles(selection); setError(selection.length ? referenceValidation(selection, mode, instructions) : null);
              }} />
              {files.length > 0 && <ul aria-label="Selected reference images" className="min-w-0 text-caption text-text-muted">{files.map((file, index) => <li key={index} className="truncate" title={displayName(file.name)}>{displayName(file.name)}</li>)}</ul>}
              <div className="flex flex-wrap gap-2">
                <Button ref={upload} type="submit" variant="secondary" loading={busy && !removing.current} disabled={locked || files.length === 0}>{saved ? 'Replace references' : 'Upload references'}</Button>
                {saved && <Button variant="ghost" disabled={locked} onClick={() => void remove()}>Remove references</Button>}
              </div>
            </fieldset>
          </form>}
          <p role="status" className="min-h-5 text-body text-text-muted">{status}</p>
          {error && <p id={`${id}-error`} role="alert" className="text-label text-danger">{error}</p>}
          {readOnly && <p className="text-caption text-text-muted">Start a new version to change these references.</p>}
        </div>
      </details>
    </section>
  );
}
