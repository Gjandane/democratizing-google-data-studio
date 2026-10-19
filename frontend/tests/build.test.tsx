import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import { ApiError, type Build, type BuildEvent, type OpFinished } from '../src/api/types';
import { BuildStage } from '../src/features/workspace/build/BuildStage';
import { failedCount, idleRun, reduceBuildRun } from '../src/features/workspace/build/buildRun';
import { useBuildStream } from '../src/features/workspace/chat/useBuildStream';
import { resetMockState, setMockBuildOutcome, setMockEngine } from '../src/mocks/api';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { PrototypeStage } from '../src/features/workspace/prototype/PrototypeStage';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

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
  return <BuildStage build={build} run={chat.buildRun} />;
}

const ops = fixtures.recipe.ops;

const opEvent = (op_id: string, status: OpFinished['status'], message = ''): BuildEvent => ({
  name: 'build.op',
  data: { event: 'op_finished', ts: '2026-10-18T10:00:00Z', op_id, op: 'x', status, message, screenshot: null, duration_ms: 10 },
});

const finished = (status: 'ok' | 'partial' | 'failed', report_url: string | null = 'https://lookerstudio.google.com/reporting/abc'): BuildEvent => ({
  name: 'build.finished',
  data: { status, report_url, version: 1 },
});

async function setup(open: OpenBuildEvents = fakeStream().open) {
  const build = await api.getBuild(fixtures.build.id);
  render(<Holder initial={build} open={open} />);
  return build;
}

/** Waits for the engine panel, generates the recipe and waits for its lines. */
async function withRecipe() {
  const stream = fakeStream();
  const build = await setup(stream.open);
  await screen.findByText(/Signed in to Google|Not signed in to Google/);
  fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
  await screen.findByRole('list', { name: 'Recipe' });
  return { build, ...stream };
}

const row = (id: string) => document.querySelector<HTMLElement>(`li[data-op-id="${id}"]`)!;
const buildButton = () => screen.getByRole('button', { name: 'Build in Data Studio' }) as HTMLButtonElement;

describe('Build stage recipe', () => {
  it('renders the recipe lines in Fira Code with their op ids', async () => {
    await withRecipe();
    const items = within(screen.getByRole('list', { name: 'Recipe' })).getAllByRole('listitem');
    expect(items).toHaveLength(ops.length);
    for (const op of ops) {
      const line = screen.getByText(op.line);
      const id = within(row(op.op_id)).getByText(op.op_id);
      expect(line.classList.contains('font-mono')).toBe(true);
      expect(id.classList.contains('font-mono')).toBe(true);
    }
    expect(screen.getByText(`· ${ops.length} ops`, { exact: false })).toBeTruthy();
  });

  it('shows the compile error and keeps the button', async () => {
    vi.spyOn(api, 'compileRecipe').mockRejectedValue(new ApiError(409, 'wrong_stage', 'Generate the plan before the recipe.', {}));
    await setup();
    await screen.findByText('Chrome running');
    fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Generate the plan before the recipe.');
    expect(screen.getByRole('button', { name: 'Generate recipe' })).toBeTruthy();
  });

  it('ticks each line with build.op and shows the failed message', async () => {
    const { fire } = await withRecipe();
    await fire(opEvent('s001', 'ok'));
    await fire(opEvent('s002', 'failed', 'style panel: colors control not found'));
    await fire(opEvent('s003', 'skipped'));
    expect(row('s001').dataset.status).toBe('ok');
    expect(row('s002').dataset.status).toBe('failed');
    expect(row('s003').dataset.status).toBe('skipped');
    expect(within(row('s002')).getByText('style panel: colors control not found')).toBeTruthy();
    expect(within(row('s001')).getByText('Done')).toBeTruthy();
  });

  it('ignores an op id that is not in the recipe but counts it as failed', async () => {
    const { fire } = await withRecipe();
    await fire(opEvent('s999', 'failed', 'boom'));
    expect(document.querySelectorAll('li[data-op-id]')).toHaveLength(ops.length);
    expect(Array.from(document.querySelectorAll('li[data-op-id]')).every((li) => (li as HTMLElement).dataset.status === 'pending')).toBe(true);
    await fire(finished('partial'));
    expect(screen.getByText('1 op failed')).toBeTruthy();
  });

  it('marks the first op without a result as running while the run goes', async () => {
    const { fire } = await withRecipe();
    await fire({ name: 'run.started', data: { run_id: 'r_000000000001', node: 'execute' } });
    await fire({ name: 'stage.changed', data: { stage: 'build' } });
    expect(row('s001').dataset.status).toBe('running');
    await fire(opEvent('s001', 'ok'));
    expect(row('s001').dataset.status).toBe('ok');
    expect(row('s002').dataset.status).toBe('running');
    expect(screen.getByText('1 of 3 ops done')).toBeTruthy();
  });
});

describe('Build stage result', () => {
  it('partial: link opens in a new tab and counts failed ops', async () => {
    const { fire } = await withRecipe();
    await fire(opEvent('s001', 'ok'));
    await fire(opEvent('s002', 'failed', 'nope'));
    await fire(finished('partial'));
    const link = screen.getByRole('link', { name: 'Open in Data Studio' }) as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('https://lookerstudio.google.com/reporting/abc');
    expect(link.target).toBe('_blank');
    expect(link.rel).toContain('noopener');
    expect(screen.getByText('1 op failed')).toBeTruthy();
    expect(screen.getByText(/The dashboard is saved/)).toBeTruthy();
  });

  it('partial: plural count', async () => {
    const { fire } = await withRecipe();
    await fire(opEvent('s001', 'failed', 'a'));
    await fire(opEvent('s002', 'failed', 'b'));
    await fire(finished('partial'));
    expect(screen.getByText('2 ops failed')).toBeTruthy();
  });

  it('ok: link and no failed count', async () => {
    const { fire } = await withRecipe();
    await fire(finished('ok'));
    expect(screen.getByText('Your dashboard is in Data Studio.')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open in Data Studio' })).toBeTruthy();
    expect(screen.queryByText(/ops? failed/)).toBeNull();
  });

  it('failed: message and no link', async () => {
    const { fire } = await withRecipe();
    await fire(finished('failed', null));
    expect(screen.getByText('The build failed.')).toBeTruthy();
    expect(screen.getByText(/The engine stopped before the dashboard was saved/)).toBeTruthy();
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('Build stage engine', () => {
  it('disables Build while signed out, then enables it after signing in', async () => {
    setMockEngine({ chrome_running: true, signed_in: false });
    const login = vi.spyOn(api, 'engineLogin');
    await setup();
    await screen.findByText('Not signed in to Google');
    fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
    await screen.findByRole('list', { name: 'Recipe' });
    expect(buildButton().disabled).toBe(true);
    expect(screen.getByText('Sign in to Google to build.')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Sign in to Google' }));
    await screen.findByText('Finish signing in in the Chrome window that opened.');
    expect(login).toHaveBeenCalledTimes(1);
    // The mock flips right away; "Check again" re-reads the status without waiting for the poll.
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
    await screen.findByText('Signed in to Google');
    await waitFor(() => expect(buildButton().disabled).toBe(false));
  });

  it('shows a retry when the engine status fails to load', async () => {
    vi.spyOn(api, 'getEngineStatus').mockRejectedValueOnce(new ApiError(502, 'network_error', 'The backend is not reachable. Start it, then retry.', {}));
    await setup();
    expect((await screen.findByRole('alert')).textContent).toContain('The backend is not reachable');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByText('Signed in to Google');
  });

  it('shows the login error inline', async () => {
    setMockEngine({ chrome_running: false, signed_in: false });
    vi.spyOn(api, 'engineLogin').mockRejectedValue(new ApiError(500, 'engine_error', 'Chrome would not start. Close other Chrome windows, then retry.', {}));
    await setup();
    await screen.findByText('Chrome not running');
    fireEvent.click(screen.getByRole('button', { name: 'Sign in to Google' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Chrome would not start');
  });
});

describe('Build stage run', () => {
  it('runs end to end on the mock stream', async () => {
    render(<MockHolder initial={await api.getBuild(fixtures.build.id)} />);
    await screen.findByText('Signed in to Google');
    fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
    await screen.findByRole('list', { name: 'Recipe' });
    await waitFor(() => expect(buildButton().disabled).toBe(false));
    fireEvent.click(buildButton());
    await waitFor(() => expect(row('s001').dataset.status).toBe('ok'));
    const status = await screen.findByText('Your dashboard is in Data Studio.');
    expect(status).toBeTruthy();
    expect(Array.from(document.querySelectorAll('li[data-op-id]')).every((li) => (li as HTMLElement).dataset.status === 'ok')).toBe(true);
  });

  it('runs a partial outcome on the mock stream', async () => {
    setMockBuildOutcome('partial');
    render(<MockHolder initial={await api.getBuild(fixtures.build.id)} />);
    await screen.findByText('Signed in to Google');
    fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
    await screen.findByRole('list', { name: 'Recipe' });
    await waitFor(() => expect(buildButton().disabled).toBe(false));
    fireEvent.click(buildButton());
    await screen.findByText('1 op failed');
    expect(within(row('s003')).getByText('style panel: colors control not found')).toBeTruthy();
  });

  it('shows the engine_busy message', async () => {
    await withRecipe();
    await waitFor(() => expect(buildButton().disabled).toBe(false));
    vi.spyOn(api, 'runBuild').mockRejectedValue(new ApiError(409, 'engine_busy', 'Another build is running in Data Studio. Wait for it to finish, then try again.', {}));
    fireEvent.click(buildButton());
    expect((await screen.findByRole('alert')).textContent).toContain('Another build is running in Data Studio');
    expect(buildButton().disabled).toBe(false);
  });

  it('re-checks the engine after engine_not_signed_in', async () => {
    await withRecipe();
    await waitFor(() => expect(buildButton().disabled).toBe(false));
    const status = vi.spyOn(api, 'getEngineStatus');
    vi.spyOn(api, 'runBuild').mockRejectedValue(new ApiError(424, 'engine_not_signed_in', 'Sign in to Google first, then build again.', {}));
    fireEvent.click(buildButton());
    await screen.findByText('Sign in to Google first, then build again.');
    await waitFor(() => expect(status).toHaveBeenCalled());
  });

  it('fetches the recipe on its own when opened with a run going', async () => {
    const stream = fakeStream();
    render(<Holder initial={{ ...(await api.getBuild(fixtures.build.id)), stage: 'build' }} open={stream.open} />);
    await screen.findByRole('list', { name: 'Recipe' });
    expect(row('s001').dataset.status).toBe('running');
    expect(screen.getByText('Building in Data Studio…')).toBeTruthy();
  });
});

/** Like Holder, on the real mock stream. */
function MockHolder({ initial }: { initial: Build }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild);
  return <BuildStage build={build} run={chat.buildRun} />;
}

describe('Build stage state from the stage', () => {
  async function running() {
    const ctx = await withRecipe();
    await ctx.fire({ name: 'run.started', data: { run_id: 'r_000000000001', node: 'execute' } });
    await ctx.fire({ name: 'stage.changed', data: { stage: 'build' } });
    await ctx.fire(opEvent('s001', 'ok'));
    expect(screen.getByText('Building in Data Studio…')).toBeTruthy();
    return ctx;
  }

  it('stops showing the run as going when the stage moves on without build.finished (done)', async () => {
    const { fire } = await running();
    await fire({ name: 'stage.changed', data: { stage: 'done' } });
    expect(screen.queryByText('Building in Data Studio…')).toBeNull();
    expect(row('s002').dataset.status).toBe('pending');
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeTruthy();
    expect(screen.getByText('Start a new version to build again.')).toBeTruthy();
  });

  it('stops showing the run as going when the stage returns to the prototype', async () => {
    const { fire } = await running();
    await fire({ name: 'stage.changed', data: { stage: 'prototype' } });
    expect(screen.queryByText('Building in Data Studio…')).toBeNull();
    await waitFor(() => expect(buildButton().disabled).toBe(false));
  });

  it('does not tick a regenerated recipe with the previous run, nor show its result', async () => {
    const { fire } = await withRecipe();
    await fire({ name: 'run.started', data: { run_id: 'r_000000000001', node: 'execute' } });
    await fire(opEvent('s001', 'failed', 'sign-in expired'));
    await fire(finished('failed', null));
    expect(screen.getByText('The build failed.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }));
    await waitFor(() => expect(screen.queryByText('The build failed.')).toBeNull());
    await waitFor(() => expect(row('s001').dataset.status).toBe('pending'));
    expect(screen.queryByText('sign-in expired')).toBeNull();
  });

  it('says "Some ops failed" for a partial build with no counted failure', async () => {
    const { fire } = await withRecipe();
    await fire(finished('partial'));
    expect(screen.getByText('Some ops failed')).toBeTruthy();
  });

  it('announces the outcome in one live region', async () => {
    const { fire } = await withRecipe();
    expect(screen.getByRole('status').textContent).toBe('');
    await fire(finished('ok'));
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.getByRole('status').textContent).toContain('Your dashboard is in Data Studio.');
  });
});

const rect = (left: number, top: number, width: number, height: number) =>
  ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;

describe('Continue to build', () => {
  it('reports pending comments from the prototype stage', async () => {
    const onPendingChange = vi.fn();
    const build = await api.getBuild(fixtures.build.id);
    render(<PrototypeStage build={build} applying={false} commentsError={null} onPendingChange={onPendingChange} />);
    expect(onPendingChange).toHaveBeenLastCalledWith(0);
  });

  it('is disabled with a hint while comments are unapplied, and moves focus when toggled', async () => {
    render(
      <MemoryRouter initialEntries={[`/builds/${fixtures.build.id}`]}>
        <Routes>
          <Route path="/builds/:id" element={<WorkspaceShell />} />
        </Routes>
      </MemoryRouter>,
    );
    const next = (await screen.findByRole('button', { name: 'Continue to build' })) as HTMLButtonElement;
    expect(next.disabled).toBe(false);
    const frame = (await screen.findByTitle(/^Prototype of /)) as HTMLIFrameElement;
    const doc = frame.contentDocument!;
    doc.open();
    doc.write(fixtures.prototypeHtml);
    doc.close();
    const canvasEl = doc.getElementById('dss-canvas');
    if (canvasEl) canvasEl.getBoundingClientRect = () => rect(0, 0, 1200, 900);
    doc.querySelectorAll<HTMLElement>('[data-cid]').forEach((el) => {
      const px = (name: 'left' | 'top' | 'width' | 'height') => parseFloat(el.style[name]);
      el.getBoundingClientRect = () => rect(px('left'), px('top'), px('width'), px('height'));
    });
    fireEvent.load(frame);
    fireEvent.click(await screen.findByRole('button', { name: 'Comment on Revenue (scorecard)' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Comment' }), { target: { value: 'Make this bigger' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Continue to build' }) as HTMLButtonElement).disabled).toBe(true));
    const button = screen.getByRole('button', { name: 'Continue to build' });
    expect(screen.getByText('Apply or remove your comments first.')).toBeTruthy();
    expect(button.getAttribute('aria-describedby')).toBe(screen.getByText('Apply or remove your comments first.').id);
  });

  it('moves focus to the stage area when the build view opens and closes', async () => {
    render(
      <MemoryRouter initialEntries={[`/builds/${fixtures.build.id}`]}>
        <Routes>
          <Route path="/builds/:id" element={<WorkspaceShell />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Continue to build' }));
    await screen.findByRole('button', { name: 'Back to prototype' });
    expect(document.activeElement?.tagName).toBe('MAIN');
    (document.activeElement as HTMLElement).blur();
    fireEvent.click(screen.getByRole('button', { name: 'Back to prototype' }));
    await screen.findByRole('button', { name: 'Continue to build' });
    expect(document.activeElement?.tagName).toBe('MAIN');
  });
});

describe('reduceBuildRun', () => {
  const started: BuildEvent = { name: 'run.started', data: { run_id: 'r_000000000001', node: 'execute' } };

  it('run.started on build starts fresh and drops earlier ops', () => {
    const before = reduceBuildRun(reduceBuildRun(idleRun, started), opEvent('s001', 'failed', 'x'));
    expect(failedCount(before)).toBe(1);
    const again = reduceBuildRun(before, started);
    expect(again).toEqual({ running: true, ops: {}, finished: null, error: null, frame: null });
  });

  it('ignores runs of other nodes and unrelated events', () => {
    expect(reduceBuildRun(idleRun, { name: 'run.started', data: { run_id: 'r_000000000001', node: 'plan' } })).toBe(idleRun);
    expect(reduceBuildRun(idleRun, { name: 'ready', data: { build_id: 'b' } })).toBe(idleRun);
  });

  it('starts fresh on stage.changed to build only while not running', () => {
    const running = reduceBuildRun(idleRun, started);
    const withOp = reduceBuildRun(running, opEvent('s001', 'ok'));
    expect(reduceBuildRun(withOp, { name: 'stage.changed', data: { stage: 'build' } })).toBe(withOp);
    expect(reduceBuildRun(idleRun, { name: 'stage.changed', data: { stage: 'build' } }).running).toBe(true);
  });

  it('build.finished ends the run; run.finished error records the error', () => {
    const done = reduceBuildRun(reduceBuildRun(idleRun, started), finished('ok'));
    expect(done.running).toBe(false);
    expect(done.finished?.status).toBe('ok');
    const failed = reduceBuildRun(reduceBuildRun(idleRun, started), {
      name: 'run.finished',
      data: { run_id: 'r_000000000001', node: 'execute', status: 'error', error: 'It broke.' },
    });
    expect(failed).toMatchObject({ running: false, error: 'It broke.' });
  });
});
