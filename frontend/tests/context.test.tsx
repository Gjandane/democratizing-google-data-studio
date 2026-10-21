import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { Build, ValidationIssue } from '../src/api/types';
import { ArtifactStage } from '../src/features/workspace/ArtifactStage';
import { ConnectStage } from '../src/features/workspace/connect/ConnectStage';
import { aggsFor, placeIssues } from '../src/features/workspace/context/model';
import { patchMockBuild, resetMockState, setMockArtifact } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const off = (el: HTMLElement) => (el as HTMLButtonElement).disabled;
const type = (input: HTMLElement, value: string) => fireEvent.change(input, { target: { value } });
const options = (select: HTMLElement) => Array.from((select as HTMLSelectElement).options).map((o) => o.textContent);
const card = (name: string) => screen.getByRole('region', { name: `KPI ${name}` });
const describedText = (el: HTMLElement) =>
  (el.getAttribute('aria-describedby') ?? '')
    .split(' ')
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' ');

const idle = { artifactSeq: { context: 0, outline: 0, design: 0, blueprint: 0 }, running: null, runErrors: {} };

function ContextHolder({ initial }: { initial: Build }) {
  const [build, setBuild] = useState(initial);
  return <ArtifactStage build={build} name="context" stream={idle} acceptReady={false} onBuildChange={setBuild} />;
}

/** The fixture build in the context stage, with the fixture Context (plus `issues`) stored. */
async function renderContext(issues: ValidationIssue[] = []) {
  const id = fixtures.build.id;
  patchMockBuild(id, { stage: 'context', artifacts: { context: 'draft', outline: 'missing', design: 'missing', blueprint: 'missing' } });
  setMockArtifact(id, 'context', { ...fixtures.context, issues });
  const build = await api.getBuild(id);
  render(<ContextHolder initial={build} />);
  await screen.findByRole('region', { name: 'KPI Net revenue' });
  return build;
}

describe('Connect notes', () => {
  function ConnectHolder({ initial }: { initial: Build }) {
    const [build, setBuild] = useState(initial);
    return <ConnectStage build={build} onBuildChange={setBuild} />;
  }

  it('blocks notes over 4000 characters with a count, and sends notes with Draft context', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    await api.addSource(created.id, { kind: 'bigquery', uri: 'project.dataset.orders' });
    render(<ConnectHolder initial={await api.getBuild(created.id)} />);
    const notes = screen.getByRole('textbox', { name: 'Notes about this data' });
    const draft = screen.getByRole('button', { name: 'Draft context' });
    expect(screen.getByText('0 / 4,000 characters')).toBeTruthy();

    type(notes, 'x'.repeat(4001));
    expect(notes.getAttribute('aria-invalid')).toBe('true');
    expect(describedText(notes)).toContain('4,001 / 4,000 characters. Remove 1 to draft the context.');
    expect(off(draft)).toBe(true);

    type(notes, 'Revenue is net of discounts.');
    expect(screen.getByText('28 / 4,000 characters')).toBeTruthy();
    expect(off(draft)).toBe(false);
    const spy = vi.spyOn(api, 'draftContext');
    fireEvent.click(draft);
    await waitFor(() => expect(spy).toHaveBeenCalledWith(created.id, 'Revenue is net of discounts.'));
    await waitFor(async () => expect((await api.getBuild(created.id)).notes).toBe('Revenue is net of discounts.'));
  });

  it('shows saved notes', async () => {
    render(<ConnectHolder initial={{ ...fixtures.build, stage: 'connect' }} />);
    expect((screen.getByRole('textbox', { name: 'Notes about this data' }) as HTMLTextAreaElement).value).toBe(fixtures.build.notes);
  });
});

describe('Context editor', () => {
  it('filters aggregations by field type', () => {
    expect(aggsFor('number')).toEqual(['sum', 'avg', 'count', 'count_distinct', 'min', 'max']);
    expect(aggsFor('string')).toEqual(['count', 'count_distinct']);
    expect(aggsFor('date')).toEqual(['count', 'count_distinct', 'min', 'max']);
  });

  it('switches a KPI card between measure (field + agg filtered by type) and ratio (two KPI pickers)', async () => {
    const build = await renderContext();
    const put = vi.spyOn(api, 'updateContext');
    const net = card('Net revenue');
    const field = within(net).getByRole('combobox', { name: 'Field' });
    const agg = within(net).getByRole('combobox', { name: 'Aggregation' });
    expect((field as HTMLSelectElement).value).toBe('revenue');
    expect(options(agg)).toEqual(['Sum', 'Average', 'Count', 'Count distinct', 'Minimum', 'Maximum']);
    expect(within(net).getByText('SUM(revenue)')).toBeTruthy();

    fireEvent.change(field, { target: { value: 'customer_segment' } });
    expect(options(agg)).toEqual(['Count', 'Count distinct']);
    expect((agg as HTMLSelectElement).value).toBe('count_distinct');
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0]?.[1].kpis[0]?.measure).toEqual({ field: 'customer_segment', agg: 'count_distinct' });

    fireEvent.click(within(net).getByRole('radio', { name: 'Ratio of KPIs' }));
    expect(within(net).queryByRole('combobox', { name: 'Field' })).toBeNull();
    const numerator = within(net).getByRole('combobox', { name: 'Numerator' });
    const denominator = within(net).getByRole('combobox', { name: 'Denominator' });
    expect(options(numerator)).toEqual(['Orders', 'Units sold', 'Average order value']);
    expect((numerator as HTMLSelectElement).value).toBe('orders');
    expect((denominator as HTMLSelectElement).value).toBe('units_sold');
    fireEvent.change(denominator, { target: { value: 'avg_order_value' } });
    await waitFor(async () => expect((await api.getContext(build.id))?.kpis[0]).toMatchObject({ measure: null, ratio: { numerator: 'orders', denominator: 'avg_order_value' } }));

    fireEvent.click(within(net).getByRole('radio', { name: 'Measure' }));
    expect((within(net).getByRole('combobox', { name: 'Field' }) as HTMLSelectElement).value).toBe('customer_segment');
    await waitFor(async () => expect((await api.getContext(build.id))?.kpis[0]).toMatchObject({ measure: { field: 'customer_segment', agg: 'count_distinct' }, ratio: null }));

    const aov = card('Average order value');
    expect((within(aov).getByRole('radio', { name: 'Ratio of KPIs' }) as HTMLInputElement).checked).toBe(true);
    expect(options(within(aov).getByRole('combobox', { name: 'Numerator' }))).not.toContain('Average order value');
  });

  it('lands each issue path on its card and field, counts them in the footer and keeps Confirm off', async () => {
    await renderContext([
      { path: '/kpis/3/ratio/denominator', message: 'Pick another KPI as the denominator.' },
      { path: '/kpis/1', message: 'Pick a measure or a ratio, not both.' },
      { path: '/thresholds/0/field', message: 'Unknown field qty. Pick a column or a derived field.' },
      { path: '/kpis/0/measure/field', message: 'Shown on the card: this KPI is a measure.' },
    ]);
    const denominator = within(card('Average order value')).getByRole('combobox', { name: 'Denominator' });
    expect(denominator.getAttribute('aria-invalid')).toBe('true');
    expect(describedText(denominator)).toBe('Pick another KPI as the denominator.');
    expect(within(card('Orders')).getByText('Pick a measure or a ratio, not both.')).toBeTruthy();
    const thresholdField = screen.getByRole('combobox', { name: 'Field of Bulk order line' });
    expect(describedText(thresholdField)).toContain('Unknown field qty.');
    expect(describedText(within(card('Net revenue')).getByRole('combobox', { name: 'Field' }))).toContain('Shown on the card');
    expect(screen.getByText('4 open issues')).toBeTruthy();
    expect(off(screen.getByRole('button', { name: 'Confirm context' }))).toBe(true);
  });

  it('places an issue on the deepest shown path', () => {
    const placed = placeIssues(
      [{ path: '/kpis/0/measure/field', message: 'a' }, { path: '/kpis/9', message: 'b' }, { path: '/title', message: 'c' }],
      new Set(['/kpis', '/kpis/0', '/title']),
    );
    expect(placed.get('/kpis/0')?.[0]?.message).toBe('a');
    expect(placed.get('/kpis')?.[0]?.message).toBe('b');
    expect(placed.get('/title')?.[0]?.message).toBe('c');
  });

  it('shows the issues of a 409 artifact_invalid from Confirm', async () => {
    const build = await renderContext();
    const confirm = screen.getByRole('button', { name: 'Confirm context' });
    expect(off(confirm)).toBe(false);
    // The server found issues the loaded copy doesn't have yet.
    setMockArtifact(build.id, 'context', { ...fixtures.context, issues: [{ path: '/kpis/2/measure/field', message: 'Unknown field quantity.' }] });
    fireEvent.click(confirm);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Fix the open issues, then confirm again.');
    expect(within(alert).getByText('/kpis/2/measure/field')).toBeTruthy();
    expect(alert.textContent).toContain('Unknown field quantity.');
  });

  it('keeps focus in the edited field through a PUT, and keeps typing made while it ran', async () => {
    const build = await renderContext();
    const put = vi.spyOn(api, 'updateContext');
    const net = card('Net revenue');
    const agg = within(net).getByRole('combobox', { name: 'Aggregation' });
    agg.focus();
    fireEvent.change(agg, { target: { value: 'avg' } });
    expect(off(screen.getByRole('button', { name: 'Confirm context' }))).toBe(true);
    await waitFor(() => expect(off(screen.getByRole('button', { name: 'Confirm context' }))).toBe(false));
    expect(put).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(agg);
    expect(screen.getByText('Revision 3')).toBeTruthy();

    const name = within(net).getByRole('textbox', { name: 'Name' });
    const unit = within(net).getByRole('textbox', { name: 'Unit' });
    name.focus();
    type(name, 'Net sales');
    expect(put).toHaveBeenCalledTimes(1);
    unit.focus(); // blur saves the name
    expect(put).toHaveBeenCalledTimes(2);
    expect(unit.matches(':disabled')).toBe(false);
    type(unit, 'EUR'); // typed while the PUT runs
    await waitFor(() => expect(screen.getByText('Revision 4')).toBeTruthy());
    expect(document.activeElement).toBe(unit);
    expect((unit as HTMLInputElement).value).toBe('EUR');
    expect((await api.getContext(build.id))?.kpis[0]).toMatchObject({ name: 'Net sales', unit: 'USD' });
    name.focus();
    await waitFor(async () => expect((await api.getContext(build.id))?.kpis[0]?.unit).toBe('EUR'));
    expect(card('Net sales')).toBeTruthy();
  });

  it('gives each new threshold an unused id', async () => {
    const build = await renderContext();
    const add = screen.getByRole('button', { name: 'Add threshold' });
    fireEvent.click(add);
    await waitFor(async () => expect((await api.getContext(build.id))?.thresholds).toHaveLength(2));
    fireEvent.click(add);
    await waitFor(async () => expect((await api.getContext(build.id))?.thresholds).toHaveLength(3));
    fireEvent.click(screen.getByRole('button', { name: 'Remove threshold 2' }));
    await waitFor(async () => expect((await api.getContext(build.id))?.thresholds).toHaveLength(2));
    fireEvent.click(add);
    await waitFor(async () => expect((await api.getContext(build.id))?.thresholds).toHaveLength(3));
    const ids = (await api.getContext(build.id))!.thresholds.map((t) => t.id);
    expect(new Set(ids).size).toBe(3);
  });

  it('adds and removes rows with focus on the new row or the Add button', async () => {
    const build = await renderContext();
    fireEvent.click(screen.getByRole('button', { name: 'Add term' }));
    const term = screen.getByRole('textbox', { name: 'Term 3' });
    expect(document.activeElement).toBe(term);
    await waitFor(async () => expect((await api.getContext(build.id))?.glossary).toHaveLength(3));
    fireEvent.click(screen.getByRole('button', { name: 'Remove term 3' }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Add term' }));
    await waitFor(async () => expect((await api.getContext(build.id))?.glossary).toHaveLength(2));
  });

  it('disables every control while a run holds the lock', async () => {
    const id = fixtures.build.id;
    patchMockBuild(id, { stage: 'context', artifacts: { context: 'draft', outline: 'missing', design: 'missing', blueprint: 'missing' } });
    setMockArtifact(id, 'context', { ...fixtures.context, issues: [] });
    render(<ArtifactStage build={await api.getBuild(id)} name="context" stream={{ ...idle, running: 'context' }} acceptReady={false} onBuildChange={() => {}} />);
    const name = (await within(await screen.findByRole('region', { name: 'KPI Net revenue' })).findByRole('textbox', { name: 'Name' })) as HTMLInputElement;
    expect(name.closest('fieldset')?.disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Add KPI' }).matches(':disabled')).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Confirm context' }))).toBe(true);
  });

  it('shows loading, then the empty state without a context', async () => {
    const id = fixtures.build.id;
    patchMockBuild(id, { stage: 'context', artifacts: { context: 'missing', outline: 'missing', design: 'missing', blueprint: 'missing' } });
    setMockArtifact(id, 'context', null);
    render(<ContextHolder initial={await api.getBuild(id)} />);
    expect(screen.getByText('Loading the context…')).toBeTruthy();
    expect(await screen.findByText('No context yet')).toBeTruthy();
  });

  it('keeps the edit and offers Save again when a PUT fails', async () => {
    await renderContext();
    const put = vi.spyOn(api, 'updateContext').mockRejectedValueOnce(new Error('offline'));
    const desc = within(card('Orders')).getByRole('textbox', { name: 'Description' });
    desc.focus();
    type(desc, 'Unique orders.');
    screen.getByRole('textbox', { name: 'Title' }).focus();
    expect(await screen.findByText("Couldn't save your change")).toBeTruthy();
    expect((desc as HTMLInputElement).value).toBe('Unique orders.');
    // The server's copy lacks the edit: Confirm and Redraft wait for a successful save.
    expect(off(screen.getByRole('button', { name: 'Confirm context' }))).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Redraft' }))).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Save again' }));
    await waitFor(() => expect(screen.queryByText("Couldn't save your change")).toBeNull());
    await waitFor(() => expect(off(screen.getByRole('button', { name: 'Confirm context' }))).toBe(false));
    expect(put).toHaveBeenCalledTimes(2);
    expect((desc as HTMLInputElement).value).toBe('Unique orders.');
  });
});
