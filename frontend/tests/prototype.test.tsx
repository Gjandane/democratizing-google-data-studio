import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, httpApi } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import { ApiError, type Build, type BuildEvent } from '../src/api/types';
import { useBuildStream } from '../src/features/workspace/chat/useBuildStream';
import { PrototypeStage } from '../src/features/workspace/prototype/PrototypeStage';
import { fixtures } from '../src/mocks/fixtures';
import { resetMockState } from '../src/mocks/api';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** A fake stream: tests push events through the captured handlers. */
function fakeStream() {
  const handlers: StreamHandlers[] = [];
  const open: OpenBuildEvents = (_id, h) => {
    handlers.push(h);
    return () => {};
  };
  const fire = (event: BuildEvent) => act(() => handlers.forEach((h) => h.onEvent(event)));
  return { open, fire };
}

function Holder({ initial, open }: { initial: Build; open: OpenBuildEvents }) {
  const [build, setBuild] = useState(initial);
  const chat = useBuildStream(build, setBuild, open);
  return <PrototypeStage build={build} applying={chat.applying} commentsError={chat.commentsError} />;
}

const rect = (left: number, top: number, width: number, height: number) =>
  ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;

/** Writes the contract fixture into the iframe and stubs the boxes jsdom cannot lay out. */
function loadFrame(html: string = fixtures.prototypeHtml, canvas = true) {
  const frame = screen.getByTitle(/^Prototype of /) as HTMLIFrameElement;
  const doc = frame.contentDocument!;
  doc.open();
  doc.write(html);
  doc.close();
  const canvasEl = doc.getElementById('dss-canvas');
  if (canvasEl && canvas) canvasEl.getBoundingClientRect = () => rect(0, 0, 1200, 900);
  doc.querySelectorAll<HTMLElement>('[data-cid]').forEach((el) => {
    const px = (name: 'left' | 'top' | 'width' | 'height') => parseFloat(el.style[name]);
    el.getBoundingClientRect = () => rect(px('left'), px('top'), px('width'), px('height'));
  });
  fireEvent.load(frame);
  return frame;
}

async function setup() {
  const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
  const build: Build = { ...(await api.getBuild(created.id)), stage: 'prototype', spec_version: 1 };
  const stream = fakeStream();
  render(<Holder initial={build} open={stream.open} />);
  const frame = loadFrame();
  return { build, frame, ...stream };
}

/** Clicks a target, types and adds the comment. */
function comment(label: string, text: string) {
  fireEvent.click(screen.getByRole('button', { name: `Comment on ${label}` }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Comment' }), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Add' }));
}

const pins = () => screen.getByTestId('prototype-pins');
const pinAnchor = (n: number) => within(pins()).getByRole('img', { name: `Comment ${n}` }).parentElement as HTMLElement;

describe('Prototype stage', () => {
  it('shows an empty state while there is no prototype', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    render(<Holder initial={{ ...(await api.getBuild(created.id)), stage: 'prototype', spec_version: null }} open={fakeStream().open} />);
    expect(screen.getByRole('heading', { level: 3, name: 'No prototype yet' })).toBeTruthy();
    expect(screen.queryByTitle(/^Prototype of /)).toBeNull();
  });

  it('shows the loading state until the iframe loads, then one button per data-cid', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    const build: Build = { ...(await api.getBuild(created.id)), stage: 'prototype', spec_version: 3 };
    const url = vi.spyOn(api, 'prototypeUrl');
    render(<Holder initial={build} open={fakeStream().open} />);
    const frame = screen.getByTitle(`Prototype of ${build.title}`) as HTMLIFrameElement;
    // The mock serves a blob URL where the browser has one; the version is the second argument.
    expect(url).toHaveBeenLastCalledWith(build.id, 3);
    expect(frame.getAttribute('src')).toBe(url.mock.results[0]?.value);
    expect(frame.getAttribute('scrolling')).toBe('no');
    expect(screen.getByRole('status').textContent).toContain('Loading the prototype');
    expect(screen.queryAllByRole('button', { name: /^Comment on / })).toHaveLength(0);
    loadFrame();
    expect(screen.queryByText('Loading the prototype…')).toBeNull();
    const count = fixtures.prototypeHtml.match(/data-cid=/g)!.length;
    expect(screen.getAllByRole('button', { name: /^Comment on / })).toHaveLength(count);
  });

  it('shows the data-label of a hovered target', async () => {
    await setup();
    expect(screen.queryByText('Revenue (scorecard)')).toBeNull();
    const target = screen.getByRole('button', { name: 'Comment on Revenue (scorecard)' });
    fireEvent.mouseEnter(target);
    expect(screen.getByText('Revenue (scorecard)')).toBeTruthy();
    fireEvent.mouseLeave(target);
    expect(screen.queryByText('Revenue (scorecard)')).toBeNull();
  });

  it('adds a comment: pin 1 sits at the top-right of that element and the list shows it', async () => {
    await setup();
    comment('Revenue (scorecard)', 'Make this bigger');
    const list = screen.getByRole('list', { name: 'Pending comments' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(list.textContent).toContain('Make this bigger');
    // p1_kpi_revenue is left:24 top:104 width:270 height:120 -> right edge 294.
    const anchor = pinAnchor(1);
    expect(anchor.style.left).toBe('294px');
    expect(anchor.style.top).toBe('104px');
    expect(screen.getByRole('button', { name: 'Apply 1 comment' })).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('offsets pins on the same element so they do not stack', async () => {
    await setup();
    comment('Orders (scorecard)', 'one');
    comment('Orders (scorecard)', 'two');
    const first = within(pins()).getByRole('img', { name: 'Comment 1' });
    const second = within(pins()).getByRole('img', { name: 'Comment 2' });
    expect(first.style.right).not.toBe(second.style.right);
  });

  it('renumbers the pins when a pending comment is removed', async () => {
    await setup();
    comment('Revenue (scorecard)', 'first');
    comment('Orders (scorecard)', 'second');
    expect(pinAnchor(2).style.left).toBe('588px');
    fireEvent.click(screen.getByRole('button', { name: 'Remove comment 1' }));
    expect(within(pins()).queryByRole('img', { name: 'Comment 2' })).toBeNull();
    // The remaining comment (Orders) is now pin 1, still at the Orders box.
    expect(pinAnchor(1).style.left).toBe('588px');
    expect(screen.getByRole('button', { name: 'Apply 1 comment' })).toBeTruthy();
  });

  it('applies two comments with their component_ids and disables while running', async () => {
    const { build, fire } = await setup();
    const post = vi.spyOn(api, 'postComments');
    comment('Revenue (scorecard)', 'first');
    comment('Top products (table)', 'second');
    const apply = screen.getByRole('button', { name: 'Apply 2 comments' }) as HTMLButtonElement;
    expect(apply.disabled).toBe(false);
    fireEvent.click(apply);
    expect(post).toHaveBeenCalledWith(build.id, [
      { component_id: 'p1_kpi_revenue', text: 'first' },
      { component_id: 'p1_top_products', text: 'second' },
    ]);
    const running = screen.getByRole('button', { name: 'Applying 2 comments…' }) as HTMLButtonElement;
    expect(running.disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Comment on Header band' }) as HTMLButtonElement).disabled).toBe(true);
    await fire({ name: 'run.started', data: { run_id: 'r_1', node: 'comments' } });
    expect((screen.getByRole('button', { name: 'Applying 2 comments…' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('on prototype.updated reloads the iframe at ?v=<new> and clears the applied pins', async () => {
    const { build, fire } = await setup();
    vi.spyOn(api, 'postComments').mockResolvedValue({ run_id: 'r_1' });
    // The real URL builder: under vitest the mock returns blob URLs, which carry no `v`.
    const url = vi.spyOn(api, 'prototypeUrl').mockImplementation(httpApi.prototypeUrl);
    comment('Revenue (scorecard)', 'first');
    fireEvent.click(screen.getByRole('button', { name: 'Apply 1 comment' }));
    await fire({ name: 'run.started', data: { run_id: 'r_1', node: 'comments' } });
    const before = (screen.getByTitle(`Prototype of ${build.title}`) as HTMLIFrameElement).getAttribute('src');
    await fire({ name: 'prototype.updated', data: { spec_version: 2 } });
    const frame = screen.getByTitle(`Prototype of ${build.title}`) as HTMLIFrameElement;
    expect(url).toHaveBeenLastCalledWith(build.id, 2);
    expect(frame.getAttribute('src')).not.toBe(before);
    expect(frame.getAttribute('src')).toMatch(/[?&]v=2(&|$)/);
    expect(screen.queryByRole('list', { name: 'Pending comments' })).toBeNull();
    expect(within(pins()).queryAllByRole('img')).toHaveLength(0);
    await fire({ name: 'run.finished', data: { run_id: 'r_1', node: 'comments', status: 'ok', error: null } });
    loadFrame();
    expect(screen.getByRole('button', { name: 'Apply 0 comments' }) as HTMLButtonElement).toHaveProperty('disabled', true);
    expect(screen.getByText('Click any part of the prototype to add a comment.')).toBeTruthy();
  });

  it('keeps the comments and shows the reason when the run fails, again on a repeat', async () => {
    const { fire } = await setup();
    vi.spyOn(api, 'postComments').mockResolvedValue({ run_id: 'r_1' });
    comment('Revenue (scorecard)', 'first');
    fireEvent.click(screen.getByRole('button', { name: 'Apply 1 comment' }));
    await fire({ name: 'run.started', data: { run_id: 'r_1', node: 'comments' } });
    await fire({ name: 'run.finished', data: { run_id: 'r_1', node: 'comments', status: 'error', error: 'The model timed out.' } });
    expect(screen.getByRole('alert').textContent).toContain('The model timed out.');
    expect(screen.getByRole('button', { name: 'Apply 1 comment' }) as HTMLButtonElement).toHaveProperty('disabled', false);
    // Retry; a second identical failure still ends the spinner.
    fireEvent.click(screen.getByRole('button', { name: 'Apply 1 comment' }));
    expect(screen.queryByRole('alert')).toBeNull();
    await fire({ name: 'run.started', data: { run_id: 'r_2', node: 'comments' } });
    await fire({ name: 'run.finished', data: { run_id: 'r_2', node: 'comments', status: 'error', error: 'The model timed out.' } });
    expect(screen.getByRole('alert').textContent).toContain('The model timed out.');
    expect(screen.getByRole('button', { name: 'Apply 1 comment' }) as HTMLButtonElement).toHaveProperty('disabled', false);
  });

  it('keeps the comments and shows the API message when posting is rejected', async () => {
    await setup();
    vi.spyOn(api, 'postComments').mockRejectedValue(new ApiError(409, 'wrong_stage', 'Open the Prototype stage first.'));
    comment('Revenue (scorecard)', 'first');
    fireEvent.click(screen.getByRole('button', { name: 'Apply 1 comment' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Open the Prototype stage first.');
    expect(screen.getByRole('list', { name: 'Pending comments' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Apply 1 comment' }) as HTMLButtonElement).toHaveProperty('disabled', false);
  });

  it('closes the popover on Esc, Cancel and returns focus to the target', async () => {
    await setup();
    const target = screen.getByRole('button', { name: 'Comment on Header band' });
    target.focus();
    fireEvent.click(target);
    expect(screen.getByRole('dialog', { name: 'Comment on Header band' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(target);
    fireEvent.click(target);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByRole('list', { name: 'Pending comments' })).toBeNull();
  });

  it('does not add a blank comment', async () => {
    await setup();
    fireEvent.click(screen.getByRole('button', { name: 'Comment on Header band' }));
    const add = screen.getByRole('button', { name: 'Add' }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    const box = screen.getByRole('textbox', { name: 'Comment' });
    fireEvent.change(box, { target: { value: '   ' } });
    expect(add.disabled).toBe(true);
    fireEvent.keyDown(box, { key: 'Enter', ctrlKey: true });
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.queryByRole('list', { name: 'Pending comments' })).toBeNull();
  });

  it('puts one scale() wrapper around both the iframe and the pin layer', async () => {
    const { frame } = await setup();
    const wrapper = screen.getByTestId('prototype-scale');
    expect(wrapper.style.transform).toMatch(/^scale\(/);
    expect(wrapper.contains(frame)).toBe(true);
    expect(wrapper.contains(pins())).toBe(true);
    expect(document.querySelectorAll('[style*="scale("]').length).toBeGreaterThanOrEqual(1);
    // The popover is outside the scaled wrapper, so its text is not scaled.
    fireEvent.click(screen.getByRole('button', { name: 'Comment on Header band' }));
    expect(wrapper.contains(screen.getByRole('dialog'))).toBe(false);
  });

  it('places the card below the element, never over its box', async () => {
    await setup();
    fireEvent.click(screen.getByRole('button', { name: 'Comment on Revenue (scorecard)' }));
    const card = screen.getByRole('dialog');
    // jsdom has no layout: the card's top is the element's bottom (104 + 120) plus the gap.
    expect(parseFloat(card.style.top)).toBeGreaterThanOrEqual(224);
    expect(parseFloat(card.style.left)).toBe(24);
  });

  it('supports the whole keyboard path: focus a target, Enter, type, Ctrl+Enter, apply', async () => {
    const { build } = await setup();
    const post = vi.spyOn(api, 'postComments').mockResolvedValue({ run_id: 'r_1' });
    const target = screen.getByRole('button', { name: 'Comment on Dashboard title' });
    target.focus();
    expect(document.activeElement).toBe(target);
    fireEvent.click(target); // Enter on a button fires click
    const box = screen.getByRole('textbox', { name: 'Comment' });
    expect(document.activeElement).toBe(box);
    fireEvent.change(box, { target: { value: 'Shorter title' } });
    fireEvent.keyDown(box, { key: 'Enter', ctrlKey: true });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(target);
    const apply = screen.getByRole('button', { name: 'Apply 1 comment' });
    apply.focus();
    fireEvent.click(apply);
    expect(post).toHaveBeenCalledWith(build.id, [{ component_id: 'p1_title', text: 'Shorter title' }]);
  });

  it('refuses more than 20 comments and says why', async () => {
    await setup();
    for (let i = 0; i < 21; i++) comment('Header band', `c${i}`);
    expect(screen.getByText('Apply at most 20 comments at a time.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Apply 21 comments' }) as HTMLButtonElement).toHaveProperty('disabled', true);
  });

  it('marks a comment whose element is not in the new version', async () => {
    const { fire } = await setup();
    comment('Revenue (scorecard)', 'first');
    await fire({ name: 'prototype.updated', data: { spec_version: 2 } });
    loadFrame(fixtures.prototypeHtml.replace('p1_kpi_revenue', 'p1_kpi_gone'));
    expect(screen.getByText(/Not in this version/)).toBeTruthy();
    expect(within(pins()).queryAllByRole('img')).toHaveLength(0);
  });

  it('shows the error state with Reload when the page cannot be read', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    render(<Holder initial={{ ...(await api.getBuild(created.id)), stage: 'prototype', spec_version: 1 }} open={fakeStream().open} />);
    loadFrame('<!doctype html><p>nothing here</p>');
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain("Couldn't read the prototype");
    const before = screen.getByTitle(/^Prototype of /);
    fireEvent.click(within(alert).getByRole('button', { name: 'Reload' }));
    const after = screen.getByTitle(/^Prototype of /);
    expect(after).not.toBe(before);
    expect(screen.getByRole('status').textContent).toContain('Loading the prototype');
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('falls back to 1200 wide and the lowest box when the canvas has no size', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    render(<Holder initial={{ ...(await api.getBuild(created.id)), stage: 'prototype', spec_version: 1 }} open={fakeStream().open} />);
    loadFrame(fixtures.prototypeHtml, false);
    const wrapper = screen.getByTestId('prototype-scale');
    expect(wrapper.style.width).toBe('1200px');
    expect(wrapper.style.height).toBe('872px'); // 572 + 300 of the lowest box
  });
});

describe('useBuildStream: comments run', () => {
  it('tracks applying and the error of a comments run', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    const { open, fire } = fakeStream();
    let latest: ReturnType<typeof useBuildStream> | null = null;
    function Probe() {
      const [build, setBuild] = useState(created as unknown as Build);
      latest = useBuildStream(build, setBuild, open);
      return null;
    }
    render(<Probe />);
    await fire({ name: 'run.started', data: { run_id: 'r_1', node: 'comments' } });
    expect(latest!.applying).toBe(true);
    await fire({ name: 'run.finished', data: { run_id: 'r_1', node: 'comments', status: 'error', error: null } });
    expect(latest!.applying).toBe(false);
    expect(latest!.commentsError?.text).toBe("Couldn't apply the comments. Try again.");
    const seq = latest!.commentsError!.seq;
    await fire({ name: 'run.started', data: { run_id: 'r_2', node: 'comments' } });
    expect(latest!.commentsError).toBeNull();
    await fire({ name: 'run.finished', data: { run_id: 'r_2', node: 'comments', status: 'error', error: null } });
    expect(latest!.commentsError!.seq).toBeGreaterThan(seq);
  });
});
