import { createContext, useContext } from 'react';

/** The signed-in Google email (api.md 3.3 `Session.user`), or null. Provided by the access gate. */
export const SessionUserContext = createContext<string | null>(null);

export const useSessionUser = (): string | null => useContext(SessionUserContext);
