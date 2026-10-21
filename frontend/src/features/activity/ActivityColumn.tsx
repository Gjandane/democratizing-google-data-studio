import { Activity as ActivityIcon } from 'lucide-react';
import { useCallback, useLayoutEffect, useRef } from 'react';
import type { Build, Message } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { LoadingState, Spinner } from '../../components/Spinner';
import { ActivityStrip } from './ActivityStrip';
import { RunCard } from './RunCard';
import { cardCandidate } from './activity';
import { Markdown } from './Markdown';
import type { BuildStream } from './useBuildStream';

/** Within this many pixels of the end counts as "reading the newest". */
const NEAR_BOTTOM = 96;

const bubble = 'min-w-0 max-w-[85%] rounded-panel px-3 py-2 text-body text-text [overflow-wrap:anywhere]';

function MessageBubble({ message }: { message: Message }) {
  if (message.role === 'user') {
    return (
      <div data-bubble="user" className={`${bubble} self-end whitespace-pre-wrap bg-primary-soft`}>
        <span className="sr-only">You: </span>
        {message.text}
      </div>
    );
  }
  return (
    <div data-bubble={message.role} className={`${bubble} self-start bg-surface-muted`}>
      <span className="sr-only">{message.role === 'system' ? 'System: ' : 'Assistant: '}</span>
      <Markdown>{message.text}</Markdown>
    </div>
  );
}

/**
 * The activity column: the assistant's notes (markdown, streamed drafts), run cards in time order
 * and the activity strip at its foot. There is no input: every action lives in the stage area.
 */
export function ActivityColumn({ build, stream }: { build: Build; stream: BuildStream }) {
  const { messages, drafts, loadError, status, activity } = stream;
  const list = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const onScroll = () => {
    const el = list.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM;
  };

  useLayoutEffect(() => {
    const el = list.current;
    if (!el) return;
    if (stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, drafts, activity]);

  const onCardShow = useCallback(() => {
    const el = list.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, []);

  const empty = messages !== null && messages.length === 0 && drafts.length === 0;
  const fresh = build.stage === 'connect';

  let body;
  if (messages === null) {
    body = loadError ? (
      <ErrorState title="Couldn't load the activity" message={loadError} onRetry={stream.reload} />
    ) : (
      <LoadingState>Loading messages…</LoadingState>
    );
  } else if (empty) {
    body = (
      <EmptyState
        icon={<ActivityIcon />}
        title="No activity yet"
        description={
          fresh
            ? 'Runs and assistant notes show up here once you draft the context.'
            : build.stage === 'done'
              ? 'No notes were kept for this build.'
              : 'Runs and assistant notes show up here.'
        }
        className="my-auto"
      />
    );
  } else {
    // The card sits in time order: after the messages known when its run started, so later ones
    // render below it, and its place never moves while the run is live.
    const at = Math.min(cardCandidate(activity)?.after ?? messages.length, messages.length);
    body = (
      <>
        {messages.slice(0, at).map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        <RunCard activity={activity} onShow={onCardShow} />
        {messages.slice(at).map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {drafts.map((d) => (
          // Hidden from screen readers while streaming: the finished bubble is announced once.
          <div key={d.id} aria-hidden="true" data-bubble="assistant" data-draft="true" className={`${bubble} self-start bg-surface-muted`}>
            <span className="sr-only">Assistant: </span>
            <Markdown>{d.text}</Markdown>
            <p className="mt-1 flex items-center gap-1 text-caption text-text-muted">
              <Spinner size="sm" />
              Writing…
            </p>
          </div>
        ))}
      </>
    );
  }

  return (
    <aside aria-label="Activity" className="flex h-full min-h-0 flex-col border-r border-border bg-surface">
      {messages !== null && loadError && (
        <ErrorState title="Couldn't refresh the activity" message={loadError} onRetry={stream.reload} className="m-3" />
      )}
      <div
        ref={list}
        role="log"
        aria-live="polite"
        aria-label="Activity log"
        onScroll={onScroll}
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3"
      >
        {body}
        {empty && <RunCard activity={activity} onShow={onCardShow} />}
      </div>
      {messages !== null && status === 'connecting' && (
        <p role="status" className="px-3 pb-2 text-caption text-text-muted">
          Reconnecting…
        </p>
      )}
      <ActivityStrip activity={activity} />
    </aside>
  );
}
