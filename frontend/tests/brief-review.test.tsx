// Task 16.4: the brief review gate (docs/stage-settings-ui.md, Brief review).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { Assessment, BriefReview, DesignPages } from '../src/api/types';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { mockRatioIssue, patchMockBuild, resetMockState, setMockArtifact, setMockAssessment, setMockDesignPages } from '../src/mocks/api';
import { emit } from '../src/mocks/events';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const id = fixtures.build.id;
const review = fixtures.designPagesReview.review!;
const off = (el: Element) => el.matches(':disabled');
const WAIT = 'Waiting for your brief review';
const CONFLICT = 'This brief changed in another window. Check it, then approve again.';
const STALE = 'The build changed after this brief was written. Cancel and run it again.';

const withReview = (change: Partial<BriefReview>): DesignPages => ({ ...fixtures.designPagesReview, review: { ...review, ...change } });

function shell(onOpenSettings: () => void = () => {}) {
  return render(
    <MemoryRouter initialEntries={[`/builds/${id}`]}>
      <Routes>
        <Route path="/builds/:id" element={<WorkspaceShell onOpenSettings={onOpenSettings} />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The prototype action paused for a review: the build stays in Blueprint (api.md 3.0). */
const inBlueprint = () =>
  patchMockBuild(id, { stage: 'blueprint', spec_version: null, artifacts: { context: 'confirmed', outline: 'confirmed', design: 'confirmed', blueprint: 'draft' } });

// The first workspace render of a file is slow under full-suite load: allow it more than the default 1 s.
const findPanel = () => screen.findByRole('region', { name: /^Review the design brief/ }, { timeout: 5000 });
const queryPanel = () => screen.queryByRole('region', { name: /^Review the design brief/ });
const approve = () => screen.getByRole('button', { name: 'Approve and generate HTML' });
const box = (name: string) => screen.getByRole('textbox', { name }) as HTMLTextAreaElement;
const overall = () => box('Overall');

async function openReview(pages: DesignPages = fixtures.designPagesReview) {
  inBlueprint();
  setMockDesignPages(id, pages);
  shell();
  return findPanel();
}

/** Types into a review field and leaves it (save on blur). */
function edit(field: HTMLTextAreaElement, value: string) {
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value } });
  fireEvent.blur(field);
}

/** Another window saves the review: the mock moves to the next revision. */
async function otherWindowSaves(change: Partial<BriefReview['brief']['brief']>) {
  const pages = await api.getDesignPages(id);
  const current = pages.review!;
  return api.saveBriefReview(id, { review_id: current.review_id, revision: current.revision, brief: { ...current.brief.brief, ...change } });
}

describe('Brief review panel', () => {
  it('lists Overall, then one Treatment per component with its label, type and id read-only', async () => {
    const panel = await openReview();
    expect(within(panel).getByRole('heading', { level: 2 }).textContent).toBe('Review the design brief · Page 1 of 2');
    expect(within(panel).getByText('HTML generation waits for you. Edit the design text; components and data stay fixed.')).toBeTruthy();
    const boxes = within(panel).getAllByRole('textbox') as HTMLTextAreaElement[];
    expect(boxes.map((b) => b.labels?.[0]?.textContent)).toEqual(['Overall', 'Treatment for Total access', 'Treatment for Yearly access']);
    expect(boxes.map((b) => b.value)).toEqual([review.brief.brief.overall, ...review.brief.brief.slots.map((s) => s.treatment)]);
    review.components.forEach((component) => {
      const block = within(panel).getByRole('group', { name: component.label });
      expect(within(block).getByText(component.id)).toBeTruthy();
      expect(within(block).getByText(component.type)).toBeTruthy();
      // Only the treatment is editable: id, type and label are text.
      expect(within(block).getAllByRole('textbox')).toHaveLength(1);
      expect(within(block).queryByRole('combobox')).toBeNull();
    });
    expect(within(panel).getByText('No open issues')).toBeTruthy();
    expect(off(approve())).toBe(false);
    expect(off(within(panel).getByRole('button', { name: 'Cancel run' }))).toBe(false);
    expect(within(panel).getByRole('button', { name: 'Download .md' })).toBeTruthy();
  });

  it('saves on blur one PUT at a time, and a late response never overwrites newer typing', async () => {
    await openReview();
    const real = api.saveBriefReview;
    let release: () => void = () => {};
    const save = vi.spyOn(api, 'saveBriefReview');
    save.mockImplementationOnce((buildId, body) => new Promise<BriefReview>((resolve) => { release = () => resolve(real(buildId, body)); }));
    edit(overall(), 'First text');
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0]![1]).toEqual({ review_id: review.review_id, revision: 1, brief: { ...review.brief.brief, overall: 'First text' } });
    expect(off(approve())).toBe(true);
    // Newer typing while the first PUT is out: it waits for that one.
    edit(overall(), 'Second text');
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => release());
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(overall().value).toBe('Second text');
    expect(save.mock.calls[1]![1]).toMatchObject({ revision: 2, brief: { overall: 'Second text' } });
    await waitFor(() => expect(off(approve())).toBe(false));
    expect(overall().value).toBe('Second text');
  });

  it('shows an issue under its Treatment and the whole-brief issue above the form, and disables Approve', async () => {
    const panel = await openReview(fixtures.designPagesReviewIssue);
    const [slotIssue, briefIssue] = fixtures.designPagesReviewIssue.review!.issues;
    const first = box('Treatment for Total access');
    expect(first.getAttribute('aria-invalid')).toBe('true');
    expect(document.getElementById(first.getAttribute('aria-describedby')!)?.textContent).toBe(slotIssue!.message);
    expect(box('Treatment for Yearly access').getAttribute('aria-invalid')).toBeNull();
    const whole = within(panel).getByText(briefIssue!.message);
    expect(whole.compareDocumentPosition(overall()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(panel).getByText('2 open issues')).toBeTruthy();
    expect(off(approve())).toBe(true);
  });

  it('Save sends the current revision; Approve posts {review_id, revision, sha256} once and its run shows a new run card', async () => {
    await openReview();
    const save = vi.spyOn(api, 'saveBriefReview');
    edit(box('Treatment for Yearly access'), 'Full-width card, thin gridlines.');
    expect(save.mock.calls[0]![1].revision).toBe(1);
    const saved = (await save.mock.results[0]!.value) as BriefReview;
    expect(saved.revision).toBe(2);
    await waitFor(() => expect(off(approve())).toBe(false));
    const post = vi.spyOn(api, 'approveBriefReview').mockResolvedValue({ run_id: 'r_reviewed' });
    fireEvent.click(approve());
    fireEvent.click(approve());
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith(id, { review_id: review.review_id, revision: 2, sha256: saved.brief.sha256 });
    await waitFor(() => expect(queryPanel()).toBeNull());
    expect(document.activeElement?.tagName).toBe('MAIN');
    act(() => emit(id, { name: 'run.started', data: { run_id: 'r_reviewed', node: 'prototype' } }));
    await waitFor(() => expect(document.querySelector('[data-run-card="r_reviewed"]')).not.toBeNull(), { timeout: 2000 });
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('a 409 brief_review_conflict on Approve refetches, shows the note with the new text, and needs a new click', async () => {
    await openReview();
    await otherWindowSaves({ overall: 'Changed in the other window.' });
    const post = vi.spyOn(api, 'approveBriefReview');
    const read = vi.spyOn(api, 'getDesignPages');
    fireEvent.click(approve());
    await screen.findByText(CONFLICT);
    expect(read).toHaveBeenCalled();
    await waitFor(() => expect(overall().value).toBe('Changed in the other window.'));
    expect(post).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(off(approve())).toBe(false));
    fireEvent.click(approve());
    expect(post).toHaveBeenCalledTimes(2);
    expect(post.mock.calls[1]![1].revision).toBe(2);
    await waitFor(() => expect(queryPanel()).toBeNull());
  });

  it('a 409 brief_review_conflict on save keeps only the unsaved typing, flagged, and takes the rest from the server', async () => {
    const panel = await openReview();
    await otherWindowSaves({ overall: 'Changed in the other window.' });
    const save = vi.spyOn(api, 'saveBriefReview');
    edit(box('Treatment for Yearly access'), 'My unsaved treatment');
    await within(panel).findByText(CONFLICT);
    await waitFor(() => expect(overall().value).toBe('Changed in the other window.'));
    const mine = box('Treatment for Yearly access');
    expect(mine.value).toBe('My unsaved treatment');
    expect(within(panel).getByText(/Not saved yet/)).toBeTruthy();
    expect(off(approve())).toBe(true);
    // Leaving the field again saves it on the new revision.
    fireEvent.focus(mine);
    fireEvent.blur(mine);
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1]![1]).toMatchObject({ revision: 2, brief: { overall: 'Changed in the other window.' } });
    await waitFor(() => expect(off(approve())).toBe(false));
    expect(within(panel).queryByText(/Not saved yet/)).toBeNull();
  });

  it('Cancel asks to confirm, posts cancel, refetches the build and returns focus', async () => {
    const panel = await openReview();
    const cancel = vi.spyOn(api, 'cancelBriefReview');
    const getBuild = vi.spyOn(api, 'getBuild');
    const button = within(panel).getByRole('button', { name: 'Cancel run' });
    button.focus();
    fireEvent.click(button);
    let dialog = screen.getByRole('dialog', { name: 'Discard this prototype run?' });
    expect(within(dialog).getByText('Nothing is published; pending comments stay.')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep reviewing' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(button);
    expect(cancel).not.toHaveBeenCalled();
    fireEvent.click(button);
    dialog = screen.getByRole('dialog', { name: 'Discard this prototype run?' });
    const before = getBuild.mock.calls.length;
    fireEvent.click(within(dialog).getByRole('button', { name: 'Discard run' }));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith(id, review.review_id));
    await waitFor(() => expect(queryPanel()).toBeNull());
    expect(getBuild.mock.calls.length).toBeGreaterThan(before);
    expect(document.activeElement?.tagName).toBe('MAIN');
    // The lock is gone with the review.
    await waitFor(() => expect(off(screen.getByRole('button', { name: 'Regenerate' }))).toBe(false));
  });

  it('a stale review shows the warning with only Cancel enabled', async () => {
    const panel = await openReview(withReview({ stale: true }));
    expect(within(panel).getByText(STALE)).toBeTruthy();
    within(panel).getAllByRole('textbox').forEach((field) => expect(off(field)).toBe(true));
    expect(off(approve())).toBe(true);
    expect(off(within(panel).getByRole('button', { name: 'Cancel run' }))).toBe(false);
  });

  it('a 409 brief_review_stale on Approve shows the stale warning with only Cancel enabled', async () => {
    const panel = await openReview();
    setMockDesignPages(id, withReview({ stale: true }));
    fireEvent.click(approve());
    await within(panel).findByText(STALE);
    within(panel).getAllByRole('textbox').forEach((field) => expect(off(field)).toBe(true));
    expect(off(approve())).toBe(true);
    expect(off(within(panel).getByRole('button', { name: 'Cancel run' }))).toBe(false);
  });

  it('survives a remount: the panel comes back from GET design-pages with the saved text', async () => {
    await openReview();
    const save = vi.spyOn(api, 'saveBriefReview');
    edit(overall(), 'Saved before the reload.');
    await save.mock.results[0]!.value;
    await waitFor(() => expect(off(approve())).toBe(false));
    cleanup();
    shell();
    await findPanel();
    expect(overall().value).toBe('Saved before the reload.');
  });
});

describe('Review lock', () => {
  const ratio = mockRatioIssue();
  /** A run paused for a review: the mock holds it and the stream announces it. */
  const pause = (action: BriefReview['action'] = 'prototype') => {
    setMockDesignPages(id, withReview({ action }));
    act(() => emit(id, { name: 'brief.review', data: { review_id: review.review_id, page: 1, pages: 2 } }));
  };
  const blocked: Assessment = { id: 'assessment_ratio', state: 'blocked', input_digest: 'digest_ratio', prototype_stale: false, issues: [ratio], pending_comments: null };

  it('in Blueprint: Accept and Regenerate go from enabled to waiting for the review; Settings still opens', async () => {
    const settings = vi.fn();
    inBlueprint();
    shell(settings);
    const accept = await screen.findByRole('button', { name: 'Accept blueprint' });
    await waitFor(() => expect(off(accept)).toBe(false));
    expect(off(screen.getByRole('button', { name: 'Regenerate' }))).toBe(false);
    expect(screen.queryByText(WAIT)).toBeNull();
    pause();
    await findPanel();
    expect(off(screen.getByRole('button', { name: 'Accept blueprint' }))).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Regenerate' }))).toBe(true);
    expect(within(screen.getByRole('main')).getAllByText(WAIT).length).toBeGreaterThan(0);
    const open = screen.getByRole('button', { name: 'Settings' });
    expect(off(open)).toBe(false);
    fireEvent.click(open);
    expect(settings).toHaveBeenCalled();
  });

  it('feasibility decisions go from enabled to waiting for the review', async () => {
    setMockArtifact(id, 'blueprint', fixtures.blueprintBlocked);
    setMockAssessment(id, blocked);
    inBlueprint();
    shell();
    // The loading view has its own <main>: read the workspace's once the stage shows.
    const drop = await screen.findByRole('button', { name: 'Drop this requirement' });
    const main = screen.getByRole('main');
    fireEvent.click(within(main).getByRole('radio', { name: ratio.alternatives[0]!.label }));
    const use = within(main).getByRole('button', { name: 'Use this alternative' });
    await waitFor(() => expect(off(drop)).toBe(false));
    expect(off(use)).toBe(false);
    pause();
    await findPanel();
    expect(off(within(main).getByRole('button', { name: 'Drop this requirement' }))).toBe(true);
    expect(off(within(main).getByRole('button', { name: 'Use this alternative' }))).toBe(true);
    expect(within(main).getAllByText(WAIT).length).toBeGreaterThan(0);
  });

  it('reference Replace (a file picked) and Remove (a saved set) go from enabled to waiting for the review', async () => {
    await api.uploadReferences(id, [new File(['image'], 'style.png', { type: 'image/png' })], 'style', '');
    await waitFor(async () => expect(await api.getReferences(id)).not.toBeNull());
    inBlueprint();
    shell();
    const remove = await screen.findByRole('button', { name: 'Remove references' });
    const main = screen.getByRole('main');
    fireEvent.change(within(main).getByLabelText('Reference images'), { target: { files: [new File(['image'], 'other.png', { type: 'image/png' })] } });
    const replace = within(main).getByRole('button', { name: 'Replace references' });
    await waitFor(() => expect(off(replace)).toBe(false));
    expect(off(remove)).toBe(false);
    pause();
    await findPanel();
    expect(off(within(main).getByRole('button', { name: 'Replace references' }))).toBe(true);
    expect(off(within(main).getByRole('button', { name: 'Remove references' }))).toBe(true);
    expect(within(main).getAllByText(WAIT).length).toBeGreaterThan(0);
  });

  it('a reopened artifact editor is disabled while the review waits', async () => {
    inBlueprint();
    setMockDesignPages(id, fixtures.designPagesReview);
    shell();
    await findPanel();
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: /^.?Context/ }));
    const goal = await screen.findByDisplayValue(fixtures.context.goal);
    expect(off(goal)).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Redraft' }))).toBe(true);
    expect(screen.getAllByText(WAIT).length).toBeGreaterThan(0);
  });

  it('in Prototype: a brief.review pause disables Apply comments, the audit and Continue to build', async () => {
    shell();
    const next = await screen.findByRole('button', { name: 'Continue to build' });
    await waitFor(() => expect(off(next)).toBe(false));
    const frame = screen.getByTitle(/^Prototype of /) as HTMLIFrameElement;
    loadPrototype(frame);
    fireEvent.click(await screen.findByRole('button', { name: 'Comment on Revenue (scorecard)' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Comment' }), { target: { value: 'Make this bigger' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    const applyButton = screen.getByRole('button', { name: 'Apply 1 comment' });
    expect(off(applyButton)).toBe(false);
    setMockDesignPages(id, withReview({ action: 'revise' }));
    act(() => emit(id, { name: 'brief.review', data: { review_id: review.review_id, page: 1, pages: 2 } }));
    // Locked in the event's own render, before the refetch lands.
    expect(off(screen.getByRole('button', { name: 'Apply 1 comment' }))).toBe(true);
    await findPanel();
    expect(off(screen.getByRole('button', { name: 'Apply 1 comment' }))).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Run UX audit' }))).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Continue to build' }))).toBe(true);
    expect(screen.getAllByText(WAIT).length).toBeGreaterThan(0);
  });

  it('in the Build view: Generate recipe and Build wait for the review', async () => {
    shell();
    const next = await screen.findByRole('button', { name: 'Continue to build' });
    await waitFor(() => expect(off(next)).toBe(false));
    fireEvent.click(next);
    const generate = await screen.findByRole('button', { name: 'Generate recipe' });
    await waitFor(() => expect(off(generate)).toBe(false));
    fireEvent.click(generate);
    // With a recipe, both Regenerate (the recipe) and Build are on before the pause.
    const recipeAgain = await screen.findByRole('button', { name: 'Regenerate' });
    await waitFor(() => expect(off(screen.getByRole('button', { name: 'Build in Data Studio' }))).toBe(false));
    expect(off(recipeAgain)).toBe(false);
    pause('revise');
    await findPanel();
    expect(off(screen.getByRole('button', { name: 'Regenerate' }))).toBe(true);
    expect(off(screen.getByRole('button', { name: 'Build in Data Studio' }))).toBe(true);
    expect(screen.getAllByText(WAIT).length).toBeGreaterThan(0);
  });

  it('a 409 brief_review_pending from any action refetches design-pages and shows the panel', async () => {
    inBlueprint();
    shell();
    const regenerate = await screen.findByRole('button', { name: 'Regenerate' });
    await waitFor(() => expect(off(regenerate)).toBe(false));
    expect(queryPanel()).toBeNull();
    // Paused in another window: this one never saw brief.review.
    setMockDesignPages(id, fixtures.designPagesReview);
    const read = vi.spyOn(api, 'getDesignPages');
    fireEvent.click(regenerate);
    await findPanel();
    expect(read).toHaveBeenCalled();
    expect(off(screen.getByRole('button', { name: 'Regenerate' }))).toBe(true);
  });

  it('the routes outside the run lock answer brief_review_pending too (references, audit, comments)', async () => {
    setMockDesignPages(id, fixtures.designPagesReview);
    const pending = (call: Promise<unknown>) => expect(call).rejects.toMatchObject({ status: 409, code: 'brief_review_pending', detail: { review_id: review.review_id } });
    await pending(api.deleteReferences(id));
    await pending(api.runAudit(id));
    await pending(api.postComments(id, [{ component_id: 'c_x', text: 'x' }]));
    await pending(api.uploadSources(id, [new File(['a'], 'a.csv', { type: 'text/csv' })]));
  });
});

const rect = (left: number, top: number, width: number, height: number) =>
  ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;

/** Writes the contract prototype into the iframe and stubs the boxes jsdom cannot lay out. */
function loadPrototype(frame: HTMLIFrameElement) {
  const doc = frame.contentDocument!;
  doc.open();
  doc.write(fixtures.prototypeHtml);
  doc.close();
  const canvas = doc.getElementById('dss-canvas');
  if (canvas) canvas.getBoundingClientRect = () => rect(0, 0, 1200, 900);
  doc.querySelectorAll<HTMLElement>('[data-cid]').forEach((el) => {
    const px = (name: 'left' | 'top' | 'width' | 'height') => parseFloat(el.style[name]);
    el.getBoundingClientRect = () => rect(px('left'), px('top'), px('width'), px('height'));
  });
  fireEvent.load(frame);
}

