import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { useBuildEvents, type OpenBuildEvents, type StreamStatus } from '../../../api/events';
import { ApiError, type Build, type BuildEvent, type Message } from '../../../api/types';
import { reduceActivity, type Activity } from '../../activity/activity';
import { publishWorkspace } from '../stretch';
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
export type StretchNode = 'style_extract' | 'research' | 'ux_audit';
export interface NodeRun {
  run_id: string;
  status: 'running' | 'ok' | 'error';
  error: string | null;
}
export type StretchRuns = Partial<Record<StretchNode, NodeRun>>;

const STRETCH_NODES: readonly string[] = ['style_extract', 'research', 'ux_audit'];
const isStretchNode = (node: string): node is StretchNode => STRETCH_NODES.includes(node);

/** The chat-side runs whose failure the user sees: plan and spec on the Interview stage, interview in the chat. */
export type RunErrorNode = 'plan' | 'interview' | 'spec';
export type RunErrors = Partial<Record<RunErrorNode, string>>;
/** Shown when `run.finished` errors with `error: null`. */
export const RUN_ERROR_FALLBACK: Readonly<Record<RunErrorNode, string>> = {
  plan: 'The plan didn\'t finish. Try "Generate plan" again.',
  spec: 'The spec didn\'t finish. Try "Generate plan" again.',
  interview: "The assistant didn't reply. Send your answer again.",
};
const isRunErrorNode = (node: string): node is RunErrorNode => node in RUN_ERROR_FALLBACK;

export interface BuildStream {
  /** Runs of this build seen on the stream since it opened (client-only; events aren't replayed). */
  activity: Activity;
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
  /** A `revise` run (applying comments) has started and not finished. */
  applying: boolean;
  /** Set when a `revise` run ends in error; `seq` changes on every failure, even an identical one. */
  commentsError: { seq: number; text: string } | null;
  /** The error of the latest failed plan, spec or interview run; cleared when that node runs again. */
  runErrors: RunErrors;
  /** The engine run of the build stage, folded from build.* and run.* events. */
  buildRun: BuildRun;
  status: StreamStatus;
  reload: () => void;
  /** Resolves true when the server accepted the message; the optimistic bubble shows at once. */
  send: (text: string) => Promise<boolean>;
  sendError: string | null;
}

const LOCAL = 'local-';
const NO_RUNS: Activity = [];

const errorText = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

/**
 * The one event stream of the open build, with its chat: messages, streamed drafts and sending.
 * On every `ready` (first connect and each reconnect) it re-reads the build and the messages.
 */
export function useBuildStream(build: Build, onBuildChange: (build: Build) => void, open?: OpenBuildEvents): BuildStream {
  const [messages, setMessageState] = useState<Message[] | null>(null);
  const [runErrors, setRunErrors] = useState<RunErrors>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [sendError, setSendError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressLine[]>([]);
  const [planning, setPlanning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [commentsError, setCommentsError] = useState<{ seq: number; text: string } | null>(null);
  const [buildRun, setBuildRun] = useState<BuildRun>(idleRun);
  const [stretchRuns, setStretchRuns] = useState<StretchRuns>({});
  const [activityOf, setActivityOf] = useState<{ buildId: string; runs: Activity }>({ buildId: build.id, runs: [] });

  const latest = useRef(build);
  const change = useRef(onBuildChange);
  const fetchSeq = useRef(0);
  /** Bumped on every build event, so a refetch never undoes an event that arrived meanwhile. */
  const buildSeq = useRef(0);
  const localSeq = useRef(0);
  const progressSeq = useRef(0);
  const errorSeq = useRef(0);
  const mounted = useRef(true);
  /** The list as of the last update, read synchronously when a run starts (state may not have rendered yet). */
  const messagesNow = useRef<Message[] | null>(null);
  const setMessages = (change: (current: Message[] | null) => Message[]) => {
    const next = change(messagesNow.current);
    messagesNow.current = next;
    setMessageState(next);
  };
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
        const loaded = messagesNow.current?.length ?? 0;
        setActivityOf((a) =>
          a.buildId === buildId && a.runs.some((r) => r.after === null)
            ? { buildId, runs: a.runs.map((r) => (r.after === null ? { ...r, after: loaded } : r)) }
            : a,
        );
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
    publishWorkspace(buildId, event);
    setBuildRun((r) => reduceBuildRun(r, event));
    const now = Date.now();
    // null until the first load lands: the run's card then sits after the whole loaded history.
    const known = messagesNow.current?.length ?? null;
    setActivityOf((a) => ({ buildId, runs: reduceActivity(a.buildId === buildId ? a.runs : [], event, now, known) }));
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
        if (isRunErrorNode(event.data.node)) {
          const { node } = event.data;
          // "Generate plan" retries the spec too and moves on from the interview, so it clears those errors as well.
          const cleared: RunErrorNode[] = node === 'plan' ? ['plan', 'spec', 'interview'] : [node];
          setRunErrors((errors) => {
            if (!cleared.some((n) => n in errors)) return errors;
            const rest = { ...errors };
            for (const n of cleared) delete rest[n];
            return rest;
          });
        }
        if (event.data.node === 'plan') setPlanning(true);
        if (event.data.node === 'revise') {
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
        if (isRunErrorNode(event.data.node) && event.data.status === 'error') {
          const { node, error } = event.data;
          setRunErrors((errors) => ({ ...errors, [node]: error ?? RUN_ERROR_FALLBACK[node] }));
        }
        if (event.data.node === 'plan') setPlanning(false);
        if (event.data.node === 'revise') {
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
  // Another build's runs never show here.
  const activity = activityOf.buildId === buildId ? activityOf.runs : NO_RUNS;

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

  return { activity, messages, loadError, drafts, progress, planning, applying, commentsError, runErrors, buildRun, stretchRuns, status, reload: load, send, sendError };
}
