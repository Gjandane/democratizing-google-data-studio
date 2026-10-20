import { CircleAlert, MessagesSquare, Send } from 'lucide-react';
import { useCallback, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { Build, Message } from '../../../api/types';
import { ActivityStrip } from '../../activity/ActivityStrip';
import { RunCard } from '../../activity/RunCard';
import { cardCandidate } from '../../activity/activity';
import { Button } from '../../../components/Button';
import { EmptyState } from '../../../components/EmptyState';
import { ErrorState } from '../../../components/ErrorState';
import { TextArea } from '../../../components/Input';
import { LoadingState, Spinner } from '../../../components/Spinner';
import { Markdown } from './Markdown';
import { openReferencePanel } from '../stretch';
import { RUN_ERROR_FALLBACK, type BuildStream } from './useBuildStream';

/** Within this many pixels of the end counts as "reading the newest". */
const NEAR_BOTTOM = 96;

/** `.`, `!` or `?`, then at most one closing quote or bracket, ends a sentence. */
const SENTENCE_END = /[.!?]["'”’»)\]]?$/;

/** The interview error as a sentence, then what to do next. */
const withNextStep = (error: string) => {
  const text = error.trim();
  return `${text}${SENTENCE_END.test(text) ? '' : '.'} Send your answer again.`;
};

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

function Composer({ build, stream, onSent }: { build: Build; stream: BuildStream; onSent: () => void }) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false);
  const noInterview = build.stage === 'connect';
  // Until the history loads, a send would show the user's bubble alone as the whole chat.
  const locked = noInterview || stream.messages === null;
  const empty = text.trim() === '';

  const submit = async () => {
    if (locked || sendingRef.current || empty) return;
    sendingRef.current = true;
    setSending(true);
    onSent();
    const ok = await stream.send(text);
    sendingRef.current = false;
    setSending(false);
    if (ok) setText('');
    input.current?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void submit();
  };

  return (
    <form
      className="flex flex-col gap-2 border-t border-border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <TextArea
        ref={input}
        label="Message"
        hideLabel
        rows={2}
        placeholder="Type your answer…"
        value={text}
        disabled={locked}
        hint={noInterview ? 'Add a source and start the interview first.' : undefined}
        error={stream.sendError}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        className="[&_textarea]:resize-none"
      />
      {/* The visible error sits under the field; this announces it, since focus stays in the field. */}
      {stream.sendError && (
        <p role="alert" className="sr-only">
          {stream.sendError}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <Button
          type="button"
          variant="secondary"
          disabled={!['connect', 'interview', 'prototype'].includes(build.stage)}
          onClick={() => openReferencePanel(build.id)}
        >
          Attach reference
        </Button>
        <Button type="submit" variant="primary" icon={<Send aria-hidden="true" />} disabled={locked || empty} loading={sending}>
          Send
        </Button>
      </div>
    </form>
  );
}

/** The chat column: message list (markdown, streamed drafts) and the composer. */
export function ChatPanel({ build, chat }: { build: Build; chat: BuildStream }) {
  const { messages, drafts, loadError, status, activity } = chat;
  const list = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const forceScroll = useRef(false);

  const onScroll = () => {
    const el = list.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM;
  };

  useLayoutEffect(() => {
    const el = list.current;
    if (!el) return;
    if (stick.current || forceScroll.current) {
      el.scrollTop = el.scrollHeight;
      stick.current = true;
    }
    forceScroll.current = false;
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
      <ErrorState title="Couldn't load the chat" message={loadError} onRetry={chat.reload} />
    ) : (
      <LoadingState>Loading messages…</LoadingState>
    );
  } else if (empty) {
    body = (
      <EmptyState
        icon={<MessagesSquare />}
        title="No messages yet"
        description={
          fresh
            ? 'The interview starts here once you add a source.'
            : build.stage === 'done'
              ? 'No messages were kept for this build.'
              : "The assistant's first question shows up here."
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
    <aside aria-label="Chat" className="flex h-full min-h-0 flex-col border-r border-border bg-surface">
      {messages !== null && loadError && (
        <ErrorState title="Couldn't refresh the chat" message={loadError} onRetry={chat.reload} className="m-3" />
      )}
      <div
        ref={list}
        role="log"
        aria-live="polite"
        aria-label="Messages"
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
      {chat.runErrors.interview && (
        <p role="alert" className="flex items-start gap-1.5 px-3 pb-2 text-label text-danger">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          <span className="min-w-0 [overflow-wrap:anywhere]">
            {/* The server's text may not say what to do next: the fallback already does. */}
            {chat.runErrors.interview === RUN_ERROR_FALLBACK.interview ? chat.runErrors.interview : withNextStep(chat.runErrors.interview)}
          </span>
        </p>
      )}
      <ActivityStrip activity={activity} />
      <Composer
        build={build}
        stream={chat}
        onSent={() => {
          forceScroll.current = true;
        }}
      />
    </aside>
  );
}
