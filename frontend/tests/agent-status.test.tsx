import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, httpApi } from '../src/api/client';
import type { OpenBuildEvents } from '../src/api/events';
import { UPLOAD_LIMIT_BYTES, type Build } from '../src/api/types';
import { SettingsModal } from '../src/features/settings/SettingsModal';
import { BuildStage } from '../src/features/workspace/build/BuildStage';
import { agentCommand } from '../src/features/workspace/build/EnginePanel';
import { useBuildStream } from '../src/features/workspace/chat/useBuildStream';
import { ConnectStage } from '../src/features/workspace/connect/ConnectStage';
import { MOCK_ACCESS_CODE, resetMockState, setMockEngine } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const noStream: OpenBuildEvents = () => () => {};

function BuildHolder({ initial }: { initial: Build }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, noStream);
  return <BuildStage build={build} run={chat.buildRun} />;
}

const buildButton = () => screen.getByRole('button', { name: 'Build in Data Studio' }) as HTMLButtonElement;

/** Renders the Build stage, waits for `ready` in the engine panel, and generates the recipe. */
async function renderBuild(ready: string | RegExp) {
  render(<BuildHolder initial={await api.getBuild(fixtures.build.id)} />);
  await screen.findByText(ready);
  fireEvent.click(screen.getByRole('button', { name: 'Generate recipe' }));
  await screen.findByRole('list', { name: 'Recipe' });
}

const agent = fixtures.engineStatus;

describe('build agent status (agent mode)', () => {
  it('offline: the panel shows the copyable agent command with this origin, and Build is off', async () => {
    setMockEngine({ ...agent, agent_connected: false });
    const writeText = vi.fn(async (_text: string) => {});
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    await renderBuild('Build agent offline');

    const command = `uv run --project backend dss-agent --server ${window.location.origin}`;
    expect(agentCommand(window.location.origin)).toBe(command);
    const code = screen.getByText(command);
    expect(code.tagName).toBe('CODE');
    expect(code.textContent).not.toContain(MOCK_ACCESS_CODE);
    expect(code.textContent).not.toMatch(/token|code=/i);
    expect(buildButton().disabled).toBe(true);
    expect(screen.getByText('Start the build agent to build.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Sign in to Google' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    await screen.findByRole('button', { name: 'Copied' });
    expect(writeText).toHaveBeenCalledWith(command);
  });

  it('connected but signed out: tells the user to run dsengine login on the agent, no sign-in button', async () => {
    setMockEngine({ ...agent, signed_in: false });
    const login = vi.spyOn(api, 'engineLogin');
    await renderBuild('Build agent connected');
    expect(screen.getByText('Not signed in to Google')).toBeTruthy();
    const hint = screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === "Run dsengine login on the agent's machine.");
    expect(hint.querySelector('code')?.textContent).toBe('dsengine login');
    expect(screen.queryByRole('button', { name: 'Sign in to Google' })).toBeNull();
    expect(buildButton().disabled).toBe(true);
    expect(login).not.toHaveBeenCalled();
  });

  it('connected and signed in: Build is on', async () => {
    setMockEngine(agent);
    await renderBuild('Build agent connected');
    expect(screen.getByText('Signed in to Google')).toBeTruthy();
    await waitFor(() => expect(buildButton().disabled).toBe(false));
  });

  it('424 agent_offline from POST /run shows the offline panel', async () => {
    setMockEngine(agent);
    const run = vi.spyOn(api, 'runBuild');
    await renderBuild('Build agent connected');
    await waitFor(() => expect(buildButton().disabled).toBe(false));
    // The agent stops between the status check and the click.
    setMockEngine({ agent_connected: false });
    fireEvent.click(buildButton());
    await screen.findByText('Build agent offline');
    await expect(run.mock.results[0]!.value).rejects.toMatchObject({ status: 424, code: 'agent_offline' });
    expect(screen.getByText(agentCommand(window.location.origin))).toBeTruthy();
    expect(buildButton().disabled).toBe(true);
  });

  it('local mode still shows the sign-in button', async () => {
    setMockEngine({ signed_in: false });
    await renderBuild('Not signed in to Google');
    expect(screen.getByRole('heading', { name: 'Data Studio engine' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sign in to Google' })).toBeTruthy();
    expect(screen.queryByText(/Build agent/)).toBeNull();
    expect(screen.getByText('Sign in to Google to build.')).toBeTruthy();
  });
});

describe('settings locked by the deployment', () => {
  it('403 settings_locked marks the API key and GCP fields as fixed; the models stay editable', async () => {
    setMockEngine(agent);
    const update = vi.spyOn(api, 'updateSettings');
    render(<SettingsModal open onClose={() => {}} onSaved={() => {}} />);
    const project = (await screen.findByLabelText('GCP project')) as HTMLInputElement;
    fireEvent.change(project, { target: { value: 'other-project' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await screen.findByText('The hosted app fixes the API key and Google Cloud settings. You can still change the models.');
    await expect(update.mock.results[0]!.value).rejects.toMatchObject({ status: 403, code: 'settings_locked' });

    for (const label of ['GCP project', 'BigQuery dataset', 'BigQuery location', 'GCS bucket', 'Google API key']) {
      const input = screen.getByLabelText(label) as HTMLInputElement;
      expect(input.disabled, label).toBe(true);
    }
    expect(project.value).toBe(fixtures.settings.gcp_project_id);
    expect(screen.getAllByText('Fixed by the deployment.').length).toBe(5);
    const planner = screen.getByLabelText('Planner model') as HTMLInputElement;
    expect(planner.disabled).toBe(false);

    fireEvent.change(planner, { target: { value: 'gemini-next' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await screen.findByText('Settings saved.');
    expect(update).toHaveBeenLastCalledWith({ planner_model: 'gemini-next' });
  });
});

describe('32 MB upload limit', () => {
  const big = () => {
    const file = new File(['a,b\n1,2'], 'huge.csv', { type: 'text/csv' });
    Object.defineProperty(file, 'size', { value: UPLOAD_LIMIT_BYTES + 1 });
    return file;
  };

  it('refuses a file over 32 MB before anything is sent', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(httpApi.uploadSources('b_3f9a0c12d4e5', [big()])).rejects.toMatchObject({
      status: 413,
      message: "Files over 32 MB can't be uploaded to the hosted app.",
    });
    await expect(httpApi.uploadStyleImages('b_3f9a0c12d4e5', [big()])).rejects.toMatchObject({ status: 413 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('maps any 413 (an HTML page from Cloud Run) to the 32 MB message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html><body>413 Request Entity Too Large</body></html>', { status: 413, headers: { 'Content-Type': 'text/html' } })));
    const small = new File(['a,b\n1,2'], 'small.csv', { type: 'text/csv' });
    await expect(httpApi.uploadSources('b_3f9a0c12d4e5', [small])).rejects.toMatchObject({
      status: 413,
      code: 'payload_too_large',
      message: "Files over 32 MB can't be uploaded to the hosted app.",
    });
  });

  it('Connect shows the 32 MB message and adds nothing', async () => {
    const build = await api.createBuild({ archetype: 'executive', mode: 'data' });
    function Holder() {
      const [current, setCurrent] = useState(build);
      return <ConnectStage build={current} onBuildChange={setCurrent} />;
    }
    render(<Holder />);
    fireEvent.drop(screen.getByRole('region', { name: 'Upload CSV files' }), { dataTransfer: { files: [big()] } });
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Files over 32 MB can't be uploaded to the hosted app.");
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
