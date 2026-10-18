// Reports the two 503s that mean "go to Settings" (contracts/api.md) from any API call, so the
// app-level banner can offer a way out wherever the call was made.
import type { ApiClient } from '../../api/client';
import { ApiError } from '../../api/types';

export const SERVICE_ERROR_CODES = ['llm_unavailable', 'gcp_not_configured'] as const;

export type ServiceError = ApiError & { code: (typeof SERVICE_ERROR_CODES)[number] };

export function isServiceError(error: unknown): error is ServiceError {
  return (
    error instanceof ApiError &&
    error.status === 503 &&
    (SERVICE_ERROR_CODES as readonly string[]).includes(error.code)
  );
}

const listeners = new Set<(error: ServiceError) => void>();

/** Calls `listener` for every service error from now on; returns the unsubscribe function. */
export function onServiceError(listener: (error: ServiceError) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Passes `error` on if it is a service error. */
export function reportServiceError(error: unknown): void {
  if (isServiceError(error)) listeners.forEach((listener) => listener(error));
}

/** The same client; a rejected call that is a service error is reported, then rethrown unchanged. */
export function withServiceNotice(client: ApiClient): ApiClient {
  const wrapped: Record<string, unknown> = {};
  for (const [name, fn] of Object.entries(client) as Array<[string, (...args: unknown[]) => unknown]>) {
    wrapped[name] = (...args: unknown[]) => {
      const result = fn(...args);
      if (!(result instanceof Promise)) return result;
      return result.catch((error: unknown) => {
        reportServiceError(error);
        throw error;
      });
    };
  }
  return wrapped as unknown as ApiClient;
}
