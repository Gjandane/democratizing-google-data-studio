import { Check, CircleCheck, CircleX, Copy, LogIn, RotateCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, type EngineStatus } from '../../../api/types';
import { Button } from '../../../components/Button';
import { ErrorState } from '../../../components/ErrorState';
import { Panel } from '../../../components/Panel';
import { LoadingState } from '../../../components/Spinner';

const POLL_MS = 2000;
/** Agent mode: how often the panel re-checks while the agent is offline or signed out. */
const AGENT_POLL_MS = 5000;
const POLL_LIMIT_MS = 5 * 60 * 1000;

const messageOf = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; engine: EngineStatus };

/** Builds can start: signed in, and in agent mode the agent is connected. */
export const engineReady = (engine: EngineStatus): boolean =>
  engine.signed_in && (engine.mode === 'local' || engine.agent_connected);

/** The command that starts the build agent against this app. It carries no code or token: the agent reads its token from .env. */
export const agentCommand = (origin: string) => `uv run --project backend dss-agent --server ${origin}`;

function Fact({ ok, children }: { ok: boolean; children: string }) {
  const Icon = ok ? CircleCheck : CircleX;
  return (
    <li className="flex items-center gap-2 text-body text-text">
      <Icon aria-hidden="true" className={`size-4 shrink-0 ${ok ? 'text-success' : 'text-text-muted'}`} />
      {children}
    </li>
  );
}

function CopyCommand({ command }: { command: string }) {
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

function AgentStatus({ engine, polling, onCheck }: { engine: EngineStatus; polling: boolean; onCheck: () => void }) {
  const checkAgain = (
    <Button icon={<RotateCw aria-hidden="true" />} onClick={onCheck}>
      Check again
    </Button>
  );
  if (!engine.agent_connected) {
    return (
      <div className="flex flex-col gap-3">
        <ul className="space-y-1.5">
          <Fact ok={false}>Build agent offline</Fact>
        </ul>
        <div className="flex flex-col gap-2">
          <p className="text-body text-text">
            Builds run on a build agent on the machine with your signed-in Chrome. Start it there, from the repo root:
          </p>
          <CopyCommand command={agentCommand(window.location.origin)} />
          <p className="text-label text-text-muted">
            The agent reads its token from the repo's .env.
            {engine.agent_last_seen && ` Last seen ${new Date(engine.agent_last_seen).toLocaleString()}.`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {checkAgain}
          {polling && <p className="text-label text-text-muted">Checking every few seconds.</p>}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <ul className="space-y-1.5">
        <Fact ok>Build agent connected</Fact>
        <Fact ok={engine.chrome_running}>{engine.chrome_running ? 'Chrome running' : 'Chrome not running'}</Fact>
        <Fact ok={engine.signed_in}>{engine.signed_in ? 'Signed in to Google' : 'Not signed in to Google'}</Fact>
      </ul>
      {!engine.signed_in && (
        <div className="flex min-w-0 flex-col items-start gap-2">
          <p className="text-body text-text">
            Run <code className="font-mono text-label">dsengine login</code> on the agent's machine.
          </p>
          {checkAgain}
        </div>
      )}
    </div>
  );
}

interface EnginePanelProps {
  /** A change re-checks the status without the loading state. */
  refreshKey: number;
  /** A change means `POST /run` answered `424 agent_offline`: show the agent as offline at once. */
  offlineSignal?: number;
  /** The latest status, or null while unknown. */
  onEngine: (engine: EngineStatus | null) => void;
}

/**
 * Engine status. Local mode: Chrome and Google sign-in; "Sign in to Google" opens the sign-in
 * window, then the panel polls until the engine reports signed in. Agent mode (hosted app): the
 * build agent's connection and sign-in, with the command that starts the agent.
 */
export function EnginePanel({ refreshKey, offlineSignal = 0, onEngine }: EnginePanelProps) {
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [polling, setPolling] = useState(false);
  const [starting, setStarting] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const mounted = useRef(true);
  const seq = useRef(0);
  const report = useRef(onEngine);
  useEffect(() => {
    report.current = onEngine;
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const show = useCallback((engine: EngineStatus) => {
    setLoad({ status: 'ready', engine });
    // Local mode polls only after "Sign in to Google"; agent mode polls until the agent is ready.
    if (engine.mode === 'agent') setPolling(!engineReady(engine));
    else if (engine.signed_in) setPolling(false);
  }, []);

  const check = useCallback(
    (showLoading: boolean) => {
      if (showLoading) setLoad({ status: 'loading' });
      const mine = ++seq.current;
      api.getEngineStatus().then(
        (engine) => {
          // A newer check started: its answer wins over this stale one.
          if (!mounted.current || mine !== seq.current) return;
          show(engine);
        },
        (error: unknown) => {
          if (!mounted.current || mine !== seq.current) return;
          // A failed poll keeps the last known status; only a failed load shows the error.
          setLoad((current) =>
            current.status === 'ready' ? current : { status: 'error', message: messageOf(error, "Couldn't reach the engine. Try again.") },
          );
        },
      );
    },
    [show],
  );

  useEffect(() => {
    check(refreshKey === 0);
  }, [check, refreshKey]);

  // The backend refused a build because the agent is gone: trust that over the last status.
  useEffect(() => {
    if (offlineSignal === 0) return;
    seq.current++;
    setLoad((current) =>
      current.status === 'ready' ? { status: 'ready', engine: { ...current.engine, mode: 'agent', agent_connected: false } } : current,
    );
    setPolling(true);
  }, [offlineSignal]);

  useEffect(() => {
    if (load.status === 'ready') report.current(load.engine);
  }, [load]);

  const agent = load.status === 'ready' && load.engine.mode === 'agent';
  useEffect(() => {
    if (!polling) return;
    const started = Date.now();
    const timer = setInterval(
      () => {
        if (Date.now() - started > POLL_LIMIT_MS) {
          clearInterval(timer);
          setPolling(false);
          return;
        }
        check(false);
      },
      agent ? AGENT_POLL_MS : POLL_MS,
    );
    return () => clearInterval(timer);
  }, [polling, agent, check]);

  const signIn = async () => {
    setStarting(true);
    setLoginError(null);
    try {
      await api.engineLogin();
      if (mounted.current) setPolling(true);
    } catch (error) {
      if (mounted.current) setLoginError(messageOf(error, "Couldn't open the sign-in window. Try again."));
    } finally {
      if (mounted.current) setStarting(false);
    }
  };

  return (
    <Panel title={agent ? 'Build agent' : 'Data Studio engine'} bodyClassName="px-4 py-3">
      {load.status === 'loading' ? (
        <LoadingState className="py-3">Checking the engine…</LoadingState>
      ) : load.status === 'error' ? (
        <ErrorState title="Couldn't check the engine" message={load.message} onRetry={() => check(true)} />
      ) : load.engine.mode === 'agent' ? (
        <AgentStatus engine={load.engine} polling={polling} onCheck={() => check(false)} />
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <ul className="space-y-1.5">
            <Fact ok={load.engine.chrome_running}>{load.engine.chrome_running ? 'Chrome running' : 'Chrome not running'}</Fact>
            <Fact ok={load.engine.signed_in}>{load.engine.signed_in ? 'Signed in to Google' : 'Not signed in to Google'}</Fact>
          </ul>
          {!load.engine.signed_in && (
            <div className="flex min-w-0 flex-col items-start gap-2">
              <div className="flex items-center gap-2">
                <Button variant="primary" icon={<LogIn aria-hidden="true" />} loading={starting} onClick={signIn}>
                  Sign in to Google
                </Button>
                {polling && (
                  <Button icon={<RotateCw aria-hidden="true" />} onClick={() => check(false)}>
                    Check again
                  </Button>
                )}
              </div>
              {polling && <p className="text-label text-text-muted">Finish signing in in the Chrome window that opened.</p>}
              {loginError && (
                <p role="alert" className="text-label text-danger">
                  {loginError}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
