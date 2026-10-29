import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, httpApi } from '../src/api/client';
import { ApiError, type Build } from '../src/api/types';
import { NewBuildDialog } from '../src/features/history/NewBuildDialog';
import { ConnectStage } from '../src/features/workspace/connect/ConnectStage';
import { resetMockState, setMockHosting } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const csv = (name: string) => new File(['a,b\n1,2'], name, { type: 'text/csv' });

function Holder({ initial }: { initial: Build }) {
  const [build, setBuild] = useState(initial);
  return <ConnectStage build={build} onBuildChange={setBuild} />;
}

async function renderConnect() {
  const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
  render(<Holder initial={build} />);
  return build;
}

const dropZone = () => screen.getByRole('region', { name: 'Upload CSV files' });
const drop = (...files: File[]) => fireEvent.drop(dropZone(), { dataTransfer: { files } });
const off = (el: HTMLElement) => (el as HTMLButtonElement).disabled;
const unusable = (el: HTMLElement) => el.matches(':disabled');
const type = (input: HTMLElement, value: string) => fireEvent.change(input, { target: { value } });

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

describe('New build dialog', () => {
  it('keeps Create build disabled until an archetype is picked, then posts it and opens the build', async () => {
    const spy = vi.spyOn(api, 'createBuild');
    render(
      <MemoryRouter>
        <NewBuildDialog open onClose={() => {}} />
        <Where />
      </MemoryRouter>,
    );
    const create = screen.getByRole('button', { name: 'Create build' });
    expect(off(create)).toBe(true);
    fireEvent.click(screen.getByRole('radio', { name: /Analytical/ }));
    expect(off(create)).toBe(false);
    fireEvent.click(create);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy.mock.calls[0]?.[0]).toMatchObject({ archetype: 'analytical', mode: 'data' });
    await waitFor(() => expect(screen.getByTestId('where').textContent).toMatch(/^\/builds\/.+/));
  });

  it('shows the API error inline and stays open', async () => {
    vi.spyOn(api, 'createBuild').mockRejectedValue(new ApiError(422, 'invalid_request', 'Pick an archetype and a mode.'));
    const onClose = vi.fn();
    render(
      <MemoryRouter>
        <NewBuildDialog open onClose={onClose} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('radio', { name: /Executive/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Create build' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Pick an archetype and a mode.');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('sends POST /api/builds with the archetype over fetch', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify(fixtures.build), { status: 201, headers: { 'Content-Type': 'application/json' } }));
    await httpApi.createBuild({ archetype: 'executive', mode: 'data' });
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/builds');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toMatchObject({ archetype: 'executive', mode: 'data' });
  });
});

describe('Connect stage', () => {
  it('shows the empty state and keeps Draft context disabled with no source', async () => {
    await renderConnect();
    expect(screen.getByText('No sources yet')).toBeTruthy();
    expect(off(screen.getByRole('button', { name: 'Draft context' }))).toBe(true);
    expect(screen.getByText('Add at least one source to start.')).toBeTruthy();
  });

  it('uploads two dropped CSVs in one call and lists both sources with their columns', async () => {
    const build = await renderConnect();
    const spy = vi.spyOn(api, 'uploadSources');
    const files = [csv('orders.csv'), csv('customers.csv')];
    drop(...files);

    const table = await screen.findByRole('table', { name: 'Sources' });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(build.id, files);
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain('orders.csv');
    expect(rows[1]?.textContent).toContain('customers.csv');
    const first = fixtures.build.sources[0]!.columns[0]!;
    expect(within(rows[0]!).getByText(first.name)).toBeTruthy();
  });

  it('shows the 422 message in an alert and adds nothing', async () => {
    await renderConnect();
    drop(new File(['x'], 'notes.txt', { type: 'text/plain' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("notes.txt isn't a CSV file. Upload .csv files only.");
    // The same files would fail again: no retry, only Dismiss.
    expect(within(alert).queryByRole('button', { name: 'Try again' })).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    expect(off(screen.getByRole('button', { name: 'Draft context' }))).toBe(true);
  });

  it('shows the uploading state while the call runs', async () => {
    await renderConnect();
    let release: (v: { sources: [] }) => void = () => {};
    vi.spyOn(api, 'uploadSources').mockReturnValue(new Promise((r) => (release = r)));
    drop(csv('a.csv'), csv('b.csv'));
    expect(await screen.findByText('Uploading 2 files…')).toBeTruthy();
    expect(off(screen.getByRole('button', { name: 'Choose CSV files' }))).toBe(true);
    release({ sources: [] });
    await waitFor(() => expect(screen.queryByText('Uploading 2 files…')).toBeNull());
  });

  it('adds a GCS source from the form and shows a bad path error', async () => {
    await renderConnect();
    const input = screen.getByPlaceholderText('gs://bucket/path/file.csv');
    const add = screen.getByRole('button', { name: 'Add source' });
    expect(off(add)).toBe(true);
    type(input, 'not-a-path');
    fireEvent.submit(input.closest('form')!);
    expect(await screen.findByText('Enter a GCS path like gs://bucket/path/file.csv.')).toBeTruthy();
    type(input, 'gs://bucket/data/sales.csv');
    fireEvent.submit(input.closest('form')!);
    expect(await screen.findByRole('table', { name: 'Sources' })).toBeTruthy();
  });

  it('enables Draft context after an upload and drafts the context', async () => {
    const build = await renderConnect();
    const start = vi.spyOn(api, 'draftContext');
    const button = screen.getByRole('button', { name: 'Draft context' });
    expect(off(button)).toBe(true);
    drop(csv('orders.csv'));
    await screen.findByRole('table', { name: 'Sources' });
    expect(off(button)).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(start).toHaveBeenCalledWith(build.id));
    await waitFor(async () => expect((await api.getBuild(build.id)).stage).toBe('context'));
  });
});

describe('Connect stage on the open link (locked sources)', () => {
  const LOCKED = 'GCS and BigQuery sources need the local app (see README)';

  it('disables the GCS/BigQuery form with the reason, while CSV upload still works', async () => {
    setMockHosting('open');
    await renderConnect();
    expect(await screen.findByText(LOCKED)).toBeTruthy();
    for (const radio of within(screen.getByRole('radiogroup', { name: 'Source type' })).getAllByRole('radio')) expect(unusable(radio)).toBe(true);
    expect(unusable(screen.getByPlaceholderText('gs://bucket/path/file.csv'))).toBe(true);
    expect(unusable(screen.getByRole('button', { name: 'Add source' }))).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Choose CSV files' }))).toBe(false);
    drop(csv('orders.csv'));
    expect(await screen.findByRole('table', { name: 'Sources' })).toBeTruthy();
  });

  it('local mode shows no lock', async () => {
    await renderConnect();
    await waitFor(() => expect(off(screen.getByRole('button', { name: 'Choose CSV files' }))).toBe(false));
    expect(screen.queryByText(LOCKED)).toBeNull();
    expect(unusable(screen.getByPlaceholderText('gs://bucket/path/file.csv'))).toBe(false);
  });

  it('403 source_locked shows the same text, not a field error, and locks the form', async () => {
    vi.spyOn(api, 'addSource').mockRejectedValue(new ApiError(403, 'source_locked', 'locked on the server', { kind: 'gcs' }));
    await renderConnect();
    const input = screen.getByPlaceholderText('gs://bucket/path/file.csv');
    type(input, 'gs://bucket/data/sales.csv');
    fireEvent.submit(input.closest('form')!);
    expect(await screen.findByText(LOCKED)).toBeTruthy();
    expect(screen.queryByText('locked on the server')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(unusable(screen.getByPlaceholderText('gs://bucket/path/file.csv'))).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Choose CSV files' }))).toBe(false);
  });
});
