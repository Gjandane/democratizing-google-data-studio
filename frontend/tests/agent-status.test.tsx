import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, httpApi } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import { ApiError, UPLOAD_LIMIT_BYTES, type AgentCheck, type Build, type BuildEvent, type JobTicket } from '../src/api/types';
import { SettingsModal } from '../src/features/settings/SettingsModal';
import { BuildStage } from '../src/features/workspace/build/BuildStage';
import { setupCommands } from '../src/features/workspace/build/setupCommand';
import { useBuildStream } from '../src/features/activity/useBuildStream';
import { ConnectStage } from '../src/features/workspace/connect/ConnectStage';
import { openMockBuildEvents } from '../src/mocks/events';
import { dropMockJob, expireMockJob, resetMockState, setMockEngine, setMockHosting } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => {
  resetMockState();
  sessionStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const noStream: OpenBuildEvents = () => () => {};

function fakeStream() {
  const handlers: StreamHandlers[] = [];
  const open: OpenBuildEvents = (_id, h) => {
    handlers.push(h);
    return () => {};
  };
  const fire = (event: BuildEvent) => act(() => handlers.forEach((h) => h.onEvent(event)));
  return { open, fire };
}

function BuildHolder({ initial }: { initial: Build }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, noStream);
  return <BuildStage build={build} run={chat.buildRun} />;
}

const buildButton = () => screen.getByRole('button', { name: 'Build in Data Studio' }) as HTMLButtonElement;

/** Renders the Build stage, waits for `ready` in the engine panel, and generates the recipe. */
async function renderBuild(ready: string | RegExp) {
  render(<BuildHolder initial={await api.getBuild(fixtures.build.id)} />);
  await screen.findByText(ready);
  fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
  await screen.findByRole('list', { name: 'Recipe' });
}

const agent = fixtures.engineStatus;

const CODE = 'K7QM-4XRT';
const POWERSHELL = `& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Gjandane/democratizing-google-data-studio/main/agent-setup/setup.ps1))) -Server ${window.location.origin} -Job ${CODE}`;
const BASH = `curl -fsSL https://raw.githubusercontent.com/Gjandane/democratizing-google-data-studio/main/agent-setup/setup.sh | bash -s -- --server ${window.location.origin} --job ${CODE}`;
const EXPIRED = 'That code expired. Build again for a new code.';
const LOST = 'The last build code was lost. Build again for a new code.';

function HostedHolder({ initial, open = openMockBuildEvents }: { initial: Build; open?: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, open);
  return <BuildStage build={build} run={chat.buildRun} />;
}

/** Renders the Build stage on the open link and generates the recipe. */
async function renderHosted(initial?: Build, open?: OpenBuildEvents) {
  setMockHosting('open');
  render(<HostedHolder initial={initial ?? (await api.getBuild(fixtures.build.id))} open={open} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Generate recipe' }));
  await screen.findByRole('list', { name: 'Recipe' });
}

const buildEnabled = () => waitFor(() => expect(buildButton().disabled).toBe(false));

/** Builds once and waits for the code panel. */
async function buildToWaiting() {
  await renderHosted();
  await buildEnabled();
  fireEvent.click(buildButton());
  await screen.findByText('Needs Google Chrome');
}

describe('hosted build (agent mode)', () => {
  it('Build is on with no agent or engine panel', async () => {
    await renderHosted();
    await buildEnabled();
    expect(screen.queryByRole('heading', { name: 'Build agent' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Data Studio engine' })).toBeNull();
    // The setup step (19.3) is the one Chrome line before the first Build.
    expect(screen.getAllByText('Needs Google Chrome')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Sign in to Google' })).toBeNull();
  });

  it('after Build: Chrome note, both setup commands with Copy, countdown and the share note', async () => {
    const writeText = vi.fn(async (_text: string) => {});
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    await buildToWaiting();
    expect(await screen.findByText('Waiting for your computer…')).toBeTruthy();
    expect(screen.getByText(CODE).tagName).toBe('CODE');

    const windows = screen.getByRole('tab', { name: 'Windows (PowerShell)' });
    expect(windows.getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText(POWERSHELL).tagName).toBe('CODE');
    expect(setupCommands(window.location.origin, 'job', CODE).powershell).toBe(POWERSHELL);
    expect(setupCommands(window.location.origin, 'job', CODE).bash).toBe(BASH);
    const unix = screen.getByRole('tab', { name: /macOS\/Linux/ });
    expect(unix.textContent).toContain('untested');
    expect(screen.getAllByRole('button', { name: 'Copy' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    await screen.findByRole('button', { name: 'Copied' });
    expect(writeText).toHaveBeenLastCalledWith(POWERSHELL);

    fireEvent.click(unix);
    expect(unix.getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText(BASH).tagName).toBe('CODE');
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    await waitFor(() => expect(writeText).toHaveBeenLastCalledWith(BASH));

    expect(screen.getByText(/^Code expires in (29|30):\d\d$/)).toBeTruthy();
    expect(screen.getByText('Your data is saved as a CSV that anyone with its private link can read, so your Data Studio account can open it.')).toBeTruthy();
  });

  it('the tabs follow the arrow keys', async () => {
    await buildToWaiting();
    const windows = screen.getByRole('tab', { name: 'Windows (PowerShell)' });
    const unix = screen.getByRole('tab', { name: /macOS\/Linux/ });
    windows.focus();
    expect(windows.tabIndex).toBe(0);
    expect(unix.tabIndex).toBe(-1);
    fireEvent.keyDown(windows, { key: 'ArrowRight' });
    expect(unix.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(unix);
    fireEvent.keyDown(unix, { key: 'Home' });
    expect(windows.getAttribute('aria-selected')).toBe('true');
  });

  it('no share note when the hosting does not share data', async () => {
    vi.spyOn(api, 'getHosting').mockResolvedValue({ ...fixtures.hostingOpen, share_data: false });
    await buildToWaiting();
    expect(screen.queryByText(/anyone with its private link/)).toBeNull();
  });

  describe('polling', () => {
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
    });
    afterEach(() => vi.useRealTimers());
    const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

    /** Builds on the open link with `getJob` spied; the mock's own events stay out of the way. */
    async function buildWithSpiedTicket(first: () => JobTicket) {
      const stream = fakeStream();
      const getJob = vi.spyOn(api, 'getJob').mockImplementation(async () => first());
      setMockHosting('open');
      const loading = api.getBuild(fixtures.build.id);
      await advance(10);
      render(<HostedHolder initial={await loading} open={stream.open} />);
      await advance(10);
      // findBy/waitFor wait on timers the test has faked: read the DOM after advancing.
      fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
      await advance(10);
      expect(buildButton().disabled).toBe(false);
      fireEvent.click(buildButton());
      await advance(10);
      stream.fire({ name: 'stage.changed', data: { stage: 'build' } });
      await advance(10);
      return getJob;
    }
    const farTicket = () => ({ ...fixtures.jobTicketWaiting, expires_at: new Date(Date.now() + 30 * 60_000).toISOString() });

    it('reads the ticket every 3 s while waiting and stops once it runs', async () => {
      const waiting = farTicket();
      let current: JobTicket = waiting;
      const getJob = await buildWithSpiedTicket(() => ({ ...current }));
      expect(screen.getByText('Needs Google Chrome')).toBeTruthy();
      const first = getJob.mock.calls.length;
      expect(first).toBeGreaterThan(0);

      await advance(3000);
      expect(getJob.mock.calls.length).toBe(first + 1);
      await advance(3000);
      expect(getJob.mock.calls.length).toBe(first + 2);

      current = { ...waiting, state: 'running', claimed_at: new Date().toISOString() };
      await advance(3000);
      expect(getJob.mock.calls.length).toBe(first + 3);
      expect(screen.getByText('Your computer claimed the build code. Building in Data Studio…')).toBeTruthy();
      expect(screen.queryByText(POWERSHELL)).toBeNull();
      await advance(12_000);
      expect(getJob.mock.calls.length).toBe(first + 3);
    });

    it('a failed read keeps the ticket and keeps polling', async () => {
      const waiting = farTicket();
      let calls = 0;
      const getJob = await buildWithSpiedTicket(() => {
        calls += 1;
        if (calls === 2) throw new ApiError(503, 'unavailable', 'Try again.');
        return { ...waiting };
      });
      const first = getJob.mock.calls.length;
      await advance(3000);
      await advance(3000);
      await advance(3000);
      expect(getJob.mock.calls.length).toBe(first + 3);
      expect(screen.getByText(POWERSHELL)).toBeTruthy();
    });

    it('the countdown ending shows the expired text before the poll does', async () => {
      const soon = new Date(Date.now() + 5000).toISOString();
      await buildWithSpiedTicket(() => ({ ...fixtures.jobTicketWaiting, expires_at: soon }));
      expect(screen.getByText(/^Code expires in 0:0\d$/)).toBeTruthy();
      await advance(2000);
      expect(screen.getByText(/^Code expires in 0:0\d$/)).toBeTruthy();
      await advance(3100);
      expect(screen.getByText(EXPIRED)).toBeTruthy();
      expect(screen.queryByText(POWERSHELL)).toBeNull();
    });
  });

  it('running shows the live op list from the stream, and the link when the build finishes', async () => {
    const stream = fakeStream();
    vi.spyOn(api, 'getJob').mockImplementation(async (id) => ({ ...fixtures.jobTicketRunning, build_id: id, code: CODE }));
    await renderHosted(undefined, stream.open);
    await buildEnabled();
    fireEvent.click(buildButton());
    stream.fire({ name: 'stage.changed', data: { stage: 'build' } });
    await screen.findByText('Your computer claimed the build code. Building in Data Studio…');
    expect(screen.queryByText(CODE)).toBeNull();
    const [first, second] = fixtures.recipe.ops;
    stream.fire({
      name: 'build.op',
      data: { event: 'op_finished', ts: '2026-10-18T10:00:00Z', op_id: first!.op_id, op: 'x', status: 'ok', message: '', screenshot: null, duration_ms: 10 },
    });
    expect(screen.getByText(`1 of ${fixtures.recipe.ops.length} ops done`)).toBeTruthy();
    stream.fire({
      name: 'build.op',
      data: { event: 'op_finished', ts: '2026-10-18T10:00:01Z', op_id: second!.op_id, op: 'x', status: 'ok', message: '', screenshot: null, duration_ms: 10 },
    });
    expect(screen.getByText(`2 of ${fixtures.recipe.ops.length} ops done`)).toBeTruthy();
    stream.fire({ name: 'build.finished', data: { status: 'ok', report_url: 'https://lookerstudio.google.com/reporting/abc', version: 1 } });
    stream.fire({ name: 'stage.changed', data: { stage: 'done' } });
    const link = await screen.findByRole('link', { name: /Open in Data Studio/ });
    expect(link.getAttribute('href')).toBe('https://lookerstudio.google.com/reporting/abc');
  });

  it('expired: tells the user to build again, Build is on, and the failed card stays out of the way', async () => {
    await buildToWaiting();
    const id = fixtures.build.id;
    act(() => expireMockJob(id));
    await screen.findByText(EXPIRED);
    expect(screen.queryByText(POWERSHELL)).toBeNull();
    expect(screen.queryByText('The build failed.')).toBeNull();
    await buildEnabled();
    // A new code replaces the message.
    fireEvent.click(buildButton());
    await screen.findByText('Needs Google Chrome');
    expect(screen.queryByText(EXPIRED)).toBeNull();
  });

  it('reopened with a running ticket, the panel shows the running state with the same build', async () => {
    const reopened = { ...(await api.getBuild(fixtures.build.id)), stage: 'build' as const };
    vi.spyOn(api, 'getJob').mockResolvedValue({ ...fixtures.jobTicketRunning, build_id: reopened.id });
    setMockHosting('open');
    render(<HostedHolder initial={reopened} open={noStream} />);
    expect(await screen.findByText('Your computer claimed the build code. Building in Data Studio…')).toBeTruthy();
    expect(screen.queryByText('Needs Google Chrome')).toBeNull();
  });

  it('reopened with a waiting ticket, the panel restores the same code', async () => {
    const reopened = { ...(await api.getBuild(fixtures.build.id)), stage: 'build' as const };
    const expires_at = new Date(Date.now() + 20 * 60_000).toISOString();
    vi.spyOn(api, 'getJob').mockResolvedValue({ ...fixtures.jobTicketWaiting, build_id: reopened.id, expires_at });
    setMockHosting('open');
    render(<HostedHolder initial={reopened} open={noStream} />);
    expect((await screen.findByText(POWERSHELL)).tagName).toBe('CODE');
    expect(screen.getByText(/^Code expires in (19|20):\d\d$/)).toBeTruthy();
  });

  it('a 404 job_not_found on reopen says the code was lost and Build is on', async () => {
    const reopened = { ...(await api.getBuild(fixtures.build.id)), stage: 'build' as const };
    setMockHosting('open');
    dropMockJob(reopened.id);
    render(<HostedHolder initial={reopened} open={noStream} />);
    await screen.findByText(LOST);
    // The build is in its build stage, so the recipe is fetched on its own.
    await screen.findByRole('list', { name: 'Recipe' });
    await buildEnabled();
    expect(screen.queryByText('Waiting for your computer…')).toBeNull();
    expect(screen.queryByText('Building in Data Studio…')).toBeNull();
  });

  it('a hosted failure shows the message without its code, and Build again', async () => {
    await renderHosted();
    setMockHosting('failed');
    await buildEnabled();
    fireEvent.click(buildButton());
    const message = await screen.findByText(/^The build agent stopped reporting\./, {}, { timeout: 6000 });
    expect(message.textContent).not.toContain('agent_timeout');
    expect(screen.getByText('The build failed.')).toBeTruthy();
    await waitFor(() => expect(buildButton().disabled).toBe(false), { timeout: 3000 });
  }, 12_000);

  it('reopened in the build stage, the panel restores the same code from the server', async () => {
    await buildToWaiting();
    cleanup();
    const reopened = await api.getBuild(fixtures.build.id);
    expect(reopened.stage).toBe('build');
    render(<HostedHolder initial={reopened} />);
    expect((await screen.findByText(POWERSHELL)).tagName).toBe('CODE');
    expect(screen.getByText(CODE)).toBeTruthy();
  });

  it('a second Build on a busy ticket (409 engine_busy) shows the existing code', async () => {
    await buildToWaiting();
    cleanup();
    const reopened = { ...(await api.getBuild(fixtures.build.id)), stage: 'prototype' as const };
    render(<HostedHolder initial={reopened} open={noStream} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Generate recipe' }));
    await screen.findByRole('list', { name: 'Recipe' });
    await buildEnabled();
    fireEvent.click(buildButton());
    expect(await screen.findByText(POWERSHELL)).toBeTruthy();
  });

  it('never writes the code to storage, the URL or the console', async () => {
    const sinks = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    await buildToWaiting();
    expect(screen.getByText(CODE)).toBeTruthy();
    const logged = JSON.stringify([...sinks.flatMap((s) => s.mock.calls), ...setItem.mock.calls]);
    expect(logged).not.toContain(CODE);
    expect(window.location.href).not.toContain(CODE);
    expect(JSON.stringify({ ...localStorage })).not.toContain(CODE);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(CODE);
  });
});

const SETUP_STEPS = [
  'Pick your system and copy the command.',
  'Paste it into PowerShell (Windows: Start menu, type PowerShell) or Terminal (macOS/Linux) and press Enter.',
  "If a Chrome window opens, sign in to Google and accept Data Studio's terms if it asks.",
  'Keep this page open. It shows Agent ready when the check passes.',
];
const AGENT_NOTE = 'To continue, the build agent runs this build on your computer, in your own Chrome. This step makes no AI calls, so it uses no AI tokens.';
const PASTE_LINE =
  'Paste it into PowerShell (Windows) or Terminal (macOS/Linux) and press Enter. On a computer without the agent, the first run installs it and asks you to sign in to Google.';
/** `a` comes before `b` in the document. */
const before = (a: Element, b: Element) => expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

describe('Build-stage agent note and job paste line (agent mode)', () => {
  it('above the setup step before the first Build', async () => {
    await renderHosted();
    const note = screen.getByText(AGENT_NOTE);
    before(note, screen.getByRole('heading', { name: 'Set up this computer' }));
    expect(screen.getAllByText(AGENT_NOTE)).toHaveLength(1);
  });

  it('above the job panel while waiting, with the paste line instead of the old one', async () => {
    await buildToWaiting();
    before(screen.getByText(AGENT_NOTE), screen.getByRole('heading', { name: 'Build on your computer' }));
    expect(screen.getByText(PASTE_LINE)).toBeTruthy();
    expect(screen.queryByText('Run this in a terminal on the computer signed in to Data Studio.')).toBeNull();
  });

  it('above the running job; gone once the build is done', async () => {
    const stream = fakeStream();
    vi.spyOn(api, 'getJob').mockImplementation(async (id) => ({ ...fixtures.jobTicketRunning, build_id: id, code: CODE }));
    await renderHosted(undefined, stream.open);
    await buildEnabled();
    fireEvent.click(buildButton());
    stream.fire({ name: 'stage.changed', data: { stage: 'build' } });
    const running = await screen.findByText('Your computer claimed the build code. Building in Data Studio…');
    before(screen.getByText(AGENT_NOTE), running);
    stream.fire({ name: 'build.finished', data: { status: 'ok', report_url: 'https://lookerstudio.google.com/reporting/abc', version: 1 } });
    stream.fire({ name: 'stage.changed', data: { stage: 'done' } });
    await screen.findByRole('link', { name: /Open in Data Studio/ });
    expect(screen.queryByText(AGENT_NOTE)).toBeNull();
  });

  it('after an expired code', async () => {
    await buildToWaiting();
    act(() => expireMockJob(fixtures.build.id));
    const expired = await screen.findByText(EXPIRED);
    before(screen.getByText(AGENT_NOTE), expired);
  });

  it('after a failed run', async () => {
    await renderHosted();
    setMockHosting('failed');
    await buildEnabled();
    fireEvent.click(buildButton());
    await screen.findByText('The build failed.', {}, { timeout: 6000 });
    expect(screen.getByText(AGENT_NOTE)).toBeTruthy();
  }, 12_000);

  it('local mode: no note', async () => {
    setMockEngine({ signed_in: false });
    await renderBuild('Not signed in to Google');
    expect(screen.queryByText(AGENT_NOTE)).toBeNull();
    expect(screen.queryByRole('list', { name: 'Steps' })).toBeNull();
  });
});

const CHECK_CODE = 'P3WN-8HJD';
const CHECK_POWERSHELL = `& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Gjandane/democratizing-google-data-studio/main/agent-setup/setup.ps1))) -Server ${window.location.origin} -Check ${CHECK_CODE}`;
const CHECK_BASH = `curl -fsSL https://raw.githubusercontent.com/Gjandane/democratizing-google-data-studio/main/agent-setup/setup.sh | bash -s -- --server ${window.location.origin} --check ${CHECK_CODE}`;

/** A check in `state`, expiring in 30 min (the fixtures' own dates are past). */
const checkIn = (state: AgentCheck['state'], extra: Partial<AgentCheck> = {}): AgentCheck => {
  const base =
    state === 'passed' ? fixtures.agentCheckPassed
    : state === 'failed' ? fixtures.agentCheckFailed
    : { ...fixtures.agentCheckWaiting, state };
  return { ...base, expires_at: new Date(Date.now() + 30 * 60_000).toISOString(), ...extra };
};

describe('setup step with the agent connection check (agent mode)', () => {
  it('shows the Chrome line and both check commands with Copy, equal to conventions 1.7 with -Check / --check', async () => {
    vi.spyOn(api, 'createAgentCheck').mockResolvedValue(checkIn('waiting'));
    await renderHosted();
    expect(screen.getByRole('heading', { name: 'Set up this computer' })).toBeTruthy();
    expect(screen.getByText('Needs Google Chrome')).toBeTruthy();
    expect(screen.getByText(CHECK_CODE).tagName).toBe('CODE');
    expect(setupCommands(window.location.origin, 'check', CHECK_CODE)).toEqual({ powershell: CHECK_POWERSHELL, bash: CHECK_BASH });
    const unix = screen.getByRole('tab', { name: /macOS\/Linux/ });
    expect(unix.textContent).toContain('untested');
    expect(screen.getByRole('tab', { name: 'Windows (PowerShell)' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText(CHECK_POWERSHELL).tagName).toBe('CODE');
    expect(screen.getAllByRole('button', { name: 'Copy' })).toHaveLength(1);
    fireEvent.click(unix);
    expect(screen.getByText(CHECK_BASH).tagName).toBe('CODE');
    expect(screen.getAllByRole('button', { name: 'Copy' })).toHaveLength(1);
    expect(screen.getByText(/^Code expires in (29|30):\d\d$/)).toBeTruthy();
    expect(screen.getByText('Already set up? Build in Data Studio.')).toBeTruthy();
  });

  it('shows the four how-to steps instead of the old terminal line', async () => {
    vi.spyOn(api, 'createAgentCheck').mockResolvedValue(checkIn('waiting'));
    await renderHosted();
    const steps = within(screen.getByRole('list', { name: 'Steps' })).getAllByRole('listitem');
    expect(steps.map((li) => li.textContent)).toEqual(SETUP_STEPS);
    expect(screen.queryByText(/^Run this once in a terminal/)).toBeNull();
  });

  it('local mode: no setup step', async () => {
    setMockEngine({ signed_in: false });
    await renderBuild('Not signed in to Google');
    expect(screen.queryByRole('heading', { name: 'Set up this computer' })).toBeNull();
    expect(screen.queryByText('Agent ready on this computer')).toBeNull();
  });

  it.each(['waiting', 'passed', 'failed', 'expired'] as const)('Build in Data Studio stays enabled with a %s check', async (state) => {
    vi.spyOn(api, 'createAgentCheck').mockResolvedValue(checkIn(state));
    await renderHosted();
    await buildEnabled();
    expect(screen.getByRole('heading', { name: 'Set up this computer' })).toBeTruthy();
  });

  describe('check states', () => {
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
    });
    afterEach(() => vi.useRealTimers());
    const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

    /** Opens the Build stage on the open link with the check calls spied; time stands still. */
    async function openSetup(create: () => AgentCheck, read?: () => AgentCheck) {
      const createSpy = vi.spyOn(api, 'createAgentCheck').mockImplementation(async () => create());
      const readSpy = vi.spyOn(api, 'getAgentCheck').mockImplementation(async () => (read ?? create)());
      setMockHosting('open');
      const loading = api.getBuild(fixtures.build.id);
      await advance(10);
      const build = await loading;
      render(<HostedHolder initial={build} open={noStream} />);
      await advance(0);
      return { createSpy, readSpy, build };
    }

    it('reads the check every 3 s while waiting and stops on any other state', async () => {
      let current = checkIn('waiting');
      const { createSpy, readSpy } = await openSetup(() => current);
      expect(createSpy).toHaveBeenCalledTimes(1);
      expect(readSpy).toHaveBeenCalledTimes(0);
      await advance(2999);
      expect(readSpy).toHaveBeenCalledTimes(0);
      await advance(1);
      expect(readSpy).toHaveBeenCalledTimes(1);
      await advance(3000);
      expect(readSpy).toHaveBeenCalledTimes(2);
      current = checkIn('passed');
      await advance(3000);
      expect(readSpy).toHaveBeenCalledTimes(3);
      expect(screen.getAllByText('Agent ready on this computer').length).toBeGreaterThan(0);
      await advance(30000);
      expect(readSpy).toHaveBeenCalledTimes(3);
    });

    it('passed: four items ticked, and sessionStorage holds only a boolean, never the code', async () => {
      let current = checkIn('waiting');
      const { createSpy, build } = await openSetup(() => current);
      current = checkIn('passed');
      await advance(3000);
      const items = screen.getAllByRole('listitem');
      expect(items.map((li) => li.textContent)).toEqual(['Server reached: ok', 'Versions match: ok', 'Chrome running: ok', 'Signed in to Google: ok']);
      expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull();
      expect(Object.fromEntries(Object.entries(sessionStorage))).toEqual({ 'dss.agentReady': '1' });
      expect(JSON.stringify(Object.entries(sessionStorage))).not.toContain(CHECK_CODE);
      cleanup();

      // A reload: the step folds to one line and asks for no new code.
      render(<HostedHolder initial={build} open={noStream} />);
      await advance(10);
      expect(createSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByText('Agent ready on this computer')).toBeTruthy();
      expect(screen.queryByRole('heading', { name: 'Set up this computer' })).toBeNull();
      expect(screen.queryByText(CHECK_CODE)).toBeNull();
    });

    it('failed: names each failed item with its fix; Check again asks for a new code', async () => {
      let n = 0;
      const { createSpy } = await openSetup(
        () => (n++ === 0 ? checkIn('waiting') : checkIn('waiting', { check_id: 'c_00000000000b', code: 'QWER-2345' })),
        () => checkIn('failed', { result: { agent_version: '0.1.0', api_version_ok: false, chrome_running: false, signed_in: false } }),
      );
      await advance(3000);
      const items = screen.getAllByRole('listitem').map((li) => li.textContent);
      expect(items).toEqual([
        'Server reached: ok',
        'Versions match: failedRerun the setup command with -Update (--update on macOS/Linux).',
        'Chrome running: failedStart Google Chrome with the agent, then check again.',
        "Signed in to Google: failedSign in to Google in the agent's Chrome window, then check again.",
      ]);
      expect(sessionStorage.getItem('dss.agentReady')).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
      await advance(0);
      expect(createSpy).toHaveBeenCalledTimes(2);
      expect(screen.getByText('QWER-2345')).toBeTruthy();
    });

    it('the folded line\'s Check again asks for a new code and keeps focus off body', async () => {
      sessionStorage.setItem('dss.agentReady', '1');
      const { createSpy } = await openSetup(() => checkIn('waiting', { code: 'QWER-2345' }));
      expect(createSpy).toHaveBeenCalledTimes(0);
      const again = screen.getByRole('button', { name: 'Check again' });
      again.focus();
      fireEvent.click(again);
      expect(document.activeElement).not.toBe(document.body);
      await advance(0);
      expect(createSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByText('QWER-2345')).toBeTruthy();
      expect(document.activeElement).toBe(screen.getByRole('tab', { name: 'Windows (PowerShell)' }));
    });

    it('failed with only the sign-in missing says to sign in to the agent\'s Chrome window', async () => {
      await openSetup(() => checkIn('failed'));
      const items = screen.getAllByRole('listitem').map((li) => li.textContent);
      expect(items[1]).toBe('Versions match: ok');
      expect(items[3]).toBe("Signed in to Google: failedSign in to Google in the agent's Chrome window, then check again.");
    });

    it('expired: offers a new code', async () => {
      let n = 0;
      const { createSpy } = await openSetup(() => (n++ === 0 ? checkIn('expired') : checkIn('waiting', { code: 'QWER-2345' })));
      expect(screen.getByText('That check code expired.')).toBeTruthy();
      fireEvent.click(screen.getByRole('button', { name: 'Get a new code' }));
      await advance(0);
      expect(createSpy).toHaveBeenCalledTimes(2);
      expect(screen.getByText('QWER-2345')).toBeTruthy();
    });

    it('a 404 on read counts as expired and stops the polling', async () => {
      const { readSpy } = await openSetup(
        () => checkIn('waiting'),
        () => {
          throw new ApiError(404, 'check_not_found', 'gone');
        },
      );
      await advance(3000);
      expect(readSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByText('That check code expired.')).toBeTruthy();
      await advance(10000);
      expect(readSpy).toHaveBeenCalledTimes(1);
    });

    it('a code that runs out locally counts as expired', async () => {
      await openSetup(() => checkIn('waiting', { expires_at: new Date(Date.now() + 2000).toISOString() }));
      await advance(2100);
      expect(screen.getByText('That check code expired.')).toBeTruthy();
    });

    it('a failed read keeps the last check and tries again', async () => {
      let fail = true;
      const { readSpy } = await openSetup(
        () => checkIn('waiting'),
        () => {
          if (fail) throw new ApiError(500, 'server_error', 'down');
          return checkIn('passed');
        },
      );
      await advance(3000);
      expect(screen.getByText(CHECK_CODE)).toBeTruthy();
      fail = false;
      await advance(3000);
      expect(readSpy).toHaveBeenCalledTimes(2);
      expect(screen.getAllByRole('listitem')).toHaveLength(4);
    });

    it('a failed create says so and offers Try again', async () => {
      vi.spyOn(api, 'createAgentCheck').mockRejectedValueOnce(new ApiError(500, 'server_error', 'down')).mockResolvedValue(checkIn('waiting'));
      setMockHosting('open');
      const loading = api.getBuild(fixtures.build.id);
      await advance(10);
      render(<HostedHolder initial={await loading} open={noStream} />);
      await advance(0);
      expect(screen.getByRole('alert').textContent).toBe("Couldn't get a check code. Try again.");
      fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
      await advance(0);
      expect(screen.getByText(CHECK_CODE)).toBeTruthy();
    });
  });
});

describe('local mode build', () => {
  it('still shows the sign-in button and no job panel', async () => {
    setMockEngine({ signed_in: false });
    await renderBuild('Not signed in to Google');
    expect(screen.getByRole('heading', { name: 'Data Studio engine' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sign in to Google' })).toBeTruthy();
    expect(screen.queryByText(/Build agent/)).toBeNull();
    expect(screen.getByText('Sign in to Google to build.')).toBeTruthy();
    expect(screen.queryByText('Needs Google Chrome')).toBeNull();
  });
});

describe('settings locked by the deployment', () => {
  it('403 settings_locked locks only the Google Cloud tab fields, and a later Models save succeeds', async () => {
    setMockEngine(agent);
    const update = vi.spyOn(api, 'updateSettings');
    render(<SettingsModal open onClose={() => {}} onSaved={() => {}} />);
    await screen.findByRole('list', { name: 'Stages' });
    // A model change and a GCP change go together: the hosted app refuses the whole save.
    const brief = screen.getByRole('button', { name: /^HTML brief / });
    fireEvent.click(brief);
    fireEvent.change(within(screen.getByRole('region', { name: 'HTML brief' })).getByLabelText('Output tokens'), { target: { value: '40000' } });
    fireEvent.click(screen.getByRole('tab', { name: 'Google Cloud' }));
    const project = (await screen.findByLabelText('GCP project')) as HTMLInputElement;
    fireEvent.change(project, { target: { value: 'other-project' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await screen.findByText(/The hosted app fixes the API key and Google Cloud settings\./);
    await expect(update.mock.results[0]!.value).rejects.toMatchObject({ status: 403, code: 'settings_locked' });
    expect(screen.getByText(/Nothing was saved: .* Save again to keep your model changes\./)).toBeTruthy();

    for (const label of ['GCP project', 'BigQuery dataset', 'BigQuery location', 'GCS bucket', 'Google API key']) {
      const input = screen.getByLabelText(label) as HTMLInputElement;
      expect(input.disabled, label).toBe(true);
    }
    expect((screen.getByLabelText('GCP project') as HTMLInputElement).value).toBe(fixtures.settings.gcp_project_id);
    expect(screen.getAllByText('Fixed by the deployment.').length).toBe(5);

    // The Models tab stays editable and keeps the change; saving it alone goes through.
    fireEvent.click(screen.getByRole('tab', { name: 'Models' }));
    const region = screen.getByRole('region', { name: 'HTML brief' });
    const output = within(region).getByLabelText('Output tokens') as HTMLInputElement;
    expect(output.disabled).toBe(false);
    expect(output.value).toBe('40000');
    for (const el of within(region).getAllByRole('combobox')) expect((el as HTMLSelectElement).disabled).toBe(false);
    expect((screen.getByLabelText('Fallback model') as HTMLSelectElement).disabled).toBe(false);
    const save = screen.getByRole('button', { name: 'Save settings' }) as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await screen.findByText('Settings saved.');
    expect(update).toHaveBeenCalledTimes(2);
    expect(update.mock.calls[1]![0]).toEqual({ stages: { html_brief: { output_tokens: 40000 } } });
    await expect(update.mock.results[1]!.value).resolves.toMatchObject({ stages: { html_brief: { output_tokens: 40000 } } });
    expect(save.disabled).toBe(true);
  });
});

describe('32 MB upload limit', () => {
  const big = () => {
    const file = new File(['a,b\n1,2'], 'huge.csv', { type: 'text/csv' });
    Object.defineProperty(file, 'size', { value: UPLOAD_LIMIT_BYTES + 1 });
    return file;
  };

  it('refuses a file over 32 MB before anything is sent', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(httpApi.uploadSources('b_3f9a0c12d4e5', [big()])).rejects.toMatchObject({
      status: 413,
      message: "Files over 32 MB can't be uploaded to the hosted app.",
    });
    await expect(httpApi.uploadStyleImages('b_3f9a0c12d4e5', [big()])).rejects.toMatchObject({ status: 413 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('maps any 413 (an HTML page from Cloud Run) to the 32 MB message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html><body>413 Request Entity Too Large</body></html>', { status: 413, headers: { 'Content-Type': 'text/html' } })));
    const small = new File(['a,b\n1,2'], 'small.csv', { type: 'text/csv' });
    await expect(httpApi.uploadSources('b_3f9a0c12d4e5', [small])).rejects.toMatchObject({
      status: 413,
      code: 'payload_too_large',
      message: "Files over 32 MB can't be uploaded to the hosted app.",
    });
  });

  it('Connect shows the 32 MB message and adds nothing', async () => {
    const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
    function Holder() {
      const [current, setCurrent] = useState(build);
      return <ConnectStage build={current} onBuildChange={setCurrent} />;
    }
    render(<Holder />);
    fireEvent.drop(screen.getByRole('region', { name: 'Upload CSV files' }), { dataTransfer: { files: [big()] } });
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Files over 32 MB can't be uploaded to the hosted app.");
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
