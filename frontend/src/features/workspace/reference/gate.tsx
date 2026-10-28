// The reference analysis gate (docs/reference-ui.md, Reference analysis review): while a recreate
// set's analysis waits for approval, Confirm design, Regenerate/Accept blueprint, Generate recipe
// and Build are off with one reason. The References panel reports the set it loaded; Workspace
// owns the one gate and provides it here; actions read it with useAnalysisGate.
import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ApiClient } from '../../../api/client';
import { ApiError, type ReferenceSet } from '../../../api/types';

export const ANALYSIS_GATE_REASON = 'Approve the reference analysis first';

/** A recreate set whose analysis isn't approved: pending, or null (saved before dashboard-intent 1.3). */
export const analysisPending = (set: ReferenceSet | null | undefined): boolean =>
  set?.mode === 'recreate' && set.analysis?.state !== 'approved';

export interface AnalysisGate {
  /** The reference set the panel last loaded or saved; undefined before the first load. */
  set: ReferenceSet | null | undefined;
  /** True while the gated actions wait for an approval. */
  pending: boolean;
  /** The panel reports each set it loads or saves. */
  report: (set: ReferenceSet | null) => void;
  /** Bumped by focusReview: the panel opens, refetches and focuses the review heading. */
  focusRequest: number;
  focusReview: () => void;
}

export const AnalysisGateContext = createContext<AnalysisGate | null>(null);

/** The workspace's gate (null outside a workspace: nothing gated). */
export function useAnalysisGate(): AnalysisGate | null {
  return useContext(AnalysisGateContext);
}

/** Owns the gate: Workspace calls it once and provides the value. */
export function useAnalysisGateState(): AnalysisGate {
  const [set, setSet] = useState<ReferenceSet | null | undefined>(undefined);
  const [focusRequest, setFocusRequest] = useState(0);
  const report = useCallback((next: ReferenceSet | null) => setSet(next), []);
  const focusReview = useCallback(() => setFocusRequest((n) => n + 1), []);
  return useMemo(() => ({ set, pending: analysisPending(set), report, focusRequest, focusReview }), [set, report, focusRequest, focusReview]);
}

/** Why a gated action is off, with a link to the review. */
export function GateReason({ id, className = '' }: { id?: string; className?: string }) {
  const gate = useAnalysisGate();
  return (
    <span id={id} className={className}>
      {ANALYSIS_GATE_REASON}.{' '}
      <button type="button" onClick={() => gate?.focusReview()} className="rounded-control font-medium text-primary underline underline-offset-2 hover:text-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
        Review it
      </button>
    </span>
  );
}

export function isReferenceUnapproved(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.code === 'reference_unapproved';
}

const listeners = new Set<() => void>();

/** Calls `listener` for every `409 reference_unapproved` from now on; returns the unsubscribe function. */
export function onReferenceUnapproved(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The same client; a rejected call that is `reference_unapproved` is reported, then rethrown unchanged. */
export function withReferenceNotice(client: ApiClient): ApiClient {
  const wrapped: Record<string, unknown> = {};
  for (const [name, fn] of Object.entries(client) as Array<[string, (...args: unknown[]) => unknown]>) {
    wrapped[name] = (...args: unknown[]) => {
      const result = fn(...args);
      if (!(result instanceof Promise)) return result;
      return result.catch((error: unknown) => {
        if (isReferenceUnapproved(error)) listeners.forEach((listener) => listener());
        throw error;
      });
    };
  }
  return wrapped as unknown as ApiClient;
}
