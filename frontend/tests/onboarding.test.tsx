import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigationType } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { api } from '../src/api/client';
import { ApiError, type AgentCheck, type Hosting } from '../src/api/types';
import { setupCommands } from '../src/features/workspace/build/setupCommand';
import { resetMockState, setMockHosting } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

const KEY = 'dss.onboardingSeen';

const H1 = 'Turn your data into a Google Data Studio dashboard';

const SHOTS = [
  {
    file: 'context.webp',
    title: 'Review the context',
    caption: 'Confirm the KPIs and questions drafted from your data.',
    alt: 'The Context stage with KPI cards to confirm',
  },
  {
    file: 'prototype.webp',
    title: 'Comment on the prototype',
    caption: 'Click any chart to leave a comment, then apply them all at once.',
    alt: 'The Prototype stage with numbered comment pins',
  },
  {
    file: 'build.webp',
    title: 'Watch the build',
    caption: 'Each step ticks off live while the agent builds the report.',
    alt: 'The Build stage with recipe steps ticking off',
  },
  {
    file: 'done.webp',
    title: 'Open your report',
    caption: 'The finished dashboard opens in your own Data Studio.',
    alt: 'The Done stage with the link to the report in Data Studio',
  },
];

const STEP_BODIES = [
  'Upload a CSV or a screenshot, then confirm each stage. Nothing is built until you say so.',
  'Building runs in Google Chrome on your computer, so the report is saved in your own Data Studio account. One copied command installs the build agent (a small helper and this app) and asks you to sign in to Google once in its own Chrome window. The first run takes a few minutes.',
  'At Build you get a code that works for 30 minutes and one command to paste into a terminal. The finished report opens in Data Studio.',
];

const CSV_NOTE = "Your build's data is saved as a CSV that anyone with its private link can read.";

beforeEach(() => {
  resetMockState();
  window.localStorage.clear();
  window.sessionStorage.clear();
  document.title = 'Data Studio builder';
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

function Where() {
  return (
    <span data-testid="where" data-nav={useNavigationType()}>
      {useLocation().pathname}
    </span>
  );
}

function renderApp(path = '/') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Where />
    </MemoryRouter>,
  );
}

const where = () => screen.getByTestId('where').textContent;
const landingHeading = () => screen.findByRole('heading', { level: 1, name: H1 });
const historyHeading = () => screen.findByRole('heading', { level: 1, name: 'Dashboards' });
const proceed = () => screen.getByRole('button', { name: 'Proceed to your dashboards' });

function blockStorage() {
  const blocked = () => {
    throw new DOMException('blocked', 'SecurityError');
  };
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(blocked);
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(blocked);
  vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(blocked);
}

describe('First visit in agent mode', () => {
  it('shows only the loading panel while hosting is pending, with the builds already requested, then lands on /welcome', async () => {
    let resolve: (hosting: Hosting) => void = () => {};
    vi.spyOn(api, 'getHosting').mockReturnValue(new Promise<Hosting>((r) => (resolve = r)));
    const list = vi.spyOn(api, 'listBuilds');
    renderApp('/');

    expect(await screen.findByText('Loading dashboards…')).toBeTruthy();
    await waitFor(() => expect(list).toHaveBeenCalled());
    // Let the builds answer: the header and list still wait on hosting.
    await act(async () => {
      await list.mock.results[0]?.value;
    });
    expect(screen.getByText('Loading dashboards…')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Dashboards' })).toBeNull();
    expect(screen.queryByRole('list', { name: 'Dashboards' })).toBeNull();
    expect(screen.queryByRole('heading', { name: H1 })).toBeNull();
    expect(where()).toBe('/');

    await act(async () => resolve(fixtures.hostingOpen));
    await landingHeading();
    expect(where()).toBe('/welcome');
    // Replace, so Back doesn't bounce to `/`.
    expect(screen.getByTestId('where').dataset.nav).toBe('REPLACE');
    expect(screen.queryByRole('heading', { name: 'Dashboards' })).toBeNull();
  });

  it('shows only the loading panel on /welcome while hosting is pending', async () => {
    vi.spyOn(api, 'getHosting').mockReturnValue(new Promise<Hosting>(() => {}));
    renderApp('/welcome');
    expect(await screen.findByText('Loading dashboards…')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: H1 })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Dashboards' })).toBeNull();
  });

  it('shows the hero, the four screenshots and How it works verbatim', async () => {
    setMockHosting('open');
    renderApp('/');
    await landingHeading();

    expect(screen.getByText('Democratizing Google Data Studio')).toBeTruthy();
    expect(
      screen.getByText('Design it here step by step. Then a small agent on your computer builds it in your own Data Studio account.'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Start a new dashboard' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Set up this computer' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /hide/i })).toBeNull();

    expect(screen.getByRole('heading', { level: 2, name: 'See it in action' })).toBeTruthy();
    const figures = screen.getAllByRole('figure');
    expect(figures).toHaveLength(4);
    figures.forEach((figure, index) => {
      const shot = SHOTS[index]!;
      const img = within(figure).getByRole('img', { name: shot.alt });
      expect(img.getAttribute('src')).toBe(`/onboarding/${shot.file}`);
      expect(img.getAttribute('width')).toBeTruthy();
      expect(img.getAttribute('height')).toBeTruthy();
      expect(img.getAttribute('loading')).toBe('lazy');
      expect(within(figure).getByText(shot.title)).toBeTruthy();
      expect(within(figure).getByText(shot.caption)).toBeTruthy();
    });

    const heading = screen.getByRole('heading', { level: 2, name: 'How it works' });
    const panel = heading.closest('section') as HTMLElement;
    expect(within(panel).getByText('Design a dashboard here, then build it in your own Google Data Studio.')).toBeTruthy();
    expect(within(panel).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
      'Design it here',
      'Set up this computer once',
      'Build with a one-time code',
      'Before you start',
    ]);
    for (const body of STEP_BODIES) expect(within(panel).getByText(body)).toBeTruthy();
    const chips = within(within(panel).getByRole('list', { name: 'Stages' })).getAllByRole('listitem');
    expect(chips.map((chip) => chip.textContent)).toEqual(['Connect', 'Context', 'Outline', 'Design', 'Blueprint', 'Prototype', 'Build']);
    const before = within(within(panel).getByRole('list', { name: 'Before you start' })).getAllByRole('listitem');
    expect(before.map((item) => item.textContent)).toEqual([
      'Google Chrome must be installed.',
      'Windows is tested. macOS and Linux are untested.',
      CSV_NOTE,
      'Everyone with this link shares one build history.',
    ]);
    expect(within(before[0] as HTMLElement).getByText('Google Chrome').tagName).toBe('STRONG');
    expect(within(before[1] as HTMLElement).getByText('Windows').tagName).toBe('STRONG');
    expect(proceed()).toBeTruthy();
  });

  it('leaves out the CSV note when the hosting does not share data', async () => {
    vi.spyOn(api, 'getHosting').mockResolvedValue({ ...fixtures.hostingOpen, share_data: false });
    renderApp('/');
    await landingHeading();
    const before = within(screen.getByRole('list', { name: 'Before you start' })).getAllByRole('listitem');
    expect(before).toHaveLength(3);
    expect(screen.queryByText(CSV_NOTE)).toBeNull();
  });

  it('sets the document title and restores it on leave; Proceed stores one boolean and opens History', async () => {
    setMockHosting('open');
    renderApp('/');
    await landingHeading();
    expect(document.title).toBe('How it works - Data Studio builder');

    fireEvent.click(proceed());
    await historyHeading();
    expect(where()).toBe('/');
    expect(document.title).toBe('Data Studio builder');
    expect(window.localStorage.length).toBe(1);
    expect(window.localStorage.getItem(KEY)).toBe('1');

    cleanup();
    renderApp('/');
    await historyHeading();
    await screen.findByRole('button', { name: 'How it works' });
    expect(where()).toBe('/');
  });

  it('"Start a new dashboard" opens the New build dialog and marks seen', async () => {
    setMockHosting('open');
    renderApp('/');
    await landingHeading();
    fireEvent.click(screen.getByRole('button', { name: 'Start a new dashboard' }));
    expect(await screen.findByRole('dialog', { name: 'New build' })).toBeTruthy();
    expect(window.localStorage.length).toBe(1);
    expect(window.localStorage.getItem(KEY)).toBe('1');
  });

  it('with storage blocked, lands every load and stops redirecting after Proceed in that mount', async () => {
    blockStorage();
    setMockHosting('open');
    renderApp('/');
    await landingHeading();
    expect(where()).toBe('/welcome');

    fireEvent.click(proceed());
    await historyHeading();
    expect(where()).toBe('/');
    // History stays put: the in-memory flag holds for this mount.
    await screen.findByRole('list', { name: 'Dashboards' });
    expect(where()).toBe('/');

    cleanup();
    renderApp('/');
    await landingHeading();
    expect(where()).toBe('/welcome');
  });
});

const STEPS = [
  'Pick your system and copy the command.',
  'Paste it into PowerShell (Windows: Start menu, type PowerShell) or Terminal (macOS/Linux) and press Enter.',
  "If a Chrome window opens, sign in to Google and accept Data Studio's terms if it asks.",
  'Keep this page open. It shows Agent ready when the check passes.',
];
const SETUP = 'Set up this computer';
const READY = 'Agent ready on this computer';

/** A check in `state`, expiring in 30 min (the fixtures' own dates are past). */
const checkIn = (state: AgentCheck['state'], extra: Partial<AgentCheck> = {}): AgentCheck => {
  const base =
    state === 'passed' ? fixtures.agentCheckPassed
    : state === 'failed' ? fixtures.agentCheckFailed
    : { ...fixtures.agentCheckWaiting, state };
  return { ...base, expires_at: new Date(Date.now() + 30 * 60_000).toISOString(), ...extra };
};

describe('Landing "Set up this computer" (agent mode)', () => {
  afterEach(() => vi.useRealTimers());
  /** Lands with real timers (the routes settle on their own), then fakes them for the check's clock. */
  async function landOnly() {
    setMockHosting('open');
    renderApp('/');
    await landingHeading();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  }
  // findBy/waitFor wait on timers the test has faked: advance, then read the DOM.
  const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

  /** Lands on /welcome with the check calls spied; `create(n)` answers the n-th create, `read(n)` the n-th read. */
  async function land(create: (n: number) => AgentCheck, read?: (n: number) => AgentCheck) {
    let made = 0;
    let reads = 0;
    const createSpy = vi.spyOn(api, 'createAgentCheck').mockImplementation(async () => create(made++));
    const readSpy = vi.spyOn(api, 'getAgentCheck').mockImplementation(async () => (read ?? create)(reads++));
    await landOnly();
    return { createSpy, readSpy };
  }
  const open = async (name = SETUP) => {
    const button = screen.getByRole('button', { name });
    button.focus();
    fireEvent.click(button);
    await advance(0);
    return screen.getByRole('dialog', { name: SETUP });
  };
  const codeN = (n: number) => `QWER-${2000 + n}`;
  const waitingN = (n: number) => checkIn('waiting', { check_id: `c_${String(n).padStart(12, '0')}`, code: codeN(n) });

  it('opens a wide dialog with one heading, the check commands with -Check/--check, the four steps and no hint', async () => {
    const { createSpy } = await land(waitingN);
    const dialog = await open();
    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(within(dialog).getAllByRole('heading', { name: SETUP })).toHaveLength(1);
    expect(within(dialog).getByText(codeN(0)).tagName).toBe('CODE');
    const commands = setupCommands(window.location.origin, 'check', codeN(0));
    expect(commands.powershell).toContain(`-Check ${codeN(0)}`);
    expect(commands.bash).toContain(`--check ${codeN(0)}`);
    expect(within(dialog).getByText(commands.powershell).tagName).toBe('CODE');
    fireEvent.click(within(dialog).getByRole('tab', { name: /macOS\/Linux/ }));
    expect(within(dialog).getByText(commands.bash).tagName).toBe('CODE');
    const steps = within(within(dialog).getByRole('list', { name: 'Steps' })).getAllByRole('listitem');
    expect(steps.map((li) => li.textContent)).toEqual(STEPS);
    expect(within(dialog).queryByText('Already set up? Build in Data Studio.')).toBeNull();
    expect(dialog.className).toContain('max-w-180');
    // Focus is in the flow, not on body.
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it.each(['passed', 'failed', 'expired'] as const)('polls every 3 s while waiting and stops on %s', async (end) => {
    let current = waitingN(0);
    const { readSpy } = await land(
      () => current,
      () => current,
    );
    await open();
    await advance(2999);
    expect(readSpy).toHaveBeenCalledTimes(0);
    await advance(1);
    expect(readSpy).toHaveBeenCalledTimes(1);
    await advance(3000);
    expect(readSpy).toHaveBeenCalledTimes(2);
    current = checkIn(end);
    await advance(3000);
    expect(readSpy).toHaveBeenCalledTimes(3);
    await advance(30_000);
    expect(readSpy).toHaveBeenCalledTimes(3);
  });

  it('a code that runs out locally stops the polling', async () => {
    let soon: AgentCheck | null = null;
    const { readSpy } = await land(() => (soon ??= checkIn('waiting', { expires_at: new Date(Date.now() + 4000).toISOString() })));
    await open();
    await advance(4100);
    const dialog = screen.getByRole('dialog', { name: SETUP });
    expect(within(dialog).getByText('That check code expired.')).toBeTruthy();
    const calls = readSpy.mock.calls.length;
    await advance(30_000);
    expect(readSpy).toHaveBeenCalledTimes(calls);
  });

  it('passed: ready in the dialog, Done closes it, the hero shows the ready line with focus on Check again; only a boolean is stored', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    await land(waitingN, () => checkIn('passed'));
    const dialog = await open();
    await advance(3000);
    expect(within(dialog).getByText(READY)).toBeTruthy();
    expect(within(dialog).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Server reached: ok',
      'Versions match: ok',
      'Chrome running: ok',
      'Signed in to Google: ok',
    ]);
    const done = within(dialog).getByRole('button', { name: 'Done' });
    expect(document.activeElement).toBe(done);
    fireEvent.click(done);
    await advance(0);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByText(READY)).toBeTruthy();
    expect(screen.queryByRole('button', { name: SETUP })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Check again' }));
    expect(Object.fromEntries(Object.entries(sessionStorage))).toEqual({ 'dss.agentReady': '1' });
    expect(window.localStorage.length).toBe(0);
    expect(JSON.stringify(setItem.mock.calls)).not.toContain(codeN(0));

    // A remount in the same tab shows the ready line.
    cleanup();
    vi.useRealTimers();
    renderApp('/');
    await landingHeading();
    expect(screen.getByText(READY)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Check again' })).toBeTruthy();
  });

  it('Check again opens a fresh code; a failed recheck brings back the button, which takes focus on close', async () => {
    window.sessionStorage.setItem('dss.agentReady', '1');
    const { createSpy } = await land(waitingN, () =>
      checkIn('failed', { result: { agent_version: '0.1.0', api_version_ok: true, chrome_running: false, signed_in: true } }),
    );
    expect(screen.getByText(READY)).toBeTruthy();
    const dialog = await open('Check again');
    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(within(dialog).getByText(codeN(0))).toBeTruthy();
    expect(within(dialog).queryByText(READY)).toBeNull();
    await advance(3000);
    expect(within(dialog).getByText('The check found a problem.')).toBeTruthy();
    expect(screen.queryByText(READY)).toBeNull();
    expect(window.sessionStorage.getItem('dss.agentReady')).toBeNull();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }));
    await advance(0);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: SETUP }));
  });

  it('a press on the backdrop keeps the dialog open and polling', async () => {
    const { readSpy } = await land(waitingN);
    const dialog = await open();
    fireEvent.pointerDown(dialog.parentElement as HTMLElement);
    await advance(3000);
    expect(screen.getByRole('dialog', { name: SETUP })).toBeTruthy();
    expect(readSpy).toHaveBeenCalledTimes(1);
  });

  it('Esc closes it while waiting; reopening asks for a new code; no code is kept anywhere', async () => {
    const sinks = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) => vi.spyOn(console, m));
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const { createSpy } = await land(waitingN);
    await open();
    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    await advance(0);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: SETUP }));
    const dialog = await open();
    expect(createSpy).toHaveBeenCalledTimes(2);
    expect(within(dialog).getByText(codeN(1))).toBeTruthy();
    const kept = JSON.stringify([
      ...sinks.flatMap((sp) => sp.mock.calls),
      ...setItem.mock.calls,
      { ...localStorage },
      { ...sessionStorage },
      window.location.href,
    ]);
    for (const code of [codeN(0), codeN(1)]) expect(kept).not.toContain(code);
  });

  it('after Check again, Get a new code or Try again, focus stays in the dialog (never body)', async () => {
    const createSpy = vi
      .spyOn(api, 'createAgentCheck')
      .mockImplementationOnce(async () => checkIn('failed'))
      .mockImplementationOnce(async () => checkIn('expired'))
      .mockImplementationOnce(async () => {
        throw new ApiError(500, 'server_error', 'down');
      })
      .mockImplementation(async () => waitingN(9));
    await landOnly();
    const dialog = await open();

    for (const name of ['Check again', 'Get a new code', 'Try again']) {
      const button = within(dialog).getByRole('button', { name });
      button.focus();
      fireEvent.click(button);
      expect(document.activeElement).not.toBe(document.body);
      await advance(0);
      expect(document.activeElement).not.toBe(document.body);
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    expect(createSpy).toHaveBeenCalledTimes(4);
    expect(within(dialog).getByText(codeN(9))).toBeTruthy();
    expect(document.activeElement).toBe(within(dialog).getByRole('tab', { name: 'Windows (PowerShell)' }));
  });
});

describe('History "How it works"', () => {
  it('shows left of "New build" in agent mode and reopens /welcome without clearing the key', async () => {
    window.localStorage.setItem(KEY, '1');
    setMockHosting('open');
    renderApp('/');
    await historyHeading();
    const howItWorks = await screen.findByRole('button', { name: 'How it works' });
    const newBuild = screen.getByRole('button', { name: 'New build' });
    expect(howItWorks.compareDocumentPosition(newBuild) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(howItWorks);
    await landingHeading();
    expect(where()).toBe('/welcome');
    expect(window.localStorage.getItem(KEY)).toBe('1');
  });
});

describe('Outside agent mode', () => {
  const settle = async () => {
    await historyHeading();
    await screen.findByRole('list', { name: 'Dashboards' });
  };

  it('local mode: / is History without "How it works", /welcome goes back to /', async () => {
    const hosting = vi.spyOn(api, 'getHosting');
    renderApp('/');
    await settle();
    await waitFor(() => expect(hosting).toHaveBeenCalled());
    await act(async () => {
      await hosting.mock.results[0]?.value;
    });
    expect(where()).toBe('/');
    expect(screen.queryByRole('button', { name: 'How it works' })).toBeNull();

    cleanup();
    renderApp('/welcome');
    await settle();
    expect(where()).toBe('/');
    expect(screen.queryByRole('heading', { name: H1 })).toBeNull();
  });

  it('a failed hosting load: / is History without "How it works", /welcome goes back to /', async () => {
    vi.spyOn(api, 'getHosting').mockRejectedValue(new Error('offline'));
    renderApp('/');
    await settle();
    expect(where()).toBe('/');
    expect(screen.queryByRole('button', { name: 'How it works' })).toBeNull();

    cleanup();
    renderApp('/welcome');
    await settle();
    expect(where()).toBe('/');
  });
});

describe('Screenshot assets', () => {
  it('ships the four .webp files, each at most 200 KB', async () => {
    // No @types/node here: a string specifier keeps tsc from resolving node:fs. Paths are relative to frontend/.
    const nodeFs = 'node:fs';
    const { statSync } = (await import(/* @vite-ignore */ nodeFs)) as { statSync: (path: string) => { size: number } };
    for (const { file } of SHOTS) {
      const size = statSync(`public/onboarding/${file}`).size;
      expect(size, file).toBeGreaterThan(0);
      expect(size, file).toBeLessThanOrEqual(200 * 1024);
    }
  });
});
