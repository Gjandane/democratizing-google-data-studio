import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { api } from '../src/api/client';
import { AppServicesProvider, useAppServices } from '../src/features/settings/AppServices';
import { SettingsModal, changedFields } from '../src/features/settings/SettingsModal';
import { TraceModal, formatLatency } from '../src/features/trace/TraceModal';
import { resetMockState, setMockServiceFault, setMockSettings } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function openModal(onSaved = vi.fn()) {
  render(<SettingsModal open onClose={() => {}} onSaved={onSaved} />);
  await screen.findByLabelText('Planner model');
  return onSaved;
}

const saveButton = () => screen.getByRole('button', { name: 'Save settings' }) as HTMLButtonElement;

describe('settings modal', () => {
  it('loads the saved values and keeps Save disabled until something changes', async () => {
    await openModal();
    expect((screen.getByLabelText('Planner model') as HTMLInputElement).value).toBe(fixtures.settings.planner_model);
    expect((screen.getByLabelText('BigQuery dataset') as HTMLInputElement).value).toBe(fixtures.settings.bq_dataset);
    expect(saveButton().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('BigQuery dataset'), { target: { value: 'other' } });
    expect(saveButton().disabled).toBe(false);
    fireEvent.change(screen.getByLabelText('BigQuery dataset'), { target: { value: fixtures.settings.bq_dataset } });
    expect(saveButton().disabled).toBe(true);
  });

  it('saves only the changed fields', async () => {
    const onSaved = await openModal();
    const update = vi.spyOn(api, 'updateSettings');
    fireEvent.change(screen.getByLabelText('BigQuery dataset'), { target: { value: 'dss_prod' } });
    fireEvent.change(screen.getByLabelText('GCS bucket'), { target: { value: 'my-bucket' } });
    fireEvent.click(saveButton());
    await screen.findByText('Settings saved.');
    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith({ bq_dataset: 'dss_prod', gcs_bucket: 'my-bucket' });
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ bq_dataset: 'dss_prod', gcs_bucket: 'my-bucket' }));
    // What was saved is now the baseline: nothing left to save.
    expect(saveButton().disabled).toBe(true);
  });

  it('sends the key only when one was typed, then empties the field and shows Key set', async () => {
    setMockSettings({ google_api_key_set: false });
    await openModal();
    expect(screen.getByText('No key yet')).toBeTruthy();
    expect(screen.queryByText('Key set')).toBeNull();
    const update = vi.spyOn(api, 'updateSettings');
    const field = screen.getByLabelText('Google API key') as HTMLInputElement;
    expect(field.type).toBe('password');
    fireEvent.change(field, { target: { value: 'secret-key' } });
    fireEvent.click(saveButton());
    await screen.findByText('Key set');
    expect(update).toHaveBeenCalledWith({ google_api_key: 'secret-key' });
    expect((screen.getByLabelText('Google API key') as HTMLInputElement).value).toBe('');
    expect(document.body.textContent).not.toContain('secret-key');
  });

  it('shows Key set from google_api_key_set on open', async () => {
    await openModal();
    expect(screen.getByText('Key set')).toBeTruthy();
    expect((screen.getByLabelText('Google API key') as HTMLInputElement).value).toBe('');
  });

  it('says what to do when saving fails', async () => {
    await openModal();
    vi.spyOn(api, 'updateSettings').mockRejectedValue(new Error('boom'));
    fireEvent.change(screen.getByLabelText('Worker model'), { target: { value: 'x' } });
    fireEvent.click(saveButton());
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Couldn't save the settings");
    expect(saveButton().disabled).toBe(false);
  });

  it('shows an error with a retry when the settings fail to load', async () => {
    const get = vi.spyOn(api, 'getSettings').mockRejectedValueOnce(new Error('down'));
    render(<SettingsModal open onClose={() => {}} onSaved={() => {}} />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Couldn't load the settings");
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await screen.findByLabelText('Planner model');
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('computes the update from the differences only', () => {
    const draft = {
      planner_model: fixtures.settings.planner_model,
      worker_model: 'w',
      gcp_project_id: fixtures.settings.gcp_project_id,
      bq_dataset: fixtures.settings.bq_dataset,
      bq_location: fixtures.settings.bq_location,
      gcs_bucket: fixtures.settings.gcs_bucket,
    };
    expect(changedFields(fixtures.settings, draft, '')).toEqual({ worker_model: 'w' });
    expect(changedFields(fixtures.settings, draft, 'k')).toEqual({ worker_model: 'w', google_api_key: 'k' });
  });

  it('traps focus inside and closes on Esc', async () => {
    const onClose = vi.fn();
    render(
      <>
        <button>Outside</button>
        <SettingsModal open onClose={onClose} onSaved={() => {}} />
      </>,
    );
    await screen.findByLabelText('Planner model');
    const dialog = screen.getByRole('dialog', { name: 'Settings' });
    const items = Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input'));
    const first = items[0] as HTMLElement;
    const last = items[items.length - 1] as HTMLElement;
    last.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(first);
    first.focus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

function Probe() {
  const { openSettings } = useAppServices();
  return (
    <>
      <button onClick={() => void api.sendMessage(fixtures.build.id, 'hello').catch(() => {})}>Send</button>
      <button onClick={() => void api.addSource(fixtures.build.id, { kind: 'bigquery', uri: 'p.d.t' }).catch(() => {})}>Add source</button>
      <button onClick={openSettings}>Probe settings</button>
    </>
  );
}

function renderServices() {
  render(
    <MemoryRouter>
      <AppServicesProvider>
        <Probe />
      </AppServicesProvider>
    </MemoryRouter>,
  );
}

describe('service banner', () => {
  it('stays away when the key and project are set', async () => {
    renderServices();
    await waitFor(() => expect(screen.getByText('Send')).toBeTruthy());
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows when the key is missing and opens Settings from its button', async () => {
    setMockSettings({ google_api_key_set: false });
    renderServices();
    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toContain('API key');
    fireEvent.click(within(banner).getByRole('button', { name: 'Open settings' }));
    expect(await screen.findByRole('dialog', { name: 'Settings' })).toBeTruthy();
  });

  it('shows when the project is missing', async () => {
    setMockSettings({ gcp_project_id: '' });
    renderServices();
    expect((await screen.findByRole('alert')).textContent).toContain('GCP project');
  });

  it('shows after a 503 llm_unavailable from any action, and its button opens Settings', async () => {
    renderServices();
    await screen.findByText('Send');
    setMockServiceFault('llm_unavailable');
    fireEvent.click(screen.getByText('Send'));
    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toContain("The planner isn't available");
    fireEvent.click(within(banner).getByRole('button', { name: 'Open settings' }));
    expect(await screen.findByRole('dialog', { name: 'Settings' })).toBeTruthy();
  });

  it('shows after a 503 gcp_not_configured, and saving settings clears it', async () => {
    renderServices();
    await screen.findByText('Add source');
    setMockSettings({ gcp_project_id: '' });
    fireEvent.click(screen.getByText('Add source'));
    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toContain("Google Cloud isn't set up");
    fireEvent.click(within(banner).getByRole('button', { name: 'Open settings' }));
    const dialog = await screen.findByRole('dialog', { name: 'Settings' });
    await within(dialog).findByLabelText('GCP project');
    fireEvent.change(within(dialog).getByLabelText('GCP project'), { target: { value: 'my-project' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save settings' }));
    await within(dialog).findByText('Settings saved.');
    await waitFor(() => expect(screen.queryByText("Google Cloud isn't set up.")).toBeNull());
    expect(screen.queryAllByRole('alert').filter((el) => el.textContent?.includes('Open settings'))).toHaveLength(0);
  });

  it('can be dismissed, and comes back with the next failure', async () => {
    renderServices();
    await screen.findByText('Send');
    setMockServiceFault('llm_unavailable');
    fireEvent.click(screen.getByText('Send'));
    const banner = await screen.findByRole('alert');
    fireEvent.click(within(banner).getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('alert')).toBeNull();
    fireEvent.click(screen.getByText('Send'));
    expect(await screen.findByRole('alert')).toBeTruthy();
  });

  it('leaves other errors alone', async () => {
    renderServices();
    await screen.findByText('Send');
    setMockServiceFault(null);
    vi.spyOn(api, 'getBuild').mockRejectedValue(new Error('x'));
    fireEvent.click(screen.getByText('Send'));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('app wiring', () => {
  it('opens Settings and Trace from the workspace top bar', async () => {
    render(
      <MemoryRouter initialEntries={[`/builds/${fixtures.build.id}`]}>
        <Routes>
          <Route path="*" element={<App />} />
        </Routes>
      </MemoryRouter>,
    );
    const settings = (await screen.findByRole('button', { name: 'Settings' })) as HTMLButtonElement;
    await waitFor(() => expect(settings.disabled).toBe(false));
    settings.focus();
    fireEvent.click(settings);
    expect(await screen.findByRole('dialog', { name: 'Settings' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    // Focus goes back to the button that opened the dialog.
    expect(document.activeElement).toBe(settings);
    fireEvent.click(screen.getByRole('button', { name: 'Trace' }));
    const dialog = await screen.findByRole('dialog', { name: 'Trace' });
    await within(dialog).findByRole('table');
  });
});

describe('trace modal', () => {
  it('lists the runs newest first and totals input and output tokens', async () => {
    render(<TraceModal open onClose={() => {}} />);
    const table = await screen.findByRole('table', { name: 'Model runs' });
    const rows = within(table).getAllByRole('row');
    // Header, two runs, totals.
    expect(rows).toHaveLength(4);
    expect(within(rows[1] as HTMLElement).getByText('plan')).toBeTruthy();
    expect(within(rows[2] as HTMLElement).getByText('interview')).toBeTruthy();
    expect(within(rows[1] as HTMLElement).getByText('14,210')).toBeTruthy();
    expect(within(rows[1] as HTMLElement).getByText('41.2 s')).toBeTruthy();
    const totals = rows[3] as HTMLElement;
    expect(totals.textContent).toContain('Total, 2 runs');
    expect(within(totals).getByText('18,130')).toBeTruthy();
    expect(within(totals).getByText('3,390')).toBeTruthy();
    // Latency and the total row never wrap at 1280.
    for (const cell of [within(rows[1] as HTMLElement).getByText('41.2 s'), within(totals).getByText('Total, 2 runs'), within(totals).getByText(/ s$| min /)]) {
      expect(cell.classList.contains('whitespace-nowrap')).toBe(true);
    }
  });

  it('shows errors, a missing model and updates totals for failed runs', async () => {
    const traces = [
      { ...fixtures.traces[0]!, run_id: 'r_1', status: 'error' as const, error: 'Model timed out', model: null, input_tokens: 1000, output_tokens: 0, latency_ms: 800 },
    ];
    vi.spyOn(api, 'listTraces').mockResolvedValue(traces);
    render(<TraceModal open onClose={() => {}} />);
    const table = await screen.findByRole('table');
    const pill = within(table).getByText('Error');
    // 4.5:1: text color on the soft danger fill, as DoneStage.
    expect(pill.classList.contains('text-text')).toBe(true);
    expect(pill.classList.contains('text-danger')).toBe(false);
    expect(within(table).getByText('Model timed out')).toBeTruthy();
    expect(within(table).getByText('—')).toBeTruthy();
    expect(within(table).getByText('Total, 1 run')).toBeTruthy();
    expect(within(table).getAllByText('800 ms').length).toBeGreaterThan(0);
  });

  it('has an empty state and an error state with retry', async () => {
    const list = vi.spyOn(api, 'listTraces').mockResolvedValueOnce([]);
    const { unmount } = render(<TraceModal open onClose={() => {}} />);
    expect(await screen.findByText('No runs yet')).toBeTruthy();
    unmount();
    list.mockRejectedValueOnce(new Error('down'));
    render(<TraceModal open onClose={() => {}} />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Couldn't load the runs");
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await screen.findByRole('table');
  });

  it('narrows to the open build and back to all builds', async () => {
    const list = vi.spyOn(api, 'listTraces');
    render(<TraceModal open onClose={() => {}} buildId={fixtures.build.id} />);
    await screen.findByRole('table');
    expect(list).toHaveBeenLastCalledWith(fixtures.build.id);
    expect(screen.getByRole('button', { name: 'This build' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'All builds' }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(undefined));
  });

  it('formats latency', () => {
    expect(formatLatency(800)).toBe('800 ms');
    expect(formatLatency(2300)).toBe('2.3 s');
    expect(formatLatency(125000)).toBe('2 min 5 s');
    // Rounds before picking the unit: never "60 s".
    expect(formatLatency(119600)).toBe('2 min 0 s');
    expect(formatLatency(59960)).not.toBe('60.0 s');
    expect(formatLatency(59960)).toBe('1 min 0 s');
    expect(formatLatency(59940)).toBe('59.9 s');
  });
});
