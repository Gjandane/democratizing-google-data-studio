"""One integer geometry implementation shared by HTML and recipes."""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import math
import re


TEXT_LAYOUT_GUIDANCE = (
    'Decoration text uses title 28px bold, subtitle 18px normal, other text 16px normal; '
    'line-height is 1.25 times font size. Titles/subtitles have zero padding; other decorations '
    'have 16px padding on each side. Text preserves newlines and wraps anywhere. '
    'font_size/font-size overrides accept positive px numbers (or px strings); '
    'font_weight/font-weight accepts normal, bold or 100..900. '
    'A default one-line title needs h>=3 (44px); h=2 is only 24px and cannot fit 28px text. '
    'Allocate more rows for larger fonts, multiple lines or long headings. '
    'Keep all boxes in bounds, avoid covering other items, and preserve the synthetic footer.'
)


def decoration_text_style(item, theme):
    """Canonical text CSS, also used in Chromium's validation document."""
    from dss.spec.models import SYNTHETIC_LABEL_ID
    size = item.style.get('font-size', item.style.get('font_size',
        28 if item.kind == 'title' else 18 if item.kind == 'subtitle' else 16))
    if isinstance(size, bool) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?(?:px)?', str(size)):
        raise ValueError('Decoration font size must be a positive pixel number')
    size = float(str(size).removesuffix('px'))
    if not math.isfinite(size) or not 0 < size <= 1200:
        raise ValueError('Decoration font size must be between 0 and 1200px')
    weight = str(item.style.get('font-weight', item.style.get('font_weight',
        700 if item.kind == 'title' else 400)))
    if weight not in ('normal', 'bold') and not re.fullmatch(r'[1-9]00', weight):
        raise ValueError('Decoration font weight must be normal, bold or 100..900')
    family = re.sub(r'[^\w\s#(),.%+\-]', '', theme.font_family)
    padding = 0 if item.kind in ('title', 'subtitle') else 16
    if item.id == SYNTHETIC_LABEL_ID:
        family, size, weight, padding = 'Arial', 16, '400', 16
    return (f'font-family:{family};font-size:{size:g}px;font-weight:{weight};'
            f'line-height:{size * 1.25:g}px;padding:{padding}px;'
            'white-space:pre-wrap;overflow-wrap:anywhere;overflow:visible')


@lru_cache(maxsize=256)
def _text_fits(cases):
    # Never run Playwright's sync API on an async API handler's event-loop thread.
    # Cache geometry/style/content only: layout-only revisions reuse the measurements.
    def measure():
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(timeout=10000)
            try:
                page = browser.new_page()
                page.set_default_timeout(5000)
                page.set_content('<div id="box"><div id="text" style="display:flow-root"></div></div>')
                return page.evaluate('''cases => cases.map(([text, style, width, height]) => {
                    const box = document.getElementById('box'), inner = document.getElementById('text');
                    box.style.cssText = `box-sizing:border-box;width:${width}px;height:${height}px;${style}`;
                    inner.textContent = text;
                    const outer = box.getBoundingClientRect(), content = inner.getBoundingClientRect();
                    const padding = parseFloat(getComputedStyle(box).paddingTop);
                    const range = document.createRange(); range.selectNodeContents(inner);
                    return content.height <= height - 2 * padding + .01 &&
                        [...range.getClientRects()].every(r => r.left >= outer.left + padding - .01 &&
                            r.right <= outer.right - padding + .01 && r.top >= outer.top + padding - .01 &&
                            r.bottom <= outer.bottom - padding + .01);
                })''', cases)
            finally:
                browser.close()
    with ThreadPoolExecutor(max_workers=1) as worker:
        return worker.submit(measure).result()


def decoration_text_errors(spec):
    """Fail closed before clipped text can be published or baked into a background."""
    errors = []
    cases, paths = [], []
    for p, page in enumerate(spec.pages):
        for i, item in enumerate(page.decorations):
            if not item.text or (item.kind == 'logo' and item.style.get('image_path')):
                continue
            path = f'pages.{p}.decorations.{i}'
            try:
                bounds = box(spec.canvas, spec.grid, item.grid, height=page.height)
            except ValueError:
                continue  # The ordinary geometry validator owns this diagnostic.
            try:
                style = decoration_text_style(item, spec.theme)
            except ValueError as exc:
                errors.append(dict(path=path + '.style', message=str(exc)))
                continue
            cases.append((item.text, style, bounds['w'], bounds['h']))
            paths.append(path)
    for path, fits in zip(paths, _text_fits(tuple(cases)) if cases else []):
        if not fits:
            errors.append(dict(path=path + '.grid', message=
                'Decoration text does not fit its content box; increase grid width/height '
                'or reduce font size/text while keeping boxes in bounds and the synthetic footer clear'))
    return errors

def overlaps(a, b):
    return a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']


def synthetic_decoration(row):
    from dss.spec.models import Decoration, SYNTHETIC_LABEL_ID, SYNTHETIC_LABEL
    return Decoration(id=SYNTHETIC_LABEL_ID, kind='text', grid=dict(col=1, row=row, w=12, h=4),
        text=SYNTHETIC_LABEL, style={'background': '#FFFFFF', 'color': '#0F172A',
                                   'font_size': 16, 'font_weight': 400, 'border_radius': 0, 'opacity': 1})


def with_synthetic_label(spec, required):
    """Code-owned provenance, with a new footer for legacy/model specs lacking the label.

    Existing labels are never repaired here: validation must reject altered or covered labels.
    Work on a copy so failed validation cannot change published state.
    """
    from dss.spec.models import SYNTHETIC_LABEL_ID
    spec = spec.model_copy(deep=True)
    spec.datasource.synthetic = required
    if required and not any(d.id == SYNTHETIC_LABEL_ID for d in spec.pages[0].decorations):
        page = spec.pages[0]
        row = max(1, (max(page.height, spec.canvas.height) - spec.grid.margin + 19) // 20 + 1)
        label = synthetic_decoration(row)
        page.height = spec.canvas.height = spec.grid.margin + (row - 1) * 20 + 64 + spec.grid.margin
        page.decorations.append(label)
    return spec


def synthetic_errors(spec):
    """Validate the immutable footer and its reserved strip, including decoration collisions."""
    from dss.spec.models import SYNTHETIC_LABEL_ID
    page = spec.pages[0]
    labels = [d for d in page.decorations if d.id == SYNTHETIC_LABEL_ID]
    if not spec.datasource.synthetic:
        return ['Synthetic label requires synthetic source provenance'] if labels else []
    if len(labels) != 1:
        return ['Synthetic sample data label is required']
    label = labels[0]
    if label != synthetic_decoration(label.grid.row):
        return ['Synthetic sample data label is read-only']
    try:
        reserved = box(spec.canvas, spec.grid, label.grid, height=page.height)
        if reserved['y'] + reserved['h'] + spec.grid.margin != page.height:
            return ['Synthetic sample data label must stay in its reserved footer']
        # Reserve the entire horizontal strip, including the label's margins.
        reserved.update(x=0, w=spec.canvas.width)
        for item in page.components + page.decorations:
            # A design covers the page; its measurement keeps every element above the footer.
            if item is label or getattr(item, 'kind', None) == 'design':
                continue
            if overlaps(reserved, layout_box(spec, page, item)):
                return ['Layout overlaps the reserved Synthetic sample data label']
    except ValueError:
        return ['Synthetic sample data label must fit the canvas']
    return []


def require_synthetic_label(spec):
    errors = synthetic_errors(spec)
    if errors:
        raise ValueError('; '.join(errors))


def layout_box(spec, page, item):
    """Layout for one spec item: a designed page's measured component `box` unchanged, the page
    rect for its `design` decoration, else the grid cell's box. Prototype, background and recipe
    all ask here, so they agree."""
    if getattr(item, 'box', None) is not None:
        return item.box.model_dump()
    if getattr(item, 'kind', None) == 'design':
        return dict(x=0, y=0, w=spec.canvas.width, h=page.height)
    return box(spec.canvas, spec.grid, item.grid, height=page.height)


def minimum_box(rule, canvas, grid):
    """(w, h) px of a catalog type's min_w x min_h cells at this canvas width."""
    from types import SimpleNamespace
    from dss.spec.models import Cell
    size = box(SimpleNamespace(width=canvas.width, height=10 ** 6), grid,
               Cell(col=1, row=1, w=rule['min_w'], h=rule['min_h']))
    return size['w'], size['h']


def design_decoration(index, height, grid=None):
    """The `p<n>_design` decoration of a designed page: its grid covers the page's grid rows;
    Layout draws it at the full page rect."""
    from dss.spec.models import Cell, Decoration, Grid
    grid = grid or Grid()
    rows = max(1, (height - 2 * grid.margin + grid.gutter) // grid.row_height)
    return Decoration(id=f'p{index}_design', kind='design', grid=Cell(col=1, row=1, w=grid.columns, h=rows))


def box(canvas, grid, cell, *, height=None):
    col_w = (canvas.width - 2 * grid.margin - (grid.columns - 1) * grid.gutter) / grid.columns
    left = grid.margin + (cell.col - 1) * (col_w + grid.gutter)
    right = left + cell.w * col_w + (cell.w - 1) * grid.gutter
    x, end = round(left), round(right)
    y = grid.margin + (cell.row - 1) * grid.row_height
    h = cell.h * grid.row_height - grid.gutter
    if (col_w <= 0 or cell.col + cell.w - 1 > grid.columns or
            x < 0 or y < 0 or end > canvas.width or y + h > (height or canvas.height) or end <= x or h <= 0):
        raise ValueError("Grid box is outside the canvas or has no area")
    return dict(x=x, y=y, w=end-x, h=h)
