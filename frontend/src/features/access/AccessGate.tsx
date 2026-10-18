import { KeyRound, LayoutDashboard } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { api } from '../../api/client';
import { ApiError } from '../../api/types';
import { Button } from '../../components/Button';
import { ErrorState } from '../../components/ErrorState';
import { Input } from '../../components/Input';
import { LoadingState } from '../../components/Spinner';
import { onAccessRequired } from './accessNotice';

type Gate =
  | { status: 'checking' }
  | { status: 'error'; message: string }
  /** `expired`: a call answered `401 access_required` after the app was open. */
  | { status: 'locked'; expired: boolean }
  | { status: 'open' };

const messageOf = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

/** The access-code form. The code lives only in this form's state and the one POST that sends it. */
function CodeForm({ expired, onOpened }: { expired: boolean; onOpened: () => void }) {
  const [code, setCode] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useLayoutEffect(() => {
    input.current?.focus();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const value = code.trim();
    if (!value || sending) return;
    setSending(true);
    setError(null);
    try {
      const session = await api.createSession(value);
      if (!mounted.current) return;
      setCode('');
      if (session.ok || !session.required) onOpened();
      else setError("That code didn't work. Check it with the person who shared the app, then try again.");
    } catch (e) {
      if (!mounted.current) return;
      setError(
        e instanceof ApiError && e.code === 'access_denied'
          ? "That code didn't work. Check it with the person who shared the app, then try again."
          : messageOf(e, "Couldn't check the code. Try again."),
      );
      input.current?.focus();
    } finally {
      if (mounted.current) setSending(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <Input
        ref={input}
        label="Access code"
        type="password"
        name="access-code"
        autoComplete="off"
        spellCheck={false}
        value={code}
        onChange={(e) => {
          setCode(e.target.value);
          setError(null);
        }}
        error={error}
        hint={expired ? 'Your session ended. Enter the code again to continue.' : 'Ask the person who shared this app for the code.'}
      />
      <Button type="submit" variant="primary" icon={<KeyRound aria-hidden="true" />} loading={sending} disabled={code.trim() === ''}>
        Continue
      </Button>
      <p role="status" className="sr-only">
        {error ?? ''}
      </p>
    </form>
  );
}

/**
 * Shows the app only once the backend says this browser may use it (contracts/api.md, Access):
 * `GET /api/session` first, the code form when it is `required && !ok`, and the form again on any
 * later `401 access_required`. While the form shows, nothing else calls `/api`.
 */
export function AccessGate({ children }: { children: ReactNode }) {
  const [gate, setGate] = useState<Gate>({ status: 'checking' });

  const check = useCallback(() => {
    setGate({ status: 'checking' });
    let active = true;
    api.getSession().then(
      (session) => {
        if (active) setGate(session.required && !session.ok ? { status: 'locked', expired: false } : { status: 'open' });
      },
      (error: unknown) => {
        if (active) setGate({ status: 'error', message: messageOf(error, "Couldn't reach the app. Try again.") });
      },
    );
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => check(), [check]);

  useEffect(() => onAccessRequired(() => setGate({ status: 'locked', expired: true })), []);

  if (gate.status === 'open') return <>{children}</>;

  return (
    <main className="flex min-h-dvh items-center justify-center bg-bg px-6 py-8">
      <div className="w-full max-w-sm">
        {gate.status === 'checking' && <LoadingState>Checking access…</LoadingState>}
        {gate.status === 'error' && <ErrorState title="Couldn't open the app" message={gate.message} onRetry={check} />}
        {gate.status === 'locked' && (
          <section aria-labelledby="access-title" className="rounded-panel border border-border bg-surface p-6">
            <div className="mb-5 flex items-center gap-3">
              <span aria-hidden="true" className="flex size-9 items-center justify-center rounded-control bg-primary-soft text-primary">
                <LayoutDashboard className="size-5" />
              </span>
              <div className="min-w-0">
                <h1 id="access-title" className="text-heading font-semibold text-text">
                  Enter the access code
                </h1>
                <p className="text-label text-text-muted">Data Studio builder</p>
              </div>
            </div>
            <CodeForm expired={gate.expired} onOpened={() => setGate({ status: 'open' })} />
          </section>
        )}
      </div>
    </main>
  );
}
