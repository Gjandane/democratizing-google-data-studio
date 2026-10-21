import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import { ApiError, type Build, type BuildEvent } from '../src/api/types';
import { BuildStage } from '../src/features/workspace/build/BuildStage';
import { idleRun, reduceBuildRun } from '../src/features/workspace/build/buildRun';
import { useBuildStream } from '../src/features/activity/useBuildStream';
import { ConnectStage } from '../src/features/workspace/connect/ConnectStage';
import { PrototypeStage } from '../src/features/workspace/prototype/PrototypeStage';
import { resetStretchAvailability } from '../src/features/workspace/stretch';
import { resetMockState } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => {
  resetMockState();
  resetStretchAvailability();
});
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

const started = (node: string, run_id: string): BuildEvent => ({ name: 'run.started', data: { run_id, node } });
const done = (node: string, run_id: string, error: string | null = null): BuildEvent => ({
  name: 'run.finished',
  data: { run_id, node, status: error ? 'error' : 'ok', error },
});

function ConnectHolder({ initial, open }: { initial: Build; open: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, open);
  return <ConnectStage build={build} onBuildChange={setBuild} stretchRuns={chat.stretchRuns} />;
}

function ProtoHolder({ initial, open }: { initial: Build; open: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, open);
  return <PrototypeStage build={build} applying={chat.applying} commentsError={chat.commentsError} stretchRuns={chat.stretchRuns} />;
}

function BuildHolder({ initial, open }: { initial: Build; open: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, open);
  return <BuildStage build={build} run={chat.buildRun} />;
}

async function connect(mode: 'data' | 'research' = 'data') {
  const stream = fakeStream();
  const build = { ...(await api.getBuild(fixtures.build.id)), mode, stage: 'connect' as const };
  render(<ConnectHolder initial={build} open={stream.open} />);
  return { build, ...stream };
}

async function prototype() {
  const stream = fakeStream();
  const build = await api.getBuild(fixtures.build.id);
  render(<ProtoHolder initial={build} open={stream.open} />);
  return { build, ...stream };
}

const off = (el: HTMLElement) => (el as HTMLButtonElement).disabled;
const accepted = (run_id: string) => Promise.resolve({ run_id });

// Former style upload assertions now cover the required reference route in references.test.tsx.

describe('Research prompt', () => {
  it('is hidden in data mode', async () => {
    await connect('data');
    expect(screen.queryByLabelText('What should the research cover?')).toBeNull();
  });

  it('posts the prompt in research mode and follows the run', async () => {
    const { build, fire } = await connect('research');
    const spy = vi.spyOn(api, 'startResearch').mockReturnValue(accepted('r_res'));
    const start = screen.getByRole('button', { name: 'Start research' });
    expect(off(start)).toBe(true);
    fireEvent.change(screen.getByLabelText('What should the research cover?'), { target: { value: '  EV market in Europe ' } });
    expect(off(start)).toBe(false);
    fireEvent.click(start);
    await waitFor(() => expect(spy).toHaveBeenCalledWith(build.id, 'EV market in Europe'));
    await screen.findByText('Researching…');
    await fire(started('research', 'r_res'));
    await fire(done('research', 'r_res'));
    await screen.findByText('Research done. New sources are in the table below.');
    expect((screen.getByLabelText('What should the research cover?') as HTMLTextAreaElement).value).toBe('  EV market in Europe ');
  });

  it('shows an error when the run fails', async () => {
    const { fire } = await connect('research');
    vi.spyOn(api, 'startResearch').mockReturnValue(accepted('r_res'));
    fireEvent.change(screen.getByLabelText('What should the research cover?'), { target: { value: 'topic' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start research' }));
    await screen.findByText('Researching…');
    await fire(started('research', 'r_res'));
    await fire(done('research', 'r_res', 'Search failed. Try a narrower prompt.'));
    expect((await screen.findByRole('alert')).textContent).toBe('Search failed. Try a narrower prompt.');
  });
});

describe('UX audit', () => {
  it('posts the audit and shows Auditing then done', async () => {
    const { build, fire } = await prototype();
    const spy = vi.spyOn(api, 'runAudit').mockReturnValue(accepted('r_aud'));
    fireEvent.click(screen.getByRole('button', { name: 'Run UX audit' }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(build.id));
    await screen.findByText('Auditing…');
    expect(off(screen.getByRole('button', { name: 'Run UX audit' }))).toBe(true);
    await fire(started('ux_audit', 'r_aud'));
    await fire(done('ux_audit', 'r_aud'));
    await screen.findByText('Audit done. The findings are in the activity column.');
    expect(off(screen.getByRole('button', { name: 'Run UX audit' }))).toBe(false);
  });

  it('follows a newer run from another tab instead of waiting on its own forever', async () => {
    const { fire } = await prototype();
    await fire(started('ux_audit', 'r_old'));
    await fire(done('ux_audit', 'r_old'));
    // Accepted, but its run.started never arrives; another tab's run takes the node over.
    vi.spyOn(api, 'runAudit').mockReturnValue(accepted('r_mine'));
    fireEvent.click(screen.getByRole('button', { name: 'Run UX audit' }));
    await screen.findByText('Auditing…');
    await fire(started('ux_audit', 'r_other'));
    await fire(done('ux_audit', 'r_other'));
    await screen.findByText('Audit done. The findings are in the activity column.');
    expect(off(screen.getByRole('button', { name: 'Run UX audit' }))).toBe(false);
  });

  it('puts focus back on the button when the audit ends', async () => {
    const { fire } = await prototype();
    vi.spyOn(api, 'runAudit').mockReturnValue(accepted('r_aud'));
    const button = screen.getByRole('button', { name: 'Run UX audit' });
    button.focus();
    fireEvent.click(button);
    await screen.findByText('Auditing…');
    button.blur();
    await fire(started('ux_audit', 'r_aud'));
    await fire(done('ux_audit', 'r_aud'));
    await screen.findByText('Audit done. The findings are in the activity column.');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Run UX audit' }));
  });

  it('is disabled while comments are being applied', async () => {
    const { fire } = await prototype();
    await fire(started('revise', 'r_c'));
    expect(off(screen.getByRole('button', { name: 'Run UX audit' }))).toBe(true);
    await fire(done('revise', 'r_c'));
    expect(off(screen.getByRole('button', { name: 'Run UX audit' }))).toBe(false);
  });

  it('shows the run error', async () => {
    const { fire } = await prototype();
    vi.spyOn(api, 'runAudit').mockReturnValue(accepted('r_aud'));
    fireEvent.click(screen.getByRole('button', { name: 'Run UX audit' }));
    await screen.findByText('Auditing…');
    await fire(started('ux_audit', 'r_aud'));
    await fire(done('ux_audit', 'r_aud', 'The audit stopped. Run it again.'));
    expect((await screen.findByRole('alert')).textContent).toBe('The audit stopped. Run it again.');
  });
});

describe('Missing stretch routes', () => {
  const missing = () => new ApiError(404, 'http_error', 'Not found');

  // Required references keep their 404 visible; references.test.tsx covers this replacement.

  it('hides the research control on 404 without an error', async () => {
    await connect('research');
    vi.spyOn(api, 'startResearch').mockRejectedValue(missing());
    fireEvent.change(screen.getByLabelText('What should the research cover?'), { target: { value: 'topic' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start research' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Start research' })).toBeNull());
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('hides the audit control on 404 without an error', async () => {
    await prototype();
    vi.spyOn(api, 'runAudit').mockRejectedValue(missing());
    fireEvent.click(screen.getByRole('button', { name: 'Run UX audit' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Run UX audit' })).toBeNull());
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('stays hidden for a later mount once a route answered 404', async () => {
    await prototype();
    vi.spyOn(api, 'runAudit').mockRejectedValue(missing());
    fireEvent.click(screen.getByRole('button', { name: 'Run UX audit' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Run UX audit' })).toBeNull());
    cleanup();
    await prototype();
    expect(screen.queryByRole('button', { name: 'Run UX audit' })).toBeNull();
  });

  it('shows build_not_found as an error instead of hiding', async () => {
    await prototype();
    vi.spyOn(api, 'runAudit').mockRejectedValue(new ApiError(404, 'build_not_found', 'This build no longer exists. Open another one from History.'));
    fireEvent.click(screen.getByRole('button', { name: 'Run UX audit' }));
    expect((await screen.findByRole('alert')).textContent).toContain('no longer exists');
    expect(screen.getByRole('button', { name: 'Run UX audit' })).toBeTruthy();
  });
});

describe('Live view', () => {
  const frame = (data: string): BuildEvent => ({ name: 'build.frame', data: { data } });
  const live = { name: 'Live view of the build in Data Studio' };

  it('shows the latest build.frame image and replaces it on the next one', async () => {
    const stream = fakeStream();
    const build = await api.getBuild(fixtures.build.id);
    render(<BuildHolder initial={build} open={stream.open} />);
    await screen.findByText(/Signed in to Google|Not signed in to Google/);
    expect(screen.queryByRole('img', live)).toBeNull();
    await stream.fire(frame('AAAA'));
    const img = screen.getByRole('img', live) as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('data:image/jpeg;base64,AAAA');
    expect(screen.getByRole('heading', { name: 'Live view' })).toBeTruthy();
    await stream.fire(frame('BBBB'));
    expect(screen.getAllByRole('img', live)).toHaveLength(1);
    expect(screen.getByRole('img', live).getAttribute('src')).toBe('data:image/jpeg;base64,BBBB');
  });

  it('reduceBuildRun keeps the frame and clears it when a build run starts', () => {
    const withFrame = reduceBuildRun(idleRun, frame('AAAA'));
    expect(withFrame.frame).toBe('AAAA');
    expect(reduceBuildRun(withFrame, { name: 'run.started', data: { run_id: 'r1', node: 'execute' } }).frame).toBeNull();
    expect(reduceBuildRun(withFrame, { name: 'run.started', data: { run_id: 'r1', node: 'plan' } }).frame).toBe('AAAA');
  });
});
