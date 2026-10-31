import { CircleCheck, CircleX, Clock } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../../../api/client';
import { ApiError, type AgentCheck, type AgentCheckResult } from '../../../api/types';
import { Button } from '../../../components/Button';
import { focusableIn } from '../../../components/focus';
import { Panel } from '../../../components/Panel';
import { Spinner } from '../../../components/Spinner';
import { clock, secondsLeft } from './JobPanel';
import { setupCommands } from './setupCommand';
import { ChromeLine, SetupCommandTabs } from './setupTabs';

/** How often a waiting check is re-read. */
export const AGENT_CHECK_POLL_MS = 3000;
/** sessionStorage key of the passed check: a boolean only, never the code. */
export const AGENT_READY_KEY = 'dss.agentReady';

/** A check passed earlier in this tab. */
export function readReady(): boolean {
  try {
    return window.sessionStorage.getItem(AGENT_READY_KEY) === '1';
  } catch {
    return false;
  }
}

function rememberReady(ready: boolean): void {
  try {
    if (ready) window.sessionStorage.setItem(AGENT_READY_KEY, '1');
    else window.sessionStorage.removeItem(AGENT_READY_KEY);
  } catch {
    // Storage is a convenience: the step just won't fold after a reload.
  }
}

interface Item {
  label: string;
  ok: boolean;
  /** What to do when it failed. */
  fix: string;
}

/** The four items of the check script (conventions 1.7); the server was reached when a result exists. */
function itemsOf(result: AgentCheckResult): Item[] {
  return [
    { label: 'Server reached', ok: true, fix: '' },
    { label: 'Versions match', ok: result.api_version_ok, fix: 'Rerun the setup command with -Update (--update on macOS/Linux).' },
    { label: 'Chrome running', ok: result.chrome_running, fix: 'Start Google Chrome with the agent, then check again.' },
    { label: 'Signed in to Google', ok: result.signed_in, fix: "Sign in to Google in the agent's Chrome window, then check again." },
  ];
}

function ItemList({ items }: { items: Item[] }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((item) => {
        const Icon = item.ok ? CircleCheck : CircleX;
        return (
          <li key={item.label} className="flex items-start gap-2 text-body">
            <Icon aria-hidden="true" className={`mt-0.5 size-4 shrink-0 ${item.ok ? 'text-success' : 'text-danger'}`} />
            <span className="min-w-0">
              <span className={item.ok ? 'text-text' : 'font-medium text-text'}>{item.label}</span>
              <span className="sr-only">{item.ok ? ': ok' : ': failed'}</span>
              {!item.ok && <span className="block text-text-muted">{item.fix}</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

const TITLE = 'Set up this computer';
const HINT = <p className="text-label text-text-muted">Already set up? Build in Data Studio.</p>;

/** The how-to steps between the Chrome line and the command tabs (docs/onboarding-ui.md#Setup modal). */
export const SETUP_STEPS = [
  'Pick your system and copy the command.',
  'Paste it into PowerShell (Windows: Start menu, type PowerShell) or Terminal (macOS/Linux) and press Enter.',
  "If a Chrome window opens, sign in to Google and accept Data Studio's terms if it asks.",
  'Keep this page open. It shows Agent ready when the check passes.',
];

export type SetupOutcome = 'passed' | 'failed' | 'expired';

interface SetupPanelProps {
  /** Open on the check-code flow and ask for a code even when a check passed in this tab. */
  startUnfolded?: boolean;
  /** Told each time the check ends. */
  onState?: (state: SetupOutcome) => void;
  /** The line under the step; `null` for none. */
  hint?: ReactNode;
  /** No Panel and no title of its own: the container (a Modal) gives both. */
  bare?: boolean;
}

/**
 * Agent mode (api.md 3.4 Checks): the setup step before the first Build. Asks for a check code,
 * shows the setup commands with it and reads the check every 3 s while it waits. A passed check
 * is remembered for the tab as a boolean (never the code); the step then folds to one line.
 * Build is never gated by it. The landing's setup modal holds it too, `bare` and `startUnfolded`.
 */
export function SetupPanel({ startUnfolded = false, onState, hint = HINT, bare = false }: SetupPanelProps = {}) {
  const [folded, setFolded] = useState(() => !startUnfolded && readReady());
  const [check, setCheck] = useState<AgentCheck | null>(null);
  /** The check is gone on the server (404). */
  const [gone, setGone] = useState(false);
  const [createFailed, setCreateFailed] = useState(false);
  /** Counts finished reads, so the poll chain re-arms after a failed one too. */
  const [round, setRound] = useState(0);
  const [, setTick] = useState(0);
  const seq = useRef(0);
  const mounted = useRef(true);
  const content = useRef<HTMLDivElement>(null);
  /** A button of ours asked for a new code (or the modal just opened): focus follows to the next state, never to body. */
  const refocus = useRef(startUnfolded);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const create = useCallback(() => {
    const mine = ++seq.current;
    setCheck(null);
    setGone(false);
    setCreateFailed(false);
    api.createAgentCheck().then(
      (next) => {
        if (mounted.current && mine === seq.current) setCheck(next);
      },
      () => {
        if (mounted.current && mine === seq.current) setCreateFailed(true);
      },
    );
  }, []);

  const read = useCallback((checkId: string) => {
    const mine = ++seq.current;
    api.getAgentCheck(checkId).then(
      (next) => {
        if (!mounted.current || mine !== seq.current) return;
        setCheck(next);
        setRound((n) => n + 1);
      },
      (error: unknown) => {
        if (!mounted.current || mine !== seq.current) return;
        // Only a 404 says the check is gone; any other failure keeps the last one and retries.
        if (error instanceof ApiError && error.status === 404) setGone(true);
        else setRound((n) => n + 1);
      },
    );
  }, []);

  const again = useCallback(() => {
    refocus.current = true;
    create();
  }, [create]);

  // Once on mount, and again when the folded line unfolds.
  useEffect(() => {
    if (!folded) create();
  }, [folded, create]);

  const remaining = check ? secondsLeft(check.expires_at) : 0;
  /** The countdown ran out before the server said so: reading it again can't help. */
  const timedOut = check?.state === 'waiting' && remaining <= 0;
  const waiting = check?.state === 'waiting' && !gone && !timedOut;
  const checkId = check?.check_id;

  // The one poller: a timeout chain that exists only while the check waits.
  useEffect(() => {
    if (!waiting || !checkId) return;
    const timer = setTimeout(() => read(checkId), AGENT_CHECK_POLL_MS);
    return () => clearTimeout(timer);
  }, [waiting, checkId, round, read]);

  // The countdown, one tick a second while waiting.
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [waiting]);

  const passed = check?.state === 'passed' && !gone;
  // A later failed check unsets it, so a reload doesn't claim a ready agent.
  const failed = check?.state === 'failed' && !gone;
  useEffect(() => {
    if (passed || failed) rememberReady(passed);
  }, [passed, failed]);

  const expired = gone || check?.state === 'expired' || timedOut;
  const outcome: SetupOutcome | null = !check && !gone ? null : expired ? 'expired' : passed ? 'passed' : failed ? 'failed' : null;
  const report = useRef(onState);
  report.current = onState;
  useEffect(() => {
    if (outcome) report.current?.(outcome);
  }, [outcome]);

  // The pressed button is gone: hold focus on the step while the code loads, then its first control.
  useLayoutEffect(() => {
    const node = content.current;
    if (!refocus.current || !node) return;
    const settled = check !== null || createFailed;
    if (settled) refocus.current = false;
    (settled ? focusableIn(node)[0] ?? node : node).focus();
  });

  if (folded) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="flex items-center gap-2 text-body text-text">
          <CircleCheck aria-hidden="true" className="size-4 shrink-0 text-success" />
          Agent ready on this computer
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            refocus.current = true;
            setFolded(false);
          }}
        >
          Check again
        </Button>
      </div>
    );
  }

  let body;
  if (createFailed) {
    body = (
      <>
        <p role="alert" className="text-body text-danger">Couldn't get a check code. Try again.</p>
        <div><Button onClick={again}>Try again</Button></div>
      </>
    );
  } else if (!check) {
    body = (
      <p role="status" className="flex items-center gap-2 text-body text-text-muted">
        <Spinner className="text-primary" />
        Getting a check code…
      </p>
    );
  } else if (expired) {
    body = (
      <>
        <p role="status" className="text-body text-text-muted">That check code expired.</p>
        <div><Button variant="primary" onClick={again}>Get a new code</Button></div>
      </>
    );
  } else if (check.state === 'passed') {
    body = (
      <>
        <p role="status" className="flex items-center gap-2 text-body font-semibold text-text">
          <CircleCheck aria-hidden="true" className="size-5 shrink-0 text-success" />
          Agent ready on this computer
        </p>
        {check.result && <ItemList items={itemsOf(check.result)} />}
      </>
    );
  } else if (check.state === 'failed') {
    body = (
      <>
        <p role="status" className="text-body font-semibold text-text">The check found a problem.</p>
        {check.result ? (
          <ItemList items={itemsOf(check.result)} />
        ) : (
          <p className="text-body text-text-muted">The agent reported nothing usable. Rerun the setup command, then check again.</p>
        )}
        <div><Button variant="primary" onClick={again}>Check again</Button></div>
      </>
    );
  } else {
    const commands = setupCommands(window.location.origin, 'check', check.code);
    body = (
      <>
        <ChromeLine />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <p className="text-body text-text-muted">
            Check code{' '}
            <code translate="no" className="rounded-control bg-surface-muted px-1.5 py-0.5 font-mono text-body font-semibold text-text">{check.code}</code>
          </p>
          <p className="flex items-center gap-1.5 text-label text-text-muted">
            <Clock aria-hidden="true" className="size-4 shrink-0" />
            <span className="tabular-nums">Code expires in {clock(remaining)}</span>
          </p>
        </div>
        <ol aria-label="Steps" className="flex list-decimal flex-col gap-1 pl-5 text-body text-text marker:font-semibold marker:text-primary">
          {SETUP_STEPS.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <SetupCommandTabs commands={commands} />
        <p role="status" className="flex items-center gap-2 text-body text-text-muted">
          <Spinner className="text-primary" />
          Waiting for the check…
        </p>
      </>
    );
  }

  const inner = (
    <div ref={content} tabIndex={-1} className="flex flex-col gap-3 outline-none">
      {body}
      {hint}
    </div>
  );
  if (bare) return inner;
  return (
    <Panel title={TITLE} bodyClassName="px-4 py-3">
      {inner}
    </Panel>
  );
}
