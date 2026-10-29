import { Globe } from 'lucide-react';
import { useId, useRef, useState, type KeyboardEvent } from 'react';
import { focusRing } from '../../../components/focus';
import { CopyCommand } from './CopyCommand';
import type { SetupCommands } from './setupCommand';

const TABS = ['windows', 'unix'] as const;
type Tab = (typeof TABS)[number];
const LABELS: Record<Tab, string> = { windows: 'Windows (PowerShell)', unix: 'macOS/Linux' };

/** The browser the agent drives (conventions 1.7). */
export function ChromeLine() {
  return (
    <p className="flex items-center gap-2 text-body text-text">
      <Globe aria-hidden="true" className="size-4 shrink-0 text-text-muted" />
      Needs Google Chrome
    </p>
  );
}

/** The Windows and macOS/Linux setup commands as two tabs, each with a Copy button. */
export function SetupCommandTabs({ commands }: { commands: SetupCommands }) {
  const [tab, setTab] = useState<Tab>('windows');
  const tabs = useRef<Record<Tab, HTMLButtonElement | null>>({ windows: null, unix: null });
  const id = useId();

  const onTabKey = (event: KeyboardEvent, current: Tab) => {
    const at = TABS.indexOf(current);
    const next =
      event.key === 'ArrowRight' ? TABS[(at + 1) % TABS.length]
      : event.key === 'ArrowLeft' ? TABS[(at + TABS.length - 1) % TABS.length]
      : event.key === 'Home' ? TABS[0]
      : event.key === 'End' ? TABS[TABS.length - 1]
      : null;
    if (!next) return;
    event.preventDefault();
    setTab(next);
    tabs.current[next]?.focus();
  };

  return (
    <div className="flex flex-col gap-2">
      <div role="tablist" aria-label="Operating system" className="flex gap-1 border-b border-border">
        {TABS.map((key) => {
          const selected = tab === key;
          return (
            <button
              key={key}
              ref={(el) => {
                tabs.current[key] = el;
              }}
              type="button"
              role="tab"
              id={`${id}-tab-${key}`}
              aria-selected={selected}
              aria-controls={`${id}-panel-${key}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setTab(key)}
              onKeyDown={(event) => onTabKey(event, key)}
              className={`-mb-px flex h-9 items-center gap-2 rounded-t-control border-b-2 px-3 text-body ${focusRing} ${
                selected ? 'border-primary font-semibold text-primary' : 'border-transparent text-text-muted hover:bg-surface-muted hover:text-text'
              }`}
            >
              {LABELS[key]}
              {key === 'unix' && <span className="rounded-control bg-surface-muted px-1.5 text-caption font-medium text-text-muted">untested</span>}
            </button>
          );
        })}
      </div>
      {TABS.map((key) => (
        <div key={key} role="tabpanel" id={`${id}-panel-${key}`} aria-labelledby={`${id}-tab-${key}`} hidden={tab !== key}>
          <CopyCommand command={key === 'windows' ? commands.powershell : commands.bash} />
        </div>
      ))}
    </div>
  );
}
