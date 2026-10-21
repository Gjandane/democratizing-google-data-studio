// User-chosen colors appear only here: as data swatches that carry their hex as text, and in the
// mini preview (docs/staged-ui.md). Both use inline style for those colors; everything else is tokens.
import type { DesignUpdate } from '../../../api/types';

const mono = 'font-mono text-caption text-text-muted';

/** A user or preset color as a data swatch, always with its hex (and an optional name) as text. */
export function Swatch({ color, name, small = false }: { color: string; name?: string; small?: boolean }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <span aria-hidden="true" className={`${small ? 'size-3' : 'size-4'} shrink-0 rounded-control border border-border`} style={{ backgroundColor: color }} />
      <code className={mono}>{name ? `${name} ${color}` : color}</code>
    </span>
  );
}

// Bar lengths of the preview's one bar chart, in palette order.
const BARS = [92, 74, 61, 48, 37, 28, 20, 14];

/** The Design at a glance: a header band, one scorecard and one bar chart, redrawn on every change. */
export function DesignPreview({ design }: { design: DesignUpdate }) {
  const compact = design.density === 'compact';
  const gap = compact ? 'gap-1.5 p-2' : 'gap-3 p-3';
  const font = { fontFamily: `"${design.font_family}", sans-serif` };
  return (
    <figure className="rounded-panel border border-border bg-surface p-3">
      <figcaption className="mb-2 flex items-baseline justify-between gap-2 text-label font-medium text-text">
        Preview
        <span className="font-normal text-text-muted">{design.page_structure === 'per_section' ? 'Page 1' : 'Single page'}</span>
      </figcaption>
      <div data-preview="" className={`flex flex-col overflow-hidden rounded-control border border-border ${gap}`} style={{ ...font, backgroundColor: design.background, color: design.text }}>
        <div className={`rounded-control border-b-4 ${compact ? 'px-2 py-1.5' : 'px-3 py-2'}`} style={{ backgroundColor: design.surface, borderBottomColor: design.accent }}>
          <p className="truncate text-body font-semibold">{design.title.trim() || 'Untitled dashboard'}</p>
          {design.subtitle && <p className="truncate text-caption opacity-75">{design.subtitle}</p>}
        </div>
        <div className={`rounded-control ${compact ? 'px-2 py-1.5' : 'px-3 py-2'}`} style={{ backgroundColor: design.surface }}>
          <p className="text-caption opacity-75">Net sales</p>
          <p className="text-heading font-semibold tabular-nums">1.24M</p>
          <span aria-hidden="true" className="mt-1 block h-1 w-10 rounded-full" style={{ backgroundColor: design.accent }} />
        </div>
        <div className={`rounded-control ${compact ? 'px-2 py-1.5' : 'px-3 py-2'}`} style={{ backgroundColor: design.surface }}>
          <p className="mb-1.5 text-caption opacity-75">Sales by region</p>
          <div aria-hidden="true" className={`flex flex-col ${compact ? 'gap-1' : 'gap-1.5'}`}>
            {design.palette.map((color, i) => (
              <span key={i} className="block h-2.5 rounded-control" style={{ backgroundColor: color, width: `${BARS[i] ?? 10}%` }} />
            ))}
          </div>
        </div>
      </div>
    </figure>
  );
}
