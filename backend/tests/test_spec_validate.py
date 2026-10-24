import copy
import json
import random
from pathlib import Path
import pytest
from dss.spec.validate import validate_spec, catalog


def sample():
    return json.loads(Path('tests/data/thin_spec.json').read_text())


def test_golden_errors():
    spec = sample()
    spec['pages'][0]['components'][0]['metrics'][0]['field'] = 'missing'
    assert validate_spec(spec) == [{'path': 'pages.0.components.0.metrics.0', 'message': 'Unknown datasource field'}]
    spec = sample()
    spec['pages'][0]['components'][1]['grid']['col'] = 1
    assert validate_spec(spec) == [{'path': 'pages.0.components.1.grid', 'message': 'Components must not overlap'}]
    assert validate_spec(sample(), high_priority=['q1']) == [{'path': 'pages.0.components', 'message': 'High-priority question q1 must be referenced'}]


def test_seeded_properties(monkeypatch):
    monkeypatch.delenv('DSS_ALLOWED_TYPES', raising=False)
    rng = random.Random(7)
    for _ in range(50):
        spec = sample()
        first, second, note = spec['pages'][0]['components']
        first['grid'] = dict(col=rng.randint(1,7), row=rng.randint(1,4), w=rng.randint(2,6), h=rng.randint(3,7))
        second['grid'] = dict(col=rng.randint(1,7), row=rng.randint(15,18), w=6, h=rng.randint(8,12))
        note['grid']['row'] = rng.randint(33,38)
        assert not validate_spec(spec)
        for mutation in ('overlap', 'field', 'catalog', 'allowed', 'pages', 'counts'):
            bad = copy.deepcopy(spec)
            items = bad['pages'][0]['components']
            allowed = set(catalog())
            if mutation == 'overlap':
                items[1]['grid'] = copy.deepcopy(items[0]['grid'])
            elif mutation == 'field':
                items[0]['metrics'][0]['field'] = 'unknown_' + str(rng.randrange(999))
            elif mutation == 'catalog':
                items[0]['type'] = 'unsupported'
            elif mutation == 'allowed':
                allowed.remove('scorecard')
            elif mutation == 'pages':
                bad['pages'].append(copy.deepcopy(bad['pages'][0]))
            else:
                items[0]['metrics'] *= rng.randint(2, 10)
            assert validate_spec(bad, allowed=allowed), mutation


def test_catalog_is_source_of_limits(tmp_path):
    root = Path('knowledge/catalog')
    for p in root.glob('*.md'):
        (tmp_path / p.name).write_text(p.read_text())
    p = tmp_path / 'scorecard.md'
    p.write_text(p.read_text().replace('max_metrics: 1', 'max_metrics: 2'))
    spec = sample()
    spec['pages'][0]['components'][0]['metrics'] *= 2
    assert validate_spec(spec)
    assert not validate_spec(spec, catalog_root=tmp_path)


@pytest.mark.parametrize('mutation', ['role','date','ids','prefix','bounds','size','height','sort'])
def test_semantic_constraints(mutation):
    spec = sample()
    c = spec['pages'][0]['components'][0]
    if mutation == 'role': c['metrics'][0]['field'] = 'region'
    if mutation == 'date': c.update(type='time_series', date_dimension='region')
    if mutation == 'ids': c['id'] = 'p1_regions'
    if mutation == 'prefix': c['id'] = 'p2_revenue'
    if mutation == 'bounds': c['grid']['col'] = 12
    if mutation == 'size': c['grid']['w'] = 1
    if mutation == 'height': spec['pages'][0]['height'] = 1000
    if mutation == 'sort': c['sort'] = {'field':'missing'}
    assert validate_spec(spec)


def test_multiline_high_priority_questions():
    from dss.spec.validate import high_questions
    text = '- q1: Revenue\nby month? (priority: high)\n- q2: Customers? (priority: low)\n- q3: Margin? (priority: high)'
    assert high_questions(text) == ['q1', 'q3']


def charted(kind):
    """thin_spec with its bar retyped; time series bind a date and no grouping dimensions."""
    spec = sample()
    spec['datasource']['fields'].append({'name': 'sale_date', 'type': 'DATE', 'label': 'Date', 'role': 'dimension'})
    c = spec['pages'][0]['components'][1]
    c['type'] = kind
    if kind == 'time_series':
        c.update(dimensions=[], date_dimension='sale_date')
    return spec, c


@pytest.mark.parametrize('kind', ['bar', 'table', 'time_series'])
@pytest.mark.parametrize('order', ['asc', 'desc'])
def test_valid_sort_orders(kind, order):
    spec, c = charted(kind)
    for field in ('revenue', 'sale_date', 'region'):
        c['sort'] = {'field': field, 'order': order}
        assert validate_spec(spec, allowed=catalog()) == []
    c.pop('sort')
    assert validate_spec(spec, allowed=catalog()) == []


@pytest.mark.parametrize('sort', [
    {'field': 'revenue'}, {'order': 'asc'}, {'field': '', 'order': 'asc'},
    {'field': 'revenue', 'order': 'up'}, {'field': 'revenue', 'order': 'ASC'}, {'field': 'revenue', 'order': None},
    {'field': 'revenue', 'direction': 'asc'}, {'field': 'revenue', 'order': 'asc', 'direction': 'desc'},
    {'field': 'revenue', 'order': 'asc', 'nulls': 'last'}, {'field': 1, 'order': 'asc'},
    'revenue', ['revenue', 'asc'], {'field': 'missing', 'order': 'asc'}])
def test_malformed_sort_fails(sort):
    spec, c = charted('bar')
    c['sort'] = sort
    errors = validate_spec(spec, allowed=catalog())
    assert errors and all(e['path'].startswith('pages.0.components.1.sort') for e in errors), errors


def test_unknown_component_field_fails():
    spec, c = charted('table')
    c['sort_order'] = 'asc'
    assert validate_spec(spec, allowed=catalog()) == [{'path': 'pages.0.components.1.sort_order', 'message': 'Extra inputs are not permitted'}]


def test_provider_schema_carries_the_sort_contract():
    from dss.spec.models import DashboardSpec
    schema = DashboardSpec.model_json_schema()
    assert schema['$defs']['Sort']['required'] == ['field', 'order']
    assert schema['$defs']['Sort']['properties']['order']['enum'] == ['asc', 'desc']
    assert schema['$defs']['Sort']['additionalProperties'] is False
    assert {'$ref': '#/$defs/Sort'} in schema['$defs']['Component']['properties']['sort']['anyOf']


THEME_COLORS = ('background', 'surface', 'text', 'muted', 'accent', 'palette')
BAD_COLORS = ('123456', '#abc', '#GG1234', '#12345678', 'red', '#123456\n', 123456, None)


@pytest.mark.parametrize('field', THEME_COLORS)
@pytest.mark.parametrize('color', BAD_COLORS)
@pytest.mark.parametrize('as_model', [False, True])
def test_theme_color_constraints(field, color, as_model):
    from dss.spec.models import DashboardSpec
    spec = sample()
    if as_model:
        spec = DashboardSpec.model_validate(spec)
        if field == 'palette':
            spec.theme.palette[1] = color
        else:
            setattr(spec.theme, field, color)
    else:
        spec.setdefault('theme', {})[field] = ['#aBc123', color] if field == 'palette' else color
    errors = validate_spec(spec)
    assert [e['path'] for e in errors] == ['theme.' + field + ('.1' if field == 'palette' else '')]
    assert all(set(e) == {'path', 'message'} for e in errors)


def test_theme_defaults_and_mixed_case_match_provider_schema():
    from dss.spec.models import DashboardSpec, Theme
    from jsonschema import Draft202012Validator
    assert validate_spec(sample()) == []
    theme = {field: ['#abcdef', '#ABCDEF', '#aBc123'] if field == 'palette' else '#aBc123'
             for field in THEME_COLORS}
    spec = sample()
    spec['theme'] = theme
    assert validate_spec(spec) == []
    assert Theme.model_validate(theme).palette == theme['palette']
    schema = DashboardSpec.model_json_schema()
    colors = schema['$defs']['Theme']['properties']
    for field in THEME_COLORS:
        rule = colors[field]['items'] if field == 'palette' else colors[field]
        assert rule['pattern'] == '^#[0-9A-Fa-f]{6}$'
        assert rule['minLength'] == rule['maxLength'] == 7
    Draft202012Validator(schema).validate(spec)


@pytest.mark.parametrize('kind,text,width,rows,style,fits', [
    ('title', 'Sales overview', 12, 2, {}, False),  # final audit reproduction
    ('title', 'Sales overview', 12, 3, {}, True),
    ('title', 'Sales overview', 12, 2, {'font_size': 16}, True),
    ('title', 'Sales overview', 12, 4, {'font-size': '40px', 'font-weight': 'bold'}, True),
    ('title', 'Sales overview', 12, 4, {'font_size': 60}, False),
    ('title', 'Sales\noverview', 12, 3, {}, False),
    ('title', 'Sales\noverview', 12, 5, {}, True),
    ('title', 'Weekly regional revenue performance overview ' * 3, 3, 4, {}, False),
    ('title', 'Weekly regional revenue performance overview ' * 3, 3, 35, {}, True),
    ('title', 'W' * 100, 2, 4, {}, False),
    ('title', 'W' * 100, 2, 35, {}, True),
    ('subtitle', 'Regional revenue', 12, 2, {}, True),
    ('subtitle', 'Regional\nrevenue', 12, 2, {}, False),
    ('subtitle', 'Regional\nrevenue', 12, 4, {}, True),
    ('subtitle', 'Regional revenue', 12, 2, {'font_size': '32px'}, False),
    ('text', 'Regional revenue', 12, 2, {}, False),
    ('text', 'Regional revenue', 12, 4, {}, True),
])
def test_decoration_content_bounds(kind, text, width, rows, style, fits):
    spec = sample()
    spec['pages'][0]['decorations'][0].update(kind=kind, text=text, style=style,
        grid=dict(col=1, row=1, w=width, h=rows))
    errors = validate_spec(spec)
    assert (errors == []) == fits, errors
    if not fits:
        assert errors[0]['path'] == 'pages.0.decorations.0.grid'
        assert 'text does not fit' in errors[0]['message']


@pytest.mark.parametrize('style', [
    {'font_size': True}, {'font_size': -1}, {'font_size': 0}, {'font_size': '120%'},
    {'font_size': 'large'}, {'font_size': '1px;color:red'}, {'font_size': float('inf')},
    {'font_weight': 'bolder'}, {'font-weight': 123},
])
def test_invalid_decoration_font_is_a_validation_diagnostic(style):
    spec = sample()
    spec['pages'][0]['decorations'][0]['style'] = style
    assert [e['path'] for e in validate_spec(spec)] == ['pages.0.decorations.0.style']


def multipage(count):
    """thin_spec plus copies of its page; later pages carry only components (one text check)."""
    spec = sample()
    for index in range(2, count + 1):
        page = copy.deepcopy(spec['pages'][0])
        page.update(index=index, name=f'Section {index}', decorations=[])
        for c in page['components']:
            c['id'] = c['id'].replace('p1_', f'p{index}_', 1)
        spec['pages'].append(page)
    return spec


@pytest.mark.parametrize('count', [1, 2, 3, 4, 5])
def test_one_to_five_pages_are_valid(count):
    assert validate_spec(multipage(count), allowed=catalog()) == []


def test_six_pages_are_rejected():
    assert validate_spec(multipage(6), allowed=catalog()) == [
        {'path': 'pages', 'message': 'List should have at most 5 items after validation, not 6'}]


@pytest.mark.parametrize('mutation,expected', [
    ('index', [{'path': 'pages.2.index', 'message': 'Page indexes must be 1..n in order'}]),
    ('prefix', [{'path': 'pages.1.components.0.id', 'message': 'ID must use the page prefix p2_'}]),
    ('duplicate', [{'path': 'pages.1.components.1.id', 'message': 'IDs must be unique'}]),
    ('overlap', [{'path': 'pages.1.components.1.grid', 'message': 'Components must not overlap'}]),
    ('short', [{'path': 'pages.2.components.2.grid', 'message': 'Grid box is outside the canvas or has no area'}]),
    ('tall', []),
])
def test_page_rules_apply_to_every_page(mutation, expected):
    spec = multipage(3)
    second, third = spec['pages'][1], spec['pages'][2]
    if mutation == 'index':
        third['index'] = 2
    elif mutation == 'prefix':
        second['components'][0]['id'] = 'p1_revenue_copy'
    elif mutation == 'duplicate':
        second['components'][1]['id'] = 'p2_revenue'
    elif mutation == 'overlap':
        second['components'][1]['grid']['col'] = 1
    elif mutation == 'short':
        third['height'] = 500  # the note ends at 508 px; later pages own their height
    else:
        third['height'] = 2000
        third['components'][2]['grid']['row'] = 80  # below the 900 px canvas, inside page 3
    assert validate_spec(spec, allowed=catalog()) == expected


def test_question_ref_coverage_applies_to_layout_output_not_revise_patches():
    golden = Path('tests/data/golden_layout_spec.json').read_text(encoding='utf-8')
    rows = json.loads(Path('tests/data/golden_blueprint.json').read_text(encoding='utf-8'))['rows']
    refs = [r['question_id'] for r in rows if r['status'] == 'ok' and r['question_id']]
    assert validate_spec(json.loads(golden), allowed=catalog(), question_refs=refs) == []
    for page, index, ref, count in ((1, 3, 'q8', 1), (0, 2, 'q1', 3)):
        spec = json.loads(golden)
        removed = spec['pages'][page]['components'].pop(index)  # "Remove this chart"
        assert removed['question_ref'] == ref
        # Revise validates a patch without question_refs: a removal is allowed (decisions.md records it).
        assert validate_spec(spec, allowed=catalog()) == []
        assert validate_spec(spec, allowed=catalog(), question_refs=refs) == [
            {'path': 'pages', 'message': f'Blueprint question {ref} needs {count} component(s) with question_ref {ref}'}]


@pytest.mark.parametrize('label, expected', [
    ("Total Population (M)','Total Nominal GDP (USD M) - Population", 'Total Population (M)'),
    ("['Total Sales', 'Orders']", 'Total Sales'),
    ('["Revenue"]', 'Revenue'),
    ("'Revenue'", 'Revenue'),
    ('Revenue"', 'Revenue'),
    ('"Revenue', 'Revenue'),
    ("', 'Orders", 'Orders'),
    ('Revenue\nby region', 'Revenue by region'),
    ("Sales 'Q1' by region", "Sales 'Q1' by region"),
    ('Revenue [USD]', 'Revenue [USD]'),
    ("['', '']", None),
    ('"', None),
])
def test_label_text_keeps_the_first_clean_fragment(label, expected):
    from dss.spec.validate import label_text
    assert label_text(label) == expected


@pytest.mark.parametrize('label', ["Total Population (M)','Total Nominal GDP", '["Revenue"]', "Revenue'", 'Two\nlines'])
def test_labels_with_list_quote_syntax_or_lines_fail_validation(label):
    spec = sample()
    spec['pages'][0]['components'][0]['label'] = label
    assert validate_spec(spec) == [{'path': 'pages.0.components.0.label',
                                    'message': 'Label must be one line without list or quote syntax'}]
    spec['pages'][0]['components'][0]['label'] = "Sales 'Q1'"
    assert not validate_spec(spec)


def designed():
    return json.loads(Path('tests/data/designed_spec.json').read_text(encoding='utf-8'))


def test_designed_spec_validates_and_serializes_unchanged():
    from dss.spec.models import DashboardSpec
    text = Path('tests/data/designed_spec.json').read_text(encoding='utf-8')
    spec = designed()
    assert spec['canvas']['width'] == 1440 and spec['pages'][0]['design']['html']
    assert [d['id'] for d in spec['pages'][0]['decorations']] == ['p1_design', 'p1_synthetic_sample_data']
    assert all(c['box'] for c in spec['pages'][0]['components'])
    assert validate_spec(spec, allowed=catalog()) == []
    assert DashboardSpec.model_validate_json(text).model_dump_json(indent=2) + '\n' == text
    # Code-laid specs keep their bytes: no `box`/`design` keys appear when they are absent.
    golden = Path('tests/data/golden_layout_spec.json').read_text(encoding='utf-8')
    assert DashboardSpec.model_validate_json(golden).model_dump_json(indent=2) == golden


def _designed_mutation(mutation):
    from dss.render.design_page import minimum
    spec = designed()
    page = spec['pages'][0]
    items = page['components']
    if mutation == 'box_without_design':
        spec = sample()
        spec['pages'][0]['components'][0]['box'] = dict(x=24, y=80, w=300, h=100)
        return spec, [{'path': 'pages.0.components.0.box',
                       'message': "A box needs the page's design: box and design appear together"}]
    if mutation == 'design_missing_box':
        del items[2]['box']
        return spec, [{'path': 'pages.0.components.2.box', 'message': 'A component on a designed page needs its measured box'}]
    if mutation == 'design_without_decoration':
        page['decorations'] = page['decorations'][1:]
        return spec, [{'path': 'pages.0.decorations', 'message': 'A designed page needs exactly one design decoration p1_design'}]
    if mutation == 'decoration_without_design':
        del page['design']
        for item in items:
            del item['box']
        return spec, [{'path': 'pages.0.decorations', 'message': "A design decoration needs the page's design"}]
    if mutation == 'overlap':
        items[1]['box'] = dict(items[0]['box'], x=items[0]['box']['x'] + 100)
        return spec, [{'path': 'pages.0.components.1.box', 'message': 'Components must not overlap'}]
    if mutation == 'small':
        need_w, need_h = minimum('table', 1440)
        items[6]['box'].update(w=need_w - 1, h=need_h - 1)
        return spec, [{'path': 'pages.0.components.6.box.w', 'message': f'Minimum w is {need_w} px at canvas width 1440'},
                      {'path': 'pages.0.components.6.box.h', 'message': f'Minimum h is {need_h} px at canvas width 1440'}]
    if mutation == 'outside':
        items[3]['box']['x'] = 1300  # 1300 + 240 > 1440
        return spec, [{'path': 'pages.0.components.3.box', 'message': 'Box is outside the 1440 x 1312 px page'}]
    if mutation == 'below':
        items[7]['box']['y'] = 1100  # 1100 + 240 > 1312
        return spec, [{'path': 'pages.0.decorations', 'message': 'Layout overlaps the reserved Synthetic sample data label'},
                      {'path': 'pages.0.components.7.box', 'message': 'Box is outside the 1440 x 1312 px page'}]
    if mutation == 'footer':
        items[7]['box']['y'] = 1000  # inside the page, but into the reserved footer at 1224-1288
        return spec, [{'path': 'pages.0.decorations', 'message': 'Layout overlaps the reserved Synthetic sample data label'}]
    width = int(mutation.removeprefix('width_'))
    spec['canvas']['width'] = width
    bound = 'greater than or equal to 1200' if width < 1200 else 'less than or equal to 1920'
    return spec, [{'path': 'canvas.width', 'message': f'Input should be {bound}'}]


@pytest.mark.parametrize('mutation', ['box_without_design', 'design_missing_box', 'design_without_decoration',
                                      'decoration_without_design', 'overlap', 'small', 'outside', 'below',
                                      'footer', 'width_1199', 'width_1921'])
def test_designed_page_errors(mutation):
    spec, expected = _designed_mutation(mutation)
    assert validate_spec(spec, allowed=catalog()) == expected


@pytest.mark.parametrize('width', [1200, 1920])
def test_canvas_width_bounds_are_inclusive(width):
    spec = designed()
    spec['canvas']['width'] = width
    errors = validate_spec(spec, allowed=catalog())
    assert not any(e['path'] == 'canvas.width' for e in errors)


def recipe_13():
    from test_render import recipe_13_spec
    return recipe_13_spec().model_dump(warnings=False)


def test_recipe_13_types_are_allowed_by_default_and_narrowing_rejects_them(monkeypatch):
    """24.1: with DSS_ALLOWED_TYPES unset (env and root .env) the catalog allows area and fixed_size_list;
    a list without them (the pre-1.3 default) rejects them and keeps the 100% stacked bar."""
    monkeypatch.delenv('DSS_ALLOWED_TYPES', raising=False)
    monkeypatch.setattr('dss.spec.validate.dotenv_values', lambda path: {})
    from dss.spec.models import TYPES
    from dss.spec.validate import allowed_types
    assert allowed_types() == set(TYPES) == set(catalog()) >= {'area', 'fixed_size_list'}
    assert validate_spec(recipe_13()) == []
    monkeypatch.setenv('DSS_ALLOWED_TYPES', 'scorecard,time_series,bar,pie,table,pivot_table,geo_map,scatter,text,image,date_range,dropdown')
    message = 'Component type is not allowed by the catalog and DSS_ALLOWED_TYPES'
    assert validate_spec(recipe_13()) == [{'path': 'pages.0.components.0.type', 'message': message},
                                          {'path': 'pages.0.components.2.type', 'message': message}]


@pytest.mark.parametrize('mutation, path, message', [
    ('list_without_field', 'pages.0.components.2.field', 'A fixed_size_list field is required'),
    ('list_on_a_metric', 'pages.0.components.2.field', 'Field role is not allowed in this slot'),
    ('list_with_metrics', 'pages.0.components.2.metrics', 'Expected 0..0 metrics'),
    ('list_too_short', 'pages.0.components.2.grid.h', 'Minimum h is 4'),
    ('area_without_date', 'pages.0.components.0.date_dimension', 'A date dimension is required'),
    ('area_on_a_string', 'pages.0.components.0.date_dimension', 'Date dimension must have a date or timestamp type'),
    ('area_with_dimensions', 'pages.0.components.0.dimensions', 'Expected 0..0 dimensions'),
    ('area_narrow', 'pages.0.components.0.grid.w', 'Minimum w is 6')])
def test_recipe_13_slot_rules(mutation, path, message):
    spec = recipe_13()
    area, _, listed = spec['pages'][0]['components']
    if mutation == 'list_without_field': listed['field'] = None
    if mutation == 'list_on_a_metric': listed['field'] = 'revenue'
    if mutation == 'list_with_metrics': listed['metrics'] = [{'field': 'revenue', 'agg': 'sum'}]
    if mutation == 'list_too_short': listed['grid']['h'] = 3
    if mutation == 'area_without_date': area['date_dimension'] = None
    if mutation == 'area_on_a_string': area['date_dimension'] = 'region'
    if mutation == 'area_with_dimensions': area['dimensions'] = ['region']
    if mutation == 'area_narrow': area['grid']['w'] = 5
    assert validate_spec(spec, allowed=catalog()) == [{'path': path, 'message': message}]
