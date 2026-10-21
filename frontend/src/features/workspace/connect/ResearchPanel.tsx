import { CircleCheck, Search } from 'lucide-react';
import { useRef, useState } from 'react';
import { api } from '../../../api/client';
import { Button } from '../../../components/Button';
import { TextArea } from '../../../components/Input';
import { Spinner } from '../../../components/Spinner';
import type { StretchRuns } from '../../activity/useBuildStream';
import { useRefocusAfter, useStretchAction } from '../stretch';

/** Research mode: a prompt for the research run, whose findings land in the sources table. */
export function ResearchPanel({ buildId, stretchRuns }: { buildId: string; stretchRuns: StretchRuns }) {
  const action = useStretchAction('research', 'research', stretchRuns);
  const [prompt, setPrompt] = useState('');
  const button = useRef<HTMLButtonElement>(null);
  const busy = action.state === 'starting' || action.state === 'running';
  useRefocusAfter(busy, button);
  if (action.hidden) return null;
  const text = prompt.trim();

  return (
    <form
      aria-label="Research"
      onSubmit={(e) => {
        e.preventDefault();
        if (text && !busy) void action.start(() => api.startResearch(buildId, text));
      }}
      className="flex flex-col gap-3 rounded-panel border border-border bg-surface p-4"
    >
      <TextArea
        label="What should the research cover?"
        hint="Name the topic, the market or the questions. The findings are added as a source."
        rows={3}
        value={prompt}
        readOnly={busy}
        onChange={(e) => setPrompt(e.target.value)}
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button ref={button} type="submit" variant="secondary" icon={<Search aria-hidden="true" />} disabled={text === '' || busy}>
          Start research
        </Button>
        <div role="status" className="text-body text-text-muted">
          {(action.state === 'starting' || action.state === 'running') && (
            <span className="inline-flex items-center gap-2">
              <Spinner />
              Researching…
            </span>
          )}
          {action.state === 'ok' && (
            <span className="inline-flex items-center gap-2 text-success">
              <CircleCheck aria-hidden="true" className="size-4 shrink-0" />
              Research done. New sources are in the table below.
            </span>
          )}
        </div>
      </div>
      {action.state === 'error' && action.error && (
        <p role="alert" className="text-label text-danger">
          {action.error}
        </p>
      )}
    </form>
  );
}
