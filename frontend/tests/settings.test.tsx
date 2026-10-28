import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { api } from '../src/api/client';
import { ApiError, type SettingsCapabilities, type StageId, type ThinkingLevel } from '../src/api/types';
import { AppServicesProvider, useAppServices } from '../src/features/settings/AppServices';
import { SettingsModal, changedFields } from '../src/features/settings/SettingsModal';
import { TraceModal, formatLatency } from '../src/features/trace/TraceModal';
import { resetMockState, setMockServiceFault, setMockSettings } from '../src/mocks/api';
import { clone, fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Opens Settings on the Google Cloud tab. */
async function openModal(onSaved = vi.fn()) {
  render(<SettingsModal open onClose={() => {}} onSaved={onSaved} />);
  fireEvent.click(await screen.findByRole('tab', { name: 'Google Cloud' }));
  await screen.findByLabelText('GCP project');
  return onSaved;
}

const saveButton = () => screen.getByRole('button', { name: 'Save settings' }) as HTMLButtonElement;

describe('settings modal', () => {
  it('loads the saved values and keeps Save disabled until something changes', async () => {
    await openModal();
    expect((screen.getByLabelText('GCP project') as HTMLInputElement).value).toBe(fixtures.settings.gcp_project_id);
    // The model profiles live on the Models tab: no planner or worker inputs remain.
    expect(screen.queryByLabelText('Planner model')).toBeNull();
    expect(screen.queryByLabelText('Worker model')).toBeNull();
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
    fireEvent.change(screen.getByLabelText('GCS bucket'), { target: { value: 'x' } });
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
    await screen.findByRole('list', { name: 'Stages' });
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('computes the update from the differences only', () => {
    const draft = {
      stages: fixtures.settings.stages,
      fallback_model: fixtures.settings.fallback_model,
      review_briefs: fixtures.settings.review_briefs,
      gcp_project_id: fixtures.settings.gcp_project_id,
      bq_dataset: fixtures.settings.bq_dataset,
      bq_location: fixtures.settings.bq_location,
      gcs_bucket: 'w',
    };
    expect(changedFields(fixtures.settings, draft, '')).toEqual({ gcs_bucket: 'w' });
    expect(changedFields(fixtures.settings, draft, 'k')).toEqual({ gcs_bucket: 'w', google_api_key: 'k' });
    // Deep per stage and field.
    const stages = { ...draft.stages, html_brief: { ...draft.stages.html_brief, output_tokens: 40000 } };
    expect(changedFields(fixtures.settings, { ...draft, stages, gcs_bucket: '' }, '')).toEqual({ stages: { html_brief: { output_tokens: 40000 } } });
  });

  it('traps focus inside and closes on Esc', async () => {
    const onClose = vi.fn();
    render(
      <>
        <button>Outside</button>
        <SettingsModal open onClose={onClose} onSaved={() => {}} />
      </>,
    );
    await screen.findByRole('list', { name: 'Stages' });
    const dialog = screen.getByRole('dialog', { name: 'Settings' });
    // The inactive tab is out of the Tab order (roving tabindex).
    const items = Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input, select')).filter((el) => el.getAttribute('tabindex') !== '-1');
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

// ---------- Models tab (docs/stage-settings-ui.md, Settings) ----------

const caps = fixtures.capabilities;
const flash = caps.models.find((m) => m.id === 'gemini-3.8-flash')!;
const STAGE_NAMES: Array<[StageId, string]> = [
  ['interview', 'Interview'],
  ['reference_interpretation', 'Reference interpretation'],
  ['native_planning', 'Native chart planning'],
  ['html_brief', 'HTML brief'],
  ['reference_html', 'HTML with a reference'],
  ['html_no_reference', 'HTML without a reference'],
  ['routine', 'Other model work (routine)'],
];
const nameOf = (stage: StageId) => STAGE_NAMES.find(([id]) => id === stage)![1];
const usd = (n: number) => `$${n.toFixed(2)}`;

async function openModels(props: Partial<Parameters<typeof SettingsModal>[0]> = {}) {
  render(<SettingsModal open onClose={() => {}} onSaved={() => {}} {...props} />);
  return screen.findByRole('list', { name: 'Stages' });
}
const rowButton = (stage: StageId) => screen.getByRole('button', { name: new RegExp(`^${nameOf(stage).replace(/[()]/g, '\\$&')} `) });
/** Expands a stage row (if needed) and returns its fields' region. */
function expand(stage: StageId): HTMLElement {
  const button = rowButton(stage);
  if (button.getAttribute('aria-expanded') !== 'true') fireEvent.click(button);
  return screen.getByRole('region', { name: nameOf(stage) });
}
const field = (region: HTMLElement, label: string) => within(region).getByLabelText(label) as HTMLInputElement & HTMLSelectElement;
const optionValues = (select: HTMLSelectElement) => Array.from(select.options).map((o) => o.value);
const withStage = <S extends StageId>(stage: S, patch: Record<string, unknown>) => {
  const stages = clone(fixtures.settings.stages);
  Object.assign(stages[stage], patch);
  return stages;
};

describe('settings models tab', () => {
  it('lists the seven stages in pipeline order with model and thinking, and Edited only where a field differs from the defaults', async () => {
    setMockSettings({ stages: withStage('html_brief', { output_tokens: 40000 }) });
    const list = await openModels();
    const rows = within(list).getAllByRole('listitem');
    expect(rows.map((row) => row.querySelector('button span span')?.textContent)).toEqual(STAGE_NAMES.map(([, name]) => name));
    for (const [stage] of STAGE_NAMES) {
      const profile = fixtures.settings.stages[stage];
      const button = rowButton(stage);
      expect(button.getAttribute('aria-expanded')).toBe('false');
      expect(button.textContent).toContain(profile.model);
      expect(button.textContent).toContain(`${profile.thinking[0]!.toUpperCase()}${profile.thinking.slice(1)} thinking`);
      expect(within(button).queryByText('Edited') !== null, stage).toBe(stage === 'html_brief');
    }
    // The Models tab comes first and is selected.
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual(['Models', 'Google Cloud']);
    expect(tabs[0]!.getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText("Used when a stage's model is unavailable or keeps failing. Not used for limits or invalid output.")).toBeTruthy();
    expect(screen.getByLabelText("Review each page's design brief before its HTML is generated")).toBeTruthy();
  });

  it('offers the selected model thinking levels; a model without the current level flags Thinking without changing it', async () => {
    const lite = { ...flash, id: 'gemini-lite', thinking_levels: ['low', 'medium'] as ThinkingLevel[], available: false };
    vi.spyOn(api, 'getSettingsCapabilities').mockResolvedValue({ ...caps, models: [...caps.models, lite] } as SettingsCapabilities);
    await openModels();
    const region = expand('html_brief');
    const model = field(region, 'Model');
    const options = Array.from(model.options).map((o) => o.textContent);
    expect(options).toEqual(['gemini-3.8-flash', 'gemini-4-argon (availability unknown)', 'gemini-lite (unavailable)']);
    const thinking = field(region, 'Thinking');
    expect(optionValues(thinking)).toEqual(['low', 'medium', 'high']);

    fireEvent.change(model, { target: { value: 'gemini-lite' } });
    expect(model.value).toBe('gemini-lite');
    // No silent downgrade: the level stays, marked unsupported, with an issue on the field.
    expect(thinking.value).toBe('high');
    expect(thinking.getAttribute('aria-invalid')).toBe('true');
    expect(within(region).getByText("gemini-lite doesn't support high thinking. Pick low or medium.")).toBeTruthy();
    expect(field(region, 'Output tokens').value).toBe(String(fixtures.settings.stages.html_brief.output_tokens));
    expect(saveButton().disabled).toBe(true);

    fireEvent.change(thinking, { target: { value: 'medium' } });
    expect(optionValues(thinking)).toEqual(['low', 'medium']);
    expect(thinking.getAttribute('aria-invalid')).toBeNull();
    expect(saveButton().disabled).toBe(false);
  });

  it('rejects token caps over the model maximum and under the minimum, blocking Save with a message on the field', async () => {
    await openModels();
    const region = expand('reference_html');
    const output = field(region, 'Output tokens');
    const input = field(region, 'Input tokens');
    const max = (n: number) => String(n);
    fireEvent.change(output, { target: { value: String(flash.max_output_tokens + 1) } });
    expect(within(region).getByText(`gemini-3.8-flash allows at most ${max(flash.max_output_tokens)} output tokens.`)).toBeTruthy();
    expect(output.getAttribute('aria-invalid')).toBe('true');
    expect(saveButton().disabled).toBe(true);
    fireEvent.change(output, { target: { value: String(caps.limits.min_output_tokens - 1) } });
    expect(within(region).getByText(`Output needs at least ${caps.limits.min_output_tokens} tokens.`)).toBeTruthy();
    expect(saveButton().disabled).toBe(true);
    fireEvent.change(output, { target: { value: '40000' } });
    expect(saveButton().disabled).toBe(false);

    const inputRange = `gemini-3.8-flash allows ${max(caps.limits.min_input_tokens)} to ${max(flash.max_input_tokens)} input tokens.`;
    fireEvent.change(input, { target: { value: String(flash.max_input_tokens + 1) } });
    expect(within(region).getByText(inputRange)).toBeTruthy();
    fireEvent.change(input, { target: { value: String(caps.limits.min_input_tokens - 1) } });
    expect(within(region).getByText(inputRange)).toBeTruthy();
    expect(saveButton().disabled).toBe(true);
    fireEvent.change(input, { target: { value: '200000' } });
    expect(saveButton().disabled).toBe(false);

    // Text that isn't a number stays only while focused, and blocks Save meanwhile.
    input.focus();
    fireEvent.change(input, { target: { value: '12k' } });
    expect(within(region).getByText('Enter a whole number.')).toBeTruthy();
    expect(saveButton().disabled).toBe(true);
    fireEvent.blur(input);
    expect(input.value).toBe('200000');
    expect(within(region).queryByText('Enter a whole number.')).toBeNull();
    expect(saveButton().disabled).toBe(false);
  });

  it('bounds Validation repairs per stage: read-only at [0, 0], reference interpretation and native planning 0 to 1 (api.md 3.2)', async () => {
    await openModels();
    const interpretation = expand('reference_interpretation');
    expect(within(interpretation).getByRole('textbox', { name: 'Validation repairs' })).toBeTruthy();
    expect(within(interpretation).getByText('0 to 1.')).toBeTruthy();
    expect(within(interpretation).queryByText(/no repair step/)).toBeNull();
    const planning = expand('native_planning');
    const repairs = within(planning).getByRole('textbox', { name: 'Validation repairs' }) as HTMLInputElement;
    expect(within(planning).getByText('0 to 1.')).toBeTruthy();
    fireEvent.change(repairs, { target: { value: '2' } });
    expect(within(planning).getByText('Use 0 to 1.')).toBeTruthy();
    expect(saveButton().disabled).toBe(true);
    fireEvent.change(repairs, { target: { value: '0' } });
    expect(within(planning).queryByText('Use 0 to 1.')).toBeNull();
    expect(saveButton().disabled).toBe(false);
  });

  it('shows a stored Settings issue on its field with the row expanded, and still saves another field', async () => {
    const message = 'gemini-2.0-old is not offered any more. Pick another model.';
    setMockSettings({ stages: withStage('html_no_reference', { model: 'gemini-2.0-old' }), issues: [{ path: '/stages/html_no_reference/model', message }] });
    await openModels();
    expect(rowButton('html_no_reference').getAttribute('aria-expanded')).toBe('true');
    expect(rowButton('html_brief').getAttribute('aria-expanded')).toBe('false');
    const region = screen.getByRole('region', { name: 'HTML without a reference' });
    const model = field(region, 'Model');
    expect(model.value).toBe('gemini-2.0-old');
    expect(model.selectedOptions[0]!.textContent).toBe('gemini-2.0-old (unknown model)');
    expect(within(region).getByText(message)).toBeTruthy();
    expect(model.getAttribute('aria-invalid')).toBe('true');
    expect(saveButton().disabled).toBe(true);
    // 4.5:1: the chip text uses the text color on the soft danger fill.
    const chip = within(rowButton('html_no_reference')).getByText('1 issue');
    expect(chip.classList.contains('text-text')).toBe(true);
    expect(chip.classList.contains('text-danger')).toBe(false);

    const update = vi.spyOn(api, 'updateSettings');
    fireEvent.change(field(region, 'Output tokens'), { target: { value: '40000' } });
    expect(saveButton().disabled).toBe(false);
    fireEvent.click(saveButton());
    await screen.findByText('Settings saved.');
    expect(update).toHaveBeenCalledWith({ stages: { html_no_reference: { output_tokens: 40000 } } });
    // The stored issue stays until its own field is fixed.
    expect(within(region).getByText(message)).toBeTruthy();
  });

  it('estimates the most a call can cost from the model price, or says the cost is unknown', async () => {
    await openModels();
    const price = flash.price!;
    const at = (input: number, output: number) => `Up to ${usd((input * price.input_usd_per_mtok + output * price.output_usd_per_mtok) / 1_000_000)} per call (estimated)`;
    const region = expand('reference_html');
    expect(within(region).getByText(at(131072, 65536))).toBeTruthy();
    expect(at(131072, 65536)).toBe('Up to $0.26 per call (estimated)');
    fireEvent.change(field(region, 'Output tokens'), { target: { value: '32768' } });
    expect(within(region).getByText(at(131072, 32768))).toBeTruthy();
    // gemini-4-argon has no price in the fixture.
    expect(within(expand('html_brief')).getByText('Cost unknown')).toBeTruthy();
    // Interview and routine caps are per step: no estimate.
    for (const stage of ['interview', 'routine'] as const) {
      expect(within(expand(stage)).queryByText(/per call|Cost unknown/)).toBeNull();
    }
    expect(screen.getByText(`Estimates from Google's list prices checked on ${price.checked_on}. Actual billing may differ.`)).toBeTruthy();
  });

  it('keeps every price out of src/: estimates come from the capabilities', () => {
    const sources = import.meta.glob('../src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    expect(Object.keys(sources).length).toBeGreaterThan(20);
    for (const [path, text] of Object.entries(sources)) {
      expect(/usd_per_mtok\s*[:=]\s*[\d.]/.test(text), path).toBe(false);
      expect(/\$\s*0\.\d+\s*(\/|per)\s*(1M|M|million)/i.test(text), path).toBe(false);
    }
  });

  it('saves only the changed field, once', async () => {
    const update = vi.spyOn(api, 'updateSettings');
    const onSaved = vi.fn();
    await openModels({ onSaved });
    fireEvent.change(field(expand('html_brief'), 'Output tokens'), { target: { value: '40000' } });
    expect(within(rowButton('html_brief')).getByText('Edited')).toBeTruthy();
    fireEvent.click(saveButton());
    await screen.findByText('Settings saved.');
    expect(update).toHaveBeenCalledTimes(1);
    expect(update.mock.calls[0]![0]).toEqual({ stages: { html_brief: { output_tokens: 40000 } } });
    expect(onSaved.mock.calls[0]![0].stages.html_brief.output_tokens).toBe(40000);
    expect(saveButton().disabled).toBe(true);
  });

  it("Reset to defaults restores that stage's draft only", async () => {
    setMockSettings({ stages: { ...withStage('html_brief', { output_tokens: 40000 }), reference_html: { ...fixtures.settings.stages.reference_html, output_tokens: 32768 } } });
    await openModels();
    const brief = expand('html_brief');
    fireEvent.change(field(brief, 'Thinking'), { target: { value: 'low' } });
    expect(within(rowButton('reference_html')).getByText('Edited')).toBeTruthy();
    fireEvent.click(within(brief).getByRole('button', { name: 'Reset HTML brief to defaults' }));
    const defaults = caps.defaults.stages.html_brief;
    expect(field(brief, 'Thinking').value).toBe(defaults.thinking);
    expect(field(brief, 'Output tokens').value).toBe(String(defaults.output_tokens));
    expect(within(rowButton('html_brief')).queryByText('Edited')).toBeNull();
    // The other stage keeps its edit; the reset is saved only on Save.
    expect(within(rowButton('reference_html')).getByText('Edited')).toBeTruthy();
    const update = vi.spyOn(api, 'updateSettings');
    expect(update).not.toHaveBeenCalled();
    fireEvent.click(saveButton());
    await screen.findByText('Settings saved.');
    expect(update).toHaveBeenCalledWith({ stages: { html_brief: { output_tokens: defaults.output_tokens } } });
  });

  it('maps a 422 invalid_settings path to its field: the row expands and focus moves there; an unknown path shows above the form', async () => {
    await openModels();
    const body = fixtures.invalidSettings.error;
    const issues = [...(body.detail!.issues as Array<{ path: string; message: string }>), { path: '/stages/html_brief/colour', message: 'Colour is not a setting.' }];
    const update = vi.spyOn(api, 'updateSettings').mockRejectedValueOnce(new ApiError(422, body.code, body.message, { issues }));
    fireEvent.click(screen.getByLabelText("Review each page's design brief before its HTML is generated"));
    expect(rowButton('html_brief').getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(saveButton());
    await waitFor(() => expect(rowButton('html_brief').getAttribute('aria-expanded')).toBe('true'));
    const region = screen.getByRole('region', { name: 'HTML brief' });
    const output = field(region, 'Output tokens');
    await waitFor(() => expect(document.activeElement).toBe(output));
    expect(within(region).getByText('gemini-4-argon allows at most 65536 output tokens.')).toBeTruthy();
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain(body.message);
    expect(alert.textContent).toContain('Colour is not a setting.');
    expect(update).toHaveBeenCalledWith({ review_briefs: true });
    // Editing the field clears its server issue.
    fireEvent.change(output, { target: { value: '30000' } });
    expect(within(region).queryByText('gemini-4-argon allows at most 65536 output tokens.')).toBeNull();
  });

  it('renders notices as status lines at the top of the tab', async () => {
    const notices = ['HTML brief now uses gemini-2.5-pro, copied from your planner model.', 'Interview now uses gemini-2.5-flash, copied from your worker model.'];
    setMockSettings({ notices });
    await openModels();
    const status = screen.getByRole('status', { name: 'Notices' });
    for (const notice of notices) expect(within(status).getByText(notice)).toBeTruthy();
  });

  it('opens at a stage with its row expanded and the field focused', async () => {
    await openModels({ at: { stage: 'reference_html', field: 'output_tokens' } });
    expect(rowButton('reference_html').getAttribute('aria-expanded')).toBe('true');
    expect(rowButton('html_brief').getAttribute('aria-expanded')).toBe('false');
    const region = screen.getByRole('region', { name: 'HTML with a reference' });
    await waitFor(() => expect(document.activeElement).toBe(field(region, 'Output tokens')));
  });

  it('openSettings(stage) from the app services opens Settings there', async () => {
    renderServices();
    fireEvent.click(await screen.findByText('Adjust in Settings'));
    const dialog = await screen.findByRole('dialog', { name: 'Settings' });
    await within(dialog).findByRole('list', { name: 'Stages' });
    const region = within(dialog).getByRole('region', { name: 'HTML with a reference' });
    await waitFor(() => expect(document.activeElement).toBe(within(region).getByLabelText('Output tokens')));
  });

  it('shows the error with Retry and no default values when the capabilities fail to load', async () => {
    const get = vi.spyOn(api, 'getSettingsCapabilities').mockRejectedValueOnce(new ApiError(502, 'invalid_response', "Couldn't read the model list. Try again."));
    render(<SettingsModal open onClose={() => {}} onSaved={() => {}} />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Couldn't load the models");
    expect(screen.queryByRole('list', { name: 'Stages' })).toBeNull();
    expect(screen.queryByLabelText('Fallback model')).toBeNull();
    expect(screen.queryByText(/gemini-|131072|Up to \$/)).toBeNull();
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await screen.findByRole('list', { name: 'Stages' });
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('read-only Validation repairs shows the stored value, and an issue on it takes focus', async () => {
    const message = 'Reference interpretation has no repair step. Reset it to 0.';
    // No 3.2 stage has a [0, 0] bound any more; a deployment's capabilities still may.
    const noRepairs = clone(caps);
    noRepairs.limits.validation_repairs.reference_interpretation = [0, 0];
    vi.spyOn(api, 'getSettingsCapabilities').mockResolvedValue(noRepairs);
    setMockSettings({ stages: withStage('reference_interpretation', { validation_repairs: 1 }), issues: [{ path: '/stages/reference_interpretation/validation_repairs', message }] });
    await openModels();
    const region = screen.getByRole('region', { name: 'Reference interpretation' });
    const value = within(region).getByText('1 (this stage has no repair step)');
    expect(within(region).getByText(message)).toBeTruthy();
    expect(within(region).queryByRole('textbox', { name: 'Validation repairs' })).toBeNull();
    // A 422 on that path focuses the read-only value instead of leaving focus pending.
    fireEvent.click(rowButton('reference_interpretation'));
    expect(rowButton('reference_interpretation').getAttribute('aria-expanded')).toBe('false');
    vi.spyOn(api, 'updateSettings').mockRejectedValueOnce(
      new ApiError(422, 'invalid_settings', 'Fix the highlighted settings and save again.', { issues: [{ path: '/stages/reference_interpretation/validation_repairs', message: 'Use 0 to 0.' }] }),
    );
    fireEvent.click(screen.getByLabelText("Review each page's design brief before its HTML is generated"));
    fireEvent.click(saveButton());
    await waitFor(() => expect((document.activeElement as HTMLElement | null)?.textContent).toBe(value.textContent));
    expect(document.activeElement?.getAttribute('aria-describedby')).toBeTruthy();
    expect(screen.getByText('Use 0 to 0.')).toBeTruthy();
  });

  it('keeps edits made while a save is in flight', async () => {
    const real = api.updateSettings.bind(api);
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const update = vi.spyOn(api, 'updateSettings').mockImplementationOnce(async (u) => {
      await gate;
      return real(u);
    });
    await openModels();
    const brief = expand('html_brief');
    fireEvent.change(field(brief, 'Output tokens'), { target: { value: '40000' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(saveButton().getAttribute('aria-busy')).toBe('true'));
    // Saving disables Save only: the fields stay editable.
    fireEvent.change(field(brief, 'Thinking'), { target: { value: 'low' } });
    fireEvent.change(field(expand('reference_html'), 'Output tokens'), { target: { value: '32768' } });
    release();
    await screen.findByText('Settings saved.');
    expect(update.mock.calls[0]![0]).toEqual({ stages: { html_brief: { output_tokens: 40000 } } });
    expect(field(brief, 'Output tokens').value).toBe('40000');
    expect(field(brief, 'Thinking').value).toBe('low');
    expect(field(screen.getByRole('region', { name: 'HTML with a reference' }), 'Output tokens').value).toBe('32768');
    expect(saveButton().disabled).toBe(false);
    fireEvent.click(saveButton());
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    expect(update.mock.calls[1]![0]).toEqual({ stages: { html_brief: { thinking: 'low' }, reference_html: { output_tokens: 32768 } } });
  });

  it('describes the API key field with its 422 error', async () => {
    await openModal();
    vi.spyOn(api, 'updateSettings').mockRejectedValueOnce(
      new ApiError(422, 'invalid_settings', 'Fix the highlighted settings and save again.', { issues: [{ path: '/google_api_key', message: 'This key is not a Google API key.' }] }),
    );
    const input = screen.getByLabelText('Google API key') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'nope' } });
    fireEvent.click(saveButton());
    await screen.findByText('This key is not a Google API key.');
    const ids = (input.getAttribute('aria-describedby') ?? '').split(' ');
    expect(ids).toContain('settings-key-status');
    const error = ids.map((id) => document.getElementById(id)).find((el) => el?.textContent === 'This key is not a Google API key.');
    expect(error).toBeTruthy();
    expect(ids.every((id) => document.getElementById(id) !== null)).toBe(true);
  });

  it('moves between tabs with the arrow keys', async () => {
    await openModels();
    const models = screen.getByRole('tab', { name: 'Models' });
    fireEvent.keyDown(models, { key: 'ArrowRight' });
    const google = screen.getByRole('tab', { name: 'Google Cloud' });
    expect(google.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(google);
    expect(screen.getByLabelText('GCP project')).toBeTruthy();
    expect(screen.queryByRole('list', { name: 'Stages' })).toBeNull();
    fireEvent.keyDown(google, { key: 'Home' });
    expect(document.activeElement).toBe(models);
    expect(screen.getByRole('list', { name: 'Stages' })).toBeTruthy();
  });
});

function Probe() {
  const { openSettings } = useAppServices();
  return (
    <>
      <button onClick={() => void api.regenerateBlueprint(fixtures.build.id).catch(() => {})}>Send</button>
      <button onClick={() => void api.addSource(fixtures.build.id, { kind: 'bigquery', uri: 'p.d.t' }).catch(() => {})}>Add source</button>
      <button onClick={() => openSettings()}>Probe settings</button>
      <button onClick={() => openSettings({ stage: 'reference_html', field: 'output_tokens' })}>Adjust in Settings</button>
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
    // The total label uses the body font; the Node column's body cells stay mono.
    expect(within(totals).getByText('Total, 2 runs').classList.contains('font-mono')).toBe(false);
    expect(within(rows[1] as HTMLElement).getByText('plan').classList.contains('font-mono')).toBe(true);
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
