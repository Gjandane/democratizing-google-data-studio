import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { ApiError, type Assessment, type BuildEventMap, type FeasibilityDecision, type Issue } from '../../api/types';
import { Button } from '../../components/Button';
import { ErrorState } from '../../components/ErrorState';
import { focusRing } from '../../components/focus';
import { LoadingState } from '../../components/Spinner';
import { subscribeWorkspace } from './stretch';

export interface FeasibilityGates { planReady: boolean; buildReady: boolean }
const closed: FeasibilityGates = { planReady: false, buildReady: false };
const reasons: Record<Issue['status'], string> = {
  unsupported_product: 'Data Studio does not support this requirement.',
  unsupported_app: 'This app cannot produce this requirement.',
  needs_data: 'More data is needed for this requirement.',
  needs_clarification: 'Your clarification is needed for this requirement.',
  unknown: 'Support for this requirement is uncertain. Check feasibility or clarify it in chat.',
};
const messageOf = (error: unknown) => error instanceof ApiError ? error.message : "Couldn't check feasibility. Try again.";

/** Uses the workspace's existing stream; an assessment never implies consent to an alternative. */
export function FeasibilityPanel({ buildId, referencesReady = true, readOnly = false, onReadyChange }: {
  buildId: string; referencesReady?: boolean; readOnly?: boolean; onReadyChange?: (gates: FeasibilityGates) => void;
}) {
  const id = useId();
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const current = useRef<Assessment | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [externalBusy, setExternalBusy] = useState(false);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [focusRequest, setFocusRequest] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const mounted = useRef(false);
  const seq = useRef(0);
  const locked = useRef(false);
  const checking = useRef(false);
  const checkTicket = useRef(0);
  const pending = useRef<string | null>(null);
  const completions = useRef(new Map<string, BuildEventMap['run.finished']>());
  const runs = useRef(new Set<string>());
  const notify = useRef(onReadyChange);
  notify.current = onReadyChange;

  const accept = useCallback((value: Assessment) => {
    if (current.current?.id !== value.id) setSelected({});
    current.current = value;
    setAssessment(value);
  }, []);
  const load = useCallback(async () => {
    const request = ++seq.current;
    setLoading(true);
    setLoadError(null);
    try {
      const value = await api.getFeasibility(buildId);
      if (!mounted.current || request !== seq.current) return;
      accept(value);
      setLoading(false);
    } catch (reason) {
      if (!mounted.current || request !== seq.current) return;
      setLoading(false);
      setLoadError(messageOf(reason));
    }
  }, [buildId, accept]);

  useLayoutEffect(() => {
    const ready = !loading && !loadError && !busy && !externalBusy && referencesReady && assessment?.state === 'ready'
      && assessment.issues.every((issue) => issue.resolution !== 'unresolved');
    notify.current?.(ready ? { planReady: true, buildReady: !assessment.prototype_stale } : closed);
  }, [assessment, loading, loadError, busy, externalBusy, referencesReady]);
  useLayoutEffect(() => {
    if (focusRequest && !loading && !busy) {
      heading.current?.focus();
      setFocusRequest(0);
    }
  }, [focusRequest, loading, busy]);

  useEffect(() => {
    mounted.current = true;
    const settle = (result: BuildEventMap['run.finished']) => {
      if (pending.current !== result.run_id) return;
      pending.current = null;
      checking.current = false;
      locked.current = false;
      setBusy(false);
      setStatus(result.status === 'ok' ? 'Feasibility checked. Review the result.' : '');
      if (result.status === 'error') setError(result.error ?? 'The feasibility check failed. Try again.');
      setFocusRequest((n) => n + 1);
    };
    const unsubscribe = subscribeWorkspace(buildId, (event) => {
      if (event === 'open-references') return;
      if (event.name === 'run.started') { runs.current.add(event.data.run_id); setExternalBusy(true); }
      if (event.name === 'run.finished') {
        runs.current.delete(event.data.run_id);
        setExternalBusy(runs.current.size > 0);
        completions.current.set(event.data.run_id, event.data);
        if (completions.current.size > 50) completions.current.delete(completions.current.keys().next().value!);
        settle(event.data);
        void load();
      }
      if (event.name === 'ready') {
        runs.current.clear(); setExternalBusy(false);
        ++checkTicket.current;
        if (checking.current) {
          checking.current = false;
          pending.current = null; locked.current = false; setBusy(false);
          setStatus('Reconnected. Review the current feasibility result.');
        }
        void load();
      }
      if (event.name === 'docs.updated') void load();
    });
    return () => { mounted.current = false; ++seq.current; unsubscribe(); };
  }, [buildId, load]);
  // Reference mutations without a run (Remove) also invalidate feasibility.
  useLayoutEffect(() => { void load(); }, [load, referencesReady]);

  const check = async () => {
    if (locked.current || externalBusy || readOnly || !referencesReady) return;
    const ticket = ++checkTicket.current;
    checking.current = true;
    locked.current = true; setBusy(true); setError(null); setStatus('Checking feasibility…');
    try {
      const accepted = await api.checkFeasibility(buildId);
      if (!mounted.current || ticket !== checkTicket.current) return;
      pending.current = accepted.run_id;
      const finished = completions.current.get(accepted.run_id);
      if (finished) {
        checking.current = false;
        pending.current = null; locked.current = false; setBusy(false);
        setStatus(finished.status === 'ok' ? 'Feasibility checked. Review the result.' : '');
        if (finished.status === 'error') setError(finished.error ?? 'The feasibility check failed. Try again.');
        setFocusRequest((n) => n + 1);
        void load();
      }
    } catch (reason) {
      if (!mounted.current || ticket !== checkTicket.current) return;
      checking.current = false;
      locked.current = false; setBusy(false); setStatus(''); setError(messageOf(reason));
      setFocusRequest((n) => n + 1);
    }
  };
  const decide = async (decision: FeasibilityDecision) => {
    const assessmentId = current.current?.id;
    if (!assessmentId || locked.current || loading || loadError || externalBusy || readOnly || !referencesReady) return;
    const request = seq.current;
    locked.current = true; setBusy(true); setError(null); setStatus('Saving your decision…');
    try {
      const value = await api.decideFeasibility(buildId, assessmentId, [decision]);
      if (!mounted.current) return;
      // A refetch or newer assessment arrived while the decision was in flight.
      if (current.current?.id === assessmentId && request === seq.current) accept(value);
      setStatus('Decision saved. Review the current assessment before continuing.');
      await load();
    } catch (reason) {
      if (!mounted.current) return;
      setStatus('');
      if (reason instanceof ApiError && reason.code === 'feasibility_stale') {
        setSelected({});
        setError('The requirements changed. Review the refreshed assessment and choose again.');
        await load();
      } else setError(messageOf(reason));
    } finally {
      if (mounted.current) { locked.current = false; setBusy(false); setFocusRequest((n) => n + 1); }
    }
  };
  const disabled = readOnly || busy || externalBusy || loading || Boolean(loadError) || !referencesReady;
  return (
    <section aria-labelledby={`${id}-heading`} className="mt-4 min-w-0 rounded-panel border border-border bg-surface p-4">
      <h3 ref={heading} id={`${id}-heading`} tabIndex={-1} className={`rounded-control text-title font-semibold text-text ${focusRing}`}>Feasibility</h3>
      {loading && <LoadingState>Loading feasibility…</LoadingState>}
      {loadError && <ErrorState className="mt-3" title="Couldn't load feasibility" message={loadError} onRetry={() => { setFocusRequest((n) => n + 1); void load(); }} retryLabel="Retry feasibility" />}
      {!loading && !loadError && assessment && <div className="mt-2 space-y-3">
        <p className="text-body text-text-muted">{assessment.state === 'ready' ? 'Your requirements are resolved.' : assessment.state === 'blocked' ? 'Resolve these requirements before generating or building.' : assessment.state === 'stale' ? 'Requirements changed. Check feasibility again before continuing.' : 'Check what this app supports before generating or building.'}</p>
        {assessment.prototype_stale && <p className="text-body font-medium text-danger">This prototype is out of date. Update the plan before generating a recipe or building.</p>}
        {assessment.issues.filter((issue) => issue.resolution === 'unresolved').map((issue) => <fieldset key={`${assessment.id}-${issue.id}`} disabled={disabled} className="min-w-0 space-y-2 rounded-control border border-border p-3">
          <legend className="max-w-full px-1 text-body font-semibold text-text [overflow-wrap:anywhere]">{issue.requirement}</legend>
          <p className="text-body font-medium text-text">{issue.status === 'unsupported_app' && /animate GPS points/i.test(issue.requirement) ? 'This app cannot animate GPS points.' : reasons[issue.status]}</p>
          <p className="text-body text-text-muted [overflow-wrap:anywhere]">{issue.reason}</p>
          <ul className="space-y-1 text-label [overflow-wrap:anywhere]" aria-label="Evidence">{issue.evidence.map((entry, index) => <li key={index}>{/^https?:\/\//i.test(entry) ? <a href={entry} target="_blank" rel="noopener noreferrer" className={`text-primary underline hover:text-primary-hover ${focusRing}`}>{entry}<span className="sr-only"> (opens in a new tab)</span></a> : <code className="font-mono text-text-muted">{entry}</code>}</li>)}</ul>
          {issue.alternatives.map((alternative) => <label key={alternative.id} className="flex items-start gap-2 text-body text-text">
            <input type="radio" name={`${id}-${issue.id}`} value={alternative.id} checked={selected[issue.id] === alternative.id} onChange={() => setSelected((value) => ({ ...value, [issue.id]: alternative.id }))} className={`mt-1 accent-primary ${focusRing}`} />
            <span className="min-w-0 [overflow-wrap:anywhere]">{alternative.label}</span>
          </label>)}
          <div className="flex flex-wrap gap-2">
            {issue.alternatives.length > 0 && <Button disabled={disabled || !selected[issue.id] || !assessment.id} onClick={() => void decide({ issue_id: issue.id, action: 'accept_alternative', alternative_id: selected[issue.id]! })}>Use this alternative</Button>}
            <Button disabled={disabled || !assessment.id} onClick={() => void decide({ issue_id: issue.id, action: 'drop', alternative_id: null })}>Drop this requirement</Button>
            {issue.status === 'needs_clarification' && <Button variant="ghost" onClick={() => document.querySelector<HTMLTextAreaElement>('aside[aria-label="Chat"] textarea')?.focus()}>Clarify in chat</Button>}
          </div>
        </fieldset>)}
        {!readOnly && (assessment.state !== 'ready' || assessment.issues.some((issue) => issue.status === 'unknown' && issue.resolution === 'unresolved')) && <Button disabled={disabled} loading={busy} onClick={() => void check()}>Check feasibility</Button>}
      </div>}
      {error && <p role="alert" className="mt-2 text-body text-danger">{error}</p>}
      <p role="status" className="mt-2 text-label text-text-muted">{status}</p>
    </section>
  );
}
