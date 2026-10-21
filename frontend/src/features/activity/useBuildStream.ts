import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { useBuildEvents, type OpenBuildEvents, type StreamStatus } from '../../api/events';
import { ApiError, ARTIFACTS, type ArtifactName, type Build, type BuildEvent, type Message } from '../../api/types';
import { reduceActivity, type Activity } from './activity';
import { publishWorkspace } from '../workspace/stretch';
import { idleRun, reduceBuildRun, type BuildRun } from '../workspace/build/buildRun';

export interface Draft {
  id: string;
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

/** The staged runs whose failure their stage area shows (api.md 2.0 `node` values). */
export type RunErrorNode = 'context' | 'outline_propose' | 'outline_other' | 'outline_suggest' | 'blueprint' | 'prototype';
export type RunErrors = Partial<Record<RunErrorNode, string>>;
/** Shown when `run.finished` errors with `error: null`. */
export const RUN_ERROR_FALLBACK: Readonly<Record<RunErrorNode, string>> = {
  context: "The context draft didn't finish. Draft it again.",
  outline_propose: "The questions weren't proposed. Try again.",
  outline_other: "Your question wasn't added. Send it again.",
  outline_suggest: "No questions were suggested. Try again.",
  blueprint: "The blueprint didn't finish. Regenerate it.",
  prototype: "The prototype wasn't rendered. Accept the blueprint again.",
};
/** Per artifact, a counter bumped by each `artifact.updated` and by every (re)connect: a stage area refetches when its own changes. */
export type ArtifactSeq = Readonly<Record<ArtifactName, number>>;
const NO_ARTIFACT_CHANGES: ArtifactSeq = { context: 0, outline: 0, design: 0, blueprint: 0 };
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
  /** The node of the newest run still going (the build's action lock is held), or null. */
  running: string | null;
  artifactSeq: ArtifactSeq;
  /** A `revise` run (applying comments) has started and not finished. */
  applying: boolean;
  /** Set when a `revise` run ends in error; `seq` changes on every failure, even an identical one. */
  commentsError: { seq: number; text: string } | null;
  /** The error of the latest failed staged run per node; cleared when that node runs again. */
  runErrors: RunErrors;
  /** The engine run of the build stage, folded from build.* and run.* events. */
  buildRun: BuildRun;
  status: StreamStatus;
  reload: () => void;
}

const NO_RUNS: Activity = [];

const errorText = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

/**
 * The one event stream of the open build, with its activity log: messages, streamed drafts and runs.
 * On every `ready` (first connect and each reconnect) it re-reads the build and the messages.
 */
export function useBuildStream(build: Build, onBuildChange: (build: Build) => void, open?: OpenBuildEvents): BuildStream {
  const [messages, setMessageState] = useState<Message[] | null>(null);
  const [runErrors, setRunErrors] = useState<RunErrors>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [artifactSeq, setArtifactSeq] = useState<ArtifactSeq>(NO_ARTIFACT_CHANGES);
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
        setLoadError(errorText(error, "Couldn't load the activity. Try again."));
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
        // A write missed while disconnected: every stage area refetches its artifact.
        setArtifactSeq((seq) => Object.fromEntries(ARTIFACTS.map((name) => [name, seq[name] + 1])) as Record<ArtifactName, number>);
        load();
        break;
      case 'artifact.updated': {
        const { artifact } = event.data;
        setArtifactSeq((seq) => ({ ...seq, [artifact]: seq[artifact] + 1 }));
        break;
      }
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
        if (isStretchNode(event.data.node)) {
          const { node, run_id } = event.data;
          setStretchRuns((runs) => ({ ...runs, [node]: { run_id, status: 'running', error: null } }));
        }
        if (isRunErrorNode(event.data.node)) {
          const { node } = event.data;
          setRunErrors((errors) => {
            if (!(node in errors)) return errors;
            const rest = { ...errors };
            delete rest[node];
            return rest;
          });
        }
        if (event.data.node === 'revise') {
          setApplying(true);
          setCommentsError(null);
        }
        break;
      case 'run.finished':
        if (isStretchNode(event.data.node)) {
          const { node, run_id, status, error } = event.data;
          setStretchRuns((runs) => ({ ...runs, [node]: { run_id, status: status === 'ok' ? 'ok' : 'error', error } }));
        }
        if (isRunErrorNode(event.data.node) && event.data.status === 'error') {
          const { node, error } = event.data;
          setRunErrors((errors) => ({ ...errors, [node]: error ?? RUN_ERROR_FALLBACK[node] }));
        }
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

  const running = [...activity].reverse().find((run) => run.status === 'running')?.node ?? null;

  return { activity, messages, loadError, drafts, running, artifactSeq, applying, commentsError, runErrors, buildRun, stretchRuns, status, reload: load };
}
