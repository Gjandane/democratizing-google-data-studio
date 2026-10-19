import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import struct
import threading
import time

import pytest

from dss.harness.nodes.render import artifacts, perform
from dss.render import background
from dss.render.prototype import aggregate_data, aggregate_sql, chart_option, render
from dss.spec.layout import box
from dss.spec.models import DashboardSpec


@pytest.fixture
def dashboard():
    return DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())


class FakeBigQuery:
    def __init__(self, delay=0):
        self.queries = []
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.delay = delay

    def aggregate(self, sql):
        with self.lock:
            self.queries.append(sql)
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return [{'region': 'West', 'm0': 12345.5}, {'region': 'East', 'm0': 4000}]


class ContractParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.stack = []
        self.items = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'data-cid' in attrs:
            assert not any(self.stack), 'Nested data-cid'
            assert attrs['data-cid'] not in self.items, 'Duplicate data-cid'
            self.items[attrs['data-cid']] = attrs
        if tag not in ('meta', 'img', 'input', 'br', 'link'):
            self.stack.append('data-cid' in attrs)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


def test_html_contract_geometry_layers(dashboard):
    for layer in ('all', 'decoration'):
        parsed = ContractParser(render(dashboard, layer=layer))
        items = dashboard.pages[0].decorations + dashboard.pages[0].components
        assert len(parsed.items) == len(items)
        for item in items:
            attrs = parsed.items[item.id]
            assert attrs['data-label']
            assert attrs['data-kind'] in ('component', 'decoration')
            b = box(dashboard.canvas, dashboard.grid, item.grid, height=dashboard.pages[0].height)
            for prop, key in [('left','x'),('top','y'),('width','w'),('height','h')]:
                assert f'{prop}:{b[key]}px' in attrs['style']
            assert ('display:none' in attrs['style']) == (layer == 'decoration' and attrs['data-kind'] == 'component')
        if layer == 'decoration':
            assert '<script' not in render(dashboard, layer=layer)


def test_cache_layout_revision_and_parallel_budget(dashboard, tmp_path):
    base = dashboard.pages[0].components[0]
    dashboard.pages[0].components = []
    dashboard.datasource.fields += [dashboard.datasource.fields[1].model_copy(update={'name': f'revenue{i}'}) for i in range(12)]
    for i in range(12):
        item = copy.deepcopy(base)
        item.id = f'p1_kpi_{i}'
        item.metrics[0].field = f'revenue{i}'
        item.grid.col, item.grid.row, item.grid.w, item.grid.h = (i % 4)*3 + 1, (i // 4)*8 + 5, 3, 6
        dashboard.pages[0].components.append(item)
    service = FakeBigQuery(.1)
    start = time.monotonic()
    data = aggregate_data(dashboard, service, tmp_path)
    html = render(dashboard, data=data)
    assert time.monotonic() - start < 15
    assert len(service.queries) == 12 and 2 <= service.peak <= 8
    assert html.count('12,345.50') == 12
    assert aggregate_data(dashboard, service, tmp_path) == data
    dashboard.spec_version += 1
    dashboard.pages[0].components[0].grid.row += 1
    aggregate_data(dashboard, service, tmp_path)
    assert len(service.queries) == 12
    aggregate_data(dashboard, service, tmp_path / 'v2')
    assert len(service.queries) == 24


def test_sql_aggregation_bounds_sort(dashboard):
    c = dashboard.pages[0].components[1]
    c.breakdown = 'revenue'
    c.metrics[0].agg = 'count_distinct'
    c.sort = {'field': 'revenue', 'direction': 'asc'}
    sql = aggregate_sql(dashboard, c)
    assert 'COUNT(DISTINCT `revenue`) AS `m0`' in sql
    assert 'GROUP BY `region`, `revenue`' in sql
    assert sql.endswith('ORDER BY `m0` ASC LIMIT 50')
    c.type = 'pivot_table'
    assert aggregate_sql(dashboard, c).endswith('LIMIT 20')
    c.sort['direction'] = 'desc; DROP TABLE x'
    with pytest.raises(ValueError):
        aggregate_sql(dashboard, c)
    c.sort = None
    c.dimensions = ['region`; SELECT *']
    with pytest.raises(ValueError):
        aggregate_sql(dashboard, c)


def test_empty_escaping_catalog_and_theme(dashboard, monkeypatch):
    dashboard.title = '</title><script>bad()</script>'
    dashboard.pages[0].components[1].label = 'A' * 500 + '</script>'
    dashboard.theme.surface = '#FFF0AA'
    html = render(dashboard, data={'p1_regions': [{'region':'</script><script>bad()</script>', 'm0': 4}]})
    assert 'No data' in html and '#FFF0AA' in html
    assert '<script>bad()' not in html
    assert '\\u003c/script' in html and 'title="AAAA' in html
    monkeypatch.setattr('dss.render.prototype.catalog', lambda: {})
    with pytest.raises(ValueError, match='catalog'):
        render(dashboard)


def test_geography_and_date_binding(dashboard):
    from dss.spec.models import DataField
    dashboard.datasource.fields.append(DataField(name='place', type='GEOGRAPHY', label='Place', role='dimension'))
    dashboard.datasource.fields.append(DataField(name='date', type='DATE', label='Date', role='dimension'))
    score = dashboard.pages[0].components[0]
    score.date_dimension = 'date'
    assert 'GROUP BY' not in aggregate_sql(dashboard, score)
    c = dashboard.pages[0].components[1]
    c.type, c.dimensions, c.date_dimension = 'geo_map', ['place'], 'date'
    sql = aggregate_sql(dashboard, c)
    assert 'ST_ASGEOJSON(ST_CENTROID(`place`)) AS `place`' in sql
    assert 'GROUP BY ST_ASGEOJSON(ST_CENTROID(`place`))' in sql
    assert '`date`' not in sql
    rows = [{'place':'{"type":"Point","coordinates":[121.0,14.6]}','m0':9}]
    option = chart_option(c, rows, dashboard.theme, 550)
    assert option['series'][0]['coordinateSystem'] == 'geo'
    assert option['series'][0]['data'][0]['value'] == [121.0,14.6,9]
    c.sort = {'field':'region'}
    assert 'ORDER BY ANY_VALUE(`region`)' in aggregate_sql(dashboard, c)


@pytest.mark.parametrize('kind', ['time_series','bar','pie','table','pivot_table','geo_map','scatter'])
def test_each_echarts_type(dashboard, kind):
    c = dashboard.pages[0].components[1]
    c.type = kind
    c.dimensions = ['region', 'category'] if kind == 'pivot_table' else ['region']
    c.metrics += [c.metrics[0].model_copy()]
    if kind == 'time_series':
        c.dimensions = []
        c.date_dimension = 'region'
        c.breakdown = 'category'
    rows = [{'region':'West','category':'A','m0':7,'m1':2}, {'region':'West','category':'B','m0':8,'m1':3}]
    option = chart_option(c, rows, dashboard.theme, 550)
    if kind in ('table','pivot_table'):
        assert option['graphic'] and '7' in json.dumps(option)
        if kind == 'pivot_table':
            assert 'A / revenue' in json.dumps(option)
    else:
        assert option['series'][0]['type'] == {'time_series':'line','geo_map':'map'}.get(kind, kind)
    if kind == 'time_series':
        assert len(option['series']) == 4
        assert option['series'][0]['data'] == [7]


def test_capture_and_artifact_order(dashboard, tmp_path, monkeypatch):
    captured = []
    def fake_capture(html, path, width, height):
        parsed = ContractParser(html)
        assert all('display:none' in a['style'] for a in parsed.items.values() if a['data-kind'] == 'component')
        captured.append((width, height))
        path.write_bytes(b'PNG')
    monkeypatch.setattr(background, 'capture', fake_capture)
    artifacts(dashboard, FakeBigQuery(), tmp_path)
    assert captured == [(1200, 900)]
    assert (tmp_path / 'background_p1.png').read_bytes() == b'PNG'
    assert '12,345.50' in (tmp_path / 'prototype.html').read_text(encoding='utf-8')


async def test_render_node_events_and_api(client, app, build_id, dashboard, tmp_path, monkeypatch):
    from dss.harness.tracing import Trace
    from dss.db import new_id
    from test_plan import events
    config = app.state.settings.get()
    folder = config.data_dir / 'builds' / build_id / 'v1'
    folder.mkdir(parents=True)
    (folder / 'spec.json').write_text(dashboard.model_dump_json())
    monkeypatch.setattr(background, 'capture', lambda html, path, w, h: path.write_bytes(b'PNG'))
    run_id = new_id('r')
    trace = Trace(app.state.db, run_id, build_id, 'render')
    await perform(app.state.harness, build_id, run_id, {'config':config,'factory':lambda c: FakeBigQuery()}, trace)
    assert ('prototype.updated', {'spec_version':1}) in events(app, build_id)
    assert ('stage.changed', {'stage':'prototype'}) in events(app, build_id)
    assert client.get(f'/api/builds/{build_id}').json()['stage'] == 'prototype'
    html = client.get(f'/api/builds/{build_id}/prototype').text
    assert '12,345.50' in html
    assert all('display:none' in a['style'] for a in ContractParser(client.get(f'/api/builds/{build_id}/prototype?layer=decoration').text).items.values() if a['data-kind'] == 'component')


async def test_render_failure_does_not_publish_or_log_secrets(client, app, build_id, monkeypatch, caplog):
    from test_plan import seed, PLAN, FakeLLM, FakeBigQuery, events
    from dss.harness.guardrails import RunError
    docs = seed(app, build_id)
    def fail(*args):
        raise RuntimeError('test-key private-provider-diagnostic')
    monkeypatch.setattr(background, 'capture', fail)
    with pytest.raises(RunError, match='Prototype rendering failed'):
        await app.state.harness.run('plan', build_id,
            {'config':app.state.settings.get(), 'factory':lambda c:FakeBigQuery()}, llm=FakeLLM(response=json.dumps(PLAN)))
    assert not any(k == 'prototype.updated' for k, _ in events(app, build_id))
    assert client.get(f'/api/builds/{build_id}').json()['stage'] == 'interview'
    assert not (docs.parent / 'prototype.html').exists()
    assert 'private-provider-diagnostic' not in caplog.text
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT status FROM traces').fetchall()
    assert len(traces) == 1 and traces[0][0] == 'error'


@pytest.mark.live
def test_real_background_dimensions(dashboard, tmp_path):
    path = tmp_path / 'background_p1.png'
    background.capture(render(dashboard, layer='decoration'), path, 1200, 900)
    assert struct.unpack('>II', path.read_bytes()[16:24]) == (1200, 900)


@pytest.mark.live
def test_twelve_component_full_render_budget(dashboard, tmp_path):
    base = dashboard.pages[0].components[0]
    dashboard.pages[0].components = []
    for i in range(12):
        item = copy.deepcopy(base)
        item.id = f'p1_kpi_{i}'
        item.grid.col, item.grid.row, item.grid.w, item.grid.h = (i % 4)*3+1, (i // 4)*8+5, 3, 6
        item.metrics[0].field = f'revenue{i}'
        dashboard.datasource.fields.append(dashboard.datasource.fields[1].model_copy(update={'name':f'revenue{i}'}))
        dashboard.pages[0].components.append(item)
    service = FakeBigQuery(.1)
    start = time.monotonic()
    artifacts(dashboard, service, tmp_path)
    elapsed = time.monotonic()-start
    print(f'12 components plus actual Chromium background: {elapsed:.2f}s; queries={len(service.queries)}')
    assert elapsed < 15
    assert len(service.queries) == 12
    artifacts(dashboard, service, tmp_path)
    assert len(service.queries) == 12
