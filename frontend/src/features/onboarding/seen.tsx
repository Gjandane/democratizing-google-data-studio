import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

/** The one thing onboarding keeps in localStorage: `1` once the landing page was left by one of its buttons. */
export const ONBOARDING_SEEN_KEY = 'dss.onboardingSeen';

function readSeen(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDING_SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

function writeSeen(): void {
  try {
    window.localStorage.setItem(ONBOARDING_SEEN_KEY, '1');
  } catch {
    // Storage blocked: the in-memory flag stops the redirect until the next load.
  }
}

interface OnboardingSeen {
  seen: boolean;
  markSeen: () => void;
}

const SeenContext = createContext<OnboardingSeen | null>(null);

/** Holds the seen flag for this app load, read once from storage (docs/onboarding-ui.md#When it shows). */
export function OnboardingSeenProvider({ children }: { children: ReactNode }) {
  const [seen, setSeen] = useState(readSeen);
  const markSeen = useCallback(() => {
    writeSeen();
    setSeen(true);
  }, []);
  const value = useMemo(() => ({ seen, markSeen }), [seen, markSeen]);
  return <SeenContext.Provider value={value}>{children}</SeenContext.Provider>;
}

export function useOnboardingSeen(): OnboardingSeen {
  const value = useContext(SeenContext);
  if (!value) throw new Error('useOnboardingSeen needs an OnboardingSeenProvider above it.');
  return value;
}
