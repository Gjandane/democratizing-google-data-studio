import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, httpApi } from '../src/api/client';
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
  await waitFor(() => expect(screen.queryByText('Loading feasibility…')).toBeNull());
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
    expect(disabled('Generate plan')).toBe(false);
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

describe('Background refetch keeps the last assessment (task 12.1)', () => {
  const docs: BuildEvent = { name: 'docs.updated', data: { docs: [] } };
  const pendingGet = () => {
    let resolve!: (value: Assessment) => void;
    const get = vi.spyOn(api, 'getFeasibility').mockImplementation(() => new Promise((r) => { resolve = r; }));
    return { get, resolve: (value: Assessment) => act(async () => resolve(value)) };
  };
  async function gatesWithRecipe() {
    setMockAssessment(id, ready);
    render(<Gates />);
    await waitFor(() => expect(disabled('Generate plan')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
    await waitFor(() => expect(disabled('Build in Data Studio')).toBe(false));
  }

  it('keeps a blocked issue list, its selection and focus on Use this alternative while the GET is pending', async () => {
    await panel();
    expect(screen.getByText('Resolve these requirements before generating or building.')).toBeTruthy();
    const issue = within(assessmentPanel()).getAllByRole('group')[0]!;
    const radio = within(issue).getByRole('radio', { name: 'Geo map of revenue by region' }) as HTMLInputElement;
    fireEvent.click(radio);
    const use = within(issue).getByRole('button', { name: 'Use this alternative' });
    use.focus();
    const { get } = pendingGet();
    fire(finished('elsewhere', 'interview'));
    fire(docs);
    expect(get).toHaveBeenCalledTimes(2);
    expect(within(assessmentPanel()).getAllByRole('group')[0]).toBe(issue);
    expect(document.activeElement).toBe(use);
    expect(use.matches(':disabled')).toBe(false);
    expect(radio.checked).toBe(true);
    expect(screen.queryByText('Loading feasibility…')).toBeNull();
  });

  it('keeps Generate plan, recipe and Build enabled for a loaded ready assessment until the refetch lands, then follows it', async () => {
    await gatesWithRecipe();
    const { get, resolve } = pendingGet();
    fire(docs);
    fire(finished('elsewhere', 'interview'));
    expect(get).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Your requirements are resolved.')).toBeTruthy();
    expect(disabled('Generate plan')).toBe(false);
    expect(disabled('Regenerate')).toBe(false);
    expect(disabled('Build in Data Studio')).toBe(false);
    expect(screen.queryByText('Loading feasibility…')).toBeNull();
    await resolve(fixtures.feasibilityAlternatives);
    await screen.findByText('Animate GPS points along a route.');
    expect(disabled('Generate plan')).toBe(true);
    expect(disabled('Regenerate')).toBe(true);
    expect(disabled('Build in Data Studio')).toBe(true);
  });

  it('keeps the gates closed after a run until its refetch lands, never reopening on the pre-run assessment', async () => {
    setMockAssessment(id, ready);
    render(<Gates />);
    await waitFor(() => expect(disabled('Generate plan')).toBe(false));
    fire({ name: 'run.started', data: { run_id: 'chat', node: 'interview' } });
    expect(disabled('Generate plan')).toBe(true);
    const { resolve } = pendingGet();
    fire(finished('chat', 'interview'));
    expect(disabled('Generate plan')).toBe(true);
    await resolve(ready);
    expect(disabled('Generate plan')).toBe(false);
  });

  it('fails closed when a background refetch fails, and stays closed while Retry is pending', async () => {
    await gatesWithRecipe();
    vi.spyOn(api, 'getFeasibility').mockRejectedValueOnce(new ApiError(500, 'failed', 'Try loading again.'));
    fire(docs);
    await screen.findByText("Couldn't load feasibility");
    expect(disabled('Generate plan')).toBe(true);
    expect(disabled('Regenerate')).toBe(true);
    expect(disabled('Build in Data Studio')).toBe(true);
    const { resolve } = pendingGet();
    fireEvent.click(screen.getByRole('button', { name: 'Retry feasibility' }));
    expect(screen.getByText("Couldn't load feasibility")).toBeTruthy();
    expect(disabled('Generate plan')).toBe(true);
    expect(disabled('Build in Data Studio')).toBe(true);
    await resolve(ready);
    expect(screen.queryByText("Couldn't load feasibility")).toBeNull();
    expect(disabled('Generate plan')).toBe(false);
    expect(disabled('Build in Data Studio')).toBe(false);
  });

  it('drops a late response for an older refetch, in the panel and the gates', async () => {
    setMockAssessment(id, ready);
    render(<Gates />);
    await waitFor(() => expect(disabled('Generate plan')).toBe(false));
    let resolveOld!: (value: Assessment) => void;
    vi.spyOn(api, 'getFeasibility').mockImplementationOnce(() => new Promise((r) => { resolveOld = r; })).mockResolvedValueOnce(fixtures.feasibilityAlternatives);
    fire(docs);
    fire(finished('newer'));
    await screen.findByText('Animate GPS points along a route.');
    await act(async () => resolveOld(ready));
    expect(screen.getByText('Animate GPS points along a route.')).toBeTruthy();
    expect(screen.queryByText('Your requirements are resolved.')).toBeNull();
    expect(disabled('Generate plan')).toBe(true);
  });

  it('drops a GET sent before a discard once the discard response lands', async () => {
    const saved = fixtures.feasibilityPending;
    await panel(saved);
    const { resolve } = pendingGet();
    fire(docs);
    vi.spyOn(api, 'discardComments').mockResolvedValue({ ...saved, id: 'after_discard', pending_comments: null });
    fireEvent.click(screen.getByRole('button', { name: 'Discard pending comments' }));
    await screen.findByText('Pending comments discarded. Review the current assessment.');
    expect(screen.queryByRole('list', { name: 'Saved comments' })).toBeNull();
    await resolve(saved);
    expect(screen.queryByRole('list', { name: 'Saved comments' })).toBeNull();
  });

  it.each([
    ['no issues', ready],
    ['only resolved issues', { ...fixtures.feasibilityAlternatives, state: 'ready', issues: fixtures.feasibilityAlternatives.issues.map((issue) => ({ ...issue, resolution: 'dropped' })) } as Assessment],
  ])('renders a ready assessment with %s as one line of text', async (_, value) => {
    await panel(value);
    const region = assessmentPanel();
    expect(region.textContent).toBe('FeasibilityYour requirements are resolved.');
    expect(within(region).queryAllByRole('button')).toHaveLength(0);
    expect(within(region).queryAllByRole('group')).toHaveLength(0);
    expect(within(region).getByText('Your requirements are resolved.').parentElement).toBe(region);
    expect(region.className).toContain('flex');
  });
});


describe('Saved comment batches and stale repair', () => {
  const saved = fixtures.feasibilityPending;
  const resolved: Assessment = { ...saved, state: 'stale', prototype_stale: true, issues: saved.issues.map((issue) => ({ ...issue, resolution: 'dropped' })) };

  it('restores every saved target/text after remount without implicit actions', async () => {
    const reapply = vi.spyOn(api, 'reapplyComments');
    const discard = vi.spyOn(api, 'discardComments');
    setMockAssessment(id, saved);
    const view = render(<FeasibilityPanel buildId={id} />);
    await screen.findByRole('list', { name: 'Saved comments' });
    view.unmount();
    render(<FeasibilityPanel buildId={id} />);
    const list = await screen.findByRole('list', { name: 'Saved comments' });
    for (const comment of saved.pending_comments!.comments) {
      expect(within(list).getByText(comment.component_id)).toBeTruthy();
      expect(within(list).getByText(comment.text)).toBeTruthy();
    }
    expect(disabled('Reapply saved comments')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Reapply saved comments' }));
    expect(reapply).not.toHaveBeenCalled(); expect(discard).not.toHaveBeenCalled();
  });

  it('reapplies once with current IDs, waits for its exact run and refetches before unlocking Build', async () => {
    setMockAssessment(id, resolved);
    const get = vi.spyOn(api, 'getFeasibility');
    const post = vi.spyOn(api, 'reapplyComments').mockResolvedValue({ run_id: 'reapply' });
    const recipe = vi.spyOn(api, 'compileRecipe'); const run = vi.spyOn(api, 'runBuild');
    render(<Gates />);
    const button = await screen.findByRole('button', { name: 'Reapply saved comments' });
    expect(disabled('Generate recipe')).toBe(true);
    expect(disabled('Generate plan')).toBe(true);
    button.focus();
    act(() => { fireEvent.click(button); fireEvent.click(button); });
    expect(post).toHaveBeenCalledExactlyOnceWith(id, resolved.id, resolved.pending_comments!.id);
    await screen.findByText('Reapplying saved comments…');
    fire(finished('unrelated', 'revise'));
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(1));
    expect(disabled('Reapply saved comments')).toBe(true);
    setMockAssessment(id, ready);
    fire(finished('reapply', 'arbitrary_node'));
    await screen.findByText('Your requirements are resolved.');
    await waitFor(() => expect(disabled('Generate recipe')).toBe(false));
    expect(screen.queryByRole('list', { name: 'Saved comments' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Feasibility' }));
    expect(recipe).not.toHaveBeenCalled(); expect(run).not.toHaveBeenCalled();
  });

  it('handles a fast reapply finish and reconnect before its POST returns', async () => {
    setMockAssessment(id, resolved);
    let resolve!: (value: { run_id: string }) => void;
    vi.spyOn(api, 'reapplyComments').mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<FeasibilityPanel buildId={id} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Reapply saved comments' }));
    fire(finished('fast', 'revise'));
    await act(async () => resolve({ run_id: 'fast' }));
    await screen.findByText('Prototype update finished. Review the current assessment.');
    expect(disabled('Reapply saved comments')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Reapply saved comments' }));
    setMockAssessment(id, ready);
    fire({ name: 'ready', data: { build_id: id } });
    await screen.findByText('Your requirements are resolved.');
    await act(async () => resolve({ run_id: 'missed' }));
    expect(screen.queryByText('Reapplying saved comments…')).toBeNull();
  });

  it('discards once and renders the server response without hiding independent issues or launching work', async () => {
    const independent = fixtures.feasibilityAlternatives.issues[0]!;
    const returned: Assessment = { ...saved, id: 'after_discard', issues: [independent], pending_comments: null };
    setMockAssessment(id, saved);
    const discard = vi.spyOn(api, 'discardComments').mockResolvedValue(returned);
    const plan = vi.spyOn(api, 'generatePlan'); const recipe = vi.spyOn(api, 'compileRecipe'); const run = vi.spyOn(api, 'runBuild');
    render(<FeasibilityPanel buildId={id} />);
    const button = await screen.findByRole('button', { name: 'Discard pending comments' });
    button.focus();
    act(() => { fireEvent.click(button); fireEvent.click(button); });
    await screen.findByText(independent.requirement);
    expect(discard).toHaveBeenCalledExactlyOnceWith(id, saved.id);
    expect(screen.queryByRole('list', { name: 'Saved comments' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Feasibility' }));
    expect(plan).not.toHaveBeenCalled(); expect(recipe).not.toHaveBeenCalled(); expect(run).not.toHaveBeenCalled();
  });

  it.each(['discardComments', 'reapplyComments'] as const)('a stale %s refetch keeps the batch until the server removes it', async (method) => {
    setMockAssessment(id, resolved);
    const get = vi.spyOn(api, 'getFeasibility');
    vi.spyOn(api, method).mockRejectedValue(new ApiError(409, 'feasibility_stale', 'Requirements changed. Refresh.'));
    render(<FeasibilityPanel buildId={id} />);
    fireEvent.click(await screen.findByRole('button', { name: method === 'discardComments' ? 'Discard pending comments' : 'Reapply saved comments' }));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    await screen.findByRole('list', { name: 'Saved comments' });
    expect(disabled('Reapply saved comments')).toBe(false);
    get.mockResolvedValue(ready);
    fire({ name: 'docs.updated', data: { docs: [] } });
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Saved comments' })).toBeNull());
  });

  it('keeps saved comments visible and repair actions disabled when a refetch fails', async () => {
    await panel(resolved);
    vi.spyOn(api, 'getFeasibility').mockRejectedValue(new ApiError(500, 'failed', 'Retry loading.'));
    fire(finished('failed-refresh'));
    await screen.findByText("Couldn't load feasibility");
    expect(screen.getByRole('list', { name: 'Saved comments' })).toBeTruthy();
    expect(disabled('Reapply saved comments')).toBe(true);
    expect(disabled('Discard pending comments')).toBe(true);
  });

  it('enables explicit Replan for resolved stale intent; Build and recipe wait for a current prototype', async () => {
    setMockAssessment(id, fixtures.feasibilityStale);
    const plan = vi.spyOn(api, 'generatePlan').mockResolvedValue({ run_id: 'plan' });
    const recipe = vi.spyOn(api, 'compileRecipe'); const run = vi.spyOn(api, 'runBuild');
    render(<><FeasibilityPanel buildId={id} canReplan /><Gates /></>);
    const button = await screen.findByRole('button', { name: 'Replan' });
    expect(button.matches(':disabled')).toBe(false);
    expect(disabled('Generate recipe')).toBe(true); expect(disabled('Build in Data Studio')).toBe(true);
    act(() => { fireEvent.click(button); fireEvent.click(button); });
    expect(plan).toHaveBeenCalledExactlyOnceWith(id);
    setMockAssessment(id, { ...ready, prototype_stale: true });
    fire(finished('plan', 'plan'));
    await screen.findAllByText('Your requirements are resolved.');
    expect(disabled('Generate recipe')).toBe(true);
    setMockAssessment(id, ready);
    fire(finished('current', 'spec'));
    await waitFor(() => expect(disabled('Generate recipe')).toBe(false));
    expect(recipe).not.toHaveBeenCalled(); expect(run).not.toHaveBeenCalled();
  });

  it('uses exact reapply JSON and encoded DELETE query, validating the returned assessment', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'r' })))
      .mockResolvedValueOnce(new Response(JSON.stringify(ready)))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...ready, extra: true })));
    await httpApi.reapplyComments('b/id', 'a?&', 'batch');
    expect(fetch).toHaveBeenNthCalledWith(1, '/api/builds/b%2Fid/feasibility/reapply', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ assessment_id: 'a?&', batch_id: 'batch' }) });
    expect(await httpApi.discardComments('b/id', 'a?&')).toEqual(ready);
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/builds/b%2Fid/feasibility/pending-comments?assessment_id=a%3F%26', { method: 'DELETE' });
    await expect(httpApi.discardComments(id, 'a')).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('a failed reapply keeps the saved batch and offers explicit retry without building', async () => {
    setMockAssessment(id, resolved);
    const post = vi.spyOn(api, 'reapplyComments').mockResolvedValue({ run_id: 'failed-reapply' });
    const recipe = vi.spyOn(api, 'compileRecipe'); const run = vi.spyOn(api, 'runBuild');
    render(<FeasibilityPanel buildId={id} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Reapply saved comments' }));
    await screen.findByText('Reapplying saved comments…');
    fire({ name: 'run.finished', data: { run_id: 'failed-reapply', node: 'revise', status: 'error', error: 'Update timed out. Try again.' } });
    await screen.findByText('Update timed out. Try again.');
    await waitFor(() => expect(disabled('Reapply saved comments')).toBe(false));
    expect(screen.getByRole('list', { name: 'Saved comments' })).toBeTruthy();
    expect(post).toHaveBeenCalledTimes(1); expect(recipe).not.toHaveBeenCalled(); expect(run).not.toHaveBeenCalled();
  });

  it('a new mock comment batch replaces the old batch and invalidates its decisions', async () => {
    setMockAssessment(id, resolved);
    const comments = [{ component_id: 'p1_title', text: 'A different request' }];
    await expect(api.postComments(id, comments)).rejects.toMatchObject({ code: 'feasibility_blocked' });
    const current = await api.getFeasibility(id);
    expect(current.pending_comments!.id).not.toBe(resolved.pending_comments!.id);
    expect(current.pending_comments!.comments).toEqual(comments);
    expect(current.issues[0]!.resolution).toBe('unresolved');
    await expect(api.reapplyComments(id, current.id!, resolved.pending_comments!.id)).rejects.toMatchObject({ code: 'feasibility_stale' });
  });

  it('mock rejects expired IDs and unresolved reapply; discard preserves independent requirements/spec', async () => {
    const unrelated = fixtures.feasibilityAlternatives.issues[0]!;
    setMockAssessment(id, { ...saved, issues: [...saved.issues, unrelated], prototype_stale: true }, saved.issues.map((issue) => issue.id));
    await expect(api.reapplyComments(id, saved.id!, saved.pending_comments!.id)).rejects.toMatchObject({ code: 'feasibility_blocked' });
    await expect(api.reapplyComments(id, 'expired', saved.pending_comments!.id)).rejects.toMatchObject({ code: 'feasibility_stale' });
    await expect(api.discardComments(id, 'expired')).rejects.toMatchObject({ code: 'feasibility_stale' });
    const before = await api.getBuild(id);
    const value = await api.discardComments(id, saved.id!);
    expect(value.pending_comments).toBeNull(); expect(value.issues).toEqual([unrelated]);
    expect(value.prototype_stale).toBe(true); expect(value.state).toBe('blocked');
    expect((await api.getBuild(id)).spec_version).toBe(before.spec_version);
  });
});
