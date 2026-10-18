import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, isMockMode } from '../src/api/client';
import { ApiError, type BuildSummary } from '../src/api/types';
import { HistoryPage } from '../src/features/history/HistoryPage';
import { resetMockState } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function renderHistory() {
  render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>,
  );
}

const rows = () => screen.getAllByRole('listitem');
const titles = () => rows().map((row) => within(row).getByRole('heading').textContent);

describe('History', () => {
  it('runs against the mock, which serves builds.json', async () => {
    expect(isMockMode).toBe(true);
    expect(await api.listBuilds()).toEqual(fixtures.builds);
  });

  it('shows loading, then the builds from the mock, newest first', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-19T00:00:00Z'));
    await api.createBuild({ title: 'Marketing funnel', archetype: 'analytical', mode: 'data' });

    renderHistory();
    expect(screen.getByRole('status').textContent).toMatch(/loading/i);
    await screen.findByRole('list', { name: 'Dashboards' });

    expect(titles()).toEqual(['Marketing funnel', 'Sales overview', 'Support tickets ops view']);
  });

  it('sorts newest first even when the API does not', async () => {
    const [newer, older] = fixtures.builds as [BuildSummary, BuildSummary];
    vi.spyOn(api, 'listBuilds').mockResolvedValue([older, newer]);
    renderHistory();
    await screen.findByRole('list', { name: 'Dashboards' });
    expect(titles()).toEqual([newer.title, older.title]);
  });

  it('shows each build with its stage, workspace link and report link', async () => {
    renderHistory();
    await screen.findByRole('list', { name: 'Dashboards' });
    const [sales, support] = rows() as [HTMLElement, HTMLElement];

    expect(within(sales).getByRole('link', { name: 'Sales overview' }).getAttribute('href')).toBe('/builds/b_3f9a0c12d4e5');
    expect(within(sales).getByText('Prototype')).toBeTruthy();
    expect(within(sales).getByText('Not published yet')).toBeTruthy();

    const report = within(support).getByRole('link', { name: /open in data studio/i });
    expect(report.getAttribute('href')).toBe(fixtures.buildDone.report_url);
    expect(report.getAttribute('target')).toBe('_blank');
    expect(report.getAttribute('rel')).toContain('noopener');
    expect(within(support).getByText('Done')).toBeTruthy();
  });

  it('shows the empty state when there are no builds', async () => {
    vi.spyOn(api, 'listBuilds').mockResolvedValue([]);
    renderHistory();
    expect(await screen.findByRole('heading', { name: 'No dashboards yet' })).toBeTruthy();
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('shows the error with what to do, and "Try again" reloads', async () => {
    const message = "Can't reach the backend. Start it on port 8000, then try again.";
    vi.spyOn(api, 'listBuilds').mockRejectedValueOnce(new ApiError(0, 'network_error', message));
    renderHistory();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(message);

    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await screen.findByRole('list', { name: 'Dashboards' });
    expect(titles()).toEqual(['Sales overview', 'Support tickets ops view']);
    expect(document.activeElement).toBe(screen.getByRole('heading', { level: 1, name: 'Dashboards' }));
  });
});
