// Task 11.1: the Connect sample-data path (docs/reference-ui.md "Synthetic data controls";
// ../contracts/synthetic-data.md 1.1 "HTTP workflow and provenance").
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import { ApiError, type Build, type GenerationRequest, type ReferenceMode } from '../src/api/types';
import { ActivityStrip } from '../src/features/activity/ActivityStrip';
import { reduceActivity } from '../src/features/activity/activity';
import { useBuildStream } from '../src/features/workspace/chat/useBuildStream';
import { ConnectStage } from '../src/features/workspace/connect/ConnectStage';
import { publishWorkspace } from '../src/features/workspace/stretch';
import { resetMockState, setMockRunFailure } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(resetMockState);
afterEach(() => {
  cleanup();
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
    const sideEffects = (['decideFeasibility', 'compileRecipe', 'runBuild', 'startInterview', 'generatePlan'] as const).map((name) => vi.spyOn(api, name));
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
    const sideEffects = (['decideFeasibility', 'compileRecipe', 'runBuild', 'startInterview', 'generatePlan'] as const).map((name) => vi.spyOn(api, name));
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
    expect([name!.textContent, kind!.textContent]).toEqual(['Synthetic sample data', 'Synthetic sample data']);
    expect(screen.queryByRole('region', { name: 'Sample data' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Start interview' }));
    expect(screen.getByText('Synthetic sample data added. Review it under Sources, then start the interview.')).toBeTruthy();
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
    await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData').mockRejectedValueOnce(offline());
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    const alert = await within(panel()).findByRole('alert');
    expect(alert.textContent).toContain("Can't reach the backend");
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

  it('releases a run whose end was missed on reconnect, and keeps its key', async () => {
    const build = await setup();
    const generate = vi.spyOn(api, 'generateSyntheticData').mockResolvedValue({ run_id: 'r_lost' });
    await openSampleData();
    type(columnsBox(), columnsJson);
    fireEvent.click(generateButton());
    await within(panel()).findByText('Generating CSV…');
    expect(generateButton().disabled).toBe(true);
    act(() => publishWorkspace(build.id, { name: 'ready', data: { build_id: build.id } }));
    await within(panel()).findByText('Reconnected. If the sample data loaded, it shows under Sources.');
    expect(generateButton().disabled).toBe(false);
    expect(choice(/^Upload\/connect data/).disabled).toBe(false);
    fireEvent.click(generateButton());
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
