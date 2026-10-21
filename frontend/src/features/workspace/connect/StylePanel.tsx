import type { StretchRuns } from '../../activity/useBuildStream';
import { ReferencePanel } from '../ReferencePanel';

/** @deprecated References now share one panel across workspace stages. */
export function StylePanel({ buildId }: { buildId: string; stretchRuns?: StretchRuns }) {
  return <ReferencePanel buildId={buildId} />;
}
