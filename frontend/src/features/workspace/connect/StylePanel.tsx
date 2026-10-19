import { CircleCheck, ImageUp } from 'lucide-react';
import { useRef, useState } from 'react';
import { api } from '../../../api/client';
import { Button } from '../../../components/Button';
import { Spinner } from '../../../components/Spinner';
import type { StretchRuns } from '../chat/useBuildStream';
import { useRefocusAfter, useStretchAction } from '../stretch';

/** Optional style screenshots: the planner reads them for colors and fonts. Hidden when the backend has no such route. */
export function StylePanel({ buildId, stretchRuns }: { buildId: string; stretchRuns: StretchRuns }) {
  const action = useStretchAction('style-images', 'style_extract', stretchRuns);
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const [count, setCount] = useState(0);
  const busy = action.state === 'starting' || action.state === 'running';
  useRefocusAfter(busy, button);
  if (action.hidden) return null;

  const choose = (files: File[]) => {
    if (files.length === 0 || busy) return;
    setCount(files.length);
    void action.start(() => api.uploadStyleImages(buildId, files));
  };

  return (
    <section aria-labelledby={`${buildId}-style`} className="flex flex-col gap-3 rounded-panel border border-border bg-surface p-4">
      <div>
        <h3 id={`${buildId}-style`} className="text-title font-semibold text-text">
          Style screenshots (optional)
        </h3>
        <p className="mt-0.5 text-body text-text-muted">Add screenshots of a dashboard you like. The planner copies its colors and layout feel.</p>
      </div>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg"
        multiple
        tabIndex={-1}
        aria-label="Style screenshots"
        className="sr-only"
        disabled={busy}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = '';
          choose(files);
        }}
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button ref={button} variant="secondary" icon={<ImageUp aria-hidden="true" />} disabled={busy} onClick={() => input.current?.click()}>
          Add style screenshots
        </Button>
        <div role="status" className="text-body text-text-muted">
          {action.state === 'starting' && (
            <span className="inline-flex items-center gap-2">
              <Spinner />
              Uploading {count} {count === 1 ? 'image' : 'images'}…
            </span>
          )}
          {action.state === 'running' && (
            <span className="inline-flex items-center gap-2">
              <Spinner />
              Reading the style…
            </span>
          )}
          {action.state === 'ok' && (
            <span className="inline-flex items-center gap-2 text-success">
              <CircleCheck aria-hidden="true" className="size-4 shrink-0" />
              Style saved. The planner uses it.
            </span>
          )}
        </div>
      </div>
      {action.state === 'error' && action.error && (
        <p role="alert" className="text-label text-danger">
          {action.error}
        </p>
      )}
    </section>
  );
}
