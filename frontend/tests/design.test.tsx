import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { Build, Design, Outline } from '../src/api/types';
import { useBuildStream } from '../src/features/activity/useBuildStream';
import { ArtifactStage } from '../src/features/workspace/ArtifactStage';
import { patchMockBuild, resetMockState, setMockArtifact } from '../src/mocks/api';
import { openMockBuildEvents } from '../src/mocks/events';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const id = fixtures.build.id;
const off = (el: HTMLElement) => el.matches(':disabled');
const type = (input: HTMLElement, value: string) => fireEvent.change(input, { target: { value } });
const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const described = (el: HTMLElement) => document.getElementById(el.getAttribute('aria-describedby') ?? '')?.textContent ?? '';
const confirmButton = () => screen.getByRole('button', { name: 'Confirm design' });
const addButton = () => screen.getByRole('button', { name: 'Add color' });
const preview = () => document.querySelector<HTMLElement>('[data-preview]')!;
const designStage = { stage: 'design' as const, artifacts: { context: 'confirmed' as const, outline: 'confirmed' as const, design: 'draft' as const, blueprint: 'missing' as const } };
const [studio, night] = fixtures.designPresets as [(typeof fixtures.designPresets)[number], (typeof fixtures.designPresets)[number]];

function Workspace({ initial }: { initial: Build }) {
  const [build, setBuild] = useState(initial);
  const stream = useBuildStream(build, setBuild, openMockBuildEvents);
  return <ArtifactStage build={build} name="design" stream={stream} acceptReady={false} onBuildChange={setBuild} />;
}

/** The fixture build in Design with `design` stored (the fixture design by default). */
async function renderDesign(patch: Partial<Design> = {}, outline: Outline = fixtures.outline) {
  patchMockBuild(id, designStage);
  setMockArtifact(id, 'outline', structuredClone(outline));
  setMockArtifact(id, 'design', { ...structuredClone(fixtures.design), ...patch });
  render(<Workspace initial={await api.getBuild(id)} />);
  await screen.findByRole('button', { name: night.name });
}

/** An outline with `n` sections, each with one selected question. */
function sectionsOutline(n: number): Outline {
  return {
    revision: 1,
    sections: Array.from({ length: n }, (_, i) => ({
      id: `s${i + 1}`,
      title: `Section ${i + 1}`,
      purpose: 'Filler.',
      questions: [{ id: `q${i + 1}`, text: `Question ${i + 1}?`, rationale: 'Filler.', recommended: true, selected: true, kpi_refs: [], origin: 'proposed' as const }],
    })),
  };
}

describe('Design picker', () => {
  it('shows each preset as a card with labelled swatches, the current one pressed', async () => {
    await renderDesign();
    const card = screen.getByRole('button', { name: studio.name });
    expect(card.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: night.name }).getAttribute('aria-pressed')).toBe('false');
    // Every swatch carries its hex as text: color is never the only cue.
    for (const color of studio.palette) expect(within(card).getByText(color)).toBeTruthy();
    expect(within(card).getByText(`bg ${studio.background}`)).toBeTruthy();
    expect(screen.getByText(`${studio.name} preset`)).toBeTruthy();
  });

  it('picking a preset fills every field, saves it and redraws the preview', async () => {
    await renderDesign();
    const put = vi.spyOn(api, 'updateDesign');
    fireEvent.click(screen.getByRole('button', { name: night.name }));
    expect(field('Background').value).toBe(night.background);
    expect(field('Surface').value).toBe(night.surface);
    expect(field('Text').value).toBe(night.text);
    expect(field('Accent').value).toBe(night.accent);
    night.palette.forEach((color, i) => expect(field(`Palette color ${i + 1}`).value).toBe(color));
    expect(screen.queryByLabelText(`Palette color ${night.palette.length + 1}`)).toBeNull();
    expect((screen.getByLabelText('Font') as HTMLSelectElement).value).toBe(night.font_family);
    expect(preview().style.backgroundColor).toBe('rgb(11, 18, 32)');
    expect(preview().style.fontFamily).toContain(night.font_family);
    await screen.findByText('Revision 2');
    expect(put).toHaveBeenCalledWith(id, expect.objectContaining({
      preset_id: night.id, background: night.background, surface: night.surface, text: night.text, accent: night.accent,
      palette: night.palette, font_family: night.font_family, source: 'preset', title: fixtures.design.title, page_structure: 'per_section',
    }));
    expect(screen.getByRole('button', { name: night.name }).getAttribute('aria-pressed')).toBe('true');
  });

  it('Reset to preset calls design/prefill and shows the fresh design', async () => {
    await renderDesign({ accent: '#123456', source: 'user' });
    expect(screen.getByText(`Edited from ${studio.name}`)).toBeTruthy();
    const prefill = vi.spyOn(api, 'prefillDesign');
    fireEvent.click(screen.getByRole('button', { name: 'Reset to preset' }));
    await waitFor(() => expect(field('Accent').value).toBe(studio.accent));
    expect(prefill).toHaveBeenCalledWith(id);
    expect(screen.getByText(`${studio.name} preset`)).toBeTruthy();
  });

  it('palette chips accept #RRGGBB only, 3 to 8 of them', async () => {
    await renderDesign();
    const put = vi.spyOn(api, 'updateDesign');
    const add = field('Add a palette color');
    for (const bad of ['#12AB3', 'blue', '#12AB3G', '12AB34']) {
      type(add, bad);
      expect(off(addButton())).toBe(true);
      expect(described(add)).toBe('Use a color like #1E40AF.');
    }
    type(add, '#12ab34');
    expect(off(addButton())).toBe(false);
    fireEvent.click(addButton());
    expect(field('Palette color 5').value).toBe('#12AB34');
    expect(add.value).toBe('');
    await screen.findByText('Revision 2');
    expect(put).toHaveBeenLastCalledWith(id, expect.objectContaining({ palette: [...fixtures.design.palette, '#12AB34'], source: 'user' }));
    // Up to 8: then adding is off and says why.
    for (const color of ['#000001', '#000002', '#000003']) {
      type(add, color);
      fireEvent.keyDown(add, { key: 'Enter' });
    }
    expect(field('Palette color 8').value).toBe('#000003');
    expect(off(add)).toBe(true);
    expect(off(addButton())).toBe(true);
    expect(screen.getByText('8 colors at most. Remove one to add another.')).toBeTruthy();
    // An edited chip takes only #RRGGBB: anything else shows the rule and is never saved.
    await waitFor(() => expect((put.mock.calls.at(-1)![1] as Design).palette).toHaveLength(8));
    const calls = put.mock.calls.length;
    const chip = field('Palette color 1');
    chip.focus();
    type(chip, '#zz0000');
    expect(described(chip)).toBe('Use a color like #1E40AF.');
    fireEvent.blur(chip);
    expect(chip.value).toBe(fixtures.design.palette[0]);
    expect(put.mock.calls.length).toBe(calls);
  });

  it('keeps at least 3 palette colors', async () => {
    await renderDesign({ palette: ['#111111', '#222222', '#333333'] });
    for (let i = 1; i <= 3; i += 1) expect(off(screen.getByRole('button', { name: new RegExp(`^Remove palette color ${i} `) }))).toBe(true);
    type(field('Add a palette color'), '#444444');
    fireEvent.click(addButton());
    expect(off(screen.getByRole('button', { name: 'Remove palette color 1 #111111' }))).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Remove palette color 1 #111111' }));
    expect(field('Palette color 1').value).toBe('#222222');
    expect(screen.queryByLabelText('Palette color 4')).toBeNull();
  });

  it('shows a low-contrast issue from the server on the Text field and blocks Confirm', async () => {
    await renderDesign();
    await waitFor(() => expect(off(confirmButton())).toBe(false));
    const text = field('Text');
    text.focus();
    type(text, '#E2E8F0');
    expect(preview().style.color).toBe('rgb(226, 232, 240)');
    fireEvent.blur(text);
    await waitFor(() => expect(described(field('Text'))).toMatch(/contrast\. Use 4\.5:1 or more\./));
    expect(field('Text').getAttribute('aria-invalid')).toBe('true');
    expect(screen.getByText('Fix the open issues to confirm')).toBeTruthy();
    expect(off(confirmButton())).toBe(true);
    expect(screen.getByText('Edited from Studio Light')).toBeTruthy();
  });

  it('per_section shows the page count from the confirmed outline', async () => {
    await renderDesign();
    const perSection = screen.getByRole('radio', { name: 'One page per section' });
    expect((perSection as HTMLInputElement).checked).toBe(true);
    await waitFor(() => expect(described(perSection)).toBe('2 pages from your confirmed outline'));
    const put = vi.spyOn(api, 'updateDesign');
    fireEvent.click(screen.getByRole('radio', { name: 'A single page' }));
    await waitFor(() => expect(put).toHaveBeenCalledWith(id, expect.objectContaining({ page_structure: 'single' })));
    expect(screen.getByText('Single page')).toBeTruthy(); // the preview follows
  });

  it('says when the outline has more sections than pages', async () => {
    await renderDesign({}, sectionsOutline(6));
    const perSection = screen.getByRole('radio', { name: 'One page per section' });
    await waitFor(() => expect(described(perSection)).toBe('6 sections have questions: one page per section allows 5 at most.'));
  });

  it('marks a design prefilled from a style reference "From your reference"', async () => {
    await renderDesign({ source: 'reference' });
    expect(screen.getByText('From your reference')).toBeTruthy();
    // An edit makes the colors the user's own.
    const accent = field('Accent');
    type(accent, '#0000AA');
    expect(screen.queryByText('From your reference')).toBeNull();
    expect(screen.getByText(`Edited from ${studio.name}`)).toBeTruthy();
  });

  it('the mock prefills from a style reference with source reference', async () => {
    patchMockBuild(id, designStage);
    const png = new File([new Uint8Array([137, 80, 78, 71])], 'style.png', { type: 'image/png' });
    await api.uploadReferences(id, [png], 'style', '');
    await waitFor(async () => expect((await api.getReferences(id))?.mode).toBe('style'), { timeout: 3000 });
    const design = await api.prefillDesign(id);
    expect(design.source).toBe('reference');
    expect(design.palette.length).toBeGreaterThanOrEqual(3);
  });

  it('the title and subtitle redraw the preview as you type and save on blur', async () => {
    await renderDesign();
    const put = vi.spyOn(api, 'updateDesign');
    const title = field('Title');
    title.focus();
    type(title, 'Weekly sales');
    expect(within(preview()).getByText('Weekly sales')).toBeTruthy();
    expect(put).not.toHaveBeenCalled();
    type(field('Subtitle'), '');
    expect(within(preview()).queryByText(fixtures.design.subtitle!)).toBeNull();
    fireEvent.blur(title);
    await waitFor(() => expect(put).toHaveBeenCalledWith(id, expect.objectContaining({ title: 'Weekly sales', subtitle: null, source: 'preset' })));
  });

  it('disables every control while a run holds the lock', async () => {
    patchMockBuild(id, designStage);
    setMockArtifact(id, 'design', structuredClone(fixtures.design));
    const build = await api.getBuild(id);
    const stream = { artifactSeq: { context: 0, outline: 0, design: 0, blueprint: 0 }, running: 'blueprint' as const, runErrors: {} };
    render(<ArtifactStage build={build} name="design" stream={stream} acceptReady={false} onBuildChange={() => {}} />);
    const card = await screen.findByRole('button', { name: night.name });
    expect(off(card)).toBe(true);
    expect(off(field('Background'))).toBe(true);
    expect(off(field('Title'))).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Reset to preset' }))).toBe(true);
    expect(off(confirmButton())).toBe(true);
  });
});
