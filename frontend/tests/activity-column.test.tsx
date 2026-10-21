import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import { ApiError, type Build, type BuildEvent, type Message } from '../src/api/types';
import { ActivityColumn } from '../src/features/activity/ActivityColumn';
import { useBuildStream, type BuildStream } from '../src/features/activity/useBuildStream';
import { resetMockState } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** A fake stream: tests push events through the captured handlers. */
function fakeStream() {
  const handlers: StreamHandlers[] = [];
  const open: OpenBuildEvents = (_id, h) => {
    handlers.push(h);
    return () => {};
  };
  const fire = (event: BuildEvent) => act(() => handlers.forEach((h) => h.onEvent(event)));
  return { open, fire };
}

let latest: { build: Build; stream: BuildStream } | null = null;

function Holder({ initial, open }: { initial: Build; open: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const stream = useBuildStream(build, setBuild, open);
  latest = { build, stream };
  return <ActivityColumn build={build} stream={stream} />;
}

async function setup(build: Build = fixtures.build) {
  const stream = fakeStream();
  render(<Holder initial={build} open={stream.open} />);
  const ready = () => stream.fire({ name: 'ready', data: { build_id: build.id } });
  return { build, ...stream, ready };
}

const message = (id: string, role: Message['role'], text: string): Message => ({
  id,
  role,
  text,
  node: null,
  created_at: '2026-10-18T09:00:00Z',
});
const bubbles = () => Array.from(document.querySelectorAll<HTMLElement>('[role="log"] [data-bubble]'));
const log = () => screen.getByRole('log', { name: 'Activity log' });
const firstNote = /I drafted the context/;

describe('Activity column', () => {
  it('is the left column with the log and the strip, and has no input', async () => {
    const { ready } = await setup();
    await ready();
    await screen.findByText(firstNote);
    const column = screen.getByRole('complementary', { name: 'Activity' });
    expect(within(column).queryByRole('textbox')).toBeNull();
    expect(within(column).queryByRole('button', { name: /send/i })).toBeNull();
    expect(column.querySelector('[data-activity-strip]')).not.toBeNull();
  });

  it('appends message.delta events to one bubble and message.done replaces it', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(firstNote);
    const before = bubbles().length;

    await fire({ name: 'message.delta', data: { message_id: 'm_draft', text: 'Hello ' } });
    await fire({ name: 'message.delta', data: { message_id: 'm_draft', text: 'world' } });
    expect(bubbles()).toHaveLength(before + 1);
    expect(document.querySelector<HTMLElement>('[data-draft="true"]')?.textContent).toContain('Hello world');

    await fire({ name: 'message.done', data: { message: message('m_draft', 'assistant', 'Hello final answer') } });
    expect(bubbles()).toHaveLength(before + 1);
    expect(document.querySelector('[data-draft="true"]')).toBeNull();
    expect(screen.getByText('Hello final answer')).toBeTruthy();
  });

  it('refetches the build and messages on every ready, and shows new server messages', async () => {
    const { build, ready } = await setup();
    const getBuild = vi.spyOn(api, 'getBuild');
    const list = vi.spyOn(api, 'listMessages');
    await ready();
    await screen.findByText(firstNote);
    expect(getBuild).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledTimes(1);

    list.mockResolvedValueOnce([...fixtures.messages, message('m_c', 'assistant', 'Brand new server message')]);
    await ready();
    await screen.findByText('Brand new server message');
    expect(getBuild).toHaveBeenLastCalledWith(build.id);
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('bumps only the updated artifact on artifact.updated, and every artifact on a reconnect', async () => {
    const { ready, fire } = await setup();
    await ready();
    const before = latest!.stream.artifactSeq;
    await fire({ name: 'artifact.updated', data: { artifact: 'outline', revision: 4 } });
    expect(latest!.stream.artifactSeq).toEqual({ ...before, outline: before.outline + 1 });
    await ready();
    expect(latest!.stream.artifactSeq).toEqual({ context: before.context + 1, outline: before.outline + 2, design: before.design + 1, blueprint: before.blueprint + 1 });
  });

  it('tracks the running staged run and its error, cleared when that node runs again', async () => {
    const { ready, fire } = await setup();
    await ready();
    await fire({ name: 'run.started', data: { run_id: 'r_1', node: 'blueprint' } });
    expect(latest!.stream.running).toBe('blueprint');
    await fire({ name: 'run.finished', data: { run_id: 'r_1', node: 'blueprint', status: 'error', error: null } });
    expect(latest!.stream.running).toBeNull();
    expect(latest!.stream.runErrors.blueprint).toBe("The blueprint didn't finish. Regenerate it.");
    await fire({ name: 'run.started', data: { run_id: 'r_2', node: 'blueprint' } });
    expect(latest!.stream.runErrors.blueprint).toBeUndefined();
  });

  it('shows a load error and re-fetches on Try again', async () => {
    const { ready } = await setup();
    const list = vi.spyOn(api, 'listMessages').mockRejectedValueOnce(new ApiError(500, 'internal', 'The server is down.'));
    await ready();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Couldn't load the activity");
    expect(alert.textContent).toContain('The server is down.');
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await screen.findByText(firstNote);
    expect(list).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows the empty state of a new build', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    const { ready } = await setup(created);
    await ready();
    await screen.findByText('No activity yet');
    expect(screen.getByText('Runs and assistant notes show up here once you draft the context.')).toBeTruthy();
  });

  it('renders markdown in assistant bubbles, with links opening in a new tab', async () => {
    const { ready } = await setup();
    vi.spyOn(api, 'listMessages').mockResolvedValue([message('m_md', 'assistant', 'Pick **one** of:\n\n- revenue\n- orders\n\nSee [the docs](https://example.com/docs).')]);
    await ready();
    expect((await screen.findByText('one')).tagName).toBe('STRONG');
    expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(2);
    const link = screen.getByRole('link', { name: /^the docs/ }) as HTMLAnchorElement;
    expect(link.textContent).toContain('(opens in a new tab)');
    expect(link.target).toBe('_blank');
    expect(link.rel).toContain('noopener');
  });

  it('shows done-build copy when a done build has no messages', async () => {
    const { build, ready, fire } = await setup();
    vi.spyOn(api, 'listMessages').mockResolvedValue([]);
    await ready();
    await fire({ name: 'build.updated', data: { build: { ...build, stage: 'done' } } });
    const empty = await screen.findByText('No activity yet');
    expect((empty.parentElement as HTMLElement).textContent).toContain('No notes were kept for this build.');
  });
});

describe('Stream races', () => {
  it('keeps a build.updated that arrives just before stage.changed', async () => {
    const { build, ready, fire } = await setup();
    await ready();
    await screen.findByText(firstNote);
    await act(async () => {
      fire({ name: 'build.updated', data: { build: { ...build, notes: 'Updated notes', artifacts: { ...build.artifacts, outline: 'draft', design: 'stale', blueprint: 'stale' } } } });
      fire({ name: 'stage.changed', data: { stage: 'outline' } });
    });
    expect(latest!.build).toMatchObject({ stage: 'outline', notes: 'Updated notes', artifacts: { outline: 'draft', design: 'stale' } });
  });

  it('keeps a message.done that lands while the reconnect re-fetch is in flight', async () => {
    const { build, ready, fire } = await setup();
    await ready();
    await screen.findByText(firstNote);
    const stale = await api.listMessages(build.id);
    let resolve: (list: Message[]) => void = () => {};
    vi.spyOn(api, 'listMessages').mockReturnValueOnce(new Promise((r) => (resolve = r)));
    await ready();
    await fire({ name: 'message.done', data: { message: message('m_late', 'assistant', 'A late explanation') } });
    await act(async () => resolve(stale));
    expect(within(log()).getByText('A late explanation')).toBeTruthy();
  });
});
