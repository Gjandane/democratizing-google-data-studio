// Tasks 11.1 and 11.2: the Connect sample-data path, job recovery and synthetic labels
// (docs/reference-ui.md "Synthetic data controls"; ../contracts/synthetic-data.md 1.1 "HTTP workflow and provenance").
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import { ApiError, type Build, type GenerationRequest, type GenerationStatus, type ReferenceMode } from '../src/api/types';
import { ActivityStrip } from '../src/features/activity/ActivityStrip';
import { reduceActivity } from '../src/features/activity/activity';
import { DoneStage } from '../src/features/history/DoneStage';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { BuildStage } from '../src/features/workspace/build/BuildStage';
import { idleRun } from '../src/features/workspace/build/buildRun';
import { useBuildStream } from '../src/features/activity/useBuildStream';
import { ConnectStage } from '../src/features/workspace/connect/ConnectStage';
import { POLL_MS, SYNTHETIC_LABEL, SyntheticDataPanel } from '../src/features/workspace/connect/SyntheticDataPanel';
import { PrototypeStage } from '../src/features/workspace/prototype/PrototypeStage';
import { publishWorkspace } from '../src/features/workspace/stretch';
import { resetMockState, setMockRunFailure } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(resetMockState);
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const KEY = /^[A-Za-z0-9_-]{1,64}$/;
const proposal = fixtures.syntheticProposal;
const columnsJson = JSON.stringify(proposal.spec.columns, null, 2);
const png = () => new File(['image'], 'dashboard.png', { type: 'image/png' });

/** Connect on the build's real (mock) event stream, as the workspace renders it. */
function Workspace({ initial }: { initial: Build }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild);
  return <ConnectStage build={build} onBuildChange={setBuild} stretchRuns={chat.stretchRuns} />;
}

async function setup(mode?: ReferenceMode) {
  const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
  if (mode) {
    await api.uploadReferences(build.id, [png()], mode, '');
    await waitFor(async () => expect(await api.getReferences(build.id)).not.toBeNull());
  }
  render(<Workspace initial={build} />);
  return build;
}

const choice = (name: RegExp) => screen.getByRole('radio', { name }) as HTMLInputElement;
const panel = () => screen.getByRole('region', { name: 'Sample data' });
const columnsBox = () => screen.getByLabelText('Columns (JSON)') as HTMLTextAreaElement;
const rowsBox = () => screen.getByLabelText('Row count') as HTMLInputElement;
const seedBox = () => screen.getByLabelText('Seed') as HTMLInputElement;
const generateButton = () => screen.getByRole('button', { name: 'Generate sample data' }) as HTMLButtonElement;
const type = (input: HTMLElement, value: string) => fireEvent.change(input, { target: { value } });
const describedText = (input: HTMLElement) =>
  (input.getAttribute('aria-describedby') ?? '').split(' ').map((id) => document.getElementById(id)?.textContent ?? '').join(' ');
const sent = (spy: { mock: { calls: unknown[][] } }, i: number) => spy.mock.calls[i]![1] as GenerationRequest;

async function openSampleData() {
  fireEvent.click(choice(/^Generate sample data/));
  await waitFor(() => expect(screen.queryByText(/The saved reference isn't loaded/)).toBeNull());
  return panel();
}

describe('Connect offers sample data as an explicit choice', () => {
  it('shows Upload/connect data and Generate sample data with no source, and keeps edits across switching', async () => {
    await setup();
    expect(choice(/^Upload\/connect data/).checked).toBe(true);
    expect(choice(/^Generate sample data/).checked).toBe(false);
    expect(screen.getByRole('region', { name: 'Upload CSV files' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Sample data' })).toBeNull();
    await openSampleData();
    expect(screen.queryByRole('region', { name: 'Upload CSV files' })).toBeNull();
    expect(within(panel()).getByText('Invented sample data')).toBeTruthy();
    type(columnsBox(), '[]');
    fireEvent.click(choice(/^Upload\/connect data/));
    expect(screen.queryByRole('region', { name: 'Sample data' })).toBeNull();
    fireEvent.click(choice(/^Generate sample data/));
    expect(columnsBox().value).toBe('[]');
  });

  it('offers no sample data once the build has a source', async () => {
    render(<Workspace initial={fixtures.build} />);
    await screen.findByRole('table', { name: 'Sources' });
    expect(screen.queryByRole('radio', { name: /^Generate sample data/ })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Sample data' })).toBeNull();
  });
});

describe('Schema proposal', () => {
  it('posts Propose schema once for a recreate set and shows fields, types, generators and assumptions as invented', async () => {
    const build = await setup('recreate');
    const reference = (await api.getReferences(build.id))!;
    const propose = vi.spyOn(api, 'proposeSyntheticSchema');
    const sideEffects = (['decideFeasibility', 'compileRecipe', 'runBuild', 'draftContext', 'acceptBlueprint'] as const).map((name) => vi.spyOn(api, name));
    await openSampleData();
    const button = within(panel()).getByRole('button', { name: 'Propose schema' });
    act(() => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    expect(propose).toHaveBeenCalledExactlyOnceWith(build.id, reference.id);
    const table = await screen.findByRole('table', { name: 'Proposed columns' });
    const rows = within(table).getAllByRole('row').slice(1).map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent));
    expect(rows).toEqual([
      ['region', 'string', 'One of East, West', '0%'],
      ['quantity', 'integer', 'Whole numbers 1 to 8', '0%'],
      ['unit_price', 'number', 'Decimals 10 to 100, 2 places', '0%'],
      ['revenue', 'number', 'quantity × unit_price, 2 places', '0%'],
    ]);
    expect(within(panel()).getByText('Names and types are guesses from your screenshot. The generators invent every value.')).toBeTruthy();
    expect(within(screen.getByRole('list', { name: 'Assumptions' })).getByText(proposal.assumptions[0]!)).toBeTruthy();
    expect(columnsBox().value).toBe(columnsJson);
    expect(rowsBox().value).toBe('1000');
    expect(seedBox().value).toBe('42');
    expect(within(panel()).getByRole('status').textContent).toContain('Schema proposed');
    for (const spy of sideEffects) expect(spy).not.toHaveBeenCalled();
  });

  it('explains why a style-only set needs a schema and offers no proposal', async () => {
    await setup('style');
    await openSampleData();
    expect(within(panel()).getByText(/Your reference is a style example: it shows how a dashboard looks, not what data it holds/)).toBeTruthy();
    expect(within(panel()).queryByRole('button', { name: 'Propose schema' })).toBeNull();
    expect(within(panel()).getByRole('button', { name: 'Change the reference' })).toBeTruthy();
  });

  it('shows the style explanation when the backend answers synthetic_schema_unavailable', async () => {
    await setup('recreate');
    vi.spyOn(api, 'proposeSyntheticSchema').mockRejectedValue(new ApiError(422, 'synthetic_schema_unavailable', 'No dataset in this reference.'));
    await openSampleData();
    fireEvent.click(within(panel()).getByRole('button', { name: 'Propose schema' }));
    expect((await within(panel()).findByRole('alert')).textContent).toContain('Switch it to Recreate dashboard, or enter the columns yourself');
  });

  it('reports a failed proposal run and keeps manual entry open', async () => {
    await setup('recreate');
    setMockRunFailure('synthetic_schema', 'The model returned no columns');
    await openSampleData();
    fireEvent.click(within(panel()).getByRole('button', { name: 'Propose schema' }));
    expect((await within(panel()).findByRole('alert')).textContent).toContain('The model returned no columns. Enter the columns yourself');
    expect(screen.queryByRole('table', { name: 'Proposed columns' })).toBeNull();
    expect(columnsBox().readOnly).toBe(false);
  });
});

describe('Schema editor', () => {
  it('works with no image: hand-written columns generate with proposal_id null, 1000 rows and seed 42', async () => {
    const build = await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData');
    const sideEffects = (['decideFeasibility', 'compileRecipe', 'runBuild', 'draftContext', 'acceptBlueprint'] as const).map((name) => vi.spyOn(api, name));
    await openSampleData();
    expect(within(panel()).getByText(/No reference yet/)).toBeTruthy();
    expect(rowsBox().value).toBe('1000');
    expect(seedBox().value).toBe('42');
    expect(generateButton().disabled).toBe(true);
    type(columnsBox(), columnsJson);
    expect(generateButton().disabled).toBe(false);
    act(() => {
      fireEvent.click(generateButton());
      fireEvent.click(generateButton());
    });
    expect(generate).toHaveBeenCalledTimes(1);
    const body = sent(generate, 0);
    expect(body.generation_key).toMatch(KEY);
    expect(body).toEqual({ generation_key: body.generation_key, proposal_id: null, spec: { schema_version: 1, row_count: 1000, seed: 42, columns: proposal.spec.columns } });
    expect(generate.mock.calls[0]![0]).toBe(build.id);
    const sources = await screen.findByRole('table', { name: 'Sources' });
    const [name, kind] = within(within(sources).getAllByRole('row')[1]!).getAllByRole('cell');
    expect([name!.firstElementChild!.firstElementChild!.textContent, kind!.textContent]).toEqual(['Synthetic sample data', 'Synthetic sample data']);
    expect(screen.queryByRole('region', { name: 'Sample data' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Draft context' }));
    expect(screen.getByText('Synthetic sample data added. Review it under Sources, then draft the context.')).toBeTruthy();
    for (const spy of sideEffects) expect(spy).not.toHaveBeenCalled();
  });

  it('blocks Generate with an inline message while the columns are not a JSON array', async () => {
    const generate = vi.spyOn(api, 'generateSyntheticData');
    await setup();
    await openSampleData();
    type(columnsBox(), '[{"name": ');
    expect(generateButton().disabled).toBe(true);
    expect(columnsBox().getAttribute('aria-invalid')).toBe('true');
    expect(describedText(columnsBox())).toMatch(/^This isn't valid JSON \(.+\)\. Fix it to generate\.$/);
    type(columnsBox(), '{"columns": []}');
    expect(generateButton().disabled).toBe(true);
    expect(describedText(columnsBox())).toBe('Enter a JSON array of columns: start with [ and end with ].');
    type(rowsBox(), '1e3');
    type(columnsBox(), columnsJson);
    expect(generateButton().disabled).toBe(true);
    expect(describedText(rowsBox())).toBe('Enter a whole number of rows.');
    type(rowsBox(), '1000');
    expect(generateButton().disabled).toBe(false);
    expect(generate).not.toHaveBeenCalled();
  });

  it('shows 422 invalid_generation_spec field errors at their path and keeps the edits', async () => {
    await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData').mockRejectedValueOnce(
      new ApiError(422, 'invalid_generation_spec', 'The generation spec is invalid', { field: 'columns[1].name', reason: 'must be snake_case' }),
    );
    await openSampleData();
    const edited = columnsJson.replace('"quantity"', '"Quantity Sold"');
    type(columnsBox(), edited);
    fireEvent.click(generateButton());
    await waitFor(() => expect(describedText(columnsBox())).toBe('columns[1].name: must be snake_case.'));
    expect(columnsBox().value).toBe(edited);
    expect(columnsBox().getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(columnsBox());
    // The mock validates like the backend: a row count out of bounds is reported at row_count.
    type(rowsBox(), '0');
    fireEvent.click(generateButton());
    await waitFor(() => expect(describedText(rowsBox())).toBe('must be between 1 and 100000.'));
    expect(rowsBox().value).toBe('0');
    expect(columnsBox().value).toBe(edited);
    expect(document.activeElement).toBe(rowsBox());
    expect(generate).toHaveBeenCalledTimes(2);
  });
});

describe('Generation key', () => {
  const offline = () => new ApiError(0, 'network_error', "Can't reach the backend. Start it on port 8000, then try again.");

  it('resends the identical request with the same key on a transport-error retry', async () => {
    const build = await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData').mockRejectedValueOnce(offline());
    const status = vi.spyOn(api, 'getSyntheticJob');
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    const alert = await within(panel()).findByRole('alert');
    // The unanswered POST is checked by its key first: this one never registered.
    expect(status).toHaveBeenCalledExactlyOnceWith(build.id, sent(generate, 0).generation_key);
    expect(alert.textContent).toContain("The request didn't reach the backend, so nothing was generated. Select Retry to send it again.");
    expect(generate).toHaveBeenCalledTimes(1);
    expect(columnsBox().value).toBe(columnsJson);
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }));
    await screen.findByRole('table', { name: 'Sources' });
    expect(generate).toHaveBeenCalledTimes(2);
    expect(sent(generate, 1)).toEqual(sent(generate, 0));
    expect(sent(generate, 1).generation_key).toBe(sent(generate, 0).generation_key);
  });

  it('mints a new key after any edit to the columns, row count or seed', async () => {
    await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData').mockRejectedValue(offline());
    await openSampleData();
    type(columnsBox(), columnsJson);
    const attempt = async (n: number) => {
      fireEvent.click(generateButton());
      await waitFor(() => expect(generate).toHaveBeenCalledTimes(n));
      await within(panel()).findByRole('alert');
      return sent(generate, n - 1);
    };
    const first = await attempt(1);
    const again = await attempt(2);
    expect(again).toEqual(first);
    type(seedBox(), '7');
    const seeded = await attempt(3);
    expect(seeded.spec.seed).toBe(7);
    type(rowsBox(), '250');
    const counted = await attempt(4);
    expect(counted.spec.row_count).toBe(250);
    type(columnsBox(), JSON.stringify(proposal.spec.columns.slice(0, 2)));
    const trimmed = await attempt(5);
    expect(trimmed.spec.columns).toHaveLength(2);
    const keys = [first, seeded, counted, trimmed].map((body) => body.generation_key);
    keys.forEach((key) => expect(key).toMatch(KEY));
    expect(new Set(keys).size).toBe(4);
  });

  it('explains a 409 synthetic_request_conflict and mints a new key', async () => {
    await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData').mockRejectedValueOnce(
      new ApiError(409, 'synthetic_request_conflict', 'This generation key was already used for a different request.'),
    );
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    const alert = await within(panel()).findByRole('alert');
    expect(alert.textContent).toContain('The request changed since its generation key was first used');
    expect(within(alert).queryByRole('button', { name: 'Retry' })).toBeNull();
    fireEvent.click(generateButton());
    await screen.findByRole('table', { name: 'Sources' });
    expect(sent(generate, 1).generation_key).not.toBe(sent(generate, 0).generation_key);
    expect(sent(generate, 1).spec).toEqual(sent(generate, 0).spec);
  });

  it('mints a new key after a failed generation run', async () => {
    await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData');
    setMockRunFailure('synthetic_generate', 'BigQuery load failed');
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    expect((await within(panel()).findByRole('alert')).textContent).toContain('BigQuery load failed. Your columns are kept.');
    setMockRunFailure('synthetic_generate', undefined);
    await waitFor(() => expect(generateButton().disabled).toBe(false));
    fireEvent.click(generateButton());
    await screen.findByRole('table', { name: 'Sources' });
    expect(sent(generate, 1).generation_key).not.toBe(sent(generate, 0).generation_key);
  });

  it('says a request over 64 KiB is too large and keeps the columns', async () => {
    await setup();
    await openSampleData();
    const huge = JSON.stringify([{ name: 'note', type: 'string', nullable_fraction: 0, generator: { kind: 'choice', values: ['x'.repeat(70_000)] } }]);
    type(columnsBox(), huge);
    fireEvent.click(generateButton());
    expect((await within(panel()).findByRole('alert')).textContent).toContain('This sample-data request is over 64 KiB');
    expect(columnsBox().value).toBe(huge);
  });
});

describe('Runs and stale proposals', () => {
  it('follows a run.finished that arrives before its 202', async () => {
    const build = await setup();
    vi.spyOn(api, 'generateSyntheticData').mockImplementation(async () => {
      act(() => publishWorkspace(build.id, { name: 'run.finished', data: { run_id: 'r_early', node: 'synthetic_generate', status: 'ok', error: null } }));
      return { run_id: 'r_early' };
    });
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    await waitFor(() => expect(within(panel()).getByRole('status').textContent).toContain('Sample data generated.'));
    expect(generateButton().disabled).toBe(false);
  });

  it('reads the job status on reconnect instead of waiting for a missed run.finished', async () => {
    const build = await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData').mockResolvedValue({ run_id: 'r_lost' });
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    await within(panel()).findByText('Generating CSV…');
    expect(generateButton().disabled).toBe(true);
    const key = sent(generate, 0).generation_key;
    const status = vi.spyOn(api, 'getSyntheticJob').mockResolvedValue({ ...fixtures.syntheticJobSucceeded, generation_key: key, run_id: 'r_lost' });
    const refetch = vi.spyOn(api, 'getBuild');
    act(() => publishWorkspace(build.id, { name: 'ready', data: { build_id: build.id } }));
    await within(panel()).findByText('Sample data generated. It shows under Sources as Synthetic sample data.');
    expect(status).toHaveBeenCalledWith(build.id, key);
    expect(refetch).toHaveBeenCalledWith(build.id);
    expect(generate).toHaveBeenCalledTimes(1);
  });

  it('offers the same request again when the backend has no record of a run on reconnect', async () => {
    const build = await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData').mockResolvedValue({ run_id: 'r_lost' });
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    await within(panel()).findByText('Generating CSV…');
    act(() => publishWorkspace(build.id, { name: 'ready', data: { build_id: build.id } }));
    const alert = await within(panel()).findByRole('alert');
    expect(alert.textContent).toContain('The backend has no record of this request, so nothing was generated.');
    expect(generateButton().disabled).toBe(false);
    expect(choice(/^Upload\/connect data/).disabled).toBe(false);
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(2));
    expect(sent(generate, 1)).toEqual(sent(generate, 0));
  });

  it('sends proposed columns as the user\'s own schema once the reference changes', async () => {
    const build = await setup('recreate');
    const generate = vi.spyOn(api, 'generateSyntheticData').mockRejectedValue(new ApiError(0, 'network_error', "Can't reach the backend."));
    await openSampleData();
    fireEvent.click(within(panel()).getByRole('button', { name: 'Propose schema' }));
    await screen.findByRole('table', { name: 'Proposed columns' });
    fireEvent.click(generateButton());
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
    expect(sent(generate, 0).proposal_id).toMatch(/^proposal_/);
    await api.uploadReferences(build.id, [png()], 'recreate', 'A newer screenshot.');
    await within(panel()).findByText(/These columns came from an earlier proposal/);
    expect(screen.queryByRole('table', { name: 'Proposed columns' })).toBeNull();
    expect(columnsBox().value).toBe(columnsJson);
    await waitFor(() => expect(generateButton().disabled).toBe(false));
    fireEvent.click(generateButton());
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(2));
    expect(sent(generate, 1).proposal_id).toBeNull();
    expect(sent(generate, 1).generation_key).not.toBe(sent(generate, 0).generation_key);
  });

  it('stops sending a proposal the backend calls stale, with a new key', async () => {
    await setup('recreate');
    const generate = vi.spyOn(api, 'generateSyntheticData').mockRejectedValueOnce(new ApiError(409, 'synthetic_proposal_stale', 'The proposal is out of date.'));
    await openSampleData();
    fireEvent.click(within(panel()).getByRole('button', { name: 'Propose schema' }));
    await screen.findByRole('table', { name: 'Proposed columns' });
    fireEvent.click(generateButton());
    expect((await within(panel()).findByRole('alert')).textContent).toContain('they now count as your own schema');
    expect(within(panel()).getByText(/These columns came from an earlier proposal/)).toBeTruthy();
    fireEvent.click(generateButton());
    await screen.findByRole('table', { name: 'Sources' });
    expect(sent(generate, 0).proposal_id).toMatch(/^proposal_/);
    expect(sent(generate, 1).proposal_id).toBeNull();
    expect(sent(generate, 1).generation_key).not.toBe(sent(generate, 0).generation_key);
  });
});

describe('Activity strip', () => {
  it.each([
    ['synthetic_schema', 'Reading the reference fields'],
    ['synthetic_generate', 'Generating invented sample rows'],
  ])('shows a %s phrase', (node, phrase) => {
    const activity = reduceActivity([], { name: 'run.started', data: { run_id: 'r_1', node } }, Date.now() - 1000);
    render(<ActivityStrip activity={activity} />);
    expect(screen.getByText(phrase)).toBeTruthy();
    expect(screen.getByRole('status').textContent).toBe(`${phrase}…`);
  });
});

// ---------- Task 11.2: job recovery, polling, download and provenance ----------

/** Connect alone, with no event stream: only the job status can report a result. */
function Quiet({ initial, onAssessmentInvalidated }: { initial: Build; onAssessmentInvalidated?: () => void }) {
  const [build, setBuild] = useState(initial);
  return <ConnectStage build={build} onBuildChange={setBuild} onAssessmentInvalidated={onAssessmentInvalidated} />;
}

const offline = () => new ApiError(0, 'network_error', "Can't reach the backend. Start it on port 8000, then try again.");
/** A job status built from the shared fixtures, never a copy. */
const jobOf = (key: string, change: Partial<GenerationStatus> = {}): GenerationStatus => ({ ...fixtures.syntheticJobSucceeded, generation_key: key, ...change });
const running = (key: string, state: GenerationStatus['state']) => jobOf(key, { state, source_id: null });
const statusLine = () => within(panel()).getByRole('status').textContent;
// The mock answers on setTimeout too, so a fake clock drives both the API and the 2 s polls (Known gotchas).
const useFakeClock = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

describe('Job status recovery', () => {
  it('(1) recovers a lost POST response by GET jobs/{key}, with no second POST', async () => {
    const build = await setup();
    const realGenerate = api.generateSyntheticData;
    // The backend registers the request, but its 202 never arrives.
    const generate = vi.spyOn(api, 'generateSyntheticData').mockImplementation(async (id, body) => {
      await realGenerate(id, body);
      throw offline();
    });
    const status = vi.spyOn(api, 'getSyntheticJob');
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    await screen.findByRole('table', { name: 'Sources' });
    expect(generate).toHaveBeenCalledTimes(1);
    expect(status).toHaveBeenCalledWith(build.id, sent(generate, 0).generation_key);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText('Synthetic sample data added. Review it under Sources, then draft the context.')).toBeTruthy();
  });

  it('(2) polls an active job every 2 s, shows its stage, and stops on a terminal state', async () => {
    useFakeClock();
    vi.spyOn(api, 'getSyntheticProposal').mockResolvedValue(null);
    vi.spyOn(api, 'listSyntheticJobs').mockResolvedValue([running('sd_run', 'queued')]);
    const status = vi
      .spyOn(api, 'getSyntheticJob')
      .mockResolvedValueOnce(running('sd_run', 'generating'))
      .mockResolvedValueOnce(running('sd_run', 'loading'))
      .mockResolvedValue(jobOf('sd_run'));
    const onGenerated = vi.fn();
    const onJobFound = vi.fn();
    render(<SyntheticDataPanel buildId="b_poll" reference={null} onGenerated={onGenerated} onJobFound={onJobFound} />);
    await advance(0);
    expect(onJobFound).toHaveBeenCalledTimes(1);
    expect(statusLine()).toBe('Generating CSV…');
    expect(generateButton().disabled).toBe(true);
    await advance(POLL_MS - 1);
    expect(status).not.toHaveBeenCalled();
    await advance(1);
    expect(status).toHaveBeenCalledExactlyOnceWith('b_poll', 'sd_run');
    await advance(POLL_MS);
    expect(status).toHaveBeenCalledTimes(2);
    expect(statusLine()).toBe('Loading sample data…');
    expect(onGenerated).not.toHaveBeenCalled();
    await advance(POLL_MS);
    expect(status).toHaveBeenCalledTimes(3);
    expect(onGenerated).toHaveBeenCalledTimes(1);
    expect(statusLine()).toBe('Sample data generated. It shows under Sources as Synthetic sample data.');
    await advance(POLL_MS * 5);
    expect(status).toHaveBeenCalledTimes(3);
    expect(onGenerated).toHaveBeenCalledTimes(1);
  });

  it('(2) stops polling when the panel unmounts', async () => {
    useFakeClock();
    vi.spyOn(api, 'getSyntheticProposal').mockResolvedValue(null);
    vi.spyOn(api, 'listSyntheticJobs').mockResolvedValue([running('sd_run', 'generating')]);
    const status = vi.spyOn(api, 'getSyntheticJob').mockResolvedValue(running('sd_run', 'generating'));
    const view = render(<SyntheticDataPanel buildId="b_poll" reference={null} />);
    await advance(0);
    await advance(POLL_MS);
    expect(status).toHaveBeenCalledTimes(1);
    view.unmount();
    await advance(POLL_MS * 5);
    expect(status).toHaveBeenCalledTimes(1);
  });

  it('(3) shows Retry for a failed job only once retry_ready is true, and Retry uses a new key', async () => {
    useFakeClock();
    vi.spyOn(api, 'getSyntheticProposal').mockResolvedValue(null);
    vi.spyOn(api, 'listSyntheticJobs').mockResolvedValue([]);
    const generate = vi.spyOn(api, 'generateSyntheticData').mockResolvedValue({ run_id: 'r_failed' });
    let cleaned = false;
    const status = vi.spyOn(api, 'getSyntheticJob').mockImplementation(async (_id, key) => ({
      ...fixtures.syntheticJobFailed,
      generation_key: key,
      run_id: 'r_failed',
      retry_ready: cleaned,
      error: { code: 'synthetic_load_failed', message: 'BigQuery load failed' },
    }));
    render(<SyntheticDataPanel buildId="b_fail" reference={null} />);
    await advance(0);
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    await advance(0);
    await advance(POLL_MS);
    expect(status).toHaveBeenCalledTimes(1);
    let alert = within(panel()).getByRole('alert');
    expect(alert.textContent).toContain('BigQuery load failed. Your columns are kept. Retry shows here once the failed run is cleaned up.');
    expect(within(alert).queryByRole('button', { name: 'Retry' })).toBeNull();
    expect(generateButton().disabled).toBe(true);
    expect(statusLine()).toBe('Cleaning up the failed run…');
    cleaned = true;
    await advance(POLL_MS);
    expect(status).toHaveBeenCalledTimes(2);
    alert = within(panel()).getByRole('alert');
    expect(alert.textContent).toContain('BigQuery load failed. Your columns are kept. Select Retry to generate them again.');
    expect(generateButton().disabled).toBe(false);
    await advance(POLL_MS * 5);
    expect(status).toHaveBeenCalledTimes(2);
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }));
    await advance(0);
    expect(generate).toHaveBeenCalledTimes(2);
    expect(sent(generate, 1).generation_key).toMatch(KEY);
    expect(sent(generate, 1).generation_key).not.toBe(sent(generate, 0).generation_key);
    expect(sent(generate, 1).spec).toEqual(sent(generate, 0).spec);
  });

  it('(3) shows a failed job found after a reload; Retry sends the columns with a new key', async () => {
    useFakeClock();
    vi.spyOn(api, 'getSyntheticProposal').mockResolvedValue(null);
    vi.spyOn(api, 'listSyntheticJobs').mockResolvedValue([fixtures.syntheticJobFailed]);
    const generate = vi.spyOn(api, 'generateSyntheticData').mockResolvedValue({ run_id: 'r_next' });
    vi.spyOn(api, 'getSyntheticJob').mockImplementation(async (_id, key) => jobOf(key, { state: 'generating', source_id: null }));
    const onJobFound = vi.fn();
    render(<SyntheticDataPanel buildId="b_reload" reference={null} onJobFound={onJobFound} />);
    await advance(0);
    expect(onJobFound).toHaveBeenCalledTimes(1);
    const alert = within(panel()).getByRole('alert');
    expect(alert.textContent).toContain('The last sample-data run failed');
    expect(alert.textContent).toContain(fixtures.syntheticJobFailed.error!.message);
    const retry = () => within(alert).getByRole('button', { name: 'Retry' }) as HTMLButtonElement;
    expect(retry().disabled).toBe(true); // A reload loses the columns: enter them first.
    type(columnsBox(), columnsJson);
    expect(retry().disabled).toBe(false);
    fireEvent.click(retry());
    await advance(0);
    expect(generate).toHaveBeenCalledTimes(1);
    expect(sent(generate, 0).generation_key).not.toBe(fixtures.syntheticJobFailed.generation_key);
  });

  it('(1) keeps a server error\'s own message when its request never registered', async () => {
    await setup();
    vi.spyOn(api, 'generateSyntheticData').mockRejectedValueOnce(
      new ApiError(503, 'gcp_not_configured', 'No GCP project is set. Open Settings, enter the project, then try again.'),
    );
    const status = vi.spyOn(api, 'getSyntheticJob');
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    const alert = await within(panel()).findByRole('alert');
    expect(status).toHaveBeenCalledTimes(1);
    expect(alert.textContent).toContain('No GCP project is set. Open Settings, enter the project, then try again. Nothing was generated.');
    expect(within(alert).getByRole('button', { name: 'Retry' })).toBeTruthy();
  });

  it('(2) says when the job status can\'t be read, and keeps polling', async () => {
    useFakeClock();
    vi.spyOn(api, 'getSyntheticProposal').mockResolvedValue(null);
    vi.spyOn(api, 'listSyntheticJobs').mockResolvedValue([running('sd_run', 'generating')]);
    const status = vi.spyOn(api, 'getSyntheticJob').mockRejectedValueOnce(offline()).mockResolvedValue(running('sd_run', 'loading'));
    render(<SyntheticDataPanel buildId="b_poll" reference={null} />);
    await advance(0);
    await advance(POLL_MS);
    expect(status).toHaveBeenCalledTimes(1);
    expect(statusLine()).toBe("Generating CSV… Can't read the run's status right now; checking again.");
    await advance(POLL_MS);
    expect(status).toHaveBeenCalledTimes(2);
    expect(statusLine()).toBe('Loading sample data…');
  });

  it('(2) stops polling with an error when the build is gone', async () => {
    useFakeClock();
    vi.spyOn(api, 'getSyntheticProposal').mockResolvedValue(null);
    vi.spyOn(api, 'listSyntheticJobs').mockResolvedValue([running('sd_run', 'generating')]);
    const status = vi
      .spyOn(api, 'getSyntheticJob')
      .mockRejectedValue(new ApiError(404, 'build_not_found', 'This build no longer exists. Open another one from History.'));
    render(<SyntheticDataPanel buildId="b_gone" reference={null} />);
    await advance(0);
    await advance(POLL_MS);
    expect(within(panel()).getByRole('alert').textContent).toContain('This build no longer exists.');
    await advance(POLL_MS * 5);
    expect(status).toHaveBeenCalledTimes(1);
  });

  it('(4) after a remount, a succeeded job restores the source, its provenance, the Synthetic badge and Download CSV', async () => {
    const build = await setup();
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    await screen.findByRole('table', { name: 'Sources' });
    cleanup();
    // Remount from a view that predates the source (a reload mid-run), with no event stream.
    const jobs = vi.spyOn(api, 'listSyntheticJobs');
    const datasets = vi.spyOn(api, 'listSyntheticDatasets');
    render(<Quiet initial={build} />);
    const sources = await screen.findByRole('table', { name: 'Sources' });
    expect(jobs).toHaveBeenCalledWith(build.id);
    const source = (await api.getBuild(build.id)).sources[0]!;
    const [name, kind] = within(within(sources).getAllByRole('row')[1]!).getAllByRole('cell');
    expect(kind!.textContent).toBe(SYNTHETIC_LABEL);
    const link = within(name!).getByRole('link', { name: 'Download CSV' });
    expect(link.getAttribute('href')).toBe(`/api/builds/${build.id}/synthetic-data/${source.id}/csv`);
    expect(link.getAttribute('download')).toBe('synthetic-sample.csv');
    const details = await screen.findByRole('region', { name: 'Sample data details' });
    await within(details).findByText(fixtures.syntheticDataset.sha256);
    expect(datasets).toHaveBeenCalledWith(build.id);
    expect(within(details).getByText(fixtures.syntheticDataset.generator_version)).toBeTruthy();
    expect(within(details).getByText('1,000')).toBeTruthy();
    expect(within(details).getByText('19.3 KB')).toBeTruthy();
  });

  it('(4) labels a source by its kind and reads its provenance from the shared dataset fixture', async () => {
    const datasets = vi.spyOn(api, 'listSyntheticDatasets').mockResolvedValue([fixtures.syntheticDataset]);
    const renamed = { ...fixtures.syntheticSource, name: 'orders.csv' };
    const build: Build = { ...fixtures.build, stage: 'connect', sources: [renamed, fixtures.build.sources[0]!] };
    render(<Quiet initial={build} />);
    const rows = within(screen.getByRole('table', { name: 'Sources' })).getAllByRole('row').slice(1);
    expect(within(rows[0]!).getAllByRole('cell')[1]!.textContent).toBe(SYNTHETIC_LABEL);
    expect(within(rows[0]!).getByRole('link', { name: 'Download CSV' })).toBeTruthy();
    expect(within(rows[1]!).getAllByRole('cell')[1]!.textContent).toBe('CSV upload');
    expect(within(rows[1]!).queryByRole('link', { name: 'Download CSV' })).toBeNull();
    const details = screen.getByRole('region', { name: 'Sample data details' });
    await within(details).findByText(fixtures.syntheticDataset.sha256);
    expect(datasets).toHaveBeenCalledWith(build.id);
    const assumptions = within(details).getByRole('list', { name: 'Assumptions of orders.csv' });
    expect(within(assumptions).getByText(fixtures.syntheticDataset.assumptions[0]!)).toBeTruthy();
  });
});

describe('Synthetic labels after Connect', () => {
  const withSample = (build: Build): Build => ({ ...build, sources: [fixtures.syntheticSource] });
  const banner = () => screen.queryByRole('note', { name: SYNTHETIC_LABEL });

  it('(5) shows the sample-data banner on Prototype, Build and the Done report-link view, and only with synthetic data', async () => {
    let view = render(<PrototypeStage build={withSample(fixtures.build)} applying={false} commentsError={null} />);
    expect(banner()!.textContent).toContain('not your data or the values in your screenshot');
    view.unmount();
    view = render(<PrototypeStage build={fixtures.build} applying={false} commentsError={null} />);
    expect(banner()).toBeNull();
    view.unmount();
    view = render(<BuildStage build={withSample(fixtures.build)} run={idleRun} />);
    expect(banner()!.textContent).toContain('invented rows');
    view.unmount();
    view = render(<BuildStage build={fixtures.build} run={idleRun} />);
    expect(banner()).toBeNull();
    view.unmount();
    render(<DoneStage build={withSample(fixtures.buildDone)} onBuildChange={() => {}} />);
    const published = screen.getByRole('region', { name: 'Published dashboard' });
    expect(within(published).getByRole('link', { name: /Open in Data Studio/ })).toBeTruthy();
    expect(published.nextElementSibling).toBe(banner());
    expect(banner()!.textContent).toContain('not real data or values from your screenshot');
    await screen.findByRole('list', { name: 'Versions' });
  });

  it('(5) offers New dashboard instead of generating when the build has a real source', async () => {
    const generate = vi.spyOn(api, 'generateSyntheticData');
    render(
      <MemoryRouter>
        <Quiet initial={{ ...fixtures.build, stage: 'connect' }} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole('radio', { name: /^Generate sample data/ })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Sample data' })).toBeNull();
    expect(screen.getByText(/It can't be mixed with these sources/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'New dashboard' }));
    expect(screen.getByRole('dialog', { name: 'New build' })).toBeTruthy();
    expect(generate).not.toHaveBeenCalled();
  });

  it('(5) answers 409 synthetic_requires_empty_build with New dashboard', async () => {
    const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
    vi.spyOn(api, 'generateSyntheticData').mockRejectedValue(new ApiError(409, 'synthetic_requires_empty_build', 'This build already has data.'));
    render(
      <MemoryRouter>
        <Workspace initial={build} />
      </MemoryRouter>,
    );
    await openSampleData();
    type(columnsBox(), columnsJson);
    await waitFor(() => expect(generateButton().disabled).toBe(false));
    fireEvent.click(generateButton());
    const alert = await within(panel()).findByRole('alert');
    expect(alert.textContent).toContain('Start a new dashboard to use sample data.');
    expect(within(alert).queryByRole('button', { name: 'Retry' })).toBeNull();
    fireEvent.click(within(alert).getByRole('button', { name: 'New dashboard' }));
    expect(screen.getByRole('dialog', { name: 'New build' })).toBeTruthy();
  });
});

describe('After a successful generation', () => {
  const effects = () =>
    (['decideFeasibility', 'checkFeasibility', 'compileRecipe', 'runBuild', 'draftContext', 'acceptBlueprint', 'postComments'] as const).map((name) =>
      vi.spyOn(api, name),
    );

  it('(6) refetches build, sources, docs and assessment, and never POSTs decisions, recipe or run', async () => {
    const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
    const forbidden = effects();
    render(
      <MemoryRouter initialEntries={[`/builds/${build.id}`]}>
        <Routes>
          <Route path="/builds/:id" element={<WorkspaceShell />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByRole('radio', { name: /^Generate sample data/ });
    await openSampleData();
    type(columnsBox(), columnsJson);
    await waitFor(() => expect(generateButton().disabled).toBe(false));
    const getBuild = vi.spyOn(api, 'getBuild');
    const assessment = vi.spyOn(api, 'getFeasibility');
    const datasets = vi.spyOn(api, 'listSyntheticDatasets');
    fireEvent.click(generateButton());
    await screen.findByRole('table', { name: 'Sources' });
    await waitFor(() => expect(datasets).toHaveBeenCalledWith(build.id));
    await waitFor(() => expect(assessment).toHaveBeenCalledWith(build.id));
    expect(getBuild).toHaveBeenCalledWith(build.id);
    const fresh = (await getBuild.mock.results.at(-1)!.value) as Build;
    expect(fresh.sources.map((s) => s.kind)).toEqual(['synthetic']);
    expect(fresh.docs).toEqual((await api.getBuild(build.id)).docs);
    expect(screen.getByRole('heading', { level: 2, name: 'Connect' })).toBeTruthy();
    for (const spy of forbidden) expect(spy).not.toHaveBeenCalled();
  });

  it('(6) a success seen only through polling still refetches the build and the assessment', async () => {
    const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
    useFakeClock();
    vi.spyOn(api, 'generateSyntheticData').mockResolvedValue({ run_id: 'r_quiet' });
    vi.spyOn(api, 'getSyntheticJob').mockImplementation(async (_id, key) => jobOf(key, { run_id: 'r_quiet' }));
    const getBuild = vi.spyOn(api, 'getBuild');
    const forbidden = effects();
    const invalidated = vi.fn();
    render(<Quiet initial={build} onAssessmentInvalidated={invalidated} />);
    await advance(0);
    fireEvent.click(choice(/^Generate sample data/));
    await advance(0);
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    await advance(0);
    expect(invalidated).not.toHaveBeenCalled();
    await advance(POLL_MS);
    expect(invalidated).toHaveBeenCalledTimes(1);
    expect(getBuild).toHaveBeenCalledWith(build.id);
    for (const spy of forbidden) expect(spy).not.toHaveBeenCalled();
  });
});
