"""Code layout: an accepted Blueprint + Design -> a validated 1-5 page Dashboard Spec.

No model call (architecture.md#Spec layout). The same inputs give byte-identical
spec.json (`model_dump_json(indent=2)`, as every spec writer saves it). Geometry is the
shared grid; header text rows come from the decoration kit's estimate and the validator
still measures every text box in Chromium before the spec is returned.
"""
import copy
import math
import re

from dss.artifacts.design import presets
from dss.render import kits
from dss.spec.layout import synthetic_decoration
from dss.spec.models import (CONTROL_TYPES as CONTROLS, DATE_AXIS_TYPES, DATE_TYPES, FIELD_CONTROLS, Canvas, Cell,
                             DashboardSpec, Grid, Theme, component_title, grain_word)
from dss.spec.validate import catalog, validate_spec

GRID = Grid()
FULL_WIDTH = ('time_series', 'area', 'table', 'pivot_table')
CONTROL_ROWS = 3
SCORECARDS_PER_ROW = 4
SCORECARD_ROWS = {'comfortable': 5, 'compact': 4}
# Default grid rows per chart type; the catalog's min_h still wins if it is larger.
CHART_ROWS = {
    'comfortable': {'time_series': 14, 'area': 14, 'bar': 14, 'pie': 14, 'scatter': 14, 'geo_map': 16,
                    'table': 16, 'pivot_table': 16, 'text': 6, 'image': 8},
    'compact': {'time_series': 11, 'area': 11, 'bar': 11, 'pie': 11, 'scatter': 11, 'geo_map': 12,
                'table': 12, 'pivot_table': 12, 'text': 4, 'image': 6}}
OTHER_ROWS = 12
HEADING_SIZE = 20
# kits.header_geometry's title widths (default 1152); subtitles always measure 1050.
TITLE_WIDTH = {'title_block': 760, 'side_rail': 1050}
# Decoration names the kits, the section heading and the synthetic footer use on a page.
RESERVED = {'header_band', 'header_rule', 'header_rail', 'header_block', 'report_title',
            'report_subtitle', 'section_heading', 'synthetic_sample_data'}


class LayoutError(ValueError):
    """The validator rejected a code layout: a defect for run.finished(error), never a model."""

    def __init__(self, errors):
        super().__init__('Code layout produced an invalid spec')
        self.errors = errors


def _slug(label, kind):
    slug = re.sub(r'[^a-z0-9]+', '_', label.casefold()).strip('_')
    if not slug[:1].isalpha():
        prefix = re.sub(r'[^a-z0-9]+', '_', kind.casefold()).strip('_')
        slug = '_'.join(part for part in (prefix if prefix[:1].isalpha() else 'component', slug) if part)
    return slug[:40].rstrip('_')


def _unique(base, used):
    name, n = base, 2
    while name in used or re.fullmatch(r'panel_[0-9]+', name):
        name, n = f'{base}_{n}', n + 1
    used.add(name)
    return name


def _wrap(text, size, width):
    """Break lines at the kits' conservative capacity (1.3em per character) so the browser never
    soft-wraps: a pre-wrap space hanging at a soft wrap pokes past the box and fails the fit check."""
    capacity = max(1, math.floor(width / (size * 1.3)))
    lines = []
    for raw in text.split('\n'):
        line = ''
        for word in re.sub(r'\s+', ' ', raw).strip().split(' '):
            if not word:
                continue
            while len(word) > capacity:  # an unbreakable run breaks at the capacity
                if line:
                    lines.append(line)
                    line = ''
                lines.append(word[:capacity])
                word = word[capacity:]
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= capacity:
                line += ' ' + word
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return '\n'.join(lines)


GRAINS = ('day', 'week', 'month', 'quarter', 'year')
TRUNC_CALL = re.compile(r'\s*(DATE|DATETIME|TIMESTAMP)_TRUNC\s*\(', re.I)
TOKEN = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`|[(),]|[^'\"`(),]+")


def bucket_grain(expression):
    """The grain of a derivation that is one whole DATE_TRUNC/DATETIME_TRUNC/TIMESTAMP_TRUNC call
    with a plain grain (TIMESTAMP_TRUNC may add a time zone), or None. Only the view's SQL counts,
    never the field's name."""
    call = TRUNC_CALL.match(expression)
    if not call:
        return None
    depth, args, end = 1, [''], None
    for token in TOKEN.finditer(expression, call.end()):
        text = token.group()
        if end is not None:
            if text.strip():
                return None  # the call is only part of the expression
        elif text == '(':
            depth += 1
        elif text == ')':
            depth -= 1
            if not depth:
                end = token.end()
                continue
        elif text == ',' and depth == 1:
            args.append('')
            continue
        if end is None:
            args[-1] += text
    if end is None or len(args) not in (2, 3) or (len(args) == 3 and call[1].upper() != 'TIMESTAMP'):
        return None
    grain = args[1].strip().lower()
    return grain if grain in GRAINS else None


def base_grains(sources, selection):
    """{view field: grain} for source DATE columns whose intake profile (data.profile bucket_start)
    puts every value on a bucket start. The view shows a join's first column of a name and every
    union branch's (a missing one is NULL), as view.blueprint_sql builds it, so a union keeps the
    finest grain its branches share; a column profiled before the fact existed gives none."""
    from dss.data.bigquery import snake_names
    from dss.harness.nodes.view import selected_sources
    starts = ('month', 'quarter', 'year')  # finest first
    found = {}
    for source in selected_sources(sources, selection):
        for name, column in zip(snake_names([c['name'] for c in source['columns']]), source['columns']):
            if selection.union or name not in found:
                found.setdefault(name, []).append(column.get('bucket_start'))
    return {name: min(grains, key=starts.index) for name, grains in found.items()
            if all(grain in starts for grain in grains)}


def _bottom(row):
    """Pixel y just below a block that ends before grid row `row` (its gutter excluded)."""
    return GRID.margin + (row - 1) * GRID.row_height - GRID.gutter


def _place(types, row, density, rules):
    """Cells by index: controls row(s), scorecard rows (<= 4 each), then packed charts."""
    cells = {}

    def rule(kind, axis, default):
        return max(default, rules.get(kind, {}).get('min_' + axis, 1))

    controls = [i for i, t in enumerate(types) if t in CONTROLS]
    width = max((rule(types[i], 'w', 3) for i in controls), default=3)
    per_row = max(1, GRID.columns // width)
    for start in range(0, len(controls), per_row):
        line = controls[start:start + per_row]
        height = max(rule(types[i], 'h', CONTROL_ROWS) for i in line)
        for k, i in enumerate(line):
            cells[i] = Cell(col=1 + k * width, row=row, w=width, h=height)
        row += height
    cards = [i for i, t in enumerate(types) if t == 'scorecard']
    per_row = max(1, min(SCORECARDS_PER_ROW, GRID.columns // rule('scorecard', 'w', 1)))
    lines = -(-len(cards) // per_row)
    for n in range(lines):
        # Balanced rows (7 -> 4 + 3), each split evenly across the 12 columns.
        count = len(cards) // lines + (n < len(cards) % lines)
        start = n * (len(cards) // lines) + min(n, len(cards) % lines)
        width = GRID.columns // count
        height = rule('scorecard', 'h', SCORECARD_ROWS[density])
        for k, i in enumerate(cards[start:start + count]):
            cells[i] = Cell(col=1 + k * width, row=row, w=width, h=height)
        row += height
    pending = None
    for i, kind in enumerate(types):
        if i in cells:
            continue
        height = rule(kind, 'h', CHART_ROWS[density].get(kind, OTHER_ROWS))
        if kind in FULL_WIDTH or rule(kind, 'w', 6) > 6:
            if pending is not None:
                cells[pending[0]] = Cell(col=1, row=row, w=6, h=pending[1])
                row, pending = row + pending[1], None
            cells[i] = Cell(col=1, row=row, w=GRID.columns, h=height)
            row += height
        elif pending is None:
            pending = (i, height)
        else:
            height = max(height, pending[1])  # a shared row keeps both cards aligned
            cells[pending[0]] = Cell(col=1, row=row, w=6, h=height)
            cells[i] = Cell(col=7, row=row, w=6, h=height)
            row, pending = row + height, None
    if pending is not None:
        cells[pending[0]] = Cell(col=1, row=row, w=6, h=pending[1])
        row += pending[1]
    return cells, row


def _component(prefix, row, cell, used, grain=None):
    c = row.component
    # The title rule again, for Blueprints saved before it; clean labels pass byte for byte.
    label = component_title(c)
    value = {'id': prefix + _unique(_slug(label, c.type), used), 'type': c.type, 'label': label,
             'grid': cell.model_dump(), 'dimensions': list(c.dimensions),
             'metrics': [m.model_dump() for m in c.metrics], 'date_dimension': c.date_dimension,
             'breakdown': c.breakdown, 'sort': c.sort.model_dump() if c.sort else None,
             'options': copy.deepcopy(c.options), 'question_ref': row.question_id}
    if c.type in FIELD_CONTROLS and len(c.dimensions) == 1:
        # Blueprint has no field slot: its single dropdown/list dimension is add_control.field.
        value['field'], value['dimensions'] = c.dimensions[0], []
    if c.type == 'pivot_table' and not c.dimensions:
        # Feasibility counts pivot row/column options as its dimensions; the
        # spec and the prototype's grouping need them too (recipe options win).
        value['dimensions'] = list(dict.fromkeys(c.options.get('row_dimensions', []) + c.options.get('column_dimensions', [])))
    if c.type == 'text':
        value['text'] = label
    if row.reference_item:
        value['reference_item'] = row.reference_item
    if grain:
        value['date_granularity'] = grain
    return value


def _page(index, name, rows, design, theme, kit, rules, heading, synthetic, grain=lambda row: None):
    prefix = f'p{index}_'
    title = _wrap(design.title, 28, TITLE_WIDTH.get(kit, 1152))
    subtitle = design.subtitle and _wrap(design.subtitle, 18, 1050)
    row = kits.content_row(kit, title, subtitle)
    extra = []
    if heading:
        text = _wrap(name, HEADING_SIZE, 1152)
        rows_needed = kits._rows(text, HEADING_SIZE, 1152)
        extra.append({'id': prefix + 'section_heading', 'kind': 'subtitle',
                      'grid': Cell(col=1, row=row, w=GRID.columns, h=rows_needed).model_dump(), 'text': text,
                      'style': {'color': theme.text, 'font_size': HEADING_SIZE, 'font_weight': 700}})
        row += rows_needed
    types = [r.component.type for r in rows]
    cells, end = _place(types, row, design.density, rules)
    used = set(RESERVED)
    components = [_component(prefix, r, cells[i], used, grain(r)) for i, r in enumerate(rows)]
    panels = [cells[i] for i, kind in enumerate(types) if kind not in CONTROLS]
    decorations = [d.model_dump() for d in kits.decorations(
        kit, theme, title, subtitle, page=index, panels=panels)] + extra
    height = _bottom(end) + GRID.margin
    if synthetic:
        # Page 1 carries the code-owned footer in its reserved bottom strip.
        label = synthetic_decoration(end)
        decorations.append(label.model_dump())
        height = _bottom(end + label.grid.h) + GRID.margin
    return {'index': index, 'name': name, 'height': height,
            'decorations': decorations, 'components': components}


def spec_value(blueprint, design, outline, fields, *, build_id, archetype, spec_version=1, synthetic=False,
               sources=()):
    """The unvalidated spec dict. `fields` are the view's {name, type, role[, label, default_agg]};
    `sources` the connected sources with their intake profile columns."""
    preset = next((p for p in presets() if p.id == design.preset_id), None)
    if preset is None:
        raise ValueError('Design names an unknown theme preset')
    theme = Theme(background=design.background, surface=design.surface, text=design.text,
                  muted=preset.muted, accent=design.accent, palette=list(design.palette),
                  font_family=design.font_family, radius=preset.radius)
    rules = catalog()
    sections = {s.id: s.title for s in outline.sections}
    rows = [r for r in blueprint.rows if r.status == 'ok']
    per_section = design.page_structure == 'per_section'
    datasource_fields = [{'name': f['name'], 'type': f['type'],
                          'label': f.get('label') or f['name'].replace('_', ' ').title(), 'role': f['role'],
                          'default_agg': f.get('default_agg') or ('sum' if f['role'] == 'metric' else 'none')}
                         for f in fields]
    # A time series on a bucket draws one point per bucket: the grain comes from the derivation
    # the view builder compiles, or from a base DATE column's code-computed profile, and reaches
    # the compiler through the spec.
    starts = base_grains(sources, blueprint.view_sources) if sources else {}
    grains = {d.name: bucket_grain(d.expression) for d in blueprint.derived_fields}
    for f in datasource_fields:
        if grains.get(f['name']) and f['type'] in ('DATE', 'DATETIME', 'TIMESTAMP'):
            f['date_granularity'] = grains[f['name']]
        elif f['name'] not in grains and starts.get(f['name']) and f['type'] == 'DATE':
            f['date_granularity'] = starts[f['name']]
    # A trend on an unbucketed date whose label or selected question names one grain is drawn at
    # it (architecture.md#Component titles and grain words); a bucket field keeps its own grain.
    texts = {q.id: q.text for s in outline.sections for q in s.questions if q.selected}
    dates = {f['name'] for f in datasource_fields
             if f['type'].upper() in DATE_TYPES and not f.get('date_granularity')}

    def grain(row):
        c = row.component
        if c.type not in DATE_AXIS_TYPES or c.date_dimension not in dates:
            return None
        return grain_word(component_title(c), texts.get(row.question_id))

    pages = []
    # Pages whose rows were all dropped vanish; later pages renumber and keep their names.
    for number in sorted({r.page for r in rows}):
        page_rows = [r for r in rows if r.page == number]
        name = sections.get(page_rows[0].section_id, design.title) if per_section else design.title
        pages.append(_page(len(pages) + 1, name, page_rows, design, theme, preset.decoration_kit,
                           rules, per_section, synthetic and not pages, grain))
    return {'spec_version': spec_version, 'build_id': build_id, 'title': design.title, 'archetype': archetype,
            'canvas': {'width': Canvas().width, 'height': pages[0]['height'] if pages else Canvas().height},
            'grid': GRID.model_dump(), 'theme': theme.model_dump(),
            'datasource': {'table': blueprint.view_table, 'fields': datasource_fields, 'synthetic': synthetic},
            'pages': pages}


def layout(blueprint, design, outline, fields, *, build_id, archetype, spec_version=1, synthetic=False,
           allowed=None, sources=()):
    """Lay out and validate, including every ok row's question_ref; raise LayoutError otherwise."""
    value = spec_value(blueprint, design, outline, fields, build_id=build_id, archetype=archetype,
                       spec_version=spec_version, synthetic=synthetic, sources=sources)
    refs = [r.question_id for r in blueprint.rows if r.status == 'ok' and r.question_id]
    errors = validate_spec(value, allowed=allowed, question_refs=refs)
    if errors:
        raise LayoutError(errors)
    return DashboardSpec.model_validate(value)
