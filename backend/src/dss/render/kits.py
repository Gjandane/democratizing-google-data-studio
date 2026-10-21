"""Deterministic decoration kits. Geometry is the spec grid, never HTML from a model.

The layout caller starts components at content_row() and can supply panel cells
to panel_grid. All IDs are page-prefixed; decorative surfaces precede their text.
"""
import math

from dss.artifacts.design import on_color
from dss.spec.models import Cell, Decoration

KITS = ('band_header', 'panel_grid', 'side_rail', 'ruled_header', 'title_block')
# Surfaces carry their accent as a fill, text decorations as their text color.
SURFACES = ('band', 'panel', 'divider')


def accent_key(kind):
    """The kit style key an accent/color comment on a decoration of this kind sets."""
    return 'background_color' if kind in SURFACES else 'color'


def _rows(text, size, width):
    # 1.3em covers wide bold Georgia glyphs (W measures 1.126em in Chromium),
    # including explicit blank lines. The final
    # renderer still checks actual browser text fit before publication.
    capacity = max(1, math.floor(width / (size * 1.3)))
    lines = sum(max(1, math.ceil(len(line) / capacity)) for line in text.split('\n'))
    return max(3, math.ceil((lines * size * 1.25 + 16) / 20))


def header_geometry(kit, title, subtitle):
    if kit not in KITS:
        raise ValueError('Unknown decoration kit')
    width = 760 if kit == 'title_block' else 1050 if kit == 'side_rail' else 1152
    title_rows = _rows(title, 28, width)
    subtitle_rows = _rows(subtitle, 18, 1050) if subtitle else 0
    subtitle_row = 2 + title_rows
    end = max(9, subtitle_row + subtitle_rows + 1)
    return title_rows, subtitle_row, subtitle_rows, end


def content_row(kit, title, subtitle=None):
    return header_geometry(kit, title, subtitle)[3] + 1


def decorations(kit, theme, title, subtitle=None, *, page=1, panels=()):
    title_rows, subtitle_row, subtitle_rows, end = header_geometry(kit, title, subtitle)
    result = []
    def add(name, kind, col, row, w, h, text=None, **style):
        result.append(Decoration(id=f'p{page}_{name}', kind=kind,
            grid=Cell(col=col, row=row, w=w, h=h), text=text, style=style))
    col, width, title_color = 1, 12, theme.text
    if kit == 'band_header':
        add('header_band', 'band', 1, 1, 12, end - 1, background_color=theme.accent, border_radius=0)
        title_color = on_color(theme.accent)
    elif kit == 'panel_grid':
        add('header_rule', 'divider', 1, 1, 3, 1, background_color=theme.accent, border_radius=0)
        for i, cell in enumerate(panels, 1):
            add(f'panel_{i}', 'panel', cell.col, cell.row, cell.w, cell.h, background_color=theme.surface)
    elif kit == 'side_rail':
        add('header_rail', 'band', 1, 1, 1, end - 1, background_color=theme.accent, border_radius=0)
        col, width = 2, 11
    elif kit == 'ruled_header':
        add('header_rule', 'divider', 1, end - 1, 12, 1, background_color=theme.accent, border_radius=0)
    elif kit == 'title_block':
        add('header_block', 'band', 1, 1, 8, title_rows + 1, background_color=theme.accent, border_radius=0)
        width, title_color = 8, on_color(theme.accent)
    add('report_title', 'title', col, 2, width, title_rows, title, color=title_color)
    if subtitle:
        color = title_color if kit == 'band_header' else theme.text
        add('report_subtitle', 'subtitle', col, subtitle_row, 13 - col, subtitle_rows, subtitle, color=color)
    return result
