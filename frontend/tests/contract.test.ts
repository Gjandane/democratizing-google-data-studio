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
  isBlueprint,
  isBuild,
  isContext,
  isDesign,
  isOutline,
  isThemePreset,
  isBuildSummary,
  artifactIssues,
  isBuildCost,
  isBriefReview,
  isDesignPages,
  isRunCalls,
  isSettingsCapabilities,
  isStageCall,
  isValidationIssue,
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
import { createMockApi, resetMockState, setMockAssessment, setMockDesignPages, setMockRunFailure } from '../src/mocks/api';
import { openMockBuildEvents } from '../src/mocks/events';
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

// contracts/fixtures/stage-settings/ (api.md 3.0).
const rawStage = import.meta.glob<string>('../../contracts/fixtures/stage-settings/*', { eager: true, query: '?raw', import: 'default' });
const stageFixture: Record<string, string> = Object.fromEntries(
  Object.entries(rawStage).map(([path, body]) => [path.slice(path.lastIndexOf('/') + 1), body]),
);
const stageJson = (name: string): unknown => JSON.parse(stageFixture[name] ?? 'null');

const jsonGuards: Record<string, Guard<unknown>> = {
  'build.json': isBuild,
  'build.done.json': isBuild,
  'builds.json': arrayOf(isBuildSummary),
  'agent_job.json': isJob,
  'blueprint.json': isBlueprint,
  'blueprint.blocked.json': isBlueprint,
  'context.json': isContext,
  'design.json': isDesign,
  'design_presets.json': arrayOf(isThemePreset),
  'outline.json': isOutline,
  'engine_status.json': isEngineStatus,
  'engine_status.local.json': isEngineStatus,
  'error.json': isApiErrorBody,
  'messages.json': arrayOf(isMessage),
  'recipe.json': isRecipe,
  'run_accepted.json': isRunAccepted,
  'session.json': isSession,
  // 'settings.json' is the 2.0 Settings (planner_model, worker_model), kept in the contract until its removal:
  // it has no guard on purpose; the 3.0 guard checks stage-settings/settings.json (below).
  'traces.json': arrayOf(isTrace),
};

const stageGuards: Record<string, Guard<unknown>> = {
  'settings.json': isSettings,
  'capabilities.json': isSettingsCapabilities,
  'design_pages.json': isDesignPages,
  'design_pages.review.json': isDesignPages,
  'design_pages.review.issue.json': isDesignPages,
  'run_calls.json': isRunCalls,
  'build_cost.json': isBuildCost,
  'error.invalid_settings.json': isApiErrorBody,
};

describe('shared fixtures match the contract', () => {
  it('has a check for every fixture file', () => {
    const checked = [...Object.keys(jsonGuards), 'settings.json', 'events.sse', 'events.usage.sse', 'prototype.sample.html', 'prototype.multipage.html'];
    expect(Object.keys(fixture).sort()).toEqual(checked.sort());
  });

  it('has a check for every stage-settings fixture file', () => {
    expect(Object.keys(stageFixture).sort()).toEqual([...Object.keys(stageGuards), 'events.review.sse'].sort());
  });

  it.each(Object.keys(stageGuards))('stage-settings/%s', (name) => {
    expect(problemsOf(stageGuards[name]!, stageJson(name), name)).toEqual([]);
  });

  it('stage-settings/error.invalid_settings.json carries its issues in detail.issues', () => {
    const body = stageJson('error.invalid_settings.json') as { error: { code: string; detail: { issues: unknown } } };
    expect(body.error.code).toBe('invalid_settings');
    expect(problemsOf(arrayOf(isValidationIssue), body.error.detail.issues)).toEqual([]);
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
  it.each(['events.sse', 'events.usage.sse', 'events.review.sse'])('%s: starts with ready, and every event matches its data shape', (file) => {
    const events = parseSse(fixture[file] ?? stageFixture[file] ?? '');
    expect(events[0]?.event).toBe('ready');
    events.forEach(({ event, data }, i) => {
      const problems: string[] = [];
      const parsed = toBuildEvent(event, JSON.parse(data), problems);
      expect(parsed, `event #${i + 1} (${event}): ${problems.join('; ')}`).not.toBeNull();
      names.add(event);
    });
  });

  // 2.0's fixtures stream no assistant message; message.delta and message.done keep their 1.x shapes (checked below).
  // brief.review (3.0) is covered by stage-settings/events.review.sse above.
  it('the event fixtures cover every event but the screencast frame and the message stream', () => {
    const expected = Object.keys(buildEventGuards).filter((name) => !['build.frame', 'message.delta', 'message.done'].includes(name));
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

  it.each([
    ['prototype.sample.html', 1],
    ['prototype.multipage.html', 2],
  ])('%s: one canvas of named page sections, flat data-cid roots with a label and a kind', (file, pages) => {
    const doc = new DOMParser().parseFromString(fixture[file] ?? '', 'text/html');
    const canvas = doc.getElementById('dss-canvas');
    expect(canvas).not.toBeNull();
    const sections = [...canvas!.querySelectorAll<HTMLElement>(':scope > section[data-page]')];
    expect(sections.map((section) => section.dataset.page)).toEqual(Array.from({ length: pages }, (_, i) => String(i + 1)));
    for (const section of sections) expect(section.dataset.pageName).toBeTruthy();
    const elements = [...doc.querySelectorAll<HTMLElement>('[data-cid]')];
    expect(elements.length).toBeGreaterThan(0);
    for (const el of elements) {
      expect(el.closest('section[data-page]'), `${el.dataset.cid} sits in a page section`).not.toBeNull();
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

  it('a Build with the removed ready_for_plan, or with the removed interview and plan stages, fails', () => {
    expect(problemsOf(isBuild, { ...build, ready_for_plan: true })).toEqual(['$.ready_for_plan: not in the contract']);
    for (const stage of ['interview', 'plan']) expect(isBuild({ ...build, stage })).toBe(false);
    expect(problemsOf(isBuild, { ...build, artifacts: { ...(build.artifacts as object), outline: 'approved' } })).toEqual([
      '$.artifacts.outline: expected one of missing | draft | confirmed | stale, got "approved"',
    ]);
    expect(STAGES).toEqual(['connect', 'context', 'outline', 'design', 'blueprint', 'prototype', 'build', 'done']);
  });

  it('staged artifacts: missing, extra and mistyped keys fail at every level', () => {
    const context = json('context.json') as Record<string, unknown>;
    const kpi = (context.kpis as object[])[0]!;
    expect(problemsOf(isContext, { ...context, kpis: [{ ...kpi, measure: { field: 'revenue', agg: 'median' } }] })).toEqual([
      '$.kpis[0].measure.agg: expected one of sum | avg | count | count_distinct | min | max, got "median"',
    ]);
    const { issues: _issues, ...noIssues } = context;
    expect(problemsOf(isContext, noIssues)).toEqual(['$.issues: missing']);
    const outline = json('outline.json') as { sections: Array<{ questions: object[] }> };
    const question = outline.sections[0]!.questions[0]!;
    expect(isOutline({ ...outline, sections: [{ ...outline.sections[0], questions: [{ ...question, origin: 'model' }] }] })).toBe(false);
    const design = json('design.json') as Record<string, unknown>;
    expect(problemsOf(isDesign, { ...design, page_structure: 'tabs' })).toEqual(['$.page_structure: expected one of single | per_section, got "tabs"']);
    expect(problemsOf(isDesign, { ...design, theme: 'dark' })).toEqual(['$.theme: not in the contract']);
    const blueprint = json('blueprint.json') as { rows: Array<Record<string, unknown>> };
    const row = blueprint.rows[1]!;
    expect(isBlueprint({ ...blueprint, rows: [{ ...row, status: 'warning' }] })).toBe(false);
    expect(isBlueprint({ ...blueprint, rows: [{ ...row, page: 1.5 }] })).toBe(false);
    expect(toBuildEvent('artifact.updated', { artifact: 'outline', revision: 3 })).toEqual({ name: 'artifact.updated', data: { artifact: 'outline', revision: 3 } });
    expect(toBuildEvent('artifact.updated', { artifact: 'spec', revision: 3 })).toBeNull();
  });

  it('a missing key, an extra key, a wrong JSON type and a nested mismatch fail', () => {
    const { notes: _dropped, ...missing } = build;
    expect(problemsOf(isBuild, missing)).toEqual(['$.notes: missing']);
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
    expect(toBuildEvent('message.delta', { message_id: 'm_000000000003', text: 'Average order' })).not.toBeNull();
    expect(toBuildEvent('message.done', { message: (json('messages.json') as unknown[])[2] })).not.toBeNull();
    const usage = { run_id: 'r_00000000000b', node: 'blueprint', input_tokens: 10, output_tokens: 2 };
    expect(toBuildEvent('run.usage', usage)).toEqual({ name: 'run.usage', data: usage });
    expect(toBuildEvent('run.usage', { ...usage, output_tokens: '2' })).toBeNull();
    expect(toBuildEvent('run.usage', { run_id: 'r_00000000000b', node: 'blueprint', input_tokens: 10 })).toBeNull();
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
    const error = await httpApi.draftContext('b_3f9a0c12d4e5').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: 'wrong_stage', detail: { stage: 'connect' } });
    expect((error as ApiError).message).toBe('Generate the plan after the interview has started.');
  });

  it('speaks every staged workflow endpoint (api.md 2.0) on relative paths, and checks each response', async () => {
    const accepted = fixture['run_accepted.json'] ?? '';
    const calls: Array<[string, () => Promise<unknown>, string, string, unknown]> = [
      [accepted, () => httpApi.draftContext('b/1', 'Net of discounts.'), 'POST', '/context', { notes: 'Net of discounts.' }],
      [accepted, () => httpApi.draftContext('b/1'), 'POST', '/context', {}],
      [fixture['context.json']!, () => httpApi.getContext('b/1'), 'GET', '/context', undefined],
      [fixture['context.json']!, () => httpApi.updateContext('b/1', fixtures.context), 'PUT', '/context', fixtures.context],
      [accepted, () => httpApi.confirmContext('b/1'), 'POST', '/context/confirm', undefined],
      [fixture['outline.json']!, () => httpApi.getOutline('b/1'), 'GET', '/outline', undefined],
      [accepted, () => httpApi.proposeOutline('b/1'), 'POST', '/outline/propose', undefined],
      [fixture['outline.json']!, () => httpApi.updateOutlineSelection('b/1', [{ id: 'q6', selected: true }]), 'PUT', '/outline/selection', { questions: [{ id: 'q6', selected: true }] }],
      [accepted, () => httpApi.addOutlineQuestions('b/1', null, 'Bulk orders by segment'), 'POST', '/outline/other', { section_id: null, text: 'Bulk orders by segment' }],
      [accepted, () => httpApi.suggestOutlineQuestions('b/1', 's2'), 'POST', '/outline/suggest', { section_id: 's2' }],
      [fixture['build.json']!, () => httpApi.confirmOutline('b/1'), 'POST', '/outline/confirm', undefined],
      [fixture['design_presets.json']!, () => httpApi.listDesignPresets('b/1'), 'GET', '/design/presets', undefined],
      [fixture['design.json']!, () => httpApi.getDesign('b/1'), 'GET', '/design', undefined],
      [fixture['design.json']!, () => httpApi.prefillDesign('b/1'), 'POST', '/design/prefill', undefined],
      [fixture['design.json']!, () => httpApi.updateDesign('b/1', fixtures.design), 'PUT', '/design', fixtures.design],
      [accepted, () => httpApi.confirmDesign('b/1'), 'POST', '/design/confirm', undefined],
      [fixture['blueprint.json']!, () => httpApi.getBlueprint('b/1'), 'GET', '/blueprint', undefined],
      [accepted, () => httpApi.regenerateBlueprint('b/1'), 'POST', '/blueprint/regenerate', undefined],
      [accepted, () => httpApi.acceptBlueprint('b/1'), 'POST', '/blueprint/accept', undefined],
    ];
    for (const [body, call, method, path, sent] of calls) {
      const fetchMock = stubFetch(200, body);
      await expect(call()).resolves.toEqual(JSON.parse(body));
      const [url, init] = fetchMock.mock.calls[0]!;
      expect([init?.method, url]).toEqual([method, `/api/builds/b%2F1${path}`]);
      expect(init?.body === undefined ? undefined : JSON.parse(String(init.body))).toEqual(sent);
    }
    stubFetch(200, 'null');
    await expect(httpApi.getOutline('b/1')).resolves.toBeNull();
    stubFetch(200, JSON.stringify({ ...fixtures.design, theme: 'dark' }));
    await expect(httpApi.getDesign('b/1')).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
    // A 1.x build (no artifacts) fails closed instead of crashing the stepper.
    const { artifacts: _artifacts, notes: _notes, ...legacy } = fixtures.build;
    stubFetch(200, JSON.stringify({ ...legacy, ready_for_plan: true }));
    await expect(httpApi.getBuild('b/1')).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
  });

  it('has no interview, chat-input or plan calls left (api.md 2.0 removed them)', () => {
    for (const name of ['startInterview', 'sendMessage', 'generatePlan']) expect(name in httpApi, name).toBe(false);
    const sources = import.meta.glob<string>('../src/**/*.{ts,tsx}', { eager: true, query: '?raw', import: 'default' });
    expect(Object.keys(sources).length).toBeGreaterThan(20);
    for (const [file, text] of Object.entries(sources)) {
      // `/interview/start`, a `/plan` route or a 'plan' node, a body sent to `/messages` (the old chat input).
      expect(text, file).not.toMatch(/interview\/start|['"`/]plan['"`]|\/messages['"`]\),\s*\{/);
    }
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

describe('mock staged workflow (api.md 2.0)', () => {
  afterEach(() => {
    setMockRunFailure('prototype', undefined);
    resetMockState();
  });

  /** Resolves with the run's run.finished once the mock has played it. */
  function finished(buildId: string, runId: string) {
    return new Promise<{ status: string; error: string | null }>((resolve) => {
      const close = openMockBuildEvents(buildId, {
        onEvent: (event) => {
          if (event.name === 'run.finished' && event.data.run_id === runId) {
            close();
            resolve(event.data);
          }
        },
      });
    });
  }

  it('walks every stage from connect to done, confirming each artifact', async () => {
    const api = createMockApi();
    const { id } = await api.createBuild({ archetype: 'executive', mode: 'data' });
    await expect(api.draftContext(id)).rejects.toMatchObject({ status: 409, code: 'wrong_stage' });
    await api.uploadSources(id, [new File(['a,b'], 'sales.csv', { type: 'text/csv' })]);
    const seen: string[] = [];
    const close = openMockBuildEvents(id, { onEvent: (event) => void (event.name === 'stage.changed' && seen.push(event.data.stage)) });
    const run = async (start: Promise<{ run_id: string }>) => {
      const { run_id } = await start;
      expect((await finished(id, run_id)).status).toBe('ok');
    };

    await run(api.draftContext(id, 'Revenue is net of discounts.'));
    expect(await api.getBuild(id)).toMatchObject({ stage: 'context', notes: 'Revenue is net of discounts.', artifacts: { context: 'draft', outline: 'missing' } });
    expect(problemsOf(isContext, await api.getContext(id))).toEqual([]);
    await run(api.confirmContext(id));
    expect(await api.getBuild(id)).toMatchObject({ stage: 'outline', artifacts: { context: 'confirmed', outline: 'draft' } });
    const outline = (await api.getOutline(id))!;
    expect(outline.sections.flatMap((s) => s.questions).filter((q) => q.selected).every((q) => q.recommended)).toBe(true);
    await run(api.addOutlineQuestions(id, 's2', 'how do bulk and single orders compare by segment'));
    expect((await api.getOutline(id))!.sections[1]!.questions.at(-1)).toMatchObject({ origin: 'other', selected: true, text: 'How do bulk and single orders compare by segment?' });
    expect((await api.confirmOutline(id)).stage).toBe('design');
    expect(await api.getDesign(id)).toMatchObject({ preset_id: 'studio_light', page_structure: 'per_section', source: 'preset', issues: [] });
    await run(api.confirmDesign(id));
    expect(await api.getBuild(id)).toMatchObject({ stage: 'blueprint', artifacts: { design: 'confirmed', blueprint: 'draft' } });
    expect((await api.getBlueprint(id))!.rows.every((row) => row.status === 'ok')).toBe(true);
    await run(api.acceptBlueprint(id));
    expect(await api.getBuild(id)).toMatchObject({
      stage: 'prototype',
      spec_version: 1,
      artifacts: { context: 'confirmed', outline: 'confirmed', design: 'confirmed', blueprint: 'confirmed' },
    });
    await api.runBuild(id);
    await vi.waitFor(async () => expect((await api.getBuild(id)).stage).toBe('done'));
    close();
    expect(seen).toEqual(['context', 'outline', 'design', 'blueprint', 'prototype', 'build', 'done']);
  });

  it('an edit in a later stage drafts that artifact, stales the later ones and moves the stage back', async () => {
    const api = createMockApi();
    const id = fixtures.build.id;
    const updated: string[] = [];
    const close = openMockBuildEvents(id, { onEvent: (event) => void (event.name === 'artifact.updated' && updated.push(`${event.data.artifact}@${event.data.revision}`)) });
    await api.updateOutlineSelection(id, [{ id: 'q6', selected: true }]);
    close();
    expect(updated).toEqual([`outline@${fixtures.outline.revision + 1}`]);
    expect(await api.getBuild(id)).toMatchObject({
      stage: 'outline',
      spec_version: fixtures.build.spec_version,
      artifacts: { context: 'confirmed', outline: 'draft', design: 'stale', blueprint: 'stale' },
    });
    await expect(api.runBuild(id)).rejects.toMatchObject({ code: 'wrong_stage' });
    await expect(api.updateContext(fixtures.buildDone.id, fixtures.context)).rejects.toMatchObject({ status: 409, code: 'wrong_stage' });
  });

  it('confirm refuses open issues with artifact_invalid', async () => {
    const api = createMockApi();
    const id = fixtures.build.id;
    const broken = { ...fixtures.context, kpis: [{ ...fixtures.context.kpis[0]!, measure: { field: 'profit', agg: 'sum' as const } }] };
    const saved = await api.updateContext(id, broken);
    expect(saved.issues).toEqual([{ path: '/kpis/0/measure/field', message: expect.stringContaining('profit') }]);
    await expect(api.confirmContext(id)).rejects.toMatchObject({ status: 409, code: 'artifact_invalid', detail: { issues: saved.issues } });
  });

  it('a failed accept stays in Blueprint with the blueprint unconfirmed', async () => {
    const api = createMockApi();
    const id = fixtures.build.id;
    const regenerate = await api.regenerateBlueprint(id);
    await finished(id, regenerate.run_id);
    setMockRunFailure('prototype', 'Rendering failed: the view dry run timed out.');
    const accept = await api.acceptBlueprint(id);
    expect(await finished(id, accept.run_id)).toMatchObject({ status: 'error', error: 'Rendering failed: the view dry run timed out.' });
    expect(await api.getBuild(id)).toMatchObject({ stage: 'blueprint', spec_version: fixtures.build.spec_version, artifacts: { blueprint: 'draft' } });
  });
});

describe('stage settings and design briefs: the guards reject what api.md 3.0 forbids', () => {
  const settings = stageJson('settings.json') as Record<string, unknown>;
  const calls = stageJson('run_calls.json') as { calls: Array<Record<string, unknown>> } & Record<string, unknown>;
  const call = calls.calls[0]!;
  const pages = stageJson('design_pages.json') as { pages: Array<Record<string, unknown>> } & Record<string, unknown>;
  const reviewPages = stageJson('design_pages.review.json') as { review: Record<string, unknown> } & Record<string, unknown>;

  it('a Settings that still has planner_model or worker_model, or lacks the 3.0 fields, fails', () => {
    expect(problemsOf(isSettings, { ...settings, planner_model: 'gemini-4-argon' })).toEqual(['$.planner_model: not in the contract']);
    expect(problemsOf(isSettings, { ...settings, worker_model: 'gemini-3.8-flash' })).toEqual(['$.worker_model: not in the contract']);
    expect(isSettings(json('settings.json'))).toBe(false);
    const { review_briefs: _dropped, ...missing } = settings;
    expect(problemsOf(isSettings, missing)).toEqual(['$.review_briefs: missing']);
  });

  it('an unknown StageId, a bad thinking level and a missing profile field fail', () => {
    const stages = settings.stages as Record<string, Record<string, unknown>>;
    expect(problemsOf(isSettings, { ...settings, stages: { ...stages, designer: stages.html_no_reference } })).toEqual(['$.stages.designer: not in the contract']);
    expect(problemsOf(isSettings, { ...settings, stages: { ...stages, routine: { ...stages.routine, thinking: 'max' } } })).toEqual([
      '$.stages.routine.thinking: expected one of low | medium | high, got "max"',
    ]);
    const { layout_fallback: _dropped, ...noFallback } = stages.html_no_reference!;
    expect(problemsOf(isSettings, { ...settings, stages: { ...stages, html_no_reference: noFallback } })).toEqual(['$.stages.html_no_reference.layout_fallback: missing']);
    expect(problemsOf(isSettings, { ...settings, stages: { ...stages, interview: { ...stages.interview, input_tokens: 10 } } })).toEqual(['$.stages.interview.input_tokens: not in the contract']);
    expect(isStageCall({ ...call, stage: 'designer' })).toBe(false);
  });

  it('a StageCall with thinking_tokens "0" or a string cost_usd_estimate fails; null means unknown', () => {
    expect(isStageCall(call)).toBe(true);
    expect(problemsOf(isStageCall, { ...call, thinking_tokens: '0' })).toEqual(['$.thinking_tokens: expected an integer']);
    expect(problemsOf(isStageCall, { ...call, cost_usd_estimate: '0.05' })).toEqual(['$.cost_usd_estimate: expected a finite number']);
    expect(isStageCall({ ...call, thinking_tokens: null, cost_usd_estimate: null })).toBe(true);
    expect(isStageCall({ ...call, outcome: 'failed' })).toBe(false);
    expect(isRunCalls({ ...calls, cost_usd_estimate: '0.05' })).toBe(false);
    expect(isRunCalls({ ...calls, settings: null })).toBe(true);
  });

  it('a standard_reason of design_failed fails; a review without revision fails', () => {
    const page = pages.pages[1]!;
    expect(isDesignPages({ ...pages, pages: [{ ...page, standard_reason: 'design_failed' }] })).toBe(false);
    expect(isDesignPages({ ...pages, pages: [{ ...page, standard_reason: 'not_designed' }] })).toBe(true);
    const { revision: _dropped, ...noRevision } = reviewPages.review;
    expect(problemsOf(isBriefReview, noRevision)).toEqual(['$.revision: missing']);
    expect(isDesignPages({ ...reviewPages, review: noRevision })).toBe(false);
    expect(isBriefReview({ ...reviewPages.review, action: 'accept' })).toBe(false);
  });

  it('capabilities, build cost and the brief.review event keep exact shapes', () => {
    const capabilities = stageJson('capabilities.json') as { limits: Record<string, unknown> } & Record<string, unknown>;
    expect(isSettingsCapabilities({ ...capabilities, limits: { ...capabilities.limits, model_timeout_s: [10] } })).toBe(false);
    expect(isSettingsCapabilities({ ...capabilities, models: [{ id: 'x' }] })).toBe(false);
    const cost = stageJson('build_cost.json') as { runs: Array<Record<string, unknown>> } & Record<string, unknown>;
    expect(isBuildCost({ ...cost, runs: [{ ...cost.runs[0], basis: 'estimate' }] })).toBe(false);
    expect(toBuildEvent('brief.review', { review_id: 'br_1', page: 1, pages: 2 })).toEqual({ name: 'brief.review', data: { review_id: 'br_1', page: 1, pages: 2 } });
    expect(toBuildEvent('brief.review', { review_id: 'br_1', page: 1 })).toBeNull();
    expect(toBuildEvent('brief.review', { review_id: 'br_1', page: '1', pages: 2 })).toBeNull();
  });
});

describe('the HTTP client speaks the stage-settings contract (api.md 3.0)', () => {
  afterEach(() => vi.unstubAllGlobals());
  const headers = { 'Content-Type': 'application/json' };
  const stub = (body: string) => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  };
  const review = fixtures.designPagesReview.review!;

  it('reads Settings and capabilities from their exact paths and fails closed on a 2.0 Settings', async () => {
    let fetchMock = stub(stageFixture['settings.json']!);
    await expect(httpApi.getSettings()).resolves.toEqual(stageJson('settings.json'));
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/settings', { method: 'GET' });
    fetchMock = stub(stageFixture['capabilities.json']!);
    await expect(httpApi.getSettingsCapabilities()).resolves.toEqual(stageJson('capabilities.json'));
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/settings/capabilities', { method: 'GET' });
    stub(fixture['settings.json']!);
    await expect(httpApi.getSettings()).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
    const update = { stages: { html_brief: { model: 'gemini-3.8-flash', thinking: 'medium' as const } }, review_briefs: true, google_api_key: 'k' };
    fetchMock = stub(stageFixture['settings.json']!);
    await httpApi.updateSettings(update);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/settings', { method: 'PUT', headers, body: JSON.stringify(update) });
  });

  it('design pages, review save, approve (with revision and sha256), cancel, run calls and build cost', async () => {
    let fetchMock = stub(stageFixture['design_pages.review.json']!);
    await expect(httpApi.getDesignPages('b/one')).resolves.toEqual(stageJson('design_pages.review.json'));
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/builds/b%2Fone/design-pages', { method: 'GET' });

    fetchMock = stub(JSON.stringify(review));
    const save = { review_id: review.review_id, revision: review.revision, brief: review.brief.brief };
    await expect(httpApi.saveBriefReview('b/one', save)).resolves.toEqual(review);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/builds/b%2Fone/briefs/review', { method: 'PUT', headers, body: JSON.stringify(save) });

    fetchMock = stub(fixture['run_accepted.json']!);
    const approval = { review_id: review.review_id, revision: review.revision, sha256: review.brief.sha256 };
    await expect(httpApi.approveBriefReview('b/one', approval)).resolves.toEqual(json('run_accepted.json'));
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/builds/b%2Fone/briefs/review/approve', { method: 'POST', headers, body: JSON.stringify(approval) });

    fetchMock = stub(fixture['build.json']!);
    await expect(httpApi.cancelBriefReview('b/one', review.review_id)).resolves.toEqual(json('build.json'));
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/builds/b%2Fone/briefs/review/cancel', { method: 'POST', headers, body: JSON.stringify({ review_id: review.review_id }) });

    fetchMock = stub(stageFixture['run_calls.json']!);
    await expect(httpApi.getRunCalls('r/1')).resolves.toEqual(stageJson('run_calls.json'));
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/traces/r%2F1/calls', { method: 'GET' });

    fetchMock = stub(stageFixture['build_cost.json']!);
    await expect(httpApi.getBuildCost('b/one')).resolves.toEqual(stageJson('build_cost.json'));
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/builds/b%2Fone/cost', { method: 'GET' });
  });

  it('fails closed on a malformed answer from any of them', async () => {
    stub(JSON.stringify({ ...review, revision: undefined }));
    await expect(httpApi.saveBriefReview('b', { review_id: 'x', revision: 1, brief: review.brief.brief })).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
    stub('{"pages": []}');
    await expect(httpApi.getDesignPages('b')).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
    stub('{"calls": []}');
    await expect(httpApi.getRunCalls('r')).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
    stub('{"runs": []}');
    await expect(httpApi.getBuildCost('b')).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
  });

  it('keeps the invalid_settings issues in the error detail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(stageFixture['error.invalid_settings.json']!, { status: 422, headers: { 'Content-Type': 'application/json' } })));
    const error = (await httpApi.updateSettings({}).catch((reason: unknown) => reason)) as ApiError;
    expect(error).toMatchObject({ status: 422, code: 'invalid_settings' });
    expect(artifactIssues(error)).toEqual([{ path: '/stages/html_brief/output_tokens', message: 'gemini-4-argon allows at most 65536 output tokens.' }]);
  });
});

describe('mock stage settings and brief review (api.md 3.0)', () => {
  const id = fixtures.build.id;
  afterEach(() => resetMockState());

  /** Resolves with the events up to and including the run's run.finished. */
  function playRun(buildId: string, runId: string, seen: Array<{ name: string; data: Record<string, unknown> }> = []) {
    return new Promise<Array<{ name: string; data: Record<string, unknown> }>>((resolve) => {
      if (seen.some((e) => e.name === 'run.finished' && e.data.run_id === runId)) return resolve(seen);
      const close = openMockBuildEvents(buildId, {
        onEvent: (event) => {
          seen.push({ name: event.name, data: event.data as unknown as Record<string, unknown> });
          if (event.name === 'run.finished' && event.data.run_id === runId) {
            close();
            resolve(seen);
          }
        },
      });
    });
  }

  it('serves the fixtures for Settings, capabilities, design pages, run calls and build cost', async () => {
    const api = createMockApi();
    expect(await api.getSettings()).toEqual(fixtures.settings);
    expect(await api.getSettingsCapabilities()).toEqual(fixtures.capabilities);
    expect(await api.getDesignPages(id)).toEqual(fixtures.designPages);
    expect(await api.getRunCalls(fixtures.runCalls.run_id)).toEqual(fixtures.runCalls);
    expect(await api.getBuildCost(id)).toEqual(fixtures.buildCost);
    await expect(api.getRunCalls('r_unknown')).rejects.toMatchObject({ status: 404, code: 'run_not_found' });
    await expect(api.getDesignPages('b_missing')).rejects.toMatchObject({ status: 404, code: 'build_not_found' });
  });

  it('merges a partial stage update and answers 422 invalid_settings with issues for an unknown model or a cap over the model limit', async () => {
    const api = createMockApi();
    const saved = await api.updateSettings({ stages: { html_brief: { thinking: 'medium' } }, review_briefs: true });
    expect(saved.stages.html_brief).toEqual({ ...fixtures.settings.stages.html_brief, thinking: 'medium' });
    expect(saved.stages.routine).toEqual(fixtures.settings.stages.routine);
    expect(saved.review_briefs).toBe(true);
    expect(problemsOf(isSettings, saved)).toEqual([]);
    await expect(api.updateSettings({ stages: { html_brief: { output_tokens: 100000 } } })).rejects.toMatchObject({
      status: 422,
      code: 'invalid_settings',
      detail: { issues: [{ path: '/stages/html_brief/output_tokens', message: expect.stringContaining('65536') }] },
    });
    await expect(api.updateSettings({ fallback_model: 'nope' })).rejects.toMatchObject({ status: 422, detail: { issues: [{ path: '/fallback_model', message: expect.any(String) }] } });
    // Nothing was saved by the refused updates.
    expect((await api.getSettings()).fallback_model).toBe(fixtures.settings.fallback_model);
    expect((await api.getSettings()).stages.html_brief.output_tokens).toBe(fixtures.settings.stages.html_brief.output_tokens);
  });

  it('editing a review bumps the revision, fills issues for a blank treatment and changes the sha256', async () => {
    const api = createMockApi();
    setMockDesignPages(id, fixtures.designPagesReview);
    const review = (await api.getDesignPages(id)).review!;
    const blank = { ...review.brief.brief, slots: review.brief.brief.slots.map((slot, i) => (i === 0 ? { ...slot, treatment: ' ' } : slot)) };
    const saved = await api.saveBriefReview(id, { review_id: review.review_id, revision: review.revision, brief: blank });
    expect(problemsOf(isBriefReview, saved)).toEqual([]);
    expect(saved.revision).toBe(review.revision + 1);
    expect(saved.brief.origin).toBe('edited');
    expect(saved.brief.sha256).not.toBe(review.brief.sha256);
    expect(saved.issues).toEqual([{ path: '/slots/0/treatment', message: 'Write a treatment for Total access.' }]);
    // The next save must carry the new revision.
    await expect(api.saveBriefReview(id, { review_id: review.review_id, revision: review.revision, brief: review.brief.brief })).rejects.toMatchObject({
      status: 409,
      code: 'brief_review_conflict',
      detail: { revision: saved.revision },
    });
    await expect(api.saveBriefReview(id, { review_id: 'br_other', revision: saved.revision, brief: blank })).rejects.toMatchObject({ status: 404, code: 'review_not_found' });
    // Open issues block approval.
    await expect(api.approveBriefReview(id, { review_id: saved.review_id, revision: saved.revision, sha256: saved.brief.sha256 })).rejects.toMatchObject({ status: 409, code: 'artifact_invalid' });
  });

  it('the sha256 follows the whole content: other edits differ, the same edit repeats', async () => {
    const api = createMockApi();
    setMockDesignPages(id, fixtures.designPagesReview);
    const review = (await api.getDesignPages(id)).review!;
    const edit = (text: string) => ({ ...review.brief.brief, slots: review.brief.brief.slots.map((slot, i) => (i === 1 ? { ...slot, treatment: text } : slot)) });
    const first = await api.saveBriefReview(id, { review_id: review.review_id, revision: 1, brief: edit('Card with a thin border.') });
    const second = await api.saveBriefReview(id, { review_id: review.review_id, revision: 2, brief: edit('Card with a thick border.') });
    const again = await api.saveBriefReview(id, { review_id: review.review_id, revision: 3, brief: edit('Card with a thin border.') });
    expect(first.brief.sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(second.brief.sha256).not.toBe(first.brief.sha256);
    expect(again.brief.sha256).toBe(first.brief.sha256);
  });

  it('a build without a spec gets its design pages when the first prototype is published', async () => {
    const api = createMockApi();
    const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
    const empty = await api.getDesignPages(build.id);
    expect(empty).toMatchObject({ version: build.current_version, spec_version: null, pages: [], review: null });
  });

  it('a pending review blocks other mutating routes with brief_review_pending; reads and settings still work', async () => {
    const api = createMockApi();
    setMockDesignPages(id, fixtures.designPagesReview);
    await expect(api.regenerateBlueprint(id)).rejects.toMatchObject({ status: 409, code: 'brief_review_pending', detail: { review_id: fixtures.designPagesReview.review!.review_id } });
    await expect(api.getBuild(id)).resolves.toMatchObject({ id });
    await expect(api.updateSettings({ review_briefs: false })).resolves.toMatchObject({ review_briefs: false });
  });

  it('approve checks revision and sha256, consumes the review, emits run events and repeats with the same run_id', async () => {
    const api = createMockApi();
    setMockDesignPages(id, fixtures.designPagesReview);
    const review = fixtures.designPagesReview.review!;
    const approval = { review_id: review.review_id, revision: review.revision, sha256: review.brief.sha256 };
    await expect(api.approveBriefReview(id, { ...approval, revision: 9 })).rejects.toMatchObject({ status: 409, code: 'brief_review_conflict', detail: { revision: review.revision } });
    await expect(api.approveBriefReview(id, { ...approval, sha256: 'old' })).rejects.toMatchObject({ status: 409, code: 'brief_review_conflict' });
    const seen: Array<{ name: string; data: Record<string, unknown> }> = [];
    const close = openMockBuildEvents(id, { onEvent: (event) => void seen.push({ name: event.name, data: event.data as unknown as Record<string, unknown> }) });
    const accepted = await api.approveBriefReview(id, approval);
    expect(problemsOf(isRunAccepted, accepted)).toEqual([]);
    expect((await api.getDesignPages(id)).review).toBeNull();
    expect(await api.approveBriefReview(id, approval)).toEqual(accepted);
    const events = await playRun(id, accepted.run_id, seen);
    close();
    expect(events.map((e) => e.name)).toEqual(expect.arrayContaining(['run.started', 'run.usage', 'run.finished']));
    expect(events.find((e) => e.name === 'run.started')?.data).toEqual({ run_id: accepted.run_id, node: review.action });
    expect(events.find((e) => e.name === 'run.finished')?.data).toEqual({ run_id: accepted.run_id, node: review.action, status: 'ok', error: null });
    expect((await api.getDesignPages(id)).pages.length).toBeGreaterThan(0);
  });

  it('cancel drops the review, returns the Build and repeats harmlessly', async () => {
    const api = createMockApi();
    setMockDesignPages(id, fixtures.designPagesReview);
    const before = await api.getBuild(id);
    const cancelled = await api.cancelBriefReview(id, fixtures.designPagesReview.review!.review_id);
    expect(problemsOf(isBuild, cancelled)).toEqual([]);
    expect(cancelled.stage).toBe(before.stage);
    expect((await api.getDesignPages(id)).review).toBeNull();
    expect(await api.cancelBriefReview(id, fixtures.designPagesReview.review!.review_id)).toEqual(cancelled);
  });

  it('with review_briefs on, an accepted blueprint pauses with brief.review, finishes ok and leaves the stage at blueprint', async () => {
    const api = createMockApi();
    await api.updateSettings({ review_briefs: true });
    const regenerate = await api.regenerateBlueprint(id);
    await playRun(id, regenerate.run_id);
    const accept = await api.acceptBlueprint(id);
    const events = await playRun(id, accept.run_id);
    const paused = events.find((e) => e.name === 'brief.review');
    expect(paused?.data).toMatchObject({ page: 1, pages: 2 });
    expect(events.at(-1)?.data).toMatchObject({ status: 'ok', error: null });
    expect(events.findIndex((e) => e.name === 'brief.review')).toBeLessThan(events.findIndex((e) => e.name === 'run.finished'));
    expect((await api.getBuild(id)).stage).toBe('blueprint');
    const { review } = await api.getDesignPages(id);
    expect(review).toMatchObject({ review_id: (paused?.data as { review_id: string }).review_id, action: 'prototype', revision: 1 });
  });
});
