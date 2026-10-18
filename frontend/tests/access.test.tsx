import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { api, httpApi } from '../src/api/client';
import { MOCK_ACCESS_CODE, resetMockState, setMockSession } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

function renderApp(path = '/') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<App />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** Spies every client call; returns the names of the calls made so far. */
function spyAll(): () => string[] {
  const spies = (Object.keys(api) as Array<keyof typeof api>).map((name) => [name, vi.spyOn(api, name)] as const);
  return () => spies.filter(([, spy]) => spy.mock.calls.length > 0).map(([name]) => name);
}

const codeInput = () => screen.getByLabelText('Access code') as HTMLInputElement;
const enter = (code: string) => {
  fireEvent.change(codeInput(), { target: { value: code } });
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
};
const historyTitle = fixtures.builds[0]!.title;

describe('access-code gate', () => {
  it('shows the gate and makes no other /api call while the session is not valid', async () => {
    setMockSession({ required: true, ok: false });
    const called = spyAll();
    renderApp();
    expect(await screen.findByRole('heading', { name: 'Enter the access code' })).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(called()).toEqual(['getSession']);
    expect(screen.queryByRole('heading', { name: 'Dashboards' })).toBeNull();
  });

  it('a wrong code shows "That code didn\'t work" (401 access_denied) and keeps the gate', async () => {
    setMockSession({ required: true, ok: false });
    const create = vi.spyOn(api, 'createSession');
    renderApp();
    await screen.findByLabelText('Access code');
    enter('not-the-code');
    expect((await screen.findAllByText(/That code didn't work/)).length).toBeGreaterThan(0);
    await expect(create.mock.results[0]!.value).rejects.toMatchObject({ status: 401, code: 'access_denied' });
    expect(codeInput().getAttribute('aria-invalid')).toBe('true');
    expect(screen.queryByRole('heading', { name: 'Dashboards' })).toBeNull();
  });

  it('the right code loads History, and the code is kept nowhere', async () => {
    setMockSession({ required: true, ok: false });
    const log = vi.spyOn(console, 'log');
    const warn = vi.spyOn(console, 'warn');
    const create = vi.spyOn(api, 'createSession');
    renderApp();
    await screen.findByLabelText('Access code');
    enter(MOCK_ACCESS_CODE);
    expect(await screen.findByRole('heading', { name: 'Dashboards' })).toBeTruthy();
    expect(await screen.findByText(historyTitle)).toBeTruthy();
    expect(create).toHaveBeenCalledWith(MOCK_ACCESS_CODE);
    const stored = [...Object.values({ ...localStorage }), ...Object.values({ ...sessionStorage })].join(' ');
    expect(stored).not.toContain(MOCK_ACCESS_CODE);
    expect(window.location.href).not.toContain(MOCK_ACCESS_CODE);
    expect(document.cookie).not.toContain(MOCK_ACCESS_CODE);
    expect(JSON.stringify([...log.mock.calls, ...warn.mock.calls])).not.toContain(MOCK_ACCESS_CODE);
  });

  it('returns to the gate on a later 401 access_required', async () => {
    renderApp();
    await screen.findByText(historyTitle);
    setMockSession({ required: true, ok: false });
    await act(async () => {
      await api.listBuilds().catch(() => {});
    });
    expect(await screen.findByRole('heading', { name: 'Enter the access code' })).toBeTruthy();
    expect(screen.getByText('Your session ended. Enter the code again to continue.')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Dashboards' })).toBeNull();
    enter(MOCK_ACCESS_CODE);
    expect(await screen.findByText(historyTitle)).toBeTruthy();
  });

  it('shows no gate when no code is required', async () => {
    setMockSession({ required: false, ok: true });
    renderApp();
    expect(await screen.findByText(historyTitle)).toBeTruthy();
    expect(screen.queryByLabelText('Access code')).toBeNull();
  });

  it('shows a retry when the session check fails', async () => {
    vi.spyOn(api, 'getSession').mockRejectedValueOnce(new Error('offline'));
    renderApp();
    expect((await screen.findByRole('alert')).textContent).toContain("Couldn't open the app");
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText(historyTitle)).toBeTruthy();
  });
});

describe('access over HTTP', () => {
  function stubFetch(status: number, body: string, type = 'application/json') {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(body, { status, headers: { 'Content-Type': type } }));
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('reads the session and posts the code to the relative /api/session only', async () => {
    const fetchMock = stubFetch(200, JSON.stringify(fixtures.session));
    expect(await httpApi.getSession()).toEqual(fixtures.session);
    await httpApi.createSession(MOCK_ACCESS_CODE);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(['/api/session', '/api/session']);
    const [, init] = fetchMock.mock.calls[1]!;
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ code: MOCK_ACCESS_CODE });
  });

  it('maps 401 access_denied and access_required to their codes', async () => {
    stubFetch(401, JSON.stringify({ error: { code: 'access_denied', message: 'Wrong code.', detail: {} } }));
    await expect(httpApi.createSession('nope')).rejects.toMatchObject({ status: 401, code: 'access_denied' });
    stubFetch(401, JSON.stringify({ error: { code: 'access_required', message: 'Enter the code.', detail: {} } }));
    await expect(httpApi.listBuilds()).rejects.toMatchObject({ status: 401, code: 'access_required' });
  });

});
