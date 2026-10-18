// Reports `401 access_required` (contracts/api.md, Access) from any API call, so the gate in
// AccessGate.tsx can take over wherever the call was made (the cookie expired, the code changed).
import type { ApiClient } from '../../api/client';
import { ApiError } from '../../api/types';

export function isAccessRequired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401 && error.code === 'access_required';
}

const listeners = new Set<() => void>();

/** Calls `listener` for every `access_required` from now on; returns the unsubscribe function. */
export function onAccessRequired(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The same client; a rejected call that is `access_required` is reported, then rethrown unchanged. */
export function withAccessNotice(client: ApiClient): ApiClient {
  const wrapped: Record<string, unknown> = {};
  for (const [name, fn] of Object.entries(client) as Array<[string, (...args: unknown[]) => unknown]>) {
    wrapped[name] = (...args: unknown[]) => {
      const result = fn(...args);
      if (!(result instanceof Promise)) return result;
      return result.catch((error: unknown) => {
        if (isAccessRequired(error)) listeners.forEach((listener) => listener());
        throw error;
      });
    };
  }
  return wrapped as unknown as ApiClient;
}
