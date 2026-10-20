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
