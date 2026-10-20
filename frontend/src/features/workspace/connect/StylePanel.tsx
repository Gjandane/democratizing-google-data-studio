import type { StretchRuns } from '../chat/useBuildStream';
import { ReferencePanel } from '../ReferencePanel';

/** @deprecated References now share one panel across workspace stages. */
export function StylePanel({ buildId }: { buildId: string; stretchRuns?: StretchRuns }) {
  return <ReferencePanel buildId={buildId} />;
}
