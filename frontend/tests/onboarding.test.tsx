import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigationType } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { api } from '../src/api/client';
import type { Hosting } from '../src/api/types';
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
    expect(screen.queryByRole('button', { name: /set up this computer/i })).toBeNull();
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
