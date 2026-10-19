import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import { ApiError, type Build, type BuildEvent, type Message } from '../src/api/types';
import { ChatPanel } from '../src/features/workspace/chat/ChatPanel';
import { AWAIT_RUN_MS, InterviewStage } from '../src/features/workspace/chat/InterviewStage';
import { useBuildStream } from '../src/features/workspace/chat/useBuildStream';
import { resetMockState, setMockRunFailure } from '../src/mocks/api';
import { openMockBuildEvents } from '../src/mocks/events';

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
      <main>
        {build.stage === 'interview' && (
          <InterviewStage build={build} messages={chat.messages} loadError={chat.loadError} runErrors={chat.runErrors} />
        )}
      </main>
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

  it('marks markdown links as opening in a new tab', async () => {
    const { ready } = await setup();
    vi.spyOn(api, 'listMessages').mockResolvedValue([message('m_link', 'assistant', 'See [the docs](https://example.com/docs).')]);
    await ready();
    const link = (await screen.findByRole('link', { name: /^the docs/ })) as HTMLAnchorElement;
    expect(link.textContent).toContain('(opens in a new tab)');
    expect(link.target).toBe('_blank');
    expect(link.rel).toContain('noopener');
    expect(link.classList.contains('hover:text-primary-hover')).toBe(true);
  });

  it('shows done-build copy when a done build has no messages', async () => {
    const { build, ready, fire } = await setup();
    vi.spyOn(api, 'listMessages').mockResolvedValue([]);
    await ready();
    await fire({ name: 'build.updated', data: { build: { ...build, stage: 'done' } } });
    const empty = await screen.findByText('No messages yet');
    const text = (empty.parentElement as HTMLElement).textContent ?? '';
    expect(text).not.toContain('first question');
    expect(text).toContain('No messages were kept for this build.');
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

describe('Run errors', () => {
  const failPlan = async (fire: (event: BuildEvent) => Promise<void> | void, error: string | null) => {
    await fire({ name: 'stage.changed', data: { stage: 'plan' } });
    await fire({ name: 'run.started', data: { run_id: 'r_plan', node: 'plan' } });
    await fire({ name: 'run.finished', data: { run_id: 'r_plan', node: 'plan', status: 'error', error } });
    await fire({ name: 'stage.changed', data: { stage: 'interview' } });
  };
  const stageAlert = () => within(screen.getByRole('main')).queryByRole('alert');

  it('shows a failed plan run on the Interview stage and clears it on the next plan run', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await failPlan(fire, 'Gemini quota hit');
    expect(stageAlert()?.textContent).toContain('Gemini quota hit');
    expect(within(stageAlert() as HTMLElement).getByRole('button', { name: 'Generate plan again' })).toBeTruthy();
    await fire({ name: 'run.started', data: { run_id: 'r_plan2', node: 'plan' } });
    expect(stageAlert()).toBeNull();
  });

  it('falls back to a line naming "Generate plan" when the error has no text', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await failPlan(fire, null);
    expect(stageAlert()?.textContent).toContain('Try "Generate plan" again.');
  });

  it('shows a failed spec run on the Interview stage; a new plan run clears it', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await fire({ name: 'run.started', data: { run_id: 'r_spec', node: 'spec' } });
    await fire({ name: 'run.finished', data: { run_id: 'r_spec', node: 'spec', status: 'error', error: null } });
    expect(stageAlert()?.textContent).toContain("The spec didn't finish.");
    await fire({ name: 'run.started', data: { run_id: 'r_plan', node: 'plan' } });
    expect(stageAlert()).toBeNull();
  });

  it('shows a failed interview run in the chat and clears it on the next interview run', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await fire({ name: 'run.started', data: { run_id: 'r_i', node: 'interview' } });
    await fire({ name: 'message.delta', data: { message_id: 'm_draft', text: 'Half a' } });
    await fire({ name: 'run.finished', data: { run_id: 'r_i', node: 'interview', status: 'error', error: 'The model timed out.' } });
    const chat = screen.getByRole('complementary', { name: 'Chat' });
    // The server's text plus what to do next.
    expect(within(chat).getByRole('alert').textContent).toBe('The model timed out. Send your answer again.');
    expect(document.querySelector('[data-draft="true"]')).toBeNull();
    await fire({ name: 'run.started', data: { run_id: 'r_i2', node: 'interview' } });
    expect(within(chat).queryByRole('alert')).toBeNull();
  });

  it('posts /plan once for two quick clicks on "Generate plan again" and disables it meanwhile', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await failPlan(fire, 'Gemini quota hit');
    let finish: (value: { run_id: string }) => void = () => {};
    const spy = vi.spyOn(api, 'generatePlan').mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const retry = within(stageAlert() as HTMLElement).getByRole('button', { name: 'Generate plan again' }) as HTMLButtonElement;
    fireEvent.click(retry);
    fireEvent.click(retry);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(retry.disabled).toBe(true);
    await act(async () => finish({ run_id: 'r_x' }));
  });

  it('posts /plan once for two clicks in the same frame (the ref guard, not only disabled)', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await failPlan(fire, 'Gemini quota hit');
    const spy = vi.spyOn(api, 'generatePlan').mockResolvedValue({ run_id: 'r_x' });
    const retry = within(stageAlert() as HTMLElement).getByRole('button', { name: 'Generate plan again' }) as HTMLButtonElement;
    await act(async () => {
      retry.click();
      retry.click();
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('keeps "Generate plan again" busy after the POST until the plan run starts', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await failPlan(fire, 'Gemini quota hit');
    const spy = vi.spyOn(api, 'generatePlan').mockResolvedValue({ run_id: 'r_x' });
    const retry = () => within(stageAlert() as HTMLElement).getByRole('button', { name: 'Generate plan again' }) as HTMLButtonElement;
    expect(retry().getAttribute('aria-busy')).toBeNull();
    await act(async () => {
      fireEvent.click(retry());
    });
    // The POST resolved; the run error stays until `run.started`.
    expect(stageAlert()?.textContent).toContain('Gemini quota hit');
    expect(retry().disabled).toBe(true);
    expect(retry().getAttribute('aria-busy')).toBe('true');
    expect(retry().querySelector('[class*="animate-spin"]')).toBeTruthy();
    await act(async () => {
      fireEvent.click(retry());
    });
    expect(spy).toHaveBeenCalledTimes(1);
    await fire({ name: 'run.started', data: { run_id: 'r_plan2', node: 'plan' } });
    expect(stageAlert()).toBeNull();
    const plan = screen.getByRole('button', { name: 'Generate plan' }) as HTMLButtonElement;
    expect(plan.disabled).toBe(false);
    expect(plan.getAttribute('aria-busy')).toBeNull();
  });

  it('frees the buttons when run.started arrives before the POST resolves', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await failPlan(fire, 'Gemini quota hit');
    let finish: (value: { run_id: string }) => void = () => {};
    vi.spyOn(api, 'generatePlan').mockReturnValue(new Promise((resolve) => (finish = resolve)));
    fireEvent.click(within(stageAlert() as HTMLElement).getByRole('button', { name: 'Generate plan again' }));
    await fire({ name: 'run.started', data: { run_id: 'r_plan2', node: 'plan' } });
    await act(async () => finish({ run_id: 'r_plan2' }));
    expect(stageAlert()).toBeNull();
    const plan = screen.getByRole('button', { name: 'Generate plan' }) as HTMLButtonElement;
    expect(plan.disabled).toBe(false);
    expect(plan.getAttribute('aria-busy')).toBeNull();
  });

  it('gives the retry back if run.started never arrives (a run missed while the stream was down)', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await failPlan(fire, 'Gemini quota hit');
    const spy = vi.spyOn(api, 'generatePlan').mockResolvedValue({ run_id: 'r_x' });
    const retry = () => within(stageAlert() as HTMLElement).getByRole('button', { name: 'Generate plan again' }) as HTMLButtonElement;
    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.click(retry());
      });
      expect(retry().disabled).toBe(true);
      act(() => vi.advanceTimersByTime(AWAIT_RUN_MS - 1));
      expect(retry().disabled).toBe(true);
      act(() => vi.advanceTimersByTime(1));
      expect(retry().disabled).toBe(false);
      expect(retry().getAttribute('aria-busy')).toBeNull();
      await act(async () => {
        fireEvent.click(retry());
      });
      expect(spy).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('re-enables the retry with the error shown when the POST is rejected', async () => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await failPlan(fire, 'Gemini quota hit');
    const spy = vi.spyOn(api, 'generatePlan').mockRejectedValue(new ApiError(502, 'backend_down', 'The planner is offline.'));
    fireEvent.click(within(stageAlert() as HTMLElement).getByRole('button', { name: 'Generate plan again' }));
    await waitFor(() => expect(stageAlert()?.textContent).toContain('The planner is offline.'));
    const retry = within(stageAlert() as HTMLElement).getByRole('button', { name: 'Try again' }) as HTMLButtonElement;
    expect(retry.disabled).toBe(false);
    expect(retry.getAttribute('aria-busy')).toBeNull();
    spy.mockResolvedValue({ run_id: 'r_y' });
    await act(async () => {
      fireEvent.click(retry);
    });
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it.each([
    ['quota hit', 'quota hit. Send your answer again.'],
    ['Model timed out.', 'Model timed out. Send your answer again.'],
    ['quota hit. ', 'quota hit. Send your answer again.'],
    ['He said "stop."', 'He said "stop." Send your answer again.'],
  ])('ends an interview error %j as a sentence before the next step', async (error, shown) => {
    const { ready, fire } = await setup();
    await ready();
    await screen.findByText(/Who will read this dashboard/);
    await fire({ name: 'run.started', data: { run_id: 'r_i', node: 'interview' } });
    await fire({ name: 'run.finished', data: { run_id: 'r_i', node: 'interview', status: 'error', error } });
    const chat = screen.getByRole('complementary', { name: 'Chat' });
    expect(within(chat).getByRole('alert').textContent).toBe(shown);
  });

  it('the mock fails a plan back to the Interview stage with its error', async () => {
    setMockRunFailure('plan', 'Gemini quota hit');
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    await api.startInterview(created.id);
    render(<Holder initial={await api.getBuild(created.id)} open={openMockBuildEvents} />);
    await screen.findByText(/Who will read this dashboard/);
    fireEvent.click(screen.getByRole('button', { name: 'Generate plan' }));
    await waitFor(() => expect(stageAlert()?.textContent).toContain('Gemini quota hit'));
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
