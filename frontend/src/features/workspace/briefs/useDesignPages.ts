import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, type BuildEvent, type DesignPages } from '../../../api/types';
import { subscribeWorkspace } from '../stretch';

export interface DesignPagesState {
  /** The last loaded design pages; kept while a background refetch runs or fails. */
  data: DesignPages | null;
  /** The last load failed (with `data` set, the shown content is the previous one). */
  error: string | null;
  /** A load is in flight. */
  loading: boolean;
  reload: () => void;
}

/** The events after which the design pages may have changed (docs/stage-settings-ui.md, Design briefs). */
export function changesDesignPages(event: BuildEvent): boolean {
  switch (event.name) {
    case 'ready': // reconnect: events aren't replayed
    case 'prototype.updated':
    case 'brief.review':
      return true;
    case 'run.finished':
      return event.data.node === 'prototype' || event.data.node === 'revise';
    default:
      return false;
  }
}

/**
 * `GET design-pages` on load, on reconnect, `prototype.updated`, `brief.review` and the
 * `run.finished` of a prototype or revise run, over the workspace's one event stream. Only the
 * latest request lands; a background refetch keeps the last content.
 */
export function useDesignPages(buildId: string): DesignPagesState {
  const [state, setState] = useState<{ buildId: string; data: DesignPages | null; error: string | null; loading: boolean }>({
    buildId,
    data: null,
    error: null,
    loading: true,
  });
  const seq = useRef(0);

  const load = useCallback(() => {
    const mine = ++seq.current;
    setState((s) => (s.buildId === buildId ? { ...s, loading: true } : { buildId, data: null, error: null, loading: true }));
    api.getDesignPages(buildId).then(
      (data) => {
        if (mine === seq.current) setState({ buildId, data, error: null, loading: false });
      },
      (reason: unknown) => {
        if (mine !== seq.current) return;
        const error = reason instanceof ApiError ? reason.message : "Couldn't read the page designs. Try again.";
        setState((s) => ({ buildId, data: s.buildId === buildId ? s.data : null, error, loading: false }));
      },
    );
  }, [buildId]);

  useEffect(() => {
    load();
    const unsubscribe = subscribeWorkspace(buildId, (event) => {
      if (event !== 'open-references' && changesDesignPages(event)) load();
    });
    return () => {
      unsubscribe();
      // A response after unmount (or for the previous build) never lands.
      seq.current += 1;
    };
  }, [buildId, load]);

  const current = state.buildId === buildId;
  return { data: current ? state.data : null, error: current ? state.error : null, loading: current ? state.loading : true, reload: load };
}
