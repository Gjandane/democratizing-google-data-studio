import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from '../../../api/client';
import type { Hosting } from '../../../api/types';

/** undefined: no provider above; null: loading or the load failed. */
const HostingContext = createContext<Hosting | null | undefined>(undefined);

function useLoadedHosting(enabled: boolean): Hosting | null {
  const [hosting, setHosting] = useState<Hosting | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    api.getHosting().then(
      (loaded) => {
        if (live) setHosting(loaded);
      },
      () => {
        // A failed load keeps the local-mode behavior; the engine status still tells the mode.
      },
    );
    return () => {
      live = false;
    };
  }, [enabled]);
  return hosting;
}

/** Loads `GET /api/hosting` once per app load (api.md 3.4). */
export function HostingProvider({ children }: { children: ReactNode }) {
  const hosting = useLoadedHosting(true);
  return <HostingContext.Provider value={hosting}>{children}</HostingContext.Provider>;
}

/** How the app is hosted, or null while loading or after a failed load. Without a provider it loads itself. */
export function useHosting(): Hosting | null {
  const shared = useContext(HostingContext);
  const own = useLoadedHosting(shared === undefined);
  return shared === undefined ? own : shared;
}
