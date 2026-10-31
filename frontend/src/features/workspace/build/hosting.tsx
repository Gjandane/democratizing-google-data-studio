import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from '../../../api/client';
import type { Hosting } from '../../../api/types';

/** `GET /api/hosting` as it stands: still pending, loaded, or failed (the app then acts as local mode). */
export type HostingLoad = { status: 'pending' } | { status: 'ready'; hosting: Hosting } | { status: 'failed' };

const PENDING: HostingLoad = { status: 'pending' };

/** undefined: no provider above. */
const HostingContext = createContext<HostingLoad | undefined>(undefined);

function useLoadedHosting(enabled: boolean): HostingLoad {
  const [load, setLoad] = useState<HostingLoad>(PENDING);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    api.getHosting().then(
      (hosting) => {
        if (live) setLoad({ status: 'ready', hosting });
      },
      () => {
        // A failed load keeps the local-mode behavior; the engine status still tells the mode.
        if (live) setLoad({ status: 'failed' });
      },
    );
    return () => {
      live = false;
    };
  }, [enabled]);
  return load;
}

/** Loads `GET /api/hosting` once per app load (api.md 3.4). */
export function HostingProvider({ children }: { children: ReactNode }) {
  const load = useLoadedHosting(true);
  return <HostingContext.Provider value={load}>{children}</HostingContext.Provider>;
}

/** The hosting load with pending and failed told apart. Without a provider it loads itself. */
export function useHostingLoad(): HostingLoad {
  const shared = useContext(HostingContext);
  const own = useLoadedHosting(shared === undefined);
  return shared === undefined ? own : shared;
}

/** How the app is hosted, or null while loading or after a failed load. Without a provider it loads itself. */
export function useHosting(): Hosting | null {
  const load = useHostingLoad();
  return load.status === 'ready' ? load.hosting : null;
}
