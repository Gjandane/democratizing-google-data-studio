import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { Build, Stage } from '../src/api/types';
import { STAGE_LABELS, Stepper } from '../src/features/workspace/Stepper';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { patchMockBuild, resetMockState } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const withState = (stage: Stage, artifacts: Build['artifacts'], spec_version: number | null = null): Build => ({ ...fixtures.build, stage, artifacts, spec_version });
const steps = () => screen.getAllByRole('listitem');
const step = (stage: Stage) => steps().find((li) => li.textContent?.startsWith(STAGE_LABELS[stage]) || li.textContent?.includes(STAGE_LABELS[stage]))!;

describe('Stepper', () => {
  it('shows the eight stages, the current one, and draft/confirmed per artifact step', () => {
    render(<Stepper build={withState('outline', { context: 'confirmed', outline: 'draft', design: 'missing', blueprint: 'missing' })} />);
    expect(steps().map((li) => li.textContent?.replace(/\(.*\)/, '').replace(/^\d/, ''))).toEqual([
      'Connect', 'Context', 'Outline', 'Design', 'Blueprint', 'Prototype', 'Build', 'Done',
    ]);
    expect(steps().map((li) => li.dataset.artifact ?? '-')).toEqual(['-', 'confirmed', 'draft', '-', '-', '-', '-', '-']);
    expect(step('outline').getAttribute('aria-current')).toBe('step');
    expect(step('context').textContent).toContain('(confirmed)');
    expect(step('outline').textContent).toContain('(draft)');
    expect(step('connect').textContent).toContain('(done)');
  });

  it('marks stale steps with why, including a prototype built from a changed step', () => {
    render(<Stepper build={withState('outline', { context: 'confirmed', outline: 'draft', design: 'stale', blueprint: 'stale' }, 2)} />);
    expect(step('design').dataset.artifact).toBe('stale');
    expect(step('design').textContent).toContain('stale, Changed: Outline');
    expect(step('blueprint').textContent).toContain('Changed: Outline');
    expect(step('prototype').dataset.artifact).toBe('stale');
    expect(within(step('design')).getByTitle('Changed: Outline')).toBeTruthy();
  });

  it('names the step re-confirmed since as the reason', () => {
    render(<Stepper build={withState('outline', { context: 'confirmed', outline: 'stale', design: 'stale', blueprint: 'missing' })} />);
    expect(step('outline').textContent).toContain('Changed: Context');
    expect(step('design').textContent).toContain('Changed: Context');
  });

  it('reopens a confirmed step: reached steps are buttons, missing, build and done steps are not', () => {
    const onSelect = vi.fn();
    render(<Stepper build={withState('design', { context: 'confirmed', outline: 'confirmed', design: 'draft', blueprint: 'missing' })} onSelect={onSelect} />);
    const buttons = screen.getAllByRole('button').map((b) => b.textContent?.replace(/\(.*\)/, '').replace(/^\d+/, ''));
    expect(buttons).toEqual(['Context', 'Outline']);
    fireEvent.click(within(step('context')).getByRole('button'));
    expect(onSelect).toHaveBeenCalledWith('context');
  });

  it('while another step is open, the current stage is a button back to it', () => {
    const onSelect = vi.fn();
    render(<Stepper build={withState('design', { context: 'confirmed', outline: 'confirmed', design: 'draft', blueprint: 'missing' })} viewing="context" onSelect={onSelect} />);
    expect(step('context').textContent).toContain('open');
    fireEvent.click(within(step('design')).getByRole('button'));
    expect(onSelect).toHaveBeenCalledWith('design');
  });
});

function renderWorkspace(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/builds/${id}`]}>
      <Routes>
        <Route path="/builds/:id" element={<WorkspaceShell />} />
      </Routes>
    </MemoryRouter>,
  );
}

const stageHeading = () => within(screen.getByRole('main')).getAllByRole('heading', { level: 2 })[0]!.textContent;
const nav = () => screen.getByRole('navigation', { name: 'Build stages' });

describe('Workspace with the staged stepper', () => {
  it('shows the activity column with no chat input', async () => {
    renderWorkspace(fixtures.build.id);
    const column = await screen.findByRole('complementary', { name: 'Activity' });
    expect(within(column).queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Send' })).toBeNull();
  });

  it('reopens a confirmed step from the prototype, then returns to the current stage', async () => {
    renderWorkspace(fixtures.build.id);
    await waitFor(() => expect(stageHeading()).toBe('Prototype'));
    fireEvent.click(within(nav()).getByRole('button', { name: /^.?Context/ }));
    await waitFor(() => expect(stageHeading()).toBe('Context'));
    const main = screen.getByRole('main');
    expect(document.activeElement).toBe(main);
    expect(main.querySelector('[data-badge="confirmed"]')).not.toBeNull();
    await within(main).findByText(fixtures.context.goal);
    expect(within(main).getByText(/You reopened this step/)).toBeTruthy();
    expect((within(main).getByRole('button', { name: 'Confirm context' }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(main).getByText(`Revision ${fixtures.context.revision}`)).toBeTruthy();

    fireEvent.click(within(nav()).getByRole('button', { name: /^.?Prototype/ }));
    await waitFor(() => expect(stageHeading()).toBe('Prototype'));
  });

  it('walks a new build from context to blueprint through the stage areas', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    await api.uploadSources(created.id, [new File(['a'], 'sales.csv', { type: 'text/csv' })]);
    await api.draftContext(created.id);
    await waitFor(async () => expect((await api.getBuild(created.id)).artifacts.context).toBe('draft'));
    renderWorkspace(created.id);
    await waitFor(() => expect(stageHeading()).toBe('Context'));
    await within(screen.getByRole('main')).findByText(fixtures.context.goal);
    expect(within(screen.getByRole('main')).getByText('No open issues')).toBeTruthy();

    fireEvent.click(within(screen.getByRole('main')).getByRole('button', { name: 'Confirm context' }));
    await waitFor(() => expect(stageHeading()).toBe('Outline'));
    await within(screen.getByRole('main')).findByText(/of 24 selected/);
    expect(step('context').dataset.artifact).toBe('confirmed');
    const confirmOutline = await within(screen.getByRole('main')).findByRole('button', { name: 'Confirm outline' });
    await waitFor(() => expect((confirmOutline as HTMLButtonElement).disabled).toBe(false));

    fireEvent.click(confirmOutline);
    await waitFor(() => expect(stageHeading()).toBe('Design'));
    await within(screen.getByRole('main')).findByText('accent #1D4ED8');
    const confirmDesign = await within(screen.getByRole('main')).findByRole('button', { name: 'Confirm design' });
    await waitFor(() => expect((confirmDesign as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(confirmDesign);
    await waitFor(() => expect(stageHeading()).toBe('Blueprint'));
    await within(screen.getByRole('main')).findByText('Page 1');
    expect(step('design').dataset.artifact).toBe('confirmed');
    expect(step('blueprint').dataset.artifact).toBe('draft');
  });

  it('shows a draft context with its open issues and keeps Confirm off', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    await api.uploadSources(created.id, [new File(['a'], 'sales.csv', { type: 'text/csv' })]);
    await api.draftContext(created.id);
    await waitFor(async () => expect((await api.getBuild(created.id)).artifacts.context).toBe('draft'));
    await api.updateContext(created.id, { ...fixtures.context, thresholds: [{ ...fixtures.context.thresholds[0]!, field: 'weight' }] });
    patchMockBuild(created.id, { stage: 'context' });
    renderWorkspace(created.id);
    await waitFor(() => expect(stageHeading()).toBe('Context'));
    const main = screen.getByRole('main');
    await within(main).findByText('1 open issue');
    expect(within(main).getByRole('list', { name: 'Open issues' }).textContent).toContain('/thresholds/0/field');
    expect((within(main).getByRole('button', { name: 'Confirm context' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
