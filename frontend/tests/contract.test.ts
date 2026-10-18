// Conformance check for ../contracts/api.md: every shared fixture in ../contracts/fixtures/api/
// passes the guards in src/api/types.ts, and the guards reject what the contract forbids.
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { httpApi } from '../src/api/client';
import { openHttpBuildEvents, useBuildEvents } from '../src/api/events';
import {
  ApiError,
  STAGES,
  arrayOf,
  buildEventGuards,
  isApiErrorBody,
  isBuild,
  isBuildSummary,
  isEngineStatus,
  isJob,
  isMessage,
  isRecipe,
  isRunAccepted,
  isSession,
  isSettings,
  isSource,
  isTrace,
  problemsOf,
  toBuildEvent,
  type Guard,
} from '../src/api/types';
import { parseSse } from '../src/mocks/sse';

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
    const checked = [...Object.keys(jsonGuards), 'events.sse', 'prototype.sample.html'];
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

  it('events.sse: starts with ready, and every event matches its data shape', () => {
    const events = parseSse(fixture['events.sse'] ?? '');
    expect(events[0]?.event).toBe('ready');
    const names = new Set<string>();
    events.forEach(({ event, data }, i) => {
      const problems: string[] = [];
      const parsed = toBuildEvent(event, JSON.parse(data), problems);
      expect(parsed, `event #${i + 1} (${event}): ${problems.join('; ')}`).not.toBeNull();
      names.add(event);
    });
    // Every event of the contract but the stretch screencast frame appears in the fixture.
    const expected = Object.keys(buildEventGuards).filter((name) => name !== 'build.frame');
    expect([...names].sort()).toEqual(expected.sort());
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
    expect(toBuildEvent('ready', { build_id: 'b_3f9a0c12d4e5' })).toEqual({ name: 'ready', data: { build_id: 'b_3f9a0c12d4e5' } });
  });
});

describe('the HTTP client speaks the contract', () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(status: number, body: string, type = 'application/json') {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(body, { status, headers: { 'Content-Type': type } }));
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

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
