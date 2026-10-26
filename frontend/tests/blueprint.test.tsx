import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChartArea, ChartBar, ChartColumn, ListChecks, Shapes } from 'lucide-react';
import { api, httpApi } from '../src/api/client';
import type { Assessment, Build } from '../src/api/types';
import type { BlueprintComponent } from '../src/api/types';
import { chartType } from '../src/features/workspace/blueprint/BlueprintTable';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { mockRatioIssue, patchMockBuild, resetMockState, setMockArtifact, setMockAssessment, setMockBlueprintBlocked, setMockRunFailure } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const id = fixtures.build.id;
const off = (el: HTMLElement) => el.matches(':disabled');
const accept = () => screen.getByRole('button', { name: 'Accept blueprint' });
const regenerate = () => screen.getByRole('button', { name: 'Regenerate' });
const table = () => screen.getByRole('table', { name: /^Blueprint/ });
const ratio = mockRatioIssue();
const blockedAssessment: Assessment = { id: 'assessment_ratio', state: 'blocked', input_digest: 'digest_ratio', prototype_stale: false, issues: [ratio], pending_comments: null };
const inBlueprint = (artifacts: Partial<Build['artifacts']> = {}) =>
  patchMockBuild(id, { stage: 'blueprint', spec_version: null, artifacts: { context: 'confirmed', outline: 'confirmed', design: 'confirmed', blueprint: 'draft', ...artifacts } });

async function renderBlueprint() {
  render(
    <MemoryRouter initialEntries={[`/builds/${id}`]}>
      <Routes>
        <Route path="/builds/:id" element={<WorkspaceShell />} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByRole('table', { name: /^Blueprint/ });
}

/** The data row of a question (its text, read from the outline), and the row under it. */
async function rowOf(question: string) {
  const header = await within(table()).findByRole('rowheader', { name: new RegExp(`^${question.replace(/[?()]/g, '\\$&')}`) });
  const row = header.closest('tr')!;
  return { row, next: row.nextElementSibling as HTMLElement | null };
}

describe('Blueprint table', () => {
  it('groups the rows by page, with the question, chart type, fields, page and status', async () => {
    inBlueprint();
    await renderBlueprint();
    const groups = [...table().querySelectorAll('tbody > tr > th[scope="rowgroup"]')];
    expect(groups.map((th) => th.textContent)).toEqual([
      'Page 1 · Revenue snapshot',
      'Page 2 · Where revenue comes from',
    ]);
    const { row } = await rowOf('Which product categories bring the most net revenue?');
    const cells = within(row).getAllByRole('cell').map((c) => c.textContent);
    expect(cells).toEqual(['Bar chart (horizontal)', 'categorySUM(revenue)sort: revenue desc', '2', 'OK']);
    const orders = await rowOf('What is the average order value?');
    expect(within(orders.row).getAllByRole('cell')[1]!.textContent).toBe('COUNT(DISTINCT order_id)');
    // The supporting control has no question.
    expect(within(table()).getByRole('rowheader', { name: /^Supporting control/ })).toBeTruthy();
    expect(screen.queryByRole('group', { name: ratio.requirement })).toBeNull();
    expect(off(accept())).toBe(false);
  });

  it('expands the blocked ratio row into its issue: Use this alternative / Drop this requirement, Accept stays disabled until ready', async () => {
    inBlueprint();
    setMockArtifact(id, 'blueprint', fixtures.blueprintBlocked);
    setMockAssessment(id, blockedAssessment);
    await renderBlueprint();
    const { row, next } = await rowOf('What is the average order value?');
    expect(row.dataset.rowStatus).toBe('blocked');
    expect(within(row).getByText('Blocked')).toBeTruthy();
    const issue = await within(next!).findByRole('group', { name: ratio.requirement });
    expect(within(issue).getByText(ratio.reason)).toBeTruthy();
    expect(within(issue).getByRole('button', { name: 'Use this alternative' })).toBeTruthy();
    expect(within(issue).getByRole('button', { name: 'Drop this requirement' })).toBeTruthy();
    // Shown once: under its row, not again in the panel.
    expect(screen.getAllByRole('button', { name: 'Drop this requirement' })).toHaveLength(1);
    expect(screen.getByText('Resolve each blocked row below before accepting the blueprint.')).toBeTruthy();
    expect(screen.getByText('1 blocked row')).toBeTruthy();
    expect(off(accept())).toBe(true);
    // No preselected acceptance.
    const use = within(issue).getByRole('button', { name: 'Use this alternative' });
    expect(off(use)).toBe(true);

    const decide = vi.spyOn(api, 'decideFeasibility');
    const read = vi.spyOn(api, 'getBlueprint');
    fireEvent.click(within(issue).getByRole('radio', { name: ratio.alternatives[0]!.label }));
    expect(off(use)).toBe(false);
    fireEvent.click(use);
    expect(decide).toHaveBeenCalledWith(id, blockedAssessment.id, [{ issue_id: ratio.id, action: 'accept_alternative', alternative_id: ratio.alternatives[0]!.id }]);
    await waitFor(() => expect(off(accept())).toBe(false));
    // The server rewrote the row without artifact.updated (as the live backend does): the stage reads it again.
    expect(read).toHaveBeenCalled();
    await waitFor(async () => expect((await rowOf('What is the average order value?')).row.dataset.rowStatus).toBe('ok'));
    expect(screen.queryByRole('group', { name: ratio.requirement })).toBeNull();
    expect(screen.queryByText('1 blocked row')).toBeNull();
  });

  it('a blocked row the server keeps after a decision shows it resolved, with the choice', async () => {
    const other = { ...ratio, id: 'i_other' };
    inBlueprint();
    setMockArtifact(id, 'blueprint', { ...fixtures.blueprintBlocked, rows: fixtures.blueprintBlocked.rows.map((r) => (r.status === 'blocked' ? { ...r, issue_ids: [other.id] } : r)) });
    setMockAssessment(id, { ...blockedAssessment, issues: [other] });
    await renderBlueprint();
    const { row, next } = await rowOf('What is the average order value?');
    fireEvent.click(await within(next!).findByRole('radio', { name: other.alternatives[0]!.label }));
    fireEvent.click(within(next!).getByRole('button', { name: 'Use this alternative' }));
    await waitFor(() => expect(off(accept())).toBe(false));
    expect(within(row).getByText('Resolved')).toBeTruthy();
    expect(within(next!).getByText(other.requirement).closest('p')?.textContent).toBe(`Alternative accepted: ${other.requirement}`);
    expect(screen.queryByText('1 blocked row')).toBeNull();
  });

  it('two blocked rows sharing an issue: the first holds the decision, the second points to it', async () => {
    inBlueprint();
    const blocked = fixtures.blueprintBlocked.rows.find((r) => r.status === 'blocked')!;
    const twin = { ...blocked, question_id: 'q3', component: { ...blocked.component, label: 'AOV by month' } };
    setMockArtifact(id, 'blueprint', { ...fixtures.blueprintBlocked, rows: [...fixtures.blueprintBlocked.rows, twin] });
    setMockAssessment(id, blockedAssessment);
    await renderBlueprint();
    const first = await rowOf('What is the average order value?');
    expect(await within(first.next!).findByRole('group', { name: ratio.requirement })).toBeTruthy();
    const twinRow = [...table().querySelectorAll<HTMLElement>('tr[data-row-status="blocked"]')].find((r) => r.textContent?.includes('AOV by month'))!;
    expect((twinRow.nextElementSibling as HTMLElement).textContent).toBe(`Decided with “${blocked.component.label}” above.`);
    expect(screen.getAllByRole('group', { name: ratio.requirement })).toHaveLength(1);
  });

  it('dropping the requirement also resolves the row', async () => {
    inBlueprint();
    setMockArtifact(id, 'blueprint', fixtures.blueprintBlocked);
    setMockAssessment(id, blockedAssessment);
    await renderBlueprint();
    const { next } = await rowOf('What is the average order value?');
    const decide = vi.spyOn(api, 'decideFeasibility');
    fireEvent.click(await within(next!).findByRole('button', { name: 'Drop this requirement' }));
    expect(decide).toHaveBeenCalledWith(id, blockedAssessment.id, [{ issue_id: ratio.id, action: 'drop', alternative_id: null }]);
    await waitFor(() => expect(off(accept())).toBe(false));
    await waitFor(() => expect(within(table()).queryByRole('rowheader', { name: /^What is the average order value\?/ })).toBeNull());
  });

  it('a regenerated draft keeps the decision: the accepted alternative replaces the blocked row', async () => {
    inBlueprint();
    setMockBlueprintBlocked(true);
    setMockArtifact(id, 'blueprint', fixtures.blueprintBlocked);
    setMockAssessment(id, blockedAssessment);
    await renderBlueprint();
    const { next } = await rowOf('What is the average order value?');
    fireEvent.click(await within(next!).findByRole('radio', { name: ratio.alternatives[0]!.label }));
    fireEvent.click(within(next!).getByRole('button', { name: 'Use this alternative' }));
    await waitFor(() => expect(off(regenerate())).toBe(false));
    fireEvent.click(regenerate());
    await waitFor(async () => expect((await rowOf('What is the average order value?')).row.dataset.rowStatus).toBe('ok'));
    expect(screen.queryByRole('group', { name: ratio.requirement })).toBeNull();
  });

  it('Regenerate and Accept post their actions; Accept moves the build to the prototype', async () => {
    inBlueprint();
    const regen = vi.spyOn(api, 'regenerateBlueprint');
    const acc = vi.spyOn(api, 'acceptBlueprint');
    await renderBlueprint();
    fireEvent.click(regenerate());
    expect(regen).toHaveBeenCalledWith(id);
    await waitFor(() => expect(off(accept())).toBe(false));
    fireEvent.click(accept());
    expect(acc).toHaveBeenCalledWith(id);
    await screen.findByText('Click any part of the prototype to comment on it.');
    expect((await api.getBuild(id)).stage).toBe('prototype');
  });

  it('the HTTP client posts regenerate and accept to their routes', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify(fixtures.runAccepted), { status: 202, headers: { 'content-type': 'application/json' } }));
    await httpApi.regenerateBlueprint('b_1');
    await httpApi.acceptBlueprint('b_1');
    const calls = fetch.mock.calls.map(([url, init]) => `${init?.method} ${String(url)}`);
    expect(calls).toEqual(['POST /api/builds/b_1/blueprint/regenerate', 'POST /api/builds/b_1/blueprint/accept']);
  });

  it('a failed accept stays in Blueprint with the run error and Retry above the table', async () => {
    inBlueprint();
    setMockRunFailure('prototype', 'The prototype did not render. Try again.');
    await renderBlueprint();
    await waitFor(() => expect(off(accept())).toBe(false));
    fireEvent.click(accept());
    const alert = await screen.findByText('The prototype did not render. Try again.');
    const error = alert.closest('[role="alert"]') ?? alert.parentElement!;
    expect(within(error.parentElement!).getByRole('button', { name: /Try again|Retry/ })).toBeTruthy();
    // ErrorState sits before the table in the document.
    expect(error.compareDocumentPosition(table()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect((await api.getBuild(id)).stage).toBe('blueprint');
  });

  it('a blueprint made stale by an earlier edit says why', async () => {
    inBlueprint({ outline: 'confirmed', design: 'confirmed', blueprint: 'stale' });
    await renderBlueprint();
    const heading = screen.getByRole('heading', { level: 2, name: 'Blueprint' });
    expect(heading.parentElement?.textContent).toMatch(/Stale.*Changed:/);
  });
});

describe('chartType labels', () => {
  const comp = (type: string, options: Record<string, unknown> = {}): BlueprintComponent => ({
    type, label: 'x', dimensions: [], metrics: [], date_dimension: null, breakdown: null, sort: null, options,
  });
  it('names area charts, fixed-size lists and 100% stacked bars', () => {
    expect(chartType(comp('area'))).toEqual({ label: 'Area chart', icon: ChartArea });
    expect(chartType(comp('fixed_size_list'))).toEqual({ label: 'Fixed-size list control', icon: ListChecks });
    expect(chartType(comp('bar', { stacked_percent: true }))).toEqual({ label: 'Bar chart (100% stacked)', icon: ChartColumn });
    expect(chartType(comp('bar', { orientation: 'horizontal', stacked_percent: true }))).toEqual({ label: 'Bar chart (horizontal, 100% stacked)', icon: ChartBar });
  });
  it('keeps existing labels', () => {
    expect(chartType(comp('bar')).label).toBe('Bar chart');
    expect(chartType(comp('bar', { orientation: 'horizontal' })).label).toBe('Bar chart (horizontal)');
    expect(chartType(comp('pivot_table')).label).toBe('Pivot table');
    expect(chartType(comp('mystery'))).toEqual({ label: 'mystery', icon: Shapes });
  });
});
