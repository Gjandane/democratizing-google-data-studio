import { Panel } from '../../../components/Panel';

/** The screencast of the engine run: the latest `build.frame` JPEG. Renders only once a frame has arrived. */
export function LiveViewPanel({ frame, running }: { frame: string | null; running: boolean }) {
  if (!frame) return null;
  return (
    <Panel title="Live view" bodyClassName="flex flex-col gap-2 p-4">
      <img
        src={`data:image/jpeg;base64,${frame}`}
        alt="Live view of the build in Data Studio"
        className="h-auto max-w-full self-start rounded-control border border-border"
      />
      {running && <p className="text-caption text-text-muted">Updates while the engine runs.</p>}
    </Panel>
  );
}
