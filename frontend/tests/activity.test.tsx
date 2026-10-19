import { act, cleanup, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import type { Build, BuildEvent } from '../src/api/types';
import { formatTokens } from '../src/features/activity/activity';
import { ChatPanel } from '../src/features/workspace/chat/ChatPanel';
import { useBuildStream } from '../src/features/workspace/chat/useBuildStream';
import { openMockBuildEvents } from '../src/mocks/events';
import { fixtures } from '../src/mocks/fixtures';
import { resetMockState } from '../src/mocks/api';

beforeEach(() => {
  resetMockState();
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
});

/** A mock API call: its latency and run steps are fake timers too. */
async function call<T>(promise: Promise<T>): Promise<T> {
  await vi.runAllTimersAsync();
  return promise;
}
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

function fakeStream() {
  const handlers: StreamHandlers[] = [];
  const open: OpenBuildEvents = (_id, h) => {
    handlers.push(h);
    return () => {};
  };
  const fire = (event: BuildEvent) => act(() => handlers.forEach((h) => h.onEvent(event)));
  return { open, fire };
}

function Holder({ initial, open }: { initial: Build; open: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, open);
  return <ChatPanel build={build} chat={chat} />;
}

function PropHolder({ build, open }: { build: Build; open: OpenBuildEvents }) {
  const chat = useBuildStream(build, () => {}, open);
  return <ChatPanel build={build} chat={chat} />;
}

async function setup() {
  const created = await call(api.createBuild({ archetype: 'executive', mode: 'data' }));
  await call(api.startInterview(created.id));
  const build = await call(api.getBuild(created.id));
  const stream = fakeStream();
  const view = render(<Holder initial={build} open={stream.open} />);
  await stream.fire({ name: 'ready', data: { build_id: build.id } });
  await advance(0);
  const start = (node: string, run_id = 'r_1') => stream.fire({ name: 'run.started', data: { run_id, node } });
  const finish = (node: string, status: 'ok' | 'error' = 'ok', run_id = 'r_1') =>
    stream.fire({ name: 'run.finished', data: { run_id, node, status, error: status === 'ok' ? null : 'Gemini timed out' } });
  const usage = (input_tokens: number, output_tokens: number, node = 'plan') =>
    stream.fire({ name: 'run.usage', data: { run_id: 'r_1', node, input_tokens, output_tokens } });
  const progress = (text: string, node = 'plan') => stream.fire({ name: 'node.progress', data: { run_id: 'r_1', node, text } });
  return { build, view, ...stream, start, finish, usage, progress };
}

/** The strip's visible line, spaces normalized ('' when empty). */
const strip = () => {
  const line = document.querySelector('[data-activity-strip] p[aria-hidden="true"]');
  return (line?.textContent ?? '').replace(/·/g, ' · ').replace(/\s+/g, ' ').trim();
};
const card = () => document.querySelector<HTMLElement>('[data-run-card]');
const steps = () => Array.from(card()?.querySelectorAll<HTMLElement>('li') ?? []);
const statuses = () => steps().map((li) => li.dataset.stepStatus);

describe('Activity strip', () => {
  it('reserves its height before any run, so the list never jumps', async () => {
    await setup();
    const slot = document.querySelector<HTMLElement>('[data-activity-strip]');
    expect(slot?.className).toContain('h-8');
    expect(strip()).toBe('');
  });

  it('shows the phrase and elapsed time 400 ms after run.started, and live tokens from run.usage', async () => {
    const { start, usage } = await setup();
    await start('plan');
    await advance(399);
    expect(strip()).toBe('');
    await advance(1);
    expect(strip()).toBe('Reading the data profile · 0:00');
    await advance(65_000);
    expect(strip()).toContain('1:05');
    expect(strip()).not.toContain('tokens');
    await usage(80140, 12360);
    expect(strip()).toContain('92.5k tokens');
    const tokens = screen.getByTitle('80,140 input · 12,360 output tokens');
    expect(tokens.textContent).toBe('92.5k tokens');
  });

  it('rotates the phrase every 4 s', async () => {
    const { start } = await setup();
    await start('plan');
    await advance(400);
    expect(strip()).toContain('Reading the data profile');
    await advance(3600);
    expect(strip()).toContain('Planning the dashboard');
  });

  it('never shows a run that finishes within 400 ms', async () => {
    const { start, finish } = await setup();
    await start('plan');
    await advance(300);
    await finish('plan');
    for (const ms of [100, 400, 5000]) {
      await advance(ms);
      expect(strip()).toBe('');
    }
    expect(card()).toBeNull();
  });

  it('formats tokens as 950, 12.4k and 1.2M', () => {
    expect([formatTokens(950), formatTokens(12_400), formatTokens(92_500), formatTokens(1_234_567)]).toEqual(['950', '12.4k', '92.5k', '1.2M']);
  });

  it('an interview turn shows the strip but no card', async () => {
    const { start } = await setup();
    await start('interview');
    await advance(400);
    expect(strip()).toContain('Reading your answer');
    expect(card()).toBeNull();
  });

  it('an unknown node shows the generic phrases', async () => {
    const { start } = await setup();
    await start('summarize');
    await advance(400);
    expect(strip()).toContain('Working on it');
    expect(card()).toBeNull();
  });

  it('an execute run counts build.op events', async () => {
    const { start, fire } = await setup();
    const op = fixtures.events.find((e) => e.name === 'build.op');
    if (op?.name !== 'build.op') throw new Error('events.sse has no build.op');
    await start('execute');
    await advance(400);
    expect(strip()).toContain('0 ops done');
    await fire(op);
    await fire(op);
    expect(strip()).toContain('2 ops done');
  });

  it('the dots animate only without prefers-reduced-motion', async () => {
    const { start } = await setup();
    await start('plan');
    await advance(400);
    const dots = Array.from(document.querySelectorAll<HTMLElement>('[data-dots] > span'));
    expect(dots).toHaveLength(3);
    for (const dot of dots) {
      const classes = dot.className.split(/\s+/);
      expect(classes).toContain('motion-safe:animate-pulse');
      expect(classes.filter((c) => c.startsWith('animate-'))).toEqual([]);
    }
  });

  it('clears when the open build changes', async () => {
    const created = await call(api.createBuild({ archetype: 'executive', mode: 'data' }));
    const other = await call(api.createBuild({ archetype: 'executive', mode: 'data' }));
    const { open, fire } = fakeStream();
    // Like the workspace route: the same component gets another build.
    const view = render(<PropHolder build={created} open={open} />);
    await fire({ name: 'run.started', data: { run_id: 'r_1', node: 'plan' } });
    await advance(400);
    expect(strip()).not.toBe('');
    view.rerender(<PropHolder build={other} open={open} />);
    await advance(1000);
    expect(strip()).toBe('');
    expect(card()).toBeNull();
  });

  it('leaves no timer behind on unmount', async () => {
    const { start, view } = await setup();
    await start('plan');
    await advance(400);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('Run checklist card', () => {
  it('lists the plan steps, ticks them on the timer, and ticks the last only on run.finished ok', async () => {
    const { start, usage, finish } = await setup();
    await start('plan');
    await advance(400);
    expect(card()?.getAttribute('aria-label')).toBe('Planning the dashboard');
    expect(steps().map((li) => li.querySelector('span:not(.sr-only)')?.textContent)).toEqual([
      'Reading the data profile',
      'Writing build docs',
      'Creating the BigQuery view',
      'Writing the dashboard spec',
      'Checking the layout',
      'Rendering the prototype',
    ]);
    expect(statuses()).toEqual(['active', 'pending', 'pending', 'pending', 'pending', 'pending']);
    await advance(8000);
    expect(statuses()).toEqual(['done', 'active', 'pending', 'pending', 'pending', 'pending']);
    await advance(600_000);
    expect(statuses()).toEqual(['done', 'done', 'done', 'done', 'done', 'active']);
    await usage(80140, 12360);
    await finish('plan');
    expect(statuses()).toEqual(['done', 'done', 'done', 'done', 'done', 'done']);
    expect(strip()).toBe('Done in 10:08 · 92.5k tokens');
    await advance(4999);
    expect(strip()).toContain('Done in');
    await advance(1);
    expect(strip()).toBe('');
    expect(statuses()).toEqual(['done', 'done', 'done', 'done', 'done', 'done']);
  });

  it('scrolls the log to the card when it appears, and keeps its ticks out of the live log', async () => {
    const { start, finish, usage } = await setup();
    const log = screen.getByRole('log');
    Object.defineProperty(log, 'scrollHeight', { configurable: true, value: 1000 });
    log.scrollTop = 0;
    await start('plan');
    await advance(400);
    expect(log.scrollTop).toBe(1000);
    expect(card()?.getAttribute('aria-live')).toBe('off');
    await usage(80140, 12360);
    await finish('plan');
    expect(document.querySelector('[data-activity-strip] [role="status"]')?.textContent).toBe('Done in 0:00 · 92.5k tokens');
  });

  it('run.finished error marks the current step failed and later ones pending', async () => {
    const { start, finish } = await setup();
    await start('plan');
    await advance(10_000);
    await finish('plan', 'error');
    expect(statuses()).toEqual(['done', 'failed', 'pending', 'pending', 'pending', 'pending']);
    expect(strip()).toBe('Stopped after 0:10');
    await advance(60_000);
    expect(statuses()).toEqual(['done', 'failed', 'pending', 'pending', 'pending', 'pending']);
  });

  it('a node.progress text replaces the current step label', async () => {
    const { start, progress } = await setup();
    await start('plan');
    await advance(9000);
    await progress('Writing questions.md');
    const labels = steps().map((li) => li.querySelector('span:not(.sr-only)')?.textContent);
    expect(labels[1]).toBe('Writing questions.md');
    expect(labels[0]).toBe('Reading the data profile');
  });
});

describe('Mock mode', () => {
  it('every mocked run emits growing run.usage before run.finished', async () => {
    const build = await call(api.createBuild({ archetype: 'executive', mode: 'data' }));
    const events: BuildEvent[] = [];
    const close = openMockBuildEvents(build.id, { onEvent: (e) => events.push(e) });
    await call(api.startInterview(build.id));
    await call(api.generatePlan(build.id));
    close();
    const runs = new Set(events.flatMap((e) => (e.name === 'run.started' ? [e.data.run_id] : [])));
    expect(runs.size).toBeGreaterThanOrEqual(2);
    for (const run of runs) {
      const mine = events.filter((e) => 'run_id' in e.data && e.data.run_id === run);
      const usage = mine.flatMap((e) => (e.name === 'run.usage' ? [e.data.input_tokens + e.data.output_tokens] : []));
      expect(usage.length).toBeGreaterThan(0);
      expect([...usage].sort((a, b) => a - b)).toEqual(usage);
      expect(mine[mine.length - 1]?.name).toBe('run.finished');
    }
  });
});
