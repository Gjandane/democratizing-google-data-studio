// The brief review lock (docs/stage-settings-ui.md, Brief review): while a review waits, every
// mutating control in the workspace is off with one reason. WorkspaceShell owns the lock and
// provides it here; controls read it with useReviewLock. Settings and reads stay usable.
import { createContext, useContext } from 'react';
import type { ApiClient } from '../../../api/client';
import { ApiError } from '../../../api/types';

export const REVIEW_LOCK_REASON = 'Waiting for your brief review';

/** The reason while a review waits, else null (also outside a workspace). */
export const ReviewLockContext = createContext<string | null>(null);

export function useReviewLock(): string | null {
  return useContext(ReviewLockContext);
}

export function isReviewPending(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.code === 'brief_review_pending';
}

const listeners = new Set<() => void>();

/** Calls `listener` for every `409 brief_review_pending` from now on; returns the unsubscribe function. */
export function onReviewPending(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The same client; a rejected call that is `brief_review_pending` is reported, then rethrown unchanged. */
export function withReviewNotice(client: ApiClient): ApiClient {
  const wrapped: Record<string, unknown> = {};
  for (const [name, fn] of Object.entries(client) as Array<[string, (...args: unknown[]) => unknown]>) {
    wrapped[name] = (...args: unknown[]) => {
      const result = fn(...args);
      if (!(result instanceof Promise)) return result;
      return result.catch((error: unknown) => {
        if (isReviewPending(error)) listeners.forEach((listener) => listener());
        throw error;
      });
    };
  }
  return wrapped as unknown as ApiClient;
}
