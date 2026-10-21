// The blueprint table and the Feasibility panel share one assessment: the table marks a slot under
// each blocked row, and the panel renders that row's issue into it (a portal), so its decision
// controls, state and focus rules stay the panel's own (docs/staged-ui.md, Blueprint).
import { createContext, useCallback, useMemo, useState, type ReactNode } from 'react';
import type { Issue } from '../../../api/types';

export interface IssueSlotHost {
  /** Slot elements under the blocked rows, by issue id. */
  slots: ReadonlyMap<string, HTMLElement>;
  register: (issueId: string, el: HTMLElement | null) => void;
  /** The issues of the panel's current assessment; null until it loads. */
  issues: ReadonlyMap<string, Issue> | null;
  setIssues: (issues: readonly Issue[] | null) => void;
  /** Bumped when an action answered `feasibility_blocked`: the panel refetches. */
  refresh: number;
  requestRefresh: () => void;
  /** Bumped after each saved decision: the server may have rewritten the blueprint rows, so it is read again. */
  decided: number;
  notifyDecided: () => void;
}

export const IssueSlotContext = createContext<IssueSlotHost | null>(null);

export function IssueSlotProvider({ children }: { children: ReactNode }) {
  const [slots, setSlots] = useState<ReadonlyMap<string, HTMLElement>>(new Map());
  const [issues, setIssueMap] = useState<ReadonlyMap<string, Issue> | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [decided, setDecided] = useState(0);
  const register = useCallback((issueId: string, el: HTMLElement | null) => {
    setSlots((current) => {
      if ((current.get(issueId) ?? null) === el) return current;
      const next = new Map(current);
      if (el) next.set(issueId, el);
      else next.delete(issueId);
      return next;
    });
  }, []);
  const setIssues = useCallback((list: readonly Issue[] | null) => setIssueMap(list ? new Map(list.map((issue) => [issue.id, issue])) : null), []);
  const requestRefresh = useCallback(() => setRefresh((n) => n + 1), []);
  const notifyDecided = useCallback(() => setDecided((n) => n + 1), []);
  const value = useMemo(
    () => ({ slots, register, issues, setIssues, refresh, requestRefresh, decided, notifyDecided }),
    [slots, register, issues, setIssues, refresh, requestRefresh, decided, notifyDecided],
  );
  return <IssueSlotContext.Provider value={value}>{children}</IssueSlotContext.Provider>;
}

/** A blocked row is settled once every issue it names is resolved in the current assessment. */
export function rowResolved(issueIds: readonly string[], issues: ReadonlyMap<string, Issue> | null): boolean {
  return issues !== null && issueIds.length > 0 && issueIds.every((id) => {
    const issue = issues.get(id);
    return issue !== undefined && issue.resolution !== 'unresolved';
  });
}
