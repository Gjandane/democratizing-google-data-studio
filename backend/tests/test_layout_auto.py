"""Code layout: Blueprint + Design -> a validated multi-page spec, deterministically and without a model."""
import random
from collections import Counter
from pathlib import Path

import pytest

from dss.artifacts.design import presets
from dss.artifacts.models import Blueprint, Design, Outline
from dss.spec import layout as geometry
from dss.spec.auto_layout import LayoutError, layout
from dss.spec.layout import box, overlaps, synthetic_errors
from dss.spec.models import SYNTHETIC_LABEL_ID
from dss.spec.validate import catalog

DATA = Path('tests/data')
GOLDEN = DATA / 'golden_layout_spec.json'
IDENTITY = dict(build_id='b_123456789abc', archetype='executive')
FIELDS = [{'name': n, 'type': t, 'role': 'metric' if t in ('FLOAT64', 'INT64') else 'dimension'} for n, t in (
    ('order_date', 'DATE'), ('region', 'STRING'), ('category', 'STRING'), ('product', 'STRING'),
    ('country', 'GEOGRAPHY'), ('order_id', 'STRING'), ('revenue', 'FLOAT64'), ('units', 'INT64'),
    ('order_size_band', 'STRING'))]


def question(qid):
    return {'id': qid, 'text': 'Question ' + qid, 'rationale': '', 'recommended': True, 'selected': True,
            'kpi_refs': [], 'origin': 'proposed'}


def outline(titles, qids=()):
    return Outline.model_validate({'revision': 1, 'sections': [
        {'id': sid, 'title': title, 'purpose': '', 'questions': [question(q) for q, s in sorted(qids) if s == sid]}
        for sid, title in titles.items()]})


GOLDEN_OUTLINE = {'s1': 'Revenue snapshot', 's2': 'Average order value', 's3': 'Where revenue comes from',
                  's4': 'Order mix'}


def golden_layout():
    """The golden layout spec as code lays it out since 31.1: its trend "Net revenue by month" on the raw
    order_date records the month grain (#Component titles and grain words); every other byte is the file's,
    which stays the pre-31.1 saved spec that test_compiler compiles byte-identically."""
    from dss.spec.models import DashboardSpec
    spec = DashboardSpec.model_validate_json(GOLDEN.read_text(encoding='utf-8'))
    assert spec.model_dump_json(indent=2) == GOLDEN.read_text(encoding='utf-8')
    [trend] = [c for p in spec.pages for c in p.components if c.type == 'time_series']
    assert trend.label == 'Net revenue by month' and trend.date_granularity is None
    trend.date_granularity = 'month'
    return spec.model_dump_json(indent=2)


def golden_inputs():
    blueprint = Blueprint.model_validate_json((DATA / 'golden_blueprint.json').read_text(encoding='utf-8'))
    design = Design.model_validate_json((DATA / 'golden_design.json').read_text(encoding='utf-8'))
    return blueprint, design, outline(GOLDEN_OUTLINE)


def test_golden_blueprint_and_design_give_byte_identical_spec():
    blueprint, design, plan = golden_inputs()
    first = layout(blueprint, design, plan, FIELDS, **IDENTITY, allowed=set(catalog()))
    again = layout(blueprint, design, plan, FIELDS, **IDENTITY, allowed=set(catalog()))
    data = first.model_dump_json(indent=2).encode('utf-8')
    assert data == again.model_dump_json(indent=2).encode('utf-8')
    # read_text: the golden is LF text whatever the checkout's line endings.
    assert data == golden_layout().encode('utf-8')
    # Blueprint pages 1, 3, 4 (page 2's rows were all dropped) renumber and keep section names.
    assert [(p.index, p.name) for p in first.pages] == [
        (1, 'Revenue snapshot'), (2, 'Where revenue comes from'), (3, 'Order mix')]
    assert first.canvas.height == first.pages[0].height
    assert [c.question_ref for p in first.pages for c in p.components] == [r.question_id for r in blueprint.rows]
    dropdown = first.pages[0].components[1]
    assert (dropdown.type, dropdown.field, dropdown.dimensions) == ('dropdown', 'region', [])
    assert not any(d.id == SYNTHETIC_LABEL_ID for p in first.pages for d in p.decorations)


def test_synthetic_footer_is_reserved_on_page_one():
    blueprint, design, plan = golden_inputs()
    plain = layout(blueprint, design, plan, FIELDS, **IDENTITY, allowed=set(catalog()))
    spec = layout(blueprint, design, plan, FIELDS, **IDENTITY, synthetic=True, allowed=set(catalog()))
    assert spec.datasource.synthetic and synthetic_errors(spec) == []
    first = spec.pages[0]
    label = first.decorations[-1]
    assert label.id == SYNTHETIC_LABEL_ID
    bounds = box(spec.canvas, spec.grid, label.grid, height=first.height)
    assert bounds['y'] + bounds['h'] + spec.grid.margin == first.height == spec.canvas.height
    strip = dict(bounds, x=0, w=spec.canvas.width)
    assert not any(overlaps(strip, box(spec.canvas, spec.grid, item.grid, height=first.height))
                   for item in first.components + first.decorations[:-1])
    assert first.height == plain.pages[0].height + 80  # four rows below the unchanged content
    assert [c.grid for c in first.components] == [c.grid for c in plain.pages[0].components]
    assert spec.pages[1:] == plain.pages[1:]


def test_invalid_layout_is_a_layout_error_with_validator_errors():
    blueprint, design, plan = golden_inputs()
    six = blueprint.model_copy(deep=True)
    for page in (5, 6, 7):
        six.rows.append(six.rows[-1].model_copy(update={'page': page, 'section_id': 's4'}, deep=True))
    with pytest.raises(LayoutError) as caught:
        layout(six, design, plan, FIELDS, **IDENTITY, allowed=set(catalog()))
    assert {'path': 'pages', 'message': 'List should have at most 5 items after validation, not 6'} in caught.value.errors
    with pytest.raises(LayoutError) as caught:
        layout(blueprint, design, plan, FIELDS[1:], **IDENTITY, allowed=set(catalog()))
    assert all(e['path'].startswith('pages.') for e in caught.value.errors) and caught.value.errors


# Property test --------------------------------------------------------------------------------
# Image rows are excluded: a Blueprint row cannot carry the uploaded asset path an image needs.
BINDINGS = {
    'scorecard': lambda r: dict(metrics=[r.choice([('revenue', 'sum'), ('units', 'avg'), ('order_id', 'count_distinct')])]),
    'time_series': lambda r: dict(metrics=[('revenue', 'sum')], date_dimension='order_date',
                                  breakdown=r.choice([None, 'region'])),
    'bar': lambda r: dict(dimensions=[r.choice(['region', 'category'])],
                          metrics=r.sample([('revenue', 'sum'), ('units', 'sum'), ('order_id', 'count')], r.randint(1, 3))),
    'pie': lambda r: dict(dimensions=['category'], metrics=[('revenue', 'sum')]),
    'table': lambda r: dict(dimensions=r.sample(['region', 'category', 'product'], r.randint(1, 3)),
                            metrics=[('units', 'sum')]),
    'pivot_table': lambda r: dict(dimensions=['region', 'category'], metrics=[('revenue', 'sum')]),
    'geo_map': lambda r: dict(dimensions=['country'], metrics=[('revenue', 'sum')]),
    'scatter': lambda r: dict(dimensions=['product'], metrics=[('revenue', 'sum'), ('units', 'sum')]),
    'text': lambda r: {},
    'date_range': lambda r: dict(date_dimension='order_date'),
    'dropdown': lambda r: dict(dimensions=['region']),
}
LABELS = ['Net revenue', 'Net revenue', 'Report title', 'Panel 1', 'Section heading', '2026 revenue',
          'Umsatz für Café', '売上', '', 'A very long label for a component ' * 3]
SECTION_TITLES = ['Overview', 'Where revenue comes from', 'W' * 60, 'Regional\nbreakdown', 'Ünïcödé séction',
                  'A long section title that wraps across more than one line on the canvas ' * 2]
TITLES = ['Sales', 'Sales Performance Overview', 'W' * 80, 'Weekly operations\nreview',
          'Weekly regional revenue performance overview for the northern region stores']
SUBTITLES = [None, 'Web shop, Jan-Sep 2026', 'A subtitle long enough to wrap onto a second line of the header ' * 2]


def random_row(r, qid, sid, page):
    kind = r.choice(sorted(BINDINGS))
    binding = BINDINGS[kind](r)
    return {'question_id': None if kind in ('date_range', 'dropdown') and r.random() < .7 else qid,
            'section_id': sid, 'page': page,
            'component': {'type': kind, 'label': r.choice(LABELS), 'dimensions': binding.get('dimensions', []),
                          'metrics': [{'field': f, 'agg': a} for f, a in binding.get('metrics', [])],
                          'date_dimension': binding.get('date_dimension'), 'breakdown': binding.get('breakdown'),
                          'sort': None, 'options': {}},
            'note': '', 'status': 'ok', 'issue_ids': []}


def random_case(r):
    count = r.randint(1, 5)
    structure = 'per_section' if count > 1 else r.choice(['single', 'per_section'])
    dropped = {p for p in range(1, count + 1) if r.random() < .25}
    if len(dropped) == count:
        dropped.discard(r.randint(1, count))
    titles, rows, n = {}, [], 0
    for page in range(1, count + 1):
        sid = f's{page}'
        titles[sid] = r.choice(SECTION_TITLES)
        for _ in range(r.randint(1, 12)):
            n += 1
            row = random_row(r, f'q{r.randint(n, n + 1)}', sid, page)
            if page in dropped:
                if r.random() < .5:
                    continue  # removed by a drop decision
                row['status'], row['issue_ids'] = 'blocked', ['i1']
            rows.append(row)
    preset = r.choice(presets())
    design = Design.model_validate({
        'revision': 1, 'preset_id': preset.id, 'background': preset.background, 'surface': preset.surface,
        'text': preset.text, 'accent': preset.accent, 'palette': preset.palette,
        'font_family': preset.font_family, 'page_structure': structure,
        'density': r.choice(['comfortable', 'compact']), 'title': r.choice(TITLES),
        'subtitle': r.choice(SUBTITLES), 'source': 'preset', 'issues': []})
    blueprint = Blueprint.model_validate({
        'revision': 1, 'view_sources': {'base': 's_a1b2c3d4e5f6', 'joins': [], 'union': []}, 'derived_fields': [],
        'rows': rows, 'view_table': 'demo-project.dss_demo.view_r1', 'assessment_id': None})
    plan = outline(titles, {(row['question_id'], row['section_id']) for row in rows if row['question_id']})
    kept = [p for p in range(1, count + 1) if p not in dropped]
    return blueprint, design, plan, titles, kept, r.random() < .4


def test_property_valid_blueprints_give_valid_specs(monkeypatch):
    measured = set()

    def record(cases):
        measured.update(cases)
        return [True] * len(cases)

    real = geometry._text_fits
    monkeypatch.setattr(geometry, '_text_fits', record)  # measured once, in one browser, below
    rules = catalog()
    rng = random.Random(1508)
    for case in range(200):
        blueprint, design, plan, titles, kept, synthetic = random_case(rng)
        spec = layout(blueprint, design, plan, FIELDS, **IDENTITY, synthetic=synthetic, allowed=set(rules))
        again = layout(blueprint, design, plan, FIELDS, **IDENTITY, synthetic=synthetic, allowed=set(rules))
        assert spec.model_dump_json(indent=2) == again.model_dump_json(indent=2), case
        ok = [row for row in blueprint.rows if row.status == 'ok']
        names = [design.title] if design.page_structure == 'single' else [titles[f's{p}'] for p in kept]
        assert [(p.index, p.name) for p in spec.pages] == list(enumerate(names, 1)), case
        assert 1 <= len(spec.pages) <= 5 and all(p.components for p in spec.pages), case
        assert [(c.type, c.label) for p in spec.pages for c in p.components] == [
            (row.component.type, row.component.label) for row in ok], case
        assert Counter(c.question_ref for p in spec.pages for c in p.components if c.question_ref) == Counter(
            row.question_id for row in ok if row.question_id), case
        assert spec.canvas.height == spec.pages[0].height
        for p in spec.pages:
            boxes = [box(spec.canvas, spec.grid, c.grid, height=p.height) for c in p.components]
            for i, c in enumerate(p.components):
                assert c.grid.w >= rules[c.type]['min_w'] and c.grid.h >= rules[c.type]['min_h'], (case, c.id)
                assert not any(overlaps(boxes[i], other) for other in boxes[i + 1:]), (case, c.id)
            for d in p.decorations:
                if d.text:  # headings and the footer are never covered by a component
                    bounds = box(spec.canvas, spec.grid, d.grid, height=p.height)
                    assert not any(overlaps(bounds, other) for other in boxes), (case, d.id)
            assert any(d.id == SYNTHETIC_LABEL_ID for d in p.decorations) == (synthetic and p.index == 1), case
        assert spec.datasource.synthetic == synthetic and synthetic_errors(spec) == [], case
    cases = tuple(sorted(measured))
    fits = real(cases)
    assert all(fits), [c[0] for c, ok in zip(cases, fits) if not ok]


@pytest.mark.parametrize('expression, grain', [
    ('DATE_TRUNC(order_date, MONTH)', 'month'), ('date_trunc(`order_date`, day)', 'day'),
    ('DATE_TRUNC(t0.order_date, WEEK)', 'week'), ('DATETIME_TRUNC(created, QUARTER)', 'quarter'),
    ('TIMESTAMP_TRUNC(created_at, YEAR)', 'year'), ("TIMESTAMP_TRUNC(created_at, MONTH, 'UTC')", 'month'),
    ('DATE_TRUNC(DATE(created_at), MONTH)', 'month'), ("DATE_TRUNC(PARSE_DATE('%Y(%m', s), YEAR)", 'year'),
    ('order_date', None), ('DATE_TRUNC(order_date, WEEK(MONDAY))', None), ('DATE_TRUNC(order_date, ISOWEEK)', None),
    ('DATE_TRUNC(order_date, HOUR)', None), ("DATE_TRUNC(order_date, MONTH, 'UTC')", None),
    ('DATE_TRUNC(a, MONTH) - DATE_TRUNC(b, DAY)', None), ('DATE_ADD(DATE_TRUNC(a, MONTH), INTERVAL 1 DAY)', None),
    ('DATE_TRUNC(order_date, MONTH', None), ("CASE WHEN x THEN 'DATE_TRUNC(a, MONTH)' END", None)])
def test_bucket_grain_reads_only_a_whole_trunc_derivation(expression, grain):
    from dss.spec.auto_layout import bucket_grain
    assert bucket_grain(expression) == grain


def test_bucket_derived_field_carries_its_grain_into_the_spec():
    """23.1: the grain reaches the compiler through the spec: the datasource field built from the
    Blueprint's DATE_TRUNC derivation records it; raw dates and name-only "buckets" get none."""
    from dss.artifacts.models import DerivedField
    blueprint, design, plan = golden_inputs()
    derived = [DerivedField(name='order_date_month', expression='DATE_TRUNC(order_date, MONTH)', type='date', description='Month'),
               DerivedField(name='order_date_week', expression='order_date', type='date', description='Not a bucket'),
               DerivedField(name='label_year', expression="FORMAT_DATE('%Y', order_date)", type='string', description='Text'),
               DerivedField(name='created_quarter', expression='TIMESTAMP_TRUNC(created_at, QUARTER)', type='datetime', description='Quarter'),
               DerivedField(name='odd_month', expression='DATE_TRUNC(order_date, MONTH)', type='string', description='Not a date view field')]
    blueprint = blueprint.model_copy(update={'derived_fields': blueprint.derived_fields + derived})
    trend = next(r for r in blueprint.rows if r.component.type == 'time_series')
    trend.component.date_dimension = 'order_date_month'
    fields = FIELDS + [{'name': 'order_date_month', 'type': 'DATE', 'role': 'dimension'},
                       {'name': 'order_date_week', 'type': 'DATE', 'role': 'dimension'},
                       {'name': 'label_year', 'type': 'STRING', 'role': 'dimension'},
                       {'name': 'created_quarter', 'type': 'TIMESTAMP', 'role': 'dimension'},
                       {'name': 'odd_month', 'type': 'STRING', 'role': 'dimension'}]
    spec = layout(blueprint, design, plan, fields, **IDENTITY, allowed=set(catalog()))
    grains = {f.name: f.date_granularity for f in spec.datasource.fields}
    assert (grains['order_date_month'], grains['created_quarter']) == ('month', 'quarter')
    # A raw date, a name-only "bucket", text, and a TRUNC whose view field is not a date: no grain.
    assert grains['order_date'] is grains['order_date_week'] is grains['label_year'] is grains['odd_month'] is None
    saved = spec.model_dump_json(indent=2)
    assert saved.count('"date_granularity"') == 2  # absent (not null) on every other field
    from dss.spec.models import DashboardSpec
    assert DashboardSpec.model_validate_json(saved) == spec


def profiled_source(level):
    """The golden source as intake profiles it (FakeBigQuery, one aggregate query); `level` is its
    `order_date` bucket aggregate (3 year, 2 quarter, 1 month, 0 another value, None all null)."""
    from google.cloud import bigquery
    from dss.data.profile import profile_table
    from test_profile import FakeBigQuery, stats
    service = FakeBigQuery([bigquery.SchemaField('order_date', 'DATE'), bigquery.SchemaField('region', 'STRING')],
                           {'row_count': 10, 'c0': {**stats([('2024-01-01', 10)]), 'bucket_start': level},
                            'c1': stats([('East', 10)])})
    return {'id': 's_a1b2c3d4e5f6', 'columns': profile_table(service, 'test-project.demo.sales')['columns']}


@pytest.mark.parametrize('level, grain', [(3, 'year'), (2, 'quarter'), (1, 'month'), (0, None), (None, None)])
def test_base_date_column_on_bucket_starts_carries_its_grain(level, grain):
    """24.2 (release 2.6 b_697880743b4f s008/s010: a yearly `year` DATE drew daily spikes): a time series
    and an area on a source DATE column whose profile puts every value on a bucket start compile with
    that grain, from the intake aggregate through the spec; a model-written grain is never trusted."""
    import json
    from dss.recipe.compiler import compile_recipe
    blueprint, design, plan = golden_inputs()
    trend = next(r for r in blueprint.rows if r.component.type == 'time_series')
    area = trend.model_copy(deep=True)
    area.component.type, area.component.label = 'area', 'Revenue area'
    trend.component.options = {'date_granularity': 'day'}
    blueprint = blueprint.model_copy(update={'rows': blueprint.rows + [area]})
    spec = layout(blueprint, design, plan, FIELDS, **IDENTITY, allowed=set(catalog()), sources=[profiled_source(level)])
    assert {f.name: f.date_granularity for f in spec.datasource.fields if f.date_granularity} == (
        {'order_date': grain} if grain else {})
    charts = [json.loads(line) for line in compile_recipe(spec, 1).splitlines()[1:]]
    charts = [o for o in charts if o['op'] == 'add_chart']
    # Without a bucket fact the trend's own words ("Net revenue by month", 31.1) set its grain, never the
    # model's `day`; the area ("Revenue area") names none. A bucket-start column's grain always wins.
    assert sorted((o['chart_type'], o['options'].get('date_granularity')) for o in charts if o.get('date_dimension')) == [
        ('area', grain), ('time_series', grain or 'month')]
    assert not any('date_granularity' in o['options'] for o in charts if not o.get('date_dimension'))


def test_profiles_without_the_bucket_fact_lay_out_as_before():
    blueprint, design, plan = golden_inputs()
    old = profiled_source(3)
    old['columns'] = [{k: v for k, v in c.items() if k != 'bucket_start'} for c in old['columns']]
    spec = layout(blueprint, design, plan, FIELDS, **IDENTITY, allowed=set(catalog()), sources=[old])
    assert spec.model_dump_json(indent=2) == golden_layout()


def test_base_grains_follow_the_view_projection():
    """A join shows the first source's column of a name; a union shows every branch's (a missing
    one is NULL), so it keeps the finest grain they share. Names are the view's snake_case names."""
    from dss.artifacts.models import Join, JoinKey, ViewSources
    from dss.spec.auto_layout import base_grains

    def source(sid, **grains):
        return {'id': sid, 'columns': [{'name': n.replace('_', ' ').title() if n == 'order_date' else n, 'bq_type': 'DATE',
                                        **({} if g == 'old' else {'bucket_start': g})} for n, g in grains.items()]}
    a = source('s_a', order_date='year', shipped='month', paid=None, legacy='old')
    b = source('s_b', order_date='month', shipped='year', paid='year', legacy='year', closed='quarter')
    union = ViewSources(base='s_a', joins=[], union=['s_b'])
    assert base_grains([a, b], union) == {'order_date': 'month', 'shipped': 'month', 'closed': 'quarter'}
    join = ViewSources(base='s_a', joins=[Join(source_id='s_b', on=[JoinKey(left='order_date', right='order_date')])], union=[])
    assert base_grains([a, b], join) == {'order_date': 'year', 'shipped': 'month', 'closed': 'quarter'}
    assert base_grains([a, b], ViewSources(base='s_b', joins=[], union=[])) == {
        'order_date': 'month', 'shipped': 'year', 'paid': 'year', 'legacy': 'year', 'closed': 'quarter'}
