import { useLayoutEffect, useMemo, useRef, useState, type SyntheticEvent } from 'react';
import { ErrorState } from '../../../components/ErrorState';
import { focusRing } from '../../../components/focus';
import { Pin } from '../../../components/Pin';
import { LoadingState } from '../../../components/Spinner';
import { CommentPopover } from './CommentPopover';
import type { PendingComment, Target } from './types';

interface Size {
  width: number;
  height: number;
}

/** The prototype page is 1200 px wide (contracts/api.md, Prototype HTML). */
const CANVAS_WIDTH = 1200;
const CANVAS_HEIGHT = 900;

/**
 * Reads the canvas size and every `[data-cid]` box from the loaded iframe document. Read only:
 * nothing is injected into the page. Null when the page is not what we expect.
 */
function readPage(frame: HTMLIFrameElement): { size: Size; targets: Target[] } | null {
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
  const targets: Target[] = elements.map((el) => {
    const rect = el.getBoundingClientRect();
    const cid = el.getAttribute('data-cid') ?? '';
    return {
      cid,
      label: el.getAttribute('data-label') ?? cid,
      kind: el.getAttribute('data-kind') ?? 'component',
      // Iframe viewport coordinates: the pin layer covers the iframe from its (0,0), wherever the canvas sits.
      box: { left: rect.left + view.x, top: rect.top + view.y, width: rect.width, height: rect.height },
    };
  });
  // The frame spans the canvas plus any offset before it, and every box (pages may stack below).
  const right = Math.max(origin.width > 0 ? origin.right + view.x : CANVAS_WIDTH, ...targets.map((t) => t.box.left + t.box.width));
  const bottom = Math.max(origin.bottom + view.y, ...targets.map((t) => t.box.top + t.box.height));
  const width = right;
  const height = bottom;
  return { size: { width, height }, targets };
}

type Read = { token: string; targets: Target[] | null };

interface PrototypeCanvasProps {
  url: string;
  title: string;
  pending: PendingComment[];
  /** Targets cannot be clicked (a batch is being applied). */
  disabled: boolean;
  /** The pending comment whose list row is hovered or focused. */
  hoveredId: number | null;
  onAdd: (target: Target, text: string) => void;
  /** The component ids found in the page after each read. */
  onRead: (cids: Set<string>) => void;
}

const byReading = (a: Target, b: Target) => a.box.top - b.box.top || a.box.left - b.box.left;

/**
 * The iframe, its overlay of clickable targets and pins, and the comment card. One scaled wrapper
 * holds the iframe and the pin layer, so both share the canvas coordinates at any stage width.
 */
export function PrototypeCanvas({ url, title, pending, disabled, hoveredId, onAdd, onRead }: PrototypeCanvasProps) {
  const [attempt, setAttempt] = useState(0);
  const [read, setRead] = useState<Read | null>(null);
  // Kept across reloads so the reserved height does not jump.
  const [size, setSize] = useState<Size>({ width: CANVAS_WIDTH, height: CANVAS_HEIGHT });
  const [outerWidth, setOuterWidth] = useState(0);
  const [hover, setHover] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const outer = useRef<HTMLDivElement>(null);

  const token = `${attempt}|${url}`;
  const current = read?.token === token ? read : null;
  const targets = useMemo(() => current?.targets ?? [], [current]);
  const failed = current !== null && current.targets === null;
  const loading = current === null;

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

  const onLoad = (event: SyntheticEvent<HTMLIFrameElement>) => {
    const page = readPage(event.currentTarget);
    setOpen(null);
    setHover(null);
    setFocused(null);
    if (!page) {
      setRead({ token, targets: null });
      onRead(new Set());
      return;
    }
    setSize(page.size);
    setRead({ token, targets: page.targets });
    onRead(new Set(page.targets.map((t) => t.cid)));
  };

  const ordered = useMemo(() => [...targets].sort(byReading), [targets]);
  // Smaller boxes sit above larger ones, so a chart is reachable over the panel behind it.
  const layer = useMemo(() => {
    const ranks = new Map<string, number>();
    [...targets].sort((a, b) => b.box.width * b.box.height - a.box.width * a.box.height).forEach((t, i) => ranks.set(t.cid, i + 1));
    return ranks;
  }, [targets]);
  const top = targets.length + 2;

  const shown = targets.find((t) => t.cid === (hover ?? focused)) ?? null;
  const opened = targets.find((t) => t.cid === open) ?? null;
  const counter = { transform: `scale(${1 / scale})`, transformOrigin: '0 0' } as const;

  const pins = pending.flatMap((comment, index) => {
    const target = targets.find((t) => t.cid === comment.component_id);
    if (!target) return [];
    const slot = pending.slice(0, index).filter((c) => c.component_id === comment.component_id).length;
    return [{ comment, n: index + 1, target, slot }];
  });

  return (
    <div ref={outer} className="relative w-full" style={{ height: size.height * scale }}>
      <div
        data-testid="prototype-scale"
        className="absolute left-0 top-0 bg-surface ring-1 ring-border"
        style={{ width: size.width, height: size.height, transform: `scale(${scale})`, transformOrigin: '0 0' }}
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
          {ordered.map((target) => (
            <button
              key={target.cid}
              type="button"
              aria-label={`Comment on ${target.label}`}
              disabled={disabled}
              onMouseEnter={() => setHover(target.cid)}
              onMouseLeave={() => setHover(null)}
              onFocus={(event) => {
                let visible = true;
                try {
                  visible = event.currentTarget.matches(':focus-visible');
                } catch {
                  /* keep the label */
                }
                if (visible) setFocused(target.cid);
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
          {pins.map(({ comment, n, target, slot }) => (
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
          anchor={{ left: opened.box.left * scale, top: opened.box.top * scale, bottom: (opened.box.top + opened.box.height) * scale }}
          outerWidth={outerWidth}
          outerHeight={size.height * scale}
          onClose={() => setOpen(null)}
          onAdd={(text) => {
            onAdd(opened, text);
            setOpen(null);
          }}
        />
      )}
    </div>
  );
}
