// Conformance check for ../contracts/api.md: every shared fixture in ../contracts/fixtures/api/
// passes the guards in src/api/types.ts, and the guards reject what the contract forbids.
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { httpApi } from '../src/api/client';
import { openHttpBuildEvents, useBuildEvents } from '../src/api/events';
import {
  ApiError,
  isAssessment,
  STAGES,
  arrayOf,
  buildEventGuards,
  isApiErrorBody,
  isBuild,
  isBuildSummary,
  isEngineStatus,
  isGenerationRequest,
  isGenerationStatus,
  isGenerator,
  isJob,
  isMessage,
  isProposal,
  isRecipe,
  isReferenceSet,
  isRunAccepted,
  isSession,
  isSettings,
  isSource,
  isSyntheticDataset,
  isTrace,
  problemsOf,
  specFieldErrors,
  SYNTHETIC_LIMIT_BYTES,
  toBuildEvent,
  type Guard,
} from '../src/api/types';
import { createMockApi, resetMockState, setMockAssessment } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';
import { parseSse } from '../src/mocks/sse';
import feasibilityFixture from '../../contracts/fixtures/dashboard-intent/feasibility.json';
import feasibilityAlternatives from '../../contracts/fixtures/dashboard-intent/feasibility.alternatives.json';
import feasibilityPending from '../../contracts/fixtures/dashboard-intent/feasibility.pending.json';
import feasibilityStale from '../../contracts/fixtures/dashboard-intent/feasibility.stale.json';
import referenceFixture from '../../contracts/fixtures/dashboard-intent/reference_set.json';
import syntheticDatasetFixture from '../../contracts/fixtures/synthetic-data/dataset.json';
import syntheticJobFailedFixture from '../../contracts/fixtures/synthetic-data/job.failed.json';
import syntheticJobSucceededFixture from '../../contracts/fixtures/synthetic-data/job.succeeded.json';
import syntheticProposalFixture from '../../contracts/fixtures/synthetic-data/proposal.json';
import syntheticRequestFixture from '../../contracts/fixtures/synthetic-data/request.json';
import syntheticSourceFixture from '../../contracts/fixtures/synthetic-data/source.json';

const raw = import.meta.glob<string>('../../contracts/fixtures/api/*', { eager: true, query: '?raw', import: 'default' });
const fixture: Record<string, string> = Object.fromEntries(
  Object.entries(raw).map(([path, body]) => [path.slice(path.lastIndexOf('/') + 1), body]),
);
const json = (name: string): unknown => JSON.parse(fixture[name] ?? 'null');

const jsonGuards: Record<string, Guard<unknown>> = {
  'build.json': isBuild,
  'build.done.json': isBuild,
  'builds.json': arrayOf(isBuildSummary),
  'agent_job.json': isJob,
  'engine_status.json': isEngineStatus,
  'engine_status.local.json': isEngineStatus,
  'error.json': isApiErrorBody,
  'messages.json': arrayOf(isMessage),
  'recipe.json': isRecipe,
  'run_accepted.json': isRunAccepted,
  'session.json': isSession,
  'settings.json': isSettings,
  'traces.json': arrayOf(isTrace),
};

describe('shared fixtures match the contract', () => {
  it('has a check for every fixture file', () => {
    const checked = [...Object.keys(jsonGuards), 'events.sse', 'events.usage.sse', 'prototype.sample.html'];
    expect(Object.keys(fixture).sort()).toEqual(checked.sort());
  });

  it.each(Object.keys(jsonGuards))('%s', (name) => {
    expect(problemsOf(jsonGuards[name]!, json(name), name)).toEqual([]);
  });

  it.each(['build.json', 'build.done.json'])('every Source in %s', (name) => {
    const { sources } = json(name) as { sources: unknown[] };
    expect(sources.length).toBeGreaterThan(0);
    sources.forEach((source, i) => expect(problemsOf(isSource, source, `${name} sources[${i}]`)).toEqual([]));
  });

  const names = new Set<string>();
  it.each(['events.sse', 'events.usage.sse'])('%s: starts with ready, and every event matches its data shape', (file) => {
    const events = parseSse(fixture[file] ?? '');
    expect(events[0]?.event).toBe('ready');
    events.forEach(({ event, data }, i) => {
      const problems: string[] = [];
      const parsed = toBuildEvent(event, JSON.parse(data), problems);
      expect(parsed, `event #${i + 1} (${event}): ${problems.join('; ')}`).not.toBeNull();
      names.add(event);
    });
  });

  it('the event fixtures cover every event but the stretch screencast frame', () => {
    const expected = Object.keys(buildEventGuards).filter((name) => name !== 'build.frame');
    expect([...names].sort()).toEqual(expected.sort());
  });

  it('events.usage.sse: run.usage totals only grow within a run, and run.finished follows the last one', () => {
    const events = parseSse(fixture['events.usage.sse'] ?? '').map(({ event, data }) => ({ event, data: JSON.parse(data) as Record<string, unknown> }));
    const usage = events.filter((e) => e.event === 'run.usage');
    expect(usage.length).toBeGreaterThan(0);
    for (let i = 1; i < usage.length; i++) {
      expect(usage[i]!.data.input_tokens as number).toBeGreaterThanOrEqual(usage[i - 1]!.data.input_tokens as number);
      expect(usage[i]!.data.output_tokens as number).toBeGreaterThanOrEqual(usage[i - 1]!.data.output_tokens as number);
    }
    const finished = events.findIndex((e) => e.event === 'run.finished');
    expect(finished).toBeGreaterThan(events.lastIndexOf(usage[usage.length - 1]!));
  });

  it('prototype.sample.html: one canvas, flat data-cid roots with a label and a kind', () => {
    const doc = new DOMParser().parseFromString(fixture['prototype.sample.html'] ?? '', 'text/html');
    const canvas = doc.getElementById('dss-canvas');
    expect(canvas?.dataset.page).toBe('1');
    const elements = [...doc.querySelectorAll<HTMLElement>('[data-cid]')];
    expect(elements.length).toBeGreaterThan(0);
    for (const el of elements) {
      expect(el.dataset.label, el.dataset.cid).toBeTruthy();
      expect(['component', 'decoration'], el.dataset.cid).toContain(el.dataset.kind);
      expect(el.parentElement?.closest('[data-cid]') ?? null, `${el.dataset.cid} is nested`).toBeNull();
    }
    const ids = elements.map((el) => el.dataset.cid);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('the guards reject what the contract forbids', () => {
  const build = json('build.json') as Record<string, unknown>;

  it('a copy of build.json with a wrong stage fails', () => {
    const copy = { ...build, stage: 'review' };
    expect(isBuild(copy)).toBe(false);
    expect(problemsOf(isBuild, copy)).toEqual([`$.stage: expected one of ${STAGES.join(' | ')}, got "review"`]);
  });

  it('a BuildSummary and a stage.changed event with a wrong stage fail', () => {
    const [summary] = json('builds.json') as Record<string, unknown>[];
    expect(isBuildSummary({ ...summary, stage: 'shipped' })).toBe(false);
    expect(toBuildEvent('stage.changed', { stage: 'shipped' })).toBeNull();
  });

  it('a missing key, an extra key, a wrong JSON type and a nested mismatch fail', () => {
    const { ready_for_plan: _dropped, ...missing } = build;
    expect(problemsOf(isBuild, missing)).toEqual(['$.ready_for_plan: missing']);
    expect(problemsOf(isBuild, { ...build, owner: 'me' })).toEqual(['$.owner: not in the contract']);
    expect(problemsOf(isBuild, { ...build, spec_version: '2' })).toEqual(['$.spec_version: expected an integer']);
    const sources = [{ ...(build.sources as object[])[0], row_count: 1.5 }];
    expect(problemsOf(isBuild, { ...build, sources })).toEqual(['$.sources[0].row_count: expected an integer']);
  });

  it('engine status: an unknown mode, a missing agent field and a numeric last-seen fail', () => {
    const engine = json('engine_status.json') as Record<string, unknown>;
    expect(problemsOf(isEngineStatus, { ...engine, mode: 'cloud' })).toEqual(['$.mode: expected one of local | agent, got "cloud"']);
    const { agent_connected: _dropped, ...missing } = engine;
    expect(problemsOf(isEngineStatus, missing)).toEqual(['$.agent_connected: missing']);
    expect(problemsOf(isEngineStatus, { ...engine, agent_last_seen: 0 })).toEqual(['$.agent_last_seen: expected a string']);
    expect(isEngineStatus(json('engine_status.local.json'))).toBe(true);
  });

  it('session and job: wrong JSON types fail', () => {
    expect(problemsOf(isSession, { required: 'yes', ok: true })).toEqual(['$.required: expected a boolean']);
    const job = json('agent_job.json') as Record<string, unknown>;
    expect(problemsOf(isJob, { ...job, files: 'recipe.jsonl' })).toEqual(['$.files: expected an array']);
    expect(problemsOf(isJob, { ...job, token: 'x' })).toEqual(['$.token: not in the contract']);
  });

  it('an unknown event name and malformed event data fail', () => {
    expect(toBuildEvent('build.deleted', {})).toBeNull();
    expect(toBuildEvent('message.delta', { message_id: 'm_000000000003' })).toBeNull();
    const usage = { run_id: 'r_00000000000b', node: 'plan', input_tokens: 10, output_tokens: 2 };
    expect(toBuildEvent('run.usage', usage)).toEqual({ name: 'run.usage', data: usage });
    expect(toBuildEvent('run.usage', { ...usage, output_tokens: '2' })).toBeNull();
    expect(toBuildEvent('run.usage', { run_id: 'r_00000000000b', node: 'plan', input_tokens: 10 })).toBeNull();
    expect(toBuildEvent('ready', { build_id: 'b_3f9a0c12d4e5' })).toEqual({ name: 'ready', data: { build_id: 'b_3f9a0c12d4e5' } });
  });
});

describe('references and synthetic sources match the contract', () => {
  it('accepts the shared reference fixture and rejects extra, missing, nested and mode mismatches', () => {
    expect(problemsOf(isReferenceSet, referenceFixture)).toEqual([]);
    expect(isReferenceSet({ ...referenceFixture, owner: 'me' })).toBe(false);
    const { summary: _summary, ...missing } = referenceFixture;
    expect(isReferenceSet(missing)).toBe(false);
    expect(isReferenceSet({ ...referenceFixture, mode: 'copy' })).toBe(false);
    expect(isReferenceSet({ ...referenceFixture, images: [{ ...referenceFixture.images[0], name: 12 }] })).toBe(false);
    expect(isReferenceSet({ ...referenceFixture, images: [{ ...referenceFixture.images[0], extra: true }] })).toBe(false);
    expect(isReferenceSet({ ...referenceFixture, images: [{ id: 'image', name: 'dashboard.png' }] })).toBe(false);
  });

  it('accepts the synthetic source inside a Build and rejects an unknown source kind', () => {
    const build = json('build.json') as Record<string, unknown>;
    expect(isBuild({ ...build, sources: [syntheticSourceFixture] })).toBe(true);
    expect(isBuild({ ...build, sources: [{ ...syntheticSourceFixture, kind: 'invented' }] })).toBe(false);
  });
});

describe('synthetic-data fixtures match the contract (synthetic-data.md 1.1)', () => {
  const files = import.meta.glob('../../contracts/fixtures/synthetic-data/*.json', { eager: true, import: 'default' });
  const cases: Array<[string, unknown, Guard<unknown>, unknown]> = [
    ['proposal.json', syntheticProposalFixture, isProposal, fixtures.syntheticProposal],
    ['request.json', syntheticRequestFixture, isGenerationRequest, fixtures.syntheticRequest],
    ['dataset.json', syntheticDatasetFixture, isSyntheticDataset, fixtures.syntheticDataset],
    ['job.succeeded.json', syntheticJobSucceededFixture, isGenerationStatus, fixtures.syntheticJobSucceeded],
    ['job.failed.json', syntheticJobFailedFixture, isGenerationStatus, fixtures.syntheticJobFailed],
    ['source.json', syntheticSourceFixture, isSource, fixtures.syntheticSource],
  ];

  it('has a check for every shared synthetic-data fixture', () => {
    expect(Object.keys(files).map((path) => path.slice(path.lastIndexOf('/') + 1)).sort()).toEqual(cases.map(([name]) => name).sort());
  });

  it.each(cases)('%s passes its exact guard and src/mocks/fixtures.ts exposes it unchanged', (name, value, guard, exposed) => {
    expect(problemsOf(guard, value, name)).toEqual([]);
    expect(exposed).toEqual(value);
  });

  it('accepts every generator kind of the contract', () => {
    const generators = [
      { kind: 'sequence', start: 1, step: 1, prefix: 'ORD-' },
      { kind: 'integer', min: 1, max: 8 },
      { kind: 'decimal', min: 10, max: 100, decimals: 2 },
      { kind: 'choice', values: ['East', 2, true] },
      { kind: 'boolean', true_probability: 0.25 },
      { kind: 'date', start: '2024-01-01', end: '2024-12-31' },
      { kind: 'product', fields: ['quantity', 'unit_price'], decimals: 2 },
      { kind: 'lookup', field: 'region', mapping: { East: 'Boston', West: 'Denver' } },
    ];
    for (const generator of generators) expect(problemsOf(isGenerator, generator)).toEqual([]);
  });

  it('rejects extra, missing, mistyped and mis-tagged synthetic shapes at every level', () => {
    const proposal = syntheticProposalFixture;
    const spec = proposal.spec;
    const column = spec.columns[0]!;
    const withGenerator = (generator: unknown) => ({ ...proposal, spec: { ...spec, columns: [{ ...column, generator }] } });
    const { assumptions: _assumptions, ...noAssumptions } = proposal;
    const { proposal_id: _proposalId, ...noProposalId } = syntheticRequestFixture;
    const failed = syntheticJobFailedFixture;
    const invalid: Array<[Guard<unknown>, unknown]> = [
      [isProposal, { ...proposal, extra: true }],
      [isProposal, noAssumptions],
      [isProposal, { ...proposal, spec: { ...spec, schema_version: 2 } }],
      [isProposal, { ...proposal, spec: { ...spec, row_count: 10.5 } }],
      [isProposal, { ...proposal, spec: { ...spec, extra: true } }],
      [isProposal, { ...proposal, spec: { ...spec, columns: [{ ...column, type: 'geo' }] } }],
      [isProposal, { ...proposal, spec: { ...spec, columns: [{ ...column, nullable_fraction: '0' }] } }],
      [isProposal, withGenerator({ kind: 'regex', pattern: '.*' })],
      [isProposal, withGenerator({ kind: 'choice', values: [null] })],
      [isProposal, withGenerator({ kind: 'integer', min: 1, max: 8, extra: 1 })],
      [isProposal, withGenerator({ kind: 'integer', min: 1 })],
      [isProposal, withGenerator({ kind: 'lookup', field: 'region', mapping: { East: [1] } })],
      [isGenerationRequest, { ...syntheticRequestFixture, generation_key: 7 }],
      [isGenerationRequest, noProposalId],
      [isSyntheticDataset, { ...syntheticDatasetFixture, synthetic: false }],
      [isSyntheticDataset, { ...syntheticDatasetFixture, bytes: '19784' }],
      [isGenerationStatus, { ...failed, state: 'done' }],
      [isGenerationStatus, { ...failed, error: { code: 'synthetic_load_failed' } }],
      [isGenerationStatus, { ...failed, error: { ...failed.error, extra: true } }],
      [isGenerationStatus, { ...syntheticJobSucceededFixture, retry_ready: 'false' }],
    ];
    for (const [guard, value] of invalid) expect(guard(value), JSON.stringify(value)).toBe(false);
  });
});

describe('the HTTP client speaks the synthetic-data contract', () => {
  afterEach(() => vi.unstubAllGlobals());
  const headers = { 'Content-Type': 'application/json' };

  function stubFetch(status: number, body: string, type = 'application/json') {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(body, { status, headers: { 'Content-Type': type } }));
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('posts the proposal and the exact generation request as JSON to relative paths', async () => {
    const fetchMock = stubFetch(202, fixture['run_accepted.json'] ?? '');
    await expect(httpApi.proposeSyntheticSchema('b/one', 'ref_example')).resolves.toEqual(json('run_accepted.json'));
    await expect(httpApi.generateSyntheticData('b/one', fixtures.syntheticRequest)).resolves.toEqual(json('run_accepted.json'));
    expect(fetchMock.mock.calls).toEqual([
      ['/api/builds/b%2Fone/synthetic-data/proposal', { method: 'POST', headers, body: JSON.stringify({ reference_set_id: 'ref_example' }) }],
      ['/api/builds/b%2Fone/synthetic-data', { method: 'POST', headers, body: JSON.stringify(syntheticRequestFixture) }],
    ]);
  });

  it('reads the proposal or null, and fails closed on a malformed one', async () => {
    const fetchMock = stubFetch(200, JSON.stringify(syntheticProposalFixture));
    await expect(httpApi.getSyntheticProposal('b/one')).resolves.toEqual(syntheticProposalFixture);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/builds/b%2Fone/synthetic-data/proposal', { method: 'GET' });
    stubFetch(200, 'null');
    await expect(httpApi.getSyntheticProposal('b/one')).resolves.toBeNull();
    stubFetch(200, JSON.stringify({ ...syntheticProposalFixture, rows: [] }));
    await expect(httpApi.getSyntheticProposal('b/one')).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
  });

  it('refuses a request over 64 KiB before sending, and maps a server 413 to the same 64 KiB message', async () => {
    const fetchMock = stubFetch(413, '<html>Too large</html>', 'text/html');
    const column = fixtures.syntheticRequest.spec.columns[0]!;
    const big = { ...fixtures.syntheticRequest, spec: { ...fixtures.syntheticRequest.spec, columns: [{ ...column, generator: { kind: 'choice' as const, values: ['x'.repeat(SYNTHETIC_LIMIT_BYTES)] } }] } };
    const local: unknown = await httpApi.generateSyntheticData('b', big).catch((reason: unknown) => reason);
    expect(local).toMatchObject({ status: 413, message: expect.stringContaining('64 KiB') });
    expect(fetchMock).not.toHaveBeenCalled();
    const remote: unknown = await httpApi.generateSyntheticData('b', fixtures.syntheticRequest).catch((reason: unknown) => reason);
    expect(remote).toMatchObject({ status: 413, message: expect.stringContaining('64 KiB') });
    expect((remote as ApiError).message).not.toContain('32 MB');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('keeps invalid_generation_spec field errors from the error detail', async () => {
    const detail = { field: 'columns[1].name', reason: 'must be snake_case' };
    stubFetch(422, JSON.stringify({ error: { code: 'invalid_generation_spec', message: 'The generation spec is invalid', detail } }));
    const error = (await httpApi.generateSyntheticData('b', fixtures.syntheticRequest).catch((reason: unknown) => reason)) as ApiError;
    expect(error).toMatchObject({ status: 422, code: 'invalid_generation_spec' });
    expect(specFieldErrors(error)).toEqual([detail]);
    const listed = new ApiError(422, 'invalid_generation_spec', 'Invalid.', { errors: [{ field: 'spec.seed', reason: 'too big' }, { nope: 1 }] });
    expect(specFieldErrors(listed)).toEqual([{ field: 'seed', reason: 'too big' }]);
  });
});

describe('feasibility assessments match the contract', () => {
  it.each([feasibilityFixture, feasibilityAlternatives, feasibilityPending, feasibilityStale])('accepts shared assessment $id', (value) => {
    expect(problemsOf(isAssessment, value)).toEqual([]);
  });

  it('rejects missing, extra, type and enum errors at every nested level', () => {
    const issue = feasibilityAlternatives.issues[0]!;
    const alternative = issue.alternatives[0]!;
    const { input_digest: _digest, ...missing } = feasibilityFixture;
    const { reason: _reason, ...missingIssue } = issue;
    const { label: _label, ...missingAlternative } = alternative;
    const invalid = [
      missing, { ...feasibilityFixture, extra: true }, { ...feasibilityFixture, state: 'approved' },
      { ...feasibilityFixture, prototype_stale: 'false' }, { ...feasibilityFixture, id: 12 },
      ...[missingIssue, { ...issue, extra: true }, { ...issue, status: 'supported' },
        { ...issue, resolution: 'accepted' }, { ...issue, evidence: [12] },
        { ...issue, alternatives: [missingAlternative] }, { ...issue, alternatives: [{ ...alternative, extra: true }] },
        { ...issue, alternatives: [{ ...alternative, label: 12 }] }].map((value) => ({ ...feasibilityFixture, issues: [value] })),
      { ...feasibilityPending, pending_comments: { comments: [] } },
      { ...feasibilityPending, pending_comments: { ...feasibilityPending.pending_comments, extra: true } },
      { ...feasibilityPending, pending_comments: { id: 'batch', comments: [{ component_id: 'title' }] } },
      { ...feasibilityPending, pending_comments: { id: 'batch', comments: [{ component_id: 12, text: 'Rename' }] } },
      { ...feasibilityPending, pending_comments: { id: 'batch', comments: [{ component_id: 'title', text: 'Rename', extra: true }] } },
    ];
    for (const value of invalid) expect(isAssessment(value), JSON.stringify(value)).toBe(false);
  });
});

describe('the HTTP client speaks the contract' , () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(status: number, body: string, type = 'application/json') {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(body, { status, headers: { 'Content-Type': type } }));
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('gets and decides feasibility with exact paths and explicit choices only', async () => {
    const fetchMock = stubFetch(200, JSON.stringify(feasibilityAlternatives));
    await expect(httpApi.getFeasibility('b/one')).resolves.toEqual(feasibilityAlternatives);
    const decisions = [{ issue_id: 'issue_gps', action: 'drop' as const, alternative_id: null }];
    await httpApi.decideFeasibility('b/one', feasibilityAlternatives.id, decisions);
    expect(fetchMock.mock.calls).toEqual([
      ['/api/builds/b%2Fone/feasibility', { method: 'GET' }],
      ['/api/builds/b%2Fone/feasibility/decisions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ assessment_id: feasibilityAlternatives.id, decisions }) }],
    ]);
  });

  it('checks feasibility with an empty POST and no automatic follow-up work', async () => {
    const fetchMock = stubFetch(202, fixture['run_accepted.json'] ?? '');
    await expect(httpApi.checkFeasibility('b/one')).resolves.toEqual(json('run_accepted.json'));
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/builds/b%2Fone/feasibility/check', { method: 'POST' });
  });

  it('fails closed on malformed GET and decision assessment responses', async () => {
    stubFetch(200, JSON.stringify({ ...feasibilityFixture, unexpected: true }));
    await expect(httpApi.getFeasibility('build')).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
    await expect(httpApi.decideFeasibility('build', 'assessment', [])).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
  });

  it('uploads reference files, mode and instructions as one multipart request', async () => {
    const fetchMock = stubFetch(202, fixture['run_accepted.json'] ?? '');
    const files = [new File(['image one'], 'one.png', { type: 'image/png' }), new File(['image two'], 'two.jpg', { type: 'image/jpeg' })];
    await httpApi.uploadReferences('b_3f9a0c12d4e5', files, 'style', 'Keep the blue palette.');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/builds/b_3f9a0c12d4e5/reference-images');
    expect(init?.method).toBe('POST');
    expect(init?.body).toBeInstanceOf(FormData);
    const form = init?.body as FormData;
    expect(form.getAll('files')).toEqual(files);
    expect(form.get('mode')).toBe('style');
    expect(form.get('instructions')).toBe('Keep the blue palette.');
    expect([...form.keys()].sort()).toEqual(['files', 'files', 'instructions', 'mode']);
  });

  it('deletes references and accepts the empty 204 response', async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(httpApi.deleteReferences('b_3f9a0c12d4e5')).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/builds/b_3f9a0c12d4e5/reference-images', expect.objectContaining({ method: 'DELETE' }));
  });

  it('rejects a saved reference response outside the contract', async () => {
    stubFetch(200, JSON.stringify({ ...referenceFixture, mode: 'unknown' }));
    await expect(httpApi.getReferences('b_3f9a0c12d4e5')).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
  });

  it('maps an HTML 413 to reference upload limits', async () => {
    stubFetch(413, '<html>Too large</html>', 'text/html');
    const file = new File(['png'], 'dashboard.png', { type: 'image/png' });
    const error: unknown = await httpApi.uploadReferences('b_3f9a0c12d4e5', [file], 'recreate', '').catch((reason: unknown) => reason);
    expect(error).toMatchObject({ status: 413 });
    expect((error as ApiError).message).toContain('5 MiB each and 15 MiB total');
    expect((error as ApiError).message).not.toContain('32');
    expect((error as ApiError).message).not.toContain('CSV');
  });

  it('maps a server 422 to reference-specific guidance', async () => {
    stubFetch(422, JSON.stringify({ error: { code: 'invalid_source', message: 'Invalid source.' } }));
    const file = new File(['png'], 'dashboard.png', { type: 'image/png' });
    await expect(httpApi.uploadReferences('b_3f9a0c12d4e5', [file], 'recreate', '')).rejects.toMatchObject({
      status: 422,
      message: expect.stringContaining('reference images'),
    });
  });

  it('posts JSON to the relative /api path', async () => {
    const fetchMock = stubFetch(201, fixture['build.json'] ?? '');
    const build = await httpApi.createBuild({ archetype: 'executive', mode: 'data' });
    expect(build.id).toBe('b_3f9a0c12d4e5');
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/builds');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ archetype: 'executive', mode: 'data' });
  });

  it('turns error.json into an ApiError with its code, message and detail', async () => {
    stubFetch(409, fixture['error.json'] ?? '');
    const error = await httpApi.generatePlan('b_3f9a0c12d4e5').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: 'wrong_stage', detail: { stage: 'connect' } });
    expect((error as ApiError).message).toBe('Generate the plan after the interview has started.');
  });

  it('reports an unreachable backend (empty 502 from the proxy) as network_error', async () => {
    stubFetch(502, '', 'text/plain');
    await expect(httpApi.listBuilds()).rejects.toMatchObject({ code: 'network_error' });
  });
});

describe('the event stream speaks the contract', () => {
  class FakeEventSource {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSED = 2;
    static instances: FakeEventSource[] = [];
    readonly url: string;
    readyState = FakeEventSource.CONNECTING;
    private listeners = new Map<string, Array<(event: Event) => void>>();

    constructor(url: string) {
      this.url = url;
      FakeEventSource.instances.push(this);
    }
    addEventListener(name: string, listener: (event: Event) => void) {
      this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
    }
    close() {
      this.readyState = FakeEventSource.CLOSED;
    }
    send(name: string, data: string) {
      this.readyState = FakeEventSource.OPEN;
      for (const listener of this.listeners.get(name) ?? []) listener(new MessageEvent(name, { data }));
    }
    drop(readyState: number) {
      this.readyState = readyState;
      for (const listener of this.listeners.get('error') ?? []) listener(new Event('error'));
    }
  }

  afterEach(() => {
    FakeEventSource.instances = [];
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('delivers typed events, drops malformed ones, and reopens with a new ready after EventSource gives up', () => {
    vi.useFakeTimers();
    vi.stubGlobal('EventSource', FakeEventSource);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const received: string[] = [];
    const ready = JSON.stringify({ build_id: 'b_3f9a0c12d4e5' });

    const { result, unmount } = renderHook(() =>
      useBuildEvents('b_3f9a0c12d4e5', (event) => received.push(event.name), openHttpBuildEvents),
    );
    const first = FakeEventSource.instances[0]!;
    expect(first.url).toBe('/api/builds/b_3f9a0c12d4e5/events');
    expect(result.current).toBe('connecting');

    act(() => first.send('ready', ready));
    expect(result.current).toBe('open');
    act(() => first.send('message.delta', JSON.stringify({ message_id: 'm_000000000003' })));
    act(() => first.send('stage.changed', 'not json'));
    expect(received).toEqual(['ready']);
    expect(warn).toHaveBeenCalledTimes(2);

    // A drop EventSource retries itself: no new stream.
    act(() => first.drop(FakeEventSource.CONNECTING));
    expect(result.current).toBe('connecting');
    expect(FakeEventSource.instances).toHaveLength(1);

    // A drop it gives up on (non-200 answer): closed, then reopened after the backoff.
    act(() => first.drop(FakeEventSource.CLOSED));
    act(() => vi.advanceTimersByTime(999));
    expect(FakeEventSource.instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(1));
    const second = FakeEventSource.instances[1]!;
    act(() => second.send('ready', ready));
    expect(result.current).toBe('open');
    expect(received).toEqual(['ready', 'ready']);

    unmount();
    expect(second.readyState).toBe(FakeEventSource.CLOSED);
  });
});


describe('mock feasibility decisions', () => {
  afterEach(() => resetMockState());

  it('keeps new builds unchecked and fixture builds ready', async () => {
    const api = createMockApi();
    expect((await api.getFeasibility(fixtures.build.id)).state).toBe('ready');
    const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
    expect(await api.getFeasibility(build.id)).toEqual({ id: null, state: 'unchecked', input_digest: null, prototype_stale: false, issues: [], pending_comments: null });
  });

  it('rejects stale or invalid decisions atomically and resolves only explicit choices', async () => {
    const api = createMockApi();
    const id = fixtures.build.id;
    setMockAssessment(id, fixtures.feasibilityAlternatives);
    const original = await api.getBuild(id);
    await expect(api.decideFeasibility(id, 'old', [{ issue_id: 'issue_gps', action: 'drop', alternative_id: null }])).rejects.toMatchObject({ status: 409, code: 'feasibility_stale' });
    await expect(api.decideFeasibility(id, fixtures.feasibilityAlternatives.id!, [
      { issue_id: 'issue_gps', action: 'drop', alternative_id: null },
      { issue_id: 'issue_revenue', action: 'accept_alternative', alternative_id: 'unoffered' },
    ])).rejects.toMatchObject({ status: 422 });
    expect(await api.getFeasibility(id)).toEqual(fixtures.feasibilityAlternatives);
    const partial = await api.decideFeasibility(id, fixtures.feasibilityAlternatives.id!, [{ issue_id: 'issue_gps', action: 'accept_alternative', alternative_id: 'alt_region_map' }]);
    expect(partial.state).toBe('blocked');
    expect(partial.id).not.toBe(fixtures.feasibilityAlternatives.id);
    const ready = await api.decideFeasibility(id, partial.id!, [{ issue_id: 'issue_revenue', action: 'drop', alternative_id: null }]);
    expect(ready.state).toBe('ready');
    expect(ready.issues.map((issue) => issue.resolution)).toEqual(['accepted_alternative', 'dropped']);
    expect(await api.getBuild(id)).toEqual(original);
  });
});
