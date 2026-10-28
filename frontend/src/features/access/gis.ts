// Google Identity Services loader. Used by the access gate only: the script is never added elsewhere.

export const GIS_SRC = 'https://accounts.google.com/gsi/client';

let loading: Promise<GoogleAccountsId> | null = null;
let credentialHandler: ((credential: string) => void) | null = null;
const initialized = new WeakMap<object, string>();

const present = () => window.google?.accounts?.id;

/** Resolves with `google.accounts.id`, adding the GIS script once; a failed load can be retried. */
export function loadGis(): Promise<GoogleAccountsId> {
  const ready = present();
  if (ready) return Promise.resolve(ready);
  if (loading && document.querySelector(`script[src="${GIS_SRC}"]`)) return loading;
  const pending = new Promise<GoogleAccountsId>((resolve, reject) => {
    let script = document.querySelector<HTMLScriptElement>(`script[src="${GIS_SRC}"]`);
    if (!script) {
      script = document.createElement('script');
      script.src = GIS_SRC;
      script.async = true;
      document.head.appendChild(script);
    }
    const tag = script;
    tag.addEventListener('load', () => {
      const id = present();
      if (id) {
        if (loading === pending) loading = null;
        resolve(id);
      } else fail();
    });
    tag.addEventListener('error', fail);
    function fail() {
      tag.remove();
      if (loading === pending) loading = null;
      reject(new Error('Google sign-in could not load'));
    }
  });
  loading = pending;
  return pending;
}

/** Routes GIS credentials to the mounted gate; returns the cleanup. */
export function setCredentialHandler(handler: (credential: string) => void): () => void {
  credentialHandler = handler;
  return () => {
    if (credentialHandler === handler) credentialHandler = null;
  };
}

/** Initializes GIS once per client id; the callback always reaches the current handler. */
export function initGis(id: GoogleAccountsId, clientId: string): void {
  if (initialized.get(id) === clientId) return;
  initialized.set(id, clientId);
  id.initialize({
    client_id: clientId,
    callback: (response) => credentialHandler?.(response.credential),
    auto_select: false,
    cancel_on_tap_outside: false,
  });
}
