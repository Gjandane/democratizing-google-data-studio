// Fake event stream: the mock API emits events per build; each open stream starts with `ready`,
// like the real one.
import type { OpenBuildEvents } from '../api/events';
import type { BuildEvent } from '../api/types';

type Listener = (event: BuildEvent) => void;

const listeners = new Map<string, Set<Listener>>();

/** Delivers `event` to every open stream of `buildId`. */
export function emit(buildId: string, event: BuildEvent): void {
  for (const listener of [...(listeners.get(buildId) ?? [])]) listener(event);
}

export const openMockBuildEvents: OpenBuildEvents = (buildId, { onEvent }) => {
  const set = listeners.get(buildId) ?? new Set<Listener>();
  listeners.set(buildId, set);
  set.add(onEvent);
  const ready = setTimeout(() => onEvent({ name: 'ready', data: { build_id: buildId } }), 0);
  return () => {
    clearTimeout(ready);
    set.delete(onEvent);
  };
};

export function closeAllMockStreams(): void {
  listeners.clear();
}
