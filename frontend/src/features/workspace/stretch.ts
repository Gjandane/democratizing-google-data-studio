// Shared by connect/ (style images, research) and prototype/ (audit), so it sits at workspace/ root.
// The three stretch routes may be missing on the backend: a 404 hides the control instead of erroring.
import { useEffect, useRef, useState, type RefObject } from 'react';
import { ApiError, type BuildEvent, type RunAccepted } from '../../api/types';
import type { NodeRun, StretchNode, StretchRuns } from './chat/useBuildStream';

/** The control disables itself while its action runs, which drops focus to the body: put it back when it ends. */
export function useRefocusAfter(busy: boolean, target: RefObject<HTMLElement | null>): void {
  const was = useRef(busy);
  useEffect(() => {
    const lost = document.activeElement === null || document.activeElement === document.body;
    if (was.current && !busy && lost) target.current?.focus();
    was.current = busy;
  }, [busy, target]);
}

export type StretchRoute = 'style-images' | 'research' | 'audit';

const unavailable = new Set<string>();

export const isStretchUnavailable = (route: StretchRoute): boolean => unavailable.has(route);
export const markStretchUnavailable = (route: StretchRoute): void => {
  unavailable.add(route);
};
/** For tests (beforeEach): forget which routes answered 404. */
export const resetStretchAvailability = (): void => {
  unavailable.clear();
};

/** A stretch route the backend doesn't serve. `build_not_found` is a real error and shows as one. */
export const isMissingRoute = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 404 && error.code !== 'build_not_found';

export type StretchState = 'idle' | 'starting' | 'running' | 'ok' | 'error';

export interface StretchAction {
  hidden: boolean;
  state: StretchState;
  error: string | null;
  start: (fn: () => Promise<RunAccepted>) => Promise<void>;
}

/** Posts a stretch action and follows its run on the build's stream. */
export function useStretchAction(route: StretchRoute, node: StretchNode, stretchRuns: StretchRuns): StretchAction {
  const [hidden, setHidden] = useState(() => isStretchUnavailable(route));
  const [starting, setStarting] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [seen, setSeen] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const entry = stretchRuns[node];
  const mine = runId !== null && entry?.run_id === runId ? entry : null;
  /** The node's entry when our POST went out: a different entry after it is a newer run (another tab). */
  const baseline = useRef<NodeRun | undefined>(undefined);

  // Events aren't replayed: when our run was running and its entry is dropped (reconnect), let go of it.
  useEffect(() => {
    if (mine?.status === 'running' && !seen) setSeen(true);
    else if (runId !== null && seen && !entry) {
      setRunId(null);
      setSeen(false);
    }
  }, [mine, runId, seen, entry]);

  const start = async (fn: () => Promise<RunAccepted>) => {
    setStarting(true);
    setLocalError(null);
    setSeen(false);
    baseline.current = stretchRuns[node];
    try {
      const accepted = await fn();
      if (!mounted.current) return;
      setRunId(accepted.run_id);
    } catch (error) {
      if (!mounted.current) return;
      setRunId(null);
      if (isMissingRoute(error)) {
        markStretchUnavailable(route);
        setHidden(true);
      } else {
        setLocalError(error instanceof ApiError ? error.message : "Couldn't start this. Try again.");
      }
    } finally {
      if (mounted.current) setStarting(false);
    }
  };

  let state: StretchState = 'idle';
  let error = localError;
  if (starting) state = 'starting';
  else if (localError) state = 'error';
  else if (runId !== null) {
    if (mine) {
      state = mine.status;
      if (mine.status === 'error') error = mine.error ?? "That didn't finish. Try again.";
    } else if (entry && entry !== baseline.current) {
      // A newer run of this node (another tab) replaced ours: show that one rather than wait forever.
      state = entry.status;
      if (entry.status === 'error') error = entry.error ?? "That didn't finish. Try again.";
    } else {
      // Accepted, run.started not seen yet.
      state = 'running';
    }
  } else if (entry?.status === 'running') {
    // Started from another tab.
    state = 'running';
  }
  return { hidden: hidden || isStretchUnavailable(route), state, error, start };
}

// Fan out the workspace's existing SSE connection to required resource panels.
const workspaceListeners = new Map<string, Set<(event: BuildEvent | 'open-references') => void>>();
export function subscribeWorkspace(buildId: string, listener: (event: BuildEvent | 'open-references') => void): () => void {
  const listeners = workspaceListeners.get(buildId) ?? new Set();
  workspaceListeners.set(buildId, listeners);
  listeners.add(listener);
  return () => { listeners.delete(listener); if (!listeners.size) workspaceListeners.delete(buildId); };
}
export function publishWorkspace(buildId: string, event: BuildEvent | 'open-references'): void {
  workspaceListeners.get(buildId)?.forEach((listener) => listener(event));
}
export const openReferencePanel = (buildId: string): void => publishWorkspace(buildId, 'open-references');
