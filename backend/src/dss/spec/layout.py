"""One integer geometry implementation shared by HTML and recipes."""

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
            if item is not label and overlaps(reserved, box(spec.canvas, spec.grid, item.grid, height=page.height)):
                return ['Layout overlaps the reserved Synthetic sample data label']
    except ValueError:
        return ['Synthetic sample data label must fit the canvas']
    return []


def require_synthetic_label(spec):
    errors = synthetic_errors(spec)
    if errors:
        raise ValueError('; '.join(errors))
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
