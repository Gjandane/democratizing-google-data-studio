import { CircleCheck, CircleX, LogIn, RotateCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, type EngineStatus } from '../../../api/types';
import { Button } from '../../../components/Button';
import { ErrorState } from '../../../components/ErrorState';
import { Panel } from '../../../components/Panel';
import { LoadingState } from '../../../components/Spinner';

const POLL_MS = 2000;
const POLL_LIMIT_MS = 5 * 60 * 1000;

const messageOf = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; engine: EngineStatus };

/** Local builds can start once Google is signed in. (Agent mode has no engine panel: the job panel takes its place.) */
export const engineReady = (engine: EngineStatus): boolean => engine.signed_in;

function Fact({ ok, children }: { ok: boolean; children: string }) {
  const Icon = ok ? CircleCheck : CircleX;
  return (
    <li className="flex items-center gap-2 text-body text-text">
      <Icon aria-hidden="true" className={`size-4 shrink-0 ${ok ? 'text-success' : 'text-text-muted'}`} />
      {children}
    </li>
  );
}

interface EnginePanelProps {
  /** A change re-checks the status without the loading state. */
  refreshKey: number;
  /** The latest status, or null while unknown. */
  onEngine: (engine: EngineStatus | null) => void;
}

/**
 * Engine status. Local mode: Chrome and Google sign-in; "Sign in to Google" opens the sign-in
 * window, then the panel polls until the engine reports signed in. Agent mode (api.md 3.4) has
 * no engine panel: BuildStage shows the job panel instead.
 */
export function EnginePanel({ refreshKey, onEngine }: EnginePanelProps) {
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
    // Polls only after "Sign in to Google".
    if (engine.signed_in) setPolling(false);
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

  useEffect(() => {
    if (load.status === 'ready') report.current(load.engine);
  }, [load]);

  useEffect(() => {
    if (!polling) return;
    const started = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - started > POLL_LIMIT_MS) {
        clearInterval(timer);
        setPolling(false);
        return;
      }
      check(false);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [polling, check]);

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
    <Panel title="Data Studio engine" bodyClassName="px-4 py-3">
      {load.status === 'loading' ? (
        <LoadingState className="py-3">Checking the engine…</LoadingState>
      ) : load.status === 'error' ? (
        <ErrorState title="Couldn't check the engine" message={load.message} onRetry={() => check(true)} />
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
