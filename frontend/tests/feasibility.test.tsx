import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import { ApiError, type Assessment, type BuildEvent, type Issue } from '../src/api/types';
import { FeasibilityPanel, type FeasibilityGates } from '../src/features/workspace/FeasibilityPanel';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { InterviewStage } from '../src/features/workspace/chat/InterviewStage';
import { BuildStage } from '../src/features/workspace/build/BuildStage';
import { idleRun } from '../src/features/workspace/build/buildRun';
import { publishWorkspace } from '../src/features/workspace/stretch';
import { presetFor } from '../src/features/activity/presets';
import { fixtures } from '../src/mocks/fixtures';
import { resetMockState, setMockAssessment } from '../src/mocks/api';

const id = fixtures.build.id;
const ready: Assessment = { id: 'ready_1', state: 'ready', input_digest: 'digest', prototype_stale: false, issues: [], pending_comments: null };
const unchecked: Assessment = { ...ready, id: null, state: 'unchecked', input_digest: null };
beforeEach(resetMockState);
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const fire = (event: BuildEvent) => act(() => publishWorkspace(id, event));
const finished = (run_id: string, node = 'capability_check'): BuildEvent => ({ name: 'run.finished', data: { run_id, node, status: 'ok', error: null } });

function Gates() {
  const [gates, setGates] = useState<FeasibilityGates>({ planReady: false, buildReady: false });
  return <><FeasibilityPanel buildId={id} onReadyChange={setGates} />
    <InterviewStage build={{ ...fixtures.build, stage: 'interview' }} messages={[]} feasibilityReady={gates.planReady} />
    <BuildStage build={fixtures.build} run={idleRun} feasibilityReady={gates.buildReady} />
  </>;
}
const disabled = (name: string) => screen.getByRole('button', { name }).matches(':disabled');
const assessmentPanel = () => screen.getByRole('region', { name: 'Feasibility' });
async function panel(value: Assessment = fixtures.feasibilityAlternatives) {
  setMockAssessment(id, value);
  render(<FeasibilityPanel buildId={id} />);
  await screen.findByText(value.state === 'ready' ? 'Your requirements are resolved.' : value.issues[0]?.requirement ?? /Check what this app/);
}

describe('Feasibility recovery and gates', () => {
  it('checks unchecked once, follows only its run, refetches on finish, and enables all three actions', async () => {
    setMockAssessment(id, unchecked);
    const get = vi.spyOn(api, 'getFeasibility');
    const post = vi.spyOn(api, 'checkFeasibility').mockResolvedValue({ run_id: 'mine' });
    render(<Gates />);
    const check = await screen.findByRole('button', { name: 'Check feasibility' });
    expect(disabled('Generate plan')).toBe(true);
    expect(disabled('Generate recipe')).toBe(true);
    expect(disabled('Build in Data Studio')).toBe(true);
    act(() => { fireEvent.click(check); fireEvent.click(check); });
    expect(post).toHaveBeenCalledExactlyOnceWith(id);
    await screen.findByText('Checking feasibility…');
    fire(finished('other'));
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(1));
    await screen.findByRole('button', { name: 'Check feasibility' });
    expect(disabled('Check feasibility')).toBe(true);
    setMockAssessment(id, ready);
    fire(finished('mine', 'different_node'));
    await screen.findByText('Your requirements are resolved.');
    await waitFor(() => expect(disabled('Generate plan')).toBe(false));
    expect(disabled('Generate recipe')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
    await screen.findByRole('list', { name: 'Recipe' });
    expect(disabled('Build in Data Studio')).toBe(false);
  });

  it('handles a finish arriving before the check POST returns', async () => {
    setMockAssessment(id, unchecked);
    let resolve!: (value: { run_id: string }) => void;
    vi.spyOn(api, 'checkFeasibility').mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<FeasibilityPanel buildId={id} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Check feasibility' }));
    setMockAssessment(id, ready);
    fire(finished('fast'));
    await act(async () => resolve({ run_id: 'fast' }));
    await screen.findByText('Feasibility checked. Review the result.');
    expect(screen.getByRole('heading', { name: 'Feasibility' })).toBe(document.activeElement);
  });

  it('recovers a missed completion when reconnect arrives before the check POST response', async () => {
    setMockAssessment(id, unchecked);
    let resolve!: (value: { run_id: string }) => void;
    vi.spyOn(api, 'checkFeasibility').mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<Gates />);
    fireEvent.click(await screen.findByRole('button', { name: 'Check feasibility' }));
    setMockAssessment(id, ready);
    fire({ name: 'ready', data: { build_id: id } });
    await screen.findByText('Your requirements are resolved.');
    expect(disabled('Generate plan')).toBe(false);
    await act(async () => resolve({ run_id: 'missed' }));
    expect(disabled('Generate plan')).toBe(false);
    expect(disabled('Generate recipe')).toBe(false);
    expect(screen.queryByText('Checking feasibility…')).toBeNull();
  });

  it.each(['mount', 'reconnect', 'docs.updated', 'run.finished'])('refetches on %s', async (trigger) => {
    const get = vi.spyOn(api, 'getFeasibility');
    await panel(ready);
    expect(get).toHaveBeenCalledTimes(1);
    if (trigger === 'reconnect') fire({ name: 'ready', data: { build_id: id } });
    if (trigger === 'docs.updated') fire({ name: 'docs.updated', data: { docs: [] } });
    if (trigger === 'run.finished') fire(finished('elsewhere'));
    if (trigger !== 'mount') await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it('fails closed on GET error and Retry recovers the gates', async () => {
    vi.spyOn(api, 'getFeasibility').mockRejectedValueOnce(new ApiError(500, 'failed', 'Try loading again.'));
    render(<Gates />);
    await screen.findByText("Couldn't load feasibility");
    expect(disabled('Generate plan')).toBe(true);
    expect(disabled('Generate recipe')).toBe(true);
    expect(disabled('Build in Data Studio')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Retry feasibility' }));
    await screen.findByText('Your requirements are resolved.');
    expect(disabled('Generate plan')).toBe(false);
    expect(disabled('Generate recipe')).toBe(false);
  });

  it.each([fixtures.feasibilityStale, { ...ready, prototype_stale: true }])('blocks recipe and Build for stale assessments/prototypes', async (value) => {
    setMockAssessment(id, value);
    render(<Gates />);
    await screen.findByText(/This prototype is out of date/);
    expect(disabled('Generate recipe')).toBe(true);
    expect(disabled('Build in Data Studio')).toBe(true);
    expect(disabled('Generate plan')).toBe(value.state !== 'ready');
  });

  it('gates the actual shell Continue action on assessment and reference errors', async () => {
    setMockAssessment(id, fixtures.feasibilityAlternatives);
    render(<MemoryRouter initialEntries={[`/builds/${id}`]}><Routes><Route path="/builds/:id" element={<WorkspaceShell />} /></Routes></MemoryRouter>);
    await screen.findByText('Animate GPS points along a route.');
    expect(disabled('Continue to build')).toBe(true);
    setMockAssessment(id, ready);
    fire(finished('resolved'));
    await waitFor(() => expect(disabled('Continue to build')).toBe(false));
    vi.spyOn(api, 'getReferences').mockRejectedValue(new ApiError(500, 'failed', 'References unavailable.'));
    fire(finished('failed-refs'));
    await screen.findByText("Couldn't load references");
    expect(disabled('Continue to build')).toBe(true);
  });
});

describe('Explicit requirements and decisions', () => {
  it('shows requirement, app reason, safe evidence and alternatives with no selection', async () => {
    const value = structuredClone(fixtures.feasibilityAlternatives);
    value.issues[0]!.evidence.push('https://example.com/support', 'javascript:alert(1)');
    await panel(value);
    expect(screen.getByText('This app cannot animate GPS points.')).toBeTruthy();
    expect(screen.getByText(value.issues[0]!.reason)).toBeTruthy();
    expect(screen.getAllByRole('radio').every((el) => !(el as HTMLInputElement).checked)).toBe(true);
    const link = screen.getByRole('link', { name: /https:\/\/example.com\/support.*opens in a new tab/ });
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(screen.getByText('javascript:alert(1)').tagName).toBe('CODE');
    expect(screen.getByText('contracts/recipe.md#Operations').tagName).toBe('CODE');
    expect(screen.getAllByRole('button', { name: 'Use this alternative' }).every((el) => (el as HTMLButtonElement).disabled)).toBe(true);
  });

  it.each([
    ['unsupported_product', 'Data Studio does not support this requirement.'],
    ['unsupported_app', 'This app cannot produce this requirement.'],
    ['needs_data', 'More data is needed for this requirement.'],
    ['needs_clarification', 'Your clarification is needed for this requirement.'],
    ['unknown', 'Support for this requirement is uncertain. Check feasibility or clarify it in chat.'],
  ] as const)('uses distinct %s copy', async (status, copy) => {
    const issue: Issue = { ...fixtures.feasibility.issues[0]!, status, requirement: 'Requested behavior' };
    await panel({ ...fixtures.feasibility, issues: [issue] });
    expect(screen.getByText(copy)).toBeTruthy();
  });

  it.each(['accept_alternative', 'drop'] as const)('sends only the explicit %s decision and focuses refreshed heading', async (action) => {
    const decide = vi.spyOn(api, 'decideFeasibility');
    const plan = vi.spyOn(api, 'generatePlan');
    const recipe = vi.spyOn(api, 'compileRecipe');
    const run = vi.spyOn(api, 'runBuild');
    await panel();
    const issue = within(assessmentPanel()).getAllByRole('group')[0]!;
    if (action === 'accept_alternative') fireEvent.click(within(issue).getByRole('radio', { name: 'Geo map of revenue by region' }));
    fireEvent.click(within(issue).getByRole('button', { name: action === 'drop' ? 'Drop this requirement' : 'Use this alternative' }));
    await screen.findByText('Decision saved. Review the current assessment before continuing.');
    expect(decide).toHaveBeenCalledExactlyOnceWith(id, fixtures.feasibilityAlternatives.id, [{ issue_id: 'issue_gps', action, alternative_id: action === 'drop' ? null : 'alt_region_map' }]);
    expect(plan).not.toHaveBeenCalled(); expect(recipe).not.toHaveBeenCalled(); expect(run).not.toHaveBeenCalled();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Feasibility' })));
  });

  it('refetches a stale decision, clears selection, and asks for another review', async () => {
    const get = vi.spyOn(api, 'getFeasibility');
    vi.spyOn(api, 'decideFeasibility').mockRejectedValue(new ApiError(409, 'feasibility_stale', 'Stale'));
    await panel();
    fireEvent.click(screen.getByRole('radio', { name: 'Geo map of revenue by region' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'Use this alternative' })[0]!);
    await screen.findByText('The requirements changed. Review the refreshed assessment and choose again.');
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect((screen.getByRole('radio', { name: 'Geo map of revenue by region' }) as HTMLInputElement).checked).toBe(false);
  });

  it('never overwrites a newer assessment with a late decision or GET', async () => {
    let resolveDecision!: (value: Assessment) => void;
    let resolveOldGet!: (value: Assessment) => void;
    const get = vi.spyOn(api, 'getFeasibility').mockResolvedValue(fixtures.feasibilityAlternatives);
    vi.spyOn(api, 'decideFeasibility').mockReturnValue(new Promise((r) => { resolveDecision = r; }));
    await panel();
    fireEvent.click(screen.getAllByRole('button', { name: 'Drop this requirement' })[0]!);
    get.mockImplementationOnce(() => new Promise((r) => { resolveOldGet = r; })).mockResolvedValue(ready);
    fire({ name: 'docs.updated', data: { docs: [] } });
    fire(finished('newer'));
    await screen.findByText('Your requirements are resolved.');
    await act(async () => { resolveOldGet(fixtures.feasibility); resolveDecision(fixtures.feasibility); });
    await screen.findByText('Decision saved. Review the current assessment before continuing.');
    await waitFor(() => expect(screen.getByText('Your requirements are resolved.')).toBeTruthy());
    expect(screen.queryByText('Animate GPS points along a route.')).toBeNull();
  });

  it('focuses the actual chat input for needs_clarification', async () => {
    setMockAssessment(id, fixtures.feasibilityAlternatives);
    render(<MemoryRouter initialEntries={[`/builds/${id}`]}><Routes><Route path="/builds/:id" element={<WorkspaceShell />} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Clarify in chat' }));
    expect(document.activeElement).toBe(screen.getByLabelText('Message'));
  });

  it('does not steal chat focus on later background refetches after a decision', async () => {
    setMockAssessment(id, fixtures.feasibilityAlternatives);
    render(<MemoryRouter initialEntries={[`/builds/${id}`]}><Routes><Route path="/builds/:id" element={<WorkspaceShell />} /></Routes></MemoryRouter>);
    const drop = await screen.findAllByRole('button', { name: 'Drop this requirement' });
    await waitFor(() => expect(drop[0]!.matches(':disabled')).toBe(false));
    fireEvent.click(drop[0]!);
    await screen.findByText('Decision saved. Review the current assessment before continuing.');
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Feasibility' })));
    const input = screen.getByLabelText('Message');
    input.focus();
    fire({ name: 'docs.updated', data: { docs: [] } });
    await screen.findByText('Show Revenue.');
    expect(document.activeElement).toBe(input);
  });

  it('has a capability_check phrase for the activity strip', () => {
    expect(presetFor('capability_check').phrases).toContain('Checking what this app supports');
  });
});
