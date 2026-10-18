import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import { ApiError } from '../src/api/types';
import { HistoryPage } from '../src/features/history/HistoryPage';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { resetMockState } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const done = fixtures.buildDone;

function renderWorkspace(id = done.id) {
  render(
    <MemoryRouter initialEntries={[`/builds/${id}`]}>
      <Routes>
        <Route path="/builds/:id" element={<WorkspaceShell />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Done stage', () => {
  it('shows the link card for the published dashboard', async () => {
    renderWorkspace();
    const card = await screen.findByRole('region', { name: 'Published dashboard' });
    expect(within(card).getByText('Your dashboard is in Data Studio.')).toBeTruthy();
    const link = within(card).getByRole('link', { name: /open in data studio/i });
    expect(link.getAttribute('href')).toBe(done.report_url);
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
  });

  it('lists v1 with its link', async () => {
    renderWorkspace();
    const list = await screen.findByRole('list', { name: 'Versions' });
    const [v1] = within(list).getAllByRole('listitem') as [HTMLElement];
    expect(within(v1).getByText('v1')).toBeTruthy();
    expect(within(v1).getByText('Published')).toBeTruthy();
    expect(within(v1).getByRole('link', { name: /open in data studio/i }).getAttribute('href')).toBe(done.versions[0]!.report_url);
  });

  it('says so when the build has no link yet', async () => {
    vi.spyOn(api, 'getBuild').mockResolvedValue({
      ...done,
      report_url: null,
      versions: [{ ...done.versions[0]!, report_url: null, status: 'failed' }],
    });
    renderWorkspace();
    const card = await screen.findByRole('region', { name: 'Published dashboard' });
    expect(within(card).getByText('No link yet.')).toBeTruthy();
    expect(within(card).queryByRole('link')).toBeNull();
    expect(screen.getByText('Not published')).toBeTruthy();
  });

  it('"New version" posts and lands on the Prototype stage with v2', async () => {
    const create = vi.spyOn(api, 'createVersion');
    renderWorkspace();
    fireEvent.click(await screen.findByRole('button', { name: 'New version' }));
    expect(create).toHaveBeenCalledWith(done.id);
    expect(await screen.findByRole('heading', { name: 'Prototype', level: 2 })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Published dashboard' })).toBeNull();
    expect((await api.getBuild(done.id)).current_version).toBe(2);
    expect((await api.getBuild(done.id)).versions.map((v) => v.n)).toEqual([1, 2]);
  });

  it('shows the error and stays on Done when the new version fails', async () => {
    vi.spyOn(api, 'createVersion').mockRejectedValue(new ApiError(409, 'wrong_stage', 'Wait for the build to finish.'));
    renderWorkspace();
    fireEvent.click(await screen.findByRole('button', { name: 'New version' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Wait for the build to finish.');
    expect(screen.getByRole('region', { name: 'Published dashboard' })).toBeTruthy();
    await waitFor(() => expect((screen.getByRole('button', { name: 'New version' }) as HTMLButtonElement).disabled).toBe(false));
  });

  it('lists v1 and v2 newest first after a new version, with v2 unpublished', async () => {
    await api.createVersion(done.id);
    const build = await api.getBuild(done.id);
    vi.spyOn(api, 'getBuild').mockResolvedValue({ ...build, stage: 'done' });
    renderWorkspace();
    const list = await screen.findByRole('list', { name: 'Versions' });
    const items = within(list).getAllByRole('listitem');
    expect(items.map((item) => within(item).getByText(/^v\d$/).textContent)).toEqual(['v2', 'v1']);
    expect(within(items[0]!).getByText('Not published')).toBeTruthy();
  });
});

describe('History with versions', () => {
  it('shows a done build with its stage and link', async () => {
    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    );
    const list = await screen.findByRole('list', { name: 'Dashboards' });
    const row = within(list).getByRole('link', { name: done.title }).closest('li') as HTMLElement;
    expect(within(row).getByText('Done')).toBeTruthy();
    expect(within(row).getByRole('link', { name: /open in data studio/i }).getAttribute('href')).toBe(done.report_url);
  });
});
