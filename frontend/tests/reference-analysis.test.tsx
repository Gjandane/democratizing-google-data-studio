import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { ReferenceSet } from '../src/api/types';
import { ReferencePanel } from '../src/features/workspace/ReferencePanel';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { ANALYSIS_GATE_REASON } from '../src/features/workspace/reference/gate';
import { CONFLICT_NOTE, STALE_WARNING } from '../src/features/workspace/reference/AnalysisReview';
import { patchMockBuild, resetMockState, setMockArtifact, setMockReferences } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(resetMockState);
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const id = fixtures.build.id;
const pending = (): ReferenceSet => structuredClone(fixtures.referenceSetPending);
const approved = (): ReferenceSet => structuredClone(fixtures.referenceSet);
const analysis = fixtures.referenceSetPending.analysis!;
const off = (el: Element) => el.matches(':disabled');
const row = (label: string) => screen.getByText(label, { selector: 'span' }).closest<HTMLElement>('li[data-item]')!;
const approveButton = () => screen.getByRole('button', { name: 'Approve and continue' });
const box = () => document.querySelector<HTMLElement>('[data-reference-box]');

async function panel(set: ReferenceSet | null = pending()) {
  setMockReferences(id, set);
  render(<ReferencePanel buildId={id} />);
  await screen.findByRole('img');
}

function workspace() {
  render(
    <MemoryRouter initialEntries={[`/builds/${id}`]}>
      <Routes>
        <Route path="/builds/:id" element={<WorkspaceShell />} />
      </Routes>
    </MemoryRouter>,
  );
}

const inDesign = () => patchMockBuild(id, { stage: 'design', spec_version: null, artifacts: { context: 'confirmed', outline: 'confirmed', design: 'draft', blueprint: 'missing' } });
const inBlueprint = () => patchMockBuild(id, { stage: 'blueprint', spec_version: null, artifacts: { context: 'confirmed', outline: 'confirmed', design: 'confirmed', blueprint: 'draft' } });

describe('Reference analysis review', () => {
  it('asks the summary as the question, one row per item with its kind, shows, reason, Native/Static and a type select of allowed_types', async () => {
    await panel();
    expect(screen.getByRole('heading', { name: analysis.summary })).toBeTruthy();
    expect(screen.getByText('Proceed?')).toBeTruthy();
    const rows = within(screen.getByRole('list', { name: 'Reference items' })).getAllByRole('listitem').filter((li) => li.hasAttribute('data-item'));
    expect(rows.map((li) => li.dataset.item)).toEqual(analysis.items.map((item) => item.id));
    const revenue = row('Revenue KPI cards');
    expect(within(revenue).getByText('KPI')).toBeTruthy();
    expect(within(revenue).getByText('Shows: revenue, orders and average order value')).toBeTruthy();
    expect(within(revenue).getByText('Scorecards show one measure each.')).toBeTruthy();
    expect((within(revenue).getByRole('radio', { name: 'Native' }) as HTMLInputElement).checked).toBe(true);
    const select = within(revenue).getByRole('combobox', { name: 'Revenue KPI cards: component type' }) as HTMLSelectElement;
    expect(select.value).toBe('scorecard');
    expect(Array.from(select.options).map((o) => o.value)).toEqual(analysis.allowed_types);
    expect(Array.from(select.options).map((o) => o.text)).toContain('Time series');
    expect(Array.from(select.options).map((o) => o.text)).toContain('Fixed-size list control');
    // A static row has no type select.
    const headline = row('Sales overview headline');
    expect((within(headline).getByRole('radio', { name: 'Static' }) as HTMLInputElement).checked).toBe(true);
    expect(within(headline).queryByRole('combobox')).toBeNull();
    // No preselected approval: the review asks.
    expect(screen.queryByText(/^Approved:/)).toBeNull();
    expect(screen.getByText('Your changes are sent when you approve.')).toBeTruthy();
    expect(screen.getByLabelText('Note for the planner')).toBeTruthy();
  });

  it('marks a row that differs from proposed as Changed, with Reset back to the proposal', async () => {
    await panel();
    const map = row('Decorative map illustration');
    expect(within(map).queryByText('Changed')).toBeNull();
    fireEvent.click(within(map).getByRole('radio', { name: 'Static' }));
    expect(within(map).getByText('Changed')).toBeTruthy();
    expect(within(map).queryByRole('combobox')).toBeNull();
    fireEvent.click(within(map).getByRole('radio', { name: 'Native' }));
    expect(within(map).queryByText('Changed')).toBeNull();
    fireEvent.change(within(map).getByRole('combobox'), { target: { value: 'image' } });
    expect(within(map).getByText('Changed')).toBeTruthy();
    fireEvent.click(within(map).getByRole('button', { name: /^Reset/ }));
    expect(within(map).queryByText('Changed')).toBeNull();
    expect((within(map).getByRole('combobox') as HTMLSelectElement).value).toBe('geo_map');
    expect(document.activeElement).toBe(within(map).getByRole('radio', { name: 'Native' }));
  });

  it('approves an unedited analysis with its revision and no PUT, once', async () => {
    await panel();
    const put = vi.spyOn(api, 'updateReferenceAnalysis');
    const approve = vi.spyOn(api, 'approveReferenceAnalysis');
    act(() => {
      fireEvent.click(approveButton());
      fireEvent.click(approveButton());
    });
    await screen.findByText('Approved: 5 native, 1 static');
    expect(put).not.toHaveBeenCalled();
    expect(approve).toHaveBeenCalledTimes(1);
    expect(approve).toHaveBeenCalledWith(id, 1);
    expect(document.activeElement).toBe(screen.getByText('Approved: 5 native, 1 static'));
    expect(screen.getByRole('button', { name: 'Edit split' })).toBeTruthy();
  });

  it('sends an edited split with PUT first, then approves the revision the PUT returned', async () => {
    await panel();
    const put = vi.spyOn(api, 'updateReferenceAnalysis');
    const approve = vi.spyOn(api, 'approveReferenceAnalysis');
    fireEvent.click(within(row('Decorative map illustration')).getByRole('radio', { name: 'Static' }));
    fireEvent.focus(within(row('Decorative map illustration')).getByRole('radio', { name: 'Static' }));
    expect(box()).not.toBeNull();
    fireEvent.change(screen.getByLabelText('Note for the planner'), { target: { value: 'Draw the map as art.' } });
    fireEvent.click(approveButton());
    await screen.findByText('Approved: 4 native, 2 static');
    // The collapsed line leaves no box on the image.
    expect(box()).toBeNull();
    expect(put).toHaveBeenCalledTimes(1);
    expect(put).toHaveBeenCalledWith(id, {
      revision: 1,
      items: analysis.items.map(({ id: itemId, disposition, type }) => (itemId === 'r6' ? { id: itemId, disposition: 'static', type: null } : { id: itemId, disposition, type })),
      note: 'Draw the map as art.',
    });
    expect(approve).toHaveBeenCalledWith(id, 2);
    expect(put.mock.invocationCallOrder[0]!).toBeLessThan(approve.mock.invocationCallOrder[0]!);
  });

  it('shows an issue on its row and keeps Approve off until that row changes', async () => {
    const set = pending();
    set.analysis!.items[5] = { ...set.analysis!.items[5]!, type: null };
    set.analysis!.issues = [{ path: '/items/5/type', message: 'Choose a Data Studio component type, or keep this item as static art.' }];
    await panel(set);
    const map = row('Decorative map illustration');
    expect(within(map).getByText('Choose a Data Studio component type, or keep this item as static art.')).toBeTruthy();
    expect(within(map).getByRole('combobox').getAttribute('aria-describedby')).toBeTruthy();
    expect(off(approveButton())).toBe(true);
    fireEvent.click(within(map).getByRole('radio', { name: 'Static' }));
    expect(off(approveButton())).toBe(false);
  });

  it('keeps Approve off when a PUT returns issues; the approve call waits for them', async () => {
    // A static row with no type to fall back to: switched to Native, it asks for a type.
    const set = pending();
    set.analysis!.items[5] = { ...set.analysis!.items[5]!, type: null, proposed: { disposition: 'static', type: null }, disposition: 'static' };
    await panel(set);
    const approve = vi.spyOn(api, 'approveReferenceAnalysis');
    fireEvent.click(within(row('Decorative map illustration')).getByRole('radio', { name: 'Native' }));
    expect((within(row('Decorative map illustration')).getByRole('combobox') as HTMLSelectElement).value).toBe('');
    fireEvent.click(approveButton());
    await within(row('Decorative map illustration')).findByText(/Choose a Data Studio component type/);
    expect(document.activeElement).toBe(within(row('Decorative map illustration')).getByRole('radio', { name: 'Native' }));
    expect(approve).not.toHaveBeenCalled();
    expect(off(approveButton())).toBe(true);
  });

  it('refetches on a 409 reference_analysis_conflict, says so and keeps the unsaved edits', async () => {
    await panel();
    fireEvent.click(within(row('Region filter')).getByRole('radio', { name: 'Static' }));
    // Another window saved a new revision.
    const newer = pending();
    newer.analysis!.revision = 2;
    setMockReferences(id, newer);
    const get = vi.spyOn(api, 'getReferences');
    fireEvent.click(approveButton());
    await screen.findByText(CONFLICT_NOTE);
    expect(get).toHaveBeenCalled();
    // Focus returns to Approve (it was disabled while saving).
    await waitFor(() => expect(document.activeElement).toBe(approveButton()));
    expect(within(row('Region filter')).getByText('Changed')).toBeTruthy();
    const put = vi.spyOn(api, 'updateReferenceAnalysis');
    fireEvent.click(approveButton());
    await screen.findByText('Approved: 4 native, 2 static');
    expect(put.mock.calls[0]?.[1].revision).toBe(2);
  });

  it('draws the hovered or focused row box over the fixed thumbnail', async () => {
    await panel();
    expect(box()).toBeNull();
    const line = row('Monthly revenue line');
    fireEvent.mouseEnter(line);
    expect(box()?.style.left).toBe('2%');
    expect(box()?.style.top).toBe('30%');
    expect(box()?.style.width).toBe('60%');
    expect(box()?.style.height).toBe('40%');
    fireEvent.mouseLeave(line);
    expect(box()).toBeNull();
    const table = row('Regional sales table');
    fireEvent.focus(within(table).getByRole('radio', { name: 'Native' }));
    expect(box()?.style.left).toBe('64%');
    fireEvent.blur(within(table).getByRole('radio', { name: 'Native' }));
    expect(box()).toBeNull();
    // The frame keeps its size; only the Enlarge button changes it.
    const frame = screen.getByRole('img').parentElement!;
    expect(frame.className).toContain('w-32');
    fireEvent.click(screen.getByRole('button', { name: 'Enlarge the reference image' }));
    expect(frame.className).toContain('w-120');
  });

  it('collapses an approved analysis to one line; Edit split warns before reopening the rows', async () => {
    await panel(approved());
    expect(screen.getByText('Approved: 4 native, 2 static')).toBeTruthy();
    expect(screen.queryByRole('list', { name: 'Reference items' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Edit split' }));
    expect(screen.getByText(`${STALE_WARNING}.`)).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Edit split' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit split' }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(screen.getByRole('list', { name: 'Reference items' })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: fixtures.referenceSet.analysis!.summary }));
    // State stays approved until the edited split is approved: nothing was sent yet.
    expect((await api.getReferences(id))!.analysis!.state).toBe('approved');
    fireEvent.click(within(row('Decorative map illustration')).getByRole('radio', { name: 'Native' }));
    fireEvent.change(within(row('Decorative map illustration')).getByRole('combobox'), { target: { value: 'geo_map' } });
    fireEvent.click(approveButton());
    await screen.findByText('Approved: 5 native, 1 static');
  });

  it('shows no review for a style set or without references; a pre-1.3 recreate set asks for a new upload', async () => {
    await panel({ ...approved(), mode: 'style', analysis: null });
    expect(screen.queryByText('Proceed?')).toBeNull();
    expect(screen.queryByText(/^Approved:/)).toBeNull();
    cleanup();
    setMockReferences(id, null);
    render(<ReferencePanel buildId={id} />);
    await screen.findByText(/No references yet/);
    expect(screen.queryByText('Proceed?')).toBeNull();
    cleanup();
    await panel({ ...approved(), analysis: null });
    expect(screen.getByText('Upload the reference again to analyze it.')).toBeTruthy();
  });
});

describe('Reference analysis gate', () => {
  it('keeps Confirm design off with the reason; Review it focuses the review heading', async () => {
    inDesign();
    setMockArtifact(id, 'design', fixtures.design);
    setMockReferences(id, pending());
    const confirm = vi.spyOn(api, 'confirmDesign');
    workspace();
    const button = await screen.findByRole('button', { name: 'Confirm design' });
    await screen.findByRole('heading', { name: analysis.summary });
    await waitFor(() => expect(off(button)).toBe(true));
    expect(screen.getByText(new RegExp(ANALYSIS_GATE_REASON))).toBeTruthy();
    expect(button.getAttribute('aria-describedby')).toBe('design-analysis-gate');
    fireEvent.click(button);
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Review it' }));
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: analysis.summary }));
    // Approving opens the gate.
    fireEvent.click(approveButton());
    await screen.findByText('Approved: 5 native, 1 static');
    await waitFor(() => expect(off(button)).toBe(false));
    expect(screen.queryByText(new RegExp(ANALYSIS_GATE_REASON))).toBeNull();
  });

  it('keeps Regenerate and Accept blueprint off while pending', async () => {
    inBlueprint();
    setMockReferences(id, pending());
    workspace();
    const accept = await screen.findByRole('button', { name: 'Accept blueprint' });
    await screen.findByRole('heading', { name: analysis.summary });
    await waitFor(() => expect(off(screen.getByRole('button', { name: 'Regenerate' }))).toBe(true));
    expect(off(accept)).toBe(true);
    expect(screen.getByText(new RegExp(ANALYSIS_GATE_REASON))).toBeTruthy();
  });

  it('keeps Generate recipe and Build off in the Build view while pending', async () => {
    setMockReferences(id, pending());
    const compile = vi.spyOn(api, 'compileRecipe');
    workspace();
    const next = await screen.findByRole('button', { name: 'Continue to build' });
    await waitFor(() => expect(off(next)).toBe(false));
    fireEvent.click(next);
    await screen.findByRole('button', { name: 'Back to prototype' });
    await screen.findByRole('heading', { name: analysis.summary });
    expect(off(screen.getByRole('button', { name: 'Generate recipe' }))).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Build in Data Studio' }))).toBe(true);
    expect(screen.getByText(new RegExp(ANALYSIS_GATE_REASON))).toBeTruthy();
    expect(compile).not.toHaveBeenCalled();
  });

  it('moves focus to the review when any action answers 409 reference_unapproved', async () => {
    inDesign();
    setMockArtifact(id, 'design', fixtures.design);
    setMockReferences(id, approved());
    workspace();
    const button = await screen.findByRole('button', { name: 'Confirm design' });
    await screen.findByText('Approved: 4 native, 2 static');
    await waitFor(() => expect(off(button)).toBe(false));
    // Another window reopened the analysis; this one still shows it approved.
    setMockReferences(id, pending());
    fireEvent.click(button);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { name: analysis.summary })));
    expect(off(button)).toBe(true);
  });

  it('ungates a style set and a build without references', async () => {
    inDesign();
    setMockArtifact(id, 'design', fixtures.design);
    setMockReferences(id, { ...approved(), mode: 'style', analysis: null });
    workspace();
    const button = await screen.findByRole('button', { name: 'Confirm design' });
    await screen.findByRole('img');
    await waitFor(() => expect(off(button)).toBe(false));
    expect(screen.queryByText(new RegExp(ANALYSIS_GATE_REASON))).toBeNull();
  });

  it('gates a pre-1.3 recreate set (analysis null)', async () => {
    inDesign();
    setMockArtifact(id, 'design', fixtures.design);
    setMockReferences(id, { ...approved(), analysis: null });
    workspace();
    const button = await screen.findByRole('button', { name: 'Confirm design' });
    await screen.findByText('Upload the reference again to analyze it.');
    await waitFor(() => expect(off(button)).toBe(true));
  });
});

describe('Blueprint rows that recreate a reference item', () => {
  it('show "Recreates: <item label>" under the component label', async () => {
    inBlueprint();
    setMockReferences(id, approved());
    const blueprint = structuredClone(fixtures.blueprint);
    blueprint.rows[0] = { ...blueprint.rows[0]!, reference_item: 'r3' };
    setMockArtifact(id, 'blueprint', blueprint);
    workspace();
    await screen.findByRole('table', { name: /^Blueprint/ });
    expect(await screen.findByText('Recreates: Monthly revenue line')).toBeTruthy();
    expect(screen.getAllByText(/^Recreates:/)).toHaveLength(1);
  });
});
