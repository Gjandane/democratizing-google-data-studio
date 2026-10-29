import { Clock, Info } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../api/client';
import { ApiError, type JobTicket, type Stage } from '../../../api/types';
import { Panel } from '../../../components/Panel';
import { setupCommands } from './setupCommand';
import { ChromeLine, SetupCommandTabs } from './setupTabs';

/** How often a waiting ticket is re-read. */
export const JOB_POLL_MS = 3000;

export interface JobStatus {
  /** The ticket waits for the visitor's computer. */
  waiting: boolean;
  /** The build is in its build stage but its ticket is gone (a 404 on restore). */
  lost: boolean;
}

interface JobPanelProps {
  buildId: string;
  stage: Stage;
  /** Bumped when a start resolves: the ticket is read again, whatever the old one said. */
  jobKey: number;
  /** A start is in flight: the old ticket's message makes way for the new one. */
  starting: boolean;
  /** Hosting.share_data: the build's data goes to a CSV anyone with its private link can read. */
  shareData: boolean;
  /** The run ended with `job_expired` (the stream says so before the next poll does). */
  runExpired: boolean;
  onStatus: (status: JobStatus) => void;
}

export const secondsLeft = (expiresAt: string): number => Math.max(0, Math.ceil((Date.parse(expiresAt) - Date.now()) / 1000));
export const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

/**
 * Agent mode (api.md 3.4): the one-shot job of the build's latest run. Waiting shows the setup
 * command with the code and a countdown; running shows that the computer claimed it. Owns the one
 * ticket poller (3 s while waiting). The code lives in React state only.
 */
export function JobPanel({ buildId, stage, jobKey, starting, shareData, runExpired, onStatus }: JobPanelProps) {
  const [ticket, setTicket] = useState<JobTicket | null>(null);
  const [lost, setLost] = useState(false);
  /** Counts finished reads, so the poll chain re-arms after a failed one too. */
  const [round, setRound] = useState(0);
  /** Ticks the countdown. */
  const [, setTick] = useState(0);
  const seq = useRef(0);
  const mounted = useRef(true);
  const stageRef = useRef(stage);
  stageRef.current = stage;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(() => {
    const mine = ++seq.current;
    api.getJob(buildId).then(
      (next) => {
        if (!mounted.current || mine !== seq.current) return;
        setTicket(next);
        setLost(false);
        setRound((n) => n + 1);
      },
      (error: unknown) => {
        if (!mounted.current || mine !== seq.current) return;
        // Only a 404 says the ticket is gone; any other failure keeps the last ticket.
        if (error instanceof ApiError && error.status === 404 && error.code === 'job_not_found') {
          setTicket(null);
          setLost(true);
        }
        setRound((n) => n + 1);
      },
    );
  }, [buildId]);

  // Opened in the build stage (a reload, another tab) or a start resolved: read the ticket.
  useEffect(() => {
    if (jobKey === 0 && stageRef.current !== 'build') return;
    if (jobKey > 0) {
      setTicket(null);
      setLost(false);
    }
    load();
  }, [buildId, jobKey, load]);

  // Another tab started the build: no start of ours will bump the key.
  const inBuild = stage === 'build';
  const wasInBuild = useRef(inBuild);
  useEffect(() => {
    if (inBuild && !wasInBuild.current && ticket === null && !lost) load();
    wasInBuild.current = inBuild;
  }, [inBuild, ticket, lost, load]);

  const waiting = ticket?.state === 'waiting' && !runExpired;

  // The one poller: a timeout chain that exists only while the ticket waits.
  useEffect(() => {
    if (!waiting) return;
    const timer = setTimeout(load, JOB_POLL_MS);
    return () => clearTimeout(timer);
  }, [waiting, round, load]);

  // The countdown, one tick a second while waiting.
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [waiting]);

  const remaining = ticket ? secondsLeft(ticket.expires_at) : 0;
  const expired = !starting && (ticket?.state === 'expired' || runExpired || (waiting && remaining <= 0));
  const showWaiting = waiting && remaining > 0 && !starting;
  const showRunning = ticket?.state === 'running' && stage === 'build' && !starting;
  const showLost = lost && !starting;

  const report = useRef(onStatus);
  report.current = onStatus;
  useEffect(() => {
    report.current({ waiting: showWaiting, lost: showLost });
  }, [showWaiting, showLost]);

  if (showLost) {
    return (
      <p role="status" className="text-body text-text-muted">
        The last build code was lost. Build again for a new code.
      </p>
    );
  }
  if (expired) {
    return (
      <p role="status" className="text-body text-text-muted">
        That code expired. Build again for a new code.
      </p>
    );
  }
  if (showRunning) {
    return (
      <p role="status" className="text-body text-text-muted">
        Your computer claimed the build code. Building in Data Studio…
      </p>
    );
  }
  if (!showWaiting || !ticket) return null;

  const commands = setupCommands(window.location.origin, 'job', ticket.code);
  return (
    <Panel title="Build on your computer" bodyClassName="flex flex-col gap-3 px-4 py-3">
      <ChromeLine />
      <p className="text-body text-text">Run this in a terminal on the computer signed in to Data Studio.</p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <p className="text-body text-text-muted">
          Build code{' '}
          <code translate="no" className="rounded-control bg-surface-muted px-1.5 py-0.5 font-mono text-body font-semibold text-text">{ticket.code}</code>
        </p>
        <p className="flex items-center gap-1.5 text-label text-text-muted">
          <Clock aria-hidden="true" className="size-4 shrink-0" />
          <span className="tabular-nums">Code expires in {clock(remaining)}</span>
        </p>
      </div>
      <SetupCommandTabs commands={commands} />
      {shareData && (
        <p className="flex items-start gap-2 text-label text-text-muted">
          <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          Your data is saved as a CSV that anyone with its private link can read, so your Data Studio account can open it.
        </p>
      )}
    </Panel>
  );
}
