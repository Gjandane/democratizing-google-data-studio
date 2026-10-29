import { Check, Copy } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '../../../components/Button';

/** A command in a code box with a Copy button; the code box scrolls, never wraps. */
export function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState<'yes' | 'failed' | null>(null);
  useEffect(() => {
    if (copied !== 'yes') return;
    const timer = setTimeout(() => setCopied(null), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  const copy = () => {
    const clipboard = typeof navigator === 'undefined' ? undefined : navigator.clipboard;
    if (!clipboard) {
      setCopied('failed');
      return;
    }
    clipboard.writeText(command).then(
      () => setCopied('yes'),
      () => setCopied('failed'),
    );
  };
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-stretch gap-2">
        <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-control border border-border bg-surface-muted px-2.5 py-1.5 font-mono text-label text-text">
          {command}
        </code>
        <Button icon={copied === 'yes' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />} onClick={copy}>
          {copied === 'yes' ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <p role="status" className={copied === 'failed' ? 'text-label text-danger' : 'sr-only'}>
        {copied === 'yes' ? 'Command copied.' : copied === 'failed' ? "Couldn't copy. Select the command and copy it." : ''}
      </p>
    </div>
  );
}
