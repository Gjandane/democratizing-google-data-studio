import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { OpenBuildEvents } from '../src/api/events';
import type { Build, Outline, OutlineQuestion } from '../src/api/types';
import { ActivityColumn } from '../src/features/activity/ActivityColumn';
import { useBuildStream } from '../src/features/activity/useBuildStream';
import { ArtifactStage } from '../src/features/workspace/ArtifactStage';
import { patchMockBuild, resetMockState, setMockArtifact, setMockRunFailure } from '../src/mocks/api';
import { openMockBuildEvents } from '../src/mocks/events';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const off = (el: HTMLElement) => el.matches(':disabled');
const type = (input: HTMLElement, value: string) => fireEvent.change(input, { target: { value } });
const box = (text: string) => screen.getByRole('checkbox', { name: text }) as HTMLInputElement;
const confirmButton = () => screen.getByRole('button', { name: 'Confirm outline' });
const activity = () => screen.getByRole('complementary', { name: 'Activity' });
const id = fixtures.build.id;
const idle = { artifactSeq: { context: 0, outline: 0, design: 0, blueprint: 0 }, running: null, runErrors: {} };
const outlineStage = { stage: 'outline' as const, artifacts: { context: 'confirmed' as const, outline: 'draft' as const, design: 'missing' as const, blueprint: 'missing' as const } };

/** The ArtifactStage beside the activity column, both on the build's (mock) stream. */
function Workspace({ initial, open }: { initial: Build; open?: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const stream = useBuildStream(build, setBuild, open ?? openMockBuildEvents);
  return (
    <>
      <ActivityColumn build={build} stream={stream} />
      <div data-testid="scroller" style={{ overflowY: 'auto', height: 400 }}>
        <ArtifactStage build={build} name="outline" stream={stream} acceptReady={false} onBuildChange={setBuild} />
      </div>
    </>
  );
}

/** A stream that holds `run.finished` until released, so the run stays live in the activity column. */
function holdFinish() {
  const held: Array<() => void> = [];
  const open: OpenBuildEvents = (buildId, handlers) =>
    openMockBuildEvents(buildId, { ...handlers, onEvent: (e) => (e.name === 'run.finished' ? held.push(() => handlers.onEvent(e)) : handlers.onEvent(e)) });
  const release = () => act(() => held.splice(0).forEach((f) => f()));
  return { open, release };
}

/** The fixture build in Outline with `outline` stored (the fixture outline by default). */
async function renderOutline(outline: Outline = fixtures.outline, open?: OpenBuildEvents) {
  patchMockBuild(id, outlineStage);
  setMockArtifact(id, 'context', { ...fixtures.context, issues: [] });
  setMockArtifact(id, 'outline', structuredClone(outline));
  render(<Workspace initial={await api.getBuild(id)} open={open} />);
  await screen.findByRole('checkbox', { name: fixtures.outline.sections[0]!.questions[0]!.text });
}

const question = (n: number, selected: boolean): OutlineQuestion => ({ id: `q${n}`, text: `Question number ${n}?`, rationale: 'Filler.', recommended: false, selected, kpi_refs: [], origin: 'proposed' });

/** The fixture outline plus a section of extra questions, `selected` of them ticked. */
function bigOutline(extra: number, selected: number): Outline {
  const base = structuredClone(fixtures.outline);
  base.sections.push({ id: 's3', title: 'More', purpose: 'Padding.', questions: Array.from({ length: extra }, (_, i) => question(100 + i, i < selected)) });
  return base;
}

describe('Outline picker', () => {
  it('starts with the recommended questions ticked when the outline is proposed', async () => {
    patchMockBuild(id, { stage: 'context', artifacts: { context: 'draft', outline: 'missing', design: 'missing', blueprint: 'missing' } });
    setMockArtifact(id, 'context', { ...fixtures.context, issues: [] });
    setMockArtifact(id, 'outline', null);
    await api.confirmContext(id);
    await waitFor(async () => expect(await api.getOutline(id)).not.toBeNull());
    render(<Workspace initial={await api.getBuild(id)} />);
    const proposed = fixtures.outline.sections.flatMap((s) => s.questions).filter((q) => q.origin === 'proposed');
    await screen.findByRole('checkbox', { name: proposed[0]!.text });
    for (const q of proposed) expect(box(q.text).checked).toBe(q.recommended);
    // The badge, KPI names and rationale describe the checkbox.
    const first = box(proposed[0]!.text);
    const meta = document.getElementById(first.getAttribute('aria-describedby')!)!;
    expect(meta.textContent).toContain('Recommended');
    await waitFor(() => expect(meta.textContent).toContain('Net revenue'));
    expect(meta.textContent).toContain(proposed[0]!.rationale);
    expect(screen.getByText('4 of 24 selected')).toBeTruthy();
  });

  it('saves a tick with PUT outline/selection and keeps focus, the rows and the scroll position', async () => {
    await renderOutline();
    const put = vi.spyOn(api, 'updateOutlineSelection');
    const scroller = screen.getByTestId('scroller');
    let top = 120;
    Object.defineProperty(scroller, 'scrollTop', { configurable: true, get: () => top, set: (v: number) => { top = v; } });
    const q6 = box('Which countries bring the most net revenue?');
    q6.focus();
    fireEvent.click(q6);
    expect(q6.checked).toBe(true);
    expect(screen.getByText('7 of 24 selected')).toBeTruthy();
    expect(off(confirmButton())).toBe(true); // the PUT is on its way
    await waitFor(() => expect(off(confirmButton())).toBe(false));
    expect(put).toHaveBeenCalledWith(id, [{ id: 'q6', selected: true }]);
    await screen.findByText('Revision 4');
    expect(box('Which countries bring the most net revenue?')).toBe(q6);
    expect(document.activeElement).toBe(q6);
    expect(top).toBe(120);
    expect(screen.queryByText('Loading the outline…')).toBeNull();
    expect((await api.getOutline(id))!.sections[1]!.questions.find((q) => q.id === 'q6')!.selected).toBe(true);
  });

  it('disables Confirm with "24 at most" at 25 selected', async () => {
    await renderOutline(bigOutline(19, 18)); // 6 + 18 = 24
    expect(screen.getByText('24 of 24 selected')).toBeTruthy();
    await waitFor(() => expect(off(confirmButton())).toBe(false));
    fireEvent.click(box('Question number 118?'));
    expect(screen.getByText('25 of 24 selected: 24 at most')).toBeTruthy();
    expect(off(confirmButton())).toBe(true);
    await screen.findByText('Revision 4');
    expect(off(confirmButton())).toBe(true);
    fireEvent.click(box('Question number 100?'));
    await waitFor(() => expect(off(confirmButton())).toBe(false));
  });

  it('keeps Other questions through Re-propose', async () => {
    await renderOutline();
    const other = 'How do bulk and single order lines compare by segment?';
    expect(document.getElementById(box(other).getAttribute('aria-describedby')!)!.textContent).toContain('Added by you');
    fireEvent.click(screen.getByRole('button', { name: 'Re-propose' }));
    await screen.findByText('Revision 4');
    expect(box(other).checked).toBe(true);
    expect(box('What is the average order value?').checked).toBe(true); // unchanged text keeps its tick
  });

  it('Suggest more shows the run in the activity column and adds the questions on artifact.updated', async () => {
    const { open, release } = holdFinish();
    await renderOutline(fixtures.outline, open);
    const s1 = fixtures.outline.sections[0]!;
    fireEvent.click(screen.getAllByRole('button', { name: 'Suggest more' })[0]!);
    expect(await within(activity()).findAllByText(/Reading the section|Suggesting questions/, {}, { timeout: 2000 })).not.toHaveLength(0);
    const added = await screen.findByRole('checkbox', { name: `Which segment leads in ${s1.title.toLowerCase()}?` });
    expect((added as HTMLInputElement).checked).toBe(false);
    // The run still holds the lock: every control waits.
    expect(off(added)).toBe(true);
    expect(off(screen.getAllByRole('button', { name: 'Suggest more' })[0]!)).toBe(true);
    release();
    await waitFor(() => expect(off(added)).toBe(false));
    expect(screen.getByText('3 of 5 selected')).toBeTruthy();
  });

  it('adds an Other question to a section and as a new section', async () => {
    const { open, release } = holdFinish();
    await renderOutline(fixtures.outline, open);
    const other = screen.getByRole('textbox', { name: 'Your own question for Where revenue comes from' });
    type(other, 'which customers order again');
    const spy = vi.spyOn(api, 'addOutlineQuestions');
    fireEvent.click(screen.getAllByRole('button', { name: 'Add question' })[1]!);
    expect(await within(activity()).findAllByText(/Reading your question|Normalizing/, {}, { timeout: 2000 })).not.toHaveLength(0);
    expect(spy).toHaveBeenCalledWith(id, 's2', 'which customers order again');
    const added = await screen.findByRole('checkbox', { name: 'Which customers order again?' });
    expect((added as HTMLInputElement).checked).toBe(true);
    expect((other as HTMLTextAreaElement).value).toBe('');
    release();

    const fresh = screen.getByRole('textbox', { name: 'Questions for a new section' });
    await waitFor(() => expect(off(fresh)).toBe(false));
    type(fresh, 'Where do returns come from?');
    fireEvent.click(screen.getByRole('button', { name: 'Add section' }));
    const section = await screen.findByRole('group', { name: 'Your questions' });
    expect(within(section).getByRole('checkbox', { name: 'Where do returns come from?' })).toBeTruthy();
    expect(spy).toHaveBeenLastCalledWith(id, null, 'Where do returns come from?');
    release();
  });

  it('shows the assistant explanation for an Other text asking for GPS animation', async () => {
    await renderOutline();
    type(screen.getByRole('textbox', { name: 'Your own question for Revenue snapshot' }), 'Animate GPS points along each delivery route');
    fireEvent.click(screen.getAllByRole('button', { name: 'Add question' })[0]!);
    expect(await within(activity()).findByText(/This app cannot animate GPS points/)).toBeTruthy();
    // Kept as a requirement in the outline.
    expect(await screen.findByRole('checkbox', { name: 'Animate GPS points along each delivery route?' })).toBeTruthy();
  });

  it('keeps ticks off from Suggest more until its run starts, so no PUT meets the lock', async () => {
    await renderOutline();
    const suggest = vi.spyOn(api, 'suggestOutlineQuestions').mockResolvedValue({ run_id: 'r_never_started' });
    const put = vi.spyOn(api, 'updateOutlineSelection');
    const q6 = box('Which countries bring the most net revenue?');
    fireEvent.click(screen.getAllByRole('button', { name: 'Suggest more' })[0]!);
    expect(off(q6)).toBe(true); // the POST is on its way
    await waitFor(() => expect(suggest).toHaveBeenCalled());
    await act(async () => {});
    // Accepted, run.started not here yet: still off.
    expect(off(q6)).toBe(true);
    expect(off(screen.getAllByRole('button', { name: 'Add question' })[0]!)).toBe(true);
    expect(put).not.toHaveBeenCalled();
  });

  it('keeps the Other text when its run fails', async () => {
    setMockRunFailure('outline_other', 'The model could not be reached.');
    await renderOutline();
    const other = screen.getByRole('textbox', { name: 'Your own question for Revenue snapshot' });
    type(other, 'Which weekday sells most?');
    fireEvent.click(screen.getAllByRole('button', { name: 'Add question' })[0]!);
    expect(await screen.findByText('The model could not be reached.')).toBeTruthy();
    await waitFor(() => expect(off(other)).toBe(false));
    expect((other as HTMLTextAreaElement).value).toBe('Which weekday sells most?');
  });

  it('blocks Other text over 1000 characters with a count', async () => {
    await renderOutline();
    const other = screen.getByRole('textbox', { name: 'Your own question for Revenue snapshot' });
    const add = screen.getAllByRole('button', { name: 'Add question' })[0]!;
    expect(off(add)).toBe(true);
    type(other, 'x'.repeat(1001));
    expect(other.getAttribute('aria-invalid')).toBe('true');
    expect(document.getElementById(other.getAttribute('aria-describedby')!)!.textContent).toBe('1,001 / 1,000 characters. Remove 1 to add it.');
    expect(off(add)).toBe(true);
    type(other, 'Which weekday sells most?');
    expect(off(add)).toBe(false);
  });

  it('keeps the tick and offers Save again when the PUT fails', async () => {
    await renderOutline();
    const put = vi.spyOn(api, 'updateOutlineSelection').mockRejectedValueOnce(new Error('offline'));
    const q6 = box('Which countries bring the most net revenue?');
    fireEvent.click(q6);
    expect(await screen.findByText("Couldn't save your selection")).toBeTruthy();
    expect(q6.checked).toBe(true);
    expect(off(confirmButton())).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Re-propose' }))).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Save again' }));
    await waitFor(() => expect(screen.queryByText("Couldn't save your selection")).toBeNull());
    await waitFor(() => expect(off(confirmButton())).toBe(false));
    expect(put).toHaveBeenCalledTimes(2);
    expect(q6.checked).toBe(true);
  });

  it('disables every control while a run holds the lock, and shows the empty state', async () => {
    patchMockBuild(id, outlineStage);
    setMockArtifact(id, 'outline', structuredClone(fixtures.outline));
    const { unmount } = render(<ArtifactStage build={await api.getBuild(id)} name="outline" stream={{ ...idle, running: 'outline_suggest' }} acceptReady={false} onBuildChange={() => {}} />);
    const q1 = await screen.findByRole('checkbox', { name: fixtures.outline.sections[0]!.questions[0]!.text });
    expect(off(q1)).toBe(true);
    expect(off(screen.getAllByRole('button', { name: 'Suggest more' })[0]!)).toBe(true);
    expect(off(screen.getByRole('textbox', { name: 'Questions for a new section' }))).toBe(true);
    expect(off(confirmButton())).toBe(true);
    unmount();

    setMockArtifact(id, 'outline', null);
    render(<ArtifactStage build={await api.getBuild(id)} name="outline" stream={idle} acceptReady={false} onBuildChange={() => {}} />);
    expect(await screen.findByText('No outline yet')).toBeTruthy();
  });
});
