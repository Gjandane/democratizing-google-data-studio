from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

from google.cloud import bigquery
import pytest

from dss.config import Config
from dss.data.bigquery import BigQuery
from dss.data.profile import profile_table, prompt_text


def stats(values, *, nulls=0, distinct=None, minimum=None, maximum=None, invalid_dates=0):
    return {'null_count': nulls, 'distinct_count': distinct if distinct is not None else len(values),
            'value_counts': [{'value': value, 'count': count} for value, count in values],
            'min_value': minimum, 'max_value': maximum, 'invalid_dates': invalid_dates}


class FakeBigQuery:
    """Adapter-boundary fake. Rejects any non-aggregate query or row-fetch API."""
    config = Config(gcp_project_id='test-project')

    def __init__(self, schema, aggregates):
        self.client = Mock(spec=['get_table', 'query'])
        self.client.get_table.return_value = SimpleNamespace(schema=schema)
        self.client.query.side_effect = self.query
        self.aggregates = aggregates

    def query(self, sql, **kwargs):
        assert sql.startswith('SELECT COUNT(*) AS row_count,')
        assert 'APPROX_COUNT_DISTINCT(' in sql and 'APPROX_TOP_COUNT(' in sql
        assert 'ARRAY_AGG' not in sql and 'SELECT *' not in sql
        return SimpleNamespace(result=lambda **_: [self.aggregates])


def test_all_values_top_five_and_no_row_fetch():
    low = [(f'category-{i}', i + 1) for i in range(20)]
    high = [(f'value-{i}', 100 - i) for i in range(24)]
    service = FakeBigQuery([bigquery.SchemaField('category', 'STRING'), bigquery.SchemaField('customer', 'STRING')],
        {'row_count': 1000, 'c0': stats(low), 'c1': stats(high, distinct=200)})
    profile = profile_table(service, 'test-project.demo.sales')
    category, customer = profile['columns']
    assert category['values_complete'] and len(category['values']) == 20
    assert {v['value'] for v in category['values']} == {v[0] for v in low}
    assert not customer['values_complete'] and customer['values'] == [
        {'value': f'value-{i}', 'count': 100-i} for i in range(5)]
    assert customer['sample'] == ['value-5', 'value-6', 'value-7']
    assert service.client.query.call_count == 1
    assert 'test-project.demo.sales' in service.client.query.call_args.args[0]
    # An approximate distinct count slightly below the actual count doesn't lose value 21.
    service.aggregates['c0'] = stats(high[:21], distinct=20)
    assert not profile_table(service, 'test-project.demo.sales')['columns'][0]['values_complete']


def test_null_types_ranges_and_date_like():
    schema = [bigquery.SchemaField('empty', 'NUMERIC'), bigquery.SchemaField('amount', 'INTEGER'),
              bigquery.SchemaField('day', 'DATE'), bigquery.SchemaField('date_text', 'STRING'),
              bigquery.SchemaField('items', 'RECORD', mode='REPEATED'), bigquery.SchemaField('bytes', 'BYTES'),
              bigquery.SchemaField('place', 'GEOGRAPHY'), bigquery.SchemaField('payload', 'JSON')]
    aggregates = {'row_count': 10, 'c0': stats([(None, 10)], nulls=10),
        'c1': stats([('2', 7)], nulls=3, minimum=2, maximum=2),
        'c2': stats([('2026-01-01', 10)], minimum='2026-01-01', maximum='2026-01-01'),
        'c3': stats([('01/03/2026', 10)], minimum='2026-01-03', maximum='2026-01-03'),
        **{f'c{i}': stats([('a', 10)]) for i in range(4, 8)}}
    service = FakeBigQuery(schema, aggregates)
    profile = profile_table(service, 'test-project.demo.sales')
    empty, number, day, date_text = profile['columns'][:4]
    assert empty['type'] == 'number' and empty['sample'] == empty['values'] == []
    assert 'empty number all null' in prompt_text(profile)
    assert number['null_pct'] == 30 and number['min'] == number['max'] == '2'
    assert day['type'] == 'date' and date_text['date_like'] and date_text['min'] == '2026-01-03'
    sql = service.client.query.call_args.args[0]
    for expression in ('TO_JSON_STRING(`items`)', 'TO_BASE64(`bytes`)', 'ST_ASTEXT(`place`)', 'TO_JSON_STRING(`payload`)', 'SAFE.PARSE_DATE'):
        assert expression in sql
    aggregates['c3']['invalid_dates'] = 1
    assert not profile_table(service, 'test-project.demo.sales')['columns'][3]['date_like']


def wide_profile(n):
    return {'row_count': 2000, 'columns': [
        {'name': f'column_{i+1}', 'type': 'string', 'null_pct': 5, 'distinct_count': 20,
         'values': [{'value': ('売上 café \\ newline\n' * 8) + str(j), 'count': 100-j} for j in range(20)],
         'sample': ['sample one', 'sample two', 'sample three'], 'values_complete': True,
         'min': None, 'max': None} for i in range(n)]}


def test_prompt_determinism_and_measured_budget():
    profile = wide_profile(30)
    original = deepcopy(profile)
    text = prompt_text(profile)
    # Conservative UTF-8 bound, stronger than the project's offline chars/4 estimate.
    assert len(text.encode('utf-8')) <= 6000 and len(text) / 4 <= 6000
    assert text == prompt_text(json.loads(json.dumps(profile))) and profile == original
    for col in profile['columns']:
        col['values'].reverse()
        col['sample'].reverse()
    assert text == prompt_text(profile)
    assert len(text.splitlines()) == 31
    assert all(f'column_{i} string' in text for i in range(1, 31))
    assert 'samples=' not in text and 'top=' in text


def test_sixty_columns_only_name_type_after_forty():
    profile = wide_profile(60)
    lines = prompt_text(profile).splitlines()
    assert lines[41:] == [f'column_{i} string' for i in range(41, 61)]
    assert all('distinct~20' in line for line in lines[1:41])


def test_profile_truncates_values_and_preserves_flexible_names():
    service = FakeBigQuery([bigquery.SchemaField('a`b', 'STRING')],
        {'row_count': 2, 'c0': stats([('x' * 100, 2)])})
    profile = BigQuery(service.config, client=service.client).profile('test-project.demo.sales')
    assert len(profile['columns'][0]['values'][0]['value']) == 60
    assert profile['columns'][0]['name'] == 'a`b'
    assert '`a\\`b`' in service.client.query.call_args.args[0]
    service.aggregates['row_count'] = 0
    with pytest.raises(Exception, match='Source could not be loaded'):
        profile_table(service, 'test-project.demo.sales')
