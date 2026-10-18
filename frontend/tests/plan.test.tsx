import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import { ApiError, type Build, type BuildEvent } from '../src/api/types';
import { useBuildStream } from '../src/features/workspace/chat/useBuildStream';
import { PlanStage } from '../src/features/workspace/plan/PlanStage';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { fixtures } from '../src/mocks/fixtures';
import { resetMockState } from '../src/mocks/api';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** A fake stream: tests push events through the captured handlers. */
function fakeStream() {
  const handlers: StreamHandlers[] = [];
  const open: OpenBuildEvents = (_id, h) => {
    handlers.push(h);
    return () => {};
  };
  const fire = (event: BuildEvent) => act(() => handlers.forEach((h) => h.onEvent(event)));
  return { open, fire };
}

function Holder({ initial, open }: { initial: Build; open: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, open);
  return build.stage === 'plan' ? <PlanStage build={build} progress={chat.progress} planning={chat.planning} /> : <p>Stage: {build.stage}</p>;
}

/** A build in the Plan stage with no docs yet; the mock's own docs exist once its plan run ends. */
async function setup() {
  const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
  await api.startInterview(created.id);
  await api.generatePlan(created.id);
  await waitFor(async () => expect((await api.getBuild(created.id)).docs.length).toBeGreaterThan(0));
  const build: Build = { ...(await api.getBuild(created.id)), stage: 'plan', docs: [] };
  const stream = fakeStream();
  render(<Holder initial={build} open={stream.open} />);
  return { build, ...stream };
}

const run = { run_id: 'r_1', node: 'plan' };
const progress = (text: string): BuildEvent => ({ name: 'node.progress', data: { ...run, text } });
const items = () => within(screen.getByRole('list', { name: 'Planner progress' })).getAllByRole('listitem').map((li) => li.textContent);

describe('Plan stage', () => {
  it('shows the waiting and empty states before the planner writes anything', async () => {
    await setup();
    expect(screen.getByRole('status').textContent).toContain('Waiting for the planner');
    expect(screen.getByRole('heading', { name: 'No docs yet' })).toBeTruthy();
    expect(screen.queryByRole('list', { name: 'Planner progress' })).toBeNull();
  });

  it('lists node.progress lines in order and starts over on a new run', async () => {
    const { fire } = await setup();
    await fire({ name: 'run.started', data: run });
    await fire(progress('Writing brief.md'));
    await fire(progress('Writing questions.md'));
    await fire(progress('Writing kpis.md'));
    expect(items()).toEqual(['Writing brief.md', 'Writing questions.md', 'Writing kpis.md']);
    expect(screen.queryByText('Waiting for the planner…')).toBeNull();

    await fire({ name: 'run.started', data: { run_id: 'r_2', node: 'plan' } });
    expect(screen.queryByRole('list', { name: 'Planner progress' })).toBeNull();
    await fire(progress('Writing design.md'));
    expect(items()).toEqual(['Writing design.md']);
  });

  it('lists the docs on docs.updated and shows the clicked one from GET /docs/{path}', async () => {
    const { build, fire } = await setup();
    const getDoc = vi.spyOn(api, 'getDoc');
    await fire({ name: 'docs.updated', data: { docs: fixtures.build.docs } });

    const list = screen.getByRole('list', { name: 'Build docs' });
    const buttons = within(list).getAllByRole('button');
    expect(buttons.map((b) => b.textContent)).toEqual(fixtures.build.docs.map((d) => `${d.title}${d.path}`));
    expect(screen.getByText('Select a doc to read it.')).toBeTruthy();
    expect(getDoc).not.toHaveBeenCalled();

    fireEvent.click(within(list).getByRole('button', { name: /KPI definitions/ }));
    expect(screen.getByRole('status').textContent).toContain('Loading kpis.md');
    expect(await screen.findByRole('heading', { name: 'KPI definitions' })).toBeTruthy();
    expect(getDoc).toHaveBeenCalledWith(build.id, 'kpis.md');
    expect(within(list).getByRole('button', { name: /KPI definitions/ }).getAttribute('aria-current')).toBe('true');
    expect(screen.getByRole('region', { name: 'KPI definitions' })).toBeTruthy();

    fireEvent.click(within(list).getByRole('button', { name: /Dashboard brief/ }));
    expect(await screen.findByRole('heading', { name: 'Dashboard brief' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'KPI definitions' })).toBeNull();
  });

  it('shows a doc error and loads it again on Try again', async () => {
    const { fire } = await setup();
    const getDoc = vi.spyOn(api, 'getDoc').mockRejectedValueOnce(new ApiError(404, 'doc_not_found', 'There is no brief.md yet.'));
    await fire({ name: 'docs.updated', data: { docs: fixtures.build.docs } });
    fireEvent.click(screen.getByRole('button', { name: /Dashboard brief/ }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('There is no brief.md yet.');
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Dashboard brief' })).toBeTruthy();
    expect(getDoc).toHaveBeenCalledTimes(2);
  });

  it('keeps the spinner on the last line while planning, even when docs already exist (re-plan)', async () => {
    const { fire } = await setup();
    await fire({ name: 'docs.updated', data: { docs: fixtures.build.docs } });
    await fire({ name: 'run.started', data: run });
    await fire(progress('Writing brief.md'));
    const spinner = () => screen.getByRole('list', { name: 'Planner progress' }).querySelector('[class~="motion-safe:animate-spin"]');
    expect(spinner()).not.toBeNull();
    await fire({ name: 'run.finished', data: { ...run, status: 'ok', error: null } });
    expect(spinner()).toBeNull();
  });

  it('ignores progress lines of other nodes, refetches an open doc on docs.updated and closes a doc that left the list', async () => {
    const { build, fire } = await setup();
    await fire({ name: 'run.started', data: { run_id: 'r_9', node: 'comments' } });
    await fire({ name: 'node.progress', data: { run_id: 'r_9', node: 'comments', text: 'Applying 2 comments' } });
    expect(screen.queryByText('Applying 2 comments')).toBeNull();

    await fire({ name: 'docs.updated', data: { docs: fixtures.build.docs } });
    const getDoc = vi.spyOn(api, 'getDoc');
    fireEvent.click(screen.getByRole('button', { name: /Dashboard brief/ }));
    await screen.findByRole('heading', { name: 'Dashboard brief' });
    await fire({ name: 'docs.updated', data: { docs: fixtures.build.docs.map((d) => ({ ...d })) } });
    await waitFor(() => expect(getDoc).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('heading', { name: 'Dashboard brief' })).toBeTruthy();

    await fire({ name: 'docs.updated', data: { docs: fixtures.build.docs.slice(1) } });
    expect(screen.queryByRole('heading', { name: 'Dashboard brief' })).toBeNull();
    await fire({ name: 'docs.updated', data: { docs: fixtures.build.docs } });
    expect(screen.getByText('Select a doc to read it.')).toBeTruthy();
    expect(getDoc).toHaveBeenCalledWith(build.id, 'brief.md');
  });

  it('switches the stage on stage.changed: prototype', async () => {
    const { fire } = await setup();
    expect(screen.getByRole('heading', { name: 'Build docs' })).toBeTruthy();
    await fire({ name: 'stage.changed', data: { stage: 'prototype' } });
    expect(screen.getByText('Stage: prototype')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Build docs' })).toBeNull();
  });
});

describe('Plan stage in the workspace', () => {
  it('mounts the Plan view for a build in the plan stage', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    const real = api.getBuild.bind(api);
    vi.spyOn(api, 'getBuild').mockImplementation(async (id) => ({ ...(await real(id)), stage: 'plan' as const, docs: [] }));
    render(
      <MemoryRouter initialEntries={[`/builds/${created.id}`]}>
        <Routes>
          <Route path="/builds/:id" element={<WorkspaceShell />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText('Waiting for the planner…')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'No docs yet' })).toBeTruthy();
  });

  it('follows a mock plan run from Interview through Plan to the Prototype stage', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    await api.startInterview(created.id);
    render(
      <MemoryRouter initialEntries={[`/builds/${created.id}`]}>
        <Routes>
          <Route path="/builds/:id" element={<WorkspaceShell />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByRole('heading', { level: 2, name: 'Interview' });
    await api.generatePlan(created.id);
    expect(await screen.findByRole('heading', { level: 2, name: 'Prototype' })).toBeTruthy();
    expect(screen.queryByRole('heading', { level: 2, name: 'Plan' })).toBeNull();
  });
});
