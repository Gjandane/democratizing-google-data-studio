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
