import { useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type SyntheticEvent } from 'react';
import { ErrorState } from '../../../components/ErrorState';
import { focusRing } from '../../../components/focus';
import { Pin } from '../../../components/Pin';
import { LoadingState } from '../../../components/Spinner';
import { CommentPopover } from './CommentPopover';
import type { Page, PendingComment, Target } from './types';

interface Size {
  width: number;
  height: number;
}

/** The prototype page is 1200 px wide (contracts/api.md, Prototype HTML). */
const CANVAS_WIDTH = 1200;
const CANVAS_HEIGHT = 900;

/**
 * Reads the canvas size, its page sections and every `[data-cid]` box from the loaded iframe
 * document. Read only: nothing is injected into the page. Null when the page is not what we expect.
 */
function readPage(frame: HTMLIFrameElement): { size: Size; targets: Target[]; pages: Page[] } | null {
  let doc: Document | null = null;
  try {
    doc = frame.contentDocument;
  } catch {
    return null;
  }
  const canvas = doc?.getElementById('dss-canvas');
  if (!doc || !canvas) return null;
  const elements = Array.from(doc.querySelectorAll('[data-cid]'));
  if (elements.length === 0) return null;
  const origin = canvas.getBoundingClientRect();
  const view = { x: doc.defaultView?.scrollX ?? 0, y: doc.defaultView?.scrollY ?? 0 };
  const sections = Array.from(canvas.querySelectorAll('section[data-page]'));
  const targets: Target[] = elements.map((el) => {
    const rect = el.getBoundingClientRect();
    const cid = el.getAttribute('data-cid') ?? '';
    const section = el.closest('section[data-page]');
    return {
      cid,
      label: el.getAttribute('data-label') ?? cid,
      kind: el.getAttribute('data-kind') ?? 'component',
      page: section ? sections.indexOf(section) : null,
      // Iframe viewport coordinates: the pin layer covers the iframe from its (0,0), wherever the canvas sits.
      box: { left: rect.left + view.x, top: rect.top + view.y, width: rect.width, height: rect.height },
    };
  });
  // The frame spans the canvas plus any offset before it, and every box (pages may stack below).
  const right = Math.max(origin.width > 0 ? origin.right + view.x : CANVAS_WIDTH, ...targets.map((t) => t.box.left + t.box.width));
  const bottom = Math.max(origin.bottom + view.y, ...targets.map((t) => t.box.top + t.box.height));
  // One page per section, in document order (2.0); a page with no laid-out height spans its boxes.
  const pages: Page[] = sections.map((section, index) => {
    const rect = section.getBoundingClientRect();
    const own = targets.filter((t) => t.page === index);
    const top = rect.height > 0 ? rect.top + view.y : Math.min(...own.map((t) => t.box.top), bottom);
    const spanned = rect.height > 0 ? rect.height : Math.max(0, ...own.map((t) => t.box.top + t.box.height - top));
    // An empty section with no height still gets a page-sized frame, never a zero-height tab panel.
    const height = spanned > 0 ? spanned : CANVAS_HEIGHT;
    const n = Number(section.getAttribute('data-page'));
    return { index, n: Number.isInteger(n) && n > 0 ? n : index + 1, name: section.getAttribute('data-page-name')?.trim() || `Page ${index + 1}`, top, height };
  });
  return { size: { width: right, height: bottom }, targets, pages };
}

type Read = { token: string; targets: Target[] | null; pages: Page[] };

interface PrototypeCanvasProps {
  url: string;
  title: string;
  pending: PendingComment[];
  /** Targets cannot be clicked (a batch is being applied). */
  disabled: boolean;
  /** The pending comment whose list row is hovered or focused. */
  hoveredId: number | null;
  onAdd: (target: Target, text: string) => void;
  /** The component ids found in the page after each read, and each one's page name (only with 2+ pages). */
  onRead: (cids: Set<string>, pageNames: Map<string, string>) => void;
  /** A short status after a page's name on its tab, by its `data-page` number. */
  pageBadge?: (n: number) => ReactNode;
  /** Told the page shown: its `data-page` number (1 before the first read), its name, and whether page tabs show. */
  onPageShown?: (page: ShownPage) => void;
}

export interface ShownPage {
  n: number;
  name: string | null;
  tabbed: boolean;
}

const byReading = (a: Target, b: Target) => a.box.top - b.box.top || a.box.left - b.box.left;

/**
 * The iframe, its overlay of clickable targets and pins, and the comment card. One scaled wrapper
 * holds the iframe and the pin layer, so both share the canvas coordinates at any stage width.
 * A page with 2+ sections gets page tabs: the wrapper shows one section, and only its targets and pins.
 */
export function PrototypeCanvas({ url, title, pending, disabled, hoveredId, onAdd, onRead, pageBadge, onPageShown }: PrototypeCanvasProps) {
  const id = useId();
  const [attempt, setAttempt] = useState(0);
  const [read, setRead] = useState<Read | null>(null);
  // Kept across reloads so the reserved height does not jump.
  const [size, setSize] = useState<Size>({ width: CANVAS_WIDTH, height: CANVAS_HEIGHT });
  const [outerWidth, setOuterWidth] = useState(0);
  const [hover, setHover] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  // The chosen page by position; a new version keeps it when that page still exists.
  const [pageIndex, setPageIndex] = useState(0);
  const outer = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  const token = `${attempt}|${url}`;
  const current = read?.token === token ? read : null;
  const targets = useMemo(() => current?.targets ?? [], [current]);
  // The last read pages stay while the next version loads, so the tabs do not jump.
  const pages = read?.pages ?? [];
  const multi = pages.length > 1;
  const page = multi ? (pages[Math.min(pageIndex, pages.length - 1)] ?? null) : null;
  const failed = current !== null && current.targets === null;
  const loading = current === null;
  // One page (or none read yet) is page 1 unless its section says otherwise.
  const shownN = (page ?? pages[0])?.n ?? 1;
  const shownName = (page ?? pages[0])?.name ?? null;
  const tabbed = multi && page !== null;
  const pageShown = useRef(onPageShown);
  useLayoutEffect(() => {
    pageShown.current = onPageShown;
  });
  useLayoutEffect(() => {
    pageShown.current?.({ n: shownN, name: shownName, tabbed });
  }, [shownN, shownName, tabbed]);

  useLayoutEffect(() => {
    const node = outer.current;
    if (!node) return;
    setOuterWidth(node.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => setOuterWidth(node.clientWidth));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const scale = outerWidth > 0 ? Math.min(1, outerWidth / size.width) : 1;
  // The part of the canvas on screen: the chosen page, or all of it.
  const shownTop = page?.top ?? 0;
  const shownHeight = page?.height ?? size.height;

  const onLoad = (event: SyntheticEvent<HTMLIFrameElement>) => {
    const loaded = readPage(event.currentTarget);
    setOpen(null);
    setHover(null);
    setFocused(null);
    if (!loaded) {
      setRead({ token, targets: null, pages: [] });
      onRead(new Set(), new Map());
      return;
    }
    setSize(loaded.size);
    setRead({ token, targets: loaded.targets, pages: loaded.pages });
    if (pageIndex >= loaded.pages.length) setPageIndex(0);
    const names = new Map<string, string>();
    if (loaded.pages.length > 1) for (const t of loaded.targets) if (t.page !== null) names.set(t.cid, loaded.pages[t.page]!.name);
    onRead(new Set(loaded.targets.map((t) => t.cid)), names);
  };

  const onPage = (t: Target) => !page || t.page === page.index;
  const ordered = useMemo(() => [...targets].sort(byReading), [targets]);
  const visible = ordered.filter(onPage);
  // Smaller boxes sit above larger ones, so a chart is reachable over the panel behind it.
  const layer = useMemo(() => {
    const ranks = new Map<string, number>();
    [...targets].sort((a, b) => b.box.width * b.box.height - a.box.width * a.box.height).forEach((t, i) => ranks.set(t.cid, i + 1));
    return ranks;
  }, [targets]);
  const top = targets.length + 2;

  const shown = visible.find((t) => t.cid === (hover ?? focused)) ?? null;
  const opened = visible.find((t) => t.cid === open) ?? null;
  const counter = { transform: `scale(${1 / scale})`, transformOrigin: '0 0' } as const;

  // Pins keep their batch-wide numbers; each shows only on its own page.
  const pins = pending.flatMap((comment, index) => {
    const target = targets.find((t) => t.cid === comment.component_id);
    if (!target) return [];
    const slot = pending.slice(0, index).filter((c) => c.component_id === comment.component_id).length;
    return [{ comment, n: index + 1, target, slot }];
  });
  const shownPins = pins.filter((p) => onPage(p.target));
  const countOn = (index: number) => pins.filter((p) => p.target.page === index).length;

  const choose = (index: number) => {
    setPageIndex(index);
    setOpen(null);
    setHover(null);
    setFocused(null);
  };
  // Arrow keys move between tabs (WAI-ARIA tabs, automatic activation).
  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = pages.length - 1;
    const next = event.key === 'ArrowRight' ? (index === last ? 0 : index + 1)
      : event.key === 'ArrowLeft' ? (index === 0 ? last : index - 1)
      : event.key === 'Home' ? 0 : event.key === 'End' ? last : null;
    if (next === null) return;
    event.preventDefault();
    choose(next);
    tabs.current[next]?.focus();
  };

  return (
    <div className="flex min-w-0 flex-col gap-2">
      {multi && page && (
        <div role="tablist" aria-label="Prototype pages" className="flex min-w-0 gap-1 border-b border-border">
          {pages.map((p) => {
            const selected = p.index === page.index;
            const count = countOn(p.index);
            const badge = pageBadge?.(p.n);
            return (
              <button
                key={p.index}
                ref={(el) => {
                  tabs.current[p.index] = el;
                }}
                type="button"
                role="tab"
                id={`${id}-tab-${p.index}`}
                aria-selected={selected}
                aria-controls={`${id}-panel`}
                tabIndex={selected ? 0 : -1}
                title={p.name}
                onClick={() => choose(p.index)}
                onKeyDown={(event) => onTabKey(event, p.index)}
                className={`-mb-px flex h-9 min-w-0 ${badge ? 'max-w-96' : 'max-w-64'} items-center gap-2 rounded-t-control border-b-2 px-3 text-body ${focusRing} ${
                  selected ? 'border-primary font-semibold text-primary' : 'border-transparent text-text-muted hover:bg-surface-muted hover:text-text'
                }`}
              >
                <span className="truncate">{p.name}</span>
                {/* Fits the 36 px tab, so the row and the canvas below never move when it arrives. */}
                {badge && (
                  <>
                    <span className="sr-only">, </span>
                    {badge}
                  </>
                )}
                {count > 0 && (
                  <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-accent px-1.5 text-caption font-semibold text-on-accent tabular-nums">
                    <span className="sr-only">, </span>
                    {count}
                    <span className="sr-only"> {count === 1 ? 'comment' : 'comments'} on this page</span>
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
      <div
        ref={outer}
        id={`${id}-panel`}
        role={multi ? 'tabpanel' : undefined}
        aria-labelledby={multi && page ? `${id}-tab-${page.index}` : undefined}
        className="relative w-full"
        style={{ height: shownHeight * scale }}
      >
        {/* Clips the stacked pages to the chosen one; the comment card sits outside the clip. */}
        <div className={`absolute inset-0 ${multi ? 'overflow-hidden' : ''}`}>
        <div
          data-testid="prototype-scale"
          className="absolute left-0 bg-surface ring-1 ring-border"
          style={{ top: -shownTop * scale, width: size.width, height: size.height, transform: `scale(${scale})`, transformOrigin: '0 0' }}
        >
          <iframe
            key={token}
            src={url}
            title={title}
            scrolling="no"
            tabIndex={-1}
            onLoad={onLoad}
            className="block"
            style={{ border: 0, width: size.width, height: size.height }}
          />
          <div data-testid="prototype-pins" className="absolute inset-0">
            {visible.map((target) => (
              <button
                key={target.cid}
                type="button"
                aria-label={`Comment on ${target.label}`}
                disabled={disabled}
                onMouseEnter={() => setHover(target.cid)}
                onMouseLeave={() => setHover(null)}
                onFocus={(event) => {
                  let visibleFocus = true;
                  try {
                    visibleFocus = event.currentTarget.matches(':focus-visible');
                  } catch {
                    /* keep the label */
                  }
                  if (visibleFocus) setFocused(target.cid);
                }}
                onBlur={() => setFocused(null)}
                onClick={() => setOpen(target.cid)}
                className={`absolute bg-transparent enabled:cursor-pointer disabled:cursor-not-allowed ${focusRing}`}
                style={{ ...target.box, zIndex: layer.get(target.cid) }}
              />
            ))}
            {/* Disabled look while a batch is applied; pins stay on top of it. */}
            {disabled && <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-surface/40" style={{ zIndex: top }} />}
            {shown && !disabled && (
              <>
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute"
                  style={{
                    ...shown.box,
                    zIndex: top,
                    outline: `${2 / scale}px solid var(--color-primary)`,
                    outlineOffset: -2 / scale,
                  }}
                />
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute whitespace-nowrap bg-primary px-1.5 py-0.5 text-caption text-on-primary"
                  style={{ left: shown.box.left, top: shown.box.top, zIndex: top, ...counter }}
                >
                  {shown.label}
                </span>
              </>
            )}
            {shownPins.map(({ comment, n, target, slot }) => (
              <div
                key={comment.id}
                className="pointer-events-none absolute"
                style={{ left: target.box.left + target.box.width, top: target.box.top, zIndex: top + 1, ...counter }}
              >
                <Pin n={n} active={hoveredId === comment.id} className="absolute" style={{ top: '0.25rem', right: `${0.25 + slot * 1.75}rem` }} />
              </div>
            ))}
          </div>
        </div>
        </div>
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-surface">
            <LoadingState>Loading the prototype…</LoadingState>
          </div>
        )}
        {failed && (
          <div className="absolute inset-0 z-20 flex items-start justify-center bg-surface p-4">
            <ErrorState
              title="Couldn't read the prototype"
              message="The page didn't load as expected. Reload it to try again."
              retryLabel="Reload"
              onRetry={() => setAttempt((n) => n + 1)}
            />
          </div>
        )}
        {opened && (
          <CommentPopover
            label={opened.label}
            anchor={{ left: opened.box.left * scale, top: (opened.box.top - shownTop) * scale, bottom: (opened.box.top + opened.box.height - shownTop) * scale }}
            outerWidth={outerWidth}
            outerHeight={shownHeight * scale}
            onClose={() => setOpen(null)}
            onAdd={(text) => {
              onAdd(opened, text);
              setOpen(null);
            }}
          />
        )}
      </div>
    </div>
  );
}
