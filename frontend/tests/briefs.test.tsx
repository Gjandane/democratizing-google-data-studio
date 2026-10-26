import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { OpenBuildEvents, StreamHandlers } from '../src/api/events';
import type { Build, BuildEvent, DesignPage, DesignPages } from '../src/api/types';
import { useBuildStream } from '../src/features/activity/useBuildStream';
import { PrototypeStage } from '../src/features/workspace/prototype/PrototypeStage';
import { fixtures } from '../src/mocks/fixtures';
import { resetMockState, setMockDesignPages } from '../src/mocks/api';

beforeEach(() => resetMockState());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

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

/** Writes a prototype into the iframe and stubs the section and component boxes jsdom cannot lay out. */
function loadPages(html: string) {
  const frame = screen.getByTitle(/^Prototype of /) as HTMLIFrameElement;
  const doc = frame.contentDocument!;
  doc.open();
  doc.write(html);
  doc.close();
  let top = 0;
  for (const section of Array.from(doc.querySelectorAll<HTMLElement>('section[data-page]'))) {
    const pageTop = top;
    const height = parseFloat(section.style.height);
    section.getBoundingClientRect = () => rect(0, pageTop, 1200, height);
    section.querySelectorAll<HTMLElement>('[data-cid]').forEach((el) => {
      const px = (name: 'left' | 'top' | 'width' | 'height') => parseFloat(el.style[name]);
      el.getBoundingClientRect = () => rect(px('left'), pageTop + px('top'), px('width'), px('height'));
    });
    top += height;
  }
  doc.getElementById('dss-canvas')!.getBoundingClientRect = () => rect(0, 0, 1200, top);
  fireEvent.load(frame);
}

const pageNames = (html: string) =>
  Array.from(new DOMParser().parseFromString(html, 'text/html').querySelectorAll('section[data-page]')).map((s) => s.getAttribute('data-page-name')!);
const [firstName, secondName] = pageNames(fixtures.prototypeMultipageHtml) as [string, string];

async function setup({ pages = fixtures.designPages, html = fixtures.prototypeMultipageHtml }: { pages?: DesignPages; html?: string } = {}) {
  const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
  const build: Build = { ...(await api.getBuild(created.id)), stage: 'prototype', spec_version: 5 };
  setMockDesignPages(build.id, pages);
  const stream = fakeStream();
  render(<Holder initial={build} open={stream.open} />);
  loadPages(html);
  return { build, ...stream };
}

const tab = (name: string) => within(screen.getByRole('tablist', { name: 'Prototype pages' })).getByRole('tab', { name: new RegExp(`^${name}`) });
const briefButton = () => screen.getByRole('button', { name: 'Design brief' });
const panel = () => screen.getByRole('region', { name: 'Design brief' });
const withPage = (n: number, change: Partial<DesignPage>): DesignPages => ({
  ...fixtures.designPages,
  pages: fixtures.designPages.pages.map((p) => (p.page === n ? { ...p, ...change } : p)),
});

describe('Design brief panel', () => {
  it('renders the saved brief markdown, its meta line and download links', async () => {
    const { build } = await setup();
    expect(briefButton().getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(briefButton());
    expect(briefButton().getAttribute('aria-expanded')).toBe('true');
    const region = panel();
    // The fixture markdown, rendered: its headings and text.
    expect(await within(region).findByRole('heading', { name: 'Page 1 brief' })).toBeTruthy();
    expect(within(region).getByRole('heading', { name: 'Overall' })).toBeTruthy();
    expect(within(region).getByRole('heading', { name: 'c_trend (time_series: Yearly access)' })).toBeTruthy();
    expect(region.textContent).toContain('Full-width card titled');
    const record = fixtures.designPages.pages[0]!.brief!;
    expect(within(region).getByTestId('brief-meta').textContent).toBe(
      `Brief by ${record.model} · HTML by ${fixtures.designPages.pages[0]!.html_model} · Generated · ${record.sha256.slice(0, 8)}`,
    );
    const md = within(region).getByRole('link', { name: 'Download .md' });
    const json = within(region).getByRole('link', { name: 'Download .json' });
    expect(md.getAttribute('href')).toBe(`/api/builds/${build.id}/files/brief_p1.md`);
    expect(json.getAttribute('href')).toBe(`/api/builds/${build.id}/files/brief_p1.json`);
    expect(md.hasAttribute('download')).toBe(true);
    expect(json.hasAttribute('download')).toBe(true);
    // A designed page has no standard layout note.
    expect(region.textContent).not.toContain('standard layout');
  });

  it('never renders raw HTML or loads images from the markdown', async () => {
    const page = fixtures.designPages.pages[0]!;
    const markdown = '# Unsafe brief\n\n<b>bold html</b> <script>window.hacked = true</script>\n\n<img src="https://example.com/x.png" alt="html image">\n\n![tracking pixel](https://example.com/p.png)\n';
    await setup({ pages: withPage(1, { brief: { ...page.brief!, markdown, origin: 'edited' } }) });
    fireEvent.click(briefButton());
    const region = panel();
    expect(await within(region).findByRole('heading', { name: 'Unsafe brief' })).toBeTruthy();
    expect(region.querySelector('b, script, img')).toBeNull();
    expect((window as unknown as { hacked?: boolean }).hacked).toBeUndefined();
    expect(within(region).getByTestId('brief-meta').textContent).toContain('· Edited ·');
  });

  it('page 2 shows a Standard layout chip on its tab and the layout_fallback note', async () => {
    await setup();
    await waitFor(() => expect(tab(secondName).textContent).toContain('Standard layout'));
    expect(tab(firstName).textContent).not.toContain('Standard layout');
    fireEvent.click(briefButton());
    fireEvent.click(tab(secondName));
    const region = panel();
    expect(await within(region).findByRole('heading', { name: 'Page 2 brief' })).toBeTruthy();
    expect(region.textContent).toContain(
      'The designed page still failed its checks after its repairs, so this page uses the standard layout (switch in Settings, HTML without a reference)',
    );
    expect(within(region).getByRole('link', { name: 'Download .md' }).getAttribute('href')).toMatch(/\/files\/brief_p2\.md$/);
  });

  it('a not_designed page says it uses the standard layout', async () => {
    await setup({ pages: withPage(2, { standard_reason: 'not_designed', brief: null, html_model: null }) });
    fireEvent.click(briefButton());
    fireEvent.click(tab(secondName));
    const region = panel();
    expect(await within(region).findByText('This page uses the standard layout.')).toBeTruthy();
    expect(within(region).getByText('No saved brief for this page')).toBeTruthy();
  });

  it('a page with a null brief says there is no saved brief and offers no downloads', async () => {
    await setup({ pages: withPage(1, { brief: null }) });
    fireEvent.click(briefButton());
    const region = panel();
    expect(await within(region).findByText('No saved brief for this page')).toBeTruthy();
    expect(within(region).queryByRole('link')).toBeNull();
  });

  it('a one-page prototype still offers the brief of page 1', async () => {
    await setup({ html: fixtures.prototypeHtml });
    expect(screen.queryByRole('tablist')).toBeNull();
    fireEvent.click(briefButton());
    expect(await within(panel()).findByRole('heading', { name: 'Page 1 brief' })).toBeTruthy();
  });

  it('a one-page standard prototype shows the chip beside the Design brief button', async () => {
    await setup({ html: fixtures.prototypeHtml, pages: withPage(1, { layout: 'standard', standard_reason: 'not_designed' }) });
    expect(await screen.findByText('Standard layout')).toBeTruthy();
    expect(screen.queryByRole('tablist')).toBeNull();
  });

  it('Esc and Close close the panel and return focus to the button', async () => {
    await setup();
    fireEvent.click(briefButton());
    await within(panel()).findByRole('heading', { name: 'Page 1 brief' });
    fireEvent.keyDown(panel(), { key: 'Escape' });
    expect(screen.queryByRole('region', { name: 'Design brief' })).toBeNull();
    expect(document.activeElement).toBe(briefButton());
    fireEvent.click(briefButton());
    fireEvent.click(within(panel()).getByRole('button', { name: 'Close design brief' }));
    expect(screen.queryByRole('region', { name: 'Design brief' })).toBeNull();
    expect(document.activeElement).toBe(briefButton());
  });

  it('a failed first load shows an error with a retry', async () => {
    const created = await api.createBuild({ archetype: 'executive', mode: 'data' });
    const build: Build = { ...(await api.getBuild(created.id)), stage: 'prototype', spec_version: 5 };
    setMockDesignPages(build.id, fixtures.designPages);
    const get = vi.spyOn(api, 'getDesignPages').mockRejectedValueOnce(new Error('down'));
    render(<Holder initial={build} open={fakeStream().open} />);
    loadPages(fixtures.prototypeMultipageHtml);
    fireEvent.click(briefButton());
    const retry = await within(panel()).findByRole('button', { name: 'Try again' });
    fireEvent.click(retry);
    expect(await within(panel()).findByRole('heading', { name: 'Page 1 brief' })).toBeTruthy();
    expect(get).toHaveBeenCalledTimes(2);
  });
});

describe('Design pages data', () => {
  it('refetches on prototype.updated, brief.review, a prototype/revise run.finished and reconnect only', async () => {
    const get = vi.spyOn(api, 'getDesignPages');
    const { build, fire } = await setup();
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    await fire({ name: 'prototype.updated', data: { spec_version: 6 } });
    expect(get).toHaveBeenCalledTimes(2);
    await fire({ name: 'brief.review', data: { review_id: 'br_1', page: 1, pages: 2 } });
    expect(get).toHaveBeenCalledTimes(3);
    await fire({ name: 'run.finished', data: { run_id: 'r_1', node: 'prototype', status: 'ok', error: null } });
    expect(get).toHaveBeenCalledTimes(4);
    await fire({ name: 'run.finished', data: { run_id: 'r_2', node: 'revise', status: 'error', error: 'x' } });
    expect(get).toHaveBeenCalledTimes(5);
    await fire({ name: 'run.finished', data: { run_id: 'r_3', node: 'context', status: 'ok', error: null } });
    await fire({ name: 'run.started', data: { run_id: 'r_4', node: 'prototype' } });
    expect(get).toHaveBeenCalledTimes(5);
    await fire({ name: 'ready', data: { build_id: build.id } });
    expect(get).toHaveBeenCalledTimes(6);
  });

  it('a background refetch keeps the panel content and the chip, also when it fails', async () => {
    const { fire } = await setup();
    fireEvent.click(briefButton());
    const region = panel();
    await within(region).findByRole('heading', { name: 'Page 1 brief' });
    await waitFor(() => expect(tab(secondName).textContent).toContain('Standard layout'));
    let fail: (reason: unknown) => void = () => {};
    vi.spyOn(api, 'getDesignPages').mockImplementation(() => new Promise((_resolve, reject) => (fail = reject)));
    await fire({ name: 'prototype.updated', data: { spec_version: 6 } });
    // In flight: the last content stays, no loading state replaces it.
    expect(within(region).getByRole('heading', { name: 'Page 1 brief' })).toBeTruthy();
    expect(within(region).queryByText(/Loading/)).toBeNull();
    expect(tab(secondName).textContent).toContain('Standard layout');
    await act(async () => fail(new Error('down')));
    expect(within(region).getByRole('heading', { name: 'Page 1 brief' })).toBeTruthy();
    expect(tab(secondName).textContent).toContain('Standard layout');
    expect(within(region).getByRole('alert').textContent).toContain("Couldn't refresh");
  });

  it('a refetch shows the new brief', async () => {
    const { build, fire } = await setup();
    fireEvent.click(briefButton());
    await within(panel()).findByRole('heading', { name: 'Page 1 brief' });
    const page = fixtures.designPages.pages[0]!;
    setMockDesignPages(build.id, withPage(1, { brief: { ...page.brief!, markdown: '# Page 1 brief, edited\n', origin: 'edited' } }));
    await fire({ name: 'run.finished', data: { run_id: 'r_1', node: 'revise', status: 'ok', error: null } });
    expect(await within(panel()).findByRole('heading', { name: 'Page 1 brief, edited' })).toBeTruthy();
  });
});
