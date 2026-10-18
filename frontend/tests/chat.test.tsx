import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import { ApiError, type Build, type BuildEvent, type Message } from '../src/api/types';
import { ChatPanel } from '../src/features/workspace/chat/ChatPanel';
import { InterviewStage } from '../src/features/workspace/chat/InterviewStage';
import { useBuildStream } from '../src/features/workspace/chat/useBuildStream';
import { resetMockState } from '../src/mocks/api';

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

function Holder({ initial, open }: { initial: Build; open: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, open);
  return (
    <>
      <ChatPanel build={build} chat={chat} />
      {build.stage === 'interview' && <InterviewStage build={build} messages={chat.messages} loadError={chat.loadError} />}
    </>
  );
}

async function setup(stage: 'connect' | 'interview' = 'interview') {
  const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
  if (stage === 'interview') await api.startInterview(created.id);
  const build = await api.getBuild(created.id);
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
const log = () => screen.getByRole('log');
const box = () => screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement;
const sendButton = () => screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement;
const type = (value: string) => fireEvent.change(box(), { target: { value } });

describe('Chat panel', () => {
  it('appends message.delta events to one bubble and message.done replaces it', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    const before = bubbles().length;

    await fire({ name: 'message.delta', data: { message_id: 'm_draft', text: 'Hello ' } });
    await fire({ name: 'message.delta', data: { message_id: 'm_draft', text: 'world' } });
    expect(bubbles()).toHaveLength(before + 1);
    const draft = document.querySelector<HTMLElement>('[data-draft="true"]');
    expect(draft?.textContent).toContain('Hello world');

    await fire({ name: 'message.done', data: { message: message('m_draft', 'assistant', 'Hello final answer') } });
    expect(bubbles()).toHaveLength(before + 1);
    expect(document.querySelector('[data-draft="true"]')).toBeNull();
    expect(screen.getByText('Hello final answer')).toBeTruthy();
    expect(screen.queryByText(/Hello world/)).toBeNull();
  });

  it('shows the user bubble at once on send and posts the text; Enter sends too', async () => {
    const { build, ready } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    const spy = vi.spyOn(api, 'sendMessage').mockReturnValue(new Promise(() => {}));

    type('The sales team');
    fireEvent.click(sendButton());
    expect(within(log()).getByText('The sales team')).toBeTruthy();
    expect(spy).toHaveBeenCalledWith(build.id, 'The sales team');

    // The first send is still pending, so use a fresh panel for the Enter path.
    cleanup();
    const second = await setup();
    await second.ready();
    await screen.findByText(/Who will read this dashboard/);
    type('Monthly numbers');
    fireEvent.keyDown(box(), { key: 'Enter' });
    expect(within(log()).getByText('Monthly numbers')).toBeTruthy();
    expect(spy).toHaveBeenLastCalledWith(second.build.id, 'Monthly numbers');
  });

  it('keeps Shift+Enter as a newline and ignores empty text', async () => {
    const { ready } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    const spy = vi.spyOn(api, 'sendMessage');
    expect(sendButton().disabled).toBe(true);
    type('   ');
    expect(sendButton().disabled).toBe(true);
    fireEvent.keyDown(box(), { key: 'Enter' });
    type('Line one');
    fireEvent.keyDown(box(), { key: 'Enter', shiftKey: true });
    expect(spy).not.toHaveBeenCalled();
  });

  it('refetches the build and messages on every ready, and shows new server messages', async () => {
    const { build, ready } = await setup();
    const getBuild = vi.spyOn(api, 'getBuild');
    const list = vi.spyOn(api, 'listMessages');
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    expect(getBuild).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledTimes(1);

    list.mockResolvedValueOnce([
      message('m_a', 'assistant', 'First question'),
      message('m_b', 'user', 'First answer'),
      message('m_c', 'assistant', 'Brand new server message'),
    ]);
    await ready();
    await screen.findByText('Brand new server message');
    expect(getBuild).toHaveBeenCalledTimes(2);
    expect(getBuild).toHaveBeenLastCalledWith(build.id);
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('shows a load error and re-fetches on Try again', async () => {
    const { ready } = await setup();
    const list = vi.spyOn(api, 'listMessages').mockRejectedValueOnce(new ApiError(500, 'internal', 'The server is down.'));
    await ready();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The server is down.');
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await screen.findByText(/Who will read this dashboard/);
    expect(list).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('keeps the text and shows the error when sending fails', async () => {
    const { ready } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    vi.spyOn(api, 'sendMessage').mockRejectedValue(new ApiError(502, 'backend_down', 'The assistant is offline.'));
    const before = bubbles().length;
    type('Will this work?');
    fireEvent.click(sendButton());
    // Shown under the field and announced once (focus stays in the field).
    expect((await screen.findByRole('alert')).textContent).toBe('The assistant is offline.');
    expect(screen.getAllByText('The assistant is offline.')).toHaveLength(2);
    expect(box().value).toBe('Will this work?');
    expect(bubbles()).toHaveLength(before);
  });

  it('locks the composer on the connect stage and shows the empty state', async () => {
    const { ready } = await setup('connect');
    await ready();
    await screen.findByText('No messages yet');
    expect(screen.getByText('The interview starts here once you add a source.')).toBeTruthy();
    expect(box().disabled).toBe(true);
    expect(sendButton().disabled).toBe(true);
    expect(screen.getByText('Add a source and start the interview first.')).toBeTruthy();
  });

  it('renders markdown in assistant bubbles', async () => {
    const { ready } = await setup();
    vi.spyOn(api, 'listMessages').mockResolvedValue([message('m_md', 'assistant', 'Pick **one** of:\n\n- revenue\n- orders')]);
    await ready();
    expect((await screen.findByText('one')).tagName).toBe('STRONG');
    expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(2);
  });
});

describe('Interview stage', () => {
  it('lists the answers with their questions', async () => {
    const { ready } = await setup();
    vi.spyOn(api, 'listMessages').mockResolvedValue([
      message('m1', 'assistant', 'Who reads it?'),
      message('m2', 'user', 'The sales director'),
    ]);
    await ready();
    const heading = await screen.findByText('Questions answered so far');
    const panel = heading.closest('section') as HTMLElement;
    await within(panel).findByText('The sales director');
    expect(within(panel).getByText('Who reads it?')).toBeTruthy();
    expect(screen.getByText('Questions answered so far')).toBeTruthy();
  });

  it('turns Generate plan primary on build.updated with ready_for_plan and posts the plan', async () => {
    const { build, ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    const plan = () => screen.getByRole('button', { name: 'Generate plan' }) as HTMLButtonElement;
    expect(plan().dataset.ready).toBe('false');
    expect(plan().classList.contains('bg-primary')).toBe(false);

    await fire({ name: 'build.updated', data: { build: { ...build, ready_for_plan: true } } });
    await waitFor(() => expect(plan().dataset.ready).toBe('true'));
    expect(plan().classList.contains('bg-primary')).toBe(true);
    expect(screen.getByText('The assistant has enough to plan.')).toBeTruthy();

    const spy = vi.spyOn(api, 'generatePlan').mockResolvedValue({ run_id: 'r_1' });
    fireEvent.click(plan());
    expect(spy).toHaveBeenCalledWith(build.id);
  });

  it('shows an inline error when planning fails', async () => {
    const { ready } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    vi.spyOn(api, 'generatePlan').mockRejectedValue(new ApiError(502, 'backend_down', 'The planner is offline.'));
    fireEvent.click(screen.getByRole('button', { name: 'Generate plan' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The planner is offline.');
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeTruthy();
  });
});

describe('Stream races', () => {
  it('keeps a build.updated that arrives just before stage.changed', async () => {
    const { build, ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await act(async () => {
      fire({ name: 'build.updated', data: { build: { ...build, ready_for_plan: true } } });
      fire({ name: 'stage.changed', data: { stage: 'interview' } });
    });
    const plan = screen.getByRole('button', { name: 'Generate plan' }) as HTMLButtonElement;
    expect(plan.dataset.ready).toBe('true');
  });

  it('keeps a message.done that lands while the reconnect re-fetch is in flight', async () => {
    const { build, ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    const stale = await api.listMessages(build.id);
    let resolve: (list: Message[]) => void = () => {};
    vi.spyOn(api, 'listMessages').mockReturnValueOnce(new Promise((r) => (resolve = r)));
    await ready();
    await fire({ name: 'message.done', data: { message: message('m_late', 'assistant', 'A late question') } });
    await act(async () => resolve(stale));
    expect(within(log()).getByText('A late question')).toBeTruthy();
  });

  it('points the answers list to the chat when the messages fail to load', async () => {
    vi.spyOn(api, 'listMessages').mockRejectedValue(new ApiError(0, 'network_error', 'Backend down.'));
    const { ready } = await setup();
    await ready();
    expect(await screen.findByText(/Couldn't load the answers/)).toBeTruthy();
  });
});
