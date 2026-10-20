import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import { ApiError, type Build, type BuildEvent } from '../src/api/types';
import { DoneStage } from '../src/features/history/DoneStage';
import { ReferencePanel } from '../src/features/workspace/ReferencePanel';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { ChatPanel } from '../src/features/workspace/chat/ChatPanel';
import { useBuildStream } from '../src/features/workspace/chat/useBuildStream';
import { ConnectStage } from '../src/features/workspace/connect/ConnectStage';
import { publishWorkspace } from '../src/features/workspace/stretch';
import { resetMockState } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(resetMockState);
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const buildId = fixtures.build.id;
const png = (name = 'style.png') => new File(['image'], name, { type: 'image/png' });
const pick = (...files: File[]) => fireEvent.change(screen.getByLabelText('Reference images'), { target: { files } });
const upload = () => screen.getByRole('button', { name: /^(Upload|Replace) references$/ });
const done = (run_id: string, error: string | null = null): BuildEvent => ({ name: 'run.finished', data: { run_id, node: 'reference_extract', status: error ? 'error' : 'ok', error } });
const fire = (event: BuildEvent) => act(() => publishWorkspace(buildId, event));
async function panel() {
  render(<ReferencePanel buildId={buildId} />);
  await screen.findByText(/No references yet/);
}
function Workspace({ initial }: { initial: Build }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild);
  return <><ChatPanel build={build} chat={chat} /><ConnectStage build={build} onBuildChange={setBuild} stretchRuns={chat.stretchRuns} /></>;
}

describe('Required references', () => {
  it('uploads recreate mode and exact instructions once, including same-frame clicks; follows its run only', async () => {
    const get = vi.spyOn(api, 'getReferences').mockResolvedValue(null);
    let resolve!: (value: { run_id: string }) => void;
    const post = vi.spyOn(api, 'uploadReferences').mockReturnValue(new Promise((r) => { resolve = r; }));
    await panel();
    const file = png();
    fireEvent.click(screen.getByRole('radio', { name: 'Recreate dashboard' }));
    fireEvent.change(screen.getByLabelText('Reference instructions'), { target: { value: '  Keep the layout.  ' } });
    pick(file);
    act(() => { fireEvent.click(upload()); fireEvent.click(upload()); });
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith(buildId, [file], 'recreate', '  Keep the layout.  ');
    await screen.findByText('Uploading 1 image…');
    expect((upload() as HTMLButtonElement).disabled).toBe(true);
    await act(async () => resolve({ run_id: 'r_mine' }));
    await screen.findByText('Reading your references…');
    await fire(done('r_other'));
    expect((upload() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText(/References saved/)).toBeNull();
    get.mockResolvedValue(fixtures.referenceSet);
    await fire(done('r_mine'));
    await screen.findByText('References saved. The planner uses them.');
    expect(get.mock.calls.length).toBeGreaterThan(1);
    await screen.findByRole('img', { name: 'Recreate dashboard reference: dashboard.png' });
  });

  it('opens the same stage panel from chat; upload appears there and restores on remount', async () => {
    const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
    render(<Workspace initial={build} />);
    await screen.findByText(/No references yet/);
    const region = screen.getByRole('region', { name: 'References' });
    const details = region.querySelector('details')!;
    fireEvent.click(within(region).getByText('References', { exact: true }));
    expect(details.open).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Attach reference' }));
    await waitFor(() => expect(details.open).toBe(true));
    expect(document.activeElement).toBe(screen.getByRole('radio', { name: 'Use style' }));
    pick(png('shared.png'));
    fireEvent.click(upload());
    await screen.findByRole('img', { name: 'Use style reference: shared.png' });
    expect(screen.getAllByRole('region', { name: 'References' })).toHaveLength(1);
    cleanup();
    render(<ReferencePanel buildId={build.id} />);
    await screen.findByRole('img', { name: 'Use style reference: shared.png' });
    expect((screen.getByRole('radio', { name: 'Use style' }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(fixtures.referenceSet.summary)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Remove references' }));
    await screen.findByText('References removed.');
    expect(await api.getReferences(build.id)).toBeNull();
  });

  it('replaces a saved set, removes it with DELETE and returns focus to the file chooser', async () => {
    const get = vi.spyOn(api, 'getReferences').mockResolvedValue(fixtures.referenceSet);
    vi.spyOn(api, 'uploadReferences').mockResolvedValue({ run_id: 'r_replace' });
    const remove = vi.spyOn(api, 'deleteReferences').mockResolvedValue();
    render(<ReferencePanel buildId={buildId} />);
    await screen.findByRole('img');
    pick(png('replacement.png'));
    fireEvent.click(upload());
    await screen.findByText('Reading your references…');
    get.mockResolvedValue({ ...fixtures.referenceSet, id: 'ref_new', images: [{ id: 'new', name: 'replacement.png', file: 'reference_new.png' }] });
    await fire(done('r_replace'));
    await screen.findByRole('img', { name: 'Recreate dashboard reference: replacement.png' });
    get.mockResolvedValue(null);
    fireEvent.click(screen.getByRole('button', { name: 'Remove references' }));
    await screen.findByText('References removed.');
    expect(remove).toHaveBeenCalledExactlyOnceWith(buildId);
    expect(document.activeElement).toBe(screen.getByLabelText('Reference images'));
    expect(screen.queryByRole('img')).toBeNull();
    await screen.findByText(/No references yet/);
  });

  it.each([
    ['recreate', [png(), png()], 'exactly 1'],
    ['style', [png(), png(), png(), png()], '1-3'],
    ['style', [new File([new Uint8Array(6 * 1024 * 1024)], 'large.png', { type: 'image/png' })], '5 MiB'],
    ['style', [new File([new Uint8Array(16 * 1024 * 1024)], 'total.png', { type: 'image/png' })], '15 MiB'],
    ['style', [new File(['x'], 'notes.txt', { type: 'text/plain' })], 'PNG/JPEG'],
  ] as const)('rejects invalid %s files before POST (%s)', async (mode, files, limit) => {
    const post = vi.spyOn(api, 'uploadReferences');
    await panel();
    if (mode === 'recreate') fireEvent.click(screen.getByRole('radio', { name: 'Recreate dashboard' }));
    pick(...files);
    fireEvent.click(upload());
    expect((await screen.findByRole('alert')).textContent).toContain(limit);
    expect(post).not.toHaveBeenCalled();
  });

  it.each([413, 422])('keeps the prior set and selection after %s, with reference-specific copy', async (status) => {
    vi.spyOn(api, 'getReferences').mockResolvedValue(fixtures.referenceSet);
    vi.spyOn(api, 'uploadReferences').mockRejectedValue(new ApiError(status, 'invalid_source', 'Files over 32 MB'));
    render(<ReferencePanel buildId={buildId} />);
    await screen.findByRole('img');
    const file = png('selected.png'); pick(file); fireEvent.click(upload());
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/reference/i);
    expect(alert.textContent).not.toContain('32 MB');
    expect(screen.getByRole('img', { name: /dashboard.png/ })).toBeTruthy();
    expect(screen.getByText('selected.png')).toBeTruthy();
    expect((screen.getByLabelText('Reference images') as HTMLInputElement).files?.[0]).toBe(file);
    expect((upload() as HTMLButtonElement).disabled).toBe(false);
  });

  it('shows a failed run without raw model output and lets the user retry with the same selection', async () => {
    vi.spyOn(api, 'uploadReferences').mockResolvedValue({ run_id: 'r_failed' });
    await panel(); pick(png()); fireEvent.click(upload());
    await screen.findByText('Reading your references…');
    await fire(done('r_failed', 'RAW /private/model/output'));
    expect((await screen.findByRole('alert')).textContent).toContain('clearer PNG/JPEG');
    expect(screen.queryByText(/RAW/)).toBeNull();
    expect(screen.getByText('style.png')).toBeTruthy();
    expect((upload() as HTMLButtonElement).disabled).toBe(false);
  });

  it('settles a finish event received before its POST response', async () => {
    let resolve!: (value: { run_id: string }) => void;
    vi.spyOn(api, 'uploadReferences').mockReturnValue(new Promise((r) => { resolve = r; }));
    await panel(); pick(png()); fireEvent.click(upload());
    await fire(done('r_early'));
    await act(async () => resolve({ run_id: 'r_early' }));
    await screen.findByText('References saved. The planner uses them.');
    expect((upload() as HTMLButtonElement).disabled).toBe(true); // selection cleared
  });

  it('shows reference 404 errors and Retry instead of hiding; ready/docs/finish refresh saved state', async () => {
    const get = vi.spyOn(api, 'getReferences').mockRejectedValue(new ApiError(404, 'http_error', 'Reference route missing.'));
    render(<ReferencePanel buildId={buildId} />);
    await screen.findByText('Reference route missing.');
    expect((upload() as HTMLButtonElement).disabled).toBe(true);
    get.mockResolvedValue(null);
    fireEvent.click(screen.getByRole('button', { name: 'Retry references' }));
    await screen.findByText(/No references yet/);
    for (const event of [{ name: 'ready', data: { build_id: buildId } }, { name: 'docs.updated', data: { docs: [] } }, done('other')] as BuildEvent[]) {
      const count = get.mock.calls.length;
      await fire(event);
      await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(count));
    }
  });

  it('shows saved references read-only beside New version', async () => {
    vi.spyOn(api, 'getReferences').mockResolvedValue(fixtures.referenceSet);
    render(<DoneStage build={fixtures.buildDone} onBuildChange={() => {}} />);
    await screen.findByRole('img', { name: /Recreate dashboard reference/ });
    expect(screen.getByRole('button', { name: 'New version' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Replace references' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Remove references' })).toBeNull();
  });

  it('fails closed on reference GET errors and keeps Generate plan disabled until Retry succeeds', async () => {
    vi.spyOn(api, 'getBuild').mockResolvedValue({ ...fixtures.build, stage: 'interview' });
    const get = vi.spyOn(api, 'getReferences').mockRejectedValue(new ApiError(503, 'unavailable', 'References are unavailable. Retry.'));
    const post = vi.spyOn(api, 'generatePlan');
    render(<MemoryRouter initialEntries={[`/builds/${buildId}`]}><Routes><Route path="/builds/:id" element={<WorkspaceShell />} /></Routes></MemoryRouter>);
    await screen.findByText('References are unavailable. Retry.');
    const button = screen.getByRole('button', { name: 'Generate plan' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(post).not.toHaveBeenCalled();
    let resolve!: (value: null) => void;
    get.mockReturnValue(new Promise((r) => { resolve = r; }));
    fireEvent.click(screen.getByRole('button', { name: 'Retry references' }));
    expect(button.disabled).toBe(true);
    await act(async () => resolve(null));
    await waitFor(() => expect(button.disabled).toBe(false));
  });

  it('keeps Attach reference working in the Build view and guards recipe/Build after a failed refresh', async () => {
    const get = vi.spyOn(api, 'getReferences').mockResolvedValue(null);
    const run = vi.spyOn(api, 'runBuild');
    const compile = vi.spyOn(api, 'compileRecipe');
    render(<MemoryRouter initialEntries={[`/builds/${buildId}`]}><Routes><Route path="/builds/:id" element={<WorkspaceShell />} /></Routes></MemoryRouter>);
    const next = await screen.findByRole('button', { name: 'Continue to build' });
    await waitFor(() => expect((next as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(next);
    await screen.findByRole('button', { name: 'Back to prototype' });
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Use style' }).matches(':disabled')).toBe(false));
    fireEvent.click(screen.getByText('References', { exact: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Attach reference' }));
    expect(document.activeElement).toBe(screen.getByRole('radio', { name: 'Use style' }));
    const generate = screen.getByRole('button', { name: 'Generate recipe' });
    fireEvent.click(generate);
    const build = screen.getByRole('button', { name: 'Build in Data Studio' }) as HTMLButtonElement;
    await waitFor(() => expect(build.disabled).toBe(false));
    get.mockRejectedValue(new ApiError(503, 'unavailable', 'References are unavailable. Retry.'));
    await fire({ name: 'docs.updated', data: { docs: [] } });
    await screen.findByText('References are unavailable. Retry.');
    const regenerate = screen.getByRole('button', { name: 'Regenerate' });
    expect(regenerate.matches(':disabled')).toBe(true);
    fireEvent.click(regenerate);
    expect(compile).toHaveBeenCalledTimes(1);
    expect(build.disabled).toBe(true);
    fireEvent.click(build);
    expect(run).not.toHaveBeenCalled();
  });
});
