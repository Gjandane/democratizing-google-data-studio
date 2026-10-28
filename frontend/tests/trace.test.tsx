// Task 16.5: stage calls in Trace and stage-limit errors (docs/stage-settings-ui.md, Stage calls and stage-limit errors).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { api } from '../src/api/client';
import { ApiError, type RunCalls, type Trace } from '../src/api/types';
import { STAGE_META, STAGE_ORDER } from '../src/features/settings/stageSettings';
import { parseStageError } from '../src/features/trace/stageErrors';
import { TraceModal } from '../src/features/trace/TraceModal';
import { publishWorkspace } from '../src/features/workspace/stretch';
import { patchMockBuild, resetMockState, setMockRunFailure } from '../src/mocks/api';
import { emit } from '../src/mocks/events';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const id = fixtures.build.id;
const runId = fixtures.runCalls.run_id;
const MESSAGE = 'reference_html page 1 attempt 1 stopped at the 65536-token output limit (answer 1210 tokens, thinking unknown). Raise Output tokens, then try again.';
const CUTOFF = `stage_output_cutoff: ${MESSAGE}`;
const HTML_INVALID = 'html_invalid: reference_html page 2 still failed its HTML checks after 2 repairs.';

/** The 3.0 run of run_calls.json, as Trace lists it. */
const run3: Trace = {
  run_id: runId,
  build_id: id,
  node: 'prototype',
  model: 'gemini-3.8-flash',
  input_tokens: 61530,
  output_tokens: 6330,
  latency_ms: 466800,
  tool_calls: 0,
  status: 'error',
  error: CUTOFF,
  started_at: '2026-10-26T10:00:00Z',
};

// The first render of a file is slow under full-suite load: allow it more than the default 1 s.
const SLOW = { timeout: 5000 };
const toggle = (node: string) => screen.getByRole('button', { name: `${node}, model calls` });
const runsTable = () => screen.findByRole('table', { name: 'Model runs' }, SLOW);
const callsOf = (node: string) => screen.findByRole('region', { name: `Model calls of the ${node} run` }, SLOW);
const rowOf = (node: string) => toggle(node).closest('tr')!;
/** The Est. cost cell of a run row (Node, Model, Input, Output, Latency, Est. cost, ...). */
const costOf = (node: string) => within(rowOf(node)).getAllByRole('cell')[5]!.textContent;
const callRows = (region: HTMLElement) => within(within(region).getByRole('table', { name: 'Stage calls' })).getAllByRole('row').slice(1);
const cell = (row: HTMLElement, col: string) => row.querySelector(`[data-col="${col}"]`)!.textContent;
/** The modal header's description (the cost lines when a build is open). */
const header = () => {
  const dialog = screen.getByRole('dialog', { name: 'Trace' });
  return document.getElementById(dialog.getAttribute('aria-describedby')!)!.textContent;
};

function openTrace(props: { runId?: string; traces?: Trace[] } = {}) {
  vi.spyOn(api, 'listTraces').mockResolvedValue(props.traces ?? [run3, ...fixtures.traces]);
  return render(<TraceModal open onClose={() => {}} buildId={id} runId={props.runId} />);
}

describe('Trace stage calls', () => {
  it('expanding a run fetches its calls once and shows the settings used and every call', async () => {
    const calls = vi.spyOn(api, 'getRunCalls');
    openTrace();
    await runsTable();
    expect(calls).not.toHaveBeenCalled();
    fireEvent.click(toggle('prototype'));
    expect(toggle('prototype').getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('Loading the model calls…')).toBeTruthy();
    const region = await callsOf('prototype');
    await within(region).findByRole('table', { name: 'Stage calls' });
    expect(calls).toHaveBeenCalledExactlyOnceWith(runId);

    // Settings used: one line per stage, in pipeline order, then the fallback and brief review.
    const used = within(region).getByRole('region', { name: 'Settings used' });
    const terms = Array.from(used.querySelectorAll('dt')).map((dt) => dt.textContent);
    expect(terms).toEqual([...STAGE_ORDER.map((stage) => STAGE_META[stage].name), 'Fallback model', 'Brief review']);
    const lines = Array.from(used.querySelectorAll('dd')).map((dd) => dd.textContent);
    expect(lines[STAGE_ORDER.indexOf('reference_html')]).toBe('gemini-3.8-flash High thinking, input 131,072, output 65,536, 1,200 s, 2 retries, 2 repairs');
    expect(lines[STAGE_ORDER.indexOf('reference_interpretation')]).toBe('gemini-3.8-flash High thinking, input 131,072, output 32,768, 600 s, 1 retry, 1 repair');
    expect(lines[STAGE_ORDER.indexOf('interview')]).toBe('gemini-3.8-flash Low thinking, 30 s');
    expect(lines.slice(-2)).toEqual(['gemini-3.8-flash', 'Off']);

    // Stage calls, in order.
    const rows = callRows(region);
    expect(rows).toHaveLength(fixtures.runCalls.calls.length);
    const [first, , third, fallback, cutoff] = rows as [HTMLElement, HTMLElement, HTMLElement, HTMLElement, HTMLElement];
    expect(cell(first, 'stage')).toBe('HTML brief');
    expect(cell(first, 'page')).toBe('1');
    expect(cell(third, 'attempt')).toBe('1 · try 3');
    expect(cell(first, 'thinking')).toBe('High');
    expect(cell(first, 'input')).toBe('18,432 / 22,631 / 131,072');
    // A null count is "unknown", never 0.
    expect(cell(first, 'output')).toBe('unknown · unknown · 32,768');
    expect(cell(first, 'outcome')).toBe('Provider error');
    expect(cell(first, 'time')).toBe('1.2 s');
    expect(cell(first, 'cost')).toBe('$0.00');
    // The fallback: requested -> actual with the chip, on that row only.
    expect(cell(fallback, 'model')).toBe('gemini-4-argon → then gemini-3.8-flash Fallback');
    expect(within(fallback).getByText('Fallback')).toBeTruthy();
    expect(rows.filter((row) => within(row).queryByText('Fallback'))).toEqual([fallback]);
    expect(cell(first, 'model')).toBe('gemini-4-argon');
    expect(cell(fallback, 'output')).toBe('5,120 · 9,870 · 32,768');
    expect(cell(fallback, 'cost')).toBe('$0.0546');
    // The output cutoff: answer known, thinking unknown, the limit; no price.
    expect(cell(cutoff, 'stage')).toBe('HTML with a reference');
    expect(cell(cutoff, 'input')).toBe('40,210 / 48,764 / 131,072');
    expect(cell(cutoff, 'output')).toBe('1,210 · unknown · 65,536');
    expect(cell(cutoff, 'outcome')).toBe('Output cut off');
    expect(cell(cutoff, 'time')).toBe('6 min 42 s');
    expect(cell(cutoff, 'cost')).toBe('unknown');
    expect(region.textContent).not.toMatch(/\b0 · |· 0 ·/);
    expect(within(region).getByText(/^Estimated cost of this run:/).textContent).toBe('Estimated cost of this run: at least $0.0546');

    // Collapse and expand again: no second request.
    fireEvent.click(toggle('prototype'));
    expect(screen.queryByRole('region', { name: 'Model calls of the prototype run' })).toBeNull();
    fireEvent.click(toggle('prototype'));
    expect(within(await callsOf('prototype')).getByRole('table', { name: 'Stage calls' })).toBeTruthy();
    expect(calls).toHaveBeenCalledTimes(1);
  });

  it('a run before 3.0 shows "Not recorded" and the empty calls state', async () => {
    openTrace();
    await runsTable();
    fireEvent.click(toggle('plan'));
    const region = await callsOf('plan');
    await within(region).findByText('No model calls in this run');
    expect(within(within(region).getByRole('region', { name: 'Settings used' })).getByText('Not recorded')).toBeTruthy();
    expect(within(region).queryByRole('table')).toBeNull();
    expect(within(region).queryByText(/^Estimated cost of this run/)).toBeNull();
  });

  it('a failed calls request shows the error with Try again, which loads them', async () => {
    const calls = vi.spyOn(api, 'getRunCalls').mockRejectedValueOnce(new ApiError(502, 'invalid_response', "Couldn't read the model calls. Try again."));
    openTrace();
    await runsTable();
    fireEvent.click(toggle('prototype'));
    const region = await callsOf('prototype');
    const alert = await within(region).findByRole('alert');
    expect(alert.textContent).toContain("Couldn't load the model calls");
    expect(alert.textContent).toContain("Couldn't read the model calls. Try again.");
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await within(region).findByRole('table', { name: 'Stage calls' });
    expect(calls).toHaveBeenCalledTimes(2);
  });

  it('long model ids truncate with the full id in the title', async () => {
    const long = 'gemini-4-argon-preview-2026-10-long-context-experimental-build';
    const withLong: RunCalls = { ...fixtures.runCalls, calls: fixtures.runCalls.calls.map((c) => ({ ...c, model: long, requested_model: long })) };
    vi.spyOn(api, 'getRunCalls').mockResolvedValue(withLong);
    openTrace();
    await runsTable();
    fireEvent.click(toggle('prototype'));
    const region = await callsOf('prototype');
    const ids = await within(region).findAllByTitle(long);
    expect(ids.length).toBeGreaterThan(0);
    for (const el of ids) {
      expect(el.classList.contains('truncate')).toBe(true);
      expect(el.textContent).toBe(long);
    }
  });

  it('opened at a run, that run is expanded and focused', async () => {
    const calls = vi.spyOn(api, 'getRunCalls');
    openTrace({ runId });
    await runsTable();
    await waitFor(() => expect(document.activeElement).toBe(toggle('prototype')));
    expect(toggle('prototype').getAttribute('aria-expanded')).toBe('true');
    expect(toggle('plan').getAttribute('aria-expanded')).toBe('false');
    await within(await callsOf('prototype')).findByRole('table', { name: 'Stage calls' });
    expect(calls).toHaveBeenCalledExactlyOnceWith(runId);
  });
});

describe('Trace cost', () => {
  it('the header shows the build estimate, the incomplete note and the date prices were checked', async () => {
    expect(fixtures.buildCost.build_id).toBe(id);
    openTrace();
    await runsTable();
    await waitFor(() => expect(header()).toContain('Estimated cost of this build: at least $0.0546'));
    expect(header()).toContain('Some calls have no price or thinking count.');
    expect(header()).toContain('Prices checked 2026-10-26. Actual billing may differ.');
    // Each run row its estimate by run_id: the 3.0 run, the pre-3.0 run from its Trace totals, and a run the cost doesn't list.
    expect(screen.getByRole('columnheader', { name: 'Est. cost' })).toBeTruthy();
    expect(costOf('prototype')).toBe('at least $0.0546');
    expect(costOf('plan')).toBe('unknown from run totals');
    expect(costOf('interview')).toBe('—');
  });

  it('a complete estimate has no note, and a null one is "unknown"', async () => {
    const cost = vi.spyOn(api, 'getBuildCost').mockResolvedValueOnce({ ...fixtures.buildCost, cost_usd_estimate: 0.26, complete: true, runs: [] });
    const view = openTrace();
    await runsTable();
    await waitFor(() => expect(header()).toContain('Estimated cost of this build: $0.26'));
    expect(header()).not.toContain('Some calls have no price');
    expect(header()).toContain('Prices checked 2026-10-26.');
    view.unmount();
    cost.mockResolvedValueOnce({ ...fixtures.buildCost, cost_usd_estimate: null, complete: true, runs: [], prices_checked_on: null });
    openTrace();
    await runsTable();
    await waitFor(() => expect(header()).toContain('Estimated cost of this build: unknown'));
    expect(header()).not.toContain('Prices checked');
    expect(header()).toContain('Actual billing may differ.');
  });

  it('a failed cost request says so with Try again, and the runs still show', async () => {
    const cost = vi.spyOn(api, 'getBuildCost').mockRejectedValueOnce(new ApiError(503, 'unavailable', 'The backend is busy. Try again.'));
    openTrace();
    await runsTable();
    await waitFor(() => expect(header()).toContain("Couldn't load the estimated cost of this build."));
    expect(costOf('prototype')).toBe('—');
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Trace' })).getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(header()).toContain('at least $0.0546'));
    expect(cost).toHaveBeenCalledTimes(2);
  });

  it('reads the cost and the runs again after each run.finished of the build', async () => {
    const cost = vi.spyOn(api, 'getBuildCost');
    const list = vi.spyOn(api, 'listTraces').mockResolvedValue([run3, ...fixtures.traces]);
    render(<TraceModal open onClose={() => {}} buildId={id} />);
    await runsTable();
    await waitFor(() => expect(header()).toContain('at least $0.0546'));
    expect(cost).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledTimes(1);
    cost.mockResolvedValueOnce({ ...fixtures.buildCost, cost_usd_estimate: 0.0812, runs: [{ ...fixtures.buildCost.runs[0]!, cost_usd_estimate: 0.0812, complete: true }] });
    act(() => publishWorkspace(id, { name: 'run.finished', data: { run_id: 'r_next', node: 'revise', status: 'ok', error: null } }));
    await waitFor(() => expect(header()).toContain('at least $0.0812'));
    expect(costOf('prototype')).toBe('$0.0812');
    expect(cost).toHaveBeenCalledTimes(2);
    expect(list).toHaveBeenCalledTimes(2);
    // Other events, and another build's runs, change nothing; the table stayed on screen throughout.
    act(() => publishWorkspace(id, { name: 'run.started', data: { run_id: 'r_more', node: 'revise' } }));
    act(() => publishWorkspace('b_other', { name: 'run.finished', data: { run_id: 'r_x', node: 'revise', status: 'ok', error: null } }));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(cost).toHaveBeenCalledTimes(2);
    expect(screen.queryByText('Loading runs…')).toBeNull();
  });
});

describe('Trace load failures', () => {
  it('under StrictMode a failed first load shows the runs and cost errors, with Try again', async () => {
    const list = vi.spyOn(api, 'listTraces').mockRejectedValue(new ApiError(503, 'unavailable', 'The backend is busy. Try again.'));
    const cost = vi.spyOn(api, 'getBuildCost').mockRejectedValue(new ApiError(503, 'unavailable', 'The backend is busy. Try again.'));
    render(
      <StrictMode>
        <TraceModal open onClose={() => {}} buildId={id} />
      </StrictMode>,
    );
    const alert = await screen.findByRole('alert', undefined, SLOW);
    expect(alert.textContent).toContain("Couldn't load the runs");
    await waitFor(() => expect(header()).toContain("Couldn't load the estimated cost of this build."));
    expect(screen.queryByText('Loading runs…')).toBeNull();
    list.mockResolvedValue([run3, ...fixtures.traces]);
    cost.mockRestore();
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await runsTable();
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Trace' })).getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(header()).toContain('at least $0.0546'));
  });

  it('a run.finished during the first load, whose refetch fails, still ends on the error state', async () => {
    let fail: (reason: unknown) => void = () => {};
    vi.spyOn(api, 'listTraces')
      .mockImplementationOnce(() => new Promise<Trace[]>(() => {}))
      .mockImplementationOnce(() => new Promise<Trace[]>((_resolve, reject) => (fail = reject)));
    render(<TraceModal open onClose={() => {}} buildId={id} />);
    expect(screen.getByText('Loading runs…')).toBeTruthy();
    act(() => publishWorkspace(id, { name: 'run.finished', data: { run_id: 'r_next', node: 'revise', status: 'ok', error: null } }));
    await act(async () => fail(new ApiError(503, 'unavailable', 'The backend is busy. Try again.')));
    expect((await screen.findByRole('alert')).textContent).toContain("Couldn't load the runs");
  });

  it('a failed refetch after run.finished keeps the runs and the cost on screen', async () => {
    const list = vi.spyOn(api, 'listTraces').mockResolvedValue([run3, ...fixtures.traces]);
    const cost = vi.spyOn(api, 'getBuildCost');
    render(<TraceModal open onClose={() => {}} buildId={id} />);
    await runsTable();
    await waitFor(() => expect(header()).toContain('at least $0.0546'));
    list.mockRejectedValueOnce(new Error('down'));
    cost.mockRejectedValueOnce(new Error('down'));
    act(() => publishWorkspace(id, { name: 'run.finished', data: { run_id: 'r_next', node: 'revise', status: 'ok', error: null } }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(cost).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.getByRole('table', { name: 'Model runs' })).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(header()).toContain('at least $0.0546');
  });
});

describe('parseStageError', () => {
  it('reads the code, the message after it and the stage it starts with', () => {
    expect(parseStageError(CUTOFF)).toEqual({ message: MESSAGE, settings: { stage: 'reference_html', field: 'output_tokens' } });
    expect(parseStageError('stage_input_over_limit: html_brief page 2 needs 140,000 input tokens; the limit is 131,072.')?.settings).toEqual({ stage: 'html_brief', field: 'input_tokens' });
    expect(parseStageError('stage_timeout: native_planning ran past 600 s.')?.settings).toEqual({ stage: 'native_planning', field: 'timeout_s' });
    expect(parseStageError('stage_model_unavailable: interview gemini-9 and gemini-3.8-flash are unavailable.')?.settings).toEqual({ stage: 'interview', field: 'model' });
    // A stage the UI doesn't know opens the Models tab.
    expect(parseStageError('stage_timeout: future_stage ran past 600 s.')?.settings).toEqual({ tab: 'models' });
    // Used-up repairs: the message, no Settings target.
    expect(parseStageError(HTML_INVALID)).toEqual({ message: 'reference_html page 2 still failed its HTML checks after 2 repairs.', settings: null });
    expect(parseStageError('brief_invalid: html_brief page 1 still failed after 1 repair.')?.settings).toBeNull();
    // Any other error keeps today's text.
    for (const other of ['Gemini timed out', 'timeout: the model took too long', 'The prototype did not render. Try again.', '', null, undefined, 'stage_timeout:']) {
      expect(parseStageError(other)).toBeNull();
    }
  });
});

/** The App at the fixture build: AppServices own the Settings and Trace dialogs. */
async function renderApp() {
  render(
    <MemoryRouter initialEntries={[`/builds/${id}`]}>
      <Routes>
        <Route path="*" element={<App />} />
      </Routes>
    </MemoryRouter>,
  );
  const trace = (await screen.findByRole('button', { name: 'Trace' }, SLOW)) as HTMLButtonElement;
  await waitFor(() => expect(trace.disabled).toBe(false));
}

/** Adjust in Settings opens Settings with reference_html expanded and Output tokens focused; Escape closes it. */
async function adjustOpensReferenceHtml(scope: HTMLElement) {
  fireEvent.click(within(scope).getByRole('button', { name: 'Adjust in Settings' }));
  const dialog = await screen.findByRole('dialog', { name: 'Settings' }, SLOW);
  const region = await within(dialog).findByRole('region', { name: 'HTML with a reference' }, SLOW);
  await waitFor(() => expect(document.activeElement).toBe(within(region).getByLabelText('Output tokens')));
  fireEvent.keyDown(document, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
}

describe('Stage-limit run errors in the workspace', () => {
  it('a failed accept (Blueprint) shows the message without its code, Adjust in Settings and View model calls', async () => {
    patchMockBuild(id, { stage: 'blueprint', spec_version: null, artifacts: { context: 'confirmed', outline: 'confirmed', design: 'confirmed', blueprint: 'draft' } });
    setMockRunFailure('prototype', CUTOFF);
    const calls = vi.spyOn(api, 'getRunCalls');
    await renderApp();
    const accept = await screen.findByRole('button', { name: 'Accept blueprint' }, SLOW);
    await waitFor(() => expect(accept.matches(':disabled')).toBe(false), SLOW);
    fireEvent.click(accept);
    const title = await screen.findByText("Couldn't render the prototype", undefined, SLOW);
    const alert = title.closest('[role="alert"]') as HTMLElement;
    expect(within(alert).getByText(MESSAGE)).toBeTruthy();
    expect(alert.textContent).not.toContain('stage_output_cutoff');
    expect(within(alert).getAllByRole('button').map((b) => b.textContent)).toEqual(['Adjust in Settings', 'View model calls', 'Try again']);

    await adjustOpensReferenceHtml(alert);

    // View model calls: Trace at that run (the mock recorded it), its calls loading.
    const failed = (await api.listTraces(id)).find((t) => t.node === 'prototype' && t.status === 'error')!;
    fireEvent.click(within(alert).getByRole('button', { name: 'View model calls' }));
    const dialog = await screen.findByRole('dialog', { name: 'Trace' });
    await within(dialog).findByRole('table', { name: 'Model runs' });
    await waitFor(() => expect(calls).toHaveBeenCalledWith(failed.run_id));
    const opened = within(dialog).getAllByRole('button', { expanded: true });
    expect(opened).toHaveLength(1);
    expect(opened[0]!.closest('tr')!.textContent).toContain(CUTOFF);
    await waitFor(() => expect(document.activeElement).toBe(opened[0]));
  });

  it('a failed revise (Prototype) shows the same actions above the comments; html_invalid only View model calls; others as before', async () => {
    await renderApp();
    await screen.findByRole('heading', { name: 'Comments' }, SLOW);
    const fail = (run_id: string, error: string) =>
      act(() => {
        emit(id, { name: 'run.started', data: { run_id, node: 'revise' } });
        emit(id, { name: 'run.finished', data: { run_id, node: 'revise', status: 'error', error } });
      });

    fail('r_rev1', CUTOFF);
    const title = await screen.findByText("Couldn't apply the comments");
    const alert = title.closest('[role="alert"]') as HTMLElement;
    expect(within(alert).getByText(MESSAGE)).toBeTruthy();
    expect(alert.textContent).not.toContain('stage_output_cutoff');
    expect(within(alert).getAllByRole('button').map((b) => b.textContent)).toEqual(['Adjust in Settings', 'View model calls']);
    const calls = vi.spyOn(api, 'getRunCalls');
    fireEvent.click(within(alert).getByRole('button', { name: 'View model calls' }));
    await screen.findByRole('dialog', { name: 'Trace' });
    await waitFor(() => expect(calls).toHaveBeenCalledWith('r_rev1'));
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await adjustOpensReferenceHtml(alert);

    fail('r_rev2', HTML_INVALID);
    await screen.findByText('reference_html page 2 still failed its HTML checks after 2 repairs.');
    const invalid = screen.getByText("Couldn't apply the comments").closest('[role="alert"]') as HTMLElement;
    expect(invalid.textContent).not.toContain('html_invalid');
    expect(within(invalid).getAllByRole('button').map((b) => b.textContent)).toEqual(['View model calls']);

    fail('r_rev3', 'The model returned no changes. Try again.');
    const plain = await screen.findByText('The model returned no changes. Try again.');
    expect(screen.queryByText("Couldn't apply the comments")).toBeNull();
    expect(screen.queryByRole('button', { name: 'View model calls' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Adjust in Settings' })).toBeNull();
    // Today's place: the comments footer's alert.
    expect(plain.closest('footer')).toBeTruthy();
  });
});
