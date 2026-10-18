import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { useBuildEvents, type OpenBuildEvents, type StreamStatus } from '../../../api/events';
import { ApiError, type Build, type BuildEvent, type Message } from '../../../api/types';
import { idleRun, reduceBuildRun, type BuildRun } from '../build/buildRun';

export interface Draft {
  id: string;
  text: string;
}

/** One `node.progress` status line of the current run, e.g. "Writing questions.md". */
export interface ProgressLine {
  key: number;
  node: string;
  text: string;
}

/** The stretch actions that run on the stream: style images, research, UX audit. */
export type StretchNode = 'style' | 'research' | 'audit';
export interface NodeRun {
  run_id: string;
  status: 'running' | 'ok' | 'error';
  error: string | null;
}
export type StretchRuns = Partial<Record<StretchNode, NodeRun>>;

const STRETCH_NODES: readonly string[] = ['style', 'research', 'audit'];
const isStretchNode = (node: string): node is StretchNode => STRETCH_NODES.includes(node);

export interface BuildStream {
  /** Latest run of each stretch node; a 'running' entry is dropped on reconnect (events aren't replayed). */
  stretchRuns: StretchRuns;
  /** null while the first load runs. */
  messages: Message[] | null;
  loadError: string | null;
  /** Assistant messages still being streamed, in arrival order. */
  drafts: Draft[];
  /** Status lines of the latest run, in arrival order; a new run starts the list over. */
  progress: ProgressLine[];
  /** A `plan` run has started and not finished. */
  planning: boolean;
  /** A `comments` run has started and not finished. */
  applying: boolean;
  /** Set when a `comments` run ends in error; `seq` changes on every failure, even an identical one. */
  commentsError: { seq: number; text: string } | null;
  /** The engine run of the build stage, folded from build.* and run.* events. */
  buildRun: BuildRun;
  status: StreamStatus;
  reload: () => void;
  /** Resolves true when the server accepted the message; the optimistic bubble shows at once. */
  send: (text: string) => Promise<boolean>;
  sendError: string | null;
}

const LOCAL = 'local-';

const errorText = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

/**
 * The one event stream of the open build, with its chat: messages, streamed drafts and sending.
 * On every `ready` (first connect and each reconnect) it re-reads the build and the messages.
 */
export function useBuildStream(build: Build, onBuildChange: (build: Build) => void, open?: OpenBuildEvents): BuildStream {
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [sendError, setSendError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressLine[]>([]);
  const [planning, setPlanning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [commentsError, setCommentsError] = useState<{ seq: number; text: string } | null>(null);
  const [buildRun, setBuildRun] = useState<BuildRun>(idleRun);
  const [stretchRuns, setStretchRuns] = useState<StretchRuns>({});

  const latest = useRef(build);
  const change = useRef(onBuildChange);
  const fetchSeq = useRef(0);
  /** Bumped on every build event, so a refetch never undoes an event that arrived meanwhile. */
  const buildSeq = useRef(0);
  const localSeq = useRef(0);
  const progressSeq = useRef(0);
  const errorSeq = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    latest.current = build;
    change.current = onBuildChange;
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const buildId = build.id;
  const load = useCallback(() => {
    const seq = ++fetchSeq.current;
    const buildAt = buildSeq.current;
    setLoadError(null);
    Promise.all([api.getBuild(buildId), api.listMessages(buildId)]).then(
      ([fresh, list]) => {
        if (!mounted.current || seq !== fetchSeq.current) return;
        if (buildAt === buildSeq.current) setBuild(fresh);
        // The server's list, plus what the stream or a send added after its snapshot.
        setMessages((current) => {
          const ids = new Set(list.map((m) => m.id));
          return [...list, ...(current ?? []).filter((m) => !ids.has(m.id))];
        });
        const ids = new Set(list.map((m) => m.id));
        setDrafts((current) => current.filter((d) => !ids.has(d.id)));
      },
      (error: unknown) => {
        if (!mounted.current || seq !== fetchSeq.current) return;
        setLoadError(errorText(error, "Couldn't load the chat. Try again."));
      },
    );
  }, [buildId]);

  // Keep `latest` current between events that arrive before React re-renders.
  const setBuild = (next: Build) => {
    latest.current = next;
    change.current(next);
  };

  const onEvent = (event: BuildEvent) => {
    setBuildRun((r) => reduceBuildRun(r, event));
    switch (event.name) {
      case 'ready':
        // Events aren't replayed: a run.finished missed while disconnected must not lock the stage.
        setApplying(false);
        setStretchRuns((runs) => {
          const kept = Object.entries(runs).filter(([, run]) => run.status !== 'running');
          return kept.length === Object.keys(runs).length ? runs : (Object.fromEntries(kept) as StretchRuns);
        });
        load();
        break;
      case 'message.delta': {
        const { message_id, text } = event.data;
        setDrafts((current) =>
          current.some((d) => d.id === message_id)
            ? current.map((d) => (d.id === message_id ? { ...d, text: d.text + text } : d))
            : [...current, { id: message_id, text }],
        );
        break;
      }
      case 'message.done': {
        const { message } = event.data;
        setMessages((current) => {
          const list = current ?? [];
          return list.some((m) => m.id === message.id)
            ? list.map((m) => (m.id === message.id ? message : m))
            : [...list, message];
        });
        setDrafts((current) => current.filter((d) => d.id !== message.id));
        break;
      }
      case 'build.updated':
        buildSeq.current += 1;
        setBuild(event.data.build);
        break;
      case 'stage.changed':
        buildSeq.current += 1;
        setBuild({ ...latest.current, stage: event.data.stage });
        break;
      case 'docs.updated':
        buildSeq.current += 1;
        setBuild({ ...latest.current, docs: event.data.docs });
        break;
      case 'prototype.updated':
        buildSeq.current += 1;
        setBuild({ ...latest.current, spec_version: event.data.spec_version });
        break;
      case 'run.started':
        setProgress([]);
        if (isStretchNode(event.data.node)) {
          const { node, run_id } = event.data;
          setStretchRuns((runs) => ({ ...runs, [node]: { run_id, status: 'running', error: null } }));
        }
        if (event.data.node === 'plan') setPlanning(true);
        if (event.data.node === 'comments') {
          setApplying(true);
          setCommentsError(null);
        }
        break;
      case 'node.progress': {
        const { node, text } = event.data;
        setProgress((current) => [...current, { key: ++progressSeq.current, node, text }]);
        break;
      }
      case 'run.finished':
        if (isStretchNode(event.data.node)) {
          const { node, run_id, status, error } = event.data;
          setStretchRuns((runs) => ({ ...runs, [node]: { run_id, status: status === 'ok' ? 'ok' : 'error', error } }));
        }
        if (event.data.node === 'plan') setPlanning(false);
        if (event.data.node === 'comments') {
          setApplying(false);
          if (event.data.status === 'error') {
            setCommentsError({ seq: ++errorSeq.current, text: event.data.error ?? "Couldn't apply the comments. Try again." });
          }
        }
        // A failed run never sends message.done for its draft.
        if (event.data.status !== 'ok') setDrafts([]);
        break;
      default:
        break;
    }
  };

  const status = useBuildEvents(buildId, onEvent, open);

  const send = async (raw: string): Promise<boolean> => {
    const text = raw.trim();
    if (!text) return false;
    const tempId = `${LOCAL}${++localSeq.current}`;
    const bubble: Message = { id: tempId, role: 'user', text, node: null, created_at: new Date().toISOString() };
    setSendError(null);
    setMessages((current) => [...(current ?? []), bubble]);
    try {
      const { message_id } = await api.sendMessage(buildId, text);
      if (!mounted.current) return true;
      setMessages((current) => {
        const list = current ?? [];
        // A refetch may already have brought the server's copy: keep one bubble.
        return list.some((m) => m.id === message_id)
          ? list.filter((m) => m.id !== tempId)
          : list.map((m) => (m.id === tempId ? { ...m, id: message_id } : m));
      });
      return true;
    } catch (error) {
      if (mounted.current) {
        setMessages((current) => (current ?? []).filter((m) => m.id !== tempId));
        setSendError(errorText(error, "Couldn't send your message. Try again."));
      }
      return false;
    }
  };

  return { messages, loadError, drafts, progress, planning, applying, commentsError, buildRun, stretchRuns, status, reload: load, send, sendError };
}
