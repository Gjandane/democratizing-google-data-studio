import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, httpApi } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import { ApiError, UPLOAD_LIMIT_BYTES, type Build, type BuildEvent, type JobTicket } from '../src/api/types';
import { SettingsModal } from '../src/features/settings/SettingsModal';
import { BuildStage } from '../src/features/workspace/build/BuildStage';
import { setupCommands } from '../src/features/workspace/build/setupCommand';
import { useBuildStream } from '../src/features/activity/useBuildStream';
import { ConnectStage } from '../src/features/workspace/connect/ConnectStage';
import { openMockBuildEvents } from '../src/mocks/events';
import { dropMockJob, expireMockJob, resetMockState, setMockEngine, setMockHosting } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
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
    expect(screen.queryByText('Needs Google Chrome')).toBeNull();
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
