import { KeyRound, LayoutDashboard } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { api } from '../../api/client';
import { ApiError, type Session } from '../../api/types';
import { Button } from '../../components/Button';
import { ErrorState } from '../../components/ErrorState';
import { Input } from '../../components/Input';
import { LoadingState } from '../../components/Spinner';
import { onAccessRequired } from './accessNotice';
import { initGis, loadGis, setCredentialHandler } from './gis';
import { SessionUserContext } from './sessionUser';

type Gate =
  | { status: 'checking' }
  | { status: 'error'; message: string }
  /** `expired`: a call answered `401 access_required` after the app was open. */
  | { status: 'locked'; expired: boolean; googleClientId: string | null }
  | { status: 'open'; user: string | null; googleClientId: string | null };

const messageOf = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

/** The access-code form. The code lives only in this form's state and the one POST that sends it. */
function CodeForm({ expired, onOpened }: { expired: boolean; onOpened: (session: Session) => void }) {
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
      if (session.ok || !session.required) onOpened(session);
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

type GoogleLoad = 'loading' | 'ready' | 'failed';

/**
 * Google sign-in (api.md 3.3): the Google button and nothing else. The ID token goes from the GIS
 * callback straight into one POST; it is held in no state, ref, storage or log.
 */
function GoogleSignIn({ clientId, expired, onOpened }: { clientId: string; expired: boolean; onOpened: (session: Session) => void }) {
  const [load, setLoad] = useState<GoogleLoad>('loading');
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const busy = useRef(false);
  const mounted = useRef(true);
  const onOpenedRef = useRef(onOpened);
  onOpenedRef.current = onOpened;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoad('loading');
    loadGis().then(
      (id) => {
        if (!active) return;
        initGis(id, clientId);
        setLoad('ready');
      },
      () => {
        if (active) setLoad('failed');
      },
    );
    return () => {
      active = false;
    };
  }, [clientId, attempt]);

  useEffect(
    () =>
      setCredentialHandler((credential) => {
        if (busy.current) return;
        busy.current = true;
        setError(null);
        api.createGoogleSession(credential).then(
          (session) => {
            if (mounted.current) onOpenedRef.current(session);
          },
          (e: unknown) => {
            busy.current = false;
            if (!mounted.current) return;
            if (e instanceof ApiError && e.code === 'signin_not_allowed') {
              const email = typeof e.detail.email === 'string' ? e.detail.email : null;
              setError(`${email ?? 'This Google account'} isn't allowed here. Sign in with another Google account.`);
            } else if (e instanceof ApiError && e.code === 'access_denied') setError('Sign-in failed. Try again.');
            else setError(messageOf(e, "Couldn't sign in. Try again."));
          },
        );
      }),
    [],
  );

  useLayoutEffect(() => {
    const id = window.google?.accounts?.id;
    if (load !== 'ready' || !id || !container.current) return;
    container.current.replaceChildren();
    id.renderButton(container.current, { type: 'standard', theme: 'outline', size: 'large', text: 'signin_with', shape: 'rectangular', logo_alignment: 'left', width: 320 });
  }, [load]);

  if (load === 'failed') {
    return (
      <ErrorState
        title="Google sign-in couldn't load"
        message="Google sign-in couldn't load. Check your connection and retry."
        retryLabel="Retry"
        onRetry={() => setAttempt((n) => n + 1)}
      />
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {load === 'loading' && <LoadingState className="px-0 py-2">Loading Google sign-in…</LoadingState>}
      <div ref={container} className="flex min-h-10 justify-start" />
      <p className="text-label text-text-muted">{expired ? 'Your session ended. Sign in again to continue.' : 'Sign in with your Google account to use the app.'}</p>
      <p role="alert" className={error ? 'text-label text-danger' : 'sr-only'}>
        {error ?? ''}
      </p>
    </div>
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
        if (active) setGate(session.required && !session.ok ? { status: 'locked', expired: false, googleClientId: session.google_client_id } : { status: 'open', user: session.user, googleClientId: session.google_client_id });
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

  // A later 401 keeps the Google client id so the gate can show the same sign-in again.
  useEffect(() => onAccessRequired(() => setGate((g) => ({ status: 'locked', expired: true, googleClientId: 'googleClientId' in g ? g.googleClientId : null }))), []);

  if (gate.status === 'open') return <SessionUserContext.Provider value={gate.user}>{children}</SessionUserContext.Provider>;

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
                  {gate.googleClientId ? 'Sign in to continue' : 'Enter the access code'}
                </h1>
                <p className="text-label text-text-muted">Data Studio builder</p>
              </div>
            </div>
            {gate.googleClientId ? (
              <GoogleSignIn clientId={gate.googleClientId} expired={gate.expired} onOpened={(session) => setGate({ status: 'open', user: session.user, googleClientId: session.google_client_id })} />
            ) : (
              <CodeForm expired={gate.expired} onOpened={(session) => setGate({ status: 'open', user: session.user, googleClientId: session.google_client_id })} />
            )}
          </section>
        )}
      </div>
    </main>
  );
}
