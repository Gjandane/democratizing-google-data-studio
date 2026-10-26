import { formatUsd } from '../settings/stageSettings';

export const count = new Intl.NumberFormat('en-US');

/** 2300 -> "2.3 s", 119600 -> "2 min 0 s"; under a second stays in ms. Rounds before choosing the unit, so never "60.0 s". */
export function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  const tenths = Math.round(ms / 100);
  if (tenths < 600) return `${(tenths / 10).toFixed(1)} s`;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

/** A token count, or "unknown" when the provider gave none (never 0). */
export const tokens = (n: number | null) => (n === null ? 'unknown' : count.format(n));

/** An estimate in USD (api.md 3.0, Cost estimates): "unknown" when null, "at least $X" when not complete. */
export function estimateText(usd: number | null, complete: boolean): string {
  if (usd === null) return 'unknown';
  return complete ? formatUsd(usd) : `at least ${formatUsd(usd)}`;
}
