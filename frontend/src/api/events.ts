// The build event stream: one EventSource per open build (GET /api/builds/{id}/events).
// Events are not replayed, so a consumer re-reads the build and its messages on every `ready`
// (the first connect and each reconnect). With VITE_MOCK=1 the stream comes from src/mocks/.
import { useEffect, useRef, useState } from 'react';
import { openMockBuildEvents } from '../mocks/events';
import { isMockMode } from './client';
import { BUILD_EVENT_NAMES, toBuildEvent, type BuildEvent } from './types';

export interface StreamHandlers {
  onEvent: (event: BuildEvent) => void;
  /** The connection dropped. `retrying` is false when the transport gave up for good. */
  onDrop?: (retrying: boolean) => void;
}

/** Opens the stream; the returned function closes it. */
export type OpenBuildEvents = (buildId: string, handlers: StreamHandlers) => () => void;

export const openHttpBuildEvents: OpenBuildEvents = (buildId, { onEvent, onDrop }) => {
  const source = new EventSource(`/api/builds/${encodeURIComponent(buildId)}/events`);
  for (const name of BUILD_EVENT_NAMES) {
    source.addEventListener(name, (message: MessageEvent<string>) => {
      let data: unknown;
      try {
        data = JSON.parse(message.data);
      } catch {
        data = undefined;
      }
      const problems: string[] = [];
      const event = toBuildEvent(name, data, problems);
      if (event) onEvent(event);
      else console.warn(`Ignored a "${name}" event that doesn't match the API contract:`, problems);
    });
  }
  // EventSource retries a dropped connection itself, but gives up on any non-200 answer
  // (the Vite proxy's 502 while the backend restarts).
  source.addEventListener('error', () => onDrop?.(source.readyState !== EventSource.CLOSED));
  return () => source.close();
};

export const openBuildEvents: OpenBuildEvents = isMockMode ? openMockBuildEvents : openHttpBuildEvents;

/** `connecting` until `ready` arrives, and again while the stream reconnects. */
export type StreamStatus = 'connecting' | 'open';

const RETRY_MIN_MS = 1000;
const RETRY_MAX_MS = 15000;

/**
 * Subscribes to the build's events while mounted (and while `buildId` is set). When the
 * transport gives up, it reopens with backoff, so a `ready` always follows a drop. `onEvent`
 * may change between renders without reopening the stream.
 */
export function useBuildEvents(
  buildId: string | undefined,
  onEvent: (event: BuildEvent) => void,
  open: OpenBuildEvents = openBuildEvents,
): StreamStatus {
  const handler = useRef(onEvent);
  const [status, setStatus] = useState<StreamStatus>('connecting');

  useEffect(() => {
    handler.current = onEvent;
  });

  useEffect(() => {
    if (!buildId) return undefined;
    let close = () => {};
    let retry: ReturnType<typeof setTimeout> | undefined;
    let delay = RETRY_MIN_MS;

    const connect = () => {
      setStatus('connecting');
      close = open(buildId, {
        onEvent: (event) => {
          if (event.name === 'ready') {
            delay = RETRY_MIN_MS;
            setStatus('open');
          }
          handler.current(event);
        },
        onDrop: (retrying) => {
          setStatus('connecting');
          if (retrying) return;
          close();
          retry = setTimeout(connect, delay);
          delay = Math.min(delay * 2, RETRY_MAX_MS);
        },
      });
    };

    connect();
    return () => {
      clearTimeout(retry);
      close();
    };
  }, [buildId, open]);

  return status;
}
